"""THE ASSEMBLY SEEN AS ONE OBJECT: addressed observations, no prose.

WHY. The verifiability apparatus works at arity 1 — one op, one
postcondition. Intent lives at arity N: «four walls closed the loop», «a
door landed in a wall», «a column stands on nothing». Facts like these ARE
COUNTED in the tree — and they scatter across four channels in four forms:
HAB rules as prose in `building` (a 2600-character ceiling, fail-open, chat
door only), a clash in `result["clash"]` only on the bulk door and absent
when the flag is off, the building graph as a note in the viewer's scene
header, `coherence` — as Russian-language strings for the prompt.

This module does not recount them. It COLLECTS them into one form fit for
reading by a MODEL, not a human.

THREE LAWS, EACH ONE PAID FOR BY A MEASUREMENT.

1. **AN OBSERVATION MUST HAVE AN ADDRESS.** An observation without an
   address gives the model nothing it can fix: «the loop is not closed»
   without wall names is just tone of voice. The address taken is THE ONE
   THE READER CAN ACT ON: at the program stage that is the operation's id,
   not an ElementId, which does not exist yet — AND IT NAMES ITS OWN
   PROGRAM (`p1/w1`), because `id` is unique only WITHIN a program, while
   the summary speaks of a BUNDLE. A bare `w1` in a bundle of two programs
   is not an address but a name collision: the 30.08 measurement showed
   eight different walls under four names in one observation. The form is
   borrowed from the bundle judge, not invented here (see
   `program_address`).

2. **THE CODE LIST IS CLOSED.** A new kind of observation must be entered
   here, or it will travel into the report nameless. This is the same
   device as `BLIND_CLASSES` with no default.

3. **A SOURCE'S SILENCE IS A RECORD, NOT AN EMPTINESS.** If the judge
   refused or crashed, its refusal travels into `silent_sources` WITH A
   REASON. Without this, an absence of observations reads as «everything is
   fine», and that is exactly the silently-wrong result the whole compiler
   is built against.

WHAT THIS MODULE DOES NOT DO, AND THIS IS THE OWNER'S DECISION, NOT AN
OVERSIGHT. It DOES NOT REFUSE. No observation turns the record red or
touches acceptance. The diagnosis is «the model builds blind», not «the
model writes garbage»; we treat blindness, not freedom. A wrong invariant
in a gate would reject a lawful building and look like a broken product; a
wrong invariant in a narrator is just an imprecise hint.

THE SOURCE BOUNDARY, NAMED HERE. There are now TWO doors, and they judge
DIFFERENT things: `observe_program` — what the program DECLARED
(`ModelSource.PROGRAM`), `observe_l0` — what was BUILT, re-read at L0
(`ModelSource.PARSE`), by the same rules and the same `check_design`. That
is why the `source` field always rides along in the response: the reader
must know whether it is judging the intent or the building.

THE HONEST BOUNDARY OF THIS SECOND DOOR, so it is not read as a closed
loop. It judges an ALREADY-read L0 and does not itself re-read Revit;
nothing in the live recording flow calls it yet. That is, the `PARSE`
branch has stopped being unreachable from this module, and it has NOT
become a participant in the turn — these are two different things, and the
second one is a trip to the bridge away.

AND THE ADDRESSES OF THE TWO DOORS LIE IN DIFFERENT SPACES — see
`address_space`.

🔴 A BOUNDARY INHERITED FROM THE JUDGE, WHICH THE SUMMARY'S READER NEEDS TO
KNOW (measured by recon on 15.08). `hab:*` observations arrive from the
verdict, and `design_check` UNCONDITIONALLY SKIPS SIX RULES:
`HAB002/003/004/042` (`_APARTMENT_ORACLE_RULES`, skipped in
`design_stage_profile` — the accuracy of apartment inference was measured
on 03.08 and is damning, 0 % on dwelling composition) plus `HAB031` (no
opening area in the snapshot) and `HAB050` (`create_wall` has no
load-bearing-wall parameter).

Which means: **evacuation, apartment composition, and the closure of an
apartment's envelope will NEVER appear in this summary** — not because the
building passes them, but because the rules never judged them. Their
absence from the observations IS NOT evidence. The summary does not hide
this: a skipped rule does not even land in `silent_sources`, so the reader
is left with THIS line — and that is exactly why it is here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence
from kir import ports

#: OBSERVATION CODES. The list is CLOSED and COMPLETE BY CONSTRUCTION for
#: the sources already wired in; a source producing a code not from here
#: crashes the assembly instead of printing it silently.
#:
#: `hab:*` — codes of fitness rules, arriving AS-IS (`rule_id`), because
#: they already have a closed registry in `checker/engine.RULE_REGISTRY`,
#: and giving the same rule a second name would mean maintaining two lists.
OBSERVATION_CODES: tuple[str, ...] = (
    "enclosure_ok",          # walls closed off an area; the number is the area, m²
    "enclosure_none",        # walls declared, closed off NOTHING
    "no_walls",              # there are no walls in the program at all — nothing to judge
    # --- structural coherence (`design/coherence`). The names are OURS,
    # because that module has no code registry: it returns Russian report
    # keys. Here they get a name once, in a closed list.
    "column_off_slab",       # a column does not stand on any slab
    "wall_off_slab",         # a wall does not stand on any slab
    "beam_unsupported",      # a beam has an end that does not reach a column
    # --- UNIT OF INTENT (`course.unit(reads_as=...)`). Arity N: a fact not
    # about an element, but about HOW A SET OF ELEMENTS READS. A
    # postcondition cannot say this by construction — it stands on a
    # single op.
    "unit_not_continuous",   # the unit's members do not read as one continuous thing
)

#: Prefix for codes arriving from a foreign closed registry. Such a code is
#: passed through without checking against `OBSERVATION_CODES`, and this is
#: NAMED: its completeness is held OVER THERE, and duplicating the rule
#: registry here would mean maintaining two lists that must match and are
#: linked by nothing.
#: `preview:*` — plan-anomaly codes (`preview.AnomalyReason`), also its own
#: closed registry, also arriving AS-IS, for the same reason.
FOREIGN_CODE_PREFIXES: tuple[str, ...] = ("hab:", "preview:")


# ══════════════════════════════════════════════════════════════════════════
# THE ADDRESS NAMES ITS PROGRAM (F-174)
# ══════════════════════════════════════════════════════════════════════════
#
# 🔴 WHAT WAS MEASURED, BY EXECUTION, ON 30.08.2026. One and the same
# summary carried TWO DIFFERENT ADDRESS FORMS under one declared `op_id`
# namespace:
#
#     hab:HAB060      at=["p1/r1"]   <- QUALIFIED by the judge
#     enclosure_ok    at=["w_s","w_e","w_n","w_w","w_s","w_e","w_n","w_w"]
#                                    <- BARE: eight different walls, four names
#
# The defect is not that a name repeats: `id` is unique WITHIN a program,
# and two independently written programs will both name their first wall
# `w_s` — that is LEGITIMATE. The defect is that the reader cannot say
# which of the two to fix, and that right next to it lies an address that
# CAN say so.
#
# 🔴 THE FORM WAS NOT INVENTED HERE, IT WAS BORROWED. The bundle judge
# adopted it earlier, with a rationale (`design_check._bundle_oid`): the
# program's position is ONE-BASED, comes first, is joined by `/`, and is
# qualified ALWAYS, not only on collision — otherwise the address would
# drift depending on what the NEIGHBORING program happens to contain.
# Introducing a second form here would mean maintaining two lists that must
# match — exactly the defect this module is written against.
#
# THE REPEAT IS GUARDED BY A NUMBER, NOT A PROMISE: `kir/tests/
# test_an_assembly_address_names_its_program.py` checks our output against
# the judge's output and goes red if the forms drift apart.

#: Separator of the qualified address — the same one the bundle judge uses.
PROGRAM_SEP = "/"

#: A position THAT DOES NOT EXIST. Placed where the address came from a
#: source that merged programs (`design.coherence`), and the `id` is
#: claimed by more than one of them: there is no way to say which one is
#: meant. This is neither «первая» nor «неважно» — it is a NAMED refusal,
#: and it is strictly better than a silent choice in favor of whichever
#: comes first.
UNKNOWN_PROGRAM = "p?"

#: Address spaces the summary can lie in. The value always rides along in
#: the response (`AssemblyView.address_space`): comparing addresses from
#: different spaces without noticing is our named defect.
ADDRESS_SPACE_OP = "op_id"
ADDRESS_SPACE_PROGRAM_OP = "program/op_id"
ADDRESS_SPACE_ELEMENT = "element_id"


def program_address(position: int, op_id: str) -> str:
    """An operation's address AT BUNDLE SCALE: program position + own id.

    `position` is ONE-BASED — the bundle's first program is `p1`, same as
    for the judge. The rationale for the form lives with the judge
    (`design_check._bundle_oid`) and is NOT REPEATED here: two accounts of
    one rationale drift apart the same way two lists do.
    """
    return "p%s%s%s" % (position, PROGRAM_SEP, op_id)


def _owners_by_op_id(programs: Sequence[Any]) -> dict[str, list[int]]:
    """Operation `id` -> the positions of the bundle programs that claim it.

    Needed ONLY by sources that merged programs before handing out
    addresses (`design.coherence` computes support across the program
    boundary and must see all slabs at once — computing it per-link would
    declare everything resting on a neighbor's slab unsupported). A source
    that works PER-LINK knows its own position and does not use this table.
    """
    owners: dict[str, list[int]] = {}
    for index, program in enumerate(programs, start=1):
        for op in _ops_of(program):
            raw = op.get("id")
            if raw in (None, ""):
                continue
            seen = owners.setdefault(str(raw), [])
            if index not in seen:
                seen.append(index)
            for member in (op.get("members") or ()):
                if not isinstance(member, Mapping):
                    continue
                mid = member.get("id")
                if mid in (None, ""):
                    continue
                seen_m = owners.setdefault(str(mid), [])
                if index not in seen_m:
                    seen_m.append(index)
    return owners


def _qualify_merged(op_id: str, owners: dict[str, list[int]]) -> str:
    """An address from a merged source -> qualified, or NAMED not-knowing.

    Three outcomes, and each must be distinguishable:
      one program    -> `p2/w1`, an exact address;
      several        -> `p?/w1`, cannot say — and this is said out loud;
      none           -> the address is not from the bundle's operation space
                        (a rule addressed to a room or a level), returned
                        AS-IS. Assigning it a program would mean making one
                        up.
    """
    holders = owners.get(op_id) or ()
    if len(holders) == 1:
        return program_address(holders[0], op_id)
    if holders:
        return "%s%s%s" % (UNKNOWN_PROGRAM, PROGRAM_SEP, op_id)
    return op_id


# ══════════════════════════════════════════════════════════════════════════
# UNIT-READING PREDICATES — AN OPEN REGISTRY
# ══════════════════════════════════════════════════════════════════════════
#
# 🔴 THE KIND OF THIS LIST: **OPEN FOR ADDITION.** This is neither «closed
# but incomplete» nor «complete by construction» — a third kind, and it is
# declared here explicitly, because the kind determines what the ABSENCE of
# an entry means. The absence of a predicate here means: WE DO NOT YET KNOW
# HOW TO CHECK THIS WAY OF READING. Not «the set does not read this way»
# and not «we decided it wasn't needed».
#
# WHY OPEN, AND WHY THIS IS NOT A WEAKNESS. The owner rejected a dictionary
# of COMPOSITES in the registry, and rejected it rightly: buildings are
# unboundedly many, and a closed list of nouns over an open domain breaks
# on the first object that does not fit it. But what is listed here is NOT
# BUILDINGS. What is listed here is the WAYS A SET OF ELEMENTS CAN READ,
# and their units are: continuous · coaxial · coplanar · stacked-by-level ·
# closing. The composite remains a function the model writes ITSELF; all it
# brings here is the answer to the question «как это читать».
#
# THE REQUIREMENT FOR EVERY RESIDENT, WITHOUT WHICH IT IS NOT A RESIDENT:
# its own FAIL control. A predicate that cannot say «нет» is not a
# predicate but decoration — it is green by construction and measures
# nothing (form 18: green without an act of discrimination). The
# `test_unit_reads.py` ratchet requires a pair for every name — «violating
# input -> finding» AND «healthy input -> empty» — and goes red when a name
# is added without that pair.

#: Joint tolerance, MM. Above the measured noise of `anchor_mm` (0.5 mm,
#: the fold measurement) and below any gap an author would write
#: intentionally.
UNIT_JOIN_TOL_MM = 1.0

#: Coaxiality tolerance — PERPENDICULAR DEVIATION IN MM, not a cross
#: product. The canon names comparing an mm tolerance against an mm²
#: product its own named defect (`_on_segment`, `_point_in_prism`); here
#: the quantity and the tolerance are in the same unit by construction.
UNIT_COLLINEAR_TOL_MM = 1.0

#: Fields whose mismatch makes neighboring segments DIFFERENT things, even
#: when their ends meet and they lie on the same axis. This is exactly the
#: «striped wall»: continuous in geometry, striped in reading.
_READS_SAME_FIELDS: tuple[str, ...] = ("type", "height_mm")


def _seg(op: Mapping[str, Any]) -> tuple[tuple[float, float],
                                         tuple[float, float]] | None:
    """An op's plan segment, MM. `None` — the op carries no segment."""
    p0, p1 = op.get("p0_mm"), op.get("p1_mm")
    try:
        return ((float(p0[0]), float(p0[1])), (float(p1[0]), float(p1[1])))
    except (TypeError, IndexError, ValueError):
        return None


def _dist_mm(a: tuple[float, float], b: tuple[float, float]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _off_line_mm(a: tuple[float, float], b: tuple[float, float],
                 p: tuple[float, float]) -> float:
    """Distance from point `p` to the LINE through `a`,`b` — in millimeters."""
    length = _dist_mm(a, b)
    if length <= 0.0:
        return _dist_mm(a, p)
    # The cross product is divided by the length -> mm² / mm = mm. This
    # division is exactly what makes the quantity comparable to an mm
    # tolerance.
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return abs(cross) / length


def reads_continuous(members: Sequence[Mapping[str, Any]]
                     ) -> list[tuple[str, tuple[str, ...]]]:
    """«These elements read as ONE continuous thing» — a strip, an axis, a
    thread.

    Returns a list of breaks: (reason, addresses of participants). Empty —
    it reads.

    WHAT «CONTINUOUS» MEANS AND WHY EXACTLY THAT. Three walls end-to-end
    are not a defect by themselves: a real strip is often assembled from
    segments (different axes, an expansion joint, a change of floor). The
    defect is when a set is DECLARED one thing but cannot read as one.
    Exactly three things are checked, and all three are about READING, not
    taste:

      `gap`          neighboring segments' ends do not meet: there is a
                     hole or an overlap between them. The reader will see
                     two objects, the author declared one;
      `kink`         ends meet, but the next one departs from the previous
                     one's axis: that is a kink — two directions, not one
                     thread;
      `type_differs` / `height_differs` — ends meet and are coaxial, but
                     declared different. THIS IS EXACTLY THE STRIPED WALL:
                     continuous in geometry, striped in reading.

    WHAT THIS PREDICATE DOES NOT DO, AND THIS IS NAMED. It does not judge
    INTENT: if the author declared as a strip something that should not be
    one, the predicate stays silent — it checks the declared reading, not
    the choice of reading. And it does not look at the floor: two walls
    from the same plan on different levels would meet ends in plan, so the
    level enters the comparison as an ordinary field (see the call site).

    A SINGLE MEMBER CANNOT FAIL, and this is said out loud: there is
    nothing to compare against. Running this predicate's control on a
    sample of one is green BY CONSTRUCTION — exactly the canon's
    «degenerate control» — which is why the ratchet requires the control
    pair to have power >= 2.
    """
    breaks: list[tuple[str, tuple[str, ...]]] = []
    prev: tuple[str, tuple, tuple] | None = None
    for member in members:
        oid = str(member.get("id") or "")
        seg = _seg(member)
        if seg is None:
            continue
        if prev is not None:
            prev_id, prev_a, prev_b = prev
            pair = (prev_id, oid)
            if _dist_mm(prev_b, seg[0]) > UNIT_JOIN_TOL_MM:
                breaks.append(("gap", pair))
            elif _off_line_mm(prev_a, prev_b, seg[1]) > UNIT_COLLINEAR_TOL_MM:
                breaks.append(("kink", pair))
        prev = (oid, seg[0], seg[1])

    # FIELD MISMATCH IS COUNTED OVER THE WHOLE SET, not just neighbors: a
    # stripe in the middle of a strip is a mismatch with both neighbors,
    # and naming it twice would count one defect as two.
    for field_name in _READS_SAME_FIELDS:
        seen: dict[str, list[str]] = {}
        for member in members:
            if _seg(member) is None or field_name not in member:
                continue
            key = _canonical_json_key(member.get(field_name))
            seen.setdefault(key, []).append(str(member.get("id") or ""))
        if len(seen) > 1:
            odd = sorted(seen.items(), key=lambda kv: (-len(kv[1]), kv[0]))
            # MINORITIES are addressed: they are what needs fixing, not the
            # majority.
            addresses = tuple(oid for _key, ids in odd[1:] for oid in ids)
            breaks.append(("%s_differs" % field_name.replace("_mm", ""),
                           addresses))
    return breaks


def _canonical_json_key(value: Any) -> str:
    """Comparable key for a field's value. A selector dict is compared AS
    A WHOLE: `{"by":"name","value":"Витраж 200"}` and
    `{"by":"name","value":"Кирпич"}` — different types, and the difference
    must be visible."""
    import json as _json
    try:
        return _json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


#: READING NAME -> PREDICATE. Open for addition; every resident must have a
#: control pair in `test_unit_reads.py` (violation -> finding, healthy ->
#: empty), or the ratchet goes red.
UNIT_READS: dict[str, Any] = {
    "continuous": reads_continuous,
}

#: A human explanation of each reading — travels to the author in the
#: REFUSAL when they named a nonexistent name. The keys must match
#: `UNIT_READS` character for character, and this is enforced by a test,
#: not a convention.
UNIT_READS_RU: dict[str, str] = {
    "continuous": "одна непрерывная вещь: лента, ось, нитка — концы сходятся, "
                  "направление не ломается, тип и высота едины",
}


#: The name this module presents itself to the judge with. Not fit for
#: COMPARISON: every caller has its own (`live.verdict` calls the judge
#: with «здание этой сессии (пачка программ)»), and a constant here would
#: produce exactly the defect this module is written against — asserting
#: in one place and reading in another. The building name for comparison
#: is ASKED OF THE VERDICT (`verdict.building_id`).
BUILDING_ID = "(сборка)"


class AssemblyViewError(ValueError):
    """A law of form is violated: a code outside the list, or an
    observation without an address."""


#: How many addresses ONE observation carries. A four-wall box is the most
#: common subject of conversation, and it must fit whole; a re-read
#: building gives 690 walls (measurement `sob62_r23_v5`, 15.08), and a list
#: like that is no longer an address — you cannot act on it, only page
#: through it.
#:
#: 🔴 CANNOT TRUNCATE SILENTLY: a truncated list that does not say it was
#: truncated reads as complete, and decisions get made on it as if it were
#: complete. That is why the observation carries `address_total` — how many
#: addresses there ACTUALLY WERE.
ADDRESS_CAP = 12


@dataclass(frozen=True)
class Observation:
    """One observation about the ASSEMBLY: what, about whom, how much."""

    code: str
    #: addresses the reader can act on. NON-EMPTY by construction.
    address: tuple[str, ...]
    #: the observation's measure; `None` — the measure is not defined for
    #: this code, not «zero».
    number: float | None = None
    #: 🔴 THIS IS A UNIT OF MEASUREMENT («м²»), NOT A UNIT OF INTENT. The
    #: name was taken earlier and is not renamed: `to_dict` reads it, and so
    #: does everything that looks into the receipt. The unit of intent is
    #: the neighboring field `of_unit`, and the two are NOT synonyms. A
    #: homonym under one word is the very kind of error that, on 13.08,
    #: nearly led to the conclusion «изоляция уже записывается».
    unit: str = ""
    #: THE ADDRESS OF THE UNIT OF INTENT in which these elements are
    #: written (`unit_id` from the envelope's `units` table). Empty — the
    #: observation is not about a unit.
    #: Stands ALONGSIDE `address`, not instead of it: element addresses say
    #: what to fix, the unit's address says in which intent this was
    #: written, and losing the latter means sending the model back to
    #: reading its own program element by element.
    of_unit: str = ""
    #: how many addresses the observation has IN TOTAL. 0 — «as many as
    #: shown». More than `len(address)` — the list is truncated, and the
    #: response must say so.
    address_total: int = 0

    def __post_init__(self) -> None:
        if not self.address:
            raise AssemblyViewError(
                "наблюдение %r без адреса: читателю нечего править" % self.code)
        if self.address_total and self.address_total < len(self.address):
            raise AssemblyViewError(
                "наблюдение %r: показано %d адресов при заявленных %d — "
                "усечение не может быть отрицательным"
                % (self.code, len(self.address), self.address_total))
        known = (self.code in OBSERVATION_CODES
                 or self.code.startswith(FOREIGN_CODE_PREFIXES))
        if not known:
            raise AssemblyViewError(
                "код %r вне закрытого списка наблюдений" % self.code)

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"code": self.code, "at": list(self.address)}
        if self.of_unit:
            row["of_unit"] = self.of_unit
        if self.address_total > len(self.address):
            # The full number always rides along when the list is
            # incomplete: without it the reader cannot tell «these four
            # walls» from «four out of six hundred ninety».
            row["at_of"] = self.address_total
        if self.number is not None:
            row["n"] = self.number
            if self.unit:
                row["unit"] = self.unit
        return row


@dataclass(frozen=True)
class AssemblyView:
    """What is visible about the assembly — and what is NOT visible, with
    a named reason."""

    observations: tuple[Observation, ...] = ()
    #: source -> why it said nothing. An empty dict = everyone answered.
    silent_sources: dict[str, str] = field(default_factory=dict)
    #: who was asked. Without this, «zero observations» is indistinguishable
    #: from «not asked».
    sources_asked: tuple[str, ...] = ()
    #: judged what was DECLARED or what was BUILT
    source: str = "program"
    #: 🔴 WHAT SPACE THE ADDRESSES LIE IN. Two summaries about the same
    #: building can address it DIFFERENTLY: intent knows only the
    #: operation id, qualified by the program's position (`p1/w1`) — an
    #: ElementId does not yet exist at the program stage — while a re-read
    #: building knows only Revit's `element_id` (`4001`). There are exactly
    #: three values, and all three are named by name:
    #: `ADDRESS_SPACE_PROGRAM_OP` (a bundle was submitted),
    #: `ADDRESS_SPACE_OP` (a flat list without a bundle was submitted),
    #: `ADDRESS_SPACE_ELEMENT` (re-read). The 15.08 measurement confirmed a
    #: shared address across the
    #: FOUR WORLDS OF DECOMPILATION (`tools/address_spine.py`: fold,
    #: building_graph, SpatialModel — zero addresses outside L0 on two
    #: buildings). It said NOTHING about the program, and could not: L0 has
    #: no program addresses by construction.
    #:
    #: There is exactly one bridge between the two spaces — the write
    #: receipt (`result["w1"]["id"] == "9001"`). Until summaries are
    #: stitched together through it, the field must ride along in the
    #: response: comparing observations from different spaces without
    #: noticing is exactly our named defect.
    address_space: str = ADDRESS_SPACE_OP

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "assembly-view/1",
            "source": self.source,
            "address_space": self.address_space,
            "asked": list(self.sources_asked),
            "silent": dict(self.silent_sources),
            "observations": [o.to_dict() for o in self.observations],
        }


