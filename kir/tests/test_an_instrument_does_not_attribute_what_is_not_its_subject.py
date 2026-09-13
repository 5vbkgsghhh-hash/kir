r"""AN INSTRUMENT MUST NOT ATTRIBUTE TO ITS SUBJECT WHAT DOES NOT BELONG TO THE SUBJECT.

Audit findings `F-341` and `F-366` (29.08.2026). One class, two mechanisms:
in both, the instrument is RIGHT ABOUT SOMEONE ELSE'S SUBJECT and presents
this as an assertion about its own.

`F-341` — `kir/course/shape._lift_refusals`. A refusal was attributed to an
operation by SUBSTRING (`if op in text`), while registry names are nested
inside one another: `create_room` ⊂ `create_room_separator`, `create_wall`
⊂ `create_wall_foundation`. Measured before the fix: **3 false
attributions** out of 36 ops, and for `create_room` BOTH lines that came
from refusals are FALSE — meaning every boundary the census declared for
this operation had been taken from a neighbor.

The cost lies in WHAT the census declares itself to be: «ось границы:
ЗАКРЫТАЯ, НО НЕ ПОЛНАЯ» (boundary axis: CLOSED, BUT NOT COMPLETE) — a
derived piece of evidence the reader is obliged to trust, and it is
printed to the author with the ⛔ icon. The absence of a record and a
record that is ENTIRELY SOMEONE ELSE'S are not the same thing: the first
reads as "no boundaries declared", the second as "here are the boundaries".

`F-366` — `kir/stage_shape.shape_delta`. The numerator was counted over
the UNION of the "before" and "after" cells, the denominator over "after"
only. A cell that disappeared entirely entered the numerator and did not
enter the denominator:

    a single row of walls was demolished  ->  «ИЗМЕНИЛОСЬ клеток: 1 из 0»

🔴 AND THIS IS NOT THE MAIN POINT. «1 из 0» is mathematically impossible,
so a reader will doubt the instrument and go look. The SILENT case is
worse: a building that lost one category out of two was printing «1 из
1» — plausible, reads as "everything that existed changed", while TWO
cells were being compared. Nobody will catch this half, and it is exactly
this half that is the real defect; the first case only makes it visible at
the edge.

The pattern, already named by the previous shift, is visible here in full:
a silent VALUE (`cells_total`) -> a silent OUTPUT (the summary line) -> a
SPEAKING assertion, read as the truth.

🔴 A CORRECTION TO THE FILE'S OWN EARLIER ARGUMENT, LIFTED BY A CONTROL.
The first edition of this file asserted that "\b is not enough here". This
IS WRONG: `_` is a word character, so the word boundary between
`create_room` and `create_room_separator` does NOT occur, and `\b`
discriminates between them just as well. Replacing it with `\b` left every
check below GREEN. The chosen form, `(?<!\w)…(?!\w)`, is stricter only for
a name that starts or ends with a non-letter — no registry name is
affected by that today, and the gain is ZERO. This is stated so that the
next person does not go looking behind the form for a measurement that
does not exist.

THE EXISTING SUITE PASSED ONE STEP AWAY FROM `F-366`:
`test_stage_shape.py` builds exactly the case where the denominator is
undercounted, and looks only at whether the category lands in `changed`;
while the test that DOES LOOK at `cells_total` is built where nothing
disappeared and both sets coincide. The defect lived BETWEEN the two tests.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.course import shape
from kir.stage_shape import BuildingShape, Cell, delta_note_ru, shape_delta


def _shape(**cells: int) -> BuildingShape:
    return BuildingShape(
        cells={tuple(k.split("|")): Cell(count=v) for k, v in cells.items()},
        seen=sum(cells.values()))


class ОтказОтноситсяКСВОЕЙОперации(unittest.TestCase):
    """F-341."""

    @staticmethod
    def _false_attributions() -> list[tuple[str, str]]:
        """Attributions where the op's name is its own substring of ANOTHER
        registry name, and the text carries exactly the longer name."""
        names = set(spec.OPS)
        bad = []
        for op, rows in shape.declared_boundaries().items():
            for _origin, what in rows:
                longer = [n for n in names if n != op and op in n and n in what]
                if longer and op not in what.replace(longer[0], ""):
                    bad.append((op, longer[0]))
        return bad

    def test_no_refusal_is_attributed_to_a_prefix_of_its_own_op(self) -> None:
        """🔴 THE SUBJECT. Before the fix — 3 false attributions."""
        self.assertEqual(self._false_attributions(), [])

    def test_the_probe_would_have_caught_the_old_behaviour(self) -> None:
        """A DENOMINATOR CONTROL THROUGH THE SUBJECT ITSELF: registry names
        REALLY ARE nested, otherwise the check above is green about nothing."""
        names = set(spec.OPS)
        nested = [(a, b) for a in names for b in names if a != b and a in b]
        self.assertGreaterEqual(len(nested), 2, f"вложенных пар: {nested}")
        self.assertIn(("create_room", "create_room_separator"), nested)

    def test_the_refusals_landed_on_their_true_owners(self) -> None:
        """The refusals were not lost — they moved. The fix must not dare EAT them."""
        b = shape.declared_boundaries()
        joined = " ".join(w for _o, w in b.get("create_room_separator", ()))
        self.assertIn("room separator", joined)
        self.assertTrue(b.get("create_wall_foundation"))

    def test_an_op_that_is_nobody_s_prefix_still_gets_its_refusals(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it, a fix of "attribute nothing to
        anyone" would pass everything else and zero out the census."""
        b = shape.declared_boundaries()
        self.assertGreaterEqual(len(b), 10)
        self.assertTrue(any(rows for rows in b.values()))


