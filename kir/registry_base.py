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
from typing import Any, Mapping, Optional, Sequence

IR_VERSION = "1.0"
REVIT_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

# The legacy execution result is a flat dictionary. These program-level keys
# can overwrite a per-operation row, so they cannot be authored operation IDs.
# Keep the input validator and generated schema on the same wire contract.
# Transport names such as "result" are not reserved by the emitter.
PROGRAM_RESULT_METADATA_KEYS = frozenset({
    "ok", "postcondition_violations", "revit_warnings",
    "revit_errors_resolved", "post", "residual_effect",
})

# ── Vocabulary deltas (coordinator arbitration 13.2/13.3) ────────────────────
# New object_kinds the registry contributes to capability_vocab. schedule_field
# deliberately deferred. Bare actions (action with no object_kind) are banned
# forever: _lint_registry() enforces every cell is a full (action, object_kind).
OBJECT_KINDS_ADDED = ("geometry", "document")
# consult stays in the action vocabulary but routes to the wiki knowledge path;
# by definition it has no IR ops. The cube renders these cells "route-only".
ROUTE_ONLY_ACTIONS = {"consult": "wiki-knowledge-path"}
# SPEC §16 verdict: the release-builder's kind-less placeholder «action×-» dies.
# The cube validator's hard error was right; orphan cards map to
# geometry/document/view via the migration table, never released with "-".
BANNED_OBJECT_KIND_PLACEHOLDERS = ("-", "")

# Single defaults table (ir_defaults discipline: one source for compiler,
# schema and future reference-interpreter — divergence reopens the fork).
DEFAULTS = {
    "wall": {"height_mm": 3000.0},
}


# ── Kind table: the closed enum that killed the pdfCount=0 bug class ────────
# Each kind maps to ONE collector idiom, written and reviewed once. `where_cs`
# is an extra predicate over the collected element (C# lambda body over `e`).
# Every idiom used here exists unchanged in Revit 2021-2026 (version-safe set).
# Project disciplines. ONE dictionary for the whole package: these are
# exactly the strings `__Discipline` in decompile/extract.py already
# returns when it guesses a link's discipline from tokens in its name
# (АР/КР/ОВ/ВК/ЭОМ). Setting up a second dictionary for views would mean
# setting up a second source of truth about the same thing.
#
# `shared` is not "unknown" but "belongs to everyone": levels, grids,
# views, and sheets are read by both АР and КР, and by the engineering
# disciplines. A view missing a discipline is a bug in the table, and it
# is caught by a test, not by convention.
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
    # The project discipline the view belongs to. Needed because work is
    # done BY DISCIPLINE: its own performer for АР, its own for КР, its
    # own for every engineering discipline. The discipline recorded in the
    # table lets both the instrument's description and its write
    # permission be narrowed — that is, it makes the boundary checkable
    # rather than promised in a prompt.
    discipline: str = "shared"

    def __post_init__(self) -> None:
        if self.discipline not in DISCIPLINES:
            raise ValueError(
                f"KindSpec {self.name!r}: unknown discipline "
                f"{self.discipline!r}; expected one of {sorted(DISCIPLINES)}")


