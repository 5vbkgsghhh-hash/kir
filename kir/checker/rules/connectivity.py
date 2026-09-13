"""Connectivity / egress rules (design §6: HAB001–004, HAB010).

Pure graph queries over build_graph(model). Each rule:
  check_habNNN(model, graph, thr) -> list[Violation]
returns [] when satisfied. No I/O, no mutation. Numeric dials come from `thr`; all
graph topology and apartment derivation come from graph.py (design §4/§5).
"""
from __future__ import annotations

import networkx as nx

from kir.checker.flags import checker_v2_enabled
from kir.checker.function_provenance import (
    describe as describe_function,
    is_authored as function_is_authored,
)
from kir.checker.graph import (
    stair_nodes,
    occupied_levels,
    ground_level_ids,
    building_entrance_rooms,
    derive_apartments,
    read_only_view,
)
from kir.checker.spatial_model import (
    SpatialModel,
    Severity,
    Violation,
    RoomFunction,
)
from kir.checker.thresholds import Thresholds


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


def _guessed_landings(model: SpatialModel) -> dict[str, str]:
    """`{room_id: function_source}` for landings whose function was NOT named
    by the author.

    🔴 WHY THIS EXISTS, BY MEASUREMENT 07.09.2026. The law of function
    provenance (`kir/checker/function_provenance.py`, 22.08) was asked by
    exactly three rules — HAB020, HAB021, HAB030. HAB003 and HAB010 picked a
    landing with the line `room.function is RoomFunction.ЛЕСТНИЦА` and did
    NOT ASK about its source, and they have none of the
    `apartments_from_authored_functions` preconditions the engine used to
    shield HAB002/HAB004/HAB042.

    THE COST IS ONE-DIRECTIONAL, AND IT IS THE WORST DIRECTION. A derived
    function only ADDS a landing, so it can only SUPPRESS a verdict: a floor
    whose only "stair" was identified by furnishing (`fixtures`) or by a
    foreign classifier (`host_classifier`) reads as connected to the ground,
    and the rule stays silent. This silence is indistinguishable from silence
    over a real stair.

    WHAT CHANGES AND WHAT DOES NOT. No BLOCKING is suppressed and no
    threshold is softened — the same law as HAB020/021/030. Exactly one thing
    changes: silence that stands on a guess stops being silence and NAMES its
    source.
    """
    return {room.id: (room.function_source or "")
            for room in model.rooms
            if room.function is RoomFunction.ЛЕСТНИЦА
            and not function_is_authored(room.function_source)}


def _guessed_note(model: SpatialModel, room_ids) -> str:
    """A human-readable reason: exactly which landing was named by a guess, and whose."""
    guessed = _guessed_landings(model)
    named = sorted(rid for rid in room_ids if rid in guessed)
    if not named:
        return ""
    return (", ".join(f"{rid} (function_source={guessed[rid]!r})" for rid in named)
            + " — " + describe_function(guessed[named[0]]))


#: The reason code by which "nothing to judge by" is told apart from "judged
#: and clean." The same technique as `hull_refused:<reason>` in clash: name
#: first, text second.
FUNCTION_GUESSED = "function_guessed"


def _landings_by_level(model: SpatialModel) -> dict[str, list[str]]:
    """`{level_id: [landing ids]}` — one parse for every reader of the file."""
    out: dict[str, list[str]] = {}
    for room in model.rooms:
        if room.function is RoomFunction.ЛЕСТНИЦА:
            out.setdefault(room.level_id, []).append(room.id)
    return out


