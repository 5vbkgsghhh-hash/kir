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
SlabEdge __el_E1 = null;
SlabEdgeType __ty_E1 = null;
List<Reference> __edges_E1 = null;
double __plen_E1 = 0.0;
int __named_E1 = 0;
int __bound_E1 = 0;
HostObject __ho_E1 = null;
using (Transaction __t = new Transaction(doc, "KIR: капельник по верхнему краю плиты"))
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
        // create_slab_edge E1
        Element __hsrc_E1 = doc.GetElement(new ElementId(7777));
        if (__hsrc_E1 == null) { __t.RollBack(); return __Refuse("E1", "краевой профиль: носитель не найден (модель изменилась после grounding)"); }
        __ho_E1 = __hsrc_E1 as HostObject;
        if (__ho_E1 == null) { __t.RollBack(); return __Refuse("E1", "краевой профиль: носителем может быть только перекрытие, кровля, потолок или стена (любой HostObject), а этот элемент — " + __ClassName(__hsrc_E1) + ". СЛЕДУЮЩИЙ ХОД: назови в host элемент нужного класса"); }
        __ty_E1 = doc.GetElement(new ElementId(1801)) as SlabEdgeType;
        if (__ty_E1 == null) { __t.RollBack(); return __Refuse("E1", "краевой профиль: тип не найден или он не SlabEdgeType (модель изменилась после grounding)"); }
        IList<Reference> __fs_E1 = null;
        try { __fs_E1 = HostObjectUtils.GetTopFaces(__ho_E1); } catch { }
        int __nf_E1 = (__fs_E1 == null) ? 0 : __fs_E1.Count;
        if (__nf_E1 == 0) { __t.RollBack(); return __Refuse("E1", "краевой профиль: у носителя нет грани со стороны «top» (HostObjectUtils вернул пусто). СЛЕДУЮЩИЙ ХОД: проверь, что host — плита или кровля, и назови другую сторону"); }
        if (__nf_E1 > 1) { __t.RollBack(); return __Refuse("E1", "краевой профиль: со стороны «top» у носителя не одна грань, а " + __nf_E1.ToString() + ". Компилятор НЕ выбирает за автора: порядок граней в теле не документирован, поэтому «первая подходящая» — число без смысла. СЛЕДУЮЩИЙ ХОД: краевой профиль по ступенчатому носителю строится отдельной операцией на каждую его плоскость"); }
        Face __fc_E1 = null;
        try { __fc_E1 = __ho_E1.GetGeometryObjectFromReference(__fs_E1[0]) as Face; } catch { }
        if (__fc_E1 == null) { __t.RollBack(); return __Refuse("E1", "краевой профиль: грань со стороны «top» не читается как Face — геометрию носителя прочитать не удалось"); }
        EdgeArrayArray __ls_E1 = __fc_E1.EdgeLoops;
        int __nl_E1 = (__ls_E1 == null) ? 0 : __ls_E1.Size;
        if (__nl_E1 != 1) { __t.RollBack(); return __Refuse("E1", "краевой профиль: у грани со стороны «top» не один контур, а " + __nl_E1.ToString() + " — значит в носителе есть отверстия, и какое из колец обводить, решает автор, а не компилятор. СЛЕДУЮЩИЙ ХОД: назови ребро явно, когда у операции появится второй род селектора (сегодня его нет: вторая ступень называет ГРАНЬ, не ребро)"); }
        __edges_E1 = new List<Reference>();
        ReferenceArray __ra_E1 = new ReferenceArray();
        foreach (Edge __ed_E1 in __ls_E1.get_Item(0))
        {
            Reference __er_E1 = __ed_E1.Reference;
            if (__er_E1 == null) { __t.RollBack(); return __Refuse("E1", "краевой профиль: у ребра периметра нет ссылки (Edge.Reference == null) — по такому ребру профиль проложить нечем"); }
            Curve __ec_E1 = __ed_E1.AsCurve();
            if (__ec_E1 == null) { __t.RollBack(); return __Refuse("E1", "краевой профиль: ребро периметра не читается как кривая"); }
            __plen_E1 += __ec_E1.Length;
            __edges_E1.Add(__er_E1);
            __ra_E1.Append(__er_E1);
        }
        if (__ra_E1.Size == 0) { __t.RollBack(); return __Refuse("E1", "краевой профиль: контур грани не дал ни одного ребра"); }
        __el_E1 = doc.Create.NewSlabEdge(__ty_E1, __ra_E1);
        if (__el_E1 == null) { __t.RollBack(); return __Refuse("E1", "создание краевого профиля вернуло null — Revit не принял эти рёбра (NewSlabEdge документирован как возвращающий null при неудаче, а не бросающий)"); }
        try { Parameter __cm = __el_E1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:0040b481:E1"); } catch { }

        doc.Regenerate();

        // post E1
        {
            __named_E1 = (__edges_E1 == null) ? 0 : __edges_E1.Count;
            if (__edges_E1 != null)
                foreach (Reference __wr_E1 in __edges_E1)
                {
                    Curve __wc_E1 = null;
                    try { __wc_E1 = __el_E1.get_ReferenceCurve(__wr_E1); } catch { }
                    if (__wc_E1 != null) __bound_E1++;
                }
            if (__named_E1 == 0 || __bound_E1 != __named_E1)
                __post.Add(__bound_E1.ToString() + " из " + __named_E1.ToString() + " "
                    + "E1: рёбер периметра связаны в построенном профиле (geometry)");
            ElementId __rt_E1 = __el_E1.GetTypeId();
            if (__rt_E1 == null || __ty_E1 == null
                || __rt_E1.ToString() != __ty_E1.Id.ToString())
                __post.Add("E1: тип построенного элемента (краевой профиль) не равен запрошенному (topology)");
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

// witness E1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_E1.Id.ToString();
    __rb["side"] = "top";
    __rb["edges_named"] = __named_E1;
    __rb["edges_bound"] = __bound_E1;
    __rb["perimeter_mm"] = MM(__plen_E1);
    try { __rb["sweep_length_mm"] = MM(__el_E1.Length); } catch { }
    try { var __stampParam = __el_E1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { if (__ty_E1 != null && __ty_E1.Name != null) __rb["type_name"] = __ty_E1.Name; } catch { }
    __results["E1"] = __rb;
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