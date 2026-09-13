"""PREDICATE B for room adjacency — `opening_point_touches_room`, and why it
MUST be named differently from predicate A.

One word for two different predicates is the same class of defect as a green
witness over an unread axis: both sides are certain they are talking about
the same thing, and the discrepancy reads as a fact about the building, not
as our own mistake.

═══════════════════════════════════════════════════════════════════════════
MEASURED (10.08.2026, instrument — a raw parse of `L0.jsonl`, corpus
`backend/backend/data/decompile`, machine-local)
═══════════════════════════════════════════════════════════════════════════

A = `bounded_by_same_wall` (`fold._semantic_fold`): rooms bounded by the
    HOST of a door; an edge only when there are EXACTLY two.
B = `opening_point_touches_room` (`design_check._openings.touching`): rooms
    whose polygon is within 300 mm (`OPENING_JOIN_TOL_MM`) of the door's
    POINT.

| building | doors | A edges | B edges | shared | JACCARD | A only | B only |
|---|---|---|---|---|---|---|---|
| `демо` (демо-v3)              | 5 941 | 1 035 | 3 272 | 963 | **0.288** | 72 | 2 309 |
| `13A-RD-AR-K2_v33` (v7)       | 2 096 |   975 | 1 438 | 950 | **0.649** | 25 |   488 |
| `Snowdon …Architectural` (v5) |   143 |    22 |    23 |  11 | **0.324** | 11 |    12 |
| `SOB6.2…AR_R23` (v5)          |   153 |    40 |   117 |  35 | **0.287** |  5 |    82 |

**Jaccard is NOT constant — it ranges from 0.287 to 0.649.** The discrepancy
runs in BOTH directions on every building, meaning neither predicate is a
coarsening of the other: they are two different questions. A asks "did Revit
declare that this wall separates two rooms"; B asks "does the opening's
point sit near the polygons of two rooms". They are not required to agree,
and they will not.

═══════════════════════════════════════════════════════════════════════════
A DEFECT INSIDE B, found along the way (wave 5): SILENT TRUNCATION TO TWO
═══════════════════════════════════════════════════════════════════════════

`design_check._openings` takes `near = sorted(touching(...))` and fills
`from_room_id=near[0]`, `to_room_id=near[1] if len(near) > 1`. When the point
touches THREE or more rooms, two are chosen **by the alphabetical order of
the room id** — a value that has nothing to do with either the geometry or
the building. The third and beyond vanish silently.

Measured, how many doors fall into this branch:

    `демо-v3`      distribution {0: 52, 1: 1211, 2: 3307, 3: 65, 4: 1}
                   → **66 doors truncated** (plus 1 305 doors with no point
                     at all)
    `k2_ar_rd_v7`  distribution {0: 42, 1: 573, 2: 1447, 3: 34}
                   → **34 doors truncated**

A hundred doors across two buildings is not much, and size is NOT the
argument here. The argument is that the choice of pair DEPENDS ON THE
STRING ORDER OF THE IDENTIFIERS: renumber the rooms, and the building's
adjacency changes without anything having changed. This is exactly "a
boundary set up by reasoning, not by measurement," just in the shape of a
sort.

Here there is no truncation at all: an edge is emitted for EVERY pair of
touching rooms, and their count travels in the evidence. A pair chosen by
sorting is never emitted.

A second fact of the same kind: **1 305 doors in `демо-v3` (22.0%) have
neither a point nor a frame**, and in `design_check` they silently drop out
of adjacency. Here they get the named refusal `opening_without_position`.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator, Mapping

from kir.decompile.building_graph import (
    GraphBuildError,
    GraphEdge,
    Modality,
    OutsideExtraction,
    Relation,
)

__all__ = [
    "OPENING_JOIN_TOL_MM",
    "REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO",
    "AdjacencyCensus",
    "ROOM_GEOMETRY_OK",
    "ROOM_GEOMETRY_NO_BOUNDARY",
    "ROOM_GEOMETRY_TOO_FEW_POINTS",
    "ROOM_GEOMETRY_REPAIRED",
    "ROOM_GEOMETRY_TRUNCATED",
    "ROOM_GEOMETRY_EMPTY",
    "opening_point_touches_room_edges",
]

#: The same tolerance as `design_check.OPENING_JOIN_TOL_MM` — an ASSIGNED
#: value, not derived; repeated here by reference to the owner so the two
#: predicates cannot silently drift apart on tolerance.
OPENING_JOIN_TOL_MM: float = 300.0

#: Rules that remove an edge of predicate B. A refuted edge REMAINS.
REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO = "opening_touches_fewer_than_two_rooms"
REFUSAL_NO_POSITION = "opening_without_position"
REFUSAL_NO_LEVEL = "opening_without_level"
REFUSAL_NO_MEASURED_ROOMS_ON_LEVEL = "no_measured_room_polygons_on_level"

#: WHAT HAPPENED TO THE ROOM'S BOUNDARY ON ITS WAY TO A POLYGON (F-319).
#:
#: 🔴 THE KINDS ARE SPLIT BY MEASUREMENT, NOT BY TASTE. The finding's log
#: described the case "butterfly -> `buffer(0)` -> only one lobe survived".
#: A measurement on the live corpus on 29.08 (51 008 rooms, all 81
#: decompiles with L0) found **ZERO** of that case, while dropped rooms
#: numbered 6 406, and ALL 6 406 (100%) have an EMPTY `boundary_mm`. That is
#: why "there is no boundary at all" is a separate name, not a subtype of
#: "fewer than three points": the mechanism to fix is the measured one, not
#: the described one.
ROOM_GEOMETRY_OK = "ok"
#: No boundary was captured at all — Revit either could not outline the
#: room or never placed it. The ONLY kind actually encountered in the
#: corpus.
ROOM_GEOMETRY_NO_BOUNDARY = "boundary_mm_is_empty"
#: A boundary exists, but has fewer than three points. NOT ENCOUNTERED in the corpus (0 of 6 406).
ROOM_GEOMETRY_TOO_FEW_POINTS = "boundary_has_fewer_than_three_points"
#: A self-intersection silently fixed by `buffer(0)`. NOT ENCOUNTERED in the corpus.
ROOM_GEOMETRY_REPAIRED = "self_intersecting_boundary_repaired_by_buffer0"
#: The fix split the room, and only ONE largest part was kept. Not encountered.
ROOM_GEOMETRY_TRUNCATED = "repair_split_the_room_and_only_the_largest_part_was_kept"
#: After everything, no area remained. Not encountered.
ROOM_GEOMETRY_EMPTY = "boundary_encloses_no_area"


@dataclass(frozen=True, slots=True)
class AdjacencyCensus:
    """How many openings the predicate TOUCHED — without this, "no
    adjacency" is empty.

    The same law as the CLASH census: the answer "no edges" means nothing
    until it is said how many openings the search touched, and why the rest
    dropped out.
    """

    openings_seen: int
    openings_evaluated: int
    refusals: Mapping[str, int]
    touch_degree: Mapping[int, int]
    #: How many header rooms the predicate TOOK IN HAND (addressable, with an `id`).
    rooms_seen: int = 0
    #: room -> what happened to its geometry. Only NOT `ok`: a room that
    #: arrived exactly as its author described it is not mentioned here.
    #:
    #: 🔴 WITHOUT THIS FIELD THE CENSUS ANSWERED HALF THE QUESTION. It
    #: converged on OPENINGS — "were all openings touched" — and never asked
    #: whether the predicate HAD THE GEOMETRY to answer with. A room with no
    #: boundary silently dropped out of the index, and "touched one room"
    #: became a fact about the building.
    room_geometry: Mapping[str, str] = field(default_factory=dict)

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    @property
    def rooms_faithful(self) -> int:
        """Rooms whose geometry reached the predicate exactly as captured."""
        return self.rooms_seen - len(self.room_geometry)

    def assert_balanced(self) -> None:
        if self.openings_evaluated + self.refused != self.openings_seen:
            raise GraphBuildError(
                f"перепись смежности не сходится: проёмов {self.openings_seen}, "
                f"оценено {self.openings_evaluated}, названных отказов "
                f"{self.refused}")
        # 🔴 THE SECOND CONVERGENCE, ON ROOMS. The first one enforces "no
        # opening was lost"; this one enforces "no damaged room was counted
        # twice or appeared from nowhere". A law that converges on one
        # subject is silent about the other, exactly as confidently as if it
        # had never been asked.
        if len(self.room_geometry) > self.rooms_seen:
            raise GraphBuildError(
                f"перепись комнат не сходится: комнат {self.rooms_seen}, "
                "с непостроенной или изменённой геометрией "
                f"{len(self.room_geometry)}")

    @property
    def truncated_by_design_check(self) -> int:
        """How many openings `design_check` would truncate to two rooms by sorting."""
        return sum(count for degree, count in self.touch_degree.items()
                   if degree >= 3)

    def as_census_row(self) -> dict[str, Any]:
        """A census in the SHAPE the graph carries with it (`GraphCensus`).

        🔴 WHY THE PROJECTION LIVES HERE, NOT AT THE READER. `graph_from_l0`
        used to compute this census and drop it into a `_`-variable: edges
        reached the graph, refusals did not (RV-03). A door with no
        `p0`/`bbox` produced zero edges, the refusal was named and counted,
        and the graph replied "adjacency was measured", freezing that zero
        in its artifact as a fact about the BUILDING.
        A projection written at the reader would be a second carrier of the
        same shape: a field added here would not force it to change, and the
        loss would again be silent — the same argument by which
        `BuildingGraph.to_dict` lives right next to its type.

        WHAT IS FOLDED, AND WHY. `room_geometry` travels as a COUNT BY KIND,
        not by name: a live building has tens of thousands of rooms, and a
        by-name list would turn the graph census into a copy of the side
        index. The `touch_degree` keys are STRINGS: the census travels over
        JSON, where a key can never be a number, and a record read back from
        disk must equal the one that was sent.
        """
        by_state: Counter[str] = Counter(self.room_geometry.values())
        return {
            "openings_seen": int(self.openings_seen),
            "openings_evaluated": int(self.openings_evaluated),
            "refusals": {str(name): int(count)
                         for name, count in sorted(self.refusals.items())
                         if count},
            "touch_degree": {str(degree): int(count)
                             for degree, count in sorted(
                                 self.touch_degree.items()) if count},
            "rooms_seen": int(self.rooms_seen),
            "rooms_by_geometry": {str(state): int(count)
                                  for state, count in sorted(by_state.items())
                                  if count},
        }


def _polygon(boundary: Any) -> tuple[Any, str]:
    """The room's polygon AND WHAT WAS DONE TO IT. The second value is
    mandatory.

    🔴 IT USED TO RETURN A SINGLE POLYGON OR `None`, AND BOTH WERE SILENT
    (F-319). A room with no polygon simply never made it into the index; a
    self-intersection was fixed by `buffer(0)` by picking the largest part,
    meaning A PART OF THE ROOM disappeared. Downstream, an opening that
    touched fewer than two rooms emitted `REFUTED` — a POSITIVE claim that
    "these rooms are not adjacent" — even though what the predicate lacked
    was not adjacency, but geometry.

    We are NOT reverting the `buffer(0)` fix: self-intersection is routine
    in live models. What changes is not the fix, but its SILENCE.
    """

    from shapely.geometry import Polygon
    if not boundary:
        return None, ROOM_GEOMETRY_NO_BOUNDARY
    if len(boundary) < 3:
        return None, ROOM_GEOMETRY_TOO_FEW_POINTS
    poly = Polygon([(float(x), float(y)) for x, y in boundary])
    state = ROOM_GEOMETRY_OK
    if not poly.is_valid:
        poly = poly.buffer(0)
        state = ROOM_GEOMETRY_REPAIRED
    if poly.geom_type == "MultiPolygon":
        if poly.is_empty:
            return None, ROOM_GEOMETRY_EMPTY
        poly = max(poly.geoms, key=lambda g: g.area)
        state = ROOM_GEOMETRY_TRUNCATED
    if poly.is_empty or poly.area <= 0.0:
        return None, ROOM_GEOMETRY_EMPTY
    return poly, state


def _position(element: Mapping[str, Any]) -> tuple[float, float] | None:
    """An opening's point: `p0_mm`, or if absent — the CENTER of the
    captured bbox.

    The fallback is not a guess about Revit, but the midpoint of the very
    box the read returned (measured 03.08: all 49 windows of the tower were
    captured as `bbox_only`). The provenance travels in the edge's evidence
    rather than being lost.
    """
    p0 = element.get("p0_mm")
    if p0 is not None:
        return float(p0[0]), float(p0[1])
    lo, hi = element.get("bbox_min_mm"), element.get("bbox_max_mm")
    if lo is not None and hi is not None:
        return ((float(lo[0]) + float(hi[0])) / 2.0,
                (float(lo[1]) + float(hi[1])) / 2.0)
    return None


def opening_point_touches_room_edges(
    header: Mapping[str, Any],
    elements: Mapping[str, Mapping[str, Any]],
    *,
    opening_categories: Iterable[str] = ("OST_Doors",),
    tol_mm: float = OPENING_JOIN_TOL_MM,
    known_node_ids: Iterable[str] | None = None,
) -> tuple[tuple[GraphEdge, ...], AdjacencyCensus]:
    """PREDICATE B, with no truncation to two and no silent drops.

    Returns edges and a census. Every opening lands EITHER among the
    evaluated ones OR in a named refusal — no third option is provided, and
    `assert_balanced` enforces this.

    `known_node_ids` is the set of addresses that are NODES as far as the
    caller is concerned. `None` means "the caller did not say": then every
    header room is considered addressable, as it was before 22.08.2026.
    `graph_from_l0` passes in its own node set here, because a header room
    is NOT REQUIRED to be a node.
    """
    from shapely.geometry import Point
    from shapely.strtree import STRtree

    wanted = frozenset(opening_categories)
    known = None if known_node_ids is None else frozenset(known_node_ids)

    def _is_node(room_id: str) -> bool:
        return known is None or room_id in known

    rooms = [r for r in (header.get("rooms") or []) if isinstance(r, Mapping)]
    polys: dict[str, Any] = {}
    level_of_room: dict[str, Any] = {}
    #: room -> what happened to its geometry (only NOT `ok`).
    room_geometry: dict[str, str] = {}
    #: level -> rooms whose geometry arrived not as it was captured.
    #:
    #: 🔴 COLLECTED IN THE SAME LOOP AS THE POLYGONS, AND IT CANNOT BE
    #: OTHERWISE: for an UNBUILT room, `level_of_room` is never filled in at
    #: all, so there is nothing left to ask its level from LATER. This is
    #: exactly the mechanics of the silence being fixed: a room used to
    #: vanish before anyone could notice its absence.
    tainted_by_level: dict[Any, list[str]] = defaultdict(list)
    rooms_seen = 0
    for room in rooms:
        room_id = room.get("id")
        if not isinstance(room_id, str) or not room_id:
            continue
        rooms_seen += 1
        poly, state = _polygon(room.get("boundary_mm"))
        if state != ROOM_GEOMETRY_OK:
            room_geometry[room_id] = state
            tainted_by_level[room.get("level_id")].append(room_id)
        if poly is None:
            continue
        polys[room_id] = poly
        level_of_room[room_id] = room.get("level_id")

    per_level: dict[Any, list[str]] = defaultdict(list)
    for room_id in polys:
        per_level[level_of_room.get(room_id)].append(room_id)
    trees: dict[Any, tuple[list[str], Any]] = {}
    for level_id, room_ids in per_level.items():
        room_ids.sort()
        trees[level_id] = (room_ids, STRtree([polys[r] for r in room_ids]))

    edges: list[GraphEdge] = []
    refusals: Counter[str] = Counter()
    degree: Counter[int] = Counter()
    seen = 0
    evaluated = 0
    #: room pair -> its FIRST piece of evidence + the list of ALL openings that produced it.
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    #: (opening, room outside the snapshot) — one edge each, not one per pair.
    outside_seen: set[tuple[str, str]] = set()

    for node_id in sorted(elements):
        element = elements[node_id]
        if element.get("category") not in wanted:
            continue
        seen += 1

        point = _position(element)
        if point is None:
            refusals[REFUSAL_NO_POSITION] += 1
            continue
        host = element.get("host_id")
        level_id = element.get("level_id")
        if not level_id and isinstance(host, str):
            level_id = (elements.get(host) or {}).get("level_id")
        if not level_id:
            refusals[REFUSAL_NO_LEVEL] += 1
            continue
        got = trees.get(level_id)
        if got is None:
            refusals[REFUSAL_NO_MEASURED_ROOMS_ON_LEVEL] += 1
            continue

        room_ids, tree = got
        pt = Point(point)
        probe = pt.buffer(tol_mm)
        near: list[str] = []
        for index in tree.query(probe):
            room_id = room_ids[int(index)]
            poly = polys[room_id]
            if poly.exterior.distance(pt) <= tol_mm or poly.contains(pt):
                near.append(room_id)
        near.sort()
        evaluated += 1
        degree[len(near)] += 1

        provenance = ("p0_mm" if element.get("p0_mm") is not None
                      else "bbox_centre")
        if len(near) < 2:
            # A NAMED refutation: "touched and it wasn't enough" is
            # distinguishable from "never looked". `design_check` is silent
            # here.
            touched = near[0] if near else None
            # 🔴 "NOT ADJACENT" AND "NOTHING TO CHECK WITH" ARE DIFFERENT
            # ANSWERS (F-319). If even one room on this level had geometry
            # that failed to build or was altered by a repair, the negation
            # IS NOT EARNED: the predicate may have failed to touch a room it
            # simply never had. The edge REMAINS (just as `REFUTED` remains),
            # but the strength of the claim changes — the graph stops
            # asserting a non-adjacency it never proved.
            #
            # The WHOLE level is tainted, not a specific pair, and that is
            # not sloppiness: the predicate looks up rooms via a tree keyed
            # by level, and by construction it cannot know which specific
            # room it was missing — knowing that would require having the
            # very geometry that is absent.
            unfaithful = sorted(tainted_by_level.get(level_id, ()))
            evidence: dict[str, Any] = {
                "source": "design_check._openings predicate",
                "rooms_touched": len(near), "tol_mm": tol_mm,
                "position_from": provenance}
            if unfaithful:
                # Addresses AND reasons — both halves: without the reasons
                # the reader does not know exactly WHAT to fix.
                evidence["rooms_with_unfaithful_geometry"] = unfaithful
                evidence["room_geometry"] = {
                    room: room_geometry[room] for room in unfaithful}
            edges.append(GraphEdge(
                relation=Relation.OPENING_POINT_TOUCHES_ROOM,
                src=node_id,
                dst=(touched if touched is not None and _is_node(touched)
                     else node_id),
                modality=(Modality.POSSIBLE if unfaithful
                          else Modality.REFUTED),
                refuted_by=(None if unfaithful
                            else REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO),
                evidence=evidence))
            continue

        # 🔴 A ROOM THE PREDICATE TOUCHED MAY NOT BE A NODE.
        # Polygons come from the L0 HEADER, and nodes come from the STREAM,
        # and on a truncated read these are different sets (measured 22.08:
        # `k2_ar_rd_v1` — 2 442 header rooms, 0 in the stream). `BuildingGraph`
        # rejects outright an edge between two outside endpoints, so the
        # outside room is addressed through the OPENING — the one endpoint
        # guaranteed to be local.
        outside = [room for room in near if not _is_node(room)]
        inside = [room for room in near if _is_node(room)]
        for room in outside:
            key = (node_id, room)
            if key in outside_seen:
                continue
            outside_seen.add(key)
            edges.append(GraphEdge(
                relation=Relation.OPENING_POINT_TOUCHES_ROOM,
                src=node_id, dst=room, modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "design_check._openings predicate",
                          "why": OutsideExtraction.ROOM_NOT_IN_SNAPSHOT.value,
                          "rooms_touched": len(near), "tol_mm": tol_mm,
                          "position_from": provenance}))

        # NO TRUNCATION: an edge for every pair, the touch count travels in
        # the evidence. `design_check` would have taken near[0], near[1] — a
        # pair chosen by alphabet.
        #
        # 🔴 ONE PAIR — ONE EDGE, AND THIS WAS BOUGHT BY THE CORE'S LAW, NOT
        # BY TASTE. `Relation.OPENING_POINT_TOUCHES_ROOM` is declared
        # SYMMETRIC, so `GraphEdge.key` is the triple `(relation, min, max)`,
        # and it carries no opening. Two doors between the same two rooms
        # (the most ordinary thing: a double-leaf door, or a door and an
        # opening side by side) used to produce two edges with ONE key, and
        # `BuildingGraph` refused OUTRIGHT — "duplicate relation/src/dst edge
        # truth is forbidden". Exactly the same refusal that on 22.08 laid
        # down the end-junction edges; there it surfaced on a real building,
        # here it would have surfaced the moment the predicate was first
        # welded into the core. Openings are not lost — they travel as a
        # list in the evidence, and "one door" is distinguishable from
        # "three doors".
        for i in range(len(inside)):
            for j in range(i + 1, len(inside)):
                pair = (inside[i], inside[j])
                row = pairs.get(pair)
                if row is None:
                    pairs[pair] = {
                        "source": "design_check._openings predicate",
                        "opening": node_id, "openings": [node_id],
                        "rooms_touched": len(near), "tol_mm": tol_mm,
                        "position_from": provenance}
                elif node_id not in row["openings"]:
                    row["openings"].append(node_id)

    for (room_a, room_b), evidence in pairs.items():
        evidence["opening_count"] = len(evidence["openings"])
        edges.append(GraphEdge(
            relation=Relation.OPENING_POINT_TOUCHES_ROOM,
            src=room_a, dst=room_b, modality=Modality.PROVEN,
            evidence=evidence))

    census = AdjacencyCensus(openings_seen=seen, openings_evaluated=evaluated,
                             refusals=dict(refusals), touch_degree=dict(degree),
                             rooms_seen=rooms_seen,
                             room_geometry=dict(room_geometry))
    census.assert_balanced()
    return tuple(edges), census