def ground_reach(model: SpatialModel, graph: nx.Graph) -> dict[str, tuple]:
    """`{level_id: (a path to ground exists, the path stands on the READ
    graph, landings)}`.

    🔴 WHAT IS ASKED IS THE PATH, NOT THE POINT (07.09.2026). The first edit
    of this wave asked for provenance at the landing REACHED: "we reached one
    at grade — did the author name it." The discriminator was reproduced by
    execution — a three-story building where the MIDDLE floor's landing is
    guessed:

        named       1 level (L1)
        should have  2 (L1 and L2): L2's only way down runs THROUGH L1

    The cost over 14 runs (N=3..6, a guess on each intermediate floor): 20
    levels went UNNAMED, apartments 34 of 34. The engine's classification-
    coverage note does not catch this: it is threshold-based (0.75), and one
    guessed landing does not move it — the building printed PASS.

    THE SECOND ANSWER COMES FROM A VIEW, NOT FROM A SECOND LAW.
    `graph.read_only_view` strips exactly the vertical transitions tagged
    `provenance == guessed`; a horizontal door connection does not depend on
    room function and stays. The real graph is whole, topology untouched.

    ONE ITERATION FOR TWO READERS: the unverifiedness counter
    (`unverifiable_levels`) and the rule's body (`check_hab010`) must see the
    same thing, or the coverage line and the finding will drift apart — our
    own named defect.
    """
    ground = ground_level_ids(model)
    ground_landings = _ground_landing_nodes(model)
    guessed = _guessed_landings(model)
    read_ground = ground_landings - set(guessed)
    view = read_only_view(graph)
    landings_by_level = _landings_by_level(model)

    out: dict[str, tuple] = {}
    for level in occupied_levels(model):
        if level.id in ground:
            continue
        landings = landings_by_level.get(level.id, [])
        if not landings:
            continue          # there is no landing at all — the rule judges and accuses
        reaches, reaches_read = False, False
        for landing_id in landings:
            if landing_id not in graph:
                continue
            if nx.node_connected_component(graph, landing_id) & ground_landings:
                reaches = True
            if (landing_id not in guessed and landing_id in view
                    and nx.node_connected_component(view, landing_id) & read_ground):
                reaches_read = True
            if reaches and reaches_read:
                break
        out[level.id] = (reaches, reaches_read, tuple(landings))
    return out


def guessed_on_the_way(model: SpatialModel, graph: nx.Graph,
                       from_ids) -> list[str]:
    """Guessed landings REACHABLE from here — the ones a descent stands on.

    Naming only the landing reached at grade would be a lie in exactly the
    case this file was set up for: the guess sits on an INTERMEDIATE floor.
    """
    guessed = _guessed_landings(model)
    seen: set[str] = set()
    for rid in from_ids:
        if rid in graph:
            seen |= nx.node_connected_component(graph, rid)
    return sorted(seen & set(guessed))


def unverifiable_levels(model: SpatialModel, graph: nx.Graph) -> tuple[int, str]:
    """How many occupied levels HAB010 has NOTHING TO JUDGE BY, and why.

    🔴 WHY A WARNING IS NOT ENOUGH (self-review 07.09.2026). The first edit of
    this wave printed a WARNING naming the source and stopped there — while
    the coverage line stayed `EVALUATED(n=2), excluded=0`, BYTE-FOR-BYTE THE
    SAME as for a building with a stair that was actually read. That is, the
    rule kept ASSERTING that it judged both levels, and "connected to the
    ground" stayed a yes with a footnote. The mandate demands something else:
    the verdict must become NOT_EVALUATED.

    A carrier for unverifiedness already exists in this model, and it is not
    "a field on the finding": it is `RuleOutcome` — `n_subjects` minus
    `excluded_subjects`, with `subjects == 0 -> NOT_EVALUATED` and a named
    reason. HAB022 uses the same carrier: a room with no height does not
    enter its population (`engine.py`, the `height_mm is not None` counter),
    and a model with no heights at all reads as NOT_EVALUATED, not as
    "clean." Here it is exactly the same for function.

    What counts as "confirmed" is decided by `ground_reach`: the whole path,
    not the point reached.
    """
    blind = sorted(lid for lid, (reaches, reaches_read, _) in
                   ground_reach(model, graph).items()
                   if reaches and not reaches_read)
    if not blind:
        return 0, ""
    return len(blind), (
        f"{FUNCTION_GUESSED}: связь с землёй у {', '.join(blind)} "
        f"подтверждается ТОЛЬКО путём через площадку, чью функцию назвал не автор "
        f"(`Room.function_source` вне `function_provenance.AUTHORED`)")


