"""Tower crane and material hoist as testable construction-site resources.

Run after ``pip install .`` from the repository root:
    python3.12 examples/construction_site.py
"""

from __future__ import annotations

import json

from kir.clash import geom as G
from kir.construction import (
    CapacityBand,
    CoverageTarget,
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


crane = TowerCrane(
    id="TC-1",
    base_mm=(0, 0, 0),
    max_hook_height_mm=54_000,
    min_radius_mm=2_500,
    load_chart=(
        CapacityBand(max_radius_mm=20_000, max_gross_load_kg=8_000),
        CapacityBand(max_radius_mm=35_000, max_gross_load_kg=4_000),
        CapacityBand(max_radius_mm=50_000, max_gross_load_kg=2_000),
    ),
    hoist_speed_mm_s=900,
    trolley_speed_mm_s=700,
    slew_speed_deg_s=0.7,
)

targets = (
    CoverageTarget(
        id="column-A1", lo_mm=(8_000, 4_000, 0), hi_mm=(8_600, 4_600, 12_000),
        hook_point_mm=(8_300, 4_300, 12_000), gross_load_kg=3_200),
    CoverageTarget(
        id="panel-D7", lo_mm=(31_000, 8_000, 18_000),
        hi_mm=(37_000, 8_300, 21_000),
        hook_point_mm=(34_000, 8_150, 21_000), gross_load_kg=2_300),
    CoverageTarget(
        id="unknown-prefab", lo_mm=(18_000, 16_000, 24_000),
        hi_mm=(20_000, 18_000, 27_000),
        hook_point_mm=(19_000, 17_000, 27_000), gross_load_kg=None),
)

coverage = analyze_crane_coverage(crane, targets)
positions = rank_crane_positions(
    crane,
    candidate_bases_mm=((0, 0, 0), (8_000, 4_000, 0), (15_000, 0, 0)),
    targets=targets,
)

lift = LiftRequest(
    id="mount-column-A1",
    pickup_mm=(12_000, -8_000, 1_500),
    set_mm=(8_300, 4_300, 12_000),
    gross_load_kg=3_200,
    load_radius_mm=800,
    clearance_mm=500,
)
temporary_no_fly_zone = Obstacle(
    id="occupied-work-front",
    hull=G.Aabb((5_000, -1_000, 0), (10_000, 2_000, 15_000)),
    authority=ObstacleAuthority.EXACT_ZONE,
    label="зона параллельных работ",
)
lift_plan = plan_tower_crane_lift(
    crane, lift, obstacles=(temporary_no_fly_zone,))

hoist = MaterialHoist(
    id="H-1",
    position_xy_mm=(2_000, -1_500),
    stops=(HoistStop("ground", 0), HoistStop("L6", 21_600)),
    max_gross_load_kg=2_000,
    up_speed_mm_s=650,
    down_speed_mm_s=800,
    load_time_s=45,
    unload_time_s=35,
    door_cycle_s=12,
)
hoist_plan = plan_hoist_trip(
    hoist, HoistTripRequest(
        id="deliver-L6", from_stop="ground", to_stop="L6",
        gross_load_kg=1_400))

result = {
    "coverage": coverage.to_dict(),
    "ranked_positions": [item.to_dict() for item in positions],
    "lift": lift_plan.to_dict(),
    "hoist": hoist_plan.to_dict(),
}
print(json.dumps(result, ensure_ascii=False, indent=2))
