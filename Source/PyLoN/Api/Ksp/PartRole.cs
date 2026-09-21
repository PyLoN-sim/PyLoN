namespace PyLoN
{
    internal static class PartRole
    {
        public static string Resolve(Part part)
        { return part == null ? "" : PartRoleMetadata.Read(part.customPartData); }

        public static void Assign(Part part, string role)
        { part.customPartData = PartRoleMetadata.Write(part.customPartData, role); }
    }
}
