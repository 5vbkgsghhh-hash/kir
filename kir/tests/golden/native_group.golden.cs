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
Wall __el_GRP1__m__W1 = null;
ElementId __requestedType_GRP1__m__W1 = null;
ElementId __assignedType_GRP1__m__W1 = null;
Wall __el_GRP1__m__W2 = null;
ElementId __requestedType_GRP1__m__W2 = null;
ElementId __assignedType_GRP1__m__W2 = null;
Autodesk.Revit.DB.Group __grp_GRP1 = null;
Autodesk.Revit.DB.GroupType __gt_GRP1 = null;
int __placed_GRP1 = 0;
var __pgl_GRP1 = new List<Autodesk.Revit.DB.Group>();
double __gpDev_GRP1 = -1.0;
int __gpUnread_GRP1 = 0;
using (Transaction __t = new Transaction(doc, "KIR: типовой этаж как нативная группа"))
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
        // create_group GRP1 — native Revit group (2 members, 2 extra placements)
        // create_wall GRP1__m__W1
        WallType __wt_GRP1__m__W1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_GRP1__m__W1 == null) { __t.RollBack(); return __Refuse("GRP1__m__W1", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_GRP1__m__W1 = doc.GetElement(new ElementId(42));
        Level __lv_GRP1__m__W1 = __lv_raw_GRP1__m__W1 as Level;
        if (__lv_GRP1__m__W1 == null) { __t.RollBack(); return __Refuse("GRP1__m__W1", (__lv_raw_GRP1__m__W1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_GRP1__m__W1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_GRP1__m__W1 = Wall.Create(doc, Line.CreateBound(P(30000, 23000, 0), P(36000, 23000, 0)), __wt_GRP1__m__W1.Id, __lv_GRP1__m__W1.Id, U(3000.0), 0.0, false, false);
        if (__el_GRP1__m__W1 == null) { __t.RollBack(); return __Refuse("GRP1__m__W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1__m__W1"); } catch { }
        int __operationPostStart_GRP1__m__W1 = __post.Count;
        // operation GRP1__m__W1
        {
            try { __requestedType_GRP1__m__W1 = __wt_GRP1__m__W1.Id;
                __assignedType_GRP1__m__W1 = __el_GRP1__m__W1.GetTypeId(); } catch { }
            if (__requestedType_GRP1__m__W1 == null || __requestedType_GRP1__m__W1 == ElementId.InvalidElementId
                || __assignedType_GRP1__m__W1 == null || __assignedType_GRP1__m__W1 == ElementId.InvalidElementId
                || !__assignedType_GRP1__m__W1.Equals(__requestedType_GRP1__m__W1))
                __post.Add("GRP1__m__W1: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_GRP1__m__W1) { __t.RollBack(); return __Refuse("GRP1__m__W1", String.Join(" ; ", __post.Skip(__operationPostStart_GRP1__m__W1))); }

        // create_wall GRP1__m__W2
        WallType __wt_GRP1__m__W2 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_GRP1__m__W2 == null) { __t.RollBack(); return __Refuse("GRP1__m__W2", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_GRP1__m__W2 = doc.GetElement(new ElementId(42));
        Level __lv_GRP1__m__W2 = __lv_raw_GRP1__m__W2 as Level;
        if (__lv_GRP1__m__W2 == null) { __t.RollBack(); return __Refuse("GRP1__m__W2", (__lv_raw_GRP1__m__W2 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_GRP1__m__W2) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_GRP1__m__W2 = Wall.Create(doc, Line.CreateBound(P(36000, 23000, 0), P(36000, 27000, 0)), __wt_GRP1__m__W2.Id, __lv_GRP1__m__W2.Id, U(3000.0), 0.0, false, false);
        if (__el_GRP1__m__W2 == null) { __t.RollBack(); return __Refuse("GRP1__m__W2", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1__m__W2"); } catch { }
        int __operationPostStart_GRP1__m__W2 = __post.Count;
        // operation GRP1__m__W2
        {
            try { __requestedType_GRP1__m__W2 = __wt_GRP1__m__W2.Id;
                __assignedType_GRP1__m__W2 = __el_GRP1__m__W2.GetTypeId(); } catch { }
            if (__requestedType_GRP1__m__W2 == null || __requestedType_GRP1__m__W2 == ElementId.InvalidElementId
                || __assignedType_GRP1__m__W2 == null || __assignedType_GRP1__m__W2 == ElementId.InvalidElementId
                || !__assignedType_GRP1__m__W2.Equals(__requestedType_GRP1__m__W2))
                __post.Add("GRP1__m__W2: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_GRP1__m__W2) { __t.RollBack(); return __Refuse("GRP1__m__W2", String.Join(" ; ", __post.Skip(__operationPostStart_GRP1__m__W2))); }

        doc.Regenerate();
        var __members_GRP1 = new List<ElementId>();
            __members_GRP1.Add(__el_GRP1__m__W1.Id);
            __members_GRP1.Add(__el_GRP1__m__W2.Id);
        __grp_GRP1 = doc.Create.NewGroup(__members_GRP1);
        if (__grp_GRP1 == null) { __t.RollBack(); return __Refuse("GRP1", "NewGroup вернул null (члены не образуют группу)"); }
        __gt_GRP1 = __grp_GRP1.GroupType;
        if (__gt_GRP1 == null) { __t.RollBack(); return __Refuse("GRP1", "у созданной группы нет GroupType"); }
        try { __gt_GRP1.Name = "Типовой этаж"; } catch { }
        var __lp0_GRP1 = __grp_GRP1.Location as LocationPoint;
        if (__lp0_GRP1 == null) { __t.RollBack(); return __Refuse("GRP1", "у группы-определения нет LocationPoint (origin)"); }
        XYZ __o0_GRP1 = __lp0_GRP1.Point;
        XYZ __loc_GRP1_0 = new XYZ(__o0_GRP1.X + U(0.0), __o0_GRP1.Y + U(0.0), __o0_GRP1.Z + U(6600.0));
        Autodesk.Revit.DB.Group __pg_GRP1_0 = doc.Create.PlaceGroup(__loc_GRP1_0, __gt_GRP1);
        if (__pg_GRP1_0 == null) { __t.RollBack(); return __Refuse("GRP1", "PlaceGroup вернул null для смещения 0"); }
        __placed_GRP1++;
        __pgl_GRP1.Add(__pg_GRP1_0);
        try { Parameter __cm = __pg_GRP1_0.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1:0"); } catch { }
        XYZ __loc_GRP1_1 = new XYZ(__o0_GRP1.X + U(0.0), __o0_GRP1.Y + U(0.0), __o0_GRP1.Z + U(13200.0));
        Autodesk.Revit.DB.Group __pg_GRP1_1 = doc.Create.PlaceGroup(__loc_GRP1_1, __gt_GRP1);
        if (__pg_GRP1_1 == null) { __t.RollBack(); return __Refuse("GRP1", "PlaceGroup вернул null для смещения 1"); }
        __placed_GRP1++;
        __pgl_GRP1.Add(__pg_GRP1_1);
        try { Parameter __cm = __pg_GRP1_1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1:1"); } catch { }
        try { Parameter __cm = __grp_GRP1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0123c8ae:GRP1"); } catch { }

        doc.Regenerate();

        // post GRP1
        {
            if (__gt_GRP1 == null || doc.GetElement(__gt_GRP1.Id) == null)
                __post.Add("GRP1: GroupType не материализован");
            else
            {
                int __cnt_GRP1 = 0;
                foreach (Autodesk.Revit.DB.Group __g_GRP1 in __gt_GRP1.Groups) __cnt_GRP1++;
                if (__cnt_GRP1 != 3)
                    __post.Add("GRP1: число экземпляров группы не совпадает (semantic)");
            }
            if (__placed_GRP1 != 2)
                __post.Add("GRP1: размещено не все экземпляры (semantic)");
            doc.Regenerate();
            double[] __gpDX_GRP1 = new double[] {0.0, 0.0};
            double[] __gpDY_GRP1 = new double[] {0.0, 0.0};
            double[] __gpDZ_GRP1 = new double[] {6600.0, 13200.0};
            var __gpAll_GRP1 = new List<List<XYZ>>();
            for (int __gi_GRP1 = -1; __gi_GRP1 < __pgl_GRP1.Count; __gi_GRP1++)
            {
                Autodesk.Revit.DB.Group __g_GRP1 = (__gi_GRP1 < 0)
                    ? __grp_GRP1 : __pgl_GRP1[__gi_GRP1];
                double __dx_GRP1 = (__gi_GRP1 < 0) ? 0.0 : __gpDX_GRP1[__gi_GRP1];
                double __dy_GRP1 = (__gi_GRP1 < 0) ? 0.0 : __gpDY_GRP1[__gi_GRP1];
                double __dz_GRP1 = (__gi_GRP1 < 0) ? 0.0 : __gpDZ_GRP1[__gi_GRP1];
                var __sig_GRP1 = new List<XYZ>();
                if (__g_GRP1 != null)
                {
                    foreach (var __mid_GRP1 in __g_GRP1.GetMemberIds())
                    {
                        var __me_GRP1 = doc.GetElement(__mid_GRP1);
                        var __mbb_GRP1 = (__me_GRP1 == null)
                            ? null : __me_GRP1.get_BoundingBox(null);
                        if (__mbb_GRP1 == null) { __gpUnread_GRP1++; continue; }
                        __sig_GRP1.Add(new XYZ(
                            MM((__mbb_GRP1.Min.X + __mbb_GRP1.Max.X) / 2.0) - __dx_GRP1,
                            MM((__mbb_GRP1.Min.Y + __mbb_GRP1.Max.Y) / 2.0) - __dy_GRP1,
                            MM((__mbb_GRP1.Min.Z + __mbb_GRP1.Max.Z) / 2.0) - __dz_GRP1));
                    }
                }
                __gpAll_GRP1.Add(__sig_GRP1);
            }
            if (__gpUnread_GRP1 > 0)
                __post.Add("GRP1: положение членов группы не прочитано (geometry)");
            else
            {
                var __gpB_GRP1 = __gpAll_GRP1[0];
                for (int __gk_GRP1 = 1; __gk_GRP1 < __gpAll_GRP1.Count; __gk_GRP1++)
                {
                    var __gpC_GRP1 = __gpAll_GRP1[__gk_GRP1];
                    if (__gpC_GRP1.Count != __gpB_GRP1.Count)
                    {
                        __post.Add("GRP1: состав размещения не равен определению (geometry)");
                        break;
                    }
                    for (int __gj_GRP1 = 0; __gj_GRP1 < __gpB_GRP1.Count; __gj_GRP1++)
                    {
                        double __best_GRP1 = double.MaxValue;
                        for (int __gm_GRP1 = 0; __gm_GRP1 < __gpC_GRP1.Count; __gm_GRP1++)
                        {
                            double __dd_GRP1 = Math.Max(
                                Math.Abs(__gpC_GRP1[__gm_GRP1].X - __gpB_GRP1[__gj_GRP1].X),
                                Math.Max(
                                    Math.Abs(__gpC_GRP1[__gm_GRP1].Y - __gpB_GRP1[__gj_GRP1].Y),
                                    Math.Abs(__gpC_GRP1[__gm_GRP1].Z - __gpB_GRP1[__gj_GRP1].Z)));
                            if (__dd_GRP1 < __best_GRP1) __best_GRP1 = __dd_GRP1;
                        }
                        if (__best_GRP1 > __gpDev_GRP1) __gpDev_GRP1 = __best_GRP1;
                    }
                }
                if (__gpDev_GRP1 > 1000.0)
                    __post.Add("GRP1: члены размещения стоят не там, где определение плюс смещение (geometry)");
            }
            if (__gt_GRP1.Name != "Типовой этаж")
                __post.Add("GRP1: имя GroupType не совпадает (semantic)");
            // post GRP1__m__W1
            {
                var __lc = __el_GRP1__m__W1.Location as LocationCurve;
                if (__lc == null) __post.Add("GRP1__m__W1: нет LocationCurve");
                else
                {
                    var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                    double __da = Math.Pow(MM(__a.X) - 30000, 2) + Math.Pow(MM(__a.Y) - 23000, 2);
                    double __db = Math.Pow(MM(__b.X) - 30000, 2) + Math.Pow(MM(__b.Y) - 23000, 2);
                    var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                    if (Math.Abs(MM(__e0.X) - 30000) > 5.0 || Math.Abs(MM(__e0.Y) - 23000) > 5.0 ||
                        Math.Abs(MM(__e1.X) - 36000) > 5.0 || Math.Abs(MM(__e1.Y) - 23000) > 5.0)
                        __post.Add("GRP1__m__W1: endpoints mismatch (geometry)");
                }
                var __bp = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
                if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                    __post.Add("GRP1__m__W1: level binding mismatch (topology)");
                var __hp = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
                if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                    __post.Add("GRP1__m__W1: height mismatch");
            }
            // post GRP1__m__W2
            {
                var __lc = __el_GRP1__m__W2.Location as LocationCurve;
                if (__lc == null) __post.Add("GRP1__m__W2: нет LocationCurve");
                else
                {
                    var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                    double __da = Math.Pow(MM(__a.X) - 36000, 2) + Math.Pow(MM(__a.Y) - 23000, 2);
                    double __db = Math.Pow(MM(__b.X) - 36000, 2) + Math.Pow(MM(__b.Y) - 23000, 2);
                    var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                    if (Math.Abs(MM(__e0.X) - 36000) > 5.0 || Math.Abs(MM(__e0.Y) - 23000) > 5.0 ||
                        Math.Abs(MM(__e1.X) - 36000) > 5.0 || Math.Abs(MM(__e1.Y) - 27000) > 5.0)
                        __post.Add("GRP1__m__W2: endpoints mismatch (geometry)");
                }
                var __bp = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
                if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                    __post.Add("GRP1__m__W2: level binding mismatch (topology)");
                var __hp = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
                if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                    __post.Add("GRP1__m__W2: height mismatch");
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

// witness GRP1__m__W1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_GRP1__m__W1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_GRP1__m__W1;
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
        {"requested_type_id", __requestedType_GRP1__m__W1 == null ? null : __requestedType_GRP1__m__W1.ToString()},
        {"observed_type_id", __assignedType_GRP1__m__W1 == null ? null : __assignedType_GRP1__m__W1.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_GRP1__m__W1.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_GRP1__m__W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_GRP1__m__W1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_GRP1__m__W1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["GRP1__m__W1"] = __rb;
}

// witness GRP1__m__W2
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_GRP1__m__W2.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_GRP1__m__W2;
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
        {"requested_type_id", __requestedType_GRP1__m__W2 == null ? null : __requestedType_GRP1__m__W2.ToString()},
        {"observed_type_id", __assignedType_GRP1__m__W2 == null ? null : __assignedType_GRP1__m__W2.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_GRP1__m__W2.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_GRP1__m__W2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_GRP1__m__W2.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_GRP1__m__W2.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["GRP1__m__W2"] = __rb;
}

// witness GRP1
{
    var __rb_GRP1 = new Dictionary<string, object>();
    try { if (__grp_GRP1 != null) __rb_GRP1["id"] = __grp_GRP1.Id.ToString(); } catch { }
    try { if (__gt_GRP1 != null) { __rb_GRP1["group_type_id"] = __gt_GRP1.Id.ToString();
        __rb_GRP1["group_type_name"] = __gt_GRP1.Name; } } catch { }
    __rb_GRP1["member_count"] = 2;
    __rb_GRP1["placed_count"] = __placed_GRP1;
    __rb_GRP1["instance_count"] = 3;
    __rb_GRP1["member_offset_max_mm"] = __gpDev_GRP1;
    __rb_GRP1["member_offset_tol_mm"] = 1000.0;
    __rb_GRP1["members_unreadable"] = __gpUnread_GRP1;
    __rb_GRP1["coincident_instances"] = 0;
    __results["GRP1"] = __rb_GRP1;
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