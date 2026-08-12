"""Deterministic, fail-closed DECOMPILE L0 -> L1 lifting.

Each :class:`~kukai.ir.decompile.schema.L0Element` produces exactly one
JSON-ready L1 node.  A node is a regenerable KIR op only when all facts needed
by the live forward op are present; every other outcome is an honest atom.

This module is deliberately offline.  It reads the frozen Wave A dataclasses
and the live registries, but performs no bridge calls and emits no C#.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Sequence, cast

from kukai.ir import contour as _contour
from kukai.ir import geom as _geom
from kukai.ir import spec
from kukai.ir.ops_authoring import WALL_LOCATION_LINE_NAMES
from kukai.ir.reverse_contract import (
    REVERSE_CONTRACTS,
    ReverseMode,
    assert_lift_emission,
)

#: Read off the op itself, so the lift can never offer a plane the emitter has
#: stopped realising (or miss one it has learned).
_LOCATION_LINE_CHOICES = frozenset(
    next(p for p in spec.OPS["create_wall"].params
         if p.name == "location_line").choices)
from kukai.ir.decompile.l1_schema import (
    AtomReason,
    L1AtomNode,
    L1Node,
    L1OpNode,
    is_valid_l1_node,
    stable_l1_id,
    validate_l1_nodes,
)
from kukai.ir.decompile.curtain_extract import (
    CURTAIN_INDEX_SCHEMA_VERSION,
    CellAddressState,
    CurtainPayloadError,
    CurtainWallRecord,
    CurveState,
    DefaultPanelState,
    GridDirection,
    GridLineRecord,
    GridLineState,
    MullionRecord,
    MullionState,
    PanelRecord,
)
from kukai.ir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    FamilyPlacementPayloadError,
    FamilyPlacementRecord,
    FamilyPlacementType,
    parse_family_placement_failures,
    parse_family_placement_index,
)
from kukai.ir.decompile.schema import (
    CANON_MM,
    GeometryKind,
    GridInfo,
    HostSource,
    L0Document,
    L0Element,
    LevelInfo,
    LocationCurveKind,
    RoomInfo,
    Vec2,
    Vec3,
)
from kukai.ir.decompile.sketch_extract import (
    CurveKind,
    ProfileIndexRecord,
    RailingPathRecord,
    SketchPayloadError,
    StairsRunPathRecord,
)
from kukai.ir.decompile.dimension_extract import (
    DIMENSION_CATEGORIES,
    DIMENSION_SHAPE_LINEAR,
    DimensionExtraction,
    DimensionPayloadError,
)
from kukai.ir.decompile.mep_system_extract import (
    MepSystemExtraction,
    MepSystemPayloadError,
)
from kukai.ir.decompile.annotation_extract import (
    AnnotationExtraction,
    AnnotationPayloadError,
)
from kukai.ir.decompile.tag_extract import (
    TAG_CATEGORIES,
    TAG_FAMILY_INDEPENDENT,
    TAG_ORIENTATION_HORIZONTAL,
    TagExtraction,
    TagPayloadError,
)
from kukai.ir.decompile.curve_extract import (
    CurveExtraction,
    CurveKind as WallCurveKind,
    CurvePayloadError,
)


@dataclass(frozen=True, slots=True)
class LiftDiagnostic:
    """Why one source element conservatively became an atom."""

    source_element_id: str
    category: str
    reason: AtomReason
    detail: str


@dataclass(frozen=True, slots=True)
class LiftResult:
    """L1 nodes plus optional per-atom observability for audits/tests."""

    nodes: tuple[L1Node, ...]
    diagnostics: tuple[LiftDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: str
    op: str
    lifter_name: str


# The exact Part 5 table, including entries currently forced to atoms by a
# registry or frozen-L0 gap.  Categories absent from this table never acquire
# an inferred op merely because a similarly named op happens to exist.
_CANDIDATES: dict[str, _Candidate] = {
    "OST_Walls": _Candidate("wall", "create_wall", "_lift_wall"),
    "OST_Floors": _Candidate("floor", "create_floor", "_lift_floor"),
    "OST_Roofs": _Candidate("roof", "create_roof", "_lift_roof"),
    "OST_Columns": _Candidate(
        "column_architectural", "create_column", "_lift_column"),
    "OST_StructuralColumns": _Candidate(
        "column_structural", "create_column", "_lift_column"),
    "OST_StructuralFraming": _Candidate(
        "beam", "create_beam", "_lift_beam"),
    "OST_StructuralFoundation": _Candidate(
        "foundation", "create_foundation", "_lift_foundation"),
    "OST_Doors": _Candidate("door", "create_door", "_lift_door"),
    "OST_Windows": _Candidate("window", "create_window", "_lift_window"),
    "OST_Rooms": _Candidate("room", "create_room", "_lift_room"),
    # Текстовое примечание поднимается, КОГДА боковой индекс оформления его
    # принёс. Когда индекса нет (все слепки до 30.07), лифтер отказывает тем
    # же source_contract_gap, что и раньше, — прежние разборы обязаны дать
    # прежний ответ дословно, иначе «мы ничего не сломали» непроверяемо.
    "OST_TextNotes": _Candidate(
        "text_note", "create_text", "_lift_text"),
    # Размер поднимается, КОГДА боковой индекс размеров его принёс. Когда
    # индекса нет (все слепки до этой волны), лифтер отказывает тем же
    # source_contract_gap с тем же текстом, что и раньше, — прежние разборы
    # обязаны дать прежний ответ ДОСЛОВНО, иначе «мы ничего не сломали»
    # непроверяемо. Ровно та же дисциплина, что у примечаний и марок.
    "OST_Dimensions": _Candidate(
        "dimension", "create_dimension", "_lift_dimension"),
    "OST_Levels": _Candidate("level", "create_level", "_lift_level"),
    "OST_Grids": _Candidate("grid", "create_grid", "_lift_grid"),
    "OST_PipeCurves": _Candidate("pipe", "create_pipe", "_lift_pipe"),
    "OST_DuctCurves": _Candidate("duct", "create_duct", "_lift_duct"),
    "OST_CableTray": _Candidate(
        "cable_tray", "create_cable_tray", "_lift_cable_tray"),
    # wave/mep-electrical (2026-08-09). Категория появилась здесь ровно по
    # той же причине, что потолок и ограждение на волне архитектуры: у неё
    # НАКОНЕЦ ЕСТЬ ОП. До неё каждый короб уходил в атом с причиной
    # «категории нет в таблице лифтера», и это была правда; теперь причиной
    # может быть только недостающий ФАКТ (не-прямая кривая), а разница между
    # этими двумя ответами решает, что чинить следующим.
    "OST_Conduit": _Candidate(
        "conduit", "create_conduit", "_lift_conduit"),
    "OST_Stairs": _Candidate("stair", "create_stairs", "_lift_stairs"),
    # wave/arch (2026-07-29). Категории появились в этой таблице потому, что
    # у них НАКОНЕЦ ЕСТЬ ОП: до неё причина атома читалась «операции не
    # существует», и это было правдой. Теперь причина называет недостающий
    # ФАКТ (профиль эскиза у потолка, путь/хозяин/позиция у ограждения) —
    # разница решает, что чинить следующим.
    "OST_Ceilings": _Candidate("ceiling", "create_ceiling", "_lift_ceiling"),
    "OST_StairsRailing": _Candidate(
        "railing", "create_railing", "_lift_railing"),
    "OST_Railings": _Candidate("railing", "create_railing", "_lift_railing"),
    # Панель витража — ЯЧЕЙКА сетки носителя, а не самостоятельный элемент:
    # оп назначает ей тип (дизайн 2026-07-28). До этой волны категории тут
    # не было вовсе, и 734 панели фасадной модели уходили в общий путь
    # размещения, который про ячейки не знает ничего.
    "OST_CurtainWallPanels": _Candidate(
        "curtain_panel", "set_curtain_panel", "_lift_curtain_panel"),
    # wave/shape (2026-07-29). НЕ BuiltInCategory, а псевдокатегория: у
    # DirectShape категория классом не определяется, и коллектор кладёт в поле
    # литерал "DirectShape" (extract.py:1296). Диспетчер об этом различии не
    # знает и знать не должен — он ищет строку.
    "DirectShape": _Candidate(
        "direct_shape", "create_directshape", "_lift_directshape"),
    # wave/room (2026-08-03). Категория читается с 29.07 как КОНТЕКСТ
    # помещений, но опа под неё не было, и все 2 313 элементов K2 уходили в
    # `no_lifter` — «операции не существует». Теперь она есть.
    "OST_RoomSeparationLines": _Candidate(
        "room_separator", "create_room_separator", "_lift_room_separator"),
}

# ДЕСЯТЬ РОДОВ МАРОК — ОДИН оп и ОДИН лифтер (волна марок, 30.07). Список не
# переписывается здесь от руки, а берётся у САМОЙ СТАДИИ ЧТЕНИЯ: категория,
# записанная в одном месте и забытая в другом, — это либо id, которых никто
# не запросит, либо элементы, которым нечем питаться. Ровно этой парностью
# уже поплатились категории потолков и ограждений 29.07.
_CANDIDATES.update({
    category: _Candidate("tag", "create_tag", "_lift_tag")
    for category in sorted(TAG_CATEGORIES)
})

LIFTER_TABLE: Mapping[str, tuple[str, str]] = MappingProxyType({
    category: (candidate.kind, candidate.op)
    for category, candidate in _CANDIDATES.items()
})


def _validate_candidate_contracts() -> None:
    """Make the category dispatch a checked view of the reverse contract.

    A candidate may be a real same-op inverse or an explicitly named capture
    gap.  It may not silently point at a decomposed/history/external op, and a
    direct candidate must name the exact function allowed to emit it.
    """
    for category, candidate in _CANDIDATES.items():
        contract = REVERSE_CONTRACTS[candidate.op]
        if contract.mode not in (
                ReverseMode.DIRECT, ReverseMode.CAPTURE_GAP):
            raise AssertionError(
                f"reverse candidate {category!r} targets {candidate.op!r} "
                f"with incompatible mode {contract.mode.value!r}")
        if (contract.mode is ReverseMode.DIRECT
                and candidate.lifter_name not in contract.entrypoints):
            raise AssertionError(
                f"reverse candidate {category!r} uses undeclared entrypoint "
                f"{candidate.lifter_name!r} for {candidate.op!r}")


_validate_candidate_contracts()


# ─── РОДА, У КОТОРЫХ ОП ЕСТЬ, А ВХОДОВ ЕМУ В ЧТЕНИИ НЕТ (29.07) ────────────
#
# Таблица чтения выросла 54 → 73 категории (ee32fb82), и в неё вошло
# содержание рабочей документации: 13 905 размеров, 2 697 примечаний и десять
# родов марок — 36 241 элемент замеренной башни. Операции под них НАПИСАНЫ и
# лежат в реестре с 28.07 (create_dimension / create_tag / create_text,
# ops_annotation.py). Лифтеров нет, и без этой таблицы каждый такой элемент
# получал `no_lifter` с текстом «category is outside the exact Part 5 lifter
# table».
#
# ЭТО НЕПРАВДА В ЕДИНСТВЕННОМ МЕСТЕ, ГДЕ ОНА ДОРОГА, — в ранжире причин, по
# которому решают, что строить дальше. `no_lifter` читается «операции нет,
# напиши её», и следующий пошёл бы писать create_dimension, который уже
# написан. Настоящая нехватка лежит на СТУПЕНЬ РАНЬШЕ: в замороженной строке
# L0 1.0 нет ПОЛЕЙ под обязательные входы этих опов, и никакой лифтер их
# оттуда не достанет.
#
# ЧТО ИМЕННО ПРОВЕРЕНО (kukai.ir.decompile.schema.L0Element — поля
# перечислены поимённо; extract.py — эмиссия строки):
#   * вида-владельца нет вовсе: ни поля, ни чтения Element.OwnerViewId;
#   * ссылок нет: Dimension.References и IndependentTag не читаются;
#   * координат вида нет: геометрия строки — модельные мм и габарит, а
#     `pt_view2d` живёт в 2D-плоскости конкретного вида;
#   * текста нет: `params` — ЗАКРЫТЫЙ белый список геометрических
#     BuiltInParameter (extract.py:__PutParams), TextNote.Text в нём
#     отсутствует, а `type_name` несёт имя ТИПА примечания, а не его текст.
#
# ПОЧЕМУ НЕ ПОДСТАВИТЬ. Каждый вход этих опов — ССЫЛКА НА ДРУГОЙ ЭЛЕМЕНТ или
# место В КОНКРЕТНОМ ВИДЕ. Размер, привязанный к «какому-нибудь» элементу, и
# марка «примерно там» прошли бы схему L1 и выглядели бы покрытием, а на деле
# были бы выдуманным источником. Лифт не вправе изобретать источники (§18.1),
# и цена такой подстановки — не процент, а доверие к числу.
#
# Таблица НЕ является таблицей лифтеров и намеренно живёт отдельно от
# _CANDIDATES: там категория обещает попытку подъёма, здесь — только верное
# имя отказа.
#
# МАРОК ЗДЕСЬ БОЛЬШЕ НЕТ (волна марок, 30.07), и это не потеря отказа, а его
# ПЕРЕЕЗД. Десять родов марок стоят теперь в ``_CANDIDATES``, и когда индекса
# нет, ``_lift_tag`` отказывает ТЕМ ЖЕ ``source_contract_gap`` с ТЕМ ЖЕ
# текстом, собранным той же ``_unsourceable_inputs_detail("create_tag")`` —
# слепки, снятые до стадии, обязаны дать прежний ответ дословно, иначе
# история покрытия перестанет быть историей. Ровно так же 30.07 переехало
# ``OST_TextNotes``.
# wave/opening (03.08.2026): ПРОЁМ КАК ОТДЕЛЬНЫЙ ЭЛЕМЕНТ — та самая
# единственная МОЛЧАЛИВАЯ потеря, которую нашёл обход восьми зданий. Тонкость
# не в том, что проём не поднимается, а в том, что до этой волны он не давал
# НИ ОДНОГО следа: категории нет ни в одной таблице, элемент не извлекается,
# атома не получается, а НОСИТЕЛЬ при этом поднимается обычным create_floor и
# пересобирается СПЛОШНЫМ. Приёмка L2 такое не ловит по построению (она прямо
# говорит, что геометрию не смотрит вообще), то есть тихо неверный результат
# снаружи неотличим от успеха.
#
# Три рода, которые ВЫРАЖАЕТ `create_opening`, стоят здесь, а не в
# `_CANDIDATES`, и это точная причина, а не осторожность: операция ЕСТЬ, но
# замороженная строка L0 1.0 не несёт ни `Opening.Host`, ни границы проёма
# (`BoundaryRect`/`BoundaryCurves`) — то есть не хватает не опа, а ЧТЕНИЯ.
# `source_contract_gap` посылает ремонт в стадию извлечения,
# `no_lifter` послал бы писать операцию, которая написана. Ровно то различие,
# ради которого этот код и заведён.
#
# `OST_ShaftOpening` здесь НАМЕРЕННО НЕТ: у шахты операции действительно нет
# (см. `ops_opening.VARIETIES_NOT_TAKEN["shaft"]` — связь с парой уровней
# нечем подтвердить с построенного элемента), и `no_lifter` про неё — правда.
# Класть её сюда значило бы обещать операцию, которой нет, — зеркальная ложь.
#
# wave/mep-electrical (09.08.2026): ГИБКИЕ УЧАСТКИ. Обе категории читаются с
# 27.07 (`extract.py`, разделы ОВ и ВК), и до сегодняшнего дня каждый гибкий
# воздуховод и каждая гибкая подводка получали `no_lifter` с текстом
# «category is outside the exact Part 5 lifter table». Утром 09.08 это стало
# НЕПРАВДОЙ: `create_flex_duct` и `create_flex_pipe` лежат в реестре
# (`ops_mep.py`), то есть отказ по-прежнему посылал бы следующего писать
# операцию, которая написана, — ровно тот класс лжи, ради которого этот код
# заведён 29.07 для размеров.
#
# Категории стоят ЗДЕСЬ, а не в `_CANDIDATES`, и это точная причина, а не
# осторожность. Строка L0 несёт ПАРУ КОНЦОВ кривой, а форма гибкого участка
# живёт в `FlexDuct.Points`/`FlexPipe.Points` — сплайне Эрмита через N точек
# (`ops_mep.py`, замер 6/6). Концы её НЕ ЗАДАЮТ: любая ломаная с теми же
# концами дала бы ту же строку. Поднять такой элемент прямым участком между
# концами значило бы ВЫДУМАТЬ геометрию и показать её покрытием — та же
# подмена, что хорда вместо дуги (`CURVE_KIND_UNSUPPORTED`), и по той же
# причине запрещённая. Поэтому и в манифесте (`reverse_contract.py`) у обеих
# операций мода `capture_gap` БЕЗ `representation_ops`.
#
# РАЗРЫВ ЗДЕСЬ ЧАСТИЧНЫЙ, И ЭТО ПЕРВЫЙ ТАКОЙ СЛУЧАЙ В ТАБЛИЦЕ: `level` строка
# L0 несёт, `path` — нет. Прежняя формулировка отказа («не несёт НИ ОДНОГО из
# обязательных входов») на них соврала бы, поэтому текст собирается теперь по
# двум таблицам — см. `_L0_ALREADY_CARRIES` ниже.
_OPS_WITHOUT_L0_INPUTS: Mapping[str, str] = MappingProxyType({
    "OST_SWallRectOpening": "create_opening",
    "OST_FloorOpening": "create_opening",
    "OST_RoofOpening": "create_opening",
    "OST_FlexDuctCurves": "create_flex_duct",
    "OST_FlexPipeCurves": "create_flex_pipe",
})

#: Обязательный вход опа → тот член Revit API, который пришлось бы НАЧАТЬ
#: СНИМАТЬ, чтобы вход появился. Это спецификация следующей волны чтения,
#: записанная там, где её найдут, — в самом отказе. Полнота карты относительно
#: реестра проверяется тестом: если оп обзаведётся новым обязательным входом,
#: а строки здесь не будет, тест упадёт, и отказ не начнёт молча врать.
#:
#: ИМЕНА СВЕРЕНЫ ПО ИНДЕКСУ ЛОВУШЕК (api_trap_index.py), А НЕ ПО ПАМЯТИ, и
#: одна проверка сразу окупилась. У МАРКИ нет НИ ОДНОГО члена, живущего во
#: всех шести версиях, — поверхность рвётся ровно на 2022:
#:
#:   P:IndependentTag.TaggedLocalElementId      2021-2022, УДАЛЁН после 2022
#:   M:IndependentTag.GetTaggedLocalElement     2021-2022, УДАЛЁН после 2022
#:   M:IndependentTag.GetTaggedLocalElementIds  2022-2026, НЕТ в 2021
#:
#: То есть 2022 — единственный год, где есть оба, а любая волна, снимающая
#: цель марки одним именем, не соберётся либо на 2021, либо на 2023+. Здесь
#: названы ОБА, чтобы следующий увидел шов раньше, чем компилятор.
#:
#: Остальные три проверены и живут во ВСЕХ версиях: Element.OwnerViewId,
#: Dimension.References, TextElement.Text (TextNote наследует её; члена
#: «TextNote.Text» в документации нет вовсе — объявлен он у TextElement).
#:
#: 30.07: строки ``in_view``/``target``/``at`` перестали быть спецификацией
#: БУДУЩЕЙ волны — стадия ``tag`` их снимает (``tag_extract``). Карта остаётся
#: на месте и по-прежнему собирает текст отказа, потому что отказ остаётся
#: верным ровно тогда, когда стадии не было: слепок без индекса обязан дать
#: тот же атом с той же причиной, что и до волны.
_L0_HAS_NO_SOURCE_FOR: Mapping[str, str] = MappingProxyType({
    "in_view": "Element.OwnerViewId",
    "refs": "Dimension.References",
    "target": ("IndependentTag.TaggedLocalElementId (2021-2022) / "
               ".GetTaggedLocalElementIds (2022+) — шов версий"),
    # Не член API, а ВЫВОД: и TagHeadPosition, и TextElement.Coord дают
    # МОДЕЛЬНЫЙ XYZ, а `pt_view2d` — координата в плоскости конкретного вида.
    # Перевод требует базиса вида, то есть самого вида, которого тоже нет.
    "at": "точка в координатах вида (нужен базис вида, не только XYZ)",
    "line_at": "точка в координатах вида (нужен базис вида, не только XYZ)",
    "content": "TextElement.Text",
    # wave/opening (03.08.2026). Род проёма — ЕДИНСТВЕННЫЙ обязательный вход
    # `create_opening`, и он не «одно поле», а решение, которое принимается по
    # ТРЁМ членам сразу: `Opening.Host` (стена -> wall_rect, перекрытие/
    # кровля/потолок -> host_face, пусто -> шахта), `IsRectBoundary` и сама
    # граница. Ни одного из них замороженная строка L0 1.0 не читает, поэтому
    # отказ называет их поимённо — он спецификация следующей волны чтения, а
    # не жалоба. Имена сверены по индексу ловушек: Host/IsRectBoundary/
    # BoundaryRect/BoundaryCurves живут 6/6, а `Opening.SketchId` — 2022-2026,
    # то есть эскиз проёма на 2021 прочесть нечем вовсе, и это шов, о который
    # следующий обязан не споткнуться.
    "variety": ("Opening.Host + Opening.IsRectBoundary + "
                "Opening.BoundaryRect/BoundaryCurves (все 6/6; "
                "Opening.SketchId только 2022-2026)"),
    # wave/mep-electrical (09.08.2026). Путь гибкого участка. Член живёт во
    # ВСЕХ шести версиях (`FlexDuct.Points`/`FlexPipe.Points`, IList<XYZ> —
    # замер компиляцией, шапка ops_mep.py), то есть это не «нельзя прочесть»,
    # а «не читаем»: строка отказа и есть спецификация одной строки захвата.
    # Названо ОДНОЙ записью на оба опа намеренно — параметр у них общий, и
    # два текста про одно поле развели бы одну дыру на две строки ранжира.
    "path": ("FlexDuct.Points / FlexPipe.Points (IList<XYZ>, 6/6) — сплайн "
             "Эрмита через N точек; пара концов кривой его НЕ задаёт"),
})

#: Обязательные входы, которые замороженная строка L0 1.0 УЖЕ НЕСЁТ, и ПОЛЕ,
#: которое их несёт. Таблица заведена 09.08 вместе с гибкими участками, и
#: работы у неё ровно две.
#:
#: ПЕРВАЯ — не дать отказу соврать. До гибких разрыв захвата умел быть только
#: ПОЛНЫМ: у размера, марки, примечания и проёма в L0 нет НИ ОДНОГО
#: обязательного входа, и текст так и говорил — «НИ ОДНОГО». У
#: `create_flex_duct` входов два, и `level` строка несёт (`level_id`/
#: `level_name`; ровно оттуда его берут лифтеры трубы, воздуховода, лотка и
#: короба). Оставить прежнюю формулировку значило бы соврать в том самом
#: утверждении, ради точности которого этот отказ и заведён.
#:
#: ВТОРАЯ — не дать разрыву стать МОЛЧАЛИВЫМ. Отказ называет только
#: недостающие входы; без положительного объявления новый обязательный вход,
#: которого нет ни в одной из двух таблиц, просто исчез бы из текста, и отказ
#: перестал бы быть спецификацией следующей волны чтения. Поэтому тест
#: требует, чтобы каждый обязательный вход стоял РОВНО В ОДНОЙ из них.
_L0_ALREADY_CARRIES: Mapping[str, str] = MappingProxyType({
    "level": "L0Element.level_id / level_name",
})


def _unsourceable_inputs_detail(op_name: str) -> str:
    """Отказ, СОБРАННЫЙ ИЗ РЕЕСТРА, а не переписанный от руки.

    Список обязательных входов берётся у самого опа, поэтому текст отказа не
    может разойтись со спецификацией: изменится оп — изменится и отказ.

    Разрыв бывает ПОЛНЫМ и ЧАСТИЧНЫМ, и текст обязан их различать. При полном
    (размер, марка, примечание, проём) формулировка ДОСЛОВНО прежняя — слепки,
    разобранные до 09.08, обязаны читаться той же таксономией и тем же
    текстом, иначе история покрытия перестаёт быть историей.
    """

    required = tuple(
        param.name for param in spec.OPS[op_name].params if param.required)
    missing = tuple(
        name for name in required if name not in _L0_ALREADY_CARRIES)
    named = "; ".join(
        f"{name} <- {_L0_HAS_NO_SOURCE_FOR.get(name, 'источник не назван')}"
        for name in missing)
    if len(missing) == len(required):
        scope = "НИ ОДНОГО из его обязательных входов"
    else:
        carried = ", ".join(
            f"{name} <- {_L0_ALREADY_CARRIES[name]}"
            for name in required if name in _L0_ALREADY_CARRIES)
        scope = (
            f"{len(missing)} из {len(required)} его обязательных входов "
            f"(несёт только: {carried})")
    return (
        f"{op_name} есть в реестре операций, но L0 1.0 не несёт {scope}, "
        f"и подставить их нечем: {named}")


#: Категории, которые поднимаются ВТОРЫМ проходом: их оп ссылается на хост,
#: и ссылка обязана не зависеть от порядка элементов в L0. Панель витража
#: ссылается на носителя ячейки ровно так же, как дверь на стену.
_HOSTED_CATEGORIES = frozenset(
    ("OST_Doors", "OST_Windows", "OST_CurtainWallPanels"))

#: Категории, которые ПЕРВЫЙ проход пропускает: их ссылка разрешается по уже
#: поднятым узлам. Носители — вторым проходом, марки — третьим (марка может
#: ссылаться на дверь, то есть на результат второго). Множество собирается из
#: двух источников, а не переписывается: разъехавшись, оно оставило бы
#: элемент без узла, и общий страж в конце превратил бы его в internal_error.
#: Оформление, которое ССЫЛАЕТСЯ на другие элементы: марка на свой
#: помеченный элемент, размер — на измеряемые. Обе категории обязаны
#: подниматься ПОСЛЕ всего, на что они способны сослаться (см. третий проход
#: в ``_lift_document``), иначе их отказ зависел бы от порядка элементов в
#: L0, а не от модели.
_REFERENCING_ANNOTATION_CATEGORIES = TAG_CATEGORIES | DIMENSION_CATEGORIES

_DEFERRED_CATEGORIES = (
    _HOSTED_CATEGORIES | _REFERENCING_ANNOTATION_CATEGORIES)


@dataclass(frozen=True, slots=True)
class _Context:
    revit_version: str | None
    elements_by_id: Mapping[str, L0Element]
    levels_by_id: Mapping[str, LevelInfo]
    grids_by_id: Mapping[str, GridInfo]
    rooms_by_id: Mapping[str, RoomInfo]
    profile_index: Mapping[str, Any]
    stairs_run_path_index: Mapping[str, Any]
    family_placement_index: Mapping[str, Any]
    family_placement_requested: bool
    wall_curve_index: Mapping[str, Any]
    # §18.2/M5: квитанции бокового индекса размещений, ключом по element_id.
    # Пустой словарь = квитанций нет (старый разбор или стадия без срезов) —
    # ровно прежнее поведение.
    family_placement_failures: Mapping[str, Any] = field(default_factory=dict)
    #: Захват ограждений стадией ``sketch`` (путь, хозяин, базовый уровень) —
    #: тот же боковой индекс, что несёт профили и пути маршей. Пустое
    #: отображение = стадии в этом слепке НЕ БЫЛО, и ограждение обязано дать
    #: ПРЕЖНИЙ отказ дословно: «слепок, снятый до стадии, обязан дать прежний
    #: ответ». Поле с умолчанием, а не обязательное, ровно поэтому.
    railing_path_index: Mapping[str, Any] = field(default_factory=dict)
    # Ячейки витражей, ключом по id ЭЛЕМЕНТА ЯЧЕЙКИ: (id носителя, строка
    # носителя, строка панели). Пустой словарь = стадия не отдала индекс (или
    # отдала схемой /1 без адресов) — панели тогда идут прежним путём и
    # остаются честными атомами.
    curtain_cells: Mapping[str, tuple[str, Any, Any]] = field(
        default_factory=dict)
    # Тела ячеек: id элемента-тела -> id ячейки, которая его породила.
    # Стена, заполнившая ячейку витража, существует ПОТОМУ ЧТО ячейке назначен
    # тип; отдельного опа на неё быть не должно — иначе пересборка построит
    # её дважды.
    curtain_cell_bodies: Mapping[str, str] = field(default_factory=dict)
    # Импосты витражей: id импоста -> (id носителя, запись носителя, запись
    # импоста). Импост живёт НА ЛИНИИ РАЗРЕЗКИ и создаётся единственным
    # способом — CurtainGridLine.AddMullions(segment, MullionType,
    # oneSegmentOnly) (RevitAPI.xml эталонного пакета). Экземпляром семейства
    # он не ставится ни при каких обстоятельствах, хотя классом и является
    # FamilyInstance. Записи носителя и импоста нужны целиком: по ним
    # решается, ПОРОЖДАЕТ ли импост сам тип носителя.
    curtain_mullions: Mapping[str, tuple[str, Any, Any]] = field(
        default_factory=dict)
    # ЛИНИИ РАЗРЕЗКИ: id линии -> (id носителя, запись носителя, запись
    # линии, направление). Линии НЕТ В L0 ВООБЩЕ — коллектор её категорию не
    # собирает (замер v13: 122 линии в индексе, 0 из них среди 3153
    # элементов L0). Поэтому её операция не «поднимается с элемента», а
    # СИНТЕЗИРУЕТСЯ из бокового индекса и привязывается к узлу носителя.
    curtain_grid_lines: Mapping[str, tuple[str, Any, Any, str]] = field(
        default_factory=dict)
    # Оформление: id элемента -> запись бокового индекса (вид-владелец,
    # точка В КООРДИНАТАХ ВИДА, текст). Пустой словарь = стадии не было,
    # и это ОТЛИЧАЕТСЯ от «стадия прошла и ничего не нашла»: в первом случае
    # честный ответ — прежний source_contract_gap.
    text_notes: Mapping[str, Any] = field(default_factory=dict)
    # МАРКИ: id элемента -> запись бокового индекса (вид-владелец, точка
    # головы В КООРДИНАТАХ ВИДА, ПОМЕЧЕННЫЙ элемент, выноска, род, тип).
    # Пустой словарь = стадии не было, и это ОТЛИЧАЕТСЯ от «стадия прошла и
    # ничего не нашла»: в первом случае честный ответ — прежний
    # source_contract_gap, дословно тот же, что до волны.
    tags: Mapping[str, Any] = field(default_factory=dict)
    # Принадлежность трубы/воздуховода СИСТЕМНОМУ ТИПУ. Пустой словарь =
    # стадии не было: оп поднимается без system_type, как до волны, и
    # пересборка честно откажется заземляться при нескольких вариантах.
    dimensions: Mapping[str, Any] = field(default_factory=dict)
    mep_systems: Mapping[str, Any] = field(default_factory=dict)


class _CannotLift(Exception):
    def __init__(self, reason: AtomReason, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _refuse(reason: AtomReason, detail: str) -> None:
    raise _CannotLift(reason, detail)


def _vec_list(value: Sequence[float] | None) -> list[float] | None:
    return None if value is None else [float(component) for component in value]


def _midpoint(p0: Vec3, p1: Vec3) -> Vec3:
    # Halving before addition cannot overflow when both frozen-L0 components
    # are finite (unlike ``(a + b) / 2`` near the float limit).
    return cast(Vec3, tuple(
        a / 2.0 + b / 2.0 for a, b in zip(p0, p1)))


def _element_anchor(element: L0Element) -> Vec3 | None:
    if (element.geom_kind is GeometryKind.CURVE
            and element.p0_mm is not None and element.p1_mm is not None):
        return _midpoint(element.p0_mm, element.p1_mm)
    if element.geom_kind is GeometryKind.POINT and element.p0_mm is not None:
        return element.p0_mm
    if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
        return _midpoint(element.bbox_min_mm, element.bbox_max_mm)
    return None


def _atom_node(
    element: L0Element,
    reason: AtomReason,
    detail: str,
) -> L1AtomNode:
    return {
        "kind": "atom",
        "_id": stable_l1_id("atom", element.element_id),
        "category": element.category,
        "category_ru": element.category_ru,
        "type_name": element.type_name,
        "bbox_min_mm": _vec_list(element.bbox_min_mm),
        "bbox_max_mm": _vec_list(element.bbox_max_mm),
        "source_element_id": element.element_id,
        "level_name": element.level_name,
        "anchor_mm": _vec_list(_element_anchor(element)),
        "reason": {"code": reason.value, "detail": detail},
    }


def _op_node(
    element: L0Element,
    op: str,
    params: dict[str, Any],
    *,
    level_name: str | None = None,
    anchor: Vec3 | None = None,
) -> L1OpNode:
    # This is the single ordinary L1 op constructor.  The exhaustive forward
    # <-> reverse manifest is therefore an executable boundary: adding a
    # lifter branch cannot expand the reverse language by accident.
    assert_lift_emission(op)
    return {
        "kind": "op",
        "op_name": op,
        "_id": stable_l1_id("op", element.element_id),
        "type_name": element.type_name,
        "params": params,
        "source_element_id": element.element_id,
        "level_name": (
            element.level_name if level_name is None else level_name),
        "anchor_mm": _vec_list(
            _element_anchor(element) if anchor is None else anchor),
    }


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _distance(p0: Sequence[float], p1: Sequence[float]) -> float:
    return math.dist(
        tuple(float(value) for value in p0),
        tuple(float(value) for value in p1),
    )


def _curve(
    element: L0Element,
    *,
    dimensions: int,
) -> tuple[list[float], list[float]]:
    if (element.geom_kind is not GeometryKind.CURVE
            or element.p0_mm is None or element.p1_mm is None):
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            f"{element.category} requires curve geometry")
    p0 = [float(value) for value in element.p0_mm[:dimensions]]
    p1 = [float(value) for value in element.p1_mm[:dimensions]]
    if _distance(p0, p1) < 1.0:
        _refuse(
            AtomReason.INVALID_VALUE,
            f"{element.category} curve is shorter than the forward 1 mm limit")
    return p0, p1


def _side_index_curve_kind(
    element: L0Element,
    context: _Context,
) -> str | None:
    """Вид кривой по БОКОВОМУ индексу, если строка про этот элемент там есть.

    Индекс собирается стадией ``curve`` для стен И каркаса (``pipeline.
    _STAGE_CATEGORIES``), то есть за строку про балку уже заплачен round-trip
    в мост. До этой волны её читали только стены, и дуговая балка спрямлялась
    хордой при том, что точная дуга лежала в ``curve.index.json`` рядом.
    """
    entry = context.wall_curve_index.get(element.element_id)
    if not isinstance(entry, Mapping):
        return None
    kind = entry.get("curve_kind")
    return kind if isinstance(kind, str) else None


def _refuse_non_line_curve(
    element: L0Element,
    context: _Context,
    op_name: str,
) -> None:
    """§18.1: не-Line без выразимой дуги — атом, НИКОГДА не хорда.

    Оп, у которого в реестре нет дугового параметра (``create_beam``,
    ``create_pipe``, ``create_duct``, ``create_cable_tray`` — проверено по
    ``spec.OPS``), не может выразить дугу ВООБЩЕ. Поэтому наличие точной дуги
    в боковом индексе исхода не меняет — меняется только текст причины: одно
    дело «мы не знаем, что там за кривая», другое — «мы знаем её точно, и
    сказать её нечем». Второе — заявка на расширение опа, первое — на
    расширение чтения; смешивать их значит потерять обе.

    Два источника факта нужны оба: ``curve_kind`` в L0 (новый захват) и
    строка бокового индекса (она есть у каркаса и на СТАРОМ L0, где поля нет).
    """
    l0_kind = element.curve_kind
    side_kind = _side_index_curve_kind(element, context)
    exact_arc = side_kind == "arc"
    non_line = (
        (l0_kind is not None and l0_kind is not LocationCurveKind.LINE)
        or (side_kind is not None and side_kind != "line")
    )
    if not non_line:
        return
    named = (
        l0_kind.value if l0_kind is not None and
        l0_kind is not LocationCurveKind.LINE else (side_kind or "non-line"))
    if exact_arc:
        detail = (
            f"exact arc is known for this element, but {op_name} has no arc "
            "parameter — a chord would silently straighten it")
    else:
        detail = (
            f"LocationCurve is {named!r} and {op_name} can only express a "
            "straight segment — a chord would silently straighten it")
    _refuse(AtomReason.CURVE_KIND_UNSUPPORTED, detail)


def _placement_unavailable(element: L0Element, context: _Context) -> bool:
    """The side index saw this instance and found no placement point.

    ``placement_available: false`` is the extractor stating a fact about the
    element, not admitting a failure of its own -- it is how a curtain-panel
    door looks.  Distinguishing the two matters: one is a gap in what the ops
    can say, the other would be a bug worth chasing.
    """
    # The ELEMENT's own geometry is the authority. A side-index row may carry
    # no point while L0 holds a perfectly good one -- it is there for flips —
    # so asking the index alone would condemn doors that lift fine today.
    if element.geom_kind is GeometryKind.POINT and element.p0_mm is not None:
        return False
    index = getattr(context, "family_placement_index", None) or {}
    row = index.get(element.element_id) if isinstance(index, Mapping) else None
    if not isinstance(row, Mapping):
        return False
    return row.get("placement_available") is False and row.get("point_mm") is None


def _point(element: L0Element) -> Vec3:
    if (element.geom_kind is not GeometryKind.POINT
            or element.p0_mm is None):
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            f"{element.category} requires point geometry")
    return element.p0_mm


def _level_ref(
    level_id: str | None,
    level_name: str | None,
) -> dict[str, str]:
    if not level_id or not level_name:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "a named level id and name are both required")
    return {"by": "name", "value": level_name, "_id": level_id}


def _catalog_ref(element: L0Element) -> dict[str, str]:
    if not element.type_name or not element.type_id:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "catalog type id and name are both required")
    return {
        "by": "name",
        "value": element.type_name,
        "_id": element.type_id,
    }


def _family_symbol_ref(
    element: L0Element,
    record: FamilyPlacementRecord,
) -> dict[str, str]:
    """Build the non-ambiguous category+family+type selector dialect."""

    if not element.category:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "family symbol selector requires a source category")
    if element.type_id and element.type_id != record.symbol_id:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "family placement symbol_id disagrees with frozen L0 type_id")
    if element.type_name and element.type_name != record.type_name:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "family placement type_name disagrees with frozen L0 type_name")
    return {
        "by": "family_type",
        "category": element.category,
        "family_name": record.family_name,
        "type_name": record.type_name,
        "_id": record.symbol_id,
    }


def _survives_canon_rounding(value: float) -> bool:
    """codex #8 (2026-07-29, tasks/b8f3v4r97.output сессии eeccfb91): the
    ONLY law for whether an optional _mm param is worth carrying at all —
    not an independent threshold, the SAME grid FidelityCanon's own
    _round_mm rounds every _mm-suffixed field on (CANON_MM=1мм, canon /3,
    fidelity-canon/3's absent=0.0 default already covers the case this
    returns False for). A value that flattens to 0 on that grid costs
    nothing to drop — absent and explicit-0 are canon-identical; anything
    that survives is a genuinely different canonical value and MUST reach
    params, however small (0.6мм rounds to 1.0мм — a real, distinct value
    a >=1мм-only gate silently discarded, live bug measured on v13 floors)."""
    return round(value / CANON_MM) != 0


def _bounded_param(
    element: L0Element,
    source_name: str,
    op_name: str,
    param_name: str,
) -> float:
    value = _finite(element.params.get(source_name))
    if value is None:
        _refuse(
            AtomReason.MISSING_PARAMETER,
            f"{source_name} is absent or not a finite number")
    param = next(
        (item for item in spec.OPS[op_name].params
         if item.name == param_name),
        None,
    )
    if param is None:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"{op_name} has no {param_name} parameter")
    if param.min_val is not None and value < param.min_val:
        _refuse(
            AtomReason.INVALID_VALUE,
            f"{source_name} is below {op_name}.{param_name}'s lower bound")
    if param.max_val is not None and value > param.max_val:
        _refuse(
            AtomReason.INVALID_VALUE,
            f"{source_name} is above {op_name}.{param_name}'s upper bound")
    return value


def _matching_level(
    context: _Context,
    level_id: str | None,
    level_name: str | None,
) -> LevelInfo:
    if not level_id or not level_name:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "level id/name is required")
    level = context.levels_by_id.get(level_id)
    if level is None or level.name != level_name:
        _refuse(
            AtomReason.MISSING_METADATA,
            "level metadata is absent or disagrees with the element")
    return level


def _side_indexes(
    profile_index: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    """Split the three exact Sketch side indexes without changing frozen L0.

    ``ProfileExtraction.profile_index`` is accepted directly for closed
    floor/roof profiles.  Stairs paths live in the extractor's sibling
    ``stairs_run_path_index``; callers may therefore pass either that index
    directly or the persisted ``ProfileExtraction.to_dict()`` envelope.

    ``railing_path_index`` — третий сосед, и он НЕОБЯЗАТЕЛЬНЫЙ по построению:
    ``ProfileExtraction.to_dict`` кладёт ключ только когда ограждения
    действительно захвачены. Слепок, снятый до волны захвата 29.07, ключа не
    имеет — и обязан дать ПРЕЖНИЙ отказ ограждения дословно, а не новый.
    Именно поэтому здесь возвращается пустое отображение, а не ``profile_index``
    целиком: в прямой (не-конвертной) форме диалекты записей различить нечем,
    и подсунуть лифту ограждения чужие строки значило бы выдумать путь.
    """

    if not isinstance(profile_index, Mapping):
        return {}, {}, {}
    nested_profiles = profile_index.get("profile_index")
    nested_stairs = profile_index.get("stairs_run_path_index")
    nested_railings = profile_index.get("railing_path_index")
    if ("profile_index" in profile_index
            or "stairs_run_path_index" in profile_index
            or "railing_path_index" in profile_index):
        return (
            nested_profiles if isinstance(nested_profiles, Mapping) else {},
            nested_stairs if isinstance(nested_stairs, Mapping) else {},
            nested_railings if isinstance(nested_railings, Mapping) else {},
        )
    # A direct closed-profile index and a direct stairs-run-path index share
    # the same element-id outer key shape.  Each lifter strictly parses only
    # its own record dialect, so exposing the mapping to both is fail-closed.
    return profile_index, profile_index, {}


def _curtain_side_index(
    curtain_index: Any,
) -> tuple[dict[str, tuple[str, CurtainWallRecord, PanelRecord]],
           dict[str, str],
           dict[str, tuple[str, CurtainWallRecord, MullionRecord]],
           dict[str, tuple[str, CurtainWallRecord, GridLineRecord, str]]]:
    """Разобрать индекс витражей: ячейки, тела, импосты и линии разрезки.

    Принимается и полный конверт (``{schema_version, curtain_index,
    failures}``), и голый словарь ``{host_id: record}``, и уже разобранный
    :class:`CurtainExtraction` — ровно как у прочих боковых индексов, чтобы
    инструменты и конвейер могли передавать то, что у них на руках.

    Битая строка ИЗОЛИРУЕТСЯ: индекс — внешние данные, и одна нечитаемая
    запись не имеет права уронить разбор здания. Панели такого носителя
    просто не получат ячейки и станут честными атомами.
    """

    if curtain_index is None:
        return {}, {}, {}, {}
    records: list[CurtainWallRecord]
    if hasattr(curtain_index, "records"):
        records = list(getattr(curtain_index, "records") or ())
    else:
        if not isinstance(curtain_index, Mapping):
            return {}, {}, {}, {}
        raw = curtain_index.get("curtain_index", curtain_index)
        if not isinstance(raw, Mapping):
            return {}, {}, {}, {}
        records = []
        for host_id, row in raw.items():
            if not isinstance(host_id, str):
                continue
            try:
                records.append(CurtainWallRecord.from_dict(
                    host_id, row, f"curtain_index[{host_id!r}]"))
            except CurtainPayloadError:
                continue
    # codex #4 (2026-07-29, tasks/b8f3v4r97.output сессии eeccfb91):
    # ``CurtainWallRecord.__post_init__`` уже требует panel_id/mullion_id
    # уникальными ВНУТРИ одного носителя (``_require_unique``) — но
    # panel_id и host_panel_id живут в ОБЩЕМ, ГЛОБАЛЬНОМ пространстве
    # идентичности документа, и глобальная сторона инъективности не
    # проверялась вовсе. Прежде чем строить cells/bodies, найти все
    # носители, чьи данные конфликтуют глобально, и изолировать их ЦЕЛИКОМ
    # (не одну ячейку — сам факт коллизии бросает тень на весь снятый
    # носитель), а не позволить last-write молча подменить или потерять
    # чужую легитимную ячейку.
    panels_by_id: dict[str, list[tuple[str, PanelRecord]]] = {}
    host_panel_by_id: dict[str, list[tuple[str, PanelRecord]]] = {}
    all_wall_ids = {record.wall_id for record in records}
    for record in records:
        if not record.curtain_available:
            continue
        for panel in record.panels:
            panels_by_id.setdefault(panel.panel_id, []).append(
                (record.wall_id, panel))
            if panel.host_panel_id:
                host_panel_by_id.setdefault(panel.host_panel_id, []).append(
                    (record.wall_id, panel))

    conflicted_walls: set[str] = set()
    for panel_id, occurrences in panels_by_id.items():
        if len(occurrences) > 1:
            # Глобальный дубль panel_id — два РАЗНЫХ носителя (или два
            # прохода одного набора данных) заявляют одну и ту же ячейку.
            conflicted_walls.update(wall_id for wall_id, _ in occurrences)
    for host_panel_id, occurrences in host_panel_by_id.items():
        if len(occurrences) > 1:
            # Дубль тела: несколько ячеек претендуют на ОДНОГО занявшего —
            # "duplicate body" из адверсариального замера.
            conflicted_walls.update(wall_id for wall_id, _ in occurrences)
        for wall_id, panel in occurrences:
            if host_panel_id == panel.panel_id:
                # Самоссылка: ячейка занята "сама собой" — не имеет
                # физического смысла, а не просто редкий случай.
                conflicted_walls.add(wall_id)
            elif host_panel_id in panels_by_id:
                # Пересечение ролей: тело этой ячейки — РЕАЛЬНЫЙ panel_id
                # ЧУЖОЙ ячейки ("body=foreign panel"). Опасность не в самом
                # псевдониме (setdefault ниже не даст ему переписать чужую
                # запись) — она в том, что `_lift_one` проверяет
                # `curtain_cell_bodies` РАНЬШЕ, чем `curtain_cells`: чужая
                # легитимная ячейка стала бы недостижимой телом, которое ею
                # не является. Изолировать ОБЕ стороны.
                conflicted_walls.add(wall_id)
                conflicted_walls.update(
                    other_wall for other_wall, _ in panels_by_id[host_panel_id])
            elif host_panel_id in all_wall_ids:
                # Вложенный curtain-host: занявший — сам носитель витража.
                # Неопределённая территория (codex #4) — не алиасить.
                conflicted_walls.add(wall_id)

    cells: dict[str, tuple[str, CurtainWallRecord, PanelRecord]] = {}
    bodies: dict[str, str] = {}
    mullions: dict[str, tuple[str, CurtainWallRecord, MullionRecord]] = {}
    grid_lines: dict[
        str, tuple[str, CurtainWallRecord, GridLineRecord, str]] = {}
    for record in records:
        if not record.curtain_available:
            continue
        isolated = record.wall_id in conflicted_walls
        for panel in record.panels:
            if isolated:
                # Изолированный носитель не участвует в cells/bodies вовсе —
                # его элементы падают в общий путь размещения и получают
                # честный (не curtain-специфичный) атом/оп, а не тихо
                # неверную generator_child-подмену. Мультимножество
                # source-id не теряет их: они просто не идут по короткому
                # пути.
                continue
            cells[panel.panel_id] = (record.wall_id, record, panel)
            if panel.host_panel_id:
                bodies[panel.host_panel_id] = panel.panel_id
        for mullion in record.mullions:
            mullions[mullion.mullion_id] = (record.wall_id, record, mullion)
        for line in record.u_grid_lines:
            grid_lines[line.line_id] = (record.wall_id, record, line, "u")
        for line in record.v_grid_lines:
            grid_lines[line.line_id] = (record.wall_id, record, line, "v")
    # У ЗАНЯТОЙ ЯЧЕЙКИ ДВА ИМЕНИ, И ДОКУМЕНТ ВПРАВЕ ЗНАТЬ ЛЮБОЕ ИЗ НИХ.
    #
    # Индекс ключует ячейку по id ЗАНЯВШЕГО (panel_id), а переизвлечение
    # пересобранной модели отдаёт id ЗАНЯТОЙ панели (host_panel_id) —
    # замер v12 (idempotence_debug.json): из 20 переизвлечённых панелей
    # 0 совпали с panel_id и 20 — с host_panel_id. Ключи не пересекались,
    # ре-лифт получал None и уходил в общий путь размещения: 0 листьев
    # ячеек там, где их ждали 20.
    #
    # Второе имя добавляется ПОСЛЕ всех первых (setdefault), чтобы псевдоним
    # одной ячейки никогда не перебил собственный ключ другой. Двух листьев
    # из двух имён не будет: пока в документе есть ЗАНЯВШИЙ, занятая панель
    # перехватывается охранником тела и остаётся generator_child — тем же,
    # чем была; псевдоним срабатывает ровно тогда, когда занявшего в
    # документе нет (замер того же v12: в исходной модели обе стороны есть
    # у всех 372 занятых ячеек, и лист обязан остаться один).
    #
    # Глобальная инъективность уже доказана выше (конфликтующие носители
    # изолированы и никогда не попадают в bodies/cells), так что
    # setdefault здесь охраняет только оставшийся, честный случай — оно
    # больше не единственная линия обороны.
    for body_id, cell_id in bodies.items():
        cell = cells.get(cell_id)
        if cell is not None:
            cells.setdefault(body_id, cell)
    return cells, bodies, mullions, grid_lines


#: Почему линия разрезки НЕ стала операцией. Причина обязана называть себя:
#: «её ставит тип» и «мы не смотрели» — разные утверждения, и только первое
#: что-то говорит о модели.
_GRID_LINE_SKIP_DETAIL: dict[GridLineState, str] = {
    GridLineState.TYPE_DRIVEN: (
        "тип носителя делит сетку сам (SPACING_LAYOUT_* != 0) — какая линия "
        "его, а какая авторская, по числам не различить; операция удвоила бы "
        "линию, а удвоенная хуже отсутствующей"),
    GridLineState.UNREADABLE: (
        "раскладка типа носителя не прочитана — поставить линию значило бы "
        "гадать, воспроизводит ли её тип сам"),
    GridLineState.NOT_CAPTURED: (
        "индекс снят схемой, которая раскладки типа не читала (до "
        "kir-decompile-curtain-index/5) — нужно свежее извлечение"),
}


def _element_id_sort_key(element_id: str) -> tuple[int, int, str]:
    """Устойчивый порядок id: числовые — по числу, прочие — по строке.

    Порядок узлов обязан быть детерминированным: от него зависит и
    канонический хеш последовательности, и порядок операций в программе.
    """

    return ((0, int(element_id), "") if element_id.isdigit()
            else (1, 0, element_id))


def _grid_line_node(
    line_id: str,
    host_id: str,
    host: CurtainWallRecord,
    line: GridLineRecord,
    direction: str,
    host_node: L1Node | None,
) -> tuple[L1OpNode | None, LiftDiagnostic | None]:
    """Линия разрезки -> ``create_curtain_grid_line``, либо честный пропуск.

    ЛИНИИ НЕТ В L0: её категорию коллектор не собирает вовсе (замер v13 —
    122 линии в индексе, ни одной среди 3153 элементов L0). Поэтому узел
    СИНТЕЗИРУЕТСЯ из бокового индекса, а не поднимается с элемента; его
    ``source_element_id`` — настоящий id линии в модели, поэтому обе дороги
    (синтез в исходной модели и подъём того же id, если переизвлечение всё
    же отдаст его элементом) дают ОДИН И ТОТ ЖЕ узел и один канонический
    хеш. Тот же урок, что у ячейки с двумя именами.

    Пропуск — не молчание: у каждого исхода своя названная причина, и она
    уходит в диагностический канал.
    """

    state = host.grid_line_state(line)
    if state is not GridLineState.MANUAL:
        return None, LiftDiagnostic(
            source_element_id=line_id,
            category="OST_CurtainGrids",
            reason=AtomReason.GENERATOR_CHILD
            if state is GridLineState.TYPE_DRIVEN
            else AtomReason.MISSING_METADATA,
            detail=_GRID_LINE_SKIP_DETAIL[state])
    if host_node is None or host_node.get("kind") != "op":
        return None, LiftDiagnostic(
            source_element_id=line_id,
            category="OST_CurtainGrids",
            reason=AtomReason.MISSING_REFERENCE,
            detail=(f"носитель линии разрезки не поднят (host_id={host_id!r}) "
                    "— ставить линию не на что"))
    # ПОЗИЦИЯ — точка НА линии: AddGridLine принимает именно точку, через
    # которую линия проходит. Середина захваченной кривой лежит на ней по
    # построению, поэтому пересборка ставит линию туда же, откуда её сняли.
    if line.curve_state is not CurveState.LINE \
            or line.p0_mm is None or line.p1_mm is None:
        return None, LiftDiagnostic(
            source_element_id=line_id,
            category="OST_CurtainGrids",
            reason=AtomReason.CURVE_KIND_UNSUPPORTED,
            detail=("кривая линии разрезки не прямая либо не прочитана "
                    f"({line.curve_state.value}) — точки, через которую её "
                    "ставить, нет"))
    position = [
        round((float(a) + float(b)) / 2.0, 6)
        for a, b in zip(line.p0_mm, line.p1_mm)
    ]
    # Grid lines are synthesized from a side index and intentionally bypass
    # _op_node (there is no L0Element).  Keep that second and only emission
    # site under the same manifest guard.
    assert_lift_emission("create_curtain_grid_line")
    node = {
        "kind": "op",
        "op_name": "create_curtain_grid_line",
        "_id": stable_l1_id("op", line_id),
        # У линии разрезки нет типа — и пустая строка здесь говорит именно
        # это, а не «тип не прочитали».
        "type_name": "",
        "params": {
            "host": {"ref": host_node["_id"]},
            "direction": direction,
            "position_mm": position,
        },
        "source_element_id": line_id,
        # Уровень и якорь берутся ОДИНАКОВО на обеих дорогах — от носителя и
        # от самой линии, а не от элемента L0, которого может не быть.
        "level_name": host_node.get("level_name"),
        "anchor_mm": position,
    }
    if not is_valid_l1_node(node):
        return None, LiftDiagnostic(
            source_element_id=line_id,
            category="OST_CurtainGrids",
            reason=AtomReason.INVALID_NODE,
            detail="узел линии разрезки не прошёл схему L1")
    return cast(L1OpNode, node), None


#: Чем именно импост НЕ доказан как порождаемый. Причина обязана называть
#: себя: «не порождается типом» и «мы не смотрели» — разные утверждения, и
#: только первое говорит что-то о модели.
_MULLION_ATOM_DETAIL: dict[MullionState, str] = {
    MullionState.MANUAL: (
        ". Сетка правлена вручную: импост либо не заперт за типом "
        "(Mullion.Lock=false), либо его тип не числится среди тех, что "
        "ставит тип носителя — пересборка носителя его НЕ построит"),
    MullionState.UNREADABLE: (
        ". Порождается ли он типом — не прочитано (нет Mullion.Lock либо "
        "слотов AUTO_MULLION_* у типа носителя); засчитать его порождаемым "
        "значило бы вычесть из знаменателя догадку"),
    MullionState.NOT_CAPTURED: (
        ". Индекс снят схемой, которая типовых импостов носителя не читала "
        "(до kir-decompile-curtain-index/4), поэтому доказать порождение "
        "нечем — нужно свежее извлечение"),
}


def _lift_curtain_panel(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Ячейка витража -> ``set_curtain_panel``, либо честный отказ.

    ПРАВИЛО РАСПОЗНАВАНИЯ СТРУКТУРНОЕ (INVARIANT #1): панель штатная, если её
    эффективный тип совпадает с типом, которым носитель разрезает сетку САМ
    (``AUTO_PANEL`` на типе носителя). Никаких списков знакомых имён: в чужой
    модели они называются иначе, а правило то же.

    Порядок отказов значим ровно так же, как в ``_lift_family_fallback``:
    сперва факты о самом элементе (тело ячейки, штатная разрезка), и только
    потом — чего не хватило нам.
    """

    cell = context.curtain_cells.get(element.element_id)
    if cell is None:
        # Индекс про этот элемент не сказал ничего. Общий путь размещения
        # по-прежнему вправе назвать его вложенным ребёнком — эту причину
        # терять нельзя (замер 27.07: 30.37% против 67.70%).
        return _lift_family_fallback(element, context, nodes_by_source)
    host_id, host, panel = cell

    if panel.address_state is not CellAddressState.OK:
        # not_a_panel — не наша немощь, а факт о модели: занявший ячейку
        # экземпляр (витражное окно) не является Panel, а GetRefGridLines
        # живёт только на Panel. Живой замер v4: 50 таких ячеек из 361.
        _refuse(
            AtomReason.MISSING_METADATA,
            "адреса ячейки в индексе витражей нет "
            f"({panel.address_state.value}) — назначать нечему; "
            "нужен повторный захват схемой "
            + CURTAIN_INDEX_SCHEMA_VERSION)
    effective_type_id = panel.effective_type_id
    if not effective_type_id:
        _refuse(
            AtomReason.MISSING_METADATA,
            "у ячейки не прочитан тип — ни собственный, ни у тела")
    # СОСТОЯНИЕ, а не наличие числа. Живой прогон 28.07 (v4) показал, чего
    # стоит их путать: у всех 195 носителей тип по умолчанию был null, и лифт
    # честно отказал по 311 ячейкам — но из того же null-а следовали три
    # разные истины, а различить их было нечем.
    if host.default_panel_state is DefaultPanelState.NONE:
        # Носитель не режет автоматическую панель ВООБЩЕ: значит ни одна
        # ячейка не порождена типом, и каждая занятая — назначена автором.
        # Это структурный вывод из прочитанного факта, а не догадка о нём.
        pass
    elif host.default_panel_state is not DefaultPanelState.OK:
        _refuse(
            AtomReason.MISSING_METADATA,
            "тип панели по умолчанию у носителя не прочитан "
            f"({host.default_panel_state.value}"
            + (f", {host.default_panel_source}"
               if host.default_panel_source else "")
            + ") — штатную панель нельзя отличить от заменённой; нужен "
            "повторный захват схемой " + CURTAIN_INDEX_SCHEMA_VERSION)
    elif effective_type_id == host.default_panel_type_id:
        _refuse(
            AtomReason.GENERATOR_CHILD,
            "тип панели равен типу разрезки носителя — ячейка порождается "
            "самим витражом, отдельной операции у неё нет")
    host_node = nodes_by_source.get(host_id)
    if host_node is None or host_node.get("kind") != "op":
        _refuse(
            AtomReason.MISSING_REFERENCE,
            f"носитель ячейки не поднят (host_id={host_id!r}) — "
            "назначать тип нечему")
    effective_type_name = panel.effective_type_name
    if not effective_type_name:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "у типа ячейки нет имени — селектор построить не из чего")
    _bounded_number(panel.u_index, "set_curtain_panel", "u")
    _bounded_number(panel.v_index, "set_curtain_panel", "v")
    node = _op_node(
        element, "set_curtain_panel",
        {
            "host": {"ref": host_node["_id"]},
            "u": int(panel.u_index),
            "v": int(panel.v_index),
            "panel_type": {
                "by": "name",
                "value": effective_type_name,
                "_id": effective_type_id,
            },
        })
    # ТИП ЛИСТА — ТИП ЯЧЕЙКИ, А НЕ ТОГО ИЗ ДВУХ ЭЛЕМЕНТОВ, КОГО ПОДНЯЛИ.
    #
    # У занятой ячейки два элемента и два имени типа: у занявшего — имя
    # системной обёртки («Стена»), у занятой панели — имя того типа, которым
    # ячейка на самом деле заполнена. Операция описывает ЯЧЕЙКУ, и её тип
    # уже назван в panel_type; оставить в листе имя обёртки значило бы, что
    # один и тот же факт модели канонизируется по-разному в зависимости от
    # того, какой из двух элементов попал в документ.
    #
    # ЗАМЕР (v12, пересборка №6): у 20 ячеек, поднятых с обеих сторон,
    # ``params`` совпадали ПОБАЙТНО — host-ссылка, u, v, panel_type, — и
    # расходился ровно ``type_name`` («Стена» против «_Пустая_ Не
    # учитывать_200мм»). Этого хватало, чтобы канонический хеш не совпал ни
    # разу и сравнение идемпотентности показывало расхождение там, где
    # модель одна и та же.
    node["type_name"] = effective_type_name
    return node


