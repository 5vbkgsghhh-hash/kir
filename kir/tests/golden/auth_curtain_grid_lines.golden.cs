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
Func<CurtainGrid, bool, XYZ, string> __KirGridOcc = (__goG, __goU, __goP) =>
{
    try
    {
        ICollection<ElementId> __goS = __goU
            ? __goG.GetUGridLineIds()
            : __goG.GetVGridLineIds();
        if (__goS == null || __goS.Count == 0)
            return "линий этой оси в сетке НЕТ ни одной — значит причина НЕ в занятой координате";
        var __goB = new List<string>();
        var __goDs = new List<double>();
        string __goA = "ось назвать нечем: ни одна существующая линия не читается";
        foreach (ElementId __goE in __goS)
        {
            CurtainGridLine __goL = doc.GetElement(__goE) as CurtainGridLine;
            if (__goL == null) continue;
            double __goD = -1.0;
            // 🔴 ЯРЛЫК КООРДИНАТЫ ВЫБИРАЕТСЯ ПО ОСИ, А НЕ ОДИН НА ОБЕ.
            // У вертикальной линии высота середины не различает НИЧЕГО:
            // она у всех такая же. Подписать её «высота» значило бы дать
            // автору величину, которая не отвечает на его вопрос, — та же
            // форма, что и весь этот дефект.
            string __goW = "положение не прочитано";
            try
            {
                Curve __goC = __goL.FullCurve;
                IntersectionResult __goR = __goC.Project(__goP);
                if (__goR != null) __goD = MM(__goR.Distance);
                XYZ __goM = __goC.Evaluate(0.5, true);
                XYZ __goV = (__goC.GetEndPoint(1) - __goC.GetEndPoint(0)).Normalize();
                if (Math.Abs(__goV.Z) < 0.01)
                {
                    __goA = "эта ось ГОРИЗОНТАЛЬНА: линия идёт вдоль носителя на постоянной ВЫСОТЕ, и двигать надо ВЫСОТУ — третью координату точки";
                    __goW = "высота " + Math.Round(MM(__goM.Z), 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + " мм";
                }
                else
                {
                    __goA = "эта ось ВЕРТИКАЛЬНА: линия идёт снизу вверх в постоянном месте вдоль носителя, и двигать надо положение ВДОЛЬ носителя — первые две координаты точки";
                    __goW = "в плане (" + Math.Round(MM(__goM.X), 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + ", "
                        + Math.Round(MM(__goM.Y), 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + ") мм";
                }
            }
            catch { }
            // 🔴 НЕПРОЧИТАННОЕ РАССТОЯНИЕ НЕ ПЕЧАТАЕТСЯ ЧИСЛОМ И СОРТИРУЕТСЯ
            // ПОСЛЕДНИМ. Пока перечень шёл в порядке прибытия, `-1.0`
            // печаталось как «до запрошенной точки -1 мм» — величина, которой
            // не бывает. С сортировкой по расстоянию это стало НЕСУЩИМ: -1
            // встал бы ВПЕРЕДИ настоящей причины (0 мм) и вытеснил бы её из
            // показанных. Сортируем по MaxValue, печатаем словом.
            __goDs.Add(__goD < 0.0 ? Double.MaxValue : __goD);
            __goB.Add(__goE.ToString() + " (" + __goW + ", "
                + (__goD < 0.0 ? "расстояние до запрошенной точки НЕ ПРОЧИТАНО"
                   : "до запрошенной точки " + Math.Round(__goD, 1).ToString(
                        System.Globalization.CultureInfo.InvariantCulture) + " мм") + ")");
        }
        // ВЫРОЖДЕННЫЙ ВХОД: линии на оси ЕСТЬ, но ни одна не перечиталась.
        // Без этой ветки печаталось бы «линий этой оси уже 0: » — утверждение,
        // прямо противоположное тому, что мы только что видели в сетке.
        if (__goB.Count == 0)
            return __goA + "; линий этой оси в сетке " + __goS.Count.ToString(
                System.Globalization.CultureInfo.InvariantCulture)
                + ", но НИ ОДНА не перечитывается — назвать занятое нечем";
        // 🔴 РЕЖЕМ ПО РЕЛЕВАНТНОСТИ, А НЕ ПО ПОРЯДКУ ПРИБЫТИЯ, и релевантность
        // здесь ТОЧНАЯ: расстояние до запрошенной точки. Причина отказа — та
        // линия, у которой оно 0 мм, и после сортировки она стоит ПЕРВОЙ,
        // то есть переживает любое усечение. Порядок прибытия (по ElementId)
        // не связан с вопросом ничем и вытеснил бы причину случайно.
        double[] __goK = __goDs.ToArray();
        string[] __goT = __goB.ToArray();
        Array.Sort(__goK, __goT);
        int __goN = __goT.Length < 6 ? __goT.Length : 6;
        var __goP2 = new List<string>();
        for (int __goI = 0; __goI < __goN; __goI++) __goP2.Add(__goT[__goI]);
        // 🔴 ЧИСЛО ПОКАЗАННОГО БЕРЁТСЯ ИЗ ТОГО ЖЕ СПИСКА, ЧТО УЕХАЛ ЧИТАТЕЛЮ
        // (идиома `_shown_of` в `ground.py`). Сегодня в этом дереве подпись
        // «ПОКАЗАНЫ 12 ИЗ 48» стояла над ПЯТЬЮ строками (`f132cb8e`) ровно
        // потому, что число объявляли в одном месте, а резали в другом.
        string __goMore = __goT.Length > __goP2.Count
            ? " ПОКАЗАНЫ " + __goP2.Count.ToString(
                System.Globalization.CultureInfo.InvariantCulture) + " БЛИЖАЙШИХ ИЗ "
              + __goT.Length.ToString(
                System.Globalization.CultureInfo.InvariantCulture)
              + " — остальные дальше и причиной быть не могут"
            : "";
        return __goA + "; линий этой оси уже " + __goT.Length.ToString(
            System.Globalization.CultureInfo.InvariantCulture) + ": "
            + String.Join(", ", __goP2) + __goMore
            + ". Revit возвращает null БЕЗ СООБЩЕНИЯ, когда линия этой оси в этом месте УЖЕ ЕСТЬ:"
            + " расстояние 0 мм у одной из перечисленных и есть причина."
            + " СЛЕДУЮЩИЙ ХОД: сдвинь точку по названной оси так, чтобы до каждой существующей линии стало больше нуля";
    }
    catch { return "перечитать линии этой оси не удалось"; }
};
var __results = new Dictionary<string, object>();
var __post = new List<string>();
Wall __el_WG = null;
ElementId __requestedType_WG = null;
ElementId __assignedType_WG = null;
Func<double, double> __ccMMGL1 = (__ccFeet) =>
    UnitUtils.ConvertFromInternalUnits(__ccFeet, UnitTypeId.Millimeters);
// Носители витражной сетки: стена, витражная система, обе разновидности
// кровли. Один класс на носителя — не «а вдруг ещё», а ровно то, что несёт
// CurtainGrid в API 2021-2026 (замер по эталонным сборкам).
Func<Element, List<CurtainGrid>> __ccGridsGL1 = (__ccHost) =>
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
Func<double[], double[], int> __ccCmpGL1 = (__ccA, __ccB) =>
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
Func<ICollection<ElementId>, List<ElementId>> __ccOrderGL1 = (__ccIds) =>
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
            Math.Round(__ccMMGL1(__ccMid.X), 1),
            Math.Round(__ccMMGL1(__ccMid.Y), 1),
            Math.Round(__ccMMGL1(__ccMid.Z), 1) };
        __ccList.Add(__ccLineId);
    }
    __ccList.Sort((__ccL, __ccR) => __ccCmpGL1(
        __ccKeys[__ccL.ToString()], __ccKeys[__ccR.ToString()]));
    for (int __ccI = 1; __ccI < __ccList.Count; __ccI++)
        if (__ccCmpGL1(__ccKeys[__ccList[__ccI - 1].ToString()],
                            __ccKeys[__ccList[__ccI].ToString()]) == 0)
            return null;
    return __ccList;
};
// Адрес ячейки: {u, v} либо null. 0 — ячейка по эту сторону первой линии.
Func<Element, List<ElementId>, List<ElementId>, int[]> __ccAddressGL1 =
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
    __ccPanelAtGL1 = (__ccGrid, __ccU, __ccV, __ccWantU, __ccWantV) =>
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
        int[] __ccAddr = __ccAddressGL1(__ccEl, __ccU, __ccV);
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
Func<Element, ElementId> __ccEffTypeGL1 = (__ccPanelEl) =>
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
Element __gh_GL1 = null;
CurtainGrid __gg_GL1 = null;
CurtainGridLine __gl_GL1 = null;
CurtainGridLine __gr_GL1 = null;
XYZ __gp_GL1 = null;
string __gli_GL1 = null;
bool __gmem_GL1 = false;
bool __gisu_GL1 = false;
double __gdel_GL1 = -1.0;
int __gmul_GL1 = -1;
Func<CurtainGridLine, XYZ, double> __gDistGL1 = (__gdl_GL1, __gdp_GL1) =>
{
    if (__gdl_GL1 == null || __gdp_GL1 == null) return -1.0;
    try
    {
        Curve __gdc_GL1 = __gdl_GL1.FullCurve;
        if (__gdc_GL1 == null) return -1.0;
        IntersectionResult __gdr_GL1 = __gdc_GL1.Project(__gdp_GL1);
        if (__gdr_GL1 == null) return -1.0;
        return MM(__gdr_GL1.Distance);
    }
    catch { return -1.0; }
};
Func<CurtainGrid, string, bool, bool> __gMemGL1 = (__gmg_GL1, __gmi_GL1, __gmu_GL1) =>
{
    if (__gmg_GL1 == null || __gmi_GL1 == null) return false;
    try
    {
        ICollection<ElementId> __gms_GL1 = __gmu_GL1
            ? __gmg_GL1.GetUGridLineIds()
            : __gmg_GL1.GetVGridLineIds();
        if (__gms_GL1 == null) return false;
        foreach (ElementId __gme_GL1 in __gms_GL1)
            if (__gme_GL1.ToString() == __gmi_GL1) return true;
    }
    catch { }
    return false;
};
Func<double, double> __ccMMGL2 = (__ccFeet) =>
    UnitUtils.ConvertFromInternalUnits(__ccFeet, UnitTypeId.Millimeters);
