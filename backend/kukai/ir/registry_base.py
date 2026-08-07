"""KIR v1 registry — the single source of truth (SPEC_V1 §3).

Everything else is GENERATED from this module: the JSON Schema
(schema_gen.py), the emitted C# (compiler.py), the capability-cell export the
coverage cube consumes (export_capability_cells), and the vocabulary deltas
(OBJECT_KINDS_ADDED / ROUTE_ONLY_ACTIONS / bare-action ban). Hand-written
copies of any of these are forbidden — see RISK_MATRIX R10.

Query family only (v1 spiral, coordinator-approved order). All kinds chosen
version-safe across Revit 2021-2026 and the emitted dialect is C# 7.3
(the .NET Framework 4.8 ceiling for Revit <=2024; compiles unchanged on
.NET 8 for 2025-2026), so the per-version emit axis carries one variant for
now — the API (emit_for_version) keeps the axis so the authoring family can
diverge per version without breaking callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Optional, Sequence


def _freeze_registry_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({
            key: _freeze_registry_value(item)
            for key, item in value.items()
        })
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_registry_value(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze_registry_value(item) for item in value)
    return value


def freeze_registry_mapping(values: Mapping[Any, Any]) -> Mapping[Any, Any]:
    """Return a defensive, recursively immutable registry mapping."""
    return _freeze_registry_value(dict(values))


IR_VERSION = "1.0"
REVIT_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

# ── Vocabulary deltas (coordinator arbitration 13.2/13.3) ────────────────────
# New object_kinds the registry contributes to capability_vocab. schedule_field
# deliberately deferred. Bare actions (action with no object_kind) are banned
# forever: _lint_registry() enforces every cell is a full (action, object_kind).
OBJECT_KINDS_ADDED = ("geometry", "document")
# consult stays in the action vocabulary but routes to the wiki knowledge path;
# by definition it has no IR ops. The cube renders these cells "route-only".
ROUTE_ONLY_ACTIONS = freeze_registry_mapping({
    "consult": "wiki-knowledge-path",
})
# SPEC §16 verdict: the release-builder's kind-less placeholder «action×-» dies.
# The cube validator's hard error was right; orphan cards map to
# geometry/document/view via the migration table, never released with "-".
BANNED_OBJECT_KIND_PLACEHOLDERS = ("-", "")

# Single defaults table (ir_defaults discipline: one source for compiler,
# schema and future reference-interpreter — divergence reopens the fork).
DEFAULTS = freeze_registry_mapping({
    "wall": {"height_mm": 3000.0},
})


# ── Kind table: the closed enum that killed the pdfCount=0 bug class ────────
# Each kind maps to ONE collector idiom, written and reviewed once. `where_cs`
# is an extra predicate over the collected element (C# lambda body over `e`).
# Every idiom used here exists unchanged in Revit 2021-2026 (version-safe set).
# Проектные разделы. Словарь ОДИН на весь пакет: ровно эти строки уже
# возвращает `__Discipline` в decompile/extract.py, когда угадывает раздел
# связи по токенам её имени (АР/КР/ОВ/ВК/ЭОМ). Заводить второй словарь для
# видов значило бы завести второй источник правды о том же самом.
#
# `shared` — не «неизвестно», а «принадлежит всем»: уровни, оси, виды, листы
# читает и АР, и КР, и инженерка. Отсутствие раздела у вида — ошибка таблицы,
# и её ловит тест, а не соглашение.
DISCIPLINES: frozenset[str] = frozenset({
    "architectural", "structural", "mechanical", "plumbing", "electrical",
    "shared",
})


@dataclass(frozen=True)
class KindSpec:
    name: str
    collector_cs: str            # FilteredElementCollector chain AFTER new FilteredElementCollector(doc)
    where_cs: Optional[str] = None   # optional C# predicate body over `e` (an Element)
    comment: str = ""
    # Раздел проекта, которому вид принадлежит.  Нужен потому, что работа
    # ведётся ПО РАЗДЕЛАМ: свой исполнитель на АР, свой на КР, свой на каждый
    # инженерный раздел.  Раздел, записанный в таблице, позволяет сузить и
    # описание инструмента, и право на запись — то есть сделать границу
    # проверяемой, а не обещанной в промпте.
    discipline: str = "shared"

    def __post_init__(self) -> None:
        if self.discipline not in DISCIPLINES:
            raise ValueError(
                f"KindSpec {self.name!r}: unknown discipline "
                f"{self.discipline!r}; expected one of {sorted(DISCIPLINES)}")


KINDS: Mapping[str, KindSpec] = freeze_registry_mapping({
    kind.name: kind for kind in (
    # The canonical regression case (2026-07-16 incident): PDF underlays are
    # raster ImageInstance elements, NOT ImportInstance — encoded here once.
    KindSpec("pdf_underlay",
             ".OfClass(typeof(ImageInstance))",
             where_cs='__TypeNameOf(e).EndsWith(".pdf", StringComparison.OrdinalIgnoreCase)',
             comment="PDF import/underlay = ImageInstance whose ImageType name ends .pdf",
             discipline="shared"),
    KindSpec("image", ".OfClass(typeof(ImageInstance))",
             comment="all raster images incl. PDF pages",
             discipline="shared"),
    KindSpec("cad_import", ".OfClass(typeof(ImportInstance))",
             where_cs="!((ImportInstance)e).IsLinked",
             comment="one-off DWG/DXF import (static)",
             discipline="shared"),
    KindSpec("cad_link", ".OfClass(typeof(ImportInstance))",
             where_cs="((ImportInstance)e).IsLinked",
             comment="live CAD link",
             discipline="shared"),
    KindSpec("wall", ".OfClass(typeof(Wall))",
             discipline="architectural"),
    KindSpec("door", ".OfCategory(BuiltInCategory.OST_Doors).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("window", ".OfCategory(BuiltInCategory.OST_Windows).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("floor", ".OfClass(typeof(Floor))",
             discipline="architectural"),
    KindSpec("ceiling", ".OfCategory(BuiltInCategory.OST_Ceilings).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("roof", ".OfCategory(BuiltInCategory.OST_Roofs).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("room", ".OfCategory(BuiltInCategory.OST_Rooms).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("level", ".OfClass(typeof(Level))",
             discipline="shared"),
    KindSpec("grid", ".OfClass(typeof(Grid))",
             discipline="shared"),
    # No guessing between the two column families — they are distinct kinds.
    KindSpec("column_structural",
             ".OfCategory(BuiltInCategory.OST_StructuralColumns).WhereElementIsNotElementType()",
             discipline="structural"),
    KindSpec("column_architectural",
             ".OfCategory(BuiltInCategory.OST_Columns).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("stair", ".OfCategory(BuiltInCategory.OST_Stairs).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("pipe", ".OfCategory(BuiltInCategory.OST_PipeCurves).WhereElementIsNotElementType()",
             discipline="plumbing"),
    KindSpec("duct", ".OfCategory(BuiltInCategory.OST_DuctCurves).WhereElementIsNotElementType()",
             discipline="mechanical"),
    KindSpec("cable_tray", ".OfCategory(BuiltInCategory.OST_CableTray).WhereElementIsNotElementType()",
             discipline="electrical"),
    KindSpec("view", ".OfClass(typeof(View))",
             where_cs="!((View)e).IsTemplate",
             comment="user views, templates excluded",
             discipline="shared"),
    KindSpec("sheet", ".OfClass(typeof(ViewSheet))",
             discipline="shared"),

    # ── Разделы кроме АР ────────────────────────────────────────────────────
    # До 27.07 таблица знала 9 архитектурных видов и по ОДНОМУ на каждый
    # инженерный раздел — то есть спросить «сколько щитов» или «какие
    # светильники» было нечем, и любой отказ выглядел как отказ компилятора,
    # хотя это отсутствие строки в таблице.  Работа ведётся по разделам, у
    # каждого свой исполнитель, поэтому таблица обязана покрывать разделы
    # соразмерно, а не в меру того, с какой модели её начинали писать.
    #
    # Каждая строка — один коллектор и ничего больше; проверка одна и та же:
    # ворота Roslyn компилируют эмиссию на шести версиях Revit, и категория,
    # которой в какой-то версии нет, роняет их, а не доезжает молча.

    # КР
    KindSpec("structural_framing",
             ".OfCategory(BuiltInCategory.OST_StructuralFraming).WhereElementIsNotElementType()",
             comment="балки, связи, прогоны", discipline="structural"),
    KindSpec("structural_foundation",
             ".OfCategory(BuiltInCategory.OST_StructuralFoundation).WhereElementIsNotElementType()",
             discipline="structural"),
    KindSpec("structural_truss",
             ".OfCategory(BuiltInCategory.OST_StructuralTruss).WhereElementIsNotElementType()",
             discipline="structural"),

    # ЭОМ
    KindSpec("electrical_equipment",
             ".OfCategory(BuiltInCategory.OST_ElectricalEquipment).WhereElementIsNotElementType()",
             comment="щиты, шкафы, трансформаторы", discipline="electrical"),
    KindSpec("electrical_fixture",
             ".OfCategory(BuiltInCategory.OST_ElectricalFixtures).WhereElementIsNotElementType()",
             comment="розетки, выключатели", discipline="electrical"),
    KindSpec("lighting_fixture",
             ".OfCategory(BuiltInCategory.OST_LightingFixtures).WhereElementIsNotElementType()",
             discipline="electrical"),
    KindSpec("lighting_device",
             ".OfCategory(BuiltInCategory.OST_LightingDevices).WhereElementIsNotElementType()",
             discipline="electrical"),
    KindSpec("cable_tray_fitting",
             ".OfCategory(BuiltInCategory.OST_CableTrayFitting).WhereElementIsNotElementType()",
             discipline="electrical"),
    KindSpec("conduit",
             ".OfCategory(BuiltInCategory.OST_Conduit).WhereElementIsNotElementType()",
             comment="короба/трубы электропроводки", discipline="electrical"),
    KindSpec("conduit_fitting",
             ".OfCategory(BuiltInCategory.OST_ConduitFitting).WhereElementIsNotElementType()",
             discipline="electrical"),

    # ОВ
    KindSpec("mechanical_equipment",
             ".OfCategory(BuiltInCategory.OST_MechanicalEquipment).WhereElementIsNotElementType()",
             discipline="mechanical"),
    KindSpec("duct_fitting",
             ".OfCategory(BuiltInCategory.OST_DuctFitting).WhereElementIsNotElementType()",
             discipline="mechanical"),
    KindSpec("duct_terminal",
             ".OfCategory(BuiltInCategory.OST_DuctTerminal).WhereElementIsNotElementType()",
             comment="воздухораспределители", discipline="mechanical"),
    KindSpec("flex_duct",
             ".OfCategory(BuiltInCategory.OST_FlexDuctCurves).WhereElementIsNotElementType()",
             discipline="mechanical"),
    KindSpec("space",
             ".OfCategory(BuiltInCategory.OST_MEPSpaces).WhereElementIsNotElementType()",
             comment="пространства ОВК — не то же, что помещения АР",
             discipline="mechanical"),

    # ВК
    KindSpec("plumbing_fixture",
             ".OfCategory(BuiltInCategory.OST_PlumbingFixtures).WhereElementIsNotElementType()",
             discipline="plumbing"),
    KindSpec("pipe_fitting",
             ".OfCategory(BuiltInCategory.OST_PipeFitting).WhereElementIsNotElementType()",
             discipline="plumbing"),
    KindSpec("pipe_accessory",
             ".OfCategory(BuiltInCategory.OST_PipeAccessory).WhereElementIsNotElementType()",
             comment="арматура: задвижки, клапаны", discipline="plumbing"),
    KindSpec("flex_pipe",
             ".OfCategory(BuiltInCategory.OST_FlexPipeCurves).WhereElementIsNotElementType()",
             discipline="plumbing"),
    KindSpec("sprinkler",
             ".OfCategory(BuiltInCategory.OST_Sprinklers).WhereElementIsNotElementType()",
             discipline="plumbing"),

    # АР — то, чего не хватало в собственном разделе
    KindSpec("railing",
             ".OfCategory(BuiltInCategory.OST_StairsRailing).WhereElementIsNotElementType()",
             comment="ограждения и перила", discipline="architectural"),
    KindSpec("ramp",
             ".OfCategory(BuiltInCategory.OST_Ramps).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("curtain_panel",
             ".OfCategory(BuiltInCategory.OST_CurtainWallPanels).WhereElementIsNotElementType()",
             comment="панели витража, включая витражные двери",
             discipline="architectural"),
    KindSpec("curtain_mullion",
             ".OfCategory(BuiltInCategory.OST_CurtainWallMullions).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("furniture",
             ".OfCategory(BuiltInCategory.OST_Furniture).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("casework",
             ".OfCategory(BuiltInCategory.OST_Casework).WhereElementIsNotElementType()",
             comment="встроенная мебель", discipline="architectural"),
    KindSpec("specialty_equipment",
             ".OfCategory(BuiltInCategory.OST_SpecialityEquipment).WhereElementIsNotElementType()",
             discipline="architectural"),
    KindSpec("area",
             ".OfCategory(BuiltInCategory.OST_Areas).WhereElementIsNotElementType()",
             discipline="architectural"),

    # общее для всех разделов
    KindSpec("generic_model",
             ".OfCategory(BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()",
             comment="обобщённые модели — ими пользуется каждый раздел",
             discipline="shared"),
    KindSpec("part",
             ".OfCategory(BuiltInCategory.OST_Parts).WhereElementIsNotElementType()",
             discipline="shared"),
)})

# Escape value (SPEC 12.8): schema admits it so decoding can't derail; the
# compiler answers with GROUND_UNSUPPORTED_KIND -> recipe-path handoff.
KIND_ESCAPE = "other"

# ── Filters (query `where`) ──────────────────────────────────────────────────
# Closed set; each is a (json_field, value_type) pair the compiler lowers to a
# C# predicate. Kept deliberately small for v1.
# value_type + optional kind restriction (a filter reading a wall-only BIP on
# doors would be a silent-wrong answer — restricted filters refuse instead).
FILTERS: Mapping[str, Mapping[str, Any]] = freeze_registry_mapping({
    "level_name": {"type": str},     # Element.LevelId -> Level with this exact name (trimmed)
    "name_contains": {"type": str},  # Element.Name contains (OrdinalIgnoreCase)
    # 2026-07-16 live prod case («выдели несущие стены»: model invented
    # STATIC_WALL_BASE_IMAGE / Wall.Structural, ~5 min of repair): the truth
    # is WALL_STRUCTURAL_SIGNIFICANT, encoded here once.
    "structural": {"type": bool, "kinds": ("wall",)},
})

LIST_FIELDS = ("id", "name", "category", "type_name", "level_name")
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 500


# ── Op registry ──────────────────────────────────────────────────────────────
class ReferenceKind(str, Enum):
    """Static type of an emitter-owned ``__el_<op-id>`` reference."""

    ELEMENT = "element"
    WALL = "wall"
    LEVEL = "level"
    FAMILY_SYMBOL = "family_symbol"


@dataclass(frozen=True)
class ParamSpec:
    name: str
    # `path` (wave/arch, 2026-07-29) — ОТКРЫТАЯ ломаная 2..64 точек [x,y] мм,
    # намеренно отдельный род от `pts`: `pts` требует >=3 точек и ненулевой
    # ПЛОЩАДИ, то есть по построению описывает замкнутое кольцо (контур
    # перекрытия). Путь ограждения кольцом не является — прямой марш это две
    # точки и нулевая площадь, — и под `pts` он был бы отвергнут как
    # «вырожденный контур».
    kind: str    # kind_enum|filters|int|str|fields|target|pt_xy|pt_xyz|mm|deg|num|sel|target_w|value|pts|pts_list|path|enum|arc
    required: bool = False
    default: Any = None
    min_val: Optional[int] = None
    max_val: Optional[int] = None
    choices: tuple = ()          # for kind == "enum"
    # Empty means ``by=ref`` is forbidden.  ELEMENT is the supertype accepted
    # by generic Element consumers; narrower kinds require an exact producer.
    ref_kinds: tuple[ReferenceKind, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "choices", tuple(self.choices))
        object.__setattr__(self, "ref_kinds", tuple(self.ref_kinds))
        object.__setattr__(self, "default", _freeze_param_default(
            self.default, field_name=f"{self.name}.default"))
        if self.ref_kinds:
            if self.kind not in ("sel", "target_w", "refs_w"):
                raise ValueError(
                    f"{self.name}: only selector params can accept refs")
            if any(not isinstance(item, ReferenceKind)
                   for item in self.ref_kinds):
                raise TypeError(f"{self.name}: ref_kinds must be typed")
            if len(self.ref_kinds) != len(set(self.ref_kinds)):
                raise ValueError(f"{self.name}: duplicate ref_kinds")

    def accepts_reference(self, producer: ReferenceKind | None) -> bool:
        if not isinstance(producer, ReferenceKind):
            return False
        return (
            producer in self.ref_kinds
            or ReferenceKind.ELEMENT in self.ref_kinds
        )


def _freeze_param_default(value: Any, *, field_name: str) -> Any:
    """Copy a JSON-shaped default into an immutable value graph.

    Registry defaults are process-wide compiler semantics. Lists become
    tuples (SDK/schema adapters already lower tuples to JSON arrays); mappings
    and sets are rejected until they have an explicit immutable wire model.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_param_default(
            item, field_name=f"{field_name}[{index}]")
                     for index, item in enumerate(value))
    if isinstance(value, (dict, set, frozenset, bytearray)):
        raise TypeError(
            f"{field_name}: mutable/ambiguous registry default "
            f"{type(value).__name__} is forbidden")
    raise TypeError(
        f"{field_name}: unsupported registry default {type(value).__name__}")


