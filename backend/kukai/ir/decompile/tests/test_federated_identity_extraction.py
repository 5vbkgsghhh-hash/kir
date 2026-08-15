"""Production extraction seam for federated graph identity."""
from __future__ import annotations

import unittest
from random import Random

from kukai.ir.decompile.building_graph import graph_from_l0
from kukai.ir.decompile.extract import (
    EXTRACT_CATEGORIES,
    _parse_metadata,
    build_category_batch_cs,
    build_metadata_cs,
)
from kukai.ir.decompile.identity import (
    CLOUD_PROJECT_MODEL_GUID,
    PROJECT_INFORMATION_UNIQUE_ID,
    REVIT_SERVER_CENTRAL_GUID,
    DocumentIdentity,
    FederationContext,
    IdentityGap,
    IdentityStatus,
    identity_context_from_l0,
)
from kukai.ir.decompile.schema import (
    DocumentIdentityFact,
    L0Element,
    L0IdentityMetadata,
    L0LinkIdentity,
    L0SourceKind,
    LinkSummary,
)
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


def _fact(value: str) -> DocumentIdentityFact:
    return DocumentIdentityFact(REVIT_SERVER_CENTRAL_GUID, value)


def _lineage_fact(value: str) -> DocumentIdentityFact:
    return DocumentIdentityFact(PROJECT_INFORMATION_UNIQUE_ID, value)


def _root_header(project_uid: str) -> dict:
    identity = L0IdentityMetadata(
        source_kind=L0SourceKind.ROOT,
        document_identity=_fact(project_uid),
        federation_root_identity=_fact(project_uid),
        link_instance_chain=(),
        status=IdentityStatus.AUTHORITATIVE,
        gaps=(),
    )
    return {
        "doc_name": "same-display-name",
        "levels": [],
        "rooms": [],
        "grids": [],
        "identity": identity.to_dict(),
    }


def _row() -> dict:
    return {
        "element_id": "42",
        "unique_id": "same-element-unique-id",
        "category": "OST_Walls",
        "type_id": "7",
        "type_name": "Wall",
        "level_id": None,
        "host_id": None,
        "params": {},
    }


class GeneratedRevitCapture(unittest.TestCase):
    def test_every_regular_element_body_writes_element_unique_id(self) -> None:
        for category in EXTRACT_CATEGORIES:
            with self.subTest(category=category):
                body = build_category_batch_cs(category)
                write = '__row["unique_id"] = __element.UniqueId;'
                self.assertIn('__row["unique_id"] = null;', body)
                self.assertIn(write, body)
                self.assertLess(body.index(write), body.index("__rows.Add(__row)"))
                # VersionGuid is a changing revision witness. It is not part
                # of definition identity and must not be smuggled into it.
                self.assertNotIn("VersionGuid", body)

    def test_header_captures_source_root_and_exact_link_instance(self) -> None:
        root = build_metadata_cs()
        linked = build_metadata_cs(link_title="MEP")
        for body in (root, linked):
            self.assertIn("__document.GetCloudModelPath()", body)
            self.assertIn("__cloudPath.GetProjectGUID()", body)
            self.assertIn("__cloudPath.GetModelGUID()", body)
            self.assertIn(
                "__document.Application.GetWorksharingCentralGUID(", body)
            self.assertIn('"cloud_project_model_guid"', body)
            self.assertIn('"revit_server_central_guid"', body)
            self.assertIn("__document.ProjectInformation", body)
            self.assertIn("__projectInformation.UniqueId", body)
            self.assertIn('"project_information_unique_id"', body)
            self.assertIn('__result["identity"]', body)
            self.assertIn('__link.UniqueId', body)
            self.assertIn('"linked_document_unavailable"', body)
            self.assertIn('"linked_document_identity_unavailable"', body)
            self.assertIn(
                '"linked_document_identity_not_authoritative"', body)
            self.assertNotIn("VersionGuid", body)
        self.assertIn("__sourceLinkInstance = __srcLi", linked)
        self.assertIn("if (__sourceLinkMatches > 1) throw", linked)
        self.assertIn("linked document title is ambiguous", linked)

    def test_linked_batch_resolves_types_in_the_linked_document(self) -> None:
        body = build_category_batch_cs("OST_Walls", link_title="MEP")
        self.assertIn("var __type = __src.GetElement(__typeId);", body)
        self.assertNotIn("var __type = doc.GetElement(__typeId);", body)