def _wall_op_ids(ops: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(op.get("id")) for op in ops
            if op.get("op") == "create_wall" and op.get("id") is not None]


def _ops_of(program: Any) -> list[Mapping[str, Any]]:
    if isinstance(program, Mapping):
        raw = program.get("ops")
        if isinstance(raw, Sequence):
            return [op for op in raw if isinstance(op, Mapping)]
    return []


def observe_program(program: Any) -> AssemblyView:
    """Observations about the assembly of ONE KIR program — from what is
    already being computed.

    No new geometry appears here at all: closure is computed by
    `design_check` via planar partitioning, with a tolerance chosen by
    measurement on a real building (100 mm; 0→11.3 %, 100→37.8 % of
    measurable rooms).
    """
    ops = _ops_of(program)
    walls = _wall_op_ids(ops)
    asked: list[str] = ["design_check", "preview", "coherence"]
    silent: dict[str, str] = {}
    out: list[Observation] = []

    if not walls:
        # WE DO NOT STAY SILENT. «There are no walls» and «there are
        # walls, but they closed off nothing» are different facts, and the
        # reader must be able to tell them apart; otherwise an empty list
        # of observations reads as «everything is fine».
        # `preview` is asked HERE TOO: «no walls» does not mean «nothing
        # to look at» — an opening with no host and an unclosed room can
        # exist without a single wall in the program. Skipping the source
        # while leaving it in `asked` would mean lying about who was
        # asked.
        anomalies, preview_silence = observe_plan_anomalies([program])
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence([program])
        silent.update(coherence_silence)
        return AssemblyView(
            observations=((Observation("no_walls", address=("(программа)",)),)
                          + tuple(anomalies) + tuple(loose)),
            silent_sources=silent, sources_asked=tuple(asked))

    try:
        from kir import design_check as _dc
        verdict = _dc.check_bundle([program], building_id=BUILDING_ID)
    except Exception as exc:  # noqa: BLE001 — the judge's refusal IS DATA
        silent["design_check"] = "%s: %s" % (type(exc).__name__, str(exc)[:160])
        anomalies, preview_silence = observe_plan_anomalies([program])
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence([program])
        silent.update(coherence_silence)
        return AssemblyView(observations=tuple(anomalies) + tuple(loose),
                            silent_sources=silent, sources_asked=tuple(asked))

    return observe_verdict(verdict, walls, programs=[program])


