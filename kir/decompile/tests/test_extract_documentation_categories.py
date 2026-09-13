"""Wave 07-29 — reading WORKING DRAWINGS: dimensions, room tags, notes.

The trigger was measured on a real working-drawing set
(13A-RD-AR-K2_v33, frozen copy ``k2_ar_rd_v6``): coverage FROM THE
DOCUMENT 9.61%, with 112 categories and 310,558 elements in the census,
while the extraction table read 54 categories = 55,293 elements
(17.80%). Most of what went unread outside the table is LEGITIMATE
(sketches, auto-dimensioning, utility content), but hidden alongside it
lay the content of the drawings themselves: 13,905 dimensions, 11,585
room tags, 9,407 lines, 3,046 detail-item elements, 2,697 text notes.

What is checked here is exactly what must not be violated:

  * the index of PREVIOUSLY existing categories has not shifted (the
    resumption format);
  * new rows exist and stand IN THE TAIL;
  * each row's collector asks for EXACTLY ITS OWN category (19 nearly
    identical rows in a row — perfect ground for copy-paste);
  * the census after the expansion counts them as READ, not "outside
    the table";
  * and — the refuting half — a derived quantity that we deliberately
    did NOT take is still honestly listed as outside the table.

The names of all 19 categories are checked by compilation 6/6 on
2021-2026 (BuiltInCategory has no such members in RevitAPI.xml at all —
the only honest oracle is the compile-service). The same run took a
control: OST_CurtainGridWall and OST_CurtainGridsSlopedGlazing do not
compile on any version (CS0117), which reproduces the note made in
extract.py by wave 07-28.
"""
from __future__ import annotations

import unittest

from kir.decompile import extract as ex
from kir.decompile.census import UnscannedReason, reconcile_census
from kir.decompile.schema import CensusEntry, L0Document
from kir.decompile.schema import GridInfo, LevelInfo, ProjectInfo
from kir.code_safety import validate_code_safety


# The order of the 54 categories as it was BEFORE this wave (git HEAD, 07-29).
# Frozen AS A WHOLE, not just the first twenty-two: the category index is
# part of the resumption format (``EXTRACT_CATEGORIES[len(processed):]``),
# so inserting into the middle of ANY of these stretches would scramble
# already-started extractions and all existing L0s. The old test froze
# only the prefix of 22 names, and positions 22..53 — the entire
# electrical/HVAC/plumbing/structural set, curtain walls, and isolation —
# were protected by nothing.
CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE = (
    "OST_Walls", "OST_Floors", "OST_Roofs", "OST_Columns",
    "OST_StructuralColumns", "OST_StructuralFraming",
    "OST_StructuralFoundation", "OST_Doors", "OST_Windows", "OST_Stairs",
    "OST_StairsRailing", "OST_Rooms", "OST_Grids", "OST_Levels",
    "OST_PipeCurves", "OST_DuctCurves", "OST_CableTray", "OST_Furniture",
    "OST_GenericModel", "DirectShape", "ImportInstance", "OST_RasterImages",
    "OST_ElectricalEquipment", "OST_ElectricalFixtures",
    "OST_LightingFixtures", "OST_LightingDevices", "OST_CableTrayFitting",
    "OST_Conduit", "OST_ConduitFitting", "OST_MechanicalEquipment",
    "OST_DuctFitting", "OST_DuctTerminal", "OST_FlexDuctCurves",
    "OST_MEPSpaces", "OST_PlumbingFixtures", "OST_PipeFitting",
    "OST_PipeAccessory", "OST_FlexPipeCurves", "OST_Sprinklers",
    "OST_StructuralTruss", "OST_Ceilings", "OST_Ramps",
    "OST_CurtainWallPanels", "OST_CurtainWallMullions", "OST_Casework",
    "OST_SpecialityEquipment", "OST_Areas", "OST_CurtaSystem",
    "OST_CurtainGridsWall", "OST_CurtainGridsRoof",
    "OST_CurtainGridsCurtaSystem", "OST_PipeInsulations",
    "OST_DuctInsulations", "OST_DuctLinings",
)

# Measurement of the k2_ar_rd_v6 census: category -> how many elements in
# the DOCUMENT. This is the content of the working drawings for whose sake
# the wave was made.
MEASURED_DOCUMENTATION_CATEGORIES = {
    "OST_Dimensions": 13_905,
    "OST_RoomTags": 11_585,
    "OST_Lines": 9_407,
    "OST_TelephoneDevices": 4_479,
    "OST_MultiCategoryTags": 3_669,
    "OST_MechanicalEquipmentTags": 3_048,
    "OST_DetailComponents": 3_046,
    "OST_TextNotes": 2_697,
    "OST_RoomSeparationLines": 2_313,
    "OST_SpotElevations": 2_292,
    "OST_GenericAnnotation": 1_954,
    "OST_DoorTags": 1_337,
    "OST_MaterialTags": 339,
    "OST_StructuralFramingTags": 161,
    "OST_FloorTags": 147,
    "OST_WallTags": 92,
    "OST_StairsRailingTags": 57,
    "OST_SpotSlopes": 46,
    "OST_AreaTags": 13,
}

# The same measurement, DERIVED AND INTERNAL: we deliberately did not go
# here. It must remain "outside the table" — otherwise the wave would eat
# the admission rule.
MEASURED_DERIVED_CATEGORIES = {
    "OST_AreaSchemeLines": 61_520,
    "OST_SketchLines": 38_093,
    "OST_WeakDims": 19_547,
    "OST_AnalyticalNodes": 2_744,
    "OST_StairsPaths": 689,
}

# 🔴 OST_Constraints WAS REMOVED FROM HERE on 2026-08-22: it stood in the
# list of DERIVED, and that claim is refuted by measurement. The category
# remains outside the table — but for a different reason, and the
# difference decides how to fix it.
#
# WHAT REFUTES IT (three independent numbers):
#   * 156 of 156 cached censuses (`data/model_cache/*.census.json`) give
#     `cat_type == "Annotation"`, and 156 of 156 have `types_top` names of
#     DimensionType; 109 of 156 have types matching the OST_Dimensions
#     types of the same document. Dimension styles are set up by the
#     author, not by Revit;
#   * the MIRROR-SYMMETRY test (the only method by which `content_coverage`
#     justifies the "derived" class: 3051 pipes / 3051 centerlines) — this
#     category fails it: equal to OST_Dimensions 0 times out of 156, in
#     38 of 156 constraints EXCEED the dimensions, the maximum ratio 17.756;
#   * MNVNK: 1,256 constraints against 745 dimensions (1.686); K2: 867
#     against 13,905 (0.062). A 27-fold spread between the two buildings.
#
# The second carrier (`tools/production_technique.py:17,42` — "constraints
# are the project's direct parametrics, and in the decompiler there are 0
# of them") is NOT refuted by measurement and remains the only one.
# `tools/content_coverage.py` moved the row into DECORATION with that
# same edit.
#
# WHAT IS STILL NOT MEASURED: how many of the 1,256 hold geometry
# (`IsLocked`, `References` to model elements). `IsLocked` is not read in
# `kukai/` even once, the ids of these elements are not in the decompiler
# at all — it is settled by one live query, and until then there is no
# row in the extraction table.
MEASURED_AUTHORED_BUT_UNREAD_CATEGORIES = {
    "OST_Constraints": 867,
}


def _document(census: dict[str, int]) -> L0Document:
    """A document WITHOUT extracted elements — census only.

    Zero extracted is chosen deliberately: it shows the REASON in pure
    form. A category outside the table and a category in the table that
    there was no time to read give the same shortfall and must receive
    DIFFERENT reasons.
    """
    return L0Document(
        doc_name="k2-census-shape",
        revit_version="2023",
        units="mm",
        change_stamp="doc-wave-v1",
        levels=(LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0),),
        grids=(GridInfo(id="7001", name="1", p0_mm=[0.0, 0.0, 0.0],
                        p1_mm=[0.0, 9_000.0, 0.0]),),
        rooms=(),
        project_info=ProjectInfo(name="К2", address="а",
                                 building_type_hint=None),
        elements=(),
        category_status=(),
        census=tuple(
            CensusEntry(key=key, name="", count=count)
            for key, count in sorted(census.items())),
    )


class TheResumeFormatIsNotDisturbed(unittest.TestCase):
    """An append to the end must leave other indices in place."""

    def test_every_earlier_category_keeps_its_index(self) -> None:
        before = CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE
        self.assertEqual(
            ex.EXTRACT_CATEGORIES[:len(before)], before,
            "порядок ранее существовавших категорий сдвинулся — это ломает "
            "возобновление уже начатых извлечений и все существующие L0")

    def test_the_table_only_grew(self) -> None:
        self.assertGreater(len(ex.EXTRACT_CATEGORIES),
                           len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE))
        self.assertEqual(len(set(ex.EXTRACT_CATEGORIES)),
                         len(ex.EXTRACT_CATEGORIES),
                         "категория продублирована")

    def test_documentation_categories_live_in_the_tail(self) -> None:
        tail = ex.EXTRACT_CATEGORIES[
            len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE):]
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                self.assertIn(name, ex.EXTRACT_CATEGORIES)
                self.assertIn(
                    name, tail,
                    "новая категория обязана быть ДОПИСАНА в конец, а не "
                    "вставлена в середину")


class EachRowAsksForItsOwnCategory(unittest.TestCase):
    """19 nearly identical rows in a row — perfect ground for copy-paste."""

    def test_collector_names_the_same_category_as_the_spec(self) -> None:
        """The EXACT rule is checked, not something resembling it.

        Not "a name starting with OST_ ⇒ a by-category collector":
        OST_Grids and OST_Levels are deliberately collected by class
        (``.OfClass(typeof(Grid))``) — grids and levels are more reliably
        taken by type than by category. The rule that must not be
        violated here is different: IF a collector walks by
        ``OfCategory``, it must name ITS OWN category. This is exactly
        what catches the copy-paste in nineteen nearly identical rows in a row.
        """
        checked = 0
        for spec in ex._CATEGORY_SPECS:
            if ".OfCategory(" not in spec.collector_cs:
                continue
            with self.subTest(category=spec.name):
                self.assertEqual(
                    spec.collector_cs,
                    f".OfCategory(BuiltInCategory.{spec.name})",
                    "коллектор спрашивает ЧУЖУЮ категорию")
                checked += 1
        self.assertGreaterEqual(checked, len(MEASURED_DOCUMENTATION_CATEGORIES))

    def test_emitted_bodies_stay_safe_and_name_the_category(self) -> None:
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                probe = ex.build_category_probe_cs(name)
                page = ex.build_category_batch_cs(name)
                for body in (probe, page):
                    self.assertIn(f"BuiltInCategory.{name})", body)
                    self.assertIn("WhereElementIsNotElementType()", body)
                    self.assertIsNone(validate_code_safety(body))
                    # Reading remains reading.
                    self.assertNotIn("Transaction", body)


class AnnotationShapedRowsSurviveTheSchema(unittest.TestCase):
    """The main risk of the wave, checked OFFLINE.

    An annotation is not a wall: a dimension has neither a level nor a
    Location, and ``GetTypeId()`` on a line can very well return
    InvalidElementId. If the L0 schema required a non-empty ``type_id`` or
    a level, then the VERY FIRST page of the new category would fail
    parsing, the category would get PARTIAL, and the wave would look like
    a broken compiler instead of honest reading. There is no live Revit
    here, so what is checked is exactly what is checkable offline: a row
    of the shape the bridge would give passes the schema.
    """

    def _row(self, category: str, **overrides: object) -> dict:
        row: dict = {
            "element_id": "123456",
            "category": category,
            "category_ru": "",
            "type_id": "",       # a line without a type — a legitimate case
            "type_name": "",
            "level_id": None,    # an annotation has no level
            "level_name": None,
            "geom_kind": "bbox_only",
            "curve_kind": None,
            "p0_mm": None,
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": [0.0, 0.0, 0.0],
            "bbox_max_mm": [100.0, 10.0, 0.0],
            "host_id": None,
            "params": {},
            "design_option": None,
            "phase_created": None,
            "workset": None,
        }
        row.update(overrides)
        return row

    def test_no_type_and_no_level_is_accepted(self) -> None:
        from kir.decompile.geometry_store import parse_geometry
        from kir.decompile.schema import L0Element

        for category in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=category):
                row = self._row(category)
                row.update(parse_geometry(row).to_element_fields())
                element = L0Element.from_dict(row)
                self.assertEqual(element.category, category)
                self.assertEqual(element.type_id, "")
                self.assertIsNone(element.level_id)

    def test_an_element_revit_gives_no_bbox_for_is_still_an_element(
            self) -> None:
        """A bounding size may not exist at all — that is not a reason to lose the element."""
        from kir.decompile.geometry_store import parse_geometry
        from kir.decompile.schema import L0Element

        row = self._row("OST_Dimensions", bbox_min_mm=None, bbox_max_mm=None)
        row.update(parse_geometry(row).to_element_fields())
        element = L0Element.from_dict(row)
        self.assertEqual(element.element_id, "123456")


