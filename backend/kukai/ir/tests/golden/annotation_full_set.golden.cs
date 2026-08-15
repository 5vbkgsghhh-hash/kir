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
Wall __el_W1 = null;
Dimension __el_D1 = null;
View __vw_D1 = null;
Element __rf_D1_0 = null;
Element __rf_D1_1 = null;
XYZ __gpt_D1_0 = null;
XYZ __gpt_D1_1 = null;
XYZ __dimDir_D1 = null;
bool __dimTake_D1(Reference __r, XYZ __o, XYZ __n, XYZ __want,
    ref Reference __gr, ref XYZ __gp, ref XYZ __gn,
    ref Reference __fr, ref XYZ __fp, ref XYZ __fn)
{
    if (__r == null || __o == null || __n == null) return false;
    XYZ __vd = __vw_D1.ViewDirection;
    XYZ __ip = __n.Subtract(__vd.Multiply(__n.DotProduct(__vd)));
    if (__ip.IsZeroLength()) return false;
    __ip = __ip.Normalize();
    if (__fr == null) { __fr = __r; __fp = __o; __fn = __ip; }
    if (__want != null && !__ip.CrossProduct(__want).IsZeroLength()) return false;
    __gr = __r; __gp = __o; __gn = __ip;
    return true;
}
void __dimWalk_D1(GeometryElement __ge, Transform __tf, XYZ __want,
    ref Reference __gr, ref XYZ __gp, ref XYZ __gn,
    ref Reference __fr, ref XYZ __fp, ref XYZ __fn)
{
    if (__ge == null) return;
    foreach (GeometryObject __go in __ge)
    {
        Solid __sol = __go as Solid;
        if (__sol != null)
        {
            foreach (Face __fc in __sol.Faces)
            {
                PlanarFace __pf = __fc as PlanarFace;
                if (__pf == null || __pf.Reference == null) continue;
                if (__dimTake_D1(__pf.Reference, __tf.OfPoint(__pf.Origin),
                        __tf.OfVector(__pf.FaceNormal), __want,
                        ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) return;
            }
            continue;
        }
        Curve __cv = __go as Curve;
        if (__cv != null)
        {
            if (__cv.Reference == null) continue;
            XYZ __ca = null; XYZ __cd = null;
            Line __cl = __cv as Line;
            if (__cl != null) { __ca = __cl.Origin; __cd = __cl.Direction; }
            else if (__cv.IsBound) { __ca = __cv.GetEndPoint(0); __cd = __cv.GetEndPoint(1).Subtract(__ca); }
            if (__ca == null || __cd == null || __cd.IsZeroLength()) continue;
            XYZ __cn = __cd.Normalize().CrossProduct(__vw_D1.ViewDirection);
            if (__cn.IsZeroLength()) continue;
            if (__dimTake_D1(__cv.Reference, __tf.OfPoint(__ca),
                    __tf.OfVector(__cn.Normalize()), __want,
                    ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) return;
            continue;
        }
        GeometryInstance __gi = __go as GeometryInstance;
        if (__gi != null)
        {
            __dimWalk_D1(__gi.GetSymbolGeometry(), __tf.Multiply(__gi.Transform), __want,
                ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn);
            if (__gr != null) return;
        }
    }
}
void __dimGeom_D1(Element __el, XYZ __want, out Reference __gr, out XYZ __gp, out XYZ __gn)
{
    __gr = null; __gp = null; __gn = null;
    Reference __fr = null; XYZ __fp = null; XYZ __fn = null;
    Wall __wl = __el as Wall;
    if (__wl != null)
    {
        try
        {
            IList<Reference> __sf = HostObjectUtils.GetSideFaces(__wl, ShellLayerType.Exterior);
            if (__sf != null)
                foreach (Reference __sr in __sf)
                {
                    PlanarFace __spf = __el.GetGeometryObjectFromReference(__sr) as PlanarFace;
                    if (__spf == null) continue;
                    if (__dimTake_D1(__sr, __spf.Origin, __spf.FaceNormal, __want,
                            ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) break;
                }
        } catch { }
    }
    if (__gr == null)
    {
        Options __gopt = new Options();
        __gopt.ComputeReferences = true;
        __gopt.IncludeNonVisibleObjects = true;
        __gopt.View = __vw_D1;
        GeometryElement __gge = null;
        try { __gge = __el.get_Geometry(__gopt); } catch { }
        __dimWalk_D1(__gge, Transform.Identity, __want,
            ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn);
    }
    if (__gr == null && __fr != null) { __gr = __fr; __gp = __fp; __gn = __fn; }
}
AngularDimension __el_A1 = null;
View __vw_A1 = null;
Element __rf_A1_0 = null;
Element __rf_A1_1 = null;
XYZ __gpt_A1_0 = null;
XYZ __gpt_A1_1 = null;
XYZ __gn_A1_0 = null;
XYZ __gn_A1_1 = null;
double __asw_A1 = 0.0;
bool __dimTake_A1(Reference __r, XYZ __o, XYZ __n, XYZ __want,
    ref Reference __gr, ref XYZ __gp, ref XYZ __gn,
    ref Reference __fr, ref XYZ __fp, ref XYZ __fn)
{
    if (__r == null || __o == null || __n == null) return false;
    XYZ __vd = __vw_A1.ViewDirection;
    XYZ __ip = __n.Subtract(__vd.Multiply(__n.DotProduct(__vd)));
    if (__ip.IsZeroLength()) return false;
    __ip = __ip.Normalize();
    if (__fr == null) { __fr = __r; __fp = __o; __fn = __ip; }
    if (__want != null && !__ip.CrossProduct(__want).IsZeroLength()) return false;
    __gr = __r; __gp = __o; __gn = __ip;
    return true;
}
void __dimWalk_A1(GeometryElement __ge, Transform __tf, XYZ __want,
    ref Reference __gr, ref XYZ __gp, ref XYZ __gn,
    ref Reference __fr, ref XYZ __fp, ref XYZ __fn)
{
    if (__ge == null) return;
    foreach (GeometryObject __go in __ge)
    {
        Solid __sol = __go as Solid;
        if (__sol != null)
        {
            foreach (Face __fc in __sol.Faces)
            {
                PlanarFace __pf = __fc as PlanarFace;
                if (__pf == null || __pf.Reference == null) continue;
                if (__dimTake_A1(__pf.Reference, __tf.OfPoint(__pf.Origin),
                        __tf.OfVector(__pf.FaceNormal), __want,
                        ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) return;
            }
            continue;
        }
        Curve __cv = __go as Curve;
        if (__cv != null)
        {
            if (__cv.Reference == null) continue;
            XYZ __ca = null; XYZ __cd = null;
            Line __cl = __cv as Line;
            if (__cl != null) { __ca = __cl.Origin; __cd = __cl.Direction; }
            else if (__cv.IsBound) { __ca = __cv.GetEndPoint(0); __cd = __cv.GetEndPoint(1).Subtract(__ca); }
            if (__ca == null || __cd == null || __cd.IsZeroLength()) continue;
            XYZ __cn = __cd.Normalize().CrossProduct(__vw_A1.ViewDirection);
            if (__cn.IsZeroLength()) continue;
            if (__dimTake_A1(__cv.Reference, __tf.OfPoint(__ca),
                    __tf.OfVector(__cn.Normalize()), __want,
                    ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) return;
            continue;
        }
        GeometryInstance __gi = __go as GeometryInstance;
        if (__gi != null)
        {
            __dimWalk_A1(__gi.GetSymbolGeometry(), __tf.Multiply(__gi.Transform), __want,
                ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn);
            if (__gr != null) return;
        }
    }
}
void __dimGeom_A1(Element __el, XYZ __want, out Reference __gr, out XYZ __gp, out XYZ __gn)
{
    __gr = null; __gp = null; __gn = null;
    Reference __fr = null; XYZ __fp = null; XYZ __fn = null;
    Wall __wl = __el as Wall;
    if (__wl != null)
    {
        try
        {
            IList<Reference> __sf = HostObjectUtils.GetSideFaces(__wl, ShellLayerType.Exterior);
            if (__sf != null)
                foreach (Reference __sr in __sf)
                {
                    PlanarFace __spf = __el.GetGeometryObjectFromReference(__sr) as PlanarFace;
                    if (__spf == null) continue;
                    if (__dimTake_A1(__sr, __spf.Origin, __spf.FaceNormal, __want,
                            ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn)) break;
                }
        } catch { }
    }
    if (__gr == null)
    {
        Options __gopt = new Options();
        __gopt.ComputeReferences = true;
        __gopt.IncludeNonVisibleObjects = true;
        __gopt.View = __vw_A1;
        GeometryElement __gge = null;
        try { __gge = __el.get_Geometry(__gopt); } catch { }
        __dimWalk_A1(__gge, Transform.Identity, __want,
            ref __gr, ref __gp, ref __gn, ref __fr, ref __fp, ref __fn);
    }
    if (__gr == null && __fr != null) { __gr = __fr; __gp = __fp; __gn = __fn; }
}
Element __el_T1 = null; Element __tg_T1 = null;
View __vw_T1 = null;
TextNote __el_X1 = null;
View __vw_X1 = null;
using (Transaction __t = new Transaction(doc, "KIR: полный набор аннотаций: размер+марка+текст"))
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
        // create_wall W1
        WallType __wt_W1 = doc.GetElement(new ElementId(100)) as WallType;
        if (__wt_W1 == null) { __t.RollBack(); return __Refuse("W1", "тип стены не найден (модель изменилась после grounding)"); }
        Element __lv_raw_W1 = doc.GetElement(new ElementId(42));
        Level __lv_W1 = __lv_raw_W1 as Level;
        if (__lv_W1 == null) { __t.RollBack(); return __Refuse("W1", (__lv_raw_W1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_W1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_W1 = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_W1.Id, __lv_W1.Id, U(3000.0), 0.0, false, false);
        if (__el_W1 == null) { __t.RollBack(); return __Refuse("W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6610b7b2:W1"); } catch { }

        // create_dimension D1
        __vw_D1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_D1 == null) { __t.RollBack(); return __Refuse("D1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        doc.Regenerate();
        __rf_D1_0 = (Element)__el_W1;
        Reference __gref_D1_0 = null;
        XYZ __gn_D1_0 = null;
        __dimGeom_D1(__rf_D1_0, null, out __gref_D1_0, out __gpt_D1_0, out __gn_D1_0);
        if (__gref_D1_0 == null) { __t.RollBack(); return __Refuse("D1", "refs[0]: у элемента нет геометрической ссылки для размера"); }
        __rf_D1_1 = doc.GetElement(new ElementId(12345));
        if (__rf_D1_1 == null) { __t.RollBack(); return __Refuse("D1", "refs[1]: элемент не найден (модель изменилась после grounding)"); }
        Reference __gref_D1_1 = null;
        XYZ __gn_D1_1 = null;
        __dimGeom_D1(__rf_D1_1, __gn_D1_0, out __gref_D1_1, out __gpt_D1_1, out __gn_D1_1);
        if (__gref_D1_1 == null) { __t.RollBack(); return __Refuse("D1", "refs[1]: у элемента нет геометрической ссылки для размера"); }
        ReferenceArray __refs_D1 = new ReferenceArray();
        __refs_D1.Append(__gref_D1_0);
        __refs_D1.Append(__gref_D1_1);
        __dimDir_D1 = __gn_D1_0;
        XYZ __p0_D1 = (__vw_D1.Origin + __vw_D1.RightDirection.Multiply(U(3000.0)) + __vw_D1.UpDirection.Multiply(U(500.0)));
        Line __ln_D1;
        try { __ln_D1 = Line.CreateBound(__p0_D1, __p0_D1.Add(__dimDir_D1.Multiply(U(1000.0)))); }
        catch (Exception __ex_D1) { __t.RollBack(); return __Refuse("D1", "line_at: вырожденная линия размера: " + __ex_D1.Message); }

        try { __el_D1 = doc.Create.NewDimension(__vw_D1, __ln_D1, __refs_D1); }
        catch (Exception __ex2_D1) { __t.RollBack(); return __Refuse("D1", "NewDimension: " + __ex2_D1.Message); }
        if (__el_D1 == null) { __t.RollBack(); return __Refuse("D1", "NewDimension вернул null"); }
        try { Parameter __cm = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6610b7b2:D1"); } catch { }

        // create_angular_dimension A1
        __vw_A1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_A1 == null) { __t.RollBack(); return __Refuse("A1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        doc.Regenerate();
        __rf_A1_0 = (Element)__el_W1;
        Reference __gref_A1_0 = null;
        __dimGeom_A1(__rf_A1_0, null, out __gref_A1_0, out __gpt_A1_0, out __gn_A1_0);
        if (__gref_A1_0 == null) { __t.RollBack(); return __Refuse("A1", "refs[0]: у элемента нет геометрической ссылки для размера"); }
        __rf_A1_1 = doc.GetElement(new ElementId(12345));
        if (__rf_A1_1 == null) { __t.RollBack(); return __Refuse("A1", "refs[1]: элемент не найден (модель изменилась после grounding)"); }
        Reference __gref_A1_1 = null;
        __dimGeom_A1(__rf_A1_1, null, out __gref_A1_1, out __gpt_A1_1, out __gn_A1_1);
        if (__gref_A1_1 == null) { __t.RollBack(); return __Refuse("A1", "refs[1]: у элемента нет геометрической ссылки для размера"); }
        XYZ __aR_A1 = __vw_A1.RightDirection;
        XYZ __aU_A1 = __vw_A1.UpDirection;
        XYZ __aO_A1 = __vw_A1.Origin;
        double __aa0_A1 = __gn_A1_0.DotProduct(__aR_A1);
        double __ab0_A1 = __gn_A1_0.DotProduct(__aU_A1);
        double __ac0_A1 = __gpt_A1_0.Subtract(__aO_A1).DotProduct(__gn_A1_0);
        double __aa1_A1 = __gn_A1_1.DotProduct(__aR_A1);
        double __ab1_A1 = __gn_A1_1.DotProduct(__aU_A1);
        double __ac1_A1 = __gpt_A1_1.Subtract(__aO_A1).DotProduct(__gn_A1_1);
        double __adet_A1 = __aa0_A1 * __ab1_A1 - __aa1_A1 * __ab0_A1;
        if (Math.Abs(__adet_A1) <= doc.Application.AngleTolerance) { __t.RollBack(); return __Refuse("A1", "refs: ссылки параллельны — у угла нет вершины"); }
        XYZ __avx_A1 = __aO_A1
            .Add(__aR_A1.Multiply((__ac0_A1 * __ab1_A1 - __ac1_A1 * __ab0_A1) / __adet_A1))
            .Add(__aU_A1.Multiply((__aa0_A1 * __ac1_A1 - __aa1_A1 * __ac0_A1) / __adet_A1));
        XYZ __aat_A1 = (__vw_A1.Origin + __vw_A1.RightDirection.Multiply(U(1500.0)) + __vw_A1.UpDirection.Multiply(U(1500.0)));
        XYZ __arv_A1 = __aat_A1.Subtract(__avx_A1);
        if (__arv_A1.IsZeroLength()) { __t.RollBack(); return __Refuse("A1", "at: точка совпала с вершиной угла — у дуги размера нулевой радиус"); }
        XYZ __ad0_A1 = __gn_A1_0.CrossProduct(__vw_A1.ViewDirection).Normalize();
        if (__ad0_A1.DotProduct(__arv_A1) < 0.0) __ad0_A1 = __ad0_A1.Negate();
        XYZ __ad1_A1 = __gn_A1_1.CrossProduct(__vw_A1.ViewDirection).Normalize();
        if (__ad1_A1.DotProduct(__arv_A1) < 0.0) __ad1_A1 = __ad1_A1.Negate();
        XYZ __ay_A1 = __vw_A1.ViewDirection.CrossProduct(__ad0_A1).Normalize();
        if (__ay_A1.DotProduct(__ad1_A1) < 0.0) __ay_A1 = __ay_A1.Negate();
        __asw_A1 = Math.Atan2(__ad1_A1.DotProduct(__ay_A1), __ad1_A1.DotProduct(__ad0_A1));
        Arc __arc_A1;
        try { __arc_A1 = Arc.Create(__avx_A1, __arv_A1.GetLength(), 0.0, __asw_A1, __ad0_A1, __ay_A1); }
        catch (Exception __ex_A1) { __t.RollBack(); return __Refuse("A1", "at: вырожденная дуга углового размера: " + __ex_A1.Message); }
        DimensionType __dt_A1 = doc.GetElement(doc.GetDefaultElementTypeId(
            ElementTypeGroup.AngularDimensionType)) as DimensionType;
        if (__dt_A1 == null) { __t.RollBack(); return __Refuse("A1", "dim_type: в документе нет типа углового размера по умолчанию — назовите dim_type явно"); }
        IList<Reference> __arefs_A1 = new List<Reference>();
        __arefs_A1.Add(__gref_A1_0);
        __arefs_A1.Add(__gref_A1_1);
        try { __el_A1 = AngularDimension.Create(doc, __vw_A1, __arc_A1, __arefs_A1, __dt_A1); }
        catch (Exception __ex2_A1) { __t.RollBack(); return __Refuse("A1", "AngularDimension.Create: " + __ex2_A1.Message); }
        if (__el_A1 == null) { __t.RollBack(); return __Refuse("A1", "AngularDimension.Create вернул null"); }
        try { Parameter __cm = __el_A1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6610b7b2:A1"); } catch { }

        // create_tag T1
        __vw_T1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_T1 == null) { __t.RollBack(); return __Refuse("T1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        __tg_T1 = (Element)__el_W1;

        try {
            var __se_T1 = __tg_T1 as SpatialElement;
            if (__se_T1 != null)
            {
                if (__se_T1.Location == null || __se_T1.Area <= 0.0)
                    { __t.RollBack(); return __Refuse("T1", "цель — пространственный элемент, который НЕ РАЗМЕЩЁН (нет Location или нулевая площадь): маркировать нечего"); }
                var __uv_T1 = new UV(3000.0, 800.0);
                var __rm_T1 = __se_T1 as Autodesk.Revit.DB.Architecture.Room;
                var __ar_T1 = __se_T1 as Area;
                var __sc_T1 = __se_T1 as Autodesk.Revit.DB.Mechanical.Space;
                if (__rm_T1 != null)
                    __el_T1 = doc.Create.NewRoomTag(new LinkElementId(__rm_T1.Id), __uv_T1, __vw_T1.Id);
                else if (__sc_T1 != null)
                    __el_T1 = doc.Create.NewSpaceTag(__sc_T1, __uv_T1, __vw_T1);
                else if (__ar_T1 != null)
                {
                    var __vp_T1 = __vw_T1 as ViewPlan;
                    if (__vp_T1 == null)
                        { __t.RollBack(); return __Refuse("T1", "марка площади требует вид-план (ViewPlan), а in_view — " + __vw_T1.ViewType.ToString()); }
                    __el_T1 = doc.Create.NewAreaTag(__vp_T1, __ar_T1, __uv_T1);
                }
                else
                    { __t.RollBack(); return __Refuse("T1", "цель — SpatialElement рода " + __se_T1.GetType().Name + ", а марки строятся только для помещения, площади и пространства"); }
            }
            else
            {
                __el_T1 = IndependentTag.Create(doc, __vw_T1.Id, new Reference(__tg_T1), false, TagMode.TM_ADDBY_CATEGORY, TagOrientation.Horizontal, (__vw_T1.Origin + __vw_T1.RightDirection.Multiply(U(3000.0)) + __vw_T1.UpDirection.Multiply(U(800.0))));
            }
        }
        catch (Exception __ex_T1) { __t.RollBack(); return __Refuse("T1", "IndependentTag.Create: " + __ex_T1.Message); }
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "IndependentTag.Create вернул null"); }
        try { Parameter __cm = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6610b7b2:T1"); } catch { }

        // create_text X1
        __vw_X1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_X1 == null) { __t.RollBack(); return __Refuse("X1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        ElementId __ttid_X1 = doc.GetDefaultElementTypeId(ElementTypeGroup.TextNoteType);
        if (__ttid_X1 == null || __ttid_X1 == ElementId.InvalidElementId)
            { __t.RollBack(); return __Refuse("X1", "в документе нет типа текста по умолчанию"); }

        try { __el_X1 = TextNote.Create(doc, __vw_X1.Id, (__vw_X1.Origin + __vw_X1.RightDirection.Multiply(U(1000.0)) + __vw_X1.UpDirection.Multiply(U(1000.0))), "Стена наружная", __ttid_X1); }
        catch (Exception __ex_X1) { __t.RollBack(); return __Refuse("X1", "TextNote.Create: " + __ex_X1.Message); }
        if (__el_X1 == null) { __t.RollBack(); return __Refuse("X1", "TextNote.Create вернул null"); }
        try { Parameter __cm = __el_X1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:6610b7b2:X1"); } catch { }


        doc.Regenerate();

        // post W1
        {
            var __lc = __el_W1.Location as LocationCurve;
            if (__lc == null) __post.Add("W1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("W1: endpoints mismatch (geometry)");
            }
            var __bp = __el_W1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("W1: level binding mismatch (topology)");
            var __hp = __el_W1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("W1: height mismatch");
        }
        // post D1
        {
            if (__el_D1.OwnerViewId.ToString() != __vw_D1.Id.ToString())
                __post.Add("D1: dimension belongs to wrong view (topology)");
            var __requested_D1 = new List<string>() { __rf_D1_0.Id.ToString(), __rf_D1_1.Id.ToString() };
            var __actual_D1 = new List<string>(); bool __refsReadable_D1 = true;
            try { foreach (Reference __rr in __el_D1.References) if (__rr != null && __rr.ElementId != null) __actual_D1.Add(__rr.ElementId.ToString()); }
            catch { __refsReadable_D1 = false; }
            if (!__refsReadable_D1 || __actual_D1.Count != __requested_D1.Count ||
                !__actual_D1.OrderBy(__x => __x, StringComparer.Ordinal).SequenceEqual(
                    __requested_D1.OrderBy(__x => __x, StringComparer.Ordinal)))
                __post.Add("D1: References do not match requested refs (topology)");
            var __proj_D1 = new List<double>();
            __proj_D1.Add(__gpt_D1_0.DotProduct(__dimDir_D1));
            __proj_D1.Add(__gpt_D1_1.DotProduct(__dimDir_D1));
            __proj_D1.Sort();
            var __expect_D1 = new List<double>();
            for (int __pi = 0; __pi + 1 < __proj_D1.Count; __pi++)
                __expect_D1.Add(__proj_D1[__pi + 1] - __proj_D1[__pi]);
            var __got_D1 = new List<double>(); bool __valRead_D1 = true;
            try
            {
                if (__el_D1.NumberOfSegments > 1)
                    foreach (DimensionSegment __sg_D1 in __el_D1.Segments)
                        __got_D1.Add(__sg_D1.Value ?? double.NaN);
                else __got_D1.Add(__el_D1.Value ?? double.NaN);
            }
            catch { __valRead_D1 = false; }
            double __vtol_D1 = doc.Application.VertexTolerance;
            bool __valBad_D1 = !__valRead_D1 || __got_D1.Count != __expect_D1.Count;
            if (!__valBad_D1)
                for (int __vi = 0; __vi < __expect_D1.Count; __vi++)
                    if (double.IsNaN(__got_D1[__vi]) ||
                        Math.Abs(__got_D1[__vi] - __expect_D1[__vi]) > __vtol_D1)
                        __valBad_D1 = true;
            if (__valBad_D1)
                __post.Add("D1: measured value is not the distance between the referenced geometry (geometry)");
        }
        // post A1
        {
            if (__el_A1.OwnerViewId.ToString() != __vw_A1.Id.ToString())
                __post.Add("A1: angular dimension belongs to wrong view (topology)");
            var __requested_A1 = new List<string>() { __rf_A1_0.Id.ToString(), __rf_A1_1.Id.ToString() };
            var __actual_A1 = new List<string>(); bool __refsReadable_A1 = true;
            try { foreach (Reference __rr in __el_A1.References) if (__rr != null && __rr.ElementId != null) __actual_A1.Add(__rr.ElementId.ToString()); }
            catch { __refsReadable_A1 = false; }
            if (!__refsReadable_A1 || __actual_A1.Count != __requested_A1.Count ||
                !__actual_A1.OrderBy(__x => __x, StringComparer.Ordinal).SequenceEqual(
                    __requested_A1.OrderBy(__x => __x, StringComparer.Ordinal)))
                __post.Add("A1: References do not match requested refs (topology)");
            double __agot_A1 = double.NaN; bool __aRead_A1 = true;
            try { __agot_A1 = __el_A1.Value ?? double.NaN; }
            catch { __aRead_A1 = false; }
            if (!__aRead_A1 || double.IsNaN(__agot_A1) ||
                Math.Abs(__agot_A1 - __asw_A1) > doc.Application.AngleTolerance)
                __post.Add("A1: measured angle is not the sweep of the arc built from the references (geometry)");
        }
        // post T1
        {
            if (__el_T1.OwnerViewId.ToString() != __vw_T1.Id.ToString())
                __post.Add("T1: tag belongs to wrong view (topology)");
            bool __bound_T1 = false;
            var __itg_T1 = __el_T1 as IndependentTag;
            var __rtg_T1 = __el_T1 as Autodesk.Revit.DB.Architecture.RoomTag;
            var __atg_T1 = __el_T1 as AreaTag;
            var __stg_T1 = __el_T1 as Autodesk.Revit.DB.Mechanical.SpaceTag;
            if (__rtg_T1 != null)
            { try { __bound_T1 = __rtg_T1.Room != null && __rtg_T1.Room.Id.ToString() == __tg_T1.Id.ToString(); } catch { } }
            else if (__atg_T1 != null)
            { try { __bound_T1 = __atg_T1.Area != null && __atg_T1.Area.Id.ToString() == __tg_T1.Id.ToString(); } catch { } }
            else if (__stg_T1 != null)
            { try { __bound_T1 = __stg_T1.Space != null && __stg_T1.Space.Id.ToString() == __tg_T1.Id.ToString(); } catch { } }
            else if (__itg_T1 != null)
            try
            {
                foreach (Element __tel in __itg_T1.GetTaggedLocalElements())
                    if (__tel != null && __tel.Id.ToString() == __tg_T1.Id.ToString()) { __bound_T1 = true; break; }
            } catch { }
            else
            { }
            if (!__bound_T1)
                __post.Add("T1: марка не связана с target (semantic, VIEW-BINDING LAW: target не виден в in_view?)");
            try
            {
                XYZ __head_T1 = (__el_T1 as IndependentTag) != null
                    ? ((IndependentTag)__el_T1).TagHeadPosition
                    : ((SpatialElementTag)__el_T1).TagHeadPosition;
                var __rel_T1 = __head_T1 - __vw_T1.Origin;
                double __ou_T1 = MM(__rel_T1.DotProduct(__vw_T1.RightDirection));
                double __ow_T1 = MM(__rel_T1.DotProduct(__vw_T1.UpDirection));
                if (Math.Abs(__ou_T1 - 3000.0) > 10.0 || Math.Abs(__ow_T1 - 800.0) > 10.0)
                    __post.Add("T1: tag head differs from at (geometry)");
            } catch { __post.Add("T1: tag head unreadable (geometry)"); }
        }
        // post X1
        {
            if (__el_X1.OwnerViewId.ToString() != __vw_X1.Id.ToString())
                __post.Add("X1: text belongs to wrong view (topology)");
            if ((__el_X1.Text ?? "").TrimEnd('\r', '\n') != "Стена наружная".TrimEnd('\r', '\n'))
                __post.Add("X1: content не совпадает после чтения (semantic)");
            try
            {
                var __loc_X1 = __el_X1.Coord;
                var __rel_X1 = __loc_X1 - __vw_X1.Origin;
                double __ou_X1 = MM(__rel_X1.DotProduct(__vw_X1.RightDirection));
                double __ow_X1 = MM(__rel_X1.DotProduct(__vw_X1.UpDirection));
                if (Math.Abs(__ou_X1 - 1000.0) > 5.0 || Math.Abs(__ow_X1 - 1000.0) > 5.0)
                    __post.Add("X1: at смещена относительно заданной точки вида (geometry)");
            } catch { __post.Add("X1: text position unreadable (geometry)"); }
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

// witness W1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_W1.Id.ToString();
    try { var __stampParam = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_W1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_W1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["W1"] = __rb;
}

// witness D1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_D1.Id.ToString();
    try { var __stampParam = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["value_mm"] = Math.Round(MM(__el_D1.Value ?? 0.0), 1); } catch { }
    try { __rb["references"] = __el_D1.References.Size; } catch { }
    __results["D1"] = __rb;
}

// witness A1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_A1.Id.ToString();
    try { var __stampParam = __el_A1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["value_deg"] = Math.Round((__el_A1.Value ?? 0.0) * 180.0 / Math.PI, 3); } catch { }
    try { __rb["references"] = __el_A1.References.Size; } catch { }
    __results["A1"] = __rb;
}

// witness T1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_T1.Id.ToString();
    try { var __stampParam = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __rb["tagged_id"] = __tg_T1.Id.ToString();
    __results["T1"] = __rb;
}

// witness X1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_X1.Id.ToString();
    try { var __stampParam = __el_X1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { __rb["content"] = __el_X1.Text; } catch { }
    __results["X1"] = __rb;
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