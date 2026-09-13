"""The join SIDE INDEX: the fact "this is joined to that" stops being lost.

THE TRIGGER IS THE OWNER'S LIVE RUN, not a guess. A building was
captured by decompile and recompiled back; the owner's verdict,
verbatim: "walls overlap everywhere and **nothing is joined to
anything else**." The forward pass works correctly here — it did not
lose the joins, it NEVER READ THEM. Measured 17.08.2026 across the
tree: ``GetJoinedElements`` occurs in ``kir/decompile/`` **0 times**,
join operations in the registry **0**.

🔴 THERE ARE THREE KINDS, NOT ONE AND NOT TWO. EACH IS BOUGHT BY A LIVE MEASUREMENT
----------------------------------------------------------------------------------

    kind                   read via                               arity
    joined_to              JoinGeometryUtils.GetJoinedElements     pair
    join_allowed_at_end    WallUtils.IsWallJoinAllowedAtEnd        wall + end
    elements_at_end_join   LocationCurve.get_ElementsAtJoin        pair + end

The third kind was introduced on 18.08 and refuted a claim that had
lived for an hour: that the fact "these two walls are joined end to
end" **is read by no API at all** and can only be derived from
geometry. The claim rested on a review of two familiar calls, and the
question was "is there a witness AT ALL." There is a witness, and it
has the same signature ``(Int32) -> ElementArray`` across all six
versions.

Below are the measurements that bought each kind.
Across 800 walls of the owner's live document, ``IsWallJoinAllowedAtEnd``
and ``GetJoinedElements`` were cross-checked:

    both ends ALLOWED and joined            143 of 288
    both ends FORBIDDEN and not joined       27 of 223
    mixed outcome                            38 of 81

🔴 AND THIS IS CONFIRMED INDEPENDENTLY, ON A DIFFERENT SAMPLE AND BY A
DIFFERENT PERSON. A second measurement (18.08.2026, Revit 2023,
`13A-RD-AR-K2_v33`, ids taken from ``query_list``, the body assembled
by THIS module): of 200 walls, **38 are forbidden on both ends — 19 %**.
The first measurement gave the same cell as 27 of 800. The samples
differ, the shares differ, but the ORDER is the same and the sign is
the same: "Revit always joins" does not hold on a live building, and
not just once. Two independent measurements are the reason these two
fields will not merge into one at the next "simplification."

That is, "allowed to join" and "joined" are **different relations**,
and one does NOT follow from the other in either direction. The index
carries both SEPARATELY and never derives one from the other anywhere.
Merging them into one field would repeat this package's namesake
defect — gluing two questions under one name, the very thing
``building_graph.Relation`` was written against ``Modality`` to take
apart.

And they differ in ARITY, and that is what decides the storage shape:

* ``joined_to`` — **a relation between two elements**. Symmetric,
  lives as a graph edge (``Relation.JOINED_TO``);
* ``join_allowed_at_end`` — **a property of ONE wall at ONE end**.
  Cannot be an edge: there is no second participant. Lives as a
  record field;
* ``elements_at_end_join`` — **a pair PLUS an end number**. Also an
  edge (``Relation.JOINED_AT_END``), but NOT symmetric: the end
  belongs to a specific wall, and "at my end 0 stands she" versus "at
  her end 1 stand I" are two facts about one joint. The edge key does
  not include this evidence, so a symmetric declaration would collapse
  them into one and erase the end number.

🔴 THE THIRD KIND DISAGREES WITH THE FIRST ON ONE PAIR OF WALLS, AND
THIS IS NOT AN EDGE CASE. Live measurement of 18.08: two walls butt
together — the end is joined, yet ``AreElementsJoined`` is **False**,
and ``JoinGeometry`` REFUSES with "cannot be joined." The reason is
not a malfunction: the end joint had already trimmed the curves, no
body overlap remains, there is nothing to merge. Before the third kind
existed, such a pair was recorded as ``joined_to: []`` — i.e. the
index answered "not joined" for exactly the case that made the owner
say "nothing is joined to anything else." One kind for three questions
would have reproduced the very complaint this module was written for.

AN EMPTY LIST OF JOINS IS DATA, NOT AN ABSENCE OF DATA
------------------------------------------------------
Here the stage diverges from ``mep_system_extract``, deliberately. A
pipe with no system gets a RECEIPT there (``aspect_not_present``),
because without a system type it cannot be reassembled. An element
with no joins reassembles perfectly well — "joined to nothing" is a
positive fact about the building, and it must arrive as a ROW. A
receipt here means exactly one thing: **we did not look**. The
difference between "not joined" and "not read" is precisely the
subject of §18.2, and at this stage it additionally decides whether to
fix the reassembly.

WHERE IT COMES FROM. ``JoinGeometryUtils.GetJoinedElements(Document,
Element)`` · ``WallUtils.IsWallJoinAllowedAtEnd(Wall, Int32)`` ·
``LocationCurve.get_ElementsAtJoin(Int32) -> ElementArray``. The
signatures were checked against
``data/api_surface/api_signatures_<version>.json`` for ALL SIX
versions 2021–2026 and match byte-for-byte; not a single guessed
member name. This trio has no version fragility — verified, not
recalled, and emission was also run through live Roslyn on
2021·2022·2023·2024·2025·2026, both arms.

EACH END IS READ IN ITS OWN ``try``, and this is a direct lesson from
a neighboring defect: in ``authoring.py:7324`` both ends sit under one
EMPTY ``catch``, and if the first throws, the second never runs —
indistinguishable from success. Here an end's failure IS NAMED
(``EndJoin.why``) and stays distinguishable from "no neighbors."

WHAT THIS STAGE DOES NOT KNOW (the boundary is named, not left unsaid)
----------------------------------------------------------------------
* **joins outside the query.** The stage asks for ids from a closed
  list of categories (``JOIN_CATEGORIES``). If ``GetJoinedElements``
  returned an address not in this set, the record SAVES it, and the
  graph gives the edge ``Modality.UNRESOLVED_TARGET`` — as
  ``hosted_in`` already does, where the same outcome reaches 95.8 %
  on ``snowdon_elec_v1``. Discarding such an address would turn our
  blindness into a negative fact about the building;
* **join order** (``SwitchJoinOrder`` — who cuts whom). The relation
  is symmetric here by construction, and order is a third question,
  left unasked. ``IsCuttingElementInJoin`` exists on all six versions
  — when order is needed, take it from there, rather than deriving it
  from ``joined_to``;
* **joins in linked files.** A link's geometry does not join with the
  host's geometry; addresses from a link will not appear here at all.

WEIGHT — A MEASUREMENT, NOT A PROMISE (``k2_ar_rd_v8``, an 84.3 MB
``L0.jsonl`` decompile):

    joinable elements                         18 071
      OST_Walls 15 341 · OST_StructuralFraming 1 426 · OST_StructuralColumns 679
      OST_Floors 455 · OST_Stairs 89 · OST_Ceilings 81
    total elements in the census              310 558
    expected edges at 2 joins                  18 071

INDEX WEIGHT — A MEASUREMENT OF THE SHAPE, not an estimate: 17 982
elements, 36 008 pairs, **1.62 MB** as raw JSON (94 B per element) and
**0.19 MB** gzipped, i.e. **1.93 %** of the same building's
``L0.jsonl`` (and the janitor gzips cooled-down snapshots, in which
case 0.23 %). The answer to "is it lightweight" — yes, and here is the
number.

THE STAGE'S COST — A LIVE MEASUREMENT, WITH FULL PROVENANCE HERE
----------------------------------------------------------------
A number cannot be quoted without provenance (form 26), so:
**18.08.2026 · Revit 2023 · document ``13A-RD-AR-K2_v33``, 15 930
walls · ids taken from ``query_list``, not invented · body assembled
by this very ``build_join_extract_cs``**:

     20 id ->  304 ms, response  1 900 B,  9 joined, 16 pairs,  2 forbidden on both ends
    200 id ->  332 ms, response 17 678 B, 55 joined, 99 pairs, 38 forbidden on both ends

**THE COST IS FLAT: a tenfold increase in the id count costs 28 ms.**
What is paid for is walking the document, not the elements — the
stage behaves like the other reading stages. For scale: the cheapest
phase of a live run (``acceptance_before``) costs 1 220 ms, i.e. the
stage is three times cheaper than it.

🔴 THE MOCK LIED BY A FACTOR OF 77, AND THAT IS A SEPARATE LESSON. On
the first attempt to wire it in, ``stage_ms['join']`` came out to
**25 626.7 ms** against 200–1 000 ms for its neighbors, and the
pipeline broke its budget. The wiring was rolled back — correctly,
because the live number did not exist yet. But the cause turned out
NOT to be the stage: the bridge mock did not know about it, the
request fell into the shared extraction branch, the response was not
parsed, and ``_side_or_resume`` went into a retry loop with a timeout.
What was fixed was the MOCK (``tests/test_pipeline._join_payload``),
not the budget: raising the ceiling would have made the stage's next
real regression invisible.

And the mock was blind WIDER THAN ONE STAGE. Its ``_requested_ids``
promised "the ids the emitter wrote," but read only ONE spelling —
``new string[]``. The census that day: ``new string[]`` for curve ·
curtain · sketch · family_placement · geom; ``new List<string>`` for
annotation · tag · dimension · mep_system · join. Five stages out of
ten were invisible, and there was nothing to notice it with, because
four of the five categories simply do not exist in the mini-model.
The first stage whose categories DO exist there immediately got
``side_stage_count_mismatch``.

The graph edge is wired in separately and works without the stage:
``graph_from_l0(..., joins=...)`` accepts the index directly
(``JoinExtraction.join_index``).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Mapping

from kir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    optional_failures,
    source_binding_cs,
)
from kir.emit_utils import cs_string_literal

#: 🔴 THE VERSION WAS BUMPED TO /2 TOGETHER WITH THE THIRD KIND
#: (`elements_at_end_join`). The decompile here refuses under a CLOSED
#: SET (`_exact_fields`), so a version /1 reader, meeting a new field,
#: would have fallen over with an unclear "unexpected" instead of "the
#: schema is different." Checked before the bump: there is NOT A
#: SINGLE version-/1 index ON DISK (0 of 76 corpus decompiles and 0
#: live), so there is nothing to break — but the version was bumped
#: not for that, but because the WIRE FORMAT changed.
JOIN_INDEX_SCHEMA_VERSION = "kir-decompile-join-index/2"
JOIN_EXTRACT_SCHEMA_VERSION = "kir-decompile-join-extract/2"

#: The categories the stage feeds on. Moves TOGETHER with the row in
#: ``pipeline._STAGE_CATEGORIES``: a category here with no row there —
#: an id will never be requested; a row there with no category here —
#: every id will leave as a receipt.
#:
#: The list is CLOSED, BUT NOT COMPLETE, and this is stated, not
#: implied. It takes the categories Revit can actually join by
#: geometry and that occur in the corpus; the count for
#: ``k2_ar_rd_v8`` is in the module header.
JOIN_CATEGORIES = frozenset({
    "OST_Walls",
    "OST_Floors",
    "OST_Roofs",
    "OST_Ceilings",
    "OST_StructuralColumns",
    "OST_StructuralFraming",
    "OST_StructuralFoundation",
    "OST_Columns",
})


class JoinPayloadError(ValueError):
    """A wire response of the wrong shape — a typed refusal, not a guess."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise JoinPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise JoinPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise JoinPayloadError(f"{field_name} must be an array")
    return value


