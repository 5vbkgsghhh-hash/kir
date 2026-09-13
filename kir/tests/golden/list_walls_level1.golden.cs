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

// query_list walls
var __c_walls = new FilteredElementCollector(doc).OfClass(typeof(Wall)).Cast<Element>()
    .Where(e => __LevelNameOf(e).Trim() == "Этаж 1")
    .OrderBy(e => __IdOf(e))
    .ToList();
{
    var __rows = new List<object>();
    foreach (var __e in __c_walls.Take(50))
    {
        var __row = new Dictionary<string, object>();
        __row["id"] = __e.Id.ToString();
        __row["name"] = __NameOf(__e);
        __row["type_name"] = __TypeNameOf(__e);
        __row["level_name"] = __LevelNameOf(__e);
        __rows.Add(__row);
    }
    var __r = new Dictionary<string, object>(); __r["kind"] = "wall"; __r["total"] = __c_walls.Count; __r["returned"] = __rows.Count; __r["rows"] = __rows;
    __results["walls"] = __r;
}

return __results;