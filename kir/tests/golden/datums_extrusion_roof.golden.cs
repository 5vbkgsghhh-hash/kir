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
ExtrusionRoof __el_XR1 = null; ReferencePlane __rp_XR1 = null; XYZ __nrm_XR1 = null; XYZ __org_XR1 = null;
ExtrusionRoof __el_XR2 = null; ReferencePlane __rp_XR2 = null; XYZ __nrm_XR2 = null; XYZ __org_XR2 = null;
using (Transaction __t = new Transaction(doc, "KIR: выдавленные кровли: щипец и плоский навес"))
{
    try
    {
        var __startStatus = __t.Start();
        if (__startStatus != TransactionStatus.Started)
            return __Refuse("$program", "transaction start status: " + __startStatus.ToString());
        __KirMainFailures.Seen.Clear();
        __KirMainFailures.Warned.Clear();
        __KirMainFailures.Resolved.Clear();
        __KirMainFailures.Attempts.Clear();
        var __fho = __t.GetFailureHandlingOptions();
        __fho.SetFailuresPreprocessor(new __KirMainFailures());
        __fho.SetForcedModalHandling(false);
        __fho.SetClearAfterRollback(true);
        __t.SetFailureHandlingOptions(__fho);
        // create_extrusion_roof XR1
        RoofType __rt_XR1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.RoofType)) as RoofType;
        if (__rt_XR1 == null) { __t.RollBack(); return __Refuse("XR1", "в документе нет типа кровли по умолчанию"); }
        Element __lv_raw_XR1 = doc.GetElement(new ElementId(42));
        Level __lv_XR1 = __lv_raw_XR1 as Level;
        if (__lv_XR1 == null) { __t.RollBack(); return __Refuse("XR1", (__lv_raw_XR1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_XR1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        View __vw_XR1 = doc.ActiveView;
        if (__vw_XR1 == null) { __t.RollBack(); return __Refuse("XR1", "активного вида нет — опорную плоскость не на чем создать"); }
        if (__vw_XR1.ViewType == ViewType.Legend || __vw_XR1.ViewType == ViewType.DraftingView || __vw_XR1.ViewType == ViewType.DrawingSheet) { __t.RollBack(); return __Refuse("XR1", "активный вид — легенда, чертёжный вид или лист: на них опорная плоскость становится ВИДОВОЙ, и кровля привязалась бы к аннотации вместо модели; откройте модельный вид"); }
        __org_XR1 = P(0.0, 0.0, 0.0);
        __rp_XR1 = doc.Create.NewReferencePlane(__org_XR1, P(0.0, 8000.0, 0.0), XYZ.BasisZ, __vw_XR1);
        if (__rp_XR1 == null) { __t.RollBack(); return __Refuse("XR1", "NewReferencePlane вернул null"); }
        XYZ __rn_XR1 = __rp_XR1.Normal;
        if (__rn_XR1 == null || __rn_XR1.GetLength() <= 0.0) { __t.RollBack(); return __Refuse("XR1", "у созданной опорной плоскости нет нормали — направление выдавливания неопределимо"); }
        __rn_XR1 = __rn_XR1.Normalize();
        double __sg_XR1 = __rn_XR1.DotProduct(new XYZ(1.0, 0.0, 0.0)) >= 0.0 ? 1.0 : -1.0;
        __nrm_XR1 = __sg_XR1 > 0.0 ? __rn_XR1 : __rn_XR1.Negate();
        double __ea_XR1 = __sg_XR1 > 0.0 ? U(0.0) : U(-12000.0);
        double __eb_XR1 = __sg_XR1 > 0.0 ? U(12000.0) : U(0.0);
        CurveArray __ca_XR1 = new CurveArray();
        __ca_XR1.Append(Line.CreateBound(P(0.0, 0.0, 3000.0), P(0.0, 4000.0, 5000.0)));
        __ca_XR1.Append(Line.CreateBound(P(0.0, 4000.0, 5000.0), P(0.0, 8000.0, 3000.0)));
        __el_XR1 = doc.Create.NewExtrusionRoof(__ca_XR1, __rp_XR1, __lv_XR1, __rt_XR1, __ea_XR1, __eb_XR1);
        if (__el_XR1 == null) { __t.RollBack(); return __Refuse("XR1", "NewExtrusionRoof вернул null"); }
        try { Parameter __cm = __el_XR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:fdb8c43d:XR1"); } catch { }

        // create_extrusion_roof XR2
        RoofType __rt_XR2 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.RoofType)) as RoofType;
        if (__rt_XR2 == null) { __t.RollBack(); return __Refuse("XR2", "в документе нет типа кровли по умолчанию"); }
        Element __lv_raw_XR2 = doc.GetElement(new ElementId(43));
        Level __lv_XR2 = __lv_raw_XR2 as Level;
        if (__lv_XR2 == null) { __t.RollBack(); return __Refuse("XR2", (__lv_raw_XR2 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_XR2) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        View __vw_XR2 = doc.ActiveView;
        if (__vw_XR2 == null) { __t.RollBack(); return __Refuse("XR2", "активного вида нет — опорную плоскость не на чем создать"); }
        if (__vw_XR2.ViewType == ViewType.Legend || __vw_XR2.ViewType == ViewType.DraftingView || __vw_XR2.ViewType == ViewType.DrawingSheet) { __t.RollBack(); return __Refuse("XR2", "активный вид — легенда, чертёжный вид или лист: на них опорная плоскость становится ВИДОВОЙ, и кровля привязалась бы к аннотации вместо модели; откройте модельный вид"); }
        __org_XR2 = P(1000.0, 2000.0, 0.0);
        __rp_XR2 = doc.Create.NewReferencePlane(__org_XR2, P(9000.0, 2000.0, 0.0), XYZ.BasisZ, __vw_XR2);
        if (__rp_XR2 == null) { __t.RollBack(); return __Refuse("XR2", "NewReferencePlane вернул null"); }
        XYZ __rn_XR2 = __rp_XR2.Normal;
        if (__rn_XR2 == null || __rn_XR2.GetLength() <= 0.0) { __t.RollBack(); return __Refuse("XR2", "у созданной опорной плоскости нет нормали — направление выдавливания неопределимо"); }
        __rn_XR2 = __rn_XR2.Normalize();
        double __sg_XR2 = __rn_XR2.DotProduct(new XYZ(0.0, -1.0, 0.0)) >= 0.0 ? 1.0 : -1.0;
        __nrm_XR2 = __sg_XR2 > 0.0 ? __rn_XR2 : __rn_XR2.Negate();
        double __ea_XR2 = __sg_XR2 > 0.0 ? U(-3000.0) : U(-9000.0);
        double __eb_XR2 = __sg_XR2 > 0.0 ? U(9000.0) : U(3000.0);
        CurveArray __ca_XR2 = new CurveArray();
        __ca_XR2.Append(Line.CreateBound(P(1000.0, 2000.0, 4000.0), P(9000.0, 2000.0, 4000.0)));
        __el_XR2 = doc.Create.NewExtrusionRoof(__ca_XR2, __rp_XR2, __lv_XR2, __rt_XR2, __ea_XR2, __eb_XR2);
        if (__el_XR2 == null) { __t.RollBack(); return __Refuse("XR2", "NewExtrusionRoof вернул null"); }
        try { Parameter __cm = __el_XR2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:fdb8c43d:XR2"); } catch { }

        doc.Regenerate();

        // post XR1
        {
            var __rr_XR1 = __el_XR1 == null ? null : doc.GetElement(__el_XR1.Id) as ExtrusionRoof;
            if (__rr_XR1 == null)
                __post.Add("XR1: элемент не перечитывается из документа как ExtrusionRoof (semantic)");
            var __blp_XR1 = __rr_XR1 == null ? null : __rr_XR1.get_Parameter(BuiltInParameter.ROOF_CONSTRAINT_LEVEL_PARAM);
            if (__blp_XR1 == null || __blp_XR1.AsElementId() == null || __blp_XR1.AsElementId().ToString() != "42")
                __post.Add("XR1: base level mismatch (topology)");
            double __lo_XR1 = double.MaxValue;
            double __hi_XR1 = double.MinValue;
            if (__rr_XR1 != null && __nrm_XR1 != null && __org_XR1 != null)
            {
                var __ge_XR1 = __rr_XR1.get_Geometry(new Options());
                if (__ge_XR1 != null)
                    foreach (GeometryObject __go_XR1 in __ge_XR1)
                    {
                        Solid __sd_XR1 = __go_XR1 as Solid;
                        if (__sd_XR1 == null || __sd_XR1.Faces.Size == 0) continue;
                        foreach (Edge __ed_XR1 in __sd_XR1.Edges)
                            foreach (XYZ __pt_XR1 in __ed_XR1.Tessellate())
                            {
                                double __dd_XR1 = __pt_XR1.Subtract(__org_XR1).DotProduct(__nrm_XR1);
                                if (__dd_XR1 < __lo_XR1) __lo_XR1 = __dd_XR1;
                                if (__dd_XR1 > __hi_XR1) __hi_XR1 = __dd_XR1;
                            }
                    }
            }
            double __vt_XR1 = 2.0 * doc.Application.VertexTolerance;
            if (__lo_XR1 == double.MaxValue)
                __post.Add("XR1: у кровли нет тела — выдавливание не замерить (geometry)");
            else if (Math.Abs(__lo_XR1 - U(0.0)) > __vt_XR1
                  || Math.Abs(__hi_XR1 - U(12000.0)) > __vt_XR1)
                __post.Add("XR1: выдавливание не от start_mm до end_mm по нормали плоскости (geometry)");
        }
        // post XR2
        {
            var __rr_XR2 = __el_XR2 == null ? null : doc.GetElement(__el_XR2.Id) as ExtrusionRoof;
            if (__rr_XR2 == null)
                __post.Add("XR2: элемент не перечитывается из документа как ExtrusionRoof (semantic)");
            var __blp_XR2 = __rr_XR2 == null ? null : __rr_XR2.get_Parameter(BuiltInParameter.ROOF_CONSTRAINT_LEVEL_PARAM);
            if (__blp_XR2 == null || __blp_XR2.AsElementId() == null || __blp_XR2.AsElementId().ToString() != "43")
                __post.Add("XR2: base level mismatch (topology)");
            double __lo_XR2 = double.MaxValue;
            double __hi_XR2 = double.MinValue;
            if (__rr_XR2 != null && __nrm_XR2 != null && __org_XR2 != null)
            {
                var __ge_XR2 = __rr_XR2.get_Geometry(new Options());
                if (__ge_XR2 != null)
                    foreach (GeometryObject __go_XR2 in __ge_XR2)
                    {
                        Solid __sd_XR2 = __go_XR2 as Solid;
                        if (__sd_XR2 == null || __sd_XR2.Faces.Size == 0) continue;
                        foreach (Edge __ed_XR2 in __sd_XR2.Edges)
                            foreach (XYZ __pt_XR2 in __ed_XR2.Tessellate())
                            {
                                double __dd_XR2 = __pt_XR2.Subtract(__org_XR2).DotProduct(__nrm_XR2);
                                if (__dd_XR2 < __lo_XR2) __lo_XR2 = __dd_XR2;
                                if (__dd_XR2 > __hi_XR2) __hi_XR2 = __dd_XR2;
                            }
                    }
            }
            double __vt_XR2 = 2.0 * doc.Application.VertexTolerance;
            if (__lo_XR2 == double.MaxValue)
                __post.Add("XR2: у кровли нет тела — выдавливание не замерить (geometry)");
            else if (Math.Abs(__lo_XR2 - U(-3000.0)) > __vt_XR2
                  || Math.Abs(__hi_XR2 - U(9000.0)) > __vt_XR2)
                __post.Add("XR2: выдавливание не от start_mm до end_mm по нормали плоскости (geometry)");
        }
        if (__post.Count > 0)
        {
            var __rollbackStatus = __t.RollBack();
            var __er = new Dictionary<string, object>();
            __er["error"] = "postconditions_violated";
            __er["violations"] = __post;
            __er["commit_status"] = __rollbackStatus.ToString();
            return __er;
        }
        var __commitStatus = __t.Commit();
        if (__commitStatus != TransactionStatus.Committed)
        {
            try { if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack(); } catch { }
            var __refused = __Refuse("$program", "transaction commit status: " + __commitStatus.ToString()
                + (__KirMainFailures.Seen.Count > 0 ? " | Revit: " + String.Join(" ; ", __KirMainFailures.Seen) : ""));
            __refused["commit_status"] = __commitStatus.ToString();
            if (__KirMainFailures.Warned.Count > 0)
                __refused["revit_warnings"] = __KirMainFailures.Warned;
            if (__KirMainFailures.Resolved.Count > 0)
                __refused["revit_errors_resolved"] = __KirMainFailures.Resolved;
            return __refused;
        }
    }
    catch
    {
        if (__t.HasStarted() && !__t.HasEnded()) __t.RollBack();
        throw;
    }
}

// witness XR1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_XR1.Id.ToString();
    try { var __stampParam = __el_XR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __tid2_XR1 = __el_XR1.GetTypeId();
        if (__tid2_XR1 != null && __tid2_XR1 != ElementId.InvalidElementId) {
            var __te_XR1 = doc.GetElement(__tid2_XR1);
            if (__te_XR1 != null && __te_XR1.Name != null) __rb["type_name"] = __te_XR1.Name;
        } } catch { }
    try { if (__rp_XR1 != null) {
        __rb["ref_plane_id"] = __rp_XR1.Id.ToString();
        var __rpn_XR1 = __rp_XR1.Normal;
        if (__rpn_XR1 != null) __rb["ref_plane_normal"] = new double[] {
            Math.Round(__rpn_XR1.X, 6), Math.Round(__rpn_XR1.Y, 6), Math.Round(__rpn_XR1.Z, 6) };
    } } catch { }
    try { var __sp_XR1 = __el_XR1.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM);
        var __ep_XR1 = __el_XR1.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM);
        if (__sp_XR1 != null) __rb["extrusion_start_mm"] = Math.Round(MM(__sp_XR1.AsDouble()), 1);
        if (__ep_XR1 != null) __rb["extrusion_end_mm"] = Math.Round(MM(__ep_XR1.AsDouble()), 1);
    } catch { }
    __results["XR1"] = __rb;
}

