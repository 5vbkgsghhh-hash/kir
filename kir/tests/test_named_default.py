"""A NAMED DEFAULT is a selection rule, not whatever comes first.

The refuting test was written FIRST and reproduces the live case from
02.08.2026 verbatim (`kir-bench`, task T1, the Snowdon document):

* the C# arm took `.FirstOrDefault()` over the collector — **1 door type out
  of 62** and 1 window out of 34 — and built it SILENTLY. The user got a door
  they never chose, and will not find out;
* the KIR arm refused with `KIR-G102` and a list of candidates, `execution:
  not_started`; the census confirmed a ZERO footprint.

Both outcomes are bad in their own way, and the fork between them is FALSE.
The correct answer is a third one, the same as in the HTML: **the button has
a default look, and it is NAMED, not accidental.** A named default differs
from `.FirstOrDefault()` in exactly one thing, but a decisive one: the rule is
declared in advance, and the choice it made lands in the receipt.

WHY THE RULE IS "MOST USED IN THE MODEL" AND NOT "THE DOCUMENT'S DEFAULT":
`ElementTypeGroup` contains NEITHER `DoorType` NOR `WindowType` — measured
with an instrument against RevitAPI.xml for all six versions (2021 and 2026
cross-checked member by member, 94 members; WallType/FloorType/RoofType/
CeilingType/TextNoteType are there, doors and windows are in none of them).
So `create_wall.type` has a document default (`ground.IN_EMIT_DEFAULT`),
while asking Revit "what is your default door" IS IMPOSSIBLE BY
CONSTRUCTION. The rule must rest on the document itself, and the only
explainable one is what a human would do: "place the same one that is
already standing throughout the project."

BOUNDARIES OF THE RULE (rigor does not give way where it is cheap):
* a tie at the maximum -> the refusal stands. A tie means the project has NO
  established practice, and the choice really would be arbitrary;
* not a single placed instance -> the rule does not apply, previous
  behavior;
* a snapshot without counters (the old bridge) -> previous behavior, byte for
  byte.
"""
from __future__ import annotations

import copy

from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT

# The live shape: 62 door types in a single document (Snowdon). One of them
# is placed throughout the project, the rest once or never. Exactly the
# situation where `.FirstOrDefault()` silently picks the wrong one.
def _door_pool() -> list[dict]:
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}",
             "instances": 1 if i % 3 == 0 else 0}
            for i in range(62)]
    # the project's established practice — 47 placed instances
    pool[31] = {"id": 7031, "name": "Дверь однопольная 900x2100",
                "instances": 47}
    return pool


def _snapshot(**pools) -> dict:
    snap = copy.deepcopy(GROUND_SNAPSHOT)
    snap.update(pools)
    return snap


