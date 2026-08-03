"""Every §6 threshold is present with the spec's v1 value (design §6/§11.4)."""
from kukai.modeling.checker.thresholds import Thresholds, THRESHOLDS


def test_threshold_values_match_spec():
    t = THRESHOLDS
    assert t.stair_min_run_width_mm == 1000.0
    assert t.stair_max_rise_mm == 180.0
    assert t.stair_min_going_mm == 250.0
    assert t.stair_min_footprint_overlap_ratio == 0.50
    assert t.min_area_zhilaya_m2 == 8.0
    assert t.min_area_kuhnya_m2 == 5.0
    assert t.min_area_sanuzel_m2 == 2.2
    assert t.min_width_zhilaya_mm == 2000.0
    assert t.min_width_koridor_mm == 900.0
    assert t.min_ceiling_height_mm == 2500.0
    assert abs(t.min_daylight_ratio - 1.0 / 8.0) < 1e-12
    assert t.max_room_overlap_m2 == 0.05
    assert t.max_envelope_gap_mm == 50.0
    assert t.min_envelope_coverage_ratio == 0.10
    assert t.struct_support_offset_mm == 200.0
    assert t.struct_min_support_overlap_mm == 300.0
    assert t.wall_snap_tol_mm == 50.0


def test_thresholds_is_frozen_and_overridable():
    # Profiles are built by constructing a NEW Thresholds, not mutating the singleton.
    strict = Thresholds(min_area_zhilaya_m2=10.0)
    assert strict.min_area_zhilaya_m2 == 10.0
    assert THRESHOLDS.min_area_zhilaya_m2 == 8.0
