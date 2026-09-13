"""Typed validation boundary for KIR authoring operations.

This module owns normalization and static refusal of authoring input.  It has
no emitter or live-execution authority: accepted values are handed to
``kir.authoring`` for deterministic C# emission.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

from kir import contour as _contour_bounds
from kir import registry_base
from kir import docspace, faceref, relate, spec
from kir.diag import (
    Diagnostic,
    GROUND_BAD_SELECTOR,
    PARSE_EXCLUSIVE_FIELDS,
    PARSE_MISSING_FIELD,
    TYPE_BAD_TYPE,
    TYPE_BOUNDS,
)
from kir.emit_utils import ELEMENT_ID_MAX, is_finite_number
from kir.registry_base import (
    WALL_LAYER_FUNCTIONS, WALL_LAYER_MAX_MM, WALL_LAYER_MIN_MM,
    WALL_LAYERS_MAX,
)
# The law of the polygonal profile is declared ONCE in geom (that is also
# where its origin and the measurement of harm live). Here it is READ:
# the forward pass must reject exactly what the reverse pass turns into
# an atom.
from kir.geom import (
    MAX_HOLE_RING_POINTS,
    MAX_HOLES,
    MAX_PATH_POINTS,
    MAX_RING_POINTS,
    MIN_PATH_POINTS,
    MIN_RING_AREA_MM2,
    MIN_RING_POINTS,
)


def _num(x) -> bool:
    return is_finite_number(x)


# ───────────────────────── a refusal must name the NEXT TURN

def _base_field(field_name: str) -> str:
    """`mesh.triangles[0]` -> `mesh`. The registry slot is only the
    path's root."""
    return field_name.split(".", 1)[0].split("[", 1)[0]


def _slot_tail(op_name: str, d: Diagnostic, *, with_roster: bool) -> str:
    """The refusal tail for ONE slot: what is legal and what to do next.

    THE MEASUREMENT THAT PAID FOR THIS. A live owner turn on 16.08.2026 on
    a flash model: in ONE turn two refusals landed side by side and
    behaved in OPPOSITE ways — `KIR-T002` («slopes без единого угла — это
    плоская крыша, просто не задавай поле») produced a corrected program
    in FOUR SECONDS, while `KIR-P003` («неизвестное поле») killed the
    turn. The difference is exactly one thing: the first one carried the
    next turn. `KIR-P003` was closed by `74b71035`; here the next two
    most frequent are closed.

    THE NUMBERS THAT SET THE ORDER (prod corpus `kir_rejections.jsonl`,
    the record form with `diag_code`, 463 records 10–16.08): `KIR-T001`
    131 · `KIR-P003` 57 (closed) · `KIR-P005` 51. Three codes — 51 % of
    live refusals, and before this fix two of them looked like this on a
    program with six defects:

        p0_mm — точка в мм · p1_mm — точка в мм · level обязателен ×2 ·
        height_mm — число в мм                      TOTAL 108 characters

    Six refusals, one hundred eight characters, and NOT ONE says what to
    do.

    WHY A TAIL PER SLOT, RATHER THAN THE WHOLE OP'S FORM, as with
    `KIR-P003`. There the field is UNKNOWN — the model missed the
    dictionary entirely, and it needs the whole dictionary. Here the slot
    is NAMED CORRECTLY and filled incorrectly: what is needed is the
    contract of THIS slot, and the whole op's form, printed six times on
    one program, is six copies of one text in the turn, where 84.6 % of
    the time is already spent waiting on the model.

    WHY IT CALLS SOMEONE ELSE'S `_annotation` RATHER THAN WRITING ITS
    OWN. `dsl._annotation` already prints the selector's kind, bounds,
    and forms — the same source `_call_form` in `KIR-P003` and the
    language's docstrings are assembled from. A render of our own would
    become a second opinion about the slot and would drift from the first
    exactly when the model reads both in a row: ALL the hand-written
    lists in this tree have drifted apart, and NOT ONE generated one has.

    THE IMPORT IS LOCAL ON PURPOSE: `dsl` imports `compiler`, which
    imports this module. The path is cold; this is the refusal branch.
    """
    from kir.dsl import _annotation  # local: a cycle, see the docstring

    ospec = spec.OPS.get(op_name)
    if ospec is None:
        return ""
    поле = d.field_name or ""
    # 🔴 A GROUP MEMBER'S PATH ADDRESSES A SLOT OF A FOREIGN OP. Measured
    # 25.08.2026. On a refusal inside a group, `ground` rewrites the
    # diagnostic address: `level` -> `members[w1].level`, and `op_id` to
    # the group's id. The root of such a path is `members`, and that IS a
    # REAL `create_group` slot, so the guard «field not in the registry —
    # stay silent» below did not trigger, and the author got advice about
    # the group's `members` when the defect was in the WALL's `level`.
    #
    # There is nothing here to give correct advice with: at this seam the
    # known op is the GROUP's, while the slot belongs to the MEMBER's op.
    # So silence — under the same law as the line below: made-up advice
    # is worse than silence, and it gets checked by a turn.
    #
    # This does not touch tails built INSIDE the member's own raising
    # (the three ordinary kinds of author error): they are assembled
    # BEFORE the address is rewritten and already sit in the text.
    # Silence occurs exactly where FOREIGN advice would otherwise have
    # appeared.
    if поле.startswith("members["):
        return ""
    base = _base_field(поле)
    p = next((pp for pp in ospec.params if pp.name == base), None)
    if p is None:
        # DO NOT MAKE THINGS UP. A field not from the registry
        # (`where.*`, `target.value`, `defaults`) — there is nothing to
        # say about it here, and silence is more honest than a guess:
        # made-up advice is worse than silence, and it gets checked by a
        # turn.
        return ""
    required = [pp.name for pp in ospec.params if pp.required]
    lines = [f"\n    {base}  {_annotation(ospec, p)}"]
    if d.got is not None and d.code == TYPE_BAD_TYPE:
        got = repr(d.got)
        lines.append(f"\n  получено: {got[:80]}{'…' if len(got) > 80 else ''}")
    if d.code == PARSE_MISSING_FIELD:
        move = f"задай {base} в виде выше"
    else:
        move = f"приведи {base} к виду выше"
    if required and with_roster:
        # The list of required fields is a property of the OP, not the
        # slot: on a program with three defects in one op it would
        # repeat verbatim three times. We print it with the op's first
        # refusal; it's one turn either way, and the model sees all of
        # them.
        move += (f"; обязательные слоты {op_name}: {', '.join(required)} — "
                 f"закрой недостающие ОДНИМ ходом, а не по одному за ход")
    lines.append(f"\nСЛЕДУЮЩИЙ ХОД: {move}.")
    return "".join(lines)


def _name_the_next_move(op_name: str, diags: list, start: int) -> None:
    """Append the next turn to refusals raised by THIS call to
    `validate`.

    ONE PLACE, NOT A FIX AT EVERY SITE, AND THIS IS A LOAD-BEARING
    DECISION. `PARSE_MISSING_FIELD` is raised at eight sites in this
    file, `TYPE_BAD_TYPE` at dozens (`contour.py` alone accounts for more
    than ten). Fixing site by site would leave the next one unwritten in
    silence: a new refusal branch would be born bare, and no one would
    notice. Here, instead, the tail is DERIVED from the code and the
    field — meaning it also covers future sites.

    Idempotent by construction: text that already carries «СЛЕДУЮЩИЙ
    ХОД» is left untouched. So `KIR-P003`, enriched by `74b71035` with
    the op's whole form, remains verbatim as it was, and its control
    does not budge.
    """
    roster_spent = False
    for d in diags[start:]:
        # 🔴 THE GATE WAS LIFTED FROM TWO CODES ON 21.08.2026 — BY
        # MEASUREMENT, NOT BY GUESS.
        #
        # Here stood `if d.code not in (PARSE_MISSING_FIELD,
        # TYPE_BAD_TYPE)`, and the tail was given to two codes out of a
        # hundred and one. A muteness measurement from the same day
        # (`tools/refusal_muteness.py`, 729 live refusals across 54
        # codes):
        #
        #     turn NAMED everywhere        29 codes    28.7 %
        #     turn NOT named anywhere      51 codes    50.5 %
        #     mute LIVE refusals          435 of 729   59.7 %
        #
        # and this one line closes **326 of 435 (74.9 %)**: the debtors —
        # `KIR-T002` ×68, `KIR-T001` ×46, `KIR-T004` ×46, `KIR-G101` ×18,
        # `KIR-L003` ×14. All of them NAME the slot and stay silent about
        # what to do with it.
        #
        # The condition is now about the SUBJECT, not a list of codes: a
        # tail is needed by every refusal that pointed at a slot.
        # `_slot_tail` itself returns emptiness if the field is not from
        # the registry (`where.*`, `target.value`) — meaning the
        # extension cannot make up advice where there is nothing to say.
        # A list of codes in its place would silently have left every
        # next kind of refusal unwritten, exactly as it left these five.
        if not (d.field_name or "").strip():
            continue
        if "СЛЕДУЮЩИЙ ХОД" in (d.message_ru or ""):
            continue
        tail = _slot_tail(op_name, d, with_roster=not roster_spent)
        if tail:
            d.message_ru = (d.message_ru or "") + tail
            roster_spent = True


# Static coordinate sanity bound (audit F12): Revit's own workable model
# extent is ~16 km from origin; a coordinate beyond that is a unit/garbage
# error that previously sailed to a late Revit runtime refusal.  Refused
# statically here instead — same enforcement point as every numeric bound.
# READ FROM THE REGISTRY, rather than written here: there used to be TWO
# copies of this number (the second in `connect.py`), and the `region`
# kind was checked by neither.
_COORD_LIMIT_MM = registry_base.COORD_LIMIT_MM

# ``ref_dir`` selects Revit's WorkPlaneBased placement overload.  The
# operands below belong to the point/TwoLevelsBased lowering: today there is
# no measured Revit contract which composes them with that overload.  Keep
# the list at the validation/emission boundary so an explicit neutral value
# (``rotation_deg=0``/``mirrored=false``) cannot disappear merely because it
# happens to match a default.
PLACE_FAMILY_WORK_PLANE_UNSUPPORTED = (
    "rotation_deg",
    "mirrored",
    "hand_flipped",
    "facing_flipped",
    "top_level",
    "base_offset_mm",
    "top_offset_mm",
)

#: Ceiling on the length of `create_text.content`.
#:
#: WHAT WAS MEASURED (02.08.2026, `k2_ar_rd_v8`, a 59-story tower): 2,697
#: text notes, maximum **4,763 characters**, nine of them longer than the
#: previous ceiling of 2,000. The previous number came from
#: `KIR_DOC_SPEC.md` — «content: непустой, <= разумной длины» — meaning
#: it was written by REASONING, and the live building refuted it.
#: Exactly the same class of defect as `create_door.sill_mm min_val=0`
#: against 140 negative marks.
#:
#: WHAT WAS NOT MEASURED: Revit's own limit on `TextNote.Text`. It is not
#: documented, was not checked by a live probe, and this ceiling does NOT
#: model it. Here it protects EMISSION: one operation must not bloat the
#: program. That is why the margin was taken with fourfold headroom over
#: the measured maximum — and as soon as Revit's limit is measured, THIS
#: NUMBER MUST be replaced with the measured one, rather than moved once
#: more by reasoning.
_TEXT_CONTENT_MAX_CHARS = 20_000


#: Cardinality and repeat law for a multi-element write-selector.
#:
#: This is runtime's authority, and the bounded-decode schema imports the
#: same function. Previously runtime held two exceptional ops here, while
#: ``schema_gen`` promised 2..16 for any ``refs_w``. A legitimate
#: single-element ``move_elements`` was therefore impossible to generate
#: through the schema, while the schema promised an angular dimension
#: with three references, even though the compiler was obligated to
#: reject it.
_REFS_W_DEFAULT_CONTRACT = (2, 16, True)
_REFS_W_CONTRACT_BY_OP = {
    "move_elements": (1, 500, False),
    "create_angular_dimension": (2, 2, True),
}


def _refs_w_contract(op_name: str) -> tuple[int, int, bool]:
    """``(min_items, max_items, reject_duplicates)`` for one op."""
    return _REFS_W_CONTRACT_BY_OP.get(op_name, _REFS_W_DEFAULT_CONTRACT)


def _pt_shape_ok(v, dims=(2, 3)) -> bool:
    """The FORM of a point, with no bound: a list of the required length
    made of finite numbers."""
    return (isinstance(v, list) and len(v) in dims
            and all(_num(c) for c in v))


def _pt_over_limit(v):
    """The first coordinate BEYOND the scene bound, or ``None``.

    🔴 SEPARATED 25.08.2026, BECAUSE MERGED IT GAVE UNACTIONABLE ADVICE.
    Form and bound are different questions, but there was one refusal:
    `KIR-T001` with `expected='[x,y] мм (числа)'` and
    `got=[99000000, 0]`. The value is ALREADY a list of two numbers, so
    «приведи к виду выше» is unactionable by construction, and the
    bound's number was never named anywhere. The neighboring `relate.py`
    refuses the same quantity correctly: `TYPE_BOUNDS` and a printed
    bound.
    """
    if not isinstance(v, list):
        return None
    for c in v:
        if _num(c) and abs(c) > _COORD_LIMIT_MM:
            return float(c)
    return None


def _pt_ok(v, dims=(2, 3)) -> bool:
    return _pt_shape_ok(v, dims) and _pt_over_limit(v) is None


def _point_bounds_diag(v, *, i, oid, field):
    """The «за пределом» diagnostic if the form is valid, otherwise
    ``None``."""
    за = _pt_over_limit(v)
    if за is None or not isinstance(v, list):
        return None
    return Diagnostic(
        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=field,
        expected=f"|координата| <= {_COORD_LIMIT_MM:.0f} мм",
        got=v,
        message_ru=(f"{field}: координата {за:.0f} мм за пределом сцены "
                    f"({_COORD_LIMIT_MM:.0f} мм от начала координат). "
                    f"Это почти всегда ошибка ЕДИНИЦ — метры вместо "
                    f"миллиметров или футы вместо метров"))


def _dist(a, b) -> float:
    dz = (a[2] if len(a) > 2 else 0) - (b[2] if len(b) > 2 else 0)
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + dz ** 2)


#: Minimum segment length (mm). Below this, Revit itself will refuse via
#: ShortCurveTolerance, and the refusal will come from the transaction
#: instead of from compilation.
_MIN_SEGMENT_MM = 1.0

#: 🔴 NOT A THIRD CARRIER OF THE QUANTITY, BUT THE SAME ONE. The segment
#: ceiling equals the ceiling of the shape's side and the body's bounding
#: box: one scene — one bound. A separate constant with the same number
#: would drift apart at the very first fix.
_MAX_SEGMENT_MM = _contour_bounds.SHAPE_SIDE_MAX_MM


