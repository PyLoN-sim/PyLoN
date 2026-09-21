using System;
using System.Collections.Generic;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using PyLoN.Domain.Control;
using UnityEngine;
using static PyLoN.JsonPacketWriter;

namespace PyLoN
{
    [Serializable]
    public sealed class PyLoNSeparationQuery
    {
        public string operationId, operationInstance, operationEpoch, operationVesselId;
    }

    public sealed partial class PyLoNVehicleManager
    {
        // Survives flight scene teardown, topology changes, vessel switching and lease loss.
        // A process restart deliberately starts a new journal and instance identity.
        private static readonly SeparationResultJournal SeparationResults = new SeparationResultJournal();
        private readonly List<PendingSeparation> pendingSeparations = new List<PendingSeparation>();
        private float nextSeparationResults;

        private sealed class PendingSeparation
        {
            internal SeparationResultJournal.Result Result;
            internal PartModule Module;
            internal Part[] OriginalParts;
            internal bool CompletionObserved;
        }

        private void ApplySeparationOperation(PyLoNActuatorCommand command)
        {
            if (!command.separate) return;
            RuntimeSession.Observe();
            var name = PyLoNMotorNames.Sanitize(command.name, "actuator");
            string operation = string.IsNullOrEmpty(command.operationId) ? LegacySeparationId(command, name) : command.operationId;
            string originalInstance = string.IsNullOrEmpty(command.operationInstance) ? RuntimeSession.InstanceId : command.operationInstance;
            string originalEpoch = string.IsNullOrEmpty(command.operationEpoch) ? RuntimeSession.Epoch : command.operationEpoch;
            string originalVessel = string.IsNullOrEmpty(command.operationVesselId) ? command.vesselId : command.operationVesselId;
            if (!ValidOperationToken(operation) || !ValidOperationToken(originalInstance) ||
                !ValidOperationToken(originalEpoch) || !ValidOperationToken(originalVessel))
            {
                Warn("Dropped separation command with invalid operation identity");
                return;
            }
            double now = Time.realtimeSinceStartup;
            var previous = SeparationResults.Find(originalInstance, originalEpoch, originalVessel, operation, now);
            if (previous != null)
            {
                // Receipt replay is read-only and works with a replacement lease, but
                // an ID may never silently select a different actuator or controller.
                if (previous.ActuatorId == name && previous.ControllerId == command.controllerId)
                    SendSeparationResult(previous);
                else SendSeparationRejection(command, operation, originalInstance, originalEpoch, originalVessel, "operation_id_conflict");
                return;
            }
            if (originalInstance != RuntimeSession.InstanceId || originalEpoch != RuntimeSession.Epoch ||
                originalVessel != RuntimeSession.VesselId)
            {
                SendSeparationRejection(command, operation, originalInstance, originalEpoch, originalVessel, "original_session_not_current");
                return;
            }
            string rejection = "control_unavailable";
            if (!TargetsActiveVessel(command.vesselId) || control == null ||
                !AcceptVehicleCommand(command.controllerId, command.leaseId, command.sequence,
                    "separation:" + name, out rejection))
            {
                SendSeparationRejection(command, operation, originalInstance, originalEpoch, originalVessel, rejection);
                return;
            }
            var result = NewSeparationResult(command, operation, originalInstance, originalEpoch, originalVessel);
            if (!SeparationResults.TryAdd(result, now))
            {
                SendSeparationRejection(command, operation, originalInstance, originalEpoch, originalVessel, "result_journal_full");
                return;
            }
            foreach (var module in parts.Separations())
            {
                string targetName = PyLoNActuatorNames.For(VesselParts.SeparationMechanism(module), module.part,
                    PyLoNActuatorNames.ModuleIndex(module.part, module));
                if (targetName != name) continue;
                if (!VesselParts.SeparationAvailable(module))
                {
                    CompleteSeparation(result, false, "actuator_unavailable", new string[0]);
                    return;
                }
                var pending = new PendingSeparation { Result = result, Module = module,
                    OriginalParts = vessel.parts.ToArray() };
                pendingSeparations.Add(pending);
                try
                {
                    var decoupler = module as ModuleDecouplerBase;
                    var clamp = module as LaunchClamp;
                    var fairing = module as ModuleProceduralFairing;
                    if (decoupler != null) decoupler.Decouple();
                    else if (clamp != null) clamp.Release();
                    else if (fairing != null) fairing.DeployFairing();
                    pending.CompletionObserved = VesselParts.SeparationComplete(module);
                }
                catch (Exception exception)
                {
                    pendingSeparations.Remove(pending);
                    CompleteSeparation(result, false, "separation_exception", ResultingVessels(pending.OriginalParts));
                    Warn("Separation operation failed: " + exception.Message);
                    return;
                }
                // Encode under the post-action envelope. The pending receipt is
                // repeated after the bridge has received the new session heartbeat.
                RuntimeSession.Observe();
                SendSeparationResult(result);
                nextManifestTime = 0f;
                if (actuatorTelemetry != null) actuatorTelemetry.Reset();
                return;
            }
            CompleteSeparation(result, false, "actuator_not_found", new string[0]);
        }

