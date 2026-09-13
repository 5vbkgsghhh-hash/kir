"""THE FACT OF A JOIN STOPS GETTING LOST — the `join_elements` op.

THE OWNER'S REQUEST, 17.08.2026, verbatim: "so that they compile into the
model itself with the join. that is, the fact that this is joined is not
lost but is preserved." Before 18.08 the registry had **zero** join
operations: a rebuilt building arrived in Revit falling apart, and there was
nothing to restore the connection from.

FOUR MEASUREMENTS FROM 18.08.2026, WITHOUT WHICH THIS OP WOULD BE A GUESS:

1. **NO version-fragility.** `AreElementsJoined` + `JoinGeometry` +
   `GetJoinedElements` were assembled by the live compile service against
   reference assemblies 2021, 2022, 2023, 2024, 2025, 2026 — six for six,
   zero errors. So this op is not in `VERSION_FRAGILE`: that is a
   MEASUREMENT, not an oversight.
2. **a pre-check is mandatory.** Autodesk's documentation (pitfall index,
   6/6): `JoinGeometry` throws `ArgumentException` — «The elements are
   already joined. -or- The elements cannot be joined.» Without
   `AreElementsJoined` BEFORE the call, a repeat run would fail on a pair
   it had itself joined last time. A rebuild consists of repeat runs, so
   this is the MAIN case.
3. **the reverse move is not a `state_transition`.** A join is not a trace
   of an action but the relation itself, and Revit stores it explicitly.

   🔴 THE 18.08 ENTRY SAID "`GetJoinedElements` occurs in `kir/decompile/`
   exactly zero times (measured 17.08)" — AND THAT WAS ALREADY A LIE AT THE
   TIME: the read was introduced by `39ebd521` at 07:03, the text was
   written by `518325f3` at 07:19, sixteen minutes later. On 22.08 the mode
   was switched to `COMPOSED`: capture reads all three kinds, the lifter
   `decompile/lift.py:lift_joins` is written, and a join cannot be an L1
   node — the relation has no element of its own.
4. **`IsWallJoinAllowedAtEnd` is a DIFFERENT relation.** A live measurement
   on 800 of the owner's walls: allowed-both 143/288, forbidden-both
   27/223, mixed 38/81. The fact of a join cannot be derived from
   permission to join.

Run:
    venv/bin/python -m pytest kir/tests/test_join_elements.py -q
"""
from __future__ import annotations

import unittest

from kir import (authoring, compiler, op_contract, reverse_contract,
                      spec, translation_cert)
from kir.tests.test_op_budget_seam import GROUND_SNAPSHOT

_A, _B = 277144, 277145


def _prog(first: int = _A, second: int = _B) -> dict:
    return {"ir_version": "1.0", "ops": [{
        "id": "j1", "op": "join_elements",
        "first": {"by": "element_id", "value": first},
        "second": {"by": "element_id", "value": second}}]}


def _cs(ver: str = "2026") -> str:
    out = compiler.compile_program(_prog(), ver, snapshot=GROUND_SNAPSHOT)
    assert out.ok, [d.code for d in (out.diagnostics or [])]
    return out.csharp


class TheOpExistsAndIsTyped(unittest.TestCase):

    def test_the_registry_carries_it_as_a_two_operand_relation(self):
        op = spec.OPS["join_elements"]
        self.assertEqual(op.family, "modify")
        self.assertTrue(op.writes_model)
        self.assertEqual([p.name for p in op.params], ["first", "second"],
                         "соединение — отношение ДВУХ элементов; один операнд "
                         "не выражает его вовсе")
        for p in op.params:
            self.assertTrue(p.required, f"{p.name} обязателен")

    def test_the_receipt_key_does_not_borrow_another_ops_word(self):
        """`moved_ids` would lie about a move, `id` would lie about a
        creation."""
        self.assertEqual(spec.OPS["join_elements"].result.identity_field,
                         "joined_ids")

    def test_it_has_an_emitter_wired_into_the_dispatch(self):
        self.assertIn("join_elements", authoring._EMITTERS)


