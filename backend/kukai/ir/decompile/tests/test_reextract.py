"""Wave A5 — re-extract-by-ids collector + row parser (offline).

The idempotence loop reads back ONLY the ids it created.  These tests prove the
collector body is a deterministic pure function of the id list (sorted, deduped),
uses NO 64-bit ``ElementId`` literal (2021-2023 compile safety), and that the row
parser reuses the frozen ``L0Element`` reader and refuses malformed/duplicate
rows with a typed error.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.reextract import (
    REEXTRACT_BATCH,
    ReExtractError,
    build_reextract_cs,
    build_room_reextract_cs,
    parse_reextract_rows,
    parse_room_reextract,
    reextracted_document,
)
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    LevelInfo,
    ProjectInfo,
    RoomInfo,
)


class BuilderTests(unittest.TestCase):
    def test_ids_are_sorted_deduped_and_deterministic(self):
        a = build_reextract_cs(["300", "20", "20", "5"])
        b = build_reextract_cs(["5", "20", "300"])
        self.assertEqual(a, b)  # order + duplicate irrelevant
        self.assertIn("5L, 20L, 300L", a)

    def test_no_64bit_elementid_constructor(self):
        # ``new ElementId(<long>)`` is 2024+ only; the collector must filter by
        # __Id(e) membership instead so it compiles on 2021-2023 too.
        body = build_reextract_cs(["99999999999"])
        self.assertNotIn("new ElementId(", body)
        self.assertIn("HashSet<long>", body)

    def test_non_numeric_id_is_typed_refusal(self):
        with self.assertRaises(ReExtractError):
            build_reextract_cs(["abc"])

    def test_more_than_200_ids_is_refused_at_builder_boundary(self):
        with self.assertRaisesRegex(ReExtractError, "exceeds 200"):
            build_reextract_cs([
                str(index) for index in range(REEXTRACT_BATCH + 1)
            ])


_LEVEL = LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0)
_PROJ = ProjectInfo(name="Проект", address="а", building_type_hint=None)


def _wall_row(eid: str) -> dict:
    return {
        "element_id": eid, "category": "OST_Walls", "category_ru": "Стены",
        "type_id": "5001", "type_name": "Стена 200", "level_id": "100",
        "level_name": "Этаж 1", "host_id": None, "geom_kind": "curve",
        "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [6000.0, 0.0, 0.0],
        "rotation_deg": None, "bbox_min_mm": None, "bbox_max_mm": None,
        "params": {"WALL_USER_HEIGHT_PARAM": 2800.0}}


class ParserTests(unittest.TestCase):
    def test_parses_bridge_envelope_and_sorts_by_id(self):
        payload = {"ok": True, "result": {"elements": [
            _wall_row("7002"), _wall_row("7001")]}}
        elements = parse_reextract_rows(payload)
        self.assertEqual([e.element_id for e in elements], ["7001", "7002"])
        self.assertEqual(elements[0].geom_kind, GeometryKind.CURVE)

    def test_bare_result_object_accepted(self):
        elements = parse_reextract_rows({"elements": [_wall_row("7001")]})
        self.assertEqual(len(elements), 1)

    def test_duplicate_id_refused(self):
        payload = {"result": {"elements": [_wall_row("7001"), _wall_row("7001")]}}
        with self.assertRaises(ReExtractError):
            parse_reextract_rows(payload)

    def test_malformed_row_is_typed(self):
        payload = {"result": {"elements": [{"element_id": "7001"}]}}
        with self.assertRaises(ReExtractError):
            parse_reextract_rows(payload)

    def test_missing_elements_array_typed(self):
        with self.assertRaises(ReExtractError):
            parse_reextract_rows({"result": {}})

    def test_requested_seen_coverage_is_exact(self):
        with self.assertRaisesRegex(ReExtractError, "missing=7002"):
            parse_reextract_rows(
                {"elements": [_wall_row("7001")]},
                requested_ids=["7001", "7002"],
            )
        with self.assertRaisesRegex(ReExtractError, "extra=7002"):
            parse_reextract_rows(
                {"elements": [_wall_row("7001"), _wall_row("7002")]},
                requested_ids=["7001"],
            )


class DocumentAssemblyTests(unittest.TestCase):
    def test_reextracted_document_reuses_metadata_and_swaps_elements(self):
        original = L0Document(
            doc_name="Проект", revit_version="2026", units="mm",
            change_stamp="s1", levels=(_LEVEL,), grids=(), rooms=(),
            project_info=_PROJ, elements=())
        elements = parse_reextract_rows({"result": {"elements": [_wall_row("7001")]}})
        re_doc = reextracted_document(original, elements, change_stamp="s2")
        self.assertEqual(re_doc.levels, original.levels)
        self.assertEqual(re_doc.change_stamp, "s2")
        self.assertEqual([e.element_id for e in re_doc.elements], ["7001"])


_ROOM_ROW = {
    "id": "9100", "name": "Зал", "level_id": "7", "level_name": "Этаж 20",
    "area_m2": 12.0,
    "boundary_mm": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]],
    "boundary_loops_mm": [[[0, 0], [4000, 0], [4000, 3000], [0, 3000]]],
    "bounding_element_ids": ["5001"],
}


class RoomReextractTests(unittest.TestCase):
    def test_builder_is_room_scoped_and_id_pure(self):
        cs = build_room_reextract_cs(["9100", "9099", "9100"])
        self.assertIn("OST_Rooms", cs)
        self.assertIn("GetBoundarySegments", cs)
        self.assertIn("9099L", cs)
        self.assertIn("9100L", cs)
        # dedup + sort: 9100 appears once, ordered after 9099
        self.assertEqual(cs.count("9100L"), 1)
        self.assertLess(cs.index("9099L"), cs.index("9100L"))
        # no 64-bit ElementId ctor (2021-2023 compile safety)
        self.assertNotIn("new ElementId(", cs)

    def test_parser_reads_boundaries_and_refuses_dupes(self):
        rooms = parse_room_reextract({"result": {"rooms": [_ROOM_ROW]}})
        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0].id, "9100")
        self.assertEqual(len(rooms[0].boundary_mm), 4)
        with self.assertRaises(ReExtractError):
            parse_room_reextract({"rooms": [_ROOM_ROW, dict(_ROOM_ROW)]})
        with self.assertRaises(ReExtractError):
            parse_room_reextract({"nope": []})

    def test_room_requested_seen_coverage_is_exact(self):
        with self.assertRaisesRegex(ReExtractError, "missing=9101"):
            parse_room_reextract(
                {"rooms": [_ROOM_ROW]}, requested_ids=["9100", "9101"])

    def test_rooms_override_swaps_the_room_context(self):
        # The Δ-copy rooms carry NEW ids — reextracted_document must bind THEM,
        # not the original metadata rooms (harness-blindness fix, 0/87 → live).
        orig_room = RoomInfo(
            id="1", name="старая", level_id="7", level_name="Этаж 20",
            area_m2=9.0, boundary_mm=((0, 0), (1, 0), (1, 1)),
            boundary_loops_mm=(((0, 0), (1, 0), (1, 1)),),
            bounding_element_ids=("2",))
        original = L0Document(
            doc_name="П", revit_version="2026", units="mm", change_stamp="s",
            levels=(_LEVEL,), grids=(), rooms=(orig_room,),
            project_info=_PROJ, elements=())
        delta = parse_room_reextract({"rooms": [_ROOM_ROW]})
        re_doc = reextracted_document(original, (), rooms=delta)
        self.assertEqual([r.id for r in re_doc.rooms], ["9100"])
        # None keeps the original rooms (legacy path)
        legacy = reextracted_document(original, ())
        self.assertEqual([r.id for r in legacy.rooms], ["1"])


if __name__ == "__main__":
    unittest.main()
