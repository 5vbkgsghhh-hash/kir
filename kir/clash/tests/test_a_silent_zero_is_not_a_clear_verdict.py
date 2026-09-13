"""AN EMPTY INTERSECTION MUST BE PROVEN, NOT TAKEN ON FAITH.

🔴 WHY THIS WAS ADDED (2026-09-07, mission-2 reconnaissance).

`BRepAlgoAPI_Common(twisted loft, prism)` returns a volume of **0.0 while
`IsDone() == True`**. Both bodies pass `BRepCheck_Analyzer.IsValid()`,
`SetFuzzyValue` of 0 · 1e-7 · 1e-3 · 0.01 · 0.1 · 1.0 changes nothing, and
the constructor-built shape gives the same. The threshold was found by
sweeping: up to and including 8.5° the answer is correct, at **9°** the
answer is zero, and that is exactly the mark where the loft's side surface
crosses outside the prism (extent along y 9000.0 → 9085.0), that is, where
the surfaces genuinely intersect. All three towers from the tree's example
sit in the refusal zone: `tower-a` 12°, `tower-b` −9°, `tower-c` 18°.

WHAT THIS WOULD HAVE COST WITHOUT A GUARD. `clear` in the `exact.py`
vocabulary means "a PROVEN absence of intersection, not 'did not find one'"
— that is, on a pair intersecting by 99% of its volume, the exact phase
would be handing back the STRONGEST of its claims. A repair move built on
such a verdict would separate bodies that already "do not intersect".

WHY ADDITIVITY DOES NOT WORK AS A GUARD. Measured on the same three
towers: `|V(A∩B) + V(A−B) − V(A)| / V(A)` = 2.2e-16 · 5.9e-12 · 1.1e-10.
`Cut` is self-consistent — it is simply wrong, and the volume check is
green by construction. Only an INDEPENDENT counter catches it: point
classification is decided by walking the hull, not by boolean algebra.
"""
from __future__ import annotations

import math
import unittest

try:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepPrimAPI import (BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder,
                                 BRepPrimAPI_MakePrism)
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pnt, gp_Vec
    OCP_READY = True
except ImportError:                                            # pragma: no cover
    OCP_READY = False

from kir.clash.exact import (DEFAULT_POLICY, REFUSALS, TolerancePolicy,
                             has_curved_faces, verify_pair, witness_common)


WIDTH, DEPTH, HEIGHT, SCALE = 14000.0, 9000.0, 10800.0, 0.82


def _wire(points, z):
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in points:
        polygon.Add(gp_Pnt(x, y, z))
    polygon.Close()
    return polygon.Wire()


def _ring():
    return [(0.0, 0.0), (WIDTH, 0.0), (WIDTH, DEPTH), (0.0, DEPTH)]


def _top(twist_deg):
    angle = math.radians(twist_deg)
    cx, cy = WIDTH / 2, DEPTH / 2
    return [(cx + SCALE * ((x - cx) * math.cos(angle) - (y - cy) * math.sin(angle)),
             cy + SCALE * ((x - cx) * math.sin(angle) + (y - cy) * math.cos(angle)))
            for x, y in _ring()]


def _blend(twist_deg):
    """The same recipe as the `create_solid_blend` example: two profiles, ruled."""
    loft = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    loft.AddWire(_wire(_ring(), 0.0))
    loft.AddWire(_wire(_top(twist_deg), HEIGHT))
    loft.Build()
    assert loft.IsDone()
    return loft.Shape()


