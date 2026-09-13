"""RING LIMITS: what they hold, what they cost, and why they were raised.

🔴 WHY THIS FILE (02.09.2026). `MAX_RING_POINTS` was raised from 64 to 256,
and `MAX_HOLE_RING_POINTS` from 32 to 128 — by a measurement of harm,
reproduced by the same instrument (`bounds_audit --measure`) on the same
three buildings: 67 of 652 outer rings rejected (worst case 130 points),
82 of 183 hole rings rejected (worst case 92).

Raising the limit is BEHAVIOR, not a constant, and what it was holding
back was not cost but the INVISIBILITY of the quadratic self-intersection
check: before the fix, ring emission grew as ~n^1.7, the exponent itself
was growing, and at 64 points this drowned in noise (2,016 pairs). So
THREE different claims are pinned here, and none follows from the other
two:

  §1 the boundary WORKS in both directions and the refusal names the
     MEASURED value (form 43);
  §2 bounding-box cutoff gives the same verdict as an all-pairs sweep —
     including the edge numbers in the refusal text;
  §3 the cost grows NO FASTER than linear with margin (a guard against
     quadratic behavior returning, not against slowness in general).
"""
from __future__ import annotations

import math
import os
import tempfile
import time
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import compile_program                       # noqa: E402
from kir import geom                                  # noqa: E402
from kir.geom import (MAX_HOLE_RING_POINTS, MAX_RING_POINTS,  # noqa: E402
                      _first_self_intersection, _seg_intersect)

_SNAP = {"levels": [{"id": 311, "name": "L01"}],
         "floor_types": [{"id": 900, "name": "Перекрытие 200"}]}


def _ring(n: int, r: float = 5000.0) -> list:
    return [[round(r * math.cos(2 * math.pi * i / n), 3),
             round(r * math.sin(2 * math.pi * i / n), 3)] for i in range(n)]


def _floor(outer, holes=None):
    contour = {"outer": {"shape": "poly", "points_mm": outer}}
    if holes:
        contour["holes"] = [{"shape": "poly", "points_mm": h} for h in holes]
    return {"ir_version": "1.0", "intent": "предел кольца", "ops": [{
        "op": "create_floor_by_contour", "id": "F1",
        "level": {"by": "name", "value": "L01"},
        "type": {"by": "name", "value": "Перекрытие 200"},
        "contour": contour}]}


def _brute(ring: list):
    """An ALL-PAIRS sweep is the reference standard the cutoff has no right to differ from."""
    n = len(ring)
    for a in range(n):
        for b in range(a + 2, n):
            if a == 0 and b == n - 1:
                continue
            if _seg_intersect(ring[a], ring[(a + 1) % n],
                              ring[b], ring[(b + 1) % n]):
                return (a, b)
    return None


class TheBoundaryWorksBothWays(unittest.TestCase):
    """§1. A limit that only rejects, and a limit that only lets through,
    are equally useless: they can only be told apart by a two-sided
    control."""

    def test_a_ring_at_the_limit_is_accepted(self) -> None:
        out = compile_program(_floor(_ring(MAX_RING_POINTS)),
                              revit_version="2026", snapshot=_SNAP, bulk=True)
        self.assertTrue(out.ok, [d.code for d in (out.diagnostics or [])])

    def test_a_ring_past_the_limit_refuses_and_names_the_measured(self) -> None:
        n = MAX_RING_POINTS + 1
        out = compile_program(_floor(_ring(n)), revit_version="2026",
                              snapshot=_SNAP, bulk=True)
        self.assertFalse(out.ok)
        d = out.diagnostics[0]
        # FORM 43: "X does not equal the expected Y" must print X. The
        # reader sees the expected value in the limit; no one but the
        # refusal sees the MEASURED one.
        self.assertEqual(d.got, n)
        self.assertIn(str(n), d.message_ru)
        self.assertIn(str(MAX_RING_POINTS), d.message_ru)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", d.message_ru)

    def test_a_hole_ring_at_the_limit_is_accepted(self) -> None:
        out = compile_program(
            _floor(_ring(8, r=20000.0), holes=[_ring(MAX_HOLE_RING_POINTS, r=2000.0)]),
            revit_version="2026", snapshot=_SNAP, bulk=True)
        self.assertTrue(out.ok, [d.code for d in (out.diagnostics or [])])


class ThePruningEqualsTheBruteForce(unittest.TestCase):
    """§2. Bounding-box cutoff is EXACT: if the boxes don't intersect, the
    segments don't intersect either. The claim is checked not by argument
    but by exhaustive search."""

    def test_same_verdict_and_same_edge_pair(self) -> None:
        import random
        rnd = random.Random(20260902)
        cases: list = []
        for n in (3, 4, 8, 16, 64, 128, 256):
            cases.append(_ring(n))                      # convex, no intersections
        for n in (5, 7, 9, 11):                          # stars: many intersections
            cases.append([[round(5000 * math.cos(4 * math.pi * i / n), 3),
                           round(5000 * math.sin(4 * math.pi * i / n), 3)]
                          for i in range(n)])
        for _ in range(600):                             # random
            n = rnd.randint(3, 40)
            cases.append([[round(rnd.uniform(-1000, 1000), 1),
                           round(rnd.uniform(-1000, 1000), 1)] for _ in range(n)])
        for _ in range(200):                             # a vertex TOUCHING an edge
            ring = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]
            ring.insert(rnd.randint(1, 3),
                        rnd.choice([[500.0, 0.0], [0.0, 500.0],
                                    [1000.0, 500.0], [500.0, 1000.0]]))
            cases.append(ring)
        for x in (200.0, 500.0, 800.0):                  # collinear overlap
            cases.append([[0.0, 0.0], [1000.0, 0.0], [x, 0.0],
                          [1000.0, 1000.0], [0.0, 1000.0]])
        hits = 0
        for ring in cases:
            expected = _brute(ring)
            hits += expected is not None
            with self.subTest(n=len(ring)):
                self.assertEqual(_first_self_intersection(ring), expected)
        # A degenerate sample is green by construction: if NO ring has any
        # intersections, the comparison distinguishes nothing.
        self.assertGreater(hits, 100, "выборка не содержит самопересечений")


class ThePriceDoesNotReturnToQuadratic(unittest.TestCase):
    """§3. A guard against the RETURN of quadratic behavior, not against
    slowness.

    What is pinned is a RATIO, not milliseconds: an absolute measure
    gauges the box and goes red from neighboring load (this tree has paid
    for a test like that before). The time ratio on doubling the number
    of points tends to 2 for a linear algorithm and to 4 for a quadratic
    one. A threshold of 3.0 separates the two with margin, even on a
    loaded machine, because it takes the MINIMUM over repeats: noise only
    ADDS time, so the minimum is closer to the true cost than the average.
    """

    def _min_ms(self, n: int, reps: int = 5) -> float:
        best = float("inf")
        for _ in range(reps):
            t0 = time.perf_counter()
            geom._first_self_intersection(_ring(n))
            best = min(best, (time.perf_counter() - t0) * 1000)
        return best

    def test_doubling_the_points_does_not_quadruple_the_time(self) -> None:
        self._min_ms(64)                                  # warm-up
        t128, t256 = self._min_ms(128), self._min_ms(256)
        self.assertLess(t256 / t128, 3.0,
                        f"проверка самопересечения вернулась к квадрату: "
                        f"128 -> {t128:.2f} мс, 256 -> {t256:.2f} мс, "
                        f"x{t256 / t128:.2f} за удвоение")


if __name__ == "__main__":
    unittest.main()
