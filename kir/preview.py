"""COMPILER EYES: a floor plan from the PROGRAM and from the DECOMPILE, by one renderer.

Why this exists
----------------
The diagnosis is stated verbatim in the header of :mod:`kir.acceptance`: the
same one who built it is not the one who checks it.  A witness confirms that
a wall was created and its ends are where asked — and stays silent about the
building turning out to be garbage.  On 29.07 two models delivered towers,
both witnesses wrote "shape and proportions match the task", and the
operator's verdict on both was "garbage geometry".  The only way to look was
live Revit: slow, prone to crashing, and unavailable today.

This module gives EYES without Revit.  It does not judge.  It draws what is
there, and presents a census of what is NOT in the picture.

Six laws it is written by
--------------------------
1. **TWO SOURCES, ONE RENDERER.**  ``build_program_preview`` (what I AM
   ABOUT to build, before any transaction) and ``build_model_preview``
   (what IS in the model) both reduce to one intermediate shape language
   (:class:`Poly`/:class:`Path`/:class:`Dot`/:class:`TextMark`), and exactly
   one function draws them — :func:`render_svg`.  The geometry is one, so
   the code is one too.
2. **SVG, not a raster.**  Deterministic text: it diffs, it goes into the
   receipt, and it is partially readable by a model without vision (the
   census sits as machine JSON in ``<metadata>``, every shape has a
   ``data-el``/``data-cat``).
3. **FLOOR PLAN FIRST.**  By level.  There are no sections and no 3D in
   this wave.
4. **A PREVIEW HAS NO RIGHT TO LOSE SOMETHING SILENTLY.**  This is not a
   wish but an invariant of the class: :class:`PreviewCensus` CANNOT be
   constructed if ``considered != drawn + the sum of reasons``.  The same
   trick by which :class:`~kir.emit_model.WitnessCheck` killed, by
   construction, the class of defects "the reader's marker stayed, the
   verdict was removed".  A preview that silently drops 30% of the building
   is worse than no preview at all: it lies more confidently.  What's more:
   DRAWN ≠ DRAWN EXACTLY, so the census has a third column —
   :class:`ApproxGroup` (a bbox instead of a profile, an axis instead of a
   body, an arc by sampling) — and a fourth — :class:`AnomalyGroup` (drawn,
   and the geometry is suspicious).
5. **DETERMINISM.**  The same input, the same byte.  No time, no random
   ids, no traversal of unordered sets without sorting; all numbers are
   printed by one ``_fmt``.
6. **HONESTY ABOUT THE STRENGTH OF THE CLAIM.**  A preview from the
   program is a self-check: it draws what the author DECLARED.  A preview
   from the decompile is an independent reading.  The difference must be
   VISIBLE IN THE ARTIFACT ITSELF, not implied: ``PROGRAM`` has a
   different header color, a dashed sheet border, a diagonal "DECLARED"
   watermark, and an explicit line "the model was not read".  Not letting
   the two look alike is a separate requirement, not decoration.

What this screen will NOT show is written in :data:`BLIND_SPOTS` and printed
on the sheet itself.  The list of blind spots matters more than the list of
capabilities: a plan in mm over XY knows neither heights nor vertical
datums, neither materials, nor whether the envelope closes.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path as _FsPath
from typing import Any, Iterable, Mapping, Sequence

__all__ = (
    "PREVIEW_SCHEMA",
    "PreviewError",
    "PreviewCensusError",
    "PreviewSource",
    "Assertion",
    "OmitReason",
    "ApproxReason",
    "AnomalyReason",
    "Layer",
    "Poly",
    "Path",
    "Dot",
    "TextMark",
    "DrawnElement",
    "OmissionGroup",
    "ApproxGroup",
    "AnomalyGroup",
    "PreviewCensus",
    "FloorPlan",
    "BuildingPreview",
    "build_program_preview",
    "build_model_preview",
    "census_lines",
    "program_headline",
    "program_card",
    "program_level_index",
    "journal_note_ru",
    "FOREIGN_JOURNAL_REFUSAL_RU_KEY",
    "HUMAN_ASSERTION_RU",
    "DARK_PALETTE",
    "THEMES",
    "AUDIENCES",
    "contrast_ratio",
    "INSTRUMENT_ASSERTION_RU",
    "TRANSFER_BUTTON_RU",
    "preview_snapshot",
    "render_svg",
    "BLIND_SPOTS",
)

PREVIEW_SCHEMA = "kir-preview/1"

#: How many example identifiers one census row holds.  The census must
#: NAME the reason and hand over something to check it against, but it is
#: not required to hold a hundred thousand ids in memory — on an
#: 88-megabyte L0 that is the difference between a tool and an OOM.
MAX_EXAMPLES = 5


class PreviewError(ValueError):
    """The preview cannot be constructed or rendered."""


class PreviewCensusError(PreviewError):
    """LAW #4 was violated: an element disappeared without being counted
    and named."""


# ---------------------------------------------------------------------------
# 1. Honesty vocabulary
# ---------------------------------------------------------------------------

class Assertion(str, Enum):
    """The strength of the artifact's claim.  It differs — and must look
    different."""

    #: Draws what the author DECLARED in the program.  The model was not
    #: read.
    SELF_REPORTED = "self_reported"
    #: Draws what was independently read from the document.
    INDEPENDENT = "independent"


class PreviewSource(str, Enum):
    """The moment in the lifecycle the plan was taken from."""

    PROGRAM = "program"
    MODEL = "model"

    @property
    def assertion(self) -> Assertion:
        return (Assertion.SELF_REPORTED if self is PreviewSource.PROGRAM
                else Assertion.INDEPENDENT)


class OmitReason(str, Enum):
    """The CLOSED set of reasons an element was not drawn.

    The reasons are addressed, not cosmetic, by exactly the same logic
    that made :class:`~kir.decompile.l1_schema.AtomReason` separate
    ``no_lifter`` from ``source_contract_gap``: one reason sends you to
    fix the renderer, another to fix the reading, a third is not a defect
    at all.
    """

    #: There is no geometry in any form: no curve, no point, no bbox.
    NO_GEOMETRY = "no_geometry"
    #: Only an AABB exists, and a contour is needed.  A bbox is NOT a
    #: contour: drawing a rectangle instead of a floor slab's profile
    #: means lying more confidently than drawing nothing at all.
    ONLY_BBOX = "only_bbox"
    #: Degenerate geometry: zero length, zero area, a collapsed bbox.
    DEGENERATE = "degenerate"
    #: NaN/inf in the coordinates.
    NON_FINITE = "non_finite"
    #: The curve is neither a line nor an arc (a spline, a helix) — it may
    #: not be straightened with a chord.
    UNSUPPORTED_CURVE = "unsupported_curve"
    #: The category exists in the reading, but there is no drawing rule
    #: for it.
    CATEGORY_NOT_DRAWN = "category_not_drawn"
    #: A 2D view annotation, not a building body.  Kept separate from the
    #: previous one on purpose: "I don't know how to draw a pipe" and "the
    #: door tag belongs to the view, not the model" are different facts,
    #: and they are fixed in different places.
    ANNOTATION_NOT_MODEL = "annotation_not_model"
    #: The element is not visible in plan by construction (the level is a
    #: section datum).
    NOT_VISIBLE_IN_PLAN = "not_visible_in_plan"
    #: Derived geometry: a curtain-wall panelization diagram is generated
    #: by the curtain wall.
    DERIVED_GEOMETRY = "derived_geometry"
    #: The element could not be assigned to any floor.
    LEVEL_UNKNOWN = "level_unknown"
    #: The element is assigned to a floor that was not drawn in this run.
    #: NOT a defect, but also NOT silence: without this row, a run over
    #: three floors of a 59-story tower would show a denominator that
    #: looks like full coverage.
    LEVEL_NOT_IN_RUN = "level_not_in_run"
    #: Opening: the host is not named.
    HOST_UNKNOWN = "host_unknown"
    #: Opening: the host is named, but its geometry is absent — there is
    #: nothing to draw on the wall.
    HOST_NOT_DRAWABLE = "host_not_drawable"
    #: Program: the operation has no drawing rule.
    OP_NOT_DRAWN = "op_not_drawn"
    #: Program: the level selector does not reduce to a plan (by=default,
    #: etc.).
    SELECTOR_UNRESOLVED = "selector_unresolved"
    #: Program: the operation HAS NO LEVEL FIELD AT ALL.
    #:
    #: 🔴 SEPARATE FROM `SELECTOR_UNRESOLVED`, FOR THE SAME REASON
    #: `NOT_AN_OP` WAS SEPARATED FROM IT ON 04.08. That case was already
    #: worked through: the plan said "the level selector does not reduce
    #: to a plan" about an input that has no level field at all, and the
    #: model went off to fix levels.
    #:
    #: The measurement of 21.08 showed the case came back from another
    #: side. A nighttime expressiveness wave introduced operations
    #: WITHOUT a level by construction — `create_surface` (fields:
    #: surface, category, name), `create_solid_boolean`,
    #: `create_directshape`: they hang in space, not on a floor. All of
    #: them fell into `SELECTOR_UNRESOLVED`, and the census explained the
    #: disappearance of a NURBS surface as a "level selector" issue.
    #:
    #: The distinction is asked of the REGISTRY, not written as a list of
    #: names: a list would diverge from the language on the very first
    #: new operation — exactly what this class of defects is generated
    #: by.
    NO_LEVEL_SLOT = "no_level_slot"
    #: 🔴 A BODY WHOSE PLAN FOOTPRINT CANNOT BE DERIVED FROM THE INPUT
    #: (08.09.2026).
    #:
    #: Separate from `NO_GEOMETRY` and from `OP_NOT_DRAWN`, and this is
    #: not pedantry. `NO_GEOMETRY` sends the author to fix the PROGRAM
    #: ("you did not give a contour"), `OP_NOT_DRAWN` sends them to fix
    #: the RENDERER ("we don't know how to handle this kind"). Here it is
    #: neither: the kind is supported, the input is complete, and this
    #: body simply has no flat footprint by the construction of its
    #: input — for example, a revolution profile whose radial extent
    #: cannot be read. There is nothing for the author to fix, and the
    #: census, not a blank sheet, must tell them so.
    BODY_TRACE_NOT_DERIVABLE = "body_trace_not_derivable"
    #: Program: this is not a KIR operation at all — the element has no
    #: `op` key.
    #:
    #: Kept separate from `SELECTOR_UNRESOLVED` on purpose, and this is
    #: not pedantry. Before 04.08, a program envelope (`{"ops": […]}` —
    #: an element of the BATCH) and an L1 decompiler node used to fall
    #: into the same place, and the plan said "the level selector does
    #: not reduce to a plan": a claim about a field the incoming item
    #: does not have AT ALL. A model reading it goes off to fix levels —
    #: exactly the lie about the input that `KIR-V001` was set up on the
    #: verdict to forbid.
    NOT_AN_OP = "not_an_op"


def _op_has_level_slot(name: str) -> bool:
    """Whether the operation has a level FIELD — by the registry, not by
    a list of names.

    Answers the question "could this operation have named a level and did
    not" versus "it has no level by construction." The first is an
    oversight by the author, the second is a property of the language,
    and confusing them means sending someone to fix what is not there.

    If the registry is unavailable (a trimmed environment, a circular
    import), we answer YES: the previous behavior, that is,
    `selector_unresolved`. The fallback favors the old answer, not the
    new one: a new reason must appear only where it has been PROVEN.
    """
    try:
        from kir import spec as _spec
    except Exception:      # noqa: BLE001
        return True
    op = (getattr(_spec, "OPS", None) or {}).get(name)
    if op is None:
        return True
    params = getattr(op, "params", None) or getattr(op, "fields", None) or {}
    try:
        names = set(params.keys()) if hasattr(params, "keys") else {
            getattr(p, "name", p) for p in params}
    except Exception:      # noqa: BLE001
        return True
    return "level" in names


class ApproxReason(str, Enum):
    """The element is DRAWN, but not exactly. The census's third column."""

    #: The contour is taken from the AABB — this is a bbox, not a profile.
    FOOTPRINT_FROM_BBOX = "footprint_from_bbox"
    #: The thickness is unknown — the axis is drawn.
    THICKNESS_UNKNOWN = "thickness_unknown"
    #: The opening's width is unknown — a tick mark is placed.
    OPENING_WIDTH_UNKNOWN = "opening_width_unknown"
    #: The door's swing side cannot be read from the source (in L0 it is
    #: not a field, in the program it hides behind the leaf's flags) — it
    #: is shown conditionally.
    DOOR_SWING_UNKNOWN = "door_swing_unknown"
    #: The arc is represented by a sampling of points.
    ARC_SAMPLED = "arc_sampled"
    #: 🔴 THE HOST IS AN ARC, BUT THE OPENING IS COMPUTED ALONG THE CHORD
    #: (F-061, 29.08.2026). The arc EXISTS in `_WallGeom` and is sampled by
    #: the wall, but the opening's position, normal, width, and swing take
    #: only `p0 -> p1`. For a semicircle the chord is 2R against the arc's
    #: πR: the "opening wider than its host" check computes against the
    #: SHORT one and stays silent exactly where there is no room, and a
    #: position at the "crown" of the arc is projected onto the chord and
    #: drifts off. This is an ADMISSION, not a fix — computing along the
    #: arc means introducing parameterization along the arc, a normal at
    #: the point, and a local basis for the swing, that is, separate work.
    OPENING_ON_CHORD = "opening_on_chord"
    #: A room in the program is a point: Revit computes the boundary, not
    #: the author.
    ROOM_BOUNDARY_NOT_COMPUTED = "room_boundary_not_computed"
    #: 🔴 THE OPERATION HAS NO LEVEL BINDING AT ALL, and the body is shown
    #: on the single plan the program declares (08.09.2026). Bought by the
    #: owner's own turn: he asked for a cube, `create_solid_extrusion` fell
    #: into `NO_LEVEL_SLOT`, the sheet came out EMPTY — and the person saw
    #: a census of someone else's programs instead of their own body. Not
    #: drawing is more honest than silence, but it is NOT more honest than
    #: drawing it and NAMING the approximation: a DirectShape has no level
    #: binding and never will (`ops_solid`), yet the body does have a
    #: place in the plan.
    LEVEL_NOT_BOUND = "level_not_bound"
    #: The level is taken not from level_id, but from a parameter (stairs
    #: hold STAIRS_BASE_LEVEL_PARAM, the extractor reads Element.Level and
    #: returns None — a known gap, see the compiler map §8.1).
    LEVEL_VIA_PARAMETER = "level_via_parameter"
    #: 🔴 BLEND: THE PLAN SHOWS THE BOTTOM PROFILE (08.09.2026). A
    #: `create_solid_blend` has TWO profiles, lying in parallel planes at
    #: a distance of `height_mm` (`ops_solid`). Exactly one of them can be
    #: shown honestly in plan — the bottom one; the top one differs, and
    #: the side surface between them is chosen by Revit ITSELF ("blending
    #: smoothly", none of the three blend factories has a volume in
    #: closed form). Drawing an "average" would mean inventing a contour
    #: that exists in no section at all.
    BLEND_TOP_PROFILE_DIFFERS = "blend_top_profile_differs"
    #: 🔴 REVOLVE: THE FOOTPRINT IS AN ANNULAR SECTOR, NOT THE PROFILE
    #: (08.09.2026). The `create_solid_revolve` profile is read in AXIAL
    #: coordinates: the contour's x is the RADIUS from the axis, y is the
    #: elevation along the axis (`ops_solid`: "The loops must lie in the
    #: xz coordinate plane… where x >= 0"). Printing its points in plan
    #: would be a lie more confident than a blank sheet: it is a different
    #: coordinate system. What is output in plan is what can be derived in
    #: closed form and what the registry itself declares as its witness —
    #: "bbox extents == the swept annular sector of the profile": a sector
    #: of radii [min x, max x] over an angle of `sweep_deg` from the world
    #: +X axis around `axis_xy_mm`.
    REVOLVE_TRACE_IS_SWEPT_SECTOR = "revolve_trace_is_swept_sector"


class AnomalyReason(str, Enum):
    """Drawn, and the geometry is suspicious. Exactly what this screen
    exists for.

    This is NOT acceptance and NOT a verdict: the list is knowingly
    incomplete, and an anomaly does not mean a defect. It means "look
    here."
    """

    #: An opening entirely outside its own wall.
    OPENING_OUTSIDE_HOST = "opening_outside_host"
    #: An opening wider than the wall it sits in.
    OPENING_WIDER_THAN_HOST = "opening_wider_than_host"
    #: Two walls with matching endpoints (a duplicate).
    COINCIDENT_WALLS = "coincident_walls"
    #: A room with zero area (it did not close).
    ROOM_NOT_ENCLOSED = "room_not_enclosed"
    #: An element lying far outside the cloud of the rest — "runaway"
    #: geometry.
    FAR_OUTLIER = "far_outlier"


#: What this screen does NOT show. Printed on the sheet itself: the list
#: of blind spots is more useful than the list of capabilities, because a
#: preview's silence reads as "everything is fine."
BLIND_SPOTS: tuple[str, ...] = (
    "высоты, отметки, вертикальные привязки — план это срез XY",
    "замкнутость оболочки и стыковку стен (стены рисуются осями и телами, "
    "а не булевым объединением)",
    "типы, материалы, слои конструкции",
    "что элемент попал не на тот уровень, если уровень назван верно",
    "перекрытия и кровли без бокового эскиза (габарит намеренно не рисуется)",
    "пересечения и коллизии в трёх измерениях",
)


class Layer(str, Enum):
    """Bottom-to-top drawing order. The value is the style key."""

    ROOM = "room"
    SLAB = "slab"
    FIXTURE = "fixture"
    MEP = "mep"
    LINE = "line"
    SEPARATION = "separation"
    GRID = "grid"
    STAIR = "stair"
    WALL = "wall"
    OPENING = "opening"
    COLUMN = "column"
    LABEL = "label"


_LAYER_ORDER: tuple[Layer, ...] = (
    Layer.ROOM, Layer.SLAB, Layer.FIXTURE, Layer.MEP, Layer.LINE,
    Layer.SEPARATION, Layer.GRID, Layer.STAIR, Layer.WALL, Layer.OPENING,
    Layer.COLUMN, Layer.LABEL,
)
_LAYER_INDEX = {layer: index for index, layer in enumerate(_LAYER_ORDER)}


# ---------------------------------------------------------------------------
# 2. The intermediate shape language — the only thing the renderer sees
# ---------------------------------------------------------------------------

Pt = tuple[float, float]


def _pt(value: Sequence[float]) -> Pt:
    x, y = float(value[0]), float(value[1])
    if not (math.isfinite(x) and math.isfinite(y)):
        raise PreviewError("координата не конечна")
    return (x, y)


@dataclass(frozen=True, slots=True)
class Poly:
    """A closed contour with holes. ``loops[0]`` is the outer one."""

    loops: tuple[tuple[Pt, ...], ...]
    role: str = "solid"          # solid | outline | void

    def points(self) -> Iterable[Pt]:
        for loop in self.loops:
            yield from loop


@dataclass(frozen=True, slots=True)
class Path:
    """An open polyline."""

    pts: tuple[Pt, ...]
    role: str = "line"           # line | thin | dashed | axis | tick

    def points(self) -> Iterable[Pt]:
        return self.pts


@dataclass(frozen=True, slots=True)
class Dot:
    xy: Pt
    r_mm: float = 60.0
    role: str = "dot"

    def points(self) -> Iterable[Pt]:
        return (self.xy,)


@dataclass(frozen=True, slots=True)
class TextMark:
    xy: Pt
    text: str
    role: str = "label"          # label | tiny | bubble
    min_area_mm2: float = 0.0    # the label is printed if there is enough room

    def points(self) -> Iterable[Pt]:
        return ()                # the label does not expand the bbox


Shape = Poly | Path | Dot | TextMark


@dataclass(frozen=True, slots=True)
class DrawnElement:
    """One drawn element and the whole truth about the quality of its
    rendering."""

    element_id: str
    category: str
    layer: Layer
    shapes: tuple[Shape, ...]
    approx: tuple[ApproxReason, ...] = ()
    anomalies: tuple[AnomalyReason, ...] = ()
    label: str = ""

    def __post_init__(self) -> None:
        if not self.element_id:
            raise PreviewError("у нарисованного элемента должен быть id")
        if not self.shapes:
            raise PreviewError(
                f"{self.element_id}: «нарисован» без единой фигуры — это "
                "потеря, а не отрисовка; такой элемент обязан уйти в перепись")

    def extent(self) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for shape in self.shapes:
            for x, y in shape.points():
                xs.append(x)
                ys.append(y)
        if not xs:
            return None
        return (min(xs), min(ys), max(xs), max(ys))


# ---------------------------------------------------------------------------
# 3. The census — LAW #4, expressed structurally
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class OmissionGroup:
    reason: OmitReason
    category: str
    count: int
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "category": self.category,
                "count": self.count, "examples": list(self.examples)}


@dataclass(frozen=True, slots=True)
class ApproxGroup:
    reason: ApproxReason
    count: int
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "count": self.count,
                "examples": list(self.examples)}


@dataclass(frozen=True, slots=True)
class AnomalyGroup:
    reason: AnomalyReason
    count: int
    examples: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"reason": self.reason.value, "count": self.count,
                "examples": list(self.examples)}


