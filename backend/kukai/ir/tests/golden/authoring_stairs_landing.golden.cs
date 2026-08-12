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
// create_stairs_landing LD1 — sole-op program, StairsEditScope owns transactions
Element __tg_LD1 = doc.GetElement(new ElementId(8888));
if (__tg_LD1 == null)
    return __Refuse("LD1", "лестница не найдена (модель изменилась после grounding)");
Autodesk.Revit.DB.Architecture.Stairs __st_LD1 = __tg_LD1 as Autodesk.Revit.DB.Architecture.Stairs;
if (__st_LD1 == null)
    return __Refuse("LD1", "указанный элемент — не лестница");
double __rh_LD1 = MM(__st_LD1.ActualRiserHeight);
if (!(__rh_LD1 > 0.0) || Double.IsNaN(__rh_LD1) || Double.IsInfinity(__rh_LD1))
    return __Refuse("LD1", "у лестницы нечитаема высота подступенка (ActualRiserHeight не является конечным положительным числом)");
if (1800.0 < __rh_LD1 / 2.0)
    return __Refuse("LD1", "elevation_mm = 1800.0 мм ниже половины высоты подступенка этой лестницы (" + Math.Round(__rh_LD1 / 2.0, 1) + " мм) — Revit такую площадку не принимает");
double __dt_LD1 = MM(doc.Application.VertexTolerance) + 0.01;
if (2.0 * __dt_LD1 >= 1600.0)
    return __Refuse("LD1", "выведенный допуск границы (" + Math.Round(__dt_LD1, 3) + " мм) не меньше половины самого короткого ребра контура (ребро 1600.0 мм, половина 800.0 мм) — свидетель границы не смог бы провалиться");
double __elevQ_LD1 = 1800.0 / __rh_LD1;
double __elevK_LD1 = Math.Round(__elevQ_LD1, MidpointRounding.AwayFromZero);
if (__elevK_LD1 < 1.0) __elevK_LD1 = 1.0;
double __elevNorm_LD1 = __elevK_LD1 * __rh_LD1;
double __elevLower_LD1 = Math.Max(__rh_LD1, Math.Floor(__elevQ_LD1) * __rh_LD1);
double __elevUpper_LD1 = Math.Max(__rh_LD1, Math.Ceiling(__elevQ_LD1) * __rh_LD1);
if (Math.Abs(1800.0 - __elevNorm_LD1) > __dt_LD1)
    return __Refuse("LD1", "elevation_mm должна быть целым кратным ActualRiserHeight; ближайшие кандидаты: " + Math.Round(__elevLower_LD1, 3) + " мм и " + Math.Round(__elevUpper_LD1, 3) + " мм");