def reject_segment_length(p0, p1, op_name: str, i, oid, diags: list) -> bool:
    """SEGMENT LENGTH FROM BOTH SIDES — ONE implementation, two stages.

    Literal ends are checked here, at validate. Ends that arrive as an
    address from grids are known only after ground — and the same law is
    called from there (`ground.ground`), rather than being rewritten
    again. A rule written twice drifts apart in one of the two places; a
    rule called twice does not.

    🔴 THE UPPER BOUND WAS INTRODUCED ON 24.08 FOLLOWING A LIVE MISS THAT
    THE OWNER'S EYE FOUND, NOT AN INSTRUMENT. An author was building an
    8×5 m apartment and wrote the far corner as `6008000` instead of
    `608000` — one extra digit. The result was an "apartment" 5,404
    meters LONG at a width of five, repeated across four samples.
    EVERYTHING passed: compilation, the witness, acceptance
    (`accepted`), `built=True`. No instrument compares what was built
    against what was ORDERED — the assignment lives in the prompt, and
    the program is its own authority.

    Symmetry had been broken: we had rejected a ZERO-length wall since
    04.08, while accepting a five-kilometer wall in silence. Height, at
    the same time, was bounded (`height_mm` ≤ 100 000); length was not.

    The ceiling is NOT made up: 500,000 mm is the same quantity that
    already bounds the shape's side and the body's bounding box
    (`contour.SHAPE_SIDE_MAX_MM`), and it IS VERIFIED AGAINST THE
    CORPUS, AND BY KIND, NOT BY A SINGLE NUMBER. 49,857 segments from six
    decompiled buildings, seven op kinds, longer than 500 m — NONE:

        create_wall       29 260   longest  43.2 m
        create_pipe       18 399            20.5 m
        create_duct        1 095             7.3 m
        create_beam          959             8.1 m
        create_grid          128            58.5 m  ← corpus record
        create_stairs         10             8.8 m
        create_cable_tray      6             5.0 m

    🔴 THE BREAKDOWN HERE IS NOT DECORATION. The law judges SEVENTEEN op
    kinds, and the first edition of this line named a number measured on
    walls — that is, it computed on one kind and bound them all. The
    breakdown answers the real question: not «does a long wall ever
    happen», but «which kind sits closest to the ceiling». The closest is
    the GRID (`create_grid`, 58.5 m): it is not even a building element
    at all, but a datum, and it is exactly the one with a legitimate
    reason to stick out past the bounding box. Even for it, the margin
    is 8.5-fold.
    """
    d = _dist(p0, p1)
    if d < _MIN_SEGMENT_MM:
        # 🔴 FORM, NOT JUST CODE+ADDRESS (25.08.2026, the mission
        # instrument `tools/mission/refusal_actionability.py`). The
        # refusal named the narrow code and the real slot, but did not
        # say WHAT TO BRING IT TO: there was no measured length, no
        # minimum, and no points themselves — the author had nothing to
        # fix with except guessing. `expected` carries the bound number
        # for number, `got` carries the measured length, and the text
        # carries both points literally.
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="p1_mm",
            got=d, expected=f">= {_MIN_SEGMENT_MM:.0f} мм",
            message_ru=(
                f"{op_name}: p0_mm={list(p0)} и p1_mm={list(p1)} — длина "
                f"{d:.3f} мм при минимуме {_MIN_SEGMENT_MM:.0f} мм. "
                f"СЛЕДУЮЩИЙ ХОД: измени p1_mm так, чтобы отстоять от p0_mm "
                f"не меньше чем на {_MIN_SEGMENT_MM:.0f} мм")))
        return False
    if d > _MAX_SEGMENT_MM:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="p1_mm",
            message_ru=(
                f"{op_name}: длина {d / 1000:.0f} м при потолке сцены "
                f"{_MAX_SEGMENT_MM / 1000:.0f} м. Самый длинный отрезок шести "
                f"разобранных зданий — 58.5 м на 49 857 (и это ОСЬ, а не "
                f"элемент), так что это почти всегда "
                f"ЛИШНИЙ РАЗРЯД в координате (6008000 вместо 608000), а не "
                f"замысел. Проверь p1_mm; если длина настоящая — режь стену "
                f"на звенья.")))
        return False
    return True


#: The name by which the two stages call the law. Renaming without an
#: alias would require editing `ground.py`, which is currently under
#: someone else's edit.
reject_zero_length = reject_segment_length


# Endpoint agreement tolerance between the arc dict and p0_mm/p1_mm (mm). The
# endpoints stay the wall's grounding/hosting anchor; the arc supplies the
# bulge. Kept loose enough for round-tripped float noise (LOT31 capture drifts
# <1e-6 mm) yet far below any real modelling tolerance.
_ARC_ENDPOINT_TOL_MM = 1.0


def _arc_endpoints_mm(arc: dict) -> tuple[tuple[float, float, float],
                                          tuple[float, float, float]]:
    """The two world-mm endpoints implied by a canonical Arc dict, evaluated
    the same way Revit's Arc.Create parameterises: P(t)=C + r(cos t·X + sin t·Y)
    at the start and end angle. Used only to cross-check p0_mm/p1_mm."""
    c = arc["center_mm"]
    r = float(arc["radius_mm"])
    xa = arc["x_axis"]
    ya = arc["y_axis"]
    out = []
    for ang in (float(arc["start_angle_rad"]), float(arc["end_angle_rad"])):
        ca, sa = math.cos(ang), math.sin(ang)
        out.append((
            c[0] + r * (ca * xa[0] + sa * ya[0]),
            c[1] + r * (ca * xa[1] + sa * ya[1]),
            c[2] + r * (ca * xa[2] + sa * ya[2]),
        ))
    return out[0], out[1]


def _validate_arc(v: dict, i: int, oid: str, p0, p1, diags: list):
    """Validate a canonical Arc dict via recompile's audited ArcCurve, then
    cross-check that its endpoints match p0_mm/p1_mm (either orientation).

    recompile owns every geometric invariant (unit axes, positive radius,
    (0,2*pi] span) — we never re-derive them here, keeping the arc law in ONE
    place. Returns the deduplicated canonical dict, or None on a diagnostic."""
    from kir.decompile import recompile
    required = {"curve_type", "center_mm", "radius_mm", "x_axis", "y_axis",
                "start_angle_rad", "end_angle_rad"}
    if set(v) != required or v.get("curve_type") != "Arc":
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="arc",
            expected=sorted(required), got=v,
            message_ru="arc — canonical Arc {center_mm, radius_mm, x_axis, "
                       "y_axis, start_angle_rad, end_angle_rad}"))
        return None
    try:
        curve = recompile.curve_from_dict(v, "arc")
    except recompile.GeometrySchemaError as exc:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="arc",
            got=v, message_ru=f"arc — недопустимая дуга: {exc}"))
        return None
    canonical = curve.to_dict()
    if p0 is not None and p1 is not None:
        a0, a1 = _arc_endpoints_mm(canonical)
        # Compare in the level PLAN plane (x/y) only: p0_mm/p1_mm carry no z
        # (the base level supplies it), while the arc's absolute z is its
        # capture elevation. Wall.Create projects the curve onto the base level,
        # so plan agreement is the correct, universal check — mirroring
        # _endpoint_check's three_d=False for the straight wall.
        def _xy(pt):
            return (pt[0], pt[1])
        # accept either endpoint orientation (Revit may store p0->p1 either way)
        forward = max(_dist(_xy(a0), _xy(p0)), _dist(_xy(a1), _xy(p1)))
        reverse = max(_dist(_xy(a0), _xy(p1)), _dist(_xy(a1), _xy(p0)))
        if min(forward, reverse) > _ARC_ENDPOINT_TOL_MM:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="arc",
                got=v, message_ru="arc: концы дуги не совпадают с p0_mm/p1_mm "
                                  f"(> {_ARC_ENDPOINT_TOL_MM} мм) — дуга и "
                                  "точки должны описывать одну кривую"))
            return None
    return canonical


#: Ceiling on a spiral stair run's radius, mm. NOT made up and NOT
#: derived by reasoning: this is the API's own DOCUMENTED bound,
#: verbatim — «The given value for radius must be greater than 0 and no
#: more than 30000 feet» (ArgumentOutOfRangeException from
#: `StairsRun.CreateSpiralRun`, RevitAPI.xml, identical across all six
#: shipped versions). 30000 feet × 304.8 mm/foot = 9,144,000 mm EXACTLY.
#: Refusing here is cheaper than learning the same thing from an
#: exception inside StairsEditScope on the user's machine.
_SPIRAL_RADIUS_MAX_MM = 30_000 * 304.8

#: Ceiling on the included angle, degrees. THE NUMBER IS ASSIGNED, and
#: here is exactly what justifies it: a run's path is ONE arc, and a
#: bounded Revit arc by construction is never longer than a full
#: revolution, so «more than 360°» is not a spiral run in the sense of
#: this call. The API does NOT name an upper bound (it only says
#: «includedAngle must be positive»), and it does not name the lower one
#: with a number either: «The includedAngle doesn't satisfy riser
#: restriction to generate spiral run (probably it's too small)» — this
#: bound depends on the riser height of the stair TYPE and on the
#: base→top rise, meaning it is unknown offline both to us and to the
#: program's author. We do NOT model it and do not make it up: from
#: below only the documented «strictly positive» stands, and the real
#: refusal comes from Revit, and it comes loudly.
_SPIRAL_MAX_INCLUDED_DEG = 360.0


def _validate_spiral(v: dict, i: int, oid: str, width_mm, diags: list):
    """Canonical spiral-run dict -> normalized dict|None.

    The form is exactly the one `StairsRun.CreateSpiralRun` accepts
    (identical across 2021-2026), but in KIR's AUTHOR units: millimeters
    and DEGREES. Radians of the canonical arc (`arc`) arrive from the
    reverse pass — an instrument writes them; a human or a model writes
    here instead, and every other author-facing angle in the language is
    measured in degrees (`rotation_deg`, `slopes[].angle_deg`). The
    conversion to radians is done by the emitter at COMPILATION; no
    trigonometry is left in C#.

    The `clockwise` key is required and intentionally WITHOUT A DEFAULT:
    the winding direction is visible in the model at first glance, and
    silently choosing «counterclockwise» on the author's behalf is
    exactly the «silently different result» this whole compiler exists
    to forbid.
    """
    required = {"center_mm", "radius_mm", "start_angle_deg",
                "included_angle_deg", "clockwise"}
    if set(v) != required:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="spiral",
            expected=sorted(required), got=sorted(v),
            message_ru="spiral — {center_mm: [x,y], radius_mm, "
                       "start_angle_deg, included_angle_deg, clockwise}"))
        return None
    if not _pt_ok(v["center_mm"], dims=(2,)):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
            field_name="spiral.center_mm", got=v["center_mm"],
            message_ru="spiral.center_mm — точка [x,y] мм (отметку центра "
                       "даёт base_level, а не автор: у CreateSpiralRun Z "
                       "центра И ЕСТЬ базовая отметка марша)"))
        return None
    if not isinstance(v["clockwise"], bool):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
            field_name="spiral.clockwise", got=v["clockwise"],
            message_ru="spiral.clockwise — true (по часовой) или false"))
        return None
    for key in ("radius_mm", "start_angle_deg", "included_angle_deg"):
        if not _num(v[key]):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                field_name=f"spiral.{key}", got=v[key],
                message_ru=f"spiral.{key} — конечное число"))
            return None
    radius = float(v["radius_mm"])
    if not 0.0 < radius <= _SPIRAL_RADIUS_MAX_MM:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid,
            field_name="spiral.radius_mm", got=radius,
            expected=f"0 < radius_mm <= {_SPIRAL_RADIUS_MAX_MM}",
            message_ru=(f"spiral.radius_mm вне границ самого API: радиус "
                        f"обязан быть больше 0 и не больше "
                        f"{_SPIRAL_RADIUS_MAX_MM:.0f} мм (30000 футов)")))
        return None
    included = float(v["included_angle_deg"])
    if not 0.0 < included <= _SPIRAL_MAX_INCLUDED_DEG:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid,
            field_name="spiral.included_angle_deg", got=included,
            expected=f"0 < included_angle_deg <= {_SPIRAL_MAX_INCLUDED_DEG}",
            message_ru=(f"spiral.included_angle_deg — строго положительный "
                        f"угол не больше {_SPIRAL_MAX_INCLUDED_DEG:.0f}° "
                        f"(путь марша — ОДНА дуга, а дуга длиннее полного "
                        f"оборота не бывает; направление задаёт clockwise, а "
                        f"не знак угла)")))
        return None
    # A DERIVED CHECK, NOT AN ASSIGNED ONE. A run is created with
    # `StairsRunJustification.Center` — the same one a straight run
    # uses — meaning the path arc runs along the MIDDLE of the run, and
    # the inner edge lies at radius `radius - width/2`. At
    # `radius <= width/2` an inner edge does not exist at all: this is
    # not a narrow staircase, it is not a staircase. This is exactly the
    # case the API names with its own refusal «The radius is too small
    # to generate a spiral run at the given justification», and here it
    # is caught BEFORE StairsEditScope, from the same two numbers the
    # compiler already has.
    if width_mm is not None and radius <= float(width_mm) / 2.0:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid,
            field_name="spiral.radius_mm", got=radius,
            expected=f"radius_mm > {float(width_mm) / 2.0}",
            message_ru=(f"spiral.radius_mm={radius:g} не больше половины "
                        f"width_mm={float(width_mm):g}: марш строится по "
                        f"середине (justification=Center), поэтому внутренняя "
                        f"кромка легла бы на радиус "
                        f"{radius - float(width_mm) / 2.0:g} мм — внутреннего "
                        f"края у такого марша нет")))
        return None
    return {"center_mm": [float(v["center_mm"][0]), float(v["center_mm"][1])],
            "radius_mm": radius,
            "start_angle_deg": float(v["start_angle_deg"]),
            "included_angle_deg": included,
            "clockwise": bool(v["clockwise"])}


def _impersonation_route(pspec, value) -> str | None:
    """An honest operation in place of the forbidden DirectShape
    category, or None.

    Triggers ONLY on an enum whose set of variants EXACTLY equals the
    closed table of DirectShape categories: that is the machine-checkable
    sign that «the ban on impersonation applies here», and it does not
    depend on either the op's name or the parameter's name. An op that
    declares a different set gets no route at all — silence here is
    cheaper than misdirected advice.
    """
    from kir.ops_shape import DIRECTSHAPE_CATEGORIES, IMPERSONATION_ROUTES

    if not isinstance(value, str):
        return None
    if set(pspec.choices) != set(DIRECTSHAPE_CATEGORIES):
        return None
    return IMPERSONATION_ROUTES.get(value)


