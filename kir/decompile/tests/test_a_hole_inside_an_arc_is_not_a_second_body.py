"""RING NESTING WAS COMPUTED BY CHORDS, AND A HOLE BECAME A SOLID (RV-15).

MEASUREMENT (04.09.2026), reproduced verbatim by this file:

    control: ring r=5000 clearly inside the r=10000 rhombus -> 1 solid, 1 hole (correct)
    trial:   ring r=9000 inside the r=10000 CIRCLE,
             its first vertex OUTSIDE the chord rhombus -> 2 solids, 0 holes (wrong)

`_group_rings` decides "ring inside another" by a single vertex, and
`_point_in_ring` computed the even/odd ray by VERTICES, i.e. by the CHORDS
of the arcs. A circle sampled as four quarters arrives as four vertices — a
rhombus — whose sagitta equals 29% of the radius. A ring lying in that gap
was declared NOT nested: a genuine HOLE became a SECOND SOLID, meaning
material landed exactly where the family has emptiness.

🔴 THE ARGUMENT BY WHICH THE BOUNDARY WAS DECLARED ACCEPTABLE IS REFUTED BY
THE MEASUREMENT. It stood in the docstring verbatim: "a discrepancy is only
possible for a point lying WITHIN THE SAGITTA of an arc from the boundary…
such a ring will be rejected by `validate_region` anyway." Both halves are
wrong: a circle's sagitta is not a small quantity, and the region in the
trial was built WITHOUT A SINGLE DIAGNOSTIC. The instrument was right about
a different subject — a polyline, not a ring with arcs.

HOW IT IS COMPUTED NOW. A rightward ray, even/odd, asked of the ACTUAL
boundary: a straight edge answers by the old rule `(y0 > y) != (y1 > y)`,
an arc by its own intersections. Chords play NO part in the count at all.
The arc, meanwhile, remains an ARC — none of them gets tessellated, which
is exactly what upholds this tree's second class ("an arc must not be
silently straightened into a chord").

🔴 WHY THERE ARE TWO FIX REVISIONS, AND WHAT THE FIRST ONE COST
(04.09.2026, the lead's analysis). The first computed "polygon by chords
XOR arc segments." The identity holds for interiors and is UNDEFINED ON
THE CHORD ITSELF: the point sits on the boundary of both terms at once.
For a circle built from two semicircles the chord IS the diameter, meaning
it was not the edge that lied but a segment running through the middle of
the solid; the grid found 15 such points. And the arrangement is not
contrived: for concentric circles sampled from the same starting angle,
the inner ring's vertex lands exactly on the outer one's diameter — and
nesting is tested precisely by the vertex — meaning RV-15 would survive
its own fix. The chord is an artifact of our counting method, and the cure
is removing the concept itself, not patching it.

🔴 WHAT WAS MISSING FROM THE FILE'S FIRST REVISION, AND THAT IS EXACTLY
WHAT LET IT SLIP THROUGH. All of its questions pointed in ONE direction —
"a point that must be INSIDE." Such a set is also passed by a predicate
that always answers `True`: the "ring clearly inside" control stays green
even with a broken predicate, because the answer there is `True` anyway.
So a control IN THE OPPOSITE DIRECTION is set up here — a 45° ray with
radii on both sides of 10,000, including a deliberately distant 50,000 —
checked against an EXACT circle by a grid, with a FAIL control on BOTH
prior revisions of the law.

🔴 A SECOND DEFECT, CAUGHT BY THE SAME MEASUREMENT AND INVISIBLE TO THE
EYE: the ends of an arc segment were recomputed from the angle
(`cy + R·sin`), which gives ±1e-9, so a vertex shared by two edges got a
DIFFERENT y at each. On a ray running exactly through that vertex, the
half-open rule diverged between neighbors, parity broke, and the CONTROL
case "ring r=5000 clearly inside r=10000" turned into "2 solids, 0 holes."
Endpoints are taken from the ring, not from arithmetic.

🔴 THE `bulge` UNIT IS PINNED DOWN RIGHT HERE, BECAUSE IT IS WHAT TRIPPED
THINGS UP. It is the DIMENSIONLESS `2s/c = tan(θ/4)`, not a sagitta in
millimeters: for a quarter circle with r=10000 the sagitta is 2929 mm,
while `bulge` is 0.414213562. A probe that fed millimeters in here
described an arc of radius 10,355,000 mm and got "the predicate lies at
any distance" — the instrument was right about a DIFFERENT arc. The value
is asked not of prose but of the PRODUCER (`_regions_from_loops`), and is
compared against both quantities at once.
"""
from __future__ import annotations

