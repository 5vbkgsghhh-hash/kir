"""KIR BOOLEAN — subtract, union, intersect. Wave 2026-08-20.

WHY. In Grasshopper, booleans are half of all shape work: subtract a niche,
union two volumes, intersect a shell with a cutting solid. KIR had NONE of
this: the registry could build an extrusion and a revolve, and that is where
shape ended. The author could compute geometry of any complexity in python
and still could not say "now subtract one from the other."

═══ WHAT THIS OPERATION IS, AND WHAT IT ACTS ON ══════════════════════════════════════════════════

🔴 OVER SOLIDS INSIDE ONE PROGRAM, NOT OVER BUILT ELEMENTS —
and this follows from how Revit is built, not from taste:

* `BooleanOperationsUtils` operates on `Solid`. A `Solid` in Revit is NOT an
  element: it has no ElementId, does not survive a transaction, and cannot be
  found by a selector. So the operands must be born and die inside a single
  op;
* a boolean OVER ELEMENTS in Revit is a different mechanism
  (`InstanceVoidCutUtils`, `SolidSolidCutUtils`), with different laws and a
  different meaning: there it is "wall minus opening," and the registry
  already has `create_opening` for that. Folding the two into one op would
  mean putting one name on two incompatible things;
* the chain is expressed as a LIST of parts, not as nested ops, for the same
  reason exactly: an intermediate solid has nowhere to live between ops.

The first part is the BASE; the rest apply to it in order, left to right.
Solid Union/Difference in Grasshopper is built the same way, and the phrase
"subtract these from this" reads the same way too.

═══ WITNESS: AN IDENTITY, NOT OUR OWN RECOMPUTATION ═══════════════════════════════════════════

The volume of a union or a difference is NOT DERIVABLE in closed form — this
is the same argument by which `ops_solid` refuses five factories out of
seven: the shape of the resulting solid is chosen by Revit, not by the input.
Computing the volume with our own sampling would mean injecting our own error
into the witness and baking it into the tolerance.

But the boolean has properties that CAN BE CHECKED, and Revit ITSELF computes
every value in them — we compute none:

    IDENTITY 1    V(A∪B) + V(A∩B) == V(A) + V(B)
    IDENTITY 2    V(A−B) + V(A∩B) == V(A)
    DIRECTION     V(A∪B) > max(V(A),V(B)) · V(A∩B) < min(V(A),V(B)) · V(A−B) < V(A)

🔴 THE FIRST EDITION OF THIS LAW WAS REFUTED BY ITS OWN CONTROL, AND THE
CORRECTION MATTERS MORE THAN THE LAW ITSELF. I wrote that the identity and
the direction check catch different things and neither is a subset of the
other. The FAIL control refuted that: it removed the direction check on the
union — NOT ONE test went red.

The reason is arithmetic, not a matter of testing. We build the intersection
with a SEPARATE Revit call, so `V(A∩B)` is known, and the identity determines
the result UNAMBIGUOUSLY:

    V(A∪B) = V(A) + V(B) − V(A∩B)     ← the only possible value
    V(A−B) = V(A) − V(A∩B)            ← the only possible value

Any deviation is caught by the identity. **The direction check, given a sound
precondition, adds nothing** — and this is written down here rather than kept
quiet, because a check that cannot add anything reads as reinforcement and is
not one.

WHY IT STAYS ANYWAY: as a SECOND WITNESS in case the precondition fails or is
later removed. Measured on the same case: without a built intersection (which
is cheaper by one solid — a real temptation) the identity cannot be checked
at all, and the direction check alone is LEAKY — it lets through "returned
A+B," i.e. an operation that did not remove the overlap. Hence the emission
law: **the intersection is always built, and it cannot be saved on.**

═══ NO-VACUUM RULE: TWO OUTCOMES — TWO CODES ════════════════════════════════════════════

🔴 THE FIRST EDITION OF THIS LAW CARRIED OUR OWN NAMED DEFECT, and it was
caught by the same measurement. The direction predicate returns "no" in TWO
different cases: when the operation was swapped out, and when the operation
is DEGENERATE (the solids do not intersect, or one is nested inside the
other). One predicate for two outcomes, and the fixes are opposite: the first
case calls for fixing emission, the second for rewriting the program.

So degeneracy is checked by a PRECONDITION, BEFORE any verdict:

    V(A∩B) > δ                  otherwise the solids do not intersect — the boolean does nothing
    V(A∩B) < min(V(A),V(B)) − δ  otherwise one is nested in the other — the result is known in advance

If the precondition is violated, the op REFUSES, named (`KIR-B101`/`KIR-B102`),
rather than signing off in green on a check that cannot fail. This is exactly
the law by which `ops_solid` forbids a vacuous tolerance.

═══ TOLERANCE: DERIVED, NOT ASSIGNED ═══════════════════════════════════════════

δ is computed AT EMISSION TIME from two quantities that come from Revit
itself, exactly as in `ops_solid`:

    δ_V = (surface area of the resulting solid) · (MM(VertexTolerance) + quantum)

By construction this cannot be a registry constant: the volume error depends
on the SIZE of the solid. `VertexTolerance` is Revit's own number ("two
points closer than this are considered coincident"), and the quantum is
`contour.EMIT_COORD_QUANTUM_MM`, a direct consequence of coordinates being
printed with two decimal digits.

═══ WHAT THIS OP DOES NOT GIVE YOU IS STATED HERE, NOT LEFT UNSAID ════════════

The result is a `DirectShape`, i.e. GEOMETRY WITHOUT BIM MEANING: no type, no
layers, no schedule entry, a human cannot edit it as a wall. Literally the
same price as `create_directshape` and `ops_solid`, and it is named for the
same reason: "we generated a building" when what was generated was a solid —
exactly the lie this whole compiler is written against.

The author is looking for something else if what is needed is a wall, a
slab, or a panel: the registry has real operations for those, and
`IMPERSONATION_ROUTES` in `ops_shape` names them by name.
"""
from __future__ import annotations

