// KIR query program — generated; read-only by construction (no txn, no writes).
// 🔴 ТИП ИЗОБРАЖЕНИЯ ЦЕЛИКОМ, А НЕ ЕГО ИМЯ (S-07, 30.08.2026). Признак
// подложки обязан спрашивать РОД (`Source`) и САМ ФАЙЛ (`Path`), потому что имя
// типа редактируется пользователем и Ревит дописывает к нему суффиксы страницы
// («… .pdf - 1») и дубля («… .pdf (2)»). Возвращается `null`, если элемент не
// изображение — вызывающий обязан это проверить.
Func<Element, ImageType> __ImageTypeOf = (Element __e) =>
{
    try
    {
        var __tid = __e.GetTypeId();
        if (__tid == null || __tid == ElementId.InvalidElementId) return null;
        return doc.GetElement(__tid) as ImageType;
    }
    catch { return null; }
};
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
Func<Element, Level> __ElementLevel = (__e) =>
{
    try
    {
        ElementId __levelId = null;
        try { __levelId = __e.LevelId; } catch { }
        if (__levelId == null || __levelId == ElementId.InvalidElementId)
        {
            Func<Parameter, bool> __holdsLevel = (__p) =>
            {
                try
                {
                    if (__p == null || !__p.HasValue) return false;
                    if (__p.StorageType != StorageType.ElementId) return false;
                    var __v = __p.AsElementId();
                    return __v != null && __v != ElementId.InvalidElementId;
                }
                catch { return false; }
            };
            Parameter __levelParam = null;
            try { __levelParam = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM); } catch { }
            if (!__holdsLevel(__levelParam))
                try { __levelParam = __e.get_Parameter(BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM); } catch { }
            if (__holdsLevel(__levelParam))
                __levelId = __levelParam.AsElementId();
        }
        if (__levelId != null && __levelId != ElementId.InvalidElementId)
            return doc.GetElement(__levelId) as Level;
    }
    catch { }
    return null;
};
Func<Element, string> __LevelKey = (__e) =>
{
    var __level = __ElementLevel(__e);
    return __level == null ? "__none__" : __level.Id.ToString();
};
Func<Element, string> __LevelNameOf = (Element __e) =>
{
    // 🔴 ОДИН СУДЬЯ УРОВНЯ НА ВСЁ ДЕРЕВО. До 25.08 здесь стояла СВОЯ цепочка
    // на четыре BuiltInParameter, и её комментарий утверждал «the SAME 4-BIP
    // fallback chain», тогда как авторитет держит СЕМЬ и ветвится иначе
    // (`__holdsLevel`: параметр обязан быть рода ElementId, а не просто
    // иметь значение). Разница видна на балке: копия останавливалась на
    // SCHEDULE_LEVEL_PARAM (HasValue=True, AsElementId=-1) и отдавала пустую
    // строку. Замер 03.08: 2367 балок, 116 лестниц, 21 ограждение с
    // level_id=null — запрос `where level_name=…` молча отбрасывал их все.
    // Теперь цепочка приходит из `revit_read_helpers`, как у экстрактора
    // и у приёмки; своей здесь нет и быть не может.
    var __le = __ElementLevel(__e);
    return (__le != null && __le.Name != null) ? __le.Name : "";
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