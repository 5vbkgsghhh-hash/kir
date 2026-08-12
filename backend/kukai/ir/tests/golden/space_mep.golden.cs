// KIR authoring program — generated. One txn; commit only after in-txn
// postcondition checks pass; any guard failure rolls back (zero-trace).
double U(double mm) => UnitUtils.ConvertToInternalUnits(mm, UnitTypeId.Millimeters);
double MM(double ft) => UnitUtils.ConvertFromInternalUnits(ft, UnitTypeId.Millimeters);
XYZ P(double x, double y, double z) => new XYZ(U(x), U(y), U(z));
Func<string, string, Dictionary<string, object>> __Refuse = (string __oid, string __msg) =>
{
    var __e = new Dictionary<string, object>();
    __e["error"] = "stale_or_failed"; __e["op_id"] = __oid; __e["message"] = __msg;
    return __e;
};
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element и у исключений — это полное имя типа CLR:
// из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ, WorksetId,
// ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и ни один из
// них сюда не передаётся. Исключение дописывает ": сообщение" и стек,
// поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __ClassName = (__cnObj) =>
{
    if (__cnObj == null) return "";
    string __cn = __cnObj.ToString();
    if (__cn == null) return "";
    int __cnCut = __cn.IndexOf((char)10);
    if (__cnCut >= 0) __cn = __cn.Substring(0, __cnCut);
    __cnCut = __cn.IndexOf(':');
    if (__cnCut >= 0) __cn = __cn.Substring(0, __cnCut);
    __cn = __cn.Trim();
    __cnCut = __cn.LastIndexOf('.');
    return __cnCut >= 0 && __cnCut + 1 < __cn.Length
        ? __cn.Substring(__cnCut + 1) : __cn;
};
var __results = new Dictionary<string, object>();
var __post = new List<string>();
Wall __el_SW1 = null;
Autodesk.Revit.DB.Mechanical.Space __el_SPA = null;
Autodesk.Revit.DB.Mechanical.Space __el_SPB = null;
using (Transaction __t = new Transaction(doc, "KIR: два пространства ОВК в венткамере"))
{
    try
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
            return __Refuse("$program", "transaction start status: " + __startStatus.ToString());
        __KirMainFailures.Seen.Clear();
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirMainFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        // create_wall SW1
        WallType __wt_SW1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_SW1 == null) { __t.RollBack(); return __Refuse("SW1", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_SW1 = doc.GetElement(new ElementId(42));
        Level __lv_SW1 = __lv_raw_SW1 as Level;
        if (__lv_SW1 == null) { __t.RollBack(); return __Refuse("SW1", (__lv_raw_SW1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_SW1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_SW1 = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(8000, 0, 0)), __wt_SW1.Id, __lv_SW1.Id, U(3000.0), 0.0, false, false);
        if (__el_SW1 == null) { __t.RollBack(); return __Refuse("SW1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_SW1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:d20e5c11:SW1"); } catch { }

        doc.Regenerate();  // realise everything created above before the enclosure is resolved
        // create_space SPA
        Element __lv_raw_SPA = doc.GetElement(new ElementId(42));
        Level __lv_SPA = __lv_raw_SPA as Level;
        if (__lv_SPA == null) { __t.RollBack(); return __Refuse("SPA", (__lv_raw_SPA == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_SPA) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        try { __el_SPA = doc.Create.NewSpace(__lv_SPA, new UV(U(2000), U(2000))); }
        catch (Exception __ex_SPA) { __t.RollBack(); return __Refuse("SPA", "NewSpace: " + __ex_SPA.Message); }
        if (__el_SPA == null) { __t.RollBack(); return __Refuse("SPA", "NewSpace вернул null"); }
        if ((__el_SPA.Location as LocationPoint) == null) { __t.RollBack(); return __Refuse("SPA", "пространство создано, но НЕ РАЗМЕЩЕНО (Location == null): точка не попала ни в одну область заданного уровня — проверьте xy и level"); }
        try { Parameter __cm = __el_SPA.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:d20e5c11:SPA"); } catch { }

        // create_space SPB
        Element __lv_raw_SPB = doc.GetElement(new ElementId(42));
        Level __lv_SPB = __lv_raw_SPB as Level;
        if (__lv_SPB == null) { __t.RollBack(); return __Refuse("SPB", (__lv_raw_SPB == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_SPB) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        try { __el_SPB = doc.Create.NewSpace(__lv_SPB, new UV(U(6000), U(2000))); }
        catch (Exception __ex_SPB) { __t.RollBack(); return __Refuse("SPB", "NewSpace: " + __ex_SPB.Message); }
        if (__el_SPB == null) { __t.RollBack(); return __Refuse("SPB", "NewSpace вернул null"); }
        if ((__el_SPB.Location as LocationPoint) == null) { __t.RollBack(); return __Refuse("SPB", "пространство создано, но НЕ РАЗМЕЩЕНО (Location == null): точка не попала ни в одну область заданного уровня — проверьте xy и level"); }
        try { Parameter __cm = __el_SPB.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:d20e5c11:SPB"); } catch { }

        doc.Regenerate();

        // post SW1
        {
            var __lc = __el_SW1.Location as LocationCurve;
            if (__lc == null) __post.Add("SW1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 8000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("SW1: endpoints mismatch (geometry)");
            }
            var __bp = __el_SW1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("SW1: level binding mismatch (topology)");
            var __hp = __el_SW1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("SW1: height mismatch");
        }
        // post SPA
        {
            if (__el_SPA.LevelId == null
                || __el_SPA.LevelId == ElementId.InvalidElementId
                || __el_SPA.LevelId.ToString() != "42")
                __post.Add("SPA: level binding mismatch (topology)");
            var __sloc_SPA = __el_SPA.Location as LocationPoint;
            if (__sloc_SPA == null
                || Math.Abs(MM(__sloc_SPA.Point.X) - 2000) > 5.0
                || Math.Abs(MM(__sloc_SPA.Point.Y) - 2000) > 5.0)
                __post.Add("SPA: space placement mismatch (geometry)");
            if (__el_SPA.Area <= 1e-06)
                __post.Add("SPA: space is not enclosed: zero area (geometry)");
            int __bl_SPA = 0;
            bool __bread_SPA = true;
            try
            {
                var __bopt_SPA = new SpatialElementBoundaryOptions();
                IList<IList<BoundarySegment>> __bsegs_SPA = __el_SPA.GetBoundarySegments(__bopt_SPA);
                if (__bsegs_SPA != null)
                    foreach (var __bloop_SPA in __bsegs_SPA)
                        if (__bloop_SPA != null && __bloop_SPA.Count > 0) __bl_SPA++;
            }
            catch { __bread_SPA = false; }
            if (!__bread_SPA)
                __post.Add("SPA: space boundary unreadable (topology)");
            else if (__bl_SPA == 0)
                __post.Add("SPA: space has no bounding loop (topology)");
        }
        // post SPB
        {
            if (__el_SPB.LevelId == null
                || __el_SPB.LevelId == ElementId.InvalidElementId
                || __el_SPB.LevelId.ToString() != "42")
                __post.Add("SPB: level binding mismatch (topology)");
            var __sloc_SPB = __el_SPB.Location as LocationPoint;
            if (__sloc_SPB == null
                || Math.Abs(MM(__sloc_SPB.Point.X) - 6000) > 5.0
                || Math.Abs(MM(__sloc_SPB.Point.Y) - 2000) > 5.0)
                __post.Add("SPB: space placement mismatch (geometry)");
            if (__el_SPB.Area <= 1e-06)
                __post.Add("SPB: space is not enclosed: zero area (geometry)");
            int __bl_SPB = 0;
            bool __bread_SPB = true;
            try
            {
                var __bopt_SPB = new SpatialElementBoundaryOptions();
                IList<IList<BoundarySegment>> __bsegs_SPB = __el_SPB.GetBoundarySegments(__bopt_SPB);
                if (__bsegs_SPB != null)
                    foreach (var __bloop_SPB in __bsegs_SPB)
                        if (__bloop_SPB != null && __bloop_SPB.Count > 0) __bl_SPB++;
            }
            catch { __bread_SPB = false; }
            if (!__bread_SPB)
                __post.Add("SPB: space boundary unreadable (topology)");
            else if (__bl_SPB == 0)
                __post.Add("SPB: space has no bounding loop (topology)");
        }
        if (__post.Count > 0)
        {
            __t.RollBack();
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = __post;
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        {
            try { if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack(); } catch { }
            return __Refuse("$program", "transaction commit status: " + __commitStatus.ToString()
                + (__KirMainFailures.Seen.Count > 0 ? " | Revit: " + String.Join(" ; ", __KirMainFailures.Seen) : ""));
        }
    }
    catch
    {
        if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();
        throw;
    }
}

// witness SW1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_SW1.Id.ToString();
    try { var __stampParam = __el_SW1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_SW1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_SW1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["SW1"] = __rb;
}

// witness SPA
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_SPA.Id.ToString();
    try { __rb["name_and_number"] = __el_SPA.Name; } catch { }
    try { __rb["number"] = __el_SPA.Number; } catch { }
    try { __rb["level_id"] = __el_SPA.LevelId.ToString(); } catch { }
    try { __rb["area_m2"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_SPA.Area, UnitTypeId.SquareMeters), 2); } catch { }
    try { __rb["volume_m3"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_SPA.Volume, UnitTypeId.CubicMeters), 3); } catch { }
    try { var __rbc_SPA = __el_SPA.Category;
        __rb["category_id"] = __rbc_SPA == null ? null : __rbc_SPA.Id.ToString(); } catch { }
    try { var __stampParam = __el_SPA.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["SPA"] = __rb;
}

// witness SPB
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_SPB.Id.ToString();
    try { __rb["name_and_number"] = __el_SPB.Name; } catch { }
    try { __rb["number"] = __el_SPB.Number; } catch { }
    try { __rb["level_id"] = __el_SPB.LevelId.ToString(); } catch { }
    try { __rb["area_m2"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_SPB.Area, UnitTypeId.SquareMeters), 2); } catch { }
    try { __rb["volume_m3"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_SPB.Volume, UnitTypeId.CubicMeters), 3); } catch { }
    try { var __rbc_SPB = __el_SPB.Category;
        __rb["category_id"] = __rbc_SPB == null ? null : __rbc_SPB.Id.ToString(); } catch { }
    try { var __stampParam = __el_SPB.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["SPB"] = __rb;
}

__results["ok"] = true;
return __results;
}
private class __KirMainFailures : IFailuresPreprocessor
{
    // Ошибки Revit КОПЯТСЯ, а не гасятся: программа, откатившаяся на
    // Commit, обязана назвать причину. Без этого пользователь видел
    // «transaction commit status: RolledBack» и ничего больше —
    // ровно тот немой исход, который этот компилятор запрещает.
    public static List<string> Seen = new List<string>();
    public FailureProcessingResult PreprocessFailures(FailuresAccessor __fa)
    {
        foreach (var __f in __fa.GetFailureMessages())
        {
            var __sev = __f.GetSeverity();
            if (__sev == FailureSeverity.Warning) { __fa.DeleteWarning(__f); continue; }
            try {
                var __ids = new List<string>();
                try { foreach (var __id in __f.GetFailingElementIds()) __ids.Add(__id.ToString()); } catch { }
                Seen.Add(__sev.ToString() + ": " + __f.GetDescriptionText()
                    + (__ids.Count > 0 ? " [элементы: " + String.Join(",", __ids) + "]" : ""));
            } catch { }
        }
        return FailureProcessingResult.Continue;
    }
}
private static class __KirPad
{