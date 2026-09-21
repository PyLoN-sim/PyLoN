using System;
using System.Net.Sockets;
using UnityEngine;

namespace PyLoN
{
    /// <summary>Flight identity is published even with no LiDAR or truth consumer.</summary>
    [KSPAddon(KSPAddon.Startup.Flight, false)]
    public sealed class PyLoNSessionPublisher : MonoBehaviour
    {
        private readonly UdpClient client = new UdpClient();
        private float nextSend;
        public void Update()
        {
            RuntimeSession.Observe();
            if (Time.realtimeSinceStartup < nextSend) return;
            nextSend = Time.realtimeSinceStartup + 0.1f;
            try
            {
                var json = JsonUtility.ToJson(new SessionPacket { type = "pylon_session", version = 1,
                    vesselId = RuntimeSession.VesselId, vesselName = RuntimeSession.VesselName,
                    available = RuntimeSession.Available,
                    universalTime = Planetarium.fetch == null ? 0.0 : Planetarium.GetUniversalTime(),
                    observationSequence = (long)Time.frameCount,
                    realtimeSinceStartup = Time.realtimeSinceStartup,
                    paused = FlightDriver.Pause || Time.timeScale == 0f,
                    packed = FlightGlobals.ActiveVessel != null && FlightGlobals.ActiveVessel.packed,
                    warpRate = TimeWarp.fetch == null ? 1.0 : TimeWarp.CurrentRate,
                    physicsWarp = TimeWarp.fetch != null && TimeWarp.WarpMode == TimeWarp.Modes.LOW });
                var bytes = TelemetryPacketCodec.Encode(json);
                client.Send(bytes, bytes.Length, RuntimeSettings.StateHost, RuntimeSettings.StatePort);
            }
            catch (Exception ex) { Debug.LogWarning("[PyLoN] Session transport: " + ex.Message); }
        }
        public void OnDestroy() { client.Close(); }
        [Serializable] private sealed class SessionPacket
        {
            public string type, vesselId, vesselName;
            public int version;
            public bool available;
            public double universalTime;
            // Frame identity remains meaningful while UT is stopped. Update and
            // realtimeSinceStartup continue while the flight pause menu is open.
            public long observationSequence;
            public double realtimeSinceStartup, warpRate;
            public bool paused, packed, physicsWarp;
        }
    }
}
