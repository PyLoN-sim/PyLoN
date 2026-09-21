using System;
using System.Collections.Generic;

namespace PyLoN.Domain.Control
{
    /// <summary>Process-local operation receipts, independent of flight topology and leases.</summary>
    public sealed class SeparationResultJournal
    {
        public sealed class Result
        {
            public string Instance, OperationId, OriginalEpoch, OriginalVesselId;
            public string ControllerId, ActuatorId;
            public long Sequence, OriginalGeneration, ResultGeneration;
            public string ResultEpoch = "", ActiveVesselId = "", Reason = "pending";
            public string[] ResultingVesselIds = new string[0];
            public bool Completed, Success, Retained;
            public double CreatedAt, CompletedAt;
        }

        private readonly List<Result> entries = new List<Result>();
        public readonly int Capacity;
        public readonly double RetentionSeconds;

        public SeparationResultJournal(int capacity = 128, double retentionSeconds = 600)
        {
            if (capacity < 1 || retentionSeconds <= 0 || double.IsNaN(retentionSeconds) || double.IsInfinity(retentionSeconds))
                throw new ArgumentOutOfRangeException();
            Capacity = capacity;
            RetentionSeconds = retentionSeconds;
        }

        public Result Find(string instance, string epoch, string vessel, string operation, double now)
        {
            Prune(now);
            return entries.Find(item => item.Instance == instance && item.OriginalEpoch == epoch &&
                item.OriginalVesselId == vessel && item.OperationId == operation);
        }

        public bool TryAdd(Result result, double now)
        {
            Prune(now);
            if (Find(result.Instance, result.OriginalEpoch, result.OriginalVesselId, result.OperationId, now) != null ||
                entries.Count >= Capacity) return false;
            result.CreatedAt = now;
            result.Retained = true;
            entries.Add(result);
            return true;
        }

        public Result[] Snapshot(double now)
        {
            Prune(now);
            return entries.ToArray();
        }

        private void Prune(double now)
        {
            // Pending operations remain until explicitly resolved. Never evict a live
            // receipt merely to admit a new destructive operation.
            entries.RemoveAll(item => item.Completed && now - item.CompletedAt >= RetentionSeconds);
        }
    }
}
