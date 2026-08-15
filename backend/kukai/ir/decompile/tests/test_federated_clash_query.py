"""Adversarial laws for the occurrence-keyed federated clash boundary."""
from __future__ import annotations

import copy

import pytest

from kukai.clash import geom as G
from kukai.clash import hulls as H
from kukai.clash.federation_transform import (
    HullFederationSource,
    federate_hulls,
)
from kukai.clash.snapshot import SnapshotIntegrityError
from kukai.ir.decompile.building_graph import Modality, graph_from_l0
from kukai.ir.decompile.federated_clash_query import (
    FederatedClashQuery,
    FederatedClashQueryError,
    federated_clash_snapshot,
)
from kukai.ir.decompile.federation import (
    ExpectedDocumentLinks,
    ExpectedLinkManifest,
    LinkExtractionCapability,
    assemble_federation,
)
from kukai.ir.decompile.graph_clash_query import (
    ClashRelation,
    ClashRelationEdge,
    ConstraintVerdict,
)
from kukai.ir.decompile.identity import (
    DocumentIdentity,
    FederationContext,
    OccurrenceIdentity,
)
from kukai.ir.decompile.schema import (
    FederationTransformEvidence,
    FederationTransformSubject,
)


ROOT = "revit:cloud:root"
HEADER = {"doc_name": "root", "levels": [], "rooms": [], "grids": []}
IDENTITY = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


def _row(
    local_id: str,
    unique_id: str,
    category: str,
    *,
    host_id: str | None = None,
) -> dict:
    return {
        "element_id": local_id,
        "unique_id": unique_id,
        "category": category,
        "type_id": "type",
        "type_name": "T",
        "level_id": None,
        "host_id": host_id,
        "params": {},
    }


def _federation(*, unresolved_host: bool = False, assembly: bool = False):
    host = "missing" if unresolved_host else ("2" if assembly else None)
    graph = graph_from_l0(
        HEADER,
        (
            _row("1", "duct-uid", "OST_DuctCurves", host_id=host),
            _row("2", "wall-uid", "OST_Walls"),
        ),
        document_identity=DocumentIdentity("root-document"),
        federation_context=FederationContext(ROOT, ()),
    )
    manifest = ExpectedLinkManifest(
        ROOT,
        (ExpectedDocumentLinks(
            graph.document_identity,
            graph.federation_context,
            (),
        ),),
        LinkExtractionCapability.DIRECT_ONLY,
    )
    return assemble_federation((graph,), manifest=manifest)


def _transform(occurrence: OccurrenceIdentity, *, root: str = ROOT):
    return FederationTransformEvidence.from_bridge_dict({
        "matrix": list(IDENTITY),
        "status": "authoritative",
        "gaps": [],
        "target_frame": "federation_root",
    }, subject_context=FederationTransformSubject(
        source_document_key=occurrence.definition.document.value,
        target_document_key=root,
        link_instance_chain=occurrence.link_instance_chain,
        target_link_instance_chain=(),
    ))


def _record(local_id: str, *, category: str, side: str) -> H.HullRecord:
    lo = 0.0 if local_id == "1" else 5.0
    return H.HullRecord(
        source_id=local_id,
        category=category,
        label="duct" if side == "mep" else "wall",
        mvp_side=side,
        hull=G.Aabb((lo, 0.0, 0.0), (lo + 10.0, 10.0, 10.0)),
        grade="coarse",
        hull_source="bbox",
        type_name="T",
    )


def _hulls(
    federation,
    *,
    include: tuple[str, ...] = ("1", "2"),
    missing_transform_for: str | None = None,
    root: str = ROOT,
):
    by_local = {
        node.local_element_id: occurrence
        for occurrence, node in federation.nodes.items()
    }
    sources = []
    for local_id in include:
        occurrence = by_local[local_id]
        category, side = (
            ("OST_DuctCurves", "mep") if local_id == "1"
            else ("OST_Walls", "struct"))
        sources.append(HullFederationSource(
            source=f"source:{local_id}",
            records=(_record(local_id, category=category, side=side),),
            occurrence_by_local_id={local_id: occurrence},
            source_to_root=(
                None if local_id == missing_transform_for
                else _transform(occurrence, root=root)),
        ))
    return federate_hulls(tuple(sources), federation_root=root)


def _possible(a: OccurrenceIdentity, b: OccurrenceIdentity):
    return ClashRelationEdge(
        a.key,
        b.key,
        ClashRelation.OVERLAP,
        Modality.POSSIBLE,
        constraint_verdict=ConstraintVerdict.POSSIBLE_VIOLATION,
        evidence={"classifier": "fixture"},
    )


def _ordered_pair(federation):
    return tuple(sorted(federation.nodes, key=lambda item: item.key))


def _query(federation, hulls, *, pairs):
    scope = federation.scope("mvp-root", federation.nodes)
    return FederatedClashQuery(
        federation,
        scope,
        hulls,
        candidate_pairs=lambda: pairs,
        classify=_possible,
        clash_scope_id="mvp_v2",
    )


