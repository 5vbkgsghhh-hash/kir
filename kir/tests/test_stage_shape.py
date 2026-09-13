"""THE BUILDING BY SHAPE: O(changes), and this has a CEILING.

🔴 THE MEASUREMENT THIS MODULE WAS BUILT FOR (21.08.2026, MNVNK, 33 944
elements). The 21.08 repeat-folding gave −58% and was exhausted: what
remains in the receipt are real coordinates and ids. Beyond this, what
shrinks it further is not compression but a different data model.

    change scenario                       cells  delta KB  per-elem KB  gain
    one new floor, one category               1       0.3        280.4  1055x
    1200 scattered across existing ones      245      32.3        264.0     8x
    the whole model rebuilt (worst case)     398      52.6       7625.2   145x
    12 elements, pinpoint                     12       1.7          2.6     2x

🔴 THE MAIN POINT HERE IS NOT "1055x". The gain depends on the SHAPE of the
change and drops to twice on a pinpoint edit — quoting a single number would
mean picking a convenient one. The main point is the CEILING: the delta is
bounded by 398 cells (52.6 KB) for ANY size of change, because the number of
"floor x category" cells in a building is finite. A per-element receipt has
no ceiling at all: the whole model is 7.6 MB, and it grows linearly.

Hence the reading rule the module must hold onto: at a STAGE boundary, look
at the shape; on a pinpoint edit, look at the receipt. Shape does NOT
REPLACE the receipt.
"""
from __future__ import annotations

import json
import unittest

from kir.stage_shape import (NO_LEVEL, BuildingShape, delta_note_ru,
                                  shape_delta, shape_of)


def _row(cat="OST_Walls", level="Э1", box=True):
    row = {"category": cat, "level_name": level}
    if box:
        row["bbox_min_mm"] = [0.0, 0.0, 0.0]
        row["bbox_max_mm"] = [1000.0, 200.0, 3000.0]
    return row


class TheShapeIsBoundedByCellsNotElements(unittest.TestCase):

    def test_a_thousand_walls_on_one_level_are_ONE_cell(self):
        shape = shape_of([_row() for _ in range(1000)])
        self.assertEqual(len(shape.cells), 1)
        self.assertEqual(shape.seen, 1000)

    def test_the_cell_carries_the_MERGED_bbox(self):
        rows = [_row(), dict(_row(), bbox_min_mm=[-500.0, 0.0, 0.0],
                             bbox_max_mm=[0.0, 0.0, 9000.0])]
        cell = next(iter(shape_of(rows).cells.values()))
        self.assertEqual(cell.count, 2)
        self.assertEqual(cell.bbox_mm[0], -500.0)
        self.assertEqual(cell.bbox_mm[5], 9000.0)

    def test_an_element_without_a_bbox_does_not_erase_the_others(self):
        cell = next(iter(shape_of([_row(), _row(box=False)]).cells.values()))
        self.assertEqual(cell.count, 2)
        self.assertIsNotNone(cell.bbox_mm)

    def test_an_element_without_a_level_gets_a_NAMED_slot(self):
        """'Level not named' is a fact about the model, not a reason to
        merge with the first one."""
        shape = shape_of([{"category": "OST_Walls"}])
        self.assertEqual(shape.levels, (NO_LEVEL,))


class TheDeltaIsOnlyWhatChanged(unittest.TestCase):

    def test_an_unchanged_cell_is_absent_from_the_delta(self):
        before = shape_of([_row() for _ in range(5)])
        after = shape_of([_row() for _ in range(5)]
                         + [_row(cat="OST_Doors")])
        delta = shape_delta(before, after)
        self.assertEqual(delta["cells_changed"], 1)
        self.assertEqual(delta["cells_total"], 2)
        self.assertIn("Э1 · OST_Doors", delta["changed"])
        self.assertNotIn("Э1 · OST_Walls", delta["changed"])

    def test_a_REMOVAL_is_carried_with_a_minus_not_hidden(self):
        """🔴 Deletion is the most expensive change there is.

        Reducing a vanished category to "zero" would mean hiding it.
        """
        before = shape_of([_row() for _ in range(5)])
        after = shape_of([_row() for _ in range(2)])
        delta = shape_delta(before, after)
        self.assertEqual(delta["elements_removed"], 3)
        self.assertEqual(delta["changed"]["Э1 · OST_Walls"]["delta"], -3)

    def test_a_category_that_VANISHED_still_appears(self):
        before = shape_of([_row(), _row(cat="OST_Doors")])
        after = shape_of([_row()])
        delta = shape_delta(before, after)
        self.assertIn("Э1 · OST_Doors", delta["changed"])
        self.assertEqual(delta["changed"]["Э1 · OST_Doors"]["now"], 0)

    def test_the_first_stage_says_so_instead_of_looking_huge(self):
        delta = shape_delta(None, shape_of([_row() for _ in range(9)]))
        self.assertTrue(delta["first_stage"])
        self.assertIn("ПЕРВАЯ СТАДИЯ", delta_note_ru(delta))


