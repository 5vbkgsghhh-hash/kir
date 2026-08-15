"""datum_emit — эмиссия трёх операций волны «датумы» (парный файл к своим
записям в ops_authoring.py, ровно как arch_emit.py к ops_arch.py):

    create_multi_segment_grid   MultiSegmentGrid.Create
    create_extrusion_roof       doc.Create.NewExtrusionRoof (+ ReferencePlane)
    create_multistory_stairs    MultistoryStairs.Create + ConnectLevels

Своя зона волны: модуль не трогает ни один ops_*.py и ни один соседний
эмиттер. authoring.py получает аддитивно импорт и три строки в `_EMITTERS` —
тот же минимальный шов, которым подключились каркас (struct_emit) и
архитектура (arch_emit).

Переиспользовано ИМПОРТОМ, не копией: `_gid`, `_eid`, `_cs`, `_safe`,
`_level_expr`, `_stamp_block`, `_stamp_readback`, `_pt3`, `EMIT_UNSUPPORTED`
и публичная модель свидетеля `WitnessCheck`.

────────────────────────────────────────────────────────────────────────────
ЗАМЕР ПО ЭТАЛОННЫМ СБОРКАМ, А НЕ ПО ПАМЯТИ (09.08.2026)
────────────────────────────────────────────────────────────────────────────
Живой Roslyn на :52412 против настоящих RevitAPI.dll
(`~/.nuget/packages/revit_all_main_versions_api_x64/{2021..2026}`).  Каждая
строка — отдельная компиляция ТЕЛА, а не чтение XML: XML и DLL расходятся, и
судья здесь компилятор (RULE ZERO, «gate_runner — единственное доказательство,
что член существует»).

  ЕСТЬ на всех шести (6/6 OK):
    MultistoryStairs.Create(Stairs)                        -> MultistoryStairs
    MultistoryStairs.IsAcceptableForMultistoryStairs(Stairs) -> bool
    MultistoryStairs.ConnectLevels(ISet<ElementId>)
    MultistoryStairs.GetAllConnectedLevels()               -> ISet<ElementId>
    MultistoryStairs.CanConnectLevel(ElementId)            -> bool
    MultistoryStairs.GetStairsPlacementLevels(Stairs)
    MultiSegmentGrid.Create(Document,ElementId,CurveLoop,ElementId) -> ElementId
    MultiSegmentGrid.IsValidCurveLoop(CurveLoop)           -> bool
    MultiSegmentGrid.IsValidSketchPlaneId(Document,ElementId) -> bool
    MultiSegmentGrid.GetGridIds()                          -> ICollection<ElementId>
    ItemFactoryBase.NewReferencePlane(XYZ,XYZ,XYZ,View)    -> ReferencePlane
    ItemFactoryBase.NewReferencePlane2(XYZ,XYZ,XYZ,View)   -> ReferencePlane
    Creation.Document.NewExtrusionRoof(CurveArray,ReferencePlane,Level,
                                       RoofType,Double,Double) -> ExtrusionRoof
    ElementTypeGroup.GridType, ElementTypeGroup.RoofType
    ReferencePlane.Normal/.Direction/.GetPlane(), SketchPlane.Create(Document,Plane)
    Application.VertexTolerance

  НЕТ НИ НА ОДНОЙ ИЗ ШЕСТИ (0/6, CS1061 на всех):
    Stairs.SetMultistoryStairsPlacementLevels(ISet<ElementId>)
    MultistoryStairs.SetMultistoryStairsPlacementLevels(...)
    MultistoryStairs.GetMultistoryStairsPlacementLevels()

Последние три были названы в постановке задачи как «тот самый механизм».  Их
не существует, и это ГЛАВНЫЙ результат замера: настоящая пара — ЗАПИСЬ
`ConnectLevels(ISet<ElementId>)` и ЧТЕНИЕ `GetAllConnectedLevels()`.  Если бы
эмиссия была написана по постановке, она не собралась бы НИ НА ОДНОЙ версии;
если бы отказ был написан по постановке («члена нет с 2021»), он оболгал бы
API в обе стороны сразу.

────────────────────────────────────────────────────────────────────────────
ПОЧЕМУ ОПОРНАЯ ПЛОСКОСТЬ — НЕ ОПЕРАЦИЯ, А ДЕТАЛЬ ЭМИССИИ КРОВЛИ
────────────────────────────────────────────────────────────────────────────
Профиль выдавливания УЖЕ задаёт свою плоскость однозначно, поэтому вторым
авторским входом она могла бы только ПРОТИВОРЕЧИТЬ первому — а несогласие
двух входов, которое компилятор не может проверить без выдуманного допуска на
компланарность, есть молчаливо-неверный результат по построению; отдельная
операция `create_reference_plane` вдобавок была бы тёмной функцией, потому
что ни один оп реестра сегодня не принимает рабочую плоскость как вход.
"""
from __future__ import annotations

import math

