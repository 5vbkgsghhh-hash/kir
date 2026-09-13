"""TYPED BUILDING GRAPH v1 — STATE, over which the KIR program is a
TRANSACTION, and Revit is one of the materialization backends.

This module does not start a seventh graph. It lays down the SPINE, onto which the six
existing graphs attach as INDEXES, and does so precisely because measurement showed:
all six have the same node address.

═══════════════════════════════════════════════════════════════════════════
THE MEASUREMENT THE WHOLE MODULE RESTS ON (10.08.2026, instrument — a raw parse
of `L0.jsonl` and `tree.json` from the corpus `backend/backend/data/decompile`,
machine-local, 76 directories / 67 with `L0.jsonl` / 52 with `tree.json`)
═══════════════════════════════════════════════════════════════════════════

**1. The node address is resolved, and resolved COMPLETELY.** The L1 leaf's `source_element_id` is a
BIJECTION onto the `element_id` from L0, on **52 trees out of 52**: 540 461 leaves against
1 139 477 elements, **0** `element_id` repeats across the whole corpus, 0 leaves with
an address outside L0, 0 elements without a leaf in those snapshots where a tree exists. This is not
"probably so" — this is an exhaustive scan of the whole corpus. The graph's spine is therefore THE
SET OF L0 ELEMENTS ITSELF, not a new identifier.

**2. The address space is ONE, including rooms, levels, and grids.** Measured on
four buildings: rooms — 7 841/7 841 lie within the element set (category
`OST_Rooms`), levels — 170/170, grids — 122/122, and every `level_id` an
element references is itself an element. This means a room and a level are ORDINARY
nodes of this graph, distinguished by category rather than a parallel entity with its own
namespace. `modeling/checker/spatial_model.py` builds a typed
world with its own `Room.id`/`Level.id` — and these ids ARE ALREADY element ids;
the parallel world is address-compatible with the graph and simply does not know it.

**3. `host_id` carries an answer, but NOT EVERYWHERE, and the difference is named.** Across the corpus:
213 811 elements (18.76 %) carry `host_id`, of which **1 263 are DANGLING** (0.59 %)
— the host is not an element of THIS snapshot. The average lies: danglingness is
CONCENTRATED. `snowdon_elec_v1` (*Snowdon Towers Sample Electrical*) — **959
of 1 001, 95.8 %**; four *Snowdon Plumbing* snapshots — **54/54, 54/54, 54/54,
50/50, i.e. 100 %**. There the host lies in a LINKED file that is not present in
the single-partition parse. So the `hosted_in` edge has THREE outcomes, not two:
host found / the element did not declare a host / **host is declared and lies OUTSIDE
the extraction**. The third is exactly the law "a missing index and an empty index are
different facts", applied to an edge. An edge that is absent because we did not
read the link must not be indistinguishable from an edge that is absent in the building.

**4. `host_source` — 0 rows out of 1 139 477, AND THIS IS A NUMBER ABOUT THE CORPUS, NOT ABOUT THE
READER.** The temptation to read zero as "the branch is broken" is strong and WRONG; verified
by dates, not by reasoning:

    `host_source` capture landed in `extract.py`   **2026-08-09 22:24:57** (`6a90a7e1`)
    the FRESHEST corpus snapshot                    **2026-08-04 16:59** (`k2_ar_rd_v15`)

All 67 snapshots were taken BEFORE the wave — by five days or more. So the instrument did not
fail, it NEVER RAN EVEN ONCE, and by this package's law, those are different facts.

Moreover, the branch CANNOT produce `host_id` without `host_source`: in `_host_readers_cs`
both fields are assigned in ONE `if` block, so a non-empty host without a
named source is structurally unconstructable. The old corpus confirms this
indirectly and precisely: before the wave, the host was populated by a single cast to
`FamilyInstance`, and in the corpus exactly the family instances have a host (doors
153/153, windows 31/31, mullions 1 452/1 452), whereas system elements —
railings, openings, foundations — have it almost nowhere (2 453 railings,
host on 24, i.e. 1.0 %).

The cost of one run is named in advance: **2 485 corpus elements** fall under
the new table branches (`OST_StairsRailing` 2 453, `OST_FloorOpening` 27,
`OST_StructuralFoundation` 5), and today only 24 of them carry a host. The field is therefore
NOT removed and NOT considered dead — it awaits a single parse against a live
Revit. Here it is read, and its absence is called "not measured" and is never
interpreted as `family_instance`.

═══════════════════════════════════════════════════════════════════════════
TWO AXES OF THE NODE, BOTH IN v1 — OTHERWISE A SEVENTH GRAPH WILL APPEAR
═══════════════════════════════════════════════════════════════════════════

**`authority` — the load-bearing line. The graph is authoritative for the DECLARED, Revit — for
the DERIVED.** Today this distinction lives in the author's head; here it is a property of the
node.

THE DIRECTION OF REFUSAL IS CHOSEN BY THE COST OF ERROR, NOT BY TASTE, and the cost is measured.
To call the declared derived means pulling the element out of reassembly: it leaves
both the NUMERATOR and the DENOMINATOR at once, so the metric barely moves
while half the model disappears. The 10.08 measurement on `snowdon_plumb_v4`: converting
MEP fittings to generated ones would remove **14 713 of 31 998 ops (46.0 %)**, and
`honest_pct` would shift **99.42 % → 98.93 %** — 0.49 pp for half a building.
Calling the derived declared is cheaper and LOUDER: you get an extra op that is
visible. Therefore:

* the default is `DECLARED`, and it is fail-closed;
* `DERIVED_BY_REVIT` is set ONLY on a NAMED witness, and the witness
  travels in the node (`authority_source`);
* **a category table is NOT a witness.** This is a direct prohibition, not
  a stylistic choice: a category prior does not know who creates the element, and it was
  exactly this that the withdrawn 10.08 claim about fittings was built on. `family_placement.index.json`
  gives all 14 713 fittings the same thing as 870 genuine authored instruments
  (`OneLevelBased`, `host_id: null`, `super_component_id: null`) — there is nothing in the
  data to tell them apart, and so nothing to declare either.

**`existence` — because the product is a VIEWER.** An engineer builds a building in chat
for three hours and only at the end presses «отправить в Revit». An unbuilt building must
be expressible in the graph from day one, otherwise the viewer will get its own representation —
and that will be a seventh graph. `MATERIALIZED` — the node was read from the document,
`PLANNED` — the node was declared by a program that has not yet executed.

The axes are ORTHOGONAL, and all four combinations are meaningful. `planned` +
`derived_by_revit` is the most interesting: the program said «соедини трубы», and
fittings WILL APPEAR, but they do not exist yet and their geometry cannot be declared. The viewer must
draw such a node differently from a declared pipe, not with the same identical body.

═══════════════════════════════════════════════════════════════════════════
THE CENSUS LAW
═══════════════════════════════════════════════════════════════════════════

`nodes = assessed + named refusals`. The same law as the CLASH census
(`eligible = hulled + unsupported + missing_geometry`), but across all nodes.
A graph whose census does not balance lies silently in exactly the same way a
detector would lie. `GraphCensus.assert_balanced()` is not a report but a condition of construction.

🔴 THE MODULE IS NO LONGER INERT — ON 22.08.2026 IT WENT INTO THE PIPELINE.

It is worth keeping the history of this paragraph in full, because it named the wrong
cause twice. The first edition claimed the module "is not imported by any working
path"; the 11.08.2026 measurement (an AST-based import walk from `kukai.main`)
REFUTED it — the module is reachable, it is imported by `viewer/scene.py` and
`viewer/graph.py`. The second edition was correct: control reaches it and
stops at the `building_graph_enabled()` gate, and the gate is off because
"it has never once been checked against a live Revit."

Today BOTH are closed: the graph now has a caller in `pipeline.run_decompile`
(the `building_graph` stage places `building_graph.json` next to the parse), and
the gate's default has been switched to ON under the condition named by the owner —
the census balances across the CORPUS, not on a single building. The 22.08 run over
`backend/data/decompile`: 88 directories, 12 without `L0.jsonl`, the graph assembled
**76 of 76**, refusals **0**, `assert_balanced()` holds at **76 of 76**
(1 576 343 nodes, 1 843 930 edges). Before that same day's fixes there were FIVE refusals,
and none of them — from the census (see `OutsideExtraction.ROOM_NOT_IN_SNAPSHOT`).

WHAT THIS DOES NOT MEAN: the module still writes nothing back to Revit and
is still NOT AUTHORITATIVE on identity — `identity_authoritative` = 0 across the whole
corpus, and the reason is typed in `identity.py`.

═══════════════════════════════════════════════════════════════════════════
🔴 WHY IDENTITY = 0, AND WHY THIS IS THE CORRECT REFUSAL, NOT A HOLE
═══════════════════════════════════════════════════════════════════════════
The temptation to read "0 of 1 576 343" as "the L0 header carries no typed
identity" is strong and WRONG. The header carries it, and so do the elements: the
22.08.2026 measurement on MNVNK — `header.identity` of schema `kir-l0-revit-identity/1` with
`document_identity` AND `federation_root_identity`, every element row has its
own `unique_id`. What is missing is EXACTLY ONE thing: the identity source is named
`project_information_unique_id`, and it is NOT among
`identity.AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES` (there only
`cloud_project_model_guid` and `revit_server_central_guid` are listed).

THIS REFUSAL IS CONFIRMED BY THE SAME MODEL, NOT ONLY BY AUTODESK'S DOCUMENTATION.
MNVNK has five `link` records — neighboring blocks of the complex. Four of them
(K1 129 365 elements, K4 75 940, K2 55 381, K5 60 616) carry
`linked_document_identity.value` = `cb8ac19a-…-0000059a`, and THIS IS THE VERY SAME
VALUE as the host document K6's. One key for FIVE DIFFERENT documents:
the blocks were made with «Сохранить как» from one template and retained the `UniqueId` of their
own `ProjectInformation`. Promote this source to authoritative — and the five buildings
of the complex WOULD COLLAPSE INTO ONE IDENTITY, meaning federation would become not
impossible, but SILENTLY WRONG. The comment in `identity._document_fact` named
this risk in words; here it is named by a number.

CAN THIS BE FIXED WITHOUT A LIVE REVIT — NO, and here is the boundary. The values
`GetCloudModelPath().GetModelGUID()` / `GetWorksharingCentralGUID` are simply absent
from L0: `extract.py:1144` asks for them, but the model was handed to us
DETACHED (this is stated right in the file name — «отсоединено отсоединено»), and
a detached copy has no central path by construction.

FIXED BY ONE QUERY, AND THE QUERY IS NOT ADDRESSED TO THIS FILE: open the SOURCE
central (or cloud) models K1/K2/K4/K5/K6 and take from each
`Document.GetCloudModelPath().GetModelGUID()` — one call per document,
five calls for the whole complex. Everything else is already ready: `graph_from_l0`
accepts `document_identity`/`federation_context` as explicit trusted
inputs, and with them the node becomes authoritative without a single code change.
Substituting a directory name or `doc_name` instead is forbidden by the same
module — and the prohibition is correct: it is exactly a home-made key that would glue the five blocks together.

`kir/checker/` is accessed read-only and is not imported here
at all.
"""
from __future__ import annotations

import math
import os
from kir import env  # noqa: E402  (a dependency-free submodule — creates no cycle)
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Iterator, Mapping, Sequence

from kir.decompile.identity import (
    DefinitionIdentity,
    DocumentIdentity,
    FederationContext,
    IdentityError,
    IdentityGap,
    IdentityStatus,
    OccurrenceIdentity,
    identity_context_from_l0,
    resolve_element_identity,
)

__all__ = [
    "Authority",
    "AuthoritySource",
    "BuildingGraph",
    "Existence",
    "DefinitionIdentity",
    "DocumentIdentity",
    "FederationContext",
    "graph_view",
    "NodeView",
    "GraphView",
    "GraphBuildError",
    "GraphCensus",
    "GraphEdge",
    "GraphNode",
    "IdentityGap",
    "IdentityStatus",
    "Modality",
    "NodeRefusal",
    "OutsideExtraction",
    "OccurrenceIdentity",
    "Relation",
    "REFUTED_HOST_NOT_BETWEEN_TWO_ROOMS",
    "REFUTED_TOP_CONSTRAINT_IS_NOT_A_LEVEL",
    "REFUTED_TOP_IS_UNCONNECTED_HEIGHT",
    "building_graph_enabled",
    "OPTIONAL_SOURCES",
    "graph_from_l0",
    "graph_from_dict",
    "GRAPH_ARTIFACT_SCHEMA",
    "GRAPH_ARTIFACT_SCHEMA_V1",
    "READABLE_GRAPH_SCHEMAS",
    "ObservationFingerprint",
    "FINGERPRINT_DERIVED",
    "FINGERPRINT_ABSENT",
    "outer_size_mm",
]


class GraphBuildError(ValueError):
    """A typed refusal of graph construction. There is no silence here."""


#: THE "ARGUMENT NOT SUPPLIED" SENTINEL (F-056).
#:
#: 🔴 AN EMPTY COLLECTION IS A SUPPLIED SOURCE, not an absent one, and the difference
#: is the MIDDLE OUTCOME of the three-outcome law `relation_count`:
#:
#:     edges exist                — a number;
#:     source supplied, no edges  — ZERO, a fact about the BUILDING;
#:     source not supplied        — REFUSAL, a fact about OUR reading.
#:
#: A truthiness check collapsed the middle outcome into the third: an empty set
#: is falsy, and an explicitly supplied empty `link_ids` landed in `sources_absent` on par
#: with one not supplied at all. The instrument thereby canceled a third of its own law — exactly
#: where the law is needed. The question "was it supplied" is about the CALL, not about the
#: content, and it cannot be answered with the content.
_NOT_GIVEN: Any = object()


def _freeze_json(value: Any, *, path: str) -> Any:
    """Snapshot JSON-like evidence so a built graph cannot change underneath.

    Frozen dataclasses are only shallowly immutable.  Before this boundary a
    caller could mutate ``GraphNode.section`` or ``GraphEdge.evidence`` after
    the census and federation had accepted them.  That turns an already-issued
    proof into different evidence.  Keep the accepted vocabulary deliberately
    small and deterministic instead of retaining arbitrary live objects.
    """

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise GraphBuildError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in sorted(value.items(), key=lambda pair: str(pair[0])):
            if not isinstance(key, str):
                raise GraphBuildError(f"{path} keys must be strings")
            frozen[key] = _freeze_json(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value))
    raise GraphBuildError(
        f"{path} contains unsupported {type(value).__name__}")


#: The values with which the graph flag is EXPLICITLY turned off. An empty string is not
#: among them: "the variable is absent" and "told to turn off" are different facts, and since
#: 22.08.2026 they give different answers.
_GRAPH_FLAG_OFF = frozenset({"0", "false", "no", "off"})


def building_graph_enabled() -> bool:
    """The building graph gate. Since 22.08.2026 the default is ON.

    ═══════════════════════════════════════════════════════════════════════
    WHAT BOUGHT THE DEFAULT SWITCH — A MEASUREMENT ACROSS THE WHOLE CORPUS
    ═══════════════════════════════════════════════════════════════════════
    The earlier edition kept the flag off with the argument "the module has never once
    been checked against a live Revit." The argument was correct and became insufficient: on 22.08
    the graph was run for the first time against the production MNVNK, and then against the WHOLE
    corpus of parses with the same inputs the pipeline supplies
    (`build_graph_for_run(run, room_adjacency=True)`):

        directories 88 · without `L0.jsonl` 12 · graph assembled **76 of 76**
        refusals **0** · census `assert_balanced()` balanced on **76 of 76**
        nodes 1 576 343 · edges 1 843 930
        longest parse — `демо-v3`, 90 758 nodes in 9.88 s

    Before that same day's fixes there were FIVE refusals (`k2_ar_rd_v1..v4`,
    `k4_geom_wave_15aug`), and all of them — not from the census, but from the premise "the header and
    the element stream are one population"; parsed in `OutsideExtraction.
    ROOM_NOT_IN_SNAPSHOT`. While they were failing, turning the flag on was not allowed, and
    that is exactly why a run across the CORPUS, not a single building, is the condition.

    ═══════════════════════════════════════════════════════════════════════
    WHAT GETS TURNED ON, AND WHAT IT COSTS THE TWO CONSUMERS
    ═══════════════════════════════════════════════════════════════════════
    * `pipeline.run_decompile` — places `building_graph.json` next to the
      parse. Cost on MNVNK: 3.03 s and a 251 MB peak against 41 minutes for the
      parse itself. A stage failure does NOT bring the run down and does NOT stay silent (`state.errors`);
    * `viewer/scene.py` — builds the graph layer when displaying a parse. The cost
      was measured in the same place and recorded by its author: 0.25 s on the facade, ~3.2 s on
      `демо-v3`; a layer failure does not bring the picture down.

    TURNED OFF BY AN EXPLICIT WORD: `KUKAI_IR_BUILDING_GRAPH=0` (also
    `false`/`no`/`off`). An unrecognized value is NOT treated as "turn off" —
    that would be a silent substitution of the default by a typo.

    🔴 WHAT THIS STILL DOES NOT MEAN: the graph is NOT AUTHORITATIVE on identity. Across
    the whole corpus `identity_authoritative` = **0 of 1 576 343**, and the reason is
    typed (see `identity.AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES`).
    Federation on these artifacts is impossible, and the artifact says so through its own
    census, rather than staying silent about it.
    """
    value = (env.get("KIR_BUILDING_GRAPH") or "").strip().lower()
    return value not in _GRAPH_FLAG_OFF