from typing import Any, Optional

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)
from kir.ops_solid import MAX_EXTENT_MM, MIN_EXTENT_MM, SOLID_CATEGORIES
from kir.emit_utils import is_finite_number

#: Precondition refusals. Their OWN codes, not a shared one: "the solids do
#: not intersect" and "one is nested in the other" call for DIFFERENT program
#: fixes — spread the operands apart versus remove the redundant one — and the
#: consumer branches on the code.
BOOLEAN_DISJOINT = "KIR-B101"
BOOLEAN_NESTED = "KIR-B102"

#: Closed list of operations. Exactly the three given by `BooleanOperationsType`
#: (checked against `data/api_surface` across all six versions: Difference,
#: Intersect, Union — and nothing else).
BOOLEAN_OPS: tuple[str, ...] = ("union", "difference", "intersect")

#: How many solids in one program. The lower bound is DERIVED: a boolean over
#: a single solid is not an operation. The upper bound is ASSIGNED, and named
#: as such: each part requires its own construction and its own pair of
#: identity checks, so the cost grows linearly, and eight operands is already
#: a description a reader cannot hold in mind.
#: 🔴 RAISING IT TO 32 WAS REQUESTED ON 2026-09-02 — REFUSED BY MEASUREMENT,
#: NOT BY ARGUMENT.
#:
#: The argument FOR raising it was strong and remains true: "eight operands is
#: already a description a reader cannot hold in mind" is an argument about a
#: HUMAN hand, and the reader here is an LLM holding the whole building at
#: once. By the law of the constitution, such a limit is subject to removal.
#:
#: BUT ITS HARM IS ZERO, AND THAT HAS BEEN MEASURED. A census of 110 real
#: families, solids per family (solid primitives plus boolean parts):
#:
#:      solids  1   2   3   4   5   6   7   8   9
#:      fams   22  12  11  11  10   7   2   1   1
#:
#: The only family above eight is «M_Kitchen Set» (9 solids), and all
#: nine are SEPARATE solid shapes raised by their own operations. Parts of a
#: single boolean number zero there. The limit counts parts INSIDE one
#: `create_solid_boolean` and did not touch a single carcass family — 0 of 83.
#:
#: Removing a limit with zero casualties would mean moving the number to fit
#: the argument instead of the measurement. The condition for revisiting it is
#: named: the first family where the parts of a SINGLE boolean exceed eight.
BOOLEAN_PARTS_MIN = 2
BOOLEAN_PARTS_MAX = 8


def witness_verdict(v_a: float, v_b: float, v_i: float, v_r: float,
                    op: str, delta: float) -> tuple[bool, str]:
    """THE LAW OF A SINGLE STEP'S WITNESS — a pure function, checked without Revit.

    The input is FOUR volumes, each computed by Revit ITSELF: the accumulator
    ``v_a``, the next part ``v_b``, their intersection ``v_i``, and the result
    ``v_r``. We compute none of them; we check the RELATIONS between them.

    Returns ``(ok, reason)``. The reason is non-empty exactly when ``ok`` is
    false, and it names WHAT exactly diverged, rather than "the witness failed."

    🔴 THE PRECONDITION IS DELIBERATELY NOT CHECKED HERE: degeneracy is a refusal
    of the OP (`KIR-B101`/`B102`), not a failure of the witness, and conflating
    them would mean giving two different troubles one outcome. Ask about it via
    :func:`degenerate_reason`.
    """
    if op == "union":
        if abs((v_r + v_i) - (v_a + v_b)) > delta:
            return False, "объём объединения не сходится с включением-исключением"
        if not (v_r > max(v_a, v_b) + delta):
            return False, "объединение не больше каждого из операндов"
        return True, ""
    if op == "difference":
        if abs((v_r + v_i) - v_a) > delta:
            return False, "объём разности плюс пересечение не даёт исходного"
        if not (v_r < v_a - delta):
            return False, "разность не меньше уменьшаемого"
        return True, ""
    if op == "intersect":
        # For an intersection, identity 1 needs to KNOW the union, which we do not
        # build; identity 2 needs the difference. So here the weight is carried by the
        # DIRECTION check plus the equality of the result with the intersection Revit
        # itself computed by a SEPARATE call. Two independent roads to one number.
        if abs(v_r - v_i) > delta:
            return False, "результат не равен посчитанному пересечению"
        if not (v_r < min(v_a, v_b) - delta):
            return False, "пересечение не меньше каждого из операндов"
        return True, ""
    return False, f"неизвестная операция {op!r}"


