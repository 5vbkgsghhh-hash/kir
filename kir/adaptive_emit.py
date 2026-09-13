"""adaptive_emit — эмиссия `create_adaptive_component` (парный файл к
`ops_adaptive.py`, ровно как `mass_emit.py` к `ops_mass.py`).

Своя зона волны: этот модуль не трогает ни один другой `ops_*.py` и ни один
другой `*_emit.py`. `authoring.py` получает аддитивно импорт и одну строку в
`_EMITTERS` — тот же минимальный шов, которым подключилась волна массы.

Переиспользовано из `authoring.py` БЕЗ ИЗМЕНЕНИЙ (импортом, не копией):
`_gid`, `_eid`, `_cs`, `_safe`, `_stamp_block`, `_stamp_readback`,
`_symbol_res`. Последний — несущий: он уже умеет ДВА рода символа (найденный в
снимке и созданный ЭТОЙ ЖЕ программой через `create_type`/`load_family`), и
второй здесь не роскошь, а главный сценарий: адаптивных семейств в проекте
обычно НЕТ, их привозит `load_family` в той же программе.

═══ ПОРЯДОК ПРОВЕРОК НЕСУЩИЙ, А НЕ КОСМЕТИЧЕСКИЙ ═══════════════════════════

    1. IsAdaptiveFamilySymbol(symbol)        безопасна: бросает только на null
    2. IsAdaptiveComponentFamily(family)     безопасна: бросает только на null
    3. GetNumberOfPlacementPoints(family)    БРОСАЕТ ArgumentException, если
                                             семейство не адаптивное

Третья идёт последней именно поэтому. Переставь — и типизированный отказ KIR
превратится в исключение Revit с чужим текстом, то есть в `KIR-X999` вместо
названной причины. Все три стоят ДО `CreateAdaptiveComponentInstance`, значит
до всякого эффекта: транзакция откатывается с нулевым следом.

═══ СВИДЕТЕЛЬ: ЧЕТЫРЕ ПРОВЕРКИ, И КАЖДАЯ ЧИТАЕТ РЕЗУЛЬТАТ ══════════════════

Прочитать `Position` обратно сразу после записи — ПОДТВЕРЖДЕНИЕ СЕТТЕРА,
именной дефект этого дерева. Поэтому свидетель спрашивает то, что решает сам
Revit:

* **род построенного** — `IsAdaptiveComponentInstance` на СОЗДАННОМ элементе.
  Revit подтверждает, что получился адаптивный экземпляр, а не что-то иное;
* **число точек размещения** — `GetInstancePlacementPointElementRefIds`
  ПОСЛЕ создания. Их количество решает семейство, и оно обязано совпасть с
  числом заявленных. Документация Autodesk обещает порядок: *«sorted by the
  placement numbers (increasing order)»* — поэтому сравнение позиционное, а
  не по множеству;
* **точки применились** — `Position` каждой ref-точки против заявленной. Да,
  мы их только что записали, и всё же проверка НЕ вакуумна: RevitAPI.xml
  объявляет у сеттера `InvalidOperationException` — *«unable to move to the
  new location»*, — а `doc.Regenerate()` между записью и чтением даёт Revit
  право переставить точку по своим ограничениям. Проверка ловит ровно этот
  исход: «попросили, а точка не поехала»;
* **габарит содержит заявленные точки** — САМАЯ СИЛЬНАЯ из четырёх, потому
  что габарит Revit считает по РЕАЛЬНОЙ геометрии семейства, а не по нашим
  числам. Не адаптировалась геометрия — панель осталась там, где была, и
  габарит заявленных точек не покроет.

🔴 ЧЕГО ЭТОТ СВИДЕТЕЛЬ НЕ ЛОВИТ, названо здесь, чтобы никто не прочитал
зелёное шире, чем оно есть:

* **форму самой панели.** Она принадлежит семейству; оп её не заявлял и
  потому свидетельствовать не вправе;
* **выступ геометрии за точки.** Проверка габарита ОДНОСТОРОННЯЯ —
  «содержит», а не «равен». Панель с бортиком законно шире своих точек, и
  требовать равенства значило бы красить верную геометрию. Обратную сторону
  (габарит НЕ содержит точку) она ловит, и это тот исход, который означает
  несработавшую адаптацию;
* **порядок точек по смыслу.** Мы верим документированной сортировке по
  номеру размещения. Если Revit её нарушит, свидетель покраснеет на верной
  геометрии — ложный красный, дорогой, но НЕ молчаливо-неверный исход.

═══ ДОПУСК ВЫВЕДЕН, А НЕ НАЗНАЧЕН ══════════════════════════════════════════

    δ = MM(doc.Application.VertexTolerance) + contour.EMIT_COORD_QUANTUM_MM

Первое — собственное число Revit («две точки в пределах этого расстояния
считаются совпадающими»), второе — квант печати координаты: точка, выписанная
с двумя знаками, уже отстоит от идеальной на величину этого кванта. Тот же
вывод, что у волны тел; реестровой константы здесь нет и быть не может.
"""
from __future__ import annotations

