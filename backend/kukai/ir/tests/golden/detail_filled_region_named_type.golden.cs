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
FilledRegion __el_F1 = null;
View __vw_F1 = null;
FilledRegionType __frt_F1 = null;
XYZ __vp_F1(double __u, double __v) => (__vw_F1.Origin + __vw_F1.RightDirection.Multiply(U(__u)) + __vw_F1.UpDirection.Multiply(U(__v)));
double[] __fu0_F1 = new double[] { 0.0, 4000.0, 4000.0, 0.0, 1000.0, 1800.0, 1800.0, 1000.0 };
double[] __fv0_F1 = new double[] { 0.0, 0.0, 2500.0, 2500.0, 800.0, 800.0, 1400.0, 1400.0 };
double[] __fum_F1 = new double[] { 2000.0, 4500.0, 2000.0, 0.0, 1400.0, 1800.0, 1400.0, 1000.0 };
double[] __fvm_F1 = new double[] { 0.0, 1250.0, 2500.0, 1250.0, 800.0, 1100.0, 1400.0, 1100.0 };
double[] __fu1_F1 = new double[] { 4000.0, 4000.0, 0.0, 0.0, 1800.0, 1800.0, 1000.0, 1000.0 };
double[] __fv1_F1 = new double[] { 0.0, 2500.0, 2500.0, 0.0, 800.0, 1400.0, 1400.0, 800.0 };
using (Transaction __t = new Transaction(doc, "KIR: заливка бетона на разрезе, с проёмом и скруглённым краем"))
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
        // create_filled_region F1
        __vw_F1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_F1 == null) { __t.RollBack(); return __Refuse("F1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        __frt_F1 = doc.GetElement(new ElementId(1800)) as FilledRegionType;
        if (__frt_F1 == null) { __t.RollBack(); return __Refuse("F1", "тип заливки не найден (модель изменилась после grounding)"); }
        if (!FilledRegion.IsValidFilledRegionTypeId(doc, __frt_F1.Id)) { __t.RollBack(); return __Refuse("F1", "type: id резолвится не в тип заливки (IsValidFilledRegionTypeId)"); }
        var __loops_F1 = new List<CurveLoop>();
        CurveLoop __ol_F1 = new CurveLoop();
        __ol_F1.Append(Line.CreateBound(__vp_F1(0.0, 0.0), __vp_F1(4000.0, 0.0)));
        __ol_F1.Append(Arc.Create(__vp_F1(4000.0, 0.0), __vp_F1(4000.0, 2500.0), __vp_F1(4500.0, 1250.0)));
        __ol_F1.Append(Line.CreateBound(__vp_F1(4000.0, 2500.0), __vp_F1(0.0, 2500.0)));
        __ol_F1.Append(Line.CreateBound(__vp_F1(0.0, 2500.0), __vp_F1(0.0, 0.0)));
        __loops_F1.Add(__ol_F1);
        CurveLoop __hl_F1_0 = new CurveLoop();
        __hl_F1_0.Append(Line.CreateBound(__vp_F1(1000.0, 800.0), __vp_F1(1800.0, 800.0)));
        __hl_F1_0.Append(Line.CreateBound(__vp_F1(1800.0, 800.0), __vp_F1(1800.0, 1400.0)));
        __hl_F1_0.Append(Line.CreateBound(__vp_F1(1800.0, 1400.0), __vp_F1(1000.0, 1400.0)));
        __hl_F1_0.Append(Line.CreateBound(__vp_F1(1000.0, 1400.0), __vp_F1(1000.0, 800.0)));
        __loops_F1.Add(__hl_F1_0);
        try { __el_F1 = FilledRegion.Create(doc, __frt_F1.Id, __vw_F1.Id, __loops_F1); }
        catch (Exception __ex_F1) { __t.RollBack(); return __Refuse("F1", "FilledRegion.Create: " + __ex_F1.Message); }
        if (__el_F1 == null) { __t.RollBack(); return __Refuse("F1", "FilledRegion.Create вернул null"); }
        try { Parameter __cm = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:006e5ff6:F1"); } catch { }

        doc.Regenerate();

        // post F1
        {
            if (__el_F1.OwnerViewId.ToString() != __vw_F1.Id.ToString())
                __post.Add("F1: filled region belongs to wrong view (topology)");
            if (__el_F1.GetTypeId().ToString() != __frt_F1.Id.ToString())
                __post.Add("F1: тип заливки после чтения не тот, что запрошен (semantic)");
            int __frLoops_F1 = 0; int __frCurves_F1 = 0;
            bool __frRead_F1 = true; bool __frStray_F1 = false;
            int[] __frHit_F1 = new int[8];
            try
            {
                foreach (CurveLoop __frCl_F1 in __el_F1.GetBoundaries())
                {
                    __frLoops_F1++;
                    foreach (Curve __frCv_F1 in __frCl_F1)
                    {
                        __frCurves_F1++;
                        var __frRa_F1 = __frCv_F1.GetEndPoint(0) - __vw_F1.Origin;
                        double __frAu_F1 = MM(__frRa_F1.DotProduct(__vw_F1.RightDirection));
                        double __frAv_F1 = MM(__frRa_F1.DotProduct(__vw_F1.UpDirection));
                        var __frRb_F1 = __frCv_F1.GetEndPoint(1) - __vw_F1.Origin;
                        double __frBu_F1 = MM(__frRb_F1.DotProduct(__vw_F1.RightDirection));
                        double __frBv_F1 = MM(__frRb_F1.DotProduct(__vw_F1.UpDirection));
                        var __frRm_F1 = __frCv_F1.Evaluate(0.5, true) - __vw_F1.Origin;
                        double __frMu_F1 = MM(__frRm_F1.DotProduct(__vw_F1.RightDirection));
                        double __frMv_F1 = MM(__frRm_F1.DotProduct(__vw_F1.UpDirection));
                        bool __frOne_F1 = false;
                        for (int __frK_F1 = 0; __frK_F1 < 8; __frK_F1++)
                        {
                            bool __frFwd_F1 = Math.Abs(__frAu_F1 - __fu0_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frAv_F1 - __fv0_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frBu_F1 - __fu1_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frBv_F1 - __fv1_F1[__frK_F1]) <= 1.0;
                            bool __frRev_F1 = Math.Abs(__frAu_F1 - __fu1_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frAv_F1 - __fv1_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frBu_F1 - __fu0_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frBv_F1 - __fv0_F1[__frK_F1]) <= 1.0;
                            if ((__frFwd_F1 || __frRev_F1)
                                && Math.Abs(__frMu_F1 - __fum_F1[__frK_F1]) <= 1.0
                                && Math.Abs(__frMv_F1 - __fvm_F1[__frK_F1]) <= 1.0)
                            { __frHit_F1[__frK_F1]++; __frOne_F1 = true; break; }
                        }
                        if (!__frOne_F1) __frStray_F1 = true;
                    }
                }
            } catch { __frRead_F1 = false; }
            bool __frExact_F1 = true;
            for (int __frJ_F1 = 0; __frJ_F1 < 8; __frJ_F1++)
                if (__frHit_F1[__frJ_F1] != 1) __frExact_F1 = false;
            if (!__frRead_F1)
                __post.Add("F1: граница заливки нечитаема — GetBoundaries бросил (geometry)");
            else if (__frLoops_F1 != 2 || __frCurves_F1 != 8)
                __post.Add("F1: прочитано " + __frLoops_F1 + " петель / " + __frCurves_F1 + " рёбер вместо 2/8 (geometry)");
            else if (__frStray_F1 || !__frExact_F1)
                __post.Add("F1: граница заливки не совпала с заданным контуром в осях вида (geometry)");
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

// witness F1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_F1.Id.ToString();
    try { var __stampParam = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __rb["view_id"] = __el_F1.OwnerViewId.ToString();
    __rb["type_id"] = __el_F1.GetTypeId().ToString();
    try { var __frTy_F1 = doc.GetElement(__el_F1.GetTypeId());
        if (__frTy_F1 != null && __frTy_F1.Name != null) __rb["type_name"] = __frTy_F1.Name; } catch { }
    try { __rb["is_masking"] = __el_F1.IsMasking; } catch { }
    __results["F1"] = __rb;
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