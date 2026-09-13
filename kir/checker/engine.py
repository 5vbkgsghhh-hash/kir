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

checker v2 (flags.checker_v2_enabled, env KIR_CHECKER_V2=1; the former
KUKAI_CHECKER_V2 keeps working — see kir/env.py) replaces the verdict
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

A CENSUS OF VERDICTS ON EMPTY INPUT (17.08.2026, reference `fixtures.builders.make_good()`,
`KUKAI_CHECKER_V2=1` — the prod path; ONE subject removed at a time). Of 20 rules,
NINE spoke on emptiness, and coverage for all nine read `EVALUATED`, i.e.
indistinguishable from "looked and found something": HAB001/002/003/004/010/042 on a model with no
DOORS, HAB030/HAB060 with no WINDOWS, HAB030/041/042/060 with no WALLS, HAB003 with no LEVELS. Five
stayed honestly silent — HAB041 "no doors", HAB011/HAB012 on stairs, HAB050 on load-bearing elements,
HAB010 on levels. The remaining eight cannot be checked this way at all: their subject is
rooms, and a model with no rooms is intercepted by the degenerate gate (HAB000).

Of these nine, MOST JUDGE THE CASE CORRECTLY: a building with no doors and no walls is a defect of
the building, not a gap in reading, and `PRECONDITIONS` already close off connectivity where the
emptiness belongs to the inference. What is fixed here is exactly what turned out to be our own blind spot:

  * `n_subjects` was counted over the FULL model, not over the one the rule saw
    after the subject filter. Measurement: HAB030 on the reference with no walls printed
    `EVALUATED(n=2)`, without saying a word — "looked and it was clean" instead of "there was
    nothing to look at," precisely what the three-valued verdict was set up to catch;
  * `vacuous_reason` is a specification constant, and for subjects held back entirely it
    asserted a falsehood ("no classified habitable/kitchen rooms" while a habitable room and a kitchen were alive).
    Now the reason names the hold;
  * a stage may name SEVERAL inputs for a rule, not just one.

🔴 AND ONE HYPOTHESIS FROM THIS SAME WAVE WAS RETRACTED BY MEASUREMENT — see `SUBJECT_INPUTS
["room_window_readable"]`: "a rule declares its own input, valid at any stage"
sounded convincing and was killed by a FAIL control on the existing corpus. The meaning of one and
the same input depends on the model's PRODUCER, and `SpatialModel` does not carry it — so the
distinction belongs to the stage, and the original intent of `StageProfile` was right.

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

from dataclasses import dataclass, replace
from typing import Any, Callable

import networkx as nx

from kir.checker.derive import DerivationReport, derive
from kir.checker.flags import checker_v2_enabled
from kir.checker.function_provenance import (
    is_authored as function_is_authored,
)
from kir.checker.graph import (
    build_graph, derive_apartments, ground_level_ids, occupied_levels)
