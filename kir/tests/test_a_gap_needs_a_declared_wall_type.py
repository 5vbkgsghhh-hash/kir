# -*- coding: utf-8 -*-
"""The gap between the atrium and the wall cannot be proven without a
DECLARED wall type.

R2 of the end-to-end instrument (`docs/FINAL_RESULT_RU.md`): on the saved
ЖК RIGHT AFTER detailing, section types are not yet declared,
`_wall_half_width` returns `None`, `_shrunk_atrium` trims the atrium
EXACTLY to the axis, `_still_open` counts a touch as an intersection.
Measurement: 3 asked, 3 answered, 3 open — forever, and
`apply_source_change` then fails with `decision_required`.

The decision, by meaning: the half-width is a number that DECLARES the
wall type. It cannot be invented on the author's behalf (that would be
made-up geometry), so the answer that needs it FAILS BY NAME and names the
action. The action closes the question — no infinite question remains.
"""
from __future__ import annotations

import pytest

from kir.project import _thaw, output_id
from kir.project_refinement import (RefinementError, answer_question, answered_decisions,
                                    apply_source_change, open_questions,
                                    record_pending_change, refine_after_source_change)
from kir.project_selection import selected_instance_program
from kir.project_store import ProjectStore
from kir.tests.fixtures import GROUND_SNAPSHOT as G
from kir.tests.test_a_source_change_names_all_three_sets import (
    CHANGE_B, CHANGE_C, INSTANCE, _scene, _source_id, _сцена)

CODE = "wall_type_required_for_gap"


def _untyped(tmp_path):
    """ЖК RIGHT AFTER detailing: section types are not yet declared."""
    source, base, _detailed = _scene()
    store = ProjectStore.create(tmp_path / "untyped.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    program = selected_instance_program(store.head(), INSTANCE)
    assert not [op for op in program["ops"] if op["op"] == "create_wall_type"], "сцена не та"
    return store, source


def _declare_types(store, source):
    """The author's ACTION: declare the wall and floor layers (the half-width will become 115)."""
    _towers, _workflow, typed = _сцена()
    head = store.head()
    typed_revision = typed.add_section_types(
        head, source=source, expected_revision=head.revision_id,
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
    store.commit(typed_revision, expected_revision=head.revision_id)
    return store.head()


# ─── 1. a named refusal instead of an infinite question ──────────────────────
def test_an_undeclared_wall_type_refuses_the_gap_by_name(tmp_path):
    """🔴 THE ANSWER WAS BEING RECORDED, THE QUESTION WAS NOT CLOSED, THE WRONG CAUSE WAS BEING NAMED."""
    store, source = _untyped(tmp_path)
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    asked = [question.question_id for question in open_questions(store)]
    assert len(asked) == 3
    address = {question.question_id: question.address for question in open_questions(store)}

    for question_id in asked:
        with pytest.raises(RefinementError) as caught:
            answer_question(store, question_id, "keep_wall_and_shrink_atrium")
        assert caught.value.code == CODE, caught.value
        assert address[question_id][:12] in str(caught.value), caught.value
        assert "create_wall_type" in str(caught.value), "действие не названо"

    assert answered_decisions(store) == (), "отказ всё же записал решение"
    assert len(open_questions(store)) == 3, "отказ снял вопрос, которого не решил"


# ─── 2. the named action CLOSES the question ─────────────────────────────────
def test_declaring_the_wall_type_closes_the_same_question(tmp_path):
    """Declare the type -> the same answer goes through, the question closes, the edit proceeds."""
    store, source = _untyped(tmp_path)
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    asked = [question.question_id for question in open_questions(store)]
    with pytest.raises(RefinementError):
        answer_question(store, asked[0], "keep_wall_and_shrink_atrium")

    _declare_types(store, source)
    still = [question.question_id for question in open_questions(store)]
    assert still == sorted(asked), "объявление типа потеряло заведённые вопросы"

    for question_id in still:
        if any(item.question_id == question_id for item in open_questions(store)):
            answer_question(store, question_id, "keep_wall_and_shrink_atrium")
    assert len(open_questions(store)) == 0, "вопрос остался открытым и с объявленным типом"
    assert len(answered_decisions(store)) >= 1
    # The source edit is possible again: `decision_required` no longer holds.
    apply_source_change(store, store.head(), source_output_id=_source_id(source),
                        change=CHANGE_B)


# ─── 3. the report names the limit, and the question names the action ───────
def test_the_report_and_the_question_name_the_missing_wall_type(tmp_path):
    store, source = _untyped(tmp_path)
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_C)
    assert len(report.needs_decision) == 3
    named = [row for row in report.analysis_limits if CODE in str(row)]
    assert named, report.analysis_limits
    for address in report.needs_decision:
        assert address[:12] in "".join(str(row) for row in named), (address, named)
    for question in report.questions:
        assert CODE in question.why, question.why

    source2, _base2, detailed = _scene()
    typed_report = refine_after_source_change(None, detailed,
                                              source_output_id=_source_id(source2),
                                              change=CHANGE_C)
    assert not [row for row in typed_report.analysis_limits if CODE in str(row)], \
        "предел назван там, где тип ОБЪЯВЛЕН"
    for question in typed_report.questions:
        assert CODE not in question.why
