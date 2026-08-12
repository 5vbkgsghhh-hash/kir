"""Live-model extractor: run the read-only C# extractor (extractor.cs) on a Revit doc via the
op_revit operator channel, then NORMALIZE the raw payload into a checker SpatialModel — assigning
each room's RoomFunction with classify.py (the §4 normalization seam; this is where classify.py
goes live). Only the operator-authorized device is permitted (safety).

`normalize()` is pure (no I/O) and unit-tested without a live model; `extract()` does the live
read-only exec.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from kukai.modeling.checker.classify import classify_room
from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import SpatialModel

VPY = "/opt/kukai-rebuild1/backend/venv/bin/python"
OP = "/opt/kukai-rebuild1/scripts/op_revit.py"
AUTHORIZED = {"a6d7d14340bc599817ae7e6896182ca0"}   # Музе only — never another user's model
_CS = Path(__file__).with_name("extractor.cs")


def _synthesize_stairs(rooms: list, levels: list) -> list:
    """Infer vertical stair runs from лестница (stair-landing) rooms that stack across consecutive
    levels. The materializer creates an aligned лестница room per floor but no Stair ELEMENT, so
    without this the floors aren't vertically connected in the checker's graph (HAB010 + upper-floor
    egress would fail). Each aligned pair on consecutive levels becomes a Stair bridging them.
    """
    lev = {l["id"]: l for l in levels}
    landings = [r for r in rooms if r.get("function") == "лестница" and r.get("boundary")]
    groups: dict = {}
    for r in landings:
        b = r["boundary"]
        cx = round(sum(p[0] for p in b) / len(b) / 500.0) * 500   # group by ~aligned footprint
        cy = round(sum(p[1] for p in b) / len(b) / 500.0) * 500
        groups.setdefault((cx, cy), []).append(r)
    v2 = checker_v2_enabled()
    out = []
    for grp in groups.values():
        grp.sort(key=lambda r: lev.get(r["level_id"], {}).get("elevation_mm", 0.0))
        for i in range(len(grp) - 1):
            lo, hi = grp[i], grp[i + 1]
            lo_l, hi_l = lev.get(lo["level_id"]), lev.get(hi["level_id"])
            if not lo_l or not hi_l:
                continue
            if v2:
                # v2 (extract truth, not fabrication): the inferred link keeps the graph
                # connected but carries NO invented dimensions — kind='inferred' makes
                # HAB011 refuse to certify it (WARNING) instead of self-certifying with
                # pass-by-construction 1100/17/280 values.
                out.append({
                    "id": f"synth_{lo['level_id']}_{hi['level_id']}",
                    "base_level_id": lo["level_id"], "top_level_id": hi["level_id"],
                    "base_z": float(lo_l.get("elevation_mm", 0.0)),
                    "top_z": float(hi_l.get("elevation_mm", 0.0)),
                    "run_width_mm": None, "riser_count": None, "tread_depth_mm": None,
                    "footprint": lo["boundary"], "kind": "inferred",
                })
            else:
                out.append({
                    "id": f"synth_{lo['level_id']}_{hi['level_id']}",
                    "base_level_id": lo["level_id"], "top_level_id": hi["level_id"],
                    "base_z": float(lo_l.get("elevation_mm", 0.0)),
                    "top_z": float(hi_l.get("elevation_mm", 0.0)),
                    "run_width_mm": 1100.0, "riser_count": 17, "tread_depth_mm": 280.0,
                    "footprint": lo["boundary"],
                })
    return out


def normalize(raw: dict) -> dict:
    """Turn the raw C# extraction into a SpatialModel-valid dict: assign each room.function via
    the RU lexicon (classify.py), backfill has_window/window_area from windows[]. Pure.

    v2 (KUKAI_CHECKER_V2=1) extracts TRUTH instead of fabricating:
      * height_mm: missing/zero stays None (v1 rewrote it to 2700 via `or 2700.0`) and
        height_source is preserved from the C# payload ("bounded"/"param");
      * apartment_id: stamped from the Revit department parameter when present;
      * doors: is_exterior is NEVER trusted from the raw payload (the v1 'one side
        null' heuristic mass-produces fake street exits) — derive.py re-establishes
        exteriority positively from envelope membership; host_wall_id is preserved;
      * windows: measured height/location pass through for the geometric join;
      * stairs: real parameters pass through as-is (None stays None — HAB011 says
        'cannot verify' instead of silently skipping), and _synthesize_stairs emits
        dimension-free kind='inferred' links."""
    v2 = checker_v2_enabled()
    rooms = []
    win_area: dict[str, float] = {}
    for w in raw.get("windows", []) or []:
        rid = w.get("room_id")
        if rid:
            win_area[rid] = win_area.get(rid, 0.0) + float(w.get("area_m2", 0.0) or 0.0)
    for r in raw.get("rooms", []) or []:
        rid = r["id"]
        if v2:
            h_raw = r.get("height_mm")
            height = float(h_raw) if h_raw not in (None, "") and float(h_raw) > 0.0 else None
            apartment = r.get("apartment_id") or (r.get("department") or "").strip() or None
        else:
            height = float(r.get("height_mm", 2700.0) or 2700.0)
            apartment = r.get("apartment_id")
        rooms.append({
            "id": rid, "name": r.get("name", ""), "number": r.get("number", ""),
            "level_id": r["level_id"],
            "function": classify_room(r.get("name", "")).value,
            "area_m2": float(r.get("area_m2", 0.0) or 0.0),
            "height_mm": height,
            "height_source": (r.get("height_source") if v2 else None),
            "boundary": r.get("boundary", []) or [],
            "apartment_id": apartment,
            "has_window": rid in win_area,
            "window_area_m2": round(win_area.get(rid, 0.0), 2),
        })
    doors = raw.get("doors", []) or []
    if v2:
        doors = [{**d, "is_exterior": False} for d in doors]  # derive.py decides
    return {
        "building_id": (raw.get("building_id") or "extracted").strip() or "extracted",
        "levels": raw.get("levels", []) or [],
        "rooms": rooms,
        "doors": doors,
        "windows": raw.get("windows", []) or [],
        "stairs": (raw.get("stairs", []) or [])
                  + _synthesize_stairs(rooms, raw.get("levels", []) or []),
        "walls": raw.get("walls", []) or [],
    }


def run_extractor_cs(device: str, timeout_ms: int = 120000) -> dict:
    """Execute the read-only extractor.cs on the operator-authorized device; return the raw dict."""
    if device not in AUTHORIZED:
        raise PermissionError(f"device {device} is not authorized for extraction")
    p = subprocess.run(
        [VPY, OP, "exec", device, "--code-file", str(_CS), "--timeout-ms", str(timeout_ms)],
        capture_output=True, text=True, timeout=timeout_ms / 1000 + 40,
    )
    r = json.loads(p.stdout)
    if r.get("status") != 200:
        raise RuntimeError(f"extractor exec failed: {json.dumps(r)[:300]}")
    res = (r.get("body") or {}).get("result")
    if not isinstance(res, dict) or res.get("error"):
        raise RuntimeError(f"extractor returned error: {json.dumps(res)[:300]}")
    return res


def extract(device: str) -> SpatialModel:
    """Read-only: extract the live Revit doc on `device` (authorized only) into a SpatialModel."""
    return SpatialModel.model_validate(normalize(run_extractor_cs(device)))
