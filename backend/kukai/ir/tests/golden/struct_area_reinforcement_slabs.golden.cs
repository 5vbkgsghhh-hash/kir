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
Floor __el_SL1 = null;
Autodesk.Revit.DB.Structure.AreaReinforcement __el_AR1 = null;
ElementId __tyid_AR1 = null;
ElementId __btid_AR1 = null;
ElementId __hkid_AR1 = null;
Element __hh_AR1 = null;
Autodesk.Revit.DB.Structure.AreaReinforcement __el_AR2 = null;
ElementId __tyid_AR2 = null;
ElementId __btid_AR2 = null;
ElementId __hkid_AR2 = null;
Element __hh_AR2 = null;
using (Transaction __t = new Transaction(doc, "KIR: армирование двух плит одной программой"))
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
        // create_floor SL1
        FloorType __ft_SL1 = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.FloorType)) as FloorType;
        if (__ft_SL1 == null) { __t.RollBack(); return __Refuse("SL1", "в документе нет типа перекрытия по умолчанию"); }
        Element __lv_raw_SL1 = doc.GetElement(new ElementId(42));
        Level __lv_SL1 = __lv_raw_SL1 as Level;
        if (__lv_SL1 == null) { __t.RollBack(); return __Refuse("SL1", (__lv_raw_SL1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_SL1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        var __loops_SL1 = new List<CurveLoop>();
        CurveLoop __ol_SL1 = new CurveLoop();
        __ol_SL1.Append(Line.CreateBound(P(0, 0, 0), P(9000, 0, 0)));
        __ol_SL1.Append(Line.CreateBound(P(9000, 0, 0), P(9000, 6000, 0)));
        __ol_SL1.Append(Line.CreateBound(P(9000, 6000, 0), P(0, 6000, 0)));
        __ol_SL1.Append(Line.CreateBound(P(0, 6000, 0), P(0, 0, 0)));
        __loops_SL1.Add(__ol_SL1);
        __el_SL1 = Floor.Create(doc, __loops_SL1, __ft_SL1.Id, __lv_SL1.Id, true, null, 0.0);
        if (__el_SL1 == null) { __t.RollBack(); return __Refuse("SL1", "создание перекрытия вернуло null"); }
        try { Parameter __cm = __el_SL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:b232575f:SL1"); } catch { }

        // create_area_reinforcement AR1
        __tyid_AR1 = doc.GetDefaultElementTypeId(ElementTypeGroup.AreaReinforcementType);
        if (doc.GetElement(__tyid_AR1) as Autodesk.Revit.DB.Structure.AreaReinforcementType == null) { __t.RollBack(); return __Refuse("AR1", "тип армирования по области не найден (в документе нет типа по умолчанию, либо модель изменилась после grounding)"); }
        __btid_AR1 = new ElementId(1902);
        if (doc.GetElement(__btid_AR1) as Autodesk.Revit.DB.Structure.RebarBarType == null) { __t.RollBack(); return __Refuse("AR1", "тип стержня не найден или не является RebarBarType (модель изменилась после grounding)"); }
        __hkid_AR1 = ElementId.InvalidElementId;
        __hh_AR1 = __el_SL1;
        if (__hh_AR1 == null) { __t.RollBack(); return __Refuse("AR1", "носитель армирования не найден (модель изменилась после grounding)"); }
        if (!(__hh_AR1 is Floor)) { __t.RollBack(); return __Refuse("AR1", "носитель армирования по области должен быть перекрытием/плитой: у вертикального носителя главное направление лежит в ЕГО плоскости, и плановым углом direction_deg оно не задаётся — армирование стены этой операцией невыразимо"); }
        if (!Autodesk.Revit.DB.Structure.RebarHostData.IsValidHost(__hh_AR1)) { __t.RollBack(); return __Refuse("AR1", "носитель не может нести армирование (RebarHostData.IsValidHost = false): сделай перекрытие несущим или смени его материал на бетон"); }
        XYZ __dir_AR1 = new XYZ(1.0, 0.0, 0.0);
        try { __el_AR1 = Autodesk.Revit.DB.Structure.AreaReinforcement.Create(doc, __hh_AR1, __dir_AR1, __tyid_AR1, __btid_AR1, __hkid_AR1); }
        catch (Exception __ex_AR1) { __t.RollBack(); return __Refuse("AR1", "AreaReinforcement.Create: " + __ex_AR1.Message); }
        if (__el_AR1 == null) { __t.RollBack(); return __Refuse("AR1", "AreaReinforcement.Create вернул null"); }
        try { Parameter __cm = __el_AR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:b232575f:AR1"); } catch { }

        // create_area_reinforcement AR2
        __tyid_AR2 = new ElementId(1901);
        if (doc.GetElement(__tyid_AR2) as Autodesk.Revit.DB.Structure.AreaReinforcementType == null) { __t.RollBack(); return __Refuse("AR2", "тип армирования по области не найден (в документе нет типа по умолчанию, либо модель изменилась после grounding)"); }
        __btid_AR2 = new ElementId(1902);
        if (doc.GetElement(__btid_AR2) as Autodesk.Revit.DB.Structure.RebarBarType == null) { __t.RollBack(); return __Refuse("AR2", "тип стержня не найден или не является RebarBarType (модель изменилась после grounding)"); }
        __hkid_AR2 = new ElementId(1904);
        if (doc.GetElement(__hkid_AR2) as Autodesk.Revit.DB.Structure.RebarHookType == null) { __t.RollBack(); return __Refuse("AR2", "тип крюка не найден или не является RebarHookType (модель изменилась после grounding)"); }
        __hh_AR2 = doc.GetElement(new ElementId(8145901));
        if (__hh_AR2 == null) { __t.RollBack(); return __Refuse("AR2", "носитель армирования не найден (модель изменилась после grounding)"); }
        if (!(__hh_AR2 is Floor)) { __t.RollBack(); return __Refuse("AR2", "носитель армирования по области должен быть перекрытием/плитой: у вертикального носителя главное направление лежит в ЕГО плоскости, и плановым углом direction_deg оно не задаётся — армирование стены этой операцией невыразимо"); }
        if (!Autodesk.Revit.DB.Structure.RebarHostData.IsValidHost(__hh_AR2)) { __t.RollBack(); return __Refuse("AR2", "носитель не может нести армирование (RebarHostData.IsValidHost = false): сделай перекрытие несущим или смени его материал на бетон"); }
        XYZ __dir_AR2 = new XYZ(0.0, 1.0, 0.0);
        try { __el_AR2 = Autodesk.Revit.DB.Structure.AreaReinforcement.Create(doc, __hh_AR2, __dir_AR2, __tyid_AR2, __btid_AR2, __hkid_AR2); }
        catch (Exception __ex_AR2) { __t.RollBack(); return __Refuse("AR2", "AreaReinforcement.Create: " + __ex_AR2.Message); }
        if (__el_AR2 == null) { __t.RollBack(); return __Refuse("AR2", "AreaReinforcement.Create вернул null"); }
        try { Parameter __cm = __el_AR2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:b232575f:AR2"); } catch { }

        doc.Regenerate();

        // post SL1
        {
            Parameter __lp = __el_SL1.get_Parameter(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_SL1.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_SL1.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM);
            if (__lp == null || !__lp.HasValue || __lp.AsElementId() == null || __lp.AsElementId() == ElementId.InvalidElementId) __lp = __el_SL1.get_Parameter(BuiltInParameter.LEVEL_PARAM);
            if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != "42")
                __post.Add("SL1: level binding mismatch (topology)");
            var __struct = __el_SL1.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);
            if (__struct == null || __struct.AsInteger() != 1)
                __post.Add("SL1: structural flag mismatch (semantic)");
            var __bb = __el_SL1.get_BoundingBox(null);
            if (__bb == null) __post.Add("SL1: нет BoundingBox");
            else if (Math.Abs(MM(__bb.Min.X) - 0) > 50.0 || Math.Abs(MM(__bb.Max.X) - 9000) > 50.0 ||
                     Math.Abs(MM(__bb.Min.Y) - 0) > 50.0 || Math.Abs(MM(__bb.Max.Y) - 6000) > 50.0)
                __post.Add("SL1: bbox extents mismatch (geometry)");
        }
        // post AR1
        {
            { var __rdh_AR1 = doc.GetElement(__el_AR1.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              if (__rdh_AR1 == null)
                  __post.Add("AR1: созданный элемент не читается из документа как AreaReinforcement (topology)");
              else if (__rdh_AR1.GetHostId() == null
                       || __rdh_AR1.GetHostId() == ElementId.InvalidElementId
                       || __rdh_AR1.GetHostId().ToString() != __hh_AR1.Id.ToString())
                  __post.Add("AR1: GetHostId != носителя (topology)"); }
            { var __rdt_AR1 = doc.GetElement(__el_AR1.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              if (__rdt_AR1 == null || __rdt_AR1.GetTypeId() == null
                  || __rdt_AR1.GetTypeId().ToString() != __tyid_AR1.ToString())
                  __post.Add("AR1: тип армирования != запрошенного (semantic)"); }
            { var __rdb_AR1 = doc.GetElement(__el_AR1.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              var __rsb_AR1 = Autodesk.Revit.DB.Structure.ReinforcementSettings.GetReinforcementSettings(doc);
              if (__rsb_AR1 != null && __rsb_AR1.HostStructuralRebar
                  && (__rdb_AR1 == null || __rdb_AR1.GetRebarInSystemIds() == null
                      || __rdb_AR1.GetRebarInSystemIds().Count == 0))
                  __post.Add("AR1: армирование не положило ни одного стержня при включённой HostStructuralRebar (semantic)"); }
            { var __rdr_AR1 = doc.GetElement(__el_AR1.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              var __rss_AR1 = Autodesk.Revit.DB.Structure.ReinforcementSettings.GetReinforcementSettings(doc);
              if (__rdr_AR1 != null && __rss_AR1 != null && __rss_AR1.HostStructuralRebar)
              {
                  var __rbi_AR1 = __rdr_AR1.GetRebarInSystemIds();
                  if (__rbi_AR1 != null)
                  {
                      foreach (ElementId __rid_AR1 in __rbi_AR1)
                      {
                          var __rbe_AR1 = doc.GetElement(__rid_AR1) as Autodesk.Revit.DB.Structure.RebarInSystem;
                          if (__rbe_AR1 == null) continue;
                          if (__rbe_AR1.GetTypeId() == null
                              || __rbe_AR1.GetTypeId().ToString() != __btid_AR1.ToString())
                          {
                              __post.Add("AR1: тип стержня != запрошенного (semantic)");
                              break;
                          }
                      }
                  }
              } }
        }
        // post AR2
        {
            { var __rdh_AR2 = doc.GetElement(__el_AR2.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              if (__rdh_AR2 == null)
                  __post.Add("AR2: созданный элемент не читается из документа как AreaReinforcement (topology)");
              else if (__rdh_AR2.GetHostId() == null
                       || __rdh_AR2.GetHostId() == ElementId.InvalidElementId
                       || __rdh_AR2.GetHostId().ToString() != __hh_AR2.Id.ToString())
                  __post.Add("AR2: GetHostId != носителя (topology)"); }
            { var __rdt_AR2 = doc.GetElement(__el_AR2.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              if (__rdt_AR2 == null || __rdt_AR2.GetTypeId() == null
                  || __rdt_AR2.GetTypeId().ToString() != __tyid_AR2.ToString())
                  __post.Add("AR2: тип армирования != запрошенного (semantic)"); }
            { var __rdb_AR2 = doc.GetElement(__el_AR2.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              var __rsb_AR2 = Autodesk.Revit.DB.Structure.ReinforcementSettings.GetReinforcementSettings(doc);
              if (__rsb_AR2 != null && __rsb_AR2.HostStructuralRebar
                  && (__rdb_AR2 == null || __rdb_AR2.GetRebarInSystemIds() == null
                      || __rdb_AR2.GetRebarInSystemIds().Count == 0))
                  __post.Add("AR2: армирование не положило ни одного стержня при включённой HostStructuralRebar (semantic)"); }
            { var __rdr_AR2 = doc.GetElement(__el_AR2.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
              var __rss_AR2 = Autodesk.Revit.DB.Structure.ReinforcementSettings.GetReinforcementSettings(doc);
              if (__rdr_AR2 != null && __rss_AR2 != null && __rss_AR2.HostStructuralRebar)
              {
                  var __rbi_AR2 = __rdr_AR2.GetRebarInSystemIds();
                  if (__rbi_AR2 != null)
                  {
                      foreach (ElementId __rid_AR2 in __rbi_AR2)
                      {
                          var __rbe_AR2 = doc.GetElement(__rid_AR2) as Autodesk.Revit.DB.Structure.RebarInSystem;
                          if (__rbe_AR2 == null) continue;
                          if (__rbe_AR2.GetTypeId() == null
                              || __rbe_AR2.GetTypeId().ToString() != __btid_AR2.ToString())
                          {
                              __post.Add("AR2: тип стержня != запрошенного (semantic)");
                              break;
                          }
                      }
                  }
              } }
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

// witness SL1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_SL1.Id.ToString();
    try { var __stampParam = __el_SL1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_SL1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_SL1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __results["SL1"] = __rb;
}

// witness AR1
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_AR1.Id.ToString();
    try { var __stampParam = __el_AR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_AR1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_AR1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rba_AR1 = doc.GetElement(__el_AR1.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
        var __rbs_AR1 = Autodesk.Revit.DB.Structure.ReinforcementSettings.GetReinforcementSettings(doc);
        if (__rbs_AR1 != null) __rb["host_structural_rebar"] = __rbs_AR1.HostStructuralRebar;
        if (__rba_AR1 != null) {
            var __rbn_AR1 = __rba_AR1.GetRebarInSystemIds();
            if (__rbn_AR1 != null) __rb["bar_count"] = __rbn_AR1.Count;
            var __rbc_AR1 = __rba_AR1.GetBoundaryCurveIds();
            if (__rbc_AR1 != null) __rb["boundary_curve_count"] = __rbc_AR1.Count;
            var __rbd_AR1 = __rba_AR1.Direction;
            if (__rbd_AR1 != null) __rb["direction"] = new double[] {
                Math.Round(__rbd_AR1.X, 6), Math.Round(__rbd_AR1.Y, 6),
                Math.Round(__rbd_AR1.Z, 6) };
            var __rbt_AR1 = doc.GetElement(__rba_AR1.GetTypeId());
            if (__rbt_AR1 != null) __rb["type_name"] = __rbt_AR1.Name;
        }
        var __rbb_AR1 = doc.GetElement(__btid_AR1);
        if (__rbb_AR1 != null) __rb["bar_type_name"] = __rbb_AR1.Name;
    } catch { }
    __results["AR1"] = __rb;
}

// witness AR2
{
    var __rb = new Dictionary<string, object>();
    __rb["id"] = __el_AR2.Id.ToString();
    try { var __stampParam = __el_AR2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_AR2.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_AR2.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rba_AR2 = doc.GetElement(__el_AR2.Id) as Autodesk.Revit.DB.Structure.AreaReinforcement;
        var __rbs_AR2 = Autodesk.Revit.DB.Structure.ReinforcementSettings.GetReinforcementSettings(doc);
        if (__rbs_AR2 != null) __rb["host_structural_rebar"] = __rbs_AR2.HostStructuralRebar;
        if (__rba_AR2 != null) {
            var __rbn_AR2 = __rba_AR2.GetRebarInSystemIds();
            if (__rbn_AR2 != null) __rb["bar_count"] = __rbn_AR2.Count;
            var __rbc_AR2 = __rba_AR2.GetBoundaryCurveIds();
            if (__rbc_AR2 != null) __rb["boundary_curve_count"] = __rbc_AR2.Count;
            var __rbd_AR2 = __rba_AR2.Direction;
            if (__rbd_AR2 != null) __rb["direction"] = new double[] {
                Math.Round(__rbd_AR2.X, 6), Math.Round(__rbd_AR2.Y, 6),
                Math.Round(__rbd_AR2.Z, 6) };
            var __rbt_AR2 = doc.GetElement(__rba_AR2.GetTypeId());
            if (__rbt_AR2 != null) __rb["type_name"] = __rbt_AR2.Name;
        }
        var __rbb_AR2 = doc.GetElement(__btid_AR2);
        if (__rbb_AR2 != null) __rb["bar_type_name"] = __rbb_AR2.Name;
    } catch { }
    __results["AR2"] = __rb;
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