// Носители витражной сетки: стена, витражная система, обе разновидности
// кровли. Один класс на носителя — не «а вдруг ещё», а ровно то, что несёт
// CurtainGrid в API 2021-2026 (замер по эталонным сборкам).
Func<Element, List<CurtainGrid>> __ccGridsGL2 = (__ccHost) =>
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
Func<double[], double[], int> __ccCmpGL2 = (__ccA, __ccB) =>
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
Func<ICollection<ElementId>, List<ElementId>> __ccOrderGL2 = (__ccIds) =>
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
            Math.Round(__ccMMGL2(__ccMid.X), 1),
            Math.Round(__ccMMGL2(__ccMid.Y), 1),
            Math.Round(__ccMMGL2(__ccMid.Z), 1) };
        __ccList.Add(__ccLineId);
    }
    __ccList.Sort((__ccL, __ccR) => __ccCmpGL2(
        __ccKeys[__ccL.ToString()], __ccKeys[__ccR.ToString()]));
    for (int __ccI = 1; __ccI < __ccList.Count; __ccI++)
        if (__ccCmpGL2(__ccKeys[__ccList[__ccI - 1].ToString()],
                            __ccKeys[__ccList[__ccI].ToString()]) == 0)
            return null;
    return __ccList;
};
// Адрес ячейки: {u, v} либо null. 0 — ячейка по эту сторону первой линии.
Func<Element, List<ElementId>, List<ElementId>, int[]> __ccAddressGL2 =
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
    __ccPanelAtGL2 = (__ccGrid, __ccU, __ccV, __ccWantU, __ccWantV) =>
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
        int[] __ccAddr = __ccAddressGL2(__ccEl, __ccU, __ccV);
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
Func<Element, ElementId> __ccEffTypeGL2 = (__ccPanelEl) =>
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
Element __gh_GL2 = null;
CurtainGrid __gg_GL2 = null;
CurtainGridLine __gl_GL2 = null;
CurtainGridLine __gr_GL2 = null;
XYZ __gp_GL2 = null;
string __gli_GL2 = null;
bool __gmem_GL2 = false;
bool __gisu_GL2 = false;
double __gdel_GL2 = -1.0;
int __gmul_GL2 = -1;
Func<CurtainGridLine, XYZ, double> __gDistGL2 = (__gdl_GL2, __gdp_GL2) =>
{
    if (__gdl_GL2 == null || __gdp_GL2 == null) return -1.0;
    try
    {
        Curve __gdc_GL2 = __gdl_GL2.FullCurve;
        if (__gdc_GL2 == null) return -1.0;
        IntersectionResult __gdr_GL2 = __gdc_GL2.Project(__gdp_GL2);
        if (__gdr_GL2 == null) return -1.0;
        return MM(__gdr_GL2.Distance);
    }
    catch { return -1.0; }
};
Func<CurtainGrid, string, bool, bool> __gMemGL2 = (__gmg_GL2, __gmi_GL2, __gmu_GL2) =>
{
    if (__gmg_GL2 == null || __gmi_GL2 == null) return false;
    try
    {
        ICollection<ElementId> __gms_GL2 = __gmu_GL2
            ? __gmg_GL2.GetUGridLineIds()
            : __gmg_GL2.GetVGridLineIds();
        if (__gms_GL2 == null) return false;
        foreach (ElementId __gme_GL2 in __gms_GL2)
            if (__gme_GL2.ToString() == __gmi_GL2) return true;
    }
    catch { }
    return false;
};
Func<double, double> __ccMMGL3 = (__ccFeet) =>
    UnitUtils.ConvertFromInternalUnits(__ccFeet, UnitTypeId.Millimeters);
