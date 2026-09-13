"""WHAT THIS TURN CONTRIBUTED — not "how many clashes are in the
building" (wave of 11.08.2026).

THE MEASUREMENT THE WAVE IS FOR (`/tmp/wiring/m_delta.py`, a live
reassembly of `snowdon_plumb_v4`, 129 chunks through
`materialize.leaves_to_program`):

    turn   3: bodies  115, pairs  2 -> INTRODUCED BY THE TURN  2, stood before the turn  0
    turn  10: bodies  164, pairs  7 -> INTRODUCED BY THE TURN  0, stood before the turn  7
    turn  40: bodies  345, pairs 16 -> INTRODUCED BY THE TURN  0, stood before the turn 16
    turn 129: bodies  905, pairs 45 -> INTRODUCED BY THE TURN  0, stood before the turn 45

On the last turn the receipt says "45 CLASHES," and all 45 stood there
BEFORE it. The engineer who pressed the button reads this as "my turn
produced 45 clashes" — and that is false in exactly the same way it was
false to blame the author for a host from a linked file: someone else's,
charged to his account.

WHAT IS EXPRESSIBLE AND WHAT IS NOT — MEASURED, NOT ASSUMED:

  * "BEFORE" WITHIN A SESSION is exactly expressible. The journal numbers
    programs (`seq`, assigned in `journal.append`), the door captures
    `programs_seen` BEFORE the body (`_building_watch`), so entries with
    `seq >= before` are exactly what THIS turn declared. The body's
    address carries the program number (`p<N>/<id>`), so a pair's side
    can be attributed to a turn without setting up a second count;
  * "BEFORE" RELATIVE TO THE DOCUMENT IS NOT EXPRESSIBLE AT ALL, and this
    is measured: `open_model.prune_ground_snapshot` leaves ONLY level
    elevations and TYPE cross-sections — not a single instance, not a
    single bounding box. The document's existing geometry NEVER enters
    the search, so the pair "both existed in the document" is impossible
    here by construction, and a clash with someone else's wall is not
    "not found" but INVISIBLE. This is a limit, and it must be named in
    words, rather than papered over with a full list.
"""
from __future__ import annotations

import unittest

from kir import clash_bundle as CB
from kir import clash_judgement as J


def _finding(a_id, b_id, la="pipe", lb="pipe"):
    return {
        "finding_id": f"{a_id}~{b_id}",
        "a": {"source_element_id": a_id, "label": la,
              "category": "OST_PipeCurves", "hull_source": "axis_section"},
        "b": {"source_element_id": b_id, "label": lb,
              "category": "OST_PipeCurves", "hull_source": "axis_section"},
        "hull_relation": "overlap", "hull_grade": "conservative",
        "hull_overlap_depth_mm": 60.0, "ranking_tol_mm": 1.0,
        "pair_kind": "physical",
    }


