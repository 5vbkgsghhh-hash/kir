# -*- coding: utf-8 -*-
"""Stage C2: a source edit -> three sets, residue, deviation, questions.

The measures are taken from the acceptance instrument (`refine-loop/acceptance`)
and from analysis computed WITHOUT the product: an atrium edit 2000→3000
changes each of the three floors' area by −5 000 000 mm²; a facade edit −800
gives +11 200 000 on two floors and +9 760 000 on the top one (its setback is
1800). None of these numbers is computed by the product here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kir.project import _canonical, _thaw, output_id
from kir.project_refinement import (RefinementError, _changed_ops, _deviation_of,
                                    _free_ends,
                                    _slab_edges_without_walls, _walls_touched,
                                    answer_question, apply_source_change, open_questions,
                                    record_pending_change, refine_after_source_change)
from kir.project_selection import selected_instance_program
from kir.project_store import ProjectStore
from kir.tests.fixtures import GROUND_SNAPSHOT as G

ROOT = Path(__file__).resolve().parents[2]


def _regions(ops):
    """Closed areas per level — counted by shapely, not by eye."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union

    levels = {}
    for op in ops:
        if op["op"] == "create_wall":
            levels.setdefault(_canonical(op.get("level")), []).append(op)
    return sum(len(list(polygonize(unary_union(
        [LineString([tuple(op["p0_mm"])[:2], tuple(op["p1_mm"])[:2]]) for op in walls]))))
        for walls in levels.values())
INSTANCE = "tower-a"
HOLE_A = [[4500.0, 2500.0], [7500.0, 5500.0]]
HOLE_C = [[4500.0, 2500.0], [7500.0, 9500.0]]
CHANGE_A = {"kind": "atrium_contour", "hole_mm": HOLE_A, "why": "контур атриума расширен"}
CHANGE_B = {"kind": "facade_curve", "outer_dy_mm": -800.0, "why": "изгиб фасада изменён"}
CHANGE_C = {"kind": "atrium_contour", "hole_mm": HOLE_C, "why": "атриум доведён до стены"}
DELTA_A = [-5_000_000.0] * 3
DELTA_B = [11_200_000.0, 11_200_000.0, 9_760_000.0]


def _сцена():
    """A scene from `examples/` — ONLY on call, not on module load.

    🔴 THERE USED TO BE A HARD EXIT HERE (fix on 07.09.2026). `from examples
    import X` at module level executes AT COLLECTION TIME: wherever
    `examples/` does not exist — which is everyone who installed the wheel
    (`[tool.setuptools.packages.find] include = ["kir*"]`) — it crashed THE
    WHOLE SUITE'S COLLECTION, not just one test.

    🔴 AND SPECIFICALLY `from examples import ...`, NOT
    `importlib.import_module(name)`. The latter would have moved the name
    into A STRING, where the boundary traversal cannot see it: the debt
    would not have become soft, it would have DISAPPEARED FROM THE LEDGER,
    and the guard would have turned green without untangling anything. The
    tree already paid exactly this price — the neighboring environment guard
    (`test_the_environment_has_one_door`) tripped over 24 references made
    through a helper, where the name was a call ARGUMENT. The exit stays
    visible, is named in the registry with a reason, and fails AT THE CALL
    SITE, rather than taking down the collection.
    """
    from examples import residential_project as towers
    from examples import residential_refinement as workflow
    from examples import residential_typed_section as typed

    return towers, workflow, typed