KINDS: dict[str, KindSpec] = {k.name: k for k in (
    # The canonical regression case (2026-07-16 incident): PDF underlays are
    # raster ImageInstance elements, NOT ImportInstance — encoded here once.
    # 🔴 A TYPE-NAME-BASED SIGNAL IS UNSOUND BY CONSTRUCTION (30.08.2026,
    # finding S-07). It used to say `__TypeNameOf(e).EndsWith(".pdf")`, i.e.
    # a suffix on the USER-EDITABLE type name. Revit itself appends suffixes
    # to this name, and both forms were found in the live corpus
    # (measurement of 30.08 across 81 L0 decompiles):
    #
    #     page of a multi-page PDF   -> "How to Use this Project.pdf - 1"
    #     duplicate on re-import     -> "01_Ситуационный план-01_Сит. план.pdf (2)"
    #
    # Numbers: rasters have 70 distinct type names, 165 instances. The
    # strict suffix catches 2 types / 2 instances; the corpus actually has
    # 9 underlay types / 21 instances. That is, the instrument found 2 of
    # 21 and SILENTLY missed 19 — 90 %.
    #
    # 🔴 THE "THIS IS A PDF" PROPERTY DOES NOT EXIST IN ANY OF THE SIX
    # TARGET VERSIONS — checked against `RevitAPI.xml` 2021…2026: `ImageType`
    # has `Source` (`ImageTypeSource`: Internal/Import/Link), `PageNumber`,
    # `Path`, and no `IsPdf` at all. So what is asked is the KIND plus THE
    # FILE ITSELF:
    #   * `Source != Internal` — kind: the image came FROM A FILE, rather
    #     than being saved by the project («Save to Project as Image», for
    #     which `Path` is empty);
    #   * the `Path` extension — path to the source file. It is NOT edited
    #     by renaming the type: Revit appends the `(2)` and `- 1` suffixes
    #     to the NAME.
    # This is not "name instead of kind", but the only PDF discriminator
    # the API provides at all — and it is taken from the FILE, not from
    # the label.
    KindSpec("pdf_underlay",
             ".OfClass(typeof(ImageInstance))",
             where_cs=(
                 '__ImageTypeOf(e) != null '
                 '&& __ImageTypeOf(e).Source != ImageTypeSource.Internal '
                 '&& __ImageTypeOf(e).Path != null '
                 '&& __ImageTypeOf(e).Path.EndsWith(".pdf", '
                 'StringComparison.OrdinalIgnoreCase)'
             ),
             comment="PDF underlay = file-backed ImageInstance whose SOURCE FILE "
                     "path ends .pdf; the type NAME is user-renamable and Revit "
                     "appends page/duplicate suffixes to it (S-07)",
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
    # 🔴 A GROUP COULD BE BUILT AND COULD NOT BE COUNTED (measurement
    # 03.09.2026, live Revit). `create_group` is a registry write-op, and
    # it had no matching query view: `query_count(kind="group")` answered
    # «неизвестный kind». The author builds and CANNOT VERIFY what was
    # built — the same "op exists, no view exists" asymmetry that the tree
    # had already closed for duct/pipe placeholders on 14.08.
    #
    # The cost was visible as a number: for a group of two walls with
    # THREE placements, `rehearsal.rehearse` declares 28 elements, `score()`
    # and the recipe — 24, while the wire receives ONE id (the map of what
    # was created is keyed by OP, not by element). Three carriers, three
    # numbers, and there was nothing to ask the document.
    #
    # CLASS, NOT CATEGORY: `Group` is an API class, and it is also what
    # distinguishes a group instance from its type (`GroupType`);
    # `.OfCategory(OST_IOSModelGroups)` would pull in types as well, and
    # `WhereElementIsNotElementType` would have to be kept as a second
    # carrier of the same distinction. Revit showed the category live: the
    # built group was read back as `OST_IOSModelGroups`.
    # 🔴 THE NAME IS FULLY QUALIFIED, AND THAT WAS BOUGHT BY A LIVE FAILURE
    # WITHIN THE HOUR. The short `typeof(Group)` gave `CS0104: 'Group' is
    # an ambiguous reference between 'Autodesk.Revit.DB.Group' and
    # 'System.Text.RegularExpressions.Group'` — the query template carries
    # `using System.Text.RegularExpressions`. The 6/6 gate did NOT catch
    # this: it compiles the bodies of OPS, and the server-side `query`
    # template is not within its scope. Found by a live run, not by the
    # suite.
    KindSpec("group", ".OfClass(typeof(Autodesk.Revit.DB.Group))",
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

    # ── Disciplines other than АР ───────────────────────────────────────────
    # Before 27.07 the table knew 9 architectural views and exactly ONE per
    # engineering discipline — meaning there was nothing to ask "how many
    # panels" or "which fixtures" with, and any refusal looked like a
    # compiler failure, even though it was a missing row in the table. Work
    # is done by discipline, each with its own performer, so the table must
    # cover disciplines proportionately, rather than to the extent of
    # whatever model it happened to be started from.
    #
    # Each row is one collector and nothing more; the check is the same
    # one throughout: the Roslyn gate compiles the emission on six Revit
    # versions, and a category missing in some version fails it rather
    # than sailing through silently.

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
    # IT COULD BE BUILT, BUT COULD NOT BE COUNTED (14.08.2026). Placeholders
    # have their own write-ops (`create_duct_placeholder`,
    # `create_pipe_placeholder`), but there was no query view for them — a
    # live failure on 13.08 asked for exactly these two names. The
    # "op exists, no view exists" asymmetry is worse than having neither:
    # the model builds and cannot verify what it built.
    #
    # A SEPARATE VIEW, NOT A FILTER ON `duct`/`pipe`. The argument that
    # stood here 🔴 IS REFUTED BY A LIVE MEASUREMENT OF 03.09.2026 — it used
    # to read: "Revit does not give the placeholder its own category, it
    # stays in OST_DuctCurves/OST_PipeCurves and is distinguished ONLY by
    # the IsPlaceholder bit; so query_count(kind="duct") counts placeholders
    # together with the real ones." IT DOES GIVE ONE:
    # OST_PlaceHolderDucts / OST_PlaceHolderPipes, both compile on
    # 2021-2026. So `query_count(kind="duct")` never counted placeholders,
    # and the mixing that the separate view was built to prevent never
    # existed.
    #
    # THE VIEW STAYS, AND THAT IS A DECISION, NOT INERTIA: collecting by
    # CLASS with the `IsPlaceholder` predicate answers the same question
    # and works; replacing it with `.OfCategory(OST_PlaceHolder*)` would be
    # an emission edit on live prod for the sake of an identical answer,
    # i.e. risk without payoff. Stated here so the next reader does not
    # mistake the argument above for one still in force.
    #
    # `IsPlaceholder` LIVES ON THE CONCRETE CLASS, NOT ON `MEPCurve`: a
    # compilation measurement of 14.08 — `MEPCurve.IsPlaceholder` is CS1061
    # on all six versions, while `Duct`/`Pipe` carry it 6/6. So the
    # collection is done by CLASS, and the predicate resolves against the
    # same one.
    KindSpec("duct_placeholder",
             # 🔴 THE COLLECTOR STAYS BY CLASS, AND THIS DECISION WAS
             # CHECKED BY ITS COST (03.09.2026). I had added
             # `.OfCategory(BuiltInCategory.OST_PlaceHolderDucts)` here so
             # the coverage gate would see the kind's category — and the
             # BYTE-PARITY gate immediately named the cost: 12 emissions
             # (two kinds × six versions) diverged from the frozen copy.
             # That is, visibility would have been paid for with an
             # emission edit on live prod, and release in parity requires
             # its OWN pin and exists for INTENTIONAL changes, not for the
             # instrument's convenience. The category is declared as DATA
             # exactly where it is asked for — in
             # `test_query_count_covers_buildable_categories`.
             ".OfClass(typeof(Autodesk.Revit.DB.Mechanical.Duct))",
             where_cs="((Autodesk.Revit.DB.Mechanical.Duct)e).IsPlaceholder",
             comment="заготовки воздуховодов — та же категория, что у настоящих",
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
    # Counterpart to `duct_placeholder` — the argument in full stands
    # there, at the duct.
    KindSpec("pipe_placeholder",
             # 🔴 THE COLLECTOR STAYS BY CLASS, AND THIS DECISION WAS
             # CHECKED BY ITS COST (03.09.2026). I had added
             # `.OfCategory(BuiltInCategory.OST_PlaceHolderPipes)` here so
             # the coverage gate would see the kind's category — and the
             # BYTE-PARITY gate immediately named the cost: 12 emissions
             # (two kinds × six versions) diverged from the frozen copy.
             # That is, visibility would have been paid for with an
             # emission edit on live prod, and release in parity requires
             # its OWN pin and exists for INTENTIONAL changes, not for the
             # instrument's convenience. The category is declared as DATA
             # exactly where it is asked for — in
             # `test_query_count_covers_buildable_categories`.
             ".OfClass(typeof(Autodesk.Revit.DB.Plumbing.Pipe))",
             where_cs="((Autodesk.Revit.DB.Plumbing.Pipe)e).IsPlaceholder",
             comment="заготовки труб — та же категория, что у настоящих",
             discipline="plumbing"),
    KindSpec("sprinkler",
             ".OfCategory(BuiltInCategory.OST_Sprinklers).WhereElementIsNotElementType()",
             discipline="plumbing"),

    # АР — what was missing in its own discipline
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

    # common to all disciplines
    KindSpec("generic_model",
             ".OfCategory(BuiltInCategory.OST_GenericModel).WhereElementIsNotElementType()",
             comment="обобщённые модели — ими пользуется каждый раздел",
             discipline="shared"),
    KindSpec("part",
             ".OfCategory(BuiltInCategory.OST_Parts).WhereElementIsNotElementType()",
             discipline="shared"),
)}

# Escape value (SPEC 12.8): schema admits it so decoding can't derail; the
# compiler answers with GROUND_UNSUPPORTED_KIND -> recipe-path handoff.
KIND_ESCAPE = "other"

# ── Envelope fields ───────────────────────────────────────────────────────
#: Two fields carried by EVERY op in a program, yet present in NONE of the
#: `OpSpec.params` — they are not the op's payload, but its ENVELOPE:
#: `op` is the discriminator by which the operation itself is recognized;
#: `id` is its name, by which `by_ref` references are resolved.
#: `compiler._validate_op` already built this set BY HAND, inline, in
#: exactly the place that checks for extraneous fields
#: (`known = {"op", "id"} | {p.name for p in ...}`) — here it is NAMED,
#: rather than duplicated, so that a "genuine registry slot" has ONE
#: source both for checking extraneous fields and for any instrument that
#: asks "is this even an addressable spot in the program at all?" (see
#: `tools/mission/refusal_actionability.py`, a live measurement of
#: 25.08.2026: a `query_count`/`query_list`-like instrument treated only
#: `ParamSpec.name` as an ADDRESS, meaning a refusal on a
#: `kind="column"`-like envelope fact — «неизвестный op» on the `op` field,
#: «дубликат id» on the `id` field — could NEVER name an address, not
#: because there was nowhere to take it from, but because the slot table
#: did not know about the envelope).
ENVELOPE_FIELDS: frozenset[str] = frozenset({"op", "id"})

# ── Filters (query `where`) ──────────────────────────────────────────────────
# Closed set; each is a (json_field, value_type) pair the compiler lowers to a
# C# predicate. Kept deliberately small for v1.
# value_type + optional kind restriction (a filter reading a wall-only BIP on
# doors would be a silent-wrong answer — restricted filters refuse instead).
FILTERS: dict[str, dict] = {
    "level_name": {"type": str},     # Element.LevelId -> Level with this exact name (trimmed)
    "name_contains": {"type": str},  # Element.Name contains (OrdinalIgnoreCase)
    # 2026-07-16 live prod case («выдели несущие стены»: model invented
    # STATIC_WALL_BASE_IMAGE / Wall.Structural, ~5 min of repair): the truth
    # is WALL_STRUCTURAL_SIGNIFICANT, encoded here once.
    "structural": {"type": bool, "kinds": ("wall",)},
}

LIST_FIELDS = ("id", "name", "category", "type_name", "level_name")
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 500

# ── query_level_plan: фон для листа (13.09.2026) ─────────────────────────────
#
# 🔴 ЗАЧЕМ ЭТОТ ОП СУЩЕСТВУЕТ. Слово владельца: «остальное здание становится
# полупрозрачным». Гасить было нечего: у листа КИР нет фона, и не по забывчивости,
# а потому что чтения геометрии ПАЧКОЙ в дереве не было ни одного —
# `prune_ground_snapshot` держит отметки и сечения типов, `LIST_FIELDS` выше не
# несёт ни одной координаты, а `query_inspect` даёт `bbox_mm` по ОДНОМУ элементу
# за оп. Этаж в 200 стен потребовал бы 200 опов.
#
# Форма согласована с W (кадр) файлом, а не правкой его файлов:
# `.work/prod-20260913/W-preview/GROUND_CONTRACT.md`, раздел «Ответы W».

#: Рода плановых следов. Проёмы СВОИМИ строками и В УМОЛЧАНИИ — ответ W 4:
#: лист адресует каждый предмет своим `data-el`, и проём, выведенный из хозяина,
#: был бы вторым источником правды о том, где он стоит; а стена, нарисованная
#: без проёма, — это на листе ДРУГАЯ стена.
LEVEL_PLAN_INCLUDE = ("walls", "floors", "columns", "openings")

#: Цена перекрытий. Умолчание `box` — ответ W 1, и он условный: габарит
#: рисуется ролью `outline`, а не `solid`, иначе залитый прямоугольник накрыл бы
#: крыло, которого у Г-образной плиты нет. Поэтому `detail` едет В КАЖДОЙ СТРОКЕ:
#: без него кадр не отличит контур от габарита и не сможет пометить огрубление.
LEVEL_PLAN_DETAIL = ("box", "sketch")

#: Потолок строк. Стены этажа считаются сотнями, поэтому шире, чем у
#: `query_list`; порог назван, чтобы отказ мог его напечатать.
LEVEL_PLAN_LIMIT_DEFAULT = 400
LEVEL_PLAN_LIMIT_MAX = 1000


# ── Op registry ──────────────────────────────────────────────────────────────
class ReferenceKind(str, Enum):
    """Static type of an emitter-owned ``__el_<op-id>`` reference."""

    ELEMENT = "element"
    WALL = "wall"
    LEVEL = "level"
    FAMILY_SYMBOL = "family_symbol"
    #: A wall type CREATED by this same program (`create_wall_type`).
    #:
    #: 🔴 WHY A SEPARATE KIND, NOT `ELEMENT`. Measurement of 23.08.2026:
    #: grounding resolves CATALOG names against a snapshot taken BEFORE the
    #: run, and a type created within this same program is not in it BY
    #: CONSTRUCTION. This is exactly what burned levels: `create_level`
    #: stood at the head, and `create_wall.level` addressed it BY NAME —
    #: and got «levels: «L03_K3_+13,150» не найден». The cure is not
    #: operation order but the KIND OF THE REFERENCE.
    #:
    #: The kind is deliberately narrow: `ELEMENT` would let the result of
    #: ANY create operation into `create_wall.type`, and a wall would
    #: accept a reference to a door. Checking the kind is the only thing
    #: standing between the program and that outcome.
    WALL_TYPE = "wall_type"
    #: Types of HOST elements created by the same program — floors, roofs,
    #: ceilings. Set up on 24.08.2026 by measurement, not by symmetry.
    #:
    #: 🔴 WHY THREE KINDS, NOT ONE `HOST_TYPE` FOR ALL. Narrowness of kind
    #: is the only thing standing between `create_floor.type` and a
    #: reference to a ROOF type: in C# both resolve via
    #: `doc.GetElement(id) as XType`, and a mix-up gives `null`, i.e. a
    #: RUNTIME refusal instead of a COMPILE-TIME one. A shared kind would
    #: give up exactly the guarantee this language exists for.
    #:
    #: 🔴 WHY AT ALL. Measurement of 24.08.2026 on porting K3 into a clean
    #: «Проект1»: 0 of 82 floors built, 0 of 36 roofs, 0 of 18 ceilings —
    #: even though the operations EXIST and are present in the programs
    #: (`create_floor` 46, `create_roof` 27, `create_ceiling` 1). Each
    #: addresses its type BY NAME, and grounding resolves names against a
    #: snapshot taken BEFORE the run: a type created by this same program
    #: is not in it BY CONSTRUCTION. Exactly the defect that burned levels,
    #: and then walls, and it is cured the same way — by the KIND OF THE
    #: REFERENCE.
    FLOOR_TYPE = "floor_type"
    ROOF_TYPE = "roof_type"
    CEILING_TYPE = "ceiling_type"


class RegistryDefault:
    """The registry default in the python front's signature — SHOW it, but
    do not WRITE it in.

    🔴 LIVES HERE, ON `ParamSpec.default`, NOT ON EITHER OF THE FRONTS
    (02.09.2026). There are TWO fronts — `sdk.py` (builders) and `dsl.py`
    (the scripting door) — and the law for them is ONE. While the class
    lived in `dsl.py`, the other front did not know it and could not know
    it: `dsl` imports `sdk`, and the reverse edge would close a cycle. The
    result was exactly what the class was written against — MEASURED:

        sdk.create_wall(...) without height_mm  -> FieldOrigin.EXPLICIT
        the same omission via raw JSON          -> FieldOrigin.REGISTRY_DEFAULT

    One intent by the author, different provenance — depending on the
    door. Two places that must declare the same thing drift apart without
    a single point of intersection across files.

    The measurement of 03.08 that this class exists because of. A field
    written in with the default value, and a field that is OMITTED, are
    NOT the same thing to the compiler:

        omitted  -> FieldOrigin.REGISTRY_DEFAULT, plan_digest 2df7a3bc…
        explicit -> FieldOrigin.EXPLICIT,         plan_digest eb267955…

    That is, a python front that writes in defaults (a) erases the
    provenance — the mechanism `midend.FieldOrigin` was written for — and
    (b) changes the identity of the program's PROOF, without changing
    anything in the building. And the plan's signature ties together all
    the subsequent evidence.

    That is why the default lives in the signature as TEXT (visible in
    `help`), and does not make it into the JSON until the author names it
    themselves.
    """

    #: 🔴 AN IDENTIFYING MARKER INSTEAD OF CLASS IDENTITY. Reloading the
    #: module sets up a SECOND class, and `isinstance` on functions
    #: captured earlier answers "no". The marker survives a reload;
    #: `isinstance` is kept alongside it as cheaper and reliable in
    #: ordinary life.
    __kir_registry_default__ = True

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self) -> str:
        return repr(self.value)

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other) -> bool:
        if isinstance(other, RegistryDefault):
            return other.value == self.value
        return other == self.value          # the drift guard compares against the registry

    def __hash__(self) -> int:
        return hash(("_RegistryDefault", repr(self.value)))


def is_registry_default(value) -> bool:
    """Marker OR identity — the argument is at the trait itself, above."""
    return (isinstance(value, RegistryDefault)
            or getattr(value, "__kir_registry_default__", False))


@dataclass(frozen=True)
class ParamSpec:
    name: str
    # `path` (wave/arch, 2026-07-29) — an OPEN polyline of 2..64 [x,y] mm
    # points, deliberately a separate kind from `pts`: `pts` requires >=3
    # points and a nonzero AREA, i.e. by construction it describes a
    # closed ring (a floor contour). A railing path is not a ring — a
    # straight run is two points and zero area — and under `pts` it would
    # be rejected as a «вырожденный контур».
    # `sel_list` (wave/datums, 2026-08-09) — a LIST of selectors from one
    # pool, i.e. the plural of the `sel` kind, exactly as `refs_w` relates
    # to `target_w`. Set up for `create_multistory_stairs.levels`: Revit
    # accepts MULTIPLE levels in one call (`ConnectLevels`), and a list of
    # element_ids instead of names would be a regression of the language —
    # levels in KIR are addressed by name everywhere.
    kind: str    # kind_enum|filters|int|str|fields|target|pt_xy|pt_xyz|mm|deg|num|sel|sel_list|target_w|value|pts|pts_list|path|enum|arc
    required: bool = False
    default: Any = None
    min_val: Optional[int] = None
    max_val: Optional[int] = None
    choices: tuple = ()          # for kind == "enum"
    # Empty means ``by=ref`` is forbidden.  ELEMENT is the supertype accepted
    # by generic Element consumers; narrower kinds require an exact producer.
    ref_kinds: tuple[ReferenceKind, ...] = ()
    # Most human-authored ``str`` parameters are canonicalised with
    # ``strip()`` and reject an empty value.  A few Revit identity parameters
    # are different: the exact string (including an empty value or outer
    # whitespace) is model state which must survive a reverse/forward round
    # trip byte-for-byte.  Such a field opts into that narrower contract
    # explicitly; changing the behaviour of every existing ``str`` parameter
    # would silently rewrite already-valid programs.
    exact_string: bool = False
    #: WHO DECIDES THIS FIELD'S VALUE. Set up on 19.08.2026 by a live
    #: benchmark.
    #:
    #: `create_wall.level` and `create_beam.level` look identical and work
    #: OPPOSITELY: a wall's level is assigned, while for a beam Revit
    #: DERIVES it from the curve's elevation and ignores the argument sent
    #: (measured on 27.07: L_01 @ 0 was passed with the curve at Z=3000 ->
    #: bound to L_01ДОО1_+2.500). The registry knew this IN PROSE — in the
    #: op's `post` and in the emitter's comment — and left the field
    #: `required=True`. The model was obligated to fill it in, it decided
    #: nothing, and 540 out of 540 beams landed at z=0 while «Этаж 5» was
    #: written down.
    #:
    #: A human reads the prose, an instrument reads the field. Hence the
    #: declaration:
    #:   "AUTHORED"          the value sent decides;
    #:   "DERIVED_BY_REVIT"  Revit computes it itself, the value sent
    #:                       DECIDES NOTHING.
    #: The same dictionary as `building_graph.py` uses for graph nodes —
    #: the concept already exists there and had not been applied to
    #: operation fields, where the ailment actually lives.
    authority: str = "AUTHORED"
    #: WHAT SILENTLY TAKES OVER IF THE FIELD IS OMITTED. A non-empty string
    #: only for fields whose omission CHANGES THE MECHANISM, rather than
    #: turning off a decoration.
    #:
    #: The distinction was bought by the same benchmark. Omitting
    #: `create_wall.arc` on a straight wall is normal, and staying silent
    #: about it is correct. Omitting `create_column.top_level` lifted the
    #: conditional obligation "top constraint == resolved top_level", and
    #: 420 columns silently ended up at 2500 mm instead of 3600–4500: not a
    #: single refusal, and three audits did not see it. Without this
    #: field, the rehearsal prints both cases IDENTICALLY, and the real
    #: signal drowns in the noise of optional decorations.
    omission_transfers: str = ""

    def __post_init__(self) -> None:
        if self.exact_string and self.kind != "str":
            raise ValueError(
                f"{self.name}: exact_string is only valid for str params")
        if self.authority not in ("AUTHORED", "DERIVED_BY_REVIT"):
            raise ValueError(
                f"{self.name}: authority must be AUTHORED or DERIVED_BY_REVIT, "
                f"got {self.authority!r}")
        if self.authority == "DERIVED_BY_REVIT" and self.omission_transfers:
            # A field that DECIDES NOTHING cannot "take over on omission":
            # Revit holds the power even when a value is passed too. The
            # two declarations together would describe an outcome that
            # does not exist.
            raise ValueError(
                f"{self.name}: DERIVED_BY_REVIT и omission_transfers вместе "
                "описывают несуществующий исход — власть уже не у автора")
        if self.ref_kinds:
            if self.kind not in ("sel", "sel_list", "target_w", "refs_w"):
                raise ValueError(
                    f"{self.name}: only selector params can accept refs")
            if any(not isinstance(item, ReferenceKind)
                   for item in self.ref_kinds):
                raise TypeError(f"{self.name}: ref_kinds must be typed")
            if len(self.ref_kinds) != len(set(self.ref_kinds)):
                raise ValueError(f"{self.name}: duplicate ref_kinds")

    def accepts_reference(self, producer: ReferenceKind | None) -> bool:
        """Whether the result of THIS producer is fit for THIS slot.

        🔴 `ELEMENT` MEANS "ANY INSTANCE", NOT "ANYTHING AT ALL" (25.08.2026,
        an audit finding, confirmed at its point of definition).

        `ELEMENT` in `ref_kinds` used to accept ANY kind, including type
        kinds — and by doing so gave up exactly the guarantee that narrow
        kinds were set up for. The `WALL_TYPE` and `FLOOR_TYPE` docstrings
        say this word for word: "a shared kind would give up exactly the
        guarantee this language exists for… a RUNTIME refusal instead of a
        COMPILE-TIME one."

        The narrowness held only at ONE end: a narrow consumer rejected a
        foreign kind (`create_wall.type` given a roof-type reference ->
        `KIR-L004`), while a wide one accepted a narrow one. Measurement:
        `move_elements.targets` accepted `WALL_TYPE`, `FLOOR_TYPE`,
        `ROOF_TYPE` — yet a type has neither position nor geometry, and
        `ElementTransformUtils.MoveElement` dies in Revit. There are 18 out
        of 71 such slots with `ELEMENT`.

        A TYPE KIND IS ACCEPTED ONLY WHEN NAMED. Slots where a type is
        legitimate (in Revit a type has its own parameters and can be
        deleted) name it EXPLICITLY through `ACCEPTS_TYPE_REFERENCE` —
        because that is a decision about each slot, not a blanket
        exemption.
        """
        if not isinstance(producer, ReferenceKind):
            return False
        if producer in self.ref_kinds:
            return True
        if ReferenceKind.ELEMENT not in self.ref_kinds:
            return False
        return producer not in TYPE_REFERENCE_KINDS


#: KINDS THAT DESCRIBE A TYPE, NOT AN INSTANCE.
#:
#: 🔴 SET UP ON 25.08.2026. A type has neither position, nor geometry, nor
#: a host: it cannot be moved, connected, tagged, measured by dimension,
#: or made a family's host. That is why `ELEMENT` ("any instance") does
#: NOT accept them, and a slot that needs a type must name it EXPLICITLY.
#:
#: The list is closed and is derived from the enumeration itself: a new
#: type kind must land here by a decision, not inherit behavior by
#: silence.
TYPE_REFERENCE_KINDS: frozenset = frozenset({
    ReferenceKind.WALL_TYPE,
    ReferenceKind.FLOOR_TYPE,
    ReferenceKind.ROOF_TYPE,
    ReferenceKind.CEILING_TYPE,
})


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
RESULT_WALL_TYPE = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.WALL_TYPE)
#: HOST TYPE KIND -> REVIT CLASS. THE SOLE AUTHORITY; there are two
#: readers: the registry (`create_wall_type.host_kind.choices`) and the
#: emitter (`authoring`).
#:
#: Here, not in the emitter, by our own named rule: a value read in two
#: places must be born in one. This dictionary's keys ARE the parameter's
#: `choices` — a test brings them together, so that a kind added in one
#: place and forgotten in the other fails red instead of building the
#: wrong class.
HOST_TYPE_CLASS: dict[str, str] = {
    "wall": "WallType",
    "floor": "FloorType",
    "roof": "RoofType",
    "ceiling": "CeilingType",
}