def apartment_ground_reach(model: SpatialModel, graph: nx.Graph,
                           apt) -> tuple[set, bool]:
    """`(reachable from the apartment, whether the exit stands on the READ
    graph)`.

    The same law as `ground_reach`, and for the same reason:
    `unverifiable_apartments` looked ONLY at the landing reached at grade, and
    across 14 runs of the discriminator named NOT A SINGLE ONE of the 34
    apartments that have nowhere to descend except through a guessed landing
    on an intermediate floor.
    """
    ground_landings = _ground_landing_nodes(model)
    read_ground = ground_landings - set(_guessed_landings(model))
    view = read_only_view(graph)
    reachable: set[str] = set()
    reachable_read: set[str] = set()
    for room_id in apt.room_ids:
        if room_id in graph:
            reachable = set(nx.node_connected_component(graph, room_id))
            if room_id in view:
                reachable_read = set(nx.node_connected_component(view, room_id))
            break
    return reachable, bool(reachable_read & read_ground)


def unverifiable_apartments(model: SpatialModel, graph: nx.Graph,
                            apartments) -> tuple[int, str]:
    """How many apartments HAB003 has nothing to judge by: the exit stands only on a guess."""
    ground_landings = _ground_landing_nodes(model)
    blind: list[str] = []
    for apt in apartments:
        reachable, read_ok = apartment_ground_reach(model, graph, apt)
        if not (reachable & ground_landings):
            continue          # there is no exit at all — the rule judges and ACCUSES
        if not read_ok:
            blind.append(str(apt.apartment_id))
    if not blind:
        return 0, ""
    return len(blind), (
        f"{FUNCTION_GUESSED}: выход у {', '.join(sorted(blind))} подтверждается "
        f"ТОЛЬКО путём через лестничную площадку, чью функцию назвал не автор")


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
        # THE SAME ITERATION AS WHAT COVERAGE READS (`unverifiable_apartments`):
        # the rule's body and the coverage line must see the same thing.
        reachable, read_ok = apartment_ground_reach(model, graph, apt)
        # Egress: reach a stair-landing (лестница) room on a ground/exit level. On an upper
        # floor that landing is reachable only by descending the stair (its vertical graph
        # edges), so this single condition covers both ground-floor and upper-floor apartments.
        if reachable & ground_landings:
            # 🔴 SILENCE OVER A GUESS STOPS BEING SILENCE. The exit is
            # counted, but it is counted through a PATH via a landing whose
            # "stairness" was not named by the author — and this landing can
            # sit on an INTERMEDIATE floor, not on the one reached at grade
            # (discriminator 07.09: 34 apartments of 34).
            if not read_ok:
                виновные = guessed_on_the_way(model, graph, apt.room_ids)
                note = _guessed_note(model, виновные)
                violations.append(
                    Violation(
                        rule_id="HAB003",
                        severity=Severity.WARNING,
                        refs=виновные or sorted(reachable & ground_landings),
                        msg=(
                            f"Apartment {apt.apartment_id!r}: egress is confirmed ONLY "
                            f"through a PATH that leans on a stair landing whose function "
                            f"was NOT read from the author: {note}. The verdict is NOT "
                            f"blocking, and it is NOT a clean pass either."
                        ),
                        fix_hint=(
                            "Назовите помещение лестничной клеткой в модели (ROOM_NAME) "
                            "— тогда вывод об эвакуации встанет на прочитанном."
                        ),
                    )
                )
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
    landings_by_level = _landings_by_level(model)
    # THE SAME ITERATION AS WHAT COVERAGE READS (`unverifiable_levels`).
    reach = ground_reach(model, graph)

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
        reaches_ground, reaches_ground_read, _ = reach[level.id]
        # The same law as HAB003 above: a connection confirmed ONLY by a
        # derived function is named, not swallowed by silence. And it is
        # asked of the PATH: a guess sits on an intermediate floor more often
        # than on the landing reached at grade (discriminator 07.09).
        if reaches_ground and not reaches_ground_read:
            виновные = guessed_on_the_way(model, graph, landings)
            violations.append(
                Violation(
                    rule_id="HAB010",
                    severity=Severity.WARNING,
                    refs=виновные or sorted(landings),
                    msg=(
                        f"Occupied level {level.name!r} ({level.id}) reaches ground ONLY "
                        f"through a PATH that leans on a stair landing whose function was "
                        f"NOT read from the author: {_guessed_note(model, виновные)}. The "
                        f"floor is NOT declared connected on authored evidence."
                    ),
                    fix_hint=(
                        "Назовите лестничную клетку в модели (ROOM_NAME) либо задайте "
                        "функцию помещения явно — тогда связь этажа с землёй будет "
                        "стоять на прочитанном, а не на выведенном."
                    ),
                )
            )
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
