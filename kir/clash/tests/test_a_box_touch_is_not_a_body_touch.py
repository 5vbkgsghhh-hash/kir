"""HULL CONTACT IS NOT BODY CONTACT, AND THEIR DEPTH IS NOT PENETRATION (F-026 · F-027).

Two walls whose BOUNDING BOXES touch exactly, while their bodies may stand
half a meter apart, were producing, under `proven=None`, two POSITIVE
statements about the building: "in contact" and "nothing: structures are
supposed to touch." A neighboring layer on the same input was telling the
truth (`review.phrase`, the `hull_relation == "contact"` branch) — meaning
it was TWO OF OUR OWN layers that disagreed, not us and the model.

Along the same lines (F-027): the detector's `hull_overlap_depth_mm` was
being published in the judgement under the name `penetration_mm` —
"penetration," a fact about BODIES. This exact falsehood was already
removed in `detect` (review #6/#14, guard
`test_06b_penetration_field_is_named_hull_overlap_depth`) and came back
through a NEIGHBORING layer that guard cannot see. Here the guard watches
BOTH ends.

🔴 THE STAGE DOES NOT CHANGE AND MUST NOT CHANGE. The bounding box is
CONSERVATIVE: contact between boxes RULES OUT intersection of bodies, and
calling a human to look where a clash is knowably absent would cost them a
day. What was wrong was not the stage but two statements — and those are
what we fix.

🔴 THE SECOND OUTCOME IS TAKEN FROM THE LIVE PATH, NOT FROM A HELPER.
Alongside the changed adjacency, we run a collision, a pass-through of a
structure, a meeting of two runs, and a duplicate — all through
`detect.evaluate` -> `judge`, and all must stay BYTE-FOR-BYTE unchanged. A
check that reaches `_text` directly would prove that the function CAN, not
that the call REACHES it.
"""

from __future__ import annotations

import unittest

from kir import clash_judgement as J
from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H


def _plain(eid: str, hull: G.Hull, label: str, category: str, side: str,
           source: str) -> H.HullRecord:
    return H.HullRecord(source_id=eid, category=category, label=label,
                        mvp_side=side, hull=hull, grade="conservative",
                        hull_source=source, inner=None)


def _certified(eid: str, hull: G.Hull, label: str, category: str, side: str,
               source: str) -> H.HullRecord:
    evidence = H.certify_analytic_inner_for_test(
        inner=hull, body=hull, outer=hull, subject_source_id=eid,
        body_source_digest=H.analytic_hull_digest(hull),
        body_source_revision=f"fixture:{eid}:body-r1",
        revision="test-r1", error_bound_mm=0.0, tolerance_mm=0.0)
    return H.HullRecord(source_id=eid, category=category, label=label,
                        mvp_side=side, hull=hull, grade="conservative",
                        hull_source=source, inner=evidence)


def _judged(a: H.HullRecord, b: H.HullRecord) -> dict:
    """THE WHOLE PATH: hulls -> detector -> judgement. No helper called
    directly: otherwise what's proven is that it CAN, not that it is
    REACHED."""
    rows = J.judge([D.evaluate(a, b).as_dict()]).judged
    assert rows, "пара не дала суждения — стенд не туда"
    return rows[0].as_dict()


#: Contact of BOUNDING boxes: `proven=None`, there is no evidence about
#: bodies at all.
def _box_contact() -> dict:
    return _judged(
        _plain("w1", G.Aabb((0, 0, 0), (1000, 200, 3000)),
               "wall", "OST_Walls", "structure", "bbox"),
        _plain("w2", G.Aabb((1000, 0, 0), (2000, 200, 3000)),
               "wall", "OST_Walls", "structure", "bbox"))


#: Contact of CERTIFIED prisms: `proven=False`. A prism is no less
#: conservative than a box, and contact between prisms doesn't prove
#: contact between bodies either.
def _prism_contact() -> dict:
    return _judged(
        _certified("w1", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                   "wall", "OST_Walls", "structure", "prism"),
        _certified("w2", G.Aabb((1000, 0, 0), (2000, 200, 3000)),
                   "wall", "OST_Walls", "structure", "prism"))


