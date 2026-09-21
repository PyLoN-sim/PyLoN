using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace PyLoN
{
    /// <summary>Namespaced metadata within KSP's semicolon-separated customPartData.</summary>
    internal static class PartRoleMetadata
    {
        private const string Prefix = "pylon.role=";

        public static string Read(string data)
        {
            foreach (string field in (data ?? "").Split(';'))
            {
                if (!field.StartsWith(Prefix, StringComparison.Ordinal)) continue;
                string role = field.Substring(Prefix.Length);
                return Valid(role) ? role : "";
            }
            return "";
        }

        public static string Write(string data, string role)
        {
            if (!Valid(role)) throw new ArgumentException("Invalid part role.");
            var fields = new List<string>();
            if (!string.IsNullOrEmpty(data))
                foreach (string field in data.Split(';'))
                    if (!field.StartsWith(Prefix, StringComparison.Ordinal)) fields.Add(field);
            fields.Add(Prefix + role);
            return string.Join(";", fields.ToArray());
        }

        private static bool Valid(string role)
        { return role != null && Regex.IsMatch(role, "\\A[A-Za-z][A-Za-z0-9_-]{0,63}\\z"); }
    }
}