RESULT_FLOOR_TYPE = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.FLOOR_TYPE)
RESULT_ROOF_TYPE = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.ROOF_TYPE)
RESULT_CEILING_TYPE = ResultSpec(
    IdentityCardinality.ONE, "id", ReferenceKind.CEILING_TYPE)

#: WALL LAYER FUNCTIONS ARE A REVIT ENUM, NOT OUR OWN LIST.
#: `MaterialFunctionAssignment`, all eight members, checked against
#: `RevitAPI.xml` for 2021–2026. In the real data (K1, 92 layers) FIVE
#: occur — Finish1 24 · Finish2 32 · Substrate 18 · Insulation 16 ·
#: Structure 2 — but the list is closed by the ENUM, not by the sample:
#: a type whose layer comes in as `Membrane` must refuse on its own
#: merits, not because of our incompleteness.
WALL_LAYER_FUNCTIONS: tuple[str, ...] = (
    "Structure", "Substrate", "Insulation",
    "Finish1", "Finish2", "Membrane", "StructuralDeck", "None",
)

#: CEILING ON THE NUMBER OF LAYERS. Measurement of 23.08.2026 on K1: the
#: thickest assembly is 11 layers (`0→4 · 1→22 · 2→9 · 3→2 · 4→2 · 6→2 ·
#: 7→1 · 8→1 · 11→1`). 64 gives almost a sixfold margin and remains a
#: CHOSEN number, not a derived one — stated here so the next reader does
#: not mistake it for something measured.
WALL_LAYERS_MAX: int = 64

