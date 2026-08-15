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
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirMainFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        // create_type T1
        FamilySymbol __src_T1 = doc.GetElement(new ElementId(500)) as FamilySymbol;
        if (__src_T1 == null) { __t.RollBack(); return __Refuse("T1", "source_type не найден (модель изменилась после grounding)"); }
        var __twin_T1 = new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)).Cast<FamilySymbol>()
            .FirstOrDefault(__c => __c.Family.Id == __src_T1.Family.Id && __c.Name == "ЖБ 400x400");
        if (__twin_T1 != null) { __el_T1 = __twin_T1; }
        else
        {
            try { __el_T1 = __src_T1.Duplicate("ЖБ 400x400") as FamilySymbol; __dupd_T1 = true; }
            catch (Exception __ex_T1) { __t.RollBack(); return __Refuse("T1", "Duplicate: " + __ex_T1.Message); }
        }
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "Duplicate вернул null"); }
        if (!__el_T1.IsActive) { __el_T1.Activate(); doc.Regenerate(); }
        var __pws_T1 = __el_T1.GetParameters("b");
        if (__pws_T1 == null || __pws_T1.Count != 1) { __t.RollBack(); return __Refuse("T1", "параметр «b» (width) не найден или неоднозначен на этом шаблоне семейства"); }
        __pw_T1 = __pws_T1[0];
        if (__pw_T1.IsReadOnly) { __t.RollBack(); return __Refuse("T1", "параметр «b» (width) read-only на этом шаблоне семейства"); }
        __pw_T1.Set(U(400.0));
        var __pds_T1 = __el_T1.GetParameters("h");
        if (__pds_T1 == null || __pds_T1.Count != 1) { __t.RollBack(); return __Refuse("T1", "параметр «h» (depth) не найден или неоднозначен на этом шаблоне семейства"); }
        __pd_T1 = __pds_T1[0];
        if (__pd_T1.IsReadOnly) { __t.RollBack(); return __Refuse("T1", "параметр «h» (depth) read-only на этом шаблоне семейства"); }
        __pd_T1.Set(U(400.0));
        __mat_T1 = new FilteredElementCollector(doc).OfClass(typeof(Material)).Cast<Material>()
            .FirstOrDefault(__m => __m.Name == "Бетон");
        if (__mat_T1 == null) { __t.RollBack(); return __Refuse("T1", "материал «Бетон» не найден в документе"); }
        Parameter __pm_T1 = __el_T1.get_Parameter(BuiltInParameter.STRUCTURAL_MATERIAL_PARAM);
        if (__pm_T1 == null || __pm_T1.IsReadOnly) { __t.RollBack(); return __Refuse("T1", "параметр материала (STRUCTURAL_MATERIAL_PARAM) недоступен на этом шаблоне семейства — материал не может быть применён"); }
        __pm_T1.Set(__mat_T1.Id);
        try { Parameter __cmt = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); if (__cmt != null && !__cmt.IsReadOnly) __cmt.Set("kir:cabe5040:T1"); } catch { }

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

// witness T1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_T1.Id.ToString();
    __rb["name"] = __el_T1.Name;
    __rb["duplicated"] = __dupd_T1;
    try { var __stampParam = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["T1"] = __rb;
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