"""Geometry-first derivation pre-pass (checker v2, roadmap 'Checker correctness & trust').

THE structural fix for the checker's five failure classes: before any rule runs, every
rule-relevant quantity is RECOMPUTED from geometry, and the declared scalars become
cross-checked claims instead of load-bearing inputs:

  * room area        <- shapely Polygon(boundary).area              (kills probe A)
  * has_window /     <- geometric window->wall->room join: the window (or its host
    window_area_m2      wall) must lie ON the room's boundary AND on the level's
                        ENVELOPE exterior ring                       (kills probes I, C)
  * door adjacency   <- the door location must touch the boundary of the rooms it
                        claims to connect; contradictions are PHANTOM doors and their
                        graph edges are dropped                      (kills declared-only
                        connectivity)
  * door exteriority <- POSITIVE envelope membership (door on the footprint's exterior
                        ring, touching exactly one room) — never the v1 'one side null'
                        heuristic                                    (kills probe D2)
  * ground levels    <- elevation band above the lowest occupied level AND a confirmed
                        envelope-exterior door (a floor-3 'exterior' door is a balcony,
                        not grade egress)
  * room function    <- names cross-checked via classify.py: a room declared ПРОЧЕЕ
                        whose name classifies to a real function is upgraded
                        (kills probe E2's silent bypass)

`derive(model, thr)` is PURE: it returns (derived_model, DerivationReport) and never
mutates its input. The engine (v2 path) runs the rules against the DERIVED model, so
rules keep their v1 signatures and read only measurements. The DerivationReport is the
witness the consistency rules (HAB060/061/062/063) and the coverage section read.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from kukai.modeling.checker.classify import classify_room, is_known_nonhabitable
from kukai.modeling.checker.spatial_model import (
    Door,
    Room,
    RoomFunction,
    SpatialModel,
)
from kukai.modeling.checker.thresholds import Thresholds

_MM2_PER_M2 = 1_000_000.0


class DoorStatus(str, Enum):
    """Geometric status of one door's declared adjacency."""
    CONFIRMED_INTERIOR = "confirmed_interior"   # touches both rooms it connects
    CONFIRMED_EXTERIOR = "confirmed_exterior"   # touches ONE room, ON the envelope ring
    UNKNOWN = "unknown"                          # geometry insufficient to confirm/deny
    CONTRADICTED = "contradicted"                # geometry contradicts the declaration
    ORPHAN = "orphan"                            # touches no room, claims no room


@dataclass(frozen=True)
class DoorDerivation:
    door_id: str
    status: DoorStatus
    touching_room_ids: tuple[str, ...] = ()
    declared_exterior: bool = False
    derived_exterior: bool = False
    on_envelope: bool = False
    note: str = ""


@dataclass(frozen=True)
class WindowDerivation:
    window_id: str
    room_id: str | None
    verified: bool
    derived_area_m2: float | None = None    # width x measured height when available
    area_measured: bool = False
    note: str = ""


@dataclass(frozen=True)
class RoomDerivation:
    room_id: str
    declared_area_m2: float
    derived_area_m2: float | None           # None = boundary unusable (unmeasured)
    area_mismatch: bool = False
    declared_has_window: bool = False
    verified_window_ids: tuple[str, ...] = ()
    verified_window_area_m2: float = 0.0
    window_claim_unbacked: bool = False     # declared has_window but nothing verified
    function_upgraded_from_name: bool = False
    unclassified: bool = False              # ПРОЧЕЕ and not a known non-habitable name


@dataclass
class DerivationReport:
    """The pre-pass witness: what geometry says, and where declarations disagree."""
    rooms: dict[str, RoomDerivation] = field(default_factory=dict)
    doors: dict[str, DoorDerivation] = field(default_factory=dict)
    windows: dict[str, WindowDerivation] = field(default_factory=dict)
    ground_level_ids: set[str] = field(default_factory=set)
    dropped_door_ids: set[str] = field(default_factory=set)   # contradicted → no edge
    above_grade_exterior_door_ids: set[str] = field(default_factory=set)
    floorplate_coverage: dict[str, float] = field(default_factory=dict)  # level → ratio
    unmeasured_room_ids: list[str] = field(default_factory=list)
    unclassified_room_ids: list[str] = field(default_factory=list)
    measured_room_ratio: float = 1.0
    classification_coverage: float = 1.0
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- geometry helpers

