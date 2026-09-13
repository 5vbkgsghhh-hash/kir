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
Wall __el_MW = null;
ElementId __requestedType_MW = null;
ElementId __assignedType_MW = null;
Autodesk.Revit.DB.Plumbing.Pipe __el_MP = null;
List<ElementId> __mtIds_ME1 = new List<ElementId>();
List<Element> __mtEls_ME1 = new List<Element>();
List<XYZ> __mtBeforePt_ME1 = new List<XYZ>();
List<XYZ> __mtBefore0_ME1 = new List<XYZ>();
List<XYZ> __mtBefore1_ME1 = new List<XYZ>();
List<List<string>> __mtInsBefore_ME1 = new List<List<string>>();
List<List<string>> __mtJoinBefore_ME1 = new List<List<string>>();
List<ElementId> __mtLockedDims_ME1 = new List<ElementId>();
bool __mtJoinRead_ME1 = true;
int __mtDimsSeen_ME1 = 0;
int __mtDimsMulti_ME1 = 0;
int __mtConnBefore_ME1 = 0;
Element __tg_CT1 = null;
ElementType __ty_CT1 = null;
ElementId __chid_CT1 = null;
Element __el_CT1 = null;
ElementId __requestedType_CT1 = null;
ElementId __assignedType_CT1 = null;
using (Transaction __t = new Transaction(doc, "KIR: перенос связки стена+труба, смена типа стены"))
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
        // create_wall MW
        WallType __wt_MW = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_MW == null) { __t.RollBack(); return __Refuse("MW", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_MW = doc.GetElement(new ElementId(42));
        Level __lv_MW = __lv_raw_MW as Level;
        if (__lv_MW == null) { __t.RollBack(); return __Refuse("MW", (__lv_raw_MW == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_MW) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_MW = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_MW.Id, __lv_MW.Id, U(3000.0), 0.0, false, false);
        if (__el_MW == null) { __t.RollBack(); return __Refuse("MW", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_MW.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:ebdab994:MW"); } catch { }
        int __operationPostStart_MW = __post.Count;
        // operation MW
        {
            try { __requestedType_MW = __wt_MW.Id;
                __assignedType_MW = __el_MW.GetTypeId(); } catch { }
            if (__requestedType_MW == null || __requestedType_MW == ElementId.InvalidElementId
                || __assignedType_MW == null || __assignedType_MW == ElementId.InvalidElementId
                || !__assignedType_MW.Equals(__requestedType_MW))
                __post.Add("MW: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_MW) { __t.RollBack(); return __Refuse("MW", String.Join(" ; ", __post.Skip(__operationPostStart_MW))); }


        // create_pipe MP
        Element __lv_raw_MP = doc.GetElement(new ElementId(42));
        Level __lv_MP = __lv_raw_MP as Level;
        if (__lv_MP == null) { __t.RollBack(); return __Refuse("MP", (__lv_raw_MP == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_MP) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_MP = Autodesk.Revit.DB.Plumbing.Pipe.Create(doc, new ElementId(300), new ElementId(200), __lv_MP.Id, P(0, 0, 2700), P(3000, 0, 2900));
        if (__el_MP == null) { __t.RollBack(); return __Refuse("MP", "Pipe.Create вернул null"); }
        try { Parameter __dp_MP = __el_MP.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM); if (__dp_MP != null && !__dp_MP.IsReadOnly) __dp_MP.Set(U(50.0)); } catch { }
        try { Parameter __cm = __el_MP.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:ebdab994:MP"); } catch { }

        // move_elements ME1
        doc.Regenerate();
        {
            Element __mte_ME1 = (Element)__el_MW;
            if (__mte_ME1.Pinned) { __t.RollBack(); return __Refuse("ME1", "targets[0]: элемент закреплён (Pinned) — перенос невозможен"); }
            __mtIds_ME1.Add(__mte_ME1.Id);
            __mtEls_ME1.Add(__mte_ME1);
            var __mtlp_ME1 = __mte_ME1.Location as LocationPoint;
            var __mtlc_ME1 = __mte_ME1.Location as LocationCurve;
            __mtBeforePt_ME1.Add(__mtlp_ME1 != null ? __mtlp_ME1.Point : null);
            __mtBefore0_ME1.Add(__mtlc_ME1 != null ? __mtlc_ME1.Curve.GetEndPoint(0) : null);
            __mtBefore1_ME1.Add(__mtlc_ME1 != null ? __mtlc_ME1.Curve.GetEndPoint(1) : null);
            ConnectorManager __mtcm_ME1 = null;
            MEPCurve __mtmc_ME1 = __mte_ME1 as MEPCurve;
            FamilyInstance __mtfi_ME1 = __mte_ME1 as FamilyInstance;
            if (__mtmc_ME1 != null) __mtcm_ME1 = __mtmc_ME1.ConnectorManager;
            else if (__mtfi_ME1 != null && __mtfi_ME1.MEPModel != null) __mtcm_ME1 = __mtfi_ME1.MEPModel.ConnectorManager;
            if (__mtcm_ME1 != null)
                foreach (Connector __mtc_ME1 in __mtcm_ME1.Connectors)
                    if (__mtc_ME1.IsConnected) __mtConnBefore_ME1++;
            var __mtins_ME1 = new List<string>();
            HostObject __mtho_ME1 = __mte_ME1 as HostObject;
            if (__mtho_ME1 != null)
                foreach (ElementId __mtii_ME1 in __mtho_ME1.FindInserts(true, true, false, false))
                    __mtins_ME1.Add(__mtii_ME1.ToString());
            __mtInsBefore_ME1.Add(__mtins_ME1);
            var __mtjn_ME1 = new List<string>();
            try { foreach (ElementId __mtji_ME1 in JoinGeometryUtils.GetJoinedElements(doc, __mte_ME1)) __mtjn_ME1.Add(__mtji_ME1.ToString()); }
            catch { __mtJoinRead_ME1 = false; }
            __mtJoinBefore_ME1.Add(__mtjn_ME1);
            foreach (ElementId __mtdi_ME1 in __mte_ME1.GetDependentElements(new ElementClassFilter(typeof(Dimension))))
            {
                Dimension __mtd_ME1 = doc.GetElement(__mtdi_ME1) as Dimension;
                if (__mtd_ME1 == null) continue;
                __mtDimsSeen_ME1++;
                if (__mtd_ME1.NumberOfSegments > 1) { __mtDimsMulti_ME1++; continue; }
                if (__mtd_ME1.IsLocked) __mtLockedDims_ME1.Add(__mtdi_ME1);
            }
        }
        {
            Element __mte_ME1 = (Element)__el_MP;
            if (__mte_ME1.Pinned) { __t.RollBack(); return __Refuse("ME1", "targets[1]: элемент закреплён (Pinned) — перенос невозможен"); }
            __mtIds_ME1.Add(__mte_ME1.Id);
            __mtEls_ME1.Add(__mte_ME1);
            var __mtlp_ME1 = __mte_ME1.Location as LocationPoint;
            var __mtlc_ME1 = __mte_ME1.Location as LocationCurve;
            __mtBeforePt_ME1.Add(__mtlp_ME1 != null ? __mtlp_ME1.Point : null);
            __mtBefore0_ME1.Add(__mtlc_ME1 != null ? __mtlc_ME1.Curve.GetEndPoint(0) : null);
            __mtBefore1_ME1.Add(__mtlc_ME1 != null ? __mtlc_ME1.Curve.GetEndPoint(1) : null);
            ConnectorManager __mtcm_ME1 = null;
            MEPCurve __mtmc_ME1 = __mte_ME1 as MEPCurve;
            FamilyInstance __mtfi_ME1 = __mte_ME1 as FamilyInstance;
            if (__mtmc_ME1 != null) __mtcm_ME1 = __mtmc_ME1.ConnectorManager;
            else if (__mtfi_ME1 != null && __mtfi_ME1.MEPModel != null) __mtcm_ME1 = __mtfi_ME1.MEPModel.ConnectorManager;
            if (__mtcm_ME1 != null)
                foreach (Connector __mtc_ME1 in __mtcm_ME1.Connectors)
                    if (__mtc_ME1.IsConnected) __mtConnBefore_ME1++;
            var __mtins_ME1 = new List<string>();
            HostObject __mtho_ME1 = __mte_ME1 as HostObject;
            if (__mtho_ME1 != null)
                foreach (ElementId __mtii_ME1 in __mtho_ME1.FindInserts(true, true, false, false))
                    __mtins_ME1.Add(__mtii_ME1.ToString());
            __mtInsBefore_ME1.Add(__mtins_ME1);
            var __mtjn_ME1 = new List<string>();
            try { foreach (ElementId __mtji_ME1 in JoinGeometryUtils.GetJoinedElements(doc, __mte_ME1)) __mtjn_ME1.Add(__mtji_ME1.ToString()); }
            catch { __mtJoinRead_ME1 = false; }
            __mtJoinBefore_ME1.Add(__mtjn_ME1);
            foreach (ElementId __mtdi_ME1 in __mte_ME1.GetDependentElements(new ElementClassFilter(typeof(Dimension))))
            {
                Dimension __mtd_ME1 = doc.GetElement(__mtdi_ME1) as Dimension;
                if (__mtd_ME1 == null) continue;
                __mtDimsSeen_ME1++;
                if (__mtd_ME1.NumberOfSegments > 1) { __mtDimsMulti_ME1++; continue; }
                if (__mtd_ME1.IsLocked) __mtLockedDims_ME1.Add(__mtdi_ME1);
            }
        }
        {
            Element __mte_ME1 = doc.GetElement(new ElementId(8145901));
            if (__mte_ME1 == null) { __t.RollBack(); return __Refuse("ME1", "targets[2]: элемент не найден (модель изменилась после grounding)"); }
            if (__mte_ME1.Pinned) { __t.RollBack(); return __Refuse("ME1", "targets[2]: элемент закреплён (Pinned) — перенос невозможен"); }
            __mtIds_ME1.Add(__mte_ME1.Id);
            __mtEls_ME1.Add(__mte_ME1);
            var __mtlp_ME1 = __mte_ME1.Location as LocationPoint;
            var __mtlc_ME1 = __mte_ME1.Location as LocationCurve;
            __mtBeforePt_ME1.Add(__mtlp_ME1 != null ? __mtlp_ME1.Point : null);
            __mtBefore0_ME1.Add(__mtlc_ME1 != null ? __mtlc_ME1.Curve.GetEndPoint(0) : null);
            __mtBefore1_ME1.Add(__mtlc_ME1 != null ? __mtlc_ME1.Curve.GetEndPoint(1) : null);
            ConnectorManager __mtcm_ME1 = null;
            MEPCurve __mtmc_ME1 = __mte_ME1 as MEPCurve;
            FamilyInstance __mtfi_ME1 = __mte_ME1 as FamilyInstance;
            if (__mtmc_ME1 != null) __mtcm_ME1 = __mtmc_ME1.ConnectorManager;
            else if (__mtfi_ME1 != null && __mtfi_ME1.MEPModel != null) __mtcm_ME1 = __mtfi_ME1.MEPModel.ConnectorManager;
            if (__mtcm_ME1 != null)
                foreach (Connector __mtc_ME1 in __mtcm_ME1.Connectors)
                    if (__mtc_ME1.IsConnected) __mtConnBefore_ME1++;
            var __mtins_ME1 = new List<string>();
            HostObject __mtho_ME1 = __mte_ME1 as HostObject;
            if (__mtho_ME1 != null)
                foreach (ElementId __mtii_ME1 in __mtho_ME1.FindInserts(true, true, false, false))
                    __mtins_ME1.Add(__mtii_ME1.ToString());
            __mtInsBefore_ME1.Add(__mtins_ME1);
            var __mtjn_ME1 = new List<string>();
            try { foreach (ElementId __mtji_ME1 in JoinGeometryUtils.GetJoinedElements(doc, __mte_ME1)) __mtjn_ME1.Add(__mtji_ME1.ToString()); }
            catch { __mtJoinRead_ME1 = false; }
            __mtJoinBefore_ME1.Add(__mtjn_ME1);
            foreach (ElementId __mtdi_ME1 in __mte_ME1.GetDependentElements(new ElementClassFilter(typeof(Dimension))))
            {
                Dimension __mtd_ME1 = doc.GetElement(__mtdi_ME1) as Dimension;
                if (__mtd_ME1 == null) continue;
                __mtDimsSeen_ME1++;
                if (__mtd_ME1.NumberOfSegments > 1) { __mtDimsMulti_ME1++; continue; }
                if (__mtd_ME1.IsLocked) __mtLockedDims_ME1.Add(__mtdi_ME1);
            }
        }
        XYZ __mtDelta_ME1 = new XYZ(U(1000.0), U(0.0), U(500.0));
        try { ElementTransformUtils.MoveElements(doc, __mtIds_ME1, __mtDelta_ME1); doc.Regenerate(); }
        catch (Exception __ex_ME1) { __t.RollBack(); return __Refuse("ME1", "MoveElements: " + __ex_ME1.Message); }
        int __operationPostStart_ME1 = __post.Count;
        // operation ME1
        {
            for (int __mti_ME1 = 0; __mti_ME1 < __mtEls_ME1.Count; __mti_ME1++)
            {
                Element __mte2_ME1 = __mtEls_ME1[__mti_ME1];
                var __mtlp2_ME1 = __mte2_ME1.Location as LocationPoint;
                XYZ __mtbp_ME1 = __mtBeforePt_ME1[__mti_ME1];
                if (__mtlp2_ME1 != null && __mtbp_ME1 != null &&
                    (Math.Abs(MM(__mtlp2_ME1.Point.X) - (MM(__mtbp_ME1.X) + 1000.0)) > 1.0 ||
                     Math.Abs(MM(__mtlp2_ME1.Point.Y) - (MM(__mtbp_ME1.Y) + 0.0)) > 1.0 ||
                     Math.Abs(MM(__mtlp2_ME1.Point.Z) - (MM(__mtbp_ME1.Z) + 500.0)) > 1.0))
                    __post.Add("ME1: targets[" + __mti_ME1 + "] точка не сдвинулась на delta_mm (geometry)");
                var __mtlc2_ME1 = __mte2_ME1.Location as LocationCurve;
                XYZ __mtb0_ME1 = __mtBefore0_ME1[__mti_ME1];
                XYZ __mtb1_ME1 = __mtBefore1_ME1[__mti_ME1];
                if (__mtlc2_ME1 != null && __mtb0_ME1 != null && __mtb1_ME1 != null)
                {
                    XYZ __mta_ME1 = __mtlc2_ME1.Curve.GetEndPoint(0);
                    XYZ __mtb_ME1 = __mtlc2_ME1.Curve.GetEndPoint(1);
                    if (Math.Abs(MM(__mta_ME1.X) - (MM(__mtb0_ME1.X) + 1000.0)) > 1.0 ||
                        Math.Abs(MM(__mta_ME1.Y) - (MM(__mtb0_ME1.Y) + 0.0)) > 1.0 ||
                        Math.Abs(MM(__mta_ME1.Z) - (MM(__mtb0_ME1.Z) + 500.0)) > 1.0 ||
                        Math.Abs(MM(__mtb_ME1.X) - (MM(__mtb1_ME1.X) + 1000.0)) > 1.0 ||
                        Math.Abs(MM(__mtb_ME1.Y) - (MM(__mtb1_ME1.Y) + 0.0)) > 1.0 ||
                        Math.Abs(MM(__mtb_ME1.Z) - (MM(__mtb1_ME1.Z) + 500.0)) > 1.0)
                        __post.Add("ME1: targets[" + __mti_ME1 + "] концы не сдвинулись на delta_mm (geometry)");
                }
            }
        }
        if (__post.Count > __operationPostStart_ME1) { __t.RollBack(); return __Refuse("ME1", String.Join(" ; ", __post.Skip(__operationPostStart_ME1))); }


        // change_type CT1
        __tg_CT1 = (Element)__el_MW;
        __ty_CT1 = doc.GetElement(new ElementId(5001)) as ElementType;
        if (__ty_CT1 == null) { __t.RollBack(); return __Refuse("CT1", "тип не найден (модель изменилась после grounding)"); }
        try { __chid_CT1 = __tg_CT1.ChangeTypeId(__ty_CT1.Id); }
        catch (Exception __ex_CT1) { __t.RollBack(); return __Refuse("CT1", "несовместимый тип (ChangeTypeId): " + __ex_CT1.Message); }
        doc.Regenerate();
        __el_CT1 = (__chid_CT1 != null && __chid_CT1 != ElementId.InvalidElementId)
            ? doc.GetElement(__chid_CT1) : __tg_CT1;
        if (__el_CT1 == null) { __t.RollBack(); return __Refuse("CT1", "элемент не найден после ChangeTypeId"); }
        int __operationPostStart_CT1 = __post.Count;
        // operation CT1
        {
            try { __requestedType_CT1 = __ty_CT1.Id;
                __assignedType_CT1 = __el_CT1.GetTypeId(); } catch { }
            if (__requestedType_CT1 == null || __requestedType_CT1 == ElementId.InvalidElementId
                || __assignedType_CT1 == null || __assignedType_CT1 == ElementId.InvalidElementId
                || !__assignedType_CT1.Equals(__requestedType_CT1))
                __post.Add("CT1: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_CT1) { __t.RollBack(); return __Refuse("CT1", String.Join(" ; ", __post.Skip(__operationPostStart_CT1))); }


        doc.Regenerate();

        // post MW
        {
            var __lc = __el_MW.Location as LocationCurve;
            if (__lc == null) __post.Add("MW: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 1000.0, 2) + Math.Pow(MM(__a.Y) - 0.0, 2);
                double __db = Math.Pow(MM(__b.X) - 1000.0, 2) + Math.Pow(MM(__b.Y) - 0.0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 1000.0) > 5.0 || Math.Abs(MM(__e0.Y) - 0.0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 7000.0) > 5.0 || Math.Abs(MM(__e1.Y) - 0.0) > 5.0)
                    __post.Add("MW: endpoints mismatch (geometry)");
            }
            var __bp = __el_MW.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("MW: level binding mismatch (topology)");
            var __hp = __el_MW.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("MW: height mismatch");
        }
        // post MP
        {
            var __lc = __el_MP.Location as LocationCurve;
            if (__lc == null) __post.Add("MP: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 1000.0, 2) + Math.Pow(MM(__a.Y) - 0.0, 2) + Math.Pow(MM(__a.Z) - 3200.0, 2);
                double __db = Math.Pow(MM(__b.X) - 1000.0, 2) + Math.Pow(MM(__b.Y) - 0.0, 2) + Math.Pow(MM(__b.Z) - 3200.0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 1000.0) > 5.0 || Math.Abs(MM(__e0.Y) - 0.0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 4000.0) > 5.0 || Math.Abs(MM(__e1.Y) - 0.0) > 5.0 || Math.Abs(MM(__e0.Z) - 3200.0) > 5.0 || Math.Abs(MM(__e1.Z) - 3400.0) > 5.0)
                    __post.Add("MP: endpoints mismatch (geometry)");
            }
            var __bp = __el_MP.get_Parameter(BuiltInParameter.RBS_START_LEVEL_PARAM);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("MP: level binding mismatch (topology)");
            var __dp = __el_MP.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM);
            if (__dp == null || Math.Abs(MM(__dp.AsDouble()) - 50.0) > 0.5)
                __post.Add("MP: diameter mismatch");
        }
        // post ME1
        {
            int __mtConnAfter_ME1 = 0;
            foreach (Element __mte3_ME1 in __mtEls_ME1)
            {
                ConnectorManager __mtcm2_ME1 = null;
                MEPCurve __mtmc2_ME1 = __mte3_ME1 as MEPCurve;
                FamilyInstance __mtfi2_ME1 = __mte3_ME1 as FamilyInstance;
                if (__mtmc2_ME1 != null) __mtcm2_ME1 = __mtmc2_ME1.ConnectorManager;
                else if (__mtfi2_ME1 != null && __mtfi2_ME1.MEPModel != null) __mtcm2_ME1 = __mtfi2_ME1.MEPModel.ConnectorManager;
                if (__mtcm2_ME1 != null)
                    foreach (Connector __mtc2_ME1 in __mtcm2_ME1.Connectors)
                        if (__mtc2_ME1.IsConnected) __mtConnAfter_ME1++;
            }
            if (__mtConnBefore_ME1 != __mtConnAfter_ME1)
                __post.Add("ME1: подключённых коннекторов стало " + __mtConnAfter_ME1 + ", было " + __mtConnBefore_ME1 + " (topology)");
            for (int __mtj_ME1 = 0; __mtj_ME1 < __mtEls_ME1.Count; __mtj_ME1++)
            {
                Element __mte4_ME1 = __mtEls_ME1[__mtj_ME1];
                var __mtlc3_ME1 = __mte4_ME1.Location as LocationCurve;
                XYZ __mtb0b_ME1 = __mtBefore0_ME1[__mtj_ME1];
                XYZ __mtb1b_ME1 = __mtBefore1_ME1[__mtj_ME1];
                if (__mtlc3_ME1 != null && __mtb0b_ME1 != null && __mtb1b_ME1 != null)
                {
                    double __mtSlopeBefore_ME1 = MM(__mtb1b_ME1.Z) - MM(__mtb0b_ME1.Z);
                    XYZ __mtA2_ME1 = __mtlc3_ME1.Curve.GetEndPoint(0);
                    XYZ __mtB2_ME1 = __mtlc3_ME1.Curve.GetEndPoint(1);
                    double __mtSlopeAfter_ME1 = MM(__mtB2_ME1.Z) - MM(__mtA2_ME1.Z);
                    if (Math.Abs(__mtSlopeAfter_ME1 - __mtSlopeBefore_ME1) > 1.0)
                        __post.Add("ME1: targets[" + __mtj_ME1 + "] наклон изменился (semantic)");
                }
            }
            for (int __mtk_ME1 = 0; __mtk_ME1 < __mtEls_ME1.Count; __mtk_ME1++)
            {
                HostObject __mtho2_ME1 = __mtEls_ME1[__mtk_ME1] as HostObject;
                if (__mtho2_ME1 == null) continue;
                var __mtnow_ME1 = new HashSet<string>();
                foreach (ElementId __mtii2_ME1 in __mtho2_ME1.FindInserts(true, true, false, false))
                    __mtnow_ME1.Add(__mtii2_ME1.ToString());
                foreach (string __mtwas_ME1 in __mtInsBefore_ME1[__mtk_ME1])
                    if (!__mtnow_ME1.Contains(__mtwas_ME1))
                        __post.Add("ME1: targets[" + __mtk_ME1 + "] потерял размещённый в нём элемент " + __mtwas_ME1 + " (topology)");
            }
            foreach (ElementId __mtld_ME1 in __mtLockedDims_ME1)
            {
                Dimension __mtd2_ME1 = doc.GetElement(__mtld_ME1) as Dimension;
                if (__mtd2_ME1 == null || !__mtd2_ME1.IsLocked)
                    __post.Add("ME1: замок размера " + __mtld_ME1.ToString() + " не пережил перенос (topology)");
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

// witness MW
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_MW.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_MW;
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
        {"requested_type_id", __requestedType_MW == null ? null : __requestedType_MW.ToString()},
        {"observed_type_id", __assignedType_MW == null ? null : __assignedType_MW.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_MW.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_MW.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_MW.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_MW.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["MW"] = __rb;
}

// witness MP
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_MP.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_MP;
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
    try { var __stampParam = __el_MP.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_MP.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_MP.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["MP"] = __rb;
}

// witness ME1
{
    var __rb = new Dictionary<string, object>();
    var __mtIdStrs_ME1 = new List<string>();
    foreach (ElementId __mtrid_ME1 in __mtIds_ME1) __mtIdStrs_ME1.Add(__mtrid_ME1.ToString());
    __rb["moved_ids"] = __mtIdStrs_ME1;
    __rb["count"] = __mtIds_ME1.Count;
    var __mtjlost_ME1 = new List<string>();
    for (int __mtm_ME1 = 0; __mtm_ME1 < __mtEls_ME1.Count; __mtm_ME1++)
    {
        var __mtjnow_ME1 = new HashSet<string>();
        try { foreach (ElementId __mtjj_ME1 in JoinGeometryUtils.GetJoinedElements(doc, __mtEls_ME1[__mtm_ME1])) __mtjnow_ME1.Add(__mtjj_ME1.ToString()); }
        catch { __mtJoinRead_ME1 = false; }
        foreach (string __mtjw_ME1 in __mtJoinBefore_ME1[__mtm_ME1])
            if (!__mtjnow_ME1.Contains(__mtjw_ME1)) __mtjlost_ME1.Add(__mtjw_ME1);
    }
    __rb["joins_lost_count"] = __mtjlost_ME1.Count;
    __rb["joins_lost"] = __mtjlost_ME1.GetRange(0, Math.Min(10, __mtjlost_ME1.Count));
    __rb["joins_read"] = __mtJoinRead_ME1;
    __rb["dims_dependent"] = __mtDimsSeen_ME1;
    __rb["dims_locked"] = __mtLockedDims_ME1.Count;
    __rb["dims_multisegment_unjudged"] = __mtDimsMulti_ME1;
    __results["ME1"] = __rb;
}

// witness CT1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_CT1.Id.ToString();
    __rb["type_assignment"] = new Dictionary<string, object> {
        {"scope", "operation_end_before_commit"},
        {"requested_type_id", __requestedType_CT1 == null ? null : __requestedType_CT1.ToString()},
        {"observed_type_id", __assignedType_CT1 == null ? null : __assignedType_CT1.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_CT1.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    __rb["new_element_created"] = __chid_CT1 != null && __chid_CT1 != ElementId.InvalidElementId;
    __results["CT1"] = __rb;
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