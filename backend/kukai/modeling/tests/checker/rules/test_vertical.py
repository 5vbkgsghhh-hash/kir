"""HAB011 stair-geometry sanity tests (design §6/§7)."""
import copy

from kukai.modeling.checker.graph import build_graph
from kukai.modeling.checker.fixtures.builders import (
    make_good, bad_steep_stair, bad_discontinuous_core,
)
from kukai.modeling.checker.rules import vertical
from kukai.modeling.checker.spatial_model import SpatialModel, Severity
from kukai.modeling.checker.thresholds import THRESHOLDS


def _run(rule, raw: dict):
    """Call a rule function in isolation — build the graph from graph.py, never engine.run."""
    model = SpatialModel.model_validate(raw)
    graph = build_graph(model)
    return rule(model, graph, THRESHOLDS)


def test_hab011_silent_on_good():
    assert _run(vertical.check_hab011, make_good()) == []


def test_hab011_fires_on_steep_stair():
    viols = _run(vertical.check_hab011, bad_steep_stair())
    assert len(viols) == 1
    v = viols[0]
    assert v.rule_id == "HAB011"
    assert v.severity is Severity.WARNING
    assert "s0" in v.refs


def test_hab011_reports_all_three_defects():
    # narrow run AND steep rise AND shallow going all named in one message.
    v = _run(vertical.check_hab011, bad_steep_stair())[0]
    assert "width" in v.msg.lower()
    assert "rise" in v.msg.lower()
    assert "going" in v.msg.lower()


def test_hab011_skips_stair_with_null_riser_count():
    raw = bad_steep_stair()
    raw["stairs"][0]["riser_count"] = None   # rise underivable
    raw["stairs"][0]["run_width_mm"] = 1200.0
    raw["stairs"][0]["tread_depth_mm"] = 280.0
    assert _run(vertical.check_hab011, raw) == []


def test_hab011_skips_stair_with_null_tread_depth():
    raw = bad_steep_stair()
    raw["stairs"][0]["tread_depth_mm"] = None  # going underivable
    raw["stairs"][0]["run_width_mm"] = 1200.0
    raw["stairs"][0]["riser_count"] = 16
    raw["stairs"][0]["base_z"] = 0.0
    raw["stairs"][0]["top_z"] = 2880.0          # rise = 180 → OK (≤ 180)
    assert _run(vertical.check_hab011, raw) == []


def test_hab011_independent_defects_each_fire():
    # ONLY a narrow run, geometry otherwise fine.
    raw = copy.deepcopy(make_good())
    raw["stairs"][0]["run_width_mm"] = 900.0
    viols = _run(vertical.check_hab011, raw)
    assert len(viols) == 1
    assert viols[0].rule_id == "HAB011"
    assert "width" in viols[0].msg.lower()


def test_hab012_silent_on_good():
    # GOOD is single-level: no consecutive served levels to pair → silent.
    assert _run(vertical.check_hab012, make_good()) == []


def test_hab012_fires_on_discontinuous_core():
    viols = _run(vertical.check_hab012, bad_discontinuous_core())
    assert len(viols) == 1
    v = viols[0]
    assert v.rule_id == "HAB012"
    assert v.severity is Severity.WARNING
    # both jogged runs are referenced (refs are sorted for determinism).
    assert "s0" in v.refs and "s1" in v.refs
    assert "overlap" in v.msg.lower()


def test_hab012_silent_when_core_is_aligned():
    # Two stacked levels with IDENTICAL footprints → 100% overlap → silent.
    raw = bad_discontinuous_core()
    raw["stairs"][1]["footprint"] = list(raw["stairs"][0]["footprint"])
    assert _run(vertical.check_hab012, raw) == []
