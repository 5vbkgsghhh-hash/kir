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
// create_stairs_run RN1 — sole-op program, StairsEditScope owns transactions
Element __tg_RN1 = doc.GetElement(new ElementId(8888));
if (__tg_RN1 == null)
    return __Refuse("RN1", "лестница не найдена (модель изменилась после grounding)");
Autodesk.Revit.DB.Architecture.Stairs __st_RN1 = __tg_RN1 as Autodesk.Revit.DB.Architecture.Stairs;
if (__st_RN1 == null)
    return __Refuse("RN1", "указанный элемент — не лестница");
double __dt_RN1 = MM(doc.Application.VertexTolerance) + 0.5;
double __rh_RN1 = MM(__st_RN1.ActualRiserHeight);
if (!(__rh_RN1 > 0.0))
    return __Refuse("RN1", "высота подступенка лестницы нечитаема или ноль — отметку марша не к чему привязать");
double __elevQ_RN1 = 1800.0 / __rh_RN1;
double __elevNorm_RN1 = Math.Round(__elevQ_RN1) * __rh_RN1;
double __elevLower_RN1 = Math.Floor(__elevQ_RN1) * __rh_RN1;
double __elevUpper_RN1 = Math.Ceiling(__elevQ_RN1) * __rh_RN1;
if (Math.Abs(1800.0 - __elevNorm_RN1) > __dt_RN1)
    return __Refuse("RN1", "base_elevation_mm должна быть целым кратным ActualRiserHeight; ближайшие кандидаты: " + Math.Round(__elevLower_RN1, 3) + " мм и " + Math.Round(__elevUpper_RN1, 3) + " мм");
double __sbz_RN1 = MM(__st_RN1.BaseElevation);
ElementId __stairsId_RN1 = __st_RN1.Id;
Action<Autodesk.Revit.DB.Architecture.StairsRun, Autodesk.Revit.DB.Architecture.Stairs> __check_RN1 = (__run_RN1, __stairs_RN1) =>
{
    if (__run_RN1 == null)
    { __post.Add("RN1: марш не найден при свежем чтении (identity)"); return; }
    if (__stairs_RN1 == null)
        __post.Add("RN1: лестница не найдена при свежем чтении (identity)");
    try
    {
        var __own_RN1 = __run_RN1.GetStairs();
        if (__stairs_RN1 == null || __own_RN1 == null || __own_RN1.Id.ToString() != __stairs_RN1.Id.ToString())
            __post.Add("RN1: марш принадлежит не той лестнице (topology)");
    }
    catch { __post.Add("RN1: владелец марша нечитаем (topology)"); }
    bool __inSet_RN1 = false;
    try
    {
        if (__stairs_RN1 != null)
            foreach (ElementId __ri_RN1 in __stairs_RN1.GetStairsRuns())
                if (__ri_RN1.ToString() == __run_RN1.Id.ToString()) __inSet_RN1 = true;
    }
    catch { }
    if (!__inSet_RN1)
        __post.Add("RN1: марша нет в GetStairsRuns своей лестницы (topology)");
    bool __pathRead_RN1 = false; bool __pathHit_RN1 = false;
    try
    {
        foreach (Curve __pc_RN1 in __run_RN1.GetStairsPath())
        {
            __pathRead_RN1 = true;
            double __ax_RN1 = MM(__pc_RN1.GetEndPoint(0).X);
            double __ay_RN1 = MM(__pc_RN1.GetEndPoint(0).Y);
            double __zx_RN1 = MM(__pc_RN1.GetEndPoint(1).X);
            double __zy_RN1 = MM(__pc_RN1.GetEndPoint(1).Y);
            bool __fwd_RN1 = Math.Abs(__ax_RN1 - 0.0) <= __dt_RN1
                && Math.Abs(__ay_RN1 - 0.0) <= __dt_RN1
                && Math.Abs(__zx_RN1 - 3200.0) <= __dt_RN1
                && Math.Abs(__zy_RN1 - 0.0) <= __dt_RN1;
            bool __rev_RN1 = Math.Abs(__ax_RN1 - 3200.0) <= __dt_RN1
                && Math.Abs(__ay_RN1 - 0.0) <= __dt_RN1
                && Math.Abs(__zx_RN1 - 0.0) <= __dt_RN1
                && Math.Abs(__zy_RN1 - 0.0) <= __dt_RN1;
            if (__fwd_RN1 || __rev_RN1) __pathHit_RN1 = true;
        }
    }
    catch { __pathRead_RN1 = false; }
    if (!__pathRead_RN1)
        __post.Add("RN1: путь марша нечитаем (geometry)");
    else if (!__pathHit_RN1)
        __post.Add("RN1: ось марша в плане не совпала с заявленной (geometry)");
    try
    {
        double __built_RN1 = MM(__run_RN1.BaseElevation);
        if (Math.Abs(__built_RN1 - (__sbz_RN1 + __elevNorm_RN1)) > __dt_RN1)
            __post.Add("RN1: отметка низа марша не совпала с заявленной (geometry)");
    }
    catch { __post.Add("RN1: отметка марша нечитаема (geometry)"); }
};
var __ess = new StairsEditScope(doc, "KIR run: второй марш на существующей лестнице");
if (!__ess.IsPermitted)
    return __Refuse("RN1", "StairsEditScope запрещён текущим состоянием документа");