// witness XR2
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_XR2.Id.ToString();
    try { var __stampParam = __el_XR2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __tid2_XR2 = __el_XR2.GetTypeId();
        if (__tid2_XR2 != null && __tid2_XR2 != ElementId.InvalidElementId) {
            var __te_XR2 = doc.GetElement(__tid2_XR2);
            if (__te_XR2 != null && __te_XR2.Name != null) __rb["type_name"] = __te_XR2.Name;
        } } catch { }
    try { if (__rp_XR2 != null) {
        __rb["ref_plane_id"] = __rp_XR2.Id.ToString();
        var __rpn_XR2 = __rp_XR2.Normal;
        if (__rpn_XR2 != null) __rb["ref_plane_normal"] = new double[] {
            Math.Round(__rpn_XR2.X, 6), Math.Round(__rpn_XR2.Y, 6), Math.Round(__rpn_XR2.Z, 6) };
    } } catch { }
    try { var __sp_XR2 = __el_XR2.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM);
        var __ep_XR2 = __el_XR2.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM);
        if (__sp_XR2 != null) __rb["extrusion_start_mm"] = Math.Round(MM(__sp_XR2.AsDouble()), 1);
        if (__ep_XR2 != null) __rb["extrusion_end_mm"] = Math.Round(MM(__ep_XR2.AsDouble()), 1);
    } catch { }
    __results["XR2"] = __rb;
}