def _polygon(boundary: list[tuple[float, float]]) -> Polygon | None:
    """Shapely polygon from a boundary loop; None when degenerate (<3 pts / zero area).

    ALWAYS a single Polygon: ``buffer(0)`` on a self-intersecting loop (routine in
    real models — live smoke 2026-07-10 hit it on LSR_Lot31 room boundaries)
    returns a MultiPolygon, which crashed every ``.exterior`` consumer downstream
    (_touches :129, ring build :313). Keep the largest-area component — the
    room's main body; smaller pieces are self-intersection slivers, not rooms."""
    if not boundary or len(boundary) < 3:
        return None
    poly = Polygon(boundary)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.area <= 0.0:
        return None
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
        if poly.is_empty or poly.area <= 0.0:
            return None
    return poly


def _touches(poly: Polygon, pt: Point, tol: float) -> bool:
    """A door/window at `pt` serves `poly`'s room: on (near) its boundary ring, or
    swallowed inside it (containment covers rooms whose geometry drifted over the
    opening — still an association, the ring test alone would call it phantom)."""
    return poly.exterior.distance(pt) <= tol or poly.contains(pt)


def _level_envelope(polys: list[Polygon], close_tol: float):
    """The level footprint (morphological closing over the room-union, so wall-thickness
    gaps between adjacent rooms merge) and its EXTERIOR ring(s). Hole rings are NOT
    exterior: a door on a shaft/courtyard hole is not a street exit."""
    if not polys:
        return None, []
    union = unary_union([p.buffer(close_tol) for p in polys]).buffer(-close_tol)
    if union.is_empty:
        return None, []
    geoms = list(getattr(union, "geoms", [union]))
    rings = [LineString(g.exterior.coords) for g in geoms if not g.is_empty]
    return union, rings


def _on_any_ring(rings, pt: Point, tol: float) -> bool:
    return any(r.distance(pt) <= tol for r in rings)


def _seg_ring_overlap(seg: LineString, rings, tol: float) -> float:
    """Length of `seg` lying within `tol` of any ring (how much of a wall actually sits
    on the envelope / on a room boundary)."""
    total = 0.0
    for r in rings:
        inter = seg.intersection(r.buffer(tol))
        total = max(total, getattr(inter, "length", 0.0))
    return total


# ------------------------------------------------------------------------------ derive

