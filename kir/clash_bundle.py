"""CLASHES IN THE BUNDLE — `kir/clash/` gets its first prod entry point.

WHAT THIS FIXES (measurement 09.08). `kir/clash/` is a mature package
(SAT/MTV, convex hull, broad phase, a closed category table, a canonical
report, six test suites), and it is DARK: not a single importer outside the
package itself, the only entry point is the manual CLI
`python -m kir.clash.tools.wall_prism_gate`. A flag that the instrument
reports "in the store" is dark BY CONSTRUCTION; here a path is built from the
chat door to the detector, not one more capability on the shelf.

WHY THE SEAM IS EXACTLY HERE — THE BUNDLE, NOT THE PROGRAM. Clash is a
RELATION BETWEEN TWO elements. Within one program a `{"by":"ref"}` reference
is legitimate, between programs it is NOT (`KIR-V002`), so two disciplines
(architectural / structural / MEP) physically cannot end up in the same
program: each performer writes their own link. The only place where the
compiler holds links from DIFFERENT authors at the same time is the session
bundle, which `live/journal.py` accumulates and `live/verdict.py` already
hands to the judge. Cutting the check into `check_ops` (a single program)
would mean building an instrument that is VACUOUS by construction for the
motivating case.

A FINDING IS EVIDENCE, NOT A VERDICT. `live/verdict.py` declares this as its
contract, verbatim: «вердикт о здании — обратная связь, а не постусловие;
сломанный судья не имеет права стоить хода, в котором Revit уже пишет». This
module inherits it wholesale: it NEVER throws, NEVER blocks, and NEVER turns
into a `Violation`. A false refusal of correct construction is the same class
of defect as `acceptance-broke-on-Cyrillic`, which rolled back sound rooms for
months; the price of a false finding here is a line in the receipt.

════════════════════════════════════════════════════════════════════════════
WHAT THE PROGRAM EXPRESSES AT ALL — AND WHY THIS IS THE MAIN FACT OF THIS MODULE
════════════════════════════════════════════════════════════════════════════

The law of `kir/clash/hulls.py` is literal: THE HULL IS REQUIRED TO CONTAIN
THE ELEMENT. Then a pair of hulls missing each other makes a missed clash
impossible, and all the coarsening goes into false positives, which are
visible and marked with a grade.

The KIR program is a DECLARATION. A measurement over the registry
(`spec.OPS`, 48 operations): NOT ONE creation operation carries wall
thickness, slab thickness, or column cross-section — they live in the TYPE.
`preview.py` independently measured exactly this: a wall carries
`ApproxReason.THICKNESS_UNKNOWN`.

WHAT THE sections WAVE CHANGED (09.08.2026). The type is resolved against the
LIVE document at the ground stage — that is, exactly where the cross-section
is knowable. The snapshot now carries it as a pool row
(`open_model.TypeSection`), and the level elevation as a row of the `levels`
pool, and both arrive here through the session journal. Before this wave, on
two real buildings the bundle gave ZERO bodies; after — 122 on
`snowdon_plumb_v5` (111 slabs by contour + 11 columns by bounding box), and
each is checked for CONTAINMENT of the real Revit bounding box
(`clash.tools.bundle_containment_gate`, 0 violations).

A hull is built for those elements whose body is determined by the program's
numbers TOGETHER WITH the geometry of its type:

  * a duct (`create_duct`, `route_duct_system`) with a declared
    `diameter_mm` — the emitter writes it into `RBS_CURVE_DIAMETER_PARAM`
    (`authoring.py:2217`), and the closed table `hulls.DIAMETER_KIND`
    classifies this parameter as `modelled`, meaning a capsule of that
    radius DOES contain the body;
  * `create_directshape` — the mesh arrives as vertices in mm;
  * SLAB, CEILING, ROOF — the program's contour + the type's thickness
    (`CompoundStructure.GetWidth`);
  * COLUMN and BEAM — the type's cross-section
    (`STRUCTURAL_SECTION_COMMON_*`) plus its own extent along Z;
  * PIPE — the declared NOMINAL size, converted to the outer dimension by
    the sizing table of the TYPE ITSELF (`PipeSegment.GetSizes`). There is no
    conversion factor here and never will be: DN100 has a nominal of 100
    against an outer dimension of 114.3, and the second cannot be derived
    from the first by anything except the table the document printed. No
    table — the nominal remains, and the refusal arrives in the words of the
    package's closed table (`section_nominal_only`).

WHAT HAS NO BODY AND WHY — THREE DIFFERENT DIAGNOSES, AND THEY ARE NAMED
DIFFERENTLY:

  * WALL. There is thickness, there is no body: the strip around the axis
    has been CHECKED on 800 real walls and violates the conservativeness law
    97 times, by up to 2854 mm outward (lengthwise — abutments, crosswise —
    the body is wider than its own `WallType.Width`). The
    `clash.tools.wall_prism_gate` lock is not open, the cause is named
    `wall_prism_refused_by_containment_gate`;
  * TRAY. The cross-section can now be declared via the `width_mm` and
    `height_mm` operands, but this layer does not get their post-commit
    readback and has no containment certificate for a rectangular hull
    around the axis. Without the full pair the cause is
    `section_not_declared`, with the pair — `geometry_not_certified`; in
    both cases no hull is built yet;
  * BOX DUCT. Neither the type nor the operation has a cross-section; a
    trade size cannot be turned into an outer dimension without the
    document's size table;
  * DOOR, WINDOW, `place_family`. The body comes from the family's
    geometry, and it is not described by a cross-section at all.

NUMBERS ARE NOT GUESSED AT. Taking "a typical 200 mm" as the wall thickness
would mean materializing a default in the frontend — exactly what the source
language's law forbids — and on top of that would make the finding NEITHER
containing NOR contained: a pipe 90 mm from the wall's axis would be accused
at a nominal of 200 and cleared at 100. Instead the element without a body
STAYS IN THE CENSUS without a hull, and the package itself prints «ПОИСК
НЕПОЛОН ПО ПОСТРОЕНИЮ» with the culprit broken down by category.

THE SEARCH SCOPE IS `all_physical_diagnostic`, AND THIS IS NAMED. The MVP
scope (`{pipe, duct, tray} × {wall, floor, column}`) is EMPTY BY CONSTRUCTION
on the program: the declaration has no `struct` side at all. The MVP scope
would always give «0 пар» — a vacuous instrument with an honest report. The
diagnostic scope is taken instead, and its name is printed in the receipt.

THE PAIR IS JUDGED BY THE RULE TABLE (the judgement wave, 09.08 evening). A
broad scope without judgement gives a report that gets thrown away: the
measurement on `snowdon_plumb_v5` — 99 pairs, of which **66 at the top
severity rung**, and all 66 are slabs of the same floor, disagreeing ONLY in
the coarsening this very module introduced. So the pairs travel to
`kir/clash_judgement.py`, and come back from there with a KIND (abutment /
pass-through-structure / collision / duplicate / not proven / no judgement), a
RUNG naming the permissible action, and a TURN derived from the program
itself. This layer does not touch the geometry of `kir/clash/`; the only new
thing this module hands it is `declaration_slack`, i.e. the NUMBER of its own
coarsening, and `op_by_id`, without which the turn can only be invented.

THE MODULE'S BOUNDARIES. Read-only. Not a single Revit call, not a single
network call, not a single write. It imports `kir.clash` and `kir.spec`; it
itself is imported only by `kir/live/verdict.py` (the path BACKWARD, same as
the verdict itself).
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from kir import env  # noqa: E402  (submodule without dependencies — creates no cycle)
from pathlib import Path as _Path
import time
from contextvars import ContextVar
from dataclasses import dataclass, replace
from dataclasses import field as dataclasses_field
from typing import Any, Iterable, Mapping, Sequence

from kir.spec import op_result_categories as _spec_op_result_categories

logger = logging.getLogger(__name__)

__all__ = (
    "BUNDLE_CLASH_SCHEMA",
    "BundleGeometry",
    "BLIND_CLASSES",
    "BLIND_CLASS_RU",
    "OP_NO_BODY",
    "REGISTRY_GAPS",
    "SECTION_PARAM_BY_OP",
    "SnapshotSections",
    "bundle_clash_report",
    "blind_class",
    "body_making_ops",
    "bundle_elements",
    "category_of",
    "op_categories",
    "FIXED_TEXT_BUDGET",
    "INTRODUCED_RULE_RU",
    "INTRODUCED_RULE_WHY",
    "clash_enabled",
    "render_bundle_clash",
)

BUNDLE_CLASH_SCHEMA = "kir-bundle-clash/1"

#: The package's search scope, chosen deliberately. See the header: the MVP
#: scope is empty by construction on the DECLARATION, because the program has
#: no `struct` side.
SCOPE = "all_physical_diagnostic"


# ═════════════════════════════════════════════════════════════════════════
# THE TURN'S DOCUMENT — WHAT OPENS THE DOOR TO THE STANDING BUILDING
#
# To compare the bundle with what already stands, we need to know WHICH
# document we are writing in. The document's identity is known in exactly one
# place — `serving`, where ground handed back `__document_fingerprint`; it
# travels here as a ContextVar, the same technique this code uses to carry
# the turn's device id (`serving._turn_device_id`) and the review's programs
# (`design.review._programs`).
#
# WHY NOT A PARAMETER THROUGH THE VERDICT. The path to here is `serving` →
# `live.verdict` → `_clash_block`; threading a parameter through would touch
# two unrelated modules for the sake of a value that belongs to the TURN, not
# the bundle. A ContextVar here is not concealment: it is declared, named,
# and cleared by the same turn that sets it.
#
# WHY NOT FROM THE SNAPSHOT. The snapshot arrives here ALREADY TRIMMED
# (`prune_ground_snapshot` leaves only pools with an elevation or a
# cross-section) — there is no document fingerprint in it. Adding it there
# would mean changing the viewer scene's `base_digest`, which is computed
# OVER THE WHOLE SNAPSHOT: someone else's cache would be silently
# invalidated for our need.
_TURN_DOCUMENT: "ContextVar[str]" = ContextVar(
    "kir_clash_turn_document", default="")


def remember_turn_document(title: str) -> None:
    """Name the document the turn is happening in. Empty — forget it."""
    _TURN_DOCUMENT.set(str(title or ""))


def _live_project_uid(snapshot: Any) -> str:
    """The `project_uid` of the open document from the ground snapshot;
    empty means none.

    Empty here means EXACTLY "we don't know", and the consumer is required
    to read this as a fact about OUR reading, not about the building: the
    snapshot may have been taken before the fingerprint wave, trimmed by
    `prune_ground_snapshot`, or not arrived at all. Absence never turns into
    "identity mismatch" — otherwise the instrument's refusal would become an
    accusation against the document.
    """
    if not isinstance(snapshot, Mapping):
        return ""
    fingerprint = snapshot.get("__document_fingerprint")
    if not isinstance(fingerprint, Mapping):
        return ""
    value = fingerprint.get("project_uid")
    return value if isinstance(value, str) else ""


def _live_revit_version(snapshot: Any) -> str:
    """The Revit version of the open document from the snapshot; empty means
    we don't know.

    The same caveat as for `_live_project_uid`: empty is a fact about OUR
    reading, not about the building, and it never turns into "version
    mismatch". The live side writes this field in `open_model.py:1986`
    (`doc.Application.VersionNumber`), the decompile in
    `passport.revit_version`. Both sides have had the value from the very
    start and it was never cross-checked once.
    """
    if not isinstance(snapshot, Mapping):
        return ""
    value = snapshot.get("__revit_version")
    return value if isinstance(value, str) else ""


def turn_document_title() -> str:
    """The turn's document header; an empty string — identity unknown."""
    try:
        return _TURN_DOCUMENT.get()
    except LookupError:      # pragma: no cover — the default is made explicit
        return ""


def clash_enabled() -> bool:
    """A switch. OFF by default, turned on deliberately.

    A switched-off flag = the behavior before this wave LETTER FOR LETTER:
    the receipt gets not one new key, `message_ru` does not change by a
    single byte. The same pattern as
    `open_model.open_model_preflight_enabled` and `KUKAI_IR_NATIVE_GROUP`.
    """

    return env.get("KIR_CLASH", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _int_env(name: str, default: int, *, low: int, high: int) -> int:
    try:
        value = int(env.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, value))


def _max_bodies() -> int:
    """The ceiling on the number of BODIES — a cheap first checkpoint
    (snapshot assembly and the grid).

    MEASUREMENT 09.08 on this box (synthetic, ducts with a declared
    diameter): a snapshot of 3 000 bodies — 91 ms, the grid — ~20 ms.
    Beyond that what costs is not the number of bodies but the number of
    PAIRS, and that is held by `_max_pairs`.
    """
    return _int_env("KIR_CLASH_MAX_BODIES", 3_000, low=16, high=50_000)


def _max_elements() -> int:
    """The ceiling on the number of ELEMENTS — and this is a DIFFERENT axis
    than the ceiling on bodies.

    WHY IT IS SEPARATE (measurement 10.08.2026, `/tmp/wiring/m_cap.py`, a
    live rebuild of `snowdon_plumb_v4` via `materialize.leaves_to_program`).
    Before this fix, a ceiling named "number of BODIES" and justified by
    "snapshot of 3 000 BODIES — 91 ms" was compared against `len(elements)`,
    that is, against THE NUMBER OF ELEMENTS, including all those with no
    hull at all. On a real rebuild this means:

        chunk  24: elements  3 081, BODIES   171 -> REFUSAL "did not look"
        chunk  30: elements  3 799, BODIES   309 -> REFUSAL
        chunk 129: elements 16 257, BODIES   905 -> REFUSAL

    That is, the refusal fired at 171 bodies against its own budget of
    3 000 — 5.7% of what it names — and the entire TAIL of the rebuild (105
    chunks out of 129) got `over_cap`. The work being refused:
    `build_from_elements` 174 ms and grid+offer estimation 11 ms on the full
    16 257 elements.

    A check labeled with one axis while reading another is not a coarse
    ceiling but a refusal WITHOUT A SUBJECT: it does not protect against
    what it names, and it fires where there is nothing to protect against.
    Therefore there are now two axes, and each measures what it is named
    for:

      * THIS ceiling holds the LINEAR cost — parsing the bundle into
        elements and attempting to build a hull for each. Measured with the
        same instrument: 7 677 elements — `bundle_elements` 103 ms +
        `build_from_elements` 77 ms; 16 257 — 643 ms + 174 ms. The default
        of 20 000 keeps the worst case around a second, that is, on the same
        order as the building-verdict budget (~0.5 s against tens of
        seconds of live writing in Revit);
      * `_max_bodies` holds the cost that actually depends on bodies, and is
        now compared against `len(snap.records)` — against BODIES.
    """
    return _int_env("KIR_CLASH_MAX_ELEMENTS", 20_000, low=16,
                    high=2_000_000)


#: TWO COSTS, AND THEY DIFFER BY TWO ORDERS OF MAGNITUDE. Measurement 09.08,
#: this box, ducts with a declared diameter, `time.perf_counter` around the
#: bundle's phases:
#:
#:   the broad phase — **4.2…5.5 μs per OFFER** (a pair encountered in a
#:   grid cell, regardless of whether it became a candidate): 12 329
#:   offers — 68 ms, 39 965 — 167 ms, 136 892 — 599 ms, 822 343 — 4 030 ms;
#:
#:   the narrow phase — **0.20…0.32 ms per CANDIDATE**: 960 candidates — 191
#:   ms, 10 000 — 3 227 ms, 25 918 — 7 917 ms.
#:
#: Hence the two ceilings: the body population predicts neither one nor the
#: other (200 non-intersecting ducts — 40 ms, 200 intersecting — 3.5 s).
_US_PER_OFFER = 4.5
_MS_PER_PAIR = 0.32


def _max_offers() -> int:
    """The ceiling on the BROAD phase, computed from an UPPER ESTIMATE that
    is free: the sum of C(k,2) over the cells of the already-built grid —
    0.01 ms on 3 000 bodies.

    The broad phase is paid for TWICE (see `_report`), so the ceiling is
    chosen so that both pass in ~1.8 s in the worst case. A measurement from
    the same wave: a plausible layout of 1 200 bodies across 8 floors gives
    136 892 offers, meaning it passes.
    """
    return _int_env("KIR_CLASH_MAX_OFFERS", 200_000, low=1_000,
                    high=50_000_000)


def _max_pairs() -> int:
    """The ceiling on the NARROW phase — by the REAL number of candidates,
    not by an estimate.

    1 500 × 0.32 ms ≈ 0.5 s — exactly the budget `live/verdict.py` has
    already chosen for the building verdict ("worst case ~0.5 s against
    tens of seconds of live writing in Revit"). A second number for the
    same question is not created.
    """
    return _int_env("KIR_CLASH_MAX_PAIRS", 1_500, low=64, high=2_000_000)


def _proposal_budget_ms() -> int:
    """The ceiling on the SECOND pass: how much time the judgement spends
    replacing the detector's raw vector with a PROVABLY minimal
    disentanglement.

    THE NUMBER IS TAKEN FROM A NEIGHBOR, NOT INVENTED. The narrow phase has
    already chosen itself ~0.5 s (`_max_pairs`), both broad ones — ~1.8 s
    (`_max_offers`); 250 ms is half of the first, and the whole pass stays
    within the worst case already accepted. A second number of the same
    kind is not created.

    WHY TIME, NOT THE NUMBER OF FINDINGS — measurement 17.08,
    `resolve.propose` on the three deepest overlaps of two saved decompiles:

        sob62_r23_v5      1 326 bodies -> 5.9 ms for three
        snowdon_plumb_v3  6 381 bodies -> 1 329.9 ms for three

    The cost grows not with the number of findings, but with the DENSITY OF
    NEIGHBORHOOD: `propose` checks whether the move would drive into a
    THIRD body. So "count to three" is a hope, not a ceiling. A budget that
    has run out IS COUNTED and travels into `Judgement.proposals`: "did not
    count" is required to be distinguishable from "nothing to count".

    `0` turns the second pass off entirely and restores the previous
    behavior byte for byte.
    """
    return _int_env("KIR_CLASH_PROPOSAL_MS", 250, low=0, high=5_000)


#: The ceiling on the receipt's text. The channel is the tool-result body;
#: the model context pays for it exactly the same way as for the building
#: verdict.
#:
#: WHY IT EXISTS AT ALL. At the previous 1 100, the findings list was
#: truncated to ZERO lines: the receipt said "there is a dispute" and
#: showed not a single one. The ceiling is held by trimming the MIDDLE —
#: the findings list is cut, not the completeness accounting.
#:
#: THE ARITHMETIC NO LONGER LIVES HERE, AND THIS IS A FIX BY MEASUREMENT.
#: This used to say "1 043 + 5×330 ≈ 2 700", and by 11.08 it was describing
#: a state that no longer existed: the non-trimmable part had grown to
#: 1 600 on a real rebuild and to 2 000 in the worst case (+53% and +92%),
#: findings were left with 2.1 judgements out of the promised five, and the
#: report printed "the judgement list was truncated". It grew SILENTLY —
#: everyone who added an honest line ate into a judgement without learning
#: about it. A number that documents a vanished state is the same kind of
#: defect as a ceiling measuring the wrong axis.
#:
#: So the arithmetic moved into `FIXED_TEXT_BUDGET` (below), where it IS
#: COMPUTED, not retold, and is locked by the test
#: `tests/test_clash_receipt_budget.py`: exceeding the budget fails the
#: test, instead of silently eating a finding. What remains here is only
#: the ceiling number itself.
#:
#: WHY IT WAS NOT RAISED TOGETHER WITH THIS WAVE. Raising it would mean
#: assigning a number instead of measuring: how much the model REALLY pays
#: for these characters, no one measured. Instead of raising it, the
#: non-trimmable part was compressed 2 000 -> 1 307 (measurement 11.08 on
#: the worst case, `tests/test_clash_receipt_budget._worst_case_pack`).
_TEXT_CAP = 2_700

#: How many findings to print in words. The rest are counted as a number.
_TOP = 5

#: THE COST OF ONE JUDGEMENT WITH A TURN. Re-measured 12.08.2026 on the
#: worst-case bundle (`_worst_case_pack`, three judgements in a row):
#: **388** characters, all three identical. The previous "250…330, measured
#: 09.08" HAD GONE STALE — the line has since been lengthened with a grade,
#: a grade tolerance, and a section ("grade conservative, grade tolerance
#: 1 mm, section mechanical"), and the cost grew by 58 characters.
#:
#: THE DERIVATION DID NOT COME APART — ITS INPUT WENT STALE, and these are
#: different repairs. The formula below has been computing correctly the
#: whole time; it was honestly propagating a stale number. So it is not
#: enough to fix the constant: it is guarded by
#: `test_the_cost_of_a_finding_is_re_measured_not_recalled`, which takes
#: the cost from the ACTUAL rendering and fails when the text outruns the
#: record again.
COST_PER_FINDING = 388

#: HOW MANY JUDGEMENTS THE TEXT GUARANTEES. Differs from `_TOP`
#: DELIBERATELY, and these are different promises: `_TOP` is how many
#: judgements will travel IN THE DATA (`findings`), while this is how many
#: will fit IN WORDS in the worst case. Before 11.08 the difference was
#: silent: five were promised, 2.1 were delivered, and no one learned of
#: it.
#:
#: 4 → 3 (12.08.2026), AND THIS IS A MEASUREMENT, NOT A CONCESSION TO THE
#: TEST. At the real cost of 388, a guarantee of four judgements is NOT
#: AFFORDABLE at this ceiling: the non-trimmable part of the worst bundle
#: takes 1307, four judgements — 1552, the sum 2859 against a `_TEXT_CAP`
#: of 2700. Three fit with room to spare: 1307 + 3×388 = 2471. The promise
#: of four was derived from the stale cost of 330
#: (2700 − 4×330 = 1380 ≥ 1307 — the arithmetic worked out, the delivery
#: did not), meaning it was authored by reasoning, not measured.
#:
#: IT CAN BE RAISED BACK BY TWO HONEST MOVES, and both require a
#: measurement, not a fix to this line: compress a judgement below 348
#: characters, or bring justification for raising `_TEXT_CAP` (it has its
#: own transport meaning).
GUARANTEED_FINDINGS = 3

#: THE BUDGET OF THE NON-TRIMMABLE PART — not assigned, but DERIVED from
#: the two numbers above. By formula, not by literal, so the budget cannot
#: diverge from its own arithmetic: raise the guarantee — the budget
#: shrinks on its own.
FIXED_TEXT_BUDGET = _TEXT_CAP - GUARANTEED_FINDINGS * COST_PER_FINDING


