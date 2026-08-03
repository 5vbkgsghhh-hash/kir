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

// query_count links
var __c_links = new FilteredElementCollector(doc).OfClass(typeof(ImportInstance)).Cast<Element>()
    .Where(e => ((ImportInstance)e).IsLinked)
    .OrderBy(e => __IdOf(e))
    .ToList();
{ var __r = new Dictionary<string, object>(); __r["kind"] = "cad_link"; __r["count"] = __c_links.Count; __results["links"] = __r; }

// query_count imports
var __c_imports = new FilteredElementCollector(doc).OfClass(typeof(ImportInstance)).Cast<Element>()
    .Where(e => !((ImportInstance)e).IsLinked)
    .OrderBy(e => __IdOf(e))
    .ToList();
{ var __r = new Dictionary<string, object>(); __r["kind"] = "cad_import"; __r["count"] = __c_imports.Count; __results["imports"] = __r; }

// query_list views
var __c_views = new FilteredElementCollector(doc).OfClass(typeof(View)).Cast<Element>()
    .Where(e => !((View)e).IsTemplate)
    .OrderBy(e => __IdOf(e))
    .ToList();
{
    var __rows = new List<object>();
    foreach (var __e in __c_views.Take(20))
    {
        var __row = new Dictionary<string, object>();
        __row["id"] = __e.Id.ToString();
        __row["name"] = __NameOf(__e);
        __rows.Add(__row);
    }
    var __r = new Dictionary<string, object>(); __r["kind"] = "view"; __r["total"] = __c_views.Count; __r["returned"] = __rows.Count; __r["rows"] = __rows;
    __results["views"] = __r;
}

// query_inspect probe
var __m___t_probe = new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Element>()
    .Where(e => __NameOf(e).Trim().Equals("Стена-Тест", StringComparison.OrdinalIgnoreCase))
    .OrderBy(e => __IdOf(e))
    .ToList();
Element __t_probe = (__m___t_probe.Count == 1) ? __m___t_probe[0] : null;
if (__t_probe == null)
{
    var __r = new Dictionary<string, object>();
    if (__m___t_probe.Count > 1) { __r["error"] = "ambiguous"; __r["candidates"] = __m___t_probe.Take(5).Select(e => __NameOf(e)).ToList(); }
    else { __r["error"] = "not_found"; }
    __results["probe"] = __r;
}
else
{
    var __row = new Dictionary<string, object>();
        __row["id"] = __t_probe.Id.ToString();
        __row["name"] = __NameOf(__t_probe);
        try { __row["category"] = (__t_probe.Category != null) ? __t_probe.Category.Name : ""; } catch { __row["category"] = ""; }
        __row["type_name"] = __TypeNameOf(__t_probe);
        __row["level_name"] = __LevelNameOf(__t_probe);
    try { var __bb = __t_probe.get_BoundingBox(null); if (__bb != null) {
        var __bbd = new Dictionary<string, object>();
        __bbd["min"] = new double[] { Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Min.X, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Min.Y, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Min.Z, UnitTypeId.Millimeters), 1) };
        __bbd["max"] = new double[] { Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Max.X, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Max.Y, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Max.Z, UnitTypeId.Millimeters), 1) };
        __row["bbox_mm"] = __bbd; } } catch { }
    __results["probe"] = __row;
}

return __results;