def degenerate_reason(v_a: float, v_b: float, v_i: float,
                      delta: float) -> Optional[tuple[str, str]]:
    """Is the boolean degenerate ON THESE SOLIDS — ``(code, reason)`` or ``None``.

    Checked BEFORE the witness and separately from it: a degenerate operation
    gives a predictable result on which ANY witness is green by construction.
    Skipping this check would mean signing off on a check that cannot fail.
    """
    if v_i <= delta:
        return (BOOLEAN_DISJOINT, BOOLEAN_DISJOINT_RU)
    if v_i >= min(v_a, v_b) - delta:
        return (BOOLEAN_NESTED, BOOLEAN_NESTED_RU)
    return None


#: 🔴 THE REFUSAL TEXT LIVES HERE, NOT IN TWO PLACES. The same degeneracy is
#: checked by EMISSION at runtime (Revit computes the volumes, not us), and
#: its C# prints exactly these strings. A separate copy of the text in the
#: emitter would drift from this one at the first wording edit, and the reader
#: of the refusal would not be able to tell which of the two checks rejected
#: it.
BOOLEAN_DISJOINT_RU = (
    "тела не пересекаются: булева не изменила бы ничего, и "
    "проверить её было бы нечем. Следующий ход: сдвинуть операнды "
    "так, чтобы они перекрывались, либо убрать операцию")
BOOLEAN_NESTED_RU = (
    "одно тело целиком внутри другого: результат известен заранее "
    "(объединение = большее, пересечение = меньшее, разность = "
    "большее минус меньшее). Следующий ход: если это и нужно — "
    "постройте нужное тело напрямую, без булевой")


