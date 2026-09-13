"""Connectivity graph + apartment derivation for the checker (design §4/§5).

Pure functions over a SpatialModel. The graph is the substrate every connectivity/
egress/vertical rule queries. Lengths are mm, areas m**2 (foundation contract)."""
from __future__ import annotations

import math
from collections import defaultdict

import networkx as nx
from pydantic import BaseModel, ConfigDict
from shapely.geometry import Polygon

from kir.checker.flags import checker_v2_enabled
from kir.checker.function_provenance import (
    is_authored as function_is_authored,
)
from kir.checker.spatial_model import (
    Door, Level, Room, RoomFunction, SpatialModel, Stair,
    OUTSIDE_ID as _OUTSIDE_ID,
)

# --- node/sentinel/attribute vocabulary (fixed here; rules must reuse) ---
#: THE GROUND PLANE. Not "anywhere that is not indoors" — the street you can stand on.
#: One node per building because a street IS one place: two doors at grade on opposite
#: facades genuinely are connected, you walk around the building.
#:
#: ONLY a door on a level the model certifies as GRADE (`ground_level_ids`) may touch
#: it. That restriction is the whole meaning of the node, and it is load-bearing:
#: reaching OUTSIDE is what every egress rule reads as "reached the ground".
#: Ground. The name is declared in `spatial_model` together with the
#: dictionary of reserved names: the same place carries the refusal for an
#: author id that collided with it (F-264). It is kept here as a NAME, not a
#: copied string, so the two carriers cannot drift apart.
OUTSIDE: str = _OUTSIDE_ID

#: 🔴 THE PROVENANCE OF A VERTICAL CONNECTION LIVES ON THE EDGE ITSELF
#: (07.09.2026).
#:
#: WHY, BY MEASUREMENT. On 07.09 HAB003/HAB010 learned to ask who named the
#: function of the landing REACHED. The question must be asked of the PATH.
#: The discriminator was reproduced by execution: a three-story building, the
#: landing on the MIDDLE floor identified by furnishing — `unverifiable_levels`
#: named ONE level (L1), whereas by what was actually read, NEITHER of the
#: two has a way down: the only road from L2 downward runs through that same
#: guessed landing. The cost over 14 runs (N=3..6 × a guess on each
#: intermediate floor): 20 levels went UNNAMED, apartments 34 of 34.
#:
#: WHY AN EDGE, AND NOT ONE MORE QUESTION TO THE ROOM. The guess concerns
#: exactly the VERTICAL transition: a horizontal connection through a door
#: does not depend on room function at all. The carrier must sit exactly
#: where the connection itself sits, or every consumer of connectivity will
#: end up re-deriving the same thing from both ends.
#:
#: THIS DOES NOT TOUCH TOPOLOGY, AND THIS IS MEASURED: 26 nodes / 25 edges
#: before and after, the landing choice (`_landing_room_on_level`) does not
#: shift by a single step. Exactly one thing changes — the connection NAMES
#: what it stands on.
EDGE_READ: str = "read"
#: A vertical transition is held up by a landing whose function was NOT named by the author.
EDGE_GUESSED: str = "guessed"


def stair_edge_provenance(landing: Room) -> str:
    """`read` or `guessed` — by the kind of the landing function's source."""
    return EDGE_READ if function_is_authored(landing.function_source) else EDGE_GUESSED


def read_only_view(graph: nx.Graph) -> nx.Graph:
    """The same graph WITHOUT vertical transitions that stand on a guess.

    A view (`nx.restricted_view`), not a copy: the real graph stays whole,
    and no consumer of topology sees a difference. It is queried by exactly
    two readers — the unverifiedness counter and the rule's body — and both
    must query the SAME iteration, or the coverage line and the finding will
    drift apart.
    """
    guessed = [(a, b) for a, b, d in graph.edges(data=True)
               if d.get("provenance") == EDGE_GUESSED]
    if not guessed:
        return graph
    return nx.restricted_view(graph, (), guessed)


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


