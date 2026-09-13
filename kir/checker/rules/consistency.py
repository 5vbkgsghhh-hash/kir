"""Declaration-consistency rules (checker v2): HAB060–HAB063.

These rules read the DerivationReport (derive.py) — the geometric witness — and flag
every place where the DECLARED model disagrees with what geometry supports. They are
the anti-self-certification layer: the fix-loop and the LLM can write any scalar they
like, but a scalar that geometry does not back is now a BLOCKING lie, not a pass.

HAB060  declared scalar vs derived geometry (area lies, window claims)   BLOCKING
HAB061  door adjacency vs geometry (phantom doors / fake exits)          BLOCKING
        (unverifiable adjacency / orphan doors / above-grade exits)      WARNING
HAB062  unclassified habitable-sized room — habitability not applied     WARNING
HAB063  floor-plate dead void (rooms-union vs closed footprint)          WARNING

Signature: check_habNNN(model, dmodel, drep, thr) -> list[Violation] — model is the
DECLARED input, dmodel the derived model, drep the DerivationReport. Run only on the
v2 engine path."""
from __future__ import annotations

import dataclasses
from typing import Any, Callable

from kir.checker.derive import DerivationReport, DoorStatus
from kir.checker.function_provenance import describe as describe_function
from kir.checker.spatial_model import (
    Severity,
    SpatialModel,
    Violation,
)
from kir.checker.thresholds import Thresholds


#: How many rooms to name BY NAME before collapsing a finding into one line
#: with a count. Not an independent value: `design_check.render_verdict`
#: prints `max_examples=3` examples per rule, `render_verdict_brief` — one,
#: so the FOURTH named line NEVER reaches the reader and lives only as an
#: object in `report.warnings`. It cannot be taken by import here — `checker`
#: sits BELOW `design_check`, and a reverse import would create a cycle; so
#: the number is duplicated, and agreement between the two carriers is held
#: by a guard.
_NAMED_ROOMS_LIMIT = 3


def profile_suspends(profile, rule_id: str) -> bool:
    """Whether the stage has suspended the rule. Asked of the law's OWNER,
    never guessed.

    An empty profile (the full "as-built" stage) suspends nothing.
    """
    if profile is None:
        return False
    return rule_id in (getattr(profile, "suspended", None) or {})


