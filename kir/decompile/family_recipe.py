"""FAMILY AS A PROGRAM — capturing the recipe, not the snapshot.

HOW THIS MODULE DIFFERS FROM THE REST OF THE DECOMPILE, AND WHY IT IS
SEPARATE. All other parsing captures INSTANCES: where something stands,
what shape it is, what bounds it. Here what is captured is the
DEFINITION — the thing an instance is made from. The difference is not
academic: 364 definitions that the decompiled building depends on
(`MNVNK_ATR_PD_B14_K6_AR_R2022`, 20.08.2026) are captured as ZERO, and as
long as they are missing, `dependency_resolved` is false for ALL 33,944
elements, and the fidelity scale is locked to `approximate` BY
CONSTRUCTION.

🔴 SNAPSHOT AND RECIPE ARE TWO DIFFERENT CLAIMS, AND CONFUSING THEM HERE
COSTS MORE THAN ANYTHING ELSE.

    snapshot  `GetOriginalGeometry` on the instance — the type's shape
              BEFORE cuts. Exact solids, faces, edges. Does NOT say what
              it was modeled with.
    recipe    `EditFamily` + `GenericForm` — extrusion, sweep, revolve,
              blend. Says WHAT WITH, but by itself does not prove WHAT
              came out.

The value is in CROSS-CHECKING THEM. If a program assembled from the
recipe yields the same geometry as captured directly, the family is
PROVEN, not just copied. That is why `predicted_volume_mm3` below is
computed from the recipe and compared against `measured_volume_mm3`,
captured by Revit from the same shape: this is the one place in the
module that can FAIL, and everything else is written for its sake.

THE VOCABULARY MATCHED, AND THAT IS A MEASUREMENT, NOT LUCK. A live run
on 20.08 over 110 model families of the same building: 109 opened in
41.4 s, 82 contain forms, 283 forms, and all four kinds are our
operations.

    Extrusion   198  ->  create_solid_extrusion
    Sweep        75  ->  create_solid_sweep
    Blend         6  ->  create_solid_blend
    Revolution    4  ->  create_solid_revolve

🔴 BUT VOCABULARY IS NOT CAPABILITY. Our four operations are PLANAR: the
profile lies in XY, extrusion runs along +Z, the revolve axis is
vertical. A family's shape is built on an ARBITRARY sketch plane. A
matching kind does not yet mean the shape can be stated, and the module
must distinguish these two claims — otherwise it would report "captured"
in a case where it rotated someone else's geometry into a plane and built
the wrong thing.

API MEMBERS ARE TAKEN FROM THE `data/api_surface/` INDEX, NOT FROM
MEMORY. Verified 6/6 across 2021-2026; two seemingly obvious names DO NOT
EXIST and are not called here:

    Extrusion    Sketch · StartOffset · EndOffset                    6/6
    Blend        BottomProfile · TopProfile · BottomSketch ·
                 TopSketch · BottomOffset · TopOffset                6/6
                 🔴 StartOffset / EndOffset — ON NONE OF THEM
    Revolution   Sketch · Axis · StartAngle · EndAngle               6/6
    Sweep        PathSketch · ProfileSketch · ProfileSymbol ·
                 Path3d · MaxSegmentAngle                            6/6
                 🔴 GetSweepProfile / GetSweepPath — ON NONE OF THEM
    GenericForm  IsSolid · Name · Subcategory · Visible              6/6

The rules for reading and building an id are the same as in
`family_tools.py`, and for the same reason: `.IntegerValue` disappeared in
2026, `.Value` appeared in 2024, so it is read as
`long.Parse(x.Id.ToString())`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from kir import contour as _contour


FAMILY_RECIPE_SCHEMA_VERSION = "kir-decompile-family-recipe/1"

#: WHERE THE KNOWLEDGE CAME FROM (OR DID NOT). A closed dictionary of FOUR
#: values, and the fourth is the most expensive.
#:
#: 🔴 THREE STATES ARE NOT ENOUGH, FOUR ARE NEEDED, AND THE DIFFERENCE WAS
#: BOUGHT BY THIS SAME FILE. A field ABSENT from the payload altogether and
#: a field that was asked for and came back empty are different answers:
#: the first is about US, the second is about the FAMILY. Merging them into
#: one value would mean declaring an old snapshot a poor family. This exact
#: shape of defect already cost the module two separate flags
#: (`drives_read`, `params_read`), introduced after "zero of an uncomputed
#: value" was read as zero.
#:
#:   not_asked  the key is absent from the payload — the snapshot was taken
#:              BEFORE we learned to ask
#:   api        asked, and got a value back
#:   absent     asked, Revit honestly answered "this isn't here"
#:   refused    asked, the call threw; the reason sits next to it in the
#:              `*_reason` field
KNOWLEDGE_NOT_ASKED = "not_asked"
KNOWLEDGE_SOURCES = (KNOWLEDGE_NOT_ASKED, "api", "absent", "refused")


def _source(raw: Any, key: str, at: str) -> str:
    """The `*_source` value from the payload, CHECKED against the
    dictionary.

    A typo in the knowledge source is quiet and toxic: `"apy"` would be
    read as "unknown" while looking like "asked". That is why this raises
    a refusal rather than falling back to a default.
    """
    if key not in raw:
        return KNOWLEDGE_NOT_ASKED
    value = str(raw.get(key) or "")
    if value not in KNOWLEDGE_SOURCES:
        raise FamilyRecipeError(
            f"{at}.{key}: источник знания {value!r} не из "
            f"{KNOWLEDGE_SOURCES}")
    return value

#: The tolerance for "the plane is horizontal": the cosine of the angle
#: between the normal and the Z axis. 1e-6 in magnitude is ~0.08°, meaning a
#: plane tilted by a tenth of a degree is ALREADY not considered planar.
#: Strict on purpose: a tilted profile laid into XY gives the wrong shape,
#: not an approximation of it.
PLANE_NORMAL_TOL = 1e-6

#: The tolerance for "the revolve's start angle IS world zero", in DEGREES.
#: Taken from the READER, not eyeballed: the C# lays down the angle as
#: `Math.Round(__rv.StartAngle * 180.0 / Math.PI, 6)`, meaning a true zero
#: arrives here as an exact zero, and the sixth digit is the entire noise
#: the reader is capable of introducing.
_REVOLVE_ANGLE_TOL_DEG = 1e-6

#: The tolerance for cross-checking predicted volume against measured
#: volume, as a FRACTION.
#: ⚠️ ASSIGNED, not measured, and flagged just as honestly as the mesh
#: limits. The reasoning: each side is computed by different arithmetic
#: (ours by the ring, Revit's by the solid), and agreement to the sixth
#: digit would be luck, not a law. The first live run must MEASURE the real
#: spread and move the number to match.
VOLUME_MATCH_TOL = 1e-3


# 🔴 HEIGHT BOUNDS ARE TAKEN FROM THE OPERATION, NOT WRITTEN HERE AS A
# NUMBER.
#
# 21.08.2026: the `ops_solid.MIN_EXTENT_MM` threshold was lowered from 100
# to 1 mm by a live measurement (Revit builds extrusions as thin as 1 mm,
# all 55 rejected shapes lay below 100). Recipe capture DID NOT MOVE FOR A
# SINGLE SHAPE as a result: this file held its own copy of the number —
# `100.0 <= height <= 500_000.0` — twice over.
#
# In other words, the same piece of knowledge lived in two places, and
# editing one did not turn the other red — a named defect of this project.
# The copy is removed: now the capturer asks the one thing that declares
# this limit.
from kir.ops_solid import (  # noqa: E402
    MAX_EXTENT_MM as _MAX_EXTENT_MM,
    MIN_EXTENT_MM as _MIN_EXTENT_MM,
)


class FormKind(str, Enum):
    """The shape kinds Revit puts into a family. A closed list."""

    EXTRUSION = "Extrusion"
    SWEEP = "Sweep"
    BLEND = "Blend"
    REVOLUTION = "Revolution"
    SWEPT_BLEND = "SweptBlend"


#: Shape kind -> registry operation. An empty cell would mean "the op
#: exists, but this kind does not map to it", and there are none of those
#: here; a missing key means "there is NO operation".
FORM_KIND_TO_OP: dict[FormKind, str] = {
    FormKind.EXTRUSION: "create_solid_extrusion",
    FormKind.SWEEP: "create_solid_sweep",
    FormKind.BLEND: "create_solid_blend",
    FormKind.REVOLUTION: "create_solid_revolve",
}


class RecipeRefusal(str, Enum):
    """WHY a shape could not be stated as an operation. A closed
    dictionary.

    Each reason calls for a DIFFERENT fix, which is why they are not merged
    into one "unsupported": some are fixed by a new operation field, others
    by a new op, and others are not fixed at all and remain a named
    boundary.
    """

    #: The shape is a VOID (`IsSolid == false`), and there is nothing to
    #: express it as an operand with.
    #:
    #: ⛔ RETIRED ON 21.08.2026 BY THE FOURTH-PART-KIND WAVE, AND KEPT HERE
    #: AS A NAME, NOT AS LIVE CODE — for exactly the same reason as
    #: `sketch_plane_not_horizontal` below: 64 refusals under this code were
    #: recorded by the 21.08 measurement (64 of 283 shapes, the largest
    #: capture blocker), and a code that silently disappeared would make the
    #: reader think the measurement was lost.
    #:
    #: What used to be true: "our boolean's operands are box/sphere/
    #: cylinder, and an arbitrary profile cannot be expressed with them."
    #: `ops_boolean.PART_SHAPES` gained a fourth kind, `prism` — a prism
    #: over a contour with EXPLICIT points — and a void-extrusion is now
    #: raised as a PART (`FormLift.part`), not a refusal.
    VOID_FORM = "void_form_not_expressible"
    #: The void is a prism by kind, but `ops_boolean.validate_parts`
    #: REJECTED it for a reason unrelated to the contour (height,
    #: elevation, plane origin). A separate code from
    #: `contour_limit_exceeded` because the fix is different.
    VOID_PART_REJECTED = "void_part_rejected_by_validator"
    #: A void exists but is not a prism: sweep, blend, and revolve are not
    #: "contour plus height", and `ops_boolean` knows no such parts. Fixed
    #: by a FIFTH PART KIND, not a field; the 21.08 measurement: 5 of 64
    #: such voids (Blend 2, Revolution 2, Sweep 1).
    VOID_KIND_NOT_A_PRISM = "void_form_is_not_a_prism"
    #: The sketch plane is not horizontal.
    #:
    #: ⛔ RETIRED ON 21.08.2026 BY THE PLANE WAVE, AND KEPT HERE AS A NAME,
    #: NOT AS LIVE CODE. `create_solid_extrusion` and `create_solid_blend`
    #: gained the `plane` kind, and a tilted plane stopped being a limit of
    #: the language. The line is deliberately not deleted: 73 refusals under
    #: this code are recorded in the canon (`CLAUDE.md`, 20.08 measurement)
    #: and in memory, and a code that silently disappeared would make the
    #: reader think the measurement was lost.
    PLANE_NOT_HORIZONTAL = "sketch_plane_not_horizontal"
    #: THE PROFILE FRAME FOR SWEEP AND REVOLVE IS NOT THE SKETCH PLANE.
    #:
    #: 🔴 THIS REPLACES A FALSE REFUSAL, IT IS NOT A NEW LIMIT. Before
    #: 21.08 the capturer asked for horizontality on ALL four kinds, while
    #: for two of them the sketch is never horizontal BY CONSTRUCTION: a
    #: sweep's profile is perpendicular to the path, a revolve's profile
    #: lies in a plane CONTAINING the axis. So the code
    #: `sketch_plane_not_horizontal` was rejecting 21 sweeps and 2 revolves
    #: for being correctly built.
    #:
    #: What is true here: our op derives these two operations' profile
    #: frame from the PATH (`path_mm` + `ref_dir`) and from the AXIS
    #: (`axis_xy_mm`), not from the sketch, and reconciling the read frame
    #: with the derived one is separate work with its own witness. Until it
    #: is done, the honest answer is to name the absence rather than hand
    #: out (u, v) at random: a profile placed into the wrong frame produces
    #: a plausible solid in the wrong location, and the volume cross-check
    #: WILL NOT CATCH THIS — volume is invariant to motion.
    PROFILE_FRAME_NOT_DERIVED = "profile_frame_not_derived_from_sketch"
    #: The plane frame was read, but the profile points do not lie on it.
    #: Deliberately separate from `profile_unavailable`: "no sketch" is a
    #: READ fix, "did not lie on it" means the normal and the rings
    #: contradict each other — i.e. TWO facts were read, and they disagree.
    PLANE_INCONSISTENT = "plane_inconsistent_with_loops"
    #: The revolve axis is not vertical: `create_solid_revolve.axis_xy_mm`
    #: — `pt_xy`.
    REVOLVE_AXIS_NOT_VERTICAL = "revolve_axis_not_vertical"
    #: Height outside the operation's bounds (`height_mm`, the bounds are
    #: taken from the operation ITSELF, see `_MIN_EXTENT_MM`).
    HEIGHT_OUT_OF_BOUNDS = "height_out_of_bounds"
    #: Revolve angle outside 1..360.
    SWEEP_ANGLE_OUT_OF_BOUNDS = "revolve_angle_out_of_bounds"
    #: THE REVOLVE'S START ANGLE CANNOT BE EXPRESSED (RH-02, 04.09.2026).
    #: The capture honestly reads `Revolution.StartAngle`, and the
    #: `start_angle_deg` field sits in the recipe; the lift took its
    #: DIFFERENCE and printed `sweep_deg`. Measured: a revolve 0°→90° and a
    #: revolve 90°→180° produced the BYTE-FOR-BYTE SAME program, even though
    #: these are different sectors in different places — the solid arrived
    #: rotated, and the volume cross-check does not catch this (volume is
    #: invariant to rotation).
    #:
    #: The operation has NO slot for a start angle, and this is stated
    #: verbatim in `ops_solid.create_solid_revolve` itself: "Always measured
    #: from the world +X axis: there is no start-angle parameter… the frame
    #: is ours to set." So there are exactly two honest moves — extend the
    #: registry (not our edit, not our file) or NAME the loss. It is named
    #: here: a sector that does not start at +X is refused instead of
    #: silently snapping to zero.
    REVOLVE_START_ANGLE_NOT_EXPRESSIBLE = "revolve_start_angle_not_expressible"
    #: The sweep's profile is set by a LOADED FAMILY (`Sweep.ProfileSymbol`),
    #: not a sketch. This is a DEPENDENCY, and capturing it takes a separate
    #: pass.
    SWEEP_PROFILE_IS_SYMBOL = "sweep_profile_is_family_symbol"
    #: THE SWEEP PATH WAS NOT READ AT ALL: `Sweep.PathSketch` is empty or
    #: absent.
    #:
    #: Deliberately separate from `recipe_incomplete`, and here is how this
    #: reason differs. `Sweep` has a `Path3d` property: the path can be set
    #: not by a sketch but by a 3D trajectory, in which case `PathSketch` is
    #: LEGITIMATELY empty. The reading C# does NOT ASK for this property
    #: (measured 21.08: 6 shapes with rings and an empty path, `path_reason`
    #: empty for all six — meaning there was no exception, there was an
    #: empty sketch). Until `Path3d` is read, there is nothing to
    #: distinguish "3D path" from "sketch is empty" with, and the code names
    #: exactly what is known.
    SWEEP_PATH_UNAVAILABLE = "sweep_path_unavailable"
    #: The path was read but does not fit the `path3` kind (more than 64
    #: points, a segment shorter than 1 mm) or the miter at a joint cannot
    #: be built (`sweep_path.feasibility`).
    SWEEP_PATH_NOT_EXPRESSIBLE = "sweep_path_not_expressible"
    #: The profile failed to read (no sketch, empty, the reader refused).
    PROFILE_UNAVAILABLE = "profile_unavailable"
    #: A ring segment is neither a line nor an arc.
    CURVE_KIND_UNSUPPORTED = "curve_kind_unsupported"
    #: The ring does not fit CONTOUR (more points than the limit, more than
    #: 8 openings).
    #:
    #: ⛔ NAME RETIRED ON 26.08.2026: IT DESCRIBED NOT A SINGLE ONE OF ITS
    #: OWN CASES. Kept here as a NAME, not as live code — for the same
    #: reason as `void_form_not_expressible` and
    #: `sketch_plane_not_horizontal` above: 16 refusals under this code are
    #: recorded by the 21.08 measurement and in the canon, and a code that
    #: silently disappeared would make the reader think the measurement was
    #: lost.
    #:
    #: WHAT WAS WRITTEN: "more points than the limit, more than 8
    #: openings." WHAT WAS ACTUALLY THE CASE (26.08 measurement, from the
    #: verbatim text of all 16 refusals): ZERO such cases. Verbatim: 12
    #: "point outside the outer contour" · 1 touching the outer boundary ·
    #: 1 zero-length edge · 1 bulge out of range · 1 degenerate contour.
    #:
    #: One code carried TWO different fixes, and this is a named defect of
    #: this tree — the same one the canon discusses under `KIR-T003`. Twelve
    #: of the sixteen were fixed by OUR READER (the rings are separate, and
    #: it called them holes); the rest by the ring's actual geometry.
    #: Branching on the code was impossible for a consumer.
    CONTOUR_LIMIT_EXCEEDED = "contour_limit_exceeded"
    #: THE PROFILE RINGS DO NOT ASSEMBLE INTO CONTOUR REGIONS.
    #:
    #: Introduced 26.08.2026. A KIR region is EXACTLY one outer ring plus
    #: holes inside it, one level of nesting. Revit's sketch is not bound by
    #: this: an island inside a hole is legal there and inexpressible here.
    #:
    #: Fixed by the LANGUAGE (nesting deeper than one level), not by
    #: reading — hence a separate code from `profile_rejected_by_contour`,
    #: where the ring's own geometry is at fault, and from the retired
    #: `contour_limit_exceeded`, where the reader was at fault.
    PROFILE_RINGS_NOT_A_REGION = "profile_rings_not_a_region"
    #: CONTOUR REJECTED THE REGION ON THE MERITS OF THE RING'S GEOMETRY:
    #: zero-length edge, degenerate area, `bulge` out of range, touching the
    #: boundary.
    #:
    #: Introduced 26.08.2026 to replace `contour_limit_exceeded` for the
    #: cases that have NOTHING TO DO with grouping rings. There are 4 of 16,
    #: and they are fixed by READING THE GEOMETRY or by acknowledging a
    #: limit, not by addressing the rings. `detail` carries the verbatim
    #: text of CONTOUR's diagnostic — it names exactly what is wrong.
    PROFILE_REJECTED_BY_CONTOUR = "profile_rejected_by_contour"
    #: The shape kind is not in the registry at all (SweptBlend).
    NO_OP_FOR_FORM_KIND = "no_op_for_form_kind"
    #: The shape was read, but something is missing from the payload.
    RECIPE_INCOMPLETE = "recipe_incomplete"


class FamilyRecipeError(ValueError):
    """The payload violated the capture protocol."""


@dataclass(frozen=True, slots=True)
class Refusal:
    """A named refusal for ONE shape.

    `detail` must be non-empty and carry a NUMBER or a NAME: a refusal
    without a measured value sends the reader off to measure again.
    """

    code: RecipeRefusal
    detail: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, RecipeRefusal):
            raise FamilyRecipeError("refusal code must be typed")
        if not isinstance(self.detail, str) or not self.detail:
            raise FamilyRecipeError("refusal detail must be non-empty")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class FamilyParam:
    """One family parameter, read from `FamilyManager` (21.08.2026)."""

    name: str
    storage: str
    is_instance: bool = False
    is_shared: bool = False
    is_reporting: bool = False
    by_formula: bool = False
    formula: str | None = None
    #: The value for the CURRENT type, in Revit's internal units.
    value_internal: float | None = None
    #: The same in millimeters — ONLY IF the parameter carries a length.
    #:
    #: 🔴 THE FIELD'S NAME IS ITS OWN CAVEAT, AND IT WAS BOUGHT BY A LIVE
    #: MEASUREMENT. Only `Definition.GetDataType` reliably gives a
    #: parameter's unit, and that does not exist on 2021. So the conversion
    #: is ALWAYS performed, and it is only correct for lengths: for the
    #: "C250X30" profile the `A` parameter (area) equals 0.004 and turns
    #: here into "12.4344 mm", which is meaningless. The `value_shown`
    #: field next to it carries the unit as TEXT, the way Revit itself
    #: writes it, and deciding from that is more honest than guessing.
    value_mm_if_length: float | None = None
    value_int: int | None = None
    value_str: str | None = None
    #: How Revit displays the value — with its own unit and its own
    #: format.
    value_shown: str | None = None
    value_reason: str | None = None
    #: `INVALID` means the parameter is AUTHOR-DEFINED; any other name
    #: means it is built into Revit.
    built_in: str | None = None

    @property
    def is_authored(self) -> bool:
        """Set up by a human (or by us), not by Revit when the family was
        created."""
        return self.built_in in (None, "INVALID")

    @property
    def has_formula(self) -> bool:
        """🔴 `formula` DECIDES, NOT THE FLAG, AND THIS IS MEASURED.

        21.08.2026, `KIR_проба_семейства`: for `Высота_удвоенная` the
        formula `"Высота_KIR * 2"` reads back correctly, while
        `IsDeterminedByFormula` = False.
        """
        return bool(self.formula)


@dataclass(frozen=True, slots=True)
class FormDrive:
    """"This family parameter drives this specific field of this specific
    shape."

    🔴 THE RELATION THE RECIPE WAS MISSING BEFORE 21.08.2026. Without it,
    `author_family` has nowhere to get `flex_param` from, and a lifter
    building on top of such a recipe would have had to INVENT a parameter
    name and a link — that is, pass off a rigid family as a flexible one.
    The 21.08 measurement showed the cost of this: an unlinked parameter
    changes the volume NOT AT ALL, while the receipt still comes back
    green.
    """

    #: The family parameter's name (localized).
    family_param: str
    #: The element parameter's name (localized: «Конец выдавливания»).
    element_param: str
    #: 🔴 THE ONLY FIELD FIT FOR MAKING A DECISION. Names are localized and
    #: will diverge on a different Revit language; `BuiltInParameter` is the
    #: same across six versions and every language.
    built_in: str | None = None
    storage: str | None = None


@dataclass(frozen=True, slots=True)
class FormRecipe:
    """One family shape, read from Revit."""

    form_id: str
    kind: FormKind
    is_solid: bool
    name: str
    #: The sketch plane's normal, unit length, in family coordinates.
    plane_normal: tuple[float, float, float] | None
    #: The profile plane's Z elevation, mm (for planar shapes).
    plane_z_mm: float | None
    #: The profile rings RAW, in family coordinates: a segment =
    #: (kind, p0_xyz, p1_xyz, mid_xyz|None).
    #:
    #: 🔴 THIS USED TO HOLD ALREADY-BUILT CONTOUR EDGES WITH A BULGE, AND
    #: THAT WAS THE SAME DEFECT THIS WHOLE WAVE FIXES. The bulge was
    #: computed in the XY plane while parsing the payload — that is, BEFORE
    #: it was known which plane the sketch actually lies in. For a tilted
    #: sketch, the projection onto XY gives a different chord, a different
    #: bulge, and a plausible but WRONG arc. So the curve's kind arrives
    #: here raw, and is converted into (u, v) at the point where the frame
    #: is already known (`_project_loops`).
    loops: tuple[tuple[tuple[Any, ...], ...], ...]
    #: The plane's origin in family coordinates, mm. `None` means an
    #: old-edition payload: then the origin is DERIVED from the rings
    #: themselves and VERIFIED.
    plane_origin_mm: tuple[float, float, float] | None = None
    #: The plane's +u axis, as returned by Revit (`Plane.XVec`). `None` —
    #: same as above.
    plane_x_dir: tuple[float, float, float] | None = None
    #: The blend's top rings (`Blend.TopSketch`), in the same raw form.
    top_loops: tuple[tuple[tuple[Any, ...], ...], ...] = ()
    #: The shape's offsets along the normal, mm.
    start_offset_mm: float | None = None
    end_offset_mm: float | None = None
    #: Revolve.
    axis_start_mm: tuple[float, float, float] | None = None
    axis_end_mm: tuple[float, float, float] | None = None
    start_angle_deg: float | None = None
    end_angle_deg: float | None = None
    #: The sweep path as POINTS. 🔴 THE CURVE'S KIND IS LOST HERE, AND THIS
    #: IS A NAMED READING GAP, NOT A LAW. The reading C# takes
    #: `GetEndPoint(0)` and `GetEndPoint(1)` from each curve of the path
    #: sketch — meaning an ARC in the path arrives here as its CHORD, with
    #: nothing to tell it apart from a straight segment. Our op does not
    #: accept arcs in a path either (the `path3` kind is a polyline), so the
    #: language is not harmed by this; the harm would be in SILENCE: an arc
    #: would get built as a straight line, and Revit would look like the
    #: one at fault.
    #:
    #: WHAT THE MEASUREMENT KNOWS (21.08.2026): for 34 sweeps for which
    #: Revit returned its own volume, the polyline reading matched it
    #: EXACTLY (worst discrepancy 0.0024%). Arcs in these 34 paths are
    #: excluded — their presence would have shifted the volume. Nothing is
    #: known about the rest, and closing this gap takes exactly one line in
    #: the reader: placing `__c.GetType().Name` next to it. It is
    #: deliberately not written here — the reader is fixed together with a
    #: live run, not blindly.
    #:
    #: A SECOND SILENCE OF THE SAME READ: if the path sketch has SEVERAL
    #: `CurveArray`s, the points are chained into one unbroken polyline.
    path_mm: tuple[tuple[float, float, float], ...] = ()
    profile_is_symbol: bool = False
    #: ── WHICH EXACT PROFILE A SWEEP HAS (26.08.2026) ─────────────────────
    #:
    #: 🔴 `profile_is_symbol` ALONE IS A RELATION WITHOUT AN ADDRESS. It is
    #: boolean: it says the profile is set by a loaded family, and does not
    #: say WHICH ONE. There was nothing to join against, and
    #: `sweep_profile_is_family_symbol` is the dominant expressibility
    #: refusal for the corpus: 20 shapes across 18 families out of 82
    #: (26.08 measurement, from a fresh payload).
    #:
    #: Read from `Sweep.ProfileSymbol` (`FamilySymbolProfile`, 5 members,
    #: 6/6 versions with no drift). The type's name and its FAMILY's name
    #: are different quantities: joining across the corpus must be done by
    #: the latter.
    profile_symbol_name: str | None = None
    profile_family_name: str | None = None
    #: The profile's PLACEMENT on the path: offsets, rotation, mirroring.
    #:
    #: 🔴 WITHOUT THESE, A SECOND PASS WOULD BUILD THE RIGHT OUTLINE IN THE
    #: WRONG PLACE, AND SAY NOTHING. The profile is not just the ring's
    #: shape: `XOffset`, `YOffset`, `Angle`, `IsFlipped` move and turn it
    #: relative to the path. Capturing only the name would mean preparing a
    #: silent lie.
    profile_x_offset_mm: float | None = None
    profile_y_offset_mm: float | None = None
    profile_angle_deg: float | None = None
    profile_flipped: bool | None = None
    #: Where the knowledge about the profile-family comes from: see
    #: :data:`KNOWLEDGE_SOURCES`.
    profile_symbol_source: str = KNOWLEDGE_NOT_ASKED
    profile_symbol_reason: str | None = None
    #: ── PATH AS 3D CURVES INSTEAD OF A SKETCH (26.08.2026) ───────────────
    #:
    #: `Sweep.Path3d` is the second legitimate form of a path. As long as it
    #: was not asked for, "the path is set by 3D curves" and "the path
    #: sketch is empty" were indistinguishable, and six shapes across five
    #: families hung on this IGNORANCE under the code
    #: `sweep_path_unavailable`.
    #:
    #: 🔴 REVIT NAMES THE KIND, NOT US. The XML doc comment doesn't declare
    #: the type ("The selected curves used for the sweep path"), so the
    #: reading C# takes the value as `object` and puts the KIND's name here
    #: exactly as Revit itself returns it. Less knowledge, but not a single
    #: invented fact.
    path3d_source: str = KNOWLEDGE_NOT_ASKED
    path3d_kind: str | None = None
    path3d_count: int | None = None
    path3d_reason: str | None = None
    #: What Revit measured for THIS SAME shape — the other side of the
    #: cross-check.
    measured_volume_mm3: float | None = None
    #: Why the profile failed to read, if it failed to read.
    profile_reason: str | None = None
    #: Parameter bindings to the fields of THIS shape.
    driven_by: tuple[FormDrive, ...] = ()
    #: 🔴 "NO BINDINGS" AND "BINDINGS NOT READ" ARE DIFFERENT ANSWERS.
    #: A payload captured before 21.08.2026 does not carry the `driven_by`
    #: key at all, and an empty tuple without this flag would mean "the
    #: family is rigid" where the truth is "we did not ask". This is our
    #: named shape of the defect — "zero of an uncomputed value".
    drives_read: bool = False
    assoc_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FamilyRecipe:
    """The family as a whole."""

    family_name: str
    category: str
    forms: tuple[FormRecipe, ...]
    open_failed_reason: str | None = None
    params: tuple[FamilyParam, ...] = ()
    #: The same discriminator as `FormRecipe.drives_read`, for parameters.
    params_read: bool = False
    types: tuple[str, ...] = ()
    current_type: str = ""
    fm_failed_reason: str | None = None
    #: ── CENSUS OF THE FAMILY DOCUMENT'S ELEMENTS (26.08.2026) ────────────
    #:
    #: 🔴 THE CENSUS LAW HELD AT THE TOP AND WAS BROKEN INSIDE. At the top
    #: level the payload carries `families_seen` and `families_read`;
    #: inside a family the capture takes ONLY `GenericForm` and says nothing
    #: about what it skipped. The 26.08 measurement: 27 of 110 families open
    #: and return ZERO shapes, and only 8 are two-dimensional by nature. The
    #: other nineteen (a sofa, a kitchen, elevators, a trash bin, five
    #: windows, a cabinet) demonstrably have geometry — and for a whole week
    #: were read as "families with no shapes".
    #:
    #: `by_class` is a PARTITION: the sum of its values equals `elements`
    #: exactly, because an element has exactly one kind. The named counters
    #: next to it are aggregates, and they CAN overlap: Revit's class
    #: inheritance is not declared to us by anything, and an `else if` chain
    #: would silently attribute a descendant to its ancestor. Reconciliation
    #: must be done via `by_class`.
    census_elements: int | None = None
    census_generic_forms: int | None = None
    census_family_instances: int | None = None
    census_import_instances: int | None = None
    census_free_form_elements: int | None = None
    census_by_class: tuple[tuple[str, int], ...] = ()
    census_source: str = KNOWLEDGE_NOT_ASKED
    census_reason: str | None = None

    @property
    def census_reconciles(self) -> bool | None:
        """Whether the census agrees WITH ITSELF: the sum of kinds equals
        the total element count.

        `None` means there is no census (not asked for, or it failed), and
        this is a THIRD answer, not "no". A census that does not add up is
        a broken instrument, and staying silent about it is worse than not
        having an instrument at all.
        """
        if self.census_source != "api" or self.census_elements is None:
            return None
        return sum(n for _c, n in self.census_by_class) == self.census_elements

    @property
    def forms_unseen(self) -> int | None:
        """How many `GenericForm`s the census found that the shape parse
        did NOT bring back.

        Zero means shape capture saw them all. More than zero means a shape
        was lost between the census and the parse, and that is a defect,
        not a property of the family. `None` means there is no census.
        """
        if self.census_source != "api" or self.census_generic_forms is None:
            return None
        return self.census_generic_forms - len(self.forms)

    @property
    def flex_candidates(self) -> tuple[tuple[str, str, str], ...]:
        """(parameter, built_in_field, shape) — what DRIVES this family.

        Empty for a rigid family AND for an unread one; `params_read`
        distinguishes between them. This is the direct input for
        `author_family.flex_param`.
        """
        out = []
        for form in self.forms:
            for drive in form.driven_by:
                out.append((drive.family_param,
                            drive.built_in or drive.element_param,
                            form.form_id))
        return tuple(out)

    @property
    def rigid_with_a_handle(self) -> tuple[str, ...]:
        """Parameters that EXIST and drive NOTHING. The silent lie of
        21.08.

        This exact case could not be seen in the recipe before 21.08: for
        `KIR_проба_семейства`, the `Высота_KIR` parameter was set to
        1600 mm, while the volume stayed at 192,000,000 = 600x400x800. It
        was only caught by measuring the solid; now it is read directly.

        🔴 The answer only makes sense when `params_read and` the bindings
        were read — otherwise it speaks about our own ignorance, not about
        the family.
        """
        if not self.params_read:
            return ()
        driven = {d.family_param for f in self.forms for d in f.driven_by}
        return tuple(p.name for p in self.params
                     if p.name not in driven
                     and p.is_authored              # built-in parameters are not required to drive anything
                     and not p.has_formula          # a formula is its own kind of work
                     and p.storage in ("Double", "Integer"))


@dataclass(frozen=True, slots=True)
class FormLift:
    """The result of translating ONE shape: an operation, a PART, or a
    refusal — exactly one.

    🔴 THE THIRD OUTCOME WAS INTRODUCED ON 21.08.2026, AND IT IS A
    DISTINCTION, NOT A CONVENIENCE. A solid family shape is an ELEMENT: it
    has its own registry operation, its own DirectShape, its own name in
    the project tree. A VOID is never an element under any conditions: it
    is an OPERAND, and the only way to state it is as part of a boolean
    (`ops_boolean.PART_SHAPES`, kind `prism`).

    Raising a void as an "operation" would mean building a SOLID exactly
    where the family has a HOLE — and calling that a captured recipe. This
    is exactly the class of silent lie the whole module is written against,
    which is why a void gets its own slot, not someone else's.
    """

    form_id: str
    kind: FormKind
    #: The shape's OPERATIONS. Plural since 26.08.2026, and this is not a
    #: convenience.
    #:
    #: 🔴 ONE REVIT SHAPE CAN BE SEVERAL SOLIDS. A sketch with separate
    #: closed rings gives as many solids as rings (see `_group_rings`). A
    #: singular here forced the reader to pick one of them and stay silent
    #: about the rest — that is, to lose geometry in a way that would make
    #: the volume cross-check blame Revit.
    #:
    #: THE LIFT IS STILL ONE PER SHAPE, and this keeps the census intact:
    #: `lift_summary` counts SHAPES, not solids, and the number 283 will not
    #: move because of this change.
    ops: tuple[dict[str, Any], ...]
    refusal: Refusal | None
    predicted_volume_mm3: float | None = None
    measured_volume_mm3: float | None = None
    #: The boolean's PARTS — for a VOID. Mutually exclusive with `ops` and
    #: `refusal`. Plural for the same reason as `ops`: a void made of
    #: separate rings is several holes, not one.
    parts: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        carried = sum(1 for v in (self.ops, self.parts, self.refusal) if v)
        if carried != 1:
            raise FamilyRecipeError(
                "FormLift must carry exactly one of ops/parts/refusal")

    @property
    def op(self) -> dict[str, Any] | None:
        """The shape's FIRST solid — only for single-solid readers.

        🔴 `None` FOR A MULTI-SOLID SHAPE IS DELIBERATE. Handing back the
        first solid would mean silently passing off a part as the whole —
        exactly the named defect the plural was introduced to fix. A reader
        that actually needs the solid needs `ops`; this accessor is left
        for the places where single-solidness is PROVEN.
        """
        return self.ops[0] if len(self.ops) == 1 else None

    @property
    def part(self) -> dict[str, Any] | None:
        """The FIRST part of a void. The same contract as :attr:`op`."""
        return self.parts[0] if len(self.parts) == 1 else None

    @property
    def bodies(self) -> int:
        """How many SOLIDS the shape yields: by operations or by parts."""
        return len(self.ops) + len(self.parts)

    @property
    def lifted(self) -> bool:
        """WHETHER THE LANGUAGE COULD STATE THIS SHAPE — as an operation OR
        as a part.

        A part counts on equal footing with an operation because this
        module's question is "can the shape be EXPRESSED", not "does it
        become an element". The question "does a family PROGRAM assemble
        from the expressed shapes" is a different one, answered by
        :func:`recipe_to_program`, which prints its own blockers as a
        separate list rather than hiding them inside this property.
        """
        return bool(self.ops) or bool(self.parts)

    @property
    def volume_verdict(self) -> str:
        """CROSS-CHECKING THE RECIPE AGAINST THE GEOMETRY — the one thing
        here that can fail.

        Three outcomes, not two: "not checked" is deliberately kept
        separate from "matched", because an uncompared value and a matching
        one both read equally green, yet mean different things.
        """
        if self.predicted_volume_mm3 is None or self.measured_volume_mm3 is None:
            return "not_compared"
        measured = self.measured_volume_mm3
        if measured <= 0.0:
            return "not_compared"
        delta = abs(self.predicted_volume_mm3 - measured) / measured
        return "match" if delta <= VOLUME_MATCH_TOL else "mismatch"


# ── reading the payload ────────────────────────────────────────────────────

def _num(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FamilyRecipeError(f"{where}: ожидалось число, пришло {value!r}")
    return float(value)


def _xyz(value: Any, where: str) -> tuple[float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise FamilyRecipeError(f"{where}: ожидалась точка [x,y,z]")
    return (_num(value[0], where), _num(value[1], where), _num(value[2], where))


def _loops_from_payload(raw: Any, where: str) -> tuple:
    """Payload rings -> RAW segments `(kind, p0, p1, mid|None)`.

    An arc arrives as three points (start, midpoint ON the arc, end) — the
    same contract as `sketch_extract`: there is no tessellation on either
    side.

    🔴 THE BULGE IS NOT COMPUTED HERE, AND THIS IS A FIX, NOT A RELOCATION.
    The previous edition called `_bulge_from_midpoint` right here — that is,
    it computed curvature in the XY plane BEFORE knowing which plane the
    sketch actually lies in. While a tilted plane was a refusal, this was
    harmless; lifting the refusal would have silently produced a plausible
    but WRONG arc. Conversion to (u, v) and the bulge now live in
    `_project_loops`, where the frame is already known.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise FamilyRecipeError(f"{where}: кольца — список")
    loops: list[tuple] = []
    for li, loop in enumerate(raw):
        if not isinstance(loop, list) or not loop:
            raise FamilyRecipeError(f"{where}[{li}]: кольцо — непустой список")
        segs: list[tuple] = []
        for si, seg in enumerate(loop):
            at = f"{where}[{li}][{si}]"
            if not isinstance(seg, Mapping):
                raise FamilyRecipeError(f"{at}: сегмент — объект")
            kind = str(seg.get("kind"))
            p0 = _xyz(seg.get("p0"), f"{at}.p0")
            p1 = _xyz(seg.get("p1"), f"{at}.p1")
            mid = (_xyz(seg.get("mid"), f"{at}.mid")
                   if kind == "arc" else None)
            segs.append((kind, p0, p1, mid))
        loops.append(tuple(segs))
    return tuple(loops)


