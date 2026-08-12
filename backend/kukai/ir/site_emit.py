"""site_emit — эмиссия create_topography / create_building_pad /
create_site_subregion (парный файл к ops_site.py, ровно как arch_emit.py к
ops_arch.py и struct_emit.py к ops_struct.py).

Своя зона волны: модуль не трогает ни один другой ops_*.py и ни один другой
*_emit.py. authoring.py получает аддитивно импорт и три строки в _EMITTERS —
тот же минимальный шов, которым подключились волны каркаса и архитектуры.

Переиспользовано из authoring.py БЕЗ ИЗМЕНЕНИЙ (импортом, не копией): _gid,
_eid, _cs, _safe, _level_expr, _stamp_block, _stamp_readback, _readback_block,
EMIT_UNSUPPORTED, плюс ПУБЛИЧНЫЕ модели свидетелей
level_chain_witness и bbox_extents_witness. Оговорка та же, что в шапках
struct_emit.py и arch_emit.py: часть имён приватные, и чистый шов лечится
повышением их до публичных в authoring.py, а не копированием тел сюда.

ГЛАВНОЕ ОБ ЭТОМ ФАЙЛЕ — СВИДЕТЕЛИ, И У КАЖДОГО РАЗНАЯ СИЛА. Все три операции
читают РЕЗУЛЬТАТ, а не собственный вызов, но читают его по-разному, и разница
названа здесь, а не спрятана:

* поверхность рельефа — САМЫЙ СИЛЬНЫЙ свидетель во всём этом файле:
  `TopographySurface.GetPoints()` возвращает точки построенного элемента, и
  каждая описанная точка ищется среди них с допуском 1 мм. Это буквально
  «прочитай обратно то, что просил»;
* толща рельефа — слабее по построению: `Toposolid.GetPoints()` НЕ
  СУЩЕСТВУЕТ (CS1061 на 2024/2025/2026 — замерено). Уверенный предикат у неё
  габарит; поточечное чтение идёт через `GetSlabShapeEditor()`, и когда
  редактор формы недоступен, утверждение НЕ ДЕЛАЕТСЯ — квитанция сообщает
  `slab_shape_vertices: -1`, и это честнее, чем проверка, которая не может
  провалиться;
* площадка под здание — граница читается обратно (`GetBoundary()`), плюс
  `AssociatedTopographySurfaceId`: Revit ВЫЧИСЛЯЕТ его сам, значит это
  настоящее чтение результата, а не эхо нашего аргумента (аргумента-хозяина у
  BuildingPad.Create вообще нет);
* подобласть — `IsSiteSubRegion` у СОЗДАННОЙ поверхности: булев факт о
  результате, который наш вызов не записывал ни в один параметр.

ХОЗЯИН ПЛОЩАДКИ — ПРЕДПРОВЕРКА, А НЕ ИСКЛЮЧЕНИЕ. `BuildingPad.Create` на
всех шести версиях бросает InvalidOperationException «Cannot find an
appropriate hosting topography surface», если сажать площадку не на что.
Исключение Revit записывается конвейером как `internal` — то есть как «у нас
что-то сломалось», хотя на самом деле пользователю нужно СНАЧАЛА создать
рельеф. Поэтому перед вызовом стоит счётчик кандидатов в хозяева, и ноль —
типизированный отказ, НАЗЫВАЮЩИЙ следующий ход. Проверка НЕОБХОДИМАЯ, а не
достаточная, и это сказано вслух: ноль кандидатов означает отказ наверняка, а
ненулевое их число не обещает, что контур площадки попал внутрь чьих-то
границ (это решает Revit). Оставшийся случай так и остаётся исключением
Revit — но уже не тот, который можно было увидеть заранее.
"""
from __future__ import annotations

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _level_expr, _stamp_block, _stamp_readback,
    _readback_block, EMIT_UNSUPPORTED,
    level_chain_witness, bbox_extents_witness,
)
from kukai.ir.emit_model import WitnessCheck, tolerances
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import (
    Diagnostic, EMIT_UNSUPPORTED_ENUM, KirRefusal, PARSE_MISSING_FIELD)
from kukai.ir.ops_site import TOPOGRAPHY_VARIETIES, TOPOSOLID_MIN_VERSION