from kir.checker.spatial_model import (
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
from kir.checker.thresholds import (
    THRESHOLDS,
    StageProfile,
    Thresholds,
)
from kir.checker.rules import (
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
    #: 🔴 A STRING OR A FUNCTION, AND THE SECOND WAS BOUGHT BY MEASUREMENT
    #: 20.08.2026. A constant describes ONE emptiness, but a rule can have
    #: several, and they are OPPOSITE in meaning: "we did not ask" is our own
    #: hole, "we asked, and the building answered NO" is a fact about the
    #: building. While the reason was a constant, HAB050 printed "no
    #: structural walls flagged" in both cases, and after
    #: `WALL_STRUCTURAL_SIGNIFICANT` was added to the capture (7845 walls,
    #: zero everywhere), the same line came to mean exactly the opposite of
    #: what it meant yesterday. Collapsing them into one code would be the
    #: same as collapsing `refused` and `no_room_in_phase` for doors.
    vacuous_reason: str | Callable[[_V2Context], str]
    mandatory: Callable[[_V2Context], bool]
    #: 🔴 THE RULE'S OWN PRECONDITIONS — THOSE TRUE AT ANY STAGE (22.08.2026).
    #:
    #: WHY THIS FIELD WAS ADDED, BY MEASUREMENT. `preconditions` lived ONLY on
    #: `StageProfile`, and `_run_v2` read them via the line
    #: `profile.preconditions.get(...) if profile is not None else ()`. So at
    #: `profile=None` — i.e. on the full as-built rule set, against which every
    #: finished building is measured — NOT A SINGLE precondition was checked.
    #: The MNVNK run on 22.08 printed the cost: the production path (with a
    #: stage profile) produced BLOCKING 0, while as-built on the same model
    #: produced 24, of which 23 were HAB010 "level hangs with no connection to
    #: the ground" with ZERO stairs read. The very accusations fixed that same
    #: day for the stage path stood untouched in the second.
    #:
    #: THE BOUNDARY, AND IT IS NOT COSMETIC. Not everything moves here, only
    #: what speaks to the INFERENCE'S BLINDNESS and does not depend on the
    #: stage: "ground not found," "stairs not read," "street entrance not
    #: confirmed." `apartments_derived` stays with the profile, because it is
    #: already covered by the subject counter (`len(c.apartments)`), and
    #: `apartments_are_dwellings` stays too — because it is a judgment about
    #: the ORACLE'S ACCURACY, measured on a specific input, not a fact about
    #: the inference; promoting it to the engine's default would silently mute
    #: HAB002 across every corpus at once.
    #:
    #: A stage still may ADD its own: sets are unioned, not substituted for
    #: one another (`_run_v2`).
    preconditions: tuple[str, ...] = ()
    #: 🔴 SUBJECTS THE RULE CAN JUDGE ONLY BY GUESSWORK (07.09.2026).
    #: `-> (how many, why)`. Before this field, unverifiedness for connectivity
    #: rules lived ONLY in the finding's text, while the coverage line stayed
    #: byte-for-byte the same as for a building with a function that was read:
    #: `EVALUATED(n), excluded=0`. That is, the rule kept ASSERTING that it
    #: judged the subject, and "connected to the ground" read as yes with a
    #: footnote.
    #:
    #: THIS IS NOT A SECOND MECHANISM, BUT A SECOND SOURCE FOR ONE. The hold
    #: already exists — `excluded_subjects`/`excluded_reason` — and exactly one
    #: side was filling it: the stage's filter by inputs (`SUBJECT_INPUTS`).
    #: Connectivity rules are DELIBERATELY excluded from `_ROOM_FILTERABLE`
    #: (they reason about paths, and a trimmed model would answer a different
    #: question), so they had nothing with which to name their own hold. Here
    #: the RULE ITSELF names it, and everything is folded into the same field:
    #: two sources, one carrier.
    unverifiable: Callable[[_V2Context], tuple[int, str]] | None = None

    def reason_for(self, ctx: _V2Context) -> str:
        """The reason for THAT emptiness which occurred on THIS building."""
        if callable(self.vacuous_reason):
            return self.vacuous_reason(ctx)
        return self.vacuous_reason


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


def _n_width_rule_subjects(ctx: _V2Context) -> int:
    """HAB021's subjects — THE SAME ONES its body considers.

    🔴 BOUGHT BY A REAL BUILDING (22.08.2026, MNVNK). Coverage printed
    `HAB021 EVALUATED(n=473), 0 нарушений`, while the rule's body considered
    ZERO rooms: `rules/dimensions.check_hab021` only takes functions that have
    a width threshold (habitable, corridor, + kitchen and bathroom under v2),
    and all 1102 rooms of this building carry the function OTHER. The counter
    was `_n_measured_rooms` — "how many rooms had their outline measured," a
    quantity unrelated to the rule's subject.

    "Checked 473, no violations" and "there was nothing to check" are
    different facts, and here the first one was a lie. The neighbor in the
    same file is done correctly: HAB020's `_n_area_rule_subjects` knows the
    functions, so HAB020 honestly went to NOT_EVALUATED on the same building.
    Two carriers of the same knowledge had drifted apart — now each rule has a
    counter keyed to ITS OWN filter.

    Width thresholds are held by `Thresholds`, and the filter by the rule's
    body; here the SET OF FUNCTIONS is duplicated, and that is the only thing
    that is. They are held together by
    `test_vacuity_names_which_emptiness.ПустотаКупленнаяНастоящимЗданием
    ::test_счётчик_HAB021_не_расходится_с_фильтром_своего_тела` — it reads the
    SOURCE of both and requires that each of the four function names be
    mentioned in them IDENTICALLY.
    """
    checked = {RoomFunction.ЖИЛАЯ, RoomFunction.КОРИДОР}
    if checker_v2_enabled():
        checked |= {RoomFunction.КУХНЯ, RoomFunction.САНУЗЕЛ}
    return sum(1 for r in ctx.model.rooms if r.function in checked)


def _n_daylit_subjects(ctx: _V2Context) -> int:
    return sum(1 for r in ctx.model.rooms
               if r.function in (RoomFunction.ЖИЛАЯ, RoomFunction.КУХНЯ))


def _n_daylight_ratio_subjects(ctx: _V2Context) -> int:
    """HAB031's subjects — THE SAME ONES its body considers.

    🔴 THE COUNTER WAS SHARED WITH HAB030, BUT THEIR BODIES DIFFER
    (07.09.2026). HAB030 judges "is there a window at all," HAB031 — "is there
    enough glazing," and therefore it skips a room with no window (that is the
    neighbor's subject), one with zero glazing, and one with zero floor area
    (division). Measurement on the fixture corpus: the counter says 80
    subjects, the body considered 76, a discrepancy on 3 of 25 buildings.
    `bad_open_envelope` printed `HAB031 EVALUATED(n=2), 0 нарушений` with ZERO
    rooms considered — "looked and it was clean" about what it never looked
    at.

    The same defect and the same fix as HAB021 (`_n_width_rule_subjects`),
    HAB012 (pairs instead of stairs), and HAB061 (doors instead of rooms):
    each rule now has a counter keyed to ITS OWN filter.
    """
    return sum(1 for r in ctx.model.rooms
               if r.function in (RoomFunction.ЖИЛАЯ, RoomFunction.КУХНЯ)
               and r.has_window and r.window_area_m2 > 0.0 and r.area_m2 > 0.0)


def _n_nonground_levels(ctx: _V2Context) -> int:
    """HAB010's subjects — OCCUPIED NON-GROUND levels, exactly the ones the
    body judges.

    🔴 ALL OCCUPIED LEVELS WERE COUNTED, BUT THE BODY `continue`s past the
    ground level on its FIRST LINE (07.09.2026). Measurement on the fixture
    corpus: 17 of 25 buildings are single-level, and all 17 printed
    `HAB010 EVALUATED(n=1), 0 нарушений` — a claim that the rule judged a
    level it never touched. On multi-story buildings, n was inflated by
    exactly 1.
    """
    ground = ground_level_ids(ctx.model)
    return sum(1 for lvl in occupied_levels(ctx.model) if lvl.id not in ground)


def _hab010_vacuity(ctx: _V2Context) -> str:
    """HAB010's EMPTINESS COMES IN TWO KINDS, AND THEY ARE OPPOSITES.

    "There are no occupied levels at all" is our own hole: the model said
    nothing. "All occupied levels are at grade" is a FACT ABOUT THE BUILDING:
    there is nothing to hang, and this is a known clean result, not a reading
    gap. The same kind as HAB062 with zero unidentified, and the same reason
    to keep them apart as `_structural_vacuity`.
    """
    if not occupied_levels(ctx.model):
        return "no occupied levels"
    return ("здание одноуровневое: занятые уровни есть, но ВСЕ они наземные — "
            "висячего этажа быть не может, и это факт о здании, а не пробел "
            "чтения")


def _n_measured_stairs(ctx: _V2Context) -> int:
    return sum(1 for s in ctx.model.stairs
               if s.kind == "element" and s.run_width_mm is not None
               and s.riser_count is not None and s.tread_depth_mm is not None)


#: A stair quantity -> what reads it. `None` in the third field means the
#: quantity is not where we look for it, and this is a NAMED ABSENCE, not debt.
_STAIR_VALUES = (
    # 🔴 "AND `OST_StairsRuns` IS OUTSIDE THE EXTRACTION TABLE" WAS WIDER THAN
    # THE TRUTH AND WAS RETRACTED BY MEASUREMENT 22.08.2026. The category is
    # indeed not in the table, but the flight IS READ by a side stage, and the
    # path is covered in 48 of 48. "There is no stage" and "there is a stage,
    # but no field" are fixed by DIFFERENT means, and the first would have
    # sent us to rewrite the capture on top of something already working. The
    # formula had FOUR carriers; this is the third.
    ("run width", "run_width_mm",
     "у `Stairs` свойства ширины НЕТ ни в одной версии 2021–2026: она живёт на `StairsRun.ActualRunWidth`. МАРШ ПРИ ЭТОМ ЧИТАЕТСЯ — боковой стадией `sketch_extract` через `Stairs.GetStairsRuns()`, путь снят у 48 маршей из 48 на MNVNK; не снимается именно ШИРИНА"),
    ("riser count", "riser_count", None),
    ("tread depth", "tread_depth_mm", None),
)


def _hab012_vacuity(ctx: "_V2Context") -> str:
    """Why comparing pairs was not needed. TWO DIFFERENT TROUBLES, not one.

    🔴 THE FIRST EDIT OF THE FIX GAVE ONE LINE FOR BOTH (29.08.2026), and this
    was caught by `test_gold_path_axes`, whose law is recorded verbatim: "one
    word for different troubles stops being a measurement." With no stairs
    and with ONE stair, the text came out byte-for-byte identical, even though
    the reader's next move differs:

        no stairs with a tread AT ALL   -> lay out flights, measure treads
        a tread exists, the pair failed -> the stair serves one level, a
                                            second one is needed on the adjacent level

    That the reason can be a FUNCTION, not a constant, was set up on 20.08
    precisely against this (see the caveat at `RuleSpec.vacuous_reason`) — the
    mechanism existed, I simply did not use it.
    """
    со_следом = sum(1 for s in ctx.model.stairs if s.footprint)
    if not со_следом:
        return ("ни одного марша со следом в плане: сравнивать нечего и не с "
                "чем — ни одной пары смежных обслуженных уровней не бывает")
    return (f"следы в плане есть ({со_следом} марш(ей)), но ни одной пары "
            f"смежных обслуженных уровней не образовалось: марши базируются "
            f"на одном уровне либо уровни не смежны")


def _stair_vacuity(ctx: _V2Context) -> str:
    """🔴 "NO STAIR HAS MEASURED GEOMETRY" STOPPED BEING TRUE (20.08.2026).

    Live measurement: `STAIRS_ACTUAL_NUM_RISERS`, `STAIRS_ACTUAL_RISER_HEIGHT`
    and `STAIRS_ACTUAL_TREAD_DEPTH` arrive for 24 of 24 stairs. One quantity
    does not arrive — flight width, and not because it was not asked for, but
    because `Stairs` simply has NO such property.

    `_n_measured_stairs` requires ALL THREE, so the coverage line is still
    NOT_EVALUATED — and the former constant "none has measured geometry" now
    UNDERSTATES: two of three quantities are measured, and violations on them
    fire. Here it is written what was judged by and what was missing.
    """
    stairs = [s for s in ctx.model.stairs if s.kind == "element"]
    if not stairs:
        inferred = len(ctx.model.stairs)
        if inferred:
            return (f"лестниц-ЭЛЕМЕНТОВ нет: все {inferred} — выведенные связи "
                    f"(kind='inferred'), их геометрию проверять нечем")
        return "лестниц нет вовсе"
    have, missing = [], []
    for label, field_name, absence in _STAIR_VALUES:
        n = sum(1 for s in stairs if getattr(s, field_name) is not None)
        if n:
            have.append(f"{label} у {n} из {len(stairs)}")
        else:
            missing.append(label if absence is None else f"{label} ({absence})")
    if not have:
        return (f"лестниц-элементов {len(stairs)}, но НИ ОДНА величина не "
                f"прочитана: {'; '.join(missing)}")
    return (f"судили по: {', '.join(have)}; НЕ ХВАТИЛО: {'; '.join(missing)}. "
            f"Строка покрытия требует все три величины сразу, поэтому она пуста "
            f"— но это НЕ «геометрия не измерена»")


def _structural_vacuity(ctx: _V2Context) -> str:
    """🔴 THREE DIFFERENT EMPTINESSES UNDER ONE FORMER TEXT.

    Before 20.08.2026, `is_structural` never arrived AT ALL and was
    substituted as `False`, so "no structural walls flagged" meant "we did
    not ask." After `WALL_STRUCTURAL_SIGNIFICANT` was added to the capture,
    the same line means "we asked, and the building answered NO" — the
    opposite statement. Live measurement: the parameter arrives for 7845 of
    10,646 walls and is ZERO EVERYWHERE.

    They can be told apart precisely because the field became
    THREE-VALUED: `None` — not captured, `False` — captured and negative.
    """
    walls = ctx.model.walls
    if not walls:
        return "стен нет вовсе — несущую непрерывность проверять не на чем"
    unknown = sum(1 for w in walls if w.is_structural is None)
    negative = sum(1 for w in walls if w.is_structural is False)
    if unknown and not negative:
        return (f"НЕ ЗАХВАЧЕНО: признак несущности не пришёл ни у одной из "
                f"{unknown} стен. Это наша дыра чтения, а не факт о здании")
    if negative and not unknown:
        return (f"ЗАХВАЧЕНО, И ЗДАНИЕ ОТВЕТИЛО НЕТ: признак прочитан у "
                f"{negative} стен, несущей нет ни одной. Это факт о здании, "
                f"а не пробел чтения")
    return (f"смешанный вход: признак прочитан у {negative} стен (все "
            f"отрицательны) и НЕ ПРИШЁЛ у {unknown}. Пока вторая половина "
            f"молчит, «несущих нет» есть утверждение о прочитанной части")


RULE_SPECS_V2: list[RuleSpec] = [
    # 🔴 WHAT DID NOT MAKE IT IN HERE, AND THIS IS A DECISION, NOT AN OVERSIGHT.
    # `building_entrance_known` and `ground_level_known` stay WITH THE
    # PROFILE: on as-built, "there is not a single exterior door" and "no
    # ground level was found" are statements ABOUT THE BUILDING, and
    # `test_grade_egress` holds them by name ("a building with no exterior
    # door at all is still sealed"). The design stage judges differently, and
    # this is a legitimate divergence between stages, not a hole. The rules'
    # OWN preconditions become only what is true under any answer the
    # building gives — marking landings with rooms.
    RuleSpec(connectivity.check_hab001, "HAB001",
             lambda c: len(c.model.rooms), "no rooms",
             lambda c: True,
             ("stair_landings_marked",)),
    # 🔴 RULES ABOUT AN APARTMENT'S COMPOSITION STAND ON THE ORACLE, AND THE
    # ORACLE MUST PROVE THAT ITS COMPONENTS ARE DWELLINGS. `apartments_are_dwellings`
    # is a definition, not a threshold (see its comment in `PRECONDITIONS`),
    # and is therefore true at any stage. MNVNK measurement 22.08.2026: as
    # soon as room function became derivable from furnishing, `derive_apartments`
    # produced 23 components, and HAB002/HAB004 each issued 23 BLOCKING —
    # "apartment with no entry to the common zone" and "apartment with no
    # entryway." Both accusations are VACUOUS BY CONSTRUCTION: only the room's
    # NAME names an entryway, and this building has no names at all, so no
    # derived apartment can have an entryway under any layout.
    RuleSpec(connectivity.check_hab002, "HAB002",
             lambda c: len(c.apartments), "no derived apartments",
             lambda c: False,
             ("apartments_from_authored_functions",)),
    RuleSpec(connectivity.check_hab003, "HAB003",
             lambda c: len(c.apartments), "no derived apartments — egress unverifiable",
             lambda c: True,
             ("stair_landings_marked",),
             lambda c: connectivity.unverifiable_apartments(c.model, c.graph,
                                                           c.apartments)),
    RuleSpec(connectivity.check_hab004, "HAB004",
             lambda c: len(c.apartments), "no derived apartments",
             lambda c: False,
             ("apartments_from_authored_functions",)),
    # 🔴 MANDATORINESS IS LIFTED TOGETHER WITH THE COUNTER, AND THIS IS ONE
    # FIX, NOT TWO (07.09.2026). Fixing the counter alone would have sent 9 of
    # 25 verdicts into NOT_EVALUATED: a single-story building has nothing to
    # judge, HAB010 is mandatory, and a veto lands on a building about which
    # everything is known. The engine's carrier for the distinction "empty,
    # and this is a fact about the building" is `mandatory`, not `status`; the
    # precedent is HAB011 (`len(stairs) > 0`), and the cost of the opposite is
    # named in the file's header: "with HAB011 mandatory-on-any-stair, every
    # design-stage building read NOT_EVALUATED forever." Measuring both fixes
    # together: verdicts shifted by 0, coverage lines by 25 of 25.
    RuleSpec(connectivity.check_hab010, "HAB010",
             _n_nonground_levels, _hab010_vacuity,
             lambda c: _n_nonground_levels(c) > 0,
             ("stair_landings_marked",),
             lambda c: connectivity.unverifiable_levels(c.model, c.graph)),
    RuleSpec(vertical.check_hab011, "HAB011",
             _n_measured_stairs, _stair_vacuity,
             lambda c: len(c.model.stairs) > 0),
    # 🔴 THE COUNT WAS BY STAIRS, BUT THE RULE LOOKS AT PAIRS (29.08.2026,
    # F-362). `sum(1 for s in c.model.stairs if s.footprint)` gives 1 for a
    # building with ONE stair, whereas `zip(served, served[1:])` inside the
    # rule is empty: not a single pair was compared. Coverage printed
    # `HAB012 EVALUATED(n=1), 0 нарушений` — "looked and it was clean" instead
    # of "there was nothing to compare." Now the counter and the rule read
    # the SAME iteration.
    RuleSpec(vertical.check_hab012, "HAB012",
             lambda c: sum(1 for _ in vertical.hab012_comparable_pairs(c.model)),
             _hab012_vacuity,
             lambda c: False),
    RuleSpec(dimensions.check_hab020, "HAB020",
             _n_area_rule_subjects,
             "no classified habitable/kitchen/bathroom room with measurable geometry",
             lambda c: True),
    RuleSpec(dimensions.check_hab021, "HAB021",
             _n_width_rule_subjects,
             "ни одного помещения с функцией, у которой есть порог ширины "
             "(жилая/коридор, под v2 ещё кухня/санузел) — ширину сравнивать "
             "не с чем",
             lambda c: False),
    RuleSpec(dimensions.check_hab022, "HAB022",
             lambda c: sum(1 for r in c.model.rooms if r.height_mm is not None),
             "no room has a known ceiling height",
             lambda c: False),
    RuleSpec(light.check_hab030, "HAB030",
             _n_daylit_subjects, "no classified жилая/кухня rooms — daylight unverifiable",
             lambda c: True),
    RuleSpec(light.check_hab031, "HAB031",
             _n_daylight_ratio_subjects,
             "ни одной жилой/кухни с ИЗМЕРЕННЫМ остеклением и ненулевым полом — "
             "отношение считать не из чего (комната без окна — предмет HAB030)",
             lambda c: False),
    RuleSpec(clash.check_hab040, "HAB040",
             _n_measured_rooms, "no measurable room boundaries",
             lambda c: False),
    RuleSpec(clash.check_hab041, "HAB041",
             lambda c: len(c.model.doors), "no doors",
             lambda c: False),
    RuleSpec(clash.check_hab042, "HAB042",
             lambda c: len(c.apartments), "no derived apartments",
             lambda c: False,
             ("apartments_from_authored_functions",)),
    RuleSpec(structure.check_hab050, "HAB050",
             lambda c: sum(1 for w in c.model.walls if w.is_structural),
             _structural_vacuity,
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
    # THE FACT ABOUT THIS ROOM'S WINDOW WAS READ IN SOME WAY AT ALL
    # (`derive.WindowStatus`). Absent EXACTLY for a room that a window names,
    # where none of its windows could be either confirmed or refuted: neither
    # a point nor a resolvable host wall.
    #
    # 🔴🔴 THIS INPUT MUST NOT BE ENABLED BY DEFAULT, AND THIS IS A
    # MEASUREMENT, NOT CAUTION. The first edit on 17.08.2026 declared it an
    # input of HAB030 ITSELF — "with no window placed, I judge my own
    # blindness." The premise sounded right and was KILLED by a FAIL control
    # on the existing corpus: two probes turned red, and both rightly so.
    #
    #   `v2_probes.probe_fabricated_window` — a window with `host_wall_id=None`,
    #     and this is NOT a reading gap: it is written this way by OUR OWN
    #     auto-repair (`generator/fix_loop._fix_hab030:55` — verified against
    #     the code, not the docstring). Under the filter, HAB030 would go into
    #     `vacuous` precisely when the loop fabricates a window — that is,
    #     probe C, the very one v2 was built to kill, would come back to life;
    #   `v2_probes.probe_walls_deleted_live_shape` — the walls were DEMOLISHED
    #     ON THE BUILDING, not in the reading; the emptiness there is a real
    #     finding.
    #
    # The reason is common: ONE AND THE SAME input has two opposite meanings
    # depending on the model's PRODUCER (live reading versus authoring), and
    # `SpatialModel` does not carry the producer. So the distinction belongs
    # to the STAGE, and only the profile has the right to name it — which is
    # exactly the original intent of `StageProfile.subject_inputs`. The live-
    # reading stage MAY name this input; the authoring stage MAY NOT.
    #
    # And what it fails to distinguish even there: it counts a room with NO
    # windows AT ALL as read, and HAB030 still accuses it just the same.
    # Nobody has a discriminator for this — `extractor.normalize:124` merges a
    # missing key with an empty list (`raw.get("windows", []) or []`), and
    # `extractor.cs:137` only collects `OST_Windows`, so a curtain-wall
    # building is indistinguishable from a building with no windows.
    "room_window_readable": ("rooms", lambda subject, drep: (
        drep.rooms[subject.id].window_fact_readable
        if subject.id in drep.rooms else True)),
}

def _landings_marked(ctx: "_V2Context") -> bool:
    """Whether all levels served by stairs are marked with ROOMS.

    The single carrier of this rule: it is read by TWO preconditions —
    `stair_landings_marked` (the rules' default, always active) and the
    composite `stair_landings_complete` (named by the stage). They must not
    drift apart, so there is one predicate.

    EMPTY WHEN THERE ARE ZERO STAIRS, AND THIS IS DELIBERATE: the set
    difference is empty when there is nothing to subtract from, so the
    statement "marking is complete" is VACUOUSLY true. Precisely for this
    reason it must not be left as the sole guard — the second clause
    (`bool(model.stairs)`) lives in the composite precondition, which has its
    own stage.

    🔴 ONLY OCCUPIED LEVELS ARE ASKED ABOUT (22.08.2026). The previous edit
    required a landing on EVERY level a stair touches, including levels
    WITHOUT A SINGLE ROOM. Measurement on the `bad_floating_column` and
    `bad_discontinuous_core` references: a flight runs from L0 to L1, there
    are no rooms at all on L1 — and the precondition muted HAB001/HAB003/HAB010
    on a building where there was something to judge and where they honestly
    passed. A level with no rooms takes part neither in connectivity
    (`occupied_levels`) nor in the verdict; requiring a landing on it means
    requiring markup for something the rule does not look at anyway.
    """
    occupied = {room.level_id for room in ctx.model.rooms}
    served = {lvl for stair in ctx.model.stairs
              for lvl in (stair.base_level_id, stair.top_level_id)} & occupied
    return not (served - {room.level_id for room in ctx.model.rooms
                          if room.function is RoomFunction.ЛЕСТНИЦА})


#: Closed vocabulary of MODEL-WIDE preconditions. Each answers "does the derivation
#: actually hold the thing this rule reasons about", and each carries the sentence a
#: reader needs when it does not.
#:
#: The reason is a string OR a function of context, exactly like
#: `RuleSpec.vacuous_reason`. The second form is needed where a precondition
#: covers SEVERAL DIFFERENT emptinesses: naming them with one phrase would
#: send the reader to fix the wrong thing. Printed by `_precondition_reason`.
PRECONDITIONS: dict[str, tuple[Callable, str | Callable[[Any], str]]] = {
    "ground_level_known": (
        lambda ctx: bool(ctx.drep.ground_level_ids),
        "ни один уровень не признан уровнем земли: наружной двери НА КОЛЬЦЕ ОБОЛОЧКИ "
        "в полосе над низшим занятым уровнем не нашлось. «Не спускается к земле» "
        "сравнивало бы этаж с землёй, которой у проверки нет"),
    # NOT "there is at least one landing," but "there is a landing on EVERY
    # level that a stair serves." The weak form misses exactly the case the
    # precondition was set up for: measurement 03.08 (snowdon) — 26 stairs,
    # landings marked on 3 of 9 levels, and HAB010 accused 8 levels of having
    # no connection to the ground, even though stairs were present there and
    # only their ROOM MARKUP was missing.
    # 🔴 TWO EMPTINESSES, NOT ONE, AND THE SECOND WAS BOUGHT BY A REAL BUILDING.
    #
    # Measurement 22.08.2026, MNVNK (first run of 20 rules against the
    # production model): BLOCKING 24, of which 23 were "level hangs with no
    # connection to the ground." Not one was a fact about the building.
    #
    # The set difference above is EMPTY when stairs are ZERO: the left-hand
    # set is empty, there is nothing to subtract, the precondition is
    # VACUOUSLY true, and the rule runs and accuses nearly every level. The
    # guard set up precisely against this (measurement 03.08 on snowdon — 26
    # stairs, markup on 3 of 9 levels) is defeated by the very emptiness it
    # guards against.
    #
    # And MNVNK has 24 stairs, and they are read: `STAIRS_BASE_LEVEL_PARAM`,
    # `ACTUAL_NUM_RISERS`, `ACTUAL_RISER_HEIGHT` arrived for 24 of 24. They
    # were discarded BY US — `_stairs_from_l0` (design_check.py:1073) requires
    # `STAIRS_TOP_LEVEL_PARAM`, and the building returned empty for it. That
    # is, "floors are hanging" was a statement about our own reading, printed
    # as a statement about the building — and this is the worst kind of error
    # a judge can make.
    #
    # Vertical edges are built ONLY through stair rooms; with not a single
    # stair, the vertical graph is empty BY CONSTRUCTION, and "the level does
    # not descend to the ground" is indistinguishable from "there is nothing
    # to descend by." This is precisely the definition of emptiness.
    #
    # 🔴 TWO EMPTINESSES LIVE IN ONE PRECONDITION, AND THEIR STAGE-DEPENDENCE
    # DIFFERS (22.08.2026). The predicate below is a conjunction of two
    # DIFFERENT statements:
    #
    #   (1) "not a single stair was read" — stage-dependent. At the design
    #       stage this is a representation gap; on as-built, a three-story
    #       house with not a single stair is a defect of the BUILDING, and
    #       `test_grade_egress` holds exactly this ("floors with no stair fail
    #       even when every floor has a street door");
    #   (2) "stairs exist, but there are no rooms with the STAIR function on
    #       the levels they serve" — NEVER stage-dependent. This is a property
    #       of our own graph: vertical edges are built only through such rooms
    #       (`graph._landing_room_on_level`), and a house is entitled to have
    #       no room named "stair." The accusation here is always about us.
    #
    # So (2) is broken out into a SEPARATE name, `stair_landings_marked`, and
    # declared a precondition of the RULES THEMSELVES (`RuleSpec.preconditions`)
    # — active even at `profile=None`; while the composite
    # `stair_landings_complete` remains what the stage names, and holds both.
    # The rule about markup has ONE carrier — `_landings_marked` below — so
    # they cannot drift apart.
    "stair_landings_marked": (
        lambda ctx: _landings_marked(ctx),
        "лестницы обслуживают уровни, на которых НЕТ помещения с функцией "
        "«лестница»: вертикальные рёбра графа строятся только через такие "
        "помещения (`graph._landing_room_on_level`), поэтому «этаж висит» "
        "здесь — свойство разметки помещений, а не здания"),
    "stair_landings_complete": (
        lambda ctx: bool(ctx.model.stairs) and _landings_marked(ctx),
        lambda ctx: (
            "лестниц в представлении НЕТ НИ ОДНОЙ: вертикальные рёбра графа "
            "строятся только через помещения-лестницы "
            "(`graph._landing_room_on_level`), поэтому без лестницы «этаж "
            "висит» неотличимо от «спускаться нечему». Проверь ПЕРВЫМ ДЕЛОМ "
            "отказы съёма лестниц (`witness.drop(\"stairs\", ...)`) — "
            "22.08.2026 на MNVNK ровно так и было: лестниц 24, отброшены все "
            "24 из-за пустого STAIRS_TOP_LEVEL_PARAM"
            if not ctx.model.stairs else
            "лестницы обслуживают уровни, на которых НЕТ помещения с функцией "
            "«лестница»: вертикальные рёбра графа строятся только через такие "
            "помещения (`graph._landing_room_on_level`), поэтому «этаж висит» "
            "здесь — свойство разметки помещений, а не здания")),
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
    # A DWELLING IS RECOGNIZED BY ITS COMPOSITION, NOT BY THE COMPONENT BEING CONNECTED.
    #
    # Measurement 15.08.2026, three inputs, `derive_apartments` without a
    # single fix:
    #
    #   generator reference (ground truth known)   non-dwellings   0 of 20   → precondition HOLDS
    #   sob62_r23_v5                                non-dwellings  11 of 12  → does NOT hold
    #   k2_ar_rd_v15                                non-dwellings 621 of 995 → does NOT hold
    #
    # The oracle gives 100% by composition on a healthy input (20 of 20 exactly
    # right), meaning the recorded "0%" is a property of the INPUT, not of the
    # algorithm, and these inputs are of two DIFFERENT kinds:
    #
    #   * `sob62_r23_v5` — a KINDERGARTEN ("Групповая ячейка", "Буфетная",
    #     "ПУИ", "ВРУ ДОО"). Nine "apartments" are OFFICES: the lexicon sends
    #     "кабинет" to HABITABLE, and the doctor's office gets counted as a
    #     dwelling. There are no apartments here at all, and the correct
    #     answer is not "12 apartments" but "this is not housing";
    #   * `k2_ar_rd_v15` — an actual residential building, but 614 singles are
    #     "Жилая комната N" and 259 are "Кухня-ниша N" SEPARATELY: the niche
    #     has no DOOR into the room, and the inference stands on doors. An
    #     open floor plan cuts the apartment into pieces.
    #
    # The predicate is neither a threshold nor a calibration: "a dwelling has
    # a kitchen or a bathroom" is the definition of a dwelling, not a fitted
    # number. A component with neither is an artifact of the inference, not
    # an apartment.
    # 🔴 THE APARTMENT ORACLE HAS NO RIGHT TO STAND ON A CLASSIFICATION THAT
    # WE OURSELVES DERIVED (22.08.2026). This is NOT a judgment about the
    # oracle's accuracy (that has `apartments_are_dwellings`) and NOT a
    # property of the stage: there is exactly one question — did we read the
    # function from the author, or did we make it up ourselves.
    #
    # The measurement that led to this precondition: as soon as room function
    # became derivable from furnishing (`function_provenance`, MNVNK —
    # `ROOM_NAME` = "Помещение" for 1102 of 1102), `derive_apartments`
    # produced 23 components, and HAB002/HAB004 each issued 23 BLOCKING. The
    # second of these is VACUOUS BY CONSTRUCTION: "apartment with no
    # entryway" — only the room's NAME names an entryway, there is no such key
    # in the furnishing lexicon and there cannot be, so no derived apartment
    # can have an entryway under any layout. The rule would be accusing the
    # building of a property of our own dictionary.
    #
    # For every input where functions are declared (and `Room.function_source`
    # defaults to `declared`), the predicate is TRUE and changes nothing.
    "apartments_from_authored_functions": (
        lambda ctx: all(
            function_is_authored(room.function_source)
            for apt in ctx.apartments
            for room in ctx.model.rooms if room.id in apt.room_ids),
        "квартира собрана из помещений, чью функцию ВЫВЕЛИ МЫ, а не назвал автор "
        "(`Room.function_source` вне `function_provenance.AUTHORED`): состав такой "
        "компоненты есть следствие нашего словаря, а не планировки. «Квартира без "
        "прихожей» здесь неизбежна по построению — прихожую называет только ИМЯ "
        "помещения. Назовите помещения в модели, и правило заговорит"),
    "apartments_are_dwellings": (
        lambda ctx: not [
            apt for apt in ctx.apartments
            if not ({RoomFunction.КУХНЯ, RoomFunction.САНУЗЕЛ}
                    & {room.function for room in ctx.model.rooms
                       if room.id in apt.room_ids})],
        "вывод дал компоненты, в которых нет НИ кухни, НИ санузла — это не жилища, "
        "а артефакт вывода: либо здание нежилое (кабинеты и группы читаются как "
        "«жилая комната»), либо квартира разрезана открытой планировкой, где комнаты "
        "связаны проёмом, а рёбра графа строятся по ДВЕРЯМ. Судить о квартирах по "
        "таким компонентам значит судить не о том"),
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


def _filtered_subjects(model: SpatialModel, drep: DerivationReport, rule_id: str,
                       input_names: tuple[str, ...]) -> tuple[SpatialModel, int, str]:
    """Return (model the rule may speak about, how many subjects were withheld, why).

    A stage may name SEVERAL inputs for one rule, and then a subject is
    withheld if it lacks AT LEAST ONE of them: "the rule has nothing to say"
    is a disjunction of reasons, not a conjunction. The returned reason names
    ALL the inputs that applied, so that a reader of coverage does not have to
    guess which one fired.
    """
    unknown = [name for name in input_names if name not in SUBJECT_INPUTS]
    if unknown:
        raise ValueError(f"unknown subject input {unknown[0]!r} for {rule_id}")
    collections = {SUBJECT_INPUTS[name][0] for name in input_names}
    if len(collections) > 1:
        raise ValueError(
            f"{rule_id} is filtered by inputs over different collections "
            f"{sorted(collections)} — one rule prunes one subject list")
    collection = collections.pop()
    why = "/".join(f"«{name}»" for name in input_names)
    predicates = [SUBJECT_INPUTS[name][1] for name in input_names]

    def _keeps(subject) -> bool:
        return all(has_input(subject, drep) for has_input in predicates)

    if collection == "rooms":
        if rule_id not in _ROOM_FILTERABLE:
            raise ValueError(
                f"{rule_id} does not examine rooms independently — pruning its model "
                "would change what it asks, not only what it asks about")
        kept = [room for room in model.rooms if _keeps(room)]
        withheld = len(model.rooms) - len(kept)
        return model.model_copy(update={"rooms": kept}), withheld, why
    if rule_id not in _DOOR_FILTERABLE:
        raise ValueError(
            f"{rule_id} does not examine doors independently — pruning its model "
            "would change what it asks, not only what it asks about")
    kept_doors = [door for door in model.doors if _keeps(door)]
    withheld = len(model.doors) - len(kept_doors)
    return model.model_copy(update={"doors": kept_doors}), withheld, why


def _required_inputs(profile: "StageProfile | None", rule_id: str) -> tuple[str, ...]:
    """The inputs a stage restricted this rule to — always a tuple.

    `StageProfile.subject_inputs` accepts both a single name and a list: a
    single name was enough while a rule had one input, and HAB030 now has two.
    A string remains a legal form so that no existing profile needs rewriting.
    """
    if profile is None or rule_id not in profile.subject_inputs:
        return ()
    declared = profile.subject_inputs[rule_id]
    names = (declared,) if isinstance(declared, str) else tuple(declared)
    return tuple(dict.fromkeys(names))


def _precondition_reason(name: str, ctx: "_V2Context") -> str:
    """The reason for THAT emptiness which occurred on THIS building.

    The same technique as `RuleSpec.reason_for`, set up here for the same
    reason: one precondition can cover several different emptinesses, and a
    generic phrase would send the reader to fix the wrong thing. Measurement
    22.08.2026 on MNVNK: `stair_landings_complete` would have stayed silent
    about "room markup" when in fact there were NO stairs at all, because the
    capture had discarded them.
    """
    reason = PRECONDITIONS[name][1]
    return reason(ctx) if callable(reason) else reason


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
    for rule in consistency.CONSISTENCY_REGISTRY:
        if profile is not None and profile.is_suspended(rule.rule_id):
            outcomes.append(RuleOutcome(
                rule_id=rule.rule_id, status=RuleStatus.NOT_EVALUATED,
                reason=_suspended_reason(profile, rule.rule_id)))
            continue
        _bin(rule.fn(model, dmodel, drep, thr), blocking, warnings, info)
        # 🔴 THE COUNT WAS `len(model.rooms)` FOR ALL FOUR (29.08.2026, F-134).
        # They iterate over different things — rooms, doors, unidentified
        # items, levels — and a model of seven rooms with not a single door
        # printed `HAB061 EVALUATED(n=7), 0 нарушений`. The population is now
        # named by the rule itself, and emptiness reads as emptiness: a
        # consistency rule obeys the same law "subjects==0 -> NOT_EVALUATED"
        # as the geometric set, otherwise the same vacuum prints differently
        # in the two halves of one report.
        n = rule.subjects(drep)
        outcomes.append(RuleOutcome(
            rule_id=rule.rule_id,
            status=RuleStatus.EVALUATED if n > 0 else RuleStatus.NOT_EVALUATED,
            n_subjects=n,
            reason="" if n > 0 else rule.vacuous_reason))

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
        # THE PRECONDITION IS CHECKED FIRST: a rule with no subject to reason
        # about must not even see the model.
        #
        # 🔴 TWO SOURCES, AND THEY ARE UNIONED, NOT SUBSTITUTED FOR ONE
        # ANOTHER (22.08.2026). The rule's own preconditions
        # (`RuleSpec.preconditions`) are true at any stage and are ALWAYS
        # active, including at `profile=None`; before this fix, at
        # `profile=None` not a single one was checked, and the as-built MNVNK
        # run printed 23 accusations of "level hangs with no connection to
        # the ground" with zero stairs read — the very ones the stage path had
        # already stopped printing. A stage may still add its own on top; the
        # order is kept as written, so the reason reads the same run to run.
        declared = tuple(spec.preconditions) + tuple(
            profile.preconditions.get(spec.rule_id, ()) if profile is not None else ())
        unmet = [name for name in dict.fromkeys(declared)
                 if not PRECONDITIONS[name][0](ctx)]
        if unmet:
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.NOT_EVALUATED,
                reason="; ".join(
                    f"нет входа «{name}»: {_precondition_reason(name, ctx)}"
                    for name in unmet)))
            # Missing a model-wide input is still NOT_EVALUATED: an active
            # mandatory rule must veto PASS just as it does with zero subjects.
            if _is_mandatory(profile, spec, ctx):
                mandatory_not_evaluated.append(spec.rule_id)
            continue
        target = dmodel
        withheld, missing_input = 0, ""
        # A stage may name SEVERAL inputs for one rule: HAB030 has two —
        # "the room's outline is measurable" and "some fact about the window
        # was read at all" — and the second does not replace the first, it
        # supplements it. The order is kept as written, so the reason in
        # coverage reads the same run to run.
        required = _required_inputs(profile, spec.rule_id)
        subject_ctx = ctx
        if required:
            target, withheld, missing_input = _filtered_subjects(
                dmodel, drep, spec.rule_id, required)
            # THE SUBJECT COUNT IS TAKEN FROM THE MODEL THE RULE ACTUALLY SAW.
            # `spatial_model.RuleOutcome` declares `n_subjects` as "elements
            # the rule examined," but it was counted over the FULL model:
            # measurement 17.08 on the `make_good()` reference with no walls
            # gave HAB030 = EVALUATED(n=2) even though both subjects were
            # withheld and the rule said not a word. "Looked and it was
            # clean" instead of "there was nothing to look at" — exactly what
            # the three-valued verdict was set up to catch. Subtracting
            # `withheld` from `n` is NOT ALLOWED: that is a count over a
            # DIFFERENT population (all rooms with no entrance are withheld,
            # while `n` counts only habitable rooms and kitchens), and the
            # difference of two different units is not a number. Recounting
            # over the filtered model is legitimate precisely because the
            # filter is admitted only for rules in `_ROOM_FILTERABLE` /
            # `_DOOR_FILTERABLE` — which consider subjects INDEPENDENTLY.
            subject_ctx = replace(ctx, model=target)
        _bin(spec.fn(target, graph, thr), blocking, warnings, info)
        n = spec.subjects(subject_ctx)
        excluded_ru = f"нет входа {missing_input}" if withheld else ""
        # A subject that can be judged only by guesswork is NOT a checked
        # subject. It moves from `n` into `excluded_subjects` with a named
        # reason, and when ALL subjects turn out this way, the branch below
        # reads it as "the subject EXISTS, but every subject is withheld,"
        # i.e. NOT_EVALUATED, not a skip.
        if spec.unverifiable is not None:
            blind, blind_why = spec.unverifiable(subject_ctx)
            if blind:
                withheld += blind
                excluded_ru = f"{excluded_ru}; {blind_why}" if excluded_ru else blind_why
                n = max(0, n - blind)
        if n > 0:
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.EVALUATED, n_subjects=n,
                excluded_subjects=withheld, excluded_reason=excluded_ru))
        else:
            # THE REASON MUST NAME THE EMPTINESS THAT ACTUALLY OCCURRED.
            # `vacuous_reason` is a specification constant, and it says "no
            # subject of this kind exists." When the subject DID exist but was
            # entirely withheld for lack of an input, this constant asserts a
            # falsehood: measurement 17.08 on the reference with no walls
            # printed for HAB030 "no classified жилая/кухня rooms," even
            # though a habitable room and a kitchen were both present, and
            # what was unread was the WINDOW. The same kind of lie as HAB011's
            # "stairs present" with zero stairs. The two cases can be told
            # apart by exactly one question: did the rule have a subject
            # BEFORE the filter.
            reason = spec.reason_for(ctx)
            if withheld and spec.subjects(ctx) > 0:
                reason = (f"предмет ЕСТЬ, но все субъекты удержаны: {excluded_ru}. "
                          f"Это утверждение о том, что удалось прочитать, а не о здании")
            outcomes.append(RuleOutcome(
                rule_id=spec.rule_id, status=RuleStatus.NOT_EVALUATED,
                reason=reason, excluded_subjects=withheld,
                excluded_reason=excluded_ru))
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
    # 🔴 A THRESHOLD CLEARED BY OUR OWN INFERENCE IS NOT A CLEARED THRESHOLD
    # (22.08.2026).
    #
    # `classification_coverage` answers "how many rooms are classified" and
    # does NOT answer "classified as what." Since 22.08, room function can be
    # DERIVED from furnishing (`function_provenance`), and a building with no
    # names at all can rack up coverage from toilets alone. Declaring PASS on
    # that basis would mean passing off our own inference as something read
    # — the very defect `function_source` was set up against.
    #
    # The condition is deliberately NARROW: the note is set only when the
    # inference DECIDED the outcome — the threshold is cleared with it and
    # not cleared without it. A building where names are written and
    # furnishing merely confirms them loses nothing, and PASS stays
    # reachable; the note means exactly what it says.
    n_rooms = len(model.rooms)
    n_derived_function = len(drep.derived_function_room_ids)
    authored_coverage = (
        (n_rooms - len(drep.unclassified_room_ids) - n_derived_function) / n_rooms
        if n_rooms else 0.0)
    if (n_derived_function
            and drep.classification_coverage >= thr.min_classification_coverage
            > authored_coverage):
        # 🔴 THE NOTE MUST NAME WHOSE INFERENCE THIS IS (28.08.2026). Until
        # that day there was one derived kind — furnishing — and the text
        # unconditionally said "DERIVED by us from furnishing." With the
        # arrival of the `ROOM_CLASSIFIER` port, derived kinds became TWO, and
        # the former wording became a lie in the voice of a measurement:
        # "by us" and "from furnishing" are both wrong when the host named the
        # function. The same defect and the same fix as in
        # `function_provenance.describe`. The breakdown is taken from the
        # model itself — `Room.function_source` already carries the answer,
        # no new wiring is needed.
        derived_ids = set(drep.derived_function_room_ids)
        by_source: dict[str, int] = {}
        for room in model.rooms:
            if room.id in derived_ids:
                key = room.function_source or "источник не назван"
                by_source[key] = by_source.get(key, 0) + 1
        breakdown = ", ".join(f"{src} — {n}"
                              for src, n in sorted(by_source.items()))
        notes.append(
            f"порог классификации {thr.min_classification_coverage:.0%} взят ТОЛЬКО "
            f"благодаря выводу: функция прочитана у автора у {authored_coverage:.0%} "
            f"помещений, ВЫВЕДЕНА ещё у {n_derived_function} ({breakdown}). "
            f"Вердикт не может быть положительным по классификации, которую назвал "
            f"не автор — назовите помещения в модели.")

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

    With KIR_CHECKER_V2=1 the v2 pipeline runs instead (see module docstring):
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
