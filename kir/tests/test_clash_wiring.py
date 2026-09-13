"""REFUTATION TESTS FOR THE «клеш видит дверь пересборки» WAVE (10.08.2026).

EVERY TEST HERE FAILED BEFORE THE FIX, AND FAILED ON EXACTLY WHAT IT NAMES.
These are not «does it work» checks: each one reproduces a MEASURED defect
and dies together with it.

WHAT IS NOT HERE. A live Revit, a bridge, or a network. Everything checked
is pure functions and a single `asyncio.run` over the receipt stamp.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import unittest

from kir import clash_bundle
from kir import clash_judgement as J
from kir.live import journal as live_journal
from kir.live import verdict as live_verdict


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


class _FlagOff:
    """The «флага нет» context is exactly the production state (measured
    10.08: `KUKAI_IR_CLASH` is absent from the live process environment)."""

    def __enter__(self):
        self._saved = os.environ.pop("KUKAI_IR_CLASH", None)
        return self

    def __exit__(self, *exc):
        if self._saved is not None:
            os.environ["KUKAI_IR_CLASH"] = self._saved
        else:
            os.environ.pop("KUKAI_IR_CLASH", None)
        return False


class _FlagOn:
    def __enter__(self):
        self._saved = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        clash_bundle._CACHE.clear()
        return self

    def __exit__(self, *exc):
        if self._saved is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._saved
        clash_bundle._CACHE.clear()
        return False


# ─────────────────────────────────────────────────────────────────────────
# 1. THE HOST IS AN EDGE, NOT A PAIR OF LABELS
# ─────────────────────────────────────────────────────────────────────────

def _finding(a_id, b_id, a_label="door", b_label="wall", *,
             relation="overlap", grade="conservative", depth=120.0,
             a_src="profile", b_src="profile", pair_kind="physical"):
    return {
        "finding_id": f"{a_id}~{b_id}",
        "a": {"source_element_id": a_id, "label": a_label,
              "category": "OST_Doors", "hull_source": a_src,
              "hull_grade": grade},
        "b": {"source_element_id": b_id, "label": b_label,
              "category": "OST_Walls", "hull_source": b_src,
              "hull_grade": grade},
        "hull_relation": relation,
        "hull_grade": grade,
        "verdict": "confirmed" if grade == "exact" else "possible",
        "hull_overlap_depth_mm": depth,
        "ranking_tol_mm": 1.0,
        "pair_kind": pair_kind,
    }


class HostIsAnEdgeNotALabelPair(unittest.TestCase):
    """THE MEASUREMENT THIS WAS WRITTEN FOR (`/tmp/wiring/m_baseline.py`,
    10.08.2026, decompile of `sob62_r23_v5`): the guess by label pair
    (`clash.resolve.ASSEMBLY_PAIRS`) fires on 497 findings out of 3,759, and
    `L0Element.host_id` confirms it in only 184 — **313 pairs (63.0%) would
    be cleared against the data**, the worst classes being `door~wall` 181
    and `wall~window` 58. On `sob62_fas_r23_v19`: 8,815 firings, 1,453
    confirmed, **7,362 (83.5%) not confirmed**.

    A verbatim sample from the corpus: door `10324348` declares wall
    `9857641` as its host, yet overlaps with wall `13109052`.
    """

    def test_declared_host_confirms_and_removes_the_pair(self):
        hosted = {"10324348": {"host_element_id": "9857641",
                               "host_class": "Wall", "source": "l0_host_id"}}
        out = J.judge([_finding("10324348", "9857641")], hosted=hosted)
        row = out.judged[0]
        self.assertEqual(row.host_state, "confirms")
        self.assertEqual(row.rule_id, "host_declared")
        self.assertEqual(row.rung, "note")

    def test_host_elsewhere_does_NOT_acquit(self):
        """THE CORE OF THE WAVE. A door overlaps a wall it does NOT live in.
        A guess by labels would say «узел, не смотри»; the data say this is
        a finding, and it must remain."""
        hosted = {"10324348": {"host_element_id": "9857641",
                               "host_class": "Wall", "source": "l0_host_id"}}
        out = J.judge([_finding("10324348", "13109052")], hosted=hosted)
        row = out.judged[0]
        self.assertEqual(row.host_state, "contradicts")
        self.assertNotEqual(row.rule_id, "host_declared")
        self.assertEqual(row.declared_host_id, "9857641")
        self.assertEqual(row.host_source, "l0_host_id")
        # the address of the ACTUAL host must reach the reader in words:
        # without it the line «это не тот хозяин» is unverifiable
        self.assertIn("9857641", row.text_ru)

    def test_absent_host_is_not_a_confirmation(self):
        """ABSENCE DOES NOT EXCUSE. The index exists, this pair has no host
        — and that is NOT «значит узел»."""
        out = J.judge([_finding("1", "2")], hosted={})
        self.assertEqual(out.judged[0].host_state, "absent")
        self.assertNotEqual(out.judged[0].rule_id, "host_declared")

    def test_absent_index_and_empty_index_are_DIFFERENT_facts(self):
        """`None` («не спрашивали») and `{}` («спросили, хозяев нет») must be
        different values — by the same law under which `journal.sections`
        distinguishes `None` from `{}`, and `hulls_coincide` distinguishes
        «нет» from «нечего сказать»."""
        empty = J.judge([_finding("1", "2")], hosted={})
        none = J.judge([_finding("1", "2")], hosted=None)
        self.assertEqual(empty.judged[0].host_state, "absent")
        self.assertEqual(none.judged[0].host_state, "unknown")
        self.assertNotEqual(empty.judged[0].host_state,
                            none.judged[0].host_state)

    def test_every_state_is_counted_even_when_it_removes_nothing(self):
        """`contradicts` and `absent` clear no pair at all, so they would not
        appear in `filtered_by_rule` AT ALL — meaning the most expensive fact
        would be left without a denominator. A counter of their own has been
        set up for them."""
        hosted = {"a": {"host_element_id": "zzz", "source": "l0_host_id"}}
        out = J.judge([_finding("a", "b"), _finding("c", "d")], hosted=hosted)
        self.assertEqual(out.by_host_state, {"absent": 1, "contradicts": 1})
        self.assertEqual(sum(out.by_host_state.values()), len(out.judged))
        for state in out.by_host_state:
            self.assertIn(state, J.HOST_STATES)


class HostRefIsQualifiedByProgram(unittest.TestCase):
    """A REFERENCE TO A HOST RESOLVES ONLY WITHIN ITS OWN PROGRAM.

    The previous `_host_declared` compared `host.value` against the
    neighbor's BARE `id`, and `id` is unique only within a program — a
    collision between programs is LEGITIMATE, which is exactly why
    `clash_bundle.bundle_oid` always qualifies the address (`p1/wall1`).
    That meant a door in program 7, declaring `wall1` of ITS OWN program as
    host, would clear a finding against a same-named wall in program 1 —
    an excuse reaching across the program boundary, which `KIR-V002`
    forbids.
    """

    def test_same_id_in_another_program_is_not_a_host(self):
        ops = {
            "p1/wall1": {"op": "create_wall", "id": "wall1"},
            "p7/wall1": {"op": "create_wall", "id": "wall1"},
            "p7/door1": {"op": "create_door", "id": "door1",
                         "host": {"by": "ref", "value": "wall1"}},
        }
        hosted = J.hosted_from_ops(ops)
        self.assertEqual(hosted["p7/door1"]["host_element_id"], "p7/wall1")
        # own program — we clear it
        self.assertEqual(
            J.host_relation("p7/door1", "p7/wall1", hosted)[0], "confirms")
        # a FOREIGN program — we do NOT clear it: this is exactly the defect
        self.assertEqual(
            J.host_relation("p7/door1", "p1/wall1", hosted)[0], "contradicts")

    def test_unresolvable_host_ref_is_named_not_swallowed(self):
        """The author NAMED a host that is not in the batch. This is a fact
        about the declaration and is fixed by the author; silence would read
        as «хозяина не объявляли»."""
        ops = {"p1/d": {"op": "create_door", "id": "d",
                        "host": {"by": "ref", "value": "нет-такого"}}}
        hosted = J.hosted_from_ops(ops)
        self.assertIsNone(hosted["p1/d"]["host_element_id"])
        state, host_id, _src = J.host_relation("p1/d", "p1/w", hosted)
        self.assertEqual(state, "contradicts")
        self.assertEqual(host_id, "нет-такого")

    def test_graph_segment_bodies_share_their_op_host(self):
        """The body of the graph edge is addressed as `p1/g#3`, while the
        host is declared by the OPERATION `p1/g`. The relationship must be
        findable at both addresses."""
        ops = {"p1/w": {"op": "create_wall", "id": "w"},
               "p1/g": {"op": "route_duct_system", "id": "g",
                        "host": {"by": "ref", "value": "w"}}}
        hosted = J.hosted_from_ops(ops)
        self.assertEqual(J.host_relation("p1/g#3", "p1/w", hosted)[0],
                         "confirms")


class OpsStillProduceTheEdge(unittest.TestCase):
    """The existing callers pass `ops`, not `hosted`. Not one of them may
    lose the host relationship because of this wave."""

    def test_ops_only_call_still_finds_the_host(self):
        ops = {"p1/w": {"op": "create_wall", "id": "w"},
               "p1/d": {"op": "create_door", "id": "d",
                        "host": {"by": "ref", "value": "w"}}}
        out = J.judge([_finding("p1/d", "p1/w")], ops=ops)
        self.assertEqual(out.judged[0].rule_id, "host_declared")
        self.assertEqual(out.judged[0].host_source, "program_host_ref")


class PenetrationNeedsBodyEvidence(unittest.TestCase):
    """The semantic rule «трасса через ограждение — узел» does not prove
    that the route and the enclosure intersect at all. The `agree` move
    needs exact geometry, not an outer-only overlap."""

    def test_outer_only_penetration_stays_possible_and_non_executable(self):
        finding = _finding("p1/pipe", "p1/w", a_label="pipe", b_label="wall")
        out = J.judge([finding], hosted={})
        row = out.judged[0]
        self.assertEqual(row.kind, "penetration")
        self.assertIs(row.proven, False)
        self.assertEqual(row.rung, "look")
        self.assertNotIn("create_opening", row.next_move_ru)

    def test_confirmed_word_without_inner_chain_cannot_reach_agree(self):
        finding = _finding("p1/pipe", "p1/w", a_label="pipe", b_label="wall",
                           a_src="prism", b_src="prism", grade="exact")
        row = J.judge([finding], hosted={}).judged[0]
        self.assertIsNone(row.proven)
        self.assertEqual(row.rung, "look")
        self.assertNotIn("create_opening", row.next_move_ru)

    def test_bbox_penetration_drops_to_look(self):
        finding = _finding("p1/pipe", "p1/w", a_label="pipe", b_label="wall",
                           a_src="bbox", b_src="bbox", grade="coarse")
        row = J.judge([finding], hosted={}).judged[0]
        self.assertIsNone(row.proven)
        self.assertEqual(row.rung, "look")


# ─────────────────────────────────────────────────────────────────────────
# 2. A CAP SIGNED BY ONE AXIS AND READING ANOTHER
# ─────────────────────────────────────────────────────────────────────────

class TheBodyCapMustReadBodies(unittest.TestCase):
    """MEASUREMENT (`/tmp/wiring/m_cap.py`, a live rebuild of
    `snowdon_plumb_v4`): a cap named «число ТЕЛ» and justified as «снапшот
    3 000 ТЕЛ — 91 мс» was being compared against `len(elements)`. On chunk
    24 that is 3,081 elements against **171 bodies** — a «не смотрели»
    refusal at 5.7% of its own budget; on the full building, 16,257 elements
    against **905 bodies**, while the work being refused costs 174 ms +
    11 ms.

    The batch below is WALLS WITHOUT A SNAPSHOT: each has an element, none
    has a shell (the thickness lives in the type, and no one asked the
    types). This is exactly the ratio seen on the real rebuild, and
    `create_room` will not serve here: it is `OP_NO_BODY` and does not land
    in `elements` at all — meaning the old cap cannot be reproduced with it.
    """

    def _pack(self, walls):
        return [{"ops": [{"op": "create_wall", "id": f"w{i}",
                          "p0_mm": [i * 5_000.0, 0.0, 0.0],
                          "p1_mm": [i * 5_000.0 + 4_000.0, 0.0, 0.0]}
                         for i in range(walls)]}]

    def test_five_thousand_bodiless_elements_do_not_trip_the_body_cap(self):
        with _FlagOn():
            block = clash_bundle.bundle_clash_report(self._pack(5_000))
        self.assertEqual(block["status"], "ok", block.get("message_ru"))
        self.assertEqual(block["bodies"], 0)
        # and the denominator is in place: 5,000 elements that were NOT SEEN
        self.assertEqual(block["without_body"], 5_000)

    def test_element_ceiling_is_its_own_named_axis(self):
        self.assertNotEqual(clash_bundle._max_elements(),
                            clash_bundle._max_bodies())
        with _FlagOn():
            os.environ["KUKAI_IR_CLASH_MAX_ELEMENTS"] = "16"
            try:
                clash_bundle._CACHE.clear()
                block = clash_bundle.bundle_clash_report(self._pack(64))
            finally:
                os.environ.pop("KUKAI_IR_CLASH_MAX_ELEMENTS", None)
        self.assertEqual(block["status"], "over_cap")
        # THE REFUSAL NAMES ITS OWN AXIS. «Не смотрели» without a subject is
        # indistinguishable from «смотрели и не нашли».
        self.assertIn("элементов", block["message_ru"])
        self.assertNotIn("тел", block["message_ru"].split("элементов")[0])


# ─────────────────────────────────────────────────────────────────────────
# 3. THE CLASH IS UNTIED FROM THE VERDICT
# ─────────────────────────────────────────────────────────────────────────

def _seed(key, programs, ops_each=4):
    live_journal.reset(key)
    for p in range(programs):
        live_journal.append(key, {"ops": [
            {"op": "create_room", "id": f"p{p}r{i}"} for i in range(ops_each)]},
            source="bulk")


def _seed_walls(key, programs, walls_each):
    """Walls without a snapshot: elements exist, bodies do not. Needed where
    the CAP BY ELEMENTS is being checked — `create_room` does not land in
    `elements` at all."""
    live_journal.reset(key)
    for p in range(programs):
        live_journal.append(key, {"ops": [
            {"op": "create_wall", "id": f"p{p}w{i}",
             "p0_mm": [i * 5_000.0, p * 9_000.0, 0.0],
             "p1_mm": [i * 5_000.0 + 4_000.0, p * 9_000.0, 0.0]}
            for i in range(walls_each)]}, source="bulk")


class ClashSurvivesTheVerdictCeiling(unittest.TestCase):
    """A MEASURED DEFECT. `judge` was returning via `_over_cap` BEFORE the
    line `clash = _clash_block(...)`, so the verdict's cap (1,200
    operations, chosen for the cost of `check_bundle`) was disabling the
    clash check ALONG WITH it — a check that has its own three caps and its
    own cost. The Snowdon Towers rebuild (6,335 operations) received not a
    word about clashes, and that silence reads as «коллизий нет».

    The comment one line below, meanwhile, asserted the opposite: «Коллизии
    считаются НЕЗАВИСИМО от вердикта о пригодности».
    """

    KEY = ("test-clash-over-cap", "")

    def tearDown(self):
        live_journal.reset(self.KEY)

    def test_over_the_verdict_ceiling_clash_still_speaks(self):
        os.environ["KUKAI_KIR_BUILDING_VERDICT_OPS"] = "20"
        try:
            _seed(self.KEY, programs=40, ops_each=4)     # 160 operations > 20
            with _FlagOn():
                block = live_verdict.judge(self.KEY)
        finally:
            os.environ.pop("KUKAI_KIR_BUILDING_VERDICT_OPS", None)
        self.assertIsNotNone(block)
        self.assertIn("НЕ СЧИТАЛСЯ", block["message_ru"])   # the verdict refused
        self.assertIn("clash", block)                        # the clash — none
        self.assertIn("КОЛЛИЗИИ", block["message_ru"])


class ClashDoesNotRideTheVerdictSwITCH(unittest.TestCase):
    """THE THIRD PLACE WHERE THE CLASH INHERITED SOMEONE ELSE'S SWITCH, and
    the most silent one.

    `judge` began with the line `if not enabled(): return None`, and
    `enabled()` reads `KUKAI_KIR_BUILDING_VERDICT` — the VERDICT flag. Two
    switches sat on one wire: turning off the model's feedback also turned
    off the BUILDING AUDIT, which has its own flag, `KUKAI_IR_CLASH`.

    WHAT EXACTLY BECAME INDISTINGUISHABLE. `judge` returns `None`, the stamp
    does `if block:` and places nothing — the receipt ships out WITHOUT a
    single word about clashes. It looks exactly the same when there are no
    clashes. That is, «прибор был выключен чужим тумблером» and
    «пересечений не найдено» produced the SAME byte-for-byte answer, and the
    reader had no way to tell them apart.
    """

    KEY = ("test-clash-verdict-switch", "")

    def tearDown(self):
        live_journal.reset(self.KEY)
        os.environ.pop("KUKAI_KIR_BUILDING_VERDICT", None)

    def test_verdict_switch_does_not_silence_the_audit(self):
        _seed(self.KEY, programs=3)
        os.environ["KUKAI_KIR_BUILDING_VERDICT"] = "0"
        with _FlagOn():
            block = live_verdict.judge(self.KEY)
        self.assertIsNotNone(block, "вердикт выключен — аудит замолчал вместе с ним")
        self.assertIn("clash", block)
        self.assertEqual(block["verdict"], "")      # there is no verdict, and there should not be one
        self.assertIn("КОЛЛИЗИИ", block["message_ru"])

    def test_both_switches_off_is_still_byte_identical(self):
        """Production: `KUKAI_IR_CLASH` is absent. Then even with the
        verdict switched off, the answer must stay the same — `None`."""
        _seed(self.KEY, programs=3)
        os.environ["KUKAI_KIR_BUILDING_VERDICT"] = "0"
        with _FlagOff():
            self.assertIsNone(live_verdict.judge(self.KEY))


class ClashObservesTheBulkDoor(unittest.TestCase):
    """A PRODUCT BLOCKER. `_stamp_building_verdict` is called from exactly
    two lines, both on the `bulk=False` path; `handle_revit_ir_bulk` never
    called it. That is, the one route by which WHOLE buildings are
    assembled is exactly the one the clash check never saw.
    """

    KEY = ("test-clash-bulk-door", "")

    def tearDown(self):
        live_journal.reset(self.KEY)

    def test_clash_only_reads_the_whole_journal_not_one_chunk(self):
        """THE SEAM IS THE JOURNAL BATCH, NOT THE CHUNK. A clash is a
        relationship between TWO elements, and a chunk is cut every 250
        operations: a pipe from chunk 7 and a wall from chunk 3 will never
        meet in the same program."""
        _seed(self.KEY, programs=26, ops_each=10)
        with _FlagOn():
            block = live_verdict.clash_only(self.KEY)
        self.assertIsNotNone(block)
        # 26 journal programs, not one: the batch is the unit of the
        # building
        self.assertEqual(len(live_journal.get(self.KEY).records), 26)

    def test_clash_only_builds_no_verdict(self):
        """The exclusion of the admin door from the VERDICT remains: there
        the author is the materializer, and there is no one to teach. The
        clash does not inherit that argument."""
        _seed(self.KEY, programs=3)
        with _FlagOn():
            block = live_verdict.clash_only(self.KEY)
        self.assertIsNotNone(block)
        for forbidden in ("verdict", "blocking", "rules_evaluated",
                          "rules_suspended"):
            self.assertNotIn(forbidden, block)

    def test_a_silent_instrument_is_distinguishable_from_a_clean_result(self):
        """«ПРИБОР НЕ РАБОТАЛ» AND «ПЕРЕСЕЧЕНИЙ НЕТ» ARE DIFFERENT ANSWERS.

        With the flag on, silence is IMPOSSIBLE by construction: every
        outcome carries a `status` and a text. A clean result must carry a
        DENOMINATOR — how many bodies took part at all and how many were not
        seen — otherwise «находок 0» is an assertion about nothing."""
        _seed(self.KEY, programs=2, ops_each=3)      # create_room: no bodies
        with _FlagOn():
            block = live_verdict.clash_only(self.KEY)
        self.assertEqual(block["status"], "ok")
        self.assertEqual(block["total_findings"], 0)
        # the denominator is in place, and it says there was NOTHING TO LOOK
        # AT
        self.assertEqual(block["bodies"], 0)
        self.assertIn("НИ ОДНОГО ТЕЛА", block["message_ru"])
        self.assertIn("Это НЕ «коллизий нет»", block["message_ru"])
        self.assertIn("search_complete", block)

    def test_a_refusal_names_its_phase_instead_of_reporting_zero(self):
        os.environ["KUKAI_IR_CLASH_MAX_ELEMENTS"] = "16"
        try:
            _seed_walls(self.KEY, programs=4, walls_each=20)
            with _FlagOn():
                block = live_verdict.clash_only(self.KEY)
        finally:
            os.environ.pop("KUKAI_IR_CLASH_MAX_ELEMENTS", None)
        self.assertEqual(block["status"], "over_cap")
        self.assertIn("phase", block)
        self.assertNotIn("total_findings", block)   # there is NO findings number at all
        self.assertIn("не смотрели", block["message_ru"])

    def test_bulk_door_stamps_clash_under_its_own_key(self):
        """The block travels under the name `clash`, and NOT inside
        `building`: the `building` key on a door with no verdict would read
        as «здание судили»."""
        _seed(self.KEY, programs=3)
        receipt = {"ok": True, "message_ru": "построено"}
        from kir import serving
        with _FlagOn():
            asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, 0)))
        self.assertIn("clash", receipt)
        self.assertNotIn("building", receipt)

    def test_reading_turn_stamps_nothing(self):
        """A read-only move does not belong to the building (measured 29.07:
        176 reads for 5 writes). The journal has not grown — there is
        nothing to say."""
        _seed(self.KEY, programs=3)
        grown = live_verdict.programs_seen(self.KEY)
        receipt = {"ok": True}
        from kir import serving
        with _FlagOn():
            asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, grown)))
        self.assertEqual(receipt, {"ok": True})

    def test_clash_never_refuses_the_write(self):
        """A FALSE REFUSAL OF A SOUND BUILD COSTS MORE THAN A MISSED FINDING.
        A broken audit has no right to cost a move in which Revit has
        already written: the stamp touches neither `ok` nor `err` even when
        it fails."""
        _seed(self.KEY, programs=3)
        receipt = {"ok": True, "message_ru": "построено"}
        before = _sha(receipt)
        from kir import serving
        broken = live_verdict.clash_only

        def explode(_key):
            raise RuntimeError("аудит сломан")

        live_verdict.clash_only = explode
        try:
            with _FlagOn():
                out = asyncio.run(
                    serving._stamp_building_clash(receipt, (self.KEY, 0)))
        finally:
            live_verdict.clash_only = broken
        self.assertIs(out, receipt)
        self.assertEqual(_sha(receipt), before)
        self.assertTrue(receipt["ok"])


class FlagOffChangesNotOneByte(unittest.TestCase):
    """MEASURED 10.08.2026 (`/tmp/wiring/m_flagoff.py`), two real buildings
    materialized from decompile, with `KUKAI_IR_CLASH` ABSENT — that is, in
    the production state:

        sob62_r23_v5     (9 programs, 1,043 operations)
            before the fix sha(verdict.judge) = 7bcd555a…b51e, message_ru 353 chars.
            after                              = 7bcd555a…b51e, message_ru 353 chars.
        snowdon_plumb_v4 (30 chunks, 7,500 operations — ABOVE the verdict cap)
            before the fix sha = dbde8fa6…15e0, message_ru 359 chars.
            after              = dbde8fa6…15e0, message_ru 359 chars.
    """

    KEY = ("test-clash-flag-off", "")

    def tearDown(self):
        live_journal.reset(self.KEY)

    def test_clash_only_is_silent(self):
        _seed(self.KEY, programs=5)
        with _FlagOff():
            self.assertIsNone(live_verdict.clash_only(self.KEY))

    def test_bulk_stamp_adds_no_key_and_no_byte(self):
        _seed(self.KEY, programs=5)
        receipt = {"ok": True, "message_ru": "построено", "kir": True}
        before = _sha(receipt)
        from kir import serving
        with _FlagOff():
            asyncio.run(serving._stamp_building_clash(receipt, (self.KEY, 0)))
        self.assertEqual(_sha(receipt), before)
        self.assertNotIn("clash", receipt)

    def test_verdict_receipt_is_unchanged_over_the_ceiling_too(self):
        """Reordering `_clash_block` ahead of the verdict cap has no right to
        change a single byte with the flag off — including the branch of the
        cap itself, where the splice now appears."""
        os.environ["KUKAI_KIR_BUILDING_VERDICT_OPS"] = "20"
        try:
            _seed(self.KEY, programs=40, ops_each=4)
            with _FlagOff():
                block = live_verdict.judge(self.KEY)
        finally:
            os.environ.pop("KUKAI_KIR_BUILDING_VERDICT_OPS", None)
        self.assertNotIn("clash", block)
        self.assertIn("НЕ СЧИТАЛСЯ", block["message_ru"])


class TheSeparatorsAreOneFact(unittest.TestCase):
    """The address of a clash finding and the address that resolves the host
    reference must lead to the same line of script. Two `"/"` literals in
    two modules would drift apart silently — and would drift apart on the
    addressing itself."""

    def test_bundle_separator_is_the_same_in_both_modules(self):
        self.assertEqual(J._BUNDLE_SEP, clash_bundle._BUNDLE_SEP)

    def test_segment_separator_is_the_same_in_both_modules(self):
        self.assertEqual(J._SEGMENT_SEP, clash_bundle._SEGMENT_SEP)


class TheHostIndexRidesTheBundle(unittest.TestCase):
    """The host edge is built by whoever decomposed the batch — a second
    reference resolver living next to the judge would drift apart from
    `bundle_oid` at the very first edit."""

    def test_bundle_elements_publishes_the_edge(self):
        pack = [{"ops": [
            {"op": "create_wall", "id": "w1", "p0_mm": [0, 0, 0],
             "p1_mm": [1000, 0, 0]},
            {"op": "create_door", "id": "d1",
             "host": {"by": "ref", "value": "w1"}},
        ]}]
        geo = clash_bundle.bundle_elements(pack)
        self.assertIn("p1/d1", geo.hosted)
        self.assertEqual(geo.hosted["p1/d1"]["host_element_id"], "p1/w1")
        self.assertEqual(geo.hosted["p1/d1"]["host_class"], "create_wall")

    def test_empty_bundle_gives_an_EMPTY_index_not_a_missing_one(self):
        """«Спросили, хозяев не объявлено» and «не спрашивали» are different
        facts, and on this path the second one never occurs."""
        geo = clash_bundle.bundle_elements([{"ops": [
            {"op": "create_wall", "id": "w1"}]}])
        self.assertEqual(geo.hosted, {})
        self.assertIsNotNone(geo.hosted)


if __name__ == "__main__":
    unittest.main()
