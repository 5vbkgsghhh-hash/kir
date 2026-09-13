"""The zone-layout discipline is taken from the extractor's table, not
from its own dictionary inside fold.py.

Trigger (07-28): the package held THREE sources of truth for one
notion, "discipline" — `registry_base.DISCIPLINES` (a closed dictionary
of values), the `CategorySpec.discipline` column in
`decompile/extract.py` (covers all categories of the table), and
`_CATEGORY_DISCIPLINE` inside `fold.py`. The third knew 17 categories
out of 47 and spoke its own lexicon
("architecture"/"structure"/"coordination"), so ALL 25 categories of
engineering disciplines — light fixtures, pipe fittings, cable trays —
fell into "unknown" in the zone layout. The entire electrical
discipline looked like "we don't know what this is," even though the
extractor's table knows everything about it.

The tests below pin down the law, not the current output: the layout
must name the discipline exactly as the extractor's table names it,
and stay silent ("unknown") only where the table itself is genuinely silent.
"""
from __future__ import annotations

import unittest

from kir.decompile import fold as fold_module
from kir.decompile.fold import TreeNode, fold_document
from kir.decompile.lift import lift_document
from kir.registry_base import DISCIPLINES
from kir.decompile.tests.test_fold import (  # noqa: E402
    _curve_element,
    _document,
    _kind,
    _point_element,
)

_LEVEL = ("1", "L1", 0.0)


def _discipline_labels(tree: TreeNode) -> set[str]:
    return {
        node["macro"]["discipline"]
        for node in _kind(tree, "group")
        if node["macro"] and node["macro"].get("type") == "discipline"
    }


def _zoned(rows: list[dict]) -> TreeNode:
    # rooms=[] — a floor with no rooms, semantic layout is impossible,
    # and FOLD falls into the zone branch, where the breakdown by
    # discipline lives.
    document = _document([_LEVEL], rows, rooms=[])
    return fold_document(document, lift_document(document))


class ZonedDisciplineFromExtractTableTests(unittest.TestCase):
    def test_engineering_category_is_not_unknown(self) -> None:
        # A refuting case: a light fixture is electrical. In the
        # extractor's table, OST_LightingFixtures has
        # discipline="electrical"; the layout must read the same row,
        # not guess from its own list.
        tree = _zoned([
            _point_element("OST_LightingFixtures", 15_000, _LEVEL,
                           (1_000.0, 1_000.0, 0.0)),
        ])

        labels = _discipline_labels(tree)

        self.assertEqual(labels, {"electrical"})
        self.assertNotIn(
            "unknown", labels,
            "категория есть в таблице экстрактора — «не знаем» здесь ложь")

    def test_every_engineering_section_is_named(self) -> None:
        # One representative from each engineering discipline: the
        # layout must name all three, not dump them into one heap.
        tree = _zoned([
            _point_element("OST_LightingFixtures", 15_010, _LEVEL,
                           (1_000.0, 1_000.0, 0.0)),
            _point_element("OST_PipeFitting", 15_011, _LEVEL,
                           (1_200.0, 1_000.0, 0.0)),
            _point_element("OST_DuctFitting", 15_012, _LEVEL,
                           (1_400.0, 1_000.0, 0.0)),
            _point_element("OST_StructuralTruss", 15_013, _LEVEL,
                           (1_600.0, 1_000.0, 0.0)),
            _point_element("OST_Ceilings", 15_014, _LEVEL,
                           (1_800.0, 1_000.0, 0.0)),
        ])

        self.assertEqual(
            _discipline_labels(tree),
            {"electrical", "plumbing", "mechanical", "structural",
             "architectural"})

    def test_lexicon_is_the_package_wide_closed_set(self) -> None:
        # There is one lexicon for the whole package. The former
        # "architecture"/"structure" from fold.py's own dictionary are
        # not part of DISCIPLINES and must not appear on any document.
        tree = _zoned([
            _curve_element("OST_Walls", 15_020, _LEVEL,
                           (0.0, 0.0, 0.0), (4_000.0, 0.0, 0.0)),
            _point_element("OST_StructuralColumns", 15_021, _LEVEL,
                           (500.0, 500.0, 0.0)),
            _curve_element("OST_PipeCurves", 15_022, _LEVEL,
                           (0.0, 800.0, 0.0), (4_000.0, 800.0, 0.0)),
            _point_element("OST_LightingFixtures", 15_023, _LEVEL,
                           (900.0, 900.0, 0.0)),
        ])

        labels = _discipline_labels(tree)

        self.assertTrue(labels)
        self.assertLessEqual(labels, set(DISCIPLINES) | {"unknown"})
        self.assertNotIn("architecture", labels)
        self.assertNotIn("structure", labels)
        self.assertNotIn("coordination", labels)

    def test_grid_is_shared_not_a_private_coordination_label(self) -> None:
        # Grids/levels are marked "shared" in the extractor's table —
        # "belongs to everyone" — not a separate "coordination"
        # discipline, which does not exist in the package's lexicon.
        tree = _zoned([
            _curve_element("OST_Grids", 15_030, _LEVEL,
                           (0.0, 0.0, 0.0), (6_000.0, 0.0, 0.0)),
        ])

        self.assertEqual(_discipline_labels(tree), {"shared"})

    def test_category_outside_the_table_stays_unknown(self) -> None:
        # An honest "we don't know" remains exactly where the table is
        # silent: guessing from the category name would be worse than emptiness.
        row = _point_element("OST_Furniture", 15_040, _LEVEL,
                             (1_000.0, 1_000.0, 0.0))
        row["category"] = "OST_SomethingTheTableDoesNotKnow"

        self.assertEqual(_discipline_labels(_zoned([row])), {"unknown"})

    def test_fold_holds_no_private_discipline_dictionary(self) -> None:
        # The law "there must not be a second dictionary for one
        # notion" is checked structurally, otherwise it survives only
        # in a reviewer's memory.
        self.assertFalse(
            hasattr(fold_module, "_CATEGORY_DISCIPLINE"),
            "fold.py снова завёл собственную таблицу разделов")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