#: Разновидность рельефа вне закрытого множества {surface, toposolid}.
#: Ремень поверх подтяжек, ровно как RAILING_UNSUPPORTED_VARIETY у волны
#: архитектуры и FOUNDATION_UNSUPPORTED_KIND у каркаса: `enum`-choices уже
#: ловит это на authoring.validate(), а здесь стоит защита в глубину — тот,
#: кто расширит choices, не дописав ветку, упадёт ГРОМКО, а не построит молча
#: не то.


# ── общие помощники ──────────────────────────────────────────────────────────

def _points_cs(points: list, var: str) -> list[str]:
    """`List<XYZ>` из точек [x,y,z] мм — ОДИН источник для создания и для
    свидетеля.

    Массив НЕ дублируется в блоке постусловий: свидетель сравнивает
    прочитанные точки с этим же списком, поэтому переменная объявляется во
    ВНЕШНЕЙ области (см. контракт областей видимости в
    tests/test_emitter_scope_contract.py), а не `var`-ится внутри create.
    Вторая копия тех же чисел удвоила бы исходник и, что важнее, могла бы
    разъехаться с первой — а разъехавшийся свидетель ничего не значит.
    """
    out = [f"{var} = new List<XYZ>();"]
    for pt in points:
        out.append(f"{var}.Add(P({pt[0]}, {pt[1]}, {pt[2]}));")
    return out


def _xy_extents(points: list) -> tuple[float, float, float, float]:
    """(xmin, xmax, ymin, ymax) по точкам — вход свидетеля габарита."""
    xs = [pt[0] for pt in points]
    ys = [pt[1] for pt in points]
    return min(xs), max(xs), min(ys), max(ys)


