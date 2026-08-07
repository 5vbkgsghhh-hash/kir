"""room_emit — эмиссия create_room_separator (парный файл к ops_room.py).

Своя зона волны: этот модуль не трогает ни один другой ops_*.py и ни один
чужой *_emit.py. authoring.py получает аддитивно импорт-обёртку и одну строку
в _EMITTERS — тот же минимальный шов, которым подключились волны каркаса,
потолков и мешей.

Переиспользовано из authoring_emit_support.py БЕЗ ИЗМЕНЕНИЙ: _gid,
_eid, _cs, _safe, _level_expr, _stamp_block, _stamp_readback. Подчёркнутые
имена пока сохраняют исторический контракт, но имеют одного владельца.

═══ ЧТО ЗДЕСЬ ВИДНО В КОДЕ (обоснование формы — в шапке ops_room.py) ═══

* ПЛОСКОСТЬ БЕРЁТСЯ У УРОВНЯ, А НЕ СЧИТАЕТСЯ НАМИ.
  `SketchPlane.Create(doc, __lv.Id)` — перегрузка, документированная индексом
  ловушек как «sketch plane from a grid, reference plane, or LEVEL» (6/6).
  Альтернатива — `Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new XYZ(0,0,z))`
  с посчитанным нами z — завела бы ВТОРОГО СУДЬЮ о том, где находится
  уровень, и разошлась бы с ним на любой модели, где уровень сдвинули после
  grounding. Отметка точек кривых берётся тем же способом:
  `MM(__lv.Elevation)`, прочитанная в рантайме, а не число из эмиссии.

* ВИД ВЫВОДИТСЯ ИЗ УРОВНЯ, А НЕ БЕРЁТСЯ ИЗ doc.ActiveView.
  Третий аргумент NewRoomBoundaryLines — `View`. Взять `doc.ActiveView`
  значило бы поставить результат в зависимость от того, на что пользователь
  сейчас смотрит: тот самый молчаливый выбор, ради запрета которого написано
  НАЗВАННОЕ УМОЛЧАНИЕ (ground.py). Правило здесь ЗАКРЫТОЕ и детерминированное:
      план этажа (ViewType.FloorPlan), не шаблон (IsTemplate == false),
      чей GenLevel — РАЗРЕШЁННЫЙ уровень этой операции,
      с наименьшим ElementId среди подошедших.
  Вид, число кандидатов и имя выбранного УХОДЯТ В КВИТАНЦИЮ (`view_id`,
  `view_name`, `view_candidates`): умолчание названо ровно тогда, когда его
  видно снаружи. Кандидатов нет — типизированный отказ, а не догадка.

  ПОЧЕМУ ЭТО НЕ ЗАПРЕТИТЕЛЬНО. Разделитель существует потому, что его
  НАРИСОВАЛИ в плане; план того уровня есть по построению источника. На K2
  разделители лежат на 45 уровнях, и каждый из них — рабочий этаж с планом.

  ЧЕСТНЫЙ ОСТАТОК: ЧТО именно решает этот аргумент, офлайн непроверяемо —
  индекс ловушек хранит для метода только summary «Creates a new boundary
  line as an Room border» и две ловушки о принадлежности документу, ни слова
  о роли вида. Поэтому выбор сделан детерминированным и НАЗВАННЫМ, а
  правильность построенного доказывают свидетели ниже (категория, уровень,
  геометрия), а не наша вера в аргумент.

* КАТЕГОРИЯ СВЕРЯЕТСЯ ЧЕРЕЗ `Category.Id`, А НЕ ЧЕРЕЗ УДОБНЫЕ ЧЛЕНЫ.
  `Category.BuiltInCategory` существует только с 2023 (4/6), а
  `ElementId.IntegerValue` снят в 2026 (5/6, замерено: CS1061). Версионно
  безопасно ровно одно: сравнить `.Category.Id` с
  `new ElementId(BuiltInCategory.OST_RoomSeparationLines)` по строке.

* ОБЪЯВЛЕНИЯ — ВО ВНЕШНЕЙ ОБЛАСТИ. При isolation="per_op" блок создания и
  блок постусловий попадают в РАЗНЫЕ области видимости, и переменная,
  объявленная внутри create, свидетелю не видна (живые грабли волны
  ограждений: CS0103 на шести per_op-прогонах). Поэтому `__segs_`, `__rsv_`
  и `__rsvn_` объявлены в `decl`, а в `create` только присваиваются.
"""
from __future__ import annotations

