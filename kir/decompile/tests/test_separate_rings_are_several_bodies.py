"""SEPARATE SKETCH LOOPS ARE MULTIPLE BODIES, NOT HOLES.

WHAT IS PINNED HERE AND WHAT IT WAS BOUGHT BY (26.08.2026). The recipe collector declared
the FIRST loop the outer one and all the rest holes — `region = {"outer": shapes[0]}`,
`region["holes"] = shapes[1:]` — WITHOUT A SINGLE NESTING CHECK. A Revit sketch
legitimately carries several separate closed loops: one shape gives several
bodies. They were declared holes of a nonexistent outer contour, and CONTOUR correctly
answered "point outside the outer contour."

A measurement over 16 refusals with the code `contour_limit_exceeded` on a real building
(110 families, payload 21.08): for THIRTEEN the loops are separate and none is
nested, for three there is ONE loop and its geometry is at fault. Not a single case
of "limit exceeded," even though the code was named exactly that.

🔴 WHY THE TEST IS SYNTHETIC, NOT ON THE CORPUS. The family corpus is machine-local
(`/home/claude/kir-evidence/…`), and a test on it would silently be skipped everywhere
the corpus is absent — that is, it would be green by absence, not by property. The law
here is clean and is checked with vertices; the corpus figure lives in the wave's report.
"""
from __future__ import annotations

import unittest

from kir.decompile import family_recipe as FR


def _ring(x0: float, y0: float, x1: float, y1: float) -> dict:
    """A rectangular loop in the shape that `_regions_from_loops` builds."""
    return {"shape": "poly",
            "points_mm": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]}


class SeparateRingsBecomeSeveralBodies(unittest.TestCase):
    """The CAPABILITY axis: what the reader can now say."""

    def test_two_disjoint_rings_are_two_regions(self):
        outer_left = _ring(0, 0, 100, 100)
        outer_right = _ring(500, 0, 600, 100)
        groups, refusal = FR._group_rings([outer_left, outer_right])
        self.assertIsNone(refusal, "раздельные кольца — законный эскиз Revit")
        self.assertEqual(len(groups), 2,
                         "два раздельных кольца — ДВА тела, а не кольцо с дырой")
        for _outer, holes in groups:
            self.assertEqual(holes, [], "у раздельного кольца дыр нет")

    def test_nested_ring_is_a_hole_not_a_body(self):
        outer = _ring(0, 0, 100, 100)
        hole = _ring(20, 20, 80, 80)
        groups, refusal = FR._group_rings([outer, hole])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 1, "вложенное кольцо — ДЫРА, не тело")
        self.assertEqual(len(groups[0][1]), 1)

    def test_the_outer_is_found_even_when_it_is_not_first(self):
        """THE ORDER OF LOOPS IN THE PAYLOAD DECIDES NOTHING.

        Exactly what the old code did not do: it took `shapes[0]`. Here the hole
        comes FIRST, and the outer one must be found by nesting, not by position.
        """
        hole = _ring(20, 20, 80, 80)
        outer = _ring(0, 0, 100, 100)
        groups, refusal = FR._group_rings([hole, outer])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][0]["points_mm"], outer["points_mm"],
                         "внешним обязано стать ОБЪЕМЛЮЩЕЕ кольцо")

    def test_group_order_is_deterministic_by_area(self):
        """The goldens are byte-stable: the order of bodies does not depend on the order of the payload."""
        small = _ring(500, 0, 560, 60)
        big = _ring(0, 0, 100, 100)
        first, _ = FR._group_rings([small, big])
        second, _ = FR._group_rings([big, small])
        self.assertEqual([g[0]["points_mm"] for g in first],
                         [g[0]["points_mm"] for g in second])
        self.assertEqual(first[0][0]["points_mm"], big["points_mm"],
                         "порядок — по убыванию площади внешнего кольца")


class WhatTheLanguageStillCannotSay(unittest.TestCase):
    """The BOUNDARY axis: a named refusal instead of a silent simplification."""

    def test_island_inside_a_hole_is_a_named_refusal(self):
        """An island inside a hole is legal in Revit and inexpressible by a KIR region.

        The old code would glue it into `holes` and build a FALSE body: the hole and
        the island would land as two holes in a row, and the volume check would accept the
        result, because the island's area would be subtracted twice in the wrong place.
        """
        outer = _ring(0, 0, 100, 100)
        hole = _ring(20, 20, 80, 80)
        island = _ring(40, 40, 60, 60)
        groups, refusal = FR._group_rings([outer, hole, island])
        self.assertIsNone(groups)
        self.assertIsNotNone(refusal)
        self.assertIs(refusal.code, FR.RecipeRefusal.PROFILE_RINGS_NOT_A_REGION)
        self.assertIn("глубже одного уровня", refusal.detail)


