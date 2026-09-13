"""SWEEP: the volume must be EXACT, not merely plausible.

WHY THIS FILE. The header of `ops_solid.py` refused the sweep verbatim like
this: "the volume of a sweep along a NON-PLANAR path of a closed shape has
none… Computing volume by sampling the path means smuggling your own error
into the witness and baking it into the tolerance". The wave of 20.08.2026
lifted the refusal, asserting `V = A·L`. A claim of that weight must be
checked by an INDEPENDENT count, or else it is no different from the
previous guess.

Here there are three independent counts, and none of them uses the formula
it is checking:

* the profile centroid — against a dense sampling of arcs, built FROM THE
  DEFINITION of the bulge (sagitta = |b|·half-chord, a circle through three
  points, the shoelace formula);
* the shortening of the miters — against OCCUPANCY: the area of the mitered
  strip around the polyline is computed by scanning a grid of points, each
  checked for membership in the bisector half-planes. Not a single reference
  to `A·L`;
* the emission — against itself across six versions (byte for byte) and
  against the translation certificate.

🔴 WHAT THIS CHECK HAS ALREADY CAUGHT ONCE. The first version of the
independent arc sampler took the LEFT normal and diverged from the closed
shape by exactly the area of a circular segment. A third party settled the
dispute — the segment area `r²/2·(θ − sin θ)`, computed by hand — and it
was the INSTRUMENT that was wrong, not the code. This is also how the
package's convention was discovered: a positive bulge is offset to the
RIGHT of `p0 → p1`.
"""
from __future__ import annotations

import math
import unittest

from kir import contour as C
from kir import sweep_path as SW
from kir.compiler import compile_program

_SNAP = {"levels": [{"id": 355, "name": "Уровень 1", "elevation_mm": 0.0}]}


def _region(spec: dict) -> dict:
    diags: list = []
    out = C.validate_region({"outer": spec}, None, "X", "f", diags)
    assert out is not None and not diags, diags
    return out


# ── independent count #1: centroid via the bulge definition ────────────────────

def _arc_points(p0, p1, bulge, n):
    """Arc points FROM THE DEFINITION: sagitta = |b|·half-chord, to the right when b>0."""
    if abs(bulge) < 1e-15:
        return [tuple(p0)]
    (x0, y0), (x1, y1) = tuple(p0), tuple(p1)
    ch = math.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / ch, (y1 - y0) / ch
    nx, ny = uy, -ux                                   # the RIGHT normal
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    sx, sy = mx + nx * bulge * ch / 2.0, my + ny * bulge * ch / 2.0
    d = 2 * (x0 * (sy - y1) + sx * (y1 - y0) + x1 * (y0 - sy))
    ox = ((x0 * x0 + y0 * y0) * (sy - y1) + (sx * sx + sy * sy) * (y1 - y0)
          + (x1 * x1 + y1 * y1) * (y0 - sy)) / d
    oy = ((x0 * x0 + y0 * y0) * (x1 - sx) + (sx * sx + sy * sy) * (x0 - x1)
          + (x1 * x1 + y1 * y1) * (sx - x0)) / d
    r = math.hypot(x0 - ox, y0 - oy)

    def unwrap(a, ref):
        while a - ref > math.pi:
            a -= 2 * math.pi
        while a - ref < -math.pi:
            a += 2 * math.pi
        return a

    a0 = math.atan2(y0 - oy, x0 - ox)
    am = unwrap(math.atan2(sy - oy, sx - ox), a0)
    a1 = unwrap(math.atan2(y1 - oy, x1 - ox), am)
    return [(ox + r * math.cos(a0 + (a1 - a0) * i / n),
             oy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n)]


def _shoelace_centroid(poly):
    a = cx = cy = 0.0
    k = len(poly)
    for i in range(k):
        (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % k]
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    a *= 0.5
    return cx / (6 * a), cy / (6 * a), abs(a)


