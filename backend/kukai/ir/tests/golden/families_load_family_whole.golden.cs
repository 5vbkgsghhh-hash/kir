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
Family __fam_F1 = null; FamilySymbol __el_F1 = null; bool __already_F1 = false;
using (Transaction __t = new Transaction(doc, "KIR: загрузить семейство"))
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
        // load_family F1
        if (!System.IO.File.Exists("C:\\Lib\\Columns\\RC.rfa")) { __t.RollBack(); return __Refuse("F1", "файл не найден: C:\\Lib\\Columns\\RC.rfa"); }
        string __family_name_F1 = System.IO.Path.GetFileNameWithoutExtension("C:\\Lib\\Columns\\RC.rfa");
        var __families_F1 = new FilteredElementCollector(doc).OfClass(typeof(Family)).Cast<Family>()
            .Where(__f => __f.Name.Equals(__family_name_F1, StringComparison.OrdinalIgnoreCase))
            .OrderBy(__f => __f.Id.ToString(), StringComparer.Ordinal).ToList();
        if (__families_F1.Count > 1) { __t.RollBack(); return __Refuse("F1", "несколько уже загруженных семейств совпали с именем файла"); }
        if (__families_F1.Count == 1) { __fam_F1 = __families_F1[0]; __already_F1 = true; }
        else
        {
            bool __loaded_F1;
            try { __loaded_F1 = doc.LoadFamily("C:\\Lib\\Columns\\RC.rfa", out __fam_F1); }
            catch (Exception __ex_F1) { __t.RollBack(); return __Refuse("F1", "LoadFamily: " + __ex_F1.Message); }
            if (!__loaded_F1 || __fam_F1 == null) { __t.RollBack(); return __Refuse("F1", "LoadFamily не загрузил семейство"); }
        }
        __el_F1 = __fam_F1.GetFamilySymbolIds().Select(__id => doc.GetElement(__id) as FamilySymbol)
            .Where(__x => __x != null).OrderBy(__x => __x.Name, StringComparer.Ordinal)
            .ThenBy(__x => __x.Id.ToString(), StringComparer.Ordinal).FirstOrDefault();
        if (__el_F1 == null) { __t.RollBack(); return __Refuse("F1", "семейство не содержит ни одного типоразмера, который резолвится"); }
        if (!__el_F1.IsActive) { __el_F1.Activate(); doc.Regenerate(); }
        try { Parameter __cmt = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); if (__cmt != null && !__cmt.IsReadOnly) __cmt.Set("kir:e8d200f7:F1"); } catch { }

        doc.Regenerate();

        // post F1
        {
            if (!__el_F1.IsActive) __post.Add("F1: символ не активен после Activate (semantic)");
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
    __rb["type_name"] = __el_F1.Name;
    __rb["family_name"] = __fam_F1 != null ? __fam_F1.Name : null;
    __rb["already_loaded"] = __already_F1;
    try { var __stampParam = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
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