"""WHAT TO DO: clearance proposals on screen.

MEASURED 11.08.2026, two buildings, two opposite profiles:

| | `sob62_fas_r23_v19` | `snowdon_plumb_v4` |
|---|---|---|
| overlaps | 19 239 | 35 633 |
| cost of ONE pair | 29.1 ms | 372.4 ms |
| whole building | 9.3 minutes | **3.7 hours** |
| recommendations | `review` 286, `assembly_relation` 114 | `move` 300 |
| minimality | `minimal_over_searched_directions` 100 % | `separating_only` 100 % |

The second row on minimality is the reason it travels with EVERY proposal:
on the engineering building, a move is never declared minimal EVEN ONCE, and
showing "move the pipe by 7.9 mm" without a caveat would mean passing off an
estimate as the optimum on 100 % of proposals.
"""

import unittest

from kir.viewer import advice as A


class TheFourPartsAllReachTheScreen(unittest.TestCase):
    """A number, a recommendation, minimality, certification. None reduces
    to another, and none can be dropped."""

    def test_a_proposal_carries_the_number(self):
        payload = _one_proposal()
        for field in ("distance_mm", "direction", "vector_mm", "element_id"):
            self.assertIn(field, payload["chosen"])

    def test_a_proposal_carries_the_recommendation_and_its_meaning(self):
        """Four DIFFERENT actions. Replacing them with one word means
        saying "move it" where the answer is "this is a junction, not a
        conflict"."""
        payload = _one_proposal()
        self.assertIn(payload["recommendation"],
                      {"move", "review", "verify_duplicate",
                       "assembly_relation"})
        self.assertTrue(payload["recommendation_note"])

    def test_a_proposal_carries_minimality_with_its_denominator(self):
        """`minimal_over_searched_directions` without the number of
        directions is a word with no number."""
        chosen = _one_proposal()["chosen"]
        self.assertIn(chosen["minimality"],
                      {"minimal_over_searched_directions", "separating_only"})
        self.assertTrue(chosen["minimality_note"])
        self.assertGreater(chosen["directions_searched"], 0)
        self.assertTrue(chosen["direction_basis"])

    def test_a_proposal_says_whether_it_was_verified(self):
        """An engineer being told to move a column has the right to know
        whether the proposal was checked by relocation."""
        self.assertIn("certified", _one_proposal()["chosen"])

    def test_minimality_is_a_separate_axis_from_certification(self):
        """"The move clears the conflict" and "the move is minimal" are
        different claims. Gluing them into one field would mean repeating a
        defect already removed."""
        from kir.clash import resolve as RS
        self.assertEqual(set(RS.MINIMALITY),
                         {"minimal_over_searched_directions",
                          "separating_only"})
        for value in RS.MINIMALITY:
            self.assertTrue(RS.MINIMALITY_NOTE[value])


class RefusalsAreTwoDifferentThings(unittest.TestCase):
    """`not_overlapping` — there is NO NEED to move anything, that is the
    answer. `no_certified_direction` — the pair intersects and we found no
    move; that is OUR failure. The first is green, the second is red."""

    def test_both_refusals_are_named_in_russian(self):
        for reason in ("not_overlapping", "no_certified_direction"):
            self.assertTrue(A.REFUSAL_RU[reason].strip())

    def test_only_the_first_is_benign(self):
        self.assertIn("not_overlapping", A.BENIGN_REFUSALS)
        self.assertNotIn("no_certified_direction", A.BENIGN_REFUSALS)

    def test_the_benign_set_is_a_closed_subset_of_the_named_reasons(self):
        """A new refusal not assigned to either side must be caught by a
        test, not go out to the screen as a neutral gray."""
        self.assertTrue(A.BENIGN_REFUSALS <= set(A.REFUSAL_RU))