from kukai.ir.authoring import (
    _cs, _eid, _gid, _level_expr, _pt3, _safe, _stamp_block, _stamp_readback,
    _target_res, EMIT_UNSUPPORTED,
)
from kukai.ir.diag import Diagnostic, KirRefusal
from kukai.ir.emit_model import WitnessCheck, tolerance
from kukai.ir.ground import IN_EMIT_DEFAULT
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt


def _mm(value: float) -> str:
    """Число мм в C#-литерал БЕЗ потери разрядов.

    `repr` питоновского float — кратчайшая запись, читающаяся обратно в тот
    же double.  Форматирование через `:.1f` (как в readback'ах, где число
    ПОКАЗЫВАЮТ) здесь было бы дефектом: координаты профиля считаются из
    единичного направления плоскости, и срезанные разряды увели бы точку с
    плоскости, в которой Revit обязан её найти.

    ``+ 0.0`` гасит ОТРИЦАТЕЛЬНЫЙ НОЛЬ, и только его: по IEEE 754
    ``-0.0 + 0.0 == 0.0``, а для любого другого значения это тождество.
    Нужно потому, что нормаль плоскости считается как ``(uy, -ux)``, и у
    оси, параллельной X, во второй координате законно получается ``-0.0`` —
    C# такой литерал принимает и считает им верно, но читатель золотого
    файла видит ``new XYZ(1.0, -0.0, 0.0)`` и тратит время на вопрос, не
    потерян ли где-то знак.  Разряды при этом не трогаются.
    """

    return repr(float(value) + 0.0)


# ───────────────────────────────────────────────────────────────────────────
# create_multi_segment_grid
# ───────────────────────────────────────────────────────────────────────────