def _closed_profile(
    element: L0Element,
    context: _Context,
    missing_detail: str,
    *,
    polygon_op: str = "create_floor/create_roof",
) -> tuple[list[list[float]], list[list[list[float]]]]:
    raw = context.profile_index.get(element.element_id)
    if raw is None:
        _refuse(AtomReason.MISSING_GEOMETRY, missing_detail)
    try:
        record = ProfileIndexRecord.from_dict(
            element.element_id,
            raw,
            f"profile_index[{element.element_id!r}]",
        )
    except SketchPayloadError as exc:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            f"Sketch profile side-index row is invalid: {exc}")
    if not record.profile_available or record.exterior_loop is None:
        _refuse(AtomReason.MISSING_GEOMETRY, missing_detail)

    loops = (record.exterior_loop,) + record.holes
    if any(len(loop.points_mm) < 3 for loop in loops):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            f"{polygon_op} requires at least three profile vertices")
    # ТОТ ЖЕ закон, что на прямом ходу, ЧИТАЕМЫЙ ИЗ ОДНОГО МЕСТА. До 10.08 эти
    # три числа стояли здесь своей копией, хотя строкой ниже сказано «forward
    # polygon bounds» — то есть копия ЗНАЛА, что повторяет чужой закон. Цена
    # расхождения здесь молчаливая: элемент становится атомом, и никакой отказ
    # об этом не скажет.
    if (len(record.exterior_loop.points_mm) > _geom.MAX_RING_POINTS
            or len(record.holes) > _geom.MAX_HOLES
            or any(len(loop.points_mm) > _geom.MAX_HOLE_RING_POINTS
                   for loop in record.holes)):
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"{polygon_op} profile exceeds the forward polygon bounds "
            f"({_geom.MAX_RING_POINTS} pts / {_geom.MAX_HOLES} holes / "
            f"{_geom.MAX_HOLE_RING_POINTS} pts per hole)")
    if any(
        kind is not CurveKind.LINE
        for loop in loops
        for kind in loop.curve_kinds
    ):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "forward polygon ops cannot exactly represent an arc profile")

    outline = [list(point) for point in record.exterior_loop.points_mm]
    holes = [
        [list(point) for point in loop.points_mm]
        for loop in record.holes
    ]

    # Mirror the existing forward polygon laws before claiming an invertible
    # op. Actual Sketch rows are normally valid Revit loops, but persisted or
    # synthetic side indexes still enter through this public boundary.
    from kukai.ir.geom import check_holes_relation, ring_normalize
    geometry_diagnostics: list[Any] = []
    normalized_outline = ring_normalize(
        outline, element.element_id, "outline", geometry_diagnostics)
    normalized_holes = []
    for index, hole in enumerate(holes):
        normalized = ring_normalize(
            hole,
            element.element_id,
            f"holes[{index}]",
            geometry_diagnostics,
        )
        if normalized is None:
            break
        normalized_holes.append(normalized)
    if (normalized_outline is None
            or len(normalized_holes) != len(holes)
            or abs(record.exterior_loop.signed_area_mm2) < _geom.MIN_RING_AREA_MM2
            or any(abs(loop.signed_area_mm2) < _geom.MIN_RING_AREA_MM2
                   for loop in record.holes)
            or not check_holes_relation(
                normalized_outline,
                normalized_holes,
                element.element_id,
                geometry_diagnostics,
            )):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            f"{polygon_op} profile fails the forward polygon laws")
    return normalized_outline, normalized_holes


