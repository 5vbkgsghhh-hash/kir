"""WHAT THE AUTHOR LACKS WITHOUT THE LIBRARIES — A MEASUREMENT, NOT A
TASTE (15.08.2026).

WHY THIS FILE EXISTS. The `ALLOWED_IMPORTS` list gets extended on a
feeling of "not enough math." The feeling was checked against three real
author tasks, and it turned out WRONG in two cases out of three:

    facade panelization along a polyline   30 lines on `math`   CORRECT
    columns on a non-orthogonal grid       68 lines on `math`   CORRECT
    hip roof on an L-shaped plan           78 lines on `math`   🔴 SILENTLY
                                                                    WRONG

The third is the entire subject of this file. The script ran GREEN,
printed "slopes built: 6 of 6" and "ridge vertices OUTSIDE the contour:
0," while the union of the built slopes covered 198 m² of a 288 m² plan
— **90 m², 31.25% of the roof, a hole nobody reported**. A naive
"skeleton" by edge offset does not converge at a concave angle, and
there is NOTHING IN `math` TO NOTICE THIS WITH: the discrepancy is
computed by a boolean operation over polygons, which is not on the
whitelist.

SO THE SHORTAGE IS NOT IN ARITHMETIC BUT IN CHECKING ONE'S OWN GEOMETRY.
Without the libraries, the author is not deprived of the ability to
COMPUTE — he is deprived of the ability to LEARN that he computed wrong.
This is exactly canon form 18: green with no act of distinction.

CONSEQUENCE FOR THE LIST: there is nothing left to extend it with.
`shapely` and `numpy` are already named in `GEOMETRY_IMPORTS`, and they
close the measured shortage completely (test below). None of the three
tasks required anything beyond that; adding `networkx`, which merely
happens to be installed, would mean extending by appetite, not by
measurement.

    venv/bin/python3.12 -m pytest \\
        kir/tests/test_author_libs_close_a_measured_gap.py -q

THE COST, MEASURED RIGHT HERE: warming up shapely+numpy costs ~4.0 s and
~17 MB on top of the baseline 0.4 s / 26 MB, and ONLY a script that names
the library pays it.
"""
from __future__ import annotations

import os
import unittest

from kir import sandbox

try:                                        # the test IS ALLOWED to work with polygons:
    from shapely.geometry import Polygon    # it is the AUTHOR who is restricted, not the checker
    from shapely.ops import unary_union
    _SHAPELY = True
except Exception:                           # noqa: BLE001
    _SHAPELY = False

#: An L-shaped plan: the concave angle is exactly the place where a
#: naive skeleton lies.
OUTLINE = [(0.0, 0.0), (24000.0, 0.0), (24000.0, 15000.0),
           (12000.0, 15000.0), (12000.0, 9000.0), (0.0, 9000.0)]
PLAN_M2 = 288.0

#: The roof done on `math`: offsetting edges inward and intersecting
#: neighbors. Exactly what an author with no boolean operations would
#: write. Prints success.
_ROOF_MATH = '''
import math
OUTLINE = [(0.0, 0.0), (24000.0, 0.0), (24000.0, 15000.0),
           (12000.0, 15000.0), (12000.0, 9000.0), (0.0, 9000.0)]
INSET = 3000.0
def _u(ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    n = math.hypot(dx, dy)
    return dx / n, dy / n
a2 = 0.0
for i in range(len(OUTLINE)):
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    a2 += x0 * y1 - x1 * y0
lines = []
for i in range(len(OUTLINE)):
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    ux, uy = _u(x0, y0, x1, y1)
    nx, ny = (-uy, ux) if a2 > 0 else (uy, -ux)
    px, py = x0 + nx * INSET, y0 + ny * INSET
    lines.append((uy, -ux, uy * px - ux * py))
ridge = []
for i in range(len(lines)):
    a1, b1, c1 = lines[i]
    a3, b3, c3 = lines[(i + 1) % len(lines)]
    det = a1 * b3 - a3 * b1
    ridge.append(None if abs(det) < 1e-9
                 else ((c1 * b3 - c3 * b1) / det, (a1 * c3 - a3 * c1) / det))
lvl = create_level(elev_mm=0, name="Кровля")
made = 0
for i in range(len(OUTLINE)):
    r0, r1 = ridge[(i - 1) % len(ridge)], ridge[i]
    if r0 is None or r1 is None:
        continue
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    create_roof(outline={"shape": "poly",
                         "points_mm": [[x0, y0], [x1, y1],
                                       [round(r1[0], 1), round(r1[1], 1)],
                                       [round(r0[0], 1), round(r0[1], 1)]]},
                level=lvl, type="Кровля 200")
    made += 1
print("скатов построено:", made, "из", len(OUTLINE))
'''

