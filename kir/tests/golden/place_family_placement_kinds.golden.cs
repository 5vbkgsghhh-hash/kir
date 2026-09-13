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
Wall __el_PW = null;
ElementId __requestedType_PW = null;
ElementId __assignedType_PW = null;
Level __el_PL = null;
FamilyInstance __el_PP = null;
Element __pfh_PP = null;
FamilyInstance __el_PT = null;
using (Transaction __t = new Transaction(doc, "KIR: прибор на рабочей плоскости и стойка между уровнями"))
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
        // create_wall PW
        WallType __wt_PW = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_PW == null) { __t.RollBack(); return __Refuse("PW", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_PW = doc.GetElement(new ElementId(42));
        Level __lv_PW = __lv_raw_PW as Level;
        if (__lv_PW == null) { __t.RollBack(); return __Refuse("PW", (__lv_raw_PW == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_PW) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_PW = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(8000, 0, 0)), __wt_PW.Id, __lv_PW.Id, U(3000.0), 0.0, false, false);
        if (__el_PW == null) { __t.RollBack(); return __Refuse("PW", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_PW.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7321b609:PW"); } catch { }
        int __operationPostStart_PW = __post.Count;
        // operation PW
        {
            try { __requestedType_PW = __wt_PW.Id;
                __assignedType_PW = __el_PW.GetTypeId(); } catch { }
            if (__requestedType_PW == null || __requestedType_PW == ElementId.InvalidElementId
                || __assignedType_PW == null || __assignedType_PW == ElementId.InvalidElementId
                || !__assignedType_PW.Equals(__requestedType_PW))
                __post.Add("PW: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_PW) { __t.RollBack(); return __Refuse("PW", String.Join(" ; ", __post.Skip(__operationPostStart_PW))); }


        // create_level PL
        __el_PL = Level.Create(doc, U(6000.0));
        if (__el_PL == null) { __t.RollBack(); return __Refuse("PL", "Level.Create вернул null"); }
        try { __el_PL.Name = "КИР-Р"; }
        catch (Exception __ex_PL) { __t.RollBack(); return __Refuse("PL", "имя уровня: " + __ex_PL.Message); }
        try { Parameter __cm = __el_PL.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7321b609:PL"); } catch { }

        // place_family (рабочая плоскость) PP
        FamilySymbol __sy_PP = doc.GetElement(new ElementId(800)) as FamilySymbol;
        if (__sy_PP == null) { __t.RollBack(); return __Refuse("PP", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_PP.IsActive) { __sy_PP.Activate(); doc.Regenerate(); }
        __pfh_PP = __el_PW;
        if (__pfh_PP == null) { __t.RollBack(); return __Refuse("PP", "хост не найден"); }
        if (__sy_PP.Family == null || __sy_PP.Family.FamilyPlacementType != FamilyPlacementType.WorkPlaneBased)
        { __t.RollBack(); return __Refuse("PP", "place_family на рабочей плоскости: у семейства род размещения " + (__sy_PP.Family == null ? "неизвестен" : __sy_PP.Family.FamilyPlacementType.ToString()) + ", а не WorkPlaneBased — выберите другой тип или ставьте точкой"); }
        XYZ __pfp_PP = new XYZ(U(4000), U(0), U(1200));
        XYZ __pfd_PP = new XYZ(1.0, 0.0, 0.0);
        if (__pfd_PP.IsZeroLength()) { __t.RollBack(); return __Refuse("PP", "ref_dir нулевой длины: направление отсчёта не задано"); }
        try { __el_PP = doc.Create.NewFamilyInstance(__pfp_PP, __sy_PP, __pfd_PP, __pfh_PP, Autodesk.Revit.DB.Structure.StructuralType.NonStructural); }
        catch (Exception __ex_PP) { __t.RollBack(); return __Refuse("PP", "NewFamilyInstance: " + __ex_PP.Message); }
        if (__el_PP == null) { __t.RollBack(); return __Refuse("PP", "NewFamilyInstance вернул null"); }
        try { Parameter __cm = __el_PP.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7321b609:PP"); } catch { }

        // place_family PT
        FamilySymbol __sy_PT = doc.GetElement(new ElementId(800)) as FamilySymbol;
        if (__sy_PT == null) { __t.RollBack(); return __Refuse("PT", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_PT.IsActive) { __sy_PT.Activate(); doc.Regenerate(); }
        Element __lv_raw_PT = doc.GetElement(new ElementId(42));
        Level __lv_PT = __lv_raw_PT as Level;
        if (__lv_PT == null) { __t.RollBack(); return __Refuse("PT", (__lv_raw_PT == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_PT) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        XYZ __pfp_PT = new XYZ(U(2000), U(2000), U(0) - __lv_PT.Elevation);
        __el_PT = doc.Create.NewFamilyInstance(__pfp_PT, __sy_PT, __lv_PT, Autodesk.Revit.DB.Structure.StructuralType.NonStructural);
        if (__el_PT == null) { __t.RollBack(); return __Refuse("PT", "NewFamilyInstance вернул null"); }
        Parameter __ptl_PT = __el_PT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
        if (__ptl_PT == null || __ptl_PT.IsReadOnly)
        { __t.RollBack(); return __Refuse("PT", "place_family: у семейства нет записываемого верхнего " + "уровня (род размещения " + (__sy_PT.Family == null ? "неизвестен" : __sy_PT.Family.FamilyPlacementType.ToString()) + "), а top_level задан"); }
        if (!__ptl_PT.Set(__el_PL.Id)) { __t.RollBack(); return __Refuse("PT", "запись верхнего уровня отклонена Revit"); }
        Parameter __pbo_PT = __el_PT.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);
        if (__pbo_PT == null || __pbo_PT.IsReadOnly) { __t.RollBack(); return __Refuse("PT", "base_offset_mm недоступен для записи у этого семейства"); }
        if (!__pbo_PT.Set(U(100.0))) { __t.RollBack(); return __Refuse("PT", "запись base_offset_mm отклонена Revit"); }
        Parameter __pto_PT = __el_PT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);
        if (__pto_PT == null || __pto_PT.IsReadOnly) { __t.RollBack(); return __Refuse("PT", "top_offset_mm недоступен для записи у этого семейства"); }
        if (!__pto_PT.Set(U(-250.0))) { __t.RollBack(); return __Refuse("PT", "запись top_offset_mm отклонена Revit"); }
        try { Parameter __cm = __el_PT.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7321b609:PT"); } catch { }

        doc.Regenerate();

        // post PW
        {
            var __lc = __el_PW.Location as LocationCurve;
            if (__lc == null) __post.Add("PW: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 8000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("PW: endpoints mismatch (geometry)");
            }
            var __bp = __el_PW.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("PW: level binding mismatch (topology)");
            var __hp = __el_PW.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("PW: height mismatch");
        }
        // post PL
        {
            if (Math.Abs(MM(__el_PL.Elevation) - 6000.0) > 1.0)
                __post.Add("PL: elevation mismatch (geometry)");
            if (__el_PL.Name != "КИР-Р") __post.Add("PL: name mismatch");
        }
        // post PP
        {
            var __wloc_PP = __el_PP.Location as LocationPoint;
            if (__wloc_PP == null
                || Math.Abs(MM(__wloc_PP.Point.X) - 4000) > 5.0
                || Math.Abs(MM(__wloc_PP.Point.Y) - 0) > 5.0
                || Math.Abs(MM(__wloc_PP.Point.Z) - 1200) > 5.0)
                __post.Add("PP: location mismatch (geometry)");
            if (__el_PP.Host == null || __el_PP.Host.Id.ToString() != __pfh_PP.Id.ToString())
                __post.Add("PP: host mismatch (topology)");
            XYZ __wdir_PP = null;
            try { __wdir_PP = __el_PP.HandOrientation; } catch { }
            XYZ __wwant_PP = new XYZ(1.0, 0.0, 0.0);
            if (__wdir_PP == null || __wdir_PP.IsZeroLength())
                __post.Add("PP: reference direction unreadable (geometry)");
            else
            {
                double __wang_PP = __wdir_PP.AngleTo(__wwant_PP);
                if (Math.Min(__wang_PP, Math.PI - __wang_PP) > Math.PI / 1800.0)
                    __post.Add("PP: reference direction mismatch (geometry)");
            }
            Parameter __lp = __el_PP.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_PP.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_PP.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_PP.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("PP: level binding mismatch (topology)");
        }
        // post PT
        {
            var __loc = __el_PT.Location as LocationPoint;
            if (__loc == null) __post.Add("PT: нет LocationPoint");
            else if (Math.Abs(MM(__loc.Point.X) - 2000) > 5.0 || Math.Abs(MM(__loc.Point.Y) - 2000) > 5.0 || Math.Abs(MM(__loc.Point.Z) - 0) > 5.0)
                __post.Add("PT: location mismatch (geometry)");
            Parameter __rtl_PT = __el_PT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
            if (__rtl_PT == null
                || __rtl_PT.AsElementId() == ElementId.InvalidElementId
                || __rtl_PT.AsElementId().ToString() != __el_PL.Id.ToString())
                __post.Add("PT: top level binding mismatch (topology)");
            Parameter __rbo_PT = __el_PT.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);
            if (__rbo_PT == null
                || Math.Abs(MM(__rbo_PT.AsDouble()) - 100.0) > 1.0)
                __post.Add("PT: base_offset_mm mismatch (semantic)");
            Parameter __rto_PT = __el_PT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);
            if (__rto_PT == null
                || Math.Abs(MM(__rto_PT.AsDouble()) - -250.0) > 1.0)
                __post.Add("PT: top_offset_mm mismatch (semantic)");
            Parameter __lp = __el_PT.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_PT.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_PT.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_PT.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("PT: level binding mismatch (topology)");
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

// witness PW
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_PW.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_PW;
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
        {"requested_type_id", __requestedType_PW == null ? null : __requestedType_PW.ToString()},
        {"observed_type_id", __assignedType_PW == null ? null : __assignedType_PW.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_PW.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_PW.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_PW.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_PW.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["PW"] = __rb;
}

// witness PL
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_PL.Id.ToString(); } catch { __rb["id"] = null; }
    __rb["elevation_mm"] = Math.Round(MM(__el_PL.Elevation), 1);
    __rb["name"] = __el_PL.Name;
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_PL;
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
    __results["PL"] = __rb;
}

// witness PP
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_PP.Id.ToString();
    try { var __wl_PP = __el_PP.Location as LocationPoint;
        if (__wl_PP != null) __rb["xyz_mm"] = new double[] { Math.Round(MM(__wl_PP.Point.X), 1), Math.Round(MM(__wl_PP.Point.Y), 1), Math.Round(MM(__wl_PP.Point.Z), 1) }; } catch { }
    try { if (__el_PP.Host != null) __rb["host_id"] = __el_PP.Host.Id.ToString(); } catch { }
    try { var __wo_PP = __el_PP.HandOrientation;
        if (__wo_PP != null) __rb["hand_orientation"] = new double[] { Math.Round(__wo_PP.X, 4), Math.Round(__wo_PP.Y, 4), Math.Round(__wo_PP.Z, 4) }; } catch { }
    try { __rb["placement_type"] = __el_PP.Symbol.Family.FamilyPlacementType.ToString(); } catch { }
    try { var __stampParam = __el_PP.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["PP"] = __rb;
}

// witness PT
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_PT.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_PT;
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
    try { var __stampParam = __el_PT.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_PT.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_PT.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["PT"] = __rb;
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