def _kind_asserted_selector(sel, param):
    """A selector with a REDUNDANT `kind`, CROSS-CHECKED against the
    parameter's kind.

    🔴 INTRODUCED 26.08.2026 FROM A LIVE MEASUREMENT, AND THIS IS NOT A
    SOFTENING OF THE LAW. The most frequent cause of fresh corpus
    refusals — 17 of 188 over 25–26.08 — is a selector of the form
    {"by": "name", "value": "Уровень 1", "kind": "level"}. The mistake
    is a reasonable one: `kind` is a real field of the language, and for
    `query_count`/`query_list` it means the ELEMENT'S KIND. The model
    carries a familiar name over into a neighboring form.

    Before, this cost a round-trip and healed itself. But a parameter
    has its OWN declared kind (`ref_kinds`), and when the author writes
    the same kind as a second carrier, we end up holding TWO records of
    one quantity. Our named defect is «a quantity declared in one place
    and read in another, with nothing forcing them to match». Here we do
    exactly the opposite: WE FORCE THEM TO MATCH.

        matched        — a redundant confirmation, `kind` is dropped,
                         the program proceeds; it does not make it into
                         the normalized form
        mismatched     — a REFUSAL, and now a STRONGER one than before:
                         it names both kinds
        no kind at all — nothing to cross-check against, a REFUSAL as
                         before. Accepting it silently would be exactly
                         the silent agreement all of this exists against

    THE BOUNDARY IS NAMED: ONLY `kind` is dropped, and ONLY when the
    form is legal without it. Any other extra key, and `kind` alongside
    another extra key, still refuses as before — the closed set of
    selector keys is not weakened.
    """
    if not isinstance(sel, dict) or "kind" not in sel:
        return sel, None
    без = {k: v for k, v in sel.items() if k != "kind"}
    if not _sel_shape_ok(без):
        return sel, None
    рода = tuple(str(getattr(k, "value", k)) for k in (param.ref_kinds or ()))
    заявлен = sel.get("kind")
    заявлен = заявлен.strip() if isinstance(заявлен, str) else заявлен
    if рода and заявлен in рода:
        return без, None
    if not рода:
        return sel, ("`kind` сверить не с чем: у параметра «%s» род ссылки не "
                     "объявлен вовсе, поэтому подтверждать нечего — убери "
                     "`kind`" % param.name)
    return sel, ("`kind`: «%s» — а параметр «%s» принимает род %s. Это не "
                 "лишнее поле, это РАСХОЖДЕНИЕ: если род верен, то неверен "
                 "параметр, и наоборот" % (
                     заявлен, param.name,
                     ", ".join("«%s»" % k for k in рода)))


def _sel_shape_ok(sel) -> bool:
    if not isinstance(sel, dict):
        return False
    by = sel.get("by")
    if by == "family_type":
        if set(sel) != {"by", "category", "family_name", "type_name"}:
            return False
        return all(
            isinstance(sel.get(key), str) and bool(sel[key].strip())
            for key in ("category", "family_name", "type_name")
        )
    disambiguate_by = sel.get("disambiguate_by")
    if disambiguate_by is not None:
        if by not in ("name", "default"):
            return False
        if (not isinstance(disambiguate_by, dict)
                or set(disambiguate_by) not in ({"param", "value"},
                                                {"param", "value", "tol_mm"})):
            return False
        pname, pvalue = (disambiguate_by.get("param"),
                         disambiguate_by.get("value"))
        if not isinstance(pname, str) or not pname.strip():
            return False
        if not (pvalue is None or isinstance(pvalue, (str, bool))
                or _num(pvalue)):
            return False
        # A TOLERANCE IS LEGITIMATE ONLY FOR A NUMBER, AND ONLY A
        # POSITIVE ONE. A shape property arrives computed (a strip's
        # thickness, a face elevation), and exact equality of two floats
        # is a refusal where the mismatch is a micron. But a tolerance
        # on a string would mean «a similar name», i.e. guessing; on
        # zero it would mean «exactly», which is already expressed by
        # the field's absence.
        tol = disambiguate_by.get("tol_mm")
        if tol is not None:
            if not (_num(pvalue) and _num(tol) and float(tol) > 0.0):
                return False
    if by == "default":
        allowed = {"by", "disambiguate_by"} if disambiguate_by is not None else {"by"}
        return set(sel) == allowed
    allowed = ({"by", "value", "disambiguate_by"}
               if disambiguate_by is not None else {"by", "value"})
    if set(sel) != allowed:
        return False
    value = sel.get("value")
    if by in ("name", "ref"):
        return isinstance(value, str) and bool(value.strip())
    if by == "element_id":
        return (not isinstance(value, bool) and isinstance(value, int)
                and 1 <= value <= ELEMENT_ID_MAX)
    return False


def _move_witness_tol() -> float:
    """The tolerance the `move_elements` witness checks the move
    against.

    🔴 TAKEN FROM THE OP ITSELF, NOT AS A LITERAL. Validation rejects a
    move the witness will not be able to tell apart from zero; the
    threshold for the two of them must be ONE AND THE SAME, or they will
    drift apart at the first tolerance fix — this tree's named form of
    defect. A lazy import: `spec` pulls in this module.
    """
    from kir.spec import OPS

    op = OPS.get("move_elements")
    tol = (op.tolerances or {}).get("location_mm") if op else None
    return float(tol) if isinstance(tol, (int, float)) else 0.0


#: The shape Revit's own `Element.UniqueId` has: a GUID, a dash, and the
#: episode/element suffix in hex. Checked as a FORM, never as a promise that the
#: element exists — only the live document can answer that, and the emission
#: does, by name.
_VERSION_GUID_FORM = re.compile(r"[0-9a-fA-F]{32}")
_UNIQUE_ID_FORM = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}-[0-9a-fA-F]+")


def _target_w_ok(sel) -> bool:
    """Write-target selector: pinned id or intra-program ref (SPEC DAG)."""
    return _target_w_why(sel) is None


def _target_w_why(sel) -> str | None:
    """WHAT EXACTLY makes the selector unfit. `None` — it is fit.

    🔴 WHY A SEPARATE FUNCTION, FROM A LIVE-RUN MEASUREMENT ON
    22.08.2026. A refusal printed `ожидается: 1..500 селекторов {by:
    element_id|ref, value: ...}` and next to it `получено: [{'by':
    'element_id', 'value': '294076'}]`. These two lines MATCH
    CHARACTER-FOR-CHARACTER in form, and what decides is the TYPE of the
    value: for `element_id` it is an INTEGER, and the string `'294076'`
    is unfit. I spent two live turns in a row on this — even though the
    receipt promises «close what's missing in ONE turn», and the
    language's main user is an LLM, which has nothing beyond the
    refusal text.

    The reason lives RIGHT NEXT TO THE CHECK and is expressed through it
    (`_target_w_ok` calls this function); otherwise «fit» and «why
    unfit» would drift apart — exactly the two-carrier form the consent
    registry was set up against.
    """
    if not isinstance(sel, dict):
        return (f"селектор обязан быть словарём {{by, value}}, "
                f"а пришёл {type(sel).__name__}")
    extra = set(sel) - {"by", "value"}
    missing = {"by", "value"} - set(sel)
    if missing:
        return f"нет ключей: {', '.join(sorted(missing))}"
    if extra:
        return f"лишние ключи: {', '.join(sorted(extra))}"
    by = sel.get("by")
    v = sel.get("value")
    if by == "element_id":
        if isinstance(v, bool) or not isinstance(v, int):
            got = f"{v!r} ({type(v).__name__})"
            hint = ""
            if isinstance(v, str) and v.strip().isdigit():
                hint = f" — сними кавычки: {int(v.strip())}"
            return (f"by=element_id требует ЦЕЛОЕ значение, пришло {got}{hint}")
        if not (1 <= v <= ELEMENT_ID_MAX):
            return (f"by=element_id: значение вне 1..{ELEMENT_ID_MAX}, "
                    f"пришло {v}")
        return None
    if by == "ref":
        if not isinstance(v, str) or not v.strip():
            return (f"by=ref требует НЕПУСТУЮ строку — id операции этой же "
                    f"программы, пришло {v!r}")
        return None
    if by == "unique_id":
        # 🔴 ПОЧЕМУ ТРЕТЬЯ ФОРМА ВООБЩЕ ПОЯВИЛАСЬ. `element_id` — адрес ВНУТРИ
        # документа, и Ревит переиспользует его после удаления
        # (`kir/contracts.py:199-208` говорит это дословно). Между двумя
        # сеансами — а повторная публикация это ровно два сеанса — по числу
        # адресовать нельзя: то же число может указывать на ДРУГОЙ элемент, и
        # запись пройдёт молча. `UniqueId` живёт с элементом, и до 13.09.2026
        # его принимал ровно один оп языка — `query_element_state`, то есть
        # ЧИТАТЬ по личности было можно, а ПИСАТЬ нет.
        if not isinstance(v, str) or not v.strip():
            return (f"by=unique_id требует НЕПУСТУЮ строку — UniqueId элемента "
                    f"из квитанции или query_element_state, пришло {v!r}")
        if not _UNIQUE_ID_FORM.fullmatch(v):
            return (f"by=unique_id: не похоже на UniqueId Ревита "
                    f"(8-4-4-4-12 шестнадцатеричных и суффикс через дефис), "
                    f"пришло {v!r} — возьми значение поля element_identity.unique_id "
                    f"из квитанции создания или из query_element_state")
        return None
    return f"by обязан быть element_id, unique_id либо ref, пришло {by!r}"


#: WHERE stage-2 of the selector is legal at all — by a NAMED list, not
#: «everywhere `refs_w` appears». A face is part of an element's body;
#: `move_elements.targets` is also `refs_w`, but «move a face» means
#: nothing, and allowing the form by the parameter's KIND would mean
#: shipping a meaningless operation as a side effect. A new carrier is
#: added here explicitly, together with its emitter.
_FACE_SEL_SITES: frozenset = frozenset({("create_dimension", "refs")})


def _face_sel_key(sel: dict) -> tuple:
    """The IDENTITY key of a face selector — for the same repeat check.

    A repeat is forbidden for the same reason as at stage 1: a dimension
    between a face and itself is a zero dimension. Two DIFFERENT faces
    of one element, however, are legal and must be distinguished by the
    key, so the predicate is part of the key."""
    inner = sel["of"]
    pred = sel["predicate"]
    return (faceref.BY_FACE, inner["by"],
            inner["value"].strip() if inner["by"] == "ref" else inner["value"],
            pred.get("side"),
            tuple(pred["normal"]) if "normal" in pred else None)


def _validate_refs_w_with_faces(v: list, *, name: str, param, oid: str, i: int,
                                lo: int, hi: int, reject_dupes: bool,
                                diags: list) -> list | None:
    """`refs_w` that contains at least one FACE selector (stage 2).

    Returns a normalized list or None (refusals are already in `diags`).

    The order of checks is chosen so that a refusal names ITS OWN
    reason: first «there is no form at all» (flag/carrier), then each
    element's form, and only then length and repeats. The reverse order
    would answer «a list of 2..16 element_id/ref selectors» on a
    correctly written face — meaning it would send the repair to the
    wrong place."""
    where = param.name
    if (name, param.name) not in _FACE_SEL_SITES:
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=i, op_id=oid, field_name=where,
            expected="element_id|ref", got=faceref.BY_FACE,
            message_ru=(
                f"{where}: селектор грани у операции «{name}» не принят — "
                f"грань адресует ЧАСТЬ ТЕЛА элемента, и смысл у этого есть "
                f"только там, где операция действительно связывается с "
                f"гранью. Носители названы поимённо: "
                f"{sorted(f'{o}.{p}' for o, p in _FACE_SEL_SITES)}")))
        return None
    if not faceref.face_ref_enabled():
        diags.append(Diagnostic(
            code=GROUND_BAD_SELECTOR, op_index=i, op_id=oid, field_name=where,
            expected="element_id|ref", got=faceref.BY_FACE,
            message_ru=(
                f"{where}: селектор грани выключен флагом оператора "
                f"{faceref.FACE_REF_FLAG} (по умолчанию ВЫКЛ). Пока он "
                f"выключен, грань назвать нельзя: адресуй элемент целиком "
                f"({{\"by\": \"element_id\"|\"ref\"}}) — компилятор возьмёт "
                f"геометрическую ссылку сам, но КАКУЮ именно, программа не "
                f"назовёт")))
        return None
    if not (isinstance(v, list) and lo <= len(v) <= hi):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=where,
            expected=f"{lo}..{hi} селекторов", got=v,
            message_ru=f"{where} — список из {lo}..{hi} селекторов"))
        return None
    out: list[dict] = []
    keys: list[tuple] = []
    for j, x in enumerate(v):
        if faceref.is_face_sel(x):
            face = faceref.validate_face_sel(
                x, oid=oid, field=param.name, i=j,
                inner_ok=_target_w_ok, diags=diags)
            if face is None:
                return None
            if not param.ref_kinds and face["of"]["by"] == "ref":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=f"{where}[{j}].of", expected="element_id", got=x,
                    message_ru=(f"{where}[{j}].of: intra-program ref не "
                                "разрешён типизированным контрактом "
                                "параметра")))
                return None
            # THE INNER SELECTOR IS NORMALIZED THE SAME WAY AS THE OUTER
            # ONE, and this is not tidiness. The compiler graph
            # traversal walks NORMALIZED ops and checks `value` against
            # op ids; stage 1 trims whitespace (below), and an untrimmed
            # stage 2 would produce KIR-L003 «ref не указывает на более
            # ранний оп» on a reference that does point to one — a
            # diagnosis that sends the repair to the wrong place.
            inner_sel = face["of"]
            face = dict(face, of={
                "by": inner_sel["by"],
                "value": (inner_sel["value"].strip()
                          if inner_sel["by"] == "ref" else inner_sel["value"])})
            out.append(face)
            keys.append(_face_sel_key(face))
        elif _target_w_ok(x):
            if not param.ref_kinds and x.get("by") == "ref":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=where, expected="только element_id-селекторы",
                    got=v,
                    message_ru=(f"{where}: intra-program ref не разрешён "
                                "типизированным контрактом параметра")))
                return None
            val = x["value"].strip() if x["by"] == "ref" else x["value"]
            out.append({"by": x["by"], "value": val})
            keys.append((x["by"], val))
        else:
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                field_name=f"{where}[{j}]",
                expected='{by: element_id|ref} либо {by: face, of, predicate}',
                got=x,
                message_ru=(f"{where}[{j}] — селектор элемента "
                            "(element_id/ref) либо селектор грани")))
            return None
    if reject_dupes and len(set(keys)) != len(keys):
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=where, got=v,
            message_ru=(f"{where}: повторяющийся селектор — нулевой размер "
                        "размера недопустим")))
        return None
    return out


#: KINDS THAT THIS FILE DOES NOT PARSE — WITH THE ADDRESS OF WHOEVER
#: DOES.
#:
#: The list was set up AGAINST TYPOS, so it is not «miscellaneous» but a
#: census: every key is named together with the place where its kind is
#: actually checked, and a new key cannot be added here without naming
#: such a place. Otherwise the list would become exactly the hole the
#: lock below closes.
#:
#: All four stand ONLY on ops of the query family, and
#: `compiler._validate_op` goes into `validate()` only for
#: `spec.WRITE_FAMILIES` — meaning today they never reach the loop below
#: at all. They are recorded because this is a fact about the LAYOUT
#: (who judges whom), not about today's route: moving an op between
#: families must not turn into silence.
_KINDS_VALIDATED_ELSEWHERE: dict[str, str] = {
    "kind_enum": "compiler._validate_op -> _check_kind (query_count/query_list)",
    "filters": "compiler._validate_op -> _check_filters (query_count/query_list)",
    "fields": "compiler._validate_op, ветка `name == \"query_list\"`",
    "target": "compiler._validate_op, ветка `name == \"query_inspect\"`",
}