# ═════════════════════════════════════════════════════════════════════════
# 1. A CLOSED TABLE: EVERY REGISTRY OPERATION LEAVES HERE WITH ONE OUTCOME
#
# The same law as `hulls.KIND_TABLE`: not a single operation can silently
# fall through. Completeness is held by a test against `spec.OPS`, not by
# attentiveness — otherwise a new operation would add bodies to the
# building that are invisible to the search, and the report would remain
# "sound".
# ═════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════
# 1b. WHY AN ELEMENT HAS NO BODY — FIVE DIFFERENT FACTS, AND THEY ARE FIXED
#     IN FIVE DIFFERENT PLACES
#
# MEASUREMENT 11.08.2026 (`/tmp/wiring/m_blind.py`, `/tmp/wiring/m_cover.py`),
# a live rebuild via `materialize.leaves_to_program`:
#
#     sob62_r23_v5      902 elements: bodies WITHOUT a type snapshot 3, WITH one 18
#     snowdon_plumb_v4  16 257 elements: bodies WITHOUT a snapshot 905, WITH one 16 247
#
# That is, coverage at the rebuild's door is decided NOT by the wiring, but
# by the presence of the open-model snapshot, and it does arrive there:
# `remember_sections` stands in the SHARED body of both doors, `clash_only`
# reads `entry.sections`.
#
# The remaining blindness is five different facts, and a flat list of
# reasons was merging them. The reader could not tell "we did not ask"
# apart from "there is no one to ask", and these call for different next
# actions: one is fixed by the author with an operand, another by ground, a
# third is not fixed here at all.
BLIND_CLASS_RU: dict[str, str] = {
    "never_a_body": (
        "тела не создаёт вовсе: операция — датум, аннотация, помещение, правка "
        "чужого элемента. В поиск не входит по построению"),
    "op_expresses_no_body": (
        "тело у СЕМЕЙСТВА: операция физический элемент создаёт, но тело "
        "приходит из "
        "СЕМЕЙСТВА или эскиза, а операция их не несёт (дверь, окно, "
        "лестница). Числа тут неоткуда взять — ни у программы, ни у типа"),
    "not_declared_by_program": (
        "автор не объявил: программа не назвала число, которым тело строится — нет оси, нет "
        "контура, нет сечения, не назван тип. Чинит АВТОР — операндом"),
    "needs_live_model": (
        "знает живой документ: число живёт в ТИПЕ или в отметке уровня. Чинится снимком стадии ground, а не программой"),
    "refused_by_hull_gate": (
        "отказал замок оболочек: числа есть, но строить по ним отказывается "
        "`kir/clash` — "
        "его замок содержания. Чинится ТАМ и не здесь"),
}

#: Cause -> class. There is deliberately NO default: a new cause not
#: assigned to any class is required to be caught by a test, not to end up
#: in the report unnamed (`tests/test_clash_coverage.py`).
BLIND_CLASSES: dict[str, str] = {
    # ── the author did not declare
    "axis_missing": "not_declared_by_program",
    "wall_axis_missing": "not_declared_by_program",
    "wall_top_unbound": "not_declared_by_program",
    "wall_type_not_declared": "not_declared_by_program",
    "beam_axis_missing": "not_declared_by_program",
    "column_xy_missing": "not_declared_by_program",
    "column_top_unbound": "not_declared_by_program",
    "pipe_diameter_not_declared": "not_declared_by_program",
    "pipe_type_not_declared": "not_declared_by_program",
    "slab_contour_is_a_region": "not_declared_by_program",
    "slab_contour_not_readable": "not_declared_by_program",
    "create_cable_tray_section_not_declared": "not_declared_by_program",
    "directshape_mesh_unreadable": "not_declared_by_program",
    # ══════════════════════════════════════════════════════════════════════
    # THE CLOSEDNESS WAVE 21.08.2026: SEVENTEEN CAUSES WITHOUT A CLASS. The
    # law `EveryBlindnessReasonIsClassified` was red, and not one of the
    # causes arrived with today's fix — all of them are literals from
    # earlier waves (roof, railing, rotation, stair, flexible runs,
    # foundation, solid). While there is no class, the report prints the
    # cause UNNAMED, and an unnamed class reads as "unclear", that is, as
    # the absence of a problem.
    #
    # Each one's class is chosen by ONE question: WHO FIXES IT. The author
    # with an operand, the ground-stage snapshot, or someone else's lock.
    #
    # ── THE AUTHOR DID NOT DECLARE A NUMBER (fixed with an operand) ───────
    "solid_height_missing": "not_declared_by_program",
    "revolve_sweep_missing": "not_declared_by_program",
    "revolve_axis_missing": "not_declared_by_program",
    # A revolve profile crossed over the axis: the numbers ARE NAMED, but
    # named illegitimately — a body cannot be bounded around an empty axis.
    # This too is fixed by the author, and also with an operand, so the
    # class is the same, not "the lock refused".
    "revolve_profile_crosses_axis": "not_declared_by_program",
    "roof_profile_missing": "not_declared_by_program",
    "roof_plane_trace_missing": "not_declared_by_program",
    # The work-plane trace is declared with zero length — the same as an
    # absence: no extrusion direction can be taken from it.
    "roof_plane_trace_degenerate": "not_declared_by_program",
    "roof_extrusion_extent_missing": "not_declared_by_program",
    "railing_path_missing": "not_declared_by_program",
    "stairs_run_path_missing": "not_declared_by_program",
    "stairs_width_not_declared": "not_declared_by_program",
    "flex_path_missing": "not_declared_by_program",
    # ── THE BODY BELONGS TO THE FAMILY OR TO THE SKETCH, THE OPERATION
    #    DOES NOT CARRY IT ──────────────────────────────────────────────
    # An isolated foundation: the bounding box lives in the SYMBOL, and the
    # branch honestly does not try — for the slab-type one the same
    # operation goes into `_slab_geometry`.
    "foundation_isolated_symbol_extent_not_expressed": "op_expresses_no_body",
    # A spiral stair run: `spiral` describes the path, not the body's
    # bounding box.
    "stairs_spiral_extent_not_expressed": "op_expresses_no_body",
    # A railing NOT along a path (hosted): the body follows a host that the
    # bundle has not resolved into geometry at this stage.
    "railing_variety_not_path": "op_expresses_no_body",
    # 🔴 A SPLINE IN THE CONTOUR: the bounding box from it is a LOWER
    # ESTIMATE, and `region_bbox` says so in its own docstring. The class is
    # specifically "does not express the body": the body DOES EXIST, but it
    # is not described by a BOX, and an undersized box hides a clash
    # silently — quieter than a refusal, and so worse.
    "region_has_spline": "op_expresses_no_body",
    # ── THE NUMBER LIVES IN THE TYPE, A SNAPSHOT IS NEEDED ─────────────
    "railing_type_not_in_snapshot": "needs_live_model",
    "railing_type_height_absent": "needs_live_model",
    # ── only the live document knows
    "no_snapshot": "needs_live_model",
    "level_elevation_unknown": "needs_live_model",
    "wall_type_not_in_snapshot": "needs_live_model",
    "wall_type_section_not_a_plate": "needs_live_model",
    "wall_type_thickness_absent": "needs_live_model",
    "slab_type_not_in_snapshot": "needs_live_model",
    "slab_type_section_not_a_plate": "needs_live_model",
    "slab_type_thickness_absent": "needs_live_model",
    "symbol_not_in_snapshot": "needs_live_model",
    "symbol_has_no_structural_section": "needs_live_model",
    "symbol_local_extent_unknown": "needs_live_model",
    "pipe_type_not_in_snapshot": "needs_live_model",
    "pipe_type_has_no_size_table": "needs_live_model",
    "pipe_nominal_not_in_type_table": "needs_live_model",
    # ── refusal of someone else's containment lock
    "wall_prism_refused_by_containment_gate": "refused_by_hull_gate",
    "wall_arc_not_a_segment": "refused_by_hull_gate",
    "slab_sloped_not_a_plate": "refused_by_hull_gate",
    "create_cable_tray_geometry_not_certified": "refused_by_hull_gate",
    "create_conduit_section_not_expressible": "refused_by_hull_gate",
}

#: Causes assembled from the OPERATION NAME: they cannot be listed by name,
#: the registry grows. Suffix -> class; checked after an exact match.
_BLIND_SUFFIX: tuple[tuple[str, str], ...] = (
    ("_geometry_not_expressed", "op_expresses_no_body"),
    ("_graph_has_no_readable_segment", "not_declared_by_program"),
)


def blind_class(reason: str) -> str:
    """A bodilessness cause -> its CLASS, or empty.

    THE LOCK'S BOUNDARY, AND IT IS WRITTEN IN WORDS, BECAUSE A SILENT LOCK
    IS WORSE THAN A MISSING ONE. The test `test_clash_coverage` catches
    unclassified causes by REGEX over this module's source, and it catches
    exactly two forms: a string literal in `blame("...")` and in
    `return "..."`. A cause assembled by CONCATENATION or arriving from a
    foreign module will slip past it.

    That is why dynamic causes are allowed here in exactly one form —
    `f"{op_name}<suffix>"` with a suffix from `_BLIND_SUFFIX` — and this is
    not a style choice but a condition of the lock's operation: any other
    way of assembling a name is required either to get its own suffix here,
    or to be written out as a literal. As long as this rule holds, "empty"
    means a hole in the table, not a hole in the check.

    Empty means "the cause is not classified", and that is an ERROR the
    test catches, not a working value: an unnamed class in the report is
    indistinguishable from the absence of a problem — exactly what this
    module has been curing since its first wave.
    """
    known = BLIND_CLASSES.get(reason)
    if known is not None:
        return known
    for suffix, name in _BLIND_SUFFIX:
        if reason.endswith(suffix):
            return name
    return ""


#: An operation creates a PHYSICAL element -> its Revit category (a key of
#: `hulls.KIND_TABLE`). A hull is built for it ONLY from the numbers of the
#: program itself; where there are no numbers, the element stays in the
#: census without a hull — and this is NAMED. THE REGISTRY IS THE ONLY
#: SOURCE OF CATEGORY. It is read as a function, not copied as a table: a
#: copy would drift, and it already has (see below).
_REGISTRY_CATEGORIES = _spec_op_result_categories

#: ROWS THE REGISTRY DOES NOT HAVE, OR DOES NOT DECIDE — AND WHY. This is
#: NOT a second table of the same relation: the registry answers "which
#: categories does the op create in Revit", and here exactly what it does
#: not answer is appended, with a cause for each row. It empties out as the
#: registry takes them over.
#:
#: MEASUREMENT 11.08.2026 (`/tmp/wiring/m_tables.py`), 29 of my rows against
#: 44 of the registry's. Two tables of the same relation have ALREADY
#: diverged:
#:   * `create_railing` — mine says `OST_StairsRailing`, the registry says
#:     `("OST_Railings", "OST_StairsRailing")`: a railing can also stand
#:     freestanding, and my row named the category Revit did not create at
#:     that time. `hulls.KIND_TABLE` knows only the second one, so the
#:     intersection decides it unambiguously and there is no more guessing;
#:   * `create_face_wall` the registry knows (`OST_Walls`), and I did not
#:     know it AT ALL — a wall by mass face was not entering the search
#:     with a single body;
#:   * `create_foundation` variety=slab the registry honestly gives out two
#:     categories: whether it is a slab or a foundation slab is decided by
#:     the TYPE, which the compiler does not see.
REGISTRY_GAPS: dict[str, str] = {
    # The registry is silent: there is no row at all in
    # `OP_RESULT_CATEGORIES`.
    #
    # REMOVED 11.08.2026: `create_curtain_grid_line` -> `OST_CurtainGridsWall`.
    # The row declared an ANSWER that `category_of` never actually returned:
    # the last word here belongs to `hulls.KIND_TABLE`, and it sets
    # `eligible=False` for this category. Measurement:
    # `category_of({"op": "create_curtain_grid_line"})` returned `None`
    # both before the fix and after — meaning the row did not work, but
    # READ as working, and a test was already relying on it
    # (`test_clash_coverage`, red on a clean HEAD). The operation moved to
    # `OP_NO_BODY` with a named cause.
    "create_wall_foundation": "OST_StructuralFoundation",
    # The registry gives out TWO categories, and `hulls.KIND_TABLE` knows
    # both. The choice is named here, not made silently: `Floor.Create` with
    # a type from the foundation pool remains a foundation, and that is
    # closer to the author's declaration than a slab. The row will disappear
    # once the registry learns to decide by type.
    "create_foundation": "OST_StructuralFoundation",
}

#: A census key that is NOT a Revit category. The registry returns it as
#: the second key for `DirectShape` deliberately (the census §18.1 keys it
#: both ways), but `hulls.KIND_TABLE` is keyed by category, and
#: substituting a literal here would mean judging the body by the rule of
#: the wrong thing.
_CENSUS_ONLY_KEYS = frozenset({"DirectShape"})

#: The operation does not create a body — and WHY. The cause travels into
#: the receipt: a blind spot that is not spoken of reads as the absence of
#: a blind spot.
OP_NO_BODY: dict[str, str] = {
    "create_level": "датум: уровень — отметка, а не тело",
    "create_grid": "датум: ось — разбивка, а не тело",
    # MERGE 09.08, the datums wave: the precedent of `create_grid` verbatim —
    # a chain of grid lines is the same layout, only a polyline.
    "create_multi_segment_grid": "датум: цепь осей — разбивка, а не тело",
    # 🔴 FOUND 21.08.2026 BY THE CLOSEDNESS LAW, AND THIS IS A PLAIN MISS OF
    # THE 20.08 WAVE. `query_surface` is the ONLY one of the registry's five
    # queries that was not standing here: `query_count`, `query_inspect`,
    # `query_list`, and `query_types` were declared as reads from the very
    # start. The `query` family, effect `READ` — the op builds nothing and
    # has nothing to hide. While the row was missing, `body_making_ops()`
    # counted a READ as an operation with a body and demanded a hull from
    # it.
    "query_surface": "чтение",
    # 🔴 FOUND 07.09.2026 BY THE SAME LAW, AND THIS IS THE THIRD CASE OF ONE
    # KIND. `query_element_state` is the registry's sixth read, and it had
    # never stood here. The complement (`body_making_ops` = registry − this
    # table) declared a READ an operation with a body, and the closedness
    # law (`tests/test_clash_in_the_receipt.py::TheTableIsClosed`) was RED
    # on HEAD `f1e394e`: a read has no category, the table has no name for
    # it, the op fell out of both outcomes.
    #
    # WHY MEMORY DOES NOT CURE THIS. This is already the third one to fall
    # through: `create_space` and `create_curtain_grid_line` (11.08),
    # `query_surface` (21.08). The complement cannot tell "the cause was not
    # named" apart from "there is a body" — it silently counts as the
    # second any name that is not here. That is why on 07.09 a REGISTRY
    # VETO was set up: a reading operation gives no body BY CONSTRUCTION,
    # and this is asked of `spec.OPS`, not recalled from memory
    # (`tests/test_the_registry_owns_every_capability.py::TheRegistryHasAVeto`).
    "query_element_state": "чтение",
    # 🔴 ЧЕТВЁРТЫЙ ЧИТАЮЩИЙ ОП, И ВЕТО ЕГО ПОЙМАЛО (13.09.2026). `query_level_plan`
    # добавлен волной фона листа; строки здесь не было, и `body_making_ops()`
    # (дополнение до реестра) молча объявил ЧТЕНИЕ операцией с телом. Отличие от
    # трёх прежних случаев — в том, что на этот раз никто ничего не вспоминал:
    # вето `TheRegistryHasAVeto::test_a_reading_op_makes_no_body`, заведённое
    # 07.09 ровно для этого, покраснело в том же прогоне, где оп появился, и
    # назвало и причину, и имя. Именно так этот класс и должен кончаться.
    "query_level_plan": "чтение",
    "create_room": "помещение — ОБЪЁМ, а не тело (так же решает hulls.KIND_TABLE)",
    "create_room_separator": "линия разделения — датум, а не тело",
    # ── TWO OPERATIONS FOUND BY THE CLOSEDNESS LAW WHEN IT WAS REVIVED
    # (11.08.2026). Neither stood here nor in `category_of`'s answer,
    # meaning they fell out of the closed table SILENTLY — exactly what the
    # law is meant to catch. There was nothing to catch them with: the
    # guard read the removed `OP_CATEGORY` and crashed on an
    # `AttributeError` before the first check.
    #
    # The decision is made by the precedent of `create_room`, not from
    # scratch: for both the category IS KNOWN, and `hulls.KIND_TABLE` knows
    # both — and sets `eligible=False` for both (measurement 11.08:
    # `OST_MEPSpaces` False, `OST_CurtainGridsWall` False). A category the
    # closed table refuses a body to is `no_body` with ITS OWN NAME, not a
    # gap: that has already been decided for the room.
    "create_space": "пространство — ОБЪЁМ, а не тело (OST_MEPSpaces у "
                    "hulls.KIND_TABLE eligible=False, как и помещение)",
    "create_curtain_grid_line": "линия разрезки ДЕЛИТ ячейки витража, своего "
                                "тела у неё нет (OST_CurtainGridsWall у "
                                "hulls.KIND_TABLE eligible=False)",
    "create_opening": "проём — ПУСТОТА в хозяине, а не тело",
    # GEOMETRY JOIN (18.08.2026). Not "there is no body because it's a
    # datum" and not "a volume instead of a body" — a third cause not yet
    # in this table: the op ADDS NOTHING to the building. Both bodies
    # already stand, other ops built them, and each is already accounted
    # for by the search under its own category. The join only changes how
    # Revit cuts their shared volume.
    #
    # 🔴 AND THIS IS NOT HARMLESS FOR CLASH, WHICH IS WORTH SAYING OUT
    # LOUD: after the join, a pair that BEFORE it was honestly counted as
    # an overlap remains an overlap in the geometry too — the join does not
    # separate the bodies, it declares their joint legitimate. Telling
    # "intersected by mistake" apart from "joined on purpose" is something
    # this table cannot and should not do: that is a question for the
    # pair's judgement (`clash_judgement`), not for whether the op has a
    # body.
    "join_elements": "соединение — ОТНОШЕНИЕ двух уже стоящих тел; оп не "
                     "добавляет зданию ни одного нового",
    "create_group": "группа: тела её членов размножены размещениями — "
                    "программа не выражает результат раскладки",
    # MERGE 09.08, the datums wave. The precedent of `create_group`, not of
    # datums: REAL bodies will appear (a run on every named level with its
    # own brood of steps and landings), but how many and where is decided
    # by `ConnectLevels`, and the program carries only a LIST OF LEVELS.
    # That is why the op also travels into `_BLIND_OPS` below: its absence
    # from the search can hide a real collision, and that is exactly the
    # definition of that dictionary.
    "create_multistory_stairs": "многоэтажная лестница: марш на каждый "
                                "уровень порождает ConnectLevels — программа "
                                "не выражает результат раскладки",
    # ── MERGE 09.08: six operations from two waves, arriving AFTER this
    # table was closed. The table is exactly the lock that caught them: not
    # one got a default category, the test demanded a decision for each.
    # The decisions are made by the precedents ALREADY STANDING here, not
    # from scratch.
    #
    # Framing (rebar cage) — the precedent of `create_group` verbatim:
    # bodies exist, but their LAYOUT is not chosen by the program. This is
    # not a brush-off but the same blind spot, and it travels into
    # `_BLIND_OPS` below, because real bodies will indeed appear in the
    # model.
    "create_beam_system": "балочная система: число и шаг балок выбирает "
                          "LayoutRule — программа не выражает результат "
                          "раскладки (тот же случай, что у create_group)",
    "create_truss": "ферма: пояса и раскосы приходят из СЕМЕЙСТВА, их "
                    "габарита программа не несёт (тот же случай, что у "
                    "place_family)",
    # Loads and the egress path — the precedent of datums and annotations:
    # there is no object with a body here at all, so they do NOT travel
    # into `_BLIND_OPS` (see the header of that dictionary: printing them
    # every turn would mean paying context for news that isn't there).
    "create_point_load": "нагрузка — РАСЧЁТНЫЙ объект, а не тело",
    "create_line_load": "нагрузка — РАСЧЁТНЫЙ объект, а не тело",
    "create_area_load": "нагрузка — РАСЧЁТНЫЙ объект, а не тело",
    "create_path_of_travel": "путь эвакуации — линия расчёта, а не тело",
    # ── PAD/SITE: the one place in this table where the cause "no body"
    # would be UNTRUE, and so a different one is written. Terrain and the
    # building pad DO have a body, and a pipe passing through the ground is
    # a real collision. But there is NOTHING to build a hull from: the
    # closed table `hulls.KIND_TABLE` knows neither OST_Topography, nor
    # OST_Toposolid, nor OST_BuildingPad (checked by search at the 09.08
    # merge — NOT A SINGLE match). Declaring them a category would mean
    # promising a hull nobody will build: the element would silently slip
    # into `kind_outside_table`, and the report would remain "sound". An
    # instrument that answers for part of the range is more dangerous than
    # a silent one, so ABSENCE is named here, and both operations travel
    # into `_BLIND_OPS`. WHAT THIS DOES NOT MEAN: this is not a decision
    # that "terrain is not subject to collisions". The hull rule for
    # ground is a geometry measurement, not a resolution of the merge
    # conflict, and it is DELIBERATELY not made here.
    "create_topography": "тело есть, но оболочку строить нечем — рельефа нет "
                         "в закрытой таблице hulls.KIND_TABLE",
    "create_building_pad": "тело есть, но оболочку строить нечем — площадки "
                           "нет в закрытой таблице hulls.KIND_TABLE",
    "create_site_subregion": "подобласть — ОКРАСКА поверхности рельефа, а не "
                             "тело: своего объёма у неё нет",
    # The curtain-profile wave (09.08): THE SAME CASE AS THE PAD, checked
    # the same way — `hulls.KIND_TABLE` (61 rows) has neither OST_Cornices,
    # nor OST_Reveals, nor OST_EdgeSlab. The body of a cornice or a drip
    # edge is real, and a pipe passing through a cornice is a real
    # collision; so ABSENCE of a hull is named here, and both operations
    # travel into `_BLIND_OPS`. Declaring them a category would mean
    # promising a hull nobody will build.
    "create_wall_sweep": "тело есть, но оболочку строить нечем — карнизов и "
                         "рустов нет в закрытой таблице hulls.KIND_TABLE",
    "create_slab_edge": "тело есть, но оболочку строить нечем — краевого "
                        "профиля нет в закрытой таблице hulls.KIND_TABLE",
    # The masses wave: the body of a wall-by-face is real, but there is
    # nothing to build a hull from. The cause is NAMED, not "missing from
    # the table by oversight": a wall's hull is built from `LocationCurve`
    # and thickness, and `FaceWall` is NOT a `Wall` (measured, CS0029 on
    # all six) and has no `LocationCurve` at all. Declaring it category
    # OST_Walls would mean promising the search a hull it would build from
    # an axis that doesn't exist.
    "create_face_wall": "тело есть, но оболочку строить нечем — FaceWall не "
                        "Wall и LocationCurve не имеет",
    # A landing — a real body, but the closed table
    # `clash.hulls.KIND_TABLE` does not know `OST_StairsLandings`.
    # Assigning it a category here would mean promising a hull
    # the search does not build.
    "create_stairs_landing": "тело есть, но оболочку строить нечем — "
                             "OST_StairsLandings нет в закрытой "
                             "таблице clash.hulls.KIND_TABLE",
    # THE SECOND RUN — the same cause word for word, and this is NOT a copy
    # for symmetry's sake: `OST_StairsRuns` is missing from `KIND_TABLE`
    # exactly like `OST_StairsLandings`. A run has a body (it is a real
    # solid), but the search does not build a hull for it, and promising
    # one with a category would mean expecting from the bundle a body that
    # will not be there.
    "create_stairs_run": "тело есть, но оболочку строить нечем — "
                         "OST_StairsRuns нет в закрытой "
                         "таблице clash.hulls.KIND_TABLE",
    "create_type": "создаёт ТИП, а не элемент",
    "load_family": "загружает семейство, а не элемент",
    "place_family": "тело зависит от семейства; габарит символа программа "
                    "не выражает",
    # 🔴 TWO OPS UNDER THE SAME PRECEDENT (21.08.2026), found by the
    # closedness law. Both place an instance of a LOADABLE family, and the
    # body for both lives in the `.rfa`: the program does not express it
    # and cannot express it. `author_family` additionally draws this very
    # family itself — but draws it inside a DIFFERENT document, in the
    # template's coordinates, and hands out an instance whose bounding box
    # is decided by the insertion point and the template itself.
    #
    # The precedent is taken from `place_family` verbatim, not derived
    # again: all three share the same argument and the same outcome.
    "author_family": "авторское семейство: тело живёт в .rfa, наружу идёт "
                     "экземпляр, чей габарит программа не выражает",
    "create_adaptive_component": "адаптивный компонент: форму решают точки "
                                 "размещения внутри семейства, программа "
                                 "габарита не выражает",
    "create_dimension": "аннотация",
    "create_angular_dimension": "аннотация",
    "create_tag": "аннотация",
    "create_text": "аннотация",
    # A filled region — 2D graphics ON THE VIEW, not a body: it has
    # neither volume nor a position in the model at all (its points are
    # offsets from View.Origin). It therefore does NOT travel into
    # `_BLIND_OPS`: there is nothing to hide.
    "create_filled_region": "аннотация: 2D-заливка вида, тела в модели нет",
    # The reinforcement wave (10.08): the bodies are real (bars), but their
    # LAYOUT is not chosen by the program — the precedent of
    # `create_beam_system` verbatim. Moreover, they may not exist at all:
    # with HostStructuralRebar turned off Revit creates not a single bar
    # (documented by Autodesk). So ABSENCE of a bounding box is named here,
    # and the operation itself travels into `_BLIND_OPS` below: rebar in a
    # slab is a real body capable of hiding a collision.
    "create_area_reinforcement": "армирование: стержни кладёт Revit по типу "
                                 "армирования, их габарита программа не несёт",
    "set_param": "правит СУЩЕСТВУЮЩИЙ элемент — его геометрии в программе нет",
    "change_type": "правит СУЩЕСТВУЮЩИЙ элемент — смена типа меняет тело, "
                   "а нового габарита программа не несёт",
    "set_curtain_panel": "правит СУЩЕСТВУЮЩУЮ панель витража — новое тело "
                         "приходит из типа, а его в программе нет",
    "move_elements": "ДВИГАЕТ существующие элементы: и старого, и нового "
                     "положения тела в программе нет — клеш, созданный "
                     "переносом, этой проверке НЕ виден",
    "delete": "удаляет существующие элементы",
    "query_count": "чтение",
    "query_inspect": "чтение",
    "query_list": "чтение",
    "query_types": "чтение",
    # ── FOUR CATALOG OPS, CLOSED 24.08.2026 BY THE CLOSEDNESS LAW ─────────
    #
    # Three of them (`create_wall_type`, `transfer_family`,
    # `create_floor_plan`) arrived on 23.08 and stood outside the table for
    # a day: the law was red, and with it NINE neighboring checks of this
    # same file were red, because each one assembles a receipt. The fourth
    # (`transfer_material`) is mine, 24.08, and it is closed in the same
    # turn so the debt does not grow.
    #
    # The cause is the same for all of them and it is NOT "a datum" and
    # not "a volume": it is the precedent of `join_elements` — THE OP ADDS
    # NOT A SINGLE BODY TO THE BUILDING. A catalog places into the
    # document a DESCRIPTION of future bodies; bodies will appear when the
    # author places a wall, a slab, or a family instance, and there they
    # are already accounted for under their own categories. Declaring them
    # a category would mean promising the search a body that does not
    # exist in the model at all.
    "create_wall_type": "тип — ОПИСАНИЕ будущих тел, а не тело: стену строит "
                        "create_wall, и там она уже учтена (тот же случай, "
                        "что у join_elements — оп не добавляет зданию ничего)",
    "transfer_family": "семейство и его типоразмер — КАТАЛОГ: тело появляется "
                       "при place_family/create_door/create_window, где и "
                       "учитывается",
    "transfer_material": "материал — СВОЙСТВО тела, а не тело: он приезжает "
                         "элементом библиотеки, и ни одного нового тела в "
                         "здании после переноса нет",
    "create_floor_plan": "вид — способ СМОТРЕТЬ на здание; ни одного тела он "
                         "не добавляет (прецедент датумов: объекта с телом "
                         "здесь нет вовсе, поэтому и в _BLIND_OPS не едет)",
}

