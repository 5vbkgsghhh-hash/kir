"""Connectivity graph + apartment derivation for the checker (design §4/§5).

Pure functions over a SpatialModel. The graph is the substrate every connectivity/
egress/vertical rule queries. Lengths are mm, areas m**2 (foundation contract)."""
from __future__ import annotations

import networkx as nx
from pydantic import BaseModel, ConfigDict
from shapely.geometry import Polygon

from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import (
    Door, Level, Room, SpatialModel, Stair, RoomFunction,
)

# --- node/sentinel/attribute vocabulary (fixed here; rules must reuse) ---
OUTSIDE: str = "OUTSIDE"

#: Functions that count as PUBLIC CIRCULATION for apartment derivation (design §4).
#: PUBLIC (not underscore-private): the rule modules import this set verbatim.
PUBLIC_CIRCULATION: frozenset[RoomFunction] = frozenset({
    RoomFunction.КОРИДОР,
    RoomFunction.ЛЕСТНИЦА,
    RoomFunction.ЛИФТ_ХОЛЛ,
    RoomFunction.ВХОДНАЯ_ГРУППА,
})


#: v2: a private component is an APARTMENT only if it holds at least one of these
#: functions; single тех/прочее/санузел closets off the corridor are SERVICE rooms and
#: must not be held to apartment rules (HAB002/003/004) — the confirmed false-BLOCKING
#: family (roadmap probe H).
APARTMENT_MARKERS: frozenset[RoomFunction] = frozenset({
    RoomFunction.ЖИЛАЯ,
    RoomFunction.КУХНЯ,
    RoomFunction.ПРИХОЖАЯ,
})


def is_public(function: RoomFunction) -> bool:
    """True iff `function` is public circulation (design §4 apartment-boundary predicate)."""
    return function in PUBLIC_CIRCULATION


def stair_node(stair_id: str) -> str:
    """Canonical graph node id for a stair run (singular id-builder)."""
    return f"stair:{stair_id}"


class Apartment(BaseModel):
    """A derived apartment (design §4): a connected component of private rooms plus the
    interior door(s) that link it to public circulation / OUTSIDE (its entrance(s)).

    Frozen so apartments are hashable and safe to pass around between rules (D1)."""
    model_config = ConfigDict(frozen=True)

    apartment_id: str
    room_ids: frozenset[str]
    entrance_door_ids: frozenset[str] = frozenset()
    prihozhaya_ids: frozenset[str] = frozenset()


def _landing_room_on_level(
    model: SpatialModel, level_id: str,
    footprint: list[tuple[float, float]] | None = None,
) -> Room | None:
    """The лестница room on `level_id` (the stair's landing on that level), or None.

    v2 (+footprint): choose the landing whose boundary polygon overlaps the stair's
    plan footprint the most — never plain list order, which mis-attaches stairs in
    multi-core buildings (roadmap probe L2). Falls back to the single unambiguous
    landing, else the v1 first-match."""
    candidates = [
        r for r in model.rooms
        if r.level_id == level_id and r.function is RoomFunction.ЛЕСТНИЦА
    ]
    if not candidates:
        return None
    if checker_v2_enabled() and footprint and len(footprint) >= 3 and len(candidates) > 1:
        fp = Polygon(footprint)
        if not fp.is_valid:
            fp = fp.buffer(0)
        if not fp.is_empty and fp.area > 0.0:
            best, best_area = None, 0.0
            for r in candidates:
                if len(r.boundary) < 3:
                    continue
                rp = Polygon(r.boundary)
                if not rp.is_valid:
                    rp = rp.buffer(0)
                if rp.is_empty:
                    continue
                inter = fp.intersection(rp).area
                if inter > best_area:
                    best, best_area = r, inter
            if best is not None:
                return best
            return None  # v2: ambiguous landings, none under the footprint — no edge
    return candidates[0]


def build_graph(model: SpatialModel,
                exclude_door_ids: frozenset[str] | set[str] = frozenset()) -> nx.Graph:
    """Build the connectivity graph (design §5).

    `exclude_door_ids` (v2): doors whose declared adjacency GEOMETRY CONTRADICTED
    (phantom doors, derive.py) contribute no edges — declared-only connectivity is not
    walkable.

    Nodes: every room id + the synthetic OUTSIDE sentinel + one `stair:<id>` per stair run.
    Edges:
      - interior door(A,B)  -> edge(A, B, kind="door", door_id=...)
      - exterior door       -> edge(room, OUTSIDE, kind="exterior", door_id=...)
      - stair run           -> edge(stair_node, landing_room) for each distinct landing,
                               bridging consecutive levels' landings through the stair node.
    """
    g: nx.Graph = nx.Graph()

    # nodes -------------------------------------------------------------
    for r in model.rooms:
        g.add_node(r.id, kind="room", level_id=r.level_id, function=r.function)
    g.add_node(OUTSIDE, kind="outside")
    for s in model.stairs:
        g.add_node(stair_node(s.id), kind="stair", stair_id=s.id)

    room_ids = {r.id for r in model.rooms}

    # door edges --------------------------------------------------------
    for d in model.doors:
        if d.id in exclude_door_ids:
            continue
        if d.is_exterior:
            room = d.from_room_id if d.from_room_id in room_ids else d.to_room_id
            if room in room_ids:
                g.add_edge(room, OUTSIDE, kind="exterior", door_id=d.id)
            continue
        a, b = d.from_room_id, d.to_room_id
        if a in room_ids and b in room_ids:
            g.add_edge(a, b, kind="door", door_id=d.id)

    # stair vertical edges ---------------------------------------------
    for s in model.stairs:
        sn = stair_node(s.id)
        for lvl in {s.base_level_id, s.top_level_id}:
            landing = _landing_room_on_level(model, lvl, footprint=s.footprint)
            if landing is not None:
                g.add_edge(sn, landing.id, kind="stair", stair_id=s.id)

    return g


