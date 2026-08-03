"""Fixture builders for the checker (design §7).

make_good() is a valid 1-bedroom apartment on a floor with public circulation + egress
that yields 0 BLOCKING. Each bad_* deep-copies make_good() and breaks EXACTLY one thing;
the fifteen bad_* mutators are authored in the dedicated builders task (after graph, before
rules) — signatures fixed in the plan foundation; this file is their single home.

checker v2 note: the GOOD plan is GEOMETRICALLY CONSISTENT — every door location lies on
the shared boundary segment of the two rooms it declares (or on the envelope for the
entrance), every window's host wall lies on its room's envelope-exterior edge, and every
declared area equals its boundary polygon's area. The original v1 layout had a phantom
apartment-entrance door (cor↔hall at a point 1200 mm away from cor) that only a
declaration-reading checker could accept; the derivation pre-pass (derive.py) rightly
rejects such geometry, so the plan was re-laid out with hall directly above cor."""
from __future__ import annotations

import copy


def make_good() -> dict:
    """Return a fresh, valid SpatialModel dict (0 BLOCKING)."""
    return copy.deepcopy(_GOOD)


# Coordinates in mm; areas in m**2. One level L0 at elevation 0.
#
# Plan (y grows upward):
#   y 11000..13000  wc   x[0,2200]
#   y  6500..11000  kit  x[0,4000]
#   y  4000..6500                 hall x[3000,4500]   bed x[4500,8000]
#   y     0..4000   ent x[0,3000] cor  x[3000,4500]   stair x[4500,7000]
_GOOD: dict = {
    "building_id": "good_zhk_v1",
    "levels": [
        {"id": "L0", "name": "Этаж 1", "elevation_mm": 0.0, "index": 0},
    ],
    "rooms": [
        # --- public circulation ---
        {"id": "ent", "name": "Входная группа", "number": "", "level_id": "L0",
         "function": "входная_группа", "area_m2": 12.0, "height_mm": 2700.0,
         "boundary": [[0, 0], [3000, 0], [3000, 4000], [0, 4000]],
         "apartment_id": None, "has_window": True, "window_area_m2": 2.0},
        {"id": "cor", "name": "Коридор", "number": "", "level_id": "L0",
         "function": "коридор", "area_m2": 6.0, "height_mm": 2700.0,  # = polygon 1500×4000
         "boundary": [[3000, 0], [4500, 0], [4500, 4000], [3000, 4000]],
         "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
        {"id": "stair", "name": "Лестничная клетка", "number": "", "level_id": "L0",
         "function": "лестница", "area_m2": 10.0, "height_mm": 2700.0,
         "boundary": [[4500, 0], [7000, 0], [7000, 4000], [4500, 4000]],
         "apartment_id": None, "has_window": False, "window_area_m2": 0.0},
        # --- apartment A1 ---
        {"id": "hall", "name": "Прихожая", "number": "1", "level_id": "L0",
         "function": "прихожая", "area_m2": 3.75, "height_mm": 2700.0,  # 1500×2500
         "boundary": [[3000, 4000], [4500, 4000], [4500, 6500], [3000, 6500]],
         "apartment_id": "A1", "has_window": False, "window_area_m2": 0.0},
        {"id": "kit", "name": "Кухня-гостиная", "number": "2", "level_id": "L0",
         "function": "кухня", "area_m2": 18.0, "height_mm": 2700.0,
         "boundary": [[0, 6500], [4000, 6500], [4000, 11000], [0, 11000]],
         "apartment_id": "A1", "has_window": True, "window_area_m2": 3.0},
        {"id": "bed", "name": "Спальня 1", "number": "3", "level_id": "L0",
         "function": "жилая", "area_m2": 8.75, "height_mm": 2700.0,  # = polygon 3500×2500
         "boundary": [[4500, 4000], [8000, 4000], [8000, 6500], [4500, 6500]],
         "apartment_id": "A1", "has_window": True, "window_area_m2": 2.5},
        {"id": "wc", "name": "Санузел", "number": "4", "level_id": "L0",
         "function": "санузел", "area_m2": 4.4, "height_mm": 2700.0,  # = polygon 2200×2000
         "boundary": [[0, 11000], [2200, 11000], [2200, 13000], [0, 13000]],
         "apartment_id": "A1", "has_window": False, "window_area_m2": 0.0},
    ],
    "doors": [
        # every location lies ON the shared boundary of the rooms it connects (v2-real)
        {"id": "d_ext", "level_id": "L0", "location": [1500, 0], "width_mm": 1200.0,
         "from_room_id": "ent", "to_room_id": None, "is_exterior": True},
        {"id": "d_ent_cor", "level_id": "L0", "location": [3000, 2000], "width_mm": 1000.0,
         "from_room_id": "ent", "to_room_id": "cor", "is_exterior": False},
        {"id": "d_cor_stair", "level_id": "L0", "location": [4500, 2000], "width_mm": 1000.0,
         "from_room_id": "cor", "to_room_id": "stair", "is_exterior": False},
        {"id": "d_cor_hall", "level_id": "L0", "location": [3750, 4000], "width_mm": 900.0,
         "from_room_id": "cor", "to_room_id": "hall", "is_exterior": False},  # apartment entrance
        {"id": "d_hall_kit", "level_id": "L0", "location": [3500, 6500], "width_mm": 900.0,
         "from_room_id": "hall", "to_room_id": "kit", "is_exterior": False},
        {"id": "d_hall_bed", "level_id": "L0", "location": [4500, 5000], "width_mm": 900.0,
         "from_room_id": "hall", "to_room_id": "bed", "is_exterior": False},
        {"id": "d_kit_wc", "level_id": "L0", "location": [1000, 11000], "width_mm": 800.0,
         "from_room_id": "kit", "to_room_id": "wc", "is_exterior": False},
    ],
    "windows": [
        # each host wall lies on its room's envelope-exterior boundary edge (v2-real)
        {"id": "w_kit", "level_id": "L0", "host_wall_id": "wall_k", "room_id": "kit",
         "width_mm": 1800.0, "area_m2": 3.0},
        {"id": "w_bed", "level_id": "L0", "host_wall_id": "wall_b", "room_id": "bed",
         "width_mm": 1500.0, "area_m2": 2.5},
        {"id": "w_ent", "level_id": "L0", "host_wall_id": "wall_e", "room_id": "ent",
         "width_mm": 1200.0, "area_m2": 2.0},
    ],
    "stairs": [
        {"id": "s0", "base_level_id": "L0", "top_level_id": "L0", "base_z": 0.0,
         "top_z": 3000.0, "run_width_mm": 1200.0, "riser_count": 17,  # 3000/17≈176.5 ≤ 180 ⇒ HAB011 silent on GOOD
         "tread_depth_mm": 280.0,
         "footprint": [[4500, 0], [7000, 0], [7000, 4000], [4500, 4000]]},
    ],
    "walls": [
        {"id": "wall_k", "level_id": "L0", "curve": [[0, 6500], [0, 11000]],
         "height_mm": 2700.0, "is_structural": True},   # kit west edge (envelope)
        {"id": "wall_b", "level_id": "L0", "curve": [[8000, 4000], [8000, 6500]],
         "height_mm": 2700.0, "is_structural": True},   # bed east edge (envelope)
        {"id": "wall_e", "level_id": "L0", "curve": [[0, 0], [3000, 0]],
         "height_mm": 2700.0, "is_structural": True},   # ent south edge (envelope)
        {"id": "wall_w", "level_id": "L0", "curve": [[0, 11000], [0, 13000]],
         "height_mm": 2700.0, "is_structural": True},   # wc west edge (envelope)
    ],
}


def bad_room_no_door(d: dict | None = None) -> dict:
    """Break ONLY connectivity → HAB001 / HAB004 (design §7).

    Isolate the санузел 'wc': remove EVERY door whose from_room_id or to_room_id is 'wc'
    (in GOOD that is exactly d_kit_wc), so the санузел is unreachable from the building
    entrance. The room stays in the model (valid schema); only its edges are gone — 'wc' is
    the isolated room HAB001/HAB004 must flag."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["doors"] = [
        door for door in d["doors"]
        if door["from_room_id"] != "wc" and door["to_room_id"] != "wc"
    ]
    return d


def bad_apartment_into_apartment(d: dict | None = None) -> dict:
    """Break ONLY apartment isolation → HAB002 branch (a) (design §6/§7).

    Add a SECOND apartment A2 (its own прихожая hall2 + жилая bed2) whose ONLY entrance door
    connects into apartment A1's прихожая instead of into public circulation — you must pass
    through A1 to reach A2 (apartment-into-apartment nesting). A2 is sized/windowed correctly,
    so only HAB002 fires: an interior door (d_hall_hall2) joins two rooms with DIFFERENT
    non-null apartment_id ('A1' ↔ 'A2'). Geometry is consistent: hall2 sits west of hall
    (shared edge x=3000), bed2 west of hall2, its window hosted in an envelope wall."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["rooms"].append(
        {"id": "hall2", "name": "Прихожая", "number": "5", "level_id": "L0",
         "function": "прихожая", "area_m2": 5.0, "height_mm": 2700.0,  # 2000×2500
         "boundary": [[1000, 4000], [3000, 4000], [3000, 6500], [1000, 6500]],
         "apartment_id": "A2", "has_window": False, "window_area_m2": 0.0},
    )
    d["rooms"].append(
        {"id": "bed2", "name": "Спальня 1", "number": "6", "level_id": "L0",
         "function": "жилая", "area_m2": 8.75, "height_mm": 2700.0,   # 3500×2500
         "boundary": [[-2500, 4000], [1000, 4000], [1000, 6500], [-2500, 6500]],
         "apartment_id": "A2", "has_window": True, "window_area_m2": 2.5},
    )
    d["windows"].append(
        {"id": "w_bed2", "level_id": "L0", "host_wall_id": "wall_b2", "room_id": "bed2",
         "width_mm": 1500.0, "area_m2": 2.5},
    )
    d["walls"].append(
        {"id": "wall_b2", "level_id": "L0", "curve": [[-2500, 4000], [-2500, 6500]],
         "height_mm": 2700.0, "is_structural": False},   # bed2 west edge (envelope)
    )
    # A2's ONLY entrance is into A1's прихожая (apartment-into-apartment), not public circ.
    d["doors"].append(
        {"id": "d_hall_hall2", "level_id": "L0", "location": [3000, 5000],
         "width_mm": 900.0, "from_room_id": "hall", "to_room_id": "hall2",
         "is_exterior": False},
    )
    d["doors"].append(
        {"id": "d_hall2_bed2", "level_id": "L0", "location": [1000, 5000],
         "width_mm": 900.0, "from_room_id": "hall2", "to_room_id": "bed2",
         "is_exterior": False},
    )
    return d


