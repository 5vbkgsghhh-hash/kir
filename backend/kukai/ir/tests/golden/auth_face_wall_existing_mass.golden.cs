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
FaceWall __el_FW1 = null;
WallType __ty_FW1 = null;
Element __hsrc_FW1 = null;
Reference __fr_FW1 = null;
XYZ __want_FW1 = null;
double __farea_FW1 = 0.0;
double __warea_FW1 = 0.0;
double __wwid_FW1 = 0.0;
double __wtol_FW1 = 0.0;
int __wfn_FW1 = 0;
bool __inbb_FW1 = false;
void __faceKeep_FW1(Element __fkEl, IList<Reference> __fkSrc, XYZ __fkWant,
    List<Reference> __fkOut)
{
    if (__fkSrc == null) return;
    foreach (Reference __fkR in __fkSrc)
    {
        if (__fkR == null) continue;
        if (__fkWant == null) { __fkOut.Add(__fkR); continue; }
        PlanarFace __fkPf = null;
        try { __fkPf = __fkEl.GetGeometryObjectFromReference(__fkR) as PlanarFace; }
        catch { }
        if (__fkPf == null) continue;
        XYZ __fkN = __fkPf.FaceNormal;
        if (__fkN.IsZeroLength()) continue;
        __fkN = __fkN.Normalize();
        if (!__fkN.CrossProduct(__fkWant).IsZeroLength()) continue;
        if (__fkN.DotProduct(__fkWant) <= 0) continue;
        __fkOut.Add(__fkR);
    }
}
void __faceWalk_FW1(GeometryElement __fwGe, Transform __fwTf, XYZ __fwWant,
    List<Reference> __fwOut)
{
    if (__fwGe == null) return;
    foreach (GeometryObject __fwGo in __fwGe)
    {
        Solid __fwSol = __fwGo as Solid;
        if (__fwSol != null)
        {
            foreach (Face __fwFc in __fwSol.Faces)
            {
                PlanarFace __fwPf = __fwFc as PlanarFace;
                if (__fwPf == null || __fwPf.Reference == null) continue;
                XYZ __fwN = __fwTf.OfVector(__fwPf.FaceNormal);
                if (__fwN.IsZeroLength()) continue;
                __fwN = __fwN.Normalize();
                if (__fwWant != null && !__fwN.CrossProduct(__fwWant).IsZeroLength()) continue;
                if (__fwWant != null && __fwN.DotProduct(__fwWant) <= 0) continue;
                __fwOut.Add(__fwPf.Reference);
            }
            continue;
        }
        GeometryInstance __fwGi = __fwGo as GeometryInstance;
        if (__fwGi != null)
            __faceWalk_FW1(__fwGi.GetSymbolGeometry(), __fwTf.Multiply(__fwGi.Transform),
                __fwWant, __fwOut);
    }
}
using (Transaction __t = new Transaction(doc, "KIR: стена по скату существующей массы"))
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
        // create_face_wall FW1
        __hsrc_FW1 = doc.GetElement(new ElementId(900001));
        if (__hsrc_FW1 == null) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: носитель не найден (модель изменилась после grounding)"); }
        __ty_FW1 = doc.GetElement(new ElementId(100)) as WallType;
        if (__ty_FW1 == null) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: тип не найден или он не WallType (модель изменилась после grounding)"); }
        bool __tyok_FW1 = false;
        try { __tyok_FW1 = FaceWall.IsWallTypeValidForFaceWall(doc, __ty_FW1.Id); } catch { }
        if (!__tyok_FW1) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: Revit не принимает этот тип стены по грани (" + __ty_FW1.Name + "). Правило целиком Autodesk нигде не перечислил, поэтому спрошен сам Revit (IsWallTypeValidForFaceWall) — и он ответил «нет» ДО эффекта, а не исключением после. СЛЕДУЮЩИЙ ХОД: назови другой тип стены; query_types kind=wall_types покажет пул"); }
        List<Reference> __fc_FW1_0 = new List<Reference>();
        XYZ __fw_FW1_0 = new XYZ(0.6, 0.0, 0.8);
        if (__fw_FW1_0.IsZeroLength()) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: face_normal: face_normal — вырожденный вектор (Revit считает его нулевым). СЛЕДУЮЩИЙ ХОД: задай направление нормали ненулевым вектором"); }
        __fw_FW1_0 = __fw_FW1_0.Normalize();
        Options __fo_FW1_0 = new Options();
        __fo_FW1_0.ComputeReferences = true;
        __fo_FW1_0.IncludeNonVisibleObjects = true;
        GeometryElement __fg_FW1_0 = null;
        try { __fg_FW1_0 = __hsrc_FW1.get_Geometry(__fo_FW1_0); } catch { }
        __faceWalk_FW1(__fg_FW1_0, Transform.Identity, __fw_FW1_0, __fc_FW1_0);
        if (__fc_FW1_0.Count == 0) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: face_normal: у элемента нет грани, отвечающей описанию (нормаль [0.6, 0, 0.8]). Описание ТОЧНОЕ: грань берётся, только если её нормаль строго параллельна и сонаправлена заданной (проверка родным XYZ.IsZeroLength на векторном произведении) — «почти параллельна» не считается, потому что углового допуска никто не мерил. СЛЕДУЮЩИЙ ХОД: проверь face_normal — это внешняя нормаль грани в координатах МОДЕЛИ. И помни правило самого Revit: стену по грани он строит ТОЛЬКО по наклонной грани массы, то есть у вертикальной ([0,0,±1]) и горизонтальной (z == 0) нормали кандидата не будет никогда"); }
        if (__fc_FW1_0.Count > 1) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: face_normal: описанию (нормаль [0.6, 0, 0.8]) отвечает не одна грань, а " + __fc_FW1_0.Count.ToString() + ". Компилятор НЕ выбирает за автора: порядок граней в теле не документирован, поэтому «первая подходящая» — число без смысла. СЛЕДУЮЩИЙ ХОД: у этой массы несколько РАЗНЫХ граней с одной и той же нормалью (параллельные скаты), и выбрать из них за автора нельзя. Это НАЗВАННЫЙ предел операции: сегодня одна нормаль — один скат. Строй стену по массе, у которой скат с таким направлением один"); }
        __fr_FW1 = __fc_FW1_0[0];
        PlanarFace __mf_FW1 = null;
        try { __mf_FW1 = __hsrc_FW1.GetGeometryObjectFromReference(__fr_FW1) as PlanarFace; } catch { }
        if (__mf_FW1 != null) __farea_FW1 = __mf_FW1.Area;
        bool __frok_FW1 = false;
        try { __frok_FW1 = FaceWall.IsValidFaceReferenceForFaceWall(doc, __fr_FW1); } catch { }
        if (!__frok_FW1) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: Revit не принимает эту грань как основание для стены по грани. Его собственное правило (IsValidFaceReferenceForFaceWall, спрошен ДО эффекта): грань обязана принадлежать МАССЕ, быть ПЛОСКОЙ, и её нормаль не должна быть ни вертикальной, ни горизонтальной — то есть стену по грани строят по НАКЛОННОЙ поверхности. СЛЕДУЮЩИЙ ХОД: для вертикальной грани строй create_wall, для горизонтальной — перекрытие или кровлю (пола и кровли ПО ГРАНИ в API нет вовсе, замерено 6/6 CS1061)"); }
        try { __el_FW1 = FaceWall.Create(doc, __ty_FW1.Id, WallLocationLine.CoreExterior, __fr_FW1); }
        catch (Exception __ex_FW1) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: FaceWall.Create отказал — " + __ex_FW1.Message); }
        if (__el_FW1 == null) { __t.RollBack(); return __Refuse("FW1", "стена по грани массы: создание вернуло null — Revit не принял эту грань, хотя предполётная проверка её пропустила"); }
        try { Parameter __cm = __el_FW1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:e240c419:FW1"); } catch { }

        doc.Regenerate();

        // post FW1
        {
            ElementId __rt_FW1 = __el_FW1.GetTypeId();
            if (__rt_FW1 == null || __ty_FW1 == null
                || __rt_FW1.ToString() != __ty_FW1.Id.ToString())
                __post.Add("FW1: тип построенной стены по грани не равен запрошенному (topology)");
            __want_FW1 = new XYZ(0.6, 0.0, 0.8);
            if (!__want_FW1.IsZeroLength()) __want_FW1 = __want_FW1.Normalize();
            IList<Reference> __wsf_FW1 = null;
            try { __wsf_FW1 = HostObjectUtils.GetSideFaces(__el_FW1, ShellLayerType.Exterior); } catch { }
            BoundingBoxXYZ __hbb_FW1 = null;
            try { __hbb_FW1 = __hsrc_FW1.get_BoundingBox(null); } catch { }
            try { __wwid_FW1 = __ty_FW1.Width; } catch { }
            try { __wtol_FW1 = doc.Application.VertexTolerance; } catch { }
            double __grow_FW1 = __wwid_FW1 + __wtol_FW1;
            if (__wsf_FW1 != null)
                foreach (Reference __wr_FW1 in __wsf_FW1)
                {
                    PlanarFace __wp_FW1 = null;
                    try { __wp_FW1 = __el_FW1.GetGeometryObjectFromReference(__wr_FW1) as PlanarFace; } catch { }
                    if (__wp_FW1 == null) continue;
                    XYZ __wn_FW1 = __wp_FW1.FaceNormal;
                    if (__wn_FW1.IsZeroLength()) continue;
                    __wn_FW1 = __wn_FW1.Normalize();
                    if (!__wn_FW1.CrossProduct(__want_FW1).IsZeroLength()) continue;
                    if (__wn_FW1.DotProduct(__want_FW1) <= 0) continue;
                    __wfn_FW1++;
                    __warea_FW1 = __wp_FW1.Area;
                    XYZ __wo_FW1 = __wp_FW1.Origin;
                    if (__hbb_FW1 != null && __wo_FW1 != null
                        && __wo_FW1.X >= __hbb_FW1.Min.X - __grow_FW1
                        && __wo_FW1.X <= __hbb_FW1.Max.X + __grow_FW1
                        && __wo_FW1.Y >= __hbb_FW1.Min.Y - __grow_FW1
                        && __wo_FW1.Y <= __hbb_FW1.Max.Y + __grow_FW1
                        && __wo_FW1.Z >= __hbb_FW1.Min.Z - __grow_FW1
                        && __wo_FW1.Z <= __hbb_FW1.Max.Z + __grow_FW1)
                        __inbb_FW1 = true;
                }
            if (__wfn_FW1 != 1)
                __post.Add(__wfn_FW1.ToString() + " "
                    + "FW1: наружных граней построенной стены сонаправлены названной грани массы, а должна быть ровно одна (geometry)");
            if (!__inbb_FW1)
                __post.Add("FW1: наружная грань построенной стены лежит вне габарита носителя, расширенного на её собственную толщину (geometry)");
            if (!(__warea_FW1 > 0.0))
                __post.Add("FW1: площадь наружной грани построенного тела не больше нуля — не построено ничего (geometry)");
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

// witness FW1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_FW1.Id.ToString();
    __rb["location_line"] = "core_exterior";
    __rb["exterior_faces_codirectional"] = __wfn_FW1;
    __rb["within_host_bbox"] = __inbb_FW1;
    __rb["wall_width_mm"] = MM(__wwid_FW1);
    __rb["vertex_tolerance_mm"] = MM(__wtol_FW1);
    __rb["named_face_area_mm2"] = MM(MM(__farea_FW1));
    __rb["built_face_area_mm2"] = MM(MM(__warea_FW1));
    try { var __stampParam = __el_FW1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { if (__ty_FW1 != null && __ty_FW1.Name != null) __rb["type_name"] = __ty_FW1.Name; } catch { }
    __results["FW1"] = __rb;
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