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
FamilyInstance __el_B1 = null;
using (Transaction __t = new Transaction(doc, "KIR: балка между колоннами на уровне"))
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
        // create_beam B1
        FamilySymbol __sy_B1 = doc.GetElement(new ElementId(1100)) as FamilySymbol;
        if (__sy_B1 == null) { __t.RollBack(); return __Refuse("B1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_B1.IsActive) { __sy_B1.Activate(); doc.Regenerate(); }
        Element __lv_raw_B1 = doc.GetElement(new ElementId(42));
        Level __lv_B1 = __lv_raw_B1 as Level;
        if (__lv_B1 == null) { __t.RollBack(); return __Refuse("B1", (__lv_raw_B1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_B1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        Line __ln_B1 = Line.CreateBound(P(0, 0, 3000), P(6000, 0, 3000));
        __el_B1 = doc.Create.NewFamilyInstance(__ln_B1, __sy_B1, __lv_B1, Autodesk.Revit.DB.Structure.StructuralType.Beam);
        if (__el_B1 == null) { __t.RollBack(); return __Refuse("B1", "NewFamilyInstance (балка) вернул null"); }
        try { Parameter __cm = __el_B1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9a1142ec:B1"); } catch { }

        doc.Regenerate();

        // post B1
        {
            var __lc = __el_B1.Location as LocationCurve;
            if (__lc == null) __post.Add("B1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2) + Math.Pow(MM(__a.Z) - 3000, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2) + Math.Pow(MM(__b.Z) - 3000, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0 || Math.Abs(MM(__e0.Z) - 3000) > 5.0 || Math.Abs(MM(__e1.Z) - 3000) > 5.0)
                    __post.Add("B1: endpoints mismatch (geometry)");
            }
            { var __rl = __el_B1.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
              if (__rl == null || __rl.AsElementId() == null
                  || __rl.AsElementId() == ElementId.InvalidElementId)
                __post.Add("B1: нет опорного уровня (topology)"); }
            if (__el_B1.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Beam)
                __post.Add("B1: StructuralType != Beam (semantic)");
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

// witness B1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_B1.Id.ToString();
    try { var __stampParam = __el_B1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_B1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_B1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rlp = __el_B1.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
        if (__rlp != null) { var __rle = doc.GetElement(__rlp.AsElementId());
            __rb["reference_level_id"] = __rlp.AsElementId().ToString();
            if (__rle != null) __rb["reference_level"] = __rle.Name; } } catch { }
    __results["B1"] = __rb;
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