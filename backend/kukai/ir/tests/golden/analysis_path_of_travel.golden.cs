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
Autodesk.Revit.DB.Analysis.PathOfTravel __el_PT1 = null;
View __vw_PT1 = null;
ViewPlan __vp_PT1 = null;
using (Transaction __t = new Transaction(doc, "KIR: путь эвакуации от точки до выхода"))
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
        // create_path_of_travel PT1
        __vw_PT1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_PT1 == null) { __t.RollBack(); return __Refuse("PT1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        __vp_PT1 = __vw_PT1 as ViewPlan;
        if (__vp_PT1 == null || __vp_PT1.IsTemplate || __vp_PT1.ViewType != ViewType.FloorPlan) { __t.RollBack(); return __Refuse("PT1", "in_view не план этажа — PathOfTravel.Create принимает только вид в плане (документировано ArgumentException «View is not a floor plan view»)"); }
        Autodesk.Revit.DB.Analysis.PathOfTravelCalculationStatus __potstatus_PT1;
        __el_PT1 = Autodesk.Revit.DB.Analysis.PathOfTravel.Create(__vp_PT1, P(0, 0, 0), P(12000, 5000, 0), out __potstatus_PT1);
        if (__el_PT1 == null) { __t.RollBack(); return __Refuse("PT1", "маршрут между заданными точками не найден, статус расчёта: " + __potstatus_PT1.ToString()); }
        if (__potstatus_PT1 != Autodesk.Revit.DB.Analysis.PathOfTravelCalculationStatus.Success) { __t.RollBack(); return __Refuse("PT1", "расчёт маршрута завершился не успехом, статус: " + __potstatus_PT1.ToString()); }
        try { Parameter __cm = __el_PT1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:71339f68:PT1"); } catch { }

        doc.Regenerate();

        // post PT1
        {
            var __ps_PT1 = __el_PT1.PathStart;
            var __pe_PT1 = __el_PT1.PathEnd;
            double __vtol_PT1 = doc.Application.VertexTolerance;
            if (__ps_PT1 == null || __pe_PT1 == null
                || Math.Abs(__ps_PT1.X - U(0)) > __vtol_PT1
                || Math.Abs(__ps_PT1.Y - U(0)) > __vtol_PT1
                || Math.Abs(__pe_PT1.X - U(12000)) > __vtol_PT1
                || Math.Abs(__pe_PT1.Y - U(5000)) > __vtol_PT1)
                __post.Add("PT1: PathStart/PathEnd построенного маршрута не совпали с заданными точками в плане (geometry)");
            var __cvs_PT1 = __el_PT1.GetCurves();
            double __len_PT1 = 0.0;
            if (__cvs_PT1 != null)
                for (int __k = 0; __k < __cvs_PT1.Count; __k++)
                    __len_PT1 += __cvs_PT1[__k].Length;
            if (__cvs_PT1 == null || __cvs_PT1.Count < 1)
                __post.Add("PT1: маршрут построен без единой кривой (geometry)");
            else if (__len_PT1 < U(13000.0) - __vtol_PT1)
                __post.Add("PT1: длина построенного маршрута меньше прямой между заданными точками (geometry)");
            var __ov_PT1 = __el_PT1.OwnerViewId;
            if (__ov_PT1 == null || __ov_PT1.ToString() != "900")
                __post.Add("PT1: построенный маршрут принадлежит не заказанному виду (topology)");
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

// witness PT1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_PT1.Id.ToString();
    try { var __stampParam = __el_PT1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["start_mm"] = new double[] { Math.Round(MM(__el_PT1.PathStart.X), 1), Math.Round(MM(__el_PT1.PathStart.Y), 1), Math.Round(MM(__el_PT1.PathStart.Z), 1) }; } catch { }
    try { __rb["end_mm"] = new double[] { Math.Round(MM(__el_PT1.PathEnd.X), 1), Math.Round(MM(__el_PT1.PathEnd.Y), 1), Math.Round(MM(__el_PT1.PathEnd.Z), 1) }; } catch { }
    try { var __rbc = __el_PT1.GetCurves();
        double __rbl = 0.0;
        if (__rbc != null)
            for (int __q = 0; __q < __rbc.Count; __q++) __rbl += __rbc[__q].Length;
        __rb["segments"] = __rbc == null ? 0 : __rbc.Count;
        __rb["length_mm"] = Math.Round(MM(__rbl), 1);
    } catch { }
    try { __rb["view_id"] = __el_PT1.OwnerViewId.ToString(); } catch { }
    __results["PT1"] = __rb;
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