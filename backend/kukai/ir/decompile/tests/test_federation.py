"""Authoritative assembly laws for FederatedBuildingGraph."""
from __future__ import annotations

import random
import unittest

from kukai.ir.decompile.building_graph import Relation, graph_from_l0
from kukai.ir.decompile.federation import (
    ExpectedDocumentLinks,
    ExpectedLink,
    ExpectedLinkManifest,
    FederationAssemblyError,
    FederationGapReason,
    LinkExtractionCapability,
    assemble_federation,
)
from kukai.ir.decompile.identity import DocumentIdentity, FederationContext


ROOT = "federation-root"
HEADER = {"doc_name": "same-title", "levels": [], "rooms": [], "grids": []}


def _row(
    element_id: str = "42",
    unique_id: str | None = "definition-42",
    *,
    host_id: str | None = None,
) -> dict:
    row = {
        "element_id": element_id,
        "category": "OST_Walls",
        "type_id": "7",
        "type_name": "Wall",
        "level_id": None,
        "host_id": host_id,
        "params": {},
    }
    if unique_id is not None:
        row["unique_id"] = unique_id
    return row


def _graph(
    document: str,
    chain: tuple[str, ...] = (),
    rows: tuple[dict, ...] = (_row(),),
    *,
    root: str = ROOT,
):
    return graph_from_l0(
        HEADER,
        rows,
        document_identity=DocumentIdentity(document),
        federation_context=FederationContext(root, chain),
    )


def _cover(graph, *links: ExpectedLink) -> ExpectedDocumentLinks:
    assert graph.document_identity is not None
    assert graph.federation_context is not None
    return ExpectedDocumentLinks(
        graph.document_identity,
        graph.federation_context,
        tuple(links),
    )


def _link(
    expectation_id: str,
    instance_unique_id: str | None,
    document: str | None,
    *,
    loaded: bool = True,
    local_id: str | None = None,
) -> ExpectedLink:
    return ExpectedLink(
        expectation_id=expectation_id,
        local_link_element_id=local_id or f"local-{expectation_id}",
        loaded=loaded,
        instance_unique_id=instance_unique_id,
        linked_document_identity=(
            DocumentIdentity(document) if document is not None else None),
    )


def _manifest(*documents: ExpectedDocumentLinks,
              capability=LinkExtractionCapability.DIRECT_ONLY):
    return ExpectedLinkManifest(ROOT, tuple(documents), capability)


class OccurrenceIsTheOnlyGlobalAddress(unittest.TestCase):
    def test_randomized_local_id_collisions_and_order_are_safe(self) -> None:
        rng = random.Random(0x4B4952)
        root = _graph("root-doc", rows=(_row("42", "root-element"),))
        children = []
        expected = []
        coverage = []
        for index in range(40):
            link_uid = f"link-{index:03d}"
            document = f"document-{index:03d}"
            child = _graph(
                document,
                (link_uid,),
                (_row("42", f"element-{rng.randrange(4)}"),),
            )
            children.append(child)
            expected.append(_link(link_uid, link_uid, document))
            coverage.append(_cover(child))
        manifest = _manifest(_cover(root, *expected), *coverage)
        reordered_manifest = _manifest(
            *reversed(coverage), _cover(root, *reversed(expected)))

        graphs = [root, *children]
        rng.shuffle(graphs)
        first = assemble_federation(graphs, manifest=manifest)
        second = assemble_federation(
            reversed(graphs), manifest=reordered_manifest)

        self.assertEqual(len(first.nodes), 41)
        self.assertEqual(
            {node.local_element_id for node in first.nodes.values()}, {"42"})
        self.assertEqual(len({identity.key for identity in first.nodes}), 41)
        self.assertEqual(first.to_json(), second.to_json())
        self.assertTrue(first.complete)
        first.census.assert_balanced()

    def test_lookup_and_scope_reject_local_element_ids(self) -> None:
        root = _graph("root-doc")
        federation = assemble_federation(
            [root], manifest=_manifest(_cover(root)))
        occurrence = next(iter(federation.nodes))

        self.assertEqual(federation.node(occurrence).local_element_id, "42")
        self.assertEqual(
            federation.scope("one", [occurrence]).occurrences,
            frozenset({occurrence}),
        )
        with self.assertRaises(TypeError):
            federation.nodes[occurrence] = (  # type: ignore[index]
                federation.node(occurrence))
        with self.assertRaisesRegex(
                FederationAssemblyError, "OccurrenceIdentity"):
            federation.node("42")  # type: ignore[arg-type]
        with self.assertRaisesRegex(
                FederationAssemblyError, "local ElementId"):
            federation.scope("wrong", ["42"])  # type: ignore[list-item]

    def test_local_edges_are_qualified_inside_their_own_graph_only(self) -> None:
        root = _graph(
            "root-doc", rows=(
                _row("1", "wall"),
                _row("2", "door", host_id="1"),
            ))
        child = _graph(
            "child-doc", ("link-A",), rows=(
                _row("1", "other-wall"),
                _row("2", "other-door", host_id="1"),
            ))
        manifest = _manifest(
            _cover(root, _link("link-A", "link-A", "child-doc")),
            _cover(child),
        )
        federation = assemble_federation([root, child], manifest=manifest)

        self.assertEqual(len(federation.edges), 2)
        for edge in federation.edges:
            self.assertEqual(edge.src.link_instance_chain,
                             edge.dst.link_instance_chain)
            self.assertIs(edge.relation, Relation.HOSTED_IN)
        self.assertNotEqual(federation.edges[0].src,
                            federation.edges[1].src)