class ПримыканиеНеРучаетсяЗаНеизмеренное(unittest.TestCase):

    def test_an_unproven_contact_says_it_is_about_hulls(self):
        for name, row in (("габариты", _box_contact()),
                          ("призмы", _prism_contact())):
            with self.subTest(name=name):
                self.assertEqual(row["rule_id"], "structure_contact")
                self.assertIsNot(row["proven"], True)
                self.assertIn("ОБОЛОЧКАМИ", row["text"])
                self.assertIn("касание тел не доказано", row["text"])

    def test_an_unproven_contact_does_not_vouch_for_the_joint(self):
        for name, row in (("габариты", _box_contact()),
                          ("призмы", _prism_contact())):
            with self.subTest(name=name):
                self.assertNotEqual(
                    row["next_move"], "ничего: конструкции обязаны касаться")
                self.assertIn("КАСАНИЕ ТЕЛ не доказано", row["next_move"])

    def test_the_rung_does_not_move(self):
        """🔴 The fix has no right to reach beyond its own subject. The box
        is conservative — contact between boxes RULES OUT intersection of
        bodies, and raising the stage would mean buying honest wording at
        the price of a false alarm."""
        for name, row in (("габариты", _box_contact()),
                          ("призмы", _prism_contact())):
            with self.subTest(name=name):
                self.assertEqual(row["rung"], "note")
                self.assertEqual(row["kind"], "adjacency")

    def test_a_proven_contact_keeps_the_old_words_byte_for_byte(self):
        """🔴 THE SECOND OUTCOME, AND ITS BOUNDARY IS NAMED HONESTLY.

        If contact between BODIES is proven, the earlier wording is
        correct and must stay. But the row for this case is assembled BY
        HAND, and here is why: today's detector does NOT produce such a
        row. `relation == "contact"` means zero overlap, while
        `verdict == "confirmed"` requires a certified INTERNAL OVERLAP —
        measured by exhaustive search; on contact the detector gives
        `possible`, and on overlap the rule already becomes
        `structure_meets_structure_overlap`.

        So the `proven is True` branch is defensive: it guards the law,
        not today's path. `judge()` accepts `clash-report/3` rows from any
        producer, so the law must be written down; but passing this case
        off as live would be exactly "proven that it CAN, not that it is
        REACHED."
        """
        overlapping = D.evaluate(
            _certified("w1", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "prism"),
            _certified("w2", G.Aabb((900, 0, 0), (2000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "prism")).as_dict()
        # Exactly what makes the case unreachable is what is done here by
        # hand.
        self.assertEqual(overlapping["hull_relation"], "overlap")
        self.assertEqual(overlapping["verdict"], "confirmed")
        row = dict(overlapping, hull_relation="contact",
                   hull_overlap_depth_mm=0.0)
        got = J.judge([row]).judged[0].as_dict()
        self.assertIs(got["proven"], True)
        self.assertEqual(got["rule_id"], "structure_contact")
        self.assertEqual(
            got["next_move"], "ничего: конструкции обязаны касаться")
        self.assertIn("соприкасаются; глубина", got["text"])
        self.assertNotIn("ОБОЛОЧКАМИ", got["text"])
        self.assertIs(got["depth_is_body_proven"], True)

    def test_other_kinds_are_not_rewritten(self):
        """🔴 THE SECOND OUTCOME FROM THE LIVE PATH. Without it, an edit
        that "always prints about hulls" would pass every check above.
        Every pair goes through `detect.evaluate`, not assembled by
        hand."""
        cases = {
            "столкновение": (
                _certified("w1", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                           "wall", "OST_Walls", "structure", "prism"),
                _certified("w2", G.Aabb((900, 0, 0), (2000, 200, 3000)),
                           "wall", "OST_Walls", "structure", "prism")),
            "проход сквозь конструкцию": (
                _plain("p1", G.Aabb((880, 0, 0), (2000, 100, 100)),
                       "pipe", "OST_PipeCurves", "mep", "bbox"),
                _plain("w3", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "bbox")),
            "встреча двух трасс": (
                _plain("p1", G.Aabb((0, 0, 0), (1000, 100, 100)),
                       "pipe", "OST_PipeCurves", "mep", "prism"),
                _plain("p2", G.Aabb((900, 0, 0), (2000, 100, 100)),
                       "pipe", "OST_PipeCurves", "mep", "prism")),
            "дубликат": (
                _plain("w1", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "prism"),
                _plain("w2", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "prism")),
        }
        for name, (a, b) in cases.items():
            with self.subTest(name=name):
                row = _judged(a, b)
                self.assertNotEqual(row["rule_id"], "structure_contact")
                self.assertNotIn("касание тел не доказано", row["text"])
                self.assertNotIn("ничего ПО КЛЕШУ", row["next_move"])


class ГлубинаОболочекНеНазываетсяПрониканием(unittest.TestCase):
    """F-027 — the same row, the other end."""

    def test_the_true_name_is_published(self):
        row = _box_contact()
        self.assertIn("hull_overlap_depth_mm", row)

    def test_the_alias_stays_and_never_drifts(self):
        """The alias `penetration_mm` is removed by the OWNER, not a
        smith: the key is already published. But two keys about the same
        value must be equal, or they drift apart silently — the way the
        two layers drifted apart."""
        for name, row in (("касание", _box_contact()),
                          ("проход", _judged(
                              _plain("p1", G.Aabb((880, 0, 0),
                                                  (2000, 100, 100)),
                                     "pipe", "OST_PipeCurves", "mep", "bbox"),
                              _plain("w3", G.Aabb((0, 0, 0),
                                                  (1000, 200, 3000)),
                                     "wall", "OST_Walls", "structure",
                                     "bbox")))):
            with self.subTest(name=name):
                self.assertEqual(row["penetration_mm"],
                                 row["hull_overlap_depth_mm"])

    def test_the_number_carries_what_it_means(self):
        """`proven` is three-valued and answers "is OVERLAP proven"; a
        reader of the NUMBER needs an answer to a different question —
        "can THIS NUMBER be read as penetration." Two questions, two
        fields."""
        unproven = _judged(
            _plain("p1", G.Aabb((880, 0, 0), (2000, 100, 100)),
                   "pipe", "OST_PipeCurves", "mep", "bbox"),
            _plain("w3", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                   "wall", "OST_Walls", "structure", "bbox"))
        self.assertIsNot(unproven["proven"], True)
        self.assertIs(unproven["depth_is_body_proven"], False)
        self.assertGreater(unproven["hull_overlap_depth_mm"], 0.0)

        proven = _judged(
            _certified("w1", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "prism"),
            _certified("w2", G.Aabb((900, 0, 0), (2000, 200, 3000)),
                       "wall", "OST_Walls", "structure", "prism"))
        self.assertIs(proven["proven"], True)
        self.assertIs(proven["depth_is_body_proven"], True)

    def test_the_row_says_what_each_hull_was_made_of(self):
        """`hull_grade` speaks to ACCURACY, but not to ORIGIN: there was
        NOTHING in the row to tell a Revit bounding box apart from a
        constructed prism. A tuple, not a single field: a pair can be
        mixed."""
        self.assertEqual(_box_contact()["hull_sources"], ["bbox", "bbox"])
        self.assertEqual(_prism_contact()["hull_sources"], ["prism", "prism"])
        mixed = _judged(
            _plain("p1", G.Aabb((880, 0, 0), (2000, 100, 100)),
                   "pipe", "OST_PipeCurves", "mep", "prism"),
            _plain("w3", G.Aabb((0, 0, 0), (1000, 200, 3000)),
                   "wall", "OST_Walls", "structure", "bbox"))
        self.assertEqual(mixed["hull_sources"], ["prism", "bbox"])


if __name__ == "__main__":
    unittest.main()