# ════════════════════════════════════════════════════════════════════════════════
# PARTS: WHAT EXACTLY IS SUBTRACTED, UNIONED, AND INTERSECTED
#
# 🔴 THE MAIN DESIGN DECISION, AND IT WAS REVISED ON 2026-08-21 — ON THE
# MERITS, NOT JUST BY SIGNATURE. This used to read: "the whole point of
# choosing primitives BY NUMBERS INSTEAD OF CONTOURS was exactly this," and
# the conclusion was wrong, even though the ARGUMENT beneath it is correct and
# is kept in full below. The cost of the error was measured: a census of real
# building recipes rejected 64 shapes out of 283 with the code
# `void_form_not_expressible` — "shape is a VOID, and our boolean's operands
# are box/sphere/cylinder." A void in a family is a prism over an arbitrary
# contour, and there was no way to say it.
#
# WHAT WAS ACTUALLY CORRECT AND REMAINS THE LAW:
#
#   A `Solid` in Revit is not an element — it has no ElementId, it does not
#   survive a transaction. So the OPERAND MUST BE BORN AND DIE INSIDE ONE OP,
#   and there is no way to address it BY REFERENCE to a neighboring op.
#
# WHAT DOES NOT FOLLOW FROM THIS: that the operand must be given AS NUMBERS.
# The law forbids a REFERENCE, and a contour with explicit points is a VALUE,
# not a reference:
#
#  * it is checked offline IN FULL by the pure function
#    `contour.validate_region` — the same rings, the same openings, the same
#    strict interior as the base;
#  * it addresses neither a grid, nor a level, nor a type, so it needs NO
#    GROUNDING AT ALL. The direct consequence: it does not pass through
#    `ground.py` either, so a collision on the shared key `__region__` does
#    not concern it AT ALL — `solid_parts` is checked in full inside
#    `authoring_validation`, before grounding;
#  * the WITNESS IS INDIFFERENT TO IT, and this has been verified, not
#    assumed. The inclusion-exclusion identity and the direction check read
#    FOUR volumes computed by Revit itself (`__bva/__bvb/__bvi/__bvr/__bvx`),
#    and the `_NEEDS` table in `boolean_emit` is keyed by the pair (law,
#    operation) — the kind of part appears in it in NOT ONE character. The
#    fourth kind of part added NOT ONE new obligation to the witness.
#
# 🔴 AND ONE REFERENCE HERE WENT STALE, WHICH IS WORTH NAMING SEPARATELY: the
# argument that "ground folds EVERY region into one shared `__region__`, so
# there cannot be two contours in one op" was TRUE ON 08-20 AND OVERTURNED
# THAT SAME EVENING. The derived-fields contract introduced named keys
# `__region_<field>__` (`midend._recomputed_derived_artifact`, `ground.py`
# next to blend), and `create_solid_blend` lives with two regions today. That
# is, the restriction that justified the shape of the part here had already
# stopped existing by the time this was read. This is written down not for
# history's sake: a reference to someone else's limit, not re-checked at edit
# time, is a named defect of this tree.
#
# ═══ FOUR KINDS OF PART, AND THE BOUNDARY BETWEEN THEM RUNS ALONG GROUNDING ═══════
#
#   box · sphere · cylinder   the solid is built by ONE Revit factory call
#                             from numbers; no rotation, world axes;
#   prism                     a prism over a contour — the SAME set of fields
#                             as `create_solid_extrusion` (profile, height_mm,
#                             and exactly one of base_z_mm / plane), because
#                             it is the same geometry. A second way to say a
#                             prism would mean two carriers of one law.
#
# WHY THE PRISM HAS A PLANE AND THE THREE PRIMITIVES DO NOT. This is not
# generosity toward one kind: `plane` (wave 08-21) is already an established
# value kind with a ready validator and ready emission through `Transform`,
# and it is exactly what distinguishes a wall's vertical face from a plan.
# Census of a real teardown: of 64 voids in a real building, 27 lie on a
# HORIZONTAL plane, 37 on an arbitrary one. A plan-only prism would cover less
# than half. The primitives still have no rotation, and this remains a named
# missing degree of freedom, not an omission: a rotated box is a separate wave
# with its own conclusion.
#
# WHAT WAS REJECTED AND WHY (all three arguments REMAIN valid):
#
#  * A REFERENCE TO A NEIGHBORING OP (`base: "E1"`). A `Solid` in Revit is not
#    an element: it has no ElementId, it does not survive a transaction. The
#    neighbor `create_solid_extrusion` leaves behind a DirectShape, not a
#    Solid, and there would be nothing to reference. Full account is in the
#    file header;
#  * AN ELEMENT SELECTOR. This is a DIFFERENT Revit mechanism
#    (`InstanceVoidCutUtils`, `SolidSolidCutUtils`) with different laws, and
#    the registry already has `create_opening` for it. One name for two
#    incompatible things is a named defect of this tree;
#  * THE `member_ops` KIND (group membership). It requires every member to be
#    a create-op with EXACTLY ONE result element, and the compiler routes it
#    through the scheduler as a real op. That is, each part would become an
#    ELEMENT — exactly the opposite of what the boolean needs: operands must
#    be born and die inside a single op.
#
# WHAT A PRISM PART DOES NOT ACCEPT, STATED HERE, NOT LEFT UNSAID:
#
#  * A GRID ADDRESS at a contour corner (`{at_grid: [...]}`). A part has no
#    grounding by construction — so it has no grid pool either, and `contour`
#    refuses it itself, in its own words, not through our copy of its rule;
#  * A SPLINE. `create_solid_boolean` is not in
#    `contour.SPLINE_WITNESSED_OPS`, and the BASE of this op no longer accepts
#    a spline either (guarded in `ground.py`). A part that allowed a spline
#    would be MORE PERMISSIVE than the base of the SAME op — that is, one op
#    with two different laws for the same geometry.
# ════════════════════════════════════════════════════════════════════════════════

#: Closed list of part kinds. The first three are primitives whose solid is
#: built by ONE Revit factory call from numbers. The fourth is a prism over a
#: contour: it needs no grounding either, because the contour is given by
#: EXPLICIT points.
PART_SHAPES: tuple[str, ...] = ("box", "sphere", "cylinder", "prism")

#: REQUIRED fields for each kind — CLOSED AND EXACT. An extra field is an
#: ERROR, not ignorable noise: "gave radius_mm on a box" means the author was
#: thinking of a different shape, and staying silent here would mean building
#: something other than what was said.
PART_FIELDS: dict[str, tuple[str, ...]] = {
    "box": ("center_mm", "size_mm"),
    "sphere": ("center_mm", "radius_mm"),
    "cylinder": ("center_mm", "radius_mm", "height_mm"),
    "prism": ("profile", "height_mm"),
}

#: OPTIONAL fields. As a separate table, not "optional is whatever is left
#: over": the three primitives have NONE AT ALL, and an empty tuple says so
#: out loud. The prism has exactly two, and they are MUTUALLY EXCLUSIVE — the
#: same law and the same wording as `create_solid_extrusion` (`plane.py`,
#: header): `base_z_mm` IS the degenerate case of `plane`, and two ways to say
#: the same thing drift apart silently. Absence of both means the profile is
#: in the world XY plane, exactly as for extrusion.
PART_OPTIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "box": (),
    "sphere": (),
    "cylinder": (),
    "prism": ("base_z_mm", "plane"),
}


