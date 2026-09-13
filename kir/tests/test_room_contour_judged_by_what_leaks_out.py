"""A room's footprint is judged by what came out OUTSIDE it, not by IoU.

🔴 THE MEASUREMENT THAT BOUGHT THE RULE (27.08.2026, a live run on a real
building).

A room 4.0 x 3.5 m was built with 200 mm walls. KIR's declared footprint
is assembled from the walls' CENTERLINES: 4000 x 3500 = 14.00 m². Revit
returned the room boundary along the INNER FACES: 3800 x 3300 = 12.54 m²
— matched to the hundredth.

That is, `IoU < 1.0` is true for EVERY correctly built room, and the
previous condition would fail the geometry check for any one of them.

WORSE, IoU DOES NOT DISTINGUISH CORRECT FROM BROKEN:

    case                            IoU     outside the declared area
    correct, 200 mm walls         0.896            0.0000
    correct, 400 mm walls         0.797            0.0000
    leaked outward past a wall    0.805            0.1333
    placed with an offset         0.627            0.1842

0.805 for the leaked one against 0.797 for the correct one with thick
walls — no threshold on IoU can separate them. The fraction that came out
OUTSIDE separates them by two orders of magnitude: a cutout the thickness
of a wall always lies INSIDE the centerline footprint.
"""
import unittest

from shapely.geometry import Polygon

from kir.design_check import _ROOM_OUTSIDE_TOL

ОСЕВОЙ = Polygon([(0, 0), (4000, 0), (4000, 3500), (0, 3500)])


def _вне(построено: Polygon) -> float:
    """The fraction of the built footprint that lies outside the
    declared one."""
    return max(0.0, 1.0 - ОСЕВОЙ.intersection(построено).area / построено.area)


def _iou(построено: Polygon) -> float:
    return (ОСЕВОЙ.intersection(построено).area
            / ОСЕВОЙ.union(построено).area)


class ВырезНаТолщинуСтеныНеРасхождение(unittest.TestCase):

    def test_правильная_комната_не_даёт_ничего_наружу(self):
        for толщина in (100, 200, 300, 400, 500):
            п = толщина / 2.0
            комната = Polygon([(п, п), (4000 - п, п),
                               (4000 - п, 3500 - п), (п, 3500 - п)])
            with self.subTest(толщина_мм=толщина):
                self.assertAlmostEqual(_вне(комната), 0.0, places=6,
                                       msg="граница по внутренним граням лежит "
                                           "ВНУТРИ осевого контура по построению")
                self.assertLessEqual(_вне(комната), _ROOM_OUTSIDE_TOL)

    def test_живое_число_воспроизводится_точно(self):
        """4.0 x 3.5 m, 200 mm walls — the very 12.54 m² that Revit
        returned."""
        комната = Polygon([(100, 100), (3900, 100), (3900, 3400), (100, 3400)])
        self.assertAlmostEqual(комната.area / 1e6, 12.54, places=2)
        self.assertAlmostEqual(ОСЕВОЙ.area / 1e6, 14.00, places=2)
        self.assertAlmostEqual(_iou(комната), 0.896, places=3)
        self.assertAlmostEqual(_вне(комната), 0.0, places=6)


class ПротечкаОтличаетсяОтВыреза(unittest.TestCase):

    def test_протёкшая_и_сдвинутая_ловятся(self):
        случаи = {
            "протекла за стену": Polygon([(100, 100), (4600, 100),
                                          (4600, 3400), (100, 3400)]),
            "встала со сдвигом": Polygon([(900, 100), (4700, 100),
                                          (4700, 3400), (900, 3400)]),
        }
        for имя, п in случаи.items():
            with self.subTest(случай=имя):
                self.assertGreater(
                    _вне(п), _ROOM_OUTSIDE_TOL,
                    "контур, вышедший за осевые линии, обязан быть пойман")

    def test_IoU_ЭТИ_СЛУЧАИ_НЕ_РАЗЛИЧАЕТ(self):
        """The control the rule was rewritten for.

        If this test ever goes red, it means IoU has suddenly started
        distinguishing a leak from thick walls, and the whole
        justification needs to be rechecked. As long as it is green, a
        threshold on IoU is impossible IN PRINCIPLE, not merely "poorly
        chosen"."""
        протекла = Polygon([(100, 100), (4600, 100), (4600, 3400), (100, 3400)])
        толстые = Polygon([(200, 200), (3800, 200), (3800, 3300), (200, 3300)])
        self.assertGreater(_iou(протекла), _iou(толстые),
                           "у ПРОТЁКШЕЙ IoU выше, чем у правильной со стенами "
                           "400 мм — значит по IoU сломанное выглядит лучше "
                           "исправного, и порог по нему разделить их не может")
        self.assertGreater(_вне(протекла), _ROOM_OUTSIDE_TOL)
        self.assertLessEqual(_вне(толстые), _ROOM_OUTSIDE_TOL)


if __name__ == "__main__":
    unittest.main()