class TheNoteNamesItsOwnBlindness(unittest.TestCase):
    """A summary that stays silent about what it cannot see is worse than
    no summary at all."""

    def test_no_numeric_change_does_NOT_read_as_no_work(self):
        same = shape_of([_row() for _ in range(5)])
        note = delta_note_ru(shape_delta(same, shape_of([_row()] * 5)))
        self.assertIn("НЕ ИЗМЕНИЛОСЬ В ЧИСЛАХ", note)
        self.assertIn("НЕ ВИДНА", note,
                      "правка на месте числа не меняет, и об этом обязано "
                      "быть сказано ровно там, где иначе прочтут «работы "
                      "не было»")

    def test_the_blindness_is_named_on_EVERY_branch(self):
        """The caveat has no right to disappear when there are changes."""
        before = shape_of([_row()])
        after = shape_of([_row(), _row(cat="OST_Doors")])
        for note in (delta_note_ru(shape_delta(before, after)),
                     delta_note_ru(shape_delta(None, after)),
                     delta_note_ru(shape_delta(after, after))):
            with self.subTest(note=note[:40]):
                self.assertIn("НЕ ВИДНА", note)

    def test_truncation_names_itself_and_the_remainder(self):
        before = BuildingShape()
        after = shape_of([_row(cat=f"OST_{i}") for i in range(20)])
        note = delta_note_ru(shape_delta(before, after), top=3)
        self.assertIn("ещё 17 клеток не показаны", note)

    def test_nothing_is_truncated_silently_when_it_fits(self):
        after = shape_of([_row(), _row(cat="OST_Doors")])
        note = delta_note_ru(shape_delta(BuildingShape(), after), top=6)
        self.assertNotIn("не показаны", note)


class TheShapeDoesNotPretendToBeTheReceipt(unittest.TestCase):
    """The shape SHOWS, the receipt PROVES. Swapping one for the other
    would be a defect."""

    def test_no_element_identity_survives_into_the_shape(self):
        rows = [dict(_row(), element_id="99887766", unique_id="u-1")]
        blob = json.dumps(shape_of(rows).to_dict(), ensure_ascii=False)
        self.assertNotIn("99887766", blob)
        self.assertNotIn("u-1", blob)

    def test_the_shape_says_how_many_elements_it_SAW(self):
        """'A summary of zero' and 'no summary was built' are different
        facts."""
        self.assertEqual(shape_of([]).seen, 0)
        self.assertEqual(shape_of([_row()] * 7).seen, 7)


class TheSizeCeilingIsRealNotHoped(unittest.TestCase):
    """The ceiling on the delta is a property, not a hope: it is checked
    with a number."""

    def test_the_delta_never_exceeds_the_cell_count(self):
        before = shape_of([_row(cat=f"OST_{i}", level=f"L{j}")
                           for i in range(8) for j in range(5)])
        # a change of ANY size: a hundred thousand elements into the same
        # cells
        after = shape_of([_row(cat=f"OST_{i}", level=f"L{j}")
                          for i in range(8) for j in range(5)
                          for _ in range(2500)])
        delta = shape_delta(before, after)
        self.assertEqual(after.seen, 100_000)
        self.assertLessEqual(delta["cells_changed"], 40)
        self.assertLess(len(json.dumps(delta, ensure_ascii=False)), 12_000,
                        "дельта ста тысяч элементов обязана остаться "
                        "килобайтами: её размер задают КЛЕТКИ, а не элементы")


if __name__ == "__main__":
    unittest.main()
