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
Wall __el_WC = null;
Func<double, double> __ccMMCP1 = (__ccFeet) =>
    UnitUtils.ConvertFromInternalUnits(__ccFeet, UnitTypeId.Millimeters);
// Носители витражной сетки: стена, витражная система, обе разновидности
// кровли. Один класс на носителя — не «а вдруг ещё», а ровно то, что несёт
// CurtainGrid в API 2021-2026 (замер по эталонным сборкам).
Func<Element, List<CurtainGrid>> __ccGridsCP1 = (__ccHost) =>
{
    var __ccOut = new List<CurtainGrid>();
    if (__ccHost == null) return __ccOut;
    try
    {
        Wall __ccWall = __ccHost as Wall;
        if (__ccWall != null)
        {
            CurtainGrid __ccOne = __ccWall.CurtainGrid;
            if (__ccOne != null) __ccOut.Add(__ccOne);
            return __ccOut;
        }
        CurtainGridSet __ccSet = null;
        CurtainSystem __ccSys = __ccHost as CurtainSystem;
        if (__ccSys != null) __ccSet = __ccSys.CurtainGrids;
        ExtrusionRoof __ccExtr = __ccHost as ExtrusionRoof;
        if (__ccExtr != null) __ccSet = __ccExtr.CurtainGrids;
        FootPrintRoof __ccFoot = __ccHost as FootPrintRoof;
        if (__ccFoot != null) __ccSet = __ccFoot.CurtainGrids;
        if (__ccSet != null)
            foreach (CurtainGrid __ccItem in __ccSet)
                if (__ccItem != null) __ccOut.Add(__ccItem);
    }
    catch { }
    return __ccOut;
};
Func<double[], double[], int> __ccCmpCP1 = (__ccA, __ccB) =>
{
    for (int __ccI = 0; __ccI < 3; __ccI++)
    {
        int __ccC = __ccA[__ccI].CompareTo(__ccB[__ccI]);
        if (__ccC != 0) return __ccC;
    }
    return 0;
};
// null == порядок не определён (нечитаемая кривая или две линии на одном
// месте). Молчаливое «оставим как пришло» здесь было бы адресом-догадкой.
Func<ICollection<ElementId>, List<ElementId>> __ccOrderCP1 = (__ccIds) =>
{
    var __ccKeys = new Dictionary<string, double[]>();
    var __ccList = new List<ElementId>();
    if (__ccIds == null) return __ccList;
    foreach (ElementId __ccLineId in __ccIds)
    {
        CurtainGridLine __ccLine = null;
        Curve __ccCurve = null;
        XYZ __ccMid = null;
        try
        {
            __ccLine = doc.GetElement(__ccLineId) as CurtainGridLine;
            if (__ccLine != null) __ccCurve = __ccLine.FullCurve;
            if (__ccCurve != null) __ccMid = __ccCurve.Evaluate(0.5, true);
        }
        catch { }
        if (__ccMid == null) return null;
        __ccKeys[__ccLineId.ToString()] = new double[] {
            Math.Round(__ccMMCP1(__ccMid.X), 1),
            Math.Round(__ccMMCP1(__ccMid.Y), 1),
            Math.Round(__ccMMCP1(__ccMid.Z), 1) };
        __ccList.Add(__ccLineId);
    }
    __ccList.Sort((__ccL, __ccR) => __ccCmpCP1(
        __ccKeys[__ccL.ToString()], __ccKeys[__ccR.ToString()]));
    for (int __ccI = 1; __ccI < __ccList.Count; __ccI++)
        if (__ccCmpCP1(__ccKeys[__ccList[__ccI - 1].ToString()],
                            __ccKeys[__ccList[__ccI].ToString()]) == 0)
            return null;
    return __ccList;
};
// Адрес ячейки: {u, v} либо null. 0 — ячейка по эту сторону первой линии.
Func<Element, List<ElementId>, List<ElementId>, int[]> __ccAddressCP1 =
    (__ccPanelEl, __ccU, __ccV) =>
{
    Panel __ccPanel = __ccPanelEl as Panel;
    if (__ccPanel == null || __ccU == null || __ccV == null) return null;
    // GetRefGridLines принимает ИМЕННО ref, а не out (замер: Roslyn против
    // эталонных сборок, CS1620 на всех шести версиях), поэтому обе ссылки
    // обязаны быть проинициализированы до вызова.
    ElementId __ccURef = ElementId.InvalidElementId;
    ElementId __ccVRef = ElementId.InvalidElementId;
    try { __ccPanel.GetRefGridLines(ref __ccURef, ref __ccVRef); }
    catch { return null; }
    var __ccAddr = new int[] { 0, 0 };
    var __ccRefs = new ElementId[] { __ccURef, __ccVRef };
    var __ccOrders = new List<ElementId>[] { __ccU, __ccV };
    string __ccInvalid = ElementId.InvalidElementId.ToString();
    for (int __ccAxis = 0; __ccAxis < 2; __ccAxis++)
    {
        ElementId __ccRef = __ccRefs[__ccAxis];
        if (__ccRef == null || __ccRef.ToString() == __ccInvalid) continue;
        int __ccRank = -1;
        List<ElementId> __ccOrderAxis = __ccOrders[__ccAxis];
        for (int __ccI = 0; __ccI < __ccOrderAxis.Count; __ccI++)
            if (__ccOrderAxis[__ccI].ToString() == __ccRef.ToString())
            { __ccRank = __ccI + 1; break; }
        if (__ccRank < 0) return null;
        __ccAddr[__ccAxis] = __ccRank;
    }
    return __ccAddr;
};
Func<CurtainGrid, List<ElementId>, List<ElementId>, int, int, Element>
    __ccPanelAtCP1 = (__ccGrid, __ccU, __ccV, __ccWantU, __ccWantV) =>
{
    if (__ccGrid == null || __ccU == null || __ccV == null) return null;
    ICollection<ElementId> __ccPanelIds = null;
    try { __ccPanelIds = __ccGrid.GetPanelIds(); }
    catch { return null; }
    if (__ccPanelIds == null) return null;
    foreach (ElementId __ccPid in __ccPanelIds)
    {
        Element __ccEl = doc.GetElement(__ccPid);
        // Страж доказуемости KUKAI002; обоснование и границы — в
        // комментарии Python над этим шаблоном, чтобы проза не ехала в Revit.
        if (__ccEl == null) continue;
        int[] __ccAddr = __ccAddressCP1(__ccEl, __ccU, __ccV);
        if (__ccAddr != null && __ccAddr[0] == __ccWantU
            && __ccAddr[1] == __ccWantV)
            return __ccEl;
    }
    return null;
};
// ЭФФЕКТИВНЫЙ тип ячейки. Ячейка, заполненная стеной, живёт в Revit ДВУМЯ
// элементами: обёрткой-Panel (её тип — системный «стена») и телом-Wall (у
// него настоящий тип). Тип ячейки — это тип ТЕЛА, если тело есть; иначе
// собственный тип панели. Одно определение на захват и на свидетеля, иначе
// пересборка «сходилась» бы с исходником по обёртке, потеряв тип тела.
Func<Element, ElementId> __ccEffTypeCP1 = (__ccPanelEl) =>
{
    if (__ccPanelEl == null) return null;
    try
    {
        Panel __ccPanel = __ccPanelEl as Panel;
        if (__ccPanel != null)
        {
            ElementId __ccBodyId = __ccPanel.FindHostPanel();
            if (__ccBodyId != null
                && __ccBodyId.ToString() != ElementId.InvalidElementId.ToString())
            {
                Element __ccBody = doc.GetElement(__ccBodyId);
                if (__ccBody != null) return __ccBody.GetTypeId();
            }
        }
    }
    catch { }
    return __ccPanelEl.GetTypeId();
};
Element __ch_CP1 = null;
CurtainGrid __cg_CP1 = null;
List<ElementId> __cu_CP1 = null;
List<ElementId> __cv_CP1 = null;
Element __cp_CP1 = null;
Element __cq_CP1 = null;
Element __cn_CP1 = null;
Element __co_CP1 = null;
string __cpi_CP1 = null;
bool __cch_CP1 = false;
ElementType __ct_CP1 = null;
Func<Element, bool> __ccAxisCP1 = (__cae_CP1) =>
{
    if (__cae_CP1 == null || __ch_CP1 == null) return false;
    try
    {
        LocationCurve __cah_CP1 = __ch_CP1.Location as LocationCurve;
        LocationCurve __cao_CP1 = __cae_CP1.Location as LocationCurve;
        if (__cah_CP1 == null || __cao_CP1 == null) return false;
        if (__cah_CP1.Curve == null || __cao_CP1.Curve == null) return false;
        XYZ __cam_CP1 = __cao_CP1.Curve.Evaluate(0.5, true);
        IntersectionResult __cap_CP1 = __cah_CP1.Curve.Project(__cam_CP1);
        if (__cap_CP1 == null) return false;
        return MM(__cap_CP1.Distance) <= 50.0;
    }
    catch { return false; }
};
using (Transaction __t = new Transaction(doc, "KIR: витраж: стеклопакет в единственную ячейку"))
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
        // create_wall WC
        WallType __wt_WC = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_WC == null) { __t.RollBack(); return __Refuse("WC", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_WC = doc.GetElement(new ElementId(42));
        Level __lv_WC = __lv_raw_WC as Level;
        if (__lv_WC == null) { __t.RollBack(); return __Refuse("WC", (__lv_raw_WC == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_WC) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_WC = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_WC.Id, __lv_WC.Id, U(3000.0), 0.0, false, false);
        if (__el_WC == null) { __t.RollBack(); return __Refuse("WC", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_WC.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:b98d8803:WC"); } catch { }

        // set_curtain_panel CP1
        __ch_CP1 = (Element)__el_WC;
        doc.Regenerate();
        var __cgs_CP1 = __ccGridsCP1(__ch_CP1);
        if (__cgs_CP1.Count == 0) { __t.RollBack(); return __Refuse("CP1", "у носителя нет витражной сетки — ячейку назначать нечему"); }
        if (__cgs_CP1.Count > 1) { __t.RollBack(); return __Refuse("CP1", "у носителя несколько витражных сеток — адрес (u,v) неоднозначен"); }
        __cg_CP1 = __cgs_CP1[0];
        __cu_CP1 = __ccOrderCP1(__cg_CP1.GetUGridLineIds());
        __cv_CP1 = __ccOrderCP1(__cg_CP1.GetVGridLineIds());
        if (__cu_CP1 == null || __cv_CP1 == null) { __t.RollBack(); return __Refuse("CP1", "порядок линий разрезки не определён (нечитаемая кривая или две линии на одном месте) — адреса ячейки нет"); }
        if (0 > __cu_CP1.Count || 0 > __cv_CP1.Count) { __t.RollBack(); return __Refuse("CP1", "адрес ячейки вне сетки носителя: (0,0) при " + __cu_CP1.Count + "×" + __cv_CP1.Count + " линиях"); }
        __cp_CP1 = __ccPanelAtCP1(__cg_CP1, __cu_CP1, __cv_CP1, 0, 0);
        if (__cp_CP1 == null) { __t.RollBack(); return __Refuse("CP1", "ячейка (0,0) не найдена в сетке носителя"); }
        __cpi_CP1 = __cp_CP1.Id.ToString();
        var __cts_CP1 = new List<ElementType>();
        foreach (Element __cte_CP1 in new FilteredElementCollector(doc).OfClass(typeof(FamilySymbol)))
            if (__cte_CP1.Name == "Стеклопакет 30мм") __cts_CP1.Add((ElementType)__cte_CP1);
        foreach (Element __ctw_CP1 in new FilteredElementCollector(doc).OfClass(typeof(WallType)))
            if (__ctw_CP1.Name == "Стеклопакет 30мм") __cts_CP1.Add((ElementType)__ctw_CP1);
        if (__cts_CP1.Count == 0) { __t.RollBack(); return __Refuse("CP1", "тип панели «Стеклопакет 30мм» не найден среди типоразмеров семейств и типов стен"); }
        if (__cts_CP1.Count > 1) { __t.RollBack(); return __Refuse("CP1", "тип панели «Стеклопакет 30мм» неоднозначен — несколько типов с этим именем; укажите element_id"); }
        __ct_CP1 = __cts_CP1[0];
        bool __clk_CP1 = true;
        try { foreach (ElementId __cli_CP1 in __cg_CP1.GetUnlockedPanelIds())
            if (__cli_CP1.ToString() == __cp_CP1.Id.ToString()) { __clk_CP1 = false; break; } } catch { }
        bool __cpn_CP1 = false;
        try { __cpn_CP1 = __cp_CP1.Pinned; } catch { }
        if (__clk_CP1 || __cpn_CP1)
        {
            try { __cp_CP1.Pinned = false; }
            catch (Exception __cux_CP1)
            {
                __t.RollBack(); return __Refuse("CP1", "замок ячейки не снимается для " + __ClassName(__cp_CP1) + " (панель " + __cp_CP1.Id.ToString() + "): " + __ClassName(__cux_CP1) + ": " + (String.IsNullOrEmpty(__cux_CP1.Message) ? "(пустое сообщение Revit)" : __cux_CP1.Message));
            }
        }
        try { __cn_CP1 = __cg_CP1.ChangePanelType(__cp_CP1, __ct_CP1); }
        catch (Exception __cex_CP1)
        {
            string __cdg_CP1 = __ClassName(__cex_CP1) + ": " + (String.IsNullOrEmpty(__cex_CP1.Message) ? "(пустое сообщение Revit)" : __cex_CP1.Message);
            if (__cex_CP1.InnerException != null)
                __cdg_CP1 += " | внутреннее " + __ClassName(__cex_CP1.InnerException) + ": " + (__cex_CP1.InnerException.Message ?? "");
            bool __cul_CP1 = false;
            try { foreach (ElementId __cui_CP1 in __cg_CP1.GetUnlockedPanelIds())
                if (__cui_CP1.ToString() == __cp_CP1.Id.ToString()) { __cul_CP1 = true; break; } } catch { }
            __cdg_CP1 += " | до отпирания: заперта=" + (__clk_CP1 ? "да" : "нет") + ", pinned=" + (__cpn_CP1 ? "да" : "нет");
            __cdg_CP1 += " | ячейка (0,0) панель " + __cp_CP1.Id.ToString() + " (" + __ClassName(__cp_CP1) + "), разблокирована=" + (__cul_CP1 ? "да" : "нет") + ", новый тип " + __ct_CP1.Id.ToString() + " (" + __ClassName(__ct_CP1) + "), носитель " + __ch_CP1.Id.ToString();
            __t.RollBack(); return __Refuse("CP1", "ChangePanelType: " + __cdg_CP1);
        }
        if (__cn_CP1 != null)
        {
            ElementId __cnt_CP1 = null;
            try { __cnt_CP1 = __cn_CP1.GetTypeId(); } catch { }
            if (__cnt_CP1 == null || __cnt_CP1.ToString() != __ct_CP1.Id.ToString())
            {
                try
                {
                    ElementId __cnr_CP1 = __cn_CP1.ChangeTypeId(__ct_CP1.Id);
                    __cch_CP1 = true;
                    if (__cnr_CP1 != null && __cnr_CP1.ToString() != ElementId.InvalidElementId.ToString())
                    {
                        Element __cnw_CP1 = doc.GetElement(__cnr_CP1);
                        if (__cnw_CP1 != null) __cn_CP1 = __cnw_CP1;
                    }
                }
                catch (Exception __ctx_CP1)
                {
                    __t.RollBack(); return __Refuse("CP1", "догон типа ячейки не прошёл: " + __ClassName(__ctx_CP1) + ": " + (String.IsNullOrEmpty(__ctx_CP1.Message) ? "(пустое сообщение Revit)" : __ctx_CP1.Message) + " | занявший " + __cn_CP1.Id.ToString() + " (" + __ClassName(__cn_CP1) + "), просили тип " + __ct_CP1.Id.ToString());
                }
            }
        }
        if (__cn_CP1 != null && __cn_CP1.Id.ToString() != __cpi_CP1)
        {
            try { Parameter __cm = __cn_CP1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:b98d8803"); } catch { }
        }

        doc.Regenerate();

        // post WC
        {
            var __lc = __el_WC.Location as LocationCurve;
            if (__lc == null) __post.Add("WC: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("WC: endpoints mismatch (geometry)");
            }
            var __bp = __el_WC.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("WC: level binding mismatch (topology)");
            var __hp = __el_WC.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("WC: height mismatch");
        }
        // post CP1
        {
            __cq_CP1 = __ccPanelAtCP1(__cg_CP1, __ccOrderCP1(__cg_CP1.GetUGridLineIds()), __ccOrderCP1(__cg_CP1.GetVGridLineIds()), 0, 0);
            if (__cn_CP1 != null)
            {
                bool __cnm_CP1 = false;
                if (__cn_CP1 is FamilyInstance)
                {
                    try { foreach (ElementId __cni_CP1 in __cg_CP1.GetPanelIds())
                        if (__cni_CP1.ToString() == __cn_CP1.Id.ToString()) { __cnm_CP1 = true; break; } } catch { }
                }
                else __cnm_CP1 = __ccAxisCP1(__cn_CP1);
                if (__cnm_CP1) __co_CP1 = __cn_CP1;
            }
            if (__co_CP1 == null) __co_CP1 = __cq_CP1;
            if (__co_CP1 == null)
                __post.Add("CP1: ячейка (0,0) не читается после сборки (semantic)");
            else
            {
                ElementId __cet_CP1 = __ccEffTypeCP1(__co_CP1);
                if (__cet_CP1 == null || __cet_CP1.ToString() != __ct_CP1.Id.ToString())
                    __post.Add("CP1: тип панели в ячейке не равен запрошенному (semantic)");
            }
            {
                FamilyInstance __cfi_CP1 = __co_CP1 as FamilyInstance;
                if (__cfi_CP1 != null)
                {
                    if (__cfi_CP1.Host == null
                        || __cfi_CP1.Host.Id.ToString() != __ch_CP1.Id.ToString())
                        __post.Add("CP1: ячейка принадлежит другому носителю (topology)");
                }
                else
                {
                    bool __chm_CP1 = __ccAxisCP1(__co_CP1);
                    if (!__chm_CP1)
                        __post.Add("CP1: ячейка принадлежит другому носителю (topology)");
                }
            }
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

// witness WC
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_WC.Id.ToString();
    try { var __stampParam = __el_WC.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_WC.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_WC.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["WC"] = __rb;
}

// witness CP1
{
    var __rb = new Dictionary<string, object>();
    __rb["host_id"] = __ch_CP1.Id.ToString();
    __rb["u"] = 0;
    __rb["v"] = 0;
    __rb["requested_type_id"] = __ct_CP1.Id.ToString();
    __rb["requested_type_name"] = __ct_CP1.Name;
    __rb["old_panel_id"] = __cpi_CP1;
    if (__cn_CP1 != null) __rb["returned_panel_id"] = __cn_CP1.Id.ToString();
    if (__cq_CP1 != null) __rb["addressed_panel_id"] = __cq_CP1.Id.ToString();
    if (__co_CP1 != null)
    {
        __rb["id"] = __co_CP1.Id.ToString();
        __rb["panel_id"] = __co_CP1.Id.ToString();
        __rb["panel_replaced"] = (__co_CP1.Id.ToString() != __cpi_CP1);
        __rb["created"] = (__co_CP1.Id.ToString() != __cpi_CP1);
        __rb["type_chased"] = __cch_CP1;
        __rb["panel_class"] = __ClassName(__co_CP1);
        bool __rbl_CP1 = false;
        try { foreach (ElementId __rbi_CP1 in __cg_CP1.GetUnlockedPanelIds())
            if (__rbi_CP1.ToString() == __co_CP1.Id.ToString()) { __rbl_CP1 = true; break; } } catch { }
        bool __rbp_CP1 = false;
        try { __rbp_CP1 = __co_CP1.Pinned; } catch { }
        __rb["panel_lock"] = (__rbl_CP1 ? "разблокирована" : "заперта") + ", pinned=" + (__rbp_CP1 ? "да" : "нет");
        ElementId __rbt_CP1 = __ccEffTypeCP1(__co_CP1);
        if (__rbt_CP1 != null)
        {
            __rb["panel_type_id"] = __rbt_CP1.ToString();
            Element __rbe_CP1 = doc.GetElement(__rbt_CP1);
            if (__rbe_CP1 != null) __rb["panel_type_name"] = __rbe_CP1.Name;
        }
    }
    __results["CP1"] = __rb;
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