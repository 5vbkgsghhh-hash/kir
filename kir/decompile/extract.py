"""Wave A read-only, streamed Revit-to-L0 extraction.

The bridge is injected as an async callable so this module owns no device or
transport policy.  One bridge response contains at most ``EXTRACT_BATCH``
elements; JSONL persistence commits one category at a time and can resume by
truncating any uncommitted category tail.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Awaitable, Callable, Iterator, Mapping

from kir.revit_read_helpers import element_level_helpers_cs

from .census import CATEGORY_READ_FAILED_KEY, NO_CATEGORY_KEY
from .geometry_store import GEOMETRY_HELPER_CS, parse_geometry
from .schema import (
    EXTRACT_BATCH,
    EXTRACT_RETRIES,
    EXTRACT_TIMEOUT_MS,
    EXTRACT_WINDOW_POLL_S,
    EXTRACT_WINDOW_WAIT_S,
    L0_DIALECT_VERSION,
    L0_SCHEMA_VERSION,
    RouteSkip,
    SECTION_RECEIPT_OUTCOMES,
    CategoryState,
    CategoryStatus,
    FederationTransformEvidence,
    FederationTransformSubject,
    L0Dialect,
    L0Document,
    UnloadedElements,
    HostSource,
    L0Element,
    L0SchemaError,
    LinkSummary,
    RoomInfo,
    SectionReceipt,
    dialect_by_version,
    resolve_dialect,
)
from .side_contract import source_binding_cs
from kir import env  # noqa: E402


BridgeExecutor = Callable[..., Awaitable[Any]]
DECOMPILE_OUT_ENV = "KIR_DECOMPILE_OUT"


def default_output_root() -> Path:
    """Root for decompile artifacts when the caller didn't name a path.

    §18.5: a hardcoded installation path ("/root/kukai-ir/decompile_out") is
    forbidden in executable code — on someone else's machine it is either a
    foreign filesystem or a permissions refusal. The primary source stays the
    same — the env var ``KUKAI_DECOMPILE_OUT``; the default is neutral and
    documented: a subdirectory of the system temp
    (``$TMPDIR/kukai-ir/decompile_out``), i.e. a place the process is allowed
    to write to on any OS. Prod and every live run set the path explicitly
    (the pipeline gets ``out_dir`` from serving), so the default is only for a
    manual call to extract_document without an argument.
    """
    configured = env.get(DECOMPILE_OUT_ENV)
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "kukai-ir" / "decompile_out"


# Historical name (imported by tools) — computed at import time.
DEFAULT_OUTPUT_ROOT = default_output_root()


class ExtractionError(RuntimeError):
    """The extraction contract could not be completed safely."""


class ExtractionProtocolError(ExtractionError):
    """A bridge/checkpoint/JSONL payload violates the extraction protocol."""


logger = logging.getLogger(__name__)


class BridgeCallError(ExtractionError):
    """A bridge round-trip failed after its bounded retry budget."""


class DocumentRevisionError(ExtractionError):
    """Two read-only calls did not observe one immutable document revision."""


class TemplateCompileError(ExtractionError):
    """OUR template never became an assembly — nothing reached Revit at all.

    A separate kind of refusal, not a variety of transport failure, and the
    difference isn't cosmetic: text that failed to compile will not compile
    just because we waited. Retrying and waiting for a window is a pure waste
    of hours for it.

    THE 30.07 LIVE CASE the class was set up for. Decompiling a 59-story
    tower on R2023 printed for an hour and a half "window not responding on
    side stage annotation batch 1/14 — waiting for it to come back," while
    the service kept writing in a loop ``TEMPLATE COMPILE FAILED ... CS1503
    ... bridge_roundtrips=0``. The window was alive. The waiting layer sent
    the search for the cause into Revit — that is, exactly where it wasn't;
    meanwhile what went out was ``ExtractionProtocolError: True``, because the
    cause was taken from the BOOLEAN flag ``error``.
    """


@dataclass(frozen=True, slots=True)
class CategorySpec:
    name: str
    collector_cs: str
    exclude_direct_shape: bool = True
    # The project discipline the category belongs to. The same closed
    # dictionary as KindSpec's (registry_base.DISCIPLINES) — there must not be
    # a second dictionary about the same concept in the package.
    #
    # Why in the EXTRACTOR: the set of categories present shows which
    # discipline lies in the document, and that is more honest than parsing
    # the file name — a name lies easily, the content does not. The coverage
    # map must name which disciplines went into the sample: on 27.07 it
    # measured two documents, both architectural, and on that basis it was
    # claimed that "coverage is stable across buildings" — a claim about the
    # compiler, made from a property of the sample. On the very first non-AR
    # model it collapsed from ~93% to 67.7%.
    discipline: str = "shared"

    def __post_init__(self) -> None:
        from kir.registry_base import DISCIPLINES
        if self.discipline not in DISCIPLINES:
            raise ValueError(
                f"CategorySpec {self.name!r}: unknown discipline "
                f"{self.discipline!r}")


# The order is part of the resume format.  These are the exact 22 families in
# DECOMPILE §4.4; class-only families use stable pseudo-category names because
# no single BuiltInCategory identifies every DirectShape or ImportInstance.
_CATEGORY_SPECS = (
    CategorySpec("OST_Walls",
                 ".OfCategory(BuiltInCategory.OST_Walls)",
                 discipline="architectural"),
    CategorySpec("OST_Floors",
                 ".OfCategory(BuiltInCategory.OST_Floors)",
                 discipline="architectural"),
    CategorySpec("OST_Roofs",
                 ".OfCategory(BuiltInCategory.OST_Roofs)",
                 discipline="architectural"),
    CategorySpec("OST_Columns",
                 ".OfCategory(BuiltInCategory.OST_Columns)",
                 discipline="architectural"),
    CategorySpec("OST_StructuralColumns",
                 ".OfCategory(BuiltInCategory.OST_StructuralColumns)",
                 discipline="structural"),
    CategorySpec("OST_StructuralFraming",
                 ".OfCategory(BuiltInCategory.OST_StructuralFraming)",
                 discipline="structural"),
    CategorySpec("OST_StructuralFoundation",
                 ".OfCategory(BuiltInCategory.OST_StructuralFoundation)",
                 discipline="structural"),
    CategorySpec("OST_Doors",
                 ".OfCategory(BuiltInCategory.OST_Doors)",
                 discipline="architectural"),
    CategorySpec("OST_Windows",
                 ".OfCategory(BuiltInCategory.OST_Windows)",
                 discipline="architectural"),
    CategorySpec("OST_Stairs",
                 ".OfCategory(BuiltInCategory.OST_Stairs)",
                 discipline="architectural"),
    CategorySpec("OST_StairsRailing",
                 ".OfCategory(BuiltInCategory.OST_StairsRailing)",
                 discipline="architectural"),
    CategorySpec("OST_Rooms",
                 ".OfCategory(BuiltInCategory.OST_Rooms)",
                 discipline="architectural"),
    CategorySpec("OST_Grids", ".OfClass(typeof(Grid))"),
    CategorySpec("OST_Levels", ".OfClass(typeof(Level))"),
    CategorySpec("OST_PipeCurves",
                 ".OfCategory(BuiltInCategory.OST_PipeCurves)",
                 discipline="plumbing"),
    CategorySpec("OST_DuctCurves",
                 ".OfCategory(BuiltInCategory.OST_DuctCurves)",
                 discipline="mechanical"),
    CategorySpec("OST_CableTray",
                 ".OfCategory(BuiltInCategory.OST_CableTray)",
                 discipline="electrical"),
    CategorySpec("OST_Furniture",
                 ".OfCategory(BuiltInCategory.OST_Furniture)",
                 discipline="architectural"),
    CategorySpec("OST_GenericModel",
                 ".OfCategory(BuiltInCategory.OST_GenericModel)"),
    CategorySpec(
        "DirectShape", ".OfClass(typeof(DirectShape))",
        exclude_direct_shape=False),
    CategorySpec(
        "ImportInstance", ".OfClass(typeof(ImportInstance))",
        exclude_direct_shape=False),
    CategorySpec("OST_RasterImages",
                 ".OfCategory(BuiltInCategory.OST_RasterImages)"),

    # ── Disciplines other than AR (added 27.07) ─────────────────────────────
    # APPENDED TO THE END DELIBERATELY: the order of this tuple is part of the
    # resumption format, inserting into the middle would shift the indexes of
    # already-started extractions.
    #
    # The reason is measured: in the training model for Electrical (SKLNK,
    # R2026) the content is electrical equipment, light fixtures, cable-tray
    # boxes, and fittings, and NOT A SINGLE one of these categories was in the
    # table. That is, the whole discipline was invisible, and the refusal
    # would have looked like a compiler failure, while it was actually the
    # absence of a line. The table knew 20 categories, 12 of them
    # architectural.
    #
    # Every line is a collector and nothing more; the check is the same as
    # for views: a category missing from any of the six Revit versions fails
    # the gate.

    # Electrical
    CategorySpec("OST_ElectricalEquipment",
                 ".OfCategory(BuiltInCategory.OST_ElectricalEquipment)",
                 discipline="electrical"),
    CategorySpec("OST_ElectricalFixtures",
                 ".OfCategory(BuiltInCategory.OST_ElectricalFixtures)",
                 discipline="electrical"),
    CategorySpec("OST_LightingFixtures",
                 ".OfCategory(BuiltInCategory.OST_LightingFixtures)",
                 discipline="electrical"),
    CategorySpec("OST_LightingDevices",
                 ".OfCategory(BuiltInCategory.OST_LightingDevices)",
                 discipline="electrical"),
    CategorySpec("OST_CableTrayFitting",
                 ".OfCategory(BuiltInCategory.OST_CableTrayFitting)",
                 discipline="electrical"),
    CategorySpec("OST_Conduit",
                 ".OfCategory(BuiltInCategory.OST_Conduit)",
                 discipline="electrical"),
    CategorySpec("OST_ConduitFitting",
                 ".OfCategory(BuiltInCategory.OST_ConduitFitting)",
                 discipline="electrical"),

    # HVAC
    CategorySpec("OST_MechanicalEquipment",
                 ".OfCategory(BuiltInCategory.OST_MechanicalEquipment)",
                 discipline="mechanical"),
    CategorySpec("OST_DuctFitting",
                 ".OfCategory(BuiltInCategory.OST_DuctFitting)",
                 discipline="mechanical"),
    CategorySpec("OST_DuctTerminal",
                 ".OfCategory(BuiltInCategory.OST_DuctTerminal)",
                 discipline="mechanical"),
    CategorySpec("OST_FlexDuctCurves",
                 ".OfCategory(BuiltInCategory.OST_FlexDuctCurves)",
                 discipline="mechanical"),
    CategorySpec("OST_MEPSpaces",
                 ".OfCategory(BuiltInCategory.OST_MEPSpaces)",
                 discipline="mechanical"),

    # Plumbing
    CategorySpec("OST_PlumbingFixtures",
                 ".OfCategory(BuiltInCategory.OST_PlumbingFixtures)",
                 discipline="plumbing"),
    CategorySpec("OST_PipeFitting",
                 ".OfCategory(BuiltInCategory.OST_PipeFitting)",
                 discipline="plumbing"),
    CategorySpec("OST_PipeAccessory",
                 ".OfCategory(BuiltInCategory.OST_PipeAccessory)",
                 discipline="plumbing"),
    CategorySpec("OST_FlexPipeCurves",
                 ".OfCategory(BuiltInCategory.OST_FlexPipeCurves)",
                 discipline="plumbing"),
    CategorySpec("OST_Sprinklers",
                 ".OfCategory(BuiltInCategory.OST_Sprinklers)",
                 discipline="plumbing"),

    # Structural
    CategorySpec("OST_StructuralTruss",
                 ".OfCategory(BuiltInCategory.OST_StructuralTruss)",
                 discipline="structural"),

    # AR — what was missing in its own discipline
    CategorySpec("OST_Ceilings",
                 ".OfCategory(BuiltInCategory.OST_Ceilings)",
                 discipline="architectural"),
    CategorySpec("OST_Ramps",
                 ".OfCategory(BuiltInCategory.OST_Ramps)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainWallPanels",
                 ".OfCategory(BuiltInCategory.OST_CurtainWallPanels)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainWallMullions",
                 ".OfCategory(BuiltInCategory.OST_CurtainWallMullions)",
                 discipline="architectural"),
    CategorySpec("OST_Casework",
                 ".OfCategory(BuiltInCategory.OST_Casework)",
                 discipline="architectural"),
    CategorySpec("OST_SpecialityEquipment",
                 ".OfCategory(BuiltInCategory.OST_SpecialityEquipment)",
                 discipline="architectural"),
    CategorySpec("OST_Areas",
                 ".OfCategory(BuiltInCategory.OST_Areas)",
                 discipline="architectural"),

    # APPENDED TO THE END DELIBERATELY, for the same reason as the section
    # above (the order of this tuple is part of the resumption format,
    # inserting into the middle would shift the indexes of already-started
    # extractions): the curtain SYSTEM (BuiltInCategory.OST_CurtaSystem, name
    # verified against RevitAPI.dll strings for all six versions 2021-2026) —
    # a third kind of curtain-grid host, alongside the wall and the roof.
    # Without a line here, such a host is invisible to READING in the
    # category table: the create_curtain capture (curtain_extract.py) already
    # knows how to walk CurtainSystem.CurtainGrids, but there was nowhere to
    # feed it an id from — curtain-system panels weren't getting a host (a
    # tail of wave aaa44b45, 28.07).
    CategorySpec("OST_CurtaSystem",
                 ".OfCategory(BuiltInCategory.OST_CurtaSystem)",
                 discipline="architectural"),

    # CURTAIN DIVISION LINES. Appended to the end for the same reason as the
    # line above: the tuple's order is part of the resumption format.
    #
    # WHY. A division line is a real element with its own id, and it is
    # exactly these that set the grid's layout: the host type doesn't carry
    # it (live measurement v14: for ALL 393 curtain-wall hosts, all six
    # SPACING_LAYOUT_* slots equal zero, while there are 122 lines across 70
    # hosts). While this category wasn't in the table, the line didn't exist
    # for READING, and the reverse pass could not set it as an operation
    # without INVENTING a source — which is where live run v14 stopped:
    # FoldError('L0/L1 source mismatch: missing=0, invented=122'). The fold's
    # census law is right: the lifter has no right to invent sources, so the
    # L0 side is what gets fixed.
    #
    # THE CATEGORY NAME IS MEASURED, NOT GUESSED. A census of live model v14
    # named it itself: OST_CurtainGridsWall, 122 elements — exactly as many as
    # the lines in the curtain index of the same run. The existence of all
    # three names is verified by compilation against 2021-2026
    # (OST_CurtainGridWall and OST_CurtainGridsSlopedGlazing, for comparison,
    # do not compile on any version).
    #
    # THERE ARE THREE KINDS, BECAUSE THERE ARE THREE KINDS OF HOST: wall,
    # roof, curtain system — exactly the ones curtain_extract.py already
    # walks. The names OST_CurtainGrids and OST_CurtainGridsSystem are
    # deliberately NOT included in the table: they compile, but no
    # measurement says what stands behind them, and a closed list is no place
    # for guesses.
    CategorySpec("OST_CurtainGridsWall",
                 ".OfCategory(BuiltInCategory.OST_CurtainGridsWall)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainGridsRoof",
                 ".OfCategory(BuiltInCategory.OST_CurtainGridsRoof)",
                 discipline="architectural"),
    CategorySpec("OST_CurtainGridsCurtaSystem",
                 ".OfCategory(BuiltInCategory.OST_CurtainGridsCurtaSystem)",
                 discipline="architectural"),
    # ── R4 reds: INSULATION AND LINING. The obstacle's body exists in the
    # model as a SEPARATE element with its own bounding size — and we weren't
    # asking it. Red measurement: DN20 (26.9 mm outer diameter) + 50 mm of
    # insulation — the pipe shell covered 4.5 % of the obstacle's
    # cross-section area. For small diameters, the insulation is THICKER than
    # the pipe. Insulated piping is the norm for HVAC and Plumbing, i.e. for
    # two of the three MVP disciplines.
    #
    # NAMES ARE VERIFIED BY COMPILATION 6/6 (2021-2026), not from memory:
    # RevitAPI.xml has no BuiltInCategory members at all, so the only honest
    # way to check is the compile service.
    #
    # Appended to THE END: the order of categories is part of the frozen flow
    # schema (`category_status` follows it strictly), and inserting into the
    # middle would shift every existing L0.
    CategorySpec("OST_PipeInsulations",
                 ".OfCategory(BuiltInCategory.OST_PipeInsulations)",
                 discipline="plumbing"),
    CategorySpec("OST_DuctInsulations",
                 ".OfCategory(BuiltInCategory.OST_DuctInsulations)",
                 discipline="mechanical"),
    CategorySpec("OST_DuctLinings",
                 ".OfCategory(BuiltInCategory.OST_DuctLinings)",
                 discipline="mechanical"),

    # ── WORKING DOCUMENTATION: DIMENSIONS, TAGS, NOTES (29.07) ─────────────
    #
    # WHY. A measurement on real working drawings (13A-RD-AR-K2_v33, snapshot
    # k2_ar_rd_v6) exposed the main READING hole: coverage OF THE DOCUMENT was
    # 9.61 %. The census shows 112 categories and 310 558 elements, while the
    # table read 54 categories = 55 293 elements, i.e. 17.80 % of the
    # document. Most of the rest outside the table is LEGITIMATELY so — it is
    # derived and internal: OST_AreaSchemeLines 61 520, no_category 53 885,
    # OST_SketchLines 38 093, OST_WeakDims 19 547. But lying invisible
    # TOGETHER with them was the CONTENT of the working documentation:
    # dimensions 13 905, room tags 11 585, lines 9 407, detail-item elements
    # 3 046, text notes 2 697. We are building a tool for working
    # documentation, and dimensions, tags, and notes ARE the working
    # documentation. Without a line here, they don't exist for reading at
    # all: no element, no category status, no refusal — exactly the muteness
    # the census law was set up to forbid (§18.1).
    #
    # WHAT IT'S MEASURED BY. Every number above and below is a census of THAT
    # VERY run (the L0.jsonl header, the census field, 112 lines), not an
    # estimate. Every line below enters with a MEASURED non-zero element
    # count; there is not a single "for the future" name here. This is the
    # same threshold by which, on 28.07, OST_CurtainGrids and
    # OST_CurtainGridsSystem were not let into the table: they compile, but no
    # measurement says what stands behind them, and a closed list is no place
    # for guesses. For the same reason, tags absent from the measured
    # document are thrown out here: including them would mean guessing, while
    # excluding OST_WallTags while including OST_DoorTags would mean fitting
    # the table to a single model. Both prohibitions resolve the same way:
    # what enters is the MEASURED thing, in full.
    #
    # 🔴 THIS ARGUMENT HAS AN EXPIRATION DATE, AND IT HAS PASSED (22.08.2026).
    # Here stood "tags absent from the measured document are thrown out
    # (OST_WindowTags, OST_CeilingTags, and other siblings)." The rule was
    # correct, but the word "measured" pointed to ONE document —
    # `k2_ar_rd_v6`. On the second building (MNVNK_ATR_PD_B14_K6_AR_R2022,
    # snapshot `mnvnk_atr_pd_b14_k6_ar_r2022_отсоединено_отсоединено`),
    # OST_WindowTags gives 660 elements, on the third (13B-RD-AR-K4_v32) —
    # 2 630, a total of 3 545 across the corpus in 4 of 11 documents. The
    # argument "they're absent" did not become false because someone made a
    # mistake: it was true exactly about its own measurement and rotted
    # silently, because nowhere was it recorded WHERE it was measured. The
    # rule "the measured thing enters" without re-measuring on every new
    # corpus fits the table to the first house forever.
    #
    # THE CURE IS NOT A PROSE FIX, IT IS A MECHANISM:
    # `TAG_CATEGORIES_NOT_TAKEN` further down the file, plus
    # `tag_categories_outside_the_law()`. The journal holds the NAMES of tag
    # kinds that were measured but not taken; the law requires that every
    # kind measured non-zero in the corpus stand EITHER in this table OR in
    # the journal. A new building with an unfamiliar tag kind fails
    # `tests/test_zero_measurement_exclusions_expire.py`, rather than lying
    # invisible until the next person happens to look.
    #
    # THE ADMISSION RULE (lead's decision on 29.07, executed literally): a
    # category is admitted if (a) its elements are design CONTENT, not
    # derived from another element, AND (b) there is an op capable of
    # expressing it, OR its reading is needed as CONTEXT.
    #
    # REFUSALS UNDER HALF (a) LIVE AS DATA, NOT AS THIS PROSE. Before 22.08
    # they were listed right here — sketches, auto-dimensioning, the
    # analytical model, parts of stairs and railings — and this was a SECOND
    # CARRIER of the same knowledge: a reader asking "is category X refused
    # as derived" had to look in two places and might find it in only one.
    # The single carrier now is `DERIVED_CATEGORIES_NOT_TAKEN` further down
    # the file: there, each name carries a corpus MEASUREMENT and an
    # argument, and `derived_categories_outside_the_law()` keeps the record
    # from rotting.
    #
    # But the SHEET layer is refused by the OTHER half of the rule, and so
    # stays here: OST_Views 4 320, OST_Schedules 3 880, OST_Viewports 2 508,
    # OST_Sheets 908 across the corpus (10 buildings) — a sheet IS real
    # working documentation and is not derived, but there isn't a single op
    # for it, and it deserves a wave of its own, not the tail of this one.
    #
    # FOUR LINES ENTER WITHOUT AN OP, AND THIS IS SAID OUT LOUD: OST_Lines,
    # OST_SpotElevations, OST_SpotSlopes, OST_GenericAnnotation. There is no
    # lifter for them, and each of their elements will become an atom with
    # the typed cause `no_lifter`. This is WORSE than a raised operation and
    # BETTER than invisibility: an atom is visible in the fold's census and
    # names its own cause, while an unread category stays silent.
    # OST_RoomSeparationLines is admitted under the SECOND half of the rule —
    # as context: we have read rooms for a long time, and it is exactly
    # these lines that set their boundaries.
    #
    # NAMES ARE VERIFIED BY COMPILATION 6/6 (2021-2026), NOT FROM MEMORY:
    # RevitAPI.xml has no BuiltInCategory members at all, so the only honest
    # oracle is the compile service. All 19 names below passed 6/6. The same
    # run also took a control, and it reproduced what was recorded earlier in
    # the file: OST_CurtainGridWall and OST_CurtainGridsSlopedGlazing do not
    # compile on any of the six versions (CS0117).
    #
    # THE COST IS MEASURED, NOT ESTIMATED. From five runs of the same model
    # (k2_ar_rd_v1/v2/v3/v5/v6; rounds counted as probes + pages by scopes,
    # time by stage boundaries), this is solved:
    # T = 0.326 s/round + 12.2 ms/element. The remainder of a full run (~41
    # min) is the census of 310 558 elements, and it does not change from
    # THIS fix. +60 587 elements and +19 probes add +12.7...13.6 min to the
    # extraction stage (56.2 -> ~69 min). Splitting pages by level barely
    # moves the cost: annotations have no level, they fall into the single
    # scope "__none__".
    #
    # WHY RIGHT HERE, AT THE END. The order of this tuple is part of the
    # frozen resumption format: the loop goes over
    # ``EXTRACT_CATEGORIES[len(processed):]``, meaning a category is
    # addressed BY INDEX, and inserting into the middle would shift every
    # started extraction and every existing L0. Appending to the tail, by
    # contrast, is safe — a checkpoint already taken will simply continue
    # from the new lines.
    #
    # A tag's discipline is its HOST's discipline (the same as the host's
    # line in this table); dimensions, lines, and notes have no host, they
    # are shared across all disciplines, hence "shared".

    # Dimensions, notes, and spot elevations — what a working-drawing sheet
    # consists of.
    CategorySpec("OST_Dimensions",
                 ".OfCategory(BuiltInCategory.OST_Dimensions)"),
    CategorySpec("OST_TextNotes",
                 ".OfCategory(BuiltInCategory.OST_TextNotes)"),
    CategorySpec("OST_SpotElevations",
                 ".OfCategory(BuiltInCategory.OST_SpotElevations)"),
    CategorySpec("OST_SpotSlopes",
                 ".OfCategory(BuiltInCategory.OST_SpotSlopes)"),
    CategorySpec("OST_GenericAnnotation",
                 ".OfCategory(BuiltInCategory.OST_GenericAnnotation)"),

    # Lines: drafting and model lines. OST_RoomSeparationLines — room
    # context (a room's boundary is set by a line, not a wall).
    CategorySpec("OST_Lines",
                 ".OfCategory(BuiltInCategory.OST_Lines)"),
    CategorySpec("OST_RoomSeparationLines",
                 ".OfCategory(BuiltInCategory.OST_RoomSeparationLines)",
                 discipline="architectural"),

    # Detail-item elements are FamilyInstance, i.e. place_family.
    CategorySpec("OST_DetailComponents",
                 ".OfCategory(BuiltInCategory.OST_DetailComponents)"),

    # TAGS (create_tag). ALL that were measured in the document are
    # admitted, not just the ones that caught the eye first — otherwise the
    # table gets fitted to the model.
    CategorySpec("OST_RoomTags",
                 ".OfCategory(BuiltInCategory.OST_RoomTags)",
                 discipline="architectural"),
    CategorySpec("OST_DoorTags",
                 ".OfCategory(BuiltInCategory.OST_DoorTags)",
                 discipline="architectural"),
    CategorySpec("OST_WallTags",
                 ".OfCategory(BuiltInCategory.OST_WallTags)",
                 discipline="architectural"),
    CategorySpec("OST_FloorTags",
                 ".OfCategory(BuiltInCategory.OST_FloorTags)",
                 discipline="architectural"),
    CategorySpec("OST_AreaTags",
                 ".OfCategory(BuiltInCategory.OST_AreaTags)",
                 discipline="architectural"),
    CategorySpec("OST_StairsRailingTags",
                 ".OfCategory(BuiltInCategory.OST_StairsRailingTags)",
                 discipline="architectural"),
    CategorySpec("OST_StructuralFramingTags",
                 ".OfCategory(BuiltInCategory.OST_StructuralFramingTags)",
                 discipline="structural"),
    CategorySpec("OST_MechanicalEquipmentTags",
                 ".OfCategory(BuiltInCategory.OST_MechanicalEquipmentTags)",
                 discipline="mechanical"),
    CategorySpec("OST_MaterialTags",
                 ".OfCategory(BuiltInCategory.OST_MaterialTags)"),
    CategorySpec("OST_MultiCategoryTags",
                 ".OfCategory(BuiltInCategory.OST_MultiCategoryTags)"),

    # MODEL CONTENT, not annotation: 4 479 elements measured in the
    # document, this is FamilyInstance under place_family, and the category
    # is a direct sibling of the already-read OST_LightingDevices. There was
    # no line for the same reason as with the Electrical wave of 27.07: not
    # because it was decided not to read it, but because no one looked.
    CategorySpec("OST_TelephoneDevices",
                 ".OfCategory(BuiltInCategory.OST_TelephoneDevices)",
                 discipline="electrical"),

    # ── OPENINGS AS SEPARATE ELEMENTS (wave/opening, 03.08.2026) ──────────
    #
    # THE ONLY SILENT LOSS found by walking eight buildings. An opening is
    # made by TWO mechanisms: an inner loop in the host's sketch (this we
    # know how to do — 60 create_floor with non-empty holes in three
    # buildings) and a SEPARATE Opening element. The second didn't exist for
    # reading at all, and that is worse than "doesn't lift": the element
    # isn't extracted ⇒ it produces no atom ⇒ it's in none of the cause
    # rankings, while the HOST is raised as an ordinary create_floor/
    # create_wall and rebuilt as SOLID. L2 acceptance does not catch this by
    # construction (acceptance.py says outright: it doesn't look at geometry
    # at all), meaning a silently wrong result is indistinguishable from
    # success from the outside.
    #
    # WHAT IS MEASURED (a census of eight buildings): OST_FloorOpening 10,
    # OST_ShaftOpening 9, OST_SWallRectOpening 9, OST_RoofOpening 7 —
    # 35 elements in 3 of 6 buildings. Exactly these four are admitted and
    # not one line more: OST_CeilingOpening, OST_ArcWallRectOpening,
    # OST_ColumnOpening, and OST_StructuralFramingOpening COMPILE (see
    # below), but no measurement says what stands behind them — the same
    # threshold by which OST_CurtainGrids was not let into the table on
    # 28.07.
    #
    # NAMES ARE VERIFIED BY COMPILATION 6/6 (:52412, 2021-2026), not from
    # memory: RevitAPI.xml has no BuiltInCategory members at all. The same
    # run also took a NEGATIVE control — the made-up OST_TotallyMadeUpOpening
    # does not compile on any version, meaning the oracle discriminates.
    #
    # THREE OF THE FOUR HAVE AN OP (`create_opening`, ops_opening.py) and
    # give `source_contract_gap`: there is an operation, but L0 1.0 carries
    # neither Opening.Host nor the opening's boundary. THE FOURTH —
    # OST_ShaftOpening — is admitted WITHOUT an op and gives `no_lifter`, and
    # that is true: no registry operation builds a shaft (the reason is in
    # ops_opening.VARIETIES_NOT_TAKEN — its tie to a pair of levels has
    # nothing to confirm it from the built element). A precedent of exactly
    # this shape is already recorded earlier in the file: "FOUR LINES ENTER
    # WITHOUT AN OP, AND THIS IS SAID OUT LOUD ... This is WORSE than a
    # raised operation and BETTER than invisibility."
    #
    # APPENDED TO THE END, like everything above: the tuple's order is part
    # of the frozen resumption format (the loop goes over
    # EXTRACT_CATEGORIES[len(processed):], meaning a category is addressed
    # BY INDEX). The table's growth from 73 to 77 had to get its own dialect
    # step — it is set up in schema.py (kir-decompile-l0-dialect/7),
    # otherwise a fresh snapshot would not open with its own reader.
    CategorySpec("OST_SWallRectOpening",
                 ".OfCategory(BuiltInCategory.OST_SWallRectOpening)",
                 discipline="architectural"),
    CategorySpec("OST_FloorOpening",
                 ".OfCategory(BuiltInCategory.OST_FloorOpening)",
                 discipline="architectural"),
    CategorySpec("OST_RoofOpening",
                 ".OfCategory(BuiltInCategory.OST_RoofOpening)",
                 discipline="architectural"),
    CategorySpec("OST_ShaftOpening",
                 ".OfCategory(BuiltInCategory.OST_ShaftOpening)",
                 discipline="architectural"),

    # ── WINDOW TAGS: THE ARGUMENT'S EXPIRATION DATE HAS PASSED (22.08.2026) ──
    #
    # WHAT IS MEASURED. A census of the corpus's 11 documents (the L0.jsonl
    # header, the `document.census` field, one fullest decompile per
    # building): OST_WindowTags is non-zero in FOUR — 13B-RD-AR-K4_v32
    # 2 630, MNVNK_ATR_PD_B14_K6 660, LEN_AR_ME_R24 153, Snowdon
    # Architectural 102, a total of 3 545. This is the LARGEST tag kind
    # outside the table: next after it, OST_RevisionCloudTags gives 2 271,
    # while the remaining thirty together give 3 050. The measuring
    # instrument is `tag_categories_outside_the_law()` below, which also
    # enforces the law; the number is not copied from someone else's screen.
    #
    # WHY THIS LINE IS LEGITIMATE, AND NOT "JUST ANOTHER CATEGORY." The
    # admission rule is satisfied by both halves: (a) a tag is the author's
    # working-documentation CONTENT, not derived from the window (Revit does
    # not place it itself), and (b) there is an op — `create_tag`, lifter
    # `_lift_tag`, side stage `tag_extract`. OST_WindowTags's kind is
    # `IndependentTag`, i.e. the SAME branch as the already-read
    # OST_DoorTags and OST_WallTags: this line requires no new capability at
    # all, the C# stage branches on the element's class (`__tgInd != null`),
    # not on the category.
    #
    # APPENDED TO THE END — by the same law as every wave above: the
    # tuple's order is the resumption format. Growing from 77 to 78 got its
    # own dialect step in schema.py (kir-decompile-l0-dialect/8), otherwise a
    # fresh snapshot would not open with its own reader.
    CategorySpec("OST_WindowTags",
                 ".OfCategory(BuiltInCategory.OST_WindowTags)",
                 discipline="architectural"),

    # ── REFERENCE PLANES: WE WRITE WHAT WE CANNOT READ (22.08.2026) ──
    #
    # WHAT IS MEASURED, AND THIS IS THE MOST EVEN NUMBER IN THE WHOLE TABLE.
    # A census of the corpus (the L0.jsonl header, the `document.census`
    # field, one fullest decompile per building): OST_CLines is non-zero in
    # TEN buildings out of ten — 9 724 elements. LEN_AR_ME_R24 2 774,
    # 13B-RD-AR-K4_v32 2 180, MNVNK 1 474, Snowdon Architectural 1 037,
    # 13A-RD-AR-K2_v33 951, SOB6.2 166, «Проект1» 165, Snowdon Plumbing 15,
    # Snowdon Electrical 11. No other untaken category is present in ALL the
    # corpus's houses.
    #
    # 🔴 THIS IS A CLASS, NOT A CATEGORY, AND THAT IS EXACTLY THE TRAP.
    # `ReferencePlane` is addressed by the collector ONLY through
    # `.OfClass(typeof(ReferencePlane))` — exactly on the pattern of
    # OST_Grids/OST_Levels two hundred lines above, where the line's name is
    # the CENSUS key (`Element.Category`), while the collector goes by
    # class. Copying `.OfCategory(BuiltInCategory.OST_CLines)` here by
    # analogy with the neighboring lines is the cheapest way to get a page
    # that compiles, answers zero, and looks like "there are none in the
    # model." The line's key must stay `OST_CLines`: the census measures the
    # category, and if the name diverged, the census law (§18.1) would call
    # MNVNK's 1 474 elements a shortfall without naming the cause.
    #
    # WHY THE LINE IS LEGITIMATE. The admission rule is satisfied by both
    # halves: (a) a reference plane is AUTHORED content, a datum on a par
    # with a grid and a level: Revit does not place it itself, the designer
    # places it and aligns geometry to it; (b) it is needed as CONTEXT, and
    # this is measured live, not derived: of MNVNK's 1 256 "dependencies,"
    # 1 233 (98.2%) are pairs (sketch, REFERENCE PLANE) with the author's
    # lock. Taking dependencies without taking planes would mean getting
    # 1 233 references into nothing.
    #
    # THERE IS NO OP, AND THIS IS SAID OUT LOUD: there is not a single
    # operation with the word `plane` in the registry (measured against
    # `spec.OPS`, 78 ops). Every plane will become an atom with the typed
    # cause `no_lifter` — by the same precedent as the four lines earlier in
    # the file ("WORSE than a raised operation and BETTER than
    # invisibility"). The difference from them is that here we are WRITING
    # what we cannot read: `family_author_emit.NewReferencePlane` has
    # created planes inside a family since 21.08, and no one sees them in a
    # project.
    #
    # THE NAME IS VERIFIED BY COMPILATION 6/6 (service :52412, 2021-2026) ON
    # A REAL BODY, not on a type declaration: both prod pages of this
    # category were assembled and sent — `build_category_probe_cs` and
    # `build_category_batch_cs`, 12 of 12 compilations succeeded. The same
    # run also took a NEGATIVE control: `.OfClass(typeof(KirTotallyMadeUpDatum))`
    # is refused on all six (CS0246), meaning the oracle discriminates.
    #
    # WHAT WILL ADDRESS IT ONCE A DEPENDENCY REACHES IT: an L0 line carries
    # `element_id` (a local Revit address, lives inside one snapshot) and
    # `unique_id` (a stable identifier, survives a re-capture). The line
    # carries NO NAME for the plane — `L0Element` has no name field at all,
    # and a datum's `type_id` is invalid — and this is a named gap for the
    # next wave, not an oversight of this one: for grids and levels, the
    # name arrives via the document header (`_METADATA_CS`); planes have no
    # such collector.
    #
    # APPENDED TO THE END — by the same law as every wave above: the
    # tuple's order is the resumption format. Growing from 78 to 79 got its
    # own dialect step in schema.py (kir-decompile-l0-dialect/9) IN THE SAME
    # MOVE.
    CategorySpec("OST_CLines", ".OfClass(typeof(ReferencePlane))"),
    # ═════════════════════════════════════════════════════════════════════
    # 04.09.2026 — WAVE "SILENCE BECOMES A REFUSAL", +13 lines.
    #
    # ALL thirteen have an operation in the registry, and NOT ONE was being
    # extracted: the element gave neither a line, nor an atom, nor a
    # refusal. A rebuilt building was left without terrain, without floor
    # fills, without loads, without cornices — and said NOTHING about it.
    # Exactly the kind this file's canon already named about openings: "the
    # host is raised as solid, L2 acceptance does not catch this by
    # construction, a silently wrong result is indistinguishable from
    # success from the outside." The precedent's shape is the same: the line
    # is admitted WITHOUT lifting and gives `source_contract_gap`, whose text
    # IS the specification for the next reading wave. This is worse than a
    # raised operation and BETTER than invisibility.
    #
    # NAMES ARE CHECKED BY THE ORACLE AGAINST THE METADATA OF SIX REAL
    # `RevitAPI.dll` FILES (`/opt/kir-audit/api_name_oracle.py`), not from
    # memory: `RevitAPI.xml` has no `BuiltInCategory` members at all, so the
    # trap index is silent about them. All thirteen are 6/6. The control was
    # executed both ways: the made-up `OST_TotallyMadeUpCategory` was not
    # found in a single assembly.
    #
    # 🔴 `OST_Toposolid` IS NOT IN THE TABLE, AND THIS IS A MEASUREMENT, NOT
    # AN OVERSIGHT. Oracle: 4/6, only 2023-2026. The collector would not have
    # compiled with it on 2021 and 2022, meaning one line would have taken
    # the WHOLE extraction out from under the gate on two of the six
    # versions. The consequence is named where it will be read: for
    # `create_topography`, only `variety="surface"` is taken, and "mass"
    # remains inexpressible until a wave that learns to branch by version.
    CategorySpec("OST_PointLoads",
                 ".OfCategory(BuiltInCategory.OST_PointLoads)",
                 discipline="structural"),
    CategorySpec("OST_LineLoads",
                 ".OfCategory(BuiltInCategory.OST_LineLoads)",
                 discipline="structural"),
    CategorySpec("OST_AreaLoads",
                 ".OfCategory(BuiltInCategory.OST_AreaLoads)",
                 discipline="structural"),
    CategorySpec("OST_AreaRein",
                 ".OfCategory(BuiltInCategory.OST_AreaRein)",
                 discipline="structural"),
    CategorySpec("OST_Topography",
                 ".OfCategory(BuiltInCategory.OST_Topography)",
                 discipline="architectural"),
    CategorySpec("OST_BuildingPad",
                 ".OfCategory(BuiltInCategory.OST_BuildingPad)",
                 discipline="architectural"),
    CategorySpec("OST_FilledRegion",
                 ".OfCategory(BuiltInCategory.OST_FilledRegion)",
                 discipline="architectural"),
    CategorySpec("OST_MaskingRegion",
                 ".OfCategory(BuiltInCategory.OST_MaskingRegion)",
                 discipline="architectural"),
    CategorySpec("OST_Cornices",
                 ".OfCategory(BuiltInCategory.OST_Cornices)",
                 discipline="architectural"),
    CategorySpec("OST_Reveals",
                 ".OfCategory(BuiltInCategory.OST_Reveals)",
                 discipline="architectural"),
    CategorySpec("OST_EdgeSlab",
                 ".OfCategory(BuiltInCategory.OST_EdgeSlab)",
                 discipline="architectural"),
    CategorySpec("OST_StairsLandings",
                 ".OfCategory(BuiltInCategory.OST_StairsLandings)",
                 discipline="architectural"),
    CategorySpec("OST_PathOfTravelLines",
                 ".OfCategory(BuiltInCategory.OST_PathOfTravelLines)",
                 discipline="architectural"),
)
EXTRACT_CATEGORIES = tuple(spec.name for spec in _CATEGORY_SPECS)
_SPEC_BY_NAME = {spec.name: spec for spec in _CATEGORY_SPECS}


# ═════════════════════════════════════════════════════════════════════════
# EXPIRATION DATE OF THE RULE "THE MEASURED THING ENTERS" (22.08.2026)
#
# WHAT HAPPENED. This table's admission rule is correct, but its input is
# THE CORPUS, and the corpus grows. On 29.07, window tags were not admitted
# with the argument "they are absent from the measured document"; the
# measured document was ONE file (`k2_ar_rd_v6`). On 20.08 a second building
# arrived in the corpus, and it has 660 window tags. The argument wasn't a
# mistake — it expired, and it expired SILENTLY, because nowhere was it
# recorded either WHERE it was measured or WHAT to do when a new building
# arrives. This is how a table ends up fitted to the first house forever.
#
# THE CURE IS A LAW, NOT PROSE. A tag kind is the only kind of category
# where the "take / don't take" decision is made purely by number (one op
# `create_tag` for all, one side stage for all, one lifter for all,
# branching in C# goes by the element's CLASS, not by category). So for it,
# completeness can be demanded mechanically:
#
#     every tag kind measured NON-ZERO in the corpus must stand EITHER in
#     `EXTRACT_CATEGORIES` OR in the journal below.
#
# The equality is two-sided: a new building with an unfamiliar kind fails
# the gate (otherwise it would lie invisible), and a journal entry the
# corpus no longer confirms also fails it (otherwise the journal would rot
# in the other direction). Held by
# `tests/test_zero_measurement_exclusions_expire.py`; the instrument is
# `tag_categories_outside_the_law` below, which also counts this block's
# numbers.
#
# THE LAW'S BOUNDARY IS NAMED: a kind is recognized BY NAME
# (`endswith("Tags")`), i.e. by an Autodesk naming convention, not by an API
# property. A tag category named otherwise is not covered by the law — and
# this is recorded here, rather than left for the reader as "the instrument
# is silent, so it's clean."
#
# 22.08 MEASUREMENT (11 corpus documents, one fullest decompile per
# building; census = the L0.jsonl header's `document.census`): 46 non-zero
# tag kinds. In the table: 11 kinds = 68 792 elements; outside the table: 35
# kinds = 4 813 elements, i.e. 6.5 % of all the corpus's tags. The largest
# untaken one is OST_RevisionCloudTags, 2 271; the remaining thirty together
# give 2 542.
#: Tag kinds MEASURED non-zero and NOT admitted into the table. This is a
#: debt with a number, not silence: as long as this line stands, elements
#: of this kind are counted as `category_outside_table` in every run's
#: census.
#:
#: The value is the argument for WHY the kind isn't taken yet. The argument
#: is the same one today for all thirty-five, and it is more honest than
#: any individual one: the cost of a line is not in the line, but in the
#: dialect step and in rewriting every live snapshot (`resolve_dialect` keys
#: the generation by the table's length). They must be taken in ONE wave,
#: when it is decided to take them, not one kind per session.
TAG_CATEGORIES_NOT_TAKEN: Mapping[str, str] = MappingProxyType({
    "OST_RevisionCloudTags": "2 271 в 4 документах — крупнейший невзятый",
    "OST_ElectricalFixtureTags": "497 в 2",
    "OST_TelephoneDeviceTags": "378 в 1",
    "OST_LightingFixtureTags": "366 в 1",
    "OST_MEPSpaceTags": "295 в 2",
    "OST_SpecialityEquipmentTags": "248 в 2",
    "OST_ElectricalEquipmentTags": "123 в 2",
    "OST_DetailComponentTags": "93 в 2",
    "OST_PathOfTravelTags": "93 в 1",
    "OST_WireTags": "86 в 1",
    "OST_PipeTags": "81 в 1",
    "OST_PlantingTags": "62 в 2",
    "OST_RoofTags": "38 в 2",
    "OST_ParkingTags": "36 в 2",
    "OST_GenericModelTags": "17 в 2",
    "OST_SitePropertyLineSegmentTags": "14 в 2",
    "OST_SitePropertyTags": "14 в 1",
    "OST_KeynoteTags": "9 в 2",
    "OST_CeilingTags": "8 в 1 — назван в прозе 29.07 как «которого нет»",
    "OST_CurtainWallPanelTags": "8 в 1",
    "OST_FurnitureTags": "8 в 1",
    "OST_PlumbingFixtureTags": "8 в 1",
    "OST_StructuralFoundationTags": "8 в 1",
    "OST_StairsLandingTags": "6 в 1",
    "OST_StairsRunTags": "6 в 1",
    "OST_StairsSupportTags": "6 в 1",
    "OST_StairsTags": "6 в 1",
    "OST_StructuralColumnTags": "6 в 1",
    "OST_AssemblyTags": "5 в 1",
    "OST_ConduitTags": "5 в 1",
    "OST_PartTags": "4 в 1",
    "OST_BeamSystemTags": "2 в 1",
    "OST_ELECTRICAL_AreaBasedLoads_Tags": "2 в 1",
    "OST_MassTags": "2 в 1",
    "OST_PlumbingEquipmentTags": "2 в 1",
})


def is_tag_category(name: str) -> bool:
    """A tag's kind — by name. An Autodesk convention, and this is said out
    loud.

    A tag's kind cannot be checked from Python by an API property: there are
    no BuiltInCategory members in RevitAPI.xml at all (29.07 measurement),
    and the gate has no live Revit. The name is the only available marker,
    so it is named as a marker, and not passed off as an API fact.
    """
    return name.startswith("OST_") and name.endswith("Tags")


def tag_categories_outside_the_law(
        census_by_document: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Who broke the tag-kind completeness law. A PURE function, no disk.

    Input: {document name: {category: how many elements in the census}} —
    exactly what lies in every L0's header (`document.census`).

    Output — two DIFFERENT violations, and they must not be mixed, because
    they are cured oppositely:

    ``unledgered``  {category: {document: count}} — the kind is measured
        non-zero, but it is not in the table and the journal doesn't know
        about it. This is exactly a rotted argument: a new house arrived
        and brought a kind the table had never heard of. Cured by a line —
        into the table or into the journal, but NAMED.

    ``unconfirmed`` {category: {}} — the kind stands in the journal, but the
        corpus no longer measures it non-zero anywhere. The journal has
        stopped being a measurement and become memory; the line must be
        removed or the reason the measurement went away explained.

    Both empty = the law holds. There isn't a single "probably" here: the
    function knows nothing about Revit, it compares two sets of names.
    """
    seen: dict[str, dict[str, int]] = {}
    for document, census in census_by_document.items():
        for category, count in census.items():
            if not is_tag_category(category) or int(count) <= 0:
                continue
            seen.setdefault(category, {})[document] = int(count)
    table = set(EXTRACT_CATEGORIES)
    unledgered = {
        category: dict(sorted(documents.items()))
        for category, documents in sorted(seen.items())
        if category not in table and category not in TAG_CATEGORIES_NOT_TAKEN
    }
    unconfirmed = {
        category: {}
        for category in sorted(TAG_CATEGORIES_NOT_TAKEN)
        if category not in seen
    }
    return {"unledgered": unledgered, "unconfirmed": unconfirmed}