def _scene():
    towers, workflow, typed = _сцена()
    source = towers.concept()
    base = workflow.develop_section(source, height_mm=4200., setback_mm=1800.)
    detailed = typed.add_section_types(
        base, source=source, expected_revision=base.revision_id,
        wall_name="KIR_Section_Wall_230",
        wall_layers=[{"width_mm": 15, "function": "Finish1"},
                     {"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                     {"width_mm": 15, "function": "Finish2"}],
        wall_source_type={"by": "element_id", "value": G["wall_types"][0]["id"]},
        floor_name="KIR_Section_Floor_260",
        floor_layers=[{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                      {"width_mm": 50, "function": "Substrate"},
                      {"width_mm": 10, "function": "Finish1"}],
        floor_source_type={"by": "element_id", "value": G["floor_types"][0]["id"]})
    return source, base, detailed


@pytest.fixture(scope="module")
def scene():
    return _scene()


def _source_id(source):
    _towers, workflow, _typed = _сцена()
    return output_id(source.project_id, INSTANCE + workflow.CONCEPT_SUFFIX, "concept-volume")


def test_the_three_sets_partition_every_output(scene):
    """The sum of the three sets = all outputs. Otherwise an output disappears SILENTLY."""
    source, _base, detailed = scene
    program = selected_instance_program(detailed, INSTANCE)
    for change in (CHANGE_A, CHANGE_B, CHANGE_C):
        report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                            change=change)
        sets = [set(report.recomputed), set(report.preserved), set(report.needs_decision)]
        assert sets[0] & sets[1] == sets[0] & sets[2] == sets[1] & sets[2] == set()
        assert sum(len(s) for s in sets) == len(program["ops"]) == 23
        assert set().union(*sets) == {op["id"] for op in program["ops"]}


def test_the_atrium_change_recomputes_exactly_the_floors_and_asks_nothing(scene):
    source, _base, detailed = scene
    report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                        change=CHANGE_A)
    program = selected_instance_program(detailed, INSTANCE)
    floors = {op["id"] for op in program["ops"] if op["op"] == "create_floor_by_contour"}
    assert set(report.recomputed) == floors and len(floors) == 3
    assert report.needs_decision == () and report.questions == ()
    assert report.deviation["measure"] == "plan_area_delta_mm2"
    assert report.deviation["unit"] == "mm2"
    assert sorted(report.deviation["value"]) == pytest.approx(sorted(DELTA_A), rel=1e-9)


def test_the_facade_change_drags_the_corners_and_leaves_no_free_end(scene):
    """🔴 BEFORE, THE FACADE MOVED ALONE, AND THE OUTLINE SILENTLY TORE OPEN.

    The owner's measurement on 07.09.2026: an edit `outer_dy_mm=-800` moved
    THREE facade walls, the ends of the abutting walls stayed put, and the
    outline went from closed (3 areas, 0 loose ends) to torn (0 areas, 12
    loose ends) — while the report read `recomputed 6 · preserved 17 ·
    needs_decision 0`. Now the corner GETS DRAGGED ALONG: recomputed is 12
    (3 floors + 3 facades + 6 abutting ends), loose ends 0, and the areas
    number the same as before. The number 6 in the old pin was itself the
    defect.
    """
    source, _base, detailed = scene
    report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                        change=CHANGE_B)
    assert sorted(report.deviation["value"]) == pytest.approx(sorted(DELTA_B), rel=1e-9)
    program = {op["id"]: op for op in selected_instance_program(detailed, INSTANCE)["ops"]}
    kinds = sorted(program[oid]["op"] for oid in report.recomputed)
    assert kinds == ["create_floor_by_contour"] * 3 + ["create_wall"] * 9
    assert report.needs_decision == ()
    before_ops = [_thaw(op) for op in selected_instance_program(detailed, INSTANCE)["ops"]]
    after_ops = _changed_ops(before_ops, CHANGE_B)
    assert len(_free_ends(before_ops)) == 0
    assert len(_free_ends(after_ops)) == 0, "правка фасада разорвала контур"
    assert _regions(after_ops) == _regions(before_ops) == 3


