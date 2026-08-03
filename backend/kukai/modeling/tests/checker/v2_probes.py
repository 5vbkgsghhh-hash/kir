"""Adversarial probes for the building-correctness checker (roadmap 'Checker correctness
& trust' front). Run twice:

  BEFORE (current /opt code, v1):
    PYTHONPATH=/opt/kukai-rebuild1/backend \
      /opt/kukai-rebuild1/backend/venv/bin/python probes.py

  AFTER (patched tree, v2 ON):
    KUKAI_CHECKER_V2=1 PYTHONPATH=/root/kukai-refactor-out/step12/patched \
      /opt/kukai-rebuild1/backend/venv/bin/python probes.py

Each probe prints PASSED/FAILED (+verdict when available). Trust bar: every probe that
prints passed=True BEFORE must print passed=False AFTER; the KNOWN-GOOD cases must stay
passed=True AFTER (no false BLOCKING).
"""
from __future__ import annotations

import copy
import json
import os
import sys

from kukai.modeling.checker.engine import run
from kukai.modeling.checker.spatial_model import SpatialModel


def _report(tag: str, model_dict: dict, expect_flip: bool = True) -> None:
    rep = run(SpatialModel.model_validate(model_dict))
    verdict = getattr(rep, "verdict", None)
    ids = sorted({v.rule_id for v in rep.blocking})
    print(f"{tag:34s} passed={rep.passed!s:5s} verdict={getattr(verdict, 'value', 'n/a'):13s} "
          f"blocking={ids}")


def _room(rid, name, func, lvl, area, boundary, *, height=2700.0, apt=None,
          win=False, win_area=0.0, number=""):
    return {"id": rid, "name": name, "number": number, "level_id": lvl, "function": func,
            "area_m2": area, "height_mm": height, "boundary": boundary,
            "apartment_id": apt, "has_window": win, "window_area_m2": win_area}


def _rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


# ---------------------------------------------------------------- probe B: empty model
def probe_empty():
    return {"building_id": "empty_extraction", "levels": [], "rooms": [], "doors": [],
            "windows": [], "stairs": [], "walls": []}


# ------------------------------------------- probe A: declared area lies over geometry
def probe_declared_area_lie():
    """Bedroom DECLARES 8.75 m² but its boundary polygon is 1.0 m² (1000x1000)."""
    from kukai.modeling.checker.fixtures.builders import make_good
    d = make_good()
    for r in d["rooms"]:
        if r["id"] == "bed":
            # keep the declared area, shrink the real polygon to a 1 m² closet anchored
            # at the bedroom's own origin so its door stays on the shared edge.
            x0, y0 = r["boundary"][0]
            r["boundary"] = _rect(x0, y0, x0 + 1000, y0 + 1000)
    return d


# --------------------------------------------------- probe I: fabricated shaft window
def probe_fabricated_window():
    """Windowless bedroom 'repaired' by a window hosted in NOTHING (host_wall_id=None) —
    exactly what generator/fix_loop._fix_hab030 writes."""
    from kukai.modeling.checker.fixtures.builders import make_good
    d = make_good()
    d["windows"] = [w for w in d["windows"] if w["id"] != "w_bed"]
    for r in d["rooms"]:
        if r["id"] == "bed":
            r["has_window"] = True          # the declared scalar the rules read
            r["window_area_m2"] = 2.5
    d["windows"].append({"id": "w_fake", "level_id": "L0", "host_wall_id": None,
                         "room_id": "bed", "width_mm": 1500.0, "area_m2": 2.5})
    return d


# ------------------------------------------------------------- probe F: 1.3 m kitchen
def probe_narrow_kitchen():
    """Kitchen squeezed to a 1300 mm-deep strip (4.0 x 1.3 = 5.2 m², still over the area
    floor) with every door/window kept geometrically attached — the ONLY defect is width."""
    from kukai.modeling.checker.fixtures.builders import make_good
    d = make_good()
    for r in d["rooms"]:
        if r["id"] == "kit":
            r["boundary"] = _rect(0, 6500, 4000, 7800)   # 4000 x 1300
            r["area_m2"] = 5.2
        if r["id"] == "wc":
            r["boundary"] = _rect(0, 7800, 2200, 9800)   # slides down to keep the shared edge
    for door in d["doors"]:
        if door["id"] == "d_kit_wc":
            door["location"] = [1000, 7800]
    for w in d["walls"]:
        if w["id"] == "wall_k":
            w["curve"] = [[0, 6500], [0, 7800]]
        if w["id"] == "wall_w":
            w["curve"] = [[0, 7800], [0, 9800]]
    return d