import math
import unittest

from kir.decompile import family_recipe as FR


def _poly(points, arcs=None) -> dict:
    shape = {"shape": "poly",
             "points_mm": [[round(x, 3), round(y, 3)] for x, y in points]}
    if arcs:
        shape["arcs"] = arcs
    return shape


def _circle(radius: float, *, quarters: int = 4, cx: float = 0.0,
            cy: float = 0.0, phase: float = 0.0) -> dict:
    """A circle in the exact shape `_regions_from_loops` builds it.

    The vertices lie on the circle itself, and each edge carries its own
    arc's sagitta (`bulge = tan(θ/4)`, positive counterclockwise — the sign
    is taken from `_bulge_from_midpoint`, not assigned).
    """
    step = 2.0 * math.pi / quarters
    points = [(cx + radius * math.cos(phase + step * i),
               cy + radius * math.sin(phase + step * i))
              for i in range(quarters)]
    bulge = math.tan(step / 4.0)
    arcs = [{"edge": i, "bulge": round(bulge, 9)} for i in range(quarters)]
    return _poly(points, arcs)


def _square(x0, y0, x1, y1) -> dict:
    return _poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _densify(points, arcs, per_arc: int = 120) -> list:
    """The same edges with DENSE vertices: a second, independent boundary
    law."""
    by_edge = {int(a["edge"]): float(a["bulge"]) for a in arcs}
    out: list = []
    count = len(points)
    for index in range(count):
        p0 = points[index]
        p1 = points[(index + 1) % count]
        out.append((float(p0[0]), float(p0[1])))
        bulge = by_edge.get(index)
        if not bulge:
            continue
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        chord = math.hypot(dx, dy)
        nx, ny = -dy / chord, dx / chord
        mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
        sagitta = bulge * chord / 2.0
        k = ((chord / 2.0) ** 2 - sagitta * sagitta) / (2.0 * sagitta)
        cx, cy = mx + nx * k, my + ny * k
        radius = abs(k + sagitta)
        start = math.atan2(p0[1] - cy, p0[0] - cx)
        sweep = 4.0 * math.atan(bulge)
        for step in range(1, per_arc):
            angle = start + sweep * step / per_arc
            out.append((cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle)))
    return out


def _in_polygon(point, ring) -> bool:
    """The even/odd ray over the READY-MADE polyline — the law being
    disputed."""
    inside = False
    count = len(ring)
    for index in range(count):
        x0, y0 = ring[index]
        x1, y1 = ring[(index + 1) % count]
        if (y0 > point[1]) != (y1 > point[1]):
            crossing = (x1 - x0) * (point[1] - y0) / ((y1 - y0) or 1e-12) + x0
            if point[0] < crossing:
                inside = not inside
    return inside