def _door_program() -> dict:
    """A door without a `symbol` — the model did not name a type because it does not care."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
         "level": {"by": "name", "value": "Этаж 1"}, "height_mm": 3000,
         "type": {"by": "name", "value": "Кирпич 250"}},
        {"op": "create_door", "id": "d1", "host": {"by": "ref", "value": "w1"},
         "offset_mm": 3000},
    ]}


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


def _ground_one(program: dict, snapshot: dict, op_name: str, param: str):
    """Grounding is a separate stage: `ground()` returns ITS OWN list of ops
    with `{param: {"__grounded__": {...}}}`, and it does NOT go into
    PlannedProgram (measured: `compiler.py:1077` keeps it as a local
    variable and hands it straight to the emitter). So the rule is checked at
    its own stage, and its visibility to the user is a separate test on the
    receipt below."""
    from kir import ground as ground_mod
    from kir.compiler import plan_program
    normed = plan_program(program, bulk=False).to_ops()
    grounded = ground_mod.ground(normed, snapshot)
    op = next(o for o in grounded if o["op"] == op_name)
    sel = op.get(param)
    return sel.get("__grounded__") if isinstance(sel, dict) else None


def _compile(program, snapshot):
    return compile_program(program, revit_version="2026", snapshot=snapshot,
                           bulk=False)


def test_the_live_refusal_we_are_here_to_remove():
    """RIGHT NOW: 62 candidates -> KIR-G102, zero built. This is what we are fixing."""
    out = _compile(_door_program(), _snapshot(door_symbols=_door_pool()))
    assert out.ok, (
        "названное умолчание обязано построить дверь: правило «самый "
        f"употребимый» имеет однозначный максимум. Диагностики: {_codes(out)}")


def test_the_choice_is_named_in_the_receipt_not_merely_made():
    """A choice without a named rule is `.FirstOrDefault()` in a costume.

    What is checked is NOT the fact of building, but the reporting: which
    rule fired, what exactly was chosen, and out of how many candidates.
    Without this we would reproduce exactly the defect this test was written
    against.
    """
    snap = _snapshot(door_symbols=_door_pool())
    grounding = _ground_one(_door_program(), snap, "create_door", "symbol")
    assert grounding is not None, "заземление symbol обязано состояться"
    assert grounding.get("via") == "most_used", (
        f"правило обязано быть НАЗВАНО, получено via={grounding.get('via')!r}")
    assert grounding["id"] == 7031, "выбран не самый употребимый тип"
    assert grounding.get("rule_detail", {}).get("instances") == 47
    assert grounding.get("rule_detail", {}).get("candidates") == 62


def test_the_receipt_carries_the_choice_to_the_user():
    """A choice the user cannot see is indistinguishable from
    `.FirstOrDefault()`.

    This is the SECOND half of the work and a separate defect: today not a
    single choice the compiler makes — even the long-existing `sole_entry` —
    reaches the caller. `ground()` hands the result straight to the emitter,
    and `CompileOutput` says nothing about it.
    """
    out = _compile(_door_program(), _snapshot(door_symbols=_door_pool()))
    assert out.ok, _codes(out)
    report = out.as_dict().get("grounding_report")
    assert report, "квитанция обязана нести сделанные выборы"
    choice = next((r for r in report
                   if r["op_id"] == "d1" and r["param"] == "symbol"), None)
    assert choice is not None, f"выбор двери отсутствует в квитанции: {report}"
    assert choice["rule"] == "most_used"
    assert choice["chosen"]["id"] == 7031
    assert choice["chosen"]["name"] == "Дверь однопольная 900x2100"
    assert choice["rule_detail"]["candidates"] == 62


def test_a_tie_on_the_maximum_still_refuses():
    """A tie = the project has no practice, and the choice really is arbitrary."""
    pool = _door_pool()
    pool[7] = {"id": 7007, "name": "Дверь двупольная 1500x2100", "instances": 47}
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok, "ничья на максимуме не должна разрешаться молча"
    assert "KIR-G102" in _codes(out), _codes(out)


def test_a_weak_lead_is_not_a_practice_measured_on_snowdon():
    """25 against 21 is a coin toss, not a project standard.

    The numbers come from a live measurement on 03.08.2026 over decompiled
    buildings on disk (`snowdon_plumb`, doors: leader 25, runner-up 21,
    margin 1.2x, share 17%). Without a threshold, the rule would sign off on
    "most used in the model" where the difference is four doors.
    """
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(26)]
    pool[3] = {"id": 7003, "name": "36\" x 84\" (60 MIN)", "instances": 25}
    pool[9] = {"id": 7009, "name": "36\" x 84\"", "instances": 21}
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok, "отрыв 1.2x не может называться сложившейся практикой"
    assert "KIR-G102" in _codes(out), _codes(out)


def test_a_real_buildings_lead_still_builds():
    """A threshold must not kill the rule's meaning on a REAL building.

    `k2_ar_rd`, a live residential building from disk: 2096 doors, 35 types,
    leader «ДГ 21-8 П» 500 against 272 — a 1.8x margin. This is the
    project's established standard, and refusing here would mean losing the
    result for the sake of a round number. It was exactly this case that set
    the threshold at 1.5, not 2.0.
    """
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(35)]
    pool[2] = {"id": 7002, "name": "ДГ 21-8 П", "instances": 500}
    pool[5] = {"id": 7005, "name": "ДГ 21-9 Л", "instances": 272}
    grounding = _ground_one(_door_program(),
                            _snapshot(door_symbols=pool),
                            "create_door", "symbol")
    assert grounding["via"] == "most_used"
    assert grounding["id"] == 7002
    assert grounding["rule_detail"]["runner_up"] == 272


def test_a_clear_lead_still_builds():
    """2698 against 1219 — practice beyond any doubt."""
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(21)]
    pool[2] = {"id": 7002, "name": "00_ДВ 21-13Л_балкон", "instances": 2698}
    pool[5] = {"id": 7005, "name": "00_ДВ 21-9Л", "instances": 1219}
    grounding = _ground_one(_door_program(),
                            _snapshot(door_symbols=pool),
                            "create_door", "symbol")
    assert grounding["via"] == "most_used"
    assert grounding["id"] == 7002
    assert grounding["rule_detail"]["runner_up"] == 1219


def test_the_receipt_shows_the_runner_up_so_the_user_can_judge():
    """The threshold is SET, not measured — so the signal's strength is always shown."""
    from kir.ground import describe_choices_ru
    note = describe_choices_ru([
        {"op_id": "d1", "param": "symbol", "rule": "most_used",
         "chosen": {"id": 7031, "name": "ДГ 21-8 П"},
         "rule_detail": {"instances": 500, "candidates": 35,
                         "runner_up": 272}}])
    assert "500" in note and "272" in note, note


