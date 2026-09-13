"""The level-READING chain is subject to the same law as the level-WRITING
chain.

THE MEASUREMENT THIS FILE WAS BORN FROM (03.08.2026, a walk over eight real
decompiles on disk). 2367 beams, 116 stairs, and 21 railings have
``level_id: null`` in L0, and this is NOT a property of the models — it is a
property of the reader:

    OST_StructuralFraming  SKLNK 2240/2240 · K2 41 · SOB6.2_AR 86
                           (all 2367 carry STRUCTURAL_BEAM_END0_ELEVATION,
                            i.e. these are genuine beams with a curve)
    OST_Stairs             K2 89/89 · SOB6.2_AR 12/12 · demo 15/15
    OST_StairsRailing      SOB6.2_AR 17/27 · K2 4/203

The house ALREADY KNEW the truth — but only on the write side. A direct
probe on 27.07
(``ir/tests/test_hangs_and_lies.BeamLevelWitnessMustReadTheParameterABeamActuallyHas``)
recorded, on a built beam:

    INSTANCE_REFERENCE_LEVEL_PARAM = 172458 ("L_01_+0.000")
    FAMILY_LEVEL_PARAM   = -1
    SCHEDULE_LEVEL_PARAM = -1
    LEVEL_PARAM          = no such parameter
    fi.LevelId           = -1

The emission witness absorbed this truth (``authoring._level_chain_check``),
the reader did not. One house, two different answers to one question — "what
level does this element have"; ``revit_read_helpers`` exists precisely so
there are not two judges, and its own docstring demands exactly this.

TWO DEFECTS, NOT ONE:

1. the chain has no LINKS in which the level for these categories actually
   sits;
2. the chain BREAKS on the first NON-NULL parameter, rather than the first
   parameter HOLDING A REAL ElementId. On a beam, ``SCHEDULE_LEVEL_PARAM``
   exists and equals -1 — meaning even a link appended at the tail would be
   unreachable. This is exactly the distinction
   ``authoring._level_chain_check`` names in words: "'a parameter being
   filled' and 'a parameter existing' are different things".

WHY NEW LINKS GO STRICTLY AT THE TAIL. The chain short-circuits: the winner
is the first link holding a real id. All previous links stay in their
previous places, so an element whose level used to be found still finds
EXACTLY THE SAME level. Appending at the tail cannot change an answer —
only supply an answer where there was none. This order is exactly what is
checked here, so the fix cannot be "improved" by reordering.
"""
from __future__ import annotations

import pathlib
import sqlite3
import unittest

from kir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS


#: Previous links — in their previous order. The list exists so the test on
#: the tail is structural, not a list of strings.
LEGACY_LEVEL_BIPS = (
    "WALL_BASE_CONSTRAINT",
    "LEVEL_PARAM",
    "SCHEDULE_LEVEL_PARAM",
    "FAMILY_LEVEL_PARAM",
)

#: New links. Each one has the category it rescues, and a measurement.
ADDED_LEVEL_BIPS = (
    "INSTANCE_REFERENCE_LEVEL_PARAM",       # beams/braces (measurement of 27.07)
    "STAIRS_BASE_LEVEL_PARAM",              # stairs (116 pcs. across 3 decompiles)
    "STAIRS_RAILING_BASE_LEVEL_PARAM",      # railings (21 pcs. across 2 decompiles)
)

TRAP_INDEX = pathlib.Path(
    "/opt/kukai-rebuild1/backend/data/api_traps/revit_api_traps.sqlite")
SHIPPED_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")


class ReadChainKnowsWhereTheseCategoriesKeepTheirLevel(unittest.TestCase):
    def test_beam_reference_level_parameter_is_a_link(self) -> None:
        """2367 beams on disk. A beam's level lies ONLY here."""
        self.assertIn("INSTANCE_REFERENCE_LEVEL_PARAM", ELEMENT_LEVEL_HELPERS_CS)

    def test_stairs_base_level_parameter_is_a_link(self) -> None:
        """116 stairs. Without a level the node goes into
        ``unassigned-level`` and ``_semantic_fold`` cannot see it — which is
        why the ``core`` label was produced not once across 52 trees."""
        self.assertIn("STAIRS_BASE_LEVEL_PARAM", ELEMENT_LEVEL_HELPERS_CS)

    def test_railing_base_level_parameter_is_a_link(self) -> None:
        self.assertIn(
            "STAIRS_RAILING_BASE_LEVEL_PARAM", ELEMENT_LEVEL_HELPERS_CS)


class ALinkHoldingNoElementDoesNotEndTheChain(unittest.TestCase):
    """`HasValue` is true even for InvalidElementId — measured on a beam.

    A link is accepted ONLY if it holds a real ElementId; otherwise the
    chain breaks on an empty parameter and the tail is unreachable. The same
    law as in ``authoring._level_chain_check``.
    """

    def test_chain_advance_tests_for_a_real_element_id(self) -> None:
        self.assertIn("InvalidElementId", ELEMENT_LEVEL_HELPERS_CS)
        # The transition condition must look at the VALUE, not merely at
        # whether the parameter exists.
        self.assertIn("AsElementId()", ELEMENT_LEVEL_HELPERS_CS)
        self.assertNotIn(
            "if (__levelParam == null)\n", ELEMENT_LEVEL_HELPERS_CS,
            "переход по одному лишь null — тот самый обрыв на -1")