# ------------------------------- probe G: all walls deleted, live-extraction shape
def probe_walls_deleted_live_shape():
    from kukai.modeling.checker.fixtures.builders import make_good
    d = make_good()
    d["walls"] = []
    for r in d["rooms"]:
        r["apartment_id"] = None            # live extraction has no apartment stamps
    return d


# ------------------------------------------------- probe E2: unclassified room names
def probe_unclassified_names():
    """Roadmap probe E2: rooms named 'Bedroom 1' (2 m², windowless, 1.2 m ceiling) and
    'Kitchen' (1.5 m²) — the 19-entry RU lexicon classifies both ПРОЧЕЕ, and ПРОЧЕЕ has
    no thresholds, so v1 checks nothing (HAB020/021/022-hard/030 all bypassed)."""
    from kukai.modeling.checker.fixtures.builders import make_good
    d = make_good()
    for r in d["rooms"]:
        if r["id"] == "bed":
            x0, y0 = r["boundary"][0]
            r.update(name="Bedroom 1", function="прочее", area_m2=2.0, height_mm=1200.0,
                     has_window=False, window_area_m2=0.0,
                     boundary=_rect(x0, y0, x0 + 1000, y0 + 2000))
        if r["id"] == "kit":
            x0, y0 = r["boundary"][0]
            r.update(name="Kitchen", function="прочее", area_m2=1.5, height_mm=1200.0,
                     has_window=False, window_area_m2=0.0,
                     boundary=_rect(x0, y0, x0 + 1000, y0 + 1500))
    d["windows"] = [w for w in d["windows"] if w["id"] not in ("w_bed", "w_kit")]
    return d


# ------------------------------------ probe K: 300 mm stair with nulls (live shape)
def probe_unbuildable_stair():
    lvl = [{"id": "L0", "name": "Э1", "elevation_mm": 0.0, "index": 0},
           {"id": "L1", "name": "Э2", "elevation_mm": 6000.0, "index": 1}]
    rooms = [
        _room("ent", "Входная группа", "входная_группа", "L0", 12.0, _rect(0, 0, 3000, 4000)),
        _room("st0", "Лестничная клетка", "лестница", "L0", 10.0, _rect(3000, 0, 5500, 4000)),
        _room("st1", "Лестничная клетка", "лестница", "L1", 10.0, _rect(3000, 0, 5500, 4000)),
        _room("bed1", "Спальня", "жилая", "L1", 10.0, _rect(5500, 0, 8000, 4000),
              apt="A1", win=True, win_area=2.5),
        _room("hall1", "Прихожая", "прихожая", "L1", 8.0, _rect(8000, 0, 10000, 4000),
              apt="A1"),
    ]
    # hall is entered from the landing; bed from hall (geометрия согласована)
    doors = [
        {"id": "dx", "level_id": "L0", "location": [1500, 0], "width_mm": 1200.0,
         "from_room_id": "ent", "to_room_id": None, "is_exterior": True},
        {"id": "d0", "level_id": "L0", "location": [3000, 2000], "width_mm": 900.0,
         "from_room_id": "ent", "to_room_id": "st0", "is_exterior": False},
        {"id": "d1", "level_id": "L1", "location": [5500, 2000], "width_mm": 900.0,
         "from_room_id": "st1", "to_room_id": "bed1", "is_exterior": False},
        {"id": "d2", "level_id": "L1", "location": [8000, 2000], "width_mm": 900.0,
         "from_room_id": "bed1", "to_room_id": "hall1", "is_exterior": False},
    ]
    windows = [{"id": "w1", "level_id": "L1", "host_wall_id": "wb", "room_id": "bed1",
                "width_mm": 1500.0, "area_m2": 2.5}]
    walls = [{"id": "wb", "level_id": "L1", "curve": [[5500, 4000], [8000, 4000]],
              "height_mm": 2700.0, "is_structural": False}]
    stairs = [{"id": "s300", "base_level_id": "L0", "top_level_id": "L1", "base_z": 0.0,
               "top_z": 6000.0, "run_width_mm": 300.0, "riser_count": None,
               "tread_depth_mm": None,
               "footprint": _rect(3000, 0, 5500, 4000)}]
    return {"building_id": "stair300", "levels": lvl, "rooms": rooms, "doors": doors,
            "windows": windows, "stairs": stairs, "walls": walls}