def _host_readback(s: str, oid: str, stamp: str, host_expr: str,
                   type_name: bool = False) -> str:
    """Квитанция с ХОЗЯИНОМ, которого выбрал Revit, а не мы.

    Своя, а не `_readback_block`, ровно по одной причине, и она — закон, а не
    вкус: у площадки хозяина в подписи нет вообще, а у подобласти он
    НЕОБЯЗАТЕЛЕН, то есть в обоих случаях топоповерхность может выбрать сама
    Revit. Выбор, которого вызывающий не видит, — это `.FirstOrDefault()` с
    лучшей репутацией (замер 02.08: плечо C# молча взяло 1 тип двери из 62).
    Свидетель проверяет, что хозяин ЕСТЬ; квитанция говорит, КТО ИМЕННО, — и
    это разные обязанности, поэтому здесь id, а не вердикт.
    """
    tn = (f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
          f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
          f"            var __te = doc.GetElement(__tid);\n"
          f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
          f"        }} }} catch {{ }}\n") if type_name else ""
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    try {{ __rb[\"host_topography_id\"] = {host_expr}.ToString(); }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") + tn +
        f"    __results[{_cs(oid)}] = __rb;\n}}")


def _region_loops_cs(region: dict, s: str) -> list[str]:
    """`List<CurveLoop> __loops_<s>` из опущенного региона CONTOUR.

    Вся тригонометрия дуг посчитана в питоне на стадии ground: emit_loop_cs
    кладёт в C# три ЛИТЕРАЛЬНЫЕ точки на дугу (Arc.Create(start, end,
    точка-на-дуге), version-safe 2014+), поэтому версии здесь не расходятся.
    """
    from kukai.ir import contour as C
    out = [f"__loops_{s} = new List<CurveLoop>();",
           C.emit_loop_cs(region["outer"], f"__ol_{s}"),
           f"__loops_{s}.Add(__ol_{s});"]
    for hi, hole in enumerate(region["holes"]):
        out.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
        out.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
    return out


def _boundary_bbox_witness(bnd_expr: str, s: str, oid: str, region: dict,
                           tol, key: str) -> WitnessCheck:
    """Габарит ГРАНИЦЫ, прочитанной с построенного элемента.

    Читатель — не `get_BoundingBox` тела (у площадки он включает её толщину и
    вырез в рельефе), а сама граница: `GetBoundary()` -> `Curve.Tessellate()`.
    Это ровно тот эскиз, который мы передали, прочитанный обратно.

    Сверяется он с `contour.edges_bbox`, а не с вершинами: у дуги крайняя
    точка почти никогда не вершина, и edges_bbox добавляет кардинальные
    экстремумы (0/90/180/270°), попавшие внутрь развёртки. Сверять дуговую
    границу по вершинам значило бы обвинять правильно построенный элемент
    ровно на ту стрелку дуги, ради которой эскиз и взят.
    """
    from kukai.ir import contour as C
    x0, y0, x1, y1 = C.edges_bbox(region["outer"])
    xmin, xmax = round(x0, 1), round(x1, 1)
    ymin, ymax = round(y0, 1), round(y1, 1)
    return WitnessCheck(
        obligation_key=key,
        # ОДНО ОБЪЯВЛЕНИЕ НА СТРОКУ, а не `double a = 0, b = 0;`. Это не
        # стиль: контракт областей видимости
        # (tests/test_emitter_scope_contract.py) разбирает объявления
        # построчно, и вторая переменная в списке для него НЕ ОБЪЯВЛЕНА —
        # то есть весь блок читался бы как утечка за пределы decl. Прибор,
        # который не видит часть диапазона, опаснее отсутствующего, и здесь
        # дешевле подстроить эмиссию, чем разбор.
        reader_cs=(
            f"    double __bx0_{s} = 0;\n"
            f"    double __bx1_{s} = 0;\n"
            f"    double __by0_{s} = 0;\n"
            f"    double __by1_{s} = 0;\n"
            f"    bool __bany_{s} = false;\n"
            f"    var __bnd_{s} = {bnd_expr};\n"
            f"    if (__bnd_{s} != null)\n"
            f"        foreach (CurveLoop __bcl_{s} in __bnd_{s})\n"
            f"            foreach (Curve __bc_{s} in __bcl_{s})\n"
            f"                foreach (XYZ __bt_{s} in __bc_{s}.Tessellate())\n"
            f"                {{\n"
            f"                    double __bmx_{s} = MM(__bt_{s}.X);\n"
            f"                    double __bmy_{s} = MM(__bt_{s}.Y);\n"
            f"                    if (!__bany_{s})\n"
            f"                    {{\n"
            f"                        __bx0_{s} = __bmx_{s};\n"
            f"                        __bx1_{s} = __bmx_{s};\n"
            f"                        __by0_{s} = __bmy_{s};\n"
            f"                        __by1_{s} = __bmy_{s};\n"
            f"                        __bany_{s} = true;\n"
            f"                    }}\n"
            f"                    else\n"
            f"                    {{\n"
            f"                        if (__bmx_{s} < __bx0_{s}) __bx0_{s} = __bmx_{s};\n"
            f"                        if (__bmx_{s} > __bx1_{s}) __bx1_{s} = __bmx_{s};\n"
            f"                        if (__bmy_{s} < __by0_{s}) __by0_{s} = __bmy_{s};\n"
            f"                        if (__bmy_{s} > __by1_{s}) __by1_{s} = __bmy_{s};\n"
            f"                    }}\n"
            f"                }}\n"),
        verdict_cs=(
            f"    if (!__bany_{s})\n"
            f"        __post.Add({_cs(oid + ': GetBoundary() не вернул ни одной кривой (geometry)')});\n"
            f"    else if (Math.Abs(__bx0_{s} - {xmin}) > {tol} || Math.Abs(__bx1_{s} - {xmax}) > {tol} ||\n"
            f"             Math.Abs(__by0_{s} - {ymin}) > {tol} || Math.Abs(__by1_{s} - {ymax}) > {tol})\n"
            f"        __post.Add({_cs(oid + ': boundary bbox mismatch (geometry)')});\n"),
        message="boundary bbox mismatch (geometry)",
        tol=tol, style="else_block")


def _grounded_type_cs(op: dict, s: str, oid: str, ver: str, cs_class: str,
                      human: str, isolation: str) -> str:
    """Разрешение типа в переменную __ty_<s>.

    ВЕТКИ doc_default ЗДЕСЬ НЕТ, и у двух операций по РАЗНЫМ причинам —
    разница названа, потому что «нельзя» и «не стали» это не одно и то же:

    * у ТОЛЩИ РЕЛЬЕФА типа по умолчанию НЕ СУЩЕСТВУЕТ в API вовсе:
      `ElementTypeGroup.ToposolidType` не компилируется ни на одной из шести
      версий (CS0117 — замерено). Спросить документ невозможно по построению,
      ровно как у ограждения;
    * у ПЛОЩАДКИ ПОД ЗДАНИЕ он есть — `ElementTypeGroup.BuildingPadType`
      компилируется 6/6, и это стоит записать отдельно, потому что наша
      собственная база API (`data/revit_api_db.json`) его не знает, — но он
      сознательно НЕ используется, по той же причине, что у потолка
      (arch_emit._grounded_type_cs): «площадка по умолчанию» на чужом здании
      почти никогда не тот тип, что нужен, а подмена типа снаружи неотличима
      от успеха. Пропущенный `type` разрешает ground общим правилом
      «единственный в пуле, иначе типизированный вопрос с кандидатами», и
      этот вопрос автор увидит, в отличие от подстановки.

    Первая редакция этого файла ветку doc_default всё-таки несла — и была
    МЁРТВОЙ: `ground.py` выдаёт `in_emit=default` ровно четырём опам
    (стена/перекрытие/кровля/контурное перекрытие), а площадки среди них нет.
    Поймал это ЭТАЛОН: в сгенерированном C# стоял id из пула, а не вызов
    GetDefaultElementTypeId. Мёртвая ветка, выглядящая как поведение, — тот
    же класс, что «ссылка в пустоту» у create_type.
    """
    sel = op.get("type")
    g = _gid(op, "type") if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=(f"{human}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    return (f"{cs_class} __ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) "
            f"as {cs_class};\n"
            f"if (__ty_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs(human + ': тип не найден (модель изменилась после grounding)'), isolation)} }}")


