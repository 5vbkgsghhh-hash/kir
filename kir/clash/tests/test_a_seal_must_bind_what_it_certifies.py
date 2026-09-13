"""THE SEAL CERTIFIES ONE THING, AND THE REPORT PRINTS ANOTHER (F-258).

`evidence_state_of` was checking the seal's INTEGRITY and that it was
issued for THIS pair of identifiers. Nothing more. And the entire
product layer — severity, action, and the Russian sentence for the site
foreman — decides based on the finding's UNSIGNED fields
(`hull_relation`, `hull_overlap_depth_mm`). Those can be changed without
touching the seal: the signature check still returns `True`, the state
stays `confirmed`, and the foreman reads a lie UNDER THE MARK OF
CONFIRMATION.

The direction of harm is a MISSED CLASH: a certified 2mm intersection
was being printed as "Body contact confirmed; verify the joint,"
severity dropped `medium -> low`, action `repair -> verify`. Exactly the
outcome that ends up on the construction site.

🔴 COVERAGE IS MEASURED, AND IT IS ZERO ON TODAY'S LIVE PATH. This is
stated here, not hidden: 3,000 pairs through `detect.evaluate` gave
2,076 `confirmed` and ZERO discrepancies; an inner body not nested
inside the outer one cannot be certified
(`body_not_contained_in_outer`); the only live caller of `build_review`
feeds it a report obtained from `detect.detect` in the same process. So
the check guards a BOUNDARY — a corrupted artifact, a hand-assembled
row, someone else's pipeline — not today's stream. Its cost is exactly
zero: on a genuine finding the answer stays byte-for-byte unchanged,
and that is the first test below.
"""

from __future__ import annotations

import copy
import unittest

from kir.clash import detect as D
from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import review as R


def _record(eid, outer, *, evidence=None):
    return H.HullRecord(source_id=eid, category="OST_DuctCurves", label="duct",
                        mvp_side="mep", hull=outer, grade="conservative",
                        hull_source="analytic_outer", inner=evidence)


def _certified(eid, outer, inner, body=None, revision="r1"):
    body = inner if body is None else body
    evidence = H.certify_analytic_inner_for_test(
        inner=inner, body=body, outer=outer, subject_source_id=eid,
        body_source_digest=H.analytic_hull_digest(body),
        body_source_revision=f"fixture:{eid}:body-r1",
        revision=revision, error_bound_mm=0.0, tolerance_mm=0.0)
    return _record(eid, outer, evidence=evidence)


def _honest() -> dict:
    """A certified 2mm intersection of inner bodies. WHOLLY through the
    detector: not a single field by hand, otherwise what's proven is
    that the function CAN, not that the call REACHES it."""
    a = _certified("a", G.Aabb((0, 0, 0), (10, 10, 10)),
                   G.Aabb((2, 2, 2), (8, 8, 8)),
                   body=G.Aabb((1, 1, 1), (9, 9, 9)), revision="a-r1")
    b = _certified("b", G.Prism(((5, 0), (15, 0), (15, 10), (5, 10)), 0, 10),
                   G.Prism(((6, 2), (12, 2), (12, 8), (6, 8)), 2, 8),
                   body=G.Prism(((5.5, 1), (14, 1), (14, 9), (5.5, 9)), 1, 9),
                   revision="b-r1")
    return D.evaluate(a, b).as_dict()


def _report(finding: dict) -> dict:
    return {"schema_version": D.REPORT_SCHEMA, "findings": [finding],
            "census": {}, "origin": {}}


