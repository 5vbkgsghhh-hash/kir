"""THE CATEGORY SELECTS THE ELEMENT, THE SHAPE SELECTS THE CLASS — and
together they must form a PARTITION.

The project's author is entitled to put a family instance into a system
element's category, and on a production building he does exactly that:
measured on MNVNK K6 — 2,801 slopes with a family shape in ``OST_Walls``,
1,114 copings and railings in ``OST_StairsRailing``. Before 22.08.2026 the
reader was asking BY CATEGORY, while the collector was filtering BY
CLASS, and the difference was thrown away under three different words in
three stages.

``_STAGE_CATEGORY_SHAPES`` names this difference. Here it is checked —
and checked NOT for the table simply being filled in, but for three of
its properties, each of which has already once cost elements:

1. **A partition, not two filters.** If the sketch stage stops taking
   point-based railings, and the placement stage does NOT take them
   either, 1,114 elements silently disappear from both indexes — and
   that is worse than before. The halves must add up to the whole
   category.
2. **A live row, not a dead one.** An entry about a category that is not
   in a stage's set filters nothing and creates the appearance of a
   decision.
3. **The discriminator is the one that is declared.** ``geom_kind`` is
   taken from ``Element.Location`` and separates a family instance from
   a system element; the test holds this on a mixed category, not on
   the docstring's bare word.
"""
from __future__ import annotations

import types
import unittest

from kir.decompile.pipeline import (
    _STAGE_CATEGORIES,
    _STAGE_CATEGORY_SHAPES,
    _ids_for_stage,
)
from kir.decompile.schema import GeometryKind, L0Element
from kir.decompile.tests.fixtures_decompile import make_element


def _element(category: str, element_id: int, kind: GeometryKind) -> L0Element:
    """An element of a given category and SHAPE — the discriminator's input."""
    row = make_element(category, element_id, ordinal=element_id % 100)
    if kind is GeometryKind.POINT:
        row["geom_kind"] = "point"
        row["p0_mm"] = [1_000.0, 2_000.0, 0.0]
        row["p1_mm"] = None
        row["rotation_deg"] = 0.0
    elif kind is GeometryKind.CURVE:
        row["geom_kind"] = "curve"
        row["curve_kind"] = "line"
        row["p0_mm"] = [0.0, 0.0, 0.0]
        row["p1_mm"] = [3_000.0, 0.0, 0.0]
    return L0Element.from_dict(row)


def _doc(elements: list[L0Element]) -> types.SimpleNamespace:
    return types.SimpleNamespace(elements=elements)


class StageCategoryShapesTest(unittest.TestCase):

    def test_every_entry_filters_a_category_the_stage_actually_asks_for(self):
        """An entry about a category outside the stage's set is a decision that does not exist."""
        for (stage, category) in _STAGE_CATEGORY_SHAPES:
            with self.subTest(stage=stage, category=category):
                self.assertIn(
                    category, _STAGE_CATEGORIES.get(stage, frozenset()),
                    f"({stage}, {category}) ничего не фильтрует: категории "
                    f"нет в _STAGE_CATEGORIES[{stage!r}]")

    def test_point_and_non_point_split_a_mixed_category_without_remainder(self):
        """The discriminator splits a mixed category exactly in two.

        The shape is taken from life: ``OST_Walls`` on K6 is 7,845 real
        walls (a wall ALWAYS has an axis) and 2,801 family instances (an
        instance has a point).
        """
        walls = [_element("OST_Walls", 900 + n, GeometryKind.CURVE)
                 for n in range(4)]
        forms = [_element("OST_Walls", 950 + n, GeometryKind.POINT)
                 for n in range(3)]
        document = _doc(walls + forms)

        asked = set(_ids_for_stage(document, "family_placement"))
        self.assertEqual(
            asked, {e.element_id for e in forms},
            "стадия размещений обязана взять ТОЛЬКО точечные: настоящая "
            "стена дала бы element_kind_mismatch и лишнюю пачку на мосту")

    def test_the_two_stages_partition_the_railing_category(self):
        """🔴 THE MAIN PROPERTY: the halves add up to the whole.

        The sketch stage takes real ``Railing``s, the placement stage
        takes family instances. No element is entitled to fall out of
        both: exactly this way 1,114 copings and glass railings would
        have been silently lost, had the filter been set on only one
        side.
        """
        rails = [_element("OST_StairsRailing", 700 + n, GeometryKind.BBOX_ONLY)
                 for n in range(3)]
        casings = [_element("OST_StairsRailing", 750 + n, GeometryKind.POINT)
                   for n in range(5)]
        document = _doc(rails + casings)
        everything = {e.element_id for e in rails + casings}

        sketch = set(_ids_for_stage(document, "sketch"))
        placement = set(_ids_for_stage(document, "family_placement"))

        self.assertEqual(
            sketch | placement, everything,
            "элементы, не спрошенные НИ ОДНОЙ стадией, исчезают молча")
        self.assertEqual(
            sketch & placement, set(),
            "один элемент, спрошенный обеими стадиями, платит мостом дважды")
        self.assertEqual(sketch, {e.element_id for e in rails})
        self.assertEqual(placement, {e.element_id for e in casings})

    def test_a_category_without_an_entry_is_taken_whole(self):
        """The absence of an entry means "take it whole," not "don't take it"."""
        doors = [_element("OST_Doors", 800 + n, GeometryKind.POINT)
                 for n in range(2)]
        doors += [_element("OST_Doors", 850 + n, GeometryKind.BBOX_ONLY)
                  for n in range(2)]
        document = _doc(doors)
        self.assertEqual(
            set(_ids_for_stage(document, "family_placement")),
            {e.element_id for e in doors},
            "у OST_Doors записи о форме нет — значит берутся все")


if __name__ == "__main__":
    unittest.main()
