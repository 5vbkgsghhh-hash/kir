"""Dimension-rule tests (design §6: HAB020/021/022). Each rule fires on its BAD
fixture and stays silent on make_good()."""
import networkx as nx

from kukai.modeling.checker.spatial_model import SpatialModel, Severity
from kukai.modeling.checker.thresholds import THRESHOLDS
from kukai.modeling.checker.graph import build_graph
from kukai.modeling.checker.rules import dimensions
from kukai.modeling.checker.fixtures.builders import (
    make_good,
    bad_tiny_bedroom,
    bad_narrow_corridor,
    bad_low_ceiling,
)


def _parsed(d: dict) -> tuple[SpatialModel, nx.Graph]:
    model = SpatialModel.model_validate(d)
    return model, build_graph(model)


# ---------- HAB020: minimum room area by function ----------

def test_hab020_silent_on_good():
    model, graph = _parsed(make_good())
    assert dimensions.check_hab020(model, graph, THRESHOLDS) == []


def test_hab020_fires_on_tiny_bedroom():
    model, graph = _parsed(bad_tiny_bedroom())
    vios = dimensions.check_hab020(model, graph, THRESHOLDS)
    assert len(vios) == 1
    v = vios[0]
    assert v.rule_id == "HAB020"
    assert v.severity is Severity.BLOCKING          # жилая is BLOCKING
    assert "bed" in v.refs
    assert "4" in v.msg and "8" in v.msg            # actual 4 m² vs required 8 m²


def test_hab020_zhilaya_is_blocking_kuhnya_is_blocking_other_is_warning():
    # Shrink the санузел below its 2.2 m² threshold → WARNING, not BLOCKING.
    d = make_good()
    for r in d["rooms"]:
        if r["id"] == "wc":
            r["area_m2"] = 1.0
    model, graph = _parsed(d)
    vios = dimensions.check_hab020(model, graph, THRESHOLDS)
    assert len(vios) == 1
    assert vios[0].rule_id == "HAB020"
    assert vios[0].severity is Severity.WARNING     # санузел is non-blocking
    assert "wc" in vios[0].refs


# ---------- HAB021: minimum room width ----------

def test_hab021_silent_on_good():
    model, graph = _parsed(make_good())
    assert dimensions.check_hab021(model, graph, THRESHOLDS) == []


def test_hab021_fires_on_narrow_corridor():
    model, graph = _parsed(bad_narrow_corridor())
    vios = dimensions.check_hab021(model, graph, THRESHOLDS)
    assert len(vios) == 1
    v = vios[0]
    assert v.rule_id == "HAB021"
    assert v.severity is Severity.WARNING
    assert "cor" in v.refs
    assert "900" in v.msg            # required коридор width 900 mm appears in the message


def test_hab021_narrow_bedroom_also_fires():
    # A 1500 mm-wide bedroom (< 2000) → WARNING on жилая width.
    d = make_good()
    for r in d["rooms"]:
        if r["id"] == "bed":
            # 1500 mm wide × long strip, area kept healthy so only HAB021 is at stake.
            r["boundary"] = [[2000, 4000], [3500, 4000], [3500, 14000], [2000, 14000]]
            r["area_m2"] = 15.0
    model, graph = _parsed(d)
    vios = dimensions.check_hab021(model, graph, THRESHOLDS)
    assert len(vios) == 1
    assert vios[0].rule_id == "HAB021"
    assert "bed" in vios[0].refs
    assert "2000" in vios[0].msg


# ---------- HAB022: minimum ceiling height ----------

def test_hab022_silent_on_good():
    model, graph = _parsed(make_good())
    assert dimensions.check_hab022(model, graph, THRESHOLDS) == []


def test_hab022_fires_on_low_ceiling():
    model, graph = _parsed(bad_low_ceiling())
    vios = dimensions.check_hab022(model, graph, THRESHOLDS)
    assert len(vios) == 1
    v = vios[0]
    assert v.rule_id == "HAB022"
    assert v.severity is Severity.WARNING
    assert "bed" in v.refs
    assert "2200" in v.msg and "2500" in v.msg     # actual 2200 vs required 2500 mm


def test_hab022_checks_every_function():
    # Drop the санузел ceiling too — both low rooms must be reported.
    d = bad_low_ceiling()
    for r in d["rooms"]:
        if r["id"] == "wc":
            r["height_mm"] = 2300.0
    model, graph = _parsed(d)
    vios = dimensions.check_hab022(model, graph, THRESHOLDS)
    refs = {ref for v in vios for ref in v.refs}
    assert refs == {"bed", "wc"}
    assert all(v.severity is Severity.WARNING for v in vios)
