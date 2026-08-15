"""ТИПИЗИРОВАННЫЙ ГРАФ ЗДАНИЯ v1 — СОСТОЯНИЕ, над которым программа KIR есть
ТРАНЗАКЦИЯ, а Revit — один из бэкендов материализации.

Этот модуль не заводит седьмой граф. Он заводит ХРЕБЕТ, на который шесть
существующих ложатся как ИНДЕКСЫ, и делает это ровно потому, что замер показал:
у всех шести один и тот же адрес узла.

═══════════════════════════════════════════════════════════════════════════
ЗАМЕР, НА КОТОРОМ СТОИТ ВЕСЬ МОДУЛЬ (10.08.2026, прибор — сырой разбор
`L0.jsonl` и `tree.json` корпуса `backend/backend/data/decompile`,
машинно-локальный, 76 каталогов / 67 с `L0.jsonl` / 52 с `tree.json`)
═══════════════════════════════════════════════════════════════════════════

**1. Адрес узла решён, и решён ПОЛНОСТЬЮ.** `source_element_id` листа L1 —
БИЕКЦИЯ на `element_id` из L0, на **52 деревьях из 52**: 540 461 лист против
1 139 477 элементов, **0** повторов `element_id` во всём корпусе, 0 листьев с
адресом вне L0, 0 элементов без листа в тех снимках, где дерево есть. Это не
«скорее всего так» — это перебор всего корпуса. Хребет графа поэтому есть САМ
НАБОР ЭЛЕМЕНТОВ L0, а не новый идентификатор.

**2. Адресное пространство ОДНО, включая комнаты, уровни и оси.** Замерено на
четырёх зданиях: комнаты — 7 841/7 841 лежат в наборе элементов (категория
`OST_Rooms`), уровни — 170/170, оси — 122/122, и каждый `level_id`, на который
ссылается элемент, сам является элементом. Значит комната и уровень — ОБЫЧНЫЕ
узлы этого графа, отличаемые категорией, а не параллельная сущность со своим
пространством имён. `modeling/checker/spatial_model.py` строит типизированный
мир с собственными `Room.id`/`Level.id` — и эти id УЖЕ являются id элементов;
параллельный мир адресно совместим с графом и просто не знает об этом.

**3. `host_id` несёт ответ, но НЕ ВЕЗДЕ, и разница названа.** По корпусу:
213 811 элементов (18.76 %) несут `host_id`, из них **1 263 ВИСЯЧИХ** (0.59 %)
— хозяин не является элементом ЭТОГО снимка. Средняя врёт: висячесть
СОСРЕДОТОЧЕНА. `snowdon_elec_v1` (*Snowdon Towers Sample Electrical*) — **959
из 1 001, 95.8 %**; четыре снимка *Snowdon Plumbing* — **54/54, 54/54, 54/54,
50/50, то есть 100 %**. Хозяин там лежит в СВЯЗАННОМ файле, которого в
однораздельном разборе нет. Поэтому у ребра `hosted_in` ТРИ исхода, а не два:
хозяин найден / хозяина элемент не объявлял / **хозяин объявлен и лежит ВНЕ
извлечения**. Третий — это ровно закон «отсутствующий индекс и пустой индекс —
разные факты», применённый к ребру. Ребро, которого нет, потому что мы не
читали связь, не должно быть неотличимо от ребра, которого нет в здании.

**4. `host_source` — 0 строк из 1 139 477, И ЭТО ЧИСЛО О КОРПУСЕ, А НЕ О
ЧИТАТЕЛЕ.** Соблазн прочесть ноль как «ветка сломана» велик и НЕВЕРЕН; проверено
датами, а не рассуждением:

    захват `host_source` лёг в `extract.py`   **2026-08-09 22:24:57** (`6a90a7e1`)
    самый СВЕЖИЙ снимок корпуса               **2026-08-04 16:59** (`k2_ar_rd_v15`)

Все 67 снимков сняты РАНЬШЕ волны — на пять суток и более. Значит инструмент не
отказал, он НИ РАЗУ НЕ ЗАПУСКАЛСЯ, а это, по закону этого пакета, разные факты.

Ветка вдобавок НЕ МОЖЕТ дать `host_id` без `host_source`: в `_host_readers_cs`
оба поля присваиваются в ОДНОМ блоке `if`, поэтому непустой хозяин без
названного источника структурно неконструируем. Старый корпус это подтверждает
косвенно и точно: до волны хозяина заполняло единственное приведение к
`FamilyInstance`, и в корпусе хозяина имеют ровно экземпляры семейств (двери
153/153, окна 31/31, импосты 1 452/1 452), тогда как системные элементы —
ограждения, проёмы, фундаменты — не имеют его почти нигде (2 453 ограждения,
хозяин у 24, то есть 1.0 %).

Цена одного прогона названа заранее: **2 485 элементов корпуса** попадают под
новые ветки таблицы (`OST_StairsRailing` 2 453, `OST_FloorOpening` 27,
`OST_StructuralFoundation` 5), и сегодня хозяина из них несут 24. Поле поэтому
НЕ удаляется и НЕ считается мёртвым — оно ждёт одного разбора против живого
Revit. Здесь оно читается, а его отсутствие называется «не мерили» и никогда не
трактуется как `family_instance`.

═══════════════════════════════════════════════════════════════════════════
ДВЕ ОСИ УЗЛА, ОБЕ В v1 — ИНАЧЕ ПОЯВИТСЯ СЕДЬМОЙ ГРАФ
═══════════════════════════════════════════════════════════════════════════

**`authority` — несущая линия. Граф авторитетен для ОБЪЯВЛЕННОГО, Revit — для
ВЫВЕДЕННОГО.** Сегодня это различие живёт в голове автора; здесь оно свойство
узла.

НАПРАВЛЕНИЕ ОТКАЗА ВЫБРАНО ПО ЦЕНЕ ОШИБКИ, А НЕ ПО ВКУСУ, и цена замерена.
Назвать объявленное выведенным — значит вынуть элемент из пересборки: он уходит
из ЧИСЛИТЕЛЯ и ЗНАМЕНАТЕЛЯ одновременно, поэтому метрика почти не шевелится,
пока пропадает половина модели. Замер 10.08 на `snowdon_plumb_v4`: перевод
MEP-фитингов в порождаемые убрал бы **14 713 из 31 998 опов (46.0 %)**, а
`honest_pct` сдвинулся бы **99.42 % → 98.93 %** — 0.49 п.п. за половину здания.
Назвать выведенное объявленным дешевле и ГРОМЧЕ: получится лишний оп, который
виден. Поэтому:

* умолчание — `DECLARED`, и оно fail-closed;
* `DERIVED_BY_REVIT` ставится ТОЛЬКО по НАЗВАННОМУ свидетелю, и свидетель
  едет в узле (`authority_source`);
* **категорийная таблица свидетелем НЕ является.** Это прямой запрет, а не
  стилистика: категорийный приор не знает, кто элемент создаёт, и ровно на нём
  строилась отозванная 10.08 заявка про фитинги. `family_placement.index.json`
  даёт всем 14 713 фитингам то же самое, что 870 настоящим авторским приборам
  (`OneLevelBased`, `host_id: null`, `super_component_id: null`) — различить по
  данным нечем, а значит и объявлять нечего.

**`existence` — потому что продукт есть ВЬЮЕР.** Инженер строит здание в чате
три часа и лишь в конце жмёт «отправить в Revit». Непостроенное здание обязано
быть выразимо в графе с первого дня, иначе вьюер получит своё представление —
и это будет седьмой граф. `MATERIALIZED` — узел прочитан из документа,
`PLANNED` — узел объявлен программой, которая ещё не исполнялась.

Оси ОРТОГОНАЛЬНЫ, и все четыре сочетания осмысленны. `planned` +
`derived_by_revit` — самое интересное: программа сказала «соедини трубы», и
фитинги ПОЯВЯТСЯ, но их ещё нет и объявлять их геометрию нельзя. Вьюер обязан
рисовать такой узел иначе, чем объявленную трубу, а не одинаковым телом.

═══════════════════════════════════════════════════════════════════════════
ЗАКОН ПЕРЕПИСИ
═══════════════════════════════════════════════════════════════════════════

`узлов = оценённых + названных отказов`. Тот же закон, что у переписи CLASH
(`eligible = hulled + unsupported + missing_geometry`), но на всех узлах.
Граф, у которого перепись не сходится, врёт молча ровно так же, как врал бы
детектор. `GraphCensus.assert_balanced()` — не отчёт, а условие построения.

ИНЕРТНОСТЬ ДЕРЖИТ ФЛАГ, А НЕ ОТСУТСТВИЕ ИМПОРТА. Прежняя редакция этого
абзаца утверждала, что модуль «не импортируется рабочим путём». Замер
11.08.2026 (обход импортов по AST от `kukai.main`/`kukai.__main__`, дерево
`aecf6cff`) это опровергает: модуль ДОСТИЖИМ, его импортируют
`kukai/viewer/scene.py:62` и `kukai/viewer/graph.py:124`. Управление сюда
доходит и останавливается на гейте — `building_graph_enabled()`
(`KUKAI_IR_BUILDING_GRAPH`, умолчание ВЫКЛ), который вызывающие проверяют
ДО обращения к графу (`scene.py:141`, `graph.py:127`).

Разница не косметическая: «не импортируется» читается как свойство графа
вызовов и проверяется обходом, который его опровергает; «закрыт выключенным
флагом» — свойство одного `os.getenv`, и оно верно. Модуль по-прежнему
ничего не подключает и ничего не переписывает, и на живом Revit не сверялся
ни разу — именно поэтому гейт стоит.

`kukai/modeling/checker/` читается только на чтение и здесь не импортируется
вовсе.
"""
from __future__ import annotations