# ═══════════════════════════════════ NODE AXES


class Authority(str, Enum):
    """WHO is authoritative for this node. The load-bearing line of the whole undertaking."""

    #: Declared by the author (by the program or by a document that was read). The graph is the truth.
    DECLARED = "declared"
    #: Derived by Revit from the declared. Revit is the truth; the graph holds only the FACT
    #: that the node will be derived, and NEVER declares its geometry.
    DERIVED_BY_REVIT = "derived_by_revit"


class AuthoritySource(str, Enum):
    """BY WHAT the `authority` value was decided — a witness, not an opinion.

    The same device as `default_panel_source` for curtain walls and `host_source` for
    the host: read several sources and record WHICH ONE answered, so that
    one value does not stand for three different truths.
    """

    #: The element was read from the document as a standalone L0 row.
    L0_ELEMENT = "l0_element"
    #: The lifter named the element a generated child (`AtomReason.GENERATOR_CHILD`).
    #: The ONLY witness of derivedness that exists in the data today.
    LIFTER_GENERATOR_CHILD = "lifter_generator_child"
    #: A program op declared the node (a direct turn).
    PROGRAM_OP = "program_op"
    #: The op's contract declares side elements as derived (`route_*`).
    #: Requires an EXPLICIT statement by the caller; it is not derived from category.
    OP_DERIVED_CONTRACT = "op_derived_contract"


class Existence(str, Enum):
    """WHETHER the node EXISTS in the document, or is so far only declared."""

    #: Read from the document: an L0 row, or a confirmed build.
    MATERIALIZED = "materialized"
    #: Declared by a program that has not yet executed. The viewer must draw
    #: such a node differently, not with the same body.
    PLANNED = "planned"


class NodeRefusal(str, Enum):
    """The named reason a row did NOT become a node.

    The census balances only together with this enumeration: "fewer nodes than
    rows" without a named reason is a silent drop, exactly the defect
    the census law was written against.
    """

    #: The row has no non-empty `element_id` — there is nothing to address by.
    NO_ADDRESS = "no_address"
    #: The address is already taken by another row. This has NOT BEEN OBSERVED across the corpus
    #: (0 repeats out of 1 139 477 rows), but the refusal must exist: the law
    #: holds by verification, not by the corpus's luck.
    DUPLICATE_ADDRESS = "duplicate_address"
    #: The row EXISTS in the snapshot, but there is nothing to read it with: it does not parse
    #: as JSON, or it parsed as something other than an object (F-057).
    #:
    #: 🔴 WITHOUT THIS NAME A CORRUPTED SNAPSHOT PRODUCED A SMALLER BUILDING, AND THE CENSUS
    #: BALANCED. The L0 reader (`graph_store.read_l0_parts`) silently skipped a broken
    #: row; it never reached the `rows_seen` counter — and `nodes +
    #: refused == rows_seen` remained true about WHAT REMAINED. The census law
    #: holds an equality, not the completeness of the input: a row that never reached it
    #: cannot be protected by construction. So a broken row must
    #: arrive here AS A NUMBER.
    ROW_UNREADABLE = "row_unreadable"


class OutsideExtraction(str, Enum):
    """WHY the edge's target did not resolve. Mandatory on every
    `Modality.UNRESOLVED_TARGET`: "target outside the extraction" without a sub-reason is
    once again one word for different facts.

    THE 10.08 MEASUREMENT REFUTED THE HYPOTHESIS THAT THIS IS ONE BOUNDARY. A dangling `host_id` and
    a dangling `bounds_room` are DIFFERENT populations, and their distributions diverge by
    three orders of magnitude:

        `snowdon_elec_v1`  host: 959 edges -> **3** distinct targets (all — `link`)
        `snowdon_plumb_v5` host:  86 edges -> **4** targets; bounds_room: 0
        `демо-v3`          host:   0;  bounds_room: 4 352 edges -> **2 146**
                           distinct targets, median 2 edges per target
        `sob62_r23_v5`     host:   1;  bounds_room: 340 -> 184 targets

    Intersection of the target sets: **0** across three buildings, **1** on `sob62_r23_v5`
    (and that one is a `link` record). Merging them into one concept would mean
    repeating exactly the defect this whole module was written to take apart.
    """

    #: The target is a `link` record — resolved EXACTLY, the edge is not dangling at all.
    #: Kept in the enumeration so that "resolved into a link" has a name.
    RESOLVED_TO_LINK = "resolved_to_link"
    #: The target is neither an element nor a link of this snapshot. An honest "no
    #: data": the snapshot DOES NOT SAY what it was, and there is nothing to guess from — a row
    #: with this address is not in the stream at all.
    TARGET_NOT_IN_SNAPSHOT = "target_not_in_snapshot"
    #: The host CANNOT HAVE A BODY BY ITS NATURE (a reference plane and the like).
    #:
    #: THIS IS NOT AN EXTRACTION BOUNDARY BUT A PROPERTY OF THE THING, and that is why the class is separate:
    #: a link can be read to completion, but a reference plane will NEVER become a body.
    #: A corpus-wide measurement by the clash team: of 1 263 dangling edges, **1 010
    #: point into a linked file**, and **86 — into a `ReferencePlane`**, which
    #: `clash/hulls.KIND_TABLE` classifies as `not_a_body`.
    #:
    #: 🔴 CORRECTION OF 22.08.2026, AND IT NARROWS THE CLASS RATHER THAN REVOKES IT. The earlier
    #: edition added "there is nothing to finish reading for a reference plane" — that is,
    #: it merged "has no body" with "is not extracted". The second one has died: `extract`
    #: has learned to take `OST_CLines` (9 724 planes across 10 of 10 buildings), and
    #: on a fresh parse such a host WILL RESOLVE — into a datum node, via the
    #: `PLACED_ON_DATUM` edge. The class remains for exactly what it was set up for:
    #: to say the target is BODILESS when it is absent from this stream. All 76
    #: corpus snapshots were taken BEFORE the wave and carry 0 planes in the stream, so
    #: today the class answers on them exactly as before.
    #:
    #: THE VALUE IS NOT DERIVED FROM L0 AND IS NOT GUESSED HERE. These targets have no address in
    #: the stream, so there is nothing to say their category from; the knowledge lives in the clash
    #: team's kind table. A caller who has it supplies the list explicitly
    #: (`bodiless_target_ids`) — exactly the way `generator_child_ids`
    #: supplies the sole witness of derivedness. A graph that assigned this
    #: class itself would return a category guess, which is exactly what we are moving away from.
    HOST_CANNOT_HAVE_A_BODY = "host_cannot_have_a_body"
    #: A room boundary references an element that the reading did not put into
    #: the stream. The mass case is `демо-v3`: 2 146 distinct targets.
    BOUNDARY_ELEMENT_NOT_EXTRACTED = "boundary_element_not_extracted"
    #: The level named by the element is absent among the snapshot's elements.
    LEVEL_NOT_IN_SNAPSHOT = "level_not_in_snapshot"
    #: 🔴 THE HEADER'S ROOM IS ABSENT AMONG THE SNAPSHOT'S ELEMENTS.
    #:
    #: THE 22.08.2026 MEASUREMENT THAT BOUGHT THIS REASON ALSO REFUTES
    #: THE PREMISE "the header and the stream are one population". Running the graph over the WHOLE
    #: corpus (88 `backend/data/decompile` directories, 76 with `L0.jsonl`): five
    #: parses DID NOT ASSEMBLE AT ALL, refused with `ordinary graph edges require two
    #: assembled local nodes`. The reason is the same for all of them:
    #:
    #:     `k2_ar_rd_v1`        18 492 elements · header rooms 2 442,
    #:                          IN THE STREAM 0 · levels 59, in the stream 0
    #:     `k2_ar_rd_v2/v3/v4`  the same
    #:     `k4_geom_wave_15aug`    993 elements · rooms 1 150, in the stream 0
    #:     (control) `k2_ar_rd_v5` 55 293 elements · rooms 2 442,
    #:                          outside the stream 0 — the graph assembles
    #:
    #: The L0 header carries the DOCUMENT SUMMARY, and the stream carries what was actually read;
    #: on a truncated or partial read these are DIFFERENT SETS. The `bounds_room`/
    #: `bounded_by_same_wall` builders checked only the boundary ELEMENT and
    #: silently counted the room as a node. The outcome was the worst possible: not "an edge with
    #: a named boundary", but the refusal of the WHOLE GRAPH — that is, reading blindness
    #: turned into an inability to build the building's state.
    ROOM_NOT_IN_SNAPSHOT = "room_not_in_snapshot"


# ═══════════════════════════════════ EDGE AXES


class Relation(str, Enum):
    """WHAT KIND of relation. The axis is orthogonal to `Modality` — that is exactly the fix.

    Today a "clash finding" glues touching, body interpenetration, and
    shell intersection into one word, and all the imprecision grows out of that gluing.
    Here the relation and the proof are separated onto different axes.
    """

    # --- ASSEMBLY edges: a property of the building, live alongside the nodes permanently ---
    #: The element is placed IN a host (`L0Element.host_id`). A door in a wall,
    #: a mullion in a curtain wall. NOT the same as "sits on a level" — see `PLACED_ON_DATUM`.
    HOSTED_IN = "hosted_in"
    #: The element is placed in a LINKED DOCUMENT: the host is a `link` record of this
    #: same L0 stream. This is NOT "the host got lost" and NOT "there is no host" — it is a precise,
    #: positive fact, and the stream carries it.
    #:
    #: THE 10.08 MEASUREMENT (raw parse of `L0.jsonl`): `snowdon_elec_v1` — 959 of 1 001
    #: declared hosts point to ONLY THREE addresses, and all three are `link`
    #: records (`1362428`, `1362762`, `1484390`). `sob62_r23_v5` — the sole
    #: dangling host `20704534` is also a `link` record, and it also carries 88 room-boundary
    #: edges. Before this parse all of them were called "outside the extraction",
    #: that is, OUR blindness; in fact L0 knew the answer and no one had asked it.
    HOSTED_IN_LINK = "hosted_in_link"
    #: The declared host is NOT a physical element but a datum level (`OST_Levels`).
    #: Measurement: `snowdon_plumb_v5` — 21 `OST_GenericModel` and 4 `OST_PlumbingFixtures`
    #: have a level as their host. Dumping this into `hosted_in` would mean repeating
    #: the same gluing this whole module was written to take apart.
    PLACED_ON_DATUM = "placed_on_datum"
    #: The element is assigned to a level (`L0Element.level_id`).
    ON_LEVEL = "on_level"
    #: A level directly above another (by elevation).
    LEVEL_ABOVE = "level_above"
    #: The element is part of a room's boundary (`RoomInfo.bounding_element_ids`).
    BOUNDS_ROOM = "bounds_room"
    #: The GEOMETRY of two elements is JOINED (`JoinGeometryUtils.GetJoinedElements`).
    #: Symmetric: Revit declares the relation from both sides, and `GraphEdge.key`
    #: collapses the pair into one edge.
    #:
    #: 🔴 THIS IS NOT "ALLOWED TO JOIN". A measurement of 800 walls of a live document:
    #: both ends allowed and joined 143 of 288 · both disallowed and not
    #: joined 27 of 223 · mixed outcome 38 of 81. Allow-to-join is a
    #: property of ONE wall at ONE end (a different arity — it cannot
    #: be an edge) and lives in the field of the `join_extract.JoinRecord` record.
    #: Deriving one from the other is forbidden in both directions.
    JOINED_TO = "joined_to"
    #: JOINED AT THE END (`LocationCurve.get_ElementsAtJoin`). A third kind, and
    #: it is NOT derivable from either `JOINED_TO` or the allow-to-join permission.
    #:
    #: 🔴 ON ONE PAIR OF WALLS THIS KIND AND `JOINED_TO` ARE SYSTEMATICALLY
    #: OPPOSITE. The 18.08.2026 measurement on a live Revit: two walls butted end to end —
    #: the end is joined, but `AreElementsJoined` is **False**, and `JoinGeometry`
    #: REFUSES with «cannot be joined». The end join has already trimmed the curves,
    #: no body overlap remains, there is nothing left to merge. While this kind did not exist, such
    #: a pair read as "not joined" — exactly what made the owner say
    #: "nothing is joined to anything else."
    #:
    #: 🔴 AND IT IS NOT SYMMETRIC, UNLIKE `JOINED_TO`. The relation
    #: is addressed by END, and an end belongs to a specific wall: "at MY end
    #: 0 it stands" and "at ITS end 1 I stand" — two different facts about one
    #: joint, and their end numbers differ. Collapsing them via `GraphEdge.key`
    #: would mean losing exactly the value this kind was set up for:
    #: the key does not include `evidence`, so two edges of the same pair with DIFFERENT
    #: ends would collide as duplicates.
    JOINED_AT_END = "joined_at_end"
    #: THE TOP OF THE WALL FOLLOWS A LEVEL (`WALL_HEIGHT_TYPE`, «Зависимость сверху»).
    #: Directed: `src` — the wall, `dst` — the level its top follows.
    #:
    #: 🔴 THIS IS THE MOST MASSIVE RELATION OF A REAL BUILDING, AND IT WAS TRAVELING AS
    #: A PARAMETER. The 22.08.2026 measurement on the production MNVNK (33 944
    #: elements, 10 646 walls): `WALL_HEIGHT_TYPE` is set on **7 007 walls
    #: (65.8 %)**, and **7 007 of 7 007** of its values resolve to a node
    #: of category `OST_Levels` — zero dangling. Before this wave the number traveled in
    #: the row's `params` and was not a relation in the graph at all: "the wall is tied to
    #: the level at the top" could neither be asked, nor traversed, nor refuted.
    #:
    #: 🔴 AND THIS IS NOT `ON_LEVEL` AT THE TOP. `ON_LEVEL` reads `level_id` — the wall's
    #: BASE; the top is decided by a different parameter and POINTS TO A DIFFERENT LEVEL:
    #: they coincide only on **292 walls of 7 007** (4.2 %). Merging them would mean
    #: repeating exactly the gluing this module was written to take apart.
    #:
    #: 🔴 `WALL_BASE_CONSTRAINT` IS NOT INCLUDED HERE AND CANNOT BE: on MNVNK
    #: it equals `None` on **10 646 walls of 10 646**. The base arrives as `level_id`
    #: and is already expressed by `ON_LEVEL`; giving it a second edge would mean
    #: setting up a second carrier for one fact.
    TOP_CONSTRAINED_TO_LEVEL = "top_constrained_to_level"

    # --- TWO ROOM-ADJACENCY PREDICATES, named DIFFERENTLY (Ш4) ---
    #: A. Both rooms are bounded by ONE AND THE SAME opening host.
    #: The `fold._semantic_fold` predicate. A fact about Revit's DECLARATION (the room
    #: boundary calculation), not about the opening's geometry. The edge arises ONLY when the host
    #: bounds EXACTLY two rooms.
    BOUNDED_BY_SAME_WALL = "bounded_by_same_wall"
    #: B. The opening's POINT touches the room's polygon within tolerance.
    #: The `design_check._openings.touching` predicate. A fact about MEASURED geometry.
    OPENING_POINT_TOUCHES_ROOM = "opening_point_touches_room"


