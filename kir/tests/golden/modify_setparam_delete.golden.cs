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
List<string> __delalso_D1 = new List<string>();
List<object> __delpred_D1 = new List<object>();
int __delpredn_D1 = 0;
using (Transaction __t = new Transaction(doc, "KIR: правка параметра и удаление"))
{
    try
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
            return __Refuse("$program", "transaction start status: " + __startStatus.ToString());
        __KirMainFailures.Seen.Clear();
        __KirMainFailures.Warned.Clear();
        __KirMainFailures.Resolved.Clear();
        __KirMainFailures.Attempts.Clear();
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
        int __operationPostStart_S1 = __post.Count;
        // operation S1
        {
            if ((__pp_S1.AsString() ?? "") != "обработано KIR") __post.Add("S1: параметр не удержал значение (re-read)");
        }
        if (__post.Count > __operationPostStart_S1) { __t.RollBack(); return __Refuse("S1", String.Join(" ; ", __post.Skip(__operationPostStart_S1))); }


        // delete D1
        Element __tg_D1 = doc.GetElement(new ElementId(8888));
        if (__tg_D1 == null) { __t.RollBack(); return __Refuse("D1", "элемент не найден (модель изменилась после grounding)"); }
        __delid_D1 = __tg_D1.Id;
        try
        {
            ICollection<ElementId> __delpredids_D1 = __tg_D1.GetDependentElements(null);
            if (__delpredids_D1 != null)
                foreach (ElementId __delpx_D1 in __delpredids_D1)
                    if (__delpx_D1.ToString() != __delid_D1.ToString())
                    { __delpredn_D1++; if (__delpred_D1.Count < 10) __delpred_D1.Add(__delpx_D1.ToString()); }
        }
        catch { __delpredn_D1 = -1; }
        try
        {
            ICollection<ElementId> __delret_D1 = doc.Delete(__delid_D1);
            if (__delret_D1 != null)
                foreach (ElementId __delx_D1 in __delret_D1)
                    if (__delx_D1.ToString() != __delid_D1.ToString())
                        __delalso_D1.Add(__delx_D1.ToString());
        }
        catch (Exception __ex_D1) { __t.RollBack(); return __Refuse("D1", "Delete: " + __ex_D1.Message); }

        doc.Regenerate();


        // post D1
        {
            if (doc.GetElement(__delid_D1) != null)
                __post.Add("D1: элемент всё ещё существует после Delete");
        }
        if (__post.Count > 0)
        {
            var __rollbackStatus = __t.RollBack();
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = __post;
            __er["commit_status"] = __rollbackStatus.ToString();
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        {
            try { if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack(); } catch { }
            var __refused = __Refuse("$program", "transaction commit status: " + __commitStatus.ToString()
                + (__KirMainFailures.Seen.Count > 0 ? " | Revit: " + String.Join(" ; ", __KirMainFailures.Seen) : ""));
            __refused["commit_status"] = __commitStatus.ToString();
            if (__KirMainFailures.Warned.Count > 0)
                __refused["revit_warnings"] = __KirMainFailures.Warned;
            if (__KirMainFailures.Resolved.Count > 0)
                __refused["revit_errors_resolved"] = __KirMainFailures.Resolved;
            return __refused;
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
    __rb["collateral_count"] = __delalso_D1.Count;
    __rb["collateral_ids"] = __delalso_D1.GetRange(0, Math.Min(10, __delalso_D1.Count));
    __rb["collateral_capped"] = __delalso_D1.Count > 10;
    __rb["dependents_predicted"] = __delpred_D1;
    __rb["dependents_predicted_count"] = __delpredn_D1;
    __rb["dependents_actual_count"] = __delalso_D1.Count;
    __rb["dependents_prediction_matched"] = __delpredn_D1 < 0 ? (object)null : (object)(__delpredn_D1 == __delalso_D1.Count);
    __results["D1"] = __rb;
}

if (__KirMainFailures.Warned.Count > 0)
    __results["revit_warnings"] = __KirMainFailures.Warned;
if (__KirMainFailures.Resolved.Count > 0)
    __results["revit_errors_resolved"] = __KirMainFailures.Resolved;
__results["ok"] = true;
return __results;
}
private class __KirMainFailures : IFailuresPreprocessor
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
{