class DefinitionIndexAndPathLaws(unittest.TestCase):
    def test_one_definition_has_two_link_occurrences(self) -> None:
        root = _graph("root-doc", rows=(_row("1", "root"),))
        first = _graph("shared-doc", ("link-A",))
        second = _graph("shared-doc", ("link-B",))
        manifest = _manifest(
            _cover(
                root,
                _link("A", "link-A", "shared-doc"),
                _link("B", "link-B", "shared-doc"),
            ),
            _cover(first),
            _cover(second),
        )
        federation = assemble_federation(
            [second, root, first], manifest=manifest)
        definition = first.node("42").definition_identity
        assert definition is not None

        occurrences = federation.occurrences_for_definition(definition)
        self.assertEqual(len(occurrences), 2)
        self.assertEqual(
            {item.link_instance_chain for item in occurrences},
            {("link-A",), ("link-B",)},
        )

    def test_different_roots_are_rejected(self) -> None:
        root = _graph("root-doc")
        alien = _graph("alien", ("link",), root="another-root")
        with self.assertRaisesRegex(
                FederationAssemblyError, "different federation roots"):
            assemble_federation(
                [root, alien], manifest=_manifest(_cover(root)))

    def test_duplicate_document_occurrence_path_is_rejected(self) -> None:
        one = _graph("doc-A")
        two = _graph("doc-B")
        with self.assertRaisesRegex(
                FederationAssemblyError, "duplicate document occurrence path"):
            assemble_federation([one, two], manifest=_manifest(_cover(one)))

    def test_duplicate_expected_path_is_rejected(self) -> None:
        root = _graph("root-doc")
        with self.assertRaisesRegex(
                FederationAssemblyError, "duplicate expected link occurrence"):
            _manifest(_cover(
                root,
                _link("first", "same-instance", "doc-A"),
                _link("second", "same-instance", "doc-B"),
            ))


