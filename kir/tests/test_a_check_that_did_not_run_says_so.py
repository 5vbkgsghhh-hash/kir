"""SILENCE STOPS READING AS «NO OBJECTIONS».

Two defects from different modules, but of one kind: an empty answer meant,
to the reader, «we looked and found nothing», while in fact it meant «we
looked in the wrong place» or «we did not look at all».

RT-28 (`live/verdict.clash_only`). The clash pack was assembled from
`entry.records`, i.e. from EVERYTHING declared, including `rolled_back` and
`refused_pre_effect` — geometry that is not in the model. `judge()` has
judged `entry.standing()` since 08-16; this door did not get that fix, and
two doors onto one journal answered DIFFERENTLY about the same building. A
rolled-back duplicate produced a PHANTOM finding.

RT-26 (`live/transfer`). Both offline checks of the transfer decision stood
under `except Exception: return ()`, and for them an empty tuple means «no
objections». A broken tree looked like a clean pack.

🔴 CAUTION WITH RT-28: next to the edited line lives the 08-17 fix — «a LIST
travels into `_new_from`, not a journal object» (`enumerate` used to raise
`TypeError`, and the absolute fail-open swallowed it and returned `None`).
It still holds here too: `standing` is a list, and it is the SAME one the
pack was assembled from, as `_new_from`'s own docstring requires. A separate
instrument below guards this.
"""
from __future__ import annotations

import builtins
import os
import unittest

from kir import clash_bundle as CB
from kir.live import journal as J
from kir.live import transfer as T
from kir.live import verdict as V


# ═══════════════════════════════════════════════════════════════════════════
# RT-28. A building's audit judges WHAT STANDS
# ═══════════════════════════════════════════════════════════════════════════

_L1 = {"by": "ref", "value": "lvl"}
_L1_BY_NAME = {"by": "name", "value": "Этаж 1"}
_BOX = [((0, 0), (8000, 0)), ((8000, 0), (8000, 5000)),
        ((8000, 5000), (0, 5000)), ((0, 5000), (0, 0)),
        ((4000, 0), (4000, 5000))]


def _ar_program() -> dict:
    """Architectural: a box. Gives no bodies — the program does not express wall thickness."""
    ops: list[dict] = [
        {"op": "create_level", "id": "lvl", "elev_mm": 0, "name": "Этаж 1"}]
    for i, (p0, p1) in enumerate(_BOX, start=1):
        ops.append({"op": "create_wall", "id": f"w{i}", "p0_mm": list(p0),
                    "p1_mm": list(p1), "level": _L1, "height_mm": 3000})
    return {"ir_version": "1.0", "ops": ops}


def _ov_program() -> dict:
    """HVAC: one duct. Two of these — a coincident duplicate."""
    return {"ir_version": "1.0", "ops": [
        {"op": "create_duct", "id": "duct1", "p0_mm": [200, 1000, 2700],
         "p1_mm": [7800, 1000, 2700], "level": _L1_BY_NAME,
         "diameter_mm": 400}]}


class _ClashOn:
    def __enter__(self):
        self._saved = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()
        return self

    def __exit__(self, *exc):
        if self._saved is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._saved
        CB._CACHE.clear()
        return False


