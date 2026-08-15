"""Federated identity: local ElementId is an alias, never a global key."""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import graph_from_l0, graph_view
from kukai.ir.decompile.identity import (
    DocumentIdentity,
    FederationContext,
    IdentityGap,
    IdentityStatus,
)

HEADER = {"doc_name": "identity-test", "levels": [], "rooms": [], "grids": []}


def _row(element_id: str = "42", unique_id: str | None = "uid-42") -> dict:
    row = {
        "element_id": element_id,
        "category": "OST_Walls",
        "type_id": "t",
        "type_name": "T",
        "level_id": None,
        "host_id": None,
        "params": {},
    }
    if unique_id is not None:
        row["unique_id"] = unique_id
    return row


def _graph(document: str, *, chain: tuple[str, ...] = (),
           root: str = "federation-A", unique_id: str = "uid-42"):
    return graph_from_l0(
        HEADER,
        [_row(unique_id=unique_id)],
        document_identity=DocumentIdentity(document),
        federation_context=FederationContext(root, chain),
    )


class DefinitionAndOccurrenceIdentity(unittest.TestCase):
    def test_same_element_id_in_two_documents_does_not_collide(self) -> None:
        left = _graph("document-A").node("42")
        right = _graph("document-B").node("42")

        # Compatibility alias intentionally stays local and unchanged.
        self.assertEqual(left.node_id, right.node_id)
        self.assertNotEqual(left.definition_identity,
                            right.definition_identity)
        self.assertNotEqual(left.definition_identity.key,
                            right.definition_identity.key)
        self.assertNotEqual(left.occurrence_identity,
                            right.occurrence_identity)
        self.assertTrue(left.identity_authoritative)
        self.assertTrue(right.identity_authoritative)

    def test_one_linked_definition_inserted_twice_has_two_occurrences(self) -> None:
        first_graph = _graph("linked-MEP", chain=("link-instance-A",))
        second_graph = _graph("linked-MEP", chain=("link-instance-B",))
        first = first_graph.node("42")
        second = second_graph.node("42")

        self.assertEqual(first.definition_identity, second.definition_identity)
        self.assertEqual(len({first.definition_identity,
                              second.definition_identity}), 1)
        self.assertEqual(len({first.occurrence_identity,
                              second.occurrence_identity}), 2)
        self.assertIs(
            first_graph.node_for_occurrence(first.occurrence_identity), first)
        self.assertEqual(
            first_graph.nodes_for_definition(first.definition_identity),
            (first,),
        )

    def test_the_entire_nested_link_chain_participates_in_occurrence(self) -> None:
        one = _graph(
            "nested-MEP", chain=("campus-link-A", "mep-link")).node("42")
        two = _graph(
            "nested-MEP", chain=("campus-link-B", "mep-link")).node("42")

        self.assertEqual(one.definition_identity, two.definition_identity)
        self.assertNotEqual(one.occurrence_identity, two.occurrence_identity)
        self.assertEqual(
            one.occurrence_identity.link_instance_chain,
            ("campus-link-A", "mep-link"),
        )
        self.assertNotEqual(one.occurrence_identity.key,
                            two.occurrence_identity.key)


class IncompleteIdentityIsExplicit(unittest.TestCase):
    def test_legacy_l0_remains_readable_but_is_not_authoritative(self) -> None:
        graph = graph_from_l0(HEADER, [_row(unique_id=None)])
        node = graph.node("42")

        self.assertEqual(node.node_id, "42")
        self.assertIsNone(node.definition_identity)
        self.assertIsNone(node.occurrence_identity)
        self.assertIs(node.identity_status, IdentityStatus.INCOMPLETE)
        self.assertIn(IdentityGap.LEGACY_CONTEXT_ABSENT,
                      node.identity_gaps)
        self.assertIn(IdentityGap.MISSING_ELEMENT_UNIQUE_ID,
                      node.identity_gaps)
        self.assertFalse(node.identity_authoritative)
        self.assertFalse(graph.identity_authoritative)
        self.assertEqual(graph.census.identity_authoritative_nodes, 0)
        self.assertEqual(graph.census.identity_incomplete_nodes, 1)
        self.assertGreaterEqual(
            graph.census.identity_gaps[
                IdentityGap.LEGACY_CONTEXT_ABSENT.value], 1)
        self.assertFalse(graph_view(graph).identity_authoritative)

    def test_missing_unique_id_is_named_even_with_complete_context(self) -> None:
        graph = graph_from_l0(
            HEADER,
            [_row(unique_id=None)],
            document_identity=DocumentIdentity("document-A"),
            federation_context=FederationContext("federation-A"),
        )
        node = graph.node("42")
        self.assertEqual(
            node.identity_gaps,
            (IdentityGap.MISSING_ELEMENT_UNIQUE_ID,),
        )
        self.assertFalse(graph.identity_authoritative)
        self.assertTrue(graph.census.identity_context_authoritative)

    def test_definition_can_be_known_while_occurrence_context_is_missing(self) -> None:
        graph = graph_from_l0(
            HEADER,
            [_row()],
            document_identity=DocumentIdentity("document-A"),
        )
        node = graph.node("42")
        self.assertIsNotNone(node.definition_identity)
        self.assertIsNone(node.occurrence_identity)
        self.assertEqual(
            node.identity_gaps,
            (IdentityGap.MISSING_FEDERATION_CONTEXT,),
        )
        self.assertFalse(node.identity_authoritative)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
