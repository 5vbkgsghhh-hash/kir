"""THE VERDICT MUST EAT WHAT THE SANDBOX PRODUCES.

Measured 08.03, a live loop over nine turns: the model writes Python -> the
sandbox returns KIR OPERATIONS (`{"op": …, "id": …}`, fields flat,
references `{"by": "ref", …}`), while `spatial_model_from_program` accepts
L1 NODES (`{"kind": "op", "op_name": …, "params": {…}}`). No adapter
existed in the tree, and the loop never closed once.

Worse than the gap itself was WHAT it answered with. KIR operations fed in
directly give `ops = []` (not one node has a `kind` key), the empty model
falls into the degenerate gate `_run_v2`, and the verdict prints:

    HAB000 — model has no rooms

with 27 `create_room` in the program itself. The statement is FALSE, and it
lies in exactly the direction the model will run to fix it: adding rooms
where there are already twenty-seven.

THE LAW THESE TESTS HOLD. "Input of the wrong shape" and "the building has
no rooms" are DIFFERENT statements, and the second one lies. A door that
receives a shape not its own must say so directly, name the shape it saw,
and name the door it should have gone to.

Run: KUKAI_CHECKER_V2=1 venv/bin/python3.12 -m pytest \
        kir/tests/test_verdict_takes_kir_ops.py -q
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import design_check as dc  # noqa: E402


# ═════════════════════════════════════════════════════════════════════════
# Material: a small but REAL building in sandbox form
# ═════════════════════════════════════════════════════════════════════════

def kir_ops() -> list[dict]:
    """Two rooms enclosed by walls, a door, and a window — KIR operations as-is.

    The shape is exactly what comes out of
    `sandbox.execute_author_script(...).ops`: flat fields, `id` as a string,
    references as selectors `{"by": "ref"}`.
    """
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_level", "id": "lvl2", "elev_mm": 3000, "name": "Этаж 2"},
    ]
    lvl = {"by": "ref", "value": "lvl"}
    # an 8000 x 5000 rectangle with a partition down the middle
    box = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
           ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
           ((4000, 0), (4000, 5000))]
    for i, (p0, p1) in enumerate(box, start=1):
        ops.append({"op": "create_wall", "id": f"w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": lvl, "height_mm": 3000})
    ops.append({"op": "create_room", "id": "r1", "xy": [2000, 2500],
                "level": lvl, "name": "Жилая комната"})
    ops.append({"op": "create_room", "id": "r2", "xy": [6000, 2500],
                "level": lvl, "name": "Кухня"})
    ops.append({"op": "create_door", "id": "d1",
                "host": {"by": "ref", "value": "w5"}, "offset_mm": 2500})
    ops.append({"op": "create_window", "id": "win1",
                "host": {"by": "ref", "value": "w1"}, "offset_mm": 2000})
    ops.append({"op": "create_window", "id": "win2",
                "host": {"by": "ref", "value": "w3"}, "offset_mm": 2000})
    return ops


def l1_nodes() -> list[dict]:
    """The same two rooms, but in the form of L1 NODES — the decompiler's own
    internal business."""
    return [
        {"kind": "op", "op_name": "create_level", "_id": "n1",
         "source_element_id": "1", "params": {"elev_mm": 0, "name": "Этаж 1"}},
        {"kind": "op", "op_name": "create_room", "_id": "n2",
         "source_element_id": "2",
         "params": {"xy": [1000, 1000], "name": "Жилая",
                    "level": {"by": "name", "value": "Этаж 1", "_id": "1"}}},
    ]


# ═════════════════════════════════════════════════════════════════════════
# 1. THE VERDICT EATS KIR OPERATIONS
# ═════════════════════════════════════════════════════════════════════════

def test_kir_ops_reach_the_verdict_with_their_rooms_intact() -> None:
    """The main assertion: what the sandbox hands back reaches the verdict.

    What is measured is not "the function didn't crash" but a NUMBER: the
    verdict has as many rooms as there are `create_room` in the program.
    Shape identity without this number proves nothing — an empty model also
    "converts successfully."
    """
    ops = kir_ops()
    declared = sum(1 for op in ops if op["op"] == "create_room")
    model, witness = dc.spatial_model_from_ops(ops, building_id="проба")
    assert witness.rooms_total == declared == 2
    assert witness.counts["walls"] == 5
    assert witness.counts["doors"] == 1
    assert witness.counts["windows"] == 2

    verdict = dc.check_ops(ops, building_id="проба")
    blocking = [v.rule_id for v in verdict.report.blocking]
    assert "HAB000" not in blocking, (
        "вердикт по 15 операциям с двумя помещениями всё ещё говорит "
        "«в модели нет помещений»")
    # And this is not an empty run: the polygons closed up, so the rules
    # about area and light really did speak.
    assert witness.rooms_measured == 2, witness.unmeasured_reasons


def test_the_ops_door_is_not_a_tautology() -> None:
    """Reversibility proves little: the result must be LEGITIMATE.

    We check that the polygons are real (the areas match the drawing: 4x5
    and 4x5 meters), not that "the conversion went through."
    """
    model, _ = dc.spatial_model_from_ops(kir_ops(), building_id="проба")
    areas = sorted(round(room.area_m2) for room in model.rooms)
    assert areas == [20, 20], areas
    assert {room.name for room in model.rooms} == {"Жилая комната", "Кухня"}


# ═════════════════════════════════════════════════════════════════════════
# 2. THE WRONG SHAPE — NAMED DIRECTLY, NOT RETOLD AS "NO ROOMS"
# ═════════════════════════════════════════════════════════════════════════

def test_the_l1_door_refuses_kir_ops_instead_of_reporting_an_empty_building() -> None:
    """THE DEFECT for which this file was written.

    Before the fix: `spatial_model_from_program(kir_ops())` returns a model
    without a single room, and the verdict over it prints HAB000 "model has
    no rooms." After: a typed refusal that names the shape it saw.
    """
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.spatial_model_from_program(kir_ops(), building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text
    assert "create_level" in text or "ops[0]" in text
    # The refusal must name the DOOR it should have gone to.
    assert "spatial_model_from_ops" in text or "check_ops" in text
    # And it has no right to look like a statement about the building.
    assert "no rooms" not in text and "нет помещений" not in text


def test_the_ops_door_refuses_l1_nodes_and_says_whose_form_that_is() -> None:
    """Symmetry: the L1 shape is the decompiler's own internal business, and
    the outer door must say so, rather than silently reading zero
    operations."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.spatial_model_from_ops(l1_nodes(), building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text
    assert "L1" in text