class TheAuditJudgesWhatStands(unittest.TestCase):

    KEY = ("rt28-audit", "")

    def tearDown(self):
        J.reset(self.KEY)
        CB._CACHE.clear()

    def _seed(self, *, roll_back_the_duplicate: bool):
        J.reset(self.KEY)
        J.append(self.KEY, _ar_program(), source="bulk")
        J.append(self.KEY, _ov_program(), source="bulk")
        third = J.append(self.KEY, _ov_program(), source="bulk")
        if roll_back_the_duplicate:
            self.assertTrue(J.advance(self.KEY, third.seq, "rolled_back"))

    def test_a_rolled_back_duplicate_is_not_a_clash(self):
        """POSITIVE. Rolled-back geometry leaves the pack.

        Measurement on this same trio of programs:
            BEFORE duplicates 1, total_findings 1, bodies 2
            AFTER  duplicates 0, total_findings 0, bodies 1
        """
        self._seed(roll_back_the_duplicate=True)
        entry = J.get(self.KEY)
        self.assertEqual(len(entry.records), 3)
        self.assertEqual(len(entry.standing()), 2)
        with _ClashOn():
            block = V.clash_only(self.KEY)
        self.assertIsNotNone(block)
        self.assertEqual(block["status"], "ok", block.get("message_ru"))
        self.assertEqual(block["total_findings"], 0, block.get("findings"))
        self.assertEqual(block["bodies"], 1)

    def test_the_probe_still_sees_the_duplicate_when_it_stands(self):
        """FAIL CONTROL. The same trio WITHOUT a rollback must produce a finding.

        Otherwise «0 findings» would be a property of the instrument, not
        of the building — exactly the swap `clash_only`'s own docstring
        warns about.
        """
        self._seed(roll_back_the_duplicate=False)
        with _ClashOn():
            block = V.clash_only(self.KEY)
        self.assertEqual(block["duplicates"], 1, block)
        self.assertEqual(block["bodies"], 2)
        pair = next(r for r in block["findings"]
                    if r["pair_kind"] == "coincident_duplicate")
        self.assertEqual({pair["a_element_id"], pair["b_element_id"]},
                         {"p2/duct1", "p3/duct1"})

    def test_a_refused_program_is_not_in_the_pack_either(self):
        """`refused_pre_effect` — it never reached the model, there was nothing to change."""
        self._seed(roll_back_the_duplicate=False)
        entry = J.get(self.KEY)
        self.assertTrue(J.advance(self.KEY, entry.records[-1].seq,
                                  "refused_pre_effect"))
        with _ClashOn():
            block = V.clash_only(self.KEY)
        self.assertEqual(block["total_findings"], 0, block.get("findings"))

    def test_both_doors_read_the_same_pack(self):
        """ONE JOURNAL — ONE ANSWER. The doors disagreeing was itself the defect.

        `judge` and `clash_only` compute clash over the same building, and
        their blocks must agree in their numbers.
        """
        self._seed(roll_back_the_duplicate=True)
        with _ClashOn():
            only = V.clash_only(self.KEY)
            CB._CACHE.clear()
            judged = V.judge(self.KEY)
        self.assertIsNotNone(judged)
        self.assertEqual(judged["clash"]["total_findings"],
                         only["total_findings"])
        self.assertEqual(judged["clash"]["bodies"], only["bodies"])

    def test_the_seq_boundary_is_translated_against_the_very_same_list(self):
        """GUARD OF THE 08-17 FIX — it is NOT broken by this patch.

        `_new_from` must receive the SAME list the pack was assembled from
        (per its own docstring), not a journal object: on the object,
        `enumerate` used to raise `TypeError`, and the absolute fail-open
        turned that into `None`, i.e. into «no collisions found». Checked by
        an observable consequence: the boundary is counted BY STANDING
        positions, not by all records.
        """
        self._seed(roll_back_the_duplicate=True)
        entry = J.get(self.KEY)
        standing = entry.standing()
        # the LAST record is rolled back, so its seq is not in the standing list
        self.assertEqual([r.seq for r in standing], [0, 1])
        self.assertEqual(V._new_from(standing, 1), 2)
        self.assertEqual(V._new_from(entry.records, 1), 2)
        with _ClashOn():
            block = V.clash_only(self.KEY, since_seq=1)
        # not `None`: `None` here would mean a swallowed exception
        self.assertIsNotNone(block)
        self.assertEqual(block["status"], "ok", block.get("message_ru"))


# ═══════════════════════════════════════════════════════════════════════════
# RT-26. A check that did not happen SAYS SO
# ═══════════════════════════════════════════════════════════════════════════

class _BrokenImport:
    """A broken tree: the listed modules fail to come up."""

    def __init__(self, *names: str) -> None:
        self.names = set(names)
        self.real = builtins.__import__

    def __enter__(self):
        def guard(name, *a, **kw):
            if name in self.names:
                raise ImportError(f"сломанное дерево: {name}")
            return self.real(name, *a, **kw)
        builtins.__import__ = guard
        return self

    def __exit__(self, *exc):
        builtins.__import__ = self.real
        return False


