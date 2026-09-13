"""THE MESH WITNESS'S EXPECTATION IS COMPUTED ALONG THE SAME ROAD REVIT
WILL COME BACK BY.

WHY THIS FILE EXISTS — A FALSE RED, CAUGHT LIVE ON 20.08.2026.

The director built an apple in an empty "Project1" (Revit 2026) — a
surface of revolution, 1190 vertices and 2376 triangles, computed by a
formula. Revit stitched it into a solid and did not lose A SINGLE face
(`read_back_solid_faces: 2376`). The surface witness, however, refused,
and the program rolled back:

    A1: built mesh surface differs from the authored surface on the canon grid

THE GEOMETRY WAS CORRECT. The witness failed on its own arithmetic — that
is, a FALSE RED, by this house's canon the most expensive outcome of all:
it does not stay silent, it confidently denies.

═══ THE MECHANISM, TWO LAYERS ═══════════════════════════════════════════

The first layer was closed earlier and sits nearby in
`_EMITTED_DECIMALS`: the expectation is computed not from the raw input
but from the PRINTED value, because it is exactly that value that goes
into Revit.

Nobody noticed the second layer: **Revit does not store what we
printed.** It holds mesh vertices in SINGLE precision, and on the way
back it returns a different number. Live measurement, three values out
of three, to the last digit:

    printed      Revit returned  float32(mm/ft)*ft
    40345.75     40345.751      40345.751294
    12345.75     12345.750      12345.749918
    40488.97     40488.970      40488.970459

The canon snaps a coordinate to a 0.5 mm grid by rounding HALF AWAY FROM
ZERO, while printing uses a 0.01 mm quantum — so a cell boundary (0.25 mm)
is reachable by a printed number EXACTLY. Python would round such a
coordinate up, while Revit, returning it a fraction of a micron lower,
forced C# to round it down.

Measurement on the apple: **27 vertices out of 1190**. On a pyramid's six
triangles this is not visible at all — the defect only surfaces with a
dense mesh, and a real shape turned out to be an instrument no test had
replaced.

═══ WHY "SHIFT THE GRID" DOESN'T WORK — REFUTED BY MEASUREMENT ═════════

The first thing that comes to mind (and what was proposed): make the
number of quanta per cell ODD, so a printed number never lands exactly on
a boundary by construction. On the apple, 37 m from the origin, this
gives zero — and that is the trap:

    discrepancies out of 1190     37 m     180 m
    today                          27       16
    odd grid 0.51                   0       12   ← only fixes things near zero
    storage model                   0        0

The odd grid's margin is half a quantum, 0.005 mm, while the single-
precision error GROWS WITH the coordinate's magnitude and reaches 0.008
mm at 180 m. Real sites of that size do occur. On top of that, the grid
itself is `GEOM_CANON_MM`, the FROZEN grid of the Tier-G content-
addressable store: changing it means devaluing the store.

So there is exactly one remedy: the expectation travels the SAME road as
the built result — printing, then single precision. Both sides of the
comparison are computed by one law, as the canon requires.

═══ THE BOUNDARY, NAMED HONESTLY ═══════════════════════════════════════

`_as_revit_stores` is a MODEL of someone else's storage, derived from
three live values, not a documented Autodesk contract. Here it is pinned
by those very three numbers. Should Revit ever start storing vertices
differently, a test will be the first to say so — not a false rollback on
the build.
"""
from __future__ import annotations

import math
import struct
import unittest

from kir.decompile.geometry_acceptance import _point_units
from kir.shape_emit import _EMITTED_DECIMALS, _as_revit_stores, _emitted_vertices

_FT = 304.8
_GRID = 0.5

#: Three "printed → Revit returned" pairs, taken LIVE on 20.08.2026 in
#: "Project1" (Revit 2026) by reading `Mesh.get_Triangle` off the built
#: element. The live response format is F3, so three decimal digits are
#: compared.
_LIVE_READBACK = (
    (40345.75, "40345.751"),
    (12345.75, "12345.750"),
    (40488.97, "40488.970"),
)


def _canon_unit_cs(mm: float, grid: float = _GRID) -> int:
    """The law of the C# helper `__KirCanonUnit`, word for word.

    Half AWAY FROM ZERO, not `round()`: banker's rounding would send
    exactly half of the boundary vertices into the neighboring cell. It is
    rewritten here DELIBERATELY, not called from `authoring`: the check
    must compare TWO INDEPENDENT implementations, otherwise it compares a
    function with itself.
    """
    scaled = mm / grid
    return (math.floor(scaled + 0.5) if scaled >= 0.0
            else math.ceil(scaled - 0.5))


def _revit_returns(mm_printed: float) -> float:
    """What Revit will give back after accepting the printed value: single precision, in FEET."""
    feet = mm_printed / _FT
    return struct.unpack("<f", struct.pack("<f", feet))[0] * _FT


