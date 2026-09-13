"""A MEASUREMENT MUST SURVIVE ITS OWN PRINTING (F-088 · F-028 · F-148).

One class of defect in four places: a certified separating translation is
checked against `geom.SEP_EPS_MM = 1e-6`, but was published and printed
with a step of 0.001 mm and even down to WHOLE millimetres. A move of
(0, 0, -0.0004) mm, which DOES separate the pair, came out as `[0, 0, 0]`,
"shift by (+0, +0, +0) mm", and "along −Y by 0 mm" — that is, an
instruction to move nothing at all, named certified.

🔴 THE GUARD LOOKS AT THE PROMISE, NOT AT THE SHAPE. The string and the
dictionary are parsed BACKWARD, and the number read out of them is held to
the same thing that was promised: `geom.separates`. A guard that compares a
string to a sample string is defeated by reshaping it — that is exactly the
incident of "an instrument gamed by reshaping guards nothing."

Every check has BOTH outcomes: next to a pair where today's printing loses
the point, stands a pair with WHOLE-NUMBER coordinates, whose output must
stay BYTE-FOR-BYTE the same as before. Without it, a fix of "print six
digits for everyone" would pass the loss check and would silently rewrite
the canon.
"""

from __future__ import annotations

import re
import unittest

from kir import clash_judgement as J
from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import resolve as R


#: A pair with a hull STUCK at sub-micron depth: a separating move exists,
#: it is certified, and it is smaller than 0.001 mm. The case is picked TO
#: MATCH the defect's subject (loss of digits), not for convenience of
#: notation.
DEEP_A = G.Aabb((0.0, 0.0, 0.0), (1000.0, 1000.0, 1000.0))
DEEP_B = G.Aabb((999.9996, 999.9996, 999.9996), (2000.0, 2000.0, 2000.0))

#: A degeneracy control: the same roles, WHOLE-NUMBER coordinates.
FLAT_A = G.Aabb((0.0, 0.0, 0.0), (10.0, 10.0, 10.0))
FLAT_B = G.Aabb((5.0, 0.0, 0.0), (15.0, 10.0, 10.0))


def _rec(eid: str, hull: G.Hull, label: str, cat: str, side: str) -> H.HullRecord:
    return H.HullRecord(source_id=eid, category=cat, label=label, mvp_side=side,
                        hull=hull, grade="conservative", hull_source="prism",
                        inner=None)


def _pair(a: G.Hull, b: G.Hull) -> tuple[H.HullRecord, H.HullRecord]:
    return (_rec("a", a, "pipe", "OST_PipeCurves", "mep"),
            _rec("b", b, "wall", "OST_Walls", "structure"))


class ОпубликованныйВекторОбязанРазводить(unittest.TestCase):
    """F-088 — `detect.Finding.as_dict`, the source of the number."""

    def test_the_published_certified_translation_still_separates(self):
        row = D.evaluate(*_pair(DEEP_A, DEEP_B)).as_dict()
        v = row["certified_separating_translation_mm"]
        self.assertIsNotNone(v, "сертифицированный ход обязан быть")
        self.assertIsNone(row["translation_unavailable_reason"])
        # A promise, not an appearance: whether it is exactly what was
        # published that pulls things apart.
        self.assertTrue(
            G.separates(DEEP_A, DEEP_B, tuple(v)),
            "опубликованный вектор %r обещания не держит" % (v,))

    def test_the_published_depth_agrees_with_the_published_distance(self):
        """`hull_overlap_depth_mm` is `max(0, -signed_distance_mm)`.

        Two fields about ONE quantity were printed with different steps and
        diverged silently: the depth came out `0.0` while `hull_relation:
        "overlap"`.
        """
        for a, b in ((DEEP_A, DEEP_B), (FLAT_A, FLAT_B)):
            with self.subTest(a=a, b=b):
                row = D.evaluate(*_pair(a, b)).as_dict()
                self.assertAlmostEqual(
                    row["hull_overlap_depth_mm"],
                    max(0.0, -row["signed_distance_mm"]),
                    places=9,
                    msg="глубина и знаковое расстояние разошлись в отчёте")

    def test_an_integral_pair_is_published_exactly_as_before(self):
        """🔴 THE SECOND OUTCOME. Whole-number coordinates — the report's bytes do not move."""
        row = D.evaluate(*_pair(FLAT_A, FLAT_B)).as_dict()
        self.assertEqual(row["signed_distance_mm"], -5.0)
        self.assertEqual(row["hull_overlap_depth_mm"], 5.0)
        self.assertEqual(row["certified_separating_translation_mm"],
                         [0.0, 0.0, 10.0])
        self.assertEqual(row["clearance_mm"], 0.0)
        self.assertEqual(row["ranking_tol_mm"], 1.0)


