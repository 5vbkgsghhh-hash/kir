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
Element __tg_S1 = null; Parameter __pp_S1 = null;
ElementId __delid_D1 = null;
using (Transaction __t = new Transaction(doc, "KIR: правка параметра и удаление"))
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
        // set_param S1
        __tg_S1 = doc.GetElement(new ElementId(7777));
        if (__tg_S1 == null) { __t.RollBack(); return __Refuse("S1", "элемент не найден (модель изменилась после grounding)"); }
        var __matches_S1 = __tg_S1.GetParameters("Комментарии");
        if (__matches_S1 == null || __matches_S1.Count == 0) { __t.RollBack(); return __Refuse("S1", "параметр «Комментарии» не найден у элемента"); }
        if (__matches_S1.Count != 1) { __t.RollBack(); return __Refuse("S1", "параметр «Комментарии» неоднозначен: найдено несколько параметров с этим именем"); }
        __pp_S1 = __matches_S1[0];
        if (__pp_S1.IsReadOnly) { __t.RollBack(); return __Refuse("S1", "параметр «Комментарии» только для чтения"); }
        if (!__pp_S1.Set("обработано KIR")) { __t.RollBack(); return __Refuse("S1", "Set(Комментарии) вернул false — несовместимый тип значения"); }

        // delete D1
        Element __tg_D1 = doc.GetElement(new ElementId(8888));
        if (__tg_D1 == null) { __t.RollBack(); return __Refuse("D1", "элемент не найден (модель изменилась после grounding)"); }
        __delid_D1 = __tg_D1.Id;
        try { doc.Delete(__delid_D1); }
        catch (Exception __ex_D1) { __t.RollBack(); return __Refuse("D1", "Delete: " + __ex_D1.Message); }

        doc.Regenerate();

        // post S1
        {
            if ((__pp_S1.AsString() ?? "") != "обработано KIR") __post.Add("S1: параметр не удержал значение (re-read)");
        }
        // post D1
        {
            if (doc.GetElement(__delid_D1) != null)
                __post.Add("D1: элемент всё ещё существует после Delete");
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

// witness S1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __tg_S1.Id.ToString();
    __rb["param"] = "Комментарии";
    try { __rb["value"] = (__pp_S1.StorageType == StorageType.String) ? (object)__pp_S1.AsString() : (object)__pp_S1.AsValueString(); } catch { }
    __results["S1"] = __rb;
}

// witness D1
{
    var __rb = new Dictionary<string, object>();
    __rb["deleted_id"] = __delid_D1.ToString();
    __results["D1"] = __rb;
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