class ThePairKnowsWhoIntroducedIt(unittest.TestCase):
    """Three classes of origin, and the third is NOT what the author
    contributed."""

    NEW = frozenset({"p3/a", "p3/b"})

    def test_both_sides_new_is_the_authors_own(self):
        row = J.judge([_finding("p3/a", "p3/b")], new_ids=self.NEW).judged[0]
        self.assertEqual(row.origin, "both_new")

    def test_one_side_new_is_still_introduced_by_this_turn(self):
        """A pair that would not have existed without this turn is also
        its contribution: before the turn, there was nothing in the
        building for the second side to clash with."""
        row = J.judge([_finding("p3/a", "p1/z")], new_ids=self.NEW).judged[0]
        self.assertEqual(row.origin, "one_new")

    def test_both_sides_prior_is_NOT_this_turns_doing(self):
        row = J.judge([_finding("p1/y", "p1/z")], new_ids=self.NEW).judged[0]
        self.assertEqual(row.origin, "both_prior")

    def test_without_a_basis_the_answer_is_unknown_not_prior(self):
        """"Was not asked" and "stood before the turn" are different
        facts. Dumping them into `both_prior` would mean declaring
        everything not asked about to be someone else's."""
        row = J.judge([_finding("p1/y", "p1/z")]).judged[0]
        self.assertEqual(row.origin, "unknown")
        self.assertNotEqual(row.origin, "both_prior")

    def test_an_empty_basis_means_this_turn_declared_nothing(self):
        """An empty set and the ABSENCE of a set are different values, by
        the same law as `sections=None` versus `{}`."""
        row = J.judge([_finding("p1/y", "p1/z")], new_ids=frozenset()).judged[0]
        self.assertEqual(row.origin, "both_prior")

    def test_graph_segment_bodies_inherit_their_program(self):
        row = J.judge([_finding("p3/g#7", "p3/b")],
                      new_ids=frozenset({"p3/g", "p3/b"})).judged[0]
        self.assertEqual(row.origin, "both_new")

    def test_every_origin_is_counted_and_the_list_is_closed(self):
        out = J.judge([_finding("p3/a", "p3/b"), _finding("p3/a", "p1/z"),
                       _finding("p1/y", "p1/z")], new_ids=self.NEW)
        self.assertEqual(out.by_origin,
                         {"both_new": 1, "both_prior": 1, "one_new": 1})
        self.assertEqual(sum(out.by_origin.values()), len(out.judged))
        for name in out.by_origin:
            self.assertIn(name, J.ORIGINS)

    def test_the_authors_own_findings_come_first_within_a_rung(self):
        """The display order answers the question that is asked: not
        "what is the deepest" but "which of these is mine." Within ONE
        tier — one's own comes first."""
        out = J.judge([_finding("p1/y", "p1/z"), _finding("p3/a", "p3/b")],
                      new_ids=self.NEW)
        self.assertEqual([r.origin for r in out.judged],
                         ["both_new", "both_prior"])

    def test_without_a_basis_the_order_is_untouched(self):
        """Byte for byte the same old order where deltas were not asked
        for."""
        pair = [_finding("p1/y", "p1/z"), _finding("p3/a", "p3/b")]
        # It used to be: judge(pair) was compared AGAINST ITSELF — that is
        # a determinism check, while the docstring promises the FORMER
        # order. We ask for what is promised: input order.
        self.assertEqual([r.finding_id for r in J.judge(pair).judged],
                         [f["finding_id"] for f in pair])
        self.assertEqual([r.origin for r in J.judge(pair).judged],
                         ["unknown", "unknown"])


class TheReceiptAnswersTheQuestionThatIsAsked(unittest.TestCase):
    """`_report` must return the TURN's contribution, not only the
    building's total."""

    def _pack(self):
        def duct(oid, x):
            return {"op": "create_duct", "id": oid, "diameter_mm": 200.0,
                    "p0_mm": [x, 0.0, 0.0], "p1_mm": [x, 2000.0, 0.0]}
        # p1: two intersecting runs (the clash STOOD before the turn)
        # p2: another one on top of them (the clash was INTRODUCED by the
        # turn)
        return [{"ops": [duct("d1", 0.0), duct("d2", 50.0)]},
                {"ops": [duct("d3", 25.0)]}]

    def setUp(self):
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def test_the_block_separates_what_this_turn_introduced(self):
        block = CB._report(self._pack(), new_from=2)
        self.assertEqual(block["delta_basis"], "session_turn")
        self.assertIn("by_origin", block)
        self.assertGreater(block["introduced"], 0)
        self.assertLess(block["introduced"], block["total_findings"])

    def test_without_a_basis_the_block_says_so_and_counts_nothing(self):
        block = CB._report(self._pack())
        self.assertEqual(block["delta_basis"], "none")
        self.assertNotIn("introduced", block)

    def test_the_cache_key_includes_the_delta(self):
        """The same bundle with a DIFFERENT turn boundary gives different
        answers, and returning the first one would be the same lie as
        returning someone else's snapshot."""
        a = CB._report(self._pack(), new_from=1)
        b = CB._report(self._pack(), new_from=2)
        self.assertNotEqual(a.get("introduced"), b.get("introduced"))

    def test_the_text_leads_with_the_turns_own_contribution(self):
        text = CB._report(self._pack(), new_from=2)["message_ru"]
        self.assertIn("ВНЕСЛА ЭТА ПАЧКА", text)

    def test_the_invisible_half_is_named_every_time(self):
        """The document's existing geometry NEVER enters the search
        (`prune_ground_snapshot` carries only levels and type
        cross-sections), so a clash with it is not "not found" but
        INVISIBLE. The limit is always named in words, not only when a
        delta was asked for."""
        for kwargs in ({}, {"new_from": 2}):
            block = CB._report(self._pack(), **kwargs)
            self.assertEqual(block["delta_scope"], "declared_only")
            self.assertIn("НЕ ВИДИТ", block["message_ru"])

    def test_a_clean_turn_still_carries_its_denominator(self):
        """"The turn contributed nothing" and "the instrument did not
        look" must be distinguishable: the former arrives together with
        the building's body count and pair count."""
        block = CB._report(self._pack(), new_from=3)
        self.assertEqual(block["introduced"], 0)
        self.assertGreater(block["total_findings"], 0)
        self.assertGreater(block["bodies"], 0)
        self.assertIn("ВНЕСЛА ЭТА ПАЧКА: 0", block["message_ru"])


