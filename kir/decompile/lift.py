"""Deterministic, fail-closed DECOMPILE L0 -> L1 lifting.

Each :class:`~kir.decompile.schema.L0Element` produces exactly one
JSON-ready L1 node.  A node is a regenerable KIR op only when all facts needed
by the live forward op are present; every other outcome is an honest atom.

This module is deliberately offline.  It reads the frozen Wave A dataclasses
and the live registries, but performs no bridge calls and emits no C#.
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field, replace
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Mapping, Sequence, cast

if TYPE_CHECKING:
    from kir.decompile.join_extract import JoinExtraction

from kir import contour as _contour
from kir import geom as _geom
from kir import spec
from kir.ops_authoring import WALL_LOCATION_LINE_NAMES
# Names WITHOUT aliases: the journal ratchet finds declarations by
# scanning the source for the pattern `NAME = Ledger(`, and it does
# not see `_Ledger(` — the journal would age silently (case of 12.08,
# the seventh common shape).
from kir.record_ratchet import CLOSE_BY, STANDS, Entry, Ledger
from kir.reverse_contract import (
    REVERSE_CONTRACTS,
    ReverseMode,
    assert_lift_emission,
)

#: Read off the op itself, so the lift can never offer a plane the emitter has
#: stopped realising (or miss one it has learned).
_LOCATION_LINE_CHOICES = frozenset(
    next(p for p in spec.OPS["create_wall"].params
         if p.name == "location_line").choices)
from kir.decompile.l1_schema import (
    AtomReason,
    L1AtomNode,
    L1Node,
    L1OpNode,
    is_valid_l1_node,
    stable_l1_id,
    validate_l1_nodes,
)
from kir.decompile.curtain_extract import (
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
from kir.decompile.family_placement_extract import (
    FamilyPlacementExtraction,
    FamilyPlacementPayloadError,
    FamilyPlacementRecord,
    FamilyPlacementType,
    parse_family_placement_failures,
    parse_family_placement_index,
)
from kir.decompile.schema import (
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
from kir.decompile.sketch_extract import (
    CurveKind,
    ProfileIndexRecord,
    RailingPathRecord,
    SketchPayloadError,
    StairsRunPathRecord,
)
from kir.decompile.dimension_extract import (
    DIMENSION_CATEGORIES,
    DIMENSION_SHAPE_LINEAR,
    DimensionExtraction,
    DimensionPayloadError,
)
from kir.decompile.mep_system_extract import (
    MepSystemExtraction,
    MepSystemPayloadError,
)
from kir.decompile.annotation_extract import (
    AnnotationExtraction,
    AnnotationPayloadError,
)
from kir.decompile.tag_extract import (
    TAG_CATEGORIES,
    TAG_FAMILIES,
    TAG_ORIENTATION_HORIZONTAL,
    TagExtraction,
    TagPayloadError,
)
from kir.decompile.curve_extract import (
    CurveExtraction,
    CurveKind as WallCurveKind,
    CurvePayloadError,
)
from kir.decompile.group_extract import parse_group_index


@dataclass(frozen=True, slots=True)
class LiftDiagnostic:
    """Why one source element conservatively became an atom."""

    source_element_id: str
    category: str
    reason: AtomReason
    detail: str


@dataclass(frozen=True, slots=True)
class LiftResult:
    """L1 nodes plus optional per-atom observability for audits/tests.

    🔴 A NEW FIELD HERE MUST REACH
    `lift_cache.serialize_lift_result`, and this is not a wish: that
    one is assembled FIELD BY FIELD BY HAND, and a field it does not
    know about it WILL DROP SILENTLY — a cached decompile will come
    back without it and without a single sign of the loss. Held in
    step by `test_lift_cache_carries_every_field` (checks the
    dataclass fields against the payload's keys), not by the editor's
    attention.
    """

    nodes: tuple[L1Node, ...]
    diagnostics: tuple[LiftDiagnostic, ...]
    #: What happened to the side index's joins. `None` — the index was
    #: NOT SUPPLIED (absence of KNOWLEDGE), an empty `JoinLift` —
    #: supplied and there are no joins (a fact about the building).
    #: Different things, hence not `field(default=JoinLift())`.
    joins: "JoinLift | None" = None
    #: What happened to the side index's GROUPS. The same discipline as
    #: for `joins`: `None` — the index was not supplied, an empty
    #: `GroupLift` — supplied and there are no groups. Merging them
    #: would mean saying "there are no design units in the building"
    #: where we simply did not ask.
    groups: "GroupLift | None" = None


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
    # A text annotation is lifted WHEN the formatting side index
    # brought it. When there is no index (all snapshots before
    # 30.07), the lifter refuses with the same source_contract_gap as
    # before — old decompiles must give the old answer verbatim,
    # otherwise "we broke nothing" is unverifiable.
    "OST_TextNotes": _Candidate(
        "text_note", "create_text", "_lift_text"),
    # A dimension is lifted WHEN the dimensions side index brought it.
    # When there is no index (all snapshots before this wave), the
    # lifter refuses with the same source_contract_gap and the same
    # text as before — old decompiles must give the old answer
    # VERBATIM, otherwise "we broke nothing" is unverifiable. Exactly
    # the same discipline as for annotations and tags.
    "OST_Dimensions": _Candidate(
        "dimension", "create_dimension", "_lift_dimension"),
    "OST_Levels": _Candidate("level", "create_level", "_lift_level"),
    "OST_Grids": _Candidate("grid", "create_grid", "_lift_grid"),
    "OST_PipeCurves": _Candidate("pipe", "create_pipe", "_lift_pipe"),
    "OST_DuctCurves": _Candidate("duct", "create_duct", "_lift_duct"),
    # 04.09.2026: FLEX RUNS MOVED HERE FROM `_OPS_WITHOUT_L0_INPUTS`.
    # The read now reads `FlexDuct.Points`/`FlexPipe.Points`, and the
    # gap stopped being a CAPTURE gap. The refusal did not go anywhere
    # — it moved down to the row level: for a snapshot with no key the
    # lifter raises the same atom with the same text.
    # 04.09.2026: OPENINGS MOVED HERE. The read now reads the boundary
    # (`extract._opening_boundary_reader_cs`); the host has been read
    # since 09.08. The refusal did not disappear — it moved down from
    # the table row to the snapshot row AND to the KIND: `wall_rect`
    # is lifted, `host_face` refuses by name, because the cut
    # direction is not read by any member of `Opening`.
    # 04.09.2026: the FIRST of eleven categories closed, opened by the
    # "silence becomes a refusal" wave on this same day.
    "OST_LineLoads": _Candidate(
        "line_load", "create_line_load", "_lift_line_load"),
    "OST_PointLoads": _Candidate(
        "point_load", "create_point_load", "_lift_point_load"),
    "OST_AreaLoads": _Candidate(
        "area_load", "create_area_load", "_lift_area_load"),
    "OST_SWallRectOpening": _Candidate(
        "opening", "create_opening", "_lift_opening"),
    "OST_FloorOpening": _Candidate(
        "opening", "create_opening", "_lift_opening"),
    "OST_RoofOpening": _Candidate(
        "opening", "create_opening", "_lift_opening"),
    "OST_FlexDuctCurves": _Candidate(
        "flex_duct", "create_flex_duct", "_lift_flex_duct"),
    "OST_FlexPipeCurves": _Candidate(
        "flex_pipe", "create_flex_pipe", "_lift_flex_pipe"),
    "OST_CableTray": _Candidate(
        "cable_tray", "create_cable_tray", "_lift_cable_tray"),
    # wave/mep-electrical (2026-08-09). The category appeared here for
    # exactly the same reason as ceilings and railings in the
    # architecture wave: it FINALLY HAS AN OP. Before it, every duct
    # went to an atom with the reason "the category is not in the
    # lifter table," and that was true; now the reason can only be a
    # missing FACT (a non-straight curve), and the difference between
    # these two answers decides what to fix next.
    "OST_Conduit": _Candidate(
        "conduit", "create_conduit", "_lift_conduit"),
    "OST_Stairs": _Candidate("stair", "create_stairs", "_lift_stairs"),
    # wave/arch (2026-07-29). The categories appeared in this table
    # because they FINALLY HAVE AN OP: before it, the atom's reason
    # read "the operation does not exist," and that was true. Now the
    # reason names the missing FACT (a ceiling's sketch profile, a
    # railing's path/host/position) — the difference decides what to
    # fix next.
    "OST_Ceilings": _Candidate("ceiling", "create_ceiling", "_lift_ceiling"),
    "OST_StairsRailing": _Candidate(
        "railing", "create_railing", "_lift_railing"),
    "OST_Railings": _Candidate("railing", "create_railing", "_lift_railing"),
    # A curtain-wall panel is a CELL of the host grid, not a
    # standalone element: the op assigns it a type (design
    # 2026-07-28). Before this wave the category did not exist here
    # at all, and 734 panels of the facade model went into the
    # generic placement path, which knows nothing about cells.
    "OST_CurtainWallPanels": _Candidate(
        "curtain_panel", "set_curtain_panel", "_lift_curtain_panel"),
    # wave/shape (2026-07-29). NOT a BuiltInCategory, but a
    # pseudo-category: a DirectShape's category is not determined by
    # its class, and the collector puts the literal "DirectShape" into
    # the field (extract.py:1296). The dispatcher does not know about
    # this distinction and should not have to — it just looks for a
    # string.
    "DirectShape": _Candidate(
        "direct_shape", "create_directshape", "_lift_directshape"),
    # wave/room (2026-08-03). The category has been read since 29.07
    # as room CONTEXT, but there was no op for it, and all 2 313
    # elements of K2 went to `no_lifter` — "the operation does not
    # exist." Now it exists.
    "OST_RoomSeparationLines": _Candidate(
        "room_separator", "create_room_separator", "_lift_room_separator"),
}

# ELEVEN KINDS OF TAGS — ONE op and ONE lifter (the tags wave, 30.07).
# The list is not rewritten here by hand, it is taken from THE READING
# STAGE ITSELF: a category recorded in one place and forgotten in the
# other is either ids no one will ever request, or elements with
# nothing to feed on. Ceiling and railing categories already paid for
# exactly this pairing on 29.07.
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


# ─── KINDS THAT HAVE AN OP, BUT NO INPUTS FOR IT IN THE READ (29.07) ───────
#
# The reading table grew from 54 to 73 categories (ee32fb82), and it
# came to include the content of working documentation: 13 905
# dimensions, 2 697 annotations, and ten kinds of tags — 36 241
# elements of the measured tower. The operations for them are WRITTEN
# and have lived in the registry since 28.07 (create_dimension /
# create_tag / create_text, ops_annotation.py). There are no lifters,
# and without this table every such element got `no_lifter` with the
# text "category is outside the exact Part 5 lifter table."
#
# THIS IS FALSE IN THE ONE PLACE WHERE THE FALSEHOOD IS COSTLY — in
# the ranking of causes used to decide what to build next. `no_lifter`
# reads as "there is no operation, go write it," and the next person
# would go write create_dimension, which is already written. The real
# shortage sits ONE STEP EARLIER: the frozen L0 1.0 row has no FIELDS
# for these ops' required inputs, and no lifter can fetch them from
# there.
#
# WHAT EXACTLY WAS CHECKED (kir.decompile.schema.L0Element — fields
# listed by name; extract.py — row emission):
#   * there is no owner view at all: neither a field, nor a read of
#     Element.OwnerViewId;
#   * there are no references: Dimension.References and
#     IndependentTag are not read;
#   * there are no view coordinates: the row's geometry is model
#     millimeters and a bounding box, while `pt_view2d` lives in the
#     2D plane of a specific view;
#   * there is no text: `params` is a CLOSED whitelist of geometric
#     BuiltInParameter values (extract.py:__PutParams), TextNote.Text
#     is absent from it, and `type_name` carries the NAME OF THE
#     annotation's TYPE, not its text.
#
# WHY NOT SUBSTITUTE SOMETHING. Every input of these ops is a
# REFERENCE TO ANOTHER ELEMENT or a location IN A SPECIFIC VIEW. A
# dimension bound to "some" element, and a tag "roughly there," would
# pass the L1 schema and look like coverage, while in reality they
# would be an invented source. The lifter has no right to invent
# sources (§18.1), and the cost of such a substitution is not a
# percentage, but trust in the number.
#
# The table is NOT a lifter table and deliberately lives separate
# from _CANDIDATES: there, a category promises an attempt to lift;
# here, only the correct name of the refusal.
#
# TAGS ARE NO LONGER HERE (the tags wave, 30.07), and this is not a
# loss of the refusal, but its RELOCATION. The ten kinds of tags now
# stand in ``_CANDIDATES``, and when there is no index, ``_lift_tag``
# refuses with the SAME ``source_contract_gap`` and the SAME text,
# assembled by the same ``_unsourceable_inputs_detail("create_tag")``
# — snapshots taken before the stage must give the old answer
# verbatim, otherwise the history of coverage stops being a history.
# ``OST_TextNotes`` relocated the exact same way on 30.07.
# wave/opening (03.08.2026): AN OPENING AS A STANDALONE ELEMENT — the
# very single SILENT loss that the eight-building sweep found. The
# subtlety is not that the opening is not lifted, but that before this
# wave it left NOT A SINGLE trace: the category is in no table, the
# element is not extracted, no atom results, while the HOST is lifted
# by an ordinary create_floor and reassembled AS SOLID. L2 acceptance
# does not catch this by construction (it says outright that it does
# not look at geometry at all), i.e. a silently wrong result is
# indistinguishable from success from the outside.
#
# The three kinds `create_opening` EXPRESSES stand here, not in
# `_CANDIDATES`, and this is the exact reason, not caution: the
# operation EXISTS, but the frozen L0 1.0 row carries neither
# `Opening.Host` nor the opening's boundary (`BoundaryRect`/
# `BoundaryCurves`) — i.e. what is missing is not the op, but the
# READ. `source_contract_gap` sends the repair to the extraction
# stage; `no_lifter` would send someone to write an operation that is
# already written. Exactly the distinction this code exists for.
#
# `OST_ShaftOpening` is DELIBERATELY ABSENT here: a shaft genuinely
# has no operation (see `ops_opening.VARIETIES_NOT_TAKEN["shaft"]` —
# the link to a pair of levels cannot be confirmed from the built
# element), and `no_lifter` about it is true. Putting it here would
# mean promising an operation that does not exist — the mirror-image
# lie.
#
# wave/mep-electrical (09.08.2026): FLEX RUNS. Both categories have
# been read since 27.07 (`extract.py`, the HVAC and plumbing
# sections), and until today every flex duct and every flex pipe got
# `no_lifter` with the text "category is outside the exact Part 5
# lifter table." On the morning of 09.08 this became FALSE:
# `create_flex_duct` and `create_flex_pipe` live in the registry
# (`ops_mep.py`), i.e. the refusal would still be sending the next
# person to write an operation that is already written — exactly the
# class of lie this code was set up against on 29.07 for dimensions.
#
# The categories stand HERE, not in `_CANDIDATES`, and this is the
# exact reason, not caution. The L0 row carries a PAIR OF CURVE ENDS,
# while a flex run's shape lives in
# `FlexDuct.Points`/`FlexPipe.Points` — a Hermite spline through N
# points (`ops_mep.py`, measured 6/6). The ends do NOT determine it:
# any polyline with the same ends would give the same row. Lifting
# such an element as a straight run between the ends would mean
# INVENTING geometry and presenting it as coverage — the same
# substitution as a chord instead of an arc
# (`CURVE_KIND_UNSUPPORTED`), and forbidden for the same reason.
# Hence, in the manifest (`reverse_contract.py`) too, both operations
# carry the `capture_gap` mode WITHOUT `representation_ops`.
#
# THE GAP HERE IS PARTIAL, AND THIS IS THE FIRST SUCH CASE IN THE
# TABLE: the L0 row carries `level`, but not `path`. The previous
# refusal wording ("carries NONE of the required inputs") would have
# lied about them, so the text is now assembled from two tables — see
# `_L0_ALREADY_CARRIES` below.
# 🔴 ON 04.09.2026 THE TABLE EMPTIED OUT, AND THIS MUST BE READ
# CORRECTLY.
# Flex runs and openings — its last residents — moved to
# `_CANDIDATES`: the read learned to carry their inputs. The refusal
# WENT NOWHERE, it moved down from the TABLE row to the SNAPSHOT row
# and to the KIND, where the lifters themselves now issue it
# (`_lift_opening`, `_lift_flex_run`) with the same text from the
# same instrument.
#
# The mechanism is deliberately kept ALIVE: it will be needed by a
# category that has an op but NO inputs AT ALL, and one like that
# will appear with the very next registry wave. But an empty table
# makes any scan over it turn GREEN WITHOUT AN ACT OF DISTINCTION, so
# the tests that walked its values have been moved to
# `_OPS_WHOSE_REFUSAL_IS_BUILT` below — otherwise my own edit would
# have silently lifted the check from three ops whose refusal this
# instrument still collects.
_OPS_WITHOUT_L0_INPUTS: Mapping[str, str] = MappingProxyType({
    # 04.09.2026 — THE "SILENCE BECOMES A REFUSAL" WAVE. Thirteen
    # categories were entered into the read by this same move
    # (`extract._CATEGORY_SPECS`, dialect stage 10). Each one HAS an
    # operation in the registry, and not one produced A SINGLE ROW: the
    # building was reassembled without topography, filled regions,
    # loads, and fascias — silently. Now each one gives
    # `source_contract_gap`, whose text is the specification for the
    # next reading wave.
    "OST_AreaRein": "create_area_reinforcement",
    "OST_Topography": "create_topography",
    "OST_BuildingPad": "create_building_pad",
    "OST_FilledRegion": "create_filled_region",
    # Masking is NOT a separate API type: the element is of the same
    # class `FilledRegion`, so the op is the same. What exactly tells
    # its kind apart is for the lifter wave to decide, and a seam
    # awaits it there too: `FilledRegion.CreateMaskingRegion` lives
    # only in 2024-2026 (per the trap index), whereas the read
    # `GetBoundaries` is 6/6.
    "OST_MaskingRegion": "create_filled_region",
    "OST_Cornices": "create_wall_sweep",
    "OST_Reveals": "create_wall_sweep",
    "OST_EdgeSlab": "create_slab_edge",
    "OST_StairsLandings": "create_stairs_landing",
    "OST_PathOfTravelLines": "create_path_of_travel",
})

#: An op's required input → the Revit API member that would have to
#: START BEING READ for the input to appear. This is the
#: specification of the next reading wave, recorded where it will be
#: found — in the refusal itself. The map's completeness against the
#: registry is checked by a test: if an op acquires a new required
#: input and there is no row here, the test fails, and the refusal
#: does not start lying silently.
#:
#: NAMES ARE CHECKED AGAINST THE TRAP INDEX (api_trap_index.py), NOT
#: FROM MEMORY, and one check already paid for itself. TAG has NOT A
#: SINGLE member living across all six versions — the surface tears
#: exactly at 2022:
#:
#:   P:IndependentTag.TaggedLocalElementId      2021-2022, REMOVED after 2022
#:   M:IndependentTag.GetTaggedLocalElement     2021-2022, REMOVED after 2022
#:   M:IndependentTag.GetTaggedLocalElementIds  2022-2026, ABSENT in 2021
#:
#: That is, 2022 is the only year where both exist, and any wave that
#: reads a tag's target under one name will fail to build on either
#: 2021 or 2023+. Both are named here so the next person sees the seam
#: before the compiler does.
#:
#: The remaining three are checked and live in ALL versions:
#: Element.OwnerViewId, Dimension.References, TextElement.Text
#: (TextNote inherits it; the member "TextNote.Text" does not exist in
#: the documentation at all — it is declared on TextElement).
#:
#: 30.07: the rows ``in_view``/``target``/``at`` stopped being the
#: specification of a FUTURE wave — the ``tag`` stage now reads them
#: (``tag_extract``). The map stays in place and still assembles the
#: refusal text, because the refusal stays correct exactly when the
#: stage was absent: a snapshot with no index must give the same atom
#: with the same reason as before the wave.
#: 04.09.2026: THE KEY BECAME A PAIR ``(op, input)``. The wildcard op
#: ``"*"`` means "this input has ONE source across all ops"; that is
#: how it stood before for all eight, and it was correct right up to
#: the first name collision. The lookup rule is in
#: :func:`_source_gap_note`.
_L0_HAS_NO_SOURCE_FOR: Mapping[tuple[str, str], str] = MappingProxyType({
    ("*", "in_view"): "Element.OwnerViewId",
    ("*", "refs"): "Dimension.References",
    ("*", "target"): ("IndependentTag.TaggedLocalElementId (2021-2022) / "
               ".GetTaggedLocalElementIds (2022+) — шов версий"),
    # Not an API member, but an INFERENCE: both TagHeadPosition and
    # TextElement.Coord give a MODEL XYZ, while `pt_view2d` is a
    # coordinate in the plane of a specific view. The conversion needs
    # the view's basis, i.e. the view itself, which is also absent.
    ("*", "at"): "точка в координатах вида (нужен базис вида, не только XYZ)",
    ("*", "line_at"): "точка в координатах вида (нужен базис вида, не только XYZ)",
    ("*", "content"): "TextElement.Text",
    # wave/opening (03.08.2026). The opening's kind is the SOLE
    # required input of `create_opening`, and it is not "one field"
    # but a decision made from THREE members at once: `Opening.Host`
    # (a wall -> wall_rect, a floor/roof/ceiling -> host_face, empty ->
    # shaft), `IsRectBoundary`, and the boundary itself. The frozen L0
    # 1.0 row reads none of them, so the refusal names them by name —
    # it is the specification of the next reading wave, not a
    # complaint. The names are checked against the trap index:
    # Host/IsRectBoundary/BoundaryRect/BoundaryCurves live 6/6, while
    # `Opening.SketchId` is 2022-2026, i.e. an opening's sketch on 2021
    # has nothing at all to read it with, and that is a seam the next
    # person must not trip on.
    # 04.09.2026: the key became an EXACT pair. As a wildcard it was
    # correct right up until a second op with a `variety` input
    # appeared, and such an op already exists in the registry
    # (`create_topography`, and also `create_solid_sweep`): each of
    # them would have gotten text ABOUT AN OPENING.
    ("create_opening", "variety"): ("Opening.Host + Opening.IsRectBoundary + "
                "Opening.BoundaryRect/BoundaryCurves (все 6/6; "
                "Opening.SketchId только 2022-2026)"),
    # wave/mep-electrical (09.08.2026). A flex run's path. The member
    # lives in ALL six versions (`FlexDuct.Points`/`FlexPipe.Points`,
    # IList<XYZ> — measured by compilation, ops_mep.py header), i.e.
    # this is not "cannot be read" but "not read": the refusal row is
    # exactly the specification of one capture row. Named as ONE entry
    # for both ops deliberately — they share the parameter, and two
    # texts about one field would spread one hole across two rows of
    # the ranking.
    ("*", "path"): ("FlexDuct.Points / FlexPipe.Points (IList<XYZ>, 6/6) — сплайн "
             "Эрмита через N точек; пара концов кривой его НЕ задаёт"),
    # ═════════════════════════════════════════════════════════════════════
    # 04.09.2026 — THE "SILENCE BECOMES A REFUSAL" WAVE, +19 entries.
    #
    # Each names the API MEMBER that would have to start being read.
    # Names are checked against the trap index (`api_trap_index`) and
    # against the metadata of the six assemblies; versions were printed
    # IN FULL — a truncated version-string slice in the report already
    # cost me one false seam on this very day.
    #
    # 🔴 THE PAIRS HERE ARE NOT DECORATION. `variety`, `contour`,
    # `host`, `p0_mm`, and `p1_mm` occur on DIFFERENT ops with
    # DIFFERENT sources, and without the key pair, one's refusal would
    # print another's API member.
    ("create_point_load", "xyz"): "PointLoad.Point (6/6, 3 ловушки)",
    ("create_point_load", "load_case"): "LoadBase.LoadCaseId (6/6, 2 ловушки)",
    ("create_line_load", "p0_mm"): "LineLoad.StartPoint (6/6, ловушек 0)",
    ("create_line_load", "p1_mm"): "LineLoad.EndPoint (6/6, ловушек 0)",
    ("create_line_load", "load_case"): "LoadBase.LoadCaseId (6/6, 2 ловушки)",
    ("create_area_load", "outline"): "AreaLoad.GetLoops (6/6, ловушек 0)",
    ("create_area_load", "elev_mm"): (
        "отметка контура нагрузки — выводится из AreaLoad.GetLoops, "
        "своего члена у неё нет"),
    ("create_area_load", "load_case"): "LoadBase.LoadCaseId (6/6, 2 ловушки)",
    ("create_area_reinforcement", "host"): (
        "AreaReinforcement.GetHostId (6/6, ловушек 0)"),
    ("create_area_reinforcement", "direction_deg"): (
        "AreaReinforcement.Direction (6/6)"),
    ("create_topography", "variety"): (
        "поверхность или толща: OST_Topography снимается, а OST_Toposolid "
        "живёт ТОЛЬКО 2023-2026 (оракул 4/6), и коллектор с ним не собрался "
        "бы на 2021-2022 — поэтому род «толща» сегодня невыразим"),
    ("create_topography", "points_mm"): (
        "TopographySurface.GetPoints (6/6, ловушек 0)"),
    ("create_building_pad", "contour"): (
        "BuildingPad.GetBoundary (6/6, ловушек 0)"),
    ("create_filled_region", "contour"): (
        "FilledRegion.GetBoundaries (6/6, ловушек 0); точки контура — [u,v] "
        "мм ПРОСТРАНСТВА ВИДА, а не модели"),
    ("create_wall_sweep", "host"): "WallSweep.GetHostIds (6/6, ловушек 0)",
    ("create_wall_sweep", "orientation"): (
        "WallSweep.GetWallSweepInfo().IsVertical (6/6)"),
    # 🔴 THE ONLY ENTRY THAT SAYS "NEVER," AND THIS IS A MEASUREMENT.
    # `SlabEdge` and `SlabEdgeType` together have FOUR members across
    # all six versions: the type itself, `SlabEdgeType`,
    # `AddSegment(Reference)`, and two `NewSlabEdge` constructors. There
    # is no host among them. So `create_slab_edge` will not become a
    # forward pass by ANY reading wave — there is nothing to read.
    ("create_slab_edge", "host"): "SlabEdge.AddSegment(Reference) (6/6)",
    ("create_slab_edge", "side"): (
        "ГЕТТЕРА НЕТ НИ В ОДНОЙ ВЕРСИИ: у SlabEdge и SlabEdgeType вместе "
        "четыре члена, стороны среди них нет — это не «не дочитали», а "
        "«читать нечего»"),
    ("create_stairs_landing", "stairs"): (
        "Stairs.GetStairsLandings (6/6, ловушек 0)"),
    ("create_stairs_landing", "contour"): (
        "StairsLanding: контур площадки берётся с её эскиза"),
    ("create_stairs_landing", "elevation_mm"): (
        "отметка площадки — с самой StairsLanding"),
    ("create_path_of_travel", "p0_mm"): (
        "PathOfTravel.PathStart (6/6, 3 ловушки) либо GetCurves"),
    ("create_path_of_travel", "p1_mm"): (
        "PathOfTravel.PathEnd (6/6) либо GetCurves"),
})

#: Required inputs the frozen L0 1.0 row ALREADY CARRIES, and the
#: FIELD that carries them. The table was created on 09.08 together
#: with flex runs, and it has exactly two jobs.
#:
#: THE FIRST — not letting the refusal lie. Before flex runs, a
#: capture gap could only be FULL: a dimension, a tag, an annotation,
#: and an opening had NOT A SINGLE required input in L0, and the text
#: said exactly that — "NOT A SINGLE ONE." `create_flex_duct` has two
#: inputs, and the L0 row carries `level` (`level_id`/`level_name`;
#: exactly where the pipe, duct, tray, and cable-tray lifters take it
#: from). Keeping the old wording would mean lying in the very claim
#: this refusal exists to be precise about.
#:
#: THE SECOND — not letting the gap become SILENT. The refusal names
#: only the missing inputs; without a positive declaration, a new
#: required input absent from both tables would simply vanish from the
#: text, and the refusal would stop being the specification of the
#: next reading wave. Hence the test requires every required input to
#: stand in EXACTLY ONE of them.
_L0_ALREADY_CARRIES: Mapping[str, str] = MappingProxyType({
    "level": "L0Element.level_id / level_name",
})


#: Ops whose refusal text is assembled by
#: :func:`_unsourceable_inputs_detail`. The SOLE CARRIER of this
#: list: the completeness test for the two input tables walks it, and
#: before 04.09 it was assembled from the values of
#: `_OPS_WITHOUT_L0_INPUTS`. That one emptied out, and walking it would
#: have become an empty walk — i.e. green, having checked nothing. The
#: list is named explicitly here too, next to the instrument, not only
#: in the test: a second carrier would have drifted apart silently.
_OPS_WHOSE_REFUSAL_IS_BUILT = frozenset({
    "create_tag", "create_text", "create_dimension",
    "create_opening", "create_flex_duct", "create_flex_pipe",
    # 04.09.2026 — the "silence becomes a refusal" wave, +11 operations.
    "create_point_load", "create_line_load", "create_area_load",
    "create_area_reinforcement", "create_topography", "create_building_pad",
    "create_filled_region", "create_wall_sweep", "create_slab_edge",
    "create_stairs_landing", "create_path_of_travel",
})


def _source_gap_note(op_name: str, param: str) -> str:
    """What this input WOULD BE READ BY — accounting for the OP, not
    just the input's name.

    🔴 CREATED 04.09.2026, AND THE TRAP WAS LATENT. The table was keyed
    by a SINGLE input name, and this worked exactly because all eight
    keys today occur on ops with the same source. The very first
    collision would print a FOREIGN source as its own: `variety` for
    an opening is `Opening.Host` plus the boundary, while `variety` for
    a topography is "surface or solid," and a topography's refusal
    would point to an opening. The text would look plausible and would
    lead someone to read the wrong API member.

    The key is now a PAIR. The wildcard op ``"*"`` is kept
    deliberately and means "this input has one source across all
    ops" — that is how `in_view`, `content`, and the others stand, for
    which it truly is one. There is one lookup rule: the exact pair
    first, then the wildcard; there is no second table.
    """

    точный = _L0_HAS_NO_SOURCE_FOR.get((op_name, param))
    if точный is not None:
        return точный
    общий = _L0_HAS_NO_SOURCE_FOR.get(("*", param))
    return общий if общий is not None else "источник не назван"


def _unsourceable_inputs_detail(op_name: str) -> str:
    """A refusal ASSEMBLED FROM THE REGISTRY, not rewritten by hand.

    The list of required inputs is taken from the op itself, so the
    refusal text cannot drift from the specification: the op changes,
    the refusal changes with it.

    A gap can be FULL or PARTIAL, and the text must tell them apart.
    For a full one (a dimension, a tag, an annotation, an opening) the
    wording is VERBATIM the old one — snapshots decompiled before
    09.08 must read with the same taxonomy and the same text, otherwise
    the history of coverage stops being a history.
    """

    required = tuple(
        param.name for param in spec.OPS[op_name].params if param.required)
    missing = tuple(
        name for name in required if name not in _L0_ALREADY_CARRIES)
    named = "; ".join(f"{name} <- {_source_gap_note(op_name, name)}"
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


#: Categories lifted on the SECOND pass: their op references a host,
#: and the reference must not depend on element order in L0. A
#: curtain panel references its cell's host exactly the way a door
#: references a wall.
#: 04.09.2026: openings added here, because `create_opening` takes a
#: REFERENCE to its host (`host: {"ref": …}`), and the reference
#: resolves against an ALREADY lifted node. On the first pass, an
#: opening would get a refusal not about the model, but about the row
#: order in L0 — exactly the defect the second pass exists to prevent
#: for doors.
_HOSTED_CATEGORIES = frozenset(
    ("OST_Doors", "OST_Windows", "OST_CurtainWallPanels",
     "OST_SWallRectOpening", "OST_FloorOpening", "OST_RoofOpening"))

#: Categories the FIRST pass skips: their reference resolves against
#: already-lifted nodes. Hosts on the second pass, tags on the third
#: (a tag can reference a door, i.e. the result of the second). The
#: set is assembled from two sources, not rewritten: were they to
#: drift apart, it would leave an element without a node, and the
#: general guard at the end would turn it into an internal_error.
#: Annotation elements that REFERENCE other elements: a tag references
#: its tagged element, a dimension references what it measures. Both
#: categories must be lifted AFTER everything they might reference
#: (see the third pass in ``_lift_document``), otherwise their
#: refusal would depend on element order in L0, not on the model.
_REFERENCING_ANNOTATION_CATEGORIES = TAG_CATEGORIES | DIMENSION_CATEGORIES

_DEFERRED_CATEGORIES = (
    _HOSTED_CATEGORIES | _REFERENCING_ANNOTATION_CATEGORIES)


def _host_pending(element: L0Element,
                  family_placement_index: Mapping[str, Any]) -> bool:
    """The element has a HOST declared by a side index record.

    🔴 CREATED 25.08.2026 BY MEASUREMENT. The deferred-pass mechanism
    covered `_DEFERRED_CATEGORIES` — doors, windows, curtain panels,
    tags, dimensions. Families whose host is declared in
    `family_placement_index.host_id` (equipment, fixtures, generic
    models) were NOT entered into it and were lifted on the first pass,
    in `document.elements` order.

    One run, one document, one index, two rows in different order:

        the wall BEFORE the equipment  ->  place_family
        the equipment BEFORE the wall  ->  ATOM missing_reference

    One model, two answers, and the refusal SPEAKS ABOUT OUR OWN
    TRAVERSAL, yet reads as a fact about the building. `MISSING_REFERENCE`
    is also not part of `_SHAPE_REFUSALS`, i.e. the refusal is
    TERMINAL. The order of L0 rows is set by the Revit collector's
    traversal and is not promised to be stable — meaning one building
    would be lifted differently from run to run, carrying off the
    canonical hashes with it.

    A RECORD is asked for, not a list of categories: the host is a
    property of the element, not of its kind, and a hand-written list
    of categories would drift from the index silently.
    """
    строка = family_placement_index.get(element.element_id)
    if not isinstance(строка, Mapping):
        return False
    хозяин = строка.get("host_id")
    return isinstance(хозяин, str) and bool(хозяин)


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
    # §18.2/M5: receipts of the placements side index, keyed by
    # element_id. An empty dict = no receipts (an old decompile or a
    # stage with no slices) — exactly the previous behavior.
    family_placement_failures: Mapping[str, Any] = field(default_factory=dict)
    #: Railing capture by the ``sketch`` stage (path, host, base level)
    #: — the same side index that carries stair profiles and paths. An
    #: empty mapping = the stage was NOT PRESENT for this snapshot, and
    #: the railing must give the SAME refusal verbatim: "a snapshot
    #: taken before the stage must give the same answer." A field with
    #: a default, not a required one, for exactly this reason.
    railing_path_index: Mapping[str, Any] = field(default_factory=dict)
    # Curtain-wall cells, keyed by the CELL ELEMENT's id: (host id,
    # host record, panel record). An empty dict = the stage did not
    # hand over an index (or handed over schema /1 with no addresses)
    # — panels then take the old path and remain honest atoms.
    curtain_cells: Mapping[str, tuple[str, Any, Any]] = field(
        default_factory=dict)
    # Cell bodies: body-element id -> id of the cell that spawned it. A
    # wall filling a curtain-wall cell exists BECAUSE the cell was
    # assigned a type; there should be no separate op for it —
    # otherwise reassembly would build it twice.
    curtain_cell_bodies: Mapping[str, str] = field(default_factory=dict)
    # Curtain-wall mullions: mullion id -> (host id, host record,
    # mullion record). A mullion lives ON THE GRID LINE and is created
    # by exactly one method — CurtainGridLine.AddMullions(segment,
    # MullionType, oneSegmentOnly) (the reference package's
    # RevitAPI.xml). It is never placed as a family instance under any
    # circumstances, even though by class it IS a FamilyInstance. The
    # host and mullion records are needed in full: they decide whether
    # the mullion is itself spawned by the host's type.
    curtain_mullions: Mapping[str, tuple[str, Any, Any]] = field(
        default_factory=dict)
    # GRID LINES: line id -> (host id, host record, line record,
    # direction). The line IS NOT IN L0 AT ALL — the collector does not
    # gather its category (measured on v13: 122 lines in the index, 0
    # of them among 3153 L0 elements). So its operation is not "lifted
    # from an element," it is SYNTHESIZED from the side index and
    # bound to the host's node.
    curtain_grid_lines: Mapping[str, tuple[str, Any, Any, str]] = field(
        default_factory=dict)
    # Annotations: element id -> side index record (owner view, point
    # IN VIEW COORDINATES, text). An empty dict = the stage was absent,
    # and this DIFFERS from "the stage ran and found nothing": in the
    # first case the honest answer is the old source_contract_gap.
    text_notes: Mapping[str, Any] = field(default_factory=dict)
    # TAGS: element id -> side index record (owner view, head point IN
    # VIEW COORDINATES, TAGGED element, leader, kind, type). An empty
    # dict = the stage was absent, and this DIFFERS from "the stage ran
    # and found nothing": in the first case the honest answer is the
    # old source_contract_gap, verbatim the same as before the wave.
    tags: Mapping[str, Any] = field(default_factory=dict)
    # A pipe/duct's membership in a SYSTEM TYPE. An empty dict = the
    # stage was absent: the op is lifted without system_type, as
    # before the wave, and reassembly will honestly refuse to ground
    # itself when there are several candidates.
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
    """The curve kind from the SIDE index, if a row for this element
    exists there.

    The index is assembled by the ``curve`` stage for walls AND framing
    (``pipeline._STAGE_CATEGORIES``), i.e. a round trip to the bridge
    has already been paid for a beam's row. Before this wave, only
    walls read it, and an arc beam was straightened into a chord even
    though the exact arc sat right next to it in
    ``curve.index.json``.
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
    """§18.1: a non-Line with no expressible arc — an atom, NEVER a
    chord.

    An op whose registry entry has no arc parameter (``create_beam``,
    ``create_pipe``, ``create_duct``, ``create_cable_tray`` — checked
    against ``spec.OPS``) cannot express an arc AT ALL. So the presence
    of an exact arc in the side index does not change the outcome —
    only the reason's text changes: "we don't know what curve that is"
    is one thing, "we know it exactly, and there is nothing to say it
    with" is another. The second is a request to extend the op, the
    first to extend the read; mixing them up loses both.

    Both sources of the fact are needed: ``curve_kind`` in L0 (the new
    capture) and the side-index row (it exists for framing, and on OLD
    L0 where the field does not).
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


def _placement_is_level_based(element: L0Element, context: _Context) -> bool:
    """A family is placed BY LEVEL, not into a host (``OneLevelBased``).

    THE FOURTH CASE OF ONE FAMILY IN THIS FILE, and it is recorded at
    ``_POINT_PLACED_PLACEMENTS`` verbatim: "the producer learned it,
    the consumer with its closed list did not." The first three are
    ``OneLevelBasedHosted`` (2 053 elements), ``TwoLevelsBased``
    (5 337), and a relative at the gate. Here the consumer is not a
    list, but the ROUTING TABLE ``_CANDIDATES``: it decides the lifter
    BY CATEGORY and does not ask about the placement kind at all.

    THE MNVNK K6 MEASUREMENT (22.08.2026), what this cost. All 2 952
    windows of the building are ``OneLevelBased`` with ``host_id =
    null`` and ``host_class = null``; the same model's doors, for
    comparison — 1 230 of 1 230 ``OneLevelBasedHosted`` with
    ``host_class = Wall``. Windows got ``missing_reference`` ("host_id
    is absent"), i.e. the refusal SPOKE ABOUT OUR OWN ROUTE, yet read
    as a fact about the model: "a window with no wall." The wall has
    nothing to do with it — the family is simply not host-based, and
    ``place_family`` expresses and emits such a placement since 12.08
    (``ONE_LEVEL_BASED`` stands first in ``_POINT_PLACED_PLACEMENTS``).

    WHY THE INDEX'S SILENCE IS NOT "YES." No row, a corrupted row, no
    field — all of this is "not measured," and asserting the placement
    kind from it would mean inventing it. We return False and leave
    the old answer verbatim: the same fail-closed-to-old-behaviour as
    with ``host_source is None`` and with a malformed arc in
    ``_wall_arc_param``.
    """
    raw = context.family_placement_index.get(element.element_id)
    if not isinstance(raw, Mapping):
        return False
    try:
        record = FamilyPlacementRecord.from_dict(
            element.element_id,
            raw,
            f"family_placement_index[{element.element_id!r}]",
        )
    except FamilyPlacementPayloadError:
        return False
    return record.placement_type is FamilyPlacementType.ONE_LEVEL_BASED


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

    ``railing_path_index`` is the third sibling, and it is OPTIONAL by
    construction: ``ProfileExtraction.to_dict`` puts in the key only when
    railings were actually captured. A snapshot taken before the capture
    wave of 29.07 does not have the key — and must give the SAME railing
    refusal verbatim, not a new one. That is exactly why an empty mapping
    is returned here, rather than the whole ``profile_index``: in the
    direct (non-envelope) form there is nothing to distinguish record
    dialects, and handing the railing lift someone else's rows would mean
    inventing a path.
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
    """Parse the curtain wall index: cells, bodies, mullions, and grid lines.

    Accepts either the full envelope (``{schema_version, curtain_index,
    failures}``), the bare dict ``{host_id: record}``, or an already
    parsed :class:`CurtainExtraction` — exactly as with the other side
    indexes, so that tools and the pipeline can pass whatever they have on
    hand.

    A broken row is ISOLATED: the index is external data, and one
    unreadable record has no right to bring down the parse of the
    building. Panels of such a host simply will not get cells and will
    become honest atoms.
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
    # codex #4 (2026-07-29, tasks/b8f3v4r97.output of session eeccfb91):
    # ``CurtainWallRecord.__post_init__`` already requires panel_id/mullion_id
    # to be unique WITHIN one host (``_require_unique``) — but panel_id and
    # host_panel_id live in the SHARED, GLOBAL identity space of the
    # document, and the global side of injectivity was not checked at all.
    # Before building cells/bodies, find all hosts whose data conflict
    # globally and isolate them ENTIRELY (not one cell — the very fact of
    # a collision casts a shadow on the whole captured host), rather than
    # letting last-write silently overwrite or lose someone else's
    # legitimate cell.
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
            # Global duplicate panel_id — two DIFFERENT hosts (or two
            # passes over the same data set) claim the same cell.
            conflicted_walls.update(wall_id for wall_id, _ in occurrences)
    for host_panel_id, occurrences in host_panel_by_id.items():
        if len(occurrences) > 1:
            # Body duplicate: several cells claim ONE occupant —
            # "duplicate body" from the adversarial measurement.
            conflicted_walls.update(wall_id for wall_id, _ in occurrences)
        for wall_id, panel in occurrences:
            if host_panel_id == panel.panel_id:
                # Self-reference: a cell occupied by "itself" — has no
                # physical meaning, not merely a rare case.
                conflicted_walls.add(wall_id)
            elif host_panel_id in panels_by_id:
                # Role crossover: this cell's body is the REAL panel_id
                # of SOMEONE ELSE'S cell ("body=foreign panel"). The
                # danger is not in the alias itself (the setdefault below
                # will not let it overwrite someone else's record) — it is
                # that `_lift_one` checks `curtain_cell_bodies` BEFORE
                # `curtain_cells`: another cell's legitimate record would
                # become unreachable, shadowed by a body that is not it.
                # Isolate BOTH sides.
                conflicted_walls.add(wall_id)
                conflicted_walls.update(
                    other_wall for other_wall, _ in panels_by_id[host_panel_id])
            elif host_panel_id in all_wall_ids:
                # Nested curtain-host: the occupant is itself a curtain
                # wall host. Undefined territory (codex #4) — do not alias.
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
                # An isolated host does not take part in cells/bodies at
                # all — its elements fall through to the common placement
                # path and get an honest (not curtain-specific) atom/op,
                # rather than a silently wrong generator_child
                # substitution. The source-id multiset does not lose them:
                # they simply do not take the short path.
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
    # AN OCCUPIED CELL HAS TWO NAMES, AND THE DOCUMENT IS ENTITLED TO KNOW
    # EITHER OF THEM.
    #
    # The index keys the cell by the id of the OCCUPANT (panel_id), while
    # re-extraction of the rebuilt model returns the id of the OCCUPIED
    # panel (host_panel_id) — measurement v12 (idempotence_debug.json): of
    # 20 re-extracted panels, 0 matched panel_id and 20 matched
    # host_panel_id. The keys did not overlap, the re-lift got None and
    # fell through to the common placement path: 0 cell leaves where 20
    # were expected.
    #
    # The second name is added AFTER all the first ones (setdefault), so
    # that one cell's alias can never override another cell's own key.
    # There will not be two leaves from two names: as long as the
    # OCCUPANT is present in the document, the occupied panel is
    # intercepted by the body guard and stays a generator_child — the same
    # thing it already was; the alias fires exactly when the occupant is
    # absent from the document (the same v12 measurement: in the source
    # model both sides are present for all 372 occupied cells, and the
    # leaf must remain single).
    #
    # Global injectivity has already been proven above (conflicting hosts
    # are isolated and never reach bodies/cells), so the setdefault here
    # only guards the remaining, honest case — it is no longer the sole
    # line of defense.
    for body_id, cell_id in bodies.items():
        cell = cells.get(cell_id)
        if cell is not None:
            cells.setdefault(body_id, cell)
    return cells, bodies, mullions, grid_lines


#: Why the grid line did NOT become an operation. The reason must name
#: itself: "the type places it" and "we did not look" are different
#: statements, and only the first says anything about the model.
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
    """Stable id ordering: numeric ones by number, others by string.

    Node order must be deterministic: both the canonical hash of the
    sequence and the order of operations in the program depend on it.
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
    """Grid line -> ``create_curtain_grid_line``, or an honest skip.

    THE LINE IS NOT IN L0: the collector does not gather its category at
    all (measurement v13 — 122 lines in the index, none among the 3153 L0
    elements). So the node is SYNTHESIZED from the side index rather than
    lifted from an element; its ``source_element_id`` is the line's real
    id in the model, so both roads (synthesis in the source model, and
    lifting the same id if re-extraction does return it as an element)
    give ONE AND THE SAME node and one canonical hash. The same lesson as
    the cell with two names.

    A skip is not silence: every outcome has its own named reason, and it
    goes to the diagnostic channel.
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
    # POSITION is a point ON the line: AddGridLine accepts exactly a point
    # that the line passes through. The midpoint of the captured curve
    # lies on it by construction, so the rebuild places the line right
    # where it was taken from.
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
        # The grid line has no type — and an empty string here says
        # exactly that, not "we failed to read the type."
        "type_name": "",
        "params": {
            "host": {"ref": host_node["_id"]},
            "direction": direction,
            "position_mm": position,
        },
        "source_element_id": line_id,
        # Level and anchor are taken IDENTICALLY on both roads — from the
        # host and from the line itself, not from the L0 element, which
        # may not exist.
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


#: Exactly why the mullion is NOT proven to be type-generated. The reason
#: must name itself: "not generated by the type" and "we did not look" are
#: different statements, and only the first says something about the
#: model.
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
    """Curtain wall cell -> ``set_curtain_panel``, or an honest refusal.

    THE RECOGNITION RULE IS STRUCTURAL (INVARIANT #1): a panel is standard
    if its effective type matches the type the host uses to divide the
    grid ITSELF (``AUTO_PANEL`` on the host's type). No lists of familiar
    names: in someone else's model they are called differently, but the
    rule is the same.

    The order of refusals matters exactly as in ``_lift_family_fallback``:
    facts about the element itself first (the cell's body, standard
    subdivision), and only then what we failed to find.
    """

    cell = context.curtain_cells.get(element.element_id)
    if cell is None:
        # The index said nothing about this element. The common placement
        # path still has the right to call it a nested child — this
        # reason must not be lost (measurement of 27.07: 30.37% versus
        # 67.70%).
        return _lift_family_fallback(element, context, nodes_by_source)
    host_id, host, panel = cell

    if panel.address_state is not CellAddressState.OK:
        # not_a_panel is not our own weakness but a fact about the model:
        # the instance occupying the cell (a curtain wall window) is not a
        # Panel, and GetRefGridLines only lives on Panel. Live measurement
        # v4: 50 such cells out of 361.
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
    # STATE, not the presence of a number. A live run of 28.07 (v4) showed
    # the cost of confusing the two: all 195 hosts had a null default
    # type, and the lift honestly refused on 311 cells — but the same null
    # implied three different truths, and there was nothing to tell them
    # apart.
    if host.default_panel_state is DefaultPanelState.NONE:
        # The host does not divide an automatic panel AT ALL: so no cell
        # is type-generated, and every occupied one was assigned by the
        # author. This is a structural conclusion from the fact read, not
        # a guess about it.
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
    # THE LEAF'S TYPE IS THE CELL'S TYPE, NOT THE TYPE OF WHICHEVER OF THE
    # TWO ELEMENTS WAS LIFTED.
    #
    # An occupied cell has two elements and two type names: the occupant
    # has the name of the system wrapper («Стена»), the occupied panel has
    # the name of the type the cell is actually filled with. The operation
    # describes the CELL, and its type is already named in panel_type;
    # leaving the wrapper's name in the leaf would mean that one and the
    # same fact about the model gets canonicalized differently depending
    # on which of the two elements ended up in the document.
    #
    # MEASUREMENT (v12, rebuild #6): for 20 cells lifted from both sides,
    # ``params`` matched BYTE FOR BYTE — host reference, u, v, panel_type
    # — and exactly ``type_name`` diverged («Стена» versus «_Пустая_ Не
    # учитывать_200мм»). That was enough for the canonical hash to never
    # match and for the idempotence comparison to show a divergence where
    # the model is the same one.
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
    # The SAME law as on the forward pass, READ FROM ONE PLACE. Before
    # 10.08 these three numbers stood here as their own copy, even though
    # the line below says «forward polygon bounds» — meaning the copy KNEW
    # it was repeating someone else's law. The cost of divergence here is
    # silent: the element becomes an atom, and no refusal will say so.
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
    from kir.geom import check_holes_relation, ring_normalize
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
        # THE REASON WAS UPDATED ON 09.08.2026, AND THIS MATTERS: from
        # this date `create_stairs` DOES EXPRESS a spiral run (`spiral` ->
        # StairsRun.CreateSpiralRun), so the earlier wording "the op
        # cannot represent a curved run" became untrue — and a wrong atom
        # reason sends people to fix the wrong thing. The reverse pass
        # still cannot: what was captured is the run's PATH (points + arc
        # midpoints), while `spiral` is described by the CENTER and RADIUS
        # of the run ITSELF, and the relationship between the two (offset
        # by the half-width, alignment) IS NOT MEASURED. The center of the
        # PATH's arc can be derived from three points; passing it off as
        # the run's center cannot be done — that would be exactly a silent
        # untruth.
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
    """Dimensions stage envelope -> lift address (id -> string).

    Accepts either a parsed ``DimensionExtraction``, a bare
    ``dimension_index``, or the full ``to_dict()`` envelope. Any
    corruption -> ``{}``, i.e. "no index", i.e. the SAME refusal verbatim:
    a snapshot taken before the stage existed must read as the absence of
    an index, not as an empty index with a different meaning (§18.2:
    absent and empty are different facts, but both must give an HONEST,
    not an invented, answer).
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
    """Reduce the system-membership index to a flat id -> record map."""
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
    """Reduce the annotation side index to a flat id -> record map.

    Accepts a parsed :class:`AnnotationExtraction`, its
    ``text_note_index`` projection, or the full ``to_dict()`` envelope.
    Any corruption -> ``{}``, i.e. exactly the prior behavior: every
    annotation stays an atom with the reason source_contract_gap. The
    refusal is closed: a corrupted index has NO right to turn into
    partially lifted annotation, because "half the texts are in place"
    looks like success and reads as coverage.
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
    """Reduce the tag side index to a flat id -> record map.

    Accepts a parsed :class:`TagExtraction`, its ``tag_index`` projection,
    or the full ``to_dict()`` envelope. Any corruption -> ``{}``, i.e.
    exactly the prior behavior: every tag stays an atom with the reason
    source_contract_gap. The refusal is closed for the same reason as
    with annotation: "half the tags are in place" looks like success and
    reads as coverage.
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
    :class:`kir.decompile.curve_extract.CurveExtraction` (live-verified on
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
        # The working curved wall path above is UNTOUCHED: what lands here
        # is only a wall for which the capture itself said "not
        # straight", and no valid side-index row was found (the index was
        # not gathered, the budget cut the row, the ends diverged). It
        # used to be a silent straight line: §18.1 forbids it exactly as
        # it does for a beam. The condition hinges on a FIELD that frozen
        # L0 does not have, so it changes the behavior of no existing
        # decompile.
        _refuse(
            AtomReason.CURVE_KIND_UNSUPPORTED,
            f"LocationCurve is {element.curve_kind.value!r} and no matching "
            "arc row is available in the curve side index — a chord would "
            "silently straighten this wall")
    # Vertical attributes (audit F6).  base offset: is carried exactly when
    # the value survives CANONICAL rounding — the sole threshold law
    # (_survives_canon_rounding).  A typical wall at level (offset 0) still
    # does not set the field, canonical hashes stay stable; but 0.6 mm no
    # longer gets lost silently, as it used to before 25.08 in six lifters
    # out of ten.
    base_offset = _finite(element.params.get("WALL_BASE_OFFSET"))
    if base_offset is not None and _survives_canon_rounding(base_offset):
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
        # THE LIFT DOES NOT LIFT AN ANCHOR THAT PUTS THE TOP BELOW THE BASE.
        # Found by rebuilding a real building on 27.07: a chunk of 250 ops
        # rolled back ENTIRELY with «Верх стены находится ниже, чем
        # подошва стены» because of TWO walls at 693 (base +2185 with top
        # −300).  The hypothesis "anchoring to its own level = height not
        # anchored" was refuted by measurement: of 94 such walls, 2 are
        # impossible, the other 92 are legitimate — the rule must be
        # geometric, not about levels coinciding.  When anchoring is
        # impossible, it is more honest to give the measured height that
        # the wall actually has (WALL_USER_HEIGHT_PARAM is already lifted
        # above) than a program that Revit will refuse to execute.
        base_level = context.levels_by_id.get(str(element.level_id))
        base_elev = _finite(getattr(base_level, "elevation_mm", None)) or 0.0
        top_elev = _finite(getattr(top, "elevation_mm", None)) or 0.0
        base_abs = base_elev + (_finite(params.get("base_offset_mm")) or 0.0)
        top_abs = top_elev + (top_offset or 0.0)
        if top_abs > base_abs:
            params["top_level"] = {
                "by": "name", "value": top.name, "_id": top.id}
            if top_offset is not None and _survives_canon_rounding(top_offset):
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
    """The sketch side-index row for the element, or None.

    Parsing is strict and the SAME on both paths (polygon and contour): a
    broken row means the profile is absent, not a reason to guess the
    shape.
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
    """Cannot be expressed as a polygon: there is an arc, or a loop of two
    segments."""

    if not record.profile_available or record.exterior_loop is None:
        return False
    loops = (record.exterior_loop,) + tuple(record.holes)
    for loop in loops:
        if len(loop.points_mm) < 3:
            return True
        if any(kind is CurveKind.ARC for kind in loop.curve_kinds):
            return True
    return False


#: An arc in the profile is point, midpoint, point. Exactly these three
#: numbers live in the sketch side index (``ProfileLoop.arc_midpoints_mm``),
#: and exactly from them ``bulge`` of the contour op is obtained. The
#: formula is the EXACT INVERSE of ``contour.bulge_midpoint``: that one
#: builds the midpoint as
#: ``chord_mid - normal * (bulge * chord / 2)``, hence
#: ``bulge = -2 * dot(mid - chord_mid, normal) / chord``.
#:
#: Verified on a measurement (28.07): 3051 arcs from two parses, the worst
#: residual of the reverse pass is 2.4e-8 mm. Every arc is recomputed
#: BACKWARD by its own function and cross-checked — a discrepancy greater
#: than 0.1 mm is a refusal, not "close enough."
_ARC_BULGE_TOL_MM = 0.1

#: NOT AN INDEPENDENT NUMBER, BUT A REFERENCE. The ring limit of the
#: CONTOUR must match what the sublanguage accepts
#: (`contour._validate_shape`), otherwise the lifter will assemble a shape
#: that the compiler will immediately reject — and the diagnosis will be
#: about the contour, not about us. Before 10.08 a private 64 stood here.
_CONTOUR_MAX_POINTS = _geom.MAX_RING_POINTS


def _bulge_from_midpoint(
    p0: Sequence[float], p1: Sequence[float], mid: Sequence[float],
) -> float | None:
    """DXF bulge of arc p0→p1, passing through ``mid``, or None."""

    dx, dy = float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1])
    chord = math.hypot(dx, dy)
    if chord < 1e-9:
        return None
    nx, ny = -dy / chord, dx / chord
    cx, cy = (float(p0[0]) + float(p1[0])) / 2.0, (float(p0[1]) + float(p1[1])) / 2.0
    sagitta = -((float(mid[0]) - cx) * nx + (float(mid[1]) - cy) * ny)
    return 2.0 * sagitta / chord


