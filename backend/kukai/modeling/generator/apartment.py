"""Parametric apartment-unit typology for the generator.

Produces tiled, habitable apartment units (rooms + interior doors + windows + exterior walls)
that satisfy the per-apartment checker rules (HAB002/004/020/021/022/030) BY CONSTRUCTION.
Coordinates in mm; the unit's entrance edge is its local y=y0 (the corridor side), so the
прихожая sits on the corridor and the unit physically abuts the corridor.
"""
from __future__ import annotations

CEIL_MM = 2700.0


def _room(rid, name, func, level_id, area_m2, boundary, apartment_id,
          has_window=False, window_area_m2=0.0):
    return {
        "id": rid, "name": name, "number": "", "level_id": level_id,
        "function": func, "area_m2": area_m2, "height_mm": CEIL_MM,
        "boundary": boundary, "apartment_id": apartment_id,
        "has_window": has_window, "window_area_m2": window_area_m2,
    }


def _door(did, level_id, loc, from_id, to_id, width=900.0, exterior=False):
    return {
        "id": did, "level_id": level_id, "location": list(loc), "width_mm": width,
        "from_room_id": from_id, "to_room_id": to_id, "is_exterior": exterior,
    }


def apartment_1br(apt_id: str, x0: float, y0: float, level_id: str, corridor_id: str,
                  *, w: float = 6000.0, h: float = 8000.0) -> dict:
    """A 1-bedroom apartment tiling [x0, x0+w] × [y0, y0+h] on `level_id`.

    Entrance is on the y0 (corridor) edge: прихожая → corridor door `corridor_id`. Returns a
    dict with rooms / doors / windows / walls; all room ids are prefixed by `apt_id` so a whole
    building's elements stay unique. The four rooms tile the footprint exactly (no overlaps,
    no gaps): прихожая + санузел (left strip) + кухня-гостиная (bottom-right) + спальня (top).
    """
    hall = f"{apt_id}_hall"
    wc = f"{apt_id}_wc"
    kit = f"{apt_id}_kit"
    bed = f"{apt_id}_bed"
    x1, y1 = x0 + w, y0 + h

    rooms = [
        _room(hall, "Прихожая", "прихожая", level_id, 4.0,
              [[x0, y0], [x0 + 2000, y0], [x0 + 2000, y0 + 2000], [x0, y0 + 2000]], apt_id),
        _room(wc, "Санузел", "санузел", level_id, 4.0,
              [[x0, y0 + 2000], [x0 + 2000, y0 + 2000], [x0 + 2000, y0 + 4000], [x0, y0 + 4000]], apt_id),
        _room(kit, "Кухня-гостиная", "кухня", level_id, 16.0,
              [[x0 + 2000, y0], [x1, y0], [x1, y0 + 4000], [x0 + 2000, y0 + 4000]], apt_id,
              has_window=True, window_area_m2=2.5),
        _room(bed, "Спальня", "жилая", level_id, 24.0,
              [[x0, y0 + 4000], [x1, y0 + 4000], [x1, y1], [x0, y1]], apt_id,
              has_window=True, window_area_m2=3.0),
    ]

    doors = [
        # entrance: прихожая ↔ corridor (the apartment's single public entrance)
        _door(f"{apt_id}_d_ent", level_id, (x0 + 1000, y0), hall, corridor_id, width=900.0),
        _door(f"{apt_id}_d_hall_wc", level_id, (x0 + 1000, y0 + 2000), hall, wc, width=800.0),
        _door(f"{apt_id}_d_hall_kit", level_id, (x0 + 2000, y0 + 1000), hall, kit, width=900.0),
        _door(f"{apt_id}_d_kit_bed", level_id, (x0 + 3000, y0 + 4000), kit, bed, width=900.0),
    ]

    w_right = f"{apt_id}_wall_right"
    w_top = f"{apt_id}_wall_top"
    w_left = f"{apt_id}_wall_left"
    windows = [
        {"id": f"{apt_id}_w_kit", "level_id": level_id, "host_wall_id": w_right,
         "room_id": kit, "width_mm": 1800.0, "area_m2": 2.5},
        {"id": f"{apt_id}_w_bed", "level_id": level_id, "host_wall_id": w_top,
         "room_id": bed, "width_mm": 2000.0, "area_m2": 3.0},
    ]

    walls = [
        {"id": w_left, "level_id": level_id, "curve": [[x0, y0], [x0, y1]],
         "height_mm": CEIL_MM, "is_structural": True},
        {"id": w_right, "level_id": level_id, "curve": [[x1, y0], [x1, y1]],
         "height_mm": CEIL_MM, "is_structural": True},
        {"id": w_top, "level_id": level_id, "curve": [[x0, y1], [x1, y1]],
         "height_mm": CEIL_MM, "is_structural": True},
    ]

    return {"rooms": rooms, "doors": doors, "windows": windows, "walls": walls}
