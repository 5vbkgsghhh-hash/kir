"""CLASH AS A SCOPED QUERY, not as a layer of stored edges.

This module is NOT a detector. It is the boundary beyond which clash enters
the building graph, and it is built so that storing clash edges is
IMPOSSIBLE, not merely discouraged. The ban is declared by structure
(`ClashQuery` returns an iterator and never accumulates), not by a comment:
a comment would not survive the first person who wants to "just cache it".

═══════════════════════════════════════════════════════════════════════════
WHY A QUERY, NOT A LAYER — THE THRESHOLD WAS NAMED IN ADVANCE AND MEASURED
═══════════════════════════════════════════════════════════════════════════

`демо-v3`, scope `all_physical_diagnostic` (measured by the CLASH team,
10.08.2026):

| quantity | value |
|---|---|
| nodes (hulls) | 84 120 |
| broad-phase candidate edges | 770 234 |
| finding edges | 769 630 |
| the report for them, ONE JSON file | **666 MB** |
| peak process RSS | **2.66 GB** |
| narrow-phase time | 38.1 s |
| the grid itself | **0.81 s** |

The ratio of edges to nodes is **9.15**. The narrow phase is **47 times**
more expensive than the grid. The limit here is not the neighbor search, but
the LIST OF EDGES: doubling the building (~170 000 nodes) needs on the order
of 10 GB just for findings. A graph that tries to keep clash edges next to
its nodes will hit the same wall — only now at the level of the whole
application, not one module.

═══════════════════════════════════════════════════════════════════════════
A CLASH EDGE IS TYPED TWICE — AND THIS IS THE MAIN FIX
═══════════════════════════════════════════════════════════════════════════

Today's "finding" glues together THREE different relations:

**(a) CONTACT** — a shared boundary, zero penetration. The way the building
is ASSEMBLED, not a defect. Measured: `sob62_fas_r23_v19` — 7 804 contacts
against 19 523 overlaps; `snowdon_plumb_v5` — 8 559 against 18 030. A third
of all relations are contacting pairs. Contact is an ASSEMBLY edge, its
place is next to the nodes forever, and it must not be shown as a finding.

**(b) BODY PENETRATION** — an intersection of positive volume. A physical
conflict. Production builders are outer-only for now (`exact` = 0 across the
historical corpus), but dual geometry can prove it by intersecting two
certified `Inner ⊆ Body` volumes. That is why `PROVEN/OVERLAP` exists, but
is built only from an opaque verified proof, never from the word `confirmed`.

**(c) HULL INTERSECTION** — what the module REALLY computes: the
intersection of two CONSERVATIVE SUPERSETS. This is a fact about our
DESCRIPTION of the construction, not about the construction itself.

`modality` today is smeared across two modules and three fields (`verdict`,
`hull_grade`, `slack`), and it was exactly at its fusion with `relation` that
both defects fixed on 10.08 broke: the vacuous `plate_z_doubling` and the
false `profile_convexified`.

**A REFUTATION IS AN EDGE, NOT THE ABSENCE OF ONE.** An edge removed by a
rule must remain in the answer, carrying the rule's NAME; otherwise "not
found" is indistinguishable from "never looked", and both diseases return.
Here this is a construction invariant: a `ClashRelationEdge` with `REFUTED`
and no `refuted_by` cannot be built.

═══════════════════════════════════════════════════════════════════════════
WHAT THE QUERY TAKES FROM THE GRAPH INSTEAD OF GUESSING
═══════════════════════════════════════════════════════════════════════════

`resolve.ASSEMBLY_PAIRS` guesses an assembly relation BY A PAIR OF LABELS
(door~wall, mullion~panel). Measured: **467 of 3 348 overlaps (14.0%)** on
`sob62_r23_v5` were attributed to assembly by this guess.

The guess is replaced by a `hosted_in` edge, and the data for it EXISTS in
the decompile — measured 10.08 from `L0Element.host_id`:

    `sob62_r23_v5`      doors 153/153 (100%) hosted by `OST_Walls`;
                        windows 31/31  (100%) hosted by `OST_Walls`
    `sob62_fas_r23_v17` mullions 1 452/1 452 (100%) hosted by `OST_Walls`;
                        panels    594/1 215 (48.9%)
    `snowdon_plumb_v5`  doors 143/143, windows 114/114 (100%)

BUT THE GUESS ALSO MISSES IN THE DIRECTION THAT LABELS CANNOT DESCRIBE, and
this is visible only through `host_id`:

* `sob62_fas_r23_v17`: **9 of 14** doors are hosted by
  `OST_CurtainWallPanels`, not a wall;
* `snowdon_plumb_v5`: **89 of 1 425** mullions are hosted by a panel, and
  **23 of 640** panels — by another panel;
* `snowdon_plumb_v5`: **21** `OST_GenericModel` and **4**
  `OST_PlumbingFixtures` are hosted by `OST_Levels` — a DATUM, not a body.
  Label pairs do not describe this relation at all, and in the graph it
  travels as a separate `PLACED_ON_DATUM`.

**AND THE MAIN LIMIT THAT CANNOT BE SWEPT AWAY:** `host_id` does not carry
an answer everywhere. Across the corpus, dangling references are 1 263 of
213 811 (0.59%), but they are CONCENTRATED: `snowdon_elec_v1` — **959 of
1 001 (95.8%)**, four Snowdon Plumbing snapshots — **100%**. The host lives
in a LINKED file. That is why the query must distinguish "there is no host"
from "the host is outside the extraction", and the second answer is exactly
the signal that makes the cross-discipline scope non-empty.
"""
from __future__ import annotations

