"""KIR CONTOUR — the sketch-geometry sublanguage (v2 invention, 2026-07-17).

THE PINNED DECISIONS (Sonnet waves tile new sketch-ops on these; changing any
of them is a Fable-level language change, not a patch):

1. CANONICAL LOWERED FORM: every profile shape lowers to a closed edge list
   [(p0_mm, p1_mm, bulge), ...] — p1 of edge k == p0 of edge k+1, ring closed
   implicitly. `bulge` is the DXF convention: tan(sweep/4), 0 = straight
   line, sign = CCW positive. ALL trigonometry happens at COMPILE time in
   python — emitted C# only ever sees three literal points per arc
   (Arc.Create(start, end, pointOnArc), version-safe 2014+).
2. CLOSED BY CONSTRUCTION beats closed-by-check: rect/l/ring shapes cannot
   express an open or self-intersecting region at all; only `poly` needs the
   full static law (normalize closure, short edges, self-intersection with
   arcs sampled at 8 chords — deterministic documented approximation).
3. ANCHORS: any point is a literal [x,y] OR an ADDRESS resolved at ground
   time from the grids pool (id/name/p0_mm/p1_mm); a missing / duplicate /
   geometry-less / near-parallel grid is a typed refusal with candidates.
   No other anchor kinds in v2.0 of CONTOUR.
   UPDATED 04.08.2026: the address grammar has moved entirely into
   `relate.py` (RELATE), and CONTOUR became its consumer — `resolve_anchor`
   no longer owns either the parsing or the refusals. The legacy form
   `offset_mm: [dx,dy]` (WORLD frame) is kept exactly here and exactly for
   the sake of the `region` goldens; the new offset form is node-based,
   `{"grid": "Б", "offset_mm": 200,
   "toward": "В"}`, and it also works inside `region`.
4. A REGION = {"outer": <shape>, "holes": [<shape>...]} — holes obey the
   same shape laws recursively, must lie strictly inside the outer (arc
   sample points included), pairwise disjoint. Same law set as v1.1 geom.py,
   lifted to arcs.
5. TOLERANCES (single source): _EDGE_TOL=1mm, |bulge|<=1.5, radius form
   requires radius >= chord/2 * 1.0005, area >= 1e4 mm².

Shapes v2.0: SEE `SHAPE_FORMS` BELOW — it is the specification itself.

🔴 A FOURTH hand-written list of shapes used to stand here (docstring,
`_validate_shape` literals, `schema_gen.py` — and this one). Nothing forced
them to agree, and on 16.08.2026 a measurement by execution showed they had
ALREADY diverged: three programs out of three were legal under the schema
the model receives, and were rejected by the compiler. The list was removed
deliberately: prose that is obliged to agree with the data is obliged to be
DERIVED from it. Printing the shape is `shape_forms_text()`; the legal
fields are `shape_fields()`; and both read `SHAPE_FORMS`.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir import relate
from kir.diag import (Diagnostic, KirRefusal, TYPE_BAD_TYPE,
                          TYPE_BOUNDS, TYPE_GEOM_RELATION)
from kir.emit_utils import is_finite_number
# The coordinate limit is ONE for the whole tree, from the registry.
from kir.registry_base import COORD_LIMIT_MM
from kir.geom import (
    MAX_HOLES,
    MAX_RING_POINTS,
    MIN_RING_AREA_MM2,
    MIN_RING_POINTS,
    MIN_RING_POINTS_ARCED,
    _dist,
    _first_self_intersection,
    _seg_intersect,
    check_holes_relation,
)

_EDGE_TOL = 1.0

#: The shape's side bounds. Used to be LITERALS inside `_validate_shape` and
#: never reached the model at all: the JSON schema declared `size_mm` as
#: plain numbers. Measured 16.08.2026 by execution — a program with
#: `size_mm=[50,50]` is LEGAL under the schema the model receives, and is
#: REJECTED by the compiler. Three such cases out of three checked.
SHAPE_SIDE_MIN_MM = 100.0
SHAPE_SIDE_MAX_MM = 500_000.0
SHAPE_ROTATION_ABS_MAX_DEG = 360.0


class _Slot(tuple):
    """One shape slot: name, kind, required flag, bounds, default.

    A tuple, not a dataclass, because the table below is DATA, and it is
    read by three consumers: the validator (the set of legal fields), the
    schema generator (the bounds), and the refusal text (what to show the
    human and the model).
    """

    __slots__ = ()

    def __new__(cls, name: str, kind: str, *, required: bool = False,
                bounds: str = "", default: str = ""):
        return super().__new__(cls, (name, kind, required, bounds, default))

    name = property(lambda self: self[0])
    kind = property(lambda self: self[1])
    required = property(lambda self: self[2])
    bounds = property(lambda self: self[3])
    default = property(lambda self: self[4])


#: 🔴 A SINGLE AUTHORITY FOR SHAPES. Before 16.08.2026 the specification was
#: written THREE TIMES: in this file's docstring, in `_validate_shape`'s
#: literals, and by hand in `schema_gen.py`. Nothing forced them to agree —
#: a named defect of the project — and they had ALREADY diverged: the schema
#: the model sees carried not a single bound.
#:
#: The refusal text is derived from that same source. The previous one
#: named three shapes and showed NONE of them ("форма — rect | l | poly");
#: an agent that received it in a live run on 16.08 spent three attempts and
#: still never hit `rect` — it uses `size_mm`, not `w`/`h`. A turn costs
#: 17–18 s (measured the same day), meaning a refusal without the shape
#: costs a full turn.
# ── SPLINE: THE THIRD EDGE KIND (20.08.2026) ──────────────────────────────────
#
# WHY. Before this day a contour had TWO edge kinds — line and arc (|bulge| <=
# 1.5, i.e. up to 225°). The language could not express a free-form shape in
# plan at all, even though the REVERSE path decompiles splines in full
# (`decompile/name.py:78` knows six kinds, `geom_extract.py` reads
# degree/knots/weights, `recompile.py` rebuilds through
# `NurbSpline.CreateCurve`). We could read what we could not say.
#
# WHY INTERPOLATION, NOT A CONTROL POLYGON. `NurbSpline.CreateCurve` takes
# CONTROL points, and the curve does NOT pass through them; `HermiteSpline
# .Create` takes points the curve passes through. For an environment whose
# main user is an LLM, this is not a matter of taste: "run a curve through
# these points" is something the model can check for itself, while "here is
# a control polygon" requires also holding in mind how Revit will smooth it.
# The constitution settles this dispute directly: what comes from the
# BUILDING is mandatory, what comes from a tool's habits is surplus.
# Both factories are 6/6 by `data/api_surface`, the compilation probe is 5/5
# (`Floor.Create` has existed since 2022), and both the CS0117 and CS0200
# controls tell them apart.
#
# 🔴 THE LANGUAGE DESCRIBES ITS TWO CURVE KINDS DIFFERENTLY, AND THAT IS A
# DECISION, NOT AN INCONSISTENCY (20.08.2026, reconciling two waves). A
# contour edge takes POINTS THE CURVE PASSES THROUGH; a surface (`surface.py`)
# takes CONTROL points. The REVERSE PATH decides the difference, not taste:
#
#   surface        `geom_extract.__gxNurbsSurface` already reads degree,
#                  knots, CONTROL points, and weights. Had the language
#                  chosen interpolation, the round trip would not close by
#                  construction: we would say one thing going forward and
#                  read another coming back, with OUR OWN approximation
#                  standing between them;
#   contour edge   `sketch_extract` accepts EXACTLY `line|arc` ("curve_kinds
#                  supports only line/arc") — it does not read a spline AT
#                  ALL. So the round trip is not yet built here, the input
#                  shape is free, and it is the LLM's profile that chooses
#                  it: "run a curve through these points" is something the
#                  model can check for itself, while a control polygon
#                  requires holding Revit's smoothing rule in mind.
#
# THE CONSEQUENCE TO KNOW IN ADVANCE: once the contour's reverse path is
# taught to read a spline, it will have CONTROL points (Revit hands those
# out, not interpolation points), and the lift will have to either convert
# them into our `via_mm` or honestly refuse. This is a NAMED debt, not a
# forgotten detail: the conversion is possible (interpolation is invertible
# for a clamped curve), but it is not free and is not exact on curves that
# Revit built by a rule other than ours.

# THE DATA SHAPE IS DERIVED FROM THE REVERSE PATH, NOT CHOSEN. `sketch.index.json`
# stores the edge kind as a PARALLEL list (`curve_kinds`, `arc_midpoints`),
# not inside the edge. The forward path mirrors the same shape: an edge
# stays a TRIPLE `(p0, p1, b)`, and the kind is carried by the TYPE of the
# third element — `float` for a line and an arc, :class:`Spline` for a
# spline. Two load-bearing consequences follow: the unpacking
# `for p0, p1, b in edges` stays intact in all five places, and the bytes of
# any program WITHOUT a spline do not move by a single character.
#
# AND A THIRD, THE REASON A TYPE WAS CHOSEN OVER A TAG VALUE: any reader that
# expects a number (`abs(b)`, a threshold comparison) will, on meeting a
# spline, refuse LOUDLY instead of silently mistaking it for a line. A
# spline silently degenerating into a chord is exactly the class of outcome
# this compiler forbids.

#: How many interior points one spline edge carries.
#: ⚠️ ASSIGNED, not measured — and named that way so it is visible. The
#: lower bound is derived: at zero points a spline is indistinguishable from
#: a line, and the kind would be vacuous. The upper bound is a decision: a
#: ring made of many points is expressed as EDGES, each with its own ends
#: and its own witness, whereas one edge carrying a hundred points makes the
#: chord sampling of the laws more expensive than the program itself.
SPLINE_VIA_MIN = 1
SPLINE_VIA_MAX = 16

#: Chords per spline when sampling for the STATIC laws (closure, area,
#: self-intersection). Same technique and same caveat as `ARC_SAMPLES`: a
#: deterministic, documented approximation, not the truth about the curve.
#: Taken twice as dense as an arc, because a spline through N points can
#: have up to N-1 inflections, whereas an arc has none.
SPLINE_SAMPLES_PER_VIA = 8


class Spline(tuple):
    """A spline edge: the points the curve passes THROUGH between the
    edge's ends.

    A tuple, not a dataclass, for the same reason as `_Slot` above: this is
    DATA, and it must be hashable and comparable byte for byte — fold
    canonicalization and the program digest compare edges directly.

    The edge's ends are NOT STORED here: they already exist in the edge
    itself, and a second copy would silently drift from the first — a named
    defect of this tree.
    """

    __slots__ = ()

    def __new__(cls, via):
        return super().__new__(cls, (tuple((float(x), float(y)) for x, y in via),))

    @property
    def via(self) -> tuple:
        """Interior points, in declared order."""
        return self[0]

    def __repr__(self) -> str:          # diagnostics are read by a human
        return f"Spline({[list(p) for p in self.via]})"


def is_spline(b) -> bool:
    """The kind of an edge's third element. ONE question, one answer, one
    place.

    🔴 THE KIND IS READ FROM THE SHAPE OF THE VALUE, NOT FROM THE OBJECT'S
    TYPE. This used to be `isinstance(b, Spline)`, and it broke EVERYTHING
    the kind existed to protect.

    Found 20.08.2026 by the first live spline call against Revit — offline,
    none of the 2360 gate runs can see this. The payload passes
    CANONICALIZATION THROUGH JSON between grounding and emission
    (`midend._canonical_json`: the plan is signed, and a signature requires
    a canonical shape). JSON knows nothing of tuple subclasses: a `Spline`
    arrives at the emitter as an ORDINARY LIST of the same structure.
    `isinstance` answers "no", the arc branch takes `abs(list)`, and the
    compiler PANICS — KIR-P000, «внутренняя ошибка», with no reason and no
    next move.

    This file's header records the argument that gave the kind to the type:
    "a reader that expects a number will, on meeting a spline, refuse
    LOUDLY instead of mistaking it for a line." The argument is correct and
    was confirmed — but the loudness turned out to be a PANIC, that is, a
    refusal that tells the program's author nothing. The shape of the value
    gives the same loudness and survives the serialization boundary: a
    number is a line or an arc, a sequence is a spline, and neither can be
    mistaken for the other in either direction.

    THE GENERAL RULE worth remembering because of this: A KIND THAT LIVES IN
    A PYTHON OBJECT'S TYPE DOES NOT CROSS THE SERIALIZATION BOUNDARY. And
    the payload always crosses that boundary, because the plan gets signed.
    """
    return isinstance(b, (list, tuple))


def spline_via(b) -> tuple:
    """A spline edge's interior points — from a `Spline` OR from its JSON
    shadow.

    Both forms share one structure (`Spline.__new__` puts the points in as
    one element), so there is a single reader and DELIBERATELY no branching
    by type here: a second carrier of the same knowledge would silently
    drift from the first.
    """
    return tuple((float(x), float(y)) for x, y in b[0])


#: OPS WHOSE WITNESS CAN PROVE A SPLINE.
#:
#: 🔴 THE LIST IS CLOSED AND NOT COMPLETE, AND THAT DIFFERENCE IS
#: LOAD-BEARING: an empty cell means "this op does NOT PROVE a spline," not
#: "it never has a spline." Completeness is unreachable by construction —
#: the witness is written by hand for every op — and declaring the list
#: complete would mean saying "we checked everything," exactly the lie both
#: kinds of lists in this tree exist to guard against.
#:
#: WHY A GUARD AT ALL, RATHER THAN "LET IT THROUGH." The language can say a
#: spline, and emission can build it — but the envelope witness on a spline
#: is UNDERSTATED (see `edges_bbox`), and the "start-middle-end" witness
#: degenerates into a chord. That is, the op would build the curve and sign
#: an envelope it never checked: a silently-wrong outcome, forbidden by the
#: cardinal invariant. A loud refusal with a named next move is the only
#: honest outcome until the witness is written.
SPLINE_WITNESSED_OPS: frozenset[str] = frozenset({
    "create_floor_by_contour",
    # 🔴 THE CEILING WAS ADDED 20.08.2026, AND IT IS THE ONLY ONE THAT FIT.
    # The criterion is closed and checkable: an op must (a) carry a `region`
    # kind parameter — otherwise there is nothing to SAY the curve with, and
    # (b) hang a `sketch_loops_witness` — otherwise there is nothing to READ
    # the curve with, because `spline_points_witness` reaches the same
    # `Sketch.Profile` through `GetDependentElements`.
    #
    # A census of all twelve ops carrying a region (measured 20.08):
    #   region AND a sketch witness   create_floor_by_contour · create_ceiling
    #   region WITHOUT a witness      stairs_landing · beam_system · filled_region
    #                                 opening · building_pad · site_subregion
    #                                 solid_extrusion/blend/revolve/boolean
    # The last four have no sketch at all — they are `DirectShape`.
    #
    # 🔴 AND THE MAIN REFUTATION: the canon is correct that FLOOR, ROOF, and
    # FOUNDATION also read their shape via `Sketch.Profile` — but a spline
    # cannot be added to them, and the obstruction is NOT in the witness but
    # in the LANGUAGE: their shape arrives as the `pts` kind (a bare list of
    # points), which has neither arcs nor splines. Confirmed by execution:
    # `create_roof` with a `splines` field is rejected with
    # `KIR-P003 неизвестное поле 'splines'` — there is no slot. Giving them
    # a curved edge needs a `_by_contour` twin, the way one already exists
    # for the floor; that is separate work, not a line in this list.
    "create_ceiling",
})


SHAPE_FORMS: dict[str, tuple[_Slot, ...]] = {
    "rect": (
        _Slot("origin", "anchor", required=True,
              bounds="точка или привязка к осям"),
        _Slot("size_mm", "[w,h] мм", required=True,
              bounds=f"каждая сторона {SHAPE_SIDE_MIN_MM:.0f}.."
                     f"{SHAPE_SIDE_MAX_MM:.0f}"),
        _Slot("rotation_deg", "число",
              bounds=f"-{SHAPE_ROTATION_ABS_MAX_DEG:.0f}.."
                     f"{SHAPE_ROTATION_ABS_MAX_DEG:.0f}", default="0"),
    ),
    "l": (
        _Slot("origin", "anchor", required=True,
              bounds="точка или привязка к осям"),
        _Slot("size_mm", "[W,H] мм", required=True,
              bounds=f"каждая сторона {SHAPE_SIDE_MIN_MM:.0f}.."
                     f"{SHAPE_SIDE_MAX_MM:.0f}"),
        _Slot("cut_mm", "[cw,ch] мм", required=True,
              bounds=f"каждый {SHAPE_SIDE_MIN_MM:.0f}..(соответствующая "
                     f"сторона − {SHAPE_SIDE_MIN_MM:.0f})"),
        _Slot("corner", "ne|nw|se|sw", default="ne"),
    ),
    "poly": (
        _Slot("points_mm", "список anchor", required=True,
              bounds=f"{MIN_RING_POINTS}..{MAX_RING_POINTS} точек"),
        _Slot("arcs", "список дуг",
              bounds="{edge:i, bulge:b} либо {edge:i, radius_mm:r, dir:ccw|cw}"),
        _Slot("splines", "список сплайнов",
              bounds="{edge:i, via_mm:[[x,y],…]} — кривая ЧЕРЕЗ эти точки, "
                     f"{SPLINE_VIA_MIN}..{SPLINE_VIA_MAX} шт."),
    ),
}


#: How many INVALID contour points are named individually. The remainder is
#: named by a count. The limit exists precisely because usually ALL points
#: are invalid at once (a units error), and without it a refusal would grow
#: to `MAX_RING_POINTS` diagnostics.
#:
#: 🔴 ONE NUMBER FOR BOTH KINDS OF POINTS (26.08.2026). Both RING points
#: (`points_mm`) and CURVE points (`splines[].via_mm[]`) are counted: they
#: share one subject — "how many invalid contour points the author sees in
#: one turn" — and a second carrier of the same law would drift from this
#: one at the very first edit. The number is NOT imported from `ground.py`:
#: its subject there is different (catalog candidates), and a shared
#: constant would tie together two unrelated laws.
#:
#: 🔴 THERE ARE TWO COUNTERS HERE, AND THEY SHOULD NOT BE MERGED INTO ONE.
#: Ring parsing RETURNS `None` before it reaches `arcs`/`splines` — meaning
#: in a single call exactly one of them is ever nonzero, and a shared
#: counter would add nothing beyond a coupling between two independent
#: sections.
_BAD_POINTS_SHOWN = 12


def shape_fields(kind: str) -> set[str]:
    """The shape's legal fields, INCLUDING the `shape` discriminator itself.

    The single source for the "unknown shape fields" check: three such sets
    used to sit as literals in three branches of `_validate_shape`.
    """
    return {"shape", *(slot.name for slot in SHAPE_FORMS[kind])}


#: 🔴 ONE PHRASE, ONE PLACE — AND THE SLOT HELP HAS TO SAY IT TOO (13.09.2026).
#: The region slot takes a WRAPPER, `{outer: shape, holes?: [shape…]}`, but the
#: help for that slot rendered only the SHAPE grammar (`rect | l | poly`), so an
#: author read "shape" and wrote a shape. Measured in the team rehearsal: FOUR
#: independent authors — two people and two model branches — made the same
#: mistake, each spending one of their three rounds on it, on an operation that
#: appears in four of the ten RQ7 tasks. The refusal knew the truth all along;
#: the help did not. The phrase now lives here once, the refusal uses it, and
#: `region_forms_text` is what a help must print for a region slot.
REGION_FORM_RU = "регион — {outer: форма, holes?: [формы]}"


def region_forms_text(field: str, *, got: Any = None) -> str:
    """What a REGION slot must show: the wrapper first, then the shapes.

    A slot help that prints `shape_forms_text` alone is telling the truth about
    the inner half and staying silent about the outer one — which reads as a
    complete answer and is not.
    """
    return f"{field}: {REGION_FORM_RU}\n{shape_forms_text(field, got=got)}"


def shape_forms_text(field: str, *, got: Any = None) -> str:
    """A refusal that SHOWS every shape, rather than listing their names.

    Generated from `SHAPE_FORMS`; there is deliberately no hand-written copy
    here — in this tree, EVERY hand-written list has drifted, and NOT ONE
    generated one has.
    """
    lines = [f"{field}: форма — {' | '.join(SHAPE_FORMS)}. "
             f"ВСЕ поля каждой формы — из реестра, других нет:"]
    for kind, slots in SHAPE_FORMS.items():
        need = [s.name for s in slots if s.required]
        opt = [f"{s.name}=…" for s in slots if not s.required]
        sig = ", ".join(need + ([f"*, {', '.join(opt)}"] if opt else []))
        lines.append(f'    {{"shape":"{kind}", {sig}}}')
        for slot in slots:
            mark = "" if slot.required else "  (необязательно"
            if not slot.required and slot.default:
                mark += f", умолчание {slot.default}"
            if mark:
                mark += ")"
            tail = f" — {slot.bounds}" if slot.bounds else ""
            lines.append(f"      {slot.name:<12} {slot.kind}{tail}{mark}")
    if isinstance(got, dict) and "shape" in got:
        lines.append(f"ПОЛУЧЕНО: shape={got['shape']!r} — такой формы нет")
    lines.append("СЛЕДУЮЩИЙ ХОД: возьми форму из списка выше и перенеси ЕЁ "
                 "поля целиком — они все перечислены здесь, один ход вместо "
                 "одного поля за ход.")
    return "\n".join(lines)

#: The language's upper bound for the DXF bulge. The reverse path reads the
#: public name too: a private copy here used to let the lifter accept an arc
#: that forward would then reject. The value is kept as-is; its origin is
#: still assigned, not a measured Revit limit.
MAX_ARC_BULGE = 1.5
ARC_SAMPLES = 8

#: THE LANGUAGE BOUNDARY between a straight edge and an arc, dimensionless
#: (bulge = 2·sagitta/chord). Below it an arc CANNOT BE EXPRESSED: the
#: forward path rejects the author's bulge (`_validate_shape`), the reverse
#: path does not write an arc (`lift._bulge_from_midpoint`). One question,
#: one answer; before 10.08.2026 the number sat as a bare literal on both
#: sides of the path, and had they drifted apart, they would have given the
#: lifter the right to invent a program the compiler would reject on the
#: spot. ASSIGNED, not measured. There is a measurement nearby, but it is
#: about something else, and it is important not to conflate the two: on
#: 28.07 a comparison of 3051 arcs across two decompiles gave a worst
#: reverse-path residual of 2.4e-8 mm (`lift._ARC_BULGE_TOL_MM`) — that is,
#: the accuracy of the conversion, not the threshold at which an arc counts
#: as an arc.
MIN_ARC_BULGE = 1e-6

#: EMISSION'S SAFETY NET, not a language boundary. It answers the question
#: "draw `Line.CreateBound` or `Arc.Create`" and sits three orders of
#: magnitude below `MIN_ARC_BULGE` DELIBERATELY: the band (1e-9, 1e-6) is
#: unreachable from either side — the forward path rejects it, the reverse
#: path never writes into it — so the net only catches a bulge computed
#: internally (a macro transform, a body of revolution). Setting it at the
#: level of the language boundary would mean dividing by near-zero in
#: `_arc_geometry`. Seven copies of this number across three modules
#: (contour, opening_emit, struct_emit) decided whether Revit would build a
#: LINE or an ARC; since 10.08.2026 there is one copy.
STRAIGHT_BULGE_EPS = 1e-9

#: How many decimal digits `emit_loop_cs`/`emit_curvearray_cs` print. The
#: number used to sit as the literal `round(..., 2)` in six places and was
#: UNFINDABLE: the wave of bodies derives its own boundary error from it,
#: and a derivation from a number that has no name drifts from the original
#: at the first edit (bounds_audit counted exactly 103 "bare literals in a
#: comparison" on 31.07).
_EMIT_DECIMALS = 2

#: THE COORDINATE EMISSION QUANTUM, mm. A full consequence of
#: `_EMIT_DECIMALS`: a point printed with two digits sits no farther than
#: half a quantum from the ideal one, along each axis. The wave of bodies
#: adds it to Revit's `VertexTolerance`, obtaining the FULL boundary error
#: of the built body.
EMIT_COORD_QUANTUM_MM = 10.0 ** (-_EMIT_DECIMALS)


#: `KIR-G105` (`GRID_ANCHOR_UNRESOLVED`) WAS RETIRED FROM USE ON 04.08.2026.
#:
#: It covered three different cases — "no name," "no geometry," "no
#: intersection" — that is, three DIFFERENT FIXES under one code, and
#: therefore it could not name the next move for any of them. Split into
#: `relate.GRID_NOT_FOUND` (G108), `GRID_NO_GEOMETRY` (G111), and
#: `GRID_NO_INTERSECTION` (G110). The name is not reused: a code that meant
#: three things must not be given a fourth.


# ── anchors ──────────────────────────────────────────────────────────────────

def anchor_is_literal(a) -> bool:
    return (isinstance(a, list) and len(a) == 2
            and all(is_finite_number(c) for c in a))


def anchor_is_grid(a) -> bool:
    return relate.is_address(a)


def resolve_anchor(a, grids_pool: list, oid, field: str, diags: list) -> Optional[list]:
    """Literal passes through; `at_grid` resolves through :mod:`relate`.

    ONE GRAMMAR, ONE RESOLVER. Before 04.08 axis-based addressing lived
    HERE and carried three latent defects (a world-frame offset, a silent
    choice on name collisions, unchecked conditioning). Generalizing it to
    every point parameter without fixing it first would have multiplied the
    foundation's defect across twenty-two new parameters — so the fix lives
    in one place, and CONTOUR became its consumer, not a second owner.

    ``allow_world_offset=True`` is a NAMED legacy door exactly for `region`:
    the form ``{"at_grid": [...], "offset_mm": [dx, dy]}`` has been shipping
    since 17.07 and sits in the goldens. In new slots it is closed (see
    `relate`).
    """
    if anchor_is_literal(a):
        # 🔴 THE COORDINATE LIMIT IS THE SAME ONE THE NEIGHBORING POINT
        # KINDS USE (25.08.2026, an audit finding, reproduced by a run).
        #
        # The `region` kind had NO limit AT ALL: for it,
        # `authoring_validation` checks `isinstance(v, dict)` and passes it
        # on with the words "the full laws will run at ground," while in
        # `_validate_shape` the coordinate magnitude was never checked
        # anywhere — not for `origin` (only its SIDES are bounded there),
        # nor for `poly`'s points (only their COUNT is measured there).
        # Measured: a `rect` with an origin of 9e11 mm — nine hundred
        # million meters — was ACCEPTED, and emission printed
        # `Line.CreateBound(P(900000000000.0, ...))`.
        #
        # The very same `create_ceiling` refused statically through `pts`,
        # but sailed through to a late Revit refusal through `contour`. One
        # magnitude, two records, two verdicts — a named defect kind of this
        # tree.
        #
        # THE PLACE WAS CHOSEN HERE because this is the ONLY GATE for every
        # region coordinate: both `origin` and `poly`'s points pass through
        # it. Checking each shape separately would have been a fourth copy
        # of the law.
        x, y = float(a[0]), float(a[1])
        if abs(x) > COORD_LIMIT_MM or abs(y) > COORD_LIMIT_MM:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=field,
                got=[x, y], expected=f"|координата| <= {COORD_LIMIT_MM:.0f} мм",
                message_ru=(
                    f"{field}: координата вне рабочего охвата модели "
                    f"(~16 км от начала координат). Такое число почти всегда "
                    f"ошибка ЕДИНИЦ — метры вместо миллиметров или наоборот. "
                    f"СЛЕДУЮЩИЙ ХОД: проверь единицы; если точка правда так "
                    f"далеко, перенеси начало координат проекта")))
            return None
        return [x, y]
    # THE SECOND FAMILY OF NODES IS NOT ACCEPTED HERE, AND THE REASON IS
    # NAMED (09.08). An address from an element reads not the snapshot but
    # the program's already-grounded ops, and a region is lowered into edges
    # from `validate_region`, which is never handed the program. Saying
    # "unknown point shape" would send the author off to fix syntax instead
    # of explaining the boundary: today the shape is correct, and it is the
    # slot that is not.
    if relate.is_element_address(a):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=a,
            message_ru=(
                f"{field}: адрес от элемента ({{at_element: ...}}) в углу "
                f"контура не принимается — контур опускается в рёбра ДО того, "
                f"как программа заземлена, и числа адресуемого опа здесь ещё "
                f"неизвестны. Годятся [x,y] мм и адрес от осей "
                f"{{at_grid:[имя,имя]}}")))
        return None
    if not isinstance(a, dict) or "at_grid" not in a:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=a,
            message_ru=f"{field}: точка — [x,y] мм или {{at_grid:[имя,имя], offset_mm?}}"))
        return None
    return relate.resolve_address(a, grids_pool, oid, field, diags, dims=2,
                                  allow_world_offset=True)


# ── arc math (ALL at compile time) ───────────────────────────────────────────

def bulge_midpoint(p0, p1, bulge: float) -> list:
    """Point on the arc at mid-sweep — the third point Arc.Create needs."""
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    # DXF bulge is positive for a CCW sweep from p0 to p1.  The midpoint
    # therefore lies on the RIGHT side of the directed chord; the circle
    # centre lies on the left for a positive minor arc.
    ch = math.hypot(dx, dy)
    if ch < 1e-9:
        return [mx, my]
    nx, ny = -dy / ch, dx / ch
    s = bulge * ch / 2.0
    return [mx - nx * s, my - ny * s]


def radius_to_bulge(p0, p1, radius: float, ccw: bool, oid, field: str,
                    diags: list) -> Optional[float]:
    ch = _dist(p0, p1)
    if radius < ch / 2.0 * 1.0005:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field,
            expected=f">={ch / 2.0:.1f}", got=radius,
            message_ru=f"{field}: радиус меньше половины хорды ({ch:.0f}мм) — дуга невозможна"))
        return None
    half = math.asin(min(1.0, ch / (2.0 * radius)))    # minor arc only in v2.0
    b = math.tan(half / 2.0)
    # 🔴 THE RESULT IS CHECKED AGAINST THE SAME BOUNDARY AS THE AUTHOR'S
    # `bulge` (25.08.2026, an audit finding, reproduced by a run).
    #
    # The form `{edge, radius_mm, dir}` bypassed the bounds check entirely:
    # from above `radius_mm` was bounded by nothing (only r>0 and
    # finiteness), and the result was checked against nothing. Measured on a
    # 1000 mm chord:
    #
    #     radius_mm 1.0e+04 -> bulge 2.5e-02   accepted (and correct)
    #     radius_mm 2.5e+09 -> bulge 1.0e-07   ACCEPTED, below MIN_ARC_BULGE
    #     radius_mm 1.0e+18 -> bulge 2.5e-16   ACCEPTED
    #
    # An author who wrote `bulge: 1e-7` BY HAND got a typed refusal. THE
    # SAME arc, named by a radius, sailed through. One magnitude, two
    # records, two verdicts — a named defect kind of this tree.
    #
    # The cost is not in tidiness: at `_EMIT_DECIMALS = 2` the three points
    # of such an "arc" become COLLINEAR, and `Arc.Create` throws an
    # ArgumentException — that is, the refusal comes from Revit and talks
    # about the wrong thing.
    #
    # The refusal taken is THE SAME ONE (`TYPE_BOUNDS`), but it names the
    # RADIUS: the author wrote that, not the bulge, and it is the radius
    # they must fix too.
    if abs(b) < MIN_ARC_BULGE or abs(b) > MAX_ARC_BULGE:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field,
            got=radius, expected=f"{MIN_ARC_BULGE} <= |bulge| <= {MAX_ARC_BULGE}",
            message_ru=(
                f"{field}: радиус {radius:.6g} мм на хорде {ch:.0f} мм даёт "
                f"кривизну {abs(b):.3g} — за пределом выразимой дуги "
                f"({MIN_ARC_BULGE} … {MAX_ARC_BULGE}). При печати координат "
                f"такая дуга становится ПРЯМОЙ, и Revit отказывает уже своей "
                f"ошибкой. СЛЕДУЮЩИЙ ХОД: возьми радиус ближе к хорде либо "
                f"опиши ребро прямым — без `arcs`")))
        return None
    return b if ccw else -b


def _arc_geometry(p0, p1, bulge: float) -> tuple:
    """(centre, radius, start_angle, signed_sweep) for a DXF-bulge arc."""
    sweep = 4.0 * math.atan(bulge)
    ch = _dist(p0, p1)
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    nx, ny = -dy / ch, dx / ch
    centre_offset = ch * (1.0 - bulge * bulge) / (4.0 * bulge)
    cx, cy = mx + nx * centre_offset, my + ny * centre_offset
    radius = ch * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
    start = math.atan2(p0[1] - cy, p0[0] - cx)
    return (cx, cy), radius, start, sweep


def _sample_arc(p0, p1, bulge: float) -> list:
    """8-chord deterministic approximation for intersection/containment laws."""
    if abs(bulge) < STRAIGHT_BULGE_EPS:
        return [list(p0), list(p1)]
    (cx, cy), r, a0, sweep = _arc_geometry(p0, p1, bulge)
    pts = []
    for k in range(ARC_SAMPLES + 1):
        a = a0 + sweep * k / ARC_SAMPLES
        pts.append([cx + r * math.cos(a), cy + r * math.sin(a)])
    pts[0], pts[-1] = list(p0), list(p1)   # exact endpoints
    return pts


def _catmull_rom(pts: list, samples_per_span: int) -> list:
    """A chord sampling of the curve passing THROUGH `pts`, for the STATIC
    laws.

    🔴 THIS IS NOT THE CURVE REVIT WILL BUILD, AND THAT IS SAID HERE BECAUSE
    STAYING SILENT ABOUT IT WOULD BE A LIE. `HermiteSpline` fits tangents by
    its own rule, which Autodesk does not document; Catmull-Rom is our
    deterministic approximation of the SAME kind as "an arc is sampled with
    eight chords" (CONTOUR canon, item 2). It is good for exactly what it
    was built for: rejecting an already-illegal contour BEFORE emission
    (a zero edge, degenerate area, self-intersection).

    WHAT FOLLOWS FROM THIS, AND WHAT MUST NOT BE DONE: this sampling MUST
    NOT be used to witness what was actually built. A witness must read the
    curve from the BUILT element and measure the distance to the declared
    points — otherwise we would be checking our own approximation against
    itself, that is, a check that cannot fail (shape 8).

    The approximation is CONSERVATIVE in exactly one direction and not the
    other: the real curve can go outside our polyline, so "no
    self-intersection by the sampling" does NOT prove its absence in the
    built curve. Nor is it required to: the last word belongs to Revit,
    which will refuse on its own, and its refusal now reaches the receipt.
    """
    n = len(pts)
    if n < 2:
        return [list(p) for p in pts]
    # Virtual ends — by reflection, so the outer spans have a tangent
    ext = [[2 * pts[0][0] - pts[1][0], 2 * pts[0][1] - pts[1][1]]] \
        + [list(p) for p in pts] \
        + [[2 * pts[-1][0] - pts[-2][0], 2 * pts[-1][1] - pts[-2][1]]]
    out = []
    for k in range(n - 1):
        p_1, p0_, p1_, p2 = ext[k], ext[k + 1], ext[k + 2], ext[k + 3]
        for s in range(samples_per_span):
            t = s / samples_per_span
            t2, t3 = t * t, t * t * t
            out.append([
                0.5 * ((2 * p0_[i]) + (-p_1[i] + p1_[i]) * t
                       + (2 * p_1[i] - 5 * p0_[i] + 4 * p1_[i] - p2[i]) * t2
                       + (-p_1[i] + 3 * p0_[i] - 3 * p1_[i] + p2[i]) * t3)
                for i in (0, 1)])
    out.append(list(pts[-1]))
    out[0] = list(pts[0])                     # exact ends, as with an arc
    return out


def sample_spline(p0, p1, sp: "Spline") -> list:
    """The polyline of a spline edge for the laws: the edge's ends plus the
    declared points."""
    return _catmull_rom([list(p0), *[list(v) for v in spline_via(sp)], list(p1)],
                        SPLINE_SAMPLES_PER_VIA)


def sample_edge(p0, p1, b) -> list:
    """ONE edge -> a polyline, regardless of kind. One question, one place."""
    return sample_spline(p0, p1, b) if is_spline(b) else _sample_arc(p0, p1, b)


def edges_to_sample_poly(edges: list) -> list:
    """Flatten (with arc/spline sampling) to a plain polygon for the geom laws."""
    poly = []
    for p0, p1, b in edges:
        seg = sample_edge(p0, p1, b)
        poly.extend(seg[:-1])
    return poly


def edges_are_straight(edges: list) -> bool:
    """All the ring's edges are straight segments, not a single arc.

    Straightness is decided by the SAME threshold emission uses to decide
    it (``STRAIGHT_BULGE_EPS``): it is exactly what determines whether
    Revit builds a LINE or an ARC. Setting up a second threshold here would
    mean splitting apart two numbers that must agree — they were already
    reduced from seven copies to one on 10.08.2026.
    """
    return all(not is_spline(bulge) and abs(bulge) < STRAIGHT_BULGE_EPS
               for _p0, _p1, bulge in edges)


def edges_vertices(edges: list) -> list:
    """The ring's vertices — one per edge, WITHOUT sampling arcs.

    Called as the shape witness, and therefore takes exactly what
    ``Curve.GetEndPoint(0)`` will return on the built sketch: the start of
    each edge. ``edges_to_sample_poly`` next to it does SOMETHING ELSE — it
    breaks an arc into segments for the v1.1 geometric laws — and swapping
    one for the other would mean comparing the sampling against the
    original.
    """
    return [list(p0) for p0, _p1, _bulge in edges]


def edges_bbox(edges: list) -> tuple:
    """The axis-aligned bounding box: EXACT for a line and an arc, an
    ESTIMATE for a spline.

    🔴 THE BOUNDARY IS NAMED HERE BECAUSE IT DECIDES WHO IS ALLOWED TO USE
    THIS NUMBER. For a line the envelope is its ends; for an arc the
    cardinal extrema are added to them, and that is exact. A spline has no
    exact envelope: Revit chooses the shape between the points, and we only
    know our own chord sampling, and the real curve can go outside it. So
    for a spline the result is a LOWER-BOUND estimate.

    THAT IS WHY THE ENVELOPE WITNESS IS ILLEGAL ON A SPLINE, and this is
    not a footnote: an understated envelope paints the "built lies inside
    declared" check GREEN exactly where the curve went outside. An op whose
    witness relies on the envelope must call :func:`region_has_spline` and
    refuse — which is exactly what the guard in `ground.py` does. Here we
    hand over the best we can and say what it costs; silently returning the
    chord would be twice as bad.
    """
    points = extreme_candidates(edges, ((1.0, 0.0), (0.0, 1.0)))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def extreme_candidates(edges: list, directions) -> list:
    """Contour points among which the extrema for every direction in
    `directions` are GUARANTEED to lie — a finite set, not a sample.

    🔴 WHY A GENERALIZATION, NOT A SECOND COPY OF THE ARC LAW (21.08.2026).
    The sketch plane made the envelope three-dimensional: for a profile laid
    on a tilted plane, the world coordinate X is a·u + b·v — a LINEAR
    function with arbitrary coefficients, neither "u" nor "v". Computing its
    extremum by sampling would put back into the envelope witness the very
    approximation it cannot tolerate; writing a second arc analysis would
    set up a second carrier of the law, and it would silently drift from
    the first.

    THE DERIVATION. The extremum of the linear function f(u,v) = a·u + b·v
    on an EDGE:

      * line          — at an end, because f is linear along the segment;
      * arc           — at an end OR wherever f's derivative with respect
                        to the parameter vanishes. A point on the arc is
                        c + r·(cos t, sin t), so f = f(c) + r·(a·cos t +
                        b·sin t), and df/dt = r·(−a·sin t + b·cos t) = 0
                        when tan t = b/a, that is at t = atan2(b, a) and
                        t + π. Both angles are taken if they fall WITHIN
                        the arc's sweep — exactly the same technique as
                        `_sector_bbox` in solid_emit;
      * spline        — there is NO exact answer, and this is named in
                        `edges_bbox` above: Revit chooses the shape between
                        the points. What is returned here is the same
                        chord sampling, that is, a LOWER-BOUND estimate, and
                        the envelope witness MUST NOT use it.

    WHY `edges_bbox` IS NOW DERIVED FROM THIS. The directions (1,0) and
    (0,1) give atan2 = {0, π} and {π/2, 3π/2} — together EXACTLY the four
    cardinal angles the previous edition enumerated. The result is
    identical down to the bit (min and max pick the same float out of a
    superset of candidates), and the carrier of the arc law is now a SINGLE
    one.
    """
    points: list = []
    tau = 2.0 * math.pi
    angles_of_interest = []
    for a, b in directions:
        base = math.atan2(b, a)
        angles_of_interest.append(base % tau)
        angles_of_interest.append((base + math.pi) % tau)
    for p0, p1, bulge in edges:
        points.extend((p0, p1))
        if is_spline(bulge):
            points.extend(sample_spline(p0, p1, bulge))
            continue
        if abs(bulge) < STRAIGHT_BULGE_EPS:
            continue
        (cx, cy), radius, start, sweep = _arc_geometry(p0, p1, bulge)
        for angle in angles_of_interest:
            travelled = ((angle - start) % tau if sweep > 0
                         else (start - angle) % tau)
            if travelled <= abs(sweep) + 1e-12:
                points.append([cx + radius * math.cos(angle),
                               cy + radius * math.sin(angle)])
    return points


# ── shapes → canonical edges ─────────────────────────────────────────────────

def _rect_edges(origin, w, h, rot_deg: float) -> list:
    ca, sa = math.cos(math.radians(rot_deg)), math.sin(math.radians(rot_deg))
    def T(x, y):
        return [origin[0] + x * ca - y * sa, origin[1] + x * sa + y * ca]
    c = [T(0, 0), T(w, 0), T(w, h), T(0, h)]
    return [(c[k], c[(k + 1) % 4], 0.0) for k in range(4)]


_L_CORNERS = ("ne", "nw", "se", "sw")


def _l_edges(origin, W, H, cw, ch_, corner: str) -> list:
    ox, oy = origin
    if corner == "ne":
        pts = [[0, 0], [W, 0], [W, H - ch_], [W - cw, H - ch_], [W - cw, H], [0, H]]
    elif corner == "nw":
        pts = [[0, 0], [W, 0], [W, H], [cw, H], [cw, H - ch_], [0, H - ch_]]
    elif corner == "se":
        pts = [[0, 0], [W - cw, 0], [W - cw, ch_], [W, ch_], [W, H], [0, H]]
    else:  # sw
        pts = [[0, ch_], [cw, ch_], [cw, 0], [W, 0], [W, H], [0, H]]
    pts = [[ox + p[0], oy + p[1]] for p in pts]
    return [(pts[k], pts[(k + 1) % 6], 0.0) for k in range(6)]


def _shoelace(poly) -> float:
    n = len(poly)
    return abs(sum(poly[k][0] * poly[(k + 1) % n][1]
                   - poly[(k + 1) % n][0] * poly[k][1] for k in range(n))) / 2.0


def _shape_edges(shape: Any, grids_pool, oid, field: str, diags: list) -> Optional[list]:
    """One shape -> canonical closed edge list, all static laws enforced.

    🔴 DO NOT CALL DIRECTLY. The only legal entry point is
    :func:`_validate_shape` below: that is exactly the place where the
    DERIVED points born here meet the coordinate limit. The body was split
    precisely for the sake of this one seam (04.09.2026, the argument is in
    the docstring of :func:`_reject_out_of_reach`).
    """
    if not isinstance(shape, dict) or shape.get("shape") not in SHAPE_FORMS:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=shape,
            candidates=sorted(SHAPE_FORMS),
            message_ru=shape_forms_text(field, got=shape)))
        return None
    kind = shape["shape"]
    if kind in ("rect", "l"):
        origin = resolve_anchor(shape.get("origin"), grids_pool, oid,
                                f"{field}.origin", diags)
        if origin is None:
            return None
        size = shape.get("size_mm")
        if not anchor_is_literal(size) \
                or size[0] < SHAPE_SIDE_MIN_MM or size[1] < SHAPE_SIDE_MIN_MM \
                or size[0] > SHAPE_SIDE_MAX_MM or size[1] > SHAPE_SIDE_MAX_MM:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.size_mm", got=size,
                message_ru=(f"{field}: size_mm — [w,h] в "
                            f"{SHAPE_SIDE_MIN_MM:.0f}..{SHAPE_SIDE_MAX_MM:.0f}")))
            return None
        if kind == "rect":
            rot = shape.get("rotation_deg", 0)
            if not is_finite_number(rot) or not (
                    -SHAPE_ROTATION_ABS_MAX_DEG <= rot <= SHAPE_ROTATION_ABS_MAX_DEG):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.rotation_deg",
                    got=rot,
                    message_ru=(f"{field}: rotation_deg — число "
                                f"-{SHAPE_ROTATION_ABS_MAX_DEG:.0f}.."
                                f"{SHAPE_ROTATION_ABS_MAX_DEG:.0f}")))
                return None
            extra = set(shape) - shape_fields("rect")
        else:
            cut = shape.get("cut_mm")
            corner = shape.get("corner", "ne")
            if not anchor_is_literal(cut) \
                    or not (SHAPE_SIDE_MIN_MM <= cut[0] <= size[0] - SHAPE_SIDE_MIN_MM) \
                    or not (SHAPE_SIDE_MIN_MM <= cut[1] <= size[1] - SHAPE_SIDE_MIN_MM):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.cut_mm", got=cut,
                    message_ru=(f"{field}: cut_mm — [cw,ch], каждый в "
                                f"{SHAPE_SIDE_MIN_MM:.0f}..(size−"
                                f"{SHAPE_SIDE_MIN_MM:.0f}) "
                                f"(вырез не съедает профиль — Г-форма by construction)")))
                return None
            if corner not in _L_CORNERS:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.corner",
                    got=corner, candidates=list(_L_CORNERS),
                    message_ru=f"{field}: corner — ne|nw|se|sw"))
                return None
            extra = set(shape) - shape_fields("l")
        if extra:
            # THE REFUSAL SHOWS THE WHOLE SHAPE, rather than stating
            # "unknown" fields. The previous text cost an agent three
            # attempts in a row on 16.08.
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=field,
                got=sorted(extra), candidates=sorted(shape_fields(kind)),
                message_ru=f"{field}: неизвестные поля формы {sorted(extra)}.\n"
                           + shape_forms_text(field)))
            return None
        if kind == "rect":
            return _rect_edges(origin, float(size[0]), float(size[1]),
                               float(shape.get("rotation_deg", 0)))
        return _l_edges(origin, float(size[0]), float(size[1]),
                        float(shape["cut_mm"][0]), float(shape["cut_mm"][1]),
                        shape.get("corner", "ne"))
    # poly
    extra = set(shape) - shape_fields("poly")
    if extra:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=sorted(extra),
            candidates=sorted(shape_fields("poly")),
            message_ru=f"{field}: неизвестные поля формы {sorted(extra)}.\n"
                       + shape_forms_text(field)))
        return None
    raw_pts = shape.get("points_mm")
    # The same profile law that `pts`-direct and the lifter use (declared in
    # geom). CONTOUR wrote its own copy on 17.07 ("v2 invention") — a third
    # answer to one question; since 10.08 there is one answer.
    # 🔴 THE UPPER BOUND IS COMPUTED WITH AN ALLOWANCE FOR THE CLOSING POINT.
    #
    # Measured 20.08.2026, the plan-algebra wave. The length was checked
    # BEFORE closure normalization (twenty lines below), and every
    # planar-geometry library — shapely included — hands back a ring WITH
    # THE FIRST POINT REPEATED. So a legal `MAX_RING_POINTS` of DISTINCT
    # points arrived as the (MAX+1)th and was rejected, even though it would
    # have been legal after normalization. Checked from both sides: 64
    # without a closing point — ok, 64 with a closing point — refused, 63
    # with a closing point — ok. That is, shapely's effective output budget
    # was 63, while the declared one was 64, and they silently drifted apart.
    #
    # The allowance is exactly ONE point and only at the top: at the bottom
    # `MIN_RING_POINTS` stays strict, and the real length check sits after
    # normalization ("fewer than 3 points after normalization") and has not
    # gone anywhere.
    # The lower bound is RELAXED to `MIN_RING_POINTS_ARCED`, and this is not
    # a loosening of the rule but a refinement of it: a ring made of two
    # ARCS is closed. The real check sits below, AFTER `arcs` parsing —
    # before that, nothing is known about whether these are arcs or
    # segments.
    if not isinstance(raw_pts, list) or not (
            MIN_RING_POINTS_ARCED <= len(raw_pts) <= MAX_RING_POINTS + 1):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.points_mm",
            got=raw_pts,
            message_ru=(f"{field}: points_mm — {MIN_RING_POINTS}.."
                        f"{MAX_RING_POINTS} точек, либо ровно "
                        f"{MIN_RING_POINTS_ARCED}, если ОБА ребра кривые "
                        f"(так Revit отдаёт окружность двумя полудугами). "
                        f"Замыкающая точка, повторяющая первую, не считается")))
        return None
    # 🔴 EVERY INVALID POINT IS NAMED, NOT JUST THE FIRST (26.08.2026).
    #
    # There used to be a `return None` inside the loop here: `resolve_anchor`
    # laid down its own diagnostic, and parsing broke off at the FIRST
    # invalid point. The rest were never even asked about.
    #
    # THE COST, REPRODUCED BY A RUN. A ring of four points, all four beyond
    # the reach limit (`points_mm` = [[1e9,1e9], …]) — the compiler named
    # `points_mm[0]` and said nothing about the other three. The author
    # fixes one, gets a refusal on the next, and so on for FOUR ROUNDS
    # instead of one. This is exactly the law the `create_wall` refusal
    # already honors word for word: "close the missing ones in ONE turn, not
    # one at a time."
    #
    # THE LIST IS CAPPED, AND THAT IS NOT CAUTION BUT THE SECOND HALF OF THE
    # SAME FIX. A ring legally carries up to `MAX_RING_POINTS` points; on a
    # UNITS error (and the message itself says that is almost always what it
    # is) ALL of them are invalid AT ONCE, and lifting the limit would trade
    # a silent loss for a refusal carrying sixty-four diagnostics. We show
    # the first `_BAD_POINTS_SHOWN` and NAME THE REMAINDER AS A COUNT — the
    # same idiom as the candidate pool in `ground.py`. Its own number, not
    # an imported one: its subject there is different (catalog candidates),
    # and a shared constant would tie together two unrelated laws.
    pts = []
    bad_points = 0
    for pi, a in enumerate(raw_pts):
        where = f"{field}.points_mm[{pi}]"
        if bad_points >= _BAD_POINTS_SHOWN:
            # We keep counting invalid ones further on, but stop laying
            # down diagnostics: the remainder count must be COMPLETE, or the
            # note attached to it would lie.
            if resolve_anchor(a, grids_pool, oid, where, []) is None:
                bad_points += 1
            continue
        r = resolve_anchor(a, grids_pool, oid, where, diags)
        if r is None:
            bad_points += 1
            continue
        pts.append(r)
    if bad_points:
        if bad_points > _BAD_POINTS_SHOWN:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid,
                field_name=f"{field}.points_mm", got=bad_points,
                message_ru=(
                    f"{field}: негодных точек {bad_points}, названы первые "
                    f"{_BAD_POINTS_SHOWN}. Столько разом — почти всегда ОДНА "
                    f"общая причина (единицы или начало координат): чини её, "
                    f"а не точки по одной")))
        return None
    # The ring PLUS the repeated first point — the same rule as in
    # geom.ring_normalize, and it must be the same number.
    if len(pts) >= MIN_RING_POINTS + 1 and _dist(pts[0], pts[-1]) < _EDGE_TOL:
        pts = pts[:-1]                       # closure normalization (v1.1 law)
    n = len(pts)
    if n < MIN_RING_POINTS_ARCED:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field,
            message_ru=(f"{field}: после нормализации {n} точ. — кольцом не "
                        f"замкнуть ничем: {MIN_RING_POINTS} для ломаной, "
                        f"{MIN_RING_POINTS_ARCED} только если ОБА ребра дуги")))
        return None
    # 🔴 THE REAL UPPER BOUND IS HERE, next to the lower one, and for the
    # same reason: what must be counted is DISTINCT points, not input
    # records. The check above (MAX+1) is only the allowance for the closing
    # point; without this line, 65 DISTINCT points would pass, and the
    # allowance would turn into a silent widening of the limit. Caught by
    # its own control right after the allowance fix.
    if n > MAX_RING_POINTS:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.points_mm",
            got=n,
            message_ru=(f"{field}: после нормализации {n} точек при пределе "
                        f"{MAX_RING_POINTS}. СЛЕДУЮЩИЙ ХОД: упростить кольцо "
                        f"(shapely: simplify с растущим допуском, join_style="
                        f"mitre, quad_segs поменьше) либо разбить на части")))
        return None
    bulges = [0.0] * n
    arcs = shape.get("arcs", [])
    if not isinstance(arcs, list) or len(arcs) > n:
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.arcs",
                                message_ru=f"{field}: arcs — список по рёбрам"))
        return None
    seen_arc_edges = set()
    for ai, arc in enumerate(arcs):
        if not isinstance(arc, dict) or isinstance(arc.get("edge"), bool) \
                or not isinstance(arc.get("edge"), int) \
                or not (0 <= arc["edge"] < n):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.arcs[{ai}]",
                got=arc, message_ru=f"{field}: arc — {{edge: 0..{n - 1}, bulge|radius_mm}}"))
            return None
        e = arc["edge"]
        if e in seen_arc_edges:
            diags.append(Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=oid,
                field_name=f"{field}.arcs[{ai}].edge", got=e,
                message_ru=f"{field}: ребро {e} описано дугой более одного раза"))
            return None
        seen_arc_edges.add(e)
        has_bulge, has_radius = "bulge" in arc, "radius_mm" in arc
        allowed = ({"edge", "bulge"} if has_bulge and not has_radius else
                   {"edge", "radius_mm", "dir"} if has_radius and not has_bulge else set())
        if not allowed or set(arc) - allowed:
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.arcs[{ai}]",
                got=arc, message_ru=(f"{field}: arc требует ровно одно из bulge/radius_mm; "
                                     "dir допустим только с radius_mm")))
            return None
        if has_bulge:
            b = arc["bulge"]
            if (not is_finite_number(b) or not (abs(b) <= MAX_ARC_BULGE)
                    or abs(b) < MIN_ARC_BULGE):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.arcs[{ai}].bulge",
                    got=b, expected=f"0<|b|<={MAX_ARC_BULGE}",
                    message_ru=f"{field}: bulge вне диапазона"))
                return None
            bulges[e] = float(b)
        else:
            r = arc["radius_mm"]
            direction = arc.get("dir", "ccw")
            if (not is_finite_number(r) or r <= 0
                    or direction not in ("ccw", "cw")):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=oid,
                    field_name=f"{field}.arcs[{ai}].radius_mm", got=r,
                    message_ru=f"{field}: radius_mm — конечное положительное число; dir=ccw|cw"))
                return None
            b = radius_to_bulge(pts[e], pts[(e + 1) % n], float(r),
                                direction == "ccw",
                                oid, f"{field}.arcs[{ai}]", diags)
            if b is None:
                return None
            bulges[e] = b
    # ── SPLINES: the same technique as arcs, and THE SAME laws of edge ownership ──
    splines = shape.get("splines", [])
    if not isinstance(splines, list) or len(splines) > n:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.splines",
            message_ru=f"{field}: splines — список по рёбрам"))
        return None
    # 🔴 EVERY INVALID POINT OF THE CURVES IS NAMED, NOT JUST THE FIRST
    # (26.08.2026).
    #
    # A TWIN OF THE SAME DEFECT FIXED FOR THE RING (`030895dd`), and it was
    # named in that very commit as still open: "the same break-off sits at
    # SPLINE points — `return None` right after the diagnostic." Here it is
    # WIDER than for the ring: the break-off carried away not only the rest
    # of THIS curve's points but every SUBSEQUENT spline too — parsing never
    # even reached them.
    #
    # MEASURED ON HEAD BEFORE THE FIX, `create_filled_region`, a 4×2.5 m
    # square:
    #     1 spline × 4 invalid points  -> 4 submitted, 1 named
    #     3 splines × 5 invalid = 15   -> 15 submitted, 1 named
    # The author fixes one point, gets a refusal on the next, and every time
    # thinks it is the last one. This is the same law the `create_wall`
    # refusal already honors word for word: "close the missing ones in ONE
    # turn, not one at a time."
    #
    # THE COUNTER IS SHARED ACROSS ALL SPLINES OF THE SHAPE, not separate
    # per curve: the author fixes the whole program at once, and five curves
    # with twelve named each would give sixty diagnostics — exactly the cost
    # the limit exists to prevent.
    #
    # STRUCTURAL CURVE REFUSALS (a foreign field, an edge already taken, the
    # wrong `via_mm` kind, a point count out of bounds, a zero span) remain
    # STOPPING ones — they are about the curve itself, not about a point, and
    # there is nothing further to parse. But they now exit via `break`, not
    # `return`: otherwise the note about the remainder already accumulated by
    # earlier curves would be lost, and the named count would lie to whoever
    # is fixing it.
    seen_spline_edges = set()
    bad_via = 0
    spline_refused = False
    for si, sp in enumerate(splines):
        if not isinstance(sp, dict) or isinstance(sp.get("edge"), bool) \
                or not isinstance(sp.get("edge"), int) \
                or not (0 <= sp["edge"] < n) or set(sp) - {"edge", "via_mm"}:
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.splines[{si}]",
                got=sp,
                message_ru=f"{field}: spline — {{edge: 0..{n - 1}, via_mm: [[x,y],…]}}"))
            spline_refused = True
            break
        e = sp["edge"]
        # ONE EDGE — ONE KIND. An arc and a spline on the same edge do not
        # "combine": they describe the SAME curve differently, and a silent
        # choice between them would be exactly the outcome the language
        # forbids.
        if e in seen_spline_edges or e in seen_arc_edges:
            diags.append(Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=oid,
                field_name=f"{field}.splines[{si}].edge", got=e,
                message_ru=(f"{field}: ребро {e} уже описано кривой — "
                            "у ребра ровно один род")))
            spline_refused = True
            break
        seen_spline_edges.add(e)
        via = sp.get("via_mm")
        if not isinstance(via, list):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_id=oid, field_name=f"{field}.splines[{si}].via_mm",
                got=via, message_ru=f"{field}: via_mm — список точек [[x,y],…]"))
            spline_refused = True
            break
        # TWO DIFFERENT OUTCOMES — TWO DIFFERENT TEXTS. Merged, they would
        # advise the reader exactly the opposite thing: from below, ADD a
        # point; from above, SPLIT the edge. One text for two troubles is
        # exactly the named defect of this tree.
        if len(via) < SPLINE_VIA_MIN:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.splines[{si}].via_mm",
                got=len(via), expected=f">= {SPLINE_VIA_MIN}",
                message_ru=(f"{field}: сплайну нужна хотя бы одна промежуточная "
                            "точка — без них он неотличим от прямой")))
            spline_refused = True
            break
        if len(via) > SPLINE_VIA_MAX:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}.splines[{si}].via_mm",
                got=len(via), expected=f"<= {SPLINE_VIA_MAX}",
                message_ru=(f"{field}: в одном ребре не больше {SPLINE_VIA_MAX} точек — "
                            "длинную кривую выражают НЕСКОЛЬКИМИ рёбрами, у каждого "
                            "свои концы и свой свидетель")))
            spline_refused = True
            break
        pts_via = []
        via_bad_here = False
        for vi, v in enumerate(via):
            where = f"{field}.splines[{si}].via_mm[{vi}]"
            if (not isinstance(v, list) or len(v) != 2
                    or not all(is_finite_number(c) for c in v)):
                via_bad_here = True
                bad_via += 1
                # We keep counting invalid ones past the limit too, just
                # without diagnostics: the remainder count must be
                # COMPLETE, or the note attached to it would lie.
                if bad_via <= _BAD_POINTS_SHOWN:
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_id=oid,
                        field_name=where, got=v,
                        message_ru=f"{field}: точка кривой — [x, y] в мм"))
                continue
            # 🔴 THE SAME LIMIT AS `resolve_anchor` USES — AND FOR THE SAME
            # REASON (25.08.2026, found by a control AFTER the
            # origin/points_mm fix).
            #
            # `via_mm` is a world coordinate (folded into `chain` alongside
            # `pts`, which has already passed `resolve_anchor`), but it
            # bypassed that same limit: only the number's finiteness was
            # checked here. Measured: `via_mm=[1500, -17_000_000]` (beyond
            # the ±16_000_000 mm limit) on the edge of an ordinary 3×3 m
            # square — was ACCEPTED silently, with not a single diagnostic,
            # because the curve goes OUTSIDE the ring and does not intersect
            # other edges, and self-intersection is the only law that could
            # have caught it by accident (and it does not always catch it
            # either: had the point been closer to the limit, or the
            # polygon not a convex square, there would have been nothing to
            # catch it with either).
            #
            # No second carrier of the limit is set up: it is the same name,
            # `COORD_LIMIT_MM` from `registry_base`, into which
            # `resolve_anchor`, `curveops`, `mesh`, `geom`, and `relate` have
            # already been consolidated.
            if abs(v[0]) > COORD_LIMIT_MM or abs(v[1]) > COORD_LIMIT_MM:
                via_bad_here = True
                bad_via += 1
                if bad_via <= _BAD_POINTS_SHOWN:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_id=oid,
                        field_name=where,
                        got=[float(v[0]), float(v[1])],
                        expected=f"|координата| <= {COORD_LIMIT_MM:.0f} мм",
                        message_ru=(
                            f"{field}: точка кривой вне рабочего охвата модели "
                            f"(~16 км от начала координат). Такое число почти "
                            f"всегда ошибка ЕДИНИЦ — метры вместо миллиметров "
                            f"или наоборот. СЛЕДУЮЩИЙ ХОД: проверь единицы; "
                            f"если точка правда так далеко, перенеси начало "
                            f"координат проекта")))
                continue
            pts_via.append([float(v[0]), float(v[1])])
        # A curve with an invalid point is not built: there is nothing to
        # compute `chain` from, and a partial `pts_via` would give a
        # DIFFERENT curve and would lie to the witness. We move on to the
        # NEXT curve — its points will reach the author in the same turn.
        if via_bad_here:
            continue
        # A degenerate curve: two consecutive coincident points (edge ends
        # included) give Revit a zero span, that is, ShortCurveTolerance at
        # execution. Caught statically by the SAME threshold that catches a
        # zero edge.
        chain = [pts[e], *pts_via, pts[(e + 1) % n]]
        for ci in range(len(chain) - 1):
            if _dist(chain[ci], chain[ci + 1]) < _EDGE_TOL:
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_id=oid,
                    field_name=f"{field}.splines[{si}].via_mm",
                    message_ru=(f"{field}: нулевой пролёт кривой на ребре {e} "
                                f"(точки {ci} и {ci + 1} ближе {_EDGE_TOL:.0f} мм)")))
                spline_refused = True
                break
        if spline_refused:
            break
        bulges[e] = Spline(pts_via)
    if bad_via > _BAD_POINTS_SHOWN:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid,
            field_name=f"{field}.splines", got=bad_via,
            message_ru=(
                f"{field}: негодных точек кривых {bad_via}, названы первые "
                f"{_BAD_POINTS_SHOWN}. Столько разом — почти всегда ОДНА общая "
                f"причина (единицы или начало координат): чини её, а не точки "
                f"по одной")))
    if bad_via or spline_refused:
        return None
    edges = [(pts[k], pts[(k + 1) % n], bulges[k]) for k in range(n)]
    # 🔴 TWO POINTS ARE LEGAL ONLY WITH BOTH EDGES CURVED, AND THIS CAN ONLY
    # BE CHECKED HERE: before `arcs`/`splines` parsing, nothing is known
    # about the edges' kind. Two half-arcs close off a region (a circle), a
    # segment with a segment gives a degenerate strip, and an arc with a
    # segment gives an unclosed crescent.
    if n < MIN_RING_POINTS:
        straight = [k for k in range(n)
                    if not isinstance(bulges[k], Spline) and not bulges[k]]
        if straight:
            # 🔴 A SHAPE, NOT JUST A CODE+ADDRESS (25.08.2026, the mission
            # instrument `tools/mission/refusal_actionability.py`). `got=n`
            # and one line of text — the instrument reads `expected` or a
            # separate multi-line carrier (see the docstring of its
            # `оценить()`); bare prose, however detailed, does not count as
            # a field. `expected` is named the same way as in
            # `resolve_anchor`/`reject_segment_length`: number to number,
            # not the name of a kind.
            diags.append(Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
                got=n, expected=(f">= {MIN_RING_POINTS} точек (или "
                                 f"{MIN_RING_POINTS_ARCED}, если оба ребра "
                                 f"— дуга либо сплайн)"),
                message_ru=(
                    f"{field}: кольцо из {n} точ. допустимо, только если ОБА "
                    f"ребра кривые (дуга или сплайн) — так Revit отдаёт "
                    f"окружность двумя полудугами. Прямых рёбер: "
                    f"{len(straight)} (номера {straight}). СЛЕДУЮЩИЙ ХОД: "
                    f"либо задать дугу/сплайн на этих рёбрах, либо описать "
                    f"кольцо {MIN_RING_POINTS} точками и более")))
            return None
    # static laws on the sampled polygon (v1.1 geom, lifted to arcs)
    for k in range(n):
        if _dist(pts[k], pts[(k + 1) % n]) < _EDGE_TOL:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=field,
                message_ru=f"{field}: нулевое ребро {k} (ShortCurveTolerance статически)"))
            return None
    sampled = edges_to_sample_poly(edges)
    if _shoelace(sampled) < MIN_RING_AREA_MM2:
        from kir.geom import degenerate_ring_ru
        diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid, field_name=field,
                                message_ru=degenerate_ring_ru(field)))
        return None
    # 🔴 THE ALL-PAIRS SCAN LIVED HERE AND WAS THE HOT PATH, NOT AT THE
    # NEIGHBOR'S (02.09.2026). The ring here is SAMPLED: arcs and splines
    # are already broken into segments, so `m` is higher than the author's
    # point count — making the square-law cost worse. Measured on a regular
    # polygon, minimum of five runs:
    #
    #     points        64      128      256      512     1024
    #     all-pairs   2.71 ms  10.76    44.52   177.83   710.16
    #     sweep       0.094     0.183    0.358    0.778    1.421
    #     speedup     28.9x    58.8x   124.2x   228.7x   499.8x
    #     per doubling         x1.95    x1.96    x2.17    x1.83
    #
    # There is ONE carrier and it lives in `geom` — a second copy of the
    # same law used to sit here, and a second copy would have silently
    # fallen behind the first. The bounding-box sweep is EXACT (boxes don't
    # intersect => segments don't intersect), the boxes are widened by the
    # same `eps` that `_seg_intersect` uses to count a touch, and the pair
    # order is preserved — the verdict matches the all-pairs scan byte for
    # byte, which is proven on 2811 rings, 2612 of them self-intersecting.
    if _first_self_intersection(sampled) is not None:
        diags.append(Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
            message_ru=f"{field}: самопересечение контура (с учётом дуг и сплайнов)"))
        return None
    return edges


def _reject_out_of_reach(edges: list, oid, field: str, diags: list) -> bool:
    """A DERIVED contour point meets the SAME limit as a written one.

    🔴 WHY (04.09.2026, audit finding FC-15, reproduced by a run).

    `resolve_anchor` checked EVERY coordinate the author WROTE, and its own
    docstring records the argument: it is "the ONLY GATE for every region
    coordinate." The argument was correct only halfway: for `rect` and `l`
    most of the vertices are not written by the author but COMPUTED —
    `origin + size`, `origin + W − cw`, and so on. The gate never saw them,
    because they did not yet exist there.

    MEASURED BEFORE THE FIX (`_validate_shape`, limit 16,000,000 mm):

        rect origin=[16,000,000, 0] size=[1000, 1000] -> ACCEPTED, diags 0,
             vertex x = [16,000,000.0, 16,001,000.0]
        l    origin=[16,000,000, 0] size=[4000, 4000]  -> ACCEPTED, diags 0,
             max vertex x = 16,004,000.0
        CONTROL origin=[0, 0], same size                -> accepted, vertices in bounds

    That is, checked input produced an UNCHECKED magnitude — the same kind
    that already cost the tree `radius_to_bulge` (25.08): an author who
    wrote a vertex by hand got a typed refusal; THE SAME vertex, named as
    origin plus a side, sailed through to a late Revit refusal.

    THE PLACE WAS CHOSEN HERE, AND THIS IS NOT A FOURTH COPY OF THE LAW. The
    number is still one (`registry_base.COORD_LIMIT_MM`), it has two readers
    in this file, and they ask DIFFERENT things: `resolve_anchor` asks about
    what was WRITTEN (and can name the exact point the author must fix),
    while this one asks about what was COMPUTED, where there simply is no
    named point in the input. Putting the check separately in `rect`, in
    `l`, and in `poly` would set up three carriers of one law; putting it in
    `_rect_edges`/`_l_edges` would hand the diagnostic to functions that have
    neither `diags` nor `field`. There is one seam: `_validate_shape` is the
    only entry point, and the edge list of every shape is born exactly there.

    WHAT IS ACTUALLY MEASURED. `edges_bbox` — that is, not only the
    vertices but also the cardinal extrema of ARCS (for `poly` the vertices
    have already passed `resolve_anchor`, and an arc between two legal
    vertices can bulge outward on its own). This is EXACT for a line and an
    arc. For a spline it is a LOWER-BOUND estimate, and the caveat is not
    hidden: see the docstring of `edges_bbox` — Revit chooses the curve's
    shape between the points, and a spline that strays past the limit
    between declared points is not caught here. It is caught at the
    `via_mm` points themselves (the check sits in `splines` parsing) and,
    ultimately, by Revit. This creates no silently-wrong outcome: the
    estimate is understated, so a refusal from this check is always true,
    and only the un-found stays un-found.
    """
    if not edges:
        return True
    min_x, min_y, max_x, max_y = edges_bbox(edges)
    worst = max((min_x, min_y, max_x, max_y), key=abs)
    if abs(worst) <= COORD_LIMIT_MM:
        return True
    diags.append(Diagnostic(
        code=TYPE_BOUNDS, op_id=oid, field_name=field,
        got=worst, expected=f"|координата| <= {COORD_LIMIT_MM:.0f} мм",
        message_ru=(
            f"{field}: сама форма законна, но её вершины уезжают за рабочий "
            f"охват модели (~16 км от начала координат): дальняя координата "
            f"{worst:.0f} мм при пределе {COORD_LIMIT_MM:.0f}. Это НЕ та точка, "
            f"которую вы написали, — она вычислена из начала и сторон формы "
            f"(габарит контура x {min_x:.0f}..{max_x:.0f}, y {min_y:.0f}.."
            f"{max_y:.0f}). СЛЕДУЮЩИЙ ХОД: сдвинуть начало формы на "
            f"{abs(worst) - COORD_LIMIT_MM:.0f} мм внутрь либо уменьшить "
            f"сторону на столько же; если форма правда так далеко, перенеси "
            f"начало координат проекта")))
    return False


def _validate_shape(shape: Any, grids_pool, oid, field: str, diags: list) -> Optional[list]:
    """One shape -> canonical closed edge list, all static laws enforced.

    THE ONLY SEAM WHERE ALL EDGES OF ANY SHAPE ARE BORN — and therefore the
    only place where derived vertices meet the coordinate limit (see
    :func:`_reject_out_of_reach`). The analysis lives in
    :func:`_shape_edges`.
    """
    edges = _shape_edges(shape, grids_pool, oid, field, diags)
    if edges is None:
        return None
    if not _reject_out_of_reach(edges, oid, field, diags):
        return None
    return edges


def validate_region(region: Any, grids_pool, oid, field: str, diags: list) -> Optional[dict]:
    """{"outer": shape, "holes": [shape...]} -> {"outer": edges, "holes": [edges]}."""
    if not isinstance(region, dict) or "outer" not in region \
            or set(region) - {"outer", "holes"}:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=region,
            message_ru=f"{field}: {REGION_FORM_RU}"))
        return None
    outer = _validate_shape(region["outer"], grids_pool, oid, f"{field}.outer", diags)
    if outer is None:
        return None
    holes_raw = region.get("holes", [])
    if not isinstance(holes_raw, list) or len(holes_raw) > MAX_HOLES:
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, op_id=oid,
                                field_name=f"{field}.holes",
                                message_ru=f"{field}: holes — до {MAX_HOLES} форм"))
        return None
    holes = []
    for hi, h in enumerate(holes_raw):
        he = _validate_shape(h, grids_pool, oid, f"{field}.holes[{hi}]", diags)
        if he is None:
            return None
        holes.append(he)
    # Containment/disjointness on sampled polygons (v1.1 law, arc-aware).
    # Reuse the shared inclusive edge law so plus-shaped overlaps, collinear
    # contact, and a hole edge crossing a concave outline cannot pass merely
    # because none of their vertices lies inside the other polygon.
    outer_poly = edges_to_sample_poly(outer)
    hole_polys = [edges_to_sample_poly(h) for h in holes]
    if not check_holes_relation(outer_poly, hole_polys, oid, diags,
                                field_prefix=f"{field}.holes"):
        return None
    return {"outer": outer, "holes": holes}


# ── MEASURES OF THE CANONICAL CONTOUR (closed shapes, everything at compile time) ──────────
#
# WHY HERE, NOT AT THE BODY WAVE. The arc arithmetic in this package lives
# in exactly one place — `_arc_geometry` above — and `edges_bbox` already
# shows the pattern: a measure of the canonical edge list is a property of
# CONTOUR, not of whoever consumes it. A second home for the same
# trigonometry would mean two answers to one question on the very day one
# of them gets fixed.
#
# Every measure is a BOUNDARY INTEGRAL (Green's theorem), not a sum over a
# sample: a sample would inject its own error into the witness, which would
# then have to be folded into the tolerance — and folding one's own
# sloppiness into the tolerance is exactly the "instrument covering only
# part of the range" that has already cost this tree a defect.
#
# CROSS-CHECK (measured 09.08, tests/test_solid.py::ClosedFormsAgreeWithSampling):
# all four measures on eight shapes (clockwise traversal and two arcs of
# opposite sign included) are checked against a polygonal sampling of 4000
# chords per arc. The worst relative discrepancy is 3.15e-8 against the
# sampling's OWN error of O(1/N²) = 6.25e-8 — that is, the closed form is
# more accurate than the instrument used to check it, and the observed
# discrepancy is fully explained by the instrument.


class SplineWitnessShape(Exception):
    """A spline cannot be expressed by the "start-middle-end" witness
    shape.

    A type separate from :class:`SplineMeasureUnavailable` DELIBERATELY:
    the measure and the witness are different questions with different
    remedies (the first is opened by a live measurement of length and area,
    the second by reading the built sketch), and one code for two outcomes
    is a named defect of this tree.
    """


class SplineMeasureUnavailable(Exception):
    """A spline edge has NO closed form for area, moment, and length.

    🔴 THIS IS A REFUSAL, NOT A GAP, AND IT IS OF THE SAME KIND AS THE FIVE
    REFUSED BODY FACTORIES (`ops_solid`, "a factory ships only with an
    honest witness"). For a line and an arc, area, moment, and length are
    computed exactly; for a curve whose shape between the points Revit
    ITSELF chooses by an undocumented rule, they are not. Computing them
    from our chord sampling would mean injecting our own error into the
    witness and folding it into the tolerance: the check would pass, but
    the number would be ours, not the building's.

    WHAT WOULD OPEN THIS REFUSAL is named here so the next person does not
    have to search: a live measurement of `Curve.Length` and the area of
    the built sketch against our sampling, on a dozen real curves. If it
    converges within a derived tolerance, the measure can honestly be
    computed from the sampling. If it does not converge, the refusal is
    confirmed by a number and closed for good.
    """


def edge_measures(p0, p1, bulge: float) -> tuple:
    """Measures of ONE canonical edge: (area, moment, length, ∫x·ds).

    * ``area``   — the edge's contribution to ``(1/2)∮(x dy − y dx)``, SIGNED
      (by traversal direction);
    * ``moment`` — its contribution to ``∮ (x²/2) dy = ∬ x dA``, signed the
      same way;
    * ``length`` — the edge's length (for an arc, r·|sweep|), always >= 0;
    * ``x_ds``   — ``∫ x ds`` along the edge; for a body-of-revolution
      profile this is exactly Pappus's second theorem (lateral surface =
      θ·∫x ds).

    A spline edge REFUSES — see :class:`SplineMeasureUnavailable`.
    """
    if is_spline(bulge):
        raise SplineMeasureUnavailable(
            "сплайн-ребро: площадь, момент и длина не выводятся замкнутой формой")
    if abs(bulge) < STRAIGHT_BULGE_EPS:
        ax, ay = p0
        bx, by = p1
        length = math.hypot(bx - ax, by - ay)
        return (0.5 * (ax * by - ay * bx),
                # ∫(x²/2)dy over a segment: x is linear in t, dy is constant ⇒
                # (By−Ay)/2 · ∫₀¹(Ax + t·dx)² dt = (By−Ay)(Ax²+AxBx+Bx²)/6.
                (by - ay) * (ax * ax + ax * bx + bx * bx) / 6.0,
                length,
                length * (ax + bx) / 2.0)
    (cx, cy), r, a0, sweep = _arc_geometry(p0, p1, bulge)
    a1 = a0 + sweep
    s0, s1, c0, c1 = math.sin(a0), math.sin(a1), math.cos(a0), math.cos(a1)
    # x = cx + r·cos a, y = cy + r·sin a ⇒ x dy − y dx = (cx·r·cos a +
    # cy·r·sin a + r²) da.
    area = 0.5 * (r * cx * (s1 - s0) - r * cy * (c1 - c0) + r * r * sweep)
    # ∫(x²/2)dy = (1/2)∫(cx + r cos a)²·r cos a da, expanded via three
    # antiderivatives: ∫cos = sin, ∫cos² = a/2 + sin2a/4, ∫cos³ = sin − sin³/3.
    i_cos = s1 - s0
    i_cos2 = (a1 / 2.0 + math.sin(2.0 * a1) / 4.0) - (a0 / 2.0 + math.sin(2.0 * a0) / 4.0)
    i_cos3 = (s1 - s1 ** 3 / 3.0) - (s0 - s0 ** 3 / 3.0)
    moment = 0.5 * (r * cx * cx * i_cos + 2.0 * cx * r * r * i_cos2 + r ** 3 * i_cos3)
    # ds = r·|da| — by ARC LENGTH, so the bounds are ordered: the direction
    # of traversal must not make the length negative.
    alo, ahi = (a0, a1) if a1 >= a0 else (a1, a0)
    x_ds = r * (cx * (ahi - alo) + r * (math.sin(ahi) - math.sin(alo)))
    return area, moment, r * abs(sweep), x_ds


def loop_measures(edges: list) -> tuple:
    """Sums of :func:`edge_measures` over a closed ring."""
    area = moment = length = x_ds = 0.0
    for p0, p1, bulge in edges:
        a, m, l, x = edge_measures(p0, p1, bulge)
        area += a
        moment += m
        length += l
        x_ds += x
    return area, moment, length, x_ds


def region_measures(region: dict) -> dict:
    """Measures of a region {outer, holes} — area, moment, perimeter, ∫x·ds.

    The ring is normalized BY THE SIGN OF ITS OWN AREA, not by the declared
    point order: CONTOUR accepts both orientations (`poly_cw` in the
    cross-check is exactly this case), and the sign of the area is the only
    fact about the traversal direction we have. Holes are subtracted; their
    strict interiority and pairwise disjointness have already been proven
    by `check_holes_relation`, so the subtraction is exact, not
    approximate.

    ``perimeter_mm`` is the FULL boundary length (outer ring + every hole):
    it is this, not the length of a single ring, that gives a prism's
    lateral surface.

    ``min_area_mm2`` is the area of the smallest DECLARED element of the
    profile (the profile itself, or its smallest hole). This is not
    decoration: a witness whose tolerance is no smaller than this magnitude
    would not notice this element vanishing, and emission must refuse on
    such a case, not sign off on it.
    """
    a_out, m_out, l_out, x_out = loop_measures(region["outer"])
    sign = 1.0 if a_out >= 0.0 else -1.0
    area = abs(a_out)
    moment = m_out * sign
    perimeter = l_out
    x_ds = x_out
    hole_areas = []
    hole_moments = []
    for hole in region.get("holes", ()):
        a_h, m_h, l_h, x_h = loop_measures(hole)
        s_h = 1.0 if a_h >= 0.0 else -1.0
        area -= abs(a_h)
        moment -= m_h * s_h
        perimeter += l_h
        x_ds += x_h
        hole_areas.append(abs(a_h))
        hole_moments.append(abs(m_h))
    return {
        "area_mm2": area,
        "moment_x_mm3": moment,
        "perimeter_mm": perimeter,
        "x_ds_mm2": x_ds,
        "hole_areas_mm2": hole_areas,
        "min_area_mm2": min([area] + hole_areas),
        # The moment of the smallest declared part plays the same role as
        # `min_area_mm2`, but for a body of revolution: there, the part's
        # volume is θ·(its moment), and taking "area × envelope radius" in
        # place of the moment would be an OVERESTIMATE, that is, an inflated
        # vacuity threshold, that is, a missed witness that cannot fail.
        "min_moment_x_mm3": min([abs(moment)] + hole_moments),
    }


def region_bbox(region: dict) -> tuple:
    """A region's envelope = the envelope of the OUTER ring (holes lie
    strictly inside it)."""
    return edges_bbox(region["outer"])


def region_has_arc(region: dict) -> bool:
    """Whether the region contains even one arc (decides the area
    witness's fate).

    A spline is DELIBERATELY not included here, and this is not an
    oversight: for an arc the measure is computed exactly, for a spline it
    is not computed at all. Two different outcomes under one question would
    be one code for two troubles. To ask about a spline, use
    :func:`region_has_spline`.
    """
    loops = [region["outer"], *region.get("holes", ())]
    return any(not is_spline(b) and abs(b) > STRAIGHT_BULGE_EPS
               for edges in loops for _p0, _p1, b in edges)


def region_has_spline(region: dict) -> bool:
    """Whether the region contains a spline — that is, a curve WITHOUT a
    derivable measure.

    An op whose witness relies on area, moment, or the "start-middle-end"
    triple must ask this BEFORE emission and refuse by name. Otherwise it
    would sign off on geometry it never checked: the triple degenerates
    into a chord for a spline, and the chord is the same for a line and for
    any curve between the same ends.
    """
    loops = [region["outer"], *region.get("holes", ())]
    return any(is_spline(b) for edges in loops for _p0, _p1, b in edges)


# ── emit helper (THE template Sonnet waves clone for new sketch-ops) ─────────

def _model_pt_cs(x: float, y: float, z: str = "0") -> str:
    """A point in MODEL space: the XY plane plus an elevation.

    Digits — `_EMIT_DECIMALS` (merged 09.08): the body wave derived
    `EMIT_COORD_QUANTUM_MM` from this same constant, which its witness uses
    to compute the boundary error, while the detailing wave set up this
    formatter against its own base, where the name did not yet exist. A
    bare `2` here would mean that one wave's output rests on a number that
    no longer exists at the point of printing.
    """
    return f"P({round(x, _EMIT_DECIMALS)}, {round(y, _EMIT_DECIMALS)}, {z})"


def _edge_curve_cs(p0, p1, b: float, z: str = "0", pt=None) -> str:
    """ONE edge of a canonical shape -> ONE Revit curve expression.

    The three assemblers below (CurveLoop / CurveArray / List<Curve>) differ
    by exactly the container and nothing else: their points must be the
    very same ones. As long as the edge's body sat rewritten in each one,
    "the very same" was held together by authorial discipline — and two out
    of three discrepancies would have been invisible (the envelope witness
    computes from the Python edges, so it would agree with any of the
    copies). The bytes of both former functions are preserved: at z="0" the
    string matches character for character.

    MERGED 09.08: the number of digits is taken from `_EMIT_DECIMALS`
    rather than a literal, and both hands were MERGED rather than one being
    picked. This refactor collapsed the edge's body into one place; the
    body wave, the same day, GAVE THE NUMBER A NAME and derived
    `EMIT_COORD_QUANTUM_MM` from it, which its witness uses to compute the
    boundary error of the built body. Leaving a bare `2` here would mean
    the wave's output rests on a constant that no longer exists at the
    single point of printing — and they would have drifted apart SILENTLY,
    because C# compiles the same either way.

    ``pt`` (09.08.2026) — the POINT FORMATTER, ``(x, y) -> a C# expression``.
    Not set up for symmetry: for a filled region the contour does not lie
    in the model's XY plane but in the VIEW'S PLANE, and Revit rejects a
    loop that is not parallel to the view's own sketch plane
    (RevitAPI.xml, ``FilledRegion.Create``). That is, a third assembler
    with a different ``z`` would not be enough here — the whole coordinate
    system changes, not just the elevation. The ARC ARITHMETIC still
    remains compile-time exactly as before (CONTOUR canon, item 1): three
    points per arc still go out, just expressed through the view's basis.
    The default is the previous model-space form, so every existing call
    stays byte for byte the same.
    """
    fmt = pt if pt is not None else (lambda x, y: _model_pt_cs(x, y, z))
    if is_spline(b):
        # INTERPOLATION through the declared points — see the "SPLINE: THE
        # THIRD EDGE KIND" block. The points are printed with the same
        # formatter and the same quantum as a line and an arc: the three
        # kinds must lie in one coordinate system, or a filled region (the
        # VIEW's plane) and a floor (the model's plane) would silently
        # drift apart. `false` means non-periodic: closure is held by the
        # RING, not by an individual edge, and a periodic spline inside a
        # ring would be a second carrier of the same law.
        pts_cs = ", ".join(
            fmt(x, y) for x, y in ((p0[0], p0[1]), *spline_via(b), (p1[0], p1[1])))
        return (f"HermiteSpline.Create("
                f"new System.Collections.Generic.List<XYZ> {{ {pts_cs} }}, false)")
    if abs(b) < STRAIGHT_BULGE_EPS:
        return (f"Line.CreateBound("
                f"{fmt(p0[0], p0[1])}, "
                f"{fmt(p1[0], p1[1])})")
    m = bulge_midpoint(p0, p1, b)
    return (f"Arc.Create("
            f"{fmt(p0[0], p0[1])}, "
            f"{fmt(p1[0], p1[1])}, "
            f"{fmt(m[0], m[1])})")


def emit_loop_cs(edges: list, var: str, indent: str = "", pt=None) -> str:
    """CurveLoop assembly from canonical edges: Line for bulge==0,
    Arc.Create(start, end, mid-on-arc) otherwise — all points precomputed.

    ``pt`` is the same point formatter as in :func:`_edge_curve_cs`;
    without it the loop is assembled in the model's XY plane, as before."""
    out = [f"{indent}CurveLoop {var} = new CurveLoop();"]
    for p0, p1, b in edges:
        out.append(f"{indent}{var}.Append({_edge_curve_cs(p0, p1, b, pt=pt)});")
    return "\n".join(out)


def edge_witness_triples(edges: list) -> list:
    """Every edge as ``(p0, mid, p1)`` — the shape the witness COMPARES.

    Why a triple, not just a pair of ends: the ends are the same for a line
    and for any arc between them, meaning a witness working from the ends
    could not tell a built arc from a built chord apart — and the arc's
    sagitta would remain unproven. The middle is computed by the SAME
    :func:`bulge_midpoint` that emits the arc (at ``bulge == 0`` it
    degenerates exactly into the chord's midpoint), and on the other side
    it is answered by ``Curve.Evaluate(0.5, true)`` — the parametric
    midpoint of both a line and a circular arc. Both sides of the
    comparison must be computed by one law; here that law is "ends plus
    midpoint."

    🔴 A SPLINE DOES NOT FIT THIS SHAPE, AND THEREFORE REFUSES RATHER THAN
    APPROXIMATING. The argument is exactly the one the triple was set up
    for. For a spline, "the middle" from our sampling is OUR number, while
    Revit's `Curve.Evaluate(0.5)` has its own parameterization; comparing
    them would give a discrepancy that means nothing, and tuning a
    tolerance to match it would give a check that cannot fail. A spline has
    a different witness, sitting right next to this one:
    :func:`spline_witness_points`.
    """
    for _p0, _p1, b in edges:
        if is_spline(b):
            raise SplineWitnessShape(
                "сплайн-ребро не выражается тройкой «начало-середина-конец»: "
                "у него свой свидетель — точки на построенной кривой")
    return [(list(p0), bulge_midpoint(p0, p1, b), list(p1))
            for p0, p1, b in edges]


def spline_witness_points(edges: list) -> list:
    """A spline witness: ``(edge index, [declared points])``.

    WHAT THIS PROVES, AND WHY IT CAN FAIL. The author declared that the
    curve passes THROUGH these points. On the other side stands
    `Curve.Distance(XYZ)` against the curve READ FROM THE BUILT SKETCH —
    not from our variable, not from our sampling. Revit is free to simplify
    the curve, drop a point, replace it with a segment; every such outcome
    widens the distance and turns the witness red. This is exactly what
    distinguishes the check from a setter confirmation.

    The edge's ends are NOT included here: the ring's general closure law
    already holds them, and a second check of the same thing would be a
    second carrier of one claim.
    """
    return [(k, [list(v) for v in spline_via(b)])
            for k, (_p0, _p1, b) in enumerate(edges) if is_spline(b)]


def emit_curvearray_cs(edges: list, var: str, indent: str = "",
                       z: str = "0") -> str:
    """2021 legacy path (CurveArray for NewFloor) — same canon, same points.

    ``z`` is a C# EXPRESSION for the sketch plane's elevation IN
    MILLIMETERS, not a number. Needed by CurveArray's second consumer, an
    opening (``NewOpening(Element, CurveArray, bool)``), whose profile must
    lie ON THE HOST'S PLANE: the elevation comes from the host itself, read
    live, and a zero would be a silent lie (a 17th-floor slab does not sit
    there, and the profile simply would not intersect it).

    THE UNITS ARE NAMED HERE ON PURPOSE, AND THIS IS A TRACE OF THE MERGE
    ON 09.08.2026. Two branches arrived at this helper with DIFFERENT
    conventions: the framing branch put in ``MM(__lv.Elevation)``
    (millimeters, later routed through ``P()``), while the opening branch
    put in ``(__hbb.Min.Z + __hbb.Max.Z) / 2.0`` (internal feet, bypassing
    ``U()``). Each was correct on its own side, and both would become
    incorrect here: ``P`` would run feet through ``U()`` a second time and
    place the profile at a height on the order of the elevation multiplied
    by 304.8. The defect would be INVISIBLE offline — C# compiles the same
    either way — and would only surface on a live model, on a floor above
    the ground one. That is why there is ONE convention here, and it is
    millimeters, as throughout the language; the caller does the
    conversion (``MM(...)`` on the opening's side).

    ``z="0"`` is the previous path, BYTE FOR BYTE: the 2021 branch used by
    ``create_floor_by_contour``, the only consumer before this day.
    """
    out = [f"{indent}CurveArray {var} = new CurveArray();"]
    for p0, p1, b in edges:
        out.append(f"{indent}{var}.Append({_edge_curve_cs(p0, p1, b, z)});")
    return "\n".join(out)


def emit_curve_list_cs(edges: list, var: str, z: str = "0",
                       indent: str = "") -> str:
    """``IList<Curve>`` from the same canonical edges — the third
    container.

    Not set up for symmetry: ``BeamSystem.Create`` accepts the profile
    SPECIFICALLY as ``IList<Curve>`` (measured by compilation on 09.08
    across all six versions; ``CurveLoop`` does not convert there — CS0266
    6/6, and neither does ``IList<Curve> x = bs.Profile``), so the two
    previous assemblers cannot cover this case.

    ``z`` is a C# EXPRESSION, not a number, and this too is not decoration:
    a beam system's profile must lie in the plane of its level, and the
    level's elevation is only known at runtime (``MM(__lv.Elevation)``).
    The same signature as ``authoring._loop_pts(pts, name, z="0")``, and
    the same default — existing calls stay byte for byte the same.
    """
    out = [f"{indent}IList<Curve> {var} = new List<Curve>();"]
    for p0, p1, b in edges:
        out.append(f"{indent}{var}.Add({_edge_curve_cs(p0, p1, b, z)});")
    return "\n".join(out)


def edges_vertex_bbox(edges: list) -> tuple:
    """An envelope from VERTICES ONLY — deliberately weaker than
    :func:`edges_bbox`.

    Needed where the witness reads the profile BACK FROM REVIT in a warped
    way: ``BeamSystem.Profile`` hands back curves for which, in C# without
    tessellation, only the ends are available (``GetEndPoint(0/1)``), that
    is, vertices. Checking the read-back vertices against
    :func:`edges_bbox`, which adds the cardinal extrema of arcs, would mean
    accusing a correctly built system of an error equal to exactly the
    arc's sagitta — the very same false refusal by which `create_beam` used
    to flip correct beams around the reference level. Both sides of the
    comparison must be computed by one law; here that law is vertices.
    """
    xs = [p[0] for edge in edges for p in (edge[0], edge[1])]
    ys = [p[1] for edge in edges for p in (edge[0], edge[1])]
    return min(xs), min(ys), max(xs), max(ys)

# ─────────────────────── BRIDGE FROM PLANAR GEOMETRY INTO THE LANGUAGE'S REGION

def region(plan: Any, holes: Any = None) -> dict:
    """A planar shape -> the language's `region`: what floor, ceiling, and
    site-plate take.

        from shapely.geometry import Polygon          # already in the sandbox
        plate = Polygon(outer).difference(Polygon(shaft))
        create_floor_by_contour(contour=region(plate), level=lvl)

    WHY. The author HAS planar booleans (shapely is live in the sandbox),
    but there was NOWHERE to put their result: `region` is a dict with a
    `poly` shape and a point list, and the author used to rewrite the
    coordinates by hand, losing the holes along the way. A mesh did not
    close that hole either: `extrude` gives GEOMETRY WITHOUT BIM MEANING,
    while a floor must remain a floor — with a type, a thickness, and a row
    in the schedule.

    ACCEPTS: a shapely Polygon; a point list [[x,y], ...]; a dict
    {"outer": ..., "holes": [...]}; an already-built language shape — in
    which case it is returned as-is, so the call is idempotent.

    DOES NOT: does not simplify the contour and does not cut it down to the
    limit. A ring longer than `MAX_RING_POINTS` is a NAMED refusal with the
    point count and advice, not a silent thinning: a point dropped on the
    author's behalf changes the building and is indistinguishable from
    success from the outside.
    """
    if isinstance(plan, dict) and "outer" in plan and holes is None:
        return plan                                   # already the language's region
    outer_src, holes_src = plan, list(holes or ())
    if hasattr(plan, "geom_type"):
        if plan.geom_type == "MultiPolygon":
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=None, field_name="contour",
                message_ru=(
                    f"фигура распалась на {len(plan.geoms)} несвязных куска — "
                    f"так возвращает булева операция, когда разность разрезала "
                    f"план. Область языка описывает ОДНУ фигуру: выдай по "
                    f"операции на кусок (`for piece in plan.geoms:`)"),
                got=len(plan.geoms))])
        if plan.geom_type != "Polygon":
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE, op_id=None, field_name="contour",
                message_ru=(f"область строится из Polygon, а пришёл "
                            f"{plan.geom_type}"), got=plan.geom_type)])
        outer_src = list(plan.exterior.coords)[:-1]
        holes_src = [list(r.coords)[:-1] for r in plan.interiors]

    def ring(points: Any, what: str) -> dict:
        pts: list = []
        for i, pt in enumerate(points or ()):
            try:
                x, y = float(pt[0]), float(pt[1])
            except Exception:
                raise KirRefusal([Diagnostic(
                    code=TYPE_BAD_TYPE, op_id=None, field_name=what,
                    message_ru=f"{what}: точка — [x, y] из двух чисел в мм",
                    got=pt)])
            pts.append([x, y])
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts = pts[:-1]
        if not (MIN_RING_POINTS <= len(pts) <= MAX_RING_POINTS):
            raise KirRefusal([Diagnostic(
                code=TYPE_BOUNDS, op_id=None, field_name=what,
                message_ru=(
                    f"{what}: {len(pts)} точек, а форма poly берёт "
                    f"{MIN_RING_POINTS}..{MAX_RING_POINTS}. Предел НЕ обходится "
                    f"прореживанием за тебя: огрубляй сам и печатай, на сколько "
                    f"мм огрубил, либо строй тело мешем через extrude()"),
                got=len(pts))])
        return {"shape": "poly", "points_mm": pts}

    if len(holes_src) > MAX_HOLES:
        raise KirRefusal([Diagnostic(
            code=TYPE_BOUNDS, op_id=None, field_name="contour.holes",
            message_ru=(f"дыр {len(holes_src)}, предел {MAX_HOLES}"),
            got=len(holes_src))])
    out: dict = {"outer": ring(outer_src, "contour.outer")}
    if holes_src:
        out["holes"] = [ring(h, f"contour.holes[{i}]")
                        for i, h in enumerate(holes_src)]
    return out
