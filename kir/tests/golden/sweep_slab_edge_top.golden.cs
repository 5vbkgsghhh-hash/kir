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
        __KirMainFailures.Warned.Clear();
        __KirMainFailures.Resolved.Clear();
        __KirMainFailures.Attempts.Clear();
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
        doc.Regenerate();
        IList<Reference> __fs_E1 = null;
        try { __fs_E1 = HostObjectUtils.GetTopFaces(__ho_E1); } catch { }
        int __nf_E1 = (__fs_E1 == null) ? 0 : __fs_E1.Count;
        if (__nf_E1 == 0) { __t.RollBack(); return __Refuse("E1", "краевой профиль: у носителя нет грани со стороны «top» (HostObjectUtils вернул пусто). СЛЕДУЮЩИЙ ХОД: проверь, что host — плита или кровля, и назови другую сторону"); }
        if (__nf_E1 > 1) { __t.RollBack(); return __Refuse("E1", "краевой профиль: со стороны «top» у носителя не одна грань, а " + __nf_E1.ToString() + ". Компилятор НЕ выбирает за автора: порядок граней в теле не документирован, поэтому «первая подходящая» — число без смысла. СЛЕДУЮЩИЙ ХОД: краевой профиль по ступенчатому носителю строится отдельной операцией на каждую его плоскость"); }
        Face __fc_E1 = null;
        try {
            var __wanted_E1 = __fs_E1[0].ConvertToStableRepresentation(doc);
            var __options_E1 = new Options { ComputeReferences = true, DetailLevel = ViewDetailLevel.Fine };
            var __geometry_E1 = __ho_E1.get_Geometry(__options_E1);
            if (__geometry_E1 != null) foreach (GeometryObject __object_E1 in __geometry_E1) {
                Solid __solid_E1 = __object_E1 as Solid;
                if (__solid_E1 == null) continue;
                foreach (Face __candidate_E1 in __solid_E1.Faces) {
                    if (__candidate_E1.Reference != null && __candidate_E1.Reference.ConvertToStableRepresentation(doc) == __wanted_E1) {
                        __fc_E1 = __candidate_E1; break;
                    }
                }
                if (__fc_E1 != null) break;
            }
        } catch { }
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