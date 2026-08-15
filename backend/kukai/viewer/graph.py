"""СЛОЙ ГРАФА ВО ВЬЮЕРЕ — линия авторитета и «этого в Revit ещё нет».

Две оси узла, ортогональные всему, что вьюер показывал раньше:

    authority  = КТО авторитетен для этого узла (граф или Revit)
    existence  = СУЩЕСТВУЕТ ли он в документе, или пока только объявлен

Обе приходят из `kukai/ir/decompile/building_graph.py` — оттуда же берутся
ПЕРЕЧИСЛЕНИЯ, а не их копии: словарь у здания обязан быть один, иначе
`planned` во вьюере и `planned` в графе через месяц окажутся разными словами.

════════════════════════════════════════════════════════════════════════════
ПОЧЕМУ `existence` — ОТДЕЛЬНАЯ ОСЬ, А НЕ ЗНАЧЕНИЕ `Fidelity`
════════════════════════════════════════════════════════════════════════════
`Fidelity.NO_BODY` значит «элемент объявлен, тела мы не знаем».
`Existence.PLANNED` значит «элемента в модели ещё нет».
Это РАЗНЫЕ утверждения, и все четыре сочетания осмысленны: тело может быть
известно точно, а элемента в Revit ещё не быть (инженер написал программу и
не нажал кнопку) — и наоборот, элемент в документе есть, а тела мы не знаем.
Слить их в одну шкалу значило бы сделать кнопку «отправить в Revit» лотереей:
человек не отличил бы то, что уже стоит, от того, что он только что задумал.

════════════════════════════════════════════════════════════════════════════
ЗАМЕР 11.08.2026, КОТОРЫЙ ЗАДАЛ ФОРМУ ЭТОГО МОДУЛЯ
════════════════════════════════════════════════════════════════════════════
`graph_from_l0` + `graph_view` на реальных разборах:

| разбор              | узлов  | граф   | вид    | declared / derived_by_revit |
|---------------------|-------:|-------:|-------:|-----------------------------|
| `sob62_fas_r23_v19` |  5 218 | 0.18 с | 0.03 с | 3 066 / 2 152               |
| `snowdon_plumb_v4`  | 32 185 | 0.63 с | 0.16 с | 32 185 / 0                  |
| `демо-v3`           | 90 758 | 1.85 с | 0.57 с | 55 667 / 35 091             |

Узлов БОЛЬШЕ, чем оболочек (90 758 против 84 120), потому что граф держит и
датумы — уровни, оси, помещения. Значит соединение «узел ↔ оболочка»
частично по построению, и вьюер обязан это назвать, а не показать разницу
как потерю.

**`existence` на всём корпусе — `materialized` и только он.** Ни одного
`planned`: `graph_from_l0` — ЕДИНСТВЕННЫЙ строитель графа, и он читает
документ. Производителя `planned` в рабочем коде НЕТ ВОВСЕ (обход
`grep -rn "Existence.PLANNED"` даёт одну строку, и та в тесте). Отсюда прямое
следствие для этого модуля, и оно названо ниже целиком: **`planned` для живой
сессии проставляет ВЬЮЕР, а не граф.**

════════════════════════════════════════════════════════════════════════════
ФЛАГ ЧУЖОГО МОДУЛЯ УВАЖАЕТСЯ
════════════════════════════════════════════════════════════════════════════
`building_graph_enabled()` по умолчанию ВЫКЛЮЧЕН, и его владелец написал
почему: «модуль ещё ни разу не сверялся с живым Revit, и „встроен“ от
„написан“ этот пакет отличает флагом, а не самочувствием автора». Показать
инженеру непроверенные числа как правду — риск ровно того же рода, от
которого флаг и поставлен. Поэтому слой графа при выключенном флаге не
строится, а сообщает `available: false` с причиной — тристейтом, как везде:
«не спрашивали» отличимо от «спросили, ничего нет».
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

__all__ = ("GRAPH_SCHEMA", "AUTHORITY_CODE", "EXISTENCE_CODE", "FLAG_REFUTED",
           "FLAG_UNRESOLVED", "ElementGraph", "facts_for_decompile",
           "facts_for_programs", "unavailable")

GRAPH_SCHEMA = "kir-viewer-graph/1"

#: Коды публикуются в заголовке сцены; клиент своей копии не держит.
AUTHORITY_CODE: dict[str, int] = {"declared": 0, "derived_by_revit": 1,
                                  "unknown": 2}
EXISTENCE_CODE: dict[str, int] = {"materialized": 0, "planned": 1,
                                  "unknown": 2}

#: Биты `elem_flags`. ОБА — ФАКТЫ О РЕБРЕ, ОТНЕСЁННЫЕ К ЕГО КОНЦУ, и
#: формулировка на экране обязана это сохранять: «у элемента опровергнуто
#: отношение», а не «элемент опровергнут».
#:
#: ПОЧЕМУ ЭТО НЕ СОСТОЯНИЕ ДОВЕРИЯ. У вьюера было заведено `Trust.CLASH_REFUTED`
#: — моя ошибка, и она удалена. `Trust` отвечает «насколько сильно утверждение,
#: что элемент таков»; опровержение же есть свойство ОТНОШЕНИЯ между двумя
#: элементами (`GraphEdge.refuted_by`, обязательный ровно при
#: `Modality.REFUTED`). Покрасить элемент как «опровергнутый» из-за одного его
#: ребра — та самая подмена оси, ради запрета которой вся эта раскраска и
#: писалась. Замер, на котором это стало видно: `демо-v3` даёт 5 941
#: опровергнутое ребро правилом `host_does_not_separate_exactly_two_rooms`,
#: и все они про ДВЕРИ, каждая из которых сама по себе прочитана прекрасно.
FLAG_REFUTED = 1
FLAG_UNRESOLVED = 2


@dataclass(frozen=True, slots=True)
class ElementGraph:
    """Графовые факты об одном элементе. Ни одного вывода."""

    authority: str
    existence: str
    authority_source: str
    flags: int = 0


def unavailable(reason: str) -> dict[str, Any]:
    """Слой не построен — и СКАЗАНО ПОЧЕМУ. Пустой слой и отсутствующий слой
    читаются одинаково только если молчать."""
    return {"schema": GRAPH_SCHEMA, "available": False, "reason": reason,
            "authority": {}, "existence": {}, "relations": {},
            "refuted_by_rule": {}, "unresolved_by_reason": {},
            "without_l1": None, "nodes": 0}


def facts_for_decompile(origin: Mapping[str, Any],
                        elements: Sequence[Mapping[str, Any]],
                        *, generator_child_ids: Iterable[str],
                        l1_source_ids: Iterable[str],
                        ) -> tuple[dict[str, ElementGraph], dict[str, Any]]:
    """Разбор -> графовые факты по элементам + свод для панели.

    `generator_child_ids` подаётся ЯВНО и приходит из атомов L1 с причиной
    `generator_child`. Категорийная таблица сюда не подаётся и подаваться не
    может: приор не знает, кто элемент создаёт, — на нём строилась отозванная
    заявка про 14 713 фитингов.
    """
    from kukai.ir.decompile.building_graph import (Modality, building_graph_enabled,
                                                   graph_from_l0, graph_view)

    if not building_graph_enabled():
        return {}, unavailable(
            "KUKAI_IR_BUILDING_GRAPH не задан: граф здания не строился. Его "
            "владелец держит модуль за флагом, пока тот не сверен с живым "
            "Revit, и показывать непроверенное как правду вьюер не вправе")

    started = time.perf_counter()
    try:
        graph = graph_from_l0(origin, elements,
                              generator_child_ids=list(generator_child_ids))
        view = graph_view(graph, l1_source_ids=list(l1_source_ids))
    except Exception as exc:  # noqa: BLE001 — чужой модуль; отказ называется
        return {}, unavailable(
            f"граф не построился: {type(exc).__name__}: {str(exc)[:200]}")

    # РЁБРА -> ФЛАГИ КОНЦОВ. Обход по рёбрам, а не по узлам: у узла этого
    # знания нет, оно принадлежит отношению. Оба конца помечаются, потому что
    # опровергнутое отношение касается обоих, и молчать про второй нельзя.
    flags: dict[str, int] = {}
    for edge in graph.edges:
        bit = (FLAG_REFUTED if edge.modality is Modality.REFUTED
               else FLAG_UNRESOLVED if edge.modality is Modality.UNRESOLVED_TARGET
               else 0)
        if not bit:
            continue
        flags[edge.src] = flags.get(edge.src, 0) | bit
        flags[edge.dst] = flags.get(edge.dst, 0) | bit

    facts = {node.node_id: ElementGraph(
        authority=node.authority, existence=node.existence,
        authority_source=node.authority_source,
        flags=flags.get(node.node_id, 0)) for node in view.nodes}

    note = {
        "schema": GRAPH_SCHEMA,
        "available": True,
        "source": "graph_from_l0",
        "doc_name": view.doc_name,
        "nodes": len(view.nodes),
        "authority": dict(view.authority),
        "existence": dict(view.existence),
        "relations": dict(view.relations),
        # ОПРОВЕРГНУТОЕ РЕБРО ОСТАЁТСЯ И НАЗЫВАЕТ ПРАВИЛО. Пустой свод и
        # отсутствие свода — разное, поэтому ключ есть всегда.
        "refuted_by_rule": dict(view.refuted_by_rule),
        "unresolved_by_reason": dict(view.unresolved_by_reason),
        "without_l1": (None if view.without_l1 is None
                       else len(view.without_l1)),
        "without_l1_ru": ("набор листьев L1 не подавали — это НЕ «таких узлов "
                          "нет»" if view.without_l1 is None else
                          "узлов, которых чтение видело, а компилятор нет"),
        "census_rows": view.census_rows,
        "census_refusals": dict(view.census_refusals),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        # УЗЛОВ БОЛЬШЕ, ЧЕМ ОБОЛОЧЕК, И ЭТО НЕ ПОТЕРЯ. Граф держит датумы
        # (уровни, оси, помещения), которым оболочка не полагается по
        # `hulls.KIND_TABLE`. Замер: демо-v3 — 90 758 узлов против 84 120
        # оболочек. Без этой строки разница читалась бы как выпадение.
        "nodes_without_hull_ru": ("граф держит и датумы (уровни, оси, "
                                  "помещения), которым оболочка не положена — "
                                  "поэтому узлов больше, чем тел на экране"),
    }
    return facts, note


def facts_for_programs(ops_by_id: Mapping[str, Mapping[str, Any]]
                       ) -> tuple[dict[str, ElementGraph], dict[str, Any]]:
    """Операции живой сессии -> `existence=planned` и линия авторитета.

    ════════════════════════════════════════════════════════════════════════
    ЭТО ВЬЮЕР УТВЕРЖДАЕТ, А НЕ ГРАФ, И ГРАНИЦА НАЗВАНА ЗДЕСЬ
    ════════════════════════════════════════════════════════════════════════
    Строителя графа из программ НЕ СУЩЕСТВУЕТ: `graph_from_l0` — единственный,
    и он читает документ, проставляя `MATERIALIZED` каждому узлу. Значит
    `planned` здесь ставит вьюер по одному простому факту: программа лежит в
    журнале сессии, а журнал наполняется ДО записи в Revit. Утверждение узкое
    и проверяемое, и вторым источником правды оно не становится — ПЕРЕЧИСЛЕНИЯ
    берутся из `building_graph`, поэтому слово `planned` во вьюере и в графе
    остаётся одним словом.

    РЁБРА ЗДЕСЬ НЕ СТРОЯТСЯ. Хозяев по словам программы уже разрешает
    `clash_judgement.hosted_from_ops`, и результат приезжает в
    `BundleGeometry.hosted`; второй экземпляр того же разрешения разъехался бы
    с первым молча. Живой слой графа — это узлы и две их оси, не больше.

    ЛИНИЯ АВТОРИТЕТА НА ЗАЯВЛЕННОМ. Оп, чей контракт объявляет побочные
    элементы выведенными (`acceptance._OP_DERIVED`: витражная стена рождает
    ячейки, панели и импосты; перекрытие — эскизные линии; лестница — марши,
    площадки и ограждения), помечается `derived_by_revit` НЕ САМ — сам он
    объявлен автором. Помечается ФАКТ, что за ним придут элементы, которых в
    программе нет и в сцене не будет: их число знает только Revit. Поэтому
    оп остаётся `declared`, а свод несёт отдельную строку `will_derive` —
    иначе вьюер обещал бы показать то, чего показать не может.
    """
    from kukai.ir.decompile.building_graph import (Authority, AuthoritySource,
                                                   Existence)
    try:
        from kukai.ir.acceptance import _OP_DERIVED
    except Exception:  # noqa: BLE001 — чужая таблица; её молчание не наш зелёный
        _OP_DERIVED = {}

    facts: dict[str, ElementGraph] = {}
    will_derive: dict[str, int] = {}
    for element_id, op in ops_by_id.items():
        name = str(op.get("op") or "")
        for category in _OP_DERIVED.get(name, ()):
            will_derive[category] = will_derive.get(category, 0) + 1
        facts[element_id] = ElementGraph(
            authority=Authority.DECLARED.value,
            existence=Existence.PLANNED.value,
            authority_source=AuthoritySource.PROGRAM_OP.value)

    note = {
        "schema": GRAPH_SCHEMA,
        "available": True,
        "source": "viewer_asserts_planned",
        "source_ru": ("`planned` проставил ВЬЮЕР: строителя графа из программ "
                      "нет, а журнал сессии наполняется ДО записи в Revit"),
        "nodes": len(facts),
        "authority": {"declared": len(facts)} if facts else {},
        "existence": {"planned": len(facts)} if facts else {},
        "relations": {},
        "refuted_by_rule": {},
        "unresolved_by_reason": {},
        "without_l1": None,
        "without_l1_ru": "у заявленного листьев L1 нет по построению",
        # ЧТО REVIT ДОБАВИТ СВЕРХ ОБЪЯВЛЕННОГО. Показать эти элементы вьюер
        # не может (их число знает только Revit), но промолчать о них значило
        # бы обещать, что на экране всё здание.
        "will_derive": dict(sorted(will_derive.items())),
        "will_derive_ru": ("Revit ДОБАВИТ эти категории сверх объявленного — "
                           "их в сцене нет и быть не может: число знает только "
                           "Revit"),
    }
    return facts, note
