"""ЗАМЕРЫ КОРПУСА — единственный источник чисел для курса.

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ ЛИТЕРАЛЫ В ПРОЗЕ. Курс, который говорит «так
принято», хуже отсутствия курса: он звучит авторитетно и не проверяется. Здесь
каждое число лежит РЯДОМ СО СПОСОБОМ ЕГО ПОЛУЧИТЬ — путь к разбору, что именно
считалось и функция, которая пересчитает это заново. `test_course.py` гоняет
пересчёт по настоящим файлам, когда корпус на боксе есть, и объявляет пропуск,
когда его нет: «индекса нет» и «индекс пуст» — разные факты.

ЧТО ЗДЕСЬ НЕ ЛЕЖИТ. Ни одного суждения. Тираж 7.8 — замер; «значит, тиражируй»
— урок, и он живёт в `lessons.py`, где видно, что это вывод, а не факт.

ЕДИНИЦА ЗАМЕРА — ЗДАНИЕ, А НЕ РАЗБОР. На диске 70 каталогов, но это версии:
19 разборов одного фасада, 9 одной башни. Считать по каталогам значит дать
фасаду девятнадцать голосов. Поэтому корпус курса — ОДИН, самый полный разбор
на здание, и их семь.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

#: Карта производных категорий берётся у приёмки. Импорт МОДУЛЬНЫЙ, а не
#: ленивый: урок «даром» печатается внутри песочницы, где страж импортов
#: отказывает всему, что не загружено заранее.
from kukai.ir.acceptance import _OP_DERIVED  # noqa: E402

#: Корень слепков. Тот же путь, что читает `serving` (`KUKAI_DECOMPILE_DATA`).
DECOMPILE_ROOT = os.environ.get(
    "KUKAI_DECOMPILE_DATA",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "backend", "data",
        "decompile"))

#: Семь зданий, по одному разбору на здание — самому полному из версий.
#: Раздел назван, потому что метод повтора от него зависит (замер: в ЭОМ групп
#: НЕТ ВОВСЕ, и это не небрежность проектировщика, а другая форма повтора).
BUILDINGS: dict[str, str] = {
    "k2_ar_rd_v9": "K2, жилая башня 59 этажей, АР",
    "демо-v3": "демо-v3, жилой дом 64 уровня, АР",
    "sob62_r23_v5": "СОБ6.2, детский сад, АР",
    "sob62_fas_r23_v19": "СОБ6.2, фасад (витражи)",
    "snowdon_plumb_v5": "Snowdon, ВК",
    "snowdon_elec_v1": "Snowdon, ЭОМ",
    "sklnk_eom_r26_v8": "Сколково, ЭОМ",
}


@dataclass(frozen=True)
class Measurement:
    """Число, его происхождение и способ пересчитать.

    `recompute` возвращает ту же величину из файлов на диске. Если она
    вернула не то, что записано, — расходится ЗАПИСЬ, а не реальность, и тест
    обязан упасть громко: устаревший замер в курсе неотличим от выдумки.
    """

    key: str
    value: float
    unit: str
    what: str
    source: str
    recompute: Callable[[], float] | None = None

    def __str__(self) -> str:
        v = (f"{self.value:.0f}" if float(self.value).is_integer()
             else f"{self.value:.2f}")
        return f"{v} {self.unit}"


# ─────────────────────────────────────────────────────── чтение слепков

def _path(building: str, name: str) -> str:
    return os.path.join(DECOMPILE_ROOT, building, name)


def available(building: str) -> bool:
    return os.path.exists(_path(building, "L0.jsonl"))


def elements(building: str) -> dict[str, dict]:
    """Элементы L0 по id. Только записи `record == "element"`."""
    out: dict[str, dict] = {}
    with open(_path(building, "L0.jsonl"), encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            envelope = json.loads(line)
            if envelope.get("record") != "element":
                continue
            element = envelope.get("element") or {}
            eid = element.get("element_id")
            if eid:
                out[eid] = element
    return out


def group_index(building: str) -> dict[str, Any]:
    path = _path(building, "group.index.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("group_index") or {}


def curtain_index(building: str) -> dict[str, Any]:
    path = _path(building, "curtain.index.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle).get("curtain_index") or {}


# ────────────────────────────────────────────────── пересчёт по разборам

def count_elements(building: str) -> float:
    return float(len(elements(building)))


def count_types(building: str) -> float:
    """Различных (категория, тип). Тип — ПЕРВЫЙ уровень повторяющейся
    единицы: он живёт в модели и правится один раз на все свои элементы."""
    return float(len({(e.get("category"), e.get("type_id"))
                      for e in elements(building).values()}))


def group_definitions(building: str) -> float:
    return float(len(group_index(building).get("definitions") or {}))


def top_level_instances(building: str) -> float:
    """Постановки ВЕРХНЕГО уровня. Вложенные (`group_id_parent`) исключены:
    у них ни origin, ни привязки к уровню, и считать их как самостоятельные
    постановки значило бы завысить тираж."""
    instances = group_index(building).get("instances") or {}
    return float(sum(1 for row in instances.values()
                     if not row.get("group_id_parent")))


def reused_definitions(building: str) -> float:
    """Определений, поставленных БОЛЬШЕ ОДНОГО раза. Определение с одним
    вхождением — не тираж, а просто именованный набор."""
    instances = group_index(building).get("instances") or {}
    per: dict[Any, int] = {}
    for row in instances.values():
        if row.get("group_id_parent"):
            continue
        per[row.get("group_type_id")] = per.get(row.get("group_type_id"), 0) + 1
    return float(sum(1 for n in per.values() if n > 1))


def reused_definition_size(building: str) -> float:
    """Медиана числа членов у определения, поставленного больше одного раза.

    Отвечает на «какого РАЗМЕРА бывает тиражируемая единица»: единичный
    элемент тиражируют типом, а целый этаж — не тиражируют вовсе.
    """
    index = group_index(building)
    definitions = index.get("definitions") or {}
    instances = index.get("instances") or {}
    per: dict[Any, int] = {}
    for row in instances.values():
        if row.get("group_id_parent"):
            continue
        per[row.get("group_type_id")] = per.get(row.get("group_type_id"), 0) + 1
    sizes = sorted(len(definitions[gid].get("slots") or [])
                   for gid, count in per.items()
                   if count > 1 and gid in definitions)
    if not sizes:
        return 0.0
    mid = len(sizes) // 2
    return float(sizes[mid] if len(sizes) % 2
                 else (sizes[mid - 1] + sizes[mid]) / 2)


def grouped_share(building: str) -> float:
    """Доля элементов L0, лежащих ВНУТРИ какой-нибудь группы, в процентах.

    Это НИЖНЯЯ граница: члены групп сплошь и рядом принадлежат категориям,
    которых коллектор L0 не снимал, и такой член в знаменатель не попадает
    вовсе. Завышать здесь нечем, занижать — сколько угодно.
    """
    els = elements(building)
    instances = group_index(building).get("instances") or {}
    members: set[str] = set()
    for row in instances.values():
        members.update(row.get("member_ids") or [])
    return round(100.0 * len(members & set(els)) / max(1, len(els)), 1)


def curtain_hosts(building: str) -> float:
    return float(sum(1 for row in curtain_index(building).values()
                     if isinstance(row, dict) and row.get("curtain_available")))


def _curtain_records(building: str):
    from kukai.ir.decompile.curtain_extract import CurtainWallRecord
    for host_id, row in curtain_index(building).items():
        if isinstance(row, dict) and row.get("curtain_available"):
            yield CurtainWallRecord.from_dict(host_id, row)


def curtain_mullions(building: str) -> float:
    return float(sum(len(r.mullions) for r in _curtain_records(building)))


def curtain_type_driven_pct(building: str) -> float:
    """Доля импостов, которые РОДИТ ТИП НОСИТЕЛЯ, в процентах.

    Считается двумя независимыми свидетелями Revit — `Mullion.Lock` и
    совпадение типа импоста с типовым для его направления
    (`curtain_extract.CurtainWallRecord.mullion_state`). Логика не
    переписана здесь: зовётся та самая, которой пользуется обратный ход.
    """
    from kukai.ir.decompile.curtain_extract import MullionState
    total = driven = 0
    for record in _curtain_records(building):
        for mullion in record.mullions:
            total += 1
            if record.mullion_state(mullion) is MullionState.TYPE_DRIVEN:
                driven += 1
    return round(100.0 * driven / max(1, total), 1)


def curtain_authored_grid_lines(building: str) -> float:
    """Линии разрезки, которые НАДО написать: те, что тип носителя не режет
    сам (`GridLineState.TYPE_DRIVEN` исключены)."""
    from kukai.ir.decompile.curtain_extract import GridLineState
    n = 0
    for record in _curtain_records(building):
        for line in list(record.u_grid_lines) + list(record.v_grid_lines):
            if record.grid_line_state(line) is not GridLineState.TYPE_DRIVEN:
                n += 1
    return float(n)


def curtain_panels(building: str) -> float:
    return float(sum(len(r.panels) for r in _curtain_records(building)))


def derived_categories() -> dict[str, tuple[str, ...]]:
    """Категория → опы, ВСЛЕД ЗА которыми Revit её производит.

    ВТОРОГО СПИСКА ЗДЕСЬ НЕТ. Правда об этом уже записана в цепи приёмки
    (`acceptance._OP_DERIVED`), где она несёт вес: производную категорию
    перепись не сверяет и не показывает как «неожиданное». Курс, который
    завёл бы свой перечень, разошёлся бы с приёмкой на первом же новом опе —
    и учил бы модель не писать то, что писать надо.

    Имя приватное намеренно: у карты нет публичного читателя, кроме этого
    урока. Тест `test_course` держит её непустой, чтобы переименование
    сломало курс громко, а не тихо.

    ИМПОРТ НЕ ЛЕНИВЫЙ: эта функция исполняется ВНУТРИ песочницы (урок
    «даром»), а там страж импортов отказывает любому корню вне белого списка.
    Всё, что нужно уроку, загружается на импорте модуля.
    """
    out: dict[str, list[str]] = {}
    for op_name, categories in _OP_DERIVED.items():
        for category in categories:
            out.setdefault(category, []).append(op_name)
    return {c: tuple(sorted(ops)) for c, ops in sorted(out.items())}


def derived_share(building: str) -> float:
    """Доля модели в производных категориях, в процентах."""
    els = elements(building)
    derived = derived_categories()
    n = sum(1 for e in els.values() if e.get("category") in derived)
    return round(100.0 * n / max(1, len(els)), 1)


def level_signatures(building: str) -> float:
    """Различных ПОДПИСЕЙ этажа (набор типов без количеств) на здание.

    Подпись — множество (категория, тип) элементов уровня. Совпали подписи —
    этаж повторён, и «типовой этаж» перестаёт быть метафорой.
    """
    per: dict[str, set] = {}
    for element in elements(building).values():
        level = element.get("level_name")
        if not level:
            continue
        per.setdefault(level, set()).add(
            (element.get("category"), element.get("type_id")))
    return float(len({tuple(sorted(s)) for s in per.values()}))


def levels_with_elements(building: str) -> float:
    return float(len({e.get("level_name") for e in elements(building).values()
                      if e.get("level_name")}))


# ═════════════════════════════════════════════════════════════════════════
# ЗАПИСАННЫЕ ЗАМЕРЫ (03.08.2026, прод-бокс, python3.12)
# ═════════════════════════════════════════════════════════════════════════

def _m(key: str, value: float, unit: str, what: str, building: str,
       fn: Callable[[str], float] | None = None) -> Measurement:
    return Measurement(
        key=key, value=value, unit=unit, what=what,
        source=f"backend/data/decompile/{building}/ — {BUILDINGS[building]}",
        recompute=(lambda: fn(building)) if fn else None)


MEASUREMENTS: dict[str, Measurement] = {m.key: m for m in (
    # ── масштаб и тип как первая повторяющаяся единица ──────────────────
    _m("k2.elements", 115880, "элементов", "элементов L0",
       "k2_ar_rd_v9", count_elements),
    _m("k2.types", 638, "типов", "различных (категория, тип)",
       "k2_ar_rd_v9", count_types),
    _m("demo.elements", 90758, "элементов", "элементов L0",
       "демо-v3", count_elements),
    _m("demo.types", 165, "типов", "различных (категория, тип)",
       "демо-v3", count_types),
    _m("sklnk.elements", 19306, "элементов", "элементов L0",
       "sklnk_eom_r26_v8", count_elements),
    _m("sklnk.types", 47, "типов", "различных (категория, тип)",
       "sklnk_eom_r26_v8", count_types),

    # ── группы: тираж повторяющейся единицы ─────────────────────────────
    _m("k2.group_defs", 367, "определений", "определений групп",
       "k2_ar_rd_v9", group_definitions),
    _m("k2.group_places", 2846, "постановок", "постановок верхнего уровня",
       "k2_ar_rd_v9", top_level_instances),
    _m("k2.group_reused", 176, "определений", "определений с тиражом > 1",
       "k2_ar_rd_v9", reused_definitions),
    _m("k2.grouped_share", 41.1, "%", "элементов внутри групп (нижняя граница)",
       "k2_ar_rd_v9", grouped_share),
    _m("plumb.group_defs", 14, "определений", "определений групп",
       "snowdon_plumb_v5", group_definitions),
    _m("plumb.group_places", 110, "постановок", "постановок верхнего уровня",
       "snowdon_plumb_v5", top_level_instances),
    _m("plumb.group_reused", 12, "определений", "определений с тиражом > 1",
       "snowdon_plumb_v5", reused_definitions),
    _m("k2.group_members", 11, "членов", "медиана членов у тиражируемого "
       "определения", "k2_ar_rd_v9", reused_definition_size),
    _m("plumb.group_members", 50.5, "членов", "медиана членов у тиражируемого "
       "определения", "snowdon_plumb_v5", reused_definition_size),
    _m("elec.group_defs", 0, "определений", "определений групп",
       "snowdon_elec_v1", group_definitions),
    _m("sklnk.group_defs", 0, "определений", "определений групп",
       "sklnk_eom_r26_v8", group_definitions),
    _m("kinder.group_defs", 1, "определение", "определений групп",
       "sob62_r23_v5", group_definitions),

    # ── витраж: три слоя, из которых пишутся два ────────────────────────
    _m("k2.curtain_hosts", 1000, "носителей", "стен с витражной сеткой",
       "k2_ar_rd_v9", curtain_hosts),
    _m("k2.curtain_lines", 2561, "линий", "линий разрезки, НЕ рождённых типом",
       "k2_ar_rd_v9", curtain_authored_grid_lines),
    _m("k2.curtain_mullions", 11091, "импостов", "импостов всего",
       "k2_ar_rd_v9", curtain_mullions),
    _m("k2.curtain_driven", 92.0, "%", "импостов, рождённых типом носителя",
       "k2_ar_rd_v9", curtain_type_driven_pct),
    _m("k2.curtain_panels", 5505, "панелей", "панелей витража",
       "k2_ar_rd_v9", curtain_panels),
    _m("fas.curtain_hosts", 393, "носителей", "стен с витражной сеткой",
       "sob62_fas_r23_v19", curtain_hosts),
    _m("fas.curtain_lines", 122, "линий", "линий разрезки, НЕ рождённых типом",
       "sob62_fas_r23_v19", curtain_authored_grid_lines),
    _m("fas.curtain_mullions", 1372, "импостов", "импостов всего",
       "sob62_fas_r23_v19", curtain_mullions),
    _m("fas.curtain_driven", 92.1, "%", "импостов, рождённых типом носителя",
       "sob62_fas_r23_v19", curtain_type_driven_pct),
    _m("fas.curtain_panels", 559, "панелей", "панелей витража",
       "sob62_fas_r23_v19", curtain_panels),

    # ── что Revit делает сам ────────────────────────────────────────────
    _m("k2.derived", 18.4, "%", "модели в производных категориях",
       "k2_ar_rd_v9", derived_share),
    _m("fas.derived", 48.7, "%", "модели в производных категориях",
       "sob62_fas_r23_v19", derived_share),

    # ── этаж как единица: где повтор есть, а где его нет ────────────────
    _m("demo.levels", 64, "уровней", "уровней с элементами",
       "демо-v3", levels_with_elements),
    _m("demo.level_sigs", 23, "подписей", "различных наборов типов на уровне",
       "демо-v3", level_signatures),
    _m("sklnk.levels", 121, "уровней", "уровней с элементами",
       "sklnk_eom_r26_v8", levels_with_elements),
    _m("sklnk.level_sigs", 21, "подписей", "различных наборов типов на уровне",
       "sklnk_eom_r26_v8", level_signatures),
    _m("k2.levels", 58, "уровней", "уровней с элементами",
       "k2_ar_rd_v9", levels_with_elements),
    _m("k2.level_sigs", 41, "подписей", "различных наборов типов на уровне",
       "k2_ar_rd_v9", level_signatures),
    _m("kinder.levels", 7, "уровней", "уровней с элементами",
       "sob62_r23_v5", levels_with_elements),
    _m("kinder.level_sigs", 7, "подписей", "различных наборов типов на уровне",
       "sob62_r23_v5", level_signatures),
)}


def value(key: str) -> float:
    return MEASUREMENTS[key].value


def n(key: str) -> str:
    """Число замера строкой — для подстановки в текст урока.

    Тысячи разделяются пробелом: «115 880» читается, «115880» пересчитывается
    глазами, а урок, который надо пересчитывать, читают по диагонали.
    """
    return fmt(MEASUREMENTS[key].value)


def fmt(v: float) -> str:
    """Число человеку: целое с разрядами, дробное с одним знаком.

    Разделитель разрядов — НЕРАЗРЫВНЫЙ пробел (U+00A0), и это не педантизм:
    переливка абзацев в `lessons._reflow` иначе рвёт «16 596» на «16» и «596»
    в конце строки, и число приходится собирать глазами обратно.
    """
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", " ")
    return f"{v:.1f}"


def ratio(a: str, b: str) -> str:
    """Отношение двух замеров. Считается, а не набирается: производное число,
    набранное руками, — первое, что расходится с источником."""
    return fmt(round(MEASUREMENTS[a].value / MEASUREMENTS[b].value, 1))


def percent(a: str, b: str) -> str:
    return fmt(round(100.0 * MEASUREMENTS[a].value / MEASUREMENTS[b].value))


# ═════════════════════════════════════════════════════════════════════════
# НАШ СОБСТВЕННЫЙ СЛЕД — то, ради чего курс написан
# ═════════════════════════════════════════════════════════════════════════

#: Замер 27.07, записан в `ground.py:671` рядом с починкой, которая сделала оп
#: достижимым: до неё `ground()` не заходил внутрь `members`, эмиттер получал
#: сырой селектор и падал голым KeyError, а наружу шло «члены должны быть
#: pre-grounded» — совет, который при исполнении отказывал точно так же.
GROUP_USES_IN_LIFTED_OPS = 0
LIFTED_OPS_MEASURED = 51_574

#: Замер 03.08 по `data/telemetry/kir_rejections.jsonl`: 1453 живых отказа,
#: 25 различных запрошенных опов, `create_group` среди них НЕТ НИ РАЗУ.
#: Отдельное свидетельство того же: оп не пробовали, а не «пробовали и не
#: вышло». Пересчёт — `test_course.test_our_own_trace_still_shows_zero`.
GROUP_IN_LIVE_REJECTIONS = 0
LIVE_REJECTIONS_MEASURED = 1_453


__all__ = [
    "BUILDINGS", "DECOMPILE_ROOT", "MEASUREMENTS", "derived_categories",
    "Measurement", "GROUP_USES_IN_LIFTED_OPS", "LIFTED_OPS_MEASURED",
    "GROUP_IN_LIVE_REJECTIONS", "LIVE_REJECTIONS_MEASURED",
    "available", "curtain_authored_grid_lines", "curtain_hosts",
    "curtain_mullions", "curtain_panels", "curtain_type_driven_pct",
    "count_elements", "count_types", "derived_share", "elements",
    "group_definitions", "grouped_share", "level_signatures",
    "reused_definition_size",
    "levels_with_elements", "n", "fmt", "percent", "ratio",
    "reused_definitions", "top_level_instances",
    "value",
]