# --------------------------- probe D2: sealed 5-story building, one fake street exit
def probe_sealed_five_story():
    """No door touches the building envelope. One floor-3 corridor door has a null side
    (unplaced closet) → the v1 extractor shape declares it is_exterior=True. v1: floor 3
    becomes 'ground', everything 'has egress', passed=True."""
    levels, rooms, doors, windows, walls, stairs = [], [], [], [], [], []
    for i in range(5):
        lid = f"L{i}"
        z = 3000.0 * i
        levels.append({"id": lid, "name": f"Этаж {i+1}", "elevation_mm": z, "index": i})
        # plan: corridor strip + stair core + apartment (hall,bed,kit,wc) — geometrically joined
        rooms += [
            _room(f"cor{i}", "Коридор", "коридор", lid, 12.0, _rect(0, 0, 8000, 1500)),
            _room(f"st{i}", "Лестничная клетка", "лестница", lid, 10.0,
                  _rect(8000, 0, 10500, 4000)),
            _room(f"hall{i}", "Прихожая", "прихожая", lid, 4.5, _rect(0, 1500, 3000, 3000)),
            _room(f"bed{i}", "Спальня", "жилая", lid, 10.5, _rect(0, 3000, 3000, 6500),
                  win=True, win_area=2.5),
            _room(f"kit{i}", "Кухня", "кухня", lid, 10.5, _rect(3000, 1500, 6000, 5000),
                  win=True, win_area=2.5),
            _room(f"wc{i}", "Санузел", "санузел", lid, 4.5, _rect(3000, 5000, 6000, 6500)),
        ]
        doors += [
            {"id": f"d_cor_st{i}", "level_id": lid, "location": [8000, 750],
             "width_mm": 1000.0, "from_room_id": f"cor{i}", "to_room_id": f"st{i}",
             "is_exterior": False},
            {"id": f"d_cor_hall{i}", "level_id": lid, "location": [1500, 1500],
             "width_mm": 900.0, "from_room_id": f"cor{i}", "to_room_id": f"hall{i}",
             "is_exterior": False},
            {"id": f"d_hall_bed{i}", "level_id": lid, "location": [1500, 3000],
             "width_mm": 900.0, "from_room_id": f"hall{i}", "to_room_id": f"bed{i}",
             "is_exterior": False},
            {"id": f"d_hall_kit{i}", "level_id": lid, "location": [3000, 2200],
             "width_mm": 900.0, "from_room_id": f"hall{i}", "to_room_id": f"kit{i}",
             "is_exterior": False},
            {"id": f"d_kit_wc{i}", "level_id": lid, "location": [4500, 5000],
             "width_mm": 800.0, "from_room_id": f"kit{i}", "to_room_id": f"wc{i}",
             "is_exterior": False},
        ]
        # real windows hosted in real envelope walls so light/consistency stay clean
        walls += [
            {"id": f"wb{i}", "level_id": lid, "curve": [[0, 3000], [0, 6500]],
             "height_mm": 2700.0, "is_structural": True},
            {"id": f"wk{i}", "level_id": lid, "curve": [[6000, 1500], [6000, 5000]],
             "height_mm": 2700.0, "is_structural": True},
        ]
        windows += [
            {"id": f"w_bed{i}", "level_id": lid, "host_wall_id": f"wb{i}",
             "room_id": f"bed{i}", "width_mm": 1500.0, "area_m2": 2.5},
            {"id": f"w_kit{i}", "level_id": lid, "host_wall_id": f"wk{i}",
             "room_id": f"kit{i}", "width_mm": 1500.0, "area_m2": 2.5},
        ]
        if i > 0:
            stairs.append({"id": f"s{i}", "base_level_id": f"L{i-1}", "top_level_id": lid,
                           "base_z": z - 3000.0, "top_z": z, "run_width_mm": 1200.0,
                           "riser_count": 17, "tread_depth_mm": 280.0,
                           "footprint": _rect(8000, 0, 10500, 4000)})
    # THE fake exit: a floor-3 corridor door to an UNPLACED closet — extractor v1 shape:
    # one null side ⇒ is_exterior=True. Its location is interior (not on the envelope).
    doors.append({"id": "d_fake_exit", "level_id": "L3", "location": [4000, 750],
                  "width_mm": 900.0, "from_room_id": "cor3", "to_room_id": None,
                  "is_exterior": True})
    return {"building_id": "sealed5", "levels": levels, "rooms": rooms, "doors": doors,
            "windows": windows, "stairs": stairs, "walls": walls}


# ------------------------------------------------- probe C: fix-loop self-certifies
def probe_fix_loop_self_certification():
    """The v1 SCALAR fixers (has_window=True + a host-less window) are injected
    explicitly: BEFORE they certify the fake repair (passed=True, 1 window hosted in
    nothing); AFTER (v2) the same edits can no longer move the verdict."""
    from kukai.modeling.checker.fixtures.builders import bad_bedroom_no_window
    from kukai.modeling.generator.fix_loop import DEFAULT_FIXERS, run_loop
    res = run_loop(bad_bedroom_no_window(), fixers=DEFAULT_FIXERS)
    fake = [w for w in res.model["windows"] if w.get("host_wall_id") in (None, "")]
    print(f"{'C fix-loop self-certify':34s} passed={res.passed!s:5s} "
          f"windows_hosted_in_nothing={len(fake)}")


