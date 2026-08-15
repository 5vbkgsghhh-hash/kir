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
Autodesk.Revit.DB.Plumbing.Pipe __el_MP = null;
List<ElementId> __mtIds_ME1 = new List<ElementId>();
List<Element> __mtEls_ME1 = new List<Element>();
List<XYZ> __mtBeforePt_ME1 = new List<XYZ>();
List<XYZ> __mtBefore0_ME1 = new List<XYZ>();
List<XYZ> __mtBefore1_ME1 = new List<XYZ>();
int __mtConnBefore_ME1 = 0;
Element __tg_CT1 = null;
ElementType __ty_CT1 = null;
ElementId __chid_CT1 = null;
Element __el_CT1 = null;
using (Transaction __t = new Transaction(doc, "KIR: перенос связки стена+труба, смена типа стены"))
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
        // create_wall MW
        WallType __wt_MW = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_MW == null) { __t.RollBack(); return __Refuse("MW", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_MW = doc.GetElement(new ElementId(42));
        Level __lv_MW = __lv_raw_MW as Level;
        if (__lv_MW == null) { __t.RollBack(); return __Refuse("MW", (__lv_raw_MW == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_MW) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_MW = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_MW.Id, __lv_MW.Id, U(3000.0), 0.0, false, false);
        if (__el_MW == null) { __t.RollBack(); return __Refuse("MW", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_MW.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:ebdab994:MW"); } catch { }

        // create_pipe MP
        Element __lv_raw_MP = doc.GetElement(new ElementId(42));
        Level __lv_MP = __lv_raw_MP as Level;
        if (__lv_MP == null) { __t.RollBack(); return __Refuse("MP", (__lv_raw_MP == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_MP) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_MP = Autodesk.Revit.DB.Plumbing.Pipe.Create(doc, new ElementId(300), new ElementId(200), __lv_MP.Id, P(0, 0, 2700), P(3000, 0, 2900));
        if (__el_MP == null) { __t.RollBack(); return __Refuse("MP", "Pipe.Create вернул null"); }
        try { Parameter __dp_MP = __el_MP.get_Parameter(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM); if (__dp_MP != null && !__dp_MP.IsReadOnly) __dp_MP.Set(U(50.0)); } catch { }
        try { Parameter __cm = __el_MP.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:ebdab994:MP"); } catch { }

        // move_elements ME1
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
        }
        XYZ __mtDelta_ME1 = new XYZ(U(1000.0), U(0.0), U(500.0));
        try { ElementTransformUtils.MoveElements(doc, __mtIds_ME1, __mtDelta_ME1); }
        catch (Exception __ex_ME1) { __t.RollBack(); return __Refuse("ME1", "MoveElements: " + __ex_ME1.Message); }

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

        doc.Regenerate();

        // post MW
        {
            var __lc = __el_MW.Location as LocationCurve;
            if (__lc == null) __post.Add("MW: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
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
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2) + Math.Pow(MM(__a.Z) - 2700, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2) + Math.Pow(MM(__b.Z) - 2700, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 3000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0 || Math.Abs(MM(__e0.Z) - 2700) > 5.0 || Math.Abs(MM(__e1.Z) - 2900) > 5.0)
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
        }
        // post CT1
        {
            if (__el_CT1.GetTypeId() == null || __el_CT1.GetTypeId().ToString() != __ty_CT1.Id.ToString())
                __post.Add("CT1: тип не удержался после ChangeTypeId (re-read)");
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

// witness MW
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_MW.Id.ToString();
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
    __rb["id"] = __el_MP.Id.ToString();
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
    __results["ME1"] = __rb;
}

// witness CT1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_CT1.Id.ToString();
    __rb["type_id"] = __el_CT1.GetTypeId().ToString();
    __rb["new_element_created"] = __chid_CT1 != null && __chid_CT1 != ElementId.InvalidElementId;
    __results["CT1"] = __rb;
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