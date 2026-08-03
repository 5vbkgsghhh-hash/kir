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
var __results = new Dictionary<string, object>();
var __post = new List<string>();
Wall __el_W1 = null;
Autodesk.Revit.DB.Plumbing.Pipe __el_P1 = null;
Grid __el_G1 = null;
using (Transaction __t = new Transaction(doc, "KIR: стена 6м + труба ХВС + ось А"))
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
        // create_wall W1
        WallType __wt_W1 = doc.GetElement(new ElementId(100)) as WallType;
        if (__wt_W1 == null) { __t.RollBack(); return __Refuse("W1", "тип стены не найден (модель изменилась после grounding)"); }
        Element __lv_raw_W1 = doc.GetElement(new ElementId(42));
        Level __lv_W1 = __lv_raw_W1 as Level;
        if (__lv_W1 == null) { __t.RollBack(); return __Refuse("W1", (__lv_raw_W1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_W1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_W1 = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_W1.Id, __lv_W1.Id, U(3000.0), 0.0, false, false);
        if (__el_W1 == null) { __t.RollBack(); return __Refuse("W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:aab4b046:W1"); } catch { }

        // create_pipe P1
        Element __lv_raw_P1 = doc.GetElement(new ElementId(42));
        Level __lv_P1 = __lv_raw_P1 as Level;
        if (__lv_P1 == null) { __t.RollBack(); return __Refuse("P1", (__lv_raw_P1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_P1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_P1 = Autodesk.Revit.DB.Plumbing.Pipe.Create(doc, new ElementId(300), new ElementId(200), __lv_P1.Id, P(0, 0, 2700), P(3000, 0, 2700));
        if (__el_P1 == null) { __t.RollBack(); return __Refuse("P1", "Pipe.Create вернул null"); }
        try { Parameter __dp_P1 = __el_P1.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM); if (__dp_P1 != null && !__dp_P1.IsReadOnly) __dp_P1.Set(U(50.0)); } catch { }
        try { Parameter __cm = __el_P1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:aab4b046:P1"); } catch { }

        // create_grid G1
        __el_G1 = Grid.Create(doc, Line.CreateBound(P(0, -1000, 0), P(0, 9000, 0)));
        if (__el_G1 == null) { __t.RollBack(); return __Refuse("G1", "Grid.Create вернул null"); }
        try { __el_G1.Name = "А"; }
        catch (Exception __ex_G1) { __t.RollBack(); return __Refuse("G1", "имя сетки: " + __ex_G1.Message); }
        try { Parameter __cm = __el_G1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:aab4b046:G1"); } catch { }

        doc.Regenerate();

        // post W1
        {
            var __lc = __el_W1.Location as LocationCurve;
            if (__lc == null) __post.Add("W1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("W1: endpoints mismatch (geometry)");
            }
            var __bp = __el_W1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("W1: level binding mismatch (topology)");
            var __hp = __el_W1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("W1: height mismatch");
        }
        // post P1
        {
            var __lc = __el_P1.Location as LocationCurve;
            if (__lc == null) __post.Add("P1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2) + Math.Pow(MM(__a.Z) - 2700, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2) + Math.Pow(MM(__b.Z) - 2700, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 3000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0 || Math.Abs(MM(__e0.Z) - 2700) > 5.0 || Math.Abs(MM(__e1.Z) - 2700) > 5.0)
                    __post.Add("P1: endpoints mismatch (geometry)");
            }
            var __bp = __el_P1.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("P1: level binding mismatch (topology)");
            var __dp = __el_P1.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            if (__dp == null || Math.Abs(MM(__dp.AsDouble()) - 50.0) > 0.5)
                __post.Add("P1: diameter mismatch");
        }
        // post G1
        {
            var __gc = __el_G1.Curve;
            if (__gc == null) __post.Add("G1: нет Curve");
            else
            {
                var __a = __gc.GetEndPoint(0); var __b = __gc.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - -1000, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - -1000, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - -1000) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 0) > 5.0 || Math.Abs(MM(__e1.Y) - 9000) > 5.0)
                    __post.Add("G1: endpoints mismatch (geometry)");
            }
            if (__el_G1.Name != "А") __post.Add("G1: name mismatch");
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

// witness W1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_W1.Id.ToString();
    try { var __stampParam = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_W1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_W1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["W1"] = __rb;
}

// witness P1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_P1.Id.ToString();
    try { var __stampParam = __el_P1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_P1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_P1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["P1"] = __rb;
}

// witness G1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_G1.Id.ToString();
    try { var __stampParam = __el_G1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __rb["name"] = __el_G1.Name;
    try { var __gc2 = __el_G1.Curve;
        if (__gc2 != null) {
            var __s2 = __gc2.GetEndPoint(0); var __e2 = __gc2.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    __results["G1"] = __rb;
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