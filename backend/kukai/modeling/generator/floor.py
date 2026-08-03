"""Parametric floor: stair core + corridor + N apartment units placed along the corridor.

The corridor strip's far edge abuts the units' entrance edge, so each unit's прихожая opens
directly onto the corridor (a coherent, tiled plan). Ground floor adds an входная группа with
the building's exterior entrance. Public circulation: ent → stair ↔ corridor ↔ each apartment.
"""
from __future__ import annotations

from kukai.modeling.generator.apartment import apartment_1br, _room, _door

CORE_W = 3000.0       # stair / entrance core width
CORR_DEPTH = 2000.0   # corridor depth
APT_W = 6000.0        # apartment unit width
APT_H = 8000.0        # apartment unit depth


def floor(level_id: str, level_index: int, n_apartments: int, *, is_ground: bool = False) -> dict:
    """Build one floor. Returns rooms/doors/windows/walls plus the corridor id and the stair
    landing-room id (the лестница room the building's stair run attaches to on this level)."""
    cor_id = f"cor_{level_index}"
    stair_id = f"stair_{level_index}"
    rooms: list = []
    doors: list = []
    windows: list = []
    walls: list = []

    cor_len = n_apartments * APT_W
    # stair landing (left core)
    rooms.append(_room(stair_id, "Лестничная клетка", "лестница", level_id, 6.0,
                       [[0, 0], [CORE_W, 0], [CORE_W, CORR_DEPTH], [0, CORR_DEPTH]], None))
    # corridor strip spanning all units, far edge (y=CORR_DEPTH) abuts the units
    rooms.append(_room(cor_id, "Коридор", "коридор", level_id, round(cor_len * CORR_DEPTH / 1e6, 1),
                       [[CORE_W, 0], [CORE_W + cor_len, 0],
                        [CORE_W + cor_len, CORR_DEPTH], [CORE_W, CORR_DEPTH]], None))
    doors.append(_door(f"d_cor_stair_{level_index}", level_id, (CORE_W, CORR_DEPTH / 2.0),
                       cor_id, stair_id, width=1100.0))

    if is_ground:
        ent_id = f"ent_{level_index}"
        rooms.append(_room(ent_id, "Входная группа", "входная_группа", level_id, 6.0,
                           [[0, -CORR_DEPTH], [CORE_W, -CORR_DEPTH], [CORE_W, 0], [0, 0]], None,
                           has_window=True, window_area_m2=2.0))
        # building entrance to OUTSIDE
        doors.append(_door(f"d_ext_{level_index}", level_id, (CORE_W / 2.0, -CORR_DEPTH),
                           ent_id, None, width=1300.0, exterior=True))
        # ent abuts the stair core (shared edge y=0) → into public circulation
        doors.append(_door(f"d_ent_stair_{level_index}", level_id, (CORE_W / 2.0, 0.0),
                           ent_id, stair_id, width=1200.0))
        # exterior wall hosting the entrance door (so HAB041 is satisfied)
        walls.append({"id": f"wall_ent_{level_index}", "level_id": level_id,
                      "curve": [[0, -CORR_DEPTH], [CORE_W, -CORR_DEPTH]],
                      "height_mm": 2700.0, "is_structural": True})

    # apartments along the corridor
    for i in range(n_apartments):
        apt_id = f"apt_{level_index}_{i}"
        x0 = CORE_W + i * APT_W
        unit = apartment_1br(apt_id, x0, CORR_DEPTH, level_id, cor_id, w=APT_W, h=APT_H)
        rooms.extend(unit["rooms"])
        doors.extend(unit["doors"])
        windows.extend(unit["windows"])
        walls.extend(unit["walls"])

    return {
        "rooms": rooms, "doors": doors, "windows": windows, "walls": walls,
        "corridor_id": cor_id, "stair_landing_id": stair_id,
    }
