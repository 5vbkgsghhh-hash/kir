"""RING CANONICALIZATION MUST CARRY A SPLINE ALONG WITH ITS EDGE.

WHY THIS FILE EXISTS — A DORMANT DEFECT, FOUND 2026-08-20, AN HOUR
BEFORE IT WOULD HAVE WOKEN UP.

`fold._canonical_contour_ring` brings a ring to canonical form by
trying all rotations and a reflection, choosing the minimal key. Arcs
are recomputed in the process: `edge` gets a new index, `bulge` flips
sign on reflection. Splines were NOT recomputed, and did not enter the
key at all.

Two independent consequences, and each is enough to justify fixing this:

* the curve's points stayed at the OLD edge index, meaning the curve
  silently moved to the WRONG side of the contour — geometric
  distortion without a single failure;
* the rotation was chosen BLIND to the splines: the canonicalization
  key did not contain them.

🔴 AND THE SECOND CONSEQUENCE TURNED OUT NOT TO BE PROVEN — A CONTROL
SHOWED THIS, NOT AN ARGUMENT. The FAIL control "remove `splines` from
the key, keeping the index recomputation" did NOT TURN RED: six out of
six green. The reason is visible on inspection: the choice of rotation
is decided by the points, and in a legitimate ring the vertices are
pairwise distinct (a zero-length edge is already forbidden at parse
time), so two candidates with equal `points_mm` cannot occur by
construction. The field is LEFT in the key as a decision — the key must
describe the whole ring, otherwise the next kind of edge would inherit
the same blindness — but this cannot be passed off as a measured
necessity. What is recorded here is exactly what is proven: recomputing
`edge` is load-bearing (removing it turns three checks red), including
it in the key is not.

🔴 WHY THIS IS CALLED DORMANT, NOT MERELY FOUND. At the moment of
discovery the spline kind already existed in the language and in
emission, but no op let it through: the `KIR-E009` guard refused it at
grounding, so the spline never made it into the model or into the
decompiler. The defect would have woken up in the exact hour the first
op entered `contour.SPLINE_WITNESSED_OPS` — and it did enter THAT SAME
DAY. The order "witness first, inclusion later" saved us not by being
correct, but by giving time to look at the neighboring pipeline.

WHAT THIS MEANS FOR THE NEXT KIND OF SHAPE: when introducing a new kind
of edge, ask not only about emission and the witness, but about THREE
canonicalizations — `fold` (this one), `merkle` (the digest), and the
reverse pass. The forward pass and the canon live in different files,
and nothing forces them to agree.
"""
from __future__ import annotations

import json
import unittest

from kir.decompile.fold import _canonical_contour_ring

_SQUARE = [[0, 0], [30000, 0], [30000, 20000], [0, 20000]]
_VIA = [[10000, 3000], [20000, -3000]]


def _ring(rotation: int, extra: dict) -> dict:
    """The same ring, started from a different vertex: the canon must merge them."""
    pts = _SQUARE[rotation:] + _SQUARE[:rotation]
    return {"shape": "poly", "points_mm": [list(p) for p in pts], **extra}


#: The canon's origin. Zero is deliberate: canonicalization LOCALIZES
#: points relative to it, and a nonzero origin would shift ALL numbers
#: at once, distinguishing nothing — the check would become about
#: subtraction, not about rotation.
_ORIGIN = (0.0, 0.0, 0.0)


def _canon(ring: dict) -> dict:
    return _canonical_contour_ring(ring, _ORIGIN)


def _sig(ring: dict) -> str:
    return json.dumps({"points_mm": ring.get("points_mm"),
                       "arcs": ring.get("arcs"),
                       "splines": ring.get("splines")}, sort_keys=True)