// Носители витражной сетки: стена, витражная система, обе разновидности
// кровли. Один класс на носителя — не «а вдруг ещё», а ровно то, что несёт
// CurtainGrid в API 2021-2026 (замер по эталонным сборкам).
Func<Element, List<CurtainGrid>> __ccGridsGL3 = (__ccHost) =>
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
Func<double[], double[], int> __ccCmpGL3 = (__ccA, __ccB) =>
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
Func<ICollection<ElementId>, List<ElementId>> __ccOrderGL3 = (__ccIds) =>
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
            Math.Round(__ccMMGL3(__ccMid.X), 1),
            Math.Round(__ccMMGL3(__ccMid.Y), 1),
            Math.Round(__ccMMGL3(__ccMid.Z), 1) };
        __ccList.Add(__ccLineId);
    }
    __ccList.Sort((__ccL, __ccR) => __ccCmpGL3(
        __ccKeys[__ccL.ToString()], __ccKeys[__ccR.ToString()]));
    for (int __ccI = 1; __ccI < __ccList.Count; __ccI++)
        if (__ccCmpGL3(__ccKeys[__ccList[__ccI - 1].ToString()],
                            __ccKeys[__ccList[__ccI].ToString()]) == 0)
            return null;
    return __ccList;
};
// Адрес ячейки: {u, v} либо null. 0 — ячейка по эту сторону первой линии.
Func<Element, List<ElementId>, List<ElementId>, int[]> __ccAddressGL3 =
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
    __ccPanelAtGL3 = (__ccGrid, __ccU, __ccV, __ccWantU, __ccWantV) =>
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
        int[] __ccAddr = __ccAddressGL3(__ccEl, __ccU, __ccV);
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
Func<Element, ElementId> __ccEffTypeGL3 = (__ccPanelEl) =>
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
Element __gh_GL3 = null;
CurtainGrid __gg_GL3 = null;
CurtainGridLine __gl_GL3 = null;
CurtainGridLine __gr_GL3 = null;
XYZ __gp_GL3 = null;
string __gli_GL3 = null;
bool __gmem_GL3 = false;
bool __gisu_GL3 = false;
double __gdel_GL3 = -1.0;
int __gmul_GL3 = -1;
Func<CurtainGridLine, XYZ, double> __gDistGL3 = (__gdl_GL3, __gdp_GL3) =>
{
    if (__gdl_GL3 == null || __gdp_GL3 == null) return -1.0;
    try
    {
        Curve __gdc_GL3 = __gdl_GL3.FullCurve;
        if (__gdc_GL3 == null) return -1.0;
        IntersectionResult __gdr_GL3 = __gdc_GL3.Project(__gdp_GL3);
        if (__gdr_GL3 == null) return -1.0;
        return MM(__gdr_GL3.Distance);
    }
    catch { return -1.0; }
};
Func<CurtainGrid, string, bool, bool> __gMemGL3 = (__gmg_GL3, __gmi_GL3, __gmu_GL3) =>
{
    if (__gmg_GL3 == null || __gmi_GL3 == null) return false;
    try
    {
        ICollection<ElementId> __gms_GL3 = __gmu_GL3
            ? __gmg_GL3.GetUGridLineIds()
            : __gmg_GL3.GetVGridLineIds();
        if (__gms_GL3 == null) return false;
        foreach (ElementId __gme_GL3 in __gms_GL3)
            if (__gme_GL3.ToString() == __gmi_GL3) return true;
    }
    catch { }
    return false;
};
using (Transaction __t = new Transaction(doc, "KIR: витраж: раскладка сетки — своя линия на каждый шаг"))
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
        // create_wall WG
        WallType __wt_WG = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_WG == null) { __t.RollBack(); return __Refuse("WG", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_WG = doc.GetElement(new ElementId(42));
        Level __lv_WG = __lv_raw_WG as Level;
        if (__lv_WG == null) { __t.RollBack(); return __Refuse("WG", (__lv_raw_WG == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_WG) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_WG = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_WG.Id, __lv_WG.Id, U(3000.0), 0.0, false, false);
        if (__el_WG == null) { __t.RollBack(); return __Refuse("WG", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_WG.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0f0b0384:WG"); } catch { }
        int __operationPostStart_WG = __post.Count;
        // operation WG
        {
            try { __requestedType_WG = __wt_WG.Id;
                __assignedType_WG = __el_WG.GetTypeId(); } catch { }
            if (__requestedType_WG == null || __requestedType_WG == ElementId.InvalidElementId
                || __assignedType_WG == null || __assignedType_WG == ElementId.InvalidElementId
                || !__assignedType_WG.Equals(__requestedType_WG))
                __post.Add("WG: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_WG) { __t.RollBack(); return __Refuse("WG", String.Join(" ; ", __post.Skip(__operationPostStart_WG))); }


        // create_curtain_grid_line GL1
        __gh_GL1 = (Element)__el_WG;
        doc.Regenerate();
        var __ggs_GL1 = __ccGridsGL1(__gh_GL1);
        if (__ggs_GL1.Count == 0) { __t.RollBack(); return __Refuse("GL1", "у носителя нет витражной сетки — линию разрезки ставить некуда"); }
        if (__ggs_GL1.Count > 1) { __t.RollBack(); return __Refuse("GL1", "у носителя несколько витражных сеток — в какую ставить линию, неизвестно"); }
        __gg_GL1 = __ggs_GL1[0];
        __gp_GL1 = P(2000.0, 0.0, 1500.0);
        try { __gl_GL1 = __gg_GL1.AddGridLine(true, __gp_GL1, false); }
        catch (Exception __gex_GL1)
        {
            string __gdg_GL1 = __ClassName(__gex_GL1) + ": " + (String.IsNullOrEmpty(__gex_GL1.Message) ? "(пустое сообщение Revit)" : __gex_GL1.Message);
            if (__gex_GL1.InnerException != null)
                __gdg_GL1 += " | внутреннее " + __ClassName(__gex_GL1.InnerException) + ": " + (__gex_GL1.InnerException.Message ?? "");
            __gdg_GL1 += " | носитель " + __gh_GL1.Id.ToString() + " (" + __ClassName(__gh_GL1) + "), направление u, точка (2000.0, 0.0, 1500.0) мм";
            if (String.IsNullOrEmpty(__gex_GL1.Message))
                __gdg_GL1 += " | пустое сообщение у этого вызова замерено 26.08.2026 на точке, лежавшей РОВНО НА ГРАНИЦЕ носителя (z равнялся отметке низа стены): сдвинь точку ВНУТРЬ носителя";
            __gdg_GL1 += " | " + __KirGridOcc(__gg_GL1, true, __gp_GL1);
            __t.RollBack(); return __Refuse("GL1", "AddGridLine: " + __gdg_GL1);
        }
        if (__gl_GL1 == null)
        {
            string __gnl_GL1 = "AddGridLine вернул null — линия не создана. Запрошено: направление u, точка (2000.0, 0.0, 1500.0) мм. " + __KirGridOcc(__gg_GL1, true, __gp_GL1);
            __t.RollBack(); return __Refuse("GL1", __gnl_GL1);
        }
        __gli_GL1 = __gl_GL1.Id.ToString();
        doc.Regenerate();
        __gr_GL1 = doc.GetElement(__gl_GL1.Id) as CurtainGridLine;
        if (__gr_GL1 == null) { __t.RollBack(); return __Refuse("GL1", "созданная линия " + __gli_GL1 + " не читается после Regenerate"); }
        try
        {
            try { Parameter __cm = __gr_GL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0f0b0384"); } catch { }
        }
        catch (Exception __gsx_GL1)
        {
            __t.RollBack(); return __Refuse("GL1", "линия разрезки не принимает штамп прогона (" + __gsx_GL1.Message + ") — созданный, но непомеченный элемент сломал бы сверку пересборки");
        }

        // create_curtain_grid_line GL2
        __gh_GL2 = (Element)__el_WG;
        doc.Regenerate();
        var __ggs_GL2 = __ccGridsGL2(__gh_GL2);
        if (__ggs_GL2.Count == 0) { __t.RollBack(); return __Refuse("GL2", "у носителя нет витражной сетки — линию разрезки ставить некуда"); }
        if (__ggs_GL2.Count > 1) { __t.RollBack(); return __Refuse("GL2", "у носителя несколько витражных сеток — в какую ставить линию, неизвестно"); }
        __gg_GL2 = __ggs_GL2[0];
        __gp_GL2 = P(3000.0, 0.0, 2100.0);
        try { __gl_GL2 = __gg_GL2.AddGridLine(false, __gp_GL2, false); }
        catch (Exception __gex_GL2)
        {
            string __gdg_GL2 = __ClassName(__gex_GL2) + ": " + (String.IsNullOrEmpty(__gex_GL2.Message) ? "(пустое сообщение Revit)" : __gex_GL2.Message);
            if (__gex_GL2.InnerException != null)
                __gdg_GL2 += " | внутреннее " + __ClassName(__gex_GL2.InnerException) + ": " + (__gex_GL2.InnerException.Message ?? "");
            __gdg_GL2 += " | носитель " + __gh_GL2.Id.ToString() + " (" + __ClassName(__gh_GL2) + "), направление v, точка (3000.0, 0.0, 2100.0) мм";
            if (String.IsNullOrEmpty(__gex_GL2.Message))
                __gdg_GL2 += " | пустое сообщение у этого вызова замерено 26.08.2026 на точке, лежавшей РОВНО НА ГРАНИЦЕ носителя (z равнялся отметке низа стены): сдвинь точку ВНУТРЬ носителя";
            __gdg_GL2 += " | " + __KirGridOcc(__gg_GL2, false, __gp_GL2);
            __t.RollBack(); return __Refuse("GL2", "AddGridLine: " + __gdg_GL2);
        }
        if (__gl_GL2 == null)
        {
            string __gnl_GL2 = "AddGridLine вернул null — линия не создана. Запрошено: направление v, точка (3000.0, 0.0, 2100.0) мм. " + __KirGridOcc(__gg_GL2, false, __gp_GL2);
            __t.RollBack(); return __Refuse("GL2", __gnl_GL2);
        }
        __gli_GL2 = __gl_GL2.Id.ToString();
        doc.Regenerate();
        __gr_GL2 = doc.GetElement(__gl_GL2.Id) as CurtainGridLine;
        if (__gr_GL2 == null) { __t.RollBack(); return __Refuse("GL2", "созданная линия " + __gli_GL2 + " не читается после Regenerate"); }
        try
        {
            try { Parameter __cm = __gr_GL2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0f0b0384"); } catch { }
        }
        catch (Exception __gsx_GL2)
        {
            __t.RollBack(); return __Refuse("GL2", "линия разрезки не принимает штамп прогона (" + __gsx_GL2.Message + ") — созданный, но непомеченный элемент сломал бы сверку пересборки");
        }

        // create_curtain_grid_line GL3
        __gh_GL3 = doc.GetElement(new ElementId(8145901));
        if (__gh_GL3 == null) { __t.RollBack(); return __Refuse("GL3", "носитель витража не найден (модель изменилась после grounding)"); }
        doc.Regenerate();
        var __ggs_GL3 = __ccGridsGL3(__gh_GL3);
        if (__ggs_GL3.Count == 0) { __t.RollBack(); return __Refuse("GL3", "у носителя нет витражной сетки — линию разрезки ставить некуда"); }
        if (__ggs_GL3.Count > 1) { __t.RollBack(); return __Refuse("GL3", "у носителя несколько витражных сеток — в какую ставить линию, неизвестно"); }
        __gg_GL3 = __ggs_GL3[0];
        __gp_GL3 = P(4000.0, 120.0, 900.0);
        try { __gl_GL3 = __gg_GL3.AddGridLine(true, __gp_GL3, false); }
        catch (Exception __gex_GL3)
        {
            string __gdg_GL3 = __ClassName(__gex_GL3) + ": " + (String.IsNullOrEmpty(__gex_GL3.Message) ? "(пустое сообщение Revit)" : __gex_GL3.Message);
            if (__gex_GL3.InnerException != null)
                __gdg_GL3 += " | внутреннее " + __ClassName(__gex_GL3.InnerException) + ": " + (__gex_GL3.InnerException.Message ?? "");
            __gdg_GL3 += " | носитель " + __gh_GL3.Id.ToString() + " (" + __ClassName(__gh_GL3) + "), направление u, точка (4000.0, 120.0, 900.0) мм";
            if (String.IsNullOrEmpty(__gex_GL3.Message))
                __gdg_GL3 += " | пустое сообщение у этого вызова замерено 26.08.2026 на точке, лежавшей РОВНО НА ГРАНИЦЕ носителя (z равнялся отметке низа стены): сдвинь точку ВНУТРЬ носителя";
            __gdg_GL3 += " | " + __KirGridOcc(__gg_GL3, true, __gp_GL3);
            __t.RollBack(); return __Refuse("GL3", "AddGridLine: " + __gdg_GL3);
        }
        if (__gl_GL3 == null)
        {
            string __gnl_GL3 = "AddGridLine вернул null — линия не создана. Запрошено: направление u, точка (4000.0, 120.0, 900.0) мм. " + __KirGridOcc(__gg_GL3, true, __gp_GL3);
            __t.RollBack(); return __Refuse("GL3", __gnl_GL3);
        }
        __gli_GL3 = __gl_GL3.Id.ToString();
        doc.Regenerate();
        __gr_GL3 = doc.GetElement(__gl_GL3.Id) as CurtainGridLine;
        if (__gr_GL3 == null) { __t.RollBack(); return __Refuse("GL3", "созданная линия " + __gli_GL3 + " не читается после Regenerate"); }
        try
        {
            try { Parameter __cm = __gr_GL3.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0f0b0384"); } catch { }
        }
        catch (Exception __gsx_GL3)
        {
            __t.RollBack(); return __Refuse("GL3", "линия разрезки не принимает штамп прогона (" + __gsx_GL3.Message + ") — созданный, но непомеченный элемент сломал бы сверку пересборки");
        }

        doc.Regenerate();

        // post WG
        {
            var __lc = __el_WG.Location as LocationCurve;
            if (__lc == null) __post.Add("WG: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("WG: endpoints mismatch (geometry)");
            }
            var __bp = __el_WG.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("WG: level binding mismatch (topology)");
            var __hp = __el_WG.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("WG: height mismatch");
        }
        // post GL1
        {
            __gmem_GL1 = __gMemGL1(__gg_GL1, __gli_GL1, true);
            try { __gisu_GL1 = __gr_GL1.IsUGridLine; } catch { }
            __gdel_GL1 = __gDistGL1(__gr_GL1, __gp_GL1);
            if (!__gmem_GL1)
                __post.Add("GL1: созданная линия не состоит в сетке носителя (topology)");
            if (__gisu_GL1 != true)
                __post.Add("GL1: направление линии не равно запрошенному (semantic)");
            if (__gdel_GL1 < 0.0 || __gdel_GL1 > 25.0)
                __post.Add("GL1: линия не проходит через запрошенную точку (geometry)");
        }
        // post GL2
        {
            __gmem_GL2 = __gMemGL2(__gg_GL2, __gli_GL2, false);
            try { __gisu_GL2 = __gr_GL2.IsUGridLine; } catch { }
            __gdel_GL2 = __gDistGL2(__gr_GL2, __gp_GL2);
            if (!__gmem_GL2)
                __post.Add("GL2: созданная линия не состоит в сетке носителя (topology)");
            if (__gisu_GL2 != false)
                __post.Add("GL2: направление линии не равно запрошенному (semantic)");
            if (__gdel_GL2 < 0.0 || __gdel_GL2 > 25.0)
                __post.Add("GL2: линия не проходит через запрошенную точку (geometry)");
        }
        // post GL3
        {
            __gmem_GL3 = __gMemGL3(__gg_GL3, __gli_GL3, true);
            try { __gisu_GL3 = __gr_GL3.IsUGridLine; } catch { }
            __gdel_GL3 = __gDistGL3(__gr_GL3, __gp_GL3);
            if (!__gmem_GL3)
                __post.Add("GL3: созданная линия не состоит в сетке носителя (topology)");
            if (__gisu_GL3 != true)
                __post.Add("GL3: направление линии не равно запрошенному (semantic)");
            if (__gdel_GL3 < 0.0 || __gdel_GL3 > 25.0)
                __post.Add("GL3: линия не проходит через запрошенную точку (geometry)");
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

// witness WG
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_WG.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_WG;
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
        {"requested_type_id", __requestedType_WG == null ? null : __requestedType_WG.ToString()},
        {"observed_type_id", __assignedType_WG == null ? null : __assignedType_WG.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_WG.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_WG.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_WG.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_WG.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["WG"] = __rb;
}

// witness GL1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __gli_GL1;
    __rb["grid_line_id"] = __gli_GL1;
    __rb["created"] = true;
    __rb["host_id"] = __gh_GL1.Id.ToString();
    __rb["direction"] = "u";
    __rb["is_u_grid_line"] = __gisu_GL1;
    __rb["in_grid"] = __gmem_GL1;
    __rb["position_mm"] = new double[] { 2000.0, 0.0, 1500.0 };
    __rb["position_delta_mm"] = __gdel_GL1;
    try
    {
        int __rbm_GL1 = 0;
        ICollection<ElementId> __rbi_GL1 = __gg_GL1.GetMullionIds();
        if (__rbi_GL1 != null)
            foreach (ElementId __rbe_GL1 in __rbi_GL1)
            {
                Mullion __rbu_GL1 = doc.GetElement(__rbe_GL1) as Mullion;
                if (__rbu_GL1 == null) continue;
                Curve __rbc_GL1 = __rbu_GL1.LocationCurve;
                if (__rbc_GL1 == null) continue;
                double __rbd_GL1 = __gDistGL1(__gr_GL1, __rbc_GL1.Evaluate(0.5, true));
                if (__rbd_GL1 >= 0.0 && __rbd_GL1 <= 10.0) __rbm_GL1++;
            }
        __gmul_GL1 = __rbm_GL1;
    }
    catch { }
    __rb["mullions_on_line"] = __gmul_GL1;
    try { __rb["line_locked"] = __gr_GL1.Lock; } catch { }
    try { var __stampParam = __gr_GL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["GL1"] = __rb;
}

// witness GL2
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __gli_GL2;
    __rb["grid_line_id"] = __gli_GL2;
    __rb["created"] = true;
    __rb["host_id"] = __gh_GL2.Id.ToString();
    __rb["direction"] = "v";
    __rb["is_u_grid_line"] = __gisu_GL2;
    __rb["in_grid"] = __gmem_GL2;
    __rb["position_mm"] = new double[] { 3000.0, 0.0, 2100.0 };
    __rb["position_delta_mm"] = __gdel_GL2;
    try
    {
        int __rbm_GL2 = 0;
        ICollection<ElementId> __rbi_GL2 = __gg_GL2.GetMullionIds();
        if (__rbi_GL2 != null)
            foreach (ElementId __rbe_GL2 in __rbi_GL2)
            {
                Mullion __rbu_GL2 = doc.GetElement(__rbe_GL2) as Mullion;
                if (__rbu_GL2 == null) continue;
                Curve __rbc_GL2 = __rbu_GL2.LocationCurve;
                if (__rbc_GL2 == null) continue;
                double __rbd_GL2 = __gDistGL2(__gr_GL2, __rbc_GL2.Evaluate(0.5, true));
                if (__rbd_GL2 >= 0.0 && __rbd_GL2 <= 10.0) __rbm_GL2++;
            }
        __gmul_GL2 = __rbm_GL2;
    }
    catch { }
    __rb["mullions_on_line"] = __gmul_GL2;
    try { __rb["line_locked"] = __gr_GL2.Lock; } catch { }
    try { var __stampParam = __gr_GL2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["GL2"] = __rb;
}

// witness GL3
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __gli_GL3;
    __rb["grid_line_id"] = __gli_GL3;
    __rb["created"] = true;
    __rb["host_id"] = __gh_GL3.Id.ToString();
    __rb["direction"] = "u";
    __rb["is_u_grid_line"] = __gisu_GL3;
    __rb["in_grid"] = __gmem_GL3;
    __rb["position_mm"] = new double[] { 4000.0, 120.0, 900.0 };
    __rb["position_delta_mm"] = __gdel_GL3;
    try
    {
        int __rbm_GL3 = 0;
        ICollection<ElementId> __rbi_GL3 = __gg_GL3.GetMullionIds();
        if (__rbi_GL3 != null)
            foreach (ElementId __rbe_GL3 in __rbi_GL3)
            {
                Mullion __rbu_GL3 = doc.GetElement(__rbe_GL3) as Mullion;
                if (__rbu_GL3 == null) continue;
                Curve __rbc_GL3 = __rbu_GL3.LocationCurve;
                if (__rbc_GL3 == null) continue;
                double __rbd_GL3 = __gDistGL3(__gr_GL3, __rbc_GL3.Evaluate(0.5, true));
                if (__rbd_GL3 >= 0.0 && __rbd_GL3 <= 10.0) __rbm_GL3++;
            }
        __gmul_GL3 = __rbm_GL3;
    }
    catch { }
    __rb["mullions_on_line"] = __gmul_GL3;
    try { __rb["line_locked"] = __gr_GL3.Lock; } catch { }
    try { var __stampParam = __gr_GL3.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    __results["GL3"] = __rb;
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