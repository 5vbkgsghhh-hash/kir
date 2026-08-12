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
MultistoryStairs __el_MS1 = null; Autodesk.Revit.DB.Architecture.Stairs __mst_MS1 = null; HashSet<string> __want_MS1 = new HashSet<string>();
using (Transaction __t = new Transaction(doc, "KIR: марш, размноженный на два этажа"))
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
        // create_multistory_stairs MS1
        Element __tg_MS1 = doc.GetElement(new ElementId(8145901));
        if (__tg_MS1 == null) { __t.RollBack(); return __Refuse("MS1", "элемент не найден (модель изменилась после grounding)"); }
        __mst_MS1 = __tg_MS1 as Autodesk.Revit.DB.Architecture.Stairs;
        if (__mst_MS1 == null) { __t.RollBack(); return __Refuse("MS1", "указанный элемент — не лестница"); }
        if (!Autodesk.Revit.DB.Architecture.MultistoryStairs.IsAcceptableForMultistoryStairs(__mst_MS1)) { __t.RollBack(); return __Refuse("MS1", "Revit не принимает эту лестницу как основу многоэтажной (не компонентная либо уже входит в другую)"); }
        __want_MS1.Add(new ElementId(42).ToString());
        __want_MS1.Add(new ElementId(43).ToString());
        __el_MS1 = Autodesk.Revit.DB.Architecture.MultistoryStairs.Create(__mst_MS1);
        if (__el_MS1 == null) { __t.RollBack(); return __Refuse("MS1", "MultistoryStairs.Create вернул null"); }
        doc.Regenerate();
        var __want2_MS1 = new HashSet<string>();
        foreach (ElementId __sl_MS1 in __el_MS1.GetAllConnectedLevels())
        {
            if (!__want_MS1.Contains(__sl_MS1.ToString())) { __t.RollBack(); return __Refuse("MS1", "уровень " + __sl_MS1.ToString() + " лестница занимает уже сейчас, но в levels он не назван — отсоединение не запрашивалось"); }
            __want2_MS1.Add(__sl_MS1.ToString());
        }
        System.Collections.Generic.ISet<ElementId> __add_MS1 = new HashSet<ElementId>();
        if (!__want2_MS1.Contains(new ElementId(42).ToString()))
        {
            if (!__el_MS1.CanConnectLevel(new ElementId(42))) { __t.RollBack(); return __Refuse("MS1", "Revit не подключает уровень 42 к этой многоэтажной лестнице (между базой и верхом обычного марша или уже подключён иначе)"); }
            __add_MS1.Add(new ElementId(42));
        }
        if (!__want2_MS1.Contains(new ElementId(43).ToString()))
        {
            if (!__el_MS1.CanConnectLevel(new ElementId(43))) { __t.RollBack(); return __Refuse("MS1", "Revit не подключает уровень 43 к этой многоэтажной лестнице (между базой и верхом обычного марша или уже подключён иначе)"); }
            __add_MS1.Add(new ElementId(43));
        }
        if (__add_MS1.Count > 0)
        {
            try { __el_MS1.ConnectLevels(__add_MS1); }
            catch (Exception __ex_MS1) { __t.RollBack(); return __Refuse("MS1", "ConnectLevels: " + __ex_MS1.Message); }
        }
        doc.Regenerate();
        try { Parameter __cm = __el_MS1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:95e770e8:MS1"); } catch { }

        doc.Regenerate();

        // post MS1
        {
            var __rr_MS1 = __el_MS1 == null ? null : doc.GetElement(__el_MS1.Id) as MultistoryStairs;
            var __got_MS1 = new HashSet<string>();
            if (__rr_MS1 == null)
                __post.Add("MS1: элемент не перечитывается из документа как MultistoryStairs (semantic)");
            else
            {
                foreach (ElementId __gl_MS1 in __rr_MS1.GetAllConnectedLevels())
                    __got_MS1.Add(__gl_MS1.ToString());
                if (!__got_MS1.SetEquals(__want_MS1))
                    __post.Add("MS1: множество уровней лестницы не совпало с запрошенным (topology)");
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

// witness MS1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_MS1.Id.ToString();
    try { var __stampParam = __el_MS1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __rl_MS1 = new List<string>();
        foreach (ElementId __wl_MS1 in __el_MS1.GetAllConnectedLevels())
            __rl_MS1.Add(__wl_MS1.ToString());
        __rl_MS1.Sort();
        __rb["connected_level_ids"] = __rl_MS1.ToArray(); } catch { }
    try { var __rs_MS1 = __el_MS1.GetAllStairsIds();
        __rb["stairs_count"] = __rs_MS1 == null ? 0 : __rs_MS1.Count;
    } catch { }
    __results["MS1"] = __rb;
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