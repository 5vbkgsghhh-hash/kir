"""Rule engine for the building correctness checker (design §2/§11).

`run(model, thr=THRESHOLDS)` is a PURE function (design §11.1, no I/O): it builds the
connectivity graph once (via graph.build_graph), runs every rule in the explicit
RULE_REGISTRY with the injected thresholds, aggregates the returned Violations, bins
them by severity, and returns a CheckReport whose `passed` is True iff there is no
BLOCKING violation (design §6). `thr` is defaulted and injectable for profile swaps.

The registry is EXPLICIT and ORDERED on purpose: the set of active rules is a
reviewable, version-controlled list — not implicit module discovery — so adding,
removing, or reordering a rule is a visible, intentional diff (matches the keystone's
'deterministic oracle' mandate).

checker v2 (flags.checker_v2_enabled, env KUKAI_CHECKER_V2=1) replaces the verdict
pipeline while keeping every rule's v1 signature:

  1. degenerate gate    — an empty model is BLOCKING (HAB000) + verdict NOT_EVALUATED,
                          never a silent pass (kills the HAB000 INFO theater);
  2. derivation         — derive.py recomputes every rule-relevant scalar from geometry
                          and produces the DerivationReport witness;
  3. consistency rules  — HAB060..063 flag every declared-vs-derived disagreement;
  4. geometric rules    — the classic registry runs against the DERIVED model
                          (rules read measurements, not claims);
  5. coverage + verdict — every rule gets an EVALUATED(n)/NOT_EVALUATED(reason) outcome
                          from the RULE_SPECS_V2 subjects table; `passed=True` requires
                          zero BLOCKING **and** every mandatory rule evaluated real
                          subjects **and** classification/measurement coverage above
                          floor. Anything else is FAIL or NOT_EVALUATED. Unknown ≠ pass.

`thr.profile` (a `StageProfile`, default None = the full as-built rule set) selects
WHICH rules a given design stage may be judged by, and WHICH SUBJECTS each of them is
entitled to speak about (`subject_inputs`: a rule may not fire on an input it does not
have — see `SUBJECT_INPUTS` below). A suspended rule does not run at all
— it cannot pass, fail, or accuse — and its coverage row carries the profile's own
reason; `profile.mandatory` overrides whether the verdict may depend on a rule that does
run. The profile's NAME travels in `CoverageInfo.profile_name`, so a report can never
show a rule count without saying which stage produced it (design 2026-08-03: with
HAB011 mandatory-on-any-stair, every design-stage building read NOT_EVALUATED forever).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import networkx as nx

from kukai.modeling.checker.derive import DerivationReport, derive
from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.graph import build_graph, derive_apartments, occupied_levels
from kukai.modeling.checker.spatial_model import (
    CheckReport,
    CoverageInfo,
    RoomFunction,
    RuleOutcome,
    RuleStatus,
    Severity,
    SpatialModel,
    Verdict,
    Violation,
)
from kukai.modeling.checker.thresholds import (
    THRESHOLDS,
    StageProfile,
    Thresholds,
)
from kukai.modeling.checker.rules import (
    clash,
    connectivity,
    consistency,
    dimensions,
    light,
    structure,
    vertical,
)

# Explicit, ordered registry — each entry is a pure rule function with the uniform
# signature check_habNNN(model, graph, thr) -> list[Violation]. Order = the §6 table.
RULE_REGISTRY = [
    connectivity.check_hab001,
    connectivity.check_hab002,
    connectivity.check_hab003,
    connectivity.check_hab004,
    connectivity.check_hab010,
    vertical.check_hab011,
    vertical.check_hab012,
    dimensions.check_hab020,
    dimensions.check_hab021,
    dimensions.check_hab022,
    light.check_hab030,
    light.check_hab031,
    clash.check_hab040,
    clash.check_hab041,
    clash.check_hab042,
    structure.check_hab050,
]


# ----------------------------------------------------------------------- v2 machinery

@dataclass(frozen=True)
class _V2Context:
    """Everything a subjects-counter may inspect (computed once per run)."""
    model: SpatialModel          # the DERIVED model the rules actually see
    drep: DerivationReport
    graph: nx.Graph
    apartments: list             # derived apartments (service rooms excluded)


@dataclass(frozen=True)
class RuleSpec:
    """v2 coverage row: how to count a rule's real subjects, and whether the verdict
    depends on it. `mandatory` may itself depend on the model (e.g. HAB011 matters only
    when stairs exist). The rule fn ALWAYS runs; subjects==0 marks the outcome
    NOT_EVALUATED so vacuity is visible instead of indistinguishable from a pass."""
    fn: Callable
    rule_id: str
    subjects: Callable[[_V2Context], int]
    vacuous_reason: str
    mandatory: Callable[[_V2Context], bool]


def _n_measured_rooms(ctx: _V2Context) -> int:
    return sum(1 for rd in ctx.drep.rooms.values() if rd.derived_area_m2 is not None)


def _n_area_rule_subjects(ctx: _V2Context) -> int:
    checked = {RoomFunction.ЖИЛАЯ, RoomFunction.КУХНЯ, RoomFunction.САНУЗЕЛ}
    return sum(
        1 for r in ctx.model.rooms
        if r.function in checked
        and ctx.drep.rooms.get(r.id) is not None
        and ctx.drep.rooms[r.id].derived_area_m2 is not None
    )


def _n_daylit_subjects(ctx: _V2Context) -> int:
    return sum(1 for r in ctx.model.rooms
               if r.function in (RoomFunction.ЖИЛАЯ, RoomFunction.КУХНЯ))


def _n_measured_stairs(ctx: _V2Context) -> int:
    return sum(1 for s in ctx.model.stairs
               if s.kind == "element" and s.run_width_mm is not None
               and s.riser_count is not None and s.tread_depth_mm is not None)


RULE_SPECS_V2: list[RuleSpec] = [
    RuleSpec(connectivity.check_hab001, "HAB001",
             lambda c: len(c.model.rooms), "no rooms",
             lambda c: True),
    RuleSpec(connectivity.check_hab002, "HAB002",
             lambda c: len(c.apartments), "no derived apartments",
             lambda c: False),
    RuleSpec(connectivity.check_hab003, "HAB003",
             lambda c: len(c.apartments), "no derived apartments — egress unverifiable",
             lambda c: True),
    RuleSpec(connectivity.check_hab004, "HAB004",
             lambda c: len(c.apartments), "no derived apartments",
             lambda c: False),
    RuleSpec(connectivity.check_hab010, "HAB010",
             lambda c: len(occupied_levels(c.model)), "no occupied levels",
             lambda c: True),
    RuleSpec(vertical.check_hab011, "HAB011",
             _n_measured_stairs,
             "stairs present but none has measured geometry (unknown ≠ pass)"
             , lambda c: len(c.model.stairs) > 0),
    RuleSpec(vertical.check_hab012, "HAB012",
             lambda c: sum(1 for s in c.model.stairs if s.footprint),
             "no stair footprints to compare",
             lambda c: False),
    RuleSpec(dimensions.check_hab020, "HAB020",
             _n_area_rule_subjects,
             "no classified habitable/kitchen/bathroom room with measurable geometry",
             lambda c: True),
    RuleSpec(dimensions.check_hab021, "HAB021",
             _n_measured_rooms, "no measurable room boundaries",
             lambda c: False),
    RuleSpec(dimensions.check_hab022, "HAB022",
             lambda c: sum(1 for r in c.model.rooms if r.height_mm is not None),
             "no room has a known ceiling height",
             lambda c: False),
    RuleSpec(light.check_hab030, "HAB030",
             _n_daylit_subjects, "no classified жилая/кухня rooms — daylight unverifiable",
             lambda c: True),
    RuleSpec(light.check_hab031, "HAB031",
             _n_daylit_subjects, "no classified жилая/кухня rooms",
             lambda c: False),
    RuleSpec(clash.check_hab040, "HAB040",
             _n_measured_rooms, "no measurable room boundaries",
             lambda c: False),
    RuleSpec(clash.check_hab041, "HAB041",
             lambda c: len(c.model.doors), "no doors",
             lambda c: False),
    RuleSpec(clash.check_hab042, "HAB042",
             lambda c: len(c.apartments), "no derived apartments",
             lambda c: False),
    RuleSpec(structure.check_hab050, "HAB050",
             lambda c: sum(1 for w in c.model.walls if w.is_structural),
             "no structural walls flagged — structural continuity unexamined",
             lambda c: False),
]

_CONSISTENCY_IDS = [rid for rid, _ in consistency.CONSISTENCY_REGISTRY]


#: Closed vocabulary of per-subject inputs a profile may require, and how to test
#: one subject for it. The predicate answers ONE question: does this subject carry
#: the input the rule reads? Nothing here judges the building.
SUBJECT_INPUTS: dict[str, tuple[str, Callable]] = {
    # a room whose boundary polygon never formed has NO area and NO width: the
    # scalars are zeros standing in for unknowns (Room.area_m2 cannot spell None)
    "room_polygon": ("rooms", lambda subject, drep: (
        drep.rooms.get(subject.id) is not None
        and drep.rooms[subject.id].derived_area_m2 is not None)),
    # Room.height_mm CAN spell None, and the rules already skip it — this exists so
    # the coverage row says how many were skipped instead of leaving it implicit
    "room_height": ("rooms", lambda subject, drep: subject.height_mm is not None),
    # a door touching no measurable room has no known side: "connects no room" would
    # be a statement about the extraction, not about the door
    "door_adjacency": ("doors", lambda subject, drep: bool(
        subject.from_room_id or subject.to_room_id or subject.is_exterior)),
}

#: Closed vocabulary of MODEL-WIDE preconditions. Each answers "does the derivation
#: actually hold the thing this rule reasons about", and each carries the sentence a
#: reader needs when it does not.
PRECONDITIONS: dict[str, tuple[Callable, str]] = {
    "ground_level_known": (
        lambda ctx: bool(ctx.drep.ground_level_ids),
        "ни один уровень не признан уровнем земли: наружной двери НА КОЛЬЦЕ ОБОЛОЧКИ "
        "в полосе над низшим занятым уровнем не нашлось. «Не спускается к земле» "
        "сравнивало бы этаж с землёй, которой у проверки нет"),
    # НЕ «есть хоть одна площадка», а «есть площадка на КАЖДОМ уровне, который
    # обслуживает лестница». Слабая форма пропускает ровно тот случай, ради которого
    # предусловие и заведено: замер 03.08 (snowdon) — 26 лестниц, площадки размечены
    # на 3 уровнях из 9, и HAB010 обвинил 8 уровней в том, что у них нет связи с
    # землёй, хотя лестницы там есть, а нет их РАЗМЕТКИ ПОМЕЩЕНИЯМИ.
    "stair_landings_complete": (
        lambda ctx: not (
            {lvl for stair in ctx.model.stairs
             for lvl in (stair.base_level_id, stair.top_level_id)}
            - {room.level_id for room in ctx.model.rooms
               if room.function is RoomFunction.ЛЕСТНИЦА}),
        "лестницы обслуживают уровни, на которых НЕТ помещения с функцией «лестница»: "
        "вертикальные рёбра графа строятся только через такие помещения "
        "(`graph._landing_room_on_level`), поэтому «этаж висит» здесь — свойство "
        "разметки помещений, а не здания"),
    "building_entrance_known": (
        lambda ctx: any(
            door.is_exterior and (door.from_room_id or door.to_room_id)
            for door in ctx.model.doors),
        "ни одна дверь не подтверждена как вход с улицы (положительное членство в "
        "кольце оболочки) — «недостижимо от входа» сравнивало бы с входом, которого "
        "проверка не нашла"),
    "apartments_derived": (
        lambda ctx: bool(ctx.apartments),
        "вывод квартиры не дал ни одной квартиры — судить о квартирах нечем"),
}


#: Rules whose subjects are examined INDEPENDENTLY, so pruning the subject list
#: narrows the rule's scope without changing its meaning. Read off the rule sources
#: (rules/*.py, 2026-08-03): each of these iterates model.rooms / model.doors and
#: decides per element. Connectivity rules (HAB002/003/004/010/042) are ABSENT on
#: purpose — they reason about components and paths, and a pruned model would make
#: them answer a different question while looking like the same one.
_ROOM_FILTERABLE = frozenset({"HAB001", "HAB020", "HAB021", "HAB022",
                              "HAB030", "HAB031", "HAB040", "HAB062"})
_DOOR_FILTERABLE = frozenset({"HAB041", "HAB061"})


def _filtered_subjects(model: SpatialModel, drep: DerivationReport,
                       rule_id: str, input_name: str) -> tuple[SpatialModel, int, str]:
    """Return (model the rule may speak about, how many subjects were withheld, why)."""
    if input_name not in SUBJECT_INPUTS:
        raise ValueError(f"unknown subject input {input_name!r} for {rule_id}")
    collection, has_input = SUBJECT_INPUTS[input_name]
    if collection == "rooms":
        if rule_id not in _ROOM_FILTERABLE:
            raise ValueError(
                f"{rule_id} does not examine rooms independently — pruning its model "
                "would change what it asks, not only what it asks about")
        kept = [room for room in model.rooms if has_input(room, drep)]
        withheld = len(model.rooms) - len(kept)
        return model.model_copy(update={"rooms": kept}), withheld, input_name
    if rule_id not in _DOOR_FILTERABLE:
        raise ValueError(
            f"{rule_id} does not examine doors independently — pruning its model "
            "would change what it asks, not only what it asks about")
    kept_doors = [door for door in model.doors if has_input(door, drep)]
    withheld = len(model.doors) - len(kept_doors)
    return model.model_copy(update={"doors": kept_doors}), withheld, input_name


def _suspended_reason(profile: "StageProfile", rule_id: str) -> str:
    """The coverage reason for a rule this stage does not run.

    The profile NAME is carried inside the reason as well as in
    `CoverageInfo.profile_name`: a coverage row is read on its own far more often than
    the header above it, and "not evaluated" without the stage that decided so is the
    kind of half-fact that gets quoted as "the checker passed it"."""
    return (f"suspended by stage profile {profile.name!r}: "
            f"{profile.suspension_reason(rule_id)}")


def _is_mandatory(profile: "StageProfile | None", spec: RuleSpec,
                  ctx: _V2Context) -> bool:
    """May the verdict depend on this rule? The profile overrides the rule's own
    predicate; absent an override the engine's default stands, so a profile that
    mentions nothing changes nothing."""
    if profile is not None and spec.rule_id in profile.mandatory:
        return bool(profile.mandatory[spec.rule_id])
    return spec.mandatory(ctx)


def _bin(violations, blocking, warnings, info):
    for violation in violations:
        if violation.severity is Severity.BLOCKING:
            blocking.append(violation)
        elif violation.severity is Severity.WARNING:
            warnings.append(violation)
        else:
            info.append(violation)


def _sorted_buckets(blocking, warnings, info):
    blocking.sort(key=lambda v: (v.rule_id, tuple(v.refs)))
    warnings.sort(key=lambda v: (v.rule_id, tuple(v.refs)))
    info.sort(key=lambda v: (v.rule_id, tuple(v.refs)))
    return blocking, warnings, info


def _run_v2(model: SpatialModel, thr: Thresholds) -> CheckReport:
    """The geometry-first pipeline (see module docstring)."""
    blocking: list[Violation] = []
    warnings: list[Violation] = []
    info: list[Violation] = []

    # 1. degenerate gate — an empty/failed extraction must NEVER read as valid.
    if not model.rooms:
        blocking.append(Violation(
            rule_id="HAB000",
            severity=Severity.BLOCKING,
            refs=[model.building_id],
            msg="model has no rooms — empty or failed extraction; nothing was verified "
                "and the building must NOT read as valid.",
            fix_hint="ensure the SpatialModel was populated before running the checker.",
        ))
        outcomes = [RuleOutcome(rule_id=rid, status=RuleStatus.NOT_EVALUATED,
                                reason="degenerate model (no rooms)")
                    for rid in (_CONSISTENCY_IDS + [s.rule_id for s in RULE_SPECS_V2])]
        coverage = CoverageInfo(
            outcomes=outcomes, rules_evaluated=0, rules_not_evaluated=len(outcomes),
            mandatory_not_evaluated=[s.rule_id for s in RULE_SPECS_V2],
            classification_coverage=0.0, measured_room_ratio=0.0,
            notes=["degenerate model: no rooms extracted"],
            profile_name=(thr.profile.name if thr.profile is not None else ""),
        )
        return CheckReport(passed=False, verdict=Verdict.NOT_EVALUATED,
                           blocking=blocking, warnings=warnings, info=info,
                           coverage=coverage)

    # 2. geometry-first derivation — rules will read MEASUREMENTS, not claims.
    dmodel, drep = derive(model, thr)
    graph: nx.Graph = build_graph(dmodel, exclude_door_ids=drep.dropped_door_ids)
    apartments = derive_apartments(dmodel, graph)
    ctx = _V2Context(model=dmodel, drep=drep, graph=graph, apartments=apartments)

    outcomes: list[RuleOutcome] = []

    profile = thr.profile

    # 3. consistency rules (declaration vs derivation) — always engaged, unless this
    #    stage's profile says it cannot supply their inputs at all.
    for rule_id, fn in consistency.CONSISTENCY_REGISTRY:
        if profile is not None and profile.is_suspended(rule_id):
            outcomes.append(RuleOutcome(
                rule_id=rule_id, status=RuleStatus.NOT_EVALUATED,
                reason=_suspended_reason(profile, rule_id)))
            continue
        _bin(fn(model, dmodel, drep, thr), blocking, warnings, info)
        outcomes.append(RuleOutcome(rule_id=rule_id, status=RuleStatus.EVALUATED,
                                    n_subjects=len(model.rooms)))

    # 4+5. geometric ruleset on the DERIVED model, with per-rule coverage.
    mandatory_not_evaluated: list[str] = []
    for spec in RULE_SPECS_V2:
        # A SUSPENDED rule never runs: at this stage it would be judging the
        # representation, not the building, and a finding like that is worse than
        # silence because it looks exactly like a finding about the building.
        if profile is not None and profile.is_suspended(spec.rule_id):
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.NOT_EVALUATED,
                reason=_suspended_reason(profile, spec.rule_id)))
            continue
        # ПРЕДУСЛОВИЕ ПРОВЕРЯЕТСЯ ПЕРВЫМ: правило, у которого нет предмета
        # рассуждения, не должно даже увидеть модель.
        unmet = [name for name in (profile.preconditions.get(spec.rule_id, ())
                                   if profile is not None else ())
                 if not PRECONDITIONS[name][0](ctx)]
        if unmet:
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.NOT_EVALUATED,
                reason="; ".join(f"нет входа «{name}»: {PRECONDITIONS[name][1]}"
                                 for name in unmet)))
            # Missing a model-wide input is still NOT_EVALUATED: an active
            # mandatory rule must veto PASS just as it does with zero subjects.
            if _is_mandatory(profile, spec, ctx):
                mandatory_not_evaluated.append(spec.rule_id)
            continue
        target = dmodel
        withheld, missing_input = 0, ""
        required = (profile.subject_inputs.get(spec.rule_id)
                    if profile is not None else None)
        if required:
            target, withheld, missing_input = _filtered_subjects(
                dmodel, drep, spec.rule_id, required)
        _bin(spec.fn(target, graph, thr), blocking, warnings, info)
        n = spec.subjects(ctx)
        if n > 0:
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.EVALUATED, n_subjects=n,
                excluded_subjects=withheld,
                excluded_reason=(f"нет входа «{missing_input}»" if withheld else "")))
        else:
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.NOT_EVALUATED,
                reason=spec.vacuous_reason, excluded_subjects=withheld,
                excluded_reason=(f"нет входа «{missing_input}»" if withheld else "")))
            if _is_mandatory(profile, spec, ctx):
                mandatory_not_evaluated.append(spec.rule_id)

    notes: list[str] = []
    if drep.classification_coverage < thr.min_classification_coverage:
        notes.append(
            f"classification coverage {drep.classification_coverage:.0%} below floor "
            f"{thr.min_classification_coverage:.0%}: rooms "
            f"{drep.unclassified_room_ids} have unknown functions — habitability rules "
            f"were not meaningfully applied."
        )
    if drep.measured_room_ratio < thr.min_measured_room_ratio:
        notes.append(
            f"only {drep.measured_room_ratio:.0%} of rooms have measurable boundary "
            f"polygons (floor {thr.min_measured_room_ratio:.0%}): geometry-first "
            f"verification impossible for {drep.unmeasured_room_ids}."
        )

    coverage = CoverageInfo(
        outcomes=outcomes,
        rules_evaluated=sum(1 for o in outcomes if o.status is RuleStatus.EVALUATED),
        rules_not_evaluated=sum(1 for o in outcomes
                                if o.status is RuleStatus.NOT_EVALUATED),
        mandatory_not_evaluated=sorted(mandatory_not_evaluated),
        classification_coverage=round(drep.classification_coverage, 4),
        unclassified_room_ids=list(drep.unclassified_room_ids),
        measured_room_ratio=round(drep.measured_room_ratio, 4),
        unmeasured_room_ids=list(drep.unmeasured_room_ids),
        notes=notes,
        profile_name=(profile.name if profile is not None else ""),
    )

    blocking, warnings, info = _sorted_buckets(blocking, warnings, info)

    if blocking:
        verdict = Verdict.FAIL
    elif mandatory_not_evaluated or notes:
        verdict = Verdict.NOT_EVALUATED   # unknown ≠ pass
    else:
        verdict = Verdict.PASS

    return CheckReport(
        passed=(verdict is Verdict.PASS),
        verdict=verdict,
        blocking=blocking,
        warnings=warnings,
        info=info,
        coverage=coverage,
    )


def run(model: SpatialModel, thr: Thresholds = THRESHOLDS) -> CheckReport:
    """Run the full ruleset over `model` and return an aggregated CheckReport.

    Pure: builds the graph once, calls every rule with the uniform (model, graph, thr)
    signature, collects all Violations, bins them by severity, and sets
    passed = (no BLOCKING). No I/O, no mutation of `model`.

    With KUKAI_CHECKER_V2=1 the v2 pipeline runs instead (see module docstring):
    geometry-first derivation, consistency rules, three-valued verdict + coverage,
    and — when `thr.profile` is set — that stage profile's rule set.
    """
    if checker_v2_enabled():
        return _run_v2(model, thr)

    graph: nx.Graph = build_graph(model)

    blocking: list[Violation] = []
    warnings: list[Violation] = []
    info: list[Violation] = []

    # Degenerate-input guard (review fix): an empty model would otherwise "pass" vacuously —
    # a failed extraction / empty generator output must not read as a valid building.
    # (v1 semantics: INFO only — the v2 path above makes this BLOCKING + NOT_EVALUATED.)
    if not model.rooms:
        info.append(Violation(
            rule_id="HAB000",
            severity=Severity.INFO,
            refs=[model.building_id],
            msg="model has no rooms — nothing to check (likely an empty or failed extraction).",
            fix_hint="ensure the SpatialModel was populated before running the checker.",
        ))

    for rule in RULE_REGISTRY:
        _bin(rule(model, graph, thr), blocking, warnings, info)

    # Canonical, deterministic ordering of each bucket (review fix) so the report is stable
    # regardless of registry / rule internal iteration order.
    blocking, warnings, info = _sorted_buckets(blocking, warnings, info)

    return CheckReport(
        passed=(len(blocking) == 0),
        blocking=blocking,
        warnings=warnings,
        info=info,
    )
