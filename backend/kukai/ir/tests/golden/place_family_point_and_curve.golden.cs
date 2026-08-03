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
FamilyInstance __el_P1 = null;
Autodesk.Revit.DB.Electrical.CableTray __el_T1 = null;
FamilyInstance __el_C1 = null;
Element __pfh_C1 = null;
using (Transaction __t = new Transaction(doc, "KIR: семейство в точку и семейство по кривой на хосте"))
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
        // place_family P1
        FamilySymbol __sy_P1 = doc.GetElement(new ElementId(800)) as FamilySymbol;
        if (__sy_P1 == null) { __t.RollBack(); return __Refuse("P1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_P1.IsActive) { __sy_P1.Activate(); doc.Regenerate(); }
        Element __lv_raw_P1 = doc.GetElement(new ElementId(42));
        Level __lv_P1 = __lv_raw_P1 as Level;
        if (__lv_P1 == null) { __t.RollBack(); return __Refuse("P1", (__lv_raw_P1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_P1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        XYZ __pfp_P1 = new XYZ(U(1000), U(2000), U(0) - __lv_P1.Elevation);
        __el_P1 = doc.Create.NewFamilyInstance(__pfp_P1, __sy_P1, __lv_P1, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (__el_P1 == null) { __t.RollBack(); return __Refuse("P1", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_P1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:eccd089b:P1"); } catch { }

        // create_cable_tray T1
        Element __lv_raw_T1 = doc.GetElement(new ElementId(42));
        Level __lv_T1 = __lv_raw_T1 as Level;
        if (__lv_T1 == null) { __t.RollBack(); return __Refuse("T1", (__lv_raw_T1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_T1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_T1 = Autodesk.Revit.DB.Electrical.CableTray.Create(doc, new ElementId(1002), P(155643, -5766, 565), P(155643, -5766, 4910), __lv_T1.Id);
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "CableTray.Create вернул null"); }
        try { Parameter __cm = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:eccd089b:T1"); } catch { }

        // place_family (кривая) C1
        FamilySymbol __sy_C1 = doc.GetElement(new ElementId(800)) as FamilySymbol;
        if (__sy_C1 == null) { __t.RollBack(); return __Refuse("C1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_C1.IsActive) { __sy_C1.Activate(); doc.Regenerate(); }
        __pfh_C1 = __el_T1;
        if (__pfh_C1 == null) { __t.RollBack(); return __Refuse("C1", "хост не найден"); }
        Line __pfc_C1 = Line.CreateBound(P(155643, -5766, 565), P(155643, -5766, 4910));
        __el_C1 = doc.Create.NewFamilyInstance(new Reference(__pfh_C1), __pfc_C1, __sy_C1);
        if (__el_C1 == null) { __t.RollBack(); return __Refuse("C1", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_C1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:eccd089b:C1"); } catch { }

        doc.Regenerate();

        // post P1
        {
            var __loc = __el_P1.Location as LocationPoint;
            if (__loc == null) __post.Add("P1: нет LocationPoint");
            else if (Math.Abs(MM(__loc.Point.X) - 1000) > 5.0 || Math.Abs(MM(__loc.Point.Y) - 2000) > 5.0 || Math.Abs(MM(__loc.Point.Z) - 0) > 5.0)
                __post.Add("P1: location mismatch (geometry)");
            Parameter __lp = __el_P1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_P1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_P1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_P1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("P1: level binding mismatch (topology)");
        }
        // post T1
        {
            var __lc = __el_T1.Location as LocationCurve;
            if (__lc == null) __post.Add("T1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 155643, 2) + Math.Pow(MM(__a.Y) - -5766, 2) + Math.Pow(MM(__a.Z) - 565, 2);
                double __db = Math.Pow(MM(__b.X) - 155643, 2) + Math.Pow(MM(__b.Y) - -5766, 2) + Math.Pow(MM(__b.Z) - 565, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 155643) > 5.0 || Math.Abs(MM(__e0.Y) - -5766) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 155643) > 5.0 || Math.Abs(MM(__e1.Y) - -5766) > 5.0 || Math.Abs(MM(__e0.Z) - 565) > 5.0 || Math.Abs(MM(__e1.Z) - 4910) > 5.0)
                    __post.Add("T1: endpoints mismatch (geometry)");
            }
            var __bp = __el_T1.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("T1: level binding mismatch (topology)");
        }
        // post C1
        {
            var __lc = __el_C1.Location as LocationCurve;
            if (__lc == null) __post.Add("C1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __d0 = Math.Pow(MM(__a.X) - 155643, 2) + Math.Pow(MM(__a.Y) - -5766, 2) + Math.Pow(MM(__a.Z) - 565, 2);
                double __d1 = Math.Pow(MM(__b.X) - 155643, 2) + Math.Pow(MM(__b.Y) - -5766, 2) + Math.Pow(MM(__b.Z) - 565, 2);
                var __e0 = __d0 <= __d1 ? __a : __b; var __e1 = __d0 <= __d1 ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 155643) > 5.0 || Math.Abs(MM(__e0.Y) - -5766) > 5.0 || Math.Abs(MM(__e0.Z) - 565) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 155643) > 5.0 || Math.Abs(MM(__e1.Y) - -5766) > 5.0 || Math.Abs(MM(__e1.Z) - 4910) > 5.0)
                    __post.Add("C1: endpoints mismatch (geometry)");
            }
            if (__el_C1.Host == null || __el_C1.Host.Id.ToString() != __pfh_C1.Id.ToString())
                __post.Add("C1: host mismatch (topology)");
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

// witness P1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_P1.Id.ToString();
    try { var __stampParam = __el_P1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_P1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_P1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["P1"] = __rb;
}

// witness T1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_T1.Id.ToString();
    try { var __stampParam = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_T1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_T1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["T1"] = __rb;
}

// witness C1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_C1.Id.ToString();
    try { var __sp = __el_C1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__sp != null) __rb["stamp"] = __sp.AsString(); } catch { }
    try { var __lc2 = __el_C1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { if (__el_C1.Host != null) __rb["host_id"] = __el_C1.Host.Id.ToString(); } catch { }
    try { var __tid = __el_C1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["C1"] = __rb;
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