#: LAYER THICKNESS BOUNDS, mm. In the data: 2.5..400.0.
#:
#: 🔴 THE LOWER BOUND IS ZERO ON PURPOSE. A `Membrane` layer in Revit has
#: ZERO thickness by construction; a "strictly greater than zero" ban
#: would reject a legitimate membrane and would be our own invention, not
#: a safeguard.
#:
#: 🔴 THERE IS NO PREFLIGHT CHECK OF THE ASSEMBLY, AND THAT IS A
#: MEASUREMENT, NOT AN ASSUMPTION. The wave was written counting on
#: `CompoundStructure.IsValid` — IT DOES NOT EXIST: compilation against
#: the reference assemblies on 23.08.2026 gave 0/6 on three signatures
#: (`IsValid()`, `IsValid(Document)`, `IsValid(Document, bool, bool)`) and
#: 0/6 on `IsValidLayerList`, while the control (a member known not to
#: exist) also gave 0/6 — meaning the instrument does discriminate. The
#: sole judge of validity is the exception from `SetCompoundStructure`,
#: and the emission must catch it and turn it into a typed refusal with a
#: rollback, rather than promise a check that does not exist.
#: THE PLACEMENT TYPE WITHOUT WHICH THE OP DOES NOT WORK — A REGISTRY
#: DECISION.
#:
#: 🔴 SET UP ON 24.08.2026 FROM A LIVE MEASUREMENT. `placement_type` has
#: been read off Revit since 24.08 (`8b3e5f64`), but there was nowhere to
#: filter by it: the pool handed back candidates, of which none at all
#: might be fit. Live («Проект1», Revit 2026): `create_adaptive_component`
#: got `KIR-G102 «320 вариантов — default невозможен»` and five
#: candidates — curtain-wall mullions, callouts, railing supports, all
#: with `placement_type` of `ViewBased`/`OneLevelBased`. The refusal said,
#: in effect, «pick one of 320», while the correct answer was «there are
#: NO adaptives in the model, and there is nothing to choose from».
#:
#: HERE THERE IS ONLY WHAT WE OURSELVES HAVE NO CHOICE ABOUT.
#: `AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance`
#: requires an adaptive family — that is a fact of the API, not our own
#: taste. Pools where SEVERAL kinds are admissible (`place_family`: 26.0 %
#: of the corpus's instances are unfit, `TwoLevelsBased` 29 361) are NOT
#: entered here: their composition is a registry decision not yet made,
#: and entering it silently would mean acting as the owner.
#:
#: THE KEY is (op, parameter), not the pool: one pool feeds different ops
#: with different requirements, and `family_symbols` feeds all of them.
PLACEMENT_TYPES_REQUIRED: dict[tuple[str, str], frozenset[str]] = {
    ("create_adaptive_component", "symbol"): frozenset({"Adaptive"}),
}