double[] __bx0_LD1 = new double[] { 0.0, 2400.0, 2400.0, 0.0 };
double[] __by0_LD1 = new double[] { 0.0, 0.0, 1600.0, 1600.0 };
double[] __bxm_LD1 = new double[] { 1200.0, 2400.0, 1200.0, 0.0 };
double[] __bym_LD1 = new double[] { 0.0, 800.0, 1600.0, 800.0 };
double[] __bx1_LD1 = new double[] { 2400.0, 2400.0, 0.0, 0.0 };
double[] __by1_LD1 = new double[] { 0.0, 1600.0, 1600.0, 0.0 };
double __sbz_LD1 = MM(__st_LD1.BaseElevation);
ElementId __stairsId_LD1 = __st_LD1.Id;
Action<Autodesk.Revit.DB.Architecture.StairsLanding, Autodesk.Revit.DB.Architecture.Stairs> __check_LD1 = (__landing_LD1, __stairs_LD1) =>
{
    if (__landing_LD1 == null)
    { __post.Add("LD1: площадка не найдена при свежем чтении (identity)"); return; }
    if (__stairs_LD1 == null)
        __post.Add("LD1: лестница не найдена при свежем чтении (identity)");
    try
    {
        var __own_LD1 = __landing_LD1.GetStairs();
        if (__stairs_LD1 == null || __own_LD1 == null || __own_LD1.Id.ToString() != __stairs_LD1.Id.ToString())
            __post.Add("LD1: площадка принадлежит не той лестнице (topology)");
    }
    catch { __post.Add("LD1: владелец площадки нечитаем (topology)"); }
    bool __inSet_LD1 = false;
    try
    {
        if (__stairs_LD1 != null)
            foreach (ElementId __li_LD1 in __stairs_LD1.GetStairsLandings())
                if (__li_LD1.ToString() == __landing_LD1.Id.ToString()) __inSet_LD1 = true;
    }
    catch { }
    if (!__inSet_LD1)
        __post.Add("LD1: площадки нет в GetStairsLandings своей лестницы (topology)");
    try { if (__landing_LD1.IsAutomaticLanding)
              __post.Add("LD1: построена автоматическая площадка вместо эскизной (semantic)"); }
    catch { __post.Add("LD1: признак автоматической площадки нечитаем (semantic)"); }
    int __bCurves_LD1 = 0;
    bool __bRead_LD1 = true; bool __bStray_LD1 = false;
    int[] __bHit_LD1 = new int[4];
    try
    {
        foreach (Curve __bc_LD1 in __landing_LD1.GetFootprintBoundary())
        {
            __bCurves_LD1++;
            double __ax_LD1 = MM(__bc_LD1.GetEndPoint(0).X);
            double __ay_LD1 = MM(__bc_LD1.GetEndPoint(0).Y);
            double __zx_LD1 = MM(__bc_LD1.GetEndPoint(1).X);
            double __zy_LD1 = MM(__bc_LD1.GetEndPoint(1).Y);
            double __mx_LD1 = MM(__bc_LD1.Evaluate(0.5, true).X);
            double __my_LD1 = MM(__bc_LD1.Evaluate(0.5, true).Y);
            bool __bOne_LD1 = false;
            for (int __bk_LD1 = 0; __bk_LD1 < 4; __bk_LD1++)
            {
                bool __bFwd_LD1 = Math.Abs(__ax_LD1 - __bx0_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__ay_LD1 - __by0_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__zx_LD1 - __bx1_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__zy_LD1 - __by1_LD1[__bk_LD1]) <= __dt_LD1;
                bool __bRev_LD1 = Math.Abs(__ax_LD1 - __bx1_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__ay_LD1 - __by1_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__zx_LD1 - __bx0_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__zy_LD1 - __by0_LD1[__bk_LD1]) <= __dt_LD1;
                if ((__bFwd_LD1 || __bRev_LD1)
                    && Math.Abs(__mx_LD1 - __bxm_LD1[__bk_LD1]) <= __dt_LD1
                    && Math.Abs(__my_LD1 - __bym_LD1[__bk_LD1]) <= __dt_LD1)
                { __bHit_LD1[__bk_LD1]++; __bOne_LD1 = true; break; }
            }
            if (!__bOne_LD1) __bStray_LD1 = true;
        }
    }
    catch { __bRead_LD1 = false; }
    bool __bExact_LD1 = true;
    for (int __bj_LD1 = 0; __bj_LD1 < 4; __bj_LD1++)
        if (__bHit_LD1[__bj_LD1] != 1) __bExact_LD1 = false;
    if (!__bRead_LD1)
        __post.Add("LD1: граница площадки нечитаема — GetFootprintBoundary бросил (geometry)");
    else if (__bCurves_LD1 != 4)
        __post.Add("LD1: прочитано " + __bCurves_LD1 + " рёбер границы вместо 4 (geometry)");
    else if (__bStray_LD1 || !__bExact_LD1)
        __post.Add("LD1: граница площадки не совпала с заданным контуром в плане (geometry)");
    try
    {
        double __gotE_LD1 = MM(__landing_LD1.BaseElevation);
        if (Math.Abs(__gotE_LD1 - __elevNorm_LD1) > __dt_LD1)
            __post.Add("LD1: отметка площадки не равна нормализованному кратному подступенка (geometry)");
    }
    catch { __post.Add("LD1: отметка площадки нечитаема (geometry)"); }
};
var __ess = new StairsEditScope(doc, "KIR landing: промежуточная площадка на существующей лестнице");
if (!__ess.IsPermitted)
    return __Refuse("LD1", "StairsEditScope запрещён текущим состоянием документа");
