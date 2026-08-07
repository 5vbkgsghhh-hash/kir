"""Curtain-wall topology EXTRACT boundary (Wave P2-X).

A curtain wall is not a solid to be tessellated but a *grid* of grid lines,
panels, and mullions.  This module owns the additive side index that records
that topology for every requested :class:`Wall`, keyed by source
``element_id``.  It is deliberately separate from :mod:`geom_extract`
(full B-Rep/mesh) and :mod:`sketch_extract` (closed floor/roof profiles):
the curtain grid needs its own accounting so the future P2-lift can rebuild
``CurtainGrid`` structure rather than a dumb mesh.

Design mirrors the frozen extractor dialect used by
:mod:`sketch_extract`/:mod:`geom_extract`:

* a deterministic, read-only Revit ``Execute`` body builder
  (:func:`build_curtain_extract_cs`) that opens no ``Transaction`` and never
  calls ``get_Geometry``/``Tessellate`` — it walks ``Wall.CurtainGrid`` and
  the U/V grid-line, panel, and mullion tables, emitting **world millimetre**
  curve endpoints (host-local re-projection is an offline parser concern for a
  later wave, not something the bridge attempts);
* a strict, versioned Python parser (:func:`extract_curtain_topology`) that
  validates the wire payload field-for-field, converts nothing implicitly,
  refuses duplicates, and builds a :class:`CurtainExtraction` with a
  ``curtain_index`` keyed by wall ``element_id`` plus a ``failures`` list.

The contract is universal across any Revit model.  The LOT31 census only shows
1×1 grids with four panels and twelve mullions, but the schema accepts any
counts.  A grid line whose ``FullCurve`` is not an exact straight ``Line`` is
recorded with the honest ``curved_unsupported`` marker rather than being
tessellated or dropped — curved curtain grids are a later, separately proven
wave.  A grid, panel, or mullion enumeration that overruns its time budget is
reported as a typed failure and never mislabelled as an empty curtain wall.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

# Таблица совместимости живёт в общем контракте, а не пятью копиями по
# экстракторам: она и заведена затем, чтобы у одной причины было одно имя.
# ``side_contract`` ничего отсюда не импортирует — цикла нет.
from .side_contract import legacy_typed_reason, source_binding_cs


CURTAIN_EXTRACT_SCHEMA_VERSION = "kir-decompile-curtain-extract/5"
CURTAIN_INDEX_SCHEMA_VERSION = "kir-decompile-curtain-index/6"

#: Схема /1 читается по-прежнему. Разбор, снятый ДО этой волны, не несёт ни
#: адреса ячейки, ни типа носителя по умолчанию — и обязан читаться таким,
#: какой он есть: панели из него получают ``address_state=not_captured`` и
#: становятся ЧЕСТНЫМИ атомами, а не догадкой. Отказать в чтении старого
#: индекса значило бы объявить сломанным каждый уже снятый разбор.
CURTAIN_INDEX_SCHEMA_VERSION_LEGACY = "kir-decompile-curtain-index/1"
#: Схема /2 несла адрес ячейки, но тип разрезки носителя в ней был
#: НЕОТЛИЧИМЫМ null-ом (живой замер v4 28.07). Её строки читаются как
#: ``default_panel_state=not_captured``: адрес из них берётся, а вывод о
#: штатности панели — нет.
CURTAIN_INDEX_SCHEMA_VERSION_ADDRESSED = "kir-decompile-curtain-index/2"
#: Схема /3 несла тип разрезки носителя, но об ИМПОСТАХ знала только имя
#: типа: разобрать, кто из них порождён типом, а кто добавлен рукой, по ней
#: нельзя. Её строки читаются как ``mullion_state=not_captured``.
CURTAIN_INDEX_SCHEMA_VERSION_PANEL_STATE = "kir-decompile-curtain-index/3"
#: Схема /4 доказала ИМПОСТЫ (два свидетеля у каждого), но о РАСКЛАДКЕ
#: сетки знала только сами линии — а не то, ставит ли их тип носителя сам.
#: Её строки читаются как ``grid_layout.state = not_captured``.
CURTAIN_INDEX_SCHEMA_VERSION_MULLION = "kir-decompile-curtain-index/4"
#: Схема /5 несла квитанции БЕЗ типизированной причины: «стена не витражная»,
#: «носитель не опознан» и «сеток две» лежали в ней одинаковыми безымянными
#: строками, и ни одна не попадала в разбивку паспорта. Её строки читаются
#: как есть, а причина выводится таблицей совместимости
#: (:func:`legacy_typed_reason`) — иначе 13A-RD-AR-K2_v33 (55 293 элемента,
#: 14 343 квитанции витражей) пришлось бы пере-снимать живым Revit, которого
#: для уже снятого разбора взять неоткуда.
CURTAIN_INDEX_SCHEMA_VERSION_UNTYPED_RECEIPTS = (
    "kir-decompile-curtain-index/5")
SUPPORTED_CURTAIN_INDEX_SCHEMA_VERSIONS = (
    CURTAIN_INDEX_SCHEMA_VERSION_LEGACY,
    CURTAIN_INDEX_SCHEMA_VERSION_ADDRESSED,
    CURTAIN_INDEX_SCHEMA_VERSION_PANEL_STATE,
    CURTAIN_INDEX_SCHEMA_VERSION_MULLION,
    CURTAIN_INDEX_SCHEMA_VERSION_UNTYPED_RECEIPTS,
    CURTAIN_INDEX_SCHEMA_VERSION,
)


class CurtainExtractionError(ValueError):
    """Base class for a fail-closed curtain extraction refusal."""


class CurtainPayloadError(CurtainExtractionError):
    """A bridge or persisted side-index payload violates the protocol."""


class GridDirection(str, Enum):
    """The two orthogonal curtain-grid axes."""

    U = "u"
    V = "v"


class CurveState(str, Enum):
    """Whether a grid line / mullion location curve is exactly representable.

    ``line`` carries two world-millimetre endpoints.  ``curved_unsupported`` is
    the honest refusal marker for any non-``Line`` curve (arc, spline, …): the
    curtain grid still accounts for the line's id/segment counts, but its exact
    curve is deferred to a later curved-grid wave rather than tessellated.
    """

    LINE = "line"
    CURVED_UNSUPPORTED = "curved_unsupported"


class HostKind(str, Enum):
    """Что несёт витражную сетку.

    Сетка живёт НЕ только на стене: витражная система и обе разновидности
    кровли несут ``CurtainGridSet`` (замер по эталонным сборкам 2021-2026).
    Пока обход шёл только по ``Wall.CurtainGrid``, панели таких носителей не
    попадали в индекс ВООБЩЕ — и снаружи это было неотличимо от «компилятор
    не умеет панели».
    """

    WALL = "wall"
    CURTAIN_SYSTEM = "curtain_system"
    ROOF = "roof"


class DefaultPanelState(str, Enum):
    """Что известно о типе панели, которым носитель разрезает сетку САМ.

    ЗАМЕР 28.07 (живой прогон v4, фасад SOB6.2, Revit 2023): все 195 витражных
    носителей вернули ``default_panel_type_id: null`` — и это ЧИСЛО не значило
    ничего. Null одинаково выглядел у трёх разных истин: «прочитали, у типа
    нет автоматической панели», «прочитать не смогли» и «эта схема поля не
    несла вовсе». Лифт обязан был отказать по всем 311 ячейкам, потому что из
    null не следует ни «штатная», ни «заменённая».

    Поэтому состояние стало ТИПИЗИРОВАННЫМ: каждая из трёх истин называет
    себя, и следующий артефакт ставит диагноз сам, не стоя очередного живого
    прогона.
    """

    #: Параметр прочитан и держит настоящий тип: сравнение возможно.
    OK = "ok"
    #: Параметр прочитан и ПУСТ: носитель не режет автоматическую панель, а
    #: значит каждая занятая ячейка назначена автором. Это факт о модели.
    NONE = "none"
    #: Параметра не нашлось ни под одним известным именем, либо чтение
    #: бросило исключение. Мы НЕ ЗНАЕМ — и говорим это вслух.
    UNREADABLE = "unreadable"
    #: Строка снята схемой, которая этого поля не несла (или несла его
    #: неотличимым null-ом — индекс /2 до живого замера 28.07).
    NOT_CAPTURED = "not_captured"


class MullionState(str, Enum):
    """Порождён ли импост ТИПОМ носителя — и потому ли воспроизводим.

    Импост нельзя создать отдельным опом (единственный конструктор —
    ``CurtainGridLine.AddMullions``), поэтому единственный честный способ
    засчитать его покрытым — доказать, что пересборка носителя РОДИТ его
    сама. Доказательство требует ДВУХ независимых свидетелей, и оба читаются
    у Revit, а не выводятся из общих соображений:

    * ``Mullion.Lock`` — «is the Mullion line locked»: собственная
      бухгалтерия Revit о том, что импост ведёт тип. Словарь отказов сборок
      знает и обратный переход: ``RequestOrphanMullionDeletion`` — «some
      mullions became NON-TYPE DRIVEN»;
    * тип импоста обязан совпасть с тем, который тип носителя ставит на
      линии ЭТОГО направления (``AUTO_MULLION_*``).

    Расхождение свидетелей — не «наверное да», а ``manual``: импост
    останется атомом, и это честнее, чем зачесть в покрытие то, чего
    пересборка не построит.
    """

    #: Заперт И тип совпал с типовым для своего направления.
    TYPE_DRIVEN = "type_driven"
    #: Разблокирован либо тип не совпадает — правлено рукой, воспроизвести
    #: нечем (опа для AddMullions в реестре нет).
    MANUAL = "manual"
    #: Хотя бы один свидетель не прочитан.
    UNREADABLE = "unreadable"
    #: Строка снята схемой, которая об импостах этого не знала.
    NOT_CAPTURED = "not_captured"


class MullionDirection(str, Enum):
    """Направление импоста, снятое с его же оси.

    Тип носителя различает вертикальные и горизонтальные импосты (шесть
    параметров ``AUTO_MULLION_*``), поэтому сравнивать тип импоста с типовым
    можно только внутри направления.
    """

    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    UNKNOWN = "unknown"


class GridLayoutState(str, Enum):
    """Прочитана ли РАСКЛАДКА сетки у типа носителя."""

    OK = "ok"
    #: Тип опрошен, ни один слот раскладки не ответил числом.
    NONE = "none"
    UNREADABLE = "unreadable"
    #: Строка снята схемой, которая раскладки не читала (до /5).
    NOT_CAPTURED = "not_captured"


#: Шесть параметров раскладки у типа носителя. Семей три, и это не запас
#: «на всякий случай»: стена разрезается по VERT/HORIZ, витражная система —
#: по GRID1/GRID2 (в API они зовутся SPACING_LAYOUT_1/2), наклонное
#: остекление — по U/V. Ярлык у всех шести одинаковый («Layout»), поэтому
#: различает их только сам BuiltInParameter — по имени не разобрать, да и
#: разбирать нельзя (ИНВАРИАНТ #1). Источник — RevitAPI.xml эталонного
#: пакета, все шесть версий (замер 29.07).
GRID_LAYOUT_SLOTS: tuple[str, ...] = (
    "vert", "horiz", "grid1", "grid2", "u", "v",
)
_GRID_LAYOUT_SLOT_SET = frozenset(GRID_LAYOUT_SLOTS)

#: Значение раскладки «тип сетку НЕ делит». Это ЧИСЛО параметра, а не наше
#: толкование его имени: у Revit раскладка — целочисленное перечисление, и
#: ноль в нём означает «нет». Утверждение фальсифицируемо и проверяется
#: живым прогоном: у носителей, чья пересборка дала НОЛЬ внутренних линий
#: при байт-идентичном типе (замер ночи 28.07 — таких оказались ВСЕ), здесь
#: обязан стоять ровно этот ноль.
GRID_LAYOUT_NONE = 0


@dataclass(frozen=True, slots=True)
class GridLayout:
    """Делит ли сетку САМ тип носителя — по числам его параметров.

    Нужна ровно для одного вопроса: воспроизведёт ли пересборка носителя
    эту линию разрезки. Если тип не делит сетку вовсе, то НИ ОДНА линия не
    родится сама — значит все линии авторские, и каждую надо ставить
    операцией. Если делит — какие именно линии его, а какие руки, по числам
    не различить, и оп на них не эмитируется: удвоенная линия хуже
    отсутствующей.
    """

    slots: Mapping[str, int | None] = field(default_factory=dict)
    state: GridLayoutState = GridLayoutState.NOT_CAPTURED

    def __post_init__(self) -> None:
        if not isinstance(self.state, GridLayoutState):
            raise CurtainPayloadError(
                "GridLayout.state must be a GridLayoutState")
        if not isinstance(self.slots, Mapping):
            raise CurtainPayloadError("GridLayout.slots must be a map")
        unknown = sorted(set(self.slots) - _GRID_LAYOUT_SLOT_SET)
        if unknown:
            raise CurtainPayloadError(
                f"GridLayout unknown slots: {', '.join(unknown)}")
        for name, value in self.slots.items():
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, int):
                raise CurtainPayloadError(
                    f"GridLayout.slots[{name!r}] must be an integer")
        answered = any(value is not None for value in self.slots.values())
        if (self.state is GridLayoutState.OK) != answered:
            raise CurtainPayloadError(
                "grid_layout state=ok requires at least one answered slot "
                "and no other state may carry one")
        object.__setattr__(self, "slots", {
            name: self.slots.get(name) for name in GRID_LAYOUT_SLOTS})

    @classmethod
    def not_captured(cls) -> "GridLayout":
        return cls(slots={}, state=GridLayoutState.NOT_CAPTURED)

    @property
    def divides(self) -> bool | None:
        """Делит ли тип сетку сам. ``None`` — не прочитано.

        Достаточно ОДНОГО слота с ненулевой раскладкой: он уже родит линии,
        которых мы не ставили.
        """

        if self.state is GridLayoutState.OK:
            return any(value is not None and value != GRID_LAYOUT_NONE
                       for value in self.slots.values())
        if self.state is GridLayoutState.NONE:
            # Ни один параметр раскладки не ответил — у типа их нет вовсе,
            # значит делить ими нечего.
            return False
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": {name: self.slots.get(name)
                      for name in GRID_LAYOUT_SLOTS},
            "state": self.state.value,
        }

    @classmethod
    def from_wire(cls, value: Any, field_name: str) -> "GridLayout":
        row = _exact_fields(value, {"slots", "state"}, field_name)
        try:
            state = GridLayoutState(row["state"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.state is unsupported: "
                f"{row['state']!r}") from exc
        raw = _mapping(row["slots"], f"{field_name}.slots")
        unknown = sorted(set(raw) - _GRID_LAYOUT_SLOT_SET)
        if unknown:
            raise CurtainPayloadError(
                f"{field_name}.slots unknown: {', '.join(unknown)}")
        slots: dict[str, int | None] = {}
        for name in GRID_LAYOUT_SLOTS:
            item = raw.get(name)
            if item is not None and (isinstance(item, bool)
                                     or not isinstance(item, int)):
                raise CurtainPayloadError(
                    f"{field_name}.slots[{name!r}] must be an integer")
            slots[name] = item
        return cls(slots=slots, state=state)


class GridLineState(str, Enum):
    """Кто поставил эту линию разрезки — автор или тип носителя.

    Тот же закон, что у импостов: линия засчитывается воспроизводимой
    только тогда, когда это ДОКАЗАНО, а не когда не опровергнуто.
    """

    #: Тип сетку не делит ⇒ линия авторская ⇒ ей нужна операция.
    MANUAL = "manual"
    #: Тип делит сетку сам: какие линии его, а какие руки, по числам не
    #: различить — оп не эмитируется, чтобы не удвоить линию.
    TYPE_DRIVEN = "type_driven"
    #: Раскладка не прочитана (схема до /5 либо отказ параметра).
    UNREADABLE = "unreadable"
    NOT_CAPTURED = "not_captured"


class AutoMullionState(str, Enum):
    """Прочитан ли набор ТИПОВЫХ импостов носителя."""

    OK = "ok"
    #: Тип носителя опрошен, но ни один из двенадцати параметров не ответил
    #: идентификатором — тип импостов не ставит вовсе.
    NONE = "none"
    #: Опрос сорвался (нет типа, отказ параметра).
    UNREADABLE = "unreadable"
    #: Строка снята схемой, которая этих параметров не знала.
    NOT_CAPTURED = "not_captured"


#: Двенадцать параметров типа носителя, задающих импосты. Их ровно две
#: семьи, и обе нужны: стена разрезается по VERT/HORIZ, а витражная система
#: и наклонное остекление — по GRID1/GRID2 (RevitAPI.xml, все шесть версий).
#: Ярлык у них одинаковый («Border 1 Type», «Interior Type»), поэтому
#: различает их только сам BuiltInParameter — по имени не разобрать.
AUTO_MULLION_SLOTS: tuple[str, ...] = (
    "border1_vert", "border2_vert", "interior_vert",
    "border1_horiz", "border2_horiz", "interior_horiz",
    "border1_grid1", "border2_grid1", "interior_grid1",
    "border1_grid2", "border2_grid2", "interior_grid2",
)
_AUTO_MULLION_SLOT_SET = frozenset(AUTO_MULLION_SLOTS)
_VERTICAL_SLOTS = ("border1_vert", "border2_vert", "interior_vert")
_HORIZONTAL_SLOTS = ("border1_horiz", "border2_horiz", "interior_horiz")


@dataclass(frozen=True, slots=True)
class AutoMullionTypes:
    """Какие импосты ставит САМ тип носителя, по слотам.

    Значение слота — идентификатор типа импоста либо ``None`` («этот слот
    пуст»). Сравнение идёт ТОЛЬКО по идентификаторам: имена типов не
    уникальны, и разбирать их на смысл запрещено ИНВАРИАНТОМ #1.
    """

    slots: Mapping[str, str | None] = field(default_factory=dict)
    state: AutoMullionState = AutoMullionState.NOT_CAPTURED

    def __post_init__(self) -> None:
        if not isinstance(self.state, AutoMullionState):
            raise CurtainPayloadError(
                "AutoMullionTypes.state must be an AutoMullionState")
        if not isinstance(self.slots, Mapping):
            raise CurtainPayloadError("AutoMullionTypes.slots must be a map")
        unknown = sorted(set(self.slots) - _AUTO_MULLION_SLOT_SET)
        if unknown:
            raise CurtainPayloadError(
                f"AutoMullionTypes unknown slots: {', '.join(unknown)}")
        for name, value in self.slots.items():
            if value is not None:
                _string(value, f"AutoMullionTypes.slots[{name!r}]")
        captured = any(value is not None for value in self.slots.values())
        if (self.state is AutoMullionState.OK) != captured:
            raise CurtainPayloadError(
                "auto_mullion state=ok requires at least one type id "
                "and no other state may carry one")
        # Все двенадцать слотов присутствуют всегда: «слот пуст» и «слота
        # нет в строке» не должны быть разными объектами — иначе одна и та
        # же запись, снятая и разобранная, перестаёт равняться себе.
        object.__setattr__(self, "slots", {
            name: self.slots.get(name) for name in AUTO_MULLION_SLOTS})

    @classmethod
    def not_captured(cls) -> "AutoMullionTypes":
        return cls(slots={}, state=AutoMullionState.NOT_CAPTURED)

    def ids_for(
        self,
        direction: "MullionDirection",
        host_kind: "HostKind",
    ) -> frozenset[str]:
        """Идентификаторы, которые тип ставит на импост ЭТОГО направления.

        Для СТЕНЫ направление и семья параметров совпадают по построению:
        вертикальный импост стены задаётся ``*_VERT``. Для прочих носителей
        оси зовутся GRID1/GRID2 и с вертикалью не связаны ничем, что можно
        было бы ПРОВЕРИТЬ — поэтому там направление не сужает набор, и в
        кандидаты идут все прочитанные слоты. Сужение — оптимизация точности,
        а не основание вердикта: основание даёт второй свидетель.
        """

        if host_kind is HostKind.WALL and direction is not \
                MullionDirection.UNKNOWN:
            names = (_VERTICAL_SLOTS if direction is MullionDirection.VERTICAL
                     else _HORIZONTAL_SLOTS)
            return frozenset(
                value for name in names
                if (value := self.slots.get(name)) is not None)
        return frozenset(
            value for value in self.slots.values() if value is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": {name: self.slots.get(name)
                      for name in AUTO_MULLION_SLOTS},
            "state": self.state.value,
        }

    @classmethod
    def from_wire(cls, value: Any, field_name: str) -> "AutoMullionTypes":
        row = _exact_fields(value, {"slots", "state"}, field_name)
        try:
            state = AutoMullionState(row["state"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.state is unsupported: "
                f"{row['state']!r}") from exc
        slots_raw = _mapping(row["slots"], f"{field_name}.slots")
        slots = {
            name: _optional_string(
                slots_raw.get(name), f"{field_name}.slots[{name!r}]")
            for name in AUTO_MULLION_SLOTS
        }
        unknown = sorted(set(slots_raw) - _AUTO_MULLION_SLOT_SET)
        if unknown:
            raise CurtainPayloadError(
                f"{field_name}.slots unknown: {', '.join(unknown)}")
        return cls(slots=slots, state=state)


class CellAddressState(str, Enum):
    """Удалось ли назвать АДРЕС ячейки — и если нет, то почему.

    Адрес ``(u_index, v_index)`` — ранг опорной линии разрезки в порядке,
    построенном из геометрии (см. ``CURTAIN_CELL_ADDRESS_CS``). Он либо
    прочитан точно, либо его нет: «панель номер 3 в списке» адресом не
    является, потому что порядок выдачи ``GetPanelIds`` Revit не обещает, а
    в пересобранной модели и id другие.
    """

    OK = "ok"
    #: Элемент ячейки — не ``Panel``, у него нет ``GetRefGridLines``.
    NOT_A_PANEL = "not_a_panel"
    #: Порядок линий разрезки не определён: нечитаемая ``FullCurve`` или две
    #: линии на одном месте. Ранг в таком порядке был бы выдумкой.
    GRID_ORDER_UNDECIDABLE = "grid_order_undecidable"
    #: Опорная линия панели не нашлась среди линий её же сетки.
    REF_LINE_UNRANKED = "ref_line_unranked"
    #: Строка снята схемой /1, где адреса не captured вовсе.
    NOT_CAPTURED = "not_captured"


class CurtainFailureReason(str, Enum):
    """Typed fail-safe reasons emitted in addition to legacy error strings.

    Значения ДОСЛОВНО совпадают с :class:`SideFailureReason`: у одной причины
    обязано быть одно имя во всех пяти индексах, иначе разбивка паспорта
    сложит одно явление как два (тот же довод, что и в ``side_contract``).
    """

    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"
    #: Стена посмотрена, CurtainGrid у неё нет — витражного аспекта не
    #: существует. Это НЕ отказ стадии: элемент вдобавок получает строку
    #: индекса с ``curtain_available: false``.
    ASPECT_NOT_PRESENT = "aspect_not_present"
    #: Сеток на носителе больше одной: адрес (u,v) без номера сетки
    #: неоднозначен, и любая одиночная пара была бы догадкой.
    ADDRESS_AMBIGUOUS = "address_ambiguous"
    #: Носитель не опознан, и эмиттер не сказал, чем именно (старая форма,
    #: где «не нашёлся» и «не тот класс» шли одной строкой).
    HOST_KIND_UNRESOLVED = "host_kind_unresolved"
    #: Запрошенный id не нашёлся в документе за один проход коллектора.
    ELEMENT_UNRESOLVED = "element_unresolved"
    #: Элемент нашёлся, но он не того класса, который несёт витражную сетку.
    ELEMENT_KIND_MISMATCH = "element_kind_mismatch"


Vec3 = tuple[float, float, float]


# ── Strict payload primitives (shape identical to the sibling extractors) ────


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CurtainPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise CurtainPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _exact_fields(
    value: Any,
    fields: set[str],
    field_name: str,
) -> dict[str, Any]:
    row = _mapping(value, field_name)
    missing = sorted(fields - set(row))
    extra = sorted(set(row) - fields)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise CurtainPayloadError(f"{field_name} fields: {'; '.join(details)}")
    return row


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise CurtainPayloadError(f"{field_name} must be an array")
    return value


def _string(value: Any, field_name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        qualifier = "a string" if empty else "a non-empty string"
        raise CurtainPayloadError(f"{field_name} must be {qualifier}")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name)


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise CurtainPayloadError(f"{field_name} must be a boolean")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CurtainPayloadError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CurtainPayloadError(f"{field_name} must be a finite number")
    return 0.0 if result == 0.0 else result


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CurtainPayloadError(
            f"{field_name} must be a non-negative integer")
    return value


def _vec3(value: Any, field_name: str) -> Vec3:
    if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
            or len(value) != 3):
        raise CurtainPayloadError(
            f"{field_name} must contain exactly three numbers")
    return (
        _number(value[0], f"{field_name}[0]"),
        _number(value[1], f"{field_name}[1]"),
        _number(value[2], f"{field_name}[2]"),
    )


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


# ── Validated side-index records ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class GridLineRecord:
    """One ``CurtainGridLine`` on the U or V axis.

    ``curve_state`` is ``line`` when ``FullCurve`` is an exact straight line
    (world-millimetre ``p0_mm``/``p1_mm`` present); otherwise it is
    ``curved_unsupported`` and no endpoints are carried.  The existing/skipped
    segment counts and the lock flag are always accounted for either way.
    """

    line_id: str
    direction: GridDirection
    curve_state: CurveState
    p0_mm: Vec3 | None
    p1_mm: Vec3 | None
    existing_segment_count: int
    skipped_segment_count: int
    locked: bool | None

    def __post_init__(self) -> None:
        _string(self.line_id, "GridLineRecord.line_id")
        if not isinstance(self.direction, GridDirection):
            raise CurtainPayloadError(
                "GridLineRecord.direction must be a GridDirection")
        if not isinstance(self.curve_state, CurveState):
            raise CurtainPayloadError(
                "GridLineRecord.curve_state must be a CurveState")
        if self.curve_state is CurveState.LINE:
            if self.p0_mm is None or self.p1_mm is None:
                raise CurtainPayloadError(
                    "line grid line requires p0_mm and p1_mm")
        elif self.p0_mm is not None or self.p1_mm is not None:
            raise CurtainPayloadError(
                "curved_unsupported grid line cannot carry endpoints")
        _nonnegative_int(
            self.existing_segment_count,
            "GridLineRecord.existing_segment_count")
        _nonnegative_int(
            self.skipped_segment_count,
            "GridLineRecord.skipped_segment_count")
        if self.locked is not None and not isinstance(self.locked, bool):
            raise CurtainPayloadError("GridLineRecord.locked must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        # ``direction`` is intentionally not serialized: it is implied by the
        # containing ``u_grid_lines``/``v_grid_lines`` list, so the persisted
        # and bridge-wire row shapes stay identical (round-trip stable).
        return {
            "line_id": self.line_id,
            "curve_state": self.curve_state.value,
            "p0_mm": list(self.p0_mm) if self.p0_mm is not None else None,
            "p1_mm": list(self.p1_mm) if self.p1_mm is not None else None,
            "existing_segment_count": self.existing_segment_count,
            "skipped_segment_count": self.skipped_segment_count,
            "locked": self.locked,
        }

    @classmethod
    def from_wire(
        cls,
        direction: GridDirection,
        value: Any,
        field_name: str,
    ) -> "GridLineRecord":
        row = _exact_fields(value, {
            "line_id", "curve_state", "p0_mm", "p1_mm",
            "existing_segment_count", "skipped_segment_count", "locked",
        }, field_name)
        try:
            curve_state = CurveState(row["curve_state"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.curve_state is unsupported: "
                f"{row['curve_state']!r}") from exc
        raw_p0 = row["p0_mm"]
        raw_p1 = row["p1_mm"]
        p0 = None if raw_p0 is None else _vec3(raw_p0, f"{field_name}.p0_mm")
        p1 = None if raw_p1 is None else _vec3(raw_p1, f"{field_name}.p1_mm")
        raw_locked = row["locked"]
        locked = (
            None if raw_locked is None
            else _boolean(raw_locked, f"{field_name}.locked"))
        return cls(
            line_id=_string(row["line_id"], f"{field_name}.line_id"),
            direction=direction,
            curve_state=curve_state,
            p0_mm=p0,
            p1_mm=p1,
            existing_segment_count=_nonnegative_int(
                row["existing_segment_count"],
                f"{field_name}.existing_segment_count"),
            skipped_segment_count=_nonnegative_int(
                row["skipped_segment_count"],
                f"{field_name}.skipped_segment_count"),
            locked=locked,
        )


_PANEL_FIELDS_V1 = frozenset({
    "panel_id", "is_family_instance", "family_name", "type_name",
    "host_panel_id", "is_door",
})

_PANEL_FIELDS_V2 = _PANEL_FIELDS_V1 | {
    "type_id", "host_panel_type_id", "host_panel_type_name",
    "u_index", "v_index", "address_state",
}


@dataclass(frozen=True, slots=True)
class PanelRecord:
    """One curtain ``GetPanelIds`` entry — a CELL of the host's grid.

    A panel may be a plain ``Panel`` (empty/glass), a ``FamilyInstance``
    (a hosted family, including a curtain-wall door or window), or the
    wrapper over a WALL that fills the cell.  ``is_family_instance``
    distinguishes the ``FamilyInstance`` case; ``family_name`` stays a
    ``FamilyInstance``-only fact.

    ``type_name``/``type_id`` are read from ``Element.GetTypeId`` and are
    therefore present for EVERY class of panel.  Reading the type only off
    ``FamilyInstance.Symbol`` (as schema /1 did) left every panel-wall with a
    null type — the type was there all along, just behind a different door.

    A cell filled by a wall exists in Revit as TWO elements: this wrapper and
    the wall body ``host_panel_id`` points at.  The wrapper's own type is the
    system "wall" panel symbol; the wall's real type lives on the body, so
    ``host_panel_type_*`` carries it.  The EFFECTIVE type of the cell is the
    body's when there is a body, the panel's own otherwise — one definition,
    mirrored by ``__ccEffType`` in the emitted C# (authoring.py) so the
    witness and the capture cannot disagree.

    ``u_index``/``v_index`` are the cell ADDRESS; ``address_state`` says
    whether it is known and why not.
    """

    panel_id: str
    is_family_instance: bool
    family_name: str | None
    type_name: str | None
    host_panel_id: str | None
    is_door: bool
    type_id: str | None = None
    host_panel_type_id: str | None = None
    host_panel_type_name: str | None = None
    u_index: int | None = None
    v_index: int | None = None
    address_state: CellAddressState = CellAddressState.NOT_CAPTURED

    def __post_init__(self) -> None:
        _string(self.panel_id, "PanelRecord.panel_id")
        if not isinstance(self.is_family_instance, bool):
            raise CurtainPayloadError(
                "PanelRecord.is_family_instance must be a boolean")
        if not isinstance(self.is_door, bool):
            raise CurtainPayloadError("PanelRecord.is_door must be a boolean")
        if not self.is_family_instance and self.family_name is not None:
            raise CurtainPayloadError(
                "non-family panel cannot carry a family name")
        for field_name in ("family_name", "type_name", "type_id",
                           "host_panel_id", "host_panel_type_id",
                           "host_panel_type_name"):
            value = getattr(self, field_name)
            if value is not None:
                _string(value, f"PanelRecord.{field_name}")
        if self.host_panel_type_id is not None and self.host_panel_id is None:
            raise CurtainPayloadError(
                "PanelRecord.host_panel_type_id requires a host_panel_id")
        if not isinstance(self.address_state, CellAddressState):
            raise CurtainPayloadError(
                "PanelRecord.address_state must be a CellAddressState")
        addressed = self.address_state is CellAddressState.OK
        if addressed:
            for field_name in ("u_index", "v_index"):
                _nonnegative_int(
                    getattr(self, field_name), f"PanelRecord.{field_name}")
        elif self.u_index is not None or self.v_index is not None:
            # Адрес либо прочитан, либо его нет. Половина адреса — это
            # догадка с видом факта, и она бы прошла все проверки ниже.
            raise CurtainPayloadError(
                "PanelRecord without an OK address_state cannot carry indices")

    @property
    def effective_type_id(self) -> str | None:
        """Тип ЯЧЕЙКИ: тип тела, если тело есть, иначе собственный тип."""

        return self.host_panel_type_id or self.type_id

    @property
    def effective_type_name(self) -> str | None:
        return self.host_panel_type_name or self.type_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "is_family_instance": self.is_family_instance,
            "family_name": self.family_name,
            "type_name": self.type_name,
            "type_id": self.type_id,
            "host_panel_id": self.host_panel_id,
            "host_panel_type_id": self.host_panel_type_id,
            "host_panel_type_name": self.host_panel_type_name,
            "u_index": self.u_index,
            "v_index": self.v_index,
            "address_state": self.address_state.value,
            "is_door": self.is_door,
        }

    @classmethod
    def from_wire(cls, value: Any, field_name: str) -> "PanelRecord":
        row = _mapping(value, field_name)
        legacy = not (set(row) - _PANEL_FIELDS_V1)
        row = _exact_fields(
            row, set(_PANEL_FIELDS_V1 if legacy else _PANEL_FIELDS_V2),
            field_name)
        if legacy:
            return cls(
                panel_id=_string(row["panel_id"], f"{field_name}.panel_id"),
                is_family_instance=_boolean(
                    row["is_family_instance"],
                    f"{field_name}.is_family_instance"),
                family_name=_optional_string(
                    row["family_name"], f"{field_name}.family_name"),
                type_name=_optional_string(
                    row["type_name"], f"{field_name}.type_name"),
                host_panel_id=_optional_string(
                    row["host_panel_id"], f"{field_name}.host_panel_id"),
                is_door=_boolean(row["is_door"], f"{field_name}.is_door"),
            )
        try:
            address_state = CellAddressState(row["address_state"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.address_state is unsupported: "
                f"{row['address_state']!r}") from exc
        return cls(
            panel_id=_string(row["panel_id"], f"{field_name}.panel_id"),
            is_family_instance=_boolean(
                row["is_family_instance"],
                f"{field_name}.is_family_instance"),
            family_name=_optional_string(
                row["family_name"], f"{field_name}.family_name"),
            type_name=_optional_string(
                row["type_name"], f"{field_name}.type_name"),
            type_id=_optional_string(row["type_id"], f"{field_name}.type_id"),
            host_panel_id=_optional_string(
                row["host_panel_id"], f"{field_name}.host_panel_id"),
            host_panel_type_id=_optional_string(
                row["host_panel_type_id"],
                f"{field_name}.host_panel_type_id"),
            host_panel_type_name=_optional_string(
                row["host_panel_type_name"],
                f"{field_name}.host_panel_type_name"),
            u_index=(
                None if row["u_index"] is None
                else _nonnegative_int(row["u_index"], f"{field_name}.u_index")),
            v_index=(
                None if row["v_index"] is None
                else _nonnegative_int(row["v_index"], f"{field_name}.v_index")),
            address_state=address_state,
            is_door=_boolean(row["is_door"], f"{field_name}.is_door"),
        )


#: Схема /1..3 знала об импосте только имя типа и ось.
_MULLION_FIELDS_V1 = frozenset({
    "mullion_id", "type_name", "curve_state", "p0_mm", "p1_mm",
})
_MULLION_FIELDS_V2 = _MULLION_FIELDS_V1 | {"type_id", "locked", "direction"}


@dataclass(frozen=True, slots=True)
class MullionRecord:
    """One curtain ``GetMullionIds`` entry.

    ``curve_state`` follows the same ``line``/``curved_unsupported`` contract
    as a grid line: a straight mullion ``LocationCurve`` carries two
    world-millimetre endpoints; any other curve is honestly deferred.
    """

    mullion_id: str
    type_name: str | None
    curve_state: CurveState
    p0_mm: Vec3 | None
    p1_mm: Vec3 | None
    #: Тип импоста ИДЕНТИФИКАТОРОМ. Сравнивать с типовым по имени нельзя:
    #: имена не уникальны, а ИНВАРИАНТ #1 запрещает разбирать их на смысл.
    type_id: str | None = None
    #: ``Mullion.Lock`` — заперт ли импост за типом. ``None`` — не прочитан
    #: (старая схема либо отказ свойства), и это НЕ «нет».
    locked: bool | None = None
    #: Направление, снятое с собственной оси импоста: тип носителя ставит
    #: вертикальные и горизонтальные импосты РАЗНЫМИ параметрами.
    direction: MullionDirection = MullionDirection.UNKNOWN

    def __post_init__(self) -> None:
        _string(self.mullion_id, "MullionRecord.mullion_id")
        if self.type_name is not None:
            _string(self.type_name, "MullionRecord.type_name")
        if self.type_id is not None:
            _string(self.type_id, "MullionRecord.type_id")
        if self.locked is not None and not isinstance(self.locked, bool):
            raise CurtainPayloadError("MullionRecord.locked must be a boolean")
        if not isinstance(self.direction, MullionDirection):
            raise CurtainPayloadError(
                "MullionRecord.direction must be a MullionDirection")
        if not isinstance(self.curve_state, CurveState):
            raise CurtainPayloadError(
                "MullionRecord.curve_state must be a CurveState")
        if self.curve_state is CurveState.LINE:
            if self.p0_mm is None or self.p1_mm is None:
                raise CurtainPayloadError(
                    "line mullion requires p0_mm and p1_mm")
        elif self.p0_mm is not None or self.p1_mm is not None:
            raise CurtainPayloadError(
                "curved_unsupported mullion cannot carry endpoints")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mullion_id": self.mullion_id,
            "type_name": self.type_name,
            "curve_state": self.curve_state.value,
            "p0_mm": list(self.p0_mm) if self.p0_mm is not None else None,
            "p1_mm": list(self.p1_mm) if self.p1_mm is not None else None,
            "type_id": self.type_id,
            "locked": self.locked,
            "direction": self.direction.value,
        }

    @classmethod
    def from_wire(cls, value: Any, field_name: str) -> "MullionRecord":
        row = _mapping(value, field_name)
        legacy = not (set(row) - _MULLION_FIELDS_V1)
        row = _exact_fields(
            row, set(_MULLION_FIELDS_V1 if legacy else _MULLION_FIELDS_V2),
            field_name)
        if legacy:
            direction = MullionDirection.UNKNOWN
            type_id = None
            locked = None
        else:
            try:
                direction = MullionDirection(row["direction"])
            except (TypeError, ValueError) as exc:
                raise CurtainPayloadError(
                    f"{field_name}.direction is unsupported: "
                    f"{row['direction']!r}") from exc
            type_id = _optional_string(row["type_id"], f"{field_name}.type_id")
            raw_locked = row["locked"]
            if raw_locked is not None and not isinstance(raw_locked, bool):
                raise CurtainPayloadError(f"{field_name}.locked must be bool")
            locked = raw_locked
        try:
            curve_state = CurveState(row["curve_state"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.curve_state is unsupported: "
                f"{row['curve_state']!r}") from exc
        raw_p0 = row["p0_mm"]
        raw_p1 = row["p1_mm"]
        return cls(
            mullion_id=_string(row["mullion_id"], f"{field_name}.mullion_id"),
            type_name=_optional_string(
                row["type_name"], f"{field_name}.type_name"),
            curve_state=curve_state,
            p0_mm=None if raw_p0 is None else _vec3(
                raw_p0, f"{field_name}.p0_mm"),
            p1_mm=None if raw_p1 is None else _vec3(
                raw_p1, f"{field_name}.p1_mm"),
            type_id=type_id,
            locked=locked,
            direction=direction,
        )


@dataclass(frozen=True, slots=True)
class CurtainWallRecord:
    """One wall's frozen-L0 curtain topology row.

    ``curtain_available=False`` means the wall has no ``CurtainGrid`` (a plain
    basic wall).  It carries no grid/panel/mullion data and no ``reason``
    string in the index; the honest ``not_curtain`` diagnostic lands in the
    extraction ``failures`` list instead, so a non-curtain wall is never
    mistaken for an empty-but-curtain wall.
    """

    wall_id: str
    curtain_available: bool
    u_grid_lines: tuple[GridLineRecord, ...] = ()
    v_grid_lines: tuple[GridLineRecord, ...] = ()
    panels: tuple[PanelRecord, ...] = ()
    mullions: tuple[MullionRecord, ...] = ()
    #: Класс носителя. По умолчанию — стена: так читается индекс схемы /1,
    #: который другого носителя и не знал.
    host_kind: HostKind = HostKind.WALL
    #: Тип панели, которым носитель РАЗРЕЗАЕТ сетку сам. Ровно он отличает
    #: штатную панель от заменённой: без него пришлось бы либо породить
    #: операцию на каждую ячейку, либо потерять замены — обе половины
    #: дизайна 2026-07-28.
    default_panel_type_id: str | None = None
    default_panel_type_name: str | None = None
    #: ЧТО ИМЕННО известно об этом типе (см. DefaultPanelState). Поле
    #: заведено после живого прогона, где null не отличал «пусто» от «не
    #: прочитали» и стоил всей волне одного круга.
    default_panel_state: DefaultPanelState = DefaultPanelState.NOT_CAPTURED
    #: Имя BuiltInParameter, который ОТВЕТИЛ (или, при unreadable, список
    #: тех, что были опрошены). Провенанс числа живёт рядом с числом.
    default_panel_source: str | None = None
    #: Импосты, которые носитель ставит САМ (двенадцать слотов типа). Без
    #: них ни один импост нельзя честно назвать порождаемым: «его сделала
    #: сетка» — это утверждение о ТИПЕ, и проверяется оно только типом.
    auto_mullion_types: AutoMullionTypes = field(
        default_factory=AutoMullionTypes.not_captured)
    #: Делит ли сетку САМ тип носителя. Без этого линию разрезки нельзя ни
    #: эмитировать (удвоится), ни промолчать о ней (потеряется вся семья
    #: детей носителя — замер ночи 28.07: замыкание 27%).
    grid_layout: GridLayout = field(default_factory=GridLayout.not_captured)

    def __post_init__(self) -> None:
        _string(self.wall_id, "CurtainWallRecord.wall_id")
        if not isinstance(self.curtain_available, bool):
            raise CurtainPayloadError(
                "CurtainWallRecord.curtain_available must be a boolean")
        if not isinstance(self.host_kind, HostKind):
            raise CurtainPayloadError(
                "CurtainWallRecord.host_kind must be a HostKind")
        for field_name in ("default_panel_type_id", "default_panel_type_name",
                           "default_panel_source"):
            value = getattr(self, field_name)
            if value is not None:
                _string(value, f"CurtainWallRecord.{field_name}")
        if not isinstance(self.default_panel_state, DefaultPanelState):
            raise CurtainPayloadError(
                "CurtainWallRecord.default_panel_state must be a "
                "DefaultPanelState")
        if not isinstance(self.auto_mullion_types, AutoMullionTypes):
            raise CurtainPayloadError(
                "CurtainWallRecord.auto_mullion_types must be an "
                "AutoMullionTypes")
        if not isinstance(self.grid_layout, GridLayout):
            raise CurtainPayloadError(
                "CurtainWallRecord.grid_layout must be a GridLayout")
        # Состояние и значение не имеют права расходиться: «ok без типа» и
        # «тип без ok» — обе формы того самого неотличимого null-а, ради
        # которого поле и заведено.
        if (self.default_panel_state is DefaultPanelState.OK) != (
                self.default_panel_type_id is not None):
            raise CurtainPayloadError(
                "default_panel_state=ok requires a default_panel_type_id "
                "and no other state may carry one")
        if not self.curtain_available and (
                self.u_grid_lines or self.v_grid_lines
                or self.panels or self.mullions
                or self.default_panel_type_id is not None
                or self.default_panel_type_name is not None
                or self.default_panel_state is not
                DefaultPanelState.NOT_CAPTURED
                or self.auto_mullion_types.state is not
                AutoMullionState.NOT_CAPTURED
                or self.grid_layout.state is not
                GridLayoutState.NOT_CAPTURED):
            raise CurtainPayloadError(
                "non-curtain wall cannot carry grid/panel/mullion data")
        for line in (*self.u_grid_lines, *self.v_grid_lines):
            if not isinstance(line, GridLineRecord):
                raise CurtainPayloadError(
                    "CurtainWallRecord grid line is invalid")
        for line in self.u_grid_lines:
            if line.direction is not GridDirection.U:
                raise CurtainPayloadError("u grid line mislabelled")
        for line in self.v_grid_lines:
            if line.direction is not GridDirection.V:
                raise CurtainPayloadError("v grid line mislabelled")
        if not all(isinstance(panel, PanelRecord) for panel in self.panels):
            raise CurtainPayloadError("CurtainWallRecord panel is invalid")
        if not all(
                isinstance(mullion, MullionRecord)
                for mullion in self.mullions):
            raise CurtainPayloadError("CurtainWallRecord mullion is invalid")
        self._require_unique(
            (line.line_id for line in
             (*self.u_grid_lines, *self.v_grid_lines)),
            "grid line")
        self._require_unique(
            (panel.panel_id for panel in self.panels), "panel")
        self._require_unique(
            (mullion.mullion_id for mullion in self.mullions), "mullion")

    def grid_line_state(self, line: GridLineRecord) -> GridLineState:
        """Нужна ли этой линии разрезки операция — по числам, не по вере.

        Линия разрезки не имеет иного конструктора, кроме
        ``CurtainGrid.AddGridLine``; тип носителя её не несёт, если сам не
        делит сетку. Отсюда ровно три исхода, и все три называют себя:

        * тип сетку НЕ делит ⇒ линия авторская, её обязан ставить оп —
          иначе у носителя не будет ни ячеек, ни импостов, ни панелей
          (замер ночи 28.07: у ВСЕХ пересобранных носителей ноль внутренних
          линий при байт-идентичных типах, замыкание детей 27%);
        * тип делит сетку сам ⇒ какая линия его, а какая авторская, по
          числам не различить: оп не эмитируется, потому что удвоенная
          линия хуже отсутствующей;
        * раскладка не прочитана ⇒ отказ, а не догадка.
        """

        if not isinstance(line, GridLineRecord):
            raise CurtainPayloadError("grid_line_state expects a line record")
        layout = self.grid_layout
        if layout.state is GridLayoutState.NOT_CAPTURED:
            return GridLineState.NOT_CAPTURED
        divides = layout.divides
        if divides is None:
            return GridLineState.UNREADABLE
        return GridLineState.TYPE_DRIVEN if divides else GridLineState.MANUAL

    def mullion_state(self, mullion: MullionRecord) -> MullionState:
        """Порождает ли ТИП носителя этот импост — по двум свидетелям.

        Отдельной операции у импоста нет и быть не может: единственный его
        конструктор — ``CurtainGridLine.AddMullions``, а в реестре такой опы
        нет. Значит «покрыт» для импоста означает ровно одно — ПЕРЕСБОРКА
        НОСИТЕЛЯ РОДИТ ЕГО САМА. Утверждать это можно, только когда
        совпадают оба независимых свидетеля:

        * ``Mullion.Lock`` — Revit сам считает импост ведомым типом (и знает
          обратный переход: ``RequestOrphanMullionDeletion`` — «some mullions
          became non-type driven»);
        * тип импоста числится среди тех, что тип носителя ставит.

        Любое расхождение, любое непрочитанное число — не «наверное да», а
        отказ: импост останется атомом. Ошибка в эту сторону стоит процента
        покрытия, ошибка в другую — вычитает из знаменателя то, чего
        пересборка не построит.
        """

        auto = self.auto_mullion_types
        if auto.state is AutoMullionState.NOT_CAPTURED:
            return MullionState.NOT_CAPTURED
        if auto.state is AutoMullionState.UNREADABLE:
            return MullionState.UNREADABLE
        if mullion.locked is None or mullion.type_id is None:
            return MullionState.UNREADABLE
        if not mullion.locked:
            return MullionState.MANUAL
        if mullion.type_id in auto.ids_for(mullion.direction, self.host_kind):
            return MullionState.TYPE_DRIVEN
        return MullionState.MANUAL

    @staticmethod
    def _require_unique(ids: Iterator[str], noun: str) -> None:
        seen: set[str] = set()
        for identifier in ids:
            if identifier in seen:
                raise CurtainPayloadError(
                    f"duplicate {noun} id in curtain wall: {identifier!r}")
            seen.add(identifier)

    @classmethod
    def not_curtain(cls, wall_id: str) -> "CurtainWallRecord":
        return cls(wall_id=wall_id, curtain_available=False)

    @property
    def u_line_count(self) -> int:
        return len(self.u_grid_lines)

    @property
    def v_line_count(self) -> int:
        return len(self.v_grid_lines)

    @property
    def panel_count(self) -> int:
        return len(self.panels)

    @property
    def mullion_count(self) -> int:
        return len(self.mullions)

    @property
    def door_count(self) -> int:
        return sum(1 for panel in self.panels if panel.is_door)

    def to_dict(self) -> dict[str, Any]:
        if not self.curtain_available:
            return {"curtain_available": False}
        return {
            "curtain_available": True,
            "host_kind": self.host_kind.value,
            "default_panel_type_id": self.default_panel_type_id,
            "default_panel_type_name": self.default_panel_type_name,
            "default_panel_state": self.default_panel_state.value,
            "default_panel_source": self.default_panel_source,
            "auto_mullion_types": self.auto_mullion_types.to_dict(),
            "grid_layout": self.grid_layout.to_dict(),
            "u_grid_lines": [line.to_dict() for line in self.u_grid_lines],
            "v_grid_lines": [line.to_dict() for line in self.v_grid_lines],
            "panels": [panel.to_dict() for panel in self.panels],
            "mullions": [mullion.to_dict() for mullion in self.mullions],
        }

    @classmethod
    def from_dict(
        cls,
        wall_id: str,
        value: Any,
        field_name: str = "curtain index record",
    ) -> "CurtainWallRecord":
        row = _mapping(value, field_name)
        available = _boolean(
            row.get("curtain_available"), f"{field_name}.curtain_available")
        if not available:
            _exact_fields(row, {"curtain_available"}, field_name)
            return cls.not_curtain(wall_id)
        legacy_fields = {
            "curtain_available", "u_grid_lines", "v_grid_lines",
            "panels", "mullions",
        }
        addressed_fields = legacy_fields | {
            "host_kind", "default_panel_type_id", "default_panel_type_name",
        }
        stateful_fields = addressed_fields | {
            "default_panel_state", "default_panel_source",
        }
        mullion_fields = stateful_fields | {"auto_mullion_types"}
        layout_fields = mullion_fields | {"grid_layout"}
        legacy = not (set(row) - legacy_fields)
        addressed = not legacy and not (set(row) - addressed_fields)
        stateful = (not legacy and not addressed
                    and not (set(row) - stateful_fields))
        mullion_era = (not legacy and not addressed and not stateful
                       and not (set(row) - mullion_fields))
        row = _exact_fields(
            row,
            set(legacy_fields if legacy
                else addressed_fields if addressed
                else stateful_fields if stateful
                else mullion_fields if mullion_era else layout_fields),
            field_name)
        default_source = None
        # Схема /1../3 об импостах типа не знала. Пустой набор здесь означал
        # бы «тип не ставит импостов» — то есть «все импосты правлены рукой»,
        # утверждение куда более сильное, чем «мы не смотрели».
        auto_mullions = (
            AutoMullionTypes.not_captured() if legacy or addressed or stateful
            else AutoMullionTypes.from_wire(
                row["auto_mullion_types"], f"{field_name}.auto_mullion_types"))
        # Схема /1../4 раскладки не читала. Пустая раскладка здесь означала
        # бы «тип сетку не делит» — то есть «ставь оп на каждую линию», а
        # это куда более сильное утверждение, чем «мы не смотрели».
        layout = (
            GridLayout.not_captured()
            if legacy or addressed or stateful or mullion_era
            else GridLayout.from_wire(
                row["grid_layout"], f"{field_name}.grid_layout"))
        if legacy:
            host_kind = HostKind.WALL
            default_type_id = None
            default_type_name = None
            default_state = DefaultPanelState.NOT_CAPTURED
        else:
            try:
                host_kind = HostKind(row["host_kind"])
            except (TypeError, ValueError) as exc:
                raise CurtainPayloadError(
                    f"{field_name}.host_kind is unsupported: "
                    f"{row['host_kind']!r}") from exc
            default_type_id = _optional_string(
                row["default_panel_type_id"],
                f"{field_name}.default_panel_type_id")
            default_type_name = _optional_string(
                row["default_panel_type_name"],
                f"{field_name}.default_panel_type_name")
            if addressed:
                # Схема /2: состояния не было. Тип есть ⇒ он прочитан;
                # тип null ⇒ НЕИЗВЕСТНО, а не «пусто»: ровно эта подмена и
                # стоила живого прогона v4.
                default_state = (
                    DefaultPanelState.OK if default_type_id is not None
                    else DefaultPanelState.NOT_CAPTURED)
            else:
                try:
                    default_state = DefaultPanelState(
                        row["default_panel_state"])
                except (TypeError, ValueError) as exc:
                    raise CurtainPayloadError(
                        f"{field_name}.default_panel_state is unsupported: "
                        f"{row['default_panel_state']!r}") from exc
                default_source = _optional_string(
                    row["default_panel_source"],
                    f"{field_name}.default_panel_source")
        u_lines = tuple(
            GridLineRecord.from_wire(
                GridDirection.U, raw, f"{field_name}.u_grid_lines[{index}]")
            for index, raw in enumerate(
                _array(row["u_grid_lines"], f"{field_name}.u_grid_lines")))
        v_lines = tuple(
            GridLineRecord.from_wire(
                GridDirection.V, raw, f"{field_name}.v_grid_lines[{index}]")
            for index, raw in enumerate(
                _array(row["v_grid_lines"], f"{field_name}.v_grid_lines")))
        panels = tuple(
            PanelRecord.from_wire(raw, f"{field_name}.panels[{index}]")
            for index, raw in enumerate(
                _array(row["panels"], f"{field_name}.panels")))
        mullions = tuple(
            MullionRecord.from_wire(raw, f"{field_name}.mullions[{index}]")
            for index, raw in enumerate(
                _array(row["mullions"], f"{field_name}.mullions")))
        return cls(wall_id, True, u_lines, v_lines, panels, mullions,
                   host_kind, default_type_id, default_type_name,
                   default_state, default_source, auto_mullions, layout)


@dataclass(frozen=True, slots=True)
class CurtainFailure:
    """One wall/stage that could not be read as a clean curtain topology."""

    wall_id: str
    reason: str
    typed_reason: CurtainFailureReason | None = None
    elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        _string(self.wall_id, "CurtainFailure.wall_id")
        _string(self.reason, "CurtainFailure.reason")
        if self.typed_reason is None:
            if self.elapsed_ms is not None:
                raise CurtainPayloadError(
                    "CurtainFailure.elapsed_ms requires a typed reason")
        else:
            if not isinstance(self.typed_reason, CurtainFailureReason):
                raise CurtainPayloadError(
                    "CurtainFailure.typed_reason must be a "
                    "CurtainFailureReason")
            # ``elapsed_ms`` необязателен ПРИ типизированной причине — ровно
            # как у SideFailure и ProfileFailure. У среза по бюджету время
            # осмысленно, у «сетки нет» его не существует, и требовать его
            # значило бы заставлять эмиттер выдумывать число.
            if self.elapsed_ms is not None:
                _nonnegative_int(self.elapsed_ms, "CurtainFailure.elapsed_ms")
            # Равенства строки и типа здесь БОЛЬШЕ НЕ ТРЕБУЕТСЯ.
            # Оно держалось, пока типизированными были только две причины,
            # чьё имя и приходило по проводу строкой. Как только у квитанции
            # появилось описание («host has no CurtainGrid» при типе
            # ``aspect_not_present``), равенство стало запрещать ровно то,
            # ради чего причина заводилась: тип агрегируется, строка
            # объясняет. Противоречить друг другу они не могут — тип пишет
            # тот же эмиттер, и он же авторитет при разборе.

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "wall_id": self.wall_id,
            "reason": self.reason,
        }
        if self.typed_reason is not None:
            result["typed_reason"] = self.typed_reason.value
            result["elapsed_ms"] = self.elapsed_ms
        return result

    @classmethod
    def from_dict(cls, value: Any, field_name: str) -> "CurtainFailure":
        row = _mapping(value, field_name)
        if "typed_reason" in row or "elapsed_ms" in row:
            row = _exact_fields(row, {
                "wall_id", "reason", "typed_reason", "elapsed_ms",
            }, field_name)
            try:
                typed = CurtainFailureReason(row["typed_reason"])
            except (TypeError, ValueError) as exc:
                raise CurtainPayloadError(
                    f"{field_name}.typed_reason is unsupported") from exc
            # ``elapsed_ms`` может быть null: у причины «сетки нет» времени
            # не существует. Пока здесь стоял безусловный _nonnegative_int,
            # КАЖДАЯ типизированная квитанция без времени не читалась назад —
            # то есть индекс, записанный этой же версией, переставал
            # разбираться, и стадия молча пересчитывалась заново.
            raw_elapsed = row["elapsed_ms"]
            return cls(
                wall_id=_string(row["wall_id"], f"{field_name}.wall_id"),
                reason=_string(row["reason"], f"{field_name}.reason"),
                typed_reason=typed,
                elapsed_ms=(
                    None if raw_elapsed is None
                    else _nonnegative_int(
                        raw_elapsed, f"{field_name}.elapsed_ms")),
            )
        row = _exact_fields(row, {"wall_id", "reason"}, field_name)
        return cls(
            wall_id=_string(row["wall_id"], f"{field_name}.wall_id"),
            reason=_string(row["reason"], f"{field_name}.reason"),
        )


@dataclass(frozen=True, slots=True)
class CurtainExtraction:
    """Validated curtain side-index result, keyed by wall ``element_id``."""

    records: tuple[CurtainWallRecord, ...]
    failures: tuple[CurtainFailure, ...] = ()

    def __post_init__(self) -> None:
        wall_ids = [record.wall_id for record in self.records]
        if len(wall_ids) != len(set(wall_ids)):
            raise CurtainPayloadError(
                "curtain index contains duplicate wall_id")

    def __iter__(self) -> Iterator[CurtainWallRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def curtain_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.wall_id: record.to_dict()
            for record in sorted(
                self.records,
                key=lambda record: _element_id_key(record.wall_id))
        }

    def entry_for(self, wall_id: str) -> CurtainWallRecord:
        for record in self.records:
            if record.wall_id == wall_id:
                return record
        raise CurtainPayloadError(
            f"wall is absent from curtain index: {wall_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CURTAIN_INDEX_SCHEMA_VERSION,
            "curtain_index": self.curtain_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda item: (
                        _element_id_key(item.wall_id), item.reason))
            ],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "CurtainExtraction":
        root = _exact_fields(value, {
            "schema_version", "curtain_index", "failures",
        }, "persisted curtain extraction")
        if root["schema_version"] not in SUPPORTED_CURTAIN_INDEX_SCHEMA_VERSIONS:
            raise CurtainPayloadError("curtain index schema_version mismatch")
        raw_index = _mapping(
            root["curtain_index"],
            "persisted curtain extraction.curtain_index")
        records = tuple(
            CurtainWallRecord.from_dict(
                wall_id,
                row,
                f"persisted curtain extraction.curtain_index[{wall_id!r}]",
            )
            for wall_id, row in sorted(
                raw_index.items(), key=lambda item: _element_id_key(item[0]))
        )
        raw_failures = _array(
            root["failures"], "persisted curtain extraction.failures")
        failures = tuple(
            CurtainFailure.from_dict(
                raw,
                f"persisted curtain extraction.failures[{index}]")
            for index, raw in enumerate(raw_failures)
        )
        return cls(records=records, failures=failures)

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "CurtainExtraction":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"curtain index is not valid JSON: {exc}") from exc
        return cls.from_dict(decoded)


def _unwrap_bridge_payload(value: Any) -> Any:
    current = value
    for _ in range(2):
        if not isinstance(current, Mapping) or "ok" not in current:
            break
        if current.get("ok") is not True:
            detail = current.get("error") or current.get("message") \
                or "bridge refused curtain extraction"
            raise CurtainPayloadError(str(detail)[:300])
        if "result" not in current:
            break
        current = current["result"]
    return current


def _parse_grid_lines(
    direction: GridDirection,
    raw_lines: Any,
    field_name: str,
) -> tuple[GridLineRecord, ...]:
    lines = _array(raw_lines, field_name)
    return tuple(
        GridLineRecord.from_wire(direction, raw, f"{field_name}[{index}]")
        for index, raw in enumerate(lines)
    )


def extract_curtain_topology(payload: Any) -> CurtainExtraction:
    """Validate one emitted payload and build the frozen-L0 curtain index.

    Wire-shape corruption is a typed exception.  A well-formed per-wall
    failure — a wall with no curtain grid, a grid enumeration error, or a
    time-budget overrun — becomes an honest ``failures`` entry (plus a
    ``not_curtain`` index record for the no-grid case) rather than being
    silently dropped or misreported as an empty curtain wall.
    """

    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "walls"},
        "curtain extraction",
    )
    if root["schema_version"] != CURTAIN_EXTRACT_SCHEMA_VERSION:
        raise CurtainPayloadError("curtain extraction schema_version mismatch")
    walls = _array(root["walls"], "curtain extraction.walls")
    records: list[CurtainWallRecord] = []
    failures: list[CurtainFailure] = []
    seen_ids: set[str] = set()

    for wall_index, raw_wall in enumerate(walls):
        field_name = f"curtain extraction.walls[{wall_index}]"
        row = _additive_wall_fields(raw_wall, field_name)
        wall_id = _string(row["wall_id"], f"{field_name}.wall_id")
        if wall_id in seen_ids:
            raise CurtainPayloadError(f"duplicate curtain wall_id: {wall_id!r}")
        seen_ids.add(wall_id)
        status = _string(row["status"], f"{field_name}.status")

        typed_reason, elapsed_ms = _parse_typed_reason(row, field_name)

        if status == "not_curtain":
            _forbid_topology(row, field_name, status)
            if typed_reason not in (
                    None, CurtainFailureReason.ASPECT_NOT_PRESENT):
                raise CurtainPayloadError(
                    f"{field_name}: not_curtain carries a foreign typed "
                    f"reason: {typed_reason.value!r}")
            records.append(CurtainWallRecord.not_curtain(wall_id))
            # Строка остаётся прежней («not_curtain»), тип добавляется
            # ВСЕГДА, в том числе для мостов, которые его ещё не шлют:
            # статус и есть причина, выводить её неоткуда больше.
            #
            # Квитанция здесь НЕ означает, что стадия не справилась: этот же
            # элемент получает и строку индекса. Она означает «посмотрели,
            # витражного аспекта нет» — класс DETERMINATION, и только
            # разделение классов не даёт этим 14 324 стенам (замер
            # 13A-RD-AR-K2_v33) читаться как масса отказов.
            failures.append(CurtainFailure(
                wall_id, "not_curtain",
                typed_reason=CurtainFailureReason.ASPECT_NOT_PRESENT))
            continue

        if status == "failed":
            _forbid_topology(row, field_name, status)
            reason = _string(row["reason"], f"{field_name}.reason")
            if (typed_reason is not None
                    and reason in _SELF_NAMING_VALUES
                    and typed_reason.value != reason):
                raise CurtainPayloadError(
                    f"{field_name}: typed reason must match the failed reason")
            if typed_reason is None:
                # Мост может не знать о типах (старее этой волны). Причина
                # выводится из НАШЕЙ ЖЕ строки одной таблицей на все пять
                # индексов — не «списком знакомых имён из модели»: сюда
                # физически не может попасть ни тип, ни семейство, ни id.
                inferred = legacy_typed_reason("curtain", reason)
                if inferred is not None:
                    typed_reason = CurtainFailureReason(inferred.value)
            failures.append(CurtainFailure(
                wall_id, reason,
                typed_reason=typed_reason,
                elapsed_ms=elapsed_ms))
            continue

        if status != "ok":
            raise CurtainPayloadError(
                f"{field_name}.status is unsupported: {status!r}")
        if row["reason"] is not None:
            raise CurtainPayloadError(
                f"{field_name}: ok status cannot carry a reason")
        if typed_reason is not None:
            raise CurtainPayloadError(
                f"{field_name}: ok status cannot carry a typed reason")

        try:
            host_kind = HostKind(row["host_kind"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.host_kind is unsupported: "
                f"{row['host_kind']!r}") from exc
        default_type_id = _optional_string(
            row["default_panel_type_id"],
            f"{field_name}.default_panel_type_id")
        default_type_name = _optional_string(
            row["default_panel_type_name"],
            f"{field_name}.default_panel_type_name")
        try:
            default_state = DefaultPanelState(row["default_panel_state"])
        except (TypeError, ValueError) as exc:
            raise CurtainPayloadError(
                f"{field_name}.default_panel_state is unsupported: "
                f"{row['default_panel_state']!r}") from exc
        default_source = _optional_string(
            row["default_panel_source"],
            f"{field_name}.default_panel_source")
        auto_mullions = AutoMullionTypes.from_wire(
            row["auto_mullion_types"], f"{field_name}.auto_mullion_types")
        layout = GridLayout.from_wire(
            row["grid_layout"], f"{field_name}.grid_layout")

        u_lines = _parse_grid_lines(
            GridDirection.U, row["u_grid_lines"],
            f"{field_name}.u_grid_lines")
        v_lines = _parse_grid_lines(
            GridDirection.V, row["v_grid_lines"],
            f"{field_name}.v_grid_lines")
        panels = tuple(
            PanelRecord.from_wire(raw, f"{field_name}.panels[{index}]")
            for index, raw in enumerate(
                _array(row["panels"], f"{field_name}.panels")))
        mullions = tuple(
            MullionRecord.from_wire(raw, f"{field_name}.mullions[{index}]")
            for index, raw in enumerate(
                _array(row["mullions"], f"{field_name}.mullions")))
        records.append(CurtainWallRecord(
            wall_id, True, u_lines, v_lines, panels, mullions,
            host_kind, default_type_id, default_type_name,
            default_state, default_source, auto_mullions, layout))

    return CurtainExtraction(
        records=tuple(sorted(
            records, key=lambda record: _element_id_key(record.wall_id))),
        failures=tuple(sorted(
            failures,
            key=lambda failure: (
                _element_id_key(failure.wall_id), failure.reason))),
    )


_TOPOLOGY_FIELDS = ("u_grid_lines", "v_grid_lines", "panels", "mullions")


def _additive_wall_fields(value: Any, field_name: str) -> dict[str, Any]:
    return _exact_fields(value, {
        "wall_id", "status", "reason", "typed_reason", "elapsed_ms",
        "host_kind", "default_panel_type_id", "default_panel_type_name",
        "default_panel_state", "default_panel_source",
        "auto_mullion_types", "grid_layout",
        *_TOPOLOGY_FIELDS,
    }, field_name)


#: Причины, у которых прошедшее время — часть самой причины и потому
#: обязательно. У остальных («сетки нет», «сеток две») времени не
#: существует, и требовать его значило бы заставить эмиттер выдумать число.
_TIMED_REASONS = frozenset({
    CurtainFailureReason.TIME_BUDGET_EXCEEDED,
    CurtainFailureReason.CALL_BUDGET_EXHAUSTED,
})

#: Причины, чьё ИМЯ и приходит по проводу строкой ``reason``. Только для них
#: строка и тип обязаны совпадать: противоречие между ними — битый ответ.
#: Хранятся ЗНАЧЕНИЯ, а не члены Enum: ``Enum.__hash__`` считается по имени,
#: поэтому ``"time_budget_exceeded" in {Reason.TIME_BUDGET_EXCEEDED}`` — ложь,
#: и проверка противоречия молча перестала бы срабатывать.
_SELF_NAMING_VALUES = frozenset(reason.value for reason in _TIMED_REASONS)


def _parse_typed_reason(
    row: Mapping[str, Any],
    field_name: str,
) -> tuple[CurtainFailureReason | None, int | None]:
    raw_typed = row["typed_reason"]
    raw_elapsed = row["elapsed_ms"]
    if raw_typed is None:
        if raw_elapsed is not None:
            raise CurtainPayloadError(
                f"{field_name}.elapsed_ms requires a typed_reason")
        return None, None
    try:
        typed = CurtainFailureReason(raw_typed)
    except (TypeError, ValueError) as exc:
        raise CurtainPayloadError(
            f"{field_name}.typed_reason is unsupported: {raw_typed!r}") \
            from exc
    if typed in _TIMED_REASONS:
        # У среза по бюджету время — часть причины: без него нельзя отличить
        # «упёрлись в потолок» от «оборвалось сразу».
        elapsed = _nonnegative_int(raw_elapsed, f"{field_name}.elapsed_ms")
    elif raw_elapsed is None:
        elapsed = None
    else:
        elapsed = _nonnegative_int(raw_elapsed, f"{field_name}.elapsed_ms")
    return typed, elapsed


def _forbid_topology(
    row: Mapping[str, Any],
    field_name: str,
    status: str,
) -> None:
    for key in _TOPOLOGY_FIELDS:
        if row[key]:
            raise CurtainPayloadError(
                f"{field_name}: {status} wall cannot carry {key}")


# ── Deterministic Revit C# emission ─────────────────────────────────────────
#
# This is an Execute-method body for the same ``wrap_user_code`` path used in
# serving.  It opens no Transaction and never calls get_Geometry/Tessellate.
# Grid-line and mullion curve endpoints cross the wire in world millimetres;
# host-local re-projection is a later offline parser concern.


CURTAIN_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE Wave P2-X — read-only curtain-grid topology helpers.
// Curve endpoints cross the wire in world millimetres. No Transaction opens.
Func<double, double> __cwMM = (__feet) =>
    UnitUtils.ConvertFromInternalUnits(__feet, UnitTypeId.Millimeters);
Func<XYZ, bool> __cwFiniteXYZ = (__point) =>
    __point != null
    && !Double.IsNaN(__point.X) && !Double.IsInfinity(__point.X)
    && !Double.IsNaN(__point.Y) && !Double.IsInfinity(__point.Y)
    && !Double.IsNaN(__point.Z) && !Double.IsInfinity(__point.Z);
Func<XYZ, object> __cwPoint = (__point) => (object)new double[] {
    __cwMM(__point.X), __cwMM(__point.Y), __cwMM(__point.Z)
};
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element/Curve/Surface и у исключений — это полное имя
// типа CLR: из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ,
// WorksetId, ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и
// ни один из них сюда не передаётся. Исключение дописывает ": сообщение" и
// стек, поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __cwClassName = (__cwcnObj) =>
{
    if (__cwcnObj == null) return "";
    string __cwcn = __cwcnObj.ToString();
    if (__cwcn == null) return "";
    int __cwcnCut = __cwcn.IndexOf((char)10);
    if (__cwcnCut >= 0) __cwcn = __cwcn.Substring(0, __cwcnCut);
    __cwcnCut = __cwcn.IndexOf(':');
    if (__cwcnCut >= 0) __cwcn = __cwcn.Substring(0, __cwcnCut);
    __cwcn = __cwcn.Trim();
    __cwcnCut = __cwcn.LastIndexOf('.');
    return __cwcnCut >= 0 && __cwcnCut + 1 < __cwcn.Length
        ? __cwcn.Substring(__cwcnCut + 1) : __cwcn;
};
Func<Exception, string> __cwError = (__error) =>
{
    string __message = __cwClassName(__error) + ": " + (__error.Message ?? "");
    return __message.Length <= 300 ? __message : __message.Substring(0, 300);
};
// A straight bound Line becomes ("line", p0, p1); anything else is the honest
// curved_unsupported marker with no endpoints. Curves are never tessellated.
Func<Curve, Dictionary<string, object>> __cwCurve = (__curve) =>
{
    var __row = new Dictionary<string, object>();
    __row["curve_state"] = "curved_unsupported";
    __row["p0_mm"] = null;
    __row["p1_mm"] = null;
    try
    {
        Line __line = __curve as Line;
        if (__line != null && __line.IsBound)
        {
            XYZ __start = __line.GetEndPoint(0);
            XYZ __end = __line.GetEndPoint(1);
            if (__cwFiniteXYZ(__start) && __cwFiniteXYZ(__end))
            {
                __row["curve_state"] = "line";
                __row["p0_mm"] = __cwPoint(__start);
                __row["p1_mm"] = __cwPoint(__end);
            }
        }
    }
    catch { }
    return __row;
};
Func<ElementId, string> __cwIdString = (__id) =>
    __id == null ? null : __id.ToString();
"""


