"""Adversarial laws for assembling occurrence-keyed federation evidence."""
from __future__ import annotations

from dataclasses import replace

import pytest

from kukai.ir.decompile.building_graph import Modality, Relation, graph_from_l0
from kukai.ir.decompile.federation import (
    ExpectedDocumentLinks,
    ExpectedLink,
    ExpectedLinkManifest,
    ExpectedLinkResolution,
    FederatedBuildingGraph,
    FederatedEdge,
    FederatedNode,
    FederationAssemblyError,
    FederationCensus,
    FederationGap,
    FederationGapReason,
    FederationGapScope,
    FederationGraphRefusal,
    FederationNodeRefusal,
    FederationRefusalReason,
    FederationSourceRowRefusal,
    assemble_federation,
)
from kukai.ir.decompile.identity import (
    DocumentIdentity,
    FederationContext,
)


ROOT = "root-authority"
HEADER = {"doc_name": "red-team", "levels": [], "rooms": [], "grids": []}


def _row(element_id: str, unique_id: str, *, host_id=None, category="OST_Walls"):
    return {
        "element_id": element_id,
        "unique_id": unique_id,
        "category": category,
        "type_id": "t",
        "type_name": "T",
        "level_id": None,
        "host_id": host_id,
        "params": {},
    }


def _graph(document: str, chain=(), rows=()):
    return graph_from_l0(
        HEADER,
        rows,
        document_identity=DocumentIdentity(document),
        federation_context=FederationContext(ROOT, chain),
    )


def _cover(graph, *links):
    return ExpectedDocumentLinks(
        graph.document_identity,
        graph.federation_context,
        tuple(links),
    )


def _manifest(*documents):
    return ExpectedLinkManifest(ROOT, tuple(documents))


def _clone(federation, **overrides):
    values = {
        "federation_root": federation.federation_root,
        "manifest": federation.manifest,
        "graph_paths": federation.graph_paths,
        "nodes": federation.nodes.values(),
        "edges": federation.edges,
        "gaps": federation.gaps,
        "node_refusals": federation.node_refusals,
        "graph_refusals": federation.graph_refusals,
        "source_row_refusals": federation.source_row_refusals,
        "link_resolutions": federation.link_resolutions,
        "census": federation.census,
    }
    values.update(overrides)
    return FederatedBuildingGraph(**values)


class TestFederationEvidenceTypes:
    @pytest.mark.parametrize("value", [True, -1, 1.5, "1"])
    def test_census_rejects_non_count_values(self, value) -> None:
        with pytest.raises(FederationAssemblyError):
            FederationCensus(
                input_graphs=value,
                assembled_graphs=0,
                refused_graphs=0,
                input_rows=0,
                source_refused_rows=0,
                input_nodes=0,
                assembled_nodes=0,
                refused_nodes=0,
                input_edges=0,
                assembled_edges=0,
                edge_gaps=0,
                expected_links=0,
                satisfied_links=0,
                incomplete_links=0,
            )

    def test_refusal_records_cannot_carry_negative_or_vacuous_evidence(self) -> None:
        with pytest.raises(FederationAssemblyError, match="graph_index"):
            FederationNodeRefusal(
                FederationRefusalReason.GRAPH_CONTEXT_INCOMPLETE,
                True, None, "42", ("legacy_context_absent",))
        with pytest.raises(FederationAssemblyError, match="identity gaps"):
            FederationNodeRefusal(
                FederationRefusalReason.GRAPH_CONTEXT_INCOMPLETE,
                0, None, "42", ())
        with pytest.raises(FederationAssemblyError, match="exact graph path"):
            FederationNodeRefusal(
                FederationRefusalReason.NODE_OCCURRENCE_INCOMPLETE,
                0, None, "42", ("missing_element_unique_id",))
        with pytest.raises(FederationAssemblyError, match="reason"):
            FederationGraphRefusal(
                FederationRefusalReason.NODE_OCCURRENCE_INCOMPLETE,
                0, "doc", 1, 0)
        with pytest.raises(FederationAssemblyError, match="non-negative"):
            FederationGraphRefusal(
                FederationRefusalReason.GRAPH_CONTEXT_INCOMPLETE,
                0, "doc", -1, 0)
        with pytest.raises(FederationAssemblyError, match="positive"):
            FederationSourceRowRefusal(0, (), "doc", "bad_row", 0)

    def test_gap_scope_and_reason_cannot_be_cross_wired(self) -> None:
        with pytest.raises(FederationAssemblyError, match="non-edge reason"):
            FederationGap(
                FederationGapScope.EDGE,
                FederationGapReason.EXPECTED_LINK_UNLOADED,
                graph_path=(),
                relation=Relation.HOSTED_IN,
                local_source="a",
                local_target="b",
            )
        with pytest.raises(FederationAssemblyError, match="non-manifest reason"):
            FederationGap(
                FederationGapScope.MANIFEST,
                FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH,
                graph_path=(),
            )

    def test_gap_occurrence_must_belong_to_its_exact_path(self) -> None:
        graph = _graph("root", (), (_row("1", "u1"),))
        occurrence = graph.node("1").occurrence_identity
        assert occurrence is not None
        with pytest.raises(FederationAssemblyError, match="exact graph path"):
            FederationGap(
                FederationGapScope.EDGE,
                FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH,
                graph_path=("different-link",),
                source_occurrence=occurrence,
                relation=Relation.HOSTED_IN,
                local_source="1",
                local_target="external",
            )

    def test_unloaded_link_cannot_mint_transform_authority(self) -> None:
        root = _graph("root")
        manifest = _manifest(_cover(root, ExpectedLink(
            "stale", "100", False, "instance-uid",
            DocumentIdentity("linked-doc"))))
        assert manifest.authority_bindings == ()
        assert manifest.census.authority_bindings == 0
        assert manifest.census.unbound_records == 1