def test_no_placed_instances_keeps_the_old_behaviour():
    """Not a single one placed — the rule has nothing to rest on."""
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}", "instances": 0}
            for i in range(62)]
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok
    assert "KIR-G102" in _codes(out), _codes(out)


def test_a_snapshot_without_counters_is_byte_stable():
    """The old bridge sends no counters — the behavior must stay unchanged."""
    pool = [{"id": 7000 + i, "name": f"Дверь тип {i:02d}"} for i in range(62)]
    out = _compile(_door_program(), _snapshot(door_symbols=pool))
    assert not out.ok
    assert "KIR-G102" in _codes(out), _codes(out)


def test_an_explicit_selector_still_wins_over_the_rule():
    """A default fills silence, it NEVER overrides what was said."""
    program = _door_program()
    program["ops"][1]["symbol"] = {"by": "element_id", "value": 7005}
    snap = _snapshot(door_symbols=_door_pool())
    grounding = _ground_one(program, snap, "create_door", "symbol")
    assert grounding["id"] == 7005
    assert grounding["via"] == "element_id"


def test_the_note_speaks_human_not_machine():
    """`via=most_used` in the response is a machine code passed off as an explanation."""
    from kir.ground import describe_choices_ru
    note = describe_choices_ru([
        {"op_id": "d1", "param": "symbol", "rule": "most_used",
         "chosen": {"id": 7031, "name": "Дверь однопольная 900x2100"},
         "rule_detail": {"instances": 47, "candidates": 62}}])
    assert "Дверь однопольная 900x2100" in note
    assert "самый употребимый" in note
    assert "47" in note and "62" in note
    assert "most_used" not in note


def test_the_note_is_silent_when_there_was_nothing_to_choose():
    """A note saying "nothing happened" is noise, and noise teaches people not to read notes."""
    from kir.ground import describe_choices_ru
    assert describe_choices_ru([]) == ""
    # the only one in the model — there was no choice, nothing to defend
    assert describe_choices_ru([
        {"op_id": "w1", "param": "type", "rule": "sole_entry",
         "chosen": {"id": 100, "name": "Кирпич 250"}}]) == ""


def test_an_uncategorised_pool_must_not_get_a_named_default():
    """A POOL WITHOUT A CATEGORY COMPARES THE INCOMPARABLE — and there the
    rule must stay silent.

    THE REFUTING TEST, WRITTEN FIRST. It failed on the rule's first draft,
    and failed for good reason: `family_symbols` was in the list of pools,
    and it is the ONLY one collected without a category filter —

        __AddPool("door_symbols",   ...OfClass(FamilySymbol).OfCategory(OST_Doors)...)
        __AddPool("family_symbols", ...OfClass(FamilySymbol)...)   ← NO filter

    (`open_model.GROUND_SNAPSHOT_CS`; the other six pools all have a
    category filter in their rule, and beam_types also filters by placement
    type).

    THE MEASUREMENT THAT EXPOSED THIS (an offline rehearsal over 63 saved
    decompiles, 03.08.2026, before live Revit). What the rule picked in
    `family_symbols`:

        R_0_200Lx50W_-50   10 190 instances, margin 1.73x  — A CURTAIN-WALL MULLION TYPE
        Standard            8 070 instances, margin 4.51x
        170x60x5              151 instances, margin 2.29x
        305x305x97UC            2 instances, margin "no runner-up" — a steel profile

    A curtain-wall mullion is not placed by `place_family` at all: it is
    generated by the host's grid. That means `place_family` without a
    `symbol` would silently get an object that this operation never places —
    and that is WORSE than the previous refusal, not better.

    THE THRESHOLD DOES NOT PROTECT HERE, and that is the main point. The
    margins — 2.29x, 3.65x, 4.51x — are confident; the trouble is not in the
    signal's strength but in the fact that "most used" among ALL families in
    the document compares a mullion with a piece of furniture and with a room
    tag. The claim "this is the practice on this project" is meaningful only
    WITHIN a kind of thing.

    So the rule's boundary is structural, not numeric: a pool without a
    category narrowing never gets a named default.
    """
    mullion_heavy = [
        # Live shape from k2_ar_rd: curtain-wall mullions outnumber
        # everything else by a wide margin, because a grid generates them,
        # not a human.
        {"id": 9001, "name": "R_0_200Lx50W_-50", "instances": 10190},
        {"id": 9002, "name": "Стул офисный", "instances": 5876},
        {"id": 9003, "name": "Стол рабочий", "instances": 120},
    ]
    program = {"ir_version": "1.0", "ops": [
        {"op": "place_family", "id": "f1", "xyz": [1000, 1000, 0],
         "level": {"by": "name", "value": "Этаж 1"}},
    ]}
    out = compile_program(
        program, "2026", snapshot=_snapshot(family_symbols=mullion_heavy))
    assert not out.ok, (
        "place_family без symbol МОЛЧА получил тип из пула без категории; "
        "на живых данных это оказывался импост витража")
    assert any(d.code == "KIR-G102" for d in out.diagnostics), (
        "отказ обязан остаться типизированным KIR-G102 с кандидатами — "
        f"получено {[d.code for d in out.diagnostics]}")