#: The same roof, but with the libraries available to the author. A
#: slope is a cell of the edge diagram; the discrepancy IS MEASURED and
#: printed — something `math` cannot do.
_ROOF_LIBS = '''
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import voronoi_diagram, unary_union
OUTLINE = [(0.0, 0.0), (24000.0, 0.0), (24000.0, 15000.0),
           (12000.0, 15000.0), (12000.0, 9000.0), (0.0, 9000.0)]
plan = Polygon(OUTLINE)
seeds, owner = [], []
for i in range(len(OUTLINE)):
    x0, y0 = OUTLINE[i]
    x1, y1 = OUTLINE[(i + 1) % len(OUTLINE)]
    n = max(2, int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 / 250.0))
    for k in range(n):
        t = (k + 0.5) / n
        seeds.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        owner.append(i)
cells = voronoi_diagram(MultiPoint(seeds), envelope=plan.buffer(5000.0))
by_edge = {}
for cell in cells.geoms:
    hit = None
    for idx, s in enumerate(seeds):
        if cell.covers(MultiPoint([s]).geoms[0]):
            hit = owner[idx]
            break
    if hit is None:
        continue
    part = cell.intersection(plan)
    if part.is_empty or part.area < 1.0:
        continue
    by_edge[hit] = unary_union([by_edge[hit], part]) if hit in by_edge else part
slopes = []
for i in sorted(by_edge):
    g = by_edge[i]
    g = max(g.geoms, key=lambda p: p.area) if g.geom_type == "MultiPolygon" else g
    slopes.append(g.simplify(1.0))
u = unary_union(slopes)
print("не покрыто м2:", round(plan.difference(u).area / 1e6, 2))
lvl = create_level(elev_mm=0, name="Кровля")
for g in slopes:
    create_roof(outline={"shape": "poly",
                         "points_mm": [[round(float(x), 1), round(float(y), 1)]
                                       for x, y in list(g.exterior.coords)[:-1]]},
                level=lvl, type="Кровля 200")
'''


def _uncovered_m2(ops) -> float:
    """How much of the plan is NOT covered by the built slopes, in m².
    Computed by the checker."""
    polys = [Polygon(o["outline"]["points_mm"])
             for o in ops if o.get("op") == "create_roof"]
    if not polys:
        return PLAN_M2
    return Polygon(OUTLINE).difference(unary_union(polys)).area / 1e6


class _Case(unittest.TestCase):
    """The toggle is ALWAYS cleared — the suite may run in any order."""

    def setUp(self) -> None:
        self._saved = os.environ.get(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG)
        os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(sandbox.AUTHOR_GEOMETRY_LIBS_FLAG, None)
        else:
            os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = self._saved

    def policy(self):
        """The policy is built by PROD'S OWN CODE.

        `SandboxPolicy(replay_check=True)` is NOT prod: its whitelist is
        frozen at the class default and it does not read the operator's
        toggle. It matches prod exactly when the flag is off, i.e. in
        half of this file's cases.
        """
        from kir import serving
        return serving._sandbox_policy()


@unittest.skipUnless(_SHAPELY, "shapely недоступен ПРОВЕРЯЮЩЕМУ — это отказ "
                               "прибора, а не сведение о списке импортов")
class TheDefaultSetCannotCheckItsOwnGeometry(_Case):
    """🔴 ON `math` ALONE THE TASK COMES OUT GREEN AND WRONG."""

    def test_the_math_roof_is_green(self) -> None:
        """The first half of the trouble: there IS NO refusal. The
        script is pleased with itself."""
        res = sandbox.execute_author_script(_ROOF_MATH, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        self.assertIn("скатов построено: 6 из 6", res.stdout)

    def test_and_it_leaves_a_hole_nobody_named(self) -> None:
        """The second half: 90 m² out of 288 are not covered, and the
        author never learned it.

        The number is not "approximate": the tolerance is 1 m² for
        coordinate rounding in the ops.
        """
        res = sandbox.execute_author_script(_ROOF_MATH, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        hole = _uncovered_m2(res.ops)
        self.assertAlmostEqual(hole, 90.0, delta=1.0,
                               msg=f"дыра в кровле изменилась: {hole:.2f} м²")

    def test_the_author_cannot_import_the_thing_that_would_show_it(self) -> None:
        """CONTROL FOR THE CAUSE: the hole is visible via a boolean
        operation, and it is not on the list."""
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertFalse(res.ok)
        self.assertEqual(res.refusal.code, "KIR-B004")


@unittest.skipUnless(_SHAPELY, "shapely недоступен ПРОВЕРЯЮЩЕМУ")
class TheLibrariesCloseExactlyThatGap(_Case):
    """With the flag on, the same task comes out CORRECT and reports the
    discrepancy."""

    def setUp(self) -> None:
        super().setUp()
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def test_the_same_roof_covers_the_plan(self) -> None:
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        hole = _uncovered_m2(res.ops)
        self.assertLess(hole, 1.0, f"скаты не накрыли план: {hole:.2f} м²")

    def test_the_script_says_the_residual_itself(self) -> None:
        """The author KNOWS his own discrepancy — that is exactly the
        closed shortage."""
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        self.assertIn("не покрыто м2: 0.0", res.stdout)


@unittest.skipUnless(_SHAPELY, "shapely недоступен ПРОВЕРЯЮЩЕМУ")
class TheMeasuringSideIsNotVacuous(_Case):
    """FAIL CONTROL for the instrument: it must be ABLE to say «there is
    a hole»."""

    def setUp(self) -> None:
        super().setUp()
        os.environ[sandbox.AUTHOR_GEOMETRY_LIBS_FLAG] = "1"

    def test_a_missing_slope_is_seen(self) -> None:
        res = sandbox.execute_author_script(_ROOF_LIBS, policy=self.policy())
        self.assertTrue(res.ok, res.refusal and res.refusal.render())
        roofs = [o for o in res.ops if o.get("op") == "create_roof"]
        self.assertGreaterEqual(len(roofs), 3, "нечего выбрасывать — контроль вырожден")
        cut = [o for o in res.ops
               if o.get("op") != "create_roof" or o is not roofs[0]]
        self.assertGreater(_uncovered_m2(cut), 1.0,
                           "прибор не заметил выброшенного ската — он вакуумен")


if __name__ == "__main__":
    unittest.main()