def bad_no_egress_stair(d: dict | None = None) -> dict:
    """Break ONLY egress-to-stair → HAB003 (design §7).

    Remove every stair run AND the door wiring into the (now disconnected) stair room, so no
    path leads from an apartment entrance to a stair. On the single-level GOOD base L0 stays a
    ground level (it keeps its exterior door), so HAB010 'every occupied level reached by a
    stair' stays silent and only the egress-to-stair rule HAB003 fires (design D7).

    v2 note: with the flag ON the same fixture fails through HAB001 (the stair room is
    unreachable) while HAB003 accepts the ground-level exterior-door egress — the verdict
    stays FAIL either way; the v1 target below is asserted with the flag OFF."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["stairs"] = []
    d["doors"] = [door for door in d["doors"] if door["id"] != "d_cor_stair"]
    return d


def bad_floating_floor(d: dict | None = None) -> dict:
    """Break ONLY 'stairs reach every occupied level' → HAB010 (design §7).

    Add a second OCCUPIED level L1 (one habitable room) but NO stair connecting L0↔L1, so L1
    floats. The L0 stair keeps its valid single-level geometry, so HAB011/HAB012 stay silent;
    L1's room is sized/windowed correctly so HAB020/HAB030 stay silent — only HAB010 fires."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["levels"].append(
        {"id": "L1", "name": "Этаж 2", "elevation_mm": 3000.0, "index": 1}
    )
    d["rooms"].append(
        {"id": "bed_L1", "name": "Спальня 2", "number": "7", "level_id": "L1",
         "function": "жилая", "area_m2": 14.0, "height_mm": 2700.0,
         "boundary": [[0, 0], [3500, 0], [3500, 4000], [0, 4000]],
         "apartment_id": "A3", "has_window": True, "window_area_m2": 2.5},
    )
    d["windows"].append(
        {"id": "w_bed_L1", "level_id": "L1", "host_wall_id": "wall_bL1", "room_id": "bed_L1",
         "width_mm": 1500.0, "area_m2": 2.5},
    )
    d["walls"].append(
        {"id": "wall_bL1", "level_id": "L1", "curve": [[0, 0], [3500, 0]],
         "height_mm": 2700.0, "is_structural": False},   # bed_L1 south edge (envelope)
    )
    # Deliberately NO stair run touching L1 → L1 floats (HAB010).
    return d


