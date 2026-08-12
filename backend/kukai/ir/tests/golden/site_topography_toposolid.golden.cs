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
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element и у исключений — это полное имя типа CLR:
// из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ, WorksetId,
// ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и ни один из
// них сюда не передаётся. Исключение дописывает ": сообщение" и стек,
// поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __ClassName = (__cnObj) =>
{
    if (__cnObj == null) return "";
    string __cn = __cnObj.ToString();
    if (__cn == null) return "";
    int __cnCut = __cn.IndexOf((char)10);
    if (__cnCut >= 0) __cn = __cn.Substring(0, __cnCut);
    __cnCut = __cn.IndexOf(':');
    if (__cnCut >= 0) __cn = __cn.Substring(0, __cnCut);
    __cn = __cn.Trim();
    __cnCut = __cn.LastIndexOf('.');
    return __cnCut >= 0 && __cnCut + 1 < __cn.Length
        ? __cn.Substring(__cnCut + 1) : __cn;
};
var __results = new Dictionary<string, object>();
var __post = new List<string>();
Toposolid __el_T1 = null;
List<XYZ> __pts_T1 = null;
int __vcnt_T1 = -1;
using (Transaction __t = new Transaction(doc, "KIR: толща рельефа с привязкой к уровню"))
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
        // create_topography(toposolid) T1
        ToposolidType __ty_T1 = doc.GetElement(new ElementId(1700)) as ToposolidType;
        if (__ty_T1 == null) { __t.RollBack(); return __Refuse("T1", "толща рельефа: тип не найден (модель изменилась после grounding)"); }
        Element __lv_raw_T1 = doc.GetElement(new ElementId(42));
        Level __lv_T1 = __lv_raw_T1 as Level;
        if (__lv_T1 == null) { __t.RollBack(); return __Refuse("T1", (__lv_raw_T1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_T1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __pts_T1 = new List<XYZ>();
        __pts_T1.Add(P(0.0, 0.0, 0.0));
        __pts_T1.Add(P(24000.0, 0.0, 800.0));
        __pts_T1.Add(P(24000.0, 18000.0, 1500.0));
        __pts_T1.Add(P(0.0, 18000.0, 400.0));
        __pts_T1.Add(P(12000.0, 9000.0, 1100.0));
        __el_T1 = Toposolid.Create(doc, __pts_T1, __ty_T1.Id, __lv_T1.Id);
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "создание толщи рельефа вернуло null"); }
        try { Parameter __cm = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:56ce25d1:T1"); } catch { }

        doc.Regenerate();

        // post T1
        {
            SlabShapeEditor __sse_T1 = null;
            try { __sse_T1 = __el_T1.GetSlabShapeEditor(); } catch { }
            var __sv_T1 = (__sse_T1 == null) ? null : __sse_T1.SlabShapeVertices;
            __vcnt_T1 = (__sv_T1 == null) ? -1 : __sv_T1.Size;
            int __miss_T1 = 0;
            if (__vcnt_T1 > 0)
            {
                foreach (XYZ __ep_T1 in __pts_T1)
                {
                    bool __hit_T1 = false;
                    foreach (SlabShapeVertex __sq_T1 in __sv_T1)
                        if (__sq_T1.Position.DistanceTo(__ep_T1) <= U(1.0)) { __hit_T1 = true; break; }
                    if (!__hit_T1) __miss_T1++;
                }
                if (__miss_T1 > 0)
                    __post.Add(__miss_T1.ToString() + " из " + __pts_T1.Count.ToString() + " "
                        + "T1: описанных точек рельефа нет среди вершин формы толщи (geometry)");
            }
            var __bb = __el_T1.get_BoundingBox(null);
            if (__bb == null) __post.Add("T1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0.0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 24000.0) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0.0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 18000.0) > 50.0)
                __post.Add("T1: bbox extents mismatch (geometry)");
            Parameter __lp = __el_T1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_T1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_T1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_T1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("T1: level binding mismatch (topology)");
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
    __rb["slab_shape_vertices"] = __vcnt_T1;
    __rb["points_requested"] = 5;
    try { var __stampParam = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
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