def observe_plan_anomalies(
        programs: Sequence[Any]) -> tuple[list[Observation], dict[str, str]]:
    """PLAN anomalies — the summary's second source, and it sees what the
    judge does not.

    🔴 WHY A SECOND SOURCE, IF THERE IS A FIRST ONE. The 15.08 measurement
    on three programs: one wall 0→6000, three walls end-to-end, and TWO
    WALLS IN THE SAME PLACE all gave `design_check` the SAME
    `enclosure_none` answer. Only the address list differed, and it speaks
    to how many walls were written — not about the assembly. A summary
    that answers the same way on a healthy input and a duplicated one
    measures nothing. `preview` tells duplicates apart from axis endpoints
    alone, in 0.1 ms, including the case where the second wall is drawn in
    the opposite direction.

    WHAT THIS SOURCE DOES NOT SEE, named by itself (`preview.BLIND_SPOTS`):
    a plan is an XY slice, it has no heights, no envelope closure, and no
    3D intersections. So it SUPPLEMENTS the judge, rather than replacing
    it.

    WHY THE CODES CARRY A PREFIX INSTEAD OF BEING RENAMED. `AnomalyReason`
    has its own closed registry; giving the same phenomena a second name
    here would mean maintaining two lists that must match — the very
    defect the module is written against.
    """
    out: list[Observation] = []
    silent: dict[str, str] = {}
    try:
        from kir import preview as _pv
    except Exception as exc:  # noqa: BLE001
        return out, {"preview": "%s: %s" % (type(exc).__name__, str(exc)[:120])}

    for index, program in enumerate(programs):
        try:
            plan = _pv.build_program_preview(program)
        except Exception as exc:  # noqa: BLE001 — the source's refusal IS DATA
            silent.setdefault(
                "preview" if len(programs) == 1 else "preview[%d]" % index,
                "%s: %s" % (type(exc).__name__, str(exc)[:140]))
            continue
        # Anomalies of one kind are collected into ONE observation: ten
        # duplicates are one kind of defect in ten places, not ten
        # different pieces of news.
        by_reason: dict[str, list[str]] = {}
        for sheet in getattr(plan, "plans", ()) or ():
            for element in getattr(sheet, "elements", ()) or ():
                raw_address = str(getattr(element, "element_id", "") or "")
                if not raw_address:
                    continue
                # THE SOURCE WORKS PER-LINK: the plan is built for ONE
                # program, so its position is known exactly and no owner
                # table is needed. We qualify ALWAYS, not only on
                # collision — the rationale belongs to the bundle judge.
                address = program_address(index + 1, raw_address)
                for reason in getattr(element, "anomalies", ()) or ():
                    code = str(getattr(reason, "value", reason))
                    seen = by_reason.setdefault(code, [])
                    if address not in seen:
                        seen.append(address)
        for code, addresses in by_reason.items():
            out.append(Observation(
                "preview:" + code, address=tuple(addresses[:ADDRESS_CAP]),
                address_total=len(addresses)))
    return out, silent


