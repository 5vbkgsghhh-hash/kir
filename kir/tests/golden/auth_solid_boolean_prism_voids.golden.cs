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
DirectShape __el_D1 = null;
Solid __sol_D1 = null;
bool __lbl_D1 = false;
int __nsol_D1 = 0;
double __rvol_D1 = 0.0;
double __rcap_D1 = 0.0;
double __dt_D1 = 0.0;
double __tvol_D1 = 0.0;
double __tcap_D1 = 0.0;
double __dtq_D1 = 0.0;
double[] __bva_D1 = new double[2];
double[] __bvb_D1 = new double[2];
double[] __bvi_D1 = new double[2];
double[] __bvr_D1 = new double[2];
double[] __bvx_D1 = new double[2];
double[] __bdl_D1 = new double[2];
using (Transaction __t = new Transaction(doc, "KIR: плита минус два выреза: один по отметке, один по грани"))
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
        // create_solid_boolean D1 — difference: база 4 рёбер x 4000 мм, части: prism, prism
        ElementId __cat_D1 = new ElementId(BuiltInCategory.OST_GenericModel);
        if (!DirectShape.IsValidCategoryId(__cat_D1, doc)) { __t.RollBack(); return __Refuse("D1", "категория недопустима для DirectShape в этом документе"); }
        CurveLoop __ol_D1 = new CurveLoop();
        __ol_D1.Append(Line.CreateBound(P(0.0, 0.0, 0), P(4000.0, 0.0, 0)));
        __ol_D1.Append(Line.CreateBound(P(4000.0, 0.0, 0), P(4000.0, 4000.0, 0)));
        __ol_D1.Append(Line.CreateBound(P(4000.0, 4000.0, 0), P(0.0, 4000.0, 0)));
        __ol_D1.Append(Line.CreateBound(P(0.0, 4000.0, 0), P(0.0, 0.0, 0)));
        IList<CurveLoop> __lps_D1 = new List<CurveLoop>();
        __lps_D1.Add(__ol_D1);
        Solid __acc_D1 = GeometryCreationUtilities.CreateExtrusionGeometry(__lps_D1, XYZ.BasisZ, U(4000.0));
        if (__acc_D1 == null || __acc_D1.Faces.Size == 0) { __t.RollBack(); return __Refuse("D1", "база булевой не построилась: Revit вернул пустое тело из этого профиля"); }
        __dtq_D1 = MM(doc.Application.VertexTolerance) + 0.01;
        // шаг 0: Difference с частью prism
        CurveLoop __ol_D1_p0 = new CurveLoop();
        __ol_D1_p0.Append(Line.CreateBound(P(1000.0, 1000.0, 0), P(3000.0, 1000.0, 0)));
        __ol_D1_p0.Append(Line.CreateBound(P(3000.0, 1000.0, 0), P(3000.0, 3000.0, 0)));
        __ol_D1_p0.Append(Line.CreateBound(P(3000.0, 3000.0, 0), P(1000.0, 3000.0, 0)));
        __ol_D1_p0.Append(Line.CreateBound(P(1000.0, 3000.0, 0), P(1000.0, 1000.0, 0)));
        IList<CurveLoop> __lps_D1_p0 = new List<CurveLoop>();
        __lps_D1_p0.Add(CurveLoop.CreateViaTransform(__ol_D1_p0, Transform.CreateTranslation(new XYZ(0, 0, U(500.0)))));
        Solid __prt_D1_0 = GeometryCreationUtilities.CreateExtrusionGeometry(__lps_D1_p0, XYZ.BasisZ, U(2000.0));
        if (__prt_D1_0 == null || __prt_D1_0.Faces.Size == 0) { __t.RollBack(); return __Refuse("D1", "часть 0 (prism) не построилась: Revit вернул пустое тело"); }
        __bva_D1[0] = __acc_D1.Volume * MM(MM(MM(1.0)));
        __bvb_D1[0] = __prt_D1_0.Volume * MM(MM(MM(1.0)));
        Solid __bau_D1_0 = BooleanOperationsUtils.ExecuteBooleanOperation(__acc_D1, __prt_D1_0, BooleanOperationsType.Intersect);
        __bvx_D1[0] = (__bau_D1_0 == null ? 0.0 : __bau_D1_0.Volume * MM(MM(MM(1.0))));
        __bvi_D1[0] = __bvx_D1[0];
        double __bpd_D1_0 = (__bau_D1_0 == null ? 0.0 : __bau_D1_0.SurfaceArea) * MM(MM(1.0)) * __dtq_D1;
        if (__bvi_D1[0] <= __bpd_D1_0) { __t.RollBack(); return __Refuse("D1", "KIR-B101 шаг 0: тела не пересекаются: булева не изменила бы ничего, и проверить её было бы нечем. Следующий ход: сдвинуть операнды так, чтобы они перекрывались, либо убрать операцию"); }
        if (__bvi_D1[0] >= Math.Min(__bva_D1[0], __bvb_D1[0]) - __bpd_D1_0) { __t.RollBack(); return __Refuse("D1", "KIR-B102 шаг 0: одно тело целиком внутри другого: результат известен заранее (объединение = большее, пересечение = меньшее, разность = большее минус меньшее). Следующий ход: если это и нужно — постройте нужное тело напрямую, без булевой"); }
        Solid __brs_D1_0 = BooleanOperationsUtils.ExecuteBooleanOperation(__acc_D1, __prt_D1_0, BooleanOperationsType.Difference);
        if (__brs_D1_0 == null || __brs_D1_0.Faces.Size == 0) { __t.RollBack(); return __Refuse("D1", "шаг 0: булева вернула пустое тело — результата, который можно положить в модель, нет"); }
        __bvr_D1[0] = __brs_D1_0.Volume * MM(MM(MM(1.0)));
        __bdl_D1[0] = (__acc_D1.SurfaceArea + __prt_D1_0.SurfaceArea + (__bau_D1_0 == null ? 0.0 : __bau_D1_0.SurfaceArea) + __brs_D1_0.SurfaceArea) * MM(MM(1.0)) * __dtq_D1;
        if (__bdl_D1[0] >= __bvi_D1[0]) { __t.RollBack(); return __Refuse("D1", "шаг 0: допуск тождества не меньше объёма пересечения — проверка не смогла бы провалиться. Тела перекрываются слишком мелко для честной сверки на своём размере"); }
        __acc_D1 = __brs_D1_0;
        // шаг 1: Difference с частью prism
        CurveLoop __ol_D1_p1 = new CurveLoop();
        __ol_D1_p1.Append(Line.CreateBound(P(0.0, 0.0, 0), P(1000.0, 0.0, 0)));
        __ol_D1_p1.Append(Line.CreateBound(P(1000.0, 0.0, 0), P(1000.0, 1000.0, 0)));
        __ol_D1_p1.Append(Line.CreateBound(P(1000.0, 1000.0, 0), P(0.0, 1000.0, 0)));
        __ol_D1_p1.Append(Line.CreateBound(P(0.0, 1000.0, 0), P(0.0, 0.0, 0)));
        Transform __pf_tf_D1_p1 = Transform.Identity;
        __pf_tf_D1_p1.Origin = P(1500.0, 1000.0, 500.0);
        __pf_tf_D1_p1.BasisX = new XYZ(1.0, 0.0, 0.0);
        __pf_tf_D1_p1.BasisY = new XYZ(0.0, 0.0, -1.0);
        __pf_tf_D1_p1.BasisZ = new XYZ(0.0, 1.0, 0.0);
        IList<CurveLoop> __lps_D1_p1 = new List<CurveLoop>();
        __lps_D1_p1.Add(CurveLoop.CreateViaTransform(__ol_D1_p1, __pf_tf_D1_p1));
        Solid __prt_D1_1 = GeometryCreationUtilities.CreateExtrusionGeometry(__lps_D1_p1, new XYZ(0.0, 1.0, 0.0), U(1500.0));
        if (__prt_D1_1 == null || __prt_D1_1.Faces.Size == 0) { __t.RollBack(); return __Refuse("D1", "часть 1 (prism) не построилась: Revit вернул пустое тело"); }
        __bva_D1[1] = __acc_D1.Volume * MM(MM(MM(1.0)));
        __bvb_D1[1] = __prt_D1_1.Volume * MM(MM(MM(1.0)));
        Solid __bau_D1_1 = BooleanOperationsUtils.ExecuteBooleanOperation(__acc_D1, __prt_D1_1, BooleanOperationsType.Intersect);
        __bvx_D1[1] = (__bau_D1_1 == null ? 0.0 : __bau_D1_1.Volume * MM(MM(MM(1.0))));
        __bvi_D1[1] = __bvx_D1[1];
        double __bpd_D1_1 = (__bau_D1_1 == null ? 0.0 : __bau_D1_1.SurfaceArea) * MM(MM(1.0)) * __dtq_D1;
        if (__bvi_D1[1] <= __bpd_D1_1) { __t.RollBack(); return __Refuse("D1", "KIR-B101 шаг 1: тела не пересекаются: булева не изменила бы ничего, и проверить её было бы нечем. Следующий ход: сдвинуть операнды так, чтобы они перекрывались, либо убрать операцию"); }
        if (__bvi_D1[1] >= Math.Min(__bva_D1[1], __bvb_D1[1]) - __bpd_D1_1) { __t.RollBack(); return __Refuse("D1", "KIR-B102 шаг 1: одно тело целиком внутри другого: результат известен заранее (объединение = большее, пересечение = меньшее, разность = большее минус меньшее). Следующий ход: если это и нужно — постройте нужное тело напрямую, без булевой"); }
        Solid __brs_D1_1 = BooleanOperationsUtils.ExecuteBooleanOperation(__acc_D1, __prt_D1_1, BooleanOperationsType.Difference);
        if (__brs_D1_1 == null || __brs_D1_1.Faces.Size == 0) { __t.RollBack(); return __Refuse("D1", "шаг 1: булева вернула пустое тело — результата, который можно положить в модель, нет"); }
        __bvr_D1[1] = __brs_D1_1.Volume * MM(MM(MM(1.0)));
        __bdl_D1[1] = (__acc_D1.SurfaceArea + __prt_D1_1.SurfaceArea + (__bau_D1_1 == null ? 0.0 : __bau_D1_1.SurfaceArea) + __brs_D1_1.SurfaceArea) * MM(MM(1.0)) * __dtq_D1;
        if (__bdl_D1[1] >= __bvi_D1[1]) { __t.RollBack(); return __Refuse("D1", "шаг 1: допуск тождества не меньше объёма пересечения — проверка не смогла бы провалиться. Тела перекрываются слишком мелко для честной сверки на своём размере"); }
        __acc_D1 = __brs_D1_1;
        __sol_D1 = __acc_D1;
        if (__sol_D1 == null || __sol_D1.Faces.Size == 0) { __t.RollBack(); return __Refuse("D1", "Revit не построил тело из этого профиля (пустой Solid)"); }
        __el_D1 = DirectShape.CreateElement(doc, __cat_D1);
        if (__el_D1 == null) { __t.RollBack(); return __Refuse("D1", "создание DirectShape вернуло null"); }
        IList<GeometryObject> __gos_D1 = new List<GeometryObject>();
        __gos_D1.Add(__sol_D1);
        __el_D1.SetShape(__gos_D1);
        __el_D1.Name = "плита минус два выреза";
        Parameter __mk_D1 = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
        if (__mk_D1 != null && !__mk_D1.IsReadOnly && string.IsNullOrEmpty(__mk_D1.AsString()))
            __lbl_D1 = __mk_D1.Set("KIR Solid: параметрическое тело без BIM-смысла (нет типа/параметров)");
        try { Parameter __cm = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0d60ec96:D1"); } catch { }

        doc.Regenerate();

        // post D1
        {
            var __ge_D1 = __el_D1.get_Geometry(new Options());
            if (__ge_D1 != null)
            {
                foreach (GeometryObject __go_D1 in __ge_D1)
                {
                    Solid __so_D1 = __go_D1 as Solid;
                    if (__so_D1 != null && __so_D1.Faces.Size > 0)
                    { __nsol_D1++; __rvol_D1 += __so_D1.Volume; }
                    GeometryInstance __gi_D1 = __go_D1 as GeometryInstance;
                    if (__gi_D1 != null)
                        foreach (GeometryObject __g2_D1 in __gi_D1.GetInstanceGeometry())
                        {
                            Solid __s2_D1 = __g2_D1 as Solid;
                            if (__s2_D1 != null && __s2_D1.Faces.Size > 0)
                            { __nsol_D1++; __rvol_D1 += __s2_D1.Volume; }
                        }
                }
            }
            if (__nsol_D1 != 1)
                __post.Add("D1: built geometry does not hold exactly one solid (geometry)");
            for (int __bi = 0; __bi < 2; __bi++)
            {
                double __a = __bva_D1[__bi];
                double __in = __bvi_D1[__bi];
                double __r = __bvr_D1[__bi];
                double __d = __bdl_D1[__bi];
                if (Math.Abs((__r + __in) - __a) > __d)
                    __post.Add("D1: шаг " + __bi + ": объём разности плюс пересечение не даёт исходного (geometry)");
            }
            for (int __bi = 0; __bi < 2; __bi++)
            {
                double __a = __bva_D1[__bi];
                double __r = __bvr_D1[__bi];
                double __d = __bdl_D1[__bi];
                if (!(__r < __a - __d))
                    __post.Add("D1: шаг " + __bi + ": разность не меньше уменьшаемого (geometry)");
            }
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

// witness D1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_D1.Id.ToString();
    __rb["name"] = __el_D1.Name;
    __rb["category"] = "generic_model";
    __rb["kind"] = "direct_shape_boolean";
    __rb["operation"] = "difference";
    __rb["parts"] = 2;
    __rb["solids"] = __nsol_D1;
    __rb["volume_mm3_measured"] = __rvol_D1 * MM(MM(MM(1.0)));
    __rb["vertex_tolerance_mm"] = MM(doc.Application.VertexTolerance);
    __rb["step0_shape"] = "prism";
    __rb["step0_part_bbox_mm"] = "1000.0 1000.0 500.0 .. 3000.0 3000.0 2500.0";
    __rb["step0_v_base_mm3"] = __bva_D1[0];
    __rb["step0_v_part_mm3"] = __bvb_D1[0];
    __rb["step0_v_intersection_mm3"] = __bvi_D1[0];
    __rb["step0_v_result_mm3"] = __bvr_D1[0];
    __rb["step0_v_auxiliary_mm3"] = __bvx_D1[0];
    __rb["step0_tolerance_mm3"] = __bdl_D1[0];
    __rb["step1_shape"] = "prism";
    __rb["step1_part_bbox_mm"] = "1500.0 1000.0 -500.0 .. 2500.0 2500.0 500.0";
    __rb["step1_v_base_mm3"] = __bva_D1[1];
    __rb["step1_v_part_mm3"] = __bvb_D1[1];
    __rb["step1_v_intersection_mm3"] = __bvi_D1[1];
    __rb["step1_v_result_mm3"] = __bvr_D1[1];
    __rb["step1_v_auxiliary_mm3"] = __bvx_D1[1];
    __rb["step1_tolerance_mm3"] = __bdl_D1[1];
    __rb["bim_semantics"] = "none";
    __rb["has_type"] = false;
    __rb["schedulable_as_building_element"] = false;
    __rb["human_editable"] = false;
    __rb["honest_label_written"] = __lbl_D1;
    __rb["warning"] = "Результат булевой в DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификацию как строительный элемент он не попадёт, вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если форма похожа.";
    try { var __stampParam = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["D1"] = __rb;
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