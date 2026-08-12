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
WallSweep __el_S1 = null;
Element __ty_S1 = null;
WallSweepInfo __wi_S1 = null;
bool __rev_S1 = false;
ICollection<ElementId> __hs_S1 = null;
Wall __ho_S1 = null;
using (Transaction __t = new Transaction(doc, "KIR: руст по только что построенной стене"))
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
        WallType __wt_W1 = doc.GetElement(new ElementId(101)) as WallType;
        if (__wt_W1 == null) { __t.RollBack(); return __Refuse("W1", "тип стены не найден (модель изменилась после grounding)"); }
        Element __lv_raw_W1 = doc.GetElement(new ElementId(42));
        Level __lv_W1 = __lv_raw_W1 as Level;
        if (__lv_W1 == null) { __t.RollBack(); return __Refuse("W1", (__lv_raw_W1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_W1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        __el_W1 = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(8000, 0, 0)), __wt_W1.Id, __lv_W1.Id, U(3000.0), 0.0, false, false);
        if (__el_W1 == null) { __t.RollBack(); return __Refuse("W1", "Wall.Create вернул null"); }
        try { Parameter __cm = __el_W1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:d4ca9624:W1"); } catch { }

        // create_wall_sweep S1
        Element __hsrc_S1 = __el_W1;
        __ho_S1 = __hsrc_S1 as Wall;
        if (__ho_S1 == null) { __t.RollBack(); return __Refuse("S1", "стенной профиль: носителем может быть только стена, а этот элемент — " + __ClassName(__hsrc_S1) + ". СЛЕДУЮЩИЙ ХОД: назови в host элемент нужного класса"); }
        __ty_S1 = doc.GetElement(new ElementId(1800));
        if (__ty_S1 == null) { __t.RollBack(); return __Refuse("S1", "стенной профиль: тип не найден (модель изменилась после grounding)"); }
        Category __rc_S1 = Category.GetCategory(doc, BuiltInCategory.OST_Reveals);
        Category __sc_S1 = Category.GetCategory(doc, BuiltInCategory.OST_Cornices);
        string __tc_S1 = (__ty_S1.Category == null) ? "" : __ty_S1.Category.Id.ToString();
        __rev_S1 = (__rc_S1 != null && __tc_S1 == __rc_S1.Id.ToString());
        bool __swp_S1 = (__sc_S1 != null && __tc_S1 == __sc_S1.Id.ToString());
        if (!__rev_S1 && !__swp_S1) { __t.RollBack(); return __Refuse("S1", "стенной профиль: разрешённый тип не принадлежит ни карнизам (OST_Cornices), ни рустам (OST_Reveals) — WallSweep.Create строит только их. Тип: " + (__ty_S1.Name ?? "") + ". СЛЕДУЮЩИЙ ХОД: спроси каталог операцией query_types(pool=\"wall_sweep_types\") и назови тип оттуда"); }
        if (!WallSweep.WallAllowsWallSweep(__ho_S1)) { __t.RollBack(); return __Refuse("S1", "стенной профиль: эта стена не может нести профиль (WallSweep.WallAllowsWallSweep вернул false — метод исключает витражные стены и главную стену составной стены). СЛЕДУЮЩИЙ ХОД: назови в host обычную стену"); }
        __wi_S1 = new WallSweepInfo(__rev_S1 ? WallSweepType.Reveal : WallSweepType.Sweep, true);
        __wi_S1.Id = -1;
        __el_S1 = WallSweep.Create(__ho_S1, __ty_S1.Id, __wi_S1);
        if (__el_S1 == null) { __t.RollBack(); return __Refuse("S1", "создание стенного профиля вернуло null"); }
        try { Parameter __cm = __el_S1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:d4ca9624:S1"); } catch { }

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
                    Math.Abs(MM(__e1.X) - 8000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("W1: endpoints mismatch (geometry)");
            }
            var __bp = __el_W1.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("W1: level binding mismatch (topology)");
            var __hp = __el_W1.get_Parameter(BuiltInParameter.WALL_USER_HEIGHT_PARAM);
            if (__hp == null || Math.Abs(MM(__hp.AsDouble()) - 3000.0) > 1.0)
                __post.Add("W1: height mismatch");
        }
        // post S1
        {
            try { __hs_S1 = __el_S1.GetHostIds(); } catch { }
            bool __hh_S1 = false;
            if (__hs_S1 != null && __ho_S1 != null)
                foreach (ElementId __hq_S1 in __hs_S1)
                    if (__hq_S1 != null && __hq_S1.ToString() == __ho_S1.Id.ToString())
                    { __hh_S1 = true; break; }
            if (!__hh_S1)
                __post.Add("S1: построенный профиль не числится на запрошенной стене (topology)");
            ElementId __rt_S1 = __el_S1.GetTypeId();
            if (__rt_S1 == null || __ty_S1 == null
                || __rt_S1.ToString() != __ty_S1.Id.ToString())
                __post.Add("S1: тип построенного элемента (стенной профиль) не равен запрошенному (topology)");
            WallSweepInfo __ri_S1 = null;
            try { __ri_S1 = __el_S1.GetWallSweepInfo(); } catch { }
            if (__ri_S1 == null)
                __post.Add("S1: GetWallSweepInfo() не прочитался — подтвердить ориентацию нечем (semantic)");
            else if (__ri_S1.IsVertical != true)
                __post.Add("S1: ориентация построенного профиля не та, что запрошена (semantic)");
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

// witness S1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_S1.Id.ToString();
    __rb["sweep_kind"] = __rev_S1 ? "reveal" : "sweep";
    __rb["orientation"] = "vertical";
    try { __rb["host_count"] = (__hs_S1 == null) ? -1 : __hs_S1.Count; } catch { }
    try { var __stampParam = __el_S1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { if (__ty_S1 != null && __ty_S1.Name != null) __rb["type_name"] = __ty_S1.Name; } catch { }
    __results["S1"] = __rb;
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