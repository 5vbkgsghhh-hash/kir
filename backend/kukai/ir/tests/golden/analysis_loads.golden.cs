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
Autodesk.Revit.DB.Structure.PointLoad __el_PL1 = null;
Autodesk.Revit.DB.Structure.LineLoad __el_LL1 = null;
Autodesk.Revit.DB.Structure.LineLoad __el_LL2 = null;
Autodesk.Revit.DB.Structure.AreaLoad __el_AL1 = null;
using (Transaction __t = new Transaction(doc, "KIR: точечная, две линейных и площадная нагрузка"))
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
        // create_point_load PL1
        Autodesk.Revit.DB.Structure.PointLoadType __ty_PL1 = doc.GetElement(new ElementId(1502)) as Autodesk.Revit.DB.Structure.PointLoadType;
        if (__ty_PL1 == null) { __t.RollBack(); return __Refuse("PL1", "точечная нагрузка: тип не найден (модель изменилась после grounding)"); }
        Autodesk.Revit.DB.Structure.LoadCase __lc_PL1 = doc.GetElement(new ElementId(1500)) as Autodesk.Revit.DB.Structure.LoadCase;
        if (__lc_PL1 == null) { __t.RollBack(); return __Refuse("PL1", "случай загружения не найден (модель изменилась после grounding)"); }
        SketchPlane __sp_PL1 = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(XYZ.BasisZ, P(1000, 2000, 3000)));
        if (__sp_PL1 == null) { __t.RollBack(); return __Refuse("PL1", "не удалось построить рабочую плоскость точечной нагрузки"); }
        __el_PL1 = Autodesk.Revit.DB.Structure.PointLoad.Create(doc, P(1000, 2000, 3000), new XYZ(UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Newtons), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Newtons), UnitUtils.ConvertToInternalUnits(-10000.0, UnitTypeId.Newtons)), new XYZ(UnitUtils.ConvertToInternalUnits(250.0, UnitTypeId.NewtonMeters), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonMeters), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonMeters)), __ty_PL1, __sp_PL1);
        if (__el_PL1 == null) { __t.RollBack(); return __Refuse("PL1", "PointLoad.Create вернул null"); }
        if (!__el_PL1.IsOrientToPermitted(Autodesk.Revit.DB.Structure.LoadOrientTo.Project)) { __t.RollBack(); return __Refuse("PL1", "нагрузка не допускает проектную систему отсчёта"); }
        __el_PL1.OrientTo = Autodesk.Revit.DB.Structure.LoadOrientTo.Project;
        __el_PL1.ForceVector = new XYZ(UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Newtons), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.Newtons), UnitUtils.ConvertToInternalUnits(-10000.0, UnitTypeId.Newtons));
        __el_PL1.MomentVector = new XYZ(UnitUtils.ConvertToInternalUnits(250.0, UnitTypeId.NewtonMeters), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonMeters), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonMeters));
        __el_PL1.LoadCaseId = __lc_PL1.Id;
        try { Parameter __cm = __el_PL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7ffacdc7:PL1"); } catch { }

        // create_line_load LL1
        Autodesk.Revit.DB.Structure.LineLoadType __ty_LL1 = doc.GetElement(new ElementId(1503)) as Autodesk.Revit.DB.Structure.LineLoadType;
        if (__ty_LL1 == null) { __t.RollBack(); return __Refuse("LL1", "линейная нагрузка: тип не найден (модель изменилась после grounding)"); }
        Autodesk.Revit.DB.Structure.LoadCase __lc_LL1 = doc.GetElement(new ElementId(1500)) as Autodesk.Revit.DB.Structure.LoadCase;
        if (__lc_LL1 == null) { __t.RollBack(); return __Refuse("LL1", "случай загружения не найден (модель изменилась после grounding)"); }
        SketchPlane __sp_LL1 = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(new XYZ(0.0, 0.0, 1.0), P(0, 0, 3000)));
        if (__sp_LL1 == null) { __t.RollBack(); return __Refuse("LL1", "не удалось построить рабочую плоскость линейной нагрузки"); }
        __el_LL1 = Autodesk.Revit.DB.Structure.LineLoad.Create(doc, P(0, 0, 3000), P(6000, 0, 3000), new XYZ(UnitUtils.ConvertToInternalUnits(120.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(-5000.0, UnitTypeId.NewtonsPerMeter)), new XYZ(0, 0, 0), __ty_LL1, __sp_LL1);
        if (__el_LL1 == null) { __t.RollBack(); return __Refuse("LL1", "LineLoad.Create вернул null"); }
        if (!__el_LL1.IsOrientToPermitted(Autodesk.Revit.DB.Structure.LoadOrientTo.Project)) { __t.RollBack(); return __Refuse("LL1", "нагрузка не допускает проектную систему отсчёта"); }
        __el_LL1.OrientTo = Autodesk.Revit.DB.Structure.LoadOrientTo.Project;
        __el_LL1.ForceVector1 = new XYZ(UnitUtils.ConvertToInternalUnits(120.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(-5000.0, UnitTypeId.NewtonsPerMeter));
        __el_LL1.LoadCaseId = __lc_LL1.Id;
        try { Parameter __cm = __el_LL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7ffacdc7:LL1"); } catch { }

        // create_line_load LL2
        Autodesk.Revit.DB.Structure.LineLoadType __ty_LL2 = doc.GetElement(new ElementId(1503)) as Autodesk.Revit.DB.Structure.LineLoadType;
        if (__ty_LL2 == null) { __t.RollBack(); return __Refuse("LL2", "линейная нагрузка: тип не найден (модель изменилась после grounding)"); }
        Autodesk.Revit.DB.Structure.LoadCase __lc_LL2 = doc.GetElement(new ElementId(1501)) as Autodesk.Revit.DB.Structure.LoadCase;
        if (__lc_LL2 == null) { __t.RollBack(); return __Refuse("LL2", "случай загружения не найден (модель изменилась после grounding)"); }
        SketchPlane __sp_LL2 = SketchPlane.Create(doc, Plane.CreateByNormalAndOrigin(new XYZ(0.31622776601683794, -0.9486832980505138, 0.0), P(0, 500, 3000)));
        if (__sp_LL2 == null) { __t.RollBack(); return __Refuse("LL2", "не удалось построить рабочую плоскость линейной нагрузки"); }
        __el_LL2 = Autodesk.Revit.DB.Structure.LineLoad.Create(doc, P(0, 500, 3000), P(6000, 2500, 4200), new XYZ(UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(-2500.0, UnitTypeId.NewtonsPerMeter)), new XYZ(0, 0, 0), __ty_LL2, __sp_LL2);
        if (__el_LL2 == null) { __t.RollBack(); return __Refuse("LL2", "LineLoad.Create вернул null"); }
        if (!__el_LL2.IsOrientToPermitted(Autodesk.Revit.DB.Structure.LoadOrientTo.Project)) { __t.RollBack(); return __Refuse("LL2", "нагрузка не допускает проектную систему отсчёта"); }
        __el_LL2.OrientTo = Autodesk.Revit.DB.Structure.LoadOrientTo.Project;
        __el_LL2.ForceVector1 = new XYZ(UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerMeter), UnitUtils.ConvertToInternalUnits(-2500.0, UnitTypeId.NewtonsPerMeter));
        __el_LL2.LoadCaseId = __lc_LL2.Id;
        try { Parameter __cm = __el_LL2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7ffacdc7:LL2"); } catch { }

        // create_area_load AL1
        Autodesk.Revit.DB.Structure.AreaLoadType __ty_AL1 = doc.GetElement(new ElementId(1504)) as Autodesk.Revit.DB.Structure.AreaLoadType;
        if (__ty_AL1 == null) { __t.RollBack(); return __Refuse("AL1", "площадная нагрузка: тип не найден (модель изменилась после grounding)"); }
        Autodesk.Revit.DB.Structure.LoadCase __lc_AL1 = doc.GetElement(new ElementId(1501)) as Autodesk.Revit.DB.Structure.LoadCase;
        if (__lc_AL1 == null) { __t.RollBack(); return __Refuse("AL1", "случай загружения не найден (модель изменилась после grounding)"); }
        CurveLoop __ol_AL1 = new CurveLoop();
        __ol_AL1.Append(Line.CreateBound(P(0, 0, 3000.0), P(6000, 0, 3000.0)));
        __ol_AL1.Append(Line.CreateBound(P(6000, 0, 3000.0), P(6000, 4000, 3000.0)));
        __ol_AL1.Append(Line.CreateBound(P(6000, 4000, 3000.0), P(0, 4000, 3000.0)));
        __ol_AL1.Append(Line.CreateBound(P(0, 4000, 3000.0), P(0, 0, 3000.0)));
        var __loops_AL1 = new List<CurveLoop>();
        __loops_AL1.Add(__ol_AL1);
        __el_AL1 = Autodesk.Revit.DB.Structure.AreaLoad.Create(doc, __loops_AL1, new XYZ(UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerSquareMeter), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerSquareMeter), UnitUtils.ConvertToInternalUnits(-3000.0, UnitTypeId.NewtonsPerSquareMeter)), __ty_AL1);
        if (__el_AL1 == null) { __t.RollBack(); return __Refuse("AL1", "AreaLoad.Create вернул null"); }
        if (!__el_AL1.IsOrientToPermitted(Autodesk.Revit.DB.Structure.LoadOrientTo.Project)) { __t.RollBack(); return __Refuse("AL1", "нагрузка не допускает проектную систему отсчёта"); }
        __el_AL1.OrientTo = Autodesk.Revit.DB.Structure.LoadOrientTo.Project;
        __el_AL1.ForceVector1 = new XYZ(UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerSquareMeter), UnitUtils.ConvertToInternalUnits(0.0, UnitTypeId.NewtonsPerSquareMeter), UnitUtils.ConvertToInternalUnits(-3000.0, UnitTypeId.NewtonsPerSquareMeter));
        __el_AL1.LoadCaseId = __lc_AL1.Id;
        try { Parameter __cm = __el_AL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7ffacdc7:AL1"); } catch { }

        doc.Regenerate();

        // post PL1
        {
            var __pt_PL1 = __el_PL1.Point;
            double __vtol_PL1 = doc.Application.VertexTolerance;
            if (__pt_PL1 == null
                || Math.Abs(__pt_PL1.X - U(1000)) > __vtol_PL1
                || Math.Abs(__pt_PL1.Y - U(2000)) > __vtol_PL1
                || Math.Abs(__pt_PL1.Z - U(3000)) > __vtol_PL1)
                __post.Add("PL1: Point построенной нагрузки не совпал с заказанной точкой (geometry)");
            if (__el_PL1.OrientTo != Autodesk.Revit.DB.Structure.LoadOrientTo.Project)
                __post.Add("PL1: OrientTo построенной нагрузки не Project — вектор силы прочитан бы в другой системе отсчёта (semantic)");
            var __vec_force_vector_PL1 = __el_PL1.ForceVector;
            if (Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_PL1.X, UnitTypeId.Newtons) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_PL1.Y, UnitTypeId.Newtons) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_PL1.Z, UnitTypeId.Newtons) - (-10000.0)) > 1e-6)
                __post.Add("PL1: вектор силы построенной нагрузки не совпал с заказанным (semantic)");
            var __vec_moment_vector_PL1 = __el_PL1.MomentVector;
            if (Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_moment_vector_PL1.X, UnitTypeId.NewtonMeters) - (250.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_moment_vector_PL1.Y, UnitTypeId.NewtonMeters) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_moment_vector_PL1.Z, UnitTypeId.NewtonMeters) - (0.0)) > 1e-6)
                __post.Add("PL1: вектор момента построенной нагрузки не совпал с заказанным (semantic)");
            var __lcid_PL1 = __el_PL1.LoadCaseId;
            if (__lcid_PL1 == null || __lcid_PL1.ToString() != "1500")
                __post.Add("PL1: случай загружения построенной нагрузки не тот, что заземлён (semantic)");
            var __tyid_PL1 = __el_PL1.GetTypeId();
            if (__tyid_PL1 == null || __tyid_PL1.ToString() != "1502")
                __post.Add("PL1: load_type построенной нагрузки не тот, что заземлён (semantic)");
        }
        // post LL1
        {
            var __sp0_LL1 = __el_LL1.StartPoint;
            var __sp1_LL1 = __el_LL1.EndPoint;
            double __vtol_LL1 = doc.Application.VertexTolerance;
            if (__sp0_LL1 == null || __sp1_LL1 == null
                || Math.Abs(__sp0_LL1.X - U(0)) > __vtol_LL1
                || Math.Abs(__sp0_LL1.Y - U(0)) > __vtol_LL1
                || Math.Abs(__sp0_LL1.Z - U(3000)) > __vtol_LL1
                || Math.Abs(__sp1_LL1.X - U(6000)) > __vtol_LL1
                || Math.Abs(__sp1_LL1.Y - U(0)) > __vtol_LL1
                || Math.Abs(__sp1_LL1.Z - U(3000)) > __vtol_LL1)
                __post.Add("LL1: StartPoint/EndPoint построенной нагрузки не совпали с заказанными (geometry)");
            if (__el_LL1.OrientTo != Autodesk.Revit.DB.Structure.LoadOrientTo.Project)
                __post.Add("LL1: OrientTo построенной нагрузки не Project — вектор силы прочитан бы в другой системе отсчёта (semantic)");
            var __vec_force_vector_LL1 = __el_LL1.ForceVector1;
            if (Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_LL1.X, UnitTypeId.NewtonsPerMeter) - (120.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_LL1.Y, UnitTypeId.NewtonsPerMeter) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_LL1.Z, UnitTypeId.NewtonsPerMeter) - (-5000.0)) > 1e-6)
                __post.Add("LL1: вектор погонной силы построенной нагрузки не совпал с заказанным (semantic)");
            if (!__el_LL1.IsUniform)
                __post.Add("LL1: построенная линейная нагрузка не равномерна, хотя задан один вектор силы (semantic)");
            var __lcid_LL1 = __el_LL1.LoadCaseId;
            if (__lcid_LL1 == null || __lcid_LL1.ToString() != "1500")
                __post.Add("LL1: случай загружения построенной нагрузки не тот, что заземлён (semantic)");
            var __tyid_LL1 = __el_LL1.GetTypeId();
            if (__tyid_LL1 == null || __tyid_LL1.ToString() != "1503")
                __post.Add("LL1: load_type построенной нагрузки не тот, что заземлён (semantic)");
        }
        // post LL2
        {
            var __sp0_LL2 = __el_LL2.StartPoint;
            var __sp1_LL2 = __el_LL2.EndPoint;
            double __vtol_LL2 = doc.Application.VertexTolerance;
            if (__sp0_LL2 == null || __sp1_LL2 == null
                || Math.Abs(__sp0_LL2.X - U(0)) > __vtol_LL2
                || Math.Abs(__sp0_LL2.Y - U(500)) > __vtol_LL2
                || Math.Abs(__sp0_LL2.Z - U(3000)) > __vtol_LL2
                || Math.Abs(__sp1_LL2.X - U(6000)) > __vtol_LL2
                || Math.Abs(__sp1_LL2.Y - U(2500)) > __vtol_LL2
                || Math.Abs(__sp1_LL2.Z - U(4200)) > __vtol_LL2)
                __post.Add("LL2: StartPoint/EndPoint построенной нагрузки не совпали с заказанными (geometry)");
            if (__el_LL2.OrientTo != Autodesk.Revit.DB.Structure.LoadOrientTo.Project)
                __post.Add("LL2: OrientTo построенной нагрузки не Project — вектор силы прочитан бы в другой системе отсчёта (semantic)");
            var __vec_force_vector_LL2 = __el_LL2.ForceVector1;
            if (Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_LL2.X, UnitTypeId.NewtonsPerMeter) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_LL2.Y, UnitTypeId.NewtonsPerMeter) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_LL2.Z, UnitTypeId.NewtonsPerMeter) - (-2500.0)) > 1e-6)
                __post.Add("LL2: вектор погонной силы построенной нагрузки не совпал с заказанным (semantic)");
            if (!__el_LL2.IsUniform)
                __post.Add("LL2: построенная линейная нагрузка не равномерна, хотя задан один вектор силы (semantic)");
            var __lcid_LL2 = __el_LL2.LoadCaseId;
            if (__lcid_LL2 == null || __lcid_LL2.ToString() != "1501")
                __post.Add("LL2: случай загружения построенной нагрузки не тот, что заземлён (semantic)");
            var __tyid_LL2 = __el_LL2.GetTypeId();
            if (__tyid_LL2 == null || __tyid_LL2.ToString() != "1503")
                __post.Add("LL2: load_type построенной нагрузки не тот, что заземлён (semantic)");
        }
        // post AL1
        {
            var __lps_AL1 = __el_AL1.GetLoops();
            double __vtol_AL1 = doc.Application.VertexTolerance;
            if (__lps_AL1 == null || __lps_AL1.Count != 1)
                __post.Add("AL1: GetLoops построенной нагрузки вернул не одно кольцо (geometry)");
            else
            {
                var __vs_AL1 = new List<XYZ>();
                foreach (Curve __c_AL1 in __lps_AL1[0]) __vs_AL1.Add(__c_AL1.GetEndPoint(0));
                double[] __ex_AL1 = new double[] { 0, 0, 6000, 0, 6000, 4000, 0, 4000 };
                bool __bad_AL1 = __vs_AL1.Count != 4;
                for (int __i = 0; __i < 4 && !__bad_AL1; __i++)
                {
                    bool __hit = false;
                    for (int __j = 0; __j < __vs_AL1.Count; __j++)
                        if (Math.Abs(__vs_AL1[__j].X - U(__ex_AL1[__i * 2])) <= __vtol_AL1
                            && Math.Abs(__vs_AL1[__j].Y - U(__ex_AL1[__i * 2 + 1])) <= __vtol_AL1
                            && Math.Abs(__vs_AL1[__j].Z - U(3000.0)) <= __vtol_AL1)
                            __hit = true;
                    if (!__hit) __bad_AL1 = true;
                }
                if (__bad_AL1) __post.Add("AL1: вершины кольца построенной нагрузки не совпали с заказанным контуром на отметке elev_mm (geometry)");
            }
            if (__el_AL1.OrientTo != Autodesk.Revit.DB.Structure.LoadOrientTo.Project)
                __post.Add("AL1: OrientTo построенной нагрузки не Project — вектор силы прочитан бы в другой системе отсчёта (semantic)");
            var __vec_force_vector_AL1 = __el_AL1.ForceVector1;
            if (Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_AL1.X, UnitTypeId.NewtonsPerSquareMeter) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_AL1.Y, UnitTypeId.NewtonsPerSquareMeter) - (0.0)) > 1e-6 ||
                Math.Abs(UnitUtils.ConvertFromInternalUnits(__vec_force_vector_AL1.Z, UnitTypeId.NewtonsPerSquareMeter) - (-3000.0)) > 1e-6)
                __post.Add("AL1: вектор площадной силы построенной нагрузки не совпал с заказанным (semantic)");
            var __lcid_AL1 = __el_AL1.LoadCaseId;
            if (__lcid_AL1 == null || __lcid_AL1.ToString() != "1501")
                __post.Add("AL1: случай загружения построенной нагрузки не тот, что заземлён (semantic)");
            var __tyid_AL1 = __el_AL1.GetTypeId();
            if (__tyid_AL1 == null || __tyid_AL1.ToString() != "1504")
                __post.Add("AL1: load_type построенной нагрузки не тот, что заземлён (semantic)");
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