class ДыраВнутриОкружностиОстаётсяДырой(unittest.TestCase):
    """The CAPABILITY axis: what grouping is now able to see."""

    def test_the_measured_case_now_gives_one_body_with_one_hole(self):
        """The very trial from the measurement: ring r=9000 inside the
        r=10000 circle."""
        outer = _circle(10000.0)
        inner = _circle(9000.0, phase=math.pi / 4)   # first vertex OUTSIDE the rhombus
        groups, refusal = FR._group_rings([outer, inner])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 1, "дыра снова стала вторым телом")
        self.assertEqual(len(groups[0][1]), 1)
        self.assertEqual(groups[0][0]["points_mm"], outer["points_mm"],
                         "внешним обязана остаться ОКРУЖНОСТЬ")

    def test_the_order_of_the_rings_still_decides_nothing(self):
        outer = _circle(10000.0)
        inner = _circle(9000.0, phase=math.pi / 4)
        groups, _ = FR._group_rings([inner, outer])
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][1]), 1)

    def test_a_point_between_chord_and_arc_is_inside_the_ring(self):
        """The same law at a single point: (6364, 6364) inside the r=10000
        circle.

        The chord rhombus answers "outside" (|x|+|y| = 12728 > 10000), the
        circle answers "inside" (radius 9000 < 10000). The arc settles the
        dispute.
        """
        circle = _circle(10000.0)
        point = (9000.0 * math.cos(math.pi / 4), 9000.0 * math.sin(math.pi / 4))
        self.assertTrue(FR._point_in_ring(point, circle["points_mm"],
                                          circle["arcs"]))
        self.assertFalse(FR._point_in_ring(point, circle["points_mm"]),
                         "без дуг ответ обязан остаться прежним — иначе "
                         "прибор мерит не то, что назван мерить")

    def test_an_inward_bulge_removes_area_as_honestly_as_outward_adds_it(self):
        """An inward segment is SUBTRACTED: a point inside it is outside
        the ring.

        Without this, the "flip the answer" rule would read as "an arc
        always adds," and a concave ring would be counted as larger than
        itself.
        """
        # A square whose bottom edge bulges INWARD (bulge < 0 for a
        # counterclockwise traversal).
        ring = _poly([(0, 0), (1000, 0), (1000, 1000), (0, 1000)],
                     [{"edge": 0, "bulge": -0.5}])
        self.assertTrue(FR._point_in_ring((500.0, 500.0),
                                          ring["points_mm"], ring["arcs"]))
        self.assertFalse(
            FR._point_in_ring((500.0, 100.0), ring["points_mm"], ring["arcs"]),
            "точка в вогнутом сегменте обязана быть СНАРУЖИ кольца")
        self.assertTrue(FR._point_in_ring((500.0, 100.0), ring["points_mm"]),
                        "по хордам она внутри — на этом и стоял дефект")

    def test_a_circle_written_as_two_semicircles_is_still_a_circle(self):
        """Two semicircles yield a DEGENERATE polyline (two vertices).

        The chord test cannot answer "inside" for ANY point — a segment
        has no area. So without arcs such a ring held NO holes AT ALL, and
        this is a second, cruder form of the same defect.
        """
        circle = _circle(10000.0, quarters=2)
        self.assertEqual(len(circle["points_mm"]), 2)
        self.assertFalse(FR._point_in_ring((0.0, 5000.0),
                                           circle["points_mm"]))
        self.assertTrue(FR._point_in_ring((0.0, 5000.0), circle["points_mm"],
                                          circle["arcs"]))

    def test_the_DIAMETER_of_such_a_circle_is_inside_it(self):
        """🔴 AN ENTIRE SEGMENT IN THE MIDDLE OF THE SOLID ANSWERED "OUTSIDE"
        (04.09.2026).

        The first fix revision computed "polygon by chords XOR arc
        segments." On the chord itself this is undefined: the point sits
        on the boundary of both terms at once. For a circle made of two
        semicircles the chord IS the DIAMETER — meaning it was not the edge
        that lied but a segment running through the middle of the solid;
        the grid found 15 such points.

        The chord is an artifact of our counting method, not the ring's
        edge, so it no longer takes part in the count at all: the ray is
        asked of arcs and straight edges.
        """
        circle = _circle(10000.0, quarters=2)
        for x in (-9000.0, -5000.0, 0.0, 5000.0, 9000.0):
            with self.subTest(x=x):
                self.assertTrue(
                    FR._point_in_ring((x, 0.0), circle["points_mm"],
                                      circle["arcs"]),
                    "точка на диаметре обязана быть ВНУТРИ круга")
        for x in (-11000.0, 11000.0):
            with self.subTest(x=x):
                self.assertFalse(
                    FR._point_in_ring((x, 0.0), circle["points_mm"],
                                      circle["arcs"]))

    def test_concentric_circles_from_the_SAME_start_angle_still_nest(self):
        """The genuine arrangement that the first revision broke.

        For two concentric circles sampled from the same starting angle,
        the inner ring's vertex lands EXACTLY ON THE DIAMETER of the outer
        one — and nesting is tested precisely by the vertex. The hole would
        again become a second solid, meaning RV-15 would survive its own
        fix.
        """
        for quarters in (2, 4):
            with self.subTest(дуг=quarters):
                outer = _circle(10000.0, quarters=quarters)
                inner = _circle(5000.0, quarters=quarters)
                self.assertEqual(inner["points_mm"][0][1], 0.0,
                                 "фикстура обязана ставить вершину на ось")
                groups, refusal = FR._group_rings([outer, inner])
                self.assertIsNone(refusal)
                self.assertEqual(len(groups), 1)
                self.assertEqual(len(groups[0][1]), 1)


