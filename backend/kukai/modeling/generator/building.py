"""Parametric multi-story residential building: stack N floors, connect them with a stair
that bridges every level to the ground entrance. Produces a SpatialModel dict the checker
validates in memory (no Revit needed) — the 'typology skeleton' half of the hybrid generator.
"""
from __future__ import annotations

from kukai.modeling.generator.floor import floor, CORE_W, CORR_DEPTH

FLOOR_H = 3000.0          # floor-to-floor height (mm); rise = FLOOR_H/risers
STAIR_RISERS = 17         # 3000/17 ≈ 176 mm ≤ 180 (HAB011)
STAIR_TREAD_MM = 280.0    # ≥ 250 (HAB011)
STAIR_RUN_WIDTH_MM = 1200.0
_CORE_FOOTPRINT = [[0, 0], [CORE_W, 0], [CORE_W, CORR_DEPTH], [0, CORR_DEPTH]]


def building(n_floors: int = 5, n_apartments: int = 4, building_id: str = "gen_zhk") -> dict:
    """Generate an `n_floors`-story building with `n_apartments` units per floor.

    The stair core repeats at the same footprint on every level (vertical continuity), the
    stair runs bridge consecutive landings, and the ground floor carries the exterior entrance.
    """
    if n_floors < 1:
        raise ValueError("n_floors must be >= 1")
    if n_apartments < 1:
        raise ValueError("n_apartments must be >= 1")

    levels = [
        {"id": f"L{k}", "name": f"Этаж {k + 1}", "elevation_mm": float(k * FLOOR_H), "index": k}
        for k in range(n_floors)
    ]

    rooms: list = []
    doors: list = []
    windows: list = []
    walls: list = []
    for k in range(n_floors):
        f = floor(f"L{k}", k, n_apartments, is_ground=(k == 0))
        rooms.extend(f["rooms"])
        doors.extend(f["doors"])
        windows.extend(f["windows"])
        walls.extend(f["walls"])

    stairs: list = []

    def _stair(sid, base_lv, top_lv, base_z, top_z):
        return {
            "id": sid, "base_level_id": base_lv, "top_level_id": top_lv,
            "base_z": float(base_z), "top_z": float(top_z),
            "run_width_mm": STAIR_RUN_WIDTH_MM, "riser_count": STAIR_RISERS,
            "tread_depth_mm": STAIR_TREAD_MM, "footprint": _CORE_FOOTPRINT,
        }

    if n_floors == 1:
        stairs.append(_stair("s_0", "L0", "L0", 0.0, FLOOR_H))
    else:
        for k in range(n_floors - 1):
            stairs.append(_stair(f"s_{k}", f"L{k}", f"L{k + 1}", k * FLOOR_H, (k + 1) * FLOOR_H))

    return {
        "building_id": building_id,
        "levels": levels,
        "rooms": rooms,
        "doors": doors,
        "windows": windows,
        "stairs": stairs,
        "walls": walls,
    }