_FAT = [[{"op": "create_wall", "id": f"w{i}", "p0_mm": [0, 0],
          "p1_mm": [6000, 0]} for i in range(30)]]


class ACheckThatDidNotRunSaysSo(unittest.TestCase):

    def test_a_broken_compiler_is_not_a_clean_pack(self):
        """POSITIVE. Both lists NAME the absence of a check.

        Measurement: before the fix both gave `()` — indistinguishable from «no objections».
        """
        with _BrokenImport("kir.compiler", "kir.spec"):
            over = T._over_budget(_FAT)
            pre = T._preflight(_FAT)
        for what, got in (("over_budget", over), ("preflight", pre)):
            self.assertEqual(len(got), 1, f"{what}: {got}")
            self.assertTrue(got[0].startswith(T.UNAVAILABLE_PREFIX), got)
            self.assertIn("ImportError", got[0])
            self.assertIn("НЕ «претензий нет»", got[0])

    def test_a_working_tree_still_answers_about_the_pack_itself(self):
        """FAIL CONTROL. On a whole tree, both checks SPEAK ABOUT THE PACK.

        Otherwise "a line exists" would become a property of the
        instrument: it must tell apart "no check", "the check found
        something" and "the check found nothing".
        """
        # THE LIMIT IS TAKEN FROM ITS OWN OWNER, NOT WRITTEN AS A LITERAL: it
        # has already moved before (today 100,000), and a literal here would
        # betray an instrument measuring last year's number.
        from kir.compiler import MAX_OPS_PER_PROGRAM as cap
        fat = [[{"op": "create_wall", "id": f"w{i}"} for i in range(cap + 1)]]
        over = T._over_budget(fat)
        self.assertEqual(len(over), 1, over[:1])
        self.assertIn("программа #1", over[0])
        pre = T._preflight(_FAT)
        self.assertEqual(len(pre), 1, pre)            # the compiler rejected the pack
        self.assertIn("программа #1", pre[0])
        # THE PREFIX NAME VIA `getattr`: this instrument must be GREEN even
        # on a frozen copy FROM BEFORE the fix — it proves that the check
        # SEES the objection to the pack, and has nothing to go red about here.
        mark = getattr(T, "UNAVAILABLE_PREFIX", "ПРОВЕРКА НЕ СОСТОЯЛАСЬ")
        self.assertNotIn(mark, over[0])
        self.assertNotIn(mark, pre[0])
        # and on a LEGAL pack the check stays silent — zero remains
        # expressible and DISTINGUISHABLE from "there was no check"
        self.assertEqual(T._over_budget(_FAT), ())

    def test_the_named_absence_reaches_the_decision_a_human_reads(self):
        """The line must reach `Decision.to_dict()`, not settle inside."""
        with _BrokenImport("kir.compiler", "kir.spec"):
            decision = T.Decision(status=T.Status.READY,
                                  over_budget=T._over_budget(_FAT),
                                  preflight=T._preflight(_FAT))
        body = decision.to_dict()
        self.assertTrue(body["over_budget"][0].startswith(T.UNAVAILABLE_PREFIX))
        self.assertTrue(body["preflight"][0].startswith(T.UNAVAILABLE_PREFIX))

    def test_the_named_absence_is_a_warning_and_not_a_refusal(self):
        """NO SECOND AUTHORITY HAS BEEN SET UP. Both checks are declared a
        WARNING (`_preflight`'s own docstring), and turning the absence of
        a prediction into a ban on transfer would violate it."""
        with _BrokenImport("kir.compiler", "kir.spec"):
            decision = T.Decision(status=T.Status.READY,
                                  over_budget=T._over_budget(_FAT),
                                  preflight=T._preflight(_FAT))
        self.assertTrue(decision.ok)
        self.assertIs(decision.refusal, None)


if __name__ == "__main__":
    unittest.main()