def stair_nodes(graph: nx.Graph) -> list[str]:
    """Every graph node that represents a stair run (kind == 'stair'), sorted."""
    return sorted(n for n, attrs in graph.nodes(data=True) if attrs.get("kind") == "stair")


def occupied_levels(model: SpatialModel) -> list[Level]:
    """Levels that hold at least one room, sorted by their `index` (design §5)."""
    occupied = {r.level_id for r in model.rooms}
    return sorted(
        (lvl for lvl in model.levels if lvl.id in occupied),
        key=lambda lvl: lvl.index,
    )


def ground_level_ids(model: SpatialModel) -> set[str]:
    """Levels that carry at least one exterior (building-entrance) door — the ground levels.

    v2: additionally gated by ELEVATION — only levels within
    thr-default 1500 mm of the lowest OCCUPIED level count as grade. An exterior door on
    an upper floor is a balcony/terrace, and must never turn floor 3 into 'ground'
    (roadmap probe D2 collapse). The band constant mirrors
    Thresholds.ground_elevation_band_mm (kept in sync by a guard test) because this
    helper predates threshold injection."""
    ext_levels = {d.level_id for d in model.doors if d.is_exterior}
    if not checker_v2_enabled():
        return ext_levels
    occupied = [lvl for lvl in model.levels
                if any(r.level_id == lvl.id for r in model.rooms)]
    if not occupied:
        return set()
    min_elev = min(lvl.elevation_mm for lvl in occupied)
    band = _GROUND_ELEVATION_BAND_MM
    return {
        lvl.id for lvl in model.levels
        if lvl.id in ext_levels and lvl.elevation_mm <= min_elev + band
    }


#: v2 grade band (mm) — see ground_level_ids docstring; == Thresholds.ground_elevation_band_mm.
_GROUND_ELEVATION_BAND_MM: float = 1500.0


def building_entrance_rooms(model: SpatialModel) -> list[str]:
    """The interior room of every exterior door — the room you step into from OUTSIDE.

    Robust to which side (from/to) the room landed on: a real extractor sets a door's
    FromRoom/ToRoom from its facing, not a semantic inside/outside, so the interior room can
    be on either side; take whichever side is non-null.
    """
    out: list[str] = []
    for d in model.doors:
        if not d.is_exterior:
            continue
        r = d.from_room_id if d.from_room_id is not None else d.to_room_id
        if r is not None:
            out.append(r)
    return sorted(out)


def derive_apartments(model: SpatialModel, graph: nx.Graph) -> list[Apartment]:
    """Derive apartments from the connectivity graph (design §4).

    An apartment = a maximal set of PRIVATE rooms connected to one another by interior
    doors, whose only links to public circulation / OUTSIDE are its entrance door(s).
    Algorithm: remove public-circulation nodes (+ OUTSIDE + stair nodes); each connected
    component of the remaining private rooms is one apartment; the door(s) linking that
    component to public circulation / OUTSIDE are its entrance(s).
    """
    func_by_id: dict[str, RoomFunction] = {r.id: r.function for r in model.rooms}
    apt_id_by_room: dict[str, str | None] = {r.id: r.apartment_id for r in model.rooms}

    def is_public_node(node: str) -> bool:
        if node == OUTSIDE:
            return True
        if node not in func_by_id:        # stair node or other non-room
            return True
        return is_public(func_by_id[node])

    # private subgraph: keep only non-public ROOM nodes
    private_nodes = [
        r.id for r in model.rooms if not is_public(r.function)
    ]
    private = graph.subgraph(private_nodes)

    v2 = checker_v2_enabled()
    apartments: list[Apartment] = []
    for component in nx.connected_components(private):
        room_ids = frozenset(component)

        # v2: single тех/прочее/санузел closets off public circulation are SERVICE
        # rooms, not apartments — real buildings' electrical rooms must not demand a
        # прихожая (HAB004 false-BLOCKING, roadmap probe H).
        if v2 and not any(
            func_by_id.get(rid) in APARTMENT_MARKERS for rid in component
        ):
            continue

        # entrances: door/exterior edges from a component room to a public node
        entrance_doors: set[str] = set()
        for room in component:
            for nbr in graph.neighbors(room):
                if nbr in component:
                    continue
                if is_public_node(nbr):
                    edge = graph.edges[room, nbr]
                    if edge.get("door_id"):
                        entrance_doors.add(edge["door_id"])

        # прихожая rooms of this component (entry-hall rooms)
        prihozhaya = frozenset(
            rid for rid in component
            if func_by_id.get(rid) is RoomFunction.ПРИХОЖАЯ
        )

        # id from stamped apartment_id when the component agrees on one
        stamped = {apt_id_by_room.get(rid) for rid in component} - {None}
        if len(stamped) == 1:
            apartment_id = next(iter(stamped))
        else:
            # content-stable synthetic id (review fix): bound to the component's rooms,
            # not networkx discovery order, so the label can't drift across versions.
            apartment_id = f"apt:{min(room_ids)}"

        apartments.append(Apartment(
            apartment_id=apartment_id,
            room_ids=room_ids,
            entrance_door_ids=frozenset(entrance_doors),
            prihozhaya_ids=prihozhaya,
        ))

    apartments.sort(key=lambda a: a.apartment_id)
    return apartments
