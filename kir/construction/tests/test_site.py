from __future__ import annotations

import json

import pytest

from kir.clash import geom as G
from kir.construction import (
    CapacityBand,
    ConstructionError,
    CoverageState,
    CoverageTarget,
    Feasibility,
    GeometryAuthority,
    HoistStop,
    HoistTripRequest,
    LiftRequest,
    MaterialHoist,
    Obstacle,
    ObstacleAuthority,
    TowerCrane,
    analyze_crane_coverage,
    plan_hoist_trip,
    plan_tower_crane_lift,
    rank_crane_positions,
)
from kir.clash.hulls import HullRecord


def crane(**changes) -> TowerCrane:
    values = {
        "id": "TC-1",
        "base_mm": (0, 0, 0),
        "max_hook_height_mm": 30_000,
        "min_radius_mm": 2_000,
        "load_chart": (
            CapacityBand(10_000, 5_000),
            CapacityBand(20_000, 2_000),
        ),
        "hoist_speed_mm_s": 1_000,
        "trolley_speed_mm_s": 500,
        "slew_speed_deg_s": 10,
    }
    values.update(changes)
    return TowerCrane(**values)


def target(identifier, lo, hi, *, hook=None, load=None) -> CoverageTarget:
    return CoverageTarget(identifier, lo, hi, hook, load)


def test_capacity_between_chart_rows_uses_the_outer_conservative_band() -> None:
    machine = crane()

    assert machine.capacity_at(10_000) == 5_000
    assert machine.capacity_at(10_001) == 2_000
    assert machine.capacity_at(20_001) is None


def test_a_chart_that_gets_stronger_with_radius_is_refused() -> None:
    with pytest.raises(ConstructionError, match="must not increase"):
        crane(load_chart=(CapacityBand(10_000, 2_000),
                          CapacityBand(20_000, 3_000)))


def test_coverage_names_full_partial_and_none_and_keeps_its_census() -> None:
    report = analyze_crane_coverage(crane(), (
        target("full", (3_000, 0, 0), (4_000, 1_000, 3_000),
               hook=(3_500, 500, 3_000), load=1_000),
        target("partial", (19_000, 0, 0), (21_000, 1_000, 3_000),
               hook=(19_500, 500, 3_000), load=1_000),
        target("none", (21_000, 0, 0), (22_000, 1_000, 3_000),
               hook=(21_500, 500, 3_000), load=1_000),
    ))

    assert [item.coverage for item in report.assessments] == [
        CoverageState.FULL, CoverageState.PARTIAL, CoverageState.NONE]
    assert report.census["coverage"] == {"full": 1, "partial": 1, "none": 1}
    assert sum(report.census["coverage"].values()) == 3


def test_unknown_mass_never_becomes_a_zero_weight_green_lift() -> None:
    report = analyze_crane_coverage(crane(), (
        target("unknown", (3_000, 0, 0), (4_000, 1_000, 3_000),
               hook=(3_500, 500, 3_000)),
    ))

    item = report.assessments[0]
    assert item.coverage is CoverageState.FULL
    assert item.liftability is Feasibility.UNKNOWN
    assert "gross_load_unknown" in item.reasons


def test_a_clash_hull_enters_coverage_without_inventing_mass_or_hook() -> None:
    record = HullRecord(
        source_id="element-7", category="Structural Columns", label="",
        mvp_side=None, hull=G.Aabb((3_000, 0, 0), (4_000, 1_000, 3_000)),
        grade="coarse", hull_source="bbox")

    converted = CoverageTarget.from_hull_record(record)
    item = analyze_crane_coverage(crane(), (converted,)).assessments[0]

    assert converted.id == "element-7"
    assert converted.geometry_authority is GeometryAuthority.OUTER_ENVELOPE
    assert item.coverage is CoverageState.FULL
    assert item.coverage_assertion == "confirmed"
    assert item.liftability is Feasibility.UNKNOWN
    assert "hook_point_unknown" in item.reasons


def test_partial_overlap_of_an_outer_hull_is_only_possible() -> None:
    record = HullRecord(
        source_id="wide-box", category="Generic Models", label="",
        mvp_side=None,
        hull=G.Aabb((19_000, 0, 0), (21_000, 1_000, 3_000)),
        grade="coarse", hull_source="bbox")

    item = analyze_crane_coverage(
        crane(), (CoverageTarget.from_hull_record(record),)).assessments[0]

    assert item.coverage is CoverageState.PARTIAL
    assert item.coverage_assertion == "possible"


def test_candidate_positions_are_ranked_by_what_they_can_really_lift() -> None:
    targets = (
        target("a", (3_000, 0, 0), (4_000, 1_000, 2_000),
               hook=(3_500, 500, 2_000), load=1_000),
        target("b", (21_000, 0, 0), (22_000, 1_000, 2_000),
               hook=(21_500, 500, 2_000), load=1_500),
    )

    ranked = rank_crane_positions(
        crane(), ((0, 0, 0), (8_000, 0, 0)), targets)

    assert ranked[0].base_mm == (8_000.0, 0.0, 0.0)
    assert ranked[0].serviceable_targets == 2
    assert ranked[1].serviceable_targets == 1


