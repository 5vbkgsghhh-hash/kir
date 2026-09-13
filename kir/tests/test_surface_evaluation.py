"""THE NURBS SURFACE COMPUTATION IS CHECKED AGAINST A KNOWN ANSWER, NOT AGAINST ITSELF.

WHY THIS FILE. On 20.08.2026 a live run showed that Revit is free to COLLAPSE
a surface's representation: a hyperbolic paraboloid given by a 4×4 grid of
degree 3×3 read back as a bilinear 1×1 patch with four points. The geometry
is the same, the parameterization is different. The previous witness compared
representations and so gave a FALSE RED on correct work.

The replacement is comparing surfaces AS SETS OF POINTS, and it rests on our
own computation (`evaluate_surface`). The instrument the law stands on
must be checked INDEPENDENTLY: if it is wrong, the witness will start
confirming incorrect builds — that is, the refusal becomes quieter than it
was.

The independence here is real, not decorative:

* **Bernstein polynomials** (`_bezier_patch`) compute the Bezier patch by a
  formula sharing no code with de Boor — a different algorithm, a different
  recursion;
* **an exact rational arc**: a quadratic rational Bezier with weights
  (1, √2/2, 1) gives A QUARTER CIRCLE EXACTLY. What is checked is not
  "looks like" but equality of the radius to machine precision — knowledge
  from geometry, not from code;
* **identities** that must hold for any clamped NURBS: corners equal the
  corner control points, partition of unity, affine invariance, the convex
  hull.

🔴 WHAT THESE TESTS DO NOT PROVE: that the samples are SUFFICIENT. A finite
sample cannot prove "the surface did not drift between samples" — that is a
boundary of the method, not a gap in the file, and it is named in
`SAMPLES_PER_SPAN`.
"""
from __future__ import annotations

import math
import unittest

from kir.surface import (MAX_SAMPLES_PER_DIR, SAMPLES_PER_SPAN,
                              evaluate_surface, sample_parameters,
                              sample_surface,
                              surface_domain, uniform_clamped_knots)

_CLAMPED_CUBIC = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
_CLAMPED_LINEAR = [0.0, 0.0, 1.0, 1.0]


def _srf(du, dv, cu, cv, pts, ku=None, kv=None, weights=None) -> dict:
    out = {"degree_u": du, "degree_v": dv, "count_u": cu, "count_v": cv,
           "knots_u": ku or uniform_clamped_knots(du, cu),
           "knots_v": kv or uniform_clamped_knots(dv, cv),
           "control_points_mm": pts}
    if weights is not None:
        out["weights"] = weights
    return out


def _bernstein(n: int, i: int, t: float) -> float:
    """B_i^n(t) — a direct formula, NOT ONE line shared with de Boor."""
    return math.comb(n, i) * (t ** i) * ((1.0 - t) ** (n - i))


def _bezier_patch(pts: list, cu: int, cv: int, u: float, v: float) -> list:
    """A Bezier patch via Bernstein. An independent implementation of the same subject."""
    out = [0.0, 0.0, 0.0]
    for iu in range(cu):
        bu = _bernstein(cu - 1, iu, u)
        for iv in range(cv):
            b = bu * _bernstein(cv - 1, iv, v)
            p = pts[iu * cv + iv]
            for k in range(3):
                out[k] += b * p[k]
    return out


def _grid(cu: int, cv: int, fz) -> list:
    return [[iu * 2000.0, iv * 2000.0, float(fz(iu, iv))]
            for iu in range(cu) for iv in range(cv)]


#: The dome is the shape that Revit built on 20.08 and signed off (3×3, 16 points).
_BUMP = _grid(4, 4, lambda iu, iv: 2500.0 if iu in (1, 2) and iv in (1, 2) else 0.0)
#: The saddle is the hypar that Revit collapsed to bilinear 1×1.
_SADDLE = _grid(4, 4, lambda iu, iv: (iu - 1.5) * (iv - 1.5) * 600.0)


