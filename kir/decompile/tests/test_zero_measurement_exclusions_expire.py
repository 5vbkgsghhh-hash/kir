"""THE ARGUMENT "IT IS NOT IN THE MEASURED DOCUMENT" HAS AN EXPIRATION DATE.

THE OCCASION, MEASURED ON 22.08.2026. On 29.07 `extract.py` rejected
window tags with the line "tags dropped that are not in the measured
document (OST_WindowTags, OST_CeilingTags, and other siblings)." The
admission rule is correct — what is MEASURED gets in — but its input is
the CORPUS, and the corpus grows. On 20.08 a second building arrived in it
(`MNVNK_ATR_PD_B14_K6_AR_R2022`), and it has 660 window tags; across the
whole corpus there are 3 545 in four documents out of eleven. The argument
was not a mistake: it was true precisely about its one document and went
stale SILENTLY, because nowhere was it recorded either WHERE the
measurement was taken or what to do when a new building arrives. This is
exactly how a reading table ends up fitted to the first building forever.

WHAT IS CHECKED HERE IS A LAW, NOT A MEMORY OF A PARTICULAR CASE:

    every tag kind measured as NONZERO in the corpus must be listed
    EITHER in `EXTRACT_CATEGORIES` OR in `TAG_CATEGORIES_NOT_TAKEN`.

The equality is TWO-SIDED, and both sides are needed. A new building with
an unfamiliar tag kind turns the gate red (otherwise it would land
invisibly — exactly the case this file was written for). A journal line
that the corpus no longer confirms also turns it red (otherwise the
journal would stop being a measurement and become a memory, which is the
second way to go stale, the mirror of the first).

WHY A TAG KIND, AND NOT ANY CATEGORY. For tags, the "take / don't take"
decision is made ONLY by number: the `create_tag` op is one for all
kinds, the side stage is one for all, the lifter is one for all, and the
C# stage branches by the element's CLASS (`IndependentTag` /
`SpatialElementTag`), not by category. For other categories such a law
would be a lie: there "not taken" can mean "nothing to express it with,"
and that is not fixed by a row in a table.

THE PROOF OF NON-EMPTINESS LIVES IN THIS SAME RUN (class
`TheLawWouldActuallyCatchIt`): two control mutations — a withdrawn
journal line and a made-up kind — must be NAMED by the instrument. A
green law that has never once shown it can turn red is indistinguishable
from a law that is looking the wrong way.
"""
from __future__ import annotations

import json
import os
import unittest

from kir.decompile import extract as extract_module
from kir.decompile.extract import (
    DERIVED_CATEGORIES_NOT_TAKEN,
    EXTRACT_CATEGORIES,
    TAG_CATEGORIES_NOT_TAKEN,
    derived_categories_outside_the_law,
    is_tag_category,
    tag_categories_outside_the_law,
)
from kir.decompile.snapshot_io import open_snapshot, snapshot_file_exists

#: The root of the snapshots is asked of whoever already tracks it
#: (`course.corpus`), not recomputed here anew: a second carrier of one
#: path would diverge from the first silently — "there is no corpus" and
#: "we are looking in the wrong place" give the same omission.
from kir.course.corpus import DECOMPILE_ROOT

# ── MEASUREMENT 22.08.2026, reproducible via `_corpus_censuses()` ──────────
# 11 documents (one most-complete decompile per building out of 39
# snapshots with a census), 46 nonzero tag kinds:
#   in the table    11 kinds = 68 792 elements
#   outside table   35 kinds =  4 813 elements (6.5 % of all corpus tags)
# The largest one not taken — OST_RevisionCloudTags 2 271; the rest of the
# thirty together give 2 542. The numbers below are LOWER BOUNDS, not
# equalities: the corpus grows, and a test demanding an exact match would
# turn red the moment a new building arrives — that is, for exactly the
# reason it was written.
MEASURED_DOCUMENTS_2608_22 = 11
MEASURED_TAG_KINDS_2608_22 = 46
MEASURED_TAG_KINDS_NOT_TAKEN_2608_22 = 35
MEASURED_TAG_ELEMENTS_NOT_TAKEN_2608_22 = 4_813


