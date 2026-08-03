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
Level __el_sec_L1 = null;
Level __el_sec_L2 = null;
Wall __el_sec_L1_W = null;
Wall __el_sec_L2_W = null;
using (Transaction __t = new Transaction(doc, "KIR: две типовых этажа со стеной"))
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
        // create_level sec_L1
        __el_sec_L1 = Level.Create(doc, U(0.0));
        if (__el_sec_L1 == null) { __t.RollBack(); return __Refuse("sec_L1", "Level.Create вернул null"); }
        try { __el_sec_L1.Name = "Этаж 1"; }
        catch (Exception __ex_sec_L1) { __t.RollBack(); return __Refuse("sec_L1", "имя уровня: " + __ex_sec_L1.Message); }
        try { Parameter __cm = __el_sec_L1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:94e573ff:sec_L1"); } catch { }

        // create_level sec_L2
        __el_sec_L2 = Level.Create(doc, U(3000.0));
        if (__el_sec_L2 == null) { __t.RollBack(); return __Refuse("sec_L2", "Level.Create вернул null"); }
        try { __el_sec_L2.Name = "Этаж 2"; }
        catch (Exception __ex_sec_L2) { __t.RollBack(); return __Refuse("sec_L2", "имя уровня: " + __ex_sec_L2.Message); }
        try { Parameter __cm = __el_sec_L2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:94e573ff:sec_L2"); } catch { }

        // create_wall sec_L1_W
        WallType __wt_sec_L1_W = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_sec_L1_W == null) { __t.RollBack(); return __Refuse("sec_L1_W", "в документе нет типа стены по умолчанию"); }
        Level __lv_sec_L1_W = __el_sec_L1;
        __el_sec_L1_W = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_sec_L1_W.Id, __lv_sec_L1_W.Id, U(2800.0), 0.0, false, false);
        if (__el_sec_L1_W == null) { __t.RollBack(); return __Refuse("sec_L1_W", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_sec_L1_W.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:94e573ff:sec_L1_W"); } catch { }

        // create_wall sec_L2_W
        WallType __wt_sec_L2_W = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_sec_L2_W == null) { __t.RollBack(); return __Refuse("sec_L2_W", "в документе нет типа стены по умолчанию"); }
        Level __lv_sec_L2_W = __el_sec_L2;
        __el_sec_L2_W = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_sec_L2_W.Id, __lv_sec_L2_W.Id, U(2800.0), 0.0, false, false);
        if (__el_sec_L2_W == null) { __t.RollBack(); return __Refuse("sec_L2_W", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_sec_L2_W.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:94e573ff:sec_L2_W"); } catch { }

        doc.Regenerate();

        // post sec_L1
        {
            if (Math.Abs(MM(__el_sec_L1.Elevation) - 0.0) > 1.0)
                __post.Add("sec_L1: elevation mismatch (geometry)");
            if (__el_sec_L1.Name != "Этаж 1") __post.Add("sec_L1: name mismatch");
        }
        // post sec_L2
        {
            if (Math.Abs(MM(__el_sec_L2.Elevation) - 3000.0) > 1.0)
                __post.Add("sec_L2: elevation mismatch (geometry)");
            if (__el_sec_L2.Name != "Этаж 2") __post.Add("sec_L2: name mismatch");
        }
        // post sec_L1_W
        {
            var __lc = __el_sec_L1_W.Location as LocationCurve;
            if (__lc == null) __post.Add("sec_L1_W: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("sec_L1_W: endpoints mismatch (geometry)");
            }
            var __bp = __el_sec_L1_W.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != __el_sec_L1.Id.ToString())
                __post.Add("sec_L1_W: level binding mismatch (topology)");
            var __hp = __el_sec_L1_W.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 2800.0) > 1.0)
                __post.Add("sec_L1_W: height mismatch");
        }
        // post sec_L2_W
        {
            var __lc = __el_sec_L2_W.Location as LocationCurve;
            if (__lc == null) __post.Add("sec_L2_W: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("sec_L2_W: endpoints mismatch (geometry)");
            }
            var __bp = __el_sec_L2_W.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != __el_sec_L2.Id.ToString())
                __post.Add("sec_L2_W: level binding mismatch (topology)");
            var __hp = __el_sec_L2_W.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 2800.0) > 1.0)
                __post.Add("sec_L2_W: height mismatch");
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

// witness sec_L1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_sec_L1.Id.ToString();
    __rb["elevation_mm"] = Math.Round(MM(__el_sec_L1.Elevation), 1);
    __rb["name"] = __el_sec_L1.Name;
    __results["sec_L1"] = __rb;
}

// witness sec_L2
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_sec_L2.Id.ToString();
    __rb["elevation_mm"] = Math.Round(MM(__el_sec_L2.Elevation), 1);
    __rb["name"] = __el_sec_L2.Name;
    __results["sec_L2"] = __rb;
}

// witness sec_L1_W
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_sec_L1_W.Id.ToString();
    try { var __stampParam = __el_sec_L1_W.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_sec_L1_W.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_sec_L1_W.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["sec_L1_W"] = __rb;
}

// witness sec_L2_W
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_sec_L2_W.Id.ToString();
    try { var __stampParam = __el_sec_L2_W.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_sec_L2_W.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_sec_L2_W.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["sec_L2_W"] = __rb;
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