#: Operations whose absence from the search can HIDE a real collision, and
#: a short phrase for the receipt. Datums, annotations, and reads are
#: deliberately not included here: they neither move nor create bodies,
#: and printing them every turn would mean paying context for news that
#: isn't there.
#: Bodies declared by the program IN FULL: they resolve neither a level
#: nor a type (`grounded` is empty for both), so their bounding box does
#: not depend on the snapshot at all.
_SOLID_OPS = frozenset({"create_solid_extrusion", "create_solid_revolve"})

#: Flexible runs: a declared 3D polyline plus the cross-section radius of
#: the TYPE.
_FLEX_OPS = frozenset({"create_flex_duct", "create_flex_pipe"})

_BLIND_OPS: dict[str, str] = {
    # ══════════════════════════════════════════════════════════════════════
    # THE CLOSEDNESS WAVE 21.08.2026. The law
    # `EveryBodyMakingOpIsAnsweredFor` was RED FOR TWO DAYS, and this is not
    # the tail of a single fix: of seven unanswered ops, SIX arrived with
    # the solids-and-surfaces wave of 20.08 (measured by `git log -S` over
    # the registries: 11b6f87f, 6961bb94, 0d3aa772, 5b03cebe), and the
    # seventh with family authoring on 21.08 (ea65f9fd). All this time
    # their bodies had NEITHER A BRANCH NOR DECLARED BLINDNESS — that is, a
    # third, silent basket, exactly the closedness this law was written
    # against.
    #
    # 🔴 WHY BLINDNESS, NOT A BRANCH, AND HOW THIS DIFFERS FROM A RETREAT.
    # The row here does NOT SILENCE, it makes LOUDER: the report prints
    # «ВНЕ ПРОВЕРКИ, И ЭТО МОЖЕТ ПРЯТАТЬ КОЛЛИЗИЮ» specifically FROM THIS
    # DICTIONARY, while the silent basket printed nothing at all. The
    # precedent is verbatim — the 19.08 wave gave a branch to eight ops out
    # of twelve, and wrote a cause for three.
    #
    # 🔴 FOR FOUR OF THE SIX THE BOUNDING BOX IS DERIVABLE, AND THIS IS A
    # DEBT WITH AN ADDRESS, NOT A VERDICT. It is deliberately not written
    # here: a branch requires the emitter's arithmetic (`solid_emit`), not
    # a guess, and "a hull made of defaults is worse than a missing one"
    # is the law of this file. The address of each branch is named in its
    # row below, so the next wave does not have to search.
    "author_family": "создаёт СЕМЕЙСТВО и ставит его экземпляр; тело живёт в "
                     ".rfa, которого на этой стадии ещё нет — вывести габарит "
                     "не из чего",
    "create_adaptive_component": "ставит адаптивный компонент по точкам; тело "
                                 "приходит из СЕМЕЙСТВА и подстраивается под "
                                 "них, поэтому сами точки дают нижнюю оценку, "
                                 "а не габарит",
    # 🔴 THIS RECIPE WAS TESTED BY EXECUTION ON 06.09.2026 AND FAILED. A
    # branch was written VERBATIM to it (union of the two profiles'
    # bounding boxes over [base_z, base_z+height]) and removed the same
    # evening. Two reasons, both with a number.
    #   THE FIRST, SUBSTANTIVE ONE. The op's own specification
    #   (`kir/ops_solid.py`, `create_solid_blend`) says: the lateral
    #   surface is built by Revit ITSELF according to an UNDOCUMENTED
    #   smoothing rule, and PRECISELY because of that the volume is not on
    #   the list of the proven. So a union of the sections' bounding boxes
    #   is not an upper estimate but a guess: the smooth side is entitled
    #   to bulge outward. For the BROAD phase this is an error in the
    #   direction of a MISS, that is, exactly the "silence reads as no
    #   collisions" that this file calls the most expensive lie. Compare
    #   the neighboring row for `create_surface`: there it says "DERIVED
    #   AND PROVEN" and names the argument (the network's convex hull).
    #   Here there is no proof — only "DERIVED".
    #   THE SECOND, MEASURED ONE. The `kir/viewer/tests` strip on frozen
    #   copies differing by EXACTLY this branch: with the branch, 18
    #   failures, without it, 0. The viewer built an entire workaround (an
    #   approximate proxy from the profile) precisely because the blend
    #   has NO body, and the branch was silently taking away its subject.
    #   WHAT INSTEAD. For a project's SAVED body the real shape already
    #   exists — `kir/clash/project_analysis.py` reads the BRep from the
    #   store, and the exact phase judges by it. A guess from profiles is
    #   not needed where the body is lying. The branch will become
    #   legitimate exactly when a PROVEN bound on Revit's smoothing
    #   appears, and not before.
    "create_solid_blend": "тело между двумя профилями; ВЫВОДИМ — объединение "
                          "габаритов profile и profile_top по [base_z, "
                          "base_z+height], ветке нужна та же арифметика, что "
                          "у _solid_geometry",
    "create_solid_boolean": "булева над parts; ВЫВОДИМА консервативная "
                            "оценка — объединение операндов для union, ПЕРВЫЙ "
                            "операнд для difference, пересечение габаритов "
                            "для intersection",
    "create_solid_sweep": "протяжка профиля по пути; ВЫВОДИМ — габарит "
                          "path_mm, расширенный радиусом описанной окружности "
                          "профиля ОТ ЯКОРЯ (ровно то число, которое уже "
                          "считает постусловие опа)",
    "create_surface": "NURBS-поверхность; ВЫВОДИМ И ДОКАЗУЕМ — поверхность "
                      "лежит в выпуклой оболочке своей сети control_points_mm, "
                      "значит габарит сети есть законная верхняя оценка",
    "move_elements": "переносит существующие элементы",
    "change_type": "меняет тип, а с ним и тело",
    "place_family": "ставит семейство, габарит которого не выражен",
    "create_opening": "режет проём в хозяине",
    # MERGE 09.08. Both arrived with the rebar-cage wave and both are
    # required to be HERE, not only in OP_NO_BODY: real beams and bars
    # appear in the model after them, meaning their absence from the
    # search can hide a REAL collision — exactly the definition of this
    # dictionary. Loads and the egress path deliberately do not travel
    # here: they have no body at all, there is nothing to hide.
    "create_multistory_stairs": "размножает марш по уровням правилом, "
                                "которого нет в программе",
    "create_beam_system": "раскладывает балки правилом, которого нет в программе",
    "create_area_reinforcement": "кладёт стержни правилом типа армирования",
    "create_truss": "ставит ферму, габариты поясов которой не выражены",
    # The pad wave: the body is real, there is no hull (see OP_NO_BODY
    # above). A subregion does NOT travel here — a surface painting has
    # nothing to hide.
    "create_topography": "строит грунт, оболочки которого поиск не умеет",
    "create_building_pad": "строит площадку, оболочки которой поиск не умеет",
    # The curtain-profile wave: the body is real, there is no hull (see
    # OP_NO_BODY).
    "create_wall_sweep": "строит карниз, оболочки которого поиск не умеет",
    "create_slab_edge": "строит краевой профиль, оболочки которого поиск "
                        "не умеет",
    "create_face_wall": "строит стену по грани массы, оболочки которой поиск "
                        "не умеет: у FaceWall нет LocationCurve",
    "create_stairs_landing": "строит площадку лестницы, оболочки "
                             "которой поиск не умеет",
    "create_stairs_run": "строит марш лестницы, оболочки которой поиск "
                         "не умеет",
    # THE BRANCHES WAVE 19.08. Twelve ops with a DECLARED body had no
    # geometry branch and were going into the lock of silence. Eight got a
    # branch; these three did NOT, and their cause is ONE and named
    # precisely: the bounding box is derived not from their own
    # declaration, but from a HOST that the bundle has not yet resolved
    # into geometry at this stage. Guessing on their behalf is not
    # allowed — a hull made of defaults produces findings that don't exist
    # and hides the real ones.
    #
    # 🔴 And they are required to be HERE, not only in the lock of
    # silence: the report's line «ВНЕ ПРОВЕРКИ, И ЭТО МОЖЕТ ПРЯТАТЬ
    # КОЛЛИЗИЮ» is computed FROM THIS DICTIONARY. Before this fix not one
    # of the twelve was counted in it — the lock named them in the census,
    # while the loudest warning stayed silent.
    "create_door": "ставит дверь, габарит которой задан символом и осью "
                   "хозяина, а не собственным объявлением",
    "create_window": "ставит окно, габарит которого задан символом и осью "
                     "хозяина, а не собственным объявлением",
    "create_wall_foundation": "ставит ленту под стену-хозяина, габарит "
                              "которой задан её осью, а не объявлением",
}

#: The `BuiltInParameter` name under which the EMITTER writes the declared
#: diameter. The numbers are put here, and deliberately NOT into
#: `section_radius_mm`: that way the fitness of the reading is judged by
#: the closed table `hulls.DIAMETER_KIND`, not by this module. It is
#: precisely that table that discards a pipe's NOMINAL size (R3 red: DN100
#: — 100 against an outer 114.3), and the refusal arrives in its words.
#:
#: Emission addresses: `authoring.py:662` (create_pipe), `authoring.py:2217`
#: (create_duct), `authoring.py:2683/2771` (pipe graphs),
#: `authoring.py:2861` (route_duct_system).
SECTION_PARAM_BY_OP: dict[str, str] = {
    "create_pipe": "RBS_PIPE_DIAMETER_PARAM",
    "create_pipe_system": "RBS_PIPE_DIAMETER_PARAM",
    "route_pipe_system": "RBS_PIPE_DIAMETER_PARAM",
    "create_duct": "RBS_CURVE_DIAMETER_PARAM",
    "route_duct_system": "RBS_CURVE_DIAMETER_PARAM",
}

#: Operations whose axis is a SEGMENT in absolute mm (the emitter's
#: `P(x,y,z)`, `authoring.py:168`: an mm->feet conversion with no tie to a
#: level whatsoever). It is exactly for these that the axis can be read
#: without knowing the level elevation.
_AXIS_OPS = frozenset({
    "create_pipe", "create_duct", "create_conduit", "create_cable_tray",
    "create_pipe_placeholder", "create_duct_placeholder",
})

#: Graph operations: one op — MANY bodies, one per edge.
_GRAPH_OPS = frozenset({
    "create_pipe_system", "route_pipe_system", "route_duct_system",
})

_DIRECTSHAPE_CATEGORY = {
    "generic_model": "OST_GenericModel",
    "specialty_equipment": "OST_SpecialityEquipment",
    "furniture": "OST_Furniture",
    # `mass`/`site`/`entourage` are absent from the package's closed table:
    # their outcome is `kind_outside_table`, named by the package, not
    # invented here.
    "mass": "OST_Mass",
    "site": "OST_Site",
    "entourage": "OST_Entourage",
}


def category_of(op: Mapping[str, Any]) -> str | None:
    """The Revit category of an operation, or `None` — this operation
    creates no body.

    THE REGISTRY ANSWERS (`spec.op_result_categories`), not a local table.
    A table of its own used to be here, it duplicated the registry's and
    had ALREADY diverged from it — the justification and numbers are in
    `REGISTRY_GAPS`. The registry can also do what the copy could not:
    resolve the category by the operation's own CLOSED enumeration
    (`category` for the column and the extrusion, `variety` for the
    foundation, the opening, the terrain), so there are no separate
    resolvers here anymore.

    WHY THIS IS STILL NOT ONE SINGLE RELATION, and why there is therefore
    an intersection with `hulls.KIND_TABLE` rather than a direct
    assignment. The registry answers the CENSUS question — "which
    categories does the op create in the document" — and honestly returns
    SEVERAL when the program does not decide (a railing: freestanding or
    on a stair; a foundation slab: a slab or a foundation). This module
    needs a different answer — "by which rule should `KIND_TABLE` judge
    the body" — and it is required to be a single one. So:

      * `DirectShape` is thrown out of the registry's answer — a CENSUS
        key, not a Revit category;
      * what remains is what `KIND_TABLE` knows: of the railing's pair,
        exactly `OST_StairsRailing` survives, and the previous guess
        became a consequence;
      * if more than one still remains after that — the choice is NAMED
        in `REGISTRY_GAPS`, not made silently.
    """
    name = str(op.get("op") or "")
    try:
        cats = _REGISTRY_CATEGORIES(op) or ()
    except Exception:  # noqa: BLE001 — no registry: the named rows remain
        logger.debug("registry category lookup failed", exc_info=True)
        cats = ()
    cats = tuple(c for c in cats if c not in _CENSUS_ONLY_KEYS)
    if len(cats) > 1:
        try:
            from kir.clash import hulls as _hulls

            known = tuple(c for c in cats
                          if _hulls.KIND_TABLE.get(c) is not None)
            if known:
                cats = known
        except Exception:  # noqa: BLE001 — no table: there is nothing to narrow down
            logger.debug("kind table lookup failed", exc_info=True)
    # Zero (the registry is silent) or more than one (the registry does
    # not decide) — both cases are closed by a NAMED row of
    # `REGISTRY_GAPS`, and both are visible in one list.
    chosen = cats[0] if len(cats) == 1 else REGISTRY_GAPS.get(name)
    if chosen is None:
        return None
    # THE LAST WORD BELONGS TO THE BODY TABLE, AND IT ANSWERS A DIFFERENT
    # QUESTION THAN THE REGISTRY. The registry is right that `create_room`
    # creates `OST_Rooms`: a room does appear in the document. But it is
    # never a body (`KIND_TABLE` -> eligible False), and keeping it in the
    # census of ELEMENTS would mean inflating the "without a body"
    # denominator with things that by nature never have a body — that is,
    # lying with the very number this whole accounting was set up to keep
    # honest. Such operations stay in `no_body` with their own NAME.
    try:
        from kir.clash import hulls as _hulls

        # A category the table does NOT know is ALSO NOT a body, and this
        # is not a nitpick: the table does not know `create_text` ->
        # `OST_TextNotes` at all, and without this row 130 text notes of
        # `snowdon_plumb_v4` would enter the element census, inflating the
        # "without a body" denominator with a thing that never has a body.
        rule = _hulls.KIND_TABLE.get(chosen)
        if rule is None or not rule.eligible:
            return None
    except Exception:  # noqa: BLE001 — no table: hand it back as is
        logger.debug("kind table eligibility lookup failed", exc_info=True)
    return chosen


def op_categories(name: str) -> tuple[str, ...]:
    """All the categories by which `category_of` judges the body of THIS
    operation.

    WHY A SEPARATE FUNCTION, NOT A REPEATED CALL TO `category_of`
    (11.08.2026). For some ops the category is decided by the operation's
    own CLOSED enumeration (`category` for `create_directshape`,
    `create_solid_extrusion`, `create_solid_revolve`; `variety` for the
    foundation, the opening, the terrain), and `category_of({"op": name})`
    without a value for the enumeration honestly answers `None`. Asking
    "does the op have a body" with one bare call means taking that `None`
    for "no body" — measurement 11.08: that is how THREE operations out of
    thirty were lost, each with a real body.

    The enumeration is iterated OVER IN FULL and the answers are
    unioned — the same technique and for the same reason as
    `spec.op_census_categories`: the module's answer is required to be
    correct for ANY permitted value, otherwise it is not an answer about
    the op.

    THIS IS NOT A SECOND TABLE. There is not a single stored "op ->
    category" pair here: the function ASKS `category_of` every time, that
    is, the registry and `hulls.KIND_TABLE`. The removed `OP_CATEGORY` was
    exactly a stored copy, and it had diverged from the registry in three
    ways (`test_clash_coverage`).
    """
    from itertools import product

    from kir import spec as _spec

    ospec = _spec.OPS.get(name)
    if ospec is None:
        return ()
    axes = [[(p.name, choice) for choice in p.choices]
            for p in ospec.params
            if p.name in ("category", "variety") and p.choices]
    found: set[str] = set()
    for combo in (product(*axes) if axes else [()]):
        probe: dict[str, Any] = {"op": name}
        probe.update(dict(combo))
        chosen = category_of(probe)
        if chosen:
            found.add(chosen)
    return tuple(sorted(found))


