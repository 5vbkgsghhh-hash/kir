"""AN ISLAND INSIDE A HOLE IS MATERIAL, NOT VOID, AND BEFORE 20.08 IT WAS
PASSING SILENTLY.

WHY THIS FILE. The `_classify_loops` refusal is called "disjoint/nested
exterior", and under this one name 1188 corpus refusals were being read as
TWO phenomena under one code. A check by construction showed something else,
and worse:

    disjoint, different area  -> REFUSAL "disjoint/nested exterior"
    disjoint, EQUAL area      -> REFUSAL "no unique containing exterior loop"
                                  (a different bucket; does NOT occur in the
                                  corpus)
    AN ISLAND INSIDE A HOLE    -> 🔴 PASSES, recorded as A SECOND HOLE

The check requires every non-primary ring to lie inside the OUTER contour. An
island inside a hole SATISFIES this condition. So the word "nested" in the
message is prose wider than the code (shape 9): it names a case the check
NEVER rejects.

And this is not merely an imprecise name. A solid slab was getting a VOID in
its place, with `ok` and not a single diagnostic — a silently wrong outcome,
exactly what the cardinal invariant stands against.

THE SEPARATION THAT WAS REQUESTED IS OBTAINED WITHOUT RINGS IN THE RECEIPT:
of the 1188 refusals, ZERO are islands — and not by a count, but BY
CONSTRUCTION, because this branch does not reject them. All 1188 are
disjoint.

THE COST OF HONESTY IS NAMED AS A NUMBER: across the corpus, 67 decompiles,
686 profiles with holes, 358 with two or more — holes inside a hole, NOT A
SINGLE ONE. The new refusal does not take away a single element today; it
changes a silently wrong answer into a named absence.
"""
from __future__ import annotations

import unittest

from kir.decompile.side_contract import SideFailureReason
from kir.decompile.sketch_extract import (
    CurveKind, ProfileLoop, SketchPayloadError, _classify_loops)


def _ring(points):
    return ProfileLoop(points_mm=tuple(points),
                       curve_kinds=tuple(CurveKind.LINE for _ in points),
                       arc_midpoints_mm=tuple(None for _ in points))


def _square(x0, y0, x1, y1):
    return _ring([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


class ОстровОтказываетСВОЕЙПричиной(unittest.TestCase):

    def test_an_island_inside_a_hole_refuses_and_names_itself(self):
        with self.assertRaises(SketchPayloadError) as caught:
            _classify_loops([_square(0, 0, 200, 200),
                             _square(20, 20, 80, 80),      # hole
                             _square(40, 40, 60, 60)])     # island IN the hole
        self.assertEqual(caught.exception.typed_reason,
                         SideFailureReason.PROFILE_ISLAND_IN_HOLE)
        self.assertIn("MATERIAL, not a void", str(caught.exception))

    def test_the_disjoint_case_keeps_its_OWN_reason_and_text(self):
        """The old refusal did not move: corpus artifacts are read exactly as
        before.

        Its reason is still derived from the PREFIX of the text, and this is
        deliberate — 1188 corpus records rely exactly on it.
        """
        with self.assertRaises(SketchPayloadError) as caught:
            _classify_loops([_square(0, 0, 100, 100),
                             _square(200, 0, 240, 40)])
        self.assertIsNone(caught.exception.typed_reason)
        self.assertIn("disjoint/nested exterior", str(caught.exception))


class ЧестныйПрофильНЕПОСТРАДАЛ(unittest.TestCase):
    """A CONTROL without which the previous class proves nothing.

    A refusal that always fires "catches" correct geometry too. Both shapes
    that MUST pass are checked here — and the second one (two NON-nested
    holes) matters more than the first: it is precisely the one that
    distinguishes "a hole inside a hole" from "there are simply many holes".
    """

    def test_a_slab_with_one_hole_passes(self):
        exterior, holes = _classify_loops(
            [_square(0, 0, 100, 100), _square(20, 20, 80, 80)])
        self.assertEqual(len(holes), 1)

    def test_two_side_by_side_holes_pass_as_TWO_holes(self):
        exterior, holes = _classify_loops(
            [_square(0, 0, 200, 200),
             _square(20, 20, 60, 60), _square(120, 120, 180, 180)])
        self.assertEqual(len(holes), 2)

    def test_three_nesting_levels_refuse_at_the_first_island(self):
        """Contour > hole > island > hole in the island — refuses on the very
        first one."""
        with self.assertRaises(SketchPayloadError) as caught:
            _classify_loops([_square(0, 0, 400, 400), _square(50, 50, 350, 350),
                             _square(100, 100, 300, 300),
                             _square(150, 150, 250, 250)])
        self.assertEqual(caught.exception.typed_reason,
                         SideFailureReason.PROFILE_ISLAND_IN_HOLE)


class ПричинаЕДЕТ_С_ОТКАЗОМ_А_НЕ_ВЫВОДИТСЯ(unittest.TestCase):
    """The cure for shape 11: writing a field that DISTINGUISHES.

    Before the fix, all contour-parsing refusals received one typed reason,
    `profile_topology_unsupported`, because it is derived from the PREFIX,
    and their prefix is shared. The distinction remained in the free-form
    tail of the message — that is, the reader was being asked to interpret a
    code that carried no distinction.
    """

    def test_an_error_without_a_reason_still_works(self):
        """Compatibility: whoever did not supply a reason behaves as
        before."""
        exc = SketchPayloadError("что-то не так")
        self.assertIsNone(exc.typed_reason)
        self.assertEqual(str(exc), "что-то не так")

    def test_the_reason_reaches_the_written_failure(self):
        """THE LAST LINK: the reason must reach the RECORD, not stay inside
        the exception.

        🔴 THE NAME OF THE KEYWORD ARGUMENT LIES IN `co_consts`, NOT IN
        `co_names`, and the first revision of this test was looking for it in
        the wrong place — red on correct code. This author paid for the same
        shape a second time today (the first was on `joins=` in the joins
        wiring), and it is therefore recorded not as a coincidence:
        `co_names` carries READABLE names, while CPython puts the names of
        keyword arguments into a separate constant tuple.
        """
        from kir.decompile import sketch_extract as SK

        def keyword_tuples(code, out=None):
            out = out if out is not None else []
            for const in code.co_consts:
                if isinstance(const, tuple):
                    out.append(const)
                elif hasattr(const, "co_consts"):
                    keyword_tuples(const, out)
            return out

        tuples = keyword_tuples(SK.extract_sketch_profiles.__code__)
        self.assertIn(("typed_reason",), tuples,
                      "место записи не передаёт причину — она снова будет "
                      "выводиться из общего префикса, и остров станет "
                      "неотличим от несвязных подошв")


if __name__ == "__main__":
    unittest.main()
