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
// create_stairs S1 — sole-op program, StairsEditScope owns transactions
Level __base_S1 = doc.GetElement(new ElementId(42)) as Level;
if (__base_S1 == null) return __Refuse("S1", "base_level: уровень не найден (модель изменилась после grounding)");
Level __top_S1 = doc.GetElement(new ElementId(43)) as Level;
if (__top_S1 == null) return __Refuse("S1", "top_level: уровень не найден (модель изменилась после grounding)");
if (__base_S1.Elevation >= __top_S1.Elevation)
    return __Refuse("S1", "base_level выше или равен top_level");
var __ess = new StairsEditScope(doc, "KIR stairs: винтовая лестница вокруг шахты");
ElementId __sid_S1 = __ess.Start(__base_S1.Id, __top_S1.Id);
Autodesk.Revit.DB.Architecture.Stairs __st_S1 = null;
try
{
    using (Transaction __t = new Transaction(doc, "KIR: stairs run"))
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
        { try { __ess.Cancel(); } catch { } return __Refuse("S1", "transaction start status: " + __startStatus.ToString()); }
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirStairsFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        StairsRun __run_S1 = StairsRun.CreateSpiralRun(doc, __sid_S1,
            new XYZ(U(3000.0), U(3000.0), __base_S1.Elevation),
            U(1500.0), 0.0, 4.71238898038469, false,
            StairsRunJustification.Center);
        if (__run_S1 == null)
        { __t.RollBack(); __ess.Cancel(); return __Refuse("S1", "CreateSpiralRun вернул null"); }
        try { __run_S1.ActualRunWidth = U(1200.0); } catch { }
        doc.Regenerate();
        __st_S1 = doc.GetElement(__sid_S1) as Autodesk.Revit.DB.Architecture.Stairs;
        if (__st_S1 == null)
        { __t.RollBack(); __ess.Cancel(); return __Refuse("S1", "лестница не материализовалась"); }
        try { Parameter __cm = __st_S1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:a29a1e38:S1"); } catch { }
        var __bl = __st_S1.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM);
        if (__bl == null || __bl.AsElementId().ToString() != __base_S1.Id.ToString())
            __post.Add("S1: base level mismatch (topology)");
        var __tl = __st_S1.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM);
        if (__tl == null || __tl.AsElementId().ToString() != __top_S1.Id.ToString())
            __post.Add("S1: top level mismatch (topology)");
        if (__st_S1.GetStairsRuns().Count < 1)
            __post.Add("S1: нет маршей (semantic)");
        try { if (Math.Abs(MM(__run_S1.ActualRunWidth) - 1200.0) > 5.0)
            __post.Add("S1: stairs run width mismatch (geometry)"); }
        catch { __post.Add("S1: stairs run width unreadable (geometry)"); }
        try
        {
            bool __spiralArc_S1 = false;
            foreach (Curve __spc_S1 in __run_S1.GetStairsPath())
                if (__spc_S1 is Arc) __spiralArc_S1 = true;
            if (!__spiralArc_S1)
                __post.Add("S1: spiral run path has no Arc (geometry)");
        }
        catch { __post.Add("S1: spiral run path unreadable (geometry)"); }
        if (__post.Count > 0)
        {
            __t.RollBack(); __ess.Cancel();
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = __post;
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        { try { __ess.Cancel(); } catch { } return __Refuse("S1", "transaction commit status: " + __commitStatus.ToString()); }
    }
    __ess.Commit(new __KirStairsFailures());
}
catch
{
    try { __ess.Cancel(); } catch { }
    throw;
}
// witness (post-scope readback)
__st_S1 = doc.GetElement(__sid_S1) as Autodesk.Revit.DB.Architecture.Stairs;
var __rb_S1 = new Dictionary<string, object>();
__rb_S1["id"] = __sid_S1.ToString();
    try { var __stampParam = __st_S1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb_S1["stamp"] = __stampParam.AsString(); } catch { }
if (__st_S1 != null)
{
    try { __rb_S1["runs"] = __st_S1.GetStairsRuns().Count; } catch { }
    try { __rb_S1["risers"] = __st_S1.ActualRisersNumber; } catch { }
    try { var __tid = __st_S1.GetTypeId(); var __ty = doc.GetElement(__tid);
          if (__ty != null) __rb_S1["type_name"] = __ty.Name; } catch { }
    try { foreach (ElementId __rid_S1 in __st_S1.GetStairsRuns())
          {
              var __r_S1 = doc.GetElement(__rid_S1) as StairsRun;
              if (__r_S1 == null) continue;
              foreach (Curve __pc_S1 in __r_S1.GetStairsPath())
              {
                  var __pa_S1 = __pc_S1 as Arc;
                  if (__pa_S1 == null) continue;
                  __rb_S1["path_center_mm"] = new double[] { Math.Round(MM(__pa_S1.Center.X), 1), Math.Round(MM(__pa_S1.Center.Y), 1) };
                  __rb_S1["path_radius_mm"] = Math.Round(MM(__pa_S1.Radius), 1);
              }
          } } catch { }
}
__results["S1"] = __rb_S1;
__results["ok"] = true;
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