def _contour_shape(loop: Any) -> dict[str, Any] | None:
    """Profile loop -> ``poly`` shape of the contour op, or None.

    A loop of TWO segments (a circle: two arcs) cannot be expressed as
    ``poly`` — the shape needs at least three points. Such an arc is CUT
    IN HALF at its own captured midpoint: this is not an approximation but
    the same curve, recorded as two arcs (measurement: 126 such loops on
    «демо-v3», all circles). The half bulge = tan(atan(b)/2), because the
    sector is split in half.
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
        # The arc's threshold and its ceiling belong to the SUBLANGUAGE,
        # not to the lifter: recording an arc that CONTOUR will later
        # reject means handing over a program that fails on its own
        # validation. Before 10.08 both numbers stood here as a copy.
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
        # Cross-check by the REVERSE pass with their own function: bulge
        # must return the same midpoint, otherwise we recorded the wrong
        # arc.
        from kir.contour import bulge_midpoint
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
    """Sketch side-index row -> ``contour`` region (or a refusal).

    ONE function for all consumers of CONTOUR, and this is not a matter of
    taste: on 09.08 the ceiling became the second contour operation, and a
    second instance of these same four checks would mean two answers to
    one question, "does the profile express as a contour". Having
    diverged, they would give different atoms on identical profiles — the
    same class of bug as two category tables (ceiling/railing, 29.07) and
    three section dicts (fold, 28.07).

    Both refusals are SHAPE refusals (`_SHAPE_REFUSALS`), i.e. "the
    element is not of the shape this op is about"; nothing is said here
    about value or reference, and they are entitled to fall through to
    `place_family`.
    """

    loops = (record.exterior_loop,) + tuple(record.holes)
    shapes = [_contour_shape(loop) for loop in loops]
    if any(shape is None for shape in shapes):
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            f"профиль не выражается контуром: петля вне границ "
            f"{_geom.MIN_RING_POINTS}..{_CONTOUR_MAX_POINTS} точек "
            f"или дуга без точной середины")
    # `shapes` is the outer ring PLUS holes, so the limit here is not an
    # independent nine but `1 + MAX_HOLES`. A bare 9 next to the text "up
    # to 8 openings" read like a typo and held up only because nobody
    # touched it: moving MAX_HOLES would have surely left this 9 forgotten.
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
    """Floor whose profile cannot be expressed as a polygon -> ``create_floor_by_contour``.

    The occasion is measured, not assumed: on «демо-v3», 155 out of 235
    floor profiles carry arcs or a loop of two segments, and all of them
    were ``unsupported_geometry`` atoms — the op is written for them and
    passes the gate, but its name never once appeared in the decompile.
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
    # A profile with an ARC or a loop of two segments cannot be expressed
    # as a polygon — but can be expressed as a contour, and the op for
    # this has existed from the start. Before this wave such a floor
    # remained an atom: `create_floor_by_contour` was never once mentioned
    # in the decompile.
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
    # P1 DOF-completeness: floor offset from the level (51% of the «демо»
    # floors). codex #8 (2026-07-29): the threshold used to be independent,
    # >=1mm, which meant 0.4-0.999mm got lost silently; now the sole law is
    # the same grid by which FidelityCanon rounds any _mm field
    # (_survives_canon_rounding); absent is the historical byte-identical
    # emission ONLY for values that the canon itself already flattens to
    # zero.
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
    """Ceiling whose profile cannot be expressed as a polygon -> ``create_ceiling``.

    THERE IS NO SEPARATE OPERATION HERE, AND THAT IS THE DIFFERENCE FROM
    THE FLOOR, not an oversight: for a floor the contour shape arrived as
    its own op (`create_floor_by_contour`), for a ceiling — as a SECOND
    INPUT of the same operation. So the op's name is the same, and the
    branches are distinguished by the set of fields: `contour` OR
    `outline`+`holes`, exactly one of the two (KIR-P007). Emitting both
    would mean handing the compiler a program it must reject — that is,
    claiming coverage that does not build.

    The offset is read from the same CEILING_HEIGHTABOVELEVEL_PARAM as in
    the forward branch: the parameter is a property of the CATEGORY, not
    of the way the shape is given.
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
    """Ceiling by the reverse pass (wave/arch, 2026-07-29).

    The mechanics are exactly the same as for a floor: a closed profile
    from the sketch side index + level + type. There are two differences,
    and both are measured, not chosen.

    1. The offset is read from CEILING_HEIGHTABOVELEVEL_PARAM (6/6), not
       from FLOOR_HEIGHTABOVELEVEL_PARAM. The parameter's name is part of
       the category's identity, and the wrong name here would silently
       return zero.
    3. CONTOUR (09.08.2026). A profile with an ARC cannot be expressed as
       a polygon, and until today such a ceiling remained an
       `unsupported_geometry` atom — "the op cannot handle this shape." On
       the morning of 09.08 that stopped being true: `create_ceiling`
       gained a second shape input, `contour` of kind `region`
       (ops_arch.py), i.e. the entire CONTOUR sketch sublanguage. Capture
       itself did not have to change BY A SINGLE LINE: the sketch side
       index has been carrying ceilings since 29.07 (`sketch_extract`,
       category in `_STAGE_CATEGORIES`) and stores, for every loop, both
       the segment kind and the arc midpoint — exactly the three numbers
       from which the floor assembles `bulge`. So this was not a capture
       gap but an unwritten branch, and this is exactly the case where the
       lifter MAY be written.

       The branch emits `contour` INSTEAD of `outline`/`holes`, not
       alongside it: a region has its own holes, and holding both
       descriptions at once is typed KIR-P007 (compiler.py). The polygonal
       path is left untouched down to the byte: a ceiling without arcs
       must give the previous node verbatim, otherwise the loop would
       break open on every already-decompiled building.

    2. THE HONESTY BOUNDARY THE READER NEEDS TO KNOW: ceiling slope IS NOT
       RECOVERED by this lift and cannot be recovered. In frozen L0 there
       is no slope in any form: no BuiltInParameter with that meaning
       exists (verified by compilation — neither CEILING_SLOPE nor any
       related name exists in any of the six versions), and the sketch
       side index stores the contour FLAT, in [x,y], with no slope arrow.
       So for a sloped ceiling this lift returns a flat one, and there is
       nothing with which to tell one from the other from the present
       snapshot — there is nothing to hang a guard on, and inventing a
       parameter name for the appearance of a guard would be worse than
       silence. This is closed NOT here but on the extraction side: until
       the extractor starts capturing the slope arrow, "ceilings round
       trip" is an unproven claim, and the wave report records it as such.
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
    """Railing by the reverse pass (wave/arch 29.07 + reading hookup 03.08).

    THE HISTORY OF THIS FUNCTION IS HALF ITS MEANING, so it is given here
    in full.

    On 29.07 the lift was written, and it honestly refused ALWAYS:
    measurement K2 showed that all 203 OST_StairsRailing lie in L0 as
    ``bbox_only``/``point`` with empty ``params`` and ``host_id: null`` —
    no path, no host, no position. The refusal was not a defect of the
    lift but an exact diagnosis of the EXTRACTION side.

    The same wave, the extraction side ACCEPTED the diagnosis:
    ``sketch_extract.RailingPathRecord`` captures ``Railing.GetPath()``,
    ``HasHost``/``HostId``, and ``STAIRS_RAILING_BASE_LEVEL_PARAM``, and
    ``pipeline._STAGE_CATEGORIES['sketch']`` feeds the stage both railing
    categories. Capture went to prod and has been gathering data since
    29.07.

    AND THE LIFT DID NOT READ IT. ``_Context`` knew ``stairs_run_path_index``
    and did not know ``railing_path_index``; the function below refused on
    ``element.host_id``, i.e. on the L0 row, while ``sketch.index.json``
    from the same parse already held ready-made paths. Measurement of
    03.08 on k2_ar_rd_v9: 31 captured rows, 28 free-standing railings with
    a path, a base level, and a plane EXACTLY at the level elevation; all
    31 are straight (``curve_kinds`` = line). This is exactly the class of
    defect for which the reason ``source_contract_gap`` was established:
    the op exists, the reading exists, but there is no wire between them.

    WHAT REMAINS A REFUSAL AND WHY (the boundaries have not moved):

    * A STAIR railing (``has_host``) — the placement position
      (``RailingPlacementPosition``) IS UNREADABLE: nowhere in the whole
      member list of ``Autodesk.Revit.DB.Architecture.Railing`` across all
      six versions is there a getter; it exists only as an argument to
      ``Create`` and as three enumeration fields. Moving such a railing to
      ``variety=path`` would mean SILENTLY LOSING THE HOST: the place
      looks the same, but the stair no longer owns its railing.
    * An ARC in the path — ``create_railing`` has no arc parameter, and a
      chord is a different railing.
    * A PATH PLANE ABOVE/BELOW THE LEVEL — ``Railing.Create(doc, CurveLoop,
      typeId, baseLevelId)`` places the path AT the level, the operation
      has no offset.

    * A SNAPSHOT WITHOUT THE STAGE — the SAME refusal VERBATIM (see the
      first branch below).
    """
    raw = context.railing_path_index.get(element.element_id)
    if raw is None:
        # THE SNAPSHOT WAS TAKEN BEFORE THE CAPTURE STAGE — the previous
        # answer VERBATIM. Do not touch the two lines below: a parse taken
        # before 29.07 must give the same refusal with the same reason,
        # not a new one.
        if element.host_id:
            # The host is known — but one host is not enough: the overload
            # Railing.Create(doc, hostId, typeId, position) requires a
            # POSITION, and it is captured by nothing in L0. Setting
            # Treads by default would mean silently placing the railing in
            # the wrong spot.
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
        # The placement position IS UNREADABLE: the full member list of
        # Autodesk.Revit.DB.Architecture.Railing across all six versions
        # contains no RailingPlacementPosition getter — it appears only as
        # an argument to two Create overloads and as three enumeration
        # fields. Moving a stair railing to variety=path would mean
        # SILENTLY LOSING the host: the railing would stop belonging to
        # the stair while appearing to stay in place.
        _refuse(
            AtomReason.MISSING_PARAMETER,
            "hosted railing has no readable RailingPlacementPosition "
            "(Railing exposes no getter on any shipped version)")
    if record.has_host is None:
        # `None` means "COULD NOT BE READ", and the record is deliberately
        # three-valued precisely so that this does not collapse into "no
        # host". A free-standing railing born of unknown state is a
        # silent loss of the host at exactly the same cost as the branch
        # above; hence a refusal here, not `not`.
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
    # A degenerate segment fails FORWARD (authoring_validation, threshold
    # 1 mm: Revit will not build such a curve). Catching it here means
    # giving back an honest atom instead of a program the compiler would
    # reject anyway.
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
    # THE ELEVATION OF THE PATH PLANE. Railing.Create(doc, CurveLoop,
    # typeId, baseLevelId) places the path AT THE LEVEL; the operation has
    # not a single parameter for an offset from the level. A railing whose
    # plane departs from the level would come back at a different
    # elevation — silently and invisibly (on a 59-story tower the outline
    # would look correct). Measurement K2: for all 28 free-standing
    # railings in the parse, plane_z is exactly equal to the level
    # elevation, so the refusal below is honest, not prohibitive.
    if record.plane_z_mm is None:
        _refuse(
            AtomReason.MISSING_GEOMETRY,
            "railing path plane elevation was not read")
    # There is ONE grid — the same CANON_MM by which the canon rounds
    # every ``*_mm`` field. Introducing its own threshold would mean
    # introducing a second judge of what counts as "the same elevation."
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
    # P1 DOF-completeness (fidelity audit 2026-07-21): column verticality
    # follows the same discipline as the wall, and since 25.08 it is ONE
    # law, not two similar-looking numbers: _survives_canon_rounding; an
    # unresolvable top level is an honest atom.
    base_offset = _finite(element.params.get("FAMILY_BASE_LEVEL_OFFSET_PARAM"))
    if base_offset is not None and _survives_canon_rounding(base_offset):
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
        if top_offset is not None and _survives_canon_rounding(top_offset):
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
    # The beam READS the curve side index. Previously this function
    # accepted the context and never opened it: an arced beam rode out as
    # a chord even though the ``curve`` stage requests
    # OST_StructuralFraming on a par with walls, and its exact arc already
    # sat in curve.index.json.
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
    """Text annotation -> ``create_text``.

    ALL three required inputs come from the annotation side index, none
    from the L0 row: the owning view (``Element.OwnerViewId``), the point
    in VIEW COORDINATES, and the text itself (``TextElement.Text``). The
    point is projected on the bridge by the same formula the forward pass
    uses to materialize it back (``docspace.emit_view2d_to_xyz_cs``), so
    the loop closes by identity, not by coincidence.

    No index -> the SAME refusal verbatim. This is not caution but a
    condition of comparability: every snapshot taken before the stage
    existed must give the same atom with the same reason, otherwise the
    coverage history stops being a history.
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
        # Empty text is not "an empty string by default" but the absence
        # of content: create_text requires content, and substituting ""
        # would mean inventing a source.
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            f"текстовое примечание без содержания (element_id={element.element_id!r})")

    # THE ONLY named L1 reference dialect: {by:"name", value, _id}. The
    # "by element_id" form does not exist in L1, and this is not a
    # limitation but a property: the rebuild looks up the object BY NAME,
    # and keeps the id only as evidence of what it was in the source
    # document.
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
    """Tag -> ``create_tag``.

    ALL three required inputs come from the tag side index, none from the
    L0 row: the owning view (``Element.OwnerViewId``), the HEAD point in
    view coordinates (``TagHeadPosition``, projected on the bridge by the
    view's basis), and the TAGGED element (``TaggedLocalElementId`` before
    2022 / ``GetTaggedLocalElementIds`` from 2022 — a seam resolved in
    ``tag_extract``).

    FIVE REFUSALS THIS LIFTER HAS NO RIGHT TO AVOID.

    1. No index -> the SAME ``source_contract_gap`` VERBATIM. This is not
       caution but a condition of comparability: every snapshot taken
       before the stage existed must give the same atom with the same
       reason.
    2. The tagged element is not among those read -> ``missing_reference``
       with ITS id in the text. Silently binding the tag to a similar
       element would be the worst thing to do here: it would pass the L1
       schema and look like coverage, while in fact being an invented
       source (§18.1).
    3. A room/area/space tag is ``SpatialElementTag``, while the forward
       pass can build EXACTLY ``IndependentTag.Create``
       (``authoring._emit_tag``). The rebuild would construct the wrong
       element class, and this is ``unsupported_forward_signature``, not
       "almost the same".
    4. A tag WITH A LEADER: for such a tag the seventh argument of
       ``IndependentTag.Create`` means the LEADER END, not the head (the
       verbatim Autodesk wording, identical in 2021 and 2026), while what
       was read is the head.
    5. A rotated tag: the emitter hard-codes ``TagOrientation.Horizontal``
       unconditionally. Straightening is invisible to a comparison by head
       position — so it must be NAMED here, not discovered later.
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

    # THE TAG'S KIND IS NO LONGER A REFUSAL (13.08.2026). A refusal used to
    # stand here — "the forward pass builds a tag in a single way,
    # IndependentTag.Create" — honest, naming the route, and it waited for
    # the forward pass: `authoring._emit_tag` distinguishes the target in
    # C# and builds `NewRoomTag`/`NewSpaceTag`/`NewAreaTag` (all 6/6 on
    # reference assemblies, controls CS1061/CS7036 — see
    # `tests/test_spatial_tag_is_its_own_class.py`).
    #
    # THE COST OF THE REFUSAL REMOVED BY THIS LINE IS MEASURED: 7,067
    # elements on `len_ar_me_r24_v1` — the largest cause of
    # `unsupported_forward_signature` on the building. The refusals below
    # STILL REMAIN for a spatial tag too: the leader (a point would mean
    # the leader's end) and implicit orientation. There is nothing left to
    # check about the kind here — the class is decided by the TARGET, and
    # Revit decides that.
    if record.get("tag_family") not in TAG_FAMILIES:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"род марки {record.get('tag_family')!r} не из закрытого списка "
            f"{sorted(TAG_FAMILIES)}: читатель увидел то, чего словарь не "
            "знает, и молча счесть это независимой маркой нельзя")

    # A LEADER CHANGES THE MEANING OF THE POINT ITSELF, and this is not
    # our guess but the verbatim Autodesk wording about the seventh
    # argument of ``IndependentTag.Create`` — the same one in 2021 and in
    # 2026, in both overloads (RevitAPI.xml, param "pnt"):
    #
    #   "For tags without leaders, this point is the position of the tag head.
    #    For tags with leaders, this point is the end point of the leader, and
    #    a leader of default length will be created from this point to the
    #    tag head."
    #
    # That is, `at` is the HEAD only for a tag without a leader. The stage
    # reads ``TagHeadPosition``, and for a tag WITH a leader the rebuild
    # would place the LEADER END where the head used to be, while moving
    # the head off by the default leader length. The shift is silent: a
    # comparison by head position does not see it, and the tag would be
    # counted as coverage.
    #
    # There is nothing to read the leader end with, without a new wave:
    # ``GetLeaderEnd`` DOES NOT EXIST in 2021 (trap index: NEW IN 2022) and
    # from 2023 it is documented to throw when the leader is not
    # free-ended or is not visible. This is a specification for the next
    # wave, and today it is a named refusal.
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

    # THE REFERENCE IS INTRA-PROGRAM, like the host of a door: the rebuild
    # must connect two NODES, not remember someone else's ElementId. The
    # target node can itself be an atom — then the reference honestly
    # points at something unbuilt, and that is visible.
    #
    # The leader is ABSENT from the parameters, and this is not an
    # omission: the forward emitter reads `at` without a `leader` key
    # exactly as "no leader" (`op.get("leader")`), and a tag WITH a leader
    # never reaches here at all — see the refusal above.
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
    """Dimension -> ``create_dimension``.

    ALL three required inputs come from the dimension side index, none
    from the L0 row: the owning view (``Element.OwnerViewId``), a point ON
    THE DIMENSION LINE in view coordinates, and the ELEMENTS between which
    it is drawn (``Dimension.References`` -> ``Reference.ElementId``).

    WHY ONE POINT IS EXACTLY ENOUGH. For the forward pass, ``line_at`` is
    the ANCHOR through which the line passes; it takes the direction from
    the normal of the first reference. ``Dimension.Curve`` is documented
    as ALWAYS unbounded, and the position along the line is emergent
    (``authoring._emit_dimension``). So any point on the line closes the
    loop by identity, not by coincidence.

    FOUR REFUSALS THIS LIFTER HAS NO RIGHT TO AVOID.

    1. No index -> the SAME ``source_contract_gap`` VERBATIM, the same
       text from the registry. A condition of comparability: every
       snapshot taken before the stage existed must give the same atom
       with the same reason, otherwise the coverage history stops being a
       history.
    2. The dimension's shape is not LINEAR -> ``unsupported_forward_signature``.
       The forward pass builds a dimension in EXACTLY one way,
       ``doc.Create.NewDimension(view, Line, ReferenceArray)``, and that
       is a linear dimension. A radial/angular/arc-length dimension would
       be rebuilt as something it was not.
    3. Even one measured element is not found among those read ->
       ``missing_reference`` WITH ITS id in the text. Silently dropping
       the reference or substituting a similar element would be the worst
       thing to do here: a dimension between OTHER elements would pass
       the L1 schema and look like coverage, while in fact being a
       different number (§18.1).
    4. Fewer than two references -> ``source_contract_gap``: there is
       nothing to measure.

    WHAT THIS LIFTER DOES NOT PROMISE, AND THIS IS NAMED, NOT HIDDEN.
    ``refs`` carries ELEMENTS, while ``NewDimension`` requires GEOMETRIC
    references; WHICH FACE to take is decided by the forward pass's own
    traversal. So a match of the NUMBER after rebuild by this lifter is
    not guaranteed and cannot be guaranteed by anything readable offline.
    The forward pass gates the measured value itself
    (``_emit_dimension``, 09.08), so a divergence becomes its own typed
    refusal, not silent coverage.
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

    # THE REFERENCES ARE INTRA-PROGRAM, like the host of a door and the
    # target of a tag: the rebuild must connect NODES, not remember
    # someone else's ElementId. The target node can itself be an atom —
    # then the reference honestly points at something unbuilt, and this is
    # visible, not hidden.
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
    # A STRIP FOOTING IS NOT A COLUMN FOOTING, AND NOW THIS IS CHECKED.
    #
    # `reverse_contract` for `create_wall_foundation` promises: such an
    # element is a typed atom, NEVER silently re-emitted as a column
    # footing. Before this wave the promise was held not by code but by
    # Revit's behavior: `WallFoundation` has no `LocationPoint`, so
    # `geom_kind` cannot become POINT, so the branch below never fires. A
    # coincidence, not an invariant — the same class as a test that passes
    # thanks to its fixture.
    #
    # The check stands BEFORE the geometry parse deliberately: it is about
    # the element's CLASS, not about what Revit put in its geometry, and
    # it must hold even if a strip footing gains a point tomorrow.
    #
    # THE DISTINGUISHER is `host_source`, not "a host exists at all". A
    # refusal on a non-empty `host_id` would reject a footing on a face or
    # a work plane — exactly the element the `isolated` branch was written
    # for — that is, it would buy honesty at the price of working
    # coverage. In frozen L0 a non-empty `host_id` additionally PROVES
    # `FamilyInstance`: no other branch filled it. So an old snapshot must
    # give the previous answer verbatim, and `host_source is None`
    # ("not measured") is not a refusal.
    #
    # WHY `NO_LIFTER`, NOT `SOURCE_CONTRACT_GAP`. The reason must be the
    # truest one, not the first one that fits, and it must address the
    # WORK. Before the capture wave, what was missing was READING
    # (`WallFoundation.WallId` was not read at all) — then source-gap
    # would have been correct. Now the reading brings both the wall and
    # the class, `create_wall_foundation` sits in `spec.OPS`, and the only
    # missing link is THE LIFTER ITSELF. `source_contract_gap` would send
    # someone to fix a reading that is already fixed.
    #
    # The reason is deliberately NOT in `_SHAPE_REFUSALS` — and that too is
    # a decision: a shape refusal would hand the strip footing to
    # `place_family`, and that is not "partial success" but loss of the
    # object. Today's answer for a bbox-only foundation
    # (`MISSING_GEOMETRY`) is a shape refusal, i.e. it opens exactly that
    # road.
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
    # explicit sill.  The threshold is the same sole law of canonical
    # rounding as for floors and walls: a typical door at level does not
    # set the field, and 0.6 mm is no longer dropped (before 25.08 an
    # independent literal >= 1.0 stood here).
    sill = _host_level_sill(element, context, insertion)
    if _survives_canon_rounding(sill):
        params["sill_mm"] = _bounded_number(sill, "create_door", "sill_mm")
    # Swing/mirror state (audit F5): absent/all-False -> byte-stable params.
    params.update(_hosted_flip_params(element, context))
    return _op_node(element, "create_door", params, anchor=insertion)


def _lift_window(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    # PLACEMENT KIND IS A FACT ABOUT THE ELEMENT, AND IT IS ASKED FIRST.
    #
    # The same order as for the curtain-wall door below in `_lift_door`:
    # first "what kind of element is this", and only then "what did we
    # fail to find". A window of a family placed by level is not a window
    # without a host, but an element of a DIFFERENT PLACEMENT KIND, and
    # `create_window`'s signature does not cover it: `host` is required
    # for it, and such an instance has no host WHATSOEVER (measurement
    # MNVNK K6: 2,952 out of 2,952).
    #
    # The refusal is a SHAPE refusal deliberately (`_SHAPE_REFUSALS`): this
    # is exactly "the element is not of the shape this op is about", and it
    # is entitled to fall through to `place_family`. The previous
    # `missing_reference` was not let into the fallback — and was, on top
    # of that, WRONG on the merits, because it described our own route in
    # the language of a fact about the model.
    #
    # `_lift_family_fallback` itself will sort out the 2,952, and sort them
    # correctly: it checks nesting FIRST, so 2,364 counted inserts
    # («Условный стеклопакет», each with a non-empty `super_component_id`)
    # will become `generator_child` and be credited to the parent, while
    # 588 real windows and balcony door units will become operations. The
    # reason `generator_child` also OVERRIDES ours
    # (`_FALLBACK_REASONS_THAT_WIN`), so an insert will name itself an
    # insert, not "an unsuitable signature".
    if _placement_is_level_based(element, context):
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "семейство окна размещается ПО УРОВНЮ (OneLevelBased), а не в "
            "хозяина: у create_window параметр host обязателен, и уровневое "
            "размещение его подпись не выражает")
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
    from kir.geom import check_holes_relation, ring_normalize

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
    # 30.07: capture of Room.Location started working. Before it, `p0_mm`
    # was null for EVERY room across all 55 saved parses — the same API
    # member that killed group reading also cost every room its point.
    # Source #1, for which `_room_centre` had been written in advance,
    # finally exists.
    #
    # Not wiring it up would mean rebuilding the room NOT WHERE it stands.
    # For a non-convex outline (L-shaped, a corridor, a room with a
    # notch), the derived center can lie OUTSIDE the room, and then the
    # rebuild creates it in a neighboring space or does not create it at
    # all. Measurement on a tower: 2153 divergences out of 2153 lifted
    # rooms, deviations up to 5339 mm.
    #
    # Trust is not blind: `_room_centre` checks that the point is finite
    # and lies inside the outline with margin, and silently falls back to
    # a deterministic variant if the snapshot has aged relative to the
    # boundaries.
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
    # 🔴 WHAT THE ENDS ARE CONNECTED BY IS ASKED FIRST. Measurement of
    # 25.08.2026: the grid axis was described by two ends and nothing
    # else, and an arced one arrived STRAIGHT. There was no red anywhere:
    # the op's postcondition "curve endpoints == p0/p1 (±5 mm)" matches a
    # CHORD against the arc EXACTLY, meaning the witness could not turn
    # red on exactly the defect it exists for.
    #
    # `_lift_grid` was the ONLY curve lifter out of seven that did not ask
    # the curve's kind: the six neighbors (beam, pipe, duct, cable tray,
    # conduit, partition) call `_refuse_non_line_curve`.
    #
    # An arc CANNOT BE EXPRESSED here — the language has no such op, and
    # adding one is separate work. What is closed is the SILENCE: the gap
    # in the language remains a gap, but stops being a silent lie.
    #
    # `None` means the snapshot was taken before this wave, the kind was
    # NOT MEASURED. A refusal on it would be a refusal out of ignorance
    # and would declare every snapshot in the corpus invalid at once.
    род = getattr(grid, "curve_kind", None)
    if род is not None and род != "line":
        _refuse(
            AtomReason.UNSUPPORTED_GEOMETRY,
            f"ось идёт кривой рода «{род}», а `create_grid` выражает только "
            f"прямую: хорда совпала бы с дугой по концам и уехала бы молча")
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
    # 🔴 THE SEGMENT'S KIND, NOT A PARAMETER VALUE (04.09.2026, closing the
    # declared gap of `create_pipe_placeholder`). Before this wave EVERY
    # row of the category went to `create_pipe` unconditionally, and a
    # placeholder was rebuilt as a FULL-FLEDGED segment — the one kind
    # that lied silently here, instead of refusing.
    #
    # THE COMPARISON WITH `is True` IS MANDATORY. The field is
    # three-valued, and `bool("false")` is true: a parse that brought a
    # string instead of a boolean would declare every pipe a placeholder.
    # The schema rejects such a string earlier (`from_dict`), but the
    # comparison is still written against the value, not against
    # truthiness.
    #
    # `None` — "NOT MEASURED" — behaves AS BEFORE, and this is not a
    # concession. The same law already governs `curve_kind` one level up:
    # refusing without evidence would mean tearing down every segment of
    # every parse taken before today, and we have no evidence about it
    # either way. What remains unknown for an old snapshot is named in the
    # reverse-pass manifest, not passed over in silence.
    placeholder = element.is_placeholder is True
    op_name = "create_pipe_placeholder" if placeholder else "create_pipe"
    _refuse_non_line_curve(element, context, op_name)
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "pipe_type": _catalog_ref(element),
    }
    # The placeholder HAS NO DIAMETER IN THE REGISTRY: `create_pipe_placeholder`
    # does not declare it. Putting it here would mean handing the compiler
    # a parameter the op does not know — a refusal instead of a segment.
    if not placeholder:
        params["diameter_mm"] = _bounded_param(
            element,
            "RBS_PIPE_DIAMETER_PARAM",
            "create_pipe",
            "diameter_mm",
        )
    # The system type comes from the SIDE index, not from the L0 row:
    # system membership is a reference to another element, while the
    # extraction whitelist is purely geometric. No index -> no key, and
    # the op stays exactly as it was before this wave.
    system = context.mep_systems.get(element.element_id)
    if system and system.get("system_type_id") and system.get("system_type_name"):
        params["system_type"] = {
            "by": "name",
            "value": str(system["system_type_name"]),
            "_id": str(system["system_type_id"]),
        }
    return _op_node(element, op_name, params)


def _lift_duct(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    p0, p1 = _curve(element, dimensions=3)
    # 🔴 THE SEGMENT'S KIND, NOT A PARAMETER VALUE (04.09.2026, closing the
    # declared gap of `create_duct_placeholder`). Before this wave EVERY
    # row of the category went to `create_duct` unconditionally, and a
    # placeholder was rebuilt as a FULL-FLEDGED segment — the one kind
    # that lied silently here, instead of refusing.
    #
    # THE COMPARISON WITH `is True` IS MANDATORY. The field is
    # three-valued, and `bool("false")` is true: a parse that brought a
    # string instead of a boolean would declare every pipe a placeholder.
    # The schema rejects such a string earlier (`from_dict`), but the
    # comparison is still written against the value, not against
    # truthiness.
    #
    # `None` — "NOT MEASURED" — behaves AS BEFORE, and this is not a
    # concession. The same law already governs `curve_kind` one level up:
    # refusing without evidence would mean tearing down every segment of
    # every parse taken before today, and we have no evidence about it
    # either way. What remains unknown for an old snapshot is named in the
    # reverse-pass manifest, not passed over in silence.
    placeholder = element.is_placeholder is True
    op_name = "create_duct_placeholder" if placeholder else "create_duct"
    _refuse_non_line_curve(element, context, op_name)
    params: dict[str, Any] = {
        "p0_mm": p0,
        "p1_mm": p1,
        "level": _level_ref(element.level_id, element.level_name),
        "duct_type": _catalog_ref(element),
    }
    if not placeholder:
        params["diameter_mm"] = _bounded_param(
            element,
            "RBS_CURVE_DIAMETER_PARAM",
            "create_duct",
            "diameter_mm",
        )
    # The system type comes from the SIDE index, not from the L0 row:
    # system membership is a reference to another element, while the
    # extraction whitelist is purely geometric. No index -> no key, and
    # the op stays exactly as it was before this wave.
    system = context.mep_systems.get(element.element_id)
    if system and system.get("system_type_id") and system.get("system_type_name"):
        params["system_type"] = {
            "by": "name",
            "value": str(system["system_type_name"]),
            "_id": str(system["system_type_id"]),
        }
    return _op_node(element, op_name, params)


#: Host category -> the opening kind PROVEN BY IT. The table is closed:
#: a kind derived from anything other than the host category would be a
#: guess. `OST_Ceilings` is here because a ceiling is a flat host just
#: like a floor slab and a roof.
_OPENING_HOST_VARIETY: Mapping[str, str] = MappingProxyType({
    "OST_Walls": "wall_rect",
    "OST_Floors": "host_face",
    "OST_Roofs": "host_face",
    "OST_Ceilings": "host_face",
})

#: 🔴 MEASUREMENT OF 04.09.2026 FROM THE TRAP INDEX, NOT FROM MEMORY. The
#: type `Autodesk.Revit.DB.Opening` has EXACTLY SEVEN members across all
#: six versions: BoundaryCurves · BoundaryRect · Host · IsRectBoundary ·
#: IsTransparentIn3D · IsTransparentInElevation · SketchId (the last only
#: 2022+). The cut direction is NOT among them. This is not "we do not
#: read it" — it is "there is nothing to read", and so `host_face` will
#: not become the forward pass by any reading wave.
_OPENING_CUT_HAS_NO_GETTER = (
    "направление реза (vertical/perpendicular) не читается НИ ОДНИМ членом "
    "Opening (их семь на всех шести версиях, замер по индексу ловушек): "
    "вертикальный и перпендикулярный совпадают только на плоском носителе, "
    "а на скате дают РАЗНЫЕ проёмы, и подставить один за автора значило бы "
    "построить не то и промолчать")


def _lift_opening(
    element: L0Element,
    context: _Context,
    nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Opening -> ``create_opening``, THE KIND IS PROVEN BY THE HOST.

    Closes the declared capture gap PARTIALLY and says so out loud —
    exactly like the railing, where only ``variety=path`` is inverted.
    """

    # 🔴 AN OLD SNAPSHOT — THE SAME REFUSAL VERBATIM. A parse taken before
    # 04.09 does not carry the boundary, and the text must stay the same,
    # otherwise the coverage history stops being a history. It is
    # assembled by the same instrument from the registry as yesterday.
    if element.opening_is_rect is None:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_opening"))

    host_id = element.host_id
    if not host_id:
        # An opening without a host is a shaft, and its kind is
        # DELIBERATELY NOT TAKEN by the registry
        # (`ops_opening.VARIETIES_NOT_TAKEN`): there is nothing to confirm
        # the pair of levels with, from the built element.
        raise _CannotLift(
            AtomReason.MISSING_REFERENCE,
            "проём без Opening.Host — это шахта, а её род не взят реестром: "
            "пару уровней нечем подтвердить с построенного элемента")
    host_element = context.elements_by_id.get(host_id)
    if host_element is None:
        raise _CannotLift(
            AtomReason.MISSING_REFERENCE,
            f"носитель проёма {host_id!r} отсутствует в разбираемом документе")
    variety = _OPENING_HOST_VARIETY.get(host_element.category)
    if variety is None:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"носитель проёма — {host_element.category}, а create_opening "
            "выражает только проём в стене и проём по профилю в "
            "перекрытии/кровле/потолке")
    if variety == "host_face":
        raise _CannotLift(AtomReason.MISSING_METADATA,
                          _OPENING_CUT_HAS_NO_GETTER)

    # Beyond this only `wall_rect` remains, and both its inputs are
    # proven.
    #
    # 🔴 THE ORDER OF THESE TWO CHECKS IS NOT A MATTER OF TASTE. For an
    # arced boundary in a wall BOTH statements are true ("not a
    # rectangle" and "not a polyline"), but the reason must be the truest
    # one, not the first one that fits: "arc" names a FACT ABOUT THE
    # BUILDING and addresses the work to the shape registry (contour),
    # while "not a rectangle" would sound like a poverty of kind and would
    # send someone looking for another variety, which does not exist for
    # an arc anyway.
    boundary = element.opening_boundary_mm
    if boundary is None:
        # `is_rect` was read, there is no boundary — it WAS READ and it is
        # not a polyline.
        raise _CannotLift(
            AtomReason.UNSUPPORTED_GEOMETRY,
            "граница проёма прочитана и она НЕ ЛОМАНАЯ: дуга под outline "
            "становится хордой, то есть ДРУГИМ проёмом, а не приближением")
    if not element.opening_is_rect:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "проём в стене с НЕпрямоугольной ломаной границей: "
            "variety=wall_rect выражает только прямоугольник, а достроить "
            "его из профиля значило бы выдать другую форму за эту")
    host_node = nodes_by_source.get(host_id)
    if host_node is None or host_node.get("kind") != "op":
        raise _CannotLift(
            AtomReason.DEPENDENCY_UNRESOLVED,
            f"носитель проёма {host_id!r} сам не поднялся в операцию, и "
            "ссылаться не на что")
    p0, p1 = boundary
    return _op_node(element, "create_opening", {
        "variety": "wall_rect",
        "host": {"ref": host_node["_id"]},
        "p0_mm": [float(p0[0]), float(p0[1]), float(p0[2])],
        "p1_mm": [float(p1[0]), float(p1[1]), float(p1[2])],
    })


