"""§18.2 — the shared contract of a side stage (the "receipt law").

Every side extractor (curve / curtain / sketch / family_placement /
group) answers the SAME way: ``rows + failures``, both keys mandatory. Any
budget, timeout, unparsable row, or unrecognized response shape must leave
behind a ``{element_id, typed_reason}`` record. One bad row is isolated into
a receipt carrying the element's id — the run stays alive.

Why this is a separate module and not a fifth copy of the same thing
----------------------------------------------------------------------
``curve_extract`` established this discipline first and kept it LOCAL
(``CurveFailureReason`` with two values). ``curtain_extract`` copied it
verbatim. ``sketch_extract`` took only the shape (``ProfileFailure`` with no
typed reason), while ``family_placement_extract`` and ``group_extract`` took
nothing at all: they dropped the element silently — a ``break`` on budget,
a ``continue`` on an unsuitable class, an empty ``catch {}``.

THE MEASUREMENT of 28.07 (SOB6.2_FAS_R23, ``backend/data/decompile/sob62_fas_r23_v2``),
for whose sake the module was written:

    stage             requested   rows    receipts    NO TRACE
    curve                  1178    1178           0           0
    curtain                1178    1178         983           0
    sketch                   55      55           5           0
    family_placement       1799    1557           0         242

All 242 are ``OST_CurtainWallPanels``; in the lift they became
``placement_kind_unknown`` atoms with the text "element is absent from the
family placement side index". From the outside this is indistinguishable
from "the compiler cannot handle panels", even though the extractor actually
dropped them. The difference between "we cannot" and "we did not look" is
exactly the subject of this law.

The invariant the stage checks
-------------------------------
COVERAGE is checked, not an arithmetic sum: every requested id must be
either among the rows or among the receipts. For curve / family_placement /
group the rows and receipts do not overlap, and coverage is identically
``|rows| + |failures| == |requested|``. For sketch and curtain this is not
so by construction: an element gets a ROW (even if with
``profile_available=False``) plus diagnostic receipts on top — one for each
unread flight of a stair. There the sum is larger than the number requested,
and demanding equality would forbid the extractor from stating a reason more
than once. A lost id is caught by coverage the same way in both cases, and
that is exactly what the check exists for.
"""
from __future__ import annotations

import json
from kir.emit_utils import cs_string_literal
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence


class SideStageContractError(ValueError):
    """A side stage broke the §18.2 contract (a lost id, a broken shape)."""