class ProductionContextResolution(unittest.TestCase):
    def test_regular_row_schema_round_trip_preserves_unique_id(self) -> None:
        row = make_element("OST_Walls", 42)
        row["unique_id"] = "wall-definition-uid"
        parsed = L0Element.from_dict(row)
        self.assertEqual(parsed.unique_id, "wall-definition-uid")
        self.assertEqual(parsed.to_dict()["unique_id"],
                         "wall-definition-uid")

    def test_metadata_parser_and_header_round_trip_preserve_identity(self) -> None:
        payload = project1_metadata()
        payload["identity"] = L0IdentityMetadata(
            source_kind=L0SourceKind.ROOT,
            document_identity=_fact("project-roundtrip"),
            federation_root_identity=_fact("project-roundtrip"),
            link_instance_chain=(),
            status=IdentityStatus.AUTHORITATIVE,
            gaps=(),
        ).to_dict()
        parsed = _parse_metadata(payload, "revision-1")

        self.assertIsNotNone(parsed.identity)
        self.assertEqual(
            parsed.metadata_dict()["identity"],
            payload["identity"],
        )

    def test_same_local_element_id_in_two_documents_never_coalesces(self) -> None:
        left = graph_from_l0(_root_header("project-A"), [_row()]).node("42")
        right = graph_from_l0(_root_header("project-B"), [_row()]).node("42")

        self.assertEqual(left.local_element_id, right.local_element_id)
        self.assertNotEqual(left.definition_identity,
                            right.definition_identity)
        self.assertNotEqual(left.occurrence_identity,
                            right.occurrence_identity)
        self.assertTrue(left.identity_authoritative)
        self.assertTrue(right.identity_authoritative)

    def test_project_information_uid_is_lineage_not_global_authority(self) -> None:
        weak = _lineage_fact("uid-that-a-save-as-copy-may-retain")
        identity = L0IdentityMetadata(
            source_kind=L0SourceKind.ROOT,
            document_identity=weak,
            federation_root_identity=weak,
            link_instance_chain=(),
            status=IdentityStatus.INCOMPLETE,
            gaps=(
                IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
                IdentityGap.FEDERATION_ROOT_IDENTITY_NOT_AUTHORITATIVE,
            ),
        )
        graph = graph_from_l0({
            "doc_name": "copy-with-same-title",
            "levels": [], "rooms": [], "grids": [],
            "identity": identity.to_dict(),
        }, [_row()])
        node = graph.node("42")

        # A weak lineage value never enters definition/occurrence indexes. A
        # trusted caller may still provide an explicit copy identity.
        self.assertIsNone(node.definition_identity)
        self.assertIsNone(node.occurrence_identity)
        self.assertIn(
            IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
            node.identity_gaps,
        )
        self.assertFalse(graph.identity_authoritative)

    def test_cloud_project_and_model_pair_is_an_authoritative_source(self) -> None:
        fact = DocumentIdentityFact(
            CLOUD_PROJECT_MODEL_GUID,
            "project-guid/model-guid",
        )
        header = L0IdentityMetadata(
            source_kind=L0SourceKind.ROOT,
            document_identity=fact,
            federation_root_identity=fact,
            link_instance_chain=(),
            status=IdentityStatus.AUTHORITATIVE,
            gaps=(),
        ).to_dict()
        context = identity_context_from_l0({"identity": header})
        self.assertTrue(context.authoritative)
        self.assertIn("cloud_project_model_guid",
                      context.document_identity.value)

    def test_randomized_documents_never_share_occurrence_keys(self) -> None:
        rng = Random(0x4B4952)
        keys: set[str] = set()
        for index in range(200):
            # Deliberately recycle a tiny ElementId/UniqueId domain. Only the
            # independently captured document fact may keep definitions apart.
            local = str(rng.randrange(1, 8))
            row = _row()
            row["element_id"] = local
            row["unique_id"] = f"recycled-{rng.randrange(1, 5)}"
            node = graph_from_l0(
                _root_header(f"project-{index}"), [row]).node(local)
            self.assertNotIn(node.occurrence_identity.key, keys)
            keys.add(node.occurrence_identity.key)
        self.assertEqual(len(keys), 200)

    def test_explicit_context_has_priority_over_header_metadata(self) -> None:
        explicit_document = DocumentIdentity("operator-document")
        explicit_federation = FederationContext(
            "operator-root", ("operator-link",))
        context = identity_context_from_l0(
            _root_header("metadata-document"),
            document_identity=explicit_document,
            federation_context=explicit_federation,
        )
        self.assertIs(context.document_identity, explicit_document)
        self.assertIs(context.federation_context, explicit_federation)
        self.assertTrue(context.authoritative)

    def test_missing_link_instance_identity_remains_incomplete(self) -> None:
        identity = L0IdentityMetadata(
            source_kind=L0SourceKind.LINK,
            document_identity=_fact("linked-document"),
            federation_root_identity=_fact("root-document"),
            link_instance_chain=(),
            status=IdentityStatus.INCOMPLETE,
            gaps=(IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE,),
        )
        header = {
            "doc_name": "linked",
            "levels": [], "rooms": [], "grids": [],
            "identity": identity.to_dict(),
        }
        graph = graph_from_l0(header, [_row()])
        node = graph.node("42")

        # Definition survives because the linked document is known. The
        # occurrence does not: using local ElementId "42" as the missing
        # link path would silently merge two insertions.
        self.assertIsNotNone(node.definition_identity)
        self.assertIsNone(node.occurrence_identity)
        self.assertIn(
            IdentityGap.LINK_INSTANCE_UNIQUE_ID_UNAVAILABLE,
            node.identity_gaps,
        )
        self.assertIn(
            IdentityGap.MISSING_FEDERATION_CONTEXT,
            node.identity_gaps,
        )
        self.assertFalse(graph.identity_authoritative)

    def test_unloaded_link_has_a_named_gap_not_a_guessed_document(self) -> None:
        link = LinkSummary.from_dict({
            "element_id": "99",
            "name": "unloaded MEP",
            "loaded": False,
            "element_count": None,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
            "discipline": "mechanical",
            "identity": L0LinkIdentity(
                instance_unique_id="link-instance-uid",
                linked_document_identity=None,
                status=IdentityStatus.INCOMPLETE,
                gaps=(IdentityGap.LINKED_DOCUMENT_UNAVAILABLE,),
            ).to_dict(),
        })

        self.assertIsNotNone(link.identity)
        self.assertFalse(link.identity.authoritative)
        self.assertIsNone(link.identity.linked_document_identity)
        self.assertEqual(
            link.identity.gaps,
            (IdentityGap.LINKED_DOCUMENT_UNAVAILABLE,),
        )

    def test_loaded_nonworkshared_link_keeps_lineage_but_not_authority(self) -> None:
        link = LinkSummary.from_dict({
            "element_id": "100",
            "name": "loaded local copy",
            "loaded": True,
            "element_count": 12,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
            "discipline": "unknown",
            "identity": L0LinkIdentity(
                instance_unique_id="link-instance-uid",
                linked_document_identity=_lineage_fact("project-info-uid"),
                status=IdentityStatus.INCOMPLETE,
                gaps=(
                    IdentityGap.LINKED_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE,
                ),
            ).to_dict(),
        })
        self.assertFalse(link.identity.authoritative)
        self.assertEqual(
            link.identity.linked_document_identity.source,
            PROJECT_INFORMATION_UNIQUE_ID,
        )


if __name__ == "__main__":
    unittest.main()