from kukai.ir.authoring_emit_support import (
    _gid, _eid, _cs, _safe, _level_expr, _stamp_block, _stamp_readback,
)
from kukai.ir.emit_model import WitnessCheck, tolerance
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.ops_room import ROOM_SEPARATOR_CATEGORY

#: C#-выражение id категории разделителя. Строится ОДИН раз и используется и
#: в отказе выбора вида, и в свидетеле: два написания одной константы — это
#: два ответа на вопрос «что мы вообще строим».
_SEPARATOR_CATEGORY_CS = (
    f"new ElementId(BuiltInCategory.{ROOM_SEPARATOR_CATEGORY})")


def _view_pick_cs(s: str, oid: str, isolation: str) -> str:
    """Выбор плана уровня — закрытое правило, см. шапку модуля.

    Обход идёт по ВСЕМ планам документа, а не обрывается на первом подошедшем,
    ровно затем, чтобы посчитать кандидатов: число в квитанции — это и есть
    разница между «выбрали единственный» и «выбрали один из семи».
    """
    return (
        f"foreach (ViewPlan __vp_{s} in new FilteredElementCollector(doc)\n"
        f"        .OfClass(typeof(ViewPlan)).Cast<ViewPlan>())\n"
        f"{{\n"
        f"    if (__vp_{s}.IsTemplate) continue;\n"
        f"    if (__vp_{s}.ViewType != ViewType.FloorPlan) continue;\n"
        f"    Level __gl_{s} = null;\n"
        f"    try {{ __gl_{s} = __vp_{s}.GenLevel; }} catch {{ }}\n"
        f"    if (__gl_{s} == null "
        f"|| __gl_{s}.Id.ToString() != __lv_{s}.Id.ToString()) continue;\n"
        f"    __rsvn_{s}++;\n"
        f"    if (__rsv_{s} == null || __vp_{s}.Id < __rsv_{s}.Id) "
        f"__rsv_{s} = __vp_{s};\n"
        f"}}\n"
        f"if (__rsv_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs("разделитель помещений: у разрешённого уровня нет ни одного "
                "плана этажа (не шаблона), а NewRoomBoundaryLines требует "
                "вид — подставить чужой план значило бы нарисовать границу "
                "не на том этаже"),
            isolation)
        + " }")