#: The tolerance with which two boundary edges are considered ONE segment, mm.
#:
#: The number was NOT fitted to the result: measurement 18.08.2026 on the
#: owner's tower gave EXACTLY THE SAME number of pairs (603) at tolerances of
#: 10, 50, 200, and 600 mm. The separation is structural, not threshold-based,
#: and the tolerance here is protection against floating-point arithmetic, not
#: a setting.
_SEPARATOR_TOUCH_MM = 50.0


def _boundary_edges(room: Room) -> list[tuple[tuple[float, float],
                                              tuple[float, float]]]:
    b = room.boundary or []
    return [(b[i], b[(i + 1) % len(b)]) for i in range(len(b))]


def _share_a_segment(r1: Room, r2: Room) -> bool:
    """Whether two rooms share a COMMON BOUNDARY SEGMENT (not merely touching)."""
    for a0, a1 in _boundary_edges(r1):
        dx, dy = a1[0] - a0[0], a1[1] - a0[1]
        length_sq = dx * dx + dy * dy
        if length_sq <= 1.0:
            continue
        length = math.sqrt(length_sq)
        for b0, b1 in _boundary_edges(r2):
            params: list[float] = []
            for px, py in (b0, b1):
                t = ((px - a0[0]) * dx + (py - a0[1]) * dy) / length_sq
                cx, cy = a0[0] + t * dx, a0[1] + t * dy
                if math.hypot(px - cx, py - cy) > _SEPARATOR_TOUCH_MM:
                    params = []
                    break
                params.append(t)
            if not params:
                continue
            lo, hi = sorted(params)
            lo, hi = max(lo, 0.0), min(hi, 1.0)
            if (hi - lo) * length > _SEPARATOR_TOUCH_MM:
                return True
    return False