from kir import contour as C
from kir.emit_core import (  # noqa: F401
    _cs, _safe, _stamp_block, _stamp_readback,
    _symbol_res,
)
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt


def _pt_cs(pt) -> str:
    """Точка модели в C#. Тот же формат и тот же квант, что у контура."""
    x, y, z = (round(float(c), 2) for c in (pt[0], pt[1], pt[2]))
    return f"P({x}, {y}, {z})"


def emit_adaptive_component(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic"
                            ) -> tuple[str, str, list, str]:
    """Адаптивный экземпляр по N точкам, Revit 2021-2026.

    Версионной ветки НЕТ: все шесть вызовов собираются одинаково на всех
    шести версиях (замер в шапке `ops_adaptive.py`), и род документа не
    ограничен ни на одной.
    """
    oid = str(op["id"])
    s = _safe(oid)
    pts = op["points_mm"]
    n = len(pts)

    # 🔴 КОНТРАКТ ОБЛАСТЕЙ (канон эмиттера, класс CS0103): всякая переменная,
    # которую читает POST или readback, объявляется В `decl`, и никогда через
    # `var` внутри `create`. Под `per_op` создание оборачивается в СВОЮ
    # try-область, и имя умирает на закрывающей скобке. Куплено здесь же:
    # первая редакция держала `__need_` и `__want_` внутри create, и оба
    # читателя (свидетель и квитанция) дали CS0103 на всех шести версиях.
    decl = (f"FamilyInstance __el_{s} = null;\n"
            f"int __need_{s} = -1;\n"
            f"XYZ[] __want_{s} = null;")

    want = ", ".join(_pt_cs(p) for p in pts)
    create = (
        f"// create_adaptive_component {cs_line_comment_fragment(oid)} — "
        f"{n} точек посадки\n"
        + _symbol_res(op, s, oid, ver, isolation) + "\n"
        # ── ТРИ ПРОВЕРКИ ДО ЭФФЕКТА, порядок несущий (см. шапку) ──────────
        f"if (!AdaptiveComponentInstanceUtils.IsAdaptiveFamilySymbol(__sy_{s})) "
        f"{{ {refuse_stmt(oid, _cs('типоразмер не адаптивный: у этого семейства нет точек размещения. Следующий ход — загрузить адаптивное семейство (load_family) либо взять place_family'), isolation)} }}\n"
        f"if (!AdaptiveComponentFamilyUtils.IsAdaptiveComponentFamily(__sy_{s}.Family)) "
        f"{{ {refuse_stmt(oid, _cs('семейство типоразмера не адаптивное'), isolation)} }}\n"
        f"__need_{s} = AdaptiveComponentFamilyUtils.GetNumberOfPlacementPoints(__sy_{s}.Family);\n"
        f"if (__need_{s} != {n}) {{ {refuse_stmt(oid, '\"семейству нужно \" + __need_' + s + '.ToString() + \" точек размещения, прислано ' + str(n) + '\"', isolation)} }}\n"
        # ── ЭФФЕКТ ───────────────────────────────────────────────────────
        f"__el_{s} = AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance(doc, __sy_{s});\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('создание адаптивного экземпляра вернуло null'), isolation)} }}\n"
        f"__want_{s} = new XYZ[] {{ {want} }};\n"
        f"IList<ElementId> __rp_{s} = "
        f"AdaptiveComponentInstanceUtils.GetInstancePlacementPointElementRefIds(__el_{s});\n"
        f"if (__rp_{s}.Count != {n}) "
        f"{{ {refuse_stmt(oid, '\"Revit отдал \" + __rp_' + s + '.Count.ToString() + \" точек размещения вместо ' + str(n) + '\"', isolation)} }}\n"
        f"for (int __i_{s} = 0; __i_{s} < {n}; __i_{s}++)\n"
        f"{{\n"
        f"    ReferencePoint __p_{s} = doc.GetElement(__rp_{s}[__i_{s}]) as ReferencePoint;\n"
        f"    if (__p_{s} == null) {{ {refuse_stmt(oid, _cs('точка размещения не читается как ReferencePoint'), isolation)} }}\n"
        f"    __p_{s}.Position = __want_{s}[__i_{s}];\n"
        f"}}\n"
        # Регенерация ОБЯЗАТЕЛЬНА до чтения: геометрия адаптируется к точкам
        # не в момент присваивания, а на регенерации — тот же закон, что у
        # витражной сетки («панели рождаются регенерацией, а не вызовом») и у
        # коннекторов CONNECT.
        f"doc.Regenerate();\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    tol_cs = f"(MM(doc.Application.VertexTolerance) + {C.EMIT_COORD_QUANTUM_MM})"
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="adaptive_kind",
            reader_cs=(
                f"    var __ak_{s} = AdaptiveComponentInstanceUtils"
                f".IsAdaptiveComponentInstance(__el_{s});\n"),
            verdict_cs=(
                f"    if (!__ak_{s})\n"
                f"        __post.Add({_cs(oid + ': построенный экземпляр не адаптивный (semantic)')});\n"),
            message="построенный экземпляр не адаптивный (semantic)",
            style="guard"),
        WitnessCheck(
            obligation_key="placement_point_count",
            reader_cs=(
                f"    var __pc_{s} = AdaptiveComponentInstanceUtils"
                f".GetInstancePlacementPointElementRefIds(__el_{s});\n"),
            verdict_cs=(
                f"    if (__pc_{s} == null || __pc_{s}.Count != {n})\n"
                f"        __post.Add({_cs(oid + ': число точек размещения не совпало с заявленным (topology)')});\n"),
            message="число точек размещения не совпало с заявленным (topology)",
            style="guard"),
        WitnessCheck(
            obligation_key="placement_points_applied",
            reader_cs=(
                f"    double __pw_{s} = 0.0;\n"
                f"    var __pl_{s} = AdaptiveComponentInstanceUtils"
                f".GetInstancePlacementPointElementRefIds(__el_{s});\n"
                f"    for (int __j_{s} = 0; __pl_{s} != null && __j_{s} < __pl_{s}.Count "
                f"&& __j_{s} < {n}; __j_{s}++)\n"
                f"    {{\n"
                f"        var __pp_{s} = doc.GetElement(__pl_{s}[__j_{s}]) as ReferencePoint;\n"
                f"        if (__pp_{s} == null) {{ __pw_{s} = double.MaxValue; break; }}\n"
                f"        double __pd_{s} = MM(__pp_{s}.Position.DistanceTo(__want_{s}[__j_{s}]));\n"
                f"        if (__pd_{s} > __pw_{s}) __pw_{s} = __pd_{s};\n"
                f"    }}\n"),
            verdict_cs=(
                f"    if (__pw_{s} > {tol_cs})\n"
                f"        __post.Add({_cs(oid + ': точка размещения не встала в заявленную (geometry)')});\n"),
            message="точка размещения не встала в заявленную (geometry)",
            style="guard"),
        WitnessCheck(
            obligation_key="bbox_contains_points",
            reader_cs=(
                f"    var __bx_{s} = __el_{s}.get_BoundingBox(null);\n"
                f"    bool __bo_{s} = __bx_{s} == null;\n"
                f"    for (int __k_{s} = 0; __bx_{s} != null && __k_{s} < {n}; __k_{s}++)\n"
                f"    {{\n"
                f"        XYZ __bw_{s} = __want_{s}[__k_{s}];\n"
                f"        double __bt_{s} = U({tol_cs});\n"
                f"        if (__bw_{s}.X < __bx_{s}.Min.X - __bt_{s} || __bw_{s}.X > __bx_{s}.Max.X + __bt_{s} ||\n"
                f"            __bw_{s}.Y < __bx_{s}.Min.Y - __bt_{s} || __bw_{s}.Y > __bx_{s}.Max.Y + __bt_{s} ||\n"
                f"            __bw_{s}.Z < __bx_{s}.Min.Z - __bt_{s} || __bw_{s}.Z > __bx_{s}.Max.Z + __bt_{s})\n"
                f"            __bo_{s} = true;\n"
                f"    }}\n"),
            verdict_cs=(
                f"    if (__bo_{s})\n"
                f"        __post.Add({_cs(oid + ': габарит экземпляра не содержит заявленную точку (geometry)')});\n"),
            message="габарит экземпляра не содержит заявленную точку (geometry)",
            style="guard"),
    ]

    readback = (
        f"{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"element_id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"placement_points\"] = __need_{s};\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __at_{s} = doc.GetElement(__el_{s}.GetTypeId());\n"
        f"          if (__at_{s} != null) __rb[\"type_name\"] = __at_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


#: ЧТО ЭТА СПИЦА ЭМИТИРУЕТ — ОБЪЯВЛЕНО ЗДЕСЬ, А НЕ В ХАБЕ (02.09.2026).
#: Прежде соответствие «оп -> тело» жило в рукописном `authoring._EMITTERS`,
#: а тело — здесь, и связывала их тонкая обёртка в хабе (41 штука на 19
#: спутников). Две записи одного факта в разных файлах — именной дефект
#: этого дерева; теперь запись ОДНА, и хаб её СПРАШИВАЕТ.
EMITTERS = {
    "create_adaptive_component": emit_adaptive_component,
}
