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
DirectShape __el_SE1 = null;
Solid __sol_SE1 = null;
bool __lbl_SE1 = false;
int __nsol_SE1 = 0;
double __rvol_SE1 = 0.0;
double __rcap_SE1 = 0.0;
double __dt_SE1 = 0.0;
double __tvol_SE1 = 0.0;
double __tcap_SE1 = 0.0;
DirectShape __el_SR1 = null;
Solid __sol_SR1 = null;
bool __lbl_SR1 = false;
int __nsol_SR1 = 0;
double __rvol_SR1 = 0.0;
double __rcap_SR1 = 0.0;
double __dt_SR1 = 0.0;
double __tvol_SR1 = 0.0;
double __tcap_SR1 = 0.0;
using (Transaction __t = new Transaction(doc, "KIR: параметрическое тело: выдавливание с проёмом и вращение"))
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
        // create_solid_extrusion SE1 — профиль 4 рёбер, 1 проёмов, площадь 24760117.3 мм², объём 44568211073.5 мм³
        ElementId __cat_SE1 = new ElementId(BuiltInCategory.OST_Mass);
        if (!DirectShape.IsValidCategoryId(__cat_SE1, doc)) { __t.RollBack(); return __Refuse("SE1", "категория недопустима для DirectShape в этом документе"); }
        CurveLoop __ol_SE1 = new CurveLoop();
        __ol_SE1.Append(Line.CreateBound(P(0.0, 0.0, 0), P(6000.0, 0.0, 0)));
        __ol_SE1.Append(Arc.Create(P(6000.0, 0.0, 0), P(6000.0, 4000.0, 0), P(6800.0, 2000.0, 0)));
        __ol_SE1.Append(Line.CreateBound(P(6000.0, 4000.0, 0), P(0.0, 4000.0, 0)));
        __ol_SE1.Append(Line.CreateBound(P(0.0, 4000.0, 0), P(0.0, 0.0, 0)));
        CurveLoop __hl_SE1_0 = new CurveLoop();
        __hl_SE1_0.Append(Line.CreateBound(P(1000.0, 1000.0, 0), P(2200.0, 1000.0, 0)));
        __hl_SE1_0.Append(Line.CreateBound(P(2200.0, 1000.0, 0), P(2200.0, 2200.0, 0)));
        __hl_SE1_0.Append(Line.CreateBound(P(2200.0, 2200.0, 0), P(1000.0, 2200.0, 0)));
        __hl_SE1_0.Append(Line.CreateBound(P(1000.0, 2200.0, 0), P(1000.0, 1000.0, 0)));
        IList<CurveLoop> __lps_SE1 = new List<CurveLoop>();
        __lps_SE1.Add(CurveLoop.CreateViaTransform(__ol_SE1, Transform.CreateTranslation(new XYZ(0, 0, U(3300.0)))));
        __lps_SE1.Add(CurveLoop.CreateViaTransform(__hl_SE1_0, Transform.CreateTranslation(new XYZ(0, 0, U(3300.0)))));
        __sol_SE1 = GeometryCreationUtilities.CreateExtrusionGeometry(__lps_SE1, XYZ.BasisZ, U(1800.0));
        if (__sol_SE1 == null || __sol_SE1.Faces.Size == 0) { __t.RollBack(); return __Refuse("SE1", "Revit не построил тело из этого профиля (пустой Solid)"); }
        __el_SE1 = DirectShape.CreateElement(doc, __cat_SE1);
        if (__el_SE1 == null) { __t.RollBack(); return __Refuse("SE1", "создание DirectShape вернуло null"); }
        IList<GeometryObject> __gos_SE1 = new List<GeometryObject>();
        __gos_SE1.Add(__sol_SE1);
        __el_SE1.SetShape(__gos_SE1);
        __el_SE1.Name = "плита с проёмом";
        Parameter __mk_SE1 = __el_SE1.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
        if (__mk_SE1 != null && !__mk_SE1.IsReadOnly && string.IsNullOrEmpty(__mk_SE1.AsString()))
            __lbl_SE1 = __mk_SE1.Set("KIR Solid: параметрическое тело без BIM-смысла (нет типа/параметров)");
        try { Parameter __cm = __el_SE1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:5b890289:SE1"); } catch { }
        __dt_SE1 = MM(doc.Application.VertexTolerance) + 0.01;
        __tvol_SE1 = 94905207.68016614 * __dt_SE1;
        if (__tvol_SE1 >= 2592000000.0) { __t.RollBack(); return __Refuse("SE1", "допуск объёмного свидетеля не меньше самой мелкой объявленной части профиля — проверка не смогла бы провалиться; тело слишком тонкое или проём слишком мелкий для честной сверки"); }
        __tcap_SE1 = 50427.747949006865 * __dt_SE1;
        if (__tcap_SE1 >= 2880000.0) { __t.RollBack(); return __Refuse("SE1", "допуск свидетеля торцов не меньше самой мелкой объявленной части профиля — проверка не смогла бы провалиться"); }

        // create_solid_revolve SR1 — профиль 4 рёбер, 0 проёмов, поворот 270°, объём 12666901579.3 мм³
        ElementId __cat_SR1 = new ElementId(BuiltInCategory.OST_GenericModel);
        if (!DirectShape.IsValidCategoryId(__cat_SR1, doc)) { __t.RollBack(); return __Refuse("SR1", "категория недопустима для DirectShape в этом документе"); }
        CurveLoop __ol_SR1 = new CurveLoop();
        __ol_SR1.Append(Line.CreateBound(P(1000.0, 0.0, 0), P(1800.0, 0.0, 0)));
        __ol_SR1.Append(Line.CreateBound(P(1800.0, 0.0, 0), P(1800.0, 2400.0, 0)));
        __ol_SR1.Append(Line.CreateBound(P(1800.0, 2400.0, 0), P(1000.0, 2400.0, 0)));
        __ol_SR1.Append(Line.CreateBound(P(1000.0, 2400.0, 0), P(1000.0, 0.0, 0)));
        Transform __tf_SR1 = Transform.Identity;
        __tf_SR1.Origin = P(12000.0, 4000.0, 0.0);
        __tf_SR1.BasisX = new XYZ(1, 0, 0);
        __tf_SR1.BasisY = new XYZ(0, 0, 1);
        __tf_SR1.BasisZ = new XYZ(0, -1, 0);
        Frame __fr_SR1 = new Frame(P(12000.0, 4000.0, 0.0), new XYZ(1, 0, 0), new XYZ(0, 1, 0), new XYZ(0, 0, 1));
        IList<CurveLoop> __lps_SR1 = new List<CurveLoop>();
        __lps_SR1.Add(CurveLoop.CreateViaTransform(__ol_SR1, __tf_SR1));
        __sol_SR1 = GeometryCreationUtilities.CreateRevolvedGeometry(__fr_SR1, __lps_SR1, 0.0, 4.71238898038469);
        if (__sol_SR1 == null || __sol_SR1.Faces.Size == 0) { __t.RollBack(); return __Refuse("SR1", "Revit не построил тело из этого профиля (пустой Solid)"); }
        __el_SR1 = DirectShape.CreateElement(doc, __cat_SR1);
        if (__el_SR1 == null) { __t.RollBack(); return __Refuse("SR1", "создание DirectShape вернуло null"); }
        IList<GeometryObject> __gos_SR1 = new List<GeometryObject>();
        __gos_SR1.Add(__sol_SR1);
        __el_SR1.SetShape(__gos_SR1);
        __el_SR1.Name = "сектор кольца";
        Parameter __mk_SR1 = __el_SR1.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);
        if (__mk_SR1 != null && !__mk_SR1.IsReadOnly && string.IsNullOrEmpty(__mk_SR1.AsString()))
            __lbl_SR1 = __mk_SR1.Set("KIR Solid: параметрическое тело без BIM-смысла (нет типа/параметров)");
        try { Parameter __cm = __el_SR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:5b890289:SR1"); } catch { }
        __dt_SR1 = MM(doc.Application.VertexTolerance) + 0.01;
        __tvol_SR1 = 46063005.26424682 * __dt_SR1;
        if (__tvol_SR1 >= 12666901579.274046) { __t.RollBack(); return __Refuse("SR1", "допуск объёмного свидетеля не меньше самой мелкой объявленной части профиля — проверка не смогла бы провалиться; тело слишком тонкое или проём слишком мелкий для честной сверки"); }
        __tcap_SR1 = 12800.0 * __dt_SR1;
        if (__tcap_SR1 >= 3840000.0) { __t.RollBack(); return __Refuse("SR1", "допуск свидетеля торцов не меньше самой мелкой объявленной части профиля — проверка не смогла бы провалиться"); }

        doc.Regenerate();

        // post SE1
        {
            var __ge_SE1 = __el_SE1.get_Geometry(new Options());
            if (__ge_SE1 != null)
            {
                foreach (GeometryObject __go_SE1 in __ge_SE1)
                {
                    Solid __so_SE1 = __go_SE1 as Solid;
                    if (__so_SE1 != null && __so_SE1.Faces.Size > 0)
                    { __nsol_SE1++; __rvol_SE1 += __so_SE1.Volume; }
                    GeometryInstance __gi_SE1 = __go_SE1 as GeometryInstance;
                    if (__gi_SE1 != null)
                        foreach (GeometryObject __g2_SE1 in __gi_SE1.GetInstanceGeometry())
                        {
                            Solid __s2_SE1 = __g2_SE1 as Solid;
                            if (__s2_SE1 != null && __s2_SE1.Faces.Size > 0)
                            { __nsol_SE1++; __rvol_SE1 += __s2_SE1.Volume; }
                        }
                }
            }
            if (__nsol_SE1 != 1)
                __post.Add("SE1: built geometry does not hold exactly one solid (geometry)");
            double __vmm_SE1 = __rvol_SE1 * MM(MM(MM(1.0)));
            if (Math.Abs(__vmm_SE1 - 44568211073.453964) > __tvol_SE1)
                __post.Add("SE1: solid volume mismatch (geometry)");
            if (__sol_SE1 != null)
                foreach (Face __f_SE1 in __sol_SE1.Faces)
                {
                    PlanarFace __pf_SE1 = __f_SE1 as PlanarFace;
                    if (__pf_SE1 != null && Math.Abs(__pf_SE1.FaceNormal.Z) > 0.999999)
                        __rcap_SE1 += MM(MM(__pf_SE1.Area));
                }
            if (Math.Abs(__rcap_SE1 - 49520234.52605996) > __tcap_SE1)
                __post.Add("SE1: planar cap area mismatch (geometry)");
            var __bb_SE1 = __el_SE1.get_BoundingBox(null);
            if (__bb_SE1 == null) __post.Add("SE1: нет BoundingBox");
            else if (Math.Abs(MM(__bb_SE1.Min.X) - 0.0) > __dt_SE1 || Math.Abs(MM(__bb_SE1.Max.X) - 6800.0) > __dt_SE1 ||
                     Math.Abs(MM(__bb_SE1.Min.Y) - 0.0) > __dt_SE1 || Math.Abs(MM(__bb_SE1.Max.Y) - 4000.0) > __dt_SE1 ||
                     Math.Abs(MM(__bb_SE1.Min.Z) - 3300.0) > __dt_SE1 || Math.Abs(MM(__bb_SE1.Max.Z) - 5100.0) > __dt_SE1)
                __post.Add("SE1: bbox extents mismatch (geometry)");
        }
        // post SR1
        {
            var __ge_SR1 = __el_SR1.get_Geometry(new Options());
            if (__ge_SR1 != null)
            {
                foreach (GeometryObject __go_SR1 in __ge_SR1)
                {
                    Solid __so_SR1 = __go_SR1 as Solid;
                    if (__so_SR1 != null && __so_SR1.Faces.Size > 0)
                    { __nsol_SR1++; __rvol_SR1 += __so_SR1.Volume; }
                    GeometryInstance __gi_SR1 = __go_SR1 as GeometryInstance;
                    if (__gi_SR1 != null)
                        foreach (GeometryObject __g2_SR1 in __gi_SR1.GetInstanceGeometry())
                        {
                            Solid __s2_SR1 = __g2_SR1 as Solid;
                            if (__s2_SR1 != null && __s2_SR1.Faces.Size > 0)
                            { __nsol_SR1++; __rvol_SR1 += __s2_SR1.Volume; }
                        }
                }
            }
            if (__nsol_SR1 != 1)
                __post.Add("SR1: built geometry does not hold exactly one solid (geometry)");
            double __vmm_SR1 = __rvol_SR1 * MM(MM(MM(1.0)));
            if (Math.Abs(__vmm_SR1 - 12666901579.274046) > __tvol_SR1)
                __post.Add("SR1: solid volume mismatch (geometry)");
            if (__sol_SR1 != null)
                foreach (Face __f_SR1 in __sol_SR1.Faces)
                {
                    PlanarFace __pf_SR1 = __f_SR1 as PlanarFace;
                    if (__pf_SR1 != null && Math.Abs(__pf_SR1.FaceNormal.Z) < 1e-06)
                        __rcap_SR1 += MM(MM(__pf_SR1.Area));
                }
            if (Math.Abs(__rcap_SR1 - 3840000.0) > __tcap_SR1)
                __post.Add("SR1: planar cap area mismatch (geometry)");
            var __bb_SR1 = __el_SR1.get_BoundingBox(null);
            if (__bb_SR1 == null) __post.Add("SR1: нет BoundingBox");
            else if (Math.Abs(MM(__bb_SR1.Min.X) - 10200.0) > __dt_SR1 || Math.Abs(MM(__bb_SR1.Max.X) - 13800.0) > __dt_SR1 ||
                     Math.Abs(MM(__bb_SR1.Min.Y) - 2200.0) > __dt_SR1 || Math.Abs(MM(__bb_SR1.Max.Y) - 5800.0) > __dt_SR1 ||
                     Math.Abs(MM(__bb_SR1.Min.Z) - 0.0) > __dt_SR1 || Math.Abs(MM(__bb_SR1.Max.Z) - 2400.0) > __dt_SR1)
                __post.Add("SR1: bbox extents mismatch (geometry)");
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

// witness SE1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_SE1.Id.ToString();
    __rb["name"] = __el_SE1.Name;
    __rb["category"] = "mass";
    __rb["kind"] = "direct_shape_solid_extrusion";
    __rb["solids"] = __nsol_SE1;
    __rb["volume_mm3_expected"] = 44568211073.453964;
    __rb["volume_mm3_measured"] = __rvol_SE1 * MM(MM(MM(1.0)));
    __rb["volume_tolerance_mm3"] = __tvol_SE1;
    __rb["profile_area_mm2"] = 24760117.26302998;
    __rb["cap_area_mm2_expected"] = 49520234.52605996;
    __rb["cap_area_mm2_measured"] = __rcap_SE1;
    __rb["cap_area_tolerance_mm2"] = __tcap_SE1;
    __rb["vertex_tolerance_mm"] = MM(doc.Application.VertexTolerance);
    __rb["bim_semantics"] = "none";
    __rb["has_type"] = false;
    __rb["schedulable_as_building_element"] = false;
    __rb["human_editable"] = false;
    __rb["honest_label_written"] = __lbl_SE1;
    __rb["warning"] = "Параметрическое тело в DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификации он не попадёт как строительный элемент, и вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если объём совпадает.";
    try { var __stampParam = __el_SE1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["SE1"] = __rb;
}

// witness SR1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_SR1.Id.ToString();
    __rb["name"] = __el_SR1.Name;
    __rb["category"] = "generic_model";
    __rb["kind"] = "direct_shape_solid_revolve";
    __rb["solids"] = __nsol_SR1;
    __rb["volume_mm3_expected"] = 12666901579.274046;
    __rb["volume_mm3_measured"] = __rvol_SR1 * MM(MM(MM(1.0)));
    __rb["volume_tolerance_mm3"] = __tvol_SR1;
    __rb["profile_area_mm2"] = 1920000.0;
    __rb["cap_area_mm2_expected"] = 3840000.0;
    __rb["cap_area_mm2_measured"] = __rcap_SR1;
    __rb["cap_area_tolerance_mm2"] = __tcap_SR1;
    __rb["cap_area_meaning"] = "сектор: два плоских торца, ожидается удвоенная площадь профиля";
    __rb["vertex_tolerance_mm"] = MM(doc.Application.VertexTolerance);
    __rb["bim_semantics"] = "none";
    __rb["has_type"] = false;
    __rb["schedulable_as_building_element"] = false;
    __rb["human_editable"] = false;
    __rb["honest_label_written"] = __lbl_SR1;
    __rb["warning"] = "Параметрическое тело в DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификации он не попадёт как строительный элемент, и вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если объём совпадает.";
    try { var __stampParam = __el_SR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["SR1"] = __rb;
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