class TheCensusNowCountsThemAsRead(unittest.TestCase):
    """A refuting pair: it was "outside the table" — it became read."""

    def test_before_the_wave_every_row_was_invisible_to_reading(self) -> None:
        """The BEFORE state is reproduced with the old table, not from memory."""
        document = _document(MEASURED_DOCUMENTATION_CATEGORIES)
        balance = reconcile_census(
            document,
            table=frozenset(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE))
        self.assertEqual(balance.categories_scanned, 0)
        by_category = {row.category: row for row in balance.rows}
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                self.assertEqual(by_category[name].reason,
                                 UnscannedReason.CATEGORY_OUTSIDE_TABLE)

    def test_after_the_wave_none_of_them_is_outside_the_table(self) -> None:
        document = _document(MEASURED_DOCUMENTATION_CATEGORIES)
        balance = reconcile_census(document)
        self.assertEqual(balance.categories_scanned,
                         len(MEASURED_DOCUMENTATION_CATEGORIES))
        by_category = {row.category: row for row in balance.rows}
        for name in MEASURED_DOCUMENTATION_CATEGORIES:
            with self.subTest(category=name):
                self.assertNotEqual(
                    by_category[name].reason,
                    UnscannedReason.CATEGORY_OUTSIDE_TABLE,
                    "категория в таблице не может числиться вне таблицы")
                # There was no time to read it — but that is a DIFFERENT, honest reason.
                self.assertEqual(by_category[name].reason,
                                 UnscannedReason.CATEGORY_SHORT_READ)

    def test_derived_content_is_still_honestly_outside_the_table(self) -> None:
        """The wave had no right to eat the admission rule.

        Sketches, auto-dimensioning, and analytics are derived from
        another element. Constraints stand next to them by RESULT (also
        outside the table), but for a DIFFERENT reason: they are
        author-created and simply not read (see
        `MEASURED_AUTHORED_BUT_UNREAD_CATEGORIES`). Absence from the
        table for both kinds is not a defect but a decision, and the
        census must keep naming them out loud.
        """
        outside = {**MEASURED_DERIVED_CATEGORIES,
                   **MEASURED_AUTHORED_BUT_UNREAD_CATEGORIES}
        document = _document(outside)
        balance = reconcile_census(document)
        self.assertEqual(balance.categories_scanned, 0)
        by_category = {row.category: row for row in balance.rows}
        for name in outside:
            with self.subTest(category=name):
                self.assertEqual(by_category[name].reason,
                                 UnscannedReason.CATEGORY_OUTSIDE_TABLE)

    def test_the_document_denominator_never_moves(self) -> None:
        """Expanding the table changes what is READ, not the size of the document.

        The denominator of §18.1 is the census, and it concerns the
        document, not our selection. If expanding the table moved
        census_total, any coverage percentage could be improved simply by
        appending a row.
        """
        census = dict(MEASURED_DOCUMENTATION_CATEGORIES)
        census.update(MEASURED_DERIVED_CATEGORIES)
        census.update(MEASURED_AUTHORED_BUT_UNREAD_CATEGORIES)
        document = _document(census)
        before = reconcile_census(
            document,
            table=frozenset(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE))
        after = reconcile_census(document)
        self.assertEqual(before.census_total, after.census_total)
        self.assertEqual(before.census_total, sum(census.values()))
        # But HOW MANY categories are read must grow by exactly the wave.
        self.assertEqual(after.categories_scanned - before.categories_scanned,
                         len(MEASURED_DOCUMENTATION_CATEGORIES))