def part_extent_bounds() -> tuple[float, float]:
    """Part size limits — the SAME ones as `ops_solid` uses for solids, by import.

    There are deliberately no numbers of its own here: two tables that must
    agree drift apart silently, and the very first edit to the extrusion's limit
    would have left the boolean with the old one.

    🔴 A DUPLICATE IMPORT WAS REMOVED ON 2026-08-21. This used to say
    `from kir.ops_solid import MAX_EXTENT_MM, MIN_EXTENT_MM` — while the module
    already imports BOTH names on line 109. A duplicate import INSIDE a function
    makes the name local to the WHOLE of its body, and any use ABOVE that line
    would raise `UnboundLocalError` instead of working. It did not raise here:
    the two lines sit right next to each other, and nothing above reads them in
    the body. That is, the defect was LOADED but never FIRED — and the charge is
    defused by deletion, because the second import gave nothing: no break in a
    cycle (the module-level one already exists), no independence (the source is
    the same).

    The shape of this was measured on 2026-08-02 on a 59-story tower:
    `run_idempotence` re-imported `json` inside a debug branch, and the refusal
    handler on the line 460 ABOVE it died with `UnboundLocalError` — a crash
    stood in for the diagnosis.
    """
    return MIN_EXTENT_MM, MAX_EXTENT_MM


def lower_part_profile(part: dict, oid: str, field: str, i: int,
                       diags: list) -> Optional[dict]:
    """Prism-part contour -> a LOWERED region (edges), or ``None`` with a refusal.

    🔴 ONE CARRIER OF THE CONTOUR LAW, CALLED FROM HERE TWICE OVER THE PROGRAM'S
    LIFE — at validation and at emission. This is NOT a second carrier: both
    sides call the same pure function `contour.validate_region` rather than
    repeating its rules. `midend._recomputed_derived_artifact` does exactly the
    same thing, replaying the region lowering for ops with a `region`-kind
    parameter.

    THE GRID POOL HERE IS `None`, AND THIS IS NOT AN OVERSIGHT. A part has no
    grounding by construction — so it has no grid either; `contour` will refuse
    `{at_grid: ...}` on its own, in its own words, not through our copy of its
    rule.
    """
    from kir import contour as contour_mod
    from kir.diag import Diagnostic, EMIT_CONTOUR_SPLINE

    profile = part.get("profile")
    lowered = contour_mod.validate_region(profile, None, oid,
                                          f"{field}[{i}].profile", diags)
    if lowered is None:
        return None
    # A SPLINE ON A PART IS FORBIDDEN BY THE SAME LAW AS A SPLINE ON THE BASE.
    # The base's guard sits in `ground.py` and checks
    # `contour.SPLINE_WITNESSED_OPS`; `create_solid_boolean` is not on that list.
    # A part without that same guard would be MORE PERMISSIVE than the base OF
    # THE SAME OP — one op with two different laws for the same geometry.
    if contour_mod.region_has_spline(lowered):
        diags.append(Diagnostic(
            code=EMIT_CONTOUR_SPLINE, op_id=oid,
            field_name=f"{field}[{i}].profile",
            message_ru=("контур части несёт сплайн, а свидетель булевой "
                        "доказывает объёмы, посчитанные Revit, по КОНТУРУ, "
                        "который мы напечатали: кривая была бы построена и не "
                        "проверена. Тот же запрет стоит на БАЗЕ этого опа "
                        "(ground.py, contour.SPLINE_WITNESSED_OPS). Следующий "
                        "ход: выразить край дугами (arcs)")))
        return None
    return lowered