def _refuse_load_whose_meaning_the_op_cannot_hold(
    element: L0Element,
    op_name: str,
) -> None:
    """Boundaries common to ALL load kinds. One shared body deliberately.

    The three properties of `LoadBase` change the load's meaning at the
    same numbers, and forgetting them in one branch out of three would
    mean introducing the same silent defect all over again. That is
    exactly how it was introduced the first time: the first edition of
    the fix read only what the gap's reason named.
    """

    # 🔴 THE WINDOW OF OUR OWN BUG IS NAMED PRECISELY, NOT BLAMED ON "AN
    # OLD SNAPSHOT". Before the commit that added `OST_LineLoads` to the
    # capture, a row of this category DID NOT EXIST at all — the category
    # was not extracted. So a row that carries the ends but does NOT carry
    # `load_hosted` can come from exactly one place: from the window
    # between that commit and this fix, where the ends were read and the
    # meaning was not. In such a snapshot a hosted load is
    # indistinguishable from a free one, and "behave as before" would mean
    # repeating the bug, not preserving history.
    #
    # Hence a refusal here, not silence: the window is narrow, there are
    # almost no snapshots from it, and the cost of a mistake is a silently
    # rebuilt, wrong load.
    if element.load_hosted is None:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            "слепок несёт концы нагрузки, но не несёт её СМЫСЛА (IsHosted / "
            "IsReaction / OrientTo): такая строка снята окном, где читались "
            "координаты и не читалось, привязана ли нагрузка, не реакция ли "
            "она и в каком базисе задана — переснять слепок")
    # The comparison with `is True` is deliberate: the fields are
    # three-valued.
    if element.load_reaction is True:
        raise _CannotLift(
            AtomReason.GENERATOR_CHILD,
            f"нагрузка-РЕАКЦИЯ (IsReaction): её вычисляет расчёт, а не автор; "
            f"пересобрать её {op_name} значит выдать вычисленное за "
            f"заданное и посчитать его дважды")
    if element.load_hosted is True:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "нагрузка ПРИВЯЗАНА к носителю (IsHosted): она ходит за ним, а "
            "{op_name} входа для носителя не имеет вовсе — свободная "
            "нагрузка в тех же координатах это ДРУГАЯ нагрузка")
    # The forward op's `OrientTo` promises exactly `Project` in the
    # postcondition. It expresses no other basis, and silently changing it
    # would mean changing the meaning of the force while leaving the
    # numbers the same.
    if element.load_orient_to is not None \
            and element.load_orient_to != "Project":
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"базис нагрузки {element.load_orient_to!r}, а {op_name} "
            "строит только Project (это его пост-условие): смена базиса "
            "меняет СМЫСЛ силы при тех же числах")