_CURTAIN_EXTRACT_BODY_CS = r"""
var __cwRequestedIds = new string[] { __CW_WALL_IDS__ };
long __cwElementBudgetMs = __CW_ELEMENT_BUDGET_MS__L;
long __cwCallBudgetMs = __CW_CALL_BUDGET_MS__L;
long __cwCallWatchT0 = DateTime.UtcNow.Ticks;

// Носителей витражной сетки в Revit ТРИ РОДА, а не один: стена, витражная
// система, кровля. Пока коллектор смотрел только на стены, панели остальных
// не попадали в индекс вовсе — снаружи это читалось как «компилятор не умеет
// панели», хотя мы просто не смотрели (дизайн 2026-07-28, пункт 4).
var __cwRequestedSet = new HashSet<string>(__cwRequestedIds);
var __cwFound = new Dictionary<string, Element>();
var __cwHostCats = new BuiltInCategory[] {
    BuiltInCategory.OST_Walls,
    BuiltInCategory.OST_CurtaSystem,
    BuiltInCategory.OST_Roofs
};
foreach (BuiltInCategory __cwCat in __cwHostCats)
{
    if (((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwCallBudgetMs) break;
    if (__cwFound.Count == __cwRequestedSet.Count) break;
    foreach (Element __element in new FilteredElementCollector(__src)
             .OfCategory(__cwCat)
             .WhereElementIsNotElementType())
    {
        if (((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwCallBudgetMs) break;
        string __id = __element.Id.ToString();
        if (__cwRequestedSet.Contains(__id) && !__cwFound.ContainsKey(__id))
        {
            __cwFound[__id] = __element;
            if (__cwFound.Count == __cwRequestedSet.Count) break;
        }
    }
}

Func<Element, string> __cwHostKind = (__host) =>
{
    if (__host is Wall) return "wall";
    if (__host is CurtainSystem) return "curtain_system";
    if (__host is RoofBase) return "roof";
    return null;
};

// ДВЕНАДЦАТЬ СЛОТОВ ТИПОВЫХ ИМПОСТОВ. Семьи две, и нужны обе: стена
// разрезается по VERT/HORIZ, витражная система и наклонное остекление —
// по GRID1/GRID2 (RevitAPI.xml эталонного пакета, все шесть версий).
// Ярлык у всех одинаковый («Border 1 Type», «Interior Type»), различает
// их только сам BuiltInParameter — по имени не разобрать, да и нельзя
// (ИНВАРИАНТ #1).
var __cwMulBips = new BuiltInParameter[] {
    BuiltInParameter.AUTO_MULLION_BORDER1_VERT,
    BuiltInParameter.AUTO_MULLION_BORDER2_VERT,
    BuiltInParameter.AUTO_MULLION_INTERIOR_VERT,
    BuiltInParameter.AUTO_MULLION_BORDER1_HORIZ,
    BuiltInParameter.AUTO_MULLION_BORDER2_HORIZ,
    BuiltInParameter.AUTO_MULLION_INTERIOR_HORIZ,
    BuiltInParameter.AUTO_MULLION_BORDER1_GRID1,
    BuiltInParameter.AUTO_MULLION_BORDER2_GRID1,
    BuiltInParameter.AUTO_MULLION_INTERIOR_GRID1,
    BuiltInParameter.AUTO_MULLION_BORDER1_GRID2,
    BuiltInParameter.AUTO_MULLION_BORDER2_GRID2,
    BuiltInParameter.AUTO_MULLION_INTERIOR_GRID2
};
var __cwMulSlots = new string[] {
    "border1_vert", "border2_vert", "interior_vert",
    "border1_horiz", "border2_horiz", "interior_horiz",
    "border1_grid1", "border2_grid1", "interior_grid1",
    "border1_grid2", "border2_grid2", "interior_grid2"
};
// РАСКЛАДКА СЕТКИ у типа носителя. Семей три, и все нужны: стена режется
// по VERT/HORIZ, витражная система — по SPACING_LAYOUT_1/2, наклонное
// остекление — по U/V (RevitAPI.xml эталонного пакета, все шесть версий).
// Ярлык у всех шести «Layout» — различает только сам BuiltInParameter.
var __cwLayBips = new BuiltInParameter[] {
    BuiltInParameter.SPACING_LAYOUT_VERT,
    BuiltInParameter.SPACING_LAYOUT_HORIZ,
    BuiltInParameter.SPACING_LAYOUT_1,
    BuiltInParameter.SPACING_LAYOUT_2,
    BuiltInParameter.SPACING_LAYOUT_U,
    BuiltInParameter.SPACING_LAYOUT_V
};
var __cwLaySlots = new string[] {
    "vert", "horiz", "grid1", "grid2", "u", "v"
};
Func<Dictionary<string, object>> __cwLayNotCaptured = () =>
{
    var __slots = new Dictionary<string, object>();
    for (int __i = 0; __i < __cwLaySlots.Length; __i++)
        __slots[__cwLaySlots[__i]] = null;
    var __out = new Dictionary<string, object>();
    __out["slots"] = __slots;
    __out["state"] = "not_captured";
    return __out;
};
// Строка «не смотрели»: у не-витражного и у отказавшего носителя слоты
// пусты именно потому, что их не читали, — и говорят это сами.
Func<Dictionary<string, object>> __cwMulNotCaptured = () =>
{
    var __slots = new Dictionary<string, object>();
    for (int __i = 0; __i < __cwMulSlots.Length; __i++)
        __slots[__cwMulSlots[__i]] = null;
    var __out = new Dictionary<string, object>();
    __out["slots"] = __slots;
    __out["state"] = "not_captured";
    return __out;
};

var __cwWallRows = new List<object>();
foreach (string __requestedId in __cwRequestedIds)
{
    var __row = new Dictionary<string, object>();
    __row["wall_id"] = __requestedId;
    __row["status"] = "failed";
    __row["reason"] = "wall not resolved";
    __row["typed_reason"] = null;
    __row["elapsed_ms"] = null;
    __row["host_kind"] = "wall";
    __row["default_panel_type_id"] = null;
    __row["default_panel_type_name"] = null;
    __row["default_panel_state"] = "not_captured";
    __row["default_panel_source"] = null;
    __row["auto_mullion_types"] = __cwMulNotCaptured();
    __row["grid_layout"] = __cwLayNotCaptured();
    var __uLines = new List<object>();
    var __vLines = new List<object>();
    var __panels = new List<object>();
    var __mullions = new List<object>();
    __row["u_grid_lines"] = __uLines;
    __row["v_grid_lines"] = __vLines;
    __row["panels"] = __panels;
    __row["mullions"] = __mullions;

    string __cwBudgetReason = null;
    long __cwBudgetElapsed = 0L;

    if (((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwCallBudgetMs)
    {
        __cwBudgetReason = "call_budget_exhausted";
        __cwBudgetElapsed = ((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond);
    }
    else
    {
        long __cwElementWatchT0 = DateTime.UtcNow.Ticks;
        Func<bool> __cwBudgetExceeded = () =>
            ((DateTime.UtcNow.Ticks - __cwElementWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwElementBudgetMs ||
            ((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwCallBudgetMs;

        Element __element = null;
        __cwFound.TryGetValue(__requestedId, out __element);
        string __cwKind = __cwHostKind(__element);
        // ДВА РАЗНЫХ СЛУЧАЯ, И РАЗНИЦА МЕЖДУ НИМИ — ВСЯ СУТЬ КВИТАНЦИИ.
        // Одной строкой «requested element is not a curtain host» они шли
        // вместе, и снаружи «мы не нашли элемент» было неотличимо от «нашли,
        // и он просто не носитель сетки». Первое — наш недосмотр (срез),
        // второе — факт о модели (определение); складывать их в одно число
        // значит потерять причину ровно там, где её и спрашивают.
        if (__element == null)
        {
            __row["reason"] = "element_unresolved";
            __row["typed_reason"] = "element_unresolved";
        }
        else if (__cwKind == null)
        {
            __row["reason"] = "element_kind_mismatch";
            __row["typed_reason"] = "element_kind_mismatch";
        }
        else
        {
            __row["host_kind"] = __cwKind;
            try
            {
                var __cwGrids = __ccGrids(__element);
                if (__cwGrids.Count == 0)
                {
                    __row["status"] = "not_curtain";
                    __row["reason"] = "host has no CurtainGrid";
                }
                else if (__cwGrids.Count > 1)
                {
                    // Несколько сеток на одном носителе: адрес (u,v) без
                    // номера сетки неоднозначен. Отдать первую значило бы
                    // выдать догадку за адрес. Это ограничение НАШЕГО
                    // адреса, а не факт о модели, — потому срез, а не
                    // определение.
                    __row["reason"] = "multiple_curtain_grids";
                    __row["typed_reason"] = "address_ambiguous";
                }
                else
                {
                    CurtainGrid __grid = __cwGrids[0];

                    // Тип панели, которым носитель разрезает сетку САМ.
                    // Без него «штатная панель» и «заменённая» неразличимы.
                    //
                    // ПАРАМЕТРОВ ДВА, И ОБА НАЗЫВАЮТСЯ «Curtain Panel».
                    // Источник — RevitAPI.xml из эталонного пакета (не вики):
                    //   <member name="F:...BuiltInParameter.AUTO_PANEL_WALL">
                    //       <summary> "Curtain Panel" </summary>
                    //   <member name="F:...BuiltInParameter.AUTO_PANEL">
                    //       <summary> "Curtain Panel" </summary>
                    // Суффикс _WALL называет семейство носителя: у типа
                    // витражной СТЕНЫ параметр этот, а не безымянный AUTO_
                    // PANEL. Живой прогон 28.07 (v4, Revit 2023, фасад
                    // SOB6.2) читал только AUTO_PANEL и получил null на всех
                    // 195 носителях — 311 ячеек отказали на ровном месте.
                    // Опрашиваются ОБА, и ответивший называется в
                    // default_panel_source: провенанс живёт рядом с числом.
                    //
                    // Пустой catch здесь БЫЛ и стоил круга: null не отличал
                    // «у типа нет автопанели» от «прочитать не смогли».
                    // Теперь каждая из трёх истин называет себя сама.
                    var __cwPanelBips = new BuiltInParameter[] {
                        BuiltInParameter.AUTO_PANEL_WALL,
                        BuiltInParameter.AUTO_PANEL
                    };
                    var __cwPanelBipNames = new string[] {
                        "AUTO_PANEL_WALL", "AUTO_PANEL"
                    };
                    string __cwDefState = "unreadable";
                    string __cwDefSource = null;
                    try
                    {
                        Element __cwHostType =
                            __src.GetElement(__element.GetTypeId());
                        if (__cwHostType != null)
                        {
                            for (int __cwB = 0;
                                 __cwB < __cwPanelBips.Length; __cwB++)
                            {
                                Parameter __cwAuto =
                                    __cwHostType.get_Parameter(
                                        __cwPanelBips[__cwB]);
                                if (__cwAuto == null) continue;
                                // Параметр НАЙДЕН — значит про него уже
                                // можно сказать правду, пустой он или нет.
                                if (__cwDefState == "unreadable")
                                {
                                    __cwDefState = "none";
                                    __cwDefSource = __cwPanelBipNames[__cwB];
                                }
                                ElementId __cwDefId = __cwAuto.AsElementId();
                                if (__cwDefId != null
                                    && __cwDefId.ToString() !=
                                       ElementId.InvalidElementId.ToString())
                                {
                                    __row["default_panel_type_id"] =
                                        __cwDefId.ToString();
                                    Element __cwDefEl =
                                        __src.GetElement(__cwDefId);
                                    if (__cwDefEl != null)
                                        __row["default_panel_type_name"] =
                                            __cwDefEl.Name;
                                    __cwDefState = "ok";
                                    __cwDefSource = __cwPanelBipNames[__cwB];
                                    break;
                                }
                            }
                        }
                    }
                    catch (Exception __cwDefEx)
                    {
                        __cwDefState = "unreadable";
                        __cwDefSource = "exception: " + __cwError(__cwDefEx);
                        __row["default_panel_type_id"] = null;
                        __row["default_panel_type_name"] = null;
                    }
                    if (__cwDefState == "unreadable" && __cwDefSource == null)
                        __cwDefSource = "tried: AUTO_PANEL_WALL, AUTO_PANEL";
                    __row["default_panel_state"] = __cwDefState;
                    __row["default_panel_source"] = __cwDefSource;

                    // ИМПОСТЫ, КОТОРЫЕ НОСИТЕЛЬ СТАВИТ САМ.
                    //
                    // Импост нельзя создать операцией: единственный его
                    // конструктор — CurtainGridLine.AddMullions по сегменту,
                    // и опы для него в реестре нет. Поэтому единственный
                    // честный способ засчитать импост — доказать, что его
                    // РОДИТ ПЕРЕСБОРКА НОСИТЕЛЯ. Доказательство требует
                    // типовых слотов: «его сделала сетка» — утверждение о
                    // ТИПЕ, и проверяется только типом.
                    //
                    // СЕМЕЙ ПАРАМЕТРОВ ДВЕ, И НУЖНЫ ОБЕ. Источник —
                    // RevitAPI.xml эталонного пакета, все шесть версий:
                    //   AUTO_MULLION_{BORDER1,BORDER2,INTERIOR}_{VERT,HORIZ}
                    //   AUTO_MULLION_{BORDER1,BORDER2,INTERIOR}_{GRID1,GRID2}
                    // Стена разрезается по VERT/HORIZ, витражная система и
                    // наклонное остекление — по GRID1/GRID2. Ярлык у всех
                    // одинаковый («Border 1 Type», «Interior Type»), так что
                    // различает их только сам BuiltInParameter — по имени не
                    // разобрать (и разбирать запрещено, ИНВАРИАНТ #1).
                    var __cwMulTypes = new Dictionary<string, object>();
                    for (int __cwM = 0; __cwM < __cwMulSlots.Length; __cwM++)
                        __cwMulTypes[__cwMulSlots[__cwM]] = null;
                    // Три исхода называют себя сами — ровно тот урок, что
                    // стоил круга на default_panel: null не отличал «тип не
                    // ставит импостов» от «прочитать не смогли».
                    string __cwMulState = "unreadable";
                    try
                    {
                        Element __cwMulHostType =
                            __src.GetElement(__element.GetTypeId());
                        if (__cwMulHostType != null)
                        {
                            __cwMulState = "none";
                            for (int __cwM = 0;
                                 __cwM < __cwMulBips.Length; __cwM++)
                            {
                                Parameter __cwMulP =
                                    __cwMulHostType.get_Parameter(
                                        __cwMulBips[__cwM]);
                                if (__cwMulP == null) continue;
                                ElementId __cwMulId = __cwMulP.AsElementId();
                                if (__cwMulId == null
                                    || __cwMulId.ToString() ==
                                       ElementId.InvalidElementId.ToString())
                                    continue;
                                __cwMulTypes[__cwMulSlots[__cwM]] =
                                    __cwMulId.ToString();
                                __cwMulState = "ok";
                            }
                        }
                    }
                    catch
                    {
                        __cwMulState = "unreadable";
                        for (int __cwM = 0;
                             __cwM < __cwMulSlots.Length; __cwM++)
                            __cwMulTypes[__cwMulSlots[__cwM]] = null;
                    }
                    var __cwMulRow = new Dictionary<string, object>();
                    __cwMulRow["slots"] = __cwMulTypes;
                    __cwMulRow["state"] = __cwMulState;
                    __row["auto_mullion_types"] = __cwMulRow;

                    // ДЕЛИТ ЛИ ТИП СЕТКУ САМ — недостающее звено генератора.
                    //
                    // ЗАМЕР НОЧИ 28.07: у ВСЕХ пересобранных носителей ноль
                    // внутренних U/V линий при БАЙТ-ИДЕНТИЧНЫХ типах, а
                    // замыкание детей — 417/1556. Раскладка оказалась
                    // авторским состоянием, которого create_wall не несёт;
                    // без неё у носителя не воспроизводится ни одна ячейка
                    // и ни один импост. Чтобы ставить линии операцией и не
                    // удваивать те, что рождает тип, нужно ЧИСЛО раскладки
                    // типа — оно здесь и снимается.
                    var __cwLayVals = new Dictionary<string, object>();
                    for (int __cwL = 0; __cwL < __cwLaySlots.Length; __cwL++)
                        __cwLayVals[__cwLaySlots[__cwL]] = null;
                    string __cwLayState = "unreadable";
                    try
                    {
                        Element __cwLayType =
                            __src.GetElement(__element.GetTypeId());
                        if (__cwLayType != null)
                        {
                            __cwLayState = "none";
                            for (int __cwL = 0;
                                 __cwL < __cwLayBips.Length; __cwL++)
                            {
                                Parameter __cwLayP =
                                    __cwLayType.get_Parameter(
                                        __cwLayBips[__cwL]);
                                if (__cwLayP == null) continue;
                                if (__cwLayP.StorageType !=
                                    StorageType.Integer) continue;
                                if (!__cwLayP.HasValue) continue;
                                __cwLayVals[__cwLaySlots[__cwL]] =
                                    __cwLayP.AsInteger();
                                __cwLayState = "ok";
                            }
                        }
                    }
                    catch
                    {
                        __cwLayState = "unreadable";
                        for (int __cwL = 0;
                             __cwL < __cwLaySlots.Length; __cwL++)
                            __cwLayVals[__cwLaySlots[__cwL]] = null;
                    }
                    var __cwLayRow = new Dictionary<string, object>();
                    __cwLayRow["slots"] = __cwLayVals;
                    __cwLayRow["state"] = __cwLayState;
                    __row["grid_layout"] = __cwLayRow;

                    // Stage 1: U/V grid lines. Each line is a bounded API/loop
                    // body; the budget is checked between lines so no id is
                    // partially emitted after the deadline.
                    Action<ICollection<ElementId>, List<object>, string>
                        __cwReadLines = (__ids, __sink, __direction) =>
                    {
                        if (__ids == null) return;
                        foreach (ElementId __lineId in __ids)
                        {
                            if (__cwBudgetExceeded()) return;
                            var __lineRow = new Dictionary<string, object>();
                            __lineRow["line_id"] = __lineId.ToString();
                            __lineRow["curve_state"] = "curved_unsupported";
                            __lineRow["p0_mm"] = null;
                            __lineRow["p1_mm"] = null;
                            __lineRow["existing_segment_count"] = 0;
                            __lineRow["skipped_segment_count"] = 0;
                            __lineRow["locked"] = null;
                            try
                            {
                                var __gridLine = __src.GetElement(__lineId)
                                    as CurtainGridLine;
                                if (__gridLine != null)
                                {
                                    var __curveRow = __cwCurve(
                                        __gridLine.FullCurve);
                                    __lineRow["curve_state"] =
                                        __curveRow["curve_state"];
                                    __lineRow["p0_mm"] = __curveRow["p0_mm"];
                                    __lineRow["p1_mm"] = __curveRow["p1_mm"];
                                    var __existing =
                                        __gridLine.ExistingSegmentCurves;
                                    __lineRow["existing_segment_count"] =
                                        __existing == null
                                            ? 0 : __existing.Size;
                                    var __skipped =
                                        __gridLine.SkippedSegmentCurves;
                                    __lineRow["skipped_segment_count"] =
                                        __skipped == null ? 0 : __skipped.Size;
                                    try
                                    {
                                        __lineRow["locked"] =
                                            (object)__gridLine.Lock;
                                    }
                                    catch { __lineRow["locked"] = null; }
                                }
                            }
                            catch { }
                            __sink.Add(__lineRow);
                        }
                    };
                    __cwReadLines(__grid.GetUGridLineIds(), __uLines, "u");
                    if (!__cwBudgetExceeded())
                        __cwReadLines(
                            __grid.GetVGridLineIds(), __vLines, "v");

                    // Stage 2: panels — то есть ЯЧЕЙКИ. Панель бывает трёх
                    // исполнений: чистая Panel, экземпляр семейства (в том
                    // числе витражная дверь или окно) и обёртка над стеной,
                    // заполнившей ячейку. Тип читается через GetTypeId, то
                    // есть ОДИНАКОВО для всех трёх: схема /1 читала его
                    // только у FamilyInstance.Symbol и оставляла тип панели-
                    // стены пустым, хотя он всё это время лежал рядом.
                    List<ElementId> __cwUOrder = null;
                    List<ElementId> __cwVOrder = null;
                    if (!__cwBudgetExceeded())
                    {
                        __cwUOrder = __ccOrder(__grid.GetUGridLineIds());
                        __cwVOrder = __ccOrder(__grid.GetVGridLineIds());
                    }
                    if (!__cwBudgetExceeded())
                    {
                        ICollection<ElementId> __panelIds =
                            __grid.GetPanelIds();
                        if (__panelIds != null)
                            foreach (ElementId __panelId in __panelIds)
                            {
                                if (__cwBudgetExceeded()) break;
                                var __panelRow =
                                    new Dictionary<string, object>();
                                __panelRow["panel_id"] = __panelId.ToString();
                                __panelRow["is_family_instance"] = false;
                                __panelRow["family_name"] = null;
                                __panelRow["type_name"] = null;
                                __panelRow["type_id"] = null;
                                __panelRow["host_panel_id"] = null;
                                __panelRow["host_panel_type_id"] = null;
                                __panelRow["host_panel_type_name"] = null;
                                __panelRow["u_index"] = null;
                                __panelRow["v_index"] = null;
                                __panelRow["address_state"] = "not_a_panel";
                                __panelRow["is_door"] = false;
                                try
                                {
                                    var __panelElement =
                                        __src.GetElement(__panelId);
                                    if (__panelElement != null)
                                    {
                                        Category __category =
                                            __panelElement.Category;
                                        // ElementId.ToString() is the
                                        // version-safe value read
                                        // (IntegerValue is gone in 2026).
                                        if (__category != null &&
                                            __category.Id != null &&
                                            __category.Id.ToString() ==
                                            ((int)BuiltInCategory.OST_Doors)
                                                .ToString())
                                            __panelRow["is_door"] = true;
                                        var __familyInstance =
                                            __panelElement as FamilyInstance;
                                        if (__familyInstance != null)
                                        {
                                            __panelRow["is_family_instance"] =
                                                true;
                                            var __symbol =
                                                __familyInstance.Symbol;
                                            if (__symbol != null
                                                && __symbol.Family != null)
                                                __panelRow["family_name"] =
                                                    __symbol.Family.Name;
                                        }
                                        ElementId __panelTypeId =
                                            __panelElement.GetTypeId();
                                        if (__panelTypeId != null
                                            && __panelTypeId.ToString() !=
                                               ElementId.InvalidElementId
                                                   .ToString())
                                        {
                                            __panelRow["type_id"] =
                                                __panelTypeId.ToString();
                                            Element __panelType =
                                                __src.GetElement(__panelTypeId);
                                            if (__panelType != null)
                                                __panelRow["type_name"] =
                                                    __panelType.Name;
                                        }
                                        var __panel =
                                            __panelElement as Panel;
                                        if (__panel != null)
                                        {
                                            ElementId __bodyId =
                                                __panel.FindHostPanel();
                                            if (__bodyId != null
                                                && __bodyId.ToString() !=
                                                   ElementId.InvalidElementId
                                                       .ToString())
                                            {
                                                __panelRow["host_panel_id"] =
                                                    __bodyId.ToString();
                                                // Ячейка, заполненная
                                                // стеной: НАСТОЯЩИЙ тип
                                                // лежит на теле, а не на
                                                // обёртке.
                                                Element __body =
                                                    __src.GetElement(__bodyId);
                                                if (__body != null)
                                                {
                                                    ElementId __bodyTypeId =
                                                        __body.GetTypeId();
                                                    if (__bodyTypeId != null
                                                        && __bodyTypeId
                                                            .ToString() !=
                                                           ElementId
                                                            .InvalidElementId
                                                            .ToString())
                                                    {
                                                        __panelRow[
                                                            "host_panel_type_id"] =
                                                            __bodyTypeId.ToString();
                                                        Element __bodyType =
                                                            __src.GetElement(
                                                                __bodyTypeId);
                                                        if (__bodyType != null)
                                                            __panelRow[
                                                                "host_panel_type_name"] =
                                                                __bodyType.Name;
                                                    }
                                                }
                                            }
                                            if (__cwUOrder == null
                                                || __cwVOrder == null)
                                                __panelRow["address_state"] =
                                                    "grid_order_undecidable";
                                            else
                                            {
                                                int[] __addr = __ccAddress(
                                                    __panelElement,
                                                    __cwUOrder, __cwVOrder);
                                                if (__addr == null)
                                                    __panelRow[
                                                        "address_state"] =
                                                        "ref_line_unranked";
                                                else
                                                {
                                                    __panelRow["u_index"] =
                                                        __addr[0];
                                                    __panelRow["v_index"] =
                                                        __addr[1];
                                                    __panelRow[
                                                        "address_state"] = "ok";
                                                }
                                            }
                                        }
                                    }
                                }
                                catch { }
                                __panels.Add(__panelRow);
                            }
                    }

                    // Stage 3: mullions.
                    if (!__cwBudgetExceeded())
                    {
                        ICollection<ElementId> __mullionIds =
                            __grid.GetMullionIds();
                        if (__mullionIds != null)
                            foreach (ElementId __mullionId in __mullionIds)
                            {
                                if (__cwBudgetExceeded()) break;
                                var __mullionRow =
                                    new Dictionary<string, object>();
                                __mullionRow["mullion_id"] =
                                    __mullionId.ToString();
                                __mullionRow["type_name"] = null;
                                __mullionRow["type_id"] = null;
                                __mullionRow["locked"] = null;
                                __mullionRow["direction"] = "unknown";
                                __mullionRow["curve_state"] =
                                    "curved_unsupported";
                                __mullionRow["p0_mm"] = null;
                                __mullionRow["p1_mm"] = null;
                                try
                                {
                                    var __mullion = __src.GetElement(__mullionId)
                                        as Mullion;
                                    if (__mullion != null)
                                    {
                                        var __mullionType =
                                            __mullion.MullionType;
                                        if (__mullionType != null)
                                        {
                                            __mullionRow["type_name"] =
                                                __mullionType.Name;
                                            __mullionRow["type_id"] =
                                                __mullionType.Id.ToString();
                                        }
                                        // Собственная бухгалтерия Revit о
                                        // том, что импост ведёт ТИП:
                                        //   P:...Mullion.Lock — "Get - to get
                                        //   whether the Mullion line is
                                        //   locked".
                                        // Обратный переход Revit тоже знает:
                                        // CurtainWallFailures.RequestOrphan
                                        // MullionDeletion — «some mullions
                                        // became NON-TYPE DRIVEN».
                                        try
                                        {
                                            __mullionRow["locked"] =
                                                __mullion.Lock;
                                        }
                                        catch { }
                                        // ОСЬ ЧИТАЕТСЯ У Mullion.Location
                                        // Curve, а НЕ у Element.Location:
                                        // у импоста Location кривой не
                                        // отдаёт, и приведение `as
                                        // LocationCurve` возвращало null —
                                        // замер v11/демо-v3 схемой /3:
                                        // curved_unsupported у 964 из 964 и
                                        // у 26291 из 26291 импостов, то есть
                                        // у ВСЕХ. Кривых импостов столько не
                                        // бывает; это был отказ чтения,
                                        // притворявшийся геометрией.
                                        Curve __mullionCurve = null;
                                        try
                                        {
                                            __mullionCurve =
                                                __mullion.LocationCurve;
                                        }
                                        catch { }
                                        if (__mullionCurve != null)
                                        {
                                            var __curveRow = __cwCurve(
                                                __mullionCurve);
                                            __mullionRow["curve_state"] =
                                                __curveRow["curve_state"];
                                            __mullionRow["p0_mm"] =
                                                __curveRow["p0_mm"];
                                            __mullionRow["p1_mm"] =
                                                __curveRow["p1_mm"];
                                            // Направление — у самой оси, а
                                            // не у имени типа: тип носителя
                                            // задаёт вертикальные и
                                            // горизонтальные импосты РАЗНЫМИ
                                            // параметрами, и сравнивать надо
                                            // внутри направления.
                                            try
                                            {
                                                XYZ __mDir =
                                                    __mullionCurve.GetEndPoint(1)
                                                    - __mullionCurve.GetEndPoint(0);
                                                double __mDz =
                                                    Math.Abs(__mDir.Z);
                                                double __mDxy = Math.Sqrt(
                                                    __mDir.X * __mDir.X +
                                                    __mDir.Y * __mDir.Y);
                                                if (__mDz > __mDxy * 10.0)
                                                    __mullionRow["direction"] =
                                                        "vertical";
                                                else if (__mDxy > __mDz * 10.0)
                                                    __mullionRow["direction"] =
                                                        "horizontal";
                                            }
                                            catch { }
                                        }
                                    }
                                }
                                catch { }
                                __mullions.Add(__mullionRow);
                            }
                    }

                    __row["status"] = "ok";
                    __row["reason"] = null;
                }
            }
            catch (Exception __wallException)
            {
                __row["status"] = "failed";
                __row["reason"] =
                    "curtain read failed: " + __cwError(__wallException);
            }
        }

        if (((DateTime.UtcNow.Ticks - __cwElementWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwElementBudgetMs)
        {
            __cwBudgetReason = "time_budget_exceeded";
            __cwBudgetElapsed = ((DateTime.UtcNow.Ticks - __cwElementWatchT0) / TimeSpan.TicksPerMillisecond);
        }
        else if (((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __cwCallBudgetMs)
        {
            __cwBudgetReason = "call_budget_exhausted";
            __cwBudgetElapsed = ((DateTime.UtcNow.Ticks - __cwCallWatchT0) / TimeSpan.TicksPerMillisecond);
        }
    }

    if (__cwBudgetReason != null)
    {
        // Never mislabel a timed-out partial curtain read as usable topology.
        __uLines.Clear();
        __vLines.Clear();
        __panels.Clear();
        __mullions.Clear();
        __row["status"] = "failed";
        __row["reason"] = __cwBudgetReason;
        __row["typed_reason"] = __cwBudgetReason;
        __row["elapsed_ms"] = __cwBudgetElapsed;
        __row["default_panel_type_id"] = null;
        __row["default_panel_type_name"] = null;
        __row["default_panel_state"] = "not_captured";
        __row["default_panel_source"] = null;
        __row["auto_mullion_types"] = __cwMulNotCaptured();
        __row["grid_layout"] = __cwLayNotCaptured();
    }
    if ((string)__row["status"] != "ok")
    {
        __row["default_panel_type_id"] = null;
        __row["default_panel_type_name"] = null;
        __row["default_panel_state"] = "not_captured";
        __row["default_panel_source"] = null;
        __row["auto_mullion_types"] = __cwMulNotCaptured();
        __row["grid_layout"] = __cwLayNotCaptured();
    }
    __cwWallRows.Add(__row);
}
return new Dictionary<string, object> {
    {"schema_version", "kir-decompile-curtain-extract/5"},
    {"walls", __cwWallRows}
};
"""


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


