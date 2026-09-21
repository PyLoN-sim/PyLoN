using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace PyLoN
{
    /// <summary>Explicit editor-space poses; independent of KSP and Unity.</summary>
    public sealed class CraftSpecification
    {
        public int version;
        public string name;
        public string facility;
        public CraftPartSpec[] parts;

        public List<CraftPartSpec> Validate()
        {
            Require(version == 1, "Unsupported craft version (expected 1).");
            Require(!string.IsNullOrWhiteSpace(name) && name.Length <= 80 && name != "." && name != ".."
                && name.IndexOfAny(new[] { '/', '\\' }) < 0, "Invalid craft name.");
            foreach (char c in name) Require(!char.IsControl(c), "Craft name contains a control character.");
            Require(facility == "VAB" || facility == "SPH", "facility must be VAB or SPH.");
            Require(parts != null && parts.Length > 0 && parts.Length <= 256, "Expected 1 to 256 parts.");
            var byId = new Dictionary<string, CraftPartSpec>(StringComparer.Ordinal);
            CraftPartSpec root = null;
            foreach (var part in parts)
            {
                Require(part != null, "Null part.");
                Require(Matches(part.id, "^[A-Za-z][A-Za-z0-9_-]{0,63}$"), "Invalid part id.");
                Require(!byId.ContainsKey(part.id), "Duplicate part id: " + part.id);
                byId.Add(part.id, part);
                Require(Matches(part.part, "^[A-Za-z0-9_.-]{1,128}$"), "Invalid part name: " + part.id);
                Vector(part.position, 3, 1000, part.id + ".position");
                Vector(part.rotation, 4, 2, part.id + ".rotation");
                double norm = 0;
                foreach (double value in part.rotation) norm += value * value;
                Require(Math.Abs(Math.Sqrt(norm) - 1) <= 0.001, "Rotation must be a unit quaternion: " + part.id);
                Require(part.stage >= -1 && part.stage <= 99, "stage must be -1 to 99: " + part.id);
                if (string.IsNullOrEmpty(part.parent))
                {
                    Require(root == null, "Expected exactly one root part.");
                    Require(part.attach == null, "Root cannot have an attachment.");
                    root = part;
                    for (int i = 0; i < 3; i++)
                    {
                        Require(Math.Abs(part.position[i]) <= 1e-6, "Root position must be [0,0,0].");
                        Require(Math.Abs(part.rotation[i]) <= 1e-6, "Root rotation must be [0,0,0,1].");
                    }
                    Require(Math.Abs(part.rotation[3] - 1) <= 1e-6, "Root rotation must be [0,0,0,1].");
                }
                else
                {
                    Require(part.parent != part.id, "Part cannot be its own parent: " + part.id);
                    Require(part.attach != null, "Missing attachment: " + part.id);
                    var a = part.attach;
                    Require(a.mode == "stack" || a.mode == "surface", "Unknown attachment mode: " + part.id);
                    if (a.mode == "stack")
                        Require(NodeName(a.node) && NodeName(a.parent_node), "Stack attachment requires both node names: " + part.id);
                    else
                        Require(a.node == "srfAttach" && string.IsNullOrEmpty(a.parent_node), "Surface attachment requires node=srfAttach and empty parent_node.");
                }
            }
            Require(root != null, "Expected exactly one root part.");
            var occupied = new HashSet<string>(StringComparer.Ordinal);
            foreach (var part in parts)
            {
                if (part == root) continue;
                Require(byId.ContainsKey(part.parent), "Unknown parent: " + part.parent);
                Require(occupied.Add(part.id + ":" + part.attach.node), "Attachment node used twice: " + part.id);
                if (part.attach.mode == "stack")
                    Require(occupied.Add(part.parent + ":" + part.attach.parent_node), "Attachment node used twice: " + part.parent + ":" + part.attach.parent_node);
            }
            // Stable parent-before-child order, accepting forward references in the file.
            var ordered = new List<CraftPartSpec> { root };
            var visited = new HashSet<string>(StringComparer.Ordinal) { root.id };
            while (ordered.Count < parts.Length)
            {
                int before = ordered.Count;
                foreach (var part in parts)
                    if (!visited.Contains(part.id) && part.parent != null && visited.Contains(part.parent))
                    { visited.Add(part.id); ordered.Add(part); }
                Require(ordered.Count > before, "Parts contain a cycle or disconnected component.");
            }
            return ordered;
        }

        private static bool NodeName(string value) { return Matches(value, "^[A-Za-z0-9_.-]{1,64}$"); }
        private static bool Matches(string value, string pattern) { return value != null && Regex.IsMatch(value, pattern.TrimEnd('$') + "\\z"); }
        private static void Vector(double[] value, int length, double bound, string label)
        {
            Require(value != null && value.Length == length, "Wrong vector length: " + label);
            foreach (double item in value)
                Require(!double.IsNaN(item) && !double.IsInfinity(item) && Math.Abs(item) <= bound, "Invalid number: " + label);
        }
        internal static void Require(bool condition, string message)
        { if (!condition) throw new ArgumentException(message); }
    }

    public sealed class CraftPartSpec
    {
        public string id;
        public string part;
        public double[] position;
        public double[] rotation;
        public string parent;
        public CraftAttachmentSpec attach;
        public int stage = -1;
    }

    public sealed class CraftAttachmentSpec
    {
        public string mode;
        public string node;
        public string parent_node;
    }
}