class ЧестныеКольцаНеПострадали(unittest.TestCase):
    """CONTROL: the fix must not move what was already correct.

    Every answer here was MEASURED BEFORE the fix and equals the same
    value after it.
    """

    def test_the_control_of_the_measurement_is_unchanged(self):
        groups, refusal = FR._group_rings([_circle(10000.0), _circle(5000.0)])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][1]), 1)

    def test_two_disjoint_circles_are_still_two_bodies(self):
        groups, refusal = FR._group_rings(
            [_circle(1000.0), _circle(1000.0, cx=5000.0)])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 2)
        self.assertEqual([len(holes) for _outer, holes in groups], [0, 0])

    def test_rings_without_arcs_answer_exactly_as_before(self):
        groups, refusal = FR._group_rings(
            [_square(0, 0, 100, 100), _square(20, 20, 80, 80)])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][1]), 1)

    def test_an_island_inside_a_hole_is_still_the_named_refusal(self):
        groups, refusal = FR._group_rings(
            [_square(0, 0, 100, 100), _square(20, 20, 80, 80),
             _square(40, 40, 60, 60)])
        self.assertIsNone(groups)
        self.assertIs(refusal.code, FR.RecipeRefusal.PROFILE_RINGS_NOT_A_REGION)


class ТочкаСНАРУЖИОстаётсяСНАРУЖИ(unittest.TestCase):
    """🔴 THE CONTROL IN THE OPPOSITE DIRECTION, without which the whole
    file is worth nothing.

    The lead's measurement of 04.09.2026 asked exactly this question: does
    the fix flip every point past the chord into "inside"? A 45° ray, and
    the truth is simple — inside if and only if the radius is less than
    10,000.
    """

    RADII_INSIDE = (100.0, 5000.0, 9000.0, 9999.0)
    RADII_OUTSIDE = (10001.0, 12000.0, 20000.0, 50000.0)

    def test_the_ray_at_45_degrees_answers_by_the_TRUE_circle(self):
        circle = _circle(10000.0)
        for radius in self.RADII_INSIDE + self.RADII_OUTSIDE:
            with self.subTest(r=radius):
                point = (radius * math.cos(math.pi / 4),
                         radius * math.sin(math.pi / 4))
                self.assertEqual(
                    FR._point_in_ring(point, circle["points_mm"],
                                      circle["arcs"]),
                    radius < 10000.0,
                    f"луч 45°, радиус {radius:g}")

    def test_a_point_just_outside_a_VERTEX_is_outside(self):
        """The vertex is the most dangerous spot: two segments meet
        there."""
        circle = _circle(10000.0)
        self.assertFalse(FR._point_in_ring((10000.0, 1.0),
                                           circle["points_mm"],
                                           circle["arcs"]))
        self.assertTrue(FR._point_in_ring((9998.0, 1.0),
                                          circle["points_mm"],
                                          circle["arcs"]))

    def test_a_ring_ENTIRELY_OUTSIDE_is_the_body_and_the_other_is_its_hole(self):
        """A concentric ring OUTSIDE: 1 solid and 1 hole, not 0 and 0.

        This is exactly where a broken predicate produces "circular
        containment" — each ring "contains" the other — and `_group_rings`
        refuses on legitimate geometry.
        """
        groups, refusal = FR._group_rings([_circle(10000.0), _circle(12000.0)])
        self.assertIsNone(refusal)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0][1]), 1)
        self.assertEqual(groups[0][0]["points_mm"],
                         _circle(12000.0)["points_mm"],
                         "внешним обязано стать БОЛЬШЕЕ кольцо")

    def test_the_four_cases_of_group_rings_together(self):
        """Four cases side by side: three with arcs and one WITHOUT them.

        The last one is the denominator: chords are honest where there are
        no arcs, and the fix has no right to move their answer.
        """
        def _bodies_holes(shapes):
            groups, refusal = FR._group_rings(shapes)
            self.assertIsNone(refusal)
            return len(groups), sum(len(holes) for _outer, holes in groups)

        self.assertEqual(_bodies_holes(
            [_circle(10000.0), _circle(9000.0, phase=math.pi / 4)]), (1, 1))
        self.assertEqual(_bodies_holes(
            [_circle(10000.0), _circle(5000.0)]), (1, 1))
        self.assertEqual(_bodies_holes(
            [_circle(10000.0), _circle(12000.0)]), (1, 1))
        self.assertEqual(_bodies_holes(
            [_poly([(10000.0 * math.cos(math.pi * i / 2),
                     10000.0 * math.sin(math.pi * i / 2)) for i in range(4)]),
             _poly([(12000.0 * math.cos(math.pi * i / 2),
                     12000.0 * math.sin(math.pi * i / 2)) for i in range(4)])]),
            (1, 1))


