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
FamilySymbol __el_T1 = null; bool __dupd_T1 = false;
Parameter __pw_T1 = null;
Parameter __pd_T1 = null;
Material __mat_T1 = null;
using (Transaction __t = new Transaction(doc, "KIR: жб колонна 400x400 из существующего типа"))
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
        // create_type T1
        FamilySymbol __src_T1 = doc.GetElement(new ElementId(500)) as FamilySymbol;
        if (__src_T1 == null) { __t.RollBack(); return __Refuse("T1", "source_type не найден (модель изменилась после grounding)"); }
        var __twins_T1 = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()
            .Where(__c => __c.Family.Id == __src_T1.Family.Id && __c.Name == "ЖБ 400x400").ToList();
        if (__twins_T1.Count > 1) { __t.RollBack(); return __Refuse("T1", "одноимённый тип неоднозначен; создание не выбирает первый"); }
        FamilySymbol __twin_T1 = __twins_T1.Count == 1 ? __twins_T1[0] : null;
        if (__twin_T1 != null) {
        string __owner_T1 = null;
        try { var __ownerParam_T1 = __twin_T1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS);
            if (__ownerParam_T1 != null) __owner_T1 = __ownerParam_T1.AsString(); } catch { }
        if (!String.Equals(__owner_T1, "kir:cabe5040:T1", StringComparison.Ordinal)) { __t.RollBack(); return __Refuse("T1", "одноимённый тип не принадлежит этому точному запросу; создание не изменяет существующие типы"); }
        __el_T1 = __twin_T1; }
        else
        {
            try { __el_T1 = __src_T1.Duplicate("ЖБ 400x400") as FamilySymbol; __dupd_T1 = true; }
            catch (Exception __ex_T1) { __t.RollBack(); return __Refuse("T1", "Duplicate: " + __ex_T1.Message); }
        }
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "Duplicate вернул null"); }
        if (__dupd_T1 && !__el_T1.IsActive) { __el_T1.Activate(); doc.Regenerate(); }
        var __pws_T1 = __el_T1.GetParameters("b");
        if (__pws_T1 == null || __pws_T1.Count != 1) { __t.RollBack(); return __Refuse("T1", "параметр «b» (width) не найден или неоднозначен на этом шаблоне семейства"); }
        __pw_T1 = __pws_T1[0];
        bool __length_T1_width = false;
        try { if (__pw_T1 != null && __pw_T1.StorageType == StorageType.Double) {
            var __definition_T1_width = __pw_T1.Definition;
            var __spec_T1_width = __definition_T1_width == null ? null : __definition_T1_width.GetDataType();
            __length_T1_width = __spec_T1_width != null && __spec_T1_width.Equals(SpecTypeId.Length);
        } } catch { }
        if (!__length_T1_width) { __t.RollBack(); return __Refuse("T1", "width: параметр должен иметь StorageType.Double и размерность Length; mm нельзя записывать или проверять как другую величину"); }
        if (__dupd_T1) {
        if (__pw_T1.IsReadOnly) { __t.RollBack(); return __Refuse("T1", "параметр «b» (width) read-only на этом шаблоне семейства"); }
        __pw_T1.Set(U(400.0));
        }
        var __pds_T1 = __el_T1.GetParameters("h");
        if (__pds_T1 == null || __pds_T1.Count != 1) { __t.RollBack(); return __Refuse("T1", "параметр «h» (depth) не найден или неоднозначен на этом шаблоне семейства"); }
        __pd_T1 = __pds_T1[0];
        bool __length_T1_depth = false;
        try { if (__pd_T1 != null && __pd_T1.StorageType == StorageType.Double) {
            var __definition_T1_depth = __pd_T1.Definition;
            var __spec_T1_depth = __definition_T1_depth == null ? null : __definition_T1_depth.GetDataType();
            __length_T1_depth = __spec_T1_depth != null && __spec_T1_depth.Equals(SpecTypeId.Length);
        } } catch { }
        if (!__length_T1_depth) { __t.RollBack(); return __Refuse("T1", "depth: параметр должен иметь StorageType.Double и размерность Length; mm нельзя записывать или проверять как другую величину"); }
        if (__dupd_T1) {
        if (__pd_T1.IsReadOnly) { __t.RollBack(); return __Refuse("T1", "параметр «h» (depth) read-only на этом шаблоне семейства"); }
        __pd_T1.Set(U(400.0));
        }
        var __materials_T1 = new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Material>()
            .Where(__m => __m.Name == "Бетон").ToList();
        if (__materials_T1.Count != 1) { __t.RollBack(); return __Refuse("T1", "материал «Бетон» отсутствует или неоднозначен в документе"); }
        __mat_T1 = __materials_T1[0];
        Parameter __pm_T1 = __el_T1.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM);
        if (__dupd_T1) {
        if (__pm_T1 == null || __pm_T1.IsReadOnly) { __t.RollBack(); return __Refuse("T1", "параметр материала (STRUCTURAL_MATERIAL_PARAM) недоступен на этом шаблоне семейства — материал не может быть применён"); }
        __pm_T1.Set(__mat_T1.Id);
        }
        if (__dupd_T1) { try { Parameter __cmt = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); if (__cmt == null) throw new InvalidOperationException("Type ownership stamp parameter missing"); if (__cmt.IsReadOnly) throw new InvalidOperationException("Type ownership stamp parameter is read-only"); if (!__cmt.Set("kir:cabe5040:T1") || __cmt.AsString() != "kir:cabe5040:T1") throw new InvalidOperationException("Type ownership stamp readback mismatch"); } catch (Exception __stampEx) { throw new InvalidOperationException("Type ownership stamp write failed: " + __stampEx.Message, __stampEx); } }

        doc.Regenerate();

        // post T1
        {
            if (__pw_T1 == null || Math.Abs(MM(__pw_T1.AsDouble()) - 400.0) > 0.5)
                __post.Add("T1: width не удержалась (re-read)");
            { if (__pd_T1 == null || Math.Abs(MM(__pd_T1.AsDouble()) - 400.0) > 0.5)
                  __post.Add("T1: depth не удержалась (re-read)"); }
            { var __pm2 = __el_T1.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM);
              if (__pm2 == null || __pm2.AsElementId() == null || __pm2.AsElementId().ToString() != __mat_T1.Id.ToString())
                  __post.Add("T1: материал не удержался (re-read)"); }
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

// witness T1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_T1.Id.ToString();
    __rb["name"] = __el_T1.Name;
    __rb["duplicated"] = __dupd_T1;
    try { var __stampParam = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["T1"] = __rb;
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