def test_a_change_never_deletes_a_hole_it_did_not_address(scene):
    """An atrium edit WAS ERASING all other floor openings: the list was replaced wholesale."""
    source, _base, detailed = scene
    ops = [_thaw(op) for op in selected_instance_program(detailed, INSTANCE)["ops"]]
    stair = {"shape": "poly", "points_mm": [[11000.0, 6000.0], [12000.0, 6000.0],
                                            [12000.0, 7000.0], [11000.0, 7000.0]]}
    for op in ops:
        if op["op"] == "create_floor_by_contour":
            contour = _thaw(op["contour"])
            contour["holes"] = list(contour["holes"]) + [stair]
            op["contour"] = contour
    after = _changed_ops(ops, CHANGE_A)
    floors = [op for op in after if op["op"] == "create_floor_by_contour"]
    assert len(floors) == 3
    for op in floors:
        holes = op["contour"]["holes"]
        assert len(holes) == 2, "чужое отверстие исчезло"
        assert _canonical(holes[1]) == _canonical(stair), "лестничная шахта обязана уцелеть"


def test_a_change_that_addresses_two_holes_refuses_instead_of_guessing(scene):
    """Two openings under the new outline are the author's choice, not our guess."""
    source, _base, detailed = scene
    ops = [_thaw(op) for op in selected_instance_program(detailed, INSTANCE)["ops"]]
    twin = {"shape": "poly", "points_mm": [[7100.0, 3000.0], [7400.0, 3000.0],
                                           [7400.0, 5000.0], [7100.0, 5000.0]]}
    for op in ops:
        if op["op"] == "create_floor_by_contour":
            contour = _thaw(op["contour"])
            contour["holes"] = list(contour["holes"]) + [twin]
            op["contour"] = contour
    with pytest.raises(RefinementError, match="ambiguous_hole_address"):
        _changed_ops(ops, CHANGE_A)


def test_a_wall_in_the_way_becomes_a_question_not_a_silent_recompute(scene):
    """An affected wall axis is A DESIGN question. There is nothing here to decide for the human."""
    source, _base, detailed = scene
    report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                        change=CHANGE_C)
    assert len(report.needs_decision) == 3
    assert len(report.questions) == len(report.needs_decision)
    for question in report.questions:
        assert question.address in report.needs_decision
        assert len(question.choices) >= 2 and question.why
    # None of the affected ones landed in the recomputed set: there is no silent decision.
    assert set(report.needs_decision) & set(report.recomputed) == set()


def test_a_refused_measurement_is_named_and_never_becomes_zero(scene):
    """Rule 1 of the B2↔C2 contract: the absence of a number is NOT zero.

    🔴 THE EXAMPLE CHANGED, THE RULE DID NOT (07.09.2026). The refusal used to
    be served here by the `CHANGE_C` edit: a hole touches the outer ring, the
    polygon is invalid, and the measure vanished for ALL three floors at
    once. But the body is defined there, and the absence of a number was not
    a refusal but a loss: now the area is made honest via `buffer(0)`, and
    the point of contact is named by address. The rule is checked against a
    real refusal — an outline with nothing to read it by.
    """
    source, _base, detailed = scene
    report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                        change=CHANGE_C)
    assert report.deviation["measure"] == "plan_area_delta_mm2"
    assert any("self_intersecting" in line for line in report.analysis_limits), \
        report.analysis_limits

    ops = [_thaw(op) for op in selected_instance_program(detailed, INSTANCE)["ops"]]
    broken = []
    for op in ops:
        if op["op"] == "create_floor_by_contour":
            op = _thaw(op)
            op["contour"] = {**op["contour"],
                             "outer": {**op["contour"]["outer"],
                                       "points_mm": [[0.0, 0.0], [1.0, 1.0]]}}
        broken.append(op)
    deviation, limits = _deviation_of(ops, broken)
    assert deviation["value"] is None and deviation["measure"] is None, deviation
    assert limits, "отказ обязан быть НАЗВАН"
    assert any("plan_area_delta" in str(line) for line in limits), limits