Func<StairsEditScope, bool> __cancel_LD1 = (__scope_LD1) =>
{
    try
    {
        if (!__scope_LD1.IsActive) return false;
        __scope_LD1.Cancel();
        return !__scope_LD1.IsActive;
    }
    catch { return false; }
};
Func<Transaction, StairsEditScope, bool> __rollbackCancel_LD1 = (__transaction_LD1, __scope_LD1) =>
{
    TransactionStatus __rollbackStatus_LD1;
    try { __rollbackStatus_LD1 = __transaction_LD1.RollBack(); }
    catch { return false; }
    if (__rollbackStatus_LD1 != TransactionStatus.RolledBack) return false;
    return __cancel_LD1(__scope_LD1);
};
ElementId __sid_LD1 = null;
ElementId __landingId_LD1 = null;
Autodesk.Revit.DB.Architecture.StairsLanding __lg_LD1 = null;
try
{
    __sid_LD1 = __ess.Start(__stairsId_LD1);
    if (__sid_LD1 == null || __sid_LD1.ToString() != __stairsId_LD1.ToString())
    {
        if (!__cancel_LD1(__ess))
            throw new InvalidOperationException("StairsEditScope.Start target mismatch and cancellation is unproven");
        throw new InvalidOperationException("StairsEditScope.Start returned a different stairs id");
    }
    using (Transaction __t = new Transaction(doc, "KIR: stairs landing"))
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
        {
            if (!__cancel_LD1(__ess))
                throw new InvalidOperationException("transaction did not start and scope cancellation is unproven");
            throw new InvalidOperationException("transaction start status: " + __startStatus.ToString());
        }
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirStairsFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        CurveLoop __ol_LD1 = new CurveLoop();
        __ol_LD1.Append(Line.CreateBound(P(0.0, 0.0, __sbz_LD1), P(2400.0, 0.0, __sbz_LD1)));
        __ol_LD1.Append(Line.CreateBound(P(2400.0, 0.0, __sbz_LD1), P(2400.0, 1600.0, __sbz_LD1)));
        __ol_LD1.Append(Line.CreateBound(P(2400.0, 1600.0, __sbz_LD1), P(0.0, 1600.0, __sbz_LD1)));
        __ol_LD1.Append(Line.CreateBound(P(0.0, 1600.0, __sbz_LD1), P(0.0, 0.0, __sbz_LD1)));
        try
        {
            __lg_LD1 = Autodesk.Revit.DB.Architecture.StairsLanding.CreateSketchedLanding(doc, __sid_LD1, __ol_LD1, U(__elevNorm_LD1));
        }
        catch (Exception __ex_LD1)
        {
            if (!__rollbackCancel_LD1(__t, __ess))
                throw new InvalidOperationException("CreateSketchedLanding failed and rollback/cancel is unproven", __ex_LD1);
            return __Refuse("LD1", "CreateSketchedLanding: " + __ex_LD1.Message);
        }
        if (__lg_LD1 == null)
        {
            if (!__rollbackCancel_LD1(__t, __ess))
                throw new InvalidOperationException("CreateSketchedLanding returned null and rollback/cancel is unproven");
            return __Refuse("LD1", "CreateSketchedLanding вернул null");
        }
        doc.Regenerate();
        try { Parameter __cm = __lg_LD1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:c6ed7ef1:LD1"); } catch { }
        __landingId_LD1 = __lg_LD1.Id;
        __post.Clear();
        __check_LD1(__lg_LD1, __st_LD1);
        if (__post.Count > 0)
        {
            if (!__rollbackCancel_LD1(__t, __ess))
                throw new InvalidOperationException("postcondition failed and rollback/cancel is unproven");
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = new List<string>(__post);
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        {
            if (!__cancel_LD1(__ess))
                throw new InvalidOperationException("transaction commit was not Committed and scope cancellation is unproven");
            throw new InvalidOperationException("transaction commit status: " + __commitStatus.ToString());
        }
    }
    __ess.Commit(new __KirStairsFailures());
    if (__ess.IsActive)
        throw new InvalidOperationException("StairsEditScope.Commit returned but scope is still active");
}
catch (Exception __scopeEx_LD1)
{
    bool __cleanup_LD1 = true;
    try
    {
        if (__ess.IsActive)
        { __ess.Cancel(); __cleanup_LD1 = !__ess.IsActive; }
    }
    catch { __cleanup_LD1 = false; }
    if (!__cleanup_LD1)
        throw new InvalidOperationException("stairs scope cleanup is unproven", __scopeEx_LD1);
    throw;
}
var __freshSt_LD1 = doc.GetElement(__stairsId_LD1) as Autodesk.Revit.DB.Architecture.Stairs;
var __freshLg_LD1 = __landingId_LD1 == null ? null : doc.GetElement(__landingId_LD1) as Autodesk.Revit.DB.Architecture.StairsLanding;
__post.Clear();
__check_LD1(__freshLg_LD1, __freshSt_LD1);
// witness (fresh post-scope readback)
var __rb_LD1 = new Dictionary<string, object>();
__rb_LD1["stairs_id"] = __stairsId_LD1.ToString();
if (__landingId_LD1 != null) __rb_LD1["id"] = __landingId_LD1.ToString();
if (__freshLg_LD1 != null)
{
        try { var __stampParam = __freshLg_LD1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb_LD1["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb_LD1["elevation_requested_mm"] = 1800.0;
          __rb_LD1["elevation_normalized_mm"] = Math.Round(__elevNorm_LD1, 3);
          __rb_LD1["elevation_built_mm"] = Math.Round(MM(__freshLg_LD1.BaseElevation), 3);
          __rb_LD1["riser_height_mm"] = Math.Round(__rh_LD1, 2); } catch { }
    __rb_LD1["elevation_lower_candidate_mm"] = Math.Round(__elevLower_LD1, 3);
    __rb_LD1["elevation_upper_candidate_mm"] = Math.Round(__elevUpper_LD1, 3);
    try { __rb_LD1["thickness_mm"] = Math.Round(MM(__freshLg_LD1.Thickness), 2); } catch { }
    try { __rb_LD1["is_automatic"] = __freshLg_LD1.IsAutomaticLanding; } catch { }
    try { __rb_LD1["boundary_tolerance_mm"] = Math.Round(__dt_LD1, 3); } catch { }
    try { var __rl_LD1 = __freshSt_LD1 == null ? null : __freshSt_LD1.GetStairsLandings();
          __rb_LD1["landings"] = __rl_LD1 == null ? 0 : __rl_LD1.Count; } catch { }
}
__results["LD1"] = __rb_LD1;
__results["ok"] = true;
if (__post.Count > 0)
    __results["postcondition_violations"] = new List<string>(__post);
return __results;
}

private class __KirStairsFailures : IFailuresPreprocessor
{
    public FailureProcessingResult PreprocessFailures(FailuresAccessor __fa)
    {
        foreach (var __f in __fa.GetFailureMessages())
            if (__f.GetSeverity() == FailureSeverity.Warning)
                __fa.DeleteWarning(__f);
        return FailureProcessingResult.Continue;
    }
}

private static class __KirPad
{  // pad scope: the fixed wrapper footer closes __KirPad, UserCode, namespace