def emit_room_separator(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Разделитель помещений ломаной по плоскости уровня.

    ``Autodesk.Revit.Creation.Document.NewRoomBoundaryLines(SketchPlane,
    CurveArray, View) -> ModelCurveArray`` — подтверждено индексом ловушек
    (6/6) и живой компиляцией на всех шести версиях. Оси версий у операции нет.
    """
    oid = op["id"]
    s = _safe(oid)
    path = op["path"]
    n_segments = len(path) - 1
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    # Кривые кладутся НА ОТМЕТКУ УРОВНЯ, прочитанную в рантайме: та же
    # плоскость, что у SketchPlane.Create(doc, levelId), иначе кривая не легла
    # бы на свой эскиз.
    geo = [f"double __z_{s} = MM(__lv_{s}.Elevation);",
           f"CurveArray __ca_{s} = new CurveArray();"]
    for k in range(n_segments):
        a, b = path[k], path[k + 1]
        geo.append(
            f"__ca_{s}.Append(Line.CreateBound("
            f"P({a[0]}, {a[1]}, __z_{s}), P({b[0]}, {b[1]}, __z_{s})));")

    decl = (f"List<ModelCurve> __segs_{s} = new List<ModelCurve>();\n"
            f"ViewPlan __rsv_{s} = null;\n"
            f"int __rsvn_{s} = 0;")

    create = (
        f"// create_room_separator {cs_line_comment_fragment(oid)}\n"
        f"{lv_res}\n"
        f"{_view_pick_cs(s, oid, isolation)}\n"
        f"SketchPlane __sp_{s} = SketchPlane.Create(doc, __lv_{s}.Id);\n"
        f"if (__sp_{s} == null) {{ "
        + refuse_stmt(oid, _cs("плоскость эскиза уровня не построена"),
                      isolation)
        + " }\n"
        + "\n".join(geo) + "\n"
        f"ModelCurveArray __mca_{s} = null;\n"
        f"try {{ __mca_{s} = doc.Create.NewRoomBoundaryLines("
        f"__sp_{s}, __ca_{s}, __rsv_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid,
                      f'"NewRoomBoundaryLines: " + __ex_{s}.Message',
                      isolation)
        + " }\n"
        f"if (__mca_{s} == null) {{ "
        + refuse_stmt(oid,
                      _cs("создание разделителя помещений вернуло null"),
                      isolation)
        + " }\n"
        # Каждый созданный сегмент — САМОСТОЯТЕЛЬНЫЙ элемент, и каждый обязан
        # быть проштампован: незаштампованный элемент для A5 — чужой, то есть
        # сирота, которую уборка не заберёт.
        f"foreach (ModelCurve __mc_{s} in __mca_{s})\n{{\n"
        f"    if (__mc_{s} == null) {{ "
        + refuse_stmt(oid,
                      _cs("созданный сегмент границы не читается как "
                          "ModelCurve"),
                      isolation)
        + " }\n"
        f"    " + _stamp_block(f"__mc_{s}", f"{stamp}:{oid}") + "\n"
        f"    __segs_{s}.Add(__mc_{s});\n}}\n"
        f"if (__segs_{s}.Count == 0) {{ "
        + refuse_stmt(oid,
                      _cs("создание разделителя помещений не вернуло ни "
                          "одного сегмента"),
                      isolation)
        + " }")

    tol = tolerance("create_room_separator", "endpoint_mm")
    # Ожидаемые пары концов — ровно те, что уехали в CurveArray. Список
    # строится ЗДЕСЬ из того же `path`, а не пересчитывается свидетелем из
    # C#: иначе проверка подтверждала бы наш собственный вызов, а не результат.
    expected = ", ".join(
        f"new double[] {{ {path[k][0]}, {path[k][1]}, "
        f"{path[k + 1][0]}, {path[k + 1][1]} }}"
        for k in range(n_segments))

    checks: list[WitnessCheck] = [
        # 1. СКОЛЬКО. Меньше — потеря, больше — мусор; и то и другое снаружи
        # выглядит успехом, потому что элемент-то создан.
        WitnessCheck(
            obligation_key="segment_count",
            reader_cs="",
            verdict_cs=(
                f"    if (__segs_{s}.Count != {n_segments})\n"
                f"        __post.Add({_cs(oid + ': room separator segment count mismatch (identity)')});\n"),
            message="room separator segment count mismatch (identity)",
            style="guard"),
        # 2. ЧТО ИМЕННО. Сердце операции: доказать, что построен РАЗДЕЛИТЕЛЬ, а
        # не обычная модельная линия. Линия «на том же месте» не ограничивает
        # ничего, и снаружи она неотличима от разделителя — ровно тот класс
        # подмены, за который волна потолков отказалась строить перекрытие.
        WitnessCheck(
            obligation_key="category",
            reader_cs=(
                f"    var __rsc_{s} = {_SEPARATOR_CATEGORY_CS}.ToString();\n"),
            verdict_cs=(
                f"    foreach (var __cs_{s} in __segs_{s})\n"
                f"        if (__cs_{s}.Category == null "
                f"|| __cs_{s}.Category.Id == null\n"
                f"            || __cs_{s}.Category.Id.ToString() != __rsc_{s})\n"
                f"            __post.Add({_cs(oid + ': сегмент не является разделителем помещений (topology)')});\n"),
            message="сегмент не является разделителем помещений (topology)",
            style="guard"),
        # 3. ГДЕ. Уровень читается ТЕМ ЖЕ Element.LevelId, которым его читает
        # сторона извлечения (revit_read_helpers: первое звено цепочки) — один
        # вопрос, один судья.
        WitnessCheck(
            obligation_key="level_binding",
            reader_cs="",
            verdict_cs=(
                f"    foreach (var __ls_{s} in __segs_{s})\n"
                f"        if (__ls_{s}.LevelId == null\n"
                f"            || __ls_{s}.LevelId == ElementId.InvalidElementId\n"
                f"            || __ls_{s}.LevelId.ToString() != {lv_idexpr})\n"
                f"            __post.Add({_cs(oid + ': level binding mismatch (topology)')});\n"),
            message="level binding mismatch (topology)",
            style="guard"),
        # 4. ТОЧНО ЛИ ТАМ. Концы сверяются НЕЗАВИСИМО ОТ ПОРЯДКА внутри
        # сегмента (Revit вправе развернуть кривую), но НЕ независимо от
        # порядка сегментов: перепутанные сегменты — другая ломаная.
        WitnessCheck(
            obligation_key="endpoints",
            reader_cs=(
                f"    var __exp_{s} = new List<double[]>() {{ {expected} }};\n"),
            verdict_cs=(
                f"    for (int __i_{s} = 0; "
                f"__i_{s} < Math.Min(__exp_{s}.Count, __segs_{s}.Count); "
                f"__i_{s}++)\n"
                f"    {{\n"
                f"        var __gc_{s} = __segs_{s}[__i_{s}].GeometryCurve;\n"
                f"        if (__gc_{s} == null) {{ "
                f"__post.Add({_cs(oid + ': сегмент без геометрии (geometry)')}); continue; }}\n"
                f"        var __e0_{s} = __gc_{s}.GetEndPoint(0);\n"
                f"        var __e1_{s} = __gc_{s}.GetEndPoint(1);\n"
                f"        var __w_{s} = __exp_{s}[__i_{s}];\n"
                f"        bool __fwd_{s} = "
                f"Math.Abs(MM(__e0_{s}.X) - __w_{s}[0]) <= {tol}\n"
                f"            && Math.Abs(MM(__e0_{s}.Y) - __w_{s}[1]) <= {tol}\n"
                f"            && Math.Abs(MM(__e1_{s}.X) - __w_{s}[2]) <= {tol}\n"
                f"            && Math.Abs(MM(__e1_{s}.Y) - __w_{s}[3]) <= {tol};\n"
                f"        bool __rev_{s} = "
                f"Math.Abs(MM(__e1_{s}.X) - __w_{s}[0]) <= {tol}\n"
                f"            && Math.Abs(MM(__e1_{s}.Y) - __w_{s}[1]) <= {tol}\n"
                f"            && Math.Abs(MM(__e0_{s}.X) - __w_{s}[2]) <= {tol}\n"
                f"            && Math.Abs(MM(__e0_{s}.Y) - __w_{s}[3]) <= {tol};\n"
                f"        if (!__fwd_{s} && !__rev_{s})\n"
                f"            __post.Add({_cs(oid + ': endpoints mismatch (geometry)')});\n"
                f"    }}\n"),
            message="endpoints mismatch (geometry)",
            tol=tol,
            # `plain`, а не `guard`/`else_block`: у проверки свободная форма —
            # читатель, цикл по сегментам и два булевых временных. Род стиля
            # ничего не меняет в рендере (байты несут сами фрагменты), он
            # существует ровно затем, чтобы аудит видел ФОРМУ проверки, а не
            # догадывался о ней.
            style="plain"),
    ]

    # Квитанция СВОЯ, а не _readback_block: тот сообщает РОВНО ОДИН id и
    # LocationCurve, а у этой операции личностей много и Location у сегмента
    # нет вовсе (ModelCurve носит геометрию в GeometryCurve). Здесь же
    # НАЗЫВАЕТСЯ выбор вида — умолчание, которого не видно, умолчанием не
    # является.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"segment_ids\"] = __segs_{s}.Select("
        f"__i => __i.Id.ToString()).ToArray();\n"
        f"    __rb[\"segment_count\"] = __segs_{s}.Count;\n"
        f"    __rb[\"view_id\"] = __rsv_{s}.Id.ToString();\n"
        f"    try {{ __rb[\"view_name\"] = __rsv_{s}.Name; }} catch {{ }}\n"
        f"    __rb[\"view_candidates\"] = __rsvn_{s};\n"
        + _stamp_readback(f"__segs_{s}[0]") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback
