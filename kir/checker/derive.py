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

import math
from dataclasses import dataclass, field
from enum import Enum

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from kir.checker.classify import classify_room, is_known_nonhabitable
from kir.checker.function_provenance import DERIVED_KIND, function_authority
from kir.checker.spatial_model import (
    Door,
    Room,
    RoomFunction,
    SpatialModel,
)
from kir.checker.thresholds import Thresholds

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


class WindowStatus(str, Enum):
    """WHAT EXACTLY THE GEOMETRY SAID ABOUT THIS WINDOW — typed, not as prose.

    Introduced 17.08.2026, because `verified=False` covers TWO outcomes of a
    different kind, and the distinction between them decides whether HAB030
    is entitled to accuse the room:

      * the geometry SAID NO — the window exists, but does not sit on the
        exterior boundary (a shaft, an interior window). This is A FINDING
        ABOUT THE BUILDING: the room has no light;
      * the geometry COULD NOT SAY — the window has neither a point nor a
        resolvable host wall, or its room has no measurable boundary. This
        is A FINDING ABOUT US: we failed to read it, not "there is no
        window."

    Measured 17.08.2026 on the `builders.make_good()` reference case with
    the WALLS removed (the windows stay in place, all three): all 3 windows
    give `verified=False` with the cause «hosted in nothing», and HAB030
    accuses 2 rooms with the text «не имеет наружного окна — жить/готовить
    без естественного света нельзя». Word for word the same text as on the
    real finding `bad_bedroom_no_window`. The reader has NOTHING to tell
    them apart with.

    The cause was already being computed — and it lived in `note` as a
    STRING. Reading prose as code is this project's named defect (form 19:
    an explanation in place of code), so a code was introduced alongside
    it, and `note` was left as it was: it is addressed to a human.
    """
    VERIFIED = "verified"                    # on the room's exterior boundary
    NOT_ON_ENVELOPE = "not_on_envelope"      # read, and the answer is NO: a shaft / an interior window
    UNPLACEABLE = "unplaceable"              # neither a point nor a host wall — there is nothing to read with
    ROOM_UNMEASURABLE = "room_unmeasurable"  # the room has no measurable boundary for the window

    @property
    def is_read(self) -> bool:
        """Whether the geometry gave a DEFINITE answer (either of the two), not a refusal."""
        return self in (WindowStatus.VERIFIED, WindowStatus.NOT_ON_ENVELOPE)


@dataclass(frozen=True)
class WindowDerivation:
    window_id: str
    room_id: str | None
    verified: bool
    status: WindowStatus
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
    #: WHETHER THE FACT ABOUT THIS ROOM'S WINDOW WAS EVER READ AT ALL. False
    #: EXACTLY when at least one window names the room and NOT ONE of them
    #: gave a definite answer (`WindowStatus.is_read`). A falsehood here is a
    #: claim about OUR OWN blindness, not about the room, and
    #: `engine.SUBJECT_INPUTS["room_window_readable"]` uses it to hold HAB030
    #: back from accusing.
    #:
    #: 🔴 A BOUNDARY NAMED OUT LOUD: a room that NO window names at all gets
    #: True — that is, it counts as read. This does NOT mean we know there
    #: are no windows; it means there is NOTHING to tell "we weren't given
    #: any windows" apart from "there are no windows" on this input, and
    #: silently turning a possible finding into `vacuous` is worse than
    #: leaving a false alarm. `SpatialModel` carries no "windows were read"
    #: marker, and `extractor.normalize` (:124) merges a missing key with an
    #: empty list (`raw.get("windows", []) or []`), so this marker doesn't
    #: exist on the live path either. Measured 17.08: `extractor.cs:137`
    #: collects ONLY `OST_Windows`, so a building with curtain-wall glazing
    #: has zero windows — and that is a third indistinguishable outcome.
    #: Only the producer can supply a way to tell them apart.
    window_fact_readable: bool = True
    #: WHETHER THIS ROOM'S GLAZING AREA WAS MEASURED. False EXACTLY when at
    #: least one CONFIRMED window of the room brought a substituted value
    #: (`Window.area_source == "nominal"`). A room with no confirmed windows
    #: gets True — it had nothing to measure, and that is a KNOWN CLEAN
    #: result, not the absence of a measurement. The boundary is named out
    #: loud by the same law as `window_fact_readable` above.
    window_area_measured: bool = True


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
    #: Rooms whose function was DERIVED by us, not read from the author
    #: (`function_provenance.DERIVED`; today that means derived from
    #: furnishings). A separate list, because `classification_coverage`
    #: answers "how much was classified" and does NOT answer "by what":
    #: coverage built from toilet fixtures and coverage built from room
    #: names are different grounds for a verdict.
    derived_function_room_ids: list[str] = field(default_factory=list)
    measured_room_ratio: float = 1.0
    classification_coverage: float = 1.0
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------- geometry helpers

