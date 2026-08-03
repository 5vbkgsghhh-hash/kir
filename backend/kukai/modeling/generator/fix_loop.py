"""Generate → check → fix loop — vibecoding for buildings.

The skeleton generator already produces clean buildings; this loop is the scaffold where
REPAIRS plug in (deterministic fixers now; an LLM adaptation layer later). It runs the
checker, feeds each violation it knows how to repair to a fixer, and re-checks until the
building passes (no BLOCKING) or the iteration budget runs out. The fixer registry is the
single extension point — swap deterministic fixers for an LLM and the loop is unchanged.

checker v2 (KUKAI_CHECKER_V2=1): the v1 fixers WROTE THE EXACT SCALARS THE RULES READ
(_fix_hab030 set has_window=True + appended a window with host_wall_id=None — a window
hosted in nothing) and the loop re-checked its own edited dict: self-certification
(roadmap probe C). Under v2:
  * the derivation pre-pass recomputes has_window/window_area from geometry, so scalar
    edits simply stop working (the old fixers now converge to FAIL, honestly);
  * DEFAULT_FIXERS_V2 are GEOMETRIC: a daylight repair inserts a real wall on an
    envelope-exterior boundary edge of the room and hosts a real, measured window in
    it — an edit the derivation layer can verify;
  * LoopResult.certified is ALWAYS False here: run_loop's verdict is a claim about the
    edited DICT. Anything destined for Revit is certified ONLY by the round-trip
    (generator/roundtrip.py: materialize → re-extract → check).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

from shapely.geometry import LineString

from kukai.modeling.checker.derive import _level_envelope, _polygon, _seg_ring_overlap
from kukai.modeling.checker.engine import run
from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import SpatialModel, Violation
from kukai.modeling.checker.thresholds import THRESHOLDS, Thresholds


def _rooms_in(model_dict: dict, refs: list[str]):
    by_id = {r["id"]: r for r in model_dict["rooms"]}
    return [by_id[r] for r in refs if r in by_id]


# ------------------------------------------------------------------ v1 fixers (legacy)

def _fix_hab030(model_dict: dict, v: Violation, thr: Thresholds) -> None:
    """v1 LEGACY: add an exterior window *scalar claim* to each flagged room (HAB030).

    Kept verbatim for the v1 path — and as the negative exhibit: under v2 the window it
    fabricates (host_wall_id=None) never verifies, so this fixer can no longer flip a
    verdict (probe C is dead)."""
    for r in _rooms_in(model_dict, v.refs):
        need = max(r.get("window_area_m2", 0.0), r.get("area_m2", 10.0) * thr.min_daylight_ratio + 0.1)
        r["has_window"] = True
        r["window_area_m2"] = need
        model_dict["windows"].append({
            "id": f"wfix_{r['id']}", "level_id": r["level_id"], "host_wall_id": None,
            "room_id": r["id"], "width_mm": 1500.0, "area_m2": need,
        })


def _fix_hab031(model_dict: dict, v: Violation, thr: Thresholds) -> None:
    """Enlarge the window so the daylight ratio clears the floor (HAB031)."""
    for r in _rooms_in(model_dict, v.refs):
        r["has_window"] = True
        r["window_area_m2"] = max(r.get("window_area_m2", 0.0),
                                  r.get("area_m2", 10.0) * thr.min_daylight_ratio + 0.1)


def _fix_hab022(model_dict: dict, v: Violation, thr: Thresholds) -> None:
    """Raise the ceiling to the minimum habitable height (HAB022)."""
    for r in _rooms_in(model_dict, v.refs):
        if r["height_mm"] is None or r["height_mm"] < thr.min_ceiling_height_mm:
            r["height_mm"] = thr.min_ceiling_height_mm


# ------------------------------------------------------------------ v2 geometric fixers

def _exterior_edges(model_dict: dict, room: dict, thr: Thresholds) -> list[tuple]:
    """The room's boundary edges that lie on the level's envelope-exterior ring,
    longest first: the honest places a window/wall can go."""
    boundary = room.get("boundary") or []
    if len(boundary) < 3:
        return []
    level_polys = [
        p for p in (
            _polygon(r.get("boundary") or [])
            for r in model_dict["rooms"] if r["level_id"] == room["level_id"]
        ) if p is not None
    ]
    _, rings = _level_envelope(level_polys, thr.derive_close_tol_mm)
    if not rings:
        return []
    edges = []
    n = len(boundary)
    for i in range(n):
        p, q = tuple(boundary[i]), tuple(boundary[(i + 1) % n])
        seg = LineString([p, q])
        if seg.length < 2.0 * thr.window_host_min_overlap_mm:
            continue
        if _seg_ring_overlap(seg, rings, thr.derive_join_tol_mm) >= seg.length * 0.9:
            edges.append((seg.length, p, q))
    edges.sort(reverse=True)
    return edges


def _fix_hab030_v2(model_dict: dict, v: Violation, thr: Thresholds) -> None:
    """v2 GEOMETRIC daylight repair: host a real, measured window in a wall that lies on
    an envelope-exterior boundary edge of the room. The derivation layer will verify it
    (or refuse — there is no exterior edge to put it on, and the loop then fails
    honestly instead of inventing light)."""
    for r in _rooms_in(model_dict, v.refs):
        if any(w.get("room_id") == r["id"] and str(w.get("id", "")).startswith("wfix2_")
               for w in model_dict["windows"]):
            continue  # already repaired once; don't stack windows
        edges = _exterior_edges(model_dict, r, thr)
        if not edges:
            continue  # no exterior edge — this room CANNOT get a real window; stay honest
        length, p, q = edges[0]
        wall_id = f"wfix2_wall_{r['id']}"
        if not any(w["id"] == wall_id for w in model_dict["walls"]):
            model_dict["walls"].append({
                "id": wall_id, "level_id": r["level_id"],
                "curve": [list(p), list(q)],
                "height_mm": 2700.0, "is_structural": False,
            })
        width = min(1500.0, length * 0.6)
        height = 1400.0
        need = max(r.get("area_m2", 10.0) * thr.min_daylight_ratio + 0.1,
                   round(width * height / 1_000_000.0, 2))
        # widen until the measured area covers the daylight need (cap at the edge)
        while round(width * height / 1_000_000.0, 2) < need and width < length * 0.9:
            width = min(length * 0.9, width + 300.0)
        area = round(width * height / 1_000_000.0, 2)
        mx, my = (p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0
        model_dict["windows"].append({
            "id": f"wfix2_{r['id']}", "level_id": r["level_id"], "host_wall_id": wall_id,
            "room_id": r["id"], "width_mm": width, "area_m2": area,
            "height_mm": height, "location": [mx, my],
        })
        # declared scalars now DESCRIBE the real window (derivation recomputes anyway;
        # keeping them in sync avoids a spurious HAB060 'unbacked claim' next iteration)
        r["has_window"] = True
        r["window_area_m2"] = area


def _fix_hab031_v2(model_dict: dict, v: Violation, thr: Thresholds) -> None:
    """v2: enlarge the room's REAL window (width/height/area together) — never the scalar."""
    for r in _rooms_in(model_dict, v.refs):
        need = r.get("area_m2", 10.0) * thr.min_daylight_ratio + 0.1
        for w in model_dict["windows"]:
            if w.get("room_id") != r["id"]:
                continue
            height = w.get("height_mm") or 1400.0
            width = max(w.get("width_mm", 1200.0), need * 1_000_000.0 / height)
            w["width_mm"] = width
            w["height_mm"] = height
            w["area_m2"] = round(width * height / 1_000_000.0, 2)
            r["window_area_m2"] = w["area_m2"]
            r["has_window"] = True
            break