def _exact_fields(value: Any, allowed: set[str], field_name: str, *,
                  optional: set[str] | None = None) -> dict[str, Any]:
    root = _mapping(value, field_name)
    optional = optional or set()
    missing = allowed - optional - set(root)
    if missing:
        raise JoinPayloadError(f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise JoinPayloadError(f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise JoinPayloadError(f"{field_name} must be a non-empty string")
    return value


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


def _joined_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    ids = [
        _string(item, f"{field_name}[{index}]")
        for index, item in enumerate(_array(value, field_name))
    ]
    if len(ids) != len(set(ids)):
        raise JoinPayloadError(f"{field_name} contains a duplicate address")
    # Revit's response order is not declared and is not guaranteed
    # from run to run. The sort here is not cosmetic: without it, the
    # decompile's content signature would depend on the document's
    # traversal order, i.e. the decompile would stop being
    # reproducible for a reason that has nothing to do with the
    # building.
    return tuple(sorted(ids, key=_element_id_key))


def _ends(value: Any, field_name: str) -> tuple[bool, bool] | None:
    """(end 0, end 1), or None — "this is not a wall, the question was
    not asked."

    None and `(False, False)` MEAN DIFFERENT THINGS here and must stay
    distinguishable: the first means the element has no ends at all,
    the second means the ends exist and joining is FORBIDDEN on both.
    A measurement of 800 walls gives 27 elements of the second kind
    out of 223 — a mass case, and merging it with "not applicable"
    would erase a fact.
    """
    if value is None:
        return None
    pair = _array(value, field_name)
    if len(pair) != 2 or not all(isinstance(item, bool) for item in pair):
        raise JoinPayloadError(f"{field_name} must be two booleans")
    return (pair[0], pair[1])


class EndState(str, Enum):
    """WHAT a wall end MEANS — THE INFERENCE IS MADE AND NAMED, not
    left to the reader.

    🔴 WHY THIS ENUM, WHEN THE DATA ALREADY SAT IN TWO FIELDS. An
    empty ``get_ElementsAtJoin`` array means TWO different facts, and
    one value does not tell them apart (live measurement 18.08.2026,
    two walls butted together, the same geometry in two states):

        at(0)=[]  with an ALLOWED joint    -- free end, no neighbor
        at(1)=[]  with a FORBIDDEN joint   -- the neighbor stands FLUSH, the joint is forbidden

    The difference is not academic: **"the building's edge" versus
    "the joint is forbidden with a live neighbor" is the difference
    between a correct outline and a hole in it.** The data was already
    enough (both fields exist in the record); what was missing was
    for the inference to be MADE here, rather than redone differently
    by every consumer. Merging the states back together will be
    possible later; splitting them apart retroactively already has
    nothing to split from.

    WHAT THIS INSTRUMENT DOES NOT SEE, AND THIS IS NAMED, NOT LEFT
    UNSAID. ``FREE_END`` does NOT prove there is no neighbor. It
    proves exactly "at this end there is no joint, and joining is
    allowed." A neighbor may stand flush and not be joined for some
    other reason — this instrument cannot establish which. Reading
    ``FREE_END`` as "here is the building's edge" is the same mistake
    one floor up.

    And there is one more thing we do NOT know, so nothing is built on
    it: **why, after the commit, ``JoinGeometry`` answers "cannot be
    joined"** — this is not explained by measurement. Four end states
    exist; no explanation of the merge refusal does.
    """

    #: Not asked, or a refusal. The reason lives in ``EndJoin.why``.
    NOT_READ = "not_read"
    #: Asked, Revit named neighbors. There IS a joint.
    JOINED = "joined"
    #: Asked, empty, joining is ALLOWED. See the caveat above: this is
    #: not proof of the absence of a neighbor.
    FREE_END = "free_end"
    #: Asked, empty, joining is FORBIDDEN. The neighbor may stand
    #: flush — and this is exactly the case that would have looked
    #: like a "free end" before the split.
    JOIN_FORBIDDEN = "join_forbidden"
    #: Asked, empty, but the PERMISSION was not read. There is nothing
    #: to tell the two cases above apart with, and the instrument says
    #: so outright instead of picking a convenient one.
    EMPTY_UNDECIDED = "empty_undecided"


@dataclass(frozen=True, slots=True)
class EndJoin:
    """ONE end of a wall: WHOM Revit named as joined — or WHY it did
    not say.

    🔴 RAW READING OUTCOMES. The end's meaning is given by ``EndState``
    — it is computed from THIS field AND from
    ``join_allowed_at_end``, because an empty array is ambiguous on
    its own (see the enum above).

        read=True,  elements=(…)   asked, Revit named neighbors
        read=True,  elements=()    asked, there is no joint — but WHY
                                    is decided by EndState
        read=False, why="…"        NOT asked, or a refusal; the reason
                                    IS NAMED

    A refusal arrives here, not as a stage receipt, because it is
    about ONE END: the element's row is honest here, it just has a
    hole in half an aspect. Dumping it into a receipt would mean
    losing the end that WAS read.

    🔴 THE REVIT ARRAY INCLUDES THE QUERIED WALL ITSELF, AND THIS IS A
    TRAP FOR ANYONE READING IT ELSEWHERE. Live measurement: ``w1.at(1)``
    returned ``[18830704, 18830705]``, where **18830704 is w1 itself**.
    A consumer reading ``.Count`` as the neighbor count gets one too
    many; one taking the first element gets ITSELF, i.e. a self-loop
    on the node that will pass every shape check and turn red nowhere.
    Our emitter drops it (``if (__jnNs == __jnRaw) continue;`` in the
    body below), and the decompile REFUSES if the loop arrives anyway
    — but that protects only THIS path, no one else's. It is written
    out in words for exactly this reason: the line of code will not
    warn the next one.
    """

    read: bool
    elements: tuple[str, ...] = ()
    why: str = ""

    def __post_init__(self) -> None:
        if self.read and self.why:
            raise JoinPayloadError(
                "прочитанный конец с причиной отказа — ложный след")
        if not self.read:
            if not self.why:
                raise JoinPayloadError(
                    "непрочитанный конец ОБЯЗАН назвать причину: без неё "
                    "«не спрашивали» неотличимо от «соседей нет»")
            if self.elements:
                raise JoinPayloadError(
                    "непрочитанный конец не может нести соседей")
        if len(self.elements) != len(set(self.elements)):
            raise JoinPayloadError("EndJoin.elements contains a duplicate")

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"read": self.read}
        if self.read:
            row["elements"] = list(self.elements)
        else:
            row["why"] = self.why
        return row

    @classmethod
    def from_dict(cls, value: Any, field_name: str) -> "EndJoin":
        root = _mapping(value, field_name)
        if root.get("read") is True:
            extra = set(root) - {"read", "elements"}
            if extra:
                raise JoinPayloadError(f"{field_name} has unexpected {sorted(extra)}")
            return cls(read=True,
                       elements=_joined_tuple(root.get("elements") or [],
                                              f"{field_name}.elements"))
        if root.get("read") is False:
            extra = set(root) - {"read", "why"}
            if extra:
                raise JoinPayloadError(f"{field_name} has unexpected {sorted(extra)}")
            return cls(read=False, why=_string(root.get("why"),
                                               f"{field_name}.why"))
        raise JoinPayloadError(f"{field_name}.read must be a boolean")


def _end_joins(value: Any, field_name: str) -> tuple[EndJoin, EndJoin] | None:
    if value is None:
        return None
    pair = _array(value, field_name)
    if len(pair) != 2:
        raise JoinPayloadError(f"{field_name} must be two ends")
    return (EndJoin.from_dict(pair[0], f"{field_name}[0]"),
            EndJoin.from_dict(pair[1], f"{field_name}[1]"))


@dataclass(frozen=True, slots=True)
class JoinRecord:
    """What the element is joined to — via THREE DIFFERENT relations,
    not one."""

    element_id: str
    #: Addresses the element's GEOMETRY is joined to
    #: (``JoinGeometryUtils.GetJoinedElements``). An empty tuple is a
    #: legal state of the building, not a reading gap; "we didn't
    #: look" arrives as a RECEIPT, and that is the only difference
    #: between the two cases.
    joined_to: tuple[str, ...] = ()
    #: ``(IsWallJoinAllowedAtEnd(0), IsWallJoinAllowedAtEnd(1))`` —
    #: ONLY for walls; None for everything else. NEVER derived from
    #: `joined_to` and never substituted into it: across 800 walls of
    #: the live document these two relations diverged on 38 elements
    #: out of 81 with a mixed outcome.
    join_allowed_at_end: tuple[bool, bool] | None = None
    #: ``(LocationCurve.get_ElementsAtJoin(0), …(1))`` — WHO is
    #: actually joined to this wall at this end. A THIRD kind, not
    #: derivable from either of the other two.
    #:
    #: 🔴 THE MEASUREMENT THAT BOUGHT THIS FIELD (live Revit,
    #: 18.08.2026): two walls butt together, the end is joined — yet
    #: ``AreElementsJoined`` is **False**, and ``JoinGeometry`` REFUSES
    #: with "cannot be joined." The reason is not a bug: the end joint
    #: had already trimmed the curves, no body overlap remains, and
    #: there is nothing to merge geometrically. That is, "joined end
    #: to end" and "merged by geometry" are not merely different
    #: relations, they are systematically OPPOSITE on the same pair of
    #: walls.
    #:
    #: Before this field existed, such a pair was recorded as
    #: `joined_to: []` — i.e. the index said "not joined" for exactly
    #: the case that made the owner say "nothing is joined to anything
    #: else."
    elements_at_end_join: tuple[EndJoin, EndJoin] | None = None

    def end_states(self) -> tuple[EndState, EndState] | None:
        """The meaning of both ends — DERIVED HERE, not left to the
        consumer.

        Lives on the record, not on `EndJoin`, precisely because the
        inference needs BOTH fields: the joint array and the
        permission. Splitting them across two objects and asking the
        reader to combine them would mean introducing N places
        required to agree — this tree's namesake defect.
        """
        ends = self.elements_at_end_join
        if ends is None:
            return None
        allowed = self.join_allowed_at_end
        out: list[EndState] = []
        for index, end in enumerate(ends):
            if not end.read:
                out.append(EndState.NOT_READ)
            elif end.elements:
                out.append(EndState.JOINED)
            elif allowed is None:
                out.append(EndState.EMPTY_UNDECIDED)
            elif allowed[index]:
                out.append(EndState.FREE_END)
            else:
                out.append(EndState.JOIN_FORBIDDEN)
        return (out[0], out[1])

    def __post_init__(self) -> None:
        if not isinstance(self.element_id, str) or not self.element_id:
            raise JoinPayloadError("JoinRecord.element_id must be non-empty")
        if self.element_id in self.joined_to:
            raise JoinPayloadError(
                "элемент объявлен соединённым САМ С СОБОЙ — такого отношения "
                "нет, и молча выброшенная петля скрыла бы сбой чтения")
        for end in (self.elements_at_end_join or ()):
            if self.element_id in end.elements:
                raise JoinPayloadError(
                    "стена объявлена состыкованной САМА С СОБОЙ на своём же "
                    "конце — молча выброшенная петля скрыла бы сбой чтения")

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "element_id": self.element_id,
            "joined_to": list(self.joined_to),
        }
        if self.join_allowed_at_end is not None:
            row["join_allowed_at_end"] = list(self.join_allowed_at_end)
        if self.elements_at_end_join is not None:
            row["elements_at_end_join"] = [
                end.to_dict() for end in self.elements_at_end_join]
        return row

    @classmethod
    def from_dict(cls, value: Any) -> "JoinRecord":
        root = _exact_fields(
            value,
            {"element_id", "joined_to", "join_allowed_at_end",
             "elements_at_end_join"},
            "join record",
            optional={"join_allowed_at_end", "elements_at_end_join"})
        return cls(
            element_id=_string(root["element_id"], "join record.element_id"),
            joined_to=_joined_tuple(root["joined_to"], "join record.joined_to"),
            join_allowed_at_end=_ends(
                root.get("join_allowed_at_end"),
                "join record.join_allowed_at_end"),
            elements_at_end_join=_end_joins(
                root.get("elements_at_end_join"),
                "join record.elements_at_end_join"),
        )


