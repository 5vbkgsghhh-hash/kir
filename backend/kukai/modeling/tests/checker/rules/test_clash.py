"""rules/clash.py tests — HAB040–042 room-footprint overlap & door/envelope rules (design §6).

Rules are tested in isolation: call clash.check_habNNN(model, build_graph(model), THRESHOLDS)
and assert on the returned list[Violation]. The engine (part 50) is NOT imported here.
"""
import copy

from kukai.modeling.checker.graph import build_graph
from kukai.modeling.checker.rules import clash
from kukai.modeling.checker.fixtures.builders import (
    make_good, bad_overlapping_rooms, bad_door_in_wall, bad_open_envelope,
)
from kukai.modeling.checker.spatial_model import SpatialModel, Severity
from kukai.modeling.checker.thresholds import THRESHOLDS


def _run(rule, d: dict):
    """Validate a raw dict into a SpatialModel and run one rule directly."""
    m = SpatialModel.model_validate(d)
    return rule(m, build_graph(m), THRESHOLDS)


def _ids(violations):
    return {v.rule_id for v in violations}


def test_hab040_fires_on_overlapping_rooms():
    vs = _run(clash.check_hab040, bad_overlapping_rooms())
    assert "HAB040" in _ids(vs)
    v = next(x for x in vs if x.rule_id == "HAB040")
    assert v.severity is Severity.BLOCKING
    # refs are sorted() for determinism (D12) → ['bed', 'kit'].
    assert v.refs == ["bed", "kit"]
    assert "overlap" in v.msg.lower()


def test_hab040_silent_on_good():
    vs = _run(clash.check_hab040, make_good())
    assert "HAB040" not in _ids(vs)


def test_hab040_ignores_overlap_below_tolerance():
    # A negligible 0.04 m² overlap (< thr.max_room_overlap_m2 = 0.05) must NOT fire.
    d = copy.deepcopy(make_good())
    bed = next(r for r in d["rooms"] if r["id"] == "bed")
    # make_good() geometry: bed x[4500,8000] y[4000,6500]; stair x[4500,7000] y[0,4000] shares
    # bed's bottom edge over a 2500 mm span. Nudge bed DOWN by 16 mm (y-min 4000→3984) → it
    # dips into stair by 2500 mm × 16 mm = 40000 mm² = 0.04 m² < 0.05 → HAB040 must stay silent.
    bed["boundary"] = [[4500, 3984], [8000, 3984], [8000, 6500], [4500, 6500]]
    vs = _run(clash.check_hab040, d)
    assert "HAB040" not in _ids(vs)


def test_hab040_only_compares_same_level():
    # Two rooms with identical footprints on DIFFERENT levels do not clash.
    d = copy.deepcopy(make_good())
    d["levels"].append({"id": "L1", "name": "Этаж 2", "elevation_mm": 3000.0, "index": 1})
    twin = copy.deepcopy(next(r for r in d["rooms"] if r["id"] == "bed"))
    twin["id"] = "bed_L1"
    twin["level_id"] = "L1"
    twin["apartment_id"] = "A2"
    d["rooms"].append(twin)
    vs = _run(clash.check_hab040, d)
    assert "HAB040" not in _ids(vs)


def test_hab041_fires_on_door_not_swinging_into_room():
    vs = _run(clash.check_hab041, bad_door_in_wall())
    v = next(x for x in vs if x.rule_id == "HAB041")
    assert v.severity is Severity.WARNING
    assert "d_inwall" in v.refs
    # bad door connects nothing (both rooms None, not exterior) → "no room"
    assert "room" in v.msg.lower()


def test_hab041_fires_when_door_wider_than_host_wall():
    d = copy.deepcopy(make_good())
    # make_good() geometry: wall_b is curve [[8000,4000],[8000,6500]] → length 2500 mm (bed's
    # east envelope edge). Add a door hosted ON it that is genuinely too wide (3000 mm > 2500).
    d["doors"].append({
        "id": "d_toowide", "level_id": "L0", "location": [8000, 5250], "width_mm": 3000.0,
        "from_room_id": "bed", "to_room_id": "kit", "is_exterior": False,
    })
    vs = _run(clash.check_hab041, d)
    v = next(x for x in vs if x.rule_id == "HAB041" and "d_toowide" in x.refs)
    assert "wider" in v.msg.lower() or "width" in v.msg.lower()


def test_hab041_interior_door_not_on_declared_wall_is_silent():
    # An interior door whose location is on no declared wall must NOT fire (wall not modeled).
    d = copy.deepcopy(make_good())
    d["doors"].append({
        "id": "d_floating", "level_id": "L0", "location": [9999, 9999], "width_mm": 800.0,
        "from_room_id": "bed", "to_room_id": "kit", "is_exterior": False,
    })
    vs = _run(clash.check_hab041, d)
    assert not any("d_floating" in v.refs for v in vs)


def test_hab041_silent_on_good():
    vs = _run(clash.check_hab041, make_good())
    assert "HAB041" not in _ids(vs)


def test_hab042_fires_on_open_envelope():
    # bad_open_envelope strips the apartment's walls → coverage ~0 → HAB042 fires.
    vs = _run(clash.check_hab042, bad_open_envelope())
    v = next(x for x in vs if x.rule_id == "HAB042")
    assert v.severity is Severity.WARNING
    assert any(ref.startswith("A1") or ref == "A1" for ref in v.refs)
    assert "gap" in v.msg.lower() or "open" in v.msg.lower() or "envelope" in v.msg.lower()


def test_hab042_silent_on_good():
    vs = _run(clash.check_hab042, make_good())
    assert "HAB042" not in _ids(vs)


def test_hab042_good_coverage_well_above_floor():
    """Regression pin (D14): GOOD envelope coverage must sit clearly above the floor so that any
    later drift of make_good()'s geometry that erodes enclosure fails loudly here, not silently."""
    m = SpatialModel.model_validate(make_good())
    coverage = clash._apartment_envelope_coverage(m, "A1", THRESHOLDS)
    assert coverage is not None
    # GOOD must clear the floor with margin (floor is THRESHOLDS.min_envelope_coverage_ratio = 0.10).
    assert coverage >= THRESHOLDS.min_envelope_coverage_ratio + 0.10, (
        f"GOOD envelope coverage {coverage:.3f} drifted toward the HAB042 floor "
        f"{THRESHOLDS.min_envelope_coverage_ratio}"
    )


def test_hab042_point_walls_do_not_fake_enclosure():
    # review fix: tiny point-sized walls must NOT fake enclosure. The old midpoint heuristic
    # scored such an apartment ~0.5 (silent); the length-based coverage scores ~0.01, so HAB042
    # correctly fires.
    d = make_good()
    d["walls"] = [{"id": "wp", "level_id": "L0", "curve": [[0, 8000], [0, 8010]],
                   "height_mm": 2700.0, "is_structural": True}]
    vs = _run(clash.check_hab042, d)
    assert any(v.rule_id == "HAB042" for v in vs)


def test_good_is_silent_across_all_clash_rules():
    d = make_good()
    fired: set[str] = set()
    for rule in (clash.check_hab040, clash.check_hab041, clash.check_hab042):
        fired |= _ids(_run(rule, d))
    assert fired.isdisjoint({"HAB040", "HAB041", "HAB042"}), f"clash rules fired on GOOD: {fired}"