def _polygon(boundary: list[tuple[float, float]],
             holes: list[list[tuple[float, float]]] | None = None) -> Polygon | None:
    """Shapely polygon from a boundary loop; None when degenerate (<3 pts / zero area).

    ALWAYS a single Polygon: ``buffer(0)`` on a self-intersecting loop (routine in
    real models — live smoke 2026-07-10 hit it on LSR_Lot31 room boundaries)
    returns a MultiPolygon, which crashed every ``.exterior`` consumer downstream
    (_touches :129, ring build :313). Keep the largest-area component — the
    room's main body; smaller pieces are self-intersection slivers, not rooms."""
    if not boundary or len(boundary) < 3:
        return None
    # 🔴 HOLES ARE SUBTRACTED (F-041). The `None` default leaves the previous
    # behavior byte for byte: an empty list of holes gives
    # `Polygon(shell, [])` == `Polygon(shell)`. Nesting is deliberately NOT
    # checked: Revit already checked it (`GetBoundarySegments` returns
    # closed loops, `L0Document` validates them), and on incorrect nesting
    # shapely will return an invalid polygon and the existing `buffer(0)`
    # branch will fix it — meaning the worst case equals today's behavior,
    # not a refusal.
    poly = Polygon(boundary, [h for h in (holes or ()) if len(h) >= 3])
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
    """Length of the WALL portion that lies ON the boundary: collinear with its
    edge and within `tol` of that edge's LINE.

    🔴 IT USED TO BE `seg.intersection(ring.buffer(tol)).length`, AND THAT
    MEASURED THE WRONG THING (30.08.2026, audit finding F-253). The ring
    buffer is a two-dimensional STRIP of width `2*tol`, so a wall CROSSING the
    facade at a right angle picks up exactly 600 mm inside it at `tol=300` and
    clears the threshold `window_host_min_overlap_mm=400`. The threshold is
    SMALLER than twice the tolerance, so ANY angle passed on LENGTH: the
    instrument was blind to direction not by configuration but BY
    CONSTRUCTION. The shaft's interior window got `VERIFIED`, and
    HAB030/HAB031 believed it.

    Raising the threshold above `2*tol` is not a fix: the question "at what
    angle is a wall still the host" would still be decided by a number nobody
    measured. The discriminator is DIRECTION, and it is obtained WITHOUT a
    single new constant: both ends of the wall must lie within `tol` of the
    edge's LINE. This alone cuts off the perpendicular case, while a wall
    TWICE AS LONG as the edge passes — the distance is taken to the LINE, not
    to the segment.

    The same technique already lives in `graph._share_a_segment`: there, both
    ends of the neighboring edge are checked for distance from the first
    edge's line. The instrument is new, the law is old.
    """
    (sx0, sy0), (sx1, sy1) = seg.coords[0], seg.coords[-1]
    sdx, sdy = sx1 - sx0, sy1 - sy0
    slen_sq = sdx * sdx + sdy * sdy
    if slen_sq <= 0.0:
        return 0.0
    slen = math.sqrt(slen_sq)
    spans: list[tuple[float, float]] = []
    for ring in rings:
        coords = list(ring.coords)
        for (ex0, ey0), (ex1, ey1) in zip(coords, coords[1:]):
            edx, edy = ex1 - ex0, ey1 - ey0
            elen_sq = edx * edx + edy * edy
            if elen_sq <= 0.0:
                continue
            elen = math.sqrt(elen_sq)
            # 1. COLLINEARITY: both ends of the wall are within tol of the edge's LINE.
            if max(abs((sx0 - ex0) * edy - (sy0 - ey0) * edx),
                   abs((sx1 - ex0) * edy - (sy1 - ey0) * edx)) > tol * elen:
                continue
            # 2. OVERLAP: the edge's endpoints, in the WALL's parameter, clamped to [0,1].
            u0 = ((ex0 - sx0) * sdx + (ey0 - sy0) * sdy) / slen_sq
            u1 = ((ex1 - sx0) * sdx + (ey1 - sy0) * sdy) / slen_sq
            lo, hi = sorted((u0, u1))
            lo, hi = max(lo, 0.0), min(hi, 1.0)
            if hi > lo:
                spans.append((lo, hi))
    if not spans:
        return 0.0
    # Merging segments PER WALL: a facade split by the envelope's closure into
    # several collinear edges must yield a SUM, not a maximum, while not
    # counting the same thing twice.
    total, cur_lo, cur_hi = 0.0, None, None
    for lo, hi in sorted(spans):
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None:
                total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    total += cur_hi - cur_lo
    return total * slen