class TheEmissionAsksBeforeItActs(unittest.TestCase):

    def test_are_elements_joined_is_asked_before_join_geometry(self):
        """The measurement that paid for this: a repeat join throws
        ArgumentException.

        Without the pre-check, a rebuild would trip over ITS OWN past
        success.
        """
        cs = _cs()
        pre = cs.index("JoinGeometryUtils.AreElementsJoined")
        act = cs.index("JoinGeometryUtils.JoinGeometry(")
        self.assertLess(pre, act,
                        "JoinGeometry зовётся раньше, чем спрошено "
                        "AreElementsJoined — повторный прогон бросит")
        self.assertIn("if (!__jpre_j1)", cs,
                      "эффект обязан быть под условием «ещё не соединены»")

    def test_the_pair_of_one_element_is_a_named_refusal(self):
        cs = _cs()
        self.assertIn("__ja_j1.Id == __jb_j1.Id", cs)
        self.assertIn("один и тот же элемент", cs)

    def test_both_failures_are_typed_refusals_not_silence(self):
        cs = _cs()
        self.assertIn('"соединить не удалось (JoinGeometry), причина не «cannot be joined»: "', cs)
        self.assertIn('"не удалось спросить, соединены ли элементы: "', cs)
        self.assertNotIn("JoinGeometry(doc, __ja_j1, __jb_j1); } catch { }", cs,
                         "пустой catch вокруг ЭФФЕКТА: отказ стал бы "
                         "неотличим от успеха")

    def test_cannot_be_joined_is_a_named_outcome_not_a_generic_crash(self):
        """25.08.2026, live measurement 13A-RD-AR-K2_v33 (Revit 2023,
        CLAUDE.md):

        `ArgumentException` carries ONE of several Autodesk messages —
        "already joined" is cut off by the pre-check FURTHER UP the stack,
        and "cannot be joined" is the measured MAIN case for this op (a
        pair built by a prior, already-committed transaction that honestly
        shares no face). Before the fix both outcomes were WRAPPED INTO ONE
        text — "emission is broken" and "a fact about the pair's geometry"
        were indistinguishable to any reader of the receipt.
        """
        cs = _cs()
        self.assertIn(
            'IndexOf("cannot be joined", StringComparison.OrdinalIgnoreCase)',
            cs, "различитель обязан читать САМО сообщение Revit — другого "
                "носителя у ArgumentException нет")
        self.assertIn("НЕ ИМЕЮТ ОБЩЕЙ ГРАНИ", cs,
                      "«cannot be joined» обязан читаться как факт о паре, "
                      "а не как безымянный сбой")
        # The named outcome sits BEFORE the general one in the text — an
        # if/else branch, not two independent catches: the order in the
        # emission guarantees this.
        self.assertLess(
            cs.index("НЕ ИМЕЮТ ОБЩЕЙ ГРАНИ"),
            cs.index("причина не «cannot be joined»"),
            "именованная ветка обязана стоять в if, а общая — в else")

    def test_the_receipt_separates_joined_from_already_joined(self):
        """Two DIFFERENT facts about the move at one document state."""
        cs = _cs()
        self.assertIn('__rb["joined_ids"]', cs)
        self.assertIn('__rb["already_joined"] = __jpre_j1;', cs)


class TheWitnessAsksExactlyWhatTheOpPromised(unittest.TestCase):

    def test_the_postcondition_rereads_the_same_relation(self):
        cs = _cs()
        self.assertEqual(cs.count("JoinGeometryUtils.AreElementsJoined"), 2,
                         "один вызов до эффекта (предпроверка), один после "
                         "(свидетель) — ни прокси, ни габарита")
        self.assertIn("НЕ соединены после JoinGeometry", cs)

    def test_the_certificate_proves_it_on_every_version(self):
        op = _prog()["ops"][0]
        for ver in ("2021", "2022", "2023", "2024", "2025", "2026"):
            cert = translation_cert.certify_op(op, ver)
            self.assertTrue(cert.proven, f"{ver}: {cert.gaps}")
            self.assertEqual(cert.vacuous, (),
                             f"{ver}: доказуемо мёртвый __post.Add")

    def test_the_lowering_contract_is_complete(self):
        """Without it, the compiler refuses with `KIR-L007` before any
        Revit is involved."""
        self.assertTrue(op_contract.contract_for("join_elements").digest)


class TheReverseStoryIsNamedHonestly(unittest.TestCase):

    def test_it_is_composed_not_an_impossibility_and_not_a_capture_gap(self):
        """22.08: the mode was changed by a MEASUREMENT, not a mood.

        `state_transition` would send you off to prove impossibility where
        the relation is read directly. `capture_gap` would send you off to
        fix a read that has been riding along since 18.08 07:03. `direct`
        would grant permission to place an L1 NODE, and executing that
        permission crashes the fold: the relation has no element of its
        own, and `fold_document` calls such a node `invented`.
        """
        c = reverse_contract._CONTRACTS["join_elements"]
        self.assertEqual(c.mode, reverse_contract.ReverseMode.COMPOSED)
        self.assertIn("lift_joins", c.entrypoints)
        self.assertEqual(c.representation_ops, ("join_elements",))
        self.assertFalse(
            c.decided_on or c.due,
            "дату и срок несёт ТОЛЬКО capture_gap — остальные моды описывают, "
            "чем обратный ход ЯВЛЯЕТСЯ, а не чего он пока не умеет")

    def test_the_reason_no_longer_claims_capture_is_blind(self):
        """The guarding test aimed at exactly the phrase that lied for four
        days."""
        c = reverse_contract._CONTRACTS["join_elements"]
        self.assertNotIn("zero occurrences", c.reason)
        self.assertNotIn("nothing in", c.reason)
        for member in ("GetJoinedElements", "IsWallJoinAllowedAtEnd",
                       "get_ElementsAtJoin"):
            self.assertIn(member, c.reason,
                          "родов три, и запись обязана назвать все три")

    def test_the_limitation_names_the_relation_that_must_not_be_confused(self):
        c = reverse_contract._CONTRACTS["join_elements"]
        self.assertIn("IsWallJoinAllowedAtEnd", c.limitation,
                      "захват, прочитавший РАЗРЕШЕНИЕ вместо ФАКТА, вернул "
                      "бы здание, соединённое не там")


class TheProgramCompilesEverywhere(unittest.TestCase):

    def test_kir_accepts_it_on_all_six_versions(self):
        for ver in ("2021", "2022", "2023", "2024", "2025", "2026"):
            out = compiler.compile_program(_prog(), ver,
                                           snapshot=GROUND_SNAPSHOT)
            self.assertTrue(out.ok,
                            f"{ver}: {[d.code for d in (out.diagnostics or [])]}")
            self.assertIn("JoinGeometryUtils.JoinGeometry(", out.csharp)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