class DeBoorAgreesWithBernstein(unittest.TestCase):
    """The Bezier patch is the one case where the answer is known EXACTLY and simply."""

    def test_bicubic_patch_matches_the_bernstein_formula(self) -> None:
        srf = _srf(3, 3, 4, 4, _BUMP, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        for i in range(11):
            for j in range(11):
                u, v = i / 10.0, j / 10.0
                got = evaluate_surface(srf, u, v)
                want = _bezier_patch(_BUMP, 4, 4, u, v)
                for k in range(3):
                    self.assertAlmostEqual(
                        got[k], want[k], places=9,
                        msg=f"(u={u}, v={v}) ось {k}: де Бур {got[k]}, "
                            f"Бернштейн {want[k]}")

    def test_the_saddle_matches_bernstein_too(self) -> None:
        """The very input that gave the false red live."""
        srf = _srf(3, 3, 4, 4, _SADDLE, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        for i in range(6):
            for j in range(6):
                u, v = i / 5.0, j / 5.0
                got = evaluate_surface(srf, u, v)
                want = _bezier_patch(_SADDLE, 4, 4, u, v)
                for k in range(3):
                    self.assertAlmostEqual(got[k], want[k], places=9)


class TheSaddleIsTrulyRuled(unittest.TestCase):
    """WHY REVIT COLLAPSED THE SADDLE — checked, not taken on faith.

    If the hypar is indeed ruled, then the degree-3×3 surface through this
    grid COINCIDES with the bilinear patch at its four corners. Then the
    "1×1, four points" read live is a legitimate collapse of representation,
    not a corruption of the geometry, and our false red gets an independent
    explanation.
    """

    def test_the_bicubic_saddle_equals_the_bilinear_patch_on_its_corners(self) -> None:
        cubic = _srf(3, 3, 4, 4, _SADDLE, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        corners = [_SADDLE[0], _SADDLE[3], _SADDLE[12], _SADDLE[15]]
        bilinear = _srf(1, 1, 2, 2,
                        [corners[0], corners[1], corners[2], corners[3]],
                        _CLAMPED_LINEAR, _CLAMPED_LINEAR)
        for i in range(11):
            for j in range(11):
                u, v = i / 10.0, j / 10.0
                a = evaluate_surface(cubic, u, v)
                b = evaluate_surface(bilinear, u, v)
                for k in range(3):
                    self.assertAlmostEqual(
                        a[k], b[k], places=6,
                        msg=f"(u={u}, v={v}): бикубическое седло разошлось с "
                            f"билинейным на оси {k}")

    def test_the_bump_is_NOT_bilinear(self) -> None:
        """A CONTROL without which the previous test is worth nothing.

        If ANY grid produced coincidence with the bilinear patch, the test
        above would be checking a property of our own code, not a property
        of the hypar. The dome must diverge — and Revit indeed did NOT
        collapse it (3×3 live).
        """
        cubic = _srf(3, 3, 4, 4, _BUMP, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        corners = [_BUMP[0], _BUMP[3], _BUMP[12], _BUMP[15]]
        bilinear = _srf(1, 1, 2, 2, corners, _CLAMPED_LINEAR, _CLAMPED_LINEAR)
        worst = max(abs(evaluate_surface(cubic, u / 10.0, v / 10.0)[2]
                        - evaluate_surface(bilinear, u / 10.0, v / 10.0)[2])
                    for u in range(11) for v in range(11))
        self.assertGreater(worst, 100.0,
                           "купол совпал с билинейным лоскутом — тогда и "
                           "«седло линейчато» ничего не утверждает")


class ExactRationalArc(unittest.TestCase):
    """The weights are computed HONESTLY: the quarter circle comes out EXACT."""

    R = 5000.0
    H = 3000.0

    def _cylinder_quarter(self) -> dict:
        w = math.sqrt(2.0) / 2.0
        arc = [(self.R, 0.0), (self.R, self.R), (0.0, self.R)]
        pts, weights = [], []
        for iu, (x, y) in enumerate(arc):
            for z in (0.0, self.H):
                pts.append([x, y, z])
                weights.append(1.0 if iu != 1 else w)
        return _srf(2, 1, 3, 2, pts,
                    [0.0, 0.0, 0.0, 1.0, 1.0, 1.0], _CLAMPED_LINEAR,
                    weights=weights)

    def test_every_sample_lies_on_the_circle(self) -> None:
        srf = self._cylinder_quarter()
        for i in range(21):
            for j in range(3):
                p = evaluate_surface(srf, i / 20.0, j / 2.0)
                r = math.hypot(p[0], p[1])
                self.assertAlmostEqual(
                    r, self.R, places=6,
                    msg=f"(u={i/20.0}, v={j/2.0}): радиус {r}, а рациональный "
                        f"Безье с весом √2/2 обязан дать ровно {self.R}")

    def test_dropping_the_weights_LEAVES_the_circle(self) -> None:
        """A CONTROL FOR THE RATIONAL BRANCH: without weights, the same grid gives NOT a circle.

        Without it, the test above would also pass on an implementation that
        ignores the weights — that is, it would be checking the shape of the
        grid, not the division.
        """
        srf = self._cylinder_quarter()
        srf.pop("weights")
        worst = max(abs(math.hypot(*evaluate_surface(srf, i / 20.0, 0.0)[:2]) - self.R)
                    for i in range(21))
        self.assertGreater(worst, 100.0,
                           "нерациональная сетка совпала с окружностью — "
                           "значит веса в вычислении не участвуют")


class IdentitiesAnyClampedSurfaceObeys(unittest.TestCase):

    def test_corners_equal_the_corner_control_points(self) -> None:
        """An identity, not an approximation: clamping is set up for exactly this."""
        for pts in (_BUMP, _SADDLE):
            srf = _srf(3, 3, 4, 4, pts, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
            (u0, u1), (v0, v1) = surface_domain(srf)
            pairs = (((u0, v0), pts[0]), ((u0, v1), pts[3]),
                     ((u1, v0), pts[12]), ((u1, v1), pts[15]))
            for (u, v), want in pairs:
                got = evaluate_surface(srf, u, v)
                for k in range(3):
                    self.assertAlmostEqual(got[k], want[k], places=9)

    def test_a_grid_of_one_repeated_point_evaluates_to_that_point(self) -> None:
        """Partition of unity. A basis sum ≠ 1 will show up here immediately."""
        pts = [[123.0, -456.0, 789.0] for _ in range(16)]
        srf = _srf(3, 3, 4, 4, pts, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        for i in range(7):
            for j in range(7):
                got = evaluate_surface(srf, i / 6.0, j / 6.0)
                for k in range(3):
                    self.assertAlmostEqual(got[k], pts[0][k], places=9)

    def test_translating_every_control_point_translates_every_sample(self) -> None:
        """Affine invariance — a consequence of the same partition of unity."""
        shift = (1111.0, -2222.0, 333.0)
        base = _srf(3, 3, 4, 4, _BUMP, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        moved = _srf(3, 3, 4, 4,
                     [[p[0] + shift[0], p[1] + shift[1], p[2] + shift[2]]
                      for p in _BUMP], _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        for i in range(6):
            for j in range(6):
                a = evaluate_surface(base, i / 5.0, j / 5.0)
                b = evaluate_surface(moved, i / 5.0, j / 5.0)
                for k in range(3):
                    self.assertAlmostEqual(b[k] - a[k], shift[k], places=6)

    def test_samples_stay_inside_the_control_grid_bbox(self) -> None:
        """The convex hull: coarse, but it catches any indexing mistake."""
        srf = _srf(3, 3, 4, 4, _BUMP, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        xs = [p[0] for p in _BUMP]; ys = [p[1] for p in _BUMP]; zs = [p[2] for p in _BUMP]
        for p in sample_surface(srf):
            self.assertGreaterEqual(p[0], min(xs) - 1e-9)
            self.assertLessEqual(p[0], max(xs) + 1e-9)
            self.assertGreaterEqual(p[1], min(ys) - 1e-9)
            self.assertLessEqual(p[1], max(ys) + 1e-9)
            self.assertGreaterEqual(p[2], min(zs) - 1e-9)
            self.assertLessEqual(p[2], max(zs) + 1e-9)


class InteriorKnotsAreHandled(unittest.TestCase):
    """More than one span — the place where a binary search can actually miss."""

    def test_a_surface_with_interior_knots_keeps_the_identities(self) -> None:
        cu = cv = 6
        ku = uniform_clamped_knots(3, cu)
        kv = uniform_clamped_knots(3, cv)
        self.assertEqual(len(set(ku)), 2 + (cu - 4),
                         "вектор без внутренних узлов не проверяет пролёты")
        pts = _grid(cu, cv, lambda iu, iv: (iu * iv) % 5 * 400.0)
        srf = _srf(3, 3, cu, cv, pts, ku, kv)
        (u0, u1), (v0, v1) = surface_domain(srf)
        for (u, v), want in (((u0, v0), pts[0]), ((u0, v1), pts[cv - 1]),
                             ((u1, v0), pts[(cu - 1) * cv]),
                             ((u1, v1), pts[cu * cv - 1])):
            got = evaluate_surface(srf, u, v)
            for k in range(3):
                self.assertAlmostEqual(got[k], want[k], places=8)

    def test_the_span_search_lands_in_the_right_span(self) -> None:
        """Direct evidence: a point at an interior knot must give the same
        answer from both sides — otherwise the span search misses at the
        boundary."""
        cu = cv = 6
        ku = uniform_clamped_knots(3, cu)
        pts = _grid(cu, cv, lambda iu, iv: (iu - iv) ** 2 * 300.0)
        srf = _srf(3, 3, cu, cv, pts, ku, uniform_clamped_knots(3, cv))
        # THE TOLERANCE IS DERIVED, NOT PICKED. The first revision required
        # agreement to within 1e-5 mm and went red at 1.5e-5 — but this was
        # not a "hole", it was the surface's OWN SLOPE: the points are 2e-9
        # of a parameter apart, while the surface travels 10 000 mm per unit
        # of parameter. That is, the test was measuring a derivative and
        # calling it a discontinuity. A genuine span miss gives a jump ON THE
        # ORDER of the control-point spread — thousands of mm — and 1 mm
        # separates the two with three orders of magnitude to spare.
        for knot in sorted(set(ku))[1:-1]:
            a = evaluate_surface(srf, knot - 1e-9, 0.5)
            b = evaluate_surface(srf, knot + 1e-9, 0.5)
            for k in range(3):
                self.assertLess(abs(a[k] - b[k]), 1.0,
                                f"разрыв на внутреннем узле {knot}: "
                                f"{a[k]} против {b[k]}")


class SampleGrid(unittest.TestCase):

    def test_the_grid_includes_both_ends_of_the_domain(self) -> None:
        srf = _srf(3, 3, 4, 4, _BUMP, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        got = sample_surface(srf)
        self.assertEqual(got[0], evaluate_surface(srf, 0.0, 0.0))
        self.assertEqual(got[-1], evaluate_surface(srf, 1.0, 1.0))

    def test_the_count_follows_the_number_of_spans(self) -> None:
        """WAS PINNING THE OLD LAW, REWRITTEN 04.09.2026 — THE ARGUMENT IS A NUMBER.

        The previous line required `spans·SAMPLES_PER_SPAN + 1` samples per
        direction. On one span that is FOUR parameters — 0, ⅓, ⅔, 1 — that
        is, TWO interior points, while the `sample_surface` docstring
        promised `SAMPLES_PER_SPAN` = THREE. The test was pinning not the
        law but its violation: it never checked what was promised, and so it
        never once went red while the uniform step skipped an entire knot
        span (measured 04.09.2026: the narrow span [0.400, 0.402] got ZERO
        samples, and the shape's peak of 10 000 mm stayed outside the
        sample set — `max_z` of the samples was 9290.2).

        The law that is checked now is the one that is declared: the
        boundaries of every non-empty span EXACTLY plus `SAMPLES_PER_SPAN`
        interior points in each, that is, `spans·(SAMPLES_PER_SPAN + 1) + 1`.
        """
        srf = _srf(3, 3, 4, 4, _BUMP, _CLAMPED_CUBIC, _CLAMPED_CUBIC)
        side = 1 * (SAMPLES_PER_SPAN + 1) + 1
        self.assertEqual(len(sample_surface(srf)), side * side)
        # AND THIS IS NOT JUST A DIFFERENT NUMBER: the number of interior
        # points in a span is exactly as promised — we count them, not trust
        # the formula.
        us = sample_parameters(0.0, 1.0, _CLAMPED_CUBIC)
        self.assertEqual(sum(1 for u in us if 0.0 < u < 1.0), SAMPLES_PER_SPAN)

    def test_a_big_grid_is_capped(self) -> None:
        """The ceiling holds the SIZE OF THE EMISSION, and it must work."""
        cu = cv = 40
        pts = _grid(cu, cv, lambda iu, iv: 0.0 if (iu + iv) % 2 else 50.0)
        srf = _srf(3, 3, cu, cv, pts, uniform_clamped_knots(3, cu),
                   uniform_clamped_knots(3, cv))
        self.assertEqual(len(sample_surface(srf)),
                         MAX_SAMPLES_PER_DIR * MAX_SAMPLES_PER_DIR)


if __name__ == "__main__":
    unittest.main()
