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

// witness R1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_R1.Id.ToString();
    __rb["created_ids"] = __ids_R1.Select(__i => __i.ToString()).ToArray();
    __rb["created_count"] = __ids_R1.Count;
    try { var __stampParam = __el_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["R1"] = __rb;
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