def validate_parts(value: Any, oid: str, field: str, i: int,
                   diags: list) -> Optional[list]:
    """List of parts -> a normalized list, or ``None`` with diagnostics.

    A pure function: no Revit, no snapshot, no model. Everything checked here is
    checkable offline IN FULL — including the prism's contour, because a contour
    with explicit points is a VALUE, not a reference. The account of why this
    does NOT contradict the law "the operand is born and dies inside the op" is
    in the "PARTS" block above.
    """
    from kir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS

    lo, hi = part_extent_bounds()
    lo_parts, hi_parts = BOOLEAN_PARTS_MIN - 1, BOOLEAN_PARTS_MAX - 1

    def bad(code: str, fname: str, message: str, got: Any = None) -> None:
        diags.append(Diagnostic(code=code, op_index=i, op_id=oid,
                                field_name=fname, got=got, message_ru=message))

    if not isinstance(value, list) or not (lo_parts <= len(value) <= hi_parts):
        bad(TYPE_BAD_TYPE, field,
            f"{field} — список частей булевой, {lo_parts}..{hi_parts} штук "
            f"(вместе с базой это {BOOLEAN_PARTS_MIN}..{BOOLEAN_PARTS_MAX} тел). "
            f"Часть — одно из: "
            + " · ".join(f"{{shape: {s!r}, " + ", ".join(PART_FIELDS[s])
                         + (("[, " + ", ".join(PART_OPTIONAL_FIELDS[s]) + "]")
                            if PART_OPTIONAL_FIELDS[s] else "") + "}"
                         for s in PART_SHAPES),
            got=value)
        return None

    out: list[dict] = []
    for pi, raw in enumerate(value):
        at = f"{field}[{pi}]"
        if not isinstance(raw, dict):
            bad(TYPE_BAD_TYPE, at, f"{at} — объект части, а не "
                                   f"{type(raw).__name__}", got=raw)
            return None
        shape = raw.get("shape")
        if shape not in PART_SHAPES:
            bad(TYPE_BAD_TYPE, f"{at}.shape",
                f"{at}.shape — одно из: {', '.join(PART_SHAPES)}. Других "
                f"родов части нет намеренно: у первых трёх тело строится одним "
                f"вызовом фабрики Revit из чисел, у призмы — из контура с "
                f"ЯВНЫМИ точками. И тому и другому заземление не нужно вовсе",
                got=shape)
            return None
        required = set(PART_FIELDS[shape]) | {"shape"}
        allowed = required | set(PART_OPTIONAL_FIELDS[shape])
        extra = sorted(set(raw) - allowed)
        missing = sorted(required - set(raw))
        if missing or extra:
            bad(TYPE_BAD_TYPE, at,
                f"{at}: у части {shape!r} обязательные поля ровно "
                f"{{{', '.join(sorted(required))}}}"
                + (f", необязательные {{{', '.join(PART_OPTIONAL_FIELDS[shape])}}}"
                   if PART_OPTIONAL_FIELDS[shape] else "")
                + (f"; нет: {', '.join(missing)}" if missing else "")
                + (f"; лишние: {', '.join(extra)}" if extra else "")
                + ". Лишнее поле — не шум, а признак, что автор думал о другой "
                  "фигуре", got=sorted(raw))
            return None

        norm: dict[str, Any] = {"shape": shape}

        # 🔴 BRANCHING BY KIND COMES BEFORE THE SHARED CENTER CHECK, NOT AFTER.
        # A prism HAS no `center_mm` and cannot have one: its position is carried by
        # the contour itself plus the elevation/plane. The earlier edition asked
        # every part for its center first — "a shared field, hoisted to the front" —
        # and the fourth kind would have hit that check before ever reaching its own
        # fields.
        if shape == "prism":
            lowered = lower_part_profile(raw, oid, field, pi, diags)
            if lowered is None:
                return None
            height = raw.get("height_mm")
            # `is_finite_number` COMES FIRST, AND THE ORDER HERE CARRIES WEIGHT: you
            # cannot ask `float(10**400)` about a limit — it raises before the question
            # is even asked. The same order holds in every numeric guard of this function
            # (see the account at `center_mm`).
            if (not is_finite_number(height)
                    or not (lo <= float(height) <= hi)):
                bad(TYPE_BOUNDS, f"{at}.height_mm",
                    f"{at}.height_mm — высота призмы в пределах {lo:g}..{hi:g} "
                    f"мм (те же пределы, что у тел ops_solid)", got=height)
                return None
            # PLANE AND ELEVATION ARE MUTUALLY EXCLUSIVE. The same law and the same
            # argument as `create_solid_extrusion` (`plane.py`, header): `base_z_mm` IS
            # the degenerate case of `plane`, and the question "which one wins" has no
            # correct answer.
            has_plane = raw.get("plane") is not None
            has_z = raw.get("base_z_mm") is not None
            if has_plane and has_z:
                bad(TYPE_BAD_TYPE, at,
                    f"{at}: plane и base_z_mm вместе не принимаются — "
                    f"base_z_mm и есть горизонтальная плоскость на отметке. "
                    f"Наклонная или вертикальная грань — plane; горизонталь на "
                    f"отметке — base_z_mm", got=["plane", "base_z_mm"])
                return None
            norm["profile"] = raw["profile"]
            norm["height_mm"] = float(height)
            if has_z:
                base_z = raw["base_z_mm"]
                if (not is_finite_number(base_z)
                        or not (-hi <= float(base_z) <= hi)):
                    bad(TYPE_BOUNDS, f"{at}.base_z_mm",
                        f"{at}.base_z_mm — отметка плоскости профиля в "
                        f"пределах ±{hi:g} мм", got=base_z)
                    return None
                norm["base_z_mm"] = float(base_z)
            elif has_plane:
                from kir.plane import validate_plane
                pl = validate_plane(raw["plane"], oid, f"{at}.plane", diags)
                if pl is None:
                    return None
                norm["plane"] = pl
            out.append(norm)
            continue

        center = raw.get("center_mm")
        # 🔴 SHAPE AND LIMIT ARE TWO DIFFERENT QUESTIONS, AND THE SECOND ONE WAS NOT
        # ASKED HERE AT ALL (fixed 2026-09-04). Only `isinstance` was checked, and
        # that let through two kinds of garbage at once, measured by execution:
        #
        #   center_mm=[10**400, 0, 0]   -> `float(c)` a line below raised
        #                                  `OverflowError` OUTWARD, past
        #                                  diagnostics: a crash instead of a refusal;
        #   center_mm=[16_000_001,0,0]  -> WAS ACCEPTED, even though this is already
        #                                  outside the model's working extent.
        #
        # Neither one is its own law: finiteness is `emit_utils
        # .is_finite_number` (the same one used by `plane._vec3`), and the limit is
        # `registry_base.COORD_LIMIT_MM`, whose home was set up on 2026-08-25 for
        # exactly the reason that there were two copies of the number and not every
        # path was checked. The refusal shape is taken from
        # `authoring_validation._point_bounds_diag`: TYPE_BOUNDS, the printed limit,
        # and the named reason "a UNITS error" — not TYPE_BAD_TYPE with the
        # unactionable advice "convert to a list of numbers" for a value that is
        # ALREADY a list of numbers.
        if (not isinstance(center, (list, tuple)) or len(center) != 3
                or not all(is_finite_number(c) for c in center)):
            bad(TYPE_BAD_TYPE, f"{at}.center_mm",
                f"{at}.center_mm — точка [x, y, z] из трёх КОНЕЧНЫХ чисел в "
                f"миллиметрах", got=center)
            return None
        за = next((float(c) for c in center if abs(c) > COORD_LIMIT_MM), None)
        if за is not None:
            bad(TYPE_BOUNDS, f"{at}.center_mm",
                f"{at}.center_mm: координата {за:.0f} мм за пределом сцены "
                f"({COORD_LIMIT_MM:.0f} мм от начала координат). Это почти "
                f"всегда ошибка ЕДИНИЦ — метры вместо миллиметров или футы "
                f"вместо метров", got=list(center))
            return None
        norm["center_mm"] = [float(c) for c in center]

        if shape == "box":
            size = raw.get("size_mm")
            if (not isinstance(size, (list, tuple)) or len(size) != 3
                    or not all(is_finite_number(c) for c in size)):
                bad(TYPE_BAD_TYPE, f"{at}.size_mm",
                    f"{at}.size_mm — размеры [dx, dy, dz] в миллиметрах",
                    got=size)
                return None
            if not all(lo <= float(c) <= hi for c in size):
                bad(TYPE_BOUNDS, f"{at}.size_mm",
                    f"{at}.size_mm — каждый размер в пределах {lo:g}..{hi:g} мм "
                    f"(те же пределы, что у тел ops_solid)", got=list(size))
                return None
            norm["size_mm"] = [float(c) for c in size]
        else:
            radius = raw.get("radius_mm")
            if (not is_finite_number(radius)
                    or not (lo / 2.0 <= float(radius) <= hi / 2.0)):
                bad(TYPE_BOUNDS, f"{at}.radius_mm",
                    f"{at}.radius_mm — радиус в пределах {lo / 2.0:g}.."
                    f"{hi / 2.0:g} мм (половина пределов ГАБАРИТА: диаметр и "
                    f"есть габарит)", got=radius)
                return None
            norm["radius_mm"] = float(radius)
            if shape == "cylinder":
                height = raw.get("height_mm")
                if (not is_finite_number(height)
                        or not (lo <= float(height) <= hi)):
                    bad(TYPE_BOUNDS, f"{at}.height_mm",
                        f"{at}.height_mm — высота в пределах {lo:g}..{hi:g} мм",
                        got=height)
                    return None
                norm["height_mm"] = float(height)
        out.append(norm)
    return out


