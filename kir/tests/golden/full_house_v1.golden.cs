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
// Округление половиной ОТ НУЛЯ на решётке канона — тот же закон, что у
// decompile.geom_extract._round_mm (floor(s+0.5) / ceil(s-0.5)), а не
// Math.Round: Math.Round(MidpointRounding.ToEven) увёл бы ровно половину
// граничных вершин в соседнюю ячейку и прообраз разошёлся бы с питоновским.
Func<double, double, long> __KirCanonUnit = (__cuMm, __cuGrid) =>
{
    double __cuS = __cuMm / __cuGrid;
    return __cuS >= 0.0
        ? (long)Math.Floor(__cuS + 0.5)
        : (long)Math.Ceiling(__cuS - 0.5);
};
// Лексикографический порядок по целым — тот же, что у python sorted() над
// кортежами: сначала поэлементно, при равенстве — по длине.
Comparison<long[]> __KirCanonCmp = (__ccA, __ccB) =>
{
    int __ccN = __ccA.Length < __ccB.Length ? __ccA.Length : __ccB.Length;
    for (int __ccI = 0; __ccI < __ccN; __ccI++)
    {
        if (__ccA[__ccI] < __ccB[__ccI]) return -1;
        if (__ccA[__ccI] > __ccB[__ccI]) return 1;
    }
    return __ccA.Length.CompareTo(__ccB.Length);
};
// Оболочку JSON (__cpHead/__cpTail) присылает Python — она выведена из того же
// канонизатора, а не набрана здесь второй раз. List.Sort нестабилен, и это
// безразлично: порядок полный по ВСЕМ девяти числам, значит равные строки
// неразличимы по значению.
Func<List<long[]>, string, string, string> __KirCanonPayload =
    (__cpRows, __cpHead, __cpTail) =>
{
    __cpRows.Sort(__KirCanonCmp);
    var __cpSb = new StringBuilder(__cpHead);
    for (int __cpI = 0; __cpI < __cpRows.Count; __cpI++)
    {
        if (__cpI > 0) __cpSb.Append(',');
        long[] __cpR = __cpRows[__cpI];
        for (int __cpJ = 0; __cpJ < 3; __cpJ++)
        {
            __cpSb.Append(__cpJ == 0 ? "[[" : ",[");
            for (int __cpK = 0; __cpK < 3; __cpK++)
            {
                if (__cpK > 0) __cpSb.Append(',');
                __cpSb.Append(__cpR[__cpJ * 3 + __cpK].ToString(
                    System.Globalization.CultureInfo.InvariantCulture));
            }
            __cpSb.Append(']');
        }
        __cpSb.Append(']');
    }
    __cpSb.Append(__cpTail);
    return __cpSb.ToString();
};
var __results = new Dictionary<string, object>();
var __post = new List<string>();
Level __el_L1 = null;
Wall __el_W1 = null;
ElementId __requestedType_W1 = null;
ElementId __assignedType_W1 = null;
FamilyInstance __el_Win1 = null;
Level __hl_Win1 = null;
FamilyInstance __el_D1 = null;
Level __hl_D1 = null;
Floor __el_F1 = null;
ElementId __requestedType_F1 = null;
ElementId __assignedType_F1 = null;
FamilyInstance __el_C1 = null;
Autodesk.Revit.DB.Architecture.Room __el_R1 = null;
FamilyInstance __el_T1 = null;
using (Transaction __t = new Transaction(doc, "KIR: полный дом v1"))
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
        // create_level L1
        __el_L1 = Level.Create(doc, U(0.0));
        if (__el_L1 == null) { __t.RollBack(); return __Refuse("L1", "Level.Create вернул null"); }
        try { __el_L1.Name = "КИР-1"; }
        catch (Exception __ex_L1) { __t.RollBack(); return __Refuse("L1", "имя уровня: " + __ex_L1.Message); }
        try { Parameter __cm = __el_L1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:L1"); } catch { }

        // create_wall W1
        WallType __wt_W1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_W1 == null) { __t.RollBack(); return __Refuse("W1", "в документе нет типа стены по умолчанию"); }
        Level __lv_W1 = __el_L1;
        __el_W1 = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(8000, 0, 0)), __wt_W1.Id, __lv_W1.Id, U(3000.0), 0.0, false, false);
        if (__el_W1 == null) { __t.RollBack(); return __Refuse("W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:W1"); } catch { }
        int __operationPostStart_W1 = __post.Count;
        // operation W1
        {
            try { __requestedType_W1 = __wt_W1.Id;
                __assignedType_W1 = __el_W1.GetTypeId(); } catch { }
            if (__requestedType_W1 == null || __requestedType_W1 == ElementId.InvalidElementId
                || __assignedType_W1 == null || __assignedType_W1 == ElementId.InvalidElementId
                || !__assignedType_W1.Equals(__requestedType_W1))
                __post.Add("W1: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_W1) { __t.RollBack(); return __Refuse("W1", String.Join(" ; ", __post.Skip(__operationPostStart_W1))); }


        // create_window Win1
        FamilySymbol __sy_Win1 = doc.GetElement(new ElementId(600)) as FamilySymbol;
        if (__sy_Win1 == null) { __t.RollBack(); return __Refuse("Win1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_Win1.IsActive) { __sy_Win1.Activate(); doc.Regenerate(); }
        __hl_Win1 = doc.GetElement(__el_W1.LevelId) as Level;
        if (__hl_Win1 == null) { __t.RollBack(); return __Refuse("Win1", "уровень стены-хоста не найден"); }
        XYZ __pt_Win1 = new XYZ(U(2000.0), U(0.0), __hl_Win1.Elevation + U(900.0));
        __el_Win1 = doc.Create.NewFamilyInstance(__pt_Win1, __sy_Win1, __el_W1, __hl_Win1, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (__el_Win1 == null) { __t.RollBack(); return __Refuse("Win1", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_Win1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:Win1"); } catch { }

        // create_door D1
        FamilySymbol __sy_D1 = doc.GetElement(new ElementId(700)) as FamilySymbol;
        if (__sy_D1 == null) { __t.RollBack(); return __Refuse("D1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_D1.IsActive) { __sy_D1.Activate(); doc.Regenerate(); }
        __hl_D1 = doc.GetElement(__el_W1.LevelId) as Level;
        if (__hl_D1 == null) { __t.RollBack(); return __Refuse("D1", "уровень стены-хоста не найден"); }
        XYZ __pt_D1 = new XYZ(U(5000.0), U(0.0), __hl_D1.Elevation + U(0.0));
        __el_D1 = doc.Create.NewFamilyInstance(__pt_D1, __sy_D1, __el_W1, __hl_D1, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (__el_D1 == null) { __t.RollBack(); return __Refuse("D1", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:D1"); } catch { }

        // create_floor F1
        FloorType __ft_F1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.FloorType)) as FloorType;
        if (__ft_F1 == null) { __t.RollBack(); return __Refuse("F1", "в документе нет типа перекрытия по умолчанию"); }
        Level __lv_F1 = __el_L1;
        var __loops_F1 = new List<CurveLoop>();
        CurveLoop __ol_F1 = new CurveLoop();
        __ol_F1.Append(Line.CreateBound(P(0, 0, 0), P(8000, 0, 0)));
        __ol_F1.Append(Line.CreateBound(P(8000, 0, 0), P(8000, 6000, 0)));
        __ol_F1.Append(Line.CreateBound(P(8000, 6000, 0), P(0, 6000, 0)));
        __ol_F1.Append(Line.CreateBound(P(0, 6000, 0), P(0, 0, 0)));
        __loops_F1.Add(__ol_F1);
        __el_F1 = Floor.Create(doc, __loops_F1, __ft_F1.Id, __lv_F1.Id);
        if (__el_F1 == null) { __t.RollBack(); return __Refuse("F1", "создание перекрытия вернуло null"); }
        try { Parameter __cm = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:F1"); } catch { }
        int __operationPostStart_F1 = __post.Count;
        // operation F1
        {
            try { __requestedType_F1 = __ft_F1.Id;
                __assignedType_F1 = __el_F1.GetTypeId(); } catch { }
            if (__requestedType_F1 == null || __requestedType_F1 == ElementId.InvalidElementId
                || __assignedType_F1 == null || __assignedType_F1 == ElementId.InvalidElementId
                || !__assignedType_F1.Equals(__requestedType_F1))
                __post.Add("F1: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_F1) { __t.RollBack(); return __Refuse("F1", String.Join(" ; ", __post.Skip(__operationPostStart_F1))); }


        // create_column C1
        FamilySymbol __sy_C1 = doc.GetElement(new ElementId(500)) as FamilySymbol;
        if (__sy_C1 == null) { __t.RollBack(); return __Refuse("C1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_C1.IsActive) { __sy_C1.Activate(); doc.Regenerate(); }
        Level __lv_C1 = __el_L1;
        __el_C1 = doc.Create.NewFamilyInstance(P(4000, 3000, 0), __sy_C1, __lv_C1, Autodesk.Revit.DB.Structure.StructuralType.Column);
        if (__el_C1 == null) { __t.RollBack(); return __Refuse("C1", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_C1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:C1"); } catch { }

        doc.Regenerate();  // realise everything created above before the enclosure is resolved
        // create_room R1
        Level __lv_R1 = __el_L1;
        __el_R1 = doc.Create.NewRoom(__lv_R1, new UV(U(4000), U(3000)));
        if (__el_R1 == null) { __t.RollBack(); return __Refuse("R1", "NewRoom вернул null"); }
        try { __el_R1.Name = "Зал"; }
        catch (Exception __ex_R1) { __t.RollBack(); return __Refuse("R1", "имя помещения: " + __ex_R1.Message); }
        try { Parameter __cm = __el_R1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:R1"); } catch { }

        // place_family T1
        FamilySymbol __sy_T1 = doc.GetElement(new ElementId(800)) as FamilySymbol;
        if (__sy_T1 == null) { __t.RollBack(); return __Refuse("T1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_T1.IsActive) { __sy_T1.Activate(); doc.Regenerate(); }
        Level __lv_T1 = __el_L1;
        XYZ __pfp_T1 = new XYZ(U(2000), U(2000), U(0) - __lv_T1.Elevation);
        __el_T1 = doc.Create.NewFamilyInstance(__pfp_T1, __sy_T1, __lv_T1, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (__el_T1 == null) { __t.RollBack(); return __Refuse("T1", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:242410e8:T1"); } catch { }

        doc.Regenerate();

        // post L1
        {
            if (Math.Abs(MM(__el_L1.Elevation) - 0.0) > 1.0)
                __post.Add("L1: elevation mismatch (geometry)");
            if (__el_L1.Name != "КИР-1") __post.Add("L1: name mismatch");
        }
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
                    Math.Abs(MM(__e1.X) - 8000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("W1: endpoints mismatch (geometry)");
            }
            var __bp = __el_W1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != __el_L1.Id.ToString())
                __post.Add("W1: level binding mismatch (topology)");
            var __hp = __el_W1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("W1: height mismatch");
        }
        // post Win1
        {
            if (__el_Win1.Host == null || __el_Win1.Host.Id.ToString() != __el_W1.Id.ToString())
                __post.Add("Win1: host mismatch (topology)");
            var __loc = __el_Win1.Location as LocationPoint;
            if (__loc == null) __post.Add("Win1: no LocationPoint (geometry)");
            else if (Math.Abs(MM(__loc.Point.X) - 2000.0) > 10.0 || Math.Abs(MM(__loc.Point.Y) - 0.0) > 10.0 ||
                     Math.Abs(__loc.Point.Z - (__hl_Win1.Elevation + U(900.0))) > U(10.0))
                __post.Add("Win1: location/sill mismatch (geometry)");
        }
        // post D1
        {
            if (__el_D1.Host == null || __el_D1.Host.Id.ToString() != __el_W1.Id.ToString())
                __post.Add("D1: host mismatch (topology)");
            var __loc = __el_D1.Location as LocationPoint;
            if (__loc == null) __post.Add("D1: no LocationPoint (geometry)");
            else if (Math.Abs(MM(__loc.Point.X) - 5000.0) > 10.0 || Math.Abs(MM(__loc.Point.Y) - 0.0) > 10.0 ||
                     Math.Abs(__loc.Point.Z - (__hl_D1.Elevation + U(0.0))) > U(10.0))
                __post.Add("D1: location/sill mismatch (geometry)");
        }
        // post F1
        {
            Parameter __lp = __el_F1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_F1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_F1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_F1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != __el_L1.Id.ToString())
                __post.Add("F1: level binding mismatch (topology)");
            var __struct = __el_F1.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);
            if (__struct == null || __struct.AsInteger() != 0)
                __post.Add("F1: structural flag mismatch (semantic)");
            var __bb = __el_F1.get_BoundingBox(null);
            if (__bb == null) __post.Add("F1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 8000) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 6000) > 50.0)
                __post.Add("F1: bbox extents mismatch (geometry): "
                    + "[" + MM(__bb.Min.X).ToString("F1") + " " + MM(__bb.Max.X).ToString("F1")
                    + " | " + MM(__bb.Min.Y).ToString("F1") + " " + MM(__bb.Max.Y).ToString("F1") + "]"
                    + " против авторских [0 8000 | 0 6000] при допуске 50.0 мм");
            string __slf_F1 = null;
            try
            {
                List<List<Curve>> __slL_F1 = null;
                var __slk_F1 = new List<Sketch>();
                foreach (ElementId __sld_F1 in __el_F1.GetDependentElements(null))
                {
                    var __sls_F1 = doc.GetElement(__sld_F1) as Sketch;
                    if (__sls_F1 != null) __slk_F1.Add(__sls_F1);
                }
                if (__slk_F1.Count == 1)
                {
                    __slL_F1 = new List<List<Curve>>();
                    foreach (CurveArray __slc0_F1 in __slk_F1[0].Profile)
                    {
                        var __slo_F1 = new List<Curve>();
                        foreach (Curve __slx_F1 in __slc0_F1) __slo_F1.Add(__slx_F1);
                        __slL_F1.Add(__slo_F1);
                    }
                }
                if (__slL_F1 != null)
                {
                    var __slr_F1 = new List<string>();
                    foreach (var __slc_F1 in __slL_F1)
                    {
                        var __slv_F1 = new List<long[]>();
                        foreach (Curve __slq_F1 in __slc_F1)
                        {
                            XYZ __slp_F1 = __slq_F1.GetEndPoint(0);
                            __slv_F1.Add(new long[] { __KirCanonUnit(MM(__slp_F1.X), 1.0), __KirCanonUnit(MM(__slp_F1.Y), 1.0) });
                        }
                        __slv_F1.Sort(__KirCanonCmp);
                        var __slb_F1 = new StringBuilder();
                        for (int __sli_F1 = 0; __sli_F1 < __slv_F1.Count; __sli_F1++)
                        {
                            if (__sli_F1 > 0) __slb_F1.Append('|');
                            __slb_F1.Append(__slv_F1[__sli_F1][0].ToString(System.Globalization.CultureInfo.InvariantCulture));
                            __slb_F1.Append(',');
                            __slb_F1.Append(__slv_F1[__sli_F1][1].ToString(System.Globalization.CultureInfo.InvariantCulture));
                        }
                        __slr_F1.Add(__slb_F1.ToString());
                    }
                    __slr_F1.Sort(StringComparer.Ordinal);
                    __slf_F1 = string.Join(";", __slr_F1);
                }
            }
            catch (Exception) { __slf_F1 = null; }
            if (__slf_F1 == null)
                __post.Add("F1: эскиз построенного элемента не прочитан(ы) — форма НЕ ПРОВЕРЕНА (geometry)");
            else if (__slf_F1 != "0,0|0,6000|8000,0|8000,6000")
                __post.Add("F1: sketch loops mismatch, expected 1 loop(s) (geometry)");
        }
        // post C1
        {
            var __loc = __el_C1.Location as LocationPoint;
            if (__loc == null) __post.Add("C1: нет LocationPoint");
            else if (Math.Abs(MM(__loc.Point.X) - 4000) > 5.0 || Math.Abs(MM(__loc.Point.Y) - 3000) > 5.0)
                __post.Add("C1: location mismatch (geometry)");
            if (__el_C1.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Column)
                __post.Add("C1: StructuralType mismatch (semantic)");
            Parameter __lp = __el_C1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_C1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_C1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_C1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != __el_L1.Id.ToString())
                __post.Add("C1: level binding mismatch (topology)");
        }
        // post R1
        {
            if (__el_R1.LevelId == null || __el_R1.LevelId.ToString() != __el_L1.Id.ToString())
                __post.Add("R1: level binding mismatch (topology)");
            var __loc = __el_R1.Location as LocationPoint;
            if (__loc == null || Math.Abs(MM(__loc.Point.X) - 4000) > 5.0 || Math.Abs(MM(__loc.Point.Y) - 3000) > 5.0)
                __post.Add("R1: room placement mismatch (geometry)");
            if (__el_R1.Area <= 1e-6)
                __post.Add("R1: room is not enclosed (semantic)");
            Parameter __rnm_R1 = __el_R1.get_Parameter(BuiltInParameter.ROOM_NAME);
            if (__rnm_R1 == null || __rnm_R1.AsString() != "Зал") __post.Add("R1: name mismatch");
        }
        // post T1
        {
            var __loc = __el_T1.Location as LocationPoint;
            if (__loc == null) __post.Add("T1: нет LocationPoint");
            else if (Math.Abs(MM(__loc.Point.X) - 2000) > 5.0 || Math.Abs(MM(__loc.Point.Y) - 2000) > 5.0 || Math.Abs(MM(__loc.Point.Z) - 0) > 5.0)
                __post.Add("T1: location mismatch (geometry)");
            Parameter __lp = __el_T1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_T1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_T1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_T1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != __el_L1.Id.ToString())
                __post.Add("T1: level binding mismatch (topology)");
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

// witness L1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_L1.Id.ToString(); } catch { __rb["id"] = null; }
    __rb["elevation_mm"] = Math.Round(MM(__el_L1.Elevation), 1);
    __rb["name"] = __el_L1.Name;
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_L1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    __results["L1"] = __rb;
}

// witness W1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_W1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_W1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    __rb["type_assignment"] = new Dictionary<string, object> {
        {"scope", "operation_end_before_commit"},
        {"requested_type_id", __requestedType_W1 == null ? null : __requestedType_W1.ToString()},
        {"observed_type_id", __assignedType_W1 == null ? null : __assignedType_W1.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_W1.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
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

// witness Win1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_Win1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_Win1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    try { var __stampParam = __el_Win1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_Win1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_Win1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["Win1"] = __rb;
}

// witness D1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_D1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_D1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    try { var __stampParam = __el_D1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_D1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_D1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["D1"] = __rb;
}

// witness F1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_F1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_F1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    __rb["type_assignment"] = new Dictionary<string, object> {
        {"scope", "operation_end_before_commit"},
        {"requested_type_id", __requestedType_F1 == null ? null : __requestedType_F1.ToString()},
        {"observed_type_id", __assignedType_F1 == null ? null : __assignedType_F1.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_F1.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_F1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_F1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["F1"] = __rb;
}

// witness C1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_C1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_C1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    try { var __stampParam = __el_C1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_C1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_C1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["C1"] = __rb;
}

// witness R1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_R1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_R1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    try { Parameter __rnb_R1 = __el_R1.get_Parameter(BuiltInParameter.ROOM_NAME);
        __rb["name"] = __rnb_R1 != null ? __rnb_R1.AsString() : __el_R1.Name; } catch { }
    try { Parameter __rno_rb_R1 = __el_R1.get_Parameter(BuiltInParameter.ROOM_NUMBER);
        __rb["number"] = __rno_rb_R1 != null ? __rno_rb_R1.AsString() : null; } catch { }
    try { __rb["name_and_number"] = __el_R1.Name; } catch { }
    try { __rb["area_m2"] = Math.Round(UnitUtils.ConvertFromInternalUnits(__el_R1.Area, UnitTypeId.SquareMeters), 2); } catch { }
    __results["R1"] = __rb;
}

// witness T1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_T1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_T1;
        if (__kirIdentityEl != null)
        {
            __rb["element_identity_reason"] = "identity_incomplete";
            var __kirIdentityId = __kirIdentityEl.Id;
            if (__kirIdentityId != null)
            {
                long __kirIdentityNumber = __kirIdentityId.Value;
                string __kirIdentityUid = __kirIdentityEl.UniqueId;
                if (__kirIdentityNumber > 0 && !String.IsNullOrWhiteSpace(__kirIdentityUid))
                {
                    string __kirIdentityVersion = __kirIdentityEl.VersionGuid.ToString("N");
                    __rb["element_identity"] = new Dictionary<string, object>
                    {
                        {"schema_version", "revit-element-identity/1"},
                        {"element_id", __kirIdentityNumber},
                        {"unique_id", __kirIdentityUid},
                        {"version_guid", __kirIdentityVersion}
                    };
                    __rb["element_identity_status"] = "captured";
                    __rb["element_identity_reason"] = null;
                }
            }
        }
    }
    catch
    {
        __rb["element_identity"] = null;
        __rb["element_identity_status"] = "unavailable";
        __rb["element_identity_reason"] = "identity_unreadable";
    }
    try { var __stampParam = __el_T1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_T1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_T1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["T1"] = __rb;
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