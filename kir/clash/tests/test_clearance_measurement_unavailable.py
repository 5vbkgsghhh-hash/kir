"""Real OCP bodies: non-intersection is not a measured clearance.

Only the distance getter is faulted. Boolean geometry, placement and the actual
exact/project-analysis integration still run. No Revit or stored project writes.
"""
from types import SimpleNamespace

import pytest

from kir.clash import exact
from kir.clash.project_analysis import (
    CLEARANCE_SOURCE, Finding, NO_CLEARANCE_REQUIREMENT, _judge_clearance, _verify_exact,
)
from kir.viewer.clash_findings import ClashDisplayRefusal, display_clash_findings


def pair(gap=10):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    bodies = {"a": (BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 100, 100, 100).Shape(), None),
              "b": (BRepPrimAPI_MakeBox(gp_Pnt(100 + gap, 0, 0), 100, 100, 100).Shape(), None)}
    finding = Finding("distance-pair", "a", "b", "possible", "clear", "clearance",
                      "axis_aligned_bbox", gap_mm=float(gap))
    return [finding], bodies


def failed_distance_getter(monkeypatch):
    original_kernel = exact._kernel
    visited = []
    def kernel():
        native = original_kernel()
        constructor = native.BRepExtrema_DistShapeShape
        class Probe:
            def __init__(self, a, b): self.actual = constructor(a, b)
            def IsDone(self): return self.actual.IsDone()
            def Value(self):
                visited.append(float(self.actual.Value()))
                raise RuntimeError("controlled distance getter failure")
        return SimpleNamespace(**{**vars(native), "BRepExtrema_DistShapeShape": Probe})
    monkeypatch.setattr(exact, "_kernel", kernel)
    return visited


@pytest.mark.parametrize("entrypoint", [_verify_exact, _judge_clearance])
def test_failed_native_distance_getter_never_confirms_required_clearance(monkeypatch, entrypoint):
    findings, bodies = pair()
    visited = failed_distance_getter(monkeypatch)
    result, limits = entrypoint(findings, bodies, {"clearance_mm": 50})
    assert visited == pytest.approx([10])
    item, = result
    assert item.status == "clearance_unverified"
    assert item.relation == "clear" and item.overlap_volume_mm3 == 0
    assert item.gap_mm is None and item.deficit_mm is None
    assert item.required_clearance_mm == 50 and item.clearance_source == CLEARANCE_SOURCE
    assert any(item.finding_id in text and "distance" in text for text in limits)
    shown = display_clash_findings({"findings": [item.to_dict()], "analysis_limits": limits,
        "hull_source": {"a": "brep", "b": "brep"}}, ["a", "b"])
    row, = shown["findings"]
    assert row["status"] == "clearance_unverified" and row["gap_mm"] is None and row["deficit_mm"] is None
    assert row["refusal_ru"] and shown["analysis_limits"] == limits


@pytest.mark.parametrize("distance", [None, float("nan"), float("inf"), -1.0])
def test_exact_distance_none_is_not_refuted_even_with_a_coarse_numeric_gap(monkeypatch, distance):
    findings, bodies = pair()
    monkeypatch.setattr(exact, "_distance", lambda *_: distance)
    result, limits = _verify_exact(findings, bodies, {"clearance_mm": 50})
    assert result[0].status == "clearance_unverified"
    assert result[0].gap_mm is None and result[0].deficit_mm is None and limits


@pytest.mark.parametrize("gap,status,deficit", [(10, "clearance_violated", 40), (50, "refuted", None), (75, "refuted", None)])
def test_real_measured_clearance_retains_the_existing_three_outcomes(gap, status, deficit):
    findings, bodies = pair(gap)
    result, limits = _verify_exact(findings, bodies, {"clearance_mm": 50})
    item, = result
    assert item.status == status and item.gap_mm == pytest.approx(gap)
    assert item.required_clearance_mm == 50 and item.deficit_mm == deficit
    assert not limits


def test_without_a_requirement_boolean_clear_does_not_need_a_distance_measurement(monkeypatch):
    findings, bodies = pair()
    failed_distance_getter(monkeypatch)
    result, limits = _verify_exact(findings, bodies, {})
    item, = result
    assert item.status == "refuted" and item.relation == "clear" and item.gap_mm is None
    assert item.required_clearance_mm is None and item.deficit_mm is None
    assert "required_clearance_mm" not in item.to_dict()
    assert limits == [NO_CLEARANCE_REQUIREMENT]


def unknown_display_row(**changes):
    return {"finding_id": "unknown-gap", "a": "a", "b": "b", "status": "clearance_unverified",
            "relation": "clear", "gap_mm": None, "deficit_mm": None, "overlap_volume_mm3": 0,
            "required_clearance_mm": 50, "clearance_source": CLEARANCE_SOURCE,
            "refusal_ru": "Расстояние не измерено; требование не проверено", **changes}


def test_display_accepts_explicit_unknown_measurement_not_an_invented_zero():
    row = unknown_display_row()
    result = display_clash_findings({"findings": [row]}, ["a", "b"])
    assert result["findings"][0]["gap_mm"] is result["findings"][0]["deficit_mm"] is None
    assert result["findings"][0]["refusal_ru"] == row["refusal_ru"]


def test_existing_coarse_unverified_gap_and_deficit_remain_displayable():
    row = unknown_display_row(gap_mm=10, deficit_mm=40, refusal_ru=None)
    result = display_clash_findings({"findings": [row]}, ["a", "b"])
    assert result["findings"][0]["gap_mm"] == 10 and result["findings"][0]["deficit_mm"] == 40


@pytest.mark.parametrize("changes", [
    {"status": "clearance_violated"}, {"required_clearance_mm": None},
    {"clearance_source": None}, {"refusal_ru": None}, {"gap_mm": 10}, {"deficit_mm": 40},
])
def test_display_refuses_incomplete_or_mixed_unknown_and_measured_claims(changes):
    with pytest.raises(ClashDisplayRefusal):
        display_clash_findings({"findings": [unknown_display_row(**changes)]}, ["a", "b"])