class AccountingAndGaps(unittest.TestCase):
    def test_upstream_row_refusal_is_retained_and_two_stage_census_balances(
            self) -> None:
        first = _row("42", "definition-A")
        duplicate_local_address = _row("42", "definition-B")
        root = _graph(
            "root-doc", rows=(first, duplicate_local_address))
        federation = assemble_federation(
            [root], manifest=_manifest(_cover(root)))

        self.assertEqual(federation.census.input_rows, 2)
        self.assertEqual(federation.census.input_nodes, 1)
        self.assertEqual(federation.census.source_refused_rows, 1)
        self.assertEqual(
            federation.census.input_rows,
            federation.census.input_nodes
            + federation.census.source_refused_rows,
        )
        self.assertEqual(len(federation.source_row_refusals), 1)
        self.assertEqual(federation.source_row_refusals[0].count, 1)
        self.assertFalse(federation.complete)

    def test_incomplete_occurrence_is_refused_and_balanced(self) -> None:
        root = _graph("root-doc", rows=(_row(unique_id=None),))
        federation = assemble_federation(
            [root], manifest=_manifest(_cover(root)))

        self.assertEqual(len(federation.nodes), 0)
        self.assertEqual(len(federation.node_refusals), 1)
        self.assertFalse(federation.complete)
        self.assertEqual(federation.census.input_nodes, 1)
        self.assertEqual(
            federation.census.input_nodes,
            federation.census.assembled_nodes
            + federation.census.refused_nodes,
        )

    def test_unresolved_edge_retains_occurrence_and_local_target(
            self) -> None:
        root = _graph(
            "root-doc", rows=(_row("1", "source", host_id="missing"),))
        # A matching local alias in another document is deliberately not a
        # candidate: local endpoints never cross a per-document graph.
        child = _graph(
            "child-doc", ("link-A",),
            rows=(_row("missing", "unrelated-target"),))
        federation = assemble_federation(
            [root, child],
            manifest=_manifest(
                _cover(root, _link("child", "link-A", "child-doc")),
                _cover(child),
            ),
        )

        self.assertEqual(len(federation.edges), 0)
        edge_gaps = [gap for gap in federation.gaps
                     if gap.relation is Relation.HOSTED_IN]
        self.assertEqual(len(edge_gaps), 1)
        gap = edge_gaps[0]
        self.assertIsNotNone(gap.source_occurrence)
        self.assertIsNone(gap.target_occurrence)
        self.assertEqual(gap.local_source, "1")
        self.assertEqual(gap.local_target, "missing")
        self.assertEqual(
            gap.reason, FederationGapReason.EDGE_TARGET_NOT_IN_GRAPH)
        self.assertEqual(federation.census.input_edges, 1)
        self.assertEqual(federation.census.edge_gaps, 1)
        self.assertFalse(federation.complete)

    def test_graph_without_context_is_named_not_silently_merged(self) -> None:
        legacy = graph_from_l0(HEADER, [_row()])
        authoritative = _graph("root-doc", rows=())
        federation = assemble_federation(
            [authoritative, legacy],
            manifest=_manifest(_cover(authoritative)),
        )
        self.assertEqual(federation.census.input_graphs, 2)
        self.assertEqual(federation.census.assembled_graphs, 1)
        self.assertEqual(federation.census.refused_graphs, 1)
        self.assertEqual(len(federation.graph_refusals), 1)
        self.assertFalse(federation.complete)