class ЗнаменательСчитаетТоЖеМножество(unittest.TestCase):
    """F-366."""

    def test_a_vanished_row_is_counted_in_both_or_in_neither(self) -> None:
        """🔴 THE VISIBLE EDGE: «1 из 0» is impossible."""
        d = shape_delta(_shape(**{"Э1|Стены": 10}), _shape())
        self.assertEqual(d["cells_changed"], 1)
        self.assertEqual(d["cells_total"], 1)
        self.assertLessEqual(d["cells_changed"], d["cells_total"])
        self.assertIn("1 из 1", delta_note_ru(d))

    def test_the_quiet_case_is_the_real_defect(self) -> None:
        """🔴 THE SILENT CASE that no reader will catch: one category out of
        TWO disappeared — it was printing «1 из 1»."""
        d = shape_delta(_shape(**{"Э1|Стены": 10, "Э1|Двери": 5}),
                        _shape(**{"Э1|Двери": 5}))
        self.assertEqual(d["cells_changed"], 1)
        self.assertEqual(d["cells_total"], 2, "сравнивались ДВЕ клетки")
        self.assertIn("1 из 2", delta_note_ru(d))

    def test_the_fraction_is_never_impossible(self) -> None:
        """A PROPERTY, NOT A SINGLE CASE: the numerator does not exceed the
        denominator on any pair in the enumeration."""
        pool = ({}, {"Э1|Стены": 10}, {"Э1|Двери": 5},
                {"Э1|Стены": 10, "Э1|Двери": 5},
                {"Э1|Стены": 12, "Э2|Стены": 1})
        for before in pool:
            for after in pool:
                with self.subTest(before=before, after=after):
                    d = shape_delta(_shape(**before), _shape(**after))
                    self.assertLessEqual(d["cells_changed"], d["cells_total"])

    def test_the_old_quantity_is_not_lost_it_is_named(self) -> None:
        """The quantity `cells_total` used to carry is now called by its own
        name. Keys are only ADDED."""
        d = shape_delta(_shape(**{"Э1|Стены": 10, "Э1|Двери": 5}),
                        _shape(**{"Э1|Двери": 5}))
        self.assertEqual(d["cells_now"], 1)
        self.assertEqual(d["cells_total"], 2)

    def test_nothing_moved_still_reads_the_same(self) -> None:
        """🔴 THE GREEN OUTCOME THAT MUST SURVIVE: where nothing disappeared,
        both sets coincide and the number is unchanged."""
        d = shape_delta(_shape(**{"Э1|Стены": 10, "Э1|Двери": 5}),
                        _shape(**{"Э1|Стены": 12, "Э1|Двери": 5}))
        self.assertEqual(d["cells_total"], 2)
        self.assertEqual(d["cells_now"], 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
