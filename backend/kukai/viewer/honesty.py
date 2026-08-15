"""СЛОВАРЬ ЧЕСТНОСТИ ВЬЮЕРА — почему цвет здесь означает ДОВЕРИЕ, а не категорию.

Обычный BIM-вьюер красит по категории: стены серые, трубы синие. Такой вьюер
физически не способен показать разницу между «стена построена операцией, у
которой есть живые прогоны» и «на этом месте атом: подъём отказался, мы знаем
только габаритный ящик». Обе будут серыми стенами, и человек три часа будет
верить картинке, которая ему этого не обещала.

Поэтому здесь принято ОБРАТНОЕ решение, и оно несущее:

    БАЗОВЫЙ ЦВЕТ ЭЛЕМЕНТА = СИЛА УТВЕРЖДЕНИЯ О НЁМ.
    ФОРМА ЭЛЕМЕНТА = ТОЧНОСТЬ ГЕОМЕТРИИ, КОТОРОЙ МЫ РАСПОЛАГАЕМ.

Второе — не метафора. Элемент, про который известен только габаритный бокс,
рисуется ЯЩИКОМ, а не стеной: у нас нет стены, у нас есть ящик. Здание, у
которого 99 % оболочек — габариты, ОБЯЗАНО выглядеть как поле ящиков, потому
что это правда о том, что мы про него знаем. Гладкая серая стена на месте
габарита — это ровно тот дефект «свидетель подписал непрочитанную ось», только
нарисованный.

ЗАМЕР, НА КОТОРОМ СТОИТ ЭТО РЕШЕНИЕ (10.08.2026, `clash.snapshot`
+ `tree.json`, реальный корпус `backend/backend/data/decompile`):

| разбор                | оболочек | Aabb (габарит)  | Prism/PrismSet | Capsule        |
|-----------------------|---------:|----------------:|---------------:|---------------:|
| `демо-v3`             |   84 120 | 84 027 (99.89 %)|    93 (0.11 %) |       0 (0 %)  |
| `k2_ar_rd_v15`        |   47 635 | 47 318 (99.33 %)|   317 (0.67 %) |       0 (0 %)  |
| `snowdon_plumb_v4`    |   31 904 | 15 648 (49.05 %)|      0 (0 %)   | 16 256 (50.95 %)|
| `sob62_fas_r23_v19`   |    4 218 |  4 118 (97.63 %)|   100 (2.37 %) |       0 (0 %)  |

То есть на архитектуре honest-геометрии СЕГОДНЯ практически нет, а на
инженерии половина — капсулы. Вьюер, который это скроет, соврёт про главное.

ВТОРОЙ ЗАМЕР, И ОН СДЕЛАЛ СЛОЙ ЧЕСТНОСТИ ВОЗМОЖНЫМ. Соединение оболочки с
узлом L1 по `source_element_id` ПОЛНОЕ — ни одной оболочки без узла:

| разбор              | оболочек | join op          | join atom        | без узла |
|---------------------|---------:|-----------------:|-----------------:|---------:|
| `sob62_fas_r23_v19` |    4 218 |  2 167 (51.38 %) |  2 051 (48.62 %) |        0 |
| `демо-v3`           |   84 120 | 46 618 (55.42 %) | 37 502 (44.58 %) |        0 |
| `snowdon_plumb_v4`  |   31 904 | 31 840 (99.80 %) |     64 (0.20 %)  |        0 |

Ноль в последней колонке — не удача, а условие осмысленности: раскраска по
доверию, у которой часть здания «не знаю», обязана иметь для этого состояние.
Она его завела (`UNKNOWN`).

И ОНО НЕ ПУСТОЕ — ЭТО ЗАМЕР, ОТМЕНИВШИЙ ПРЕДЫДУЩУЮ РЕДАКЦИЮ ЭТОГО АБЗАЦА.
Здесь сначала было написано «на этом корпусе оно пусто», выведенное из трёх
разборов, у которых `tree.json` есть. Полный обход корпуса это опроверг:
**из 67 разборов с потоком L0 дерево L1 есть только у 52.** У остальных 15
(`k2_ar_rd_v15`, `snowdon_plumb_v5` и др.) соединять оболочку НЕ С ЧЕМ, и
`UNKNOWN` там — 100 %, а не ноль. Это ровно та «граница, заведённая
рассуждением, а не замером», которую пакет считает своим главным классом
дефекта, и она чуть не проехала в комментарий-спецификацию.

Практическое следствие для картинки: такие здания вьюер обязан красить
состоянием «неизвестно» ЦЕЛИКОМ и печатать причину из
`read_l1_honesty(...)[1]["reason"]`. Серое здание, про которое честно сказано
«узлов L1 нет», полезно; то же здание, покрашенное как доказанное, — это
ровно тот дефект, ради которого весь этот модуль написан.

ЛОВУШКА, В КОТОРУЮ ЭТОТ МОДУЛЬ ПОПАЛ И ВЫБРАЛСЯ (записано, чтобы не повторили).
Первый замер соединения дал 32.7–37.9 % оболочек «без узла L1» — и это был
ДЕФЕКТ ПРИБОРА, а не факт о зданиях: обход дерева читал только `payload`
узлов и не читал `members` у `atom_cluster` / `row` / `grid_array`, где лежат
СХЛОПНУТЫЕ атомы (на `демо-v3` их 118 кластеров). Прибор, покрывающий часть
своего диапазона, хуже отсутствующего — поэтому `iter_l1_nodes` идёт и по
`children`, и по `members`, и на это есть тест.

ОТМЕНЁННОЕ СОСТОЯНИЕ, И ЭТО МОЯ ОШИБКА, А НЕ ЧУЖАЯ. Здесь стояло
`Trust.CLASH_REFUTED` — «ребро клеша, снятое именованным правилом». Оно
удалено, и не потому, что источник не появился (появился: `Modality.REFUTED`
и `GraphEdge.refuted_by` в `building_graph`, живой замер `демо-v3` — 5 941
снятое ребро правилом `host_does_not_separate_exactly_two_rooms`), а потому,
что это была ПОДМЕНА ОСИ. `Trust` отвечает на вопрос «насколько сильно
утверждение, что ЭЛЕМЕНТ таков»; опровержение же есть свойство ОТНОШЕНИЯ
между двумя элементами. Покрасить дверь как «опровергнутую» из-за того, что
её ребро с комнатой снято правилом, значило бы обвинить прекрасно прочитанный
элемент — ровно та подмена, ради запрета которой вся эта раскраска и писалась.

Настоящий сигнал живёт на своей оси: `viewer.graph.FLAG_REFUTED` — бит
«у этого элемента ОПРОВЕРГНУТО ОТНОШЕНИЕ», плюс свод по ИМЕНАМ правил.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

__all__ = (
    "AXES_ORDER",
    "AXES_UNJUDGEABLE",
    "HONESTY_SCHEMA",
    "Trust",
    "Fidelity",
    "ElementHonesty",
    "HonestyCensus",
    "iter_l1_nodes",
    "read_l1_honesty",
    "unproven_ops",
)

HONESTY_SCHEMA = "kir-viewer-honesty/1"


class Trust(str, Enum):
    """НАСКОЛЬКО СИЛЬНО утверждение о том, что этот элемент вообще таков.

    Порядок значений — от сильного к слабому, и он же порядок тревожности
    цвета во вьюере. Значение читается как ответ на вопрос «чем доказано, что
    здесь стоит именно это».
    """

    #: Элемент поднят в операцию KIR, и у этой операции есть живые прогоны:
    #: её нет в `tool_doc.UNPROVEN`. Самое сильное, что вообще бывает офлайн.
    OP_PROVEN = "op_proven"

    #: Элемент поднят в операцию, но операция стоит в `tool_doc.UNPROVEN`
    #: (29 записей на 10.08.2026): ворота её собирают, живьём её никто не
    #: строил. «Скомпилируется» и «построится» — разные утверждения, и
    #: смешивать их на картинке нельзя.
    OP_UNPROVEN = "op_unproven"

    #: Элемент — АТОМ: подъём отказался и НАЗВАЛ причину
    #: (`payload.reason.code`). Пересборка его не построит. Это не дефект
    #: чтения сам по себе — `generator_child` значит «его делает генератор
    #: Revit», и это законно, — но и зданием, которое мы умеем воспроизвести,
    #: он не является.
    ATOM = "atom"

    #: Оболочка есть, узла L1 нет. На замеренном корпусе ПУСТО (0 из 120 242).
    #: Состояние существует, чтобы отсутствие было видно, если оно появится.
    UNKNOWN = "unknown"



class Fidelity(str, Enum):
    """НАСКОЛЬКО ТОЧНА геометрия, которой мы про элемент располагаем.

    Прямо соответствует `clash.hulls.GRADES` плюс вырожденность из
    `clash.hulls.hull_degeneracy`. Вьюер обязан выбирать по этому полю ФОРМУ,
    а не только оттенок: габарит, нарисованный телом, — это ложь о знании.
    """

    #: `grade="conservative"`: контур подошвы (`profile`), полоса вокруг оси
    #: (`prism`) или капсула по оси с сечением из данных (`axis_section`).
    #: Оболочка СОДЕРЖИТ тело и повторяет его форму.
    SHAPED = "shaped"

    #: `grade="coarse"`, `hull_source="bbox"`: известен только габаритный бокс.
    #: На `демо-v3` это 99.89 % элементов. Рисуется ЯЩИКОМ.
    BOX_ONLY = "box_only"

    #: Габарит нулевого объёма (`hull_degeneracy` != "ok"): плоскость, линия
    #: или точка. Замер по всему складу — 64 357 из 664 870 (9.7 %), а на
    #: `демо-v3` 32 165 из 84 120 (38.2 %, все `OST_GenericModel`). Такая
    #: оболочка не может доказать НИЧЕГО и обязана быть видна отдельно.
    DEGENERATE = "degenerate"

    #: `grade="exact"` — недостижим ПО ВЫВОДУ (`hulls.UNREACHABLE_GRADE_REASONS`):
    #: ни один источник не доказывает равенства оболочки телу. Заведён, чтобы
    #: недостижимость была названа, а не выглядела как «не нашлось».
    EXACT = "exact"

    #: ТЕЛА НЕТ ВОВСЕ. Элемент программой объявлен, а построить его тело
    #: `clash_bundle` отказался и назвал причину. Это НЕ «нулевой объём»
    #: (`DEGENERATE`, где тело есть и оно плоское) и не «только габарит»
    #: (`BOX_ONLY`, где габарит есть): здесь нет НИЧЕГО, и на экране элемент
    #: держится только контуром из плана.
    #:
    #: ЗАМЕР 11.08.2026, ради которого состояние заведено: пачка из шести стен
    #: и трубы БЕЗ снимка открытой модели даёт **0 тел из 7**, все семь —
    #: `needs_live_model`. Толщина стены и наружный диаметр трубы живут в ТИПЕ,
    #: и офлайн их взять неоткуда. То же на масштабе: `snowdon_plumb_v4` —
    #: 905 тел без снимка против 16 247 из 16 257 (99.94 %) со снимком.
    #: Вьюер, рисующий эти семь стен как построенные, соврал бы про ровно то,
    #: что отделяет «я написал программу» от «здание есть».
    NO_BODY = "no_body"


#: Причины атома, при которых атом — НОРМА, а не потеря. `generator_child`
#: значит «элемент порождает генератор Revit» (вложенные семейства, мулльоны
#: за `Mullion.Lock`): опа для него быть НЕ ДОЛЖНО, и красить его тревожно
#: значило бы звать чинить то, что не сломано. Замер `sob62_fas_r23_v19`:
#: 2 152 из 2 412 атомов (89.2 %) — именно `generator_child`.
BENIGN_ATOM_REASONS: frozenset[str] = frozenset({"generator_child"})


@dataclass(frozen=True, slots=True)
class ElementHonesty:
    """Всё, что вьюер знает о ДОВЕРИИ к одному элементу. Ни одного вывода."""

    element_id: str
    trust: Trust
    fidelity: Fidelity
    #: `op_name` для `OP_*`, `reason.code` для `ATOM`, `""` для `UNKNOWN`.
    why: str = ""
    #: Атом по законной причине (см. `BENIGN_ATOM_REASONS`).
    benign: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.element_id, "trust": self.trust.value,
                "fidelity": self.fidelity.value, "why": self.why,
                "benign": self.benign}


@dataclass
class HonestyCensus:
    """Перепись слоя честности. Тот же закон, что у `clash.snapshot.Census`:
    сумма по состояниям обязана равняться числу элементов, иначе процент
    внизу экрана не имеет знаменателя."""

    by_trust: dict[str, int] = field(default_factory=dict)
    by_fidelity: dict[str, int] = field(default_factory=dict)
    by_atom_reason: dict[str, int] = field(default_factory=dict)
    by_unproven_op: dict[str, int] = field(default_factory=dict)
    total: int = 0

    def add(self, item: ElementHonesty) -> None:
        self.total += 1
        self.by_trust[item.trust.value] = self.by_trust.get(item.trust.value, 0) + 1
        key = item.fidelity.value
        self.by_fidelity[key] = self.by_fidelity.get(key, 0) + 1
        if item.trust is Trust.ATOM and item.why:
            self.by_atom_reason[item.why] = self.by_atom_reason.get(item.why, 0) + 1
        elif item.trust is Trust.OP_UNPROVEN and item.why:
            self.by_unproven_op[item.why] = self.by_unproven_op.get(item.why, 0) + 1

    def balanced(self) -> bool:
        """Сходимость переписи. Расхождение — не предупреждение: раскраска, у
        которой часть элементов не попала ни в одно состояние, показывает
        зелёное здание, про которое неизвестно, зелёное ли оно."""
        return sum(self.by_trust.values()) == self.total == sum(
            self.by_fidelity.values())

    def to_dict(self) -> dict[str, Any]:
        return {"schema": HONESTY_SCHEMA, "total": self.total,
                "by_trust": dict(sorted(self.by_trust.items())),
                "by_fidelity": dict(sorted(self.by_fidelity.items())),
                "by_atom_reason": dict(sorted(self.by_atom_reason.items())),
                "by_unproven_op": dict(sorted(self.by_unproven_op.items())),
                "balanced": self.balanced()}


def unproven_ops() -> frozenset[str]:
    """Имена операций из `tool_doc.UNPROVEN` (29 записей на 10.08.2026).

    Импорт ленивый и защищённый: `tool_doc` тянет реестр, а вьюер обязан
    рисовать здание и тогда, когда реестр не поднялся. Пустое множество
    здесь означает «спросить было нечем», и это НЕ то же самое, что «все опы
    доказаны», — поэтому вызывающий получает ещё и флаг в `read_l1_honesty`.
    """
    try:
        from kukai.ir.tool_doc import UNPROVEN
        return frozenset(UNPROVEN)
    except Exception:  # noqa: BLE001 — реестр чужой; его молчание не наш зелёный
        return frozenset()


def iter_l1_nodes(node: Any) -> Iterator[Mapping[str, Any]]:
    """Все НЕСУЩИЕ ЭЛЕМЕНТ узлы дерева L1 — и по `children`, и по `members`.

    ВТОРОЙ ОБХОД НЕ ДЕКОРАЦИЯ. `atom_cluster` / `row` / `grid_array` схлопывают
    однотипные атомы в один узел и держат их в `members`, а не в `children`;
    у самого кластера `payload` пуст. Обход, читающий только `payload`
    потомков, теряет их МОЛЧА: замер 10.08 дал 37.9 % «оболочек без узла» на
    `демо-v3`, и все они нашлись в `members`. После правки — 0.
    """
    if not isinstance(node, Mapping):
        return
    payload = node.get("payload")
    if isinstance(payload, Mapping) and payload.get("source_element_id"):
        yield payload
    for member in (node.get("members") or ()):
        if isinstance(member, Mapping) and member.get("source_element_id"):
            yield member
    for child in (node.get("children") or ()):
        yield from iter_l1_nodes(child)


def read_l1_honesty(run_dir: str | pathlib.Path) -> tuple[
        dict[str, tuple[Trust, str]], dict[str, Any]]:
    """`tree.json` разбора -> {element_id: (Trust, почему)} + справка о чтении.

    Возвращает ДВА значения, и второе обязательно: если дерева нет или оно не
    прочиталось, вьюер не имеет права молча покрасить всё здание в
    `OP_PROVEN`. Справка несёт `available` и причину, а вызывающий обязан
    перевести всё в `Trust.UNKNOWN`.
    """
    path = pathlib.Path(run_dir) / "tree.json"
    note: dict[str, Any] = {"available": False, "reason": "", "path": str(path),
                            "unproven_table": True}
    if not path.exists():
        note["reason"] = "tree.json отсутствует: узлов L1 в этом разборе нет"
        return {}, note
    try:
        tree = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 — испорченное дерево это не зелёный
        note["reason"] = f"tree.json не разобран: {type(exc).__name__}"
        return {}, note

    unproven = unproven_ops()
    note["unproven_table"] = bool(unproven)
    if not unproven:
        # Реестр не поднялся. Тогда `OP_PROVEN` было бы ВЫВОДОМ, а не
        # измерением, и его нельзя показывать как измерение.
        note["reason"] = ("таблица tool_doc.UNPROVEN не прочитана: отличить "
                          "доказанный оп от недоказанного нечем")

    out: dict[str, tuple[Trust, str]] = {}
    for payload in iter_l1_nodes(tree):
        sid = str(payload.get("source_element_id"))
        kind = payload.get("kind")
        if kind == "atom":
            reason = (payload.get("reason") or {})
            out[sid] = (Trust.ATOM, str(reason.get("code") or "unnamed"))
        elif kind == "op":
            name = str(payload.get("op_name") or "")
            if not unproven:
                out[sid] = (Trust.UNKNOWN, name)
            else:
                out[sid] = ((Trust.OP_UNPROVEN if name in unproven
                             else Trust.OP_PROVEN), name)
    note["available"] = True
    note["nodes"] = len(out)
    return out, note


def fidelity_of(grade: str, hull_source: str, degeneracy: str) -> Fidelity:
    """Грейд + источник + вырожденность -> ФОРМА, которой элемент рисуется.

    Порядок проверок — не вкусовой. Вырожденность СТАРШЕ грейда: габарит
    нулевого объёма остаётся `coarse` по таблице грейдов, но телом он не
    является вообще, и рисовать его ящиком значило бы придумать ему толщину.
    """
    if degeneracy and degeneracy != "ok":
        return Fidelity.DEGENERATE
    if grade == "exact":
        return Fidelity.EXACT
    if grade == "conservative" or hull_source in ("profile", "prism",
                                                  "axis_section"):
        return Fidelity.SHAPED
    return Fidelity.BOX_ONLY


# ---------------------------------------------------------------------------
# Оси, по которым никто не обещал проверять — ПОЭЛЕМЕНТНО и ТРИСТЕЙТОМ
# ---------------------------------------------------------------------------
#
# `serving._unwitnessed_axes` отвечает не «нарушена ли ось», а «бралась ли она
# вообще проверять», и отвечает ТРЕМЯ состояниями:
#
#     {}          — каждый оп объявил обязательства по всем трём осям
#     {ось: опы}  — по этим осям обязательств нет, и названы виновники
#     None        — судить нечем (оп вне таблицы, таблица не поднялась)
#
# **`None` — это НЕ «всё хорошо»**, и именно поэтому здесь байт, а не флаг:
# двоичное «ок/не ок» слило бы третье состояние с первым, то есть показало бы
# зелёный там, где не смотрели. Ровно тот дефект, ради которого поле заведено.
#
# ПРАВИЛО НЕ КОПИРУЕТСЯ. Опрос идёт вызовом `serving._unwitnessed_axes`;
# здесь только УПАКОВКА ответа в байт. Две копии правила разошлись бы молча —
# тот же довод, по которому в `serving` копия одна.

#: Порядок битов. Публикуется в заголовке сцены: клиент не держит своей копии.
AXES_ORDER: tuple[str, ...] = ("geometry", "topology", "semantic")

#: «Судить нечем». Не ноль и не любая маска: ноль означает «все три
#: объявлены», а это противоположное утверждение.
AXES_UNJUDGEABLE = 255


def axes_byte(unwitnessed: Any) -> int:
    """Ответ `_unwitnessed_axes` -> один байт. Тристейт сохраняется.

    0 — все три оси объявлены; маска — по этим осям обязательств нет;
    `AXES_UNJUDGEABLE` — судить нечем.
    """
    if unwitnessed is None:
        return AXES_UNJUDGEABLE
    if not unwitnessed:
        return 0
    mask = 0
    for index, axis in enumerate(AXES_ORDER):
        if unwitnessed.get(axis):
            mask |= 1 << index
    # Непустой ответ, не попавший ни в один известный бит, — это НОВАЯ ось у
    # владельца таблицы. Отдать ноль значило бы сказать «всё объявлено» про
    # то, чего мы не поняли; отдаём «судить нечем».
    return mask if mask else AXES_UNJUDGEABLE


def axes_for_ops(op_names: Sequence[str]) -> Any:
    """Оси для НАБОРА операций. Тонкая обёртка над единственным правилом.

    Пустой список даёт `None`, а не `{}`: у элемента без операции нечего
    спрашивать, и это «судить нечем», а не «всё объявлено».
    """
    names = [str(n) for n in op_names if n]
    if not names:
        return None
    try:
        from kukai.ir.serving import _unwitnessed_axes
        return _unwitnessed_axes(names)
    except Exception:  # noqa: BLE001 — чужой модуль; его молчание не наш зелёный
        return None