def check_hab060(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB060 — declaration consistency: every declared scalar must match geometry."""
    violations: list[Violation] = []
    names = {r.id: r.name for r in model.rooms}
    unmeasured_glazing: list[str] = []
    for rid, rd in sorted(drep.rooms.items()):
        if rd.area_mismatch and rd.derived_area_m2 is not None:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.BLOCKING,
                refs=[rid],
                msg=(f"Room '{names.get(rid, rid)}' declares area "
                     f"{rd.declared_area_m2:g} m² but its boundary polygon measures "
                     f"{rd.derived_area_m2:g} m² — the declaration is not backed by "
                     f"geometry."),
                fix_hint="Fix the boundary polygon (the geometry is the truth); the "
                         "declared area_m2 is recomputed from it.",
            ))
        if rd.window_claim_unbacked:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.BLOCKING,
                refs=[rid],
                msg=(f"Room '{names.get(rid, rid)}' declares has_window=true but NO "
                     f"window is geometrically verified for it (host wall/location must "
                     f"lie on the room's envelope-exterior boundary)."),
                fix_hint="Add a real window hosted in a wall on an exterior boundary "
                         "segment of this room — setting the scalar is not a window.",
            ))
        if rd.derived_area_m2 is None:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.WARNING,
                refs=[rid],
                msg=(f"Room '{names.get(rid, rid)}' has no measurable boundary polygon "
                     f"— its declared dimensions cannot be verified."),
                fix_hint="Give the room a valid closed boundary loop (>= 3 points, "
                         "non-zero area).",
            ))
        if not rd.window_area_measured:
            unmeasured_glazing.append(rid)
    # 🔴 ONE LINE PER BUILDING, NOT A LINE PER ROOM, AND THE THRESHOLD HERE IS
    # NOT TASTE. Without a finding, fix F-254 turns HAB031's FALSE answer into
    # SILENCE, and silence is indistinguishable from "checked and clean." But
    # a per-room line does not work either: both renderers group findings by
    # `rule_id` and print a limited number of examples (`render_verdict` —
    # three, `render_verdict_brief` — one), so from the FOURTH room on, a
    # named line never gets printed at all. Measurement on the tower's
    # numbers (2364 of 2442 rooms): per-room gives 2364 findings and
    # 671,520 bytes of JSON; as one line, one finding and 20,502 bytes — 32.8
    # times smaller FOR THE SAME PRINTED OUTPUT.
    #
    # 🔴 WHAT IS NOT HERE, THOUGH EXPECTED: the brief verdict is NOT DROWNED
    # by this stream — measurement gives 803 characters against a ceiling of
    # 1800, with no truncation. Truncation triggers on the number of DISTINCT
    # RULES, not findings, and HAB060 adds exactly one. The collapsing is
    # paid for in REPORT SIZE, not in rescuing the verdict; claiming
    # otherwise would justify a correct fix with the wrong number.
    # 🔴 DO NOT SAY THROUGH A SECOND CHANNEL WHAT THE PROFILE HAS ALREADY SAID
    # (F-254, 30.08.2026). The finding exists so that HAB031's silence does
    # not read as "checked and clean." But at a stage where HAB031 is
    # SUSPENDED by the profile, that reading is impossible by construction:
    # the reason is already named by name in the coverage line ("the program
    # sets the window by type, the dimension lives in the family — there is
    # nothing to compare"). Repeating it here would set up a SECOND CARRIER
    # of one fact — exactly what this whole module is written against — and
    # would also shift the pinned gold-path counters. Caught by the
    # `test_gold_path_axes` run: on the PROGRAM path, the finding was a
    # duplicate, not a finding.
    профиль = getattr(thr, "profile", None)
    hab031_снят = profile_suspends(профиль, "HAB031")
    if unmeasured_glazing and not hab031_снят:
        total = len(drep.rooms)
        if len(unmeasured_glazing) <= _NAMED_ROOMS_LIMIT:
            for rid in unmeasured_glazing:
                violations.append(Violation(
                    rule_id="HAB060",
                    severity=Severity.WARNING,
                    refs=[rid],
                    msg=(f"Room '{names.get(rid, rid)}': the glazing AREA was not "
                         f"measured (opening height unknown — the extractor "
                         f"substituted a stand-in), so the 1:8 daylight ratio "
                         f"(HAB031) was NOT applied to this room."),
                    fix_hint="Give the window family a readable height parameter; "
                             "the window ITSELF is confirmed, only its size is not.",
                ))
        else:
            violations.append(Violation(
                rule_id="HAB060",
                severity=Severity.WARNING,
                refs=sorted(unmeasured_glazing),
                msg=(f"Glazing AREA was NOT MEASURED in {len(unmeasured_glazing)} "
                     f"rooms out of {total}: the opening height is unknown and the "
                     f"extractor substituted a stand-in, so the 1:8 daylight ratio "
                     f"(HAB031) was NOT applied to any of them. The windows "
                     f"THEMSELVES are geometrically confirmed — only their size is "
                     f"not."),
                fix_hint="Give the window families a readable height parameter; "
                         "until then the daylight norm has no subject in these rooms.",
            ))
    return violations


def check_hab061(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB061 — door adjacency must be geometrically real (no phantom connectivity)."""
    violations: list[Violation] = []
    #: WHAT THE AUTHOR DECLARED THEMSELVES. Taken from the SOURCE model, not
    #: the derived one: derivation substitutes fields, and asking `dmodel`
    #: would mean asking ourselves.
    door_claims = {
        d.id: tuple(x for x in (d.from_room_id, d.to_room_id) if x)
        for d in model.doors
    }
    for did, dd in sorted(drep.doors.items()):
        if dd.status is DoorStatus.CONTRADICTED:
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.BLOCKING,
                refs=[did],
                msg=f"Phantom door {did!r}: {dd.note}. Its declared connectivity was "
                    f"removed from the graph.",
                fix_hint="Place the door on the shared boundary segment of the two "
                         "rooms it connects (or on the envelope for an entrance).",
            ))
        elif dd.status is DoorStatus.ORPHAN:
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.WARNING,
                refs=[did],
                msg=f"Orphan door {did!r}: touches no room and claims no room.",
                fix_hint="Remove the door or host it between two rooms / on the envelope.",
            ))
        elif dd.status is DoorStatus.UNKNOWN and dd.declared_exterior:
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.WARNING,
                refs=[did],
                msg=(f"Door {did!r} is declared EXTERIOR but geometry does not support "
                     f"it ({dd.note}) — it is NOT counted as a building exit."),
                fix_hint="A street exit must sit on the building envelope; check the "
                         "door's room phase / the unplaced room on its far side.",
            ))
        elif dd.status is DoorStatus.UNKNOWN:
            # 🔴 "UNVERIFIABLE ADJACENCY" WAS PROMISED BY THIS FILE'S HEADER
            # AND HAD NEVER BEEN ISSUED, NOT ONCE (F-355, 30.08.2026). The
            # branch above caught exactly ONE kind of unverifiability — the
            # exterior one — while an interior door whose sides geometry
            # could not read slipped away SILENTLY, with a WHOLE edge left in
            # the graph: connectivity and egress rules walked a connection
            # nobody had confirmed.
            #
            # Severity is WARNING, like the neighboring branch, and for the
            # same reason: this is a finding about OUR OWN READING, not a
            # proven defect of the building. The edge is not removed —
            # removing it would mean asserting the door does NOT exist, when
            # all we know is that we could not verify it.
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.WARNING,
                refs=[did],
                msg=(f"Door {did!r}: adjacency is UNVERIFIABLE ({dd.note}) — the "
                     f"connectivity it carries is DECLARED, not confirmed."),
                fix_hint="Give the rooms this door connects a valid closed boundary, "
                         "or fix the door's declared room ids.",
            ))
        # 🔴 THE MIRROR SIDE, SET UP 19.08.2026 — WITHOUT IT THE MISMATCH
        # PASSED SILENTLY IN ONE OF THE TWO DIRECTIONS.
        #
        # The branch above catches "declared EXTERIOR, geometry does not
        # confirm" — a lost exit. Nobody caught the reverse case, even though
        # `DoorDerivation` has carried both values from the start: they were
        # COMPUTED, WRITTEN, and compared NOWHERE — our own named defect
        # class.
        #
        # WHY THIS IS NOT COSMETIC: derivation SUBSTITUTES the value
        # (`derived_doors` gets `is_exterior=True`), and HAB003 counts an
        # exterior door at grade as an EXIT. An unnoticed mismatch FABRICATES
        # egress.
        #
        # 🔴 AND WHY THE CONDITION IS NOT `derived_exterior != declared_exterior`,
        # EVEN THOUGH THAT IS EXACTLY HOW I WROTE IT FIRST. Such a branch
        # turned red on the gold-path REFERENCE, and rightly so: the KIR
        # operation `create_door` has NO `is_exterior` field AT ALL, so on the
        # program path "declared False" is a DEFAULT, not a statement by the
        # author. Accusing it means demanding a promise the caller never
        # made — the law this same package already bought on `height_mm`
        # (every correctly built wall was rejected for "height mismatch").
        #
        # So the discriminator is taken from a field the author CAN declare —
        # connectivity. Measurement 19.08, both sides:
        #
        #   reference, d2      from='r1', touches ('r1',)  -> the author said
        #                      so, geometry confirmed: NOT a finding
        #   bad_door_in_wall   from=None, to=None,
        #     d_inwall         touches ('ent',)             -> the author said
        #                      NOTHING, geometry says: a finding
        #
        # Severity is WARNING, like the neighboring branch: this is a
        # mismatch in DECLARATION, not a proven defect of the building; the
        # consequence is named in the text.
        elif (dd.derived_exterior and not dd.declared_exterior
                and not (door_claims.get(did) or ())):
            touching = ", ".join(dd.touching_room_ids) or "the envelope"
            violations.append(Violation(
                rule_id="HAB061",
                severity=Severity.WARNING,
                refs=[did],
                msg=(f"Door {did!r} claims NO room (from/to both empty) yet geometry "
                     f"places it on {touching} and derives it EXTERIOR — it IS counted "
                     f"as a building exit, so egress is judged on a value the author "
                     f"never declared."),
                fix_hint="Declare the room(s) this door connects, or move it off the "
                         "envelope if it is not an entrance.",
            ))
    for did in sorted(drep.above_grade_exterior_door_ids):
        violations.append(Violation(
            rule_id="HAB061",
            severity=Severity.INFO,
            refs=[did],
            msg=(f"Exterior door {did!r} sits above the grade band — treated as a "
                 f"balcony/terrace door, not ground egress."),
            fix_hint="",
        ))
    return violations