class Modality(str, Enum):
    """HOW MUCH the relation is proven. Orthogonal to `Relation`.

    `REFUTED` is not the absence of an edge but an edge with the name of the rule that
    removed it (`GraphEdge.refuted_by`). Without this, "did not find" is indistinguishable from "did not
    look", and both ailments return: it was exactly on the gluing of modality with the
    relation that `plate_z_doubling` and `profile_convexified` broke.
    """

    #: The relation was read from the document or was proven.
    PROVEN = "proven"
    #: The relation is allowed by the available data, but not proven by it.
    POSSIBLE = "possible"
    #: The relation is REFUTED by a named rule. The edge REMAINS in the graph.
    REFUTED = "refuted"
    #: The relation is declared by the source, but there is nothing to verify it with — the TARGET IS
    #: OUTSIDE THE EXTRACTION. This is NOT `possible`: there there is enough data and the answer is unknown,
    #: here there is no data at all. Measurement: 959 of 1 001 `host_id` values in
    #: `snowdon_elec_v1` point outside the snapshot.
    UNRESOLVED_TARGET = "unresolved_target"


_SYMMETRIC_RELATIONS = frozenset({
    Relation.BOUNDED_BY_SAME_WALL,
    Relation.OPENING_POINT_TOUCHES_ROOM,
    Relation.JOINED_TO,
})


#: THE OPTIONAL INPUT of `graph_from_l0` -> RELATIONS that, without it, remain
#: empty BY OUR BLINDNESS, not by the building's construction.
#:
#: 🔴 THE LIST IS COMPLETE BY CONSTRUCTION, and here is its authority: these are exactly the
#: `graph_from_l0` arguments whose absence EXTINGUISHES A WHOLE EDGE KIND. Other
#: optional inputs (`generator_child_ids`, `host_classes`,
#: `bodiless_target_ids`) do not extinguish a kind — they change the node's axis or the sub-reason
#: of a refusal, and their absence is visible in other census columns. This
#: correspondence is held by the test `test_graph_artifact.py`, not by convention: it takes
#: the `graph_from_l0` signature by reflection and requires that every extinguishing input
#: be named here.
#:
#: Without this table, "zero joint edges" and "the joint index was not supplied" arrive
#: as ONE value — exactly the form for whose sake this file set up
#: `Modality.UNRESOLVED_TARGET` and `NodeRefusal`.
#:
#: 🔴 `room_adjacency` STANDS HERE, NOT AMONG THE ORDINARY FLAGS, AND HERE IS WHY.
#: Nothing is supplied to predicate B from outside — it is computed from THAT SAME L0
#: (`header.rooms[].boundary_mm` + the opening's point). What extinguishes it is not the absence
#: of data but OUR REFUSAL TO COMPUTE IT, and by this file's law such a zero must
#: be named exactly as loudly: "the source was not supplied."
OPTIONAL_SOURCES: Mapping[str, tuple[Relation, ...]] = MappingProxyType({
    "joins": (Relation.JOINED_TO, Relation.JOINED_AT_END),
    "link_ids": (Relation.HOSTED_IN_LINK,),
    "room_adjacency": (Relation.OPENING_POINT_TOUCHES_ROOM,),
})


# ═══════════════════════════════════ NODE AND EDGE


@dataclass(frozen=True, slots=True)
class GraphNode:
    """Узел графа with a legacy local alias and federated identities.

    ``node_id`` remains the L0 ``ElementId`` string for compatibility with
    existing local edges and queries.  It is not authoritative outside one
    document.  ``definition_identity`` and ``occurrence_identity`` are the
    collision-free semantic addresses; legacy rows name their gaps instead
    of silently promoting ``ElementId`` to a global identity.
    """

    node_id: str
    category: str
    authority: Authority
    authority_source: AuthoritySource
    existence: Existence
    level_id: str | None = None
    type_id: str | None = None
    type_name: str | None = None
    #: `HostSource` as a string, or None = "not measured". Across the corpus — None EVERYWHERE
    #: (0 rows out of 1 139 477). Treating None as `family_instance` is forbidden.
    host_source: str | None = None
    #: THE MEASURED SECTION: parameters from the closed list `SECTION_PARAM_NAMES`,
    #: exactly as the reading sent them, the key is the `BuiltInParameter` name, which is also the provenance.
    #:
    #: WHY THIS IS HERE, AND NOT IN THE OP. The 10.08 measurement (`snowdon_plumb_v4`): L0 carries
    #: an outer diameter for **15 342 of 15 342 pipes**, and `lift._lift_pipe`
    #: reads only `RBS_PIPE_DIAMETER_PARAM` (the nominal) and drops the outer one.
    #: It CANNOT be recovered from the nominal, and this is not an opinion: the same nominal
    #: **50.8 gives TWO different outer diameters** — 60.325 (1 835 pipes) and 53.975
    #: (530 pipes). The outer diameter is a function of TYPE, not of the nominal; they coincide
    #: only on 20 of 15 342 pipes.
    section: Mapping[str, Any] = field(default_factory=dict)
    definition_identity: DefinitionIdentity | None = None
    occurrence_identity: OccurrenceIdentity | None = None
    identity_status: IdentityStatus = IdentityStatus.INCOMPLETE
    identity_gaps: tuple[IdentityGap, ...] = (
        IdentityGap.LEGACY_CONTEXT_ABSENT,)

    @property
    def local_element_id(self) -> str:
        """Compatibility alias; never use as a cross-document identity."""
        return self.node_id

    @property
    def identity_authoritative(self) -> bool:
        return self.identity_status is IdentityStatus.AUTHORITATIVE

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id:
            raise GraphBuildError("GraphNode.node_id must be a non-empty string")
        if not isinstance(self.category, str) or not self.category:
            raise GraphBuildError("GraphNode.category must be a non-empty string")
        if not isinstance(self.authority, Authority):
            raise GraphBuildError("GraphNode.authority must be an Authority")
        if not isinstance(self.authority_source, AuthoritySource):
            raise GraphBuildError(
                "GraphNode.authority_source must be an AuthoritySource — "
                "значение `authority` без названного свидетеля запрещено")
        if not isinstance(self.existence, Existence):
            raise GraphBuildError("GraphNode.existence must be an Existence")
        if not isinstance(self.section, Mapping):
            raise GraphBuildError("GraphNode.section must be a mapping")
        object.__setattr__(
            self, "section", _freeze_json(self.section, path="GraphNode.section"))
        if not isinstance(self.identity_status, IdentityStatus):
            raise GraphBuildError("GraphNode.identity_status must be typed")
        if isinstance(self.identity_gaps, str):
            raise GraphBuildError("GraphNode.identity_gaps must be a sequence")
        gaps = tuple(self.identity_gaps)
        if any(not isinstance(gap, IdentityGap) for gap in gaps):
            raise GraphBuildError("GraphNode.identity_gaps must contain IdentityGap")
        if len(gaps) != len(set(gaps)):
            raise GraphBuildError("GraphNode.identity_gaps must be unique")
        object.__setattr__(self, "identity_gaps", gaps)
        if (self.definition_identity is not None
                and not isinstance(self.definition_identity, DefinitionIdentity)):
            raise GraphBuildError("GraphNode.definition_identity must be typed")
        if (self.occurrence_identity is not None
                and not isinstance(self.occurrence_identity, OccurrenceIdentity)):
            raise GraphBuildError("GraphNode.occurrence_identity must be typed")
        if (self.occurrence_identity is not None
                and self.occurrence_identity.definition != self.definition_identity):
            raise GraphBuildError(
                "occurrence identity must reference the node definition identity")
        if self.identity_status is IdentityStatus.AUTHORITATIVE:
            if (self.definition_identity is None
                    or self.occurrence_identity is None or gaps):
                raise GraphBuildError(
                    "authoritative identity requires definition, occurrence, "
                    "and zero gaps")
        else:
            if self.occurrence_identity is not None:
                raise GraphBuildError(
                    "an occurrence identity cannot be marked incomplete")
            if not gaps:
                raise GraphBuildError(
                    "incomplete identity must name at least one gap")


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """An edge: the relation, the modality, and BY WHAT it was proven or refuted.

    `refuted_by` is mandatory exactly when `Modality.REFUTED` and forbidden otherwise —
    a refutation without the rule's name is that very silence the module
    is cured of, and a rule's name on an unproven edge is a false trail.
    """

    relation: Relation
    src: str
    dst: str
    modality: Modality
    #: The name of the RULE that removed the edge. Mandatory under REFUTED, forbidden otherwise.
    refuted_by: str | None = None
    #: What confirms the edge: the source, the field, the tolerance, the coarsening.
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.relation, Relation):
            raise GraphBuildError("GraphEdge.relation must be a Relation")
        if not isinstance(self.modality, Modality):
            raise GraphBuildError("GraphEdge.modality must be a Modality")
        for name, value in (("src", self.src), ("dst", self.dst)):
            if not isinstance(value, str) or not value:
                raise GraphBuildError(f"GraphEdge.{name} must be a non-empty string")
        if self.modality is Modality.REFUTED:
            if (not isinstance(self.refuted_by, str)
                    or not self.refuted_by.strip()):
                raise GraphBuildError(
                    "REFUTED без `refuted_by` неотличим от «не искали» — "
                    "правило, снявшее ребро, обязано назваться")
        elif self.refuted_by is not None:
            raise GraphBuildError(
                "`refuted_by` при модальности, отличной от REFUTED, — ложный след")
        if not isinstance(self.evidence, Mapping):
            raise GraphBuildError("GraphEdge.evidence must be a mapping")
        object.__setattr__(
            self, "evidence",
            _freeze_json(self.evidence, path="GraphEdge.evidence"))

    @property
    def key(self) -> tuple[str, str, str]:
        src, dst = self.src, self.dst
        if self.relation in _SYMMETRIC_RELATIONS:
            src, dst = sorted((src, dst))
        return (self.relation.value, src, dst)


# ═══════════════════════════════════ CENSUS


@dataclass(frozen=True, slots=True)
class GraphCensus:
    """`nodes = assessed + named refusals`. A condition, not a report."""

    rows_seen: int
    nodes: int
    refusals: Mapping[str, int]
    identity_authoritative_nodes: int = 0
    identity_incomplete_nodes: int | None = None
    identity_gaps: Mapping[str, int] = field(default_factory=dict)
    identity_context_authoritative: bool = False
    #: OPTIONAL INPUTS THAT WERE NOT SUPPLIED. Names from `OPTIONAL_SOURCES`.
    #:
    #: 🔴 WHY, BY THE 19.08.2026 MEASUREMENT ON THE TOWER. `graph_from_l0(..., joins=None)`
    #: built not a single joint edge, and the graph answered `joined_to: 0` —
    #: indistinguishable from "nothing in the building is joined". The tower
    #: has no `join.index.json`, it has 15 341 walls, and a live canon measurement
    #: gives 143 joined pairs out of 288. So the zero was OUR blindness, and
    #: an artifact on disk would have frozen it as a fact about the building.
    #:
    #: The comment at the edge-assembly site said this word for word — "`None` means
    #: the index was not supplied, an absence of KNOWLEDGE" — and the code did nothing with it.
    #: The prose was wider than the behavior — our named form, in the very file that names it.
    sources_absent: tuple[str, ...] = ()
    #: THE CENSUS OF PREDICATE B, if it was called. `None` — it was not called (in which case
    #: `room_adjacency` stands in `sources_absent`).
    #:
    #: 🔴 WHY, BY THE 04.09.2026 MEASUREMENT (RV-03). `graph_from_l0` called
    #: `opening_point_touches_room_edges`, took the EDGES, and threw the census away into
    #: a `_` variable. A door without `p0`/`bbox` yields zero edges and a NAMED refusal
    #: `opening_without_position`; the refusal was counted and went nowhere, while
    #: the graph answered "adjacency was measured". That is, for one and the same zero,
    #: "the predicate looked and found nothing" and "the predicate had nothing to look with"
    #: once again became one fact — exactly what `sources_absent`
    #: two fields above was set up against.
    #:
    #: The row's shape is set by `AdjacencyCensus.as_census_row`, and it is also what
    #: builds it: the law about the shape lives with the type, not with the reader.
    adjacency: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("rows_seen", self.rows_seen),
            ("nodes", self.nodes),
            ("identity_authoritative_nodes",
             self.identity_authoritative_nodes),
        ):
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise GraphBuildError(
                    f"GraphCensus.{name} must be a non-negative int")
        if not isinstance(self.identity_context_authoritative, bool):
            raise GraphBuildError(
                "GraphCensus.identity_context_authoritative must be boolean")
        incomplete = self.identity_incomplete_nodes
        if incomplete is None:
            incomplete = self.nodes - self.identity_authoritative_nodes
            object.__setattr__(self, "identity_incomplete_nodes", incomplete)
        if (isinstance(incomplete, bool) or not isinstance(incomplete, int)
                or incomplete < 0):
            raise GraphBuildError(
                "GraphCensus.identity_incomplete_nodes must be a "
                "non-negative int or null")

        if not isinstance(self.refusals, Mapping):
            raise GraphBuildError("GraphCensus.refusals must be a mapping")
        refusals: dict[str, int] = {}
        for name, count in self.refusals.items():
            if not isinstance(name, str) or not name.strip():
                raise GraphBuildError(
                    "GraphCensus refusal keys must be non-empty strings")
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise GraphBuildError(
                    "GraphCensus refusal counts must be non-negative ints")
            if count:
                refusals[name] = count

        if not isinstance(self.identity_gaps, Mapping):
            raise GraphBuildError(
                "GraphCensus.identity_gaps must be a mapping")
        gaps: dict[str, int] = {}
        for name, count in self.identity_gaps.items():
            if not isinstance(name, str) or not name.strip():
                raise GraphBuildError(
                    "identity gap census keys must be non-empty strings")
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise GraphBuildError(
                    "identity gap census counts must be non-negative ints")
            if count:
                gaps[name] = count
        if incomplete and not gaps:
            # Compatibility for direct v1 GraphCensus construction.  It is
            # explicit and red, never silently treated as authoritative.
            gaps = {IdentityGap.LEGACY_CONTEXT_ABSENT.value: incomplete}
        object.__setattr__(
            self, "refusals", MappingProxyType(dict(sorted(refusals.items()))))
        object.__setattr__(
            self, "identity_gaps", MappingProxyType(dict(sorted(gaps.items()))))

        if isinstance(self.sources_absent, str):
            raise GraphBuildError(
                "GraphCensus.sources_absent must be a sequence, not str")
        absent = tuple(sorted(set(self.sources_absent)))
        for name in absent:
            if name not in OPTIONAL_SOURCES:
                raise GraphBuildError(
                    f"GraphCensus.sources_absent: {name!r} не входит в закрытый "
                    f"список необязательных входов "
                    f"({', '.join(sorted(OPTIONAL_SOURCES))})")
        object.__setattr__(self, "sources_absent", absent)

        # 🔴 THE ADJACENCY CENSUS IS CHECKED HERE TOO, NOT ONLY AT HOME.
        # `AdjacencyCensus.assert_balanced` holds the same law at CONSTRUCTION time,
        # but an artifact from disk is read by `graph_from_dict`, and there not a single
        # `AdjacencyCensus` ever arises. Without this check a corrupted
        # file would yield a census that does not balance — exactly the
        # case for which `graph_from_dict` reruns
        # `GraphCensus.assert_balanced` instead of trusting the bytes.
        if self.adjacency is not None:
            row = self.adjacency
            if not isinstance(row, Mapping):
                raise GraphBuildError(
                    "GraphCensus.adjacency must be a mapping or null")
            expected = {"openings_seen", "openings_evaluated", "refusals",
                        "touch_degree", "rooms_seen", "rooms_by_geometry"}
            if set(row) != expected:
                raise GraphBuildError(
                    "GraphCensus.adjacency fields: "
                    f"{sorted(set(row) ^ expected)}")
            counts: dict[str, int] = {}
            for name in ("openings_seen", "openings_evaluated", "rooms_seen"):
                value = row[name]
                if (isinstance(value, bool) or not isinstance(value, int)
                        or value < 0):
                    raise GraphBuildError(
                        f"GraphCensus.adjacency.{name} must be a "
                        "non-negative int")
                counts[name] = value
            refused = 0
            for name in ("refusals", "touch_degree", "rooms_by_geometry"):
                block = row[name]
                if not isinstance(block, Mapping):
                    raise GraphBuildError(
                        f"GraphCensus.adjacency.{name} must be a mapping")
                for key, count in block.items():
                    if not isinstance(key, str) or not key.strip():
                        raise GraphBuildError(
                            f"GraphCensus.adjacency.{name} keys must be "
                            "non-empty strings")
                    if (isinstance(count, bool) or not isinstance(count, int)
                            or count < 0):
                        raise GraphBuildError(
                            f"GraphCensus.adjacency.{name} counts must be "
                            "non-negative ints")
                    if name == "refusals":
                        refused += count
            if (counts["openings_evaluated"] + refused
                    != counts["openings_seen"]):
                raise GraphBuildError(
                    "перепись смежности не сходится: проёмов "
                    f"{counts['openings_seen']}, оценено "
                    f"{counts['openings_evaluated']}, названных отказов "
                    f"{refused}")
            if "room_adjacency" in absent:
                raise GraphBuildError(
                    "перепись смежности есть, а `room_adjacency` объявлен "
                    "неподанным: измеренное и неизмеренное разом")
            object.__setattr__(
                self, "adjacency",
                _freeze_json(dict(row), path="GraphCensus.adjacency"))

        self.assert_balanced()

    def unmeasured_relations(self) -> tuple[Relation, ...]:
        """Relations whose SOURCE was not supplied. Their zero is not a fact about the building."""
        out: set[Relation] = set()
        for name in self.sources_absent:
            out.update(OPTIONAL_SOURCES[name])
        return tuple(sorted(out, key=lambda item: item.value))

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    @property
    def identity_authoritative(self) -> bool:
        return (self.identity_context_authoritative
                and self.identity_authoritative_nodes == self.nodes
                and self.identity_incomplete_nodes == 0
                and not self.identity_gaps)

    def assert_balanced(self) -> None:
        if self.nodes + self.refused != self.rows_seen:
            raise GraphBuildError(
                f"перепись графа не сходится: строк {self.rows_seen}, "
                f"узлов {self.nodes}, названных отказов {self.refused} "
                f"(молчаливое выпадение "
                f"{self.rows_seen - self.nodes - self.refused})")
        if (self.identity_authoritative_nodes
                + (self.identity_incomplete_nodes or 0) != self.nodes):
            raise GraphBuildError(
                "перепись identity не сходится: "
                f"узлов {self.nodes}, authoritative "
                f"{self.identity_authoritative_nodes}, incomplete "
                f"{self.identity_incomplete_nodes}")
        if ((self.identity_incomplete_nodes or 0) > 0
                and sum(self.identity_gaps.values())
                < (self.identity_incomplete_nodes or 0)):
            raise GraphBuildError(
                "не каждый identity-incomplete узел назвал причину")


