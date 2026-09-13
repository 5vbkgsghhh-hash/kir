"""Lifting a text note — and the price it does NOT have the right to charge.

The annotation wave closes the first of three ops that lay dead: 2,697
notes in the RD tower. But it carries a counter-obligation, and half the
tests here exist for it: fixtures captured BEFORE the stage must yield the
same atom with the same reason VERBATIM. Otherwise the coverage history
stops being a history — yesterday's 96.13% and today's would become numbers
about different things.
"""
from __future__ import annotations

import copy
import unittest

from kir.decompile.annotation_extract import (
    AnnotationExtraction,
    TextNoteRecord,
)
from kir.decompile.lift import lift_document_detailed
from kir.decompile.lift_cache import lift_cache_key
from kir.decompile.l1_schema import AtomReason
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


TEXT_ID = "4200"
VIEW_ID = "900"
VIEW_NAME = "1 этаж"


def _document() -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "annotation-wave"
    element = make_element("OST_TextNotes", int(TEXT_ID))
    row["elements"] = [element]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _index(**overrides) -> AnnotationExtraction:
    record = TextNoteRecord(
        element_id=overrides.get("element_id", TEXT_ID),
        owner_view_id=overrides.get("owner_view_id", VIEW_ID),
        owner_view_name=overrides.get("owner_view_name", VIEW_NAME),
        at_view_mm=overrides.get("at_view_mm", (3048.0, -762.0)),
        content=overrides.get("content", "ТЕХНИЧЕСКОЕ ПОДПОЛЬЕ"),
        type_id=overrides.get("type_id", "77"),
        type_name=overrides.get("type_name", "Текст 2.5 мм"),
    )
    return AnnotationExtraction(text_notes=(record,))


def _only(result):
    self_nodes = [n for n in result.nodes if n is not None]
    assert len(self_nodes) == 1, self_nodes
    return self_nodes[0]


class LiftWithIndexTests(unittest.TestCase):

    def test_text_note_becomes_create_text(self) -> None:
        node = _only(lift_document_detailed(
            _document(), annotation_index=_index()))
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_text")
        params = node["params"]
        self.assertEqual(params["in_view"],
                         {"by": "name", "value": VIEW_NAME, "_id": VIEW_ID})
        self.assertEqual(params["content"], "ТЕХНИЧЕСКОЕ ПОДПОЛЬЕ")
        self.assertEqual(params["text_type"],
                         {"by": "name", "value": "Текст 2.5 мм", "_id": "77"})

    def test_the_point_stays_two_dimensional(self) -> None:
        """The view point is TWO-DIMENSIONAL. A third coordinate would mean a model point."""
        node = _only(lift_document_detailed(
            _document(), annotation_index=_index()))
        self.assertEqual(node["params"]["at"], [3048.0, -762.0])
        self.assertEqual(len(node["params"]["at"]), 2)

    def test_a_persisted_envelope_works_as_well_as_the_object(self) -> None:
        """Parsing from disk must yield the same op as the in-memory object."""
        from_disk = lift_document_detailed(
            _document(), annotation_index=_index().to_dict())
        in_memory = lift_document_detailed(
            _document(), annotation_index=_index())
        self.assertEqual(_only(from_disk), _only(in_memory))

    def test_missing_text_type_simply_omits_it(self) -> None:
        """Missing type — an absent key, not a substituted default."""
        node = _only(lift_document_detailed(
            _document(), annotation_index=_index(type_id=None)))
        self.assertNotIn("text_type", node["params"])


class HonestyWithoutIndexTests(unittest.TestCase):

    def _atom_detail(self, **kwargs) -> tuple[str, str]:
        result = lift_document_detailed(_document(), **kwargs)
        node = _only(result)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(len(result.diagnostics), 1)
        reason = node["reason"]
        code = reason["code"] if isinstance(reason, dict) else reason
        return code, result.diagnostics[0].detail

    def test_without_the_index_the_old_refusal_is_reproduced_verbatim(self) -> None:
        reason, detail = self._atom_detail()
        self.assertEqual(reason, AtomReason.SOURCE_CONTRACT_GAP.value)
        # The refusal text IS ASSEMBLED FROM THE REGISTRY, so its load-bearing
        # parts are checked, not the whole string: it is expected to change
        # along with the op.
        self.assertIn("create_text", detail)
        self.assertIn("in_view", detail)
        self.assertIn("content", detail)

    def test_an_index_without_this_element_refuses_the_same_way(self) -> None:
        """The stage ran and did not bring this element — also a refusal, not a fabrication."""
        reason, detail = self._atom_detail(
            annotation_index=_index(element_id="999"))
        self.assertEqual(reason, AtomReason.SOURCE_CONTRACT_GAP.value)
        self.assertIn("create_text", detail)

    def test_empty_content_is_a_refusal_not_an_empty_string(self) -> None:
        reason, detail = self._atom_detail(annotation_index=_index(content=""))
        self.assertEqual(reason, AtomReason.SOURCE_CONTRACT_GAP.value)
        self.assertIn("без содержания", detail)

    def test_a_corrupt_index_degrades_to_the_refusal_not_to_half_a_lift(self) -> None:
        reason, _ = self._atom_detail(
            annotation_index={"schema_version": "чужая/1", "text_note_index": {}})
        self.assertEqual(reason, AtomReason.SOURCE_CONTRACT_GAP.value)


class CacheKeyTests(unittest.TestCase):

    def test_the_annotation_index_changes_the_cache_key(self) -> None:
        """Otherwise the cache will return an ATOM for a request WITH an index, and the wiring will be illusory.

        This exact class of defect already cost the curtain-wall and window
        indexes: the key did not include the input, the cache returned the
        previous answer, and the wave looked applied while silently not
        working.
        """
        document = _document()
        without = lift_cache_key(document)
        with_index = lift_cache_key(document, annotation_index=_index())
        other = lift_cache_key(
            document, annotation_index=_index(content="ДРУГОЙ ТЕКСТ"))
        self.assertNotEqual(without, with_index)
        self.assertNotEqual(with_index, other)

    def test_the_same_index_gives_the_same_key(self) -> None:
        document = _document()
        self.assertEqual(
            lift_cache_key(document, annotation_index=_index()),
            lift_cache_key(document, annotation_index=_index()))


if __name__ == "__main__":
    unittest.main()