import hashlib
import json
import math
import pathlib
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from kir.clash import detect as clash_detect
from kir.decompile.building_graph import (
    BuildingGraph,
    GraphBuildError,
    Modality,
    Relation,
)

__all__ = [
    "ClashQuery",
    "ClashRelation",
    "ClashRelationEdge",
    "ClashProofKind",
    "ConstraintVerdict",
    "ClashScope",
    "ScopeCensus",
    "VerifiedClashProof",
    "assembly_relation_of",
    "edge_from_finding",
    "graph_for_clash_query",
]


class ClashRelation(str, Enum):
    """The GEOMETRIC relation between hulls. Orthogonal to `Modality`.

    Three values instead of the one word "finding" — see the module header.
    """

    #: A shared boundary, zero penetration. A way of assembly, not a defect.
    CONTACT = "contact"
    #: An intersection of positive volume (or its conservative over-estimate).
    OVERLAP = "overlap"
    #: Kept apart. An answer that also must be sayable.
    SEPARATED = "separated"


class ClashProofKind(str, Enum):
    """The exact theorem a trusted detector proved for one pair."""

    CERTIFIED_INNER_OVERLAP = "certified_inner_overlap"
    CONSERVATIVE_OUTER_SEPARATION = "conservative_outer_separation"
    EXACT_BODY_CONTACT = "exact_body_contact"


class ConstraintVerdict(str, Enum):
    """Whether the requested clearance/interference rule was violated."""

    NOT_EVALUATED = "not_evaluated"
    SATISFIED = "satisfied"
    POSSIBLE_VIOLATION = "possible_violation"
    PROVEN_VIOLATION = "proven_violation"


_VERIFIED_CLASH_PROOF_AUTHORITY = object()


def _freeze_evidence(value: Any, *, path: str = "clash evidence") -> Any:
    """Deep immutable snapshot of JSON-like classifier evidence."""

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
            frozen[key] = _freeze_evidence(item, path=f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_evidence(item, path=f"{path}[{index}]")
            for index, item in enumerate(value))
    raise GraphBuildError(
        f"{path} contains unsupported {type(value).__name__}")


@dataclass(frozen=True, init=False, slots=True)
class VerifiedClashProof:
    """Opaque in-process capability for a proven geometric relation.

    Public finding fields are audit data and can be edited after JSON
    serialization.  A caller therefore cannot construct this token from a
    plausible ``verdict`` string.  ``edge_from_finding`` mints it only while
    consuming a typed detector result and, for overlap, after validating the
    detector's complete sealed inner-proof chain.

    This is a trust boundary for serialized data, not a Python sandbox: code
    already executing inside this process is trusted.
    """

    kind: ClashProofKind
    relation: ClashRelation
    subject_a: str
    subject_b: str
    evidence_digest: str
    _authority: object = field(repr=False, compare=False)

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TypeError(
            "VerifiedClashProof is opaque; consume a typed detector finding")

    def valid_for(self, a: str, b: str, relation: ClashRelation) -> bool:
        return (
            self._authority is _VERIFIED_CLASH_PROOF_AUTHORITY
            and self.relation is relation
            and self.subject_a == a
            and self.subject_b == b
            and isinstance(self.evidence_digest, str)
            and len(self.evidence_digest) == 64
            and all(char in "0123456789abcdef"
                    for char in self.evidence_digest)
        )