def part_bbox(part: dict,
              lowered: Optional[dict] = None
              ) -> tuple[float, float, float, float, float, float]:
    """The part's bounding box IN CLOSED FORM. Used by the receipt, not the witness.

    🔴 THIS NUMBER IS NOT GIVEN TO THE WITNESS, AND THAT IS A DECISION. The
    RESULT's bounding box of a boolean is NOT DERIVABLE in closed form: for a
    union it equals the union of the bounding boxes, while for a difference and
    an intersection it is only CONTAINED IN the base's bounding box, with no
    equality. A check that holds for one operation out of three would read as if
    it held generally. The receipt needs the parts' bounding box for a different
    purpose — so a human can see WHERE the operands stood when the result
    surprised them.

    `lowered` is the LOWERED contour of the prism, required exactly for it. It
    arrives as an argument rather than being computed here: emission has already
    lowered it for the rings, and lowering it a second time would be a second
    call of the same thing at the same step.
    """
    if part["shape"] == "prism":
        if lowered is None:
            raise ValueError("prism part bbox needs the lowered profile")
        h = float(part["height_mm"])
        plane = part.get("plane")
        if plane is not None:
            # THE ROTATED-PROFILE BOUNDING FUNCTION IS THE SINGLE CARRIER, AND SINCE
            # 2026-09-01 IT LIVES IN `kir.plane`, below both readers. A local copy here
            # would drift from the one used to compute the bounding box for an extrusion
            # on the same plane — and carriers drift silently. The carrier used to live
            # in `solid_emit`, and the late import was not hiding the cost of loading it
            # but a DECISION ABOUT LAYERING: the registry pulled in the emitter anyway,
            # and through that edge the live-plan renderer reached all the way into the
            # compiler (measured by `capability_graph`: 10 solvers out of 15).
            from kir.plane import plane_profile_box
            return plane_profile_box(plane, (lowered, lowered), (0.0, h))
        from kir import contour as contour_mod
        x0, y0, x1, y1 = contour_mod.region_bbox(lowered)
        z0 = float(part.get("base_z_mm") or 0.0)
        return (x0, y0, z0, x1, y1, z0 + h)
    cx, cy, cz = part["center_mm"]
    if part["shape"] == "box":
        dx, dy, dz = part["size_mm"]
        return (cx - dx / 2, cy - dy / 2, cz - dz / 2,
                cx + dx / 2, cy + dy / 2, cz + dz / 2)
    r = part["radius_mm"]
    if part["shape"] == "sphere":
        return (cx - r, cy - r, cz - r, cx + r, cy + r, cz + r)
    h = part["height_mm"]
    return (cx - r, cy - r, cz - h / 2, cx + r, cy + r, cz + h / 2)


