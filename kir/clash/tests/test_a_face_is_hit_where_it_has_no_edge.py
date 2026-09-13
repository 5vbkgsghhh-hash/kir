"""BOTH BRANCHES OF `_seg_polygon_distance` STOOD WITHOUT A NUMBER WITNESS (E-55).

A continuation of E-54. That measurement broke the function AS A WHOLE and
gave "shield 67.1%, six reds." Too coarse: inside the function, BRANCHES
behave differently. Corruption by branch (30.08.2026, the whole `clash`
group) showed:

    branch                        reds   of them about THIS branch's NUMBER
    projecting the endpoint onto a face   2              0
    minimum over edges                    2              0
    kinks inside a segment                8              yes (dense_sampling)
    minimum over faces                    7              yes

For the first two, neither red is a witness: one sits in BASELINE §2.1 #1
and was already red BEFORE the corruption; the other is
`test_the_canonical_golden_does_not_move` (the golden is a BYTE SNAPSHOT,
not a statement about a number: it says "something shifted," and a D1
regeneration would clear this one too) or
`test_r3_the_missed_clash_is_actually_
found_now` (a test about a DIFFERENT subject).

🔴 THE HARM REACHES THE VERDICT, AND THIS IS MEASURED, NOT INFERRED. With
the projection branch stubbed out:

    pipe LIES on the slab       truth  0.0 `contact`   -> became +15.6 `separated`
    pipe PUSHED 3mm into slab   truth -3.0 `overlap`   -> became +15.1 `separated`
    pipe 10mm above the slab    truth 10.0 `separated` -> became +20.0 (same word)

A missed clash is the one that ends up on the construction site. The
direction of harm from this branch is always the same: the distance is
OVERSTATED, because without the projection, the nearest point is declared
to be the edge, and the edge is farther away.

WHY THE CORPUS DOESN'T CATCH THIS. `seg_prism_signed_distance` is called
only on a CAPSULE × PRISM pair, and the corpus gives few such pairs: of 68
decompiles, both a capsule AND a prism are present together in EIGHT, and
pairs within 2,000mm occur there — 83 of them, across five decompiles. The
witness needs to be a whole set — the corpus is weak here by construction.
"""

from __future__ import annotations

import math
import unittest

from kir.clash import detect as D
from kir.clash import geom as G


#: A 100×100×50 slab — the same shape as the floor slab in the decompile.
SLAB = G.Prism(((0., 0.), (100., 0.), (100., 100.), (0., 100.)), 0., 50.)

#: The slab's top face: it is what the projection branch resolves against.
TOP_FACE = ((0., 0., 50.), (100., 0., 50.), (100., 100., 50.), (0., 100., 50.))


def _edges_only(s0, s1, poly):
    """What the EDGES-ONLY branch alone would have answered. Needed to
    prove that the case is genuinely resolved by the OTHER branch, and
    isn't green by construction."""
    n = len(poly)
    return min(G.seg_seg_distance(s0, s1, poly[i], poly[(i + 1) % n])
               for i in range(n))