class TheCostForcesAScope(unittest.TestCase):
    """19 239 × 29.1 ms = 9.3 minutes; 35 633 × 372.4 ms = 3.7 hours. This
    is not expensive for a frame — it is expensive for a single click."""

    def test_the_ceiling_is_computed_from_the_worst_price_not_the_average(self):
        """A TEST THAT REFUTES ITS OWN CAP. The first version computed it
        from the average cost (372.4 ms) and allowed 200 pairs. But the
        region is taken BY DEPTH, and deep pairs cost more: a sorted sample
        gave 977.1 ms — meaning 200 pairs would take 195 s, not 75."""
        self.assertLessEqual(A.DEFAULT_LIMIT, A.MAX_LIMIT)
        self.assertLessEqual(A.MAX_LIMIT * A.WORST_PAIR_MS / 1000.0,
                             A.PRESS_BUDGET_S + 1.0)
        self.assertGreaterEqual(A.WORST_PAIR_MS,
                                max(A.COST_PER_PAIR_MS.values()))

    def test_the_measured_price_is_published_not_remembered(self):
        self.assertIn("sob62_fas_r23_v19", A.COST_PER_PAIR_MS)
        self.assertIn("snowdon_plumb_v4", A.COST_PER_PAIR_MS)

    def test_truncation_is_named_by_number(self):
        """A list of fifty proposals and a list where fifty are out of
        nineteen thousand are different things, and the second, without
        this line, reads as the first."""
        advice = A.Advice(overlaps_total=19239, considered=50, truncated=19189)
        payload = advice.to_dict()
        self.assertEqual(payload["truncated"], 19189)
        self.assertIn("19189", payload["truncated_ru"])

    def test_nothing_truncated_says_nothing(self):
        payload = A.Advice(overlaps_total=3, considered=3).to_dict()
        self.assertEqual(payload["truncated_ru"], "")

    def test_the_scene_admits_it_did_not_compute_them(self):
        """The scene's silence would read as "there is nothing to clear"."""
        from kir.viewer.tests.test_reconcile import scene_without_requested_analyses
        response = scene_without_requested_analyses()
        self.assertIs(response["advice"]["available"], False)
        self.assertTrue(response["advice"]["reason"])
        self.assertEqual(response["advice"]["endpoint"], "/api/viewer/advice")

    def test_advice_is_never_called_from_a_scene_path(self):
        import inspect
        from kir.viewer import live_scene as L
        from kir.viewer import scene as S
        for module in (S, L):
            self.assertNotIn("advise_run", inspect.getsource(module))


class ItDoesNotRewriteTheOwnersWords(unittest.TestCase):

    def test_the_human_sentence_comes_from_resolve(self):
        """A wording of its own would drift apart from `to_russian` at the
        first verb refinement, and would drift apart silently."""
        import inspect
        self.assertIn("RS.to_russian", inspect.getsource(A.advise_run))

    def test_the_deepest_overlaps_are_taken_first(self):
        """If only part can be computed, the deepest part must be computed.
        Address order would pick the region alphabetically, that is, by
        nothing at all."""
        import inspect
        self.assertIn("hull_overlap_depth_mm", inspect.getsource(A.advise_run))


class TheUnavailableShapeIsComplete(unittest.TestCase):

    def test_it_publishes_every_key_a_consumer_reads(self):
        note = A.unavailable("нипочему")
        for key in ("available", "reason", "proposals", "considered",
                    "truncated"):
            self.assertIn(key, note)
        self.assertFalse(note["available"])


def _one_proposal():
    """One real proposal from a real building, the deepest one.

    TWO GAPS, NOT ONE, AND THAT IS THE POINT. "The corpus is unreachable"
    and "the corpus is in place, no proposals were built" are DIFFERENT
    facts, and before 11.08.2026 the first one arrived here as a
    `FileNotFoundError` from `advice.py:204`, meaning the absence of
    machine-local data read as a product breakage. The whole family was red
    in every worktree except prod, and the first person to work around it
    planted a private symlink.
    """
    from kir.viewer.scene import corpus_unreachable_reason
    why = corpus_unreachable_reason()
    if why:
        raise unittest.SkipTest(why)
    advice = A.advise_run("sob62_fas_r23_v19", limit=1)
    payload = advice.to_dict()
    if not payload["proposals"]:
        raise unittest.SkipTest("на этом корпусе предложений не построилось")
    return payload["proposals"][0]