def emit_multi_segment_grid(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic"):
    """Цепь осей из ОТКРЫТОЙ ломаной, одна ось на звено.

    Три отказа берутся у самого Revit, а не сочиняются нами:
    `IsValidCurveLoop` (цепь обязана быть открытой из отрезков и дуг),
    `IsValidSketchPlaneId` (плоскость обязана быть горизонтальной) и null от
    `Create`.  Спрашивать разрешение ПЕРЕД вызовом дешевле, чем ловить
    ArgumentException: у отказа появляется имя, а не текст исключения.
    """
    oid = op["id"]
    s = _safe(oid)
    path = op["path"]
    nseg = len(path) - 1
    lv_res, _lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    # Кривые кладутся НА отметку уровня: четвёртый аргумент Create — id
    # горизонтального SketchPlane, и кривая вне своей плоскости — это не
    # «почти правильно», а другой объект.  Отметка приходит из Revit
    # (`Level.Elevation`, футы), поэтому Z нельзя набрать помощником P(),
    # который ждёт миллиметры: только U() по X/Y и сырые футы по Z.
    seg = []
    for k in range(nseg):
        a, b = path[k], path[k + 1]
        seg.append(
            f"__cl_{s}.Append(Line.CreateBound("
            f"new XYZ(U({_mm(a[0])}), U({_mm(a[1])}), __ze_{s}), "
            f"new XYZ(U({_mm(b[0])}), U({_mm(b[1])}), __ze_{s})));")

    decl = (f"MultiSegmentGrid __el_{s} = null; "
            f"SketchPlane __sp_{s} = null; double __ze_{s} = 0.0;")
    create = (
        f"// create_multi_segment_grid {cs_line_comment_fragment(oid)}\n"
        f"{lv_res}\n"
        f"__ze_{s} = __lv_{s}.Elevation;\n"
        f"__sp_{s} = SketchPlane.Create(doc, "
        f"Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0.0, 0.0, __ze_{s})));\n"
        f"if (__sp_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('SketchPlane.Create вернул null'), isolation)} }}\n"
        f"if (!MultiSegmentGrid.IsValidSketchPlaneId(doc, __sp_{s}.Id)) {{ "
        f"{refuse_stmt(oid, _cs('эскизный план уровня не признан горизонтальным — цепь осей на нём не строится'), isolation)} }}\n"
        f"CurveLoop __cl_{s} = new CurveLoop();\n"
        + "\n".join(seg) + "\n"
        f"if (!MultiSegmentGrid.IsValidCurveLoop(__cl_{s})) {{ "
        f"{refuse_stmt(oid, _cs('цепь не принята Revit: MultiSegmentGrid требует ОТКРЫТУЮ ломаную из отрезков и дуг (замкнутая или самопересекающаяся отвергается)'), isolation)} }}\n"
        f"ElementId __tid_{s} = doc.GetDefaultElementTypeId(ElementTypeGroup.GridType);\n"
        f"if (__tid_{s} == null || __tid_{s} == ElementId.InvalidElementId) {{ "
        f"{refuse_stmt(oid, _cs('в документе нет типа оси по умолчанию'), isolation)} }}\n"
        f"ElementId __nid_{s} = MultiSegmentGrid.Create(doc, __tid_{s}, __cl_{s}, __sp_{s}.Id);\n"
        f"if (__nid_{s} == null || __nid_{s} == ElementId.InvalidElementId) {{ "
        f"{refuse_stmt(oid, _cs('MultiSegmentGrid.Create не вернул id'), isolation)} }}\n"
        f"__el_{s} = doc.GetElement(__nid_{s}) as MultiSegmentGrid;\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('созданный элемент не перечитывается как MultiSegmentGrid'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    gtol = tolerance("create_multi_segment_grid", "endpoint_mm")
    xs0 = ", ".join(_mm(path[k][0]) for k in range(nseg))
    ys0 = ", ".join(_mm(path[k][1]) for k in range(nseg))
    xs1 = ", ".join(_mm(path[k + 1][0]) for k in range(nseg))
    ys1 = ", ".join(_mm(path[k + 1][1]) for k in range(nseg))

    # СОПОСТАВЛЕНИЕ МНОЖЕСТВ, А НЕ ИНДЕКСОВ.  Порядок `GetGridIds()` не
    # документирован ни в одной из шести версий, и свидетель, читающий i-ю
    # ось как i-е звено, проверял бы НАШУ догадку о порядке, а не постройку.
    # Каждая ось привязывается к ещё не занятому звену (в любой ориентации
    # концов — направление оси Revit выбирает сам), и требуется полное
    # паросочетание.
    post = [WitnessCheck(
        obligation_key="segment_count",
        reader_cs=(f"    var __ids_{s} = __el_{s} == null ? null : "
                   f"__el_{s}.GetGridIds();\n"),
        verdict_cs=(
            f"    if (__ids_{s} == null || __ids_{s}.Count != {nseg})\n"
            f"        __post.Add({_cs(oid + ': число осей в цепи не равно числу звеньев (geometry)')});\n"),
        message="число осей в цепи не равно числу звеньев (geometry)",
        style="guard"),
        WitnessCheck(
        obligation_key="endpoints",
        reader_cs=(
            f"    double[] __ax_{s} = new double[] {{ {xs0} }};\n"
            f"    double[] __ay_{s} = new double[] {{ {ys0} }};\n"
            f"    double[] __bx_{s} = new double[] {{ {xs1} }};\n"
            f"    double[] __by_{s} = new double[] {{ {ys1} }};\n"
            f"    bool[] __used_{s} = new bool[{nseg}];\n"
            f"    int __hit_{s} = 0;\n"),
        verdict_cs=(
            f"    if (__ids_{s} != null)\n"
            f"    {{\n"
            f"        foreach (ElementId __gid_{s} in __ids_{s})\n"
            f"        {{\n"
            f"            Grid __g_{s} = doc.GetElement(__gid_{s}) as Grid;\n"
            f"            if (__g_{s} == null || __g_{s}.Curve == null) continue;\n"
            f"            var __ga_{s} = __g_{s}.Curve.GetEndPoint(0);\n"
            f"            var __gb_{s} = __g_{s}.Curve.GetEndPoint(1);\n"
            f"            for (int __k_{s} = 0; __k_{s} < {nseg}; __k_{s}++)\n"
            f"            {{\n"
            f"                if (__used_{s}[__k_{s}]) continue;\n"
            f"                bool __fw_{s} = Math.Abs(MM(__ga_{s}.X) - __ax_{s}[__k_{s}]) <= {gtol}\n"
            f"                    && Math.Abs(MM(__ga_{s}.Y) - __ay_{s}[__k_{s}]) <= {gtol}\n"
            f"                    && Math.Abs(MM(__gb_{s}.X) - __bx_{s}[__k_{s}]) <= {gtol}\n"
            f"                    && Math.Abs(MM(__gb_{s}.Y) - __by_{s}[__k_{s}]) <= {gtol};\n"
            f"                bool __rv_{s} = Math.Abs(MM(__gb_{s}.X) - __ax_{s}[__k_{s}]) <= {gtol}\n"
            f"                    && Math.Abs(MM(__gb_{s}.Y) - __ay_{s}[__k_{s}]) <= {gtol}\n"
            f"                    && Math.Abs(MM(__ga_{s}.X) - __bx_{s}[__k_{s}]) <= {gtol}\n"
            f"                    && Math.Abs(MM(__ga_{s}.Y) - __by_{s}[__k_{s}]) <= {gtol};\n"
            f"                if (__fw_{s} || __rv_{s}) {{ __used_{s}[__k_{s}] = true; __hit_{s}++; break; }}\n"
            f"            }}\n"
            f"        }}\n"
            f"    }}\n"
            f"    if (__hit_{s} != {nseg})\n"
            f"        __post.Add({_cs(oid + ': концы звеньев цепи не совпали (geometry)')});\n"),
        message="концы звеньев цепи не совпали (geometry)",
        tol=gtol,
        style="guard")]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __rids_{s} = __el_{s}.GetGridIds();\n"
        f"        __rb[\"grid_count\"] = __rids_{s} == null ? 0 : __rids_{s}.Count;\n"
        f"        var __rn_{s} = new List<string>();\n"
        f"        if (__rids_{s} != null)\n"
        f"            foreach (ElementId __ri_{s} in __rids_{s})\n"
        f"            {{\n"
        f"                Grid __rg_{s} = doc.GetElement(__ri_{s}) as Grid;\n"
        f"                if (__rg_{s} != null) __rn_{s}.Add(__rg_{s}.Name);\n"
        f"            }}\n"
        f"        __rb[\"grid_names\"] = __rn_{s}.ToArray(); }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


# ───────────────────────────────────────────────────────────────────────────
# create_extrusion_roof
# ───────────────────────────────────────────────────────────────────────────

def emit_extrusion_roof(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic"):
    """Выдавленная кровля: профиль в вертикальной плоскости, ход по нормали.

    ЗНАК НОРМАЛИ РЕШАЕТСЯ В РАНТАЙМЕ, И ЭТО НЕ ПЕДАНТИЗМ.  `start`/`end`
    отмеряются «в направлении нормали плоскости», а какую из двух нормалей
    выберет Revit для только что созданной `ReferencePlane`, не сказано ни в
    XML, ни в DLL — это можно узнать только у самого объекта.  Поэтому
    эмиссия читает `ReferencePlane.Normal`, сравнивает с НАШЕЙ ориентацией
    (dir x Z) и при расхождении подаёт пару перевёрнутой.  Без этого кровля с
    вероятностью ~1/2 уезжала бы на другую сторону здания, а свидетель,
    считающий габарит по нормали Revit, этого бы НЕ ЗАМЕТИЛ: он мерил бы то
    же расстояние с той же стороны.
    """
    oid = op["id"]
    s = _safe(oid)
    g_type = (_gid(op, "type")
              if isinstance(op.get("type"), dict) and "__grounded__" in op["type"]
              else None)
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    x0, y0, _ = _pt3(op["p0_mm"])
    x1, y1, _ = _pt3(op["p1_mm"])
    profile = op["profile_mm"]
    start_mm = float(op["start_mm"])
    end_mm = float(op["end_mm"])

    # Единичное направление следа плоскости и НАША нормаль (dir x Z).
    # Невырожденность уже доказана законом «длина ~0» на разборе, поэтому
    # деления на ноль здесь быть не может.
    dx, dy = float(x1) - float(x0), float(y1) - float(y0)
    dlen = math.hypot(dx, dy)
    ux, uy = dx / dlen, dy / dlen
    nx, ny = uy, -ux

    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        rt = (f"RoofType __rt_{s} = doc.GetElement("
              f"doc.GetDefaultElementTypeId(ElementTypeGroup.RoofType)) as RoofType;\n"
              f"if (__rt_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('в документе нет типа кровли по умолчанию'), isolation)} }}")
    else:
        rt = (f"RoofType __rt_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as RoofType;\n"
              f"if (__rt_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('тип кровли не найден (модель изменилась после grounding)'), isolation)} }}")

    # Профиль в мировых мм: p0 + u*dir по плану, z — мировая отметка.  Точки
    # лежат в плоскости ТОЖДЕСТВЕННО, а не «в пределах допуска» — ровно ради
    # этого профиль и задан в координатах плоскости (см. ops_authoring.py).
    world = [(float(x0) + u * ux, float(y0) + u * uy, z) for u, z in profile]
    geo = [f"CurveArray __ca_{s} = new CurveArray();"]
    for k in range(len(world) - 1):
        a, b = world[k], world[k + 1]
        geo.append(
            f"__ca_{s}.Append(Line.CreateBound("
            f"P({_mm(a[0])}, {_mm(a[1])}, {_mm(a[2])}), "
            f"P({_mm(b[0])}, {_mm(b[1])}, {_mm(b[2])})));")

    decl = (f"ExtrusionRoof __el_{s} = null; ReferencePlane __rp_{s} = null; "
            f"XYZ __nrm_{s} = null; XYZ __org_{s} = null;")
    create = (
        f"// create_extrusion_roof {cs_line_comment_fragment(oid)}\n"
        f"{rt}\n{lv_res}\n"
        # Вид — ФОРМАЛЬНОСТЬ ровно для модельных видов, и это сказано в самой
        # документации метода: вид применяется к опорной плоскости ТОЛЬКО для
        # Legend / DraftingView / DrawingSheet.  На таком активном виде
        # плоскость стала бы видовой аннотацией, и кровля повисла бы на ней —
        # поэтому отказ типизированный и ДО создания чего бы то ни было, а не
        # «возьмём какой-нибудь другой вид» (вид, который автор не называл,
        # выбирать не наше дело).
        f"View __vw_{s} = doc.ActiveView;\n"
        f"if (__vw_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('активного вида нет — опорную плоскость не на чем создать'), isolation)} }}\n"
        f"if (__vw_{s}.ViewType == ViewType.Legend "
        f"|| __vw_{s}.ViewType == ViewType.DraftingView "
        f"|| __vw_{s}.ViewType == ViewType.DrawingSheet) {{ "
        f"{refuse_stmt(oid, _cs('активный вид — легенда, чертёжный вид или лист: на них опорная плоскость становится ВИДОВОЙ, и кровля привязалась бы к аннотации вместо модели; откройте модельный вид'), isolation)} }}\n"
        f"__org_{s} = P({_mm(x0)}, {_mm(y0)}, 0.0);\n"
        f"__rp_{s} = doc.Create.NewReferencePlane(__org_{s}, "
        f"P({_mm(x1)}, {_mm(y1)}, 0.0), XYZ.BasisZ, __vw_{s});\n"
        f"if (__rp_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('NewReferencePlane вернул null'), isolation)} }}\n"
        f"XYZ __rn_{s} = __rp_{s}.Normal;\n"
        f"if (__rn_{s} == null || __rn_{s}.GetLength() <= 0.0) {{ "
        f"{refuse_stmt(oid, _cs('у созданной опорной плоскости нет нормали — направление выдавливания неопределимо'), isolation)} }}\n"
        f"__rn_{s} = __rn_{s}.Normalize();\n"
        f"double __sg_{s} = __rn_{s}.DotProduct(new XYZ({_mm(nx)}, {_mm(ny)}, 0.0)) >= 0.0 ? 1.0 : -1.0;\n"
        f"__nrm_{s} = __sg_{s} > 0.0 ? __rn_{s} : __rn_{s}.Negate();\n"
        f"double __ea_{s} = __sg_{s} > 0.0 ? U({_mm(start_mm)}) : U({_mm(-end_mm)});\n"
        f"double __eb_{s} = __sg_{s} > 0.0 ? U({_mm(end_mm)}) : U({_mm(-start_mm)});\n"
        + "\n".join(geo) + "\n"
        f"__el_{s} = doc.Create.NewExtrusionRoof(__ca_{s}, __rp_{s}, __lv_{s}, "
        f"__rt_{s}, __ea_{s}, __eb_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('NewExtrusionRoof вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    post = [
        WitnessCheck(
            obligation_key="element_class",
            reader_cs=(f"    var __rr_{s} = __el_{s} == null ? null : "
                       f"doc.GetElement(__el_{s}.Id) as ExtrusionRoof;\n"),
            verdict_cs=(
                f"    if (__rr_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': элемент не перечитывается из документа как ExtrusionRoof (semantic)')});\n"),
            message="элемент не перечитывается из документа как ExtrusionRoof (semantic)",
            style="guard"),
        WitnessCheck(
            obligation_key="base_level",
            reader_cs=(f"    var __blp_{s} = __rr_{s} == null ? null : "
                       f"__rr_{s}.get_Parameter(BuiltInParameter.ROOF_BASE_LEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__blp_{s} == null || __blp_{s}.AsElementId() == null "
                f"|| __blp_{s}.AsElementId().ToString() != {lv_idexpr})\n"
                f"        __post.Add({_cs(oid + ': base level mismatch (topology)')});\n"),
            message="base level mismatch (topology)",
            style="guard"),
        # ДОПУСК ЧИТАЕТСЯ У ЖИВОГО ДОКУМЕНТА, А НЕ БЕРЁТСЯ ИЗ РЕЕСТРА.
        # `Application.VertexTolerance` — собственное утверждение Revit о том,
        # с какой точностью он хранит вершину.  Двойка перед ним ВЫВЕДЕНА, а
        # не подобрана: замеряется РАЗНОСТЬ двух проекций (max и min), и
        # погрешность каждой ограничена одной вершинной точностью, потому что
        # |e·n| <= |e| для единичной n.  Реестр этого числа не знает и не
        # должен: оно приходит от прибора, а не от нас (закон 4).
        WitnessCheck(
            obligation_key="extrusion_extent",
            reader_cs=(
                # ДВА ОТДЕЛЬНЫХ ОБЪЯВЛЕНИЯ, А НЕ ОДНО ЧЕРЕЗ ЗАПЯТУЮ.  C# принял
                # бы и `double __lo = a, __hi = b;` (живой Roslyn собрал 6/6),
                # но контракт области видимости читает объявления регулярным
                # выражением и видит в такой строке ТОЛЬКО первое имя — второе
                # он считает необъявленным.  Ослаблять прибор ради красоты
                # строки нельзя: он ловит настоящий CS0103 в per_op-изоляции.
                f"    double __lo_{s} = double.MaxValue;\n"
                f"    double __hi_{s} = double.MinValue;\n"
                f"    if (__rr_{s} != null && __nrm_{s} != null && __org_{s} != null)\n"
                f"    {{\n"
                f"        var __ge_{s} = __rr_{s}.get_Geometry(new Options());\n"
                f"        if (__ge_{s} != null)\n"
                f"            foreach (GeometryObject __go_{s} in __ge_{s})\n"
                f"            {{\n"
                f"                Solid __sd_{s} = __go_{s} as Solid;\n"
                f"                if (__sd_{s} == null || __sd_{s}.Faces.Size == 0) continue;\n"
                f"                foreach (Edge __ed_{s} in __sd_{s}.Edges)\n"
                f"                    foreach (XYZ __pt_{s} in __ed_{s}.Tessellate())\n"
                f"                    {{\n"
                f"                        double __dd_{s} = __pt_{s}.Subtract(__org_{s}).DotProduct(__nrm_{s});\n"
                f"                        if (__dd_{s} < __lo_{s}) __lo_{s} = __dd_{s};\n"
                f"                        if (__dd_{s} > __hi_{s}) __hi_{s} = __dd_{s};\n"
                f"                    }}\n"
                f"            }}\n"
                f"    }}\n"
                f"    double __vt_{s} = 2.0 * doc.Application.VertexTolerance;\n"),
            verdict_cs=(
                f"    if (__lo_{s} == double.MaxValue)\n"
                f"        __post.Add({_cs(oid + ': у кровли нет тела — выдавливание не замерить (geometry)')});\n"
                f"    else if (Math.Abs(__lo_{s} - U({_mm(start_mm)})) > __vt_{s}\n"
                f"          || Math.Abs(__hi_{s} - U({_mm(end_mm)})) > __vt_{s})\n"
                f"        __post.Add({_cs(oid + ': выдавливание не от start_mm до end_mm по нормали плоскости (geometry)')});\n"),
            message="выдавливание не от start_mm до end_mm по нормали плоскости (geometry)",
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __tid2_{s} = __el_{s}.GetTypeId();\n"
        f"        if (__tid2_{s} != null && __tid2_{s} != ElementId.InvalidElementId) {{\n"
        f"            var __te_{s} = doc.GetElement(__tid2_{s});\n"
        f"            if (__te_{s} != null && __te_{s}.Name != null) __rb[\"type_name\"] = __te_{s}.Name;\n"
        f"        }} }} catch {{ }}\n"
        # СЫРЬЁ ДЛЯ ПЕРВОГО ЖИВОГО УСТРОЙСТВА: какую нормаль выбрал Revit и
        # какую пару мы в итоге подали.  Ничем не ограждается — это ЗАПИСЬ
        # наблюдения, ровно как нечекнутые центр/радиус винтового марша у
        # create_stairs.
        f"    try {{ if (__rp_{s} != null) {{\n"
        f"        __rb[\"ref_plane_id\"] = __rp_{s}.Id.ToString();\n"
        f"        var __rpn_{s} = __rp_{s}.Normal;\n"
        f"        if (__rpn_{s} != null) __rb[\"ref_plane_normal\"] = new double[] {{\n"
        f"            Math.Round(__rpn_{s}.X, 6), Math.Round(__rpn_{s}.Y, 6), Math.Round(__rpn_{s}.Z, 6) }};\n"
        f"    }} }} catch {{ }}\n"
        f"    try {{ var __sp_{s} = __el_{s}.get_Parameter(BuiltInParameter.EXTRUSION_START_PARAM);\n"
        f"        var __ep_{s} = __el_{s}.get_Parameter(BuiltInParameter.EXTRUSION_END_PARAM);\n"
        f"        if (__sp_{s} != null) __rb[\"extrusion_start_mm\"] = Math.Round(MM(__sp_{s}.AsDouble()), 1);\n"
        f"        if (__ep_{s} != null) __rb[\"extrusion_end_mm\"] = Math.Round(MM(__ep_{s}.AsDouble()), 1);\n"
        f"    }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback


# ───────────────────────────────────────────────────────────────────────────
# create_multistory_stairs
# ───────────────────────────────────────────────────────────────────────────

def emit_multistory_stairs(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic"):
    """Один авторский марш, размноженный по названным уровням одним вызовом.

    ЧТО ЭТО МЕНЯЕТ СТРАТЕГИЧЕСКИ.  04.08.2026 записан вывод: многоэтажное
    здание непостроимо ОДНОЙ программой по построению, потому что
    `create_stairs` лежит в `spec.SOLO_OPS`.  Вывод верен ровно наполовину:
    марш действительно обязан быть единственным опом СВОЕЙ программы —
    `StairsEditScope` владеет своими транзакциями.  Но размножение марша по
    этажам `StairsEditScope` НЕ ТРЕБУЕТ: `MultistoryStairs.Create` и
    `ConnectLevels` — обычные документные вызовы.  Значит цена многоэтажки —
    ДВЕ программы (марш, затем всё остальное), а не по программе на этаж, и
    этот оп рядом с соседями законен.

    ИМЯ `__mst_` ВМЕСТО ОЧЕВИДНОГО `__st_` — НЕ ВКУС, А ЗАМЕР.  Первая
    редакция звала переменную лестницы `__st_<oid>`, и это ровно то имя,
    которым обёртка изоляции per_op называет СВОЮ `SubTransaction`
    (`authoring._wrap_create_per_op`).  В атомарной изоляции шва не видно
    вовсе; в per_op живой Roslyn дал CS0136 + CS0029 + CS1503 на ВСЕХ ШЕСТИ
    версиях.  Поймали не глаза и не тесты эмиссии, а ворота 6/6 — тот самый
    класс дефекта, ради которого они и стоят.

    ОГОВОРКА, КОТОРУЮ НЕ ЗАКРЫТЬ БЕЗ ЖИВОГО REVIT: что `MultistoryStairs.
    Create` не открывает собственный `StairsEditScope` внутри, компилятор
    проверить не может — это поведение, а не сигнатура.  Оп поэтому
    СОЗНАТЕЛЬНО не добавлен в `SOLO_OPS`: выдуманное ограничение стоило бы
    ровно того же, что выдуманный допуск.
    """
    oid = op["id"]
    s = _safe(oid)

    # ────────────────────────────────────────────────────────────────────
    # ОТКАЗ НА net48 (Revit 2021-2024) — ЗАМЕР, А НЕ ОСТОРОЖНОСТЬ.
    # 12.08.2026: ворота дают 6/6, а РАЗВЁРНУТЫЙ плагин это тело не соберёт.
    # Весь API многоэтажного марша типизирован
    # `System.Collections.Generic.ISet<ElementId>`:
    #     ConnectLevels(ISet<ElementId>)      DisconnectLevels(ISet<ElementId>)
    #     GetAllConnectedLevels() -> ISet     GetAllStairsIds() -> ISet
    #     GetStairsPlacementLevels(Stairs) -> ISet
    # (все шесть версий, замерено по индексу ловушек), и `ISet` тело называет
    # ещё и ЛИТЕРАЛОМ в объявлении `__add_<oid>`. Обойти нечем: ISet-свободного
    # пути к уровням у этого класса НЕТ ни одного.
    #
    # Причина ровно одна и она названа числом: замыкания ссылок клиента
    # различаются РОВНО ОДНОЙ сборкой —
    #     declared/net48  43 сборки, 3003 типа, `ISet` ЕСТЬ
    #     deployed/net48  42 сборки, 2007 типов, `ISet` НЕТ  (нет System.dll)
    # На net8 (2025/2026) `ISet` в замыкании есть, и там эмиссия законна.
    #
    # ЧИНИТЬ В ИСХОДНИКЕ НЕЧЕГО, И ЭТО ВАЖНО ДЛЯ МАРШРУТА. `CodeCompiler.cs` на
    # HEAD уже держит `System` в `allowedExactNames`, и его собственный
    # комментарий называет `ISet<>` первым же примером того, что даёт
    # `System.dll`. Расхождение — между HEAD и РАЗВЁРНУТЫМ ДВОИЧНЫМ ФАЙЛОМ, то
    # есть флот бежит на старом плагине. Профиль `deployed` — ЧЕСТНО НАЗВАННАЯ
    # ИНФЕРЕНЦИЯ по трём живым отказам 04.08.2026 (`Regex` дважды, `Stopwatch`
    # один раз, все с хвостом «forwarded to assembly 'System'»), а не снимок
    # чьей-то машины.
    #
    # ОТКАЗ ПОЭТОМУ ШИРЕ СВОЕЙ ПРИЧИНЫ, И ЭТО ОСОЗНАННО. Обновлённый клиент на
    # 2021-2024 `ISet` связал бы, и для него отказ ЛИШНИЙ. Но эмиттер не знает,
    # какой двоичный файл стоит у пользователя, а хвост необновлённых у нас
    # замерен и непуст. Выбор между «отказ кому-то лишний» и «CS0012 кому-то
    # молча» решается кардинальным инвариантом в одну сторону: названный отказ
    # с маршрутом, а не непонятная ошибка компиляции на чужой машине.
    #
    # УСЛОВИЕ СНЯТИЯ, чтобы отказ не пережил свою причину: строка уходит, когда
    # развёрнутый плагин начнёт связывать `ISet`. Судья — не память, а
    # `tests/bridge_reference_closure.py` (профиль `deployed`): как только
    # `ISet` появится в его индексе типов, проверка границы в
    # `kukai/ir/tests/test_datums_multistory_net48.py` покраснеет и потребует
    # решения.
    if ver < "2025":
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name="levels",
            message_ru=(
                f"create_multistory_stairs недоступен на Revit {ver}: весь API "
                f"многоэтажного марша типизирован ISet<ElementId>, а плагин, "
                f"развёрнутый на флоте, на net48 не связывает System.dll — "
                f"тело не соберётся у пользователя (CS0012), хотя собирается "
                f"у нас. МАРШРУТ, по убыванию силы: (1) обновить плагин Revit "
                f"— текущая сборка System.dll уже ссылается, и тогда оп "
                f"заработает на этой версии; (2) на Revit 2025/2026 оп "
                f"работает уже сейчас; (3) без обновления марш размножается "
                f"по этажам как отдельная программа create_stairs на каждый "
                f"уровень (create_stairs лежит в SOLO_OPS и обязан быть "
                f"единственным опом своей программы)"))])

    levels = [entry["__grounded__"] for entry in op["levels"]]
    lids = [lv["id"] for lv in levels]

    tg = _target_res({"target": op["stairs"]}, s, ver, oid, isolation)

    want = "\n".join(
        f"__want_{s}.Add({_eid(i, ver, oid)}.ToString());" for i in lids)
    connect = "\n".join(
        f"if (!__want2_{s}.Contains({_eid(i, ver, oid)}.ToString()))\n"
        f"{{\n"
        f"    if (!__el_{s}.CanConnectLevel({_eid(i, ver, oid)})) {{ "
        f"{refuse_stmt(oid, f'"Revit не подключает уровень {i} к этой многоэтажной лестнице (между базой и верхом обычного марша или уже подключён иначе)"', isolation)} }}\n"
        f"    __add_{s}.Add({_eid(i, ver, oid)});\n"
        f"}}" for i in lids)

    decl = (f"MultistoryStairs __el_{s} = null; "
            f"Autodesk.Revit.DB.Architecture.Stairs __mst_{s} = null; "
            f"HashSet<string> __want_{s} = new HashSet<string>();")
    create = (
        f"// create_multistory_stairs {cs_line_comment_fragment(oid)}\n"
        f"{tg}\n"
        f"__mst_{s} = __tg_{s} as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"if (__mst_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('указанный элемент — не лестница'), isolation)} }}\n"
        f"if (!Autodesk.Revit.DB.Architecture.MultistoryStairs"
        f".IsAcceptableForMultistoryStairs(__mst_{s})) {{ "
        f"{refuse_stmt(oid, _cs('Revit не принимает эту лестницу как основу многоэтажной (не компонентная либо уже входит в другую)'), isolation)} }}\n"
        f"{want}\n"
        f"__el_{s} = Autodesk.Revit.DB.Architecture.MultistoryStairs.Create(__mst_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('MultistoryStairs.Create вернул null'), isolation)} }}\n"
        f"doc.Regenerate();\n"
        # ЗАТРАВКА: уровни, которые Create занял САМ (как минимум базовый
        # уровень исходного марша).  Запрос, который их не называет, означал
        # бы ОТСОЕДИНЕНИЕ — намерения, которого автор не писал; отказ, а не
        # молчаливый DisconnectLevels.  Ровно на этом отказе стоит право
        # свидетеля требовать РАВЕНСТВА множеств вместо включения.
        f"var __want2_{s} = new HashSet<string>();\n"
        f"foreach (ElementId __sl_{s} in __el_{s}.GetAllConnectedLevels())\n"
        f"{{\n"
        f"    if (!__want_{s}.Contains(__sl_{s}.ToString())) {{ "
        f"{refuse_stmt(oid, f'"уровень " + __sl_{s}.ToString() + " лестница занимает уже сейчас, но в levels он не назван — отсоединение не запрашивалось"', isolation)} }}\n"
        f"    __want2_{s}.Add(__sl_{s}.ToString());\n"
        f"}}\n"
        f"System.Collections.Generic.ISet<ElementId> __add_{s} = "
        f"new HashSet<ElementId>();\n"
        f"{connect}\n"
        f"if (__add_{s}.Count > 0)\n"
        f"{{\n"
        f"    try {{ __el_{s}.ConnectLevels(__add_{s}); }}\n"
        f"    catch (Exception __ex_{s}) {{ "
        f"{refuse_stmt(oid, f'"ConnectLevels: " + __ex_{s}.Message', isolation)} }}\n"
        f"}}\n"
        f"doc.Regenerate();\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    post = [WitnessCheck(
        obligation_key="connected_levels",
        reader_cs=(
            f"    var __rr_{s} = __el_{s} == null ? null : "
            f"doc.GetElement(__el_{s}.Id) as MultistoryStairs;\n"
            f"    var __got_{s} = new HashSet<string>();\n"),
        verdict_cs=(
            f"    if (__rr_{s} == null)\n"
            f"        __post.Add({_cs(oid + ': элемент не перечитывается из документа как MultistoryStairs (semantic)')});\n"
            f"    else\n    {{\n"
            f"        foreach (ElementId __gl_{s} in __rr_{s}.GetAllConnectedLevels())\n"
            f"            __got_{s}.Add(__gl_{s}.ToString());\n"
            f"        if (!__got_{s}.SetEquals(__want_{s}))\n"
            f"            __post.Add({_cs(oid + ': множество уровней лестницы не совпало с запрошенным (topology)')});\n"
            f"    }}\n"),
        message="множество уровней лестницы не совпало с запрошенным (topology)",
        style="else_block")]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __rl_{s} = new List<string>();\n"
        f"        foreach (ElementId __wl_{s} in __el_{s}.GetAllConnectedLevels())\n"
        f"            __rl_{s}.Add(__wl_{s}.ToString());\n"
        f"        __rl_{s}.Sort();\n"
        f"        __rb[\"connected_level_ids\"] = __rl_{s}.ToArray(); }} catch {{ }}\n"
        f"    try {{ var __rs_{s} = __el_{s}.GetAllStairsIds();\n"
        f"        __rb[\"stairs_count\"] = __rs_{s} == null ? 0 : __rs_{s}.Count;\n"
        f"    }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, post, readback