@pytest.mark.parametrize("bad, needle", [
    ([], "пуст"),
    ("create_wall", "строка"),
    ([{"op": "create_wall"}, 42], "ops[1]"),
    ([{"id": "w1", "p0_mm": [0, 0]}], "op"),
])
def test_every_wrong_input_names_itself(bad, needle) -> None:
    """A refusal that does not name what it saw is a second round of repair."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.spatial_model_from_ops(bad, building_id="проба")
    assert needle in caught.value.render(), caught.value.render()


def test_a_program_envelope_is_accepted_as_well_as_a_bare_list() -> None:
    """The sandbox hands back a list, the pipeline hands back
    `{"ops": [...]}`. Both shapes are KIR operations, and demanding the
    caller unwrap it would introduce a third shape where there are already
    two."""
    envelope = {"ir_version": "1.0", "ops": kir_ops()}
    model, witness = dc.spatial_model_from_ops(envelope, building_id="проба")
    assert witness.rooms_total == 2


# ═════════════════════════════════════════════════════════════════════════
# 3. THE HEADLINE IS NOT STRONGER THAN THE BODY
# ═════════════════════════════════════════════════════════════════════════

def test_a_not_evaluated_verdict_never_hides_rule_coverage() -> None:
    """An integration carrier: on a real KIR program, part of the rules is
    evaluated, while the mandatory preconditions for others are not proven.
    The outcome is honestly `NOT_EVALUATED`, but it has no right to hide the
    coverage denominator.
    """
    verdict = dc.check_ops(kir_ops(), building_id="проба")
    coverage = verdict.report.coverage
    evaluated = coverage.rules_evaluated
    total = len(coverage.outcomes)
    assert evaluated < total, (
        "материал перестал быть материалом: на этой программе оценены ВСЕ "
        "правила, и заголовку нечего скрывать — тест потерял предмет")
    # Mandatory preconditions refuse fail-closed: this carrier is honestly
    # NOT_EVALUATED and must still name the coverage in the first line.
    assert verdict.verdict is dc.Verdict.NOT_EVALUATED

    head = dc.render_verdict(verdict).splitlines()[0]
    assert str(evaluated) in head and str(total) in head, head
    assert "НЕ ОЦЕНЕН" in head.upper(), head
    # Historically a bare "FIT" stood here; neither that old outcome nor a
    # bare "NOT EVALUATED" has the right to hide the coverage.
    assert head.strip() != "═══ ВЕРДИКТ О ЗАМЫСЛЕ: ПРИГОДЕН ═══"


@pytest.mark.parametrize(("evaluated", "total"), [
    (0, 20),
    (10, 20),
    (20, 20),
])
def test_a_not_evaluated_headline_names_its_rule_coverage(
    evaluated: int, total: int,
) -> None:
    assert dc.verdict_headline_text(
        dc.Verdict.NOT_EVALUATED, evaluated=evaluated, total=total,
    ) == f"ИТОГ НЕ ОЦЕНЕН; ОЦЕНЕНО {evaluated} ПРАВИЛ ИЗ {total}"


def test_a_partial_pass_headline_names_its_rule_coverage() -> None:
    assert dc.verdict_headline_text(
        dc.Verdict.PASS, evaluated=10, total=20,
    ) == "ПРИГОДЕН ПО 10 ПРАВИЛАМ ИЗ 20, ОСТАЛЬНОЕ НЕ ОЦЕНЕНО"


def test_the_headline_of_a_full_pass_stays_short() -> None:
    """A caveat has no right to stand where there is nothing to caveat: if
    all rules were evaluated, the headline must stay plain."""
    verdict = dc.check_ops(kir_ops(), building_id="проба")
    coverage = verdict.report.coverage
    n = len(coverage.outcomes)
    assert dc.verdict_headline_text(
        dc.Verdict.PASS, evaluated=n, total=n) == "ПРИГОДЕН"


# ═════════════════════════════════════════════════════════════════════════
# 4. THE SHORT VERDICT FITS THE SANDBOX CHANNEL
# ═════════════════════════════════════════════════════════════════════════

def separator_ops() -> list[dict]:
    """A room enclosed by THREE walls and ONE room separator.

    This is exactly how everything open to a corridor is closed: there is
    and must be no fourth wall there. `create_room_separator` EXISTS in the
    language (`spec.OPS`, measured by me, 08.03: parameters `path` +
    `level`), and the program writes it.
    """
    lvl = {"by": "ref", "value": "lvl"}
    return [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
        # A level above is needed on the merits: room height is computed only
        # if the enclosure REACHES the next level ("an enclosure is not a
        # ceiling"). Without it the height is honestly unknown, and the test
        # about separators diluting the vote would have no subject.
        {"op": "create_level", "id": "lvl2", "elev_mm": 3000, "name": "Этаж 2"},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [4000, 0],
         "level": lvl, "height_mm": 3000},
        {"op": "create_wall", "id": "w2", "p0_mm": [4000, 0],
         "p1_mm": [4000, 5000], "level": lvl, "height_mm": 3000},
        {"op": "create_wall", "id": "w3", "p0_mm": [4000, 5000],
         "p1_mm": [0, 5000], "level": lvl, "height_mm": 3000},
        # THE FOURTH SIDE IS A SEPARATOR, not a wall.
        {"op": "create_room_separator", "id": "sep1",
         "path": [[0, 5000], [0, 0]], "level": lvl},
        {"op": "create_room", "id": "r1", "xy": [2000, 2500], "level": lvl,
         "name": "Жилая комната"},
    ]


def test_a_room_closed_by_a_separator_gets_its_polygon() -> None:
    """DEFECT: the planar partition was built ONLY from `create_wall`.

    A room separator is a full-fledged room boundary in Revit, and it exists
    in the KIR language. As long as it did not reach the partition, a room
    open to a corridor did not close: there is no area, so HAB020 says "area
    0," HAB030 says "no window," HAB040/HAB060 stay silent. The instrument
    exists, the data exists, there was no wire.
    """
    ops = separator_ops()
    model, witness = dc.spatial_model_from_ops(ops, building_id="проба")
    assert witness.rooms_total == 1
    assert witness.rooms_measured == 1, (
        f"комната не замкнулась: {dict(witness.unmeasured_reasons)}")
    assert round(model.rooms[0].area_m2) == 20, model.rooms[0].area_m2
    # A separator is NOT a wall: the wall rules have no right to count it.
    assert witness.counts["walls"] == 3
    assert len(model.walls) == 3
    # And it does not invent a height: a separator has none at all.
    assert model.rooms[0].height_mm == 3000, model.rooms[0].height_mm


def test_a_separator_alone_does_not_invent_a_room() -> None:
    """The flip side: a separator that closes nothing has no right to give a
    room a polygon."""
    ops = [op for op in separator_ops() if op["op"] != "create_wall"]
    _model, witness = dc.spatial_model_from_ops(ops, building_id="проба")
    assert witness.rooms_measured == 0
    assert witness.rooms_total == 1


def test_a_building_without_stairs_is_never_told_its_stairs_lack_geometry() -> None:
    """D-4. `engine.RULE_SPECS_V2` carries a hardcoded string for HAB011,
    "stairs present but none has measured geometry" — and prints it with
    ZERO stairs in the model. The string asserts the presence of something
    that isn't there, and asserts it confidently: the model reads it as
    "stairs exist but their curves are bad."
    """
    verdict = dc.check_ops(kir_ops(), building_id="проба")
    assert verdict.witness.counts["stairs"] == 0, "материал потерял предмет"
    reasons = {o.rule_id: o.reason for o in verdict.report.coverage.outcomes}
    assert "stairs present" not in reasons["HAB011"], reasons["HAB011"]
    assert "лестниц" in reasons["HAB011"].lower(), reasons["HAB011"]


def test_a_building_with_stairs_still_gets_the_stair_rule() -> None:
    """The flip side: a discharge must be CONDITIONAL. A rule that is always
    discharged is a rule that does not exist.

    WHY A BATCH HERE, NOT ONE PROGRAM (edit of 08.04). The first edition
    appended `create_stairs` to the body and called `check_ops` — that is,
    it checked a correct assertion on a program THE COMPILER WILL NOT TAKE
    (`KIR-L002`: stairs own their own transactions and must be the sole op).
    The test was pinning exactly the defect for which `KIR-V003` was later
    opened: the verdict judged the fitness of the unbuildable. The assertion
    stayed the same, the carrier changed — the stairs moved into their own
    link, as is proper in a real building.
    """
    stairs = {"op": "create_stairs", "id": "s1",
              "p0_mm": [1000, 1000], "p1_mm": [1000, 4000],
              "base_level": {"by": "name", "value": "Этаж 1"},
              "top_level": {"by": "name", "value": "Этаж 2"},
              "width_mm": 1200}
    verdict = dc.check_bundle(
        [{"ir_version": "1.0", "ops": kir_ops()},
         {"ir_version": "1.0", "ops": [stairs]}],
        building_id="проба")
    assert verdict.witness.counts["stairs"] == 1
    assert "HAB011" not in verdict.rules_suspended, verdict.rules_suspended


def test_the_brief_verdict_fits_the_sandbox_stdout() -> None:
    """The sandbox's `stdout` is truncated at `MAX_STDOUT_CHARS`, and a
    verdict that eats the whole channel takes away the model's own output.
    The full verdict is too large for this channel — the short one must fit
    with room to spare."""
    from kir.sandbox import MAX_STDOUT_CHARS

    verdict = dc.check_ops(kir_ops(), building_id="проба")
    brief = dc.render_verdict_brief(verdict)
    assert len(brief) < MAX_STDOUT_CHARS // 2, len(brief)
    # Brevity has no right to cost honesty: the headline is the same.
    assert brief.splitlines()[0] == dc.render_verdict(verdict).splitlines()[0]
    # And it must name exactly what was NOT evaluated.
    assert "не оценено" in brief.lower()


# ═════════════════════════════════════════════════════════════════════════
# 4. THE UNIT OF A BUILDING IS A BATCH OF PROGRAMS, NOT A PROGRAM
#
# THE DEFECT for which this section was written. Two rules are each correct
# on their own:
#   * `create_stairs` is the sole op of its own program (KIR-L002): its
#     `StairsEditScope` owns its own transactions — a Revit API fact;
#   * `HAB010` blocks an occupied level above ground with no stair
#     connection.
# Together they gave a third, false one: a multi-story building expressed as
# ONE program is unfit BY CONSTRUCTION — you cannot put stairs into it, and
# without them the verdict must block. Measured on 08.03-04 (4 A/B runs, 2
# models, 20 turns each): NOT ONE building without blockers, all four with
# `stairs 0`. The strong model found the wall itself and improvised stairs
# out of 15 `create_floor`.
#
# What is fixed is the UNIT OF JUDGMENT, not the emitter: the ban is a Revit
# fact, but judging a program where the building is a BATCH of programs was
# our own mistake.
# ═════════════════════════════════════════════════════════════════════════

def two_storey_body() -> dict:
    """The body of a two-story building: WITHOUT stairs — putting them there
    is forbidden.

    The stairwell (a room) IS present here: it is an ordinary room and does
    not contradict the KIR-L002 law. Only `create_stairs` itself is missing.
    """
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"},
        {"op": "create_level", "id": "lvl2", "elev_mm": 3000, "name": "Этаж 2"},
    ]
    box = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
           ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
           ((4000, 0), (4000, 5000))]
    for storey, lid in ((1, "lvl"), (2, "lvl2")):
        lvl = {"by": "ref", "value": lid}
        for i, (p0, p1) in enumerate(box, start=1):
            ops.append({"op": "create_wall", "id": f"w{storey}_{i}",
                        "p0_mm": list(p0), "p1_mm": list(p1),
                        "level": lvl, "height_mm": 3000})
        ops.append({"op": "create_room", "id": f"r{storey}", "xy": [6000, 2500],
                    "level": lvl, "name": "Жилая комната"})
        ops.append({"op": "create_room", "id": f"st{storey}", "xy": [2000, 2500],
                    "level": lvl, "name": "Лестничная клетка"})
        # a door between the living room and the stairwell
        ops.append({"op": "create_door", "id": f"d{storey}",
                    "host": {"by": "ref", "value": f"w{storey}_5"},
                    "offset_mm": 2500})
        ops.append({"op": "create_window", "id": f"win{storey}",
                    "host": {"by": "ref", "value": f"w{storey}_2"},
                    "offset_mm": 2500})
    # the outside entrance — into the first-floor stairwell
    ops.append({"op": "create_door", "id": "entrance",
                "host": {"by": "ref", "value": "w1_1"}, "offset_mm": 2000})
    return {"ir_version": "1.0", "ops": ops}


def stairs_program() -> dict:
    """Stairs as a SEPARATE program, levels addressed BY NAME.

    By name, not by reference, and this is not a style choice:
    `create_stairs.base_level` does not accept `ref` (`ref_kinds` is empty —
    KIR-G002), and moreover the level lives in ANOTHER program of the batch,
    where its `id` no longer exists.
    """
    return {"ir_version": "1.0", "ops": [{
        "op": "create_stairs", "id": "s1",
        "p0_mm": [2000, 1000], "p1_mm": [2000, 4000],
        "base_level": {"by": "name", "value": "Этаж 1"},
        "top_level": {"by": "name", "value": "Этаж 2"},
        "width_mm": 1200}]}


def test_one_program_alone_cannot_express_a_habitable_two_storey_building() -> None:
    """THE FLOOR AS IT WAS. A body without stairs HAS NO RIGHT to be fit.

    🔴 THE MECHANISM CHANGED ON 2026-08-22, THE LAW DID NOT. Here it used to
    read "must be BLOCKED by HAB010 — and this is HONEST: there really is no
    connection between floors in it." That was honest exactly as long as
    stairs were absent FROM THE BUILDING. On a real model (MNVNK) the same
    accusation was voiced 23 times, and all 23 were about OUR OWN READING:
    there are 24 stairs there, and the extraction discarded all 24, demanding
    a parameter on which the building answered empty.

    The precondition is fixed: with not a single stair, there are no vertical
    edges BY CONSTRUCTION, and "the floor hangs" is indistinguishable from
    "there is nothing to descend by." The body still does not pass — but
    because THE MANDATORY RULE DID NOT SPEAK, not because it accused the
    building of our own hole.
    """
    verdict = dc.check_ops(two_storey_body(), building_id="тело")
    outcome = getattr(verdict.report.verdict, "value", verdict.report.verdict)
    assert outcome != "pass", outcome
    assert "HAB010" in verdict.report.coverage.mandatory_not_evaluated, \
        verdict.report.coverage.mandatory_not_evaluated
    rows = {o.rule_id: o for o in verdict.report.coverage.outcomes}
    assert "НЕТ НИ ОДНОЙ" in (rows["HAB010"].reason or ""), rows["HAB010"].reason


def test_the_same_building_as_a_bundle_clears_the_stair_rules() -> None:
    """THE FLOOR IS LIFTED. The same body + stairs as a SEPARATE program ->
    HAB010 goes away.

    What is checked is not "zero blockers" (that would confuse PASSED with
    NOT EVALUATED — a rule discharged by a profile also does not land among
    the blockers), but TWO assertions at once: the rule was EVALUATED and
    was not violated.
    """
    verdict = dc.check_bundle([two_storey_body(), stairs_program()],
                              building_id="пачка")
    blocking = [v.rule_id for v in verdict.report.blocking]
    assert "HAB010" not in blocking, blocking
    assert "HAB001" not in blocking, blocking
    # And the rule really DID speak, rather than being discharged for lack of
    # input.
    assert "HAB010" not in verdict.rules_suspended, verdict.rules_suspended
    assert verdict.witness.counts["stairs"] == 1


def test_the_bundle_keeps_the_order_it_was_given() -> None:
    """The batch's order matters: programs execute sequentially, and a level
    created by the first exists for the second. Merging is concatenation."""
    model, _ = dc.spatial_model_from_bundle(
        [two_storey_body(), stairs_program()], building_id="пачка")
    # The stairs addressed levels BY NAME across a program boundary — and
    # found them.
    stair = model.stairs[0]
    elevations = {lvl.id: lvl.elevation_mm for lvl in model.levels}
    assert elevations[stair.base_level_id] == 0
    assert elevations[stair.top_level_id] == 3000


def test_colliding_ids_across_programs_are_named_not_silently_merged() -> None:
    """`id` is unique WITHIN a program; a collision between programs is
    LEGITIMATE.

    Silently resolving it in favor of the last program would mean losing an
    element AND redirecting a reference into a foreign operation. Both
    survive, each has its own address, and the collision itself is NAMED in
    the witness.
    """
    one = {"ops": [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Э1"},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "level": {"by": "ref", "value": "lvl"}, "height_mm": 3000}]}
    two = {"ops": [
        {"op": "create_level", "id": "lvl", "elev_mm": 3000, "name": "Э2"},
        {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "level": {"by": "ref", "value": "lvl"}, "height_mm": 3000}]}
    model, witness = dc.spatial_model_from_bundle([one, two], building_id="х")
    assert len(model.walls) == 2, "стена второй программы затёрла первую"
    assert {w.id for w in model.walls} == {"p1/w1", "p2/w1"}
    # Each wall's reference resolved to ITS OWN level, not to the last one.
    by_id = {w.id: w.level_id for w in model.walls}
    assert by_id["p1/w1"] == "p1/lvl" and by_id["p2/w1"] == "p2/lvl"
    collision = [n for n in witness.notes if n.code == "bundle_id_collision"]
    assert collision and "lvl" in collision[0].detail, witness.notes


def test_a_ref_across_a_program_boundary_is_refused_by_name() -> None:
    """A reference lives WITHIN a program. The neighboring one is a separate
    transaction, where the first program's id no longer exists; silently
    ignoring such a reference would mean judging a different building than
    the one that will actually be built."""
    stairs = {"ops": [{
        "op": "create_stairs", "id": "s1", "p0_mm": [2000, 1000],
        "p1_mm": [2000, 4000],
        "base_level": {"by": "ref", "value": "lvl"},      # a FOREIGN program
        "top_level": {"by": "name", "value": "Этаж 2"}, "width_mm": 1200}]}
    with pytest.raises(dc.BundleContractError) as caught:
        dc.check_bundle([two_storey_body(), stairs], building_id="пачка")
    text = caught.value.render()
    assert "KIR-V002" in text
    assert "lvl" in text and "s1" in text        # what exactly and where
    assert "имени" in text.lower()               # and where to go instead


@pytest.mark.parametrize("bad, needle", [
    ([], "пуст"),
    ("тело", "строка"),
])
def test_a_malformed_bundle_names_itself(bad, needle) -> None:
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.check_bundle(bad, building_id="проба")
    assert needle in caught.value.render(), caught.value.render()


def test_one_program_in_the_bundle_door_is_told_which_door_it_wanted() -> None:
    """Symmetry with KIR-V001: a door must name not only what it saw, but
    also the door it should have gone to."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.check_bundle(two_storey_body(), building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text and "check_ops" in text


def test_a_list_of_programs_in_the_ops_door_is_told_about_the_bundle() -> None:
    """And conversely: a batch fed into a program's door must hear about the
    batch, not "can't tell what this is from the keys."""
    with pytest.raises(dc.ProgramShapeError) as caught:
        dc.check_ops([two_storey_body(), stairs_program()], building_id="проба")
    text = caught.value.render()
    assert "KIR-V001" in text and "check_bundle" in text


def test_a_query_op_is_not_mistaken_for_an_l1_node() -> None:
    """A SHAPE DEFECT found on 08.04 while working on the batch.

    `_shape_of` asked for `kind` BEFORE `op`, while `query_count`/`query_list`
    have THEIR OWN parameter named `kind`, lying flat. A legitimate KIR
    operation was declared an L1 node, and `check_ops` refused with
    KIR-V001, sending it to THE WRONG DOOR — exactly the lie about the input
    against which this whole file is written.
    """
    assert dc._shape_of({"op": "query_count", "id": "q", "kind": "wall"}) == "ops"
    ops = kir_ops() + [{"op": "query_count", "id": "q", "kind": "wall"}]
    model, _ = dc.spatial_model_from_ops(ops, building_id="проба")
    assert len(model.rooms) == 2