#: How far a ring point may stray from the declared plane, mm.
#: 🔴 MEASURED, NOT ASSIGNED: across 110 tilted shapes of a real building,
#: the largest spread of points along the normal was **0.0001 mm**, the
#: median was zero. The threshold is set three orders of magnitude above
#: the measurement and still four orders of magnitude below the coordinate
#: print quantum (`contour.EMIT_COORD_QUANTUM_MM` = 0.01 mm), meaning it
#: can only fail on a real contradiction between the normal and the rings.
PLANE_FIT_TOL_MM = 0.1


def _plane_from_form(form: "FormRecipe") -> tuple[dict | None, Refusal | None]:
    """The sketch frame FROM WHAT WAS READ, with verification. Never
    silently guesses.

    THE ORDER OF SOURCES AND WHY IT IS THAT WAY:

      1. `plane_origin_mm` / `plane_x_dir` — what Revit ITSELF returned
         (`Plane.Origin`, `Plane.XVec`). Taken first because it is the only
         answer that closes the loop literally: what we state going forward
         is the same frame we read going back;
      2. DERIVED FROM THE RINGS — for a prior-edition payload where these
         fields are absent. This is not guessing on the author's behalf:
         every ring point LIES in the plane, so any frame with the same
         normal describes the same geometry, and the difference between
         them is calibration, not shape.

    🔴 AND IN BOTH CASES THE FRAME IS VERIFIED BY A ROUND TRIP. This is what
    tells derivation apart from guessing: every point read is converted to
    (u, v) and back into world space, and a discrepancy larger than
    `PLANE_FIT_TOL_MM` is a NAMED refusal. The check can fail — for
    instance if Revit returns one sketch's normal together with another's
    rings — and that is exactly why it is worth something.
    """
    from kir import plane as PL

    normal = form.plane_normal
    if normal is None:
        return None, Refusal(RecipeRefusal.PROFILE_UNAVAILABLE,
                             "у эскиза не прочитана нормаль плоскости "
                             "(SketchPlane.GetPlane() вернул null либо бросил)")
    pts = [pt for loop in form.loops for seg in loop
           for pt in (seg[1], seg[2]) if pt is not None]
    if not pts:
        return None, Refusal(RecipeRefusal.PROFILE_UNAVAILABLE,
                             "профиль не содержит ни одной точки")

    length = math.sqrt(sum(c * c for c in normal))
    if length <= 0.0:
        return None, Refusal(RecipeRefusal.PLANE_INCONSISTENT,
                             f"нормаль нулевой длины {normal!r}")
    n = tuple(c / length for c in normal)

    origin = form.plane_origin_mm
    if origin is None:
        # HORIZONTAL IS THE DEGENERATE CASE, AND IT MUST YIELD EXACTLY
        # TODAY'S FRAME: origin [0, 0, plane_z], +u along world +X. Then
        # u = x and v = y, meaning the projection matches the old "take the
        # first two coordinates" DOWN TO THE BIT, and the 27 already-raised
        # shapes do not move.
        if abs(abs(n[2]) - 1.0) <= PLANE_NORMAL_TOL:
            origin = (0.0, 0.0, float(form.plane_z_mm or 0.0))
        else:
            origin = pts[0]
    x_dir = form.plane_x_dir
    if x_dir is None:
        if abs(abs(n[2]) - 1.0) <= PLANE_NORMAL_TOL:
            x_dir = (1.0, 0.0, 0.0)
        else:
            # THE POINT FARTHEST FROM THE ORIGIN, NOT "THE NEXT ONE": the
            # choice must be robust to segment order and to a degenerately
            # short first edge. Ties are broken by index — that is, the
            # choice is DETERMINISTIC, not "whichever came up".
            best = None
            best_d = 0.0
            for pt in pts:
                d = tuple(pt[k] - origin[k] for k in range(3))
                proj = sum(d[k] * n[k] for k in range(3))
                d = tuple(d[k] - proj * n[k] for k in range(3))
                mag = math.sqrt(sum(c * c for c in d))
                if mag > best_d + 1e-12:
                    best_d, best = mag, d
            if best is None or best_d <= 1e-9:
                return None, Refusal(
                    RecipeRefusal.PLANE_INCONSISTENT,
                    "все точки профиля совпали с началом плоскости — рамку "
                    "вывести не из чего")
            x_dir = tuple(c / best_d for c in best)

    diags: list = []
    built = PL.validate_plane(
        {"origin_mm": [float(c) for c in origin],
         "normal": [float(c) for c in n],
         "x_dir": [float(c) for c in x_dir]},
        form.form_id or "F", "plane", diags)
    if built is None:
        first = diags[0].message_ru if diags else "плоскость отвергнута"
        return None, Refusal(RecipeRefusal.PLANE_INCONSISTENT, str(first)[:240])

    # THE ROUND TRIP IS WHAT MAKES THIS A MEASUREMENT, NOT AN ASSUMPTION.
    worst = 0.0
    for pt in pts:
        u, v = _to_uv(built, pt)
        back = PL.to_world(built, u, v)
        worst = max(worst, max(abs(back[k] - pt[k]) for k in range(3)))
    if worst > PLANE_FIT_TOL_MM:
        return None, Refusal(
            RecipeRefusal.PLANE_INCONSISTENT,
            f"точки профиля не лежат в прочитанной плоскости: наибольшее "
            f"расхождение {worst:.4f} мм при допуске {PLANE_FIT_TOL_MM} мм "
            f"(нормаль и кольца прочитаны оба и не согласны)")
    return built, None