#: `coherence` report key -> our observation code. The list is CLOSED: a
#: new kind of incoherence must get a name here, or it will travel into the
#: report nameless.
_COHERENCE_CODES: tuple[tuple[str, str], ...] = (
    ("колонн_вне_плиты_адреса", "column_off_slab"),
    ("стен_вне_плиты_адреса", "wall_off_slab"),
    ("балок_без_опоры_адреса", "beam_unsupported"),
)


def observe_units(
        programs: Sequence[Any]) -> tuple[list[Observation], dict[str, str]]:
    """UNITS OF INTENT — a source that works at ARITY N.

    🔴 WHY THIS EXISTS AT ALL, IN ONE SENTENCE. All the rest of the
    apparatus checks arity 1: op -> element -> postcondition. Intent lives
    at arity N — «three neighboring walls MUST read as one strip» — and a
    postcondition cannot say this by construction: it stands on a single
    op and knows nothing about its neighbor. A striped wall passes all
    three of the witness's axes, because each wall is flawless on its own.
    Here a SET is read.

    WHERE THE SET COMES FROM. From the envelope's `units` table, which
    `course.unit(...)` writes AS A SLICE — following the pattern of
    `phase()`. The ops themselves remain byte-for-byte the same: their
    digest signs the program, and a unit number written into every op
    would shift the signature of a building that had not changed.

    WHY MEMBERS ARE LOOKED UP TWO WAYS. A unit can be written as a Revit
    group (`as_group=True`, today's default) — then its members lie
    INSIDE the `create_group` op; or as a slice (`as_group=False`) — then
    they lie at the program's top level. The reading does not depend on
    this, and the predicate must answer the same way either time: the way
    it was WRITTEN does not change how the set READS.

    SILENCE IS NAMED. A unit without `reads_as` is not judged — the author
    did not say how to read it, and inventing one on their behalf would
    mean shouting about everything indiscriminately (`silent_sources`). A
    name outside the registry never makes it here: `course.unit()` rejects
    it at write time, with a list of known names.
    """
    out: list[Observation] = []
    silent: dict[str, str] = {}
    seen_any = False

    for index, program in enumerate(programs):
        if not isinstance(program, Mapping):
            continue
        units = program.get("units")
        if not units:
            continue
        ops_by_id: dict[str, Mapping[str, Any]] = {}
        for op in (program.get("ops") or ()):
            if isinstance(op, Mapping) and op.get("id") is not None:
                ops_by_id[str(op["id"])] = op
                # a group's members are also addressable ops
                for member in (op.get("members") or ()):
                    if isinstance(member, Mapping) and member.get("id") is not None:
                        ops_by_id[str(member["id"])] = member
        for row in units:
            if not isinstance(row, Mapping):
                continue
            unit_id = str(row.get("unit_id") or "")
            reads_as = row.get("reads_as")
            if not reads_as:
                continue
            seen_any = True
            predicate = UNIT_READS.get(str(reads_as))
            if predicate is None:
                # A name the registry does not know made it through: the
                # registry is OPEN, so this is «we don't know how to check
                # this» rather than «a violation». We stay silent with a
                # reason.
                silent["unit:%s" % unit_id] = (
                    "прочтение %r не в реестре предикатов — проверить нечем"
                    % reads_as)
                continue
            members = [ops_by_id[str(mid)]
                       for mid in (row.get("member_ids") or ())
                       if str(mid) in ops_by_id]
            if len(members) < 2:
                # A DEGENERATE INPUT IS NAMED, NOT PASSED THROUGH SILENTLY:
                # on a single member, every continuity predicate is green
                # by construction, and green here would mean «проверено»,
                # even though there is nothing to compare against. This is
                # the canon's form 18, caught at the input.
                silent["unit:%s" % unit_id] = (
                    "членов %d — предикату %r нечего сравнивать (нужно >= 2)"
                    % (len(members), reads_as))
                continue
            try:
                breaks = predicate(members)
            except Exception as exc:  # noqa: BLE001 — the source's refusal IS DATA
                silent["unit:%s" % unit_id] = (
                    "%s: %s" % (type(exc).__name__, str(exc)[:140]))
                continue
            if not breaks:
                continue
            addresses: list[str] = []
            reasons: list[str] = []
            for reason, ids in breaks:
                reasons.append(reason)
                for oid in ids:
                    if not oid:
                        continue
                    # A UNIT LIVES INSIDE ONE PROGRAM (it is written by
                    # `course.unit` as a slice of ITS OWN program), so the
                    # position is known exactly. Without it, two programs,
                    # each with its own `d1,d2` strip, gave TWO
                    # BYTE-FOR-BYTE IDENTICAL observations — an executed
                    # measurement from 30.08, F-174.
                    address = program_address(index + 1, oid)
                    if address not in addresses:
                        addresses.append(address)
            if not addresses:
                continue
            # THE CODE IS DERIVED FROM THE READING NAME, NOT WRITTEN AS A
            # LITERAL. The predicate registry is OPEN, the code list is
            # CLOSED — and this is not a contradiction but a seam that
            # must creak: a new predicate without its own code travels
            # into silence WITH A REASON, meaning it demands a decision,
            # instead of leaning on someone else's code and becoming
            # indistinguishable from it in the receipt.
            code = "unit_not_%s" % reads_as
            if code not in OBSERVATION_CODES:
                silent["unit:%s" % unit_id] = (
                    "предикат %r есть, а кода %r в закрытом списке наблюдений "
                    "нет: назови код, иначе находка неотличима от чужой"
                    % (reads_as, code))
                continue
            shown = tuple(addresses[:ADDRESS_CAP])
            out.append(Observation(
                code=code,
                address=shown,
                of_unit=unit_id or "(без адреса)",
                number=float(len(breaks)),
                unit="разрыв",
                address_total=len(addresses)))
    if not seen_any and not out:
        return out, silent
    return out, silent


