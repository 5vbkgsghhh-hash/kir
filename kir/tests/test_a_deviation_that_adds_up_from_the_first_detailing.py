# -*- coding: utf-8 -*-
"""Deviation from R0, self-intersection with an address, and a SECOND facade edge.

Three subjects of one F3/G03 turn:

* **A** — the report carries the STEP and the SUM FROM R0 (the first
  detailing). The sum is MEASURED as the difference from the recorded
  base, not added up from steps: a manual edit made between changes must
  land in the sum and must not land in the addition.
* **B** — a self-intersecting contour stops eating the whole measure: the
  area is honest via `buffer(0)`, and the intersection site is named by an
  address. An unreadable contour still FAILS (otherwise the fix would turn
  failures into zeros).
* **C** — the facade side is declared (`min_y` / `max_y`); the other side
  and an undeclared edit key are named refusals, not a silent
  reinterpretation.

The numbers are taken from the scene's geometry, not from the product: the
outer contour is 14000×9000 for the two floors and 12200×9000 for the top
one; the atrium is 2000×2000; the `−800` edit grows the plan by
800×width.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from kir.project import _thaw, output_id
from kir.project_refinement import (RefinementError, _changed_ops, _free_ends,
                                    apply_source_change, refine_after_source_change)
from kir.project_selection import selected_instance_program
from kir.project_store import ProjectStore
from kir.refine.deviation import plan_area_delta
from kir.tests.test_a_source_change_names_all_three_sets import (
    CHANGE_A, CHANGE_B, HOLE_C, INSTANCE, _scene, _source_id)

FACADE_2 = {"kind": "facade_curve", "outer_dy_mm": -400.0, "why": "вторая правка фасада"}
CHANGE_C = {"kind": "atrium_contour", "hole_mm": HOLE_C, "why": "атриум доведён до стены"}
NORTH = {"kind": "facade_curve", "outer_dy_mm": 600.0, "side": "max_y",
         "why": "вторая кромка"}
#: Someone else's shaft, 1000×1000: a manual edit MADE BETWEEN source changes.
STAIR = {"shape": "poly", "points_mm": [[11000.0, 6000.0], [12000.0, 6000.0],
                                        [12000.0, 7000.0], [11000.0, 7000.0]]}
STAIR_AREA = 1_000_000.0
#: The sum of steps B(−800) and A(atrium 2000→3000) across floors, computed from the geometry.
STEPS_SUM = [6_200_000.0, 6_200_000.0, 4_760_000.0]
#: Honest area with a hole brought to the edge: 3000×6500 instead of 2000×2000.
SELF_TOUCH_DELTA = [-15_500_000.0] * 3
#: Second edge at +600: 14000×600 for the two floors, 12200×600 for the top one.
NORTH_DELTA = [8_400_000.0, 8_400_000.0, 7_320_000.0]


def _section(project):
    return next(instance for instance in project.instances if instance.key == INSTANCE)


def _store(tmp_path):
    source, base, detailed = _scene()
    store = ProjectStore.create(tmp_path / "scene.sqlite", source)
    store.commit(base, expected_revision=source.revision_id)
    store.commit(detailed, expected_revision=base.revision_id)
    return store, source


def _ops(project):
    return [_thaw(op) for op in selected_instance_program(project, INSTANCE)["ops"]]


def _add_stair(store):
    """A manual edit MADE BETWEEN source changes: someone else's shaft in all floors."""
    project = store.head()
    instance = _section(project)
    outputs = []
    for output in instance.outputs:
        op = _thaw(output.operation)
        if op["op"] == "create_floor_by_contour":
            contour = _thaw(op["contour"])
            contour["holes"] = list(contour.get("holes") or ()) + [_thaw(STAIR)]
            op["contour"] = contour
        outputs.append(replace(output, operation=op))
    store.commit(project.replace_instance(replace(instance, outputs=tuple(outputs)),
                                          expected_revision=project.revision_id),
                 expected_revision=project.revision_id)


def _total(report):
    total = report.deviation.get("total")
    assert isinstance(total, dict), f"отчёт не несёт сумму от R0: {sorted(report.deviation)}"
    return total


