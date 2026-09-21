using System;
using System.Collections.Generic;

namespace PyLoN
{
    /// <summary>Explicit wire mapping; independent of Unity's nested-object serialization.</summary>
    internal static class CraftBuilderCodec
    {
        public static CraftBuilderRequest ReadRequest(string json)
        {
            var obj = Object(CraftJson.Parse(json), "version,id,session,expiresAt,command,filter,load,spec");
            var request = new CraftBuilderRequest
            {
                version = Integer(obj, "version"), id = Text(obj, "id"), session = Text(obj, "session"),
                expiresAt = Number(obj["expiresAt"]), command = Text(obj, "command"),
                filter = Text(obj, "filter"), load = Boolean(obj, "load")
            };
            if (request.command == "build") request.spec = ReadSpec(obj["spec"]);
            return request;
        }

        private static CraftSpecification ReadSpec(object value)
        {
            var obj = Object(value, "version,name,facility,parts");
            var items = obj["parts"] as List<object>;
            if (items == null || items.Count > 256) throw new ArgumentException("Expected up to 256 parts.");
            var spec = new CraftSpecification
            {
                version = Integer(obj, "version"), name = Text(obj, "name"), facility = Text(obj, "facility"),
                parts = new CraftPartSpec[items.Count]
            };
            for (int i = 0; i < items.Count; i++)
            {
                var item = Object(items[i], "id,part,position,rotation", "parent,attach,stage,autostrut,rigid_attachment,separation_force_percent,role");
                var part = new CraftPartSpec
                {
                    id = Text(item, "id"), part = Text(item, "part"), position = Vector(item["position"], 3),
                    rotation = Vector(item["rotation"], 4), parent = item.ContainsKey("parent") ? Text(item, "parent") : "",
                    stage = item.ContainsKey("stage") ? Integer(item, "stage") : -1
                };
                if (item.ContainsKey("autostrut")) part.autostrut = Text(item, "autostrut");
                if (item.ContainsKey("rigid_attachment")) part.rigid_attachment = Boolean(item, "rigid_attachment");
                if (item.ContainsKey("separation_force_percent")) part.separation_force_percent = Number(item["separation_force_percent"]);
                if (item.ContainsKey("role")) part.role = Text(item, "role");
                if (item.ContainsKey("attach"))
                {
                    var a = Object(item["attach"], "mode,node,parent_node");
                    part.attach = new CraftAttachmentSpec { mode = Text(a, "mode"), node = Text(a, "node"), parent_node = Text(a, "parent_node") };
                }
                spec.parts[i] = part;
            }
            spec.Validate();
            return spec;
        }

        public static string WriteStatus(CraftBuilderStatus status)
        {
            return CraftJson.Stringify(new Dictionary<string, object>
            {
                {"version", status.version}, {"session", status.session}, {"updatedAt", status.updatedAt},
                {"ready", status.ready}, {"facility", status.facility}, {"save", status.save ?? ""}
            });
        }

        public static string WriteResult(CraftBuilderResult result)
        {
            var parts = new List<object>();
            foreach (var p in result.parts)
            {
                var nodes = new List<object>();
                foreach (var n in p.nodes)
                    nodes.Add(new Dictionary<string, object>
                    {
                        {"id", n.id}, {"position", n.position}, {"direction", n.direction}, {"attachedPart", n.attachedPart}
                    });
                parts.Add(new Dictionary<string, object>
                {
                    {"id", p.id ?? ""}, {"part", p.part}, {"title", p.title}, {"parent", p.parent ?? ""},
                    {"position", p.position}, {"rotation", p.rotation}, {"stage", p.stage}, {"nodes", nodes},
                    {"surfaceAttach", p.surfaceAttach}, {"allowSurfaceAttach", p.allowSurfaceAttach},
                    {"stackAttach", p.stackAttach}, {"allowStack", p.allowStack},
                    {"autostrut", p.autostrut}, {"rigid_attachment", p.rigid_attachment},
                    {"separation_force_percent", p.separation_force_percent}, {"role", p.role}
                });
            }
            return CraftJson.Stringify(new Dictionary<string, object>
            {
                {"version", result.version}, {"id", result.id}, {"ok", result.ok}, {"error", result.error},
                {"craftPath", result.craftPath}, {"loaded", result.loaded}, {"parts", parts}
            });
        }

        private static Dictionary<string, object> Object(object value, string required, string optional = "")
        {
            var obj = value as Dictionary<string, object>;
            if (obj == null) throw new ArgumentException("Expected a JSON object.");
            var allowed = new HashSet<string>(required.Split(','), StringComparer.Ordinal);
            foreach (string name in allowed) if (!obj.ContainsKey(name)) throw new ArgumentException("Missing field: " + name);
            if (optional.Length > 0) foreach (string name in optional.Split(',')) allowed.Add(name);
            foreach (string name in obj.Keys) if (!allowed.Contains(name)) throw new ArgumentException("Unknown field: " + name);
            return obj;
        }
        private static string Text(Dictionary<string, object> obj, string key)
        {
            var text = obj[key] as string;
            if (text == null) throw new ArgumentException("Expected string: " + key);
            return text;
        }
        private static bool Boolean(Dictionary<string, object> obj, string key)
        {
            if (!(obj[key] is bool)) throw new ArgumentException("Expected boolean: " + key);
            return (bool)obj[key];
        }
        private static double Number(object value)
        {
            if (value is int) return (int)value;
            if (!(value is double)) throw new ArgumentException("Expected a JSON number.");
            return (double)value;
        }
        private static int Integer(Dictionary<string, object> obj, string key)
        {
            double number = Number(obj[key]);
            if (number != Math.Truncate(number) || number < int.MinValue || number > int.MaxValue)
                throw new ArgumentException("Expected integer: " + key);
            return (int)number;
        }
        private static double[] Vector(object value, int size)
        {
            var list = value as List<object>;
            if (list == null || list.Count != size) throw new ArgumentException("Wrong vector length.");
            var numbers = new double[size];
            for (int i = 0; i < size; i++) numbers[i] = Number(list[i]);
            return numbers;
        }
    }
}
