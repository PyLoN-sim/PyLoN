using System.Text;
using UnityEngine;
using static PyLoN.JsonPacketWriter;

namespace PyLoN
{
    public sealed partial class PyLoNVehicleManager
    {
        private float nextHealthTime;

        private void SendVehicleHealth()
        {
            if (vessel == null || Time.realtimeSinceStartup < nextHealthTime) return;
            nextHealthTime = Time.realtimeSinceStartup + 0.5f;
            double totalCharge = 0.0, totalCapacity = 0.0;
            var ut = Planetarium.GetUniversalTime();
            foreach (var part in vessel.parts)
            {
                if (part == null) continue;
                double charge = 0.0, capacity = 0.0;
                foreach (PartResource resource in part.Resources)
                {
                    if (resource.resourceName != "ElectricCharge") continue;
                    charge += resource.amount;
                    capacity += resource.maxAmount;
                }
                totalCharge += charge;
                totalCapacity += capacity;
                // One small packet per part avoids truncating the thermal state
                // of large craft at the UDP datagram size limit.
                var b = BeginHealthPacket("pylon_part_thermal_state", ut);
                AppendNumber(b, "partFlightId", (long)part.flightID);
                AppendNumber(b, "partPersistentId", (long)part.persistentId);
                AppendString(b, "partName", part.partInfo == null ? part.name : part.partInfo.name);
                AppendNumber(b, "temperature", part.temperature);
                AppendNumber(b, "maxTemperature", part.maxTemp);
                AppendNumber(b, "skinTemperature", part.skinTemperature);
                AppendNumber(b, "maxSkinTemperature", part.skinMaxTemp);
                AppendBoolean(b, "shieldedFromAirstream", part.ShieldedFromAirstream);
                AppendNumber(b, "electricCharge", charge);
                AppendNumber(b, "electricCapacity", capacity);
                b.Append('}');
                Send(b.ToString());
            }
            var power = BeginHealthPacket("pylon_vehicle_health", ut);
            AppendNumber(power, "electricCharge", totalCharge);
            AppendNumber(power, "electricCapacity", totalCapacity);
            power.Append('}');
            Send(power.ToString());
        }

        private StringBuilder BeginHealthPacket(string type, double ut)
        {
            var b = new StringBuilder(640);
            b.Append('{');
            AppendString(b, "type", type, true);
            AppendNumber(b, "version", 1);
            AppendString(b, "vesselId", ActiveVesselId());
            AppendNumber(b, "observationSequence", (long)Time.frameCount);
            AppendNumber(b, "universalTime", ut);
            return b;
        }
    }
}