#: COORDINATE LIMIT, mm — ONE FOR THE WHOLE TREE.
#:
#: Revit's working model extent is ~16 km from the origin; a coordinate
#: beyond that is a units error or garbage, and it used to drift all the
#: way to a late runtime refusal. We refuse statically, in the same place
#: as every other numeric bound (audit F12).
#:
#: 🔴 THE HOME WAS SET UP ON 25.08.2026, BECAUSE THERE WERE TWO COPIES,
#: AND CHECKS WERE NOT EVERYWHERE. `authoring_validation._COORD_LIMIT_MM`
#: and `connect._COORD_LIMIT_MM` each carried the same number separately
#: (the second with a note saying "same limit as authoring's" — meaning
#: the author KNEW about the copy and left it). And the `region` kind was
#: not checked AT ALL: a `rect` with an origin of 9e11 mm — 900 million
#: meters — was accepted, and the emission printed
#: `Line.CreateBound(P(900000000000.0, ...))`.
#:
#: The very same `create_ceiling` was refused via `pts` but sailed through
#: via `contour`. One value, two records, two verdicts.
COORD_LIMIT_MM: float = 16_000_000.0

#: THE FILE NAME DEPENDS ON THE LOCALE, AND THAT IS THE ONLY THING WE KNOW
#: AS A LIST. A Russian install (the director's measurement of 21.08.2026,
#: RVT 2026, 25+ .rft files in `...\\Family Templates\\Russian\\`) holds
#: «Метрическая система, типовая модель.rft»; the English one holds
#: «Metric Generic Model.rft». The list is CLOSED and NOT COMPLETE: on a
#: third locale the refusal will name the directory, every name tried, and
#: which .rft files are actually THERE — that is, a next move, not
#: "not found".
FAMILY_TEMPLATES: dict[str, tuple[str, ...]] = {
    "generic_model": (
        "Метрическая система, типовая модель.rft",
        "Metric Generic Model.rft",
        "Metric_Generic_Model-ENU.rft",
    ),
}