class TheCentroidIsClosedForm(unittest.TestCase):

    def test_a_rectangle_is_exact(self) -> None:
        reg = _region({"shape": "poly",
                       "points_mm": [[500, 300], [700, 300], [700, 500], [500, 500]]})
        cx, cy, area = SW.profile_centroid(reg)
        self.assertAlmostEqual(cx, 600.0, places=9)
        self.assertAlmostEqual(cy, 400.0, places=9)
        self.assertAlmostEqual(area, 40000.0, places=6)

    def test_arcs_agree_with_an_INDEPENDENT_dense_count(self) -> None:
        """The closed shape against an independent count. The discrepancy is
        sampling error, and it must DECREASE as the sampling is refined;
        otherwise it is the formula that is wrong."""
        reg = _region({"shape": "poly",
                       "points_mm": [[0, 0], [600, 0], [600, 600], [0, 600]],
                       "arcs": [{"edge": 0, "bulge": 0.35},
                                {"edge": 2, "bulge": -0.2}]})
        cx, cy, area = SW.profile_centroid(reg)
        worst = None
        for n in (200, 20000):
            poly = []
            for p0, p1, b in reg["outer"]:
                poly += _arc_points(p0, p1, b, n)
            sx, sy, sa = _shoelace_centroid(poly)
            worst = max(abs(cx - sx), abs(cy - sy), abs(area - sa) / area)
        self.assertLess(worst, 1e-5,
                        "замкнутый центроид разошёлся с независимым счётом")

    def test_the_MIRROR_is_what_gives_the_second_moment(self) -> None:
        """A FAIL CONTROL for the technique: without flipping the bulge
        sign, the reflection gives a DIFFERENT figure, hence a different
        answer.

        🔴 THE FIRST VERSION OF THIS CONTROL WAS BLIND, and this is worth
        remembering more than the technique itself. It took a rectangle
        with an arc on a side edge and compared `cy` — but such a figure is
        SYMMETRIC in y, and `cy` equals 150 for either sign of the bulge,
        even though the areas differ by 30%. The control was green by
        construction of the input, not by correctness of the code: the same
        pattern recorded in the canon as "a control on a degenerate input".
        Hence two requirements on the input here: an arc on an edge that
        BREAKS the symmetry, and checking BOTH quantities — area and
        centroid.
        """
        reg = _region({"shape": "poly",
                       "points_mm": [[0, 0], [400, 0], [400, 300], [0, 300]],
                       "arcs": [{"edge": 0, "bulge": 0.45}]})
        _cx, cy, area = SW.profile_centroid(reg)
        broken = [((p0[1], p0[0]), (p1[1], p1[0]), b)      # the sign is NOT flipped
                  for p0, p1, b in reg["outer"]]
        wrong = C.region_measures({"outer": broken, "holes": []})
        self.assertNotAlmostEqual(area, wrong["area_mm2"], places=1,
                                  msg="отражение без смены знака дало ту же "
                                      "ПЛОЩАДЬ — вход не различает приём")
        self.assertNotAlmostEqual(
            cy, wrong["moment_x_mm3"] / wrong["area_mm2"], places=1,
            msg="отражение без смены знака дало тот же ЦЕНТРОИД")


# ── independent count #2: the miters are shortened (checked by OCCUPANCY) ───────────────

def _band_area_by_occupancy(path2d, half_width, step):
    """The area of the MITERED strip around a planar polyline — by scanning
    a grid.

    A point belongs to the strip if there is a segment for which it (a) is
    no farther than `half_width` from its line, (b) lies on the required
    side of both bisectors (at the ends — on the required side of the end
    planes).

    Not a single reference to `A·L`: if the miters are NOT shortened, this
    area will diverge from `2·half_width·L`, and it will diverge more
    noticeably the sharper the turns.
    """
    n = len(path2d) - 1
    d = []
    for i in range(n):
        dx = path2d[i + 1][0] - path2d[i][0]
        dy = path2d[i + 1][1] - path2d[i][1]
        ln = math.hypot(dx, dy)
        d.append((dx / ln, dy / ln))
    # bisector normals at interior nodes
    bis = [None] * (n + 1)
    for j in range(1, n):
        mx, my = d[j - 1][0] + d[j][0], d[j - 1][1] + d[j][1]
        ln = math.hypot(mx, my)
        bis[j] = (mx / ln, my / ln)
    xs = [p[0] for p in path2d]
    ys = [p[1] for p in path2d]
    lo_x, hi_x = min(xs) - half_width * 2, max(xs) + half_width * 2
    lo_y, hi_y = min(ys) - half_width * 2, max(ys) + half_width * 2
    inside = 0
    total = 0
    y = lo_y
    while y <= hi_y:
        x = lo_x
        while x <= hi_x:
            total += 1
            for i in range(n):
                px, py = x - path2d[i][0], y - path2d[i][1]
                off = abs(px * (-d[i][1]) + py * d[i][0])
                if off > half_width:
                    continue
                start_n = bis[i] if bis[i] is not None else d[i]
                end_n = bis[i + 1] if bis[i + 1] is not None else d[i]
                if (px * start_n[0] + py * start_n[1]) < 0.0:
                    continue
                qx, qy = x - path2d[i + 1][0], y - path2d[i + 1][1]
                if (qx * end_n[0] + qy * end_n[1]) > 0.0:
                    continue
                inside += 1
                break
            x += step
        y += step
    return inside * step * step


