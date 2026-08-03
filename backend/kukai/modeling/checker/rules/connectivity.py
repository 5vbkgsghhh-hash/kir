"""Connectivity / egress rules (design §6: HAB001–004, HAB010).

Pure graph queries over build_graph(model). Each rule:
  check_habNNN(model, graph, thr) -> list[Violation]
returns [] when satisfied. No I/O, no mutation. Numeric dials come from `thr`; all
graph topology and apartment derivation come from graph.py (design §4/§5).
"""
from __future__ import annotations

import networkx as nx

from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.graph import (
    stair_nodes,
    occupied_levels,
    ground_level_ids,
    building_entrance_rooms,
    derive_apartments,
)
from kukai.modeling.checker.spatial_model import (
    SpatialModel,
    Severity,
    Violation,
    RoomFunction,
)
from kukai.modeling.checker.thresholds import Thresholds


def check_hab001(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """Every room must be reachable (in the connectivity graph) from a building entrance.

    A building entrance room touches an exterior door. We collect the set of nodes reachable
    from ANY entrance room and flag every room node not in it. If there is no entrance at all,
    every room is unreachable (the whole building is sealed) — flagged too.
    """
    entrances = building_entrance_rooms(model)
    reachable: set[str] = set()
    for room_id in entrances:
        if room_id in graph:
            reachable |= nx.node_connected_component(graph, room_id)

    unreachable = sorted(
        room.id for room in model.rooms
        if room.id not in reachable
    )
    if not unreachable:
        return []
    return [
        Violation(
            rule_id="HAB001",
            severity=Severity.BLOCKING,
            refs=unreachable,
            msg=(
                "Rooms are not reachable from any building entrance: "
                + ", ".join(unreachable)
            ),
            fix_hint="Add a door connecting each isolated room to the apartment/corridor it belongs to.",
        )
    ]


def _interior_apartment_of(model: SpatialModel) -> dict[str, str | None]:
    """Map each room id to its stamped apartment_id (None if unstamped / public)."""
    return {room.id: room.apartment_id for room in model.rooms}


def check_hab002(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """No apartment-into-apartment, and each apartment has EXACTLY ONE public entrance.

    Branch (a): any interior door connecting two rooms with DIFFERENT non-null apartment_id means
        one apartment is nested inside (or pierced into) another — BLOCKING.
    Branch (b): a derived apartment whose entrance-door count into public circulation is
        not exactly one (zero => sealed/nested; >1 => through-apartment) — BLOCKING.
    Branch (c): a single private component holding >1 прихожая means multiple apartments are fused
        into one — apartment-into-apartment caught STRUCTURALLY, without relying on apartment_id
        stamps (§4 makes the stamp optional, so branch (a) alone is blind on unstamped input).
    (design §6 HAB002)
    """
    violations: list[Violation] = []
    apt_of = _interior_apartment_of(model)

    # Branch (a): interior doors between two different non-null apartment ids.
    for door in model.doors:
        if door.is_exterior:
            continue
        a = apt_of.get(door.from_room_id)
        b = apt_of.get(door.to_room_id)
        if a is not None and b is not None and a != b:
            violations.append(
                Violation(
                    rule_id="HAB002",
                    severity=Severity.BLOCKING,
                    refs=sorted({a, b, door.from_room_id, door.to_room_id}),
                    msg=(
                        f"Interior door {door.id!r} connects apartment {a!r} directly to "
                        f"apartment {b!r} (apartment-into-apartment)."
                    ),
                    fix_hint="Apartments may only connect to each other through public circulation, "
                             "never via a shared interior door.",
                )
            )

    # Branch (c): >1 прихожая in one private component = fused apartments (stamp-independent).
    for apt in derive_apartments(model, graph):
        if len(apt.prihozhaya_ids) > 1:
            violations.append(
                Violation(
                    rule_id="HAB002",
                    severity=Severity.BLOCKING,
                    refs=sorted({apt.apartment_id, *apt.prihozhaya_ids}),
                    msg=(
                        f"Private cluster {apt.apartment_id!r} contains {len(apt.prihozhaya_ids)} "
                        f"прихожая rooms {sorted(apt.prihozhaya_ids)} — multiple apartments are "
                        "fused into one (apartment-into-apartment)."
                    ),
                    fix_hint="Each apartment is its own private cluster with a single прихожая "
                             "reached from public circulation; never chain one apartment through another.",
                )
            )

    # Branch (b): each apartment must have exactly one entrance into public circulation.
    for apt in derive_apartments(model, graph):
        n = len(apt.entrance_door_ids)
        if n == 1:
            continue
        if n == 0:
            msg = (
                f"Apartment {apt.apartment_id!r} has no entrance into public circulation "
                "(sealed or nested inside another apartment)."
            )
            hint = "Connect this apartment's прихожая to a corridor / stair lobby with one entrance door."
        else:
            msg = (
                f"Apartment {apt.apartment_id!r} has {n} entrances into public circulation "
                "(expected exactly one)."
            )
            hint = "Keep a single entrance door from public circulation into the apartment's прихожая."
        violations.append(
            Violation(
                rule_id="HAB002",
                severity=Severity.BLOCKING,
                refs=sorted({apt.apartment_id, *apt.room_ids}),
                msg=msg,
                fix_hint=hint,
            )
        )
    return violations


def _ground_landing_nodes(model: SpatialModel) -> set[str]:
    """Room ids of ЛЕСТНИЦА (stair landing) rooms that sit on a ground/exit level."""
    ground = ground_level_ids(model)
    return {
        room.id for room in model.rooms
        if room.function is RoomFunction.ЛЕСТНИЦА and room.level_id in ground
    }


def check_hab003(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """From each apartment there must be a path to a stair AND down to a ground/exit level
    (design §6 HAB003).

    Egress is satisfied for an apartment when, starting from any of its rooms (which are
    connected outward through its entrance door), the graph reaches a stair node and also
    reaches a stair-landing room that is on a ground/exit level (a level with an exterior door).
    """
    ground_landings = _ground_landing_nodes(model)
    violations: list[Violation] = []

    # v2: a room holding a ground-level exterior door IS an egress point — a valid
    # 1-story building with a street door and no stair must not BLOCK (probe M).
    ground_egress_rooms: set[str] = set()
    if checker_v2_enabled():
        ground = ground_level_ids(model)
        level_of = {r.id: r.level_id for r in model.rooms}
        ground_egress_rooms = {
            rid for rid in building_entrance_rooms(model)
            if level_of.get(rid) in ground
        }

    for apt in derive_apartments(model, graph):
        reachable: set[str] = set()
        for room_id in apt.room_ids:
            if room_id in graph:
                reachable |= nx.node_connected_component(graph, room_id)
                break
        # Egress: reach a stair-landing (лестница) room on a ground/exit level. On an upper
        # floor that landing is reachable only by descending the stair (its vertical graph
        # edges), so this single condition covers both ground-floor and upper-floor apartments.
        if reachable & ground_landings:
            continue
        if ground_egress_rooms and (reachable & ground_egress_rooms):
            continue  # v2: direct exterior egress at grade
        why = "no path to a stair landing on a ground/exit level (a level with an exterior door)"
        violations.append(
            Violation(
                rule_id="HAB003",
                severity=Severity.BLOCKING,
                refs=sorted(apt.entrance_door_ids) or sorted(apt.room_ids),
                msg=f"Apartment {apt.apartment_id!r} has no egress: {why}.",
                fix_hint="Ensure the corridor leads to a stair that descends to a level with an exterior exit door.",
            )
        )
    return violations


def check_hab004(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """Inside an apartment, every room must be reachable from the прихожая, walking only
    through the apartment's own rooms (design §6 HAB004).

    If an apartment has no прихожая, that itself is flagged (no defined entrance hall to
    reach rooms from). Otherwise we induce the subgraph on the apartment's rooms and check
    that every member is reachable from some прихожая node.
    """
    violations: list[Violation] = []
    for apt in derive_apartments(model, graph):
        if not apt.prihozhaya_ids:
            violations.append(
                Violation(
                    rule_id="HAB004",
                    severity=Severity.BLOCKING,
                    refs=sorted(apt.room_ids),
                    msg=f"Apartment {apt.apartment_id!r} has no прихожая to reach its rooms from.",
                    fix_hint="Add a прихожая (entrance hall) that connects to every room in the apartment.",
                )
            )
            continue
        sub = graph.subgraph(apt.room_ids)
        reachable: set[str] = set()
        for hall_id in apt.prihozhaya_ids:
            if hall_id in sub:
                reachable |= nx.node_connected_component(sub, hall_id)
        unreachable = sorted(apt.room_ids - reachable)
        if unreachable:
            violations.append(
                Violation(
                    rule_id="HAB004",
                    severity=Severity.BLOCKING,
                    refs=unreachable,
                    msg=(
                        f"Apartment {apt.apartment_id!r}: rooms not reachable from the прихожая: "
                        + ", ".join(unreachable)
                    ),
                    fix_hint="Add interior doors so every room connects back to the прихожая.",
                )
            )
    return violations


def check_hab010(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """Stairs must connect ALL occupied levels (>=1 room) to a ground level — no floating
    floor (design §6 HAB010).

    A level is occupied if it has >=1 room. A ground/exit level has an exterior door. Each
    occupied non-ground level must reach a ground-level stair landing via the connectivity
    graph (which carries vertical stair edges). A level with rooms but no stair landing, or a
    landing that cannot reach ground, floats.
    """
    ground = ground_level_ids(model)
    ground_landings = _ground_landing_nodes(model)

    # Map each level to its ЛЕСТНИЦА (landing) room ids.
    landings_by_level: dict[str, list[str]] = {}
    for room in model.rooms:
        if room.function is RoomFunction.ЛЕСТНИЦА:
            landings_by_level.setdefault(room.level_id, []).append(room.id)

    violations: list[Violation] = []
    for level in occupied_levels(model):
        if level.id in ground:
            continue  # a ground/exit level is reachable by definition
        landings = landings_by_level.get(level.id, [])
        if not landings:
            violations.append(
                Violation(
                    rule_id="HAB010",
                    severity=Severity.BLOCKING,
                    refs=[level.id],
                    msg=(
                        f"Occupied level {level.name!r} ({level.id}) has no stair landing — "
                        "it is a floating floor with no vertical connection to ground."
                    ),
                    fix_hint="Add a stair (and a лестничная клетка room) connecting this level down to ground.",
                )
            )
            continue
        reaches_ground = False
        for landing_id in landings:
            if landing_id in graph and (
                nx.node_connected_component(graph, landing_id) & ground_landings
            ):
                reaches_ground = True
                break
        if not reaches_ground:
            violations.append(
                Violation(
                    rule_id="HAB010",
                    severity=Severity.BLOCKING,
                    refs=sorted([level.id, *landings]),
                    msg=(
                        f"Occupied level {level.name!r} ({level.id}) does not connect down to a "
                        "ground/exit level via any stair."
                    ),
                    fix_hint="Add stair runs so this level's лестничная клетка descends to a level with an exterior exit.",
                )
            )
    return violations