# ═════════════════════════════════════════════════════════════════════════
# REFUSAL UNDER HALF (a) OF THE ADMISSION RULE: DERIVED, NOT CONTENT
#
# WHY AS DATA. On 22.08, decompiling the real building MNVNK called
# `OST_Parts` (2 735 elements, 0 in the decompile) a LOSS, and it cost half a
# wave: "take" and "don't take" looked equally cheap, because the previous
# decision lay as PROSE in a comment above the table and could neither be
# asked nor checked. A record here costs the same number of lines, but the
# instrument sees it.
#
# 🔴 THIS LAW'S BOUNDARY IS NAMED, AND IT IS NARROWER THAN THE TAG LAW'S
# BOUNDARY. For tag kinds, completeness is required mechanically: a kind is
# recognized BY NAME (`endswith("Tags")`), so "everything measured must
# stand either in the table or in the journal" is a checkable claim.
# DERIVED-NESS is recognized by nothing at all: there is nothing to
# enumerate "all of Revit's derived categories" with, and a completeness law
# here would be a LIE dressed up as a check. So this law has two sides, not
# three, and both are about the journal itself:
#
#     `unconfirmed`  — a record the corpus no longer measures non-zero:
#                      the journal has stopped being a measurement and
#                      become memory;
#     `contradicted` — a record whose category SIMULTANEOUSLY stands in the
#                      reading table: two opposite decisions about one name.
#
# The absence of a third side (`unledgered`, as with tags) here is
# DELIBERATE: silence about a category that isn't in the journal means
# "no one looked," and passing that off as "clean" is forbidden. This is
# exactly how the window-tags argument rotted.
#
# 22.08 MEASUREMENT (10 corpus buildings, one fullest decompile per
# building; census = the L0.jsonl header's `document.census`). The numbers
# in the values are THIS run's, and they are recomputed by the test.
#: Categories MEASURED non-zero in the corpus and not admitted into the
#: table because their elements are DERIVED from another element. The value
#: is the argument, and it must say WHAT the category is derived from:
#: "we decided not to take it" without this is indistinguishable from
#: "no one looked."
DERIVED_CATEGORIES_NOT_TAKEN: Mapping[str, str] = MappingProxyType({
    # Sketches and auto-dimensioning are derived from THEIR OWN HOST; the
    # host is read by the table, and its sketch is reconstructed by a side
    # stage (`sketch_extract`), not by a category line.
    "OST_SketchLines": "232 149 в 10 зданиях — эскиз своего носителя",
    "OST_WeakDims": "156 122 в 10 — автонанесение размеров в эскизе",
    "OST_StairsSketchBoundaryLines": "584 в 6 — эскиз лестницы",
    "OST_StairsSketchPathLines": "205 в 5 — эскиз лестницы",
    "OST_StairsSketchRunLines": "3 в 1 — эскиз лестницы",
    "OST_StairsSketchLandingCenterLines": "3 в 1 — эскиз лестницы",
    # The analytical model is derived by Revit from the physical one.
    "OST_AnalyticalNodes": "6 954 в 5 — выводится из физической модели",
    "OST_AnalyticalMember": "1 729 в 5 — выводится из физической модели",
    # Stair and railing parts are parts, not elements: they are created by
    # the host, which is read.
    "OST_StairsRuns": "564 в 7 — часть лестницы, а не элемент",
    # 🔴 OST_StairsLandings WAS REMOVED FROM HERE ON 04.09.2026, AND THIS IS
    # A RESOLUTION OF A CONTRADICTION, NOT A FIX FOR A WAVE. The line read
    # "278 in 6 — a stair part, not an element," meaning the landing is
    # produced by the host, which is read. An opposite contract in this SAME
    # tree asserted the opposite, with a consequence: "until then every
    # landing of a decompiled building is lost silently, and the stairs
    # lifts as its run alone".
    #
    # Both sides cannot exist. What resolves them is an argument, not a
    # vote: the "part" classification predicts that raising the HOST will
    # return the landing, while the contract says the stair is raised as ONE
    # SINGLE RUN. So the host does not produce it, and "part, not element"
    # is wrong here.
    #
    # The category was added to the table by the 04.09 wave; it cannot be
    # removed back even if desired — the ladder of dialects strictly
    # increases in length, and that too is an argument: the table is
    # appended to, while decisions about it are revised out loud.
    "OST_RailingTopRail": "304 в 7 — часть ограждения, а не элемент",
    # 🔴 PARTS (22.08.2026). The category was called a LOSS in
    # `tools/production_technique.py` ("live 2735, in the decompile 0"), and
    # the 22.08 wave was going to take it. THE MEASUREMENT CANCELED THE
    # ITEM, and canceling costs more than executing.
    #
    # WHAT DECIDED IT. The oracle is RevitAPI.xml of all six versions, and it
    # is asked about the class's MEANING, not about a member's existence
    # (for existence, documentation is not an authority — the canon carries
    # two cases where Autodesk documents a member that isn't in the
    # assembly; for WHAT a class IS, no other oracle exists at all):
    #
    #   T:Part                    «This element represents a part of ANOTHER
    #                              ELEMENT»
    #   M:Part.GetSourceElementIds «elements FROM WHICH this Part is created
    #                              by the PartMaker»
    #   P:Part.OriginalCategoryId  «category Id of the ORIGINAL element»
    #   T:PartMaker               «takes some source elements (e.g. a wall
    #                              with all its layers) and CREATES one or
    #                              more Parts out of it»
    #
    # That is, a part is the result of cutting up an already-read host, and
    # half (a) of the admission rule is not satisfied literally. Taking it,
    # we would read the RESULT without reading the ACT, and would put into
    # L0 the volume of walls that is already in L0.
    #
    # NUMBERS CONFIRM THE READING, THEY DO NOT REPLACE IT. Across the corpus
    # there are 2 765 parts, 2 735 of them (98.9 %) in one document.
    # `OST_Parts` and `OST_Divisions` are non-zero in EXACTLY THE SAME four
    # buildings and zero in exactly the same six (2735/1151, 28/10, 1/1,
    # 1/1): a match of 4 of 4 and 6 of 6 — exactly what you'd expect from an
    # "act → result" pair.
    #
    # 🔴 THE NEXT WAVE'S ADDRESS, AND IT IS DIFFERENT. Authorship lives in
    # the DIVISION (`PartMaker`, category OST_Divisions, 1 163 in 4
    # buildings), not in the part. It is that which must be taken, together
    # with an op over `PartUtils.CreateParts` / `DivideParts`.
    # `OST_Divisions` is deliberately NOT in this journal: calling the act
    # itself derived would be a false argument, and the journal holds
    # arguments.
    "OST_Parts": ("2 765 в 4 зданиях, 98.9 % из них в одном — «a part of "
                  "another element» (RevitAPI.xml): результат разрезания "
                  "читаемого носителя. Авторство в OST_Divisions"),
})