class TheSplineTravelsWithItsEdge(unittest.TestCase):

    def test_the_same_ring_started_anywhere_canonicalises_the_same(self) -> None:
        """Rotation belongs to the record, not to the ring."""
        sigs = set()
        for rot in range(4):
            sigs.add(_sig(_canon(_ring(rot, {"splines": [
                {"edge": (0 - rot) % 4, "via_mm": _VIA}]}))))
        self.assertEqual(len(sigs), 1,
                         "четыре записи одного кольца дали разные каноны:\n"
                         + "\n".join(sorted(sigs)))

    def test_the_edge_index_is_RECOMPUTED_not_carried(self) -> None:
        """Direct evidence of the defect: the index must move together with the points."""
        rot2 = _canon(_ring(2, {"splines": [{"edge": 2, "via_mm": _VIA}]}))
        rot0 = _canon(_ring(0, {"splines": [{"edge": 0, "via_mm": _VIA}]}))
        self.assertEqual(_sig(rot0), _sig(rot2))

    def test_two_rings_differing_ONLY_by_which_edge_curves_stay_apart(self) -> None:
        """THE CONTROL WITHOUT WHICH THE FIRST TEST IS WORTHLESS.

        A canon that merges EVERYTHING passes a coincidence check
        trivially. Here the rings must remain DIFFERENT: a curve on the
        top side and a curve on the left side are two different buildings.
        """
        a = _sig(_canon(_ring(0, {"splines": [{"edge": 0, "via_mm": _VIA}]})))
        b = _sig(_canon(_ring(0, {"splines": [
            {"edge": 1, "via_mm": [[31000, 5000], [29000, 15000]]}]})))
        self.assertNotEqual(a, b,
                            "два разных кольца слились в один канонический ключ")

    def test_a_ring_without_splines_is_untouched(self) -> None:
        """A NARROWNESS CONTROL: the fix must not touch previous rings.

        The canonicalization key grew a field; if it appears on a ring
        WITHOUT splines, the canon would change for the whole corpus,
        and `merkle` would declare all previous decompiles different.
        """
        plain = _canon(_ring(0, {}))
        self.assertNotIn("splines", plain)
        with_arc = _canon(_ring(0, {"arcs": [{"edge": 0, "bulge": 0.3}]}))
        self.assertNotIn("splines", with_arc)

    def test_reflection_reverses_the_points_inside_the_edge(self) -> None:
        """Reflection also flips the ORDER of points within an edge.

        For an arc this is expressed by flipping the sign of `bulge`;
        a spline has no sign, so the list must be reversed. Forgetting
        this yields a mirrored curve with the same key — that is, two
        different buildings under one address.
        """
        forward = _canon(_ring(0, {"splines": [{"edge": 0, "via_mm": _VIA}]}))
        mirrored_pts = [list(p) for p in reversed(_SQUARE)]
        mirrored = _canon({"shape": "poly", "points_mm": mirrored_pts,
                           "splines": [{"edge": 2, "via_mm": list(reversed(_VIA))}]})
        self.assertEqual(_sig(forward), _sig(mirrored))

    def test_an_unrecognised_spline_shape_fails_OPEN(self) -> None:
        """An unfamiliar shape — the ring is returned UNTOUCHED, not corrupted.

        The same law that already holds for arcs: the canon has no
        right to improve an input it did not understand.
        """
        broken = _ring(0, {"splines": [{"edge": "нет", "via_mm": _VIA}]})
        self.assertEqual(_canon(broken), broken)


if __name__ == "__main__":
    unittest.main()