def _prism():
    face = BRepBuilderAPI_MakeFace(_wire(_ring(), 0.0)).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0.0, 0.0, HEIGHT)).Shape()


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class ASilentZeroIsRefusedNotPublished(unittest.TestCase):
    """The 9° threshold is pinned by a NUMBER from both sides, not by a single point."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.prism = _prism()

    def test_below_the_threshold_the_kernel_is_believed(self) -> None:
        """THE DENOMINATOR FIRST: a guard that turns everything red is not a guard.

        Up to and including 8.5°, `Common` is correct, the loft is fully
        contained in the prism, and the verdict must be `contained`, with
        the volume of the loft itself.
        """
        for twist in (0.0, 6.0, 8.5):
            with self.subTest(twist=twist):
                verdict = verify_pair(_blend(twist), self.prism)
                self.assertIsNone(verdict.refusal, f"{twist}°: ложное срабатывание")
                self.assertEqual(verdict.relation, "contained")
                self.assertGreater(verdict.overlap_volume_mm3, 1.1e12)

    def test_at_and_above_the_threshold_the_verdict_is_a_named_refusal(self) -> None:
        """9° · 12° · −9° · 18° — four out of four, and `clear` is not among them."""
        for twist in (9.0, 12.0, 18.0, -9.0):
            with self.subTest(twist=twist):
                verdict = verify_pair(_blend(twist), self.prism)
                self.assertEqual(verdict.refusal, "boolean_contradicts_witness")
                self.assertIsNone(verdict.relation,
                                  "объём пересечения не публикуется при отказе")
                self.assertIsNone(verdict.overlap_volume_mm3)

    def test_the_refusal_is_in_the_closed_list(self) -> None:
        self.assertIn("boolean_contradicts_witness", REFUSALS)

    def test_additivity_would_not_have_caught_it(self) -> None:
        """The guard's argument is checked by EXECUTION, not by a retelling
        in the docstring.

        If the guard were the check `V(A∩B) + V(A−B) = V(A)`, it would have
        stayed green: the discrepancy here is ten orders of magnitude below
        any reasonable threshold. The test SHOWS this, so that tomorrow's
        reader does not replace the witness with a "cheaper check".
        """
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Cut
        from OCP.BRepGProp import BRepGProp
        from OCP.GProp import GProp_GProps

        def volume(shape):
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape, props)
            return float(props.Mass())

        loft = _blend(12.0)
        common = BRepAlgoAPI_Common(loft, self.prism)
        common.Build()
        cut = BRepAlgoAPI_Cut(loft, self.prism)
        cut.Build()
        self.assertTrue(common.IsDone() and cut.IsDone(),
                        "кернел объявляет обе операции удавшимися — в этом и беда")
        self.assertEqual(volume(common.Shape()), 0.0, "немой ноль на месте")
        total = volume(common.Shape()) + volume(cut.Shape())
        self.assertLess(abs(total - volume(loft)) / volume(loft), 1e-9,
                        "аддитивность ЗЕЛЕНА при неверном ответе — она не сторож")


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class TheSelectorAndTheWitnessBothAnswerNo(unittest.TestCase):
    """An instrument that cannot say NO guards nothing."""

    def test_the_selector_can_say_no(self) -> None:
        """🔴 THIS TEST WAS BOUGHT BY A BUG, AND IT IS WORTH NAMING.

        The first edition of `has_curved_faces` called `k.TopoDS`, which did
        not exist in the kernel's namespace. The `AttributeError` fell into
        `except Exception: return True`, and the selector answered "curved"
        for EVERY body, including a box. All seven verdicts were correct
        despite this — the defect was invisible in the answers and would
        have cost 0.5 s of witness on every planar pair. It is visible only
        by asking "and can the instrument say NO?".
        """
        box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), gp_Pnt(200, 200, 100)).Shape()
        cylinder = BRepPrimAPI_MakeCylinder(100.0, 50.0).Shape()
        self.assertFalse(has_curved_faces(box), "у коробки нет криволинейных граней")
        self.assertTrue(has_curved_faces(cylinder), "у цилиндра они есть")

    def test_the_witness_publishes_its_denominator(self) -> None:
        """"0 out of 0" and "0 out of 250" print the same and mean different things."""
        box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), gp_Pnt(200, 200, 100)).Shape()
        far = BRepPrimAPI_MakeBox(gp_Pnt(9000, 9000, 9000), gp_Pnt(9200, 9200, 9100)).Shape()
        overlapping = BRepPrimAPI_MakeBox(gp_Pnt(100, 100, 50), gp_Pnt(300, 300, 150)).Shape()
        both, tried = witness_common(box, far, grid_n=5)
        self.assertEqual(both, 0)
        self.assertEqual(tried, 250, "две фигуры по 5³ точек")
        both, tried = witness_common(box, overlapping, grid_n=5)
        self.assertGreater(both, 0)
        self.assertEqual(tried, 250)
        self.assertEqual(witness_common(None, box), (0, 0))

    def test_a_curved_body_that_truly_misses_stays_clear(self) -> None:
        """There is no false positive where the bodies REALLY are apart."""
        cylinder = BRepPrimAPI_MakeCylinder(100.0, 50.0).Shape()
        far = BRepPrimAPI_MakeBox(gp_Pnt(9000, 9000, 9000), gp_Pnt(9200, 9200, 9100)).Shape()
        verdict = verify_pair(cylinder, far)
        self.assertIsNone(verdict.refusal)
        self.assertEqual(verdict.relation, "clear")
        self.assertGreater(verdict.gap_mm, 0.0)

    def test_planar_pairs_do_not_pay_for_the_witness(self) -> None:
        """The witness costs 0.5 s; no defect was observed on planar bodies."""
        box = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), gp_Pnt(200, 200, 100)).Shape()
        far = BRepPrimAPI_MakeBox(gp_Pnt(9000, 9000, 9000), gp_Pnt(9200, 9200, 9100)).Shape()
        verdict = verify_pair(box, far)
        self.assertEqual(verdict.relation, "clear")
        self.assertLess(verdict.cost_ms, 400.0,
                        "плоская пара не должна платить за сетку свидетеля")


class ThePolicyCarriesTheWitnessDensity(unittest.TestCase):
    """The grid's density CHANGES the answer, so it must be in the digest."""

    def test_the_density_is_declared_and_digested(self) -> None:
        self.assertEqual(DEFAULT_POLICY.witness_grid_n, 5)
        self.assertIn("witness_grid_n", DEFAULT_POLICY.to_dict())
        self.assertNotEqual(DEFAULT_POLICY.digest,
                            TolerancePolicy(witness_grid_n=7).digest,
                            "два прогона с разной плотностью не сравнимы — "
                            "дайджест обязан их различать")

    def test_a_meaningless_density_is_refused(self) -> None:
        for value in (0, 1, -3, 2.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TolerancePolicy(witness_grid_n=value)


if __name__ == "__main__":                                     # pragma: no cover
    unittest.main()
