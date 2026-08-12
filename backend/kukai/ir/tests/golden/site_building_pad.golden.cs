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
BuildingPad __el_P1 = null;
List<CurveLoop> __loops_P1 = null;
using (Transaction __t = new Transaction(doc, "KIR: площадка под здание с проёмом под приямок"))
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
        // create_building_pad P1
        BuildingPadType __ty_P1 = doc.GetElement(new ElementId(1701)) as BuildingPadType;
        if (__ty_P1 == null) { __t.RollBack(); return __Refuse("P1", "площадка под здание: тип не найден (модель изменилась после grounding)"); }
        Element __lv_raw_P1 = doc.GetElement(new ElementId(42));
        Level __lv_P1 = __lv_raw_P1 as Level;
        if (__lv_P1 == null) { __t.RollBack(); return __Refuse("P1", (__lv_raw_P1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_P1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        int __hosts_P1 = new FilteredElementCollector(doc).OfClass(typeof(TopographySurface)).WhereElementIsNotElementType().GetElementCount();
        __hosts_P1 += new FilteredElementCollector(doc).OfClass(typeof(Toposolid)).WhereElementIsNotElementType().GetElementCount();
        if (__hosts_P1 == 0) { __t.RollBack(); return __Refuse("P1", "площадку под здание не на что сажать: в документе нет ни одной топоповерхности. Следующий ход — создать рельеф операцией create_topography, и только потом площадку (Revit ищет хозяина сам и без него бросает «Cannot find an appropriate hosting topography surface»)"); }
        __loops_P1 = new List<CurveLoop>();
        CurveLoop __ol_P1 = new CurveLoop();
        __ol_P1.Append(Line.CreateBound(P(2000.0, 2000.0, 0), P(14000.0, 2000.0, 0)));
        __ol_P1.Append(Line.CreateBound(P(14000.0, 2000.0, 0), P(14000.0, 11000.0, 0)));
        __ol_P1.Append(Line.CreateBound(P(14000.0, 11000.0, 0), P(2000.0, 11000.0, 0)));
        __ol_P1.Append(Line.CreateBound(P(2000.0, 11000.0, 0), P(2000.0, 2000.0, 0)));
        __loops_P1.Add(__ol_P1);
        CurveLoop __hl_P1_0 = new CurveLoop();
        __hl_P1_0.Append(Line.CreateBound(P(5000.0, 4000.0, 0), P(6500.0, 4000.0, 0)));
        __hl_P1_0.Append(Line.CreateBound(P(6500.0, 4000.0, 0), P(6500.0, 5500.0, 0)));
        __hl_P1_0.Append(Line.CreateBound(P(6500.0, 5500.0, 0), P(5000.0, 5500.0, 0)));
        __hl_P1_0.Append(Line.CreateBound(P(5000.0, 5500.0, 0), P(5000.0, 4000.0, 0)));
        __loops_P1.Add(__hl_P1_0);
        __el_P1 = BuildingPad.Create(doc, __ty_P1.Id, __lv_P1.Id, __loops_P1);
        if (__el_P1 == null) { __t.RollBack(); return __Refuse("P1", "создание площадки под здание вернуло null"); }
        try { Parameter __cm = __el_P1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:7eb5da62:P1"); } catch { }

        doc.Regenerate();

        // post P1
        {
            Parameter __lp = __el_P1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_P1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_P1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_P1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("P1: level binding mismatch (topology)");
            double __bx0_P1 = 0;
            double __bx1_P1 = 0;
            double __by0_P1 = 0;
            double __by1_P1 = 0;
            bool __bany_P1 = false;
            var __bnd_P1 = __el_P1.GetBoundary();
            if (__bnd_P1 != null)
                foreach (CurveLoop __bcl_P1 in __bnd_P1)
                    foreach (Curve __bc_P1 in __bcl_P1)
                        foreach (XYZ __bt_P1 in __bc_P1.Tessellate())
                        {
                            double __bmx_P1 = MM(__bt_P1.X);
                            double __bmy_P1 = MM(__bt_P1.Y);
                            if (!__bany_P1)
                            {
                                __bx0_P1 = __bmx_P1;
                                __bx1_P1 = __bmx_P1;
                                __by0_P1 = __bmy_P1;
                                __by1_P1 = __bmy_P1;
                                __bany_P1 = true;
                            }
                            else
                            {
                                if (__bmx_P1 < __bx0_P1) __bx0_P1 = __bmx_P1;
                                if (__bmx_P1 > __bx1_P1) __bx1_P1 = __bmx_P1;
                                if (__bmy_P1 < __by0_P1) __by0_P1 = __bmy_P1;
                                if (__bmy_P1 > __by1_P1) __by1_P1 = __bmy_P1;
                            }
                        }
            if (!__bany_P1)
                __post.Add("P1: GetBoundary() не вернул ни одной кривой (geometry)");
            else if (Math.Abs(__bx0_P1 - 2000.0) > 50.0 || Math.Abs(__bx1_P1 - 14000.0) > 50.0 ||
                     Math.Abs(__by0_P1 - 2000.0) > 50.0 || Math.Abs(__by1_P1 - 11000.0) > 50.0)
                __post.Add("P1: boundary bbox mismatch (geometry)");
            var __atid_P1 = __el_P1.AssociatedTopographySurfaceId;
            if (__atid_P1 == null || __atid_P1 == ElementId.InvalidElementId)
                __post.Add("P1: площадка не привязана к топоповерхности (topology)");
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

// witness P1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_P1.Id.ToString();
    try { __rb["host_topography_id"] = __el_P1.AssociatedTopographySurfaceId.ToString(); } catch { }
    try { var __stampParam = __el_P1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __tid = __el_P1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["P1"] = __rb;
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