class ПредложениеОбязаноНестиИсполнимоеЧисло(unittest.TestCase):
    """The fourth place of the same class: `resolve.Move.as_dict`."""

    def test_the_published_move_vector_still_separates(self):
        p = R.propose(*_pair(DEEP_A, DEEP_B))
        self.assertIsNotNone(p.chosen)
        d = p.as_dict()["chosen"]
        self.assertTrue(d["certified"])
        self.assertTrue(
            G.separates(DEEP_A, DEEP_B, tuple(d["vector_mm"])),
            "квитанция говорит `certified`, а опубликованный ход %r "
            "не разводит" % (d["vector_mm"],))

    def test_the_published_direction_times_distance_is_the_published_vector(self):
        """A reader who multiplies the direction by the distance must get
        exactly the published vector — otherwise there are three fields but
        two numbers."""
        p = R.propose(*_pair(DEEP_A, DEEP_B))
        d = p.as_dict()["chosen"]
        for got, want in zip(
                (c * d["distance_mm"] for c in d["direction"]),
                d["vector_mm"]):
            self.assertLessEqual(abs(got - want), G.SEP_EPS_MM)

    def test_an_integral_move_is_published_exactly_as_before(self):
        """🔴 THE SECOND OUTCOME."""
        p = R.propose(*_pair(FLAT_A, FLAT_B))
        d = p.as_dict()["chosen"]
        self.assertEqual(d["vector_mm"], [-5.0, 0.0, 0.0])
        self.assertEqual(d["distance_mm"], 5.0)
        self.assertEqual(d["direction"], [-1.0, 0.0, 0.0])


def _move(direction, distance):
    return R.Move("p1", "труба", "OST_PipeCurves", direction, distance,
                  tuple(c * distance for c in direction), True, True)