# ─── A1. step AND sum from R0, with the source address ──────────────────────
def test_the_report_carries_both_the_step_and_the_total_from_the_first_detailing(tmp_path):
    store, source = _store(tmp_path)
    steps = []
    report = None
    for change in (CHANGE_B, FACADE_2, CHANGE_A):
        report = refine_after_source_change(store, store.head(),
                                            source_output_id=_source_id(source), change=change)
        steps.append(sorted(report.deviation["value"]))
        apply_source_change(store, store.head(), source_output_id=_source_id(source),
                            change=change)
    total = _total(report)
    assert total["measure"] == "plan_area_delta_mm2" and total["unit"] == "mm2"
    assert total["source_output_id"] == _source_id(source), "сумма без адреса источника"
    expected = [sum(values) for values in zip(*[sorted(step) for step in steps])]
    assert sorted(total["value"]) == pytest.approx(sorted(expected), rel=1e-9)
    assert sorted(total["by_level"].values()) == pytest.approx(sorted(expected), rel=1e-9)


# ─── A2. the sum is MEASURED, not added up from steps ───────────────────────
def test_the_total_is_measured_from_the_baseline_not_summed_from_the_steps(tmp_path):
    """🔴 AN ADDED-UP SUM IS BLIND TO WHAT HAPPENED BETWEEN STEPS."""
    store, source = _store(tmp_path)
    first = refine_after_source_change(store, store.head(),
                                       source_output_id=_source_id(source), change=CHANGE_B)
    apply_source_change(store, store.head(), source_output_id=_source_id(source),
                        change=CHANGE_B)
    _add_stair(store)                       # manual edit: −1 000 000 mm² per floor
    second = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_A)
    steps = [sum(values) for values in zip(*[sorted(first.deviation["value"]),
                                             sorted(second.deviation["value"])])]
    assert sorted(steps) == pytest.approx(sorted(STEPS_SUM), rel=1e-9)
    total = _total(second)
    measured = sorted(total["value"])
    assert measured == pytest.approx(sorted(value - STAIR_AREA for value in STEPS_SUM), rel=1e-9)
    assert measured != pytest.approx(sorted(STEPS_SUM), rel=1e-9), \
        "сумма сложена из шагов: ручная правка между ними не видна"


# ─── A3. the number of ops and the volume — with a named limit instead of zero ───
def test_the_total_carries_the_op_count_and_the_volume_or_names_the_refusal(tmp_path):
    store, source = _store(tmp_path)
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_B)
    apply_source_change(store, store.head(), source_output_id=_source_id(source),
                        change=CHANGE_B)
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_A)
    total = _total(report)
    ops = total["op_count"]
    assert ops["baseline"] == 23 and ops["now"] == 23 and ops["delta"] == 0

    assert "volume_mm3" in total, "объём не назван вовсе"
    if total["volume_mm3"] is None:
        assert any("volume" in str(row) for row in
                   list(total.get("limits") or ()) + list(report.analysis_limits)), \
            "объём отсутствует БЕЗ названной причины — это ноль, выданный за меру"
    else:
        assert isinstance(total["volume_mm3"], float)
        assert total["baseline_volume_mm3"] is not None


# ─── B1. self-intersection: the number + the intersection address ───────────
def test_a_self_touching_contour_is_measured_and_its_intersection_addressed(tmp_path):
    store, source = _store(tmp_path)
    before = _ops(store.head())
    after = _changed_ops(before, CHANGE_C)
    delta, problems = plan_area_delta(before, after)
    assert len(delta) == 3, f"мера съедена целиком: {problems}"
    assert sorted(delta.values()) == pytest.approx(sorted(SELF_TOUCH_DELTA), rel=1e-9)
    marked = [row for row in problems if row.get("note") == "self_intersecting"
              or "self_intersecting" in str(row)]
    assert marked, problems
    points = [row.get("at_mm") for row in marked if row.get("at_mm")]
    assert points, f"место пересечения не адресовано: {marked}"
    assert any(float(point[0]) == pytest.approx(7500.0)
               and float(point[1]) == pytest.approx(9000.0) for point in points), points


# ─── B2. the report stops emitting `measure: None` on this edit ─────────────
def test_the_report_measures_the_change_that_touches_the_wall(tmp_path):
    store, source = _store(tmp_path)
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=CHANGE_C)
    assert report.deviation["measure"] == "plan_area_delta_mm2", report.analysis_limits
    assert sorted(report.deviation["value"]) == pytest.approx(sorted(SELF_TOUCH_DELTA), rel=1e-9)
    assert any("self_intersecting" in str(row) for row in report.analysis_limits), \
        report.analysis_limits


