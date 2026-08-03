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
Wall __el_W1 = null;
Dimension __el_D1 = null;
View __vw_D1 = null;
Element __rf_D1_0 = null;
Element __rf_D1_1 = null;
IndependentTag __el_T1 = null; Element __tg_T1 = null;
View __vw_T1 = null;
TextNote __el_X1 = null;
View __vw_X1 = null;
Element __ltel_X1 = null;
using (Transaction __t = new Transaction(doc, "KIR: аннотации с явными типами и выноской"))
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
        WallType __wt_W1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_W1 == null) { __t.RollBack(); return __Refuse("W1", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_W1 = doc.GetElement(new ElementId(42));
        Level __lv_W1 = __lv_raw_W1 as Level;
        if (__lv_W1 == null) { __t.RollBack(); return __Refuse("W1", (__lv_raw_W1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __lv_raw_W1.GetType().Name + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_W1 = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_W1.Id, __lv_W1.Id, U(3000.0), 0.0, false, false);
        if (__el_W1 == null) { __t.RollBack(); return __Refuse("W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9f982893:W1"); } catch { }

        // create_dimension D1
        __vw_D1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_D1 == null) { __t.RollBack(); return __Refuse("D1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        doc.Regenerate();
        __rf_D1_0 = (Element)__el_W1;
        Reference __gref_D1_0 = null;
        Wall __gref_D1_0_wall = __rf_D1_0 as Wall;
        if (__gref_D1_0_wall != null)
        {
            try
            {
                var __gref_D1_0_sf = HostObjectUtils.GetSideFaces(__gref_D1_0_wall, ShellLayerType.Exterior);
                if (__gref_D1_0_sf != null && __gref_D1_0_sf.Count > 0) __gref_D1_0 = __gref_D1_0_sf[0];
            } catch { }
        }
        if (__gref_D1_0 == null)
        {
            Options __gref_D1_0_opt = new Options();
            __gref_D1_0_opt.ComputeReferences = true;
            __gref_D1_0_opt.View = __vw_D1;
            GeometryElement __gref_D1_0_ge = __rf_D1_0.get_Geometry(__gref_D1_0_opt);
            if (__gref_D1_0_ge != null)
                foreach (GeometryObject __gref_D1_0_go in __gref_D1_0_ge)
                {
                    Solid __gref_D1_0_sol = __gref_D1_0_go as Solid;
                    if (__gref_D1_0_sol == null) continue;
                    foreach (Face __gref_D1_0_fc in __gref_D1_0_sol.Faces)
                    {
                        PlanarFace __gref_D1_0_pf = __gref_D1_0_fc as PlanarFace;
                        if (__gref_D1_0_pf != null && __gref_D1_0_pf.Reference != null)
                        { __gref_D1_0 = __gref_D1_0_pf.Reference; break; }
                    }
                    if (__gref_D1_0 != null) break;
                }
        }
        if (__gref_D1_0 == null) { __t.RollBack(); return __Refuse("D1", "refs[0]: у элемента нет геометрической ссылки для размера"); }
        __rf_D1_1 = doc.GetElement(new ElementId(12345));
        if (__rf_D1_1 == null) { __t.RollBack(); return __Refuse("D1", "refs[1]: элемент не найден (модель изменилась после grounding)"); }
        Reference __gref_D1_1 = null;
        Wall __gref_D1_1_wall = __rf_D1_1 as Wall;
        if (__gref_D1_1_wall != null)
        {
            try
            {
                var __gref_D1_1_sf = HostObjectUtils.GetSideFaces(__gref_D1_1_wall, ShellLayerType.Exterior);
                if (__gref_D1_1_sf != null && __gref_D1_1_sf.Count > 0) __gref_D1_1 = __gref_D1_1_sf[0];
            } catch { }
        }
        if (__gref_D1_1 == null)
        {
            Options __gref_D1_1_opt = new Options();
            __gref_D1_1_opt.ComputeReferences = true;
            __gref_D1_1_opt.View = __vw_D1;
            GeometryElement __gref_D1_1_ge = __rf_D1_1.get_Geometry(__gref_D1_1_opt);
            if (__gref_D1_1_ge != null)
                foreach (GeometryObject __gref_D1_1_go in __gref_D1_1_ge)
                {
                    Solid __gref_D1_1_sol = __gref_D1_1_go as Solid;
                    if (__gref_D1_1_sol == null) continue;
                    foreach (Face __gref_D1_1_fc in __gref_D1_1_sol.Faces)
                    {
                        PlanarFace __gref_D1_1_pf = __gref_D1_1_fc as PlanarFace;
                        if (__gref_D1_1_pf != null && __gref_D1_1_pf.Reference != null)
                        { __gref_D1_1 = __gref_D1_1_pf.Reference; break; }
                    }
                    if (__gref_D1_1 != null) break;
                }
        }
        if (__gref_D1_1 == null) { __t.RollBack(); return __Refuse("D1", "refs[1]: у элемента нет геометрической ссылки для размера"); }
        ReferenceArray __refs_D1 = new ReferenceArray();
        __refs_D1.Append(__gref_D1_0);
        __refs_D1.Append(__gref_D1_1);
        XYZ __dimDir_D1 = __vw_D1.RightDirection;
        try
        {
            GeometryObject __ddgo_D1 = __rf_D1_0.GetGeometryObjectFromReference(__gref_D1_0);
            PlanarFace __ddpf_D1 = __ddgo_D1 as PlanarFace;
            if (__ddpf_D1 != null)
            {
                XYZ __ddn_D1 = __ddpf_D1.FaceNormal;
                XYZ __ddInPlane_D1 = __ddn_D1.Subtract(__vw_D1.ViewDirection.Multiply(__ddn_D1.DotProduct(__vw_D1.ViewDirection)));
                if (__ddInPlane_D1.GetLength() > 1e-6) __dimDir_D1 = __ddInPlane_D1.Normalize();
            }
        } catch { }
        XYZ __p0_D1 = (__vw_D1.Origin + __vw_D1.RightDirection.Multiply(U(3000.0)) + __vw_D1.UpDirection.Multiply(U(500.0)));
        Line __ln_D1;
        try { __ln_D1 = Line.CreateBound(__p0_D1, __p0_D1.Add(__dimDir_D1.Multiply(U(1000.0)))); }
        catch (Exception __ex_D1) { __t.RollBack(); return __Refuse("D1", "line_at: вырожденная линия размера: " + __ex_D1.Message); }
        Element __dtel_D1 = doc.GetElement(new ElementId(6001));
        if (__dtel_D1 == null) { __t.RollBack(); return __Refuse("D1", "dim_type: элемент не найден (модель изменилась после grounding)"); }
        DimensionType __dt_D1 = __dtel_D1 as DimensionType;
        if (__dt_D1 == null) { __t.RollBack(); return __Refuse("D1", "dim_type: элемент не DimensionType"); }
        try { __el_D1 = doc.Create.NewDimension(__vw_D1, __ln_D1, __refs_D1, __dt_D1); }
        catch (Exception __ex2_D1) { __t.RollBack(); return __Refuse("D1", "NewDimension: " + __ex2_D1.Message); }
        if (__el_D1 == null) { __t.RollBack(); return __Refuse("D1", "NewDimension вернул null"); }
        try { Parameter __cm = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9f982893:D1"); } catch { }

        // create_tag T1
        __vw_T1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_T1 == null) { __t.RollBack(); return __Refuse("T1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        __tg_T1 = (Element)__el_W1;
        Element __ttel_T1 = doc.GetElement(new ElementId(5555));
        if (__ttel_T1 == null) { __t.RollBack(); return __Refuse("T1", "tag_type: элемент не найден (модель изменилась после grounding)"); }
        try { __el_T1 = IndependentTag.Create(doc, __ttel_T1.Id, __vw_T1.Id, new Reference(__tg_T1), true, TagOrientation.Horizontal, (__vw_T1.Origin + __vw_T1.RightDirection.Multiply(U(3000.0)) + __vw_T1.UpDirection.Multiply(U(800.0)))); }
        catch (Exception __ex_T1) { __t.RollBack(); return __Refuse("T1", "IndependentTag.Create: " + __ex_T1.Message); }
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "IndependentTag.Create вернул null"); }
        try { Parameter __cm = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9f982893:T1"); } catch { }

        // create_text X1
        __vw_X1 = doc.GetElement(new ElementId(900)) as View;
        if (__vw_X1 == null) { __t.RollBack(); return __Refuse("X1", "in_view: вид не найден (модель изменилась после grounding, либо id — не View)"); }
        Element __ttel_X1 = doc.GetElement(new ElementId(7000));
        if (__ttel_X1 == null) { __t.RollBack(); return __Refuse("X1", "text_type: элемент не найден (модель изменилась после grounding)"); }

        try { __el_X1 = TextNote.Create(doc, __vw_X1.Id, (__vw_X1.Origin + __vw_X1.RightDirection.Multiply(U(1000.0)) + __vw_X1.UpDirection.Multiply(U(1000.0))), "См. примечание", __ttel_X1.Id); }
        catch (Exception __ex_X1) { __t.RollBack(); return __Refuse("X1", "TextNote.Create: " + __ex_X1.Message); }
        if (__el_X1 == null) { __t.RollBack(); return __Refuse("X1", "TextNote.Create вернул null"); }
        try { Parameter __cm = __el_X1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:9f982893:X1"); } catch { }
        __ltel_X1 = (Element)__el_W1;
        try
        {
            __el_X1.AddLeader(TextNoteLeaderTypes.TNLT_STRAIGHT_L);
            var __ldrs_X1 = __el_X1.GetLeaders();
            if (__ldrs_X1 != null && __ldrs_X1.Count > 0)
            {
                var __ld_X1 = __ldrs_X1[__ldrs_X1.Count - 1];
                var __ltbb_X1 = __ltel_X1.get_BoundingBox(__vw_X1);
                if (__ltbb_X1 != null)
                {
                    var __ltmid_X1 = (__ltbb_X1.Min + __ltbb_X1.Max) * 0.5;
                    __ld_X1.End = __ltmid_X1;
                }
            }
        } catch { }  // best-effort leader placement (no snap-to-element API)

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
        }
        // post T1
        {
            if (__el_T1.OwnerViewId.ToString() != __vw_T1.Id.ToString())
                __post.Add("T1: tag belongs to wrong view (topology)");
            bool __bound_T1 = false;
            try
            {
                foreach (var __tid in __el_T1.GetTaggedLocalElementIds())
                    if (__tid.ToString() == __tg_T1.Id.ToString()) { __bound_T1 = true; break; }
            } catch { }
            if (!__bound_T1)
                __post.Add("T1: марка не связана с target (semantic, VIEW-BINDING LAW: target не виден в in_view?)");
            try
            {
                var __rel_T1 = __el_T1.TagHeadPosition - __vw_T1.Origin;
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
            if ((__el_X1.Text ?? "").TrimEnd('\r', '\n') != "См. примечание".TrimEnd('\r', '\n'))
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
            bool __leaderTargetVisible_X1 = false; bool __leaderOk_X1 = false;
            try
            {
                var __ltbb2_X1 = __ltel_X1.get_BoundingBox(__vw_X1);
                if (__ltbb2_X1 != null)
                {
                    __leaderTargetVisible_X1 = true;
                    var __ltmid2_X1 = (__ltbb2_X1.Min + __ltbb2_X1.Max) * 0.5;
                    var __ldrs2_X1 = __el_X1.GetLeaders();
                    if (__ldrs2_X1 != null) foreach (var __ldr2 in __ldrs2_X1)
                        if (__ldr2.End.DistanceTo(__ltmid2_X1) <= U(10.0)) { __leaderOk_X1 = true; break; }
                }
            } catch { }
            if (!__leaderTargetVisible_X1)
                __post.Add("X1: leader target not visible in view (semantic, VIEW-BINDING LAW)");
            if (!__leaderOk_X1)
                __post.Add("X1: leader endpoint does not match target (geometry)");
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