class AnOlderSnapshotIsNamedNotReinterpreted(unittest.TestCase):
    """The price of expanding the table, named out loud and pinned down by a test.

    THIS CLASS CHANGED ITS DISPOSITION ON 07-29, AND HERE IS WHY. In its
    first edition it required an old frozen copy to REFUSE ("footer
    precedes one or more fixed categories"), and it was right on the main
    point: silently reading an old stream as complete means introducing a
    second dialect where the word "complete" means different things for
    two frozen copies. The mistake was not in the prohibition, but in the
    fact that besides refusal NOTHING else was offered: the dialect had
    no version, so the only way not to lie was not to read.

    The same day showed the price: ``L0_SCHEMA_VERSION`` never changed
    EVEN ONCE, while the table grew SIX times (22 -> 47 -> 48 -> 51 -> 54
    -> 73), meaning every past growth likewise devalued what had
    accumulated — 53 whole frozen copies on disk, taken from live models
    over eleven days, stopped opening. The law of the house answers this
    not with a refusal, but with a name: the dialect changed — the
    version must say so (the same was done for the curtain-wall index,
    6b486c08).

    So now: the frozen copy IS READ, its generation IS NAMED, and the
    categories that were not yet in the table at that time are listed by
    name. The prohibition stayed exactly where it belonged in substance —
    on silent reinterpretation: not one of the missing categories may
    look like "read zero." The ladder of generations and its guard are in
    ``schema.py``; the check on real corpus bytes is in ``test_l0_dialect.py``.
    """

    def _stream(self, path, categories) -> None:
        from kir.decompile.schema import (
            CategoryState, CategoryStatus, L0_SCHEMA_VERSION)
        from kir.decompile.tests.fixtures_decompile import (
            project1_metadata)

        with open(path, "wb") as handle:
            ex._write_record(handle, {
                "record": "header",
                "schema_version": L0_SCHEMA_VERSION,
                "document": ex._parse_metadata(
                    project1_metadata(), "snapshot-v1").metadata_dict(),
            })
            for name in categories:
                ex._write_record(handle, {
                    "record": "category_status",
                    "status": CategoryStatus(
                        category=name, state=CategoryState.COMPLETE,
                        extracted_count=0, expected_count=0).to_dict(),
                })
            ex._write_record(handle, {
                "record": "footer", "stream_complete": True,
                "element_count": 0, "link_count": 0,
                "category_count": len(categories),
            })

    def test_a_stream_written_under_the_old_table_reads_and_is_named(self) -> None:
        """An old frozen copy is read — and names its own generation itself."""
        import tempfile
        from pathlib import Path

        from kir.decompile.schema import (
            categories_outside_dialect, resolve_dialect)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            self._stream(path, CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE)
            reader = ex.L0JSONLReader(path)
            reader.validate()
            expected = resolve_dialect(
                len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE),
                ex.EXTRACT_CATEGORIES)
            self.assertEqual(reader.dialect().version, expected.version)
            # What is missing is NAMED explicitly, not padded out with zeros.
            #
            # What is checked is EQUALITY with the set "everything
            # appended to the table AFTER this generation," not a single
            # wave: after the working-drawings wave the table grew again
            # (08-03 — openings as separate elements), and a constant
            # nailed to one wave would have turned LEGITIMATE growth into
            # a failure. The meaning of the test is not weakened by this:
            # the tail is still checked BY NAME and in full — it is
            # simply taken from the table itself rather than rewritten by
            # hand for every wave.
            absent = categories_outside_dialect(
                reader.dialect(), ex.EXTRACT_CATEGORIES)
            added_since = set(
                ex.EXTRACT_CATEGORIES[
                    len(CATEGORIES_BEFORE_THE_DOCUMENTATION_WAVE):])
            self.assertEqual(set(absent), added_since)
            # ...and inside it BOTH waves must be present by name: the
            # measured working drawings and the openings.
            self.assertLessEqual(
                set(MEASURED_DOCUMENTATION_CATEGORIES), set(absent))
            self.assertLessEqual(
                {"OST_SWallRectOpening", "OST_FloorOpening",
                 "OST_RoofOpening", "OST_ShaftOpening"}, set(absent))

    def test_a_stream_of_an_invented_table_size_is_still_refused(self) -> None:
        """REFUTING: the relaxation concerns GENERATIONS, not just any tail.

        A length that existed in no build at all is not a generation: it
        is unknown what that build considered complete. The guess
        "probably the prefix" would be exactly that same silent
        reinterpretation.
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            self._stream(path, ex.EXTRACT_CATEGORIES[:30])
            with self.assertRaises(ex.ExtractionProtocolError) as caught:
                ex.L0JSONLReader(path).validate()
            self.assertIn("30", str(caught.exception))

    def test_a_stream_written_under_the_current_table_is_accepted(self) -> None:
        """The refuting half: the refusal above is about COMPOSITION, not about everything indiscriminately."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "L0.jsonl"
            self._stream(path, ex.EXTRACT_CATEGORIES)
            ex.L0JSONLReader(path).validate()  # does not raise


if __name__ == "__main__":
    unittest.main()