def bad_steep_stair(d: dict | None = None) -> dict:
    """Break ONLY stair geometry → HAB011 (design §7).

    Narrow run (800 < 1000), steep rise (3000/10 = 300 > 180), shallow going (220 < 250).
    Footprint and level span stay valid so HAB012/HAB010 remain silent."""
    if d is None:
        d = copy.deepcopy(make_good())
    s = d["stairs"][0]
    s["run_width_mm"] = 800.0
    s["riser_count"] = 10
    s["tread_depth_mm"] = 220.0
    s["base_z"] = 0.0
    s["top_z"] = 3000.0  # rise = 3000 / 10 = 300 mm > 180
    return d


def bad_discontinuous_core(d: dict | None = None) -> dict:
    """Break ONLY stair-core plan continuity → HAB012 (design §7).

    Add a second served level L1 and a second stair run based on L1 whose footprint is
    shifted in +x so it overlaps the L0 run by < 50%. Both runs keep SANE geometry (width,
    rise, going) so HAB011/HAB010 stay silent — only HAB012 fires."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["levels"].append(
        {"id": "L1", "name": "Этаж 2", "elevation_mm": 3000.0, "index": 1}
    )
    base = d["stairs"][0]
    base["top_level_id"] = "L1"
    base["base_z"] = 0.0
    base["top_z"] = 3000.0
    base["footprint"] = [[4500, 0], [7000, 0], [7000, 4000], [4500, 4000]]
    upper = copy.deepcopy(base)
    upper["id"] = "s1"
    upper["base_level_id"] = "L1"
    upper["top_level_id"] = "L1"
    upper["base_z"] = 3000.0
    upper["top_z"] = 6000.0
    # Shifted +2400 mm in x: overlap (7000-6900)/2500 ≈ 4% << 50%.
    upper["footprint"] = [[6900, 0], [9400, 0], [9400, 4000], [6900, 4000]]
    d["stairs"].append(upper)
    return d


def bad_tiny_bedroom(d: dict | None = None) -> dict:
    """Break ONLY room area → HAB020 (design §7).

    Shrink the спальня (жилая) to 4 m² (< 8 m² minimum). Boundary is shrunk consistently so
    the room stays a valid rectangle (declared area == polygon area — no HAB060 noise), its
    door stays on the shared edge, and its window's host wall moves to the room's NEW
    envelope-exterior east edge (so only the area rule fires)."""
    if d is None:
        d = copy.deepcopy(make_good())
    for room in d["rooms"]:
        if room["id"] == "bed":
            room["area_m2"] = 4.0
            # 2000 x 2000 mm = 4 m² rectangle anchored at the bedroom's origin.
            room["boundary"] = [[4500, 4000], [6500, 4000], [6500, 6000], [4500, 6000]]
    for wall in d["walls"]:
        if wall["id"] == "wall_b":
            wall["curve"] = [[6500, 4000], [6500, 6000]]   # bed's new east edge (envelope)
    return d


def bad_narrow_corridor(d: dict | None = None) -> dict:
    """Break ONLY room width → HAB021 (design §7).

    Collapse the коридор to ~700 mm wide (< 900 mm minimum) by moving its WEST edge to
    x=3800 and growing the entrance group to meet it (so every door still sits on a real
    shared edge and declared areas still match the polygons). Only HAB021 fires."""
    if d is None:
        d = copy.deepcopy(make_good())
    for room in d["rooms"]:
        if room["id"] == "ent":
            # ent grows east to x=3800: 3.8 x 4.0 = 15.2 m².
            room["boundary"] = [[0, 0], [3800, 0], [3800, 4000], [0, 4000]]
            room["area_m2"] = 15.2
        if room["id"] == "cor":
            # x in [3800, 4500] (700 mm wide), y in [0, 4000]: 0.7 x 4.0 = 2.8 m².
            room["boundary"] = [[3800, 0], [4500, 0], [4500, 4000], [3800, 4000]]
            room["area_m2"] = 2.8
    for door in d["doors"]:
        if door["id"] == "d_ent_cor":
            door["location"] = [3800, 2000]     # the moved shared edge ent|cor
        if door["id"] == "d_cor_hall":
            door["location"] = [4000, 4000]     # still on cor-top ∩ hall-bottom
    return d


def bad_low_ceiling(d: dict | None = None) -> dict:
    """Break ONLY ceiling height → HAB022 (design §7).

    Lower the спальня's height to 2200 mm (< 2500 mm minimum). Area/width/window/connectivity
    untouched so only HAB022 fires."""
    if d is None:
        d = copy.deepcopy(make_good())
    for room in d["rooms"]:
        if room["id"] == "bed":
            room["height_mm"] = 2200.0
    return d


def bad_bedroom_no_window(d: dict | None = None) -> dict:
    """Break ONLY daylight presence → HAB030 (design §7).

    The спальня (жилая) loses its exterior window: clear has_window/window_area_m2 on the
    room AND drop its windows[] entry so the model stays internally consistent. Exactly one
    habitable room becomes windowless — nothing else changes."""
    if d is None:
        d = copy.deepcopy(make_good())
    for room in d["rooms"]:
        if room["id"] == "bed":
            room["has_window"] = False
            room["window_area_m2"] = 0.0
    d["windows"] = [w for w in d["windows"] if w["id"] != "w_bed"]
    return d


def bad_low_daylight(d: dict | None = None) -> dict:
    """Break ONLY daylight RATIO → HAB031 (INFO) (design §6/§7).

    The спальня KEEPS a window (so HAB030 'has a window' stays silent), but its glazing area is
    shrunk to 1.0 m² against an 8.75 m² floor → ratio 0.114 < 1:8 (0.125). Shrink the room's
    window_area_m2 AND the matching windows[] entry so the model stays self-consistent. Exactly
    one room's glazing ratio drops — only HAB031 fires (INFO, never blocking)."""
    if d is None:
        d = copy.deepcopy(make_good())
    for room in d["rooms"]:
        if room["id"] == "bed":
            room["has_window"] = True
            room["window_area_m2"] = 1.0
    for w in d["windows"]:
        if w["id"] == "w_bed":
            w["area_m2"] = 1.0
            w["width_mm"] = 600.0
    return d