class РусскаяСтрокаИсполнимаБезПереписывания(unittest.TestCase):
    """F-148 — `resolve.to_russian`, a string for a HUMAN."""

    #: 20° off the −Y axis. `int(round(...))` used to snap this to a clean "along −Y".
    OFF_AXIS = (0.342, -0.940, 0.0)

    def test_a_non_axis_direction_is_not_called_an_axis(self):
        line = R.to_russian(R.Proposal("f", "move", _move(self.OFF_AXIS, 12.3),
                                       None, None, "absent"))
        self.assertNotIn("по −Y", line)
        self.assertIn("вектор:", line)

    def test_the_printed_move_multiplies_back_to_the_vector(self):
        """🔴 THE PROMISE, NOT THE SHAPE. The direction and distance are read
        OUT OF THE STRING, multiplied, and checked against `Move.vector_mm`
        with the certificate's tolerance."""
        for distance in (0.4, 0.04, 7.6, 12.3):
            with self.subTest(distance=distance):
                m = _move(self.OFF_AXIS, distance)
                line = R.to_russian(
                    R.Proposal("f", "move", m, None, None, "absent"))
                got = re.search(
                    r"по \((-?[\d.]+), (-?[\d.]+), (-?[\d.]+)\) на "
                    r"(-?[\d.]+) мм", line)
                self.assertIsNotNone(got, "строка не разбирается: %r" % line)
                direction = tuple(float(x) for x in got.group(1, 2, 3))
                read = tuple(c * float(got.group(4)) for c in direction)
                for a, b in zip(read, m.vector_mm):
                    self.assertLessEqual(
                        abs(a - b), G.SEP_EPS_MM,
                        "прочитанный из строки ход %r разошёлся с %r"
                        % (read, m.vector_mm))

    def test_a_sub_millimetre_axial_move_keeps_its_number(self):
        """The second half of the fix is checked SEPARATELY from the first:
        a real axis, but a distance under a millimetre."""
        line = R.to_russian(R.Proposal("f", "move", _move((0.0, -1.0, 0.0), 0.4),
                                       None, None, "absent"))
        self.assertEqual(
            line, "f: сдвиньте труба p1 по −Y на 0.4 мм — ход свободен")

    def test_a_whole_millimetre_axial_move_is_printed_exactly_as_before(self):
        """🔴 THE SECOND OUTCOME. An axial move in whole mm — the string
        stays BYTE-FOR-BYTE the same, and there is no vector in it: for an
        axial move it is printed without error."""
        line = R.to_russian(R.Proposal("f", "move", _move((0.0, -1.0, 0.0), 25.0),
                                       None, None, "absent"))
        self.assertEqual(
            line, "f: сдвиньте труба p1 по −Y на 25 мм — ход свободен")
        self.assertNotIn("вектор:", line)


class КвитанцияНазываетНастоящееЧисло(unittest.TestCase):
    """F-028 — `clash_judgement._next_move`, the move in the receipt."""

    FINDING = {"a": {"source_element_id": "p1", "label": "pipe",
                     "category": "OST_PipeCurves"},
               "b": {"source_element_id": "w1", "label": "wall",
                     "category": "OST_Walls"}}

    def _line(self, vector):
        finding = dict(self.FINDING,
                       certified_separating_translation_mm=vector)
        return J._next_move("run_meets_run", finding, (), None, None, True)

    def test_the_printed_translation_still_separates(self):
        """🔴 THE PROMISE, NOT THE SHAPE: the vector is read OUT OF the
        receipt's string, and `geom.separates` is required of it on the
        same pair."""
        vector = G.certified_separating_translation(DEEP_A, DEEP_B)
        self.assertIsNotNone(vector)
        line = self._line([D.G._norm_zero(round(float(c), 9)) for c in vector])
        got = re.search(r"на \((\+?-?[\d.]+), (\+?-?[\d.]+), (\+?-?[\d.]+)\) мм",
                        line)
        self.assertIsNotNone(got, "строка не разбирается: %r" % line)
        read = tuple(float(x) for x in got.group(1, 2, 3))
        self.assertTrue(G.separates(DEEP_A, DEEP_B, read),
                        "напечатанный ход %r обещания не держит" % (read,))

    def test_a_sub_millimetre_move_is_not_printed_as_zero(self):
        self.assertIn("(+0.4, +0, +0)", self._line([0.4, 0.0, 0.0]))
        self.assertIn("(+0.0004, +0, +0)", self._line([0.0004, 0.0, 0.0]))

    def test_an_integral_move_is_printed_exactly_as_before(self):
        """🔴 THE SECOND OUTCOME."""
        self.assertEqual(
            self._line([12.0, 0.0, 0.0]),
            "развести: сдвинуть `оп p1` на (+12, +0, +0) мм — это "
            "сертифицированный разводящий перенос детектора")

    def test_the_branch_without_a_vector_is_untouched(self):
        """The "no vector" branch prints the run's diameter and is untouched
        by the fix: the diameter is declared by the author in whole
        millimetres and carries no certificate."""
        finding = dict(self.FINDING, certified_separating_translation_mm=None)
        line = J._next_move("run_meets_run", finding, (),
                            {"op": "create_pipe", "diameter_mm": 110}, None, True)
        self.assertIn("Ø110 мм", line)


if __name__ == "__main__":
    unittest.main()
