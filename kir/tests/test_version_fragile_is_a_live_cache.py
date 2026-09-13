"""A RATCHET ON `spec.VERSION_FRAGILE`: A CACHE WITHOUT INVALIDATION IS A LIE.

`VERSION_FRAGILE` is not a list we invented, but a **CACHED ANSWER FROM THE
GATE**: `tools/compile_gate_offline.py` prints which op with which field
fails to emit on which version, and that answer is recorded in
`version_fragile_gate_answer.json` next to it. The gate cannot be asked at
the moment of materialization — the gate IS materialization plus
compilation — so the loop is opened by TIME instead: run, record, use.

**A cache with no staleness check is a lie, not an optimization.** Hence
this file.

WHY THE RATCHET IS TWO-SIDED, AND WHY A ONE-SIDED ONE WOULD BE HALF OF IT:

    the gate refuses a pair that is NOT in the list
        → the op will ride in the shared chunk and take its neighbors down
          with it. Measured on 08.13: THREE such ops took down 2,742
          compatible ones, a ratio of 1:914. The error is LOUD — it is
          visible from the loss count.

    the list has a pair the gate NO LONGER REFUSES
        → the op stays in its own program forever, even though it no longer
          needs isolation: a branch was added to the emitter, Autodesk fixed
          it, or the op was rewritten. The error is SILENT: the gate is
          green, losses are small, everything looks correct, and we pay in
          extra bridge round-trips. A stale cache entry does not break
          correctness — it charges silently, which is exactly why nobody
          finds it.

Hence what is checked is the SYMMETRIC DIFFERENCE, not mere containment.

🔴 THIS FILE IS RED ON DELIVERY, AND THAT IS NOT A REGRESSION — DO NOT FIX
IT BY DISABLING.

    AssertionError: set() is not true : the gate's answer is empty — there
    is nothing to check against

The gate's answer is recorded, but `op_name` in it is NOT RESOLVED: the
`compile_gate_offline.py` report names the culprit as an `op_id` like
`e11862664`, while checking requires (OP, FIELD) pairs. Resolving
`op_id → op_name` requires one pass over the `k2_ar_rd_v7` tree under the
box lock, which neighboring zones held at the moment of delivery.

**Red here is a vacuum guard that fired on its own instrument on the very
first run:** it refused to check against an EMPTY authority instead of
silently turning green on an empty set. Green on an empty `gate_pairs()`
would have meant "no discrepancies," even though there was nothing to check
against — exactly the form this file guards against.

FIXED IN ONE ACTION: resolve `op_name` in
`version_fragile_gate_answer.json` by a pass over the tree. Neither
`VERSION_FRAGILE`, nor the predicate, nor the materializer are touched by
this — they were measured by a paired run (2,745 → 125 lost ops, 1,519
checks, 0 compilation refusals).

WHAT THIS FILE DOES NOT DO. It does not run the gate — the run takes half an
hour and requires the box lock. It checks the list against the RECORDED
answer. So it catches the discrepancy "list versus the last run" and does
NOT catch "the last run versus today's compiler." The latter is closed only
by a new run, and the answer's date is printed in the file itself so its
age is visible.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from kir import spec

ANSWER = pathlib.Path(__file__).with_name("version_fragile_gate_answer.json")


def gate_pairs(answer: dict) -> set[tuple[str, str | None]]:
    """Pairs (op, field) that the GATE refused. The sole authority."""
    return {(row["op_name"], row["field"]) for row in answer["refusals"]
            if row.get("op_name")}


def drift(cached: set, from_gate: set) -> tuple[set, set]:
    """A cache miss in BOTH directions: (stale, missing)."""
    return cached - from_gate, from_gate - cached


class TheCacheAgreesWithTheGateInBothDirections(unittest.TestCase):

    def setUp(self) -> None:
        self.answer = json.loads(ANSWER.read_text(encoding="utf-8"))
        # A VACUUM GUARD — IN `setUp`, NOT IN ONE METHOD.
        #
        # The first edition put it only in the drift control, and one method
        # out of three passed on an empty authority FOR NOTHING: `missed = ∅
        # − cached` is empty by construction, so "the gate refuses nothing
        # that isn't in the list" is a truth that carries no information.
        #
        # And this vacuum was visible ONLY because the neighbors were
        # failing. Resolving `op_name` would turn the neighbors green, and
        # the third would stay green for BOTH reasons at once — there would
        # be nothing left to tell "fine" apart from "on an empty set." A
        # DEFECT WHOSE ONLY SYMPTOM IS A NEIGHBOR FAILING DISAPPEARS ALONG
        # WITH THE NEIGHBOR'S FIX: the window of visibility closes by REPAIR,
        # not by time. Hence the threshold is placed BEFORE name resolution,
        # not after.
        self.gate = gate_pairs(self.answer)
        #: Ops that the run behind this answer ACTUALLY contained
        #: (`facts.op_histogram` of its tree). The authority's scope of coverage.
        self.ops_in_run = set(self.answer.get("ops_in_run") or ())
        self.assertTrue(
            self.gate,
            "ответ ворот пуст — сверять не с чем. НИ ОДИН из методов этого "
            "класса не имеет права судить на пустом авторитете: на пустом "
            "множестве и «пропущенных нет», и «протухших нет» истинны "
            "тавтологически.")

    def test_no_pair_is_missing_from_the_cache(self):
        """THE LOUD SIDE: the gate refused, and the list is silent."""
        stale, missed = drift(set(spec.VERSION_FRAGILE), self.gate)
        self.assertFalse(missed, (
            f"ворота отказывают паре, которой нет в VERSION_FRAGILE: "
            f"{sorted(missed)}. Такой оп поедет в общем куске и унесёт "
            f"соседей — 13.08 это стоило 2 742 опа на трёх опах."))

    def test_no_pair_outlived_its_reason(self):
        """THE SILENT SIDE: the list remembers something the gate no longer refuses.

        🔴 ONLY WHAT THE RUN COULD OBSERVE IS JUDGED (amendment of 2026-08-15).

        The gate's answer was taken from ONE building (`k2_ar_rd_v7`, 150
        programs, 3 refusals), and its `facts.op_histogram` names **13
        ops**. Pairs whose op was not in the run at all cannot be judged by
        this answer: zero refusals there means "there was nothing to refuse
        with," not "the gate does not refuse."

        The measurement that prompted the amendment: padding
        `VERSION_FRAGILE` with five pairs from the `*_emit.py` satellites
        (a foundation with openings, a multi-story stair run, three
        structural loads) colored this check red — even though none of the
        five ops is IN the building. The accusation was about DATA and read
        as about the list; this is canon form 4: a zero from the corpus
        requires proof that the corpus was reachable.

        The amendment does NOT require and does not get a "missed" side:
        there the gate SPEAKS and the list is silent, and the list's silence
        is guilty regardless of the run's composition.
        """
        stale, _missed = drift(set(spec.VERSION_FRAGILE), self.gate)
        judged = {(op, field) for op, field in stale if op in self.ops_in_run}
        unjudgeable = sorted(stale - judged)
        self.assertFalse(judged, (
            f"в VERSION_FRAGILE пара, которую ворота больше не отказывают: "
            f"{sorted(judged)}. Оп остаётся в собственной программе без нужды, "
            f"и мы платим лишними кругами моста молча."))
        # The unjudged does not stay silent: otherwise the scope of coverage
        # would silently expand with every new pair, and one day there would
        # be nothing left to judge.
        if unjudgeable:
            print("\n  вне охвата ответа ворот (опа нет в прогоне %s): %s"
                  % (self.answer.get("run"), unjudgeable))

    def test_the_scope_of_the_answer_is_declared_and_non_empty(self):
        """Coverage must be DECLARED. An answer without a list of its own ops
        lets the previous check judge over an unknown domain — and it will
        turn green or red for a reason nobody sees."""
        self.assertTrue(
            self.ops_in_run,
            "в ответе ворот нет `ops_in_run` — область охвата не объявлена, "
            "и сторону «протухло» не на чем ограничить. Пересними ответ: "
            "`facts.op_histogram` в корне `<run>/tree.json`")
        # Every pair the answer NAMES must lie inside the coverage —
        # otherwise the coverage describes a different run than the one the
        # answer was taken from.
        outside = sorted({op for op, _f in self.gate} - set(self.ops_in_run))
        self.assertFalse(outside, (
            f"ответ ворот отказывает опам, которых нет в объявленном охвате: "
            f"{outside}. Значит `ops_in_run` и `refusals` сняты с РАЗНЫХ "
            f"прогонов, и сверять ими нельзя ничего."))

    def test_the_drift_check_catches_both_directions(self):
        """CONTROL-FAIL AT BOTH ENDS: without it, the green above means
        nothing.

        What is checked is not the list but the check's ABILITY to see a
        discrepancy. A one-sided ratchet would pass the first half and fail
        the second.
        """
        gate = self.gate
        one = next(iter(gate))

        stale, missed = drift(gate | {("create_wall_that_does_not_exist", None)}, gate)
        self.assertEqual(stale, {("create_wall_that_does_not_exist", None)})
        self.assertFalse(missed)

        stale, missed = drift(gate - {one}, gate)
        self.assertEqual(missed, {one})
        self.assertFalse(stale)

        self.assertEqual(drift(gate, gate), (set(), set()),
                         "совпадающие множества обязаны давать пустой дрейф")


class TheMissingSideCanActuallyFail(unittest.TestCase):
    """THE CARDINALITY AT WHICH "NOTHING IS MISSING" IS ABLE TO FAIL — AS A
    STANDING TEST, NOT A ONE-OFF CHECK BY HAND.

    The threshold in the neighboring class's `setUp` forbids judging on an
    EMPTY authority. But as soon as op names are resolved, the threshold
    will pass and become invisible — and the method
    `test_no_pair_is_missing_from_the_cache` will stay green, and it will
    again be unclear whether it is green on the merits or because it has
    nothing to fail on.

    It needs AT LEAST ONE pair at the gate that is NOT in `VERSION_FRAGILE`.
    Here it is supplied as a STAND-IN, every run: if the method does not
    notice it, it will not notice a real one either.

    A one-off check by hand would rot silently: in a week nobody will
    remember it existed. It is the same difference as between a promise in
    prose and an assertion in code — the former rots without a trace.
    """

    def test_a_planted_pair_absent_from_the_cache_turns_it_red(self):
        planted = {"run": "подставной", "dated": "—", "tool": "—", "checks": 0,
                   "refusals": [
                       {"op_name": "create_op_that_no_cache_knows",
                        "field": None, "versions": ["2021"], "count": 1},
                   ]}
        gate = gate_pairs(planted)
        self.assertTrue(gate, "подставной ответ обязан быть НЕПУСТЫМ, иначе "
                              "этот тест сам вакуумен")
        stale, missed = drift(set(spec.VERSION_FRAGILE), gate)
        self.assertTrue(missed, (
            "подставная пара, которой нет в VERSION_FRAGILE, НЕ ПОПАЛА в "
            "`missed` — значит сторона «пропущенных нет» неспособна упасть, и "
            "её зелёный ничего не обеспечивает"))
        self.assertIn(("create_op_that_no_cache_knows", None), missed)

    def test_and_a_pair_the_cache_knows_does_not(self):
        """Control-PASS to the previous one: the test must also be able to
        NOT go red."""
        known = next(iter(spec.VERSION_FRAGILE))
        planted = {"refusals": [{"op_name": known[0], "field": known[1],
                                 "versions": ["2021"], "count": 1}]}
        stale, missed = drift(set(spec.VERSION_FRAGILE), gate_pairs(planted))
        self.assertFalse(missed, "известная кэшу пара не должна числиться "
                                 "пропущенной")


class TheAnswerNamesItsOwnProvenance(unittest.TestCase):
    """A SEPARATE CLASS — ON PURPOSE, AND THIS IS NOT COSMETIC.

    The "the gate's answer is not empty" threshold sits in the neighboring
    class's `setUp` and fails ALL of its methods. This check does not belong
    there: it judges not the CACHE but the FILE — whether it names its own
    provenance. An empty answer with no provenance and an empty answer with
    provenance are different defects, and the second must not hide behind
    the first.

    Leave it under the threshold — "the file did not name its run" would
    read as "the gate is empty," and fixing the emptiness would make the
    missing provenance invisible. Exactly the same mechanism for which the
    threshold exists in the first place.

    THE DEBT "REPLACE THE DATE WITH A DIGEST OF EMISSION SOURCES" IS CLOSED
    BY REFUSAL, 2026-08-13, and the refusal matters more than compliance. A
    digest of `authoring.py` would report that something changed and would
    go red on EVERY emitter edit (6,858 lines, edited weekly) — that is, it
    would become chronically red, and a chronically red test stops being an
    instrument (form 1). The question the digest was meant to answer — "has
    the list diverged from the emitter" — is settled more strongly and
    precisely: `test_version_fragile_asks_the_emitter.py` walks
    `authoring.py` by its syntax tree and names EVERY version-refusal site
    by name. A digest DESCRIBES the code; a traversal ASKS it — the same
    difference as between a date and a path.

    It paid for itself immediately: the pair `("create_tag", "tag_type")`
    turned up missing from `VERSION_FRAGILE`, because `k2_ar_rd_v7` — the
    run this cache was taken from — contains NOT ONE tag (851 of them lie in
    `k2_ar_rd_v8`, and all 851 carry `tag_type`).
    """

    def test_the_answer_names_run_date_tool_and_checks(self):
        answer = json.loads(ANSWER.read_text(encoding="utf-8"))
        for key in ("run", "dated", "tool", "checks"):
            self.assertIn(key, answer, f"ответ ворот не назвал {key}")


class AnEmptyAnswerMustFailEveryMethodNotSome(unittest.TestCase):
    """CONTROL-FAIL on the guard itself: an empty answer fails ALL three methods.

    Without it, "two of three shout, the third stays silent" would return on
    the next edit, and noticing it again would be possible only through a
    neighbor's failure.
    """

    def test_every_method_refuses_on_an_empty_gate_answer(self):
        empty = {"run": "x", "dated": "x", "tool": "x", "checks": 0,
                 "refusals": []}
        self.assertEqual(gate_pairs(empty), set())
        for name in ("test_no_pair_is_missing_from_the_cache",
                     "test_no_pair_outlived_its_reason",
                     "test_the_drift_check_catches_both_directions"):
            with self.subTest(method=name):
                case = TheCacheAgreesWithTheGateInBothDirections(name)
                case.answer = empty
                with self.assertRaises(AssertionError, msg=(
                        f"{name} прошёл на ПУСТОМ ответе ворот — "
                        f"вакуумно-зелёный метод")):
                    case.gate = gate_pairs(empty)
                    case.assertTrue(case.gate, "ответ ворот пуст")


class ThePredicateReadsFieldsNotNames(unittest.TestCase):
    """The key is the pair (op, FIELD). By name alone, 333 ops would have
    left instead of 125."""

    def test_the_same_op_is_fragile_only_with_the_field(self):
        self.assertTrue(spec.is_version_fragile("create_floor", {"holes": [[0, 0]]}))
        self.assertFalse(spec.is_version_fragile("create_floor", {"outline": []}))

    def test_a_dotted_path_is_walked_not_matched_as_a_key(self):
        """`contour.holes` is a PATH. `get("contour.holes")` would find
        nothing, and "not fragile" would become indistinguishable from
        "not found"."""
        self.assertTrue(spec.is_version_fragile(
            "create_floor_by_contour", {"contour": {"holes": [1]}}))
        self.assertFalse(spec.is_version_fragile(
            "create_floor_by_contour", {"contour": {}}))

    def test_a_field_none_entry_means_the_whole_op(self):
        self.assertTrue(spec.is_version_fragile("create_ceiling", {}))

    def test_an_unrelated_op_is_never_fragile(self):
        self.assertFalse(spec.is_version_fragile("create_wall", {"holes": [1]}))


if __name__ == "__main__":
    unittest.main()
