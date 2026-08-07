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
Wall __el_GRP1__m__W1 = null;
Wall __el_GRP1__m__W2 = null;
Autodesk.Revit.DB.Group __grp_GRP1 = null;
Autodesk.Revit.DB.GroupType __gt_GRP1 = null;
int __placed_GRP1 = 0;
using (Transaction __t = new Transaction(doc, "KIR: типовой этаж как нативная группа"))
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
        // create_group GRP1 — native Revit group (2 members, 2 extra placements)
        // create_wall GRP1__m__W1
        WallType __wt_GRP1__m__W1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_GRP1__m__W1 == null) { __t.RollBack(); return __Refuse("GRP1__m__W1", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_GRP1__m__W1 = doc.GetElement(new ElementId(42));
        Level __lv_GRP1__m__W1 = __lv_raw_GRP1__m__W1 as Level;
        if (__lv_GRP1__m__W1 == null) { __t.RollBack(); return __Refuse("GRP1__m__W1", (__lv_raw_GRP1__m__W1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_GRP1__m__W1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_GRP1__m__W1 = Wall.Create(doc, Line.CreateBound(P(30000, 23000, 0), P(36000, 23000, 0)), __wt_GRP1__m__W1.Id, __lv_GRP1__m__W1.Id, U(3000.0), 0.0, false, false);
        if (__el_GRP1__m__W1 == null) { __t.RollBack(); return __Refuse("GRP1__m__W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1__m__W1"); } catch { }
        // create_wall GRP1__m__W2
        WallType __wt_GRP1__m__W2 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_GRP1__m__W2 == null) { __t.RollBack(); return __Refuse("GRP1__m__W2", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_GRP1__m__W2 = doc.GetElement(new ElementId(42));
        Level __lv_GRP1__m__W2 = __lv_raw_GRP1__m__W2 as Level;
        if (__lv_GRP1__m__W2 == null) { __t.RollBack(); return __Refuse("GRP1__m__W2", (__lv_raw_GRP1__m__W2 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_GRP1__m__W2) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_GRP1__m__W2 = Wall.Create(doc, Line.CreateBound(P(36000, 23000, 0), P(36000, 27000, 0)), __wt_GRP1__m__W2.Id, __lv_GRP1__m__W2.Id, U(3000.0), 0.0, false, false);
        if (__el_GRP1__m__W2 == null) { __t.RollBack(); return __Refuse("GRP1__m__W2", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1__m__W2"); } catch { }
        doc.Regenerate();
        var __members_GRP1 = new List<ElementId>();
            __members_GRP1.Add(__el_GRP1__m__W1.Id);
            __members_GRP1.Add(__el_GRP1__m__W2.Id);
        __grp_GRP1 = doc.Create.NewGroup(__members_GRP1);
        if (__grp_GRP1 == null) { __t.RollBack(); return __Refuse("GRP1", "NewGroup вернул null (члены не образуют группу)"); }
        __gt_GRP1 = __grp_GRP1.GroupType;
        if (__gt_GRP1 == null) { __t.RollBack(); return __Refuse("GRP1", "у созданной группы нет GroupType"); }
        try { __gt_GRP1.Name = "Типовой этаж"; } catch { }
        var __lp0_GRP1 = __grp_GRP1.Location as LocationPoint;
        if (__lp0_GRP1 == null) { __t.RollBack(); return __Refuse("GRP1", "у группы-определения нет LocationPoint (origin)"); }
        XYZ __o0_GRP1 = __lp0_GRP1.Point;
        XYZ __loc_GRP1_0 = new XYZ(__o0_GRP1.X + U(0.0), __o0_GRP1.Y + U(0.0), __o0_GRP1.Z + U(6600.0));
        Autodesk.Revit.DB.Group __pg_GRP1_0 = doc.Create.PlaceGroup(__loc_GRP1_0, __gt_GRP1);
        if (__pg_GRP1_0 == null) { __t.RollBack(); return __Refuse("GRP1", "PlaceGroup вернул null для смещения 0"); }
        __placed_GRP1++;
        try { Parameter __cm = __pg_GRP1_0.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1:0"); } catch { }
        XYZ __loc_GRP1_1 = new XYZ(__o0_GRP1.X + U(0.0), __o0_GRP1.Y + U(0.0), __o0_GRP1.Z + U(13200.0));
        Autodesk.Revit.DB.Group __pg_GRP1_1 = doc.Create.PlaceGroup(__loc_GRP1_1, __gt_GRP1);
        if (__pg_GRP1_1 == null) { __t.RollBack(); return __Refuse("GRP1", "PlaceGroup вернул null для смещения 1"); }
        __placed_GRP1++;
        try { Parameter __cm = __pg_GRP1_1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1:1"); } catch { }
        try { Parameter __cm = __grp_GRP1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1"); } catch { }

        doc.Regenerate();

        // post GRP1
        {
            if (__gt_GRP1 == null || doc.GetElement(__gt_GRP1.Id) == null)
                __post.Add("GRP1: GroupType не материализован");
            else
            {
                int __cnt_GRP1 = 0;
                foreach (Autodesk.Revit.DB.Group __g_GRP1 in __gt_GRP1.Groups) __cnt_GRP1++;
                if (__cnt_GRP1 != 3)
                    __post.Add("GRP1: число экземпляров группы не совпадает (semantic)");
            }
            if (__placed_GRP1 != 2)
                __post.Add("GRP1: размещено не все экземпляры (semantic)");
            if (__gt_GRP1.Name != "Типовой этаж")
                __post.Add("GRP1: имя GroupType не совпадает (semantic)");
            // post GRP1__m__W1
            {
                var __lc = __el_GRP1__m__W1.Location as LocationCurve;
                if (__lc == null) __post.Add("GRP1__m__W1: нет LocationCurve");
                else
                {
                    var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                    double __da = Math.Pow(MM(__a.X) - 30000, 2) + Math.Pow(MM(__a.Y) - 23000, 2);
                    double __db = Math.Pow(MM(__b.X) - 30000, 2) + Math.Pow(MM(__b.Y) - 23000, 2);
                    var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                    if (Math.Abs(MM(__e0.X) - 30000) > 5.0 || Math.Abs(MM(__e0.Y) - 23000) > 5.0 ||
                        Math.Abs(MM(__e1.X) - 36000) > 5.0 || Math.Abs(MM(__e1.Y) - 23000) > 5.0)
                        __post.Add("GRP1__m__W1: endpoints mismatch (geometry)");
                }
                var __bp = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
                if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                    __post.Add("GRP1__m__W1: level binding mismatch (topology)");
                var __hp = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
                if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                    __post.Add("GRP1__m__W1: height mismatch");
            }
            // post GRP1__m__W2
            {
                var __lc = __el_GRP1__m__W2.Location as LocationCurve;
                if (__lc == null) __post.Add("GRP1__m__W2: нет LocationCurve");
                else
                {
                    var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                    double __da = Math.Pow(MM(__a.X) - 36000, 2) + Math.Pow(MM(__a.Y) - 23000, 2);
                    double __db = Math.Pow(MM(__b.X) - 36000, 2) + Math.Pow(MM(__b.Y) - 23000, 2);
                    var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                    if (Math.Abs(MM(__e0.X) - 36000) > 5.0 || Math.Abs(MM(__e0.Y) - 23000) > 5.0 ||
                        Math.Abs(MM(__e1.X) - 36000) > 5.0 || Math.Abs(MM(__e1.Y) - 27000) > 5.0)
                        __post.Add("GRP1__m__W2: endpoints mismatch (geometry)");
                }
                var __bp = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
                if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                    __post.Add("GRP1__m__W2: level binding mismatch (topology)");
                var __hp = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
                if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                    __post.Add("GRP1__m__W2: height mismatch");
            }
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

// witness GRP1__m__W1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_GRP1__m__W1.Id.ToString();
    try { var __stampParam = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_GRP1__m__W1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_GRP1__m__W1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["GRP1__m__W1"] = __rb;
}

// witness GRP1__m__W2
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_GRP1__m__W2.Id.ToString();
    try { var __stampParam = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_GRP1__m__W2.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_GRP1__m__W2.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["GRP1__m__W2"] = __rb;
}

// witness GRP1
{
    var __rb_GRP1 = new Dictionary<string, object>();
    try { if (__grp_GRP1 != null) __rb_GRP1["id"] = __grp_GRP1.Id.ToString(); } catch { }
    try { if (__gt_GRP1 != null) { __rb_GRP1["group_type_id"] = __gt_GRP1.Id.ToString();
        __rb_GRP1["group_type_name"] = __gt_GRP1.Name; } } catch { }
    __rb_GRP1["member_count"] = 2;
    __rb_GRP1["placed_count"] = __placed_GRP1;
    __rb_GRP1["instance_count"] = 3;
    __results["GRP1"] = __rb_GRP1;
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