class TheRefusalCodeNamesItsRepair(unittest.TestCase):
    """The code's name must name the REPAIR, otherwise branching on it is impossible."""

    def test_the_lying_code_is_retired_and_not_produced(self):
        """`contour_limit_exceeded` is no longer issued by ANY path.

        The name is deliberately left in the dictionary — 16 refusals are recorded under it in the canon,
        and a code that silently disappeared would make the reader think the measurement was lost.
        But it must have no producer.
        """
        import pathlib
        source = pathlib.Path(FR.__file__).read_text(encoding="utf-8")
        produced = source.count("RecipeRefusal.CONTOUR_LIMIT_EXCEEDED")
        self.assertEqual(
            produced, 0,
            "код, чьё имя не описывает ни один его случай, снова выдаётся")

    def test_the_two_repairs_have_two_codes(self):
        """Loops and a loop's geometry are fixed by DIFFERENT means — so the codes differ too."""
        self.assertNotEqual(
            FR.RecipeRefusal.PROFILE_RINGS_NOT_A_REGION.value,
            FR.RecipeRefusal.PROFILE_REJECTED_BY_CONTOUR.value)


class ControlFail(unittest.TestCase):
    """FAIL CONTROL: bring back the old assumption — the property must disappear.

    What is checked is the BEHAVIOR of the substituted law, not reading the source: a test
    that reads text turns green from a comment.
    """

    def test_restoring_first_ring_is_outer_loses_the_second_body(self):
        rings = [_ring(0, 0, 100, 100), _ring(500, 0, 600, 100)]

        def first_is_outer(shapes):
            """The old law verbatim: the first is outer, the rest are holes."""
            return [(shapes[0], list(shapes[1:]))], None

        groups_now, _ = FR._group_rings(rings)
        groups_then, _ = first_is_outer(rings)
        self.assertEqual(len(groups_now), 2)
        self.assertEqual(len(groups_then), 1,
                         "прежний закон давал ОДНО тело из двух раздельных")
        self.assertEqual(len(groups_then[0][1]), 1,
                         "и второе кольцо становилось ДЫРОЙ — то есть исчезало")


class OneFormStaysOneLift(unittest.TestCase):
    """THE CENSUS DOES NOT MOVE: the lift is still ONE per shape.

    There are 283 shapes in the corpus, and this number has no right to shift just because we
    learned to speak of multiple bodies. Bodies are counted separately (`bodies`).
    """

    def test_lift_carries_several_bodies_but_counts_as_one_form(self):
        lift = FR.FormLift(
            form_id="F1", kind=FR.FormKind.EXTRUSION,
            ops=({"op": "create_solid_extrusion", "id": "F1b1"},
                 {"op": "create_solid_extrusion", "id": "F1b2"}),
            refusal=None)
        self.assertTrue(lift.lifted)
        self.assertEqual(lift.bodies, 2)
        self.assertIsNone(
            lift.op,
            "однотельный доступ обязан молчать у многотельной формы, "
            "иначе отдал бы часть за целое")

    def test_single_body_form_keeps_the_old_singular_access(self):
        lift = FR.FormLift(
            form_id="F1", kind=FR.FormKind.EXTRUSION,
            ops=({"op": "create_solid_extrusion", "id": "F1"},),
            refusal=None)
        self.assertEqual(lift.bodies, 1)
        self.assertIsNotNone(lift.op)
        self.assertEqual(lift.op["id"], "F1")

    def test_exactly_one_of_ops_parts_refusal(self):
        with self.assertRaises(FR.FamilyRecipeError):
            FR.FormLift(form_id="F", kind=FR.FormKind.EXTRUSION,
                        ops=(), refusal=None)
        with self.assertRaises(FR.FamilyRecipeError):
            FR.FormLift(form_id="F", kind=FR.FormKind.EXTRUSION,
                        ops=({"op": "x"},), parts=({"shape": "prism"},),
                        refusal=None)


if __name__ == "__main__":
    unittest.main()