WALL_LAYER_MIN_MM: float = 0.0
WALL_LAYER_MAX_MM: float = 5_000.0
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
    # Wave A2 (registry-ontology): the op's witness tolerances, keyed by
    # obligation aspect ("endpoint_mm", "height_mm", ...).  Values are the
    # EXACT numbers the emitters historically inlined (byte-parity discipline:
    # no "improved" figures) so each number lives in ONE place.
    #
    # 03.08 — THE LAW OF PROVENANCE (emit_model.py): emitters no longer
    # read this dictionary directly.  A number reaches C# only as the
    # object `emit_model.tolerance(op, key)`, and the witness that
    # declared the tolerance must contain the string that this same object
    # rendered. Hence:
    #   * a key that nothing here answers for will not survive emission;
    #   * every `±<number>` from `post` must live HERE (law 3);
    #   * a dead entry here is also a defect: it is caught by the
    #     perturbing oracle (tests/test_tolerance_provenance.py).
    tolerances: dict[str, float] = field(default_factory=dict)
    #: AN OBSERVATION ABOUT THE HOST THAT THE AUTHOR OTHERWISE PAYS FOR IN
    #: TIME.
    #:
    #: 🔴 WHY THIS WAS SET UP (26.08.2026). A real model was building a
    #: curtain wall through chat: 22 calls, 630 seconds, task not closed.
    #: Almost all of that time went into deriving, BY TRIAL AND ERROR, two
    #: properties of Revit — `AddGridLine` does not survive a second grid
    #: line in one transaction, and a line does not land exactly on the
    #: intersection of existing ones. We already knew both properties;
    #: there was NOWHERE to say them.
    #:
    #: A PARAMETER has had such a place for a long time
    #: (`ParamSpec.omission_transfers` — "what happens if the slot is not
    #: named"), but an OPERATION did not. So the knowledge settled as a
    #: comment in `ops_*.py`, where a programmer reads it and the model
    #: does NOT: the channel to the model is `course.spec("<op>")`, and it
    #: is assembled from the registry, not from the comments around it.
    #:
    #: WHAT TO PUT HERE, AND WHAT NOT TO. Here goes an observation about
    #: RUNTIME that changes how the call is made and that cannot be
    #: derived from the contract: a host property, a cross-operation
    #: condition, a cost in trips. NOT here is what is already said by the
    #: postcondition (`post`), the slot's bounds, or a refusal: a third
    #: carrier of the same knowledge would drift from the first two, and
    #: that is this tree's own named defect.
    #:
    #: WHY AN OBSERVATION, NOT A REFUSAL. Refusing a second line in the
    #: program would mean declaring impossible something that Revit
    #: SOMETIMES lets through, i.e. substituting a law for an observation.
    #: The author is warned; the decision is theirs.
    caveat: str = ""
    #: RESULT KIND DECIDED BY A PARAMETER: (parameter name, value ->
    #: ResultSpec).
    #:
    #: 🔴 WHY THIS FIELD EXISTS, AND WHY IT WAS ALMOST REPLACED BY FOUR OPS
    #: (24.08.2026). `WallType`, `FloorType`, `RoofType`, and `CeilingType`
    #: share ONE constructor (`Duplicate` + `CreateSimpleCompoundStructure`
    #: + `SetCompoundStructure`) and ONE witness (the layer assembly) —
    #: verified by compiling against the real 2021-2026 assemblies, 6/6 on
    #: every member with two negative controls at 0/6. Four ops with an
    #: identical body would be four copies of the same knowledge, i.e. our
    #: own named defect.
    #:
    #: But a SINGLE result kind for four classes cannot be taken either:
    #: then `create_floor.type` would statically accept a reference to a
    #: roof type, and the refusal would arrive only inside Revit. Hence
    #: the third path: one op, and the result kind IS READ FROM THE
    #: PARAMETER — `result` stays as the default value (and answers
    #: exactly that for an omitted parameter), while the table names the
    #: rest.
    #:
    #: This field must be asked THROUGH `result_for(node)`, not by hand: a
    #: spot that reads `spec.result` directly on such an op will get the
    #: "wall" kind for a roof type and not notice.
    result_by_param: tuple[str, dict[str, "ResultSpec"]] | None = None
    #: GROUNDING POOL DECIDED BY A PARAMETER: (parameter name, value ->
    #: {field to ground: pool}). The same shape as `result_by_param`, and
    #: for the same reason.
    #:
    #: 🔴 WHY. `Duplicate` is an INSTANCE method: a floor type is born only
    #: from a floor type. Leaving `source_type` on the `wall_types` pool
    #: when `host_kind="floor"` would mean searching for the floor type's
    #: name among wall types and refusing "not found" — a refusal naming
    #: the wrong cause is worse than silence: it sends the author off to
    #: fix something that is not broken.
    #:
    #: Ask through `grounded_for(node)`. Static readers (the snapshot, the
    #: gate, the contract) are still answered by `grounded`: the pools of
    #: the other kinds are present in the snapshot regardless — declared
    #: by `create_floor`, `create_roof`, and `create_ceiling` through their
    #: own rows.
    grounded_pool_by_param: tuple[str, dict[str, dict[str, str]]] | None = None

    def __post_init__(self) -> None:
        if self.grounded_pool_by_param is not None:
            gname, gtable = self.grounded_pool_by_param
            if not any(p.name == gname for p in self.params):
                raise ValueError(
                    f"{self.name}: grounded_pool_by_param ссылается на "
                    f"параметр «{gname}», которого у опа нет")
            declared = {param for param, _pool, _req in self.grounded}
            for value, pools in gtable.items():
                stray = sorted(set(pools) - declared)
                if stray:
                    raise ValueError(
                        f"{self.name}: grounded_pool_by_param[{value!r}] "
                        f"называет незаземляемые поля: {stray}")
        if self.result_by_param is None:
            return
        pname, table = self.result_by_param
        param = next((p for p in self.params if p.name == pname), None)
        if param is None:
            raise ValueError(
                f"{self.name}: result_by_param ссылается на параметр "
                f"«{pname}», которого у опа нет")
        if param.kind != "enum" or not param.choices:
            raise ValueError(
                f"{self.name}: род результата может решать только enum-параметр "
                f"с перечисленными choices, а «{pname}» — {param.kind}")
        unknown = sorted(set(table) - set(param.choices))
        if unknown:
            raise ValueError(
                f"{self.name}: result_by_param называет значения, которых нет "
                f"в choices параметра «{pname}»: {unknown}")
        # The default must be IN THE TABLE OR EQUAL TO `result`: otherwise
        # the result kind for a program that omitted the parameter is
        # named NOWHERE.
        missing = sorted(set(param.choices) - set(table))
        if missing and param.default not in table:
            if param.default is None:
                raise ValueError(
                    f"{self.name}: параметр «{pname}» без умолчания обязан "
                    f"называть род для КАЖДОГО значения; не названы: {missing}")
        for value, rspec in table.items():
            if not isinstance(rspec, ResultSpec):
                raise TypeError(
                    f"{self.name}: род результата для «{value}» не ResultSpec")
            if not rspec.referenceable:
                raise ValueError(
                    f"{self.name}: род результата для «{value}» не даёт ссылки "
                    "— тогда параметр не решает ничего")

    def _decided_value(self, pname: str,
                       node: Mapping[str, Any] | None) -> Any:
        value = node.get(pname) if isinstance(node, Mapping) else None
        if value is None:
            param = next((p for p in self.params if p.name == pname), None)
            value = param.default if param is not None else None
        return value

    def grounded_for(
        self, node: Mapping[str, Any] | None = None,
    ) -> tuple[tuple[str, str, bool], ...]:
        """The grounding triples for THIS call: the pool may be decided by a parameter."""
        if self.grounded_pool_by_param is None:
            return self.grounded
        pname, table = self.grounded_pool_by_param
        pools = table.get(self._decided_value(pname, node))
        if not pools:
            return self.grounded
        return tuple(
            (param, pools.get(param, pool), required)
            for param, pool, required in self.grounded)

    def result_for(self, node: Mapping[str, Any] | None = None) -> "ResultSpec":
        """The result kind of THIS call, not of the op in general.

        An omitted parameter is answered by `result` — the same kind the
        op answered with before the parameter existed. That is exactly
        byte-for-byte compatibility: a program written yesterday gets
        yesterday's kind."""
        if self.result_by_param is None or not isinstance(node, Mapping):
            return self.result
        pname, table = self.result_by_param
        value = node.get(pname)
        if value is None:
            param = next((p for p in self.params if p.name == pname), None)
            value = param.default if param is not None else None
        return table.get(value, self.result)

    @property
    def grounded_pools(self) -> tuple[str, ...]:
        """ALL pools the op can ever ask for — for STATIC readers.

        The snapshot is taken BEFORE the run and does not know parameter
        values, so it must carry the union. Reading only `grounded` here
        would mean not putting `floor_types` into the snapshot for a
        program made up entirely of
        `create_wall_type(host_kind="floor")` calls — and refusing it
        `KIR-G101` "type not found", even though it was the POOL that was
        not found. Measurement of 24.08.2026: exactly this is how the
        catalog of K3's 18 types was refused.
        """
        pools = [pool for _param, pool, _req in self.grounded]
        if self.grounded_pool_by_param is not None:
            for table in self.grounded_pool_by_param[1].values():
                for pool in table.values():
                    if pool not in pools:
                        pools.append(pool)
        return tuple(pools)

    @property
    def result_kinds(self) -> tuple["ResultSpec", ...]:
        """ALL kinds the op can ever produce — for readers of the registry."""
        if self.result_by_param is None:
            return (self.result,)
        seen = [self.result]
        for rspec in self.result_by_param[1].values():
            if rspec not in seen:
                seen.append(rspec)
        return tuple(seen)


