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
MultiSegmentGrid __el_MG1 = null; SketchPlane __sp_MG1 = null; double __ze_MG1 = 0.0;
using (Transaction __t = new Transaction(doc, "KIR: цепь осей ломаной"))
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
        // create_multi_segment_grid MG1
        Element __lv_raw_MG1 = doc.GetElement(new ElementId(42));
        Level __lv_MG1 = __lv_raw_MG1 as Level;
        if (__lv_MG1 == null) { __t.RollBack(); return __Refuse("MG1", (__lv_raw_MG1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_MG1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __ze_MG1 = __lv_MG1.Elevation;
        __sp_MG1 = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0.0, 0.0, __ze_MG1)));
        if (__sp_MG1 == null) { __t.RollBack(); return __Refuse("MG1", "SketchPlane.Create вернул null"); }
        if (!MultiSegmentGrid.IsValidSketchPlaneId(doc, __sp_MG1.Id)) { __t.RollBack(); return __Refuse("MG1", "эскизный план уровня не признан горизонтальным — цепь осей на нём не строится"); }
        CurveLoop __cl_MG1 = new CurveLoop();
        __cl_MG1.Append(Line.CreateBound(new XYZ(U(0.0), U(0.0), __ze_MG1), new XYZ(U(8000.0), U(0.0), __ze_MG1)));
        __cl_MG1.Append(Line.CreateBound(new XYZ(U(8000.0), U(0.0), __ze_MG1), new XYZ(U(8000.0), U(6000.0), __ze_MG1)));
        __cl_MG1.Append(Line.CreateBound(new XYZ(U(8000.0), U(6000.0), __ze_MG1), new XYZ(U(14000.0), U(6000.0), __ze_MG1)));
        if (!MultiSegmentGrid.IsValidCurveLoop(__cl_MG1)) { __t.RollBack(); return __Refuse("MG1", "цепь не принята Revit: MultiSegmentGrid требует ОТКРЫТУЮ ломаную из отрезков и дуг (замкнутая или самопересекающаяся отвергается)"); }
        ElementId __tid_MG1 = doc.GetDefaultElementTypeId(ElementTypeGroup.GridType);
        if (__tid_MG1 == null || __tid_MG1 == ElementId.InvalidElementId) { __t.RollBack(); return __Refuse("MG1", "в документе нет типа оси по умолчанию"); }
        ElementId __nid_MG1 = MultiSegmentGrid.Create(doc, __tid_MG1, __cl_MG1, __sp_MG1.Id);
        if (__nid_MG1 == null || __nid_MG1 == ElementId.InvalidElementId) { __t.RollBack(); return __Refuse("MG1", "MultiSegmentGrid.Create не вернул id"); }
        __el_MG1 = doc.GetElement(__nid_MG1) as MultiSegmentGrid;
        if (__el_MG1 == null) { __t.RollBack(); return __Refuse("MG1", "созданный элемент не перечитывается как MultiSegmentGrid"); }
        try { Parameter __cm = __el_MG1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:dacf7c33:MG1"); } catch { }

        doc.Regenerate();

        // post MG1
        {
            var __ids_MG1 = __el_MG1 == null ? null : __el_MG1.GetGridIds();
            if (__ids_MG1 == null || __ids_MG1.Count != 3)
                __post.Add("MG1: число осей в цепи не равно числу звеньев (geometry)");
            double[] __ax_MG1 = new double[] { 0.0, 8000.0, 8000.0 };
            double[] __ay_MG1 = new double[] { 0.0, 0.0, 6000.0 };
            double[] __bx_MG1 = new double[] { 8000.0, 8000.0, 14000.0 };
            double[] __by_MG1 = new double[] { 0.0, 6000.0, 6000.0 };
            bool[] __used_MG1 = new bool[3];
            int __hit_MG1 = 0;
            if (__ids_MG1 != null)
            {
                foreach (ElementId __gid_MG1 in __ids_MG1)
                {
                    Grid __g_MG1 = doc.GetElement(__gid_MG1) as Grid;
                    if (__g_MG1 == null || __g_MG1.Curve == null) continue;
                    var __ga_MG1 = __g_MG1.Curve.GetEndPoint(0);
                    var __gb_MG1 = __g_MG1.Curve.GetEndPoint(1);
                    for (int __k_MG1 = 0; __k_MG1 < 3; __k_MG1++)
                    {
                        if (__used_MG1[__k_MG1]) continue;
                        bool __fw_MG1 = Math.Abs(MM(__ga_MG1.X) - __ax_MG1[__k_MG1]) <= 5.0
                            && Math.Abs(MM(__ga_MG1.Y) - __ay_MG1[__k_MG1]) <= 5.0
                            && Math.Abs(MM(__gb_MG1.X) - __bx_MG1[__k_MG1]) <= 5.0
                            && Math.Abs(MM(__gb_MG1.Y) - __by_MG1[__k_MG1]) <= 5.0;
                        bool __rv_MG1 = Math.Abs(MM(__gb_MG1.X) - __ax_MG1[__k_MG1]) <= 5.0
                            && Math.Abs(MM(__gb_MG1.Y) - __ay_MG1[__k_MG1]) <= 5.0
                            && Math.Abs(MM(__ga_MG1.X) - __bx_MG1[__k_MG1]) <= 5.0
                            && Math.Abs(MM(__ga_MG1.Y) - __by_MG1[__k_MG1]) <= 5.0;
                        if (__fw_MG1 || __rv_MG1) { __used_MG1[__k_MG1] = true; __hit_MG1++; break; }
                    }
                }
            }
            if (__hit_MG1 != 3)
                __post.Add("MG1: концы звеньев цепи не совпали (geometry)");
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

// witness MG1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_MG1.Id.ToString();
    try { var __stampParam = __el_MG1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __rids_MG1 = __el_MG1.GetGridIds();
        __rb["grid_count"] = __rids_MG1 == null ? 0 : __rids_MG1.Count;
        var __rn_MG1 = new List<string>();
        if (__rids_MG1 != null)
            foreach (ElementId __ri_MG1 in __rids_MG1)
            {
                Grid __rg_MG1 = doc.GetElement(__ri_MG1) as Grid;
                if (__rg_MG1 != null) __rn_MG1.Add(__rg_MG1.Name);
            }
        __rb["grid_names"] = __rn_MG1.ToArray(); } catch { }
    __results["MG1"] = __rb;
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