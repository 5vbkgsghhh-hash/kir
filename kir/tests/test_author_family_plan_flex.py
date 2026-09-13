"""THE PLAN BENDS — AND IT BENDS HONESTLY OR IT DOES NOT BEND AT ALL.

🔴 WHY THIS AXIS WAS SET UP (21.08.2026). The named limit of
`author_family`'s first draft read: «the family stretches upward and does
not stretch in plan». HEIGHT has a ready-made shape field
(`EXTRUSION_END_PARAM`), and binding the parameter to it is one call. THE
PLAN HAS NO SUCH FIELD AT ALL: the extrusion width is not a property of
the shape but a consequence of the sketch. So the chain is longer:

    ReferencePlane -> NewAlignment -> NewDimension -> Dimension.FamilyLabel

and every link is mandatory. Skip the alignment and the dimension will
move the planes while the body stays put: a handle that lies to the
author.

THE LIVE MEASUREMENT THAT PAID FOR ALL OF THIS (Revit 2026, «Проект1»):
volume 192 000 000 -> 384 000 000 when the width is doubled, a ratio of
2.0000.

🔴 WHAT THIS FILE GUARDS ABOVE ALL IS NOT FLEXIBILITY, BUT REFUSAL. The
alignment only holds edges that lie on the plane. A round column has none
at all: the family would assemble, look parametric, and skew on the very
first parameter change. A silently wrong answer costs more than no
answer, so a non-rectangular profile is REFUSED, and the refusal names the
profile's KIND.
"""
from __future__ import annotations

import unittest

from kir import contour as C
from kir.compiler import compile_program
from kir.diag import KirRefusal
from kir.family_author_emit import axis_rect_or_reason

_RECT = {"shape": "rect", "origin": [0, 0], "size_mm": [600, 400]}


def _region(outer, holes=None):
    diags: list = []
    payload = {"outer": outer}
    if holes:
        payload["holes"] = holes
    out = C.validate_region(payload, [], "AF1", "profile", diags)
    if out is None:
        raise AssertionError(f"область не построилась: "
                             f"{[d.message_ru[:80] for d in diags]}")
    return out


def _prog(**over):
    op = {"op": "author_family", "id": "AF1",
          "family_name": "KIR_Тест", "type_name": "Тип",
          "template": "generic_model", "profile": {"outer": _RECT},
          "height_mm": 800, "flex_param": "Высота_KIR"}
    op.update(over)
    return {"ir_version": "1.0", "intent": "тест", "ops": [op]}


class TheGuardNamesTheProfileKind(unittest.TestCase):

    def test_an_axis_rectangle_is_accepted_with_its_bbox(self):
        bbox, why = axis_rect_or_reason(_region(_RECT))
        self.assertIsNone(why)
        self.assertEqual(bbox, (0.0, 0.0, 600.0, 400.0))

    def test_a_rotated_rectangle_is_refused_and_says_WHY(self):
        """A rotated one is not «almost a rectangle» — it is a different
        case.

        The reference plane is built ALONG Y; a rotated edge does not lie
        on it, and the alignment will not hold it.
        """
        _, why = axis_rect_or_reason(
            _region({**_RECT, "rotation_deg": 30}))
        self.assertIsNotNone(why)
        self.assertIn("не осевой", why)

    def test_an_arc_edge_is_refused_and_the_reason_says_arcs(self):
        _, why = axis_rect_or_reason(_region(
            {"shape": "poly",
             "points_mm": [[0, 0], [600, 0], [600, 400], [0, 400]],
             "arcs": [{"edge": 1, "bulge": 0.4}]}))
        self.assertIsNotNone(why)
        self.assertIn("дуги", why)

    def test_an_L_shape_is_refused_and_counts_its_edges(self):
        _, why = axis_rect_or_reason(_region(
            {"shape": "l", "origin": [0, 0], "size_mm": [600, 400],
             "cut_mm": [200, 150]}))
        self.assertIsNotNone(why)
        self.assertIn("6 рёбер", why)

    def test_a_hole_is_refused_because_alignment_does_not_reach_it(self):
        _, why = axis_rect_or_reason(_region(
            _RECT, [{"shape": "rect", "origin": [200, 150],
                     "size_mm": [150, 100]}]))
        self.assertIsNotNone(why)
        self.assertIn("проём", why)