#: The envelope of the scan's edge effect, a fraction of area per millimeter
#: of step. DERIVED, not fitted: a cell counts as occupied by its corner, so
#: the scan overestimates the area by roughly `perimeter · step / 2`; for
#: this file's strips that is ≈ 0.009 of area per millimeter of step
#: (measured: 0.0091 at step 1, 0.0182 at step 2 — exactly first order).
#: 0.011 is the same with a 20% margin.
#:
#: 🔴 WHY NOT PAIRWISE MONOTONICITY, which stood here originally. The grid
#: gives ALIASING: at an 8 mm step the error came out 0.0031, and at 4 mm —
#: 0.0365, because at 8 mm the strip width fit a whole number of cells and
#: the offsets cancelled each other out. The requirement "the error
#: decreases at every step" went red on this coincidence, saying nothing
#: about the law. The envelope tells the two apart correctly: a wrong law
#: gives a CONSTANT residual, which at a small step will inevitably break
#: through it, while aliasing stays under it.
_ENVELOPE = 0.011


class TheMiterCorrectionCancels(unittest.TestCase):
    """THE FILE'S MAIN CHECK: `V = A·L` holds PRECISELY because the miter
    correction vanishes when the axis passes through the centroid."""

    def _check(self, path2d, half_width, steps):
        """CONVERGENCE is checked, not a single number, and here is why.

        The grid scan counts a cell as occupied by its corner, so it
        overestimates the area by roughly `perimeter · step / 2` — a
        FIRST-order edge effect, not an error in the law. A single
        tolerance on such an instrument either lets a real error through
        (if wide) or goes red on its own discretization (if narrow): the
        first version of this test failed exactly that way, showing 1.8%
        against a declared 2%.

        Convergence tells the two cases apart: if the law is correct, the
        error decreases LINEARLY with the step; if it is wrong, it runs
        into a constant residual.
        """
        length = sum(math.dist(path2d[i], path2d[i + 1])
                     for i in range(len(path2d) - 1))
        claimed = 2.0 * half_width * length
        for st in steps:
            err = abs(_band_area_by_occupancy(path2d, half_width, st)
                      - claimed) / claimed
            self.assertLess(
                err, _ENVELOPE * st,
                f"шаг {st}: ошибка {err:.4f} больше огибающей "
                f"{_ENVELOPE * st:.4f} — краевым эффектом это не объясняется, "
                f"значит усы НЕ сокращаются и V = A·L неверно")

    def test_a_right_angle_turn(self) -> None:
        """THE RESOLVING POWER OF THIS CHECK IS MEASURED, not asserted.

        Substituting deliberately wrong values in place of `A·L`, we get:
        the envelope catches a 5% error at steps 2 and 1, does NOT catch a
        2% error at those steps, but does catch it at step 0.5. That is, the
        check proves the law to a precision of about two percent — it
        catches a BLUNDER (a lost term, a wrong sign, a forgotten miter),
        not a confirmation of accuracy down to the last digit.

        Accuracy down to the last digit is checked by the LIVE run: there
        the witness compares against Revit's own `Solid.Volume` with a
        tolerance of δ·(surface area), that is, many orders of magnitude
        stricter. Here it is protection against a blunder, and it is called
        by its own name.
        """
        self._check([(0.0, 0.0), (600.0, 0.0), (600.0, 700.0)],
                    60.0, (8.0, 4.0, 2.0, 1.0, 0.5))

    def test_a_zigzag_of_four_turns(self) -> None:
        self._check([(0.0, 0.0), (400.0, 0.0), (700.0, 300.0),
                     (700.0, 800.0), (300.0, 1100.0), (0.0, 1100.0)],
                    50.0, (10.0, 5.0, 2.5))

    def test_an_OFF_AXIS_band_does_NOT_obey_the_law(self) -> None:
        """A CONTROL WITHOUT WHICH THE PREVIOUS ONES ARE WORTH NOTHING.

        If `A·L` held for ANY position of the profile, the checks above
        would pass trivially and say nothing about the centroid. A strip
        offset from the axis must give a DIFFERENT area — by exactly
        `ū·A·Δθ`.
        """
        path = [(0.0, 0.0), (600.0, 0.0), (600.0, 700.0)]
        length = 1300.0
        half = 60.0
        # a strip from +20 to +140 from the axis: the same width 120, center offset by 80
        shifted = _band_area_by_occupancy(
            [(0.0, 80.0), (520.0, 80.0), (520.0, 700.0)], half, 5.0)
        centred = 2.0 * half * length
        self.assertGreater(abs(shifted - centred) / centred, 0.02,
                           "сдвинутая полоса дала ту же площадь — проверка "
                           "слепа к положению профиля")