def test_residue_is_a_number_with_an_address(scene):
    source, _base, detailed = scene
    report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                        change=CHANGE_A)
    assert report.residue
    assert all(row["address"] and row["count"] >= 1 for row in report.residue)
    # The residue's address is THE SOURCE: losses are declared about it, not about the descendant.
    assert {row["address"] for row in report.residue} == {_source_id(source)}
    assert {row["what"] for row in report.residue} >= {"concept_twist_removed",
                                                       "concept_top_taper_removed"}


def test_decisions_survive_the_recompute_byte_for_byte(scene):
    """Types are the author's decisions: they are in `preserved` and their digest does not move."""
    source, _base, detailed = scene
    program = selected_instance_program(detailed, INSTANCE)
    types = {op["id"] for op in program["ops"] if op["op"] == "create_wall_type"}
    assert len(types) == 2
    digests = set()
    for change in (CHANGE_A, CHANGE_B, CHANGE_C):
        report = refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                            change=change)
        assert types <= set(report.preserved)
        digests.add(report.decisions_digest)
    assert len(digests) == 1, "решения не зависят от рода правки источника"


def test_an_unknown_change_kind_refuses_by_name(scene):
    source, _base, detailed = scene
    with pytest.raises(RefinementError, match="unsupported_change_kind"):
        refine_after_source_change(None, detailed, source_output_id=_source_id(source),
                                   change={"kind": "make_it_nicer"})
    with pytest.raises(RefinementError, match="unknown_refinement_source"):
        refine_after_source_change(None, detailed, source_output_id="0" * 64, change=CHANGE_A)