class TheOpRefusesBeforeTouchingRevit(unittest.TestCase):
    """The refusal is STATIC, and that is the cheapest outcome for the
    author.

    The profile's kind is visible without Revit. Sending a round column
    into a live run just to have it refuse THERE would mean occupying
    someone else's window for an answer already known in advance.
    """

    def test_a_curved_profile_with_a_plan_param_is_refused_at_compile(self):
        out = compile_program(_prog(
            flex_plan_param="Ширина_KIR",
            profile={"outer": {"shape": "poly",
                               "points_mm": [[0, 0], [600, 0], [600, 400],
                                             [0, 400]],
                               "arcs": [{"edge": 1, "bulge": 0.4}]}}),
            revit_version="2026")
        self.assertFalse(out.ok)
        msg = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("flex_plan_param", msg)
        self.assertIn("дуги", msg)
        self.assertIn("Убери flex_plan_param", msg,
                      "отказ обязан называть СЛЕДУЮЩИЙ ХОД, а не только "
                      "причину")

    def test_one_name_cannot_drive_both_axes(self):
        """Revit would accept the second binding and silently drop the
        first."""
        out = compile_program(
            _prog(flex_plan_param="Высота_KIR"), revit_version="2026")
        self.assertFalse(out.ok)
        self.assertIn("одинаково",
                      " ".join(d.message_ru for d in out.diagnostics))


class TheEmissionCarriesTheWholeChain(unittest.TestCase):

    def test_all_four_links_are_emitted(self):
        out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                              revit_version="2026")
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])
        for link in ("NewReferencePlane", "NewAlignment", "NewDimension",
                     "FamilyLabel"):
            with self.subTest(link=link):
                self.assertIn(link, out.csharp)

    def test_the_alignment_count_is_CHECKED_not_assumed(self):
        """Without both alignments the parameter would be moving thin
        air."""
        out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                              revit_version="2026")
        self.assertIn("рёбер вместо двух", out.csharp)

    def test_the_acceptance_is_VOLUME_not_a_written_value(self):
        out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                              revit_version="2026")
        self.assertIn("ПЛАН НЕ СЛУШАЕТ ПАРАМЕТР", out.csharp)
        # reference case is closed: 600x400x800 -> 1200x400x800
        self.assertIn("192000000", out.csharp)
        self.assertIn("384000000", out.csharp)

    def test_the_value_is_RESTORED_and_the_restore_is_checked(self):
        out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                              revit_version="2026")
        self.assertIn("не той ширины", out.csharp)

    def test_without_the_field_there_is_NOT_A_TRACE(self):
        """An undeclared axis leaves no dead code in the program."""
        out = compile_program(_prog(), revit_version="2026")
        self.assertTrue(out.ok)
        for link in ("NewReferencePlane", "NewAlignment", "NewDimension",
                     "FamilyLabel"):
            with self.subTest(link=link):
                self.assertNotIn(link, out.csharp)


class TheReceiptTellsTheTruthAboutBothAxes(unittest.TestCase):

    def test_flex_axes_names_both_when_both_are_asked(self):
        out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                              revit_version="2026")
        self.assertIn('"Высота_KIR", "Ширина_KIR"', out.csharp)

    def test_the_named_absence_CHANGES_when_the_plan_flexes(self):
        """The receipt has no right to repeat a limitation that has been
        lifted.

        While the plan was rigid, the honest line was «stretches upward
        and does not stretch in plan». With the plan axis in place, that
        line would become a LIE — and a named absence that has turned
        false is worse than no statement at all: people believe it.
        """
        rigid = compile_program(_prog(), revit_version="2026").csharp
        flexed = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                                 revit_version="2026").csharp
        self.assertIn("не растягивается в плане", rigid)
        self.assertNotIn("не растягивается в плане", flexed)
        self.assertIn("ГЛУБИНА профиля жёсткая", flexed)

    def test_the_receipt_carries_the_plan_ratio_field(self):
        out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                              revit_version="2026")
        self.assertIn('__rb["plan_volume_ratio"]', out.csharp)
        self.assertIn('__rb["flex_plan_bound_to"]', out.csharp)


class ItEmitsOnAllSixVersions(unittest.TestCase):

    def test_the_parameter_is_added_in_the_spelling_of_each_version(self):
        """`AddParameter` is written differently before and after 2022 —
        both members simply DO NOT EXIST on the other side, this is not a
        matter of style."""
        for ver, marker in (("2021", "ParameterType.Length"),
                            ("2026", "SpecTypeId.Length")):
            with self.subTest(ver=ver):
                out = compile_program(_prog(flex_plan_param="Ширина_KIR"),
                                      revit_version=ver)
                self.assertTrue(out.ok)
                self.assertIn(marker, out.csharp)
                self.assertEqual(out.csharp.count(marker), 2,
                                 "оба параметра — высоты и плана — заводятся "
                                 "написанием СВОЕЙ версии")


if __name__ == "__main__":
    unittest.main()