# Write families share one transaction; only query is exclusive.
WRITE_FAMILIES = ("authoring", "modify")

#: Fields that the compiler ATTACHES ITSELF — field name -> the ops it
#: belongs to. **THIS IS THE SOLE AUTHORITY; there are four readers.**
#:
#: WHY THIS WAS SET UP (measurement of 12.08.2026). `__host_wall__` lived
#: as a LITERAL in four places — the writer `compiler.hosted_offset_check`,
#: the readers `midend`, `effects`, `authoring` — and nothing forced them
#: to agree. The fifth place, which was OBLIGATED to know it, had no
#: literal: op parsing (`compiler._validate_op`). The cost of exactly this
#: gap — a floor with walls AND doors did not assemble into a group AT
#: ALL: group members pass through the plan twice (the second time from
#: `ground._ground_members`), the first pass attached the field, the
#: second refused it as KIR-P003 «неизвестное поле». Our own named class
#: of defect in pure form — a value is born in one place and re-read in
#: another, and nothing brings them together.
#:
#: WHY PARSING STRIPS IT, RATHER THAN ACCEPTING IT. There is no way to
#: tell "the field was attached by our own planner" apart from "the field
#: was brought in by a foreign program" at the input: the JSON looks the
#: same. Beyond that is exactly what is PROVEN, with no rounding in our
#: own favor:
#:
#:   * the field has no authorial name: accepting it at input would mean
#:     handing the language a slot the language does not have — and a
#:     slot that cannot be written cannot be confused with another either;
#:   * the value is RE-DERIVED, but NOT unconditionally. There are two
#:     sites, and both are conditional: `compiler._parse_and_check_internal`
#:     — when the wall's endpoints are literal; `ground` — when the wall is
#:     addressed AND resolved (`ground.py:1405-1415`). A path outside both
#:     conditions I have NOT constructed — and I have NOT proven its
#:     unreachability.
#:
#: Hence the choice, by our own order of remedies: **removing the
#: possibility is cheaper than proving unreachability.** A direct check
#: confirmed this: the mutation "accept the field instead of stripping
#: it" did NOT turn a single test red — meaning the accept/strip
#: difference on the constructed paths is NOT OBSERVABLE, and justifying
#: the stripping with "otherwise a forgery would reach the emitter" would
#: overreach what is proven. Stripping is taken not because accepting has
#: been proven harmful, but because stripping requires no proof at all.
#:
#: Where the host is an existing element (`element_id`), the field is not
#: attached at all (`authoring._emit_hosted` reads it only when
#: `host.by == "ref"`), and there is nothing to strip.
#:
#: A name of the form `__x__` was not chosen for looks: the language has
#: not a single authorial slot with such a name, so there is nothing for
#: it to collide with in the registry — checked by
#: `test_synthetic_fields_have_one_authority.py`. The host's shape
#: (`p0_mm`/`p1_mm`/`arc` of the wall), taken by the plan from the ACTUAL
#: wall of the same program and passed to the emitter. The one and only
#: literal of this name in the whole tree is here.
SYNTHETIC_HOST_WALL = "__host_wall__"