def test_graph_and_hulls_must_bind_the_same_federation_root() -> None:
    federation = _federation()
    hulls = _hulls(federation)
    object.__setattr__(hulls, "federation_root", "alien-root")
    with pytest.raises(FederatedClashQueryError, match="federation root"):
        federated_clash_snapshot(
            federation,
            federation.scope("all", federation.nodes),
            hulls,
        )


def test_scope_denominator_rejects_missing_and_extra_transformed_hulls() -> None:
    federation = _federation()
    all_scope = federation.scope("all", federation.nodes)
    with pytest.raises(FederatedClashQueryError, match="not exactly accounted"):
        federated_clash_snapshot(
            federation, all_scope, _hulls(federation, include=("1",)))

    one = min(federation.nodes, key=lambda item: item.key)
    one_scope = federation.scope("one", (one,))
    with pytest.raises(FederatedClashQueryError, match="outside scope"):
        federated_clash_snapshot(
            federation, one_scope, _hulls(federation))


def test_swapped_occurrence_pair_is_rejected_before_classification() -> None:
    federation = _federation()
    hulls = _hulls(federation)
    a, b = _ordered_pair(federation)
    called = False

    def classify(left, right):
        nonlocal called
        called = True
        return _possible(left, right)

    query = FederatedClashQuery(
        federation,
        federation.scope("all", federation.nodes),
        hulls,
        candidate_pairs=lambda: ((b, a),),
        classify=classify,
        clash_scope_id="mvp_v2",
    )
    with pytest.raises(FederatedClashQueryError, match="canonical"):
        list(query)
    assert called is False


def test_unresolved_external_host_is_uncertainty_never_false_refutation() -> None:
    federation = _federation(unresolved_host=True)
    a, b = _ordered_pair(federation)
    query = _query(federation, _hulls(federation), pairs=((a, b),))

    edge = list(query)[0]
    assert edge.modality is Modality.POSSIBLE
    assert edge.constraint_verdict is ConstraintVerdict.POSSIBLE_VIOLATION
    assert edge.refuted_by is None
    assert edge.evidence["assembly_semantic_verdict"] == "unresolved"
    assert edge.evidence["assembly_uncertainty"]
    assert query.completeness()["axes"]["federation"]["complete"] is False


def test_exact_proven_federated_assembly_edge_alone_refutes() -> None:
    federation = _federation(assembly=True)
    a, b = _ordered_pair(federation)
    edge = list(_query(
        federation, _hulls(federation), pairs=((a, b),)))[0]
    assert edge.modality is Modality.REFUTED
    assert edge.constraint_verdict is ConstraintVerdict.SATISFIED
    assert edge.refuted_by == "assembly_relation:hosted_in"
    assert edge.evidence["assembly_from"] == "federated_building_graph"


def test_geometry_gap_with_zero_candidates_survives_completeness() -> None:
    federation = _federation()
    hulls = _hulls(federation, missing_transform_for="2")
    query = _query(federation, hulls, pairs=())

    tally = query.tally()
    completeness = tally["completeness"]
    assert tally["scope:nodes"] == 2
    assert tally["scope:hulled"] == 1
    assert tally["scope_refusal:missing_transform"] == 1
    assert tally["candidates:adjudicated"] == 0
    assert completeness["complete"] is False
    assert completeness["axes"]["query_scope"]["complete"] is True
    assert completeness["axes"]["geometry"]["complete"] is False
    federation_axis = completeness["axes"]["federation"]
    assert federation_axis["complete"] is False
    assert federation_axis["geometry_transform_gaps"][0]["gap"][
        "reason"] == "missing_transform"


def test_green_requires_exact_scope_accounting_and_zero_federation_gaps() -> None:
    federation = _federation()
    query = _query(federation, _hulls(federation), pairs=())
    completeness = query.tally()["completeness"]
    assert completeness["complete"] is True
    assert completeness["axes"]["federation"]["scope_census"] == {
        "occurrences": 2,
        "hulled": 2,
        "refused": 0,
    }


def test_snapshot_coverage_digest_and_live_hull_digest_fail_closed() -> None:
    federation = _federation()
    hulls = _hulls(federation)
    scope = federation.scope("all", federation.nodes)
    snapshot = federated_clash_snapshot(federation, scope, hulls)

    forged = copy.deepcopy(snapshot.origin["federation_coverage"])
    forged["complete"] = not forged["complete"]
    snapshot.origin["federation_coverage"] = forged
    with pytest.raises(SnapshotIntegrityError, match="digest"):
        snapshot.validate()

    clean_hulls = _hulls(federation)
    query = _query(federation, clean_hulls, pairs=())
    object.__setattr__(clean_hulls, "content_digest", "0" * 64)
    with pytest.raises(FederatedClashQueryError, match="hull-set digest"):
        list(query)