class КольцоЛокализуетСЯЦЕЛИКОМ(unittest.TestCase):
    """🔴 MEASUREMENT 2026-08-25: THE CANON CARRIED A SPLINE IN ABSOLUTE COORDINATES.

    `_canonical_contour_ring` subtracts the component's origin from
    `points_mm` (`localized`), but takes the spline's points RAW:

        edge_via[sp["edge"]] = [list(v) for v in sp["via_mm"]]   # no origin
        ...
        new_via = [[_round_mm(c) for c in v] for v in via]       # rounding only

    Running the same ring in place and shifted by (1000, 2000):

        canon in place   : [{"edge": 0, "via_mm": [[2000.0,  500.0]]}]
        canon shifted    : [{"edge": 0, "via_mm": [[3000.0, 2500.0]]}]

    The keys differ, so merkle will not merge two IDENTICAL apartments
    with a wavy floor edge standing in different places — even though
    that is the whole point of the canon's job. This is the third
    instance of one lesson in a single day: a quantity in millimeters
    that is not localized by everyone who is required to.

    AND THE SECOND ISSUE, IN THE SAME SPOT: three fail-open branches
    returned the INPUT dict (`return ring`), i.e. absolute, UNROUNDED
    points — even though the localized ring was computed one line above
    and then discarded. The neighboring `_canonical_ring` is built
    differently: its fail-open returns the ALREADY-localized value.
    There is no failure, no log, nothing to distinguish it from a
    normal pass — and any A5 run where such a ring occurred compares
    the incomparable.

    BOUNDARY. What is being judged here is LOCALIZATION. Canonicalizing
    an unrecognized shape (an arc with an extra key, an arc of
    impossible radius, a spline without `via_mm`) is still NOT done —
    this is a deliberate fail-open, and it stays. What changes is only
    that it no longer drops the coordinate system.
    """

    ТОЧКИ = [[0.0, 0.0], [4000.0, 0.0], [4000.0, 3000.0]]
    НАЧАЛО = [1000.0, 2000.0, 0.0]

    def _кольцо(self, **ещё):
        return {"shape": "poly", "points_mm": [list(p) for p in self.ТОЧКИ], **ещё}

    def test_сплайн_канонизируется_относительно_начала(self):
        на_месте = _canonical_contour_ring(
            self._кольцо(splines=[{"edge": 0, "via_mm": [[2000.0, 500.0]]}]),
            [0.0, 0.0, 0.0])
        сдвинутое = _canonical_contour_ring(
            {"shape": "poly",
             "points_mm": [[p[0] + 1000.0, p[1] + 2000.0] for p in self.ТОЧКИ],
             "splines": [{"edge": 0, "via_mm": [[3000.0, 2500.0]]}]},
            self.НАЧАЛО)
        self.assertEqual(
            на_месте, сдвинутое,
            "одно кольцо в двух местах дало два канона: merkle не склеит "
            "две одинаковые квартиры с волнистым краем пола")

    def test_КОНТРОЛЬ_разные_кольца_остаются_разными(self):
        """The instrument must also be able to TELL THINGS APART. A
        canon that merges everything indiscriminately is green by
        construction and useless."""
        а = _canonical_contour_ring(
            self._кольцо(splines=[{"edge": 0, "via_mm": [[2000.0, 500.0]]}]),
            [0.0, 0.0, 0.0])
        б = _canonical_contour_ring(
            self._кольцо(splines=[{"edge": 0, "via_mm": [[2000.0, 900.0]]}]),
            [0.0, 0.0, 0.0])
        self.assertNotEqual(а, б, "канон склеил кольца с РАЗНОЙ кривой")

    def test_fail_open_не_роняет_систему_координат(self):
        """Three shapes the canon does not recognize. It is not obliged
        to canonicalize them, but it has no right to return absolute coordinates."""
        неузнанные = {
            "дуга с лишним ключом":
                self._кольцо(arcs=[{"edge": 0, "bulge": 0.5, "weird": 1}]),
            "дуга невозможного радиуса":
                self._кольцо(arcs=[{"edge": 0, "radius_mm": 1.0, "dir": "ccw"}]),
            "сплайн без via_mm":
                self._кольцо(splines=[{"edge": 0}]),
        }
        for имя, кольцо in неузнанные.items():
            with self.subTest(форма=имя):
                вышло = _canonical_contour_ring(кольцо, self.НАЧАЛО)
                self.assertEqual(
                    вышло["points_mm"][0], [-1000.0, -2000.0],
                    f"{имя}: fail-open вернул СЫРЫЕ абсолютные точки "
                    f"{вышло['points_mm'][0]} вместо локализованных")

    def test_КОНТРОЛЬ_законная_форма_по_прежнему_канонизируется(self):
        """PASS control: fixing the fail-open must not have turned a
        recognized arc into an unrecognized one."""
        вышло = _canonical_contour_ring(
            self._кольцо(arcs=[{"edge": 0, "bulge": 0.5}]), self.НАЧАЛО)
        self.assertIn("arcs", вышло)
        self.assertIn("mid_mm", вышло["arcs"][0],
                      "законная дуга перестала опускаться в физическую "
                      "середину — канонизация сломана, а не fail-open")
