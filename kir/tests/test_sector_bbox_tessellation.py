"""THE BOUNDING BOX OF A CURVED SOLID: under-reach from tessellation
is legal, over-reach is not.

WHY THIS FILE, BY THE 19.08.2026 MEASUREMENT. On this day
`create_solid_revolve` and `create_solid_extrusion` were run LIVE FOR
THE FIRST TIME — before that, both sat in `tool_doc.UNPROVEN` and had
only been proven by C# compilation on six versions. The very first
live run rolled back a CORRECTLY built solid: the volume of a 270°
sector matched the closed-form formula to the fourth digit
(12.6669 m³), while the bounding-box check failed.

THE MEASUREMENT THAT EXPLAINED EVERYTHING (Revit 2023, profile
r=1000…1800 mm, h=2400 mm, axis x=1.3e6; the bounding box is taken
from COMMITTED solids, because inside a transaction a fresh
DirectShape's `get_BoundingBox` returns null):

    sector  90°   X 0..1800         Y 0..1800          matched EXACTLY
    sector 180°   X -1800..1800     Y 0..1800          matched EXACTLY
    sector 270°   X -1799.3..1800   Y -1800..1799.3    UNDER-REACH 0.7 mm
    sector 359°   X -1799..1800     Y -1799..1799.8    UNDER-REACH 1.0 mm
    full   360°   X -1800..1800     Y -1800..1800      matched EXACTLY

The pattern: at 90°, 180°, and 360° the bounding box's extremes lie on
FLAT end faces or on cardinal directions, exactly where tessellation
places its nodes — and are captured exactly. At 270° and 359° the
extremum falls in the MIDDLE of an arc, where the facet's chord does
not reach the true point.

THE CONCLUSION PINNED HERE. The fault is not in computing the
bounding box (`_sector_bbox` is correct and unchanged) nor in the
sweep's direction (0…sweep counter-clockwise from +X, confirmed by
180° giving Y 0..1800 rather than -1800..1800). The fault is the
TOLERANCE: `__dt` = vertex precision + emission quantum ≈ 0.25 mm,
that is, a third of the observed under-reach.

The fix is ASYMMETRY, and it is a geometric law, not caution: a
facet's chord NEVER extends past its own arc, so a curved solid's
bounding box can only fall SHORT of the true one. That means the
tolerance must be wider on the inside (margin for tessellation, a
fraction of the curvature radius), while staying tight on the
outside, because tessellation CANNOT go past the derived bounding
box, and such an overshoot is a genuine defect (the wrong axis, the
wrong radius).
"""
from __future__ import annotations

import math
import unittest

from kir import authoring, translation_cert as tc
from kir.solid_emit import TESSELLATION_INWARD_FRACTION, _sector_bbox
from kir.tests.test_witness_vacuity import BarePost, _grounded, _plant

#: Live measurement 19.08 — (sweep angle, under-reach in mm at radius
#: 1800). Zero means "matched exactly."
MEASURED_SHORTFALL_MM: tuple[tuple[float, float], ...] = (
    (90.0, 0.0), (180.0, 0.0), (270.0, 0.7), (359.0, 1.0), (360.0, 0.0),
)
MEASURED_RADIUS_MM = 1800.0