@dataclass(frozen=True, slots=True)
class JoinFailure:
    """Receipt of §18.2: an element the stage requested and did not
    read."""

    element_id: str
    reason: str
    typed_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"element_id": self.element_id, "reason": self.reason,
                "typed_reason": self.typed_reason}

    @classmethod
    def from_dict(cls, value: Any) -> "JoinFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"}, "join failure")
        return cls(
            element_id=_string(root["element_id"], "join failure.element_id"),
            reason=_string(root["reason"], "join failure.reason"),
            typed_reason=_string(
                root["typed_reason"], "join failure.typed_reason"))


@dataclass(frozen=True, slots=True)
class JoinExtraction:
    """A verified join side index."""

    joins: tuple[JoinRecord, ...] = ()
    failures: tuple[JoinFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.joins]
        if len(ids) != len(set(ids)):
            raise JoinPayloadError("join index contains duplicate element_id")

    def __iter__(self) -> Iterator[JoinRecord]:
        return iter(self.joins)

    def __len__(self) -> int:
        return len(self.joins)

    @property
    def records(self) -> tuple[JoinRecord, ...]:
        """The CONTRACT name the §18.2 verifier asks by.

        Set IMMEDIATELY. The formatting wave stumbled on exactly this:
        the field was named by meaning, the verifier asked by
        contract, and a live run died on 26 elements with sound C#.
        """
        return self.joins

    @property
    def join_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.joins, key=lambda r: _element_id_key(r.element_id))
        }

    def pairs(self) -> tuple[tuple[str, str], ...]:
        """Joins as PAIRS, each exactly once.

        Revit declares the relation from both sides, so a naive row
        count doubles the number of joins. The pair is normalized by
        sorting the addresses — the same trick by which
        ``GraphEdge.key`` collapses symmetric edges, and for the same
        reason.
        """
        seen: set[tuple[str, str]] = set()
        for record in self.joins:
            for other in record.joined_to:
                a, b = sorted((record.element_id, other), key=_element_id_key)
                seen.add((a, b))
        return tuple(sorted(seen, key=lambda p: (_element_id_key(p[0]),
                                                 _element_id_key(p[1]))))

    def end_join_pairs(self) -> tuple[tuple[str, int, str], ...]:
        """End-to-end joints: ``(wall, its end number, neighbor)``.

        SEPARATE from `pairs()` and NOT collapsed with it: this is a
        different relation, and on one pair of walls the two can be
        opposite (an end joint exists, geometry merging does not —
        measured 18.08). The pair is not normalized by sorting here,
        because the end belongs to a SPECIFIC wall: "my end 0" and
        "its end 1" are two different facts about one joint.
        """
        out: list[tuple[str, int, str]] = []
        for record in self.joins:
            for end_index, end in enumerate(record.elements_at_end_join or ()):
                if not end.read:
                    continue
                for other in end.elements:
                    out.append((record.element_id, end_index, other))
        return tuple(sorted(out, key=lambda t: (_element_id_key(t[0]), t[1],
                                                _element_id_key(t[2]))))

    def end_join_refusals(self) -> tuple[tuple[str, int, str], ...]:
        """``(wall, end, WHY it was not read)`` — "we didn't ask" out
        loud.

        Without this method the refusal would live in the record with
        no reader, and an unread end would look like an end with no
        neighbors.
        """
        out: list[tuple[str, int, str]] = []
        for record in self.joins:
            for end_index, end in enumerate(record.elements_at_end_join or ()):
                if not end.read:
                    out.append((record.element_id, end_index, end.why))
        return tuple(sorted(out, key=lambda t: (_element_id_key(t[0]), t[1])))

    def ends_in_state(self, state: EndState) -> tuple[tuple[str, int], ...]:
        """``(wall, end)`` for one named state.

        This method exists for the sake of `JOIN_FORBIDDEN`: before
        the split, these ends looked free, and "the joint is forbidden
        with a live neighbor" versus "the building's edge" is the
        difference between a correct outline and a hole in it.
        """
        out: list[tuple[str, int]] = []
        for record in self.joins:
            for end_index, got in enumerate(record.end_states() or ()):
                if got is state:
                    out.append((record.element_id, end_index))
        return tuple(sorted(out, key=lambda t: (_element_id_key(t[0]), t[1])))

    def end_state_census(self) -> dict[str, int]:
        """A census of ends by state. The keys are ALL of them,
        including the zero ones.

        The zero state is printed deliberately: a missing key reads as
        "that never happens," while it means "did not occur today."
        """
        census = {state.value: 0 for state in EndState}
        for record in self.joins:
            for got in (record.end_states() or ()):
                census[got.value] += 1
        return census

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": JOIN_INDEX_SCHEMA_VERSION,
            "join_index": self.join_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda f: (_element_id_key(f.element_id), f.reason))],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, value: Any) -> "JoinExtraction":
        root = _exact_fields(
            value, {"schema_version", "join_index", "failures"},
            "join index", optional={"failures"})
        if root["schema_version"] != JOIN_INDEX_SCHEMA_VERSION:
            raise JoinPayloadError("join index schema_version mismatch")
        index = _mapping(root["join_index"], "join index.join_index")
        records = []
        for key, row in index.items():
            record = JoinRecord.from_dict(row)
            if record.element_id != key:
                raise JoinPayloadError(
                    "join index key does not match record.element_id")
            records.append(record)
        failures = tuple(
            JoinFailure.from_dict(row)
            for row in optional_failures(
                root.get("failures"), "join index.failures",
                JoinPayloadError))
        return cls(joins=tuple(records), failures=failures)

    @classmethod
    def from_json(cls, text: str) -> "JoinExtraction":
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise JoinPayloadError(
                f"join index is not valid JSON: {exc}") from exc
        return cls.from_dict(value)