def _level_from_id(
    element: L0Element,
    context: _Context,
    source_param: str,
) -> LevelInfo:
    level_id = element.params.get(source_param)
    if not isinstance(level_id, str) or not level_id:
        _refuse(
            AtomReason.MISSING_PARAMETER,
            f"{source_param} is absent or not an element id")
    level = context.levels_by_id.get(level_id)
    if level is None:
        _refuse(
            AtomReason.MISSING_METADATA,
            f"{source_param} level metadata is absent")
    return level


def _stairs_run_endpoints(
    element: L0Element,
    context: _Context,
) -> tuple[list[float], list[float]]:
    missing_detail = "frozen L0 has no reliable stair-run geometry"
    raw = context.stairs_run_path_index.get(element.element_id)
    if raw is None:
        _refuse(AtomReason.MISSING_GEOMETRY, missing_detail)
    if not isinstance(raw, Mapping):
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "stairs run-path side-index row is not an object")
    if "profile_available" in raw:
        _refuse(AtomReason.MISSING_GEOMETRY, missing_detail)

    # The persisted shape is {stairs_id: {run_id: path_record}}.  Also accept
    # one exact path record when callers pass a single extracted row directly.
    if "path_available" in raw:
        path_rows = ((element.element_id, raw),)
    else:
        if not all(isinstance(run_id, str) for run_id in raw):
            _refuse(
                AtomReason.MISSING_GEOMETRY,
                "stairs run ids must be strings")
        path_rows = tuple(raw.items())
    if not path_rows:
        _refuse(AtomReason.MISSING_GEOMETRY, missing_detail)
    if len(path_rows) != 1:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "create_stairs can reproduce exactly one straight source run")

    run_id, raw_path = path_rows[0]
    try:
        record = StairsRunPathRecord.from_dict(
            element.element_id,
            run_id,
            raw_path,
            f"stairs_run_path_index[{element.element_id!r}][{run_id!r}]",
        )
    except SketchPayloadError as exc:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            f"stairs run-path side-index row is invalid: {exc}")
    if not record.path_available or record.path is None:
        _refuse(AtomReason.MISSING_GEOMETRY, missing_detail)
    if any(kind is not CurveKind.LINE for kind in record.path.curve_kinds):
        # ПРИЧИНА ОБНОВЛЕНА 09.08.2026, И ЭТО ВАЖНО: с этого дня `create_stairs`
        # ВЫРАЖАЕТ винтовой марш (`spiral` -> StairsRun.CreateSpiralRun), так
        # что прежняя формулировка «оп не может представить кривой марш» стала
        # неправдой — а неверная причина атома отправляет чинить не то.
        # Обратный ход всё ещё не может: захвачен ПУТЬ марша (точки + середины
        # дуг), а `spiral` описывается центром и радиусом САМОГО марша, и
        # отношение между ними (смещение на полуширину, юстировка) НЕ
        # ИЗМЕРЕНО. Вывести из трёх точек центр дуги ПУТИ можно; выдать его за
        # центр марша — нельзя, это и была бы тихая неправда.
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "curved stairs run: create_stairs.spiral expresses it forward, "
            "but the captured stairs PATH cannot yet be turned into the run's "
            "own centre/radius (that offset is unmeasured)")

    points = record.path.points_mm
    p0 = points[0]
    p1 = points[-1]
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    length_squared = dx * dx + dy * dy
    if length_squared < 1.0:
        _refuse(
            AtomReason.INVALID_VALUE,
            "stairs run endpoints are shorter than the forward 1 mm limit")

    # A multi-segment path is representable by create_stairs only when every
    # segment belongs to the same directed straight run.  The tolerance is at
    # floating-point noise scale, not a geometric chord approximation.
    previous_fraction = 0.0
    cross_tolerance = 1e-12 * max(length_squared, 1.0)
    for point in points[1:-1]:
        rel_x = point[0] - p0[0]
        rel_y = point[1] - p0[1]
        cross = dx * rel_y - dy * rel_x
        fraction = (rel_x * dx + rel_y * dy) / length_squared
        if (abs(cross) > cross_tolerance
                or fraction <= previous_fraction
                or fraction >= 1.0):
            _refuse(
                AtomReason.UNSUPPORTED_GEOMETRY,
                "stairs path is not one exact directed straight run")
        previous_fraction = fraction
    return list(p0), list(p1)


def _dimension_side_index(dimension_index: Any) -> Mapping[str, Any]:
    """Конверт стадии размеров -> адрес лифта (id -> строка).

    Принимается и разобранный ``DimensionExtraction``, и голый
    ``dimension_index``, и полный ``to_dict()``-конверт. Любая порча -> ``{}``,
    то есть «индекса нет», то есть ПРЕЖНИЙ отказ дословно: слепок, снятый до
    появления стадии, обязан читаться как отсутствие индекса, а не как пустой
    индекс с другим смыслом (§18.2: отсутствующий и пустой — разные факты, но
    оба обязаны дать ЧЕСТНЫЙ, а не выдуманный, ответ).
    """
    if dimension_index is None:
        return {}
    if isinstance(dimension_index, DimensionExtraction):
        return dimension_index.dimension_index
    if not isinstance(dimension_index, Mapping):
        return {}
    if "dimension_index" in dimension_index or "schema_version" in dimension_index:
        try:
            return DimensionExtraction.from_dict(dimension_index).dimension_index
        except (DimensionPayloadError, ValueError, TypeError):
            return {}
    return dimension_index


def _mep_system_side_index(mep_system_index: Any) -> Mapping[str, Any]:
    """Привести индекс принадлежности системе к плоской карте id -> запись."""
    if mep_system_index is None:
        return {}
    if isinstance(mep_system_index, MepSystemExtraction):
        return mep_system_index.system_index
    if not isinstance(mep_system_index, Mapping):
        return {}
    if "system_index" in mep_system_index or "schema_version" in mep_system_index:
        try:
            return MepSystemExtraction.from_dict(mep_system_index).system_index
        except MepSystemPayloadError:
            return {}
    return mep_system_index


def _annotation_side_index(annotation_index: Any) -> Mapping[str, Any]:
    """Привести боковой индекс оформления к плоской карте id -> запись.

    Принимается разобранный :class:`AnnotationExtraction`, его проекция
    ``text_note_index`` или полный ``to_dict()``-конверт. Любая порча -> ``{}``,
    то есть ровно прежнее поведение: каждое примечание остаётся атомом с
    причиной source_contract_gap. Отказ закрытый: испорченный индекс НЕ имеет
    права превратиться в частично поднятое оформление, потому что «половина
    текстов на месте» выглядит как успех и читается как покрытие.
    """
    if annotation_index is None:
        return {}
    if isinstance(annotation_index, AnnotationExtraction):
        return annotation_index.text_note_index
    if not isinstance(annotation_index, Mapping):
        return {}
    if "text_note_index" in annotation_index or "schema_version" in annotation_index:
        try:
            return AnnotationExtraction.from_dict(annotation_index).text_note_index
        except AnnotationPayloadError:
            return {}
    return annotation_index


def _tag_side_index(tag_index: Any) -> Mapping[str, Any]:
    """Привести боковой индекс марок к плоской карте id -> запись.

    Принимается разобранный :class:`TagExtraction`, его проекция
    ``tag_index`` или полный ``to_dict()``-конверт. Любая порча -> ``{}``, то
    есть ровно прежнее поведение: каждая марка остаётся атомом с причиной
    source_contract_gap. Отказ закрытый по той же причине, что и у
    оформления: «половина марок на месте» выглядит как успех и читается как
    покрытие.
    """
    if tag_index is None:
        return {}
    if isinstance(tag_index, TagExtraction):
        return tag_index.tag_index
    if not isinstance(tag_index, Mapping):
        return {}
    if "tag_index" in tag_index or "schema_version" in tag_index:
        try:
            return TagExtraction.from_dict(tag_index).tag_index
        except TagPayloadError:
            return {}
    return tag_index