def _lift_area_load(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Area load -> ``create_area_load``. FIVE boundaries, all from
    measurement.

    The three common to all kinds are taken from one shared body. Two of
    its own are named here, and both are read from the op's own
    postcondition, not invented:
    «GetLoops returns ONE ring whose vertices are the outline at elev_mm».
    """

    if element.load_area_loops_mm is None:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_area_load"))
    _refuse_load_whose_meaning_the_op_cannot_hold(element, "create_area_load")
    # FOURTH: an area load has THREE force vectors at reference points,
    # while the op holds ONE. More than one reference point means
    # non-uniformity, and taking the first vector would mean passing off
    # a different load as this one.
    if element.load_ref_points is not None and element.load_ref_points > 1:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"нагрузка задана по {element.load_ref_points} опорным точкам "
            "(NumRefPoints), то есть НЕРАВНОМЕРНА: у неё три вектора силы, а "
            "create_area_load выражает один")
    if element.load_projected is True:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "нагрузка ПРОЕКЦИОННАЯ (IsProjected): её величина отнесена к "
            "проекции площади, и create_area_load такого входа не имеет")
    # FIFTH: the op promises EXACTLY ONE ring. Several rings mean an area
    # with a hole, or several separate areas; picking one of them would
    # mean building a different load and staying silent about the rest.
    if len(element.load_area_loops_mm) != 1:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"у нагрузки {len(element.load_area_loops_mm)} колец, а "
            "create_area_load выражает ровно одно (его пост-условие): "
            "выбрать из них одно значило бы промолчать об остальных")
    кольцо = element.load_area_loops_mm[0]
    # SIXTH: `elev_mm` is ONE number. A non-planar ring cannot be
    # described by it, and taking the z of the first vertex would mean
    # dropping the rest to its elevation.
    отметки = {round(float(точка[2]), 6) for точка in кольцо}
    if len(отметки) != 1:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_GEOMETRY,
            f"кольцо нагрузки НЕПЛОСКОЕ: отметок {len(отметки)}, а elev_mm "
            "одно число — взять первую значило бы уронить остальные вершины")
    if not element.load_case_id or not element.load_case_name:
        raise _CannotLift(
            AtomReason.MISSING_REFERENCE,
            "случай нагрузки не прочитан (LoadBase.LoadCaseId): подставить "
            "его нечем, а create_area_load требует его обязательно")
    params: dict[str, Any] = {
        # `outline` is a TWO-DIMENSIONAL contour; the third coordinate
        # moved into elev_mm, and it is the same for every vertex, as
        # checked above.
        "outline": [[float(точка[0]), float(точка[1])] for точка in кольцо],
        "elev_mm": float(next(iter(отметки))),
        "load_case": {"by": "name", "value": str(element.load_case_name),
                      "_id": str(element.load_case_id)},
    }
    if element.load_force_n_per_m2 is not None:
        fx, fy, fz = element.load_force_n_per_m2
        params.update(fx_n_per_m2=float(fx), fy_n_per_m2=float(fy),
                      fz_n_per_m2=float(fz))
    return _op_node(element, "create_area_load", params)


def _lift_point_load(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Point load -> ``create_point_load``.

    The second closed load kind. The boundaries are the same and are
    taken from ONE shared body: this op's postcondition promises exactly
    `OrientTo == Project`, just like the linear one, and it has no inputs
    for a host or for a reaction.
    """

    if element.load_p0_mm is None:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_point_load"))
    _refuse_load_whose_meaning_the_op_cannot_hold(element, "create_point_load")
    if not element.load_case_id or not element.load_case_name:
        raise _CannotLift(
            AtomReason.MISSING_REFERENCE,
            "случай нагрузки не прочитан (LoadBase.LoadCaseId): подставить "
            "его нечем, а create_point_load требует его обязательно")
    params: dict[str, Any] = {
        "xyz": [float(v) for v in element.load_p0_mm],
        "load_case": {"by": "name", "value": str(element.load_case_name),
                      "_id": str(element.load_case_id)},
    }
    # Force is in NEWTONS, moment in newton-meters — different fields and
    # different units. Absence stays absence: a zero triple is a VALUE,
    # not ignorance, and substituting it would mean declaring the load
    # zero.
    if element.load_force_n is not None:
        fx, fy, fz = element.load_force_n
        params.update(fx_n=float(fx), fy_n=float(fy), fz_n=float(fz))
    if element.load_moment_nm is not None:
        mx, my, mz = element.load_moment_nm
        params.update(mx_nm=float(mx), my_nm=float(my), mz_nm=float(mz))
    return _op_node(element, "create_point_load", params)


def _lift_line_load(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    """Line load -> ``create_line_load``, with THREE boundaries.

    The first of eleven closed gaps established the same day by the
    "silence becomes a refusal" wave: before it the category was not
    extracted at all.
    """

    # THE FIRST BOUNDARY is an old snapshot. No keys, refusal VERBATIM the
    # previous one: the text is assembled by the same instrument from the
    # registry as before the wave.
    if element.load_p0_mm is None or element.load_p1_mm is None:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail("create_line_load"))
    # THE SECOND — A NON-UNIFORM LOAD CANNOT BE EXPRESSED, AND THIS IS NOT
    # CAUTION. It has TWO different vectors at its ends (`ForceVector1` !=
    # `ForceVector2`), while the op holds ONE triple. Taking the first
    # would mean passing off a different load as this one — exactly the
    # same substitution for which a chord instead of an arc is forbidden.
    # The comparison is with `is False`, not `not`: the field is
    # three-valued, and "not measured" (`None`) must behave as before, not
    # as "non-uniform".
    if element.load_uniform is False:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "нагрузка НЕРАВНОМЕРНАЯ: у неё два разных вектора по концам, а "
            "create_line_load выражает один — взять первый значило бы выдать "
            "другую нагрузку за эту")
    # THE THIRD — PROJECTED. It is set on the length's projection, not on
    # the length itself; the op has no input for this at all, and
    # silently building a non-projected one would mean changing the
    # magnitude while leaving the appearance unchanged.
    if element.load_projected is True:
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "нагрузка ПРОЕКЦИОННАЯ (IsProjected): её величина отнесена к "
            "проекции длины, и create_line_load такого входа не имеет")
    # 🔴 THREE BOUNDARIES ADDED AFTER OUR OWN MISS THE SAME DAY. The first
    # edition read from the load only what the gap's reason named, and so
    # it SILENTLY rebuilt a hosted load as free-standing, a
    # locally-oriented one as projected, and an analytical reaction as
    # authored. Exactly the kind for whose closing this whole wave was
    # done.
    #
    _refuse_load_whose_meaning_the_op_cannot_hold(element, "create_line_load")
    if not element.load_case_id or not element.load_case_name:
        # `load_case` IS REQUIRED by the op. Substituting "some" case
        # would mean assigning the load to the wrong load combination.
        raise _CannotLift(
            AtomReason.MISSING_REFERENCE,
            "случай нагрузки не прочитан (LoadBase.LoadCaseId): подставить "
            "его нечем, а create_line_load требует его обязательно")
    params: dict[str, Any] = {
        "p0_mm": [float(v) for v in element.load_p0_mm],
        "p1_mm": [float(v) for v in element.load_p1_mm],
        "load_case": {"by": "name", "value": str(element.load_case_name),
                      "_id": str(element.load_case_id)},
    }
    # The vector is OPTIONAL for the op, and absence stays absence: it
    # must not be substituted by a zero triple — zero is a VALUE, not
    # ignorance.
    if element.load_force_n_per_m is not None:
        fx, fy, fz = element.load_force_n_per_m
        params["fx_n_per_m"] = float(fx)
        params["fy_n_per_m"] = float(fy)
        params["fz_n_per_m"] = float(fz)
    return _op_node(element, "create_line_load", params)