def observe_coherence(
        programs: Sequence[Any]) -> tuple[list[Observation], dict[str, str]]:
    """Structural coherence — the third source: what STANDS ON NOTHING.

    🔴 WHY IT DID NOT EXIST BEFORE 15.08, EVEN THOUGH IT HAS LONG BEEN
    COMPUTED. `coherence.check` used to return COUNTERS with no addresses
    («колонн_вне_плиты: 404»), and the summary's first law demands an
    address that can be acted on: the model cannot fix «404 columns in the
    air». The cause of the counters sat one function up — `flatten` held
    the operation's `id` in its hands and did not carry it over into
    `Elem`. The source was not missing; it was cut off by ONE FIELD. This
    is our default form of failure: the work is done and not connected.

    WHAT THIS SOURCE SEES THAT THE OTHER TWO DO NOT. The judge speaks of
    rooms and envelope, the plan speaks of coincidences in an XY slice.
    Neither one answers «does this column stand on anything»: that is a
    relation BETWEEN floors, i.e. arity N along the vertical.

    A BOUNDARY NAMED BY A NUMBER: the slab-edge tolerance of 300 mm and
    the beam reach of 1500 mm live in `coherence` and are chosen there;
    they are not re-asked or duplicated here. A program with no slabs
    gives «off the slab» to EVERYTHING — that is true and useless, so at
    zero slabs the source stays silent WITH A REASON, instead of flooding
    the summary.
    """
    out: list[Observation] = []
    try:
        _co = ports.need(ports.DESIGN_COHERENCE)
    except Exception as exc:  # noqa: BLE001
        return out, {"coherence": "%s: %s" % (type(exc).__name__, str(exc)[:120])}

    try:
        elements = _co.flatten(list(programs))
        report = _co.check(elements)
    except Exception as exc:  # noqa: BLE001 — the source's refusal IS DATA
        return out, {"coherence": "%s: %s" % (type(exc).__name__, str(exc)[:140])}

    if not int(report.get("плит") or 0):
        # A DEGENERATE INPUT, NAMED OUT LOUD. Without slabs, «stands on
        # nothing» is true for EVERY element and does not tell healthy
        # from broken — green (here, red) without an act of
        # discrimination.
        return out, {"coherence": "плит в программе нет: «вне плиты» было бы "
                                  "верно для всех и не различало бы ничего"}

    # 🔴 THE ONLY MERGED SOURCE, AND IT IS MERGED FOR GOOD REASON.
    # `flatten` must see all programs at once: a column of the second
    # program stands on a slab of the first, and a source computed
    # per-link would declare it unsupported. So it cannot return the
    # program's position, and the address is resolved by the OWNER
    # TABLE — with a named outcome where there is more than one owner.
    owners = _owners_by_op_id(programs)
    for key, code in _COHERENCE_CODES:
        addresses = [_qualify_merged(str(a), owners)
                     for a in (report.get(key) or ()) if a]
        if addresses:
            out.append(Observation(code, address=tuple(addresses[:ADDRESS_CAP]),
                                   address_total=len(addresses)))
    return out, {}


