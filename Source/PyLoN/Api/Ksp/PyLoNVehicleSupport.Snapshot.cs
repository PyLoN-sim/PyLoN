using System.Collections.Generic;
using System.Text;
using UnityEngine;
using static PyLoN.JsonPacketWriter;

namespace PyLoN
{
    public sealed partial class PyLoNVehicleManager
    {
        private bool collectingSnapshot;
        private string snapshotFlight, snapshotEpoch;
        private readonly List<string> snapshotEngines = new List<string>();
        private readonly List<string> snapshotSeparations = new List<string>();

        private void BeginControlSnapshot()
        {
            RuntimeSession.Observe();
            snapshotEpoch = RuntimeSession.Epoch;
            snapshotFlight = null;
            snapshotEngines.Clear();
            snapshotSeparations.Clear();
            collectingSnapshot = true;
        }
        private void CaptureControlSnapshot(string json)
        {
            if (!collectingSnapshot) return;
            if (json.Contains("\"type\":\"pylon_flight_state\"")) snapshotFlight = json;
            else if (json.Contains("\"type\":\"pylon_actuator_state\""))
            {
                if (json.Contains("\"actuatorType\":\"engine\"")) snapshotEngines.Add(json);
                else if (json.Contains("\"actuatorType\":\"separation\"")) snapshotSeparations.Add(json);
            }
        }
        private void EndControlSnapshot()
        {
            collectingSnapshot = false;
            if (snapshotFlight == null || snapshotEpoch != RuntimeSession.Epoch) return;
            var b = new StringBuilder(4096);
            b.Append('{');
            AppendString(b, "type", "pylon_control_snapshot", true);
            AppendNumber(b, "version", 1);
            AppendString(b, "vesselId", ActiveVesselId());
            AppendNumber(b, "observationSequence", Time.frameCount);
            Prefix(b, "flight", false); b.Append(snapshotFlight);
            Prefix(b, "engines", false); b.Append('[').Append(string.Join(",", snapshotEngines.ToArray())).Append(']');
            Prefix(b, "separations", false); b.Append('[').Append(string.Join(",", snapshotSeparations.ToArray())).Append(']');
            b.Append('}');
            // Oversized snapshots are omitted, never truncated into a partial view.
            if (Encoding.UTF8.GetByteCount(b.ToString()) <= 60000) Send(b.ToString());
            else Warn("Control snapshot exceeds the UDP size limit");
        }
    }
}
