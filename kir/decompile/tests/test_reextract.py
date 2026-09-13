"""Wave A5 — re-extract-by-ids collector + row parser (offline).

The idempotence loop reads back ONLY the ids it created.  These tests prove the
collector body is a deterministic pure function of the id list (sorted, deduped),
uses NO 64-bit ``ElementId`` literal (2021-2023 compile safety), and that the row
parser reuses the frozen ``L0Element`` reader and refuses malformed/duplicate
rows with a typed error.
"""
from __future__ import annotations

import unittest

from kir.decompile.reextract import (
    REEXTRACT_BATCH,
    ReExtractError,
    build_reextract_cs,
    build_room_reextract_cs,
    parse_reextract_rows,
    parse_room_reextract,
    reextracted_document,
)
from kir.decompile.schema import (
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


class TheRereadAsksTheDocumentInsteadOfWalkingIt(unittest.TestCase):
    """🔴 MEASUREMENT 18.08.2026: `built_reread` cost 2663 ms per turn, and the reason
    was in THIS body — it materialized the ENTIRE document into a list and
    SORTED it (`OrderBy(__Id)`) in order to find no more than 200 ids.

    On the owner's tower (310 558 elements) that is 310 thousand calls to
    `e.Id.ToString()` + `long.Parse` for the sake of two hundred matches. The canon already
    named the symptom — "the slope against N is zero, a document walk is paid for, not
    the number of ids" — but not the cause.

    A direct lookup asks the document for exactly what is needed. The boundary is named and
    checked by compilation: `new ElementId(int)` builds on all SIX
    versions, `new ElementId(long)` only from 2024 on, and the body is emitted as ONE
    text for all of them — meaning a 64-bit id falls back to the walk.
    """

    def test_small_ids_are_fetched_directly(self):
        from kir.decompile.reextract import build_reextract_cs

        body = build_reextract_cs(["18830681", "18830682"])
        self.assertIn("doc.GetElement(new ElementId(__wid))", body)
        self.assertIn("18830681, 18830682", body)
        # not a single walk remains — otherwise there is no savings
        self.assertNotIn("WhereElementIsNotElementType", body)
        self.assertNotIn("OfClass(typeof(Grid))", body)

    def test_a_64bit_id_falls_back_to_the_walk_with_a_named_reason(self):
        """Falling back from a direct lookup is NAMED, not silent."""
        from kir.decompile.reextract import (
            _INT32_MAX, _candidates_cs, build_reextract_cs)

        body = build_reextract_cs([str(_INT32_MAX + 1)])
        self.assertIn("WhereElementIsNotElementType", body)
        _cs, why = _candidates_cs([_INT32_MAX + 1])
        self.assertIn("больше Int32", why)
        self.assertIn("2024", why)

    def test_the_direct_path_still_refuses_element_types(self):
        """🔴 A CONTROL FOR LOSING THE SUBJECT, AND IT IS ABOUT A DISCREPANCY, NOT ABOUT SPEED.

        The walk used `WhereElementIsNotElementType()`, meaning it did not see
        type instances at all. A direct lookup by id sees EVERYTHING, including a type instance
        created by `create_type`. Without an explicit `is ElementType`, the two branches of one
        body would answer DIFFERENTLY for the same id — silently, and only on
        documents where the id is small.
        """
        from kir.decompile.reextract import build_reextract_cs

        body = build_reextract_cs(["700"])
        # 🔴 AN ASSERTION, NOT LETTERS (edit 21.08). The previous revision
        # pinned the line verbatim and turned red when the skip learned to
        # NAME ITSELF: the body now not only discards the type instance but also
        # puts its id into `skipped_element_types`, so that the built-result judge
        # can tell "a different kind" apart from "went missing". The test must guard what
        # its name asserts — that the direct path does NOT RETURN type instances.
        self.assertIn("__el is ElementType", body)
        self.assertIn("__skippedTypes.Add", body,
                      "пропуск обязан НАЗЫВАТЬ себя, а не молчать")
        self.assertIn("skipped_element_types", body,
                      "названное обязано доехать до читателя тела")

    def test_both_branches_keep_the_filter_and_the_dedup(self):
        """The narrowing has no right to drop either the id filter or the dedup.

        On the direct path they become an identity — and that is normal; dropping them
        would make the two branches non-equivalent in a third place.
        """
        from kir.decompile.reextract import _INT32_MAX, build_reextract_cs

        for ids in (["700"], [str(_INT32_MAX + 1)]):
            with self.subTest(ids=ids):
                body = build_reextract_cs(ids)
                self.assertIn("__wanted.Contains(__eid)", body)
                self.assertIn("__seen.Contains(__eid)", body)

    def test_an_empty_id_list_does_not_emit_a_direct_fetch(self):
        """An empty list is a degenerate input; a direct lookup from zero ids
        would assemble `new int[] {  }` and silently return emptiness instead of a refusal."""
        from kir.decompile.reextract import _candidates_cs

        body, why = _candidates_cs([])
        self.assertIn("WhereElementIsNotElementType", body)
        self.assertEqual(why, "пусто")


if __name__ == "__main__":
    unittest.main()