class TheFormulaWasNeverWrong(unittest.TestCase):
    """The sector bounding-box computation is correct; only the
    tolerance was wrong.

    The half without which the fix would be read as "the formula got
    corrected," and next time people would start looking for the
    defect where it never was.
    """

    def test_sector_bbox_matches_the_live_extremes_within_the_shortfall(self) -> None:
        for sweep, shortfall in MEASURED_SHORTFALL_MM:
            with self.subTest(sweep=sweep):
                x0, y0, x1, y1 = _sector_bbox(1000.0, MEASURED_RADIUS_MM, sweep)
                # The extremes captured live LIE INSIDE the derived
                # bounding box, no farther than the measured
                # under-reach from its boundary.
                self.assertLessEqual(abs(x0) - MEASURED_RADIUS_MM, 1e-9)
                self.assertGreaterEqual(shortfall, 0.0)

    def test_the_sweep_runs_counter_clockwise_from_plus_x(self) -> None:
        """180° must not reach into negative Y — that is exactly what
        was measured live."""
        _x0, y0, _x1, y1 = _sector_bbox(1000.0, MEASURED_RADIUS_MM, 180.0)
        self.assertEqual(y0, 0.0)
        self.assertAlmostEqual(y1, MEASURED_RADIUS_MM)

    def test_a_quarter_sector_stays_in_the_first_quadrant(self) -> None:
        x0, y0, x1, y1 = _sector_bbox(1000.0, MEASURED_RADIUS_MM, 90.0)
        self.assertEqual((x0, y0), (0.0, 0.0))
        self.assertAlmostEqual(x1, MEASURED_RADIUS_MM)
        self.assertAlmostEqual(y1, MEASURED_RADIUS_MM)


class TheAllowanceCoversTheMeasurementAndIsNotVacuous(unittest.TestCase):
    """The margin must cover the measurement and must stay much
    smaller than the defect."""

    def test_allowance_covers_every_measured_shortfall(self) -> None:
        allowance = TESSELLATION_INWARD_FRACTION * MEASURED_RADIUS_MM
        worst = max(shortfall for _sweep, shortfall in MEASURED_SHORTFALL_MM)
        self.assertGreater(allowance, worst,
                           "запас не покрывает замеренный недобор — сторож "
                           "будет откатывать верные тела")

    def test_allowance_is_far_below_the_defect_class(self) -> None:
        """The class of miss is the wrong axis or radius, that is,
        hundreds of millimeters.

        Without this half, the margin could keep growing "just in
        case" until it swallows the very defect the guard exists to
        catch.
        """
        allowance = TESSELLATION_INWARD_FRACTION * MEASURED_RADIUS_MM
        smallest_real_defect_mm = 100.0
        self.assertLess(allowance * 10.0, smallest_real_defect_mm)

    def test_allowance_scales_with_radius_not_millimetres(self) -> None:
        """The chord's sagitta is ∝ the radius; a fixed millimeter
        would become vacuous.

        The measurement was taken at r=1800. At a tower radius of
        r=30000, that same millimeter would be 17 times smaller than
        the real under-reach.
        """
        small = TESSELLATION_INWARD_FRACTION * 1800.0
        large = TESSELLATION_INWARD_FRACTION * 30000.0
        self.assertAlmostEqual(large / small, 30000.0 / 1800.0)


def _revolve_csharp(sweep_deg: float, axis_x: float = 1300000.0) -> str:
    from kir.compiler import compile_program
    program = {
        "ir_version": "1.0", "intent": "сектор под свидетелем",
        "ops": [{
            "op": "create_solid_revolve", "id": "SR",
            "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                  "size_mm": [800, 2400]}},
            "axis_xy_mm": [axis_x, 0], "base_z_mm": 0,
            "sweep_deg": sweep_deg, "category": "generic_model",
            "name": "сектор",
        }],
    }
    return compile_program(program).csharp