def _lift_flex_run(
    element: L0Element,
    context: _Context,
    op_name: str,
    type_param: str,
) -> L1OpNode:
    """Common body of a flex segment: duct and hose differ ONLY in the
    op's name and the type parameter's name.

    Written as ONE body deliberately. Two nearly identical lifters would
    have diverged silently — exactly the reason the block of host readers
    in the capture is also one for all categories.
    """

    # 🔴 THERE IS NO PATH — THIS IS NOT "A PATH OF TWO ENDS" (04.09.2026).
    # A snapshot taken before this wave does not carry `flex_path_mm`, and
    # the refusal must be VERBATIM the previous one: the same atom, the
    # same reason, the same text. Otherwise the coverage history stops
    # being a history. The text is assembled by the same instrument from
    # the registry that assembled it yesterday — not rewritten by hand.
    path = element.flex_path_mm
    if path is None:
        raise _CannotLift(
            AtomReason.SOURCE_CONTRACT_GAP,
            _unsourceable_inputs_detail(op_name))
    # 🔴 THE LANGUAGE'S LIMIT IS CUT OFF HERE, NOT IN CAPTURE, AND BY A
    # REFUSAL, NOT BY TRUNCATION. `path3` holds 2..64 points. A longer
    # route is not "almost the same": dropping the middle would mean
    # passing off a DIFFERENT route as this one, i.e. exactly the
    # substitution for which a chord instead of an arc is forbidden. The
    # reason addresses the REGISTRY (the op cannot express it), not the
    # reading (everything was read). The limit is asked of `kir.geom` —
    # the same authority the railing asks it of at line 2328. A private
    # copy of "2..64" would be a second carrier of one number, and the two
    # would diverge silently.
    if not (_geom.MIN_PATH_POINTS <= len(path) <= _geom.MAX_PATH_POINTS):
        raise _CannotLift(
            AtomReason.UNSUPPORTED_SIGNATURE,
            f"{op_name} выражает ломаную из {_geom.MIN_PATH_POINTS}.."
            f"{_geom.MAX_PATH_POINTS} точек, а снято {len(path)}: "
            "выброшенная середина дала бы ДРУГУЮ трассу при зелёном вердикте")
    params: dict[str, Any] = {
        "path": [[float(x), float(y), float(z)] for x, y, z in path],
        "level": _level_ref(element.level_id, element.level_name),
        type_param: _catalog_ref(element),
    }
    # Flex segments HAVE NO system type AND WILL NEVER GET ONE FROM THIS
    # INDEX: the `mep_system_extract` stage declares its categories as a
    # closed list, and flex segments are deliberately not in it. The
    # parameter is optional, and absence stays absence, not a substituted
    # name.
    return _op_node(element, op_name, params)