class ПерпендикулярПадаетВНУТРЬГрани(unittest.TestCase):
    """The "projecting the segment's endpoint onto the face plane"
    branch."""

    #: (name · segment · truth · what EDGES ALONE would have given)
    CASES = (
        ("над серединой грани", (50., 50., 80.), (50., 50., 120.), 30.0, 58.3095),
        ("над гранью, наклонный", (40., 40., 75.), (60., 60., 130.), 25.0, 47.1699),
    )

    def test_the_case_is_decided_by_this_branch(self):
        """🔴 FIRST IT IS PROVEN THAT THE CASE IS ON SUBJECT. The edges
        branch must give a DIFFERENT number: otherwise the check below is
        green by construction and guards thin air — exactly the pit that
        E-55 came from."""
        for name, s0, s1, exact, edges in self.CASES:
            with self.subTest(name=name):
                self.assertAlmostEqual(_edges_only(s0, s1, TOP_FACE), edges,
                                       places=3)
                self.assertGreater(edges - exact, 1.0,
                                   "рёбра и проекция совпали — случай не о том")

    def test_the_distance_is_the_perpendicular_not_the_edge(self):
        for name, s0, s1, exact, _edges in self.CASES:
            with self.subTest(name=name):
                self.assertAlmostEqual(
                    G._seg_polygon_distance(s0, s1, TOP_FACE), exact, places=4)
                self.assertAlmostEqual(
                    G.seg_prism_signed_distance(s0, s1, SLAB), exact, places=4)

    def test_a_pipe_lying_on_the_slab_is_a_contact_not_a_gap(self):
        """🔴 THE WHOLE PATH AND THE VERDICT, not a single helper number. A
        pipe of radius 5mm with its axis at 55mm TOUCHES a slab 50mm
        tall."""
        pipe = G.Capsule(((20., 50., 55.), (80., 50., 55.)), 5.0)
        distance = G.signed_distance(pipe, SLAB)
        self.assertAlmostEqual(distance, 0.0, places=6)
        self.assertEqual(D.relation_of(distance), "contact")

    def test_a_pipe_pressed_into_the_slab_is_an_overlap(self):
        """A genuine clash: axis at 52mm, radius 5 — the pipe is 3mm inside
        the slab's body. With the branch stubbed out, the tree answered
        `separated` at +15.1mm."""
        pipe = G.Capsule(((20., 50., 52.), (80., 50., 52.)), 5.0)
        distance = G.signed_distance(pipe, SLAB)
        self.assertAlmostEqual(distance, -3.0, places=6)
        self.assertEqual(D.relation_of(distance), "overlap")

    def test_a_pipe_above_the_slab_keeps_its_true_gap(self):
        """🔴 THE SECOND OUTCOME. A pair kept apart must stay apart AND
        keep its NUMBER: without this, an edit that "always declares
        contact" would pass both checks above."""
        pipe = G.Capsule(((20., 50., 65.), (80., 50., 65.)), 5.0)
        distance = G.signed_distance(pipe, SLAB)
        self.assertAlmostEqual(distance, 10.0, places=6)
        self.assertEqual(D.relation_of(distance), "separated")


class ПерпендикулярПадаетВНЕГрани(unittest.TestCase):
    """The "minimum over edges" branch. It resolves cases where the
    projection doesn't apply to any face: the segment stands at a CORNER
    of the prism."""

    def test_the_case_is_decided_by_this_branch(self):
        """🔴 ON SUBJECT: at the corner, no face accepts a perpendicular,
        and without edges there is NO ANSWER AT ALL — the function would
        return infinity. This is asserted here through GEOMETRY: the
        prism's point nearest to axis (130, 130) is its vertical edge
        (100, 100)."""
        s0, s1 = (130., 130., 5.), (130., 130., 25.)
        self.assertAlmostEqual(G.seg_prism_signed_distance(s0, s1, SLAB),
                               math.hypot(30.0, 30.0), places=4)

    def test_the_corner_gap_survives_the_whole_path(self):
        pipe = G.Capsule(((130., 130., 5.), (130., 130., 25.)), 2.0)
        distance = G.signed_distance(pipe, SLAB)
        self.assertAlmostEqual(distance, math.hypot(30.0, 30.0) - 2.0,
                               places=4)
        self.assertEqual(D.relation_of(distance), "separated")

    def test_a_side_face_still_answers_by_its_perpendicular(self):
        """🔴 THE SECOND OUTCOME for this branch. A segment PAST THE EDGE,
        but opposite a side face, must give exactly 50mm — a perpendicular
        to the face x = 100, not the distance to its edge. Without this
        pair, an edit that "counts only edges" would pass the checks
        above."""
        s0, s1 = (150., 50., 10.), (150., 50., 40.)
        self.assertAlmostEqual(G.seg_prism_signed_distance(s0, s1, SLAB),
                               50.0, places=6)
        self.assertAlmostEqual(_edges_only(s0, s1, TOP_FACE), 50.9902,
                               places=3)


if __name__ == "__main__":
    unittest.main()
