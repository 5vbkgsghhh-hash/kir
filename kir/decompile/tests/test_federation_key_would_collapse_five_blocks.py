"""WHY `identity` = 0 ACROSS THE WHOLE CORPUS — AND WHY THAT IS THE CORRECT REFUSAL.

🔴 MEASUREMENT 2026-08-22, PRODUCTION MODEL MNVNK (`Building 6`, 33,944
elements, five `link` records to neighboring blocks of the same complex):

    host document K6      identity.document_identity.value
                          = `cb8ac19a-095c-49d7-b988-0533c015d0c9-0000059a`
    link K1 (129,365 elements)   linked_document_identity.value = THE SAME
    link K4 ( 75,940)                                             THE SAME
    link K2 ( 55,381)                                             THE SAME
    link K5 ( 60,616)                                             THE SAME
    link KR (structural section)  linked_document_identity = null

ONE KEY FOR FIVE DIFFERENT DOCUMENTS. The source is called
`project_information_unique_id`, i.e. `ProjectInformation.UniqueId`, and
Autodesk contracts the stability of `Element.UniqueId` only WITHIN a
document: the complex's blocks were made with "Save As" from one
template and kept the value.

THE CONSEQUENCE THIS FILE EXISTS FOR: promoting this source to
authoritative would not "turn on federation" — it would COLLAPSE FIVE
BUILDINGS INTO ONE, silently and in the dangerous direction. The
`*_not_authoritative` refusal is therefore load-bearing, and
`identity_authoritative = 0` is not a hole but an honest "nothing to work with."

WHAT FIXES IT, AND THIS IS A BOUNDARY, NOT AN EVENING'S TASK:
`cloud_project_model_guid` or `revit_server_central_guid`, taken from the
ORIGINAL central models. In this L0 they are absent by construction —
the model was handed over detached, and a detached copy has no central
path to speak of. `graph_from_l0` already accepts explicit trusted
`document_identity`/`federation_context`: as soon as the keys are
obtained, nodes become authoritative without a single code change. This
is pinned down here precisely so that "nothing to work with" does not
turn into "impossible."
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import graph_from_l0
from kir.decompile.identity import (
    AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES,
    PROJECT_INFORMATION_UNIQUE_ID,
    DocumentIdentity,
    FederationContext,
    IdentityGap,
)

#: A header of exactly the shape that sits in MNVNK's `L0.jsonl`.
_SHARED_VALUE = "cb8ac19a-095c-49d7-b988-0533c015d0c9-0000059a"


def _header(value: str = _SHARED_VALUE) -> dict:
    fact = {"source": PROJECT_INFORMATION_UNIQUE_ID, "value": value}
    return {
        "doc_name": "MNVNK_ATR_PD_B14_K6_AR_R2022",
        "levels": [], "rooms": [], "grids": [],
        "identity": {
            "schema_version": "kir-l0-revit-identity/1",
            "source_kind": "root",
            "document_identity": dict(fact),
            "federation_root_identity": dict(fact),
            "link_instance_chain": [],
            "gaps": ["source_document_identity_not_authoritative",
                     "federation_root_identity_not_authoritative"],
            "status": "incomplete",
        },
    }


def _element(element_id: str, unique_id: str | None = "u-1") -> dict:
    return {"element_id": element_id, "category": "OST_Walls",
            "type_id": "t", "type_name": "T", "level_id": None,
            "host_id": None, "params": {}, "unique_id": unique_id}


class TheHeaderDOESCarryIdentityAndItStillIsNotAuthoritative(unittest.TestCase):
    """The first assertion — against the temptation to read 0 as "there are no fields"."""

    def test_project_information_unique_id_is_deliberately_weak(self) -> None:
        self.assertNotIn(PROJECT_INFORMATION_UNIQUE_ID,
                         AUTHORITATIVE_DOCUMENT_IDENTITY_SOURCES)

    def test_a_full_header_still_yields_zero_authoritative_nodes(self) -> None:
        graph = graph_from_l0(_header(), [_element("W1")])
        self.assertEqual(graph.census.identity_authoritative_nodes, 0)
        self.assertFalse(graph.identity_authoritative)
        # THE REASON IS NAMED, NOT IMPLIED: without a name for the gap,
        # "nothing to work with" and "did not look" would arrive as the
        # same zero.
        self.assertIn(IdentityGap.MISSING_DOCUMENT_IDENTITY.value,
                      graph.census.identity_gaps)
        self.assertIn(IdentityGap.MISSING_FEDERATION_CONTEXT.value,
                      graph.census.identity_gaps)
        self.assertIn(
            IdentityGap.SOURCE_DOCUMENT_IDENTITY_NOT_AUTHORITATIVE.value,
            graph.census.identity_gaps)

    def test_the_element_unique_id_is_present_and_still_not_enough(self) -> None:
        """The gap is NOT in the element's row: it has a `unique_id`."""
        graph = graph_from_l0(_header(), [_element("W1", "живой-uid")])
        self.assertNotIn(IdentityGap.MISSING_ELEMENT_UNIQUE_ID.value,
                         graph.census.identity_gaps)


