"""A persisted answer edits one atrium ring, never its neighbouring openings.

Project/Store/ChangeProposal and contour validation are real; no recipe replay,
native model, or BRep is involved in this authored section correction.
"""
from dataclasses import replace

import pytest

from kir.contour import validate_region
from kir.project import _canonical, _thaw, output_id
from kir.project_refinement import (RefinementError, answer_question, open_questions,
                                    record_pending_change)
from kir.project_store import ProjectStore
from kir.tests.test_a_source_change_names_all_three_sets import (
    CHANGE_C, INSTANCE, _scene, _source_id,
)


STAIR = {"shape": "poly", "points_mm": [[9800., 6200.], [10400., 6200.],
                                          [10400., 6800.], [9800., 6800.]]}
RECT_STAIR = {"shape": "rect", "origin": [9800., 6200.], "size_mm": [600., 600.]}
ARC_STAIR = {**STAIR, "arcs": [{"edge": 0, "bulge": 0.2}]}
# Intersects the REQUESTED atrium but not its eventual typed-wall shrink (8885).
AMBIGUOUS = {"shape": "poly", "points_mm": [[7200., 8890.], [7400., 8890.],
                                              [7400., 8990.], [7200., 8990.]]}


def _section(project):
    return next(instance for instance in project.instances if instance.key == INSTANCE)


def _floors(project):
    return [output for output in _section(project).outputs
            if output.operation["op"] == "create_floor_by_contour"]


def _revise_floors(project, transform, *, typed=True):
    instance = _section(project)
    outputs = []
    index = 0
    for output in instance.outputs:
        op = _thaw(output.operation)
        if op["op"] == "create_floor_by_contour":
            op["contour"]["holes"] = transform(op["contour"]["holes"], index)
            index += 1
        elif op["op"] == "create_wall" and not typed:
            op.pop("type", None)
        outputs.append(replace(output, operation=op))
    assert index == 3
    return project.replace_instance(replace(instance, outputs=outputs),
                                    expected_revision=project.revision_id)