# ── create_topography ────────────────────────────────────────────────────────

def _emit_topography_surface(op: dict, ver: str, stamp: str,
                             isolation: str) -> tuple[str, str, list, str]:
    """Поверхность рельефа, Revit 2021-2026.

    `TopographySurface.Create(doc, IList<XYZ>)` — 6/6. УРОВНЯ У НЕЁ НЕТ, и
    это не упущение подписи: отметка земли живёт в Z КАЖДОЙ точки, а не в
    привязке к этажу. Поэтому здесь нет ни `_level_expr`, ни свидетеля
    привязки — свидетель обязан подписывать ту ось, которую действительно
    читал, а привязки к уровню у этого элемента не существует.

    [Obsolete] с 2024, но `error=false`, и компайл-сервис собирает без
    предупреждений-как-ошибок (`CSharpCompilationOptions` без
    TreatWarningsAsErrors; собираются только `DiagnosticSeverity.Error` —
    проверено по RoslynCompiler.cs, а не предположено). Заменять её на
    Toposolid по номеру версии запрещено: это элемент ДРУГОЙ категории.
    """
    oid = op["id"]
    s = _safe(oid)
    points = op["points_mm"]
    tol = tolerances("create_topography")
    decl = (f"TopographySurface __el_{s} = null;\n"
            f"List<XYZ> __pts_{s} = null;")
    create = (f"// create_topography(surface) {cs_line_comment_fragment(oid)}\n"
              + "\n".join(_points_cs(points, f"__pts_{s}")) + "\n"
              f"__el_{s} = TopographySurface.Create(doc, __pts_{s});\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание поверхности рельефа вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xmin, xmax, ymin, ymax = _xy_extents(points)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            # ОБЩИЙ КЛЮЧ ОБЯЗАТЕЛЬСТВА У ОБЕИХ РАЗНОВИДНОСТЕЙ —
            # "terrain_points", то, что построенный элемент обязан вернуть:
            # поверхность отдаёт его через GetPoints(), толща — через
            # вершины редактора формы. Так сертификат перевода закрывает одно
            # обязательство любой из двух эмиссий, ровно как "anchor" у
            # create_railing и "footprint" у create_foundation.
            obligation_key="terrain_points",
            reader_cs=(f"    var __tp_{s} = __el_{s}.GetPoints();\n"
                       f"    int __miss_{s} = 0;\n"),
            verdict_cs=(
                f"    if (__tp_{s} == null || __tp_{s}.Count == 0)\n"
                f"        __post.Add({_cs(oid + ': GetPoints() не вернул ни одной точки (geometry)')});\n"
                f"    else\n"
                f"    {{\n"
                f"        foreach (XYZ __ep_{s} in __pts_{s})\n"
                f"        {{\n"
                f"            bool __hit_{s} = false;\n"
                f"            foreach (XYZ __q_{s} in __tp_{s})\n"
                f"                if (__ep_{s}.DistanceTo(__q_{s}) <= U({tol['point_mm']})) {{ __hit_{s} = true; break; }}\n"
                f"            if (!__hit_{s}) __miss_{s}++;\n"
                f"        }}\n"
                f"        if (__miss_{s} > 0)\n"
                f"            __post.Add(__miss_{s}.ToString() + \" из \" + __pts_{s}.Count.ToString() + \" \"\n"
                f"                + {_cs(oid + ': описанных точек рельефа нет в GetPoints() (geometry)')});\n"
                f"    }}\n"),
            message="описанных точек рельефа нет в GetPoints() (geometry)",
            tol=tol["point_mm"], style="else_block"),
        bbox_extents_witness(f"__el_{s}", oid, xmin, xmax, ymin, ymax,
                             tol["bbox_mm"]),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