def _apple(cx: float, cy: float, cz: float = 1000.0,
           nu: int = 44, nv: int = 28, r: float = 900.0) -> list:
    """The director's apple: a sphere with DENTED poles, computed by a
    formula.

    A dense organic mesh here is not for looks: it is exactly what
    exposes the defect, invisible on six triangles.
    """
    def profile(v: float) -> tuple[float, float]:
        top = 0.34 * math.exp(-(v / 0.42) ** 2)
        bottom = 0.16 * math.exp(-((math.pi - v) / 0.55) ** 2)
        radius = r * math.sin(v) * (1.0 + 0.10 * math.sin(2.0 * v))
        height = -r * math.cos(v) * (1.0 - top - bottom)
        return radius, height

    verts = [[cx, cy, cz + profile(0.0)[1]], [cx, cy, cz + profile(math.pi)[1]]]
    for j in range(1, nv):
        v = math.pi * j / nv
        radius, height = profile(v)
        for i in range(nu):
            u = 2.0 * math.pi * i / nu
            verts.append([cx + radius * math.cos(u),
                          cy + radius * math.sin(u), cz + height])
    return verts


def _disagreements(verts: list) -> int:
    """How many vertices the expectation and C# assign to DIFFERENT canon cells."""
    bad = 0
    for source, emitted in zip(verts, _emitted_vertices(verts)):
        expected = _point_units(tuple(emitted))
        built = tuple(_canon_unit_cs(_revit_returns(round(c, _EMITTED_DECIMALS)))
                      for c in source)
        if expected != built:
            bad += 1
    return bad


class TheStorageModelMatchesLiveRevit(unittest.TestCase):
    """The model was derived from a live measurement — here it is pinned by that very measurement."""

    def test_the_three_live_values_reproduce_to_the_digit(self) -> None:
        for printed, live_f3 in _LIVE_READBACK:
            with self.subTest(printed=printed):
                self.assertEqual(f"{_as_revit_stores(printed):.3f}", live_f3)

    def test_the_model_is_not_the_identity(self) -> None:
        """CONTROL: a model that changes nothing would pass everything
        above for free.

        Of the three live values, two come back DIFFERENT, and if
        `_as_revit_stores` were the identity, the check above would go
        green on two out of three — that is, it would barely
        discriminate.
        """
        changed = sum(1 for printed, _ in _LIVE_READBACK
                      if _as_revit_stores(printed) != printed)
        self.assertEqual(changed, 3, "модель обязана двигать все три значения")

    def test_double_precision_would_not_explain_the_live_answer(self) -> None:
        """A DISCRIMINATING EXPERIMENT: why SINGLE precision specifically.

        A round-trip conversion in double precision gives an error on the
        order of 1e-12 mm and would have printed `40345.750`. Revit
        answered `40345.751`. So the explanation is not unit conversion
        but storage width — and this is the only hypothesis that survived
        the live answer.
        """
        printed = 40345.75
        double_roundtrip = (printed / _FT) * _FT
        self.assertEqual(f"{double_roundtrip:.3f}", "40345.750")
        self.assertEqual(f"{_as_revit_stores(printed):.3f}", "40345.751")


class TheExpectationTravelsTheSameRoad(unittest.TestCase):
    """Both sides of the comparison must be computed by ONE law."""

    def test_the_apple_agrees_everywhere_it_was_built(self) -> None:
        self.assertEqual(_disagreements(_apple(37000.0, 12000.0)), 0)

    def test_it_agrees_far_from_the_origin_too(self) -> None:
        """🔴 THIS IS EXACTLY WHERE "SHIFT THE GRID" FALLS APART.

        The single-precision error grows with the coordinate's magnitude.
        An odd grid only holds up near zero (measurement: 0 discrepancies
        at 37 m and 12 at 180 m), and sites of that size are ordinary.
        """
        for cx, cy in ((180000.0, 150000.0), (400000.0, 300000.0)):
            with self.subTest(cx=cx):
                self.assertEqual(_disagreements(_apple(cx, cy)), 0)

    def test_a_coarse_mesh_was_never_broken_and_still_is_not(self) -> None:
        """NARROWNESS CONTROL: the pyramid passed BEFORE the fix and must
        pass after it.

        A fix that repairs the dense mesh at the price of the sparse one
        would be a trade-off, not a repair.
        """
        a, h = 4000.0, 3000.0
        pyramid = [[0.0, 0.0, 0.0], [a, 0.0, 0.0], [a, a, 0.0], [0.0, a, 0.0],
                   [a / 2, a / 2, h]]
        self.assertEqual(_disagreements(pyramid), 0)


class TheDefectIsReproducibleWithoutRevit(unittest.TestCase):
    """The defect must be caught OFFLINE, otherwise the next person will find it live all over again."""

    def test_the_unmodelled_expectation_disagrees_on_a_dense_mesh(self) -> None:
        """A FAIL control built into the test: compute the expectation
        the OLD way.

        This is not a mutation of production code but a direct
        reproduction of the earlier law ("expectation from the printed
        value, no storage model") on the same data. Should it ever prove
        sufficient again, the test will turn red and say that the storage
        model is no longer needed.
        """
        verts = _apple(37000.0, 12000.0)
        bad = 0
        for source in verts:
            printed = [round(c, _EMITTED_DECIMALS) for c in source]
            expected_old = _point_units(tuple(printed))          # THE PREVIOUS law
            built = tuple(_canon_unit_cs(_revit_returns(c)) for c in printed)
            if expected_old != built:
                bad += 1
        self.assertEqual(
            bad, 27,
            "прежний закон обязан расходиться ровно на 27 вершинах — это то "
            "число, которым дефект был измерен живьём")


if __name__ == "__main__":
    unittest.main()
