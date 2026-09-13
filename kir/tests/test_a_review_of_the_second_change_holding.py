# -*- coding: utf-8 -*-
"""The self-review put on "repeated changes to the source" — via three
third-party questions.

The three questions are posed AS THIRD-PARTY: ownership of a part's
position, the fate of a decision, whose question is rendered moot by a
subsequent change, and how a decision behaves when merging two submissions
from the same base.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from kir.project import NamedOutput, _thaw, output_id
from kir import project_refinement as _refinement
from kir.project_refinement import (answer_question, apply_source_change, open_questions,
                                    record_pending_change, refine_after_source_change)
from kir.project_store import ProjectStore
from kir.tests.test_a_source_change_names_all_three_sets import (
    CHANGE_B, CHANGE_C, INSTANCE, _scene, _source_id)
from kir.tests.test_a_second_source_change_keeps_the_first_decisions import (
    OPENING_P0, OPENING_P1, _atrium_top, _section, _store, answered_decisions)

MOVED_DY = 350.0


def _facade_wall_id(project):
    return output_id(project.project_id, INSTANCE, "storey-01-wall-0")


def _with_opening(store):
    project = store.head()
    instance = _section(project)
    opening = NamedOutput(key="foreign-opening-1", operation={
        "op": "create_opening", "variety": "wall_rect",
        "host": {"by": "ref", "value": _facade_wall_id(project)},
        "p0_mm": list(OPENING_P0), "p1_mm": list(OPENING_P1), "cut": "vertical"})
    store.commit(project.replace_instance(
        replace(instance, outputs=tuple(instance.outputs) + (opening,)),
        expected_revision=project.revision_id), expected_revision=project.revision_id)
    return store


def _opening(project):
    return _thaw(next(output for output in _section(project).outputs
                      if output.key == "foreign-opening-1").operation)


def _wall(project, key="storey-01-wall-0"):
    return _thaw(next(output for output in _section(project).outputs
                      if output.key == key).operation)


# ─── 1. Ownership of an opening's position ─────────────────────────────────
def test_an_explicitly_moved_opening_is_not_silently_overwritten(tmp_path):
    """The author EXPLICITLY moved the opening after detailing; then the
    facade shifted.

    There is no silent third option: either the opening moves ALONG THE SAME
    VECTOR from its NEW position, or its address sits in `needs_decision`.
    Silently returning the opening to the "correct" place would mean erasing
    the human's decision.
    """
    store, source = _store(tmp_path, foreign=False)
    _with_opening(store)
    project = store.head()
    instance = _section(project)
    outputs = []
    for output in instance.outputs:
        op = _thaw(output.operation)
        if output.key == "foreign-opening-1":
            # The human moved the opening ALONG the wall and 350 mm outward from it.
            op["p0_mm"] = [op["p0_mm"][0] + 1200.0, op["p0_mm"][1] - MOVED_DY, op["p0_mm"][2]]
            op["p1_mm"] = [op["p1_mm"][0] + 1200.0, op["p1_mm"][1] - MOVED_DY, op["p1_mm"][2]]
        outputs.append(replace(output, operation=op))
    store.commit(project.replace_instance(replace(instance, outputs=tuple(outputs)),
                                          expected_revision=project.revision_id),
                 expected_revision=project.revision_id)
    moved = _opening(store.head())
    opening_id = output_id(project.project_id, INSTANCE, "foreign-opening-1")

    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_B)
    if opening_id in report.needs_decision:
        return  # the second declared outcome: the author was asked — also not silently
    apply_source_change(store, store.head(), source_output_id=_source_id(source), change=CHANGE_B)
    after = _opening(store.head())
    dy = float(CHANGE_B["outer_dy_mm"])
    assert float(after["p0_mm"][0]) == pytest.approx(float(moved["p0_mm"][0])), \
        "правка фасада тронула положение ВДОЛЬ стены, которого не касалась"
    assert float(after["p0_mm"][1]) == pytest.approx(float(moved["p0_mm"][1]) + dy), \
        "явная правка человека затёрта: проём поехал не от своего нового положения"
    assert float(after["p1_mm"][1]) == pytest.approx(float(moved["p1_mm"][1]) + dy)
    # And the link to the host is not made up: the gap the human set is PRESERVED.
    wall = _wall(store.head())
    assert float(wall["p0_mm"][1]) - float(after["p0_mm"][1]) == pytest.approx(MOVED_DY)


# ─── 2. A decision whose question is rendered moot by a later change ───────
def test_a_decision_whose_wall_is_gone_is_rechecked_or_asked_again(tmp_path):
    """The wall the question was about is DELETED after the answer.

    A decision must not go on being silently counted as applied to someone
    else's geometry: either its address returns to `needs_decision`, or the
    limit names the stale decision by number.
    """
    store, source = _store(tmp_path, foreign=False)
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    questions = open_questions(store)
    assert questions
    answer_question(store, questions[0].question_id, "keep_wall_and_shrink_atrium")
    assert not open_questions(store)
    decided = answered_decisions(store)
    assert len(decided) == 1
    address = decided[0]["address"]
    shrunk = _atrium_top(store.head())

    project = store.head()
    instance = _section(project)
    victim = next(output for output in instance.outputs
                  if output_id(project.project_id, INSTANCE, output.key) == address)
    store.commit(project.replace_instance(
        replace(instance, outputs=tuple(output for output in instance.outputs
                                        if output.key != victim.key)),
        expected_revision=project.revision_id), expected_revision=project.revision_id)
    assert _atrium_top(store.head()) == shrunk

    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_B)
    stale = [row for row in report.analysis_limits if "decision" in str(row)]
    assert address in report.needs_decision or stale, (
        "решение продолжает числиться применённым к стене, которой больше нет: "
        f"{report.analysis_limits}")
    if stale:
        assert address[:12] in "".join(str(row) for row in stale), stale


# ─── 3. A decision and the merge of two submissions from the same base ─────
def _proposal(base, candidate, keys):
    from kir.project_merge import ChangeProposal, ProposalScope
    return ChangeProposal(base, candidate, ProposalScope(instances=tuple(keys)),
                          "review", "review probe")


def _scope(keys):
    from kir.project_merge import ProposalScope
    return ProposalScope(instances=tuple(keys))


def _control_merge(path):
    """Control: the same scene, a DIVERGENCE exists, and there is no decision
    at all.

    🔴 WITHOUT THIS CONTROL BOTH MERGE PROBES LIE IN DIFFERENT DIRECTIONS.
    Measurement from 07.09: the typed section carries `element_id`
    selectors, and ANY diverging edit gives `dependency_analysis_incomplete`
    before it even reaches the passport. Then "the decision got lost" is not
    about the decision, and "a conflict was caught" is not about the second
    answer. Here the section is edited NEUTRALLY (a note in the passport)
    and through the same `accept_proposal` as the answer to the question —
    the divergence is the same in kind.
    """
    from kir.project_merge import ProposalScope, accept_proposal, merge_proposal

    path.mkdir()
    store, _source = _store(path, foreign=False)
    base = store.head()
    section = _section(base)
    diverged = base.replace_instance(
        replace(section, metadata={**_thaw(section.metadata), "review_note": "a"}),
        expected_revision=base.revision_id)
    accept_proposal(store, _proposal(base, diverged, (INSTANCE,)),
                    expected_revision=base.revision_id,
                    authorized_scope=ProposalScope(instances=(INSTANCE,)))
    other = next(instance for instance in base.instances if instance.key != INSTANCE)
    side = base.replace_instance(
        replace(other, metadata={**_thaw(other.metadata or {}), "review_note": "b"}),
        expected_revision=base.revision_id)
    return merge_proposal(_proposal(base, side, (other.key,)), store.head(),
                          authorized_scope=_scope((other.key,)))


def test_a_decision_survives_a_merge_with_a_neighbouring_instance(tmp_path):
    """A answered the question, B edits a NEIGHBORING instance from the same
    base.

    Both submissions are merged; the author's decision must remain in the
    result.
    """
    from kir.project_merge import merge_proposal

    store, source = _store(tmp_path, foreign=False)
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    base = store.head()
    questions = open_questions(store)
    answer_question(store, questions[0].question_id, "keep_wall_and_shrink_atrium")
    decided = answered_decisions(store)
    assert len(decided) == 1
    current = store.head()          # side A is already in the store

    other = next(instance for instance in base.instances if instance.key != INSTANCE)
    b_side = base.replace_instance(
        replace(other, metadata={**_thaw(other.metadata or {}), "review_note": "b"}),
        expected_revision=base.revision_id)
    # 🔴 CONTROL BEFORE BLAME. This probe's red could come not from the
    # decision but from the scene itself: the typed section carries
    # `element_id` selectors, and the merge refuses with
    # `selector_requires_grounding` before it even reaches the passport. The
    # control merges the SAME neighbor edit with a revision that has no
    # decision at all; if it is also red, the subject lies elsewhere.
    control = _control_merge(tmp_path / "control")
    if not control.clean:
        pytest.skip("предмет чужой: слияние отказывает и БЕЗ решения — "
                    f"{[row.get('kind') or row for row in control.to_dict()['conflicts']]}")

    merged = merge_proposal(_proposal(base, b_side, (other.key,)), current,
                            authorized_scope=_scope((other.key,)))
    assert merged.clean, merged.to_dict()["conflicts"]
    section = next(instance for instance in merged.revision.instances
                   if instance.key == INSTANCE)
    stored = _thaw(section.metadata.get("refinement_decisions"))
    assert stored, "слияние с соседом потеряло решение автора"
    assert [row["question_id"] for row in stored] == [decided[0]["question_id"]]
    assert _thaw(next(instance for instance in merged.revision.instances
                      if instance.key == other.key).metadata)["review_note"] == "b"


def test_two_different_answers_to_one_question_are_a_conflict(tmp_path):
    """One question, two DIFFERENT answers — a conflict, not "last one wins"."""
    from kir.project_merge import merge_proposal

    store, source = _store(tmp_path, foreign=False)
    record_pending_change(store, store.head(), source_output_id=_source_id(source),
                          change=CHANGE_C)
    base = store.head()
    questions = open_questions(store)
    answer_question(store, questions[0].question_id, "keep_wall_and_shrink_atrium")
    current = store.head()
    rows = [dict(row) for row in _thaw(_section(current).metadata["refinement_decisions"])]
    assert rows

    conflicting = [{**rows[0], "choice": "move_wall_to_new_atrium_edge",
                    "applied_mm": rows[0]["requested_mm"], "conceded_mm": 0.0}]
    b_side = base.replace_instance(
        replace(_section(base), metadata={**_thaw(_section(base).metadata),
                                          "refinement_decisions": conflicting}),
        expected_revision=base.revision_id)
    # 🔴 A GREEN "CONFLICT" MEANS NOTHING UNTIL IT IS SHOWN THAT THIS SAME
    # SCENE CAN MERGE CLEANLY. Otherwise the probe is not catching the
    # second answer, but the scene's inability to merge at all.
    control = _control_merge(tmp_path / "control")
    if not control.clean:
        pytest.skip("предмет чужой: сцена не сливается даже нейтральной правкой — "
                    f"{[row.get('kind') or row for row in control.to_dict()['conflicts']]}")

    merged = merge_proposal(_proposal(base, b_side, (INSTANCE,)), current,
                            authorized_scope=_scope((INSTANCE,)))
    assert not merged.clean, (
        "второй ответ на ТОТ ЖЕ вопрос принят молча: "
        f"{merged.to_dict()['status']}")
