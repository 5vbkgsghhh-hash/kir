"""Adversarial construction laws for the local graph trust boundary."""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
    Authority,
    AuthoritySource,
    BuildingGraph,
    Existence,
    GraphBuildError,
    GraphCensus,
    GraphEdge,
    GraphNode,
    Modality,
    Relation,
    graph_from_l0,
)


def _node(node_id: str) -> GraphNode:
    return GraphNode(
        node_id,
        "OST_Walls",
        Authority.DECLARED,
        AuthoritySource.L0_ELEMENT,
        Existence.MATERIALIZED,
    )


def _census(nodes: int, *, refusals=None) -> GraphCensus:
    refusals = {} if refusals is None else refusals
    return GraphCensus(
        rows_seen=nodes + sum(refusals.values()),
        nodes=nodes,
        refusals=refusals,
    )


def _graph(nodes, edges=()) -> BuildingGraph:
    nodes = tuple(nodes)
    return BuildingGraph(
        doc_name="red-team",
        nodes=nodes,
        edges=tuple(edges),
        census=_census(len(nodes)),
    )


class CensusCannotBeRebalancedByMalformedNumbers(unittest.TestCase):
    def test_boolean_and_negative_counts_are_rejected_on_every_axis(self) -> None:
        payloads = (
            {"rows_seen": True, "nodes": 1, "refusals": {}},
            {"rows_seen": 1, "nodes": False, "refusals": {"x": 1}},
            {"rows_seen": 1, "nodes": 2, "refusals": {"x": -1}},
            {"rows_seen": 1, "nodes": 0, "refusals": {"x": True}},
            {"rows_seen": 1, "nodes": 1, "refusals": {"": 0}},
            {"rows_seen": 1, "nodes": 1, "refusals": {7: 0}},
            {"rows_seen": 1, "nodes": 1, "refusals": [],},
            {"rows_seen": 1, "nodes": 1, "refusals": {},
             "identity_authoritative_nodes": True},
            {"rows_seen": 1, "nodes": 1, "refusals": {},
             "identity_incomplete_nodes": False},
            {"rows_seen": 1, "nodes": 1, "refusals": {},
             "identity_context_authoritative": 1},
            {"rows_seen": 1, "nodes": 1, "refusals": {},
             "identity_gaps": {"x": True}},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(GraphBuildError):
                    GraphCensus(**payload)  # type: ignore[arg-type]

    def test_census_mappings_are_snapshotted_and_read_only(self) -> None:
        refusals = {"no_address": 1}
        gaps = {"missing_element_unique_id": 1}
        census = GraphCensus(
            rows_seen=2,
            nodes=1,
            refusals=refusals,
            identity_authoritative_nodes=0,
            identity_incomplete_nodes=1,
            identity_gaps=gaps,
        )
        refusals["no_address"] = 99
        gaps["missing_element_unique_id"] = 99
        self.assertEqual(census.refused, 1)
        self.assertEqual(census.identity_gaps["missing_element_unique_id"], 1)
        with self.assertRaises(TypeError):
            census.refusals["new"] = 1  # type: ignore[index]


class AcceptedEvidenceCannotChangeAfterConstruction(unittest.TestCase):
    def test_node_section_is_a_deep_snapshot(self) -> None:
        section = {"outer": {"samples": [1.0, 2.0]}}
        node = GraphNode(
            "1", "OST_PipeCurves", Authority.DECLARED,
            AuthoritySource.L0_ELEMENT, Existence.MATERIALIZED,
            section=section,
        )
        section["outer"]["samples"].append(999.0)
        self.assertEqual(node.section["outer"]["samples"], (1.0, 2.0))
        with self.assertRaises(TypeError):
            node.section["outer"]["new"] = 1  # type: ignore[index]

    def test_edge_evidence_is_a_deep_snapshot(self) -> None:
        evidence = {"proof": {"steps": ["a", "b"]}}
        edge = GraphEdge(
            Relation.HOSTED_IN, "a", "b", Modality.PROVEN,
            evidence=evidence,
        )
        evidence["proof"]["steps"].append("forged")
        self.assertEqual(edge.evidence["proof"]["steps"], ("a", "b"))
        with self.assertRaises(TypeError):
            edge.evidence["proof"]["new"] = 1  # type: ignore[index]

    def test_graph_node_mapping_is_read_only(self) -> None:
        graph = _graph((_node("a"),))
        with self.assertRaises(TypeError):
            graph.nodes["b"] = _node("b")  # type: ignore[index]


class EndpointAndEdgeTruthLaws(unittest.TestCase):
    def test_ordinary_edge_requires_two_local_nodes(self) -> None:
        with self.assertRaisesRegex(GraphBuildError, "two assembled"):
            _graph(
                (_node("a"),),
                (GraphEdge(Relation.HOSTED_IN, "a", "external",
                           Modality.PROVEN),),
            )
        with self.assertRaisesRegex(GraphBuildError, "two assembled"):
            _graph(
                (_node("b"),),
                (GraphEdge(Relation.BOUNDS_ROOM, "external", "b",
                           Modality.PROVEN),),
            )

    def test_unresolved_requires_exactly_one_local_endpoint_and_a_reason(self) -> None:
        local = _node("local")
        for src, dst in (("local", "also-local"),
                         ("external-a", "external-b")):
            nodes = (local, _node("also-local")) if src == "local" else (local,)
            with self.subTest(src=src, dst=dst):
                with self.assertRaisesRegex(GraphBuildError, "exactly one"):
                    _graph(nodes, (GraphEdge(
                        Relation.HOSTED_IN, src, dst,
                        Modality.UNRESOLVED_TARGET,
                        evidence={"why": "target_not_in_snapshot"}),))
        with self.assertRaisesRegex(GraphBuildError, "evidence.why"):
            _graph((local,), (GraphEdge(
                Relation.HOSTED_IN, "local", "external",
                Modality.UNRESOLVED_TARGET),))

        self.assertEqual(len(_graph((local,), (GraphEdge(
            Relation.HOSTED_IN, "local", "external",
            Modality.UNRESOLVED_TARGET,
            evidence={"why": "target_not_in_snapshot"}),)).edges), 1)
        self.assertEqual(len(_graph((local,), (GraphEdge(
            Relation.BOUNDS_ROOM, "external", "local",
            Modality.UNRESOLVED_TARGET,
            evidence={"why": "boundary_element_not_extracted"}),)).edges), 1)

    def test_hosted_in_link_is_the_only_proven_external_reference(self) -> None:
        local = _node("local")
        link = GraphEdge(
            Relation.HOSTED_IN_LINK, "local", "link-record-7",
            Modality.PROVEN, evidence={"why": "resolved_to_link"})
        self.assertEqual(len(_graph((local,), (link,)).edges), 1)
        # A future graph may represent the link row locally; the typed relation
        # remains unambiguous and must not be rejected merely for being local.
        self.assertEqual(len(_graph(
            (local, _node("link-record-7")), (link,)).edges), 1)
        with self.assertRaisesRegex(GraphBuildError, "local source"):
            _graph((local,), (GraphEdge(
                Relation.HOSTED_IN_LINK, "external", "local",
                Modality.PROVEN),))
        with self.assertRaisesRegex(GraphBuildError, "two assembled"):
            _graph((local,), (GraphEdge(
                Relation.HOSTED_IN_LINK, "local", "external",
                Modality.POSSIBLE),))

    def test_duplicate_or_contradictory_edge_truth_is_rejected(self) -> None:
        edges = (
            GraphEdge(Relation.HOSTED_IN, "a", "b", Modality.PROVEN),
            GraphEdge(Relation.HOSTED_IN, "a", "b", Modality.REFUTED,
                      refuted_by="forged-contradiction"),
        )
        with self.assertRaisesRegex(GraphBuildError, "duplicate"):
            _graph((_node("a"), _node("b")), edges)

    def test_external_door_adjacency_is_unknown_not_refuted(self) -> None:
        graph = graph_from_l0(
            {"doc_name": "t", "levels": [], "rooms": [], "grids": []},
            [{"element_id": "door", "unique_id": "door-uid",
              "category": "OST_Doors", "type_id": "t", "type_name": "T",
              "level_id": None, "host_id": "external-wall", "params": {}}],
        )
        adjacency = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(adjacency), 1)
        self.assertIs(adjacency[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertIsNone(adjacency[0].refuted_by)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