import math
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, Sequence

from kukai.ir.decompile.identity import (
    DefinitionIdentity,
    DocumentIdentity,
    FederationContext,
    IdentityError,
    IdentityGap,
    IdentityStatus,
    OccurrenceIdentity,
    identity_context_from_l0,
    resolve_element_identity,
)

__all__ = [
    "Authority",
    "AuthoritySource",
    "BuildingGraph",
    "Existence",
    "DefinitionIdentity",
    "DocumentIdentity",
    "FederationContext",
    "graph_view",
    "NodeView",
    "GraphView",
    "GraphBuildError",
    "GraphCensus",
    "GraphEdge",
    "GraphNode",
    "IdentityGap",
    "IdentityStatus",
    "Modality",
    "NodeRefusal",
    "OutsideExtraction",
    "OccurrenceIdentity",
    "Relation",
    "building_graph_enabled",
    "graph_from_l0",
    "outer_size_mm",
]


class GraphBuildError(ValueError):
    """Типизированный отказ построения графа. Молчания здесь нет."""


def _freeze_json(value: Any, *, path: str) -> Any:
    """Snapshot JSON-like evidence so a built graph cannot change underneath.

    Frozen dataclasses are only shallowly immutable.  Before this boundary a
    caller could mutate ``GraphNode.section`` or ``GraphEdge.evidence`` after
    the census and federation had accepted them.  That turns an already-issued
    proof into different evidence.  Keep the accepted vocabulary deliberately
    small and deterministic instead of retaining arbitrary live objects.
    """

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GraphBuildError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            if not isinstance(key, str):
                raise GraphBuildError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value))
    raise GraphBuildError(
        f"{path} contains unsupported {type(value).__name__}")