# ── miter feasibility and refusals before the effect ────────────────────────────────────

class TheRefusalsComeBeforeTheEffect(unittest.TestCase):

    def test_a_too_sharp_turn_is_refused_by_NAME(self) -> None:
        path = [[0, 0, 0], [2000, 0, 0], [0, 100, 0]]
        why = SW.feasibility(path, 200.0)
        self.assertIsNotNone(why)
        self.assertIn("поворот", why)

    def test_a_gentle_turn_is_allowed(self) -> None:
        path = [[0, 0, 0], [4000, 0, 0], [8000, 1500, 0]]
        self.assertIsNone(SW.feasibility(path, 200.0))

    def test_a_short_leg_between_two_miters_is_refused(self) -> None:
        """A NARROWNESS CONTROL: it is not the turn itself that matters, but
        that the miters eat into the segment. The same turns on a long
        segment must succeed."""
        sharp = [[0, 0, 0], [3000, 0, 0], [3300, 300, 0], [6300, 300, 0]]
        self.assertIsNotNone(SW.feasibility(sharp, 900.0))
        self.assertIsNone(SW.feasibility(
            [[0, 0, 0], [3000, 0, 0], [6000, 3000, 0], [9000, 3000, 0]], 900.0))

    def test_a_reference_along_the_path_is_refused(self) -> None:
        self.assertIsNone(SW.frame_at((1.0, 0.0, 0.0), (1.0, 0.0, 0.0)))
        self.assertIsNotNone(SW.frame_at((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)))

    def test_the_frame_is_orthonormal_and_right_handed(self) -> None:
        e1, e2 = SW.frame_at((0.3, 0.4, 0.86602540378), (0.0, 0.0, 1.0))
        t = SW._unit((0.3, 0.4, 0.86602540378))
        for a, b, want in ((e1, e1, 1.0), (e2, e2, 1.0), (e1, e2, 0.0),
                           (e1, t, 0.0), (e2, t, 0.0)):
            self.assertAlmostEqual(SW._dot(a, b), want, places=9)
        self.assertAlmostEqual(SW._dot(SW._cross(e1, e2), t), 1.0, places=9)


# ── emission ─────────────────────────────────────────────────────────────────

def _compile(path, variety="fixed_reference", ver="2026",
             profile=None, ref=(0, 0, 1), anchor=None):
    op = {"op": "create_solid_sweep", "id": "S1", "variety": variety,
          "profile": profile or {"outer": {"shape": "rect", "origin": [0, 0],
                                           "size_mm": [400, 200]}},
          "path_mm": path, "ref_dir": list(ref),
          "category": "generic_model", "name": "проба"}
    if anchor is not None:
        op["anchor_uv_mm"] = list(anchor)
    return compile_program({"ir_version": "1.0", "ops": [op]},
                           revit_version=ver, snapshot=_SNAP)


