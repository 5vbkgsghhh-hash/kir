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
Railing __el_R1 = null;
using (Transaction __t = new Transaction(doc, "KIR: ограждение по краю балкона"))
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
        // create_railing(path) R1
        RailingType __ty_R1 = doc.GetElement(new ElementId(1201)) as RailingType;
        if (__ty_R1 == null) { __t.RollBack(); return __Refuse("R1", "ограждение: тип не найден (модель изменилась после grounding)"); }
        Element __lv_raw_R1 = doc.GetElement(new ElementId(42));
        Level __lv_R1 = __lv_raw_R1 as Level;
        if (__lv_R1 == null) { __t.RollBack(); return __Refuse("R1", (__lv_raw_R1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_R1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        CurveLoop __pth_R1 = new CurveLoop();
        __pth_R1.Append(Line.CreateBound(P(0.0, 0.0, 0), P(4000.0, 0.0, 0)));
        __pth_R1.Append(Line.CreateBound(P(4000.0, 0.0, 0), P(4000.0, 2500.0, 0)));
        __el_R1 = Railing.Create(doc, __pth_R1, __ty_R1.Id, __lv_R1.Id);
        if (__el_R1 == null) { __t.RollBack(); return __Refuse("R1", "создание ограждения вернуло null"); }
        try { Parameter __cm = __el_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:8dd19674:R1"); } catch { }

        doc.Regenerate();

        // post R1
        {
            var __rlp_R1 = __el_R1.get_Parameter(BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM);
            if (__rlp_R1 == null || __rlp_R1.AsElementId() == null
                || __rlp_R1.AsElementId().ToString() != "42")
                __post.Add("R1: base level mismatch (topology)");
            var __bb = __el_R1.get_BoundingBox(null);
            if (__bb == null) __post.Add("R1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0.0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 4000.0) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0.0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 2500.0) > 50.0)
                __post.Add("R1: bbox extents mismatch (geometry)");
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

// witness R1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_R1.Id.ToString();
    try { var __stampParam = __el_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_R1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_R1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["R1"] = __rb;
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