class EffectKind(str, Enum):
    """Closed model-state effect of one operation."""

    READ = "read"
    CREATE = "create"
    MUTATE = "mutate"
    DELETE = "delete"


class IdentityCardinality(str, Enum):
    """Number of primary Revit identities carried by an op result."""

    NONE = "none"
    ONE = "one"
    MANY = "many"


def _result_element_id(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value > 0
    if not isinstance(value, str) or not value:
        return False
    try:
        return int(value) > 0 and str(int(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True)
class ResultSpec:
    """Typed wire identity and intra-program reference contract.

    ``identity_field`` names independent execution evidence in the per-op
    result row.  ``reference_kind`` is present only when the result denotes
    one emitter-owned ``__el_<op-id>`` value that later selectors may address.
    The two facts are deliberately separate: a group or a deleted element has
    identity evidence but is not a valid forward reference producer.
    """

    identity_cardinality: IdentityCardinality
    identity_field: str | None = None
    reference_kind: ReferenceKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity_cardinality, IdentityCardinality):
            raise TypeError("result identity_cardinality must be typed")
        if self.identity_cardinality is IdentityCardinality.NONE:
            if self.identity_field is not None or self.reference_kind is not None:
                raise ValueError("identity-free result cannot be referenceable")
            return
        if not isinstance(self.identity_field, str) or not self.identity_field:
            raise ValueError("identity-bearing result needs identity_field")
        if (self.reference_kind is not None
                and not isinstance(self.reference_kind, ReferenceKind)):
            raise TypeError("result reference_kind must be typed")
        if (self.reference_kind is not None
                and self.identity_cardinality is not IdentityCardinality.ONE):
            raise ValueError("only a single-identity result can be referenced")

    @property
    def referenceable(self) -> bool:
        return self.reference_kind is not None

    def identity_present(self, row: Mapping[str, Any]) -> bool:
        """Validate independent primary identity evidence in one result row."""

        if self.identity_cardinality is IdentityCardinality.NONE:
            return True
        if not isinstance(row, Mapping) or self.identity_field not in row:
            return False
        value = row[self.identity_field]
        if self.identity_cardinality is IdentityCardinality.ONE:
            return _result_element_id(value)
        return (
            isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
            and len(value) > 0
            and all(_result_element_id(item) for item in value)
        )


RESULT_QUERY = ResultSpec(IdentityCardinality.NONE)
RESULT_ELEMENT = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.ELEMENT)
RESULT_WALL = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.WALL)
RESULT_LEVEL = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.LEVEL)
RESULT_FAMILY_SYMBOL = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.FAMILY_SYMBOL)
RESULT_UNREFERENCED_ELEMENT = ResultSpec(IdentityCardinality.ONE, "id")
RESULT_DELETED_ELEMENT = ResultSpec(
    IdentityCardinality.ONE, "deleted_id")