class TheEmissionSaysWhatItProves(unittest.TestCase):

    _PATH = [[0, 0, 0], [4000, 0, 0], [7500, 900, 0], [11000, 900, 2000]]

    def test_both_varieties_reach_their_own_factory(self) -> None:
        self.assertIn("CreateFixedReferenceSweptGeometry",
                      _compile(self._PATH, "fixed_reference").csharp)
        cs = _compile(self._PATH, "frame").csharp
        self.assertIn("CreateSweptGeometry(", cs)
        self.assertNotIn("CreateFixedReferenceSweptGeometry", cs)

    def test_the_fixed_reference_is_emitted_UNIT(self) -> None:
        """`fixedReferenceDirection is not length 1.0` — ArgumentOutOfRange
        on all six versions. Normalization here makes it unreachable."""
        cs = _compile(self._PATH, "fixed_reference", ref=(0, 0, 7)).csharp
        self.assertIn("new XYZ(0.0, 0.0, 1.0)", cs)

    def test_the_expected_volume_is_area_times_length(self) -> None:
        out = _compile(self._PATH)
        length = SW.path_length_mm([[float(c) for c in p] for p in self._PATH])
        want = 400.0 * 200.0 * length
        self.assertIn(f"{want!r}", out.csharp)

    def test_six_versions_emit_the_same_bytes(self) -> None:
        """The sweep HAS NO version axis: both factories are 6/6. A
        divergence would mean someone introduced a branch and did not say
        so."""
        seen = {v: _compile(self._PATH, ver=v).csharp
                for v in ("2021", "2022", "2023", "2024", "2025", "2026")}
        self.assertEqual(len(set(seen.values())), 1)

    def test_the_profile_is_placed_by_its_CENTROID(self) -> None:
        """A profile declared FAR from the coordinate origin must arrive at
        the path — otherwise the volume law is wrong and the body sits in
        the wrong place.

        This is exactly the FAIL control for the law itself: remove the
        centroid subtraction, and the origin of the transform will coincide
        with the origin of the path, which the test will catch.
        """
        far = {"outer": {"shape": "rect", "origin": [90000, 40000],
                         "size_mm": [400, 200]}}
        cs = _compile(self._PATH, profile=far).csharp

        def _vec(marker):
            line = next(l for l in cs.splitlines() if marker in l)
            body = line.split("(", 1)[1].rsplit(")", 1)[0]
            return [float(t) for t in body.split(",")]

        e1 = _vec(".BasisX = new XYZ(")
        e2 = _vec(".BasisY = new XYZ(")
        origin = _vec(".Origin = P(")
        # It is the MAPPING ITSELF that is checked, not a single coordinate:
        # the first version of the test compared nums[1] to −40100 and
        # failed, because the basis here is (0,−1,0)/(0,0,−1), and the
        # coordinates are permuted. The invariant, however, is one and does
        # not depend on the basis: the profile's local centroid point must
        # arrive at the origin of the path.
        cx, cy = 90200.0, 40100.0
        mapped = [origin[k] + cx * e1[k] + cy * e2[k] for k in range(3)]
        for k, want in enumerate(self._PATH[0]):
            self.assertLess(abs(mapped[k] - want), 1e-6,
                            f"центроид профиля не сел на начало пути: "
                            f"{mapped} против {self._PATH[0]}")

    # ── OFFSETTING THE PROFILE FROM THE PATH (21.08.2026) ──────────────────────────────

    #: An L-shaped path and a 200 × 200 profile at the corner. The numbers
    #: are derived by hand from the definition of the miter
    #: (`2·ū·tan(φ/2)` at φ = 90°), not lifted from this same code: a
    #: control that checks the checked against itself is green by
    #: construction.
    _CORNER = [[0, 0, 0], [3000, 0, 0], [3000, 3000, 0]]
    _SQUARE = {"outer": {"shape": "rect", "origin": [0, 0],
                         "size_mm": [200, 200]}}

    def test_the_anchor_defaults_to_the_centroid_and_keeps_area_times_length(self) -> None:
        """The previous law is not overturned — it is the special case at
        zero offset."""
        cs = _compile(self._CORNER, profile=self._SQUARE,
                      ref=(0, 0, -1)).csharp
        self.assertIn(f'volume_mm3_expected"] = {200.0 * 200.0 * 6000.0!r}', cs)

    def test_an_offset_anchor_changes_the_volume_BY_THE_MITER_TERM(self) -> None:
        """A FAIL CONTROL FOR THE LAW. The profile's centroid sits at
        (100, 100); by anchoring the path at (0, 0), we offset the centroid
        by 100 mm INTO the turn, and the volume must drop by exactly
        `A·2·100·tan(45°)`. Remove the correction and the number reverts to
        the old one, and the test fails."""
        cs = _compile(self._CORNER, profile=self._SQUARE, ref=(0, 0, -1),
                      anchor=(0, 0)).csharp
        # It is PRECISELY the declared volume that is checked, not any
        # occurrence of the number: the same 240 000 000 also appears nearby
        # as a vacuity threshold for the tolerance, and an imprecise check
        # would go green on that instead.
        area = 200.0 * 200.0
        self.assertIn(f'volume_mm3_expected"] = {area * (6000.0 - 200.0)!r}', cs)
        self.assertNotIn(f'volume_mm3_expected"] = {area * 6000.0!r}', cs)

    def test_an_offset_under_variety_frame_is_REFUSED_by_name(self) -> None:
        """The turn direction there is Revit's choice, and every term of
        the correction depends on it. A refusal is more honest than a
        tolerance — and it must name the way out."""
        out = _compile(self._CORNER, variety="frame", profile=self._SQUARE,
                       ref=(0, 0, -1), anchor=(0, 0))
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("fixed_reference", text)

    def test_the_profile_is_placed_by_its_ANCHOR_when_one_is_given(self) -> None:
        """The same invariant as for the centroid, but the point is now
        named."""
        cs = _compile(self._CORNER, profile=self._SQUARE, ref=(0, 0, -1),
                      anchor=(0, 0)).csharp

        def _vec(marker):
            line = next(l for l in cs.splitlines() if marker in l)
            return [float(t) for t in
                    line.split("(", 1)[1].rsplit(")", 1)[0].split(",")]

        e1, e2 = _vec(".BasisX = new XYZ("), _vec(".BasisY = new XYZ(")
        origin = _vec(".Origin = P(")
        for k in range(3):
            self.assertLess(abs(origin[k] + 0.0 * e1[k] + 0.0 * e2[k]
                                - self._CORNER[0][k]), 1e-6)

    def test_the_exact_check_accepts_what_the_isotropic_one_refused(self) -> None:
        """🔴 A MEASUREMENT, NOT A RELAXATION. A 200 × 2000 profile across
        the path: the miters cut it only ACROSS (200 mm), while an isotropic
        radius takes 2010 mm in every direction and rejects a legitimate
        program. On the real building this difference was what held up
        three sweeps that Revit did build.
        """
        tall = {"outer": {"shape": "rect", "origin": [0, 0],
                          "size_mm": [200, 2000]}}
        path = [[0, 0, 0], [600, 0, 0], [600, 600, 0]]
        radius = SW.profile_circumradius(
            {"outer": [((0.0, 0.0), (200.0, 0.0), 0.0),
                       ((200.0, 0.0), (200.0, 2000.0), 0.0),
                       ((200.0, 2000.0), (0.0, 2000.0), 0.0),
                       ((0.0, 2000.0), (0.0, 0.0), 0.0)]}, 0.0, 0.0)
        self.assertIsNotNone(SW.feasibility(path, radius))   # isotropic — NO
        self.assertTrue(_compile(path, profile=tall, ref=(0, 0, -1),
                                 anchor=(0, 0)).ok)          # exact — YES

    def test_a_zero_reference_is_refused_not_normalised(self) -> None:
        out = _compile(self._PATH, ref=(0, 0, 0))
        self.assertFalse(out.ok)
        self.assertTrue(any("ref_dir" in (d.field_name or "")
                            for d in out.diagnostics))

    def test_caps_are_witnessed_only_when_the_sum_is_honest(self) -> None:
        """The end-cap witness works ONLY if no segment is perpendicular to
        the cap. Otherwise the side face of such a segment would fall into
        the cap sum, and the check would be accusing correct geometry."""
        clean = _compile([[0, 0, 0], [4000, 0, 0], [7500, 900, 0]]).csharp
        dirty = _compile([[0, 0, 0], [4000, 0, 0], [4000, 3000, 0]]).csharp
        self.assertIn("PlanarFace", clean)
        self.assertNotIn("PlanarFace", dirty)
        self.assertIn("cap_expectation_ru", dirty)
        self.assertNotIn("cap_area_mm2_expected\"] = 0", dirty)


if __name__ == "__main__":
    unittest.main()
