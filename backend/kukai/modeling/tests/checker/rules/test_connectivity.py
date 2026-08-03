"""Connectivity rule tests (design §6: HAB001–004, HAB010).

Each rule fires on its dedicated bad_* fixture (imported from the canonical builders) and stays
silent on make_good(). Rules are exercised directly via build_graph + THRESHOLDS — the engine is
built last and is NOT imported here.
"""
from kukai.modeling.checker.fixtures.builders import (
    make_good,
    bad_room_no_door,
    bad_apartment_into_apartment,
    bad_no_egress_stair,
    bad_floating_floor,
)
from kukai.modeling.checker.graph import build_graph
from kukai.modeling.checker.thresholds import THRESHOLDS
from kukai.modeling.checker.spatial_model import SpatialModel, Severity
from kukai.modeling.checker.rules import connectivity


def _run(rule, model_dict):
    model = SpatialModel.model_validate(model_dict)
    graph = build_graph(model)
    return rule(model, graph, THRESHOLDS)


def _ids(violations):
    return {v.rule_id for v in violations}


# ---- HAB001 -------------------------------------------------------------------

def test_hab001_silent_on_good():
    assert _run(connectivity.check_hab001, make_good()) == []


def test_hab001_fires_on_unreachable_room():
    violations = _run(connectivity.check_hab001, bad_room_no_door())
    assert "HAB001" in _ids(violations)
    v = next(v for v in violations if v.rule_id == "HAB001")
    assert v.severity is Severity.BLOCKING
    assert "wc" in v.refs            # the isolated санузел is named


# ---- HAB002 -------------------------------------------------------------------

def test_hab002_silent_on_good():
    assert _run(connectivity.check_hab002, make_good()) == []


def test_hab002_fires_on_apartment_into_apartment():
    violations = _run(connectivity.check_hab002, bad_apartment_into_apartment())
    assert "HAB002" in _ids(violations)
    v = next(v for v in violations if v.rule_id == "HAB002")
    assert v.severity is Severity.BLOCKING
    # the offending door connects A1's hall and A2's hall2 — both apartment ids named in refs
    assert "A1" in v.refs and "A2" in v.refs


# ---- HAB003 -------------------------------------------------------------------

def test_hab003_silent_on_good():
    assert _run(connectivity.check_hab003, make_good()) == []


def test_hab003_fires_when_no_path_to_stair():
    violations = _run(connectivity.check_hab003, bad_no_egress_stair())
    assert "HAB003" in _ids(violations)
    v = next(v for v in violations if v.rule_id == "HAB003")
    assert v.severity is Severity.BLOCKING
    assert v.refs                    # names the apartment entrance door(s) / rooms lacking egress


# ---- HAB004 -------------------------------------------------------------------

def test_hab004_silent_on_good():
    assert _run(connectivity.check_hab004, make_good()) == []


def test_hab004_fires_when_room_unreachable_from_prihozhaya():
    # Same fixture as HAB001: the санузел 'wc' is cut off from its прихожая.
    violations = _run(connectivity.check_hab004, bad_room_no_door())
    assert "HAB004" in _ids(violations)
    v = next(v for v in violations if v.rule_id == "HAB004")
    assert v.severity is Severity.BLOCKING
    assert "wc" in v.refs


# ---- HAB010 -------------------------------------------------------------------

def test_hab010_silent_on_good():
    assert _run(connectivity.check_hab010, make_good()) == []


def test_hab010_fires_on_floating_floor():
    violations = _run(connectivity.check_hab010, bad_floating_floor())
    assert "HAB010" in _ids(violations)
    v = next(v for v in violations if v.rule_id == "HAB010")
    assert v.severity is Severity.BLOCKING
    assert "L1" in v.refs            # the floating level is named


def test_hab010_fires_when_no_stairs_at_all_multilevel():
    # Multi-level base (L0 + occupied L1) with EVERY stair removed: L1 is occupied, non-ground,
    # and has no vertical connection to ground -> HAB010 fires. (On the single-level GOOD base,
    # removing stairs leaves L0 a ground level, so HAB010 correctly stays silent there — that
    # single-level case is HAB003's job, covered above.)
    d = bad_no_egress_stair(bad_floating_floor())
    violations = _run(connectivity.check_hab010, d)
    assert "HAB010" in _ids(violations)


# ---- group regression guard ---------------------------------------------------

_CONNECTIVITY_RULES = [
    connectivity.check_hab001,
    connectivity.check_hab002,
    connectivity.check_hab003,
    connectivity.check_hab004,
    connectivity.check_hab010,
]


def test_all_connectivity_rules_silent_on_good():
    good = make_good()
    fired = set()
    for rule in _CONNECTIVITY_RULES:
        fired |= _ids(_run(rule, good))
    assert fired == set()


def test_each_bad_fixture_trips_its_target_rule():
    # (fixture, rule_ids that MUST appear when sweeping the whole connectivity group)
    cases = [
        (bad_room_no_door(), {"HAB001", "HAB004"}),       # isolated 'wc': unreachable + not from прихожая
        (bad_apartment_into_apartment(), {"HAB002"}),     # nested apartment A2 inside A1
        (bad_no_egress_stair(), {"HAB003"}),              # single-level base: no stair -> no egress (L0 stays ground)
        (bad_floating_floor(), {"HAB010"}),               # floating upper level L1
    ]
    for model_dict, must_fire in cases:
        fired = set()
        for rule in _CONNECTIVITY_RULES:
            fired |= _ids(_run(rule, model_dict))
        assert must_fire <= fired, (model_dict.get("building_id"), must_fire, fired)


def test_hab002_detects_unstamped_apartment_nesting():
    # Strip the nested apartment's apartment_id: branch (a) goes blind, but the structural
    # >1-прихожая signal (branch c) must still flag the fusion (review fix — §4 stamp is optional).
    d = bad_apartment_into_apartment()
    for r in d["rooms"]:
        if r["id"] in ("hall2", "bed2"):
            r["apartment_id"] = None
    fired = _ids(_run(connectivity.check_hab002, d))
    assert "HAB002" in fired
