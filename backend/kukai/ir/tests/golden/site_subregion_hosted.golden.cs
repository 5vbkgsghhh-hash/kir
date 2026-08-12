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
SiteSubRegion __sr_R1 = null;
TopographySurface __el_R1 = null;
List<CurveLoop> __loops_R1 = null;
Element __hst_R1 = null;
using (Transaction __t = new Transaction(doc, "KIR: подобласть площадки под газон, с закруглённым краем"))
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
        // create_site_subregion R1
        __hst_R1 = doc.GetElement(new ElementId(7777));
        if (__hst_R1 == null) { __t.RollBack(); return __Refuse("R1", "топоповерхность-хозяин не найдена (модель изменилась после grounding)"); }
        __loops_R1 = new List<CurveLoop>();
        CurveLoop __ol_R1 = new CurveLoop();
        __ol_R1.Append(Line.CreateBound(P(1000.0, 1000.0, 0), P(9000.0, 1000.0, 0)));
        __ol_R1.Append(Arc.Create(P(9000.0, 1000.0, 0), P(9000.0, 7000.0, 0), P(10050.0, 4000.0, 0)));
        __ol_R1.Append(Line.CreateBound(P(9000.0, 7000.0, 0), P(1000.0, 7000.0, 0)));
        __ol_R1.Append(Line.CreateBound(P(1000.0, 7000.0, 0), P(1000.0, 1000.0, 0)));
        __loops_R1.Add(__ol_R1);
        __sr_R1 = SiteSubRegion.Create(doc, __loops_R1, __hst_R1.Id);
        if (__sr_R1 == null) { __t.RollBack(); return __Refuse("R1", "создание подобласти площадки вернуло null"); }
        __el_R1 = __sr_R1.TopographySurface;
        if (__el_R1 == null) { __t.RollBack(); return __Refuse("R1", "подобласть создана, но её поверхность не читается — элемента, которым можно владеть, нет"); }
        try { Parameter __cm = __el_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9702dbd8:R1"); } catch { }

        doc.Regenerate();

        // post R1
        {
            if (!__el_R1.IsSiteSubRegion)
                __post.Add("R1: созданная поверхность не помечена как подобласть (semantic)");
            double __bx0_R1 = 0;
            double __bx1_R1 = 0;
            double __by0_R1 = 0;
            double __by1_R1 = 0;
            bool __bany_R1 = false;
            var __bnd_R1 = __sr_R1.GetBoundary();
            if (__bnd_R1 != null)
                foreach (CurveLoop __bcl_R1 in __bnd_R1)
                    foreach (Curve __bc_R1 in __bcl_R1)
                        foreach (XYZ __bt_R1 in __bc_R1.Tessellate())
                        {
                            double __bmx_R1 = MM(__bt_R1.X);
                            double __bmy_R1 = MM(__bt_R1.Y);
                            if (!__bany_R1)
                            {
                                __bx0_R1 = __bmx_R1;
                                __bx1_R1 = __bmx_R1;
                                __by0_R1 = __bmy_R1;
                                __by1_R1 = __bmy_R1;
                                __bany_R1 = true;
                            }
                            else
                            {
                                if (__bmx_R1 < __bx0_R1) __bx0_R1 = __bmx_R1;
                                if (__bmx_R1 > __bx1_R1) __bx1_R1 = __bmx_R1;
                                if (__bmy_R1 < __by0_R1) __by0_R1 = __bmy_R1;
                                if (__bmy_R1 > __by1_R1) __by1_R1 = __bmy_R1;
                            }
                        }
            if (!__bany_R1)
                __post.Add("R1: GetBoundary() не вернул ни одной кривой (geometry)");
            else if (Math.Abs(__bx0_R1 - 1000.0) > 50.0 || Math.Abs(__bx1_R1 - 10050.0) > 50.0 ||
                     Math.Abs(__by0_R1 - 1000.0) > 50.0 || Math.Abs(__by1_R1 - 7000.0) > 50.0)
                __post.Add("R1: boundary bbox mismatch (geometry)");
            var __hid_R1 = __sr_R1.HostId;
            if (__hid_R1 == null || __hid_R1 == ElementId.InvalidElementId)
                __post.Add("R1: подобласть не принадлежит ни одной топоповерхности (topology)");
            else if (__hid_R1.ToString() != __hst_R1.Id.ToString())
                __post.Add("R1: подобласть принадлежит не запрошенной топоповерхности (topology)");
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
    try { __rb["host_topography_id"] = __sr_R1.HostId.ToString(); } catch { }
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