class TestFederatedAssemblyCannotDoubleCountTruth:
    def test_duplicate_or_contradictory_edge_key_is_rejected(self) -> None:
        root = _graph(
            "root", (),
            (_row("a", "ua"), _row("b", "ub", host_id="a")),
        )
        federation = assemble_federation(
            (root,), manifest=_manifest(_cover(root)))
        original = federation.edges[0]
        contradiction = FederatedEdge(
            original.relation,
            original.src,
            original.dst,
            Modality.POSSIBLE,
            evidence={"forged": True},
        )
        census = replace(
            federation.census, input_edges=2, assembled_edges=2)
        with pytest.raises(FederationAssemblyError, match="edge truth"):
            _clone(
                federation,
                edges=(original, contradiction),
                census=census,
            )

    def test_federated_node_cannot_relabel_its_local_alias(self) -> None:
        root = _graph("root", (), (_row("1", "u1"),))
        federation = assemble_federation(
            (root,), manifest=_manifest(_cover(root)))
        node = next(iter(federation.nodes.values()))
        with pytest.raises(FederationAssemblyError, match="local alias"):
            FederatedNode(
                node.occurrence, "forged-local-id", node.document_name,
                node.node)

    def test_resolution_cannot_swap_link_authority_bindings(self) -> None:
        root = _graph("root")
        left = _graph("shared", ("left-uid",))
        right = _graph("shared", ("right-uid",))
        left_link = ExpectedLink(
            "left", "100", True, "left-uid", DocumentIdentity("shared"))
        right_link = ExpectedLink(
            "right", "101", True, "right-uid", DocumentIdentity("shared"))
        federation = assemble_federation(
            (root, left, right),
            manifest=_manifest(
                _cover(root, left_link, right_link),
                _cover(left),
                _cover(right),
            ),
        )
        resolutions = list(federation.link_resolutions)
        assert len(resolutions) == 2
        swapped = (
            replace(
                resolutions[0],
                authority_binding_key=resolutions[1].authority_binding_key),
            replace(
                resolutions[1],
                authority_binding_key=resolutions[0].authority_binding_key),
        )
        with pytest.raises(FederationAssemblyError, match="binding was swapped"):
            _clone(federation, link_resolutions=swapped)


class TestExternalLocalEdgesBecomeOnlyTypedGaps:
    def test_unresolved_target_never_becomes_cross_document_topology(self) -> None:
        root = _graph(
            "root", (), (_row("fixture", "uf", host_id="wall-42"),))
        child = _graph("child", ("link",), (_row("wall-42", "uw"),))
        manifest = _manifest(
            _cover(root, ExpectedLink(
                "child", "link-local", True, "link",
                DocumentIdentity("child"))),
            _cover(child),
        )
        federation = assemble_federation((root, child), manifest=manifest)
        gaps = [gap for gap in federation.gaps
                if gap.relation is Relation.HOSTED_IN]
        assert len(gaps) == 1
        assert gaps[0].reason is FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH
        assert gaps[0].source_occurrence is not None
        assert gaps[0].target_occurrence is None
        assert federation.edges == ()

    def test_external_room_boundary_preserves_the_other_endpoint(self) -> None:
        header = {
            **HEADER,
            "rooms": [{"id": "room", "bounding_element_ids": ["external"]}],
        }
        root = graph_from_l0(
            header,
            (_row("room", "ur", category="OST_Rooms"),),
            document_identity=DocumentIdentity("root"),
            federation_context=FederationContext(ROOT, ()),
        )
        federation = assemble_federation(
            (root,), manifest=_manifest(_cover(root)))
        gap = next(gap for gap in federation.gaps
                   if gap.relation is Relation.BOUNDS_ROOM)
        assert gap.reason is FederationGapReason.EDGE_SOURCE_NOT_IN_GRAPH
        assert gap.source_occurrence is None
        assert gap.target_occurrence is not None
        assert federation.edges == ()

    def test_proven_link_reference_is_still_a_gap_not_a_global_edge(self) -> None:
        root = graph_from_l0(
            HEADER,
            (_row("fixture", "uf", host_id="link-row"),),
            document_identity=DocumentIdentity("root"),
            federation_context=FederationContext(ROOT, ()),
            link_ids=("link-row",),
        )
        federation = assemble_federation(
            (root,), manifest=_manifest(_cover(root)))
        gap = next(gap for gap in federation.gaps
                   if gap.relation is Relation.HOSTED_IN_LINK)
        assert gap.reason is FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH
        assert gap.source_occurrence is not None
        assert federation.edges == ()


def test_local_clash_query_cannot_silently_consume_a_federated_graph() -> None:
    from kukai.ir.decompile.graph_clash_query import (
        ClashQuery,
        ClashScope,
        ScopeCensus,
    )

    root = _graph("root", (), (_row("1", "u1"),))
    federation = assemble_federation(
        (root,), manifest=_manifest(_cover(root)))
    with pytest.raises(Exception, match="local-only"):
        ClashQuery(
            federation,  # type: ignore[arg-type]
            ClashScope("wrong-address-space", frozenset({"1"})),
            candidate_pairs=lambda: (),
            classify=lambda _a, _b: None,
            census=ScopeCensus(1, 1, {}),
        )