# ------------------------------------------------------------------------------ derive

def derive(model: SpatialModel, thr: Thresholds) -> tuple[SpatialModel, DerivationReport]:
    """Run the geometry-first pre-pass. Returns (derived_model, report). Pure."""
    rep = DerivationReport()
    tol = thr.derive_join_tol_mm

    # --- room polygons + per-level envelopes -------------------------------------
    polys: dict[str, Polygon] = {}
    for r in model.rooms:
        p = _polygon(r.boundary, r.boundary_holes)
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
    function_sources: dict[str, str | None] = {}
    upgraded: set[str] = set()
    unclassified: set[str] = set()
    for r in model.rooms:
        func = r.function
        source = r.function_source
        if func is RoomFunction.ПРОЧЕЕ:
            by_name = classify_room(r.name)
            if by_name is not RoomFunction.ПРОЧЕЕ:
                func = by_name           # 'Bedroom 1' declared other → habitable
                # The upgrade reads the NAME the author wrote — so the
                # quantity's kind is the author's, whatever kind the declared function has.
                source = "room_name"
                upgraded.add(r.id)
            elif not is_known_nonhabitable(r.name):
                unclassified.add(r.id)
        derived_functions[r.id] = func
        function_sources[r.id] = source
    rep.unclassified_room_ids = sorted(unclassified)
    rep.derived_function_room_ids = sorted(
        rid for rid, src in function_sources.items()
        if rid not in unclassified and function_authority(src) == DERIVED_KIND)
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
                # 🔴 ONLY WHAT RESOLVED COMPLETELY CAN BE CONFIRMED
                # (F-252, 30.08.2026). The condition `declared_measurable <= touching`
                # is true even when the SECOND declared end did not resolve
                # at all: the measurable subset agreed, and the unresolved one
                # simply took no part in the comparison. The neighboring
                # exteriority branch has asked this same question from the
                # start — here it was skipped.
                #
                # The cost of the silence is named by the GRAPH ITSELF:
                # `build_graph` only builds a door edge when `a in room_ids and
                # b in room_ids`, so a door with an end OUTSIDE the model loses
                # its connection WITHOUT A SINGLE REFUSAL, while a door with an
                # end WITHOUT A BOUNDARY keeps its edge — unverified. The
                # outcomes are DIFFERENT, and both must be named.
                if declared_unmeasurable:
                    status = DoorStatus.UNKNOWN
                    dangling = [x for x in declared_unmeasurable
                                if x not in room_ids]
                    note = (
                        f"declared room(s) {dangling} are not in the model at all — "
                        f"the graph drops this door's edge"
                        if dangling else
                        f"declared room(s) {declared_unmeasurable} have no measurable "
                        f"boundary — the adjacency is kept but NOT verified")
                else:
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
    # 🔴 AN UNKNOWN ELEVATION IS NOT A SMALL ONE. A level addressed by
    # `element_id` in an existing document enters the model without a number
    # (see `Level.elevation_mm`); folding it into `min()` as 0.0 would make the
    # lowest floor of the building out of whatever floor the author happened to
    # reference. So the band is computed over levels that HAVE a number, and a
    # level without one joins the ground set only when NOTHING has a number —
    # i.e. when there is nothing to be lower than, which is exactly the
    # single-level case the production program hits.
        known = [lvl.elevation_mm for lvl in occupied if lvl.elevation_mm is not None]
        min_elev = min(known) if known else None
        exterior_levels = {d.level_id for d in derived_doors if d.is_exterior}
        for lvl in model.levels:
            if lvl.id not in exterior_levels:
                continue
            if min_elev is None:
                rep.ground_level_ids.add(lvl.id)
            elif (lvl.elevation_mm is not None
                    and lvl.elevation_mm <= min_elev + thr.ground_elevation_band_mm):
                rep.ground_level_ids.add(lvl.id)
        # exterior doors above the grade band = balconies/terraces, not egress
        for d in derived_doors:
            if d.is_exterior and d.level_id not in rep.ground_level_ids:
                rep.above_grade_exterior_door_ids.add(d.id)

    # --- window -> wall -> room geometric join ------------------------------------
    walls_by_id = {w.id: w for w in model.walls}
    rooms_by_id = {r.id: r for r in model.rooms}
    verified_by_room: dict[str, list[str]] = {}
    verified_area_by_room: dict[str, float] = {}
    #: rooms for which at least one window gave a DEFINITE answer, and rooms
    #: for which a window was found but could not be read. Overlap is
    #: possible: a room has two windows, one read, the other not — the read
    #: one wins.
    window_read_rooms: set[str] = set()
    window_unread_rooms: set[str] = set()
    #: Rooms where at least one CONFIRMED window brought a SUBSTITUTED
    #: area. For them the 1:8 norm has no subject (F-254).
    nominal_area_rooms: set[str] = set()
    for w in model.windows:
        room = rooms_by_id.get(w.room_id) if w.room_id else None
        verified = False
        note = ""
        status = WindowStatus.UNPLACEABLE
        derived_area: float | None = None
        area_measured = False
        if w.height_mm is not None and w.height_mm > 0 and w.width_mm > 0:
    # 🔴 ROUNDING WAS REMOVED 29.08.2026 (audit findings F-040, F-256, F-336).
            # THE LAW IS THE SAME FOR ALL FOUR SITES: rounding is allowed only for
            # DISPLAY, never before comparison with a threshold. A rounded value fed
            # to a rule changes the VERDICT, not the printed precision:
            #
            #   F-040  habitable 7995x1000 mm: exact area 7.995 < 8.0 -> violation,
            #          round(7.995, 2) = 8.0 -> HAB020 IS SILENT
            #   F-336  room 10 m², glazing 1.246: ratio 0.1246 < 1/8 -> violation,
            #          round(1.246, 2) = 1.25 -> ratio exactly 0.125 -> HAB031 IS SILENT
            #   F-256  two windows 1000x546: exact sum 1.092 < 1.09375 -> violation,
            #          0.55 + 0.55 = 1.10 -> HAB031 IS SILENT (rounding BEFORE the sum)
            #
            # All three misses go the same way: the building looks BETTER than it
            # actually is. That is not a coincidence but a property of round-to-
            # nearest applied to a value compared against a lower threshold.
            #
            # Display does not suffer: rule messages print `:g` and `:.2f`, and full
            # precision looks the same to them.
            derived_area = w.width_mm * w.height_mm / _MM2_PER_M2
            area_measured = True
        if room is None or room.id not in polys:
            note = "window's room is missing or has no measurable boundary"
            status = WindowStatus.ROOM_UNMEASURABLE
        else:
            ring = LineString(polys[room.id].exterior.coords)
            _, env_rings = envelopes.get(room.level_id, (None, []))
            if w.location is not None:
                pt = Point(w.location)
                if ring.distance(pt) <= tol and _on_any_ring(env_rings, pt, tol):
                    verified = True
                    status = WindowStatus.VERIFIED
                else:
                    # THE POINT EXISTS and it is NOT on the exterior contour: geometry said NO.
                    status = WindowStatus.NOT_ON_ENVELOPE
                    note = ("window location is not on the room's envelope-exterior "
                            "boundary (shaft/interior window)")
            elif w.host_wall_id and w.host_wall_id in walls_by_id:
                seg = LineString(walls_by_id[w.host_wall_id].curve)
                need = thr.window_host_min_overlap_mm
                on_room = _seg_ring_overlap(seg, [ring], tol) >= need
                on_env = _seg_ring_overlap(seg, env_rings, tol) >= need
                if on_room and on_env:
                    verified = True
                    status = WindowStatus.VERIFIED
                else:
                    # THE HOST WALL WAS FOUND and it lies elsewhere: geometry said NO.
                    status = WindowStatus.NOT_ON_ENVELOPE
                    note = ("host wall does not lie on the room's envelope-exterior "
                            "boundary (shaft/interior wall)")
            else:
                # Neither a point nor a RESOLVABLE host wall. This also covers a
                # window whose `host_wall_id` is named but the wall itself is
                # NOT in the model — that is, "we were not given the walls,"
                # not "the window hangs in mid-air."
                status = WindowStatus.UNPLACEABLE
                note = ("window has no location and no resolvable host wall — "
                        "hosted in nothing (fabricated?)")
        rep.windows[w.id] = WindowDerivation(
            window_id=w.id, room_id=w.room_id, verified=verified, status=status,
            derived_area_m2=derived_area, area_measured=area_measured, note=note,
        )
        if w.room_id:
            (window_read_rooms if status.is_read else window_unread_rooms).add(w.room_id)
        if verified and w.room_id:
            verified_by_room.setdefault(w.room_id, []).append(w.id)
            # 🔴 A MADE-UP AREA IS NOT AN AREA (F-254, 30.08.2026).
            # `area_measured` was computed, written to the report, and NOT
            # ASKED FOR here — our named defect class: the value exists and
            # nobody reads it. We take the value DECLARED BY THE AUTHOR as
            # before (otherwise we would relax strictness on every authored
            # input while measuring nothing), and we do not take a
            # SUBSTITUTED one at all.
            if area_measured:
                area = derived_area
            elif w.area_source == "nominal":
                area = 0.0
                nominal_area_rooms.add(w.room_id)
            else:
                area = w.area_m2 or 0.0
            verified_area_by_room[w.room_id] = (
                verified_area_by_room.get(w.room_id, 0.0) + (area or 0.0)
            )

    # --- room scalars: derived area, verified windows, mismatches -----------------
    derived_rooms: list[Room] = []
    for r in model.rooms:
        p = polys.get(r.id)
        # Rounding removed along with the other three — see the law at the first window.
        derived_area = p.area / _MM2_PER_M2 if p is not None else None
        mismatch = False
        if derived_area is not None:
            diff = abs(derived_area - r.area_m2)
            if diff > thr.area_mismatch_abs_m2 and (
                derived_area <= 0.0 or diff / max(derived_area, 1e-9) > thr.area_mismatch_rel
            ):
                mismatch = True
        win_ids = tuple(sorted(verified_by_room.get(r.id, [])))
        # The sum is WITHOUT rounding, and so are the addends: F-256 — the
        # accumulated error of rounded addends pushed the room past the 1:8
        # threshold.
        win_area = verified_area_by_room.get(r.id, 0.0)
        claim_unbacked = bool(r.has_window and not win_ids)
        rep.rooms[r.id] = RoomDerivation(
            room_id=r.id, declared_area_m2=r.area_m2, derived_area_m2=derived_area,
            area_mismatch=mismatch, declared_has_window=r.has_window,
            verified_window_ids=win_ids, verified_window_area_m2=win_area,
            window_claim_unbacked=claim_unbacked,
            function_upgraded_from_name=(r.id in upgraded),
            unclassified=(r.id in unclassified),
            # Unread EXACTLY when a window for this room was found and none of
            # its windows gave a definite answer. A room that no window names
            # remains "read" — see the boundary in `RoomDerivation`.
            window_fact_readable=not (r.id in window_unread_rooms
                                      and r.id not in window_read_rooms),
            window_area_measured=(r.id not in nominal_area_rooms),
        )
        derived_rooms.append(r.model_copy(update={
            "function": derived_functions[r.id],
            "function_source": function_sources[r.id],
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