class ЧестнаяНаходкаНеТронута(unittest.TestCase):
    """🔴 THE SECOND OUTCOME, AND IT IS FIRST IN IMPORTANCE. Without it,
    an edit that "always possible" would pass every check below, and
    that is exactly what a green, worthless control looks like."""

    def test_a_finding_from_the_detector_keeps_every_verdict(self):
        finding = _honest()
        self.assertIsNone(R.proof_disagreement(finding))
        self.assertEqual(R.evidence_state_of(finding), "confirmed")
        self.assertEqual(R.impact_severity_of(finding), "medium")
        self.assertEqual(R.actionability_of(finding), ("repair", False))
        self.assertIn("Пересечение тел", R.phrase(finding))
        self.assertIn("требуется исправление", R.phrase(finding))

    def test_an_honest_report_counts_zero_disagreements(self):
        """Zero is a CHECKABLE statement that the pipeline is intact,
        not an absent field: the key must EXIST and must be zero."""
        summary = R.build_review(_report(_honest()))["summary"]
        self.assertIn("proof_disagreements", summary)
        self.assertEqual(summary["proof_disagreements"], 0)

    def test_the_detector_never_produces_a_disagreement(self):
        """COVERAGE, NOT A GUESS: the invariant is checked over a
        sample, not declared. Pairs are built by the detector, fields
        are not touched by hand."""
        import random
        rng = random.Random(20260830)
        confirmed = disagreed = 0
        for _ in range(300):
            ax, ay, az = (rng.uniform(-50, 50) for _ in range(3))
            aw, ah, ad = (rng.uniform(4, 40) for _ in range(3))
            a_outer = G.Aabb((ax, ay, az), (ax + aw, ay + ah, az + ad))
            m = rng.uniform(0.5, min(aw, ah, ad) / 2.5)
            a_inner = G.Aabb((ax + m, ay + m, az + m),
                             (ax + aw - m, ay + ah - m, az + ad - m))
            bx = ax + rng.uniform(-aw, aw)
            b_outer = G.Aabb((bx, ay, az), (bx + aw, ay + ah, az + ad))
            m2 = rng.uniform(0.5, min(aw, ah, ad) / 2.5)
            b_inner = G.Aabb((bx + m2, ay + m2, az + m2),
                             (bx + aw - m2, ay + ah - m2, az + ad - m2))
            try:
                a = _certified("a", a_outer, a_inner, revision="a-r1")
                b = _certified("b", b_outer, b_inner, revision="b-r1")
            except Exception:                     # a degenerate pair doesn't count
                continue
            finding = D.evaluate(a, b).as_dict()
            if finding["verdict"] != "confirmed":
                continue
            confirmed += 1
            if R.proof_disagreement(finding) is not None:
                disagreed += 1
        self.assertGreater(confirmed, 50, "выборка вырождена — стенд не туда")
        self.assertEqual(disagreed, 0,
                         f"детектор дал {disagreed} расхождений из {confirmed}")

    def test_a_nested_inner_is_the_law_upstream_too(self):
        """Why the invariant holds: an inner body's certificate is
        issued ONLY for a proven `Inner ⊆ Body ⊆ Outer`. The check on
        the reader's side does not invent the law, it re-verifies it."""
        with self.assertRaises(ValueError) as caught:
            H.certify_analytic_inner_for_test(
                inner=G.Aabb((-5, -5, -5), (20, 20, 20)),
                body=G.Aabb((-5, -5, -5), (20, 20, 20)),
                outer=G.Aabb((0, 0, 0), (10, 10, 10)),
                subject_source_id="x",
                body_source_digest=H.analytic_hull_digest(
                    G.Aabb((-5, -5, -5), (20, 20, 20))),
                body_source_revision="fixture:x:body-r1")
        self.assertIn("not_contained", str(caught.exception))


class ПодменённыеПоляНеПроходятПодЗнакомПодтверждения(unittest.TestCase):

    def test_a_swapped_relation_is_named_and_downgraded(self):
        finding = copy.deepcopy(_honest())
        finding["hull_relation"] = "contact"
        finding["hull_overlap_depth_mm"] = 0.0
        # The seal is still INTACT — that is the whole defect.
        self.assertTrue(D.verify_serialized_physical_overlap_proof(
            finding["physical_overlap_proof"], subject_a="a", subject_b="b"))
        self.assertEqual(R.evidence_state_of(finding), "possible")
        self.assertEqual(R.impact_severity_of(finding), "unknown")
        self.assertIn("hull_relation", R.proof_disagreement(finding))
        # 🔴 NOT `assertNotIn("confirmed", ...)`: the new sentence reads
        # "body contact is NOT confirmed," and the substring is right
        # there in it. A substring check would catch the LABEL instead
        # of the substance — the exact shape this tree has already been
        # caught by. We require the honest wording in full.
        self.assertIn("не подтверждён, требуется проверка", R.phrase(finding))
        self.assertNotIn("Контакт тел", R.phrase(finding))

    def test_a_swapped_depth_alone_is_caught_too(self):
        """THE SECOND HALF, and it does NOT follow from the first: the
        relation stayed `overlap`, only the depth was substituted."""
        finding = copy.deepcopy(_honest())
        finding["hull_overlap_depth_mm"] = 0.0
        self.assertEqual(R.evidence_state_of(finding), "possible")
        self.assertIn("меньше заверенной внутренней",
                      R.proof_disagreement(finding))

    def test_any_relation_but_overlap_is_refused(self):
        """A whitelist, not `== contact`: substitution can be to
        anything at all, and a blacklist has a hole by construction."""
        for relation in ("contact", "separated", "unknown", None):
            with self.subTest(relation=relation):
                finding = copy.deepcopy(_honest())
                finding["hull_relation"] = relation
                self.assertEqual(R.evidence_state_of(finding), "possible")
                self.assertIsNotNone(R.proof_disagreement(finding))

    def test_the_review_says_it_out_loud(self):
        """A downgrade without a NAMED reason would be a silent value of
        the very same kind as the defect itself: the finding would
        simply become "needs review"."""
        finding = copy.deepcopy(_honest())
        finding["hull_relation"] = "contact"
        review = R.build_review(_report(finding))
        self.assertEqual(review["summary"]["proof_disagreements"], 1)
        self.assertIsNotNone(review["top_findings"][0]["proof_disagreement"])
        self.assertIn("расходятся с заверенной печатью",
                      R.to_markdown(review))

    def test_a_finding_without_a_seal_is_untouched_by_this_law(self):
        """A finding WITHOUT a seal is sent to `possible` by the very
        first line of `evidence_state_of` and never reaches this check —
        the new function must stay silent about it, not invent a
        discrepancy."""
        finding = copy.deepcopy(_honest())
        finding.pop("physical_overlap_proof")
        self.assertIsNone(R.proof_disagreement(finding))
        self.assertEqual(R.evidence_state_of(finding), "possible")


if __name__ == "__main__":
    unittest.main()