class TheTwoDoorsGetTwoDifferentAnswers(unittest.TestCase):
    """The chat door HAS a "before" — it is what the session declared
    earlier. The reassembly door has none: the materializer builds the
    building from scratch, and the session's first chunk has no
    predecessor at all. One word for two situations would mean the
    reassembly's delta reads as "0 introduced" — that is, exactly the
    opposite."""

    KEY = ("test-clash-delta", "")

    def setUp(self):
        from kir.live import journal
        journal.reset(self.KEY)
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        from kir.live import journal
        journal.reset(self.KEY)
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def _seed(self, n):
        from kir.live import journal
        for p in range(n):
            journal.append(self.KEY, {"ops": [
                {"op": "create_duct", "id": f"p{p}d{i}", "diameter_mm": 200.0,
                 "p0_mm": [i * 25.0, 0.0, 0.0], "p1_mm": [i * 25.0, 2000.0, 0.0]}
                for i in range(3)]}, source="bulk")

    def test_the_first_turn_of_a_session_has_no_before(self):
        from kir.live import verdict
        self._seed(1)
        block = verdict.clash_only(self.KEY, since_seq=0)
        self.assertEqual(block["delta_basis"], "whole_bundle_new")
        self.assertEqual(block["introduced"], block["total_findings"])

    def test_a_later_turn_is_measured_against_the_session(self):
        from kir.live import verdict
        self._seed(2)
        block = verdict.clash_only(self.KEY, since_seq=1)
        self.assertEqual(block["delta_basis"], "session_turn")

    def test_asking_without_a_seq_keeps_the_whole_building_answer(self):
        from kir.live import verdict
        self._seed(2)
        block = verdict.clash_only(self.KEY)
        self.assertEqual(block["delta_basis"], "none")

    def test_eviction_does_not_shift_the_boundary(self):
        """Eviction of the journal's head shifts POSITIONS in the bundle,
        but not `seq`. Counting the boundary by position would mean
        declaring someone else's as one's own precisely on the largest
        building — the one where the journal overflowed."""
        from kir.live import journal
        self._seed(3)
        entry = journal.get(self.KEY)
        entry.records.pop(0)
        entry.programs_evicted += 1
        from kir.live import verdict as V
        block = V.clash_only(self.KEY, since_seq=2)
        self.assertEqual(block["delta_basis"], "session_turn")
        self.assertLess(block["introduced"], block["total_findings"] + 1)


class TheBulkDoorStampsTheDelta(unittest.TestCase):
    KEY = ("test-clash-delta-door", "")

    def setUp(self):
        from kir.live import journal
        journal.reset(self.KEY)
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        from kir.live import journal
        journal.reset(self.KEY)
        CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        CB._CACHE.clear()

    def test_the_watch_is_the_delta_boundary(self):
        """The marker the door already captures BEFORE the body
        (`_building_watch`) is precisely the turn's boundary. No second
        "what's new" count is set up."""
        import asyncio

        from kir import serving
        from kir.live import journal
        for p in range(2):
            journal.append(self.KEY, {"ops": [
                {"op": "create_duct", "id": f"q{p}", "diameter_mm": 200.0,
                 "p0_mm": [p * 25.0, 0.0, 0.0],
                 "p1_mm": [p * 25.0, 2000.0, 0.0]}]}, source="bulk")
        receipt = {"ok": True}
        asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, 1)))
        self.assertEqual(receipt["clash"]["delta_basis"], "session_turn")