#: The total `delta_mm` of ALL legitimate `move_elements` calls in the same
#: program that stand AFTER this op and address its result (`by: ref`).
#: Attached by `authoring.emit_program` on a COPY of the op — already
#: after the plan and acceptance, so parsing does not see it and there is
#: nothing to strip.
#:
#: 🔴 WHY, FROM A MEASUREMENT OF 07.09.2026 (E-2, "the last lawful writer",
#: second half). The final `create_wall` witness compared endpoints against
#: the AUTHORED p0/p1 after the WHOLE program. The program "create a wall
#: (0,0)–(6000,0), then move it by +1000 along X" builds the building
#: CORRECTLY, yet the witness expects the old endpoints under the
#: endpoint_mm tolerance — a guaranteed `postconditions_violated` and a
#: RollBack on a legitimate program. This is the same compositional defect
#: that E-1 closed for `set_param.value_held` and `move_elements.location`,
#: only on the CREATION side, and it is cured not by staging but by
#: ARITHMETIC: the final witness's expectation is computed from the
#: outcome of the last lawful writer.
#:
#: THE COST IS NAMED AS A NUMBER: with an empty shift, the field is not
#: attached at all and the emission is byte-for-byte unchanged — across
#: the whole frozen corpus, the "created → moved by ref" chain is carried
#: by 2 fixtures out of 242 (24 keys out of 2361).
SYNTHETIC_FINAL_SHIFT = "__final_shift__"

SYNTHETIC_FIELDS: dict[str, frozenset[str]] = {
    SYNTHETIC_HOST_WALL: frozenset({"create_door", "create_window"}),
    # E-3 (07.09.2026): nine readers — all creating ops whose ENDPOINTS
    # are legitimately rewritten by `move_elements` through a reference.
    # E-2 carried the shift through to the wall only, and the remaining
    # eight gave the SAME false refusal (measured by the "created → moved"
    # probe: 8 of 8 expected the authored endpoints).
    SYNTHETIC_FINAL_SHIFT: frozenset({
        "create_wall", "create_pipe", "create_duct", "create_cable_tray",
        "create_conduit", "create_pipe_placeholder", "create_duct_placeholder",
        "create_beam", "create_truss", "create_window", "create_door"}),
}


# ── REVIT PARAMETER NAME ↔ CREATING OP'S OBLIGATION KEY ─────────────────────
#
# 🔴 WHY THIS WAS SET UP (08.09.2026, wave 8, link E-4 of "the last lawful
# writer"). The program
#
#     create_wall(W, base_offset_mm=100); set_param(W, "Base Offset", 500мм)
#
# builds the building CORRECTLY and used to get `postconditions_violated`
# with a RollBack: the final CREATION witness pinned the overridden
# 100 mm. The cause is not arithmetic (E-2/E-3 closed the case where the
# value is computed as a program shift) — here the value comes from a
# FOREIGN OP, and the cure is staging: the creation witness is correct at
# the end of ITS OWN operation, but by the end of the program it was
# legitimately overwritten by `set_param`.
#
# WHY THIS COULD NOT BE DONE WITHOUT A TABLE (a reconnaissance measurement
# of 08.09): `set_param` addresses the parameter BY ITS REVIT NAME
# (`GetParameters("Base Offset")`, authoring.py), while the creation
# witness is pinned to an OBLIGATION KEY (`base_offset`). The literal
# `"Base Offset"` occurred ZERO times in the non-test tree, and there was
# nothing to tie the two together — not in the registry, not in the
# certificate, not in the emitter. So the link was missing entirely, not
# lying there as a second carrier.
#
# WHY HERE, AND NOT IN THE CERTIFICATE OR THE EMITTER. The registry is the
# sole owner of ops, their fields, and their effects; "which Revit
# parameter carries which obligation of this op" is a property of the OP,
# not of its translation into C# and not of its proof. Put this in the
# certificate, and the emitter would grow its own opinion, and the two
# would drift apart at the first edit (this tree's own named defect).
#
# 🔴 WHAT IN THE ROW IS VERIFIABLE, AND WHAT IS DECLARED (a named
# unknown). The row's third member — BuiltInParameter — is here not for
# looks: it makes the row VERIFIABLE WITHOUT REVIT. A witness that
# declares the key must read EXACTLY this BuiltInParameter — checked
# against the emission
# (`kir/tests/test_a_parameter_name_reaches_its_obligation.py`), and a row
# naming the wrong key fails red.
# But the NAME ITSELF («Base Offset» for WALL_BASE_OFFSET) is a claim
# about Revit's interface, and there is nothing to check it against
# offline: there is no live Revit in this tree (0 runs). The cost of an
# error in the name is ASYMMETRIC and therefore tolerable: a
# nonexistent name will simply match no `set_param` and leave today's
# behavior in place, whereas the error "a foreign parameter's name → our
# key" would weaken the witness. That is why the table is CLOSED and
# holds only rows where the name is Revit's canonical interface, not a
# guess by analogy.
#
# Shape: op -> {Revit parameter name: (obligation key, BuiltInParameter)}.
REVIT_PARAM_OBLIGATIONS: dict[str, dict[str, tuple[str, str]]] = {
    "create_wall": {
        "Base Offset": ("base_offset", "WALL_BASE_OFFSET"),
        "Top Offset": ("top_offset", "WALL_TOP_OFFSET"),
        "Unconnected Height": ("height", "WALL_USER_HEIGHT_PARAM"),
    },
    "create_column": {
        "Base Offset": ("base_offset", "FAMILY_BASE_LEVEL_OFFSET_PARAM"),
        "Top Offset": ("top_offset", "FAMILY_TOP_LEVEL_OFFSET_PARAM"),
    },
    "create_room": {
        "Limit Offset": ("upper_offset", "ROOM_UPPER_OFFSET"),
    },
    "create_floor": {
        "Height Offset From Level": ("height_offset",
                                     "FLOOR_HEIGHTABOVELEVEL_PARAM"),
    },
    "create_ceiling": {
        "Height Offset From Level": ("height_offset",
                                     "CEILING_HEIGHTABOVELEVEL_PARAM"),
    },
}


def obligation_for_revit_param(op_name: str, param_name: str) -> Optional[str]:
    """The obligation key carried by the Revit parameter with this name.

    THE SOLE READER OF THE TABLE. A direct reference to
    :data:`REVIT_PARAM_OBLIGATIONS` from the emitter or the certificate
    would introduce a second default for a name not found; here there is
    just one — ``None``, meaning "this parameter carries no creation
    obligation belonging to anyone."
    """

    row = REVIT_PARAM_OBLIGATIONS.get(op_name)
    if not row:
        return None
    found = row.get(param_name)
    return None if found is None else found[0]