def _lift_flex_duct(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    return _lift_flex_run(element, context, "create_flex_duct", "flex_duct_type")


def _lift_flex_pipe(
    element: L0Element,
    context: _Context,
    _nodes_by_source: Mapping[str, L1Node],
) -> L1OpNode:
    return _lift_flex_run(element, context, "create_flex_pipe", "flex_pipe_type")


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
    """MEP duct — a mirror of the cable tray, and this is not a coincidence
    of names.

    In the L0 row, a duct and a cable tray are INDISTINGUISHABLE by shape:
    both are linear MEPCurve, both have the same pair of ends read, the
    same level, and the same catalog type. There is DELIBERATELY no
    diameter here — the forward op does not take one either (a duct's
    nominal size is a trade size from the type table, not a length; see
    the header of ops_mep.py), and lifting a number that cannot be
    rebuilt would mean passing off an unbuildable program as a full
    circle.
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
    """Why there is no row: from the receipt, if there is one.

    §18.2/M5. «element is absent from the family placement side index» is
    true, but USELESS: it sounds the same whether the compiler cannot
    handle such an element or the extractor never reached it. On the live
    SOB6.2 this phrase stood on 242 curtain wall panels that the extractor
    simply discarded (a panel-wall is not a FamilyInstance), and it read
    like a gap in capability. The reason is taken FROM THE RECEIPT —
    typed, when the receipt is typed.

    The refusal code stays ``placement_kind_unknown``: introducing a
    separate AtomReason value would mean expanding the CLOSED dictionary
    of reasons for the sake of a nuance, while the mirror FidelityReason
    table and every coverage counter are keyed off it. Precision lives in
    detail, where it is actually read.
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


# Placements that `place_family` expresses as a POINT.  Both go through
# one overload, NewFamilyInstance(point, symbol, [host,] level, …); the
# difference between them is exactly whether a host is required.  The
# remaining enum values are a different shape (curve, two elevations, a
# work plane, adaptive points), and they are not placed by a point.
_POINT_PLACED_PLACEMENTS = frozenset((
    FamilyPlacementType.ONE_LEVEL_BASED,
    FamilyPlacementType.ONE_LEVEL_BASED_HOSTED,
    # ── TwoLevelsBased WAS ADDED ON 12.08.2026, AND THE PREVIOUS LINE
    # NEXT TO IT ASSERTED THE OPPOSITE. The comment above used to read:
    # «CurveDrivenStructural, TwoLevelsBased, WorkPlaneBased, and Adaptive
    # are not placed by a point». For the two-level kind this is WRONG,
    # and it is refuted by measurement, not by reasoning: in the parse
    # `k2_ar_rd_v15` there are 5,337 `TwoLevelsBased` rows, and EVERY LAST
    # ONE has a point, a rotation, `placement_available`, a resolvable
    # `FAMILY_BASE_LEVEL_PARAM`, and a resolvable `FAMILY_TOP_LEVEL_PARAM`.
    # None nested, none in-place, none hosted.
    #
    # Revit HAS no separate overload for this kind: an instance is placed
    # by the SAME point overload, and "up to which level" is set by
    # parameters after placement — and `place_family` ALREADY emits this
    # (`authoring.py`, the `two_levels` branch), already carries the
    # operands `top_level`/`base_offset_mm`/`top_offset_mm`, and already
    # has the witness obligation «FAMILY_TOP_LEVEL_PARAM == top_level when
    # given». Verified by the compiler on all six versions, with controls:
    # the enum member itself, both BuiltInParameters, the point overload
    # with a level, and READING BOTH LEVELS BACK from the built instance —
    # 6/6.
    #
    # THIS IS THE THIRD CASE OF THE SAME FAMILY IN THIS FILE: the producer
    # learned, the consumer with its closed list did not. The first was
    # `OneLevelBasedHosted` ("the op learned to host, and the lift's gate
    # was not extended", 2,053 elements on this same tower). Its relative
    # in the gate: the producer is unconditional, the consumer sits behind
    # a switched-off flag. Two sides of one fact evolve apart, and nothing
    # forces them to match; so the list below is now CLOSED BY THE
    # JOURNAL, not by the absence of rows.
    #
    # 679 load-bearing columns from the same 5,337 will NOT LAND here and
    # cannot: they are resolved earlier, by category, in `create_column`
    # (verified — 679 ops, zero atoms). The extension picks up 4,658: 4,479
    # telephone devices, 175 equipment items, 4 generic models.
    FamilyPlacementType.TWO_LEVELS_BASED,
))


#: PLACEMENT KINDS NOT PLACED BY A POINT — WITH A REASON AND A DATE FOR
#: EACH.
#:
#: WHY A JOURNAL, RATHER THAN JUST AN ABSENCE FROM THE SET ABOVE. Extending
#: the set by one entry means fixing today while keeping the mechanism:
#: the next kind will silently hit the same wall, and that would be the
#: THIRD time in one file. As long as the exception is expressed as an
#: ABSENCE, it demands a decision from no one; as a record with a reason
#: and a deadline, it does. Replacing the list with the rule "has a point
#: ⇒ we lift it" is FORBIDDEN here: `WorkPlaneBased` also has a point
#: (5,060 rows in the same tower), and a work plane is a separate fact,
#: and lifting by point would lose it silently.
#:
#: The test `tests/test_placement_kinds_are_all_decided.py` requires that
#: EVERY member of `FamilyPlacementType` be either point-based,
#: view-dependent, or named here. There is no empty fourth option.
PLACEMENTS_NOT_POINT_PLACED = Ledger(
    "lift.PLACEMENTS_NOT_POINT_PLACED",
    {
        FamilyPlacementType.WORK_PLANE_BASED.value: Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "точка у него ЕСТЬ (5 060 строк в k2_ar_rd_v15), но рабочая "
            "плоскость — отдельный факт, которого точка не несёт; подъём "
            "точкой потерял бы привязку молча. Закрывается операндом плоскости "
            "у place_family либо отдельным опом, не расширением этих ворот"),
        FamilyPlacementType.CURVE_BASED.value: Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "семейство по КРИВОЙ: у place_family для этого своя ветка "
            "(`p0_mm`/`p1_mm` + host), и она уже построена — сюда он не "
            "относится вовсе, гейт точки для него не тот вопрос"),
        FamilyPlacementType.CURVE_DRIVEN_STRUCTURAL.value: Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "несущее по кривой (41 строка в той же башне): ставится "
            "перегрузкой с Line и StructuralType, а не точкой; у балок это "
            "уже делает create_beam, и заводить второй путь через "
            "place_family значило бы двух судей об одном"),
        FamilyPlacementType.CURVE_BASED_DETAIL.value: Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "детальное по кривой (413 строк): и кривая, и ВИД — два "
            "недостающих факта сразу, поэтому оно не станет точечным даже "
            "после операнда вида"),
        FamilyPlacementType.ADAPTIVE.value: Entry(
            CLOSE_BY, "2026-08-12", "2026-09-11",
            "адаптивное семейство описывается НАБОРОМ точек-узлов, а не одной "
            "точкой вставки; одна точка не выражает его формы, и подъём был "
            "бы утверждением о геометрии, которого мы не делали"),
        FamilyPlacementType.INVALID.value: Entry(
            STANDS, "2026-08-12", "",
            "значение перечисления, означающее ОТСУТСТВИЕ рода размещения; "
            "поднимать нечего по построению, и срока у этого не бывает"),
    },
    instrument=(
        "боковой индекс размещений разбора: доля строк этого рода, у которых "
        "есть точка, поворот и разрешимые уровни — если появились все входы, "
        "запись обязана уехать в _POINT_PLACED_PLACEMENTS, а не ждать"))


