"""AN ARC MUST NOT BE SILENTLY STRAIGHTENED INTO A CHORD — NEITHER THE WALL,
NOR AN OPENING IN IT.

Audit findings `F-060` (P0) and `F-061`, `kir/preview.py`. One class: the
drawing shows the human a STRAIGHT line where a CURVE stands, while the
census at the same time says "coverage 100%".

`F-060`. `L0` DISTINGUISHES `LocationCurveKind.ARC`. The real arc was taken
only from `curve_index`; if the index is absent, empty, or its row is
corrupt — `arc` stayed `None`, and a semicircular wall was drawn as a
rectangle along the chord. Neither an approximation nor an omission was
recorded. Measured on the same semicircle of radius 3 m:

    index EXISTS and is valid    drawn 1  coverage 100.0%  POINTS 66
    index MISSING entirely       drawn 1  coverage 100.0%  POINTS  4   <- chord
    index EMPTY {}               drawn 1  coverage 100.0%  POINTS  4
    index CORRUPT                drawn 1  coverage 100.0%  POINTS  4

🔴 66 AGAINST 4 — THAT IS THE WHOLE PROOF, and coverage in both rows reads 100%.

The tree ALREADY KNOWS HOW to refuse: a spline (`curve_kind == "other"`)
honestly gets `UNSUPPORTED_CURVE` with the argument "CANNOT be straightened
into a chord. Refusal, not approximation". Exactly the same argument holds
for an arc without data — and exactly there it was missing.

🔴 THE FORK, NAMED FOR THE LEAD: REFUSAL or APPROXIMATION. Refusal removes
the wall from the plan and counts it in the census with a reason;
approximation would have kept it and required a NEW `ApproxReason` kind,
which would have to be carried through to the sheet and to KUKAI. REFUSAL
was chosen: it is HOMOGENEOUS with the spline case — one law, not two.

`F-061`. An opening on an arced wall is calculated by the CHORD even when
the arc is read EXACTLY: position, normal, width, and swing direction all
take only `p0 -> p1`. For a semicircle the chord is 2R against the arc's
πR — the "opening wider than its host" check computes against the SHORT
one and stays silent exactly where there is no room.

THE FIRST MOVE IS AN ADMISSION, NOT GEOMETRY. Computing by the arc means
setting up parameterization along the arc, the normal at a point, and a
local basis for the swing — that is a piece of work, not a fix, and it
must not be mixed up with the repair. Before that work, the opening MUST
stop passing itself off as exact: a new kind, `ApproxReason.OPENING_ON_CHORD`.
"""
from __future__ import annotations

import unittest

from kir.decompile.schema import LocationCurveKind
from kir.tests.test_preview import _doc, _opening, _wall

import kir.preview as P

_ARC = {"center_mm": [3000.0, 0.0], "radius_mm": 3000.0,
        "x_axis": [1.0, 0.0], "y_axis": [0.0, 1.0],
        "start_angle_rad": 0.0, "end_angle_rad": 3.141592653589793}


def _plan(elements, curve_index=None):
    return P.build_model_preview(_doc(), elements,
                                 curve_index=curve_index).plan("L1")


def _points(plan) -> int:
    return sum(len(ring) for e in plan.elements for s in e.shapes
               for ring in getattr(s, "loops", ()) or ())


def _omitted(plan):
    return {getattr(g.reason, "value", str(g.reason)): g.count
            for g in plan.census.omitted}


def _approx(plan):
    return {getattr(a, "value", str(a))
            for e in plan.elements for a in (e.approx or ())}


class ОбъявленнаяДугаБезДанныхНеСтановитсяПрямой(unittest.TestCase):
    """F-060."""

    def _arc_wall(self):
        return _wall("1", (0.0, 0.0), (6000.0, 0.0),
                     curve_kind=LocationCurveKind.ARC)

    def test_a_readable_arc_is_still_drawn_as_an_arc(self) -> None:
        """🔴 THE GREEN OUTCOME FIRST: the fix must not dare take away what already works."""
        plan = _plan([self._arc_wall()],
                     curve_index={"1": {"curve_kind": "arc", "arc": _ARC}})
        self.assertEqual(plan.census.drawn, 1)
        self.assertGreater(_points(plan), 60, "дуга перестала сэмплироваться")
        self.assertIn("arc_sampled", _approx(plan))

    def test_a_declared_arc_without_data_is_refused_not_straightened(self) -> None:
        """🔴 THE SUBJECT. Three paths to the loss — all three MUST give the same answer."""
        for label, index in (("индекса нет", None),
                             ("индекс пуст", {}),
                             ("индекс битый",
                              {"1": {"curve_kind": "arc",
                                     "arc": {"center_mm": [3000.0, 0.0]}}})):
            with self.subTest(label=label):
                plan = _plan([self._arc_wall()], curve_index=index)
                self.assertEqual(plan.census.drawn, 0,
                                 "дуга нарисована ХОРДОЙ")
                self.assertEqual(_omitted(plan), {"unsupported_curve": 1})

    def test_a_straight_wall_is_untouched(self) -> None:
        """🔴 THE SECOND GREEN OUTCOME. Without it a fix of "refuse every wall
        without an index" would pass, and most walls in a building are straight."""
        plan = _plan([_wall("1", (0.0, 0.0), (6000.0, 0.0),
                            curve_kind=LocationCurveKind.LINE)])
        self.assertEqual(plan.census.drawn, 1)
        self.assertEqual(_points(plan), 4)
        self.assertEqual(_omitted(plan), {})

    def test_the_answer_matches_the_spline_which_already_refused(self) -> None:
        """ONE LAW, NOT TWO: the spline has the same outcome and the same reason."""
        spline = _plan([_wall("1", (0.0, 0.0), (6000.0, 0.0),
                              curve_kind=LocationCurveKind.OTHER)])
        arc_lost = _plan([self._arc_wall()])
        self.assertEqual(_omitted(spline), _omitted(arc_lost))


class ПроёмНаДугеНеВыдаётСебяЗаТочный(unittest.TestCase):
    """F-061."""

    def test_an_opening_on_a_read_arc_says_it_is_on_the_chord(self) -> None:
        """🔴 THE SUBJECT: the arc is read EXACTLY, and the opening is still by the chord."""
        plan = _plan([_wall("1", (0.0, 0.0), (6000.0, 0.0),
                            curve_kind=LocationCurveKind.ARC),
                      _opening("2", "1", (3000.0, 0.0))],
                     curve_index={"1": {"curve_kind": "arc", "arc": _ARC}})
        self.assertIn("opening_on_chord", _approx(plan))

    def test_an_opening_on_a_straight_host_claims_nothing(self) -> None:
        """🔴 THE GREEN OUTCOME. A flag on a straight wall would be noise on
        every opening in the building."""
        plan = _plan([_wall("1", (0.0, 0.0), (6000.0, 0.0),
                            curve_kind=LocationCurveKind.LINE),
                      _opening("2", "1", (3000.0, 0.0))])
        self.assertNotIn("opening_on_chord", _approx(plan))

    def test_every_approx_reason_has_human_text(self) -> None:
        """The new kind is ADDITIVE, and it MUST reach the sheet as words,
        not as a code. The check is exhaustive over the enumeration: the
        next kind without text will turn red here, rather than appear on
        the sheet as a raw code."""
        missing = [r.value for r in P.ApproxReason if r not in P._APPROX_TEXT]
        self.assertEqual(missing, [])
        self.assertIn(P.ApproxReason.OPENING_ON_CHORD, P._APPROX_TEXT)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