        private void PollSeparationOperations()
        {
            double now = Time.realtimeSinceStartup;
            for (int index = pendingSeparations.Count - 1; index >= 0; index--)
            {
                var pending = pendingSeparations[index];
                if (pending.Module != null && pending.Module.part != null)
                    pending.CompletionObserved |= VesselParts.SeparationComplete(pending.Module);
                // Give KSP at least one update to finish assigning the detached parts
                // to vessels. Disappearance by itself never proves success.
                double elapsed = now - pending.Result.CreatedAt;
                if (elapsed < 0.1 || (!pending.CompletionObserved && elapsed < 2)) continue;
                var ids = ResultingVessels(pending.OriginalParts);
                CompleteSeparation(pending.Result, pending.CompletionObserved,
                    pending.CompletionObserved ? "separated" : "completion_not_observed", ids);
                pendingSeparations.RemoveAt(index);
            }
            if (now < nextSeparationResults) return;
            nextSeparationResults = (float)now + 0.5f;
            foreach (var result in SeparationResults.Snapshot(now))
                if (!result.Completed || now - result.CompletedAt < 10) SendSeparationResult(result);
        }

        private void CancelPendingSeparationOperations()
        {
            foreach (var pending in pendingSeparations)
                CompleteSeparation(pending.Result, false, "flight_scene_ended_before_result", ResultingVessels(pending.OriginalParts));
            pendingSeparations.Clear();
        }

        private void QuerySeparationOperation(PyLoNSeparationQuery query)
        {
            if (query == null || !ValidOperationToken(query.operationId) || !ValidOperationToken(query.operationInstance) ||
                !ValidOperationToken(query.operationEpoch) || !ValidOperationToken(query.operationVesselId)) return;
            var result = SeparationResults.Find(query.operationInstance, query.operationEpoch, query.operationVesselId,
                query.operationId, Time.realtimeSinceStartup);
            if (result == null)
            {
                result = new SeparationResultJournal.Result { OperationId = query.operationId, Instance = query.operationInstance,
                    OriginalEpoch = query.operationEpoch, OriginalVesselId = query.operationVesselId,
                    Completed = true, Reason = "result_not_retained", CompletedAt = Time.realtimeSinceStartup };
            }
            SendSeparationResult(result);
        }

        private void CompleteSeparation(SeparationResultJournal.Result result, bool success, string reason, string[] vessels)
        {
            RuntimeSession.Observe();
            result.Completed = true;
            result.Success = success;
            result.Reason = reason;
            result.ResultEpoch = RuntimeSession.Epoch;
            result.ResultGeneration = RuntimeSession.Generation;
            result.ActiveVesselId = RuntimeSession.VesselId;
            result.ResultingVesselIds = vessels;
            result.CompletedAt = Time.realtimeSinceStartup;
            SendSeparationResult(result);
        }