# A VIEW-DEPENDENT placement is a separate refusal, and here is why it is
# not the same one.
#
# The gate below cuts off everything "not a point", and before 29.07 a
# nail element got exactly this text: «place_family only places
# point-based placements, and this instance is 'ViewBased'». This reads
# as "a different GEOMETRY is needed", and the next person would go
# looking for a curve or adaptive points. But ViewBased IS A POINT.
# Autodesk describes the value verbatim: "The family is view-specific
# (e.g. a detail annotation)" (RevitAPI.xml, F:…FamilyPlacementType.ViewBased,
# all six versions). The nail element does have a point, and it sits in
# the side index; what is missing is not the shape but the VIEW.
#
# The real reason is in the operation itself: place_family HAS NO view
# parameter (ops_authoring.py: xyz, p0_mm, p1_mm, host, level, symbol,
# rotation_deg, three flags — and that is all). And this is not an
# oversight of the registry but the shape of the API: Revit keeps
# model-based and view-based placement as DIFFERENT overloads, and the
# only view-based one is linear and documents the failure in plain text
# (trap index, api_trap_index.py):
#
#   M:…ItemFactoryBase.NewFamilyInstance(Line,FamilySymbol,View)  [all]
#   InvalidOperationException: "Thrown when attempting to place a model-based
#   family. Only 2D detail families can be placed in views."
#
# That is, substituting the model-based overload here is not possible even
# in theory: it would place a MODEL instance instead of a view-based one —
# a different element, silently passed off as the same one. Measurement
# K2: 3,046 nail elements.
#
# The placement type IS IN QUOTES deliberately — the reason map folds
# quoted values into '…', and both view-dependent forms remain ONE
# structural row of the ranking.
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
    # THE ORDER HERE MATTERS, and it was chosen by measurement, not by the
    # function's wording.
    #
    # Nesting is checked FIRST: a generated child stays a child no matter
    # its placement — it is created by the parent, and it is not a
    # separate hole. The refusal reason must be the TRUEST of those that
    # apply, not the first one encountered.
    #
    # While the placement check stood earlier, nested instances with a
    # placement other than OneLevelBased got its label. The difference is
    # not cosmetic: `generator_child` IS SUBTRACTED from honest coverage,
    # while `unsupported_signature` is not. Measurement of 27.07 on the
    # MEP training model (SKLNK R2026): 1738 instances, 1659 nested, 79
    # standalone — honest coverage showed as 30.37% instead of 67.70%,
    # meaning the compiler slandered itself by half.
    if record.super_component_id is not None:
        _refuse(
            AtomReason.GENERATOR_CHILD,
            "nested shared FamilyInstance is generated by parent "
            f"{record.super_component_id!r}")
    # A CurveBased instance with a READ line is lifted along the curve.
    #
    # Measurement of 27.07 (MEP training model, SKLNK R2026): 79 instances
    # — the entire remaining hole of this model — are CurveBased, and all
    # have a live LocationCurve. The instances hang on cable trays, but
    # the host here is NOT an obstacle: the NewFamilyInstance overload
    # with a curve does not accept a host, Revit links it itself, so the
    # host is read back in the witness. Refusing over a field the call
    # does not have would mean losing the element for nothing.
    #
    # `curved_unsupported` is skipped deliberately: the marker is set
    # BEFORE the attempt to read and means exactly "the line could not be
    # captured". Lifting such a thing by nonexistent endpoints would be
    # inventing geometry.
    if (record.placement_type is FamilyPlacementType.CURVE_BASED
            and record.curve_state is CurveState.LINE
            and record.curve_p0_mm is not None
            and record.curve_p1_mm is not None):
        # The curved variant HAS NO level, the host IS REQUIRED — both are
        # measured, not chosen (see ops_authoring.place_family): the
        # overload with a level projects the curve onto the level's plane
        # and collapses a vertical segment into a point, while the correct
        # overload goes by a reference to the host's face and does not
        # accept a level at all.
        #
        # The first version of this branch (27.07) required a level and
        # did not pass a host — it was written BEFORE the measurement.
        # Re-extraction of MEP showed exactly that: 79 enclosures refused
        # with "need both the level id and the name", meaning the chain
        # had not been closed all the way.
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
    # A POINT placement is TWO types, not one.
    #
    # Below, this same function assembles `hosted_ref` and passes the host
    # into `place_family` through the very overload
    # NewFamilyInstance(point, symbol, HOST, level, …) that places doors
    # and windows (measured live on 28.07 on MEP). But the gate stood on
    # `is not ONE_LEVEL_BASED` and cut off exactly the type that MEANS
    # "hosted" — `OneLevelBasedHosted`. The host branch remained reachable
    # only for the `OneLevelBased` row, which happened to have a `host_id`
    # by accident (a curtain wall system on K2). That is, the op learned
    # to host, and the lift's gate was not extended.
    #
    # Measurement of 29.07 over the side indexes, non-nested rows:
    # `OneLevelBasedHosted` exists in FOUR documents — demo 3122,
    # 13A-RD-AR-K2_v33 2053, SOB6.2_AR 184, SOB6.2_FAS 14 — and EVERY LAST
    # ONE has a point, a rotation, and `host_id`.
    #
    # The gate NARROWS, it does not disappear: CurveDrivenStructural,
    # TwoLevelsBased, WorkPlaneBased, and Adaptive are not placed by a
    # point, and the refusal remains for them.
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
            # The placement type is IN QUOTES deliberately: the reason map
            # folds quoted values into '…', and the rule remains ONE
            # structural row of the ranking instead of four (one per
            # shape), while the type itself is still read in every
            # element's detail.
            "place_family ставит только точечные размещения "
            "(OneLevelBased/OneLevelBasedHosted), а у этого экземпляра "
            f"{record.placement_type.value!r}")
    if record.in_place:
        _refuse(
            AtomReason.UNSUPPORTED_SIGNATURE,
            "in-place families require source-native family definitions")
    # A hosted instance is not a refusal but a host in the op.
    #
    # MEASUREMENT of 28.07 (MEP): once the side index covered the
    # sections, the ONLY remaining cause of atoms became 199 elements
    # with this message — equipment on walls and ceilings. The op now
    # places them with the same overload
    # NewFamilyInstance(point, symbol, HOST, level, …) that has long
    # placed doors and windows.
    #
    # The host MUST BE LIFTED: placing onto something that does not exist
    # in the program is impossible, and "place it without a host" would be
    # a silent loss of the attachment.
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
        # A family that, BY ITS PLACEMENT TYPE, exists only on a host
        # cannot be placed without one. A free-standing point would look
        # like success while silently losing the attachment — exactly the
        # silent loss §18.1 forbids.
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
    # THE TOP LEVEL — ONLY IF IT WAS READ, AND A REFUSAL IF THE KIND
    # REQUIRES IT.
    #
    # A two-level family WITHOUT a top level is not "we'll lift it as a
    # regular one": `TwoLevelsBased` means the top is set by an anchor,
    # and losing it would mean building an instance that stands in the
    # wrong place, with a green witness (the top-level witness is
    # CONDITIONAL and is dismissed by the absence of the operand — meaning
    # silence would cover up its own loss).
    # THE IDIOM IS TAKEN FROM A NEIGHBOR, NOT WRITTEN ANEW: the column
    # lifter in this same file resolves the top exactly the same way
    # (`context.levels_by_id`, typed refusals, the same selector shape and
    # the same offset). A second way of reading the same parameter would
    # mean two judges of one fact.
    if record.placement_type is FamilyPlacementType.TWO_LEVELS_BASED:
        top_level_id = (element.params or {}).get("FAMILY_TOP_LEVEL_PARAM")
        if not isinstance(top_level_id, str):
            _refuse(
                AtomReason.MISSING_METADATA,
                "двухуровневое размещение: FAMILY_TOP_LEVEL_PARAM не строка-id")
        top = context.levels_by_id.get(top_level_id)
        if top is None:
            _refuse(
                AtomReason.MISSING_METADATA,
                "двухуровневое размещение: FAMILY_TOP_LEVEL_PARAM не "
                "разрешается в прочитанный уровень — верх задан привязкой, и "
                "поднять экземпляр как одноуровневый значило бы молча её "
                "потерять при УСЛОВНОМ свидетеле, который на отсутствие "
                "операнда разряжается")
        params["top_level"] = {"by": "name", "value": top.name, "_id": top.id}
        top_offset = _finite(
            (element.params or {}).get("FAMILY_TOP_LEVEL_OFFSET_PARAM"))
        if top_offset is not None and _survives_canon_rounding(top_offset):
            params["top_offset_mm"] = _bounded_param(
                element, "FAMILY_TOP_LEVEL_OFFSET_PARAM", "place_family",
                "top_offset_mm")
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
    """DirectShape -> create_directshape, or an EXACT refusal reason.

    The mesh is taken from the side slice (`profile_index`, keyed by
    element id) for the same reason the run path is taken from there for
    a stair: L0 has none of this geometry. Here this is not an
    implementation detail but the central fact of direction: GeometryKind
    is closed to the values curve/point/bbox_only, and it carries neither
    L0 vertices nor triangles at all (Wave G, KIR_DECOMPILE_SPEC §0.6, not
    built). There is also today no live stage that would fill this slice
    for DirectShape — and this is a NAMED debt, not a silent hole: without
    the slice, the element becomes an atom with the reason
    MISSING_GEOMETRY, which says exactly what is missing.

    What is DELIBERATELY absent here is mesh recovery from the bounding
    box. A box in place of a shell would pass any structural test and
    would be an untruth: "built something else" is indistinguishable from
    success from the outside.
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
        # The DirectShape category is not preserved in L0 (the field holds
        # the literal "DirectShape"), so the slice must supply it.
        # Substituting generic_model would mean silently changing the
        # element's category.
        _refuse(
            AtomReason.MISSING_METADATA,
            "категория DirectShape не сохранена в L0 и не принесена срезом — "
            "подставлять её за источник запрещено")
    from kir.ops_shape import DIRECTSHAPE_CATEGORIES
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

    # THE SAME LAWS AS THE COMPILER'S, AND THE SAME CODE. The direction
    # invariant: the lifter has no right to hand back a program the
    # compiler will later reject — otherwise the parse is "successful"
    # while the rebuild fails.
    from kir.mesh import validate_mesh
    diags: list = []
    # A SEAM (a facing pair of faces on the same points) is ALLOWED here
    # for the same reason as in escrow: this is geometry read from
    # someone else's document, not authored. A real duplicate — the same
    # wrapping — is still a refusal.
    mesh = validate_mesh(
        {"vertices_mm": raw.get("vertices_mm"),
         "triangles": raw.get("triangles")},
        element.element_id, "mesh", diags, allow_seam_faces=True)
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
    """Room separation line by the reverse pass (wave/room, 03.08).

    BEFORE THIS WAVE THE CATEGORY DID NOT EXIST HERE AT ALL, and that was
    true: the operation did not exist, all 2,313 K2 elements honestly got
    ``no_lifter`` («category is outside the exact Part 5 lifter table»).
    The category had been read since 29.07 — as room CONTEXT (extract.py:
    "the room boundary is set by the line, not the wall") — but there was
    nothing to say with what was read.

    ONE ELEMENT — ONE SEGMENT, AND THIS IS NOT A SIMPLIFICATION. In L0,
    every OST_RoomSeparationLines carries its own ``p0_mm``/``p1_mm`` and
    its own ``level_id``; a four-segment polyline lies in the model as
    four ELEMENTS with four ElementIds. Stitching adjacent lines into one
    polyline is impossible both by law ("one L0 element -> EXACTLY ONE L1
    node") and by data: they have no shared identity that would prove
    their kinship — only a coincidence of coordinates, and that is a
    guess. So the lift gives a polyline of exactly two points, and the
    rebuild returns as many elements as there were.

    WHAT REMAINS A REFUSAL AND WHY (measurement k2_ar_rd_v9, 2,313
    elements):

    * AN ARC — 14 elements (``curve_kind: arc``). ``path`` has no arc
      parameter, and a chord is a different boundary: the room would
      shift in area, and verify would not see it (the ends are compared).
    * A PLANE OFF THE LEVEL — 4 elements (offset -30 mm). There is no
      offset either in the operation or the API: SketchPlane.Create(doc,
      levelId) builds the plane OF the level ITSELF. Silently returning
      such a separator "approximately there" is exactly the silent loss
      §18.1 forbids.
    * NO LEVEL IN THE REFERENCE TABLE — a level is required, and there is
      nowhere to derive it from.
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
    # ELEVATION. There is ONE grid — the same CANON_MM by which the canon
    # rounds every ``*_mm`` field; a private threshold here would mean a
    # second judge of what counts as "the same elevation" (the same
    # argument and the same trick as with _lift_railing and its plane_z).
    # BOTH ends are checked: this simultaneously proves that the segment
    # lies IN the level's plane rather than crossing it.
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
    "_lift_area_load": _lift_area_load,
    "_lift_point_load": _lift_point_load,
    "_lift_line_load": _lift_line_load,
    "_lift_opening": _lift_opening,
    "_lift_flex_duct": _lift_flex_duct,
    "_lift_flex_pipe": _lift_flex_pipe,
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
#: EXPANDED ON 12.08.2026 AND CHECKED FOR LAG — THERE IS NO LAG.
#:
#: After `_POINT_PLACED_PLACEMENTS` turned out to be narrower than the op
#: can handle (4,658 elements), the question arose of how many more such
#: lists there are. The instrument tied each LIST to a REFUSAL (a constant
#: whose check stands before `_refuse`), rather than searching for
#: constants in general: a list that never decides a refusal does not
#: answer the question. FIVE were found deciding a refusal, all in this
#: file — `fold.py` and `materialize.py` do not decide a lift by any list
#: (8 and 6 constants, zero at refusals).
#:
#: What checking each one for "does the writing side know more" showed:
#:
#:   `_POINT_PLACED_PLACEMENTS`   WAS LAGGING — fixed, 4,658 elements;
#:   `_VIEW_SPECIFIC_PLACEMENTS`  is NOT lagging: `place_family` has no
#:                                view operand at all (834 elements on the
#:                                tower), i.e. the refusal is correct, not
#:                                narrow;
#:   `_LOCATION_LINE_CHOICES`     CANNOT diverge BY CONSTRUCTION — it is
#:                                taken from `spec.OPS["create_wall"]`,
#:                                the acceptance reference;
#:   `_CANDIDATES` (35 rows)      is NOT lagging: for EVERY category with
#:                                `no_lifter` the op is simply absent from
#:                                the registry — `OST_Lines` 9,407,
#:                                `OST_SpotElevations` 2,292,
#:                                `OST_GenericAnnotation` 1,954. The
#:                                dispatcher has nowhere to send them, and
#:                                this is a gap in the LANGUAGE, not in
#:                                bookkeeping;
#:   `_SHAPE_REFUSALS`            is NOT lagging — see below.
#:
#: MEASUREMENT AGAINST THIS LIST. Elements that sit in the placement index
#: (i.e. a second chance through `place_family` would be technically
#: possible) and got a reason OUTSIDE the set: 21,926, of which 20,932 are
#: `generator_child`, which MUST NOT be given a second chance (the parent
#: already builds them), and 994 are `missing_reference` from an unlifted
#: host, i.e. dependency order, not narrowness of the list. Both
#: exceptions are already named: the first right below
#: (`_FALLBACK_REASONS_THAT_WIN`), the second is separate work.
#:
#: THE CONCLUSION THAT MATTERS MORE THAN THE EXPANSION ITSELF: the
#: `TwoLevelsBased` case turned out to be a SINGLE occurrence among this
#: file's lists. Three known cases of the same family
#: (`OneLevelBasedHosted`, `TwoLevelsBased`, an identity in the gate) are
#: not a sign that the bookkeeping lags everywhere; it had to be checked,
#: and the check answered "no".
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
    # A TAG NEVER FALLS INTO place_family.
    #
    # Both of its refusals — "kind is SpatialElementTag" and "orientation
    # cannot be expressed" — are ``unsupported_forward_signature``, i.e. a
    # SHAPE refusal, and a shape refusal here by default means "let
    # place_family try". For a tag this would be an INVENTED SOURCE
    # (§18.1): neither ``IndependentTag`` nor ``SpatialElementTag`` is a
    # ``FamilyInstance``, and a family placement in place of a tag would
    # pass the L1 schema and look like coverage.
    #
    # Today the path is unreachable — tag categories are not in the
    # placement side index's table, and its C# does not produce
    # non-FamilyInstance rows. This line holds the boundary for the day
    # the table is extended, and it stands BEFORE the index parse so as
    # not to depend on what ended up in them.
    if element.category in TAG_CATEGORIES:
        return None
    # A curtain wall door/window is a CELL, not an opening in a wall: it
    # has no LocationPoint at all, and its own lifter refuses by shape. If
    # the curtain side index knows this cell, the one responsible for the
    # element must be it, not place_family, which knows nothing about the
    # grid.
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
    # THE CELL'S BODY is checked before any category: the wall that fills
    # a curtain wall cell exists because the cell has a type assigned.
    # Its own operation would be a second instance of the same geometry —
    # and, unlike other reasons, this is a fact about the element, not
    # about our own abilities.
    owner_cell = context.curtain_cell_bodies.get(element.element_id)
    if owner_cell is not None and owner_cell in context.elements_by_id:
        # THE OCCUPANT IS PRESENT IN THIS SAME DOCUMENT — then the
        # occupied panel is precisely a body, and the cell has exactly
        # one operation, on the occupant's side. But if the occupant is
        # not in the document, this panel is the ONLY representation of
        # the cell, and calling it a generated child would mean losing
        # the cell entirely (on a re-lift of the rebuilt model).
        reason = AtomReason.GENERATOR_CHILD
        detail = (
            "тело витражной ячейки — его создаёт назначение типа ячейке "
            f"{owner_cell!r}, отдельной операции у него нет")
        return (
            _atom_node(element, reason, detail),
            _diagnostic(element, reason, detail),
        )
    # A MULLION is not a family instance placed at a point, but an
    # element of a GRID LINE. Its class is FamilyInstance, so the
    # placement side index gives a row about it, and the common path used
    # to place it with `place_family` at a point — meaning that on
    # rebuild the curtain wall would get its OWN mullions from the type
    # plus ours on top (measurement v6: 956 such ops, 42% of all facade
    # ops). The only way to create a mullion is
    # CurtainGridLine.AddMullions(segment, MullionType, oneSegmentOnly)
    # (RevitAPI.xml of the reference package); the mullion itself has a
    # LocationCurve, not a point. There is no op for this in the registry.
    #
    # Hence EXACTLY TWO honest outcomes, and what separates them is not
    # our preference but proof. A mullion the host does NOT generate is an
    # honest hole: calling it generator_child would mean subtracting from
    # the denominator something the rebuild will not build. A mullion the
    # host generates ITSELF is a child: it needs no operation, because it
    # will appear from the type. The proof requires two witnesses and
    # lives in CurtainWallRecord.mullion_state: Mullion.Lock (Revit itself
    # considers it type-driven) AND the mullion type being among the
    # host's AUTO_MULLION_* slots. The index schema before /4 read
    # neither, and its rows honestly remain a hole (measurement v11: 964
    # mullions, v12: 1372).
    # A GRID LINE is checked before the categories: it has its own id and
    # its own row in the side index, but neither a type nor a placement
    # point — the common placement path would place it with
    # `place_family` into a void.
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
            # A PROVEN child: rebuilding the host will spawn it by
            # itself, and only for that reason can it be subtracted from
            # the denominator. Both witnesses agree — Mullion.Lock and
            # the host type's slot.
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
        # THE OP EXISTS, IT HAS NO INPUTS FOR IT — checked FIRST, because
        # this is the most PRECISE of the applicable facts, and the reason
        # must be the truest one, not the first one encountered (the same
        # rule by which nesting is checked before placement in
        # _lift_family_fallback).
        #
        # Below stands §18.2 about the placement stage's silence, and for
        # a dimension or a tag it would give `no_lifter`: an annotation
        # never lands in the placement index, it is not a FamilyInstance.
        # The answer would be formally explainable and practically false
        # — it would send someone to write an operation that is already
        # written.
        annotation_op = _OPS_WITHOUT_L0_INPUTS.get(element.category)
        if annotation_op is not None:
            # The registry remains the SOLE authority on whether the op
            # exists: if it were to suddenly not be there, the honest
            # answer is the previous registry-gap, not a story about the
            # inputs of a nonexistent operation.
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
        # §18.2: an EMPTY placement index and an ABSENT one are different
        # things. While only the presence of rows was checked, a stage
        # entirely cut by the budget (not a single row, but a full
        # receipt list) looked like "we have no lifter for this
        # category" — the most wrong of the possible answers: the lifter
        # exists, the READING never reached the element.
        #
        # 29.07: the same distinction was generalized from the DOCUMENT to
        # the ELEMENT. While it was set for the whole document, it took
        # the stage running on just one row — and a ceiling, an area, a
        # stair railing, a curtain wall system, i.e. an element that was
        # NEVER a FamilyInstance and could never end up in the placement
        # index, got "element is absent from the family placement side
        # index". This reads as "the extractor lost it", while the truth
        # is "we have no operation for its category".
        #
        # This is visible directly in the reason map: one population stood
        # in it TWICE under different names — 28,926 elements "category is
        # outside the … lifter table" (snapshots where the stage did not
        # run) and 8,207 elements "absent from the family placement side
        # index" (the same categories where the stage did run). The reason
        # ranking is what is used to decide what to build next, and a
        # duplicate in it costs more than any percentage of coverage.
        #
        # Rule: if the stage has neither a row nor a receipt for THIS
        # element, it said nothing about it, and its silence is not
        # evidence against it. The old condition is a special case of the
        # new one: an empty index with no receipts is exactly silence
        # about every element.
        if element.element_id not in context.family_placement_index \
                and element.element_id not in context.family_placement_failures:
            reason = AtomReason.NO_LIFTER
            # The category IS NAMED (10.08). Measurement over 67 parses:
            # this reason is first in the map — 10 documents out of 10,
            # 77,733 elements — and the only one touching ALL documents.
            # Without the category's name nothing can be done about it: it
            # reports "something is missing", and it is used to decide
            # which row of the category table to write next. The name
            # comes BEFORE the previous wording, because the wording
            # itself is referenced by three tests and two comments in this
            # file.
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


# ─────────────────────────────────────────────────────────────────────────────
# JOINS: A RELATION, NOT AN ELEMENT
# ─────────────────────────────────────────────────────────────────────────────
#
# WHY THIS IS NOT AN L1 NODE AND NEVER WILL BE. The flat L1 layer is
# EXACTLY ONE node per L0 element: `validate_l1_nodes` rejects a repeated
# `source_element_id`, and `fold_document` rejects a node whose source is
# not in L0 (`L0/L1 source mismatch: missing=…, invented=…`). A join has
# no element of its own — it is a relation between TWO. Synthesizing a
# node for it was already tried on curtain wall grid lines, and the live
# run v14 stumbled on exactly this (`invented=122` — the case is analyzed
# below, in `_lift_document`, at the grid-line branch). So lifting a join
# is a COMPOSED operation AFTER the lift, exactly like `create_group` in
# `component_to_group_program`, and its reverse contract mode is
# `COMPOSED`, not `DIRECT`.
#
# 🔴 ONLY ONE KIND OUT OF THREE IS LIFTED, AND THIS IS NOT AN OVERSIGHT BUT
# A BOUNDARY OF THE LANGUAGE. The side index carries three DIFFERENT
# relations (`join_extract`, module header):
#
#     joined_to             JoinGeometryUtils.GetJoinedElements   a pair
#     join_allowed_at_end   WallUtils.IsWallJoinAllowedAtEnd      wall + end
#     elements_at_end_join  LocationCurve.get_ElementsAtJoin      pair + end
#
# The language has an op for exactly the FIRST one: `join_elements`
# promises `AreElementsJoined(doc, first, second) == true` post-commit —
# the very relation `GetJoinedElements` returns, re-read by the same
# function. There is NO op for the other two, and substituting
# `join_elements` for them would not be an approximation but a LIE: a
# live measurement of 18.08.2026 found a pair of walls where the join AT
# THE END EXISTS, while `AreElementsJoined` is False and `JoinGeometry`
# refuses with "cannot be joined" (join_extract.py:419). On one pair of
# walls these relations can be OPPOSITE, and a lifter that blurred them
# together would return a building joined in the wrong place.


class JoinLiftReason(str, Enum):
    """Closed reasons why a READ join did not become an op.

    Deliberately separate from :class:`AtomReason`: that one enumerates
    why an ELEMENT stayed an atom, while this one is about a RELATION,
    which has no element of its own at all. Merging them into one
    enumeration would mean giving one name to two questions — a naming
    defect of this tree.
    """

    #: The address from `joined_to` does not occur among the elements
    #: read. The index KEEPS such an address (discarding it would mean
    #: turning our own blindness into a negative fact about the building),
    #: the graph sets `Modality.UNRESOLVED_TARGET` on the edge, and there
    #: can be no operation for it: there is nothing to reference.
    TARGET_OUTSIDE_SNAPSHOT = "target_outside_snapshot"
    #: The far side was read and remained an ATOM. There is nothing to
    #: join: an atom has no op to reference, and `{"ref": …}` in
    #: materialization requires a materialized op. The reason for the atom
    #: ITSELF is carried into `detail` verbatim — otherwise the next
    #: person would go fix the joins where what needs fixing is the
    #: wall's lift.
    TARGET_STAYED_ATOM = "target_stayed_atom"


@dataclass(frozen=True, slots=True)
class JoinRefusal:
    """A single PAIR the index brought that the language could not express."""

    first: str
    second: str
    reason: JoinLiftReason
    detail: str


#: JOIN RELATIONS FOR WHICH THE LANGUAGE HAS NO OP — enumerated, not
#: passed over in silence. An empty cell reads as "this cannot happen",
#: while here it means "we READ this and cannot express it", and the
#: difference decides what to build next. A pair: (relation name, how it
#: is read, why there is no op).
JOIN_RELATIONS_WITHOUT_AN_OP: tuple[tuple[str, str, str], ...] = (
    ("join_allowed_at_end", "WallUtils.IsWallJoinAllowedAtEnd",
     "свойство ОДНОГО конца ОДНОЙ стены, а не отношение двух элементов. "
     "Опа, разрешающего/запрещающего стык на конце, в реестре нет; "
     "`join_elements` его не выражает и выражать не может — у него два "
     "операнда и ни одного конца"),
    ("elements_at_end_join", "LocationCurve.get_ElementsAtJoin",
     "стык КОНЦАМИ. Опа нет. Подставить `join_elements` нельзя: живой замер "
     "18.08.2026 дал пару стен, где стык концом есть, а AreElementsJoined "
     "False и JoinGeometry отказывает — отношения на одной паре бывают "
     "противоположны"),
    ("порядок реза", "JoinGeometryUtils.SwitchJoinOrder / "
     "IsCuttingElementInJoin",
     "НЕ ЧИТАЕТСЯ ЗАХВАТОМ ВОВСЕ. Это названное отсутствие, а не пробел "
     "лифтера: члены есть на всех шести версиях, но `join_extract` их не "
     "спрашивает, и выводить порядок из `joined_to` (отношение симметрично "
     "по построению) значило бы его ВЫДУМАТЬ"),
)


@dataclass(frozen=True, slots=True)
class JoinLift:
    """What became of the side index's joins — by THREE kinds, SEPARATELY."""

    #: Composed `join_elements` operations, one per PAIR, in the order of
    #: `JoinExtraction.pairs()`. References are in the L1 dialect
    #: (`{"ref": <node _id>}`), the same one L1 node params use:
    #: introducing a private dialect here would create a second carrier
    #: of the selector schema, and it is `materialize._translate_reference`
    #: that translates it.
    ops: tuple[dict[str, Any], ...] = ()
    #: Pairs that were read and NOT expressed, with a NAMED reason.
    refusals: tuple[JoinRefusal, ...] = ()
    #: How many `joined_to` pairs the index gave (ops + refusals, by
    #: construction).
    pairs_read: int = 0
    #: Ends with an end-join (`elements_at_end_join`) — a SEPARATE kind,
    #: no op exists. Printed so that "lifted 0 of 0" cannot be read as
    #: "there are no joins in the building": on `bench_A` `joined_to`
    #: pairs are ZERO, while end-joins are 872.
    end_joins_read: int = 0
    #: Walls for which the join-allowed-at-end setting was read
    #: (`join_allowed_at_end`) — the third kind, no op exists.
    walls_with_end_permission: int = 0
    #: A census of end states IN FULL, including zero keys. `not_read` and
    #: `free_end` are DIFFERENT statements, and there is nothing here to
    #: merge them with.
    end_states: Mapping[str, int] = field(default_factory=dict)
    #: Elements the stage requested and did NOT read (receipts, §18.2).
    #: "Not looked at" and "not joined" are different facts.
    elements_not_read: tuple[str, ...] = ()


def _join_extraction(join_index: Any) -> "JoinExtraction":
    """Reduce the input to a parsed :class:`JoinExtraction`.

    🔴 THE REFUSAL HERE IS LOUD, NOT `-> {}`, AND THIS IS A DELIBERATE
    DEPARTURE FROM ITS NEIGHBORS. For dimensions, tags, and annotations a
    quiet `{}` protects the PREVIOUS answer: a snapshot taken before the
    stage existed must refuse verbatim the same way it used to refuse.
    For joins no previous answer exists — there was no lifter at all —
    so there is nothing to protect, and a corrupted index read as "there
    are no joins" would reproduce exactly the owner's complaint for which
    the whole module was written: "nothing is joined to anything".
    """
    from kir.decompile.join_extract import (
        JoinExtraction,
        JoinPayloadError,
        JoinRecord,
    )

    if join_index is None:
        return JoinExtraction()
    if isinstance(join_index, JoinExtraction):
        return join_index
    if not isinstance(join_index, Mapping):
        raise JoinPayloadError(
            "join index must be a JoinExtraction, an envelope mapping, or None")
    if "join_index" in join_index or "schema_version" in join_index:
        return JoinExtraction.from_dict(join_index)
    records = []
    for key, row in join_index.items():
        record = JoinRecord.from_dict(row)
        if record.element_id != key:
            raise JoinPayloadError(
                "join index key does not match record.element_id")
        records.append(record)
    return JoinExtraction(joins=tuple(records))


def lift_joins(join_index: Any, nodes: Sequence[L1Node]) -> JoinLift:
    """Lift the side index's JOINS into composed language operations.

    Input: the `join_extract` side index (parsed, envelope, or bare map)
    and the ALREADY LIFTED L1 nodes of the same document. Output:
    `join_elements` operations with references to nodes, plus NAMED
    refusals.

    WHAT THIS FUNCTION DOES NOT DO, AND THIS IS NAMED, NOT PASSED OVER IN
    SILENCE:

    * it does not assign the op an `id`. Operation identity is handed out
      by `materialize._op_id` from `source_element_id`, and a join has no
      source; introducing a second carrier of the id scheme here would
      mean buying exactly the defect this whole file stands against;
    * it does not decide ORDER. The op must ride AFTER both sides and in
      the SAME program as them — that is the packer's job
      (`materialize._pack_groups`, `_toposort_chunk`), and how many pairs
      survive the split into programs is not measured here;
    * it does not read or invent the CUT ORDER
      (`JOIN_RELATIONS_WITHOUT_AN_OP`).

    MEASUREMENT (22.08.2026, parses on disk, both sides lifted with the
    full set of side indexes):

        parse                pairs joined_to   lifted   remaining   end-joins
        MNVNK (33,944)            10,082        1,992       8,090       6,629
        k2v33_join2 (115,889)      1,952        1,887          65      12,059
        bench_A (4,223)                0            0           0         872
        graph_check (1,556)            0            0           0           0

    The reason for the remainder is NAMED, and on MNVNK it is SINGULAR:
    8,061 pairs out of 8,090 ran into an `OST_Walls` side with
    `missing_geometry` — meaning the work lies in lifting the WALL, not
    the join. `target_outside_snapshot` FIRED NOT ONCE across all four
    parses (0 of 12,034 pairs): the reason was established not by a
    guess but by the stage's named boundary (`join_extract`: an address
    outside `JOIN_CATEGORIES` still gets its record KEPT), and its
    non-emptiness is proven by fabricated material in a test, not by the
    corpus.

    🔴 ZERO ON `bench_A` IS NOT "THERE ARE NO JOINS". `joined_to` pairs
    there are zero, while end-joins are 872: this is entirely a kind the
    language does not express. Reading "lifted 0 of 0" as "there is
    nothing to join in the building" would reproduce the owner's
    complaint for which the whole of `join_extract` was written.
    """
    from kir.reverse_contract import assert_composed_emission

    extraction = _join_extraction(join_index)
    # THE REVERSE-PASS BOUNDARY IS EXECUTABLE, NOT DECLARED, exactly as
    # with `_op_node`: a composed op has no right to appear if the
    # manifest did not declare it composed.
    assert_composed_emission("join_elements")

    node_by_source = {node["source_element_id"]: node for node in nodes}
    ops: list[dict[str, Any]] = []
    refusals: list[JoinRefusal] = []
    for first, second in extraction.pairs():
        blocked = False
        for address in (first, second):
            node = node_by_source.get(address)
            if node is None:
                refusals.append(JoinRefusal(
                    first, second, JoinLiftReason.TARGET_OUTSIDE_SNAPSHOT,
                    f"адрес {address} назван соединённым, но среди прочитанных "
                    "элементов его нет — сослаться не на что"))
                blocked = True
                break
            if node["kind"] != "op":
                reason = node.get("reason") or {}
                refusals.append(JoinRefusal(
                    first, second, JoinLiftReason.TARGET_STAYED_ATOM,
                    f"{address} остался атомом ({node.get('category')}): "
                    f"{reason.get('code')} — {reason.get('detail')}"))
                blocked = True
                break
        if blocked:
            continue
        ops.append({
            "op_name": "join_elements",
            "params": {
                "first": {"ref": node_by_source[first]["_id"]},
                "second": {"ref": node_by_source[second]["_id"]},
            },
            "sources": (first, second),
        })

    permissions = sum(
        1 for record in extraction.joins
        if record.join_allowed_at_end is not None)
    return JoinLift(
        ops=tuple(ops),
        refusals=tuple(refusals),
        pairs_read=len(extraction.pairs()),
        end_joins_read=len(extraction.end_join_pairs()),
        walls_with_end_permission=permissions,
        end_states=extraction.end_state_census(),
        elements_not_read=tuple(
            failure.element_id for failure in extraction.failures),
    )


class GroupLiftReason(str, Enum):
    """Why a READ group did not become a `create_group` operation.

    Deliberately separate from :class:`AtomReason` and from
    :class:`JoinLiftReason`, and for the same reason those two are kept
    apart: the first answers "why did the ELEMENT stay an atom", the
    second "why is the RELATION between two not expressed", and here the
    subject is a UNIT OF INTENT, which has neither its own element in L0
    (`OST_IOSModelGroups` is not taken into the parse) nor a pair of
    sides.

    ALL reasons below are about US or about the BUILDING, and this
    distinction is kept in each one's text: "a member stayed an atom"
    addresses the work to lifting THAT member, while "the instance
    composition diverged" is a fact about the model — there is nothing
    to fix.
    """

    #: A definition slot names an element that is not among those read.
    #: Measurement of 23.08: K6 4,535 slots, K3 4,213 — groups name
    #: things the parse does not take at all (sketches, parts, planes,
    #: dimensions).
    MEMBER_OUTSIDE_SNAPSHOT = "member_outside_snapshot"
    #: The member was read and remained an ATOM: there is nothing to
    #: reference, and `create_group` requires OPS. The reason for the
    #: atom itself is carried through verbatim — otherwise the next
    #: person would go fix groups where what needs fixing is the wall's
    #: lift.
    MEMBER_STAYED_ATOM = "member_stayed_atom"
    #: The member was lifted, but its op DOES NOT FIT as a group member,
    #: by kind.
    #: 🔴 A live measurement of 23.08 found exactly one such kind, and it
    #: is not invented: `create_room_separator` (K6 439 members across 31
    #: definitions, K3 308 across 27) has `identity_cardinality = many` —
    #: one operation spawns SEVERAL elements, and it cannot correspond to
    #: a definition slot.
    MEMBER_OP_INELIGIBLE = "member_op_ineligible"
    #: There are more members than `create_group.members` accepts.
    #: 🔴 THIS IS OUR OWN CEILING, NOT A FACT ABOUT THE BUILDING, and it
    #: hits the most expensive cases: measurement of 23.08 — K6 47
    #: definitions out of 177 (16,024 members), K3 38 out of 164 (13,131).
    #: This is exactly where facade floors land
    #: (`АР_Фасад_N этаж_`, 334–413 members) and whole typical apartments.
    MEMBER_COUNT_OVER_CEILING = "member_count_over_ceiling"
    #: The definition has not a single slot: there is nothing to place.
    DEFINITION_HAS_NO_MEMBERS = "definition_has_no_members"
    #: There is nothing to derive the offset from: no member has a point
    #: in L0. A fact about the KIND of the members (dimensions, floors by
    #: contour), not about the group.
    PLACEMENT_NOT_DERIVABLE = "placement_not_derivable"
    #: The offset is derived AMBIGUOUSLY: the members of one instance give
    #: different vectors. Substituting zero or "whichever comes first" is
    #: forbidden here by the same argument the group parser uses to
    #: refuse to invent an angle:
    #: «retain that as unavailable instead of inventing 0 degrees from its
    #: absence».
    PLACEMENT_AMBIGUOUS = "placement_ambiguous"
    #: The instance's composition differs from the reference one
    #: (the side index's `composition_mismatches`). Placing a definition
    #: that is different at this spot is a silent loss.
    COMPOSITION_MISMATCH = "composition_mismatch"


@dataclass(frozen=True, slots=True)
class GroupRefusal:
    """A single DEFINITION the index brought that the language could not
    express."""

    group_type_id: str
    group_type_name: str
    reason: GroupLiftReason
    detail: str


#: THE MEMBER CEILING OF `create_group.members` IS A REFERENCE, NOT A
#: SECOND CARRIER.
#:
#: 🔴 A LITERAL 200 USED TO STAND HERE, AND THE DANGER WAS NAMED RIGHT
#: ABOVE IT: "raise the ceiling in the validator, and no one will
#: remember the lifter." On 23.08.2026 the owner raised the ceiling to
#: 1000 — and the prediction came true within the hour: the validator
#: accepted, the lifter kept refusing 47 K6 definitions and 38 K3.
#:
#: Fixed not by synchronization but by REMOVING the second carrier: the
#: number lives in the registry (`spec.GROUP_MEMBERS_MAX`), and the
#: measurement it was chosen from sits right there. The behavioral guard
#: in `test_group_lift.py` stays, and stays useful — it checks that the
#: LIFTER and the VALIDATOR answer the same at the boundary, not that two
#: literals match.
_GROUP_MEMBER_CEILING = spec.GROUP_MEMBERS_MAX


def _group_member_eligible(
    op_name: str, params: Mapping[str, Any] | None = None,
) -> bool:
    """Whether an op qualifies as a group member — BY THE REGISTRY, not by
    a list of names.

    The conditions are the same ones the validator applies to
    `member_ops`: a single create operation of an authored family,
    yielding EXACTLY ONE element, not `create_group` and not solo. A list
    of names here would be a third carrier of the same truth and would
    diverge from the registry on the very first new op.

    🔴 `params` IS NOT DECORATION. The result kind of
    `create_room_separator` is declared `many`, and it gives "exactly one
    fewer segment than there are points in path" — that is, for a path of
    TWO points, exactly one element. The lift always gives it exactly two
    points (measurement of 23.08: K6 1086 of 1086, K3 917 of 917 — by
    construction, one L0 element is one ModelCurve). Asking only the
    declaration, the lifter refused 31 K6 definitions and 27 K3 — the
    second largest refusal reason after member-atoms. The INSTANCE
    decides, and it is decided by the same `spec.group_member_yields_one`
    as in the validator.
    """
    op = spec.OPS.get(op_name)
    if op is None:
        return False
    probe: dict[str, Any] = {"op": op_name}
    if params:
        probe.update(params)
    return (op.family == "authoring"
            and op.effect.value == "create"
            and spec.group_member_yields_one(op_name, probe)
            and op_name != "create_group"
            and op_name not in spec.SOLO_OPS)


def _member_shape_key(element: "L0Element | None") -> tuple:
    """The matching key for members of two instances of the same
    definition.

    TYPE AND CATEGORY, not the order in `member_ids`: Revit makes no
    promise about order, and a rank in an unpromised order would be an
    invention — the same argument by which the curtain wall index refuses
    to count "panel number 3" as an address.
    """
    if element is None:
        return ("", "")
    return (element.type_name or "", element.category or "")


def _instance_offset(
    reference_members: Sequence[str],
    other_members: Sequence[str],
    elements_by_id: Mapping[str, "L0Element"],
) -> tuple[tuple[float, float, float] | None, str]:
    """The offset of ONE instance relative to the reference — or a
    refusal reason.

    🔴 DERIVED FROM THE MEMBERS, BECAUSE THE GROUP HAS NONE OF ITS OWN.
    `transform_available` is False for ALL instances of all parses, and
    this is not a shortcoming of ours: `LocationPoint.Rotation` for
    `Group` throws `InvalidOperationException` in all six supported
    versions (Autodesk states this verbatim), and the attempt to read it
    already cost 2,846 groups out of 2,941 on `13A-RD-AR-K2_v33`. The full
    argument is in `group_extract.py`, the C# emission header.

    EXACTLY ONE vector is returned, or a refusal: if the members of one
    instance give different differences, this instance has no offset, and
    "take the first one" would be a guessed address.
    """
    ref_points: dict[tuple, list[tuple[float, ...]]] = {}
    for member_id in reference_members:
        element = elements_by_id.get(member_id)
        if element is None or element.p0_mm is None:
            continue
        ref_points.setdefault(
            _member_shape_key(element), []).append(tuple(element.p0_mm))
    if not ref_points:
        return None, ("ни у одного члена эталонного экземпляра нет точки в "
                      "L0 — сдвиг не с чего вывести")
    other_points: dict[tuple, list[tuple[float, ...]]] = {}
    for member_id in other_members:
        element = elements_by_id.get(member_id)
        if element is None or element.p0_mm is None:
            continue
        other_points.setdefault(
            _member_shape_key(element), []).append(tuple(element.p0_mm))
    if set(other_points) != set(ref_points):
        return None, ("набор родов членов у экземпляра не совпал с "
                      "эталонным — сопоставлять нечего")
    vectors: set[tuple[float, float, float]] = set()
    for key, ref_list in ref_points.items():
        other_list = other_points[key]
        if len(other_list) != len(ref_list):
            return None, (f"членов рода {key[0]!r} у экземпляра "
                          f"{len(other_list)}, у эталона {len(ref_list)}")
        for ref_point, other_point in zip(sorted(ref_list), sorted(other_list)):
            vectors.add(tuple(
                round(float(other_point[axis]) - float(ref_point[axis]), 3)
                for axis in range(3)
            ))
        if len(vectors) > 1:
            break
    if len(vectors) != 1:
        return None, (f"члены экземпляра дают {len(vectors)} разных векторов "
                      "сдвига — однозначного смещения у него нет")
    return next(iter(vectors)), ""


@dataclass(frozen=True, slots=True)
class GroupLift:
    """What became of the side index's groups — by kind, separately."""

    #: Composed `create_group` operations, one per DEFINITION. References
    #: to members are in the L1 dialect (`{"ref": <node _id>}`), the same
    #: one `lift_joins` uses.
    #:
    #: 🔴 THIS IS NOT THE LANGUAGE'S READY-MADE `create_group`, AND THE
    #: DIFFERENCE IS NAMED. The op requires members as EMBEDDED, grounded
    #: op-dicts with their own `id`s, not references; embedding is the
    #: materializer's job, exactly like the ordering and program-splitting
    #: for joins. This is NOT DONE here, and it must not be passed over in
    #: silence: otherwise "lifted N" would be read as "N groups will
    #: rebuild".
    ops: tuple[dict[str, Any], ...] = ()
    #: Definitions that were read and NOT expressed, with a NAMED reason.
    refusals: tuple[GroupRefusal, ...] = ()
    #: How many definitions the index brought.
    definitions_read: int = 0
    #: How many OCCURRENCES the index brought.
    instances_read: int = 0
    #: How many occurrences are covered by lifted definitions.
    instances_covered: int = 0
    #: How many member ops sit inside lifted definitions.
    member_ops: int = 0
    #: 🔴 THE CENTRAL NUMBER OF THIS LIFTER: how many operations will NOT
    #: need to be written one by one. Counted by MEASUREMENT on the lift,
    #: not by promise: folding BY FAMILY (21.08) shrank the form by 98.3%
    #: and did not shrink a single operation, because `place_family` is
    #: still stated for every instance. A group's form is different —
    #: `placements` ride as a list inside ONE operation — and this is what
    #: that is actually worth.
    ops_not_written_individually: int = 0
    #: Occurrences whose composition diverged from the reference one (the
    #: index counts them itself).
    composition_mismatches: int = 0


def lift_groups(group_index: Any, nodes: Sequence[L1Node],
                document: L0Document) -> GroupLift:
    """Lift the side index's GROUPS into `create_group` operations.

    Input: the `group_extract` side index, the ALREADY LIFTED L1 nodes of
    the same document, and L0 itself (needed for members' coordinates:
    the offset is derived from them). Output: one operation per
    definition, plus NAMED refusals.

    WHY A GROUP, AND NOT OUR OWN REPETITION. The unit of intent in a real
    building is named by the designer himself, and the names are direct
    speech about the intent:
    `АР_Квартира_Ст_Секция 1_Тип1_3-7,9-11 этаж_кв 3_` ×12,
    `Отделка лестниц_типовой этаж` ×15. Our merkle-based repetition sees
    only 16.7–26.7% of the authored groups, and 133 of 145 forms CUT
    across their boundary — meaning geometric identity and intent carve
    up the model differently.

    WHAT THIS FUNCTION DOES NOT DO — named, not passed over in silence:

    * it does NOT embed members into the op. `create_group.members`
      requires grounded op-dicts; here there stand `{"ref": …}`
      references of the L1 dialect, and the translation is the
      materializer's job (the same seam as with `lift_joins`);
    * it does not assign the op an `id` and does not decide order;
    * it DOES NOT READ OR INVENT ROTATION. `Group` has none in the Revit
      API at all; `placements` carry only the offset, exactly as the op
      declares.

    MEASUREMENT OF 23.08.2026 (two blocks of the same complex, full set
    of indexes):

        parse             defs.  lift.  occur.  covered  NOT ONE-BY-ONE
        K6 (19,629 ops)     177     27     575       77   756  (3.85%)
        K3 (14,943 ops)     164     28     442       60   393  (2.63%)

    🔴 AND WHY THE REST DID NOT LIFT — this is the second half of the
    answer, and without it "lifted 27" would be read as "there is nothing
    else":

        K6: member stayed an atom 60 · members > 200 47 ·
            op kind does not fit 31 · member outside parse 11 · composition diverged 1
        K3: member stayed an atom 53 · members > 200 38 ·
            op kind does not fit 27 · member outside parse 14 · offset not derivable 4

    BYTES FOR COVERED OCCURRENCES (one-by-one versus as a group):

        K6  817,440 -> 371,575   −54.5%
        K3  595,595 -> 385,338   −35.3%

    🔴 AND THIS IS THE MAIN DIFFERENCE FROM FOLDING BY FAMILY. That
    (21.08) shrank the form by 98.3% and DID NOT SHRINK A SINGLE
    OPERATION, because `place_family` is still stated for every instance.
    Here both operations and bytes shrink, because `placements` is a LIST
    inside one operation. The caution of 21.08 is lifted by measurement,
    not by reasoning.

    🔴 BUT THE PAYOFF IS NOT WHERE IT WAS EXPECTED. Typical apartments and
    facade floors — the very units this lifter was written for — do NOT
    lift at all: the former run into member-atoms, the latter into our
    own ceiling of 200 (`АР_Фасад_N этаж_` carries 334–413 members). What
    lifts are smaller things:
    `Фасад_ГБ под окнами_2+` (×10), `Кондиционеры 2-9 NEW_` (×10),
    `Мусорные баки_` (×24).
    """
    from kir.reverse_contract import assert_composed_emission

    # THE REVERSE-PASS BOUNDARY IS EXECUTABLE, NOT DECLARED, exactly as
    # with `lift_joins` and `_op_node`.
    assert_composed_emission("create_group")

    bundle = parse_group_index(group_index)
    if bundle is None:
        return GroupLift()
    index = bundle.get("group_index") or {}
    definitions = index.get("definitions") or {}
    instances = index.get("instances") or {}
    mismatches = index.get("composition_mismatches") or []
    mismatched_instances = {
        row.get("instance_id") for row in mismatches
        if isinstance(row, Mapping)
    }

    node_by_source = {node["source_element_id"]: node for node in nodes}
    elements_by_id = {
        element.element_id: element for element in document.elements}

    ops: list[dict[str, Any]] = []
    refusals: list[GroupRefusal] = []
    covered = 0
    member_ops = 0
    saved = 0

    for type_id in sorted(definitions):
        definition = definitions[type_id] or {}
        name = definition.get("group_type_name") or ""

        def refuse(reason: GroupLiftReason, detail: str) -> None:
            refusals.append(GroupRefusal(type_id, name, reason, detail))

        slots = definition.get("slots") or []
        members = [
            slot.get("reference_member_id") for slot in slots
            if isinstance(slot, Mapping)
        ]
        instance_ids = list(definition.get("instance_ids") or ())
        if not members:
            refuse(GroupLiftReason.DEFINITION_HAS_NO_MEMBERS,
                   "у определения нет ни одного слота")
            continue
        # THE CEILING IS CHECKED FIRST, AND THIS IS DELIBERATE: it is
        # ABOUT US, and naming it before facts about the building is more
        # honest — otherwise a group of 400 members, one of which also
        # happens to be an atom, would be reported as "a member stayed an
        # atom", and the work would be ordered as a lift instead of a
        # ceiling fix.
        if len(members) > _GROUP_MEMBER_CEILING:
            refuse(GroupLiftReason.MEMBER_COUNT_OVER_CEILING,
                   f"членов {len(members)}, а `create_group.members` "
                   f"принимает не больше {_GROUP_MEMBER_CEILING} — это НАШ "
                   "потолок, а не факт о здании")
            continue
        blocked = False
        for member_id in members:
            node = node_by_source.get(member_id)
            if node is None:
                refuse(GroupLiftReason.MEMBER_OUTSIDE_SNAPSHOT,
                       f"слот называет {member_id}, но среди прочитанных "
                       "элементов его нет — сослаться не на что")
                blocked = True
                break
            if node.get("kind") != "op":
                reason = node.get("reason") or {}
                refuse(GroupLiftReason.MEMBER_STAYED_ATOM,
                       f"{member_id} остался атомом ({node.get('category')}): "
                       f"{reason.get('code')} — {reason.get('detail')}")
                blocked = True
                break
            op_name = node.get("op_name")
            if not _group_member_eligible(op_name, node.get("params")):
                refuse(GroupLiftReason.MEMBER_OP_INELIGIBLE,
                       f"{member_id} поднят как {op_name!r}, а членом группы "
                       "может быть только одиночная create-операция с ОДНИМ "
                       "элементом-результатом")
                blocked = True
                break
        if blocked:
            continue

        reference_id = definition.get("reference_instance_id")
        placements: list[list[float]] = []
        for instance_id in instance_ids:
            if instance_id == reference_id:
                continue
            if instance_id in mismatched_instances:
                refuse(GroupLiftReason.COMPOSITION_MISMATCH,
                       f"состав вхождения {instance_id} разошёлся с "
                       "эталонным — ставить определение здесь было бы "
                       "тихой потерей")
                blocked = True
                break
            other = instances.get(instance_id) or {}
            offset, why = _instance_offset(
                members, other.get("member_ids") or (), elements_by_id)
            if offset is None:
                refuse(
                    GroupLiftReason.PLACEMENT_NOT_DERIVABLE
                    if "нет точки" in why
                    else GroupLiftReason.PLACEMENT_AMBIGUOUS,
                    f"вхождение {instance_id}: {why}")
                blocked = True
                break
            placements.append([offset[0], offset[1], offset[2]])
        if blocked:
            continue

        ops.append({
            "op_name": "create_group",
            "params": {
                "members": [
                    {"ref": node_by_source[member_id]["_id"]}
                    for member_id in members
                ],
                "placements": placements,
                "name": name,
            },
            "sources": tuple(members),
        })
        covered += len(instance_ids)
        member_ops += len(members)
        # One by one these occurrences would cost
        # len(members) * len(instance_ids) operations; as a group —
        # len(members) members plus the operation itself.
        saved += max(
            len(members) * len(instance_ids) - len(members) - 1, 0)

    return GroupLift(
        ops=tuple(ops),
        refusals=tuple(refusals),
        definitions_read=len(definitions),
        instances_read=len(instances),
        instances_covered=covered,
        member_ops=member_ops,
        ops_not_written_individually=saved,
        composition_mismatches=len(mismatches),
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
    # Deferral is required not only by KIND (doors, windows, panels), but
    # also by every element whose host is DECLARED by a side-index
    # record — otherwise its reference would depend on the order of L0
    # rows. See `_host_pending`.
    отложены = {
        element.element_id
        for element in document.elements
        if element.category in _DEFERRED_CATEGORIES
        # 🔴 THE INDEX IS TAKEN FROM THE CONTEXT, NOT FROM THE RAW
        # PARAMETER.
        # The first edition called `.get` on the parameter itself and
        # failed with `AttributeError: 'FamilyPlacementExtraction' object
        # has no attribute 'get'`: on the outside the index arrives as an
        # OBJECT, and it becomes a mapping in `_context`. Five idempotence
        # tests caught this immediately.
        or _host_pending(element, context.family_placement_index)
    }

    for index, element in enumerate(document.elements):
        if element.element_id in отложены:
            continue
        node, diagnostic = _lift_one(element, context, nodes_by_source)
        nodes[index] = node
        nodes_by_source[element.element_id] = node
        if collect_diagnostics and diagnostic is not None:
            diagnostics.append(diagnostic)

    for index, element in enumerate(document.elements):
        if element.element_id not in отложены:
            continue
        if (element.category in _REFERENCING_ANNOTATION_CATEGORIES):
            continue      # tags and dimensions — as the THIRD pass, as it was before
        node, diagnostic = _lift_one(element, context, nodes_by_source)
        nodes[index] = node
        nodes_by_source[element.element_id] = node
        if collect_diagnostics and diagnostic is not None:
            diagnostics.append(diagnostic)

    # THIRD PASS — REFERENCING ANNOTATION (TAGS AND DIMENSIONS), and it must
    # be exactly third.
    #
    # A tag references ANY document element, including a door or window,
    # which are themselves lifted in the second pass. Lift it earlier, and a
    # tag on a door would get `missing_reference` not because the door
    # doesn't exist, but because it hasn't been reached yet: a refusal that
    # depends on the lift's internal order, not on the model. This is the
    # same law that established the second pass for doors (a reference must
    # not depend on element order in L0), applied one step further.
    #
    # THE DIMENSION LANDED HERE FOR THE SAME REASON, measured rather than
    # assumed: while it was lifted in the first pass, a dimension between
    # two ordinary walls refused with `missing_reference` on the very FIRST
    # reference — the walls existed in L0, but there was no node for them
    # yet. The refusal would read as "these elements aren't in the model,"
    # when the truth was "the lift hadn't reached them yet."
    for index, element in enumerate(document.elements):
        if element.category not in _REFERENCING_ANNOTATION_CATEGORIES:
            continue
        node, diagnostic = _lift_one(element, context, nodes_by_source)
        nodes[index] = node
        nodes_by_source[element.element_id] = node
        if collect_diagnostics and diagnostic is not None:
            diagnostics.append(diagnostic)

    # A CUT LINE THAT HAS NO COUNTERPART IN L0 DOES NOT BECOME A NODE.
    #
    # The first edit of this wave synthesized such a node from a side
    # index — and the live v14 run stopped exactly on it:
    # FoldError('L0/L1 source mismatch: missing=0, invented=122'). The
    # census law is right: a node must have a SOURCE IN L0, otherwise the
    # lift invents elements that reading never saw. This is fixed on the
    # reading side — cut-line categories were added to the extractor
    # table — and what remains here is an honest diagnosis for the case
    # when a line exists in the index but not in L0 (a budget slice, a
    # foreign carrier kind, an old decompile).
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
    join_index: Any = None,
    group_index: Any = None,
) -> LiftResult:
    """Lift and retain one typed diagnostic for each atom fallback.

    🔴 `join_index` COMES LAST, AND FOR A DIFFERENT REASON THAN THE OTHERS.
    The other side indexes enrich a SINGLE element and are read inside its
    own lift. A join is a RELATION BETWEEN TWO, and it can only be
    expressed once BOTH arms have already become ops: `lift_joins` works
    over finished nodes, not over L0 rows. Hence the ordering, and hence
    its own refusal reason (`JoinLiftReason`, not `AtomReason`) — a
    relation has no element of its own.

    `join_index is None` means "the index was NOT SUPPLIED," and then
    `joins` is also `None`. An empty `JoinLift` would mean "supplied, no
    joins" — a different statement, and substituting one for the other
    here would cost exactly the owner's complaint the lifter was written
    to answer.
    """

    result = _lift_document(
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
    # 🔴 GROUPS COME AFTER JOINS, AND FOR THE SAME REASON: both are an
    # OVERLAY on already-finished nodes, not an enrichment of a single
    # element. The only difference is that a join needs TWO lifted arms,
    # while a group needs ALL of its members at once plus coordinates from
    # L0 (the offset is derived from them).
    #
    # `group_index is None` means "the index was NOT SUPPLIED," and then
    # `groups` is also `None`. An empty `GroupLift` would mean "supplied,
    # no groups" — a different statement, and substituting one for the
    # other here would cost the conclusion "there is no design unit in
    # this building" on a document that has 177 of them.
    if join_index is not None:
        result = replace(result, joins=lift_joins(join_index, result.nodes))
    if group_index is not None:
        result = replace(result, groups=lift_groups(
            group_index, result.nodes, document))
    return result


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
    "JOIN_RELATIONS_WITHOUT_AN_OP",
    "JoinLift",
    "JoinLiftReason",
    "JoinRefusal",
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
    "lift_joins",
    "stable_l1_id",
]
