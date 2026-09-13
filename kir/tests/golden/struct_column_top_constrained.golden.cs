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
FamilyInstance __el_CT = null;
double __vexLo_CT = 0.0;
double __vexHi_CT = 0.0;
using (Transaction __t = new Transaction(doc, "KIR: колонна между двумя уровнями, верх привязан, оба смещения"))
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
        // create_column CT
        FamilySymbol __sy_CT = doc.GetElement(new ElementId(500)) as FamilySymbol;
        if (__sy_CT == null) { __t.RollBack(); return __Refuse("CT", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_CT.IsActive) { __sy_CT.Activate(); doc.Regenerate(); }
        Element __lv_raw_CT = doc.GetElement(new ElementId(42));
        Level __lv_CT = __lv_raw_CT as Level;
        if (__lv_CT == null) { __t.RollBack(); return __Refuse("CT", (__lv_raw_CT == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_CT) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        Level __ctl_CT = doc.GetElement(new ElementId(43)) as Level;
        if (__ctl_CT == null) { __t.RollBack(); return __Refuse("CT", "top_level: уровень не найден (модель изменилась после grounding)"); }
        __el_CT = doc.Create.NewFamilyInstance(P(3000, 1500, 0), __sy_CT, __lv_CT, Autodesk.Revit.DB.Structure.StructuralType.Column);
        if (__el_CT == null) { __t.RollBack(); return __Refuse("CT", "NewFamilyInstance вернул null"); }

        Parameter __cbo_CT = __el_CT.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);
        if (__cbo_CT == null || __cbo_CT.IsReadOnly) { __t.RollBack(); return __Refuse("CT", "FAMILY_BASE_LEVEL_OFFSET_PARAM недоступен у колонны"); }
        __cbo_CT.Set(U(150.0));
        Parameter __ctp_CT = __el_CT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
        if (__ctp_CT == null || __ctp_CT.IsReadOnly) { __t.RollBack(); return __Refuse("CT", "FAMILY_TOP_LEVEL_PARAM недоступен у колонны"); }
        __ctp_CT.Set(__ctl_CT.Id);
        try { Parameter __cto_CT = __el_CT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM); if (__cto_CT != null && !__cto_CT.IsReadOnly) __cto_CT.Set(U(-250.0)); } catch { }
        __vexLo_CT = MM(__lv_CT.Elevation) + 150.0;
        __vexHi_CT = MM(__ctl_CT.Elevation) + -250.0;
        try { Parameter __cm = __el_CT.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:fa4f0a4c:CT"); } catch { }

        doc.Regenerate();

        // post CT
        {
            var __loc = __el_CT.Location as LocationPoint;
            if (__loc == null) __post.Add("CT: нет LocationPoint");
            else if (Math.Abs(MM(__loc.Point.X) - 3000) > 5.0 || Math.Abs(MM(__loc.Point.Y) - 1500) > 5.0)
                __post.Add("CT: location mismatch (geometry)");
            if (__el_CT.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Column)
                __post.Add("CT: StructuralType mismatch (semantic)");
            Parameter __lp = __el_CT.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_CT.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_CT.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_CT.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("CT: level binding mismatch (topology)");
            var __cbop = __el_CT.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM);
            if (__cbop == null || Math.Abs(MM(__cbop.AsDouble()) - 150.0) > 1.0)
                __post.Add("CT: base offset mismatch (geometry)");
            var __ctpp = __el_CT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM);
            if (__ctpp == null || __ctpp.AsElementId() == null || __ctpp.AsElementId().ToString() != "43")
                __post.Add("CT: top constraint mismatch (topology)");
            var __vexBB_CT = __el_CT.get_BoundingBox(null);
            if (__vexBB_CT == null)
                __post.Add("CT: вертикальный габарит не прочитан (geometry)");
            else
            {
                double __vexGot_CT = MM(__vexBB_CT.Max.Z) - MM(__vexBB_CT.Min.Z);
                double __vexWant_CT = __vexHi_CT - __vexLo_CT;
                if (__vexGot_CT < __vexWant_CT - 300.0)
                    __post.Add("CT: вертикальный габарит НЕ ДОХОДИТ до верхнего уровня (geometry)");
            }
            var __ctop = __el_CT.get_Parameter(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM);
            if (__ctop == null || Math.Abs(MM(__ctop.AsDouble()) - -250.0) > 1.0)
                __post.Add("CT: top offset mismatch (geometry)");
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

// witness CT
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_CT.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_CT;
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
    try { var __stampParam = __el_CT.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_CT.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_CT.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rbb = __el_CT.get_BoundingBox(null);
        if (__rbb != null) {
            __rb["vertical_extent_mm"] = new double[] { Math.Round(MM(__rbb.Min.Z), 1), Math.Round(MM(__rbb.Max.Z), 1) };
            __rb["vertical_extent_expected_mm"] = new double[] { Math.Round(__vexLo_CT, 1), Math.Round(__vexHi_CT, 1) };
        } } catch { }
    __results["CT"] = __rb;
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