// witness PL1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_PL1.Id.ToString();
    try { var __stampParam = __el_PL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["load_case_name"] = __el_PL1.LoadCaseName; } catch { }
    try { __rb["load_nature_name"] = __el_PL1.LoadNatureName; } catch { }
    try { __rb["orient_to"] = __el_PL1.OrientTo.ToString(); } catch { }
    try { __rb["is_hosted"] = __el_PL1.IsHosted; } catch { }
    try { var __tid = __el_PL1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["PL1"] = __rb;
}

// witness LL1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_LL1.Id.ToString();
    try { var __stampParam = __el_LL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["load_case_name"] = __el_LL1.LoadCaseName; } catch { }
    try { __rb["load_nature_name"] = __el_LL1.LoadNatureName; } catch { }
    try { __rb["orient_to"] = __el_LL1.OrientTo.ToString(); } catch { }
    try { __rb["is_hosted"] = __el_LL1.IsHosted; } catch { }
    try { var __tid = __el_LL1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["LL1"] = __rb;
}

// witness LL2
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_LL2.Id.ToString();
    try { var __stampParam = __el_LL2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["load_case_name"] = __el_LL2.LoadCaseName; } catch { }
    try { __rb["load_nature_name"] = __el_LL2.LoadNatureName; } catch { }
    try { __rb["orient_to"] = __el_LL2.OrientTo.ToString(); } catch { }
    try { __rb["is_hosted"] = __el_LL2.IsHosted; } catch { }
    try { var __tid = __el_LL2.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["LL2"] = __rb;
}

// witness AL1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_AL1.Id.ToString();
    try { var __stampParam = __el_AL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["load_case_name"] = __el_AL1.LoadCaseName; } catch { }
    try { __rb["load_nature_name"] = __el_AL1.LoadNatureName; } catch { }
    try { __rb["orient_to"] = __el_AL1.OrientTo.ToString(); } catch { }
    try { __rb["is_hosted"] = __el_AL1.IsHosted; } catch { }
    try { var __tid = __el_AL1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { __rb["area_m2"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_AL1.Area, UnitTypeId.SquareMeters), 3); } catch { }
    __results["AL1"] = __rb;
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