def _axial_plane_from_form(form: "FormRecipe") -> tuple[dict | None, Refusal | None]:
    """The REVOLVE profile's frame is DERIVED FROM THE AXIS, not read from
    the sketch.

    WHY SEPARATE FROM `_plane_from_form`. Our op reads a revolve's profile
    in AXIAL coordinates: u is the RADIUS from the axis, v is the elevation
    along the axis (as Revit itself requires — "loops must lie in the xz
    coordinate plane… where x >= 0" — and as `ops_solid` states). The
    family sketch's frame plays no such role: Revit chose its origin and
    +u axis itself, and taking them would mean reading a radius from
    someone else's point. Here the frame is DERIVED from the axis and
    VERIFIED by the same two laws as any other: the points must lie on the
    plane, the radius must be non-negative.

    A DERIVED BASIS, SO IT CAN BE CHECKED BY EYE. The axis is vertical
    (verified separately and earlier), so the profile plane CONTAINS Z,
    meaning its normal is horizontal. The radial direction is r = Z × n:
    then Y = n × r = Z, meaning v matches the world elevation and u matches
    the distance from the axis. If the profile ends up on the left
    (u < 0), the normal is flipped — this changes the sign of r and does
    NOT change Y, because both factors flip sign together.

    🔴 THE FALSE REFUSAL THIS REMOVES: before 21.08, a revolve was asked for
    sketch HORIZONTALITY, while a revolve's sketch is vertical BY
    CONSTRUCTION. Two revolve solids of a real building were rejected for
    being correctly built.
    """
    from kir import plane as PL

    normal = form.plane_normal
    if normal is None:
        return None, Refusal(RecipeRefusal.PROFILE_UNAVAILABLE,
                             "у эскиза вращения не прочитана нормаль плоскости")
    if form.axis_start_mm is None or form.axis_end_mm is None:
        return None, Refusal(RecipeRefusal.RECIPE_INCOMPLETE,
                             "у вращения не прочитана ось")
    ax0 = form.axis_start_mm
    length = math.sqrt(sum(c * c for c in normal))
    if length <= 0.0:
        return None, Refusal(RecipeRefusal.PLANE_INCONSISTENT,
                             f"нормаль нулевой длины {normal!r}")
    n = tuple(c / length for c in normal)
    if abs(n[2]) > PLANE_NORMAL_TOL * 1e3:
        return None, Refusal(
            RecipeRefusal.PLANE_INCONSISTENT,
            f"плоскость профиля вращения не содержит вертикальной оси: "
            f"нормаль [{n[0]:.4f}, {n[1]:.4f}, {n[2]:.4f}], её Z-компонента "
            f"{n[2]:.6f} обязана быть нулём")
    # r = Z × n
    r = (-n[1], n[0], 0.0)
    rlen = math.sqrt(r[0] * r[0] + r[1] * r[1])
    if rlen <= 1e-9:
        return None, Refusal(RecipeRefusal.PLANE_INCONSISTENT,
                             "нормаль коллинеарна оси — радиального "
                             "направления в плоскости нет")
    r = (r[0] / rlen, r[1] / rlen, 0.0)
    origin = (float(ax0[0]), float(ax0[1]), 0.0)
    pts = [pt for loop in form.loops for seg in loop
           for pt in (seg[1], seg[2]) if pt is not None]
    if not pts:
        return None, Refusal(RecipeRefusal.PROFILE_UNAVAILABLE,
                             "профиль вращения не содержит ни одной точки")
    signed = [sum((pt[k] - origin[k]) * r[k] for k in range(3)) for pt in pts]
    if max(signed) <= 0.0:
        n = tuple(-c for c in n)
        r = tuple(-c for c in r)

    diags: list = []
    built = PL.validate_plane(
        {"origin_mm": list(origin), "normal": list(n), "x_dir": list(r)},
        form.form_id or "F", "plane", diags)
    if built is None:
        first = diags[0].message_ru if diags else "плоскость отвергнута"
        return None, Refusal(RecipeRefusal.PLANE_INCONSISTENT, str(first)[:240])

    worst = 0.0
    for pt in pts:
        u, v = _to_uv(built, pt)
        back = PL.to_world(built, u, v)
        worst = max(worst, max(abs(back[k] - pt[k]) for k in range(3)))
    if worst > PLANE_FIT_TOL_MM:
        return None, Refusal(
            RecipeRefusal.PLANE_INCONSISTENT,
            f"точки профиля вращения не легли в осевую плоскость: наибольшее "
            f"расхождение {worst:.4f} мм при допуске {PLANE_FIT_TOL_MM} мм")
    return built, None


def _to_uv(plane: dict, pt) -> tuple[float, float]:
    """A world point -> a plane's (u, v). ONE place for the whole module."""
    from kir import plane as PL

    o, x, y, _n = PL.frame(plane)
    d = (pt[0] - o[0], pt[1] - o[1], pt[2] - o[2])
    return (d[0] * x[0] + d[1] * x[1] + d[2] * x[2],
            d[0] * y[0] + d[1] * y[1] + d[2] * y[2])


def _project_loops(loops, plane: dict) -> tuple:
    """Raw segments -> CONTOUR edges `(p0_uv, p1_uv, bulge)` IN THE PLANE.

    The bulge is computed here, and only here, because the frame is known
    here, and only here. A kind CONTOUR does not know arrives as a STRING
    in the bulge's place — the same way as before: it must become a NAMED
    refusal further up, not silently turn into a straight line.
    """
    out = []
    for loop in loops:
        edges = []
        for kind, p0, p1, mid in loop:
            a = _to_uv(plane, p0)
            b = _to_uv(plane, p1)
            if kind == "line":
                edges.append((a, b, 0.0))
            elif kind == "arc" and mid is not None:
                edges.append((a, b, _bulge_from_midpoint(a, b, _to_uv(plane, mid))))
            else:
                edges.append((a, b, kind))
        out.append(tuple(edges))
    return tuple(out)


def _bulge_from_midpoint(p0, p1, mid) -> float:
    """`bulge = tan(sweep/4)`, from a point ON the arc at its parametric
    midpoint.

    Computed IN THE SKETCH PLANE'S COORDINATES (u, v), not in world XY:
    before 21.08.2026 this used world XY, and that was correct only because
    a tilted sketch was refused earlier. Lifting the refusal would have made
    that same arithmetic wrong — projecting the arc onto the wrong plane
    gives a different chord, a different bulge, and a plausible but WRONG
    arc. The caller must supply (u, v).
    """
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    chord = math.hypot(dx, dy)
    if chord <= 0.0:
        return 0.0
    # 🔴 THE SIGN IS DERIVED FROM `contour.bulge_midpoint`, NOT INVENTED. It
    # places the midpoint as `chord_mid - n*s`, where `n = (-dy, dx)/ch` is
    # the chord's LEFT normal, and `s = bulge*ch/2`. So the reverse step is
    # `s = -(mid-chord_mid)·n`.
    #
    # The first edition took the sign of the cross product and got the
    # OPPOSITE one: a circle made of four quarters bulged inward, the area
    # came out as 858,407 mm² instead of 3,141,593 — meaning a round column
    # turned into a concave star, silently. Caught by a test against a
    # circle's area; the argument "the sign is obvious" turned out to be
    # exactly half wrong.
    nx, ny = -dy / chord, dx / chord
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    sagitta = -((mid[0] - mx) * nx + (mid[1] - my) * ny)
    return 2.0 * sagitta / chord