def _fix_hab060(model_dict: dict, v: Violation, thr: Thresholds) -> None:
    """v2: declaration-consistency repair — geometry is the truth, so the DECLARATION is
    what gets corrected: declared area := polygon area; an unbacked window claim is
    withdrawn (and HAB030 will then demand a real window via _fix_hab030_v2)."""
    for r in _rooms_in(model_dict, v.refs):
        poly = _polygon(r.get("boundary") or [])
        if poly is not None:
            r["area_m2"] = round(poly.area / 1_000_000.0, 2)
        room_windows = [w for w in model_dict["windows"] if w.get("room_id") == r["id"]]
        hosted = [w for w in room_windows if w.get("host_wall_id") or w.get("location")]
        if r.get("has_window") and not hosted:
            r["has_window"] = False
            r["window_area_m2"] = 0.0
            model_dict["windows"] = [w for w in model_dict["windows"]
                                     if w.get("room_id") != r["id"]]


#: rule_id -> in-place repair. The single extension point (LLM fixers slot in here later).
DEFAULT_FIXERS: dict[str, Callable[[dict, Violation, Thresholds], None]] = {
    "HAB030": _fix_hab030,
    "HAB031": _fix_hab031,
    "HAB022": _fix_hab022,
}

#: v2 registry: geometric repairs only — every fix is an edit the derivation layer can
#: independently verify. No fixer writes a scalar a rule reads without the geometry
#: behind it.
DEFAULT_FIXERS_V2: dict[str, Callable[[dict, Violation, Thresholds], None]] = {
    "HAB030": _fix_hab030_v2,
    "HAB031": _fix_hab031_v2,
    "HAB022": _fix_hab022,
    "HAB060": _fix_hab060,
}


@dataclass
class LoopResult:
    model: dict
    passed: bool
    iterations: int
    history: list[list[str]] = field(default_factory=list)  # rule_ids present each iteration
    #: run_loop verdicts are claims about the edited DICT. Only the round-trip
    #: (generator/roundtrip.py: materialize → re-extract → check) may certify a
    #: building for the real world; this field exists so no caller can confuse the two.
    certified: bool = False


def run_loop(model_dict: dict, *, max_iters: int = 8, thr: Thresholds = THRESHOLDS,
             fixers: dict | None = None) -> LoopResult:
    """Run the check→fix loop until the building passes (no BLOCKING) or the budget runs out.

    Pure w.r.t. the input dict (works on a deep copy). Returns the (possibly repaired) model,
    whether it passes, the iterations used, and the per-iteration violation history.
    NOTE: `passed` refers to the edited dict only — see LoopResult.certified.
    """
    if fixers is None:
        fixers = DEFAULT_FIXERS_V2 if checker_v2_enabled() else DEFAULT_FIXERS
    model_dict = copy.deepcopy(model_dict)
    history: list[list[str]] = []

    for it in range(max_iters):
        report = run(SpatialModel.model_validate(model_dict), thr)
        history.append([v.rule_id for v in (report.blocking + report.warnings + report.info)])
        if report.passed:
            return LoopResult(model_dict, True, it, history)
        repaired = False
        for v in report.blocking + report.warnings:
            fx = fixers.get(v.rule_id)
            if fx is not None:
                fx(model_dict, v, thr)
                repaired = True
        if not repaired:
            break  # no fixer for the remaining violations → give up honestly

    final = run(SpatialModel.model_validate(model_dict), thr)
    return LoopResult(model_dict, final.passed, len(history), history)