# ------------------------------------------- KNOWN-GOOD controls (must stay passing)
def control_good():
    from kukai.modeling.checker.fixtures.builders import make_good
    return make_good()


def control_tech_room():
    """Real building pattern: an Электрощитовая off the corridor (probe H) — must NOT
    produce BLOCKING HAB004 ('apartment without прихожая')."""
    from kukai.modeling.checker.fixtures.builders import make_good
    d = make_good()
    d["rooms"].append(_room("tech", "Электрощитовая", "тех", "L0", 3.0,
                            _rect(3000, -2000, 4500, 0)))
    d["doors"].append({"id": "d_cor_tech", "level_id": "L0", "location": [3750, 0],
                       "width_mm": 900.0, "from_room_id": "cor", "to_room_id": "tech",
                       "is_exterior": False})
    return d


def control_one_story_no_stair():
    """Valid 1-story house with direct exterior egress and NO stair (probe M) — must NOT
    produce BLOCKING HAB003."""
    lvl = [{"id": "L0", "name": "Э1", "elevation_mm": 0.0, "index": 0}]
    rooms = [
        _room("hall", "Прихожая", "прихожая", "L0", 6.0, _rect(0, 0, 2000, 3000), apt="A1"),
        _room("kit", "Кухня", "кухня", "L0", 9.0, _rect(2000, 0, 5000, 3000), apt="A1",
              win=True, win_area=2.0),
        _room("bed", "Спальня", "жилая", "L0", 10.5, _rect(0, 3000, 3000, 6500), apt="A1",
              win=True, win_area=2.5),
        _room("wc", "Санузел", "санузел", "L0", 3.5, _rect(3000, 3000, 5000, 4750), apt="A1"),
    ]
    doors = [
        {"id": "d_ext", "level_id": "L0", "location": [1000, 0], "width_mm": 1000.0,
         "from_room_id": "hall", "to_room_id": None, "is_exterior": True},
        {"id": "d_hall_kit", "level_id": "L0", "location": [2000, 1500], "width_mm": 900.0,
         "from_room_id": "hall", "to_room_id": "kit", "is_exterior": False},
        {"id": "d_hall_bed", "level_id": "L0", "location": [1000, 3000], "width_mm": 900.0,
         "from_room_id": "hall", "to_room_id": "bed", "is_exterior": False},
        {"id": "d_bed_wc", "level_id": "L0", "location": [3000, 3800], "width_mm": 800.0,
         "from_room_id": "bed", "to_room_id": "wc", "is_exterior": False},
    ]
    walls = [
        {"id": "w_e", "level_id": "L0", "curve": [[0, 0], [2000, 0]],
         "height_mm": 2700.0, "is_structural": True},
        {"id": "w_k", "level_id": "L0", "curve": [[2000, 0], [5000, 0]],
         "height_mm": 2700.0, "is_structural": True},
        {"id": "w_b", "level_id": "L0", "curve": [[0, 6500], [3000, 6500]],
         "height_mm": 2700.0, "is_structural": True},
    ]
    windows = [
        {"id": "w_kit", "level_id": "L0", "host_wall_id": "w_k", "room_id": "kit",
         "width_mm": 1400.0, "area_m2": 2.0},
        {"id": "w_bed", "level_id": "L0", "host_wall_id": "w_b", "room_id": "bed",
         "width_mm": 1500.0, "area_m2": 2.5},
    ]
    return {"building_id": "one_story", "levels": lvl, "rooms": rooms, "doors": doors,
            "windows": windows, "stairs": [], "walls": walls}


def main():
    print(f"KUKAI_CHECKER_V2={os.environ.get('KUKAI_CHECKER_V2', '0')}  "
          f"code={__import__('kukai.modeling.checker.engine', fromlist=['x']).__file__}")
    print("--- adversarial (BEFORE: all passed=True; AFTER: must all be passed=False) ---")
    _report("B  empty model", probe_empty())
    _report("A  declared-area lie", probe_declared_area_lie())
    _report("I  fabricated shaft window", probe_fabricated_window())
    _report("F  1.3 m kitchen", probe_narrow_kitchen())
    _report("G  all walls deleted (live)", probe_walls_deleted_live_shape())
    _report("E2 unclassified room names", probe_unclassified_names())
    _report("K  300mm stair, null geometry", probe_unbuildable_stair())
    _report("D2 sealed 5-story, fake exit", probe_sealed_five_story())
    probe_fix_loop_self_certification()
    print("--- known-good controls ---")
    _report("GOOD make_good() (True->True)", control_good())
    _report("H  тех-room (False->True)", control_tech_room())
    _report("M  1-story no stair (F->True)", control_one_story_no_stair())


if __name__ == "__main__":
    main()