@dataclass(frozen=True, slots=True)
class PreviewCensus:
    """"Drawn 412 out of 480; not drawn 68: …" — and this is CHECKED.

    The identity ``considered == drawn + Σ count`` lives in
    ``__post_init__``, not in a test, because a test can be forgotten for
    a new path, while the constructor cannot be bypassed.
    """

    considered: int
    drawn: int
    omitted: tuple[OmissionGroup, ...] = ()
    approx: tuple[ApproxGroup, ...] = ()
    anomalies: tuple[AnomalyGroup, ...] = ()

    def __post_init__(self) -> None:
        for name in ("considered", "drawn"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PreviewCensusError(f"{name} — неотрицательное целое")
        missing = sum(group.count for group in self.omitted)
        if self.considered != self.drawn + missing:
            raise PreviewCensusError(
                f"ЗАКОН №4 нарушен: рассмотрено {self.considered}, "
                f"нарисовано {self.drawn}, названо причин на {missing}; "
                f"молча потеряно {self.considered - self.drawn - missing}")

    @property
    def omitted_total(self) -> int:
        return sum(group.count for group in self.omitted)

    @property
    def approx_total(self) -> int:
        return sum(group.count for group in self.approx)

    @property
    def anomaly_total(self) -> int:
        return sum(group.count for group in self.anomalies)

    @property
    def coverage_pct(self) -> float:
        if self.considered == 0:
            return 0.0
        return 100.0 * self.drawn / self.considered

    @property
    def vacuous(self) -> bool:
        """Nothing was considered at all. A separate field, not 100%
        coverage — the same trick as ``Verdict.vacuous`` in acceptance."""
        return self.considered == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "considered": self.considered,
            "drawn": self.drawn,
            "omitted_total": self.omitted_total,
            "coverage_pct": round(self.coverage_pct, 2),
            "vacuous": self.vacuous,
            "omitted": [group.to_dict() for group in self.omitted],
            "approx": [group.to_dict() for group in self.approx],
            "anomalies": [group.to_dict() for group in self.anomalies],
        }


class _CensusBuilder:
    """The census accumulator. Deterministic order is guaranteed by
    sorting in :meth:`build`, not by insertion order."""

    __slots__ = ("_omitted", "_approx", "_anomalies", "considered", "drawn")

    def __init__(self) -> None:
        self._omitted: dict[tuple[str, str], list[Any]] = {}
        self._approx: dict[str, list[Any]] = {}
        self._anomalies: dict[str, list[Any]] = {}
        self.considered = 0
        self.drawn = 0

    def offer(self, count: int = 1) -> None:
        self.considered += count

    def omit(self, element_id: str, category: str, reason: OmitReason,
             count: int = 1) -> None:
        key = (reason.value, category)
        slot = self._omitted.setdefault(key, [0, []])
        slot[0] += count
        if len(slot[1]) < MAX_EXAMPLES and element_id:
            slot[1].append(element_id)

    def draw(self, element: DrawnElement) -> None:
        self.drawn += 1
        for reason in element.approx:
            slot = self._approx.setdefault(reason.value, [0, []])
            slot[0] += 1
            if len(slot[1]) < MAX_EXAMPLES:
                slot[1].append(element.element_id)
        for reason in element.anomalies:
            slot = self._anomalies.setdefault(reason.value, [0, []])
            slot[0] += 1
            if len(slot[1]) < MAX_EXAMPLES:
                slot[1].append(element.element_id)

    def absorb(self, census: PreviewCensus) -> None:
        self.considered += census.considered
        self.drawn += census.drawn
        for group in census.omitted:
            slot = self._omitted.setdefault(
                (group.reason.value, group.category), [0, []])
            slot[0] += group.count
            for example in group.examples:
                if len(slot[1]) < MAX_EXAMPLES:
                    slot[1].append(example)
        for group in census.approx:
            slot = self._approx.setdefault(group.reason.value, [0, []])
            slot[0] += group.count
            for example in group.examples:
                if len(slot[1]) < MAX_EXAMPLES:
                    slot[1].append(example)
        for group in census.anomalies:
            slot = self._anomalies.setdefault(group.reason.value, [0, []])
            slot[0] += group.count
            for example in group.examples:
                if len(slot[1]) < MAX_EXAMPLES:
                    slot[1].append(example)

    def build(self) -> PreviewCensus:
        omitted = tuple(
            OmissionGroup(OmitReason(reason), category, slot[0],
                          tuple(slot[1]))
            for (reason, category), slot in sorted(
                self._omitted.items(), key=lambda kv: (-kv[1][0], kv[0]))
        )
        approx = tuple(
            ApproxGroup(ApproxReason(reason), slot[0], tuple(slot[1]))
            for reason, slot in sorted(
                self._approx.items(), key=lambda kv: (-kv[1][0], kv[0]))
        )
        anomalies = tuple(
            AnomalyGroup(AnomalyReason(reason), slot[0], tuple(slot[1]))
            for reason, slot in sorted(
                self._anomalies.items(), key=lambda kv: (-kv[1][0], kv[0]))
        )
        return PreviewCensus(self.considered, self.drawn, omitted, approx,
                             anomalies)