def _emit_topography_toposolid(op: dict, ver: str, stamp: str,
                               isolation: str) -> tuple[str, str, list, str]:
    """Толща рельефа, Revit 2024-2026.

    `Toposolid.Create(doc, IList<XYZ>, ElementId typeId, ElementId levelId)` —
    2024/2025/2026, и НИ ОДНОЙ версией раньше (CS0246: типа `Toposolid` не
    существует). Уровень здесь ОБЯЗАТЕЛЕН самой подписью, в отличие от
    поверхности, — это и есть настоящее расхождение сигнатур, ради которого
    у операции появилась разновидность.

    ПОТОЧЕЧНОЕ ЧТЕНИЕ ЕСТЬ, НО СЛАБЕЕ. `Toposolid.GetPoints()` не существует
    (CS1061 на всех трёх версиях, где есть сам тип), поэтому точки читаются
    через `GetSlabShapeEditor().SlabShapeVertices` (обе строки компилируются,
    редактор — 2024+). Отдаст ли этот редактор непустой набор вершин у толщи,
    построенной ПО ТОЧКАМ, офлайн не проверяется никак: это факт живого
    Revit. Поэтому недоступный редактор здесь НЕ объявлен нарушением —
    утверждение просто не делается, а квитанция несёт
    `slab_shape_vertices: -1`, чтобы «не прочитали» не читалось как «сошлось».
    Уверенный предикат геометрии у толщи — габарит.
    """
    oid = op["id"]
    s = _safe(oid)
    points = op["points_mm"]
    tol = tolerances("create_topography")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    ty = _grounded_type_cs(op, s, oid, ver, "ToposolidType", "толща рельефа",
                           isolation)
    decl = (f"Toposolid __el_{s} = null;\n"
            f"List<XYZ> __pts_{s} = null;\n"
            f"int __vcnt_{s} = -1;")
    create = (f"// create_topography(toposolid) {cs_line_comment_fragment(oid)}\n"
              f"{ty}\n{lv_res}\n"
              + "\n".join(_points_cs(points, f"__pts_{s}")) + "\n"
              f"__el_{s} = Toposolid.Create(doc, __pts_{s}, __ty_{s}.Id, "
              f"__lv_{s}.Id);\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание толщи рельефа вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xmin, xmax, ymin, ymax = _xy_extents(points)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="terrain_points",   # см. комментарий в ветке surface
            reader_cs=(
                f"    SlabShapeEditor __sse_{s} = null;\n"
                f"    try {{ __sse_{s} = __el_{s}.GetSlabShapeEditor(); }} catch {{ }}\n"
                f"    var __sv_{s} = (__sse_{s} == null) ? null : __sse_{s}.SlabShapeVertices;\n"
                f"    __vcnt_{s} = (__sv_{s} == null) ? -1 : __sv_{s}.Size;\n"
                f"    int __miss_{s} = 0;\n"),
            verdict_cs=(
                # Утверждение делается ТОЛЬКО когда редактор формы прочитался.
                # Иначе оно не делается вовсе, и это видно в квитанции
                # (__vcnt_ == -1) — «не прочитали» не должно выглядеть как
                # «сошлось», но и обвинять правильную толщу за то, чего мы не
                # измеряли, нельзя.
                f"    if (__vcnt_{s} > 0)\n"
                f"    {{\n"
                f"        foreach (XYZ __ep_{s} in __pts_{s})\n"
                f"        {{\n"
                f"            bool __hit_{s} = false;\n"
                f"            foreach (SlabShapeVertex __sq_{s} in __sv_{s})\n"
                f"                if (__sq_{s}.Position.DistanceTo(__ep_{s}) <= U({tol['point_mm']})) {{ __hit_{s} = true; break; }}\n"
                f"            if (!__hit_{s}) __miss_{s}++;\n"
                f"        }}\n"
                f"        if (__miss_{s} > 0)\n"
                f"            __post.Add(__miss_{s}.ToString() + \" из \" + __pts_{s}.Count.ToString() + \" \"\n"
                f"                + {_cs(oid + ': описанных точек рельефа нет среди вершин формы толщи (geometry)')});\n"
                f"    }}\n"),
            message="описанных точек рельефа нет среди вершин формы толщи (geometry)",
            tol=tol["point_mm"], style="guard"),
        bbox_extents_witness(f"__el_{s}", oid, xmin, xmax, ymin, ymax,
                             tol["bbox_mm"]),
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
    ]
    # Квитанция своя, а не _readback_block: она обязана сказать, ПРОЧИТАЛСЯ ли
    # редактор формы. Число вершин здесь — данные наблюдения, а не вердикт.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"slab_shape_vertices\"] = __vcnt_{s};\n"
        f"    __rb[\"points_requested\"] = {len(points)};\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def emit_topography(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Развилка по закрытому множеству {surface, toposolid}.

    Здесь же — УСЛОВНО ОБЯЗАТЕЛЬНЫЕ поля, которые ParamSpec.required выразить
    не может по построению (`level`/`type` нужны только толще; статическое
    required=True требовало бы их у поверхности, которой уровня нет ВООБЩЕ).
    Тот же шов и та же причина, что у emit_foundation и emit_railing:
    типизированный KIR-P005 здесь, а не голый KeyError, который выше
    поймается как KIR-P000 «внутренняя ошибка» — fail-closed, но диагностика
    хуже.

    ОСЬ ВЕРСИЙ У ТОЛЩИ — ОТКАЗ, А НЕ РАЗВИЛКА, и отказ НАЗЫВАЕТ СЛЕДУЮЩИЙ
    ХОД. Свернуть на поверхность молча нельзя: у неё другая категория
    (OST_Topography против OST_Toposolid), другая привязка и другой
    свидетель, то есть это был бы другой элемент, выданный за запрошенный.
    """
    variety = op.get("variety")
    if variety == "surface":
        return _emit_topography_surface(op, ver, stamp, isolation)
    if variety == "toposolid":
        if ver < TOPOSOLID_MIN_VERSION:
            raise KirRefusal([Diagnostic(
                code=EMIT_UNSUPPORTED, op_id=op.get("id"), field_name="variety",
                got=variety, candidates=["surface"],
                message_ru=(
                    f"толща рельефа (Toposolid) не создаётся на Revit {ver}: "
                    f"тип появился только в {TOPOSOLID_MIN_VERSION} — "
                    f"замерено компиляцией на шести версиях. Следующий ход: "
                    f"variety=\"surface\" (TopographySurface, 2021-2026) — но "
                    f"это ДРУГОЙ элемент другой категории, поэтому подменить "
                    f"его за вас компилятор не станет"))])
        if op.get("level") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"),
                field_name="level",
                message_ru=("create_topography(variety=toposolid): level "
                            "обязателен — Toposolid.Create требует levelId, в "
                            "отличие от поверхности, у которой уровня нет "
                            "вовсе"))])
        return _emit_topography_toposolid(op, ver, stamp, isolation)
    raise KirRefusal([Diagnostic(
        code=EMIT_UNSUPPORTED_ENUM, op_id=op.get("id"),
        field_name="variety", got=variety, candidates=list(TOPOGRAPHY_VARIETIES),
        message_ru=(f"create_topography: разновидность {variety!r} не "
                    f"поддержана (в API ровно два элемента рельефа — "
                    f"поверхность и толща)"))])


# ── create_building_pad ──────────────────────────────────────────────────────

def _host_candidate_count_cs(s: str, ver: str) -> str:
    """C#-выражение «сколько в документе кандидатов в хозяева площадки».

    ВЕРСИЯ РАСХОДИТСЯ ЗДЕСЬ, и это не украшение: на 2024+ рельеф в документе
    может быть толщей, а типа `Toposolid` на 2021-2023 не существует вовсе
    (CS0246) — одна строка на все шесть версий не собралась бы. Считаются
    ЭКЗЕМПЛЯРЫ, а не типы (`WhereElementIsNotElementType`).
    """
    base = (f"int __hosts_{s} = new FilteredElementCollector(doc)"
            f".OfClass(typeof(TopographySurface)).WhereElementIsNotElementType()"
            f".GetElementCount();")
    if ver >= TOPOSOLID_MIN_VERSION:
        base += (f"\n__hosts_{s} += new FilteredElementCollector(doc)"
                 f".OfClass(typeof(Toposolid)).WhereElementIsNotElementType()"
                 f".GetElementCount();")
    return base


def emit_building_pad(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Площадка под здание по эскизу CONTOUR, Revit 2021-2026.

    `BuildingPad.Create(doc, ElementId typeId, ElementId levelId,
    IList<CurveLoop>)` — 6/6, никогда не [Obsolete]. Порядок аргументов
    именно такой (тип и уровень ПЕРЕД границей) — проверено компиляцией, а не
    восстановлено по памяти о соседних Create.

    ХОЗЯИНА В ПОДПИСИ НЕТ: Revit ищет топоповерхность сам и бросает
    InvalidOperationException, если не нашёл. Предпроверка кандидатов стоит
    ДО вызова именно поэтому — см. шапку модуля.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    tol = tolerances("create_building_pad")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    ty = _grounded_type_cs(op, s, oid, ver, "BuildingPadType",
                           "площадка под здание", isolation)
    decl = (f"BuildingPad __el_{s} = null;\n"
            f"List<CurveLoop> __loops_{s} = null;")
    create = (f"// create_building_pad {cs_line_comment_fragment(oid)}\n"
              f"{ty}\n{lv_res}\n"
              + _host_candidate_count_cs(s, ver) + "\n"
              f"if (__hosts_{s} == 0) {{ "
              + refuse_stmt(
                  oid,
                  _cs("площадку под здание не на что сажать: в документе нет "
                      "ни одной топоповерхности. Следующий ход — создать "
                      "рельеф операцией create_topography, и только потом "
                      "площадку (Revit ищет хозяина сам и без него бросает "
                      "«Cannot find an appropriate hosting topography "
                      "surface»)"),
                  isolation)
              + " }\n"
              + "\n".join(_region_loops_cs(region, s)) + "\n"
              f"__el_{s} = BuildingPad.Create(doc, __ty_{s}.Id, __lv_{s}.Id, "
              f"__loops_{s});\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание площадки под здание вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        _boundary_bbox_witness(f"__el_{s}.GetBoundary()", s, oid, region,
                               tol["bbox_mm"], "bbox"),
        WitnessCheck(
            # НАСТОЯЩЕЕ ЧТЕНИЕ РЕЗУЛЬТАТА, А НЕ ЭХО АРГУМЕНТА: хозяина мы не
            # передавали — его нашёл Revit, и вот его ответ. Проверка стоит
            # после doc.Regenerate() (эмиттер программы вставляет его между
            # созданиями и постусловиями), а сама привязка устанавливается
            # внутри Create: именно её отсутствие Create и превращает в
            # InvalidOperationException. Значит успешный Create + невалидный
            # id — это состояние, которого быть не должно, и молчать о нём
            # нельзя.
            obligation_key="hosting_topography",
            reader_cs=(f"    var __atid_{s} = __el_{s}.AssociatedTopographySurfaceId;\n"),
            verdict_cs=(
                f"    if (__atid_{s} == null || __atid_{s} == ElementId.InvalidElementId)\n"
                f"        __post.Add({_cs(oid + ': площадка не привязана к топоповерхности (topology)')});\n"),
            message="площадка не привязана к топоповерхности (topology)",
            style="guard"),
    ]
    return decl, create, checks, _host_readback(
        s, oid, stamp, f"__el_{s}.AssociatedTopographySurfaceId",
        type_name=True)


# ── create_site_subregion ────────────────────────────────────────────────────

def emit_site_subregion(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Подобласть площадки по эскизу CONTOUR, Revit 2021-2026.

    Две перегрузки, обе 6/6: `SiteSubRegion.Create(doc, IList<CurveLoop>)` —
    хозяина ищет Revit; `SiteSubRegion.Create(doc, IList<CurveLoop>,
    ElementId)` — хозяин назван. [Obsolete] с 2024 (как и
    TopographySurface.Create), но `error=false`.

    ГЛАВНАЯ ЛОВУШКА ЭТОГО ОПА: `SiteSubRegion` — НЕ `Element`. У него нет
    `.Id` и нет `get_Parameter` (CS1061/CS0029 на всех шести). Созданный
    ЭЛЕМЕНТ — это `sr.TopographySurface`, и штамп, квитанция и свидетели
    работают именно с ним. Написать `__sr.Id` было бы шестикратным CS1061;
    молча не записать штамп — потерять владение, потому что A5 сверяет его
    по квитанции.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    host_sel = op.get("host")
    tol = tolerances("create_site_subregion")
    # ХОЗЯИН ОБЪЯВЛЯЕТСЯ ВО ВНЕШНЕЙ ОБЛАСТИ, а не в блоке создания: при
    # isolation="per_op" create и post попадают в РАЗНЫЕ области видимости, и
    # переменная, объявленная внутри create, свидетелю не видна (CS0103 —
    # ровно тот шов, на котором волна ограждений получила шесть отказов ворот).
    host_decl, host_res, host_id_cs = "", "", None
    if isinstance(host_sel, dict):
        if host_sel.get("by") == "ref":
            host_id_cs = "__el_" + _safe(host_sel["value"]) + ".Id"
        else:
            host_decl = f"\nElement __hst_{s} = null;"
            host_res = (
                f"__hst_{s} = doc.GetElement("
                f"{_eid(host_sel['value'], ver, oid)});\n"
                f"if (__hst_{s} == null) {{ "
                f"{refuse_stmt(oid, _cs('топоповерхность-хозяин не найдена (модель изменилась после grounding)'), isolation)} }}\n")
            host_id_cs = f"__hst_{s}.Id"
    make = (f"__sr_{s} = SiteSubRegion.Create(doc, __loops_{s}, {host_id_cs});"
            if host_id_cs else
            f"__sr_{s} = SiteSubRegion.Create(doc, __loops_{s});")
    decl = (f"SiteSubRegion __sr_{s} = null;\n"
            f"TopographySurface __el_{s} = null;\n"
            f"List<CurveLoop> __loops_{s} = null;" + host_decl)
    create = (f"// create_site_subregion {cs_line_comment_fragment(oid)}\n"
              + host_res
              + "\n".join(_region_loops_cs(region, s)) + "\n"
              + make + "\n"
              f"if (__sr_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание подобласти площадки вернуло null'), isolation)} }}\n"
              f"__el_{s} = __sr_{s}.TopographySurface;\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('подобласть создана, но её поверхность не читается — элемента, которым можно владеть, нет'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    host_verdict = (
        f"    if (__hid_{s} == null || __hid_{s} == ElementId.InvalidElementId)\n"
        f"        __post.Add({_cs(oid + ': подобласть не принадлежит ни одной топоповерхности (topology)')});\n")
    if host_id_cs:
        host_verdict += (
            f"    else if (__hid_{s}.ToString() != {host_id_cs}.ToString())\n"
            f"        __post.Add({_cs(oid + ': подобласть принадлежит не запрошенной топоповерхности (topology)')});\n")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            # БУЛЕВ ФАКТ О РЕЗУЛЬТАТЕ, который наш вызов никуда не записывал:
            # Revit сам помечает созданную поверхность как подобласть. Если
            # бы Create вернул обычную поверхность, снаружи это было бы
            # неотличимо от успеха — вплоть до того дня, когда кто-то
            # заметил бы, что подобласти в модели нет.
            obligation_key="is_subregion",
            reader_cs="",
            verdict_cs=(
                f"    if (!__el_{s}.IsSiteSubRegion)\n"
                f"        __post.Add({_cs(oid + ': созданная поверхность не помечена как подобласть (semantic)')});\n"),
            message="созданная поверхность не помечена как подобласть (semantic)",
            style="guard"),
        _boundary_bbox_witness(f"__sr_{s}.GetBoundary()", s, oid, region,
                               tol["bbox_mm"], "bbox"),
        WitnessCheck(
            obligation_key="host_binding",
            reader_cs=(f"    var __hid_{s} = __sr_{s}.HostId;\n"),
            verdict_cs=host_verdict,
            message="подобласть не принадлежит запрошенной топоповерхности (topology)",
            style="guard"),
    ]
    return decl, create, checks, _host_readback(
        s, oid, stamp, f"__sr_{s}.HostId")