def _mint_verified_clash_proof(
    *, kind: ClashProofKind, relation: ClashRelation,
    subject_a: str, subject_b: str, evidence_digest: str,
) -> VerifiedClashProof:
    proof = object.__new__(VerifiedClashProof)
    object.__setattr__(proof, "kind", kind)
    object.__setattr__(proof, "relation", relation)
    object.__setattr__(proof, "subject_a", subject_a)
    object.__setattr__(proof, "subject_b", subject_b)
    object.__setattr__(proof, "evidence_digest", evidence_digest)
    object.__setattr__(proof, "_authority", _VERIFIED_CLASH_PROOF_AUTHORITY)
    return proof


@dataclass(frozen=True, slots=True)
class ClashRelationEdge:
    """A clash edge. Lives ONLY inside a query response and is never stored."""

    a: str
    b: str
    relation: ClashRelation
    modality: Modality
    #: Relation truth and rule truth are independent.  In particular,
    #: conservative outers can prove SEPARATED while only suggesting that the
    #: true-body clearance is too small.
    constraint_verdict: ConstraintVerdict = ConstraintVerdict.NOT_EVALUATED
    #: The name of the COARSENING or rule that removed the edge. Mandatory when REFUTED.
    refuted_by: str | None = None
    #: The source of hull A and B, the depth, whether this is a lower-bound estimate.
    evidence: Mapping[str, Any] = field(default_factory=dict)
    #: In-process proof capability.  It is deliberately not reconstructed
    #: from ``evidence`` and never serialized as authority.
    verified_proof: VerifiedClashProof | None = field(
        default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name, subject in (("a", self.a), ("b", self.b)):
            if not isinstance(subject, str) or not subject.strip():
                raise GraphBuildError(
                    f"clash edge {name} must be a non-empty subject key")
        if self.a == self.b:
            raise GraphBuildError("clash edge requires two distinct subjects")
        if not isinstance(self.relation, ClashRelation):
            raise GraphBuildError("clash edge relation must be typed")
        if not isinstance(self.modality, Modality):
            raise GraphBuildError("clash edge modality must be typed")
        if not isinstance(self.constraint_verdict, ConstraintVerdict):
            raise GraphBuildError("constraint_verdict must be typed")
        if self.modality is Modality.REFUTED:
            if (not isinstance(self.refuted_by, str)
                    or not self.refuted_by.strip()):
                raise GraphBuildError(
                    "клеш-ребро REFUTED без имени огрубления неотличимо от "
                    "«не искали» — правило обязано назваться")
        if self.modality is not Modality.REFUTED and self.refuted_by:
            raise GraphBuildError(
                "`refuted_by` при неопровергнутом ребре — ложный след")
        if not isinstance(self.evidence, Mapping):
            raise GraphBuildError("clash edge evidence must be a mapping")
        object.__setattr__(
            self, "evidence", _freeze_evidence(self.evidence))
        if self.modality is Modality.PROVEN:
            if (not isinstance(self.verified_proof, VerifiedClashProof)
                    or not self.verified_proof.valid_for(
                        self.a, self.b, self.relation)):
                raise GraphBuildError(
                    "PROVEN геометрическое ребро требует opaque verified proof")
            if (self.relation is ClashRelation.OVERLAP
                    and self.verified_proof.kind
                    is not ClashProofKind.CERTIFIED_INNER_OVERLAP):
                raise GraphBuildError(
                    "PROVEN overlap требует certified inner overlap")
            if (self.relation is ClashRelation.CONTACT
                    and self.verified_proof.kind
                    is not ClashProofKind.EXACT_BODY_CONTACT):
                raise GraphBuildError(
                    "PROVEN contact требует exact-body contact proof")
            if (self.relation is ClashRelation.SEPARATED
                    and self.verified_proof.kind
                    is not ClashProofKind.CONSERVATIVE_OUTER_SEPARATION):
                raise GraphBuildError(
                    "PROVEN separation требует conservative outer proof")
        elif self.verified_proof is not None:
            raise GraphBuildError(
                "verified proof запрещён у ребра без PROVEN modality")


def _finding_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def edge_from_finding(
        finding: clash_detect.Finding) -> ClashRelationEdge:
    """Adapt a typed detector result without promoting its JSON strings.

    Relation and proof modality are different axes:

    * certified inner positive-volume overlap -> ``PROVEN/OVERLAP``;
    * outer-only overlap or contact -> ``POSSIBLE``;
    * separation of conservative outer supersets -> ``PROVEN/SEPARATED``.

    The last implication is safe because ``Body ⊆ Outer`` on both sides: if
    the outers are disjoint, the bodies are disjoint.  It says nothing about
    a clearance violation being proven; that remains explicit in evidence.
    """

    if not isinstance(finding, clash_detect.Finding):
        raise GraphBuildError("clash edge adapter requires detector Finding")
    wire = finding.as_dict()
    side_a = wire.get("a")
    side_b = wire.get("b")
    if not isinstance(side_a, Mapping) or not isinstance(side_b, Mapping):
        raise GraphBuildError("detector finding has malformed subjects")
    a = side_a.get("source_element_id")
    b = side_b.get("source_element_id")
    if not isinstance(a, str) or not a or not isinstance(b, str) or not b:
        raise GraphBuildError("detector finding subjects must be non-empty")
    try:
        relation = ClashRelation(str(wire.get("hull_relation")))
    except ValueError as exc:
        raise GraphBuildError("detector finding relation is unsupported") from exc

    proof: VerifiedClashProof | None = None
    modality = Modality.POSSIBLE
    if relation is ClashRelation.OVERLAP and wire.get("verdict") == "confirmed":
        serialized = wire.get("physical_overlap_proof")
        if (isinstance(serialized, Mapping)
                and clash_detect.verify_serialized_physical_overlap_proof(
                    serialized, subject_a=a, subject_b=b)):
            proof_digest = serialized.get("proof_digest")
            if not isinstance(proof_digest, str):
                raise GraphBuildError("confirmed overlap proof lacks digest")
            proof = _mint_verified_clash_proof(
                kind=ClashProofKind.CERTIFIED_INNER_OVERLAP,
                relation=relation, subject_a=a, subject_b=b,
                evidence_digest=proof_digest,
            )
            modality = Modality.PROVEN
    elif relation is ClashRelation.SEPARATED:
        # This capability is minted from the live typed detector object, not
        # from a deserialized mapping.  The digest is an audit address only.
        proof = _mint_verified_clash_proof(
            kind=ClashProofKind.CONSERVATIVE_OUTER_SEPARATION,
            relation=relation, subject_a=a, subject_b=b,
            evidence_digest=_finding_digest({
                "finding_id": wire.get("finding_id"),
                "a": side_a,
                "b": side_b,
                "signed_distance_mm": wire.get("signed_distance_mm"),
                "hull_relation": wire.get("hull_relation"),
            }),
        )
        modality = Modality.PROVEN

    deficit = wire.get("clearance_deficit_mm")
    has_deficit = (
        not isinstance(deficit, bool)
        and isinstance(deficit, (int, float))
        and float(deficit) > 0.0
    )
    if relation is ClashRelation.OVERLAP:
        constraint_verdict = (
            ConstraintVerdict.PROVEN_VIOLATION
            if modality is Modality.PROVEN
            else ConstraintVerdict.POSSIBLE_VIOLATION)
    elif has_deficit:
        # A conservative outer gap is a lower bound on the true-body gap: it
        # proves separation, but not that the bodies fail the clearance.
        constraint_verdict = ConstraintVerdict.POSSIBLE_VIOLATION
    else:
        constraint_verdict = ConstraintVerdict.SATISFIED

    return ClashRelationEdge(
        a=a,
        b=b,
        relation=relation,
        modality=modality,
        constraint_verdict=constraint_verdict,
        evidence={
            "finding_id": wire.get("finding_id"),
            "geometry_verdict": wire.get("verdict"),
            "pair_kind": wire.get("pair_kind"),
            "signed_distance_mm": wire.get("signed_distance_mm"),
            "hull_overlap_depth_mm": wire.get("hull_overlap_depth_mm"),
            "clearance_mm": wire.get("clearance_mm"),
            "clearance_deficit_mm": wire.get("clearance_deficit_mm"),
            "proof_digest": (
                proof.evidence_digest if proof is not None else None),
        },
        verified_proof=proof,
    )


@dataclass(frozen=True, slots=True)
class ScopeCensus:
    """The query's DENOMINATOR. Without it, "no clashes" means nothing.

    The CLASH census law (`eligible = hulled + unsupported +
    missing_geometry`) converges today for every category of every one of 65
    decompiles — 0 silent drops across ~1.03 million elements. Here the same
    law applies to GRAPH nodes.
    """

    nodes_in_scope: int
    nodes_with_hull: int
    refusals: Mapping[str, int]

    def __post_init__(self) -> None:
        for name, value in (
            ("nodes_in_scope", self.nodes_in_scope),
            ("nodes_with_hull", self.nodes_with_hull),
        ):
            if (isinstance(value, bool) or not isinstance(value, int)
                    or value < 0):
                raise GraphBuildError(
                    f"ScopeCensus.{name} must be a non-negative int")
        if not isinstance(self.refusals, Mapping):
            raise GraphBuildError("ScopeCensus.refusals must be a mapping")
        normalized: dict[str, int] = {}
        for reason, count in self.refusals.items():
            if not isinstance(reason, str) or not reason.strip():
                raise GraphBuildError(
                    "ScopeCensus refusal keys must be non-empty strings")
            if (isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise GraphBuildError(
                    "ScopeCensus refusal counts must be non-negative ints")
            normalized[reason] = count
        object.__setattr__(
            self, "refusals",
            MappingProxyType(dict(sorted(normalized.items()))))
        self.assert_balanced()

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())

    def assert_balanced(self) -> None:
        if self.nodes_with_hull + self.refused != self.nodes_in_scope:
            raise GraphBuildError(
                f"перепись области не сходится: узлов {self.nodes_in_scope}, "
                f"с оболочкой {self.nodes_with_hull}, названных отказов "
                f"{self.refused}")


@dataclass(frozen=True, slots=True)
class ClashScope:
    """The query's SCOPE. Clash with no scope is 770 234 edges and 666 MB.

    `scope_id` already exists in the clash module; here it is MANDATORY,
    because it is exactly what separates a query from a layer.
    """

    scope_id: str
    node_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise GraphBuildError(
                "запрос без `scope_id` есть слой рёбер под другим именем")
        if not isinstance(self.node_ids, frozenset):
            raise GraphBuildError(
                "ClashScope.node_ids must be an immutable frozenset")
        if any(not isinstance(node_id, str) or not node_id.strip()
               for node_id in self.node_ids):
            raise GraphBuildError(
                "ClashScope node keys must be non-empty strings")
        if not self.node_ids:
            raise GraphBuildError(
                "empty ClashScope cannot support a non-vacuous clash verdict")


#: Graph relations under which a hull intersection is ASSEMBLY, not a
#: conflict. This is EVIDENCE (a read `host_id`), not a guess from a pair of
#: labels.
_ASSEMBLY_RELATIONS: frozenset[Relation] = frozenset({
    Relation.HOSTED_IN,
    Relation.PLACED_ON_DATUM,
})


def assembly_relation_of(graph: BuildingGraph, a: str, b: str) -> str | None:
    """Whether an ASSEMBLY relation is declared between the pair — by the
    graph, not by labels.

    Returns the name of only an exact ``PROVEN src↔dst`` relation, or None.
    An unresolved reference to an external host remains an uncertainty, but
    is never proof that some arbitrary second candidate is that host.

    Replaces `resolve.ASSEMBLY_PAIRS`: 467 of 3 348 overlaps (14.0%) on
    `sob62_r23_v5` used to be classified by this label-pair guess.
    """
    if not isinstance(graph, BuildingGraph):
        raise GraphBuildError("assembly lookup requires BuildingGraph")
    for name, value in (("a", a), ("b", b)):
        if not isinstance(value, str) or not value.strip():
            raise GraphBuildError(
                f"assembly lookup {name} must be a non-empty node key")
        if value not in graph:
            raise GraphBuildError(
                f"assembly lookup {name} is not a graph node: {value!r}")
    if a == b:
        raise GraphBuildError("assembly lookup requires two distinct nodes")
    for src, dst in ((a, b), (b, a)):
        for edge in graph.out_edges(src):
            if edge.relation not in _ASSEMBLY_RELATIONS:
                continue
            if edge.dst == dst and edge.modality is Modality.PROVEN:
                return edge.relation.value
    return None


def _assembly_uncertainty(
        graph: BuildingGraph, a: str, b: str) -> tuple[dict[str, Any], ...]:
    """Retain external-host blindness without turning it into pair truth."""

    unresolved: list[dict[str, Any]] = []
    for src in sorted((a, b)):
        for edge in graph.out_edges(src):
            if (edge.relation is Relation.HOSTED_IN
                    and edge.modality is Modality.UNRESOLVED_TARGET):
                unresolved.append({
                    "kind": "unresolved_external_host",
                    "source_node_id": src,
                    "declared_local_target": edge.dst,
                    "relation": edge.relation.value,
                    "modality": edge.modality.value,
                    "source_evidence": dict(edge.evidence),
                })
    return tuple(unresolved)


class ClashQuery:
    """Clash as a QUERY. Returns an iterator and accumulates NOTHING.

    The absence of a method that returns a list is not an oversight: it IS
    the ban. The measurement names the list's cost up front (770 234 edges,
    666 MB, 2.66 GB RSS on `демо-v3`), which is why a list is never offered
    at all.
    """

    __slots__ = ("graph", "scope", "_pairs", "_classify", "census")

    def __init__(
        self,
        graph: BuildingGraph,
        scope: ClashScope,
        *,
        candidate_pairs: Callable[[], Iterable[tuple[str, str]]],
        classify: Callable[[str, str], ClashRelationEdge | None],
        census: ScopeCensus,
    ) -> None:
        if not isinstance(graph, BuildingGraph):
            raise GraphBuildError(
                "ClashQuery is local-only and requires BuildingGraph; an "
                "occurrence-keyed federated graph needs a federated adapter")
        if not isinstance(scope, ClashScope):
            raise GraphBuildError("ClashQuery scope must be ClashScope")
        if not isinstance(census, ScopeCensus):
            raise GraphBuildError("ClashQuery census must be ScopeCensus")
        if not callable(candidate_pairs) or not callable(classify):
            raise GraphBuildError(
                "ClashQuery candidate_pairs and classify must be callable")
        unknown = scope.node_ids - set(graph.nodes)
        if unknown:
            raise GraphBuildError(
                f"область называет {len(unknown)} узлов, которых в графе нет; "
                f"первый — {sorted(unknown)[0]!r}")
        if census.nodes_in_scope != len(scope.node_ids):
            raise GraphBuildError(
                "ScopeCensus.nodes_in_scope must equal the exact declared "
                "ClashScope node-key set")
        self.graph = graph
        self.scope = scope
        self._pairs = candidate_pairs
        self._classify = classify
        self.census = census

    def __iter__(self) -> Iterator[ClashRelationEdge]:
        """The only way to get clash edges — walk them ONCE."""
        previous_pair: tuple[str, str] | None = None
        for candidate in self._pairs():
            if (not isinstance(candidate, (tuple, list))
                    or len(candidate) != 2):
                raise GraphBuildError(
                    "candidate stream must yield exact two-key pairs")
            a, b = candidate
            for name, node_id in (("a", a), ("b", b)):
                if not isinstance(node_id, str) or not node_id.strip():
                    raise GraphBuildError(
                        f"candidate {name} must be a non-empty node key")
            if a == b:
                raise GraphBuildError(
                    "candidate pair cannot address one node twice")
            pair = (a, b)
            if pair != tuple(sorted(pair)):
                raise GraphBuildError(
                    "candidate pair must use canonical subject order; A/B swap "
                    "would detach side-specific evidence")
            if previous_pair is not None and pair <= previous_pair:
                raise GraphBuildError(
                    "candidate stream must be strictly ordered and duplicate-free")
            previous_pair = pair
            if a not in self.scope.node_ids or b not in self.scope.node_ids:
                raise GraphBuildError(
                    "candidate pair escapes the exact declared ClashScope")
            assembly = assembly_relation_of(self.graph, a, b)
            uncertainty = _assembly_uncertainty(self.graph, a, b)
            edge = self._classify(a, b)
            if edge is None:
                raise GraphBuildError(
                    "classifier silently dropped a candidate; return an exact "
                    "SEPARATED, REFUTED, or uncertainty edge")
            if not isinstance(edge, ClashRelationEdge):
                raise GraphBuildError(
                    "classifier must return ClashRelationEdge")
            if (edge.a, edge.b) != (a, b):
                raise GraphBuildError(
                    "classifier returned swapped evidence or evidence for "
                    "another candidate pair")
            if assembly is not None and edge.modality is not Modality.REFUTED:
                reserved = {
                    "assembly_from", "was_modality",
                    "assembly_semantic_verdict",
                }
                if reserved.intersection(edge.evidence):
                    raise GraphBuildError(
                        "classifier evidence uses reserved assembly keys")
                # An assembly relation REMOVES a finding — and the edge
                # REMAINS, carrying the rule's name. `resolve` used to guess
                # this from labels.
                edge = ClashRelationEdge(
                    a=edge.a, b=edge.b, relation=edge.relation,
                    modality=Modality.REFUTED,
                    constraint_verdict=ConstraintVerdict.SATISFIED,
                    refuted_by=f"assembly_relation:{assembly}",
                    evidence={**dict(edge.evidence),
                              "assembly_from": "building_graph",
                              "was_modality": edge.modality.value,
                              "assembly_semantic_verdict": "resolved"})
            elif uncertainty:
                reserved = {
                    "assembly_uncertainty", "assembly_semantic_verdict",
                    "constraint_verdict_before_assembly_uncertainty",
                }
                if reserved.intersection(edge.evidence):
                    raise GraphBuildError(
                        "classifier evidence uses reserved assembly keys")
                # Unknown external host is evidence about what this snapshot
                # could not resolve.  It is never evidence that candidate B
                # *is* that host, so the geometric finding, proof, AND exact
                # requested constraint verdict stay unchanged.
                edge = ClashRelationEdge(
                    a=edge.a,
                    b=edge.b,
                    relation=edge.relation,
                    modality=edge.modality,
                    constraint_verdict=edge.constraint_verdict,
                    refuted_by=edge.refuted_by,
                    evidence={
                        **dict(edge.evidence),
                        "assembly_uncertainty": list(uncertainty),
                        "assembly_semantic_verdict": "unresolved",
                        "constraint_verdict_before_assembly_uncertainty": (
                            edge.constraint_verdict.value),
                    },
                    verified_proof=edge.verified_proof,
                )
            yield edge

    def tally(self) -> Mapping[str, int]:
        """A summary from one pass. Edges are not kept — only counters."""
        from collections import Counter
        counter: Counter[str] = Counter()
        counter["scope:nodes"] = self.census.nodes_in_scope
        counter["scope:hulled"] = self.census.nodes_with_hull
        counter["scope:complete"] = int(self.census.refused == 0)
        for reason, count in self.census.refusals.items():
            counter[f"scope_refusal:{reason}"] = count
        adjudicated = 0
        for edge in self:
            adjudicated += 1
            counter[f"{edge.relation.value}/{edge.modality.value}"] += 1
            counter[f"constraint:{edge.constraint_verdict.value}"] += 1
            if edge.refuted_by:
                counter[f"refuted_by:{edge.refuted_by}"] += 1
        counter["candidates:adjudicated"] = adjudicated
        return dict(counter)


# ═══════════════════════════════════════════════════════════════════════════
# WIRING: FROM A DECOMPILED BUILDING TO A QUERY, IN ONE COMMAND
# ═══════════════════════════════════════════════════════════════════════════

def graph_for_clash_query(run_dir) -> BuildingGraph:
    """The canonical stored BuildingGraph, or its full builder.

    The decompile pipeline already writes ``building_graph.json`` after
    folding L0 together with the available typed side indexes. A second
    assembly built only from ``document``/``element`` rows and joins used to
    lose link records and the other sources already represented in this
    artifact.

    A missing artifact is not corruption, so the same canonical builder can
    reconstruct it in memory. An existing but wrong artifact is not hidden by
    a fallback: :func:`graph_store.load_graph` refuses before the builder is
    ever considered.
    """

    from kir.decompile import graph_store

    run = pathlib.Path(run_dir)
    graph = graph_store.load_graph(run)
    if graph is None:
        graph = graph_store.build_graph_for_run(run)
    # The type is checked both by the producers and at this boundary: a new
    # adapter must not turn a foreign shape into a plausible-looking query
    # object.
    if not isinstance(graph, BuildingGraph):
        raise GraphBuildError(
            "canonical clash graph adapter did not return BuildingGraph")
    return graph


def query_from_decompile(
    run_dir,
    *,
    pair_filter=None,
    clearance_mm: float = 0.0,
) -> "ClashQuery":
    """An on-disk decompile -> a `ClashQuery` over a LIVE graph and a LIVE
    detector.

    🔴 WHAT THIS FIXES, BY MEASUREMENT ON 19.08.2026. This module had ZERO
    production importers, and that read as "built and not wired in". The
    measurement showed something else, and worse: **the entry point was
    unreachable BY CONSTRUCTION**. `edge_from_finding` accepts a typed
    `clash_detect.Finding`, while `detect()` at the report boundary returned
    `[f.as_dict() ...]` — dicts. The one bridge from clash into the graph
    would not accept what the one production entry point of the detector
    produces.

    The addresses, meanwhile, had agreed the whole time: on `sob62_r23_v5`
    **298 of 298** subjects of the first 400 findings are present in the
    graph as nodes, because the key on both sides is the L0 `element_id`.
    What was missing was exactly the wire, and the wire turned out to be
    impossible because of the type, not the address.

    Fixed on the detector's side (`clash.detect.search()` now returns typed
    objects, the report is byte-for-byte the same), and here — the wiring
    was assembled.

    THE SCOPE IS DERIVED FROM THE FINDINGS, NOT DECLARED MORE BROADLY.
    `ClashQuery` requires EVERY candidate to be classified and forbids a
    silent skip; so the candidates here are exactly the pairs the detector
    spoke about, and the scope's nodes are exactly their subjects. Taking
    "every graph node" as the scope would commit to emitting an edge for
    1.1e9 pairs in the tower: that is exactly the edge layer this module was
    written to forbid.

    WHAT THIS WIRING DOES NOT DO: it does not widen the detector's coverage,
    does not raise the hull grade, and does not turn `possible` into
    `confirmed` — 99.33% of hulls are still a bare bounding box.

    🔴 BUT THE TAIL OF THAT SENTENCE WAS RETRACTED ON 20.08.2026. It used to
    read "and this is fixed by capture"; a corpus re-measurement says
    otherwise. Wall thickness IS CAPTURED: `params.WALL_ATTR_WIDTH_PARAM` is
    present on 220 326 of 286 430 walls, and the full field set needed for a
    prism — on 203 661 (71.1%). What holds the grade back is not capture,
    but the measured refusal `hulls.WALL_BAND_REFUSAL`: the band around the
    axis does not contain a real body. Full write-up —
    `hulls.WALL_WITNESS_2026_08_20`.
    """
    from kir.clash import detect as _detect
    from kir.clash import snapshot as _snapshot

    if pair_filter is None:
        pair_filter = _detect.mvp_pair_filter

    run = pathlib.Path(run_dir)
    graph = graph_for_clash_query(run)

    found = _detect.search(
        _snapshot.build_from_decompile(run),
        clearance_mm=clearance_mm, pair_filter=pair_filter)

    by_pair: dict[tuple[str, str], Any] = {}
    # 🔴 SCOPE REFUSALS ARE COLLECTED, NOT SKIPPED (E-56, 03.09.2026).
    # The comment below has stood here from the very start and promised
    # exactly this — "a named scope refusal, not a silent skip, it reduces
    # the census denominator and must be visible" — while the code did
    # `continue`, and the census was built as `ScopeCensus(len(node_ids),
    # len(node_ids), {})`. The law `nodes = with_hull + refusals` degenerated
    # into `N + 0 == N`: it IS CAPABLE of failing red (`ScopeCensus(10, 7,
    # {})` refuses), but it was NEVER built that way. The prose promised,
    # the mechanism did not exist.
    вне_графа: set[str] = set()
    безымянных = 0
    for finding in found.findings:
        wire = finding.as_dict()
        a = str(wire["a"].get("source_element_id") or "")
        b = str(wire["b"].get("source_element_id") or "")
        if not a or not b or a == b:
            # A subject with no address, or a pair with itself, is not a
            # SCOPE refusal: such a finding owns no node, and it has no place
            # in the node denominator. Counted separately so it does not
            # dissolve unnoticed.
            безымянных += 1
            continue
        # A subject outside the graph is a NAMED scope refusal, not a silent
        # skip: it reduces the census denominator and must be visible.
        снаружи = [x for x in (a, b) if x not in graph.nodes]
        if снаружи:
            вне_графа.update(снаружи)
            continue
        by_pair[tuple(sorted((a, b)))] = finding

    node_ids = frozenset(key for pair in by_pair for key in pair)
    if not node_ids:
        raise GraphBuildError(
            f"{run.name}: детектор не дал ни одной пары, чьи оба субъекта "
            f"есть в графе — область пуста, и запрос был бы вакуумным")

    ordered = tuple(sorted(by_pair))
    scope = ClashScope(scope_id=found.scope_id, node_ids=node_ids)
    # THE DENOMINATOR is ALL subjects the detector named: those that made
    # it into the graph plus those rejected. Previously both fields took the
    # same number, and the law was checking itself.
    #
    # 🔴 THE ASSUMPTION IS NAMED, NOT LEFT UNSAID: "a node in the graph" is
    # treated here as "a node with a hull". A graph node has no hull flag of
    # its own, and one cannot be invented; if one appears, `nodes_with_hull`
    # must ask IT, not graph membership.
    отказы: dict[str, int] = {}
    if вне_графа:
        отказы["субъект вне графа"] = len(вне_графа)
    census = ScopeCensus(
        nodes_in_scope=len(node_ids) + len(вне_графа),
        nodes_with_hull=len(node_ids),
        refusals=отказы,
    )

    def _pairs():
        return iter(ordered)

    def _classify(a: str, b: str) -> ClashRelationEdge:
        return edge_from_finding(by_pair[(a, b)])

    return ClashQuery(graph, scope, candidate_pairs=_pairs,
                      classify=_classify, census=census)
