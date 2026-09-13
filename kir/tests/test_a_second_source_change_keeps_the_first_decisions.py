# -*- coding: utf-8 -*-
"""A SECOND and THIRD source change: the decision survives, addresses stay
intact, foreign parts stay in place.

Mission 2's acceptance instrument and commit `e32d556` check EXACTLY ONE
source change. Mandate F3/G03 asks about repeated ones: do agreed decisions
persist, do the 1:N links and part addresses hold, are the deviation and the
residue measured after EACH change.

The scene's numbers are taken from the neighboring file
(`test_a_source_change_names_all_three_sets`); they are not recomputed here
and not derived from the product.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from kir.project import NamedOutput, _thaw, output_id
from kir import project_refinement as _refinement
from kir.project_refinement import (answer_question, apply_source_change, open_questions,
                                    record_pending_change, refine_after_source_change)


def answered_decisions(store, revision=None):
    """The entry point MAY be missing — then the probe turns red by name, rather than breaking collection."""
    entry = getattr(_refinement, "answered_decisions", None)
    assert entry is not None, "нет точки входа kir.project_refinement.answered_decisions"
    return entry(store, revision)
from kir.project_selection import selected_instance_program
from kir.project_store import ProjectStore
from kir.tests.test_a_source_change_names_all_three_sets import (
    CHANGE_A, CHANGE_B, CHANGE_C, HOLE_C, INSTANCE, _scene, _source_id)

ROOT = Path(__file__).resolve().parents[2]

#: A foreign stair shaft — added AFTER detailing, not by the source.
STAIR = {"shape": "poly", "points_mm": [[11000.0, 6000.0], [12000.0, 6000.0],
                                        [12000.0, 7000.0], [11000.0, 7000.0]]}
#: A foreign opening in the first floor's FACADE wall: `wall_rect` is
#: addressed by ABSOLUTE coordinates, so a shifted facade must drag it along.
OPENING_P0 = [3000.0, 0.0, 900.0]
OPENING_P1 = [4500.0, 0.0, 3000.0]
FACADE_2 = {"kind": "facade_curve", "outer_dy_mm": -400.0, "why": "вторая правка фасада"}
FACADE_3 = {"kind": "facade_curve", "outer_dy_mm": 600.0, "why": "третья правка фасада"}


def _section(project):
    return next(instance for instance in project.instances if instance.key == INSTANCE)


def _with_foreign_parts(project):
    """The foreign opening and shaft, added after detailing: not members of the lineage record."""
    instance = _section(project)
    wall_id = output_id(project.project_id, INSTANCE, "storey-01-wall-0")
    outputs = []
    for output in instance.outputs:
        op = _thaw(output.operation)
        if op["op"] == "create_floor_by_contour":
            contour = _thaw(op["contour"])
            contour["holes"] = list(contour.get("holes") or ()) + [_thaw(STAIR)]
            op["contour"] = contour
        outputs.append(replace(output, operation=op))
    outputs.append(NamedOutput(key="foreign-opening-1", operation={
        "op": "create_opening", "variety": "wall_rect",
        "host": {"by": "ref", "value": wall_id},
        "p0_mm": list(OPENING_P0), "p1_mm": list(OPENING_P1), "cut": "vertical"}))
    return project.replace_instance(replace(instance, outputs=tuple(outputs)),
                                    expected_revision=project.revision_id)


def _store(tmp_path, *, foreign=True):
    source, base, detailed = _scene()
    store = ProjectStore.create(tmp_path / "scene.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    if foreign:
        store.commit(_with_foreign_parts(detailed), expected_revision=detailed.revision_id)
    return store, source


def _addresses(project):
    return sorted(output_id(project.project_id, INSTANCE, output.key)
                  for output in _section(project).outputs)


def _wall(project, key):
    return _thaw(next(output for output in _section(project).outputs
                      if output.key == key).operation)


def _holes(project):
    return [_thaw(output.operation["contour"]).get("holes") or ()
            for output in _section(project).outputs
            if output.operation["op"] == "create_floor_by_contour"]


def _atrium_top(project):
    """The upper edge of the first floor's atrium — the number that makes the decision visible."""
    for hole in _holes(project)[0]:
        points = hole.get("points_mm") or []
        if points and min(float(x) for x, _ in points) == HOLE_C[0][0]:
            return max(float(y) for _, y in points)
    raise AssertionError("атриум исчез из пола")