def _assert_kind_dispatched(p, op_name: str) -> None:
    """A LOCK AGAINST A TYPO IN `ParamSpec.kind`.

    `kind` is an OPEN string: it has no closed enum, `spec._lint_registry`
    does not check it (that one is about capability cells), and a typo
    in a new kind fails nowhere. The chain below is an `if/elif` with no
    tail, so a parameter with an unrecognized kind is not merely «not
    checked»: it also does not make it into `norm`, meaning it travels
    onward as if the author had never written it. A refusal would have
    noticed this; silence does not.

    The exception is a PROGRAMMER's error, not the program author's, so
    here it is an `AssertionError`, not a `Diagnostic`: a diagnostic
    would tell the user that they are at fault, and would refuse a
    correct program. The same device, for the same reason, already
    stands in `schema_gen` (`unknown param kind`) and in `dsl` — this
    third lock is needed because the first two guard SOMEONE ELSE'S
    passages: before 07.08 a typo was only caught if someone happened to
    generate the schema.
    """
    if p.kind in _KINDS_VALIDATED_ELSEWHERE:
        return
    if p.kind in ("pt_xy", "pt_xyz") and p.name in ("p0_mm", "p1_mm"):
        # The segment's ends are DELIBERATELY excluded from the loop's
        # first branch: the pair is checked and normalized AS A WHOLE
        # before the loop (that is also where the «length ~0» law
        # lives, which needs both points at once). A branch working on
        # one point would cut that law in half.
        return
    raise AssertionError(
        f"{op_name}.{p.name}: вид {p.kind!r} не разбирает ни одна ветвь "
        f"`authoring_validation.validate`, и в `norm` параметр не попадёт — "
        f"опечатка в `ParamSpec.kind` либо новый вид без ветви. Если вид "
        f"разбирается в другом файле, назовите его в "
        f"`_KINDS_VALIDATED_ELSEWHERE` вместе с адресом разбора")