# ═══════════════════════════════════ OBSERVATION FINGERPRINT


@dataclass(frozen=True, slots=True)
class ObservationFingerprint:
    """WHAT EXACTLY was observed: the document's change stamp and the snapshot's identity.

    🔴 WHY THIS IS HERE, AND NOT WITH THE CALLER. Before 07.09.2026 the graph carried NEITHER
    A REVISION NOR A FINGERPRINT: the representation knew the schema, `doc_name`, the document's
    identity, the federation context, the census, the nodes, and the edges — and nothing about
    WHEN this was taken. A consumer comparing the author's revision against the observation was
    forced to accept the fingerprint as the caller's DECLARATION, and there was nothing to verify
    the declaration with: derive it from a directory name, and it becomes a fingerprint of
    our assumption, not of the building.

    Both fields are DERIVED at construction time from the same L0 as the nodes:
    `change_stamp` lives in the snapshot's header, `l0_sha256` is computed by
    `graph_store` over the UNPACKED stream.

    🔴 THIS IS NOT `Capture.source_sha256`, AND THE DIFFERENCE IS MECHANICAL.
    `capture_edit._snapshot_digest` hashes the FILE'S BYTES, while the run janitor
    compresses `L0.jsonl` into `L0.jsonl.gz` — meaning for one and the same building, its
    number changes because of COMPRESSION, an event that has nothing to do with the building. Here
    the STREAM'S CONTENT is hashed, so a cold run gives the same number
    as a hot one. The two numbers must NOT be checked against each other: they count
    different things and will match only by coincidence — on an uncompressed snapshot.
    """

    change_stamp: str
    l0_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.change_stamp, str) or not self.change_stamp.strip():
            raise GraphBuildError(
                "ObservationFingerprint.change_stamp: снимок без штампа "
                "изменения не датирован — пустая строка была бы выдумкой")
        if (not isinstance(self.l0_sha256, str) or len(self.l0_sha256) != 64
                or any(char not in "0123456789abcdef" for char in self.l0_sha256)):
            raise GraphBuildError(
                "ObservationFingerprint.l0_sha256 must be a lowercase sha256")

    def to_dict(self) -> dict[str, str]:
        return {"change_stamp": self.change_stamp, "l0_sha256": self.l0_sha256}

    @classmethod
    def from_dict(cls, payload: Any) -> "ObservationFingerprint":
        payload = _as_mapping(payload, "observation fingerprint")
        return cls(change_stamp=payload.get("change_stamp"),
                   l0_sha256=payload.get("l0_sha256"))


#: The fingerprint was DERIVED when the graph was built from L0.
FINGERPRINT_DERIVED = "derived"
#: There is no fingerprint: a `/1`-version artifact, or a graph assembled without a snapshot.
#: 🔴 THERE IS DELIBERATELY NO THIRD VALUE: "undated" must be distinguishable from
#: "dated with emptiness", otherwise an old artifact would silently receive a date.
FINGERPRINT_ABSENT = "absent"


# ═══════════════════════════════════ GRAPH