def _separator_pairs(model: SpatialModel) -> list[tuple[str, str, str]]:
    """Pairs of rooms OPEN to each other across a separation line.

    🔴 A SHARED SEPARATOR ID IS NOT A WITNESS, AND THIS WAS BOUGHT BY A
    CONTROL ON 18.08.2026. The first edit connected, as a CLIQUE, every room
    naming the same separator. On the owner's tower **34 separators border
    more than two rooms**, and the clique produced **19 "apartments" with two
    or more kitchens** — that is, two apartments merged into one. A false
    merge is worse than an undercount: it does not understate the number, it
    LIES ABOUT THE DWELLING'S COMPOSITION, and composition is exactly the
    subject of rules HAB002/003/004.

    The witness is a SHARED BOUNDARY SEGMENT. With it, false merges are **0**
    (control: not a single apartment with two kitchens), pairs 604 instead of
    765 by clique.

    WHY THE SEPARATOR'S OWN GEOMETRY IS NOT NEEDED, even though it looks more
    correct. Both variants were measured: projecting boundaries onto the
    separator's segment gives 603 pairs, a shared boundary segment gives 604,
    and they diverge by EXACTLY ONE pair out of 604 (0.17%). The second does
    not require dragging separator curves into the model, i.e. it covers the
    same ground with a smaller surface. The discrepancy is named here, not
    hidden: if it ever becomes important, this is where to start.

    A shared `separator_id` still remains a MANDATORY condition: without it,
    a "shared boundary segment" exists for any two rooms on opposite sides of
    a SHARED WALL, and we would have connected neighboring apartments.
    """
    by_separator: dict[str, list[Room]] = defaultdict(list)
    for room in model.rooms:
        for sid in (room.separator_ids or ()):
            by_separator[sid].append(room)
    pairs: dict[tuple[str, str], str] = {}
    for sid, rooms in by_separator.items():
        rooms = sorted(rooms, key=lambda r: r.id)
        for i in range(len(rooms)):
            for j in range(i + 1, len(rooms)):
                key = (rooms[i].id, rooms[j].id)
                if key in pairs:
                    continue
                if _share_a_segment(rooms[i], rooms[j]):
                    pairs[key] = sid
    return [(a, b, sid) for (a, b), sid in sorted(pairs.items())]


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

    def _link(a: str, b: str, kind: str, **ids: str) -> None:
        """Add a connection WITHOUT ERASING one already standing between the
        same nodes.

        🔴 IT USED TO BE `g.add_edge(a, b, kind=..., door_id=...)`, AND THIS
        LOST CONNECTIONS SILENTLY (29.08.2026, audit finding F-263). `nx.Graph`
        holds EXACTLY ONE edge between a pair of nodes, and `add_edge` on an
        existing edge UPDATES its attributes. Hence two losses, different in
        mechanics:

          * two legitimate doors between the same pair of rooms left
            `door_id` holding only the LAST one. The count of entries into
            an apartment and the egress rules saw fewer real doors — without
            a single refusal;
          * a separator processed AFTER a door overwrote `kind` to
            `"separator"`. The door did not disappear (`door_id` was still
            there), but a consumer asking for `kind == "door"` lost it.

        A multigraph (`MultiGraph`) would change the topology under every
        consumer of connectivity; here the topology is correct — what was
        wrong was the BOOKKEEPING. So the edge stays singular, and everything
        that sits on it accumulates: `door_ids`, `separator_ids`, `kinds`.
        The one field ever queried (`door_id`) is replaced with `door_ids` —
        keeping it as an alias would have preserved the same half-truth.
        """
        data = g.get_edge_data(a, b)
        if data is None:
            g.add_edge(a, b, kind=kind, kinds=(kind,))
            data = g.edges[a, b]
        else:
            if kind not in data["kinds"]:
                data["kinds"] = data["kinds"] + (kind,)
            # `kind` — the FIRST one set, not the last: it was exactly what
            # was being silently overwritten. The full truth lives in `kinds`.
        for field, value in ids.items():
            plural = field + "s"
            data[plural] = tuple(dict.fromkeys(data.get(plural, ()) + (value,)))

    room_ids = {r.id for r in model.rooms}
    #: Levels that ARE the ground plane. The height band has been applied
    #: UNCONDITIONALLY since 18.08.2026 (the owner's decision, see
    #: `ground_level_ids`): "ground" must mean the same thing regardless of
    #: the lever. On live data this is inert — L0 does not declare
    #: `is_exterior` at all — and it changes the answer where exteriority is
    #: DERIVED.
    grade_levels = ground_level_ids(model)

    # door edges --------------------------------------------------------
    for d in model.doors:
        if d.id in exclude_door_ids:
            continue
        if d.is_exterior:
            room = d.from_room_id if d.from_room_id in room_ids else d.to_room_id
            if room in room_ids:
                if d.level_id in grade_levels:
                    _link(room, OUTSIDE, "exterior", door_id=d.id)
                else:
                    # Above grade: you step out, and the model knows nowhere to step to.
                    oa = open_air_node(d.id)
                    g.add_node(oa, kind="open_air", level_id=d.level_id, door_id=d.id)
                    _link(room, oa, "open_air", door_id=d.id)
            continue
        a, b = d.from_room_id, d.to_room_id
        if a in room_ids and b in room_ids:
            _link(a, b, "door", door_id=d.id)

    # separator edges (open plan) ---------------------------------------
    for a, b, sid in _separator_pairs(model):
        _link(a, b, "separator", separator_id=sid)

    # stair vertical edges ---------------------------------------------
    for s in model.stairs:
        sn = stair_node(s.id)
        for lvl in {s.base_level_id, s.top_level_id}:
            landing = _landing_room_on_level(model, lvl, footprint=s.footprint)
            if landing is not None:
                # Provenance is set HERE, where the connection is born: room
                # function chose the landing, so the edge carries the kind of
                # THAT function.
                g.add_edge(sn, landing.id, kind="stair", stair_id=s.id,
                           function_source=landing.function_source,
                           provenance=stair_edge_provenance(landing))

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

    Gated by ELEVATION: only levels within thr-default 1500 mm of the lowest OCCUPIED
    level count as grade. An exterior door on an upper floor is a balcony/terrace, and
    must never turn floor 3 into 'ground' (roadmap probe D2 collapse). The band constant
    mirrors Thresholds.ground_elevation_band_mm (kept in sync by a guard test) because
    this helper predates threshold injection.

    🔴 THE BAND BECAME UNCONDITIONAL ON 18.08.2026 — THE OWNER'S DECISION.
    Before that day it applied only under `KUKAI_CHECKER_V2`, and the flag is
    off by default in prod.

    MEASUREMENT ON A REAL TOWER (`k2_ar_rd_v15`, 2442 rooms, 2096 doors),
    after running `derive`'s inference:

        exterior doors                257   (0 in the RAW model — see below)
        levels with an exterior door   41
        with the band                   1   <- ground
        without the band                41   <- forty-one floors become "ground"

    Without the band, a balcony door on the fortieth floor turns that floor
    into "ground," and egress rules then judge nonsense.

    🔴 WHY THIS DOES NOT BREAK `flags.py`'s "v1 bit-for-bit" PROMISE ON LIVE
    DATA, AND THIS IS MEASURED, NOT ASSUMED. On the L0 path, `is_exterior` is
    not declared AT ALL — `design_check` sets a literal `False` and states
    this verbatim: "exteriority is derived by `derive.py` from positive
    membership in the envelope ring; declaring it here would mean handing the
    checker the answer to the question it is asking." Verified by execution:
    on the tower, the raw model gives **0 exterior doors out of 2096**, so
    under v1 the set of ground levels is empty, and there is NOTHING for the
    band to filter. Exteriority appears only after `derive`, and `derive` is
    called from `engine.run` under v2.

    Bottom line: the fix changes the answer exactly where exteriority is
    derived, and is inert where nobody declared it. The only casualty is the
    synthetic guard that declared `is_exterior` BY HAND; it is rewritten, not
    removed, and it carries this decision.
    """
    ext_levels = {d.level_id for d in model.doors if d.is_exterior}
    occupied = [lvl for lvl in model.levels
                if any(r.level_id == lvl.id for r in model.rooms)]
    if not occupied:
        return set()
    # 🔴 AN UNKNOWN ELEVATION IS NOT A SMALL ONE. A level addressed by
    # `element_id` in an existing document enters the model without a number
    # (see `Level.elevation_mm`); folding it into `min()` as 0.0 would make the
    # lowest floor of the building out of whatever floor the author happened to
    # reference. So the band is computed over levels that HAVE a number, and a
    # level without one joins the ground set only when NOTHING has a number —
    # i.e. when there is nothing to be lower than, which is exactly the
    # single-level case the production program hits.
    known = [lvl.elevation_mm for lvl in occupied if lvl.elevation_mm is not None]
    band = _GROUND_ELEVATION_BAND_MM
    if not known:
        return {lvl.id for lvl in model.levels if lvl.id in ext_levels}
    min_elev = min(known)
    return {
        lvl.id for lvl in model.levels
        if lvl.id in ext_levels and lvl.elevation_mm is not None
        and lvl.elevation_mm <= min_elev + band
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

        # v2: single technical/other/bathroom closets off public circulation are SERVICE
        # rooms, not apartments — real buildings' electrical rooms must not demand an
        # entryway (HAB004 false-BLOCKING, roadmap probe H).
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
                    # ALL doors of this edge, not the last one: two can
                    # legitimately stand between one pair of rooms, and an
                    # entry lost here reduced the apartment's entry count
                    # without a refusal.
                    entrance_doors.update(graph.edges[room, nbr].get("door_ids", ()))

        # entryway rooms of this component (entry-hall rooms)
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
