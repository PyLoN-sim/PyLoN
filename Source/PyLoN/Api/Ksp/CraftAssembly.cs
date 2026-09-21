using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace PyLoN
{
    /// <summary>Builds an isolated part tree and delegates .craft serialization to KSP.</summary>
    internal static class CraftAssembly
    {
        public static void Build(CraftSpecification spec, string requestId, CraftBuilderResult result)
        {
            if (HighLogic.CurrentGame.Mode != Game.Modes.SANDBOX)
                throw new ArgumentException("Craft builder currently supports Sandbox saves only.");
            var ordered = spec.Validate();
            var available = new Dictionary<string, AvailablePart>(StringComparer.Ordinal);
            foreach (var item in ordered)
            {
                var info = PartLoader.getPartInfoByName(item.part);
                if (info == null || info.partPrefab == null)
                    throw new ArgumentException("Part is not installed: " + item.part + " (" + item.id + ")");
                available.Add(item.id, info);
            }
            // Validate all attachment points on the prefabs before instantiating anything.
            foreach (var item in ordered)
            {
                if (string.IsNullOrEmpty(item.parent)) continue;
                var child = available[item.id].partPrefab;
                var parent = available[item.parent].partPrefab;
                if (item.attach.mode == "stack")
                {
                    if (!child.attachRules.stack || !parent.attachRules.allowStack)
                        throw new ArgumentException("Stack attachment is not allowed: " + item.id);
                    FindNode(child, item.attach.node);
                    FindNode(parent, item.attach.parent_node);
                }
                else if (!child.attachRules.srfAttach || !parent.attachRules.allowSrfAttach || child.srfAttachNode == null)
                    throw new ArgumentException("Surface attachment is not allowed: " + item.id);
            }

            var clones = new Dictionary<string, Part>(StringComparer.Ordinal);
            ShipConstruct loaded = null;
            ShipConstruct ship = null;
            ConfigNode previousShipConfig = ShipConstruction.ShipConfig;
            var container = new GameObject("PyLoN craft assembly");
            try
            {
                foreach (var item in ordered)
                {
                    var info = available[item.id];
                    var part = UnityEngine.Object.Instantiate(info.partPrefab, container.transform, false);
                    clones.Add(item.id, part);
                    // Activation runs Unity's normal Awake initialization before KSP saves the part.
                    part.enabled = false;
                    part.gameObject.SetActive(true);
                    foreach (var collider in part.GetComponentsInChildren<Collider>(true)) collider.enabled = false;
                    part.partInfo = info;
                    part.craftID = (uint)clones.Count;
                    part.flagURL = HighLogic.CurrentGame.flagURL;
                    part.parent = null;
                    part.children.Clear();
                    part.symmetryCounterparts.Clear();
                    part.inverseStage = item.stage;
                    part.transform.position = Position(item.position);
                    part.transform.rotation = Rotation(item.rotation);
                }
                foreach (var item in ordered)
                {
                    if (string.IsNullOrEmpty(item.parent)) continue;
                    Part child = clones[item.id], parent = clones[item.parent];
                    child.parent = parent;
                    parent.children.Add(child);
                    // Keep the file's assembly-space pose, including intentional editor offsets.
                    child.transform.SetParent(parent.transform, true);
                    if (item.attach.mode == "stack")
                    {
                        child.attachMode = AttachModes.STACK;
                        FindNode(child, item.attach.node).attachedPart = parent;
                        FindNode(parent, item.attach.parent_node).attachedPart = child;
                    }
                    else
                    {
                        child.attachMode = AttachModes.SRF_ATTACH;
                        child.srfAttachNode.attachedPart = parent;
                    }
                }
                ship = new ShipConstruct(spec.name, "Created by PyLoN craft builder", clones[ordered[0].id]);
                ship.shipFacility = spec.facility == "VAB" ? EditorFacility.VAB : EditorFacility.SPH;
                if (ship.parts.Count != ordered.Count) throw new InvalidOperationException("KSP did not collect the complete part tree.");
                ConfigNode node = ship.SaveShip();
                if (node == null) throw new InvalidOperationException("KSP could not serialize this craft.");

                // A saved file is only accepted after KSP reloads it with the requested tree and poses.
                loaded = new ShipConstruct();
                if (!loaded.LoadShip(node)) throw new InvalidOperationException("KSP could not reload the generated craft.");
                Verify(loaded, ordered);
                result.parts = Inspect(loaded);
                for (int i = 0; i < result.parts.Length; i++)
                {
                    var original = ordered[(int)loaded.parts[i].craftID - 1];
                    result.parts[i].id = original.id;
                    result.parts[i].parent = original.parent ?? "";
                    foreach (var endpoint in result.parts[i].nodes)
                    {
                        if (string.IsNullOrEmpty(endpoint.attachedPart)) continue;
                        int index = int.Parse(endpoint.attachedPart.Substring(1)) - 1;
                        endpoint.attachedPart = ordered[index].id;
                    }
                }
                string folder = Path.Combine(KSPUtil.ApplicationRootPath, "saves", HighLogic.SaveFolder, "Ships", spec.facility);
                Directory.CreateDirectory(folder);
                string path = Path.Combine(folder, "PyLoN_" + requestId + ".craft");
                string temporary = path + ".tmp";
                try
                {
                    node.Save(temporary);
                    if (!File.Exists(temporary)) throw new IOException("KSP did not write the craft file.");
                    File.Move(temporary, path); // Unique name; never overwrite an existing craft.
                }
                finally { if (File.Exists(temporary)) File.Delete(temporary); }
                result.craftPath = path;
            }
            finally
            {
                ShipConstruction.ShipConfig = previousShipConfig;
                if (ship != null && ship.vesselDeltaV != null) UnityEngine.Object.Destroy(ship.vesselDeltaV.gameObject);
                if (loaded != null)
                {
                    if (loaded.vesselDeltaV != null) UnityEngine.Object.Destroy(loaded.vesselDeltaV.gameObject);
                    foreach (var part in loaded.parts)
                        if (part != null) UnityEngine.Object.Destroy(part.gameObject);
                }
                UnityEngine.Object.Destroy(container);
            }
        }

        private static void Verify(ShipConstruct ship, List<CraftPartSpec> ordered)
        {
            if (ship.parts.Count != ordered.Count) throw new InvalidOperationException("Part count changed during KSP reload.");
            var byId = new Dictionary<uint, Part>();
            foreach (var part in ship.parts) byId.Add(part.craftID, part);
            Part root;
            if (!byId.TryGetValue(1, out root)) throw new InvalidOperationException("Root id changed during KSP reload.");
            for (int i = 0; i < ordered.Count; i++)
            {
                var expected = ordered[i];
                Part part;
                if (!byId.TryGetValue((uint)i + 1, out part) || part.partInfo.name != expected.part)
                    throw new InvalidOperationException("Part identity changed during KSP reload: " + expected.id);
                if (part.inverseStage != expected.stage)
                    throw new InvalidOperationException("Stage changed during KSP reload: " + expected.id);
                var position = Quaternion.Inverse(root.transform.rotation) * (part.transform.position - root.transform.position);
                var rotation = Quaternion.Inverse(root.transform.rotation) * part.transform.rotation;
                if (Vector3.Distance(position, Position(expected.position)) > 0.0005f
                    || Quaternion.Angle(rotation, Rotation(expected.rotation)) > 0.05f)
                    throw new InvalidOperationException("Part pose changed during KSP reload: " + expected.id);
                uint parentId = 0;
                for (int j = 0; j < ordered.Count; j++) if (ordered[j].id == expected.parent) parentId = (uint)j + 1;
                if ((part.parent == null ? 0 : part.parent.craftID) != parentId)
                    throw new InvalidOperationException("Parent changed during KSP reload: " + expected.id);
                if (parentId == 0) continue;
                var node = expected.attach.mode == "stack" ? FindNode(part, expected.attach.node) : part.srfAttachNode;
                if (node == null || node.attachedPart != part.parent)
                    throw new InvalidOperationException("Attachment changed during KSP reload: " + expected.id);
                if (expected.attach.mode == "stack" && FindNode(part.parent, expected.attach.parent_node).attachedPart != part)
                    throw new InvalidOperationException("Parent attachment changed during KSP reload: " + expected.id);
            }
        }

        public static CraftPartReport[] Catalog(string filter)
        {
            if (filter != null && filter.Length > 128) throw new ArgumentException("Part filter is too long.");
            var reports = new List<CraftPartReport>();
            foreach (var info in PartLoader.LoadedPartsList)
            {
                if (info == null || info.partPrefab == null) continue;
                if (!string.IsNullOrEmpty(filter) && info.name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0
                    && info.title.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0) continue;
                var report = Report(info.partPrefab);
                report.part = info.name;
                report.title = info.title;
                reports.Add(report);
            }
            reports.Sort((a, b) => string.CompareOrdinal(a.part, b.part));
            return reports.ToArray();
        }

        public static CraftPartReport[] Inspect(ShipConstruct ship)
        {
            var reports = new List<CraftPartReport>();
            if (ship.parts.Count == 0) return reports.ToArray();
            Part root = ship.parts[0];
            foreach (var part in ship.parts) if (part.parent == null) { root = part; break; }
            Quaternion inverse = Quaternion.Inverse(root.transform.rotation);
            foreach (var part in ship.parts)
            {
                var report = Report(part);
                report.id = "p" + part.craftID;
                report.parent = part.parent == null ? "" : "p" + part.parent.craftID;
                report.position = Values(inverse * (part.transform.position - root.transform.position));
                report.rotation = Values(inverse * part.transform.rotation);
                reports.Add(report);
            }
            return reports.ToArray();
        }

        private static CraftPartReport Report(Part part)
        {
            var nodes = new List<CraftNodeReport>();
            foreach (var node in part.attachNodes) if (node != null) nodes.Add(NodeReport(node));
            if (part.srfAttachNode != null)
            {
                var surface = NodeReport(part.srfAttachNode);
                surface.id = "srfAttach";
                nodes.Add(surface);
            }
            return new CraftPartReport
            {
                part = part.partInfo == null ? part.name : part.partInfo.name,
                title = part.partInfo == null ? part.name : part.partInfo.title,
                stage = part.inverseStage, nodes = nodes.ToArray(),
                surfaceAttach = part.attachRules.srfAttach, allowSurfaceAttach = part.attachRules.allowSrfAttach,
                stackAttach = part.attachRules.stack, allowStack = part.attachRules.allowStack
            };
        }

        private static CraftNodeReport NodeReport(AttachNode node)
        {
            return new CraftNodeReport { id = node.id, position = Values(node.position), direction = Values(node.orientation),
                attachedPart = node.attachedPart == null ? "" : "p" + node.attachedPart.craftID };
        }
        private static AttachNode FindNode(Part part, string name)
        {
            var node = part.FindAttachNode(name);
            if (node == null) throw new ArgumentException("Unknown attachment node " + name + " on " + part.partInfo.name);
            return node;
        }
        private static Vector3 Position(double[] v) { return new Vector3((float)v[0], (float)v[1], (float)v[2]); }
        private static Quaternion Rotation(double[] q) { return new Quaternion((float)q[0], (float)q[1], (float)q[2], (float)q[3]).normalized; }
        private static double[] Values(Vector3 v) { return new[] { (double)v.x, v.y, v.z }; }
        private static double[] Values(Quaternion q) { return new[] { (double)q.x, q.y, q.z, q.w }; }
    }
}
