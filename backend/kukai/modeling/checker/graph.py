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
#: THE GROUND PLANE. Not "anywhere that is not indoors" — the street you can stand on.
#: One node per building because a street IS one place: two doors at grade on opposite
#: facades genuinely are connected, you walk around the building.
#:
#: ONLY a door on a level the model certifies as GRADE (`ground_level_ids`) may touch
#: it. That restriction is the whole meaning of the node, and it is load-bearing:
#: reaching OUTSIDE is what every egress rule reads as "reached the ground".
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


def open_air_node(door_id: str) -> str:
    """Canonical node id for the open air behind ONE above-grade exterior door.

    A balcony/terrace/roof door leads somewhere real that this model does not
    describe — there is no room, no slab, no railing on the far side. The honest
    encoding is a node of its own, per DOOR (never per level: two balconies on floor 3
    are not connected to each other), with exactly one edge. It is a dead end by
    construction, so it can carry no path anywhere, and the door still EXISTS in the
    graph instead of being silently deleted from it."""
    return f"open_air:{door_id}"


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

    Nodes: every room id + the synthetic OUTSIDE (grade) sentinel + one `stair:<id>`
    per stair run + one `open_air:<door_id>` per ABOVE-GRADE exterior door.
    Edges:
      - interior door(A,B)  -> edge(A, B, kind="door", door_id=...)
      - exterior door AT GRADE
                            -> edge(room, OUTSIDE, kind="exterior", door_id=...)
      - exterior door ABOVE GRADE (balcony / terrace / roof exit)
                            -> edge(room, open_air_node(door), kind="open_air",
                                    door_id=...) — a DEAD END, never OUTSIDE
      - stair run           -> edge(stair_node, landing_room) for each distinct landing,
                               bridging consecutive levels' landings through the stair node.

    WHY the grade split (the defect it closes, measured 2026-08-03): with one OUTSIDE
    node for the whole building, an exterior door on EVERY floor welded every floor into
    a single connected component through the street. A 3-storey building with ZERO
    stairs and no vertical connection whatsoever then read PASS: HAB010 asked "does this
    level reach a ground-level stair landing" and the answer travelled floor 3 -> street
    -> floor 1. The rule could not fail. Worse, the verdict's own first-round advice is
    "add a building entrance", so the tool taught the model to disarm it.

    The derivation already KNEW: `DerivationReport.above_grade_exterior_door_ids` names
    exactly these doors and HAB061 already prints "treated as a balcony/terrace door,
    not ground egress" for each. The graph simply did not obey what the report said.
    `ground_level_ids` is the single place that answers "is this level grade" (elevation
    band + a confirmed envelope door), so it is asked here rather than re-guessed.
    """
    g: nx.Graph = nx.Graph()

    # nodes -------------------------------------------------------------
    for r in model.rooms:
        g.add_node(r.id, kind="room", level_id=r.level_id, function=r.function)
    g.add_node(OUTSIDE, kind="outside")
    for s in model.stairs:
        g.add_node(stair_node(s.id), kind="stair", stair_id=s.id)

    room_ids = {r.id for r in model.rooms}
    #: Levels that ARE the ground plane. Under v1 this is "every level holding an
    #: exterior door", so every exterior door reaches OUTSIDE exactly as before and
    #: this whole branch is a no-op — v1 stays bit-for-bit (flags.py contract).
    grade_levels = ground_level_ids(model)

    # door edges --------------------------------------------------------
    for d in model.doors:
        if d.id in exclude_door_ids:
            continue
        if d.is_exterior:
            room = d.from_room_id if d.from_room_id in room_ids else d.to_room_id
            if room in room_ids:
                if d.level_id in grade_levels:
                    g.add_edge(room, OUTSIDE, kind="exterior", door_id=d.id)
                else:
                    # Above grade: you step out, and the model knows nowhere to step to.
                    oa = open_air_node(d.id)
                    g.add_node(oa, kind="open_air", level_id=d.level_id, door_id=d.id)
                    g.add_edge(room, oa, kind="open_air", door_id=d.id)
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


def open_air_nodes(graph: nx.Graph) -> list[str]:
    """Every dead-end node behind an above-grade exterior door (kind == 'open_air')."""
    return sorted(n for n, attrs in graph.nodes(data=True)
                  if attrs.get("kind") == "open_air")


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
    """The interior room of every exterior door AT GRADE — the room you step into when
    you walk in off the street.

    Robust to which side (from/to) the room landed on: a real extractor sets a door's
    FromRoom/ToRoom from its facing, not a semantic inside/outside, so the interior room can
    be on either side; take whichever side is non-null.

    GRADE-ONLY (2026-08-03, same defect as the OUTSIDE node): a balcony door on floor 3
    is not a building entrance, and counting it as one made HAB001 unable to fail — every
    floor trivially "reachable from an entrance" because every floor had one of its own.
    Under v1 `ground_level_ids` returns every level holding an exterior door, so the
    filter removes nothing and the v1 answer is unchanged.

    FALLBACK, deliberate: when NO level is grade (the derivation found no exterior door
    inside the band — e.g. the only entrance is up a flight of external steps) the filter
    is skipped and every exterior door counts. Otherwise this helper would report the
    checker's own blindness as "the building is sealed", in the confident voice of a
    finding. A building with no exterior door AT ALL still yields [] — that is a real
    defect, not blindness, and HAB001 must keep saying so.
    """
    grade = ground_level_ids(model)
    out: list[str] = []
    for d in model.doors:
        if not d.is_exterior:
            continue
        if grade and d.level_id not in grade:
            continue  # balcony / terrace / roof exit — not a way IN off the street
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
    #: A balcony is not a way out of the apartment into the building. Counting its door
    #: as an entrance made HAB002 accuse every flat with a balcony of having "2 entrances
    #: into public circulation" — a false BLOCKING that arrived with the same single
    #: OUTSIDE node that made HAB010 unable to fail.
    open_air = set(open_air_nodes(graph))

    def is_public_node(node: str) -> bool:
        if node == OUTSIDE:
            return True
        if node in open_air:              # dead end behind an above-grade door
            return False
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