class ПредикатСверенСТОЧНОЙОКРУЖНОСТЬЮ(unittest.TestCase):
    """The NUMBER axis: not five hand-picked points, but a grid checked
    against the exact truth."""

    def test_a_grid_agrees_with_the_analytic_circle(self):
        for quarters in (2, 3, 4, 8):
            ring = _circle(10000.0, quarters=quarters)
            disagreements = boundary = 0
            for i in range(-23, 24):
                for j in range(-23, 24):
                    x, y = i * 1301.0, j * 1301.0
                    distance = math.hypot(x, y)
                    if abs(distance - 10000.0) < 1.0:
                        boundary += 1
                        continue
                    if FR._point_in_ring((x, y), ring["points_mm"],
                                         ring["arcs"]) != (distance < 10000.0):
                        disagreements += 1
            with self.subTest(дуг=quarters):
                self.assertEqual(disagreements, 0,
                                 f"дуг {quarters}, на границе пропущено "
                                 f"{boundary}")

    def test_a_MAJOR_arc_keeps_the_disk_minus_its_minor_segment(self):
        """A 270° arc: `bulge` is greater than one and NEGATIVE.

        🔴 THE SIGN IS TAKEN FROM THE PRODUCER, NOT FROM ME. The first
        revision of this check set `+tan(67.5°)` and declared the
        predicate broken on 1166 points. The bug was the FIXTURE:
        `(A, B, +2.414)` describes an arc on a circle centered at
        (10000, 10000), while the truth was computed for a circle around
        the origin — the expectation was computing a DIFFERENT LAW. For a
        clockwise arc `_bulge_from_midpoint` gives −2.414214, and on it
        there are zero discrepancies.
        """
        radius = 10000.0
        a, b = (radius, 0.0), (0.0, radius)
        bulge = -math.tan(math.radians(270.0) / 4.0)
        ring = {"points_mm": [list(a), list(b)],
                "arcs": [{"edge": 0, "bulge": bulge}]}
        dx, dy = b[0] - a[0], b[1] - a[1]
        chord = math.hypot(dx, dy)
        nx, ny = -dy / chord, dx / chord
        mx, my = (a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0
        centre_side = (0.0 - mx) * nx + (0.0 - my) * ny

        disagreements = 0
        for i in range(-14, 15):
            for j in range(-14, 15):
                x, y = i * 1301.0, j * 1301.0
                side = (x - mx) * nx + (y - my) * ny
                distance = math.hypot(x, y)
                if abs(distance - radius) < 5.0 or abs(side) < 5.0:
                    continue
                truth = distance < radius and side * centre_side > 0.0
                if FR._point_in_ring((x, y), ring["points_mm"],
                                     ring["arcs"]) != truth:
                    disagreements += 1
        self.assertEqual(disagreements, 0)

    def test_a_ring_of_lines_AND_arcs_agrees_with_a_dense_tessellation(self):
        """A mix of straight edges and arcs against a dense tessellation of
        THE SAME edges.

        Here the tessellation is a SECOND membership law (a ray over 960
        vertices), not a second copy of the first: the dispute is exactly
        about how "inside" is computed, and it is resolved by density, not
        by argument.
        """
        count = 8
        points = [[10000.0 * math.cos(2 * math.pi * i / count),
                   10000.0 * math.sin(2 * math.pi * i / count)]
                  for i in range(count)]
        arcs = [{"edge": i, "bulge": math.tan(math.radians(45.0) / 4.0)}
                for i in range(1, count, 2)]   # arcs on EVERY OTHER edge
        dense = _densify(points, arcs, per_arc=120)
        disagreements = 0
        for i in range(-7, 8):
            for j in range(-7, 8):
                point = (i * 1801.0, j * 1801.0)
                if FR._point_in_ring(point, points, arcs) != _in_polygon(
                        point, dense):
                    disagreements += 1
        self.assertEqual(disagreements, 0)


class ЕдиницаСтрелкиЗАКРЕПЛЕНА(unittest.TestCase):
    """`bulge` is dimensionless, and this is asked of the PRODUCER."""

    def test_the_producer_puts_a_DIMENSIONLESS_bulge_in_the_shape(self):
        radius = 10000.0
        corners = [(radius, 0.0, 0.0), (0.0, radius, 0.0),
                   (-radius, 0.0, 0.0), (0.0, -radius, 0.0)]
        loop = []
        for index in range(4):
            start, end = corners[index], corners[(index + 1) % 4]
            angle = math.atan2(start[1], start[0]) + math.pi / 4
            loop.append(("arc", start, end,
                         (radius * math.cos(angle), radius * math.sin(angle),
                          0.0)))
        plane = {"origin_mm": [0.0, 0.0, 0.0], "normal": [0.0, 0.0, 1.0],
                 "x_dir": [1.0, 0.0, 0.0]}
        regions, _lowered, refusal = FR._regions_from_loops(
            FR._project_loops((tuple(loop),), plane), "F1")
        self.assertIsNone(refusal)
        produced = regions[0]["outer"]["arcs"][0]["bulge"]
        self.assertAlmostEqual(produced, math.tan(math.pi / 8), places=9,
                               msg="производитель кладёт tan(θ/4)")
        sagitta_mm = radius * (1.0 - math.sqrt(2.0) / 2.0)
        self.assertNotAlmostEqual(
            produced, sagitta_mm, places=3,
            msg="стрелка в миллиметрах — ДРУГАЯ величина (2929 против 0.414)")


class КонтрольFailВДругуюСторону(unittest.TestCase):
    """🔴 TWO PRIOR REVISIONS OF THE LAW, AND BOTH MUST LOSE THE PROPERTY.

    Without this class, both of them would pass the file: all the
    questions in the first revision pointed toward "the point must be
    INSIDE," and such a set stays green even for a predicate that always
    answers `True`.
    """

    @staticmethod
    def _chord_xor_segments(point, points, arcs, *, check_radius=True):
        """The first fix revision, verbatim: chords XOR arc segments.

        `check_radius=False` is the same revision WITHOUT the "no farther
        than the arc" check — exactly the broken predicate the lead was
        wary of.
        """
        x, y = point
        inside = False
        count = len(points)
        for index in range(count):
            x1, y1 = points[index]
            x2, y2 = points[(index + 1) % count]
            if (y1 > y) != (y2 > y):
                denominator = (y2 - y1) or 1e-12
                if x < (x2 - x1) * (y - y1) / denominator + x1:
                    inside = not inside
        for arc in arcs:
            edge = int(arc["edge"])
            bulge = float(arc["bulge"])
            (ax, ay) = points[edge]
            (bx, by) = points[(edge + 1) % count]
            dx, dy = bx - ax, by - ay
            chord = math.hypot(dx, dy)
            if chord <= 0.0 or bulge == 0.0:
                continue
            nx, ny = -dy / chord, dx / chord
            mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
            sagitta = bulge * chord / 2.0
            side = (point[0] - mx) * nx + (point[1] - my) * ny
            if side * sagitta >= 0.0:
                continue
            if check_radius:
                k = ((chord / 2.0) ** 2 - sagitta * sagitta) / (2.0 * sagitta)
                cx, cy = mx + nx * k, my + ny * k
                if math.hypot(point[0] - cx,
                              point[1] - cy) > abs(k + sagitta):
                    continue
            inside = not inside
        return inside

    def test_the_chord_law_loses_the_whole_diameter(self):
        """The prior revision: a point on the diameter is declared
        OUTSIDE."""
        circle = _circle(10000.0, quarters=2)
        points, arcs = circle["points_mm"], circle["arcs"]
        self.assertFalse(self._chord_xor_segments((0.0, 0.0), points, arcs),
                         "прежний закон терял точку посреди тела")
        self.assertTrue(FR._point_in_ring((0.0, 0.0), points, arcs),
                        "нынешний обязан её удержать")

    def test_dropping_the_radius_turns_a_far_point_into_an_inside_one(self):
        """The revision without the radius check: the lie becomes
        UNBOUNDED."""
        circle = _circle(10000.0)
        points, arcs = circle["points_mm"], circle["arcs"]
        for radius in (10001.0, 12000.0, 20000.0, 50000.0):
            far = (radius * math.cos(math.pi / 4),
                   radius * math.sin(math.pi / 4))
            with self.subTest(r=radius):
                self.assertTrue(
                    self._chord_xor_segments(far, points, arcs,
                                             check_radius=False),
                    "сломанный закон обязан звать точку внутренней")
                self.assertFalse(FR._point_in_ring(far, points, arcs),
                                 "нынешний обязан ответить «снаружи»")


class КонтрольFail(unittest.TestCase):
    """FAIL control: bring back chord-based counting — the property must
    disappear.

    What is checked is the BEHAVIOR of the old law, not the source text.
    """

    def test_counting_by_chords_turns_the_hole_into_a_second_body(self):
        outer = _circle(10000.0)
        inner = _circle(9000.0, phase=math.pi / 4)
        chords_say = FR._point_in_ring(inner["points_mm"][0],
                                       outer["points_mm"])
        arcs_say = FR._point_in_ring(inner["points_mm"][0],
                                     outer["points_mm"], outer["arcs"])
        self.assertFalse(chords_say, "прежний закон: вершина ВНЕ ромба")
        self.assertTrue(arcs_say, "нынешний закон: вершина ВНУТРИ окружности")
        groups, _ = FR._group_rings([outer, inner])
        self.assertEqual(len(groups), 1)
        self.assertEqual(sum(len(holes) for _o, holes in groups), 1)


if __name__ == "__main__":
    unittest.main()