class SharingOneKeyWouldCollapseTheComplex(unittest.TestCase):
    """🔴 THE REFUTING CASE: the key being asked to be promoted does NOT
    DISTINGUISH the complex's five blocks — and this is measured on the
    model itself."""

    def test_two_distinct_documents_share_the_weak_key(self) -> None:
        k6 = _header()["identity"]["document_identity"]["value"]
        k1_linked_value = _SHARED_VALUE  # this is how it sits in MNVNK's `link` record
        self.assertEqual(k6, k1_linked_value,
                         "если это когда-нибудь разойдётся — довод устарел, "
                         "и его надо перемерить, а не подпирать")

    def test_the_weak_key_promoted_would_merge_them(self) -> None:
        """What would happen if the source were recognized as
        authoritative: one and the same `DocumentIdentity` for two
        DIFFERENT documents."""
        as_if_k6 = DocumentIdentity(
            f"revit:{PROJECT_INFORMATION_UNIQUE_ID}:{_SHARED_VALUE}")
        as_if_k1 = DocumentIdentity(
            f"revit:{PROJECT_INFORMATION_UNIQUE_ID}:{_SHARED_VALUE}")
        self.assertEqual(as_if_k6, as_if_k1,
                         "именно эта неразличимость и есть цена повышения")


class TheTrustedOverrideIsTheDoorThatEXISTS(unittest.TestCase):
    """"Nothing to work with" is not the same as "impossible": the path
    to authority is open and checked."""

    def test_explicit_context_makes_every_node_authoritative(self) -> None:
        document = DocumentIdentity("revit:cloud_project_model_guid:K6-GUID")
        federation = FederationContext("revit:cloud_project_model_guid:K6-GUID")
        graph = graph_from_l0(
            _header(), [_element("W1", "живой-uid")],
            document_identity=document, federation_context=federation)
        self.assertTrue(graph.identity_authoritative)
        self.assertEqual(graph.census.identity_authoritative_nodes, 1)
        self.assertEqual(dict(graph.census.identity_gaps), {})

    def test_distinct_cloud_guids_keep_two_blocks_APART(self) -> None:
        """Exactly what today's key cannot do."""
        k6 = DocumentIdentity("revit:cloud_project_model_guid:K6-GUID")
        k1 = DocumentIdentity("revit:cloud_project_model_guid:K1-GUID")
        self.assertNotEqual(k6, k1)

    def test_a_node_without_its_unique_id_stays_incomplete_anyway(self) -> None:
        """A CONTROL IN THE OPPOSITE DIRECTION: a trusted context does
        NOT hand out authority to those who have no address of their own."""
        document = DocumentIdentity("revit:cloud_project_model_guid:K6-GUID")
        federation = FederationContext("revit:cloud_project_model_guid:K6-GUID")
        graph = graph_from_l0(
            _header(), [_element("W1", None)],
            document_identity=document, federation_context=federation)
        self.assertFalse(graph.identity_authoritative)
        self.assertIn(IdentityGap.MISSING_ELEMENT_UNIQUE_ID.value,
                      graph.census.identity_gaps)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
