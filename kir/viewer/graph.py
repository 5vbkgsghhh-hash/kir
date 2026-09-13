"""THE GRAPH LAYER IN THE VIEWER — the line of authority and "this
doesn't exist in Revit yet."

Two axes of a node, orthogonal to everything the viewer showed before:

    authority  = WHO is authoritative for this node (the graph or Revit)
    existence  = WHETHER it exists in the document, or is only declared
                 so far

Both come from `kir/decompile/building_graph.py` — the ENUMS themselves
are taken from there too, not copies of them: a building must have
exactly one dictionary, otherwise `planned` in the viewer and `planned` in
the graph will turn out to be different words a month from now.

════════════════════════════════════════════════════════════════════════════
WHY `existence` IS A SEPARATE AXIS, NOT A VALUE OF `Fidelity`
════════════════════════════════════════════════════════════════════════════
`Fidelity.NO_BODY` means "the element is declared, we don't know its
body." `Existence.PLANNED` means "the element doesn't exist in the model
yet." These are DIFFERENT claims, and all four combinations make sense:
the body can be known exactly while the element doesn't exist in Revit yet
(the engineer wrote the program and hasn't pressed the button) — and
conversely, the element exists in the document while we don't know its
body. Merging them into one scale would turn the "send to Revit" button
into a lottery: a person wouldn't be able to tell what's already standing
from what they just thought up.

════════════════════════════════════════════════════════════════════════════
MEASUREMENT 11.08.2026, WHICH SET THIS MODULE'S SHAPE
════════════════════════════════════════════════════════════════════════════
`graph_from_l0` + `graph_view` on real parses:

| parse               | nodes  | graph  | view   | declared / derived_by_revit |
|----------------------|-------:|-------:|-------:|-----------------------------|
| `sob62_fas_r23_v19` |  5 218 | 0.18 s | 0.03 s | 3 066 / 2 152               |
| `snowdon_plumb_v4`  | 32 185 | 0.63 s | 0.16 s | 32 185 / 0                  |
| `демо-v3`           | 90 758 | 1.85 s | 0.57 s | 55 667 / 35 091             |

There are MORE nodes than shells (90 758 versus 84 120), because the graph
also holds datums — levels, grids, rooms. So the "node ↔ shell"
correspondence is partial by construction, and the viewer must name that,
rather than show the difference as a loss.

**`existence` across the whole corpus is `materialized` and nothing
else.** Not a single `planned`: `graph_from_l0` is the ONLY builder of the
graph, and it reads the document. There is NO PRODUCER of `planned` in the
working code AT ALL (a `grep -rn "Existence.PLANNED"` sweep gives one
line, and that one is in a test). This has a direct consequence for this
module, and it is named below in full: **`planned` for a live session is
set by the VIEWER, not by the graph.**

════════════════════════════════════════════════════════════════════════════
A FLAG BELONGING TO ANOTHER MODULE IS RESPECTED
════════════════════════════════════════════════════════════════════════════
`building_graph_enabled()` was kept OFF on the owner's argument: "the
module hasn't been checked against a live Revit even once yet, and this
package tells 'built in' apart from 'written' by a flag, not by the
author's gut feeling." The owner himself flipped it, on 22.08.2026, when
the condition he had named was met: the graph census converges across the
CORPUS — 76 parses out of 76, 0 refusals.

WHAT CHANGES HERE AS A RESULT: the graph layer is now built BY DEFAULT,
and its cost was measured by the scene's author and recorded next to the
call site (`scene.py`) — a second pass over L0, 0.25 s on the facade and
~3.2 s on демо-v3. Turning it off remains an explicit word
(`KUKAI_IR_BUILDING_GRAPH=0`), and a disabled layer still reports
`available: false` WITH A REASON — a tri-state, as everywhere: "we didn't
ask" is distinguishable from "we asked, there's nothing there."

🔴 THE DECISION DOES NOT BELONG TO THE VIEWER. The viewer ASKS the flag
and never decides on its behalf; if the default moves back, this line
moves with it, rather than outliving it as a second carrier.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

__all__ = ("GRAPH_SCHEMA", "AUTHORITY_CODE", "EXISTENCE_CODE", "FLAG_REFUTED",
           "FLAG_UNRESOLVED", "ElementGraph", "facts_for_decompile",
           "facts_for_programs", "unavailable")

GRAPH_SCHEMA = "kir-viewer-graph/1"

#: The codes are published in the scene header; the client keeps no
#: copy of its own.
AUTHORITY_CODE: dict[str, int] = {"declared": 0, "derived_by_revit": 1,
                                  "unknown": 2}
EXISTENCE_CODE: dict[str, int] = {"materialized": 0, "planned": 1,
                                  "unknown": 2}

#: The `elem_flags` bits. BOTH ARE FACTS ABOUT THE EDGE, ATTRIBUTED TO
#: ITS ENDPOINT, and the on-screen wording must preserve that: "this
#: element has a refuted relation," not "this element is refuted."
#:
#: WHY THIS IS NOT A TRUST STATE. The viewer used to have
#: `Trust.CLASH_REFUTED` set up — my mistake, and it was removed. `Trust`
#: answers "how strong is the claim that the ELEMENT is such"; a
#: refutation, on the other hand, is a property of the RELATION between
#: two elements (`GraphEdge.refuted_by`, mandatory exactly when
#: `Modality.REFUTED`). Coloring an element as "refuted" because of one
#: of its edges is exactly the axis conflation this whole coloring scheme
#: was written to forbid. The measurement that made this visible:
#: `демо-v3` gives 5 941 edges refuted by the rule
#: `host_does_not_separate_exactly_two_rooms`, and all of them are about
#: DOORS, each of which is read perfectly well on its own.
FLAG_REFUTED = 1
FLAG_UNRESOLVED = 2


@dataclass(frozen=True, slots=True)
class ElementGraph:
    """Graph facts about one element. Not a single inference."""

    authority: str
    existence: str
    authority_source: str
    flags: int = 0


def unavailable(reason: str) -> dict[str, Any]:
    """The layer was not built — and WHY IS STATED. An empty layer and a
    missing layer read the same only if you stay silent."""
    return {"schema": GRAPH_SCHEMA, "available": False, "reason": reason,
            "authority": {}, "existence": {}, "relations": {},
            "refuted_by_rule": {}, "unresolved_by_reason": {},
            "without_l1": None, "nodes": 0}


def facts_for_decompile(origin: Mapping[str, Any],
                        elements: Sequence[Mapping[str, Any]],
                        *, generator_child_ids: Iterable[str],
                        l1_source_ids: Iterable[str],
                        ) -> tuple[dict[str, ElementGraph], dict[str, Any]]:
    """Parse -> graph facts per element + a summary for the panel.

    `generator_child_ids` is supplied EXPLICITLY and comes from L1 atoms
    with the `generator_child` reason. A category table is not, and
    cannot be, supplied here: a prior does not know who creates an
    element — that is what the retracted claim about 14 713 fittings was
    built on.
    """
    from kir.decompile.building_graph import (Modality, building_graph_enabled,
                                                   graph_from_l0, graph_view)

    if not building_graph_enabled():
        return {}, unavailable(
            "KUKAI_IR_BUILDING_GRAPH не задан: граф здания не строился. Его "
            "владелец держит модуль за флагом, пока тот не сверен с живым "
            "Revit, и показывать непроверенное как правду вьюер не вправе")

    started = time.perf_counter()
    try:
        graph = graph_from_l0(origin, elements,
                              generator_child_ids=list(generator_child_ids))
        view = graph_view(graph, l1_source_ids=list(l1_source_ids))
    except Exception as exc:  # noqa: BLE001 — a foreign module; the refusal is named
        return {}, unavailable(
            f"граф не построился: {type(exc).__name__}: {str(exc)[:200]}")

    # EDGES -> ENDPOINT FLAGS. A walk over edges, not over nodes: a node
    # does not have this knowledge, it belongs to the relation. Both
    # endpoints are marked, because a refuted relation concerns both, and
    # staying silent about the second is not allowed.
    flags: dict[str, int] = {}
    for edge in graph.edges:
        bit = (FLAG_REFUTED if edge.modality is Modality.REFUTED
               else FLAG_UNRESOLVED if edge.modality is Modality.UNRESOLVED_TARGET
               else 0)
        if not bit:
            continue
        flags[edge.src] = flags.get(edge.src, 0) | bit
        flags[edge.dst] = flags.get(edge.dst, 0) | bit

    facts = {node.node_id: ElementGraph(
        authority=node.authority, existence=node.existence,
        authority_source=node.authority_source,
        flags=flags.get(node.node_id, 0)) for node in view.nodes}

    note = {
        "schema": GRAPH_SCHEMA,
        "available": True,
        "source": "graph_from_l0",
        "doc_name": view.doc_name,
        "nodes": len(view.nodes),
        "authority": dict(view.authority),
        "existence": dict(view.existence),
        "relations": dict(view.relations),
        # A REFUTED EDGE STAYS AND NAMES THE RULE. An empty summary and a
        # missing summary are different, so the key is always present.
        "refuted_by_rule": dict(view.refuted_by_rule),
        "unresolved_by_reason": dict(view.unresolved_by_reason),
        "without_l1": (None if view.without_l1 is None
                       else len(view.without_l1)),
        "without_l1_ru": ("набор листьев L1 не подавали — это НЕ «таких узлов "
                          "нет»" if view.without_l1 is None else
                          "узлов, которых чтение видело, а компилятор нет"),
        "census_rows": view.census_rows,
        "census_refusals": dict(view.census_refusals),
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        # THERE ARE MORE NODES THAN SHELLS, AND THIS IS NOT A LOSS. The
        # graph holds datums (levels, grids, rooms), which are not
        # entitled to a shell under `hulls.KIND_TABLE`. Measurement:
        # демо-v3 — 90 758 nodes versus 84 120 shells. Without this line
        # the difference would read as a dropout.
        "nodes_without_hull_ru": ("граф держит и датумы (уровни, оси, "
                                  "помещения), которым оболочка не положена — "
                                  "поэтому узлов больше, чем тел на экране"),
    }
    return facts, note


def facts_for_programs(ops_by_id: Mapping[str, Mapping[str, Any]],
                       hosted: Mapping[str, Mapping[str, Any]] | None = None,
                       ) -> tuple[dict[str, ElementGraph], dict[str, Any]]:
    """Live-session operations -> `existence=planned` and the line of
    authority.

    ════════════════════════════════════════════════════════════════════
    THIS IS ASSERTED BY THE VIEWER, NOT BY THE GRAPH, AND THE BOUNDARY IS
    NAMED HERE
    ════════════════════════════════════════════════════════════════════
    A graph builder from programs DOES NOT EXIST: `graph_from_l0` is the
    only one, and it reads the document, marking every node
    `MATERIALIZED`. So `planned` here is set by the viewer on one simple
    fact: the program sits in the session journal, and the journal fills
    up BEFORE the write to Revit. The claim is narrow and verifiable, and
    it does not become a second source of truth — the ENUMS are taken
    from `building_graph`, so the word `planned` stays one word between
    the viewer and the graph.

    ════════════════════════════════════════════════════════════════════
    EDGES ARE NOT BUILT HERE — BUT A READY ONE IS ACCEPTED (22.08.2026)
    ════════════════════════════════════════════════════════════════════
    The previous edition of this paragraph ended with "the live graph
    layer is nodes and their two axes, nothing more," and its argument
    was exactly half right. The right half: resolving references again
    HERE is not allowed — `hosted_from_ops` already does that, and a
    second instance would drift from the first silently. The wrong half:
    "don't resolve" does not imply "don't accept what's already
    resolved."

    The cost of silence was measured: the summary was returning
    `relations: {}` and `unresolved_by_reason: {}` UNCONDITIONALLY, that
    is, for a live session an empty summary and an UNASKED summary looked
    the same — exactly the shape that a tri-state was set up throughout
    this whole house to forbid. And the viewer ALREADY KNOWS how to show
    edges: `FLAG_REFUTED`/`FLAG_UNRESOLVED` are parsed on the client and
    arrive from `facts_for_decompile`.

    `hosted` is the READY `BundleGeometry.hosted` index, computed before
    this call by the same frame (`live_scene`: `CB.bundle_elements(...)`
    runs earlier). `None` means "not supplied," and then the summary
    honestly says that edges were not asked about. An empty dict means
    "asked, no hosts declared."

    🔴 WHAT WILL NOT BE HERE, AND THE PRICE IS NAMED AS A NUMBER. A live
    session cannot give edges to a LEVEL or a ROOM, and that is a
    property of its address space, not laziness: a registry measurement
    on 22.08.2026 — out of 78 language operations, **30 carry `level`, 4
    `top_level`, 1 `base_level`, 12 `host`**, and every datum reference
    has `ParamSpec.kind='sel'`, that is, it is a SELECTOR (a name/query),
    not an address. There is no level node in a live scene at all:
    `preview.build_program_preview` hands out plans with
    `level_elevation_mm` and not a single identifier. An edge there would
    require a graph-from-programs producer (`graph_from_programs` does
    not exist) together with minting datum nodes — that is a wave, not a
    patch, and doing it here silently would mean setting up a seventh
    graph.

    `host`, on the other hand, is addressed WITHIN the program (`KIR-V002`
    forbids a reference across a program boundary), so both ends of such
    an edge are ordinary nodes of this same summary, and accepting it
    costs nothing.

    THE LINE OF AUTHORITY ON WHAT IS DECLARED. An op whose contract
    declares side elements to be derived (`acceptance._OP_DERIVED`: a
    curtain wall spawns cells, panels, and mullions; a floor spawns
    sketch lines; a stair spawns runs, landings, and railings) is not
    itself marked `derived_by_revit` — it itself is declared by the
    author. What is marked is the FACT that elements will follow it that
    are not in the program and will not be in the scene: only Revit knows
    their number. That's why the op stays `declared`, while the summary
    carries a separate `will_derive` line — otherwise the viewer would be
    promising to show something it cannot show.
    """
    from kir.decompile.building_graph import (Authority, AuthoritySource,
                                                   Existence)
    try:
        from kir.acceptance import _OP_DERIVED, _OP_DERIVED_CONDITIONAL
    except Exception:  # noqa: BLE001 — a foreign table; its silence is not our green light
        _OP_DERIVED = {}
        _OP_DERIVED_CONDITIONAL = {}

    # EDGES -> ENDPOINT FLAGS, by the same walk as for the parse. A host
    # NAMED by the author and not found is exactly
    # `Modality.UNRESOLVED_TARGET`: the reference is declared, there's
    # nothing to check it against. `hosted_from_ops` writes
    # `host_element_id = None` there and says so verbatim.
    flags: dict[str, int] = {}
    hosted_edges = 0
    hosted_unresolved = 0
    if hosted is not None:
        for element_id, row in hosted.items():
            if not isinstance(row, Mapping):
                continue
            target = row.get("host_element_id")
            if isinstance(target, str) and target:
                hosted_edges += 1
                continue
            hosted_unresolved += 1
            flags[str(element_id)] = (
                flags.get(str(element_id), 0) | FLAG_UNRESOLVED)

    facts: dict[str, ElementGraph] = {}
    will_derive: dict[str, int] = {}
    #: Categories that Revit will add ONLY UNDER THE CONDITION named in
    #: `_OP_DERIVED_CONDITIONAL`. A separate count, not a term to add in:
    #: summing them with the certain ones would mean bringing the same
    #: defect back more quietly (F-312).
    may_derive: dict[str, int] = {}
    may_why: dict[str, str] = {}
    for element_id, op in ops_by_id.items():
        name = str(op.get("op") or "")
        # 🔴 THE CONDITIONAL DOES NOT ADD TO THE CERTAIN (F-312,
        # 30.08.2026). `_OP_DERIVED` is set up as a list of EXCEPTIONS
        # ("never verified") and therefore DELIBERATELY overestimates:
        # for an exception, extra is safe. But here every line was being
        # incremented and captioned "Revit WILL ADD" — the overestimate
        # was presented as fact.
        #
        # Measurement: for 194 142 real corpus walls out of 196 110
        # (99.0 %), the claim about curtain-wall categories is FALSE; for
        # `create_group` the lines are outright mutually exclusive — a
        # group is either a model group OR a detail group.
        bucket = (may_derive if name in _OP_DERIVED_CONDITIONAL
                  else will_derive)
        for category in _OP_DERIVED.get(name, ()):
            bucket[category] = bucket.get(category, 0) + 1
        if name in _OP_DERIVED_CONDITIONAL:
            may_why.setdefault(name, _OP_DERIVED_CONDITIONAL[name])
        facts[element_id] = ElementGraph(
            authority=Authority.DECLARED.value,
            existence=Existence.PLANNED.value,
            authority_source=AuthoritySource.PROGRAM_OP.value,
            flags=flags.get(element_id, 0))

    # AN EMPTY SUMMARY AND AN UNASKED SUMMARY ARE DIFFERENT, AND HERE
    # THIS IS FINALLY VISIBLE. `None` is printed exactly where the index
    # was not supplied.
    relations: dict[str, Any] = ({} if hosted is None
                                 else {"hosted_in": hosted_edges})
    unresolved: dict[str, Any] = (
        {} if hosted is None else
        {"host_named_but_not_found": hosted_unresolved} if hosted_unresolved
        else {})

    note = {
        "schema": GRAPH_SCHEMA,
        "available": True,
        "source": "viewer_asserts_planned",
        "source_ru": ("`planned` проставил ВЬЮЕР: строителя графа из программ "
                      "нет, а журнал сессии наполняется ДО записи в Revit"),
        "nodes": len(facts),
        "authority": {"declared": len(facts)} if facts else {},
        "existence": {"planned": len(facts)} if facts else {},
        "relations": relations,
        "refuted_by_rule": {},
        "unresolved_by_reason": unresolved,
        # 🔴 A TRI-STATE, NOT AN EMPTINESS. `None` — the host index was
        # not supplied, and zero edges above is a fact ABOUT THE CALL.
        # `false` — it was supplied, and zero is a fact ABOUT THE
        # PROGRAM. Without this line the two cases printed the same.
        "edges_unmeasured": hosted is None,
        "edges_unmeasured_ru": (
            "индекс хозяев (`BundleGeometry.hosted`) не подавали — «рёбер 0» "
            "здесь факт о вызове, а не о программе"
            if hosted is None else
            "индекс хозяев подан: ноль рёбер означал бы, что хозяев не "
            "объявлено ни одним опом"),
        # A live session cannot give edges to a LEVEL or a ROOM by the
        # nature of the address space, not out of our laziness; the
        # breakdown with numbers is in the docstring.
        "datum_edges_ru": (
            "рёбер к уровню/комнате у живой сессии нет: ссылка на датум в "
            "языке — СЕЛЕКТОР (`ParamSpec.kind='sel'`), узла уровня в сцене "
            "не существует вовсе"),
        "without_l1": None,
        "without_l1_ru": "у заявленного листьев L1 нет по построению",
        # WHAT REVIT WILL ADD BEYOND WHAT IS DECLARED. The viewer cannot
        # show these elements (only Revit knows their number), but
        # staying silent about them would mean promising that the whole
        # building is on screen.
        "will_derive": dict(sorted(will_derive.items())),
        "will_derive_ru": ("Revit ДОБАВИТ эти категории сверх объявленного — "
                           "их в сцене нет и быть не может: число знает только "
                           "Revit"),
        # 🔴 THE SECOND HALF OF THE SUMMARY, AND IT MAKES NO PROMISE
        # (F-312). These are lines whose condition is named and is NOT
        # CHECKED against the program; summing them with the certain
        # ones is not allowed, and staying silent about them is even
        # less so: they are exactly the part of the building the viewer
        # will not show.
        "may_derive": dict(sorted(may_derive.items())),
        "may_derive_ru": ("Revit МОЖЕТ добавить эти категории — условие "
                          "названо и по программе не проверяется; это ВЕРХНЯЯ "
                          "ГРАНИЦА, а не обещание"),
        "may_derive_why": dict(sorted(may_why.items())),
    }
    return facts, note
