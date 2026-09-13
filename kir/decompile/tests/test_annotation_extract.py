"""Acceptance of the annotation side index.

The stage exists for the sake of one number: 53,796 annotation elements
are read and not one of them comes up, because L0 carries no inputs for
them. The tests here guard not "it works" but the properties whose loss
would make the index look nice while lying: unit conversion happening in
exactly one place, the two-dimensionality of a view point, a receipt for
every unread element, and a step name in every refusal.
"""
from __future__ import annotations

import json
import unittest

from kir.decompile.annotation_extract import (
    ANNOTATION_EXTRACT_SCHEMA_VERSION,
    ANNOTATION_INDEX_SCHEMA_VERSION,
    AnnotationExtraction,
    AnnotationFailure,
    AnnotationPayloadError,
    TextNoteRecord,
    build_annotation_extract_cs,
    extract_annotations,
    merge_annotations,
)
from kir.code_safety import validate_code_safety


def _wire(**overrides):
    payload = {
        "schema_version": ANNOTATION_EXTRACT_SCHEMA_VERSION,
        "elements": [{
            "element_id": "4200",
            "owner_view_id": "900",
            "owner_view_name": "1 этаж",
            "at_view_ft": [10.0, -2.5],
            "content": "ПОМЕЩЕНИЕ 1",
            "type_id": "77",
            "type_name": "Текст 2.5 мм",
        }],
        "failures": [],
    }
    payload.update(overrides)
    return payload


class WireShapeTests(unittest.TestCase):

    def test_feet_become_millimetres_exactly_once(self) -> None:
        extraction = extract_annotations(_wire())
        record = extraction.text_notes[0]
        self.assertAlmostEqual(record.at_view_mm[0], 10.0 * 304.8, places=6)
        self.assertAlmostEqual(record.at_view_mm[1], -2.5 * 304.8, places=6)
        # And a second pass through disk does NOT recompute a second
        # time.
        again = AnnotationExtraction.from_json(extraction.to_json())
        self.assertEqual(again.text_notes[0].at_view_mm, record.at_view_mm)

    def test_bridge_envelope_is_unwrapped_once(self) -> None:
        extraction = extract_annotations({"payload": _wire()})
        self.assertEqual(len(extraction), 1)

    def test_unexpected_field_is_a_typed_refusal(self) -> None:
        payload = _wire()
        payload["elements"][0]["ширина"] = 1
        with self.assertRaises(AnnotationPayloadError):
            extract_annotations(payload)

    def test_foreign_schema_version_refuses_instead_of_half_parsing(self) -> None:
        with self.assertRaises(AnnotationPayloadError):
            extract_annotations(_wire(schema_version="kir-something-else/9"))

    def test_a_view_point_with_three_components_is_refused(self) -> None:
        """The third coordinate is the signature of a model point in a
        view's plane."""
        payload = _wire()
        payload["elements"][0]["at_view_ft"] = [1.0, 2.0, 3.0]
        with self.assertRaises(AnnotationPayloadError):
            extract_annotations(payload)

    def test_non_finite_coordinate_is_refused(self) -> None:
        payload = _wire()
        payload["elements"][0]["at_view_ft"] = [float("inf"), 0.0]
        with self.assertRaises(AnnotationPayloadError):
            extract_annotations(payload)

    def test_a_view_without_a_name_is_refused(self) -> None:
        """The L1 reference dialect is named — a view without a name
        cannot be expressed."""
        payload = _wire()
        payload["elements"][0]["owner_view_name"] = ""
        with self.assertRaises(AnnotationPayloadError):
            extract_annotations(payload)

    def test_failures_survive_parsing(self) -> None:
        payload = _wire(failures=[{
            "element_id": "4201", "reason": "annotation has no owner view",
            "typed_reason": "aspect_not_present"}])
        extraction = extract_annotations(payload)
        self.assertEqual(len(extraction.failures), 1)
        self.assertEqual(extraction.failures[0].typed_reason, "aspect_not_present")