def body_making_ops() -> tuple[str, ...]:
    """Registry operations about whose body this module is REQUIRED to
    have an answer.

    The complement of `OP_NO_BODY` up to the registry, and in exactly this
    form — because the table's closedness is precisely the claim
    "registry = bodies + named causes for their absence", there is no
    third basket. Listing them with a list OF OUR OWN would mean setting
    up the very registry copy whose removal this file describes.
    """
    from kir import spec as _spec

    return tuple(sorted(set(_spec.OPS) - set(OP_NO_BODY)))


# ═════════════════════════════════════════════════════════════════════════
# 2. BUNDLE -> ELEMENTS IN L0 FORM
# ═════════════════════════════════════════════════════════════════════════

#: The separator of a bundle operation's qualified identifier. EQUALS
#: `design_check._BUNDLE_SEP` deliberately and is held by a test: the
#: address of a clash finding and the address of a verdict finding are
#: required to lead to the same line of the script.
_BUNDLE_SEP = "/"

#: The prefix of a body spawned by a graph edge: one op — many bodies.
_SEGMENT_SEP = "#"


def bundle_oid(position: int, oid: str) -> str:
    """An operation's identifier AT THE SCALE OF THE BUNDLE: `p1/wall3`.

    It is qualified ALWAYS, not only on collision — for the same reason as
    in `design_check._bundle_oid`: `id` is unique within a program, a
    match between programs is legitimate, and the address of a fix is
    required to depend only on what it leads to.
    """
    return f"p{position}{_BUNDLE_SEP}{oid}"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") else None


def _pt3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        return None
    out = [_num(c) for c in value[:3]]
    return None if any(c is None for c in out) else [float(c) for c in out]


def _sel_text(value: Any) -> str | None:
    """A selector -> a short address string. It resolves nothing: the
    address is needed by the finding so there is something to pin it to
    visually."""
    if isinstance(value, Mapping):
        by, raw = value.get("by"), value.get("value")
        if by and raw is not None:
            return f"{by}:{raw}"
        return None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _mesh_bbox(mesh: Any) -> tuple[list[float], list[float]] | None:
    if not isinstance(mesh, Mapping):
        return None
    verts = mesh.get("vertices_mm")
    if not isinstance(verts, (list, tuple)) or not verts:
        return None
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for raw in verts:
        pt = _pt3(raw)
        if pt is None:
            return None
        for k in range(3):
            lo[k] = min(lo[k], pt[k])
            hi[k] = max(hi[k], pt[k])
    return lo, hi


def _type_name_of(op: Mapping[str, Any]) -> str | None:
    for field in ("duct_type", "pipe_type", "tray_type", "conduit_type",
                  "type", "symbol"):
        text = _sel_text(op.get(field))
        if text is not None:
            return text
    return None


def _graph_bodies(op: Mapping[str, Any]) -> list[tuple[list[float], list[float], float | None]]:
    """Graph edges -> bodies' axes. The node/edge shape is taken from
    `connect.graph_validate` (`{"id", "xyz_mm"}` and
    `{"from", "to", "diameter_mm"?}`), not guessed."""
    nodes: dict[str, list[float]] = {}
    for node in op.get("nodes") or ():
        if not isinstance(node, Mapping):
            continue
        nid, pt = node.get("id"), _pt3(node.get("xyz_mm"))
        if isinstance(nid, str) and pt is not None:
            nodes[nid] = pt
    default_dia = _num(op.get("diameter_mm"))
    out: list[tuple[list[float], list[float], float | None]] = []
    for seg in op.get("segments") or ():
        if not isinstance(seg, Mapping):
            continue
        a, b = nodes.get(str(seg.get("from"))), nodes.get(str(seg.get("to")))
        if a is None or b is None:
            continue
        dia = _num(seg.get("diameter_mm"))
        out.append((a, b, default_dia if dia is None else dia))
    return out


#: The ELEMENT keys that carry coordinates. The set is CLOSED and small —
#: that is why the shift is done here, not on the op: the op's fields are
#: kind-dependent (a direction is not a point, the 21.08 lesson cost a
#: day), whereas the element's geometry is already reduced to points,
#: elevations, and a bounding box. `prism` carries no coordinates at all
#: (width, uniformity, blockers, source), so it is not in the list and
#: should not be.
_ELEMENT_POINTS = ("p0_mm", "p1_mm", "bbox_min_mm", "bbox_max_mm")
_ELEMENT_Z = ("z0_mm", "z1_mm")


def _element(sid: str, category: str, op: Mapping[str, Any]) -> dict[str, Any]:
    el = {
        "element_id": sid,
        "category": category,
        "level_id": _sel_text(op.get("level")) or _sel_text(op.get("base_level")),
        "type_name": _type_name_of(op),
    }
    delta = op.get("__group_delta__")
    if delta is not None:
        el["__group_delta__"] = delta
    return el


def _apply_group_deltas(elements: list[dict]) -> int:
    """Shift the bodies of the group's copies and remove the marker.
    Returns the number shifted."""
    moved = 0
    for el in elements:
        d = el.pop("__group_delta__", None)
        if d is None:
            continue
        dx, dy, dz = (list(d) + [0.0, 0.0, 0.0])[:3]
        for k in _ELEMENT_POINTS:
            v = el.get(k)
            if isinstance(v, (list, tuple)) and len(v) >= 2:
                z = float(v[2]) + float(dz) if len(v) > 2 else float(dz)
                el[k] = [float(v[0]) + float(dx), float(v[1]) + float(dy), z]
        for k in _ELEMENT_Z:
            v = el.get(k)
            if isinstance(v, (int, float)):
                el[k] = float(v) + float(dz)
        moved += 1
    return moved


def _with_group_placements(ops):
    """Expand a group into members AND INSTANCES, marking each copy with
    an offset.

    🔴 MEASUREMENT 23.08.2026, A LIVE WRITE ALONGSIDE A REAL K3. A program
    with a unit of seven walls and eleven instances placed 84 walls into
    the model, and NOT ONE of them took part in the clash search: the
    report printed «ВНЕ ПРОВЕРКИ, И ЭТО МОЖЕТ ПРЯТАТЬ КОЛЛИЗИЮ:
    create_group ×1».

    The third consumer in a row that did not know about the group:
    acceptance attributed all the copies to one level, the scene showed
    zero walls out of seven. Both were fixed the same day; this is where
    the last one is closed.

    WHY IT IS POSSIBLE NOW, WHEN IT WASN'T IN THE MORNING. In the morning
    I set the branch aside, calling it a debt: shifting the OP is required
    to be kind-dependent, and a flat `_shift` would have ruined the
    directions. But there is no need to shift the op — it is enough to
    shift the finished BODY, whose coordinates are already reduced to a
    closed set of six keys. The debt is closed by moving where the fix is
    made, not by boldness.
    """
    for op in (ops or ()):
        if not isinstance(op, Mapping) or str(op.get("op") or "") != "create_group":
            yield op
            continue
        members = op.get("members")
        if not isinstance(members, list):
            yield op            # a broken group remains itself and will enter the census
            continue
        gid = str(op.get("id") or "group")
        flat = [m for m in members if isinstance(m, Mapping)]
        for m in flat:          # occupancy 0 — the members themselves, without a shift
            yield dict(m, id=f"{gid}/{m.get('id') or 'm'}")
        placements = op.get("placements")
        if not isinstance(placements, list):
            continue
        for k, pl in enumerate(placements, start=1):
            if not isinstance(pl, (list, tuple)) or len(pl) < 2:
                continue
            for m in flat:
                yield dict(m, id=f"{gid}/{m.get('id') or 'm'}@{k}",
                           __group_delta__=list(pl))


# ═════════════════════════════════════════════════════════════════════════
# 2b. THE TYPE'S CROSS-SECTION AND THE LEVEL ELEVATION — WHAT IS READ FROM
#     THE SNAPSHOT
#
# The sections wave (09.08). Before it, this module knew exactly what the
# program wrote, and wall thickness is not and never will be in the
# program: it lives in the TYPE. Now the type arrives from the ground
# stage already resolved against the LIVE document, and its geometry
# travels with it. Nothing is still guessed at: where there is no
# snapshot, the behavior is the previous one LETTER FOR LETTER (zero
# bodies for the wall); where there is a snapshot but the type has no
# cross-section, that is a NAMED census row.
# ═════════════════════════════════════════════════════════════════════════

#: The tolerance for comparing two numbers in mm that arrived by different
#: paths (the program writes 100.0, the document stores feet and converts
#: back). See `open_model.TypeSection.outer_for_nominal_mm` — the
#: justification is there too.
_NOMINAL_TOL_MM = 0.5


@dataclass(frozen=True)
class SnapshotSections:
    """Type geometry and level elevations of ONE open-model snapshot.

    The row's key is the same short selector text that `_sel_text` prints
    (`name:Стена 200`, `element_id:273445`), so the search runs on exactly
    what the program WROTE, without a second selector resolution
    alongside ground. A selector that ground resolves by a rule
    (`by:default`, `by:ref`) does not end up here and gets a named cause,
    not a silent miss.
    """

    levels: Mapping[str, float]
    types: Mapping[str, Mapping[str, Mapping[str, Any]]]

    @classmethod
    def from_snapshot(cls, snapshot: Any) -> "SnapshotSections | None":
        """The ground snapshot -> an index. `None` — there is no snapshot
        at all.

        An empty index and an ABSENT index are different facts: the first
        means "we asked, the types have no cross-section", the second
        means "we did not ask". The receipt prints them in different
        words, so here too they are different values.
        """
        if not isinstance(snapshot, Mapping):
            return None
        levels: dict[str, float] = {}
        types: dict[str, dict[str, Mapping[str, Any]]] = {}
        for pool, rows in snapshot.items():
            if not isinstance(pool, str) or not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                keys = []
                if row.get("id") is not None:
                    keys.append(f"element_id:{row['id']}")
                if isinstance(row.get("name"), str) and row["name"]:
                    keys.append(f"name:{row['name']}")
                if pool == "levels":
                    elevation = _num(row.get("elevation_mm"))
                    if elevation is not None:
                        for key in keys:
                            levels.setdefault(key, elevation)
                    continue
                section = row.get("section")
                if isinstance(section, Mapping):
                    bucket = types.setdefault(pool, {})
                    for key in keys:
                        bucket.setdefault(key, section)
        return cls(levels, types)

    def level_mm(self, selector: Any) -> float | None:
        key = _sel_text(selector)
        return None if key is None else self.levels.get(key)

    def section(self, pool: str, selector: Any) -> Mapping[str, Any] | None:
        key = _sel_text(selector)
        if key is None:
            return None
        return (self.types.get(pool) or {}).get(key)

    def outer_for_nominal_mm(self, section: Mapping[str, Any],
                             nominal_mm: float) -> float | None:
        """Nominal -> OUTER dimension by the TYPE's table. Not a single
        multiplier: the conversion exists because the document printed it
        (`PipeSegment.GetSizes`), not because we know the sizing
        standard."""
        for pair in (section.get("sizes") or ()):
            if (not isinstance(pair, (list, tuple)) or len(pair) != 2):
                continue
            nominal, outer = _num(pair[0]), _num(pair[1])
            if nominal is None or outer is None:
                continue
            if abs(nominal - float(nominal_mm)) <= _NOMINAL_TOL_MM:
                return outer
        return None


def _pool_for(op_name: str, param: str, op: Mapping[str, Any]) -> str | None:
    """The snapshot pool against which ground resolves this operand.

    It is asked of the REGISTRY, not written out here as a second list: a
    pool that had drifted from `spec.OPS` would be reading the
    cross-section of the wrong kind of thing.
    """
    try:
        from kir import spec
    except Exception:  # noqa: BLE001 — the registry is unavailable: there simply are no cross-sections
        return None
    op_spec = spec.OPS.get(op_name)
    if op_spec is None:
        return None
    for name, pool, _required in op_spec.grounded:
        if name != param:
            continue
        if "{category}" in pool:
            return pool.format(
                category=str(op.get("category") or "structural"))
        return pool
    return None


#: Slab operations: a plan contour + the TYPE's thickness. The value is
#: the name of the operand that declares the contour.
_SLAB_OPS = {"create_floor": "outline", "create_ceiling": "outline",
             "create_roof": "outline"}

#: Operations whose body is a prism around an AXIS with a cross-section
#: from the TYPE.
_SECTION_BBOX_OPS = frozenset({"create_column", "create_beam"})