def _source_name(witness: Any, verdict: Any) -> str:
    """«program» or «parse» — TAKEN FROM THE WITNESS'S WORD, not from the
    door's name.

    The witness is asked, not the caller: `observe_verdict` is an open
    door, and a verdict from the PARSE path can be submitted to it
    directly. Deciding by which function was called would mean asserting
    the source in one place and reading it in another.
    """
    for holder in (witness, verdict):
        raw = getattr(holder, "source", None)
        if raw is not None:
            return str(getattr(raw, "value", raw) or "program")
    return "program"


def observe_l0(document: Any, *, building_id: str | None = None) -> AssemblyView:
    """Observations about the BUILT building — by the SAME rules.

    🔴 THE SECOND HALF OF WHOLENESS. A single entry point for rules was
    declared as a TYPE (`ModelSource`), but only the `PROGRAM` branch was
    alive: the product judged INTENT and called it checking the RESULT.
    Here `spatial_model_from_l0` is called (`ModelSource.PARSE`), and the
    same `check_design` — not one new rule, not one new piece of geometry.
    Only the model's source differs, and `source` in the response says so.

    THE FORM OF THE CALL IS PART OF THE CONTRACT, AND IT COST A FALSE
    CONCLUSION. `L0JSONLReader.metadata()` returns the HEADER: levels,
    grids, rooms; `elements` in it is empty by construction. Feed it the
    header and you get «0 walls» on a building that has 695 — and this
    reads as the branch's inability to read walls. What is passed in here
    is the WHOLE DOCUMENT (header plus `iter_elements()`); the whole
    building can be checked with the `tools/address_spine.py` instrument.

    WHAT THIS DOOR DOES NOT DO. It does not re-read Revit — it judges an
    ALREADY-read L0. Only a live bridge can close the loop «wrote →
    re-read → judged», and that is separate work with a separate turn
    cost.
    """
    asked = ("design_check",)
    try:
        from kir import design_check as _dc
        model, witness = _dc.spatial_model_from_l0(
            document, building_id=building_id)
        verdict = _dc.check_design(model, witness)
    except Exception as exc:  # noqa: BLE001 — the judge's refusal IS DATA
        return AssemblyView(
            observations=(),
            silent_sources={"design_check": "%s: %s"
                            % (type(exc).__name__, str(exc)[:160])},
            sources_asked=asked, source="parse",
            address_space=ADDRESS_SPACE_ELEMENT)

    walls = [str(getattr(wall, "id", "")) for wall in (model.walls or ())]
    view = observe_verdict(verdict, [w for w in walls if w])
    # Addresses here are Revit's `element_id`, not operation ids: what is
    # judged is the built thing.
    return AssemblyView(
        observations=view.observations, silent_sources=view.silent_sources,
        sources_asked=view.sources_asked, source=view.source,
        address_space=ADDRESS_SPACE_ELEMENT)