class NewLinksAreStrictlyAtTheTail(unittest.TestCase):
    def test_every_legacy_link_precedes_every_added_link(self) -> None:
        for legacy in LEGACY_LEVEL_BIPS:
            self.assertIn(legacy, ELEMENT_LEVEL_HELPERS_CS, legacy)
        for added in ADDED_LEVEL_BIPS:
            self.assertIn(added, ELEMENT_LEVEL_HELPERS_CS, added)
        last_legacy = max(
            ELEMENT_LEVEL_HELPERS_CS.index(bip) for bip in LEGACY_LEVEL_BIPS)
        first_added = min(
            ELEMENT_LEVEL_HELPERS_CS.index(bip) for bip in ADDED_LEVEL_BIPS)
        self.assertLess(
            last_legacy, first_added,
            "новое звено раньше прежнего = элемент, у которого уровень "
            "находился, может получить ДРУГОЙ уровень")

    def test_legacy_links_keep_their_relative_order(self) -> None:
        positions = [ELEMENT_LEVEL_HELPERS_CS.index(bip)
                     for bip in LEGACY_LEVEL_BIPS]
        self.assertEqual(positions, sorted(positions))


class EveryLinkExistsOnEveryShippedVersion(unittest.TestCase):
    """A Revit API member name is checked against the trap index, not from
    memory."""

    def test_all_chain_bips_ship_on_all_six(self) -> None:
        if not TRAP_INDEX.exists():
            self.skipTest(f"индекса ловушек нет: {TRAP_INDEX}")
        connection = sqlite3.connect(f"file:{TRAP_INDEX}?mode=ro", uri=True)
        try:
            for bip in LEGACY_LEVEL_BIPS + ADDED_LEVEL_BIPS:
                row = connection.execute(
                    "select versions from member where owner = ? "
                    "and simple = ?",
                    ("Autodesk.Revit.DB.BuiltInParameter", bip),
                ).fetchone()
                self.assertIsNotNone(row, f"{bip} нет в индексе ловушек")
                shipped = tuple(row[0].split(","))
                self.assertEqual(
                    shipped, SHIPPED_VERSIONS,
                    f"{bip} живёт не на всех шести: {row[0]}")
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()


class ТретийНосительЦепиУровняСнят(unittest.TestCase):
    """🔴 MEASUREMENT OF 25.08.2026: THE LEVEL-READING CHAIN HAD THREE
    CARRIERS.

    The authority (`revit_read_helpers.ELEMENT_LEVEL_HELPERS_CS`) holds
    seven links. The copy in the compiler (`_PREAMBLE.__LevelNameOf`) held
    FOUR, and its own comment claimed "the SAME 4-BIP fallback chain", while
    the authority's docstring says "copying that chain would create two
    judges".

    What was missing from the copy:
        INSTANCE_REFERENCE_LEVEL_PARAM · STAIRS_BASE_LEVEL_PARAM
        STAIRS_RAILING_BASE_LEVEL_PARAM

    And one more, quieter, discrepancy: the authority branches through
    `__holdsLevel` (the parameter must be of the ElementId kind), the copy
    through `!__lp.HasValue`. The difference shows on a beam: the copy's
    chain stops at SCHEDULE_LEVEL_PARAM (`HasValue=True`, `AsElementId=-1`)
    and returns an EMPTY string.

    THE COST, MEASURED ON 03.08: 2367 beams, 116 stairs, 21 railings with
    `level_id=null`. A `where level_name=…` query was silently dropping all
    of them, and the `level_name` field was returning an empty string — even
    though the extractor, on the SAME element, returns the real level. A
    silently wrong answer about the model, i.e. the worst class under the
    project's constitution.
    """

    @staticmethod
    def _уровневые_биты(текст: str) -> set[str]:
        import re
        return set(re.findall(r"BuiltInParameter\.(\w*LEVEL\w*)", текст))

    def test_компилятор_несёт_авторитет_дословно(self):
        from kir import compiler
        from kir.revit_read_helpers import element_level_helpers_cs
        self.assertIn(
            element_level_helpers_cs("doc"), compiler._PREAMBLE,
            "у двери запросов своя цепочка чтения уровня: два судьи одной "
            "величины, и они уже разошлись на три звена")

    def test_у_двери_запросов_нет_второй_цепочки(self):
        from kir import compiler
        from kir.revit_read_helpers import element_level_helpers_cs
        свои = self._уровневые_биты(
            compiler._PREAMBLE.replace(element_level_helpers_cs("doc"), ""))
        self.assertEqual(
            свои, set(),
            f"после авторитета в преамбуле осталась своя цепочка: {свои}")

    def test_КОНТРОЛЬ_авторитет_по_прежнему_несёт_все_семь_звеньев(self):
        """PASS control: checking the copy against the authority is
        pointless if the authority itself has been impoverished. Seven
        links — the measurement of 03.08, it is in the docstring above."""
        from kir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS
        for бит in ("WALL_BASE_CONSTRAINT", "LEVEL_PARAM",
                    "SCHEDULE_LEVEL_PARAM", "FAMILY_LEVEL_PARAM",
                    "INSTANCE_REFERENCE_LEVEL_PARAM",
                    "STAIRS_BASE_LEVEL_PARAM",
                    "STAIRS_RAILING_BASE_LEVEL_PARAM"):
            with self.subTest(звено=бит):
                self.assertIn(бит, ELEMENT_LEVEL_HELPERS_CS)