def _wall_curve_side_index(
    wall_curve_index: CurveExtraction | Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    """Normalise the optional wall-curve side index to a plain per-id mapping.

    The canon location-curve extractor is
    :class:`kukai.ir.decompile.curve_extract.CurveExtraction` (live-verified on
    LOT31). This accepts a parsed ``CurveExtraction``, its ``curve_index``
    projection, or a full ``to_dict()`` envelope (``{schema_version,
    curve_index, failures}``). Anything malformed becomes ``{}`` — fail-closed:
    an absent/unreadable side index simply lifts every wall as a straight Line,
    exactly as before this wave."""
    if wall_curve_index is None:
        return {}
    if isinstance(wall_curve_index, CurveExtraction):
        return wall_curve_index.curve_index
    if not isinstance(wall_curve_index, Mapping):
        return {}
    # A persisted envelope carries the schema_version + curve_index map; rebuild
    # it through the audited parser so malformed rows are rejected, not trusted.
    if "curve_index" in wall_curve_index or "schema_version" in wall_curve_index:
        try:
            return CurveExtraction.from_dict(wall_curve_index).curve_index
        except CurvePayloadError:
            return {}
    # Otherwise it is already a per-id projection ({element_id: {curve_kind...}}).
    return wall_curve_index


def _lift_wall(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _curve(element, dimensions=2)
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "height_mm": _bounded_param(
            element,
            "WALL_USER_HEIGHT_PARAM",
            "create_wall",
            "height_mm",
        ),
        "type": _catalog_ref(element),
    }
    # Curve-IR (P4-B): if the additive wall-curve side index says this wall is
    # an Arc, emit the arc dict so it recompiles curved instead of flattened to
    # a straight Line. Frozen L0 only knows p0/p1, so a curved wall is invisible
    # without this side index — its absence just leaves the straight-Line lift
    # untouched (fail-open to the pre-existing behaviour). A non-Arc / malformed
    # side entry is ignored (fail-closed to the straight wall, never a wrong arc).
    arc = _wall_arc_param(element, context, p0, p1)
    if arc is not None:
        params["arc"] = arc
    elif element.curve_kind is not None \
            and element.curve_kind is not LocationCurveKind.LINE:
        # Рабочий дуговой путь стены выше НЕ ТРОНУТ: сюда попадает только
        # стена, про которую сам захват сказал «не прямая», а годной строки
        # бокового индекса не нашлось (индекс не собирался, бюджет срезал
        # строку, концы разошлись). Раньше это была тихая прямая: §18.1
        # запрещает её ровно так же, как у балки. Условие завязано на ПОЛЕ,
        # которого в замороженном L0 нет, поэтому ни один существующий разбор
        # поведения не меняет.
        _refuse(
            AtomReason.CURVE_KIND_UNSUPPORTED,
            f"LocationCurve is {element.curve_kind.value!r} and no matching "
            "arc row is available in the curve side index — a chord would "
            "silently straighten this wall")
    # Vertical attributes (audit F6).  base offset: emitted only when >=1mm so
    # the typical on-level wall keeps its historical byte-identical params
    # (canonical hashes stable, same threshold discipline as the door's sill).
    base_offset = _finite(element.params.get("WALL_BASE_OFFSET"))
    if base_offset is not None and abs(base_offset) >= 1.0:
        params["base_offset_mm"] = _bounded_param(
            element, "WALL_BASE_OFFSET", "create_wall", "base_offset_mm")
    # Which plane the location-line RULE names.  MEASURED 2026-07-28
    # (docs/2026-07-28-location-line-measurement.md): LocationCurve is the
    # body's CENTRE plane at every ordinal — the rebuilt wall's body stands
    # in place even without the rule.  The rule is semantic state: it decides
    # which plane survives a future thickness change, so it must survive the
    # round trip as itself.  Ordinal 0 is Revit's default and is deliberately
    # NOT lifted (emitting it would move every historical wall's params and
    # canon hash for a rule the rebuild already follows).  Anything else is a
    # defining semantic DOF.  An unknown ordinal is an honest atom, never a
    # guessed plane.
    key_ref = element.params.get("WALL_KEY_REF_PARAM")
    if key_ref is not None:
        try:
            ordinal = int(key_ref)
        except (TypeError, ValueError):
            _refuse(AtomReason.MISSING_METADATA,
                    "WALL_KEY_REF_PARAM is not an integer ordinal")
        if ordinal != 0:
            name = WALL_LOCATION_LINE_NAMES.get(ordinal)
            if name is None:
                _refuse(AtomReason.MISSING_METADATA,
                        f"WALL_KEY_REF_PARAM ordinal {ordinal} is not a known "
                        "wall location line")
            if name not in _LOCATION_LINE_CHOICES:
                # A plane Revit has and the emitter cannot yet realise (the
                # core planes).  Lifting it would produce a program the
                # compiler refuses; claiming centreline would move the wall.
                # An atom is the only honest answer.
                _refuse(AtomReason.UNSUPPORTED_SIGNATURE,
                        f"wall location line {name!r} is not expressible by "
                        "create_wall yet (needs the type's compound structure)")
            params["location_line"] = name
    # Top constraint: WALL_HEIGHT_TYPE carries the attached top level's id
    # (absent for unconnected walls — __PutIdParam skips InvalidElementId).
    # Present but NOT resolving to a known level = contradictory metadata ->
    # honest atom, never a guessed constraint.  height_mm stays required
    # (already lifted above): it is the measured actual height and doubles as
    # the emit-side consistency witness against the attached constraint.
    top_level_id = element.params.get("WALL_HEIGHT_TYPE")
    if top_level_id is not None:
        if not isinstance(top_level_id, str):
            _refuse(
                AtomReason.MISSING_METADATA,
                "WALL_HEIGHT_TYPE is not an element-id string")
        top = context.levels_by_id.get(top_level_id)
        if top is None:
            _refuse(
                AtomReason.MISSING_METADATA,
                "WALL_HEIGHT_TYPE does not resolve to an extracted level")
        # Wall-fidelity (live A5 evidence 2026-07-21): the top offset is a
        # DEFINING DOF of the attach — without it the emitter derives height as
        # the full span and canon misses by exactly |offset|.  Same >=1mm
        # threshold discipline as base_offset (unattached walls and zero-offset
        # attaches keep their historical byte-identical params).
        top_offset = _finite(element.params.get("WALL_TOP_OFFSET"))
        # ЛИФТ НЕ ПОДНИМАЕТ ПРИВЯЗКУ, КОТОРАЯ КЛАДЁТ ВЕРХ НИЖЕ ПОДОШВЫ.
        # Найдено пересборкой настоящего здания 27.07: чанк из 250 опов
        # откатывался ЦЕЛИКОМ с «Верх стены находится ниже, чем подошва стены»
        # из-за ДВУХ стен на 693 (подошва +2185 при верхе −300).  Гипотеза
        # «привязка на собственный уровень = высота не привязана» опровергнута
        # замером: из 94 таких стен невозможны 2, остальные 92 законны — правило
        # обязано быть геометрическим, а не про совпадение уровней.  Когда
        # привязка невозможна, честнее отдать измеренную высоту, которую стена
        # и имеет (WALL_USER_HEIGHT_PARAM уже поднят выше), чем программу,
        # которую Revit откажется исполнять.
        base_level = context.levels_by_id.get(str(element.level_id))
        base_elev = _finite(getattr(base_level, "elevation_mm", None)) or 0.0
        top_elev = _finite(getattr(top, "elevation_mm", None)) or 0.0
        base_abs = base_elev + (_finite(params.get("base_offset_mm")) or 0.0)
        top_abs = top_elev + (top_offset or 0.0)
        if top_abs > base_abs:
            params["top_level"] = {
                "by": "name", "value": top.name, "_id": top.id}
            if top_offset is not None and abs(top_offset) >= 1.0:
                params["top_offset_mm"] = _bounded_param(
                    element, "WALL_TOP_OFFSET", "create_wall", "top_offset_mm")
    return _op_node(element, "create_wall", params)


def _wall_arc_param(
    element: L0Element,
    context: _Context,
    p0: list[float],
    p1: list[float],
) -> dict[str, Any] | None:
    """The canonical authoring Arc dict for this wall from the side index, or
    None.

    Only an ``arc``-kind record whose endpoints agree with the frozen-L0 p0/p1
    (±1 mm, either orientation, in the plan plane) is accepted — so a stale /
    mismatched side entry can never silently bend a wall it does not describe.
    The canon ``curve_index`` row nests the six ArcCurve fields under ``arc``
    (no ``curve_type``); the authoring op wants the same six plus
    ``curve_type: "Arc"`` at the top level, so this translates the shape.
    Fidelity is ``approximate`` (Step-0 scale): the arc geometry is faithful but
    the downstream create is a fresh authoring op, not a byte round-trip."""
    entry = context.wall_curve_index.get(element.element_id)
    if not isinstance(entry, Mapping):
        return None
    if entry.get("curve_kind") != WallCurveKind.ARC.value:
        return None
    curve = entry.get("arc")
    if not isinstance(curve, Mapping):
        return None
    # Endpoints implied by the arc must match the frozen-L0 wall endpoints in
    # the plan plane, else the side index describes a different wall — refuse to
    # attach it (p0/p1 are 2D; the arc's absolute z is its capture elevation).
    try:
        c = curve["center_mm"]
        r = float(curve["radius_mm"])
        xa = curve["x_axis"]
        ya = curve["y_axis"]
        start = float(curve["start_angle_rad"])
        end = float(curve["end_angle_rad"])
        ends = []
        for ang in (start, end):
            ca, sa = math.cos(ang), math.sin(ang)
            ends.append((
                c[0] + r * (ca * xa[0] + sa * ya[0]),
                c[1] + r * (ca * xa[1] + sa * ya[1])))
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    p0xy, p1xy = (p0[0], p0[1]), (p1[0], p1[1])
    forward = max(_distance(ends[0], p0xy), _distance(ends[1], p1xy))
    reverse = max(_distance(ends[0], p1xy), _distance(ends[1], p0xy))
    if min(forward, reverse) > 1.0:
        return None
    return {
        "curve_type": "Arc",
        "center_mm": [float(v) for v in c],
        "radius_mm": r,
        "x_axis": [float(v) for v in xa],
        "y_axis": [float(v) for v in ya],
        "start_angle_rad": start,
        "end_angle_rad": end,
    }


def _profile_record(element: L0Element, context: _Context) -> Any:
    """Строка бокового индекса эскизов для элемента, либо None.

    Разбор строгий и ОДИН на оба пути (полигон и контур): битая строка — это
    отсутствие профиля, а не повод угадать форму.
    """

    raw = context.profile_index.get(element.element_id)
    if raw is None:
        return None
    try:
        return ProfileIndexRecord.from_dict(
            element.element_id, raw,
            f"profile_index[{element.element_id!r}]")
    except SketchPayloadError:
        return None


def _profile_needs_contour(record: Any) -> bool:
    """Полигоном НЕ выражается: есть дуга либо петля из двух сегментов."""

    if not record.profile_available or record.exterior_loop is None:
        return False
    loops = (record.exterior_loop,) + tuple(record.holes)
    for loop in loops:
        if len(loop.points_mm) < 3:
            return True
        if any(kind is CurveKind.ARC for kind in loop.curve_kinds):
            return True
    return False


#: Дуга в профиле — точка, середина, точка. Ровно эти три числа лежат в
#: боковом индексе эскизов (``ProfileLoop.arc_midpoints_mm``), и ровно из них
#: получается ``bulge`` контурного опа. Формула — ТОЧНАЯ ОБРАТНАЯ к
#: ``contour.bulge_midpoint``: та строит середину как
#: ``chord_mid - normal * (bulge * chord / 2)``, значит
#: ``bulge = -2 * dot(mid - chord_mid, normal) / chord``.
#:
#: Проверено на замере (28.07): 3051 дуга двух разборов, худшая невязка
#: обратного хода 2.4e-8 мм. Каждая дуга пересчитывается ОБРАТНО их же
#: функцией и сверяется — расхождение больше 0.1 мм это отказ, а не «почти
#: то же самое».
_ARC_BULGE_TOL_MM = 0.1

#: НЕ САМОСТОЯТЕЛЬНОЕ ЧИСЛО, А ССЫЛКА. Предел кольца КОНТУРА обязан совпадать
#: с тем, что подъязык принимает (`contour._validate_shape`), иначе лифтер
#: соберёт форму, которую компилятор тут же отвергнет, — и диагноз будет о
#: контуре, а не о нас. До 10.08 здесь стояла собственная 64.
_CONTOUR_MAX_POINTS = _geom.MAX_RING_POINTS


def _bulge_from_midpoint(
    p0: Sequence[float], p1: Sequence[float], mid: Sequence[float],
) -> float | None:
    """DXF-bulge дуги p0→p1, проходящей через ``mid``, либо None."""

    dx, dy = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
    chord = math.hypot(dx, dy)
    if chord < 1e-9:
        return None
    nx, ny = -dy / chord, dx / chord
    cx, cy = (float(p0[0]) + float(p1[0])) / 2.0, (float(p0[1]) + float(p1[1])) / 2.0
    sagitta = -((float(mid[0]) - cx) * nx + (float(mid[1]) - cy) * ny)
    return 2.0 * sagitta / chord


def _contour_shape(loop: Any) -> dict[str, Any] | None:
    """Петля профиля -> форма ``poly`` контурного опа, либо None.

    Петля из ДВУХ сегментов (окружность: две дуги) в ``poly`` не выражается —
    у формы минимум три точки. Такая дуга РЕЖЕТСЯ ПОПОЛАМ по своей же
    захваченной середине: это не аппроксимация, а та же кривая, записанная
    двумя дугами (замер: 126 таких петель на «демо-v3», все — окружности).
    Половинный bulge = tan(atan(b)/2), потому что сектор делится пополам.
    """

    points = [tuple(float(value) for value in point) for point in loop.points_mm]
    kinds = list(loop.curve_kinds)
    midpoints = list(loop.arc_midpoints_mm)
    split = len(points) < 3
    out_points: list[list[float]] = []
    arcs: list[dict[str, Any]] = []
    for index, kind in enumerate(kinds):
        start = points[index]
        end = points[(index + 1) % len(points)]
        if kind is not CurveKind.ARC:
            out_points.append([start[0], start[1]])
            continue
        mid = midpoints[index]
        if mid is None:
            return None
        bulge = _bulge_from_midpoint(start, end, mid)
        # Порог дуги и её потолок принадлежат ПОДЪЯЗЫКУ, а не лифтеру:
        # записать дугу, которую CONTOUR потом отвергнет, значит отдать
        # программу, падающую на своей же валидации. До 10.08 оба числа
        # стояли здесь копией.
        if (bulge is None or abs(bulge) < _contour.MIN_ARC_BULGE
                or abs(bulge) > _contour.MAX_ARC_BULGE):
            return None
        if split:
            half = math.tan(math.atan(bulge) / 2.0)
            if abs(half) < 1e-6:
                return None
            arcs.append({"edge": len(out_points), "bulge": half})
            out_points.append([start[0], start[1]])
            arcs.append({"edge": len(out_points), "bulge": half})
            out_points.append([float(mid[0]), float(mid[1])])
            continue
        # Сверка ОБРАТНЫМ ходом их же функцией: bulge обязан вернуть ту же
        # середину, иначе мы записали не ту дугу.
        from kukai.ir.contour import bulge_midpoint
        back = bulge_midpoint(list(start), list(end), bulge)
        if math.dist(back, (float(mid[0]), float(mid[1]))) > _ARC_BULGE_TOL_MM:
            return None
        arcs.append({"edge": len(out_points), "bulge": bulge})
        out_points.append([start[0], start[1]])
    if not (_geom.MIN_RING_POINTS <= len(out_points) <= _CONTOUR_MAX_POINTS):
        return None
    shape: dict[str, Any] = {"shape": "poly", "points_mm": out_points}
    if arcs:
        shape["arcs"] = arcs
    return shape


def _contour_region(record: Any) -> dict[str, Any]:
    """Строка бокового индекса эскизов -> регион ``contour`` (или отказ).

    ОДНА функция на всех потребителей КОНТУРА, и это не вкус: 09.08 второй
    контурной операцией стал потолок, и второй экземпляр этих же четырёх
    проверок означал бы два ответа на один вопрос «выражается ли профиль
    контуром». Разъехавшись, они дали бы разные атомы на одинаковых профилях
    — тот же класс, что две таблицы категорий (потолок/ограждение, 29.07) и
    три словаря разделов (fold, 28.07).

    Оба отказа — ФОРМЕННЫЕ (`_SHAPE_REFUSALS`), то есть «элемент не той
    формы, о которой этот оп»; про значение или ссылку здесь не говорится
    ничего, и падать в `place_family` они вправе.
    """

    loops = (record.exterior_loop,) + tuple(record.holes)
    shapes = [_contour_shape(loop) for loop in loops]
    if any(shape is None for shape in shapes):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            f"профиль не выражается контуром: петля вне границ "
            f"{_geom.MIN_RING_POINTS}..{_CONTOUR_MAX_POINTS} точек "
            f"или дуга без точной середины")
    # `shapes` — это внешнее кольцо ПЛЮС отверстия, поэтому предел здесь не
    # самостоятельная девятка, а `1 + MAX_HOLES`. Голая 9 рядом с текстом
    # «до 8 проёмов» читалась как опечатка и держалась только тем, что её
    # никто не трогал: подвинув MAX_HOLES, эту 9 забыли бы наверняка.
    if len(shapes) > 1 + _geom.MAX_HOLES:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"контур поддерживает до {_geom.MAX_HOLES} проёмов")
    region: dict[str, Any] = {"outer": shapes[0]}
    if len(shapes) > 1:
        region["holes"] = shapes[1:]
    return region


def _lift_floor_by_contour(
    element: L0Element,
    context: _Context,
    record: Any,
) -> L1OpNode:
    """Пол, чей профиль полигоном не выражается -> ``create_floor_by_contour``.

    Повод замерен, а не предположен: на «демо-v3» 155 полов из 235 профилей
    несут дуги либо петлю из двух сегментов, и все они были атомами
    ``unsupported_geometry`` — оп для них написан и проходит ворота, но в
    декомпайле его имени не было ни разу.
    """

    params: dict[str, Any] = {
        "contour": _contour_region(record),
        "level": _level_ref(element.level_id, element.level_name),
        "type": _catalog_ref(element),
    }
    height_offset = _finite(
        element.params.get("FLOOR_HEIGHTABOVELEVEL_PARAM"))
    if height_offset is not None and _survives_canon_rounding(height_offset):
        params["height_offset_mm"] = _bounded_param(
            element, "FLOOR_HEIGHTABOVELEVEL_PARAM",
            "create_floor_by_contour", "height_offset_mm")
    return _op_node(element, "create_floor_by_contour", params)


def _lift_floor(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    # Профиль с ДУГОЙ или петлёй из двух сегментов полигоном не выражается —
    # но выражается контуром, и оп для этого есть с самого начала. До этой
    # волны такой пол оставался атомом: `create_floor_by_contour` не
    # упоминался в декомпайле ни разу.
    record = _profile_record(element, context)
    if record is not None and _profile_needs_contour(record):
        return _lift_floor_by_contour(element, context, record)
    outline, holes = _closed_profile(
        element,
        context,
        "frozen L0 has no reliable floor Sketch profile",
    )
    params: dict[str, Any] = {
        "outline": outline,
        "holes": holes,
        "level": _level_ref(element.level_id, element.level_name),
        "type": _catalog_ref(element),
    }
    # P1 DOF-completeness: смещение пола от уровня (51% полов «демо»).
    # codex #8 (2026-07-29): порог был независимым >=1мм, из-за чего
    # 0.4-0.999мм терялись молча; теперь единственный закон — тот же грид,
    # которым FidelityCanon округляет любое _mm-поле (_survives_canon_
    # rounding); absent — историческая байт-идентичная эмиссия ТОЛЬКО для
    # значений, которые сам канон уже сплющивает в ноль.
    height_offset = _finite(
        element.params.get("FLOOR_HEIGHTABOVELEVEL_PARAM"))
    if height_offset is not None and _survives_canon_rounding(height_offset):
        params["height_offset_mm"] = _bounded_param(
            element, "FLOOR_HEIGHTABOVELEVEL_PARAM", "create_floor",
            "height_offset_mm")
    return _op_node(element, "create_floor", params)


def _lift_ceiling_by_contour(
    element: L0Element,
    context: _Context,
    record: Any,
) -> L1OpNode:
    """Потолок, чей профиль полигоном не выражается -> ``create_ceiling``.

    ОТДЕЛЬНОЙ ОПЕРАЦИИ ЗДЕСЬ НЕТ, И ЭТО РАЗНИЦА С ПОЛОМ, а не недосмотр: у
    пола контурная форма приехала своим опом (`create_floor_by_contour`), у
    потолка — ВТОРЫМ ВХОДОМ той же операции. Поэтому имя опа то же самое, а
    различает ветки набор полей: `contour` ЛИБО `outline`+`holes`, ровно одно
    из двух (KIR-P007). Эмитировать оба значило бы отдать компилятору
    программу, которую он обязан отвергнуть, — то есть заявить покрытие,
    которое не строится.

    Смещение читается тем же CEILING_HEIGHTABOVELEVEL_PARAM, что и в прямой
    ветке: параметр — свойство КАТЕГОРИИ, а не способа задать форму.
    """

    params: dict[str, Any] = {
        "contour": _contour_region(record),
        "level": _level_ref(element.level_id, element.level_name),
        "type": _catalog_ref(element),
    }
    height_offset = _finite(
        element.params.get("CEILING_HEIGHTABOVELEVEL_PARAM"))
    if height_offset is not None and _survives_canon_rounding(height_offset):
        params["height_offset_mm"] = _bounded_param(
            element, "CEILING_HEIGHTABOVELEVEL_PARAM", "create_ceiling",
            "height_offset_mm")
    return _op_node(element, "create_ceiling", params)


def _lift_ceiling(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Потолок обратным ходом (wave/arch, 2026-07-29).

    Механика ровно та же, что у пола: замкнутый профиль из бокового индекса
    эскизов + уровень + тип. Отличий два, и оба замерены, а не выбраны.

    1. Смещение читается из CEILING_HEIGHTABOVELEVEL_PARAM (6/6), а не из
       FLOOR_HEIGHTABOVELEVEL_PARAM. Имя параметра — часть тождества
       категории, и чужое имя здесь молча вернуло бы ноль.
    3. КОНТУР (09.08.2026). Профиль с ДУГОЙ полигоном не выражается, и до
       сегодня такой потолок оставался атомом `unsupported_geometry` — «оп не
       умеет эту форму». Утром 09.08 это перестало быть правдой: у
       `create_ceiling` появился второй вход формы, `contour` рода `region`
       (ops_arch.py), то есть весь язык эскиза CONTOUR. Захват при этом
       менять не пришлось НИ НА СТРОКУ: боковой индекс эскизов несёт потолки
       с 29.07 (`sketch_extract`, категория в `_STAGE_CATEGORIES`) и хранит
       для каждой петли и род сегмента, и середину дуги — ровно те три числа,
       из которых пол собирает `bulge`. Значит здесь был не разрыв захвата, а
       ненаписанная ветка, и это ровно тот случай, когда лифтер писать МОЖНО.

       Ветка эмитирует `contour` ВМЕСТО `outline`/`holes`, а не рядом: у
       региона отверстия свои, и держать оба описания сразу — типизированный
       KIR-P007 (compiler.py). Полигональный путь при этом не тронут ни на
       байт: потолок без дуг обязан дать прежний узел дословно, иначе круг
       разомкнётся на каждом уже разобранном здании.

    2. ГРАНИЦА ЧЕСТНОСТИ, КОТОРУЮ НАДО ЗНАТЬ ЧИТАТЕЛЮ: наклон потолка этим
       лифтом НЕ ВОССТАНАВЛИВАЕТСЯ и восстановлен быть не может. В
       замороженном L0 наклона нет ни в каком виде: BuiltInParameter с таким
       смыслом не существует (проверено компиляцией — ни CEILING_SLOPE, ни
       родственных имён нет ни на одной из шести версий), а боковой индекс
       эскизов хранит контур ПЛОСКО, в [x,y], без стрелки уклона. Значит для
       наклонного потолка этот лифт вернёт плоский, и отличить один от
       другого по нынешнему слепку НЕЧЕМ — сторожа на это поставить не из
       чего, и выдумывать имя параметра ради видимости сторожа было бы хуже
       молчания. Закрывается это НЕ здесь, а на стороне извлечения: пока
       экстрактор не начнёт снимать стрелку уклона, «потолки ездят
       туда-обратно» — утверждение недоказанное, и в отчёте волны оно так и
       записано.
    """
    record = _profile_record(element, context)
    if record is not None and _profile_needs_contour(record):
        return _lift_ceiling_by_contour(element, context, record)
    outline, holes = _closed_profile(
        element,
        context,
        "frozen L0 has no reliable ceiling Sketch profile",
        polygon_op="create_ceiling",
    )
    params: dict[str, Any] = {
        "outline": outline,
        "holes": holes,
        "level": _level_ref(element.level_id, element.level_name),
        "type": _catalog_ref(element),
    }
    height_offset = _finite(
        element.params.get("CEILING_HEIGHTABOVELEVEL_PARAM"))
    if height_offset is not None and _survives_canon_rounding(height_offset):
        params["height_offset_mm"] = _bounded_param(
            element, "CEILING_HEIGHTABOVELEVEL_PARAM", "create_ceiling",
            "height_offset_mm")
    return _op_node(element, "create_ceiling", params)


def _lift_railing(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Ограждение обратным ходом (wave/arch 29.07 + подключение чтения 03.08).

    ИСТОРИЯ ЭТОЙ ФУНКЦИИ — половина её смысла, поэтому она здесь целиком.

    29.07 лифт написали, и он честно отказывал ВСЕГДА: замер K2 показал, что
    все 203 OST_StairsRailing лежат в L0 как ``bbox_only``/``point`` с пустым
    ``params`` и ``host_id: null`` — ни пути, ни хозяина, ни позиции. Отказ
    был не дефектом лифта, а точным диагнозом стороне ИЗВЛЕЧЕНИЯ.

    Той же волной сторона извлечения диагноз ПРИНЯЛА:
    ``sketch_extract.RailingPathRecord`` снимает ``Railing.GetPath()``,
    ``HasHost``/``HostId`` и ``STAIRS_RAILING_BASE_LEVEL_PARAM``, а
    ``pipeline._STAGE_CATEGORIES['sketch']`` кормит стадию обеими категориями
    ограждений. Захват поехал в прод и снимает данные с 29.07.

    А ЛИФТ ЕГО НЕ ЧИТАЛ. ``_Context`` знал ``stairs_run_path_index`` и не знал
    ``railing_path_index``; функция ниже отказывала по ``element.host_id``, то
    есть по строке L0, при том что в ``sketch.index.json`` того же разбора
    лежали готовые пути. Замер 03.08 по k2_ar_rd_v9: 31 строка захвата,
    28 — свободные ограждения с путём, базовым уровнем и плоскостью РОВНО на
    отметке уровня; все 31 — прямые (``curve_kinds`` = line). Это ровно тот
    класс дефекта, ради которого заведена причина ``source_contract_gap``:
    оп есть, чтение есть, а провода между ними нет.

    ЧТО ОСТАЁТСЯ ОТКАЗОМ И ПОЧЕМУ (границы не переехали):

    * ЛЕСТНИЧНОЕ ограждение (``has_host``) — позиция установки
      (``RailingPlacementPosition``) НЕЧИТАЕМА: во всём член-составе
      ``Autodesk.Revit.DB.Architecture.Railing`` на всех шести версиях
      геттера нет, она существует только как аргумент ``Create`` и как три
      поля перечисления. Переложить такое ограждение в ``variety=path``
      значило бы МОЛЧА ПОТЕРЯТЬ ХОЗЯИНА: на вид то же место, а лестница
      больше не владеет своим ограждением.
    * ДУГА в пути — у ``create_railing`` нет дугового параметра, а хорда
      это другое ограждение.
    * ПЛОСКОСТЬ ПУТИ ВЫШЕ/НИЖЕ УРОВНЯ — ``Railing.Create(doc, CurveLoop,
      typeId, baseLevelId)`` кладёт путь на уровень, смещения у операции нет.

    * СЛЕПОК БЕЗ СТАДИИ — прежний отказ ДОСЛОВНО (см. первую ветку ниже).
    """
    raw = context.railing_path_index.get(element.element_id)
    if raw is None:
        # СЛЕПОК СНЯТ ДО СТАДИИ ЗАХВАТА — прежний ответ ДОСЛОВНО. Обе строки
        # ниже не трогать: разбор, снятый до 29.07, обязан дать тот же отказ
        # с той же причиной, а не новый.
        if element.host_id:
            # Хозяин известен — но одного хозяина мало: перегрузка
            # Railing.Create(doc, hostId, typeId, position) требует ПОЗИЦИЮ, а
            # она в L0 не снимается ничем. Ставить Treads по умолчанию значило
            # бы поставить ограждение не туда молча.
            _refuse(
                AtomReason.MISSING_PARAMETER,
                "frozen L0 carries no RailingPlacementPosition for a hosted "
                "railing (host is known, placement side is not)")
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "frozen L0 has no railing path and no host id "
            "(ограждение в слепке — только габарит)")
    try:
        record = RailingPathRecord.from_dict(
            element.element_id, raw,
            f"railing_path_index[{element.element_id!r}]")
    except SketchPayloadError as exc:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            f"railing side-index row is invalid: {exc}")
    if record.has_host is True or record.host_id or element.host_id:
        # Позиция установки НЕЧИТАЕМА: полный член-состав
        # Autodesk.Revit.DB.Architecture.Railing на всех шести версиях не
        # содержит геттера RailingPlacementPosition — она встречается только
        # как аргумент двух перегрузок Create и как три поля перечисления.
        # Перекладывать лестничное ограждение в variety=path значило бы
        # ПОТЕРЯТЬ хозяина молча: ограждение перестало бы принадлежать
        # лестнице, оставшись на вид на месте.
        _refuse(
            AtomReason.MISSING_PARAMETER,
            "hosted railing has no readable RailingPlacementPosition "
            "(Railing exposes no getter on any shipped version)")
    if record.has_host is None:
        # `None` — «ПРОЧИТАТЬ НЕ УДАЛОСЬ», и запись заведена трёхзначной
        # именно затем, чтобы это не схлопнулось в «хозяина нет». Свободное
        # ограждение из неизвестности — это молчаливая потеря хозяина ровно
        # той же ценой, что и ветка выше; поэтому здесь отказ, а не `not`.
        _refuse(
            AtomReason.MISSING_METADATA,
            "railing host state was not read (unknown is not 'no host')")
    if not record.path_available or record.path is None:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "railing side index read no path for this railing")
    path = record.path
    if any(kind is not CurveKind.LINE for kind in path.curve_kinds):
        _refuse(
            AtomReason.CURVE_KIND_UNSUPPORTED,
            "create_railing path has no arc parameter and a chord would be "
            "a different railing")
    if not (_geom.MIN_PATH_POINTS <= len(path.points_mm) <= _geom.MAX_PATH_POINTS):
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"create_railing path holds {_geom.MIN_PATH_POINTS}.."
            f"{_geom.MAX_PATH_POINTS} points "
            f"(this railing has {len(path.points_mm)})")
    # Вырожденное звено отказывает ВПЕРЁД (authoring_validation, порог 1 мм:
    # Revit такую кривую не строит). Поймать здесь — значит отдать честный
    # атом вместо программы, которую компилятор всё равно отвергнет.
    if any(math.dist(path.points_mm[i], path.points_mm[i + 1]) < 1.0
           for i in range(len(path.points_mm) - 1)):
        _refuse(
            AtomReason.INVALID_VALUE,
            "railing path has a segment shorter than 1 mm "
            "(Revit does not build such a curve)")
    if not record.base_level_id:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "create_railing(variety=path) has no base level and none can be "
            "derived — STAIRS_RAILING_BASE_LEVEL_PARAM was not read")
    level = context.levels_by_id.get(record.base_level_id)
    if level is None or not level.name:
        _refuse(
            AtomReason.MISSING_METADATA,
            "railing base level metadata is absent")
    # ОТМЕТКА ПЛОСКОСТИ ПУТИ. Railing.Create(doc, CurveLoop, typeId,
    # baseLevelId) кладёт путь НА УРОВЕНЬ; смещения от уровня у операции нет
    # ни одного параметра. Ограждение, чья плоскость от уровня отстоит,
    # приехало бы обратно на другой отметке — молча и незаметно (у башни в 59
    # этажей контур был бы правильный). Замер K2: у всех 28 свободных
    # ограждений разбора plane_z ровно равна отметке уровня, то есть отказ
    # ниже честный, а не запретительный.
    if record.plane_z_mm is None:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "railing path plane elevation was not read")
    # Сетка ОДНА — та же CANON_MM, на которой канон округляет каждое поле
    # ``*_mm``. Заводить свой порог значило бы завести второго судью о том,
    # что считать «той же отметкой».
    if abs(record.plane_z_mm - level.elevation_mm) > CANON_MM:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "railing path plane is offset from its base level and "
            "create_railing has no offset parameter "
            f"({record.plane_z_mm - level.elevation_mm:+.1f} mm)")
    params: dict[str, Any] = {
        "variety": "path",
        "path": [[float(x), float(y)] for x, y in path.points_mm],
        "level": _level_ref(level.id, level.name),
        "type": _catalog_ref(element),
    }
    return _op_node(element, "create_railing", params)