def observe_verdict(verdict: Any, wall_ids: Sequence[str], *,
                    programs: Sequence[Any] = ()) -> AssemblyView:
    """The same thing, but from an ALREADY-COMPUTED verdict.

    🔴 WHY A SEPARATE DOOR. `live.verdict.judge` calls the same judge on
    every turn and discards the verdict object into prose. Calling
    `check_bundle` again just for the summary would mean opening a SECOND
    JUDGMENT ABOUT THE SAME THING — paying for it twice (the `serving`
    header measurement: ~0.4 ms per operation), and getting two answers
    with nothing to guarantee they match. Here, what is already computed
    is read.
    """
    silent: dict[str, str] = {}
    out: list[Observation] = []
    # 🔴 A WALL'S ADDRESS NAMES ITS PROGRAM WHEN A BUNDLE IS SUBMITTED
    # (F-174). The caller submits a FLAT list of walls for the whole
    # bundle, and on it two programs, each with its own `w_s`, gave the
    # address `[w_s, …, w_s, …]`: eight different walls under four names,
    # and the reader has nothing to fix. The work here is FINISHED, not
    # declared impossible: the bundle's order is known, and the same wall
    # predicate (`_wall_op_ids`) reads it per-link.
    #
    # THE CALLER IS NOT SWAPPED SILENTLY: without `programs` (the
    # `observe_l0` door, the `element_id` space), the list taken is
    # exactly the one submitted. Today both live callers count walls with
    # the SAME predicate over the SAME bundle — this is a second carrier
    # of one piece of knowledge, and it is guarded by a number
    # (`test_an_assembly_address_names_its_program.py`).
    if programs:
        walls = [program_address(index, oid)
                 for index, program in enumerate(programs, start=1)
                 for oid in _wall_op_ids(_ops_of(program))]
        space = ADDRESS_SPACE_PROGRAM_OP
    else:
        walls = [str(w) for w in wall_ids]
        space = ADDRESS_SPACE_OP
    # THE BUILDING NAME BELONGS TO THE VERDICT, NOT TO US. Comparing
    # against our own constant was correct exactly on our call path, and
    # leaked `HAB000` into the observations the moment `live.verdict`
    # called the summary with its own building name (live measurement,
    # 15.08).
    building_id = str(getattr(verdict, "building_id", "") or BUILDING_ID)

    witness = getattr(verdict, "witness", None)
    # The full address count rides along with the ones shown: on a
    # program of four walls it is the same thing; on a re-read building of
    # 690, it is not.
    shown, total = tuple(walls[:ADDRESS_CAP]), len(walls)

    # 🔴 ASK THE WITNESS WHETHER IT ANSWERED THIS QUESTION AT ALL, RATHER
    # THAN READING THE NUMBER. `partition_faces` computes ONLY for
    # `spatial_model_from_program`: on the PARSE path the partition is
    # deliberately not built — room contours are taken exactly as Revit
    # returned them, and recomputing them with a worse copy is not
    # allowed. So on the parsed path the field is zero BY CONSTRUCTION.
    #
    # The first edition read the zero as an answer and produced
    # `enclosure_none` on a building where 107 of 120 rooms carry a
    # measured contour (live measurement `sob62_r23_v5`, 15.08). This is a
    # silently-wrong observation — exactly the outcome the whole compiler
    # is written against, and it was caught not by output, but by the
    # question «does the instrument even compute this value on this
    # input».
    source_name = _source_name(witness, verdict)
    if source_name == "program":
        faces = int(getattr(witness, "partition_faces", 0) or 0)
        if faces > 0:
            out.append(Observation("enclosure_ok", address=shown,
                                   address_total=total,
                                   number=float(faces), unit="граней"))
        elif shown:
            out.append(Observation("enclosure_none", address=shown,
                                   address_total=total))
        else:
            # 🔴 WITHOUT WALLS THIS IS NOT «DID NOT CLOSE», BUT «NOTHING TO
            # JUDGE» (F-171, 29.08.2026). `enclosure_none` was being built
            # with an EMPTY address, and `Observation.__post_init__`
            # forbids such an address («the reader has nothing to fix») —
            # the exception flew out of the observation itself, and the
            # live wrapper swallowed it silently, TAKING THE WHOLE
            # SUMMARY WITH IT. Measurement: the summary is absent in every
            # one of 65 corpus frames, and the cause is named nowhere.
            #
            # The code and address form are taken from the ALREADY
            # EXISTING wall-less branch of this same module (`no_walls`,
            # address=("(программа)",)): a second way of saying the same
            # thing would split one dictionary into two.
            out.append(Observation("no_walls", address=("(программа)",)))
    else:
        silent["design_check:enclosure"] = (
            "разбиение на этом пути не строится: контуры помещений взяты у "
            "Revit, и замкнутость отвечается ими, а не нашим разбиением")

    # HAB violations arrive with THEIR OWN codes and THEIR OWN addresses
    # (`refs`), because they already have both. Our job is not to rename
    # them.
    report = getattr(verdict, "report", None)
    for bucket in ("blocking", "warnings"):
        for violation in list(getattr(report, bucket, ()) or ()):
            rule = str(getattr(violation, "rule_id", "?"))
            refs = tuple(str(r) for r in (getattr(violation, "refs", ()) or ()))
            if not refs or refs == (building_id,):
                # 🔴 A RULE ADDRESSED TO THE WHOLE BUILDING IS SILENCE
                # WITH A REASON, NOT AN OBSERVATION. A live case:
                # `HAB000` («в модели нет помещений») on a program of
                # walls alone. It is true and says nothing about the
                # ASSEMBLY — it says there was nothing to judge. Putting
                # it into the observations would mean handing the model
                # the address `(сборка)`, which cannot be acted on —
                # against this module's own law of addresses.
                silent.setdefault(
                    "design_check:" + rule,
                    str(getattr(violation, "msg", ""))[:140] or "без сообщения")
                continue
            out.append(Observation("hab:" + rule, address=refs))

    asked = ["design_check"]
    if programs:
        # THE SECOND SOURCE IS ASKED ONLY WHERE THERE IS SOMETHING TO ASK.
        # `preview` reads the PROGRAM; on the PARSE path there is none,
        # and silently substituting emptiness there would mean saying «no
        # anomalies» instead of «not asked».
        asked.extend(("preview", "coherence", "units"))
        anomalies, preview_silence = observe_plan_anomalies(programs)
        out.extend(anomalies)
        silent.update(preview_silence)
        loose, coherence_silence = observe_coherence(programs)
        out.extend(loose)
        silent.update(coherence_silence)
        # THE FOURTH SOURCE — UNITS OF INTENT, and it is the only one
        # that reads a SET. The three previous ones judge an element
        # (closure by walls, plan anomaly, structural support); this one
        # answers a question that at arity 1 is never even posed: «does
        # what is written read the way the author declared it». It
        # stands here, rather than behind a separate door, because the
        # live path already calls `observe_verdict` with `programs`
        # (`live.verdict._with_assembly`) — a new door would have
        # required cutting into someone else's file for the same call.
        unit_obs, unit_silence = observe_units(programs)
        out.extend(unit_obs)
        silent.update(unit_silence)

    return AssemblyView(observations=tuple(out), silent_sources=silent,
                        sources_asked=tuple(asked), source=source_name,
                        address_space=space)


