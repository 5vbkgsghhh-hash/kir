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
Element __hst_O1 = null;
using (Transaction __t = new Transaction(doc, "KIR: проём в существующем перекрытии, вертикальный рез"))
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
        // create_opening(host_face) O1
        __hst_O1 = doc.GetElement(new ElementId(8145901));
        if (__hst_O1 == null) { __t.RollBack(); return __Refuse("O1", "носитель проёма не найден (модель изменилась после grounding)"); }
        doc.Regenerate();
        var __hbb_O1 = __hst_O1.get_BoundingBox(null);
        if (__hbb_O1 == null) { __t.RollBack(); return __Refuse("O1", "у носителя проёма нет габарита — отметку профиля взять неоткуда, а нулевая была бы тихой неправдой"); }
        double __z_O1 = (__hbb_O1.Min.Z + __hbb_O1.Max.Z) / 2.0;
        CurveArray __ca_O1 = new CurveArray();
        __ca_O1.Append(Line.CreateBound(new XYZ(U(1000), U(1000), __z_O1), new XYZ(U(3000), U(1000), __z_O1)));
        __ca_O1.Append(Line.CreateBound(new XYZ(U(3000), U(1000), __z_O1), new XYZ(U(3000), U(3000), __z_O1)));
        __ca_O1.Append(Line.CreateBound(new XYZ(U(3000), U(3000), __z_O1), new XYZ(U(1000), U(3000), __z_O1)));
        __ca_O1.Append(Line.CreateBound(new XYZ(U(1000), U(3000), __z_O1), new XYZ(U(1000), U(1000), __z_O1)));
        __el_O1 = doc.Create.NewOpening(__hst_O1, __ca_O1, false);
        if (__el_O1 == null) { __t.RollBack(); return __Refuse("O1", "создание проёма по профилю вернуло null"); }
        try { Parameter __cm = __el_O1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6cf8a99a:O1"); } catch { }

        doc.Regenerate();

        // post O1
        {
            var __hh_O1 = __el_O1.Host;
            if (__hh_O1 == null)
                __post.Add("O1: у проёма нет носителя (topology)");
            else if (__hh_O1.Id.ToString() != __hst_O1.Id.ToString())
                __post.Add("O1: проём не принадлежит запрошенному носителю (topology)");
            var __bc_O1 = __el_O1.BoundaryCurves;
            double __ox0_O1 = 0;
            double __ox1_O1 = 0;
            double __oy0_O1 = 0;
            double __oy1_O1 = 0;
            int __on_O1 = 0;
            if (__bc_O1 != null)
            {
                foreach (Curve __c_O1 in __bc_O1)
                {
                    for (int __k_O1 = 0; __k_O1 < 2; __k_O1++)
                    {
                        var __pt_O1 = __c_O1.GetEndPoint(__k_O1);
                        double __px_O1 = MM(__pt_O1.X);
                        double __py_O1 = MM(__pt_O1.Y);
                        if (__on_O1 == 0) { __ox0_O1 = __px_O1; __ox1_O1 = __px_O1; __oy0_O1 = __py_O1; __oy1_O1 = __py_O1; }
                        else { __ox0_O1 = Math.Min(__ox0_O1, __px_O1); __ox1_O1 = Math.Max(__ox1_O1, __px_O1);
                               __oy0_O1 = Math.Min(__oy0_O1, __py_O1); __oy1_O1 = Math.Max(__oy1_O1, __py_O1); }
                        __on_O1++;
                    }
                }
            }
            if (__on_O1 == 0)
                __post.Add("O1: у проёма нет граничных кривых (geometry)");
            else
            {
                if (Math.Abs(__ox0_O1 - 1000) > 50.0 || Math.Abs(__ox1_O1 - 3000) > 50.0
                    || Math.Abs(__oy0_O1 - 1000) > 50.0 || Math.Abs(__oy1_O1 - 3000) > 50.0)
                    __post.Add("O1: opening extents mismatch (geometry)");
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