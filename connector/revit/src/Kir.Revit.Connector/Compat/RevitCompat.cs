using Autodesk.Revit.DB;

namespace Kir.Revit.Connector.Compat
{
    internal static class RevitCompat
    {
        public static long IdValue(ElementId id)
        {
#if REVIT2024 || REVIT_MODERN
            return id.Value;
#else
            return id.IntegerValue;
#endif
        }
    }
}