def build_curtain_extract_cs(
    wall_ids: Sequence[str | int],
    *,
    element_budget_ms: int = 2_000,
    call_budget_ms: int = 20_000,
    link_title: str | None = None,
) -> str:
    """Emit one deterministic, read-only Revit Execute body.

    Numeric ids are resolved by their version-safe ``ElementId.ToString()``
    representation, avoiding the 2021/2024 ``int``/``long`` constructor fork.

    The two time budgets are cooperative fail-safes, not hard preemption
    (mirroring :func:`geom_extract.build_geometry_extract_cs`).  Elapsed time
    is checked before/after each Revit API stage — grid-line enumeration,
    panel enumeration, mullion enumeration — and between walls.  A single
    blocking API call may still exceed its budget, but any partial topology is
    discarded, the overrun is reported as a typed ``time_budget_exceeded`` /
    ``call_budget_exhausted`` failure, and every remaining wall id is still
    accounted for.

    ОБЩИЙ С ПРЯМЫМ КОМПИЛЯТОРОМ АДРЕС ЯЧЕЙКИ ЕДЕТ СЮДА ЖЕ, и он тоже читает
    документ (линия сетки, панель, тело панели). Поэтому источник передаётся
    и в него: одна ячейка, посчитанная по двум документам, — это адрес,
    который не переживёт пересборку, при том что обе стороны по отдельности
    выглядят правильными.

    ``link_title`` — читать не ХОЗЯИНА, а его СВЯЗЬ с таким ``Document.Title``.
    Источник один на ВСЁ тело: у документов разные пространства
    идентификаторов, поэтому id связи, спрошенный у хозяина, либо не находится
    (квитанция на ровном месте), либо находит ЧУЖОЙ элемент с тем же числом —
    и тогда стадия записывает чужую строку как свою, молча. Замер 30.07 на
    связанной электрике Snowdon дал оба исхода разом.
    """

    if isinstance(wall_ids, (str, bytes)):
        raise ValueError("wall_ids must be a sequence, not a string")
    normalized = []
    for index, value in enumerate(wall_ids):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(
                f"wall_ids[{index}] must be a numeric string or integer")
        item = str(value)
        if re.fullmatch(r"-?[0-9]+", item) is None:
            raise ValueError(f"wall_ids[{index}] must be a numeric Revit id")
        normalized.append(item)
    if not normalized:
        raise ValueError("at least one wall id is required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("wall_ids must be unique")

    for field_name, value in (
        ("element_budget_ms", element_budget_ms),
        ("call_budget_ms", call_budget_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        if value > 9_223_372_036_854_775_807:
            raise ValueError(f"{field_name} exceeds the C# Int64 range")

    body = _CURTAIN_EXTRACT_BODY_CS.replace(
        "__CW_WALL_IDS__",
        ", ".join(_csharp_string(value) for value in normalized),
        1,
    )
    body = body.replace("__CW_ELEMENT_BUDGET_MS__", str(element_budget_ms))
    body = body.replace("__CW_CALL_BUDGET_MS__", str(call_budget_ms))
    if "__CW_" in body:
        raise CurtainExtractionError(
            "internal curtain emitter placeholder was not resolved")
    # Адрес ячейки определён ОДИН РАЗ и подставляется сюда из прямого
    # компилятора: захват и эмиттер обязаны считать (u,v) одним и тем же
    # кодом, иначе адрес не переживёт пересборку — молча, потому что каждая
    # сторона по отдельности выглядела бы правильной.
    from kukai.ir.authoring import curtain_cell_address_cs

    return (
        source_binding_cs(link_title)
        + "\n" + CURTAIN_EXTRACT_HELPER_CS.strip()
        + "\n" + curtain_cell_address_cs("", document="__src").strip()
        + "\n" + body.strip())


# Descriptive aliases keep the public boundary discoverable.
parse_curtain_topology = extract_curtain_topology


__all__ = [
    "CURTAIN_EXTRACT_SCHEMA_VERSION",
    "CURTAIN_INDEX_SCHEMA_VERSION",
    "CURTAIN_INDEX_SCHEMA_VERSION_LEGACY",
    "CURTAIN_INDEX_SCHEMA_VERSION_ADDRESSED",
    "CURTAIN_INDEX_SCHEMA_VERSION_PANEL_STATE",
    "AUTO_MULLION_SLOTS",
    "AutoMullionState",
    "AutoMullionTypes",
    "CURTAIN_INDEX_SCHEMA_VERSION_MULLION",
    "CURTAIN_INDEX_SCHEMA_VERSION_UNTYPED_RECEIPTS",
    "GRID_LAYOUT_SLOTS",
    "GRID_LAYOUT_NONE",
    "GridLayout",
    "GridLayoutState",
    "GridLineState",
    "DefaultPanelState",
    "SUPPORTED_CURTAIN_INDEX_SCHEMA_VERSIONS",
    "CURTAIN_EXTRACT_HELPER_CS",
    "CellAddressState",
    "HostKind",
    "CurtainExtraction",
    "CurtainExtractionError",
    "CurtainFailure",
    "CurtainFailureReason",
    "CurtainPayloadError",
    "CurtainWallRecord",
    "CurveState",
    "GridDirection",
    "GridLineRecord",
    "MullionDirection",
    "MullionRecord",
    "MullionState",
    "PanelRecord",
    "build_curtain_extract_cs",
    "extract_curtain_topology",
    "parse_curtain_topology",
]