class PersistenceTests(unittest.TestCase):

    def test_round_trip_through_disk_is_exact(self) -> None:
        extraction = extract_annotations(_wire(failures=[{
            "element_id": "9", "reason": "read failed at TextElement.Coord: "
            "InvalidOperationException", "typed_reason": "read_failed"}]))
        again = AnnotationExtraction.from_json(extraction.to_json())
        self.assertEqual(again.to_dict(), extraction.to_dict())

    def test_index_key_must_match_the_record(self) -> None:
        good = extract_annotations(_wire()).to_dict()
        good["text_note_index"]["999"] = good["text_note_index"].pop("4200")
        with self.assertRaises(AnnotationPayloadError):
            AnnotationExtraction.from_dict(good)

    def test_duplicate_element_id_is_refused(self) -> None:
        record = TextNoteRecord("1", "900", "1 этаж", (0.0, 0.0), "a")
        with self.assertRaises(AnnotationPayloadError):
            AnnotationExtraction(text_notes=(record, record))

    def test_persisted_schema_version_is_checked(self) -> None:
        payload = extract_annotations(_wire()).to_dict()
        payload["schema_version"] = "kir-decompile-annotation-index/0"
        with self.assertRaises(AnnotationPayloadError):
            AnnotationExtraction.from_dict(payload)


class MergeTests(unittest.TestCase):

    def test_first_page_wins_and_failures_accumulate(self) -> None:
        first = AnnotationExtraction(
            text_notes=(TextNoteRecord("1", "900", "вид", (1.0, 1.0), "первый"),),
            failures=(AnnotationFailure("7", "нет вида", "aspect_not_present"),))
        second = AnnotationExtraction(
            text_notes=(TextNoteRecord("1", "900", "вид", (2.0, 2.0), "второй"),
                        TextNoteRecord("2", "900", "вид", (3.0, 3.0), "другой")),
            failures=(AnnotationFailure("8", "нет текста", "aspect_not_present"),))
        merged = merge_annotations([first, second])
        by_id = {r.element_id: r for r in merged.text_notes}
        self.assertEqual(by_id["1"].content, "первый")
        self.assertEqual(len(merged.text_notes), 2)
        self.assertEqual(len(merged.failures), 2)


class EmittedCsTests(unittest.TestCase):

    def test_ids_and_schema_literal_are_embedded(self) -> None:
        code = build_annotation_extract_cs(["4200", "4201"])
        self.assertIn('"4200"', code)
        self.assertIn('"4201"', code)
        self.assertIn(ANNOTATION_EXTRACT_SCHEMA_VERSION, code)

    def test_no_transaction_is_opened(self) -> None:
        """A READING stage: a transaction here would be a write into
        someone else's model."""
        code = build_annotation_extract_cs(["1"])
        self.assertNotIn("Transaction", code)

    def test_every_read_is_named_by_step(self) -> None:
        """The lesson of 2846 groups: a refusal must name WHAT was being
        read."""
        code = build_annotation_extract_cs(["1"])
        for step in ("Document.GetElement", "Element.OwnerViewId",
                     "TextElement.Coord", "TextElement.Text",
                     "View basis (Origin/RightDirection/UpDirection)"):
            self.assertIn(step, code)
        self.assertIn("__anStep", code)

    def test_projection_uses_the_same_formula_as_the_forward_emitter(self) -> None:
        """rel·Right and rel·Up are the exact inverse of
        Origin + u*Right + v*Up."""
        code = build_annotation_extract_cs(["1"])
        self.assertIn("__anCoord - __anOrigin", code)
        self.assertIn("DotProduct(__anRight)", code)
        self.assertIn("DotProduct(__anUp)", code)

    def test_a_budgeted_page_never_runs_unbounded(self) -> None:
        code = build_annotation_extract_cs(["1"], call_budget_ms=1234)
        self.assertIn("1234L", code)
        self.assertIn("call_budget_exhausted", code)

    def test_emitted_code_passes_the_safety_validator(self) -> None:
        # None == no violations; a list == the list of violations.
        self.assertIsNone(
            validate_code_safety(build_annotation_extract_cs(["1", "2"])))

    def test_empty_page_is_still_well_formed(self) -> None:
        code = build_annotation_extract_cs([])
        self.assertIn("__anIds", code)
        self.assertIsNone(validate_code_safety(code))


if __name__ == "__main__":
    unittest.main()
