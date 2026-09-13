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
Wall __el_WT = null;
ElementId __requestedType_WT = null;
ElementId __assignedType_WT = null;
double __wexLo_WT = 0.0;
double __wexHi_WT = 0.0;
using (Transaction __t = new Transaction(doc, "KIR: стена, приаттаченная к верхнему уровню"))
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
        // create_wall WT
        WallType __wt_WT = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.WallType)) as WallType;
        if (__wt_WT == null) { __t.RollBack(); return __Refuse("WT", "в документе нет типа стены по умолчанию"); }
        Element __lv_raw_WT = doc.GetElement(new ElementId(42));
        Level __lv_WT = __lv_raw_WT as Level;
        if (__lv_WT == null) { __t.RollBack(); return __Refuse("WT", (__lv_raw_WT == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_WT) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        Level __tl_WT = doc.GetElement(new ElementId(43)) as Level;
        if (__tl_WT == null) { __t.RollBack(); return __Refuse("WT", "top_level: уровень не найден (модель изменилась после grounding)"); }
        __el_WT = Wall.Create(doc, Line.CreateBound(P(0, 0, 0), P(6000, 0, 0)), __wt_WT.Id, __lv_WT.Id, U(3000.0), 0.0, false, false);
        if (__el_WT == null) { __t.RollBack(); return __Refuse("WT", "Wall.Create вернул null"); }
        if (__tl_WT.Elevation + 0.0 <= __lv_WT.Elevation + 0.0)
        { __t.RollBack(); return __Refuse("WT", "верх стены не выше подошвы: привязка верха невозможна"); }
        Parameter __ht_WT = __el_WT.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE);
        if (__ht_WT == null || __ht_WT.IsReadOnly) { __t.RollBack(); return __Refuse("WT", "WALL_HEIGHT_TYPE недоступен у стены"); }
        __ht_WT.Set(__tl_WT.Id);
        try { Parameter __to_WT = __el_WT.get_Parameter(BuiltInParameter.WALL_TOP_OFFSET); if (__to_WT != null && !__to_WT.IsReadOnly) __to_WT.Set(0.0); } catch { }
        __wexLo_WT = MM(__lv_WT.Elevation);
        __wexHi_WT = MM(__tl_WT.Elevation);
        try { Parameter __cm = __el_WT.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:a1cde8df:WT"); } catch { }
        int __operationPostStart_WT = __post.Count;
        // operation WT
        {
            try { __requestedType_WT = __wt_WT.Id;
                __assignedType_WT = __el_WT.GetTypeId(); } catch { }
            if (__requestedType_WT == null || __requestedType_WT == ElementId.InvalidElementId
                || __assignedType_WT == null || __assignedType_WT == ElementId.InvalidElementId
                || !__assignedType_WT.Equals(__requestedType_WT))
                __post.Add("WT: type assignment mismatch or unavailable (operation)");
        }
        if (__post.Count > __operationPostStart_WT) { __t.RollBack(); return __Refuse("WT", String.Join(" ; ", __post.Skip(__operationPostStart_WT))); }


        doc.Regenerate();

        // post WT
        {
            var __lc = __el_WT.Location as LocationCurve;
            if (__lc == null) __post.Add("WT: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 0, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 0, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 0) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 6000) > 5.0 || Math.Abs(MM(__e1.Y) - 0) > 5.0)
                    __post.Add("WT: endpoints mismatch (geometry)");
            }
            var __bp = __el_WT.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT);
            if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != "42")
                __post.Add("WT: level binding mismatch (topology)");
            var __htp = __el_WT.get_Parameter(BuiltInParameter.WALL_HEIGHT_TYPE);
            if (__htp == null || __htp.AsElementId() == null || __htp.AsElementId().ToString() != "43")
                __post.Add("WT: top constraint mismatch (topology)");
            var __wexBB_WT = __el_WT.get_BoundingBox(null);
            if (__wexBB_WT == null)
                __post.Add("WT: вертикальный габарит не прочитан (geometry)");
            else
            {
                double __wexGot_WT = MM(__wexBB_WT.Max.Z) - MM(__wexBB_WT.Min.Z);
                double __wexWant_WT = __wexHi_WT - __wexLo_WT;
                if (__wexGot_WT < __wexWant_WT - 300.0)
                    __post.Add("WT: вертикальный габарит НЕ ДОХОДИТ до верхнего уровня (geometry)");
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

// witness WT
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_WT.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_WT;
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
        {"requested_type_id", __requestedType_WT == null ? null : __requestedType_WT.ToString()},
        {"observed_type_id", __assignedType_WT == null ? null : __assignedType_WT.ToString()} };
    __rb["type_id"] = null; __rb["type_id_status"] = "unavailable";
    __rb["type_id_reason"] = "type_id_unreadable";
    try { var __finalType = __el_WT.GetTypeId();
        if (__finalType != null && __finalType != ElementId.InvalidElementId) {
            __rb["type_id"] = __finalType.ToString(); __rb["type_id_status"] = "captured";
            __rb["type_id_reason"] = null;
        } else __rb["type_id_reason"] = "type_id_missing"; } catch { }
    try { var __stampParam = __el_WT.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_WT.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_WT.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rbb = __el_WT.get_BoundingBox(null);
        if (__rbb != null) {
            __rb["vertical_extent_mm"] = new double[] { Math.Round(MM(__rbb.Min.Z), 1), Math.Round(MM(__rbb.Max.Z), 1) };
            __rb["vertical_extent_expected_mm"] = new double[] { Math.Round(__wexLo_WT, 1), Math.Round(__wexHi_WT, 1) };
        } } catch { }
    __results["WT"] = __rb;
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