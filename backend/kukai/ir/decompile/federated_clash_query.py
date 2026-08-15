"""Occurrence-keyed streaming clash query over one proven federation frame."""
from __future__ import annotations

import collections
import hashlib
import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Iterable, Iterator, Mapping

from kukai.clash import detect as clash_detect
from kukai.clash import hulls as H
from kukai.clash import snapshot as clash_snapshot
from kukai.clash.federation_transform import (
    FederatedHullSet,
    FederationGeometryGap,
)

from .building_graph import Modality, Relation
from .federation import (
    FederatedBuildingGraph,
    FederatedEdge,
    FederatedScope,
    FederationAssemblyError,
)
from .graph_clash_query import (
    ClashRelationEdge,
    ConstraintVerdict,
)
from .identity import OccurrenceIdentity


__all__ = [
    "FederatedClashQuery",
    "FederatedClashQueryError",
    "FederatedScopeCensus",
    "federated_assembly_relation_of",
    "federated_clash_snapshot",
]


class FederatedClashQueryError(ValueError):
    """Graph, geometry, scope, or streaming evidence contradicts its binding."""


_ASSEMBLY_RELATIONS = frozenset({
    Relation.HOSTED_IN,
    Relation.PLACED_ON_DATUM,
})


def _sha256_json(value: Mapping[str, Any]) -> str:
    try:
        raw = json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FederatedClashQueryError(
            "federated clash evidence is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _graph_digest(graph: FederatedBuildingGraph) -> str:
    return hashlib.sha256(graph.to_json().encode("utf-8")).hexdigest()


def _validated_hull_digest(hulls: FederatedHullSet) -> str:
    wire = hulls.as_dict()
    claimed = wire.pop("content_digest", None)
    actual = _sha256_json(wire)
    if (not isinstance(claimed, str) or claimed != actual
            or hulls.content_digest != actual):
        raise FederatedClashQueryError(
            "federated hull-set digest does not verify")
    return actual


def _gap_refusal_id(gap: FederationGeometryGap, index: int) -> str:
    digest = _sha256_json({
        "schema_version": "clash-federation-gap-refusal/1",
        "index": index,
        "gap": gap.as_dict(),
    })
    return f"kir:federation-gap-refusal:v1:{digest}"


def _category_rule(category: str, mvp_side: str | None) -> Any:
    rule = H.KIND_TABLE.get(category)
    if rule is None or not rule.eligible:
        raise FederatedClashQueryError(
            f"federated clash geometry has non-eligible category {category!r}")
    if rule.mvp_side != mvp_side:
        raise FederatedClashQueryError(
            f"federated geometry mvp_side contradicts category {category!r}")
    return rule


def _record_occurrence_binding(
    graph: FederatedBuildingGraph,
    occurrence: OccurrenceIdentity,
    record: H.HullRecord,
) -> None:
    if record.source_id != occurrence.key:
        raise FederatedClashQueryError(
            "federated record is not keyed by its exact occurrence")
    graph_node = graph.node(occurrence)
    if record.category != graph_node.node.category:
        raise FederatedClashQueryError(
            "federated record category differs from graph occurrence")
    _category_rule(record.category, record.mvp_side)
    metadata = record.extra.get("federation")
    if not isinstance(metadata, Mapping):
        raise FederatedClashQueryError(
            "federated record lacks source-to-root metadata")
    if (metadata.get("federation_root") != graph.federation_root
            or metadata.get("occurrence_key") != occurrence.key
            or metadata.get("occurrence_identity") != occurrence.as_dict()
            or metadata.get("local_source_id")
            != graph_node.local_element_id):
        raise FederatedClashQueryError(
            "graph and hull record do not share one exact occurrence binding")
    transform_digest = metadata.get("transform_digest")
    if (not isinstance(transform_digest, str) or len(transform_digest) != 64
            or any(char not in "0123456789abcdef"
                   for char in transform_digest)):
        raise FederatedClashQueryError(
            "federated record lacks an exact transform digest")


def _gap_occurrence_binding(
    graph: FederatedBuildingGraph,
    occurrence: OccurrenceIdentity,
    gap: FederationGeometryGap,
) -> None:
    graph_node = graph.node(occurrence)
    if (gap.local_source_id != graph_node.local_element_id
            or gap.category != graph_node.node.category):
        raise FederatedClashQueryError(
            "graph and geometry refusal do not share one occurrence alias")
    _category_rule(gap.category, gap.mvp_side)


@dataclass(frozen=True, slots=True)
class FederatedScopeCensus:
    occurrences: int
    hulled: int
    refusals: Mapping[str, int]

    def __post_init__(self) -> None:
        for name, value in (
            ("occurrences", self.occurrences), ("hulled", self.hulled),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise FederatedClashQueryError(
                    f"federated scope census {name} must be non-negative int")
        if not isinstance(self.refusals, Mapping):
            raise FederatedClashQueryError(
                "federated scope refusals must be a mapping")
        normalized: dict[str, int] = {}
        for reason, count in self.refusals.items():
            if (not isinstance(reason, str) or not reason
                    or isinstance(count, bool) or not isinstance(count, int)
                    or count < 0):
                raise FederatedClashQueryError(
                    "federated scope refusal counts are malformed")
            normalized[reason] = count
        object.__setattr__(
            self, "refusals",
            MappingProxyType(dict(sorted(normalized.items()))))
        if self.occurrences != self.hulled + sum(normalized.values()):
            raise FederatedClashQueryError(
                "federated scope census is not hull-or-refusal balanced")

    @property
    def refused(self) -> int:
        return sum(self.refusals.values())


def _build_snapshot_census(
    records: tuple[H.HullRecord, ...],
    gaps: tuple[tuple[str, FederationGeometryGap], ...],
) -> tuple[clash_snapshot.Census, list[H.Refusal]]:
    census = clash_snapshot.Census()
    refusals: list[H.Refusal] = []
    for record in records:
        _category_rule(record.category, record.mvp_side)
        census.eligible[record.category] += 1
        census.hulled[record.category] += 1
        degeneracy = H.hull_degeneracy(record.hull)
        census.degenerate_hulls[degeneracy] += 1
        if degeneracy != "ok":
            census.degenerate_by_category[record.category][degeneracy] += 1
        if record.mvp_side in H.MVP_PAIR:
            census.mvp_eligible[record.mvp_side] += 1
            census.mvp_hulled[record.mvp_side] += 1
        if H.category_allows_sections(record.category):
            present = bool(
                not isinstance(record.section_radius_mm, bool)
                and isinstance(record.section_radius_mm, (int, float))
                and math.isfinite(float(record.section_radius_mm))
                and float(record.section_radius_mm) > 0.0)
            if present:
                census.section_present[record.category] += 1
            else:
                census.section_absent[record.category] += 1
                census.types_without_section[record.category].add(
                    record.type_name or "__without_type_name__")
            if record.hull_source == "axis_section":
                census.section_hulled[record.category] += 1

    for refusal_id, gap in gaps:
        _category_rule(gap.category, gap.mvp_side)
        reason = f"federation:{gap.reason.value}"
        refusals.append(H.Refusal(
            source_id=refusal_id,
            category=gap.category,
            bucket="missing_geometry",
            reason=reason,
        ))
        census.eligible[gap.category] += 1
        census.missing_geometry[gap.category] += 1
        census.reasons[reason] += 1
        if gap.mvp_side in H.MVP_PAIR:
            census.mvp_eligible[gap.mvp_side] += 1
            census.no_hull_mvp_side[gap.mvp_side] += 1
            census.no_hull_by_category[gap.category] += 1
        if H.category_allows_sections(gap.category):
            if gap.section_present:
                census.section_present[gap.category] += 1
            else:
                census.section_absent[gap.category] += 1
                census.types_without_section[gap.category].add(
                    gap.type_name or "__without_type_name__")
    refusals.sort(key=lambda item: item.source_id)
    return census, refusals


def _federation_coverage(
    graph: FederatedBuildingGraph,
    scope: FederatedScope,
    hulls: FederatedHullSet,
    *,
    graph_digest: str,
    hull_digest: str,
    gaps_with_ids: tuple[tuple[str, FederationGeometryGap], ...],
) -> dict[str, Any]:
    scope_keys = sorted(item.key for item in scope.occurrences)
    hulled = sorted(record.source_id for record in hulls.records)
    refused = sorted(
        gap.occurrence_key for _, gap in gaps_with_ids
        if gap.occurrence_key is not None)
    graph_gaps = [item.to_dict() for item in graph.gaps]
    node_refusals = [item.to_dict() for item in graph.node_refusals]
    graph_refusals = [item.to_dict() for item in graph.graph_refusals]
    source_refusals = [item.to_dict() for item in graph.source_row_refusals]
    incomplete_links = [
        item.to_dict() for item in graph.link_resolutions if not item.satisfied]
    geometry_gaps = [
        {"snapshot_refusal_id": refusal_id, "gap": gap.as_dict()}
        for refusal_id, gap in gaps_with_ids]
    graph_complete = not any((
        graph_gaps, node_refusals, graph_refusals, source_refusals,
        incomplete_links,
    ))
    if graph_complete != graph.complete:
        raise FederatedClashQueryError(
            "federated graph completeness contradicts its named ledgers")
    payload: dict[str, Any] = {
        "schema_version": clash_snapshot.FEDERATION_COVERAGE_SCHEMA,
        "federation_root": graph.federation_root,
        "graph_content_digest": graph_digest,
        "hull_set_content_digest": hull_digest,
        "scope_id": scope.scope_id,
        "scope_occurrences": scope_keys,
        "hulled_occurrences": hulled,
        "geometry_refusal_occurrences": refused,
        "scope_census": {
            "occurrences": len(scope_keys),
            "hulled": len(hulled),
            "refused": len(refused),
        },
        "graph_complete": graph_complete,
        "complete": graph_complete and not geometry_gaps,
        "graph_gaps": graph_gaps,
        "node_refusals": node_refusals,
        "graph_refusals": graph_refusals,
        "source_row_refusals": source_refusals,
        "incomplete_link_resolutions": incomplete_links,
        "geometry_transform_gaps": geometry_gaps,
    }
    return {**payload, "content_digest": _sha256_json(payload)}


def federated_clash_snapshot(
    graph: FederatedBuildingGraph,
    scope: FederatedScope,
    hulls: FederatedHullSet,
) -> clash_snapshot.ClashGeometrySnapshot:
    """Bind one typed graph scope to transformed hulls without local IDs."""

    if not isinstance(graph, FederatedBuildingGraph):
        raise FederatedClashQueryError(
            "federated clash requires FederatedBuildingGraph")
    if not isinstance(scope, FederatedScope):
        raise FederatedClashQueryError(
            "federated clash requires FederatedScope")
    if not isinstance(hulls, FederatedHullSet):
        raise FederatedClashQueryError(
            "federated clash requires FederatedHullSet")
    if hulls.federation_root != graph.federation_root:
        raise FederatedClashQueryError(
            "graph and hulls belong to different federation roots")
    if any(item.federation_root != graph.federation_root
           for item in scope.occurrences):
        raise FederatedClashQueryError(
            "scope contains another federation root")
    unknown = tuple(
        sorted(item.key for item in scope.occurrences if item not in graph.nodes))
    if unknown:
        raise FederatedClashQueryError(
            f"scope contains unassembled occurrences: {unknown}")

    graph_digest = _graph_digest(graph)
    hull_digest = _validated_hull_digest(hulls)
    occurrence_by_key = {item.key: item for item in scope.occurrences}
    record_by_key: dict[str, H.HullRecord] = {}
    for record in hulls.records:
        occurrence = occurrence_by_key.get(record.source_id)
        if occurrence is None:
            raise FederatedClashQueryError(
                "transformed federated hull lies outside scope")
        _record_occurrence_binding(graph, occurrence, record)
        if record.source_id in record_by_key:
            raise FederatedClashQueryError(
                "duplicate transformed occurrence hull")
        record_by_key[record.source_id] = record

    keyed_gap_by_occurrence: dict[str, FederationGeometryGap] = {}
    gaps_with_ids: list[tuple[str, FederationGeometryGap]] = []
    for index, gap in enumerate(hulls.gaps):
        if not isinstance(gap, FederationGeometryGap):
            raise FederatedClashQueryError(
                "federated hull gaps must be typed")
        refusal_id = _gap_refusal_id(gap, index)
        gaps_with_ids.append((refusal_id, gap))
        if gap.occurrence_key is None:
            continue
        occurrence = occurrence_by_key.get(gap.occurrence_key)
        if occurrence is None:
            raise FederatedClashQueryError(
                "keyed federated geometry refusal lies outside scope")
        _gap_occurrence_binding(graph, occurrence, gap)
        if gap.occurrence_key in keyed_gap_by_occurrence:
            raise FederatedClashQueryError(
                "duplicate geometry refusal for one occurrence")
        keyed_gap_by_occurrence[gap.occurrence_key] = gap

    overlap = set(record_by_key).intersection(keyed_gap_by_occurrence)
    accounted = set(record_by_key).union(keyed_gap_by_occurrence)
    scope_keys = set(occurrence_by_key)
    if overlap or accounted != scope_keys:
        raise FederatedClashQueryError(
            "federated scope is not exactly accounted by one hull or one "
            f"named refusal; overlap={sorted(overlap)}, "
            f"missing={sorted(scope_keys - accounted)}")

    ordered_records = tuple(sorted(
        record_by_key.values(), key=lambda item: item.source_id))
    ordered_gaps = tuple(sorted(
        gaps_with_ids, key=lambda item: item[0]))
    census, refusals = _build_snapshot_census(ordered_records, ordered_gaps)
    coverage = _federation_coverage(
        graph, scope, hulls, graph_digest=graph_digest,
        hull_digest=hull_digest, gaps_with_ids=ordered_gaps)
    origin = {
        "adapter": "federated_clash_snapshot/1",
        "federation_root": graph.federation_root,
        "stream_complete": True,
        "elements_in_l0": len(ordered_records) + len(ordered_gaps),
        "header_census_total": len(ordered_records) + len(ordered_gaps),
        "federation_coverage": coverage,
    }
    snapshot = clash_snapshot.ClashGeometrySnapshot(
        list(ordered_records), census, origin, refusals)
    snapshot.validate()
    return snapshot


def federated_assembly_relation_of(
    graph: FederatedBuildingGraph,
    a: OccurrenceIdentity,
    b: OccurrenceIdentity,
) -> str | None:
    """Return only an exact PROVEN federated src-dst assembly relation."""

    if not isinstance(graph, FederatedBuildingGraph):
        raise FederatedClashQueryError(
            "federated assembly lookup requires FederatedBuildingGraph")
    for occurrence in (a, b):
        if not isinstance(occurrence, OccurrenceIdentity):
            raise FederatedClashQueryError(
                "federated assembly lookup forbids local ElementId aliases")
        try:
            graph.node(occurrence)
        except FederationAssemblyError as exc:
            raise FederatedClashQueryError(str(exc)) from exc
    if a == b:
        raise FederatedClashQueryError(
            "federated assembly lookup requires distinct occurrences")
    for src, dst in ((a, b), (b, a)):
        for edge in graph.out_edges(src):
            if (isinstance(edge, FederatedEdge)
                    and edge.relation in _ASSEMBLY_RELATIONS
                    and edge.dst == dst
                    and edge.modality is Modality.PROVEN):
                return edge.relation.value
    return None


def _assembly_uncertainty(
    graph: FederatedBuildingGraph,
    a: OccurrenceIdentity,
    b: OccurrenceIdentity,
) -> tuple[dict[str, Any], ...]:
    subjects = {a, b}
    gaps = []
    for gap in graph.gaps:
        if (gap.source_occurrence in subjects
                and gap.relation in _ASSEMBLY_RELATIONS):
            gaps.append(gap.to_dict())
    return tuple(sorted(
        gaps,
        key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))


class FederatedClashQuery:
    """Stream temporary clash judgements over occurrence identities only."""

    __slots__ = (
        "graph", "scope", "hulls", "snapshot", "census",
        "clash_scope_id", "_pairs", "_classify", "_graph_digest",
        "_hull_digest", "_coverage_digest",
    )

    def __init__(
        self,
        graph: FederatedBuildingGraph,
        scope: FederatedScope,
        hulls: FederatedHullSet,
        *,
        candidate_pairs: Callable[
            [], Iterable[tuple[OccurrenceIdentity, OccurrenceIdentity]]],
        classify: Callable[
            [OccurrenceIdentity, OccurrenceIdentity],
            ClashRelationEdge | None],
        clash_scope_id: str,
    ) -> None:
        if not callable(candidate_pairs) or not callable(classify):
            raise FederatedClashQueryError(
                "candidate_pairs and classify must be callable")
        snapshot = federated_clash_snapshot(graph, scope, hulls)
        # Validate the canonical clash-scope name before storing a query that
        # could later print an invented completeness boundary.
        try:
            clash_detect.completeness_of(snapshot, scope_id=clash_scope_id)
        except ValueError as exc:
            raise FederatedClashQueryError(str(exc)) from exc
        keyed_gaps = tuple(
            gap for gap in hulls.gaps if gap.occurrence_key is not None)
        refusal_counts = collections.Counter(
            gap.reason.value for gap in keyed_gaps)
        self.census = FederatedScopeCensus(
            occurrences=len(scope.occurrences),
            hulled=len(hulls.records),
            refusals=refusal_counts,
        )
        self.graph = graph
        self.scope = scope
        self.hulls = hulls
        self.snapshot = snapshot
        self.clash_scope_id = clash_scope_id
        self._pairs = candidate_pairs
        self._classify = classify
        self._graph_digest = _graph_digest(graph)
        self._hull_digest = _validated_hull_digest(hulls)
        self._coverage_digest = snapshot.origin[
            "federation_coverage"]["content_digest"]

    def _assert_bound(self) -> None:
        if self.graph.federation_root != self.hulls.federation_root:
            raise FederatedClashQueryError(
                "graph and hulls no longer share a federation root")
        if _graph_digest(self.graph) != self._graph_digest:
            raise FederatedClashQueryError(
                "federated graph content changed after query binding")
        if _validated_hull_digest(self.hulls) != self._hull_digest:
            raise FederatedClashQueryError(
                "federated hull-set digest changed after query binding")
        self.snapshot.validate()
        coverage = self.snapshot.origin.get("federation_coverage")
        if (not isinstance(coverage, Mapping)
                or coverage.get("content_digest") != self._coverage_digest):
            raise FederatedClashQueryError(
                "federation coverage changed after query binding")

    def completeness(
        self,
        *,
        candidate_pairs: int | None = None,
        narrow_evaluations: int | None = None,
    ) -> dict[str, Any]:
        self._assert_bound()
        return clash_detect.completeness_of(
            self.snapshot,
            scope_id=self.clash_scope_id,
            candidate_pairs=candidate_pairs,
            narrow_evaluations=narrow_evaluations,
            narrow_refusals={},
        )

    def __iter__(self) -> Iterator[ClashRelationEdge]:
        self._assert_bound()
        previous_pair: tuple[str, str] | None = None
        for candidate in self._pairs():
            if (not isinstance(candidate, (tuple, list))
                    or len(candidate) != 2):
                raise FederatedClashQueryError(
                    "candidate stream must yield exact two-occurrence pairs")
            a, b = candidate
            if (not isinstance(a, OccurrenceIdentity)
                    or not isinstance(b, OccurrenceIdentity)):
                raise FederatedClashQueryError(
                    "candidate stream forbids local ElementId aliases")
            if a == b:
                raise FederatedClashQueryError(
                    "candidate pair cannot address one occurrence twice")
            pair = (a.key, b.key)
            if pair != tuple(sorted(pair)):
                raise FederatedClashQueryError(
                    "candidate pair must use canonical occurrence order")
            if previous_pair is not None and pair <= previous_pair:
                raise FederatedClashQueryError(
                    "candidate stream must be strictly ordered and deduplicated")
            previous_pair = pair
            if a not in self.scope.occurrences or b not in self.scope.occurrences:
                raise FederatedClashQueryError(
                    "candidate pair escapes the exact federated scope")
            assembly = federated_assembly_relation_of(self.graph, a, b)
            uncertainty = _assembly_uncertainty(self.graph, a, b)
            edge = self._classify(a, b)
            if edge is None:
                raise FederatedClashQueryError(
                    "classifier silently dropped a federated candidate")
            if not isinstance(edge, ClashRelationEdge):
                raise FederatedClashQueryError(
                    "classifier must return ClashRelationEdge")
            if (edge.a, edge.b) != pair:
                raise FederatedClashQueryError(
                    "classifier returned swapped or foreign occurrence evidence")
            if assembly is not None and edge.modality is not Modality.REFUTED:
                reserved = {
                    "assembly_from", "was_modality",
                    "assembly_semantic_verdict",
                }
                if reserved.intersection(edge.evidence):
                    raise FederatedClashQueryError(
                        "classifier evidence uses reserved assembly keys")
                edge = ClashRelationEdge(
                    a=edge.a,
                    b=edge.b,
                    relation=edge.relation,
                    modality=Modality.REFUTED,
                    constraint_verdict=ConstraintVerdict.SATISFIED,
                    refuted_by=f"assembly_relation:{assembly}",
                    evidence={
                        **dict(edge.evidence),
                        "assembly_from": "federated_building_graph",
                        "was_modality": edge.modality.value,
                        "assembly_semantic_verdict": "resolved",
                    },
                )
            elif uncertainty:
                reserved = {
                    "assembly_uncertainty", "assembly_semantic_verdict",
                    "constraint_verdict_before_assembly_uncertainty",
                }
                if reserved.intersection(edge.evidence):
                    raise FederatedClashQueryError(
                        "classifier evidence uses reserved assembly keys")
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

    def tally(self) -> dict[str, Any]:
        counter: collections.Counter[str] = collections.Counter()
        counter["scope:nodes"] = self.census.occurrences
        counter["scope:hulled"] = self.census.hulled
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
        return {
            **dict(counter),
            "completeness": self.completeness(
                candidate_pairs=adjudicated,
                narrow_evaluations=adjudicated,
            ),
        }