RESULT_MOVED_ELEMENTS = ResultSpec(
    IdentityCardinality.MANY, "moved_ids")
RESULT_NETWORK_SEGMENTS = ResultSpec(
    IdentityCardinality.MANY, "segment_ids")


@dataclass(frozen=True)
class OpSpec:
    name: str
    family: str                              # "query" | "authoring" ("modify" later)
    params: tuple[ParamSpec, ...]
    # capability cells this op covers, as (action, object_kind) pairs — the
    # cube reads these via export_capability_cells(). Full pairs only (13.2).
    capability: tuple[tuple[str, str], ...]
    post: str                                 # human-readable postcondition contract
    effect: EffectKind
    result: ResultSpec
    reads_model: bool = True
    writes_model: bool = False                # query family invariant: always False
    # authoring only: selector params ground.py must resolve, as
    # (param_name, snapshot_pool, required) triples. The pool names the census
    # slice ("levels", "wall_types", "pipe_types", "piping_system_types").
    grounded: tuple[tuple[str, str, bool], ...] = ()
    # Wave A2 (registry-онтология): the op's witness tolerances, keyed by
    # obligation aspect ("endpoint_mm", "height_mm", ...).  Values are the
    # EXACT numbers the emitters historically inlined (byte-parity discipline:
    # no "improved" figures) so each number lives in ONE place.
    #
    # 03.08 — ЗАКОН ПРОВЕНАНСА (emit_model.py): эмиттеры больше НЕ читают
    # этот словарь напрямую.  Число попадает в C# только объектом
    # `emit_model.tolerance(op, key)`, и витнес, объявивший допуск, обязан
    # содержать строку, которую этот объект сам отрендерил.  Поэтому:
    #   * ключа, которому здесь никто не отвечает, эмиссия не переживёт;
    #   * каждое `±<число>` из `post` обязано лежать ЗДЕСЬ (закон 3);
    #   * мёртвая запись здесь — тоже дефект: её ловит возмущающий оракул
    #     (tests/test_tolerance_provenance.py).
    tolerances: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        params = tuple(self.params)
        if any(not isinstance(param, ParamSpec) for param in params):
            raise TypeError(f"{self.name}: params must contain ParamSpec")
        capability = tuple(tuple(cell) for cell in self.capability)
        grounded = tuple(tuple(binding) for binding in self.grounded)
        copied_tolerances = dict(self.tolerances)
        for key, value in copied_tolerances.items():
            if not isinstance(key, str) or not key:
                raise TypeError(f"{self.name}: tolerance keys must be strings")
            if (not isinstance(value, (int, float))
                    or isinstance(value, bool)):
                raise TypeError(
                    f"{self.name}.{key}: tolerance must be numeric")
        object.__setattr__(self, "params", params)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(self, "grounded", grounded)
        object.__setattr__(
            self, "tolerances", MappingProxyType(copied_tolerances))

# Write families share one transaction; only query is exclusive.
WRITE_FAMILIES = ("authoring", "modify")