def parse_recipe_payload(payload: Any) -> tuple[FamilyRecipe, ...]:
    """The bridge payload -> typed recipes. Never guesses."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, Mapping):
        raise FamilyRecipeError("payload — объект")
    if payload.get("schema_version") != FAMILY_RECIPE_SCHEMA_VERSION:
        raise FamilyRecipeError(
            f"schema_version: ожидалось {FAMILY_RECIPE_SCHEMA_VERSION!r}, "
            f"пришло {payload.get('schema_version')!r}")
    families_raw = payload.get("families")
    if not isinstance(families_raw, list):
        raise FamilyRecipeError("payload.families — список")
    out: list[FamilyRecipe] = []
    for fi, fam in enumerate(families_raw):
        at = f"families[{fi}]"
        if not isinstance(fam, Mapping):
            raise FamilyRecipeError(f"{at}: семейство — объект")
        forms: list[FormRecipe] = []
        for gi, form in enumerate(fam.get("forms") or []):
            forms.append(_parse_form(form, f"{at}.forms[{gi}]"))
        params_raw = fam.get("family_params")
        out.append(FamilyRecipe(
            family_name=str(fam.get("name") or ""),
            category=str(fam.get("category") or ""),
            forms=tuple(forms),
            open_failed_reason=(str(fam["open_failed"])
                                if fam.get("open_failed") else None),
            params=tuple(_parse_family_param(r, f"{at}.family_params[{i}]")
                         for i, r in enumerate(params_raw or [])),
            params_read=isinstance(params_raw, list),
            types=tuple(str(t) for t in (fam.get("types") or [])),
            current_type=str(fam.get("current_type") or ""),
            fm_failed_reason=(str(fam["fm_failed"])
                              if fam.get("fm_failed") else None),
            census_elements=_opt_int(fam, "census_elements", at),
            census_generic_forms=_opt_int(fam, "census_generic_forms", at),
            census_family_instances=_opt_int(fam, "census_family_instances", at),
            census_import_instances=_opt_int(fam, "census_import_instances", at),
            census_free_form_elements=_opt_int(fam, "census_free_form_elements", at),
            census_by_class=_by_class(fam.get("census_by_class"),
                                      f"{at}.census_by_class"),
            census_source=_source(fam, "census_source", at),
            census_reason=(str(fam["census_reason"])
                           if fam.get("census_reason") else None),
        ))
    return tuple(out)


def _opt_int(raw: Mapping, key: str, at: str) -> int | None:
    """An integer from the payload, or `None`. A boolean is NOT COUNTED as
    an integer.

    In Python, `True` is `1`, and without this check `census_elements: true`
    would arrive as a census of one element.
    """
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        if value is not None:
            raise FamilyRecipeError(f"{at}.{key}: ожидалось целое, "
                                    f"пришло {value!r}")
        return None
    return value


def _by_class(raw: Any, at: str) -> tuple[tuple[str, int], ...]:
    """The census breakdown by kind, sorted by DESCENDING count.

    The order is fixed here rather than left to the payload's whim: the
    census is read by eye, and the first kind must be the most common one.
    """
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise FamilyRecipeError(f"{at}: разбиение переписи — объект")
    rows: list[tuple[str, int]] = []
    for name, count in raw.items():
        if isinstance(count, bool) or not isinstance(count, int):
            raise FamilyRecipeError(f"{at}[{name!r}]: счёт — целое, "
                                    f"пришло {count!r}")
        rows.append((str(name), count))
    return tuple(sorted(rows, key=lambda r: (-r[1], r[0])))


def _parse_family_param(raw: Any, at: str) -> FamilyParam:
    if not isinstance(raw, Mapping):
        raise FamilyRecipeError(f"{at}: параметр — объект")
    name = str(raw.get("name") or "")
    if not name:
        raise FamilyRecipeError(f"{at}: у параметра нет имени")

    def _f(key: str) -> float | None:
        v = raw.get(key)
        return float(v) if isinstance(v, (int, float)) else None

    return FamilyParam(
        name=name,
        storage=str(raw.get("storage") or ""),
        is_instance=bool(raw.get("is_instance")),
        is_shared=bool(raw.get("is_shared")),
        is_reporting=bool(raw.get("is_reporting")),
        by_formula=bool(raw.get("by_formula")),
        formula=(str(raw["formula"]) if raw.get("formula") else None),
        value_internal=_f("value_internal"),
        value_mm_if_length=_f("value_mm_if_length"),
        value_int=(int(raw["value_int"])
                   if isinstance(raw.get("value_int"), int) else None),
        value_str=(str(raw["value_str"])
                   if raw.get("value_str") is not None else None),
        value_shown=(str(raw["value_shown"])
                     if raw.get("value_shown") is not None else None),
        value_reason=(str(raw["value_reason"])
                      if raw.get("value_reason") else None),
        built_in=(str(raw["built_in"]) if raw.get("built_in") else None),
    )


def _parse_drive(raw: Any, at: str) -> FormDrive:
    if not isinstance(raw, Mapping):
        raise FamilyRecipeError(f"{at}: привязка — объект")
    fp = str(raw.get("family_param") or "")
    ep = str(raw.get("element_param") or "")
    if not fp or not ep:
        raise FamilyRecipeError(f"{at}: у привязки нет обоих концов")
    return FormDrive(family_param=fp, element_param=ep,
                     built_in=(str(raw["built_in"])
                               if raw.get("built_in") else None),
                     storage=(str(raw["storage"])
                              if raw.get("storage") else None))


def _parse_form(raw: Any, at: str) -> FormRecipe:
    if not isinstance(raw, Mapping):
        raise FamilyRecipeError(f"{at}: форма — объект")
    kind_raw = str(raw.get("kind") or "")
    try:
        kind = FormKind(kind_raw)
    except ValueError:
        kind = FormKind.SWEPT_BLEND if kind_raw == "SweptBlend" else None  # type: ignore[assignment]
        if kind is None:
            raise FamilyRecipeError(f"{at}.kind: неизвестный род {kind_raw!r}")
    normal = raw.get("plane_normal")
    return FormRecipe(
        form_id=str(raw.get("id") or ""),
        kind=kind,
        is_solid=bool(raw.get("is_solid")),
        name=str(raw.get("name") or ""),
        plane_normal=_xyz(normal, f"{at}.plane_normal") if normal else None,
        plane_z_mm=(_num(raw["plane_z_mm"], f"{at}.plane_z_mm")
                    if raw.get("plane_z_mm") is not None else None),
        plane_origin_mm=(_xyz(raw["plane_origin_mm"], f"{at}.plane_origin_mm")
                         if raw.get("plane_origin_mm") else None),
        plane_x_dir=(_xyz(raw["plane_x_dir"], f"{at}.plane_x_dir")
                     if raw.get("plane_x_dir") else None),
        loops=_loops_from_payload(raw.get("loops"), f"{at}.loops"),
        top_loops=_loops_from_payload(raw.get("top_loops"), f"{at}.top_loops"),
        start_offset_mm=(_num(raw["start_offset_mm"], at)
                         if raw.get("start_offset_mm") is not None else None),
        end_offset_mm=(_num(raw["end_offset_mm"], at)
                       if raw.get("end_offset_mm") is not None else None),
        axis_start_mm=(_xyz(raw["axis_start_mm"], at)
                       if raw.get("axis_start_mm") else None),
        axis_end_mm=(_xyz(raw["axis_end_mm"], at)
                     if raw.get("axis_end_mm") else None),
        start_angle_deg=(_num(raw["start_angle_deg"], at)
                         if raw.get("start_angle_deg") is not None else None),
        end_angle_deg=(_num(raw["end_angle_deg"], at)
                       if raw.get("end_angle_deg") is not None else None),
        path_mm=tuple(_xyz(p, f"{at}.path_mm") for p in (raw.get("path_mm") or [])),
        profile_is_symbol=bool(raw.get("profile_is_symbol")),
        profile_symbol_name=(str(raw["profile_symbol_name"])
                             if raw.get("profile_symbol_name") else None),
        profile_family_name=(str(raw["profile_family_name"])
                             if raw.get("profile_family_name") else None),
        profile_x_offset_mm=(_num(raw["profile_x_offset_mm"], at)
                             if raw.get("profile_x_offset_mm") is not None else None),
        profile_y_offset_mm=(_num(raw["profile_y_offset_mm"], at)
                             if raw.get("profile_y_offset_mm") is not None else None),
        profile_angle_deg=(_num(raw["profile_angle_deg"], at)
                           if raw.get("profile_angle_deg") is not None else None),
        profile_flipped=(bool(raw["profile_flipped"])
                         if raw.get("profile_flipped") is not None else None),
        profile_symbol_source=_source(raw, "profile_symbol_source", at),
        profile_symbol_reason=(str(raw["profile_symbol_reason"])
                               if raw.get("profile_symbol_reason") else None),
        path3d_source=_source(raw, "path3d_source", at),
        path3d_kind=(str(raw["path3d_kind"]) if raw.get("path3d_kind") else None),
        path3d_count=(int(raw["path3d_count"])
                      if isinstance(raw.get("path3d_count"), int)
                      and not isinstance(raw.get("path3d_count"), bool) else None),
        path3d_reason=(str(raw["path3d_reason"])
                       if raw.get("path3d_reason") else None),
        measured_volume_mm3=(_num(raw["measured_volume_mm3"], at)
                             if raw.get("measured_volume_mm3") is not None else None),
        profile_reason=(str(raw["profile_reason"])
                        if raw.get("profile_reason") else None),
        driven_by=tuple(_parse_drive(d, f"{at}.driven_by[{k}]")
                        for k, d in enumerate(raw.get("driven_by") or [])),
        drives_read=isinstance(raw.get("driven_by"), list),
        assoc_reason=(str(raw["assoc_reason"])
                      if raw.get("assoc_reason") else None),
    )


# ── translating the recipe into operations ─────────────────────────────────

def _plane_is_horizontal(normal: tuple[float, float, float] | None) -> bool:
    if normal is None:
        return False
    nx, ny, nz = normal
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm <= 0.0:
        return False
    return abs(abs(nz / norm) - 1.0) <= PLANE_NORMAL_TOL


def _ring_area_mm2(points: list) -> float:
    """A ring's area from its vertices, sign discarded. Arcs are NOT taken
    into account."""
    total = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _arc_circle(a, b, bulge: float):
    """The arc `a→b` with its bulge -> (center, radius, start angle,
    sweep).

    🔴 `bulge` IS A DIMENSIONLESS QUANTITY `2s/c = tan(θ/4)`, NOT A SAGITTA
    IN MILLIMETERS. Spelled out because this was already tripped over
    during the 04.09.2026 recheck: for a quarter circle with r=10000 the
    sagitta is 2929 mm, while `bulge` is 0.414213562, and a probe that fed
    millimeters in here described an arc with a radius of 10,355,000 mm,
    and along with it "the predicate lies without bound". The unit is set
    by `_bulge_from_midpoint` (`2.0 * sagitta / chord`), which is the same
    one that goes into `shape["arcs"]`, and is pinned by the PRODUCER's
    measurement in `test_a_hole_inside_an_arc_is_not_a_second_body`.

    The circle is reconstructed by reversing the SAME arithmetic that
    `_bulge_from_midpoint` used to record it, not by a second formula:
    `n = (-dy, dx)/c` is the chord's left normal, `s = bulge*c/2`, the
    arc's midpoint `M = серединаХорды - n*s`. The center lies on the
    perpendicular bisector, `C = серединаХорды + n*k`, and from
    `|C-a| = |C-M| = R` follows `k = ((c/2)² - s²) / (2s)`, `R = |k + s|`.
    The sweep `θ = 4·atan(bulge)` carries a SIGN: that sign is the winding
    direction.
    """
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    chord = math.hypot(dx, dy)
    if chord <= 0.0 or bulge == 0.0:
        return None
    nx, ny = -dy / chord, dx / chord
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    sagitta = bulge * chord / 2.0
    k = ((chord / 2.0) ** 2 - sagitta * sagitta) / (2.0 * sagitta)
    centre = (mx + nx * k, my + ny * k)
    radius = abs(k + sagitta)
    if radius <= 0.0:
        return None
    return (centre, radius,
            math.atan2(ay - centre[1], ax - centre[0]),
            4.0 * math.atan(bulge))


def _arc_ray_crossings(point, a, b, bulge: float) -> int:
    """How many times an ARC crosses a rightward ray from the point. 0, 1,
    or 2.

    🔴 WHY A RAY, AND NOT "POLYGON PLUS SEGMENTS" (04.09.2026 recheck, and
    this is the SECOND edition of the RV-15 fix). The first computed it
    this way: even/odd by chords, then flipped the answer on every segment
    between the chord and the arc that covered the point. The identity
    holds for interiors and FAILS ON THE CHORD ITSELF: a point lying
    exactly on the chord sits on the boundary of both terms at once, and
    the XOR of two undefined values is undefined. A grid measurement caught
    15 such points on a circle made of TWO semicircles — there the chord IS
    A DIAMETER, meaning an entire segment in the middle of the solid lied.

    And this case is not rare — it is exactly ours: for two concentric
    circles taken from the same start angle, the inner ring's vertex LIES
    ON THE DIAMETER of the outer one — and `_group_rings` tests nesting
    precisely by the vertex. The hole would again become a second solid,
    meaning RV-15 would have survived its own fix.

    The fix is not a patch but removing the concept itself: the chord is an
    ARTIFACT of our own bookkeeping — a ring has two kinds of boundary,
    arcs and lines. The ray is tested against them directly, and then the
    chord exists under no condition at all.

    THE INTERSECTION RULE IS THE SAME AS FOR A LINE, AND THIS IS LOAD-
    BEARING: the arc is cut into pieces MONOTONIC IN y (the cut points are
    its own extrema, at angles ±90°), and each piece is tested with exactly
    `(y0 > y) != (y1 > y)` — the half-open rule of the neighboring branch,
    where a vertex level with the ray counts as "below". Two different
    rules on the same ring would give different parity at the vertex where
    a line meets an arc.
    """
    built = _arc_circle(a, b, bulge)
    if built is None:
        return 0
    (cx, cy), radius, start, sweep = built
    px, py = point
    height = py - cy
    if abs(height) >= radius:
        # The ray is above/below the circle or TOUCHES it: a tangency does
        # not change membership and does not count as a crossing.
        return 0
    offset = math.sqrt(radius * radius - height * height)
    # 🔴 THE ENDPOINTS ARE TAKEN FROM THE RING, NOT RECOMPUTED FROM THE
    # ANGLE, and this is not tidiness but a CONVERGENCE requirement. A
    # vertex shared by two edges must have the SAME y on both sides:
    # recomputing `cy + R·sin(angle)` gives ±1e-9, and on a ray passing
    # exactly through the vertex, the half-open rule diverges between
    # neighbors — parity breaks, and with it the answer. Bought by
    # measurement: the control case "ring r=5000 clearly inside r=10000"
    # became "2 solids, 0 holes" exactly this way.
    cuts = [(0.0, a[1]), (1.0, b[1])]
    for extremum in (math.pi / 2.0, -math.pi / 2.0):
        delta = (extremum - start) % (2.0 * math.pi)
        if sweep < 0.0:
            delta -= 2.0 * math.pi
        share = delta / sweep
        if 0.0 < share < 1.0:
            cuts.append((share, cy + radius * math.sin(extremum)))
    cuts.sort()
    crossings = 0
    for (left, y0), (right, y1) in zip(cuts, cuts[1:]):
        if (y0 > py) == (y1 > py):
            continue
        # A piece is monotonic in y, so it lies entirely on one side of the
        # vertical x = cx (the y-extrema sit exactly on it).
        middle = math.cos(start + sweep * (left + right) / 2.0)
        crossing_x = cx + (offset if middle >= 0.0 else -offset)
        if px < crossing_x:
            crossings += 1
    return crossings


def _point_in_ring(point, points: list, arcs=()) -> bool:
    """Whether a point is inside the ring — ACCOUNTING FOR ARCS, not just
    chords.

    🔴 CHORDS SENT A HOLE INTO A SEPARATE SOLID (RV-15, measured
    04.09.2026). The previous edition took the ring as a polyline through
    its vertices and CALLED this acceptable: "a discrepancy is only
    possible for a point within the arc's sagitta of the boundary." The
    sagitta of a circle made of four quarters is 29% of the radius, and
    here is the measurement that refutes the argument:

        ring r=5000 inside diamond r=10000          -> 1 solid, 1 hole  (correct)
        ring r=9000 inside CIRCLE r=10000, its first
        vertex OUTSIDE the chord diamond             -> 2 solids, 0 holes (wrong)

    In the second row a real HOLE became a SECOND SOLID: material appeared
    exactly where the family has emptiness, and the volume cross-check
    would only catch this by accident. The second half of the argument
    ("such a ring would be rejected by `validate_region` anyway") did not
    hold either: in the experiment the region was built with not a single
    diagnostic.

    HOW IT IS COMPUTED. A rightward ray, even/odd, tested against the
    ACTUAL boundary: a straight edge answers by the old rule
    `(y0 > y) != (y1 > y)`, an arc by its own crossings
    (:func:`_arc_ray_crossings`). There is NO chord in the computation at
    all, because there is none in the ring either: it was an artifact of
    our own arithmetic.

    🔴 HOW THIS DIFFERS FROM THE FIRST EDITION OF THE FIX, AND WHY A SECOND
    ONE WAS NEEDED. The first computed "polygon by chords XOR arc
    segments." The identity holds for interiors and is undefined ON THE
    CHORD ITSELF, and the chord is not the solid's edge: a grid found 15
    such points on a circle made of two semicircles, where the chord IS A
    DIAMETER. The case is not contrived: for concentric circles taken from
    the same start angle, the inner ring's vertex lands exactly on the
    outer one's diameter — and `_group_rings` tests nesting precisely by
    the vertex, meaning RV-15 would have survived its own fix.

    Arcs arrive in exactly the form `_regions_from_loops` puts them in:
    `{"edge": index, "bulge": sagitta}`, only for non-zero ones. `bulge` is
    DIMENSIONLESS (`2s/c`), see :func:`_arc_circle`.
    """
    x, y = point
    by_edge = {}
    for arc in arcs or ():
        edge = int(arc.get("edge", -1))
        bulge = float(arc.get("bulge") or 0.0)
        if bulge:
            by_edge[edge] = bulge
    crossings = 0
    count = len(points)
    for index in range(count):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % count]
        bulge = by_edge.get(index)
        if bulge is not None:
            crossings += _arc_ray_crossings(
                point, (x1, y1), (x2, y2), bulge)
            continue
        if (y1 > y) != (y2 > y):
            denominator = (y2 - y1) or 1e-12
            if x < (x2 - x1) * (y - y1) / denominator + x1:
                crossings += 1
    return crossings % 2 == 1


def _group_rings(shapes: list) -> tuple[list | None, Refusal | None]:
    """Rings -> groups of "outer + its holes". NESTING IS VERIFIED.

    🔴 WHY THIS FUNCTION EXISTS, BY THE 26.08.2026 MEASUREMENT. This used to
    read `region = {"outer": shapes[0]}`, `region["holes"] = shapes[1:]` —
    the first ring was DECLARED outer, all the rest holes, WITHOUT A SINGLE
    CHECK. A Revit sketch legitimately carries several SEPARATE closed
    rings: one shape gives several solids. They were declared holes of a
    nonexistent outer contour, and CONTOUR correctly answered "point
    outside the outer contour".

    A measurement over 16 refusals under the `contour_limit_exceeded` code:
    for THIRTEEN, the rings are separate, none nested; for three, there is
    a SINGLE ring and its own geometry is at fault. In other words it was
    not the language refusing but our own reader — and the code it refused
    under was named "contour limit exceeded", even though not one of its
    cases was a limit.

    🔴 THE "PICK THE OUTER ONE BY AREA" HYPOTHESIS WAS REFUTED BY
    EXPERIMENT (26.08 recon): it fixes 0 of 16. It fixes the choice of the
    outer ring among NESTED rings, while the real trouble was that there
    was no nesting at all.

    DEPTH IS COMPUTED, NOT GUESSED: a ring at depth 0 is the outer boundary
    of its own region, at depth 1 it is a hole of its single enclosing
    ring. Depth 2 and beyond is an island inside a hole: legal in Revit,
    inexpressible in a KIR region (exactly one outer ring plus holes), and
    this is a LANGUAGE REFUSAL with its own code, not a silent
    simplification.
    """
    points = [shape["points_mm"] for shape in shapes]
    # A ring's arcs travel TOGETHER with its vertices: without them,
    # nesting is computed by chords, and a hole inside a circle becomes a
    # second solid (RV-15).
    arcs = [shape.get("arcs") or () for shape in shapes]
    if len(shapes) == 1:
        return [(shapes[0], [])], None
    containers: list[list[int]] = []
    for index, own in enumerate(points):
        # ANY vertex of the ring is taken: rings do not intersect by
        # construction of the sketch, so the membership of one vertex
        # decides for the whole ring.
        holders = [other for other, poly in enumerate(points)
                   if other != index
                   and _point_in_ring(own[0], poly, arcs[other])]
        containers.append(holders)
    deep = [index for index, holders in enumerate(containers)
            if len(holders) > 1]
    if deep:
        return None, Refusal(
            RecipeRefusal.PROFILE_RINGS_NOT_A_REGION,
            f"колец {len(shapes)}, и {len(deep)} из них лежит глубже одного "
            f"уровня (остров внутри дыры). Регион CONTOUR — ровно одно внешнее "
            f"кольцо плюс дыры В НЁМ; вложенность глубже одного уровня язык не "
            f"выражает")
    groups: list[tuple] = []
    for index, holders in enumerate(containers):
        if holders:
            continue
        holes = [shapes[other] for other, own_holders in enumerate(containers)
                 if own_holders == [index]]
        groups.append((shapes[index], holes))
    if not groups:
        # There cannot be zero rings of depth 0 among non-intersecting
        # rings; if it happened, the nesting test has said something
        # impossible, and this cannot pass in silence.
        return None, Refusal(
            RecipeRefusal.PROFILE_RINGS_NOT_A_REGION,
            f"колец {len(shapes)}, и НИ ОДНО не является внешним: тест "
            f"вложенности дал круговое содержание, чего у замкнутых "
            f"непересекающихся колец не бывает")
    # The groups are ordered by DESCENDING area of the outer ring: this is
    # deterministic and does not depend on the order of rings in the
    # payload, so the golden files stay byte-stable.
    groups.sort(key=lambda pair: -_ring_area_mm2(pair[0]["points_mm"]))
    return groups, None


def _regions_from_loops(loops, oid: str) -> tuple[list | None, list | None, Refusal | None]:
    """Rings -> CONTOUR regions (one per solid), or a named refusal.

    The check goes THROUGH CONTOUR ITSELF (`validate_region`), not through
    our own copy of its rules: a second carrier of one law would silently
    diverge from the first — a named defect of this tree, bought on 20.08
    four times in one night.

    There can be SEVERAL regions: separate rings of one sketch are several
    solids of one Revit shape, see :func:`_group_rings`.
    """
    if not loops:
        return None, None, Refusal(RecipeRefusal.PROFILE_UNAVAILABLE,
                                   "профиль не содержит ни одного кольца")
    for loop in loops:
        for _p0, _p1, bulge in loop:
            if isinstance(bulge, str):
                return None, None, Refusal(
                    RecipeRefusal.CURVE_KIND_UNSUPPORTED,
                    f"сегмент рода {bulge!r}: CONTOUR говорит прямыми, дугами "
                    f"и сплайнами, других родов ребра нет")
    # 🔴 AN ARC TRAVELS AS AN ARC, NOT AS A CHORD. The first edition
    # computed `bulge` and THREW IT AWAY: the ring was assembled from
    # vertices alone, and every arc silently turned into a straight line.
    # This is a named shape of defect — "the value's kind was computed and
    # lost along the way" — and here it would have been especially costly:
    # a round column would have arrived square, the area would be off by a
    # quarter, and the volume cross-check would blame Revit.
    shapes = []
    for loop in loops:
        points = [[round(p0[0], 3), round(p0[1], 3)] for p0, _p1, _b in loop]
        shape: dict[str, Any] = {"shape": "poly", "points_mm": points}
        # `bulge` here and everywhere below is the DIMENSIONLESS
        # `2s/c = tan(θ/4)` from `_bulge_from_midpoint`, NOT a sagitta in
        # millimeters: both CONTOUR (`bulge_midpoint`) and `_point_in_ring`
        # read this same unit.
        arcs = [{"edge": index, "bulge": round(float(bulge), 9)}
                for index, (_p0, _p1, bulge) in enumerate(loop)
                if not isinstance(bulge, str) and abs(float(bulge)) > 0.0]
        if arcs:
            shape["arcs"] = arcs
        shapes.append(shape)
    groups, refusal = _group_rings(shapes)
    if refusal is not None:
        return None, None, refusal
    regions: list[dict] = []
    lowereds: list = []
    for index, (outer, holes) in enumerate(groups):
        region: dict[str, Any] = {"outer": outer}
        if holes:
            region["holes"] = holes
        diags: list = []
        # THE MEASUREMENT IS RETURNED TOGETHER WITH THE REGION DELIBERATELY:
        # computing the measures via a second call to `validate_region`
        # would mean keeping two carriers of one computation, and they
        # diverge silently — a shape of defect this tree paid for four
        # times in one night on 20.08.
        lowered = _contour.validate_region(
            region, None, oid if len(groups) == 1 else f"{oid}b{index + 1}",
            "profile", diags)
        if lowered is None:
            first = diags[0].message_ru if diags else "регион отвергнут CONTOUR"
            return None, None, Refusal(
                RecipeRefusal.PROFILE_REJECTED_BY_CONTOUR, str(first)[:240])
        regions.append(region)
        lowereds.append(lowered)
    return regions, lowereds, None


def form_to_op(form: FormRecipe, *, category: str, name: str) -> FormLift:
    """ONE shape -> an operation or a named refusal. Never both."""

    def refuse(code: RecipeRefusal, detail: str) -> FormLift:
        return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                        refusal=Refusal(code, detail),
                        measured_volume_mm3=form.measured_volume_mm3)

    if form.kind not in FORM_KIND_TO_OP:
        return refuse(RecipeRefusal.NO_OP_FOR_FORM_KIND,
                      f"рода {form.kind.value!r} нет в реестре: "
                      f"есть {', '.join(sorted(k.value for k in FORM_KIND_TO_OP))}")
    if not form.is_solid and form.kind is not FormKind.EXTRUSION:
        # 🔴 A VOID IS RAISED AS A PART, NOT AN OPERATION, AND THERE ARE
        # FOUR PART KINDS, WHILE A VOID COMES IN FIVE KINDS. A prism is
        # "contour plus height"; a sweep, a blend, and a revolve are not
        # that, and there is nothing to state them as a part with. The
        # refusal is NAMED with a separate code, not the old
        # `void_form_not_expressible`: it calls for a different fix (a
        # fifth part kind), and merging them would mean running one code
        # for two different jobs.
        return refuse(RecipeRefusal.VOID_KIND_NOT_A_PRISM,
                      f"вырез рода {form.kind.value!r}: часть булевой — "
                      f"призма над контуром (ops_boolean.PART_SHAPES), а "
                      f"{form.kind.value} контуром плюс высотой не задаётся")
    if form.profile_is_symbol:
        # 🔴 THE REFUSAL NAMES THE PROFILE, IF THE CAPTURE ASKED FOR IT
        # (26.08.2026). The refusal condition has NOT CHANGED by one
        # symbol — only what it now says has changed: it names WHAT is
        # missing, by name. A refusal that names a dependency with no name
        # sends the reader off to find it all over again.
        if form.profile_symbol_source == "api" and form.profile_family_name:
            where = (f"семейство {form.profile_family_name!r}, типоразмер "
                     f"{form.profile_symbol_name!r}")
        elif form.profile_symbol_source == KNOWLEDGE_NOT_ASKED:
            where = ("какое именно — НЕ СПРАШИВАЛИ: снимок снят до того, как "
                     "захват научился читать Sweep.ProfileSymbol")
        elif form.profile_symbol_source == "refused":
            where = (f"спросили, и вызов бросил: "
                     f"{form.profile_symbol_reason or 'причина не записана'}")
        else:
            where = "спросили, и Ревит вернул пустой профиль"
        return refuse(RecipeRefusal.SWEEP_PROFILE_IS_SYMBOL,
                      f"профиль протяжки задан загруженным семейством "
                      f"(Sweep.ProfileSymbol), а не эскизом — {where}: это "
                      f"ЗАВИСИМОСТЬ, и снимать её надо отдельным проходом")
    if form.profile_reason:
        return refuse(RecipeRefusal.PROFILE_UNAVAILABLE, form.profile_reason[:240])

    # 🔴 EVERY ONE OF THE FOUR KINDS HAS A PROFILE FRAME, AND IT IS NOW READ
    # FOR THREE OF THEM. Extrusion and blend place their profile ON THE
    # SKETCH PLANE — and that is what we read. SWEEP (21.08.2026) reads the
    # same plane, through the same call: its sketch is perpendicular to the
    # path, and the ORIGIN of this plane lies exactly on the path — this is
    # measured, not assumed (49 shapes of 49, distance 0). So the frame is
    # not "derived from the path" but READ, and the profile's offset from
    # the path is read along with it. Revolve still derives its frame from
    # the AXIS: its op reads the profile in axial coordinates, where u is
    # the radius.
    if form.kind is FormKind.REVOLUTION:
        plane, refusal = _axial_plane_from_form(form)
    else:
        plane, refusal = _plane_from_form(form)
    if refusal is not None:
        return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                        refusal=refusal,
                        measured_volume_mm3=form.measured_volume_mm3)
    assert plane is not None

    regions, lowereds, refusal = _regions_from_loops(
        _project_loops(form.loops, plane), form.form_id or "F")
    if refusal is not None:
        return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                        refusal=refusal,
                        measured_volume_mm3=form.measured_volume_mm3)

    # THE MEASURES ARE COMPUTED PER SOLID, AND IT IS THE SUM THAT IS
    # CROSS-CHECKED. Revit measures the volume of the WHOLE shape;
    # comparing a single solid's prediction against it would be checking a
    # part against the whole, and for a multi-solid shape it would fail an
    # honestly built one.
    measures_per_body = [_contour.region_measures(item) for item in lowereds]
    area_mm2 = sum(float(item.get("area_mm2") or 0.0)
                   for item in measures_per_body)
    single = len(regions) == 1
    form_key = form.form_id or "F"

    def body_base(index: int) -> dict:
        """The operation envelope FOR ONE SOLID. Its name and id carry the
        solid's number.

        🔴 THE ID MUST DIFFER: two ops with the same `id` in a program is a
        `KIR-P006` refusal (duplicate identifier), and the whole multi-solid
        shape would fail to build. The suffix is applied ONLY to a
        multi-solid shape, so for single-solid ones the `id` stays
        byte-for-byte the same and the golden files do not move.
        """
        if single:
            return {"op": FORM_KIND_TO_OP[form.kind], "id": form_key,
                    "category": category, "name": name}
        return {"op": FORM_KIND_TO_OP[form.kind],
                "id": f"{form_key}b{index + 1}",
                "category": category,
                "name": f"{name}#{index + 1}"[:64]}

    base = body_base(0)

    if form.kind is FormKind.EXTRUSION:
        if form.start_offset_mm is None or form.end_offset_mm is None:
            return refuse(RecipeRefusal.RECIPE_INCOMPLETE,
                          "у выдавливания не прочитаны StartOffset/EndOffset")
        height = abs(form.end_offset_mm - form.start_offset_mm)
        if not (_MIN_EXTENT_MM <= height <= _MAX_EXTENT_MM):
            return refuse(RecipeRefusal.HEIGHT_OUT_OF_BOUNDS,
                          f"высота {height:.1f} мм вне границ операции "
                          f"{_MIN_EXTENT_MM:g}..{_MAX_EXTENT_MM:g}")
        placement = _placement(plane, min(form.start_offset_mm,
                                          form.end_offset_mm))
        if not form.is_solid:
            # A VOID. The prism-part's fields are the SAME as an
            # extrusion's, and that is not a coincidence: `ops_boolean`
            # introduced its fourth part kind with exactly the same set
            # (`profile`, `height_mm`, one of `base_z_mm`/`plane`), because
            # it is the SAME geometry. So it is built here with the same
            # line, without a second branch for reading the recipe.
            built_parts = [dict(shape="prism", profile=item,
                                height_mm=round(height, 3), **placement)
                           for item in regions]
            # 🔴 THE PART IS CHECKED BY THE SAME VALIDATOR AS THE COMPILER
            # USES. A capturer that judged feasibility by its OWN copy of
            # the law would silently diverge from the compiler — and we
            # would get "captured" for a part the compiler rejects. This
            # same argument is already on record for the sweep
            # (`SW.frame_feasibility` is called by the same name as in
            # emission).
            from kir.ops_boolean import validate_parts as _validate_parts
            diags: list = []
            if _validate_parts(built_parts, form.form_id or "F", "parts", 0,
                               diags) is None:
                first = diags[0] if diags else None
                detail = str(first.message_ru if first else "часть отвергнута")
                # THE CODE IS CHOSEN BY FIELD, NOT ONE CODE FOR ALL
                # VALIDATOR REFUSALS. The contour and everything else call
                # for different fixes, and one code for two fixes is a
                # named defect of this tree.
                field = str(getattr(first, "field_name", "") or "")
                code = (RecipeRefusal.PROFILE_REJECTED_BY_CONTOUR
                        if ".profile" in field
                        else RecipeRefusal.VOID_PART_REJECTED)
                return refuse(code, detail[:240])
            return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                            refusal=None, parts=tuple(built_parts),
                            measured_volume_mm3=form.measured_volume_mm3)
        built_ops = [dict(body_base(index), profile=item,
                          height_mm=round(height, 3), **placement)
                     for index, item in enumerate(regions)]
        return FormLift(form_id=form.form_id, kind=form.kind,
                        ops=tuple(built_ops), refusal=None,
                        predicted_volume_mm3=area_mm2 * height,
                        measured_volume_mm3=form.measured_volume_mm3)

    if form.kind is FormKind.REVOLUTION:
        if form.axis_start_mm is None or form.axis_end_mm is None:
            return refuse(RecipeRefusal.RECIPE_INCOMPLETE,
                          "у вращения не прочитана ось")
        ax0, ax1 = form.axis_start_mm, form.axis_end_mm
        if (abs(ax1[0] - ax0[0]) > 1e-6) or (abs(ax1[1] - ax0[1]) > 1e-6):
            return refuse(RecipeRefusal.REVOLVE_AXIS_NOT_VERTICAL,
                          f"ось из [{ax0[0]:.1f},{ax0[1]:.1f},{ax0[2]:.1f}] в "
                          f"[{ax1[0]:.1f},{ax1[1]:.1f},{ax1[2]:.1f}]: "
                          f"axis_xy_mm — pt_xy, ось обязана быть вертикальной")
        if form.start_angle_deg is None or form.end_angle_deg is None:
            return refuse(RecipeRefusal.RECIPE_INCOMPLETE,
                          "у вращения не прочитаны углы")
        sweep = abs(form.end_angle_deg - form.start_angle_deg)
        if not (1.0 <= sweep <= 360.0):
            return refuse(RecipeRefusal.SWEEP_ANGLE_OUT_OF_BOUNDS,
                          f"угол {sweep:.3f}° вне границ 1..360")
        # 🔴 THE SECTOR'S START IS NOT SILENTLY DISCARDED (RH-02,
        # 04.09.2026). This used to hold ONE difference, and
        # `start_angle_deg` went nowhere from there: 0°→90° and 90°→180°
        # produced byte-for-byte the same program. A full revolution is the
        # ONE exception, and it is not a concession: at 360° the sector's
        # start is unobservable, the solid does not depend on it at all.
        start = float(form.start_angle_deg) % 360.0
        if sweep < 360.0 - _REVOLVE_ANGLE_TOL_DEG and not (
                start <= _REVOLVE_ANGLE_TOL_DEG
                or start >= 360.0 - _REVOLVE_ANGLE_TOL_DEG):
            return refuse(
                RecipeRefusal.REVOLVE_START_ANGLE_NOT_EXPRESSIBLE,
                f"сектор начинается с {form.start_angle_deg:.3f}° и "
                f"кончается {form.end_angle_deg:.3f}°, а "
                f"`create_solid_revolve` отсчитывает поворот ВСЕГДА от "
                f"мировой оси +X: слота под начальный угол у операции нет. "
                f"Промолчать значило бы построить те же {sweep:.3f}° от "
                f"нуля — тело в другом месте, и объёмная сверка этого не "
                f"заметит")
        built_ops = [dict(body_base(index), profile=item,
                          axis_xy_mm=[round(ax0[0], 3), round(ax0[1], 3)],
                          sweep_deg=round(sweep, 6))
                     for index, item in enumerate(regions)]
        # 🔴 THE FORMULA IS TAKEN FROM THE EMITTER, NOT REWRITTEN
        # (21.08.2026). `emit_solid_revolve` computes `V = θ·M`, where M is
        # the profile's first moment IN CONTOUR COORDINATES, because for
        # this op the contour's x IS the radius from the axis (as declared
        # in `ops_solid`, and as Revit itself requires).
        #
        # THIS USED TO READ `radius = abs(centroid_x - ax0[0])` — meaning
        # the RADIUS WAS SUBTRACTED A SECOND TIME, from a value already
        # measured from the axis. With the axis at zero, both formulas
        # agree numerically, so the discrepancy was invisible; with the
        # axis at x=500, the volume came out HALF what it should be. The
        # neighboring test was written PRECISELY AGAINST this degenerate
        # case — and "proved" the wrong formula, because its fixture fed
        # the profile in WORLD coordinates, not axial ones. The control was
        # designed against the wrong law.
        moment = sum(float(item.get("moment_x_mm3") or 0.0)
                     for item in measures_per_body)
        predicted = math.radians(sweep) * moment
        return FormLift(form_id=form.form_id, kind=form.kind,
                        ops=tuple(built_ops),
                        refusal=None, predicted_volume_mm3=predicted,
                        measured_volume_mm3=form.measured_volume_mm3)

    if form.kind is FormKind.SWEEP:
        # 🔴 A MULTI-SOLID SWEEP IS NOT RAISED, AND THIS IS A NAMED
        # BOUNDARY, NOT A FORGOTTEN BRANCH. The profile's attachment to the
        # path (`_sweep_attachment`) is solved FOR ONE ring: with several
        # separate rings, the attachment point is different for each one,
        # while `create_solid_sweep` takes a single `anchor_uv_mm` per
        # operation. Untangling this needs an attachment measurement per
        # solid — work with its own witness — and doing it by guesswork
        # would mean placing the profile in the wrong frame: the solid
        # would come out plausible and in the wrong place, and the volume
        # cross-check WILL NOT CATCH THIS (volume is invariant to motion).
        if len(regions) > 1:
            return refuse(
                RecipeRefusal.PROFILE_RINGS_NOT_A_REGION,
                f"протяжка с {len(regions)} раздельными кольцами профиля: "
                f"точка привязки к пути своя у каждого тела, а "
                f"create_solid_sweep берёт один anchor_uv_mm на операцию")
        return _sweep_lift(form, plane, regions[0], lowereds[0], base)

    # BLEND
    if form.start_offset_mm is None or form.end_offset_mm is None:
        return refuse(RecipeRefusal.RECIPE_INCOMPLETE,
                      "у бленда не прочитаны BottomOffset/TopOffset")
    height = abs(form.end_offset_mm - form.start_offset_mm)
    if not (_MIN_EXTENT_MM <= height <= _MAX_EXTENT_MM):
        return refuse(RecipeRefusal.HEIGHT_OUT_OF_BOUNDS,
                      f"высота {height:.1f} мм вне границ операции 100..500000")
    # 🔴 THE TOP PROFILE IS ITS OWN, AND THIS IS A FIX FOR A SILENT DEFECT
    # (21.08.2026). The previous edition set `profile_top=region`, that is,
    # it substituted the BOTTOM profile a second time. The reading C# had
    # been putting `top_loops` into the payload from day one — the evidence
    # was in hand, and only the parser was throwing it away. A blend with
    # identical ends is a PRISM: every transition of the cross-section
    # would arrive straightened, and the volume cross-check does not catch
    # this at all (for a blend, volume is NOT PREDICTED,
    # `predicted_volume_mm3=None`). The same named class of defect as the
    # arc-chord one two commits earlier.
    #
    # 🔴 A BLEND IS NOT RAISED AS MULTI-SOLID — THE PAIRING OF ENDS IS NOT
    # DERIVED. A blend has TWO profiles, and with N bottom rings and M top
    # ones, the relation "this bottom transitions into this top" is absent
    # from the recipe, just like the relation "this void cuts this shape"
    # is. Matching them by area or by order would mean GUESSING, and here a
    # guess is invisible: a blend's volume is not predicted at all
    # (`predicted_volume_mm3=None`), and a mismatched pair of ends would be
    # caught by nothing.
    if len(regions) > 1:
        return refuse(
            RecipeRefusal.PROFILE_RINGS_NOT_A_REGION,
            f"бленд с {len(regions)} раздельными кольцами нижнего профиля: "
            f"отношения «этот низ переходит в этот верх» в рецепте нет, а "
            f"объём бленда не предсказывается — перепутанную пару торцов не "
            f"поймал бы ни один свидетель")
    region = regions[0]
    region_top = region
    if form.top_loops:
        regions_top, lowereds_top, refusal_top = _regions_from_loops(
            _project_loops(form.top_loops, plane),
            (form.form_id or "F") + "T")
        if refusal_top is not None:
            return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                            refusal=refusal_top,
                            measured_volume_mm3=form.measured_volume_mm3)
        if len(regions_top) > 1:
            return refuse(
                RecipeRefusal.PROFILE_RINGS_NOT_A_REGION,
                f"бленд с {len(regions_top)} раздельными кольцами ВЕРХНЕГО "
                f"профиля: довод тот же, что у нижнего — пара торцов не "
                f"выводится")
        region_top = regions_top[0]
    op = dict(base, profile=region, profile_top=region_top,
              height_mm=round(height, 3),
              **_placement(plane, min(form.start_offset_mm, form.end_offset_mm)))
    # 🔴 A BLEND'S VOLUME IS NOT PREDICTED: Revit chooses the lateral
    # surface between the profiles and does not document it. Here it is
    # `None`, not a number — the same discipline as in `solid_emit`: an
    # uncomputed value is not printed as zero.
    return FormLift(form_id=form.form_id, kind=form.kind, ops=(op,),
                    refusal=None, predicted_volume_mm3=None,
                    measured_volume_mm3=form.measured_volume_mm3)


#: How far a sweep's sketch-plane origin may stray from the path, mm.
#: 🔴 MEASURED, NOT ASSIGNED: across 49 family sweeps of a real building
#: for which the path was readable, the distance from `Plane.Origin` to the
#: path polyline was EXACTLY ZERO for all 49 (not "small" — zero at double
#: precision). The threshold is set at 0.001 mm — the same order as the
#: rounding of the coordinates themselves in the payload — and it can only
#: fail when the plane that was read has nothing to do with this path.
PATH_ATTACHMENT_TOL_MM = 0.001


def _sweep_attachment(form: "FormRecipe", plane: dict) -> tuple:
    """THE PROFILE'S ATTACHMENT SEGMENT and the path, oriented TO MATCH THE
    SKETCH FRAME.

    Returns `(points, att, ref_dir, refusal)`.

    WHAT IS DECIDED HERE, AND WHY IT IS NOT GUESSWORK.

    Revit places a sweep's profile in a plane PERPENDICULAR to the path at
    the attachment point, and this plane's `Plane.Origin` lies ON the
    path. Both facts are measured, not assumed: for 49 of 49 shapes a
    segment was found whose direction is collinear with the sketch normal
    (|cos| = 1.000000), and `Plane.Origin` lay on that segment at zero
    distance. The attachment parameter for ALL 46 shapes with a readable
    contour turned out to be exactly 0.5 — Revit places the profile at the
    MIDPOINT of the segment, not at its start.

    🔴 THE ATTACHMENT SEGMENT MUST BE FOUND, NOT TAKEN AS THE FIRST ONE, AND
    HERE IS THE COST OF GETTING IT WRONG. For a U-shaped path, segments 0
    and 2 are antiparallel, so the sketch normal is collinear with BOTH.
    Taking whichever comes first gives a frame mirrored relative to the
    path: the profile's offset flips sign, and with it the sign of the
    miter correction. Measured: choosing "the first match" made the volume
    agree for 20 of 34 shapes, choosing "the one the plane's origin lies
    on" made it agree for 34 of 34. The error was visible ONLY through
    volume: the solid stayed plausible.

    THE PATH IS REVERSED IF THE SEGMENT RUNS AGAINST THE NORMAL. This is
    not a fudge: our op reads the profile's (u, v) in the frame
    `(e1, e2)`, while the sketch's frame is `(XVec, YVec)`, where
    `YVec = Normal × XVec`. They agree only when the segment's direction
    matches the normal; otherwise `v` would come out with the opposite
    sign, meaning the profile would arrive MIRRORED. Reversing the polyline
    does not change the geometry.
    """
    from kir import plane as PL
    from kir import sweep_path as SW

    points = [tuple(float(c) for c in pt) for pt in form.path_mm]
    if len(points) < 2:
        # 🔴 THIS TEXT WAS TRUE BEFORE 26.08.2026 AND WOULD HAVE BECOME A
        # LIE. It used to say "the reading C# does not yet ask for Path3d:
        # there is nothing to tell these two cases apart with." Now it
        # asks — and the refusal must say WHAT it heard. The refusal
        # condition is unchanged: a path shorter than two points. What
        # changed is the answer to "why", not to "whether to refuse".
        if form.path3d_source == "api":
            heard = (f"Path3d СПРОШЕН и вернул {form.path3d_kind or '?'} на "
                     f"{form.path3d_count} кривых: путь задан трёхмерной "
                     f"траекторией, а не эскизом, и языку он пока не выразим")
        elif form.path3d_source == "absent":
            heard = ("Path3d СПРОШЕН и пуст — значит пути нет ни эскизом, ни "
                     "трёхмерной траекторией")
        elif form.path3d_source == "refused":
            heard = (f"Path3d спрошен, и вызов бросил: "
                     f"{form.path3d_reason or 'причина не записана'}")
        else:
            heard = ("Path3d НЕ СПРАШИВАЛИ: снимок снят до того, как захват "
                     "научился, и отличить 3D-путь от пустого эскиза нечем")
        return None, None, None, Refusal(
            RecipeRefusal.SWEEP_PATH_UNAVAILABLE,
            f"путь протяжки прочитан {len(points)} точками: Sketch пути пуст "
            f"либо его нет. {heard}")

    origin, x_dir, _y, normal = PL.frame(plane)

    def dot(a, b):
        return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]

    def unit(v):
        length = math.sqrt(dot(v, v))
        return tuple(c / length for c in v)

    dirs = SW.path_directions(points)
    att = None
    for index in range(len(dirs)):
        if abs(abs(dot(dirs[index], normal)) - 1.0) > PLANE_NORMAL_TOL * 1e3:
            continue
        a, b = points[index], points[index + 1]
        seg = tuple(b[k] - a[k] for k in range(3))
        span = dot(seg, seg)
        t = dot(tuple(origin[k] - a[k] for k in range(3)), seg) / span
        if not (-1e-9 <= t <= 1.0 + 1e-9):
            continue
        foot = tuple(a[k] + t * seg[k] for k in range(3))
        if math.dist(origin, foot) <= PATH_ATTACHMENT_TOL_MM:
            att = index
            break
    if att is None:
        best = max((abs(dot(d, normal)) for d in dirs), default=0.0)
        return None, None, None, Refusal(
            RecipeRefusal.PROFILE_FRAME_NOT_DERIVED,
            f"начало эскиза профиля не лежит ни на одном звене пути, "
            f"перпендикулярном этому эскизу: лучшее совпадение нормали со "
            f"звеном |cos| = {best:.6f} при требуемой единице, звеньев "
            f"{len(dirs)}. Рамку профиля к пути привязать не к чему")

    if dot(dirs[att], normal) < 0.0:
        points = list(reversed(points))
        att = len(dirs) - 1 - att
        dirs = SW.path_directions(points)

    # THE REFERENCE DIRECTION IS DERIVED, NOT CHOSEN: `e1 = unit(T × ref)`,
    # and `ref = XVec × T` gives `e1 = XVec` identically (XVec ⟂ T by
    # construction of the profile plane). In other words, the profile's
    # rotation about the path is READ from Revit, not "the default world
    # vertical" that the previous edition of this branch used.
    ref = SW._cross(x_dir, dirs[att])
    if math.sqrt(dot(ref, ref)) < 1e-9:
        return None, None, None, Refusal(
            RecipeRefusal.PROFILE_FRAME_NOT_DERIVED,
            f"ось +u эскиза коллинеарна ходу звена привязки "
            f"[{x_dir[0]:.4f}, {x_dir[1]:.4f}, {x_dir[2]:.4f}]: опорного "
            f"направления из них не построить")
    ref = unit(ref)
    if SW.frames_along(points, ref) is None:
        return None, None, None, Refusal(
            RecipeRefusal.PROFILE_FRAME_NOT_DERIVED,
            f"опорное направление [{ref[0]:.4f}, {ref[1]:.4f}, {ref[2]:.4f}], "
            f"выведенное из рамки эскиза, коллинеарно какому-то звену пути: "
            f"рамки профиля на этом звене не существует. Путь непланарен, и "
            f"правило разворота Revit на нём НЕ ВЫВЕДЕНО")
    return points, att, ref, None


def _sweep_lift(form: "FormRecipe", plane: dict, region: dict,
                lowered: dict, base: dict) -> "FormLift":
    """A FAMILY SWEEP -> `create_solid_sweep`, with the profile's offset.

    Before 21.08.2026 this held an unconditional refusal naming THREE
    missing things. Two of them turned out to be readable (rotation —
    `Plane.XVec`; offset — `Plane.Origin` on the path), the third — the
    rotation rule on a composite path — is closed by that same
    `Plane.XVec`: it sets the frame at the attachment segment, and
    `fixed_reference` propagates it to the remaining segments by a law, not
    by a choice.
    """
    from kir import sweep_path as SW
    from kir.authoring_validation import _MIN_SEGMENT_MM

    def refuse(code: RecipeRefusal, detail: str) -> "FormLift":
        return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                        refusal=Refusal(code, detail),
                        measured_volume_mm3=form.measured_volume_mm3)

    if form.plane_origin_mm is None or form.plane_x_dir is None:
        return refuse(
            RecipeRefusal.PROFILE_FRAME_NOT_DERIVED,
            "рамка эскиза профиля не прочитана: в payload нет Plane.Origin "
            "либо Plane.XVec. У протяжки её вывести из колец НЕЛЬЗЯ — начало "
            "рамки здесь несёт ТОЧКУ ПУТИ, а не калибровку, и любое другое "
            "начало сдвинуло бы профиль поперёк пути молча")

    points, att, ref, refusal = _sweep_attachment(form, plane)
    if refusal is not None:
        return FormLift(form_id=form.form_id, kind=form.kind, ops=(),
                        refusal=refusal,
                        measured_volume_mm3=form.measured_volume_mm3)

    from kir.geom import MAX_PATH_POINTS

    if len(points) > MAX_PATH_POINTS:
        return refuse(RecipeRefusal.SWEEP_PATH_NOT_EXPRESSIBLE,
                      f"путь из {len(points)} точек, предел рода path3 — "
                      f"{MAX_PATH_POINTS}")
    short = next((k for k in range(len(points) - 1)
                  if math.dist(points[k], points[k + 1]) < _MIN_SEGMENT_MM), None)
    if short is not None:
        return refuse(
            RecipeRefusal.SWEEP_PATH_NOT_EXPRESSIBLE,
            f"звено {short}-{short + 1} длиной "
            f"{math.dist(points[short], points[short + 1]):.4f} мм короче "
            f"{_MIN_SEGMENT_MM:g} мм — Revit такую кривую не строит")

    # THE ATTACHMENT POINT IN THE PROFILE'S COORDINATES IS EXACTLY THE
    # FRAME'S ORIGIN, that is (0, 0): the rings are converted to (u, v)
    # FROM IT (`_project_loops`), and it itself lies on the path. There is
    # nothing to compute here, and that is the main property of the chosen
    # representation: the capturer does not compute the offset, it READS
    # it.
    anchor = (0.0, 0.0)
    cx, cy, area_mm2 = SW.profile_centroid(lowered)
    offset = (cx - anchor[0], cy - anchor[1])
    # THE CHECK IS THE SAME AS EMISSION'S, AND CALLED BY THE SAME NAME: a
    # capturer that asked about feasibility using its own copy of the law
    # would silently diverge from the compiler — and we would get
    # "captured" for a shape that does not compile.
    bad = SW.frame_feasibility(points, lowered, anchor, ref)
    if bad is not None:
        return refuse(RecipeRefusal.SWEEP_PATH_NOT_EXPRESSIBLE,
                      f"ус в узле пути не строится: {bad}"[:240])
    correction = SW.miter_correction_mm(points, ref, offset)
    if correction is None:
        return refuse(RecipeRefusal.PROFILE_FRAME_NOT_DERIVED,
                      "поправка уса не вычислилась: в узле пути разворот на "
                      "месте либо рамки на звене нет")

    op = dict(base, variety="fixed_reference", profile=region,
              path_mm=[[round(c, 3) for c in pt] for pt in points],
              ref_dir=[round(c, 9) for c in ref],
              anchor_uv_mm=[round(anchor[0], 3), round(anchor[1], 3)])
    return FormLift(
        form_id=form.form_id, kind=form.kind, ops=(op,), refusal=None,
        predicted_volume_mm3=SW.swept_volume_mm3(area_mm2, points, correction),
        measured_volume_mm3=form.measured_volume_mm3)


def _placement(plane: dict, offset_along_normal: float) -> dict:
    """How to state the profile's position: `base_z_mm` or `plane`. Exactly
    one.

    🔴 THE SHAPE'S OFFSET IS MEASURED FROM THE SKETCH PLANE, NOT FROM THE
    FAMILY'S ORIGIN, AND BEFORE 21.08 THIS WAS LOST SILENTLY. This tree's
    API database (`data/revit_api_db.json`, class `Extrusion`) says
    verbatim: "The direction of the offset is based on the normal of the
    extrusion's sketch plane," and the family editor's own recipe, in the
    same place, says: "end is the signed DEPTH of the extrusion FROM THE
    SKETCH PLANE (StartOffset defaults to 0)." The previous edition wrote
    `base_z_mm = min(start, end)` and THREW AWAY the plane's elevation.

    WHAT THIS COST, IN NUMBERS FROM A REAL BUILDING: of 153 horizontal
    sketches, **72 do not sit at zero** — ranging from -200 to +8500 mm. So
    for 72 of 153 shapes the solid drifted vertically by the sketch's
    entire elevation, and not a single witness caught it: volume, end-cap
    area, and profile area are all invariant to a shift, and the bounding-
    box witness compared against the SAME shifted reference.

    THE DEGENERATE CASE PRINTS THE OLD WAY. A horizontal plane with its
    origin at plan zero and +u along +X is exactly `base_z_mm`, and it
    travels as that: the program comes out identical to before the wave,
    and `plane` appears exactly where nothing else can say it.
    """
    from kir import plane as PL

    o, _x, _y, n = PL.frame(plane)
    moved = {"origin_mm": [round(o[k] + offset_along_normal * n[k], 3)
                           for k in range(3)],
             "normal": list(plane["normal"]),
             "x_dir": list(plane["x_dir"])}
    if PL.is_horizontal(moved):
        return {"base_z_mm": round(moved["origin_mm"][2], 3)}
    return {"plane": moved}


def recipe_to_ops(recipe: FamilyRecipe, *,
                  category: str = "generic_model") -> tuple[FormLift, ...]:
    """A family -> the translations of all its shapes, one per shape."""
    lifts: list[FormLift] = []
    for index, form in enumerate(recipe.forms):
        name = f"{recipe.family_name}#{index + 1}"[:64] or f"форма {index + 1}"
        lifts.append(form_to_op(form, category=category, name=name))
    return tuple(lifts)


# ── ASSEMBLING THE FAMILY PROGRAM ────────────────────────────────────────────
#
# 🔴 A SHAPE'S EXPRESSIBILITY AND ASSEMBLING THE PROGRAM ARE TWO DIFFERENT
# QUESTIONS, AND BEFORE 21.08.2026 ONLY THE FIRST EXISTED HERE. While a void
# was refused outright, the difference was invisible: an unexpressed shape
# meant no program either. As soon as a void became part of a boolean, the
# two questions diverged, and the second turned out to be STRICTER than the
# first.
#
# THE 21.08.2026 MEASUREMENT over 110 families of a real building (110
# families, 82 with shapes, 283 shapes, 64 voids):
#
#     voids per family           1 -> 11 families · 2 -> 16 · 3 -> 3 · 4 -> 3
#     solids in a family with a void   0 -> 4 · exactly 1 -> 5 · more than 1 -> 24
#
# AND FROM THIS, THE MAIN NUMBER OF THIS BLOCK: for 24 of 33 families, solid
# shapes number MORE THAN ONE, while a `Sweep`/`Blend`/`Revolution` can never
# be a prism base at all.
class RecipeProgramBlocker(str, Enum):
    """WHY expressed shapes failed to assemble into a program. A closed
    dictionary.

    Deliberately separate from :class:`RecipeRefusal`: there the reason is
    about the SHAPE ("the language cannot state it"), here it is about
    ASSEMBLY ("the language states it, but there is nothing to put it into
    the program with"). Merging them would mean running one code for two
    different jobs, and the very first summary would stop answering what
    to fix.
    """

    #: The family has NOT A SINGLE solid shape — meaning the void cuts the
    #: HOST, not its own family. Measured: 4 of 33 families (three window
    #: ones and «Стена_Полый элемент»), that is, an opening in a wall
    #: rather than a shape of the product. There is a DIFFERENT op in the
    #: registry for this — `create_opening`; it is fixed by reading the
    #: «Вырезает при загрузке» parameter, which is absent from the
    #: payload.
    VOID_CUTS_HOST = "voids_cut_the_host_not_this_family"
    #: There is MORE THAN ONE solid shape, and which one the void cuts is
    #: not stated in the payload (measured: a shape has 20 fields, and a
    #: "cuts" relation is NOT among them). Only ONE solid can be a
    #: boolean's base, and choosing it on the author's behalf would mean
    #: building the hole in the wrong place. Measured: 24 of 33 families.
    #:
    #: 🔴 WHY NOT "SUBTRACT THE VOID FROM EVERY SOLID". Set-theoretically
    #: this is EXACT: (A ∪ B) \\ V = (A\\V) ∪ (B\\V), and the family program
    #: already builds every shape as a separate DirectShape anyway.
    #: Rejected by MEASUREMENT, not by taste: `create_solid_boolean` REFUSES
    #: by name (`KIR-B101`) when the solids do not intersect — and for
    #: «М_Кухонный гарнитур» (8 solids, 1 void), seven of eight ops would
    #: refuse at runtime. A program that refuses by construction is worse
    #: than none: its refusal reads as Revit being broken.
    VOID_TARGET_AMBIGUOUS = "void_target_ambiguous"
    #: There is exactly one solid shape, but it is not an extrusion: a
    #: boolean's base is a PRISM (contour plus height), and a sweep, blend,
    #: or revolve is not one. Fixed by a second BASE kind, not by a field.
    VOID_BASE_NOT_A_PRISM = "void_base_is_not_a_prism"
    #: At least one family shape is not expressed at all — there is no
    #: program for this reason, and calling it an assembly blocker would be
    #: a substitution.
    FORM_NOT_EXPRESSIBLE = "some_form_is_not_expressible"
    #: There are more voids than the boolean takes as parts at once.
    TOO_MANY_VOIDS = "too_many_voids_for_one_boolean"


@dataclass(frozen=True, slots=True)
class RecipeProgram:
    """A family program, or named assembly blockers. Never silence."""

    family_name: str
    ops: tuple[dict[str, Any], ...]
    blockers: tuple[tuple[str, str], ...]

    @property
    def complete(self) -> bool:
        """Whether the program assembled COMPLETELY — that is, with not a
        single blocker."""
        return not self.blockers


def recipe_to_program(recipe: FamilyRecipe, *,
                      category: str = "generic_model",
                      lifts: Sequence[FormLift] | None = None) -> RecipeProgram:
    """A family -> a PROGRAM with voids already subtracted, or blockers.

    🔴 A VOID NEVER BECOMES AN ELEMENT UNDER ANY CONDITIONS. It enters the
    program ONLY as part of `create_solid_boolean`, and that is precisely
    why assembly is only possible where the base can be named
    unambiguously.
    """
    from kir.ops_boolean import BOOLEAN_PARTS_MAX

    if lifts is None:
        lifts = recipe_to_ops(recipe, category=category)
    blockers: list[tuple[str, str]] = []
    solid_lifts = [lift for lift, form in zip(lifts, recipe.forms)
                   if form.is_solid]
    void_lifts = [lift for lift, form in zip(lifts, recipe.forms)
                  if not form.is_solid]

    for lift in lifts:
        if lift.refusal is not None:
            blockers.append((RecipeProgramBlocker.FORM_NOT_EXPRESSIBLE.value,
                             f"форма {lift.form_id or '?'} "
                             f"({lift.kind.value}): "
                             f"{lift.refusal.code.value}"))

    # SOLIDS, NOT LIFTS. One Revit shape can be several solids (separate
    # sketch rings), and since 26.08.2026 the lift carries all of them.
    ops = [item for lift in solid_lifts for item in lift.ops]
    solid_bodies = len(ops)

    if not void_lifts:
        # A FAMILY WITH NO VOIDS — the prior behavior, down to the bit.
        return RecipeProgram(family_name=recipe.family_name, ops=tuple(ops),
                             blockers=tuple(blockers))

    parts = [item for lift in void_lifts for item in lift.parts]
    if sum(1 for lift in void_lifts if lift.parts) != len(void_lifts):
        # Some voids are not expressed: the rest CANNOT be subtracted — the
        # result would be a solid with one hole present and another
        # missing, and it would look legitimate. The blocker is already
        # named above, by shape.
        return RecipeProgram(family_name=recipe.family_name, ops=(),
                             blockers=tuple(blockers))

    def blocked(code: "RecipeProgramBlocker", detail: str) -> RecipeProgram:
        return RecipeProgram(
            family_name=recipe.family_name, ops=(),
            blockers=tuple(blockers) + ((code.value, detail),))

    if not solid_lifts:
        return blocked(RecipeProgramBlocker.VOID_CUTS_HOST,
                       f"{len(void_lifts)} вырез(ов) и НИ ОДНОЙ сплошной "
                       f"формы: этот вырез режет ХОЗЯИНА (проём в стене), а "
                       f"не своё семейство. Оп для этого другой — "
                       f"create_opening")
    # 🔴 SOLIDS ARE COUNTED, NOT SHAPES, AND THIS IS A CORRECTION, NOT A
    # TIGHTENING. A boolean's base is ONE solid; a shape made of two
    # separate rings yields TWO, and there is just as little to address a
    # void between them with as between two shapes. Before 26.08.2026, such
    # a shape simply never reached this check: the ring reader rejected it
    # first. Having lifted that refusal, we must count honestly — otherwise
    # the void would silently end up in the first solid.
    if solid_bodies > 1:
        return blocked(RecipeProgramBlocker.VOID_TARGET_AMBIGUOUS,
                       f"сплошных ТЕЛ {solid_bodies} (форм "
                       f"{len(solid_lifts)}), вырезов {len(void_lifts)}, а "
                       f"отношения «этот вырез режет вот это тело» в рецепте "
                       f"НЕТ (у формы 20 полей, такого среди них нет). "
                       f"База булевой — одно тело")
    base_lift = solid_lifts[0]
    if not base_lift.ops:
        return RecipeProgram(family_name=recipe.family_name, ops=(),
                             blockers=tuple(blockers))
    if base_lift.ops[0].get("op") != "create_solid_extrusion":
        return blocked(RecipeProgramBlocker.VOID_BASE_NOT_A_PRISM,
                       f"единственная сплошная форма — "
                       f"{base_lift.kind.value}, а база булевой это призма "
                       f"(контур плюс высота)")
    if len(parts) > BOOLEAN_PARTS_MAX - 1:
        return blocked(RecipeProgramBlocker.TOO_MANY_VOIDS,
                       f"вырезов {len(parts)}, булева берёт "
                       f"{BOOLEAN_PARTS_MAX - 1} частей за раз")

    base = base_lift.ops[0]
    boolean = {"op": "create_solid_boolean", "id": base["id"],
               "operation": "difference", "profile": base["profile"],
               "height_mm": base["height_mm"], "parts": list(parts),
               "category": base["category"], "name": base["name"]}
    # THE BASE'S POSITION CARRIES OVER AS IS: a boolean has the same two
    # mutually exclusive fields as an extrusion, and that is exactly why
    # there is not a single recomputation here — it would be a second
    # carrier of the placement law.
    for key in ("base_z_mm", "plane"):
        if key in base:
            boolean[key] = base[key]
    return RecipeProgram(family_name=recipe.family_name, ops=(boolean,),
                         blockers=tuple(blockers))

def lift_summary(lifts: Sequence[FormLift]) -> dict[str, Any]:
    """A summary meant to be READ BY A HUMAN. Silences are printed on equal
    footing with findings."""
    total = len(lifts)
    lifted = sum(1 for lift in lifts if lift.lifted)
    # 🔴 AS AN OPERATION AND AS A PART ARE TWO DIFFERENT NUMBERS, AND BOTH
    # ARE PRINTED. A shape raised as a PART is expressed by the language but
    # will never become an element, and enters the program only inside a
    # boolean. A single combined number would hide exactly this
    # distinction where it matters: `recipe_to_program` does not assemble
    # for every family whose shapes are all expressed.
    as_op = sum(1 for lift in lifts if lift.ops)
    as_part = sum(1 for lift in lifts if lift.parts)
    by_refusal: dict[str, int] = {}
    for lift in lifts:
        if lift.refusal is not None:
            key = lift.refusal.code.value
            by_refusal[key] = by_refusal.get(key, 0) + 1
    verdicts: dict[str, int] = {}
    for lift in lifts:
        if lift.lifted:
            verdicts[lift.volume_verdict] = verdicts.get(lift.volume_verdict, 0) + 1
    return {
        "forms_total": total,
        "lifted": lifted,
        "lifted_as_op": as_op,
        "lifted_as_boolean_part": as_part,
        "refused": total - lifted,
        "lifted_pct": round(100.0 * lifted / total, 2) if total else 0.0,
        "refusals_by_code": dict(sorted(by_refusal.items())),
        "volume_verdicts": dict(sorted(verdicts.items())),
    }


# ── the reading C# ────────────────────────────────────────────────────────
#
# 🔴 THE PROFILE IS READ ONLY THROUGH `Sketch.Profile`, AND THIS IS A
# DECISION. Blend has `BottomProfile`/`TopProfile`, Sweep has its own pair,
# but their TYPES are not held by the surface index (it holds member names
# and METHOD signatures, and these are properties). Guessing between
# `CurveArray` and `CurveArrArray` means shipping a CS1503 into a live run.
# `Sketch.Profile` is confirmed 6/6 AND typed unambiguously, and Sketch
# exists on EVERY ONE of the four kinds:
#
#     Extrusion.Sketch · Blend.BottomSketch/TopSketch ·
#     Revolution.Sketch · Sweep.PathSketch/ProfileSketch
#
# So one reader covers all four kinds, and not a single branch is written
# "just in case".
#
# THE REVOLVE AXIS IS READ DEFENSIVELY: the type of `Revolution.Axis` is
# confirmed by nothing that exists in the tree, so `ModelLine` and `Line`
# are both tried, and a failure is recorded as a REASON rather than
# dropping the pass. The shape "compilation answers whether a member
# exists, not whether a call will run" has been bought by this house three
# times over.

_RECIPE_CS_TEMPLATE = r'''
var __out = new Dictionary<string, object>();
__out["schema_version"] = "%(schema)s";
var __families = new List<object>();
int __budget = %(limit)d;

Func<double, double> __MM = (__v) =>
    UnitUtils.ConvertFromInternalUnits(__v, UnitTypeId.Millimeters);
Func<XYZ, double[]> __P3 = (__p) => new double[] {
    Math.Round(__MM(__p.X), 3), Math.Round(__MM(__p.Y), 3),
    Math.Round(__MM(__p.Z), 3) };
Func<Exception, string> __Cls = (__e) => {
    string __n = __e.GetType().FullName ?? "Exception";
    int __cut = __n.LastIndexOf('.');
    return __cut >= 0 && __cut + 1 < __n.Length ? __n.Substring(__cut + 1) : __n;
};

// Одно кольцо -> список сегментов. Дуга ТРЕМЯ точками (начало, точка НА дуге
// в параметрической середине, конец) — тот же контракт, что у sketch_extract:
// тесселяции нет ни на одной стороне.
Func<Sketch, List<object>> __Loops = (__sketch) => {
    var __loops = new List<object>();
    if (__sketch == null) return __loops;
    CurveArrArray __profile = __sketch.Profile;
    if (__profile == null) return __loops;
    foreach (CurveArray __array in __profile)
    {
        var __segs = new List<object>();
        foreach (Curve __curve in __array)
        {
            var __seg = new Dictionary<string, object>();
            __seg["p0"] = __P3(__curve.GetEndPoint(0));
            __seg["p1"] = __P3(__curve.GetEndPoint(1));
            if (__curve is Line) { __seg["kind"] = "line"; }
            else if (__curve is Arc)
            {
                __seg["kind"] = "arc";
                __seg["mid"] = __P3(__curve.Evaluate(0.5, true));
            }
            else
            {
                string __cn = __curve.GetType().Name;
                __seg["kind"] = __cn;
            }
            __segs.Add(__seg);
        }
        __loops.Add(__segs);
    }
    return __loops;
};

Func<Sketch, double[]> __Normal = (__sketch) => {
    if (__sketch == null || __sketch.SketchPlane == null) return null;
    try {
        Plane __plane = __sketch.SketchPlane.GetPlane();
        if (__plane == null) return null;
        XYZ __n = __plane.Normal;
        return new double[] { Math.Round(__n.X, 9), Math.Round(__n.Y, 9),
                              Math.Round(__n.Z, 9) };
    } catch { return null; }
};

Func<Sketch, object> __PlaneZ = (__sketch) => {
    if (__sketch == null || __sketch.SketchPlane == null) return null;
    try {
        Plane __plane = __sketch.SketchPlane.GetPlane();
        return __plane == null ? null
            : (object)Math.Round(__MM(__plane.Origin.Z), 3);
    } catch { return null; }
};

// 🔴 НАЧАЛО И ОСЬ +u ПЛОСКОСТИ — ВТОРАЯ ПОЛОВИНА РАМКИ, И БЕЗ НЕЁ ЧИТАЛОСЬ
// ТОЛЬКО «КУДА СМОТРИТ», НО НЕ «ГДЕ ЛЕЖИТ И КАК ПОВЁРНУТА». Обе величины
// подтверждены 6/6 по `data/api_surface` (`Plane.Origin`, `Plane.XVec`).
// Питон умеет и без них — выводит рамку из самих колец и ПРОВЕРЯЕТ обратным
// отображением, — но ответ Revit замыкает круговой ход буквально, а вывод
// только по существу.
Func<Sketch, double[]> __PlaneOrigin = (__sketch) => {
    if (__sketch == null || __sketch.SketchPlane == null) return null;
    try {
        Plane __plane = __sketch.SketchPlane.GetPlane();
        return __plane == null ? null : __P3(__plane.Origin);
    } catch { return null; }
};

Func<Sketch, double[]> __PlaneXDir = (__sketch) => {
    if (__sketch == null || __sketch.SketchPlane == null) return null;
    try {
        Plane __plane = __sketch.SketchPlane.GetPlane();
        if (__plane == null) return null;
        XYZ __xv = __plane.XVec;
        return new double[] { Math.Round(__xv.X, 9), Math.Round(__xv.Y, 9),
                              Math.Round(__xv.Z, 9) };
    } catch { return null; }
};

// Объём САМОЙ формы — вторая сторона сверки. Считает Revit, не мы.
Func<Element, object> __Volume = (__el) => {
    try {
        var __opt = new Options();
        GeometryElement __ge = __el.get_Geometry(__opt);
        if (__ge == null) return null;
        double __v = 0.0;
        foreach (GeometryObject __go in __ge)
        {
            Solid __s = __go as Solid;
            if (__s != null && __s.Volume > 0) __v += __s.Volume;
        }
        if (__v <= 0.0) return null;
        double __mm3 = __v * Math.Pow(
            UnitUtils.ConvertFromInternalUnits(1.0, UnitTypeId.Millimeters), 3);
        return (object)Math.Round(__mm3, 3);
    } catch { return null; }
};

var __model = new List<Family>();
foreach (Family __f in new FilteredElementCollector(doc).OfClass(typeof(Family)))
{
    var __ct = __f.FamilyCategory != null
        ? __f.FamilyCategory.CategoryType : CategoryType.Invalid;
    if (__ct == CategoryType.Model && __f.IsEditable) __model.Add(__f);
}

int __done = 0;
foreach (Family __fam in __model)
{
    if (__done >= __budget) break;
    __done++;
    var __row = new Dictionary<string, object>();
    __row["name"] = __fam.Name;
    __row["category"] = __fam.FamilyCategory != null
        ? __fam.FamilyCategory.Name : "";
    var __forms = new List<object>();
    Document __fd = null;
    try { __fd = doc.EditFamily(__fam); }
    catch (Exception __e) { __row["open_failed"] = __Cls(__e); }
    if (__fd == null)
    {
        if (!__row.ContainsKey("open_failed"))
            __row["open_failed"] = "EditFamily returned null";
        __row["forms"] = __forms;
        __families.Add(__row);
        continue;
    }
    // ── ПАРАМЕТРЫ СЕМЕЙСТВА И ИХ ПРИВЯЗКИ (21.08.2026) ──────────────────
    //
    // 🔴 РАДИ ЧЕГО ЭТО ЧИТАЕТСЯ. До сегодня съём брал ФОРМУ и не брал
    // ОТНОШЕНИЕ. `author_family` — это не форма: его обязательное поле
    // `flex_param`, и вся ценность в том, что тело СЛУШАЕТ параметр.
    // Замер 21.08: параметр без привязки — бесполезная ручка, и это
    // проходит ТИХО (объём не меняется, квитанция зелёная). Пока привязки
    // нет в рецепте, всякий лифтер обязан ВЫДУМАТЬ имя параметра и связь,
    // то есть выдать жёсткое семейство за гибкое.
    //
    // Все четыре члена проверены по индексу ловушек: `FamilyManager.
    // Parameters`, `Types`, `GetAssociatedFamilyParameter(Parameter)` и
    // `CanElementParameterBeAssociated` есть на ВСЕХ ШЕСТИ версиях.
    FamilyManager __fm = null;
    var __fparams = new List<object>();
    var __fparamByName = new Dictionary<string, FamilyParameter>();
    try { __fm = __fd.FamilyManager; }
    catch (Exception __e) { __row["fm_failed"] = __Cls(__e); }
    if (__fm != null)
    {
        FamilyType __cur = null;
        try { __cur = __fm.CurrentType; } catch { }
        foreach (FamilyParameter __fp in __fm.Parameters)
        {
            if (__fp == null || __fp.Definition == null) continue;
            var __pr = new Dictionary<string, object>();
            string __pname = __fp.Definition.Name ?? "";
            __pr["name"] = __pname;
            if (__pname.Length > 0 && !__fparamByName.ContainsKey(__pname))
                __fparamByName[__pname] = __fp;
            try { __pr["storage"] = __fp.StorageType.ToString(); } catch { }
            try { __pr["is_instance"] = __fp.IsInstance; } catch { }
            try { __pr["is_shared"] = __fp.IsShared; } catch { }
            try { __pr["is_reporting"] = __fp.IsReporting; } catch { }
            try
            {
                // 🔴 `IsDeterminedByFormula` — НЕ «есть ли формула». Живой
                // замер 21.08.2026, `KIR_проба_семейства`: параметр
                // `Высота_удвоенная` имеет `Formula = "Высота_KIR * 2"`, а
                // флаг вернул FALSE. Пишутся ОБА, и решать надо по `formula`.
                __pr["by_formula"] = __fp.IsDeterminedByFormula;
                if (__fp.Formula != null) __pr["formula"] = __fp.Formula;
            }
            catch { }
            // ВСТРОЕННЫЙ ИЛИ АВТОРСКИЙ. Без этого «ручка, которая ничего не
            // гнёт» включала бы «Стоимость» и «Отметка по умолчанию» —
            // системные параметры, геометрию гнуть не обязанные, — и полезный
            // сигнал утонул бы в них.
            try
            {
                InternalDefinition __fid = __fp.Definition as InternalDefinition;
                if (__fid != null)
                    __pr["built_in"] = __fid.BuiltInParameter.ToString();
            }
            catch { }
            // ЗНАЧЕНИЕ ПИШЕТСЯ СЫРЫМ И ФОРМАТИРОВАННЫМ, И ЭТО НАМЕРЕННО.
            // Единицу параметра надёжно даёт только `Definition.GetDataType`,
            // которого нет на 2021, а `AsValueString` несёт единицу текстом
            // на всех шести. Сырое число + текст Ревита = достаточно, чтобы
            // лифтер решил сам; догадка о единице здесь была бы ложью.
            if (__cur != null)
            {
                try
                {
                    if (__fp.StorageType == StorageType.Double)
                    {
                        double? __dv = __cur.AsDouble(__fp);
                        if (__dv.HasValue)
                        {
                            __pr["value_internal"] = Math.Round(__dv.Value, 9);
                            __pr["value_mm_if_length"] =
                                Math.Round(__MM(__dv.Value), 4);
                        }
                    }
                    else if (__fp.StorageType == StorageType.Integer)
                    {
                        int? __iv = __cur.AsInteger(__fp);
                        if (__iv.HasValue) __pr["value_int"] = __iv.Value;
                    }
                    else if (__fp.StorageType == StorageType.String)
                    {
                        __pr["value_str"] = __cur.AsString(__fp) ?? "";
                    }
                    string __vs = __cur.AsValueString(__fp);
                    if (__vs != null) __pr["value_shown"] = __vs;
                }
                catch (Exception __e) { __pr["value_reason"] = __Cls(__e); }
            }
            else __pr["value_reason"] = "у семейства нет текущего типа";
            __fparams.Add(__pr);
        }
        var __ftypes = new List<object>();
        try
        {
            foreach (FamilyType __ft in __fm.Types)
                if (__ft != null && (__ft.Name ?? "").Length > 0)
                    __ftypes.Add(__ft.Name);
        }
        catch (Exception __e) { __row["types_reason"] = __Cls(__e); }
        __row["types"] = __ftypes;
        __row["current_type"] = __cur != null ? (__cur.Name ?? "") : "";
    }
    __row["family_params"] = __fparams;

    // ── ПЕРЕПИСЬ ЭЛЕМЕНТОВ ДОКУМЕНТА СЕМЕЙСТВА (26.08.2026) ──────────────
    //
    // 🔴 ЗАКОН ПЕРЕПИСИ (§18) ДЕРЖАЛСЯ НА УРОВНЕ СЕМЕЙСТВ И БЫЛ СЛОМАН НА
    // УРОВНЕ ЭЛЕМЕНТОВ. Наверху есть `families_seen` и `families_read`, а
    // внутри семейства тело собирает ТОЛЬКО `typeof(GenericForm)` и не
    // говорит, что пропустило. Замер 26.08: 27 семейств из 110 ОТКРЫВАЮТСЯ
    // и отдают ноль форм, и лишь 8 из них двумерны по природе (4 «Элементы
    // узлов» + 4 «Профили»). Остальные девятнадцать — диван, кухня, лифты,
    // мусорный бак, пять окон, тумба — геометрию имеют заведомо. Без переписи
    // «форм нет» и «форм не увидели» неразличимы, и неделю читались как
    // первое.
    //
    // 🔴 СЧЁТЧИКИ РОДОВ МОГУТ ПЕРЕСЕКАТЬСЯ, И ЭТО НАЗВАНО ЗДЕСЬ. Наследование
    // классов Ревита нам не объявлено ничем (`data/api_surface` несёт членов,
    // а не предков), поэтому проверки идут НЕЗАВИСИМЫМИ `if`, а не цепочкой
    // `else if`: цепочка тихо приписала бы предку то, что принадлежит
    // потомку. Сводить перепись надо по `census_by_class` — он разбивает
    // РОВНО `census_elements` без пересечений, потому что род у элемента
    // ровно один.
    var __byClass = new Dictionary<string, object>();
    try
    {
        int __seen2 = 0, __gf2 = 0, __fi2 = 0, __ii2 = 0, __ff2 = 0;
        var __counts = new Dictionary<string, int>();
        foreach (Element __e2 in new FilteredElementCollector(__fd)
            .WhereElementIsNotElementType())
        {
            if (__e2 == null) continue;
            __seen2++;
            string __cn2 = __e2.GetType().Name;
            __counts[__cn2] = (__counts.ContainsKey(__cn2) ? __counts[__cn2] : 0) + 1;
            if (__e2 is GenericForm) __gf2++;
            if (__e2 is FamilyInstance) __fi2++;
            if (__e2 is ImportInstance) __ii2++;
            if (__e2 is FreeFormElement) __ff2++;
        }
        // 🔴 ТИП БЕЗ ПРОБЕЛА ПОСЛЕ ЗАПЯТОЙ, И ЭТО НЕ ВКУСОВЩИНА. Реестр
        // согласий (`agreements.тело_объявляет_помощников`) узнаёт объявление
        // в `foreach` выражением `[\w.<>,\[\]?]+`, а пробела в этом классе
        // нет: `KeyValuePair<string, int>` читается как НЕобъявление, и
        // сторож кричит «зовёт и НЕ объявляет __kv2». Куплено воротами
        // 26.08.2026 с первого прогона.
        foreach (KeyValuePair<string,int> __kv2 in __counts)
            __byClass[__kv2.Key] = __kv2.Value;
        __row["census_elements"] = __seen2;
        __row["census_generic_forms"] = __gf2;
        __row["census_family_instances"] = __fi2;
        __row["census_import_instances"] = __ii2;
        __row["census_free_form_elements"] = __ff2;
        __row["census_by_class"] = __byClass;
        __row["census_source"] = "api";
    }
    catch (Exception __e)
    {
        __row["census_source"] = "refused";
        __row["census_reason"] = __Cls(__e);
    }

    try
    {
        foreach (Element __el in new FilteredElementCollector(__fd)
            .OfClass(typeof(GenericForm)))
        {
            GenericForm __gf = __el as GenericForm;
            if (__gf == null) continue;
            var __form = new Dictionary<string, object>();
            __form["id"] = long.Parse(__el.Id.ToString()).ToString();
            __form["kind"] = __el.GetType().Name;
            __form["is_solid"] = __gf.IsSolid;
            __form["name"] = __gf.Name ?? "";
            __form["measured_volume_mm3"] = __Volume(__el);

            Sketch __shape = null;
            Extrusion __ex = __el as Extrusion;
            Blend __bl = __el as Blend;
            Revolution __rv = __el as Revolution;
            Sweep __sw = __el as Sweep;

            if (__ex != null)
            {
                __shape = __ex.Sketch;
                __form["start_offset_mm"] = Math.Round(__MM(__ex.StartOffset), 3);
                __form["end_offset_mm"] = Math.Round(__MM(__ex.EndOffset), 3);
            }
            else if (__bl != null)
            {
                __shape = __bl.BottomSketch;
                __form["start_offset_mm"] = Math.Round(__MM(__bl.BottomOffset), 3);
                __form["end_offset_mm"] = Math.Round(__MM(__bl.TopOffset), 3);
                __form["top_loops"] = __Loops(__bl.TopSketch);
            }
            else if (__rv != null)
            {
                __shape = __rv.Sketch;
                __form["start_angle_deg"] = Math.Round(
                    __rv.StartAngle * 180.0 / Math.PI, 6);
                __form["end_angle_deg"] = Math.Round(
                    __rv.EndAngle * 180.0 / Math.PI, 6);
                // Тип Axis не подтверждён индексом — пробуем и записываем
                // ПРИЧИНУ, а не роняем проход.
                try
                {
                    object __axis = __rv.Axis;
                    ModelLine __ml = __axis as ModelLine;
                    Line __ln = __ml != null
                        ? (__ml.GeometryCurve as Line) : (__axis as Line);
                    if (__ln != null)
                    {
                        __form["axis_start_mm"] = __P3(__ln.GetEndPoint(0));
                        __form["axis_end_mm"] = __P3(__ln.GetEndPoint(1));
                    }
                    else __form["axis_reason"] = "Axis is "
                        + (__axis == null ? "null" : __axis.GetType().Name);
                }
                catch (Exception __e) { __form["axis_reason"] = __Cls(__e); }
            }
            else if (__sw != null)
            {
                __shape = __sw.ProfileSketch;
                __form["profile_is_symbol"] =
                    (__sw.ProfileSketch == null && __sw.ProfileSymbol != null);
                // ── КАКОЙ ИМЕННО ПРОФИЛЬ (26.08.2026) ────────────────────
                //
                // 🔴 ДО СЕГОДНЯ ЗАХВАТ ЗНАЛ, ЧТО ОТНОШЕНИЕ ЕСТЬ, И НЕ ЗНАЛ,
                // К ЧЕМУ. `profile_is_symbol` — БУЛЕВ: двадцать протяжек
                // корпуса говорят `true`, и ни одна не называет профиль.
                // Присоединиться не к чему, и `sweep_profile_is_family_symbol`
                // — доминирующий отказ выразимости: 20 форм у 18 семейств из
                // 82. Это ровно та же форма дефекта, что у выреза, второй раз
                // в одном теле: отношение объявлено и не адресовано.
                //
                // ПОЧЕМУ ЧЕТЫРЕ ПОЛЯ РАЗМЕЩЕНИЯ, А НЕ ОДНО ИМЯ. Профиль — не
                // только очертание: `FamilySymbolProfile` несёт ещё смещения,
                // поворот и зеркало (`XOffset`, `YOffset`, `Angle`,
                // `IsFlipped`, все 6/6 по `data/api_surface`). Снять одно имя
                // значило бы подготовить второй проход, который построит
                // ВЕРНОЕ очертание в НЕВЕРНОМ месте и промолчит об этом.
                try
                {
                    FamilySymbolProfile __fsp =
                        __sw.ProfileSymbol as FamilySymbolProfile;
                    FamilySymbol __psym = __fsp != null ? __fsp.Profile : null;
                    if (__psym == null) __form["profile_symbol_source"] = "absent";
                    else
                    {
                        __form["profile_symbol_source"] = "api";
                        __form["profile_symbol_name"] = __psym.Name ?? "";
                        __form["profile_family_name"] = __psym.Family != null
                            ? (__psym.Family.Name ?? "") : "";
                        __form["profile_x_offset_mm"] =
                            Math.Round(__MM(__fsp.XOffset), 3);
                        __form["profile_y_offset_mm"] =
                            Math.Round(__MM(__fsp.YOffset), 3);
                        __form["profile_angle_deg"] =
                            Math.Round(__fsp.Angle * 180.0 / Math.PI, 6);
                        __form["profile_flipped"] = __fsp.IsFlipped;
                    }
                }
                catch (Exception __e)
                {
                    __form["profile_symbol_source"] = "refused";
                    __form["profile_symbol_reason"] = __Cls(__e);
                }
                // ── ПУТЬ ТРЁХМЕРНЫМИ КРИВЫМИ (26.08.2026) ────────────────
                //
                // Причина `sweep_path_unavailable` стояла в коде дословно:
                // «у Sweep есть Path3d — путь бывает задан трёхмерной
                // траекторией, а не эскизом, — и читающий C# его пока не
                // спрашивает: отличить эти два случая нечем». Шесть форм у
                // пяти семейств висели на этом НЕЗНАНИИ.
                //
                // 🔴 ТИП НЕ ОБЪЯВЛЯЕТСЯ, А СПРАШИВАЕТСЯ. Проза XML говорит
                // только «The selected curves used for the sweep path», типа
                // не называет. Объявить его здесь значило бы угадать; вместо
                // этого берётся `object`, и наружу едет ИМЯ рода, как его
                // назвал сам Ревит, плюс счёт по `IEnumerable`. Меньше знания
                // — но ни одного выдуманного факта.
                try
                {
                    object __p3 = __sw.Path3d;
                    if (__p3 == null) __form["path3d_source"] = "absent";
                    else
                    {
                        __form["path3d_source"] = "api";
                        __form["path3d_kind"] = __p3.GetType().Name;
                        int __p3n = 0;
                        System.Collections.IEnumerable __p3e =
                            __p3 as System.Collections.IEnumerable;
                        if (__p3e != null)
                            foreach (object __p3i in __p3e) __p3n += (__p3i == null ? 0 : 1);
                        __form["path3d_count"] = __p3n;
                    }
                }
                catch (Exception __e)
                {
                    __form["path3d_source"] = "refused";
                    __form["path3d_reason"] = __Cls(__e);
                }
                var __path = new List<object>();
                try
                {
                    Sketch __ps = __sw.PathSketch;
                    if (__ps != null && __ps.Profile != null)
                    {
                        foreach (CurveArray __arr in __ps.Profile)
                            foreach (Curve __c in __arr)
                            {
                                if (__path.Count == 0)
                                    __path.Add(__P3(__c.GetEndPoint(0)));
                                __path.Add(__P3(__c.GetEndPoint(1)));
                            }
                    }
                }
                catch (Exception __e) { __form["path_reason"] = __Cls(__e); }
                __form["path_mm"] = __path;
            }

            var __normal = __Normal(__shape);
            if (__normal != null) __form["plane_normal"] = __normal;
            var __pz = __PlaneZ(__shape);
            if (__pz != null) __form["plane_z_mm"] = __pz;
            var __po = __PlaneOrigin(__shape);
            if (__po != null) __form["plane_origin_mm"] = __po;
            var __px = __PlaneXDir(__shape);
            if (__px != null) __form["plane_x_dir"] = __px;
            if (__shape == null)
                __form["profile_reason"] = "у формы нет читаемого эскиза";
            else
                __form["loops"] = __Loops(__shape);
            // ── ПРИВЯЗКИ ЭТОЙ ФОРМЫ (21.08.2026) ───────────────────────
            //
            // Отношение, которого рецепту не хватало: КАКОЙ параметр
            // семейства управляет КАКИМ полем этой формы. Без него
            // `flex_param` неоткуда взять, а с ним — берётся ИМЕНЕМ, а не
            // догадкой.
            //
            // `BuiltInParameter` записывается рядом с человеческим именем
            // намеренно: имя локализовано («Высота выдавливания» против
            // "Extrusion End"), а встроенный код одинаков на шести версиях и
            // на всех языках. Лифтеру нужен именно он.
            var __assoc = new List<object>();
            if (__fm != null)
            {
                try
                {
                    foreach (Parameter __ep in __el.Parameters)
                    {
                        if (__ep == null || __ep.Definition == null) continue;
                        FamilyParameter __drv = null;
                        try { __drv = __fm.GetAssociatedFamilyParameter(__ep); }
                        catch { continue; }
                        if (__drv == null || __drv.Definition == null) continue;
                        var __a = new Dictionary<string, object>();
                        __a["element_param"] = __ep.Definition.Name ?? "";
                        InternalDefinition __id = __ep.Definition as InternalDefinition;
                        if (__id != null)
                        {
                            try { __a["built_in"] = __id.BuiltInParameter.ToString(); }
                            catch { }
                        }
                        __a["family_param"] = __drv.Definition.Name ?? "";
                        try { __a["storage"] = __ep.StorageType.ToString(); } catch { }
                        __assoc.Add(__a);
                    }
                }
                catch (Exception __e) { __form["assoc_reason"] = __Cls(__e); }
            }
            __form["driven_by"] = __assoc;
            __forms.Add(__form);
        }
    }
    catch (Exception __e) { __row["read_failed"] = __Cls(__e); }
    try { __fd.Close(false); } catch { }
    __row["forms"] = __forms;
    __families.Add(__row);
}

__out["families"] = __families;
__out["families_seen"] = __model.Count;
__out["families_read"] = __done;
return __out;
'''


def family_recipe_cs(*, limit: int = 200) -> str:
    """The reading C# for recipe capture. WRITES NOTHING TO THE DOCUMENT.

    `limit` is how many families to read in one pass. Measured 20.08: one
    family opens in ~380 ms, 109 of them fit into 41.4 s, so the limit here
    is about the RESPONSE'S MEMORY footprint, not about time.

    🔴 `EditFamily` OPENS A DOCUMENT and must close it: `Close(false)` sits
    in a `finally`-like position after the read, and saves nothing. An
    unclosed family stays in Revit's memory until the end of the session.
    """
    if not isinstance(limit, int) or limit < 1:
        raise FamilyRecipeError("limit — целое ≥ 1")
    return _RECIPE_CS_TEMPLATE % {
        "schema": FAMILY_RECIPE_SCHEMA_VERSION,
        "limit": limit,
    }


def summarise_payload(payload: Any) -> dict[str, Any]:
    """A live payload -> a summary over ALL families at once.

    Answers the question the whole capture was started for: how many
    families translate into a program COMPLETELY, how many partially, and
    what each one was missing. A partial family is deliberately named
    apart from a complete one: "raised three shapes of six" and "raised
    everything" are different claims, and folded into one ratio they read
    as the second.
    """
    recipes = parse_recipe_payload(payload)
    per_family: list[dict[str, Any]] = []
    full = partial = none = 0
    all_lifts: list[FormLift] = []
    for recipe in recipes:
        if recipe.open_failed_reason:
            per_family.append({"family": recipe.family_name,
                               "open_failed": recipe.open_failed_reason})
            continue
        if not recipe.forms:
            continue
        lifts = recipe_to_ops(recipe)
        all_lifts.extend(lifts)
        lifted = sum(1 for lift in lifts if lift.lifted)
        if lifted == len(lifts):
            full += 1
        elif lifted:
            partial += 1
        else:
            none += 1
        per_family.append({
            "family": recipe.family_name,
            "category": recipe.category,
            "forms": len(lifts),
            "lifted": lifted,
            "refusals": sorted({lift.refusal.code.value
                                for lift in lifts if lift.refusal}),
        })
    summary = lift_summary(all_lifts)
    summary.update({
        "families_with_forms": full + partial + none,
        "families_lifted_fully": full,
        "families_lifted_partially": partial,
        "families_lifted_none": none,
    })
    return {"summary": summary, "families": per_family}


def _main(argv: Sequence[str]) -> int:  # pragma: no cover - manual run
    import pathlib
    if len(argv) != 2:
        print("usage: python -m kir.decompile.family_recipe <payload.json>")
        print("       либо  --cs  чтобы напечатать читающий C#")
        return 2
    if argv[1] == "--cs":
        print(family_recipe_cs())
        return 0
    raw = json.loads(pathlib.Path(argv[1]).read_text(encoding="utf-8"))
    # The bridge's response wraps the payload in `result`; both forms are
    # accepted.
    if isinstance(raw, Mapping) and "result" in raw:
        raw = raw["result"]
    report = summarise_payload(raw)
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys as _sys
    raise SystemExit(_main(_sys.argv))
