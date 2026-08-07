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
Opening __el_O1 = null;
Wall __hw_O1 = null;
using (Transaction __t = new Transaction(doc, "KIR: прямоугольный проём в существующей стене"))
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
        // create_opening(wall_rect) O1
        __hw_O1 = doc.GetElement(new ElementId(8145901)) as Wall;
        if (__hw_O1 == null) { __t.RollBack(); return __Refuse("O1", "носитель проёма не читается как стена (модель изменилась после grounding или id указывает не на стену)"); }
        doc.Regenerate();
        __el_O1 = doc.Create.NewOpening(__hw_O1, P(1000.0, 0.0, 900.0), P(2500.0, 0.0, 2400.0));
        if (__el_O1 == null) { __t.RollBack(); return __Refuse("O1", "создание прямоугольного проёма в стене вернуло null (наклонные и многослойные стены прямоугольных проёмов не поддерживают — ремарка спеки)"); }
        try { Parameter __cm = __el_O1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:f078e807:O1"); } catch { }

        doc.Regenerate();

        // post O1
        {
            var __hh_O1 = __el_O1.Host;
            if (__hh_O1 == null)
                __post.Add("O1: у проёма нет носителя (topology)");
            else if (__hh_O1.Id.ToString() != __hw_O1.Id.ToString())
                __post.Add("O1: проём не принадлежит запрошенной стене (topology)");
            var __br_O1 = __el_O1.BoundaryRect;
            int __brn_O1 = __br_O1 == null ? 0 : System.Linq.Enumerable.Count(__br_O1);
            if (!__el_O1.IsRectBoundary || __brn_O1 != 2)
                __post.Add("O1: граница проёма не прямоугольник (geometry)");
            else
            {
                double __bz0_O1 = Math.Min(MM(__br_O1[0].Z), MM(__br_O1[1].Z));
                double __bz1_O1 = Math.Max(MM(__br_O1[0].Z), MM(__br_O1[1].Z));
                double __bw_O1 = Math.Sqrt(
                    Math.Pow(MM(__br_O1[0].X) - MM(__br_O1[1].X), 2)
                  + Math.Pow(MM(__br_O1[0].Y) - MM(__br_O1[1].Y), 2));
                if (Math.Abs(__bz0_O1 - 900.0) > 50.0 || Math.Abs(__bz1_O1 - 2400.0) > 50.0
                    || Math.Abs(__bw_O1 - 1500.0) > 50.0)
                    __post.Add("O1: rect extents mismatch (geometry)");
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

// witness O1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_O1.Id.ToString();
    try { var __stampParam = __el_O1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_O1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_O1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["O1"] = __rb;
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