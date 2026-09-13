"""The `prism` source: a strip around the axis × [z0, z1], and why nobody
claims it today.

The builder is written, checked, and NOT WIRED IN — exactly like
`hull_from_wall_axis` before it. The difference is that this is no longer
"hands never got to it", but a MEASUREMENT: the sections wave gave a wall its
thickness from its type and checked the strip against 800 real walls of the
Snowdon building versus Revit's bounding boxes — 97 violations of the
conservatism law, up to 2854 mm outward
(`clash.tools.bundle_containment_gate`). The "zero violations" lock is not
open.

These tests hold three things: the builder is correct, a refusal is NAMED,
and no category in the table claims a source that nobody is accountable for.
"""
from __future__ import annotations

import unittest

from kir.clash import hulls as H


def _wall(prism=None, **extra):
    element = {"element_id": "w1", "category": "OST_Walls",
               "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [5000.0, 0.0, 0.0],
               "z0_mm": 0.0, "z1_mm": 3000.0}
    if prism is not None:
        element["prism"] = prism
    element.update(extra)
    return element


class ThePrismBuilderIsCorrect(unittest.TestCase):

    def test_a_full_set_builds_a_strip_of_half_the_width_on_each_side(self):
        """The offset is exactly zero: a live measurement from 2026-07-28
        (700+ real walls) — the body is SYMMETRIC around `LocationCurve` for
        any location-line ordinal."""
        record, why = H._prism_record(
            _wall({"width_mm": 200.0, "uniform": True}),
            dict(source_id="w1", category="OST_Walls", label="wall",
                 mvp_side="struct", level_id=None, type_name=None),
            (0.0, 3000.0))
        self.assertEqual(why, "")
        self.assertIsNotNone(record)
        lo, hi = record.hull.bounds()
        self.assertAlmostEqual(lo[1], -100.0)
        self.assertAlmostEqual(hi[1], 100.0)
        self.assertEqual((lo[2], hi[2]), (0.0, 3000.0))
        self.assertEqual(record.hull_source, "prism")
        self.assertEqual(record.grade, "conservative")

    def test_every_missing_input_is_a_named_refusal(self):
        common = dict(source_id="w1", category="OST_Walls", label="wall",
                      mvp_side="struct", level_id=None, type_name=None)
        cases = [
            (_wall({"uniform": True}), (0.0, 3000.0),
             "prism_incomplete_width_mm"),
            (_wall({"width_mm": 200.0, "uniform": False,
                    "blockers": ["wall_sweeps"]}), (0.0, 3000.0),
             "prism_blocked_wall_sweeps"),
            (_wall({"width_mm": 0.0, "uniform": True}), (0.0, 3000.0),
             "prism_width_invalid"),
            (_wall({"width_mm": 200.0, "uniform": True}), None,
             "prism_z_span_missing"),
        ]
        for element, span, expected in cases:
            with self.subTest(expected=expected):
                record, why = H._prism_record(element, dict(common), span)
                self.assertIsNone(record)
                self.assertEqual(why, expected)

    def test_a_zero_length_axis_refuses_instead_of_building_a_point(self):
        element = _wall({"width_mm": 200.0, "uniform": True})
        element["p1_mm"] = list(element["p0_mm"])
        record, why = H._prism_record(
            element, dict(source_id="w1", category="OST_Walls", label="wall",
                          mvp_side="struct", level_id=None, type_name=None),
            (0.0, 3000.0))
        self.assertIsNone(record)
        self.assertEqual(why, "prism_zero_length")

    def test_an_element_without_a_prism_key_says_nothing_at_all(self):
        """Neither a refusal nor a hull: an element that did not EVEN TRY is
        not obligated to explain itself — otherwise an L0 decompile would
        bury the census in reasons for something nobody asked it about."""
        record, why = H._prism_record(
            _wall(), dict(source_id="w1", category="OST_Walls", label="wall",
                          mvp_side="struct", level_id=None, type_name=None),
            (0.0, 3000.0))
        self.assertIsNone(record)
        self.assertEqual(why, "")


class TheSourceIsClaimedOnlyWhereNothingCanBeMeasured(unittest.TestCase):
    """On 2026-08-14 the strip was admitted — and admitted NARROWER than the
    table row reads.

    The previous ratchet here required something true: `prism` may only be
    claimed TOGETHER WITH a re-measurement of the containment gate. The gate
    has NOT been re-measured, and 97 violations out of 800 remain in force.
    What changed is different: those 800 are walls DECOMPILED from the
    model, which have a real bounding box, and the strip disagrees with it.
    A wall DECLARED by a program has no bounding box at all — there the
    choice is "the strip versus nothing", and the gate's lock says nothing
    about this case.

    So the admission rests on the DATA, not on intent, and these three tests
    hold both of its halves: where there is nothing to measure with — the
    strip; where there is something to measure with — the bounding box, as
    before.
    """

    def test_the_wall_is_the_only_category_claiming_the_prism(self):
        """The list of claimants is CLOSED. A new category with the strip
        must arrive with its own measurement, not inherit someone else's."""
        claimed = [category for category, rule in H.KIND_TABLE.items()
                   if "prism" in rule.sources]
        self.assertEqual(claimed, ["OST_Walls"])
        self.assertEqual(H.KIND_TABLE["OST_Walls"].sources, H.SOURCES_PRISM)

    def test_a_declared_wall_gets_the_band_instead_of_nothing(self):
        """A wall without a bounding box: before the fix — zero bodies,
        after — the strip.

        This is exactly the owner's case from 08-14: the program named a
        type, the thickness came from the snapshot, and the scene stayed
        empty.
        """
        record, refusal = H.build_hull(_wall({"width_mm": 200.0,
                                              "uniform": True}))
        self.assertIsNone(refusal)
        self.assertEqual(record.hull_source, "prism")
        self.assertEqual(record.grade, "conservative")

    def test_a_wall_with_a_prism_still_falls_back_to_the_box(self):
        """THE MAIN LOCK OF THIS FIX, and it has not shifted by a single
        byte: where a real body is measured, it remains a body. The
        containment lock is closed for this case, and the strip does not
        bypass it."""
        element = _wall({"width_mm": 200.0, "uniform": True})
        element["bbox_min_mm"] = [0.0, -500.0, 0.0]
        element["bbox_max_mm"] = [5000.0, 500.0, 3000.0]
        record, refusal = H.build_hull(element)
        self.assertIsNone(refusal)
        self.assertEqual(record.hull_source, "bbox")

    def test_the_corpus_shape_is_untouched_because_it_carries_no_prism(self):
        """THE RADIUS OF THE FIX, measured, not promised: a CORPUS element
        is a bounding box without the `prism` key, and it gets exactly what
        it got before."""
        element = _wall()
        element["bbox_min_mm"] = [0.0, -500.0, 0.0]
        element["bbox_max_mm"] = [5000.0, 500.0, 3000.0]
        record, refusal = H.build_hull(element)
        self.assertIsNone(refusal)
        self.assertEqual(record.hull_source, "bbox")
        self.assertEqual(record.grade, "coarse")


if __name__ == "__main__":
    unittest.main()