def test_every_named_pool_is_narrowed_by_category():
    """A lock on the STRUCTURAL boundary, not on a list of names.

    A neighboring test holds the list of pools, but a list is just an
    enumeration, and it does not explain WHY a pool is not in it. What is
    checked here is the membership rule itself: every named-default pool
    must be narrowed by category in the snapshot collector itself. An author
    who wants to add a pool must first narrow its collector — and then the
    addition becomes safe by construction, not by the reviewer's
    attentiveness.
    """
    from kir.ground import MOST_USED_POOLS
    from kir.open_model import GROUND_SNAPSHOT_CS

    unnarrowed = []
    for pool in sorted(MOST_USED_POOLS):
        marker = f'__AddPool("{pool}"'
        start = GROUND_SNAPSHOT_CS.find(marker)
        assert start != -1, f"пул {pool} не собирается снапшотом вовсе"
        line = GROUND_SNAPSHOT_CS[start:GROUND_SNAPSHOT_CS.find("\n", start)]
        if ".OfCategory(" not in line:
            unnarrowed.append(pool)
    assert not unnarrowed, (
        "пул названного умолчания обязан быть сужен категорией — иначе "
        "«самый употребимый» сравнивает несравнимое (замер 03.08: импост "
        f"витража против мебели): {unnarrowed}")


def test_the_pool_list_is_closed_and_this_test_is_the_lock():
    """The rule's pool list is CLOSED, and the comment in ground.py promises
    exactly that.

    A promise without a lock is that same documentation which asserts the
    opposite of the truth (a defect class named in the package's canon). A
    pool that enters the rule without a measurement turns an honest refusal
    into a silent substitution — exactly the defect this rule was written
    against. Extending the list must be a separate decision that breaks this
    test and forces the author to explain what they measured it with.
    """
    from kir.ground import MOST_USED_POOLS
    assert MOST_USED_POOLS == frozenset({
        "door_symbols", "window_symbols",
        "column_symbols_structural", "column_symbols_architectural",
        "foundation_symbols", "beam_types",
    }), ("список пулов названного умолчания изменён — это осознанное решение "
         "с замером, а не побочный эффект правки")


def test_every_named_pool_actually_exists_in_the_registry():
    """A rule declared on a pool that does not exist is a dead letter."""
    from kir.ground import MOST_USED_POOLS
    from kir import spec
    declared = {pool.format(category=category)
                for op in spec.OPS.values()
                for _param, pool, _req in op.grounded
                for category in ("structural", "architectural")}
    unknown = MOST_USED_POOLS - declared
    assert not unknown, f"пулы правила отсутствуют в реестре: {sorted(unknown)}"


def test_the_sole_entry_path_is_untouched():
    """The sole one in a pool already resolved before — the rule does not change this path."""
    grounding = _ground_one(_door_program(), GROUND_SNAPSHOT,
                            "create_door", "symbol")
    assert grounding["via"] == "sole_entry"