def _answer_everything(store, source, change):
    record_pending_change(store, store.head(), source_output_id=_source_id(source), change=change)
    asked = [question.question_id for question in open_questions(store)]
    assert asked, "правка до стены обязана спросить"
    answered = []
    for question_id in asked:
        if any(question.question_id == question_id for question in open_questions(store)):
            answer_question(store, question_id, "keep_wall_and_shrink_atrium")
            answered.append(question_id)
    assert not open_questions(store), "вопросы остались открытыми — сцена не та"
    return sorted(answered)


# ─── (a) the decision from the first change survives the second ────────────
def test_an_answered_decision_survives_a_second_source_change(tmp_path):
    """🔴 THE HUMAN'S ANSWER DISAPPEARED ALONG WITH THE LAST QUESTION.

    `answer_question` removed `pending_source_change` entirely once the last
    question closed, and the `answered` list left along with it. After that,
    no reader — not the second change, not another process — could name
    which decision the author made, or at which address.
    """
    store, source = _store(tmp_path)
    asked = _answer_everything(store, source, CHANGE_C)
    shrunk = _atrium_top(store.head())
    assert shrunk < HOLE_C[1][1], "решение не обрезало атриум — сцена не та"

    decisions = answered_decisions(store)
    assert [row["question_id"] for row in decisions] == asked
    assert {row["choice"] for row in decisions} == {"keep_wall_and_shrink_atrium"}

    apply_source_change(store, store.head(), source_output_id=_source_id(source), change=CHANGE_B)
    after = answered_decisions(store)
    assert [row["question_id"] for row in after] == asked, "второе изменение сбросило решение"
    assert {row["address"] for row in after} == {row["address"] for row in decisions}
    assert _atrium_top(store.head()) == shrunk, "второе изменение вернуло атриум к стене"


# ─── (b) three changes in a row: addresses stable, the untouched stays preserved ────
def test_three_changes_keep_part_addresses_and_count_the_untouched_as_preserved(tmp_path):
    """🔴 `preserved` WAS CALLING SOMETHING "PRESERVED" THAT HAD TORN AWAY
    FROM ITS HOST.

    Three consecutive facade edits moved the wall by −800, −400, +600; the
    foreign opening `wall_rect` stayed at its old mark and landed in
    `preserved` three times over. The output address indeed did not change —
    and that is exactly why address stability alone proves nothing.
    """
    store, source = _store(tmp_path)
    start = _addresses(store.head())
    opening_id = output_id(store.head().project_id, INSTANCE, "foreign-opening-1")
    seen = []
    for change in (CHANGE_B, FACADE_2, FACADE_3):
        report = refine_after_source_change(store, store.head(),
                                            source_output_id=_source_id(source), change=change)
        program = selected_instance_program(store.head(), INSTANCE)
        assert (len(report.recomputed) + len(report.preserved)
                + len(report.needs_decision)) == len(program["ops"])
        seen.append((len(report.recomputed), len(report.preserved), opening_id in report.preserved))
        apply_source_change(store, store.head(), source_output_id=_source_id(source), change=change)
        assert _addresses(store.head()) == start

    wall = _wall(store.head(), "storey-01-wall-0")
    opening = _thaw(next(output for output in _section(store.head()).outputs
                         if output.key == "foreign-opening-1").operation)
    assert float(wall["p0_mm"][1]) == pytest.approx(-600.0)
    # The opening must travel with its host, not be counted as "preserved" in place.
    assert float(opening["p0_mm"][1]) == pytest.approx(float(wall["p0_mm"][1])), seen
    assert float(opening["p1_mm"][1]) == pytest.approx(float(wall["p1_mm"][1])), seen
    assert [row[2] for row in seen] == [False, False, False], (
        "оторванный от носителя проём назван сохранённым")