def _lift_roof(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    outline, holes = _closed_profile(
        element,
        context,
        "frozen L0 has no reliable roof Sketch profile or slope semantics",
    )
    if holes:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "create_roof has no exact hole-loop parameter")
    params: dict[str, Any] = {
        "outline": outline,
        "level": _level_ref(element.level_id, element.level_name),
        "type": _catalog_ref(element),
    }
    # The pitch, already matched onto this very outline's edges by geometry at
    # extraction time.  Only stated when some edge is actually sloped: a flat
    # roof keeps its historical params and canon hash, and create_roof refuses
    # an all-null list precisely because that is a flat roof asking to be
    # written as one.  A length that disagrees with the outline would pitch the
    # wrong edges, so it is an honest atom instead.
    # The index holds raw wire rows; _closed_profile above already validated
    # this one, so parsing it again is total.
    record = ProfileIndexRecord.from_dict(
        element.element_id,
        context.profile_index.get(element.element_id),
        f"profile_index[{element.element_id!r}]",
    )
    pitches = record.slopes or ()
    if any(p is not None for p in pitches):
        if len(pitches) != len(outline):
            _refuse(
                AtomReason.UNSUPPORTED_SIGNATURE,
                "roof slope list does not align with its outline")
        params["slopes"] = [None if p is None else float(p) for p in pitches]
    return _op_node(element, "create_roof", params)


def _lift_column(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    # A SLANTED column is a LocationCURVE, not a point.  L0 already records it
    # that way -- ``geom_kind == CURVE`` with both endpoints -- but _point()
    # refuses anything that is not a point, so every slanted column became an
    # atom before its lifter ran a single line.  Take the base from the near
    # end instead, and the top from the far one.
    top_xy = None
    if element.geom_kind is GeometryKind.CURVE:
        near, far = element.p0_mm, element.p1_mm
        if not (isinstance(near, (list, tuple)) and len(near) >= 3
                and isinstance(far, (list, tuple)) and len(far) >= 2):
            _refuse(
                AtomReason.MISSING_GEOMETRY,
                "slanted column is missing an endpoint in frozen L0")
        point = [float(near[0]), float(near[1]), float(near[2])]
        top_xy = [float(far[0]), float(far[1])]
    else:
        point = _point(element)
    rotation = _finite(element.rotation_deg)
    if rotation is None:
        if top_xy is None:
            _refuse(
                AtomReason.MISSING_GEOMETRY,
                "column LocationPoint rotation is absent from frozen L0")
        # The axis carries the orientation; the op's own default stands.
        rotation = 0.0
    # Preserve the measured L0 angle rather than rewriting it to an equivalent
    # turn; the forward postcondition performs the modulo-360 comparison.
    rotation = float(rotation)
    if rotation == 0.0:  # canonicalize -0.0 for stable JSON.
        rotation = 0.0
    category = (
        "structural"
        if element.category == "OST_StructuralColumns"
        else "architectural"
    )
    params: dict[str, Any] = {
        "xy": [point[0], point[1]],
        "level": _level_ref(element.level_id, element.level_name),
        "category": category,
        "symbol": _catalog_ref(element),
        "rotation_deg": rotation,
    }
    if top_xy is not None:
        params["top_xy"] = top_xy
    # P1 DOF-completeness (fidelity audit 2026-07-21): столбовая вертикаль —
    # та же дисциплина, что у стены (порог 1мм, отсутствие = историческая
    # байт-идентичная эмиссия; неразрешимый top-уровень = честный атом).
    base_offset = _finite(element.params.get("FAMILY_BASE_LEVEL_OFFSET_PARAM"))
    if base_offset is not None and abs(base_offset) >= 1.0:
        params["base_offset_mm"] = _bounded_param(
            element, "FAMILY_BASE_LEVEL_OFFSET_PARAM", "create_column",
            "base_offset_mm")
    top_level_id = element.params.get("FAMILY_TOP_LEVEL_PARAM")
    if top_level_id is not None:
        if not isinstance(top_level_id, str):
            _refuse(
                AtomReason.MISSING_METADATA,
                "FAMILY_TOP_LEVEL_PARAM is not an element-id string")
        top = context.levels_by_id.get(top_level_id)
        if top is None:
            _refuse(
                AtomReason.MISSING_METADATA,
                "FAMILY_TOP_LEVEL_PARAM does not resolve to an extracted level")
        params["top_level"] = {
            "by": "name", "value": top.name, "_id": top.id}
        top_offset = _finite(
            element.params.get("FAMILY_TOP_LEVEL_OFFSET_PARAM"))
        if top_offset is not None and abs(top_offset) >= 1.0:
            params["top_offset_mm"] = _bounded_param(
                element, "FAMILY_TOP_LEVEL_OFFSET_PARAM", "create_column",
                "top_offset_mm")
    if top_xy is not None and "top_level" not in params:
        # create_column refuses a slant with no top level, and rightly: the
        # upper end would have no elevation.  Emitting one anyway would hand
        # the rebuild a program the compiler rejects, so this is an atom.
        _refuse(
            AtomReason.MISSING_METADATA,
            "slanted column has no resolvable FAMILY_TOP_LEVEL_PARAM")
    return _op_node(element, "create_column", params, anchor=point)


def _lift_beam(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _curve(element, dimensions=3)
    # Балка ЧИТАЕТ боковой curve-индекс. Раньше эта функция принимала контекст
    # и не открывала его: дуговая балка ехала хордой при том, что стадия
    # ``curve`` запрашивает OST_StructuralFraming наравне со стенами и её
    # точная дуга уже лежала в curve.index.json.
    _refuse_non_line_curve(element, context, "create_beam")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "symbol": _catalog_ref(element),
    }
    return _op_node(element, "create_beam", params)


def _lift_text(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Текстовое примечание -> ``create_text``.

    ВСЕ три обязательных входа приходят из бокового индекса оформления, ни
    один — из строки L0: вид-владелец (``Element.OwnerViewId``), точка в
    КООРДИНАТАХ ВИДА и сам текст (``TextElement.Text``). Точка спроецирована
    на мосту той же формулой, которой прямой ход материализует её обратно
    (``docspace.emit_view2d_to_xyz_cs``), поэтому круг замыкается тождеством, а
    не совпадением.

    Индекса нет -> прежний ОТКАЗ дословно. Это не осторожность, а условие
    сравнимости: все слепки, снятые до появления стадии, обязаны давать тот же
    атом с той же причиной, иначе история покрытия перестанет быть историей.
    """
    record = context.text_notes.get(element.element_id)
    if not record:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_text"))

    view_id = record.get("owner_view_id")
    view_name = record.get("owner_view_name")
    at = record.get("at_view_mm")
    content = record.get("content")
    if not view_id or not view_name \
            or not isinstance(at, (list, tuple)) or len(at) != 2:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            "боковой индекс оформления принёс запись без вида, без его "
            "имени или без точки вида "
            f"(element_id={element.element_id!r})")
    if not isinstance(content, str) or not content:
        # Пустой текст — не «пустая строка по умолчанию», а отсутствие
        # содержания: create_text требует content, и подставлять "" значило бы
        # выдумать источник.
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            f"текстовое примечание без содержания (element_id={element.element_id!r})")

    # ЕДИНСТВЕННЫЙ именованный диалект ссылок L1: {by:"name", value, _id}.
    # Формы «по element_id» в L1 не существует, и это не ограничение, а
    # свойство: пересборка ищет объект ПО ИМЕНИ, а id держит как улику
    # того, чем он был в исходном документе.
    params: dict[str, Any] = {
        "in_view": {"by": "name", "value": str(view_name), "_id": str(view_id)},
        "at": [float(at[0]), float(at[1])],
        "content": content,
    }
    type_id = record.get("type_id")
    type_name = record.get("type_name")
    if type_id and type_name:
        params["text_type"] = {
            "by": "name", "value": str(type_name), "_id": str(type_id)}
    return _op_node(element, "create_text", params)


def _lift_tag(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Марка -> ``create_tag``.

    ВСЕ три обязательных входа приходят из бокового индекса марок, ни один —
    из строки L0: вид-владелец (``Element.OwnerViewId``), точка ГОЛОВЫ в
    координатах вида (``TagHeadPosition``, спроецированная на мосту базисом
    вида) и ПОМЕЧЕННЫЙ элемент (``TaggedLocalElementId`` до 2022 /
    ``GetTaggedLocalElementIds`` с 2022 — шов, разведённый в ``tag_extract``).

    ПЯТЬ ОТКАЗОВ, КОТОРЫХ ЭТОТ ЛИФТЕР НЕ ИМЕЕТ ПРАВА ИЗБЕЖАТЬ.

    1. Индекса нет -> прежний ``source_contract_gap`` ДОСЛОВНО. Это не
       осторожность, а условие сравнимости: все слепки, снятые до появления
       стадии, обязаны давать тот же атом с той же причиной.
    2. Помеченного элемента нет среди прочитанных -> ``missing_reference``
       с ЕГО id в тексте. Молча привязать марку к похожему элементу — худшее,
       что здесь можно сделать: это прошло бы схему L1 и выглядело бы
       покрытием, а на деле было бы выдуманным источником (§18.1).
    3. Марка помещения/площади/пространства — ``SpatialElementTag``, а
       прямой ход умеет РОВНО ``IndependentTag.Create``
       (``authoring._emit_tag``). Пересборка построила бы не тот класс
       элемента, и это ``unsupported_forward_signature``, а не «почти то же».
    4. Марка С ВЫНОСКОЙ: у ``IndependentTag.Create`` седьмой аргумент для
       такой марки означает КОНЕЦ ВЫНОСКИ, а не голову (дословная строка
       Autodesk, одинаковая в 2021 и 2026), а прочитана голова.
    5. Повёрнутая марка: эмиттер вшивает ``TagOrientation.Horizontal``
       безусловно. Выпрямление не видно сравнению по положению головы —
       значит, оно обязано быть НАЗВАНО здесь, а не обнаружено потом.
    """
    record = context.tags.get(element.element_id)
    if not record:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_tag"))

    view_id = record.get("owner_view_id")
    view_name = record.get("owner_view_name")
    at = record.get("at_view_mm")
    target_id = record.get("tagged_element_id")
    if not view_id or not view_name \
            or not isinstance(at, (list, tuple)) or len(at) != 2 \
            or not target_id:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            "боковой индекс марок принёс запись без вида, без его имени, "
            "без точки вида или без помеченного элемента "
            f"(element_id={element.element_id!r})")

    if record.get("tag_family") != TAG_FAMILY_INDEPENDENT:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"марка рода {record.get('tag_family')!r} — это "
            "SpatialElementTag (помещение/площадь/пространство), а прямой "
            "ход строит марку единственным способом, IndependentTag.Create; "
            "пересборка дала бы элемент другого класса, а не эту марку")

    # ВЫНОСКА МЕНЯЕТ СМЫСЛ САМОЙ ТОЧКИ, и это не наша догадка, а дословная
    # строка Autodesk про седьмой аргумент ``IndependentTag.Create`` — одна и
    # та же в 2021 и в 2026, в обеих перегрузках (RevitAPI.xml, param "pnt"):
    #
    #   "For tags without leaders, this point is the position of the tag head.
    #    For tags with leaders, this point is the end point of the leader, and
    #    a leader of default length will be created from this point to the
    #    tag head."
    #
    # То есть `at` — это ГОЛОВА только у марки без выноски. Стадия читает
    # ``TagHeadPosition``, и для марки С выноской пересборка поставила бы
    # КОНЕЦ ВЫНОСКИ туда, где была голова, а голову увела бы на длину
    # выноски по умолчанию. Сдвиг молчаливый: сравнение по положению головы
    # его не видит, и марка засчиталась бы покрытием.
    #
    # Читать конец выноски нечем без новой волны: ``GetLeaderEnd`` НЕТ в 2021
    # (индекс ловушек: NEW IN 2022) и с 2023 он документированно бросает,
    # когда выноска не свободного конца или не видна. Это спецификация
    # следующей волны, а сегодня — названный отказ.
    if record.get("leader"):
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "у марки есть выноска, а `at` опа — это седьмой аргумент "
            "IndependentTag.Create, который для марки С ВЫНОСКОЙ означает "
            "КОНЕЦ ВЫНОСКИ, а не голову (RevitAPI.xml, param pnt, 2021-2026); "
            "прочитан же TagHeadPosition — пересборка увела бы голову на "
            "длину выноски по умолчанию, и сравнение по голове этого не "
            "заметило бы")

    orientation = record.get("orientation")
    if orientation != TAG_ORIENTATION_HORIZONTAL:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"ориентация марки {orientation!r} не выражается: у create_tag "
            "нет такого параметра, и эмиттер ставит "
            f"TagOrientation.{TAG_ORIENTATION_HORIZONTAL} безусловно — "
            "пересборка выпрямила бы марку молча")

    target_node = nodes_by_source.get(str(target_id))
    if target_node is None:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            f"помеченный элемент {str(target_id)!r} не найден среди "
            "прочитанных: марку нельзя привязать ни к чему другому — "
            "«похожий элемент» не тот же элемент")

    # ССЫЛКА ВНУТРИПРОГРАММНАЯ, как host у двери: пересборка обязана связать
    # два УЗЛА, а не запомнить чужой ElementId. Узел цели может быть и атомом
    # — тогда ссылка честно указывает на нечто непостроенное, и это видно.
    #
    # Выноски НЕТ в параметрах, и это не упущение: `at` без ключа `leader`
    # прямой эмиттер читает ровно как «без выноски» (`op.get("leader")`), а
    # марка С выноской сюда не доходит вовсе — см. отказ выше.
    params: dict[str, Any] = {
        "in_view": {"by": "name", "value": str(view_name), "_id": str(view_id)},
        "target": {"ref": target_node["_id"]},
        "at": [float(at[0]), float(at[1])],
    }
    type_id = record.get("type_id")
    type_name = record.get("type_name")
    if type_id and type_name:
        params["tag_type"] = {
            "by": "name", "value": str(type_name), "_id": str(type_id)}
    return _op_node(element, "create_tag", params)


