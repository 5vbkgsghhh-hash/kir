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
List<ModelCurve> __segs_RS1 = new List<ModelCurve>();
ViewPlan __rsv_RS1 = null;
int __rsvn_RS1 = 0;
using (Transaction __t = new Transaction(doc, "KIR: отделить кухню-нишу от гостиной без стены"))
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
        // create_room_separator RS1
        Element __lv_raw_RS1 = doc.GetElement(new ElementId(42));
        Level __lv_RS1 = __lv_raw_RS1 as Level;
        if (__lv_RS1 == null) { __t.RollBack(); return __Refuse("RS1", (__lv_raw_RS1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_RS1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        foreach (ViewPlan __vp_RS1 in new FilteredElementCollector(doc)
                .OfClass(typeof(ViewPlan)).Cast<ViewPlan>())
        {
            if (__vp_RS1.IsTemplate) continue;
            if (__vp_RS1.ViewType != ViewType.FloorPlan) continue;
            Level __gl_RS1 = null;
            try { __gl_RS1 = __vp_RS1.GenLevel; } catch { }
            if (__gl_RS1 == null || __gl_RS1.Id.ToString() != __lv_RS1.Id.ToString()) continue;
            __rsvn_RS1++;
            if (__rsv_RS1 == null || __vp_RS1.Id < __rsv_RS1.Id) __rsv_RS1 = __vp_RS1;
        }
        if (__rsv_RS1 == null) { __t.RollBack(); return __Refuse("RS1", "разделитель помещений: у разрешённого уровня нет ни одного плана этажа (не шаблона), а NewRoomBoundaryLines требует вид — подставить чужой план значило бы нарисовать границу не на том этаже"); }
        SketchPlane __sp_RS1 = SketchPlane.Create(doc, __lv_RS1.Id);
        if (__sp_RS1 == null) { __t.RollBack(); return __Refuse("RS1", "плоскость эскиза уровня не построена"); }
        double __z_RS1 = MM(__lv_RS1.Elevation);
        CurveArray __ca_RS1 = new CurveArray();
        __ca_RS1.Append(Line.CreateBound(P(0.0, 0.0, __z_RS1), P(3200.0, 0.0, __z_RS1)));
        __ca_RS1.Append(Line.CreateBound(P(3200.0, 0.0, __z_RS1), P(3200.0, 2400.0, __z_RS1)));
        __ca_RS1.Append(Line.CreateBound(P(3200.0, 2400.0, __z_RS1), P(0.0, 2400.0, __z_RS1)));
        ModelCurveArray __mca_RS1 = null;
        try { __mca_RS1 = doc.Create.NewRoomBoundaryLines(__sp_RS1, __ca_RS1, __rsv_RS1); }
        catch (Exception __ex_RS1) { __t.RollBack(); return __Refuse("RS1", "NewRoomBoundaryLines: " + __ex_RS1.Message); }
        if (__mca_RS1 == null) { __t.RollBack(); return __Refuse("RS1", "создание разделителя помещений вернуло null"); }
        foreach (ModelCurve __mc_RS1 in __mca_RS1)
        {
            if (__mc_RS1 == null) { __t.RollBack(); return __Refuse("RS1", "созданный сегмент границы не читается как ModelCurve"); }
            try { Parameter __cm = __mc_RS1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:8b17d28f:RS1"); } catch { }
            __segs_RS1.Add(__mc_RS1);
        }
        if (__segs_RS1.Count == 0) { __t.RollBack(); return __Refuse("RS1", "создание разделителя помещений не вернуло ни одного сегмента"); }

        doc.Regenerate();

        // post RS1
        {
            if (__segs_RS1.Count != 3)
                __post.Add("RS1: room separator segment count mismatch (identity)");
            var __rsc_RS1 = new ElementId(BuiltInCategory.OST_RoomSeparationLines).ToString();
            foreach (var __cs_RS1 in __segs_RS1)
                if (__cs_RS1.Category == null || __cs_RS1.Category.Id == null
                    || __cs_RS1.Category.Id.ToString() != __rsc_RS1)
                    __post.Add("RS1: сегмент не является разделителем помещений (topology)");
            foreach (var __ls_RS1 in __segs_RS1)
                if (__ls_RS1.LevelId == null
                    || __ls_RS1.LevelId == ElementId.InvalidElementId
                    || __ls_RS1.LevelId.ToString() != "42")
                    __post.Add("RS1: level binding mismatch (topology)");
            var __exp_RS1 = new List<double[]>() { new double[] { 0.0, 0.0, 3200.0, 0.0 }, new double[] { 3200.0, 0.0, 3200.0, 2400.0 }, new double[] { 3200.0, 2400.0, 0.0, 2400.0 } };
            for (int __i_RS1 = 0; __i_RS1 < Math.Min(__exp_RS1.Count, __segs_RS1.Count); __i_RS1++)
            {
                var __gc_RS1 = __segs_RS1[__i_RS1].GeometryCurve;
                if (__gc_RS1 == null) { __post.Add("RS1: сегмент без геометрии (geometry)"); continue; }
                var __e0_RS1 = __gc_RS1.GetEndPoint(0);
                var __e1_RS1 = __gc_RS1.GetEndPoint(1);
                var __w_RS1 = __exp_RS1[__i_RS1];
                bool __fwd_RS1 = Math.Abs(MM(__e0_RS1.X) - __w_RS1[0]) <= 5.0
                    && Math.Abs(MM(__e0_RS1.Y) - __w_RS1[1]) <= 5.0
                    && Math.Abs(MM(__e1_RS1.X) - __w_RS1[2]) <= 5.0
                    && Math.Abs(MM(__e1_RS1.Y) - __w_RS1[3]) <= 5.0;
                bool __rev_RS1 = Math.Abs(MM(__e1_RS1.X) - __w_RS1[0]) <= 5.0
                    && Math.Abs(MM(__e1_RS1.Y) - __w_RS1[1]) <= 5.0
                    && Math.Abs(MM(__e0_RS1.X) - __w_RS1[2]) <= 5.0
                    && Math.Abs(MM(__e0_RS1.Y) - __w_RS1[3]) <= 5.0;
                if (!__fwd_RS1 && !__rev_RS1)
                    __post.Add("RS1: endpoints mismatch (geometry)");
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

// witness RS1
{
    var __rb = new Dictionary<string, object>();
    __rb["segment_ids"] = __segs_RS1.Select(__i => __i.Id.ToString()).ToArray();
    __rb["segment_count"] = __segs_RS1.Count;
    __rb["view_id"] = __rsv_RS1.Id.ToString();
    try { __rb["view_name"] = __rsv_RS1.Name; } catch { }
    __rb["view_candidates"] = __rsvn_RS1;
    try { var __stampParam = __segs_RS1[0].get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["RS1"] = __rb;
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