class BuildingGraph:
    """The typed building graph: nodes with an L0 address + edges with a modality.

    Clash edges do NOT LIVE here and cannot — the measurement names the threshold in advance:
    `демо-v3` gives 84 120 nodes against 770 234 candidate pairs (a ratio of
    **9.15**), a 666 MB report, a 2.66 GB peak RSS. Clash enters the graph via a SCOPED
    QUERY — see `graph_clash_query.py`.
    """

    __slots__ = (
        "doc_name", "document_identity", "federation_context", "observation",
        "_nodes", "_edges", "census", "_out", "_in", "_by_relation",
        "_by_definition", "_by_occurrence",
    )

    def __init__(
        self,
        *,
        doc_name: str,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        census: GraphCensus,
        document_identity: DocumentIdentity | None = None,
        federation_context: FederationContext | None = None,
        observation: ObservationFingerprint | None = None,
    ) -> None:
        if (document_identity is not None
                and not isinstance(document_identity, DocumentIdentity)):
            raise GraphBuildError("document_identity must be typed")
        if (observation is not None
                and not isinstance(observation, ObservationFingerprint)):
            raise GraphBuildError("observation must be ObservationFingerprint")
        if (federation_context is not None
                and not isinstance(federation_context, FederationContext)):
            raise GraphBuildError("federation_context must be typed")
        self.doc_name = doc_name
        self.document_identity = document_identity
        self.federation_context = federation_context
        self.observation = observation
        mutable_nodes: dict[str, GraphNode] = {}
        by_definition: dict[DefinitionIdentity, list[GraphNode]] = defaultdict(list)
        by_occurrence: dict[OccurrenceIdentity, GraphNode] = {}
        identity_authoritative_nodes = 0
        identity_incomplete_nodes = 0
        identity_gaps: Counter[str] = Counter()
        for node in nodes:
            if not isinstance(node, GraphNode):
                raise GraphBuildError("BuildingGraph nodes must be GraphNode")
            if node.node_id in mutable_nodes:
                raise GraphBuildError(
                    f"повтор адреса узла {node.node_id!r}")
            mutable_nodes[node.node_id] = node
            if node.definition_identity is not None:
                by_definition[node.definition_identity].append(node)
            if node.occurrence_identity is not None:
                if node.occurrence_identity in by_occurrence:
                    raise GraphBuildError(
                        "повтор authoritative occurrence identity "
                        f"{node.occurrence_identity.key}")
                by_occurrence[node.occurrence_identity] = node
            if node.identity_authoritative:
                identity_authoritative_nodes += 1
            else:
                identity_incomplete_nodes += 1
                identity_gaps.update(gap.value for gap in node.identity_gaps)
        edge_rows = tuple(edges)
        if any(not isinstance(edge, GraphEdge) for edge in edge_rows):
            raise GraphBuildError("BuildingGraph edges must be GraphEdge")
        edge_keys = [edge.key for edge in edge_rows]
        if len(edge_keys) != len(set(edge_keys)):
            raise GraphBuildError(
                "duplicate relation/src/dst edge truth is forbidden")
        self._edges = edge_rows
        self.census = census
        if not isinstance(census, GraphCensus):
            raise GraphBuildError("BuildingGraph census must be GraphCensus")
        census.assert_balanced()
        if (census.identity_authoritative_nodes != identity_authoritative_nodes
                or census.identity_incomplete_nodes != identity_incomplete_nodes
                or dict(census.identity_gaps) != dict(identity_gaps)):
            raise GraphBuildError(
                "identity census does not match GraphNode identity states")
        context_authoritative = (
            document_identity is not None and federation_context is not None)
        if census.identity_context_authoritative != context_authoritative:
            raise GraphBuildError(
                "identity context census disagrees with graph context")

        out: dict[str, list[GraphEdge]] = defaultdict(list)
        incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        by_relation: dict[Relation, list[GraphEdge]] = defaultdict(list)
        for edge in self._edges:
            src_local = edge.src in mutable_nodes
            dst_local = edge.dst in mutable_nodes
            if edge.modality is Modality.UNRESOLVED_TARGET:
                if src_local == dst_local:
                    raise GraphBuildError(
                        "UNRESOLVED_TARGET requires exactly one local endpoint "
                        "and one external endpoint")
                why = edge.evidence.get("why")
                if why not in {item.value for item in OutsideExtraction}:
                    raise GraphBuildError(
                        "UNRESOLVED_TARGET requires a typed evidence.why")
            elif (edge.relation is Relation.HOSTED_IN_LINK
                  and edge.modality is Modality.PROVEN):
                if not src_local:
                    raise GraphBuildError(
                        "HOSTED_IN_LINK requires a local source node")
                if (edge.evidence.get("why")
                        != OutsideExtraction.RESOLVED_TO_LINK.value):
                    raise GraphBuildError(
                        "HOSTED_IN_LINK requires exact resolved_to_link evidence")
                # The link row is a typed L0 external reference.  Its exact id
                # may also be represented locally by a future graph revision;
                # both cases remain unambiguous under this relation tag.
            elif not src_local or not dst_local:
                raise GraphBuildError(
                    "ordinary graph edges require two assembled local nodes")
            out[edge.src].append(edge)
            incoming[edge.dst].append(edge)
            by_relation[edge.relation].append(edge)

        self._nodes = MappingProxyType(mutable_nodes)
        self._by_definition = MappingProxyType({
            identity: tuple(rows) for identity, rows in by_definition.items()})
        self._by_occurrence = MappingProxyType(by_occurrence)
        self._out = MappingProxyType({
            node_id: tuple(rows) for node_id, rows in out.items()})
        self._in = MappingProxyType({
            node_id: tuple(rows) for node_id, rows in incoming.items()})
        self._by_relation = MappingProxyType({
            relation: tuple(rows) for relation, rows in by_relation.items()})

    # --- access ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, node_id: object) -> bool:
        return node_id in self._nodes

    @property
    def nodes(self) -> Mapping[str, GraphNode]:
        return self._nodes

    @property
    def edges(self) -> tuple[GraphEdge, ...]:
        return self._edges

    @property
    def identity_authoritative(self) -> bool:
        return self.census.identity_authoritative

    @property
    def fingerprint_status(self) -> str:
        """`derived` or `absent`. "Undated" is not the same as "empty"."""
        return (FINGERPRINT_ABSENT if self.observation is None
                else FINGERPRINT_DERIVED)

    def nodes_for_definition(
            self, identity: DefinitionIdentity) -> tuple[GraphNode, ...]:
        if not isinstance(identity, DefinitionIdentity):
            raise GraphBuildError("definition lookup requires DefinitionIdentity")
        return tuple(self._by_definition.get(identity, ()))

    def node_for_occurrence(self, identity: OccurrenceIdentity) -> GraphNode:
        if not isinstance(identity, OccurrenceIdentity):
            raise GraphBuildError("occurrence lookup requires OccurrenceIdentity")
        try:
            return self._by_occurrence[identity]
        except KeyError:
            raise GraphBuildError(
                f"occurrence {identity.key!r} is not in the graph") from None

    def node(self, node_id: str) -> GraphNode:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise GraphBuildError(f"узла {node_id!r} в графе нет") from None

    def out_edges(self, node_id: str,
                  relation: Relation | None = None) -> tuple[GraphEdge, ...]:
        got = self._out.get(node_id, ())
        if relation is None:
            return tuple(got)
        return tuple(e for e in got if e.relation is relation)

    def in_edges(self, node_id: str,
                 relation: Relation | None = None) -> tuple[GraphEdge, ...]:
        got = self._in.get(node_id, ())
        if relation is None:
            return tuple(got)
        return tuple(e for e in got if e.relation is relation)

    def relation_edges(self, relation: Relation) -> tuple[GraphEdge, ...]:
        return tuple(self._by_relation.get(relation, ()))

    # --- summaries ----------------------------------------------------------

    def authority_counts(self) -> Mapping[str, int]:
        return dict(Counter(n.authority.value for n in self._nodes.values()))

    def existence_counts(self) -> Mapping[str, int]:
        return dict(Counter(n.existence.value for n in self._nodes.values()))

    def relation_counts(self) -> Mapping[str, int]:
        """The edge count by kind. AN EMPTY KIND DOES NOT LAND HERE AT ALL.

        🔴 A MISSING KEY MUST NOT BE READ AS ZERO: a kind can be empty because
        its source was not supplied (`census.sources_absent`). Ask
        `relation_count()` if the answer is going to feed a decision.
        """
        return {rel.value: len(edges)
                for rel, edges in sorted(self._by_relation.items(),
                                         key=lambda kv: kv[0].value)
                if edges}

    def relation_count(self, relation: Relation) -> int:
        """How many edges of this kind — OR a refusal "source not supplied".

        Three outcomes, as with a document's directory, and for the same reason:

            edges exist                 — a number;
            source supplied, no edges   — ZERO, a fact about the BUILDING;
            source not supplied         — REFUSAL, a fact about OUR reading.

        The measurement that bought this: the tower `k2_ar_rd_v15` has no
        `join.index.json`, and the graph answered "0 joints" with 15 341 walls. A live
        canon measurement on 800 walls gives 143 joined pairs out of 288 — that is,
        the real number is known to be large, and the zero was our blindness.
        """
        if not isinstance(relation, Relation):
            raise GraphBuildError("relation_count ждёт Relation")
        if relation in self.census.unmeasured_relations():
            missing = ", ".join(
                name for name in self.census.sources_absent
                if relation in OPTIONAL_SOURCES[name])
            raise GraphBuildError(
                f"род {relation.value!r} НЕ ИЗМЕРЕН: не подан источник "
                f"({missing}). Ноль здесь означал бы факт о здании, а это "
                f"факт о нашем чтении")
        return len(self._by_relation.get(relation, ()))

    def unmeasured_relations(self) -> tuple[Relation, ...]:
        """Kinds whose zero means nothing. An empty tuple — everything was measured."""
        return self.census.unmeasured_relations()

    def modality_counts(self,
                        relation: Relation | None = None) -> Mapping[str, int]:
        source = (self._by_relation.get(relation, ())
                  if relation is not None else self._edges)
        return dict(Counter(e.modality.value for e in source))

    def refuted_by_counts(self) -> Mapping[str, int]:
        """What exactly the edges were captured by. An empty summary and the absence of a summary are different."""
        return dict(Counter(
            e.refuted_by for e in self._edges
            if e.modality is Modality.REFUTED and e.refuted_by))

    def unresolved_targets(self) -> tuple[GraphEdge, ...]:
        """Edges whose TARGET is outside the extraction. The main cross-partition signal."""
        return tuple(e for e in self._edges
                     if e.modality is Modality.UNRESOLVED_TARGET)

    # --- artifact -------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """The graph as a JSON-representable value. The inverse is `graph_from_dict`.

        🔴 WHY THIS IS HERE, AND NOT IN A SEPARATE MODULE. A serializer living
        far from the type is a second carrier of the shape: a field added to `GraphNode`
        will not force it to change, and the loss will be silent. Here it is caught by
        a round-trip run that checks OBJECTS, not bytes.

        🔴 CLASH EDGES CANNOT BE WRITTEN, AND THIS IS NOT A CONVENTION. An edge is printed
        through `Relation`, where clash relations DO NOT EXIST AT ALL — they live as a separate
        type in `graph_clash_query.py`. So the prohibition is held by the type system,
        not by a comment, and it is confirmed by a control: a payload naming an
        unknown relation REFUSES on read.
        """
        return {
            "schema": GRAPH_ARTIFACT_SCHEMA,
            "doc_name": self.doc_name,
            # 🔴 `/2` DIFFERS FROM `/1` BY EXACTLY THESE TWO KEYS, and the second
            # is mandatory: without `fingerprint_status` a `null` read back would mean
            # both "did not date" and "dated with emptiness".
            "observation": (None if self.observation is None
                            else self.observation.to_dict()),
            "fingerprint_status": self.fingerprint_status,
            "document_identity": (self.document_identity.as_dict()
                                  if self.document_identity else None),
            "federation_context": (self.federation_context.as_dict()
                                   if self.federation_context else None),
            "census": {
                "rows_seen": self.census.rows_seen,
                "nodes": self.census.nodes,
                "refusals": dict(self.census.refusals),
                "identity_authoritative_nodes":
                    self.census.identity_authoritative_nodes,
                "identity_incomplete_nodes":
                    self.census.identity_incomplete_nodes,
                "identity_gaps": dict(self.census.identity_gaps),
                "identity_context_authoritative":
                    self.census.identity_context_authoritative,
                # 🔴 GOES TO DISK, MANDATORY. Without this line the artifact
                # would freeze "zero joints" as a fact about the building where
                # the joint index simply was not supplied.
                "sources_absent": list(self.census.sources_absent),
                # 🔴 GOES TO DISK FOR THE SAME REASON AS THE LINE ABOVE.
                # `null` here means "the predicate was not called", not "it had no
                # refusals": without this the artifact would again freeze
                # "zero adjacency" where the door simply had no point.
                # The artifact's schema DOES NOT MIGRATE: the key is read via `.get`,
                # meaning anything captured before today reads as "was not asked" —
                # the same optionality as `slopes` in `sketch_extract`.
                "adjacency": (_thaw_json(self.census.adjacency)
                              if self.census.adjacency is not None else None),
            },
            "nodes": [_node_to_dict(node)
                      for node in self._nodes.values()],
            "edges": [_edge_to_dict(edge) for edge in self._edges],
        }


# ═══════════════════════════════════ ARTIFACT ON DISK

#: The artifact's schema version. A reader that meets a foreign one REFUSES loudly:
#: silently reading old bytes as new ones is the same ailment
#: `TEMPLATE_CANON_VERSION` protects the collapsed tree from.
#: The earlier form, WITHOUT an observation fingerprint. Still readable: 76 corpus
#: parses lie on disk in exactly this form, and declaring them unreadable would mean
#: losing the buildings' state for the sake of a key that was never in them. Such a graph
#: honestly answers `fingerprint_status: absent`.
GRAPH_ARTIFACT_SCHEMA_V1 = "building-graph/1"
GRAPH_ARTIFACT_SCHEMA = "building-graph/2"
#: What the reader KNOWS how to parse. Everything else is a loud refusal, as before.
READABLE_GRAPH_SCHEMAS: frozenset[str] = frozenset(
    {GRAPH_ARTIFACT_SCHEMA_V1, GRAPH_ARTIFACT_SCHEMA})


def _thaw_json(value: Any) -> Any:
    """`MappingProxyType`/tuple back into what `json.dump` can handle.

    Needed because `_freeze_json` deliberately returns immutable views, and
    `json.dump` does not accept them: `MappingProxyType` drops the whole serialization.
    """
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


def _node_to_dict(node: GraphNode) -> dict[str, Any]:
    """A node in JSON. A field with a default value is OMITTED — but only where
    the default and absence mean ONE AND THE SAME THING.

    `identity_gaps` is ALWAYS printed, even when empty: its default is
    `(LEGACY_CONTEXT_ABSENT,)`, not emptiness, so an omission would read as a
    named gap where there are no gaps. Exactly the case where "absent"
    and "empty" are different facts.
    """
    row: dict[str, Any] = {
        "node_id": node.node_id,
        "category": node.category,
        "authority": node.authority.value,
        "authority_source": node.authority_source.value,
        "existence": node.existence.value,
        "identity_status": node.identity_status.value,
        "identity_gaps": [gap.value for gap in node.identity_gaps],
    }
    for name in ("level_id", "type_id", "type_name", "host_source"):
        value = getattr(node, name)
        if value is not None:
            row[name] = value
    if node.section:
        row["section"] = _thaw_json(node.section)
    if node.definition_identity is not None:
        row["definition_identity"] = node.definition_identity.as_dict()
    if node.occurrence_identity is not None:
        row["occurrence_identity"] = node.occurrence_identity.as_dict()
    return row


def _edge_to_dict(edge: GraphEdge) -> dict[str, Any]:
    row: dict[str, Any] = {
        "relation": edge.relation.value,
        "src": edge.src,
        "dst": edge.dst,
        "modality": edge.modality.value,
    }
    if edge.refuted_by is not None:
        row["refuted_by"] = edge.refuted_by
    if edge.evidence:
        row["evidence"] = _thaw_json(edge.evidence)
    return row


def _enum_from(cls: Any, value: Any, what: str) -> Any:
    """A value from a closed dictionary — or a NAMED REFUSAL. Never a default."""
    try:
        return cls(value)
    except ValueError:
        raise GraphBuildError(
            f"{what}: {value!r} не принадлежит закрытому словарю "
            f"{cls.__name__} ({', '.join(sorted(item.value for item in cls))})"
        ) from None


def _document_identity_from(payload: Any) -> DocumentIdentity | None:
    if payload is None:
        return None
    payload = _as_mapping(payload, "document_identity")
    return DocumentIdentity(value=str(payload.get("value") or ""))


def _federation_context_from(payload: Any) -> FederationContext | None:
    if payload is None:
        return None
    payload = _as_mapping(payload, "federation_context")
    return FederationContext(
        federation_root=str(payload.get("federation_root") or ""),
        link_instance_chain=tuple(payload.get("link_instance_chain") or ()),
    )


def _definition_identity_from(payload: Any) -> DefinitionIdentity | None:
    if payload is None:
        return None
    payload = _as_mapping(payload, "definition_identity")
    document = _document_identity_from(payload.get("document"))
    if document is None:
        raise GraphBuildError("definition_identity без document")
    return DefinitionIdentity(
        document=document,
        element_unique_id=str(payload.get("element_unique_id") or ""))


def _occurrence_identity_from(payload: Any) -> OccurrenceIdentity | None:
    if payload is None:
        return None
    payload = _as_mapping(payload, "occurrence_identity")
    definition = _definition_identity_from(payload.get("definition"))
    if definition is None:
        raise GraphBuildError("occurrence_identity без definition")
    return OccurrenceIdentity(
        federation_root=str(payload.get("federation_root") or ""),
        link_instance_chain=tuple(payload.get("link_instance_chain") or ()),
        definition=definition)


def graph_from_dict(payload: Mapping[str, Any]) -> BuildingGraph:
    """A graph FROM an artifact. The inverse of `BuildingGraph.to_dict`.

    🔴 READING GOES THROUGH THE SAME CONSTRUCTORS AS CONSTRUCTION, and this is a load-bearing
    property, not tidiness. `GraphNode.__post_init__`,
    `GraphEdge.__post_init__`, `GraphCensus.assert_balanced()`, and all the checks in
    `BuildingGraph.__init__` are rerun on what was read. This means **a corrupted
    file REFUSES, rather than yielding a lying graph**: a census that does not balance with
    its contents is unconstructable — exactly the same condition as when building from
    L0. An artifact that can be read is an artifact whose census balanced.

    A foreign schema version is a loud refusal, not an attempt to parse.
    """
    payload = _as_mapping(payload, "graph artifact")
    schema = payload.get("schema")
    if schema not in READABLE_GRAPH_SCHEMAS:
        raise GraphBuildError(
            f"артефакт графа версии {schema!r}, читатель знает "
            f"{sorted(READABLE_GRAPH_SCHEMAS)} — разбирать чужую форму запрещено")
    # 🔴 `/1` DOES NOT GET A FINGERPRINT RETROACTIVELY. Neither the directory name, nor
    # `doc_name`, nor the file's date is a fingerprint: there is nothing to recover it
    # with, and calling it "absent" is the only honest outcome.
    raw_observation = payload.get("observation")
    observation = (ObservationFingerprint.from_dict(raw_observation)
                   if raw_observation is not None else None)
    declared_status = payload.get("fingerprint_status")
    if declared_status is not None:
        expected = (FINGERPRINT_ABSENT if observation is None
                    else FINGERPRINT_DERIVED)
        if declared_status != expected:
            raise GraphBuildError(
                f"artifact fingerprint_status {declared_status!r} contradicts "
                f"its own observation payload ({expected!r})")

    census_payload = _as_mapping(payload.get("census"), "census")
    census = GraphCensus(
        rows_seen=census_payload.get("rows_seen", 0),
        nodes=census_payload.get("nodes", 0),
        refusals=_as_mapping(census_payload.get("refusals") or {}, "refusals"),
        identity_authoritative_nodes=census_payload.get(
            "identity_authoritative_nodes", 0),
        identity_incomplete_nodes=census_payload.get(
            "identity_incomplete_nodes"),
        identity_gaps=_as_mapping(
            census_payload.get("identity_gaps") or {}, "identity_gaps"),
        identity_context_authoritative=bool(
            census_payload.get("identity_context_authoritative", False)),
        sources_absent=tuple(census_payload.get("sources_absent") or ()),
        adjacency=(_as_mapping(census_payload["adjacency"],
                               "census.adjacency")
                   if census_payload.get("adjacency") is not None else None),
    )

    nodes: list[GraphNode] = []
    for row in payload.get("nodes") or ():
        row = _as_mapping(row, "node row")
        nodes.append(GraphNode(
            node_id=str(row.get("node_id") or ""),
            category=str(row.get("category") or ""),
            authority=_enum_from(Authority, row.get("authority"),
                                 "GraphNode.authority"),
            authority_source=_enum_from(
                AuthoritySource, row.get("authority_source"),
                "GraphNode.authority_source"),
            existence=_enum_from(Existence, row.get("existence"),
                                 "GraphNode.existence"),
            level_id=row.get("level_id"),
            type_id=row.get("type_id"),
            type_name=row.get("type_name"),
            host_source=row.get("host_source"),
            section=row.get("section") or {},
            definition_identity=_definition_identity_from(
                row.get("definition_identity")),
            occurrence_identity=_occurrence_identity_from(
                row.get("occurrence_identity")),
            identity_status=_enum_from(
                IdentityStatus, row.get("identity_status"),
                "GraphNode.identity_status"),
            identity_gaps=tuple(
                _enum_from(IdentityGap, gap, "GraphNode.identity_gaps")
                for gap in (row.get("identity_gaps") or ())),
        ))

    edges: list[GraphEdge] = []
    for row in payload.get("edges") or ():
        row = _as_mapping(row, "edge row")
        edges.append(GraphEdge(
            relation=_enum_from(Relation, row.get("relation"),
                                "GraphEdge.relation"),
            src=str(row.get("src") or ""),
            dst=str(row.get("dst") or ""),
            modality=_enum_from(Modality, row.get("modality"),
                                "GraphEdge.modality"),
            refuted_by=row.get("refuted_by"),
            evidence=row.get("evidence") or {},
        ))

    return BuildingGraph(
        doc_name=str(payload.get("doc_name") or ""),
        nodes=nodes,
        edges=edges,
        census=census,
        document_identity=_document_identity_from(
            payload.get("document_identity")),
        federation_context=_federation_context_from(
            payload.get("federation_context")),
        observation=observation,
    )


# ═══════════════════════════════════ CONSTRUCTION FROM L0


#: A category whose element is a DATUM, not a body. A datum host travels via
#: `PLACED_ON_DATUM`, not via `HOSTED_IN` — see the comment at Relation.
#: DATUM CATEGORIES: a host from this set gives `PLACED_ON_DATUM`, not
#: `HOSTED_IN`. A datum is an author's mark, not a physical body, and gluing
#: "door IN THE WALL" together with "instrument ON THE DATUM" would mean repeating exactly
#: the gluing this module was written to take apart.
#:
#: 🔴 `OST_CLines` (REFERENCE PLANES) WERE ADDED ON 22.08.2026, AND THIS IS THE CONSEQUENCE
#: OF SOMEONE ELSE'S WAVE, NOT OUR WHIM. On that day `extract` learned to take them
#: (`CategorySpec("OST_CLines", ".OfClass(typeof(ReferencePlane))")`) — before
#: that, planes were not extracted AT ALL, and a plane-host could only be
#: dangling. The numbers on both sides:
#:
#:     planes in the corpus (header census)          9 724 across 10 of 10 buildings
#:     hosts of class `ReferencePlane` today          86, all `snowdon_plumb_v5`
#:     in the corpus's L0 stream on disk               0 — all snapshots predate the wave
#:
#: This means that on the NEXT live parse these 86 edges will stop being
#: `UNRESOLVED_TARGET/host_cannot_have_a_body` and will become resolved. Without
#: this line they would have become `HOSTED_IN` — that is, "the instrument is placed IN a reference
#: plane", next to "the door is placed IN the wall". With it they become
#: `PLACED_ON_DATUM`, exactly like the 25 instruments whose host is a level.
#:
#: THE KEY IS SPECIFICALLY `OST_CLines`, not `OST_ReferencePlanes`: `ReferencePlane` is
#: a Revit CLASS, and the census measures CATEGORY, and the extractor's row is named after
#: the category deliberately (its argument is in that file's `CategorySpec` header).
#: Separate from this lives `_HOST_CLASS_BODILESS`, which reads the CLASS from
#: a side index — it answers a different question: what the target was, when it is
#: NOT in the stream.
_DATUM_CATEGORIES: frozenset[str] = frozenset({
    "OST_Levels", "OST_Grids", "OST_CLines"})

_ROOM_CATEGORY = "OST_Rooms"


def _section_of(element: Mapping[str, Any]) -> dict[str, Any]:
    """The row's measured section parameters — from the CLOSED reading list.

    The list is taken from `extract.SECTION_PARAM_NAMES`, not rewritten: two
    dictionaries for one fact diverge, and this package has already paid for that (a third
    private discipline dictionary, canon /4).
    """
    from kir.decompile.extract import SECTION_PARAM_NAMES

    params = element.get("params") or {}
    if not isinstance(params, Mapping):
        return {}
    return {name: params[name] for name in SECTION_PARAM_NAMES
            if params.get(name) is not None}


#: Parameters carrying the body's OUTER dimension, in order of preference.
#: The outer dimension answers the question "what space does the element occupy"; the nominal is
#: the type size's NAME, and it is not a body.
_OUTER_SECTION_PARAMS: tuple[str, ...] = (
    "RBS_PIPE_OUTER_DIAMETER",
    "RBS_CONDUIT_OUTER_DIAM_PARAM",
)

#: The NOMINAL parameters. Kept separate and NEVER substituted for the
#: outer dimension: the `snowdon_plumb_v4` measurement — a nominal of 50.8 corresponds to both 60.325 and
#: 53.975, meaning the nominal->outer mapping is NOT A FUNCTION.
_NOMINAL_SECTION_PARAMS: tuple[str, ...] = (
    "RBS_PIPE_DIAMETER_PARAM",
    "RBS_CONDUIT_DIAMETER_PARAM",
    "RBS_CURVE_DIAMETER_PARAM",
)


def outer_size_mm(node: "GraphNode") -> tuple[float, str] | None:
    """(outer dimension, BY WHAT it was measured) or None — NEVER the nominal.

    Returns None when there is no outer dimension, even if the nominal exists. Substituting
    the nominal would mean declaring the type size's name a body and being wrong by 9.525 mm
    on every other pipe — silently and in the dangerous direction (the body is SMALLER than the real one,
    meaning a clash will not be found).
    """
    for name in _OUTER_SECTION_PARAMS:
        value = node.section.get(name)
        if isinstance(value, (int, float)):
            return float(value), name
    return None


def _as_mapping(value: Any, what: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GraphBuildError(f"{what} must be a mapping, got {type(value).__name__}")
    return value


def graph_from_l0(
    header: Mapping[str, Any],
    elements: Iterable[Mapping[str, Any]],
    *,
    document_identity: DocumentIdentity | None = None,
    federation_context: FederationContext | None = None,
    generator_child_ids: Iterable[str] = (),
    link_ids: Iterable[str] = _NOT_GIVEN,
    bodiless_target_ids: Iterable[str] = (),
    host_classes: Mapping[str, str] | None = None,
    joins: Mapping[str, Any] | None = None,
    room_adjacency: bool = False,
    #: THE OBSERVATION FINGERPRINT. Is not derived here and cannot be: this
    #: input sees the PARSED header and rows, not the snapshot's bytes. It is computed
    #: by `graph_store.build_graph_for_run`, which holds the path to L0 in hand.
    observation: "ObservationFingerprint | None" = None,
    #: How many snapshot rows the READER could not parse and so did not supply
    #: here at all. Travels as a NUMBER, not as rows: there is nothing to parse them with, and
    #: staying silent about them is not allowed — see `NodeRefusal.ROW_UNREADABLE` (F-057).
    unreadable_rows: int = 0,
) -> BuildingGraph:
    """Build a graph from RAW L0 (a header + element rows).

    ``document_identity`` and ``federation_context`` are explicit trusted
    overrides.  Missing values are recovered only from the typed identity
    facts captured in the L0 header; they are never inferred from ``doc_name``,
    paths, or local ElementId values. With complete context, each row still
    needs its Revit ``unique_id``; otherwise the node remains readable through
    ``node_id`` but is identity-incomplete and the graph cannot claim authority.

    `generator_child_ids` is the ONLY input by which a node receives
    `DERIVED_BY_REVIT`, and it is EXPLICIT. A category table is not supplied here and
    cannot be: a prior does not know who creates the element, and it was exactly this that
    the withdrawn claim about 14 713 fittings was built on.
    """
    header = _as_mapping(header, "header")
    try:
        identity_context = identity_context_from_l0(
            header,
            document_identity=document_identity,
            federation_context=federation_context,
        )
    except IdentityError as exc:
        raise GraphBuildError(f"invalid federated identity context: {exc}") from exc
    document_identity = identity_context.document_identity
    federation_context = identity_context.federation_context
    doc_name = str(header.get("doc_name") or "")
    derived = set(generator_child_ids)

    if (isinstance(unreadable_rows, bool)
            or not isinstance(unreadable_rows, int) or unreadable_rows < 0):
        raise GraphBuildError(
            "graph_from_l0(unreadable_rows=) must be a non-negative int")
    # An unread row ENTERS `rows_seen` and immediately the refusals too: it was in the
    # snapshot, so the census must see it, and it did not become a node, so it
    # must have a named reason. The law's equality is not violated by this —
    # the addition goes into BOTH of its sides.
    rows = unreadable_rows
    refusals: Counter[str] = Counter()
    if unreadable_rows:
        refusals[NodeRefusal.ROW_UNREADABLE.value] = unreadable_rows
    identity_authoritative_nodes = 0
    identity_incomplete_nodes = 0
    identity_gaps: Counter[str] = Counter()
    nodes: dict[str, GraphNode] = {}
    raw: dict[str, Mapping[str, Any]] = {}

    for element in elements:
        rows += 1
        element = _as_mapping(element, "element row")
        node_id = element.get("element_id")
        if not isinstance(node_id, str) or not node_id:
            refusals[NodeRefusal.NO_ADDRESS.value] += 1
            continue
        if node_id in nodes:
            refusals[NodeRefusal.DUPLICATE_ADDRESS.value] += 1
            continue
        try:
            identity = resolve_element_identity(
                element_unique_id=element.get("unique_id"),
                document_identity=document_identity,
                federation_context=federation_context,
                context_gaps=identity_context.gaps,
            )
        except IdentityError as exc:
            raise GraphBuildError(f"invalid federated identity context: {exc}") from exc
        is_derived = node_id in derived
        nodes[node_id] = GraphNode(
            node_id=node_id,
            category=str(element.get("category") or "no_category"),
            authority=(Authority.DERIVED_BY_REVIT if is_derived
                       else Authority.DECLARED),
            authority_source=(AuthoritySource.LIFTER_GENERATOR_CHILD if is_derived
                              else AuthoritySource.L0_ELEMENT),
            # An L0 row was read from the document: the node EXISTS.
            existence=Existence.MATERIALIZED,
            level_id=element.get("level_id"),
            type_id=element.get("type_id"),
            type_name=element.get("type_name"),
            host_source=element.get("host_source"),
            section=_section_of(element),
            definition_identity=identity.definition,
            occurrence_identity=identity.occurrence,
            identity_status=identity.status,
            identity_gaps=identity.gaps,
        )
        if identity.authoritative:
            identity_authoritative_nodes += 1
        else:
            identity_incomplete_nodes += 1
            identity_gaps.update(gap.value for gap in identity.gaps)
        raw[node_id] = element

    # SOURCES THAT WERE NOT SUPPLIED ARE NAMED HERE. `joins=None` and an empty
    # `link_ids` extinguish a whole edge kind, and without this record their zero reads as a
    # fact about the building — see `OPTIONAL_SOURCES` and `GraphCensus.sources_absent`.
    #
    # 🔴 THE SETS ARE BUILT BEFORE THE CHECK, NOT AFTER. `link_ids` is declared
    # `Iterable`, and a generator is TRUTHY even when empty: a "not supplied" check on the
    # raw argument would answer "supplied" for an empty generator — a zero of the very quantity
    # the instrument did not count, in an instrument written against this very form.
    # 🔴 AN IDENTITY CHECK, NOT A TRUTHINESS CHECK (F-056). The earlier guard against an empty
    # generator IS PRESERVED and strengthened: `is not _NOT_GIVEN` does not touch
    # the iterator at all, whereas `frozenset(...)` exhausted it before the check.
    #
    # `joins` needs no sentinel: `Mapping | None` already carries the three-valuedness
    # BY TYPE, and `is not None` is an exact check. Setting up a second carrier
    # for one law where the first suffices would double it.
    #
    # `room_adjacency` IS NOT TOUCHED, and this is a decision, not an oversight: it is not
    # a source but a QUERY. `False` means "adjacency was not computed", that is,
    # the absence of measurement AS SUCH; applying the same rule to it would mean
    # declaring the unmeasured measured — trading one emptiness for another.
    link_ids_given = link_ids is not _NOT_GIVEN
    links = frozenset(link_ids if link_ids_given else ())
    bodiless = frozenset(bodiless_target_ids)
    absent_sources = tuple(
        name for name, given in (("joins", joins is not None),
                                 ("link_ids", link_ids_given),
                                 ("room_adjacency", room_adjacency))
        if not given)

    # PREDICATE B IS COMPUTED BEFORE THE CENSUS, BECAUSE IT IS PART OF IT (RV-03).
    # It used to stand lower, among the edge assembly, and its census went into
    # a `_` variable: see `GraphCensus.adjacency`. The edges are still added
    # in the same place and the same order — only the COMPUTATION has moved.
    adjacency_edges: tuple[GraphEdge, ...] = ()
    adjacency_row: Mapping[str, Any] | None = None
    if room_adjacency:
        from kir.decompile.graph_adjacency import (
            opening_point_touches_room_edges)

        adjacency_edges, adjacency_census = opening_point_touches_room_edges(
            header, raw, known_node_ids=nodes.keys())
        adjacency_row = adjacency_census.as_census_row()

    census = GraphCensus(rows_seen=rows, nodes=len(nodes),
                         refusals=dict(refusals),
                         identity_authoritative_nodes=(
                             identity_authoritative_nodes),
                         identity_incomplete_nodes=identity_incomplete_nodes,
                         identity_gaps=dict(identity_gaps),
                         identity_context_authoritative=(
                             document_identity is not None
                             and federation_context is not None),
                         sources_absent=absent_sources,
                         adjacency=adjacency_row)

    edges: list[GraphEdge] = []
    edges.extend(_host_edges(nodes, raw, links, bodiless, host_classes or {}))
    edges.extend(_level_edges(header, nodes, raw))
    edges.extend(_top_constraint_edges(nodes, raw))
    edges.extend(_room_boundary_edges(header, nodes, links))
    edges.extend(_bounded_by_same_wall_edges(header, nodes, raw))
    # Joins arrive EXPLICITLY from a side index: L0 does not carry them, and there is nothing
    # to derive them from in an element row. `None` means "the index was not supplied" —
    # an absence of KNOWLEDGE, not a negative fact about the building.
    if joins:
        edges.extend(_join_edges(nodes, joins))
    # PREDICATE B IS FROM THIS SAME L0, AND BEFORE 22.08.2026 NO ONE CALLED IT.
    #
    # 🔴 THE ANALYSIS OF WHY THIS IS A WIRE, NOT A NOTE "PREDICATE B IS NOT NEEDED BY THE GRAPH".
    # There was a temptation to cancel the item: the `graph_adjacency` header proves by measurement
    # that A and B are TWO DIFFERENT QUESTIONS (the Jaccard ranges 0.287…0.649, diverging
    # in both directions on every building). But that is exactly the argument FOR the wire:
    # if B were a coarsening of A, its absence would cost nothing. It is
    # not that — and exactly those 2 309 `демо-v3` pairs that ONLY B sees
    # silently fell out of the graph, even though the kind `OPENING_POINT_TOUCHES_ROOM`
    # is declared in this file's `Relation`.
    #
    # The shape of the defect is named precisely: the relation is DECLARED by the core, IS BUILT
    # outside it, and is NEVER produced by the core. So "no one calls the module" and "the kind
    # does not exist in the building" become one zero.
    #
    # WHY OPT-IN, NOT ALWAYS: the cost. The predicate pulls in `shapely` and builds
    # an `STRtree` for every level; it is the only piece of the graph that
    # needs geometry, and the only one with an external dependency.
    # The absence of the computation is therefore NAMED (`sources_absent`), rather than silent.
    edges.extend(adjacency_edges)

    return BuildingGraph(
        doc_name=doc_name,
        nodes=nodes.values(), edges=edges, census=census,
        observation=observation,
        document_identity=document_identity,
        federation_context=federation_context,
    )


#: Host classes, each with its OWN answer. The keys are `host_class` values from
#: `family_placement.index.json`, taken by READING, not derived from category.
#:
#: WHY NOT A CATEGORY TABLE (the 11.08.2026 measurement, which cancels the plan to place
#: this fact on `CategorySpec` next to `discipline`):
#:
#:   * ⛔ THE FIRST ARGUMENT WAS CANCELED ON 22.08.2026, AND CANCELED BY MEASUREMENT. It read:
#:     "`ReferencePlane` is not a category but a Revit class; the extractor's table has
#:     77 rows, and neither `OST_CLines` nor `OST_ReferencePlanes` is among them —
#:     reference planes are not extracted AT ALL." The first half is still true
#:     today (a class, not a category), the second has DIED: on that day the table
#:     received the row `CategorySpec("OST_CLines", ".OfClass(typeof(
#:     ReferencePlane))")`, and planes became extractable — 9 724 of them across
#:     ten of ten corpus buildings. The argument was not a mistake; it EXPIRED,
#:     and expired silently, exactly like the window brands on 29.07. Keeping it further
#:     would mean explaining correct code with an incorrect reason.
#:   * ✅ THE SECOND ARGUMENT HOLDS, AND IT IS LOAD-BEARING: for a DANGLING host the category
#:     is unknown IN PRINCIPLE — there is NO row with that address in the snapshot. Any
#:     table keyed by category answers a question we cannot
#:     ask. Taking planes does not change this and cannot: a
#:     target lying in a linked file, or not read by this pass,
#:     remains without a category no matter how complete the table is.
#:   * But the answer ALREADY LIES ON DISK, per element: `host_class` in the side
#:     placement index. Measurement: `snowdon_plumb_v5` — `Wall` 2 647,
#:     `Ceiling` 100, `ReferencePlane` **86**, `Level` 25, `FamilyInstance` 2
#:     (those exact 86 dangling ones, named by name); `sob62_r23_v5` —
#:     `RevitLinkInstance` **1** (that same sole dangling one).
#:
#: The `fold._discipline` precedent is HONORED here, not violated: it forbids
#: A SECOND dictionary about one concept. Here no second one is set up at all — what is read
#: is what the reading already recorded.
_HOST_CLASS_LINK = "RevitLinkInstance"
_HOST_CLASS_BODILESS: frozenset[str] = frozenset({"ReferencePlane"})


def _why_unresolved(
    node_id: str,
    host: str,
    bodiless_ids: frozenset[str],
    host_classes: Mapping[str, str],
) -> str:
    """The sub-reason for an unresolved target — by the MEASURED class, if it exists."""
    measured = host_classes.get(node_id)
    if measured == _HOST_CLASS_LINK:
        return OutsideExtraction.RESOLVED_TO_LINK.value
    if measured in _HOST_CLASS_BODILESS:
        return OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value
    if host in bodiless_ids:
        return OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value
    return OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value


def _host_edges(
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
    link_ids: frozenset[str] = frozenset(),
    bodiless_ids: frozenset[str] = frozenset(),
    host_classes: Mapping[str, str] = {},
) -> Iterator[GraphEdge]:
    """`hosted_in` / `placed_on_datum` with THREE outcomes, not two.

    The third outcome — `UNRESOLVED_TARGET`: the element DECLARED a host, and the host is
    not in this extraction. Measurement: `snowdon_elec_v1` — 959 of 1 001 (95.8 %),
    four Snowdon Plumbing snapshots — 100 %. The host lies in a linked file.
    An edge with an unresolved target REMAINS in the graph precisely because it is
    the sole signal that makes the cross-partition region non-empty: erasing it
    would make "we did not read the link" indistinguishable from "there is no link".
    """
    for node_id in sorted(nodes):
        host = raw[node_id].get("host_id")
        if not isinstance(host, str) or not host:
            continue
        if host in link_ids:
            # A LINK is a positive fact, not our blindness. The 959 edges of
            # `snowdon_elec_v1` live exactly here.
            yield GraphEdge(
                relation=Relation.HOSTED_IN_LINK, src=node_id, dst=host,
                modality=Modality.PROVEN,
                evidence={"source": "L0Element.host_id",
                          "resolved_by": "L0 link record",
                          "why": OutsideExtraction.RESOLVED_TO_LINK.value},
            )
            continue
        host_node = nodes.get(host)
        if host_node is None:
            yield GraphEdge(
                relation=Relation.HOSTED_IN, src=node_id, dst=host,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "L0Element.host_id",
                          "host_class": host_classes.get(node_id),
                          "why": _why_unresolved(node_id, host, bodiless_ids,
                                                 host_classes)},
            )
            continue
        relation = (Relation.PLACED_ON_DATUM
                    if host_node.category in _DATUM_CATEGORIES
                    else Relation.HOSTED_IN)
        yield GraphEdge(
            relation=relation, src=node_id, dst=host,
            modality=Modality.PROVEN,
            evidence={"source": "L0Element.host_id",
                      "host_category": host_node.category,
                      # None = "not measured"; across the corpus — everywhere. We do not stay silent.
                      "host_source": raw[node_id].get("host_source")},
        )


def _level_edges(
    header: Mapping[str, Any],
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
) -> Iterator[GraphEdge]:
    """`on_level` + `level_above`.

    `resolve._level_band` derives both relations anew on EVERY call — it pulls
    the elevations from the L0 header and finds the next level by sorting. Here these are
    edges, not a traversal.
    """
    for node_id in sorted(nodes):
        level = nodes[node_id].level_id
        if not isinstance(level, str) or not level:
            continue
        if level in nodes:
            yield GraphEdge(
                relation=Relation.ON_LEVEL, src=node_id, dst=level,
                modality=Modality.PROVEN,
                evidence={"source": "L0Element.level_id"})
        else:
            yield GraphEdge(
                relation=Relation.ON_LEVEL, src=node_id, dst=level,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "L0Element.level_id",
                          "why": OutsideExtraction.LEVEL_NOT_IN_SNAPSHOT.value})

    levels = [lvl for lvl in (header.get("levels") or [])
              if isinstance(lvl, Mapping)]
    ordered = sorted(
        ((str(lvl.get("id") or ""), lvl.get("elevation_mm")) for lvl in levels),
        key=lambda pair: (pair[1] is None, pair[1] if pair[1] is not None else 0.0,
                          pair[0]))
    usable = [(lid, elev) for lid, elev in ordered if lid and elev is not None]
    for (lower, low_z), (upper, high_z) in zip(usable, usable[1:]):
        # 🔴 A HEADER LEVEL IS NOT NECESSARILY A NODE. On a truncated read
        # the header carries all 59 of the document's levels, and the stream carries none
        # (`k2_ar_rd_v1`, the 22.08 measurement). An edge with BOTH ends external has
        # nothing to be addressed by: a graph is a graph OVER ITS OWN NODES, and `BuildingGraph`
        # rejects such an edge outright. No fact is lost by this silence:
        # the absence of the levels themselves among the nodes is directly visible, and every element
        # that referenced a missing level has already given up its own `on_level` with
        # `LEVEL_NOT_IN_SNAPSHOT` earlier in this same function.
        if upper not in nodes and lower not in nodes:
            continue
        if upper not in nodes or lower not in nodes:
            local, outside = ((lower, upper) if lower in nodes
                              else (upper, lower))
            yield GraphEdge(
                relation=Relation.LEVEL_ABOVE, src=local, dst=outside,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={
                    "source": "header.levels.elevation_mm",
                    "delta_mm": float(high_z) - float(low_z),
                    "why": OutsideExtraction.LEVEL_NOT_IN_SNAPSHOT.value,
                    # The relation's direction is lost when the external one turns out to be
                    # the UPPER level: `src` must be the local end.
                    # Which of the pair is higher is said by this line, not by order.
                    "upper": upper,
                })
            continue
        yield GraphEdge(
            relation=Relation.LEVEL_ABOVE, src=upper, dst=lower,
            modality=Modality.PROVEN,
            evidence={"source": "header.levels.elevation_mm",
                      "delta_mm": float(high_z) - float(low_z)})


#: The wall's TOP-CONSTRAINT parameter («Зависимость сверху»). The value is a LEVEL
#: ADDRESS as a string, not a number: the MNVNK measurement — 7 007 of 7 007 values
#: resolve to an `OST_Levels` node.
_TOP_CONSTRAINT_PARAM = "WALL_HEIGHT_TYPE"

#: The category of the top-constraint target. NOT `_DATUM_CATEGORIES`: grids (`OST_Grids`)
#: never hold a wall's top, and accepting them would mean extending the relation
#: with a guess.
_LEVEL_CATEGORY = "OST_Levels"

#: 🔴 WITNESSES THAT THE WALL'S PARAMETER BLOCK WAS READ AT ALL. Without them
#: "the top is set by a number" and "we did not ask" would arrive as one value —
#: a missing key.
#:
#: THE MNVNK MEASUREMENT OF 22.08.2026 (10 646 walls), which splits the remainder IN TWO:
#:
#:     `WALL_HEIGHT_TYPE` present                    7 007  (65.8 %)
#:     absent, but the wall block WAS READ             838  -> top by number
#:     absent, and NOT A SINGLE `WALL_*` key in the row 2 801  -> NOT ASKED
#:
#: The third row is not a property of the building. For these 2 801 rows the parameters are
#: entirely different (`FLOOR_HEIGHTABOVELEVEL_PARAM`, `INSTANCE_SILL_HEIGHT_PARAM`,
#: `SLANTED_COLUMN_TYPE_PARAM`), meaning the reading mask never reached the wall block.
#: Calling them "top not constrained" would mean passing OUR blindness off as
#: a fact about the building — exactly what this whole module is written against.
_WALL_BLOCK_WITNESSES: tuple[str, ...] = (
    "WALL_USER_HEIGHT_PARAM",
    "WALL_TOP_OFFSET",
    "WALL_TOP_IS_ATTACHED",
    "WALL_BOTTOM_IS_ATTACHED",
    "WALL_BASE_OFFSET",
    "WALL_KEY_REF_PARAM",
)

#: The rule that removes the top-constraint edge: the wall's top is set by a NUMBER
#: («Unconnected Height»), not by a level. The name travels in the edge, the edge remains.
REFUTED_TOP_IS_UNCONNECTED_HEIGHT = "top_is_unconnected_height"

#: The rule that removes the edge when the constraint's target was read but is not
#: a level. This has NOT BEEN OBSERVED across the corpus; the rule exists because
#: the law holds by verification, not by the corpus's luck.
REFUTED_TOP_CONSTRAINT_IS_NOT_A_LEVEL = "top_constraint_target_is_not_a_level"


def _top_constraint_edges(
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
) -> Iterator[GraphEdge]:
    """`top_constrained_to_level` — THE WALL'S TOP FOLLOWS A LEVEL.

    The most massive relation of a real building that was missing from the graph:
    65.8 % of MNVNK's walls are held by exactly this. Before this wave it traveled as a NUMBER in
    `params`, and there was nothing to ask the graph "what shifts if this level is raised" with —
    even though `ON_LEVEL` (the base) was already a relation.

    FOUR OUTCOMES, AND EACH IS NAMED:

        target is a snapshot level        `PROVEN`
        target read, but not a level      `REFUTED` + a rule
        target absent from the snapshot   `UNRESOLVED_TARGET` + `why`
        no parameter, block WAS READ      `REFUTED` + `top_is_unconnected_height`
        no parameter, block NOT READ      `POSSIBLE` — a self-loop on the wall itself

    🔴 THE LAST OUTCOME IS A SELF-LOOP, AND IT IS DELIBERATE. An edge without a second end
    cannot be invented: which level the top would belong to — the snapshot DOES NOT SAY.
    Staying silent is also not allowed: 2 801 MNVNK walls would leave the graph without a single trace,
    and a reader subtracting 7 007 from 10 646 would get "3 639 walls have no top-to-level
    constraint" — a statement FALSE for 2 801 of them. The self-loop with
    `Modality.POSSIBLE` says exactly what is true: the relation is ALLOWED by the data
    and not decided by it either. A precedent for a self-loop already stands in this house —
    `graph_adjacency` produces one for an opening that touched no room at all.
    """
    for node_id in sorted(nodes):
        if nodes[node_id].category != "OST_Walls":
            continue
        params = raw[node_id].get("params")
        if not isinstance(params, Mapping):
            params = {}
        target = params.get(_TOP_CONSTRAINT_PARAM)
        if isinstance(target, str) and target:
            target_node = nodes.get(target)
            if target_node is None:
                yield GraphEdge(
                    relation=Relation.TOP_CONSTRAINED_TO_LEVEL,
                    src=node_id, dst=target,
                    modality=Modality.UNRESOLVED_TARGET,
                    evidence={
                        "source": f"params.{_TOP_CONSTRAINT_PARAM}",
                        "why": OutsideExtraction.LEVEL_NOT_IN_SNAPSHOT.value})
                continue
            if target_node.category != _LEVEL_CATEGORY:
                yield GraphEdge(
                    relation=Relation.TOP_CONSTRAINED_TO_LEVEL,
                    src=node_id, dst=target, modality=Modality.REFUTED,
                    refuted_by=REFUTED_TOP_CONSTRAINT_IS_NOT_A_LEVEL,
                    evidence={"source": f"params.{_TOP_CONSTRAINT_PARAM}",
                              "target_category": target_node.category})
                continue
            yield GraphEdge(
                relation=Relation.TOP_CONSTRAINED_TO_LEVEL,
                src=node_id, dst=target, modality=Modality.PROVEN,
                evidence={
                    "source": f"params.{_TOP_CONSTRAINT_PARAM}",
                    # THE BASE AND THE TOP RARELY COINCIDE: 292 walls of 7 007 (4.2 %).
                    # This line stands here so that `ON_LEVEL` and this relation
                    # cannot be mistaken for one fact.
                    "same_as_base_level": target == nodes[node_id].level_id,
                    "top_offset_mm": params.get("WALL_TOP_OFFSET")})
            continue
        if target is not None:
            # The parameter exists, but is not an address string. There is nothing to read,
            # nothing to guess from — and this is NOT the same as "the parameter is absent".
            yield GraphEdge(
                relation=Relation.TOP_CONSTRAINED_TO_LEVEL,
                src=node_id, dst=node_id, modality=Modality.POSSIBLE,
                evidence={"source": f"params.{_TOP_CONSTRAINT_PARAM}",
                          "why": "top_constraint_is_not_an_address",
                          "read_as": type(target).__name__})
            continue
        if not any(name in params for name in _WALL_BLOCK_WITNESSES):
            if not params:
                # 🔴 AN EMPTY `params` IS NOT THE SAME AS A MASK WITHOUT A WALL BLOCK, and
                # the difference here decides whether there is an edge at all.
                #
                # The `POSSIBLE` edge below asserts a narrow, verifiable thing:
                # the row's parameters WERE READ, and the wall block is not among them —
                # that is, the reading mask never reached it. A row WITHOUT A SINGLE
                # parameter has no such witness at all: to say "possible"
                # about it is to say it about any row in existence.
                #
                # THE 22.08.2026 MEASUREMENT ACROSS THE WHOLE CORPUS (297 076 walls in 76
                # parses) — the branch subtracts NOTHING from what was measured:
                #     constraint present                        209 406
                #     block read, no constraint                  84 585
                #     params NON-EMPTY, no wall block              3 085
                #     params EMPTY OUTRIGHT                           0
                # The zero in the last row is exactly the argument: the distinction is free
                # on real data and mandatory on degenerate data.
                continue
            yield GraphEdge(
                relation=Relation.TOP_CONSTRAINED_TO_LEVEL,
                src=node_id, dst=node_id, modality=Modality.POSSIBLE,
                evidence={"source": f"params.{_TOP_CONSTRAINT_PARAM}",
                          "why": "wall_parameter_block_not_read",
                          "params_seen": len(params)})
            continue
        base = nodes[node_id].level_id
        # The top is set by a NUMBER. Exactly the relation it would have had with
        # the BASE level is refuted: "this top does NOT follow this level".
        # There is no base in the snapshot — the edge becomes a self-loop, so as not to invent
        # a second end.
        dst = base if isinstance(base, str) and base in nodes else node_id
        yield GraphEdge(
            relation=Relation.TOP_CONSTRAINED_TO_LEVEL,
            src=node_id, dst=dst, modality=Modality.REFUTED,
            refuted_by=REFUTED_TOP_IS_UNCONNECTED_HEIGHT,
            evidence={"source": f"params.{_TOP_CONSTRAINT_PARAM}",
                      "unconnected_height_mm": params.get(
                          "WALL_USER_HEIGHT_PARAM"),
                      "base_level": base if dst != node_id else None})


def _room_boundary_edges(
    header: Mapping[str, Any],
    nodes: Mapping[str, GraphNode],
    link_ids: frozenset[str] = frozenset(),
) -> Iterator[GraphEdge]:
    """`bounds_room` — the raw material of both adjacency predicates, named separately."""
    for room in (header.get("rooms") or []):
        if not isinstance(room, Mapping):
            continue
        room_id = room.get("id")
        if not isinstance(room_id, str) or not room_id:
            continue
        # 🔴 A HEADER ROOM IS ALSO NOT NECESSARILY A NODE, and before 22.08.2026
        # this was not checked AT ALL: the `room_id` side went into the edge as a given.
        # The cost is measured — five corpus parses did not assemble into a graph at all;
        # parsed in `OutsideExtraction.ROOM_NOT_IN_SNAPSHOT`.
        room_local = room_id in nodes
        for element_id in (room.get("bounding_element_ids") or []):
            if not isinstance(element_id, str) or not element_id:
                continue
            if element_id in nodes and room_local:
                yield GraphEdge(
                    relation=Relation.BOUNDS_ROOM, src=element_id, dst=room_id,
                    modality=Modality.PROVEN,
                    evidence={"source": "RoomInfo.bounding_element_ids"})
                continue
            if not room_local:
                if element_id not in nodes:
                    # BOTH ends are external — there is nothing to address the edge by. The fact is
                    # not lost: the room's absence among the nodes is directly visible.
                    continue
                yield GraphEdge(
                    relation=Relation.BOUNDS_ROOM, src=element_id, dst=room_id,
                    modality=Modality.UNRESOLVED_TARGET,
                    evidence={"source": "RoomInfo.bounding_element_ids",
                              "why": (OutsideExtraction
                                      .ROOM_NOT_IN_SNAPSHOT.value)})
                continue
            # The sub-reason is MANDATORY, and here it is DIFFERENT from the host's:
            # the populations are measurably disjoint (target intersection 0 of 2 146
            # on `демо-v3`). A link is named separately — on `sob62_r23_v5`
            # one `link` record carries 88 boundary edges.
            why = (OutsideExtraction.RESOLVED_TO_LINK if element_id in link_ids
                   else OutsideExtraction.BOUNDARY_ELEMENT_NOT_EXTRACTED)
            yield GraphEdge(
                relation=Relation.BOUNDS_ROOM, src=element_id, dst=room_id,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={"source": "RoomInfo.bounding_element_ids",
                          "why": why.value})


#: The rule that removes predicate A's edge. The name TRAVELS IN THE EDGE, and the edge remains.
REFUTED_HOST_NOT_BETWEEN_TWO_ROOMS = "host_does_not_separate_exactly_two_rooms"


def _bounded_by_same_wall_edges(
    header: Mapping[str, Any],
    nodes: Mapping[str, GraphNode],
    raw: Mapping[str, Mapping[str, Any]],
) -> Iterator[GraphEdge]:
    """PREDICATE A — `bounded_by_same_wall` (what `fold._semantic_fold` builds).

    An edge between two rooms bounded by ONE opening host. This is a fact
    about Revit's DECLARATION (the room boundary calculation), not about the door's geometry.

    WHAT IS FIXED HERE AGAINST `fold`. `fold` requires `len(adjacent) == 2` and on
    any other number SILENTLY does not create an edge. The 10.08 measurement, by the number of rooms
    bounded by a door's host:

        `демо-v3`      (5 941 doors): 0→2816, 1→154, 2→1036, 3→966, 4→648,
                       5→50, 6→76, 7→25, 8→55, 9→113, 30→1, 34→1
        `k2_ar_rd_v7`  (2 096 doors): 0→66, 1→449, 2→1054, 3→326, 4→125, …
        `sob62_r23_v5` (153 doors):    0→15, 1→79, 2→47, 3→12

    That is, on `демо-v3` an edge is obtained by 1 036 doors out of 5 941 — **17.4 %**, while
    4 905 doors drop out WITHOUT A NAMED REASON. The predicate is called "room
    adjacency", but means "the host separates EXACTLY two rooms". Here a door whose
    host bounds not two rooms yields an edge with `Modality.REFUTED` and
    a rule name: "did not look" becomes distinguishable from "did not find".
    """
    boundary_to_rooms: dict[str, set[str]] = defaultdict(set)
    for room in (header.get("rooms") or []):
        if not isinstance(room, Mapping):
            continue
        room_id = room.get("id")
        if not isinstance(room_id, str) or not room_id:
            continue
        for element_id in (room.get("bounding_element_ids") or []):
            if isinstance(element_id, str) and element_id:
                boundary_to_rooms[element_id].add(room_id)

    seen: set[tuple[str, str]] = set()
    for node_id in sorted(nodes):
        if nodes[node_id].category != "OST_Doors":
            continue
        host = raw[node_id].get("host_id")
        if not isinstance(host, str) or not host:
            continue
        if host not in nodes:
            # The room predicate was not evaluated: its host lives beyond this
            # local graph.  Calling this REFUTED would turn extraction blindness
            # into a negative fact about the building.
            yield GraphEdge(
                relation=Relation.BOUNDED_BY_SAME_WALL,
                src=node_id, dst=host,
                modality=Modality.UNRESOLVED_TARGET,
                evidence={
                    "source": "fold._semantic_fold predicate",
                    "why": OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value,
                    "predicate_status": "host_outside_local_graph",
                })
            continue
        adjacent = sorted(boundary_to_rooms.get(host, ()))
        if len(adjacent) == 2:
            pair = (adjacent[0], adjacent[1])
            if pair in seen:
                continue
            seen.add(pair)
            # 🔴 THE PREDICATE RESOLVED, BUT THE ROOMS ARE NOT IN THE STREAM. The edge runs between
            # TWO rooms, and before 22.08.2026 no one checked them as nodes:
            # on `k2_ar_rd_v1` there are 210 such edges, and each had TWO external
            # ends. There is exactly one local end here, and it is always present — the
            # opening itself; the edge is addressed by it, and both rooms travel in the evidence.
            outside = [room for room in pair if room not in nodes]
            if outside:
                yield GraphEdge(
                    relation=Relation.BOUNDED_BY_SAME_WALL,
                    src=node_id, dst=outside[0],
                    modality=Modality.UNRESOLVED_TARGET,
                    evidence={"source": "fold._semantic_fold predicate",
                              "why": (OutsideExtraction
                                      .ROOM_NOT_IN_SNAPSHOT.value),
                              "via_host": host, "room_ids": list(pair),
                              "rooms_outside_snapshot": outside})
                continue
            yield GraphEdge(
                relation=Relation.BOUNDED_BY_SAME_WALL,
                src=pair[0], dst=pair[1], modality=Modality.PROVEN,
                evidence={"source": "fold._semantic_fold predicate",
                          "via_host": host, "opening": node_id})
            continue
        # A NAMED refutation instead of a silent drop.
        yield GraphEdge(
            relation=Relation.BOUNDED_BY_SAME_WALL,
            src=node_id, dst=host, modality=Modality.REFUTED,
            refuted_by=REFUTED_HOST_NOT_BETWEEN_TWO_ROOMS,
            evidence={"source": "fold._semantic_fold predicate",
                      "rooms_bounded_by_host": len(adjacent),
                      "room_ids": adjacent[:8]})


#: The join evidence. ONE literal for the whole module — but 🔴 IT DOES NOT BECOME
#: A SHARED OBJECT, and this is MEASURED, not assumed.
#:
#: I wrote this object for the sake of economy and verified that economy by execution. There
#: IS NO economy: `GraphEdge.__post_init__` runs the evidence through `_freeze_json`, which
#: builds a NEW `MappingProxyType` on every edge. A control — 100 edges with
#: the same evidence yield **100 distinct objects** (`id(e.evidence)`). The freeze
#: boundary is right: it must detach from the caller's live dictionary,
#: otherwise the delivered proof could be changed after the fact. So the device
#: is called off, rather than remaining decoration with a false
#: signature.
#:
#: SO WHAT DOES ANSWER "lightweight" — numbers taken on `k2_ar_rd_v8`
#: (18 071 joinable elements, `L0.jsonl` 84.3 MB):
#:
#:     empty evidence      283 B per edge    4.88 MB
#:     2-key evidence      403 B per edge    6.95 MB   <- here
#:     4-key evidence      403 B per edge    6.95 MB
#:
#: That is, the cost of provenance is 120 B per edge, 2.1 MB per building, and it does NOT GROW
#: with the number of keys (strings are interned). Against an 84.3 MB parse that is 8 %, and
#: paying it is worth it: `joined_to` without a named source would become
#: the only relation in this enumeration that has no witness.
#: The lightness comes not from economizing on the evidence but from its FORM: the kind is distinguished by one
#: enum value, the addresses are integers, and `GraphEdge.key` collapses the pair.
JOIN_EVIDENCE: Mapping[str, Any] = MappingProxyType({
    "source": "JoinGeometryUtils.GetJoinedElements",
    "stage": "join_extract",
})

#: The evidence of an edge whose TARGET is outside the local graph. Also one for all.
JOIN_EVIDENCE_OUTSIDE: Mapping[str, Any] = MappingProxyType({
    "source": "JoinGeometryUtils.GetJoinedElements",
    "stage": "join_extract",
    "why": OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value,
})


def _end_join_edges(
    nodes: Mapping[str, GraphNode],
    joins: Mapping[str, Any],
) -> Iterator[GraphEdge]:
    """`joined_at_end` edges — JOINED AT THE END, with END NUMBERS in the evidence.

    A DIRECTED edge: `src` is the wall whose end this is. The reverse fact ("at its
    end I stand") arrives as its own edge with its own number, and this is not a duplicate, but
    the other half of the same joint, said from the other side.

    AN UNREAD EDGE END YIELDS NOTHING AT ALL, and this is deliberate: an edge means
    "a joint exists", and we do not know that. The refusal lives in the record (`EndJoin.why`)
    and is enumerated by `JoinExtraction.end_join_refusals()`; inventing an edge with a modality
    for it would mean setting up an edge without a second end.

    🔴 ONE PAIR — ONE EDGE, AND THIS WAS BOUGHT BY A REFUSAL ON A REAL BUILDING
    (22.08.2026, MNVNK, the graph's first run against a production model).
    The earlier edition gave ONE EDGE PER END, and the comment next to it assured
    that the end number in the evidence distinguishes the joint's sides. The edge's key does not carry it
    (`GraphEdge.key` is the triple `relation/src/dst`), so a pair of walls
    joined at BOTH their ends produced two edges with one key, and
    `BuildingGraph` refused outright: «duplicate relation/src/dst edge truth
    is forbidden». The building did not assemble into a graph AT ALL because of two pairs.

    Why this was not caught: a corpus-wide measurement — 2 of 5 parses carry such
    a pair (MNVNK 2 pairs out of 6 629 end edges, bench_A 4), while the largest
    index, `k2v33_join2` (17 982 records), is clean. The only run the module
    references (`graph_clash_query.py:807`) went over the clean one.

    The end numbers remain in the evidence, in the `ends` field — a sorted set.
    "Joined at one end" and "joined at both" are different facts about the building, and
    collapsing them into one edge loses neither of them.
    """
    for node_id in sorted(joins):
        if node_id not in nodes:
            continue
        row = joins[node_id]
        ends = (row.get("elements_at_end_join") if isinstance(row, Mapping)
                else getattr(row, "elements_at_end_join", None))
        at_ends: dict[str, list[int]] = {}
        for end_index, end in enumerate(ends or ()):
            read = (end.get("read") if isinstance(end, Mapping)
                    else getattr(end, "read", False))
            if not read:
                continue
            members = (end.get("elements") if isinstance(end, Mapping)
                       else getattr(end, "elements", ()))
            for other in (members or ()):
                if not isinstance(other, str) or not other or other == node_id:
                    continue
                bucket = at_ends.setdefault(other, [])
                if end_index not in bucket:
                    bucket.append(end_index)
        for other in sorted(at_ends):
            evidence = {
                "source": "LocationCurve.get_ElementsAtJoin",
                "stage": "join_extract",
                "ends": tuple(sorted(at_ends[other])),
            }
            if other in nodes:
                yield GraphEdge(
                    relation=Relation.JOINED_AT_END,
                    src=node_id, dst=other, modality=Modality.PROVEN,
                    evidence=evidence)
            else:
                yield GraphEdge(
                    relation=Relation.JOINED_AT_END,
                    src=node_id, dst=other,
                    modality=Modality.UNRESOLVED_TARGET,
                    evidence={**evidence,
                              "why": (OutsideExtraction
                                      .TARGET_NOT_IN_SNAPSHOT.value)})


def _join_edges(
    nodes: Mapping[str, GraphNode],
    joins: Mapping[str, Any],
) -> Iterator[GraphEdge]:
    """`joined_to` edges from the SIDE JOIN INDEX (`join_extract`).

    The index is supplied EXPLICITLY, exactly like `generator_child_ids` and
    `bodiless_target_ids`: L0 does not carry joins, and there is nothing to derive them from
    in an element row. A graph that assigned this relation on its own — by
    category, by bounding-box touch, or by end coincidence — would return a
    guess, and guesses are exactly what we are moving away from. No index — no edges, and this
    is an absence of KNOWLEDGE, not a negative fact about the building.

    A TARGET OUTSIDE THE GRAPH IS `UNRESOLVED_TARGET`, not `REFUTED`. The relation is declared
    by the document and there is nothing to verify it with: exactly the case for which
    the modality was set up (959 of 1 001 `host_id` values in `snowdon_elec_v1`).
    Calling this a refutation would mean turning the boundary of OUR coverage into
    a statement about the building.
    """
    yield from _end_join_edges(nodes, joins)
    seen: set[tuple[str, str]] = set()
    for node_id in sorted(joins):
        row = joins[node_id]
        others = (row.get("joined_to") if isinstance(row, Mapping)
                  else getattr(row, "joined_to", ()))
        if node_id not in nodes:
            # The index speaks of something that is not in the graph at all. Silence here
            # would be a loss: the row EXISTS, and the node does not — this is a discrepancy between two
            # sources, and it must be visible, not discarded.
            continue
        for other in (others or ()):
            if not isinstance(other, str) or not other or other == node_id:
                continue
            pair = tuple(sorted((node_id, other)))
            if pair in seen:
                continue
            seen.add(pair)
            if other in nodes:
                yield GraphEdge(
                    relation=Relation.JOINED_TO,
                    src=node_id, dst=other, modality=Modality.PROVEN,
                    evidence=JOIN_EVIDENCE)
            else:
                yield GraphEdge(
                    relation=Relation.JOINED_TO,
                    src=node_id, dst=other,
                    modality=Modality.UNRESOLVED_TARGET,
                    evidence=JOIN_EVIDENCE_OUTSIDE)


# ═══════════════════════════════════ WHAT THE VIEWER ASKS THE GRAPH
#
# Today the viewer reads `clash/hulls` HULLS, not the building's state, and this
# is visible by the numbers: on `демо-v3` **99.89 % of hulls are bounding boxes**, and
# **38.24 % are degenerate** (32 165 of 84 120 with zero volume). By showing them, the viewer
# shows the precision of clash geometry, not what building the engineer is
# actually facing. Below is a projection that answers "what kind of node is this", not
# "what box covers it".
#
# THE BOUNDARY OF RESPONSIBILITY, and it is load-bearing: the projection does NOT contain body
# geometry. It gives out the address, the class, and the FOUR honesty axes; the node's body is taken
# by the viewer where it exists, and it must be drawn DIFFERENTLY by `authority` and `existence`,
# not with identical bodies. Offline 3D shows the DECLARED; what Revit derives
# does not exist offline at all, and drawing it as declared would mean
# building a third witness that signs off on an unread axis, at the scale of the
# product.


@dataclass(frozen=True, slots=True)
class NodeView:
    """One node through the viewer's eyes: address, class, and BY WHAT it is confirmed."""

    node_id: str
    category: str
    #: `declared` | `derived_by_revit` — the graph is authoritative for the first,
    #: Revit for the second. The viewer must tell them apart by appearance, not by a label.
    authority: str
    #: BY WHAT the value above was decided. Without a witness the axis is not read.
    authority_source: str
    #: `materialized` | `planned` — built versus declared in chat.
    existence: str
    level_id: str | None
    #: The measured section, if the reading yielded it. Empty is not "zero" but "none".
    section: Mapping[str, Any]
    #: The outer dimension and BY WHAT it was measured, or None. The nominal never
    #: lands here — see `outer_size_mm`.
    outer_mm: tuple[float, str] | None
    #: Stable semantic keys. ``node_id`` above remains the local legacy alias.
    definition_identity: str | None
    occurrence_identity: str | None
    identity_authoritative: bool
    identity_gaps: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphView:
    """The building's state for the viewer: nodes + summaries + HONESTY.

    The summaries here are not decoration. `unresolved` and `refuted` are exactly what
    the engineer must see WHILE WORKING, not at the end: a refuted edge with
    a rule name, a target outside the extraction with a sub-reason, a node without an L1. The
    honesty layer in the viewer turns internal hygiene into a product property.
    """

    doc_name: str
    nodes: tuple[NodeView, ...]
    authority: Mapping[str, int]
    existence: Mapping[str, int]
    relations: Mapping[str, int]
    #: Edges whose target did not resolve, by sub-reason (`OutsideExtraction`).
    unresolved_by_reason: Mapping[str, int]
    #: Removed edges by the rule's NAME. An empty summary and the absence of a summary are different.
    refuted_by_rule: Mapping[str, int]
    #: Nodes that are not among the L1 leaves: the reading saw them, the compiler did not.
    #: `None` means "the leaf set was not supplied", and this is NOT "there are no such nodes".
    without_l1: tuple[str, ...] | None
    #: 🔴 KINDS WHOSE ZERO IN `relations` MEANS NOTHING: their source was not
    #: supplied. An empty tuple means "everything was measured".
    #:
    #: THE MEASUREMENT THAT BOUGHT THIS FIELD (RV-05, 04.09.2026):
    #:
    #:     graph_from_l0(..., joins=None)  and  graph_from_l0(..., joins={})
    #:        the views (graph_view) ARE IDENTICAL
    #:        the censuses DIFFER
    #:
    #: That is, the core PRESERVES the distinction (`census.sources_absent`), while the projection
    #: for the reader was losing it: `relations` does not carry empty kinds at all, and
    #: "joints were not measured" arrived at the viewer as the same view as "there are no joints
    #: in the building". Exactly the law this same file declares for
    #: `without_l1` and holds for `relation_count` — just not carried through to the
    #: final reader.
    unmeasured_relations: tuple[str, ...]
    #: The names of the unsupplied inputs themselves (`census.sources_absent`): the kind says
    #: WHAT is blind, and the name says WHAT was not supplied, and it is cured by supplying the input.
    sources_absent: tuple[str, ...]
    #: The census of the adjacency predicate, if it was called; `None` — it was not called.
    adjacency: Mapping[str, Any] | None
    #: The graph's census: nodes = assessed + named refusals.
    census_rows: int
    census_refusals: Mapping[str, int]
    identity_authoritative: bool
    identity_authoritative_nodes: int
    identity_incomplete_nodes: int
    identity_gaps: Mapping[str, int]


def graph_view(
    graph: "BuildingGraph",
    *,
    l1_source_ids: Iterable[str] | None = None,
) -> GraphView:
    """The graph's projection for the viewer. It computes nothing anew and draws nothing.

    `l1_source_ids` — the L1 leaf addresses of this same building. If not supplied -> the field
    `without_l1` equals `None`, meaning "was not asked"; an empty tuple
    means "asked, there are none". The same difference as `hosted` has in clashes.
    """
    views = tuple(
        NodeView(
            node_id=node.node_id,
            category=node.category,
            authority=node.authority.value,
            authority_source=node.authority_source.value,
            existence=node.existence.value,
            level_id=node.level_id,
            section=node.section,
            outer_mm=outer_size_mm(node),
            definition_identity=(
                node.definition_identity.key
                if node.definition_identity is not None else None),
            occurrence_identity=(
                node.occurrence_identity.key
                if node.occurrence_identity is not None else None),
            identity_authoritative=node.identity_authoritative,
            identity_gaps=tuple(gap.value for gap in node.identity_gaps),
        )
        for node in sorted(graph.nodes.values(), key=lambda n: n.node_id)
    )
    unresolved: Counter[str] = Counter()
    for edge in graph.edges:
        if edge.modality is Modality.UNRESOLVED_TARGET:
            unresolved[str(edge.evidence.get("why") or "unnamed")] += 1
    without_l1: tuple[str, ...] | None = None
    if l1_source_ids is not None:
        known = set(l1_source_ids)
        without_l1 = tuple(sorted(set(graph.nodes) - known))
    return GraphView(
        doc_name=graph.doc_name,
        nodes=views,
        authority=graph.authority_counts(),
        existence=graph.existence_counts(),
        relations=graph.relation_counts(),
        unresolved_by_reason=dict(unresolved),
        refuted_by_rule=graph.refuted_by_counts(),
        without_l1=without_l1,
        unmeasured_relations=tuple(
            relation.value for relation in graph.unmeasured_relations()),
        sources_absent=tuple(graph.census.sources_absent),
        adjacency=graph.census.adjacency,
        census_rows=graph.census.rows_seen,
        census_refusals=dict(graph.census.refusals),
        identity_authoritative=graph.identity_authoritative,
        identity_authoritative_nodes=graph.census.identity_authoritative_nodes,
        identity_incomplete_nodes=graph.census.identity_incomplete_nodes or 0,
        identity_gaps=dict(graph.census.identity_gaps),
    )