def bad_overlapping_rooms(d: dict | None = None) -> dict:
    """Break ONLY planar non-overlap → HAB040 (design §7).

    Move the спальня's footprint so it overlaps the кухня-гостиная by well over 0.05 m².
    The bedroom keeps a valid area_m2/height/window (so HAB020/HAB022/HAB030 stay silent in
    v1); only the boundary moves into the kitchen, isolating HAB040 (v1). Under v2 the moved
    room honestly also produces phantom-door/unverified-window findings — geometry broke in
    more than one way, and the derivation layer says so.

    кухня-гостиная boundary: x[0,4000] y[6500,11000]. We shove the bedroom to
    x[1000,4500] y[7000,9500] (3500×2500 = 8.75 m², area stays consistent) → a
    3000 x 2500 mm overlap (7.5 m² >> 0.05 m²)."""
    if d is None:
        d = copy.deepcopy(make_good())
    for room in d["rooms"]:
        if room["id"] == "bed":
            room["boundary"] = [[1000, 7000], [4500, 7000], [4500, 9500], [1000, 9500]]
    return d


def bad_door_in_wall(d: dict | None = None) -> dict:
    """Break ONLY door hosting → HAB041 (WARNING) (design §6/§7).

    Add ONE door that swings into a blank wall: its location sits on wall_e
    ([[0,0],[3000,0]]) but it connects NO rooms (from/to both None) and is not exterior — so
    it cannot swing into a room. Rooms/walls untouched; only this one door is malformed, so
    only HAB041 fires (WARNING, never blocking)."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["doors"].append(
        {"id": "d_inwall", "level_id": "L0", "location": [1500, 0], "width_mm": 900.0,
         "from_room_id": None, "to_room_id": None, "is_exterior": False},
    )
    return d


def bad_open_envelope(d: dict | None = None) -> dict:
    """Break ONLY envelope enclosure → HAB042 (WARNING in v1; BLOCKING in v2) (design §6/§7).

    Remove EVERY wall, so the apartment's envelope perimeter is covered by walls+openings at
    ~0% — far below the v1 coverage floor (thr.min_envelope_coverage_ratio). Rooms/doors/
    windows stay valid (so HAB041 'door hosted in wall' still tolerates interior doors with no
    declared wall per its v1 rule), isolating HAB042. Under v2 the windows also lose their
    hosts → the daylight/consistency rules fire too (a wall-stripped building IS multiply
    broken; the wall-stripped probe G must FAIL)."""
    if d is None:
        d = copy.deepcopy(make_good())
    d["walls"] = []
    return d


def bad_floating_column(d: dict | None = None) -> dict:
    """Break ONLY vertical structural continuity → HAB050 (WARNING) (design §6/§7).

    Add a second occupied level L1 and ONE structural wall hosted on L1 whose plan position
    has NO structural wall beneath it on L0 — a mid-air load path. L1 is reached by the
    existing stair (its top_level_id is repointed to L1) so it is NOT a floating floor
    (HAB010 stays silent); the new wall is the only structural defect, isolating HAB050
    (WARNING, never blocking)."""
    if d is None:
        d = copy.deepcopy(make_good())
    # Second occupied level, reached by the existing stair (so HAB010 stays silent).
    d["levels"].append(
        {"id": "L1", "name": "Этаж 2", "elevation_mm": 3000.0, "index": 1}
    )
    d["stairs"][0]["top_level_id"] = "L1"
    d["stairs"][0]["base_z"] = 0.0
    d["stairs"][0]["top_z"] = 3000.0
    # A structural wall on L1 sitting in plan over open space on L0 (nothing beneath it):
    # x in [12000, 15000] — far outside any L0 structural-wall footprint.
    d["walls"].append(
        {"id": "wall_float", "level_id": "L1",
         "curve": [[12000, 0], [15000, 0]],
         "height_mm": 2700.0, "is_structural": True},
    )
    return d
