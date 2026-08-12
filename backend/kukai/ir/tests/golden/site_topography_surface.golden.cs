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
TopographySurface __el_T1 = null;
List<XYZ> __pts_T1 = null;
using (Transaction __t = new Transaction(doc, "KIR: рельеф участка по съёмочным точкам"))
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
        // create_topography(surface) T1
        __pts_T1 = new List<XYZ>();
        __pts_T1.Add(P(0.0, 0.0, 0.0));
        __pts_T1.Add(P(24000.0, 0.0, 800.0));
        __pts_T1.Add(P(24000.0, 18000.0, 1500.0));
        __pts_T1.Add(P(0.0, 18000.0, 400.0));
        __pts_T1.Add(P(12000.0, 9000.0, 1100.0));
        __el_T1 = TopographySurface.Create(doc, __pts_T1);
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "создание поверхности рельефа вернуло null"); }
        try { Parameter __cm = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:d231299a:T1"); } catch { }

        doc.Regenerate();

        // post T1
        {
            var __tp_T1 = __el_T1.GetPoints();
            int __miss_T1 = 0;
            if (__tp_T1 == null || __tp_T1.Count == 0)
                __post.Add("T1: GetPoints() не вернул ни одной точки (geometry)");
            else
            {
                foreach (XYZ __ep_T1 in __pts_T1)
                {
                    bool __hit_T1 = false;
                    foreach (XYZ __q_T1 in __tp_T1)
                        if (__ep_T1.DistanceTo(__q_T1) <= U(1.0)) { __hit_T1 = true; break; }
                    if (!__hit_T1) __miss_T1++;
                }
                if (__miss_T1 > 0)
                    __post.Add(__miss_T1.ToString() + " из " + __pts_T1.Count.ToString() + " "
                        + "T1: описанных точек рельефа нет в GetPoints() (geometry)");
            }
            var __bb = __el_T1.get_BoundingBox(null);
            if (__bb == null) __post.Add("T1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0.0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 24000.0) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0.0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 18000.0) > 50.0)
                __post.Add("T1: bbox extents mismatch (geometry)");
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