Func<StairsEditScope, bool> __cancel_RN1 = (__scope_RN1) =>
{
    try
    {
        if (!__scope_RN1.IsActive) return false;
        __scope_RN1.Cancel();
        return !__scope_RN1.IsActive;
    }
    catch { return false; }
};
Func<Transaction, StairsEditScope, bool> __rollbackCancel_RN1 = (__transaction_RN1, __scope_RN1) =>
{
    TransactionStatus __rollbackStatus_RN1;
    try { __rollbackStatus_RN1 = __transaction_RN1.RollBack(); }
    catch { return false; }
    if (__rollbackStatus_RN1 != TransactionStatus.RolledBack) return false;
    return __cancel_RN1(__scope_RN1);
};
ElementId __sid_RN1 = null;
ElementId __runId_RN1 = null;
Autodesk.Revit.DB.Architecture.StairsRun __rn_RN1 = null;
try
{
    __sid_RN1 = __ess.Start(__stairsId_RN1);
    if (__sid_RN1 == null || __sid_RN1.ToString() != __stairsId_RN1.ToString())
    {
        if (!__cancel_RN1(__ess))
            throw new InvalidOperationException("StairsEditScope.Start target mismatch and cancellation is unproven");
        throw new InvalidOperationException("StairsEditScope.Start returned a different stairs id");
    }
    using (Transaction __t = new Transaction(doc, "KIR: stairs run"))
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
        {
            if (!__cancel_RN1(__ess))
                throw new InvalidOperationException("transaction did not start and scope cancellation is unproven");
            throw new InvalidOperationException("transaction start status: " + __startStatus.ToString());
        }
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirStairsFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        Line __path_RN1 = Line.CreateBound(
            new XYZ(U(0.0), U(0.0), U(__sbz_RN1 + __elevNorm_RN1)),
            new XYZ(U(3200.0), U(0.0), U(__sbz_RN1 + __elevNorm_RN1)));
        try
        {
            __rn_RN1 = Autodesk.Revit.DB.Architecture.StairsRun.CreateStraightRun(doc, __sid_RN1, __path_RN1, Autodesk.Revit.DB.Architecture.StairsRunJustification.Left);
        }
        catch (Exception __ex_RN1)
        {
            if (!__rollbackCancel_RN1(__t, __ess))
                throw new InvalidOperationException("CreateStraightRun failed and rollback/cancel is unproven", __ex_RN1);
            return __Refuse("RN1", "CreateStraightRun: " + __ex_RN1.Message);
        }
        if (__rn_RN1 == null)
        {
            if (!__rollbackCancel_RN1(__t, __ess))
                throw new InvalidOperationException("CreateStraightRun returned null and rollback/cancel is unproven");
            return __Refuse("RN1", "CreateStraightRun вернул null");
        }
        doc.Regenerate();
        try { Parameter __cm = __rn_RN1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:76e10d24:RN1"); } catch { }
        __runId_RN1 = __rn_RN1.Id;
        __post.Clear();
        __check_RN1(__rn_RN1, __st_RN1);
        if (__post.Count > 0)
        {
            if (!__rollbackCancel_RN1(__t, __ess))
                throw new InvalidOperationException("postcondition failed and rollback/cancel is unproven");
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = new List<string>(__post);
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        {
            if (!__cancel_RN1(__ess))
                throw new InvalidOperationException("transaction commit was not Committed and scope cancellation is unproven");
            throw new InvalidOperationException("transaction commit status: " + __commitStatus.ToString());
        }
    }
    __ess.Commit(new __KirStairsFailures());
    if (__ess.IsActive)
        throw new InvalidOperationException("StairsEditScope.Commit returned but scope is still active");
}
catch (Exception __scopeEx_RN1)
{
    bool __cleanup_RN1 = true;
    try
    {
        if (__ess.IsActive)
        { __ess.Cancel(); __cleanup_RN1 = !__ess.IsActive; }
    }
    catch { __cleanup_RN1 = false; }
    if (!__cleanup_RN1)
        throw new InvalidOperationException("stairs scope cleanup is unproven", __scopeEx_RN1);
    throw;
}
var __freshSt_RN1 = doc.GetElement(__stairsId_RN1) as Autodesk.Revit.DB.Architecture.Stairs;
var __freshRn_RN1 = __runId_RN1 == null ? null : doc.GetElement(__runId_RN1) as Autodesk.Revit.DB.Architecture.StairsRun;
__post.Clear();
__check_RN1(__freshRn_RN1, __freshSt_RN1);
// witness (fresh post-scope readback)
var __rb_RN1 = new Dictionary<string, object>();
__rb_RN1["stairs_id"] = __stairsId_RN1.ToString();
if (__runId_RN1 != null) __rb_RN1["id"] = __runId_RN1.ToString();
if (__freshRn_RN1 != null)
{
        try { var __stampParam = __freshRn_RN1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb_RN1["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb_RN1["base_elevation_requested_mm"] = 1800.0;
          __rb_RN1["base_elevation_normalized_mm"] = Math.Round(__elevNorm_RN1, 3);
          __rb_RN1["base_elevation_built_mm"] = Math.Round(MM(__freshRn_RN1.BaseElevation), 3);
          __rb_RN1["riser_height_mm"] = Math.Round(__rh_RN1, 2); } catch { }
    __rb_RN1["base_elevation_lower_candidate_mm"] = Math.Round(__elevLower_RN1, 3);
    __rb_RN1["base_elevation_upper_candidate_mm"] = Math.Round(__elevUpper_RN1, 3);
    try { __rb_RN1["top_elevation_mm"] = Math.Round(MM(__freshRn_RN1.TopElevation), 2); } catch { }
    try { __rb_RN1["run_width_mm"] = Math.Round(MM(__freshRn_RN1.ActualRunWidth), 2); } catch { }
    __rb_RN1["justification"] = "Left";
}
__results["RN1"] = __rb_RN1;
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