#: Digest ceiling. Measured against the reader, not chosen: history is
#: collapsed by `chat_helpers._summarize_tool_result`, and it leaves a
#: top-level string WHOLE up to exactly 120 characters, cutting anything
#: longer with an ellipsis. Lists and dicts are replaced with
#: «<N элем. — свёрнуто>», with nothing left over.
DIGEST_LIMIT = 120

#: How many addresses we show for one observation. Four — because a
#: four-wall box is the most common subject of conversation, and cutting
#: it off at the third wall means losing exactly the one that was
#: missing.
DIGEST_ADDRESSES = 4


def digest(view: "AssemblyView", limit: int = DIGEST_LIMIT) -> str:
    """A flat string that SURVIVES history collapsing.

    🔴 WHY A SEPARATE FORM, IF STRUCTURE ALREADY EXISTS. A perception the
    model cannot RECALL is not a loop. The structural summary reaches the
    model within the turn (ceiling 50,000), but only 5,000 is kept in
    history, and past thirty messages `_summarize_tool_result` replaces
    EVERY dict and list with «свёрнуто». Only top-level scalars survive
    from the receipt — and the digest is written so as to be one of them.

    NEVER LOOKS COMPLETE WHILE BEING TRUNCATED. Unshown observations are
    counted in a `+N` tail, silent sources in a `?K` tail. A string that
    silently cuts off is worse than an absent one: a decision gets made
    on it as if it were complete (the same argument by which history does
    not hand back truncated JSON).
    """
    if not view.observations and not view.silent_sources:
        return "сборка: не измерена"

    head = "сборка: "
    parts: list[str] = []
    shown = 0
    for obs in view.observations:
        addrs = list(obs.address[:DIGEST_ADDRESSES])
        tail = "+%d" % (len(obs.address) - len(addrs)) if len(obs.address) > len(addrs) else ""
        piece = "%s@%s%s" % (obs.code, ",".join(addrs), tail)
        if obs.of_unit:
            # THE UNIT'S ADDRESS RIDES ALONG IN THE FLAT STRING TOO. The
            # digest is the only thing that survives history collapsing;
            # an arity-N observation that loses its unit there sends the
            # model back to reading its own program element by
            # element — exactly what the unit was introduced to prevent.
            #
            # 🔴 PARENTHESES, NOT A SLASH (30.08.2026). The slash is
            # already taken by address qualification (`p1/d1`), and
            # `…@p1/d1,p1/d2/u1` cannot be parsed by anything: where the
            # address ends and the unit begins cannot be derived from the
            # string. A separator that becomes a homonym loses both
            # meanings.
            piece += "[%s]" % obs.of_unit
        if obs.number is not None:
            piece += "=%g" % obs.number
        candidate = head + "; ".join(parts + [piece])
        # the tail is counted IN ADVANCE: the string must fit TOGETHER
        # with it
        reserve = len(" +%d" % (len(view.observations) - shown - 1)) + \
            (len(" ?%d" % len(view.silent_sources)) if view.silent_sources else 0)
        if len(candidate) + reserve > limit:
            break
        parts.append(piece)
        shown += 1

    out = head + "; ".join(parts) if parts else head.strip()
    hidden = len(view.observations) - shown
    if hidden > 0:
        out += " +%d" % hidden
    if view.silent_sources:
        out += " ?%d" % len(view.silent_sources)
    return out