def derive(model: SpatialModel, thr: Thresholds) -> tuple[SpatialModel, DerivationReport]:
    """Run the geometry-first pre-pass. Returns (derived_model, report). Pure."""
    rep = DerivationReport()
    tol = thr.derive_join_tol_mm

    # --- room polygons + per-level envelopes -------------------------------------
    polys: dict[str, Polygon] = {}
    for r in model.rooms:
        p = _polygon(r.boundary)
        if p is not None:
            polys[r.id] = p
        else:
            rep.unmeasured_room_ids.append(r.id)

    rooms_by_level: dict[str, list[Room]] = {}
    for r in model.rooms:
        rooms_by_level.setdefault(r.level_id, []).append(r)

    envelopes: dict[str, tuple] = {}
    for lid, rooms in rooms_by_level.items():
        lvl_polys = [polys[r.id] for r in rooms if r.id in polys]
        footprint, rings = _level_envelope(lvl_polys, thr.derive_close_tol_mm)
        envelopes[lid] = (footprint, rings)
        if footprint is not None and lvl_polys:
            union_area = unary_union(lvl_polys).area
            rep.floorplate_coverage[lid] = (
                union_area / footprint.area if footprint.area > 0 else 1.0
            )

    n_rooms = len(model.rooms)
    rep.measured_room_ratio = (len(polys) / n_rooms) if n_rooms else 0.0

    # --- function cross-check (classification upgrade from names) -----------------
    derived_functions: dict[str, RoomFunction] = {}
    upgraded: set[str] = set()
    unclassified: set[str] = set()
    for r in model.rooms:
        func = r.function
        if func is RoomFunction.ПРОЧЕЕ:
            by_name = classify_room(r.name)
            if by_name is not RoomFunction.ПРОЧЕЕ:
                func = by_name           # 'Bedroom 1' declared прочее → жилая
                upgraded.add(r.id)
            elif not is_known_nonhabitable(r.name):
                unclassified.add(r.id)
        derived_functions[r.id] = func
    rep.unclassified_room_ids = sorted(unclassified)
    rep.classification_coverage = (
        (n_rooms - len(unclassified)) / n_rooms if n_rooms else 0.0
    )

    # --- door adjacency + positive exteriority -----------------------------------
    room_ids = {r.id for r in model.rooms}
    derived_doors: list[Door] = []
    for d in model.doors:
        pt = Point(d.location)
        _, rings = envelopes.get(d.level_id, (None, []))
        on_env = _on_any_ring(rings, pt, tol)
        touching = tuple(sorted(
            r.id for r in rooms_by_level.get(d.level_id, [])
            if r.id in polys and _touches(polys[r.id], pt, tol)
        ))
        declared = tuple(x for x in (d.from_room_id, d.to_room_id) if x)
        declared_measurable = [x for x in declared if x in polys]
        declared_unmeasurable = [x for x in declared if x not in polys]

        status = DoorStatus.UNKNOWN
        derived_ext = False
        note = ""
        if not touching:
            if declared_measurable:
                status = DoorStatus.CONTRADICTED
                note = (f"declared rooms {declared_measurable} have measurable boundaries "
                        f"but the door touches none of them (phantom door)")
            elif declared:
                status = DoorStatus.UNKNOWN
                note = "declared rooms have no measurable boundary — cannot verify"
            else:
                status = DoorStatus.ORPHAN
                note = "door touches no room and claims no room"
        elif len(touching) >= 2:
            if d.is_exterior:
                status = DoorStatus.CONTRADICTED
                note = (f"declared EXTERIOR but geometrically connects rooms "
                        f"{list(touching)} (fake street exit)")
            elif set(declared_measurable) <= set(touching):
                status = DoorStatus.CONFIRMED_INTERIOR
            else:
                status = DoorStatus.CONTRADICTED
                note = (f"declared rooms {declared_measurable} do not match the rooms "
                        f"the door actually touches {list(touching)}")
        else:  # exactly one touching room
            other_declared = [x for x in declared_measurable if x != touching[0]]
            if other_declared:
                status = DoorStatus.CONTRADICTED
                note = (f"declared to connect {declared_measurable} but only touches "
                        f"{touching[0]}")
            elif on_env and not declared_unmeasurable:
                # POSITIVE exteriority: one room, on the envelope exterior ring, and no
                # unresolved second room claimed.
                status = DoorStatus.CONFIRMED_EXTERIOR
                derived_ext = True
            else:
                status = DoorStatus.UNKNOWN
                note = ("declared exterior but NOT on the level envelope — unplaced "
                        "room / shaft / phase artefact, never a street exit"
                        if d.is_exterior else
                        "adjacency unverifiable (second side unresolved, not on envelope)")

        if status is DoorStatus.CONTRADICTED:
            rep.dropped_door_ids.add(d.id)

        rep.doors[d.id] = DoorDerivation(
            door_id=d.id, status=status, touching_room_ids=touching,
            declared_exterior=d.is_exterior, derived_exterior=derived_ext,
            on_envelope=on_env, note=note,
        )
        derived_doors.append(d.model_copy(update={"is_exterior": derived_ext}))

    # --- ground levels: envelope-exterior door + elevation band -------------------
    occupied = [lvl for lvl in model.levels
                if any(r.level_id == lvl.id for r in model.rooms)]
    if occupied:
        min_elev = min(lvl.elevation_mm for lvl in occupied)
        exterior_levels = {d.level_id for d in derived_doors if d.is_exterior}
        for lvl in model.levels:
            if lvl.id not in exterior_levels:
                continue
            if lvl.elevation_mm <= min_elev + thr.ground_elevation_band_mm:
                rep.ground_level_ids.add(lvl.id)
        # exterior doors above the grade band = balconies/terraces, not egress
        for d in derived_doors:
            if d.is_exterior and d.level_id not in rep.ground_level_ids:
                rep.above_grade_exterior_door_ids.add(d.id)

    # --- window -> wall -> room geometric join ------------------------------------
    walls_by_id = {w.id: w for w in model.walls}
    verified_by_room: dict[str, list[str]] = {}
    verified_area_by_room: dict[str, float] = {}
    for w in model.windows:
        room = next((r for r in model.rooms if r.id == w.room_id), None)
        verified = False
        note = ""
        derived_area: float | None = None
        area_measured = False
        if w.height_mm is not None and w.height_mm > 0 and w.width_mm > 0:
            derived_area = round(w.width_mm * w.height_mm / _MM2_PER_M2, 2)
            area_measured = True
        if room is None or room.id not in polys:
            note = "window's room is missing or has no measurable boundary"
        else:
            ring = LineString(polys[room.id].exterior.coords)
            _, env_rings = envelopes.get(room.level_id, (None, []))
            if w.location is not None:
                pt = Point(w.location)
                if ring.distance(pt) <= tol and _on_any_ring(env_rings, pt, tol):
                    verified = True
                else:
                    note = ("window location is not on the room's envelope-exterior "
                            "boundary (shaft/interior window)")
            elif w.host_wall_id and w.host_wall_id in walls_by_id:
                seg = LineString(walls_by_id[w.host_wall_id].curve)
                need = thr.window_host_min_overlap_mm
                on_room = _seg_ring_overlap(seg, [ring], tol) >= need
                on_env = _seg_ring_overlap(seg, env_rings, tol) >= need
                if on_room and on_env:
                    verified = True
                else:
                    note = ("host wall does not lie on the room's envelope-exterior "
                            "boundary (shaft/interior wall)")
            else:
                note = ("window has no location and no resolvable host wall — "
                        "hosted in nothing (fabricated?)")
        rep.windows[w.id] = WindowDerivation(
            window_id=w.id, room_id=w.room_id, verified=verified,
            derived_area_m2=derived_area, area_measured=area_measured, note=note,
        )
        if verified and w.room_id:
            verified_by_room.setdefault(w.room_id, []).append(w.id)
            area = derived_area if area_measured else (w.area_m2 or 0.0)
            verified_area_by_room[w.room_id] = (
                verified_area_by_room.get(w.room_id, 0.0) + (area or 0.0)
            )

    # --- room scalars: derived area, verified windows, mismatches -----------------
    derived_rooms: list[Room] = []
    for r in model.rooms:
        p = polys.get(r.id)
        derived_area = round(p.area / _MM2_PER_M2, 2) if p is not None else None
        mismatch = False
        if derived_area is not None:
            diff = abs(derived_area - r.area_m2)
            if diff > thr.area_mismatch_abs_m2 and (
                derived_area <= 0.0 or diff / max(derived_area, 1e-9) > thr.area_mismatch_rel
            ):
                mismatch = True
        win_ids = tuple(sorted(verified_by_room.get(r.id, [])))
        win_area = round(verified_area_by_room.get(r.id, 0.0), 2)
        claim_unbacked = bool(r.has_window and not win_ids)
        rep.rooms[r.id] = RoomDerivation(
            room_id=r.id, declared_area_m2=r.area_m2, derived_area_m2=derived_area,
            area_mismatch=mismatch, declared_has_window=r.has_window,
            verified_window_ids=win_ids, verified_window_area_m2=win_area,
            window_claim_unbacked=claim_unbacked,
            function_upgraded_from_name=(r.id in upgraded),
            unclassified=(r.id in unclassified),
        )
        derived_rooms.append(r.model_copy(update={
            "function": derived_functions[r.id],
            "area_m2": derived_area if derived_area is not None else r.area_m2,
            "has_window": bool(win_ids),
            "window_area_m2": win_area,
            "height_source": r.height_source or "declared",
        }))

    derived_model = model.model_copy(update={
        "rooms": derived_rooms,
        "doors": derived_doors,
    })
    return derived_model, rep