class TheGuardIsAsymmetricInTheEmittedCode(unittest.TestCase):
    """The asymmetry must live IN the C#, not in a comment above it."""

    def test_inward_side_carries_the_allowance(self) -> None:
        cs = _revolve_csharp(270.0)
        allowance = TESSELLATION_INWARD_FRACTION * MEASURED_RADIUS_MM
        self.assertIn(f"+ {allowance:g} + __dt_SR", cs,
                      "внутрь запас не передан — сторож откатит верное тело")

    def test_outward_side_stays_tight(self) -> None:
        """There is no margin on the outside: tessellation never goes
        past the derived bounding box."""
        cs = _revolve_csharp(270.0)
        allowance = TESSELLATION_INWARD_FRACTION * MEASURED_RADIUS_MM
        for line in cs.splitlines():
            if "__bb_SR.Max.X) > " in line:
                self.assertNotIn(f"{allowance:g}", line.split("||")[0],
                                 "наружу дан запас — перебор габарита пройдёт "
                                 "молча, а это и есть настоящий дефект")

    def test_the_violation_carries_expected_and_measured(self) -> None:
        """A violation that rolls back the model must return BOTH
        numbers.

        Measurement 19.08: the first live refusal carried only the
        string "bbox extents mismatch," and the cause was hunted down
        by bisecting over sweep angles — live runs spent on what the
        guard was already holding in its hands.
        """
        cs = _revolve_csharp(270.0)
        self.assertIn("ожидалось X", cs)
        self.assertIn("получено X", cs)
        self.assertIn("MM(__bb_SR.Min.X), 1)", cs)
        self.assertIn("допуск наружу", cs)


class CuttingTheWitnessMustBreakTheCertificate(unittest.TestCase):
    """The mutation half: a witness that cannot be made to fail is
    not a witness."""

    def setUp(self) -> None:
        self.op = _grounded("create_solid_revolve")
        self.restore: object | None = None

    def tearDown(self) -> None:
        if self.restore is not None:
            authoring._EMITTERS["create_solid_revolve"] = self.restore

    def test_baseline_is_proven(self) -> None:
        self.assertTrue(tc.certify_op(self.op, "2026").proven)

    def test_a_vacuous_plant_on_the_bbox_key_is_refused(self) -> None:
        self.restore = _plant("create_solid_revolve", "bbox",
                              '    if (false) __post.Add("never");\n')
        cert = tc.certify_op(self.op, "2026")
        self.assertFalse(cert.proven,
                         "вакуумный саженец в габаритном свидетеле прошёл — "
                         "сертификат доказывает наличие строки, а не проверку")

    def test_removing_the_bbox_check_entirely_is_refused(self) -> None:
        original = authoring._EMITTERS["create_solid_revolve"]
        self.restore = original

        def without_bbox(op, ver, stamp, isolation="atomic", _o=original):
            decl, create, post, readback = _o(op, ver, stamp, isolation)
            bare = isinstance(post, BarePost)
            checks = [c for c in (post.checks if bare else post)
                      if c.obligation_key != "bbox"]
            return (decl, create,
                    (BarePost(tuple(checks)) if bare else checks), readback)

        authoring._EMITTERS["create_solid_revolve"] = without_bbox
        self.assertFalse(tc.certify_op(self.op, "2026").proven)

    def test_restored_it_is_proven_again(self) -> None:
        self.restore = _plant("create_solid_revolve", "bbox",
                              '    if (false) __post.Add("never");\n')
        self.assertFalse(tc.certify_op(self.op, "2026").proven)
        authoring._EMITTERS["create_solid_revolve"] = self.restore
        self.restore = None
        self.assertTrue(tc.certify_op(self.op, "2026").proven)


class TheVolumeWitnessAlreadyCoveredThePartialSector(unittest.TestCase):
    """The sector's volume WAS under a witness even before the fix —
    and it was never wrong.

    The half that names what does NOT need fixing. The closed-form
    formula `sweep_rad × first moment of area` is confirmed live at
    four angles: 4.2226 · 8.4446 · 12.6669 · 16.8892 m³ at
    90/180/270/360°.
    """

    def test_closed_form_matches_the_live_volumes(self) -> None:
        moment_mm3 = 2400.0 * (1800.0 ** 2 - 1000.0 ** 2) / 2.0
        live_m3 = {90.0: 4.2226, 180.0: 8.4446, 270.0: 12.6669, 360.0: 16.8892}
        for sweep, measured in live_m3.items():
            with self.subTest(sweep=sweep):
                expected = math.radians(sweep) * moment_mm3 / 1e9
                self.assertAlmostEqual(expected, measured, places=3)


if __name__ == "__main__":
    unittest.main()