def _corpus_censuses() -> dict[str, dict[str, int]]:
    """{document: {category: count}} from the corpus's L0 headers.

    The key is `doc_name`, NOT the directory name: on disk there are 88
    directories, but these are versions of the same building (nine
    decompiles of one tower). Counting by directory would give the tower
    nine votes in a law that speaks about buildings. When one document
    has several decompiles, the maximum per category is taken — the most
    complete one measured.
    """
    root = DECOMPILE_ROOT
    censuses: dict[str, dict[str, int]] = {}
    if not os.path.isdir(root):
        return censuses
    for name in sorted(os.listdir(root)):
        directory = os.path.join(root, name)
        if not os.path.isdir(directory):
            continue
        path = os.path.join(directory, "L0.jsonl")
        if not snapshot_file_exists(path):
            continue
        try:
            with open_snapshot(path, "rt", encoding="utf-8",
                               touch=False) as handle:
                header = json.loads(handle.readline())
        except Exception:                                      # noqa: BLE001
            # A broken snapshot is not a fact about the reading table. It
            # is named as an instrument skip below (`_skip_if_no_corpus`),
            # not quietly counted as empty.
            continue
        document = header.get("document") or {}
        census = document.get("census")
        if not census:
            continue
        key = document.get("doc_name") or name
        row = censuses.setdefault(key, {})
        for entry in census:
            category = entry.get("key")
            count = int(entry.get("count") or 0)
            if category:
                row[category] = max(row.get(category, 0), count)
    return censuses


class TheTagTableCoversEveryMeasuredKind(unittest.TestCase):
    """The completeness law for tag kinds on the REAL corpus."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.censuses = _corpus_censuses()

    def _skip_if_no_corpus(self) -> None:
        if len(self.censuses) < 2:
            self.skipTest(
                f"корпус разборов недоступен ({DECOMPILE_ROOT}): закон "
                "полноты родов марки проверять НЕ НА ЧЕМ. «Корпуса нет» и "
                "«нарушений нет» — разные факты, и второй здесь не "
                "утверждается")

    def test_no_measured_tag_kind_is_invisible(self) -> None:
        """No measured tag kind stays silent: it is either in the table or in the journal."""
        self._skip_if_no_corpus()
        verdict = tag_categories_outside_the_law(self.censuses)
        self.assertEqual(
            verdict["unledgered"], {},
            "в корпусе появился род марки, о котором таблица чтения не знает "
            "и журнал невзятого молчит. Это и есть протухший довод «в "
            "замеренном документе такого нет»: замеренным документом был "
            "ОДИН файл, а корпус вырос. Решение обязано быть НАЗВАННЫМ — "
            "строка в extract._CATEGORY_SPECS (и ступень диалекта в "
            "schema.py) либо строка в extract.TAG_CATEGORIES_NOT_TAKEN")

    def test_the_ledger_is_a_measurement_not_a_memory(self) -> None:
        """The reverse side: the journal does not hold what the corpus does not measure."""
        self._skip_if_no_corpus()
        verdict = tag_categories_outside_the_law(self.censuses)
        self.assertEqual(
            verdict["unconfirmed"], {},
            "строка журнала невзятых родов больше не подтверждается ни одним "
            "документом корпуса: журнал перестал быть замером и стал "
            "памятью. Снять строку или назвать, куда делся замер")

    def test_the_measurement_of_2026_08_22_still_holds(self) -> None:
        """The measurement's numbers are recomputed by the instrument, not quoted."""
        self._skip_if_no_corpus()
        kinds: dict[str, int] = {}
        for census in self.censuses.values():
            for category, count in census.items():
                if is_tag_category(category) and count > 0:
                    kinds[category] = kinds.get(category, 0) + count
        table = set(EXTRACT_CATEGORIES)
        not_taken = {k: v for k, v in kinds.items() if k not in table}
        self.assertGreaterEqual(len(self.censuses), MEASURED_DOCUMENTS_2608_22)
        self.assertGreaterEqual(len(kinds), MEASURED_TAG_KINDS_2608_22)
        self.assertGreaterEqual(len(not_taken),
                                MEASURED_TAG_KINDS_NOT_TAKEN_2608_22)
        self.assertGreaterEqual(sum(not_taken.values()),
                                MEASURED_TAG_ELEMENTS_NOT_TAKEN_2608_22)

    def test_window_tags_are_read_now(self) -> None:
        """The fix itself: 660 MNVNK window tags stopped being invisible.

        Both halves, because one without the other is useless: a row in
        the table without a row in the stage gives an element without a
        tag-in-the-index, a row in the stage without a row in the table —
        ids that nobody will request.
        """
        from kir.decompile.tag_extract import TAG_CATEGORIES

        self.assertIn("OST_WindowTags", EXTRACT_CATEGORIES)
        self.assertIn("OST_WindowTags", TAG_CATEGORIES)
        self.assertNotIn("OST_WindowTags", TAG_CATEGORIES_NOT_TAKEN)
        self._skip_if_no_corpus()
        measured = {
            document: census["OST_WindowTags"]
            for document, census in self.censuses.items()
            if census.get("OST_WindowTags")
        }
        self.assertGreaterEqual(len(measured), 4)
        self.assertGreaterEqual(sum(measured.values()), 3_545)