def check_hab062(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB062 — an unclassified (ПРОЧЕЕ) room of habitable size is UNVERIFIABLE, not
    exempt: the dimension/light rules silently skip it, so say so out loud."""
    violations: list[Violation] = []
    by_id = {r.id: r for r in dmodel.rooms}
    for rid in drep.unclassified_room_ids:
        room = by_id.get(rid)
        if room is None:
            continue
        rd = drep.rooms.get(rid)
        area = rd.derived_area_m2 if (rd and rd.derived_area_m2 is not None) else room.area_m2
        if area is None or area < thr.unclassified_min_area_m2:
            continue
        violations.append(Violation(
            rule_id="HAB062",
            severity=Severity.WARNING,
            refs=[rid],
            msg=(f"Room '{room.name}' ({area:g} m²) has an UNCLASSIFIED function — the "
                 f"habitability rules (area/width/height/daylight) were NOT applied to it."),
            fix_hint="Name the room recognizably (спальня/кухня/санузел/…) or stamp an "
                     "explicit function; unknown ≠ exempt.",
        ))
    violations.extend(_hab062_guessed(dmodel, drep, thr))
    return violations


def _hab062_guessed(dmodel: SpatialModel, drep: DerivationReport,
                    thr: Thresholds) -> list[Violation]:
    """GUESSED ≠ READ — the second half of the law "unknown ≠ exempt."

    🔴 WHAT WAS RED HERE (07.09.2026). HAB062 iterates over
    `drep.unclassified_room_ids`, and a room whose function was named by
    FURNISHING LEAVES that list. Rules do get applied to it — and HAB062's
    silence reads as "applied to something read," when in fact it was applied
    to a toilet. A guess was SUPPRESSING the warning; exactly the direction
    `function_provenance` was set up against on 22.08, and exactly what was
    closed for HAB003/HAB010 on 07.09.

    No new carrier was needed: `drep.derived_function_room_ids` has been
    computed in `derive` since 22.08 and sits in the report this rule
    ALREADY receives.

    🔴 THERE IS ONE LINE, AND THIS IS A MEASUREMENT, NOT TASTE. On the
    fixture corpus with function fully derived, there are 236 of 276 such
    rooms. The reader will not see two hundred thirty-six separate findings:
    `design_check.render_verdict` prints three examples per rule,
    `render_verdict_brief` — one, and the rest lives only as objects in
    `report.warnings` (the same argument as `_NAMED_ROOMS_LIMIT` above). So
    here it is a COUNT plus the first `_NAMED_ROOMS_LIMIT` names, with the
    full list in `refs`, where a machine will pick it up, not an eye.
    """
    by_id = {r.id: r for r in dmodel.rooms}
    названные: list[str] = []
    for rid in drep.derived_function_room_ids:
        room = by_id.get(rid)
        if room is None:
            continue
        rd = drep.rooms.get(rid)
        area = rd.derived_area_m2 if (rd and rd.derived_area_m2 is not None) else room.area_m2
        if area is None or area < thr.unclassified_min_area_m2:
            continue
        названные.append(rid)
    if not названные:
        return []
    голова = ", ".join(
        f"'{by_id[rid].name}' ({by_id[rid].function.value})"
        for rid in названные[:_NAMED_ROOMS_LIMIT])
    ещё = len(названные) - _NAMED_ROOMS_LIMIT
    хвост = f" и ещё {ещё}" if ещё > 0 else ""
    источники = sorted({by_id[rid].function_source or "" for rid in названные})
    return [Violation(
        rule_id="HAB062",
        severity=Severity.WARNING,
        refs=sorted(названные),
        msg=(f"У {len(названные)} помещений жилого размера "
             f"(>= {thr.unclassified_min_area_m2:g} m²) функцию назвал НЕ АВТОР, "
             f"и правила пригодности применены к ней как к прочитанной: "
             f"{голова}{хвост}. {describe_function(источники[0])}"),
        fix_hint="Назовите помещения в модели (ROOM_NAME) либо проставьте функцию "
                 "явно: угаданное ≠ прочитанное, как неизвестное ≠ освобождённое.",
    )]


def check_hab063(model: SpatialModel, dmodel: SpatialModel,
                 drep: DerivationReport, thr: Thresholds) -> list[Violation]:
    """HAB063 — floor-plate dead void: rooms must substantially cover the closed level
    footprint (the DeepSeek 26%-void case). WARNING instrument (courtyards dip legitimately)."""
    violations: list[Violation] = []
    for lid, coverage in sorted(drep.floorplate_coverage.items()):
        if coverage < thr.min_floorplate_coverage:
            violations.append(Violation(
                rule_id="HAB063",
                severity=Severity.WARNING,
                refs=[lid],
                msg=(f"Level {lid}: rooms cover only {coverage * 100:.0f}% of the closed "
                     f"floor plate (< {thr.min_floorplate_coverage:.0%}) — large dead "
                     f"void / unusable in-between space."),
                fix_hint="Fill the plate with rooms or shrink the envelope; every m² "
                         "inside the envelope should belong to a room.",
            ))
    return violations


@dataclasses.dataclass(frozen=True)
class ConsistencyRule:
    """A consistency rule plus ITS OWN population of subjects.

    🔴 THE `subjects` FIELD DID NOT EXIST, AND ALL FOUR REPORTED THE ROOM
    COUNT (29.08.2026, audit finding F-134). The engine wrote
    `n_subjects=len(model.rooms)` identically for all of them, whereas they
    each iterate over DIFFERENT things:

        HAB060  drep.rooms                 rooms cross-checked
        HAB061  drep.doors                 doors cross-checked
        HAB062  drep.rooms                 classification outcome for each
        HAB063  drep.floorplate_coverage   levels with computed coverage

    Live: a model of seven rooms and ZERO doors printed
    `HAB061 EVALUATED(n=7), 0 нарушений` — that is, "doors cross-checked and
    clean" where there were no doors at all. The number is correct — just
    not about the right subject: an instrument that is truthful about a
    DIFFERENT population is the most convincing form of lying, precisely
    because there is nothing to object to.

    `vacuous_reason` is mandatory for the same reason as at `RuleSpec`:
    emptiness comes in our own kind ("we did not ask") and the building's
    kind ("we asked, it answered NO"), and they must not be printed the same
    way.
    """

    rule_id: str
    fn: Callable
    subjects: Callable[[Any], int]
    vacuous_reason: str

    def __iter__(self):
        """Compatibility with unpacking as `for rid, fn in REGISTRY`.

        Kept on purpose: the registry is read in five places, two of them
        tests asserting the rule list's completeness. Breaking their shape
        for a field they do not need would mean changing someone else's
        contract along with our own.
        """
        return iter((self.rule_id, self.fn))


#: Ordered v2 consistency registry (engine runs these before the geometric ruleset).
CONSISTENCY_REGISTRY = [
    ConsistencyRule("HAB060", check_hab060,
                    lambda drep: len(drep.rooms),
                    "ни одно помещение не было сверено: сверять нечего"),
    ConsistencyRule("HAB061", check_hab061,
                    lambda drep: len(drep.doors),
                    "ни одна дверь не была сверена: сверять нечего"),
    # 🔴 WHAT IS COUNTED IS NOT THE UNIDENTIFIED, BUT ALL PARSED ROOMS, AND
    # THIS IS NOT NITPICKING. Zero unidentified rooms is a KNOWN CLEAN RESULT
    # ("we looked, everything is identified"), not the absence of a
    # measurement. Counting the violations themselves as subjects would mean
    # printing `NOT_EVALUATED` exactly when the rule performed best — that
    # is, saying "unknown" where it is known. This is the very defect being
    # fixed, just turned inside out. The rule's subject is the CLASSIFICATION
    # OUTCOME for each parsed room; it is empty if and only if not a single
    # room was parsed.
    ConsistencyRule("HAB062", check_hab062,
                    lambda drep: len(drep.rooms),
                    "ни одно помещение не разобрано: исход классификации "
                    "не определён ни у кого"),
    ConsistencyRule("HAB063", check_hab063,
                    lambda drep: len(drep.floorplate_coverage),
                    "покрытие плиты не посчитано ни на одном уровне"),
]