def test_lift_raises_above_an_exact_zone_and_emits_animation_keyframes() -> None:
    lift = LiftRequest(
        id="L-1", pickup_mm=(5_000, 0, 0), set_mm=(0, 10_000, 0),
        gross_load_kg=1_000, load_radius_mm=200, clearance_mm=300)
    obstacle = Obstacle(
        id="building", hull=G.Aabb((3_000, 3_000, 0), (8_000, 8_000, 8_000)),
        authority=ObstacleAuthority.EXACT_ZONE)

    plan = plan_tower_crane_lift(crane(), lift, (obstacle,))

    assert plan.feasibility is Feasibility.FEASIBLE
    assert plan.travel_z_mm > 8_500
    assert plan.keyframes[0].state == "pickup"
    assert plan.keyframes[-1].state == "placed"
    assert plan.duration_s > 0
    assert any(segment.action == "slew" for segment in plan.segments)
    assert plan.approximation_error_mm > 0
    assert plan.conflicts == ()


def test_planner_changes_motion_order_when_that_avoids_the_obstacle() -> None:
    lift = LiftRequest(
        id="L-order", pickup_mm=(5_000, 0, 0), set_mm=(0, 10_000, 0),
        gross_load_kg=1_000, load_radius_mm=200, clearance_mm=300)
    obstacle = Obstacle(
        id="inside-small-arc",
        hull=G.Aabb((3_000, 3_000, -1_000), (4_000, 4_000, 1_000)),
        authority=ObstacleAuthority.EXACT_ZONE)

    plan = plan_tower_crane_lift(crane(), lift, (obstacle,))

    assert plan.feasibility is Feasibility.FEASIBLE
    assert plan.motion_order == "trolley_then_slew"
    assert plan.travel_z_mm == 0.0


def test_an_outer_envelope_can_only_make_the_path_unknown() -> None:
    lift = LiftRequest(
        id="L-2", pickup_mm=(5_000, 0, 0), set_mm=(0, 10_000, 0),
        gross_load_kg=1_000, load_radius_mm=200, clearance_mm=300)
    obstacle = Obstacle(
        id="coarse-model",
        hull=G.Aabb((-20_000, -20_000, -1_000),
                    (20_000, 20_000, 40_000)),
        authority=ObstacleAuthority.OUTER_ENVELOPE)

    plan = plan_tower_crane_lift(crane(), lift, (obstacle,))

    assert plan.feasibility is Feasibility.UNKNOWN
    assert "possible_path_intersection_with_outer_envelope" in plan.reasons
    assert plan.conflicts
    assert all(item.conclusion == "possible_intersection"
               for item in plan.conflicts)


def test_an_overweight_lift_is_refused_before_a_pretty_trajectory_exists() -> None:
    lift = LiftRequest(
        id="heavy", pickup_mm=(15_000, 0, 0), set_mm=(0, 15_000, 0),
        gross_load_kg=2_500, load_radius_mm=100)

    plan = plan_tower_crane_lift(crane(), lift)

    assert plan.feasibility is Feasibility.REFUSED
    assert plan.segments == ()
    assert "gross_load_exceeds_chart_at_worst_radius" in plan.reasons


def test_hoist_trip_has_a_timed_vertical_motion_and_cycle_time() -> None:
    hoist = MaterialHoist(
        id="H-1", position_xy_mm=(1_000, 2_000),
        stops=(HoistStop("ground", 0), HoistStop("L4", 10_000)),
        max_gross_load_kg=2_000, up_speed_mm_s=1_000,
        down_speed_mm_s=2_000, load_time_s=10, unload_time_s=20,
        door_cycle_s=5)

    plan = plan_hoist_trip(
        hoist, HoistTripRequest("trip-1", "ground", "L4", 1_500))

    assert plan.feasibility is Feasibility.FEASIBLE
    assert plan.duration_s == pytest.approx(50.0)
    assert plan.segments[0].action == "hoist_up"
    assert [frame.state for frame in plan.keyframes] == [
        "loading", "depart", "arrive", "complete"]
    assert plan.keyframes[-1].position_mm == (1_000.0, 2_000.0, 10_000.0)


def test_overweight_hoist_trip_is_refused() -> None:
    hoist = MaterialHoist(
        id="H-1", position_xy_mm=(0, 0),
        stops=(HoistStop("ground", 0), HoistStop("L1", 3_000)),
        max_gross_load_kg=1_000, up_speed_mm_s=500, down_speed_mm_s=500,
        load_time_s=0, unload_time_s=0, door_cycle_s=0)

    plan = plan_hoist_trip(
        hoist, HoistTripRequest("trip", "ground", "L1", 1_001))

    assert plan.feasibility is Feasibility.REFUSED
    assert plan.keyframes == ()
    assert plan.reasons == ("gross_load_exceeds_hoist_capacity",)


def test_reports_are_plain_deterministic_json_values() -> None:
    report = analyze_crane_coverage(crane(), (
        target("a", (3_000, 0, 0), (4_000, 1_000, 2_000),
               hook=(3_500, 500, 2_000), load=1_000),
    ))

    once = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    twice = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    assert once == twice