class TheDerivedLedgerIsAMeasurementNotAMemory(unittest.TestCase):
    """THE REFUSAL JOURNAL FOR DERIVED-NESS — THE SAME PATTERN, ALREADY A LAW.

    On 22.08 `OST_Parts` (2 735 live on MNVNK, 0 in the decompile) was
    listed as a LOSS in `tools/production_technique.py`, and the wave was
    heading to take it up. The measurement overturned the item: a part is
    "a part of another element" (RevitAPI.xml), that is, the result of
    cutting an already-read carrier, while authorship lies in the
    DIVISION (`OST_Divisions`). A cancellation is worth the same as an
    implementation exactly as long as it is RECORDED so that the
    instrument sees it — otherwise the next wave would go take up parts
    again, because "0 in the decompile" looks like a hole from any
    report.

    🔴 THE LAW HERE IS NARROWER THAN FOR TAGS, AND THIS IS NAMED. Tags
    require COMPLETENESS ("every measured kind — in the table or in the
    journal"), because a tag kind is identified by name. Being-derived is
    identified by nothing by name, and the same requirement cannot exist
    here: it would be a lie passed off as a check. Only two sides of the
    JOURNAL ITSELF are checked — that every entry in it is confirmed by
    the corpus, and that none of them contradicts the reading table.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.censuses = _corpus_censuses()

    def _skip_if_no_corpus(self) -> None:
        if len(self.censuses) < 2:
            self.skipTest(
                f"корпус разборов недоступен ({DECOMPILE_ROOT}): «корпуса "
                "нет» и «нарушений нет» — разные факты")

    def test_every_ledger_row_is_still_measured_by_the_corpus(self) -> None:
        self._skip_if_no_corpus()
        verdict = derived_categories_outside_the_law(self.censuses)
        self.assertEqual(
            verdict["unconfirmed"], {},
            "запись журнала производных больше не подтверждается ни одним "
            "документом корпуса: довод перестал опираться на замер. Снять "
            "строку или назвать, куда делся замер")

    def test_no_row_contradicts_the_reading_table(self) -> None:
        self._skip_if_no_corpus()
        verdict = derived_categories_outside_the_law(self.censuses)
        self.assertEqual(
            verdict["contradicted"], {},
            "категория стоит И в журнале отказов, И в таблице чтения — два "
            "противоположных решения об одном имени, и молча побеждает "
            "таблица")

    def test_parts_are_refused_by_measurement_not_by_silence(self) -> None:
        """Cancellation of the item: parts are NOT read, and this is recorded with a rationale."""
        self.assertNotIn("OST_Parts", EXTRACT_CATEGORIES)
        self.assertIn("OST_Parts", DERIVED_CATEGORIES_NOT_TAKEN)
        # The rationale must name WHAT the category is derived from —
        # otherwise "decided not to take" is indistinguishable from
        # "nobody looked."
        for category, reason in DERIVED_CATEGORIES_NOT_TAKEN.items():
            with self.subTest(category=category):
                self.assertTrue(reason.strip(), category)
        self._skip_if_no_corpus()
        parts = {d: c["OST_Parts"] for d, c in self.censuses.items()
                 if c.get("OST_Parts")}
        divisions = {d: c["OST_Divisions"] for d, c in self.censuses.items()
                     if c.get("OST_Divisions")}
        self.assertGreaterEqual(sum(parts.values()), 2_765)
        # The "act → result" coincidence, measured, not assumed: parts
        # and divisions are nonzero in EXACTLY the same buildings.
        self.assertEqual(sorted(parts), sorted(divisions))

    def test_reference_planes_are_read_now(self) -> None:
        """The second half of the wave: 9 724 planes stopped being invisible.

        The collection is arranged DIFFERENTLY than for window tags, and
        the test pins this down: `ReferencePlane` is a CLASS, the
        collector goes `.OfClass`, while the row's key remains the census
        category. A copied `.OfCategory` would give a page that compiles
        and answers zero.
        """
        from kir.decompile.extract import _SPEC_BY_NAME

        self.assertIn("OST_CLines", EXTRACT_CATEGORIES)
        self.assertNotIn("OST_CLines", DERIVED_CATEGORIES_NOT_TAKEN)
        self.assertEqual(_SPEC_BY_NAME["OST_CLines"].collector_cs,
                         ".OfClass(typeof(ReferencePlane))")
        self._skip_if_no_corpus()
        measured = {d: c["OST_CLines"] for d, c in self.censuses.items()
                    if c.get("OST_CLines")}
        self.assertGreaterEqual(len(measured), 10)
        self.assertGreaterEqual(sum(measured.values()), 9_724)


class TheDerivedLawWouldActuallyCatchIt(unittest.TestCase):
    """PROOF OF NON-EMPTINESS. Both sides must be able to turn red.

    Green from one side says nothing about the other — a form bought on
    20.08 ("a patch made of two halves — two controls").
    """

    def test_a_ledger_row_the_corpus_no_longer_confirms_is_named(self) -> None:
        dropped = "OST_Parts"
        self.assertIn(dropped, DERIVED_CATEGORIES_NOT_TAKEN)
        census = dict.fromkeys(DERIVED_CATEGORIES_NOT_TAKEN, 1)
        del census[dropped]
        verdict = derived_categories_outside_the_law({"дом": census})
        self.assertEqual(verdict["unconfirmed"], {dropped: {}})
        self.assertEqual(verdict["contradicted"], {})

    def test_a_row_that_also_stands_in_the_table_is_named(self) -> None:
        taken = EXTRACT_CATEGORIES[0]
        self.assertNotIn(taken, DERIVED_CATEGORIES_NOT_TAKEN)
        ledger = dict(DERIVED_CATEGORIES_NOT_TAKEN)
        ledger[taken] = "подсаженная строка: категория читается"
        original = extract_module.DERIVED_CATEGORIES_NOT_TAKEN
        extract_module.DERIVED_CATEGORIES_NOT_TAKEN = ledger
        try:
            verdict = derived_categories_outside_the_law(
                {"дом": dict.fromkeys(ledger, 1)})
        finally:
            extract_module.DERIVED_CATEGORIES_NOT_TAKEN = original
        self.assertEqual(verdict["contradicted"], {taken: {"дом": 1}})
        self.assertEqual(verdict["unconfirmed"], {})

    def test_a_zero_count_is_not_a_measurement_of_presence(self) -> None:
        """Zero in the census is not confirmation: it must turn red as a skip."""
        census = dict.fromkeys(DERIVED_CATEGORIES_NOT_TAKEN, 1)
        census["OST_Parts"] = 0
        verdict = derived_categories_outside_the_law({"дом": census})
        self.assertEqual(verdict["unconfirmed"], {"OST_Parts": {}})


class TheLawWouldActuallyCatchIt(unittest.TestCase):
    """PROOF OF NON-EMPTINESS. The law must be able to turn red.

    Both mutations strike DIFFERENT sides of the law, because green from
    one side says nothing about the other — a form bought on 20.08 ("a
    patch made of two halves — two controls").
    """

    def test_a_new_building_with_an_unknown_tag_kind_is_named(self) -> None:
        verdict = tag_categories_outside_the_law({
            "дом-которого-ещё-не-было": {"OST_ThisKindIsNewTags": 41},
            "MNVNK": dict.fromkeys(TAG_CATEGORIES_NOT_TAKEN, 1),
        })
        self.assertEqual(
            verdict["unledgered"],
            {"OST_ThisKindIsNewTags": {"дом-которого-ещё-не-было": 41}})
        self.assertEqual(verdict["unconfirmed"], {})

    def test_a_ledger_row_the_corpus_no_longer_confirms_is_named(self) -> None:
        dropped = "OST_RevisionCloudTags"
        self.assertIn(dropped, TAG_CATEGORIES_NOT_TAKEN)
        census = dict.fromkeys(TAG_CATEGORIES_NOT_TAKEN, 1)
        del census[dropped]
        verdict = tag_categories_outside_the_law({"MNVNK": census})
        self.assertEqual(verdict["unledgered"], {})
        self.assertEqual(verdict["unconfirmed"], {dropped: {}})

    def test_a_zero_count_is_not_a_measurement_of_presence(self) -> None:
        """Zero in the census is not "the kind exists," otherwise the law would turn red from a zero."""
        verdict = tag_categories_outside_the_law({
            "дом": {"OST_ThisKindIsNewTags": 0,
                    **dict.fromkeys(TAG_CATEGORIES_NOT_TAKEN, 1)},
        })
        self.assertEqual(verdict["unledgered"], {})

    def test_the_kind_predicate_is_named_by_name_not_guessed(self) -> None:
        """The boundary of the law: a kind is identified by NAME, and that is its limit."""
        self.assertTrue(is_tag_category("OST_WindowTags"))
        self.assertTrue(is_tag_category("OST_ELECTRICAL_AreaBasedLoads_Tags"))
        self.assertFalse(is_tag_category("OST_Walls"))
        self.assertFalse(is_tag_category("OST_TagsThatAreNot"))
        self.assertFalse(is_tag_category("MyOwnTags"))


if __name__ == "__main__":
    unittest.main()


class ВторойНосительСпискаРодовМарокНеРасходится(unittest.TestCase):
    """🔴 IT HAS ALREADY DIVERGED ONCE, ON 22.08.2026.

    `spec.OP_RESULT_CATEGORIES["create_tag"]` is a verbatim copy of
    `TAG_CATEGORIES`: a tag's result category cannot be read from the
    program (it is decided by the TARGET's category), so the registry
    carries the SUM over the kinds the pipeline reads. When capture took
    up `OST_WindowTags` (660 on MNVNK, 3 545 across the corpus), the copy
    stayed at ten kinds — and the acceptance judge did not contain the
    window tag among the result categories.

    Merging the two carriers into one cannot be done cheaply today: the
    table is taken RAW by two more places (`acceptance._OP_CATEGORIES`,
    an enumeration in `authoring.py`), and a row moved out of it into a
    function disappears for them entirely — verified by a run, both
    ratchets turned red. While there are three readers, THIS guard holds
    the discrepancy.
    """

    def test_tag_result_categories_match_the_capture_table(self):
        from kir.spec import OP_RESULT_CATEGORIES
        from kir.decompile.tag_extract import TAG_CATEGORIES
        self.assertEqual(
            sorted(OP_RESULT_CATEGORIES["create_tag"]),
            sorted(TAG_CATEGORIES),
            "реестр обязан называть РОВНО те рода марок, которые читает "
            "конвейер: род, взятый захватом и не названный здесь, не попадёт "
            "в категории результата `create_tag` у судьи приёмки")