        private static string[] ResultingVessels(Part[] originalParts)
        {
            var ids = new SortedSet<string>(StringComparer.Ordinal);
            foreach (var part in originalParts)
                if (part != null && part.vessel != null) ids.Add(part.vessel.id.ToString("N"));
            var result = new string[ids.Count];
            ids.CopyTo(result);
            return result;
        }

        private static SeparationResultJournal.Result NewSeparationResult(PyLoNActuatorCommand command,
            string operation, string originalInstance, string originalEpoch, string originalVessel)
        {
            return new SeparationResultJournal.Result { OperationId = operation, Instance = originalInstance,
                OriginalEpoch = originalEpoch, OriginalVesselId = originalVessel,
                OriginalGeneration = originalInstance == RuntimeSession.InstanceId && originalEpoch == RuntimeSession.Epoch ? RuntimeSession.Generation : 0,
                ActuatorId = PyLoNMotorNames.Sanitize(command.name, "actuator"), ControllerId = command.controllerId,
                Sequence = command.sequence };
        }

        private void SendSeparationRejection(PyLoNActuatorCommand command, string operation, string originalInstance,
            string originalEpoch, string originalVessel, string reason)
        {
            var result = NewSeparationResult(command, operation, originalInstance, originalEpoch, originalVessel);
            CompleteSeparation(result, false, reason, new string[0]);
        }

        private void SendSeparationResult(SeparationResultJournal.Result result)
        {
            RuntimeSession.Observe();
            var builder = new StringBuilder(1024);
            builder.Append('{');
            AppendString(builder, "type", "pylon_separation_result", true);
            AppendNumber(builder, "version", 1L);
            AppendString(builder, "operationId", result.OperationId);
            AppendString(builder, "operationInstance", result.Instance);
            AppendString(builder, "operationEpoch", result.OriginalEpoch);
            AppendString(builder, "operationVesselId", result.OriginalVesselId);
            AppendNumber(builder, "originalGeneration", result.OriginalGeneration);
            AppendString(builder, "name", result.ActuatorId);
            AppendString(builder, "controllerId", result.ControllerId);
            AppendNumber(builder, "sequence", result.Sequence);
            AppendBoolean(builder, "completed", result.Completed);
            AppendBoolean(builder, "success", result.Success);
            AppendBoolean(builder, "retained", result.Retained);
            AppendString(builder, "reason", result.Reason);
            AppendString(builder, "resultEpoch", result.ResultEpoch);
            AppendNumber(builder, "resultGeneration", result.ResultGeneration);
            AppendString(builder, "activeVesselId", result.ActiveVesselId);
            AppendNumber(builder, "retentionRemainingSeconds", !result.Retained ? 0 : result.Completed
                ? Math.Max(0, SeparationResults.RetentionSeconds - (Time.realtimeSinceStartup - result.CompletedAt))
                : SeparationResults.RetentionSeconds);
            Prefix(builder, "resultingVesselIds", false);
            builder.Append('[');
            for (int index = 0; index < result.ResultingVesselIds.Length; index++)
            {
                if (index != 0) builder.Append(',');
                JsonString(builder, result.ResultingVesselIds[index]);
            }
            builder.Append("]}");
            Send(builder.ToString());
        }

        private static bool ValidOperationToken(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > 128) return false;
            foreach (char c in value) if (c < 33 || c > 126) return false;
            return true;
        }

        private static string LegacySeparationId(PyLoNActuatorCommand command, string name)
        {
            string input = (command.controllerId ?? "") + "\n" + (command.leaseId ?? "") + "\n" + name + "\n" +
                command.sequence.ToString(CultureInfo.InvariantCulture);
            using (var hash = SHA256.Create())
                return "legacy-" + BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(input))).Replace("-", "").ToLowerInvariant();
        }
    }
}