class SideFailureReason(str, Enum):
    """A closed dictionary of typed cut reasons.

    The values ``time_budget_exceeded`` / ``call_budget_exhausted`` match
    the previously established ``CurveFailureReason`` /
    ``CurtainFailureReason`` VERBATIM: the same reason must carry one name
    across all five indexes, or the reason breakdown in the passport would
    lump different rows together as different phenomena.
    """

    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"
    # The requested id was not found IN THE DOCUMENT within one bounded pass
    # of the collector (the model may have changed, the id may have come
    # from a different decompile). The measurement that narrowed the reason
    # to this row: for `snowdon_elec_v1`, 1,837 such refusals came with 20
    # rows from a FOREIGN document (`dependencies.py`) — meaning "came from
    # outside" is a real sense and must stay distinguishable.
    ELEMENT_UNRESOLVED = "element_unresolved"
    # The stage REQUESTED the id, none of its collectors picked it up, and
    # the element IS PRESENT IN L0 of this very run. This is the boundary of
    # the stage's REACH, not an absence from the document. Established
    # 12.08.2026 after `sketch_extract`'s general catch sent
    # `element_unresolved` for 172 `OST_StairsRailing`, all 172 of 172 found
    # in L0 (control: 8 of 8 real ids found, 0 of 5 made-up ones). Two
    # readers drew OPPOSITE conclusions from this code, each correct
    # relative to its own source: the contract declared "not in the
    # document", the producer wrote "I don't read this". It was the
    # AUTHORITY and the PRODUCER that diverged, not two careless people.
    # The cure takes the same shape as HOST_KIND_UNRESOLVED below: the
    # reason is split, the old code REMAINS declared for the sake of
    # artifacts captured before the split, and new decompiles do not write
    # it at this spot.
    ELEMENT_NOT_CLAIMED = "element_not_claimed"
    # The element was found, but it is not the class this stage reads
    # (a panel-wall in a curtain wall is not a FamilyInstance). An HONEST
    # fact about the model, not a failure: these are exactly the 242 rows
    # that used to be lost silently.
    ELEMENT_KIND_MISMATCH = "element_kind_mismatch"
    # Reading the element raised an exception inside the bridge.
    READ_FAILED = "read_failed"
    # The response row failed the strict parser — isolated.
    ROW_UNPARSABLE = "row_unparsable"
    # mirrored == hand XOR facing did not hold. NOT fatal to the run: see
    # family_placement_extract on mirroring by an arbitrary plane.
    MIRROR_INVARIANT_VIOLATED = "mirror_invariant_violated"
    # The bridge's response arrived in a shape the contract does not know.
    PAYLOAD_SHAPE_UNRECOGNIZED = "payload_shape_unrecognized"
    # ── Below: reasons introduced by the "a refusal must have a reason" wave. ──
    #
    # The stage LOOKED AT the element, and the aspect it indexes is simply
    # absent from it: a wall has no CurtainGrid, an element has no profile.
    # No compiler can do anything here — there is nothing to do.
    ASPECT_NOT_PRESENT = "aspect_not_present"
    # The host is not identified, BUT the emitter merged two different cases
    # into one row ("element not found" and "found, but the wrong class").
    # The reason states exactly what is known: which of the two is unknown.
    # New decompiles do not write it (the emitter has been split); it
    # remains for the sake of artifacts captured before the split.
    HOST_KIND_UNRESOLVED = "host_kind_unresolved"
    # The aspect is present, but there is more than one address host (two
    # grids on one curtain wall): any single address would be a guess. A
    # limitation of OUR addressing, not a fact about the model.
    ADDRESS_AMBIGUOUS = "address_ambiguous"
    # The contour was read, but its topology is outside what the side
    # schema can handle (a disconnected/nested outer contour).
    PROFILE_TOPOLOGY_UNSUPPORTED = "profile_topology_unsupported"
    # AN ISLAND INSIDE A HOLE: a loop lying inside another hole-loop is
    # MATERIAL, not a void. Established 20.08.2026, and not as a reserve.
    #
    # Before it, such a profile did not refuse AT ALL: the `_classify_loops`
    # check requires every non-primary loop to lie inside the OUTER one, and
    # an island inside a hole SATISFIES that condition — and got recorded as
    # a second hole. That is, a solid slab got a void in its place, silently
    # and with `ok`. Verified by construction: a 200x200 contour, a 60x60
    # hole, a 20x20 island — "PASSED, 2 holes".
    #
    # A separate reason, not PROFILE_TOPOLOGY_UNSUPPORTED, because the cure
    # is OPPOSITE: disconnected footprints in one element may be an honest
    # atom forever, while an island is an extension of the loop contract.
    # One code for two outcomes leaves the reader to interpret a distinction
    # the code never carried.
    #
    # Across the corpus (67 decompiles, 686 profiles with holes, 358 with
    # two or more) islands number ZERO: the branch exists, the incident has
    # not.
    PROFILE_ISLAND_IN_HOLE = "profile_island_in_hole"
    # The host has no single reliable closed contour.
    PROFILE_NOT_SINGLE_CLOSED = "profile_not_single_closed"
    # There is more than one dependent sketch, and nothing to pick the single one by.
    DEPENDENT_SKETCH_AMBIGUOUS = "dependent_sketch_ambiguous"
    # ── The TAGS wave (30.07). ──────────────────────────────────────────────
    #
    # A tag REFERENCES another element, and the reference cannot always be
    # recovered: a tag on an element of a LINKED file gives an empty
    # ``GetTaggedLocalElementIds()`` (2022+) / ``InvalidElementId`` in
    # ``TaggedLocalElementId`` (2021); an orphaned tag looks the same.
    #
    # A separate reason is needed because none of the earlier ones tell the
    # truth: ``ELEMENT_UNRESOLVED`` is about the REQUESTED id (the tag
    # itself was found just fine), ``ASPECT_NOT_PRESENT`` is about a missing
    # aspect (the tag's target DOES EXIST, it is just not in this document).
    # The worst thing that could be done here is bind the tag to a similar
    # element of our own file: that would pass the L1 schema and look like
    # coverage.
    #
    # Class CUT, not DETERMINATION: our ``target`` addresses an element OF
    # THIS document, so the limitation is ours, not a fact about the model.
    # The dictionary is deliberately self-critical (see SideFailureKind),
    # and a disputed case is placed in the cut.
    TAG_TARGET_NOT_LOCAL = "tag_target_not_local"

    # ── The DIMENSIONS wave. ──────────────────────────────────────────────
    #
    # THE MEASUREMENT for whose sake these reasons were established
    # (k2_ar_rd_v8, a re-lift with the current lift): 13,905 dimensions =
    # 13,905 source_contract_gap atoms, that is, every single one. There was
    # no stage at all, while the create_dimension op has been in the
    # registry since 28.07.
    #
    # A dimension is LINKED to references (``Dimension.References`` ->
    # ``ReferenceArray``, its type measured by the compiler on
    # 2021/2023/2026, living in RevitAPI.dll — none of the `System.dll`
    # trap that killed the tags stage on 04.08 is here). A reference may
    # point to an element of a LINKED file, or to something not addressable
    # in this document at all: then there is nothing to assemble the op's
    # ``refs`` from. Class CUT, not DETERMINATION, by the same rule as
    # ``TAG_TARGET_NOT_LOCAL``: our ``refs`` addresses elements OF THIS
    # document, so the limitation is OURS.
    DIMENSION_REF_NOT_LOCAL = "dimension_ref_not_local"
    # A point ON THE dimension's LINE could not be read: ``Dimension.Origin``
    # did not answer and ``Dimension.Curve`` gave no start. Without a point
    # the ``line_at`` op cannot be assembled, and substituting any point
    # would mean making up a source.
    #
    # A SEPARATE REASON, NOT ``ASPECT_NOT_PRESENT``: a dimension HAS a line
    # by definition (it is drawn by it), so this is OUR failure to read it,
    # not a fact about the model. Class CUT.
    DIMENSION_LINE_UNREADABLE = "dimension_line_unreadable"


class SideFailureKind(str, Enum):
    """The receipt's class: "we did not look closely" versus "we looked, the aspect is absent".

    The split was introduced because without it ONE number named two
    different phenomena, and the larger of the two was not what it was
    taken for.

    THE MEASUREMENT of 29.07 (13A-RD-AR-K2_v33, 55,293 elements,
    ``backend/data/decompile/k2_ar_rd_v6``), for whose sake the class was
    established: ``side_failures_by_stage.curtain`` showed 14,343 — the
    largest mass of decompile failures. Of these, 14,324 are ordinary walls
    with no CurtainGrid, and EACH of them has, besides the receipt, an index
    row too (``curtain_available: false``). That is, the stage handled them
    cleanly, and the number was read as "curtain walls unhandled on 14
    thousand elements".

    ``CUT`` — we did not look closely enough: budget, exception, an
    unparsed row, an unrecognized response shape, plus OUR OWN limitations
    of addressing and schema. Everything that is on us belongs here; the
    class is deliberately self-critical, and in a disputed case the reason
    goes here.

    ``DETERMINATION`` — we looked, and the element does not have this
    aspect. Exactly two reasons land here: the aspect is absent entirely,
    and the element is of a different class than the stage reads. Both are
    facts about the model, not about the compiler.
    """

    CUT = "cut"
    DETERMINATION = "determination"