def _lift_dimension(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Размер -> ``create_dimension``.

    ВСЕ три обязательных входа приходят из бокового индекса размеров, ни один
    — из строки L0: вид-владелец (``Element.OwnerViewId``), точка НА ЛИНИИ
    размера в координатах вида и ЭЛЕМЕНТЫ, между которыми он проведён
    (``Dimension.References`` -> ``Reference.ElementId``).

    ПОЧЕМУ ТОЧКА РОВНО ОДНА И ЭТОГО ДОВОЛЬНО. У прямого хода ``line_at`` —
    ЯКОРЬ, через который проходит линия; направление он берёт из нормали
    первой ссылки. ``Dimension.Curve`` документирована ВСЕГДА неограниченной,
    и положение вдоль линии эмерджентно (``authoring._emit_dimension``).
    Значит любая точка на линии замыкает круг тождеством, а не совпадением.

    ЧЕТЫРЕ ОТКАЗА, КОТОРЫХ ЭТОТ ЛИФТЕР НЕ ИМЕЕТ ПРАВА ИЗБЕЖАТЬ.

    1. Индекса нет -> прежний ``source_contract_gap`` ДОСЛОВНО, тем же
       текстом из реестра. Условие сравнимости: все слепки, снятые до
       появления стадии, обязаны давать тот же атом с той же причиной, иначе
       история покрытия перестанет быть историей.
    2. Форма размера не ЛИНЕЙНАЯ -> ``unsupported_forward_signature``. Прямой
       ход строит размер РОВНО одним способом,
       ``doc.Create.NewDimension(view, Line, ReferenceArray)``, и это линейный
       размер. Радиальный/угловой/дуговой пересобрался бы не тем, чем был.
    3. Хоть один измеряемый элемент не найден среди прочитанных ->
       ``missing_reference`` С ЕГО id в тексте. Молча выкинуть ссылку или
       подставить похожий элемент — худшее, что здесь можно сделать: размер
       между ДРУГИМИ элементами прошёл бы схему L1 и выглядел бы покрытием,
       а на деле был бы другим числом (§18.1).
    4. Ссылок меньше двух -> ``source_contract_gap``: измерять нечего.

    ЧЕГО ЭТОТ ЛИФТЕР НЕ ОБЕЩАЕТ, И ЭТО НАЗВАНО, А НЕ СПРЯТАНО. ``refs`` несёт
    ЭЛЕМЕНТЫ, а ``NewDimension`` требует ГЕОМЕТРИЧЕСКИХ ссылок; КАКУЮ ГРАНЬ
    взять, решает прямой ход своим обходом. Значит совпадение ЧИСЛА после
    пересборки этим лифтером не гарантировано и не может быть гарантировано
    ничем, что читается offline. Прямой ход гейтит измеренное значение сам
    (``_emit_dimension``, 09.08), поэтому расхождение станет его типизированным
    отказом, а не молчаливым покрытием.
    """
    record = context.dimensions.get(element.element_id)
    if not record:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_dimension"))

    view_id = record.get("owner_view_id")
    view_name = record.get("owner_view_name")
    at = record.get("line_at_view_mm")
    refs = record.get("ref_element_ids")
    if not view_id or not view_name \
            or not isinstance(at, (list, tuple)) or len(at) != 2 \
            or not isinstance(refs, (list, tuple)):
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            "боковой индекс размеров принёс запись без вида, без его имени, "
            "без точки вида или без измеряемых элементов "
            f"(element_id={element.element_id!r})")
    if len(refs) < 2:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            f"размер связан с {len(refs)} элементом(ами) — измерять нечего "
            f"(element_id={element.element_id!r})")

    shape = record.get("dimension_shape")
    if shape != DIMENSION_SHAPE_LINEAR:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"форма размера {shape!r} не выражается: прямой ход строит размер "
            "единственным способом, doc.Create.NewDimension(view, Line, "
            f"ReferenceArray), а это {DIMENSION_SHAPE_LINEAR}-размер; "
            "пересборка дала бы размер другого рода, а не этот")

    # ССЫЛКИ ВНУТРИПРОГРАММНЫЕ, как host у двери и target у марки: пересборка
    # обязана связать УЗЛЫ, а не запомнить чужой ElementId. Узел цели может
    # быть и атомом — тогда ссылка честно указывает на непостроенное, и это
    # видно, а не спрятано.
    ref_selectors: list[dict[str, Any]] = []
    for ref_id in refs:
        ref_node = nodes_by_source.get(str(ref_id))
        if ref_node is None:
            _refuse(
                AtomReason.MISSING_REFERENCE,
                f"измеряемый элемент {str(ref_id)!r} не найден среди "
                "прочитанных: размер нельзя перевесить ни на что другое — "
                "«похожий элемент» не тот же элемент, и число вышло бы другое")
        ref_selectors.append({"ref": ref_node["_id"]})

    params: dict[str, Any] = {
        "in_view": {"by": "name", "value": str(view_name), "_id": str(view_id)},
        "refs": ref_selectors,
        "line_at": [float(at[0]), float(at[1])],
    }
    type_id = record.get("type_id")
    type_name = record.get("type_name")
    if type_id and type_name:
        params["dim_type"] = {
            "by": "name", "value": str(type_name), "_id": str(type_id)}
    return _op_node(element, "create_dimension", params)


def _lift_foundation(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    # ЛЕНТОЧНЫЙ ФУНДАМЕНТ — НЕ СТОЛБЧАТЫЙ БАШМАК, И ТЕПЕРЬ ЭТО ПРОВЕРЯЕТСЯ.
    #
    # `reverse_contract` про `create_wall_foundation` обещает: такой элемент —
    # типизованный атом, НИКОГДА не переизлучаемый молча как столбчатый. До
    # этой волны обещание держалось не кодом, а поведением Revit: у
    # `WallFoundation` нет `LocationPoint`, значит `geom_kind` не станет
    # POINT, значит ветка ниже не выполнится. Совпадение, а не инвариант — тот
    # же класс, что тест, проходящий по фикстуре.
    #
    # Проверка стоит ДО разбора геометрии намеренно: она о КЛАССЕ элемента, а
    # не о том, что Revit положил в его геометрию, и обязана держаться, даже
    # если завтра у ленты появится точка.
    #
    # РАЗЛИЧИТЕЛЬ — `host_source`, а не «хозяин вообще есть». Отказ по
    # непустому `host_id` отверг бы башмак на грани или рабочей плоскости —
    # ровно тот элемент, ради которого ветка `isolated` и написана, — то есть
    # купил бы честность ценой рабочего покрытия. В замороженном L0 непустой
    # `host_id` вдобавок ДОКАЗЫВАЕТ `FamilyInstance`: другая ветка его не
    # заполняла. Поэтому старый слепок обязан дать прежний ответ дословно, и
    # `host_source is None` («не мерили») отказом не является.
    #
    # ПОЧЕМУ `NO_LIFTER`, А НЕ `SOURCE_CONTRACT_GAP`. Причина обязана быть
    # самой верной, а не первой подходящей, и адресует она РАБОТУ. До волны
    # захвата не хватало ЧТЕНИЯ (`WallFoundation.WallId` не читался вовсе) —
    # тогда верен был бы source-gap. Теперь чтение приносит и стену, и класс,
    # `create_wall_foundation` лежит в `spec.OPS`, и единственное недостающее
    # звено — САМ ЛИФТЕР. `source_contract_gap` послал бы чинить чтение,
    # которое уже починено.
    #
    # Причина НЕ входит в `_SHAPE_REFUSALS` — и это тоже решение: форменный
    # отказ отдал бы ленту `place_family`, а это не «частичный успех», а
    # потеря объекта. Сегодняшний ответ на bbox-фундамент (`MISSING_GEOMETRY`)
    # форменный, то есть ровно эту дорогу и открывал.
    if element.host_source is HostSource.WALL_FOUNDATION:
        _refuse(
            AtomReason.NO_LIFTER,
            "ленточный фундамент (host_source=wall_foundation): "
            "create_wall_foundation есть в реестре и захват приносит его "
            "стену, но лифтера под него нет; create_foundation выразить его "
            "не может — ни точки, ни контура у него нет")
    if element.geom_kind is GeometryKind.POINT:
        point = _point(element)
        rotation = _finite(element.rotation_deg)
        if rotation is None or math.remainder(rotation, 360.0) != 0.0:
            _refuse(
                AtomReason.UNSUPPORTED_SIGNATURE,
                "live create_foundation cannot reproduce footing rotation")
        params: dict[str, Any] = {
            "variety": "isolated",
            "xy": [point[0], point[1]],
            "symbol": _catalog_ref(element),
            "level": _level_ref(element.level_id, element.level_name),
        }
        return _op_node(
            element, "create_foundation", params, anchor=point)

    # System foundation slabs have no LocationPoint/LocationCurve in frozen
    # L0. A curve-based foundation may instead be a wall/strip/grillage
    # foundation whose semantics create_foundation(variety="slab") cannot
    # prove, even if an unrelated side-index row is supplied.
    if element.geom_kind is not GeometryKind.BBOX_ONLY:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "foundation slab needs a Sketch profile; only point footing is invertible")

    outline, holes = _closed_profile(
        element,
        context,
        "foundation slab needs a Sketch profile; only point footing is invertible",
        polygon_op="create_foundation",
    )
    if holes:
        try:
            supports_holes = (
                context.revit_version is not None
                and int(context.revit_version) >= 2022
            )
        except ValueError:
            supports_holes = False
        if not supports_holes:
            _refuse(
                AtomReason.UNSUPPORTED_SIGNATURE,
                "foundation slab holes require the Revit 2022+ forward path")
    params: dict[str, Any] = {
        "variety": "slab",
        "outline": outline,
        "type": _catalog_ref(element),
        "level": _level_ref(element.level_id, element.level_name),
    }
    if holes:
        params["holes"] = holes
    return _op_node(element, "create_foundation", params)


def _arc_host_offset(
    insertion: Vec3,
    p0: Sequence[float],
    p1: Sequence[float],
    arc: Mapping[str, Any],
) -> tuple[float, float]:
    """Return (distance from p0 along Arc, total Arc length), in millimetres."""

    try:
        center = arc["center_mm"]
        radius = float(arc["radius_mm"])
        x_axis = arc["x_axis"]
        y_axis = arc["y_axis"]
        start = float(arc["start_angle_rad"])
        end = float(arc["end_angle_rad"])
        span = end - start
        if radius <= 0.0 or span <= 0.0 or span > math.tau + 1e-9:
            raise ValueError
        endpoint_rows: list[tuple[float, float]] = []
        for angle in (start, end):
            ca, sa = math.cos(angle), math.sin(angle)
            endpoint_rows.append((
                float(center[0]) + radius * (
                    ca * float(x_axis[0]) + sa * float(y_axis[0])),
                float(center[1]) + radius * (
                    ca * float(x_axis[1]) + sa * float(y_axis[1])),
            ))
        vx = float(insertion[0]) - float(center[0])
        vy = float(insertion[1]) - float(center[1])
        phase = math.atan2(
            vx * float(y_axis[0]) + vy * float(y_axis[1]),
            vx * float(x_axis[0]) + vy * float(x_axis[1]))
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        _refuse(AtomReason.MISSING_GEOMETRY, "host wall Arc is malformed")

    turns = round((start - phase) / math.tau)
    candidates = [phase + (turns + shift) * math.tau
                  for shift in (-1, 0, 1)]
    param_tol = 1.0 / radius
    inside = [value for value in candidates
              if start - param_tol <= value <= end + param_tol]
    if not inside:
        _refuse(
            AtomReason.INVALID_VALUE,
            "hosted insertion projects outside the host Arc")
    parameter = min(
        inside,
        key=lambda value: abs(min(max(value, start), end) - value))
    parameter = min(max(parameter, start), end)
    p0xy = (float(p0[0]), float(p0[1]))
    p0_is_start = _distance(endpoint_rows[0], p0xy) <= _distance(
        endpoint_rows[1], p0xy)
    offset = (radius * (parameter - start) if p0_is_start
              else radius * (end - parameter))
    length = radius * span
    return min(max(offset, 0.0), length), length


def _host_offset(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> tuple[float, L1Node]:
    insertion = _point(element)
    if not element.host_id:
        _refuse(AtomReason.MISSING_REFERENCE, "host_id is absent")
    host = context.elements_by_id.get(element.host_id)
    if host is None or host.category != "OST_Walls":
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "host_id does not resolve to an extracted wall")
    if (host.geom_kind is not GeometryKind.CURVE
            or host.p0_mm is None or host.p1_mm is None):
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "host wall has no curve for exact offset projection")
    arc = _wall_arc_param(host, context, list(host.p0_mm), list(host.p1_mm))
    if arc is not None:
        offset, length = _arc_host_offset(
            insertion, host.p0_mm, host.p1_mm, arc)
    else:
        dx = host.p1_mm[0] - host.p0_mm[0]
        dy = host.p1_mm[1] - host.p0_mm[1]
        length = math.hypot(dx, dy)
        if length < 1.0:
            _refuse(
                AtomReason.INVALID_VALUE,
                "host wall curve is shorter than the forward 1 mm limit")
        offset = (
            (insertion[0] - host.p0_mm[0]) * dx
            + (insertion[1] - host.p0_mm[1]) * dy
        ) / length
    if offset < 0.0 or offset > length:
        _refuse(
            AtomReason.INVALID_VALUE,
            "projected insertion lies outside the host wall segment")
    host_node = nodes_by_source.get(host.element_id)
    if host_node is None:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "host wall has no corresponding L1 node")
    return offset, host_node


def _host_level_sill(
    element: L0Element,
    context: _Context,
    insertion: Vec3,
) -> float:
    """Vertical anchor of a hosted element, measured from the HOST WALL's level.

    The forward emitter (`authoring._emit_hosted`) places a hosted instance at
    ``host_wall.LevelId.Elevation + sill`` — so the ONLY faithful sill basis is
    the host wall's own level, never the hosted element's schedule level (audit
    F1: on a multi-storey/facade wall the two differ and a window-level-based
    sill silently rebuilt the instance on the wrong storey).  Sub-millimetre
    negative noise clamps to 0.

    A genuinely NEGATIVE sill is ordinary, not an error — this docstring used to
    claim the opposite and ``create_door.sill_mm`` carried ``min_val=0`` to
    enforce it.  Measured on SOB6.2_UPO_L_DOO_AR_R23: 140 of 151 doors are
    negative, 131 of them at exactly -100 mm.  The wall's own
    ``WALL_BASE_OFFSET`` is -150, so the wall body starts below its level and a
    door at the finished floor lands below that level while remaining wholly
    inside the wall.  The old bound rejected reality and atomised 92.7% of the
    building's doors.
    """

    host = context.elements_by_id.get(element.host_id or "")
    if host is None:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "host_id does not resolve to an extracted wall")
    host_level = _matching_level(context, host.level_id, host.level_name)
    sill = insertion[2] - host_level.elevation_mm
    if -1.0 < sill < 0.0:
        sill = 0.0
    return sill


def _hosted_flip_params(
    element: L0Element,
    context: _Context,
) -> dict[str, bool]:
    """Swing/mirror state of a hosted door/window from the placement index.

    audit F5: the FamilyInstance placement side index already reads
    ``mirrored``/``hand_flipped``/``facing_flipped`` (and ``host_id``) for
    EVERY instance, hosted included — hosted rows were simply never consumed.
    Returns ``{}`` (the exact pre-existing lift, canonical hashes byte-stable)
    when the index is absent, the row is missing/malformed, or its ``host_id``
    disagrees with frozen L0 — contradictory side data is ignored, never
    trusted (the same fail-closed-to-old-behaviour precedent as
    ``_wall_arc_param``'s malformed-arc rule).  When ALL flags are False the
    default placement already matches, so nothing is emitted (absent ==
    default, exactly like the door's optional ``sill_mm``).  When ANY flag is
    True, ALL THREE are emitted explicitly: mirroring can flip hand/facing
    state as a side effect in Revit, so the emitter must enforce the COMPLETE
    requested state, including the False flags.
    """

    raw = context.family_placement_index.get(element.element_id)
    if raw is None:
        if context.family_placement_requested:
            _refuse(
                AtomReason.FLIP_STATE_UNKNOWN,
                "requested family placement evidence is missing for hosted "
                "instance: "
                + _placement_absence_detail(element.element_id, context))
        return {}
    try:
        record = FamilyPlacementRecord.from_dict(
            element.element_id,
            raw,
            f"family_placement_index[{element.element_id!r}]",
        )
    except FamilyPlacementPayloadError as exc:
        if context.family_placement_requested:
            _refuse(
                AtomReason.FLIP_STATE_UNKNOWN,
                f"hosted family placement evidence is invalid: {exc}")
        return {}
    if record.host_id is not None and element.host_id \
            and record.host_id != element.host_id:
        if context.family_placement_requested:
            _refuse(
                AtomReason.FLIP_STATE_UNKNOWN,
                "hosted family placement host_id contradicts frozen L0")
        return {}
    if not (record.mirrored or record.hand_flipped or record.facing_flipped):
        return {}
    return {
        "mirrored": record.mirrored,
        "hand_flipped": record.hand_flipped,
        "facing_flipped": record.facing_flipped,
    }


def _lift_door(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    # A door that replaces a curtain PANEL has no LocationPoint at all: Revit
    # positions it by the grid cell it occupies, not by a point on a wall.
    # Measured on LOT31: 2 819 of 5 941 doors — 5% of the whole building — are
    # exactly this, one family ("Дверь витражная"), every host in the curtain
    # index.  _point() refused them with "requires point geometry", which
    # reads as lost data and hid a capability gap behind an extraction excuse.
    # create_door takes an insertion point on a host wall and genuinely cannot
    # express a curtain cell, so this stays an atom — but an honest one.
    if _placement_unavailable(element, context):
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "door has no insertion point (curtain-panel door); create_door "
            "places on a host wall and cannot express a curtain grid cell")
    insertion = _point(element)
    offset, host_node = _host_offset(element, context, nodes_by_source)
    # Apply the live forward bound after the exact geometric projection.
    offset = _bounded_number(offset, "create_door", "offset_mm")
    params: dict[str, Any] = {
        "host": {"ref": host_node["_id"]},
        "offset_mm": offset,
        "symbol": _catalog_ref(element),
    }
    # Vertical anchor (audit F1): a door on a multi-storey wall sits ABOVE the
    # wall's base level; the emitter places at host-level + sill (0 when the
    # param is absent), so a non-zero insertion z must be preserved as an
    # explicit sill.  Omitted when < 1mm so the typical per-storey-wall door
    # keeps its historical byte-identical params (canonical hashes stable).
    sill = _host_level_sill(element, context, insertion)
    if abs(sill) >= 1.0:
        params["sill_mm"] = _bounded_number(sill, "create_door", "sill_mm")
    # Swing/mirror state (audit F5): absent/all-False -> byte-stable params.
    params.update(_hosted_flip_params(element, context))
    return _op_node(element, "create_door", params, anchor=insertion)


def _lift_window(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    insertion = _point(element)
    offset, host_node = _host_offset(element, context, nodes_by_source)
    # Sill from the HOST WALL's level — the emitter's placement basis (audit
    # F1).  The window's own schedule level is deliberately NOT used: on a
    # multi-storey wall it names the storey, not the placement datum.
    sill = _host_level_sill(element, context, insertion)
    params: dict[str, Any] = {
        "host": {"ref": host_node["_id"]},
        "offset_mm": _bounded_number(
            offset, "create_window", "offset_mm"),
        "sill_mm": _bounded_number(sill, "create_window", "sill_mm"),
        "symbol": _catalog_ref(element),
    }
    # Swing/mirror state (audit F5): absent/all-False -> byte-stable params.
    params.update(_hosted_flip_params(element, context))
    return _op_node(element, "create_window", params, anchor=insertion)


_ROOM_INTERIOR_MARGIN_MM = 10.0
_ROOM_INTERIOR_PRECISION_MM = 0.5
_ROOM_INTERIOR_MAX_CELLS = 50_000


def _clean_ring(ring: Sequence[Vec2]) -> tuple[Vec2, ...]:
    points = tuple(ring)
    while len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    if len(set(points)) < 3:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "room boundary needs at least three distinct vertices")
    if len(set(points)) != len(points):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "room boundary repeats a non-closing vertex")
    return points


def _canonical_ring(ring: Sequence[Vec2]) -> tuple[Vec2, ...]:
    """Canonical cyclic representation, independent of start and winding."""

    points = _clean_ring(ring)
    start = min(range(len(points)), key=lambda index: points[index])
    forward = points[start:] + points[:start]
    reverse_points = tuple(reversed(points))
    reverse_start = min(
        range(len(reverse_points)), key=lambda index: reverse_points[index])
    reverse = reverse_points[reverse_start:] + reverse_points[:reverse_start]
    return min(forward, reverse)


def _polygon_centroid(ring: Sequence[Vec2]) -> Vec2 | None:
    """Area centroid candidate; concave/holey validity is checked separately."""

    points = tuple(ring)
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    for index, point in enumerate(points):
        nxt = points[(index + 1) % len(points)]
        cross = point[0] * nxt[1] - nxt[0] * point[1]
        area2 += cross
        cx += (point[0] + nxt[0]) * cross
        cy += (point[1] + nxt[1]) * cross
    if area2 == 0.0:
        return None
    centroid = (cx / (3.0 * area2), cy / (3.0 * area2))
    if not all(math.isfinite(value) for value in centroid):
        return None
    return centroid


def _point_in_ring(point: Vec2, points: Sequence[Vec2]) -> bool:
    inside = False
    x, y = point
    previous = points[-1]
    for current in points:
        x0, y0 = previous
        x1, y1 = current
        if ((y0 > y) != (y1 > y)):
            crossing_x = (x1 - x0) * (y - y0) / (y1 - y0) + x0
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def _point_segment_distance(point: Vec2, a: Vec2, b: Vec2) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    length2 = dx * dx + dy * dy
    if length2 == 0.0:
        return math.hypot(point[0] - a[0], point[1] - a[1])
    projection = (
        (point[0] - a[0]) * dx + (point[1] - a[1]) * dy
    ) / length2
    projection = min(1.0, max(0.0, projection))
    nearest = (a[0] + projection * dx, a[1] + projection * dy)
    return math.hypot(point[0] - nearest[0], point[1] - nearest[1])


def _room_clearance(
    point: Vec2,
    exterior: Sequence[Vec2],
    holes: Sequence[Sequence[Vec2]],
) -> float:
    """Signed distance to polygon-with-holes (positive only in its interior)."""

    inside = _point_in_ring(point, exterior) and not any(
        _point_in_ring(point, hole) for hole in holes)
    distance = min(
        _point_segment_distance(
            point, ring[index], ring[(index + 1) % len(ring)])
        for ring in (exterior, *holes)
        for index in range(len(ring))
    )
    return distance if inside else -distance


def _validated_room_rings(
    room: RoomInfo,
) -> tuple[tuple[Vec2, ...], tuple[tuple[Vec2, ...], ...]]:
    exterior_raw = _clean_ring(room.boundary_mm)
    loop_rows = room.boundary_loops_mm
    holes_raw = tuple(_clean_ring(loop) for loop in loop_rows[1:])

    # Reuse the forward contour laws: short edges, self-intersections,
    # touching/outside/nested holes all fail closed before the search.
    from kukai.ir.geom import check_holes_relation, ring_normalize

    diagnostics: list[Any] = []
    exterior_list = ring_normalize(
        list(exterior_raw), room.id, "room.boundary_mm", diagnostics)
    holes_list: list[list[list[float]]] = []
    for index, hole in enumerate(holes_raw):
        normalized = ring_normalize(
            list(hole), room.id,
            f"room.boundary_loops_mm[{index + 1}]", diagnostics)
        if normalized is None:
            break
        holes_list.append(normalized)
    if (exterior_list is None or len(holes_list) != len(holes_raw)
            or not check_holes_relation(
                exterior_list, holes_list, room.id, diagnostics,
                field_prefix="room.holes")):
        detail = (
            diagnostics[0].message_ru
            if diagnostics else "room boundary topology is invalid")
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            detail)
    exterior = _canonical_ring(tuple(
        (float(point[0]), float(point[1])) for point in exterior_list))
    holes = tuple(sorted(
        _canonical_ring(tuple(
            (float(point[0]), float(point[1])) for point in hole))
        for hole in holes_list
    ))
    return exterior, holes


def _room_interior_point(
    exterior: tuple[Vec2, ...],
    holes: tuple[tuple[Vec2, ...], ...],
) -> Vec2:
    """Deterministic branch-and-bound maximum-clearance interior point.

    A cell's centre distance plus its half-diagonal is an upper bound because
    distance to polygon boundaries is 1-Lipschitz.  Subdivision therefore
    terminates with a point within ``_ROOM_INTERIOR_PRECISION_MM`` of the
    global maximum.  The final explicit margin keeps room placement away from
    ambiguous boundaries across Revit versions.
    """

    min_x = min(point[0] for point in exterior)
    min_y = min(point[1] for point in exterior)
    max_x = max(point[0] for point in exterior)
    max_y = max(point[1] for point in exterior)
    width = max_x - min_x
    height = max_y - min_y
    cell_size = min(width, height)
    if (not math.isfinite(cell_size)
            or cell_size <= 2.0 * _ROOM_INTERIOR_MARGIN_MM):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "room has no provable interior clearance from its boundary")

    count_x = int(math.ceil(width / cell_size))
    count_y = int(math.ceil(height / cell_size))
    if count_x * count_y > _ROOM_INTERIOR_MAX_CELLS:
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "room interior search exceeds the deterministic cell budget")

    half = cell_size / 2.0
    diagonal = math.sqrt(2.0)
    heap: list[tuple[float, float, float, float, float]] = []

    def push(x: float, y: float, half_size: float) -> None:
        distance = _room_clearance((x, y), exterior, holes)
        upper_bound = distance + half_size * diagonal
        # Max-priority via the negated bound.  Coordinates are deterministic
        # tie-breakers, so equal-clearance symmetric rooms never depend on
        # heap insertion or input traversal order.
        heapq.heappush(
            heap, (-upper_bound, x, y, half_size, distance))

    for x_index in range(count_x):
        for y_index in range(count_y):
            push(
                min_x + (x_index + 0.5) * cell_size,
                min_y + (y_index + 0.5) * cell_size,
                half,
            )

    bbox_centre = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    candidates = [bbox_centre]
    centroid = _polygon_centroid(exterior)
    if centroid is not None:
        candidates.append(centroid)
    best_point, best_distance = min(
        (
            (point, _room_clearance(point, exterior, holes))
            for point in candidates
        ),
        key=lambda item: (-item[1], item[0]),
    )

    visited = 0
    while heap:
        neg_upper_bound, x, y, cell_half, distance = heapq.heappop(heap)
        visited += 1
        if visited > _ROOM_INTERIOR_MAX_CELLS:
            _refuse(
                AtomReason.UNSUPPORTED_GEOMETRY,
                "room interior search exceeds the deterministic cell budget")
        point = (x, y)
        # Preserve the already-selected bbox/area-centroid candidate on an
        # exact tie (notably ordinary rectangles).  Otherwise heap ordering
        # supplies a canonical coordinate tie-break independent of ring order.
        if distance > best_distance:
            best_point = point
            best_distance = distance
        upper_bound = -neg_upper_bound
        if upper_bound - best_distance <= _ROOM_INTERIOR_PRECISION_MM:
            continue
        next_half = cell_half / 2.0
        push(x - next_half, y - next_half, next_half)
        push(x - next_half, y + next_half, next_half)
        push(x + next_half, y - next_half, next_half)
        push(x + next_half, y + next_half, next_half)

    if best_distance < _ROOM_INTERIOR_MARGIN_MM:
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "room has no provable 10mm interior clearance from every boundary")
    return best_point


def _room_centre(
    room: RoomInfo,
    *,
    source_location_mm: Vec2 | None = None,
) -> Vec2:
    exterior, holes = _validated_room_rings(room)
    # Source priority is explicit for the future additive room side-index:
    # (1) captured Room.Location, once available; (2) deterministic fallback.
    # Frozen L0 1.0 RoomInfo has no Location field, so current callers pass
    # None and cannot silently present a derived point as source-native data.
    if source_location_mm is not None:
        if (all(math.isfinite(value) for value in source_location_mm)
                and _room_clearance(
                    source_location_mm, exterior, holes
                ) >= _ROOM_INTERIOR_MARGIN_MM):
            return source_location_mm
    return _room_interior_point(exterior, holes)


def _lift_room(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    room = context.rooms_by_id.get(element.element_id)
    if room is None:
        _refuse(
            AtomReason.MISSING_METADATA,
            "matching room boundary metadata is absent")
    level = _matching_level(context, room.level_id, room.level_name)
    if not room.name:
        _refuse(
            AtomReason.MISSING_METADATA,
            "room metadata has no reproducible name")
    # 30.07: захват Room.Location поехал. До него `p0_mm` был null у КАЖДОГО
    # помещения во всех 55 сохранённых разборах — тот же член API, что убил
    # чтение групп, стоил точки и всем помещениям. Источник №1, под который
    # `_room_centre` был написан заранее, наконец существует.
    #
    # Не подключить его — значит пересобирать помещение НЕ ТАМ, где оно
    # стоит. У невыпуклого контура (Г-образного, коридора, помещения с
    # вырезом) выведенный центр может лежать ВНЕ помещения, и тогда
    # пересборка создаёт его в соседнем пространстве или не создаёт вовсе.
    # Замер на башне: 2153 расхождения из 2153 поднятых помещений,
    # отклонения до 5339 мм.
    #
    # Доверие не слепое: `_room_centre` проверяет, что точка конечна и лежит
    # внутри контура с запасом, и молча откатывается к детерминированному
    # варианту, если слепок постарел относительно границ.
    source_xy: Vec2 | None = None
    if element.p0_mm is not None and len(element.p0_mm) >= 2:
        source_xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
    centre = _room_centre(room, source_location_mm=source_xy)
    anchor: Vec3 = (centre[0], centre[1], level.elevation_mm)
    params: dict[str, Any] = {
        "xy": [centre[0], centre[1]],
        "level": _level_ref(room.level_id, room.level_name),
        "name": room.name,
    }
    # None is the additive-wire legacy state (number was not measured).
    # A measured value, including "", is exact model identity and must reach
    # the forward op rather than being inferred from Room.Name or omitted.
    if room.number is not None:
        params["number"] = room.number
    return _op_node(
        element,
        "create_room",
        params,
        level_name=room.level_name,
        anchor=anchor,
    )


def _lift_level(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    level = context.levels_by_id.get(element.element_id)
    if level is None:
        _refuse(
            AtomReason.MISSING_METADATA,
            "matching level elevation metadata is absent")
    if not level.name:
        _refuse(
            AtomReason.MISSING_METADATA,
            "level metadata has no reproducible name")
    elevation = _bounded_number(
        level.elevation_mm, "create_level", "elev_mm")
    params: dict[str, Any] = {
        "elev_mm": elevation,
        "name": level.name,
    }
    return _op_node(
        element,
        "create_level",
        params,
        level_name=level.name,
    )


def _lift_grid(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    grid = context.grids_by_id.get(element.element_id)
    if grid is None:
        _refuse(
            AtomReason.MISSING_METADATA,
            "matching grid curve/name metadata is absent")
    p0 = [grid.p0_mm[0], grid.p0_mm[1]]
    p1 = [grid.p1_mm[0], grid.p1_mm[1]]
    if _distance(p0, p1) < 1.0:
        _refuse(
            AtomReason.INVALID_VALUE,
            "grid curve is shorter than the forward 1 mm limit")
    if not grid.name:
        _refuse(
            AtomReason.MISSING_METADATA,
            "grid metadata has no reproducible name")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "name": grid.name,
    }
    return _op_node(
        element,
        "create_grid",
        params,
        anchor=_midpoint(grid.p0_mm, grid.p1_mm),
    )


def _lift_pipe(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _curve(element, dimensions=3)
    _refuse_non_line_curve(element, context, "create_pipe")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "pipe_type": _catalog_ref(element),
        "diameter_mm": _bounded_param(
            element,
            "RBS_PIPE_DIAMETER_PARAM",
            "create_pipe",
            "diameter_mm",
        ),
    }
    # Системный тип — из БОКОВОГО индекса, не из строки L0: принадлежность
    # системе это ссылка на другой элемент, а белый список параметров
    # извлечения чисто геометрический. Индекса нет -> ключа нет, и оп
    # остаётся ровно таким, каким был до этой волны.
    system = context.mep_systems.get(element.element_id)
    if system and system.get("system_type_id") and system.get("system_type_name"):
        params["system_type"] = {
            "by": "name",
            "value": str(system["system_type_name"]),
            "_id": str(system["system_type_id"]),
        }
    return _op_node(element, "create_pipe", params)


def _lift_duct(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _curve(element, dimensions=3)
    _refuse_non_line_curve(element, context, "create_duct")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "duct_type": _catalog_ref(element),
        "diameter_mm": _bounded_param(
            element,
            "RBS_CURVE_DIAMETER_PARAM",
            "create_duct",
            "diameter_mm",
        ),
    }
    # Системный тип — из БОКОВОГО индекса, не из строки L0: принадлежность
    # системе это ссылка на другой элемент, а белый список параметров
    # извлечения чисто геометрический. Индекса нет -> ключа нет, и оп
    # остаётся ровно таким, каким был до этой волны.
    system = context.mep_systems.get(element.element_id)
    if system and system.get("system_type_id") and system.get("system_type_name"):
        params["system_type"] = {
            "by": "name",
            "value": str(system["system_type_name"]),
            "_id": str(system["system_type_id"]),
        }
    return _op_node(element, "create_duct", params)


def _lift_cable_tray(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _curve(element, dimensions=3)
    _refuse_non_line_curve(element, context, "create_cable_tray")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "tray_type": _catalog_ref(element),
    }
    # Old L0 captures predate tray-section extraction.  Preserve their valid
    # lift byte-for-byte: each dimension is lifted only when that exact
    # instance parameter exists, never from an invented default.
    for source, name in (("RBS_CABLETRAY_WIDTH_PARAM", "width_mm"),
                         ("RBS_CABLETRAY_HEIGHT_PARAM", "height_mm")):
        if _finite(element.params.get(source)) is not None:
            params[name] = _bounded_param(
                element, source, "create_cable_tray", name)
    return _op_node(element, "create_cable_tray", params)


def _lift_conduit(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Короб ЭОМ — зеркало лотка, и это не совпадение имён.

    В строке L0 короб и лоток НЕРАЗЛИЧИМЫ по форме: оба линейные MEPCurve,
    у обоих читается та же пара концов, тот же уровень и тот же тип из
    каталога. Диаметра здесь нет НАМЕРЕННО — прямой оп его тоже не берёт
    (номинал короба это торговый размер из таблицы типа, а не длина; см.
    шапку ops_mep.py), и поднять число, которое обратно не построится, значило
    бы выдать невыполнимую программу за круг.
    """
    p0, p1 = _curve(element, dimensions=3)
    _refuse_non_line_curve(element, context, "create_conduit")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "conduit_type": _catalog_ref(element),
    }
    return _op_node(element, "create_conduit", params)


def _lift_stairs(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _stairs_run_endpoints(element, context)
    base_level = _level_from_id(
        element, context, "STAIRS_BASE_LEVEL_PARAM")
    top_level = _level_from_id(
        element, context, "STAIRS_TOP_LEVEL_PARAM")
    if base_level.elevation_mm >= top_level.elevation_mm:
        _refuse(
            AtomReason.INVALID_VALUE,
            "stairs base level must be below its top level")
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "base_level": _level_ref(base_level.id, base_level.name),
        "top_level": _level_ref(top_level.id, top_level.name),
    }
    return _op_node(element, "create_stairs", params)


def _placement_absence_detail(element_id: str, context: _Context) -> str:
    """Почему строки нет: по квитанции, если она есть.

    §18.2/M5. «element is absent from the family placement side index» —
    правда, но БЕСПОЛЕЗНАЯ: она одинаково звучит и когда компилятор не умеет
    такой элемент, и когда экстрактор до него не дошёл. На живом SOB6.2 эта
    фраза стояла на 242 витражных панелях, которые экстрактор просто выбросил
    (панель-стена не FamilyInstance), и читалась как дыра в возможностях.
    Причина берётся ИЗ КВИТАНЦИИ — типизированная, если она типизирована.

    Код отказа остаётся ``placement_kind_unknown``: заводить отдельное
    значение AtomReason значило бы расширить ЗАКРЫТЫЙ словарь причин ради
    оттенка, а зеркальная таблица FidelityReason и все считалки покрытия
    ключуются по нему. Точность живёт в detail, где её и читают.
    """
    failure = context.family_placement_failures.get(element_id)
    if failure is None:
        return "element is absent from the family placement side index"
    typed = getattr(failure, "typed_reason", None)
    typed_value = getattr(typed, "value", typed)
    reason = getattr(failure, "reason", None) or "unspecified"
    if typed_value:
        return (
            "family placement side index refused this element: "
            f"{typed_value} ({reason})")
    return f"family placement side index refused this element: {reason}"


# Размещения, которые `place_family` выражает ТОЧКОЙ.  Оба идут одной
# перегрузкой NewFamilyInstance(point, symbol, [host,] level, …); разница между
# ними ровно в том, обязателен ли хост.  Остальные значения перечисления —
# другая форма (кривая, две отметки, рабочая плоскость, адаптивные точки), и
# точкой они не ставятся.
_POINT_PLACED_PLACEMENTS = frozenset((
    FamilyPlacementType.ONE_LEVEL_BASED,
    FamilyPlacementType.ONE_LEVEL_BASED_HOSTED,
))


# ВИДОЗАВИСИМОЕ размещение — отдельный отказ, и вот почему он не тот же самый.
#
# Ворота ниже отсекают всё, что «не точка», и до 29.07 элемент узла получал
# ровно этот текст: «place_family ставит только точечные размещения, а у этого
# экземпляра 'ViewBased'». Читается это как «нужна другая ГЕОМЕТРИЯ», и
# следующий пошёл бы искать кривую или адаптивные точки. Но ViewBased — ЭТО
# ТОЧКА. Autodesk описывает значение дословно: "The family is view-specific
# (e.g. a detail annotation)" (RevitAPI.xml, F:…FamilyPlacementType.ViewBased,
# все шесть версий). Точка у элемента узла есть, и в боковом индексе она
# лежит; недостаёт не формы, а ВИДА.
#
# Настоящая причина — в самой операции: у place_family НЕТ параметра вида
# (ops_authoring.py: xyz, p0_mm, p1_mm, host, level, symbol, rotation_deg,
# три флага — и всё). И это не упущение реестра, а форма API: Revit держит
# модельное и видовое размещение РАЗНЫМИ перегрузками, причём единственная
# видовая — линейная и документирует отказ прямым текстом (индекс ловушек,
# api_trap_index.py):
#
#   M:…ItemFactoryBase.NewFamilyInstance(Line,FamilySymbol,View)  [all]
#   InvalidOperationException: "Thrown when attempting to place a model-based
#   family. Only 2D detail families can be placed in views."
#
# То есть подставить сюда модельную перегрузку нельзя даже теоретически: она
# поставила бы МОДЕЛЬНЫЙ экземпляр вместо видового — другой элемент, молча
# выданный за тот же. Замер K2: 3 046 элементов узлов.
#
# Тип размещения В КАВЫЧКАХ намеренно — карта причин сворачивает закавыченное
# в '…', и обе видозависимые формы остаются ОДНОЙ структурной строкой ранжира.
_VIEW_SPECIFIC_PLACEMENTS = frozenset((
    FamilyPlacementType.VIEW_BASED,
    FamilyPlacementType.CURVE_BASED_DETAIL,
))


def _lift_family_fallback(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Lift a FamilyInstance the owning lifter could not shape, using exact
    side metadata.

    Presence in the side index is the FamilyInstance discriminator; this is
    deliberately not a category whitelist.  A category owned by ``_CANDIDATES``
    reaches this function only after its own lifter has refused on SHAPE
    grounds (see ``_SHAPE_REFUSALS``) — never in preference to it, and never
    after a refusal about a value or a reference.
    """

    raw = context.family_placement_index.get(element.element_id)
    if raw is None:
        _refuse(
            AtomReason.PLACEMENT_KIND_UNKNOWN,
            _placement_absence_detail(element.element_id, context))
    try:
        record = FamilyPlacementRecord.from_dict(
            element.element_id,
            raw,
            f"family_placement_index[{element.element_id!r}]",
        )
    except FamilyPlacementPayloadError as exc:
        _refuse(
            AtomReason.PLACEMENT_KIND_UNKNOWN,
            f"family placement side-index row is invalid: {exc}")
    # ПОРЯДОК ЗДЕСЬ ЗНАЧИМ, и он выбран замером, а не текстом функции.
    #
    # Вложенность проверяется ПЕРВОЙ: порождённый ребёнок остаётся ребёнком,
    # каким бы ни было его размещение, — его создаёт родитель, и отдельной
    # дырой он не является. Причина отказа обязана быть самой ВЕРНОЙ из
    # применимых, а не первой попавшейся.
    #
    # Пока проверка размещения стояла раньше, вложенные экземпляры с
    # размещением, отличным от OneLevelBased, получали её ярлык. Разница не
    # косметическая: `generator_child` ВЫЧИТАЕТСЯ из честного покрытия, а
    # `unsupported_signature` — нет. Замер 27.07 на тренировочной модели ЭОМ
    # (SKLNK R2026): 1738 экземпляров, 1659 вложенных, 79 самостоятельных —
    # честное покрытие показывалось как 30.37% вместо 67.70%, то есть
    # компилятор клеветал на себя вдвое.
    if record.super_component_id is not None:
        _refuse(
            AtomReason.GENERATOR_CHILD,
            "nested shared FamilyInstance is generated by parent "
            f"{record.super_component_id!r}")
    # CurveBased с ПРОЧИТАННОЙ прямой поднимается по кривой.
    #
    # Замер 27.07 (тренировочная модель ЭОМ, SKLNK R2026): 79 экземпляров —
    # весь остаток дыры этой модели — CurveBased, и у всех живой
    # LocationCurve. Экземпляры висят на кабельных лотках, но хост здесь НЕ
    # препятствие: перегрузка NewFamilyInstance с кривой хоста не принимает,
    # Revit связывает сам, поэтому хост читается обратно в свидетеле.
    # Отказывать из-за поля, которого у вызова нет, значило бы терять
    # элемент ни за чем.
    #
    # `curved_unsupported` пропускается сознательно: маркер ставится ДО
    # попытки чтения и означает ровно «прямую снять не удалось». Поднимать
    # такое по несуществующим концам — придумывать геометрию.
    if (record.placement_type is FamilyPlacementType.CURVE_BASED
            and record.curve_state is CurveState.LINE
            and record.curve_p0_mm is not None
            and record.curve_p1_mm is not None):
        # Уровня у кривого варианта НЕТ, хост ОБЯЗАТЕЛЕН — и то и другое
        # замерено, а не выбрано (см. ops_authoring.place_family): перегрузка
        # с уровнем проецирует кривую на плоскость уровня и схлопывает
        # вертикальный отрезок в точку, а верная перегрузка идёт по ссылке на
        # грань хоста и уровня не принимает вовсе.
        #
        # Первая версия этой ветки (27.07) требовала уровень и не передавала
        # хост — она была написана ДО замера. Повторное извлечение ЭОМ это и
        # показало: 79 кожухов отказали «нужны и id уровня, и имя», то есть
        # цепочка была сомкнута не до конца.
        host_node = _nodes_by_source.get(record.host_id or "")
        if host_node is None:
            _refuse(
                AtomReason.MISSING_REFERENCE,
                "хост кривого семейства не поднят — ставить не на что "
                f"(host_id={record.host_id!r})")
        return _op_node(
            element, "place_family",
            {
                "p0_mm": list(record.curve_p0_mm),
                "p1_mm": list(record.curve_p1_mm),
                "host": {"ref": host_node["_id"]},
                "symbol": _family_symbol_ref(element, record),
            },
            anchor=record.curve_p0_mm)
    # ТОЧЕЧНОЕ размещение — это ДВА типа, а не один.
    #
    # Ниже эта же функция собирает `hosted_ref` и передаёт хост в
    # `place_family` той самой перегрузкой NewFamilyInstance(point, symbol,
    # HOST, level, …), которой ставятся двери и окна (замерено живьём 28.07 на
    # ЭОМ). Но ворота стояли на `is not ONE_LEVEL_BASED` и отсекали ровно тот
    # тип, который и ЗНАЧИТ «закреплённое», — `OneLevelBasedHosted`. Ветка
    # хоста оставалась достижимой только для строки `OneLevelBased`, у которой
    # `host_id` оказался случайно (витражная система на K2). То есть оп
    # научился хосту, а ворота лифта не расширили.
    #
    # Замер 29.07 по боковым индексам, строки НЕ вложенные: `OneLevelBasedHosted`
    # есть в ЧЕТЫРЁХ документах — демо 3122, 13A-RD-AR-K2_v33 2053, SOB6.2_AR
    # 184, SOB6.2_FAS 14 — и у ВСЕХ до одной есть точка, поворот и `host_id`.
    #
    # Ворота СУЖАЮТСЯ, а не исчезают: CurveDrivenStructural, TwoLevelsBased,
    # WorkPlaneBased и Adaptive точкой не ставятся, и для них отказ остаётся.
    if record.placement_type in _VIEW_SPECIFIC_PLACEMENTS:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "размещение видозависимое "
            f"({record.placement_type.value!r}), а у place_family нет "
            "параметра вида: Revit держит модельное и видовое размещение "
            "разными перегрузками, и видовая отказывает модельным семействам "
            "дословно («Only 2D detail families can be placed in views»). "
            "Точка у элемента ЕСТЬ — недостаёт не формы, а вида")
    if record.placement_type not in _POINT_PLACED_PLACEMENTS:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            # Тип размещения — В КАВЫЧКАХ намеренно: карта причин сворачивает
            # закавыченное в '…', и правило остаётся ОДНОЙ структурной
            # строкой ранжира вместо четырёх (по одной на форму), а сам тип
            # при этом читается в детали каждого элемента.
            "place_family ставит только точечные размещения "
            "(OneLevelBased/OneLevelBasedHosted), а у этого экземпляра "
            f"{record.placement_type.value!r}")
    if record.in_place:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "in-place families require source-native family definitions")
    # Закреплённый экземпляр — не отказ, а хост в опе.
    #
    # ЗАМЕР 28.07 (ЭОМ): после того как боковой индекс покрыл разделы,
    # ЕДИНСТВЕННОЙ оставшейся причиной атомов стали 199 элементов с этой
    # надписью — оборудование на стенах и потолках. Оп теперь ставит их той
    # же перегрузкой NewFamilyInstance(point, symbol, HOST, level, …),
    # которой давно ставятся двери и окна.
    #
    # Хост обязан быть ПОДНЯТ: ставить на то, чего в программе нет, нельзя,
    # и «поставим без хоста» было бы тихой потерей привязки.
    hosted_ref = None
    if record.host_id is not None:
        host_node = _nodes_by_source.get(record.host_id)
        if host_node is None:
            _refuse(
                AtomReason.MISSING_REFERENCE,
                "хост закреплённого семейства не поднят — ставить не на что "
                f"(host_id={record.host_id!r})")
        hosted_ref = {"ref": host_node["_id"]}
    elif record.placement_type is FamilyPlacementType.ONE_LEVEL_BASED_HOSTED:
        # Семейство, которое ПО ТИПУ РАЗМЕЩЕНИЯ существует только на хосте, без
        # хоста поставить нельзя. Свободная точка выглядела бы успехом и молча
        # теряла привязку — ровно та тихая потеря, которую §18.1 запрещает.
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "закреплённое семейство без host_id: OneLevelBasedHosted "
            "существует только на хосте, а точка без него потеряла бы привязку")
    if (not record.placement_available
            or record.point_mm is None
            or record.rotation_deg is None):
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "FamilyInstance has no captured LocationPoint and rotation")
    point = record.point_mm
    params: dict[str, Any] = {
        # ``xyz`` is the existing forward-op spelling.  The side-index field
        # is named point_mm; this boundary performs the explicit mapping.
        "xyz": list(point),
        **({"host": hosted_ref} if hosted_ref else {}),
        "level": _level_ref(element.level_id, element.level_name),
        "symbol": _family_symbol_ref(element, record),
        "rotation_deg": record.rotation_deg,
        "mirrored": record.mirrored,
        "hand_flipped": record.hand_flipped,
        "facing_flipped": record.facing_flipped,
    }
    return _op_node(element, "place_family", params, anchor=point)


def _bounded_number(value: float, op_name: str, param_name: str) -> float:
    number = _finite(value)
    if number is None:
        _refuse(
            AtomReason.INVALID_VALUE,
            f"{op_name}.{param_name} is not finite")
    param = next(
        (item for item in spec.OPS[op_name].params
         if item.name == param_name),
        None,
    )
    if param is None:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"{op_name} has no {param_name} parameter")
    if param.min_val is not None and number < param.min_val:
        _refuse(
            AtomReason.INVALID_VALUE,
            f"{op_name}.{param_name} is below its forward bound")
    if param.max_val is not None and number > param.max_val:
        _refuse(
            AtomReason.INVALID_VALUE,
            f"{op_name}.{param_name} is above its forward bound")
    return number


def _lift_directshape(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """DirectShape -> create_directshape, либо ТОЧНАЯ причина отказа.

    Меш берётся из бокового среза (`profile_index`, ключ — id элемента) по той
    же причине, по которой путь марша берётся оттуда у лестницы: в L0 этой
    геометрии нет. Здесь это не деталь реализации, а главный факт направления:
    GeometryKind закрыт значениями curve/point/bbox_only, и ни вершин, ни
    треугольников L0 не переносит вообще (Волна G, KIR_DECOMPILE_SPEC §0.6, не
    построена). Живой стадии, которая наполняла бы этот срез для DirectShape,
    сегодня тоже нет — и это НАЗВАННЫЙ долг, а не тихая дыра: без среза
    элемент становится атомом с причиной MISSING_GEOMETRY, которая говорит,
    чего именно не хватает.

    Чего здесь СОЗНАТЕЛЬНО нет — восстановления меша из габарита. Коробка
    вместо оболочки прошла бы любой структурный тест и была бы неправдой:
    «построил что-то другое» снаружи неотличимо от успеха.
    """
    raw = context.profile_index.get(element.element_id)
    if not isinstance(raw, Mapping) or not raw.get("mesh_available"):
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "L0 не переносит меш (geom_kind ограничен curve/point/bbox_only), "
            "а бокового среза с вершинами и треугольниками для этого "
            "DirectShape нет — восстанавливать форму не из чего")

    category = raw.get("category")
    if not isinstance(category, str) or not category:
        # Категория DirectShape в L0 не сохраняется (в поле лежит литерал
        # "DirectShape"), поэтому её обязан принести срез. Подставить
        # generic_model значило бы молча поменять категорию элемента.
        _refuse(
            AtomReason.MISSING_METADATA,
            "категория DirectShape не сохранена в L0 и не принесена срезом — "
            "подставлять её за источник запрещено")
    from kukai.ir.ops_shape import DIRECTSHAPE_CATEGORIES
    if category not in DIRECTSHAPE_CATEGORIES:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"категория {category!r} не выражается create_directshape "
            f"(операция намеренно не берёт категории, у которых есть свой оп)")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        _refuse(
            AtomReason.MISSING_METADATA,
            "у DirectShape не прочитано имя, а оп требует его обязательно")

    # ТЕ ЖЕ ЗАКОНЫ, ЧТО У КОМПИЛЯТОРА, И ТОТ ЖЕ КОД. Инвариант направления:
    # лифтер не имеет права отдать программу, которую компилятор потом
    # отвергнет, — иначе разбор «успешен», а пересборка падает.
    from kukai.ir.mesh import validate_mesh
    diags: list = []
    mesh = validate_mesh(
        {"vertices_mm": raw.get("vertices_mm"),
         "triangles": raw.get("triangles")},
        element.element_id, "mesh", diags)
    if mesh is None:
        detail = diags[0].message_ru if diags else "меш не прошёл законы формы"
        _refuse(AtomReason.UNSUPPORTED_GEOMETRY, detail)

    return _op_node(element, "create_directshape", {
        "mesh": mesh,
        "category": category,
        "name": name.strip()[:64],
    })


def _lift_room_separator(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Разделитель помещений обратным ходом (wave/room, 03.08).

    ДО ЭТОЙ ВОЛНЫ КАТЕГОРИИ ЗДЕСЬ НЕ БЫЛО ВОВСЕ, и это была правда: операции
    не существовало, все 2 313 элементов K2 честно получали ``no_lifter``
    («category is outside the exact Part 5 lifter table»). Читалась категория
    с 29.07 — как КОНТЕКСТ помещений (extract.py: «границу помещения задаёт
    линия, а не стена»), — но сказать прочитанное было нечем.

    ОДИН ЭЛЕМЕНТ — ОДИН ОТРЕЗОК, И ЭТО НЕ УПРОЩЕНИЕ. В L0 каждый
    OST_RoomSeparationLines несёт собственные ``p0_mm``/``p1_mm`` и
    собственный ``level_id``; ломаная из четырёх звеньев лежит в модели
    четырьмя ЭЛЕМЕНТАМИ с четырьмя ElementId. Сшивать соседние линии в одну
    ломаную нельзя ни по закону («один L0-элемент → РОВНО ОДИН L1-узел»), ни
    по данным: общей личности, которая доказывала бы их родство, у них нет —
    только совпадение координат, а это догадка. Поэтому лифт даёт ломаную
    ровно из двух точек, и пересборка вернёт столько же элементов, сколько
    было.

    ЧТО ОСТАЁТСЯ ОТКАЗОМ И ПОЧЕМУ (замер k2_ar_rd_v9, 2 313 элементов):

    * ДУГА — 14 элементов (``curve_kind: arc``). У ``path`` дугового
      параметра нет, а хорда — это другая граница: помещение поехало бы
      площадью, и verify этого не увидел бы (сравниваются концы).
    * ПЛОСКОСТЬ НЕ НА УРОВНЕ — 4 элемента (смещение -30 мм). Смещения нет ни
      у операции, ни у API: SketchPlane.Create(doc, levelId) строит плоскость
      САМОГО уровня. Вернуть такой разделитель «примерно туда» молча —
      ровно та тихая потеря, которую §18.1 запрещает.
    * УРОВНЯ НЕТ В СПРАВОЧНИКЕ — уровень обязателен, вывести его неоткуда.
    """
    p0, p1 = _curve(element, dimensions=3)
    _refuse_non_line_curve(element, context, "create_room_separator")
    level = (context.levels_by_id.get(element.level_id)
             if element.level_id else None)
    if level is None or not level.name:
        _refuse(
            AtomReason.MISSING_REFERENCE,
            "room separator has no named level and create_room_separator "
            "takes its sketch plane from the level itself")
    # ОТМЕТКА. Сетка ОДНА — та же CANON_MM, на которой канон округляет каждое
    # поле ``*_mm``; свой порог здесь означал бы второго судью о том, что
    # считать «той же отметкой» (тот же довод и тот же приём, что у
    # _lift_railing с его plane_z).  Проверяются ОБА конца: это заодно
    # доказывает, что отрезок лежит В ПЛОСКОСТИ уровня, а не пересекает её.
    if (abs(p0[2] - level.elevation_mm) > CANON_MM
            or abs(p1[2] - level.elevation_mm) > CANON_MM):
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "room separator plane is offset from its own level and "
            "create_room_separator has no offset parameter "
            f"({p0[2] - level.elevation_mm:+.1f} mm)")
    params: dict[str, Any] = {
        "path": [[p0[0], p0[1]], [p1[0], p1[1]]],
        "level": _level_ref(level.id, level.name),
    }
    return _op_node(element, "create_room_separator", params)


_LIFTERS = {
    "_lift_directshape": _lift_directshape,
    "_lift_room_separator": _lift_room_separator,
    "_lift_wall": _lift_wall,
    "_lift_floor": _lift_floor,
    "_lift_roof": _lift_roof,
    "_lift_column": _lift_column,
    "_lift_beam": _lift_beam,
    "_lift_text": _lift_text,
    "_lift_tag": _lift_tag,
    "_lift_dimension": _lift_dimension,
    "_lift_foundation": _lift_foundation,
    "_lift_door": _lift_door,
    "_lift_window": _lift_window,
    "_lift_room": _lift_room,
    "_lift_level": _lift_level,
    "_lift_grid": _lift_grid,
    "_lift_pipe": _lift_pipe,
    "_lift_duct": _lift_duct,
    "_lift_cable_tray": _lift_cable_tray,
    "_lift_conduit": _lift_conduit,
    "_lift_stairs": _lift_stairs,
    "_lift_curtain_panel": _lift_curtain_panel,
    "_lift_ceiling": _lift_ceiling,
    "_lift_railing": _lift_railing,
}


def _diagnostic(
    element: L0Element,
    reason: AtomReason,
    detail: str,
) -> LiftDiagnostic:
    return LiftDiagnostic(
        source_element_id=element.element_id,
        category=element.category,
        reason=reason,
        detail=detail,
    )


# A category owns exactly one lifter, and until this seam existed that lifter's
# refusal was terminal: the generic placement path was reachable only for
# categories missing from ``_CANDIDATES`` altogether.  On SOB6.2 that cost 275
# point-placed OST_StructuralFraming instances — 57% of the building's atoms —
# all of them unhosted OneLevelBased FamilyInstances that ``place_family``
# already expresses.  Only a SHAPE refusal defers: the element simply is not the
# form the owning op is about.  A refusal about a VALUE or a REFERENCE stays
# terminal, because ``place_family`` would "resolve" it by discarding the facts
# the specialised op exists to preserve.
_SHAPE_REFUSALS = frozenset((
    AtomReason.MISSING_GEOMETRY,
    AtomReason.UNSUPPORTED_GEOMETRY,
    AtomReason.UNSUPPORTED_SIGNATURE,
))


# When the fallback also refuses, the owning lifter's reason is normally the
# honest one: it names the real gap, while the fallback's would only say why a
# SECOND op declined too.  GENERATOR_CHILD is the exception, because it is not a
# statement about place_family's limits at all — it is a fact about the element,
# namely that a parent family already creates it and recreating it individually
# would duplicate geometry.  On SOB6.2 this is 237 of 275 structural framing
# instances; reporting them as "requires curve geometry" would send the next
# reader hunting for a curve lifter that must never be written.
_FALLBACK_REASONS_THAT_WIN = frozenset((AtomReason.GENERATOR_CHILD,))


def _shape_fallback(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
    refusal: "_CannotLift",
) -> tuple[L1Node, LiftDiagnostic | None] | None:
    """``place_family`` for a shape the owning lifter is not about, else None.

    Returning None means "keep the original atom".
    """

    if refusal.reason not in _SHAPE_REFUSALS:
        return None
    # МАРКА НИКОГДА НЕ ПАДАЕТ В place_family.
    #
    # Оба её отказа — «род SpatialElementTag» и «ориентация не выражается» —
    # это ``unsupported_forward_signature``, то есть ФОРМЕННЫЙ отказ, а
    # форменный отказ здесь по умолчанию означает «пусть попробует
    # place_family». Для марки это было бы ВЫДУМАННЫМ ИСТОЧНИКОМ (§18.1): ни
    # ``IndependentTag``, ни ``SpatialElementTag`` не являются
    # ``FamilyInstance``, и место семейства вместо марки прошло бы схему L1 и
    # выглядело бы покрытием.
    #
    # Сегодня путь недостижим — категорий марок нет в таблице бокового
    # индекса размещений, и его C# не-FamilyInstance строк не порождает. Эта
    # строка держит границу на тот день, когда таблицу расширят, и стоит
    # ПЕРЕД разбором индексов, чтобы не зависеть от того, что в них попало.
    if element.category in TAG_CATEGORIES:
        return None
    # Витражная дверь/окно — это ЯЧЕЙКА, а не проём в стене: у неё нет
    # LocationPoint вовсе, и собственный лифтер отказывает по форме. Если
    # боковой индекс витражей знает эту ячейку, отвечать за элемент обязан
    # он, а не place_family, который про сетку не знает ничего.
    if element.element_id in context.curtain_cells:
        try:
            node = _lift_curtain_panel(element, context, nodes_by_source)
            if is_valid_l1_node(node):
                return node, None
        except _CannotLift as exc:
            if exc.reason in _FALLBACK_REASONS_THAT_WIN:
                return (
                    _atom_node(element, exc.reason, exc.detail),
                    _diagnostic(element, exc.reason, exc.detail),
                )
        except Exception:  # noqa: BLE001 - any defect falls closed to the atom
            pass
    if not context.family_placement_index:
        return None
    try:
        node = _lift_family_fallback(element, context, nodes_by_source)
    except _CannotLift as exc:
        if exc.reason not in _FALLBACK_REASONS_THAT_WIN:
            return None
        return (
            _atom_node(element, exc.reason, exc.detail),
            _diagnostic(element, exc.reason, exc.detail),
        )
    except Exception:  # noqa: BLE001 - any defect falls closed to the atom
        return None
    return (node, None) if is_valid_l1_node(node) else None


def _lift_one(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> tuple[L1Node, LiftDiagnostic | None]:
    # ТЕЛО ЯЧЕЙКИ проверяется раньше всякой категории: стена, заполнившая
    # ячейку витража, существует потому, что ячейке назначен тип. Своя
    # операция у неё была бы вторым экземпляром той же геометрии — и, в
    # отличие от прочих причин, это факт об элементе, а не о наших умениях.
    owner_cell = context.curtain_cell_bodies.get(element.element_id)
    if owner_cell is not None and owner_cell in context.elements_by_id:
        # ЗАНЯВШИЙ ЕСТЬ В ЭТОМ ЖЕ ДОКУМЕНТЕ — тогда занятая панель именно
        # тело, и операция у ячейки ровно одна, на стороне занявшего.
        # Если же занявшего в документе нет, эта панель — ЕДИНСТВЕННОЕ
        # представительство ячейки, и назвать её порождаемым ребёнком
        # значило бы потерять ячейку целиком (ре-лифт пересобранной модели).
        reason = AtomReason.GENERATOR_CHILD
        detail = (
            "тело витражной ячейки — его создаёт назначение типа ячейке "
            f"{owner_cell!r}, отдельной операции у него нет")
        return (
            _atom_node(element, reason, detail),
            _diagnostic(element, reason, detail),
        )
    # ИМПОСТ — не экземпляр семейства, поставленный в точку, а элемент
    # ЛИНИИ РАЗРЕЗКИ. Класс у него FamilyInstance, поэтому боковой индекс
    # размещений отдаёт про него строку, и общий путь ставил его
    # `place_family`-ем в точку — то есть при пересборке витраж получал бы
    # СВОИ импосты от типа плюс наши поверх (замер v6: 956 таких опов, 42%
    # всех опов фасада). Единственный способ создать импост —
    # CurtainGridLine.AddMullions(segment, MullionType, oneSegmentOnly)
    # (RevitAPI.xml эталонного пакета); у самого импоста LocationCurve, а не
    # точка. Опы для этого в реестре нет.
    #
    # Отсюда РОВНО ДВА честных исхода, и разделяет их не наше желание, а
    # доказательство. Импост, которого носитель НЕ порождает, — честная
    # дыра: назвать его generator_child значило бы вычесть из знаменателя
    # то, чего пересборка не построит. Импост, которого носитель порождает
    # САМ, — ребёнок: ему не нужна операция, потому что он появится от типа.
    # Доказательство требует двух свидетелей и живёт в
    # CurtainWallRecord.mullion_state: Mullion.Lock (Revit сам считает его
    # ведомым типом) И тип импоста среди слотов AUTO_MULLION_* носителя.
    # Схема индекса до /4 не читала ни того, ни другого — её строки честно
    # остаются дырой (замер v11: 964 импоста, v12: 1372).
    # ЛИНИЯ РАЗРЕЗКИ проверяется раньше категорий: у неё есть свой id и своя
    # строка в боковом индексе, но нет ни типа, ни точки размещения — общий
    # путь размещения поставил бы её `place_family`-ем в пустоту.
    grid_line_row = context.curtain_grid_lines.get(element.element_id)
    if grid_line_row is not None:
        host_id, host_record, line, direction = grid_line_row
        node, diagnostic = _grid_line_node(
            element.element_id, host_id, host_record, line, direction,
            nodes_by_source.get(host_id))
        if node is not None:
            return node, None
        reason = (diagnostic.reason if diagnostic is not None
                  else AtomReason.MISSING_METADATA)
        detail = (diagnostic.detail if diagnostic is not None
                  else "линия разрезки не поднята")
        return (
            _atom_node(element, reason, detail),
            _diagnostic(element, reason, detail),
        )

    mullion_row = context.curtain_mullions.get(element.element_id)
    if mullion_row is not None:
        mullion_host, host_record, mullion = mullion_row
        state = host_record.mullion_state(mullion)
        if state is MullionState.TYPE_DRIVEN:
            # ДОКАЗАННЫЙ ребёнок: пересборка носителя родит его сама, и
            # только поэтому его можно вычесть из знаменателя. Оба
            # свидетеля сошлись — Mullion.Lock и слот типа носителя.
            reason = AtomReason.GENERATOR_CHILD
            detail = (
                f"импост порождается типом носителя {mullion_host!r}: он "
                f"заперт за типом (Mullion.Lock) и его тип {mullion.type_id!r} "
                "числится среди тех, что носитель ставит сам — пересборка "
                "носителя построит его без всякой операции")
        else:
            reason = AtomReason.UNSUPPORTED_SIGNATURE
            detail = (
                "импост витража принадлежит сетке носителя "
                f"{mullion_host!r} и создаётся только "
                "CurtainGridLine.AddMullions по сегменту линии разрезки; "
                "place_family поставил бы второй импост поверх того, который "
                "витраж порождает сам") + _MULLION_ATOM_DETAIL[state]
        return (
            _atom_node(element, reason, detail),
            _diagnostic(element, reason, detail),
        )
    candidate = _CANDIDATES.get(element.category)
    if candidate is None:
        # ОП ЕСТЬ, ВХОДОВ ЕМУ НЕТ — проверяется ПЕРВЫМ, потому что это самый
        # ТОЧНЫЙ из применимых фактов, а причина обязана быть самой верной, а
        # не первой попавшейся (то же правило, по которому вложенность
        # проверяется раньше размещения в _lift_family_fallback).
        #
        # Ниже стоит §18.2 про молчание стадии размещений, и для размера или
        # марки оно дало бы `no_lifter`: в индекс размещений аннотация не
        # попадает никогда, она не FamilyInstance. Ответ был бы формально
        # объясним и практически ложен — он послал бы писать операцию, которая
        # написана.
        annotation_op = _OPS_WITHOUT_L0_INPUTS.get(element.category)
        if annotation_op is not None:
            # Реестр остаётся ЕДИНСТВЕННОЙ властью над тем, есть ли оп: если
            # его вдруг не окажется, честный ответ — прежний registry-gap, а
            # не рассказ про входы несуществующей операции.
            if annotation_op not in spec.OPS:
                reason = AtomReason.REGISTRY_OP_GAP
                detail = f"{annotation_op!r} is absent from spec.OPS"
            else:
                reason = AtomReason.SOURCE_CONTRACT_GAP
                detail = _unsourceable_inputs_detail(annotation_op)
            return (
                _atom_node(element, reason, detail),
                _diagnostic(element, reason, detail),
            )
        # §18.2: ПУСТОЙ индекс размещений и ОТСУТСТВУЮЩИЙ — разные вещи.
        # Пока проверялось только наличие строк, стадия, которую целиком
        # срезал бюджет (ни одной строки, но полный список квитанций),
        # выглядела как «этой категории у нас нет лифтера» — самый неверный
        # из возможных ответов: лифтер есть, до элемента не дошло ЧТЕНИЕ.
        #
        # 29.07: то же различие обобщено с ДОКУМЕНТА на ЭЛЕМЕНТ. Пока оно
        # ставилось про весь документ, стоило стадии отработать хоть по одной
        # строке — и потолок, площадь, ограждение лестницы, витражная система,
        # то есть элемент, который НИКОГДА не был FamilyInstance и в индексе
        # размещений оказаться не мог, получал «element is absent from the
        # family placement side index». Читается это как «экстрактор его
        # потерял», а правда — «для его категории у нас нет операции».
        #
        # Видно это прямо в карте причин: одна популяция стояла в ней ДВАЖДЫ
        # под разными именами — 28926 эл. «category is outside the … lifter
        # table» (слепки, где стадия не запускалась) и 8207 эл. «absent from
        # the family placement side index» (те же категории там, где стадия
        # запускалась). Ранжир причин — то, по чему решают, что строить
        # дальше, и двоение в нём дороже любого процента покрытия.
        #
        # Правило: если про ЭТОТ элемент у стадии нет ни строки, ни квитанции,
        # она о нём не высказалась, и её молчание не улика против него. Старое
        # условие — частный случай нового: пустой индекс без квитанций и есть
        # молчание про каждый элемент.
        if element.element_id not in context.family_placement_index \
                and element.element_id not in context.family_placement_failures:
            reason = AtomReason.NO_LIFTER
            # Категория НАЗВАНА (10.08). Замер по 67 разборам: эта причина
            # первая в карте — 10 документов из 10, 77 733 элемента — и
            # единственная, задевающая ВСЕ документы. Без имени категории по
            # ней нельзя действовать: она сообщает «чего-то нет», а решают по
            # ней, какую строку таблицы категорий писать следующей. Имя идёт
            # ПЕРЕД прежней формулировкой, потому что на саму формулировку
            # ссылаются три теста и два комментария в этом файле.
            detail = (f"{element.category}: category is outside the exact "
                      "Part 5 lifter table")
            return (
                _atom_node(element, reason, detail),
                _diagnostic(element, reason, detail),
            )
        try:
            node = _lift_family_fallback(
                element, context, nodes_by_source)
            if not is_valid_l1_node(node):
                raise _CannotLift(
                    AtomReason.INVALID_NODE,
                    "place_family produced a structurally invalid L1 node",
                )
            return node, None
        except _CannotLift as exc:
            return (
                _atom_node(element, exc.reason, exc.detail),
                _diagnostic(element, exc.reason, exc.detail),
            )
        except Exception as exc:  # noqa: BLE001 - total fail-closed transform
            reason = AtomReason.INTERNAL_ERROR
            detail = (
                f"unexpected {type(exc).__name__}; element preserved as atom")
            return (
                _atom_node(element, reason, detail),
                _diagnostic(element, reason, detail),
            )
    if candidate.op not in spec.OPS:
        reason = AtomReason.REGISTRY_OP_GAP
        detail = f"{candidate.op!r} is absent from spec.OPS"
        return (
            _atom_node(element, reason, detail),
            _diagnostic(element, reason, detail),
        )
    try:
        node = _LIFTERS[candidate.lifter_name](
            element, context, nodes_by_source)
        if not is_valid_l1_node(node):
            raise _CannotLift(
                AtomReason.INVALID_NODE,
                f"{candidate.op} produced a structurally invalid L1 node",
            )
        return node, None
    except _CannotLift as exc:
        fallback = _shape_fallback(element, context, nodes_by_source, exc)
        if fallback is not None:
            return fallback
        return (
            _atom_node(element, exc.reason, exc.detail),
            _diagnostic(element, exc.reason, exc.detail),
        )
    except Exception as exc:  # noqa: BLE001 - total transform, atom on defects
        reason = AtomReason.INTERNAL_ERROR
        detail = f"unexpected {type(exc).__name__}; element preserved as atom"
        return (
            _atom_node(element, reason, detail),
            _diagnostic(element, reason, detail),
        )


def _context(
    document: L0Document,
    profile_index: Mapping[str, Any] | None = None,
    family_placement_index: (
        FamilyPlacementExtraction | Mapping[str, Any] | None
    ) = None,
    wall_curve_index: (
        CurveExtraction | Mapping[str, Any] | None
    ) = None,
    curtain_index: Any = None,
    annotation_index: Any = None,
    tag_index: Any = None,
    dimension_index: Any = None,
    mep_system_index: Any = None,
) -> _Context:
    profiles, stairs_paths, railing_paths = _side_indexes(profile_index)
    placements = parse_family_placement_index(family_placement_index)
    (curtain_cells, curtain_bodies, curtain_mullions,
     curtain_grid_lines) = _curtain_side_index(curtain_index)
    return _Context(
        revit_version=document.revit_version,
        elements_by_id={
            element.element_id: element for element in document.elements},
        levels_by_id={level.id: level for level in document.levels},
        grids_by_id={grid.id: grid for grid in document.grids},
        rooms_by_id={room.id: room for room in document.rooms},
        profile_index=profiles,
        stairs_run_path_index=stairs_paths,
        family_placement_index=placements,
        family_placement_requested=family_placement_index is not None,
        wall_curve_index=_wall_curve_side_index(wall_curve_index),
        family_placement_failures=parse_family_placement_failures(
            family_placement_index),
        railing_path_index=railing_paths,
        curtain_cells=curtain_cells,
        curtain_cell_bodies=curtain_bodies,
        curtain_mullions=curtain_mullions,
        curtain_grid_lines=curtain_grid_lines,
        text_notes=_annotation_side_index(annotation_index),
        tags=_tag_side_index(tag_index),
        dimensions=_dimension_side_index(dimension_index),
        mep_systems=_mep_system_side_index(mep_system_index),
    )


def _lift_document(
    document: L0Document,
    *,
    collect_diagnostics: bool,
    profile_index: Mapping[str, Any] | None = None,
    family_placement_index: (
        FamilyPlacementExtraction | Mapping[str, Any] | None
    ) = None,
    wall_curve_index: (
        CurveExtraction | Mapping[str, Any] | None
    ) = None,
    curtain_index: Any = None,
    annotation_index: Any = None,
    tag_index: Any = None,
    dimension_index: Any = None,
    mep_system_index: Any = None,
) -> LiftResult:
    context = _context(
        document, profile_index, family_placement_index, wall_curve_index,
        curtain_index, annotation_index, tag_index, dimension_index,
        mep_system_index)
    nodes: list[L1Node | None] = [None] * len(document.elements)
    nodes_by_source: dict[str, L1Node] = {}
    diagnostics: list[LiftDiagnostic] = []

    # First lift every non-hosted element.  Doors/windows are resolved in a
    # second pass, so their host reference is independent of L0 input order and
    # can consistently target either an op or atom wall node.
    for index, element in enumerate(document.elements):
        if element.category in _DEFERRED_CATEGORIES:
            continue
        node, diagnostic = _lift_one(element, context, nodes_by_source)
        nodes[index] = node
        nodes_by_source[element.element_id] = node
        if collect_diagnostics and diagnostic is not None:
            diagnostics.append(diagnostic)

    for index, element in enumerate(document.elements):
        if element.category not in _HOSTED_CATEGORIES:
            continue
        node, diagnostic = _lift_one(element, context, nodes_by_source)
        nodes[index] = node
        nodes_by_source[element.element_id] = node
        if collect_diagnostics and diagnostic is not None:
            diagnostics.append(diagnostic)

    # ТРЕТИЙ ПРОХОД — ССЫЛАЮЩЕЕСЯ ОФОРМЛЕНИЕ (МАРКИ И РАЗМЕРЫ), и он обязан
    # быть именно третьим.
    #
    # Марка ссылается на ЛЮБОЙ элемент документа, в том числе на дверь или
    # окно, которые сами поднимаются вторым проходом. Подними её раньше — и
    # марка на двери получила бы `missing_reference` не потому, что двери
    # нет, а потому, что до неё ещё не дошли: отказ, зависящий от
    # внутреннего порядка лифта, а не от модели. Это тот же закон, по
    # которому второй проход завели для дверей (ссылка не должна зависеть от
    # порядка элементов в L0), применённый на шаг дальше.
    #
    # РАЗМЕР ПРИЕХАЛ СЮДА ЖЕ И ПО ТОЙ ЖЕ ПРИЧИНЕ, замеренной, а не
    # предположенной: пока он поднимался первым проходом, размер между двумя
    # обычными стенами отказывал `missing_reference` на ПЕРВОЙ же ссылке —
    # стены существовали в L0, но узла для них ещё не было. Отказ читался бы
    # как «этих элементов нет в модели», а правда была «лифт до них не дошёл».
    for index, element in enumerate(document.elements):
        if element.category not in _REFERENCING_ANNOTATION_CATEGORIES:
            continue
        node, diagnostic = _lift_one(element, context, nodes_by_source)
        nodes[index] = node
        nodes_by_source[element.element_id] = node
        if collect_diagnostics and diagnostic is not None:
            diagnostics.append(diagnostic)

    # ЛИНИЯ РАЗРЕЗКИ, КОТОРОЙ НЕТ В L0, НЕ СТАНОВИТСЯ УЗЛОМ.
    #
    # Первая редакция этой волны синтезировала такой узел из бокового
    # индекса — и живой прогон v14 остановился ровно на нём:
    # FoldError('L0/L1 source mismatch: missing=0, invented=122'). Закон
    # переписи прав: у узла обязан быть ИСТОЧНИК В L0, иначе лифт сочиняет
    # элементы, которых чтение не видело. Чинится сторона чтения — категории
    # линий разрезки добавлены в таблицу экстрактора, — а здесь остаётся
    # честный диагноз для случая, когда линия в индексе есть, а в L0 её нет
    # (срез бюджета, чужой род носителя, старый разбор).
    if collect_diagnostics:
        for line_id, (host_id, _host_record, _line, _direction) in sorted(
                context.curtain_grid_lines.items(),
                key=lambda item: _element_id_sort_key(item[0])):
            if line_id in context.elements_by_id:
                continue
            diagnostics.append(LiftDiagnostic(
                source_element_id=line_id,
                category="OST_CurtainGridsWall",
                reason=AtomReason.MISSING_METADATA,
                detail=(
                    f"линия разрезки носителя {host_id!r} есть в индексе "
                    "витражей, но её нет среди прочитанных элементов — "
                    "операции у неё не будет: узел без источника в L0 "
                    "фолд отвергает как изобретённый")))

    # Keep the public transform total even if a future category/pass edit
    # accidentally leaves a slot unfilled: preserve that source as an atom and
    # surface the defect through the detailed diagnostic channel.
    for index, node in enumerate(nodes):
        if node is not None:
            continue
        element = document.elements[index]
        detail = "internal pass left the source unhandled; element preserved as atom"
        nodes[index] = _atom_node(
            element, AtomReason.INTERNAL_ERROR, detail)
        if collect_diagnostics:
            diagnostics.append(_diagnostic(
                element,
                AtomReason.INTERNAL_ERROR,
                detail,
            ))
    final_nodes = cast(tuple[L1Node, ...], tuple(nodes))
    # Validate collection-level uniqueness and hosted references at the shared
    # boundary.  A defect here is a programmer/schema error, not a source-model
    # insufficiency; individual insufficiencies already became typed atoms.
    validate_l1_nodes(final_nodes)
    return LiftResult(
        nodes=final_nodes,
        diagnostics=tuple(diagnostics),
    )


def lift_document(
    document: L0Document,
    profile_index: Mapping[str, Any] | None = None,
    family_placement_index: (
        FamilyPlacementExtraction | Mapping[str, Any] | None
    ) = None,
    wall_curve_index: (
        CurveExtraction | Mapping[str, Any] | None
    ) = None,
    curtain_index: Any = None,
) -> tuple[L1Node, ...]:
    """Lift L0 with optional Sketch, FamilyInstance, curve and curtain indexes."""

    return _lift_document(
        document,
        collect_diagnostics=False,
        profile_index=profile_index,
        family_placement_index=family_placement_index,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
    ).nodes


def lift_document_detailed(
    document: L0Document,
    profile_index: Mapping[str, Any] | None = None,
    family_placement_index: (
        FamilyPlacementExtraction | Mapping[str, Any] | None
    ) = None,
    wall_curve_index: (
        CurveExtraction | Mapping[str, Any] | None
    ) = None,
    curtain_index: Any = None,
    annotation_index: Any = None,
    tag_index: Any = None,
    dimension_index: Any = None,
    mep_system_index: Any = None,
) -> LiftResult:
    """Lift and retain one typed diagnostic for each atom fallback."""

    return _lift_document(
        document,
        collect_diagnostics=True,
        profile_index=profile_index,
        family_placement_index=family_placement_index,
        wall_curve_index=wall_curve_index,
        curtain_index=curtain_index,
        annotation_index=annotation_index,
        tag_index=tag_index,
        dimension_index=dimension_index,
        mep_system_index=mep_system_index,
    )


def lift_element(
    element: L0Element,
    document: L0Document | None = None,
    profile_index: Mapping[str, Any] | None = None,
    family_placement_index: (
        FamilyPlacementExtraction | Mapping[str, Any] | None
    ) = None,
    wall_curve_index: (
        CurveExtraction | Mapping[str, Any] | None
    ) = None,
    curtain_index: Any = None,
) -> L1Node:
    """Lift one element.

    Document context is required for metadata-backed levels/grids/rooms,
    window sill inversion, and hosted references.  With a supplied document,
    the full order-independent transform is used and the matching source node
    is returned.  Without it, any context-dependent case honestly atomizes.
    """

    if document is not None:
        for source, node in zip(
                document.elements, lift_document(
                    document, profile_index, family_placement_index,
                    wall_curve_index, curtain_index)):
            if source.element_id == element.element_id:
                return node
    profiles, stairs_paths, railing_paths = _side_indexes(profile_index)
    (curtain_cells, curtain_bodies, curtain_mullions,
     curtain_grid_lines) = _curtain_side_index(curtain_index)
    empty_context = _Context(
        revit_version=None,
        elements_by_id={element.element_id: element},
        levels_by_id={},
        grids_by_id={},
        rooms_by_id={},
        profile_index=profiles,
        stairs_run_path_index=stairs_paths,
        family_placement_index=parse_family_placement_index(
            family_placement_index),
        family_placement_requested=family_placement_index is not None,
        wall_curve_index=_wall_curve_side_index(wall_curve_index),
        railing_path_index=railing_paths,
        curtain_cells=curtain_cells,
        curtain_cell_bodies=curtain_bodies,
        curtain_mullions=curtain_mullions,
        curtain_grid_lines=curtain_grid_lines,
    )
    return _lift_one(element, empty_context, {})[0]


__all__ = [
    "AtomReason",
    "L1AtomNode",
    "L1Node",
    "L1OpNode",
    "LIFTER_TABLE",
    "LiftDiagnostic",
    "LiftResult",
    "is_valid_l1_node",
    "lift_document",
    "lift_document_detailed",
    "lift_element",
    "stable_l1_id",
]
