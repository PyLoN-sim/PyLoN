using System;
using System.Collections.Generic;
using UnityEngine;

namespace PyLoN
{
    [Serializable]
    public sealed class PyLoNControlBatch
    {
        public string type, vesselId, controllerId, leaseId;
        public int version;
        public long sequence;
        public bool renewLease, suppressSas, hasFlight, hasSeparation;
        public double leaseDurationSeconds;
        public string flightJson, separationJson;
        public string[] engineJson;
        [NonSerialized] public PyLoNFlightControlCommand flight;
        [NonSerialized] public PyLoNActuatorCommand[] engines;
        [NonSerialized] public PyLoNActuatorCommand separation;
    }

    public sealed partial class PyLoNVehicleManager
    {
        private bool applyingControlBatch;

        private bool AcceptVehicleCommand(string controller, string lease, long sequence,
            string stream, out string reason)
        {
            reason = "lease_not_owned";
            if (control == null) return false;
            if (applyingControlBatch) return control.Authority.Owns(controller, lease);
            return control.Authority.AcceptCommand(controller, lease, Time.realtimeSinceStartup,
                sequence, stream, out reason);
        }

        private void ApplyControlBatch(PyLoNControlBatch batch)
        {
            if (batch == null || control == null || !TargetsActiveVessel(batch.vesselId) ||
                !ValidControlBatch(batch)) return;
            string reason;
            if (!control.Authority.AcceptCommand(batch.controllerId, batch.leaseId,
                Time.realtimeSinceStartup, batch.sequence, "batch", out reason))
            {
                SendControlAuthorityState(reason);
                return;
            }
            // One datagram, one main-thread callback. All values are validated
            // first. Separation goes last because it can invalidate the epoch.
            if (batch.renewLease)
            {
                if (!control.Authority.RenewAcceptedCommand(batch.controllerId, batch.leaseId,
                    Time.realtimeSinceStartup, batch.leaseDurationSeconds, batch.suppressSas)) return;
                if (batch.suppressSas) AcquireSasOverride();
                else RestoreSasState();
                SendControlAuthorityState("lease_renewed");
            }
            applyingControlBatch = true;
            try
            {
                if (batch.hasFlight) ApplyFlightControl(batch.flight);
                foreach (var engine in batch.engines) ApplyActuatorCommand(engine);
                if (batch.hasSeparation) ApplyActuatorCommand(batch.separation);
            }
            finally { applyingControlBatch = false; }
        }

        private static bool ValidControlBatch(PyLoNControlBatch batch)
        {
            if (batch.sequence <= 0 || batch.engines == null || batch.engines.Length > 16 ||
                (batch.renewLease && (!IsFinite(batch.leaseDurationSeconds) ||
                 batch.leaseDurationSeconds < .1 || batch.leaseDurationSeconds > 10))) return false;
            if (batch.hasFlight)
            {
                var f = batch.flight;
                if (f == null || !SameBatchIdentity(batch, f.vesselId, f.controllerId, f.leaseId, f.sequence) ||
                    !ValidGimbalAxis(f.pitch) || !ValidGimbalAxis(f.yaw) || !ValidGimbalAxis(f.roll) ||
                    !IsFinite(f.timeoutSeconds) || f.timeoutSeconds < .05 || f.timeoutSeconds > 1) return false;
            }
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var e in batch.engines)
            {
                if (e == null || e.actuatorType != "engine" || string.IsNullOrWhiteSpace(e.name) ||
                    !names.Add(PyLoNMotorNames.Sanitize(e.name, "actuator")) ||
                    !SameBatchIdentity(batch, e.vesselId, e.controllerId, e.leaseId, e.sequence) ||
                    !IsFinite(e.targetThrust) || e.targetThrust < 0 ||
                    !ValidGimbalAxis(e.gimbalPitch) || !ValidGimbalAxis(e.gimbalYaw) || !ValidGimbalAxis(e.gimbalRoll) ||
                    !IsFinite(e.timeoutSeconds) || e.timeoutSeconds < .05 || e.timeoutSeconds > 1) return false;
            }
            var s = batch.separation;
            return !batch.hasSeparation || (s != null && s.actuatorType == "separation" && s.separate &&
                !string.IsNullOrWhiteSpace(s.name) &&
                (string.IsNullOrEmpty(s.operationId) || ValidOperationToken(s.operationId)) &&
                (string.IsNullOrEmpty(s.operationInstance) || ValidOperationToken(s.operationInstance)) &&
                (string.IsNullOrEmpty(s.operationEpoch) || ValidOperationToken(s.operationEpoch)) &&
                (string.IsNullOrEmpty(s.operationVesselId) || ValidOperationToken(s.operationVesselId)) &&
                SameBatchIdentity(batch, s.vesselId, s.controllerId, s.leaseId, s.sequence));
        }

        private static bool SameBatchIdentity(PyLoNControlBatch b, string vessel, string controller, string lease, long sequence)
        {
            return b.vesselId == vessel && b.controllerId == controller && b.leaseId == lease && b.sequence == sequence;
        }
    }
}
