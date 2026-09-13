"""L2 acceptance: the expectation is DERIVED from the program, the
verdict is computed from a REREAD of the model.

THE COST OF AN ERROR HERE IS NOT A BUG, IT IS THE LOSS OF MEANING OF THE
WHOLE LOOP. On 29.07 two models built a tower, looked at their own
result, and wrote "the shape and proportions match the brief"; the
operator's verdict on both: "garbage geometry." A day earlier, the "pass
1-to-1" criterion NEVER passed. There is one disease: the same party
that built also checks, and the threshold only chooses which direction
the loop lies in. That is why there is not a single judgment call here —
only a measurement against a predicate that no one wrote by hand.

WHY THE EXPECTATION IS DERIVED, NOT DECLARED. The design
(docs/2026-07-29-independent-acceptance-design.md, step 1) says "the
program declares the expected delta." That way the conflict of interest
comes back through the back door: the author will declare a weak
expectation, and acceptance will mean nothing again. The compiler KNOWS
EXACTLY what it compiled — how many create_wall calls and at what level.
The author expresses intent through OPERATIONS; the predicate follows
from them by itself, and it cannot be weakened, because no one writes
it. Pre-registration falls out by construction: the expectation exists
before execution, because it is derived from the program, not from the
result. :func:`expectation_digest` gives a short signature — it can be
written into a receipt BEFORE the build and later prove that the
predicate was not adjusted to fit the result.

THE COST OF INVENTED PRECISION IS HIGHER THAN THE COST OF NO CHECK AT
ALL. An expectation of "exactly N" where N is in fact unknown fails
HONEST builds, and a checker that lies on an honest build gets
disabled — and along with it, the checks that did work get disabled too.
That is why every kind of contribution carries its own degree of
certainty (:class:`Certainty`), and "I don't know" is a legitimate
answer here, not a disgrace.

WHAT WAS MEASURED, NOT RECALLED (31 saved decompilations,
backend/data/decompile, 30.07 — the numbers are checkable by the same
walk):

* a DOOR's level does not equal its host wall's level in 76 cases out of
  15 569 (0.49%): a door in wall L42 with a 400 mm base offset gets
  ``LEVEL_PARAM`` = "L42_+500". Deriving the door's level from its host
  is plausible and wrong; so the level of a door and a window is
  UNKNOWN;
* ``OST_Stairs``: 0 rows out of 351 carry ``level_name``. An expectation
  of "a stair at level X" would fail every honest stair;
* ``create_beam``: Revit derives the supporting level from the CURVE'S
  ELEVATION, not from the ``level`` argument (the 27.07 measurement is
  recorded right in the op's own ``post``: L_01@0 was passed with a
  curve at Z=3000 → the binding lands on L_01ДОО1_+2.500);
* ``Railing.Create(doc, hostId, typeId, position)`` returns a
  COLLECTION (arch_emit.py: a stair flight gets a railing on both sides
  at once) — one op gives 1..N railings, meaning "at least 1," not
  "exactly 1." This lever is absent from ``tools/capability_map.py``:
  there the lever is looked up by the parameter's kind, but here it lies
  in Revit's own behavior;
* fittings: ``route_pipe_system`` builds EXACTLY len(segments) pipes
  (connect.py ``emit_segments_cs`` — one Create line per edge), but the
  operation does not name the NUMBER of fittings. THE CAUSE STATED HERE
  WAS WRONG until 10.08.2026 — it used to read "Revit itself built
  2 652 fittings and 152 units of Snowdon accessory hardware with ZERO
  authored ones," and both halves are refuted by something cheap to
  check. The fittings ARE AUTHORED: ``connect.emit_fittings_cs`` itself
  calls ``doc.Create.NewElbowFitting``/``NewTeeFitting``/
  ``NewTransitionFitting`` at every junction of degree >= 2 (three call
  sites: ``authoring.py`` 2951/3038/3137). And the numbers are a census
  of the ORIGINAL model, not the output of a rebuild: the L0 header for
  ``snowdon_plumb_v3`` gives ``OST_PipeFitting`` 2652,
  ``OST_DuctFitting`` 152, ``OST_PipeAccessory`` 126 (measured
  10.08.2026), meaning "152 accessories" is actually a count of DUCT
  fittings under the wrong label, there are 126 accessories in the
  model, and NOT ONE emitter in the package creates an accessory. The
  real cause is narrower already, and it is named as unmeasured:
  ``classify_junction`` can reduce a joint to a bare
  ``Connector.ConnectTo`` and produce no element at all, and which
  family gets substituted into the call is decided by routing
  preferences — neither of these has been measured. That is why
  ``OST_PipeFitting`` is not checked: a counting witness would be
  gating an unmeasured quantity, not somebody else's decision;
* derived categories exist even for peaceful ops: ``OST_SketchLines`` is
  present in 31 out of 31 decompilations (366 902 elements),
  ``OST_StairsRuns``/``Landings``/``RailingHandRail``/``RailingTopRail``
  appear on their own, following a stair and a railing. So "a category
  showed up in the model that is not in the expectation" is
  INFORMATIONAL, not a refusal (see :attr:`Verdict.unexpected`).

THIS MODULE IS ONLY THE L2 JUDGE. The live correctness loop additionally
composes it with ``acceptance_mutation``: exact-id ``set_param``,
``move_elements``, ``change_type``, and ``delete`` are reread
separately, and their ``UniqueId``/``VersionGuid`` become guards at the
transaction's entry. So the limitations below apply specifically to the
creation census, not to the whole live acceptance loop.

WHAT THE L2 CENSUS DOES NOT CATCH — AND THIS LIST MATTERS MORE THAN THE
PREVIOUS ONE. A gap that is known about is a documented boundary; a gap
that is kept silent is the very same old lie, just now in code.

* IT DOES NOT LOOK AT GEOMETRY AT ALL. Twelve walls of the right
  category at the right level, placed as garbage geometry, PASS
  acceptance. That is L3's job (a footprint inside the declared area,
  matching duplicates, a clash delta), and it is deliberately absent
  here;
* THE TYPE OF THE CREATED ELEMENT IS NOT CHECKED. A wall of the wrong
  type is still a wall. A separate exact-id ``change_type`` is checked
  by the mutation judge, but that does not prove the resulting type of
  any create op;
* A SWAP WITHIN ONE COVERAGE CELL IS INVISIBLE: demolishing someone
  else's wall and putting up your own at the same level gives the same
  delta;
* EXTRAS IN AN UNDECLARED CATEGORY — informational only. A refusal
  there would fail every honest build (see the note on derived
  categories above);
* UPPER BOUNDS ARE LIFTED ENTIRELY the moment a program contains even
  one op with an unknown category (``set_curtain_panel``,
  ``create_curtain_grid_line``) or an op whose delta has no upper bound
  (``place_family``: see below) — meaning duplicates in such programs
  are not caught. They are also lifted pointwise: for a category that
  belongs to two groups at once (a floor slab and a foundation slab),
  and for a category that something in the same program derivatively
  produces (railings alongside a stair);
* LEVEL NAMES ARE COMPARED LITERALLY (after trimming whitespace).
  Rename the level between two censuses and you get a discrepancy
  that isn't real;
* THERE IS NOTHING TO TELL A CREATION DELTA FROM SOMEONE ELSE'S EDIT: if
  another actor added elements of the same category between the two
  reads, they land in our count. Exact-id mutations are protected by a
  ``VersionGuid`` inside the transaction, A5 has its own revision guard;
  an ordinary category-census build does not yet have such an
  attributor;
* THE PURE FUNCTION ITSELF CANNOT TELL A RECEIPT FROM A REREAD. In
  production this is closed by ``acceptance_probe`` + ``acceptance_runtime``:
  one independent document-bound bridge read, a strict wire parser,
  distinct ``before``/``after`` phases. A standalone new caller must use
  the same adapter.

``PLACE_FAMILY`` IS NO LONGER BLIND, AND THIS IS NOT A WEAKENING OF THE
RULE BUT CLOSING A HOLE IN IT (09.08). The registry's most heavily used
writing op (7 000 built instances, 6 accused) could not, until today,
reach an independent ``ACCEPTED``: ``blind_ops`` non-empty ⇒
``AcceptanceRegistration.blind`` ⇒ ``INCONCLUSIVE`` on any build. The
cause of the blindness had been named as: "an instance's category = its
family's category, and the family arrives via a symbol selector — it
cannot be read from the program." The first half is true, the second is
not, and the difference decides everything: the category is not read
FROM THE PROGRAM, but it does sit in the MODEL SNAPSHOT. Every row of
the ``family_symbols`` pool carries a ``category``, read from Revit by
the same ``Enum.GetName(BuiltInCategory, …)`` that the live census uses
to key elements (``open_model.GROUND_SNAPSHOT_CS`` against
``acceptance_live.scope_census_fragment``) — that is, DATA ABOUT THE
MODEL, not the program author's opinion, exactly like
``level_names_by_id`` from the ``levels`` pool. The snapshot is taken
BEFORE the write (``acceptance_runtime.prepare_acceptance``), so
pre-registration is preserved by construction.

WHAT IS PROMISED HERE, AND WHAT IS NOT:

* what is promised is EXACTLY "cell of category C gained at least N" —
  a lower bound along one axis. This is the one statement true of ANY
  correct build, and it is enough for a placement that never happened
  to produce a ``category_shortfall``;
* the number is NOT exact (``AT_LEAST``), because Revit ITSELF creates
  nested shared-family instances: on a 59-story tower that is 21 555
  elements (``tools/content_coverage.py``, 30.07), and some of them
  fall into the parent's category. ``EXACT`` would reject every honest
  build of such a family;
* for the same reason, UPPER BOUNDS ARE LIFTED FOR THE WHOLE program: a
  nested child is entitled to land in any category, including one
  declared by a neighboring op. This is exactly what held under
  blindness too — nothing is lost;
* THERE IS NO LEVEL (the row is "floating"). A door and a window are
  also FamilyInstances, and their level is declared UNKNOWN by
  measurement: 76 of 15 569 doors sit at a level other than their
  host's. Asserting a level for ``place_family`` would mean betting on
  the unmeasured, where an error = a false refusal of a correct build;
* WHEN THE CATEGORY IS NOT PROVEN — A NAMED REFUSAL TO JUDGE, not a
  silent degradation: the pool is unavailable or truncated; candidates
  give different categories; the symbol is absent from the snapshot (it
  is created by ``create_type``/``load_family`` of the same program —
  exactly the ``partial_blind_scope`` from the contract); the category
  is named other than by a ``BuiltInCategory`` name (the snapshot falls
  back to the numeric path) — the live census does NOT carve out such a
  cell. Every such case remains a ``BlindOp`` with its own reason, i.e.
  ``ok:false``.

THE MODULE'S BOUNDARY. Both public functions are PURE: no Revit, no
network, no disk, no clock. The expectation is serializable
(:meth:`Expectation.to_dict`) and stable across processes: strings are
sorted, sets are turned into tuples. Level L2 and only L2 — footprints,
duplicates and clashes (L3), and a screenshot (L4) do not enter here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from kir import spec
from kir.diag import KirRefusal
from kir.midend import PlannedProgram
from kir.record_ratchet import CLOSE_BY, STANDS, Entry, Ledger


#: The level of an element that has none. NOT None and not "unknown":
#: the absence of a level is a census FACT (a mark, a size, a stair),
#: and it must be a countable key, not dissolve away. The same device as
#: ``NO_CATEGORY_KEY`` in §18.1 (decompile/census.py).
LEVEL_NONE = ""


class Certainty(str, Enum):
    """How firmly the delta of an expectation row is known."""

    #: Exactly this many. The one degree at which the UPPER bound is
    #: checked, meaning duplicates are caught.
    EXACT = "exact"
    #: At least this many. The top is open: Revit is entitled to add its
    #: own.
    AT_LEAST = "at_least"
    #: Neither a number nor a category. The row is not checked at all
    #: and exists for the sake of the report's honesty: "we are blind
    #: here" must be visible.
    UNKNOWN = "unknown"


class MismatchCode(str, Enum):
    """What exactly diverged. "Roughly similar" is deliberately absent."""

    #: The category gained FEWER than the program implies.
    CATEGORY_SHORTFALL = "category_shortfall"
    #: MORE was added (duplicates; checked only under full precision).
    CATEGORY_OVERSHOOT = "category_overshoot"
    #: At the declared level, fewer than declared — "built somewhere
    #: else." This class is the whole reason L2 exists.
    LEVEL_SHORTFALL = "level_shortfall"
    #: At the level, more than could have landed there under any
    #: arrangement of "floating" rows.
    LEVEL_OVERSHOOT = "level_overshoot"


@dataclass(frozen=True, slots=True)
class BlindOp:
    """An op the expectation cannot say anything checkable about.

    It exists so that blindness is NAMED. Silently skipping such an op
    is a checker that grows more confident the less it understands.
    """

    op_id: str
    op_name: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"op_id": self.op_id, "op": self.op_name, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ExpectedRow:
    """One expectation row: how much is added, where, and how firmly.

    ``categories`` — a tuple of one or more census keys. More than one
    means "the element will land in EXACTLY ONE of them, and which one
    cannot be seen from the program": a railing is either
    ``OST_StairsRailing`` or ``OST_Railings``, a DirectShape in §18.1 is
    keyed by its own BuiltInCategory, but in the extraction rows by the
    literal ``DirectShape``. The SUM over the group is checked; that way
    the check stays true under any variant and does not invent what the
    compiler does not know.

    ``level is None`` — a "floating" row: the elements will certainly
    exist, but at what level does not follow from the program.
    """

    categories: tuple[str, ...]
    level: str | None
    count: int
    certainty: Certainty
    op_ids: tuple[str, ...]
    why: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "categories": list(self.categories),
            "level": self.level,
            "count": self.count,
            "certainty": self.certainty.value,
            "op_ids": list(self.op_ids),
            "why": self.why,
        }


@dataclass(frozen=True, slots=True)
class Expectation:
    """The acceptance predicate, derived from the program.

    ``upper_bounds_valid=False`` means the program contains an op with
    an UNKNOWN category. Such an op can add elements to any declared
    category, so the duplicate check is honestly turned off.

    ``lower_bounds_valid=False`` is stronger: a
    ``delete``/replacement-like op can SUBTRACT an element from the same
    cell a create op added it to. The net delta is then smaller than the
    honestly created count, and L2 would give a false shortfall after a
    commit that already happened. In such a mixed case the census does
    not judge at all; the exact mutation judge keeps working, and the
    composite evidence stays explicitly incomplete.
    """

    rows: tuple[ExpectedRow, ...]
    derived_categories: tuple[str, ...]
    blind_ops: tuple[BlindOp, ...]
    upper_bounds_valid: bool
    op_count: int
    notes: tuple[str, ...] = ()

    @property
    def checkable(self) -> bool:
        """Whether there is even one row that can fail."""
        return (self.lower_bounds_valid
                and any(row.certainty is not Certainty.UNKNOWN
                        and row.count > 0 for row in self.rows))

    @property
    def lower_bounds_valid(self) -> bool:
        """Whether no blind operation can subtract a registered census cell."""

        return not any(op.op_name in _OPS_CAN_INVALIDATE_LOWER_BOUNDS
                       for op in self.blind_ops)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows": [row.to_dict() for row in self.rows],
            "derived_categories": list(self.derived_categories),
            "blind_ops": [op.to_dict() for op in self.blind_ops],
            "lower_bounds_valid": self.lower_bounds_valid,
            "upper_bounds_valid": self.upper_bounds_valid,
            "op_count": self.op_count,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class Mismatch:
    """A named discrepancy: what, where, how much was expected, how
    much was received."""

    code: MismatchCode
    categories: tuple[str, ...]
    level: str | None
    expected: int
    observed: int
    op_ids: tuple[str, ...]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "categories": list(self.categories),
            "level": self.level,
            "expected": self.expected,
            "observed": self.observed,
            "op_ids": list(self.op_ids),
            "detail": self.detail,
        }


#: WHY the verdict is what it is. There are three outcomes, and "there
#: was nothing to check" is one of them — a separate word, not a shade
#: of `accepted=False`. A measured refusal and the absence of a
#: measurement are fixed from OPPOSITE ends (the former — the build, the
#: latter — the expectation), so they cannot be merged into one boolean.
VERDICT_MEASURED = "measured"
VERDICT_MISMATCHED = "mismatched"
VERDICT_NOTHING_TO_CHECK = "nothing_to_check"


@dataclass(frozen=True, slots=True)
class Verdict:
    """The result of the check. ``accepted`` is the only thing that
    carries weight.

    ``accepted`` IS DERIVED, NOT STORED, AND FAILS CLOSED. It used to be
    a FIELD, and `check_acceptance` put `not mismatches` into it. At
    zero checked groups there are no mismatches BY CONSTRUCTION —
    meaning the verdict declared success without checking anything,
    exactly the case the whole module was written to forbid. Now
    success requires TWO things at once: zero mismatches AND at least
    one checked group. There is no longer any field named ``accepted``
    at all, so a verdict that lies cannot even be constructed.

    ``reason`` SEPARATES A FINDING FROM EMPTINESS. Both cases give
    ``accepted=False``, but `mismatched` means "the build diverged from
    the expectation," while `nothing_to_check` means "there was nothing
    for the expectation to fail on"; a bare ``False`` would merge them,
    and they are cured differently.

    ``vacuous=True`` — the acceptance CHECKED NOTHING AT ALL (the
    expectation is empty or everything in it is unknown). The field is
    kept: it predates ``reason`` and is already referenced from outside
    (`preview` holds the same device under the same name).

    ``unexpected`` — categories where a delta exists but is absent from
    the expectation. This is INFORMATIONAL, not a refusal: Revit makes
    more derived elements than authored ones (366 902 ``OST_SketchLines``
    across 31 decompilations), and a refusal here would fail every
    honest build.
    """

    mismatches: tuple[Mismatch, ...]
    checked_groups: int
    unexpected: tuple[tuple[str, int], ...]
    upper_bound_groups: tuple[tuple[str, ...], ...]
    blind_ops: tuple[BlindOp, ...]

    @property
    def upper_bounds_checked(self) -> bool:
        """Compatibility bit: every checked group had an upper-bound check.

        Eligibility flags in Expectation are not evidence that any check ran.
        A vacuous or partially covered scope never reports full coverage.
        """
        return self.checked_groups > 0 and len(self.upper_bound_groups) == self.checked_groups

    @property
    def upper_bound_coverage(self) -> str:
        if self.upper_bounds_checked:
            return "full"
        return "partial" if self.upper_bound_groups else "none"

    @property
    def accepted(self) -> bool:
        """Success = NO mismatches AND there WAS something to check.
        Both conjuncts are needed: the first without the second is
        "it matched" about an empty set."""
        return not self.mismatches and self.checked_groups > 0

    @property
    def reason(self) -> str:
        return (VERDICT_MISMATCHED if self.mismatches
                else VERDICT_NOTHING_TO_CHECK if self.checked_groups == 0
                else VERDICT_MEASURED)

    @property
    def vacuous(self) -> bool:
        return self.checked_groups == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "vacuous": self.vacuous,
            "mismatches": [m.to_dict() for m in self.mismatches],
            "checked_groups": self.checked_groups,
            "unexpected": [{"category": c, "delta": d}
                           for c, d in self.unexpected],
            "upper_bounds_checked": self.upper_bounds_checked,
            "upper_bound_coverage": self.upper_bound_coverage,
            "upper_bound_groups": [list(group) for group in self.upper_bound_groups],
            "blind_ops": [op.to_dict() for op in self.blind_ops],
        }

    def summary_ru(self) -> str:
        if self.vacuous:
            return ("приёмка НИЧЕГО не проверила: в ожидании нет ни одной "
                    "проверяемой строки")
        if self.accepted:
            tail = "" if self.upper_bounds_checked else (
                " (верхние границы не проверялись)" if not self.upper_bound_groups else
                f" (верхние границы проверены только для {len(self.upper_bound_groups)} "
                f"из {self.checked_groups} групп)")
            return (f"сошлось; проверено групп категорий: "
                    f"{self.checked_groups}{tail}")
        parts = "; ".join(m.detail for m in self.mismatches[:4])
        more = len(self.mismatches) - 4
        if more > 0:
            parts += f"; ещё {more}"
        return f"НЕ сошлось: {parts}"


# ── Tables: the category, level, and lever of every op ──────────────────────
#
# The tables are EXPLICIT, not derived from ``lift.LIFTER_TABLE``, though
# the temptation is strong. The reason is the direction: the lifter's
# table answers "which op WOULD HAVE LIFTED an element of this
# category," while here the reverse question is needed: "which category
# does the result of THIS op land in," and the two do not always agree
# (``create_column`` has two categories to choose from,
# ``create_foundation(slab)``'s category depends on the TYPE, and half
# the lifter registry has none at all). Silently inheriting future
# lifter rows would give an expectation no one had checked — so the
# link between the tables is held by a TEST (``test_acceptance``), not
# an import.

#: ONE TABLE, AND IT LIVES IN THE REGISTRY. Before 10.08, "which
#: category will the result of this op land in" was known by TWO
#: dictionaries: this one and `clash_bundle.OP_CATEGORY` (29 ops against
#: 43), and `spec.op_census_categories` asked the ACCEPTANCE JUDGE for
#: the answer — meaning the registry depended on acceptance, not the
#: other way around. A question about an op's result is a question TO
#: THE REGISTRY, so the table and its resolver moved to `spec`, and what
#: remains here are the names already referenced from outside.
#:
#: THE REMAINING DUPLICATE IS NAMED: `clash_bundle.OP_CATEGORY`.
#: Migrating it this session was not possible (the file was held by
#: another agent), and the next one must know about it, along with
#: whose side to take:
#:
#:   * `create_column` — THE SIDES DO NOT CONTRADICT, though it looks
#:     that way. Acceptance answers `("OST_StructuralColumns",
#:     "OST_Columns")`, clash holds `""` — but `clash_bundle.category_of`
#:     reads this string as `OP_CATEGORY.get(name) or None` and resolves
#:     the column in a BRANCH above it (`_column_category`). An empty
#:     string there is a marker for "resolved outside the table," not a
#:     claim of an empty category.
#:   * `create_railing` — NOW THIS IS A REAL DISCREPANCY, and neither
#:     side has an exception branch: acceptance expects the SUM over
#:     `("OST_Railings", "OST_StairsRailing")`, clash names just one,
#:     `"OST_StairsRailing"`. Acceptance's side is correct, and the
#:     reason is recorded right in the row below: `OST_Railings` never
#:     occurred in any of the 31 decompilations, but the lifter table
#:     knows BOTH, and a different Revit version could decide
#:     otherwise; the sum over both is correct under any answer, picking
#:     one is a bet.
_OP_CATEGORIES: Mapping[str, tuple[str, ...]] = spec.OP_RESULT_CATEGORIES

#: Derived categories: elements Revit creates ON ITS OWN, following an
#: op. Never checked, and never included in the "unexpected" report.
_OP_DERIVED: Mapping[str, tuple[str, ...]] = {
    # A curtain-type wall spawns its own cells, panels, and mullions;
    # the type is a selector, so "is it a curtain wall" is not visible
    # from the program.
    "create_wall": ("OST_CurtainGridsWall", "OST_CurtainWallPanels",
                    "OST_CurtainWallMullions"),
    "create_floor": ("OST_SketchLines",),
    "create_floor_by_contour": ("OST_SketchLines",),
    "create_roof": ("OST_SketchLines",),
    # An extruded roof spawns the same sketch lines as a footprint
    # roof does — in Revit, the profile is a real sketch.
    "create_extrusion_roof": ("OST_SketchLines",),
    "create_ceiling": ("OST_SketchLines",),
    "create_foundation": ("OST_SketchLines",),
    "create_stairs": ("OST_StairsRuns", "OST_StairsLandings",
                      "OST_StairsRailing", "OST_StairsRailingBaluster",
                      "OST_RailingHandRail", "OST_RailingTopRail",
                      "OST_SketchLines"),
    # ConnectLevels spawns a flight for every added level, and each one
    # drags along the same brood as an ordinary stair. The number of
    # derived elements here is proportional to the number of levels,
    # not to one — so the census must know them as DERIVED, or an
    # honest success would read as somebody else's unordered create.
    "create_multistory_stairs": ("OST_Stairs", "OST_StairsRuns",
                                 "OST_StairsLandings",
                                 "OST_StairsRailing",
                                 "OST_StairsRailingBaluster",
                                 "OST_RailingHandRail",
                                 "OST_RailingTopRail",
                                 "OST_SketchLines"),
    "create_railing": ("OST_StairsRailingBaluster", "OST_RailingHandRail",
                       "OST_RailingTopRail",
                       "OST_RailingRailPathExtensionLines"),
    # The fittings are authored (emit_fittings_cs calls NewElbow/
    # NewTee/NewTransitionFitting), but the op does not name their
    # NUMBER, and it has not been derived by any measurement; not one
    # emitter in the package creates an accessory. The earlier row cited
    # "2 652 fittings and 152 accessories with ZERO authored ones" —
    # that is a census of snowdon_plumb_v3 (PF=2652, DF=152, PA=126),
    # not the output of a rebuild; see the module docstring
    # (10.08.2026).
    "create_pipe_system": ("OST_PipeFitting", "OST_PipeAccessory"),
    "route_pipe_system": ("OST_PipeFitting", "OST_PipeAccessory"),
    "route_duct_system": ("OST_DuctFitting", "OST_DuctAccessory"),
    # The group wrapper is Revit's own bookkeeping: model-based or
    # node-based, depending on the members' makeup. Counting it exactly
    # would mean guessing.
    "create_group": ("OST_IOSModelGroups", "OST_IOSDetailGroups"),
    "create_curtain_grid_line": ("OST_CurtainWallMullions",
                                 "OST_CurtainWallPanels"),
}

#: 🔴 FOR WHICH OPS THE `_OP_DERIVED` ROW IS AN OVERESTIMATE, NOT A FACT
#: (F-312, 30.08.2026). The table above was set up to EXCLUDE categories
#: from the "unexpected" report ("never checked"), and for that purpose
#: an overestimate is safe: an extra exclusion accuses no one. But
#: `viewer.graph` incremented EVERY row and captioned the summary "Revit
#: WILL ADD" — meaning something conditional was presented as certain.
#:
#: A COVERAGE MEASUREMENT ON 30.08.2026 (turn 1, mine): 219 724 ops in
#: the table across 57 of 65 corpus decompilations; of those,
#: `create_wall` — 196 110, and CURTAIN walls among them — 1 968. That
#: is, for 194 142 real walls (99.0%) the claim "Revit will add cells,
#: panels, and mullions" is FALSE.
#:
#: THE REASON FOR THE CONDITIONALITY IS NOT MADE UP — it already stood
#: in the table's comments, in prose, and here it gets a name. The list
#: is CLOSED and its completeness is guarded by a number: every
#: `_OP_DERIVED` key must be classified, or a new op will silently fall
#: back into "certain."
_OP_DERIVED_CONDITIONAL: Mapping[str, str] = {
    "create_wall": ("только у стены ВИТРАЖНОГО типа; тип — селектор, и "
                    "«витражная ли она» из программы не видно"),
    "create_group": ("обёртка группы модельная ЛИБО узловая, смотря по "
                     "составу членов — обе сразу не бывают никогда"),
}

#: Ops whose result level EQUALS the resolved ``level`` selector.
#: Everything absent here "floats" — and almost every absence is paid
#: for by a measurement (the module's header).
_LEVEL_FROM_PARAM: frozenset[str] = frozenset({
    "create_wall", "create_floor", "create_floor_by_contour", "create_roof",
    "create_ceiling", "create_column", "create_room", "create_pipe",
    "create_duct", "create_cable_tray", "create_foundation",
    # wave/mep-electrical: for all five, the level is passed INTO THE
    # CALL ITSELF (`levelId`), meaning it equals the resolved selector
    # by construction, not by coincidence — exactly like the pipe and
    # the tray above. Checked by the same witness
    # `RBS_START_LEVEL_PARAM`.
    "create_conduit", "create_pipe_placeholder", "create_duct_placeholder",
    "create_flex_duct", "create_flex_pipe",
    "create_pipe_system", "route_pipe_system", "route_duct_system",
    # wave/room: the sketch plane is built FROM THE LEVEL ITSELF
    # (SketchPlane.Create(doc, levelId)), so the result level equals the
    # resolved selector by construction, not by coincidence.
    "create_room_separator",
    # wave/space (10.08): the level rides INTO THE CALL ITSELF
    # (`NewSpace(Level, UV)`), meaning it equals the resolved selector
    # by construction — exactly like create_room in the row above.
    # Checked by the same `Element.LevelId` that both the op's witness
    # and the extraction side read it by: one question, one judge.
    "create_space",
})

#: Writing ops that add NOT ONE element to the census.
#:
#: 🔴 THERE IS ONE OBJECT, AND IT LIVES IN THE REGISTRY (moved on
#: 28.08.2026). What stands here is an ALIAS, not a copy:
#: `spec.OPS_WITHOUT_ELEMENTS` — the very same frozenset, and the
#: identity is held by a test (`assertIs`), like the neighboring
#: category table. A second list of the same names would drift from the
#: first at the very first new op.
#:
#: Why it moved: the registry (`spec.op_disciplines`,
#: `spec.group_member_yields_one`) was asking for this list HERE — from
#: its own consumer — and the architectural lock was rightly flagging
#: red over it. The reasoning for every name moved TOGETHER with the
#: list — authority without its own reasoning would only be half an
#: authority.
_OPS_WITHOUT_ELEMENTS: frozenset[str] = spec.OPS_WITHOUT_ELEMENTS

#: Ops whose delta can be neither named nor bounded below — with a
#: reason. The reason goes into the report verbatim: "blind" without an
#: explanation is indistinguishable from "forgotten."
#:
#: ``place_family`` remains here ONLY as a refusal heading: since 09.08
#: its category is taken from the snapshot's ``family_symbols`` pool
#: (see the module header), and it lands among the blind only when the
#: snapshot fails to prove it. The reason is then filled in
#: concretely — "the pool was truncated," "different categories," "no
#: symbol before the write" — because "blind" without a breakdown is
#: indistinguishable from "we didn't look."
#: SINCE 09.08.2026 EVERY ROW IS DATED AND CARRIES A VERDICT
#: (`record_ratchet`). The reason this very journal exists: the
#: `place_family` row used to explain its blindness by saying the
#: category "cannot be read from the program." That is TRUE, and yet it
#: is not the real reason: the category sat in the SNAPSHOT the program
#: is grounded on, and acceptance simply never asked it. The corpus's
#: most heavily used op — 7 000 builds — was blind because of a SWAP IN
#: THE JUSTIFICATION, while the justification looked measured. A truth
#: with no deadline is an archive.
#:
#: `stands-because` against `close-by` is not cosmetic here, it is a
#: DIFFERENT thing: six rows are structural (the snapshot does not
#: store what is not in it; Revit picks the layout inside the
#: transaction), and a deadline on them would be a fiction. Two are
#: closed by work, and they do have a deadline.
#: 🔴 FIVE STANDING DECISIONS WERE RE-MEASURED ON 01.09.2026, AND THIS
#: IS A RUN, NOT A DATE.
#:
#: `record_ratchet` turned red on `place_family`, `delete`,
#: `change_type`, `set_curtain_panel`, `create_curtain_grid_line`: the
#: 30.07 decision had reached 33 days against `REVIEW_DAYS = 30`. The
#: ratchet WAS RIGHT — that is exactly what it was set up for.
#:
#: Re-measured by an instrument named in the journal itself:
#: `derive_expectation()` on a program made of ONLY this one op. A row
#: holds as long as the op falls into `blind_ops`, not into `rows`. The
#: result — five out of five hold, and each one's reason matched what
#: was recorded VERBATIM:
#:
#:     delete                   op_count=1  rows=0  blind_ops=[delete]
#:     change_type              op_count=1  rows=0  blind_ops=[change_type]
#:     set_curtain_panel        op_count=1  rows=0  blind_ops=[set_curtain_panel]
#:     place_family             op_count=1  rows=0  blind_ops=[place_family]
#:     create_curtain_grid_line op_count=1  rows=0  blind_ops=[create_curtain_grid_line]
#:
#: 🔴 THE DENOMINATOR WITHOUT WHICH THESE FIVE ROWS ARE NOT A
#: MEASUREMENT. The probe's first three attempts gave `op_count=0` for
#: ALL ops, and "not in blind" would have read as "the decision has
#: gone stale." Not one of the three zeros was about the actual
#: subject: first the probe was reading a nonexistent field `blind`
#: instead of `blind_ops` and silently getting `{}` from `getattr`;
#: then the programs failed to pass the plan (`KIR-D001` — a
#: destructive op needs `allow_destructive`); then the ops' fields were
#: invented rather than taken from the registry
#: (`KIR-P003/T001/P005/P007`, and a cut line's `direction` accepts
#: `u`/`v`, not `horizontal`/`vertical`). What saved it was `notes`: the
#: expectation NAMES that the program failed to plan, instead of
#: handing back a plausible zero. Without this row, the re-measurement
#: would have lied in its own favor three times over — "the row has
#: gone stale, take it down."
_OPS_BLIND_ENTRIES: Mapping[str, Entry] = {
    "place_family": Entry(
        STANDS, "2026-09-01", "",
        "категория экземпляра = категория семейства, и снимок её не "
        "подтверждает"),
    "delete": Entry(
        STANDS, "2026-09-01", "",
        "цель адресуется id или ссылкой; какой категории элемент удалён, "
        "программа не говорит"),
    # 21.08.2026, found by the coverage law `TestRegistryCoverage`: the
    # op arrived with the 20.08 wave and was not sorted here by ANY
    # register — meaning it silently fell out of acceptance.
    #
    # The argument is verbatim the same as `place_family`'s above, and
    # it is not an analogy but the same mechanism: an adaptive
    # component is a FAMILY INSTANCE, its category is the family's
    # category, and the snapshot does not confirm it. Its own points
    # (`points_mm`) are not enough for the census: they say WHERE the
    # component sits, and say nothing about WHAT it is.
    "create_adaptive_component": Entry(
        STANDS, "2026-08-21", "",
        "категория экземпляра = категория семейства, и снимок её не "
        "подтверждает; points_mm говорят положение, а не род"),
    # A TRACE OF THE 09.08 MERGE. The datums wave was writing this
    # journal as PLAIN ROWS — its base predated the ratchet — and a
    # text merge cut a dict literal in half: the end of the `delete`
    # entry from one side and the new `_OPS_BLIND` declaration from the
    # other. The lesson is recorded here because it is general: MERGING
    # A DICT IS NOT MERGING TEXT, and Python resolves duplicate keys
    # silently, keeping the last one. The wave's entries have been
    # brought into the journal's form, the `place_family` and `delete`
    # duplicates removed — the dated versions carry the more precise
    # reason (see the header about the swap in `place_family`'s
    # justification).
    #
    # wave/datums (09.08.2026). The blindness is NAMED and has exactly
    # two causes, both about the census, not the op. FIRST: the
    # container and its links share ONE cell — every link of a chain is
    # an ordinary Grid of category OST_Grids, and the cell would get
    # "+1" where Revit places 1 + (len(path)-1); declaring "+1" would
    # mean a CORRECTLY built chain reads as somebody else's create.
    # SECOND, more honest than the first: the category of
    # MultiSegmentGrid itself is NOT MEASURED, and a guess in the
    # census table is indistinguishable from a fact. WHAT THIS DOES NOT
    # OVERRIDE: the op's witness checks both the NUMBER of grids and
    # the ENDS of every link by rereading from the document. It is the
    # census that is blind, not the op.
    "create_multi_segment_grid": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "контейнер цепи и каждое её звено — элементы одной категории "
        "OST_Grids, поэтому одна ячейка переписи получает 1+N вместо 1; "
        "к тому же категория самого MultiSegmentGrid не замерена живым "
        "Revit — оп при этом проверяется своим свидетелем (число осей и "
        "концы каждого звена, перечитанные из документа)"),
    "create_stairs_run": Entry(
        CLOSE_BY, "2026-08-15", "2026-09-14",
        "категория марша живым Revit НЕ ЗАМЕРЕНА. `OST_StairsRuns` "
        "существует на всех шести (замер компиляцией 15.08), и "
        "`Stairs.GetStairsRuns()` возвращает id — но ЧТО увидит в этой ячейке "
        "перепись, не проверял никто: разбор `StairsRun` не читает вовсе "
        "(см. одноимённую строку `reverse_contract`), а живого прогона у опа "
        "нет по решению владельца (инцидент модального окна 15.08). "
        "СОСЕДНЯЯ ПЛОЩАДКА строку в OP_RESULT_CATEGORIES взяла — здесь она "
        "НЕ взята сознательно, и это не робость: ошибка слепоты обратима "
        "(теряется верхняя граница), ошибка заполнения — нет, она отклоняет "
        "ЧЕСТНУЮ постройку. Цена слепоты тут заведомо мала: оп СОЛО, значит "
        "снятая верхняя граница принадлежит его собственной программе и ни "
        "одного соседа не задевает. Закрывается ОДНИМ живым прогоном — "
        "квитанция уже везёт Category.Id созданного элемента"),
    "change_type": Entry(
        STANDS, "2026-09-01", "",
        "смена типа обычно идёт НА МЕСТЕ, но документированный случай "
        "стена ↔ витражная панель создаёт НОВЫЙ элемент другой категории"),
    "set_curtain_panel": Entry(
        STANDS, "2026-09-01", "",
        "ChangePanelType при типе-стене строит стену вместо панели "
        "(замер 28.07) — дельта категорий не выводима"),
    "create_curtain_grid_line": Entry(
        STANDS, "2026-09-01", "",
        "линия разрезки делит ячейки: число панелей и импостов после неё "
        "определяет Revit"),
    # THE COUNT IS KNOWN (exactly one element), THE CATEGORY IS NOT, and this
    # is a measurement, not laziness. None of the parses saved to disk
    # contain A SINGLE WallFoundation (grep over L0.jsonl of all parses,
    # 09.08), meaning there is nothing to check against for which census cell
    # a strip foundation falls into. Writing «OST_StructuralFoundation» here
    # by Revit's taxonomy is exactly the kind of temptation that made
    # acceptance reject CORRECTLY built programs: an error here gives a FALSE
    # REFUSAL of a correct build, while blindness only loses the upper bound.
    # Of two evils the reversible one was chosen. It closes with ONE live
    # run: it suffices to read the Category.Id of the created element (the
    # receipt already carries it).
    # A DEADLINE EXISTS, because the entry itself names what closes it: one
    # live run, the Category.Id of the created element, which the receipt
    # already carries.
    "create_wall_foundation": Entry(
        CLOSE_BY, "2026-08-09", "2026-09-08",
        "категория ленточного фундамента не замерена: WallFoundation не "
        "встретился ни в одном сохранённом разборе, а назвать клетку "
        "переписи по памяти значит завернуть верную постройку"),
    # wave/framing (09.08). For BOTH operations the blindness is not about
    # the wrapper's category but about what is SPAWNED: one call places both
    # the object itself and an a priori unknown number of elements inside it.
    # This is exactly the case of create_pipe_system, where the op does not
    # name the number of fittings (the fittings themselves are authorial, and
    # their count is unmeasured) — there too it is named, not estimated.
    "create_beam_system": Entry(
        STANDS, "2026-08-09", "",
        "число балок выбирает LayoutRule уже внутри транзакции: ни одного "
        "количества операция не называет, поэтому дельта каркаса не выводима "
        "ни сверху, ни снизу — тот же случай, что фитинги у трубной системы"),
    "create_truss": Entry(
        STANDS, "2026-08-09", "",
        "стержни фермы (пояса, раскосы, стойки) порождает семейство фермы, а "
        "их число и категории зависят от него — из программы не читается "
        "ничего, кроме того, что стержни будут"),
    # wave/reinforcement (10.08). The blindness is DOUBLE, and both halves
    # are measured, not assumed. FIRST: one call places both the
    # reinforcement system itself and an a priori unknown number of bars
    # (`RebarInSystem`), and there may be NONE at all — Autodesk states that
    # with `ReinforcementSettings.HostStructuralRebar` turned off, ZERO of
    # them are created. SECOND: the census cell of the system itself is
    # unmeasured — in 38 saved parses with a census there are ZERO
    # OST_AreaRein elements (measured 10.08 from the census records of the
    # whole corpus). Writing a cell here by Revit's taxonomy is the same kind
    # of temptation as with the strip foundation: an error here gives a
    # FALSE REFUSAL of a correct build, blindness only loses the upper
    # bound. The op's own witness is meanwhile full-fledged (host, type,
    # rebar type, and non-emptiness of bars under the enabled setting) — it
    # is the census that is blind, not the op.
    # FAMILY AUTHORSHIP (21.08.2026). THE BLINDNESS HERE IS STRUCTURAL, AND
    # THIS IS NOT "not measured yet": the category of the created family is
    # decided by the TEMPLATE FILE on the user's machine. We do not set it
    # with any op parameter (`.rft` brings its own — «Обобщённые модели» for
    # the metric default template, but which one exactly depends on the
    # locale and on which file was found). That is, the census cell is not
    # derivable from the PROGRAM by construction, not from an omission, and
    # `STANDS` is more honest here than any deadline.
    #
    # THE COST OF BLINDNESS IS KNOWN TO BE SMALL, AND THIS IS THE SAME
    # ARGUMENT AS FOR `create_stairs_run`: the op is SOLO, so the lifted
    # upper bound belongs to its own program and touches no neighbor.
    # Writing OST_GenericModel here by taxonomy would be a temptation of
    # exactly the same kind as with the strip foundation: a fill-in error
    # REJECTS a correct build, blindness only loses the upper bound. Of two
    # evils the reversible one was chosen.
    #
    # WHAT THIS DOES NOT CANCEL: the op's witness is full-fledged and
    # STRONGER than the census — it does not count elements but DOUBLES a
    # parameter inside the family document and requires a volume ratio of
    # 2.0000. It is the census that is blind, not the op.
    "author_family": Entry(
        STANDS, "2026-08-21", "",
        "категорию семейства приносит ФАЙЛ ШАБЛОНА с машины пользователя "
        "(Application.FamilyTemplatePath), а не параметр операции — клетка "
        "переписи не выводится из программы по построению; экземпляр к тому "
        "же необязателен (place_at), и без него дельта равна нулю при вполне "
        "успешной программе"),
    "create_area_reinforcement": Entry(
        STANDS, "2026-08-10", "",
        "один вызов кладёт систему и неизвестное заранее число стержней "
        "(RebarInSystem), а при выключенной ReinforcementSettings."
        "HostStructuralRebar не кладёт ни одного — дельта не выводима ни "
        "сверху, ни снизу; клетка переписи самой системы к тому же не "
        "замерена (ноль OST_AreaRein во всём корпусе разборов)"),
}

#: THE JOURNAL OF BLIND OPS. Consumers take the reason as ONE piece of text —
#: via `.reason`, rather than rewriting it a third time next to the refusal
#: site.
_OPS_BLIND = Ledger(
    "acceptance._OPS_BLIND", _OPS_BLIND_ENTRIES,
    instrument=(
        "derive_expectation() на программе из одного этого опа и снимке "
        "заземления: строка держится, пока оп попадает в blind, а не в rows; "
        "у place_family решает наличие его символа в пуле family_symbols"))

# These operations may delete or replace a pre-existing instance.  Because
# the current L2 wire predicate does not preregister the old category x level
# cell, their negative contribution cannot be separated from a create-op's
# positive contribution.  Purely additive unknown-category operations (for
# example place_family) only invalidate upper bounds and are not listed here.
_OPS_CAN_INVALIDATE_LOWER_BOUNDS: frozenset[str] = frozenset({
    "delete", "change_type", "set_curtain_panel",
    "create_curtain_grid_line",
})


#: The census key must be the NAME of ``BuiltInCategory``. The live census
#: (``acceptance_live.scope_census_fragment``) keys an element by the string
#: ``Enum.GetName(typeof(BuiltInCategory), id)`` and drops everything not in
#: the declared set; the snapshot writes the same string via the same call,
#: BUT has a numeric fallback path (``?? __categoryId.ToString()``) for a
#: category with no name in the enum. The live census will NEVER surface a
#: numeric key — so this is exactly the case of "there is no cell to
#: assign", where the only honest answer is to refuse judgment.
_CENSUS_CATEGORY_RE = re.compile(r"OST_[A-Za-z0-9_]+\Z")

#: The ``place_family`` expectation row: why the top is left open.
_PLACE_FAMILY_WHY = (
    "экземпляр ровно один, но ВЛОЖЕННЫЕ общие семейства Revit создаёт сам "
    "(21 555 элементов на 59-этажной башне) — верх клетки открыт")

#: Why upper bounds are lifted across the whole program when the category is
#: known.
_PLACE_FAMILY_OPEN_NOTE = (
    "верхние границы сняты целиком: вложенные общие семейства, которые Revit "
    "создаёт вслед за place_family, вправе лечь в ЛЮБУЮ категорию, в том "
    "числе объявленную соседним опом")


def symbol_rows_from_snapshot(
        snapshot: Mapping[str, Any] | None) -> tuple[Mapping[str, Any], ...] | None:
    """Rows of the ``family_symbols`` pool — or ``None`` if they cannot be trusted.

    ``None`` (rather than an empty tuple) means "no data", and these are
    different facts: an empty pool says no symbols were found in the model,
    while an absent one says we did not look. A pool truncated by the
    collector (``__truncated``) also yields ``None``: a symbol of another
    category could remain past the cutoff, and "all visible candidates
    agree" would stop proving anything — the same argument by which
    ``ground`` refuses sole-entry there.
    """
    if not isinstance(snapshot, Mapping):
        return None
    if snapshot.get("family_symbols__truncated"):
        return None
    rows = snapshot.get("family_symbols")
    if not isinstance(rows, list):
        return None
    return tuple(row for row in rows if isinstance(row, Mapping))


def _symbol_candidates(selector: Any,
                       rows: Sequence[Mapping[str, Any]],
                       ) -> tuple[list[Mapping[str, Any]] | None, str]:
    """Rows of the pool with which ``ground`` COULD resolve this selector.

    The set is DELIBERATELY WIDER than what ``ground`` will pick: the
    narrowing by ``disambiguate_by`` is not repeated, and with ``by=default``
    the whole pool becomes candidates. Acceptance needs not the symbol's
    identity but its CATEGORY, and "all candidates agree" is a stronger
    claim than "this one will win". Erring toward too many candidates can
    only lead to a refusal of judgment; erring toward too few leads to a
    false refusal of the build.
    """
    if selector is None:
        # symbol omitted: ground takes the sole one in the pool (there is no
        # most_used rule for family_symbols — the pool is excluded from
        # MOST_USED_POOLS).
        return (list(rows), "")
    if not isinstance(selector, Mapping):
        return (None, "селектор symbol не объект")
    by = selector.get("by")
    value = selector.get("value")
    if by == "family_type":
        want = {key: selector.get(key)
                for key in ("category", "family_name", "type_name")}
        if any(not isinstance(item, str) or not item.strip()
               for item in want.values()):
            return (None, "family_type-селектор неполон")
        want = {key: item.strip() for key, item in want.items()}
        return ([row for row in rows
                 if all(row.get(key) == item for key, item in want.items())], "")
    if by == "element_id":
        if isinstance(value, bool) or not isinstance(value, int):
            return (None, "element_id-селектор не целое")
        return ([row for row in rows if row.get("id") == value], "")
    if by == "name":
        if not isinstance(value, str) or not value.strip():
            return (None, "name-селектор пуст")
        want_name = value.strip()
        exact = [row for row in rows
                 if str(row.get("name", "")).strip() == want_name]
        if not exact:
            # The same fallback path as in ground._resolve_one.
            exact = [row for row in rows
                     if str(row.get("name", "")).strip().lower()
                     == want_name.lower()]
        return (exact, "")
    if by == "default":
        return (list(rows), "")
    return (None, f"селектор symbol вида {by!r} по снимку не разрешается")


def _family_symbol_category(selector: Any,
                            rows: Sequence[Mapping[str, Any]] | None,
                            ) -> tuple[str | None, str]:
    """The category of the future instance, or ``None`` and a reason for refusal.

    The claim is proved ONLY by the agreement of all candidates: one
    category for all of them — and then it does not matter which one
    ``ground`` will actually pick. Any uncertainty returns a reason, not a
    guess.
    """
    if rows is None:
        return (None, "пул family_symbols снимка недоступен или обрезан")
    candidates, refusal = _symbol_candidates(selector, rows)
    if candidates is None:
        return (None, refusal)
    if not candidates:
        return (None, "символа нет в снимке ДО записи (например, его создаёт "
                      "create_type/load_family в этой же программе)")
    found = {row.get("category") for row in candidates}
    if len(found) != 1:
        return (None, f"кандидаты дают {len(found)} разных категорий")
    category = found.pop()
    if (not isinstance(category, str)
            or _CENSUS_CATEGORY_RE.fullmatch(category) is None):
        return (None, "категория символа названа не именем BuiltInCategory — "
                      "живая перепись такую клетку не выделяет")
    return (category, "")


def _level_from_selector(selector: Any,
                         level_names: Mapping[str, str],
                         level_names_by_id: Mapping[str, str]) -> str | None:
    """The level name from the selector, or None if there is nowhere to take a name from.

    ``by=default`` gives a rule, not a name; ``by=element_id`` gives a
    number, and the name for it is found ONLY in the model's lookup.
    Substituting something of our own here would mean checking against the
    wrong level and failing a correct build.

    WHY A LOOKUP BY id IS NEEDED. Without it the level axis is BLIND exactly
    where it is needed most: the rebuild materializer pins the level as
    ``{"by": "element_id"}`` (``same_document`` mode), and on a real building
    (sob62_fas_r23_v18, 11 programs, 2 720 ops) NOT ONE of 2 450 expectation
    rows got a level — that is, L2 degenerated into L1. The lookup is DATA
    ABOUT THE MODEL (the snapshot's ``levels`` pool), not the program
    author's opinion: it cannot weaken the predicate, and without it there
    is simply no predicate.
    """
    if not isinstance(selector, dict):
        return None
    by = selector.get("by")
    value = selector.get("value")
    if by == "name" and isinstance(value, str) and value.strip():
        return value.strip()
    if by == "ref" and isinstance(value, str):
        return level_names.get(value.strip())
    if by == "element_id" and value is not None:
        return level_names_by_id.get(str(value))
    return None


def _category_of_op(op: Mapping[str, Any]) -> tuple[str, ...] | None:
    """Census keys for the op's result; None means the category is unknown.

    A THIN WRAPPER OVER THE REGISTRY, not a second answer. The resolver
    moved into `spec.op_result_categories` together with the table:
    previously `spec` imported THIS function, meaning the registry asked
    acceptance for the category. The name was kept because it is referenced
    from outside (`test_opening`, `test_mass`) and within this file.
    """
    return spec.op_result_categories(op)


def _plural_count(op: Mapping[str, Any]) -> tuple[int, Certainty, str]:
    """How many elements the op will yield: the count, its firmness, and the reason for softness."""
    name = op.get("op")
    if name in ("create_pipe_system", "route_pipe_system",
                "route_duct_system"):
        segments = op.get("segments")
        if not isinstance(segments, Sequence) or isinstance(segments, str):
            return (0, Certainty.UNKNOWN, "segments не список")
        # One edge — one Create line (connect.emit_segments_cs).
        return (len(segments), Certainty.EXACT,
                "одно ребро графа = один отрезок трубы/воздуховода")
    if name == "create_room_separator":
        # A polyline of n points = n-1 ModelCurve, and this is an EXACT
        # count, not a lower bound: NewRoomBoundaryLines places one curve per
        # CurveArray element. EXACT matters more than convenience — only it
        # catches EXTRA elements, and an extra boundary cuts a room in two.
        path = op.get("path")
        if not isinstance(path, Sequence) or isinstance(path, str) \
                or len(path) < 2:
            return (0, Certainty.UNKNOWN, "path не ломаная из >=2 точек")
        return (len(path) - 1, Certainty.EXACT,
                "одно звено ломаной = один сегмент границы")
    if name == "create_railing":
        if op.get("variety") == "hosted":
            return (1, Certainty.AT_LEAST,
                    "Railing.Create(host) возвращает КОЛЛЕКЦИЮ: у марша "
                    "ограждение встаёт с двух сторон сразу")
        return (1, Certainty.EXACT, "")
    return (1, Certainty.EXACT, "")


def _normalise_program(program: Any) -> tuple[list[dict], tuple[str, ...]]:
    """Consume the compiler's immutable plan; never re-plan accepted input.

    A raw envelope is supported for the standalone API, but it is converted by
    the public compiler mid-end exactly once.  Serving passes the
    ``CompileOutput.planned`` object, binding acceptance to the same payload
    that was emitted.  A bare list remains a compatibility input and is wrapped
    in the current IR envelope before planning.
    """
    if isinstance(program, PlannedProgram):
        return program.to_ops(), ()
    if isinstance(program, Mapping):
        envelope: Any = program
    elif isinstance(program, Sequence) and not isinstance(program, (str, bytes)):
        envelope = {"ir_version": spec.IR_VERSION, "ops": list(program)}
    else:
        return ([], ("программа не объект, не список и не PlannedProgram",))

    # Lazy import prevents acceptance from entering the package's compiler
    # import chain when it is used only to check an already registered digest.
    from kir.compiler import plan_program
    try:
        planned = plan_program(envelope)
    except KirRefusal as exc:
        codes = tuple(dict.fromkeys(diag.code for diag in exc.diagnostics))
        suffix = ",".join(codes) if codes else "без кода"
        return ([], (f"программа не прошла KIR plan: {suffix}",))
    except Exception as exc:  # defensive: acceptance must stay honest/fail-closed
        return ([], (f"KIR plan не построен: {exc.__class__.__name__}",))
    return planned.to_ops(), ()


def _lifts(placement: Any) -> bool:
    """Whether this group instance lifts the copy vertically.

    An instance is [dx, dy] or [dx, dy, dz]. A nonzero `dz` means the copy
    will end up NOT on the level where the definition member stands, and the
    level of such a copy is not derivable from the program.
    """
    if not isinstance(placement, (list, tuple)) or len(placement) < 3:
        return False
    try:
        return abs(float(placement[2])) > 1e-9
    except (TypeError, ValueError):
        return True   # an unclear offset is treated as lifting: do not promise more than warranted


def _contributions(ops: Iterable[Mapping[str, Any]],
                   level_names: dict[str, str],
                   level_names_by_id: Mapping[str, str],
                   *,
                   multiplier: int,
                   id_prefix: str,
                   rows: list[ExpectedRow],
                   blind: list[BlindOp],
                   derived: set[str],
                   family_symbols: Sequence[Mapping[str, Any]] | None,
                   open_scope: list[str],
                   forget_level: bool = False) -> None:
    """Expand a flat list of ops into expectation rows (recursing into groups).

    `forget_level` — do not attach a level to the rows. Set for group
    instances lifted vertically: exactly which level Revit will assign them
    to is NOT DERIVABLE from the program, and naming a level at random would
    mean presenting the model with an expectation we do not actually know.
    """
    for op in ops:
        name = op.get("op")
        op_id = f"{id_prefix}{op.get('id') or name}"
        ospec = spec.OPS.get(name) if isinstance(name, str) else None
        if ospec is None or not ospec.writes_model:
            continue                    # query ops do not touch the model

        # Levels declared by THIS SAME program are the only way to learn the
        # name behind a by=ref reference (this is how the stack macro
        # works).
        if name == "create_level":
            declared = op.get("name")
            own_id = op.get("id")
            if (isinstance(declared, str) and declared.strip()
                    and isinstance(own_id, str) and own_id.strip()):
                level_names[own_id.strip()] = declared.strip()

        derived.update(_OP_DERIVED.get(name, ()))

        if name in _OPS_WITHOUT_ELEMENTS:
            continue

        if name == "place_family":
            # THE MOST HEAVILY LOADED WRITING OP IN THE REGISTRY. The
            # category is taken from the model snapshot (the family_symbols
            # pool), not from the program; when the snapshot does not prove
            # it, the op stays blind WITH A NAMED REASON. Details are in the
            # module header.
            category, refusal = _family_symbol_category(op.get("symbol"),
                                                        family_symbols)
            if category is None:
                blind.append(BlindOp(
                    op_id, name, f"{_OPS_BLIND.reason(name)}: {refusal}"))
                continue
            open_scope.append(op_id)
            rows.append(ExpectedRow(
                categories=(category,),
                # There is deliberately NO level: a door and a window are the
                # same FamilyInstance, and their level is declared unknown by
                # measurement (76 of 15 569).
                level=None,
                count=multiplier,
                certainty=Certainty.AT_LEAST,
                op_ids=(op_id,),
                why=_PLACE_FAMILY_WHY,
            ))
            continue

        if name in _OPS_BLIND:
            blind.append(BlindOp(op_id, name, _OPS_BLIND.reason(name)))
            continue

        if name == "create_group":
            members = op.get("members")
            placements = op.get("placements")
            if not isinstance(members, list) or not isinstance(placements, list):
                blind.append(BlindOp(op_id, name,
                                     "members/placements не списки"))
                continue
            # 🔴 OCCUPANCY 0 AND LIFTED INSTANCES ARE NOW SEPARATED
            # (23.08.2026, bought with a live run next to a real K3).
            #
            # There used to be a single call with a `1 + len(placements)`
            # multiplier, and ALL copies were attributed to the level named
            # on the member. But Revit places them by OFFSET: a program of
            # seven walls with eleven instances produced seven walls on
            # twelve floors, and acceptance read this as "84 promised on
            # L02, 7 added" plus eleven `level_overshoot`. The KIR-A006
            # refusal was FALSE: the witness was green, the build was
            # correct, the instrument was wrong.
            #
            # WHY THE LEVEL IS FORGOTTEN RATHER THAN COMPUTED. The
            # temptation is to add the level's elevation to the offset and
            # find the nearest one. But which level an element belongs to is
            # decided by REVIT, from its own elevation table and the
            # element's kind; our own computation would be a second opinion
            # on someone else's decision and could silently diverge from
            # it — the same shape of bug that this commit fixes. It is more
            # honest not to know: a row without a level still takes part in
            # checking the TOTAL count for the category.
            flat = [m for m in members if isinstance(m, Mapping)]
            kw = dict(rows=rows, blind=blind, derived=derived,
                      family_symbols=family_symbols, open_scope=open_scope)
            _contributions(flat, dict(level_names), level_names_by_id,
                           multiplier=multiplier, id_prefix=f"{op_id}/", **kw)
            плоские = sum(1 for pl in placements if not _lifts(pl))
            поднятые = len(placements) - плоские
            if плоские:
                _contributions(flat, dict(level_names), level_names_by_id,
                               multiplier=multiplier * плоские,
                               id_prefix=f"{op_id}/", **kw)
            if поднятые:
                _contributions(flat, dict(level_names), level_names_by_id,
                               multiplier=multiplier * поднятые,
                               id_prefix=f"{op_id}/", forget_level=True, **kw)
            continue

        categories = _category_of_op(op)
        if categories is None:
            blind.append(BlindOp(
                op_id, name,
                (_OPS_BLIND.reason(name) if name in _OPS_BLIND
                 else "категория результата не выводится")))
            continue

        count, certainty, why = _plural_count(op)
        level = (_level_from_selector(op.get("level"), level_names,
                                      level_names_by_id)
                 if name in _LEVEL_FROM_PARAM and not forget_level else None)
        if certainty is Certainty.UNKNOWN:
            blind.append(BlindOp(op_id, name, why))
            continue
        rows.append(ExpectedRow(
            categories=categories,
            level=level,
            count=count * multiplier,
            certainty=certainty,
            op_ids=(op_id,),
            why=why,
        ))


def _merge_rows(rows: Sequence[ExpectedRow]) -> tuple[ExpectedRow, ...]:
    """Reduce rows to canon: one row per (categories, level, firmness).

    The order is fixed by sorting, not by the order of the ops — otherwise
    the same program would produce different signatures, and
    pre-registration would prove nothing.
    """
    merged: dict[tuple[tuple[str, ...], str | None, str], list[Any]] = {}
    for row in rows:
        key = (row.categories, row.level, row.certainty.value)
        slot = merged.setdefault(key, [0, [], ""])
        slot[0] += row.count
        slot[1].extend(row.op_ids)
        if row.why and not slot[2]:
            slot[2] = row.why
    out = [
        ExpectedRow(categories=key[0], level=key[1], count=slot[0],
                    certainty=Certainty(key[2]),
                    op_ids=tuple(sorted(slot[1])), why=slot[2])
        for key, slot in merged.items()
    ]
    out.sort(key=lambda r: (r.categories, r.level or "", r.certainty.value))
    return tuple(out)


def derive_expectation(program: Any,
                       *,
                       level_names_by_id: Mapping[Any, str] | None = None,
                       family_symbols: Sequence[Mapping[str, Any]] | None = None,
                       ) -> Expectation:
    """Derive the acceptance predicate FROM THE PROGRAM. A pure function.

    The preferred input is ``CompileOutput.planned``: then the expectation
    describes literally the same immutable plan that was lowered to C#. For
    standalone use, the same envelope that ``compile_program`` takes is also
    accepted (or a bare list): it goes through the public ``plan_program``
    exactly once.

    ``family_symbols`` — rows of the snapshot's ``family_symbols`` pool
    (obtain via :func:`symbol_rows_from_snapshot`, so that a truncated pool
    does not pass itself off as complete). If not passed — the family's
    category is not proven, and EVERY ``place_family`` honestly stays
    blind: the same principle as for the levels below — data about the
    model cannot weaken the predicate, and without it there simply is no
    predicate.

    ``level_names_by_id`` — level ``ElementId`` → its name, from the model
    snapshot's ``levels`` pool. If not passed — levels pinned by id will
    remain unknown, and acceptance honestly degenerates into checking
    totals by category. Measurement: on the rebuild of a real building (11
    programs, 2 720 ops) without the lookup, ZERO of 2 450 rows had a level
    assigned.

    Lifts nothing: a program the compiler refuses to accept yields an empty
    expectation with a recorded reason — there is nothing for acceptance to
    check, and it must say so rather than pretend success.
    """
    ops, notes = _normalise_program(program)
    by_id = {str(key): value.strip()
             for key, value in (level_names_by_id or {}).items()
             if isinstance(value, str) and value.strip()}
    rows: list[ExpectedRow] = []
    blind: list[BlindOp] = []
    derived: set[str] = set()
    level_names: dict[str, str] = {}
    open_scope: list[str] = []
    symbols = (tuple(row for row in family_symbols if isinstance(row, Mapping))
               if family_symbols is not None else None)
    _contributions(ops, level_names, by_id, multiplier=1, id_prefix="",
                   rows=rows, blind=blind, derived=derived,
                   family_symbols=symbols, open_scope=open_scope)
    return Expectation(
        rows=_merge_rows(rows),
        derived_categories=tuple(sorted(derived)),
        blind_ops=tuple(blind),
        # The resolved place_family category yields a LOWER bound, but not
        # an upper one: Revit itself creates nested shared families. By
        # lifting the upper bound here, we stay exactly where we were under
        # blindness — and do not buy catching duplicates at the price of a
        # false refusal of a correct build.
        upper_bounds_valid=not blind and not open_scope,
        op_count=len(ops),
        notes=notes + ((_PLACE_FAMILY_OPEN_NOTE,) if open_scope else ()),
    )


def expectation_digest(expectation: Expectation) -> str:
    """A short expectation signature — proof of pre-registration.

    Recorded into the receipt BEFORE the build, it makes a predicate swapped
    in after the result detectable. Without it, "the predicate was declared
    in advance" is a promise, and promises have already failed us in this
    loop.
    """
    payload = json.dumps(expectation.to_dict(), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def expectation_categories(expectation: Expectation) -> tuple[str, ...]:
    """Return the exact category universe required by an L2 live read.

    Derived categories are intentionally absent: they are documented blind
    output, never acceptance predicates.  The returned tuple is canonical so
    the live request, pre-registration record, and post-read parser can bind
    the same scope byte-for-byte.
    """

    if not isinstance(expectation, Expectation):
        raise TypeError("category scope requires a typed Expectation")
    return tuple(sorted({
        category
        for row in expectation.rows
        for category in row.categories
    }))


# ── Scope census and reconciliation ─────────────────────────────────────────
#
# THE FORMAT IS TAKEN FROM §18.1 EXACTLY AS FAR AS IT FITS, AND NO FURTHER.
# ``decompile.census.reconcile_census`` reconciles the document's census
# with the extracted one, and its key is ONE axis, BuiltInCategory
# (``CensusEntry.key``): there is no level in it, either in the record or in
# the pass that takes it
# (``FilteredElementCollector(doc).WhereElementIsNotElementType()``, one
# whole-model count). L2 is by definition two-dimensional — "category ×
# level" — so the structure of §18.1 cannot be taken wholesale: it does not
# express scope. What is taken is what does express it: the category key is
# the same BuiltInCategory string, the count is the same integer, and the
# asymmetry between shortfall and overshoot (§18.1: shortfall is a typed
# row, overshoot is an error) is inherited directly into MismatchCode. The
# second axis comes from ``L0Element.level_name``, which is read by THE
# SAME pipeline and the same BIP chain as the level in the probes.

ScopeCensus = Mapping[tuple[str, str], int]


def scope_census_from_elements(elements: Iterable[Any]) -> dict[tuple[str, str], int]:
    """Scope census from element rows: (category, level) → count.

    Accepts anything with ``category``/``level_name`` fields (L0 rows,
    probe rows, plain dicts). The level is normalized by trimming
    whitespace; its absence yields :data:`LEVEL_NONE`, not a dropped row —
    losing an element here means undercounting it in the delta and blaming
    a correct build.
    """
    counts: dict[tuple[str, str], int] = {}
    for element in elements:
        if isinstance(element, Mapping):
            category = element.get("category")
            level = element.get("level_name")
        else:
            category = getattr(element, "category", None)
            level = getattr(element, "level_name", None)
        if not isinstance(category, str) or not category:
            continue
        key = (category, level.strip() if isinstance(level, str) else LEVEL_NONE)
        counts[key] = counts.get(key, 0) + 1
    return counts


def census_delta(before: ScopeCensus, after: ScopeCensus) -> dict[tuple[str, str], int]:
    """What was added: ``after - before`` over the union of keys.

    A key that did not exist BEFORE is zero, not a gap: a category that
    first appears in the model must be counted in full.
    """
    keys = set(before) | set(after)
    return {key: int(after.get(key, 0)) - int(before.get(key, 0))
            for key in keys}


def _observed_by_level(delta: Mapping[tuple[str, str], int],
                       categories: Sequence[str]) -> dict[str, int]:
    wanted = set(categories)
    out: dict[str, int] = {}
    for (category, level), value in delta.items():
        if category in wanted:
            out[level] = out.get(level, 0) + value
    return out


def _check_total(categories: tuple[str, ...],
                 rows: Sequence[ExpectedRow],
                 observed: Mapping[str, int],
                 exact_group: bool) -> list[Mismatch]:
    """The total for a group of categories: not less than declared, and
    under full precision — also not more."""
    lower = sum(row.count for row in rows
                if row.certainty is not Certainty.UNKNOWN)
    got = sum(observed.values())
    op_ids = tuple(sorted({oid for row in rows for oid in row.op_ids}))
    names = "/".join(categories)
    if got < lower:
        return [Mismatch(
            code=MismatchCode.CATEGORY_SHORTFALL, categories=categories,
            level=None, expected=lower, observed=got, op_ids=op_ids,
            detail=(f"{names}: программа даёт {lower} элементов, "
                    f"в модели прибавилось {got}"))]
    if exact_group and got > lower:
        return [Mismatch(
            code=MismatchCode.CATEGORY_OVERSHOOT, categories=categories,
            level=None, expected=lower, observed=got, op_ids=op_ids,
            detail=(f"{names}: программа даёт ровно {lower} элементов, "
                    f"в модели прибавилось {got}"))]
    return []


def _check_levels(categories: tuple[str, ...],
                  rows: Sequence[ExpectedRow],
                  observed: Mapping[str, int],
                  exact_group: bool) -> list[Mismatch]:
    """The breakdown by level — the very reason L2 exists.

    A row with a known level gives a LOWER bound on that level: its
    elements are required to end up there. Rows without a level
    ("floating") provide a reserve that may land anywhere — and it is by
    this reserve that the upper bound of every level is widened.
    """
    located: dict[str, int] = {}
    floating = 0
    for row in rows:
        if row.certainty is Certainty.UNKNOWN:
            continue
        if row.level is None:
            floating += row.count
        else:
            located[row.level] = located.get(row.level, 0) + row.count
    if not located:
        return []
    names = "/".join(categories)
    ops_at: dict[str, tuple[str, ...]] = {}
    for row in rows:
        if row.level is not None:
            ops_at[row.level] = ops_at.get(row.level, ()) + row.op_ids
    out: list[Mismatch] = []
    for level in sorted(set(located) | set(observed)):
        need = located.get(level, 0)
        got = observed.get(level, 0)
        shown = level or "(без уровня)"
        if got < need:
            out.append(Mismatch(
                code=MismatchCode.LEVEL_SHORTFALL, categories=categories,
                level=level, expected=need, observed=got,
                op_ids=tuple(sorted(set(ops_at.get(level, ())))),
                detail=(f"{names} на уровне «{shown}»: программа даёт {need}, "
                        f"в модели прибавилось {got}")))
        elif exact_group and got > need + floating:
            out.append(Mismatch(
                code=MismatchCode.LEVEL_OVERSHOOT, categories=categories,
                level=level, expected=need + floating, observed=got,
                op_ids=tuple(sorted(set(ops_at.get(level, ())))),
                detail=(f"{names} на уровне «{shown}»: туда могло попасть не "
                        f"более {need + floating}, прибавилось {got}")))
    return out


def _merge_overlapping_groups(
    groups: Mapping[tuple[str, ...], Sequence[ExpectedRow]],
) -> list[tuple[tuple[str, ...], list[ExpectedRow]]]:
    """Merge groups sharing at least one category into ONE reconciliation.

    🔴 WHY THIS IS NOT COSMETIC BUT THE ONLY PLACE WHERE ACCEPTANCE COULD
    ACCEPT THE UNBUILT (F-094). The same category can belong to TWO groups
    at once: `create_floor` gives («OST_Floors»), while
    `create_foundation(variety=slab)` gives («OST_Floors»,
    «OST_StructuralFoundation»), because whether a slab is a floor or a
    foundation is decided by its type. As long as the groups were
    reconciled SEPARATELY, both read the SAME `OST_Floors` delta, and ONE
    observed floor satisfied TWO independent lower bounds: a program of two
    ops was accepted having built one. Measurement before the fix:
    `after={('OST_Floors','Этаж 3'): 1}` → `accepted=True,
    checked_groups=2, mismatches=[]`.

    The old code KNEW about the overlap and drew exactly one conclusion
    from it — it disabled the UPPER bound. A second conclusion was not
    drawn: from "the sum can be credited twice" it also follows that
    "not-less cannot be required PER GROUP".

    After merging, both conclusions become unnecessary: an element in the
    merged group is counted EXACTLY ONCE, so both bounds are provable
    again — the sum over the union of categories must be not less than the
    sum of the rows, and under full precision, also not more. The former
    "the upper bound is lifted on overlap" is deliberately left standing as
    wrong: it treated the symptom of double counting, not the double
    counting itself.

    Groups that overlap with no one pass through this function
    BYTE-FOR-BYTE as the same (categories, rows) pair as before.
    """
    keys = sorted(groups)
    parent: dict[tuple[str, ...], tuple[str, ...]] = {key: key for key in keys}

    def find(key: tuple[str, ...]) -> tuple[str, ...]:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    owner: dict[str, tuple[str, ...]] = {}
    for key in keys:
        for category in key:
            if category in owner:
                left, right = find(owner[category]), find(key)
                if left != right:
                    parent[max(left, right)] = min(left, right)
            else:
                owner[category] = key

    merged: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for key in keys:
        merged.setdefault(find(key), []).append(key)

    out: list[tuple[tuple[str, ...], list[ExpectedRow]]] = []
    for members in merged.values():
        categories = tuple(sorted({c for key in members for c in key}))
        rows = [row for key in members for row in groups[key]]
        out.append((categories, rows))
    out.sort(key=lambda item: item[0])
    return out


def check_acceptance(expectation: Expectation,
                     before: ScopeCensus,
                     after: ScopeCensus) -> Verdict:
    """Reconcile the expectation against a RE-READ scope census. A pure function.

    ``before``/``after`` — counters (category, level) → count, taken BEFORE
    and AFTER the build. The source must be a REPEATED READ of the model,
    not the build's receipt: the receipt says what we ASKED FOR, the census
    says what IS in the model, and the discrepancy between the two is the
    most valuable finding (this is how 30.07 exposed that rooms in every
    model never had a point). A pure function cannot tell the two apart; the
    production call must go through the strict
    ``acceptance_probe``/``acceptance_runtime``.
    """
    delta = census_delta(before, after)
    groups: dict[tuple[str, ...], list[ExpectedRow]] = {}
    if expectation.lower_bounds_valid:
        for row in expectation.rows:
            groups.setdefault(row.categories, []).append(row)

    # OVERLAPPING GROUPS ARE RECONCILED WITH ONE CHECK OVER THE UNION OF
    # CATEGORIES. The full account is in `_merge_overlapping_groups`; in
    # short: while reconciliation was done PER GROUP, one observed element
    # closed TWO independent lower bounds, and a missed operation was
    # accepted (F-094). Merging counts each element exactly once, so both
    # bounds are provable.
    #
    # THE UPPER BOUND IS STILL NOT PROVABLE EVERYWHERE, AND THIS IS NOT
    # CAUTION BUT ARITHMETIC: a stair makes its own railings, and their
    # addition would land in the railing group's count. So derived
    # categories still lift "not more" — but OVERLAP no longer lifts it,
    # because after merging there is no double counting.
    derived_set = set(expectation.derived_categories)

    mismatches: list[Mismatch] = []
    checked = 0
    upper_bound_groups: list[tuple[str, ...]] = []
    for categories, rows in _merge_overlapping_groups(groups):
        if all(row.certainty is Certainty.UNKNOWN or row.count == 0
               for row in rows):
            continue
        exact_group = (expectation.upper_bounds_valid
                       and all(row.certainty is Certainty.EXACT
                               for row in rows)
                       and not (set(categories) & derived_set))
        observed = _observed_by_level(delta, categories)
        checked += 1
        mismatches.extend(_check_total(categories, rows, observed, exact_group))
        mismatches.extend(_check_levels(categories, rows, observed, exact_group))
        if exact_group:
            upper_bound_groups.append(categories)

    named = {category for row in expectation.rows for category in row.categories}
    named.update(expectation.derived_categories)
    unexpected = sorted(
        ((category, value) for category, value in _fold_by_category(delta).items()
         if category not in named and value),
        key=lambda item: (-item[1], item[0]))

    return Verdict(
        # `accepted` is NO LONGER PASSED IN here: it is derived from these
        # same numbers and requires `checked > 0`. The former
        # `accepted=not mismatches` gave success with `checked == 0` — a
        # success with not a single check performed.
        mismatches=tuple(mismatches),
        checked_groups=checked,
        unexpected=tuple(unexpected),
        upper_bound_groups=tuple(upper_bound_groups),
        blind_ops=expectation.blind_ops,
    )


def _fold_by_category(delta: Mapping[tuple[str, str], int]) -> dict[str, int]:
    """Collapse the delta by category (level dropped) — for reference."""
    out: dict[str, int] = {}
    for (category, _level), value in delta.items():
        out[category] = out.get(category, 0) + value
    return out


__all__ = [
    "LEVEL_NONE",
    "BlindOp",
    "Certainty",
    "ExpectedRow",
    "Expectation",
    "Mismatch",
    "MismatchCode",
    "ScopeCensus",
    "VERDICT_MEASURED",
    "VERDICT_MISMATCHED",
    "VERDICT_NOTHING_TO_CHECK",
    "Verdict",
    "census_delta",
    "check_acceptance",
    "derive_expectation",
    "expectation_categories",
    "expectation_digest",
    "scope_census_from_elements",
    "symbol_rows_from_snapshot",
]