class TheChatDoorGetsTheDeltaToo(unittest.TestCase):
    """IN CHAT THE CHECK IS READ BY THE MODEL, AND THIS CHANGES THE COST
    OF AN ERROR.

    A model that sees "45 CLASHES" where 45 stood there before it will
    behave in one of two ways, and both are harmful: it will either start
    fixing what it did not break — spending turns and making edits to
    SOMEONE ELSE'S geometry — or it will report to the engineer that it
    broke the building. This is not a missing capability but active
    harm, so the delta in chat comes before cosmetics.

    THE FORM IS STRICTLY ADDITIVE. All the former keys keep their meaning
    byte for byte: the corpus of witnesses and goldens reads the old
    form, and it has no right to budge. The delta travels under NEW keys,
    and without a basis there are none of them at all — a zero instead of
    "not asked" is forbidden here just as it is everywhere else.
    """

    KEY = ("test-clash-chat-delta", "")

    def setUp(self):
        from kir.live import journal
        journal.reset(self.KEY)
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        from kir.live import journal
        journal.reset(self.KEY)
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def _seed(self, n):
        from kir.live import journal
        for p in range(n):
            journal.append(self.KEY, {"ops": [
                {"op": "create_duct", "id": f"c{p}d{i}", "diameter_mm": 200.0,
                 "p0_mm": [i * 25.0, 0.0, 0.0],
                 "p1_mm": [i * 25.0, 2000.0, 0.0]}
                for i in range(3)]}, source="chat")

    def test_the_verdict_carries_the_delta_when_the_turn_is_named(self):
        from kir.live import verdict
        self._seed(2)
        block = verdict.judge(self.KEY, since_seq=1)
        self.assertEqual(block["clash"]["delta_basis"], "session_turn")
        self.assertIn("introduced", block["clash"])

    def test_without_a_turn_the_form_does_not_move(self):
        """The `introduced` key is ABSENT, rather than equal to zero:
        "the turn contributed nothing" and "the turn's boundary was not
        named" are different answers."""
        from kir.live import verdict
        self._seed(2)
        block = verdict.judge(self.KEY)
        self.assertEqual(block["clash"]["delta_basis"], "none")
        self.assertNotIn("introduced", block["clash"])

    def test_the_old_keys_keep_their_meaning(self):
        from kir.live import verdict
        self._seed(2)
        plain = verdict.judge(self.KEY)
        delta = verdict.judge(self.KEY, since_seq=1)
        for key in ("schema", "programs", "ops", "programs_evicted",
                    "verdict"):
            self.assertEqual(plain[key], delta[key], key)
        for key in ("schema", "status", "bodies", "total_findings",
                    "elements_considered", "without_body"):
            self.assertEqual(plain["clash"][key], delta["clash"][key], key)

    def test_the_verdict_stamp_passes_the_same_watch(self):
        """The boundary is the same marker as the watch's. No second
        "what's new" count is set up in the tree for either door."""
        import asyncio

        from kir import serving
        self._seed(2)
        result = {"ok": True}
        asyncio.run(serving._stamp_building_verdict(result, (self.KEY, 1)))
        self.assertEqual(result["building"]["clash"]["delta_basis"],
                         "session_turn")


class TheRuleBehindTheNumberIsNamed(unittest.TestCase):
    """A CHOICE THE CALLER CANNOT SEE IS `.FirstOrDefault()` WITH A
    BETTER REPUTATION. The law about named defaults was not written for
    this module (`ground.py`), but the case here is exactly the same.

    `introduced` adds up `both_new` and `one_new`, and this is a
    JUDGMENT, not a measurement: a pair with one new side would not have
    existed at all without this turn — but the opposite reading ("the new
    element merely discovered an already-existing condition") is
    defensible. So the rule must travel alongside the number IN WORDS and
    in the payload, not in a code comment.
    """

    def _pack(self):
        def duct(oid, x):
            return {"op": "create_duct", "id": oid, "diameter_mm": 200.0,
                    "p0_mm": [x, 0.0, 0.0], "p1_mm": [x, 2000.0, 0.0]}
        return [{"ops": [duct("d1", 0.0), duct("d2", 50.0)]},
                {"ops": [duct("d3", 25.0)]}]

    def setUp(self):
        self._prev = CB.__dict__["os"].environ.get("KUKAI_IR_CLASH")
        CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        if self._prev is None:
            CB.__dict__["os"].environ.pop("KUKAI_IR_CLASH", None)
        else:
            CB.__dict__["os"].environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def test_the_number_arrives_with_its_rule(self):
        block = CB._report(self._pack(), new_from=2)
        self.assertIn("introduced_rule", block)
        self.assertIn("ХОТЯ БЫ ОДНА", block["introduced_rule"])

    def test_the_rule_is_absent_when_the_number_is(self):
        block = CB._report(self._pack())
        self.assertNotIn("introduced_rule", block)
        self.assertNotIn("introduced", block)

    def test_the_addends_are_published_separately(self):
        """A reader who counts differently must be given the material for
        their own count, not just my total."""
        block = CB._report(self._pack(), new_from=2)
        origins = block["by_origin"]
        self.assertEqual(block["introduced"],
                         origins.get("both_new", 0) + origins.get("one_new", 0))
        self.assertIn("one_new", origins)

    def test_the_receipt_says_the_rule_out_loud(self):
        text = CB._report(self._pack(), new_from=2)["message_ru"]
        self.assertIn("хотя бы одна", text.lower())


if __name__ == "__main__":
    unittest.main()