class ExpectedLinkManifestLaws(unittest.TestCase):
    def test_authority_join_binds_local_alias_uid_path_and_documents(self) -> None:
        root = _graph("root-doc", rows=())
        same_linked_document = DocumentIdentity("shared-doc")
        manifest = _manifest(_cover(
            root,
            _link("left", "instance-A", "shared-doc", local_id="100"),
            _link("right", "instance-B", "shared-doc", local_id="101"),
        ))

        self.assertEqual(manifest.census.to_dict(), {
            "records": 2,
            "local_aliases": 2,
            "authority_bindings": 2,
            "unbound_records": 0,
        })
        left = manifest.authority_binding(
            parent_document_identity=DocumentIdentity("root-doc"),
            parent_context=FederationContext(ROOT, ()),
            local_link_element_id="100",
            link_instance_unique_id="instance-A",
            linked_document_identity=same_linked_document,
        )
        right = manifest.authority_binding(
            parent_document_identity=DocumentIdentity("root-doc"),
            parent_context=FederationContext(ROOT, ()),
            local_link_element_id="101",
            link_instance_unique_id="instance-B",
            linked_document_identity=same_linked_document,
        )
        self.assertNotEqual(left.key, right.key)
        self.assertEqual(
            left.child_context.link_instance_chain, ("instance-A",))
        self.assertEqual(left.transform_subject(), {
            "source_document_key": "shared-doc",
            "target_document_key": "root-doc",
            "link_instance_chain": ["instance-A"],
            "target_link_instance_chain": [],
        })
        left.assert_transform_subject(left.transform_subject())
        with self.assertRaisesRegex(
                FederationAssemblyError, "does not match"):
            right.assert_transform_subject(left.transform_subject())
        with self.assertRaisesRegex(
                FederationAssemblyError, "no exact link authority"):
            manifest.authority_binding(
                parent_document_identity=DocumentIdentity("root-doc"),
                parent_context=FederationContext(ROOT, ()),
                local_link_element_id="100",
                link_instance_unique_id="instance-B",
                linked_document_identity=same_linked_document,
            )

    def test_duplicate_local_link_alias_in_one_parent_is_rejected(self) -> None:
        root = _graph("root-doc", rows=())
        with self.assertRaisesRegex(
                FederationAssemblyError, "duplicate local link ElementId"):
            _cover(
                root,
                _link("left", "instance-A", "doc-A", local_id="100"),
                _link("right", "instance-B", "doc-B", local_id="100"),
            )

    def test_incomplete_link_still_balances_record_and_local_alias(self) -> None:
        root = _graph("root-doc", rows=())
        manifest = _manifest(_cover(
            root, _link("unknown", None, None, local_id="100")))
        self.assertEqual(manifest.census.to_dict(), {
            "records": 1,
            "local_aliases": 1,
            "authority_bindings": 0,
            "unbound_records": 1,
        })

    def test_unloaded_missing_identity_and_missing_path_are_distinct(self) -> None:
        root = _graph("root-doc")
        manifest = _manifest(_cover(
            root,
            _link("unloaded", "link-U", None, loaded=False),
            _link("missing-path", None, "child-P"),
            _link("missing-identity", "link-I", None),
        ))
        federation = assemble_federation([root], manifest=manifest)
        reasons = {gap.reason for gap in federation.gaps}

        self.assertIn(FederationGapReason.EXPECTED_LINK_UNLOADED, reasons)
        self.assertIn(
            FederationGapReason.EXPECTED_LINK_IDENTITY_MISSING, reasons)
        self.assertIn(FederationGapReason.EXPECTED_LINK_PATH_MISSING, reasons)
        self.assertEqual(federation.census.expected_links, 3)
        self.assertEqual(federation.census.satisfied_links, 0)
        self.assertEqual(federation.census.incomplete_links, 3)
        self.assertFalse(federation.complete)

    def test_loaded_link_without_child_graph_is_incomplete(self) -> None:
        root = _graph("root-doc")
        federation = assemble_federation(
            [root],
            manifest=_manifest(_cover(
                root, _link("missing-child", "link-A", "child-doc"))),
        )
        self.assertIn(
            FederationGapReason.EXPECTED_LINK_GRAPH_MISSING,
            {gap.reason for gap in federation.gaps},
        )
        self.assertFalse(federation.complete)

    def test_nested_chain_works_and_direct_extractor_gap_is_named(self) -> None:
        root = _graph("root-doc", rows=())
        parent = _graph("parent-doc", ("link-A",), rows=())
        manifest = _manifest(
            _cover(root, _link("direct", "link-A", "parent-doc")),
            _cover(parent, _link("nested", "link-B", "nested-doc")),
            capability=LinkExtractionCapability.DIRECT_ONLY,
        )
        federation = assemble_federation([root, parent], manifest=manifest)

        nested = next(item for item in federation.link_resolutions
                      if item.expectation_id == "nested")
        self.assertEqual(
            nested.child_context.link_instance_chain,
            ("link-A", "link-B"),
        )
        self.assertIn(
            FederationGapReason.EXTRACTOR_DIRECT_LINK_ONLY,
            nested.reasons,
        )
        self.assertEqual(federation.summary().max_link_depth, 1)
        self.assertFalse(federation.complete)

    def test_unexpected_orphan_graph_path_is_a_named_gap(self) -> None:
        root = _graph("root-doc", rows=())
        orphan = _graph("orphan", ("unmanifested",), rows=())
        federation = assemble_federation(
            [root, orphan],
            manifest=_manifest(_cover(root), _cover(orphan)),
        )
        self.assertIn(
            FederationGapReason.GRAPH_PATH_NOT_EXPECTED,
            {gap.reason for gap in federation.gaps},
        )
        self.assertFalse(federation.complete)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