def building_graph_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF.

    Модуль лежит на складе намеренно: он ещё ни разу не сверялся с живым
    Revit, и «встроен» от «написан» этот пакет отличает флагом, а не
    самочувствием автора.
    """
    return os.getenv("KUKAI_IR_BUILDING_GRAPH", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ═══════════════════════════════════ ОСИ УЗЛА


class Authority(str, Enum):
    """КТО авторитетен для этого узла. Несущая линия всей затеи."""

    #: Объявлено автором (программой или прочитанным документом). Граф — истина.
    DECLARED = "declared"
    #: Выведено Revit из объявленного. Revit — истина; граф хранит лишь ФАКТ,
    #: что узел будет выведен, и НИКОГДА не объявляет его геометрию.
    DERIVED_BY_REVIT = "derived_by_revit"


class AuthoritySource(str, Enum):
    """ЧЕМ решено значение `authority` — свидетель, а не мнение.

    Тот же приём, что `default_panel_source` у витражей и `host_source` у
    хозяина: читать несколько источников и записывать, КОТОРЫЙ ответил, чтобы
    одно значение не означало три разные правды.
    """

    #: Элемент прочитан из документа как самостоятельная строка L0.
    L0_ELEMENT = "l0_element"
    #: Лифтер назвал элемент порождаемым родителем (`AtomReason.GENERATOR_CHILD`).
    #: ЕДИНСТВЕННЫЙ свидетель выведенности, который сегодня есть в данных.
    LIFTER_GENERATOR_CHILD = "lifter_generator_child"
    #: Оп программы объявил узел (прямой ход).
    PROGRAM_OP = "program_op"
    #: Контракт опа объявляет побочные элементы выведенными (`route_*`).
    #: Требует ЯВНОГО указания вызывающим; из категории не выводится.
    OP_DERIVED_CONTRACT = "op_derived_contract"


class Existence(str, Enum):
    """СУЩЕСТВУЕТ ли узел в документе, или пока только объявлен."""

    #: Прочитан из документа: строка L0 либо подтверждённая постройка.
    MATERIALIZED = "materialized"
    #: Объявлен программой, которая ещё не исполнялась. Вьюер обязан рисовать
    #: такой узел иначе, а не тем же телом.
    PLANNED = "planned"


class NodeRefusal(str, Enum):
    """Названная причина, по которой строка НЕ стала узлом.

    Перепись сходится только вместе с этим перечислением: «узлов меньше, чем
    строк» без названной причины — это молчаливое выпадение, ровно тот дефект,
    против которого написан закон переписи.
    """

    #: У строки нет непустого `element_id` — адресовать нечем.
    NO_ADDRESS = "no_address"
    #: Адрес уже занят другой строкой. По корпусу этого НЕ НАБЛЮДАЛОСЬ
    #: (0 повторов на 1 139 477 строк), но отказ обязан существовать: закон
    #: держится проверкой, а не удачей корпуса.
    DUPLICATE_ADDRESS = "duplicate_address"


class OutsideExtraction(str, Enum):
    """ПОЧЕМУ цель ребра не разрешилась. Обязательна на каждом
    `Modality.UNRESOLVED_TARGET`: «цель вне извлечения» без под-причины — это
    снова одно слово на разные факты.

    ЗАМЕР 10.08 ОПРОВЕРГ ГИПОТЕЗУ, ЧТО ЭТО ОДНА ГРАНИЦА. Висячий `host_id` и
    висячий `bounds_room` суть РАЗНЫЕ популяции, и распределения расходятся на
    три порядка:

        `snowdon_elec_v1`  host: 959 рёбер -> **3** различных цели (все — `link`)
        `snowdon_plumb_v5` host:  86 рёбер -> **4** цели; bounds_room: 0
        `демо-v3`          host:   0;  bounds_room: 4 352 ребра -> **2 146**
                           различных целей, медиана 2 ребра на цель
        `sob62_r23_v5`     host:   1;  bounds_room: 340 -> 184 цели

    Пересечение множеств целей: **0** на трёх зданиях, **1** на `sob62_r23_v5`
    (и та единица — запись `link`). Слить их в одно понятие значило бы
    повторить ровно тот дефект, ради разбора которого писан весь модуль.
    """

    #: Цель есть запись `link` — разрешено ТОЧНО, ребро не висячее вовсе.
    #: Оставлено в перечислении, чтобы «разрешилось в связь» имело имя.
    RESOLVED_TO_LINK = "resolved_to_link"
    #: Цель не является ни элементом, ни связью этого снимка. Честное «нет
    #: данных»: чем она была, снимок НЕ ГОВОРИТ, и догадываться нечем — строки
    #: с этим адресом в потоке нет вовсе.
    TARGET_NOT_IN_SNAPSHOT = "target_not_in_snapshot"
    #: Хозяин НЕ МОЖЕТ ИМЕТЬ ТЕЛА ПО ПРИРОДЕ (опорная плоскость и подобное).
    #:
    #: ЭТО НЕ ГРАНИЦА ИЗВЛЕЧЕНИЯ, А СВОЙСТВО ВЕЩИ, и потому класс отдельный:
    #: связь можно дочитать, опорную плоскость дочитывать НЕЧЕГО — телом она
    #: не станет никогда. Замер команды клешей по корпусу: из 1 263 висячих
    #: рёбер **1 010 указывают в связанный файл**, а **86 — в `ReferencePlane`**,
    #: который `clash/hulls.KIND_TABLE` относит к `not_a_body`.
    #:
    #: ЗНАЧЕНИЕ НЕ ВЫВОДИТСЯ ИЗ L0 И НЕ УГАДЫВАЕТСЯ ЗДЕСЬ. Адреса этих целей в
    #: потоке нет, поэтому категорию их сказать нечем; знание живёт в таблице
    #: родов у клешей. Вызывающий, у которого она есть, подаёт список явно
    #: (`bodiless_target_ids`) — ровно так же, как `generator_child_ids`
    #: подаёт единственного свидетеля выведенности. Граф, назначающий этот
    #: класс сам, вернул бы догадку по категории, от которой мы и уходим.
    HOST_CANNOT_HAVE_A_BODY = "host_cannot_have_a_body"
    #: Граница помещения ссылается на элемент, которого чтение не положило в
    #: поток. Массовый случай `демо-v3`: 2 146 различных целей.
    BOUNDARY_ELEMENT_NOT_EXTRACTED = "boundary_element_not_extracted"
    #: Уровень, названный элементом, отсутствует среди элементов снимка.
    LEVEL_NOT_IN_SNAPSHOT = "level_not_in_snapshot"


# ═══════════════════════════════════ ОСИ РЕБРА


class Relation(str, Enum):
    """ЧТО за отношение. Ось ортогональна `Modality` — это и есть исправление.

    Сегодня «находка клеша» склеивает касание, взаимопроникновение тел и
    пересечение оболочек в одно слово, и вся неточность растёт из склейки.
    Здесь отношение и доказанность разведены по разным осям.
    """

    # --- рёбра СБОРКИ: свойство здания, живут рядом с узлами постоянно ---
    #: Элемент размещён В хозяине (`L0Element.host_id`). Дверь в стене,
    #: импост в витраже. НЕ то же, что «стоит на уровне» — см. `PLACED_ON_DATUM`.
    HOSTED_IN = "hosted_in"
    #: Элемент размещён в СВЯЗАННОМ ДОКУМЕНТЕ: хозяин есть запись `link` этого
    #: же потока L0. Это НЕ «хозяин потерялся» и НЕ «хозяина нет» — это точный,
    #: положительный факт, и поток его несёт.
    #:
    #: ЗАМЕР 10.08 (сырой разбор `L0.jsonl`): `snowdon_elec_v1` — 959 из 1 001
    #: объявленных хозяев указывают ВСЕГО НА ТРИ адреса, и все три суть записи
    #: `link` (`1362428`, `1362762`, `1484390`). `sob62_r23_v5` — единственный
    #: висячий хозяин `20704534` тоже запись `link`, и он же несёт 88 рёбер
    #: границы помещения. До этого разбора все они назывались «вне извлечения»,
    #: то есть НАШЕЙ слепотой; на деле L0 знал ответ и его никто не спрашивал.
    HOSTED_IN_LINK = "hosted_in_link"
    #: Хозяином объявлен НЕ физический элемент, а отметка (`OST_Levels`).
    #: Замер: `snowdon_plumb_v5` — 21 `OST_GenericModel` и 4 `OST_PlumbingFixtures`
    #: хозяином имеют уровень. Сваливать это в `hosted_in` значило бы повторить
    #: ту же склейку, ради разбора которой написан весь модуль.
    PLACED_ON_DATUM = "placed_on_datum"
    #: Элемент отнесён к уровню (`L0Element.level_id`).
    ON_LEVEL = "on_level"
    #: Уровень непосредственно выше другого (по отметке).
    LEVEL_ABOVE = "level_above"
    #: Элемент входит в границу комнаты (`RoomInfo.bounding_element_ids`).
    BOUNDS_ROOM = "bounds_room"

    # --- ДВА ПРЕДИКАТА СМЕЖНОСТИ КОМНАТ, названные РАЗНО (Ш4) ---
    #: A. Обе комнаты ограничены ОДНИМ И ТЕМ ЖЕ хозяином проёма.
    #: Предикат `fold._semantic_fold`. Факт об ОБЪЯВЛЕНИИ Revit (расчёт границ
    #: помещения), не о геометрии проёма. Ребро возникает ТОЛЬКО когда хозяин
    #: ограничивает РОВНО две комнаты.
    BOUNDED_BY_SAME_WALL = "bounded_by_same_wall"
    #: B. ТОЧКА проёма касается полигона комнаты в пределах допуска.
    #: Предикат `design_check._openings.touching`. Факт об ИЗМЕРЕННОЙ геометрии.
    OPENING_POINT_TOUCHES_ROOM = "opening_point_touches_room"


class Modality(str, Enum):
    """НАСКОЛЬКО отношение доказано. Ортогональна `Relation`.

    `REFUTED` — не отсутствие ребра, а ребро с именем правила, которое его
    сняло (`GraphEdge.refuted_by`). Без этого «не нашли» неотличимо от «не
    искали», и обе болезни возвращаются: ровно на склейке модальности с
    отношением сломались `plate_z_doubling` и `profile_convexified`.
    """

    #: Отношение прочитано из документа либо доказано.
    PROVEN = "proven"
    #: Отношение допускается имеющимися данными, но не доказано ими.
    POSSIBLE = "possible"
    #: Отношение ОПРОВЕРГНУТО названным правилом. Ребро ОСТАЁТСЯ в графе.
    REFUTED = "refuted"
    #: Отношение объявлено источником, но проверить его нечем — ЦЕЛЬ ВНЕ
    #: ИЗВЛЕЧЕНИЯ. Это НЕ `possible`: там данных хватает и ответ неизвестен,
    #: здесь данных нет вовсе. Замер: 959 из 1 001 `host_id` в
    #: `snowdon_elec_v1` указывают за пределы снимка.
    UNRESOLVED_TARGET = "unresolved_target"


_SYMMETRIC_RELATIONS = frozenset({
    Relation.BOUNDED_BY_SAME_WALL,
    Relation.OPENING_POINT_TOUCHES_ROOM,
})


# ═══════════════════════════════════ УЗЕЛ И РЕБРО


@dataclass(frozen=True, slots=True)
class GraphNode:
    """Узел графа with a legacy local alias and federated identities.

    ``node_id`` remains the L0 ``ElementId`` string for compatibility with
    existing local edges and queries.  It is not authoritative outside one
    document.  ``definition_identity`` and ``occurrence_identity`` are the
    collision-free semantic addresses; legacy rows name their gaps instead
    of silently promoting ``ElementId`` to a global identity.
    """

    node_id: str
    category: str
    authority: Authority
    authority_source: AuthoritySource
    existence: Existence
    level_id: str | None = None
    type_id: str | None = None
    type_name: str | None = None
    #: `HostSource` строкой, либо None = «не мерили». По корпусу — None ВЕЗДЕ
    #: (0 строк из 1 139 477). Трактовать None как `family_instance` запрещено.
    host_source: str | None = None
    #: ИЗМЕРЕННОЕ СЕЧЕНИЕ: параметры из закрытого списка `SECTION_PARAM_NAMES`,
    #: как их прислало чтение, ключ — имя `BuiltInParameter`, оно же провенанс.
    #:
    #: ЗАЧЕМ ЭТО ЗДЕСЬ, А НЕ В ОПЕ. Замер 10.08 (`snowdon_plumb_v4`): L0 несёт
    #: наружный диаметр для **15 342 труб из 15 342**, а `lift._lift_pipe`
    #: читает только `RBS_PIPE_DIAMETER_PARAM` (номинал) и наружный роняет.
    #: Восстановить его из номинала НЕЛЬЗЯ, и это не мнение: тот же номинал
    #: **50.8 даёт ДВА разных наружных** — 60.325 (1 835 труб) и 53.975
    #: (530 труб). Наружный есть функция ТИПА, а не номинала; совпадают они
    #: лишь у 20 труб из 15 342.
    section: Mapping[str, Any] = field(default_factory=dict)
    definition_identity: DefinitionIdentity | None = None
    occurrence_identity: OccurrenceIdentity | None = None
    identity_status: IdentityStatus = IdentityStatus.INCOMPLETE
    identity_gaps: tuple[IdentityGap, ...] = (
        IdentityGap.LEGACY_CONTEXT_ABSENT,)

    @property
    def local_element_id(self) -> str:
        """Compatibility alias; never use as a cross-document identity."""
        return self.node_id

    @property
    def identity_authoritative(self) -> bool:
        return self.identity_status is IdentityStatus.AUTHORITATIVE

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise GraphBuildError("GraphNode.node_id must be a non-empty string")
        if not isinstance(self.category, str) or not self.category:
            raise GraphBuildError("GraphNode.category must be a non-empty string")
        if not isinstance(self.authority, Authority):
            raise GraphBuildError("GraphNode.authority must be an Authority")
        if not isinstance(self.authority_source, AuthoritySource):
            raise GraphBuildError(
                "GraphNode.authority_source must be an AuthoritySource — "
                "значение `authority` без названного свидетеля запрещено")
        if not isinstance(self.existence, Existence):
            raise GraphBuildError("GraphNode.existence must be an Existence")
        if not isinstance(self.section, Mapping):
            raise GraphBuildError("GraphNode.section must be a mapping")
        object.__setattr__(
            self, "section", _freeze_json(self.section, path="GraphNode.section"))
        if not isinstance(self.identity_status, IdentityStatus):
            raise GraphBuildError("GraphNode.identity_status must be typed")
        if isinstance(self.identity_gaps, str):
            raise GraphBuildError("GraphNode.identity_gaps must be a sequence")
        gaps = tuple(self.identity_gaps)
        if any(not isinstance(gap, IdentityGap) for gap in gaps):
            raise GraphBuildError("GraphNode.identity_gaps must contain IdentityGap")
        if len(gaps) != len(set(gaps)):
            raise GraphBuildError("GraphNode.identity_gaps must be unique")
        object.__setattr__(self, "identity_gaps", gaps)
        if (self.definition_identity is not None
                and not isinstance(self.definition_identity, DefinitionIdentity)):
            raise GraphBuildError("GraphNode.definition_identity must be typed")
        if (self.occurrence_identity is not None
                and not isinstance(self.occurrence_identity, OccurrenceIdentity)):
            raise GraphBuildError("GraphNode.occurrence_identity must be typed")
        if (self.occurrence_identity is not None
                and self.occurrence_identity.definition != self.definition_identity):
            raise GraphBuildError(
                "occurrence identity must reference the node definition identity")
        if self.identity_status is IdentityStatus.AUTHORITATIVE:
            if (self.definition_identity is None
                    or self.occurrence_identity is None or gaps):
                raise GraphBuildError(
                    "authoritative identity requires definition, occurrence, "
                    "and zero gaps")
        else:
            if self.occurrence_identity is not None:
                raise GraphBuildError(
                    "an occurrence identity cannot be marked incomplete")
            if not gaps:
                raise GraphBuildError(
                    "incomplete identity must name at least one gap")


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """Ребро: отношение, модальность и ЧЕМ это доказано либо опровергнуто.

    `refuted_by` обязателен ровно при `Modality.REFUTED` и запрещён иначе —
    опровержение без имени правила есть то самое молчание, от которого модуль
    лечится, а имя правила при недоказанном ребре есть ложный след.
    """

    relation: Relation
    src: str
    dst: str
    modality: Modality
    #: Имя ПРАВИЛА, снявшего ребро. Обязательно при REFUTED, иначе запрещено.
    refuted_by: str | None = None
    #: Чем ребро подтверждено: источник, поле, допуск, огрубление.
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.relation, Relation):
            raise GraphBuildError("GraphEdge.relation must be a Relation")
        if not isinstance(self.modality, Modality):
            raise GraphBuildError("GraphEdge.modality must be a Modality")
        for name, value in (("src", self.src), ("dst", self.dst)):
            if not isinstance(value, str) or not value:
                raise GraphBuildError(f"GraphEdge.{name} must be a non-empty string")
        if self.modality is Modality.REFUTED:
            if (not isinstance(self.refuted_by, str)
                    or not self.refuted_by.strip()):
                raise GraphBuildError(
                    "REFUTED без `refuted_by` неотличим от «не искали» — "
                    "правило, снявшее ребро, обязано назваться")
        elif self.refuted_by is not None:
            raise GraphBuildError(
                "`refuted_by` при модальности, отличной от REFUTED, — ложный след")
        if not isinstance(self.evidence, Mapping):
            raise GraphBuildError("GraphEdge.evidence must be a mapping")
        object.__setattr__(
            self, "evidence",
            _freeze_json(self.evidence, path="GraphEdge.evidence"))

    @property
    def key(self) -> tuple[str, str, str]:
        src, dst = self.src, self.dst
        if self.relation in _SYMMETRIC_RELATIONS:
            src, dst = sorted((src, dst))
        return (self.relation.value, src, dst)


# ═══════════════════════════════════ ПЕРЕПИСЬ


@dataclass(frozen=True, slots=True)
class GraphCensus:
    """`узлов = оценённых + названных отказов`. Условие, а не отчёт."""

    rows_seen: int
    nodes: int
    refusals: Mapping[str, int]
    identity_authoritative_nodes: int = 0
    identity_incomplete_nodes: int | None = None
    identity_gaps: Mapping[str, int] = field(default_factory=dict)
    identity_context_authoritative: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("rows_seen", self.rows_seen),
            ("nodes", self.nodes),
            ("identity_authoritative_nodes",
             self.identity_authoritative_nodes),
        ):
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise GraphBuildError(
                    f"GraphCensus.{name} must be a non-negative int")
        if not isinstance(self.identity_context_authoritative, bool):
            raise GraphBuildError(
                "GraphCensus.identity_context_authoritative must be boolean")
        incomplete = self.identity_incomplete_nodes
        if incomplete is None:
            incomplete = self.nodes - self.identity_authoritative_nodes
            object.__setattr__(self, "identity_incomplete_nodes", incomplete)
        if (isinstance(incomplete, bool) or not isinstance(incomplete, int)
                or incomplete < 0):
            raise GraphBuildError(
                "GraphCensus.identity_incomplete_nodes must be a "
                "non-negative int or null")

        if not isinstance(self.refusals, Mapping):
            raise GraphBuildError("GraphCensus.refusals must be a mapping")
        refusals: dict[str, int] = {}
        for name, count in self.refusals.items():
            if not isinstance(name, str) or not name.strip():
                raise GraphBuildError(
                    "GraphCensus refusal keys must be non-empty strings")
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise GraphBuildError(
                    "GraphCensus refusal counts must be non-negative ints")
            if count:
                refusals[name] = count

        if not isinstance(self.identity_gaps, Mapping):
            raise GraphBuildError(
                "GraphCensus.identity_gaps must be a mapping")
        gaps: dict[str, int] = {}
        for name, count in self.identity_gaps.items():
            if not isinstance(name, str) or not name.strip():
                raise GraphBuildError(
                    "identity gap census keys must be non-empty strings")
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise GraphBuildError(
                    "identity gap census counts must be non-negative ints")
            if count:
                gaps[name] = count
        if incomplete and not gaps:
            # Compatibility for direct v1 GraphCensus construction.  It is
            # explicit and red, never silently treated as authoritative.
            gaps = {IdentityGap.LEGACY_CONTEXT_ABSENT.value: incomplete}
        object.__setattr__(
            self, "refusals", MappingProxyType(dict(sorted(refusals.items()))))
        object.__setattr__(
            self, "identity_gaps", MappingProxyType(dict(sorted(gaps.items()))))
        self.assert_balanced()

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    @property
    def identity_authoritative(self) -> bool:
        return (self.identity_context_authoritative
                and self.identity_authoritative_nodes == self.nodes
                and self.identity_incomplete_nodes == 0
                and not self.identity_gaps)

    def assert_balanced(self) -> None:
        if self.nodes + self.refused != self.rows_seen:
            raise GraphBuildError(
                f"перепись графа не сходится: строк {self.rows_seen}, "
                f"узлов {self.nodes}, названных отказов {self.refused} "
                f"(молчаливое выпадение "
                f"{self.rows_seen - self.nodes - self.refused})")
        if (self.identity_authoritative_nodes
                + (self.identity_incomplete_nodes or 0) != self.nodes):
            raise GraphBuildError(
                "перепись identity не сходится: "
                f"узлов {self.nodes}, authoritative "
                f"{self.identity_authoritative_nodes}, incomplete "
                f"{self.identity_incomplete_nodes}")
        if ((self.identity_incomplete_nodes or 0) > 0
                and sum(self.identity_gaps.values())
                < (self.identity_incomplete_nodes or 0)):
            raise GraphBuildError(
                "не каждый identity-incomplete узел назвал причину")


# ═══════════════════════════════════ ГРАФ


class BuildingGraph:
    """Типизированный граф здания: узлы с адресом L0 + рёбра с модальностью.

    Клеш-рёбра здесь НЕ ЖИВУТ и жить не могут — замер называет порог заранее:
    `демо-v3` даёт 84 120 узлов против 770 234 пар-кандидатов (отношение
    **9.15**), отчёт 666 МБ, пик RSS 2.66 ГБ. Клеш входит в граф ЗАПРОСОМ С
    ОБЛАСТЬЮ — см. `graph_clash_query.py`.
    """

    __slots__ = (
        "doc_name", "document_identity", "federation_context",
        "_nodes", "_edges", "census", "_out", "_in", "_by_relation",
        "_by_definition", "_by_occurrence",
    )

    def __init__(
        self,
        *,
        doc_name: str,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        census: GraphCensus,
        document_identity: DocumentIdentity | None = None,
        federation_context: FederationContext | None = None,
    ) -> None:
        if (document_identity is not None
                and not isinstance(document_identity, DocumentIdentity)):
            raise GraphBuildError("document_identity must be typed")
        if (federation_context is not None
                and not isinstance(federation_context, FederationContext)):
            raise GraphBuildError("federation_context must be typed")
        self.doc_name = doc_name
        self.document_identity = document_identity
        self.federation_context = federation_context
        mutable_nodes: dict[str, GraphNode] = {}
        by_definition: dict[DefinitionIdentity, list[GraphNode]] = defaultdict(list)
        by_occurrence: dict[OccurrenceIdentity, GraphNode] = {}
        identity_authoritative_nodes = 0
        identity_incomplete_nodes = 0
        identity_gaps: Counter[str] = Counter()
        for node in nodes:
            if not isinstance(node, GraphNode):
                raise GraphBuildError("BuildingGraph nodes must be GraphNode")
            if node.node_id in mutable_nodes:
                raise GraphBuildError(
                    f"повтор адреса узла {node.node_id!r}")
            mutable_nodes[node.node_id] = node
            if node.definition_identity is not None:
                by_definition[node.definition_identity].append(node)
            if node.occurrence_identity is not None:
                if node.occurrence_identity in by_occurrence:
                    raise GraphBuildError(
                        "повтор authoritative occurrence identity "
                        f"{node.occurrence_identity.key}")
                by_occurrence[node.occurrence_identity] = node
            if node.identity_authoritative:
                identity_authoritative_nodes += 1
            else:
                identity_incomplete_nodes += 1
                identity_gaps.update(gap.value for gap in node.identity_gaps)
        edge_rows = tuple(edges)
        if any(not isinstance(edge, GraphEdge) for edge in edge_rows):
            raise GraphBuildError("BuildingGraph edges must be GraphEdge")
        edge_keys = [edge.key for edge in edge_rows]
        if len(edge_keys) != len(set(edge_keys)):
            raise GraphBuildError(
                "duplicate relation/src/dst edge truth is forbidden")
        self._edges = edge_rows
        self.census = census
        if not isinstance(census, GraphCensus):
            raise GraphBuildError("BuildingGraph census must be GraphCensus")
        census.assert_balanced()
        if (census.identity_authoritative_nodes != identity_authoritative_nodes
                or census.identity_incomplete_nodes != identity_incomplete_nodes
                or dict(census.identity_gaps) != dict(identity_gaps)):
            raise GraphBuildError(
                "identity census does not match GraphNode identity states")
        context_authoritative = (
            document_identity is not None and federation_context is not None)
        if census.identity_context_authoritative != context_authoritative:
            raise GraphBuildError(
                "identity context census disagrees with graph context")

        out: dict[str, list[GraphEdge]] = defaultdict(list)
        incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        by_relation: dict[Relation, list[GraphEdge]] = defaultdict(list)
        for edge in self._edges:
            src_local = edge.src in mutable_nodes
            dst_local = edge.dst in mutable_nodes
            if edge.modality is Modality.UNRESOLVED_TARGET:
                if src_local == dst_local:
                    raise GraphBuildError(
                        "UNRESOLVED_TARGET requires exactly one local endpoint "
                        "and one external endpoint")
                why = edge.evidence.get("why")
                if why not in {item.value for item in OutsideExtraction}:
                    raise GraphBuildError(
                        "UNRESOLVED_TARGET requires a typed evidence.why")
            elif (edge.relation is Relation.HOSTED_IN_LINK
                  and edge.modality is Modality.PROVEN):
                if not src_local:
                    raise GraphBuildError(
                        "HOSTED_IN_LINK requires a local source node")
                if (edge.evidence.get("why")
                        != OutsideExtraction.RESOLVED_TO_LINK.value):
                    raise GraphBuildError(
                        "HOSTED_IN_LINK requires exact resolved_to_link evidence")
                # The link row is a typed L0 external reference.  Its exact id
                # may also be represented locally by a future graph revision;
                # both cases remain unambiguous under this relation tag.
            elif not src_local or not dst_local:
                raise GraphBuildError(
                    "ordinary graph edges require two assembled local nodes")
            out[edge.src].append(edge)
            incoming[edge.dst].append(edge)
            by_relation[edge.relation].append(edge)

        self._nodes = MappingProxyType(mutable_nodes)
        self._by_definition = MappingProxyType({
            identity: tuple(rows) for identity, rows in by_definition.items()})
        self._by_occurrence = MappingProxyType(by_occurrence)
        self._out = MappingProxyType({
            node_id: tuple(rows) for node_id, rows in out.items()})
        self._in = MappingProxyType({
            node_id: tuple(rows) for node_id, rows in incoming.items()})
        self._by_relation = MappingProxyType({
            relation: tuple(rows) for relation, rows in by_relation.items()})

    # --- доступ ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    @property
    def nodes(self) -> Mapping[str, GraphNode]:
        return self._nodes

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return self._edges

    @property
    def identity_authoritative(self) -> bool:
        return self.census.identity_authoritative

    def nodes_for_definition(
            self, identity: DefinitionIdentity) -> tuple[GraphNode, ...]:
        if not isinstance(identity, DefinitionIdentity):
            raise GraphBuildError("definition lookup requires DefinitionIdentity")
        return tuple(self._by_definition.get(identity, ()))

    def node_for_occurrence(self, identity: OccurrenceIdentity) -> GraphNode:
        if not isinstance(identity, OccurrenceIdentity):
            raise GraphBuildError("occurrence lookup requires OccurrenceIdentity")
        try:
            return self._by_occurrence[identity]
        except KeyError:
            raise GraphBuildError(
                f"occurrence {identity.key!r} is not in the graph") from None

    def node(self, node_id: str) -> GraphNode:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise GraphBuildError(f"узла {node_id!r} в графе нет") from None

    def out_edges(self, node_id: str,
                  relation: Relation | None = None) -> tuple[GraphEdge, ...]:
        got = self._out.get(node_id, ())
        if relation is None:
            return tuple(got)
        return tuple(e for e in got if e.relation is relation)

    def in_edges(self, node_id: str,
                 relation: Relation | None = None) -> tuple[GraphEdge, ...]:
        got = self._in.get(node_id, ())
        if relation is None:
            return tuple(got)
        return tuple(e for e in got if e.relation is relation)

    def relation_edges(self, relation: Relation) -> tuple[GraphEdge, ...]:
        return tuple(self._by_relation.get(relation, ()))

    # --- своды ----------------------------------------------------------

    def authority_counts(self) -> Mapping[str, int]:
        return dict(Counter(n.authority.value for n in self._nodes.values()))

    def existence_counts(self) -> Mapping[str, int]:
        return dict(Counter(n.existence.value for n in self._nodes.values()))

    def relation_counts(self) -> Mapping[str, int]:
        return {rel.value: len(edges)
                for rel, edges in sorted(self._by_relation.items(),
                                         key=lambda kv: kv[0].value)
                if edges}

    def modality_counts(self,
                        relation: Relation | None = None) -> Mapping[str, int]:
        source = (self._by_relation.get(relation, ())
                  if relation is not None else self._edges)
        return dict(Counter(e.modality.value for e in source))

    def refuted_by_counts(self) -> Mapping[str, int]:
        """Чем именно снимались рёбра. Пустой свод и отсутствие свода — разное."""
        return dict(Counter(
            e.refuted_by for e in self._edges
            if e.modality is Modality.REFUTED and e.refuted_by))

    def unresolved_targets(self) -> tuple[GraphEdge, ...]:
        """Рёбра, чья ЦЕЛЬ вне извлечения. Главный межраздельный сигнал."""
        return tuple(e for e in self._edges
                     if e.modality is Modality.UNRESOLVED_TARGET)


# ═══════════════════════════════════ ПОСТРОЕНИЕ ИЗ L0


#: Категория, чей элемент есть ОТМЕТКА, а не тело. Хозяин-отметка едет по
#: `PLACED_ON_DATUM`, а не по `HOSTED_IN` — см. комментарий у Relation.
_DATUM_CATEGORIES: frozenset[str] = frozenset({"OST_Levels", "OST_Grids"})

_ROOM_CATEGORY = "OST_Rooms"


def _section_of(element: Mapping[str, Any]) -> dict[str, Any]:
    """Измеренные параметры сечения строки — по ЗАКРЫТОМУ списку чтения.

    Список берётся у `extract.SECTION_PARAM_NAMES`, а не переписывается: два
    словаря на один факт расходятся, и этот пакет уже платил за это (третий
    приватный словарь дисциплин, канон /4).
    """
    from kukai.ir.decompile.extract import SECTION_PARAM_NAMES

    params = element.get("params") or {}
    if not isinstance(params, Mapping):
        return {}
    return {name: params[name] for name in SECTION_PARAM_NAMES
            if params.get(name) is not None}


#: Параметры, несущие НАРУЖНЫЙ размер тела, в порядке предпочтения.
#: Наружный отвечает на вопрос «какое место элемент занимает»; номинал — это
#: ИМЯ типоразмера, и телом он не является.
_OUTER_SECTION_PARAMS: tuple[str, ...] = (
    "RBS_PIPE_OUTER_DIAMETER",
    "RBS_CONDUIT_OUTER_DIAM_PARAM",
)

#: Параметры НОМИНАЛА. Держатся отдельно и НИКОГДА не подставляются вместо
#: наружного: замер `snowdon_plumb_v4` — номинал 50.8 отвечает и 60.325, и
#: 53.975, то есть отображение номинал->наружный НЕ ФУНКЦИЯ.
_NOMINAL_SECTION_PARAMS: tuple[str, ...] = (
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
)


def outer_size_mm(node: "GraphNode") -> tuple[float, str] | None:
    """(наружный размер, ЧЕМ измерен) либо None — НИКОГДА не номинал.

    Отдаёт None, когда наружного нет, даже если номинал есть. Подставить
    номинал значило бы объявить телом имя типоразмера и ошибиться на 9.525 мм
    у каждой второй трубы — молча и в опасную сторону (тело МЕНЬШЕ настоящего,
    значит клеш не найдётся).
    """
    for name in _OUTER_SECTION_PARAMS:
        value = node.section.get(name)
        if isinstance(value, (int, float)):
            return float(value), name
    return None


def _as_mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GraphBuildError(f"{what} must be a mapping, got {type(value).__name__}")
    return value


def graph_from_l0(
    header: Mapping[str, Any],
    elements: Iterable[Mapping[str, Any]],
    *,
    document_identity: DocumentIdentity | None = None,
    federation_context: FederationContext | None = None,
    generator_child_ids: Iterable[str] = (),
    link_ids: Iterable[str] = (),
    bodiless_target_ids: Iterable[str] = (),
    host_classes: Mapping[str, str] | None = None,
) -> BuildingGraph:
    """Построить граф из СЫРОГО L0 (заголовок + строки элементов).

    ``document_identity`` and ``federation_context`` are explicit trusted
    overrides.  Missing values are recovered only from the typed identity
    facts captured in the L0 header; they are never inferred from ``doc_name``,
    paths, or local ElementId values. With complete context, each row still
    needs its Revit ``unique_id``; otherwise the node remains readable through
    ``node_id`` but is identity-incomplete and the graph cannot claim authority.

    `generator_child_ids` — единственный вход, которым узел получает
    `DERIVED_BY_REVIT`, и он ЯВНЫЙ. Категорийная таблица сюда не подаётся и
    подаваться не может: приор не знает, кто элемент создаёт, и ровно на нём
    строилась отозванная заявка про 14 713 фитингов.
    """
    header = _as_mapping(header, "header")
    try:
        identity_context = identity_context_from_l0(
            header,
            document_identity=document_identity,
            federation_context=federation_context,
        )
    except IdentityError as exc:
        raise GraphBuildError(f"invalid federated identity context: {exc}") from exc
    document_identity = identity_context.document_identity
    federation_context = identity_context.federation_context
    doc_name = str(header.get("doc_name") or "")
    derived = set(generator_child_ids)

    rows = 0
    refusals: Counter[str] = Counter()
    identity_authoritative_nodes = 0
    identity_incomplete_nodes = 0
    identity_gaps: Counter[str] = Counter()
    nodes: dict[str, GraphNode] = {}
    raw: dict[str, Mapping[str, Any]] = {}

    for element in elements:
        rows += 1
        element = _as_mapping(element, "element row")
        node_id = element.get("element_id")
        if not isinstance(node_id, str) or not node_id:
            refusals[NodeRefusal.NO_ADDRESS.value] += 1
            continue
        if node_id in nodes:
            refusals[NodeRefusal.DUPLICATE_ADDRESS.value] += 1
            continue
        try:
            identity = resolve_element_identity(
                element_unique_id=element.get("unique_id"),
                document_identity=document_identity,
                federation_context=federation_context,
                context_gaps=identity_context.gaps,
            )
        except IdentityError as exc:
            raise GraphBuildError(f"invalid federated identity context: {exc}") from exc
        is_derived = node_id in derived
        nodes[node_id] = GraphNode(
            node_id=node_id,
            category=str(element.get("category") or "no_category"),
            authority=(Authority.DERIVED_BY_REVIT if is_derived
                       else Authority.DECLARED),
            authority_source=(AuthoritySource.LIFTER_GENERATOR_CHILD if is_derived
                              else AuthoritySource.L0_ELEMENT),
            # Строка L0 прочитана из документа: узел СУЩЕСТВУЕТ.
            existence=Existence.MATERIALIZED,
            level_id=element.get("level_id"),
            type_id=element.get("type_id"),
            type_name=element.get("type_name"),
            host_source=element.get("host_source"),
            section=_section_of(element),
            definition_identity=identity.definition,
            occurrence_identity=identity.occurrence,
            identity_status=identity.status,
            identity_gaps=identity.gaps,
        )
        if identity.authoritative:
            identity_authoritative_nodes += 1
        else:
            identity_incomplete_nodes += 1
            identity_gaps.update(gap.value for gap in identity.gaps)
        raw[node_id] = element

    census = GraphCensus(rows_seen=rows, nodes=len(nodes),
                         refusals=dict(refusals),
                         identity_authoritative_nodes=(
                             identity_authoritative_nodes),
                         identity_incomplete_nodes=identity_incomplete_nodes,
                         identity_gaps=dict(identity_gaps),
                         identity_context_authoritative=(
                             document_identity is not None
                             and federation_context is not None))

    links = frozenset(link_ids)
    bodiless = frozenset(bodiless_target_ids)
    edges: list[GraphEdge] = []
    edges.extend(_host_edges(nodes, raw, links, bodiless, host_classes or {}))
    edges.extend(_level_edges(header, nodes, raw))
    edges.extend(_room_boundary_edges(header, nodes, links))
    edges.extend(_bounded_by_same_wall_edges(header, nodes, raw))

    return BuildingGraph(
        doc_name=doc_name, nodes=nodes.values(), edges=edges, census=census,
        document_identity=document_identity,
        federation_context=federation_context,
    )


#: Классы хозяина, каждый со СВОИМ ответом. Ключи — значения `host_class` из
#: `family_placement.index.json`, снятые ЧТЕНИЕМ, а не выведенные из категории.
#:
#: ПОЧЕМУ НЕ ТАБЛИЦА КАТЕГОРИЙ (замер 11.08.2026, и он отменяет план положить
#: этот факт на `CategorySpec` рядом с `discipline`):
#:
#:   * `ReferencePlane` — НЕ КАТЕГОРИЯ, а класс Revit. В таблице экстрактора
#:     77 строк, и ни `OST_CLines`, ни `OST_ReferencePlanes` среди них нет:
#:     опорные плоскости не извлекаются вовсе (1 037 штук в цензе
#:     `snowdon_plumb_v5`, 0 в потоке). Колонка на `CategorySpec` не смогла бы
#:     ответить про них НИКОГДА — строки для них не существует.
#:   * И глубже: у ВИСЯЧЕГО хозяина категория неизвестна В ПРИНЦИПЕ — строки с
#:     этим адресом в снимке нет. Любая таблица, ключ которой категория,
#:     отвечает на вопрос, которого мы не можем задать.
#:   * Зато ответ УЖЕ ЛЕЖИТ НА ДИСКЕ поэлементно: `host_class` в боковом
#:     индексе размещения. Замер: `snowdon_plumb_v5` — `Wall` 2 647,
#:     `Ceiling` 100, `ReferencePlane` **86**, `Level` 25, `FamilyInstance` 2
#:     (те самые 86 висячих, названные по имени); `sob62_r23_v5` —
#:     `RevitLinkInstance` **1** (тот самый единственный висячий).
#:
#: Прецедент `fold._discipline` при этом СОБЛЮДЁН, а не нарушен: он запрещает
#: ВТОРОЙ словарь об одном понятии. Здесь второго не заводится вовсе — читается
#: то, что чтение уже записало.
_HOST_CLASS_LINK = "RevitLinkInstance"
_HOST_CLASS_BODILESS: frozenset[str] = frozenset({"ReferencePlane"})


def _why_unresolved(
    node_id: str,
    host: str,
    bodiless_ids: frozenset[str],
    host_classes: Mapping[str, str],
) -> str:
    """Под-причина неразрешённой цели — по ИЗМЕРЕННОМУ классу, если он есть."""
    measured = host_classes.get(node_id)
    if measured == _HOST_CLASS_LINK:
        return OutsideExtraction.RESOLVED_TO_LINK.value
    if measured in _HOST_CLASS_BODILESS:
        return OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value
    if host in bodiless_ids:
        return OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value
    return OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value


def _host_edges(
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
    link_ids: frozenset[str] = frozenset(),
    bodiless_ids: frozenset[str] = frozenset(),
    host_classes: Mapping[str, str] = {},
) -> Iterator[GraphEdge]:
    """`hosted_in` / `placed_on_datum` с ТРЕМЯ исходами, а не двумя.

    Третий исход — `UNRESOLVED_TARGET`: элемент ОБЪЯВИЛ хозяина, а хозяина в
    этом извлечении нет. Замер: `snowdon_elec_v1` — 959 из 1 001 (95.8 %),
    четыре снимка Snowdon Plumbing — 100 %. Хозяин лежит в связанном файле.
    Ребро с неразрешённой целью ОСТАЁТСЯ в графе именно потому, что это
    единственный сигнал, делающий межраздельную область непустой: стереть его
    значило бы сделать «мы не читали связь» неотличимым от «связи нет».
    """
    for node_id in sorted(nodes):
        host = raw[node_id].get("host_id")
        if not isinstance(host, str) or not host:
            continue
        if host in link_ids:
            # СВЯЗЬ — положительный факт, а не наша слепота. 959 рёбер
            # `snowdon_elec_v1` живут ровно здесь.
            yield GraphEdge(
                relation=Relation.HOSTED_IN_LINK, src=node_id, dst=host,
                modality=Modality.PROVEN,
                evidence={"source": "L0Element.host_id",
                          "resolved_by": "L0 link record",
                          "why": OutsideExtraction.RESOLVED_TO_LINK.value},
            )
            continue
        host_node = nodes.get(host)
        if host_node is None:
            yield GraphEdge(
                relation=Relation.HOSTED_IN, src=node_id, dst=host,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "L0Element.host_id",
                          "host_class": host_classes.get(node_id),
                          "why": _why_unresolved(node_id, host, bodiless_ids,
                                                 host_classes)},
            )
            continue
        relation = (Relation.PLACED_ON_DATUM
                    if host_node.category in _DATUM_CATEGORIES
                    else Relation.HOSTED_IN)
        yield GraphEdge(
            relation=relation, src=node_id, dst=host,
            modality=Modality.PROVEN,
            evidence={"source": "L0Element.host_id",
                      "host_category": host_node.category,
                      # None = «не мерили»; по корпусу — везде. Не молчим.
                      "host_source": raw[node_id].get("host_source")},
        )


def _level_edges(
    header: Mapping[str, Any],
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
) -> Iterator[GraphEdge]:
    """`on_level` + `level_above`.

    `resolve._level_band` выводит обе связи заново на КАЖДОМ вызове — вытаскивает
    отметки из заголовка L0 и ищет следующий уровень сортировкой. Здесь это
    рёбра, а не обход.
    """
    for node_id in sorted(nodes):
        level = nodes[node_id].level_id
        if not isinstance(level, str) or not level:
            continue
        if level in nodes:
            yield GraphEdge(
                relation=Relation.ON_LEVEL, src=node_id, dst=level,
                modality=Modality.PROVEN,
                evidence={"source": "L0Element.level_id"})
        else:
            yield GraphEdge(
                relation=Relation.ON_LEVEL, src=node_id, dst=level,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "L0Element.level_id",
                          "why": OutsideExtraction.LEVEL_NOT_IN_SNAPSHOT.value})

    levels = [lvl for lvl in (header.get("levels") or [])
              if isinstance(lvl, Mapping)]
    ordered = sorted(
        ((str(lvl.get("id") or ""), lvl.get("elevation_mm")) for lvl in levels),
        key=lambda pair: (pair[1] is None, pair[1] if pair[1] is not None else 0.0,
                          pair[0]))
    usable = [(lid, elev) for lid, elev in ordered if lid and elev is not None]
    for (lower, low_z), (upper, high_z) in zip(usable, usable[1:]):
        yield GraphEdge(
            relation=Relation.LEVEL_ABOVE, src=upper, dst=lower,
            modality=Modality.PROVEN,
            evidence={"source": "header.levels.elevation_mm",
                      "delta_mm": float(high_z) - float(low_z)})


def _room_boundary_edges(
    header: Mapping[str, Any],
    nodes: Mapping[str, GraphNode],
    link_ids: frozenset[str] = frozenset(),
) -> Iterator[GraphEdge]:
    """`bounds_room` — сырьё обоих предикатов смежности, названное отдельно."""
    for room in (header.get("rooms") or []):
        if not isinstance(room, Mapping):
            continue
        room_id = room.get("id")
        if not isinstance(room_id, str) or not room_id:
            continue
        for element_id in (room.get("bounding_element_ids") or []):
            if not isinstance(element_id, str) or not element_id:
                continue
            if element_id in nodes:
                yield GraphEdge(
                    relation=Relation.BOUNDS_ROOM, src=element_id, dst=room_id,
                    modality=Modality.PROVEN,
                    evidence={"source": "RoomInfo.bounding_element_ids"})
                continue
            # Под-причина ОБЯЗАТЕЛЬНА и здесь она ДРУГАЯ, чем у хозяина:
            # популяции измеренно не совпадают (пересечение целей 0 из 2 146
            # на `демо-v3`). Связь называется отдельно — на `sob62_r23_v5`
            # одна запись `link` несёт 88 рёбер границы.
            why = (OutsideExtraction.RESOLVED_TO_LINK if element_id in link_ids
                   else OutsideExtraction.BOUNDARY_ELEMENT_NOT_EXTRACTED)
            yield GraphEdge(
                relation=Relation.BOUNDS_ROOM, src=element_id, dst=room_id,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "RoomInfo.bounding_element_ids",
                          "why": why.value})


#: Правило, снимающее ребро предиката A. Имя ЕДЕТ В РЕБРЕ, а ребро остаётся.
REFUTED_HOST_NOT_BETWEEN_TWO_ROOMS = "host_does_not_separate_exactly_two_rooms"


def _bounded_by_same_wall_edges(
    header: Mapping[str, Any],
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
) -> Iterator[GraphEdge]:
    """ПРЕДИКАТ A — `bounded_by_same_wall` (то, что строит `fold._semantic_fold`).

    Ребро между двумя комнатами, ограниченными ОДНИМ хозяином проёма. Это факт
    об ОБЪЯВЛЕНИИ Revit (расчёт границ помещения), а не о геометрии двери.

    ЧТО ЗДЕСЬ ИСПРАВЛЕНО ПРОТИВ `fold`. `fold` требует `len(adjacent) == 2` и на
    любом другом числе МОЛЧА не создаёт ребра. Замер 10.08 по числу комнат,
    ограниченных хозяином двери:

        `демо-v3`      (5 941 дверь): 0→2816, 1→154, 2→1036, 3→966, 4→648,
                       5→50, 6→76, 7→25, 8→55, 9→113, 30→1, 34→1
        `k2_ar_rd_v7`  (2 096 дверей): 0→66, 1→449, 2→1054, 3→326, 4→125, …
        `sob62_r23_v5` (153 двери):    0→15, 1→79, 2→47, 3→12

    То есть на `демо-v3` ребро получают 1 036 дверей из 5 941 — **17.4 %**, а
    4 905 дверей выпадают БЕЗ НАЗВАННОЙ ПРИЧИНЫ. Предикат называется «смежность
    комнат», а означает «хозяин разделяет РОВНО две комнаты». Здесь дверь, чей
    хозяин ограничивает не две комнаты, даёт ребро с `Modality.REFUTED` и
    именем правила: «не искали» становится отличимо от «не нашли».
    """
    boundary_to_rooms: dict[str, set[str]] = defaultdict(set)
    for room in (header.get("rooms") or []):
        if not isinstance(room, Mapping):
            continue
        room_id = room.get("id")
        if not isinstance(room_id, str) or not room_id:
            continue
        for element_id in (room.get("bounding_element_ids") or []):
            if isinstance(element_id, str) and element_id:
                boundary_to_rooms[element_id].add(room_id)

    seen: set[tuple[str, str]] = set()
    for node_id in sorted(nodes):
        if nodes[node_id].category != "OST_Doors":
            continue
        host = raw[node_id].get("host_id")
        if not isinstance(host, str) or not host:
            continue
        if host not in nodes:
            # The room predicate was not evaluated: its host lives beyond this
            # local graph.  Calling this REFUTED would turn extraction blindness
            # into a negative fact about the building.
            yield GraphEdge(
                relation=Relation.BOUNDED_BY_SAME_WALL,
                src=node_id, dst=host,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={
                    "source": "fold._semantic_fold predicate",
                    "why": OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value,
                    "predicate_status": "host_outside_local_graph",
                })
            continue
        adjacent = sorted(boundary_to_rooms.get(host, ()))
        if len(adjacent) == 2:
            pair = (adjacent[0], adjacent[1])
            if pair in seen:
                continue
            seen.add(pair)
            yield GraphEdge(
                relation=Relation.BOUNDED_BY_SAME_WALL,
                src=pair[0], dst=pair[1], modality=Modality.PROVEN,
                evidence={"source": "fold._semantic_fold predicate",
                          "via_host": host, "opening": node_id})
            continue
        # НАЗВАННОЕ опровержение вместо молчаливого выпадения.
        yield GraphEdge(
            relation=Relation.BOUNDED_BY_SAME_WALL,
            src=node_id, dst=host, modality=Modality.REFUTED,
            refuted_by=REFUTED_HOST_NOT_BETWEEN_TWO_ROOMS,
            evidence={"source": "fold._semantic_fold predicate",
                      "rooms_bounded_by_host": len(adjacent),
                      "room_ids": adjacent[:8]})


# ═══════════════════════════════════ ЧТО ВЬЮЕР СПРАШИВАЕТ У ГРАФА
#
# Вьюер сегодня читает ОБОЛОЧКИ `clash/hulls`, а не состояние здания, и это
# видно числом: на `демо-v3` **99.89 % оболочек суть габаритные ящики**, а
# **38.24 % вырождены** (32 165 из 84 120 нулевого объёма). Показывая их, вьюер
# показывает точность геометрии клешей, а не то, что за здание перед
# инженером. Ниже — проекция, отвечающая на вопрос «что это за узел», а не
# «какой ящик его накрывает».
#
# ГРАНИЦА ОТВЕТСТВЕННОСТИ, и она несущая: проекция НЕ содержит геометрии тел.
# Она отдаёт адрес, класс и ЧЕТЫРЕ оси честности; тело узла вьюер берёт там,
# где оно есть, и обязан рисовать РАЗНО по `authority` и `existence`, а не
# одинаковыми телами. Офлайн-3D показывает ОБЪЯВЛЕННОЕ; выведенное Revit
# офлайн не существует вовсе, и нарисовать его как объявленное значило бы
# построить третьего свидетеля, подписывающего непрочитанную ось, размером с
# продукт.


@dataclass(frozen=True, slots=True)
class NodeView:
    """Один узел глазами вьюера: адрес, класс и ЧЕМ он подтверждён."""

    node_id: str
    category: str
    #: `declared` | `derived_by_revit` — граф авторитетен для первого,
    #: Revit для второго. Вьюер обязан различать их видом, а не подписью.
    authority: str
    #: ЧЕМ решено значение выше. Без свидетеля ось не читается.
    authority_source: str
    #: `materialized` | `planned` — построенное против объявленного в чате.
    existence: str
    level_id: str | None
    #: Измеренное сечение, если чтение его дало. Пусто — не «ноль», а «нет».
    section: Mapping[str, Any]
    #: Наружный размер и ЧЕМ измерен, либо None. Номинал сюда не попадает
    #: никогда — см. `outer_size_mm`.
    outer_mm: tuple[float, str] | None
    #: Stable semantic keys. ``node_id`` above remains the local legacy alias.
    definition_identity: str | None
    occurrence_identity: str | None
    identity_authoritative: bool
    identity_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphView:
    """Состояние здания для вьюера: узлы + своды + ЧЕСТНОСТЬ.

    Своды здесь не украшение. `unresolved` и `refuted` — это ровно то, что
    инженер обязан видеть В ПРОЦЕССЕ, а не в конце: опровергнутое ребро с
    именем правила, цель вне извлечения с под-причиной, узел без L1. Слой
    честности во вьюере превращает внутреннюю гигиену в свойство продукта.
    """

    doc_name: str
    nodes: tuple[NodeView, ...]
    authority: Mapping[str, int]
    existence: Mapping[str, int]
    relations: Mapping[str, int]
    #: Рёбра, чья цель не разрешилась, по под-причине (`OutsideExtraction`).
    unresolved_by_reason: Mapping[str, int]
    #: Снятые рёбра по ИМЕНИ правила. Пустой свод и отсутствие свода — разное.
    refuted_by_rule: Mapping[str, int]
    #: Узлы, которых нет среди листьев L1: чтение их видело, компилятор — нет.
    #: `None` значит «набор листьев не подавали», и это НЕ «таких узлов нет».
    without_l1: tuple[str, ...] | None
    #: Перепись графа: узлов = оценённых + названных отказов.
    census_rows: int
    census_refusals: Mapping[str, int]
    identity_authoritative: bool
    identity_authoritative_nodes: int
    identity_incomplete_nodes: int
    identity_gaps: Mapping[str, int]


def graph_view(
    graph: "BuildingGraph",
    *,
    l1_source_ids: Iterable[str] | None = None,
) -> GraphView:
    """Проекция графа для вьюера. Ничего не вычисляет заново и не рисует.

    `l1_source_ids` — адреса листьев L1 этого же здания. Не подан -> поле
    `without_l1` равно `None`, что означает «не спрашивали»; пустой кортеж
    означает «спросили, таких нет». Разница та же, что у `hosted` в клешах.
    """
    views = tuple(
        NodeView(
            node_id=node.node_id,
            category=node.category,
            authority=node.authority.value,
            authority_source=node.authority_source.value,
            existence=node.existence.value,
            level_id=node.level_id,
            section=node.section,
            outer_mm=outer_size_mm(node),
            definition_identity=(
                node.definition_identity.key
                if node.definition_identity is not None else None),
            occurrence_identity=(
                node.occurrence_identity.key
                if node.occurrence_identity is not None else None),
            identity_authoritative=node.identity_authoritative,
            identity_gaps=tuple(gap.value for gap in node.identity_gaps),
        )
        for node in sorted(graph.nodes.values(), key=lambda n: n.node_id)
    )
    unresolved: Counter[str] = Counter()
    for edge in graph.edges:
        if edge.modality is Modality.UNRESOLVED_TARGET:
            unresolved[str(edge.evidence.get("why") or "unnamed")] += 1
    without_l1: tuple[str, ...] | None = None
    if l1_source_ids is not None:
        known = set(l1_source_ids)
        without_l1 = tuple(sorted(set(graph.nodes) - known))
    return GraphView(
        doc_name=graph.doc_name,
        nodes=views,
        authority=graph.authority_counts(),
        existence=graph.existence_counts(),
        relations=graph.relation_counts(),
        unresolved_by_reason=dict(unresolved),
        refuted_by_rule=graph.refuted_by_counts(),
        without_l1=without_l1,
        census_rows=graph.census.rows_seen,
        census_refusals=dict(graph.census.refusals),
        identity_authoritative=graph.identity_authoritative,
        identity_authoritative_nodes=graph.census.identity_authoritative_nodes,
        identity_incomplete_nodes=graph.census.identity_incomplete_nodes or 0,
        identity_gaps=dict(graph.census.identity_gaps),
    )