# ─── B3. control: an unreadable contour still FAILS ──────────────────────────
def test_an_unreadable_contour_still_refuses_with_its_address(tmp_path):
    store, _source = _store(tmp_path)
    before = _ops(store.head())
    broken = []
    victim = None
    for op in before:
        if op["op"] == "create_floor_by_contour" and victim is None:
            victim = op
            op = {**_thaw(op)}
            contour = _thaw(op["contour"])
            contour["outer"] = {**contour["outer"], "points_mm": [[0.0, 0.0], [1.0, 1.0]]}
            op["contour"] = contour
        broken.append(op)
    delta, problems = plan_area_delta(before, broken)
    # 🔴 EXACTLY THIS CONTOUR, NOT JUST ANY RED LINE. The first draft of the
    # probe simply searched for the `plan_contour_unusable` code — and was
    # blind: `plan_area_delta` sets the same line, "the floor exists on
    # only one side of the comparison," so substituting the failure with a
    # different label did NOT turn the mutation red. What is asked is the
    # parse itself.
    unreadable = [row for row in problems if row.get("code") == "plan_contour_unusable"
                  and "не читается" in str(row.get("detail"))]
    assert unreadable, problems
    assert all(row.get("diag") == "KIR-R015" for row in unreadable)
    assert all(row.get("address") for row in unreadable), unreadable
    assert not [row for row in problems if row.get("note") == "self_intersecting"], \
        "нечитаемый контур выдан за самопересечение"
    assert len(delta) == 2, "отказ превращён в ноль"


# ─── C1. the wrong facade side — a named refusal ─────────────────────────────
def test_an_unsupported_facade_side_is_refused_by_name(tmp_path):
    store, source = _store(tmp_path)
    with pytest.raises(RefinementError) as caught:
        refine_after_source_change(store, store.head(), source_output_id=_source_id(source),
                                   change={"kind": "facade_curve", "outer_dy_mm": -800.0,
                                           "side": "north", "why": "другая сторона"})
    assert caught.value.code == "facade_side_unsupported", caught.value
    assert "north" in str(caught.value), caught.value
    assert "min_y" in str(caught.value) and "max_y" in str(caught.value), \
        "объявленные стороны не названы"


# ─── C2. an undeclared edit key — a named refusal ────────────────────────────
def test_an_undeclared_change_key_is_refused_by_name(tmp_path):
    store, source = _store(tmp_path)
    with pytest.raises(RefinementError) as caught:
        refine_after_source_change(store, store.head(), source_output_id=_source_id(source),
                                   change={"kind": "facade_curve", "outer_dy_mm": -800.0,
                                           "outer_dx_mm": 100.0, "why": "боком"})
    assert caught.value.code == "unsupported_change_key", caught.value
    assert "outer_dx_mm" in str(caught.value), caught.value
    with pytest.raises(RefinementError) as caught:
        refine_after_source_change(store, store.head(), source_output_id=_source_id(source),
                                   change={"kind": "atrium_contour", "hole_mm": HOLE_C,
                                           "side": "max_y", "why": "у атриума стороны нет"})
    assert caught.value.code == "unsupported_change_key", caught.value


# ─── C3. the second edge is EXPRESSED ────────────────────────────────────────
def test_the_far_facade_edge_moves_its_own_walls_and_slab(tmp_path):
    store, source = _store(tmp_path)
    before = _ops(store.head())
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=_source_id(source), change=NORTH)
    assert sorted(report.deviation["value"]) == pytest.approx(sorted(NORTH_DELTA), rel=1e-9)
    assert report.needs_decision == (), report.questions
    after = _changed_ops(before, NORTH)
    assert len(_free_ends(before)) == 0 and len(_free_ends(after)) == 0, \
        "правка второй кромки разорвала контур"
    moved = {round(float(point[1]), 6)
             for op in after if op["op"] == "create_wall"
             for point in (op["p0_mm"], op["p1_mm"])}
    assert 9600.0 in moved and 9000.0 not in moved, sorted(moved)
    assert {round(float(point[1]), 6) for op in after
            if op["op"] == "create_floor_by_contour"
            for point in op["contour"]["outer"]["points_mm"]} == {0.0, 9600.0}
    # The near edge is untouched: editing one side does not move the opposite one.
    assert 0.0 in moved