def test_the_question_survives_a_restart_and_its_answer_goes_through_the_existing_merge(tmp_path):
    """The full circle: a question -> ANOTHER PROCESS sees it -> an answer -> accept_proposal."""
    source, base, detailed = _scene()
    store = ProjectStore.create(tmp_path / "scene.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    head = store.head()
    assert open_questions(store, head) == []

    record_pending_change(store, head, source_output_id=_source_id(source), change=CHANGE_C)
    pending = open_questions(store)
    assert len(pending) == 3

    child = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from kir.project_store import ProjectStore
from kir.project_refinement import open_questions
store = ProjectStore.open(sys.argv[1])
print(json.dumps([q.to_dict() for q in open_questions(store)], ensure_ascii=False))
""", str(tmp_path / "scene.sqlite")], capture_output=True, text=True, timeout=120,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    seen = json.loads(child.stdout)
    assert [row["question_id"] for row in seen] == [q.question_id for q in pending]

    with pytest.raises(RefinementError, match="not one of the declared choices"):
        answer_question(store, pending[0].question_id, "просто сделай хорошо")
    with pytest.raises(RefinementError, match="choice_not_implemented"):
        answer_question(store, pending[0].question_id, "split_wall_around_the_opening")

    before = store.head()
    after_id = answer_question(store, pending[0].question_id, "keep_wall_and_shrink_atrium")
    after = store.head()
    assert after.revision_id == after_id != before.revision_id
    assert after.parent_revision == before.revision_id, "предложение — прямой ребёнок головы"
    assert open_questions(store) == [], "отвеченный вопрос закрыт, а не остался висеть"
    # The decisions (types) survived the answer BYTE FOR BYTE.
    def types_of(revision):
        return _canonical([output.to_dict() for instance in revision.instances
                           for output in instance.outputs
                           if output.operation["op"] == "create_wall_type"])
    assert types_of(after) == types_of(before)
    # The hole genuinely shrank: the floor outline changed, and it changed DOWNWARD.
    holes = [_thaw(output.operation["contour"])["holes"][0]["points_mm"]
             for instance in after.instances for output in instance.outputs
             if output.operation["op"] == "create_floor_by_contour"]
    assert holes and all(max(point[1] for point in hole) <= 9000.0 for hole in holes)


def test_the_change_is_actually_saved_and_another_process_sees_it(tmp_path):
    """🔴 A REPORT IS NOT A CHANGE. The store's head did not move at all after edit B."""
    source, base, detailed = _scene()
    store = ProjectStore.create(tmp_path / "scene.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    head_before = store.head().revision_id
    refine_after_source_change(store, store.head(), source_output_id=_source_id(source),
                               change=CHANGE_B)
    assert store.head().revision_id == head_before, "отчёт обязан оставаться немым"

    saved = apply_source_change(store, store.head(), source_output_id=_source_id(source),
                                change=CHANGE_B)
    assert saved != head_before and store.head().revision_id == saved
    child = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from kir.project_store import ProjectStore
from kir.project_selection import selected_instance_program
store = ProjectStore.open(sys.argv[1])
walls = [op for op in selected_instance_program(store.head(), sys.argv[2])["ops"]
         if op["op"] == "create_wall"]
print(json.dumps({"head": store.head().revision_id,
                  "moved_ends": sum(1 for op in walls for point in (op["p0_mm"], op["p1_mm"])
                                    if float(point[1]) == -800.0)}))
""", str(tmp_path / "scene.sqlite"), INSTANCE], capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr[-500:]
    payload = json.loads(child.stdout)
    assert payload["head"] == saved
    # 3 facade walls with both ends + 6 abutting walls with one end = 12 ends at −800.
    assert payload["moved_ends"] == 12

    # An edit that touches the author's decision is NOT applied silently from here on.
    with pytest.raises(RefinementError, match="decision_required"):
        apply_source_change(store, store.head(), source_output_id=_source_id(source),
                            change=CHANGE_C)


def test_an_answer_closes_only_the_questions_its_result_no_longer_touches(tmp_path):
    """🔴 "NO MORE QUESTIONS" ≠ "THE DECISION WAS CARRIED OUT."

    The previous handler deleted the ENTIRE pending-questions list without
    asking the result what became of it: the owner's measurement showed all
    three affected walls being touched while "questions: 0." Now, after
    applying, the outline is recomputed: only the questions whose address the
    new outline does not touch get closed, and the trim is carried through to
    the wall's EDGE — half the width is taken from the declared type (230 mm
    → 115), not made up.
    """
    from dataclasses import replace as _replace

    from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal

    source, base, detailed = _scene()
    store = ProjectStore.create(tmp_path / "scene.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    pending = open_questions(store)
    assert len(pending) == 3
    answer_question(store, pending[0].question_id, "keep_wall_and_shrink_atrium")
    ops = [_thaw(op) for op in selected_instance_program(store.head(), INSTANCE)["ops"]]
    holes = [_thaw(op["contour"])["holes"][0]["points_mm"]
             for op in ops if op["op"] == "create_floor_by_contour"]
    top = max(point[1] for hole in holes for point in hole)
    assert top == 8885.0, "обрезка обязана дойти до ГРАНИ стены (9000 − 230/2)"
    touched = _walls_touched(ops, {"kind": "atrium_contour",
                                   "hole_mm": [[4500.0, 2500.0], [7500.0, top]]})
    assert touched == [], "контур всё ещё задевает ось"
    assert open_questions(store) == [], "касания нет — вопросы закрыты законно"

    # And now THE SAME edit where the wall's width is NOT declared: the trim
    # reaches only the axis, the contact remains — and the questions must
    # stay open.
    head = store.head()
    instance = next(item for item in head.instances if item.key == INSTANCE)
    stripped = tuple(
        _replace(output, operation={key: value
                                    for key, value in _thaw(output.operation).items()
                                    if key != "type"})
        if output.operation["op"] == "create_wall" else output
        for output in instance.outputs)
    candidate = head.replace_instance(_replace(instance, outputs=stripped),
                                      expected_revision=head.revision_id)
    accept_proposal(store, ChangeProposal(head, candidate,
                                          ProposalScope(instances=(INSTANCE,)),
                                          "test", "strip declared wall types"),
                    expected_revision=head.revision_id,
                    authorized_scope=ProposalScope(instances=(INSTANCE,)))
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    again = open_questions(store)
    assert len(again) == 3
    # 🔴 A NEW LAW, 07.09.2026, R2 OF THE END-TO-END INSTRUMENT: trimming to
    # the axis without a declared type was passing off made-up geometry as
    # designed. The previous draft expected here "trimmed to the axis,
    # contact remained, three questions open" — exactly the state that a
    # saved apartment building had no way out of. Half the width is a number
    # from the DECLARED type; no type means a named refusal with an action,
    # and not a single byte in the store.
    before_answer = store.head().dumps()
    with pytest.raises(RefinementError) as caught:
        answer_question(store, again[0].question_id, "keep_wall_and_shrink_atrium")
    assert caught.value.code == "wall_type_required_for_gap", caught.value
    assert again[0].address[:12] in str(caught.value), caught.value
    assert "create_wall_type" in str(caught.value), "действие не названо"
    assert ProjectStore.open(store.path).head().dumps() == before_answer
    left = open_questions(store)
    assert len(left) == 3, "отказ снял вопрос, которого не решил"
    assert all("wall_type_required_for_gap" in question.why for question in left), \
        "причина вопроса называет чужое"


def test_a_second_facade_change_moves_the_walls_and_the_slab_together(scene):
    """🔴 THE LITERAL `y == 0` HELD FOR EXACTLY ONE EDIT.

    Review 6's measurement: a second edit `outer_dy_mm=-800` moved the floor
    outline to −1600, while the walls stayed at −800 — the slab slid out from
    under the facade, and the report called the walls PRESERVED (`recomputed
    3 · preserved 20`), raised no questions, and printed no limits. The
    facade is now recognized by the CURRENT edge of its own level's floor
    outline, so the second edit moves both the walls and the slab.
    """
    source, _base, detailed = scene
    ops = [_thaw(op) for op in selected_instance_program(detailed, INSTANCE)["ops"]]
    once = _changed_ops(ops, CHANGE_B)
    twice = _changed_ops(once, CHANGE_B)

    def ys(rows, kind, reader):
        return sorted({round(value, 6) for op in rows if op["op"] == kind
                       for value in reader(op)})

    walls_once = ys(once, "create_wall", lambda op: (float(op["p0_mm"][1]),
                                                     float(op["p1_mm"][1])))
    slab_once = ys(once, "create_floor_by_contour",
                   lambda op: (point[1] for point in op["contour"]["outer"]["points_mm"]))
    walls_twice = ys(twice, "create_wall", lambda op: (float(op["p0_mm"][1]),
                                                       float(op["p1_mm"][1])))
    slab_twice = ys(twice, "create_floor_by_contour",
                    lambda op: (point[1] for point in op["contour"]["outer"]["points_mm"]))
    assert walls_once == slab_once == [-800.0, 9000.0]
    assert walls_twice == slab_twice == [-1600.0, 9000.0], "плита уехала из-под стен"
    assert _slab_edges_without_walls(twice) == ()
    assert len(_free_ends(twice)) == 0 and _regions(twice) == 3


def test_a_slab_edge_left_without_a_wall_becomes_a_question(scene):
    """A control in the other direction: where the link TRULY breaks, there must be a question."""
    from dataclasses import replace as _replace

    source, _base, detailed = scene
    instance = next(item for item in detailed.instances if item.key == INSTANCE)
    without_facade = tuple(
        output for output in instance.outputs
        if not (output.operation.get("op") == "create_wall"
                and float(output.operation["p0_mm"][1]) == 0.0
                and float(output.operation["p1_mm"][1]) == 0.0))
    stripped = detailed.replace_instance(_replace(instance, outputs=without_facade),
                                         expected_revision=detailed.revision_id)
    report = refine_after_source_change(None, stripped, source_output_id=_source_id(source),
                                        change=CHANGE_B)
    assert len(report.needs_decision) == 3 and len(report.questions) == 3
    assert all("slab" in question.choices[0] or "slab" in question.why
               for question in report.questions)
    assert any("slab edges left without a wall" in row for row in report.analysis_limits)
