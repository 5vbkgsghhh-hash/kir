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
var __ess = new StairsEditScope(doc, "KIR stairs: прямой марш между этажами");
ElementId __sid_S1 = __ess.Start(__base_S1.Id, __top_S1.Id);
Autodesk.Revit.DB.Architecture.Stairs __st_S1 = null;
try
{
    using (Transaction __t = new Transaction(doc, "KIR: stairs run"))
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
        { try { __ess.Cancel(); } catch { } return __Refuse("S1", "transaction start status: " + __startStatus.ToString()); }
        __KirStairsFailures.Seen.Clear();
        __KirStairsFailures.Warned.Clear();
        __KirStairsFailures.Resolved.Clear();
        __KirStairsFailures.Attempts.Clear();
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirStairsFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        StairsRun __run_S1 = StairsRun.CreateStraightRun(doc, __sid_S1,
            Line.CreateBound(
                new XYZ(U(0), U(0), __base_S1.Elevation),
                new XYZ(U(5000), U(0), __base_S1.Elevation)),
            StairsRunJustification.Center);
        if (__run_S1 == null)
        { __t.RollBack(); __ess.Cancel(); return __Refuse("S1", "CreateStraightRun вернул null"); }
        try { __run_S1.ActualRunWidth = U(1200.0); } catch { }
        doc.Regenerate();
        __st_S1 = doc.GetElement(__sid_S1) as Autodesk.Revit.DB.Architecture.Stairs;
        if (__st_S1 == null)
        { __t.RollBack(); __ess.Cancel(); return __Refuse("S1", "лестница не материализовалась"); }
        try { Parameter __cm = __st_S1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:dbf51211:S1"); } catch { }
        var __bl = __st_S1.get_Parameter(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM);
        if (__bl == null || __bl.AsElementId().ToString() != __base_S1.Id.ToString())
            __post.Add("S1: base level mismatch (topology)");
        var __tl = __st_S1.get_Parameter(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM);
        if (__tl == null || __tl.AsElementId().ToString() != __top_S1.Id.ToString())
            __post.Add("S1: top level mismatch (topology)");
        if (__st_S1.GetStairsRuns().Count < 1)
            __post.Add("S1: нет маршей (semantic)");
        try
        {
            int __desR_S1 = __st_S1.DesiredRisersNumber;
            int __actR_S1 = __st_S1.ActualRisersNumber;
            if (__desR_S1 > 0 && __actR_S1 > __desR_S1)
            {
                double __td_S1 = MM(__st_S1.ActualTreadDepth);
                __post.Add("S1: марш перелетает top_level — подступенков "
                    + __actR_S1 + " против нужных " + __desR_S1
                    + "; длина марша должна быть "
                    + Math.Round((__desR_S1 - 1) * __td_S1, 1)
                    + " мм при проступи " + Math.Round(__td_S1, 1)
                    + " мм (vertical extent, geometry)");
            }
        }
        catch { __post.Add("S1: число подступенков непрочитаемо (geometry)"); }
        try { if (Math.Abs(MM(__run_S1.ActualRunWidth) - 1200.0) > 5.0)
            __post.Add("S1: stairs run width mismatch (geometry)"); }
        catch { __post.Add("S1: stairs run width unreadable (geometry)"); }
        if (__post.Count > 0)
        {
            var __rollbackStatus = __t.RollBack(); __ess.Cancel();
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = __post;
            __er["commit_status"] = __rollbackStatus.ToString();
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        { try { __ess.Cancel(); } catch { } var __refused = __Refuse("S1", "transaction commit status: " + __commitStatus.ToString()
            + (__KirStairsFailures.Seen.Count > 0 ? " | Revit: " + String.Join(" ; ", __KirStairsFailures.Seen) : ""));
          __refused["commit_status"] = __commitStatus.ToString();
          if (__KirStairsFailures.Warned.Count > 0) __refused["revit_warnings"] = __KirStairsFailures.Warned;
          if (__KirStairsFailures.Resolved.Count > 0) __refused["revit_errors_resolved"] = __KirStairsFailures.Resolved;
          return __refused; }
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
    try { __rb_S1["risers_desired"] = __st_S1.DesiredRisersNumber; } catch { }
    try { __rb_S1["tread_depth_mm"] = Math.Round(MM(__st_S1.ActualTreadDepth), 1); } catch { }
    try { __rb_S1["riser_height_mm"] = Math.Round(MM(__st_S1.ActualRiserHeight), 1); } catch { }
    try { __rb_S1["run_length_for_top_mm"] = Math.Round((__st_S1.DesiredRisersNumber - 1) * MM(__st_S1.ActualTreadDepth), 1); } catch { }
    try { var __tid = __st_S1.GetTypeId(); var __ty = doc.GetElement(__tid);
          if (__ty != null) __rb_S1["type_name"] = __ty.Name; } catch { }
}
__results["S1"] = __rb_S1;
if (__KirStairsFailures.Warned.Count > 0)
    __results["revit_warnings"] = __KirStairsFailures.Warned;
if (__KirStairsFailures.Resolved.Count > 0)
    __results["revit_errors_resolved"] = __KirStairsFailures.Resolved;
__results["ok"] = true;
return __results;
}

private class __KirStairsFailures : IFailuresPreprocessor
{
    // Ошибки КОПЯТСЯ, а не гасятся: программа, откатившаяся на
    // Commit, обязана назвать причину.
    public static List<string> Seen = new List<string>();
    // Предупреждения СНИМАЮТСЯ (иначе модальный диалог паркует
    // Revit) и ЗАПИСЫВАЮТСЯ (иначе программа зеленеет молча).
    public static List<object> Warned = new List<object>();
    // РАЗРЕШЁННЫЕ ОШИБКИ — третье ведро, и оно не сливается с двумя
    // первыми: «Revit решил за нас» это не предупреждение и не наш
    // отказ, а отдельный факт о модели.
    public static List<object> Resolved = new List<object>();
    // Счётчик попыток по роду отказа. RevitAPI.xml: ResolveFailure
    // БРОСАЕТ, если один и тот же отказ разрешают дважды тем же
    // типом, и требует «avoid an infinite loop».
    public static Dictionary<string, int> Attempts = new Dictionary<string, int>();
    public FailureProcessingResult PreprocessFailures(FailuresAccessor __fa)
    {
        bool __resolvedAny = false;
        bool __unresolvable = false;
        foreach (var __f in __fa.GetFailureMessages())
        {
            var __sev = __f.GetSeverity();
            var __ids = new List<string>();
            try { foreach (var __id in __f.GetFailingElementIds()) __ids.Add(__id.ToString()); } catch { }
            string __guid = "?";
            try { __guid = __f.GetFailureDefinitionId().Guid.ToString(); } catch { }
            string __text = "";
            try { __text = __f.GetDescriptionText(); } catch { }
            if (__sev == FailureSeverity.Warning)
            {
                try {
                    var __w = new Dictionary<string, object>();
                    __w["guid"] = __guid; __w["text"] = __text; __w["elements"] = __ids;
                    Warned.Add(__w);
                } catch { }
                try { __fa.DeleteWarning(__f); } catch { }
                continue;
            }
            // ОШИБКА. Записываем ВСЕГДА — до всякой попытки.
            try {
                Seen.Add(__sev.ToString() + ": " + __text
                    + (__ids.Count > 0 ? " [элементы: " + String.Join(",", __ids) + "]" : ""));
            } catch { }
            int __tried = 0;
            try { if (Attempts.ContainsKey(__guid)) __tried = Attempts[__guid]; } catch { }
            bool __has = false;
            try { __has = __f.HasResolutions(); } catch { }
            if (!__has || __tried >= 1)
            {
                // Неразрешимая ИЛИ уже пробованная: второй заход тем
                // же типом Revit запрещает, а другого у нас нет.
                __unresolvable = true;
                continue;
            }
            try {
                Attempts[__guid] = __tried + 1;
                string __cap = "";
                try { __cap = __f.GetDefaultResolutionCaption(); } catch { }
                __fa.ResolveFailure(__f);
                __resolvedAny = true;
                var __r = new Dictionary<string, object>();
                __r["guid"] = __guid; __r["text"] = __text;
                __r["elements"] = __ids; __r["resolution"] = __cap;
                Resolved.Add(__r);
            }
            catch { __unresolvable = true; }
        }
        // ПОРЯДОК ИСХОДОВ ЗНАЧИМ.
        // `Continue` не возвращается НИКОГДА при ошибке: он и есть
        // модальное окно (RevitAPI.xml, дословно).
        if (__unresolvable) return FailureProcessingResult.ProceedWithRollBack;
        if (__resolvedAny) return FailureProcessingResult.ProceedWithCommit;
        return FailureProcessingResult.Continue;
    }
}

private static class __KirPad
{  // pad scope: the fixed wrapper footer closes __KirPad, UserCode, namespace