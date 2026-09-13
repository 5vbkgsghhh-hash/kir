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
BeamSystem __el_BS1 = null;
ElementId __syid_BS1 = null;
BeamSystem __el_BS2 = null;
ElementId __syid_BS2 = null;
Autodesk.Revit.DB.Structure.Truss __el_TR1 = null;
double __z_TR1 = 0;
ElementId __tyid_TR1 = null;
Autodesk.Revit.DB.Structure.Truss __el_TR2 = null;
double __z_TR2 = 0;
ElementId __tyid_TR2 = null;
FamilyInstance __el_B1 = null;
using (Transaction __t = new Transaction(doc, "KIR: пролёт: две балочные системы, две фермы и балка"))
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
        // create_beam_system BS1
        FamilySymbol __sy_BS1 = doc.GetElement(new ElementId(1100)) as FamilySymbol;
        if (__sy_BS1 == null) { __t.RollBack(); return __Refuse("BS1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_BS1.IsActive) { __sy_BS1.Activate(); doc.Regenerate(); }
        { var __pt_BS1 = __sy_BS1.Family.FamilyPlacementType;
          if (__pt_BS1 != FamilyPlacementType.CurveDrivenStructural && __pt_BS1 != FamilyPlacementType.CurveBased) { __t.RollBack(); return __Refuse("BS1", "типоразмер балки размещается по точке (" + __pt_BS1.ToString() + "), а балочная система ставит балки по кривой — этим типом она построена быть не может"); } }
        __syid_BS1 = __sy_BS1.Id;
        Element __lv_raw_BS1 = doc.GetElement(new ElementId(42));
        Level __lv_BS1 = __lv_raw_BS1 as Level;
        if (__lv_BS1 == null) { __t.RollBack(); return __Refuse("BS1", (__lv_raw_BS1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_BS1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        double __z_BS1 = MM(__lv_BS1.Elevation);
        IList<Curve> __prof_BS1 = new List<Curve>();
        __prof_BS1.Add(Line.CreateBound(P(0.0, 0.0, __z_BS1), P(12000.0, 0.0, __z_BS1)));
        __prof_BS1.Add(Line.CreateBound(P(12000.0, 0.0, __z_BS1), P(12000.0, 6000.0, __z_BS1)));
        __prof_BS1.Add(Line.CreateBound(P(12000.0, 6000.0, __z_BS1), P(0.0, 6000.0, __z_BS1)));
        __prof_BS1.Add(Line.CreateBound(P(0.0, 6000.0, __z_BS1), P(0.0, 0.0, __z_BS1)));
        try { __el_BS1 = BeamSystem.Create(doc, __prof_BS1, __lv_BS1, 0, false); }
        catch (Exception __ex_BS1) { __t.RollBack(); return __Refuse("BS1", "BeamSystem.Create: " + __ex_BS1.Message); }
        if (__el_BS1 == null) { __t.RollBack(); return __Refuse("BS1", "BeamSystem.Create вернул null"); }
        try { __el_BS1.BeamType = __sy_BS1; }
        catch (Exception __exb_BS1) { __t.RollBack(); return __Refuse("BS1", "BeamSystem.BeamType: " + __exb_BS1.Message); }
        try { Parameter __cm = __el_BS1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:42dd3c42:BS1"); } catch { }

        // create_beam_system BS2
        FamilySymbol __sy_BS2 = doc.GetElement(new ElementId(1100)) as FamilySymbol;
        if (__sy_BS2 == null) { __t.RollBack(); return __Refuse("BS2", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_BS2.IsActive) { __sy_BS2.Activate(); doc.Regenerate(); }
        { var __pt_BS2 = __sy_BS2.Family.FamilyPlacementType;
          if (__pt_BS2 != FamilyPlacementType.CurveDrivenStructural && __pt_BS2 != FamilyPlacementType.CurveBased) { __t.RollBack(); return __Refuse("BS2", "типоразмер балки размещается по точке (" + __pt_BS2.ToString() + "), а балочная система ставит балки по кривой — этим типом она построена быть не может"); } }
        __syid_BS2 = __sy_BS2.Id;
        Element __lv_raw_BS2 = doc.GetElement(new ElementId(42));
        Level __lv_BS2 = __lv_raw_BS2 as Level;
        if (__lv_BS2 == null) { __t.RollBack(); return __Refuse("BS2", (__lv_raw_BS2 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_BS2) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        double __z_BS2 = MM(__lv_BS2.Elevation);
        IList<Curve> __prof_BS2 = new List<Curve>();
        __prof_BS2.Add(Line.CreateBound(P(0.0, 7000.0, __z_BS2), P(12000.0, 7000.0, __z_BS2)));
        __prof_BS2.Add(Line.CreateBound(P(12000.0, 7000.0, __z_BS2), P(12000.0, 12000.0, __z_BS2)));
        __prof_BS2.Add(Line.CreateBound(P(12000.0, 12000.0, __z_BS2), P(8000.0, 12000.0, __z_BS2)));
        __prof_BS2.Add(Line.CreateBound(P(8000.0, 12000.0, __z_BS2), P(8000.0, 15000.0, __z_BS2)));
        __prof_BS2.Add(Line.CreateBound(P(8000.0, 15000.0, __z_BS2), P(0.0, 15000.0, __z_BS2)));
        __prof_BS2.Add(Line.CreateBound(P(0.0, 15000.0, __z_BS2), P(0.0, 7000.0, __z_BS2)));
        try { __el_BS2 = BeamSystem.Create(doc, __prof_BS2, __lv_BS2, 0, false); }
        catch (Exception __ex_BS2) { __t.RollBack(); return __Refuse("BS2", "BeamSystem.Create: " + __ex_BS2.Message); }
        if (__el_BS2 == null) { __t.RollBack(); return __Refuse("BS2", "BeamSystem.Create вернул null"); }
        try { __el_BS2.BeamType = __sy_BS2; }
        catch (Exception __exb_BS2) { __t.RollBack(); return __Refuse("BS2", "BeamSystem.BeamType: " + __exb_BS2.Message); }
        try { Parameter __cm = __el_BS2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:42dd3c42:BS2"); } catch { }

        // create_truss TR1
        Autodesk.Revit.DB.Structure.TrussType __ty_TR1 = doc.GetElement(new ElementId(1600)) as Autodesk.Revit.DB.Structure.TrussType;
        if (__ty_TR1 == null) { __t.RollBack(); return __Refuse("TR1", "тип фермы не найден или не является TrussType (модель изменилась после grounding, либо id указывает не на тип фермы)"); }
        if (!__ty_TR1.IsActive) { __ty_TR1.Activate(); doc.Regenerate(); }
        __tyid_TR1 = __ty_TR1.Id;
        Element __lv_raw_TR1 = doc.GetElement(new ElementId(42));
        Level __lv_TR1 = __lv_raw_TR1 as Level;
        if (__lv_TR1 == null) { __t.RollBack(); return __Refuse("TR1", (__lv_raw_TR1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_TR1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        SketchPlane __sp_TR1 = SketchPlane.Create(doc, __lv_TR1.Id);
        if (__sp_TR1 == null) { __t.RollBack(); return __Refuse("TR1", "плоскость эскиза уровня не построена — ферме негде лежать"); }
        __z_TR1 = MM(__lv_TR1.Elevation);
        Line __base_TR1 = Line.CreateBound(P(0, 16000, __z_TR1), P(12000, 16000, __z_TR1));
        try { __el_TR1 = Autodesk.Revit.DB.Structure.Truss.Create(doc, __tyid_TR1, __sp_TR1.Id, __base_TR1); }
        catch (Exception __ex_TR1) { __t.RollBack(); return __Refuse("TR1", "Truss.Create: " + __ex_TR1.Message); }
        if (__el_TR1 == null) { __t.RollBack(); return __Refuse("TR1", "Truss.Create вернул null"); }
        try { Parameter __cm = __el_TR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:42dd3c42:TR1"); } catch { }

        // create_truss TR2
        Autodesk.Revit.DB.Structure.TrussType __ty_TR2 = doc.GetElement(new ElementId(1600)) as Autodesk.Revit.DB.Structure.TrussType;
        if (__ty_TR2 == null) { __t.RollBack(); return __Refuse("TR2", "тип фермы не найден или не является TrussType (модель изменилась после grounding, либо id указывает не на тип фермы)"); }
        if (!__ty_TR2.IsActive) { __ty_TR2.Activate(); doc.Regenerate(); }
        __tyid_TR2 = __ty_TR2.Id;
        Element __lv_raw_TR2 = doc.GetElement(new ElementId(42));
        Level __lv_TR2 = __lv_raw_TR2 as Level;
        if (__lv_TR2 == null) { __t.RollBack(); return __Refuse("TR2", (__lv_raw_TR2 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_TR2) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        SketchPlane __sp_TR2 = SketchPlane.Create(doc, __lv_TR2.Id);
        if (__sp_TR2 == null) { __t.RollBack(); return __Refuse("TR2", "плоскость эскиза уровня не построена — ферме негде лежать"); }
        __z_TR2 = MM(__lv_TR2.Elevation);
        Line __base_TR2 = Line.CreateBound(P(0, 19000, __z_TR2), P(12000, 19000, __z_TR2));
        try { __el_TR2 = Autodesk.Revit.DB.Structure.Truss.Create(doc, __tyid_TR2, __sp_TR2.Id, __base_TR2); }
        catch (Exception __ex_TR2) { __t.RollBack(); return __Refuse("TR2", "Truss.Create: " + __ex_TR2.Message); }
        if (__el_TR2 == null) { __t.RollBack(); return __Refuse("TR2", "Truss.Create вернул null"); }
        try { Parameter __cm = __el_TR2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:42dd3c42:TR2"); } catch { }

        // create_beam B1
        FamilySymbol __sy_B1 = doc.GetElement(new ElementId(1100)) as FamilySymbol;
        if (__sy_B1 == null) { __t.RollBack(); return __Refuse("B1", "типоразмер не найден (модель изменилась после grounding)"); }
        if (!__sy_B1.IsActive) { __sy_B1.Activate(); doc.Regenerate(); }
        Element __lv_raw_B1 = doc.GetElement(new ElementId(42));
        Level __lv_B1 = __lv_raw_B1 as Level;
        if (__lv_B1 == null) { __t.RollBack(); return __Refuse("B1", (__lv_raw_B1 == null ? "уровень не найден (модель изменилась после grounding)" : "id уровня резолвится не в Level, а в " + __ClassName(__lv_raw_B1) + " — причина (дрейф модели или неверный id) не определена рантаймом")); }
        Line __ln_B1 = Line.CreateBound(P(0, 22000, 3000), P(12000, 22000, 3000));
        __el_B1 = doc.Create.NewFamilyInstance(__ln_B1, __sy_B1, __lv_B1, Autodesk.Revit.DB.Structure.StructuralType.Beam);
        if (__el_B1 == null) { __t.RollBack(); return __Refuse("B1", "NewFamilyInstance (балка) вернул null"); }
        try { Parameter __cm = __el_B1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__cm != null && !__cm.IsReadOnly) __cm.Set("kir:42dd3c42:B1"); } catch { }

        doc.Regenerate();

        // post BS1
        {
            string __slf_BS1 = null;
            try
            {
                var __slL_BS1 = new List<List<Curve>>();
                var __slE_BS1 = doc.GetElement(__el_BS1.Id) as BeamSystem;
                CurveArray __slA_BS1 = __slE_BS1 == null ? null : __slE_BS1.Profile;
                if (__slA_BS1 == null || __slA_BS1.Size == 0) __slL_BS1 = null;
                else
                {
                    var __slO_BS1 = new List<Curve>();
                    foreach (Curve __slX_BS1 in __slA_BS1) __slO_BS1.Add(__slX_BS1);
                    __slL_BS1.Add(__slO_BS1);
                }
                if (__slL_BS1 != null)
                {
                    var __slr_BS1 = new List<string>();
                    foreach (var __slc_BS1 in __slL_BS1)
                    {
                        var __slv_BS1 = new List<long[]>();
                        foreach (Curve __slq_BS1 in __slc_BS1)
                        {
                            XYZ __slp_BS1 = __slq_BS1.GetEndPoint(0);
                            __slv_BS1.Add(new long[] { __KirCanonUnit(MM(__slp_BS1.X), 1.0), __KirCanonUnit(MM(__slp_BS1.Y), 1.0) });
                        }
                        __slv_BS1.Sort(__KirCanonCmp);
                        var __slb_BS1 = new StringBuilder();
                        for (int __sli_BS1 = 0; __sli_BS1 < __slv_BS1.Count; __sli_BS1++)
                        {
                            if (__sli_BS1 > 0) __slb_BS1.Append('|');
                            __slb_BS1.Append(__slv_BS1[__sli_BS1][0].ToString(System.Globalization.CultureInfo.InvariantCulture));
                            __slb_BS1.Append(',');
                            __slb_BS1.Append(__slv_BS1[__sli_BS1][1].ToString(System.Globalization.CultureInfo.InvariantCulture));
                        }
                        __slr_BS1.Add(__slb_BS1.ToString());
                    }
                    __slr_BS1.Sort(StringComparer.Ordinal);
                    __slf_BS1 = string.Join(";", __slr_BS1);
                }
            }
            catch (Exception) { __slf_BS1 = null; }
            if (__slf_BS1 == null)
                __post.Add("BS1: профиль построенного элемента не прочитан(ы) — форма НЕ ПРОВЕРЕНА (geometry)");
            else if (__slf_BS1 != "0,0|0,6000|12000,0|12000,6000")
                __post.Add("BS1: sketch loops mismatch, expected 1 loop(s) (geometry)");
            { var __rdp_BS1 = doc.GetElement(__el_BS1.Id) as BeamSystem;
              CurveArray __pr_BS1 = __rdp_BS1 == null ? null : __rdp_BS1.Profile;
              if (__rdp_BS1 == null || __pr_BS1 == null || __pr_BS1.Size == 0)
                  __post.Add("BS1: профиль балочной системы не читается обратно (geometry)");
              else {
                  double __bx0_BS1 = double.MaxValue;
                  double __by0_BS1 = double.MaxValue;
                  double __bx1_BS1 = double.MinValue;
                  double __by1_BS1 = double.MinValue;
                  foreach (Curve __pc_BS1 in __pr_BS1)
                  {
                      for (int __pk_BS1 = 0; __pk_BS1 < 2; __pk_BS1++)
                      {
                          XYZ __pp_BS1 = __pc_BS1.GetEndPoint(__pk_BS1);
                          double __px_BS1 = MM(__pp_BS1.X);
                          double __py_BS1 = MM(__pp_BS1.Y);
                          if (__px_BS1 < __bx0_BS1) __bx0_BS1 = __px_BS1;
                          if (__px_BS1 > __bx1_BS1) __bx1_BS1 = __px_BS1;
                          if (__py_BS1 < __by0_BS1) __by0_BS1 = __py_BS1;
                          if (__py_BS1 > __by1_BS1) __by1_BS1 = __py_BS1;
                      }
                  }
                  if (Math.Abs(__bx0_BS1 - 0.0) > 50.0 || Math.Abs(__bx1_BS1 - 12000.0) > 50.0
                      || Math.Abs(__by0_BS1 - 0.0) > 50.0 || Math.Abs(__by1_BS1 - 6000.0) > 50.0)
                      __post.Add("BS1: profile bbox mismatch (geometry)");
              } }
            { var __rdn_BS1 = doc.GetElement(__el_BS1.Id) as BeamSystem;
              if (__rdn_BS1 == null || __rdn_BS1.GetBeamIds() == null
                  || __rdn_BS1.GetBeamIds().Count == 0)
                  __post.Add("BS1: балочная система не положила ни одной балки (semantic)"); }
            { var __rdl_BS1 = doc.GetElement(__el_BS1.Id) as BeamSystem;
              if (__rdl_BS1 == null || __rdl_BS1.Level == null
                  || __rdl_BS1.Level.Id.ToString() != "42")
                  __post.Add("BS1: level binding mismatch (topology)"); }
            { var __rdt_BS1 = doc.GetElement(__el_BS1.Id) as BeamSystem;
              if (__rdt_BS1 == null || __rdt_BS1.BeamType == null
                  || __rdt_BS1.BeamType.Id.ToString() != __syid_BS1.ToString())
                  __post.Add("BS1: тип балки != запрошенного (semantic)"); }
        }
        // post BS2
        {
            string __slf_BS2 = null;
            try
            {
                var __slL_BS2 = new List<List<Curve>>();
                var __slE_BS2 = doc.GetElement(__el_BS2.Id) as BeamSystem;
                CurveArray __slA_BS2 = __slE_BS2 == null ? null : __slE_BS2.Profile;
                if (__slA_BS2 == null || __slA_BS2.Size == 0) __slL_BS2 = null;
                else
                {
                    var __slO_BS2 = new List<Curve>();
                    foreach (Curve __slX_BS2 in __slA_BS2) __slO_BS2.Add(__slX_BS2);
                    __slL_BS2.Add(__slO_BS2);
                }
                if (__slL_BS2 != null)
                {
                    var __slr_BS2 = new List<string>();
                    foreach (var __slc_BS2 in __slL_BS2)
                    {
                        var __slv_BS2 = new List<long[]>();
                        foreach (Curve __slq_BS2 in __slc_BS2)
                        {
                            XYZ __slp_BS2 = __slq_BS2.GetEndPoint(0);
                            __slv_BS2.Add(new long[] { __KirCanonUnit(MM(__slp_BS2.X), 1.0), __KirCanonUnit(MM(__slp_BS2.Y), 1.0) });
                        }
                        __slv_BS2.Sort(__KirCanonCmp);
                        var __slb_BS2 = new StringBuilder();
                        for (int __sli_BS2 = 0; __sli_BS2 < __slv_BS2.Count; __sli_BS2++)
                        {
                            if (__sli_BS2 > 0) __slb_BS2.Append('|');
                            __slb_BS2.Append(__slv_BS2[__sli_BS2][0].ToString(System.Globalization.CultureInfo.InvariantCulture));
                            __slb_BS2.Append(',');
                            __slb_BS2.Append(__slv_BS2[__sli_BS2][1].ToString(System.Globalization.CultureInfo.InvariantCulture));
                        }
                        __slr_BS2.Add(__slb_BS2.ToString());
                    }
                    __slr_BS2.Sort(StringComparer.Ordinal);
                    __slf_BS2 = string.Join(";", __slr_BS2);
                }
            }
            catch (Exception) { __slf_BS2 = null; }
            if (__slf_BS2 == null)
                __post.Add("BS2: профиль построенного элемента не прочитан(ы) — форма НЕ ПРОВЕРЕНА (geometry)");
            else if (__slf_BS2 != "0,7000|0,15000|8000,12000|8000,15000|12000,7000|12000,12000")
                __post.Add("BS2: sketch loops mismatch, expected 1 loop(s) (geometry)");
            { var __rdp_BS2 = doc.GetElement(__el_BS2.Id) as BeamSystem;
              CurveArray __pr_BS2 = __rdp_BS2 == null ? null : __rdp_BS2.Profile;
              if (__rdp_BS2 == null || __pr_BS2 == null || __pr_BS2.Size == 0)
                  __post.Add("BS2: профиль балочной системы не читается обратно (geometry)");
              else {
                  double __bx0_BS2 = double.MaxValue;
                  double __by0_BS2 = double.MaxValue;
                  double __bx1_BS2 = double.MinValue;
                  double __by1_BS2 = double.MinValue;
                  foreach (Curve __pc_BS2 in __pr_BS2)
                  {
                      for (int __pk_BS2 = 0; __pk_BS2 < 2; __pk_BS2++)
                      {
                          XYZ __pp_BS2 = __pc_BS2.GetEndPoint(__pk_BS2);
                          double __px_BS2 = MM(__pp_BS2.X);
                          double __py_BS2 = MM(__pp_BS2.Y);
                          if (__px_BS2 < __bx0_BS2) __bx0_BS2 = __px_BS2;
                          if (__px_BS2 > __bx1_BS2) __bx1_BS2 = __px_BS2;
                          if (__py_BS2 < __by0_BS2) __by0_BS2 = __py_BS2;
                          if (__py_BS2 > __by1_BS2) __by1_BS2 = __py_BS2;
                      }
                  }
                  if (Math.Abs(__bx0_BS2 - 0.0) > 50.0 || Math.Abs(__bx1_BS2 - 12000.0) > 50.0
                      || Math.Abs(__by0_BS2 - 7000.0) > 50.0 || Math.Abs(__by1_BS2 - 15000.0) > 50.0)
                      __post.Add("BS2: profile bbox mismatch (geometry)");
              } }
            { var __rdn_BS2 = doc.GetElement(__el_BS2.Id) as BeamSystem;
              if (__rdn_BS2 == null || __rdn_BS2.GetBeamIds() == null
                  || __rdn_BS2.GetBeamIds().Count == 0)
                  __post.Add("BS2: балочная система не положила ни одной балки (semantic)"); }
            { var __rdl_BS2 = doc.GetElement(__el_BS2.Id) as BeamSystem;
              if (__rdl_BS2 == null || __rdl_BS2.Level == null
                  || __rdl_BS2.Level.Id.ToString() != "42")
                  __post.Add("BS2: level binding mismatch (topology)"); }
            { var __rdt_BS2 = doc.GetElement(__el_BS2.Id) as BeamSystem;
              if (__rdt_BS2 == null || __rdt_BS2.BeamType == null
                  || __rdt_BS2.BeamType.Id.ToString() != __syid_BS2.ToString())
                  __post.Add("BS2: тип балки != запрошенного (semantic)"); }
        }
        // post TR1
        {
            var __lc = __el_TR1.Location as LocationCurve;
            if (__lc == null) __post.Add("TR1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 16000, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 16000, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 16000) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 12000) > 5.0 || Math.Abs(MM(__e1.Y) - 16000) > 5.0)
                    __post.Add("TR1: endpoints mismatch (geometry)");
            }
            { var __tz_TR1 = __el_TR1.Location as LocationCurve;
              if (__tz_TR1 == null)
                  __post.Add("TR1: нет LocationCurve (geometry)");
              else if (Math.Abs(MM(__tz_TR1.Curve.GetEndPoint(0).Z) - __z_TR1) > 5.0
                       || Math.Abs(MM(__tz_TR1.Curve.GetEndPoint(1).Z) - __z_TR1) > 5.0)
                  __post.Add("TR1: base elevation mismatch (geometry)"); }
            { var __rdt_TR1 = doc.GetElement(__el_TR1.Id);
              if (__rdt_TR1 == null || __rdt_TR1.GetTypeId() == null
                  || __rdt_TR1.GetTypeId().ToString() != __tyid_TR1.ToString())
                  __post.Add("TR1: тип фермы != запрошенного (semantic)"); }
            { var __rdm_TR1 = doc.GetElement(__el_TR1.Id) as Autodesk.Revit.DB.Structure.Truss;
              if (__rdm_TR1 == null || __rdm_TR1.Members == null
                  || __rdm_TR1.Members.Count == 0)
                  __post.Add("TR1: ферма не породила ни одного стержня (semantic)"); }
            { var __rl_TR1 = __el_TR1.get_Parameter(BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM);
              if (__rl_TR1 == null || __rl_TR1.AsElementId() == null
                  || __rl_TR1.AsElementId() == ElementId.InvalidElementId)
                  __post.Add("TR1: нет опорного уровня (topology)"); }
        }
        // post TR2
        {
            var __lc = __el_TR2.Location as LocationCurve;
            if (__lc == null) __post.Add("TR2: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 19000, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 19000, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 19000) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 12000) > 5.0 || Math.Abs(MM(__e1.Y) - 19000) > 5.0)
                    __post.Add("TR2: endpoints mismatch (geometry)");
            }
            { var __tz_TR2 = __el_TR2.Location as LocationCurve;
              if (__tz_TR2 == null)
                  __post.Add("TR2: нет LocationCurve (geometry)");
              else if (Math.Abs(MM(__tz_TR2.Curve.GetEndPoint(0).Z) - __z_TR2) > 5.0
                       || Math.Abs(MM(__tz_TR2.Curve.GetEndPoint(1).Z) - __z_TR2) > 5.0)
                  __post.Add("TR2: base elevation mismatch (geometry)"); }
            { var __rdt_TR2 = doc.GetElement(__el_TR2.Id);
              if (__rdt_TR2 == null || __rdt_TR2.GetTypeId() == null
                  || __rdt_TR2.GetTypeId().ToString() != __tyid_TR2.ToString())
                  __post.Add("TR2: тип фермы != запрошенного (semantic)"); }
            { var __rdm_TR2 = doc.GetElement(__el_TR2.Id) as Autodesk.Revit.DB.Structure.Truss;
              if (__rdm_TR2 == null || __rdm_TR2.Members == null
                  || __rdm_TR2.Members.Count == 0)
                  __post.Add("TR2: ферма не породила ни одного стержня (semantic)"); }
            { var __rl_TR2 = __el_TR2.get_Parameter(BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM);
              if (__rl_TR2 == null || __rl_TR2.AsElementId() == null
                  || __rl_TR2.AsElementId() == ElementId.InvalidElementId)
                  __post.Add("TR2: нет опорного уровня (topology)"); }
        }
        // post B1
        {
            var __lc = __el_B1.Location as LocationCurve;
            if (__lc == null) __post.Add("B1: нет LocationCurve");
            else
            {
                var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);
                double __da = Math.Pow(MM(__a.X) - 0, 2) + Math.Pow(MM(__a.Y) - 22000, 2) + Math.Pow(MM(__a.Z) - 3000, 2);
                double __db = Math.Pow(MM(__b.X) - 0, 2) + Math.Pow(MM(__b.Y) - 22000, 2) + Math.Pow(MM(__b.Z) - 3000, 2);
                var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;
                if (Math.Abs(MM(__e0.X) - 0) > 5.0 || Math.Abs(MM(__e0.Y) - 22000) > 5.0 ||
                    Math.Abs(MM(__e1.X) - 12000) > 5.0 || Math.Abs(MM(__e1.Y) - 22000) > 5.0 || Math.Abs(MM(__e0.Z) - 3000) > 5.0 || Math.Abs(MM(__e1.Z) - 3000) > 5.0)
                    __post.Add("B1: endpoints mismatch (geometry)");
            }
            { var __rl = __el_B1.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
              if (__rl == null || __rl.AsElementId() == null
                  || __rl.AsElementId() == ElementId.InvalidElementId)
                __post.Add("B1: нет опорного уровня (topology)"); }
            if (__el_B1.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Beam)
                __post.Add("B1: StructuralType != Beam (semantic)");
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

// witness BS1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_BS1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_BS1;
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
    try { var __stampParam = __el_BS1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_BS1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_BS1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __rb["direction_edge"] = 0;
    try { var __rbs_BS1 = doc.GetElement(__el_BS1.Id) as BeamSystem;
        if (__rbs_BS1 != null) {
            __rb["beam_count"] = __rbs_BS1.GetBeamIds().Count;
            __rb["elevation_mm"] = Math.Round(MM(__rbs_BS1.Elevation), 1);
            __rb["layout_rule"] = __rbs_BS1.LayoutRule.ToString();
            var __rbd_BS1 = __rbs_BS1.Direction;
            if (__rbd_BS1 != null) __rb["direction"] = new double[] {
                Math.Round(__rbd_BS1.X, 6), Math.Round(__rbd_BS1.Y, 6),
                Math.Round(__rbd_BS1.Z, 6) };
            if (__rbs_BS1.Level != null) __rb["level_name"] = __rbs_BS1.Level.Name;
            if (__rbs_BS1.BeamType != null) __rb["beam_type_name"] = __rbs_BS1.BeamType.Name;
        } } catch { }
    __results["BS1"] = __rb;
}

// witness BS2
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_BS2.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_BS2;
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
    try { var __stampParam = __el_BS2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_BS2.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_BS2.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    __rb["direction_edge"] = 0;
    try { var __rbs_BS2 = doc.GetElement(__el_BS2.Id) as BeamSystem;
        if (__rbs_BS2 != null) {
            __rb["beam_count"] = __rbs_BS2.GetBeamIds().Count;
            __rb["elevation_mm"] = Math.Round(MM(__rbs_BS2.Elevation), 1);
            __rb["layout_rule"] = __rbs_BS2.LayoutRule.ToString();
            var __rbd_BS2 = __rbs_BS2.Direction;
            if (__rbd_BS2 != null) __rb["direction"] = new double[] {
                Math.Round(__rbd_BS2.X, 6), Math.Round(__rbd_BS2.Y, 6),
                Math.Round(__rbd_BS2.Z, 6) };
            if (__rbs_BS2.Level != null) __rb["level_name"] = __rbs_BS2.Level.Name;
            if (__rbs_BS2.BeamType != null) __rb["beam_type_name"] = __rbs_BS2.BeamType.Name;
        } } catch { }
    __results["BS2"] = __rb;
}

// witness TR1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_TR1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_TR1;
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
    try { var __stampParam = __el_TR1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_TR1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_TR1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rbt_TR1 = doc.GetElement(__el_TR1.Id) as Autodesk.Revit.DB.Structure.Truss;
        if (__rbt_TR1 != null) {
            __rb["member_count"] = __rbt_TR1.Members.Count;
            if (__rbt_TR1.Curves != null) __rb["curve_count"] = __rbt_TR1.Curves.Size;
        }
        var __rlp_TR1 = __el_TR1.get_Parameter(BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM);
        if (__rlp_TR1 != null) {
            __rb["reference_level_id"] = __rlp_TR1.AsElementId().ToString();
            var __rle_TR1 = doc.GetElement(__rlp_TR1.AsElementId());
            if (__rle_TR1 != null) __rb["reference_level"] = __rle_TR1.Name;
        } } catch { }
    __results["TR1"] = __rb;
}

// witness TR2
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_TR2.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_TR2;
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
    try { var __stampParam = __el_TR2.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_TR2.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_TR2.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rbt_TR2 = doc.GetElement(__el_TR2.Id) as Autodesk.Revit.DB.Structure.Truss;
        if (__rbt_TR2 != null) {
            __rb["member_count"] = __rbt_TR2.Members.Count;
            if (__rbt_TR2.Curves != null) __rb["curve_count"] = __rbt_TR2.Curves.Size;
        }
        var __rlp_TR2 = __el_TR2.get_Parameter(BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM);
        if (__rlp_TR2 != null) {
            __rb["reference_level_id"] = __rlp_TR2.AsElementId().ToString();
            var __rle_TR2 = doc.GetElement(__rlp_TR2.AsElementId());
            if (__rle_TR2 != null) __rb["reference_level"] = __rle_TR2.Name;
        } } catch { }
    __results["TR2"] = __rb;
}

// witness B1
{
    var __rb = new Dictionary<string, object>();
    try { __rb["id"] = __el_B1.Id.ToString(); } catch { }
    __rb["element_identity"] = null;
    __rb["element_identity_status"] = "unavailable";
    __rb["element_identity_reason"] = "element_missing";
    try
    {
        Element __kirIdentityEl = __el_B1;
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
    try { var __stampParam = __el_B1.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); if (__stampParam != null) __rb["stamp"] = __stampParam.AsString(); } catch { }
    try { var __lc2 = __el_B1.Location as LocationCurve;
        if (__lc2 != null) {
            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);
            __rb["start_mm"] = new double[] { Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) };
            __rb["end_mm"] = new double[] { Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) };
        } } catch { }
    try { var __tid = __el_B1.GetTypeId();
        if (__tid != null && __tid != ElementId.InvalidElementId) {
            var __te = doc.GetElement(__tid);
            if (__te != null && __te.Name != null) __rb["type_name"] = __te.Name;
        } } catch { }
    try { var __rlp = __el_B1.get_Parameter(BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);
        if (__rlp != null) { var __rle = doc.GetElement(__rlp.AsElementId());
            __rb["reference_level_id"] = __rlp.AsElementId().ToString();
            if (__rle != null) __rb["reference_level"] = __rle.Name; } } catch { }
    __results["B1"] = __rb;
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