// KIR query program — generated; read-only by construction (no txn, no writes).
Func<Element, string> __TypeNameOf = (Element __e) =>
{
    try
    {
        var __tid = __e.GetTypeId();
        if (__tid == null || __tid == ElementId.InvalidElementId) return "";
        var __te = doc.GetElement(__tid);
        return (__te != null && __te.Name != null) ? __te.Name : "";
    }
    catch { return ""; }
};
Func<Element, string> __LevelNameOf = (Element __e) =>
{
    // audit F2: bare Element.LevelId is InvalidElementId for whole categories
    // whose level binding lives in a parameter (the extractor's __ElementLevel
    // proved this with the SAME 4-BIP fallback chain — mirrored here so a
    // level_name filter/field never silently undercounts).
    try
    {
        ElementId __lid = null;
        try { __lid = __e.LevelId; } catch { }
        if (__lid == null || __lid == ElementId.InvalidElementId)
        {
            Parameter __lp = null;
            try { __lp = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT); } catch { }
            if (__lp == null || !__lp.HasValue)
                try { __lp = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM); } catch { }
            if (__lp == null || !__lp.HasValue)
                try { __lp = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM); } catch { }
            if (__lp == null || !__lp.HasValue)
                try { __lp = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM); } catch { }
            if (__lp != null && __lp.HasValue)
                __lid = __lp.AsElementId();
        }
        if (__lid == null || __lid == ElementId.InvalidElementId) return "";
        var __le = doc.GetElement(__lid) as Level;
        return (__le != null && __le.Name != null) ? __le.Name : "";
    }
    catch { return ""; }
};
Func<Element, string> __NameOf = (Element __e) =>
{
    try { return __e.Name ?? ""; } catch { return ""; }
};
Func<Element, long> __IdOf = (Element __e) =>
{
    long __value;
    return (__e != null && long.TryParse(__e.Id.ToString(), out __value))
        ? __value : long.MaxValue;
};
var __results = new Dictionary<string, object>();

// query_count pdf
var __c_pdf = new FilteredElementCollector(doc).OfClass(typeof(ImageInstance)).Cast<Element>()
    .Where(e => __TypeNameOf(e).EndsWith(".pdf", StringComparison.OrdinalIgnoreCase))
    .OrderBy(e => __IdOf(e))
    .ToList();
{ var __r = new Dictionary<string, object>(); __r["kind"] = "pdf_underlay"; __r["count"] = __c_pdf.Count; __results["pdf"] = __r; }

return __results;