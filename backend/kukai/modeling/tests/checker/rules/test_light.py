"""HAB030 / HAB031 daylight-rule tests (design §6, IDs HAB030–HAB031)."""
from kukai.modeling.checker.fixtures.builders import (
    make_good,
    bad_bedroom_no_window,
    bad_low_daylight,
)
from kukai.modeling.checker.graph import build_graph
from kukai.modeling.checker.rules import light
from kukai.modeling.checker.spatial_model import SpatialModel, Severity
from kukai.modeling.checker.thresholds import THRESHOLDS


def _run030(d: dict):
    model = SpatialModel.model_validate(d)
    return light.check_hab030(model, build_graph(model), THRESHOLDS)


def test_hab030_silent_on_good():
    assert _run030(make_good()) == []


def test_hab030_fires_blocking_on_bedroom_without_window():
    viols = _run030(bad_bedroom_no_window())
    assert len(viols) == 1
    v = viols[0]
    assert v.rule_id == "HAB030"
    assert v.severity is Severity.BLOCKING      # жилая → BLOCKING
    assert "bed" in v.refs


def test_hab030_kitchen_without_window_is_warning_not_blocking():
    d = make_good()
    for room in d["rooms"]:
        if room["id"] == "kit":
            room["has_window"] = False
            room["window_area_m2"] = 0.0
    d["windows"] = [w for w in d["windows"] if w["id"] != "w_kit"]
    viols = _run030(d)
    assert len(viols) == 1
    assert viols[0].rule_id == "HAB030"
    assert viols[0].severity is Severity.WARNING   # кухня → WARNING
    assert "kit" in viols[0].refs


def test_hab030_ignores_non_habitable_rooms():
    # Removing a window from the санузел (not жилая/кухня) must NOT fire HAB030.
    d = make_good()
    for room in d["rooms"]:
        if room["id"] == "wc":
            room["has_window"] = False
            room["window_area_m2"] = 0.0
    assert _run030(d) == []


def _run031(d: dict):
    model = SpatialModel.model_validate(d)
    return light.check_hab031(model, build_graph(model), THRESHOLDS)


def test_hab031_silent_on_good():
    # make_good() bedroom: 2.5 m² window / 14 m² floor = 0.179 > 1/8 = 0.125 → OK.
    assert _run031(make_good()) == []


def test_hab031_fires_info_on_under_daylit_habitable_room():
    # bad_low_daylight shrinks the bedroom window below 1/8 of its floor area while
    # keeping has_window True (so it is HAB031's concern, not HAB030's).
    viols = _run031(bad_low_daylight())
    assert len(viols) == 1
    v = viols[0]
    assert v.rule_id == "HAB031"
    assert v.severity is Severity.INFO
    assert "bed" in v.refs


def test_hab031_does_not_double_report_windowless_room():
    # A windowless bedroom is HAB030's concern; HAB031 must stay silent on it.
    assert _run031(bad_bedroom_no_window()) == []


def test_hab031_ignores_non_habitable_rooms():
    # коридор has no window and a small ratio, but is not subject to HAB031.
    assert all(v.refs != ["cor"] for v in _run031(make_good()))