#: The class of every reason. The dictionary is COMPLETE by construction: the
#: test ``test_every_reason_is_classified`` fails on any new
#: ``SideFailureReason`` member that was not added here — otherwise the
#: first unclassified reason would silently drop out of both sums.
SIDE_FAILURE_KINDS: dict["SideFailureReason", SideFailureKind] = {
    SideFailureReason.TIME_BUDGET_EXCEEDED: SideFailureKind.CUT,
    SideFailureReason.CALL_BUDGET_EXHAUSTED: SideFailureKind.CUT,
    SideFailureReason.ELEMENT_UNRESOLVED: SideFailureKind.CUT,
    SideFailureReason.ELEMENT_NOT_CLAIMED: SideFailureKind.CUT,
    SideFailureReason.READ_FAILED: SideFailureKind.CUT,
    SideFailureReason.ROW_UNPARSABLE: SideFailureKind.CUT,
    SideFailureReason.MIRROR_INVARIANT_VIOLATED: SideFailureKind.CUT,
    SideFailureReason.PAYLOAD_SHAPE_UNRECOGNIZED: SideFailureKind.CUT,
    SideFailureReason.HOST_KIND_UNRESOLVED: SideFailureKind.CUT,
    SideFailureReason.ADDRESS_AMBIGUOUS: SideFailureKind.CUT,
    SideFailureReason.PROFILE_TOPOLOGY_UNSUPPORTED: SideFailureKind.CUT,
    # A CUT, not a determination: an island is real MATERIAL of the building,
    # and it is OUR loop schema, not Revit, that cannot express it. Recording
    # it as a determination would mean declaring our shortcoming a property
    # of the model and steering it out of the passport.
    SideFailureReason.PROFILE_ISLAND_IN_HOLE: SideFailureKind.CUT,
    SideFailureReason.PROFILE_NOT_SINGLE_CLOSED: SideFailureKind.CUT,
    SideFailureReason.DEPENDENT_SKETCH_AMBIGUOUS: SideFailureKind.CUT,
    SideFailureReason.TAG_TARGET_NOT_LOCAL: SideFailureKind.CUT,
    SideFailureReason.DIMENSION_REF_NOT_LOCAL: SideFailureKind.CUT,
    SideFailureReason.DIMENSION_LINE_UNREADABLE: SideFailureKind.CUT,
    # Both reasons below are facts about the model. ``ELEMENT_KIND_MISMATCH``
    # moved here from the cuts: its own docstring called it an "HONEST fact
    # about the model, not a failure" from the very start, yet it was counted
    # together with the cuts.
    SideFailureReason.ASPECT_NOT_PRESENT: SideFailureKind.DETERMINATION,
    SideFailureReason.ELEMENT_KIND_MISMATCH: SideFailureKind.DETERMINATION,
}


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SideStageContractError(f"{field_name} must be a non-empty string")
    return value


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SideStageContractError(
            f"{field_name} must be a non-negative integer")
    return value


def element_id_key(value: str) -> tuple[int, int | str, str]:
    """A numeric id sorts as a number; any other id sorts lexicographically."""
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


@dataclass(frozen=True, slots=True)
class SideFailure:
    """One receipt: an element the stage could not speak of in a row.

    The shape deliberately matches ``CurveFailure``/``CurtainFailure`` —
    ``{element_id, reason}`` plus an optional ``{typed_reason, elapsed_ms}``
    pair. ``elapsed_ms`` stays optional even with a typed reason: a cut by
    element class has no meaningful time, and requiring one would force the
    emitter to make up a number.
    """

    element_id: str
    reason: str
    typed_reason: SideFailureReason | None = None
    elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "SideFailure.element_id")
        _string(self.reason, "SideFailure.reason")
        if self.typed_reason is None:
            if self.elapsed_ms is not None:
                raise SideStageContractError(
                    "SideFailure.elapsed_ms requires a typed reason")
        else:
            if not isinstance(self.typed_reason, SideFailureReason):
                raise SideStageContractError(
                    "SideFailure.typed_reason must be a SideFailureReason")
            if self.elapsed_ms is not None:
                _nonnegative_int(self.elapsed_ms, "SideFailure.elapsed_ms")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "element_id": self.element_id,
            "reason": self.reason,
        }
        if self.typed_reason is not None:
            result["typed_reason"] = self.typed_reason.value
            result["elapsed_ms"] = self.elapsed_ms
        return result

    @classmethod
    def from_dict(cls, value: Any, field_name: str) -> "SideFailure":
        if not isinstance(value, Mapping):
            raise SideStageContractError(f"{field_name} must be an object")
        row = dict(value)
        allowed = {"element_id", "reason", "typed_reason", "elapsed_ms"}
        extra = sorted(set(row) - allowed)
        if extra:
            raise SideStageContractError(
                f"{field_name} unexpected fields: {', '.join(extra)}")
        typed: SideFailureReason | None = None
        raw_typed = row.get("typed_reason")
        if raw_typed is not None:
            try:
                typed = SideFailureReason(raw_typed)
            except (TypeError, ValueError) as exc:
                raise SideStageContractError(
                    f"{field_name}.typed_reason is unsupported") from exc
        elapsed = row.get("elapsed_ms")
        if elapsed is not None:
            _nonnegative_int(elapsed, f"{field_name}.elapsed_ms")
        return cls(
            element_id=_string(
                row.get("element_id"), f"{field_name}.element_id"),
            reason=_string(row.get("reason"), f"{field_name}.reason"),
            typed_reason=typed,
            elapsed_ms=elapsed,
        )


def sorted_failures(
    failures: Iterable[SideFailure],
) -> tuple[SideFailure, ...]:
    """A deterministic order for receipts (I4: the artifact is byte-stable)."""
    return tuple(sorted(
        failures,
        key=lambda item: (element_id_key(item.element_id), item.reason)))


