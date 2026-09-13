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
// Округление половиной ОТ НУЛЯ на решётке канона — тот же закон, что у
// decompile.geom_extract._round_mm (floor(s+0.5) / ceil(s-0.5)), а не
// Math.Round: Math.Round(MidpointRounding.ToEven) увёл бы ровно половину
// граничных вершин в соседнюю ячейку и прообраз разошёлся бы с питоновским.
Func<double, double, long> __KirCanonUnit = (__cuMm, __cuGrid) =>
{
    double __cuS = __cuMm / __cuGrid;
    return __cuS >= 0.0
        ? (long)Math.Floor(__cuS + 0.5)
        : (long)Math.Ceiling(__cuS - 0.5);
};
// Лексикографический порядок по целым — тот же, что у python sorted() над
// кортежами: сначала поэлементно, при равенстве — по длине.
Comparison<long[]> __KirCanonCmp = (__ccA, __ccB) =>
{
    int __ccN = __ccA.Length < __ccB.Length ? __ccA.Length : __ccB.Length;
    for (int __ccI = 0; __ccI < __ccN; __ccI++)
    {
        if (__ccA[__ccI] < __ccB[__ccI]) return -1;
        if (__ccA[__ccI] > __ccB[__ccI]) return 1;
    }
    return __ccA.Length.CompareTo(__ccB.Length);
};
// Оболочку JSON (__cpHead/__cpTail) присылает Python — она выведена из того же
// канонизатора, а не набрана здесь второй раз. List.Sort нестабилен, и это
// безразлично: порядок полный по ВСЕМ девяти числам, значит равные строки
// неразличимы по значению.
Func<List<long[]>, string, string, string> __KirCanonPayload =
    (__cpRows, __cpHead, __cpTail) =>
{
    __cpRows.Sort(__KirCanonCmp);
    var __cpSb = new StringBuilder(__cpHead);
    for (int __cpI = 0; __cpI < __cpRows.Count; __cpI++)
    {
        if (__cpI > 0) __cpSb.Append(',');
        long[] __cpR = __cpRows[__cpI];
        for (int __cpJ = 0; __cpJ < 3; __cpJ++)
        {
            __cpSb.Append(__cpJ == 0 ? "[[" : ",[");
            for (int __cpK = 0; __cpK < 3; __cpK++)
            {
                if (__cpK > 0) __cpSb.Append(',');
                __cpSb.Append(__cpR[__cpJ * 3 + __cpK].ToString(
                    System.Globalization.CultureInfo.InvariantCulture));
            }
            __cpSb.Append(']');
        }
        __cpSb.Append(']');
    }
    __cpSb.Append(__cpTail);
    return __cpSb.ToString();
};
var __results = new Dictionary<string, object>();
var __post = new List<string>();
Floor __el_F1 = null;
using (Transaction __t = new Transaction(doc, "KIR: плитный фундамент с двумя проёмами"))
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
        // create_foundation(slab) F1
        FloorType __ft_F1 = doc.GetElement(new ElementId(400)) as FloorType;
        if (__ft_F1 == null) { __t.RollBack(); return __Refuse("F1", "тип фундаментной плиты не найден (модель изменилась после grounding)"); }
        Element __lv_raw_F1 = doc.GetElement(new ElementId(42));
        Level __lv_F1 = __lv_raw_F1 as Level;
        if (__lv_F1 == null) { __t.RollBack(); return __Refuse("F1", (__lv_raw_F1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_F1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        var __loops_F1 = new List<CurveLoop>();
        CurveLoop __ol_F1 = new CurveLoop();
        __ol_F1.Append(Line.CreateBound(P(0, 0, 0), P(12000, 0, 0)));
        __ol_F1.Append(Line.CreateBound(P(12000, 0, 0), P(12000, 8000, 0)));
        __ol_F1.Append(Line.CreateBound(P(12000, 8000, 0), P(0, 8000, 0)));
        __ol_F1.Append(Line.CreateBound(P(0, 8000, 0), P(0, 0, 0)));
        __loops_F1.Add(__ol_F1);
        CurveLoop __hl_F1_0 = new CurveLoop();
        __hl_F1_0.Append(Line.CreateBound(P(2000, 2000, 0), P(4000, 2000, 0)));
        __hl_F1_0.Append(Line.CreateBound(P(4000, 2000, 0), P(4000, 4000, 0)));
        __hl_F1_0.Append(Line.CreateBound(P(4000, 4000, 0), P(2000, 4000, 0)));
        __hl_F1_0.Append(Line.CreateBound(P(2000, 4000, 0), P(2000, 2000, 0)));
        __loops_F1.Add(__hl_F1_0);
        CurveLoop __hl_F1_1 = new CurveLoop();
        __hl_F1_1.Append(Line.CreateBound(P(7000, 3000, 0), P(10000, 3000, 0)));
        __hl_F1_1.Append(Line.CreateBound(P(10000, 3000, 0), P(10000, 6000, 0)));
        __hl_F1_1.Append(Line.CreateBound(P(10000, 6000, 0), P(8500, 7000, 0)));
        __hl_F1_1.Append(Line.CreateBound(P(8500, 7000, 0), P(7000, 6000, 0)));
        __hl_F1_1.Append(Line.CreateBound(P(7000, 6000, 0), P(7000, 3000, 0)));
        __loops_F1.Add(__hl_F1_1);
        __el_F1 = Floor.Create(doc, __loops_F1, __ft_F1.Id, __lv_F1.Id, true, null, 0.0);
        if (__el_F1 == null) { __t.RollBack(); return __Refuse("F1", "создание фундаментной плиты вернуло null"); }
        try { Parameter __cm = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:1ae63604:F1"); } catch { }

        doc.Regenerate();

        // post F1
        {
            Parameter __lp = __el_F1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_F1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_F1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_F1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("F1: level binding mismatch (topology)");
            var __bb = __el_F1.get_BoundingBox(null);
            if (__bb == null) __post.Add("F1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 12000) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 8000) > 50.0)
                __post.Add("F1: bbox extents mismatch (geometry): "
                    + "[" + MM(__bb.Min.X).ToString("F1") + " " + MM(__bb.Max.X).ToString("F1")
                    + " | " + MM(__bb.Min.Y).ToString("F1") + " " + MM(__bb.Max.Y).ToString("F1") + "]"
                    + " против авторских [0 12000 | 0 8000] при допуске 50.0 мм");
            string __slf_F1 = null;
            try
            {
                List<List<Curve>> __slL_F1 = null;
                var __slk_F1 = new List<Sketch>();
                foreach (ElementId __sld_F1 in __el_F1.GetDependentElements(null))
                {
                    var __sls_F1 = doc.GetElement(__sld_F1) as Sketch;
                    if (__sls_F1 != null) __slk_F1.Add(__sls_F1);
                }
                if (__slk_F1.Count == 1)
                {
                    __slL_F1 = new List<List<Curve>>();
                    foreach (CurveArray __slc0_F1 in __slk_F1[0].Profile)
                    {
                        var __slo_F1 = new List<Curve>();
                        foreach (Curve __slx_F1 in __slc0_F1) __slo_F1.Add(__slx_F1);
                        __slL_F1.Add(__slo_F1);
                    }
                }
                if (__slL_F1 != null)
                {
                    var __slr_F1 = new List<string>();
                    foreach (var __slc_F1 in __slL_F1)
                    {
                        var __slv_F1 = new List<long[]>();
                        foreach (Curve __slq_F1 in __slc_F1)
                        {
                            XYZ __slp_F1 = __slq_F1.GetEndPoint(0);
                            __slv_F1.Add(new long[] { __KirCanonUnit(MM(__slp_F1.X), 1.0), __KirCanonUnit(MM(__slp_F1.Y), 1.0) });
                        }
                        __slv_F1.Sort(__KirCanonCmp);
                        var __slb_F1 = new StringBuilder();
                        for (int __sli_F1 = 0; __sli_F1 < __slv_F1.Count; __sli_F1++)
                        {
                            if (__sli_F1 > 0) __slb_F1.Append('|');
                            __slb_F1.Append(__slv_F1[__sli_F1][0].ToString(System.Globalization.CultureInfo.InvariantCulture));
                            __slb_F1.Append(',');
                            __slb_F1.Append(__slv_F1[__sli_F1][1].ToString(System.Globalization.CultureInfo.InvariantCulture));
                        }
                        __slr_F1.Add(__slb_F1.ToString());
                    }
                    __slr_F1.Sort(StringComparer.Ordinal);
                    __slf_F1 = string.Join(";", __slr_F1);
                }
            }
            catch (Exception) { __slf_F1 = null; }
            if (__slf_F1 == null)
                __post.Add("F1: эскиз построенного элемента не прочитан(ы) — форма НЕ ПРОВЕРЕНА (geometry)");
            else if (__slf_F1 != "0,0|0,8000|12000,0|12000,8000;2000,2000|2000,4000|4000,2000|4000,4000;7000,3000|7000,6000|8500,7000|10000,3000|10000,6000")
                __post.Add("F1: sketch loops mismatch, expected 3 loop(s) (geometry)");
            var __sp = __el_F1.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);
            if (__sp == null || __sp.AsInteger() != 1)
                __post.Add("F1: структурный флаг не установлен (semantic)");
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

// witness F1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_F1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_F1;
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
    try { var __stampParam = __el_F1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_F1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_F1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["F1"] = __rb;
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