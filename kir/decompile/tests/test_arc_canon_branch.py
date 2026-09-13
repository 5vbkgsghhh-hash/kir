# -*- coding: utf-8 -*-
"""A REFUTING TEST: an arc wall does not survive the canon round trip.

The trigger — rebuild #11 (v18): create_wall expected 2346 / missing 244.
239 of the 244 are explained by refused chunks (238 — chunk 9, 1 —
solo-chunk 12). The remaining FIVE were built live and did not reconcile
in the canon; they are the ones listed as `extra_rebuilt`. All five are
ARCS, from four different committed chunks, four types, and four levels —
so this is not a property of a single element.

There are exactly two defects, both reproduced on synthetic data without
Revit:

  A. THE 2π BRANCH. `_FIDELITY_RADIAN_FIELDS` are quantized on a 1e-6
     grid but are not reduced modulo 2π. `rotation_deg` has such a
     reduction (`_canonical_rotation`, "360°≡0°"), radians do not. Live:
     expected start=3.4732052114687098, got -2.8099800957108703; the
     difference is exactly 1.0×2π. The same arc — a different hash.
     Affects 4 of 5.

  B. A STORED ENDPOINT AGAINST ITS OWN ARC. In the source sheet, `p0_mm`/
     `p1_mm` diverge from the point computed from that same sheet's `arc`
     by 0.37-0.94 mm. A rebuilt wall is built FROM the arc, and its
     endpoints match the arc to 0.0000 mm — measured across all five. The
     canon compares a redundant, inconsistent copy and catches a crossing
     of the CANON_MM=1 grid. Affects 2 of 5.

The fix was accepted by the lead on 29.07 (fidelity-canon/4): both
defective tests were converted from `expectedFailure` to ordinary ones —
they now guard the closed hole.
"""
from __future__ import annotations

import copy
import math
import unittest

from kir.decompile.fold import FidelityCanon

ORIGIN = (0.0, 0.0, 0.0)

# The arc of live wall 8146232 (v18), VERBATIM from idempotence_debug.json,
# trimmed to the fields that take part in the canon.
ARC_WALL = {
    "kind": "op",
    "_id": "arcwall",
    "op_name": "create_wall",
    "level_name": "L_02.1Кровля ДОО_+10.460",
    "params": {
        "arc": {
            "center_mm": [1503010.0, 24214.0, 9700.0],
            "curve_type": "Arc",
            "radius_mm": 3819.999999999997,
            "start_angle_rad": 3.4732052114687098,
            "end_angle_rad": 4.712388980384677,
            "x_axis": [0.9455185755993463, 0.3255681544570712, 0.0],
            "y_axis": [0.3255681544570712, -0.9455185755993463, 0.0],
        },
        "p0_mm": [1499190.0, 24214.0],
        "p1_mm": [1501766.0, 27825.0],
        "height_mm": 550.0000000000006,
        "base_offset_mm": 520.0,
        "level": {"by": "name", "value": "L_02.1Кровля ДОО_+10.460",
                  "_id": "7476592"},
        "type": {"by": "name", "value": "НР_НВФ", "_id": "8146075"},
    },
}
TWO_PI = 2.0 * math.pi


def arc_point(arc: dict, angle: float) -> list[float]:
    """A point on the arc, from its own parameters."""
    c, xa, ya, r = (arc["center_mm"], arc["x_axis"],
                    arc["y_axis"], arc["radius_mm"])
    return [c[0] + r * (math.cos(angle) * xa[0] + math.sin(angle) * ya[0]),
            c[1] + r * (math.cos(angle) * xa[1] + math.sin(angle) * ya[1])]


def shifted_branch(leaf: dict, turns: int = -1) -> dict:
    """The same sheet, whose angles are recorded on a different 2π
    branch.

    The sweep (end-start) is preserved bit-for-bit: BOTH angles are
    shifted by the same multiple. Geometrically this is the SAME arc —
    exactly how atan2 returns it when read back from Revit.
    """
    out = copy.deepcopy(leaf)
    arc = out["params"]["arc"]
    arc["start_angle_rad"] += turns * TWO_PI
    arc["end_angle_rad"] += turns * TWO_PI
    return out


def endpoints_from_arc(leaf: dict) -> dict:
    """The same sheet, whose p0/p1 are consistent with its own arc (as
    Revit builds it)."""
    out = copy.deepcopy(leaf)
    arc = out["params"]["arc"]
    out["params"]["p0_mm"] = arc_point(arc, arc["start_angle_rad"])
    out["params"]["p1_mm"] = arc_point(arc, arc["end_angle_rad"])
    return out


class ArcCanonRoundTrip(unittest.TestCase):

    def test_shifted_branch_is_the_same_arc(self):
        """Premise: a shift by 2π changes neither the sweep nor the
        points."""
        moved = shifted_branch(ARC_WALL)
        a, b = ARC_WALL["params"]["arc"], moved["params"]["arc"]
        self.assertAlmostEqual(b["end_angle_rad"] - b["start_angle_rad"],
                               a["end_angle_rad"] - a["start_angle_rad"],
                               places=12)
        for angle_key in ("start_angle_rad", "end_angle_rad"):
            self.assertLess(
                math.dist(arc_point(a, a[angle_key]),
                          arc_point(b, b[angle_key])), 1e-6)

    def test_stored_endpoints_disagree_with_their_own_arc(self):
        """Premise of defect B: the discrepancy is real and
        sub-millimeter.

        This is NOT the canon being fussy — it is a contradiction inside
        the sheet itself.
        """
        arc = ARC_WALL["params"]["arc"]
        drift = max(
            math.dist(arc_point(arc, arc["start_angle_rad"]),
                      ARC_WALL["params"]["p0_mm"]),
            math.dist(arc_point(arc, arc["end_angle_rad"]),
                      ARC_WALL["params"]["p1_mm"]))
        self.assertGreater(drift, 0.3)
        self.assertLess(drift, 1.0)

    def test_A_canon_collapses_the_2pi_branch(self):
        """DEFECT A. One arc on two 2π branches must yield ONE canon."""
        self.assertEqual(
            FidelityCanon.hash(ARC_WALL, ORIGIN),
            FidelityCanon.hash(shifted_branch(ARC_WALL), ORIGIN))

    def test_B_canon_reads_endpoints_from_the_arc(self):
        """DEFECT B. A sheet and its own source arc must yield ONE canon.

        On the left — how decompile stores it, on the right — how Revit
        would build it. The 0.37-0.94 mm discrepancy crosses the
        CANON_MM=1 grid and splits the hashes apart.
        """
        self.assertEqual(
            FidelityCanon.hash(ARC_WALL, ORIGIN),
            FidelityCanon.hash(endpoints_from_arc(ARC_WALL), ORIGIN))


if __name__ == "__main__":
    unittest.main()
