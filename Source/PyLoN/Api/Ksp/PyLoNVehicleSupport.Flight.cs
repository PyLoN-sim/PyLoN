using System;
using System.Text;
using UnityEngine;
using static PyLoN.JsonPacketWriter;

namespace PyLoN
{
    [Serializable]
    public sealed class PyLoNFlightControlCommand
    {
        public string type, vesselId, controllerId, leaseId;
        public int version;
        public long sequence;
        public double pitch, yaw, roll, timeoutSeconds;
        public bool landingGear;
    }

    public sealed partial class PyLoNVehicleManager
    {
        private PyLoNFlightControlCommand flightInput;
        private float flightInputExpires;

        private void ApplyFlightControl(PyLoNFlightControlCommand command)
        {
            if (command == null || !TargetsActiveVessel(command.vesselId) || control == null ||
                !ValidGimbalAxis(command.pitch) || !ValidGimbalAxis(command.yaw) ||
                !ValidGimbalAxis(command.roll) || !IsFinite(command.timeoutSeconds) ||
                command.timeoutSeconds < 0.05 || command.timeoutSeconds > 1.0) return;
            string reason;
            if (!control.Authority.AcceptCommand(command.controllerId, command.leaseId,
                Time.realtimeSinceStartup, command.sequence, out reason)) return;
            // Flight inputs and wrench allocation cannot own the same attitude axes.
            if (wrenchActive)
            {
                wrenchActive = false;
                RestoreBodyEngineStates();
                RestoreRcsActionGroup();
            }
            flightInput = command;
            flightInputExpires = Time.realtimeSinceStartup + (float)command.timeoutSeconds;
            vessel.ActionGroups.SetGroup(KSPActionGroup.Gear, command.landingGear);
        }

        private void SendFlightState()
        {
            if (vessel == null || vessel.mainBody == null || vessel.ReferenceTransform == null) return;
            double fuel = 0, oxidizer = 0, electricity = 0;
            foreach (var part in vessel.parts)
                foreach (PartResource resource in part.Resources)
                {
                    if (resource.resourceName == "LiquidFuel") fuel += resource.amount;
                    else if (resource.resourceName == "Oxidizer") oxidizer += resource.amount;
                    else if (resource.resourceName == "ElectricCharge") electricity += resource.amount;
                }
            var body = vessel.mainBody;
            var radius = body.Radius + vessel.altitude;
            var b = new StringBuilder(1536);
            b.Append('{');
            AppendString(b, "type", "pylon_flight_state", true);
            AppendNumber(b, "version", 1);
            AppendString(b, "vesselId", ActiveVesselId());
            AppendString(b, "bodyName", body.bodyName);
            AppendNumber(b, "universalTime", Planetarium.GetUniversalTime());
            AppendNumber(b, "altitudeAsl", vessel.altitude);
            AppendNumber(b, "altitudeAgl", vessel.heightFromTerrain);
            AppendNumber(b, "latitude", vessel.latitude);
            AppendNumber(b, "longitude", vessel.longitude);
            AppendNumber(b, "mass", vessel.GetTotalMass() * FrameConversions.TonnesToKilograms);
            AppendNumber(b, "liquidFuel", fuel);
            AppendNumber(b, "oxidizer", oxidizer);
            AppendNumber(b, "electricCharge", electricity);
            AppendNumber(b, "gravity", body.gravParameter / (radius * radius));
            AppendNumber(b, "bodyRadius", body.Radius);
            AppendNumber(b, "gravitationalParameter", body.gravParameter);
            AppendNumber(b, "atmosphereDepth", body.atmosphereDepth);
            AppendNumber(b, "apoapsis", vessel.orbit.ApA);
            AppendNumber(b, "periapsis", vessel.orbit.PeA);
            AppendNumber(b, "timeToApoapsis", vessel.orbit.timeToAp);
            AppendNumber(b, "verticalSpeed", vessel.verticalSpeed);
            AppendNumber(b, "horizontalSpeed", vessel.horizontalSrfSpeed);
            AppendNumber(b, "dynamicPressure", 0.5 * vessel.atmDensity * vessel.srf_velocity.sqrMagnitude);
            AppendBoolean(b, "landed", vessel.Landed);
            AppendBoolean(b, "splashed", vessel.Splashed);
            AppendVector(b, "upBody", WorldVectorToBody(vessel.upAxis));
            AppendVector(b, "eastBody", WorldVectorToBody(vessel.east));
            AppendVector(b, "northBody", WorldVectorToBody(vessel.north));
            AppendVector(b, "surfaceVelocityBody", WorldVectorToBody(vessel.srf_velocity));
            AppendVector(b, "orbitalVelocityBody", WorldVectorToBody(vessel.obt_velocity));
            AppendVector(b, "angularVelocityBody", VesselAngularVelocityBody());
            b.Append('}');
            Send(b.ToString());
        }
    }
}