def _unwrap_bridge_payload(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "payload" in payload \
            and "schema_version" not in payload:
        return payload["payload"]
    return payload


def extract_joins(payload: Any) -> JoinExtraction:
    """Check one bridge response and assemble the index."""
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "join extraction", optional={"failures"})
    if root["schema_version"] != JOIN_EXTRACT_SCHEMA_VERSION:
        raise JoinPayloadError("join extraction schema_version mismatch")
    records = []
    for index, row in enumerate(_array(root["elements"],
                                       "join extraction.elements")):
        item = _exact_fields(
            row,
            {"element_id", "joined_to", "join_allowed_at_end",
             "elements_at_end_join"},
            f"join extraction.elements[{index}]",
            optional={"join_allowed_at_end", "elements_at_end_join"})
        records.append(JoinRecord(
            element_id=_string(item["element_id"],
                               f"elements[{index}].element_id"),
            joined_to=_joined_tuple(item["joined_to"],
                                    f"elements[{index}].joined_to"),
            join_allowed_at_end=_ends(
                item.get("join_allowed_at_end"),
                f"elements[{index}].join_allowed_at_end"),
            elements_at_end_join=_end_joins(
                item.get("elements_at_end_join"),
                f"elements[{index}].elements_at_end_join"),
        ))
    failures = tuple(
        JoinFailure.from_dict(row)
        for row in optional_failures(
            root.get("failures"), "join extraction.failures",
            JoinPayloadError))
    return JoinExtraction(joins=tuple(records), failures=failures)