# ─── (c) foreign openings and details do not disappear after the second change ────
def test_foreign_openings_and_details_survive_a_second_change(tmp_path):
    """The foreign shaft and the foreign opening after the decision and after the SECOND change."""
    store, source = _store(tmp_path)
    _answer_everything(store, source, CHANGE_C)
    assert all(len(holes) == 2 for holes in _holes(store.head()))

    apply_source_change(store, store.head(), source_output_id=_source_id(source), change=CHANGE_B)
    holes = _holes(store.head())
    assert [len(row) for row in holes] == [2, 2, 2], "чужая шахта исчезла"
    assert any(_thaw(hole) == _thaw(STAIR) for hole in holes[0]), "шахта поехала чужой правкой"

    section = _section(store.head())
    opening = next((output for output in section.outputs
                    if output.key == "foreign-opening-1"), None)
    assert opening is not None, "чужой проём исчез"
    wall = _wall(store.head(), "storey-01-wall-0")
    assert float(_thaw(opening.operation)["p0_mm"][1]) == pytest.approx(float(wall["p0_mm"][1])), \
        "чужой проём остался висеть там, где носителя больше нет"


# ─── (d) save -> close -> open BY ANOTHER process -> change 3 ──────────────
def test_a_reopened_store_applies_a_third_change_with_the_decisions_intact(tmp_path):
    store, source = _store(tmp_path)
    asked = _answer_everything(store, source, CHANGE_C)
    apply_source_change(store, store.head(), source_output_id=_source_id(source), change=CHANGE_B)
    saved = store.head().revision_id
    shrunk = _atrium_top(store.head())
    del store

    child = subprocess.run(
        [sys.executable, "-c", """
import json, sys
from kir.project_store import ProjectStore
from kir.project_refinement import (answered_decisions, apply_source_change, open_questions)
store = ProjectStore.open(sys.argv[1], readonly=False)
before = store.head().revision_id
rows = [dict(row) for row in answered_decisions(store)]
after = apply_source_change(store, store.head(), source_output_id=sys.argv[2],
                            change=json.loads(sys.argv[3]))
print(json.dumps({"before": before, "after": after,
                  "decisions": rows,
                  "decisions_after": [dict(r) for r in answered_decisions(store)],
                  "questions": [q.to_dict() for q in open_questions(store)]},
                 ensure_ascii=False))
""", str(tmp_path / "scene.sqlite"), _source_id(source), json.dumps(FACADE_2)],
        capture_output=True, text=True, timeout=300,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr[-800:]
    payload = json.loads(child.stdout)
    assert payload["before"] == saved
    assert payload["after"] != saved, "третье изменение не доехало до хранилища"
    assert [row["question_id"] for row in payload["decisions"]] == asked
    assert payload["decisions_after"] == payload["decisions"], \
        "третье изменение переписало решения"

    reopened = ProjectStore.open(tmp_path / "scene.sqlite")
    assert reopened.head().revision_id == payload["after"]
    assert _atrium_top(reopened.head()) == shrunk


# ─── (e) deviation and residue are measured after EACH change ──────────────
def test_deviation_and_residue_are_measured_after_every_change(tmp_path):
    """🔴 THE DECISION'S CONCESSION WAS NOT LANDING IN THE RESIDUE.

    `keep_wall_and_shrink_atrium` hands the author NOT WHAT they asked for:
    the atrium is trimmed to `8885` instead of the requested `9500`. The
    difference is untranslated, and `residue` must carry it with an address
    and a number — otherwise, after the second and third change, the residue
    stays the same old constant while the discrepancy grows silently.
    """
    store, source = _store(tmp_path)
    base_report = refine_after_source_change(store, store.head(),
                                             source_output_id=_source_id(source), change=CHANGE_B)
    base_residue = len(base_report.residue)
    assert base_residue > 0 and base_report.deviation["measure"] == "plan_area_delta_mm2"

    _answer_everything(store, source, CHANGE_C)
    gap = HOLE_C[1][1] - _atrium_top(store.head())
    assert gap > 0.0

    measured = []
    for change in (CHANGE_B, FACADE_2, CHANGE_A):
        report = refine_after_source_change(store, store.head(),
                                            source_output_id=_source_id(source), change=change)
        assert report.deviation["measure"] == "plan_area_delta_mm2", report.analysis_limits
        assert report.deviation["value"], report.analysis_limits
        conceded = [row for row in report.residue if str(row.get("what", "")).startswith("decision:")]
        assert conceded, "остаток молчит об уступке решения"
        assert all(row["address"] for row in conceded)
        assert any(float(row.get("mm", 0.0)) == pytest.approx(gap) for row in conceded), \
            [dict(row) for row in report.residue]
        assert len(report.residue) > base_residue
        measured.append(len(report.residue))
        apply_source_change(store, store.head(),
                            source_output_id=_source_id(source), change=change)
    assert measured == [measured[0]] * 3, "остаток растёт от одного и того же решения"


# ─── the limit is named when a part CANNOT travel with its host ────────────
def test_a_part_that_cannot_follow_its_host_is_named_not_silently_preserved(tmp_path):
    """🔴 A SKIP BY THE OP'S NAME WAS DECLARING SOMEONE MOVED WHO HAD NOT
    BEEN TOUCHED.

    A `create_opening` of kind `host_face` carries `outline`, not
    `p0_mm`/`p1_mm`: a facade edit does not move it. The limit's first draft
    skipped it by the op's NAME, and the part stayed in place silently. What
    is checked is the number in `analysis_limits`, not the presence of a
    line.
    """
    store, source = _store(tmp_path, foreign=False)
    project = store.head()
    instance = _section(project)
    facade = output_id(project.project_id, INSTANCE, "storey-01-wall-0")
    corner = output_id(project.project_id, INSTANCE, "storey-01-wall-1")
    extra = (
        NamedOutput(key="foreign-hostface-1", operation={
            "op": "create_opening", "variety": "host_face",
            "host": {"by": "ref", "value": facade},
            "outline": [[3000.0, 0.0, 900.0], [4000.0, 0.0, 900.0],
                        [4000.0, 0.0, 2100.0], [3000.0, 0.0, 2100.0]], "cut": "vertical"}),
        NamedOutput(key="foreign-opening-side", operation={
            "op": "create_opening", "variety": "wall_rect",
            "host": {"by": "ref", "value": corner},
            "p0_mm": [14000.0, 3000.0, 900.0], "p1_mm": [14000.0, 4500.0, 3000.0],
            "cut": "vertical"}),
        NamedOutput(key="foreign-opening-facade", operation={
            "op": "create_opening", "variety": "wall_rect",
            "host": {"by": "ref", "value": facade},
            "p0_mm": list(OPENING_P0), "p1_mm": list(OPENING_P1), "cut": "vertical"}))
    store.commit(project.replace_instance(replace(instance, outputs=tuple(instance.outputs) + extra),
                                          expected_revision=project.revision_id),
                 expected_revision=project.revision_id)
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_B)
    named = [row for row in report.analysis_limits
             if str(row).startswith("hosted parts do not follow their host")]
    assert len(named) == 1, report.analysis_limits
    # Exactly two: `host_face` on the shifted facade and `wall_rect` on the
    # corner wall, where only one end moves. The third is the one that moved
    # along with the facade.
    assert named[0].startswith("hosted parts do not follow their host: 2"), named
    for key in ("foreign-hostface-1", "foreign-opening-side"):
        assert output_id(project.project_id, INSTANCE, key)[:12] in named[0], (key, named)
    assert output_id(project.project_id, INSTANCE, "foreign-opening-facade")[:12] not in named[0]