def derived_categories_outside_the_law(
        census_by_document: Mapping[str, Mapping[str, int]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Who broke the derived-categories journal's law. A PURE function, no
    disk.

    The input is the same as :func:`tag_categories_outside_the_law`'s:
    {document: {category: how many elements in the census}} — the
    `document.census` field of the L0 header.

    Output — TWO violations, and they are cured oppositely:

    ``unconfirmed``  {category: {}} — the record exists, but the corpus no
        longer measures this category non-zero anywhere. The argument has
        stopped resting on a measurement; remove the line or say where the
        measurement went.

    ``contradicted`` {category: {document: count}} — the category stands
        BOTH in the refusal journal AND in the reading table. Two opposite
        decisions about one name: one of them is false, and the table wins
        silently.

    🔴 THERE IS NO THIRD SIDE HERE, AND THIS IS NOT FORGOTTEN. There is no
    law that "every derived category of the corpus must stand in the
    journal": derived-ness is not recognized by name, there is nothing to
    enumerate the class with. An empty answer from this function means "the
    journal does not contradict the corpus," NOT "everything derived is
    accounted for."
    """
    seen: dict[str, dict[str, int]] = {}
    for document, census in census_by_document.items():
        for category, count in census.items():
            if int(count) <= 0:
                continue
            seen.setdefault(category, {})[document] = int(count)
    table = set(EXTRACT_CATEGORIES)
    unconfirmed = {
        category: {}
        for category in sorted(DERIVED_CATEGORIES_NOT_TAKEN)
        if category not in seen
    }
    contradicted = {
        category: dict(sorted(seen.get(category, {}).items()))
        for category in sorted(DERIVED_CATEGORIES_NOT_TAKEN)
        if category in table
    }
    return {"unconfirmed": unconfirmed, "contradicted": contradicted}


_COMMON_HELPERS_CS = r"""
Func<double, double> __MM = (__value) =>
    UnitUtils.ConvertFromInternalUnits(__value, UnitTypeId.Millimeters);
Func<Element, long> __Id = (__e) =>
{
    try { return long.Parse(__e.Id.ToString()); }
    catch { return long.MinValue; }
};
""".strip() + "\n" + element_level_helpers_cs("__src")
#: 🔴 "__src", NOT "doc": the extraction body ALWAYS binds a source
#: (`Document __src = doc;` without a link, the linked document with one),
#: so one name is correct in both cases. With `doc`, a link element's level
#: was searched for in the HOST — different spaces, matching numbers.


_ELEMENT_HELPERS_CS = r"""
// КВИТАНЦИИ fail-open сечений (ревью кодекса №12). Прежде null, HasValue=false,
// чужой StorageType и исключение схлопывались в ОДИН отсутствующий ключ:
// «у этого класса параметра нет» было неотличимо от «параметр есть, а
// прочитать не вышло». Замер v13: ширина у 992 стен из 1189, все 197 пропусков
// совпадают с витражными носителями — совпадение идеальное, а доказательства
// не было. Счётчики агрегатные (шесть int на ПАРАМЕТР, не на элемент),
// поэтому цена не зависит от размера модели.
var __sectionReceipts = new Dictionary<string, int[]>();
Action<string, int> __BumpSection = (__name, __slot) =>
{
    int[] __row;
    if (!__sectionReceipts.TryGetValue(__name, out __row))
    {
        __row = new int[6];
        __sectionReceipts[__name] = __row;
    }
    __row[__slot] = __row[__slot] + 1;
};
Action<Element, Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutSectionParam = (__e, __typeEl, __bip, __name, __params) =>
{
    if (__RouteSkips(__name)) return;
    // Ровно ОДИН инкремент на вызов: иначе сумма перестанет быть переписью.
    bool __counted = false;
    try
    {
        Parameter __p = null;
        bool __exists = false;
        bool __fromType = false;
        try { __p = __e.get_Parameter(__bip); } catch { }
        if (__p != null) __exists = true;
        if (__p == null || !__p.HasValue)
        {
            Parameter __tp = null;
            try
            {
                if (__typeEl != null) __tp = __typeEl.get_Parameter(__bip);
            }
            catch { }
            if (__tp != null)
            {
                __exists = true;
                if (__tp.HasValue) { __p = __tp; __fromType = true; }
            }
        }
        if (__p == null || !__p.HasValue)
        {
            // 2 = not_applicable: параметра нет НИ на экземпляре, НИ на типе —
            // класс элемента его не имеет вовсе. 3 = no_value: параметр есть,
            // значение не задано. Это разные диагнозы одной пустой ячейки.
            __counted = true;
            __BumpSection(__name, __exists ? 3 : 2);
            return;
        }
        if (__p.StorageType != StorageType.Double)
        {
            __counted = true;
            __BumpSection(__name, 4);
            return;
        }
        __params[__name] = __MM(__p.AsDouble());
        __counted = true;
        __BumpSection(__name, __fromType ? 1 : 0);
    }
    catch { if (!__counted) __BumpSection(__name, 5); }
};
// Сечение, которое НЕ длина: WALL_CROSS_SECTION ("Cross-Section") —
// перечисление (Integer), отличающее vertical от slanted/tapered. Читать его
// через __PutSectionParam нельзя: тот требует StorageType.Double и записал бы
// каждой стене `wrong_storage` — ответ честный, но бесполезный. Квитанция
// ОБЩАЯ с длинами: закон переписи (сумма шести исходов = число опрошенных)
// не различает тип хранения.
Action<Element, Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutSectionIntParam = (__e, __typeEl, __bip, __name, __params) =>
{
    if (__RouteSkips(__name)) return;
    bool __counted = false;
    try
    {
        Parameter __p = null;
        bool __exists = false;
        bool __fromType = false;
        try { __p = __e.get_Parameter(__bip); } catch { }
        if (__p != null) __exists = true;
        if (__p == null || !__p.HasValue)
        {
            Parameter __tp = null;
            try
            {
                if (__typeEl != null) __tp = __typeEl.get_Parameter(__bip);
            }
            catch { }
            if (__tp != null)
            {
                __exists = true;
                if (__tp.HasValue) { __p = __tp; __fromType = true; }
            }
        }
        if (__p == null || !__p.HasValue)
        {
            __counted = true;
            __BumpSection(__name, __exists ? 3 : 2);
            return;
        }
        if (__p.StorageType != StorageType.Integer)
        {
            __counted = true;
            __BumpSection(__name, 4);
            return;
        }
        __params[__name] = __p.AsInteger();
        __counted = true;
        __BumpSection(__name, __fromType ? 1 : 0);
    }
    catch { if (!__counted) __BumpSection(__name, 5); }
};
// СВЯЗЬ-ПАРАМЕТР С КВИТАНЦИЕЙ. Зеркало `__PutSectionIntParam` для
// StorageType.ElementId. Пустая ссылка (`AsElementId() == -1`) ложится в
// `no_value`, а не в отдельный бакет: канон называет её «пустой связью»
// прямым текстом (замер на балке 27.07), и шести исходов переписи хватает
// ровно потому, что закон суммы их не различает.
Action<Element, Element, BuiltInParameter, string, Dictionary<string, object>>
    __PutSectionIdParam = (__e, __typeEl, __bip, __name, __params) =>
{
    if (__RouteSkips(__name)) return;
    bool __counted = false;
    try
    {
        Parameter __p = null;
        bool __exists = false;
        bool __fromType = false;
        try { __p = __e.get_Parameter(__bip); } catch { }
        if (__p != null) __exists = true;
        if (__p == null || !__p.HasValue)
        {
            Parameter __tp = null;
            try
            {
                if (__typeEl != null) __tp = __typeEl.get_Parameter(__bip);
            }
            catch { }
            if (__tp != null)
            {
                __exists = true;
                if (__tp.HasValue) { __p = __tp; __fromType = true; }
            }
        }
        if (__p == null || !__p.HasValue)
        {
            __counted = true;
            __BumpSection(__name, __exists ? 3 : 2);
            return;
        }
        if (__p.StorageType != StorageType.ElementId)
        {
            __counted = true;
            __BumpSection(__name, 4);
            return;
        }
        var __id = __p.AsElementId();
        if (__id == null || __id == ElementId.InvalidElementId)
        {
            __counted = true;
            __BumpSection(__name, 3);
            return;
        }
        __params[__name] = __id.ToString();
        __counted = true;
        __BumpSection(__name, __fromType ? 1 : 0);
    }
    catch { if (!__counted) __BumpSection(__name, 5); }
};
Action<Element, Dictionary<string, object>> __PutParams = (__e, __row) =>
{
    // Выборка считается ОДИН раз на элемент: иначе 43 зонда дали бы 43 разных
    // ответа на вопрос «этот элемент проверяемый».
    __auditNow = (__routeSeen++ % __routeEvery) == 0;
    var __params = new Dictionary<string, object>();
    // 🔴 ТИП БЕРЁТСЯ ОДИН РАЗ НА ЭЛЕМЕНТ, А НЕ ОДИН РАЗ НА ЗОНД.
    //
    // Замер 20.08.2026 по квитанциям корпуса (28 категорий, 3 661 545
    // зондов): на экземпляре промахиваются 82.1 % — `not_applicable` 76.2 %
    // плюс `type_hit` 5.9 %, — и КАЖДЫЙ такой промах отдельно спрашивал
    // `doc.GetElement(__e.GetTypeId())`. При 43 зондах это ~35 обращений к
    // документу на элемент там, где достаточно одного; по корпусу
    // (173 698 элементов) — порядка 6.1 млн лишних поисков.
    //
    // Правка НЕ трогает ни одного значения: тот же элемент типа, тот же
    // `get_Parameter`, та же квитанция. Она снимает повтор, а не проверку —
    // и потому, в отличие от маршрутизации по категориям, не может ничего
    // потерять молча.
    Element __typeEl = null;
    try { __typeEl = __src.GetElement(__e.GetTypeId()); } catch { }
    __PutSectionParam(__e, __typeEl, BuiltInParameter.WALL_USER_HEIGHT_PARAM,
                     nameof(BuiltInParameter.WALL_USER_HEIGHT_PARAM), __params);
    // audit F6: vertical wall attributes.  WALL_BASE_OFFSET (length, mm) and
    // WALL_HEIGHT_TYPE (the attached top-constraint level's id; __PutSectionIdParam
    // skips InvalidElementId, so an unconnected wall carries neither key).
    // Additive: params is the open per-element dictionary, frozen L0 1.0
    // schema untouched.
    __PutSectionParam(__e, __typeEl, BuiltInParameter.WALL_BASE_OFFSET,
                     nameof(BuiltInParameter.WALL_BASE_OFFSET), __params);
    __PutSectionIdParam(__e, __typeEl, BuiltInParameter.WALL_HEIGHT_TYPE,
                 nameof(BuiltInParameter.WALL_HEIGHT_TYPE), __params);
    // Wall-fidelity (live A5 evidence 2026-07-21): WALL_TOP_OFFSET is a
    // DEFINING degree of freedom of an attached wall.  Unread, the rebuild
    // derives height as the full base->top span (emitter forced offset 0) and
    // every attached wall missed canon by exactly |top offset| (observed
    // -300/-400/-2100mm on «демо»).  Additive length param, same discipline
    // as WALL_BASE_OFFSET.
    __PutSectionParam(__e, __typeEl, BuiltInParameter.WALL_TOP_OFFSET,
                     nameof(BuiltInParameter.WALL_TOP_OFFSET), __params);
    // P1 DOF-completeness (fidelity audit 2026-07-21, Находка B): vertical
    // defining DOF of columns / floors / beams — the same class the wall's
    // top_offset belonged to.  Pull-only (lift ignores unread keys): this is
    // the EVIDENCE step — offline stats over a fresh L0 decide which lift/emit
    // chains are material.  All Put* helpers skip absent params, so every
    // category stays byte-compatible.
    __PutSectionIdParam(__e, __typeEl, BuiltInParameter.FAMILY_BASE_LEVEL_PARAM,
                 nameof(BuiltInParameter.FAMILY_BASE_LEVEL_PARAM), __params);
    __PutSectionIdParam(__e, __typeEl, BuiltInParameter.FAMILY_TOP_LEVEL_PARAM,
                 nameof(BuiltInParameter.FAMILY_TOP_LEVEL_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM,
                     nameof(BuiltInParameter.FAMILY_BASE_LEVEL_OFFSET_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM,
                     nameof(BuiltInParameter.FAMILY_TOP_LEVEL_OFFSET_PARAM), __params);
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.SLANTED_COLUMN_TYPE_PARAM,
                  nameof(BuiltInParameter.SLANTED_COLUMN_TYPE_PARAM), __params);
    // A wall is a location CURVE plus the rule saying which plane of the wall
    // that curve is (centreline, core centreline, or one of four faces).  Two
    // walls with identical endpoints and identical types occupy DIFFERENT
    // space when the rule differs -- by half the thickness, 100mm for the
    // 200mm types LOT31 is full of.  Unread, the round trip compares curves,
    // the curves match, and a wall standing 100mm away is recorded `exact`:
    // twenty times the 5mm endpoint tolerance, and a metric lying in its own
    // favour.  An enum ordinal, so Int and never Length -- reading it as a
    // length would unit-convert it into a plausible wrong number.
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.WALL_KEY_REF_PARAM,
                  nameof(BuiltInParameter.WALL_KEY_REF_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM,
                     nameof(BuiltInParameter.FLOOR_HEIGHTABOVELEVEL_PARAM), __params);
    // Потолочное смещение — СВОЁ имя, а не floor-овское: имя параметра здесь
    // часть тождества категории. `_lift_ceiling` (lift.py:1787) читало
    // CEILING_HEIGHTABOVELEVEL_PARAM, которого захват не клал НИКОГДА, и
    // каждый потолок поднимался на отметке уровня. Не отказом — молчаливым
    // нулём, худшим из двух исходов, названных ведомостью захвата. Тот же
    // род расхождения, что стоил 2153 помещений: производитель поля и его
    // потребитель договорились комментарием, а не контрактом.
    __PutSectionParam(__e, __typeEl, BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM,
                     nameof(BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM), __params);
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL,
                  nameof(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION,
                     nameof(BuiltInParameter.STRUCTURAL_BEAM_END0_ELEVATION), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION,
                     nameof(BuiltInParameter.STRUCTURAL_BEAM_END1_ELEVATION), __params);
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.Z_JUSTIFICATION,
                  nameof(BuiltInParameter.Z_JUSTIFICATION), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.Z_OFFSET_VALUE,
                     nameof(BuiltInParameter.Z_OFFSET_VALUE), __params);
    // СЕЧЕНИЯ — все одиннадцать через __PutSectionParam, который сам падает
    // на ТИП элемента (толщина стены живёт на WallType, а не на стене) и
    // ОСТАВЛЯЕТ КВИТАНЦИЮ о причине пропуска (ревью кодекса №12). Имена
    // сверены по RevitAPI.xml (ref/net8.0) — в частности WALL_ATTR_WIDTH_PARAM,
    // а НЕ WALL_ATTR_WIDTH: члена с таким именем в перечислении нет вовсе.
    // Без этих чисел клеш-детектор строит только габаритные боксы (замер D1
    // на фасаде SOB6.2: exact=0 из 2754 оболочек).
    // R3 красных: RBS_PIPE_DIAMETER_PARAM — это "Diameter", то есть НОМИНАЛ.
    // У ДУ100 он 100 мм при наружном 114.3: капсула радиуса 50 не содержит
    // тела радиуса 57.15, и клеш пропускается в паре MVP. Наружный —
    // отдельный параметр, и снимать надо ОБА: номинал остаётся квитанцией
    // «наружного не нашлось», а не молчаливой заменой ему.
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_PIPE_DIAMETER_PARAM,
                     nameof(BuiltInParameter.RBS_PIPE_DIAMETER_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
                     nameof(BuiltInParameter.RBS_PIPE_OUTER_DIAMETER), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
                     nameof(BuiltInParameter.RBS_CURVE_DIAMETER_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
                     nameof(BuiltInParameter.RBS_CURVE_WIDTH_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CURVE_HEIGHT_PARAM,
                     nameof(BuiltInParameter.RBS_CURVE_HEIGHT_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.WALL_ATTR_WIDTH_PARAM,
                     nameof(BuiltInParameter.WALL_ATTR_WIDTH_PARAM), __params);
    // ⛔ ЗАМЕР v18 ОТМЕНЁН 20.08.2026 ПЕРЕМЕРОМ ПО ВСЕМУ КОРПУСУ. Он говорил
    // «WALL_CROSS_SECTION не снят НИ У ОДНОЙ из 2360 стен» — сегодня он снят
    // у 220 812 стен из 286 430 (77.1 %), вертикальных 220 782. Строка ниже
    // работает; отменяется утверждение о ней, а не она сама.
    //
    // И ВЫВОД ИЗ НЕЁ ТОЖЕ БЫЛ НЕВЕРЕН: призма запрещена НЕ потому, что
    // «отличить vertical от slanted нечем». Полный набор величин лежит в L0 у
    // 203 661 стены (71.1 %). Запрещает её `hulls.WALL_BAND_REFUSAL`: полоса
    // вокруг оси не содержит настоящего тела (стык до 250 мм за конец, 93
    // стены из 800 шире собственной WallType.Width до 2854 мм). Разбор —
    // в `hulls.WALL_WITNESS_2026_08_20`.
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.WALL_CROSS_SECTION,
                     nameof(BuiltInParameter.WALL_CROSS_SECTION), __params);
    // ПРИСОЕДИНЕНИЕ верха/низа стены. Замер v19: у присоединённой стены
    // реальная высота НЕ равна WALL_USER_HEIGHT_PARAM (8234565: параметр
    // 7970 мм при настоящих 9755 мм), а присоединение к КРЫШЕ не описывается
    // даже отметкой верхнего уровня. Признак структурный и универсальный —
    // никаких имён типов и семейств. Квитанция ОБЩАЯ с сечениями.
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.WALL_TOP_IS_ATTACHED,
                     nameof(BuiltInParameter.WALL_TOP_IS_ATTACHED), __params);
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.WALL_BOTTOM_IS_ATTACHED,
                     nameof(BuiltInParameter.WALL_BOTTOM_IS_ATTACHED), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
                     nameof(BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM,
                     nameof(BuiltInParameter.RBS_CABLETRAY_HEIGHT_PARAM), __params);
    // "Diameter(Trade Size)" — номинал прямым текстом в API.
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM,
                     nameof(BuiltInParameter.RBS_CONDUIT_DIAMETER_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
                     nameof(BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH,
                     nameof(BuiltInParameter.STRUCTURAL_SECTION_COMMON_WIDTH), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STRUCTURAL_SECTION_COMMON_HEIGHT,
                     nameof(BuiltInParameter.STRUCTURAL_SECTION_COMMON_HEIGHT), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STRUCTURAL_SECTION_COMMON_DIAMETER,
                     nameof(BuiltInParameter.STRUCTURAL_SECTION_COMMON_DIAMETER), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.FAMILY_WIDTH_PARAM,
                     nameof(BuiltInParameter.FAMILY_WIDTH_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.FAMILY_HEIGHT_PARAM,
                     nameof(BuiltInParameter.FAMILY_HEIGHT_PARAM), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM,
                     nameof(BuiltInParameter.INSTANCE_SILL_HEIGHT_PARAM), __params);
    __PutSectionIdParam(__e, __typeEl, BuiltInParameter.STAIRS_BASE_LEVEL_PARAM,
                 nameof(BuiltInParameter.STAIRS_BASE_LEVEL_PARAM), __params);
    __PutSectionIdParam(__e, __typeEl, BuiltInParameter.STAIRS_TOP_LEVEL_PARAM,
                 nameof(BuiltInParameter.STAIRS_TOP_LEVEL_PARAM), __params);
    // ─── ШЕСТЬ, ВНЕСЁННЫХ 20.08.2026: У КАЖДОГО НАЗВАН ПОТРЕБИТЕЛЬ ───────
    //
    // Правило пригодности, которое МОЛЧИТ, и правило, которое СУДИТ ПО
    // ПОДСТАВЛЕННОЙ ВЕЛИЧИНЕ, — две разные болезни, и вторая хуже. Здесь
    // закрываются обе, и потребитель назван у каждой строки, чтобы захват
    // нельзя было прочитать как «сняли впрок».
    //
    // Имена сверены КОМПИЛЯЦИЕЙ против референс-сборок 2021–2026
    // (`tools/bip_exists.py`, все шесть — ВСЕ ШЕСТЬ версий), а не по
    // RevitAPI.xml: документация Autodesk расходится с её же сборками, и
    // канон несёт два таких случая поимённо.
    //
    // Тип НЕ НУЖЕН отдельным помощником: считающие помощники сами падают на
    // `doc.GetElement(__e.GetTypeId())`, если у экземпляра значения нет.
    //
    // 🔴 ЭТА СТРОКА ПРАВЛЕНА 20.08 В ТОТ ЖЕ ДЕНЬ, КОГДА НАПИСАНА. Она
    // говорила «идёт обычным `__PutLengthParam`, а `__PutSectionParam`
    // засорил бы перепись СЕЧЕНИЙ чужим знаменателем». Довод отменён вместе
    // с делением: перепись стала переписью ВСЕХ 43 зондов, молчаливых
    // помощников не осталось, и чужого знаменателя больше нет.
    //
    //   HAB050 «несущая стена». 🔴 ЭТИ ДВЕ СТРОКИ ПЕРЕПИСАНЫ 22.08 ПО ЗАМЕРУ:
    //   они говорили «сегодня `is_structural` не приходит ВОВСЕ, и правило
    //   молчит на всём корпусе», а это довод ДО добавления зонда, оставшийся
    //   стоять в настоящем времени после него. Живой замер по MNVNK:
    //   `WALL_STRUCTURAL_SIGNIFICANT` приходит у 7845 стен из 7845 и ВЕЗДЕ
    //   ноль. Правило молчит по ДРУГОЙ причине, и она противоположна по
    //   смыслу: «захвачено, и здание ответило НЕТ» (это AR-файл, несущность в
    //   нём не объявляется) — исход, который `_structural_vacuity` уже
    //   различает с 20.08.
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT,
                  nameof(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT), __params);
    //   HAB011 «уклон марша». Та же поправка: три величины ПРИХОДЯТ, 24 из 24
    //   лестниц MNVNK (замер 22.08), и написанное ниже про ширину это уже
    //   говорит. Правило молчит не потому, что величин нет, а потому, что до
    //   него не доезжает сама лестница: `design_check._stairs_from_l0`
    //   требует `STAIRS_TOP_LEVEL_PARAM`, здание вернуло по нему пусто, и все
    //   24 отброшены двумя этажами выше.
    __PutSectionIntParam(__e, __typeEl, BuiltInParameter.STAIRS_ACTUAL_NUM_RISERS,
                  nameof(BuiltInParameter.STAIRS_ACTUAL_NUM_RISERS), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STAIRS_ACTUAL_TREAD_DEPTH,
                     nameof(BuiltInParameter.STAIRS_ACTUAL_TREAD_DEPTH), __params);
    __PutSectionParam(__e, __typeEl, BuiltInParameter.STAIRS_ACTUAL_RISER_HEIGHT,
                     nameof(BuiltInParameter.STAIRS_ACTUAL_RISER_HEIGHT), __params);
    // 🔴 STAIRS_ATTR_TREAD_WIDTH ЗДЕСЬ НЕТ, И ЭТО НАЗВАННОЕ ОТСУТСТВИЕ, А НЕ
    // ЗАБЫТАЯ СТРОКА. Он был внесён вместе с пятью соседями 20.08 и снят в
    // тот же день ЖИВЫМ ПРОГОНОМ: `MNVNK_ATR_PD_B14_K6_AR_R2022`, Revit 2023,
    // 24 лестницы — `есть 0 / пусто 24 / отказ 0`. Не исключение и не отказ:
    // параметр на элементе ЕСТЬ и пуст, и `__Parameter` уже спросил тип.
    //
    // Причина найдена у авторитета, а не додумана: в референс-сборках
    // 2021–2026 у `Autodesk.Revit.DB.Architecture.Stairs` свойства ширины НЕТ
    // ВООБЩЕ (есть `ActualRiserHeight`, `ActualTreadDepth`,
    // `ActualRisersNumber` — те три, что живьём и пришли), а ширина живёт на
    // МАРШЕ: `StairsRun.ActualRunWidth`, одинаково на всех шести версиях.
    //
    // Взять её нечем СЕГОДНЯ: `OST_StairsRuns` в таблице извлечения нет — 77
    // категорий, лестничных три (`OST_Stairs`, `OST_StairsRailing`,
    // `OST_StairsRailingTags`).
    //
    // 🔴 «МАРШ НЕ ЧИТАЕТСЯ ВОВСЕ» СТОЯЛО ЗДЕСЬ И БЫЛО ШИРЕ ПРАВДЫ (снято
    // замером 22.08 по MNVNK). Марш читается — БОКОВОЙ СТАДИЕЙ, а не таблицей
    // категорий: `sketch_extract` зовёт `Stairs.GetStairsRuns()` и снял ПУТЬ
    // марша у 48 из 48. Верна только узкая половина утверждения: ширины
    // (`ActualRunWidth`) не снимает никто. Разница не косметическая — «стадии
    // нет» и «стадия есть, поля нет» чинятся разным, и первое послало бы
    // писать съём заново поверх работающего.
    //
    // ЧЕМ ЭТО ЗАКРЫВАЕТСЯ, когда дойдут руки (рецепт, а не намерение):
    // `Stairs.GetStairsRuns()` есть на всех шести версиях и отдаёт id маршей;
    // ширина снимается с каждого и ложится ОТДЕЛЬНЫМ ПОЛЕМ строки, НЕ в
    // `params`: ключи `params` равны именам `BuiltInParameter` (на этом стоит
    // `hulls.SECTION_RULES`), и величина, снятая свойством, там завела бы ключ
    // чужого рода.
    //
    // ЦЕНА МОЛЧАНИЯ НАЗВАНА: `HAB011` получает ТРИ величины из четырёх.
    // Уклон марша проверяем, ширина — нет.
    //   HAB022 «высота помещения» — 🔴 ЭТОТ ТРЕТЬЕГО РОДА И ОПАСНЕЕ ПЯТИ
    //   ПЕРВЫХ. Правило не молчит: оно выносит вердикт по величине, которой
    //   автор не объявлял, подставляя вертикальный размах ГАБАРИТА. От
    //   тихой лжи это отличает ровно одно — подстановка НАЗВАНА полем
    //   `height_source`. С этим параметром у правила появляется величина,
    //   которую помещение несёт САМО.
    __PutSectionParam(__e, __typeEl, BuiltInParameter.ROOM_UPPER_OFFSET,
                     nameof(BuiltInParameter.ROOM_UPPER_OFFSET), __params);
    __row["params"] = __params;
};
Action<Element, Dictionary<string, object>> __PutGroupingState = (__e, __row) =>
{
    __row["design_option"] = null;
    __row["phase_created"] = null;
    __row["workset"] = null;
    try
    {
        var __option = __e.DesignOption;
        if (__option != null)
            __row["design_option"] = new Dictionary<string, object> {
                {"id", __option.Id.ToString()}, {"name", __option.Name ?? ""}
            };
    }
    catch { }
    try
    {
        var __phaseId = __e.CreatedPhaseId;
        if (__phaseId != null && __phaseId != ElementId.InvalidElementId)
        {
            var __phase = __src.GetElement(__phaseId) as Phase;
            if (__phase != null)
                __row["phase_created"] = new Dictionary<string, object> {
                    {"id", __phase.Id.ToString()}, {"name", __phase.Name ?? ""}
                };
        }
    }
    catch { }
    try
    {
        if (__src.IsWorkshared)
        {
            var __workset = __src.GetWorksetTable().GetWorkset(__e.WorksetId);
            if (__workset != null)
                __row["workset"] = new Dictionary<string, object> {
                    {"id", __workset.Id.ToString()}, {"name", __workset.Name ?? ""}
                };
        }
    }
    catch { }
};
""".strip()


_METADATA_CS = r"""
Func<double, double> __MM = (__value) =>
    UnitUtils.ConvertFromInternalUnits(__value, UnitTypeId.Millimeters);
long __RoomAfter = __ROOM_AFTER__;
Func<XYZ, double[]> __VecMM = (__p) => new double[] {
    __MM(__p.X), __MM(__p.Y), __MM(__p.Z)
};
Func<double, bool> __Finite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
Func<Transform, string, Dictionary<string, object>> __TransformEvidence =
    (__transform, __targetFrame) =>
{
    var __transformGaps = new List<object>();
    object __matrix = null;
    if (__transform == null)
    {
        __transformGaps.Add("transform_unavailable");
    }
    else
    {
        try
        {
            XYZ __bx = __transform.BasisX;
            XYZ __by = __transform.BasisY;
            XYZ __bz = __transform.BasisZ;
            XYZ __origin = __transform.Origin;
            double __ox = __MM(__origin.X);
            double __oy = __MM(__origin.Y);
            double __oz = __MM(__origin.Z);
            double __nxx = __bx.DotProduct(__bx);
            double __nyy = __by.DotProduct(__by);
            double __nzz = __bz.DotProduct(__bz);
            double __nxy = __bx.DotProduct(__by);
            double __nxz = __bx.DotProduct(__bz);
            double __nyz = __by.DotProduct(__bz);
            double __det = __bx.X * (__by.Y * __bz.Z - __by.Z * __bz.Y)
                - __by.X * (__bx.Y * __bz.Z - __bx.Z * __bz.Y)
                + __bz.X * (__bx.Y * __by.Z - __bx.Z * __by.Y);
            const double __transformTolerance = 1e-8;
            bool __valid =
                __Finite(__bx.X) && __Finite(__bx.Y) && __Finite(__bx.Z) &&
                __Finite(__by.X) && __Finite(__by.Y) && __Finite(__by.Z) &&
                __Finite(__bz.X) && __Finite(__bz.Y) && __Finite(__bz.Z) &&
                __Finite(__ox) && __Finite(__oy) && __Finite(__oz) &&
                Math.Abs(__nxx - 1.0) <= __transformTolerance &&
                Math.Abs(__nyy - 1.0) <= __transformTolerance &&
                Math.Abs(__nzz - 1.0) <= __transformTolerance &&
                Math.Abs(__nxy) <= __transformTolerance &&
                Math.Abs(__nxz) <= __transformTolerance &&
                Math.Abs(__nyz) <= __transformTolerance &&
                Math.Abs(Math.Abs(__det) - 1.0) <= __transformTolerance;
            if (__valid)
            {
                // Row-major affine source -> parent. Basis is dimensionless;
                // only Origin crosses the Revit feet -> L0 millimetres seam.
                __matrix = new double[] {
                    __bx.X, __by.X, __bz.X, __ox,
                    __bx.Y, __by.Y, __bz.Y, __oy,
                    __bx.Z, __by.Z, __bz.Z, __oz,
                    0.0, 0.0, 0.0, 1.0
                };
            }
            else
            {
                __transformGaps.Add("transform_invalid");
            }
        }
        catch
        {
            __transformGaps.Add("transform_unavailable");
        }
    }
    return new Dictionary<string, object> {
        {"matrix", __matrix},
        {"status", __matrix == null ? "incomplete" : "authoritative"},
        {"gaps", __transformGaps},
        {"target_frame", __targetFrame}
    };
};
Func<string, object> __Text = (__value) =>
    String.IsNullOrWhiteSpace(__value) ? null : (object)__value;
var __result = new Dictionary<string, object>();
__result["doc_name"] = String.IsNullOrWhiteSpace(__src.Title) ? "(untitled)" : __src.Title;
__result["revit_version"] = __src.Application.VersionNumber;
__result["units"] = "mm";

// Document identity is a Revit-owned fact, not a filename and never a local
// ElementId promoted to global scope. Cloud project/model GUIDs and the Revit
// Server central GUID identify logical models. ProjectInformation.UniqueId is
// retained only as lineage evidence: Autodesk contracts Element.UniqueId as
// unique *within* one document, so Save As/copies cannot be disambiguated by
// it. The element revision GUID is deliberately absent: it is a revision
// witness, not identity, and would split one document after edits.
Func<Document, Dictionary<string, object>> __DocumentIdentityFact =
    (__document) =>
{
    try
    {
        if (__document.IsModelInCloud)
        {
            var __cloudPath = __document.GetCloudModelPath();
            if (__cloudPath != null)
            {
                var __projectGuid = __cloudPath.GetProjectGUID();
                var __modelGuid = __cloudPath.GetModelGUID();
                if (__projectGuid != Guid.Empty && __modelGuid != Guid.Empty)
                {
                    return new Dictionary<string, object> {
                        {"source", "cloud_project_model_guid"},
                        {"value", __projectGuid.ToString("D") + "/" +
                                  __modelGuid.ToString("D")}
                    };
                }
            }
        }
    }
    catch { }
    try
    {
        if (__document.IsWorkshared)
        {
            var __centralPath = __document.GetWorksharingCentralModelPath();
            var __serverPath = __centralPath as ServerPath;
            if (__serverPath != null)
            {
                var __centralGuid =
                    __document.Application.GetWorksharingCentralGUID(
                        __serverPath);
                if (__centralGuid != Guid.Empty)
                {
                    return new Dictionary<string, object> {
                        {"source", "revit_server_central_guid"},
                        {"value", __centralGuid.ToString("D")}
                    };
                }
            }
        }
    }
    catch { }
    string __projectUniqueId = null;
    try
    {
        var __projectInformation = __document.ProjectInformation;
        if (__projectInformation != null &&
            !String.IsNullOrWhiteSpace(__projectInformation.UniqueId))
            __projectUniqueId = __projectInformation.UniqueId;
    }
    catch { }
    if (String.IsNullOrWhiteSpace(__projectUniqueId)) return null;
    return new Dictionary<string, object> {
        {"source", "project_information_unique_id"},
        {"value", __projectUniqueId}
    };
};
Func<Dictionary<string, object>, bool> __DocumentIdentityAuthoritative =
    (__fact) =>
{
    if (__fact == null || !__fact.ContainsKey("source")) return false;
    string __source = __fact["source"] as string;
    return __source == "cloud_project_model_guid" ||
           __source == "revit_server_central_guid";
};
var __sourceDocumentIdentity = __DocumentIdentityFact(__src);
var __federationRootIdentity = __DocumentIdentityFact(__federationRoot);
var __sourceIdentityGaps = new List<object>();
var __sourceLinkChain = new List<object>();
if (__sourceDocumentIdentity == null)
    __sourceIdentityGaps.Add("source_document_identity_unavailable");
else if (!__DocumentIdentityAuthoritative(__sourceDocumentIdentity))
    __sourceIdentityGaps.Add("source_document_identity_not_authoritative");
if (__federationRootIdentity == null)
    __sourceIdentityGaps.Add("federation_root_identity_unavailable");
else if (!__DocumentIdentityAuthoritative(__federationRootIdentity))
    __sourceIdentityGaps.Add("federation_root_identity_not_authoritative");
if (__sourceLinkInstance != null)
{
    string __sourceLinkUniqueId = null;
    try
    {
        if (!String.IsNullOrWhiteSpace(__sourceLinkInstance.UniqueId))
            __sourceLinkUniqueId = __sourceLinkInstance.UniqueId;
    }
    catch { }
    if (__sourceLinkUniqueId == null)
        __sourceIdentityGaps.Add("link_instance_unique_id_unavailable");
    else
        __sourceLinkChain.Add(__sourceLinkUniqueId);
}
bool __sourceIdentityAuthoritative =
    __DocumentIdentityAuthoritative(__sourceDocumentIdentity) &&
    __DocumentIdentityAuthoritative(__federationRootIdentity) &&
    (__sourceLinkInstance == null || __sourceLinkChain.Count > 0) &&
    __sourceIdentityGaps.Count == 0;
__result["identity"] = new Dictionary<string, object> {
    {"schema_version", "kir-l0-revit-identity/1"},
    {"source_kind", __sourceLinkInstance == null ? "root" : "link"},
    {"document_identity", __sourceDocumentIdentity},
    {"federation_root_identity", __federationRootIdentity},
    {"link_instance_chain", __sourceLinkChain},
    {"status", __sourceIdentityAuthoritative
        ? "authoritative" : "incomplete"},
    {"gaps", __sourceIdentityGaps}
};
if (__sourceLinkInstance == null)
{
    __result["federation_transform"] = __TransformEvidence(
        Transform.Identity, "federation_root");
}
else
{
    try
    {
        __result["federation_transform"] = __TransformEvidence(
            __sourceLinkInstance.GetTotalTransform(), "federation_root");
    }
    catch
    {
        __result["federation_transform"] = __TransformEvidence(
            null, "federation_root");
    }
}

var __levels = new List<object>();
foreach (Level __level in new FilteredElementCollector(__src)
         .OfClass(typeof(Level)).WhereElementIsNotElementType()
         .Cast<Level>().OrderBy(__x => __x.Elevation)
         .ThenBy(__x => __x.Id.ToString()))
{
    __levels.Add(new Dictionary<string, object> {
        {"id", __level.Id.ToString()},
        {"name", __level.Name ?? ""},
        {"elevation_mm", __MM(__level.ProjectElevation)}
    });
}
__result["levels"] = __levels;

var __grids = new List<object>();
foreach (Grid __grid in new FilteredElementCollector(__src)
         .OfClass(typeof(Grid)).WhereElementIsNotElementType()
         .Cast<Grid>().OrderBy(__x => __x.Id.ToString()))
{
    var __curve = __grid.Curve;
    if (__curve == null)
        throw new InvalidOperationException(
            "Grid " + __grid.Id.ToString() + " has no curve");
    __grids.Add(new Dictionary<string, object> {
        {"id", __grid.Id.ToString()},
        {"name", __grid.Name ?? ""},
        {"p0_mm", __VecMM(__curve.GetEndPoint(0))},
        {"p1_mm", __VecMM(__curve.GetEndPoint(1))},
        // 🔴 ЧЕМ СОЕДИНЕНЫ КОНЦЫ. До 25.08 брались только они, и дуговая ось
        // приезжала ПРЯМОЙ: постусловие «концы == p0/p1» у хорды совпадает
        // с дугой точно, красного не было нигде. Грепом `IsCurved` по всему
        // дереву было НОЛЬ совпадений.
        {"curve_kind", __curve is Line ? "line" : __curve.GetType().Name}
    });
}
__result["grids"] = __grids;

var __rooms = new List<object>();
var __boundaryOptions = new SpatialElementBoundaryOptions();
var __roomPage = new FilteredElementCollector(__src)
    .OfCategory(BuiltInCategory.OST_Rooms)
    .WhereElementIsNotElementType()
    .Cast<Autodesk.Revit.DB.Architecture.Room>()
    .Where(__x => long.Parse(__x.Id.ToString()) > __RoomAfter)
    .OrderBy(__x => long.Parse(__x.Id.ToString()))
    .Take(__ROOM_TAKE__)
    .ToList();
bool __roomsHaveMore = __roomPage.Count > __ROOM_BATCH__;
if (__roomsHaveMore)
    __roomPage.RemoveRange(
        __ROOM_BATCH__, __roomPage.Count - __ROOM_BATCH__);
foreach (Autodesk.Revit.DB.Architecture.Room __room in __roomPage)
{
    var __roomRow = new Dictionary<string, object>();
    __roomRow["id"] = __room.Id.ToString();
    // Room.Name is a display composite (name + number), not ROOM_NAME.
    // Read the two independent built-in parameters so reverse compilation
    // never bakes a display label back into the authored name.
    Parameter __roomName = __room.get_Parameter(BuiltInParameter.ROOM_NAME);
    Parameter __roomNumber = __room.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    if (__roomName == null || __roomNumber == null)
        throw new InvalidOperationException(
            "Room " + __room.Id.ToString() +
            " has no ROOM_NAME/ROOM_NUMBER parameter");
    __roomRow["name"] = __roomName.AsString() ?? "";
    __roomRow["number"] = __roomNumber.AsString() ?? "";
    __roomRow["level_id"] = null;
    __roomRow["level_name"] = null;
    try
    {
        var __level = __room.Level;
        if (__level != null)
        {
            __roomRow["level_id"] = __level.Id.ToString();
            __roomRow["level_name"] = __level.Name ?? "";
        }
    }
    catch { }
    double __roomArea = UnitUtils.ConvertFromInternalUnits(
        __room.Area, UnitTypeId.SquareMeters);
    __roomRow["area_m2"] = __roomArea;

    var __loopsOut = new List<object>();
    var __boundaryIds = new List<object>();
    var __seenBoundaryIds = new HashSet<string>();
    // Area==0 is Revit's ordinary unplaced/unbounded-room state.  A placed
    // room, by contrast, must not become a plausible empty boundary merely
    // because an API read failed.
    if (__roomArea > 0.0)
    {
        var __loops = __room.GetBoundarySegments(__boundaryOptions);
        if (__loops == null || __loops.Count == 0)
            throw new InvalidOperationException(
                "Placed room " + __room.Id.ToString() +
                " has no readable boundary");
        foreach (var __loop in __loops)
        {
            var __points = new List<object>();
            foreach (var __segment in __loop)
            {
                var __point = __segment.GetCurve().GetEndPoint(0);
                __points.Add(new double[] {
                    __MM(__point.X), __MM(__point.Y)
                });
                var __boundaryId = __segment.ElementId;
                if (__boundaryId != null &&
                    __boundaryId != ElementId.InvalidElementId)
                {
                    string __id = __boundaryId.ToString();
                    if (__seenBoundaryIds.Add(__id))
                        __boundaryIds.Add(__id);
                }
            }
            __loopsOut.Add(__points);
        }
    }
    __roomRow["boundary_loops_mm"] = __loopsOut;
    __roomRow["boundary_mm"] =
        __loopsOut.Count > 0 ? __loopsOut[0] : new List<object>();
    __roomRow["bounding_element_ids"] = __boundaryIds;
    __rooms.Add(__roomRow);
}
__result["rooms"] = __rooms;
__result["rooms_has_more"] = __roomsHaveMore;
__result["rooms_next_cursor"] = (
    __roomsHaveMore && __roomPage.Count > 0
    ? (object)__roomPage[__roomPage.Count - 1].Id.ToString()
    : null);

var __project = new Dictionary<string, object>();
__project["name"] = null;
__project["address"] = null;
__project["building_type_hint"] = null;
try
{
    var __info = __src.ProjectInformation;
    if (__info != null)
    {
        __project["name"] = __Text(__info.Name);
        __project["address"] = __Text(__info.Address);
    }
}
catch { }
__result["project_info"] = __project;

Func<string, string> __Discipline = (__name) =>
{
    string __upper = (__name ?? "").ToUpperInvariant();
    // БЕЗ Regex, и это не вкусовщина. Замер 04.08 на живом устройстве:
    // голое `Regex` -> CS0103, полное имя -> CS1069 «type has been forwarded
    // to assembly 'System'».
    //
    // ПРИЧИНА ОДНА, А НЕ ДВЕ (первая редакция этого комментария была неверна
    // и списывала CS0103 на usings): обёртку излучаемого кода строит СЕРВЕР
    // (`bridge_protocol._WRAPPER_HEADER`), клиент своего списка не имеет
    // вовсе — `CodeCompiler` сам себя описывает как «receives pre-wrapped
    // code from server», и все шесть копий обёртки одинаковы и все включают
    // `System.Text.RegularExpressions`. Значит оба отказа — про ОТСУТСТВУЮЩУЮ
    // ССЫЛКУ: на .NET Framework 4.8 `Regex` живёт в `System.dll`, которой нет
    // в замыкании РАЗВЁРНУТОГО у пользователя плагина (в HEAD она есть —
    // расхождение между деревом и установленным бинарником, а не внутри
    // дерева). Там же `Stopwatch` и `Stack<T>` — итого 24 места, все найдены
    // одним проходом переписи после того, как три из них нашлись живьём.
    //
    // Разбор по индексам требует только String/Char: `Char.IsLetterOrDigit`
    // покрывает те же категории Unicode, что `[^\p{L}\p{Nd}]+` в обратную.
    // Сторож класса — `tests/bridge_reference_closure.py`, профиль `deployed`.
    var __tokens = new HashSet<string>();
    int __tokStart = -1;
    for (int __tokI = 0; __tokI <= __upper.Length; __tokI++)
    {
        bool __tokIn = __tokI < __upper.Length
            && Char.IsLetterOrDigit(__upper[__tokI]);
        if (__tokIn) { if (__tokStart < 0) __tokStart = __tokI; }
        else if (__tokStart >= 0)
        {
            __tokens.Add(__upper.Substring(__tokStart, __tokI - __tokStart));
            __tokStart = -1;
        }
    }
    if (__tokens.Contains("ОВ") || __tokens.Contains("HVAC") ||
        __tokens.Contains("MECH")) return "mechanical";
    if (__tokens.Contains("ВК") || __tokens.Contains("PLUMB"))
        return "plumbing";
    if (__tokens.Contains("ЭОМ") || __tokens.Contains("ЭЛ") ||
        __tokens.Contains("ELECT")) return "electrical";
    if (__tokens.Contains("КР") || __tokens.Contains("КЖ") ||
        __tokens.Contains("STRUCT")) return "structural";
    if (__tokens.Contains("АР") || __tokens.Contains("ARCH"))
        return "architectural";
    return "unknown";
};
// ── Рабочие наборы ──────────────────────────────────────────────────────
// ЗАМЕР 27.07 (тренировочная модель ЭОМ, SKLNK R2026): модель открыли с 17
// закрытыми наборами из 18, и `FilteredElementCollector` честно вернул то,
// что видел, — 11 элементов в 3D-видах вместо 2016. Извлечение при этом
// прошло бы БЕЗ ЕДИНОГО ПРИЗНАКА неполноты, и покрытие, посчитанное по
// такому L0, описывало бы диалог открытия файла, а не компилятор.
//
// Молчаливо-неполное чтение неотличимо от полного — ровно тот исход,
// который этот компилятор объявляет невыразимым на записи. Значит и на
// чтении состояние наборов обязано ехать в паспорт, а не подразумеваться.
//
// 🔴 И ОТКАЗ ЭТОГО ЧТЕНИЯ — ТОЖЕ ФАКТ О ЗАМЕРЕ, А НЕ О МОДЕЛИ (02.09.2026).
// Блок ниже стоял под пустым `catch`, а три ключа писались БЕЗУСЛОВНО. Значит
// упавший `FilteredWorksetCollector` отдавал `worksharing=true, worksets=[],
// worksets_closed=0` — побайтово тот же вердикт, что у честно прочитанной
// разделённой модели со ВСЕМИ открытыми наборами: `is_partial_read=False`
// при `partial_read_measured=True`. Хуже того, бросок самого `IsWorkshared`
// объявлял модель ОДНОПОЛЬЗОВАТЕЛЬСКОЙ.
//
// Лечится не новым полем, а МОЛЧАНИЕМ В ПРАВИЛЬНУЮ СТОРОНУ: у обоих ключей
// третье состояние уже есть и стоит в `L0Document` дословно — «ключа нет
// значит НЕ МЕРИЛИ» (`worksets_closed: int | None`, `worksharing: bool |
// None`). Отказ чтения обязан приезжать этим состоянием, а не нулём.
var __worksets = new List<object>();
bool __worksharing = false;
int __worksetsClosed = 0;
bool __wsThrew = false;
string __wsError = null;
try
{
    __worksharing = __src.IsWorkshared;
    if (__worksharing)
    {
        foreach (Workset __ws in new FilteredWorksetCollector(__src)
                 .OfKind(WorksetKind.UserWorkset))
        {
            var __wsRow = new Dictionary<string, object>();
            // Идентификатор берётся строкой: числовой аксессор ElementId
            // нестабилен между версиями Revit, и правило одно для ВСЕХ
            // идентификаторов — иначе пришлось бы помнить исключения.
            // Инвариант проверяет подстроку во всей эмиссии, поэтому её
            // нельзя даже упоминать в комментарии (проверено падением).
            __wsRow["id"] = __ws.Id.ToString();
            __wsRow["name"] = __ws.Name ?? "";
            __wsRow["open"] = __ws.IsOpen;
            if (!__ws.IsOpen) __worksetsClosed++;
            __worksets.Add(__wsRow);
        }
    }
}
catch (Exception __wsException)
{
    __wsThrew = true;
    string __wsMessage = __wsException.Message ?? "";
    if (__wsMessage.Length > 200) __wsMessage = __wsMessage.Substring(0, 200);
    __wsError = __wsException.GetType().Name + ": " + __wsMessage;
    // Частично собранный список — та же ложь под другим видом: он
    // выглядит перечислением, будучи обрывом. Свидетельствует КВИТАНЦИЯ.
    __worksets.Clear();
}
__result["worksets"] = __worksets;
if (!__wsThrew)
{
    __result["worksharing"] = __worksharing;
    __result["worksets_closed"] = __worksetsClosed;
}
else
{
    __result["worksets_read_failed"] = __wsError;
}

var __links = new List<object>();
foreach (RevitLinkInstance __link in new FilteredElementCollector(__src)
         .OfClass(typeof(RevitLinkInstance))
         .WhereElementIsNotElementType()
         .Cast<RevitLinkInstance>().OrderBy(__x => __x.Id.ToString()))
{
    var __linkRow = new Dictionary<string, object>();
    string __name = __link.Name ?? "";
    __linkRow["element_id"] = __link.Id.ToString();
    __linkRow["name"] = __name;
    __linkRow["loaded"] = false;
    __linkRow["element_count"] = null;
    __linkRow["bbox_min_mm"] = null;
    __linkRow["bbox_max_mm"] = null;
    __linkRow["discipline"] = __Discipline(__name);
    var __linkedDocument = __link.GetLinkDocument();
    if (__linkedDocument != null)
    {
        __linkRow["loaded"] = true;
        try
        {
            __linkRow["element_count"] =
                new FilteredElementCollector(__linkedDocument)
                .WhereElementIsNotElementType().GetElementCount();
        }
        catch { }
    }
    string __linkInstanceUniqueId = null;
    try
    {
        if (!String.IsNullOrWhiteSpace(__link.UniqueId))
            __linkInstanceUniqueId = __link.UniqueId;
    }
    catch { }
    var __linkedDocumentIdentity = (__linkedDocument == null
        ? null : __DocumentIdentityFact(__linkedDocument));
    var __linkIdentityGaps = new List<object>();
    if (__linkInstanceUniqueId == null)
        __linkIdentityGaps.Add("link_instance_unique_id_unavailable");
    if (__linkedDocument == null)
        __linkIdentityGaps.Add("linked_document_unavailable");
    else if (__linkedDocumentIdentity == null)
        __linkIdentityGaps.Add("linked_document_identity_unavailable");
    else if (!__DocumentIdentityAuthoritative(__linkedDocumentIdentity))
        __linkIdentityGaps.Add(
            "linked_document_identity_not_authoritative");
    bool __linkIdentityAuthoritative =
        __linkInstanceUniqueId != null &&
        __DocumentIdentityAuthoritative(__linkedDocumentIdentity) &&
        __linkIdentityGaps.Count == 0;
    __linkRow["identity"] = new Dictionary<string, object> {
        {"schema_version", "kir-l0-revit-identity/1"},
        {"instance_unique_id", __linkInstanceUniqueId},
        {"linked_document_identity", __linkedDocumentIdentity},
        {"status", __linkIdentityAuthoritative
            ? "authoritative" : "incomplete"},
        {"gaps", __linkIdentityGaps}
    };
    try
    {
        __linkRow["transform"] = __TransformEvidence(
            __link.GetTotalTransform(), "parent_source");
    }
    catch
    {
        __linkRow["transform"] = __TransformEvidence(
            null, "parent_source");
    }
    try
    {
        var __bbox = __link.get_BoundingBox(null);
        if (__bbox != null)
        {
            __linkRow["bbox_min_mm"] = __VecMM(__bbox.Min);
            __linkRow["bbox_max_mm"] = __VecMM(__bbox.Max);
        }
    }
    catch { }
    __links.Add(__linkRow);
}
__result["links"] = __links;

// ── Перепись документа (§18.1) ──────────────────────────────────────────
// Таблица категорий закрыта (47 штук), и всё, чего в ней нет — топография,
// площадка, паркинг, озеленение, массы, арматура, изоляция, — не давало НИ
// ЭЛЕМЕНТА, НИ СТРОКИ СТАТУСА, НИ ОТКАЗА. Знаменатель покрытия был выборкой
// таблицы, а не документом.
//
// Перепись — ОДИН проход, без геометрии и без параметров: только счётчик на
// категорию, поэтому дёшева даже на полумиллионе элементов и исполняется
// ВСЕГДА. Ключ — BuiltInCategory (§18.5: локализованное имя категории
// допустимо лишь как справочная колонка, ключом правила ему быть нельзя).
// Enum.GetName зовётся один раз на КАТЕГОРИЮ, а не на элемент.
//
// DirectShape/ImportInstance отражены здесь ровно так же, как их берут
// коллекторы таблицы (по классу, а не по категории) — иначе тождество
// «перепись = прочитано + не читалось» не сходилось бы по построению и
// показывало бы непрочитанным то, что прочитано.
var __censusCounts = new Dictionary<string, int>();
var __censusNames = new Dictionary<string, string>();
var __censusKeyByCatId = new Dictionary<string, string>();
long __censusTotal = 0;
bool __censusWanted = (__RoomAfter == -9223372036854775808L);
if (__censusWanted)
{
    foreach (Element __any in new FilteredElementCollector(__src)
             .WhereElementIsNotElementType())
    {
        __censusTotal++;
        string __key = "__CENSUS_NO_CATEGORY__";
        if (__any is DirectShape)
        {
            __key = "DirectShape";
        }
        else if (__any is ImportInstance)
        {
            __key = "ImportInstance";
        }
        else
        {
            // Отказ ОБРАЩЕНИЯ и отсутствие категории — разные факты, и до
            // 12.08.2026 `catch { }` сливал их в один ключ: отказ прибора
            // становился измерением о модели (форма 3 канона) на 17.35%
            // документа. Флаг ставится ТОЛЬКО в catch, поэтому на прогоне,
            // где ничего не бросает, эмиссия ведёт себя как прежде.
            Category __anyCat = null;
            bool __anyCatThrew = false;
            try { __anyCat = __any.Category; } catch { __anyCatThrew = true; }
            if (__anyCat == null && __anyCatThrew)
            {
                __key = "__CENSUS_CATEGORY_THREW__";
            }
            if (__anyCat != null)
            {
                string __catId = __anyCat.Id.ToString();
                if (!__censusKeyByCatId.TryGetValue(__catId, out __key))
                {
                    string __enumName = null;
                    long __catNumeric = 0;
                    if (Int64.TryParse(__catId, out __catNumeric))
                    {
                        try
                        {
                            __enumName = Enum.GetName(
                                typeof(BuiltInCategory),
                                (BuiltInCategory)__catNumeric);
                        }
                        catch { }
                    }
                    __key = String.IsNullOrEmpty(__enumName)
                        ? ("category_id:" + __catId) : __enumName;
                    __censusKeyByCatId[__catId] = __key;
                    string __localized = "";
                    try { __localized = __anyCat.Name ?? ""; } catch { }
                    if (!__censusNames.ContainsKey(__key))
                        __censusNames[__key] = __localized;
                }
            }
        }
        __censusCounts[__key] = __censusCounts.ContainsKey(__key)
            ? __censusCounts[__key] + 1 : 1;
    }
}
if (__censusWanted)
{
    var __census = new List<object>();
    foreach (var __censusPair in __censusCounts.OrderBy(__x => __x.Key))
        __census.Add(new Dictionary<string, object> {
            {"key", __censusPair.Key},
            {"name", __censusNames.ContainsKey(__censusPair.Key)
                ? __censusNames[__censusPair.Key] : ""},
            {"count", __censusPair.Value}
        });
    __result["census"] = __census;
    __result["census_total"] = __censusTotal;
}
else
{
    // Страница комнат №2+ переписи НЕ ПОВТОРЯЕТ: документ между страницами
    // неизменен (ревизия сторожится), и платить полным проходом за каждую
    // страницу значило бы делать закон дорогим ровно там, где модель велика.
    __result["census"] = null;
    __result["census_total"] = null;
}
return __result;
""".strip()


def _source_binding_cs(
    link_title: str | None,
    link_instance_unique_id: str | None = None,
) -> str:
    """Whose document we are reading: the host or its LINK.

    Linked documents are already open in the session (30.07 measurement on
    Snowdon: ``Application.Documents.Size == 5``), and ``GetLinkDocument()``
    hands back a ready-made ``Document``. So reading a link requires OPENING
    nothing: it's enough to build collectors against it instead of against
    the host. We still cannot open a link with a window either —
    ``UIApplication.OpenAndActivateDocument`` is forbidden from inside an
    event handler (documented by Autodesk, verified live: the call returned
    null without throwing an exception).

    Each link is captured by its OWN snapshot with its own stamp. This gives
    it a local stream, but NOT a global address space: the production header
    additionally carries the document's identity, the federation root's, and
    the UniqueId of the exact link instance. The numeric ElementId remains
    only a local address.

    A CAVEAT THAT CANNOT BE HIDDEN: the revision guard fingerprints the
    HOST's document. An edit inside a link does not change the host's
    revision, meaning that when reading a link, the guard will NOT CATCH a
    concurrent edit. As long as this is so, a link's snapshot is an honest
    read without protection against simultaneous editing, and that is
    exactly how it must be described.

    THE TEXT LIVES IN ONE PLACE (``side_contract.source_binding_cs``),
    because since 30.07 it is emitted not only by category pages but by
    EVERY side stage. A second copy would mean a second truth about which
    document is being read, and the law "one body — one document" is
    checked against the TEXT of the emission: copies would drift apart
    silently and leave the check green.
    """
    return source_binding_cs(link_title, link_instance_unique_id)


def _collector_cs(spec: CategorySpec, variable: str = "__query") -> str:
    code = (
        f"System.Collections.Generic.IEnumerable<Element> {variable} = "
        f"new FilteredElementCollector(__src){spec.collector_cs}"
        ".WhereElementIsNotElementType().Cast<Element>();"
    )
    if spec.exclude_direct_shape:
        code += (
            f"\n{variable} = {variable}.Where("
            "__e => !(__e is DirectShape));"
        )
    return code


def build_metadata_cs(*, after_room_id: int | None = None,
                      link_title: str | None = None,
                      link_instance_unique_id: str | None = None) -> str:
    """Return one version-safe document-metadata/room-boundary page.

    §18.1: the document census travels in this SAME body — as a separate
    round-trip it would cost an extra move for every model (latency here is
    measured in the number of rounds, not bytes), and its result is needed
    in exactly the same place as the rest of the header. It is computed only
    on the FIRST rooms page.
    """

    after = (
        "-9223372036854775808L"
        if after_room_id is None else f"{after_room_id}L")
    return (
        # Metadata and the CENSUS must be computed against the same document
        # as the elements: otherwise the census would measure the host,
        # while the elements would come from the link — and the census law
        # would catch this as a discrepancy without naming the cause.
        _source_binding_cs(link_title, link_instance_unique_id)
        + "\n" + _METADATA_CS
        .replace("__ROOM_AFTER__", after, 1)
        .replace("__ROOM_TAKE__", str(EXTRACT_BATCH + 1))
        .replace("__ROOM_BATCH__", str(EXTRACT_BATCH))
        .replace("__CENSUS_NO_CATEGORY__", NO_CATEGORY_KEY)
        .replace("__CENSUS_CATEGORY_THREW__", CATEGORY_READ_FAILED_KEY)
    )


def build_category_probe_cs(category: str, *,
                            link_title: str | None = None,
                            link_instance_unique_id: str | None = None) -> str:
    """Build the count/level-scope probe for one fixed category."""

    spec = _SPEC_BY_NAME.get(category)
    if spec is None:
        raise ValueError(f"unknown extraction category: {category!r}")
    return "\n".join((
        # 🔴 THE BINDING COMES FIRST, AND THIS IS NOT A STYLE CHOICE. The
        # helpers are lambdas capturing `__src`, and a C# local variable is
        # not visible above its declaration. While the binding stood AFTER
        # the helpers, they could not physically read the source — and read
        # the host instead. The same order is prescribed by the docstring of
        # `side_contract.source_binding_cs`; the `metadata` body already
        # holds to it.
        _source_binding_cs(link_title, link_instance_unique_id),
        _COMMON_HELPERS_CS,
        _collector_cs(spec),
        r"""
var __counts = new Dictionary<string, int>();
int __total = 0;
foreach (var __element in __query)
{
    __total++;
    string __key = __LevelKey(__element);
    __counts[__key] = __counts.ContainsKey(__key)
        ? __counts[__key] + 1 : 1;
}
var __scopes = new List<object>();
foreach (var __pair in __counts.OrderBy(__x => __x.Key))
    __scopes.Add(new Dictionary<string, object> {
        {"key", __pair.Key}, {"count", __pair.Value}
    });
return new Dictionary<string, object> {
    {"count", __total}, {"levels", __scopes}
};
""".strip(),
    ))


def _csharp_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class _HostReader:
    """One branch of host reading. The table is ONE mechanism, not a list of
    cases.

    ``id_expr`` — an expression from the variable ``__h`` (the element,
    already cast to ``cs_type``), yielding an ``ElementId``. Everything else
    is a frame shared by all branches and written ONCE in
    :func:`_host_readers_cs`: the cast, filtering out an invalid id, writing
    the ``host_id``/``host_source`` pair, swallowing the exception. Adding a
    class means adding a LINE, not a branch.

    The class name is written IN FULL. The extraction body is wrapped by
    different wrappers (the gate's `wrap_user_code`, the live-run bridge's
    wrapper), and relying on each of them declaring `using
    Autodesk.Revit.DB.Architecture` would put the compilation at the mercy
    of a file this generator cannot see.
    """

    source: HostSource
    cs_type: str
    id_expr: str


# A MEASUREMENT, NOT MEMORY (09.08, compilation against :52412 real
# assemblies 2021-2026 — the arbiter here is the compiler, not
# RevitAPI.xml). Candidates were obtained by a census of all six
# RevitAPI.xml files for members with "Host" in the name; below are those
# whose class does NOT inherit `FamilyInstance` (meaning the old branch
# never saw them) and whose category is in `EXTRACT_CATEGORIES`:
#
#   WallFoundation.WallId                → 6/6   OST_StructuralFoundation
#   Railing.HostId (+ HasHost)           → 6/6   OST_StairsRailing
#   Opening.Host                         → 6/6   OST_SWallRectOpening,
#                                                OST_FloorOpening,
#                                                OST_RoofOpening,
#                                                OST_ShaftOpening
#   InsulationLiningBase.HostElementId   → 6/6   OST_PipeInsulations,
#                                                OST_DuctInsulations,
#                                                OST_DuctLinings
#     (PipeInsulation/DuctInsulation/DuctLining inherit this base class —
#      verified by compilation 6/6, so ONE line covers three categories)
#
# WHAT IS MEASURED AND DELIBERATELY NOT TAKEN:
#   * `Panel` and `Mullion` inherit `FamilyInstance` 6/6 — curtain walls were
#     read correctly even before the wave (in the corpus,
#     OST_CurtainWallMullions: 119 573 elements, 0 empty host_id). A
#     separate branch would be dead code.
#   * `Stairs.MultistoryStairsId` 6/6 — but this is an OWNER assembly, not a
#     host: a stair does not "hang on" a multistory stair, it BELONGS to it.
#     Putting this into `host_id` would mean housing two different
#     relations in one field — exactly what the field was cured of. A
#     separate field is a separate wave.
#   * `Wall`, in the role of a curtain-panel host, HAS NO SUCH THING AT ALL:
#     `__w.Host` gives CS1061 on all six versions. This is a MEASURED
#     ABSENCE, not a gap in our reading, and it explains 14 251 panels with
#     an empty host_id in the corpus.
#   * `WallSweep.GetHostIds`, `Rebar/AreaReinforcement/PathReinforcement`,
#     `LoadBase`, `BuildingPad`, `FabricArea/FabricSheet`, `Toposolid` (3/6,
#     2024+) have a readable host, but their categories are not in
#     `EXTRACT_CATEGORIES` — that is a READING gap, not a gap in this table.
_HOST_READERS: tuple[_HostReader, ...] = (
    # FamilyInstance stands FIRST and on the same footing as the rest.
    # Before the wave it was the only one and therefore implicit; the line
    # in the table makes its source NAMED — otherwise `host_source` on a
    # door would mean "not measured."
    _HostReader(
        HostSource.FAMILY_INSTANCE, "Autodesk.Revit.DB.FamilyInstance",
        "__h.Host == null ? ElementId.InvalidElementId : __h.Host.Id"),
    _HostReader(
        HostSource.WALL_FOUNDATION, "Autodesk.Revit.DB.WallFoundation",
        "__h.WallId"),
    # `HasHost` is asked BEFORE `HostId` not for elegance: for a
    # freestanding railing, `HostId` returns InvalidElementId, and without
    # the filter below the field would get the string "-1" — a FALSE host,
    # which is worse than an empty field.
    _HostReader(
        HostSource.RAILING, "Autodesk.Revit.DB.Architecture.Railing",
        "__h.HasHost ? __h.HostId : ElementId.InvalidElementId"),
    _HostReader(
        HostSource.OPENING, "Autodesk.Revit.DB.Opening",
        "__h.Host == null ? ElementId.InvalidElementId : __h.Host.Id"),
    _HostReader(
        HostSource.INSULATION_LINING,
        "Autodesk.Revit.DB.InsulationLiningBase", "__h.HostElementId"),
)


def _indent(block: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(
        pad + line if line.strip() else line for line in block.split("\n"))


def _host_readers_cs() -> str:
    """Assemble the host-reading block — shared by ALL 77 categories.

    The block deliberately doesn't depend on the category, and the gate
    holds that same condition: it compiles the extraction on three
    categories on the grounds that only the COLLECTOR depends on the
    category. A reader keyed to categories would take the remaining 74 out
    from under the gate.
    """

    lines = ['__row["host_id"] = null;', '__row["host_source"] = null;']
    for reader in _HOST_READERS:
        lines.append(f"""if (__row["host_id"] == null)
{{
    try
    {{
        var __h = __element as {reader.cs_type};
        if (__h != null)
        {{
            var __hid = {reader.id_expr};
            if (__hid != null && __hid != ElementId.InvalidElementId)
            {{
                __row["host_id"] = __hid.ToString();
                __row["host_source"] = {_csharp_string(reader.source.value)};
            }}
        }}
    }}
    catch {{ }}
}}""")
    return "\n".join(lines)


def _placeholder_reader_cs() -> str:
    """The kind of an MEP segment — a placeholder or a real segment.

    THE BLOCK DOES NOT DEPEND ON THE CATEGORY, the same condition
    :func:`_host_readers_cs` holds: the gate compiles the extraction on
    THREE of 77 categories on the grounds that only the collector depends on
    the category. A reader keyed to categories would take the remaining 74
    out from under the gate. Hence a type cast here, not a branch by name.

    🔴 THE KEY IS WRITTEN ONLY WHEN IT WAS READ, and this is a load-bearing
    property, not tidiness. The field has three states
    (`L0Element.is_placeholder`), and the third — "not measured" — is
    expressed by the ABSENCE of the key. Writing `false` on a read failure
    would mean declaring a placeholder a real segment, by exactly the
    mechanism the block was set up to fix.

    A failure arrives as a RECEIPT, not an empty `catch { }`. An empty
    swallower here would stand in the same file as an already-named defect
    of the same kind (`_host_readers_cs`, F-038): a thrown accessor would
    give a line byte-identical to an honest "not a placeholder."

    Names are checked AGAINST THE TRAP INDEX (`api_trap_index`), not from
    memory: both live in ALL six versions, both have ZERO documented traps,
    both are in `RevitAPI` — the assembly the capture already references::

        P:Autodesk.Revit.DB.Plumbing.Pipe.IsPlaceholder     2021-2026, traps 0
        P:Autodesk.Revit.DB.Mechanical.Duct.IsPlaceholder   2021-2026, traps 0

    The same query also shows a namesake unrelated to segments and
    indistinguishably similar:
    ``P:Autodesk.Revit.DB.ViewSheet.IsPlaceholder``.
    """

    return """try
{
    var __phPipe = __element as Autodesk.Revit.DB.Plumbing.Pipe;
    if (__phPipe != null)
    {
        __row["is_placeholder"] = __phPipe.IsPlaceholder;
    }
    else
    {
        var __phDuct = __element as Autodesk.Revit.DB.Mechanical.Duct;
        if (__phDuct != null)
        {
            __row["is_placeholder"] = __phDuct.IsPlaceholder;
        }
    }
}
catch (Exception __phException)
{
    __row["is_placeholder_read_failed"] = __phException.GetType().Name;
}"""


def _flex_path_reader_cs() -> str:
    """A flex segment's path is a PRIMARY quantity, not a pair of endpoints.

    The block doesn't depend on the category by the same law as
    :func:`_placeholder_reader_cs` and :func:`_host_readers_cs`.

    🔴 `Points` IS READ, NOT `LocationCurve`, AND THIS IS NOT A CONVENIENCE
    CHOICE. For a flex element, `Location` gives a Hermite spline whose
    endpoints are COMPUTED from the points; the forward op directly requires
    checking all the points and their count, because "checking the
    endpoints would miss a discarded middle, i.e. a different route under a
    green verdict" (`ops_mep`). A pair of endpoints doesn't define a route:
    any polyline with the same endpoints would give the same line.

    Names are checked AGAINST THE TRAP INDEX, not from memory::

        P:Autodesk.Revit.DB.Mechanical.FlexDuct.Points   2021-2026, traps 0
        P:Autodesk.Revit.DB.Plumbing.FlexPipe.Points     2021-2026, traps 0

    Both are in `RevitAPI` — the assembly the capture already references.

    The key is written ONLY when it was read; a failure arrives as a
    receipt, not an empty `catch { }`. The point count is NOT TRUNCATED
    HERE: the language's limit (2..64) is a property of the OP, and it is
    the lifter's duty to decide it, since it knows how to refuse with a
    named cause. Truncating the route in the capture would mean inventing
    different geometry and presenting it as coverage.
    """

    return """try
{
    IList<XYZ> __fxPoints = null;
    var __fxDuct = __element as Autodesk.Revit.DB.Mechanical.FlexDuct;
    if (__fxDuct != null)
    {
        __fxPoints = __fxDuct.Points;
    }
    else
    {
        var __fxPipe = __element as Autodesk.Revit.DB.Plumbing.FlexPipe;
        if (__fxPipe != null)
        {
            __fxPoints = __fxPipe.Points;
        }
    }
    if (__fxPoints != null)
    {
        var __fxRow = new List<object>();
        foreach (XYZ __fxPt in __fxPoints)
        {
            __fxRow.Add(__VecMM(__fxPt));
        }
        __row["flex_path_mm"] = __fxRow;
    }
}
catch (Exception __fxException)
{
    __row["flex_path_read_failed"] = __fxException.GetType().Name;
}"""


def _opening_boundary_reader_cs() -> str:
    """An opening's boundary — a rectangle or a profile, and ONLY if it is a
    polyline.

    The block doesn't depend on the category by the same law as the two
    readers above. The opening's host (`Opening.Host`) has already been read
    by the host block since 09.08 — here, exactly what was missing gets read
    in addition: the boundary itself.

    🔴 AN ARC IS NOT APPROXIMATED BY A POLYLINE, IT IS REFUSED. The `outline`
    of the forward op is a polyline, and a round opening for a riser or a
    rounded cutout in a slab cannot be expressed by it: the result would be
    a DIFFERENT shape, not an approximation (the forward op says so
    literally). So on the very first non-`Line` curve, the boundary key is
    NOT WRITTEN AT ALL, and `opening_is_rect` stays `false` — the pair "there
    is an answer about rectangularity, there is no boundary" IS exactly the
    state by which the lifter refuses by name. A partially assembled contour
    would be a lie disguised as an enumeration.

    Names are checked AGAINST THE TRAP INDEX: `IsRectBoundary`,
    `BoundaryRect`, and `BoundaryCurves` live in ALL six versions, 0 traps,
    assembly `RevitAPI`. `Opening.SketchId` lives only 2022-2026 — a seam,
    and is therefore not read here at all.
    """

    return """try
{
    var __opEl = __element as Autodesk.Revit.DB.Opening;
    if (__opEl != null)
    {
        bool __opRect = __opEl.IsRectBoundary;
        __row["opening_is_rect"] = __opRect;
        var __opPts = new List<object>();
        bool __opExpressible = true;
        if (__opRect)
        {
            foreach (XYZ __opCorner in __opEl.BoundaryRect)
            {
                __opPts.Add(__VecMM(__opCorner));
            }
        }
        else
        {
            foreach (Curve __opCurve in __opEl.BoundaryCurves)
            {
                if (!(__opCurve is Line))
                {
                    __opExpressible = false;
                    break;
                }
                __opPts.Add(__VecMM(__opCurve.GetEndPoint(0)));
            }
        }
        if (__opExpressible && __opPts.Count > 0)
        {
            __row["opening_boundary_mm"] = __opPts;
        }
    }
}
catch (Exception __opException)
{
    __row["opening_boundary_read_failed"] = __opException.GetType().Name;
}"""


def _load_reader_cs() -> str:
    """A line load: endpoints, case, vector — and TWO markers of a BOUNDARY.

    The block doesn't depend on the category by the same law as the three
    readers above.

    🔴 `IsUniform` AND `IsProjected` ARE READ NOT FOR THE DATA, BUT FOR THE
    REFUSAL. The op holds ONE single triple vector, while a non-uniform load
    carries two different ones at its ends (`ForceVector1` !=
    `ForceVector2`): taking the first would mean passing off a DIFFERENT
    load as this one. A projected load is set against the length's
    projection, and the op has no such input at all. The lifter must refuse
    both cases BY NAME, and for that the markers must reach it in the line.

    Names are checked against the trap index, versions printed IN FULL::

        LineLoad.StartPoint / EndPoint      2021-2026, traps 0
        LineLoad.ForceVector1 / Vector2     2021-2026, 2 traps each — BOTH "on write"
        LineLoad.IsUniform / IsProjected    2021-2026, traps 0
        LoadBase.LoadCaseId                 2021-2026, 2 traps — BOTH "when setting"

    That is, READING is safe for all of them: not one documented trap
    pertains to reading. A refusal still arrives as a receipt, not an empty
    `catch { }`: an undocumented exception remains possible.
    """

    return """try
{
    var __ldBase = __element as Autodesk.Revit.DB.Structure.LoadBase;
    if (__ldBase != null)
    {
        // ОБЩЕЕ ДЛЯ ВСЕХ РОДОВ НАГРУЗКИ — читается ОДИН раз, у LoadBase.
        // Три этих свойства меняют СМЫСЛ при тех же числах, и потому они
        // здесь, а не в ветке рода: забыть их в одной ветке из трёх значило
        // бы завести тот же тихий дефект заново.
        __row["load_hosted"] = __ldBase.IsHosted;
        __row["load_reaction"] = __ldBase.IsReaction;
        __row["load_orient_to"] = __ldBase.OrientTo.ToString();
        ElementId __ldCase = __ldBase.LoadCaseId;
        if (__ldCase != null && __ldCase != ElementId.InvalidElementId)
        {
            __row["load_case_id"] = __ldCase.ToString();
        }
        if (__ldBase.LoadCaseName != null)
        {
            __row["load_case_name"] = __ldBase.LoadCaseName;
        }
    }
    var __plEl = __element as Autodesk.Revit.DB.Structure.PointLoad;
    if (__plEl != null)
    {
        __row["load_p0_mm"] = __VecMM(__plEl.Point);
        XYZ __plF = __plEl.ForceVector;
        __row["load_force_n"] = new double[] {
            UnitUtils.ConvertFromInternalUnits(__plF.X, UnitTypeId.Newtons),
            UnitUtils.ConvertFromInternalUnits(__plF.Y, UnitTypeId.Newtons),
            UnitUtils.ConvertFromInternalUnits(__plF.Z, UnitTypeId.Newtons)
        };
        XYZ __plM = __plEl.MomentVector;
        __row["load_moment_nm"] = new double[] {
            UnitUtils.ConvertFromInternalUnits(__plM.X, UnitTypeId.NewtonMeters),
            UnitUtils.ConvertFromInternalUnits(__plM.Y, UnitTypeId.NewtonMeters),
            UnitUtils.ConvertFromInternalUnits(__plM.Z, UnitTypeId.NewtonMeters)
        };
    }
    var __alEl = __element as Autodesk.Revit.DB.Structure.AreaLoad;
    if (__alEl != null)
    {
        __row["load_ref_points"] = __alEl.NumRefPoints;
        __row["load_projected"] = __alEl.IsProjected;
        XYZ __alF = __alEl.ForceVector1;
        __row["load_force_n_per_m2"] = new double[] {
            UnitUtils.ConvertFromInternalUnits(__alF.X, UnitTypeId.NewtonsPerSquareMeter),
            UnitUtils.ConvertFromInternalUnits(__alF.Y, UnitTypeId.NewtonsPerSquareMeter),
            UnitUtils.ConvertFromInternalUnits(__alF.Z, UnitTypeId.NewtonsPerSquareMeter)
        };
        // КОЛЬЦА ЦЕЛИКОМ, А НЕ ПЕРВОЕ: их ЧИСЛО — граница, оп выражает одно.
        // И только ЛОМАНЫЕ: дуга под `outline` стала бы хордой, то есть
        // другой площадью. Первая же не-Line обнуляет весь список, а не
        // урезает его — частичный контур это ложь под видом перечисления.
        var __alLoops = new List<object>();
        bool __alPoly = true;
        foreach (CurveLoop __alLoop in __alEl.GetLoops())
        {
            var __alPts = new List<object>();
            foreach (Curve __alC in __alLoop)
            {
                if (!(__alC is Line)) { __alPoly = false; break; }
                __alPts.Add(__VecMM(__alC.GetEndPoint(0)));
            }
            if (!__alPoly) break;
            if (__alPts.Count > 0) __alLoops.Add(__alPts);
        }
        if (__alPoly && __alLoops.Count > 0)
        {
            __row["load_area_loops_mm"] = __alLoops;
        }
    }
    var __llEl = __element as Autodesk.Revit.DB.Structure.LineLoad;
    if (__llEl != null)
    {
        __row["load_p0_mm"] = __VecMM(__llEl.StartPoint);
        __row["load_p1_mm"] = __VecMM(__llEl.EndPoint);
        __row["load_uniform"] = __llEl.IsUniform;
        __row["load_projected"] = __llEl.IsProjected;
        XYZ __llForce = __llEl.ForceVector1;
        __row["load_force_n_per_m"] = new double[] {
            UnitUtils.ConvertFromInternalUnits(__llForce.X, UnitTypeId.NewtonsPerMeter),
            UnitUtils.ConvertFromInternalUnits(__llForce.Y, UnitTypeId.NewtonsPerMeter),
            UnitUtils.ConvertFromInternalUnits(__llForce.Z, UnitTypeId.NewtonsPerMeter)
        };
    }
}
catch (Exception __ldException)
{
    __row["load_read_failed"] = __ldException.GetType().Name;
}"""


def _route_cs(category: str | None) -> str:
    """Probe routing by DATA, not by rewriting the generated C#.

    🔴 WHY NOT TEXTUAL SURGERY ON THE BODY. The canon carries a named
    precedent: `_wrap_create_per_op` chose the refusal form by SUBSTITUTING
    lines in already-generated C#, and one operation rolled back its
    neighbors. Since then, generated C# rewrites nothing. The same rule
    applies here: the list of cut-off names travels as a `HashSet`, and the
    decision is made in a helper keyed by parameter name — by DATA that the
    artifact's reader can also see.

    An empty route yields an empty set and a branch that is never taken:
    disabled routing must be identical to prior behavior.
    """
    from kir.decompile.param_route import AUDIT_EVERY, route_skip

    # `None` — the route is DISABLED (the measurement arm). An empty set
    # gives a branch that is never taken, i.e. byte-for-byte prior behavior.
    names = [] if category is None else sorted(route_skip(category))
    literals = ", ".join(_csharp_string(name) for name in names)
    return """
// МАРШРУТ ЗОНДОВ: имена, которые этой категории не задают. Провенанс таблицы
// и предикат отбора — в `kir/decompile/param_route.py`.
var __routeSkip = new HashSet<string>(new string[] {{ {literals} }});
int __routeEvery = {every};
int __routeSeen = 0;
bool __auditNow = false;
// имя -> [обойдено, проверено выборочно]
var __routeRows = new Dictionary<string, int[]>();
Action<string, bool> __BumpRoute = (__name, __audited) =>
{{
    int[] __row;
    if (!__routeRows.TryGetValue(__name, out __row))
    {{
        __row = new int[2];
        __routeRows[__name] = __row;
    }}
    if (__audited) __row[1] = __row[1] + 1; else __row[0] = __row[0] + 1;
}};
// Возвращает true, когда зонд задавать НЕ надо. Выборочный элемент проходит
// полный список — это и есть страховка: таблица, разошедшаяся с моделью,
// оставит след в квитанции, а не будет обойдена молча.
Func<string, bool> __RouteSkips = (__name) =>
{{
    if (!__routeSkip.Contains(__name)) return false;
    __BumpRoute(__name, __auditNow);
    return !__auditNow;
}};
""".format(literals=literals, every=AUDIT_EVERY).strip()



#: How the arms of the live measurement on 20.08.2026 were named — the same letters appear in the reports.
PROBE_AB_ARMS = ("A", "R", "B")


def build_probe_ab_arms(category: str) -> dict[str, str]:
    """Three arms for measuring the probing cost. Assembled by the PROD FUNCTION.

        A  route DISABLED — as it was before routing
        R  route enabled — as in prod now
        B  NO probes AT ALL — the control arm

    🔴 WHY A FUNCTION, NOT A RECIPE OF THREE `str.replace`. The first
    edition of the recipe assembled the arms by substituting text in
    already-generated C#, and that is the same technique rejected for the
    route itself: substitution rests on the shape of the line and silently
    stops working when the shape shifts.

    🔴 AND THE MAIN REQUIREMENT — NOT ON THE BUILD, BUT ON THE RUN, bought on
    20.08: ALL THREE ARMS ARE TAKEN IN ONE PASS. A measurement where one arm
    is taken in a different pass is a measurement of the difference between
    passes, halved with the difference between arms. On that day this gave
    30% against the real 22 — a pleasant untruth that would have made it
    into the report.

    The evidence is free and lies right next to it: **arm B contains no
    probes, and the route cannot touch it — so it is REQUIRED to stay put**.
    If it moved between passes, the baseline has drifted and nothing else
    can be counted. That is why B is built with the route DISABLED: one
    canonical control arm, not two nearly-identical ones.
    """
    a = build_category_batch_cs(category, route=False)
    r = build_category_batch_cs(category, route=True)
    call = "__PutParams(__element, __row);"
    if a.count(call) != 1:
        raise ExtractionProtocolError(
            "рука B не собирается: вызов __PutParams встречается %d раз, "
            "а подмена рассчитана ровно на один" % a.count(call))
    return {"A": a, "R": r, "B": a.replace(call, "", 1)}


def build_category_batch_cs(
    category: str,
    *,
    level_scope: str = "__all__",
    after_element_id: int | None = None,
    link_title: str | None = None,
    link_instance_unique_id: str | None = None,
    route: bool = True,
) -> str:
    """Build one deterministic page (at most ``EXTRACT_BATCH`` rows).

    ``route=False`` disables probe routing and exists PURELY FOR
    MEASUREMENT (`build_probe_ab_arms`): the "as it was before routing" arm
    must be assemblable by the PROD FUNCTION, otherwise it gets assembled by
    substituting text in already-generated C# — exactly the practice this
    same file rejects for the route itself.

    In prod the key is never passed; that the prod path never touches it is
    held by a test, not by a gentlemen's agreement.
    """

    spec = _SPEC_BY_NAME.get(category)
    if spec is None:
        raise ValueError(f"unknown extraction category: {category!r}")
    after = (
        "-9223372036854775808L"
        if after_element_id is None else f"{after_element_id}L")
    category_literal = _csharp_string(category)
    scope_literal = _csharp_string(level_scope)
    body = f"""
string __Category = {category_literal};
string __Scope = {scope_literal};
long __After = {after};
var __page = __query
    .Where(__e => __Id(__e) > __After &&
        (__Scope == "__all__" || __LevelKey(__e) == __Scope))
    .OrderBy(__e => __Id(__e))
    .Take({EXTRACT_BATCH + 1})
    .ToList();
bool __hasMore = __page.Count > {EXTRACT_BATCH};
if (__hasMore) __page.RemoveRange({EXTRACT_BATCH},
                                  __page.Count - {EXTRACT_BATCH});
var __rows = new List<object>();
foreach (var __element in __page)
{{
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __element.Id.ToString();
    __row["unique_id"] = null;
    try
    {{
        if (!String.IsNullOrWhiteSpace(__element.UniqueId))
            __row["unique_id"] = __element.UniqueId;
    }}
    catch {{ }}
    __row["category"] = __Category;
    __row["category_ru"] = "";
    try
    {{
        if (__element.Category != null && __element.Category.Name != null)
            __row["category_ru"] = __element.Category.Name;
    }}
    catch {{ }}
    __row["type_id"] = "";
    __row["type_name"] = "";
    try
    {{
        var __typeId = __element.GetTypeId();
        if (__typeId != null && __typeId != ElementId.InvalidElementId)
        {{
            __row["type_id"] = __typeId.ToString();
            var __type = __src.GetElement(__typeId);
            if (__type != null && __type.Name != null)
                __row["type_name"] = __type.Name;
        }}
    }}
    catch {{ }}
    __row["level_id"] = null;
    __row["level_name"] = null;
    var __level = __ElementLevel(__element);
    if (__level != null)
    {{
        __row["level_id"] = __level.Id.ToString();
        __row["level_name"] = __level.Name ?? "";
    }}
{_indent(_host_readers_cs(), 4)}
{_indent(_placeholder_reader_cs(), 4)}
{_indent(_flex_path_reader_cs(), 4)}
{_indent(_opening_boundary_reader_cs(), 4)}
{_indent(_load_reader_cs(), 4)}
    __PutParams(__element, __row);
    __PutGroupingState(__element, __row);
    __PutGeometry(__element, __row);
    __rows.Add(__row);
}}
object __next = null;
if (__hasMore && __page.Count > 0)
    __next = __page[__page.Count - 1].Id.ToString();
// Квитанции сечений (ревью кодекса №12). Порядок ЗАДАН сортировкой, а не
// порядком словаря: два прогона обязаны давать один отчёт.
var __receipts = new List<object>();
foreach (var __kv in __sectionReceipts.OrderBy(__x => __x.Key))
    __receipts.Add(new Dictionary<string, object> {{
        {{"parameter", __kv.Key}},
        {{"instance_hit", __kv.Value[0]}},
        {{"type_hit", __kv.Value[1]}},
        {{"not_applicable", __kv.Value[2]}},
        {{"no_value", __kv.Value[3]}},
        {{"wrong_storage", __kv.Value[4]}},
        {{"exception", __kv.Value[5]}}
    }});
// Строки МАРШРУТА рядом с квитанциями. Порядок задан сортировкой: два
// прогона обязаны давать один отчёт.
var __routeOut = new List<object>();
foreach (var __kv in __routeRows.OrderBy(__x => __x.Key))
    __routeOut.Add(new Dictionary<string, object> {{
        {{"parameter", __kv.Key}},
        {{"skipped", __kv.Value[0]}},
        {{"audited", __kv.Value[1]}}
    }});
return new Dictionary<string, object> {{
    {{"elements", __rows}},
    {{"has_more", __hasMore}},
    {{"next_cursor", __next}},
    {{"section_receipts", __receipts}},
    {{"route_skipped", __routeOut}}
}};
""".strip()
    return "\n".join((
        # 🔴 BINDING FIRST, AND THIS IS NOT STYLE. The helpers are lambdas
        # capturing `__src`, and a local C# variable is not visible above its
        # declaration. While the binding stood AFTER the helpers, they could
        # not physically read the source — and read the host instead. The
        # same order is mandated by the `side_contract.source_binding_cs`
        # docstring; the `metadata` body already honors it.
        _source_binding_cs(link_title, link_instance_unique_id),
        _COMMON_HELPERS_CS,
        # The route is declared BEFORE the helpers: they read it, and C#
        # requires declaration before use within the same body.
        _route_cs(category if route else None),
        _ELEMENT_HELPERS_CS,
        GEOMETRY_HELPER_CS,
        _collector_cs(spec),
        body,
    ))


@dataclass(frozen=True, slots=True)
class _Scope:
    key: str
    count: int


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    output_path: Path
    checkpoint_path: Path
    element_count: int
    completed_categories: tuple[str, ...]
    partial_categories: tuple[str, ...]
    resumed: bool
    #: TIME breakdown by category, keyed by category name (see
    #: :func:`_timing_totals` for what is split here and what is not).
    #: An empty dict for a resume of a completed stream: nothing was read
    #: there.
    timing: Mapping[str, Mapping[str, float]] = field(default_factory=dict)


#: MEASUREMENT BOUNDARY, STATED IN WORDS.
#:
#: ``bridge_ms`` is one indivisible segment from this point on. Inside it,
#: in order: sending to the websocket, waiting for Revit's UI thread, C#
#: body compilation by Roslyn, work of the Revit API collector,
#: serialization of the response to JSON on the plugin side, the return
#: transport, and ``json.loads`` in our process.
#: THESE CANNOT BE SPLIT FROM PYTHON: the plugin does not return its own
#: timing (Stopwatch exists only in ContextCollector and IFCExporter — those
#: are different paths, not the decompile path). Whoever wants to split it
#: must add instrumentation INSIDE THE PLUGIN, and that is a separate wave.
#:
#: What IS measured separately and honestly:
#:   ``probe_ms``  — the cheap probe call (count + max id) of the same
#:                   category. It carries the same fixed call cost
#:                   (transport + Roslyn + hitting the UI thread), but
#:                   almost no collection or serialization. So
#:                   ``probe_ms/call`` is an UPPER BOUND on the fixed cost
#:                   of one bridge round trip, and ``bridge_ms/pages`` minus
#:                   it is a lower bound on Revit's useful work. An upper
#:                   bound, not an exact one: the probe also runs the
#:                   collector.
#:   ``parse_ms``  — OUR parsing of the page into types (``_parse_page``).
#:   ``write_ms``  — OUR write of rows to L0.jsonl together with ``fsync``.
#:   ``bytes``     — how much L0 grew on this category (a proxy for response
#:                   size: we've already parsed the response, and
#:                   re-serializing it just to size it costs more than the
#:                   measurement itself).
_TIMING_KEYS = ("probe_ms", "bridge_ms", "parse_ms", "write_ms")


def _new_timing_slot() -> dict[str, float]:
    return {"probe_ms": 0.0, "bridge_ms": 0.0, "parse_ms": 0.0,
            "write_ms": 0.0, "pages": 0.0, "bytes": 0.0, "elements": 0.0}


def _timing_totals(
    timing: Mapping[str, Mapping[str, float]],
) -> dict[str, float]:
    """Collapse the per-category breakdown into the run's totals.

    ``bridge_ms`` is NOT split further — see ``_TIMING_KEYS`` above.
    ``our_ms`` (parse+write) and ``bridge_ms`` are exactly the boundary that
    answers the question "do our optimizations even matter": if
    ``bridge_ms`` dominates, the only fix is reading LESS, not a faster
    Python.
    """

    out: dict[str, float] = {key: 0.0 for key in _TIMING_KEYS}
    out.update({"pages": 0.0, "bytes": 0.0, "elements": 0.0})
    for slot in timing.values():
        for key in out:
            out[key] += float(slot.get(key) or 0.0)
    out["our_ms"] = out["parse_ms"] + out["write_ms"]
    out["bridge_ms_share"] = (
        round(out["bridge_ms"] / (out["bridge_ms"] + out["our_ms"]), 4)
        if (out["bridge_ms"] + out["our_ms"]) > 0 else 0.0)
    return {key: round(value, 3) for key, value in out.items()}


@dataclass(frozen=True, slots=True)
class ExtractProgress:
    """One report on a completed category — exactly what has already landed
    on disk.

    Measurement of 30.07 on a live tower: extraction ran for 41 minutes, L0
    grew to 88 MB and closed with a footer, while whoever asked "how's the
    run going" got ``stage=open_model_profile, done 0/0`` the whole time.
    There was no way to tell "running normally" from "hung on the first
    page" other than the file size.

    The report is emitted AFTER the checkpoint is written, not before: it
    must describe a state that will already survive a process crash. A
    report about what is merely about to be done is a promise, not
    progress.
    """

    category: str
    #: The value of :class:`~kir.decompile.schema.CategoryState` as a
    #: string. The category's verdict is part of the progress: a PARTIAL
    #: learned about only at the end devalues the whole report.
    category_state: str
    categories_done: int
    categories_total: int
    #: Elements already committed to the stream (not "expected" but
    #: "on disk").
    elements: int


def _require_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ExtractionProtocolError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ExtractionProtocolError(f"{field_name} keys must be strings")
    return dict(value)


def _require_list(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExtractionProtocolError(f"{field_name} must be an array")
    return value


def _require_int(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ExtractionProtocolError(
            f"{field_name} must be an integer >= {minimum}")
    return value


#: A group of envelope codes (``kukai.llm.envelope.ErrCode``) meaning that
#: OUR text did not become a build. Checked by PREFIX: the group is closed
#: and growing (``compile.cs_error``, ``compile.failed_after_repairs``), and
#: enumerating its members here would mean keeping a second dictionary of
#: the same concept.
_TEMPLATE_COMPILE_ERR_PREFIX = "compile."


def _envelope_failure_detail(row: Mapping[str, Any]) -> str:
    """The human-readable refusal reason from the envelope — NEVER a bare
    ``True``.

    The order is not accidental. ``error`` in the envelope can be either a
    string or a BOOLEAN flag; ``str(True)`` is not a reason but the loss of
    one, and that is exactly what the operator saw instead of
    ``CS1503 ... (line 103)``. The string is taken from wherever it exists,
    and the flag is never passed off as text.
    """
    for key in ("message", "error"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    err = row.get("err")
    if isinstance(err, Mapping):
        code = err.get("code")
        if isinstance(code, str) and code:
            return code
    return "bridge refused"


def _raise_envelope_failure(row: Mapping[str, Any]) -> None:
    """Envelope refusal — typed by ITS OWN code, not by guesswork."""
    detail = _envelope_failure_detail(row)[:240]
    err = row.get("err")
    code = err.get("code") if isinstance(err, Mapping) else None
    if isinstance(code, str) and code.startswith(_TEMPLATE_COMPILE_ERR_PREFIX):
        raise TemplateCompileError(detail)
    raise ExtractionProtocolError(detail)


def _unwrap_bridge_payload(value: Any) -> Any:
    """Unwrap the serving pipeline envelope without guessing at plain rows."""

    current = value
    for _ in range(2):
        if not isinstance(current, Mapping) or "ok" not in current:
            break
        if current.get("ok") is not True:
            _raise_envelope_failure(current)
        if "result" not in current:
            break
        current = current["result"]
    if (isinstance(current, Mapping)
            and current.get("error") not in (None, False)):
        _raise_envelope_failure(current)
    return current


#: Pauses between page retry attempts. An instant retry (sleep(0)) hit a
#: still-DEAD socket: a network break kills the bridge with code 1006, the
#: window comes back with a new ws_id after seconds — the retry needs to
#: WAIT for the reconnect, not burn its budget in milliseconds (measured
#: 29.07, К2 РД: three runs). Reads are idempotent, each page is under a
#: revision guard — waiting is safe by construction.
EXTRACT_RETRY_BACKOFF_S: tuple[float, ...] = (5.0, 20.0)


async def _execute_with_retries(
    executor: BridgeExecutor,
    code: str,
    *,
    timeout_ms: int,
    retries: int,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            call = executor(code, timeout_ms=timeout_ms)
            raw = await asyncio.wait_for(
                call, timeout=max(timeout_ms / 1000.0, 0.001))
            return _unwrap_bridge_payload(raw)
        except asyncio.CancelledError:
            raise
        except DocumentRevisionError:
            # A retry would merely choose another revision and make a mixed
            # snapshot look successful.  Revision drift is a run-level typed
            # refusal, never a transport failure within the retry budget.
            raise
        except TemplateCompileError:
            # OUR template failed to build. A second identical call would
            # send the same text to the same Roslyn and get the same CS
            # code back: a retry here is not an "extra attempt" but a
            # guaranteed-useless one. It bypasses the retry budget AND the
            # window wait (see the class) — exactly like a document
            # revision.
            raise
        except Exception as exc:  # bridge/protocol failures share retry budget
            last_error = exc
            if attempt < retries:
                await asyncio.sleep(EXTRACT_RETRY_BACKOFF_S[
                    min(attempt, len(EXTRACT_RETRY_BACKOFF_S) - 1)])
    assert last_error is not None
    detail = f"{type(last_error).__name__}: {last_error}"[:240]
    raise BridgeCallError(
        f"bridge round-trip failed after {retries + 1} attempts: {detail}"
    ) from last_error


class _WindowWaitBudget:
    """A budget of window-return wait shared across the whole RUN (task
    #26).

    The page retry budget tolerates ~25 s. A real outage lasts longer: the
    network breaks, the bridge dies with 1006, the window comes back with a
    NEW ws_id after seconds to minutes (measured 29.07, К2 РД). Burying a
    category after 25 seconds means throwing away the extraction of an
    entire model over a router reboot.

    The budget is SHARED, not per-page: a per-page budget would multiply by
    the number of pages, and a window closed forever would cost hours of
    phantom work. Here a dead window costs `EXTRACT_WINDOW_WAIT_S` exactly
    once per run.

    Safe by construction: reads are idempotent, each page runs under a
    revision guard. If the document changed during the outage, the guard
    raises DocumentRevisionError — a typed refusal of the RUN, and that is
    the correct outcome, not grounds for one more attempt.
    """

    __slots__ = ("_remaining", "spent", "waits")

    def __init__(self, total_s: float | None = None) -> None:
        # Constants are read AT RUNTIME, not latched into a default value:
        # otherwise overriding via the environment would affect neither an
        # already-imported module nor a test, and a "setting that doesn't
        # set anything" is the worst kind of setting.
        total = EXTRACT_WINDOW_WAIT_S if total_s is None else total_s
        self._remaining = max(0.0, float(total))
        self.spent = 0.0
        self.waits = 0

    @property
    def remaining(self) -> float:
        return self._remaining

    async def pause(self, poll_s: float | None = None) -> bool:
        """Wait before the next attempt; False means the budget is spent."""

        if self._remaining <= 0.0:
            return False
        poll = EXTRACT_WINDOW_POLL_S if poll_s is None else poll_s
        slice_s = min(float(poll), self._remaining)
        await asyncio.sleep(slice_s)
        self._remaining -= slice_s
        self.spent += slice_s
        self.waits += 1
        return True


async def _execute_awaiting_window(
    executor: BridgeExecutor,
    code: str,
    *,
    timeout_ms: int,
    retries: int,
    budget: _WindowWaitBudget,
    what: str,
) -> Any:
    """A page call that survives the window being gone for minutes.

    Retries inside ``_execute_with_retries`` remain transport-level; once
    their budget is burned, the WAIT begins here: pause — retry — pause,
    until the window returns or the run's shared budget runs out.

    No new "silent success" path is added: only what the bridge actually
    returned is passed onward. An exhausted budget is still a
    ``BridgeCallError``, just with an honest mention of how long it waited
    (the text goes into the partial reason). ``DocumentRevisionError`` never
    reaches here — ``_execute_with_retries`` raises it past the retry
    budget, and it likewise flies past the wait.

    ONLY THE WINDOW'S SILENCE IS WAITED ON. ``TemplateCompileError`` is a
    second refusal that flies past: "the bridge is silent" and "we failed
    to build what we meant to send" are different states, and the second is
    not cured by time. While they were treated as one, decompiling the tower
    on R2023 spent an hour and a half reporting "window not responding"
    about a live window and our own CS1503.
    """

    while True:
        try:
            return await _execute_with_retries(
                executor, code, timeout_ms=timeout_ms, retries=retries)
        except BridgeCallError as exc:
            if not await budget.pause():
                raise BridgeCallError(
                    f"{exc} | окно не вернулось за "
                    f"{budget.spent:.0f} с ожидания ({what})") from exc
            logger.warning(
                "[extract] окно не отвечает на %s — ждём возвращения "
                "(потрачено %.0f с, осталось %.0f, ожидание №%d)",
                what, budget.spent, budget.remaining, budget.waits)


def _parse_census(row: dict[str, Any]) -> list[Any]:
    """Verify the census contract and return its rows (§18.1/§18.2).

    The bridge sends both rows and its own total. A mismatch between them is
    not grounds to "take whichever looks plausible": the census exists to be
    the denominator, and a denominator computed from a truncated response
    would lie more quietly and more dangerously than no response at all.
    """
    census = row.pop("census", None)
    total = row.pop("census_total", None)
    if census is None:
        if total is not None:
            raise ExtractionProtocolError(
                "metadata.census_total is present without metadata.census")
        return []
    rows = _require_list(census, "metadata.census")
    declared = _require_int(total, "metadata.census_total")
    counted = 0
    for index, entry in enumerate(rows):
        item = _require_mapping(entry, f"metadata.census[{index}]")
        counted += _require_int(
            item.get("count"), f"metadata.census[{index}].count")
    if counted != declared:
        raise ExtractionProtocolError(
            f"metadata.census rows sum to {counted}, "
            f"but census_total says {declared}")
    return rows


def _parse_metadata(value: Any, change_stamp: str) -> L0Document:
    row = _require_mapping(value, "metadata")
    row.pop("rooms_has_more", None)
    row.pop("rooms_next_cursor", None)
    if "links" not in row:
        raise ExtractionProtocolError(
            "metadata is missing required links array")
    links = _require_list(row.pop("links"), "metadata.links")
    # The exact Bridge closure cannot compile SHA256 on Revit 2025/2026.
    # Validate every measured isometry here and issue its canonical digest
    # before persisting L0. Historical payloads without this additive axis
    # stay readable, but are explicitly transform-incomplete downstream.
    raw_identity = row.get("identity")
    identity_row = (
        _require_mapping(raw_identity, "metadata.identity")
        if raw_identity is not None else {})

    def document_key(value: Any, field_name: str) -> str | None:
        if value is None:
            return None
        fact = _require_mapping(value, field_name)
        source = fact.get("source")
        identity_value = fact.get("value")
        if (not isinstance(source, str) or not source
                or not isinstance(identity_value, str) or not identity_value):
            return None
        return f"revit:{source}:{identity_value}"

    raw_chain = identity_row.get("link_instance_chain") or []
    if not isinstance(raw_chain, list) or any(
            not isinstance(item, str) or not item for item in raw_chain):
        raise ExtractionProtocolError(
            "metadata.identity.link_instance_chain must be string array")
    source_chain = tuple(raw_chain)
    source_document_key = document_key(
        identity_row.get("document_identity"),
        "metadata.identity.document_identity")
    root_document_key = document_key(
        identity_row.get("federation_root_identity"),
        "metadata.identity.federation_root_identity")
    if row.get("federation_transform") is not None:
        try:
            row["federation_transform"] = (
                FederationTransformEvidence.from_bridge_dict(
                    row["federation_transform"],
                    "metadata.federation_transform",
                    subject_context=FederationTransformSubject(
                        source_document_key=source_document_key,
                        target_document_key=root_document_key,
                        link_instance_chain=source_chain,
                        target_link_instance_chain=())).to_dict())
        except L0SchemaError as exc:
            raise ExtractionProtocolError(
                f"invalid metadata federation transform: {exc}") from exc
    normalized_links: list[Any] = []
    for index, raw_link in enumerate(links):
        link_row = _require_mapping(raw_link, f"metadata.links[{index}]")
        if link_row.get("transform") is not None:
            try:
                link_identity = _require_mapping(
                    link_row.get("identity"),
                    f"metadata.links[{index}].identity")
                child_uid = link_identity.get("instance_unique_id")
                child_chain = (
                    (*source_chain, child_uid)
                    if isinstance(child_uid, str) and child_uid
                    else source_chain)
                link_row["transform"] = (
                    FederationTransformEvidence.from_bridge_dict(
                        link_row["transform"],
                        f"metadata.links[{index}].transform",
                        subject_context=FederationTransformSubject(
                            source_document_key=document_key(
                                link_identity.get(
                                    "linked_document_identity"),
                                f"metadata.links[{index}].identity."
                                "linked_document_identity"),
                            target_document_key=source_document_key,
                            link_instance_chain=child_chain,
                            target_link_instance_chain=(
                                source_chain))).to_dict())
            except L0SchemaError as exc:
                raise ExtractionProtocolError(
                    f"invalid metadata link transform: {exc}") from exc
        normalized_links.append(link_row)
    links = normalized_links
    census = _parse_census(row)
    document = {
        **row,
        "change_stamp": change_stamp,
        "elements": [],
        "category_status": [],
        "links": links,
        "census": census,
    }
    try:
        return L0Document.from_dict(document)
    except L0SchemaError as exc:
        raise ExtractionProtocolError(f"invalid metadata: {exc}") from exc


def _parse_metadata_page(
    value: Any,
    change_stamp: str,
    *,
    after_room_id: int | None,
) -> tuple[L0Document, bool, int | None]:
    row = _require_mapping(value, "metadata")
    has_more = row.get("rooms_has_more")
    if not isinstance(has_more, bool):
        raise ExtractionProtocolError(
            "metadata.rooms_has_more must be boolean")
    raw_cursor = row.get("rooms_next_cursor")
    if has_more:
        if not isinstance(raw_cursor, str) or not raw_cursor:
            raise ExtractionProtocolError(
                "paged room metadata requires rooms_next_cursor")
        try:
            cursor = int(raw_cursor)
        except ValueError as exc:
            raise ExtractionProtocolError(
                "metadata room cursor must be a numeric element id") from exc
        if after_room_id is not None and cursor <= after_room_id:
            raise ExtractionProtocolError(
                "metadata room cursor did not advance")
    else:
        if raw_cursor is not None:
            raise ExtractionProtocolError(
                "final room metadata page must have null cursor")
        cursor = None
    document = _parse_metadata(row, change_stamp)
    if len(document.rooms) > EXTRACT_BATCH:
        raise ExtractionProtocolError(
            f"metadata room page exceeds EXTRACT_BATCH={EXTRACT_BATCH}")
    room_ids: list[int] = []
    for room in document.rooms:
        try:
            room_ids.append(int(room.id))
        except ValueError as exc:
            raise ExtractionProtocolError(
                "Revit room id must be numeric") from exc
    if room_ids != sorted(room_ids) or len(room_ids) != len(set(room_ids)):
        raise ExtractionProtocolError(
            "metadata room ids must be unique and sorted")
    if has_more and not room_ids:
        raise ExtractionProtocolError(
            "empty room metadata page cannot claim has_more")
    if has_more and room_ids[-1] != cursor:
        raise ExtractionProtocolError(
            "room metadata cursor must equal its last room id")
    if after_room_id is not None and room_ids and room_ids[0] <= after_room_id:
        raise ExtractionProtocolError(
            "room metadata page repeated an emitted room")
    return document, has_more, cursor


def _parse_probe(value: Any) -> tuple[int, tuple[_Scope, ...]]:
    row = _require_mapping(value, "category probe")
    total = _require_int(row.get("count"), "category probe.count")
    levels = _require_list(row.get("levels"), "category probe.levels")
    parsed: list[_Scope] = []
    seen: set[str] = set()
    for index, raw_scope in enumerate(levels):
        scope = _require_mapping(raw_scope, f"category probe.levels[{index}]")
        key = scope.get("key")
        if not isinstance(key, str) or not key:
            raise ExtractionProtocolError(
                f"category probe.levels[{index}].key must be non-empty")
        if key in seen:
            raise ExtractionProtocolError(
                f"duplicate category probe level scope {key!r}")
        seen.add(key)
        count = _require_int(
            scope.get("count"), f"category probe.levels[{index}].count")
        if count:
            parsed.append(_Scope(key, count))
    if sum(scope.count for scope in parsed) != total:
        raise ExtractionProtocolError(
            "category probe level counts do not equal total count")
    if total <= EXTRACT_BATCH:
        return total, ((_Scope("__all__", total),) if total else ())
    return total, tuple(parsed)


#: Sixteen section parameters, read together with the receipt (it used to
#: say "eleven" — the comment had fallen five names behind the tuple;
#: recounted on 11.08.2026 straight from it). The list is CLOSED:
#: a page that fails to send a row for each of them is rejected — otherwise
#: "no section" would again become indistinguishable from "stopped asking".
#: THE CLOSED LIST OF PARAMETERS FOR WHICH SECTION RECEIPTS ARRIVE.
#:
#: 🔴 THIS LIST IS THE SECOND CARRIER, AND IT HAS ALREADY DIVERGED FROM THE
#: FIRST. The first carrier is the emitter itself: the calls
#: `__PutSectionParam`, `__PutSectionIntParam`, `__PutSectionIdParam` in the
#: generated C#. Whichever of them calls `__BumpSection` is the one that
#: sends the receipt.
#:
#: The cost of the divergence was measured on 20.08.2026 on a REAL building
#: (Revit 2023, 75 936 elements, 94 categories): commit `00ee35f5` at 11:12
#: expanded receipts from 16 probes to 43 — exactly as its title promises —
#: and did NOT touch this list. The `_parse_section_receipts` guard is
#: fail-closed: any name outside the list is a refusal. The result:
#: `extracted_count: 0` for ALL 31 categories that had content (33 944
#: elements), `elements_total: 0`, and decompiling any real building
#: returned emptiness for the next ~10 hours with an honest
#: `is_partial_read: false`.
#:
#: The list below is derived FROM THE EMITTER and pinned to it by the
#: `test_section_param_list_matches_the_emitter` test. No need to update it
#: by hand: add a probe in C#, and the test will name it and demand a row
#: here.
SECTION_PARAM_NAMES: tuple[str, ...] = (
    "CEILING_HEIGHTABOVELEVEL_PARAM",
    "FAMILY_BASE_LEVEL_OFFSET_PARAM",
    "FAMILY_BASE_LEVEL_PARAM",
    "FAMILY_HEIGHT_PARAM",
    "FAMILY_TOP_LEVEL_OFFSET_PARAM",
    "FAMILY_TOP_LEVEL_PARAM",
    "FAMILY_WIDTH_PARAM",
    "FLOOR_HEIGHTABOVELEVEL_PARAM",
    "FLOOR_PARAM_IS_STRUCTURAL",
    "INSTANCE_SILL_HEIGHT_PARAM",
    "RBS_CABLETRAY_HEIGHT_PARAM",
    "RBS_CABLETRAY_WIDTH_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "RBS_CONDUIT_OUTER_DIAM_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
    "RBS_CURVE_HEIGHT_PARAM",
    "RBS_CURVE_WIDTH_PARAM",
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_PIPE_OUTER_DIAMETER",
    "ROOM_UPPER_OFFSET",
    "SLANTED_COLUMN_TYPE_PARAM",
    "STAIRS_ACTUAL_NUM_RISERS",
    "STAIRS_ACTUAL_RISER_HEIGHT",
    "STAIRS_ACTUAL_TREAD_DEPTH",
    "STAIRS_BASE_LEVEL_PARAM",
    "STAIRS_TOP_LEVEL_PARAM",
    "STRUCTURAL_BEAM_END0_ELEVATION",
    "STRUCTURAL_BEAM_END1_ELEVATION",
    "STRUCTURAL_SECTION_COMMON_DIAMETER",
    "STRUCTURAL_SECTION_COMMON_HEIGHT",
    "STRUCTURAL_SECTION_COMMON_WIDTH",
    "WALL_ATTR_WIDTH_PARAM",
    "WALL_BASE_OFFSET",
    "WALL_BOTTOM_IS_ATTACHED",
    "WALL_CROSS_SECTION",
    "WALL_HEIGHT_TYPE",
    "WALL_KEY_REF_PARAM",
    "WALL_STRUCTURAL_SIGNIFICANT",
    "WALL_TOP_IS_ATTACHED",
    "WALL_TOP_OFFSET",
    "WALL_USER_HEIGHT_PARAM",
    "Z_JUSTIFICATION",
    "Z_OFFSET_VALUE",
)



def _parse_route_skips(value: Any, *, interrogated: int) -> "tuple[RouteSkip, ...]":
    """Route rows for one page. A missing key is NOT an error.

    The old bridge (pre-routing) does not send the key, and requiring it
    would mean declaring the prior protocol broken. An empty list means
    "there was a route and it cut nothing off"; absence means "there was no
    route at all" — the difference travels onward as `None` versus `()` in
    `CategoryStatus`.
    """
    if value is None:
        return ()
    rows = _require_list(value, "category page.route_skipped")
    out: list[RouteSkip] = []
    for index, raw in enumerate(rows):
        try:
            out.append(RouteSkip.from_dict(raw))
        except L0SchemaError as exc:
            raise ExtractionProtocolError(
                f"invalid route skip at index {index}: {exc}") from exc
    names = [r.parameter for r in out]
    if len(set(names)) != len(names):
        raise ExtractionProtocolError("route skips repeat a parameter")
    for row_ in out:
        if row_.total() != interrogated:
            raise ExtractionProtocolError(
                f"маршрут не сходится: {row_.parameter} обошёл {row_.skipped} "
                f"и проверил {row_.audited}, на странице {interrogated}")
    return tuple(sorted(out, key=lambda r: r.parameter))


def _parse_section_receipts(
    value: Any,
    *,
    interrogated: int,
    category: str | None = None,
    route_rows: "tuple[RouteSkip, ...]" = (),
) -> tuple[SectionReceipt, ...]:
    """Receipts for one page -> a tuple sorted by parameter.

    Codex review No. 12. What is checked is exactly what, if absent, would
    make a missing section indistinguishable from a failed read: (a)
    receipts EXIST, (b) there are exactly as many parameters as we asked
    for, (c) the sum of the six outcomes for each parameter equals the
    number of elements polled on the page.
    """
    if value is None:
        raise ExtractionProtocolError(
            "category page has no section_receipts: fail-open чтения сечений "
            "снова стал молчаливым (ревью №12)")
    rows = _require_list(value, "category page.section_receipts")
    receipts: list[SectionReceipt] = []
    for index, raw in enumerate(rows):
        try:
            receipts.append(SectionReceipt.from_dict(raw))
        except L0SchemaError as exc:
            raise ExtractionProtocolError(
                f"invalid section receipt at index {index}: {exc}") from exc
    names = tuple(sorted(r.parameter for r in receipts))
    if len(set(names)) != len(names):
        raise ExtractionProtocolError(
            "section receipts repeat a parameter")
    # THE CLOSED LIST STAYS CLOSED, BUT THE ROUTE IS SUBTRACTED FROM IT.
    # A name cut off for this category has no receipt — and that is not a
    # loss but a DECISION recorded as a route row. Requiring it here would
    # mean declaring the route a protocol defect.
    #
    # There is no relaxation: an extra name is still a refusal, and a
    # cut-off name is required to BE PRESENT in the route rows — otherwise
    # it would have vanished without a trace.
    skipped_names = {row.parameter for row in route_rows
                     if row.skipped and not row.audited}
    required = set(SECTION_PARAM_NAMES) - skipped_names
    if interrogated and (set(names) - set(SECTION_PARAM_NAMES)
                         or required - set(names)):
        missing = sorted(required - set(names))
        extra = sorted(set(names) - set(SECTION_PARAM_NAMES))
        raise ExtractionProtocolError(
            f"квитанции сечений не покрывают закрытый список параметров: "
            f"не хватает {missing}, лишние {extra}"
            + (f" (маршрут {category} отсёк {len(skipped_names)})"
               if skipped_names else ""))
    if not interrogated and receipts:
        raise ExtractionProtocolError(
            "пустая страница никого не опрашивала, а квитанции прислала")
    skipped_by = {row.parameter: row.skipped for row in route_rows}
    for receipt in receipts:
        asked = receipt.total() + skipped_by.get(receipt.parameter, 0)
        if asked != interrogated:
            raise ExtractionProtocolError(
                f"перепись сечений не сходится: {receipt.parameter} опросил "
                f"{receipt.total()} плюс отсечено "
                f"{skipped_by.get(receipt.parameter, 0)}, "
                f"на странице {interrogated}")
    return tuple(sorted(receipts, key=lambda r: r.parameter))


def _parse_page(
    value: Any,
    *,
    category: str,
    scope: _Scope,
    after_element_id: int | None,
) -> tuple[tuple[L0Element, ...], bool, int | None,
           tuple[SectionReceipt, ...], "tuple[RouteSkip, ...]"]:
    row = _require_mapping(value, "category page")
    raw_elements = _require_list(row.get("elements"), "category page.elements")
    if len(raw_elements) > EXTRACT_BATCH:
        raise ExtractionProtocolError(
            f"category page exceeds EXTRACT_BATCH={EXTRACT_BATCH}")
    has_more = row.get("has_more")
    if not isinstance(has_more, bool):
        raise ExtractionProtocolError(
            "category page.has_more must be boolean")
    raw_cursor = row.get("next_cursor")
    if has_more:
        if not isinstance(raw_cursor, str) or not raw_cursor:
            raise ExtractionProtocolError(
                "paged category response requires next_cursor")
        try:
            next_cursor = int(raw_cursor)
        except ValueError as exc:
            raise ExtractionProtocolError(
                "category page.next_cursor must be a numeric element id") from exc
        if after_element_id is not None and next_cursor <= after_element_id:
            raise ExtractionProtocolError(
                "category page cursor did not advance")
    else:
        if raw_cursor is not None:
            raise ExtractionProtocolError(
                "final category page must have null next_cursor")
        next_cursor = None

    elements: list[L0Element] = []
    ids: list[int] = []
    for index, raw_element in enumerate(raw_elements):
        element_row = _require_mapping(
            raw_element, f"category page.elements[{index}]")
        try:
            geometry = parse_geometry(element_row)
            element_row.update(geometry.to_element_fields())
            element = L0Element.from_dict(element_row)
        except L0SchemaError as exc:
            raise ExtractionProtocolError(
                f"invalid {category} element at page index {index}: {exc}"
            ) from exc
        if element.category != category:
            raise ExtractionProtocolError(
                f"element category {element.category!r} does not match "
                f"collector {category!r}")
        if scope.key == "__none__" and element.level_id is not None:
            raise ExtractionProtocolError(
                f"{category} element escaped no-level scope")
        if scope.key not in ("__all__", "__none__") \
                and element.level_id != scope.key:
            raise ExtractionProtocolError(
                f"{category} element escaped level scope {scope.key!r}")
        try:
            numeric_id = int(element.element_id)
        except ValueError as exc:
            raise ExtractionProtocolError(
                "Revit element_id must be numeric") from exc
        ids.append(numeric_id)
        elements.append(element)
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ExtractionProtocolError(
            "category page element ids must be unique and sorted")
    if has_more and not elements:
        raise ExtractionProtocolError(
            "empty category page cannot claim has_more")
    if has_more and ids[-1] != next_cursor:
        raise ExtractionProtocolError(
            "category page cursor must equal its last element id")
    if after_element_id is not None and ids and ids[0] <= after_element_id:
        raise ExtractionProtocolError(
            "category page repeated an already-emitted element")
    route_rows = _parse_route_skips(
        row.get("route_skipped"), interrogated=len(elements))
    receipts = _parse_section_receipts(
        row.get("section_receipts"), interrogated=len(elements),
        category=category, route_rows=route_rows)
    return tuple(elements), has_more, next_cursor, receipts, route_rows


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            value, ensure_ascii=False, allow_nan=False,
            separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ExtractionProtocolError(
            f"record is not valid JSON data: {exc}") from exc
    return text.encode("utf-8") + b"\n"


def _write_record(handle: Any, value: Mapping[str, Any]) -> None:
    handle.write(_json_bytes(value))


def _sync_file(handle: Any) -> int:
    handle.flush()
    os.fsync(handle.fileno())
    return handle.tell()


@dataclass(frozen=True, slots=True)
class _StreamMark:
    """Where a category ends in the stream and how many elements it yielded."""

    category: str
    state: str
    extracted_count: int
    offset_after: int


def _scan_stream_ledger(output: Path) -> tuple[int, tuple[_StreamMark, ...]]:
    """``(offset after the header, per-category marks)`` — read straight
    from the stream itself.

    Offsets are deliberately NOT stored in the checkpoint: the stream
    already contains them, and duplicating them would create a second
    source of truth about where a category ends — if it diverged from the
    file, a rewind would cut at a phantom boundary. Here the boundary is
    read from the very same place it was written.

    The file is line-based, so the offset is the sum of line lengths;
    ``_write_record`` knows no other delimiter.
    """

    header_offset = 0
    marks: list[_StreamMark] = []
    seen_header = False
    with output.open("rb") as handle:
        offset = 0
        for line in handle:
            offset += len(line)
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ExtractionProtocolError(
                    f"L0 stream has an unreadable record at {offset}") from exc
            kind = row.get("record")
            if kind == "header":
                seen_header = True
                header_offset = offset
            elif kind == "link":
                if not seen_header:
                    raise ExtractionProtocolError("L0 link precedes the header")
                header_offset = offset
            elif kind == "category_status":
                status = row.get("status") or {}
                marks.append(_StreamMark(
                    category=str(status.get("category")),
                    state=str(status.get("state")),
                    extracted_count=int(status.get("extracted_count") or 0),
                    offset_after=offset,
                ))
    if not seen_header:
        raise ExtractionProtocolError("L0 stream has no header record")
    return header_offset, tuple(marks)


def _rewind_to_first_partial(
    output: Path,
    state: dict[str, Any],
    checkpoint: Path,
) -> bool:
    """Rewind the stream to the FIRST unfinished category (task #27).

    Today, a resume with an already-written footer returns the result as
    is, and partial categories flow downstream as "the snapshot is not
    authoritative" — leaving the operator with a full run under a new
    stamp (measured: attempts 2-3 of k2_ar_rd_v1 died instantly). Partial on
    resume IS WORK.

    WHY A REWIND, AND NOT A SECOND FOOTER OR PATCHING THE TAIL. Appending
    the re-extracted category at the end is not possible: its previous
    (incomplete) elements are already in the stream, and next to the new
    ones they would produce DUPLICATES the reader cannot tell apart. A
    second, prioritized footer would fix only the counter and leave the
    duplicates in place, while also making "the last footer wins" a second
    law alongside ``stream_complete``. A rewind keeps the format exactly as
    declared: ONE header, categories in a fixed order, ONE footer last with
    the true counter. The cost is that categories after the first
    unfinished one are re-extracted; that is minutes against the hours of a
    full run, and they are honest minutes.

    Returns True if a rewind happened (there is more to extract).
    """

    states = dict(state["category_states"])
    first_partial = next(
        (category for category in EXTRACT_CATEGORIES
         if states.get(category) == CategoryState.PARTIAL.value), None)
    if first_partial is None:
        return False

    header_offset, marks = _scan_stream_ledger(output)
    by_category = {mark.category: mark for mark in marks}
    # The stream and the checkpoint must say the same thing about what is
    # finished. A mismatch is not grounds to "pick the more complete one":
    # both sides describe ONE run, and if they disagree, it is unknown
    # which boundary is the real one.
    for category, value in states.items():
        mark = by_category.get(category)
        if mark is not None and mark.state != value:
            raise ExtractionProtocolError(
                f"checkpoint says {category} is {value}, stream says "
                f"{mark.state}")

    index = EXTRACT_CATEGORIES.index(first_partial)
    kept = list(EXTRACT_CATEGORIES[:index])
    if kept:
        previous = by_category.get(kept[-1])
        if previous is None:
            raise ExtractionProtocolError(
                f"L0 stream has no category_status for {kept[-1]}")
        rewind_offset = previous.offset_after
    else:
        rewind_offset = header_offset
    element_count = sum(
        by_category[category].extracted_count
        for category in kept if category in by_category)

    with output.open("r+b") as handle:
        handle.truncate(rewind_offset)
    state.update({
        "committed_offset": rewind_offset,
        "processed_categories": kept,
        "category_states": {
            category: value for category, value in states.items()
            if category in kept},
        "element_count": element_count,
        # The footer is REMOVED together with the tail: it will be written
        # again at the end of the re-extraction, with the true counter.
        # `stream_complete` remains the law — it's just that right now the
        # stream is honestly NOT complete.
        "footer_written": False,
    })
    _atomic_write_json(checkpoint, state)
    logger.info(
        "[extract] резюм: отмотка к %s (оставлено %d категорий, %d элементов, "
        "смещение %d) — доизвлекаем",
        first_partial, len(kept), element_count, rewind_offset)
    return True


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


#: A counter for the temp file name. One process can write the same path
#: twice within a millisecond, and the pid alone cannot tell them apart
#: then.
_TMP_SEQ = itertools.count()


def _temp_name(path: Path) -> Path:
    """Temp file name, UNIQUE across all writers.

    🔴 IT USED TO BE `path.name + ".tmp"` — ONE NAME FOR EVERYONE, and this
    is not theory. A measurement from a neighboring session on the twin of
    this same function in `pipeline.py`: two streams of 1000 records each
    give **294-733 `FileNotFoundError` failures** — someone's `os.replace`
    grabs another's temp file right out from under it. After the unique
    name — zero. The fix's shape was taken from that same place (`bdc5db1`),
    not invented anew.

    Three sources of difference, and each closes off its own way to
    collide: pid — against different processes, the counter — against two
    writes by the same process within one millisecond, random bytes —
    against a pid collision after the kernel recycles the number.
    """

    return path.with_name(
        f"{path.name}.{os.getpid()}.{next(_TMP_SEQ)}."
        f"{os.urandom(4).hex()}.tmp")


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = _temp_name(path)
    with temporary.open("wb") as handle:
        handle.write(_json_bytes(value))
        _sync_file(handle)
    os.replace(temporary, path)
    _sync_directory(path.parent)


def _checkpoint_template(change_stamp: str, output_path: Path) -> dict[str, Any]:
    return {
        "schema_version": L0_SCHEMA_VERSION,
        # The generation of the table this RUN is conducted under.
        # Checkpoints taken before versioning (all 55 on disk on 29.07) do
        # not carry this key — its absence means "generation not named", not
        # "today's generation"; parsing is in ``_load_checkpoint``.
        "dialect": L0_DIALECT_VERSION,
        #: The generations under which chunks of this stream were written,
        #: in order. One element means the stream is homogeneous; more than
        #: one means a resume crossed a table bump, and that MUST be
        #: WRITTEN, not inferred after the fact.
        "dialect_history": [L0_DIALECT_VERSION],
        "change_stamp": change_stamp,
        "output_path": str(output_path.resolve()),
        "committed_offset": 0,
        "header_written": False,
        "footer_written": False,
        "processed_categories": [],
        "category_states": {},
        "element_count": 0,
        "link_count": 0,
    }


def _load_checkpoint(
    path: Path,
    *,
    change_stamp: str,
    output_path: Path,
) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExtractionProtocolError(
            f"cannot read checkpoint {path}: {exc}") from exc
    row = _require_mapping(raw, "checkpoint")
    if row.get("schema_version") != L0_SCHEMA_VERSION:
        raise ExtractionProtocolError("checkpoint schema version mismatch")
    if row.get("change_stamp") != change_stamp:
        raise ExtractionProtocolError(
            "checkpoint change_stamp differs; refusing stale resume")
    if row.get("output_path") != str(output_path.resolve()):
        raise ExtractionProtocolError("checkpoint output_path mismatch")
    offset = _require_int(
        row.get("committed_offset"), "checkpoint.committed_offset")
    header_written = row.get("header_written")
    footer_written = row.get("footer_written")
    if not isinstance(header_written, bool) or not isinstance(
            footer_written, bool):
        raise ExtractionProtocolError(
            "checkpoint header/footer flags must be boolean")
    processed = _require_list(
        row.get("processed_categories"), "checkpoint.processed_categories")
    if not all(isinstance(item, str) for item in processed):
        raise ExtractionProtocolError(
            "checkpoint.processed_categories must contain strings")
    if processed != list(EXTRACT_CATEGORIES[:len(processed)]):
        raise ExtractionProtocolError(
            "checkpoint categories are not a valid extraction prefix")
    states = _require_mapping(
        row.get("category_states"), "checkpoint.category_states")
    if set(states) != set(processed) or any(
            state not in (CategoryState.COMPLETE.value,
                          CategoryState.PARTIAL.value)
            for state in states.values()):
        raise ExtractionProtocolError(
            "checkpoint category states do not match processed categories")
    _require_int(row.get("element_count"), "checkpoint.element_count")
    _require_int(row.get("link_count"), "checkpoint.link_count")
    # ── RESUMING ACROSS A DIALECT BUMP ──────────────────────────────────
    #
    # READING AND APPENDING ARE DIFFERENT VERBS, WITH DIFFERENT ANSWERS. An
    # old, complete snapshot MUST be READABLE (that is exactly why the
    # generation ladder was built). It is not required to be appendable,
    # and here is the boundary:
    #
    # * A BROKEN-OFF run (no footer) — WE CONTINUE. Appending to the tail is
    #   proven by three sources, so the categories already processed are the
    #   same rows at the same indices; the loop addresses a category by
    #   INDEX (``EXTRACT_CATEGORIES[len(processed):]``), and appending to
    #   the tail shifts no index at all. New rows simply get appended after,
    #   and the footer at the end will tell the truth: every category of
    #   today's table has been walked for this ``change_stamp``. The cost of
    #   a refusal would be disproportionate: a К2 РД run is ~69 minutes, and
    #   throwing it away because the table grew between the break and the
    #   retry would mean punishing it for its own growth.
    #
    # * A FINISHED run (footer written) of an old generation — REFUSAL. Not
    #   because appending is technically impossible, but because
    #   ``stream_complete`` is the sole law of this container. A stream that
    #   has once said "I am complete" has no right to later say "not
    #   complete, appending" — that is not further extraction but a
    #   retroactive edit of a published fact, and any consumer that has
    #   already relied on that footer would be deceived after the fact. A
    #   refusal here costs the reader nothing: the snapshot still opens as
    #   its own generation.
    #
    # IS A MIXED SNAPSHOT HONEST. Yes — provided the mixing is NAMED.
    # Categories cannot be mixed (prefix), but FIELDS can: chunks taken by
    # different builds differ in which fields were added between them
    # (``curve_kind``, section receipts). But the house already has a law
    # for this: a missing field means "not measured", not "zero" — and it
    # applies PER RECORD, so a mixed stream remains parseable, and each
    # record stays truthful about itself. What remains is to name the
    # mixing as a whole: that is ``dialect_history`` in the checkpoint and
    # in the footer.
    #
    # A CHECKPOINT WITHOUT A ``dialect`` FIELD is a separate, FOURTH case,
    # and it is the common one: on 29.07 that is 55 out of 55. Such a
    # checkpoint's generation cannot be inferred (7 processed categories
    # look identical whether they broke off under generation /1 or
    # generation /6), so it is simply called ``unknown``. We continue:
    # refusing would mean throwing away all the accumulated unfinished work
    # for the sake of a field that did not exist at the time it was
    # written. But it is ``unknown`` that goes into the lineage, not
    # today's version: substituting the latter here would be exactly the
    # silent guesswork the ladder was built to forbid.
    raw_dialect = row.get("dialect")
    if raw_dialect is not None:
        if not isinstance(raw_dialect, str):
            raise ExtractionProtocolError("checkpoint.dialect must be a string")
        try:
            dialect_by_version(raw_dialect)
        except L0SchemaError as exc:
            raise ExtractionProtocolError(f"checkpoint: {exc}") from exc
    if footer_written and processed != list(EXTRACT_CATEGORIES):
        raise ExtractionProtocolError(
            f"checkpoint is a FINISHED stream of dialect "
            f"{raw_dialect or 'unknown'} ({len(processed)} categories); "
            f"today's dialect is {L0_DIALECT_VERSION} "
            f"({len(EXTRACT_CATEGORIES)} categories). A committed footer is "
            f"never re-opened — the snapshot still reads as its own "
            f"generation; extract afresh to get the added categories")
    history = row.get("dialect_history")
    if history is None:
        history = [raw_dialect or "unknown"]
    elif (not isinstance(history, list)
            or not all(isinstance(item, str) for item in history)):
        raise ExtractionProtocolError(
            "checkpoint.dialect_history must contain strings")
    if history[-1] != L0_DIALECT_VERSION:
        logger.warning(
            "[extract] резюм ПЕРЕСЁК бамп диалекта: поток начат под %s, "
            "продолжается под %s. Категории не смешиваются (дописка в "
            "хвост), поля — могут: в первых %d категориях полей, заведённых "
            "позже, НЕТ, и это значит «не мерили», а не «ноль». Родословная "
            "записана в футер.",
            history[-1], L0_DIALECT_VERSION, len(processed))
        history = [*history, L0_DIALECT_VERSION]
    row["dialect_history"] = history
    row["dialect"] = L0_DIALECT_VERSION
    if not header_written and (offset or processed):
        raise ExtractionProtocolError(
            "checkpoint has progress before its header commit")
    return row


def _safe_document_filename(doc_name: str) -> str:
    value = re.sub(r"[^\w.-]+", "_", doc_name, flags=re.UNICODE).strip("._")
    return value or "untitled"


def _checkpoint_path(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".checkpoint.json")


async def _new_metadata(
    executor: BridgeExecutor,
    change_stamp: str,
    *,
    timeout_ms: int,
    retries: int,
    link_title: str | None = None,
    link_instance_unique_id: str | None = None,
) -> L0Document:
    room_cursor: int | None = None
    metadata: L0Document | None = None
    rooms: list[RoomInfo] = []
    while True:
        payload = await _execute_with_retries(
            executor, build_metadata_cs(after_room_id=room_cursor,
                                        link_title=link_title,
                                        link_instance_unique_id=(
                                            link_instance_unique_id)),
            timeout_ms=timeout_ms, retries=retries)
        page, has_more, next_cursor = _parse_metadata_page(
            payload, change_stamp, after_room_id=room_cursor)
        if metadata is None:
            metadata = page
        else:
            stable_first = (
                metadata.doc_name, metadata.revit_version, metadata.units,
                metadata.change_stamp, metadata.levels, metadata.grids,
                metadata.project_info, metadata.links, metadata.identity,
                metadata.federation_transform,
            )
            stable_page = (
                page.doc_name, page.revit_version, page.units,
                page.change_stamp, page.levels, page.grids,
                page.project_info, page.links, page.identity,
                page.federation_transform,
            )
            if stable_page != stable_first:
                raise ExtractionProtocolError(
                    "document metadata changed between room pages")
        rooms.extend(page.rooms)
        if not has_more:
            break
        room_cursor = next_cursor
    assert metadata is not None
    return L0Document(
        doc_name=metadata.doc_name,
        revit_version=metadata.revit_version,
        units=metadata.units,
        change_stamp=metadata.change_stamp,
        levels=metadata.levels,
        grids=metadata.grids,
        rooms=tuple(rooms),
        project_info=metadata.project_info,
        links=metadata.links,
        # §18.4: reassembling the document from room pages must carry over
        # the worksets' state — otherwise read incompleteness dies right
        # here, between parsing the C# response and writing the header.
        worksharing=metadata.worksharing,
        worksets=metadata.worksets,
        worksets_closed=metadata.worksets_closed,
        # §18.1: the census is computed on the FIRST room page and lives in
        # ``metadata``; pages 2+ return null and must not erase it.
        census=metadata.census,
        identity=metadata.identity,
        federation_transform=metadata.federation_transform,
    )


def _read_header(path: Path, *, touch: bool = True) -> L0Document:
    """The L0 stream header — THROUGH THE SAME DOOR AS THE STREAM ITSELF.

    🔴 A DEFECT REPRODUCED ON 19.08.2026, AND IT WAS ASYMMETRIC WITHIN A
    SINGLE READER. `_records()` opens the stream via `open_snapshot` and
    reads the janitor-compressed parse; this function opened the same file
    with a bare `path.open("rb")`. On a compressed run, `iter_elements()`
    handed back 1,510 elements, while `metadata()` of the same reader
    raised `cannot read L0 header … No such file or directory`.

    The trap is recorded verbatim in the project map — "only
    `open_snapshot` / `read_snapshot_text`" — and it was the reading CORE
    itself that violated it.

    WHY NOBODY SAW THIS: the janitor `tools/snapshot_janitor.py` is wired
    to no timer at all, so compressed parses stand at 0 out of 75 today and
    the defect slept. Two shelves covered each other's defects — the reader
    stays intact only while the janitor is dead. This gets fixed BEFORE the
    janitor is called in, not after.

    `touch` is left at its default (true) DELIBERATELY: this is a REAL read
    by a consumer, and the last-access mark is exactly what the janitor
    uses to gauge "has this parse gone cold". Turning it off is a job for
    INSTRUMENTS that are dating what they measure, not for consumers.

    🔴 THE MARK'S CARRIER CHANGED ON 07.09.2026, THE DEFAULT DID NOT.
    Previously the mark landed IN the parse directory itself, so a "real
    read" thereby changed the thing being read; now it moves to an EXTERNAL
    JOURNAL (`kir.model.snapshot_io.access_journal_dir`). The case for the
    default only got stronger from this: deferring the janitor is still
    bought, while the directory is not touched at all — and `open_capture`,
    which promises "the directory is READ-ONLY", no longer pays for it with
    an exception on the pin.

    A handle is nonetheless wired through and exposed
    (`L0JSONLReader(..., touch=False)`) precisely for instruments: the
    journal is a trace too, and an instrument that is dating what it
    measures leaves its mark there as well.
    """
    # The import is lazy — the same technique as in `_records()` below; no
    # second convention is introduced for one call here.
    from kir.decompile.snapshot_io import open_snapshot

    try:
        with open_snapshot(path, "rb", touch=touch) as handle:
            raw_line = handle.readline()
    except OSError as exc:
        raise ExtractionProtocolError(
            f"cannot read L0 header from {path}: {exc}") from exc
    if not raw_line:
        raise ExtractionProtocolError("L0 stream has no header")
    try:
        row = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExtractionProtocolError(f"invalid L0 header JSON: {exc}") from exc
    record = _require_mapping(row, "L0 header")
    if (record.get("record") != "header"
            or record.get("schema_version") != L0_SCHEMA_VERSION):
        raise ExtractionProtocolError("invalid L0 stream header")
    document = _require_mapping(record.get("document"), "L0 header.document")
    try:
        header = L0Document.from_dict({
            **document, "elements": [], "category_status": [], "links": []})
    except L0SchemaError as exc:
        raise ExtractionProtocolError(f"invalid L0 header: {exc}") from exc
    # 🔴 THE HEADER STOPS SILENTLY IMPERSONATING A DOCUMENT. The full
    # argument is in `schema.UnloadedElements`; in short: on 18.08.2026 this
    # trap was stepped on THREE TIMES IN ONE DAY, even though it is recorded
    # verbatim in the root canon. The header's census knows the true element
    # count, so "zero with a non-empty census" is caught with no knowledge
    # of the caller at all.
    total = sum(int(getattr(row, "count", 0) or 0) for row in (header.census or ()))
    import dataclasses as _dc
    # The second argument is WHETHER the census was taken, not its value: a
    # snapshot without a `census` key proves nothing about the document
    # being empty.
    return _dc.replace(
        header,
        elements=UnloadedElements(total, header.census is not None))


async def extract_document(
    executor: BridgeExecutor,
    *,
    change_stamp: str,
    output_path: str | os.PathLike[str] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    resume: bool = True,
    timeout_ms: int = EXTRACT_TIMEOUT_MS,
    retries: int = EXTRACT_RETRIES,
    window_budget: "_WindowWaitBudget | None" = None,
    on_progress: Callable[[ExtractProgress], None] | None = None,
    #: Read not the host, but its LINK to such a Document.Title. Linked
    #: documents are already open in the session — nothing needs to be
    #: opened. A link's snapshot is separate, with its own stamp; its header
    #: also carries the definition identity and the occurrence path from the
    #: federation root. ElementId is never treated as global across these
    #: separate streams.
    link_title: str | None = None,
    #: Preferred selector. Unlike Document.Title this identifies one exact
    #: RevitLinkInstance occurrence and cannot collapse two placements of the
    #: same linked definition.
    link_instance_unique_id: str | None = None,
) -> ExtractionResult:
    """Extract one document without retaining its element population in RAM.

    ``executor`` must execute a read-only C# body and accept ``timeout_ms`` as
    a keyword argument.  The caller/world-state owner supplies the document
    change stamp; resume refuses a different stamp rather than inventing one.
    """

    if not isinstance(change_stamp, str) or not change_stamp:
        raise ValueError("change_stamp must be a non-empty string")
    if link_title is not None and link_instance_unique_id is not None:
        raise ValueError(
            "link_title and link_instance_unique_id are mutually exclusive")
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) \
            or timeout_ms <= 0 or timeout_ms > EXTRACT_TIMEOUT_MS:
        raise ValueError(
            f"timeout_ms must be in 1..{EXTRACT_TIMEOUT_MS}")
    if isinstance(retries, bool) or not isinstance(retries, int) \
            or retries < 0 or retries > EXTRACT_RETRIES:
        raise ValueError(f"retries must be in 0..{EXTRACT_RETRIES}")

    metadata: L0Document | None = None
    if output_path is None:
        metadata = await _new_metadata(
            executor, change_stamp, timeout_ms=timeout_ms, retries=retries,
            link_title=link_title,
            link_instance_unique_id=link_instance_unique_id)
        # We read env EVERY time: the module is imported once per process,
        # and a root remembered at import time could not be reassigned via
        # config.
        output = default_output_root() / (
            _safe_document_filename(metadata.doc_name) + "_L0.jsonl")
    else:
        output = Path(output_path)
    checkpoint = (
        Path(checkpoint_path) if checkpoint_path is not None
        else _checkpoint_path(output))
    if output.resolve() == checkpoint.resolve():
        raise ValueError("output_path and checkpoint_path must be different")
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)

    resumed = checkpoint.exists()
    if resumed:
        if not resume:
            raise ExtractionProtocolError(
                f"checkpoint already exists: {checkpoint}")
        state = _load_checkpoint(
            checkpoint, change_stamp=change_stamp, output_path=output)
    else:
        if output.exists():
            raise ExtractionProtocolError(
                f"output exists without a checkpoint; refusing overwrite: {output}")
        state = _checkpoint_template(change_stamp, output)
        _atomic_write_json(checkpoint, state)

    committed_offset = int(state["committed_offset"])
    if committed_offset:
        if not output.exists() or output.stat().st_size < committed_offset:
            raise ExtractionProtocolError(
                "checkpoint offset exceeds the existing output")
    elif state["header_written"]:
        raise ExtractionProtocolError(
            "header-written checkpoint cannot have zero offset")

    if state["footer_written"]:
        reader = L0JSONLReader(output)
        reader.validate()
        # PARTIAL ON RESUME IS WORK, NOT A FINAL RESULT (task #27). The
        # footer used to close the conversation: a resume returned the
        # snapshot as is, it failed downstream with
        # `snapshot_non_authoritative`, and the operator was left with a
        # full run under a new stamp. Now the stream is rewound to the
        # first unfinished category, and the ordinary loop extracts the
        # rest.
        if _rewind_to_first_partial(output, state, checkpoint):
            resumed = True
            # The rewind REWROTE the boundary — the local copy of the
            # offset is stale, and the file gets truncated by it further
            # down. Re-read from the state that has just become the truth.
            committed_offset = int(state["committed_offset"])
        else:
            complete = tuple(
                category for category in EXTRACT_CATEGORIES
                if state["category_states"][category] ==
                CategoryState.COMPLETE.value)
            # A completed stream is not re-read — we return the breakdown
            # of THAT read which filled it, not an empty one (otherwise
            # resuming a completed snapshot would look free).
            _done_timing = state.get("timing")
            return ExtractionResult(
                output, checkpoint, int(state["element_count"]),
                complete, (), resumed=True,
                timing=(dict(_done_timing)
                        if isinstance(_done_timing, Mapping) else {}))

    if state["header_written"]:
        metadata = _read_header(output)
        if metadata.change_stamp != change_stamp:
            raise ExtractionProtocolError(
                "L0 header change_stamp differs from checkpoint")
        with output.open("r+b") as handle:
            handle.truncate(committed_offset)
    else:
        if metadata is None:
            metadata = await _new_metadata(
                executor, change_stamp,
                timeout_ms=timeout_ms, retries=retries,
                link_title=link_title,
                link_instance_unique_id=link_instance_unique_id)
        with output.open("wb") as handle:
            _write_record(handle, {
                "record": "header",
                "schema_version": L0_SCHEMA_VERSION,
                "document": metadata.metadata_dict(),
            })
            for link in metadata.links:
                _write_record(handle, {
                    "record": "link", "link": link.to_dict()})
            committed_offset = _sync_file(handle)
        state["committed_offset"] = committed_offset
        state["header_written"] = True
        state["link_count"] = len(metadata.links)
        _atomic_write_json(checkpoint, state)

    processed = list(state["processed_categories"])
    category_states = dict(state["category_states"])
    element_count = int(state["element_count"])
    # The breakdown SURVIVES a resume: checkpoints taken before this wave
    # do not carry the key, and its absence means "not measured", not "zero
    # milliseconds". Categories finished off in a second pass are appended
    # to the first ones — the sum then describes the WORK, not a single
    # calendar interval.
    _prior_timing = state.get("timing")
    timing: dict[str, dict[str, float]] = (
        {str(key): {str(k): float(v) for k, v in dict(value).items()}
         for key, value in _prior_timing.items()}
        if isinstance(_prior_timing, Mapping) else {})
    # The window-wait budget is ONE per run (see _WindowWaitBudget): a dead
    # window must cost five minutes exactly once, not five minutes for each
    # of fifty-odd categories. The pipeline passes down ITS OWN budget so
    # extraction and the side stages spend a shared one, rather than five
    # minutes each.
    if window_budget is None:
        window_budget = _WindowWaitBudget()

    with output.open("r+b") as handle:
        handle.truncate(int(state["committed_offset"]))
        handle.seek(int(state["committed_offset"]))
        for category in EXTRACT_CATEGORIES[len(processed):]:
            expected_count: int | None = None
            extracted_count = 0
            error: str | None = None
            category_state = CategoryState.COMPLETE
            # Section receipts accumulate by CATEGORY (Codex review No. 12):
            # `parameter -> [six outcomes]`. An aggregate over pages, not
            # elements, so its size does not depend on the model's size.
            receipt_slots: dict[str, list[int]] = {}
            route_slots: dict[str, list[int]] = {}
            # THE INSTRUMENT. The clock starts BEFORE the probe and lives
            # for exactly one category: the breakdown must survive a crash,
            # so it travels into the checkpoint together with the offset,
            # rather than accumulating in memory until the end of a
            # forty-minute read.
            slot_t = _new_timing_slot()
            _bytes_at_start = handle.tell()
            try:
                _t0 = time.monotonic()
                probe_payload = await _execute_awaiting_window(
                    executor,
                    build_category_probe_cs(
                        category, link_title=link_title,
                        link_instance_unique_id=link_instance_unique_id),
                    timeout_ms=timeout_ms, retries=retries,
                    budget=window_budget, what=f"проба {category}")
                slot_t["probe_ms"] += (time.monotonic() - _t0) * 1000.0
                expected_count, scopes = _parse_probe(probe_payload)
                for scope in scopes:
                    scope_count = 0
                    cursor: int | None = None
                    while True:
                        _t0 = time.monotonic()
                        page_payload = await _execute_awaiting_window(
                            executor,
                            build_category_batch_cs(
                                category, level_scope=scope.key,
                                after_element_id=cursor,
                                link_title=link_title,
                                link_instance_unique_id=(
                                    link_instance_unique_id)),
                            timeout_ms=timeout_ms, retries=retries,
                            budget=window_budget,
                            what=(f"страница {category}"
                                  f" scope={scope.key!r} after={cursor}"))
                        _t1 = time.monotonic()
                        slot_t["bridge_ms"] += (_t1 - _t0) * 1000.0
                        slot_t["pages"] += 1.0
                        (elements, has_more, next_cursor, receipts,
                         route_rows) = _parse_page(
                            page_payload, category=category, scope=scope,
                            after_element_id=cursor)
                        _t2 = time.monotonic()
                        slot_t["parse_ms"] += (_t2 - _t1) * 1000.0
                        for receipt in receipts:
                            slots = receipt_slots.setdefault(
                                receipt.parameter, [0] * len(SECTION_RECEIPT_OUTCOMES))
                            for slot, name in enumerate(SECTION_RECEIPT_OUTCOMES):
                                slots[slot] += getattr(receipt, name)
                        # The route accumulates exactly like the receipts:
                        # by page, by name. Otherwise a category spanning
                        # two pages would report as if it were one.
                        for row_ in route_rows:
                            pair = route_slots.setdefault(row_.parameter, [0, 0])
                            pair[0] += row_.skipped
                            pair[1] += row_.audited
                        for element in elements:
                            _write_record(handle, {
                                "record": "element",
                                "collector": category,
                                "element": element.to_dict(),
                            })
                            scope_count += 1
                            extracted_count += 1
                        slot_t["write_ms"] += (
                            time.monotonic() - _t2) * 1000.0
                        if not has_more:
                            break
                        cursor = next_cursor
                    if scope_count != scope.count:
                        raise ExtractionProtocolError(
                            f"{category} scope {scope.key!r} yielded "
                            f"{scope_count}, expected {scope.count}")
                if extracted_count != expected_count:
                    raise ExtractionProtocolError(
                        f"{category} yielded {extracted_count}, "
                        f"expected {expected_count}")
            except (BridgeCallError, ExtractionProtocolError) as exc:
                category_state = CategoryState.PARTIAL
                error = str(exc)[:240]

            section_receipts = tuple(
                SectionReceipt(parameter=name,
                               **dict(zip(SECTION_RECEIPT_OUTCOMES, slots)))
                for name, slots in sorted(receipt_slots.items()))
            # `None` versus an empty tuple: there was no route at all is not
            # the same thing as "there was a route and it cut nothing off".
            route_skipped = tuple(
                RouteSkip(parameter=name, skipped=pair[0], audited=pair[1])
                for name, pair in sorted(route_slots.items())) or None

            # 🔴 THE ROUTE'S INSURANCE, AND IT IS LOUD. A sampled full pass
            # has already happened (every `AUDIT_EVERY`-th element), its
            # receipts sit in `section_receipts`. Here they are checked
            # against the table: if a cut-off name is found ANYWAY, the
            # category is declared INCOMPLETE with a named reason.
            #
            # Not "patched on the fly": a mismatch means the table describes
            # a different model, and a human must decide that. A silent
            # branch here would bring back exactly the disease all this
            # machinery was written against.
            if route_skipped:
                from kir.decompile.param_route import (
                    verify_against_receipts)
                drift = verify_against_receipts(category, section_receipts)
                if drift:
                    category_state = CategoryState.PARTIAL
                    error = ("маршрут зондов разошёлся с моделью: "
                             + "; ".join(f"{k}: {v}"
                                         for k, v in sorted(drift.items()))
                             )[:240]
            try:
                status = CategoryStatus(
                    category=category,
                    state=category_state,
                    extracted_count=extracted_count,
                    expected_count=expected_count,
                    error=error,
                    # The census law is checked by the TYPE ITSELF: the sum
                    # of the six outcomes for each parameter must equal the
                    # number of extracted elements in the category (Codex
                    # review No. 12).
                    section_receipts=section_receipts,
                    route_skipped=route_skipped,
                )
            except L0SchemaError as exc:
                raise ExtractionProtocolError(
                    f"{category}: {exc}") from exc
            _t3 = time.monotonic()
            _write_record(handle, {
                "record": "category_status", "status": status.to_dict()})
            committed_offset = _sync_file(handle)
            slot_t["write_ms"] += (time.monotonic() - _t3) * 1000.0
            slot_t["bytes"] = float(committed_offset - _bytes_at_start)
            slot_t["elements"] = float(extracted_count)
            timing[category] = {
                key: round(value, 3) for key, value in slot_t.items()}
            processed.append(category)
            category_states[category] = category_state.value
            element_count += extracted_count
            state.update({
                "committed_offset": committed_offset,
                "processed_categories": list(processed),
                "category_states": dict(category_states),
                "element_count": element_count,
                # The breakdown travels into the checkpoint, not into L0:
                # L0 is a deterministic artifact (I4), and wall-clock time
                # inside it would make two identical reads differ
                # byte-for-byte.
                "timing": dict(timing),
            })
            _atomic_write_json(checkpoint, state)
            if on_progress is not None:
                # The progress sink is an OBSERVER, not a participant: a
                # broken observer has no right to bring down a forty-minute
                # read. The same technique as status_cb in the pipeline.
                try:
                    on_progress(ExtractProgress(
                        category=category,
                        category_state=category_state.value,
                        categories_done=len(processed),
                        categories_total=len(EXTRACT_CATEGORIES),
                        elements=element_count,
                    ))
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "extract: сток прогресса отказал на %s", category,
                        exc_info=True)

        _write_record(handle, {
            "record": "footer",
            "stream_complete": True,
            "element_count": element_count,
            "link_count": int(state["link_count"]),
            "category_count": len(processed),
            # The generation is named EXPLICITLY, even though the reader
            # can infer it from ``category_count``: the inference rests on
            # the tail-append law, while the write rests on nothing. Let a
            # future snapshot answer for itself, even if the law is ever
            # broken.
            "dialect": L0_DIALECT_VERSION,
            # The mixed lineage of a resume (see ``_load_checkpoint``): the
            # generations under which earlier chunks of this stream were
            # written. The key is absent if the stream was written under a
            # single generation.
            **({"dialect_history": list(state["dialect_history"])}
               if len(state.get("dialect_history") or ()) > 1 else {}),
        })
        committed_offset = _sync_file(handle)

    state["committed_offset"] = committed_offset
    state["footer_written"] = True
    _atomic_write_json(checkpoint, state)
    complete = tuple(
        category for category in EXTRACT_CATEGORIES
        if category_states[category] == CategoryState.COMPLETE.value)
    partial = tuple(
        category for category in EXTRACT_CATEGORIES
        if category_states[category] == CategoryState.PARTIAL.value)
    return ExtractionResult(
        output, checkpoint, element_count, complete, partial, resumed,
        timing=timing)


@dataclass(frozen=True, slots=True)
class _TypedRecord:
    kind: str
    value: Any


class L0JSONLReader:
    """Streaming validator/parser for the Wave A JSONL container.

    Iterating elements keeps only one JSONL record in memory.  ``materialize``
    is intentionally explicit and reserved for tests or known-small models.
    """

    def __init__(self, path: str | os.PathLike[str], *,
                 touch: bool = True) -> None:
        """`touch` — whether to mark access to the parse (07.09.2026).

        The default is TRUE and stays that way: the reader here is a
        consumer, and the last-access mark is exactly what the janitor uses
        to gauge "has this parse gone cold". The handle is wired in for
        INSTRUMENTS that are dating what they measure — the same argument
        and the same shape as `open_snapshot(..., touch=False)`.

        One handle for BOTH reads of the class. An asymmetry within a
        single reader already cost this file a defect on 19.08.2026
        (`_records` went through `open_snapshot`, `_read_header` through a
        bare `open`), and it will not be reintroduced here a second time,
        now over the access mark.
        """
        self.path = Path(path)
        self._touch = bool(touch)
        self._dialect: L0Dialect | None = None

    def dialect(self) -> L0Dialect:
        """The table generation this stream was taken under.

        This alone is not enough for the reader to answer "is this
        snapshot complete by today's standards" — and rightly so: the
        answer depends on who is asking. Here only the fact is stated
        ("taken by a table of N categories"), while the inference ("so it
        is missing these specific categories") is made by
        :func:`~kir.decompile.schema.categories_outside_dialect`, for
        whoever needs it.
        """
        if self._dialect is None:
            self.validate()
        assert self._dialect is not None
        return self._dialect

    def _records(self) -> Iterator[_TypedRecord]:
        header_seen = False
        footer_seen = False
        element_count = 0
        link_count = 0
        status_count = 0
        current_category_count = 0
        category_started = False
        try:
            from kir.decompile.snapshot_io import open_snapshot
            handle = open_snapshot(self.path, "rb", touch=self._touch)
        except OSError as exc:
            raise ExtractionProtocolError(
                f"cannot open L0 stream {self.path}: {exc}") from exc
        with handle:
            for line_number, raw_line in enumerate(handle, start=1):
                if footer_seen:
                    raise ExtractionProtocolError(
                        f"record after footer at line {line_number}")
                try:
                    raw = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ExtractionProtocolError(
                        f"invalid JSONL at line {line_number}: {exc}") from exc
                row = _require_mapping(raw, f"JSONL line {line_number}")
                kind = row.get("record")
                if not isinstance(kind, str):
                    raise ExtractionProtocolError(
                        f"missing record kind at line {line_number}")
                if not header_seen:
                    if kind != "header":
                        raise ExtractionProtocolError(
                            "first JSONL record must be header")
                    if row.get("schema_version") != L0_SCHEMA_VERSION:
                        raise ExtractionProtocolError(
                            "L0 schema version mismatch")
                    document = _require_mapping(
                        row.get("document"), "header.document")
                    try:
                        parsed = L0Document.from_dict({
                            **document, "elements": [],
                            "category_status": [], "links": []})
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid header document: {exc}") from exc
                    header_seen = True
                    yield _TypedRecord(kind, parsed)
                elif kind == "header":
                    raise ExtractionProtocolError("duplicate JSONL header")
                elif kind == "element":
                    collector = row.get("collector")
                    if collector not in _SPEC_BY_NAME:
                        raise ExtractionProtocolError(
                            f"unknown element collector {collector!r}")
                    if (status_count >= len(EXTRACT_CATEGORIES)
                            or collector != EXTRACT_CATEGORIES[status_count]):
                        raise ExtractionProtocolError(
                            "element collector is out of category order")
                    category_started = True
                    element_row = _require_mapping(
                        row.get("element"), "element record")
                    try:
                        geometry = parse_geometry(element_row)
                        element_row.update(geometry.to_element_fields())
                        parsed = L0Element.from_dict(element_row)
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid element record: {exc}") from exc
                    if parsed.category != collector:
                        raise ExtractionProtocolError(
                            "element category/collector mismatch")
                    element_count += 1
                    current_category_count += 1
                    yield _TypedRecord(kind, parsed)
                elif kind == "link":
                    if category_started or status_count:
                        raise ExtractionProtocolError(
                            "link record appears after category extraction began")
                    try:
                        parsed = LinkSummary.from_dict(row.get("link"))
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid link record: {exc}") from exc
                    link_count += 1
                    yield _TypedRecord(kind, parsed)
                elif kind == "category_status":
                    try:
                        parsed = CategoryStatus.from_dict(row.get("status"))
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(
                            f"invalid category status: {exc}") from exc
                    if (status_count >= len(EXTRACT_CATEGORIES)
                            or parsed.category !=
                            EXTRACT_CATEGORIES[status_count]):
                        raise ExtractionProtocolError(
                            "category status is missing, duplicate, or out of order")
                    if parsed.extracted_count != current_category_count:
                        raise ExtractionProtocolError(
                            "category status extracted_count does not match "
                            "streamed records")
                    category_started = True
                    status_count += 1
                    current_category_count = 0
                    yield _TypedRecord(kind, parsed)
                elif kind == "footer":
                    if row.get("stream_complete") is not True:
                        raise ExtractionProtocolError(
                            "footer does not mark stream_complete")
                    if _require_int(
                            row.get("element_count"),
                            "footer.element_count") != element_count:
                        raise ExtractionProtocolError(
                            "footer element count mismatch")
                    if _require_int(
                            row.get("link_count"),
                            "footer.link_count") != link_count:
                        raise ExtractionProtocolError(
                            "footer link count mismatch")
                    if _require_int(
                            row.get("category_count"),
                            "footer.category_count") != status_count:
                        raise ExtractionProtocolError(
                            "footer category count mismatch")
                    # GENERATION, NOT "AS MANY AS TODAY". This used to read
                    # ``status_count != len(EXTRACT_CATEGORIES)``, and every
                    # growth of the table devalued EVERYTHING accumulated:
                    # on 29.07 (54 -> 73), 55 snapshots stopped opening all
                    # at once, but the five prior growths had just as
                    # silently devalued them too — nobody had simply tried
                    # opening the old ones with the new code.
                    #
                    # The check has not weakened, it has become precise. A
                    # strict prefix is still required row by row above
                    # (element/category_status are checked against
                    # ``EXTRACT_CATEGORIES`` positionally), and here the
                    # stream must end at the length of the generation that
                    # ACTUALLY EXISTED. A fresh build cannot do otherwise
                    # anyway: the footer is written after walking the whole
                    # table, and a failed category gets status PARTIAL and
                    # is still counted — so for today's streams this is
                    # exactly the old requirement of "all 73".
                    try:
                        self._dialect = resolve_dialect(
                            status_count, EXTRACT_CATEGORIES)
                    except L0SchemaError as exc:
                        raise ExtractionProtocolError(str(exc)) from exc
                    footer_seen = True
                    yield _TypedRecord(kind, dict(row))
                else:
                    raise ExtractionProtocolError(
                        f"unknown JSONL record kind {kind!r}")
        if not header_seen:
            raise ExtractionProtocolError("L0 stream is empty")
        if not footer_seen:
            raise ExtractionProtocolError("L0 stream has no committed footer")

    def metadata(self) -> L0Document:
        return _read_header(self.path, touch=self._touch)

    def iter_elements(self) -> Iterator[L0Element]:
        for record in self._records():
            if record.kind == "element":
                yield record.value

    def iter_links(self) -> Iterator[LinkSummary]:
        for record in self._records():
            if record.kind == "link":
                yield record.value

    def iter_category_status(self) -> Iterator[CategoryStatus]:
        for record in self._records():
            if record.kind == "category_status":
                yield record.value

    def validate(self) -> None:
        for _record in self._records():
            pass

    def materialize(self) -> L0Document:
        metadata: L0Document | None = None
        elements: list[L0Element] = []
        links: list[LinkSummary] = []
        statuses: list[CategoryStatus] = []
        for record in self._records():
            if record.kind == "header":
                metadata = record.value
            elif record.kind == "element":
                elements.append(record.value)
            elif record.kind == "link":
                links.append(record.value)
            elif record.kind == "category_status":
                statuses.append(record.value)
        assert metadata is not None
        return L0Document(
            doc_name=metadata.doc_name,
            revit_version=metadata.revit_version,
            units=metadata.units,
            change_stamp=metadata.change_stamp,
            levels=metadata.levels,
            grids=metadata.grids,
            rooms=metadata.rooms,
            project_info=metadata.project_info,
            elements=tuple(elements),
            category_status=tuple(statuses),
            links=tuple(links),
            # §18.4: the same on read — the materialized document carries
            # the header's mark, otherwise the whole offline tail
            # (lift/fold/verify/passport) treats a partial read as
            # complete.
            worksharing=metadata.worksharing,
            worksets=metadata.worksets,
            worksets_closed=metadata.worksets_closed,
            # §18.1: the same on read — without a census in the
            # materialized document, the whole offline tail treats the
            # sample as the denominator.
            census=metadata.census,
            identity=metadata.identity,
            federation_transform=metadata.federation_transform,
        )