def _store(tmp_path, *, mixed=False, target_index=0, typed=True):
    source, base, detailed = _scene()
    store = ProjectStore.create(tmp_path / "section.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    neighbours = (STAIR, RECT_STAIR, ARC_STAIR) if mixed else (STAIR,) * 3

    def add(holes, index):
        assert len(holes) == 1
        return ([holes[0], _thaw(neighbours[index])] if target_index == 0
                else [_thaw(neighbours[index]), holes[0]])

    with_holes = _revise_floors(detailed, add, typed=typed)
    store.commit(with_holes, expected_revision=detailed.revision_id)
    for output in _floors(with_holes):
        diagnostics = []
        assert validate_region(_thaw(output.operation["contour"]), [], output.key,
                               "contour", diagnostics) is not None, diagnostics
    return store, source


@pytest.mark.parametrize("typed", [True, False], ids=["known-width", "unknown-width"])
@pytest.mark.parametrize("mixed", [False, True], ids=["poly-neighbours", "mixed-shapes"])
@pytest.mark.parametrize("target_index", [0, 1], ids=["atrium-first", "atrium-last"])
def test_answer_preserves_other_holes_and_questions_after_reopen(
        tmp_path, typed, mixed, target_index):
    store, source = _store(tmp_path, typed=typed, mixed=mixed, target_index=target_index)
    original = store.head()
    original_bytes = original.dumps()
    record_pending_change(store, original, source_output_id=_source_id(source), change=CHANGE_C)
    pending_revision = store.head()
    pending_bytes = pending_revision.dumps()
    questions = open_questions(store)
    assert len(questions) == 3

    # 🔴 A NEW LAW, 2026-09-07, R2 OF THE END-TO-END INSTRUMENT
    # (docs/FINAL_RESULT_RU.md): without a DECLARED wall type, "trim to
    # axis" was passing off invented geometry as the design one — the atrium
    # was trimmed exactly on the axis, `_still_open` counted a touch as an
    # intersection, and the saved residential complex forever showed "asked
    # 3, answered 3, open 3." The earlier version of this parametrization
    # locked in exactly that behavior (`9000.0` and "questions remained").
    # Now the half-width is taken ONLY from the declared type, and its
    # absence is a named refusal with an action, before any write to the
    # store.
    writer = ProjectStore.open(store.path, readonly=False)
    if not typed:
        address = questions[0].address
        with pytest.raises(RefinementError) as caught:
            answer_question(writer, questions[0].question_id, "keep_wall_and_shrink_atrium")
        assert caught.value.code == "wall_type_required_for_gap", caught.value
        assert address[:12] in str(caught.value), caught.value
        assert "create_wall_type" in str(caught.value), "действие не названо"
        untouched = ProjectStore.open(store.path)
        assert untouched.head().dumps() == pending_bytes, "отказ всё же что-то записал"
        assert {question.question_id for question in open_questions(untouched)} == \
            {question.question_id for question in questions}
        for output in _floors(untouched.head()):
            assert len(_thaw(output.operation["contour"])["holes"]) == 2, \
                "отказ тронул чужое отверстие"
        return

    # And with a DECLARED type, the entire earlier happy path still holds:
    # the answer corrects EXACTLY the addressed ring and does not touch the
    # neighboring opening.
    answer_id = answer_question(writer, questions[0].question_id, "keep_wall_and_shrink_atrium")
    reopened = ProjectStore.open(store.path)
    after = reopened.head()
    assert after.revision_id == answer_id
    assert after.parent_revision == pending_revision.revision_id
    assert reopened.get(original.revision_id).dumps() == original_bytes
    assert reopened.get(pending_revision.revision_id).dumps() == pending_bytes

    before_floors, after_floors = _floors(original), _floors(after)
    assert [output.key for output in before_floors] == [output.key for output in after_floors]
    for before, updated in zip(before_floors, after_floors):
        before_op, after_op = _thaw(before.operation), _thaw(updated.operation)
        old_holes, holes = before_op["contour"]["holes"], after_op["contour"]["holes"]
        assert len(holes) == 2, "answer discarded another authored opening"
        assert _canonical(holes[1 - target_index]) == _canonical(old_holes[1 - target_index])
        assert max(point[1] for point in holes[target_index]["points_mm"]) == 8885.0
        # Restore ONLY the addressed ring: everything else must be identical,
        # including floor type/level refs, outer contour, and neighbour curve data.
        holes[target_index] = old_holes[target_index]
        assert _canonical(after_op) == _canonical(before_op)
    assert [module.to_dict() for module in after.modules] == [
        module.to_dict() for module in original.modules]
    assert [instance.to_dict() for instance in after.instances if instance.key != INSTANCE] == [
        instance.to_dict() for instance in original.instances if instance.key != INSTANCE]
    assert [output.to_dict() for output in _section(after).outputs
            if output.operation["op"] != "create_floor_by_contour"] == [
        output.to_dict() for output in _section(original).outputs
        if output.operation["op"] != "create_floor_by_contour"]
    assert open_questions(reopened) == [], "зазор доказан типом — вопросы закрыты законно"


def test_answer_refuses_an_ambiguous_original_address_before_any_write(tmp_path):
    store, source = _store(tmp_path)
    record_pending_change(store, store.head(), source_output_id=_source_id(source), change=CHANGE_C)
    question = open_questions(store)[0]
    head = store.head()
    # Another authored edit makes the saved REQUEST ambiguous. Looking only at
    # the clipped result would miss this second candidate and silently choose.
    ambiguous = _revise_floors(head, lambda holes, _: [*holes, _thaw(AMBIGUOUS)])
    store.commit(ambiguous, expected_revision=head.revision_id)
    before = ambiguous.dumps()
    with pytest.raises(RefinementError, match="ambiguous_hole_address"):
        answer_question(store, question.question_id, "keep_wall_and_shrink_atrium")
    reopened = ProjectStore.open(store.path)
    assert reopened.head().dumps() == before
    assert len(open_questions(reopened)) == 3


def test_record_refuses_ambiguous_holes_without_storing_a_pending_change(tmp_path):
    store, source = _store(tmp_path)
    head = store.head()
    ambiguous = _revise_floors(head, lambda holes, _: [*holes, _thaw(AMBIGUOUS)])
    store.commit(ambiguous, expected_revision=head.revision_id)
    with pytest.raises(RefinementError, match="ambiguous_hole_address"):
        record_pending_change(store, ambiguous, source_output_id=_source_id(source), change=CHANGE_C)
    assert ProjectStore.open(store.path).head().dumps() == ambiguous.dumps()
    assert open_questions(store) == []


@pytest.mark.parametrize("curved", [False, True], ids=["actual-straight-contact", "curve-unknown"])
def test_answer_rechecks_retained_openings_on_their_own_level(tmp_path, curved):
    store, source = _store(tmp_path, mixed=curved)
    head = store.head()
    instance = _section(head)
    north = [output for output in instance.outputs if output.operation["op"] == "create_wall"
             and all(point[1] == 9000.0 for point in (output.operation["p0_mm"],
                                                     output.operation["p1_mm"]))]
    assert len(north) == 3
    chosen = north[2 if curved else 0]
    # This wall intersects the preserved stair opening on ONE level. The
    # answered atrium can clear it; that does not clear the other opening.
    op = _thaw(chosen.operation)
    op["p0_mm"][1] = op["p1_mm"][1] = 6600.0
    revised = head.replace_instance(replace(instance, outputs=[
        replace(output, operation=op) if output.key == chosen.key else output
        for output in instance.outputs]), expected_revision=head.revision_id)
    store.commit(revised, expected_revision=head.revision_id)
    record_pending_change(store, revised, source_output_id=_source_id(source), change=CHANGE_C)
    questions = open_questions(store)
    assert len(questions) == 3
    address = output_id(head.project_id, INSTANCE, chosen.key)
    question = next(question for question in questions if question.address == address)
    answer_question(store, question.question_id, "keep_wall_and_shrink_atrium")
    reopened = ProjectStore.open(store.path)
    remaining = open_questions(reopened)
    assert [question.question_id for question in remaining] == [question.question_id]
    assert all(len(output.operation["contour"]["holes"]) == 2
               for output in _floors(reopened.head()))
    if curved:
        assert "curved hole/axis intersection is unavailable" in remaining[0].why
    else:
        assert "по-прежнему задевает" in remaining[0].why