OPS = [
    OpSpec(
        name="create_solid_boolean",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # WHAT WE DO. A closed list of three, and this is exactly what
            # `BooleanOperationsType` gives (measured against `data/api_surface`: the
            # fields Difference, Intersect, Union across all six versions, and nothing
            # else). A fourth boolean does not exist in Revit.
            ParamSpec("operation", "enum", required=True,
                      choices=BOOLEAN_OPS),
            # THE BASE is a prism over a contour. Exactly ONE parameter of the `region`
            # kind: the account of why a second one is illegal today is in the "PARTS"
            # block above.
            ParamSpec("profile", "region", required=True),
            ParamSpec("height_mm", "mm", required=True,
                      min_val=MIN_EXTENT_MM, max_val=MAX_EXTENT_MM),
            # Elevation of the profile plane. No default: absence means Z=0 and prints
            # NO transform at all (absent stays absent).
            ParamSpec("base_z_mm", "mm",
                      min_val=-MAX_EXTENT_MM, max_val=MAX_EXTENT_MM),
            # THE BASE'S SKETCH PLANE (2026-08-21), mutually exclusive with `base_z_mm` —
            # a shared law of the kind, checked in one line in `authoring_validation` for
            # EVERY op that has both fields.
            #
            # 🔴 INTRODUCED TOGETHER WITH THE FOURTH PART KIND, AND THIS IS NOT
            # "INCIDENTAL." A boolean's base and a prism part are THE SAME geometry
            # (contour plus height). Giving the plane to the part but not to the base
            # would mean the language says the same prism in TWO different ways depending
            # on its place in the op, and there would be no way to express a vertical
            # void in a vertical wall: the part would lie on the face and the base would
            # not.
            ParamSpec("plane", "plane"),
            # PARTS. Its own value kind: a list of primitives is neither points, nor
            # contours, nor selectors, and no existing kind describes it. The account of
            # rejected shapes is in the "PARTS" block.
            ParamSpec("parts", "solid_parts", required=True),
            ParamSpec("category", "enum", required=True,
                      choices=SOLID_CATEGORIES),
            # The name is required for the same reason as for a mesh and a surface: for
            # an element without a type, the name is the only thing that tells it apart
            # from a nameless blob in the project tree a year from now.
            ParamSpec("name", "str", required=True, max_val=64),
        ),
        capability=(("create", "geometry"),),
        # WHAT IS PROMISED IS EXACTLY WHAT IS CHECKED, AND EVERY VALUE IS COMPUTED BY
        # REVIT ITSELF — we compute not a single volume. The account of the law and
        # its two refutations by its own control is in the file header.
        post=("boolean direct shape exists (materialized or typed refusal); "
              "built geometry holds exactly one solid (geometry); "
              "every step is non-degenerate: intersection volume is neither "
              "zero nor the whole of the smaller body (typed refusal "
              "KIR-B101/KIR-B102 before any effect); "
              # 🔴 "BUILT BY A DIFFERENT CALL" IS NOT A CLARIFICATION — IT IS THE POINT. The
              # first edition promised, for intersect, "V(result)==V(A&B)," while emission
              # obtained both numbers from ONE AND THE SAME kernel call: the check could
              # not fail. A promise that is trivially satisfiable is worse than no promise
              # at all — it gets read as verified.
              "every step satisfies inclusion-exclusion on volumes measured "
              "by Revit, with the auxiliary body built by a DIFFERENT kernel "
              "call than the result: union and difference verify against a "
              "separately built intersection, intersect verifies against a "
              "separately built union (geometry); "
              "every step moves the volume in the direction its operation "
              "names (geometry, second carrier)"),
        writes_model=True,
        # EMPTY BY CONSTRUCTION: a DirectShape has no type — there is nothing to ground.
        grounded=(),
        # EMPTY BY CONSTRUCTION: the tolerance here is a function of the SURFACE
        # AREAS of the solids involved in the step, and of Revit's own number
        # (`VertexTolerance`). It cannot be a registry constant: the volume error
        # depends on the size of the solid, and solids are born at runtime.
        tolerances={},
    ),
]