if (__KirMainFailures.Warned.Count > 0)
    __results["revit_warnings"] = __KirMainFailures.Warned;
if (__KirMainFailures.Resolved.Count > 0)
    __results["revit_errors_resolved"] = __KirMainFailures.Resolved;
__results["ok"] = true;
return __results;
}
private class __KirMainFailures : IFailuresPreprocessor
{
    // Ошибки КОПЯТСЯ, а не гасятся: программа, откатившаяся на
    // Commit, обязана назвать причину.
    public static List<string> Seen = new List<string>();
    // Предупреждения СНИМАЮТСЯ (иначе модальный диалог паркует
    // Revit) и ЗАПИСЫВАЮТСЯ (иначе программа зеленеет молча).
    public static List<object> Warned = new List<object>();
    // РАЗРЕШЁННЫЕ ОШИБКИ — третье ведро, и оно не сливается с двумя
    // первыми: «Revit решил за нас» это не предупреждение и не наш
    // отказ, а отдельный факт о модели.
    public static List<object> Resolved = new List<object>();
    // Счётчик попыток по роду отказа. RevitAPI.xml: ResolveFailure
    // БРОСАЕТ, если один и тот же отказ разрешают дважды тем же
    // типом, и требует «avoid an infinite loop».
    public static Dictionary<string, int> Attempts = new Dictionary<string, int>();
    public FailureProcessingResult PreprocessFailures(FailuresAccessor __fa)
    {
        bool __resolvedAny = false;
        bool __unresolvable = false;
        foreach (var __f in __fa.GetFailureMessages())
        {
            var __sev = __f.GetSeverity();
            var __ids = new List<string>();
            try { foreach (var __id in __f.GetFailingElementIds()) __ids.Add(__id.ToString()); } catch { }
            string __guid = "?";
            try { __guid = __f.GetFailureDefinitionId().Guid.ToString(); } catch { }
            string __text = "";
            try { __text = __f.GetDescriptionText(); } catch { }
            if (__sev == FailureSeverity.Warning)
            {
                try {
                    var __w = new Dictionary<string, object>();
                    __w["guid"] = __guid; __w["text"] = __text; __w["elements"] = __ids;
                    Warned.Add(__w);
                } catch { }
                try { __fa.DeleteWarning(__f); } catch { }
                continue;
            }
            // ОШИБКА. Записываем ВСЕГДА — до всякой попытки.
            try {
                Seen.Add(__sev.ToString() + ": " + __text
                    + (__ids.Count > 0 ? " [элементы: " + String.Join(",", __ids) + "]" : ""));
            } catch { }
            int __tried = 0;
            try { if (Attempts.ContainsKey(__guid)) __tried = Attempts[__guid]; } catch { }
            bool __has = false;
            try { __has = __f.HasResolutions(); } catch { }
            if (!__has || __tried >= 1)
            {
                // Неразрешимая ИЛИ уже пробованная: второй заход тем
                // же типом Revit запрещает, а другого у нас нет.
                __unresolvable = true;
                continue;
            }
            try {
                Attempts[__guid] = __tried + 1;
                string __cap = "";
                try { __cap = __f.GetDefaultResolutionCaption(); } catch { }
                __fa.ResolveFailure(__f);
                __resolvedAny = true;
                var __r = new Dictionary<string, object>();
                __r["guid"] = __guid; __r["text"] = __text;
                __r["elements"] = __ids; __r["resolution"] = __cap;
                Resolved.Add(__r);
            }
            catch { __unresolvable = true; }
        }
        // ПОРЯДОК ИСХОДОВ ЗНАЧИМ.
        // `Continue` не возвращается НИКОГДА при ошибке: он и есть
        // модальное окно (RevitAPI.xml, дословно).
        if (__unresolvable) return FailureProcessingResult.ProceedWithRollBack;
        if (__resolvedAny) return FailureProcessingResult.ProceedWithCommit;
        return FailureProcessingResult.Continue;
    }
}
private static class __KirPad
{