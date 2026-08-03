"""All tunable thresholds for the ruleset (design §6). The 'common sense' dials.
Swapping this object (or its values) is how a future formal СП/СНиП profile is built."""

from pydantic import BaseModel, ConfigDict


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    # HAB011 — stair geometry sanity (mm)
    stair_min_run_width_mm: float = 1000.0
    stair_max_rise_mm: float = 180.0
    stair_min_going_mm: float = 250.0
    # HAB012 — core continuity
    stair_min_footprint_overlap_ratio: float = 0.50
    # HAB020 — minimum room area by function (m²)
    min_area_zhilaya_m2: float = 8.0
    min_area_kuhnya_m2: float = 5.0
    min_area_sanuzel_m2: float = 2.2
    # HAB021 — minimum room width (mm)
    min_width_zhilaya_mm: float = 2000.0
    min_width_koridor_mm: float = 900.0
    # HAB022 — minimum ceiling height (mm)
    min_ceiling_height_mm: float = 2500.0
    # HAB031 — daylight ratio window/floor (window_area_m2 : floor_area_m2)
    min_daylight_ratio: float = 1.0 / 8.0
    # HAB040 — room footprint overlap (m²)
    max_room_overlap_m2: float = 0.05
    # HAB042 — envelope gap (mm) + minimum substantial-enclosure coverage ratio
    max_envelope_gap_mm: float = 50.0
    # 0.10: with length-based coverage (clash.py) an under-walled-but-real apartment
    # (GOOD ~0.28) clears this floor while a wall-stripped or point-walled one (~0.03) does not.
    min_envelope_coverage_ratio: float = 0.10
    # HAB041/HAB042 — how close a wall must lie to a door / to the perimeter to count as
    # hosting / enclosing it (mm). Was a hidden 50.0 inside clash.py; lifted here (review fix).
    wall_snap_tol_mm: float = 50.0
    # HAB050 — column→support alignment tolerance + minimum support overlap (mm)
    struct_support_offset_mm: float = 200.0
    struct_min_support_overlap_mm: float = 300.0

    # ------------------------------------------------------------------ checker v2 dials
    # derive.py — geometric join tolerance (mm): room boundaries are offset from wall
    # centerlines by up to a wall half-thickness, so doors/windows sit up to ~150-200 mm
    # away from the boundary polyline they serve; 300 covers thick walls without
    # swallowing a whole niche.
    derive_join_tol_mm: float = 300.0
    # derive.py — morphological-closing radius when unioning rooms into the level
    # footprint (fills wall-thickness gaps between adjacent rooms).
    derive_close_tol_mm: float = 300.0
    # derive.py — a window's host wall must overlap the room boundary ring AND the level
    # envelope by at least this length (mm) to count as a verified exterior window.
    window_host_min_overlap_mm: float = 400.0
    # derive.py — ground levels: an exterior door counts as GRADE egress only when its
    # level sits within this band above the lowest occupied level (kills the "floor 3
    # is ground because a balcony/fake door is exterior" collapse).
    ground_elevation_band_mm: float = 1500.0
    # HAB060 — declared-vs-derived area mismatch tolerance: BLOCKING when BOTH exceeded.
    area_mismatch_abs_m2: float = 0.5
    area_mismatch_rel: float = 0.10
    # HAB021 v2 — width floors for kitchens / bathrooms (mm). A kitchen narrower than
    # 1700 mm cannot hold a 600 counter + passage → BLOCKING (probe F: the 1.3 m kitchen).
    min_width_kuhnya_mm: float = 1700.0
    min_width_sanuzel_mm: float = 800.0
    # HAB022 v2 — hard uninhabitable ceiling floor (BLOCKING below; WARNING below the
    # comfort floor min_ceiling_height_mm).
    min_ceiling_hard_mm: float = 2200.0
    # HAB062 — unclassified rooms at/above this derived area are flagged (WARNING).
    unclassified_min_area_m2: float = 4.0
    # verdict gate — minimum share of classified rooms for PASS to be claimable.
    min_classification_coverage: float = 0.75
    # verdict gate — minimum share of rooms with a measurable boundary polygon.
    min_measured_room_ratio: float = 0.75
    # HAB063 — floor-plate dead-void instrument: rooms-union / closed-footprint ratio
    # below this is WARNING (non-blocking v1 of the rule; courtyards legitimately dip).
    min_floorplate_coverage: float = 0.80


THRESHOLDS = Thresholds()
