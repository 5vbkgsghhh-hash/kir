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
Railing __el_R1 = null;
ICollection<ElementId> __ids_R1 = null;
Element __hst_R1 = null;
using (Transaction __t = new Transaction(doc, "KIR: ограждение по существующей лестнице"))
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
        // create_railing(hosted) R1
        RailingType __ty_R1 = doc.GetElement(new ElementId(1201)) as RailingType;
        if (__ty_R1 == null) { __t.RollBack(); return __Refuse("R1", "ограждение: тип не найден (модель изменилась после grounding)"); }
        __hst_R1 = doc.GetElement(new ElementId(8888));
        if (__hst_R1 == null) { __t.RollBack(); return __Refuse("R1", "лестница/пандус-хост не найден (модель изменилась после grounding)"); }
        __ids_R1 = Railing.Create(doc, __hst_R1.Id, __ty_R1.Id, RailingPlacementPosition.Treads);
        if (__ids_R1 == null || __ids_R1.Count == 0) { __t.RollBack(); return __Refuse("R1", "создание ограждения на хосте не вернуло ни одного элемента"); }
        foreach (var __rid_R1 in __ids_R1)
        {
            var __rr_R1 = doc.GetElement(__rid_R1) as Railing;
            if (__rr_R1 == null) { __t.RollBack(); return __Refuse("R1", "созданное ограждение не читается как Railing"); }
            try { Parameter __cm = __rr_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:f5584826:R1"); } catch { }
            if (__el_R1 == null) __el_R1 = __rr_R1;
        }

        doc.Regenerate();

        // post R1
        {
            foreach (var __hid_R1 in __ids_R1)
            {
                var __hr_R1 = doc.GetElement(__hid_R1) as Railing;
                if (__hr_R1 == null || !__hr_R1.HasHost
                    || __hr_R1.HostId == null
                    || __hr_R1.HostId == ElementId.InvalidElementId
                    || __hr_R1.HostId.ToString() != __hst_R1.Id.ToString())
                    __post.Add("R1: ограждение не принадлежит запрошенному хосту (topology)");
            }
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

// witness R1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_R1.Id.ToString();
    __rb["railing_ids"] = __ids_R1.Select(__i => __i.ToString()).ToArray();
    __rb["created_count"] = __ids_R1.Count;
    try { var __stampParam = __el_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["R1"] = __rb;
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