# ---------------------------------------------------------------------------
# 4. Plan and building
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class FloorPlan:
    source: PreviewSource
    doc_name: str
    level_name: str
    level_elevation_mm: float | None
    elements: tuple[DrawnElement, ...]
    census: PreviewCensus
    datums: tuple[DrawnElement, ...] = ()
    notes: tuple[str, ...] = ()
    #: The frame follows the CORE of the point cloud: runaway geometry has
    #: no right to drag the scale away and hide the building. It is still
    #: drawn (and clipped by the frame), and still named in the census as
    #: :attr:`AnomalyReason.FAR_OUTLIER`.
    frame_mm: tuple[float, float, float, float] | None = None
    outliers: int = 0

    @property
    def assertion(self) -> Assertion:
        return self.source.assertion

    def extents_mm(self) -> tuple[float, float, float, float] | None:
        if self.frame_mm is not None:
            return self.frame_mm
        boxes = [element.extent() for element in self.elements]
        boxes = [box for box in boxes if box is not None]
        if not boxes:
            boxes = [box for box in (d.extent() for d in self.datums)
                     if box is not None]
        if not boxes:
            return None
        return (min(b[0] for b in boxes), min(b[1] for b in boxes),
                max(b[2] for b in boxes), max(b[3] for b in boxes))

    def to_dict(self) -> dict[str, Any]:
        extents = self.extents_mm()
        return {
            "schema": PREVIEW_SCHEMA,
            "source": self.source.value,
            "assertion": self.assertion.value,
            "doc_name": self.doc_name,
            "level_name": self.level_name,
            "level_elevation_mm": self.level_elevation_mm,
            "extents_mm": list(extents) if extents else None,
            "census": self.census.to_dict(),
            "datums_drawn": len(self.datums),
            "outliers_outside_frame": self.outliers,
            "notes": list(self.notes),
        }

    @property
    def content_digest(self) -> str:
        """The plan's content signature — without it, the sheet can
        neither be compared nor placed in the receipt as evidence."""
        payload = {
            "meta": self.to_dict(),
            "elements": [
                {"id": e.element_id, "cat": e.category, "layer": e.layer.value,
                 "shapes": _shapes_digest_payload(e.shapes),
                 "approx": [r.value for r in e.approx],
                 "anomalies": [r.value for r in e.anomalies]}
                for e in self.elements
            ],
        }
        blob = json.dumps(payload, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class BuildingPreview:
    source: PreviewSource
    doc_name: str
    revit_version: str
    change_stamp: str
    plans: tuple[FloorPlan, ...]
    census: PreviewCensus
    levels_total: int = 0

    @property
    def assertion(self) -> Assertion:
        return self.source.assertion

    def plan(self, level_name: str) -> FloorPlan:
        for item in self.plans:
            if item.level_name == level_name:
                return item
        raise KeyError(level_name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PREVIEW_SCHEMA,
            "source": self.source.value,
            "assertion": self.assertion.value,
            "doc_name": self.doc_name,
            "revit_version": self.revit_version,
            "change_stamp": self.change_stamp,
            "levels_total": self.levels_total,
            "levels_rendered": len(self.plans),
            "census": self.census.to_dict(),
            "plans": [p.to_dict() for p in self.plans],
        }


def _shapes_digest_payload(shapes: Sequence[Shape]) -> list[Any]:
    out: list[Any] = []
    for shape in shapes:
        if isinstance(shape, Poly):
            out.append(["poly", shape.role,
                        [[[_round(x), _round(y)] for x, y in loop]
                         for loop in shape.loops]])
        elif isinstance(shape, Path):
            out.append(["path", shape.role,
                        [[_round(x), _round(y)] for x, y in shape.pts]])
        elif isinstance(shape, Dot):
            out.append(["dot", shape.role,
                        [_round(shape.xy[0]), _round(shape.xy[1])],
                        _round(shape.r_mm)])
        else:
            out.append(["text", shape.role,
                        [_round(shape.xy[0]), _round(shape.xy[1])], shape.text])
    return out


def _round(value: float) -> float:
    return round(float(value), 3) + 0.0


# ---------------------------------------------------------------------------
# 5. Geometric primitives
# ---------------------------------------------------------------------------

#: Shorter than this, a wall/line is considered degenerate (mm). The same
#: number as ``geom._EDGE_TOL``: below it, Revit itself refuses to build
#: the curve.
MIN_EDGE_MM = 1.0
#: The tolerance within which an opening is considered to lie on the wall
#: (mm).
OPENING_ON_HOST_TOL_MM = 25.0
#: The arc sampling step (rad). Fixed — otherwise byte-level determinism
#: is lost.
ARC_STEP_RAD = math.pi / 32.0
ARC_MAX_SAMPLES = 128


def _unit(dx: float, dy: float) -> tuple[float, float] | None:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    return (dx / length, dy / length)


def _band(a: Pt, b: Pt, thickness_mm: float) -> tuple[Pt, ...]:
    """The wall body: a rectangle of width ``thickness_mm`` around the
    axis a→b."""
    direction = _unit(b[0] - a[0], b[1] - a[1])
    if direction is None:
        raise PreviewError("нулевая ось — тело не построить")
    nx, ny = -direction[1] * thickness_mm / 2.0, direction[0] * thickness_mm / 2.0
    return ((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
            (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny))


def _sample_arc(center: Sequence[float], radius: float,
                x_axis: Sequence[float], y_axis: Sequence[float],
                a0: float, a1: float) -> tuple[Pt, ...]:
    span = a1 - a0
    steps = int(math.ceil(abs(span) / ARC_STEP_RAD))
    steps = max(4, min(ARC_MAX_SAMPLES, steps))
    pts: list[Pt] = []
    for i in range(steps + 1):
        ang = a0 + span * i / steps
        ca, sa = math.cos(ang), math.sin(ang)
        pts.append((center[0] + radius * (ca * x_axis[0] + sa * y_axis[0]),
                    center[1] + radius * (ca * x_axis[1] + sa * y_axis[1])))
    return tuple(pts)


def _arc_through(a: Pt, mid: Pt, b: Pt) -> tuple[Pt, ...]:
    """Sampling an arc from three points. The degenerate case is the
    segment a→b."""
    ax, ay = a
    bx, by = mid
    cx, cy = b
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return (a, mid, b)
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    radius = math.hypot(ax - ux, ay - uy)
    if not math.isfinite(radius) or radius < 1e-6 or radius > 1e9:
        return (a, mid, b)
    t0 = math.atan2(ay - uy, ax - ux)
    tm = math.atan2(by - uy, bx - ux)
    t1 = math.atan2(cy - uy, cx - ux)
    # Orient it so the midpoint lies between the endpoints.
    two_pi = 2.0 * math.pi
    forward = (t1 - t0) % two_pi
    mid_forward = (tm - t0) % two_pi
    span = forward if mid_forward <= forward else forward - two_pi
    return _sample_arc((ux, uy), radius, (1.0, 0.0), (0.0, 1.0), t0, t0 + span)


def _ring_area(loop: Sequence[Pt]) -> float:
    total = 0.0
    n = len(loop)
    for i in range(n):
        x0, y0 = loop[i]
        x1, y1 = loop[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return abs(total) / 2.0


def _bbox_rect(bbox_min: Sequence[float], bbox_max: Sequence[float]
               ) -> tuple[Pt, ...]:
    x0, y0 = float(bbox_min[0]), float(bbox_min[1])
    x1, y1 = float(bbox_max[0]), float(bbox_max[1])
    return ((x0, y0), (x1, y0), (x1, y1), (x0, y1))


# ---------------------------------------------------------------------------
# 6. The rule table: category -> how to draw it
# ---------------------------------------------------------------------------

class _Rule(str, Enum):
    WALL = "wall"
    SLAB = "slab"                 # contour only from the side sketch
    OPENING = "opening"
    ROOM = "room"
    GRID = "grid"
    COLUMN = "column"
    STAIR = "stair"
    CURVE_MEMBER = "curve_member"
    MEP_LINE = "mep_line"
    THIN_LINE = "thin_line"
    FIXTURE = "fixture"           # a bbox footprint, honestly named as an approximation
    ANNOTATION = "annotation"
    NOT_IN_PLAN = "not_in_plan"
    DERIVED = "derived"


_CATEGORY_RULES: dict[str, _Rule] = {
    "OST_Walls": _Rule.WALL,
    "OST_Floors": _Rule.SLAB,
    "OST_Roofs": _Rule.SLAB,
    "OST_Ceilings": _Rule.SLAB,
    "OST_Columns": _Rule.COLUMN,
    "OST_StructuralColumns": _Rule.COLUMN,
    "OST_StructuralFoundation": _Rule.FIXTURE,
    "OST_StructuralFraming": _Rule.CURVE_MEMBER,
    "OST_StructuralTruss": _Rule.CURVE_MEMBER,
    "OST_Doors": _Rule.OPENING,
    "OST_Windows": _Rule.OPENING,
    "OST_Stairs": _Rule.STAIR,
    "OST_StairsRailing": _Rule.THIN_LINE,
    "OST_Ramps": _Rule.FIXTURE,
    "OST_Rooms": _Rule.ROOM,
    "OST_MEPSpaces": _Rule.FIXTURE,
    "OST_Areas": _Rule.FIXTURE,
    "OST_Grids": _Rule.GRID,
    "OST_Levels": _Rule.NOT_IN_PLAN,
    "OST_RoomSeparationLines": _Rule.THIN_LINE,
    "OST_Lines": _Rule.THIN_LINE,
    "OST_PipeCurves": _Rule.MEP_LINE,
    "OST_DuctCurves": _Rule.MEP_LINE,
    "OST_FlexPipeCurves": _Rule.MEP_LINE,
    "OST_FlexDuctCurves": _Rule.MEP_LINE,
    "OST_CableTray": _Rule.MEP_LINE,
    "OST_Conduit": _Rule.MEP_LINE,
    "OST_PipeInsulations": _Rule.MEP_LINE,
    "OST_DuctInsulations": _Rule.MEP_LINE,
    "OST_DuctLinings": _Rule.MEP_LINE,
    "OST_CurtainWallPanels": _Rule.CURVE_MEMBER,
    "OST_CurtainWallMullions": _Rule.FIXTURE,
    "OST_CurtaSystem": _Rule.FIXTURE,
    "OST_CurtainGridsWall": _Rule.DERIVED,
    "OST_CurtainGridsRoof": _Rule.DERIVED,
    "OST_CurtainGridsCurtaSystem": _Rule.DERIVED,
    "OST_Furniture": _Rule.FIXTURE,
    "OST_Casework": _Rule.FIXTURE,
    "OST_PlumbingFixtures": _Rule.FIXTURE,
    "OST_SpecialityEquipment": _Rule.FIXTURE,
    "OST_MechanicalEquipment": _Rule.FIXTURE,
    "OST_ElectricalEquipment": _Rule.FIXTURE,
    "OST_ElectricalFixtures": _Rule.FIXTURE,
    "OST_LightingFixtures": _Rule.FIXTURE,
    "OST_LightingDevices": _Rule.FIXTURE,
    "OST_TelephoneDevices": _Rule.FIXTURE,
    "OST_Sprinklers": _Rule.FIXTURE,
    "OST_DuctTerminal": _Rule.FIXTURE,
    "OST_DuctFitting": _Rule.FIXTURE,
    "OST_PipeFitting": _Rule.FIXTURE,
    "OST_PipeAccessory": _Rule.FIXTURE,
    "OST_CableTrayFitting": _Rule.FIXTURE,
    "OST_ConduitFitting": _Rule.FIXTURE,
    "OST_GenericModel": _Rule.FIXTURE,
    "DirectShape": _Rule.FIXTURE,
    "ImportInstance": _Rule.FIXTURE,
    "OST_RasterImages": _Rule.ANNOTATION,
    "OST_Dimensions": _Rule.ANNOTATION,
    "OST_TextNotes": _Rule.ANNOTATION,
    "OST_SpotElevations": _Rule.ANNOTATION,
    "OST_SpotSlopes": _Rule.ANNOTATION,
    "OST_GenericAnnotation": _Rule.ANNOTATION,
    "OST_DetailComponents": _Rule.ANNOTATION,
    "OST_RoomTags": _Rule.ANNOTATION,
    "OST_DoorTags": _Rule.ANNOTATION,
    "OST_WallTags": _Rule.ANNOTATION,
    "OST_FloorTags": _Rule.ANNOTATION,
    "OST_AreaTags": _Rule.ANNOTATION,
    "OST_StairsRailingTags": _Rule.ANNOTATION,
    "OST_StructuralFramingTags": _Rule.ANNOTATION,
    "OST_MechanicalEquipmentTags": _Rule.ANNOTATION,
    "OST_MaterialTags": _Rule.ANNOTATION,
    "OST_MultiCategoryTags": _Rule.ANNOTATION,
}

_RULE_LAYER: dict[_Rule, Layer] = {
    _Rule.WALL: Layer.WALL,
    _Rule.SLAB: Layer.SLAB,
    _Rule.OPENING: Layer.OPENING,
    _Rule.ROOM: Layer.ROOM,
    _Rule.GRID: Layer.GRID,
    _Rule.COLUMN: Layer.COLUMN,
    _Rule.STAIR: Layer.STAIR,
    _Rule.CURVE_MEMBER: Layer.LINE,
    _Rule.MEP_LINE: Layer.MEP,
    _Rule.THIN_LINE: Layer.SEPARATION,
    _Rule.FIXTURE: Layer.FIXTURE,
}

#: Datum categories: they do not belong to a floor and are drawn on every
#: plan.
_DATUM_CATEGORIES = frozenset({"OST_Grids"})

#: The parameters by which the level is recovered when ``level_id`` is
#: empty. The order matters and is fixed: the first match wins.
_LEVEL_PARAM_FALLBACKS: tuple[str, ...] = (
    "STAIRS_BASE_LEVEL_PARAM",
    "FAMILY_BASE_LEVEL_PARAM",
    "WALL_BASE_CONSTRAINT",
    "ROOF_BASE_LEVEL_PARAM",
    "SCHEDULE_LEVEL_PARAM",
)


# ---------------------------------------------------------------------------
# 7. FRONT END A: preview from the PROGRAM ("what I AM ABOUT to build")
# ---------------------------------------------------------------------------

_PROGRAM_LEVEL_FIELDS = ("level", "base_level", "host_level")


def _selector_key(sel: Any) -> str | None:
    """The level key from the selector. ``None`` — the selector does not
    reduce to a plan."""
    if not isinstance(sel, Mapping):
        return None
    by = sel.get("by")
    value = sel.get("value")
    if by == "name" and isinstance(value, str) and value.strip():
        return value.strip()
    if by == "ref" and isinstance(value, str) and value.strip():
        return "$" + value.strip()
    if by == "element_id" and isinstance(value, int) and not isinstance(value, bool):
        return "#" + str(value)
    return None


def _level_declarations(ops: Sequence[Mapping[str, Any]]
                        ) -> list[tuple[str, str]]:
    """[(key `$id`, floor name)] for every `create_level`, in declaration
    order."""
    out: list[tuple[str, str]] = []
    for op in ops:
        if not isinstance(op, Mapping) or op.get("op") != "create_level":
            continue
        oid = str(op.get("id", ""))
        name = op.get("name")
        out.append(("$" + oid,
                    str(name) if isinstance(name, str) and name.strip()
                    else f"уровень {oid}"))
    return out


def _level_vocabulary(
    ops: Sequence[Mapping[str, Any]],
    context: Sequence[Mapping[str, Any]] = (),
) -> tuple[dict[str, str], dict[str, str], tuple[str, ...]]:
    """THE ONLY CARRIER OF THE RULE "how a level key becomes a NAME".

    -> (key→name, name→key, names declared by the PROGRAM ITSELF).

    🔴 ONE FLOOR USED TO GET TWO NAMES, AND THIS WAS REMOVED BY THE
    MEASUREMENT OF 08.09.2026. Live-document datums come from
    `built_verdict.datum_ops`, where **the operation's `id` = the level's
    ElementId in Revit**. That means the same floor is addressed by two
    legitimate forms:

        {"by": "ref",        "value": "2607"} -> key `$2607`
        {"by": "element_id", "value": 2607}   -> key `#2607`

    The name dictionary knew the first, not the second, and the second
    printed AS ITSELF. Measured on a program with "a wall on level #2607"
    next to its own `create_level id=2607 name="Этаж 9"`: the index
    returned TWO rows — `('#2607', 1)` and `('Этаж 9', 0)`, meaning one
    floor twice, with what was built sitting on the nameless half. This is
    the very same split, "one floor — two sheets", that
    `build_program_preview` warns about, only arriving from the other
    side: not through the name, but through the address's form.

    THE CONTEXT GIVES ONLY NAMES AND NOTHING ELSE. It is not counted, not
    drawn, and enters no denominator: the census must stay about THIS
    program (P3-03), otherwise 94 out of 98 from a foreign slice would
    come back. A program's own declaration is STRONGER than the
    context's — the program knows more about itself than the session
    journal does.
    """
    свои = _level_declarations(ops)
    занято = {key for key, _ in свои}
    чужие = [(key, label) for key, label in _level_declarations(context)
             if key not in занято]
    объявлено = свои + чужие
    names: dict[str, str] = {}
    for key, label in объявлено:
        names.setdefault(key, label)
    by_label: dict[str, list[str]] = {}
    for key, label in объявлено:
        by_label.setdefault(label, []).append(key)
    # Only an UNAMBIGUOUS name is resolved: two `create_level` calls with
    # the same name are not a reason to pick either one (the same rule as
    # in `build_program_preview`).
    alias = {label: keys[0] for label, keys in by_label.items()
             if len(keys) == 1}
    ярлыки = set(by_label)
    for key, _label in объявлено:
        oid = key[1:]
        # 🔴 ONLY NUMERIC `id`s ARE RESOLVED, AND THIS IS NOT NITPICKING.
        # The equality "operation `id` = ElementId" holds EXACTLY FOR
        # LIVE-DOCUMENT DATUMS (`built_verdict.datum_ops` is what makes
        # them so). An author's `create_level id="L1"` has no relation to
        # Revit element No. …, and resolving `{"by": "element_id"}`
        # against it would mean inventing a connection.
        if not oid.isdigit():
            continue
        eid = "#" + oid
        # AMBIGUITY REMAINS UNKNOWN-NESS: if a level is NAMED "#2607",
        # then the key `#2607` could have come from either
        # `{"by": "name"}` or `{"by": "element_id"}`. There is nothing to
        # tell them apart with, so no resolution happens at all — exactly
        # as with two `create_level` calls sharing one name.
        if eid in ярлыки:
            continue
        alias.setdefault(eid, key)
    return names, alias, tuple(dict.fromkeys(label for _, label in свои))


def _program_ops(program: Any) -> list[dict[str, Any]]:
    if hasattr(program, "to_ops"):
        return list(program.to_ops())
    if isinstance(program, Mapping) and "ops" in program:
        return [dict(op) for op in program["ops"]]
    if isinstance(program, Sequence) and not isinstance(program, (str, bytes)):
        return [dict(op) for op in program]
    raise PreviewError("программа — PlannedProgram, {ops: [...]} или список опов")


def _members_out_of_groups(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expand a group into its MEMBERS — without a coordinate shift.

    🔴 MEASURED 23.08.2026, A LIVE PROGRAM RIGHT NEXT TO THE ACTUAL K3.
    A program of seven walls as one unit plus eleven placements put 84
    walls into the model — while the scene showed FOUR elements, and all
    four were rooms:

        census: considered 5, drawn 4, skipped 1
        skip: no_level_slot · create_group × 1

    The reason is named correctly ABOUT THE OP ITSELF — `create_group` has
    no level slot (`members`, `placements`, `name`) — and incorrectly
    about the subject: the decision was made on the group, and the
    renderer never went inside the members, even though EVERY member has
    a level. A reader seeing "no level field" would go off to fix levels,
    when what needed fixing was the recursion.

    The third consumer in a row not to know about the group: acceptance
    attributed all copies to a single level (fixed 23.08), the clash
    named the blindness a debt with an address, the scene discarded it.

    🔴 PLACEMENTS ARE NOT EXPANDED HERE, AND THIS IS A DECISION. A copy
    sits at the same place as the member, plus an offset; the coordinate
    shift must be KIND-DEPENDENT (a direction is not a point, the lesson
    of 21.08 cost a day), and which floor a lifted copy ends up on is not
    derivable from the program at all: the assignment is Revit's to make.
    Drawing it "approximately" would mean showing the engineer something
    that is not in the model. So this is where occupancy 0 appears —
    seven real walls instead of zero — while placements remain a named
    debt.
    """
    out: list[dict[str, Any]] = []
    for op in ops:
        if str(op.get("op", "")) != "create_group":
            out.append(op)
            continue
        members = op.get("members")
        if not isinstance(members, list):
            out.append(op)
            continue
        out.extend(dict(m) for m in members if isinstance(m, Mapping))
    return out


def build_program_preview(
    program: Any,
    *,
    doc_name: str = "(программа KIR)",
    levels: Sequence[str] | None = None,
) -> BuildingPreview:
    """The plan(s) from the PROGRAM — before any transaction.

    The strength of the claim is SELF-CHECK (:attr:`Assertion.SELF_REPORTED`):
    what is drawn is what the author DECLARED. No selector here is
    resolved against the actual document, so wall thicknesses, opening
    widths, and room boundaries are UNKNOWN — and every such unknown falls
    into the census's third column, rather than being replaced by a
    plausible number.
    """
    ops = _members_out_of_groups(_program_ops(program))
    intent = getattr(program, "intent", None)
    if intent is None and isinstance(program, Mapping):
        intent = program.get("intent")

    # ONE FLOOR — ONE SHEET, no matter how it is addressed.
    #
    # `create_wall(level={"by":"ref"})` gives the key `$L1`, while
    # `create_stairs(base_level={"by":"name"})` gives "Этаж 1": it does
    # NOT accept a `base_level` reference AT ALL, so both forms sit side
    # by side in a batch ALWAYS, not occasionally. Without resolving the
    # keys, one floor came out as TWO sheets with the same title — the
    # same split the header of `live/journal.py` warns about.
    #
    # 🔴 THE RULE LIVES IN `_level_vocabulary` AND ONLY THERE (08.09.2026).
    # A copy of its body used to sit here, and a second one in
    # `program_level_index`, and they had already diverged: the card and
    # the sheet named the same floor differently, because only one of them
    # knew the `{"by": "element_id"}` form.
    level_names, alias, _ = _level_vocabulary(ops)

    def level_key_of(op: Mapping[str, Any]) -> str | None:
        key = _op_level_key(op)
        return alias.get(key, key) if key is not None else None

    # The program's walls are hosts for openings.
    walls: dict[str, dict[str, Any]] = {}
    for op in ops:
        if op.get("op") == "create_wall":
            oid = str(op.get("id", ""))
            try:
                p0 = _pt(op["p0_mm"])
                p1 = _pt(op["p1_mm"])
            except (KeyError, TypeError, IndexError, PreviewError):
                continue
            walls[oid] = {"p0": p0, "p1": p1, "arc": op.get("arc"),
                          "level": level_key_of(op)}

    buckets: dict[str, list[DrawnElement]] = {}
    datums: list[DrawnElement] = []
    building = _CensusBuilder()
    per_level: dict[str, _CensusBuilder] = {}

    def bucket_for(key: str) -> _CensusBuilder:
        return per_level.setdefault(key, _CensusBuilder())

    # Every operation is presented to EXACTLY ONE counter: either to the
    # building (datums and unresolved selectors), or to its own floor —
    # otherwise LAW #4's identity would balance against a doubled
    # denominator, and coverage would lie downward.
    for op in ops:
        name = str(op.get("op", ""))
        oid = str(op.get("id", "")) or name
        if not name:
            # NOT AN OPERATION AT ALL. The `op` key is the one thing every
            # KIR operation has and no L1 node has (`_shape_of` in the
            # verdict stands on the same signal). Previously such an
            # element fell further down and got the diagnosis "the level
            # selector does not reduce to a plan" — a claim about a field
            # it does not have at all.
            building.offer()
            building.omit(oid, "", OmitReason.NOT_AN_OP)
            continue
        if name in ("create_grid", "create_level"):
            # A datum: lives outside the floor. create_grid is drawn on
            # every plan, create_level is not a plan object at all.
            building.offer()
            if name == "create_grid":
                drawn = _program_grid(op, oid)
                if drawn is not None:
                    datums.append(drawn)
                    building.draw(drawn)
                    continue
                building.omit(oid, name, OmitReason.DEGENERATE)
            else:
                building.omit(oid, name, OmitReason.NOT_VISIBLE_IN_PLAN)
            continue

        level_key = level_key_of(op)
        if level_key is None and name in ("create_door", "create_window"):
            host = op.get("host")
            host_ref = (host.get("value")
                        if isinstance(host, Mapping) and host.get("by") == "ref"
                        else None)
            if isinstance(host_ref, str) and host_ref in walls:
                level_key = walls[host_ref]["level"]
        приближение_уровня = False
        if level_key is None and not _op_has_level_slot(name) \
                and len(set(alias.values())) == 1 and name in _BODY_OPS:
            # 🔴 BOUGHT BY THE OWNER'S OWN TURN ON 08.09.2026: "make a
            # cube." `create_solid_extrusion` fell into `NO_LEVEL_SLOT` —
            # a DirectShape has no level binding and never will
            # (`ops_solid`) — and the program's sheet came out EMPTY. The
            # person saw a census of SOMEONE ELSE's programs instead of
            # their own cube and concluded the build had failed. The body
            # DOES have a place in the plan, so it is drawn on the single
            # plan the program declares, and the approximation IS NAMED
            # (`LEVEL_NOT_BOUND`). Single — because choosing between two
            # would be a guess, and a guess costs more here than a blank
            # sheet.
            level_key = next(iter(alias.values()))
            приближение_уровня = True
        if level_key is None:
            building.offer()
            building.omit(oid, name,
                          OmitReason.SELECTOR_UNRESOLVED
                          if _op_has_level_slot(name)
                          else OmitReason.NO_LEVEL_SLOT)
            continue

        bucket = bucket_for(level_key)
        bucket.offer()
        drawn, reason = _program_shape(op, oid, walls)
        if drawn is not None and приближение_уровня:
            drawn = DrawnElement(
                drawn.element_id, drawn.category, drawn.layer, drawn.shapes,
                approx=tuple(drawn.approx) + (ApproxReason.LEVEL_NOT_BOUND,),
                anomalies=drawn.anomalies)
        if drawn is None:
            bucket.omit(oid, name, reason or OmitReason.OP_NOT_DRAWN)
            continue
        buckets.setdefault(level_key, []).append(drawn)

    # 🔴 DUPLICATE WALLS ARE LOOKED FOR ON THE PROGRAM PATH TOO, NOT ONLY
    # ON THE MODEL PATH.
    #
    # `AnomalyReason.COINCIDENT_WALLS` is declared in the anomaly
    # vocabulary and, before 15.08.2026, was raised in EXACTLY one
    # place — `build_model_preview`, that is, against the DECOMPILED
    # building. A program declaring two walls with the same endpoints was
    # flagged with nothing at all (measured: two walls (0,0)-(6000,0) —
    # no anomalies).
    #
    # This is the same input skew that closure had: the capability exists
    # on one source and is absent on the other. And a duplicate wall is a
    # defect that is specifically the AUTHOR's: it is fixed by whoever
    # writes the program, and they must learn about it BEFORE it becomes
    # two walls in the model.
    #
    # Wall identity is computed by the SAME `_wall_identity` as the model
    # path: it knows what a retelling does not (matching endpoints alone
    # is not enough — two different arcs sharing a chord are two
    # different walls).
    _dupes = _coincident_wall_ids(walls)
    if _dupes:
        for _key, _elements in buckets.items():
            buckets[_key] = [_with_anomaly(e, AnomalyReason.COINCIDENT_WALLS)
                             if e.element_id in _dupes else e
                             for e in _elements]

    wanted = set(levels) if levels is not None else None
    plans: list[FloorPlan] = []
    for level_key in sorted(per_level):
        label = level_names.get(level_key, level_key.lstrip("$"))
        raw = buckets.get(level_key, [])
        flagged, frame, outliers = _flag_far_outliers(raw)
        bucket = per_level[level_key]
        for element in flagged:
            bucket.draw(element)
        census = bucket.build()
        if wanted is not None and label not in wanted and level_key not in wanted:
            building.offer(census.considered)
            building.omit("", f"(этаж {label})", OmitReason.LEVEL_NOT_IN_RUN,
                          count=census.considered)
            continue
        building.absorb(census)
        plans.append(FloorPlan(
            source=PreviewSource.PROGRAM,
            doc_name=doc_name,
            level_name=label,
            level_elevation_mm=_program_level_elevation(ops, level_key),
            elements=tuple(sorted(flagged, key=_sort_key)),
            census=census,
            datums=tuple(sorted(datums, key=_sort_key)),
            frame_mm=frame,
            outliers=outliers,
            notes=_notes_for(census, PreviewSource.PROGRAM,
                             str(intent or "")),
        ))

    return BuildingPreview(
        source=PreviewSource.PROGRAM,
        doc_name=doc_name,
        revit_version="(не применимо: документ не открывался)",
        change_stamp=getattr(program, "plan_digest", "") or "(нет плана)",
        plans=tuple(plans),
        census=building.build(),
        levels_total=len(per_level),
    )


def _program_level_elevation(ops: Sequence[Mapping[str, Any]],
                             level_key: str) -> float | None:
    """The level elevation declared by the PROGRAM ITSELF. `None` — it
    cannot be derived.

    NAME-BASED ADDRESSING IS ON EQUAL FOOTING WITH A REFERENCE, and before
    04.08 it was not here at all: only `$id` was resolved, and addressing
    by name printed "elev. None mm". This is a blindness on exactly the
    form the batch's own law prescribes — `create_stairs.base_level` does
    not accept a reference at all (`ref_kinds` is empty), and a
    neighboring program's level is visible only by NAME. The model's eyes
    went dark on the one form it is required to use.

    AMBIGUITY REMAINS UNKNOWN-NESS. Two `create_level` calls with the same
    name and different elevations are not a reason to "take the first
    one": a plausible number costs more here than an honest gap, because
    there is nothing to tell it apart from the correct one. Matching
    elevations create no ambiguity.
    """
    if level_key.startswith("$"):
        target, field = level_key[1:], "id"
    else:
        target, field = level_key, "name"
    found: set[float] = set()
    for op in ops:
        if op.get("op") != "create_level":
            continue
        if str(op.get(field, "")).strip() != target:
            continue
        value = op.get("elev_mm")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            found.add(float(value))
    return found.pop() if len(found) == 1 else None


def _op_level_key(op: Mapping[str, Any]) -> str | None:
    for field_name in _PROGRAM_LEVEL_FIELDS:
        if field_name in op:
            key = _selector_key(op[field_name])
            if key is not None:
                return key
    return None


def _program_grid(op: Mapping[str, Any], oid: str) -> DrawnElement | None:
    try:
        p0 = _pt(op["p0_mm"])
        p1 = _pt(op["p1_mm"])
    except (KeyError, TypeError, IndexError, PreviewError):
        return None
    if math.dist(p0, p1) < MIN_EDGE_MM:
        return None
    name = op.get("name")
    label = str(name) if isinstance(name, str) and name.strip() else oid
    return DrawnElement(oid, "create_grid", Layer.GRID,
                        (Path((p0, p1), role="axis"),
                         TextMark(p0, label, role="bubble"),
                         TextMark(p1, label, role="bubble")),
                        label=label)


#: Ops that have no level field BY CONSTRUCTION, yet DO have a place in
#: the plan.
#:
#: 🔴 THE SET WAS EXPANDED ON 08.09.2026, AND EACH MEMBER JOINED WITH ITS
#: OWN FOOTPRINT, NOT BY NAME KINSHIP. The previous edition held one
#: extrusion here and named the reason: "their plan footprint cannot be
#: derived from the profile in one line, and it may not be invented." The
#: argument is true for the PROFILE and false for the FOOTPRINT:
#:
#:   * `create_solid_blend` — both profiles lie in PARALLEL XY planes
#:     (`ops_solid`: "one frame plus a height"), so the bottom profile is
#:     a ready-made footprint, and its difference from the top one is a
#:     NAMED approximation (`BLEND_TOP_PROFILE_DIFFERS`), not a guess;
#:   * `create_solid_revolve` — the profile does NOT lie in the plane at
#:     all (axial coordinates), but the footprint can be derived in
#:     closed form and is declared as a witness by the registry itself:
#:     "bbox extents == the swept annular sector of the profile". That is
#:     what is drawn, not the profile's points
#:     (`REVOLVE_TRACE_IS_SWEPT_SECTOR`).
#:
#: What could NOT be derived goes into `BODY_TRACE_NOT_DERIVABLE`, that
#: is, into the census with a name, not into a blank sheet.
_BODY_OPS: frozenset[str] = frozenset({
    "create_solid_extrusion", "create_solid_blend", "create_solid_revolve"})

#: Bodies whose footprint is the BOTTOM profile in plan (the top one
#: differs).
_BLEND_BODY_OPS: frozenset[str] = frozenset({"create_solid_blend"})

#: Bodies whose footprint is an annular sector around a vertical axis.
_REVOLVE_BODY_OPS: frozenset[str] = frozenset({"create_solid_revolve"})


def _profile_loops(profile: Any) -> tuple[tuple[Pt, ...], ...]:
    """Profile contours into the plan. If the shape is not understood, we
    return empty — we do not guess."""
    if not isinstance(profile, Mapping):
        return ()
    loops: list[tuple[Pt, ...]] = []
    for region in (profile.get("outer"),) + tuple(profile.get("holes") or ()):
        if not isinstance(region, Mapping):
            continue
        shape = region.get("shape")
        if shape == "rect":
            origin = region.get("origin") or (0.0, 0.0)
            size = region.get("size_mm")
            if not (isinstance(size, Sequence) and len(size) == 2):
                continue
            try:
                x0, y0 = float(origin[0]), float(origin[1])
                w, h = float(size[0]), float(size[1])
            except (TypeError, ValueError, IndexError):
                continue
            loops.append(((x0, y0), (x0 + w, y0), (x0 + w, y0 + h),
                          (x0, y0 + h)))
        elif shape == "poly":
            points = region.get("points_mm")
            if not isinstance(points, Sequence) or len(points) < 3:
                continue
            try:
                loops.append(tuple((float(p[0]), float(p[1]))
                                   for p in points))
            except (TypeError, ValueError, IndexError):
                continue
    return tuple(loops)


def _revolve_trace(op: Mapping[str, Any]) -> tuple[tuple[Pt, ...], ...]:
    """THE PLAN FOOTPRINT OF A REVOLVE BODY. Empty means it cannot be
    derived, and this IS NAMED.

    The profile is read in AXIAL coordinates: the contour's `x` is the
    radius from the axis, `y` is the elevation along the axis
    (`ops_solid.create_solid_revolve`, a requirement of Revit itself). The
    body's plan projection is an annular sector of radii [min x, max x]
    over an angle of `sweep_deg`, measured from the world +X axis; this is
    exactly what the registry declares as its witness ("the swept annular
    sector of the profile"). The axis is a VERTICAL line through
    `axis_xy_mm` — there is no tilted axis in v1 — so the sector is
    computed in closed form, not by sampling the body.
    """
    loops = _profile_loops(op.get("profile"))
    if not loops:
        return ()
    xs = [pt[0] for loop in loops for pt in loop]
    r0, r1 = min(xs), max(xs)
    if not (math.isfinite(r0) and math.isfinite(r1)) or r1 - r0 < MIN_EDGE_MM:
        return ()
    r0 = max(0.0, r0)
    axis = op.get("axis_xy_mm")
    try:
        centre = _pt(axis)
    except (TypeError, IndexError, PreviewError):
        return ()
    sweep = op.get("sweep_deg")
    if not isinstance(sweep, (int, float)) or isinstance(sweep, bool):
        return ()
    a1 = math.radians(max(1.0, min(360.0, float(sweep))))
    ex, ey = (1.0, 0.0), (0.0, 1.0)
    внешняя = _sample_arc(centre, r1, ex, ey, 0.0, a1)
    if a1 >= 2.0 * math.pi - 1e-9:
        # A full revolution: the outer circle, the inner one is a hole,
        # not a slice.
        if r0 < MIN_EDGE_MM:
            return (внешняя,)
        return (внешняя, tuple(reversed(_sample_arc(centre, r0, ex, ey,
                                                    0.0, a1))))
    if r0 < MIN_EDGE_MM:
        # A sector down to the axis: it closes at the axis's own point,
        # not with a zero-radius arc — otherwise the contour would
        # collapse into a segment.
        return (внешняя + (centre,),)
    return (внешняя + tuple(reversed(_sample_arc(centre, r0, ex, ey, 0.0, a1))),)


def _loop_centroid(loop: Sequence[Pt]) -> Pt:
    return (sum(p[0] for p in loop) / len(loop),
            sum(p[1] for p in loop) / len(loop))


def _program_shape(
    op: Mapping[str, Any], oid: str, walls: Mapping[str, dict[str, Any]],
) -> tuple[DrawnElement | None, OmitReason | None]:
    name = str(op.get("op", ""))
    try:
        if name == "create_wall":
            p0 = _pt(op["p0_mm"])
            p1 = _pt(op["p1_mm"])
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            approx = [ApproxReason.THICKNESS_UNKNOWN]
            arc = op.get("arc")
            if isinstance(arc, Mapping) and arc.get("curve_type") == "Arc":
                pts = _sample_arc(arc["center_mm"], float(arc["radius_mm"]),
                                  arc["x_axis"], arc["y_axis"],
                                  float(arc["start_angle_rad"]),
                                  float(arc["end_angle_rad"]))
                approx.append(ApproxReason.ARC_SAMPLED)
                shapes: tuple[Shape, ...] = (Path(pts, role="spine"),)
            else:
                shapes = (Path((p0, p1), role="spine"),)
            return DrawnElement(oid, name, Layer.WALL, shapes,
                                approx=tuple(approx)), None

        if name in _BODY_OPS:
            approx_body: tuple[ApproxReason, ...] = ()
            if name in _REVOLVE_BODY_OPS:
                loops = _revolve_trace(op)
                if not loops:
                    # A NAMED REFUSAL, not "no geometry": the author's
                    # input is complete, there is nothing for them to
                    # fix — it is the FOOTPRINT that cannot be derived.
                    return None, OmitReason.BODY_TRACE_NOT_DERIVABLE
                approx_body = (ApproxReason.REVOLVE_TRACE_IS_SWEPT_SECTOR,
                               ApproxReason.ARC_SAMPLED)
            else:
                loops = _profile_loops(op.get("profile"))
                if not loops:
                    return None, OmitReason.NO_GEOMETRY
                if name in _BLEND_BODY_OPS:
                    approx_body = (ApproxReason.BLEND_TOP_PROFILE_DIFFERS,)
            return DrawnElement(
                oid, name, Layer.SLAB,
                (Poly(loops, role="solid"),
                 TextMark(_loop_centroid(loops[0]),
                          str(op.get("name") or oid)[:22], role="label")),
                approx=approx_body,
            ), None

        if name in ("create_door", "create_window"):
            host = op.get("host")
            if not (isinstance(host, Mapping) and host.get("by") == "ref"):
                return None, OmitReason.HOST_UNKNOWN
            host_id = str(host.get("value", ""))
            wall = walls.get(host_id)
            if wall is None:
                return None, OmitReason.HOST_NOT_DRAWABLE
            offset = op.get("offset_mm")
            if not isinstance(offset, (int, float)) or isinstance(offset, bool):
                return None, OmitReason.NO_GEOMETRY
            p0, p1 = wall["p0"], wall["p1"]
            direction = _unit(p1[0] - p0[0], p1[1] - p0[1])
            if direction is None:
                return None, OmitReason.HOST_NOT_DRAWABLE
            length = math.dist(p0, p1)
            at = (p0[0] + direction[0] * float(offset),
                  p0[1] + direction[1] * float(offset))
            normal = (-direction[1], direction[0])
            tick = 400.0
            shapes = (
                Path(((at[0] - normal[0] * tick, at[1] - normal[1] * tick),
                      (at[0] + normal[0] * tick, at[1] + normal[1] * tick)),
                     role="tick"),
                Dot(at, r_mm=90.0),
            )
            anomalies: list[AnomalyReason] = []
            if float(offset) < -OPENING_ON_HOST_TOL_MM or \
                    float(offset) > length + OPENING_ON_HOST_TOL_MM:
                anomalies.append(AnomalyReason.OPENING_OUTSIDE_HOST)
            approx = (ApproxReason.OPENING_WIDTH_UNKNOWN,)
            if name == "create_door":
                approx = approx + (ApproxReason.DOOR_SWING_UNKNOWN,)
            return DrawnElement(oid, name, Layer.OPENING, shapes,
                                approx=approx,
                                anomalies=tuple(anomalies)), None

        if name in ("create_floor", "create_roof", "create_ceiling"):
            outline = op.get("outline")
            if not isinstance(outline, Sequence) or len(outline) < 3:
                return None, OmitReason.NO_GEOMETRY
            loop = tuple(_pt(point) for point in outline)
            if _ring_area(loop) < 1.0:
                return None, OmitReason.DEGENERATE
            loops = [loop]
            holes = op.get("holes")
            if isinstance(holes, Sequence):
                for hole in holes:
                    if isinstance(hole, Sequence) and len(hole) >= 3:
                        loops.append(tuple(_pt(point) for point in hole))
            return DrawnElement(oid, name, Layer.SLAB,
                                (Poly(tuple(loops), role="outline"),)), None

        if name == "create_room":
            xy = _pt(op["xy"])
            label = op.get("name")
            shapes = (Dot(xy, r_mm=140.0),)
            if isinstance(label, str) and label.strip():
                shapes = shapes + (TextMark(xy, label.strip(), role="label"),)
            return DrawnElement(
                oid, name, Layer.ROOM, shapes,
                approx=(ApproxReason.ROOM_BOUNDARY_NOT_COMPUTED,),
                label=str(label or "")), None

        if name == "create_column":
            xy = _pt(op["xy"])
            half = 200.0
            rect = ((xy[0] - half, xy[1] - half), (xy[0] + half, xy[1] - half),
                    (xy[0] + half, xy[1] + half), (xy[0] - half, xy[1] + half))
            return DrawnElement(oid, name, Layer.COLUMN,
                                (Poly((rect,), role="solid"),),
                                approx=(ApproxReason.FOOTPRINT_FROM_BBOX,)), None

        # wave/mep-electrical: placeholders are drawn with the same line
        # as a pipe and a duct — in the plan, that is exactly the route;
        # the `IsPlaceholder` bit does not translate into the drawing.
        if name in ("create_beam", "create_pipe", "create_duct",
                    "create_cable_tray", "create_conduit",
                    "create_pipe_placeholder", "create_duct_placeholder"):
            p0 = _pt(op["p0_mm"])
            p1 = _pt(op["p1_mm"])
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            layer = Layer.MEP if name != "create_beam" else Layer.LINE
            return DrawnElement(oid, name, layer,
                                (Path((p0, p1), role="thin"),)), None

        # A flexible run is a POLYLINE, not a segment. Drawing it by its
        # endpoints would show a route in the plan that does not exist in
        # the model: exactly the substitution because of which the
        # operation has its own kind of parameter.
        if name in ("create_flex_duct", "create_flex_pipe"):
            pts = tuple(_pt(point) for point in op["path"])
            if all(math.dist(pts[k], pts[k + 1]) < MIN_EDGE_MM
                   for k in range(len(pts) - 1)):
                return None, OmitReason.DEGENERATE
            return DrawnElement(oid, name, Layer.MEP,
                                (Path(pts, role="thin"),)), None

        if name == "place_family":
            if "xyz" in op and op["xyz"] is not None:
                xy = _pt(op["xyz"])
                return DrawnElement(oid, name, Layer.FIXTURE,
                                    (Dot(xy, r_mm=120.0),)), None
            if op.get("p0_mm") is not None and op.get("p1_mm") is not None:
                p0 = _pt(op["p0_mm"])
                p1 = _pt(op["p1_mm"])
                if math.dist(p0, p1) < MIN_EDGE_MM:
                    return None, OmitReason.DEGENERATE
                return DrawnElement(oid, name, Layer.FIXTURE,
                                    (Path((p0, p1), role="thin"),)), None
            return None, OmitReason.NO_GEOMETRY

        if name == "create_stairs":
            # A spiral stair flight (09.08): it has no straight segment AT
            # ALL, and drawing it as a straight line would show the wrong
            # staircase. The arc is sampled by the same function as an
            # arced wall — and is just as honestly marked ARC_SAMPLED.
            spiral = op.get("spiral")
            if isinstance(spiral, Mapping):
                a0 = math.radians(float(spiral["start_angle_deg"]))
                span = math.radians(float(spiral["included_angle_deg"]))
                a1 = a0 - span if spiral.get("clockwise") else a0 + span
                pts = _sample_arc(
                    (float(spiral["center_mm"][0]),
                     float(spiral["center_mm"][1])),
                    float(spiral["radius_mm"]), (1.0, 0.0), (0.0, 1.0), a0, a1)
                return DrawnElement(
                    oid, name, Layer.STAIR, (Path(pts, role="line"),),
                    approx=(ApproxReason.ARC_SAMPLED,)), None
            p0 = _pt(op["p0_mm"])
            p1 = _pt(op["p1_mm"])
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            return DrawnElement(oid, name, Layer.STAIR,
                                (Path((p0, p1), role="line"),)), None
    except (KeyError, TypeError, IndexError, ValueError):
        return None, OmitReason.NO_GEOMETRY

    return None, OmitReason.OP_NOT_DRAWN


def _sort_key(element: DrawnElement) -> tuple[int, str, int, str]:
    """Drawing order: layer, category, id. Numeric ids are sorted
    numerically, otherwise "10" would come before "9" and the order would
    depend on the identifier's width."""
    ident = element.element_id
    numeric = int(ident) if ident.isdigit() else -1
    return (_LAYER_INDEX[element.layer], element.category, numeric, ident)


# ---------------------------------------------------------------------------
# 8. FRONT END B: preview from the DECOMPILE ("what IS in the model")
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class _WallGeom:
    p0: Pt
    p1: Pt
    thickness_mm: float | None
    arc: dict[str, Any] | None
    #: 🔴 L0 NAMED THIS WALL AN ARC. "The arc is declared" and "the arc is
    #: readable" are two different facts (F-060, 29.08.2026), and only the
    #: second one used to be distinguished: a wall whose arc L0 named, but
    #: for which `curve_index` gave nothing, was drawn as a CHORD, with
    #: the census reading "drawn 1, coverage 100%". Measured: 66 points
    #: against 4 on the very same semicircle of radius 3 m. The default
    #: was false — the fix is additive, every input today behaves
    #: byte-for-byte as before.
    arc_expected: bool = False


def _coincident_wall_ids(walls: Mapping[str, Mapping[str, Any]]) -> set[str]:
    """Ids of walls that have a twin with the same identity ON THE SAME
    LEVEL.

    Identity is taken from `_wall_identity` — shared with the model path.
    Retelling it here would mean losing the decision it already contains:
    an arc is part of the identity, because two different arcs sharing a
    chord are not duplicates.

    🔴 THE LEVEL IS PART OF THE IDENTITY, AND THIS IS NOT CAUTION, IT IS A
    MEASUREMENT (15.08.2026). On the PROGRAM path, a point is
    two-dimensional: `p0_mm`/`p1_mm` carry only the plan, and the
    elevation is carried by a separate `level` field. So a key without a
    level glues a typical floor to itself across every elevation. Measured
    on an ordinary tower — 5 floors × 8 walls: **40 out of 40 flagged**,
    meaning the one observation about the assembly that made it to the
    model was 100% false on any multi-story building.

    The MODEL path (`build_model_preview`) did not suffer from this and
    could not have: there, the endpoints are three-dimensional and the
    elevation already sits inside the point. One predicate was answering
    two different questions, because the inputs have different
    dimensionality — the very input skew the call's header declares
    closed.

    The level is taken from the same record as the geometry
    (`walls[oid]["level"]`, `level_key_of(op)` is placed next to
    `p0`/`p1`). A wall without a level gets a separate `None` segment and
    is compared only with others like it: mixing it with the level «Этаж
    1» would mean guessing on the author's behalf.
    """
    seen: dict[tuple[Any, tuple[int, ...]], list[str]] = {}
    for wall_id, geom in walls.items():
        try:
            key = _wall_identity(_WallGeom(
                p0=geom["p0"], p1=geom["p1"],
                thickness_mm=None, arc=geom.get("arc")))
        except (KeyError, TypeError, ValueError):
            continue
        seen.setdefault((geom.get("level"), key), []).append(str(wall_id))
    return {wall_id for ids in seen.values() if len(ids) > 1 for wall_id in ids}


def _with_anomaly(element: DrawnElement, reason: AnomalyReason) -> DrawnElement:
    """The same element plus an anomaly. The order of anomalies is stable
    by value."""
    return DrawnElement(
        element.element_id, element.category, element.layer, element.shapes,
        element.approx,
        tuple(sorted(set(element.anomalies) | {reason}, key=lambda r: r.value)),
        element.label)


def build_model_preview(
    document: Any,
    elements: Iterable[Any],
    *,
    levels: Sequence[str] | None = None,
    curve_index: Mapping[str, Any] | None = None,
    sketch_index: Mapping[str, Any] | None = None,
) -> BuildingPreview:
    """The plan(s) from the DECOMPILE: ``L0Document`` (the header) + a
    stream of ``L0Element``.

    The strength of the claim is INDEPENDENT READING
    (:attr:`Assertion.INDEPENDENT`): this is what IS in the document, not
    what someone intended to build.

    The function is pure with respect to I/O: the element stream arrives
    as an iterator, so an 88-megabyte ``L0.jsonl`` is read exactly once
    and is never materialized in full (see :func:`preview_snapshot`).
    """
    level_by_id = {level.id: level for level in document.levels}
    rooms_by_id = {room.id: room for room in document.rooms}
    wanted_names: set[str] | None = set(levels) if levels is not None else None

    keep: dict[str, list[Any]] = {}
    walls: dict[str, _WallGeom] = {}
    building = _CensusBuilder()
    deferred: dict[str, int] = {}
    datum_rows: list[Any] = []
    routed_via_param: set[str] = set()

    # Every row of the stream is presented to EXACTLY ONE counter: the
    # building (datum / floor undetermined / floor not drawn), or its own
    # plan below. Otherwise LAW #4's identity would balance against a
    # doubled denominator.
    for element in elements:
        category = element.category
        if category in _DATUM_CATEGORIES:
            building.offer()
            datum_rows.append(element)
            continue
        if category == "OST_Walls":
            geom = _wall_geom(element, curve_index)
            if geom is not None:
                walls[element.element_id] = geom
        level_id, via = _route_level(element, level_by_id)
        if level_id is None:
            building.offer()
            building.omit(element.element_id, category, OmitReason.LEVEL_UNKNOWN)
            continue
        if via != "level_id":
            routed_via_param.add(element.element_id)
        level_name = level_by_id[level_id].name
        if wanted_names is not None and level_name not in wanted_names:
            building.offer()
            deferred[level_name] = deferred.get(level_name, 0) + 1
            continue
        keep.setdefault(level_id, []).append(element)

    for level_name in sorted(deferred):
        building.omit("", f"(этаж {level_name})", OmitReason.LEVEL_NOT_IN_RUN,
                      count=deferred[level_name])

    # Datums (grids) — once per building, drawn on every plan.
    datums: list[DrawnElement] = []
    for grid in document.grids:
        p0 = (float(grid.p0_mm[0]), float(grid.p0_mm[1]))
        p1 = (float(grid.p1_mm[0]), float(grid.p1_mm[1]))
        if math.dist(p0, p1) < MIN_EDGE_MM:
            continue
        datums.append(DrawnElement(
            grid.id, "OST_Grids", Layer.GRID,
            (Path((p0, p1), role="axis"),
             TextMark(p0, grid.name, role="bubble"),
             TextMark(p1, grid.name, role="bubble")),
            label=grid.name))
    drawn_grid_ids = {d.element_id for d in datums}
    for element in datum_rows:
        if element.element_id in drawn_grid_ids:
            building.drawn += 1
        else:
            building.omit(element.element_id, element.category,
                          OmitReason.DEGENERATE)

    plans: list[FloorPlan] = []
    ordered_levels = [level for level in document.levels
                      if wanted_names is None or level.name in wanted_names]
    for level in ordered_levels:
        rows = keep.get(level.id, [])
        census_builder = _CensusBuilder()
        drawn_elements: list[DrawnElement] = []
        wall_key_seen: dict[tuple[int, int, int, int], list[str]] = {}

        for element in sorted(rows, key=_l0_sort_key):
            census_builder.offer()
            drawn, reason = _model_shape(
                element, walls=walls, rooms_by_id=rooms_by_id,
                curve_index=curve_index, sketch_index=sketch_index,
                via_param=element.element_id in routed_via_param)
            if drawn is None:
                census_builder.omit(element.element_id, element.category,
                                    reason or OmitReason.CATEGORY_NOT_DRAWN)
                continue
            if element.category == "OST_Walls":
                geom = walls.get(element.element_id)
                if geom is not None:
                    key = _wall_identity(geom)
                    wall_key_seen.setdefault(key, []).append(element.element_id)
            drawn_elements.append(drawn)

        duplicates = {ident for ids in wall_key_seen.values() if len(ids) > 1
                      for ident in ids}
        if duplicates:
            drawn_elements = [
                (element if element.element_id not in duplicates else
                 DrawnElement(element.element_id, element.category,
                              element.layer, element.shapes, element.approx,
                              tuple(sorted(set(element.anomalies) |
                                           {AnomalyReason.COINCIDENT_WALLS},
                                           key=lambda r: r.value)),
                              element.label))
                for element in drawn_elements
            ]
        drawn_elements, frame, outliers = _flag_far_outliers(drawn_elements)
        for element in drawn_elements:
            census_builder.draw(element)

        census = census_builder.build()
        building.absorb(census)
        plans.append(FloorPlan(
            source=PreviewSource.MODEL,
            doc_name=document.doc_name,
            level_name=level.name,
            level_elevation_mm=level.elevation_mm,
            elements=tuple(sorted(drawn_elements, key=_sort_key)),
            census=census,
            datums=tuple(sorted(datums, key=_sort_key)),
            frame_mm=frame,
            outliers=outliers,
            notes=_notes_for(census, PreviewSource.MODEL,
                             document.project_info.name or ""),
        ))

    return BuildingPreview(
        source=PreviewSource.MODEL,
        doc_name=document.doc_name,
        revit_version=document.revit_version,
        change_stamp=document.change_stamp,
        plans=tuple(plans),
        census=building.build(),
        levels_total=len(document.levels),
    )


def _l0_sort_key(element: Any) -> tuple[str, int, str]:
    ident = element.element_id
    return (element.category, int(ident) if ident.isdigit() else -1, ident)


def _wall_identity(geom: _WallGeom) -> tuple[int, ...]:
    """A wall's identity for finding duplicates: the endpoints (unordered)
    AND the arc.

    Endpoints ALONE are NOT ENOUGH: two different arcs sharing a chord are
    two different walls, and without the center and radius a "duplicate"
    would be false.
    """
    a = (int(round(geom.p0[0])), int(round(geom.p0[1])))
    b = (int(round(geom.p1[0])), int(round(geom.p1[1])))
    ends = (*a, *b) if a <= b else (*b, *a)
    if geom.arc is None:
        return ends + (0, 0, 0)
    try:
        centre = geom.arc["center_mm"]
        return ends + (int(round(float(centre[0]))),
                       int(round(float(centre[1]))),
                       int(round(float(geom.arc["radius_mm"]))))
    except (KeyError, TypeError, ValueError, IndexError):
        return ends + (0, 0, 0)


#: Below this number of drawn elements, a "cloud" is undefined, and any
#: talk of runaway geometry is moot.
OUTLIER_MIN_POPULATION = 12
#: How many median radii away from the median center an element must sit
#: to be considered a runaway. The measure is MEDIAN-based, not
#: percentile-based: the first edition took the 2nd and 98th percentile
#: and missed on k2/L16 — 44 runaways out of 1654 is 2.66%, meaning the
#: 98th percentile itself already sat inside the garbage. The median holds
#: up to 50% contamination, a percentile holds exactly as much as the
#: author happened to guess.
OUTLIER_RADIUS_FACTOR = 8.0
#: A lower tolerance bound (mm) — so the frame does not collapse for a
#: tiny model.
OUTLIER_MIN_PAD_MM = 5_000.0
#: If more than a quarter of the population turns out to be "runaway",
#: these are not outliers but two clouds, and the rule stays silent about
#: them. Better to say nothing than to call half the building garbage.
OUTLIER_MAX_SHARE = 0.25


def _median(values: Sequence[float]) -> float:
    """The median over a SORTED copy, with no interpolation at even
    length: the upper of the two middle values is taken. The rule is
    fixed so that the artifact's bytes do not depend on the version of
    the statistics module."""
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _flag_far_outliers(
    elements: Sequence[DrawnElement],
) -> tuple[list[DrawnElement], tuple[float, float, float, float] | None, int]:
    """Flag "runaway" geometry and return a frame based on the cloud's
    CORE.

    Measured 03.08 on k2/L16: 44 ``OST_TelephoneDevices`` sit 200 m east
    of a 26-meter tower. Without this rule the scale dropped from 32 to
    146 mm/px and the building occupied 12% of the sheet — 1 610 correct
    elements disappeared from view because of 44 incorrect ones. This is
    NOT cosmetics: a silent loss of readability is exactly the refusal to
    show that LAW #4 was written against. Runaway elements are still
    DRAWN (clipped by the frame, not discarded) and NAMED.
    """
    boxes = [(element, element.extent()) for element in elements]
    boxes = [(element, box) for element, box in boxes if box is not None]
    if len(boxes) < OUTLIER_MIN_POPULATION:
        if not boxes:
            return list(elements), None, 0
        return (list(elements),
                (min(b[1][0] for b in boxes), min(b[1][1] for b in boxes),
                 max(b[1][2] for b in boxes), max(b[1][3] for b in boxes)), 0)

    centres = [((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)
               for _, box in boxes]
    mx = _median([centre[0] for centre in centres])
    my = _median([centre[1] for centre in centres])
    radii = [max(abs(cx - mx), abs(cy - my)) for cx, cy in centres]
    threshold = max(_median(radii) * OUTLIER_RADIUS_FACTOR, OUTLIER_MIN_PAD_MM)
    suspects = sum(1 for radius in radii if radius > threshold)
    if suspects > len(boxes) * OUTLIER_MAX_SHARE:
        return (list(elements),
                (min(b[1][0] for b in boxes), min(b[1][1] for b in boxes),
                 max(b[1][2] for b in boxes), max(b[1][3] for b in boxes)), 0)

    kept: list[tuple[float, float, float, float]] = []
    out: list[DrawnElement] = []
    outliers = 0
    for (element, box), radius in zip(boxes, radii):
        if radius <= threshold:
            kept.append(box)
            out.append(element)
        else:
            outliers += 1
            out.append(DrawnElement(
                element.element_id, element.category, element.layer,
                element.shapes, element.approx,
                tuple(sorted(set(element.anomalies) |
                             {AnomalyReason.FAR_OUTLIER},
                             key=lambda reason: reason.value)),
                element.label))
    known = {id(element) for element, _ in boxes}
    out.extend(element for element in elements if id(element) not in known)
    if not kept:
        kept = [box for _, box in boxes]
    frame = (min(b[0] for b in kept), min(b[1] for b in kept),
             max(b[2] for b in kept), max(b[3] for b in kept))
    return out, frame, outliers


def _route_level(element: Any, level_by_id: Mapping[str, Any]
                 ) -> tuple[str | None, str]:
    """The element's level and WHERE it was taken from.

    ``level_id`` is empty for stairs for a known reason (the extractor
    reads ``Element.Level``, while a stair holds
    ``STAIRS_BASE_LEVEL_PARAM``), so falling back to the parameter is not
    a guess but a second, declared reading. It IS MARKED as an
    approximation, not passed off as direct knowledge.
    """
    if element.level_id and element.level_id in level_by_id:
        return element.level_id, "level_id"
    params = element.params or {}
    for key in _LEVEL_PARAM_FALLBACKS:
        value = params.get(key)
        if isinstance(value, str) and value in level_by_id:
            return value, key
    return None, ""


def _wall_geom(element: Any, curve_index: Mapping[str, Any] | None
               ) -> _WallGeom | None:
    thickness = element.params.get("WALL_ATTR_WIDTH_PARAM") if element.params else None
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)):
        thickness = None
    elif thickness <= 0:
        thickness = None
    arc = None
    # 🔴 "THE ARC IS DECLARED" AND "THE ARC IS READ" ARE DIFFERENT FACTS
    # (F-060). L0 distinguishes `LocationCurveKind.ARC`; the curve index
    # may be absent, empty, or carry a broken row — and in all three
    # cases the arc was silently turned into a straight line.
    arc_expected = (element.curve_kind is not None
                    and element.curve_kind.value == "arc")
    if curve_index:
        row = curve_index.get(element.element_id)
        if isinstance(row, Mapping) and row.get("curve_kind") == "arc":
            candidate = row.get("arc")
            if isinstance(candidate, Mapping):
                arc = dict(candidate)
    if element.geom_kind.value != "curve" or element.p0_mm is None or element.p1_mm is None:
        return None
    return _WallGeom(
        p0=(float(element.p0_mm[0]), float(element.p0_mm[1])),
        p1=(float(element.p1_mm[0]), float(element.p1_mm[1])),
        thickness_mm=float(thickness) if thickness is not None else None,
        arc=arc, arc_expected=arc_expected)


def _wall_centerline(geom: _WallGeom) -> tuple[tuple[Pt, ...], bool, bool]:
    """Points, WHETHER the arc was sampled, and WHETHER the DECLARED arc
    was lost.

    🔴 The third value is not a convenience (F-060, 29.08.2026). "There
    was no arc" and "there was an arc and it could not be read" show the
    person a DIFFERENT building, yet they share one chord: previously both
    cases produced `(p0, p1), False`, and a wall whose arc L0 had named
    went onto the sheet as a straight line at 100% coverage.
    """
    if geom.arc is not None:
        try:
            pts = _sample_arc(geom.arc["center_mm"], float(geom.arc["radius_mm"]),
                              geom.arc["x_axis"], geom.arc["y_axis"],
                              float(geom.arc["start_angle_rad"]),
                              float(geom.arc["end_angle_rad"]))
            return pts, True, False
        except (KeyError, TypeError, ValueError):
            # The index gave an arc, but it is broken — the loss is named
            # the same way as an absent index: to the reader, it is the
            # same thing.
            return (geom.p0, geom.p1), False, True
    return (geom.p0, geom.p1), False, geom.arc_expected


def _offset_polyline(pts: Sequence[Pt], half: float) -> tuple[Pt, ...]:
    out: list[Pt] = []
    for index, point in enumerate(pts):
        if index == 0:
            other = pts[1]
            direction = _unit(other[0] - point[0], other[1] - point[1])
        elif index == len(pts) - 1:
            other = pts[index - 1]
            direction = _unit(point[0] - other[0], point[1] - other[1])
        else:
            before, after = pts[index - 1], pts[index + 1]
            direction = _unit(after[0] - before[0], after[1] - before[1])
        if direction is None:
            direction = (1.0, 0.0)
        out.append((point[0] - direction[1] * half, point[1] + direction[0] * half))
    return tuple(out)


def _model_shape(
    element: Any, *, walls: Mapping[str, _WallGeom],
    rooms_by_id: Mapping[str, Any],
    curve_index: Mapping[str, Any] | None,
    sketch_index: Mapping[str, Any] | None,
    via_param: bool,
) -> tuple[DrawnElement | None, OmitReason | None]:
    category = element.category
    rule = _CATEGORY_RULES.get(category)
    base_approx: tuple[ApproxReason, ...] = (
        (ApproxReason.LEVEL_VIA_PARAMETER,) if via_param else ())

    if rule is None:
        return None, OmitReason.CATEGORY_NOT_DRAWN
    if rule is _Rule.ANNOTATION:
        return None, OmitReason.ANNOTATION_NOT_MODEL
    if rule is _Rule.NOT_IN_PLAN:
        return None, OmitReason.NOT_VISIBLE_IN_PLAN
    if rule is _Rule.DERIVED:
        return None, OmitReason.DERIVED_GEOMETRY

    ident = element.element_id

    if rule is _Rule.WALL:
        # A spline wall may NOT be straightened with a chord: exactly this
        # silent substitution used to pass VERIFY as exact (finding M2 of
        # the 28.07 audit), because only the endpoints are compared. A
        # refusal, not an approximation.
        if element.curve_kind is not None and element.curve_kind.value == "other":
            return None, OmitReason.UNSUPPORTED_CURVE
        geom = walls.get(ident)
        if geom is None:
            if element.geom_kind.value == "curve":
                return None, OmitReason.UNSUPPORTED_CURVE
            return None, OmitReason.NO_GEOMETRY
        if math.dist(geom.p0, geom.p1) < MIN_EDGE_MM and geom.arc is None:
            return None, OmitReason.DEGENERATE
        centerline, sampled, arc_lost = _wall_centerline(geom)
        if arc_lost:
            # 🔴 THE SAME ARGUMENT AS FOR THE SPLINE TEN LINES ABOVE: an
            # arc may NOT be straightened with a chord SILENTLY. The only
            # difference from a spline is that there the shape cannot be
            # expressed, while here it simply was not given — to the
            # reader it is the same thing: they would see a STRAIGHT wall
            # where a semicircular one stands, and the census would say
            # "coverage 100%".
            #
            # A REFUSAL, NOT AN APPROXIMATION — a fork named to the lead.
            # A refusal removes the wall from the plan and counts it in
            # the census with a reason; an approximation would have kept
            # it and required a NEW kind of `ApproxReason`, which would
            # have to be carried through to the sheet and to KUKAI. A
            # refusal was chosen: it is UNIFORM with the spline — one law,
            # not two — and unwinds in a single line.
            return None, OmitReason.UNSUPPORTED_CURVE
        approx = list(base_approx)
        if sampled:
            approx.append(ApproxReason.ARC_SAMPLED)
        if geom.thickness_mm is None:
            approx.append(ApproxReason.THICKNESS_UNKNOWN)
            shapes: tuple[Shape, ...] = (Path(centerline, role="spine"),)
        else:
            half = geom.thickness_mm / 2.0
            left = _offset_polyline(centerline, half)
            right = _offset_polyline(centerline, -half)
            shapes = (Poly((left + tuple(reversed(right)),), role="solid"),)
        return DrawnElement(ident, category, Layer.WALL, shapes,
                            approx=tuple(approx)), None

    if rule is _Rule.OPENING:
        host_id = element.host_id
        if not host_id:
            return None, OmitReason.HOST_UNKNOWN
        geom = walls.get(host_id)
        if geom is None:
            return None, OmitReason.HOST_NOT_DRAWABLE
        if element.p0_mm is None:
            return None, OmitReason.NO_GEOMETRY
        at = (float(element.p0_mm[0]), float(element.p0_mm[1]))
        direction = _unit(geom.p1[0] - geom.p0[0], geom.p1[1] - geom.p0[1])
        if direction is None:
            return None, OmitReason.HOST_NOT_DRAWABLE
        length = math.dist(geom.p0, geom.p1)
        t = ((at[0] - geom.p0[0]) * direction[0]
             + (at[1] - geom.p0[1]) * direction[1])
        width = element.params.get("FAMILY_WIDTH_PARAM") if element.params else None
        approx = list(base_approx)
        # 🔴 AN ADMISSION, NOT A FIX (F-061). An opening is computed along
        # its host's CHORD, even when the arc is read exactly. The flag is
        # set both when the arc EXISTS (`geom.arc`) and when it is
        # DECLARED but could not be read (`arc_expected`): in the second
        # case the chord likewise does not describe the wall, and the wall
        # itself has already gone into the skip list under F-060 — the
        # opening would otherwise be left hanging on a curve that is not
        # on the sheet.
        if geom.arc is not None or geom.arc_expected:
            approx.append(ApproxReason.OPENING_ON_CHORD)
        if (isinstance(width, bool) or not isinstance(width, (int, float))
                or width < MIN_EDGE_MM):
            width = 900.0
            approx.append(ApproxReason.OPENING_WIDTH_UNKNOWN)
        width = float(width)
        thickness = geom.thickness_mm if geom.thickness_mm else 200.0
        if geom.thickness_mm is None:
            approx.append(ApproxReason.THICKNESS_UNKNOWN)
        anomalies: list[AnomalyReason] = []
        if t + width / 2.0 < -OPENING_ON_HOST_TOL_MM or \
                t - width / 2.0 > length + OPENING_ON_HOST_TOL_MM:
            anomalies.append(AnomalyReason.OPENING_OUTSIDE_HOST)
        if width > length + OPENING_ON_HOST_TOL_MM:
            anomalies.append(AnomalyReason.OPENING_WIDER_THAN_HOST)

        normal = (-direction[1], direction[0])
        half_w, half_t = width / 2.0, thickness / 2.0

        def at_offset(along: float, across: float) -> Pt:
            return (geom.p0[0] + direction[0] * along + normal[0] * across,
                    geom.p0[1] + direction[1] * along + normal[1] * across)

        a0, a1 = t - half_w, t + half_w
        void = (at_offset(a0, -half_t), at_offset(a1, -half_t),
                at_offset(a1, half_t), at_offset(a0, half_t))
        shapes = [Poly((void,), role="void")]
        shapes.append(Path((at_offset(a0, -half_t), at_offset(a0, half_t)),
                           role="tick"))
        shapes.append(Path((at_offset(a1, -half_t), at_offset(a1, half_t)),
                           role="tick"))
        if category == "OST_Doors":
            approx.append(ApproxReason.DOOR_SWING_UNKNOWN)
            shapes.append(Path((at_offset(a0, 0.0), at_offset(a0, width)),
                               role="thin"))
            shapes.append(Path(_arc_through(at_offset(a0, width),
                                            at_offset(t - half_w * 0.293,
                                                      width * 0.707),
                                            at_offset(a1, 0.0)), role="thin"))
        else:
            shapes.append(Path((at_offset(a0, -half_t * 0.35),
                                at_offset(a1, -half_t * 0.35)), role="thin"))
            shapes.append(Path((at_offset(a0, half_t * 0.35),
                                at_offset(a1, half_t * 0.35)), role="thin"))
        return DrawnElement(ident, category, Layer.OPENING, tuple(shapes),
                            approx=tuple(approx),
                            anomalies=tuple(anomalies)), None

    if rule is _Rule.ROOM:
        room = rooms_by_id.get(ident)
        if room is None:
            return None, OmitReason.NO_GEOMETRY
        loops = [tuple(_pt(point) for point in loop)
                 for loop in room.boundary_loops_mm if len(loop) >= 3]
        if not loops:
            return None, OmitReason.DEGENERATE
        anomalies = ([AnomalyReason.ROOM_NOT_ENCLOSED]
                     if room.area_m2 <= 0.0 else [])
        label = room.name or ""
        area_text = f"{room.area_m2:.1f} м²"
        cx = sum(x for x, _ in loops[0]) / len(loops[0])
        cy = sum(y for _, y in loops[0]) / len(loops[0])
        min_area = _ring_area(loops[0])
        shapes = [Poly(tuple(loops), role="solid")]
        if label:
            shapes.append(TextMark((cx, cy), label, role="label",
                                   min_area_mm2=min_area))
        shapes.append(TextMark((cx, cy), area_text, role="tiny",
                               min_area_mm2=min_area))
        return DrawnElement(ident, category, Layer.ROOM, tuple(shapes),
                            approx=base_approx,
                            anomalies=tuple(anomalies), label=label), None

    if rule is _Rule.SLAB:
        profile = None
        if sketch_index:
            profile = sketch_index.get(ident)
        if not isinstance(profile, Mapping) or not profile.get("profile_available"):
            if element.bbox_min_mm is None:
                return None, OmitReason.NO_GEOMETRY
            return None, OmitReason.ONLY_BBOX
        loops = _sketch_loops(profile)
        if not loops:
            return None, OmitReason.DEGENERATE
        approx = list(base_approx)
        if any(kind == "arc" for kinds in profile.get("curve_kinds") or ()
               for kind in (kinds if isinstance(kinds, list) else [kinds])):
            approx.append(ApproxReason.ARC_SAMPLED)
        return DrawnElement(ident, category, Layer.SLAB,
                            (Poly(tuple(loops), role="outline"),),
                            approx=tuple(approx)), None

    if rule is _Rule.COLUMN:
        if element.bbox_min_mm is None or element.bbox_max_mm is None:
            if element.p0_mm is None:
                return None, OmitReason.NO_GEOMETRY
            xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
            return DrawnElement(ident, category, Layer.COLUMN,
                                (Dot(xy, r_mm=120.0),),
                                approx=base_approx), None
        rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
        if _ring_area(rect) < 1.0:
            return None, OmitReason.DEGENERATE
        return DrawnElement(ident, category, Layer.COLUMN,
                            (Poly((rect,), role="solid"),),
                            approx=base_approx + (
                                ApproxReason.FOOTPRINT_FROM_BBOX,)), None

    if rule is _Rule.STAIR:
        runs = None
        if sketch_index is not None:
            runs = (sketch_index.get("__runs__") or {}).get(ident)
        shapes = []
        if isinstance(runs, Mapping):
            for run_id in sorted(runs):
                run = runs[run_id]
                pts = run.get("points_mm") if isinstance(run, Mapping) else None
                if isinstance(pts, list) and len(pts) >= 2:
                    shapes.append(Path(tuple(_pt(p) for p in pts), role="line"))
        if shapes:
            return DrawnElement(ident, category, Layer.STAIR, tuple(shapes),
                                approx=base_approx), None
        if element.bbox_min_mm is None or element.bbox_max_mm is None:
            return None, OmitReason.NO_GEOMETRY
        rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
        if _ring_area(rect) < 1.0:
            return None, OmitReason.DEGENERATE
        return DrawnElement(ident, category, Layer.STAIR,
                            (Poly((rect,), role="outline"),),
                            approx=base_approx + (
                                ApproxReason.FOOTPRINT_FROM_BBOX,)), None

    if rule in (_Rule.CURVE_MEMBER, _Rule.MEP_LINE, _Rule.THIN_LINE):
        if element.curve_kind is not None and element.curve_kind.value == "other":
            return None, OmitReason.UNSUPPORTED_CURVE
        if element.geom_kind.value == "curve" and element.p0_mm and element.p1_mm:
            p0 = (float(element.p0_mm[0]), float(element.p0_mm[1]))
            p1 = (float(element.p1_mm[0]), float(element.p1_mm[1]))
            if math.dist(p0, p1) < MIN_EDGE_MM:
                return None, OmitReason.DEGENERATE
            approx = list(base_approx)
            pts: tuple[Pt, ...] = (p0, p1)
            if curve_index:
                row = curve_index.get(ident)
                if isinstance(row, Mapping) and row.get("curve_kind") == "arc" \
                        and isinstance(row.get("arc"), Mapping):
                    arc = row["arc"]
                    try:
                        pts = _sample_arc(arc["center_mm"],
                                          float(arc["radius_mm"]),
                                          arc["x_axis"], arc["y_axis"],
                                          float(arc["start_angle_rad"]),
                                          float(arc["end_angle_rad"]))
                        approx.append(ApproxReason.ARC_SAMPLED)
                    except (KeyError, TypeError, ValueError):
                        pts = (p0, p1)
                elif isinstance(row, Mapping) and row.get("curve_kind") == "other":
                    return None, OmitReason.UNSUPPORTED_CURVE
            role = "thin" if rule is not _Rule.THIN_LINE else "dashed"
            return DrawnElement(ident, category, _RULE_LAYER[rule],
                                (Path(pts, role=role),),
                                approx=tuple(approx)), None
        if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
            rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
            if _ring_area(rect) < 1.0:
                return None, OmitReason.DEGENERATE
            return DrawnElement(ident, category, _RULE_LAYER[rule],
                                (Poly((rect,), role="outline"),),
                                approx=base_approx + (
                                    ApproxReason.FOOTPRINT_FROM_BBOX,)), None
        return None, OmitReason.NO_GEOMETRY

    if rule is _Rule.FIXTURE:
        if element.bbox_min_mm is not None and element.bbox_max_mm is not None:
            rect = _bbox_rect(element.bbox_min_mm, element.bbox_max_mm)
            if _ring_area(rect) < 1.0:
                if element.p0_mm is None:
                    return None, OmitReason.DEGENERATE
                xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
                return DrawnElement(ident, category, Layer.FIXTURE,
                                    (Dot(xy, r_mm=80.0),),
                                    approx=base_approx), None
            return DrawnElement(ident, category, Layer.FIXTURE,
                                (Poly((rect,), role="outline"),),
                                approx=base_approx + (
                                    ApproxReason.FOOTPRINT_FROM_BBOX,)), None
        if element.p0_mm is not None:
            xy = (float(element.p0_mm[0]), float(element.p0_mm[1]))
            return DrawnElement(ident, category, Layer.FIXTURE,
                                (Dot(xy, r_mm=80.0),),
                                approx=base_approx), None
        return None, OmitReason.NO_GEOMETRY

    return None, OmitReason.CATEGORY_NOT_DRAWN


def _sketch_loops(profile: Mapping[str, Any]) -> list[tuple[Pt, ...]]:
    loops: list[tuple[Pt, ...]] = []
    exterior = profile.get("exterior_loop")
    kinds = profile.get("curve_kinds") or []
    mids = profile.get("arc_midpoints") or []
    if isinstance(exterior, list) and len(exterior) >= 3:
        loops.append(_loop_with_arcs(
            exterior,
            kinds[0] if kinds and isinstance(kinds[0], list) else None,
            mids[0] if mids and isinstance(mids[0], list) else None))
    holes = profile.get("holes")
    if isinstance(holes, list):
        for index, hole in enumerate(holes):
            if isinstance(hole, list) and len(hole) >= 3:
                kind = kinds[index + 1] if len(kinds) > index + 1 else None
                mid = mids[index + 1] if len(mids) > index + 1 else None
                loops.append(_loop_with_arcs(
                    hole, kind if isinstance(kind, list) else None,
                    mid if isinstance(mid, list) else None))
    return [loop for loop in loops if len(loop) >= 3]


def _loop_with_arcs(points: Sequence[Any], kinds: Sequence[Any] | None,
                    mids: Sequence[Any] | None) -> tuple[Pt, ...]:
    verts = [_pt(point) for point in points]
    if not kinds or not mids or len(kinds) != len(verts):
        return tuple(verts)
    out: list[Pt] = []
    count = len(verts)
    for index in range(count):
        start = verts[index]
        end = verts[(index + 1) % count]
        out.append(start)
        if kinds[index] == "arc" and index < len(mids) and mids[index]:
            try:
                mid = _pt(mids[index])
            except (PreviewError, TypeError, IndexError):
                continue
            arc = _arc_through(start, mid, end)
            out.extend(arc[1:-1])
    return tuple(out)


# ---------------------------------------------------------------------------
# 9. A convenience wrapper over the snapshot on disk
# ---------------------------------------------------------------------------

def preview_snapshot(snapshot_dir: str | _FsPath, *,
                     levels: Sequence[str] | None = None) -> BuildingPreview:
    """Read the snapshot ``backend/data/decompile/<stamp>/`` and build the
    preview.

    The ``L0.jsonl`` stream is read EXACTLY ONCE: files in this corpus run
    up to 88 MB, and materializing the whole document would cost
    gigabytes.
    """
    from kir.decompile.extract import L0JSONLReader
    from kir.decompile.snapshot_io import (read_snapshot_text,
                                                snapshot_file_exists)

    directory = _FsPath(snapshot_dir)
    reader = L0JSONLReader(directory / "L0.jsonl")
    document = reader.metadata()

    curve_index: dict[str, Any] = {}
    if snapshot_file_exists(directory / "curve.index.json"):
        raw = json.loads(read_snapshot_text(directory / "curve.index.json"))
        curve_index = raw.get("curve_index") or {}

    sketch_index: dict[str, Any] = {}
    if snapshot_file_exists(directory / "sketch.index.json"):
        raw = json.loads(read_snapshot_text(directory / "sketch.index.json"))
        sketch_index = dict(raw.get("profile_index") or {})
        sketch_index["__runs__"] = raw.get("stairs_run_path_index") or {}

    return build_model_preview(document, reader.iter_elements(), levels=levels,
                               curve_index=curve_index,
                               sketch_index=sketch_index)


# ---------------------------------------------------------------------------
# 10. THE RENDERER — the one shared by both sources
# ---------------------------------------------------------------------------

SHEET_W = 1680
SHEET_H = 1400
HEADER_H = 104
DRAW_X = 40
DRAW_Y = HEADER_H + 24
DRAW_W = SHEET_W - 2 * DRAW_X
DRAW_H = 960
FOOTER_Y = DRAW_Y + DRAW_H + 24


_STYLE: dict[Layer, dict[str, Any]] = {
    Layer.ROOM: {"fill": "#e8eef5", "stroke": "#b6c4d4", "width": 0.8},
    Layer.SLAB: {"fill": "none", "stroke": "#9aa7b4", "width": 1.0,
                 "dash": "8 5"},
    Layer.FIXTURE: {"fill": "none", "stroke": "#b9c2cc", "width": 0.7},
    Layer.MEP: {"fill": "none", "stroke": "#7fa8c9", "width": 1.0},
    Layer.LINE: {"fill": "none", "stroke": "#8f9aa6", "width": 1.0},
    Layer.SEPARATION: {"fill": "none", "stroke": "#a8b4c0", "width": 0.9,
                       "dash": "5 4"},
    Layer.GRID: {"fill": "none", "stroke": "#c2a15a", "width": 0.9,
                 "dash": "18 5 3 5"},
    Layer.STAIR: {"fill": "none", "stroke": "#6d7c8b", "width": 1.4},
    Layer.WALL: {"fill": "#2b3440", "stroke": "#2b3440", "width": 0.6},
    Layer.OPENING: {"fill": "#ffffff", "stroke": "#2b3440", "width": 1.0},
    Layer.COLUMN: {"fill": "#4a5563", "stroke": "#2b3440", "width": 0.6},
    Layer.LABEL: {"fill": "none", "stroke": "#2b3440", "width": 0.8},
}

_SOURCE_STYLE: dict[PreviewSource, dict[str, str]] = {
    PreviewSource.PROGRAM: {
        "accent": "#b26a00",
        "band": "#fff3e0",
        "border_dash": "12 6",
        "title": "ПРЕВЬЮ ПРОГРАММЫ · САМОПРОВЕРКА",
        "claim": "рисуется ЗАЯВЛЕННОЕ автором. Модель НЕ читалась, "
                 "ни один селектор не разрешён.",
        "watermark": "ЗАЯВЛЕНО",
    },
    PreviewSource.MODEL: {
        "accent": "#1d5b8f",
        "band": "#e7f0f8",
        "border_dash": "",
        "title": "ПРЕВЬЮ РАЗБОРА · НЕЗАВИСИМОЕ ЧТЕНИЕ",
        "claim": "рисуется то, что ЕСТЬ в документе (L0), а не то, "
                 "что кто-то собирался построить.",
        "watermark": "",
    },
}

_APPROX_TEXT: dict[ApproxReason, str] = {
    ApproxReason.FOOTPRINT_FROM_BBOX:
        "след взят из ГАБАРИТА (AABB), а не из профиля",
    ApproxReason.THICKNESS_UNKNOWN:
        "толщина неизвестна — нарисована ОСЬ, не тело",
    ApproxReason.OPENING_WIDTH_UNKNOWN:
        "ширина проёма неизвестна — засечка/условные 900 мм",
    ApproxReason.DOOR_SWING_UNKNOWN:
        "сторона открывания двери в источнике отсутствует — показана условно",
    ApproxReason.ARC_SAMPLED: "дуга представлена выборкой точек",
    ApproxReason.OPENING_ON_CHORD:
        "хозяин — ДУГА, а проём посчитан по хорде: положение, ширина и "
        "открывание приблизительны",
    ApproxReason.ROOM_BOUNDARY_NOT_COMPUTED:
        "границу помещения считает Revit — в программе это точка",
    ApproxReason.LEVEL_NOT_BOUND:
        "у операции нет привязки к уровню — тело показано на единственном "
        "объявленном плане программы",
    ApproxReason.LEVEL_VIA_PARAMETER:
        "этаж восстановлен по параметру (level_id пуст)",
    ApproxReason.BLEND_TOP_PROFILE_DIFFERS:
        "тело перехода: в плане показан НИЖНИЙ профиль — верхний отличается, "
        "а боковую поверхность между ними выбирает сам Revit",
    ApproxReason.REVOLVE_TRACE_IS_SWEPT_SECTOR:
        "тело вращения: след в плане — кольцевой сектор по радиальному "
        "размаху профиля (сам профиль задан в осевых координатах и в плане "
        "не лежит)",
}

_OMIT_TEXT: dict[OmitReason, str] = {
    OmitReason.NO_GEOMETRY: "геометрии нет",
    OmitReason.ONLY_BBOX: "есть только габарит, а нужен контур",
    OmitReason.DEGENERATE: "вырожденная геометрия",
    OmitReason.NON_FINITE: "неконечные координаты",
    OmitReason.UNSUPPORTED_CURVE: "кривая не прямая и не дуга",
    OmitReason.CATEGORY_NOT_DRAWN: "категория не поддержана",
    OmitReason.ANNOTATION_NOT_MODEL: "аннотация вида, не тело здания",
    OmitReason.NOT_VISIBLE_IN_PLAN: "в плане не виден по построению",
    OmitReason.DERIVED_GEOMETRY: "производная геометрия",
    OmitReason.LEVEL_UNKNOWN: "этаж не определён",
    OmitReason.LEVEL_NOT_IN_RUN: "этаж не рисовали в этом прогоне",
    OmitReason.HOST_UNKNOWN: "хост не назван",
    OmitReason.HOST_NOT_DRAWABLE: "геометрии хоста нет",
    OmitReason.OP_NOT_DRAWN: "у операции нет правила рисования",
    OmitReason.SELECTOR_UNRESOLVED: "селектор уровня не сведён к плану",
    OmitReason.NO_LEVEL_SLOT: ("у операции нет поля уровня вовсе — она "
                               "не привязана к этажу по построению"),
    OmitReason.NOT_AN_OP: "не операция KIR: ключа `op` у элемента нет",
    OmitReason.BODY_TRACE_NOT_DERIVABLE: (
        "тело вращения/перехода: след в плане не выводится из его профиля"),
}

_ANOMALY_TEXT: dict[AnomalyReason, str] = {
    AnomalyReason.OPENING_OUTSIDE_HOST: "проём за пределами своей стены",
    AnomalyReason.OPENING_WIDER_THAN_HOST: "проём шире стены",
    AnomalyReason.COINCIDENT_WALLS: "стены-дубли (совпадают концы)",
    AnomalyReason.ROOM_NOT_ENCLOSED: "помещение не замкнулось (площадь 0)",
    AnomalyReason.FAR_OUTLIER: "элемент далеко за облаком остальных",
}


#: How many census rows FIT in the sheet's footer. The numbers are
#: geometric: a footer of height (SHEET_H - FOOTER_Y) with a 17 px row
#: holds exactly this many. They used to sit as unnamed slices
#: `[:5]`/`[:4]` right in the markup, and the truncation WAS NOT NAMED —
#: meaning the module that exists to forbid silence was itself silent.
#: Now the remainder is printed as a "… N more" line, the same as for
#: skips.
_FOOTER_OMIT_ROWS = 7
_FOOTER_APPROX_ROWS = 5
_FOOTER_ANOMALY_ROWS = 4
_FOOTER_BLIND_ROWS = 4


def census_lines(census: PreviewCensus) -> tuple[dict[str, Any], ...]:
    """THE CENSUS IN HUMAN-READABLE LINES — in full, with no slicing.

    The sheet prints as many lines as fit in the footer, and honestly
    names the remainder. But the census's recipient (the panel, the
    transfer decision, the receipt) does not need truncation at all: there
    is no footer and no footer height there. The Russian text of the
    reasons lives in exactly one place — `_OMIT_TEXT`/`_APPROX_TEXT`/
    `_ANOMALY_TEXT` — and a second copy of these phrasings is never
    introduced: it would diverge from the reason codes on the very first
    new reason.
    """
    out: list[dict[str, Any]] = []
    for group in census.omitted:
        out.append({
            "kind": "omitted", "reason": group.reason.value,
            "category": group.category, "count": group.count,
            "examples": list(group.examples),
            "ru": _OMIT_TEXT.get(group.reason, group.reason.value),
        })
    for group in census.approx:
        out.append({
            "kind": "approx", "reason": group.reason.value,
            "category": "", "count": group.count,
            "examples": list(group.examples),
            "ru": _APPROX_TEXT.get(group.reason, group.reason.value),
        })
    for group in census.anomalies:
        out.append({
            "kind": "anomaly", "reason": group.reason.value,
            "category": "", "count": group.count,
            "examples": list(group.examples),
            "ru": _ANOMALY_TEXT.get(group.reason, group.reason.value),
        })
    return tuple(out)


# ---------------------------------------------------------------------------
# 8. THE CARD FOR A HUMAN: the subject on the first line, the instrument on
#    the second
# ---------------------------------------------------------------------------
#
# 🔴 BOUGHT BY THE OWNER'S OWN LIVE TURN ON 08.09.2026. He wrote "make a
# cube." A program of one operation was accepted and HELD
# (`serving.held_in_kir`), meaning the cube stood ready for transfer. What
# arrived in the window as the first line was:
#
#     перепись: нарисовано 94 из 98 (95.92%) · 4 не показано — у операции нет
#     правила рисования [create_floor_by_contour] · 43 приближено … ·
#     заявлено по этажам: #2607 — 6 · … · ⇣ перенести в Revit (124 опов) ·
#     подпись 93310f4797afc6ed
#
# Not one of these numbers was ABOUT HIS CUBE: the census was taken from a
# journal slice for the floor (`live/plan_stream._slice_for`, a ceiling of
# 1500 operations), "заявлено по этажам" came from the whole session
# (`live/journal.SessionJournal.summary`), and "программ в журнале: 195"
# came from the same place. The owner's word: "I asked it to build a
# cube — it can't." He did not understand that the cube was READY.
#
# The constitution (`kir/CLAUDE.md`) demands exactly the reverse order: the
# environment must report in units of the MODEL AND THE HUMAN, and the next
# turn must name a button that EXISTS. So this is where one pair of values
# is introduced: `summary` (the subject and the next turn) and `details`
# (the instrument and all its numbers). NOTHING IS HIDDEN: the census, the
# anomalies, the signature, and the honesty outcome sit in full inside
# `details` — the window decides whether to collapse them, but it cannot
# lose them.

#: What the person can do with this. This is EXACTLY what rides the first
#: line, not the instrument's vocabulary: «ЗАЯВЛЕНО»/«САМОПРОВЕРКА»
#: describe the STRENGTH of the claim correctly, but answer a question
#: the person never asked.
HUMAN_ASSERTION_RU = ("превью построено по программе, а не по модели Revit: "
                      "модель не читалась")

#: The same fact in the instrument's vocabulary — verbatim the same line
#: that used to be the card's badge before 08.09. It is not removed: the
#: strength of the claim must remain expressible, otherwise a month from
#: now someone will say "but I saw it, everything was fine." It moved to
#: the SECOND half of the card.
INSTRUMENT_ASSERTION_RU = "ЗАЯВЛЕНО программой — модель не читалась"

#: THE WORDS WRITTEN ON THE BUTTON. Not «Отправить в Revit», not
#: «Построить»: exactly `kukai_chat_v5.html` (`data-kir-go="all"`). This
#: tree's named class of bug is "the next turn names something that does
#: not exist"; it has already cost the owner one turn on 16.08 and a
#: second on 08.09. The window always prints the count next to these
#: words as «опов»; here it is grammatically agreed in Russian, because
#: the load-bearing part is the WORDS, and a person reads «1 опов» as a
#: typo by the instrument.
#: 🔴 ОДНО СЛОВО, А НЕ ФРАЗА (13.09.2026). Было «⇣ перенести в Revit»; слово
#: владельца, смотревшего на окно: «оч много кринжа в словах у UI… человеку
#: доступно минимум кнопок». Величина живёт ЗДЕСЬ и читается панелью и
#: квитанцией придержки — у надписи на кнопке ровно один автор, и сверяет их
#: `backend/tests/test_held_receipt_names_a_real_button.py`.
TRANSFER_BUTTON_RU = "Одобрить"

#: Datums: declarations, not something built. `create_level` is not drawn
#: in the plan by construction, `create_grid` is an axis. The same set by
#: which `build_program_preview` tells them apart; a second copy of the
#: rule is not introduced.
_DATUM_OPS = frozenset({"create_level", "create_grid"})

#: RUSSIAN OPERATION NAMES.
#:
#: 🔴 БЫЛ НАРОЧНО НЕПОЛНЫМ — И ЭТО СТОИЛО ВЛАДЕЛЬЦУ ЛИЦА ПРОДУКТА
#: (13.09.2026). Правило «незнакомую операцию печатаем её собственным именем,
#: чтобы не выдумывать обобщение» верно для ПРИБОРА и ложно для ЧЕЛОВЕКА: в
#: окне КИР на «построй коробку» он прочёл `create_extrusion_roof` среди своих
#: стен. Латинский идентификатор в списке того, что сейчас построится, — это
#: не честность, это отказ говорить.
#:
#: Разрешение противоречия: имя даётся КАЖДОЙ строящей операции реестра (пин
#: `test_no_create_op_is_printed_raw`), а «не выдумывать» сохраняется иначе —
#: имя называет РОД («кровля выдавливанием», «воздуховод»), а размеры и
#: параметры по-прежнему приходят только из самой операции (`_describe_op_ru`).
#: Незнакомое имя (оп завели, сюда не дописали) больше не печатается сырым:
#: `_op_kind_ru` выводит род по разделу реестра словами.
_OP_RU: dict[str, str] = {
    "create_wall": "стена",
    "create_floor": "перекрытие",
    "create_floor_by_contour": "перекрытие по контуру",
    "create_roof_by_footprint": "кровля",
    "create_column": "колонна",
    "create_beam": "балка",
    "create_door": "дверь",
    "create_window": "окно",
    "create_room": "помещение",
    "create_level": "уровень",
    "create_grid": "ось",
    "create_stairs": "лестница",
    "create_solid_extrusion": "тело выдавливанием",
    "create_solid_revolve": "тело вращением",
    "create_solid_blend": "тело переходом",
    "create_directshape": "тело",
    "create_ceiling": "потолок",
    "create_roof": "кровля",
    "create_extrusion_roof": "кровля выдавливанием",
    "create_face_wall": "стена по поверхности",
    "create_building_pad": "площадка основания",
    "create_foundation": "фундамент",
    "create_wall_foundation": "фундамент стены",
    "create_slab_edge": "край плиты",
    "create_wall_sweep": "профиль стены",
    "create_beam_system": "система балок",
    "create_truss": "ферма",
    "create_railing": "ограждение",
    "create_stairs_run": "марш лестницы",
    "create_stairs_landing": "площадка лестницы",
    "create_multistory_stairs": "лестница многоэтажная",
    "create_curtain_grid_line": "линия витражной сетки",
    "set_curtain_panel": "панель витража",
    "create_opening": "проём",
    "create_room_separator": "разделитель помещений",
    "create_space": "инженерное пространство",
    "create_duct": "воздуховод",
    "create_flex_duct": "гибкий воздуховод",
    "create_duct_placeholder": "заготовка воздуховода",
    "create_pipe": "труба",
    "create_flex_pipe": "гибкая труба",
    "create_pipe_placeholder": "заготовка трубы",
    "create_pipe_system": "трубопроводная система",
    "create_cable_tray": "кабельный лоток",
    "create_conduit": "короб",
    "route_duct_system": "трасса воздуховодов",
    "route_pipe_system": "трасса труб",
    "create_solid_sweep": "тело по траектории",
    "create_solid_boolean": "тело булевой операцией",
    "create_surface": "поверхность",
    "create_topography": "рельеф",
    "create_site_subregion": "подобласть площадки",
    "create_multi_segment_grid": "составная ось",
    "create_floor_plan": "план этажа",
    "create_dimension": "размер",
    "create_angular_dimension": "угловой размер",
    "create_tag": "марка",
    "create_text": "текст",
    "create_filled_region": "закрашенная область",
    "create_path_of_travel": "путь эвакуации",
    "create_point_load": "сосредоточенная нагрузка",
    "create_line_load": "линейная нагрузка",
    "create_area_load": "площадная нагрузка",
    "create_area_reinforcement": "армирование области",
    "create_adaptive_component": "адаптивный компонент",
    "create_group": "группа",
    "create_type": "тип",
    "create_wall_type": "тип стены",
    "place_family": "экземпляр семейства",
    "load_family": "загрузка семейства",
    "author_family": "семейство",
    "transfer_family": "перенос семейства",
    "transfer_material": "перенос материала",
    "change_type": "смена типа",
    "set_param": "параметр",
    "move_elements": "перемещение",
    "delete": "удаление",
    "join_elements": "соединение элементов",
    "query_count": "подсчёт",
    "query_list": "перечень",
    "query_types": "перечень типов",
    "query_inspect": "осмотр элемента",
    "query_element_state": "состояние элемента",
    "query_surface": "чтение поверхности",
    "query_level_plan": "план уровня",
}


#: THE NAME OF THE LIFT REFUSAL THAT THE CARD MUST SPELL OUT IN RUSSIAN.
#: The string duplicates `live.journal.FOREIGN_JOURNAL_REFUSAL`
#: DELIBERATELY: `preview` lives without `live` (the KIR↔product boundary
#: and a clean install), and importing for the sake of one literal would
#: saddle the renderer with a dependency on the live journal. Divergence
#: is guarded by an instrument —
#: `test_a_journal_belongs_to_a_document_not_to_a_name` checks both sides
#: with a single equality.
FOREIGN_JOURNAL_REFUSAL_RU_KEY = "journal_of_another_document_with_the_same_name"


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    """1 операция · 2 операции · 5 операций. It is computed, not
    guessed."""
    n = abs(int(n))
    if n % 100 in (11, 12, 13, 14):
        return many
    last = n % 10
    if last == 1:
        return one
    if last in (2, 3, 4):
        return few
    return many


def program_element_ids(ops: Sequence[Mapping[str, Any]]
                        ) -> tuple[str, ...]:
    """The addresses one program's operations will be DRAWN under — cheap.

    The same seam as :func:`program_level_index`, for the same reason: the
    caller (`live/plan_stream`) needs only the ids, and building a full
    `BuildingPreview` for them computes every element's shapes and throws
    them away. MEASURED on the live-plan budget test 13.09.2026: the preview
    route cost **5.820 ms per program against a 4 ms budget** and turned
    `focus=` from a highlight into a stall; this walk costs one pass over the
    operations.

    🔴 THE ID RULE IS NOT REWRITTEN HERE. `build_program_preview` names a
    drawn element `str(op["id"]) or the op's name`, over the SAME
    `_members_out_of_groups` (a group publishes its MEMBERS, not itself). Both
    lines live in this file, next to each other, on purpose: an id that
    matches nothing does not raise — it dims the whole sheet, silently. The
    agreement of the two is held by
    `kir/tests/test_a_focus_lists_exactly_what_the_sheet_draws.py`, not by
    this docstring.

    WIDER THAN THE SHEET, AND DELIBERATELY SO. An operation that ends up
    omitted (no drawing rule, unresolved level, `create_level` — not a plan
    object at all) still gives its id here. `focus` is a WHITELIST: an id
    matching nothing costs nothing, whereas a missing id costs the person
    their subject.
    """
    flat = _members_out_of_groups(_program_ops({"ops": list(ops)}))
    ids: list[str] = []
    seen: set[str] = set()
    for op in flat:
        name = str(op.get("op", ""))
        oid = str(op.get("id", "")) or name
        if oid and oid not in seen:
            seen.add(oid)
            ids.append(oid)
    return tuple(ids)


def program_element_names(ops: Sequence[Mapping[str, Any]]
                          ) -> tuple[tuple[str, str], ...]:
    """(address, human name) for one program's operations — the SAME walk
    as :func:`program_element_ids`, with the Russian phrase alongside.

    THE SEAM EXISTS BECAUSE OF THE WINDOW, NOT BECAUSE OF SYMMETRY. The KIR
    window's right column has to name what is about to be built — «стена
    длиной 6000 мм», «дверь», «перекрытие» — and the only other thing it
    could print is the address (`p1/w0`), which is a hash to a human. Owner,
    13.09.2026: the panel must speak, not show internals.

    🔴 THE ORDER AND THE IDS ARE NOT RECOMPUTED — the ids come from
    :func:`program_element_ids`, so a focus and a name list can never
    disagree about what an element is called. Only the phrase is added, and
    it is taken from the single author of that phrase (`_describe_op_ru`),
    the same one `program_headline` uses for the card's first line. Two
    places wording "a wall" differently is precisely the class of defect this
    file keeps closing.

    Cheap on purpose: one pass over the operations, not a single
    `DrawnElement` built. The live-plan budget is 4 ms per program, and the
    preview route was measured at 5.820 ms.
    """
    flat = _members_out_of_groups(_program_ops({"ops": list(ops)}))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for op in flat:
        name = str(op.get("op", ""))
        oid = str(op.get("id", "")) or name
        if not oid or oid in seen:
            continue
        seen.add(oid)
        # DECLARATIONS ARE NOT ELEMENTS. A level and a grid are statements
        # about the building, not things in it; listing «уровень 1» among
        # "what will be built" is the same lie as counting it as an
        # operation in the first line (`program_headline`).
        if name in _DATUM_OPS:
            continue
        out.append((oid, _describe_op_ru(op)))
    return tuple(out)


def program_level_index(ops: Sequence[Mapping[str, Any]], *,
                        context: Sequence[Mapping[str, Any]] = ()
                        ) -> tuple[tuple[str, int], ...]:
    """(floor name, how many PROGRAM operations were presented to it) —
    cheap.

    The seam that the header of `live/plan_stream._levels_of` asks for:
    there, for the sake of two fields, a FULL `BuildingPreview` gets
    built, meaning the shapes of every element are computed and
    immediately discarded. Here operations are only sorted by
    `_op_level_key`/`_selector_key`, and not a single `DrawnElement` is
    constructed.

    The membership rule is NOT rewritten: it takes exactly the same
    `_op_level_key` and the same resolution of a key to a name via an
    unambiguous `create_level` as `build_program_preview` does. A second
    source of truth about this would cost one floor two sheets.

    A DECLARED FLOOR WITH NO OPERATIONS STILL LANDS HERE WITH ZERO, and
    this is not a triviality: the program "make a cube" declares «Уровень
    1» and puts zero plan objects on it (`create_solid_extrusion` has no
    level field at all — a DirectShape has no level binding). Staying
    silent about this floor would read as "the program has nothing to do
    with it", while it is the one point a person's eyes hold onto.
    """
    flat = _members_out_of_groups(_program_ops({"ops": list(ops)}))
    среза = (_members_out_of_groups(_program_ops({"ops": list(context)}))
             if context else [])
    names, alias, свои = _level_vocabulary(flat, среза)
    # 🔴 ZERO ROWS — ONLY FOR ONE'S OWN DECLARATIONS. A slice floor this
    # program never touched does not land in its card AT ALL: otherwise
    # "заявлено по этажам: #2607 — 6 · …" would come back with a hundred
    # of the document's levels — exactly what the card was narrowed to
    # forbid (P3-04).
    tally: dict[str, int] = {label: 0 for label in свои}
    # A body with no level slot falls onto the SINGLE plan the PROGRAM
    # ITSELF declares — exactly as in `build_program_preview`. A SLICE
    # level does not fit here: the renderer does not see the context, and
    # the index would count the body onto a plan that is not on the
    # sheet.
    единственный = {alias[label] for label in свои if label in alias}
    for op in flat:
        name = str(op.get("op", ""))
        if not name or name in _DATUM_OPS:
            continue
        key = _op_level_key(op)
        if key is None and len(единственный) == 1 and name in _BODY_OPS:
            # The same conclusion as in `build_program_preview`: the body
            # has a place in the plan, no level binding, and the
            # approximation IS NAMED (`ApproxReason.LEVEL_NOT_BOUND`) —
            # here it is only counted.
            key = next(iter(единственный))
        if key is None:
            continue
        key = alias.get(key, key)
        label = names.get(key, key)
        tally[label] = tally.get(label, 0) + 1
    return tuple(sorted(tally.items()))


def _rect_size_mm(region: Any) -> tuple[float, float] | None:
    if not isinstance(region, Mapping) or region.get("shape") != "rect":
        return None
    size = region.get("size_mm")
    if not isinstance(size, Sequence) or len(size) != 2:
        return None
    try:
        w, d = float(size[0]), float(size[1])
    except (TypeError, ValueError):
        return None
    return (w, d) if math.isfinite(w) and math.isfinite(d) else None


def _size_ru(*mm: float) -> str:
    """The bbox in HUMAN units: meters, as long as it's not below a
    meter.

    The owner's word of 08.09: "A 3×3×3 m cube." Millimeters are the
    model's units and stay in the machine channel; in the line a human
    reads, three four-digit numbers force them to do arithmetic in their
    head for nothing.
    """
    if min(mm) >= 1000.0:
        return "×".join(_fmt(round(v / 1000.0, 3)) for v in mm) + " м"
    return "×".join(_fmt(v) for v in mm) + " мм"


def _describe_op_ru(op: Mapping[str, Any]) -> str:
    """One operation in the MODEL'S UNITS. If we don't know, we name the
    op, we don't invent."""
    name = str(op.get("op", ""))
    if name == "create_solid_extrusion":
        rect = _rect_size_mm((op.get("profile") or {}).get("outer")
                             if isinstance(op.get("profile"), Mapping) else None)
        height = op.get("height_mm")
        if rect is not None and isinstance(height, (int, float)) \
                and math.isfinite(float(height)):
            w, d, h = rect[0], rect[1], float(height)
            размеры = _size_ru(w, d, h)
            # "A cube" is a measured property, not a guess: three equal
            # sides.
            род = "куб" if w == d == h else "тело"
            return f"{род} {размеры}"
    if name == "create_wall":
        try:
            p0, p1 = _pt(op["p0_mm"]), _pt(op["p1_mm"])
        except (KeyError, TypeError, IndexError, PreviewError):
            p0 = p1 = None
        if p0 is not None and p1 is not None:
            длина = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if math.isfinite(длина):
                return f"стена длиной {_size_ru(длина)}"
    return _op_kind_ru(name)


#: Род операции по её ПРЕФИКСУ — запасной путь для опа, который завели в
#: реестре и не дописали в `_OP_RU`. Обобщение здесь законно ровно потому, что
#: оно берётся из ИМЕНИ САМОЙ ОПЕРАЦИИ, а не придумывается: `create_*` строит,
#: `query_*` читает, `set_*` правит. Латиница человеку не показывается ни в
#: одном случае — она уходит в скобки, чтобы агент мог назвать её точно.
_OP_KIND_RU: tuple[tuple[str, str], ...] = (
    ("create_solid_", "тело"),
    ("create_", "элемент"),
    ("route_", "трасса"),
    ("query_", "чтение модели"),
    ("set_", "правка параметра"),
    ("change_", "правка"),
    ("transfer_", "перенос"),
    ("load_", "загрузка"),
    ("author_", "авторство"),
)


def _op_kind_ru(name: str) -> str:
    """Русское имя операции. Сырую латиницу человеку НЕ печатает никогда."""
    if not name:
        return "операция без имени"
    known = _OP_RU.get(name)
    if known:
        return known
    for prefix, kind in _OP_KIND_RU:
        if name.startswith(prefix):
            return f"{kind} ({name})"
    return f"операция ({name})"


def _level_clause_ru(ops: Sequence[Mapping[str, Any]], *,
                     context: Sequence[Mapping[str, Any]] = ()) -> str:
    """"on level X" — only when the operation is ACTUALLY bound to it.

    A `create_solid_extrusion` has no level field at all (`ops_solid`: "a
    `level` selector would promise a binding that does not exist in the
    built element"). So a level the program declares is named with
    DIFFERENT words than one it is bound to: lying about the binding
    costs more than staying silent.
    """
    index = program_level_index(ops, context=context)
    привязанные = [name for name, count in index if count]
    if len(привязанные) == 1:
        return f"на уровне «{привязанные[0]}»"
    if len(привязанные) > 1:
        return f"этажей: {len(привязанные)}"
    if len(index) == 1:
        return f"уровень программы — «{index[0][0]}»"
    if len(index) > 1:
        return f"уровней объявлено: {len(index)}"
    return ""


def program_headline(program: Any, *,
                     context: Sequence[Mapping[str, Any]] = ()) -> str:
    """THE FIRST LINE FOR A HUMAN: what was built, in millimeters and in
    Russian.

    Computed from the PROGRAM ITSELF and nowhere else: neither the
    session journal, nor the floor slice, nor the document enter here —
    it was exactly this substitution that made the 08.09 card tell the
    person about someone else's 195 programs instead of their cube.

    Datums (`create_level`, `create_grid`) do not count toward
    "operations": these are declarations, not something built. The
    program "make a cube" is two operations and ONE body, and "2
    operations" in the first line would sound like two boxes.
    """
    ops = _members_out_of_groups(_program_ops(program))
    строящие = [op for op in ops
                if str(op.get("op", "")) and str(op.get("op")) not in _DATUM_OPS]
    if not строящие:
        # Zero built is an outcome, not a blank line: a program made of
        # nothing but levels and grids DOES exist, and staying silent
        # about it reads as a refusal.
        уровень = _level_clause_ru(ops, context=context)
        хвост = f" · {уровень}" if уровень else ""
        return f"строящих операций нет (только объявления){хвост}"
    if len(строящие) == 1:
        предмет = _describe_op_ru(строящие[0])
    else:
        counts: dict[str, int] = {}
        for op in строящие:
            имя = _op_kind_ru(str(op.get("op", "")))
            counts[имя] = counts.get(имя, 0) + 1
        порядок = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        предмет = " · ".join(f"{имя} — {n}" for имя, n in порядок[:4])
        if len(порядок) > 4:
            предмет += f" · и ещё родов: {len(порядок) - 4}"
    части = [предмет]
    уровень = _level_clause_ru(ops, context=context)
    if уровень:
        части.append(уровень)
    n = len(строящие)
    части.append(f"{n} {_plural_ru(n, 'операция', 'операции', 'операций')}")
    # 🔴 THE CARD'S TWO NUMBERS ARE SPLIT BY RECIPIENT, NOT ADDED INTO ONE
    # LINE. The button carries the count of ALL operations (the showroom
    # transfers the whole program), the first line carries the count of
    # what was BUILT. The first edition appended "· 1 declaration
    # (levels, grids)" here so that 1 and 2 would reconcile in the
    # reader's head — and that is exactly the clutter the owner's word of
    # 08.09 was about: "he needs to see the minimum amount of
    # information." The breakdown moved to `details.ops_breakdown`, where
    # an agent reads it, and to "details" on click; it left the human's
    # line.
    return " · ".join(части)


def journal_note_ru(note: Any) -> str:
    """THE JOURNAL-RECOVERY DIAGNOSIS — IN ONE HUMAN LINE. Empty means
    there is nothing to say.

    🔴 WHY THIS IS HERE AND NOT IN `live/journal.py` (08.09.2026). Wave 9
    carried the diagnosis as far as the RECEIPT, in the `journal_restore`
    field — and stopped there: the field exists, but there is no text a
    human will read in the chat ("NOT DONE" item #2 of the `journal-key`
    allotment: "drawing the receipt belongs to the
    `preview.py`/card allotment"). A field nobody unfolds is the
    instrument's journal, not a message: the owner said exactly this
    about such fields on 08.09 — "even I don't know what our labels
    mean."

    WHAT A HUMAN MUST UNDERSTAND FROM ONE LINE: how many programs were
    found, what was NOT done with them, and what their next turn is. The
    refusal's name (`journal_of_another_document_with_the_same_name`),
    the store key, and the file path stay in `details` — they are
    correct and needed by the instrument, but they do not answer the
    human's question.
    """
    if not isinstance(note, Mapping):
        return ""
    try:
        рядом = int(note.get("programs_by_name") or 0)
    except (TypeError, ValueError):
        рядом = 0
    try:
        поднято = int(note.get("restored") or 0)
    except (TypeError, ValueError):
        поднято = 0
    if рядом <= 0:
        # Nothing to name: the recovery either succeeded cleanly or found
        # nothing at all. A blank line is MORE HONEST than a cheerful
        # "everything is fine": the card is not required to speak about
        # what never happened.
        return ""
    имя = str(note.get("document_name") or "").strip()
    чьи = f" («{имя}»)" if имя else ""
    сколько = f"{рядом} {_plural_ru(рядом, 'программа', 'программы', 'программ')}"
    ход = str(note.get("next_step_ru") or "").strip()
    if note.get("refused") == FOREIGN_JOURNAL_REFUSAL_RU_KEY or поднято <= 0:
        # NOTHING WAS RECOVERED. The human HAS a next turn, and it is
        # named.
        return (f"В этом Ревите есть {сколько} документа с таким же именем"
                f"{чьи} — они НЕ подняты: это может быть другой документ."
                + (f" Поднять: {ход}" if ход else ""))
    # ITS OWN JOURNAL WAS RECOVERED, while a pile with the same name sits
    # next to it. It has no next turn — and promising one would be worse
    # than silence; the REASON is named instead.
    return (f"Журнал этого документа поднят: {поднято} "
            f"{_plural_ru(поднято, 'программа', 'программы', 'программ')}. "
            f"Рядом на складе лежат ещё {сколько} документа с таким же "
            f"именем{чьи} — они НЕ подняты"
            + (f": {ход}" if ход else "."))


def program_card(program: Any, *, ops: int | None = None,
                 digest: str = "", transferable: bool = True,
                 blocked_ru: str = "",
                 context: Sequence[Mapping[str, Any]] = (),
                 journal_restore: Any = None) -> dict[str, Any]:
    """THE SINGLE-PROGRAM CARD: `summary` for the human, `details` for
    the instrument.

    The split is STRUCTURAL, not typographic: the window must be able to
    collapse the second half without parsing the text into lines. This is
    exactly what was missing on 08.09 — the card was one solid block, and
    there was nothing to collapse in it.

    `ops` — how many operations will ride ON THE BUTTON. By default, all
    the program's operations; holding (`serving.held_in_kir`) and the
    showroom (`live/showroom`) count them themselves and pass along their
    own number, because their number is about delivery, while the number
    in the first line is about what was built, and the two need not
    match (for a cube with a declared level, 1 and 2).

    `context` — the SLICE'S DATUMS (the session's levels and grids), and
    it gives exactly one thing: the NAME of a floor declared by a
    different program. Wave 9's "NOT DONE" item #3, verbatim: "`pack[-1]`
    is only the program's own operations, and if `create_level` arrived
    as a separate program, the floor name in its header will not
    resolve." Measured on a program "a wall on level #2607" with no
    `create_level` of its own: the header read `на уровне «#2607»`. The
    context enters no DENOMINATOR: the census, `ops`, and the count of
    what was built stay about THIS program (P3-03), otherwise "94 out of
    98" from a foreign slice would come back.

    `journal_restore` — the outcome of the journal recovery
    (`live.journal.restore_note`). It unfolds into ONE human line of the
    card; the refusal's name and the store path go to `details`.
    """
    все = _members_out_of_groups(_program_ops(program))
    контекст = list(context or ())
    total = len(все) if ops is None else int(ops)
    построено = program_headline(program, context=контекст)
    if transferable:
        next_ru = f"Следующий ход: «{TRANSFER_BUTTON_RU}» в окне КИР."
    else:
        next_ru = (blocked_ru or "Следующий ход недоступен: программу не "
                   "удалось подписать, кнопки переноса на этой карточке нет.")
    # The census — FOR THIS PROGRAM. Not the journal, not a floor slice,
    # not the document.
    building = build_program_preview(program)
    census = building.census
    levels = [{"level": name, "declared": count}
              for name, count in program_level_index(все, context=контекст)]
    журнал_ru = journal_note_ru(journal_restore)
    строки = [построено, next_ru]
    if журнал_ru:
        # THIRD, NOT FIRST. The first line is the subject of the request,
        # the second is the next turn; the memory of a foreign,
        # identically-named document matters, but a human reading it
        # first will conclude their program failed.
        строки.append(журнал_ru)
    summary: dict[str, Any] = {
        "built_ru": построено,
        "next_ru": next_ru,
        "ops": total,
        "levels": levels,
    }
    if журнал_ru:
        summary["journal_ru"] = журнал_ru
    return {
        "schema": PREVIEW_SCHEMA,
        "summary_ru": "\n".join(строки),
        "summary": summary,
        "levels": levels,
        "details": {
            "assertion": building.assertion.value,
            "assertion_ru": HUMAN_ASSERTION_RU,
            "instrument_ru": INSTRUMENT_ASSERTION_RU,
            "census": census.to_dict(),
            "census_lines": list(census_lines(census)),
            "digest": digest,
            "blind_spots": list(BLIND_SPOTS),
            "ops_breakdown": {
                "built": sum(1 for op in все
                             if str(op.get("op", ""))
                             and str(op.get("op")) not in _DATUM_OPS),
                "declarations": sum(1 for op in все
                                    if str(op.get("op", "")) in _DATUM_OPS),
                "transferred": total,
            },
            # THE INSTRUMENT'S WORDS ABOUT THE RECOVERY — IN FULL, HERE:
            # the refusal's name, the store key, the file path. What went
            # into `summary` is one line, not a retelling.
            "journal_restore": (dict(journal_restore)
                                if isinstance(journal_restore, Mapping)
                                else None),
        },
    }


def _fmt(value: float) -> str:
    if not math.isfinite(value):
        raise PreviewError("нельзя напечатать неконечное число")
    text = f"{value:.2f}"
    if text.endswith(".00"):
        text = text[:-3]
    elif text.endswith("0"):
        text = text[:-1]
    return "0" if text in ("-0", "-0.0") else text


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _nice_length(max_mm: float) -> float:
    if max_mm <= 0:
        return 1000.0
    exponent = math.floor(math.log10(max_mm))
    for factor in (5.0, 2.0, 1.0):
        candidate = factor * (10.0 ** exponent)
        if candidate <= max_mm:
            return candidate
    return 10.0 ** exponent


#: 🔴 DARK THEME — ONE TABLE, NOT A SECOND RENDERER (08.09.2026).
#:
#: The owner's word: dark theme must be FULL-FLEDGED. Full-fledged is not
#: "we inverted the background": the sheet has colors that CARRY MEANING
#: (anomaly, approximation, refusal), and they must stay distinguishable,
#: not drown.
#:
#: The design is chosen so the promise "ONLY colors change" holds BY
#: CONSTRUCTION, not by attentiveness: the renderer ALWAYS prints the
#: light sheet, and the dark one is produced by ONE substitution over
#: this table. There is no second branch in the markup at all, so there
#: is nothing to diverge. `<metadata>` is excluded from the
#: substitution: it's the machine channel, and there is nothing there to
#: color.
#:
#: Contrast (WCAG, `contrast_ratio` below) is computed by a TEST, not by
#: eye: `kir/tests/test_the_dark_sheet_is_the_same_sheet.py`.
_DARK_FOR: dict[str, str] = {
    # paper, field, footer, frames
    "#ffffff": "#12161c",   # sheet, opening, tag circle, the second half of the dimension mark
    "#fcfcfd": "#171c24",   # the drawing field and the "hole" (role=void)
    "#f7f8fa": "#151a21",   # footer
    "#dfe4ea": "#39434f",   # field frame, footer frame, divider
    # ink
    "#2b3440": "#e8edf3",   # primary: header text, wall, dimension, north
    "#3c4855": "#cdd6e0",   # element labels and footer text
    "#5a6673": "#a7b3c1",   # coverage line
    "#8a95a1": "#7f8b99",   # digest and notes
    "#78838f": "#8e9aa8",   # small labels and the pixel scale
    # MEANINGFUL COLORS — the ones this table exists for
    "#c0392b": "#ff6b5e",   # anomaly
    "#8a5200": "#ffb020",   # approximation (an axis instead of a body)
    "#b0392e": "#ff7d6d",   # refusal: empty / north not set
    "#6b5424": "#e8c46a",   # opening tag text
    # layers
    "#e8eef5": "#1d2733",   # room (fill)
    "#b6c4d4": "#4d5e70",   # room (edge)
    "#9aa7b4": "#7d8b9a",   # slab
    "#b9c2cc": "#6f7a86",   # equipment
    "#7fa8c9": "#7fb6e0",   # MEP
    "#8f9aa6": "#8b96a3",   # line
    "#a8b4c0": "#7e8b99",   # room separator
    "#c2a15a": "#d0ad63",   # grid
    "#6d7c8b": "#93a3b4",   # stairs
    "#4a5563": "#adb8c6",   # column
    "#c9d0d8": "#3c4653",   # compass ring
    # sources
    "#b26a00": "#ffb14d",   # PROGRAM accent
    "#fff3e0": "#2a2013",   # PROGRAM stripe
    "#1d5b8f": "#7fbdf0",   # DECOMPILE accent
    "#e7f0f8": "#132330",   # DECOMPILE stripe
}

#: The table's public name: the window has every right to recolor the
#: sheet on its own side, without asking for a second render. The
#: promise "only the colors differ" holds there too.
DARK_PALETTE = _DARK_FOR

THEMES: tuple[str, ...] = ("light", "dark")

#: Who the sheet is addressed to. `human` — to a human: the drawing and
#: ONE line in their own words. `instrument` — to the instrument and to
#: analysis: the census, blind spots, the signature, coverage. The
#: owner's word of 08.09: "there's a pile of garbage information for a
#: human… he needs to see the minimum amount of info… he shouldn't have
#: to guess what our labels mean. even I don't know." Nothing is
#: deleted — the RECIPIENT changed: everything that left the human sheet
#: lives in `<metadata>` of the same file and in the card's `details`
#: (`program_card`).
AUDIENCES: tuple[str, ...] = ("human", "instrument")

_HEX = re.compile(r"#[0-9a-f]{6}")


def _relative_luminance(colour: str) -> float:
    """WCAG 2.1. Needed by the contrast test, so it is public within the
    module."""
    raw = colour.lstrip("#")
    parts = []
    for index in (0, 2, 4):
        value = int(raw[index:index + 2], 16) / 255.0
        parts.append(value / 12.92 if value <= 0.03928
                     else ((value + 0.055) / 1.055) ** 2.4)
    red, green, blue = parts
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    """The WCAG contrast ratio. 4.5 is the threshold for readable text."""
    a, b = _relative_luminance(first), _relative_luminance(second)
    high, low = max(a, b), min(a, b)
    return (high + 0.05) / (low + 0.05)


def _to_dark(chunk: str) -> str:
    """Recolor a piece of markup. An unfamiliar color is a REFUSAL, not
    "leave as is".

    The table must be complete: a color forgotten in it would glow as a
    white patch on the dark sheet, and we would learn about it from a
    human, not from an instrument.
    """
    def swap(match: re.Match) -> str:
        light = match.group(0)
        try:
            return _DARK_FOR[light]
        except KeyError:
            raise PreviewError(
                f"цвета {light} нет в таблице тёмной темы (_DARK_FOR): "
                f"тёмный лист был бы неполон") from None
    return _HEX.sub(swap, chunk)


def _human_title(plan: FloorPlan, title_ru: str) -> str:
    """ONE line for a human. It contains no instrument words, by
    construction."""
    if title_ru.strip():
        return title_ru.strip()
    подпись = f"План · этаж «{plan.level_name}»"
    if plan.level_elevation_mm is not None:
        подпись += f" · отм. {_fmt(plan.level_elevation_mm)} мм"
    return подпись


def render_svg(plan: FloorPlan, *, theme: str = "light",
               audience: str = "human", title_ru: str = "",
               focus: Sequence[str] | None = None,
               chrome: bool = True) -> str:
    """ONE renderer for both sources. The same input, the same byte.

    `theme` — "light" or "dark": the dark one is produced by ONE
    substitution via `_DARK_FOR` over the finished light sheet, so two
    sheets of the same scene differ ONLY in color values — by
    construction, not by promise.

    `audience` — "human" (the default) or "instrument". For a human: the
    drawing and one line in THEIR OWN words (`title_ru`). For the
    instrument: everything that was on the sheet before 08.09 — the
    census, blind spots, coverage, the signature, the watermark. Nothing
    is lost: `<metadata>` rides in BOTH, and it holds the whole
    `plan.to_dict()`.

    `focus` — the identifiers of the elements that are the SUBJECT OF THE
    REQUEST. Everything else on the sheet dims toward context
    (`opacity`), rather than disappearing: the human asked for a cube,
    and the cube must be visible among ninety unrelated elements.

    🔴 `chrome` — THE SHEET'S FURNITURE: the header band with the title,
    the scale bar («0 / 1 м», «1 px = 3.74 мм») and the north marker
    («ПН (+Y)», «истинный север не задан»). `True` keeps every existing
    byte for every existing caller. `False` is for the KIR WINDOW, and
    it is not taste: the owner, 13.09.2026, looking at that window —
    «там куча непонятной инфы, не относящейся к моделированию». A
    drawing shown INSIDE a modelling window has a scale of its own (the
    window zooms), and a north it did not read is a claim, not a service.
    Nothing is lost: all of it stays in `<metadata>`, whole, in both
    modes.
    """
    if theme not in THEMES:
        raise PreviewError(f"тема {theme!r} не из {THEMES}")
    if audience not in AUDIENCES:
        raise PreviewError(f"адресат {audience!r} не из {AUDIENCES}")
    для_прибора = audience == "instrument"
    в_фокусе = frozenset(focus) if focus is not None else None
    style = _SOURCE_STYLE[plan.source]
    extents = plan.extents_mm()
    parts: list[str] = []
    out = parts.append

    out(f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_W}" '
        f'height="{SHEET_H}" viewBox="0 0 {SHEET_W} {SHEET_H}" '
        f'font-family="DejaVu Sans, Helvetica, Arial, sans-serif">')
    заголовок = _human_title(plan, title_ru)
    out(f'<title>{_esc(заголовок)}</title>' if not для_прибора else
        f'<title>{_esc(plan.doc_name)} — {_esc(plan.level_name)} — '
        f'{_esc(style["title"])}</title>')
    # THE MACHINE CHANNEL RIDES IN BOTH SHEETS AND IS NOT COLORED. The
    # census left the human's sheet — but not the file: it is here, in
    # full, together with the blind spots and the signature. The
    # RECIPIENT changed, not the contents.
    meta_index = len(parts)
    out('<metadata id="kir-preview">'
        + _esc(json.dumps({**plan.to_dict(),
                           "content_digest": plan.content_digest},
                          sort_keys=True, ensure_ascii=False,
                          separators=(",", ":")))
        + '</metadata>')
    out(f'<rect width="{SHEET_W}" height="{SHEET_H}" fill="#ffffff"/>')

    # --- sheet border: for a self-check it is DASHED (law #6)
    dash = f' stroke-dasharray="{style["border_dash"]}"' if style["border_dash"] else ""
    out(f'<rect x="8" y="8" width="{SHEET_W - 16}" height="{SHEET_H - 16}" '
        f'fill="none" stroke="{style["accent"]}" stroke-width="3"{dash}/>')

    # --- header
    census = plan.census
    if chrome:
        out(f'<rect x="8" y="8" width="{SHEET_W - 16}" height="{HEADER_H}" '
            f'fill="{style["band"]}"/>')
    if not chrome:
        pass
    elif not для_прибора:
        # 🔴 ONE LINE IN THEIR OWN WORDS. Here stood THREE lines of the
        # instrument's own text («ПРЕВЬЮ ПРОГРАММЫ · САМОПРОВЕРКА»,
        # «рисуется ЗАЯВЛЕННОЕ автором. Модель НЕ читалась», «нарисовано
        # 94 из 98» + «покрытие 95.9% · приближений 43» + «digest
        # 93310f47…»). The owner's word of 08.09: "he shouldn't have to
        # guess what our labels mean. even I don't know."
        out(f'<text x="28" y="58" font-size="22" font-weight="bold" '
            f'fill="#2b3440">{_esc(заголовок)}</text>')
        # THE SECOND LINE IS DELIBERATELY ABSENT. `plan.notes[0]` used to
        # stand here — the program's intent («куб») — and on the cube it
        # REPEATED the title word for word. A repeat is the same
        # clutter, just a polite one: it takes up a line and adds no
        # fact. Notes live in full inside `<metadata>`.
    else:
        out(f'<text x="28" y="46" font-size="24" font-weight="bold" '
            f'fill="{style["accent"]}">{_esc(style["title"])}</text>')
        out(f'<text x="28" y="72" font-size="15" fill="#2b3440">'
            f'{_esc(plan.doc_name)} · этаж <tspan font-weight="bold">'
            f'{_esc(plan.level_name)}</tspan>'
            + (f' · отм. {_fmt(plan.level_elevation_mm)} мм'
               if plan.level_elevation_mm is not None else '')
            + '</text>')
        out(f'<text x="28" y="94" font-size="12.5" fill="{style["accent"]}">'
            f'{_esc(style["claim"])}</text>')
        summary = (f'нарисовано {census.drawn} из {census.considered}'
                   if not census.vacuous else 'НЕЧЕГО РИСОВАТЬ (0 элементов)')
        out(f'<text x="{SHEET_W - 28}" y="46" font-size="20" text-anchor="end" '
            f'font-weight="bold" fill="#2b3440">{_esc(summary)}</text>')
        out(f'<text x="{SHEET_W - 28}" y="70" font-size="13" text-anchor="end" '
            f'fill="#5a6673">покрытие {census.coverage_pct:.1f}% · '
            f'приближений {census.approx_total} · '
            f'аномалий {census.anomaly_total}</text>')
        out(f'<text x="{SHEET_W - 28}" y="92" font-size="11" text-anchor="end" '
            f'fill="#8a95a1">digest {plan.content_digest[:16]}</text>')

    # --- drawing field
    out(f'<rect x="{DRAW_X}" y="{DRAW_Y}" width="{DRAW_W}" height="{DRAW_H}" '
        f'fill="#fcfcfd" stroke="#dfe4ea" stroke-width="1"/>')

    # The watermark goes UNDER the geometry: it must be visible at first
    # glance, and it has no right to obscure the reason the sheet was
    # opened.
    if style["watermark"] and для_прибора:
        out(f'<text x="{SHEET_W / 2}" y="{DRAW_Y + DRAW_H / 2}" '
            f'font-size="150" text-anchor="middle" fill="{style["accent"]}" '
            f'opacity="0.09" font-weight="bold" '
            f'transform="rotate(-24 {SHEET_W / 2} {DRAW_Y + DRAW_H / 2})">'
            f'{_esc(style["watermark"])}</text>')

    if extents is None:
        out(f'<text x="{DRAW_X + DRAW_W / 2}" y="{DRAW_Y + DRAW_H / 2}" '
            f'font-size="22" text-anchor="middle" fill="#b0392e">'
            f'ПУСТО: ни одна фигура не построена</text>')
        scale = 0.0
    else:
        min_x, min_y, max_x, max_y = extents
        span_x = max(max_x - min_x, 1.0)
        span_y = max(max_y - min_y, 1.0)
        pad = 26.0
        scale = min((DRAW_W - 2 * pad) / span_x, (DRAW_H - 2 * pad) / span_y)
        off_x = DRAW_X + pad + ((DRAW_W - 2 * pad) - span_x * scale) / 2.0
        off_y = DRAW_Y + pad + ((DRAW_H - 2 * pad) - span_y * scale) / 2.0

        def to_px(point: Pt) -> tuple[float, float]:
            return (off_x + (point[0] - min_x) * scale,
                    off_y + (max_y - point[1]) * scale)

        out(f'<clipPath id="fld"><rect x="{DRAW_X}" y="{DRAW_Y}" '
            f'width="{DRAW_W}" height="{DRAW_H}"/></clipPath>')
        out('<g clip-path="url(#fld)">')

        ordered = sorted(tuple(plan.datums) + tuple(plan.elements),
                         key=_sort_key)
        for element in ordered:
            out(_render_element(element, to_px, scale, в_фокусе))
        out('</g>')

        if plan.outliers:
            out(f'<text x="{DRAW_X + DRAW_W - 18}" y="{DRAW_Y + DRAW_H - 16}" '
                f'font-size="12.5" text-anchor="end" fill="#c0392b" '
                f'font-weight="bold">КАДР ПО ЯДРУ: {plan.outliers} '
                f'элемент(ов) улетели за облако и обрезаны полем '
                f'(см. аномалии)</text>')

        if chrome:
            out(_scale_bar(scale))

    if chrome:
        out(_north_marker())
    if для_прибора:
        out(_footer(plan, style))
    out('</svg>')
    if theme == "dark":
        # THE ONE PLACE WHERE THE THEMES DIVERGE. Metadata is not
        # colored.
        parts = [chunk if index == meta_index else _to_dark(chunk)
                 for index, chunk in enumerate(parts)]
    return "\n".join(parts) + "\n"


def _render_element(element: DrawnElement, to_px, scale: float,
                    focus: frozenset[str] | None = None) -> str:
    style = dict(_STYLE[element.layer])
    flagged = bool(element.anomalies)
    if flagged:
        style = {**style, "stroke": "#c0392b", "width": max(
            float(style["width"]), 1.6)}
    chunks: list[str] = []
    attrs = (f' data-el="{_esc(element.element_id)}" '
             f'data-cat="{_esc(element.category)}"')
    if flagged:
        attrs += (' data-anomaly="'
                  + _esc(",".join(r.value for r in element.anomalies)) + '"')
    # THE SUBJECT OF THE REQUEST GLOWS, EVERYTHING ELSE DIMS — but does
    # not disappear: "not drawn" and "drawn faintly" are different
    # facts, and the second is more honest.
    if focus is not None and element.element_id not in focus:
        attrs += ' data-context="1" opacity="0.16"'
    chunks.append(f'<g{attrs}>')
    for shape in element.shapes:
        if isinstance(shape, Poly):
            path = " ".join(
                "M " + " L ".join(
                    f"{_fmt(px)} {_fmt(py)}"
                    for px, py in (to_px(point) for point in loop)) + " Z"
                for loop in shape.loops if loop)
            if not path:
                continue
            if shape.role == "void":
                fill, stroke = "#fcfcfd", "none"
            elif shape.role == "outline":
                fill, stroke = "none", style["stroke"]
            else:
                fill, stroke = style["fill"], style["stroke"]
            dash = (f' stroke-dasharray="{style["dash"]}"'
                    if style.get("dash") and shape.role != "solid" else "")
            chunks.append(
                f'<path d="{path}" fill="{fill}" fill-rule="evenodd" '
                f'stroke="{stroke}" stroke-width="{style["width"]}"{dash}/>')
        elif isinstance(shape, Path):
            pts = [to_px(point) for point in shape.pts]
            if len(pts) < 2:
                continue
            path = ("M " + " L ".join(f"{_fmt(px)} {_fmt(py)}"
                                      for px, py in pts))
            width = float(style["width"])
            dash = ""
            stroke_override = ""
            if shape.role == "thin":
                width = max(0.6, width * 0.7)
            elif shape.role == "spine":
                # An axis instead of a body: the line must be NOTICEABLY
                # different, so that "thickness unknown" reads off the
                # sheet, not only from the census. Since 08.09 it is
                # also COLORED: thickness alone is not enough, and the
                # dark theme must keep the approximation distinguishable
                # — the contrast of both values is computed by a test
                # (≥ 4.5 against the field).
                width = 2.4
                stroke_override = "#8a5200"
            elif shape.role == "tick":
                width = max(1.2, width)
            elif shape.role == "dashed":
                dash = f' stroke-dasharray="{style.get("dash", "5 4")}"'
            elif shape.role == "axis":
                dash = f' stroke-dasharray="{style.get("dash", "18 5 3 5")}"'
            chunks.append(
                f'<path d="{path}" fill="none" '
                f'stroke="{stroke_override or style["stroke"]}" '
                f'stroke-width="{_fmt(width)}"{dash}/>')
        elif isinstance(shape, Dot):
            px, py = to_px(shape.xy)
            radius = max(1.6, shape.r_mm * scale)
            chunks.append(
                f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="{_fmt(radius)}" '
                f'fill="{style["stroke"]}" opacity="0.85"/>')
        else:  # TextMark
            px, py = to_px(shape.xy)
            if shape.role == "bubble":
                chunks.append(
                    f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="11" '
                    f'fill="#ffffff" stroke="{style["stroke"]}" '
                    f'stroke-width="1"/>')
                chunks.append(
                    f'<text x="{_fmt(px)}" y="{_fmt(py + 3.6)}" font-size="9.5" '
                    f'text-anchor="middle" fill="#6b5424">'
                    f'{_esc(shape.text[:5])}</text>')
                continue
            # A label is printed only if there is room for it on the
            # sheet. The threshold is deterministic: the contour's area
            # in pixels. A zero ``min_area_mm2`` means "there is room by
            # construction" (a point-like program label), not "there is
            # no room".
            if 0.0 < shape.min_area_mm2 * scale * scale < 2600.0:
                continue
            size = 11.0 if shape.role == "label" else 9.0
            dy = -3.0 if shape.role == "label" else 10.0
            colour = "#3c4855" if shape.role == "label" else "#78838f"
            text = shape.text if len(shape.text) <= 22 else shape.text[:21] + "…"
            chunks.append(
                f'<text x="{_fmt(px)}" y="{_fmt(py + dy)}" font-size="{size}" '
                f'text-anchor="middle" fill="{colour}">{_esc(text)}</text>')
    chunks.append('</g>')
    return "".join(chunks)


def _scale_bar(scale: float) -> str:
    if scale <= 0:
        return ""
    bar_mm = _nice_length((DRAW_W * 0.22) / scale)
    bar_px = bar_mm * scale
    x0 = DRAW_X + 18
    y0 = DRAW_Y + DRAW_H - 26
    label = (f"{_fmt(bar_mm / 1000.0)} м" if bar_mm >= 1000
             else f"{_fmt(bar_mm)} мм")
    return (
        f'<g><rect x="{_fmt(x0)}" y="{_fmt(y0)}" width="{_fmt(bar_px / 2)}" '
        f'height="7" fill="#2b3440"/>'
        f'<rect x="{_fmt(x0 + bar_px / 2)}" y="{_fmt(y0)}" '
        f'width="{_fmt(bar_px / 2)}" height="7" fill="#ffffff" '
        f'stroke="#2b3440" stroke-width="1"/>'
        f'<text x="{_fmt(x0)}" y="{_fmt(y0 - 6)}" font-size="11" '
        f'fill="#2b3440">0</text>'
        f'<text x="{_fmt(x0 + bar_px)}" y="{_fmt(y0 - 6)}" font-size="11" '
        f'text-anchor="end" fill="#2b3440">{_esc(label)}</text>'
        f'<text x="{_fmt(x0)}" y="{_fmt(y0 + 20)}" font-size="10.5" '
        f'fill="#78838f">1 px = {_fmt(1.0 / scale)} мм</text></g>')


def _north_marker() -> str:
    """The PROJECT north arrow.

    True north is not a field in L0 (checked against
    ``decompile/schema.py``/``extract.py``: neither ``ProjectPosition``
    nor an angle), so the arrow is labeled honestly. Silently drawing
    "N" would mean passing the orientation off as something that was
    read.
    """
    cx = SHEET_W - 96
    cy = DRAW_Y + 74
    return (
        f'<g><circle cx="{cx}" cy="{cy}" r="30" fill="#ffffff" '
        f'stroke="#c9d0d8" stroke-width="1"/>'
        f'<path d="M {cx} {cy - 22} L {cx + 9} {cy + 14} L {cx} {cy + 6} '
        f'L {cx - 9} {cy + 14} Z" fill="#2b3440"/>'
        f'<text x="{cx}" y="{cy + 44}" font-size="11" text-anchor="middle" '
        f'font-weight="bold" fill="#2b3440">ПН (+Y)</text>'
        f'<text x="{cx}" y="{cy + 58}" font-size="9" text-anchor="middle" '
        f'fill="#b0392e">истинный север не задан</text></g>')


def _rest_line(groups: Sequence[Any], shown: int,
               what: str) -> list[tuple[str, str]]:
    """«… ещё N» AS ONE RULE across all three columns of the census.

    The remainder used to be named only by the omissions column;
    approximations, anomalies, and blind spots were truncated silently
    (measured 04.08: 7 approximation groups → 5 lines and not a word, 5
    anomalies → 4 lines and not a word, 6 blind spots → 4 and not a
    word). One rule instead of three places — because someone will add a
    fourth column, and bypassing a shared helper is harder than
    forgetting to copy the slice.
    """
    if len(groups) <= shown:
        return []
    rest = sum(g.count for g in groups[shown:])
    return [("", f"{rest:>7}  … ещё {len(groups) - shown} {what}")]


def _footer(plan: FloorPlan, style: Mapping[str, str]) -> str:
    census = plan.census
    #: THE TEXTS OF TRUNCATION NOTICES. A set, not a signal read from a
    #: line's shape: recognizing a notice by a regular expression on
    #: «… и ещё» would mean setting up a second source of truth about its
    #: own format — and it would diverge from `_rest_line` on the very
    #: first edit of its text.
    вести: set[str] = set()

    def _весть(построенное: list[tuple[str, str]]) -> list[tuple[str, str]]:
        вести.update(текст for _, текст in построенное)
        return построенное

    lines_left: list[tuple[str, str]] = []
    lines_left.append(("ПЕРЕПИСЬ",
                       f"рассмотрено {census.considered} · "
                       f"нарисовано {census.drawn} · "
                       f"не нарисовано {census.omitted_total}"))
    for group in census.omitted[:_FOOTER_OMIT_ROWS]:
        text = _OMIT_TEXT.get(group.reason, group.reason.value)
        lines_left.append(("", f"{group.count:>7}  {group.category} — {text}"))
    lines_left.extend(_весть(_rest_line(census.omitted, _FOOTER_OMIT_ROWS,
                                 "строк(и) причин")))

    lines_right: list[tuple[str, str]] = []
    if census.approx:
        lines_right.append(("НАРИСОВАНО, НО НЕ ТОЧНО", ""))
        for group in census.approx[:_FOOTER_APPROX_ROWS]:
            lines_right.append(
                ("", f"{group.count:>7}  "
                     f"{_APPROX_TEXT.get(group.reason, group.reason.value)}"))
        lines_right.extend(_весть(_rest_line(census.approx, _FOOTER_APPROX_ROWS,
                                      "строк(и) приближений")))
    if census.anomalies:
        lines_right.append(("АНОМАЛИИ (нарисованы красным)", ""))
        for group in census.anomalies[:_FOOTER_ANOMALY_ROWS]:
            lines_right.append(
                ("", f"{group.count:>7}  "
                     f"{_ANOMALY_TEXT.get(group.reason, group.reason.value)} "
                     f"[{', '.join(group.examples[:3])}]"))
        lines_right.extend(_весть(_rest_line(census.anomalies, _FOOTER_ANOMALY_ROWS,
                                      "строк(и) аномалий")))
    if not lines_right:
        lines_right.append(("НАРИСОВАНО, НО НЕ ТОЧНО", ""))
        lines_right.append(("", "      —  приближений и аномалий не отмечено"))
    lines_right.append(("ЭТОТ ЭКРАН НЕ ПОКАЖЕТ", ""))
    for spot in BLIND_SPOTS[:_FOOTER_BLIND_ROWS]:
        lines_right.append(("", f"      ·  {spot}"))
    if len(BLIND_SPOTS) > _FOOTER_BLIND_ROWS:
        # A blind-spot list truncated silently reads as "this is exactly
        # what the blindness is" — that is, it lies in precisely the
        # direction this sheet is not allowed to lie in.
        lines_right.extend(_весть([
            ("", f"      ·  … и ещё {len(BLIND_SPOTS) - _FOOTER_BLIND_ROWS} "
                 f"вид(а) слепоты — см. preview.BLIND_SPOTS")]))

    chunks = [f'<rect x="{DRAW_X}" y="{FOOTER_Y}" width="{DRAW_W}" '
              f'height="{SHEET_H - FOOTER_Y - 24}" fill="#f7f8fa" '
              f'stroke="#dfe4ea" stroke-width="1"/>']
    chunks.append(f'<line x1="{SHEET_W / 2}" y1="{FOOTER_Y}" '
                  f'x2="{SHEET_W / 2}" y2="{SHEET_H - 24}" '
                  f'stroke="#dfe4ea" stroke-width="1"/>')

    def column(lines: Sequence[tuple[str, str]], x: float) -> None:
        y = FOOTER_Y + 24
        for head, body in lines:
            if head:
                chunks.append(
                    f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-size="12" '
                    f'font-weight="bold" fill="{style["accent"]}">'
                    f'{_esc(head)}</text>')
                y += 18
            if body:
                chunks.append(
                    f'<text x="{_fmt(x)}" y="{_fmt(y)}" font-size="11.5" '
                    f'fill="#3c4855" xml:space="preserve" '
                    f'font-family="DejaVu Sans Mono, monospace">'
                    f'{_esc(body)}</text>')
                y += 17

    # 🔴 THE FOOTER IS TRUNCATED BY HEIGHT, AND THE TRUNCATION IS NAMED.
    # Measured 25.08.2026: four independent budget constants (7·5·4·4)
    # were computed without regard to how many lines the footer itself
    # holds — 288 px at a 17 px step, that is, 16.9 lines. A sweep over
    # the grid of approximations × anomalies:
    #
    #     ap=4,an=5 -> 1 line PAST the edge of the sheet
    #     ap=5,an=4 -> 1        ap=6,an=3 -> 1
    #     ap=6,an=5 -> 3
    #
    # And it was exactly the LAST lines of the right column that fell
    # off — that is, the BLIND-SPOT list and the «… и ещё N видов
    # слепоты» line, set up expressly against silent truncation. The
    # module written to forbid silence was itself silent, and
    # understated its own blindness.
    _ЁМКОСТЬ = int((SHEET_H - 24 - (FOOTER_Y + 24)) // 17)

    def _вместить(lines: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """Trim to the footer's capacity, NAMING what was trimmed.

        🔴 THE TRUNCATION NOTICE IS DISCARDED LAST, AND THIS IS NOT SORT
        ORDER, IT IS MEANING (01.09.2026). The previous edition cut the
        list straight through and replaced the tail with a shared line,
        «… и ещё N строк(и) подвала не поместились». The right column's
        tail is EXACTLY the `_rest_line` notices and the «… и ещё N
        вид(а) слепоты» line — that is, the very declarations of WHAT was
        trimmed. And those were cut first: on a full census (every
        `OmitReason`, `ApproxReason`, `AnomalyReason`), the notice of
        blindness left the sheet, and the reader got "this is exactly
        what the blindness is" instead of "the blindness was trimmed".
        The module written to forbid silence was itself silent — the
        same defect that, two paragraphs above, was already named and
        fixed BY HEIGHT, but not BY COMPOSITION: it counted how many
        lines would fit, and never asked which of them carry the meaning
        of the truncation.

        So the notices always go through, and the budget is taken from
        the ordinary lines instead. If something is still discarded
        after that, the shared notice is added on top — it is about the
        SHEET, not about the census, and has no right to substitute
        itself for the census's own notices.
        """
        if len(lines) <= _ЁМКОСТЬ:
            return lines
        вести_здесь = [ln for ln in lines if ln[1] in вести]
        бюджет = _ЁМКОСТЬ - len(вести_здесь) - 1   # one line reserved for the sheet's own notice
        оставлено: list[tuple[str, str]] = []
        выброшено = 0
        for ln in lines:
            if ln[1] in вести:
                оставлено.append(ln)
            elif бюджет > 0:
                оставлено.append(ln)
                бюджет -= 1
            else:
                выброшено += 1
        if выброшено:
            оставлено.append(
                ("", f"      ·  … и ещё {выброшено} строк(и) "
                     f"подвала не поместились на лист"))
        return оставлено

    column(_вместить(lines_left), DRAW_X + 18)
    column(_вместить(lines_right), SHEET_W / 2 + 18)

    for index, note in enumerate(plan.notes[:2]):
        chunks.append(
            f'<text x="{DRAW_X + 18}" y="{SHEET_H - 34 + index * 14}" '
            f'font-size="10.5" fill="#8a95a1">{_esc(note)}</text>')
    return "".join(chunks)


def _notes_for(census: PreviewCensus, source: PreviewSource,
               subtitle: str) -> tuple[str, ...]:
    notes: list[str] = []
    if subtitle:
        notes.append(subtitle[:120])
    if source is PreviewSource.PROGRAM:
        notes.append("самопроверка: несовпадение с моделью этим листом "
                     "не обнаруживается")
    else:
        notes.append(f"источник: L0 (независимое чтение), "
                     f"приближений {census.approx_total}")
    return tuple(notes)
