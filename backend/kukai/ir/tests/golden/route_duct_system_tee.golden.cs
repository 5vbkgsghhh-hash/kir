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
Element __sysprobe_SYS1 = null;
var __segids_SYS1 = new List<string>();
MEPCurve __seg_SYS1_0 = null;
MEPCurve __seg_SYS1_1 = null;
MEPCurve __seg_SYS1_2 = null;
using (Transaction __t = new Transaction(doc, "KIR: тройник ОВ приточной сети"))
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
        // route_duct_system SYS1 — graph: 4 nodes, 3 segments
        Element __lv_raw_SYS1 = doc.GetElement(new ElementId(42));
        Level __lv_SYS1 = __lv_raw_SYS1 as Level;
        if (__lv_SYS1 == null) { __t.RollBack(); return __Refuse("SYS1", (__lv_raw_SYS1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_SYS1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __seg_SYS1_0 = Autodesk.Revit.DB.Mechanical.Duct.Create(doc, new ElementId(1001), new ElementId(1000), __lv_SYS1.Id, P(0.0, 0.0, 3000.0), P(3000.0, 0.0, 3000.0));
        if (__seg_SYS1_0 == null) { __t.RollBack(); return __Refuse("seg-0", "создание сегмента вернуло null"); }
        try { var __d0 = __seg_SYS1_0.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM); if (__d0 != null && !__d0.IsReadOnly) __d0.Set(U(250.0)); } catch { }
        __seg_SYS1_1 = Autodesk.Revit.DB.Mechanical.Duct.Create(doc, new ElementId(1001), new ElementId(1000), __lv_SYS1.Id, P(0.0, 0.0, 3000.0), P(-3000.0, 0.0, 3000.0));
        if (__seg_SYS1_1 == null) { __t.RollBack(); return __Refuse("seg-1", "создание сегмента вернуло null"); }
        try { var __d1 = __seg_SYS1_1.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM); if (__d1 != null && !__d1.IsReadOnly) __d1.Set(U(250.0)); } catch { }
        __seg_SYS1_2 = Autodesk.Revit.DB.Mechanical.Duct.Create(doc, new ElementId(1001), new ElementId(1000), __lv_SYS1.Id, P(0.0, 0.0, 3000.0), P(0.0, 3000.0, 3000.0));
        if (__seg_SYS1_2 == null) { __t.RollBack(); return __Refuse("seg-2", "создание сегмента вернуло null"); }
        try { var __d2 = __seg_SYS1_2.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM); if (__d2 != null && !__d2.IsReadOnly) __d2.Set(U(250.0)); } catch { }
        doc.Regenerate();  // connectors materialize after regen (CONNECT emit order)
        // fittings: connect segment ends by proximity to each junction node
        Func<Element, XYZ, Connector> __nearestFree = (Element __el, XYZ __p) =>
        {
            ConnectorManager __cm = (__el is MEPCurve) ? ((MEPCurve)__el).ConnectorManager : null;
            if (__cm == null) return null;
            Connector __best = null; double __bd = double.MaxValue;
            foreach (Connector __c in __cm.Connectors) {
                if (__c.IsConnected) continue;
                double __dd = __c.Origin.DistanceTo(__p);
                if (__dd < __bd) { __bd = __dd; __best = __c; }
            }
            return __best;
        };
        var __cn_0_0 = __nearestFree(__seg_SYS1_0, P(0.0, 0.0, 3000.0));
        var __cn_0_1 = __nearestFree(__seg_SYS1_1, P(0.0, 0.0, 3000.0));
        var __cn_0_2 = __nearestFree(__seg_SYS1_2, P(0.0, 0.0, 3000.0));
        if (__cn_0_0 == null || __cn_0_1 == null || __cn_0_2 == null) { __t.RollBack(); return __Refuse("SYS1:T", "нет свободного коннектора для фитинга"); }
        try { doc.Create.NewTeeFitting(__cn_0_0, __cn_0_1, __cn_0_2); }
        catch (Exception __exf) { __t.RollBack(); return __Refuse("SYS1:T", "NewTeeFitting: " + __exf.Message + " (angle=180.0deg, main 250.0/250.0mm, branch 250.0mm)"); }
        try { Parameter __cm = __seg_SYS1_0.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6048843f:SYS1:0"); } catch { }
        try { Parameter __cm = __seg_SYS1_1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6048843f:SYS1:1"); } catch { }
        try { Parameter __cm = __seg_SYS1_2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6048843f:SYS1:2"); } catch { }
        __segids_SYS1.Add(__seg_SYS1_0.Id.ToString());
        __segids_SYS1.Add(__seg_SYS1_1.Id.ToString());
        __segids_SYS1.Add(__seg_SYS1_2.Id.ToString());
        __sysprobe_SYS1 = __seg_SYS1_0;

        doc.Regenerate();

        // post SYS1
            { var __lc = __seg_SYS1_0.Location as LocationCurve; if (__lc == null) __post.Add("SYS1: segment 0 no curve (geometry)");
              else { var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                bool __fwd = __a.DistanceTo(P(0.0, 0.0, 3000.0)) <= __b.DistanceTo(P(0.0, 0.0, 3000.0));
                var __e0 = __fwd ? __a : __b; var __e1 = __fwd ? __b : __a;
                double __ux = (1.0);
                double __uy = (0.0);
                double __uz = (0.0);
                double __r0x = MM(__e0.X)-(0.0);
                double __r0y = MM(__e0.Y)-(0.0);
                double __r0z = MM(__e0.Z)-(3000.0);
                double __t0 = __r0x*__ux + __r0y*__uy + __r0z*__uz;
                double __d0 = Math.Sqrt(Math.Max(0.0, __r0x*__r0x + __r0y*__r0y + __r0z*__r0z - __t0*__t0));
                double __r1x = MM(__e1.X)-(3000.0);
                double __r1y = MM(__e1.Y)-(0.0);
                double __r1z = MM(__e1.Z)-(3000.0);
                double __t1 = -(__r1x*__ux + __r1y*__uy + __r1z*__uz);
                double __d1 = Math.Sqrt(Math.Max(0.0, __r1x*__r1x + __r1y*__r1y + __r1z*__r1z - __t1*__t1));
                if (__d0 > 5 || __t0 < -5 || __t0 > (1500.0) ||
                    __d1 > 5 || __t1 < -5 || __t1 > (5.0))
                  __post.Add("SYS1: segment 0 endpoints (geometry)"); } }
            { var __lc = __seg_SYS1_1.Location as LocationCurve; if (__lc == null) __post.Add("SYS1: segment 1 no curve (geometry)");
              else { var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                bool __fwd = __a.DistanceTo(P(0.0, 0.0, 3000.0)) <= __b.DistanceTo(P(0.0, 0.0, 3000.0));
                var __e0 = __fwd ? __a : __b; var __e1 = __fwd ? __b : __a;
                double __ux = (-1.0);
                double __uy = (0.0);
                double __uz = (0.0);
                double __r0x = MM(__e0.X)-(0.0);
                double __r0y = MM(__e0.Y)-(0.0);
                double __r0z = MM(__e0.Z)-(3000.0);
                double __t0 = __r0x*__ux + __r0y*__uy + __r0z*__uz;
                double __d0 = Math.Sqrt(Math.Max(0.0, __r0x*__r0x + __r0y*__r0y + __r0z*__r0z - __t0*__t0));
                double __r1x = MM(__e1.X)-(-3000.0);
                double __r1y = MM(__e1.Y)-(0.0);
                double __r1z = MM(__e1.Z)-(3000.0);
                double __t1 = -(__r1x*__ux + __r1y*__uy + __r1z*__uz);
                double __d1 = Math.Sqrt(Math.Max(0.0, __r1x*__r1x + __r1y*__r1y + __r1z*__r1z - __t1*__t1));
                if (__d0 > 5 || __t0 < -5 || __t0 > (1500.0) ||
                    __d1 > 5 || __t1 < -5 || __t1 > (5.0))
                  __post.Add("SYS1: segment 1 endpoints (geometry)"); } }
            { var __lc = __seg_SYS1_2.Location as LocationCurve; if (__lc == null) __post.Add("SYS1: segment 2 no curve (geometry)");
              else { var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                bool __fwd = __a.DistanceTo(P(0.0, 0.0, 3000.0)) <= __b.DistanceTo(P(0.0, 0.0, 3000.0));
                var __e0 = __fwd ? __a : __b; var __e1 = __fwd ? __b : __a;
                double __ux = (0.0);
                double __uy = (1.0);
                double __uz = (0.0);
                double __r0x = MM(__e0.X)-(0.0);
                double __r0y = MM(__e0.Y)-(0.0);
                double __r0z = MM(__e0.Z)-(3000.0);
                double __t0 = __r0x*__ux + __r0y*__uy + __r0z*__uz;
                double __d0 = Math.Sqrt(Math.Max(0.0, __r0x*__r0x + __r0y*__r0y + __r0z*__r0z - __t0*__t0));
                double __r1x = MM(__e1.X)-(0.0);
                double __r1y = MM(__e1.Y)-(3000.0);
                double __r1z = MM(__e1.Z)-(3000.0);
                double __t1 = -(__r1x*__ux + __r1y*__uy + __r1z*__uz);
                double __d1 = Math.Sqrt(Math.Max(0.0, __r1x*__r1x + __r1y*__r1y + __r1z*__r1z - __t1*__t1));
                if (__d0 > 5 || __t0 < -5 || __t0 > (1500.0) ||
                    __d1 > 5 || __t1 < -5 || __t1 > (5.0))
                  __post.Add("SYS1: segment 2 endpoints (geometry)"); } }
            { try { var __dp = __seg_SYS1_0.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM);
                if (__dp == null || Math.Abs(MM(__dp.AsDouble())-(250.0))>0.5)
                  __post.Add("SYS1: segment 0 diameter (semantic)"); }
              catch { __post.Add("SYS1: segment 0 diameter unreadable (semantic)"); } }
            { try { var __dp = __seg_SYS1_1.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM);
                if (__dp == null || Math.Abs(MM(__dp.AsDouble())-(250.0))>0.5)
                  __post.Add("SYS1: segment 1 diameter (semantic)"); }
              catch { __post.Add("SYS1: segment 1 diameter unreadable (semantic)"); } }
            { try { var __dp = __seg_SYS1_2.get_Parameter(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM);
                if (__dp == null || Math.Abs(MM(__dp.AsDouble())-(250.0))>0.5)
                  __post.Add("SYS1: segment 2 diameter (semantic)"); }
              catch { __post.Add("SYS1: segment 2 diameter unreadable (semantic)"); } }
        // connectivity witness SYS1
        {
            var __segs = new Element[] { __seg_SYS1_0, __seg_SYS1_1, __seg_SYS1_2 };
            var __ids = new HashSet<string>();
            foreach (var __e in __segs) __ids.Add(__e.Id.ToString());
            var __seen = new HashSet<string>();
            var __stack = new Stack<Element>();
            __stack.Push(__segs[0]); __seen.Add(__segs[0].Id.ToString());
            while (__stack.Count > 0) {
                var __cur = __stack.Pop();
                ConnectorManager __cm = null;
                try { if (__cur is MEPCurve) __cm = ((MEPCurve)__cur).ConnectorManager;
                       else if (__cur is FamilyInstance) __cm = ((FamilyInstance)__cur).MEPModel.ConnectorManager; } catch { }
                if (__cm == null) continue;
                foreach (Connector __c in __cm.Connectors) {
                    foreach (Connector __r in __c.AllRefs) {
                        var __owner = __r.Owner;
                        if (__owner == null) continue;
                        var __k = __owner.Id.ToString();
                        if (!__seen.Contains(__k)) { __seen.Add(__k);
                            if (__ids.Contains(__k)) __stack.Push(__owner);
                            else __stack.Push(__owner); }
                    }
                }
            }
            int __reachedSegs = 0;
            foreach (var __e in __segs) if (__seen.Contains(__e.Id.ToString())) __reachedSegs++;
            if (__reachedSegs < 3)
                __post.Add("SYS1: network not fully connected (topology)");
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

// witness SYS1
{
    var __rb = new Dictionary<string, object>();
    __rb["segments"] = 3;
    __rb["segment_ids"] = __segids_SYS1.ToArray();
    __results["SYS1"] = __rb;
}
// mep-system readback SYS1: membership is DERIVED by Revit at commit — read, never constructed (connect.py §A)
{
    var __sysIds = new List<string>();
    foreach (var __sg in new MEPCurve[] { __seg_SYS1_0, __seg_SYS1_1, __seg_SYS1_2 }) {
        if (__sg == null) continue;
        try { var __ms = __sg.MEPSystem;
               if (__ms != null && !__sysIds.Contains(__ms.Id.ToString()))
                   __sysIds.Add(__ms.Id.ToString()); } catch { }
    }
    var __sysRb = __results["SYS1"] as Dictionary<string, object>;
    if (__sysRb != null) {
        __sysRb["mep_system_ids"] = __sysIds.ToArray();
        __sysRb["one_system"] = (__sysIds.Count == 1);
    }
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