def _named_id(item: Any) -> str | None:
    for attribute in ("element_id", "wall_id"):
        value = getattr(item, attribute, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(item, Mapping):
        for key in ("element_id", "wall_id"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def failure_element_id(failure: Any) -> str | None:
    """The element id from a receipt of ANY of the five indexes.

    ``CurtainFailure`` calls its field ``wall_id`` (the curtain wall index
    knows only walls). Renaming it would mean changing the shape of
    artifacts already recorded for the reader's sake of uniformity — the
    reader is cheaper to adapt.
    """
    return _named_id(failure)


def record_element_id(record: Any) -> str | None:
    """The element id from an index ROW — the same naming inconsistency as in receipts.

    ``CurtainWallRecord.wall_id`` is neither a typo nor legacy: the curtain
    wall index describes walls and nothing else, and the field is named for
    what it holds. The stage's reconciliation must be able to read both
    names, or it will declare every successfully read curtain wall lost.
    """
    return _named_id(record)


def failure_typed_reason(failure: Any) -> str | None:
    """The receipt's typed reason, if it has one.

    ``.value`` is taken ALWAYS, not only for non-strings: all three reason
    Enums are ``str`` enums, and ``isinstance(value, str)`` is true for
    them. An "if not a string" check let them pass through and printed
    ``SideFailureReason.TIME_BUDGET_EXCEEDED`` in the passport instead of
    ``time_budget_exceeded``.
    """
    value = getattr(failure, "typed_reason", None)
    if value is None and isinstance(failure, Mapping):
        value = failure.get("typed_reason")
    if value is None:
        return None
    resolved = getattr(value, "value", value)
    return resolved if isinstance(resolved, str) else str(resolved)


#: Reasons that OUR OWN emitters wrote as a string before the receipt got a
#: type. The key is the start of the string: some messages carry a number in
#: the tail ("dependent Sketch count is 2"), and matching them in full would
#: mean parsing one building and missing on the next.
#:
#: THIS IS NOT A LIST OF FAMILIAR NAMES FROM THE MODEL. Only strings of our
#: own protocol live here — no type name, family name, or id can come from
#: here, and the table works exactly the same way on a foreign building.
#: It is needed because decompiles already sit on disk: they cannot be
#: re-captured without Revit, yet they must be read with the new taxonomy.
_LEGACY_REASON_PREFIXES: tuple[tuple[str, str, "SideFailureReason"], ...] = (
    ("curtain", "not_curtain", SideFailureReason.ASPECT_NOT_PRESENT),
    ("curtain", "host has no CurtainGrid",
     SideFailureReason.ASPECT_NOT_PRESENT),
    ("curtain", "requested element is not a curtain host",
     SideFailureReason.HOST_KIND_UNRESOLVED),
    ("curtain", "multiple_curtain_grids",
     SideFailureReason.ADDRESS_AMBIGUOUS),
    ("sketch", "exact profile topology unavailable",
     SideFailureReason.PROFILE_TOPOLOGY_UNSUPPORTED),
    ("sketch", "stairs parent has no single reliable closed Sketch profile",
     SideFailureReason.PROFILE_NOT_SINGLE_CLOSED),
    ("sketch", "dependent Sketch count is",
     SideFailureReason.DEPENDENT_SKETCH_AMBIGUOUS),
    # A railing is a PATH element: it has no closed contour not because we
    # did not look closely, but because one does not exist for it. This is
    # verbatim the case ASPECT_NOT_PRESENT describes with its own example
    # ("the element has no profile"), hence DETERMINATION, not CUT:
    # otherwise 203 railings from K2 alone would arrive in the passport as
    # our shortcoming. The table is addressed by PREFIX, not by index (see
    # legacy_typed_reason), so the row sits next to its own stage rather
    # than at the tail of the tuple.
    ("sketch", "railing is a path element",
     SideFailureReason.ASPECT_NOT_PRESENT),
    ("family_placement", "not a FamilyInstance",
     SideFailureReason.ELEMENT_KIND_MISMATCH),
    ("group", "group read failed", SideFailureReason.READ_FAILED),
)


def legacy_typed_reason(stage: str, reason: Any) -> "SideFailureReason | None":
    """The type for a receipt recorded BEFORE a type became mandatory."""
    if not isinstance(reason, str) or not reason:
        return None
    for known_stage, prefix, typed in _LEGACY_REASON_PREFIXES:
        if known_stage == stage and reason.startswith(prefix):
            return typed
    return None


def resolved_typed_reason(failure: Any, stage: str) -> str | None:
    """The receipt's type: its own if it has one, else inferred from the old string.

    The order is not accidental: a recorded type always outranks an
    inferred one, or today's compatibility table would rewrite tomorrow's
    receipts.
    """
    typed = failure_typed_reason(failure)
    if typed is not None:
        return typed
    reason = getattr(failure, "reason", None)
    if reason is None and isinstance(failure, Mapping):
        reason = failure.get("reason")
    inferred = legacy_typed_reason(stage, reason)
    return inferred.value if inferred is not None else None


def failure_kind(typed_reason: Any) -> SideFailureKind | None:
    """The reason's class (cut / determination) from its value."""
    if typed_reason is None:
        return None
    try:
        reason = SideFailureReason(getattr(
            typed_reason, "value", typed_reason))
    except (TypeError, ValueError):
        return None
    return SIDE_FAILURE_KINDS.get(reason)


def reconcile_side_stage(
    stage: str,
    *,
    requested: Sequence[str],
    accounted: Iterable[str],
) -> None:
    """Reconcile what was requested with what was received; a mismatch is a typed refusal.

    ``accounted`` is the union of row ids and receipt ids. COVERAGE is
    checked (see the module docstring for why it, and not a sum of lengths).
    """
    wanted = set(requested)
    seen = set(accounted)
    # 🔴 "UNREQUESTED" IS CHECKED FIRST, AND THIS IS NOT A REORDERING FOR
    # ORDER'S SAKE (F-177). An unrequested id speaks of a FOREIGN DOCUMENT,
    # while a missing one speaks of incompleteness of OUR OWN; the first
    # voids the meaning of the second, because it is meaningless to ask
    # "what is missing" of an answer about the wrong building.
    #
    # And, above all: this spot used to hold `if not wanted: return`, which
    # made the unrequested-id guard UNREACHABLE on an empty request. An
    # empty request does not mean "nothing to check" — it means "we asked
    # for NOTHING", and any id that arrives anyway is evidence that the
    # bridge read a different document. Exactly the trouble that cost 1,837
    # foreign receipts on 30.07 (the argument is recorded verbatim in
    # `source_binding_cs`).
    unexpected = sorted(seen - wanted, key=element_id_key)
    if unexpected:
        raise SideStageContractError(
            f"{stage}: ответ несёт {len(unexpected)} незапрошенных id "
            f"(первые: {', '.join(unexpected[:8])})")
    if not wanted:
        return
    missing = sorted(wanted - seen, key=element_id_key)
    if missing:
        raise SideStageContractError(
            f"{stage}: запрошено {len(wanted)}, без строки и без квитанции "
            f"{len(missing)} (первые: {', '.join(missing[:8])})")


def summarize_side_failures(
    extractions: Mapping[str, Any],
) -> dict[str, Any]:
    """Aggregate the receipts of all side indexes for run.json / status / the passport.

    Receipts are sorted into TWO classes (see :class:`SideFailureKind`), and
    both are printed side by side. ``side_cuts_*`` are cuts only, i.e. what
    we did not look at closely. ``side_determinations_*`` is what we looked
    at and the element does not have.

    This used to say "untyped refusals are honest observations, and
    labelling them with a type would be a lie." The observation was true,
    the conclusion was not: what followed from it was not the absence of a
    type but the absence of a SECOND CLASS. While there was no class,
    ``not_curtain`` stayed without a reason, fell into no breakdown, and
    surfaced as the single number ``side_failures_by_stage``, where it read
    as a mass of failures: 14,343 on 13A-RD-AR-K2_v33 against 19 real ones.
    ``side_failures_untyped`` must now be zero, and this is checked by a
    test, not by convention.
    """
    by_stage: dict[str, int] = {}
    cuts: dict[str, int] = {}
    determinations: dict[str, int] = {}
    unclassified: dict[str, int] = {}
    cuts_by_stage: dict[str, int] = {}
    determinations_by_stage: dict[str, int] = {}
    untyped = 0
    for stage in sorted(extractions):
        extraction = extractions[stage]
        if extraction is None:
            continue
        failures = tuple(getattr(extraction, "failures", ()) or ())
        if not failures:
            continue
        by_stage[stage] = len(failures)
        for failure in failures:
            reason = resolved_typed_reason(failure, stage)
            if reason is None:
                untyped += 1
                continue
            kind = failure_kind(reason)
            bucket = (cuts if kind is SideFailureKind.CUT
                      else determinations if kind is SideFailureKind.DETERMINATION
                      else unclassified)
            bucket[reason] = bucket.get(reason, 0) + 1
            if kind is SideFailureKind.CUT:
                cuts_by_stage[stage] = cuts_by_stage.get(stage, 0) + 1
            elif kind is SideFailureKind.DETERMINATION:
                determinations_by_stage[stage] = (
                    determinations_by_stage.get(stage, 0) + 1)
    summary = {
        "side_failures_total": sum(by_stage.values()),
        "side_failures_by_stage": by_stage,
        "side_failures_untyped": untyped,
        "side_cuts_total": sum(cuts.values()),
        "side_cuts_by_reason": dict(sorted(cuts.items())),
        # The stage breakdown is needed in EXACTLY this shape: it was the
        # single number ``side_failures_by_stage[curtain]`` = 14,343 that
        # got the stage branded as the biggest failure. Next to it there
        # must stand the fact that only 19 of those are cuts, the rest are
        # answers.
        "side_cuts_by_stage": dict(sorted(cuts_by_stage.items())),
        "side_determinations_total": sum(determinations.values()),
        "side_determinations_by_reason": dict(sorted(determinations.items())),
        "side_determinations_by_stage": dict(sorted(
            determinations_by_stage.items())),
    }
    if unclassified:
        # The reason exists, it just has no class: staying silent about
        # this is not an option — it is exactly the hole this dictionary
        # was set up to close.
        summary["side_failures_unclassified"] = dict(sorted(
            unclassified.items()))
    return summary


def receipts_summary_ru(summary: Mapping[str, Any]) -> str:
    """The passport row (in Russian): "cut receipts: N (by reason: …)" or "no cuts".

    Printed AFTER the census and BEFORE the percentages for the same reason
    the census stands there: the reader must learn what we did not look at
    closely before seeing the share that was lifted.
    """
    def _detail(reasons: Mapping[str, Any]) -> str:
        return ", ".join(
            f"{reason} {count}"
            for reason, count in sorted(
                reasons.items(), key=lambda item: (-item[1], item[0])))

    total = int(summary.get("side_cuts_total") or 0)
    if total:
        head = f"{total} (по причинам: " \
               f"{_detail(summary.get('side_cuts_by_reason') or {})})"
    else:
        head = "срезов нет"
    # Determinations are printed in the same row as a SEPARATE number:
    # without them the reader sees "no cuts" where the stage put out 14
    # thousand receipts, and rightly stops trusting the row.
    determined = int(summary.get("side_determinations_total") or 0)
    if determined:
        head += (f"; определений: {determined} (по причинам: "
                 f"{_detail(summary.get('side_determinations_by_reason') or {})})")
    # 🔴 RECEIPTS WITHOUT A CLASS WERE NOT PRINTED AT ALL (F-178), and the row
    # said "no cuts" while 14,343 receipts had no class. The summary COUNTS
    # them a row above — with the direct argument "staying silent about this
    # is not an option, it is exactly the hole this dictionary was set up to
    # close" — yet stayed silent here.
    #
    # And this is exactly the figure the same file names as the reason to
    # set up the breakdown: it was the single number 14,343 that got the
    # stage branded as the biggest failure. The number came back with the
    # OPPOSITE sign — by it the stage would have been branded the CLEANEST,
    # meaning the lie went in the reassuring direction.
    #
    # A number without a class is WORSE than a number with one: it cannot be
    # used to decide anything, yet its ABSENCE gets read as there being
    # nothing to decide.
    unclassified = summary.get("side_failures_unclassified") or {}
    if unclassified:
        head += (f"; БЕЗ КЛАССА: {sum(int(v) for v in unclassified.values())} "
                 f"(причины: {_detail(unclassified)})")
    # A third kind: a receipt with no TYPED reason at all. Today there are
    # zero of them and a separate test holds that — but the row must cover
    # the WHOLE, or the next kind will disappear the same way this one did.
    untyped = int(summary.get("side_failures_untyped") or 0)
    if untyped:
        head += f"; БЕЗ ТИПА: {untyped}"
    return head


# ── §18.2b: DID A LIFTED RELATION MAKE IT TO THE PROGRAM ────────────────────
#
# THE TRIGGER (E-30, measurement of 29.08.2026). A building carried over into
# a foreign document arrived as "a Frankenstein whose walls stick out": 6,015
# walls and NOT ONE join. The cause was sought in the capture and in the
# lift, but it is in the ROUTE: `lift_joins` lifts joins (measured on the
# live corpus 29.08: 1,887 · 1,992 · 1,758 · 1,339 operations across four
# buildings), `lift_groups` lifts groups (35 · 28), and NEITHER of them makes
# it to the program. The materializer accepts them as the `joins=` parameter,
# but gets it from no one.
#
# 🔴 WHY THIS IS A RECEIPT, NOT A ROUTE FIX. Laying the route means touching
# `serving.py` and the materializer — someone else's land, and a separate
# decision about COST. But while there is no route, "zero joins in the
# program" is indistinguishable from "the building has no joins", and that
# is exactly the substitution the whole of §18.2 was written against: the
# difference between "we cannot" and "we did not look". So the answer DOES
# NOT CHANGE, and the silence gets a REASON that can be asked — the same
# shape as `snapshot_pins.Reach.reason` and `install_root_refusal`.

#: WHY a lifted relation does not make it to the program today. The string
#: must name the NEXT MOVE: a reason with no action following from it is
#: the same silence, only longer.
RELATIONS_UNDELIVERED_REASON = (
    "поднятые отношения конвейер НИКУДА не передаёт: `tree.json` несёт только "
    "листья, а `materialize.leaves_to_program` получает `joins=` ни от кого "
    "(параметра `groups=` у него нет вовсе). Всякий «соединений в программе "
    "ноль» отсюда есть факт о МАРШРУТЕ, а не о здании. СЛЕДУЮЩИЙ ХОД: "
    "сохранить поднятые отношения рядом с разбором и подать их "
    "`leaves_to_program(joins=…)`; для групп сперва нужно встраивание членов, "
    "которого материализатор не умеет (`lift.GroupLift.ops` называет это "
    "прямо)")

#: The language op's name for every kind of relation. The key is the kind,
#: the value is the op.
#: 🔴 `create_join` DOES NOT EXIST IN THE LANGUAGE, and this is not a typo:
#: the op is called `join_elements`. The E-30 measurement searched decompiles
#: for the name `create_join` and never found it — true, but about a
#: NONEXISTENT subject.
RELATION_OPS: tuple[tuple[str, str], ...] = (
    ("joins", "join_elements"),
    ("groups", "create_group"),
)


def relations_reach(joins: Any, groups: Any) -> dict[str, Any]:
    """What became of the RELATIONS: lifted, refused, made it to the program.

    Input is the ``joins`` and ``groups`` fields of the lift result.
    ``None`` means "the index was NOT SUPPLIED" and lands in
    ``relations_not_asked``: an empty count next to a non-empty one would
    read as "the building has none", and that is a different claim (the
    same discipline as :class:`lift.LiftResult`).

    ``relations_delivered_to_program`` is zero ALWAYS and by construction
    today — see :data:`RELATIONS_UNDELIVERED_REASON`. Printing it next to
    ``relations_lifted`` is mandatory: one number without the other is
    either "we lifted and stayed silent" or "0 made it" with no
    explanation, and both are worse than the pair.
    """

    lifted: dict[str, int] = {}
    refused: dict[str, int] = {}
    not_asked: list[str] = []
    for field, op_name in RELATION_OPS:
        lift = joins if field == "joins" else groups
        if lift is None:
            not_asked.append(op_name)
            continue
        lifted[op_name] = len(getattr(lift, "ops", ()) or ())
        for refusal in getattr(lift, "refusals", ()) or ():
            raw = getattr(refusal, "reason", None)
            key = f"{op_name}:{getattr(raw, 'value', raw)}"
            refused[key] = refused.get(key, 0) + 1
    total = sum(lifted.values())
    summary: dict[str, Any] = {
        "relations_lifted": dict(sorted(lifted.items())),
        "relations_lifted_total": total,
        "relations_delivered_to_program": 0,
        "relations_refused_by_reason": dict(sorted(refused.items())),
        "relations_not_asked": sorted(not_asked),
        "relations_reach_reason": (
            RELATIONS_UNDELIVERED_REASON if total else None),
    }
    summary["relations_reach_summary_ru"] = relations_summary_ru(summary)
    return summary


def relations_summary_ru(summary: Mapping[str, Any]) -> str:
    """The passport row about relations (in Russian). Reads without the rest of the passport."""

    lifted = summary.get("relations_lifted") or {}
    not_asked = summary.get("relations_not_asked") or []
    parts: list[str] = []
    if lifted:
        parts.append("поднято: " + ", ".join(
            f"{name} {count}" for name, count in sorted(lifted.items())))
    if not_asked:
        parts.append("индекс не подавали: " + ", ".join(sorted(not_asked)))
    if not parts:
        return "отношений не поднимали"
    if summary.get("relations_lifted_total"):
        parts.append(
            "до программы доехало "
            f"{summary.get('relations_delivered_to_program', 0)} — "
            "маршрута нет (`relations_reach_reason`)")
    return "; ".join(parts)


#: A FALSE ZERO OF RECEIPTS (F-164) — ONE RULE FOR ALL READERS.
#:
#: All seven side readers wrote `_array(root.get("failures") or [], …)`.
#: `or []` substitutes a default value for a SHAPE CHECK, and so a wire that
#: sent `failures: false`, `0`, `""`, or `{}` was accepted as an HONEST ZERO
#: RECEIPTS — that is, "we looked at everything, no cuts" instead of "the
#: response's shape is broken". Measured BEFORE the fix landed on
#: `dimension_extract`: all five unfit values were accepted, receipts came
#: out 0 for both readers, disk and wire alike.
#:
#: 🔴 THE REFUSAL FIRES IMMEDIATELY, WITH NO DELAY, AND THIS IS MEASURED,
#: NOT ASSUMED. Separator Д2: it can only fire on input that is ALREADY
#: unfit. A measurement on the live corpus 29.08 (144 `*.index.json` files,
#: read-only): `failures` is a list in 144 of 144, unfit values in NOT ONE.
#:
#: A missing key and `null` still resolve to an empty list: `failures` is
#: declared optional, and turning "was not sent" into a refusal would mean
#: changing the contract, not fixing a defect.


def optional_failures(
    value: Any,
    field_name: str,
    error: type[Exception],
) -> list[Any]:
    """`failures`: absent means an empty list; anything else non-list is a REFUSAL.

    ``error`` is supplied by the caller deliberately: every stage has its
    own typed parse error, and one shared across all of them would be a
    third carrier of the same schema. The knowledge here is ONE (see the
    comment above), while the refusal's name belongs to the stage.
    """

    if value is None:
        return []
    if not isinstance(value, list):
        raise error(f"{field_name} must be an array")
    return value


def parse_wire_failures(
    value: Any,
    field_name: str,
) -> tuple[SideFailure, ...]:
    """Parse the list of receipts from the bridge's response (strict, fail-closed)."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SideStageContractError(f"{field_name} must be an array")
    return sorted_failures(
        SideFailure.from_dict(raw, f"{field_name}[{index}]")
        for index, raw in enumerate(value)
    )


def failures_to_json(failures: Iterable[SideFailure]) -> str:
    return json.dumps(
        [failure.to_dict() for failure in sorted_failures(failures)],
        ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"))


# ── which document a stage reads ─────────────────────────────────────────────
#: The only LEGITIMATE reference the emitted body makes to the host
#: document: looking up the link itself. Everything else in the body must go
#: through ``__src``.
SOURCE_HOST_LOOKUP_CS = (
    "foreach (RevitLinkInstance __srcLi in new FilteredElementCollector(doc)")


def csharp_string(value: str) -> str:
    """A C# string literal: the document name arrives from outside and travels as a LITERAL."""
    return cs_string_literal(value)


# ── how to build an ElementId from a number ──────────────────────────────────
#: The ONLY way to assemble an ``ElementId`` from a number in an emitted
#: body. One text for ALL bodies for exactly the same reason as the source
#: binding: two copies of this decision would mean two truths about what is
#: legitimate across six versions, and they would drift apart silently.
#:
#: THE LIVE MEASUREMENT of 30.07, for whose sake this fragment exists.
#: Decompiling a 59-storey tower on **Revit 2023** hung dead and repeated in
#: a loop, every 5-20 seconds, ``bridge_roundtrips=0``:
#:
#:     CS1503: Argument 1: cannot convert from 'long' to
#:     'Autodesk.Revit.DB.BuiltInParameter'   (line 103)
#:
#: The word ``BuiltInParameter`` is not in ANY of our sources — and this is
#: not an oddity of the message, it is how it is built. ``ElementId(Int64)``
#: appeared ONLY in 2024 (checked against RevitAPI.xml for all six
#: versions); on 2021-2023 the overload set is
#: ``{BuiltInCategory, BuiltInParameter, Int32}``, and ``long`` fits none of
#: them. The type name in CS1503 comes from the SHIPPED ASSEMBLY, not from
#: our text, so hunting for the culprit by grepping the message is useless:
#: what must be searched for is ``new ElementId(``.
#:
#: ``int`` passes on all six: 2021-2023 take their own constructor, 2024+
#: implicitly widen ``int``→``long``. So the number travels as an ``int``,
#: and going beyond ``Int32`` is NOT truncated: a truncated id would
#: silently address a FOREIGN element — an outcome worse than any named
#: refusal. On 2021-2023 such ids cannot occur by construction (there
#: ``ElementId`` is 32-bit); on 2024+ that is a document with two billion
#: elements.
ELEMENT_ID_HELPER_CS = (
    "Func<long, ElementId> __sideElementId = (__value) =>\n"
    "    (__value < Int32.MinValue || __value > Int32.MaxValue)\n"
    "        ? null : new ElementId((int)__value);"
)

#: The receipt reason for an id the emitted body cannot address. One text
#: for all stages: one phenomenon, one string, or the passport's breakdown
#: would lump it together as three different ones.
ELEMENT_ID_OUT_OF_RANGE_REASON = (
    "element id is outside the 32-bit id space this body can address"
)


def source_binding_cs(
    link_title: str | None,
    link_instance_unique_id: str | None = None,
) -> str:
    """The source binding: the host, or its LINK with the given ``Document.Title``.

    One text for ALL bodies — the main extraction and every side stage
    alike. Two copies of this C# would mean two truths about which document
    is being read, and the law "one body — one document" is checked against
    the emission TEXT: the copies would drift apart silently and leave the
    check green.

    The body must begin with this binding. The reason is not stylistic: the
    side stages' helpers are lambdas that capture ``__src``, and a C# local
    variable is not visible above its own declaration. A binding placed
    after the helpers would not "read the wrong thing" — it simply would not
    compile under Roslyn, which means it would only be found out live.

    THE MEASUREMENT of 30.07 (``backend/data/decompile/snowdon_elec_v1``),
    for whose sake the binding moved here: linked electrical work, captured
    from the plumbing window, produced 1,837 receipts from a single family
    placement stage — its collector searched for the link's id in the HOST.
    And 20 times the host ANSWERED: documents have separate id spaces whose
    numbers coincide, and the stage recorded foreign rows as its own.

    A CAVEAT THAT CANNOT BE HIDDEN: the revision guard fingerprints the HOST
    document, so it will not catch a concurrent edit made on a link's read
    (see ``extract._source_binding_cs``).

    Exact ``RevitLinkInstance.UniqueId`` is the authoritative selector.
    ``Document.Title`` remains only a legacy selector and requires exactly one
    loaded match; two placements with the same title refuse instead of
    choosing an arbitrary occurrence.  Either route retains the exact
    ``RevitLinkInstance`` for identity and transform evidence.
    """
    if link_title is not None and link_instance_unique_id is not None:
        raise ValueError(
            "link_title and link_instance_unique_id are mutually exclusive")
    if link_instance_unique_id is not None and (
            not isinstance(link_instance_unique_id, str)
            or not link_instance_unique_id.strip()):
        raise ValueError("link_instance_unique_id must be a non-blank string")
    if not link_title:
        if link_instance_unique_id is not None:
            uid = csharp_string(link_instance_unique_id)
            return (
                "Document __federationRoot = doc;\n"
                "Document __src = null;\n"
                "RevitLinkInstance __sourceLinkInstance = null;\n"
                "int __sourceLinkMatches = 0;\n"
                + SOURCE_HOST_LOOKUP_CS + "\n"
                "         .OfClass(typeof(RevitLinkInstance)).WhereElementIsNotElementType()\n"
                "         .Cast<RevitLinkInstance>()\n"
                "         .OrderBy(__x => __x.Id.ToString()))\n"
                "{\n"
                "    string __candidateUniqueId = null;\n"
                "    try { __candidateUniqueId = __srcLi.UniqueId; } catch { }\n"
                "    if (__candidateUniqueId == " + uid + ")\n"
                "    {\n"
                "        __sourceLinkMatches++;\n"
                "        Document __srcLd = __srcLi.GetLinkDocument();\n"
                "        if (__srcLd != null)\n"
                "        {\n"
                "            __src = __srcLd;\n"
                "            __sourceLinkInstance = __srcLi;\n"
                "        }\n"
                "    }\n"
                "}\n"
                "if (__sourceLinkMatches > 1) throw new InvalidOperationException(\n"
                "    \"duplicate RevitLinkInstance.UniqueId: \" + " + uid + ");\n"
                "if (__sourceLinkMatches == 0) throw new InvalidOperationException(\n"
                "    \"link instance UniqueId not found: \" + " + uid + ");\n"
                "if (__src == null) throw new InvalidOperationException(\n"
                "    \"link instance is not loaded: \" + " + uid + ");"
            )
        return (
            "Document __federationRoot = doc;\n"
            "Document __src = doc;\n"
            "RevitLinkInstance __sourceLinkInstance = null;")
    return (
        "Document __federationRoot = doc;\n"
        "Document __src = null;\n"
        "RevitLinkInstance __sourceLinkInstance = null;\n"
        "int __sourceLinkMatches = 0;\n"
        + SOURCE_HOST_LOOKUP_CS + "\n"
        "         .OfClass(typeof(RevitLinkInstance)).WhereElementIsNotElementType()\n"
        "         .Cast<RevitLinkInstance>()\n"
        "         .OrderBy(__x => __x.Id.ToString()))\n"
        "{\n"
        "    Document __srcLd = __srcLi.GetLinkDocument();\n"
        "    if (__srcLd != null && __srcLd.Title == " + csharp_string(link_title) + ")\n"
        "    {\n"
        "        __sourceLinkMatches++;\n"
        "        if (__sourceLinkMatches == 1)\n"
        "        {\n"
        "            __src = __srcLd;\n"
        "            __sourceLinkInstance = __srcLi;\n"
        "        }\n"
        "    }\n"
        "}\n"
        "if (__sourceLinkMatches > 1) throw new InvalidOperationException(\n"
        "    \"linked document title is ambiguous; select a link instance: \" + "
        + csharp_string(link_title) + ");\n"
        "if (__src == null) throw new InvalidOperationException(\n"
        "    \"linked document not found or not loaded: \" + "
        + csharp_string(link_title) + ");"
    )


__all__ = [
    "ELEMENT_ID_HELPER_CS",
    "ELEMENT_ID_OUT_OF_RANGE_REASON",
    "SIDE_FAILURE_KINDS",
    "SOURCE_HOST_LOOKUP_CS",
    "SideFailure",
    "SideFailureKind",
    "SideFailureReason",
    "SideStageContractError",
    "csharp_string",
    "element_id_key",
    "failure_element_id",
    "failure_kind",
    "failure_typed_reason",
    "legacy_typed_reason",
    "resolved_typed_reason",
    "record_element_id",
    "failures_to_json",
    "parse_wire_failures",
    "receipts_summary_ru",
    "reconcile_side_stage",
    "sorted_failures",
    "source_binding_cs",
    "summarize_side_failures",
]
