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
Ceiling __el_C1 = null;
using (Transaction __t = new Transaction(doc, "KIR: подвесной потолок в помещении с проёмом под шахту"))
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
        // create_ceiling C1
        CeilingType __ty_C1 = doc.GetElement(new ElementId(1200)) as CeilingType;
        if (__ty_C1 == null) { __t.RollBack(); return __Refuse("C1", "потолок: тип не найден (модель изменилась после grounding)"); }
        Element __lv_raw_C1 = doc.GetElement(new ElementId(42));
        Level __lv_C1 = __lv_raw_C1 as Level;
        if (__lv_C1 == null) { __t.RollBack(); return __Refuse("C1", (__lv_raw_C1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_C1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        var __loops_C1 = new List<CurveLoop>();
        CurveLoop __ol_C1 = new CurveLoop();
        __ol_C1.Append(Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)));
        __ol_C1.Append(Line.CreateBound(P(6000, 0, 0), P(6000, 4000, 0)));
        __ol_C1.Append(Line.CreateBound(P(6000, 4000, 0), P(0, 4000, 0)));
        __ol_C1.Append(Line.CreateBound(P(0, 4000, 0), P(0, 0, 0)));
        __loops_C1.Add(__ol_C1);
        CurveLoop __hl_C1_0 = new CurveLoop();
        __hl_C1_0.Append(Line.CreateBound(P(2000, 1500, 0), P(3000, 1500, 0)));
        __hl_C1_0.Append(Line.CreateBound(P(3000, 1500, 0), P(3000, 2500, 0)));
        __hl_C1_0.Append(Line.CreateBound(P(3000, 2500, 0), P(2000, 2500, 0)));
        __hl_C1_0.Append(Line.CreateBound(P(2000, 2500, 0), P(2000, 1500, 0)));
        __loops_C1.Add(__hl_C1_0);
        __el_C1 = Ceiling.Create(doc, __loops_C1, __ty_C1.Id, __lv_C1.Id);
        if (__el_C1 == null) { __t.RollBack(); return __Refuse("C1", "создание потолка вернуло null"); }

        Parameter __cho_C1 = __el_C1.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM);
        if (__cho_C1 == null || __cho_C1.IsReadOnly) { __t.RollBack(); return __Refuse("C1", "CEILING_HEIGHTABOVELEVEL_PARAM недоступен у потолка"); }
        __cho_C1.Set(U(2700.0));try { Parameter __cm = __el_C1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9af80f1e:C1"); } catch { }

        doc.Regenerate();

        // post C1
        {
            Parameter __lp = __el_C1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_C1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_C1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_C1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("C1: level binding mismatch (topology)");
            var __bb = __el_C1.get_BoundingBox(null);
            if (__bb == null) __post.Add("C1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 6000) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 4000) > 50.0)
                __post.Add("C1: bbox extents mismatch (geometry)");
            var __chop = __el_C1.get_Parameter(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM);
            if (__chop == null || Math.Abs(MM(__chop.AsDouble()) - 2700.0) > 1.0)
                __post.Add("C1: height offset mismatch (geometry)");
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

// witness C1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_C1.Id.ToString();
    try { var __stampParam = __el_C1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_C1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_C1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["C1"] = __rb;
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