def merge_joins(parts: list[JoinExtraction]) -> JoinExtraction:
    """Merge the pages without losing a single record or receipt."""
    records: list[JoinRecord] = []
    failures: list[JoinFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.joins:
            # The FIRST one read wins: "the last one wins" would make
            # the result depend on page order, i.e. on the network.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return JoinExtraction(joins=tuple(records), failures=tuple(failures))


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


JOIN_HELPER_CS = r"""
// KIR DECOMPILE — read-only join helpers. Никаких транзакций.
// Имя класса берётся через Object.ToString() без обращения к среде выполнения
// за типом: та форма записи целиком отвергается валидатором безопасности
// моста версий до 06.07.2026, который всё ещё стоит на части флота.
Func<object, string> __jnClassName = (__jncObj) =>
{
    if (__jncObj == null) return "";
    string __jnc = __jncObj.ToString();
    if (__jnc == null) return "";
    int __jncCut = __jnc.IndexOf((char)10);
    if (__jncCut >= 0) __jnc = __jnc.Substring(0, __jncCut);
    __jncCut = __jnc.IndexOf(':');
    if (__jncCut >= 0) __jnc = __jnc.Substring(0, __jncCut);
    __jnc = __jnc.Trim();
    __jncCut = __jnc.LastIndexOf('.');
    return __jncCut >= 0 && __jncCut + 1 < __jnc.Length
        ? __jnc.Substring(__jncCut + 1) : __jnc;
};
""" + ELEMENT_ID_HELPER_CS + "\n"


_JOIN_BODY_CS = r"""
long __jnCallBudgetMs = __JN_CALL_BUDGET_MS__L;
long __jnCallWatchT0 = DateTime.UtcNow.Ticks;

var __jnFailures = new List<object>();
Action<string, string, string> __jnFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __jnFailures.Add(__failure);
};

var __jnIds = new List<string> { __JOIN_IDS__ };
var __jnRows = new List<object>();
bool __jnBudgetOut = false;
foreach (string __jnRaw in __jnIds)
{
    if (__jnBudgetOut
        || ((DateTime.UtcNow.Ticks - __jnCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __jnCallBudgetMs)
    {
        __jnBudgetOut = true;
        __jnFail(__jnRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // Имя ШАГА, который сейчас идёт: тип исключения без имени вызова — одно
    // ведро на всё, и по нему нельзя сказать ни ЧТО читали, ни ЧТО ответил Revit.
    string __jnStep = "ElementId.Parse";
    try
    {
        long __jnNum = 0L;
        if (!Int64.TryParse(__jnRaw, out __jnNum))
        {
            __jnFail(__jnRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __jnStep = "Document.GetElement";
        ElementId __jnId = __sideElementId(__jnNum);
        if (__jnId == null)
        {
            __jnFail(__jnRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __jnEl = __src.GetElement(__jnId);
        if (__jnEl == null)
        {
            __jnFail(__jnRaw, "element not found in document", "element_unresolved");
            continue;
        }

        // ── ОТНОШЕНИЕ 1: с чем СОЕДИНЕНА геометрия ───────────────────────
        __jnStep = "JoinGeometryUtils.GetJoinedElements";
        var __jnJoined = new List<object>();
        ICollection<ElementId> __jnSet =
            Autodesk.Revit.DB.JoinGeometryUtils.GetJoinedElements(__src, __jnEl);
        if (__jnSet != null)
        {
            foreach (ElementId __jnOther in __jnSet)
            {
                if (__jnOther == null || __jnOther == ElementId.InvalidElementId)
                    continue;
                string __jnOtherStr = __jnOther.ToString();
                // Петля на себя отношением не является. Молча выброшенная,
                // она спрятала бы сбой чтения, поэтому её здесь просто нет:
                // разбор на питоне ОТКАЗЫВАЕТ, если она всё же придёт.
                if (__jnOtherStr == __jnRaw) continue;
                __jnJoined.Add(__jnOtherStr);
            }
        }

        // ── ОТНОШЕНИЕ 2: РАЗРЕШЕНО ли стене соединяться концом ────────────
        // Другая арность и другой вопрос. Замер 800 стен: с отношением 1 оно
        // расходится на 38 элементах из 81 — выводить одно из другого нельзя.
        __jnStep = "WallUtils.IsWallJoinAllowedAtEnd";
        object __jnEnds = null;
        Autodesk.Revit.DB.Wall __jnWall = __jnEl as Autodesk.Revit.DB.Wall;
        if (__jnWall != null)
        {
            var __jnEndList = new List<object>();
            __jnEndList.Add(
                Autodesk.Revit.DB.WallUtils.IsWallJoinAllowedAtEnd(__jnWall, 0));
            __jnEndList.Add(
                Autodesk.Revit.DB.WallUtils.IsWallJoinAllowedAtEnd(__jnWall, 1));
            __jnEnds = __jnEndList;
        }

        // ── ОТНОШЕНИЕ 3: КТО состыкован концом ───────────────────────────
        // `LocationCurve.get_ElementsAtJoin(Int32)` — свидетель, которого мы
        // считали несуществующим. Замер: две стены встык дают здесь соседа,
        // а AreElementsJoined при этом FALSE и JoinGeometry ОТКАЗЫВАЕТ, —
        // подрезка концов уже съела перекрытие тел.
        //
        // КАЖДЫЙ КОНЕЦ В СВОЁМ try, и это не стиль: ровно на общем перехвате
        // двух концов стоит де-джойн в authoring.py, где отказ первого конца
        // МОЛЧА уносит второй. Здесь отказ конца НАЗЫВАЕТСЯ и остаётся
        // отличим от «соседей нет».
        __jnStep = "LocationCurve.get_ElementsAtJoin";
        object __jnAtJoin = null;
        if (__jnWall != null)
        {
            var __jnAtList = new List<object>();
            for (int __jnEndIx = 0; __jnEndIx < 2; __jnEndIx++)
            {
                var __jnCell = new Dictionary<string, object>();
                try
                {
                    Autodesk.Revit.DB.LocationCurve __jnLc =
                        __jnEl.Location as Autodesk.Revit.DB.LocationCurve;
                    if (__jnLc == null)
                    {
                        __jnCell["read"] = false;
                        __jnCell["why"] = "Location is not a LocationCurve";
                    }
                    else
                    {
                        Autodesk.Revit.DB.ElementArray __jnAt =
                            __jnLc.get_ElementsAtJoin(__jnEndIx);
                        var __jnNeighbours = new List<object>();
                        if (__jnAt != null)
                        {
                            foreach (Autodesk.Revit.DB.Element __jnN in __jnAt)
                            {
                                if (__jnN == null || __jnN.Id == null) continue;
                                string __jnNs = __jnN.Id.ToString();
                                if (__jnNs == __jnRaw) continue;
                                __jnNeighbours.Add(__jnNs);
                            }
                        }
                        __jnCell["read"] = true;
                        __jnCell["elements"] = __jnNeighbours;
                    }
                }
                catch (Exception __jnEndEx)
                {
                    __jnCell["read"] = false;
                    __jnCell["why"] = "get_ElementsAtJoin threw "
                        + __jnClassName(__jnEndEx);
                }
                __jnAtList.Add(__jnCell);
            }
            __jnAtJoin = __jnAtList;
        }

        var __jnRow = new Dictionary<string, object>();
        __jnRow["element_id"] = __jnRaw;
        // Пустой список едет СТРОКОЙ, а не квитанцией: «ни с чем не соединён»
        // есть положительный факт о здании. Квитанция здесь значит ровно
        // «мы не посмотрели», и в этом вся её польза.
        __jnRow["joined_to"] = __jnJoined;
        if (__jnEnds != null) __jnRow["join_allowed_at_end"] = __jnEnds;
        if (__jnAtJoin != null) __jnRow["elements_at_end_join"] = __jnAtJoin;
        __jnRows.Add(__jnRow);
    }
    catch (Exception __jnEx)
    {
        __jnFail(__jnRaw,
                 "join read failed at " + __jnStep + ": "
                     + __jnClassName(__jnEx),
                 "read_failed");
    }
}

var __jnPayload = new Dictionary<string, object>();
__jnPayload["schema_version"] = __JN_SCHEMA__;
__jnPayload["elements"] = __jnRows;
__jnPayload["failures"] = __jnFailures;
return __jnPayload;
"""


def build_join_extract_cs(element_ids: list[str], *,
                          call_budget_ms: int = 20_000,
                          link_title: str | None = None) -> str:
    """The C# of one page of the joins stage.

    ``link_title`` — read not the HOST, but its link, via such a
    ``Document.Title``. The source must be a single one for the whole
    body: ``__src.GetElement`` by the link's id in the host document
    would return either null (a receipt out of nowhere) or a FOREIGN
    element with the same number — silently, indistinguishable from
    the truth.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _JOIN_BODY_CS
    body = body.replace("__JN_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__JOIN_IDS__", quoted)
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__JN_SCHEMA__", _csharp_string(JOIN_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + JOIN_HELPER_CS + body)


__all__ = [
    "JOIN_CATEGORIES",
    "JOIN_EXTRACT_SCHEMA_VERSION",
    "JOIN_INDEX_SCHEMA_VERSION",
    "JoinExtraction",
    "EndJoin",
    "EndState",
    "JoinFailure",
    "JoinPayloadError",
    "JoinRecord",
    "build_join_extract_cs",
    "extract_joins",
    "merge_joins",
]