def validate(op: dict, name: str, i: int, oid: str, diags: list) -> dict:
    """Structural typecheck for authoring ops; deep resolution is ground.py's."""
    # Refusals of THIS call, not of the whole program: `diags` is
    # shared across all ops, and enriching someone else's is not
    # allowed — a neighboring op has a different slot registry.
    _diag_start = len(diags)
    norm: dict[str, Any] = {"op": name, "id": oid}
    ospec = spec.OPS[name]
    has_pts = any(pp.name == "p0_mm" for pp in ospec.params)
    endpoint_spec = next((p for p in ospec.params if p.name == "p0_mm"), None)
    dims = (3,) if endpoint_spec and endpoint_spec.kind == "pt_xyz" else (2,)
    # A segment's ends can be OPTIONAL (place_family: either a point or
    # a curve). Before 27.07 every p0_mm/p1_mm in the registry was
    # required=True, so the absence of a value was not distinguished
    # from a value of the wrong form — and an optional pair produced
    # «p0_mm — точка в мм» on a program where there is, and should be,
    # no curve. The skip repeats the same guard,
    # `if v is None and not p.required`, that appears a few lines
    # below: a required pair is still checked verbatim.
    _pt_required = {
        pp.name: pp.required for pp in ospec.params
        if pp.name in ("p0_mm", "p1_mm")}
    # RELATE (04.08): a parameter's addressability is a question for the
    # REGISTRY, not for a list here. `relate.addressable_params` derives
    # it from the pt_xy/pt_xyz kind, with one NAMED exception
    # (`move_elements.delta_mm` — an offset, not a position). A list of
    # our own would become a fourth judge and would drift apart on the
    # very first new op.
    _addressable = relate.addressable_params(name)
    for key in (("p0_mm", "p1_mm") if has_pts else ()):
        v = op.get(key)
        if v is None and not _pt_required.get(key, True):
            continue
        if relate.is_address(v) and key in _addressable:
            if relate.validate_address(v, oid, key, diags,
                                       dims=_addressable[key]):
                norm[key] = v
            continue
        if not _pt_ok(v, dims=dims):
            граница = (_point_bounds_diag(v, i=i, oid=oid, field=key)
                       if _pt_shape_ok(v, dims) else None)
            diags.append(граница or Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=key,
                expected=f"[x,y{',z' if dims == (3,) else ''}] мм (числа)", got=v,
                message_ru=f"{key} — точка в мм"))
        else:
            norm[key] = v
    # The «length ~0» law is a pure function of NUMBERS, and when the
    # numbers arrive from a snapshot, it must move across the same line
    # with them, not get lost. The second call to the same function
    # stands in `ground` (one implementation, two call sites); an
    # instrument that stays silent over part of the range is more
    # dangerous than a missing one.
    if ("p0_mm" in norm and "p1_mm" in norm
            and not relate.is_address(norm["p0_mm"])
            and not relate.is_address(norm["p1_mm"])):
        reject_zero_length(norm["p0_mm"], norm["p1_mm"], name, i, oid, diags)
    for p in ospec.params:
        if p.kind == "dir_xyz":
            # 🔴 DIRECTION IS A SEPARATE KIND, AND THIS WAS PAID FOR BY
            # A MEASUREMENT ON 21.08.2026. `ref_dir` had been declared
            # as `pt_xyz`, i.e. as a POINT. Running
            # `program_source._shift` on a real value:
            #
            #     ref_dir [-1, 0, 0]  ->  [-1001.0, -500.0, 0.0]
            #
            # The direction picked up the local frame's origin and
            # stopped being a unit vector. Not one check would have
            # failed: a list of three numbers remains a legal list of
            # three numbers. Exactly the form `FREE_KEYS` was already
            # set up against for the plane («_shift would have
            # subtracted the local frame's origin from a DIRECTION») —
            # but there the KEY inside a dict is protected, while here
            # the quantity sits as a PARAMETER, with no key at all.
            #
            # The defect slept for one reason: `create_solid_sweep`'s
            # reverse pass is `capture_gap`. `place_family`'s is
            # `direct`, and it has the same `ref_dir`: the very first
            # lifter that decided to express a rotation as a direction
            # would have woken this up silently.
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if not _pt_ok(v, dims=(3,)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, expected="направление [x,y,z]", got=v,
                    message_ru=(f"{p.name} — НАПРАВЛЕНИЕ [x,y,z], "
                                f"безразмерное. Не точка и не миллиметры: "
                                f"длина не важна, важен только луч")))
            elif all(float(c) == 0.0 for c in v):
                # 🔴 EQUALITY TO ZERO, NOT A THRESHOLD, AND THIS IS A
                # FIX TO MY OWN CHANGE (21.08.2026, found by a fork the
                # same day). The branch's first edition wrote
                # `_dist(...) < 1e-9` — that is, it introduced A NUMBER
                # NOBODY HAD MEASURED, next to a number Revit reports
                # itself. The previous path (`pt_xyz`) rejected an
                # EXACT zero and forbade a threshold verbatim, in its
                # own comment; I moved the parameter to a new kind and
                # lost the ban along with it.
                #
                # THE MEASUREMENT that showed the difference: the old
                # path LET [1e-10, 0, 0] THROUGH (correctly — Revit
                # either normalizes an almost-zero vector itself or
                # refuses it with its own number), while my edit
                # rejected it. The op was losing a legitimate program to
                # our own invention.
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid,
                    field_name=p.name, expected="ненулевой вектор", got=v,
                    message_ru=(f"{p.name}: нулевой вектор — направления нет, "
                                f"отсчитывать не от чего. Почти-нулевой "
                                f"НЕ отвергается: свой порог здесь был бы "
                                f"числом, которого никто не мерил, а Ревит "
                                f"сообщает своё сам")))
            else:
                norm[p.name] = [float(v[0]), float(v[1]), float(v[2])]
        elif p.kind in ("pt_xy", "pt_xyz") and p.name not in ("p0_mm", "p1_mm"):
            v = op.get(p.name)
            if relate.is_address(v) and p.name in _addressable:
                if relate.validate_address(v, oid, p.name, diags,
                                           dims=_addressable[p.name]):
                    norm[p.name] = v
                continue
            # wave/struct (2026-07-17): OPTIONAL pt_xy/pt_xyz — needed for
            # create_foundation's kind-discriminated xy (isolated-only;
            # absent for kind=slab). Every PRE-EXISTING pt_xy/pt_xyz param
            # across the registry is required=True, so an omitted value was
            # never legitimately None before this — this None-skip mirrors
            # the mm/sel/str kinds' own "if v is None: continue" convention
            # a few lines below and changes nothing for any required param
            # (still validated exactly as before when present or missing-
            # but-required, since required-ness is enforced at ground.py for
            # sel and implicitly by this same _pt_ok check for a REQUIRED
            # pt_xy/pt_xyz — None only reaches here for an optional one).
            if v is None and not p.required:
                continue
            d2 = (3,) if p.kind == "pt_xyz" else (2,)
            if not _pt_ok(v, dims=d2):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="точка в мм", got=v,
                    message_ru=f"{p.name} — точка [x,y{',z' if d2 == (3,) else ''}] мм"))
            # move_elements.delta_mm (28.07 SRC PIN, live schema_gen
            # collision): reuses pt_xyz's SCHEMA-recognized shape (schema_gen
            # is exhaustive/foreign-dirty — no new kind), but it is a
            # DISPLACEMENT, not an absolute position, so the generic
            # _COORD_LIMIT_MM (16 000 000mm workable-extent bound) is the
            # wrong ceiling — the design's own 100_000mm (100m) per-
            # component bound is tighter, and only applies to this op/param.
            elif name == "move_elements" and p.name == "delta_mm" \
                    and not all(_num(c) and abs(c) <= 100_000 for c in v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="[dx,dy,dz] мм, |компонент| <= 100000", got=v,
                    message_ru=f"{p.name} — вектор [dx,dy,dz] мм, "
                               "|компонент| не более 100000"))
            # 🔴 WHAT IS REJECTED IS NOT JUST AN EXACT ZERO, BUT ANY
            # MOVE BELOW THE WITNESS'S TOLERANCE (22.08.2026). Here
            # stood `float(c) == 0.0`, and this left a blind strip: the
            # `location` commitment's tolerance is `location_mm = 1.0`
            # mm, meaning a move whose ALL THREE components are no more
            # than a millimeter in absolute value COUNTS AS FULFILLED,
            # even if Revit silently did nothing at all. The op commits
            # green on a fulfilled commitment — meaning the witness
            # signs off on something it could not tell apart.
            #
            # This is NOT introducing a threshold in place of equality
            # (a recorded ban: for a DIRECTION a threshold would be a
            # lie, see `dir_xyz` below). Here the quantity is in
            # MILLIMETERS, and the number is taken not from taste but
            # from the TOLERANCE OF THE SAME OP — no second carrier is
            # introduced.
            #
            # Refusing BEFORE emission is cheaper than rolling back
            # after a commit: a program with a move like this is
            # unprovable by construction, and it is better to say so
            # right away.
            elif name == "move_elements" and p.name == "delta_mm" \
                    and all(_num(c) and abs(float(c))
                            <= _move_witness_tol() for c in v):
                tol = _move_witness_tol()
                zero = all(float(c) == 0.0 for c in v)
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    got=v,
                    message_ru=(
                        f"{p.name}: нулевой перенос — переносить нечего"
                        if zero else
                        f"{p.name}: перенос НЕДОКАЗУЕМ — все компоненты по "
                        f"модулю не больше допуска свидетеля {tol:g} мм, и "
                        f"«сдвинулось» будет неотличимо от «не сдвинулось». "
                        f"Задай смещение больше {tol:g} мм либо не двигай")))
            # wave/mass (2026-08-10): create_face_wall.face_normal —
            # the same device as `delta_mm` a line above, for the same
            # reason (`schema_gen` is exhaustive, the [x,y,z] form is
            # already recognized, and a new kind just for a value of
            # the same form would have cost an edit in every consumer
            # of the schema). The difference from a move is in the
            # UNITS: this is a DIRECTION, not millimeters, so the
            # coordinate ceiling (_COORD_LIMIT_MM, the model's working
            # extent) does not apply to it at all — a direction has no
            # length that matters to the operation; it is normalized in
            # Revit.
            #
            # EXACTLY ONE THING IS REJECTED: AN EXACT ZERO. This is not
            # a threshold and not a tolerance, but degeneracy by
            # definition — there is no direction at [0,0,0] in any
            # system. An «almost zero» vector is deliberately NOT
            # touched here: only Revit knows where that boundary runs,
            # and it answers that question with its own
            # `XYZ.IsZeroLength()` already at runtime (the
            # `faceref.resolve_cs` emission places a typed refusal
            # there). Assigning a threshold here would mean introducing
            # a number nobody measured, next to a number Revit reports
            # itself.
            elif name == "create_face_wall" and p.name == "face_normal" \
                    and all(_num(c) and float(c) == 0.0 for c in v):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected="ненулевой вектор [x,y,z]", got=v,
                    message_ru=(f"{p.name}: нулевой вектор — направления в "
                                f"[0,0,0] нет, называть грань нечем")))
            else:
                norm[p.name] = v
        elif p.kind == "mm":
            v = op.get(p.name, p.default)
            if v is None:
                # Same PRE-EXISTING GAP class as the str-kind branch above:
                # a MISSING required mm param (create_window/door.offset_mm
                # are already required=True — same latent bug, just never
                # exercised by an existing negative test; create_type.width_mm
                # is the one that surfaced it) used to `continue` silently and
                # panic emit-side with a raw KeyError instead of a typed
                # refusal. Fixed for every required mm param, additive.
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            if not _num(v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="число (мм)", got=v, message_ru=f"{p.name} — число в мм"))
            elif ((p.min_val is not None and v < p.min_val)
                  or (p.max_val is not None and v > p.max_val)):
                if p.min_val is None:
                    expected = f"<= {p.max_val}"
                    replacement = p.max_val
                elif p.max_val is None:
                    expected = f">= {p.min_val}"
                    replacement = p.min_val
                else:
                    expected = f"{p.min_val}..{p.max_val}"
                    replacement = min(max(v, p.min_val), p.max_val)
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=expected, got=v,
                    suggested_replacement=replacement,
                    applicability="maybe-incorrect",
                    message_ru=f"{p.name} вне границ {expected} мм"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "deg":
            # Additive angle kind: keep an omitted default implicit so old
            # normalized programs, program hashes and emitted C# do not move.
            # Explicit values remain in degrees and are compared modulo 2*pi
            # by the live postcondition.
            #
            # THE REQUIREDNESS OF THE `deg` KIND WAS UNENFORCEABLE
            # BEFORE 10.08.2026. This branch exited via `not in op`
            # EARLIER than anyone asked `p.required`, meaning
            # `required=True` on an angle was a promise the validator
            # did not keep: a program missing a required angle reached
            # the emitter and crashed there with a KeyError (KIR-P000
            # «внутренняя ошибка») instead of a named refusal. As long
            # as every angle in the registry was optional
            # (`rotation_deg`, default=0.0), the hole went
            # unobserved — exactly «an instrument for only part of the
            # range». The reinforcement wave brought the first required
            # angle (`create_area_reinforcement.direction_deg`: the
            # working rebar's principal direction, which has no default
            # and should not have one), and the hole became reachable.
            # The fix is ADDITIVE: nothing changes, not by one byte,
            # for optional angles.
            if p.name not in op:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, expected="конечное число (градусы)",
                        message_ru=f"{p.name} обязателен — угол в градусах"))
                continue
            v = op.get(p.name)
            if not _num(v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, expected="конечное число (градусы)",
                    got=v, message_ru=f"{p.name} — угол в градусах"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "sel":
            sel = op.get(p.name)
            if sel is None:
                # Requiredness is a property of the authored program, not of
                # the model snapshot.  Program-envelope defaults have already
                # been applied before this validator runs, so an absent value
                # here cannot become valid during grounding.  Deferring the
                # refusal used to let PlannedProgram represent an impossible
                # program and made the same input fail at a different stage
                # depending on whether a caller happened to invoke ground().
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected="обязательный селектор",
                        message_ru=f"{p.name} обязателен"))
                continue
            sel, _kind_note = _kind_asserted_selector(sel, p)
            if not _sel_shape_ok(sel):
                # 🔴 THE EXTRA KEY IS NAMED BY NAME (26.08.2026, a live
                # turn).
                #
                # Twice out of two, the model sent a level selector
                # with an extra field: {"by": "name", "value": "Уровень
                # 1", "kind": "level"}. The refusal printed what was
                # received IN FULL and the form it expects — and left
                # the author to compare them by eye. Each time this cost
                # an extra round-trip; it self-heals, but is paid for
                # again every time.
                #
                # The mistake, though, is REASONABLE, not careless:
                # `kind` is a real field of the language, and for
                # `query_count`/`query_list` it means the element's
                # kind. The model carried a familiar name over into a
                # neighboring form where it does not belong. One token
                # for two different things is our named defect, and
                # here it is caught on the reader's side, not the
                # author's.
                #
                # The selector's key set is CLOSED (`_sel_shape_ok`
                # above), so what is extra is computed EXACTLY, not
                # guessed. We count only what does not occur under ANY
                # form of `by`: a key that is extra only for the chosen
                # form would be wrong to name as such.
                хвост = ""
                if isinstance(sel, dict):
                    вообще = {"by", "value", "disambiguate_by",
                              "category", "family_name", "type_name"}
                    лишние = sorted(set(sel) - вообще)
                    # 🔴 Since 26.08 `kind` is NO LONGER an "extra field", and
                    # calling it that would be lying about our own law: when the
                    # kind matches, we ACCEPT it. Since the check has spoken, the
                    # general text about a closed set no longer applies to
                    # `kind`.
                    if _kind_note:
                        лишние = [k for k in лишние if k != "kind"]
                    if лишние:
                        хвост = (". ЛИШНЕЕ ПОЛЕ: %s — селектор его не несёт "
                                 "ни при какой форме `by`; убери его"
                                 % ", ".join("«%s»" % k for k in лишние))
                        if "kind" in лишние:
                            хвост += (". `kind` существует у query_count и "
                                      "query_list, где означает РОД ЭЛЕМЕНТА, "
                                      "а не часть селектора")
                if _kind_note:
                    хвост += ". " + _kind_note
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "name|element_id|default", "value": "..."}, got=sel,
                    message_ru=f"{p.name} — селектор{хвост}"))
            elif (sel.get("by") == "family_type"
                  and not (name == "place_family" and p.name == "symbol")):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected={"by": "name|element_id|default"}, got=sel,
                    message_ru=("family_type поддержан только для "
                                "place_family.symbol")))
            elif sel.get("by") == "ref" and not p.ref_kinds:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "name|element_id|default"}, got=sel,
                    message_ru=(f"{p.name}: intra-program ref не разрешён "
                                "типизированным контрактом параметра; "
                                "используйте element_id/каталожный селектор")))
            else:
                norm[p.name] = dict(sel)
                if sel.get("by") == "family_type":
                    for key in ("category", "family_name", "type_name"):
                        norm[p.name][key] = sel[key].strip()
                if sel.get("by") in ("name", "ref"):
                    norm[p.name]["value"] = sel["value"].strip()
                if "disambiguate_by" in sel:
                    norm[p.name]["disambiguate_by"] = dict(sel["disambiguate_by"])
                    norm[p.name]["disambiguate_by"]["param"] = \
                        sel["disambiguate_by"]["param"].strip()
        elif p.kind == "sel_list":
            # Plural kind `sel` (wave/datums): a list of selectors from ONE
            # pool. The shape of each element is checked by the same
            # `_sel_shape_ok` as a single selector — one implementation,
            # two sites; a separate parser would diverge from `sel` at the
            # very first new selector kind.
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected="список селекторов (1..64)", got=v,
                        message_ru=f"{p.name} — список селекторов"))
                continue
            # ONE LAW, TWO CARRIERS — AND THEY MUST MATCH. The check for a
            # redundant `kind` was set up for the `sel` kind; if the selector
            # list had not received it, an author who wrote `kind` would pass
            # on one parameter and be refused on the neighboring one — exactly
            # the carrier divergence that OPS_WITH_DOC_DEFAULT_TYPE (4 vs 8)
            # was bought to fix.
            _kind_note = None
            if isinstance(v, list):
                _пары = [_kind_asserted_selector(s, p) for s in v]
                v = [_с for _с, _ in _пары]
                _kind_note = next((_n for _, _n in _пары if _n), None)
            if not (isinstance(v, list) and 1 <= len(v) <= 64
                    and all(_sel_shape_ok(s) for s in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected="список из 1..64 селекторов", got=v,
                    message_ru=(f"{p.name} — список из 1..64 селекторов"
                                + (". " + _kind_note if _kind_note else ""))))
                continue
            bad_ref = next((s for s in v
                            if s.get("by") == "ref" and not p.ref_kinds), None)
            bad_ft = next((s for s in v if s.get("by") == "family_type"), None)
            if bad_ref is not None or bad_ft is not None:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected={"by": "name|element_id|default"},
                    got=bad_ref if bad_ref is not None else bad_ft,
                    message_ru=(f"{p.name}: селектор такого вида здесь не "
                                "разрешён — имя, element_id или default")))
                continue
            out_sels = []
            for s in v:
                one = dict(s)
                if s.get("by") in ("name", "ref"):
                    one["value"] = s["value"].strip()
                if "disambiguate_by" in s:
                    one["disambiguate_by"] = dict(s["disambiguate_by"])
                    one["disambiguate_by"]["param"] = \
                        s["disambiguate_by"]["param"].strip()
                out_sels.append(one)
            # A REPEAT IS A REFUSAL, NOT A SILENT MERGE. A set in which one
            # level appears twice is indistinguishable from a set in which it
            # was named once; but a program that wrote it twice almost
            # certainly meant TWO different levels and got the name wrong. By
            # silently collapsing it we would build a staircase with a
            # different number of floors than requested, and the equal-set
            # witness would MISS it.
            seen: list = []
            for one in out_sels:
                key = json.dumps(one, sort_keys=True, ensure_ascii=False)
                if key in seen:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name,
                        message_ru=(f"{p.name}: селектор повторён "
                                    f"({one.get('value', one.get('by'))}) — "
                                    "повтор в множестве неотличим от "
                                    "опечатки в имени соседа")))
                    break
                seen.append(key)
            else:
                norm[p.name] = out_sels
        elif p.kind == "num":
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            if not _num(v):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="число", got=v, message_ru=f"{p.name} — число"))
            elif not (p.min_val <= v <= p.max_val):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"{p.min_val}..{p.max_val}", got=v,
                    message_ru=f"{p.name} вне границ"))
            else:
                norm[p.name] = float(v)
        elif p.kind == "target_w":
            sel = op.get(p.name)
            if sel is None and not p.required:
                # Optional target_w (Documentation family: dim_type/tag_type/
                # text_type/leader_to) — absence is a legal "use doc default"
                # signal, handled in-emit (IN_EMIT_DEFAULT pattern), NOT a
                # missing-selector diagnostic (that would wrongly reject every
                # program that omits an optional catalog type).
                continue
            # "host — ref only" comes from the door and window kind: their
            # host must be built by this same program. For a curtain-wall
            # panel that is not the case — the 2026-07-28 design writes
            # `host: ref|element_id` directly into the signature: "change the
            # panel in this curtain wall" refers to an ALREADY EXISTING wall
            # that the program did not create. The rule has been narrowed to
            # the ops for which it was actually the law, not lifted — nothing
            # changed for the rest.
            #
            # host: element_id (28.07, audit — the most common external
            # scenario: "put a window in MY wall"). The ref path is NOT
            # touched by a single byte — ref remains the only lawful form for
            # ALL other target_w host fields (place_family along a curve,
            # etc.); it is narrowed TO create_door/create_window, not lifted
            # entirely. compiler.py (the plan stage) looks up host.value in
            # byid — a table indexed by op-row id; element_id is an int and by
            # construction is not there, __host_wall__ is not attached, and
            # the compile-time "offset past the wall edge" check does NOT fire
            # for this branch. The law is not lifted — it has moved to
            # runtime (_emit_hosted: a live read of the host's
            # LocationCurve).
            # create_curtain_grid_line: the same case as the panel — the
            # layout is edited on an EXISTING curtain wall too ("add a
            # mullion to this wall"), not only on one created by this same
            # program.
            # create_railing: the same case as the curtain-wall panel and the
            # grid line — a railing gets hung on an EXISTING stair too ("put a
            # railing along this stair"), not only on one created by this same
            # program. For the reverse pass this is in fact the only possible
            # kind of reference at all: for a railing pulled up from the
            # model, the owner is a stair with a real element_id, and the
            # op-row that created it is not, and cannot be, in the program.
            # create_opening: the same case as the curtain panel, the grid
            # line, and the railing — and MOREOVER, the primary one. An
            # opening is cut into something that IS ALREADY STANDING ("make
            # an opening in this slab"), and a host built by this same
            # program is the special case. Requiring ref would mean banning
            # the main scenario of the operation.
            # create_face_wall: the same case, and also the PRIMARY one. A
            # wall by face is built on a mass that IS ALREADY STANDING in the
            # model ("make a wall along this roof slope"); a mass placed by
            # this same program via place_family is the special case.
            # Requiring ref would mean banning the main scenario of the
            # operation.
            # create_wall_sweep / create_slab_edge: the same case as the
            # opening, and also PRIMARY. A cornice is hung on a wall that IS
            # ALREADY STANDING ("put a molding along this wall"), a drip edge
            # goes along the edge of an already-built slab. A host created by
            # this same program is the special case; requiring ref would mean
            # banning the main scenario of both operations.
            # create_area_reinforcement: the same case as the opening and the
            # cornice, and also PRIMARY. You reinforce a slab that IS ALREADY
            # STANDING ("reinforce this slab"); a slab built by this same
            # program is the special case. Requiring ref would mean banning
            # the main scenario of the structural-reinforcement section.
            if p.name == "host" \
                    and name not in ("set_curtain_panel",
                                     "create_curtain_grid_line",
                                     "create_railing",
                                     "create_opening",
                                     "create_wall_sweep",
                                     "create_slab_edge",
                                     "create_area_reinforcement",
                                     "create_face_wall") \
                    and name not in ("create_door", "create_window") \
                    and isinstance(sel, dict) and sel.get("by") != "ref":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=sel, message_ru="host в v1 — только ref на create_wall этой же программы"))
            # change_type.type: element_id is MANDATORY in v1 (28.07, CLASH) —
            # NOT ref (there is no op that creates types except create_type —
            # a ref to it would work, but that is the next wave, not
            # freelancing in this one) and not a name (there is no snapshot
            # pool across ALL categories — the same honestly declared gap as
            # for panel_type, except there the compiler can search with a
            # collector limited to TWO known type spaces, whereas here the
            # target's category is not known in advance to any space at
            # all).
            elif p.name == "type" and name == "change_type" \
                    and isinstance(sel, dict) and sel.get("by") != "element_id":
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "element_id"}, got=sel,
                    message_ru="type в v1 — только element_id (нет снапшот-пула "
                               "типов по всем категориям)"))
            elif (почему := _target_w_why(sel)) is not None:
                # 🔴 THE REASON WAS COMPUTED AND THEN DISCARDED. Before
                # 25.08.2026 the NEIGHBORING boolean `_target_w_ok` was called
                # here, and the text written was generic: "— an element_id or
                # ref selector." The model sent
                # {"by": "element_id", "value": "743932"} — exactly the shape
                # the refusal described to it — and repeated it, because there
                # was nothing in the text to fix from.
                #
                # LIVE-CORPUS MEASUREMENT: 670 `join_elements` refusals in a
                # SINGLE day, 23.08 — 40% of all refusals for the week, all on
                # these two fields. Checkability did not change the model's
                # decision even once.
                #
                # `_target_w_why` was set up on 22.08 for EXACTLY this case;
                # its docstring: "decides the value's TYPE… I spent two live
                # turns in a row on this." It can answer "strip the quotes:
                # 743932." All that remained was to call it.
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"by": "element_id|unique_id|ref", "value": "..."}, got=sel,
                    message_ru=f"{p.name}: {почему}"))
            elif sel.get("by") == "ref" and not p.ref_kinds:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected={"by": "element_id"}, got=sel,
                    message_ru=(f"{p.name}: intra-program ref не разрешён "
                                "типизированным контрактом параметра")))
            else:
                value = sel["value"].strip() if sel["by"] == "ref" else sel["value"]
                norm[p.name] = {"by": sel["by"], "value": value}
        elif p.kind == "identity":
            # 🔴 THE BASE, NOT THE ADDRESS. `target` says WHICH element to
            # change; this says WHICH ELEMENT THE AUTHOR LOOKED AT before
            # deciding. Both fields are checked at the op, and the refusal there
            # names the op — a program-level pin would only be able to say that
            # SOMETHING moved.
            v = op.get(p.name)
            # 🔴 `unique_id` IS THE ONLY STRONG FIELD (13.09.2026, lead's word).
            # RevitAPI.xml 2023 on `Element.UniqueId`: «stable across upgrades
            # and workset operations such as Save To Central» — it survives
            # exactly what breaks the version. `version_guid` is OPTIONAL and is
            # «версия СОХРАНЁННОГО файла, не свежесть»: its period is between two
            # saves, so in-session it cannot detect a change and across a save it
            # moves without one. It is carried whenever the producer read it, and
            # compared only if `compare_version` asks — default off.
            allowed = {"unique_id", "version_guid", "compare_version"}
            if v is None:
                pass  # optional: a write without a declared base is still legal
            elif not isinstance(v, dict) or "unique_id" not in v or not (set(v) <= allowed):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected={"unique_id": "UniqueId (обязательно)",
                              "version_guid": "32 hex (необязательно)",
                              "compare_version": "bool (необязательно)"}, got=v,
                    message_ru=(f"{p.name}: обязателен unique_id; version_guid и "
                                f"compare_version необязательны — поля берутся из "
                                f"element_identity квитанции или query_element_state")))
            elif "compare_version" in v and not isinstance(v["compare_version"], bool):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=f"{p.name}.compare_version",
                    expected="true или false", got=v["compare_version"],
                    message_ru=(f"{p.name}.compare_version: true или false; "
                                f"по умолчанию версия НЕ сверяется")))
            elif v.get("compare_version") and not v.get("version_guid"):
                # Asking for a comparison against nothing would emit no guard at
                # all, and the author would believe a version check is standing.
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=f"{p.name}.compare_version",
                    expected="version_guid рядом", got=v,
                    message_ru=(f"{p.name}.compare_version=true без version_guid: "
                                f"сверять не с чем, и страж НЕ был бы выпущен — "
                                f"подай version_guid из той же квитанции либо убери "
                                f"compare_version")))
            elif not (isinstance(v["unique_id"], str) and _UNIQUE_ID_FORM.fullmatch(v["unique_id"])):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=f"{p.name}.unique_id",
                    expected="UniqueId вида 8-4-4-4-12-суффикс", got=v["unique_id"],
                    message_ru=(f"{p.name}.unique_id: не похоже на UniqueId Ревита — возьми "
                                f"element_identity.unique_id из квитанции или query_element_state")))
            elif "version_guid" in v and not (isinstance(v["version_guid"], str)
                      and _VERSION_GUID_FORM.fullmatch(v["version_guid"])):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=f"{p.name}.version_guid",
                    expected="32 шестнадцатеричных знака (VersionGuid \"N\")",
                    got=v["version_guid"],
                    message_ru=(f"{p.name}.version_guid: 32 шестнадцатеричных знака — возьми "
                                f"element_identity.version_guid из той же квитанции")))
            else:
                # The normalised shape keeps only what was given: an absent
                # version stays absent rather than becoming an empty string that
                # a later comparison would read as a real value.
                norm[p.name] = {"unique_id": v["unique_id"]}
                if "version_guid" in v:
                    norm[p.name]["version_guid"] = v["version_guid"].lower()
                if v.get("compare_version"):
                    norm[p.name]["compare_version"] = True
        elif p.kind == "value":
            v = op.get(p.name)
            if v is None and not p.required:
                # An OPTIONAL value slot that was not filled is not a malformed
                # value: `expected_current` is the first such slot, and without
                # this the absence would be refused as "value — строка, bool или
                # {value, unit}", sending the repair to a field nobody wrote.
                pass
            elif isinstance(v, bool):
                norm[p.name] = {"type": "int", "v": 1 if v else 0}
            elif isinstance(v, str):
                if len(v) > 1000:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        message_ru="строка значения <=1000"))
                else:
                    norm[p.name] = {"type": "str", "v": v}
            elif isinstance(v, dict) and set(v) == {"workset"}:
                # A WORKSET IS NOT A REFERENCE, though it looks like one.
                # `Workset` does not inherit `Element`,
                # `Parameter.Set(WorksetId)` does not exist (CS1503 on all
                # six), and a workset is written WHOLE. Its own value kind was
                # set up deliberately: folding it into `ref` would give one
                # entry living under different rules than the rest — and a
                # capability that LOOKS proven.
                name = v.get("workset")
                if not isinstance(name, str) or not name.strip():
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected={"workset": "имя рабочего набора"}, got=v,
                        message_ru="значение набора — {workset: <имя>}"))
                else:
                    norm[p.name] = {"type": "int_ref", "pool": "worksets",
                                    "by": "name", "v": name.strip()}
            elif isinstance(v, dict) and set(v) == {"phase"}:
                # THE SECOND REFERENCE KIND. The technique is the same as for
                # material, and that is DELIBERATE — one technique, not a
                # second way of doing the same thing: they would diverge at
                # the very first third kind that comes along.
                name = v.get("phase")
                if not isinstance(name, str) or not name.strip():
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected={"phase": "имя фазы"}, got=v,
                        message_ru="ссылочное значение — {phase: <имя>}"))
                else:
                    norm[p.name] = {"type": "ref", "pool": "phases",
                                    "by": "name", "v": name.strip()}
            elif isinstance(v, dict) and set(v) == {"material"}:
                # A REFERENCE VALUE. The value set of `set_param` was closed
                # to str|bool|number, and so every parameter with a
                # reference value was UNREACHABLE: material, phase, room,
                # level. The branch is opened for material — one, not all
                # four: opening all four at once would give four unproven
                # things instead of one proven one.
                #
                # A REFERENCE IS SPELLED OUT EXPLICITLY AND HAS NO DEFAULT. An
                # omitted value would be allowed by the `sole_entry` rule,
                # which does not CHOOSE but states that there is no
                # alternative: measured on 12.08.2026 — on the fixture this
                # resolves 46 pairs out of 47 that way, while on real
                # buildings 42 of 91 defaults stop working. Here that choice
                # is not created BY CONSTRUCTION, not by the executor's
                # memory.
                name = v.get("material")
                if not isinstance(name, str) or not name.strip():
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                        field_name=p.name,
                        expected={"material": "имя материала"}, got=v,
                        message_ru="ссылочное значение — {material: <имя>}"))
                else:
                    norm[p.name] = {"type": "ref", "pool": "materials",
                                    "by": "name", "v": name.strip()}
            elif isinstance(v, dict) and set(v) <= {"value", "unit"}:
                num, unit = v.get("value"), v.get("unit")
                if not _num(num) or unit not in ("mm", "raw"):
                    diags.append(Diagnostic(
                        code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                        expected={"value": "число", "unit": "mm|raw"}, got=v,
                        message_ru="числовое значение — {value, unit: mm|raw}"))
                elif unit == "mm" and not (-1_000_000 <= num <= 1_000_000):
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        got=num, message_ru="value(mm) вне границ ±1e6"))
                elif unit == "raw" and isinstance(num, int) \
                        and not (-0x80000000 <= num <= 0x7FFFFFFF):
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name, got=num,
                        expected="32-битное целое -2147483648..2147483647",
                        message_ru=("raw integer не помещается в Revit Parameter.Set(int); "
                                    "для double передайте число с десятичной точкой")))
                elif unit == "raw" and isinstance(num, int):
                    norm[p.name] = {"type": "int", "v": num}
                else:
                    norm[p.name] = {"type": unit, "v": float(num)}
            elif _num(v):
                # bare numbers are BANNED: unit ambiguity is the R6 bug class
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, suggested_replacement={"value": v, "unit": "mm"},
                    applicability="maybe-incorrect",
                    message_ru="число без единиц запрещено — укажите {value, unit: mm|raw}"))
            else:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru="value — строка, bool или {value, unit}"))
        elif p.kind == "pts":
            v = op.get(p.name)
            # wave/struct: same optional-geometry None-skip as pt_xy/pt_xyz
            # above — create_foundation's outline (slab-only) is the first
            # non-required "pts" param in the registry (create_floor's own
            # outline is required=True).
            if v is None and not p.required:
                continue
            if not (isinstance(v, list)
                    and MIN_RING_POINTS <= len(v) <= MAX_RING_POINTS
                    and all(_pt_ok(pt, dims=(2,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f">={MIN_RING_POINTS} точек [x,y] мм", got=v,
                    message_ru=(f"{p.name} — контур из {MIN_RING_POINTS}.."
                                f"{MAX_RING_POINTS} точек")))
            else:
                area = abs(sum(v[k][0] * v[(k + 1) % len(v)][1]
                               - v[(k + 1) % len(v)][0] * v[k][1]
                               for k in range(len(v)))) / 2.0
                if area < MIN_RING_AREA_MM2:
                    from kir.geom import degenerate_ring_ru
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=degenerate_ring_ru(p.name)))
                else:
                    from kir.geom import ring_normalize
                    ring = ring_normalize(v, oid, p.name, diags)
                    if ring is not None:
                        norm[p.name] = ring
        elif p.kind == "pts_xyz":
            # SURFACE POINT CLOUD (wave/site, 09.08.2026). The laws are
            # ENTIRELY static (none of them looks at the model), so they run
            # here rather than at the ground stage — like `mesh`, and unlike
            # `region`, which needs axes from the snapshot. The laws have one
            # owner — geom.validate_points_xyz; this is only the call site,
            # and that is deliberate: a second rule set about the same thing
            # would drift apart.
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if v is None:
                diags.append(Diagnostic(
                    code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                    field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            from kir.geom import validate_points_xyz
            pts = validate_points_xyz(v, oid, p.name, diags)
            if pts is not None:
                norm[p.name] = pts
        elif p.kind == "path":
            # OPEN polyline (wave/arch): 2..64 points, WITHOUT an area check
            # and WITHOUT ring_normalize. Two points make a legitimate
            # straight railing; its area is zero, and requiring one would ban
            # the most common case. Not required -> None is skipped: `path`
            # is needed only by the variety="path" variant (the conditional
            # requirement is checked in arch_emit.emit_railing as the typed
            # KIR-P005).
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if not (isinstance(v, list)
                    and MIN_PATH_POINTS <= len(v) <= MAX_PATH_POINTS
                    and all(_pt_ok(pt, dims=(2,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f">={MIN_PATH_POINTS} точек [x,y] мм", got=v,
                    message_ru=(f"{p.name} — ломаная из {MIN_PATH_POINTS}.."
                                f"{MAX_PATH_POINTS} точек")))
            else:
                # A degenerate SEGMENT is a refusal, not a silent merge. The
                # 1 mm threshold: a short curve in Revit (~0.8 mm) does not
                # get built at all, and silently dropping such a segment
                # would put a railing of a different shape than requested
                # back into the model.
                bad = next((k for k in range(len(v) - 1)
                            if _dist(v[k], v[k + 1]) < 1.0), None)
                if bad is not None:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name,
                        message_ru=(f"{p.name}: звено {bad}-{bad + 1} короче "
                                    f"1 мм (Revit такую кривую не строит)")))
                else:
                    norm[p.name] = [[float(pt[0]), float(pt[1])] for pt in v]
        elif p.kind == "path3":
            # THREE-DIMENSIONAL open polyline (wave/mep-electrical): 2..64
            # points [x,y,z] in mm. A separate kind from `path`, not an
            # extension of it: for a railing the path lies ON a level and the
            # third coordinate would be a spurious degree of freedom, while
            # for flexible conduit the whole point is exactly the rise to the
            # ceiling. The same argument by which create_beam required
            # `pt_xyz` instead of `pt_xy`+level.
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            if not (isinstance(v, list)
                    and MIN_PATH_POINTS <= len(v) <= MAX_PATH_POINTS
                    and all(_pt_ok(pt, dims=(3,)) for pt in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f">={MIN_PATH_POINTS} точек [x,y,z] мм", got=v,
                    message_ru=(f"{p.name} — трёхмерная ломаная из "
                                f"{MIN_PATH_POINTS}..{MAX_PATH_POINTS} точек")))
            else:
                # Coinciding points are a REFUSAL, not a rounding triviality.
                # Autodesk writes about Flex*.Create verbatim: "Note the
                # duplicate points don't take into account" — meaning Revit
                # DISCARDS them and builds a run with a DIFFERENT number of
                # points than requested. The path witness would then honestly
                # fail, but the diagnosis "geometry did not match" would name
                # the effect instead of the cause, while the cause is already
                # visible right here.
                bad = next((k for k in range(len(v) - 1)
                            if _dist(v[k], v[k + 1]) < _MIN_SEGMENT_MM), None)
                if bad is not None:
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid,
                        field_name=p.name,
                        message_ru=(f"{p.name}: звено {bad}-{bad + 1} короче "
                                    f"{_MIN_SEGMENT_MM:g} мм — Revit считает "
                                    "такие точки совпадающими и выбрасывает "
                                    "их, то есть построил бы другую трассу")))
                else:
                    norm[p.name] = [[float(pt[0]), float(pt[1]), float(pt[2])]
                                    for pt in v]
        elif p.kind == "pts_list":
            v = op.get(p.name)
            if v is None or (isinstance(v, list) and not v):
                # Absent OR empty list ⇒ "no holes" (semantically identical).
                # The materializer emits holes=[] for hole-free floors/roofs; a
                # bare `is None` check refused every such op KIR-T001.  Do not
                # use truthiness here: False/0/""/{} are malformed payloads,
                # not an alternative spelling of an empty hole list (F29).
                continue
            if not (isinstance(v, list) and 1 <= len(v) <= MAX_HOLES
                    and all(isinstance(h, list)
                            and MIN_RING_POINTS <= len(h) <= MAX_HOLE_RING_POINTS
                            and all(_pt_ok(pt, dims=(2,)) for pt in h) for h in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    message_ru=(f"{p.name} — список контуров (каждый "
                                f"{MIN_RING_POINTS}..{MAX_HOLE_RING_POINTS} "
                                f"точек)")))
            else:
                from kir.geom import ring_normalize
                rings, bad = [], False
                for hi, h in enumerate(v):
                    r = ring_normalize(h, oid, f"{p.name}[{hi}]", diags)
                    if r is None:
                        bad = True
                        break
                    rings.append(r)
                if not bad:
                    norm[p.name] = rings
        elif p.kind == "enum":
            if p.name not in op and p.default is None and not p.required:
                continue          # an OPTIONAL enum with no default: absent
                                  # stays absent, exactly as the bool branch
                                  # below.  Without this the framework could
                                  # not express such a param at all —
                                  # ``op.get(name, None)`` is not in choices,
                                  # so every program omitting the field was
                                  # refused with a type error.
            v = op.get(p.name, p.default)
            if v not in p.choices:
                # A ROUTE INSTEAD OF "NOT ALLOWED" (09.08).
                # `ops_shape.IMPERSONATION_ROUTES` describes HOW to honestly
                # do what a person reaches for the forbidden DirectShape
                # category to get (wall, floor, roof…). The table has existed
                # since 29.07 and had ZERO importers: the law was written
                # down and never spoken in a single refusal, and the user got
                # a dry "one of [generic_model, mass, …]" without learning
                # that the operation they needed already EXISTS in KIR.
                #
                # The condition is addressed to the CHOICE TABLE, not to the
                # op's name: the rule is about the DirectShape categories, and
                # any op declaring exactly that set must refuse the same way.
                # Addressing it by op name would once again split the law
                # from its carriers — exactly the same fix already made for
                # the `region` kind in ground.py.
                route = _impersonation_route(p, v)
                message = f"{p.name} — одно из {list(p.choices)}"
                if route is not None:
                    message += (f". Категория {v!r} тут запрещена намеренно: "
                                f"геометрия без BIM-смысла читалась бы «{v}» в "
                                f"каждом фильтре и каждой спецификации, не "
                                f"будучи ничем, чем этот элемент является. "
                                f"Это делается операцией {route}")
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=list(p.choices), got=v, message_ru=message))
            else:
                norm[p.name] = v
        elif p.kind == "slopes":
            # Parallel to `outline`, so the two are validated together: a
            # slope list of a different length silently pitches the wrong
            # edges, which is the kind of plausible-wrong this compiler exists
            # to refuse.
            if p.name not in op:
                continue
            v = op.get(p.name)
            ring = norm.get("outline") or op.get("outline") or []
            def _pitch_ok(x):
                return x is None or (
                    isinstance(x, (int, float)) and not isinstance(x, bool)
                    and 0.0 < float(x) < 90.0)
            if not (isinstance(v, list) and len(v) == len(ring)
                    and all(_pitch_ok(x) for x in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    expected=f"list of {len(ring)} entries, each null or 0<deg<90",
                    message_ru=f"{p.name} — по одному значению на ребро outline "
                               f"({len(ring)}), каждое null или угол 0..90 градусов"))
            elif not any(x is not None for x in v):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    message_ru=f"{p.name} без единого угла — это плоская крыша, "
                               "просто не задавай поле"))
            else:
                norm[p.name] = [None if x is None else float(x) for x in v]
        elif p.kind == "bool":
            if p.name not in op:
                continue          # default stays implicit: program_hash/stamps
                                  # of pre-v1.1 programs must not shift
            v = op.get(p.name)
            if not isinstance(v, bool):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="true|false", got=v,
                    message_ru=f"{p.name} — булево"))
            else:
                norm[p.name] = v
        elif p.kind == "region":
            v = op.get(p.name)
            # The same None-skip for a NON-mandatory field as for
            # pt_xy/pts/path above. It became necessary on 09.08, when
            # `region` stopped being only a mandatory field of
            # create_floor_by_contour: for create_ceiling the sketch is an
            # ALTERNATIVE to a direct outline, and without this line a
            # silently absent second input read as a broken type
            # (KIR-T001 on a field the author never wrote), while mutual
            # requiredness (KIR-P007) never lived to reach the plan at all.
            if v is None and not p.required:
                continue
            if not isinstance(v, dict):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name} — объект {{outer, holes?}}"))
            else:
                norm[p.name] = v      # full laws run at ground (anchors need world)
        elif p.kind in ("graph_nodes", "graph_segments"):
            v = op.get(p.name)
            if not isinstance(v, list):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name} — список"))
            else:
                norm[p.name] = v      # graph laws run once, cross-field, at ground
        elif p.kind == "mesh":
            # wave/shape. The laws of mesh shape are ENTIRELY static (none of
            # them looks at the model), so they run here rather than at the
            # ground stage — unlike `region`, which needs axes from the
            # snapshot. The validator either returns a normalized mesh or
            # lodges a named refusal; it has no silent input fixing.
            from kir.mesh import validate_mesh
            v = validate_mesh(op.get(p.name), oid, p.name, diags)
            if v is not None:
                norm[p.name] = v
        elif p.kind == "surface":
            # wave/surface (2026-08-20). THE SAME law as for the mesh: all
            # surface-shape rules are static (degrees, knot clamping,
            # grid rectangularity, weights), the model is not needed for
            # them — so their place is here, not at the ground stage. The
            # validator either returns a normalized surface or lodges a
            # named refusal.
            from kir.surface import validate_surface
            v = validate_surface(op.get(p.name), oid, p.name, diags)
            if v is not None:
                norm[p.name] = v
        elif p.kind == "plane":
            # wave/plane (2026-08-21). THE SAME law as for the mesh, the
            # surface, and the boolean operands: all plane rules are static
            # (three fields, non-zero vectors, x_dir ⊥ normal, origin
            # bounds), the model is not needed for a single one of these
            # fields. The validator either returns a NORMALIZED plane
            # (unit vectors) or lodges a named refusal; it has no silent
            # input fixing — no orthogonalizing on the author's behalf.
            from kir.plane import validate_plane
            v = op.get(p.name)
            if v is None and not p.required:
                continue
            v = validate_plane(v, oid, p.name, diags)
            if v is not None:
                norm[p.name] = v
        elif p.kind == "solid_parts":
            # wave/boolean (2026-08-20). THE SAME law as for the mesh and the
            # surface, and here it holds MOST STRONGLY of all: part of the
            # boolean is given entirely in numbers — box, sphere, cylinder —
            # and not one of these numbers addresses an axis, a level, or a
            # type. So it is checkable FULLY offline, and the snapshot is
            # not needed for any field. That was exactly the argument for
            # choosing primitives over contours (the breakdown is in the
            # "PARTS" block of ops_boolean.py).
            from kir.ops_boolean import validate_parts
            v = validate_parts(op.get(p.name), oid, p.name, i, diags)
            if v is not None:
                norm[p.name] = v
        elif p.kind == "str":
            v = op.get(p.name)
            if v is None:
                # PRE-EXISTING GAP fixed here (found while gating load_family/
                # create_type's required str params): this branch used to
                # `continue` unconditionally, so a MISSING required str param
                # (e.g. set_param.param, also required=True) produced no
                # diagnostic at all and later panicked emit-side with a raw
                # KeyError (KIR-P000) instead of a typed refusal — the exact
                # class of bug the compiler-must-never-panic invariant bans.
                # Every pre-existing str param without this check was either
                # optional (name) or always supplied in every existing test
                # (set_param.param) — this closes the gap for both, additive.
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            # cap defaults to 64 (unchanged for every pre-existing str param,
            # all of which leave max_val unset); an op can opt into a wider
            # cap for genuinely long strings (load_family.path — Windows
            # MAX_PATH-class .rfa paths) via ParamSpec(..., max_val=N).
            cap = p.max_val if p.max_val is not None else 64
            if not isinstance(v, str):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=(f"строка <={cap}" if p.exact_string
                              else f"непустая строка <={cap}"),
                    got=v, message_ru=f"{p.name} — строка"))
            elif not p.exact_string and not v.strip():
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"непустая строка <={cap}", got=v,
                    message_ru=f"{p.name} — непустая строка"))
            elif len(v) > cap:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"строка <={cap}", got=v,
                    message_ru=f"{p.name} длиннее {cap} символов"))
            else:
                norm[p.name] = v if p.exact_string else v.strip()
        elif p.kind == "int":
            # A WHOLE NUMBER, not "a number we'll truncate later." The first
            # authoring op with this kind is set_curtain_panel.u/v: a cell
            # address. 1.5 is not an address; accepting it and truncating it
            # would mean choosing the neighboring cell on the author's
            # behalf — exactly the silent choice this compiler forbids. bool
            # is cut off separately: in Python True is 1, and "truth" is not
            # an address.
            v = op.get(p.name, p.default)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid,
                        field_name=p.name, message_ru=f"{p.name} обязателен"))
                continue
            if isinstance(v, bool) or not isinstance(v, int):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="целое число", got=v,
                    message_ru=f"{p.name} — целое число"))
            elif (p.min_val is not None and v < p.min_val) \
                    or (p.max_val is not None and v > p.max_val):
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"{p.min_val}..{p.max_val}", got=v,
                    message_ru=f"{p.name} вне границ {p.min_val}..{p.max_val}"))
            else:
                norm[p.name] = int(v)
        elif p.kind == "str_long":
            # Documentation family (create_text.content): a longer bound than
            # "str" (KIR_DOC_SPEC.md: "content: непустой, <= разумной длины"),
            # same json.dumps-escaping law as v1 (no separate rule needed here
            # — _cs() at emit time is the single escaping point).
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=f"{p.name} обязателен"))
                continue
            # Three DIFFERENT refusals, three different messages. Merged
            # into one, they lie: a measurement on 02.08 on a 59-story tower
            # produced nine notes longer than the limit (max 4763
            # characters) — and all nine reported "content — non-empty
            # string," meaning they sent you looking for emptiness where
            # there was none. Diagnostics that name the wrong refusal are
            # more costly than no diagnostics at all: they get the wrong
            # thing fixed.
            if not isinstance(v, str):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="строка", got=v,
                    message_ru=f"{p.name} — строка (текст заметки)"))
            elif not v.strip():
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="непустая строка", got=v,
                    message_ru=(f"{p.name} пуст — текст примечания обязателен, "
                                "подставлять пустую строку значило бы выдумать "
                                "источник")))
            elif len(v) > _TEXT_CONTENT_MAX_CHARS:
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"<={_TEXT_CONTENT_MAX_CHARS} символов",
                    got=len(v),
                    message_ru=(f"{p.name} длиннее {_TEXT_CONTENT_MAX_CHARS} "
                                f"символов ({len(v)})")))
            else:
                norm[p.name] = v
        elif p.kind == "pt_view2d":
            # Documentation VIEW-SPACE law (KIR_DOC_SPEC.md): reuse docspace's
            # core, never reinvent it. A 3D point here is KIR-T001 by
            # construction (docspace.check_pt_view2d), not a truncation.
            v = op.get(p.name)
            if v is None:
                if p.required:
                    diags.append(Diagnostic(
                        code=PARSE_MISSING_FIELD, op_index=i, op_id=oid, field_name=p.name,
                        message_ru=f"{p.name} обязателен — точка вида [u,v] мм"))
                continue
            # `docspace` is imported at module level (line 12); a repeated
            # local import made the name local to the whole of `validate`.
            pt = docspace.check_pt_view2d(v, oid, p.name, diags)
            if pt is not None:
                norm[p.name] = pt
        elif p.kind == "refs_w":
            # Documentation `refs` (create_dimension): >=2 write-target
            # selectors (element_id | intra-program ref), no two identical
            # (a dimension between an element and itself is a zero-size
            # refusal, same law as p0==p1 for walls/pipes/grids).
            #
            # move_elements.targets (28.07 SRC PIN, live schema_gen
            # collision): reuses this SAME kind — it is exactly "a list of
            # target_w selectors", and schema_gen.py's kind-switch is
            # exhaustive and foreign-dirty (cannot learn a new kind).  The
            # bound/dedup rule is looked up BY OP NAME, same discipline as
            # the beam/foundation dims-by-name branch above: create_dimension
            # keeps its ORIGINAL 2..16 + no-duplicates law untouched;
            # move_elements gets its own 1..500, duplicates ALLOWED (moving
            # the same element twice is harmless — Revit's ElementId
            # collection de-duplicates — not a zero-size-dimension hazard).
            # create_angular_dimension: EXACTLY two, and the bound is derived
            # from the API rather than picked — RevitAPI.xml requires the
            # references to be "rays of the arc passed", and the arc's vertex
            # is the intersection of the two referenced planes, a construction
            # a third plane has no place in (09.08).
            lo, hi, reject_dupes = _refs_w_contract(name)
            v = op.get(p.name)
            # THE SECOND SELECTOR STAGE (`{"by": "face", ...}`, `faceref.py`).
            #
            # AS A SEPARATE BRANCH, NOT WOVEN INTO THE CHECK BELOW, AND THIS
            # IS NOT A STYLE CHOICE. The law of the flag: when off it must be
            # INDISTINGUISHABLE from the shape not existing at all. As long
            # as the list contains not a single face selector, the code below
            # runs EXACTLY as it did before this change — meaning byte-for-
            # byte emission equality is provable by structure, not by running
            # it (`test_faceref.py::FlagOffIsAbsentTests` checks both sides).
            # A woven-in condition would have to be proven by exhaustive
            # testing.
            if isinstance(v, list) and any(faceref.is_face_sel(x) for x in v):
                norm_faces = _validate_refs_w_with_faces(
                    v, name=name, param=p, oid=oid, i=i,
                    lo=lo, hi=hi, reject_dupes=reject_dupes, diags=diags)
                if norm_faces is not None:
                    norm[p.name] = norm_faces
            elif not (isinstance(v, list) and lo <= len(v) <= hi
                    and all(_target_w_ok(x) for x in v)):
                # 🔴 THE REASON FOR EACH UNFIT SELECTOR, NOT ONE SHAPE FOR THE
                # WHOLE LIST. A shape without a value type is
                # indistinguishable from what was actually sent (measured
                # 22.08: `{'by':'element_id','value':'294076'}` against
                # "expected {by: element_id|ref, value: ...}" — two live
                # turns spent on a single quote mark).
                why = ""
                if isinstance(v, list):
                    bad = [(j, _target_w_why(x)) for j, x in enumerate(v)]
                    bad = [(j, w) for j, w in bad if w]
                    if bad:
                        why = "; ".join(f"[{j}] {w}" for j, w in bad[:4])
                        if len(bad) > 4:
                            why += f"; ещё {len(bad) - 4} таких же"
                    elif not (lo <= len(v) <= hi):
                        why = f"селекторов {len(v)}, а нужно от {lo} до {hi}"
                else:
                    why = (f"{p.name} обязан быть СПИСКОМ селекторов, "
                           f"а пришёл {type(v).__name__}")
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=(f"{lo}..{hi} селекторов "
                              "{by: element_id, value: ЦЕЛОЕ} либо "
                              "{by: ref, value: \"id операции\"}"),
                    got=v, message_ru=(f"{p.name} — список из {lo}..{hi} "
                                       f"селекторов element_id/ref. "
                                       f"НЕГОДНО: {why}" if why else
                                       f"{p.name} — список из {lo}..{hi} "
                                       "селекторов element_id/ref")))
            elif (not p.ref_kinds
                  and any(x.get("by") == "ref" for x in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name,
                    expected="только element_id-селекторы", got=v,
                    message_ru=(f"{p.name}: intra-program ref не разрешён "
                                "типизированным контрактом параметра")))
            else:
                keys = [(x["by"],
                         x["value"].strip() if x["by"] == "ref" else x["value"])
                        for x in v]
                if reject_dupes and len(set(keys)) != len(keys):
                    diags.append(Diagnostic(
                        code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name=p.name,
                        got=v, message_ru=f"{p.name}: повторяющийся ref — нулевой размер размера недопустим"))
                else:
                    norm[p.name] = [
                        {"by": x["by"],
                         "value": x["value"].strip() if x["by"] == "ref" else x["value"]}
                        for x in v]
        elif p.kind == "arc":
            # Curve-IR (P4-B): optional canonical Arc dict on create_wall.
            # Absent -> unchanged straight Line wall (program_hash/emitted C#
            # byte-stable). Present -> validated through the audited
            # recompile.ArcCurve invariants (single source of truth for
            # frame/radius/span), AND cross-checked so the arc endpoints match
            # p0_mm/p1_mm (which stay the grounding/hosting anchor).
            if p.name not in op:
                continue
            v = op.get(p.name)
            if not isinstance(v, dict):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=v, message_ru=f"{p.name} — объект дуги (canonical Arc)"))
                continue
            # RELATE + an arc do NOT mix, and that is a decision, not an
            # omission. An arc is given by center, radius, and angles; its
            # ends must MATCH p0_mm/p1_mm, and that is checked right below.
            # If the ends come from the snapshot, there is nothing to check
            # at validate time, and moving the check to ground would mean
            # that an arc, on an axis miss, drifts away from its own
            # endpoints. `arc` is explicitly carved out of v1 by the spec
            # (§9.4).
            if any(relate.is_address(norm.get(k)) for k in ("p0_mm", "p1_mm")):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    got=sorted(k for k in ("p0_mm", "p1_mm")
                               if relate.is_address(norm.get(k))),
                    message_ru=(
                        f"{name}: дуга и адрес от осей вместе не выражаются — "
                        "концы дуги заданы её центром/радиусом/углами и обязаны "
                        "совпасть с p0_mm/p1_mm. Задайте концы дуговой стены "
                        "литералами [x, y]")))
                continue
            arc_norm = _validate_arc(v, i, oid, norm.get("p0_mm"),
                                     norm.get("p1_mm"), diags)
            if arc_norm is not None:
                norm[p.name] = arc_norm
        elif p.kind == "spiral":
            # A spiral stair (09.08): an ALTERNATIVE to direct p0_mm/p1_mm,
            # not an addition to it. Its absence is the historical straight
            # run, byte for byte; "both at once" and "neither" are the typed
            # KIR-P007 in the plan (a schema cannot express mutual
            # requiredness). The same None-skip as for pt_xy/region above.
            if p.name not in op or op.get(p.name) is None:
                continue
            v = op.get(p.name)
            if not isinstance(v, dict):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    message_ru=f"{p.name} — объект винтового марша "
                               "{center_mm, radius_mm, start_angle_deg, "
                               "included_angle_deg, clockwise}"))
                continue
            # width_mm is already normalized: the `mm` kind sits HIGHER in
            # the registry, and the "radius greater than half-width" check
            # reads both numbers at once.
            spiral_norm = _validate_spiral(v, i, oid, norm.get("width_mm"),
                                           diags)
            if spiral_norm is not None:
                norm[p.name] = spiral_norm
        elif p.kind == "member_ops":
            # feat/native-groups: the group definition is 1..N create-authoring
            # ops at occurrence 0's absolute coordinates.  This first pass owns
            # container shape, identity and obvious capability exclusions.  The
            # compiler immediately runs every accepted member through the SAME
            # single-op planner as a top-level operation and binds its OpContract
            # into the parent plan; no component bridge is a validation trust
            # boundary.
            v = op.get(p.name)
            # The ceiling is taken from the registry (`spec.GROUP_MEMBERS_MAX`)
            # rather than sitting here as a literal: before 23.08.2026 the
            # number 200 was written into THIS block THREE TIMES and had no
            # rationale at any of the three spots. The measurement on two
            # production buildings and the argument for the current value
            # are in the registry, next to the number itself.
            _cap = spec.GROUP_MEMBERS_MAX
            if not (isinstance(v, list) and 1 <= len(v) <= _cap
                    and all(isinstance(m, dict) for m in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected=f"список из 1..{_cap} опов-членов", got=v,
                    message_ru=f"{p.name} — список опов-членов группы "
                               f"(1..{_cap})"))
            else:
                ok = True
                seen_ids: set = set()
                for mi, m in enumerate(v):
                    mop = m.get("op")
                    mospec = spec.OPS.get(mop) if isinstance(mop, str) else None
                    # The result kind is asked of THE INSTANCE, not only of
                    # the declaration: `identity_cardinality` describes the
                    # OP IN GENERAL, while membership is decided by the
                    # SPECIFIC CALL. A room separator is declared `many` and
                    # on a two-point path produces EXACTLY ONE segment — that
                    # is its own postcondition, not a relaxation. There is
                    # one rule shared by the validator and the lifter: `spec`.
                    if (mospec is None
                            or mospec.family != "authoring"
                            or mospec.effect.value != "create"
                            or not spec.group_member_yields_one(mop, m)
                            or mop == "create_group"
                            or mop in spec.SOLO_OPS):
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].op", got=mop,
                            message_ru=("член группы — одиночный create-authoring "
                                        "op, дающий ОДИН элемент (не "
                                        "query/modify/delete/solo/create_group)")))
                        ok = False
                        continue
                    mid = m.get("id")
                    if not isinstance(mid, str) or not (1 <= len(mid) <= 64):
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].id", got=mid,
                            message_ru="у члена группы должен быть строковый id"))
                        ok = False
                        continue
                    if mid in seen_ids:
                        diags.append(Diagnostic(
                            code=TYPE_BOUNDS, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}].id", got=mid,
                            message_ru=f"дублирующийся id члена группы {mid!r}"))
                        ok = False
                        continue
                    seen_ids.add(mid)
                    # A reference INTO the group is lawful; a reference OUT
                    # of it is not.
                    #
                    # Lead review #3 refused every `ref` inside a member, and
                    # the reason was correct exactly halfway: a ref to a
                    # variable OUTSIDE the group's namespace would give a
                    # nonexistent `__el_*` and fail at the compile gate. But a
                    # ref to a NEIGHBOR IN THE SAME GROUP is not a reference
                    # out: the emitter names members `{oid}__m__{id}`, and it
                    # is enough to rewrite the reference's value with that
                    # same name (`authoring._emit_group`).
                    #
                    # **THE COST OF THE OLD REFUSAL, MEASURED 12.08.2026.** A
                    # door addresses its wall ONLY through `ref`, so a floor
                    # with walls AND doors was ungroupable BY CONSTRUCTION —
                    # and that is exactly how a person assembles a 59-story
                    # building: **41.1% of a real tower's elements live
                    # inside groups** (walls 94.9%, load-bearing columns
                    # 100%, curtain panels 99.3%, doors 91.4%; 2,941
                    # instances out of 367 definitions). The remaining form
                    # was enumeration, and it hit a ceiling of 300 against a
                    # real floor's median of 796 ops.
                    #
                    # Member order is checked right here, for FREE:
                    # `seen_ids` is exactly "members declared ABOVE," so a
                    # backward reference passes and a forward reference is
                    # refused with a named reason. An author naturally writes
                    # the wall before the door.
                    def _refs(node) -> list:
                        out: list = []
                        if isinstance(node, dict):
                            if node.get("by") == "ref":
                                out.append(node.get("value"))
                            g = node.get("__grounded__")
                            if isinstance(g, dict) and g.get("via") == "ref":
                                out.append(g.get("value"))
                            for x in node.values():
                                out.extend(_refs(x))
                        elif isinstance(node, list):
                            for x in node:
                                out.extend(_refs(x))
                        return out
                    body = {k: v2 for k, v2 in m.items() if k != "id"}
                    member_ids = {
                        str(other.get("id")) for other in v
                        if isinstance(other, dict) and other.get("id") is not None}
                    outside = [r for r in _refs(body)
                               if str(r) not in member_ids]
                    forward = [r for r in _refs(body)
                               if str(r) in member_ids and str(r) not in seen_ids]
                    if outside:
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}]", got=sorted(outside),
                            expected=sorted(member_ids),
                            message_ru=(
                                f"член группы ссылается НАРУЖУ группы: "
                                f"{sorted(outside)!r}. Внутри группы ссылаться "
                                f"можно только на её же членов "
                                f"({sorted(member_ids)!r}); на элементы вне "
                                f"группы — по element_id. СЛЕДУЮЩИЙ ХОД: либо "
                                f"внеси адресуемый элемент в members, либо "
                                f"замени ref на element_id")))
                        ok = False
                        continue
                    if forward:
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{mi}]", got=sorted(forward),
                            message_ru=(
                                f"член группы ссылается на члена, объявленного "
                                f"НИЖЕ: {sorted(forward)!r}. Внутри группы "
                                f"порядок членов — это порядок создания. "
                                f"СЛЕДУЮЩИЙ ХОД: переставь адресуемого члена "
                                f"выше ссылающегося (стену раньше двери)")))
                        ok = False
                        continue
                if ok:
                    # Deep-copy so the emitter can safely namespace member ids
                    # under the group op id without mutating the caller's ops.
                    import copy as _copy
                    norm[p.name] = _copy.deepcopy(v)
        elif p.kind == "placements":
            # feat/native-groups: per-ADDITIONAL-occurrence offset deltas
            # [dx,dy,dz] (mm), each == occ_origin_k - occ_origin_0 (occurrence 0
            # is the members themselves, so an EMPTY list is legal — a group
            # placed once, or the definition-only degenerate the bridge refuses
            # upstream). Deltas may be [x,y] (z=0 implied) or [x,y,z].
            v = op.get(p.name)
            if not (isinstance(v, list) and len(v) <= 4096
                    and all(_pt_ok(d, dims=(2, 3)) for d in v)):
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=p.name,
                    expected="список смещений [dx,dy(,dz)] мм (0..4096)", got=v,
                    message_ru=f"{p.name} — список смещений [dx,dy,dz] в мм"))
            else:
                norm[p.name] = [
                    [float(d[0]), float(d[1]), float(d[2] if len(d) > 2 else 0.0)]
                    for d in v
                ]
        elif p.kind == "wall_layers":
            # THE WALL'S LAYER CAKE, OUTSIDE TO INSIDE — exactly the order in
            # which `CompoundStructure.GetLayers()` returns it and in which
            # `SetLayers` lays it down. A layer: {width_mm, function,
            # material?}.
            #
            # 🔴 WHY THIS IS A KIND, NOT A LIST OF NUMBERS. Measured
            # 23.08.2026 on K1: of 44 wall types, 40 carry a composition,
            # COMPOUND (>1 layer) 18 = 41%. A type created from a SINGLE
            # thickness would give the right name and the right volume with
            # the wrong layer cake, and there would be nothing to catch it
            # with: the `create_wall` witness is silent about the type,
            # `verify.json` does not read the layers, and the clash shell
            # takes `WallType.Width` and would come out CORRECT. A silently
            # wrong outcome is exactly what KIR is written against.
            #
            # `material` is OPTIONAL: `MaterialId == InvalidElementId` is a
            # legitimate Revit state, not a gap of ours. But an EMPTY string
            # is not that: it is "a name exists and it is empty," i.e., a
            # fabrication.
            v = op.get(p.name)
            ok_shape = (isinstance(v, list) and 1 <= len(v) <= WALL_LAYERS_MAX
                        and all(isinstance(x, dict) for x in v))
            if not ok_shape:
                diags.append(Diagnostic(
                    code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                    field_name=p.name, got=v,
                    expected=(f"список слоёв 1..{WALL_LAYERS_MAX}: "
                              "{width_mm, function, material?}"),
                    message_ru=(f"{p.name} — пирог стены снаружи внутрь, "
                                f"1..{WALL_LAYERS_MAX} слоёв "
                                "{width_mm, function, material?}")))
            else:
                clean: list = []
                bad = False
                for li, layer in enumerate(v):
                    extra = set(layer) - {"width_mm", "function", "material"}
                    if extra:
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{li}]", got=sorted(extra),
                            message_ru=("лишние ключи слоя: "
                                        + ", ".join(sorted(extra)))))
                        bad = True
                        continue
                    w = layer.get("width_mm")
                    if (isinstance(w, bool) or not isinstance(w, (int, float))
                            or not _num(w)
                            or not (WALL_LAYER_MIN_MM <= float(w)
                                    <= WALL_LAYER_MAX_MM)):
                        diags.append(Diagnostic(
                            code=TYPE_BOUNDS, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{li}].width_mm", got=w,
                            message_ru=(f"толщина слоя обязана быть числом "
                                        f"{WALL_LAYER_MIN_MM}..{WALL_LAYER_MAX_MM} мм")))
                        bad = True
                        continue
                    fn = layer.get("function")
                    if fn not in WALL_LAYER_FUNCTIONS:
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{li}].function", got=fn,
                            expected=list(WALL_LAYER_FUNCTIONS),
                            message_ru=("функция слоя — одно из: "
                                        + ", ".join(WALL_LAYER_FUNCTIONS))))
                        bad = True
                        continue
                    mat = layer.get("material")
                    if mat is not None and not (isinstance(mat, str)
                                                and mat.strip()
                                                and len(mat) <= 128):
                        diags.append(Diagnostic(
                            code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                            field_name=f"{p.name}[{li}].material", got=mat,
                            message_ru=("имя материала — непустая строка до "
                                        "128 знаков; ОТСУТСТВИЕ ключа — "
                                        "законный слой без материала, "
                                        "пустая строка — нет")))
                        bad = True
                        continue
                    one = {"width_mm": float(w), "function": fn}
                    if mat is not None:
                        one["material"] = mat
                    clean.append(one)
                if not bad:
                    norm[p.name] = clean
        else:
            # THE TAIL OF THE CHAIN. Without it the `if/elif` silently lets a
            # parameter slip past every check AND past `norm` — see
            # `_assert_kind_dispatched`.
            _assert_kind_dispatched(p, name)
    # 🔴 PLANE AND ELEVATION — TWO WAYS OF SAYING THE SAME THING, AND BOTH
    # TOGETHER ARE FORBIDDEN. The law is addressed to a KIND, not an op's
    # name: it holds for every operation that has both `plane` and
    # `base_z_mm` — today there are two of them, tomorrow more. The question
    # "which one wins" has no correct answer here: `base_z_mm` moves the
    # profile along world Z, `plane.origin_mm` places it at a point, and a
    # silent choice between them would mean the other is lost without a
    # single word.
    if norm.get("plane") is not None and norm.get("base_z_mm") is not None:
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="plane",
            got=["plane", "base_z_mm"], expected="ровно одно из двух",
            message_ru=("plane и base_z_mm вместе не принимаются: base_z_mm "
                        "ЕСТЬ плоскость (горизонтальная на отметке z), то есть "
                        "вырожденный случай того же рода. Наклонная плоскость "
                        "— plane; горизонталь на отметке — base_z_mm")))
    if name == "create_extrusion_roof":
        # THE EXTRUSION RUN IS AN INTERVAL, NOT A PAIR OF NUMBERS.
        # `start_mm >= end_mm` is either an empty run (no roof at all) or an
        # inverted one — and the second case is more dangerous: Revit will
        # most likely build the same volume, and the witness compares the
        # MINIMUM of the projection with `start_mm` and the MAXIMUM with
        # `end_mm`, and will honestly fail. The diagnosis "wrong extrusion"
        # would name the EFFECT, while the cause is already visible right
        # here, before any emission.
        #
        # The threshold is NOT NEW: `_MIN_SEGMENT_MM` is the same 1 mm this
        # file already uses to reject a degenerate polyline segment, with
        # the same justification ("a short curve in Revit, ~0.8 mm, does not
        # get built"). Setting up a second number for the same physical
        # quantity would mean setting up a second judge.
        a, b = norm.get("start_mm"), norm.get("end_mm")
        if (isinstance(a, (int, float)) and isinstance(b, (int, float))
                and float(b) - float(a) < _MIN_SEGMENT_MM):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="end_mm",
                expected=f"end_mm - start_mm >= {_MIN_SEGMENT_MM:g} мм",
                got=float(b) - float(a),
                message_ru=(
                    f"end_mm ({b}) не больше start_mm ({a}) хотя бы на "
                    f"{_MIN_SEGMENT_MM:g} мм — ход выдавливания пуст или "
                    "перевёрнут; это отрезок ВДОЛЬ нормали плоскости, и "
                    "начало обязано быть меньше конца")))
    if name == "set_curtain_panel":
        # There is no deterministic "by default" rule for a curtain-panel
        # type: neither a doc-default (there isn't one in the API) nor
        # "the pool's sole entry" (there is no pool — the panel type lives
        # in two type spaces). The refusal is typed and happens AT PARSE
        # TIME, not at emission.
        selector = norm.get("panel_type")
        if isinstance(selector, dict) and selector.get("by") == "default":
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                field_name="panel_type",
                expected={"by": "name|element_id"}, got=selector,
                message_ru=("panel_type: у типа ячейки витража нет правила по "
                            "умолчанию — назовите тип или его element_id")))
    if name == "place_family" and "ref_dir" in op:
        # ``_emit_place`` routes to the WorkPlaneBased overload as soon as it
        # sees ref_dir.  Before this guard every explicit operand below was
        # accepted by the registry and then lost at that early return.  A
        # typed refusal is deliberately stricter than interpreting a neutral
        # explicit value as omission: source intent must never disappear.
        for field in PLACE_FAMILY_WORK_PLANE_UNSUPPORTED:
            if field not in op:
                continue
            diags.append(Diagnostic(
                code=PARSE_EXCLUSIVE_FIELDS,
                op_index=i,
                op_id=oid,
                field_name=field,
                expected=(f"{field} без ref_dir или ref_dir без "
                          f"{field}"),
                got=op[field],
                message_ru=(
                    f"place_family на рабочей плоскости: {field} "
                    "не имеет доказанного совместного lowering с "
                    "ref_dir; уберите один из операндов — компилятор не "
                    "будет молча игнорировать авторское поле")))
    if name in ("create_door", "create_window", "place_family"):
        raw_states = {
            key: op.get(key, False)
            for key in ("mirrored", "hand_flipped", "facing_flipped")
        }
        if ("mirrored" in op
                and all(isinstance(value, bool)
                        for value in raw_states.values())
                and raw_states["mirrored"] != (
                    raw_states["hand_flipped"]
                    != raw_states["facing_flipped"])):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_index=i, op_id=oid,
                field_name="mirrored",
                expected="hand_flipped XOR facing_flipped",
                got=raw_states["mirrored"],
                message_ru=("mirrored — производное состояние: должно быть "
                            "равно hand_flipped XOR facing_flipped")))
    if (name == "create_floor"
            or (name == "create_foundation" and norm.get("variety") == "slab")) \
            and "outline" in norm and norm.get("holes"):
        from kir.geom import check_holes_relation
        check_holes_relation(norm["outline"], norm["holes"], oid, diags)
    _name_the_next_move(name, diags, _diag_start)
    return norm