def _outline_xy(op: Mapping[str, Any], field: str) -> list[list[float]] | None:
    """A plan contour, if it is declared with NUMBERS. A region
    (`contour`) deliberately does not fall in here: its vertices can be
    grid-line addresses and arcs, and resolving them is the job of
    `contour.py` with a grid pool, which the bundle does not have."""
    raw = op.get(field)
    if not isinstance(raw, (list, tuple)) or len(raw) < 3:
        return None
    out: list[list[float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        x, y = _num(point[0]), _num(point[1])
        if x is None or y is None:
            return None
        out.append([x, y])
    return out


def _region_lowered(op: Mapping[str, Any], field: str) -> tuple[Any, str]:
    """A program region -> canonical edges, or a named refusal cause.

    THE GRID-LINE POOL IS EMPTY HERE, AND THIS IS NOT A SIMPLIFICATION. A
    region's vertex can be a grid-line address (`{"at_grid": [...]}`), and
    the bundle has no grid-line pool — `_outline_xy` for the same reason
    does not take regions at all. The difference is that lowering with an
    empty pool REFUSES with a typed cause (`KIR-G104`), rather than
    inventing a point: a literal region passes, one addressed by grid
    lines is called a refusal. Verified for both cases.

    The bounding box after lowering is EXACT, arcs included:
    `contour.edges_bbox` takes an arc's cardinal extrema, not the chord
    (measurement: a `poly` with bulge 0.4 gives 6800 against 6000 by the
    chord — 800 mm of body outside the chord).
    """
    raw = op.get(field)
    if not isinstance(raw, Mapping):
        return None, f"{field}_not_a_region"
    # A broken import is not a fact about geometry; the argument is
    # entirely in `_solid_geometry`.
    from kir import contour as _contour
    diags: list = []
    lowered = _contour.validate_region(raw, [], str(op.get("id") or ""),
                                       field, diags)
    if lowered is None:
        return None, ("region_addresses_grids" if diags
                      else f"{field}_region_invalid")
    return lowered, ""


def _solid_geometry(op: Mapping[str, Any], el: dict[str, Any],
                    ctx: "SnapshotSections | None") -> str:
    """An extrusion / revolve body: the bounding box is DERIVED FROM THE
    PROGRAM IN FULL.

    For both operations `grounded` is EMPTY — they resolve neither a
    level nor a type, all the geometry is declared by the author. So no
    snapshot is needed here, and a `no_snapshot` refusal would be false:
    there is nothing to ask.

    The sector's bounding box is taken with the same
    `solid_emit._sector_bbox` the emitter uses to compute it for the
    witness — we do not create a second number for one question.
    """
    name = str(op.get("op") or "")
    lowered, why = _region_lowered(op, "profile")
    if lowered is None:
        return why
    # 🔴 A BROKEN IMPORT IS NOT A FACT ABOUT GEOMETRY (21.08.2026). A
    # literal cause used to be returned here, meaning a failure of OUR OWN
    # module traveled into the report on a par with "the author did not
    # declare a contour" and read as "the element has no body". These are
    # different things: "no body" is a legitimate quiet outcome, while a
    # contour sublanguage that failed to load is a broken tree, in which
    # `import_guard` screams while all of clash computes an untruth.
    #
    # There was nothing to classify this as, and there is no need to: not
    # one of the five classes answers the question "who fixes it" (not
    # the author, not the snapshot, not the hull lock). So the failure is
    # re-raised, rather than turned into a cause.
    from kir import contour as _contour
    x0, y0, x1, y1 = _contour.region_bbox(lowered)
    base_z = _num(op.get("base_z_mm")) or 0.0
    if name == "create_solid_extrusion":
        height = _num(op.get("height_mm"))
        if height is None or height <= 0:
            return "solid_height_missing"
        el["bbox_min_mm"] = [x0, y0, base_z]
        el["bbox_max_mm"] = [x1, y1, base_z + height]
        return ""
    # REVOLVE. The profile is declared in axial coordinates: x — radius,
    # y — elevation above `base_z_mm`. The radii are taken from the
    # profile's bounding box, and so is the height.
    sweep = _num(op.get("sweep_deg"))
    axis = op.get("axis_xy_mm")
    if sweep is None or not sweep:
        return "revolve_sweep_missing"
    if not (isinstance(axis, (list, tuple)) and len(axis) >= 2):
        return "revolve_axis_missing"
    if x0 < 0.0:
        return "revolve_profile_crosses_axis"
    # The same argument as for the contour above: a `solid_emit` that
    # failed to load is a broken tree, not an element without a body. The
    # failure is re-raised.
    from kir.solid_emit import _sector_bbox

    sx0, sy0, sx1, sy1 = _sector_bbox(x0, x1, abs(float(sweep)))
    ax, ay = float(axis[0]), float(axis[1])
    el["bbox_min_mm"] = [ax + sx0, ay + sy0, base_z + y0]
    el["bbox_max_mm"] = [ax + sx1, ay + sy1, base_z + y1]
    return ""


def _stairs_geometry(op: Mapping[str, Any], el: dict[str, Any],
                     ctx: "SnapshotSections | None") -> str:
    """A stair run: a declared path + width + level elevations -> a
    bounding box.

    WHAT IS LEGITIMATE HERE, AND WHAT IS NOT. Width and path are declared
    by the program, elevations are resolved by the level pool. But the
    NUMBER of steps Revit takes from the run's length divided by the
    TYPE's tread — and this op does not choose the type at all (its
    `grounded` has only levels). Measurement 19.08: a length of 8680 with
    a tread of 250 gave 36 risers instead of the needed 29, and the run
    went 995 mm ABOVE the top level. Since 19.08 such a program is rolled
    back by the guard `ActualRisersNumber > DesiredRisersNumber`, so the
    declared span [bottom, top] IS the one built: the overshoot no longer
    reaches the model.

    The remaining 66 mm is tread material above the nominal elevation, a
    constant across all nine runs of the live building. It is ADDED
    upward, not ignored: the hull is required to contain the body, not
    coincide with the nominal.
    """
    if op.get("spiral") is not None:
        return "stairs_spiral_extent_not_expressed"
    p0, p1 = op.get("p0_mm"), op.get("p1_mm")
    if not (isinstance(p0, (list, tuple)) and isinstance(p1, (list, tuple))
            and len(p0) >= 2 and len(p1) >= 2):
        return "stairs_run_path_missing"
    if ctx is None:
        return "no_snapshot"
    z_base = _level_z(ctx, op, "base_level", None)
    z_top = _level_z(ctx, op, "top_level", None)
    if z_base is None or z_top is None:
        return "level_elevation_unknown"
    width = _num(op.get("width_mm"))
    if width is None or width <= 0:
        return "stairs_width_not_declared"
    half = width / 2.0
    xs = [float(p0[0]), float(p1[0])]
    ys = [float(p0[1]), float(p1[1])]
    lo, hi = min(z_base, z_top), max(z_base, z_top)
    el["bbox_min_mm"] = [min(xs) - half, min(ys) - half, lo]
    el["bbox_max_mm"] = [max(xs) + half, max(ys) + half, hi + _STAIR_TREAD_MM]
    return ""


#: Tread material ABOVE the nominal elevation of the run's top.
#: Measurement 19.08 on nine runs of a live building: 66 mm, THE SAME on
#: all of them, regardless of the rise (5400 and 3900 gave the same
#: number) — meaning it is a thickness, not a layout error. It is added
#: to the bounding box upward, because the hull is required to CONTAIN
#: the body; an undersized value here hides a collision with the slab of
#: the floor above.
_STAIR_TREAD_MM = 70.0


def _path_xyz(raw: Any, *, dims: int) -> list[list[float]] | None:
    """A declared polyline -> a list of points. Open, must not be
    closed."""
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    out: list[list[float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < dims:
            return None
        vals = [_num(point[i]) for i in range(dims)]
        if any(v is None for v in vals):
            return None
        out.append([float(v) for v in vals])  # type: ignore[arg-type]
    return out


def _railing_geometry(op: Mapping[str, Any], el: dict[str, Any],
                      ctx: "SnapshotSections | None") -> str:
    """A railing along a path: a polyline + level elevation + the TYPE's
    HEIGHT.

    The height is NOT guessed at. In the live measurement of 19.08 the
    depths of a railing-beam conflict came out to 875.4 and 1075.0 mm —
    and these are exactly the heights of the «900 мм» and «1100 мм»
    catalog types. So the value is decisive, and it can only be taken
    from the type: without the type's cross-section the branch REFUSES by
    name, rather than substituting 1000.
    """
    if str(op.get("variety") or "") != "path":
        return "railing_variety_not_path"
    path = _path_xyz(op.get("path"), dims=2)
    if path is None:
        return "railing_path_missing"
    if ctx is None:
        return "no_snapshot"
    z_base = _level_z(ctx, op, "level", None)
    if z_base is None:
        return "level_elevation_unknown"
    pool = _pool_for("create_railing", "type", op)
    section = None if pool is None else ctx.section(pool, op.get("type"))
    if section is None:
        return ("railing_type_not_in_snapshot" if op.get("type") is not None
                else "railing_type_not_declared")
    height = _num(section.get("height_mm"))
    if height is None or height <= 0:
        return "railing_type_height_absent"
    thick = _num(section.get("thickness_mm")) or 0.0
    half = max(thick, 0.0) / 2.0
    xs = [pt[0] for pt in path]
    ys = [pt[1] for pt in path]
    el["bbox_min_mm"] = [min(xs) - half, min(ys) - half, z_base]
    el["bbox_max_mm"] = [max(xs) + half, max(ys) + half, z_base + height]
    return ""


def _flex_geometry(op: Mapping[str, Any], el: dict[str, Any],
                   ctx: "SnapshotSections | None") -> str:
    """A flexible run: a declared THREE-DIMENSIONAL polyline + the TYPE's
    cross-section radius.

    The polyline's bounding box CONTAINS the sag only if there is none: a
    flexible duct between Revit points follows a spline, and downward sag
    is not covered by the polyline's bounding box. So the radius is taken
    from the type and added in ALL directions, and the sag itself is
    named a limitation: an undersized value here hides a collision, and
    the reader is required to know this, not guess at it.
    """
    name = str(op.get("op") or "")
    path = _path_xyz(op.get("path"), dims=3)
    if path is None:
        return "flex_path_missing"
    if ctx is None:
        return "no_snapshot"
    param = "flex_duct_type" if name == "create_flex_duct" else "flex_pipe_type"
    pool = _pool_for(name, param, op)
    section = None if pool is None else ctx.section(pool, op.get(param))
    if section is None:
        return (f"{name}_type_not_in_snapshot" if op.get(param) is not None
                else f"{name}_type_not_declared")
    diameter = _num(section.get("diameter_mm"))
    if diameter is None or diameter <= 0:
        return f"{name}_type_diameter_absent"
    radius = diameter / 2.0
    xs = [pt[0] for pt in path]
    ys = [pt[1] for pt in path]
    zs = [pt[2] for pt in path]
    el["bbox_min_mm"] = [min(xs) - radius, min(ys) - radius, min(zs) - radius]
    el["bbox_max_mm"] = [max(xs) + radius, max(ys) + radius, max(zs) + radius]
    return ""


def _extrusion_roof_geometry(op: Mapping[str, Any], el: dict[str, Any],
                             ctx: "SnapshotSections | None") -> str:
    """An extruded roof: a profile in a vertical plane + a run along the
    normal.

    NO SNAPSHOT IS NEEDED HERE, AND THIS IS NOT A SIMPLIFICATION. The
    profile is declared in the coordinates of the `[u, z]` plane, where
    `z` is a WORLD elevation (this is how the emitter lowers it:
    `world = [(x0 + u*ux, y0 + u*uy, z) ...]`), and the run is given by
    the numbers `start_mm`/`end_mm`. The level for this op decides the
    attachment, not the geometry.

    THE SIGN OF THE NORMAL. The emitter reads `ReferencePlane.Normal` at
    runtime and on a mismatch feeds the pair flipped — that is, the run
    is always measured from OUR normal `dir x Z`. The bounding box is
    therefore built from both ends of the run, and the order of
    `start`/`end` does not affect it.
    """
    p0, p1 = op.get("p0_mm"), op.get("p1_mm")
    if not (isinstance(p0, (list, tuple)) and isinstance(p1, (list, tuple))
            and len(p0) >= 2 and len(p1) >= 2):
        return "roof_plane_trace_missing"
    profile = _path_xyz(op.get("profile_mm"), dims=2)
    if profile is None:
        return "roof_profile_missing"
    start, end = _num(op.get("start_mm")), _num(op.get("end_mm"))
    if start is None or end is None:
        return "roof_extrusion_extent_missing"
    x0, y0 = float(p0[0]), float(p0[1])
    dx, dy = float(p1[0]) - x0, float(p1[1]) - y0
    dlen = math.hypot(dx, dy)
    if dlen <= 0.0:
        return "roof_plane_trace_degenerate"
    ux, uy = dx / dlen, dy / dlen
    nx, ny = uy, -ux
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for u, z in profile:
        for t in (start, end):
            xs.append(x0 + u * ux + t * nx)
            ys.append(y0 + u * uy + t * ny)
            zs.append(z)
    el["bbox_min_mm"] = [min(xs), min(ys), min(zs)]
    el["bbox_max_mm"] = [max(xs), max(ys), max(zs)]
    return ""


def _contour_slab_geometry(op: Mapping[str, Any], el: dict[str, Any],
                           ctx: "SnapshotSections | None") -> str:
    """A slab by contour: a REGION + elevation + the type's thickness ->
    a bounding box.

    It differs from `_slab_geometry` in exactly the input: there the
    contour is declared with numbers (`outline`), here with a region
    (`contour`), which handles arcs and grid-line addresses. So we do not
    assemble a prism with a profile here — we hand back a bounding box: a
    profile from a region would require the READER to resolve arcs into
    flat edges, and `hulls` for OST_Floors takes the `profile` source
    from ready-made loops.
    """
    lowered, why = _region_lowered(op, "contour")
    if lowered is None:
        return why
    if ctx is None:
        return "no_snapshot"
    # A broken import is not a fact about geometry; the argument is
    # entirely in `_solid_geometry`.
    from kir import contour as _contour
    # 🔴 THE BOUNDING BOX FROM A SPLINE IS A LOWER ESTIMATE, AND THIS IS
    # SAID IN `region_bbox` ITSELF (25.08.2026, an audit finding,
    # confirmed by reading): "THEREFORE A BOUNDING-BOX WITNESS ON A
    # SPLINE IS ILLEGITIMATE… an op whose witness rests on a bounding box
    # is required to ask `region_has_spline` and refuse".
    #
    # Both emitters do exactly that, bought by a LIVE measurement: Revit
    # gave 9705.3 mm along Y, our estimate expected 9426.0 — 279 mm
    # against a tolerance of 50.
    #
    # Here there was no one to ask. `create_floor_by_contour` STANDS in
    # `SPLINE_WITNESSED_OPS`, meaning the grounding guard PASSES it
    # through together with the spline — and an undersized bounding box
    # was traveling into the bundle's `bbox_min_mm/bbox_max_mm`. The
    # consequence is quieter than a refusal and so worse: a collision
    # BEYOND the undersized box's boundary simply is not found, and "0
    # disputes" reads as "clean".
    #
    # The solid neighbor (`_solid_geometry`) deliberately does NOT have
    # this check: the spline does not reach it — the grounding guard cuts
    # it off, because there are no solid ops in `SPLINE_WITNESSED_OPS`. A
    # guard that cannot fire is worse than a missing one.
    if _contour.region_has_spline(lowered):
        return "region_has_spline"
    x0, y0, x1, y1 = _contour.region_bbox(lowered)
    z_ref = _level_z(ctx, op, "level", "height_offset_mm")
    if z_ref is None:
        return "level_elevation_unknown"
    pool = _pool_for("create_floor_by_contour", "type", op)
    section = None if pool is None else ctx.section(pool, op.get("type"))
    if section is None:
        return ("slab_type_not_in_snapshot" if op.get("type") is not None
                else "slab_type_not_declared")
    if section.get("kind") != "plate":
        return "slab_type_section_not_a_plate"
    thickness = _num(section.get("thickness_mm"))
    if thickness is None or thickness <= 0:
        return "slab_type_thickness_absent"
    # The same UNION of interpretations [z-t, z+t] as in `_slab_geometry`: the
    # program does not declare which direction the body grows from the
    # elevation, and guessing the sign is forbidden.
    el["bbox_min_mm"] = [x0, y0, z_ref - thickness]
    el["bbox_max_mm"] = [x1, y1, z_ref + thickness]
    return ""


def _level_z(ctx: "SnapshotSections | None", op: Mapping[str, Any],
             field: str, offset_field: str | None) -> float | None:
    if ctx is None:
        return None
    base = ctx.level_mm(op.get(field))
    if base is None:
        return None
    if offset_field is None:
        return base
    offset = _num(op.get(offset_field))
    return base + (0.0 if offset is None else offset)


def _wall_geometry(op: Mapping[str, Any], el: dict[str, Any],
                   ctx: "SnapshotSections | None") -> str:
    """Wall: axis (2D) + level elevations + TYPE thickness -> strip.

    An arc wall is REFUSED: a strip around the chord of the arc's body does
    not contain it — exactly the finding because of which `profile_refusal`
    refuses an outline with an arc (floor 9981227, 752.832 mm OUTSIDE the
    "conservative" hull).
    """
    if op.get("arc") is not None:
        return "wall_arc_not_a_segment"
    p0, p1 = op.get("p0_mm"), op.get("p1_mm")
    if not (isinstance(p0, (list, tuple)) and isinstance(p1, (list, tuple))
            and len(p0) >= 2 and len(p1) >= 2):
        return "wall_axis_missing"
    if ctx is None:
        return "no_snapshot"
    z_base = _level_z(ctx, op, "level", "base_offset_mm")
    if z_base is None:
        return "level_elevation_unknown"
    tops: list[float] = []
    z_top = _level_z(ctx, op, "top_level", "top_offset_mm")
    if z_top is not None:
        tops.append(z_top)
    height = _num(op.get("height_mm"))
    if height is not None:
        tops.append(z_base + height)
    if not tops:
        return "wall_top_unbound"
    # A UNION of interpretations, not a choice: when BOTH the top level AND
    # the height are declared, Revit decides, and rounding upward is
    # legitimate — guessing which of the two wins is not.
    lo = min([z_base] + tops)
    hi = max([z_base] + tops)
    pool = _pool_for("create_wall", "type", op)
    section = None if pool is None else ctx.section(pool, op.get("type"))
    if section is None:
        return ("wall_type_not_in_snapshot" if op.get("type") is not None
                else "wall_type_not_declared")
    if section.get("kind") != "plate":
        return "wall_type_section_not_a_plate"
    width = _num(section.get("thickness_mm"))
    if width is None or width <= 0:
        return "wall_type_thickness_absent"
    el["p0_mm"] = [float(p0[0]), float(p0[1]), lo]
    el["p1_mm"] = [float(p1[0]), float(p1[1]), lo]
    el["z0_mm"], el["z1_mm"] = lo, hi
    el["prism"] = {
        "width_mm": width,
        "uniform": bool(section.get("uniform")),
        "blockers": list(section.get("blockers") or ()),
        "source": str(section.get("source") or ""),
    }
    # The numbers are gathered and sit on the element; `hulls` will build the
    # strip from them — IF its closed table allows the wall a `prism` source.
    #
    # A QUESTION, NOT A STATEMENT, AND HERE IS WHY. A CONSTANT used to stand
    # here that asserted the contents of someone else's table without ever
    # reading it: "today OST_Walls rests on the bounding box." The assertion
    # was true BY ACCIDENT — right up to the day `prism` appears in
    # `sources`. On that day the wall would gain a BODY, and this line would
    # keep writing it into the census as "without geometry": `without_body`
    # is counted from bodies, while the REASON is printed from here, and the
    # two would drift apart silently.
    #
    # That day arrived on 14.08, and the question TO THE TABLE turned out to
    # be too small. The strip is admitted not by a table row alone, but by
    # the PAIR "table row AND absence of a bounding box" (`hulls.build_hull`:
    # the containment lock is measured against the actual body and stays
    # closed everywhere that body exists). Asking half the condition means
    # reproducing the same defect one level up — so instead we ask the VERY
    # function that builds the body, and by this line the element is already
    # complete.
    try:
        from kir.clash import hulls as _hulls

        record, _refusal = _hulls.build_hull(el)
        if record is not None:
            return ""
    except Exception:  # noqa: BLE001 — no hulls: treat the lock as closed
        logger.debug("wall prism gate lookup failed", exc_info=True)
    return "wall_prism_refused_by_containment_gate"


def _slab_geometry(op: Mapping[str, Any], el: dict[str, Any],
                   ctx: "SnapshotSections | None", field: str
                   ) -> tuple[str, dict | None, float | None]:
    """Slab: plan outline + TYPE thickness -> prism.

    THE Z-SPAN IS A UNION OF TWO INTERPRETATIONS, AND THAT IS STATED. Exactly
    which way the body grows from the elevation — downward (a floor slab) or
    upward (a ceiling) — this module cannot prove: it has no live Revit, and
    `create_floor` declares only an offset. So it takes [z−t, z+t]: a
    TWOFOLD rounding on thickness, legitimate under the law of conservatism,
    instead of guessing the sign — exactly the same decision as
    `wall_axis_halfwidth` makes when the offset side is unknown.

    THE ELEVATION DRIFTS AWAY AS A THIRD VALUE. The span [z−t, z+t] is a
    union of two interpretations, and from it alone the elevation AROUND
    which the union was built can no longer be recovered: the midpoint of
    the span coincides with it only because the two halves are equal, and
    that is a coincidence of arithmetic, not a fact. Whoever will judge
    whether slices meet must receive the elevation itself as a number.

    THERE ARE EIGHT EXITS HERE: seven refusals and one success, and all
    eight are required to return the triple. To whoever extends this return
    again: fix EVERY `return`, not just the last one — the size of the work
    is visible from here, not from an unpacking crash on the seventh
    refusal.
    """
    loop = _outline_xy(op, field)
    if loop is None:
        return ("slab_contour_is_a_region" if op.get("contour") is not None
                else "slab_outline_missing"), None, None
    if ctx is None:
        return "no_snapshot", None, None
    if op.get("slopes"):
        return "slab_sloped_not_a_plate", None, None
    z_ref = _level_z(ctx, op, "level", "height_offset_mm")
    if z_ref is None:
        return "level_elevation_unknown", None, None
    pool = _pool_for(str(op.get("op") or ""), "type", op)
    section = None if pool is None else ctx.section(pool, op.get("type"))
    if section is None:
        return ("slab_type_not_in_snapshot" if op.get("type") is not None
                else "slab_type_not_declared"), None, None
    if section.get("kind") != "plate":
        return "slab_type_section_not_a_plate", None, None
    thickness = _num(section.get("thickness_mm"))
    if thickness is None or thickness <= 0:
        return "slab_type_thickness_absent", None, None
    el["z0_mm"], el["z1_mm"] = z_ref - thickness, z_ref + thickness
    return "", {"profile_available": True, "exterior_loop": loop,
                "holes": [], "curve_kinds": []}, z_ref


def _section_radius_mm(section: Mapping[str, Any], *, doubled: bool
                       ) -> float | None:
    """Type section -> plan radius that CONTAINS the profile at any
    rotation.

    A rectangle is taken by its HALF-DIAGONAL for the same reason as in
    `hulls.SECTION_RULES`: the program declares the section's rotation
    (`rotation_deg`), but not the justification and profile anchor, and the
    half-diagonal contains the box at ANY angle.

    `doubled` — for a beam: the beam axis does not pass through the
    section's center (justification, review #3), and the offset side is not
    expressed in the program. The body, at any offset, lies within the FULL
    diagonal from the axis; this is a twofold rounding, and it is NAMED, not
    hidden.
    """
    factor = 2.0 if doubled else 1.0
    diameter = _num(section.get("diameter_mm"))
    if diameter is not None and diameter > 0:
        return diameter / 2.0 * factor
    width, height = _num(section.get("width_mm")), _num(section.get("height_mm"))
    if width and height and width > 0 and height > 0:
        return math.hypot(width, height) / 2.0 * factor
    return None


def _section_bbox_geometry(op: Mapping[str, Any], el: dict[str, Any],
                           ctx: "SnapshotSections | None") -> str:
    """Column / beam: TYPE section + axis -> bounding box."""
    name = str(op.get("op") or "")
    if ctx is None:
        return "no_snapshot"
    pool = _pool_for(name, "symbol", op)
    section = None if pool is None else ctx.section(pool, op.get("symbol"))
    if section is None:
        return ("symbol_not_in_snapshot" if op.get("symbol") is not None
                else "symbol_not_declared")
    radius = _section_radius_mm(section, doubled=(name == "create_beam"))
    if radius is None:
        return "symbol_has_no_structural_section"
    if name == "create_beam":
        p0, p1 = _pt3(op.get("p0_mm")), _pt3(op.get("p1_mm"))
        if p0 is None or p1 is None:
            return "beam_axis_missing"
        xs, ys, zs = ([p0[0], p1[0]], [p0[1], p1[1]], [p0[2], p1[2]])
    else:
        xy = op.get("xy")
        if not (isinstance(xy, (list, tuple)) and len(xy) >= 2):
            return "column_xy_missing"
        xs, ys = [float(xy[0])], [float(xy[1])]
        top_xy = op.get("top_xy")
        if isinstance(top_xy, (list, tuple)) and len(top_xy) >= 2:
            xs.append(float(top_xy[0]))
            ys.append(float(top_xy[1]))
        z_base = _level_z(ctx, op, "level", "base_offset_mm")
        z_top = _level_z(ctx, op, "top_level", "top_offset_mm")
        if z_base is None:
            return "level_elevation_unknown"
        if z_top is None:
            return "column_top_unbound"
        # THE FAMILY'S OWN OVERHANG. Measured 09.08 (Snowdon, 114 columns):
        # 4 columns of one type extended past the hull by exactly 254.0 mm
        # DOWNWARD — the family base sits below its own elevation. Only the
        # type knows this, and now it says so. The overhang is added by
        # UNION, not by replacement: a column stretched between levels stays
        # stretched.
        z_local_lo = _num(section.get("local_z_min_mm"))
        z_local_hi = _num(section.get("local_z_max_mm"))
        zs = [z_base, z_top]
        if z_local_lo is not None and z_local_hi is not None:
            zs.append(z_base + min(0.0, z_local_lo))
            zs.append(z_top + max(0.0, z_local_hi - (z_top - z_base)))
        else:
            return "symbol_local_extent_unknown"
    el["bbox_min_mm"] = [min(xs) - radius, min(ys) - radius, min(zs)]
    el["bbox_max_mm"] = [max(xs) + radius, max(ys) + radius, max(zs)]
    return ""


def _pipe_outer_mm(op: Mapping[str, Any],
                   ctx: "SnapshotSections | None") -> tuple[float | None, str]:
    """Declared NOMINAL SIZE -> outer diameter from the TYPE table.

    The nominal size by itself does not contain the body (DN100: 100 vs.
    114.3), and this module still does not convert it by any multiplier.
    The conversion is taken from the table the document itself printed; if
    there is no table or no row, the nominal size remains, and the closed
    table `hulls.DIAMETER_KIND` refuses in its own words.
    """
    nominal = _num(op.get("diameter_mm"))
    if nominal is None:
        return None, "pipe_diameter_not_declared"
    if ctx is None:
        return None, "no_snapshot"
    pool = _pool_for(str(op.get("op") or ""), "pipe_type", op)
    section = None if pool is None else ctx.section(pool, op.get("pipe_type"))
    if section is None:
        return None, ("pipe_type_not_in_snapshot"
                      if op.get("pipe_type") is not None
                      else "pipe_type_not_declared")
    if section.get("kind") != "nominal_table":
        return None, "pipe_type_has_no_size_table"
    outer = ctx.outer_for_nominal_mm(section, nominal)
    if outer is None:
        return None, "pipe_nominal_not_in_type_table"
    return outer, ""


@dataclass(frozen=True)
class BundleGeometry:
    """Everything the bundle managed to say about bodies, TOGETHER with what it could not."""

    elements: list[dict]
    #: An op that does not create a body at all (datum, annotation, edit) -> how many times.
    no_body: dict[str, int]
    #: Collisions of qualified op identifiers.
    collisions: int
    #: WHY an element has no geometry — by named reasons. An empty dictionary
    #: means "every element has geometry," not "we did not ask": the reason
    #: is recorded at the same instant as the skip.
    no_geometry: dict[str, int]
    #: Footprint outlines, keyed by `element_id`, shaped as input to `hulls.build_hull`.
    profiles: dict[str, dict]
    #: THE ROUNDING THIS MODULE INTRODUCED — as a number, per element.
    #: `{"z_mm": t}` means: the actual body is a slice of thickness t within
    #: the declared span 2t, and the program does not name the slice's
    #: position. Until this number is written out, a false positive produced
    #: by OUR OWN rounding is indistinguishable from a genuine finding
    #: (measured 09.08: 66 "critical" out of 99 on `snowdon_plumb_v5` — every
    #: single one from here).
    declaration_slack: dict[str, dict] = dataclasses_field(default_factory=dict)
    #: `element_id` -> the OP the element was born from. Without it, the
    #: finding's next move can only be invented: "move the pipe" without an
    #: op address is advice the author cannot act on.
    op_by_id: dict[str, Mapping[str, Any]] = dataclasses_field(
        default_factory=dict)
    #: THE HOST EDGE, resolved IN THE PROGRAM'S OWN WORDS:
    #: `element_id -> {"host_element_id", "host_ref", "host_class", "source"}`.
    #: Built by `clash_judgement.hosted_from_ops` and kept here so that
    #: judgement receives a READY-MADE edge instead of resolving references
    #: again next to the detector. An EMPTY dictionary means "we asked, no
    #: hosts were declared"; "we did not ask" cannot happen on this path —
    #: the bundle always exists.
    hosted: dict[str, dict[str, Any]] = dataclasses_field(default_factory=dict)
    #: Op identifiers that someone else in this bundle REFERS TO. Needed by
    #: the declaration duplicate: deleting what serves as another op's
    #: support is not allowed. An EMPTY set means "we asked, there are no
    #: references" — "we did not count" cannot happen on this path, the
    #: bundle is always read in full.
    referenced_op_ids: frozenset[str] = dataclasses_field(
        default_factory=frozenset)


#: The provenance of a claim: the PROGRAM'S TEXT, not a body and not a field
#: survey. It rides into the finding because "fix" based on a fact about the
#: text and "fix" based on a field survey in Revit are different claims,
#: even though they would carry the same stage.
DECLARATION_PROVENANCE = "declared-program-text/v1"


def _declaration_digest(element: Mapping[str, Any]) -> str:
    """Fingerprint of an element's DECLARATION: everything except the bundle address."""
    payload = {k: v for k, v in element.items()
               if k not in ("element_id", "declaration_digest")}
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def _referenced_op_ids(pack: Sequence[Any]) -> frozenset[str]:
    """Op identifiers that someone else in the bundle refers to."""
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            if value.get("by") == "ref" and isinstance(value.get("value"), str):
                found.add(value["value"])
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    for program in (pack or ()):
        ops = program.get("ops") if isinstance(program, Mapping) else program
        for op in (ops or ()):
            if isinstance(op, Mapping):
                walk({k: v for k, v in op.items() if k != "id"})
    return frozenset(found)


def declared_duplicates(geometry: BundleGeometry) -> list[dict[str, Any]]:
    """Pairs of elements declared BYTE-FOR-BYTE IDENTICAL, except for
    address.

    THIS IS A FACT ABOUT THE TEXT, AND IT IS DEFINED EXACTLY. There is no
    geometric coincidence of hulls here at all: no hull is built, no proof
    core is queried, there is nothing to round. The program said the same
    thing twice — either it did, or it did not.

    WHY THIS DOES NOT DUPLICATE `detect.exact_body_equality_proof`. That one
    answers a question about BODIES ("two hulls are one body") and requires
    the `exact` grade, which production sources do not yield — in its own
    words: «destructive duplicate advice remains unreachable there». The
    question here is different, and the ban from there does not apply to it.

    THE REFUSAL IS NAMED, NOT PASSED OVER IN SILENCE. A pair where one side
    is REFERENCED by another op stays `certain=False` with the reason
    `declaration_is_referenced`: deleting another op's support is not
    allowed, and "no references" differs from "references were not
    counted" — the latter is impossible on this path, the bundle is read in
    full.
    """
    by_digest: dict[str, list[dict[str, Any]]] = {}
    for el in geometry.elements:
        digest = el.get("declaration_digest")
        if digest:
            by_digest.setdefault(str(digest), []).append(el)

    out: list[dict[str, Any]] = []
    for digest, group in sorted(by_digest.items()):
        if len(group) < 2:
            continue
        pair = [str(group[0]["element_id"]), str(group[1]["element_id"])]
        op_ids = {
            str((geometry.op_by_id.get(el["element_id"]) or {}).get("id") or "")
            for el in group[:2]}
        referenced = sorted(op_ids & set(geometry.referenced_op_ids))
        row: dict[str, Any] = {
            "pair": pair,
            "declaration_digest": digest,
            "count": len(group),
            "provenance": DECLARATION_PROVENANCE,
            "certain": not referenced,
            "refused": "declaration_is_referenced" if referenced else None,
            "referenced_op_ids": referenced,
        }
        row["text_ru"] = (
            f"ОДИН И ТОТ ЖЕ ЭЛЕМЕНТ ОБЪЯВЛЕН ДВАЖДЫ: {pair[0]} и {pair[1]} — "
            f"объявления совпадают полностью (факт о ТЕКСТЕ программы, "
            f"происхождение `{DECLARATION_PROVENANCE}`, не обмер в Revit)"
            if not referenced else
            f"объявления {pair[0]} и {pair[1]} совпадают, но на "
            f"{', '.join(referenced)} ССЫЛАЮТСЯ другие операции — удалять "
            f"опору чужого опа нельзя")
        out.append(row)
    return out


def _with_program_levels(ctx: "SnapshotSections | None",
                         pack: "Sequence[Any]") -> "SnapshotSections | None":
    """Add the elevations the pack's own `create_level` ops declare.

    Returns `ctx` unchanged when the pack declares none. A pack with levels but
    NO snapshot still gets an index: "there is no document" and "the document
    says nothing about this level" are different facts, and a program that
    declares its own levels has answered the second one itself.
    """
    declared: dict[str, float] = {}
    for program in pack or ():
        ops = program.get("ops") if isinstance(program, Mapping) else None
        for op in ops or ():
            if not isinstance(op, Mapping) or op.get("op") != "create_level":
                continue
            elevation = _num(op.get("elev_mm"))
            if elevation is None:
                continue
            # Keyed exactly as `_sel_text` renders a selector, so the lookup
            # runs on what the program WROTE: `{by: ref, value: "L"}` reaches
            # the level as `ref:L`, `{by: name, …}` as `name:Этаж 1`. A second
            # key shape here would be a second selector resolution beside
            # ground's, which is what `SnapshotSections` exists to avoid.
            identifier, name = op.get("id"), op.get("name")
            for key in (f"ref:{identifier}" if isinstance(identifier, str) and identifier else None,
                        f"name:{name}" if isinstance(name, str) and name else None,
                        name if isinstance(name, str) and name else None):
                if key:
                    declared.setdefault(key, float(elevation))
    if not declared:
        return ctx
    if ctx is None:
        return SnapshotSections(levels=dict(declared), types={})
    merged = dict(declared)
    merged.update(ctx.levels)  # the document wins on a key collision
    return replace(ctx, levels=merged)


def bundle_elements(pack: Sequence[Any], *, snapshot: Any = None
                    ) -> BundleGeometry:
    """A bundle of programs -> L0-shape elements and the NAMED reasons for
    their bodilessness.

    Only READ numbers are placed here: the program's own numbers and TYPE
    geometry resolved by the ground stage against the LIVE document. No
    thickness is still guessed here; what changed is exactly that there is
    now something TO read. Where there is no snapshot, the behavior is the
    same letter for letter, and the reason is named `no_snapshot`, not
    silence.
    """
    ctx = SnapshotSections.from_snapshot(snapshot)
    # 🔴 A LEVEL THE PROGRAM ITSELF DECLARES IS A LEVEL (13.09.2026).
    # Elevations were read ONLY from the snapshot, so a wall standing on a
    # `create_level` of the same pack came back `level_elevation_unknown` and
    # got no body at all. Measured on one program with one difference — level
    # by `{by: ref}` versus by `{by: element_id}` — bodies 0 either way, and the
    # team rehearsal read that as "walls and columns are not materialised". They
    # are: `body_making_ops()` names 32 ops of 83 and both are in it. What was
    # missing is the number the geometry needs, and the program was carrying it
    # all along. The snapshot still WINS on a clash of keys: the document is the
    # authority on what already exists, and a program cannot redefine it.
    ctx = _with_program_levels(ctx, pack)
    elements: list[dict] = []
    no_body: dict[str, int] = {}
    no_geometry: dict[str, int] = {}
    profiles: dict[str, dict] = {}
    slack: dict[str, dict] = {}
    op_by_id: dict[str, Mapping[str, Any]] = {}
    seen: set[str] = set()
    collisions = 0

    def blame(reason: str) -> None:
        if reason:
            no_geometry[reason] = no_geometry.get(reason, 0) + 1

    def address(raw: str) -> str:
        nonlocal collisions
        sid = raw
        k = 2
        while sid in seen:
            collisions += 1
            sid = f"{raw}~{k}"
            k += 1
        seen.add(sid)
        return sid

    for index, program in enumerate(pack):
        position = index + 1
        ops = program.get("ops") if isinstance(program, Mapping) else program
        for op in _with_group_placements(ops):
            if not isinstance(op, Mapping):
                continue
            name = str(op.get("op") or "")
            oid = str(op.get("id") or f"#{len(elements)}")
            category = category_of(op)
            if category is None:
                no_body[name] = no_body.get(name, 0) + 1
                continue
            base = bundle_oid(position, oid)
            if name in _GRAPH_OPS:
                bodies = _graph_bodies(op)
                if not bodies:
                    blame(f"{name}_graph_has_no_readable_segment")
                    elements.append(_element(address(base), category, op))
                    continue
                param = SECTION_PARAM_BY_OP.get(name)
                for k, (a, b, dia) in enumerate(bodies, start=1):
                    el = _element(address(f"{base}{_SEGMENT_SEP}{k}"),
                                  category, op)
                    el["p0_mm"], el["p1_mm"] = a, b
                    if param and dia is not None:
                        el["params"] = {param: dia}
                    op_by_id[el["element_id"]] = op
                    elements.append(el)
                continue
            el = _element(address(base), category, op)
            op_by_id[el["element_id"]] = op
            profile: dict | None = None
            if name in _AXIS_OPS:
                p0, p1 = _pt3(op.get("p0_mm")), _pt3(op.get("p1_mm"))
                if p0 is not None and p1 is not None:
                    el["p0_mm"], el["p1_mm"] = p0, p1
                else:
                    blame("axis_missing")
                param = SECTION_PARAM_BY_OP.get(name)
                dia = _num(op.get("diameter_mm"))
                if param and dia is not None:
                    el["params"] = {param: dia}
                # PIPE: nominal size -> OUTER diameter from the TYPE table.
                # Written under the emitter parameter's NAME, so that the
                # package's closed table judges read fitness, not this
                # module.
                if name in ("create_pipe", "create_pipe_placeholder"):
                    outer, why = _pipe_outer_mm(op, ctx)
                    if outer is not None:
                        el.setdefault("params", {})[
                            "RBS_PIPE_OUTER_DIAMETER"] = outer
                    else:
                        blame(why)
                elif name == "create_cable_tray":
                    # THE SECTION IS NOW EXPRESSIBLE via the op's two
                    # operands, so the previous `section_not_expressible` has
                    # become false. But these numbers cannot be silently
                    # passed to `hulls`: the clash layer sees the program's
                    # declaration, not a post-commit readback, and there is
                    # still no physical containment certificate for a
                    # rectangular capsule around the axis. So both branches
                    # remain WITHOUT a hull, but name different next actions.
                    width = _num(op.get("width_mm"))
                    height = _num(op.get("height_mm"))
                    if (width is not None and width > 0
                            and height is not None and height > 0):
                        blame("create_cable_tray_geometry_not_certified")
                    else:
                        blame("create_cable_tray_section_not_declared")
                elif name == "create_conduit":
                    # A duct box still does not declare an outer section: a
                    # trade size cannot be turned into one without the
                    # document's size table. Its previous diagnosis does not
                    # change.
                    blame("create_conduit_section_not_expressible")
            elif name == "create_wall":
                blame(_wall_geometry(op, el, ctx))
            elif name in _SLAB_OPS:
                why, profile, z_ref = _slab_geometry(
                    op, el, ctx, _SLAB_OPS[name])
                blame(why)
                if profile is not None:
                    # THE ROUNDING IS NAMED AS A NUMBER EXACTLY WHERE IT IS
                    # INTRODUCED. `_slab_geometry` takes [z−t, z+t] instead of
                    # guessing the sign; so the actual slab is a slice of
                    # thickness t within the span 2t, and later this is
                    # exactly the magnitude by which the finding cannot be
                    # considered proven.
                    slack[el["element_id"]] = {
                        "z_mm": (el["z1_mm"] - el["z0_mm"]) / 2.0,
                        "z_ref_mm": z_ref,
                        #: The CONVENTION class for how the body grows from
                        #: the elevation. Not the direction (the snapshot
                        #: does not carry it — see open_model.__Section), but
                        #: the NAME of the convention: two ops of the same
                        #: class are read IDENTICALLY, and that is a fact
                        #: about the language, not about the construction. It
                        #: is exactly this that narrows the set of legitimate
                        #: readings.
                        "grow_class": name,
                        "why": "plate_z_doubling"}
            elif name in _SECTION_BBOX_OPS:
                blame(_section_bbox_geometry(op, el, ctx))
            elif name in _SOLID_OPS:
                blame(_solid_geometry(op, el, ctx))
            elif name == "create_stairs":
                blame(_stairs_geometry(op, el, ctx))
            elif name == "create_railing":
                blame(_railing_geometry(op, el, ctx))
            elif name in _FLEX_OPS:
                blame(_flex_geometry(op, el, ctx))
            elif name == "create_floor_by_contour":
                blame(_contour_slab_geometry(op, el, ctx))
            elif name == "create_extrusion_roof":
                blame(_extrusion_roof_geometry(op, el, ctx))
            elif name == "create_foundation":
                # THE SUBTYPE DECIDES, AND THE REFUSAL MUST NAME ITS OWN. A
                # mat foundation is `create_floor` under a different name
                # with the same input (`outline` as numbers, level, type),
                # so it follows the same path. An isolated footing declares
                # a POINT and a symbol, and the snapshot today does not
                # carry the symbol's bounding size — to say "no slab
                # outline" about this would mean naming someone else's
                # reason.
                if str(op.get("variety") or "") == "slab":
                    why, _profile, _z = _slab_geometry(op, el, ctx, "outline")
                    blame(why)
                else:
                    blame("foundation_isolated_symbol_extent_not_expressed")
            elif name == "create_directshape":
                box = _mesh_bbox(op.get("mesh"))
                if box is not None:
                    el["bbox_min_mm"], el["bbox_max_mm"] = box
                else:
                    blame("directshape_mesh_unreadable")
            else:
                # A LOCK AGAINST SILENCE. The op creates a physical element,
                # but none of the branches above said anything about its
                # body — meaning it will go into the census without a hull
                # and WITHOUT A REASON, which is exactly the outcome this
                # whole bookkeeping was set up to forbid. A new registry op
                # lands here instead of disappearing.
                blame(f"{name}_geometry_not_expressed")
            if profile is not None:
                profiles[el["element_id"]] = profile
            elements.append(el)
    # THE HOST EDGE IS BUILT HERE, NOT AT THE PAIR JUDGE. The reason is
    # exactly the same as why `declaration_slack` is also counted here:
    # resolving a reference is a fact about the BUNDLE (which `id` in which
    # program), and only whoever unpacked the bundle knows it. A second
    # reference resolver next to the judge would drift from this on the
    # very first addressing change — the way `bundle_oid` would drift too,
    # if the reader decided address qualification.
    hosted: dict[str, dict[str, Any]] = {}
    try:
        from kir import clash_judgement as _judgement

        hosted = _judgement.hosted_from_ops(op_by_id)
    except Exception:  # noqa: BLE001 — the judge did not come up: there are simply no edges
        logger.debug("hosted index build failed", exc_info=True)
    # THE DECLARATION FINGERPRINT IS A FACT ABOUT THE TEXT, NOT ABOUT BODIES
    # (11.08.2026). The bundle address (`p1/duct1`) is OUR bookkeeping, not
    # something the author said; were it to enter the fingerprint, "the same
    # thing said twice" would become inexpressible by construction.
    # Everything else in the element's content is the declaration.
    # 🔴 THE SHIFT HAPPENS BEFORE THE FINGERPRINT, NOT AFTER. The declaration
    # fingerprint is computed from the element's content; shifting it
    # afterward would give two copies at different heights ONE fingerprint,
    # and "the same thing said twice" would collapse into one.
    _apply_group_deltas(elements)
    for el in elements:
        el["declaration_digest"] = _declaration_digest(el)
    return BundleGeometry(elements, no_body, collisions, no_geometry, profiles,
                          slack, op_by_id, hosted,
                          referenced_op_ids=_referenced_op_ids(pack))


# ═════════════════════════════════════════════════════════════════════════
# 3. RUN
# ═════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class _Cached:
    key: str
    block: dict[str, Any]


#: A cache on the bundle's CANONICAL BYTES — the same technique as schema
#: lifting. The same input must cost once: a turn that re-asks the same
#: bundle (a replay, two doors of one turn) does not pay a second time.
#: Measured 09.08: 116 ms cold versus 0.28 ms warm.
#:
#: There is no lock and none is needed: the key is the sha256 of the bundle
#: itself, so a miss between two threads costs an extra computation but can
#: never hand back SOMEONE ELSE'S answer. Different sessions have different
#: bundles by construction.
_CACHE: list[_Cached] = []
_CACHE_MAX = 8


def _bundle_sha(pack: Sequence[Any]) -> str:
    payload = json.dumps(
        [[dict(op) for op in ((p.get("ops") if isinstance(p, Mapping) else p) or ())]
         for p in pack],
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sections_sha(snapshot: Any) -> str:
    """A fingerprint of exactly the part of the snapshot that changes
    bodies.

    Hashing the whole snapshot would cost more for no benefit: `unique_id`,
    `version_guid`, and instance counters do not affect the hull, and the
    `family_symbols` pool can run to thousands of lines.
    """
    index = SnapshotSections.from_snapshot(snapshot)
    if index is None:
        return "none"
    payload = json.dumps(
        {"levels": index.levels,
         "types": {pool: dict(rows) for pool, rows in index.types.items()}},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


#: INPUTS THAT CAN TURN AN ANSWER INTO A REFUSAL, AND THEREFORE MUST BE IN
#: THE CACHE KEY. The list lives HERE, next to the key, not in the author's
#: memory.
#:
#: THE THIRD CASE OF ONE DEFECT IN THIS MODULE IN A WEEK, and what they
#: share is not a topic but a SHAPE — A QUANTITY THAT DOES NOT COVER WHAT
#: CHANGES THE ANSWER:
#:   * a ceiling named "number of BODIES" that compared the number of
#:     ELEMENTS (it refused at 171 bodies out of 3,000 named);
#:   * a key without `new_from`: the same bundle with a different turn
#:     boundary — a different answer ("45 introduced" versus "0
#:     introduced");
#:   * a key without ceilings — this one. Measured 11.08: `MAX_PAIRS=8` ->
#:     `over_cap`, raised to 100,000 -> **the same `over_cap` from the
#:     cache**, cache cleared -> `ok, pairs 219`. And it strikes exactly
#:     where the answer is trusted most: the ceiling gets raised PRECISELY
#:     because the building refused.
#:
#: THE LOCK IS IN THE ABSENCE OF A DEFAULT. `tests/test_clash_cache_key`
#: requires that EVERY `_max_*` function of this module stand here; a fifth
#: added ceiling will fail the test, rather than one day hand the operator
#: someone else's answer.
ANSWER_INPUTS: tuple[tuple[str, Any], ...] = (
    ("max_elements", _max_elements),
    ("max_bodies", _max_bodies),
    ("max_offers", _max_offers),
    ("max_pairs", _max_pairs),
    # 🔴 THE SECOND-PASS BUDGET CHANGES THE NUMBER WITHIN A TURN, NOT THE
    # SPEED (F-047, 29.08.2026). The gap between the detector's raw vector
    # and the provably minimal separation is measured by the tree itself
    # (`clash_judgement`, 600 findings on `sob62_r23_v5`): median ×5.892,
    # p90 ×56.667, maximum ×112,066.5, and a value of `0` turns the pass off
    # entirely. So it was computed with a budget of 0 — and, after raising
    # it to 250, got THE SAME answer from the cache.
    #
    # This is the FOURTH case of one defect in this module, and it slipped
    # past the lock because it is not called `_max_*`: the lock guarded a
    # NAME MASK, not the KIND of quantity. An instrument that can be
    # bypassed by renaming guards nothing — so along with this line the
    # guard moved too (to reading the environment).
    ("proposal_budget_ms", _proposal_budget_ms),
)


def _cache_key(pack: Sequence[Any], snapshot: Any,
               new_from: int | None, existing_run: Any = None) -> str:
    """The cache key is a READABLE string, not one opaque fingerprint.

    WHY NOT A FULL SHA. Ceilings folded into a hash would become invisible,
    and the next person who adds a fifth one would not know it must be put
    there — that is, the lock would close today's case and let tomorrow's
    through. So SMALL inputs sit in the key as NAMES and values, and only
    what is large gets folded: a bundle can run to thousands of ops, a
    snapshot to thousands of pool lines, and keeping them in the key in
    full would mean paying memory for readability where it is not needed.

    `new_from=none` and `new_from=1` are DIFFERENT keys on purpose: the
    first means "the delta was not asked about" (basis `none`), the second
    means "the boundary is at the first program" (basis
    `whole_bundle_new`), and these are different answers.
    """
    parts = [f"bundle={_bundle_sha(pack)}",
             f"sections={_sections_sha(snapshot)}",
             f"new_from={'none' if new_from is None else int(new_from)}",
             # THE SOURCE OF THE EXISTING STOCK IS AN INPUT THAT CHANGES THE
             # ANSWER, so it belongs in the key. The same bundle against a
             # DIFFERENT building is a different answer, and handing back
             # the first would be the same lie as silence. The key holds
             # the source's NAME, not its content: the on-disk decompile is
             # immutable by construction (a new read is a new directory).
             f"existing={'none' if existing_run is None else str(existing_run)}",
             # 🔴 THE IDENTITY OF THE TURN'S DOCUMENT (F-046, 29.08.2026).
             # `existing_run` is resolved LATER than this point — `_report`
             # computes the key, and only seventy lines further down calls
             # `resolve_run(...)` FROM EXACTLY THESE THREE VALUES. So
             # `existing=none` in the key means "not yet asked," not "no
             # source," and the entire existing-stock context never entered
             # the key at all.
             #
             # Measured on two decompiles of one corpus (a bundle of 6
             # ducts, identical to the byte): document A gave 9 bodies, 33
             # pairs; document B got the SAME 9 and 33 FROM THE CACHE, while
             # its own actual answer was 13 bodies, 57 pairs. Four bodies
             # and twenty-four pairs of a different building vanished,
             # replaced by its neighbor's answer.
             #
             # The three values sit as NAMES, not folded into a hash: that
             # was already decided in this function's header — what is
             # folded becomes invisible, and the next person who adds a
             # value will not know it must be placed here. Hashing the
             # whole snapshot is also not allowed: that was explicitly
             # rejected by the author of `_sections_sha` and remains true.
             #
             # EMPTY and EMPTY give ONE key on purpose. `_live_project_uid`
             # declares: empty is a fact about OUR OWN reading, not about
             # the building, and "absence never turns into 'the identity
             # did not match.'" The key holds the same law: two turns
             # without a fingerprint are equally unknown, separating them
             # would mean inventing a distinction. The cost of this
             # decision is named: such turns keep sharing the cache, and
             # the hole can only be closed by making the fingerprint
             # mandatory — and that is a decision for the OWNER, not the
             # smith.
             f"doc={turn_document_title()}",
             f"project_uid={_live_project_uid(snapshot)}",
             f"revit_version={_live_revit_version(snapshot)}"]
    parts += [f"{name}={reader()}" for name, reader in ANSWER_INPUTS]
    return "|".join(parts)


def _cache_get(key: str) -> dict[str, Any] | None:
    for item in _CACHE:
        if item.key == key:
            return dict(item.block)
    return None


def _cache_put(key: str, block: dict[str, Any]) -> None:
    _CACHE.append(_Cached(key, dict(block)))
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.pop(0)


def bundle_clash_report(pack: Sequence[Any], *, snapshot: Any = None,
                        new_from: int | None = None,
                        existing_run: Any = None
                        ) -> dict[str, Any] | None:
    """A bundle of programs -> the clash section of the receipt. NEVER
    raises.

    `snapshot` — the open-model snapshot of the same session (`ground`).
    Without it, behavior is unchanged letter for letter: bodies are built
    only from the program's own numbers, and "thickness lives in the type"
    remains a named hole. With it, declared walls, slabs, and columns GAIN
    a body.

    `None` is returned in EXACTLY one case — the flag is off. Everything
    else, including a ceiling overflow and an internal failure, is
    returned as text: silence reads as "no clashes," and that is the most
    expensive lie possible.
    """
    if not clash_enabled():
        return None
    try:
        return _report(pack, snapshot=snapshot, new_from=new_from,
                       existing_run=existing_run)
    except Exception as exc:  # noqa: BLE001 — the receipt must not cost a turn
        logger.debug("bundle clash check failed", exc_info=True)
        # 🔴 THE FAILURE LOCATION IS PRINTED IN THE RECEIPT ITSELF, NOT
        # ONLY IN `debug`. Found live on 20.08.2026: the receipt said
        # «NameError: name 'snapshot_file_exists' is not defined» — and
        # that was all. The service runs with `--log-level info`, so the
        # sole carrier of the frame (`logger.debug`) is written NOWHERE,
        # and a static search across the tree gives zero: the name is
        # bound everywhere it is written. A refusal that names the kind of
        # error and omits the location costs one more live run — exactly
        # what this receipt was supposed to avoid.
        import traceback as _tb
        frames = _tb.extract_tb(exc.__traceback__)
        where = ""
        if frames:
            last = frames[-1]
            # 🔴 IT USED TO BE `_Path(__file__).parents[2]` — counting
            # STEPS UPWARD from the MODULE, that is, tied to how deep the
            # module sits inside the package. After the split it gave
            # `/opt`, and the prefix was not trimmed: the receipt printed
            # the full path instead of the short one. The anchor is now
            # taken from where THE PACKAGE ITSELF sits (`kir.__file__`) —
            # the layout changes, this does not (fixed in `f518b05`). The
            # module can move into a subpackage — the answer will not
            # change.
            import kir as _kir
            root = str(_Path(_kir.__file__).resolve().parent.parent) + "/"
            where = (f" [{str(last.filename).replace(root, '')}:{last.lineno}"
                     f" в {last.name}: {(last.line or '').strip()[:120]}]")
        return {
            "schema": BUNDLE_CLASH_SCHEMA,
            "status": "unavailable",
            "message_ru": (
                f"ПРОВЕРКА НА КОЛЛИЗИИ НЕ ВЫПОЛНЕНА: "
                f"{type(exc).__name__}: {exc}{where}. Это НЕ «коллизий нет» — "
                f"это «не смотрели»."),
        }


def _over_cap(key: str, snap: Any, phase: str, work: int, cap: int,
              seconds: float) -> dict[str, Any]:
    """A ceiling overflow is a NAMED refusal, not a silent zero findings."""
    block = {
        "schema": BUNDLE_CLASH_SCHEMA,
        "status": "over_cap",
        "phase": phase,
        "bodies": len(snap.records),
        "work": work,
        "cap": cap,
        "message_ru": (
            f"ПРОВЕРКА НА КОЛЛИЗИИ НЕ СЧИТАЛАСЬ: тел {len(snap.records)}, и "
            f"они стоят так плотно, что {phase} стоит {work} пар при потолке "
            f"хода {cap} (≈{seconds:.1f} с). Это НЕ «коллизий нет» — это «не "
            f"смотрели». Спроси проверку по интересующей части здания "
            f"отдельной пачкой."),
    }
    _cache_put(key, block)
    return block


#: THE DOMAIN IN WHICH THE DELTA IS DEFINED AT ALL, AND THAT IS A LIMIT,
#: NOT A SETTING. The search contains ONLY what the session declared.
#: Existing geometry of the document NEVER enters it:
#: `open_model.prune_ground_snapshot` leaves level elevations and TYPE
#: sections — not one instance, not one bounding size (measured
#: 11.08.2026). So a clash with someone else's wall that stood in the
#: document before the session is, here, not "not found" but INVISIBLE,
#: and staying silent about it is not allowed at any delta.
DELTA_SCOPE = "declared_only"

#: THE RULE BY WHICH `introduced` IS COUNTED — IN WORDS AND IN THE
#: PAYLOAD, not in a code comment.
#:
#: WHY THIS IS MANDATORY. Adding `both_new + one_new` is a JUDGEMENT, not
#: a measurement: a pair with one new side would not have existed at all
#: without this turn — but the opposite reading ("the new element merely
#: DISCOVERED an already-existing condition") is defensible, and choosing
#: for the reader silently means making a choice the reader does not see.
#: This tree's law for such a case is not written here (`ground.py`,
#: named defaults): a choice the caller does not see is a
#: `.FirstOrDefault()` with a better reputation.
#:
#: So the number stays SINGLE — the engineer needs one, otherwise he will
#: add it himself and worse — but the rule and both addends separately
#: ride alongside it. THE RULE ITSELF — IN ONE PHRASE, and it rides in
#: EVERY answer.
#:
#: HOW THIS CASE DIFFERS FROM `why` AND `action_ru`, whose text was
#: replaced by a pointer. Those repeated WITHIN one answer — five lines of
#: one value — and a pointer to the same answer's table removed the
#: repetition without hiding anything. This field rides ONCE per answer:
#: an outward pointer would remove not the repetition but the very
#: VISIBILITY the field was set up for, that is, it would put the rule
#: back into a comment — where the caller does not see it.
#:
#: So what was shortened is not the field but its CONTENT: 362 characters
#: were carrying the rule TOGETHER WITH ITS DEFENSE (measured 11.08: 4.2%
#: of the block on `snowdon_plumb_v4`, 8.4% on `sob62_r23_v5`). The reader
#: needs the rule; the defense sits alongside it under a name.
INTRODUCED_RULE_RU = (
    "внесённой считается пара, у которой новой является ХОТЯ БЫ ОДНА сторона "
    "(защита выбора — `clash_bundle.INTRODUCED_RULE_WHY`; слагаемые "
    "раздельно — `by_origin`)")

#: THE DEFENSE OF THE CHOICE — SITS ONCE AND IS NAMED, not deleted. A
#: choice the caller does not see is a `.FirstOrDefault()` with a better
#: reputation; the RULE in the answer is what makes it visible, and a
#: reader who wants to argue with it comes here.
INTRODUCED_RULE_WHY = (
    "Сложение `both_new + one_new` есть СУЖДЕНИЕ, а не замер. За «хотя бы "
    "одну сторону» говорит то, что без этого хода такой пары не существовало "
    "бы вовсе. Обратное прочтение — «новый элемент лишь ОБНАРУЖИЛ уже "
    "существовавшее условие, а виновата сторона, стоявшая раньше» — защитимо "
    "и в части случаев верно. Разрешить спор замером нечем: какая из сторон "
    "«виновата», программа не выражает. Поэтому итог считается одним "
    "правилом, правило названо в ответе, а ОБА слагаемых публикуются "
    "раздельно (`by_origin`), чтобы читатель, считающий иначе, имел материал "
    "для своего счёта, а не только мой итог.")

#: THE CEILING ON THE RULE ITSELF. Not decoration: the field has already
#: once grown from a phrase into an essay and become the block's third
#: heaviest key. The number is held by a test, so that the next added
#: qualifier is FORCED into a decision — carry it off into the defense —
#: instead of quietly settling into every answer again.
INTRODUCED_RULE_CAP = 160


def _new_ids(elements: Sequence[Mapping[str, Any]],
             new_from: int | None) -> frozenset[str] | None:
    """Addresses of bodies declared by THIS turn, or `None` — no boundary
    was named.

    The boundary arrives as a POSITION NUMBER IN THE BUNDLE, not a
    journal `seq`: the caller hands the bundle in here, and only it knows
    which position corresponds to which record after head eviction. The
    translation is done by `verdict.clash_only`, which has the journal at
    hand; here the position is already computed.
    """
    if new_from is None:
        return None
    out: set[str] = set()
    for el in elements:
        sid = str(el.get("element_id") or "")
        head, sep, _ = sid.partition(_BUNDLE_SEP)
        if not sep or not head.startswith("p"):
            continue
        try:
            position = int(head[1:])
        except ValueError:
            continue
        if position >= new_from:
            out.add(sid)
    return frozenset(out)


def _row_for_receipt(row: dict[str, Any], rules: Mapping[str, str],
                     rung_actions: Mapping[str, str]) -> dict[str, Any]:
    """A judgement line -> a RECEIPT line: without what the block already
    carries.

    WHAT THIS FIXES (measured 11.08.2026, `snowdon_plumb_v4`,
    serialization without spaces): the block is 9,931 characters, of
    which `findings` is 5,586 (56%), and the receipt's own text is 2,586
    (26%). Inside `findings`'s five lines:

        why        975 (195 per line) — ONE line per RULE
        action_ru  815 (163 per line) — ONE line per STAGE

    Of the five `why` values, one is DIFFERENT among them: 772 characters
    out of 975 are pure repetition. And the same text already sits in the
    block ONCE, in `rules`.

    THIS IS A BROKEN OLD RULE, NOT A NEW ONE.
    `clash_judgement.Judged.why_ru` states it verbatim — "there is one
    justification per rule, and findings under it can number eighty:
    printing it on every line would drown the findings in it too." The
    text followed it; the payload did not.

    THE FIELD DOES NOT DISAPPEAR AND DOES NOT GO EMPTY. A silent
    disappearance is worse than deletion: the reader would get a
    `KeyError` at best and `None` at worst. Instead of the text, a
    POINTER rides to the place in the block where it sits once.

    THE COMPRESSION LIVES HERE, NOT IN `Judged.as_dict`. The pair judge
    is a pure function with a public shape, and its line must be
    self-contained: whoever calls `judge` directly has no block nearby.
    Saving on repetition is the RECEIPT's concern, and it is settled
    where the tables are already assembled.
    """
    out = dict(row)
    rule_id = str(out.get("rule_id") or "")
    if rule_id and str(out.get("why") or "") == str(rules.get(rule_id) or ""):
        out["why"] = f"см. rules[{rule_id}]"
    rung = str(out.get("rung") or "")
    if rung and str(out.get("action_ru") or "") == str(
            rung_actions.get(rung) or ""):
        out["action_ru"] = f"см. rung_actions[{rung}]"
    return out


def _blind_by_class(geometry: "BundleGeometry") -> dict[str, int]:
    """Reasons for bodilessness -> a count BY CLASS, including ops with no
    element.

    `never_a_body` is counted from `no_body` (the op did not create an
    element at all), the rest from `no_geometry` (the element exists,
    there is no body). They cannot be added into one number: for the
    first there is nothing to be a body, for the second the body exists
    in reality and we simply lack it.

    A reason with no class does NOT DISAPPEAR: it goes out under the key
    `unclassified`, so that a hole in the table is visible in the report,
    not only in the test.
    """
    out: dict[str, int] = {}
    if geometry.no_body:
        out["never_a_body"] = sum(geometry.no_body.values())
    for reason, count in geometry.no_geometry.items():
        name = blind_class(reason) or "unclassified"
        out[name] = out.get(name, 0) + count
    return dict(sorted(out.items()))


def _report(pack: Sequence[Any], *, snapshot: Any = None,
            new_from: int | None = None,
            existing_run: Any = None) -> dict[str, Any]:
    from kir.clash import detect as _detect
    from kir.clash import review as _review
    from kir import clash_judgement as _judgement

    # The cache key is computed from the bundle AND the snapshot: the
    # same bundle against a DIFFERENT document is a different answer, and
    # handing back the first would be a lie of the same kind as silence.
    # THE KEY IS ASSEMBLED IN ONE PLACE AND COVERS EVERY INPUT CAPABLE OF
    # TURNING THE ANSWER INTO A REFUSAL — see `ANSWER_INPUTS` and
    # `_cache_key`.
    # It used to be assembled here across three branches, and ceilings
    # never entered it at all: whoever raised a ceiling got the same
    # refusal back from the cache.
    key = _cache_key(pack, snapshot, new_from, existing_run)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    started = time.perf_counter()
    geometry = bundle_elements(pack, snapshot=snapshot)
    elements = geometry.elements
    no_body = geometry.no_body
    collisions = geometry.collisions
    # THE FIRST CHECKPOINT IS BY ELEMENTS, and it names ELEMENTS. It
    # holds the linear cost of decompiling the bundle; the ceiling on
    # BODIES sits lower, AFTER the snapshot, and measures bodies. On why
    # there are two axes — see `_max_elements`.
    cap = _max_elements()
    if len(elements) > cap:
        block = {
            "schema": BUNDLE_CLASH_SCHEMA,
            "status": "over_cap",
            "phase": "разбор пачки",
            "elements": len(elements),
            "cap": cap,
            "message_ru": (
                f"ПРОВЕРКА НА КОЛЛИЗИИ НЕ СЧИТАЛАСЬ: элементов в пачке "
                f"{len(elements)} при потолке хода {cap}. Это НЕ «коллизий "
                f"нет» — это «не смотрели»."),
        }
        _cache_put(key, block)
        return block

    from kir.clash import snapshot as _snapshot

    origin = {
        "source": "kir-program-bundle",
        "run_dir": "пачка программ сессии",
        "assertion": "self_reported",
        "programs": len(pack),
        # THE BUNDLE'S FINGERPRINT, NOT THE CACHE KEY. `key` used to
        # stand here, and that was wrong BEFORE this wave too: with a
        # snapshot, the key was a sha of sha+sections, meaning the field
        # named `bundle_sha256` was not holding the bundle's fingerprint.
        # The readable-key wave made the discrepancy visible (the
        # ceiling values would have ridden into the field too), but did
        # not create it. Provenance must name exactly what it names:
        # this is the BUNDLE's fingerprint, and by it a finding is
        # checked against the program, not against the cache.
        "bundle_sha256": _bundle_sha(pack),
        "type_sections": "read" if snapshot is not None else "absent",
    }
    snap = _snapshot.build_from_elements(
        elements, origin=origin, profiles=geometry.profiles)

    # ═════ WHAT ALREADY STANDS IN THE DOCUMENT — THE SECOND SIDE OF THE PAIR ═════
    # Before this wave the bundle was compared AGAINST ITSELF, and its
    # own receipt named this: "a clash with someone else's wall is not
    # 'not found' but INVISIBLE." The domain is taken AFTER the bundle's
    # bodies are assembled, because it is exactly the bounding size of
    # those bodies; the reverse order would be a guess about where the
    # bundle will end up.
    #
    # The checkpoints for bodies/offers/pairs stand LOWER on purpose: the
    # existing stock enters them on equal footing with the bundle,
    # otherwise a domain that swept up half the building would go around
    # the ceiling that exists precisely for that.
    from kir.clash import existing as _existing

    region = _existing.Region.around(snap.records)
    # THE SOURCE IS RESOLVED HERE, NOT DEMANDED FROM THE CALLER. A
    # parameter that no one passes is a capability without a door; that
    # is exactly how `sdk.py` lay unreachable for five weeks. An explicit
    # `existing_run` remains (an admin door, tests) and OVERRIDES the
    # resolution.
    resolved_freshness = None
    if existing_run is None:
        # THE LIVE DOCUMENT'S IDENTITY IS TAKEN RIGHT HERE, FROM THE
        # GROUND SNAPSHOT. By the same argument as the paragraph above: a
        # parameter that no one passes is a capability without a door.
        # The snapshot ALREADY carries `__document_fingerprint`
        # (`open_model.py:870,1908`), and its `project_uid` is the very
        # Revit field that the decompile writes into the passport. From
        # here `serving` has nothing to ask for: it has already given
        # everything needed.
        existing_run, why, resolved_freshness = _existing.resolve_run(
            turn_document_title(),
            project_uid=_live_project_uid(snapshot),
            revit_version=_live_revit_version(snapshot))
        if existing_run is None:
            standing = _existing.Existing.absent(why)
        else:
            standing = _existing.load(existing_run, region,
                                      doc_name=turn_document_title(),
                                      freshness=resolved_freshness)
    else:
        standing = _existing.load(existing_run, region,
                                  doc_name=str(origin.get("doc_name") or ""))
    pair_filter = _detect.any_physical_pair_filter
    if standing.present and standing.elements:
        origin = dict(origin)
        origin["existing_source"] = standing.source
        snap = _snapshot.build_from_elements(
            list(elements) + list(standing.elements),
            origin=origin, profiles=geometry.profiles)
        pair_filter = _detect.bundle_vs_document_pair_filter
    bundle_bodies = sum(1 for r in snap.records
                        if not _existing.is_existing(r.source_id))
    standing_bodies = len(snap.records) - bundle_bodies
    # THE SECOND CHECKPOINT IS BY BODIES, AND NOW IT ACTUALLY COUNTS
    # THEM. It stands AFTER the snapshot on purpose: before that, bodies
    # do not exist yet, and counting them by elements is exactly the
    # "signing someone else's axis" this checkpoint used to suffer from
    # (the measurement and numbers are in `_max_elements`). The snapshot
    # costs 174 ms on 16,257 elements, meaning the cost of knowing the
    # true number of bodies is lower than the cost of getting it wrong.
    if len(snap.records) > _max_bodies():
        return _over_cap(key, snap, "сборка тел", len(snap.records),
                         _max_bodies(),
                         len(snap.records) * _US_PER_OFFER / 1e6)
    # THE THIRD CHECKPOINT IS BY PAIRS, AND IT IS FREE. The grid is
    # built by the same `build_grid` that `detect` will use to build it
    # (the same defaults: cell edge from the median bounding size,
    # slack=0), and the upper estimate of the number of pairs is taken
    # straight from its own layout: the sum of C(k,2) over cells plus
    # giants-against-all. Measured: the estimate itself is 0.01 ms on
    # 320 bodies, the grid is 3 ms. `detect` further down will build the
    # grid again, and that is a deliberate cost: 3-20 ms so that the
    # decision "compute or refuse" is made BEFORE the narrow phase,
    # which alone costs seconds.
    grid = _detect.build_grid(snap.records)
    offers = sum(len(m) * (len(m) - 1) // 2 for m in grid.buckets.values())
    offers += len(grid.oversized) * len(snap.records)
    if offers > _max_offers():
        return _over_cap(
            key, snap, "широкая фаза", offers, _max_offers(),
            offers * _US_PER_OFFER / 1e6)
    # THE FOURTH CHECKPOINT IS BY ACTUAL CANDIDATES. The estimate above
    # can be generous by an order of magnitude (a plausible layout:
    # 136,892 offers -> 960 candidates), and refusing based on it would
    # mean refusing a sound building. The actual number costs one broad
    # phase, already bounded by the previous checkpoint; `detect` further
    # down will build it AGAIN, and this double cost is named here as a
    # number, not hidden: it is exactly the price of having the decision
    # "compute or refuse" made BEFORE the narrow phase.
    cands = _detect.candidate_pairs(
        snap.records, grid, pair_filter=pair_filter)
    if len(cands) > _max_pairs():
        return _over_cap(
            key, snap, "узкая фаза", len(cands), _max_pairs(),
            len(cands) * _MS_PER_PAIR / 1e3)
    report = _detect.detect(snap, pair_filter=pair_filter)
    view = _review.build_review(report, top=_TOP, max_elements=0)

    # ═════ THE JUDGEMENT LAYER ═════
    # The detector returns PAIRS; the designer needs JUDGEMENTS. Measured
    # 09.08 on `snowdon_plumb_v5`: of 99 pairs, 66 stood at the top
    # stage, and all 66 were slabs of one floor disputing only in OUR OWN
    # rounding. The layer lives as a separate module and recomputes
    # NOTHING in the package's geometry.
    # TURN BOUNDARY -> BODY ADDRESSES. The position in the bundle is
    # already baked into the address (`p<N>/<id>`), so a second "what is
    # new" bookkeeping is not set up.
    new_ids = _new_ids(elements, new_from)
    # TWO DOORS — TWO DIFFERENT ANSWERS, AND THEY CANNOT BE NAMED WITH
    # ONE WORD. The chat door has a "before": what the session declared
    # in earlier turns. The session's first turn has NO PREDECESSOR AT
    # ALL — the reassembly materializer builds the building from
    # scratch, and "0 introduced" there would be exactly the opposite.
    # So the boundary at the first program is named separately.
    delta_basis = ("none" if new_from is None
                   else ("whole_bundle_new" if new_from <= 1
                         else "session_turn"))
    judgement = _judgement.judge(
        report["findings"], new_ids=new_ids,
        hulls={rec.source_id: rec for rec in snap.records},
        profiles=geometry.profiles, slack=geometry.declaration_slack,
        ops=geometry.op_by_id,
        # THE INDEX IS ALWAYS PASSED, even when empty. Empty means "we
        # asked, no hosts were declared," absent means "we did not ask";
        # on this path the latter never happens, and substituting the
        # former with the latter would mean printing `unknown` where an
        # answer exists.
        hosted=geometry.hosted,
        # THE SECOND PASS: the detector's raw vector -> the minimal
        # separation. Computed AFTER sorting and only while the budget
        # lasts, because the cost depends on neighborhood density, not
        # on the number of findings.
        propose_budget_ms=_proposal_budget_ms())
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    census = report["census"]
    completeness = report["search"]["completeness"]
    summary = view["summary"]
    # TABLES ARE ASSEMBLED BEFORE LINES: a line refers to them, it does
    # not copy them. Like `rules`, the stage table carries ONLY what
    # triggered — printing all five would mean bringing back the same
    # cost from the other side.
    shown = judgement.judged[:_TOP]
    rung_actions = {row.rung: _judgement._RUNG_ACTION[row.rung]
                    for row in shown}
    findings = [_row_for_receipt(row.as_dict(), judgement.justifications,
                                 rung_actions)
                for row in shown]
    totals = census["totals"]
    block: dict[str, Any] = {
        "schema": BUNDLE_CLASH_SCHEMA,
        "status": "ok",
        "scope_id": report["search"]["scope_id"],
        "assertion": "self_reported",
        # WHAT WAS COMPARED AGAINST — WITHOUT THIS FIELD, ZERO FINDINGS
        # MEAN NOTHING. `present: false` with a reason and `present:
        # true` with zero bodies in the domain are DIFFERENT facts: the
        # first is "did not look," the second is "looked, the domain is
        # empty." Merging them into an empty list would mean bringing
        # back exactly the green result without the act of distinction
        # this wave was made for.
        "compared_against": standing.to_dict(),
        # THE PAIR COUNT — BY FORMULA FROM TWO KNOWN CARDINALITIES, not
        # by a reduction over classes: the reduction is legitimate only
        # for filters that decide by `(label, mvp_side)`, while this one
        # decides by SOURCE, and `detect` honestly returns
        # `eligible_pairs=None` for it with a named reason. `None`, read
        # as zero, has already once produced "zero next to 58,280
        # findings," so here stands the exact number.
        "pairs_compared": _existing.pairs_compared(
            bundle_bodies, standing_bodies),
        "bodies_bundle": bundle_bodies,
        "bodies_existing": standing_bodies,
        "bodies": report["search"]["hulls"],
        "elements_considered": totals["eligible"],
        # THE FULL DENOMINATOR, not just the MVP side: a door without a
        # hull is also a hole in the search, even though it does not
        # enter MVP pairs.
        "without_body": totals["eligible"] - totals["hulled"],
        "without_body_on_mvp_side": completeness["without_hull_on_mvp_side"],
        "search_complete": completeness["complete"],
        "without_body_by_category": {
            cat: row["missing_geometry"] + row["unsupported"]
            for cat, row in census["by_category"].items()
            if row["missing_geometry"] or row["unsupported"]},
        "ops_without_body": dict(sorted(no_body.items())),
        # WHY THE ELEMENT HAS NO GEOMETRY — IN WORDS. Without this, "0
        # bodies" and "the type's section did not read" look identical,
        # yet are fixed in different places: one by the op's operand, the
        # other by the snapshot.
        "no_geometry_reasons": dict(sorted(geometry.no_geometry.items())),
        # FIVE REASONS, NOT ONE NUMBER. "The author did not declare it,"
        # "only the live document knows," "the op does not express a
        # body," "someone else's lock refused," and "the op does not
        # create a body" are fixed in FIVE different places; a flat list
        # of reasons forced the reader to classify them himself, and he
        # will not do that — he will decide nothing was seen at all.
        "blind_by_class": _blind_by_class(geometry),
        "type_sections": "read" if snapshot is not None else "absent",
        "op_id_collisions": collisions,
        "total_findings": summary["total"],
        "duplicates": summary["duplicates"],
        "overlaps": summary["overlaps"],
        "touches": summary["touches"],
        # THREE DIFFERENT NUMBERS, AND THEY DO NOT ADD INTO ONE. A pair
        # removed BY A RULE, a pair that was NEVER SEEN AT ALL (the
        # element has no body), and a "contradiction" are three different
        # facts; one number instead of three lies twice.
        "judgement_schema": _judgement.JUDGEMENT_SCHEMA,
        # WHAT THIS TURN INTRODUCED — as a number separate from what is
        # in the building. Measured 11.08: on the last reassembly chunk
        # of `snowdon_plumb_v4`, 45 pairs, and the turn introduced NOT A
        # SINGLE ONE. One number for both questions always answers the
        # one that was not asked.
        "delta_basis": delta_basis,
        "delta_scope": DELTA_SCOPE,
        "by_origin": judgement.by_origin,
        "disputes": len(judgement.actionable),
        "filtered": sum(judgement.filtered_by_rule.values()),
        "unjudged": sum(judgement.refused_by_rule.values()),
        "filtered_by_rule": judgement.filtered_by_rule,
        "refused_by_rule": judgement.refused_by_rule,
        "filtered_by_slack": judgement.filtered_by_slack,
        # THE HOST EDGE — AS FOUR DIFFERENT NUMBERS, AND THEY DO NOT ADD
        # UP. "The host confirmed," "a DIFFERENT host was declared," "no
        # host was declared," and "there was no index" are four different
        # facts; one number instead of four lies three times over, and
        # the second lies the most expensively, because it is exactly the
        # finding that a label-based guess used to remove in silence.
        "by_host_state": judgement.by_host_state,
        "hosted_edges": len(geometry.hosted),
        # THE JUSTIFICATIONS OF THE RULES THAT FIRED TODAY — in full and
        # as data. A rule that removed a pair without saying why is
        # silent filtering, exactly what this wave forbids.
        "rules": judgement.justifications,
        # THE STAGE'S ACTION — ONE LINE PER STAGE, not a copy in every
        # finding. The same decision as for `rules`, and for the same
        # reason: measured 11.08 — 815 characters out of 5,586 in
        # `findings` were five copies of two lines. A finding's stage is
        # named by the `rung` field, and that is the key.
        "rung_actions": dict(sorted(rung_actions.items())),
        "by_kind": judgement.by_kind,
        "by_rung": judgement.by_rung,
        "findings": findings,
        "elapsed_ms": round(elapsed_ms, 1),
    }
    if new_ids is not None:
        # "Introduced" IS COMPUTED, not derived by the reader:
        # `both_new + one_new`. A pair with one new side is also a
        # contribution of the turn: without it, the pair would not have
        # existed at all. The key is ABSENT when no boundary was named:
        # "0 introduced" and "not asked" are different answers.
        block["introduced"] = (judgement.by_origin.get("both_new", 0)
                               + judgement.by_origin.get("one_new", 0))
        # THE NUMBER DOES NOT TRAVEL WITHOUT ITS RULE. The key appears
        # and disappears TOGETHER with `introduced`: a rule without a
        # number is decoration, a number without a rule is that very
        # invisible choice.
        block["introduced_rule"] = INTRODUCED_RULE_RU
    block["message_ru"], block["text_budget"] = _render(block, report)
    # THE COST OF THE PAYLOAD — AS A NUMBER, AND IN THE ANSWER ITSELF.
    # The text is bounded by a ceiling, while the block around it was
    # bounded by nothing: measured 11.08 — the text is 2,586 characters
    # inside a block of 9,931, meaning the budget was only guarding a
    # quarter of the cost.
    #
    # NO CEILING IS SET HERE, and that is the same decision as for
    # `_TEXT_CAP`: no one has measured how much the model ACTUALLY pays
    # for these characters, and assigning a number instead of measuring
    # is exactly what is forbidden here. What is locked is a STRUCTURAL
    # invariant (a line does not repeat the block's table), which needs
    # no number, and the value itself rides outward so drift is visible
    # in production, not only in a test.
    block["text_budget"]["payload_chars"] = len(json.dumps(
        block, ensure_ascii=False, separators=(",", ":"), default=str))
    _cache_put(key, block)
    return block


# ═════════════════════════════════════════════════════════════════════════
# 4. TEXT THAT THE MODEL READS
# ═════════════════════════════════════════════════════════════════════════

#: THE CEILING ON JUSTIFICATION IN THE TEXT. Rule justifications sit in
#: full in the payload's `rules`, and printing them in the text a SECOND
#: time is paying context twice for one thing. Measured 11.08: one
#: justification costs 317 characters, and a receipt can carry two (a
#: removed rule plus a refused one), that is 634 out of 2,700 — almost
#: two judgements. What remains here is a LEAD-IN sufficient to
#: recognize the rule, and a reader who wants to argue with it goes to
#: the data.
_WHY_IN_TEXT = 170


def _why_brief(text: str) -> str:
    """Justification -> a lead-in for the text. A cutoff is NAMED, not silent."""
    text = str(text or "")
    if len(text) <= _WHY_IN_TEXT:
        return text
    return text[:_WHY_IN_TEXT].rsplit(" ", 1)[0] + "… (целиком в `rules`)"


def render_bundle_clash(block: Mapping[str, Any],
                        report: Mapping[str, Any]) -> str:
    """Block -> receipt lines. The public signature is unchanged: text only."""
    return _render(block, report)[0]


def _findings_in(lines: "list[str]") -> int:
    """How many JUDGEMENTS are in these lines — one answer to one question.

    A finding has two lines: `[LOOK]` and its `TURN`. As long as the
    truncation text and the payload counted this separately, they
    drifted apart twofold and called different things by the one word
    "shown." Both sides ask HERE now, so they can no longer drift apart;
    and if a finding ever grows a third line, exactly one place needs to
    change.
    """
    return len([line for line in lines if line.startswith("  [")])


def _render(block: Mapping[str, Any], report: Mapping[str, Any]
            ) -> tuple[str, dict[str, int]]:
    """Block -> receipt lines. THE DENOMINATOR BEFORE THE ASSERTION: first
    how many bodies took part at all, and only then the findings. "0
    findings" without the body count is an assertion about nothing, and
    it reads as "all clear."

    ONLY THE MIDDLE IS TRUNCATED. The text ceiling cuts the LIST OF
    FINDINGS, not the completeness accounting: before this wave, the
    truncation went from the tail, and "WITHOUT A BODY" was the first
    under the knife — exactly what the receipt has no right to be
    missing.
    """
    bodies = block["bodies"]
    # THREE NUMBERS IN ONE LINE AND NOT A SINGLE ADDITION.
    # "Contradiction," "removed by a rule," and "not seen" answer three
    # different questions, and gluing them into "N findings" means
    # losing exactly the fact that costs the most: not seen.
    head = [
        f"КОЛЛИЗИИ (ЗАЯВЛЕНО, не построено): тел в поиске {bodies}, "
        f"пар {block['total_findings']} — СПОРОВ {block.get('disputes', 0)}, "
        f"снято правилом {block.get('filtered', 0)}, "
        f"без суждения {block.get('unjudged', 0)}, "
        f"без тела (НЕ ВИДЕЛИ) {block['without_body']}"
    ]
    # THE FIRST LINE — THE ANSWER TO THE QUESTION ASKED. The engineer in
    # front of the button is not asking "how many clashes are in the
    # building" but "what did I introduce." Measured 11.08 on the
    # reassembly of `snowdon_plumb_v4`: 45 pairs, 0 introduced by the
    # turn — and before this line the two figures looked like one.
    basis = str(block.get("delta_basis") or "none")
    if basis != "none":
        origins = block.get("by_origin") or {}
        prior = int(origins.get("both_prior", 0))
        whole = basis == "whole_bundle_new"
        head.append(
            f"ВНЕСЛА ЭТА ПАЧКА: {block.get('introduced', 0)} из "
            f"{block['total_findings']} — правило «новой хотя бы одна "
            f"сторона» ({origins.get('both_new', 0)}+"
            f"{origins.get('one_new', 0)}, см. `introduced_rule`); СТОЯЛО ДО "
            f"НЕЁ: {prior}"
            + (" — у первой пачки предшественника нет, новым считается ВСЁ"
               if whole else " — не работа этой пачки"))
    body: list[str] = []
    for row in block["findings"]:
        body.append(f"  [{row.get('rung_name', '')}] {row['text']}")
        move = str(row.get("next_move") or "")
        if move:
            body.append(f"      ХОД: {move}")
    rest = block["total_findings"] - len(block["findings"])
    if rest > 0:
        body.append(f"  … ещё {rest}")
    lines: list[str] = []
    why_of = block.get("rules") or {}

    def _ranked(counts: Mapping[str, int]) -> list[tuple[str, int]]:
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    by_rule = block.get("filtered_by_rule") or {}
    if by_rule:
        # NOTHING IN SILENCE. A rule that removed a pair must name
        # itself: a pair removed in silence and a pair never found are
        # indistinguishable in the receipt. The justification is printed
        # for the day's MAIN rule — once for all its findings, not as a
        # copy in every line.
        ranked = _ranked(by_rule)
        lines.append("СНЯТО ПРАВИЛОМ: " + ", ".join(
            f"{name} ×{count}" for name, count in ranked))
        top_why = why_of.get(ranked[0][0])
        if top_why:
            lines.append(
                f"  ПОЧЕМУ `{ranked[0][0]}`: {_why_brief(top_why)}")
    # THE HOST — AS A LINE, AND ONLY WHEN IT SAYS SOMETHING. Exactly
    # `contradicts` is printed: the state in which a pair LOOKS like a
    # node by labels ("a door and a wall — of course a node"), while the
    # author's declaration says the opposite. `absent` and `unknown` do
    # not go into the text — they are a property of the QUERY, not of
    # the building, and live as a number in `by_host_state`.
    host_states = block.get("by_host_state") or {}
    contradicts = int(host_states.get("contradicts") or 0)
    if contradicts:
        lines.append(
            f"ХОЗЯИН ОБЪЯВЛЕН ДРУГОЙ (пар: {contradicts}): у этих пар автор "
            f"САМ назвал хозяина, и это не вторая сторона находки — "
            f"перекрытие с элементом, внутри которого элемент не живёт. "
            f"Такая пара НЕ снимается: снять её значило бы принять догадку "
            f"по паре ярлыков вместо заявления автора. Подтверждено хозяином "
            f"и снято: {int(host_states.get('confirms') or 0)}; рёбер хозяина "
            f"в пачке: {block.get('hosted_edges', 0)}.")
    outside = int(host_states.get("host_out_of_scope") or 0)
    if outside:
        # THE READING BOUNDARY IS NAMED AS A SEPARATE LINE AND NEVER
        # BLAMES THE AUTHOR. Measured across the corpus: `snowdon_elec_v1`
        # has 959 such edges out of 1,001, and all of them lead into a
        # linked file. A line that blames the author 959 times for
        # someone else's boundary is a report the reader will throw away
        # together with the genuine findings.
        lines.append(
            f"ХОЗЯИН ЗА ГРАНИЦЕЙ ИЗВЛЕЧЕНИЯ (пар: {outside}): разбор называет "
            f"хозяина, которого мы не извлекали — связанный файл либо датум. "
            f"Про вмещение у этих пар сказать НЕЧЕГО; это не ошибка автора и "
            f"не оправдание паре.")
    refused = block.get("refused_by_rule") or {}
    if refused:
        # "NO RULE" — A SEPARATE LINE, AND ALWAYS WITH A JUSTIFICATION.
        # This is neither a finding nor silence: it is a list of what the
        # DECLARATION is missing for the pair to be judged at all.
        # Inventing a rule is cheaper than admitting it — and that is why
        # the admission is printed in full.
        ranked_refused = _ranked(refused)
        lines.append("БЕЗ СУЖДЕНИЯ, ПРАВИЛО ОТКАЗАНО: " + ", ".join(
            f"`{name}` ×{count}" for name, count in ranked_refused))
        # THE JUSTIFICATION IS SINGLE, ON THE DAY'S MAIN RULE, by the
        # same technique as the removed rules a line above. It used to be
        # printed as a copy for EVERY refused rule (344 characters per
        # line), meaning it grew without a ceiling and crowded out
        # findings — and findings are exactly what the receipt is read
        # for. The remaining justifications sit in full in `rules`.
        top_refused = why_of.get(ranked_refused[0][0])
        if top_refused:
            lines.append(
                f"  ПОЧЕМУ `{ranked_refused[0][0]}`: "
                f"{_why_brief(top_refused)}")

    if not bodies:
        lines.append(
            "НИ ОДНОГО ТЕЛА: программа не выражает ни одной оболочки, поиск "
            "не состоялся вовсе. Это НЕ «коллизий нет».")
    if block["without_body"]:
        by_cat = block["without_body_by_category"]
        who = ", ".join(f"{cat} {n}" for cat, n in sorted(by_cat.items())[:6])
        # A REASON, NOT JUST A NUMBER. "Thickness lives in the type"
        # stopped being the only answer on the day the snapshot began
        # carrying it: now the receipt must distinguish "did not ask the
        # document," "asked, the type does not have it," and "the op does
        # not express a size at all."
        why = block.get("no_geometry_reasons") or {}
        top = ", ".join(f"{name} ×{count}" for name, count
                        in sorted(why.items(), key=lambda kv: (-kv[1], kv[0]))[:4])
        tail = (
            "снапшот открытой модели этой проверке НЕ передан, поэтому "
            "толщины и сечения ТИПОВ не читались вовсе"
            if block.get("type_sections") != "read" else
            "геометрия типов прочитана, и у этих элементов её всё равно "
            "не хватило")
        # RAW REASONS ARE DELIBERATELY REMOVED FROM THE TEXT: they sit in
        # full in `no_geometry_reasons`, and their place in the text is
        # taken by CLASSES — the same fact, but answering the question
        # "where to fix this." Two lines on one topic cost 521 characters
        # out of 2,000 non-removable ones (measured 11.08).
        classes = block.get("blind_by_class") or {}
        by_class = "; ".join(
            f"{BLIND_CLASS_RU.get(name, name).split(':')[0]} {count}"
            for name, count in sorted(classes.items(),
                                      key=lambda kv: (-kv[1], kv[0])))
        lines.append(
            f"БЕЗ ТЕЛА (НЕ ВИДЕЛИ): {block['without_body']}"
            + (f" — {who}" if who else "")
            + (f". ПОЧЕМУ: {by_class}" if by_class else "")
            + ". Пропущены ПО ПОСТРОЕНИЮ, а не по порогу.")
        # FIVE CLASSES AS A SEPARATE LINE. The number "without a body"
        # answers five questions at once and therefore none of them: "the
        # author did not declare it" is fixed by the author on the next
        # turn, "the live document knows" is fixed by the ground stage,
        # "the op does not express a body" is not fixed at all. A reader
        # given one number will read it as "the instrument is blind" and
        # throw away the whole report.

    walls_hulled = ((report.get("census") or {}).get("by_category", {})
                    .get("OST_Walls", {}).get("hulled", 0))
    if walls_hulled:
        lines.append(
            "СТЫКИ СТЕН ВНЕ ПРОВЕРКИ: в углах примыкания Revit достраивает "
            "материал за концами объявленной оси, и программа его не "
            "выражает — оболочка стены его не содержит.")
    nominal = (report.get("census") or {}).get("sections", {})
    if nominal.get("nominal_only_total"):
        lines.append(
            f"ТОЛЬКО НОМИНАЛ: {nominal['nominal_only_total']} — капсула по "
            f"номиналу тела не содержит (ДУ100: 100 против 114.3), оболочки "
            f"нет.")
    blind = [f"{name} ×{n} ({_BLIND_OPS[name]})"
             for name, n in sorted(block["ops_without_body"].items())
             if name in _BLIND_OPS]
    if blind:
        lines.append("ВНЕ ПРОВЕРКИ, И ЭТО МОЖЕТ ПРЯТАТЬ КОЛЛИЗИЮ: "
                     + ", ".join(blind[:4]))
    # THE DELTA LIMIT IS ALWAYS NAMED, not only when it was asked about:
    # "0 introduced" without this line reads as "and nothing in the
    # document was clashed against," and the check does not know that
    # and cannot know it.
    # THE DOMAIN LIMIT IS ALWAYS NAMED, AND IN DIFFERENT WORDS. Before
    # the existing-stock wave, one phrase stood here for all cases; now
    # there are three, because there are three facts: "did not look,"
    # "looked, the domain is empty," "looked, here is what against." One
    # phrase for three facts is the same merging of outcomes that this
    # module forbids in the census.
    against = block.get("compared_against") or {}
    if not against.get("present"):
        lines.append(
            "НЕ ВИДИТ СТОЯЩЕЕ: сравнивали только объявленное сессией "
            f"({against.get('reason') or 'источник не задан'}) — столкновение "
            "с чужой стеной не «не найдено», а НЕВИДИМО.")
    else:
        region = against.get("region") or {}
        lines.append(
            f"СРАВНИВАЛИ СО СТОЯЩИМ: разбор `{against.get('source')}`, "
            f"{against.get('bodies', 0)} тел в области из "
            f"{against.get('scanned', 0)} прочитанных, пар "
            f"{block.get('pairs_compared', 0)}. Область — габарит новых тел, "
            f"запас {region.get('margin_mm', 0)} мм: перекрытие и касание "
            "требуют пересечения габаритов, поэтому вне её находка невозможна. "
            "Отношение «рядом» против стоящего НЕ публикуется — иначе в "
            "находки уехало бы всё здание.")
        if against.get("without_bbox"):
            lines.append(
                f"У {against['without_bbox']} записей разбора габарита нет "
                "вовсе — они вне сравнения, и это не «не бьются».")
        # FRESHNESS IS ALWAYS PRINTED WHEN THE SOURCE IS RESOLVED BY US.
        # A finding taken from a week-old decompile is a comparison
        # against a PAST building, and staying silent about it is not
        # allowed: the same class as "a stale catalog gives KIR-G101, not
        # a silent build."
        fresh = against.get("freshness") or {}
        if fresh and not fresh.get("proven"):
            age = fresh.get("age_days")
            # 🔴 TWO DIFFERENT WORST CASES, AND BEFORE 20.08 ONLY ONE WAS
            # PRINTED. "A past state of THE SAME document" and "possibly A
            # DIFFERENT document" demand different actions from the
            # reader: the first is "check against the model," the second
            # is "this report cannot be trusted at all." The old text
            # named only the first, while the corpus says the second: 54
            # decompiles across 11 unique names, 94% sit in the group of
            # same-named ones, 49 of 54 are same-named and WITHOUT an
            # identity.
            drift = str(fresh.get("version_drift") or "")
            lines.append(
                "🔴 ИСТОЧНИК СТОЯЩЕГО НЕ ДОКАЗАН: "
                + (f"разбору {age} сут; " if age is not None else "")
                + f"совпало только {fresh.get('matched_by')} — "
                + str(fresh.get("why") or "")
                + ". Находки ниже сняты с ПРОШЛОГО состояния документа: "
                  "элемент, снесённый или подвинутый после разбора, здесь "
                  "по-прежнему стоит.")
            if drift:
                lines.append(
                    f"🔴🔴 И ЭТО МОЖЕТ БЫТЬ ВООБЩЕ ДРУГОЙ ДОКУМЕНТ: разбор "
                    f"снят в Ревите {drift.split(' -> ')[0]}, живой документ "
                    f"открыт в {drift.split(' -> ')[-1]}. Апгрейд это "
                    f"объясняет; совпадение ХОДОВОГО имени — нет. Пока не "
                    f"сверено вручную, находки ниже читать как ГИПОТЕЗУ, а "
                    f"их отсутствие — не как «чисто».")
    lines.append(
        f"область `{block['scope_id']}` (ВСЕ физические пары), судит "
        f"`{block.get('judgement_schema', '')}`. СВИДЕТЕЛЬСТВО, не отказ.")
    # THE MIDDLE IS SACRIFICED FIRST. The head (three numbers) and the
    # tail (completeness) must always be in the receipt; the list of
    # findings is what can be asked for again, so it is what gets cut.
    fixed = len("\n".join(head + lines)) + 1
    room = max(0, _TEXT_CAP - fixed)
    kept: list[str] = []
    used = 0
    for index, line in enumerate(body):
        # THE FIRST JUDGEMENT ALWAYS GETS THROUGH, together with its
        # TURN. "3 CONTRADICTIONS" without a single shown line is a
        # report the reader must throw away, and a discarded report is
        # worse than no report at all.
        if index >= 2 and used + len(line) + 1 > room:
            # WE COUNT JUDGEMENTS, NOT LINES, AND WITH ONE AND THE SAME
            # FUNCTION AS THE PAYLOAD. `len(kept)` used to stand here:
            # `kept` accumulates LINES, and each finding has two of them
            # (`[LOOK]` and its `TURN`), so for three shown judgements
            # the text wrote "6 shown" — twice as many, silently, and in
            # exactly the field the reader uses to decide whether to ask
            # for the rest. The payload in this very same receipt
            # counted correctly, so one receipt was calling two
            # different quantities by one name.
            kept.append(
                f"  … список суждений обрезан, показано {_findings_in(kept)}")
            break
        kept.append(line)
        used += len(line) + 1
    # THE BUDGET IS RETURNED AS A NUMBER FROM THE VERY PLACE IT IS
    # COMPUTED. A second calculation of "how much the non-removable part
    # took" next to the test would drift from this on the very first new
    # line, and a lock that measures something other than what is
    # growing is worse than no lock at all.
    budget = {"fixed": fixed, "cap": _TEXT_CAP, "room": room,
              "shown": _findings_in(kept),
              "of": _findings_in(body)}
    return "\n".join(head + kept + lines), budget
