"""OPERATION IDENTITY WAS TAKING THE TURN FROM TWO SOURCES AT ONCE (RT-29).

The subject is `kir/operations/protocol.py`. `derive_action_id` substituted the literal
`'turn-unknown'` when `turn_id` was empty, while `OperationIdentity.for_payload` immediately
placed a fresh random `uuid4` into the `turn_id` FIELD. Two states were being mixed
silently, and mixed at the one single place where the bridge decides whether "this is a new
action or a repeat of an old one".

MEASUREMENT BEFORE THE FIX (04.09.2026), two calls to
`for_payload(turn_id="", tool_call_id="c1", tool_name="t", method="m",
params={"x": 1})`:

    turn_id       DIFFERENT    (f856dc63… and b10e6f9d…)
    action_id     THE SAME
    operation_id  THE SAME
    control: with a named turn_id="T1" the action_id differs — the field works

That is, two turns, DECLARED different by the very value of the field itself, are indistinguishable by
operation identity.

WHY THE FIX IS A REFUSAL, AND NOT "LET THE UUID PARTICIPATE IN THE DERIVATION"
------------------------------------------------------------
The second path fixes the merging of two turns at the cost of SPLITTING one apart: a genuine
redelivery of the same nameless turn would get a fresh `action_id` and
`operation_id`, and the building would get built TWICE. This is exactly what is forbidden, verbatim, by the
owner of this contract (`kukai/api/bridge_protocol.py`: «never acquire a fresh random
operation id and execute twice»). Only the CALLER can tell "a new turn" apart from "a repeat" —
it has a retry policy; here there is no such knowledge by
construction, and it must not be invented.

The cost to live callers is zero, measured by name: `acceptance_runtime` supplies
`binding.run_id`, `bridge_protocol` supplies `artifact_binding.run_id` or
`ledger.turn_id if ledger is not None else str(uuid.uuid4())`, `admin_kir` supplies
`uuid.uuid4().hex`. Not a single live path relied on the substitution.

THE MAIN TEST HERE IS `test_the_field_and_the_derivation_read_the_same_turn`.
It is not about emptiness, but about a PROPERTY: whatever is written into the `turn_id` field is
exactly what `action_id` is derived from. The old code violated it precisely on a nameless turn, and
would violate it again with any new substitution — whatever literal were chosen.
"""
from __future__ import annotations

import unittest

from kir.operations.protocol import (OperationIdentity, derive_action_id,
                                     derive_operation_id)

ВЫЗОВ = dict(tool_call_id="c1", tool_name="t", method="m", params={"x": 1})


class ANamelessTurnIsARefusal(unittest.TestCase):

    def test_an_empty_turn_is_refused_not_invented(self) -> None:
        """An empty turn is a refusal. `_bounded_id` right next to it could do this from the very start,
        and the substitution was the ONLY thing stopping it from firing."""
        with self.assertRaises(ValueError) as поймано:
            OperationIdentity.for_payload(turn_id="", **ВЫЗОВ)
        self.assertIn("turn_id", str(поймано.exception))

    def test_whitespace_is_not_a_name_either(self) -> None:
        """A blank is not a turn name: `_bounded_id` trims the edges, and after trimming
        the same emptiness remains. Otherwise the refusal could be dodged with a single character."""
        with self.assertRaises(ValueError):
            OperationIdentity.for_payload(turn_id="   ", **ВЫЗОВ)

    def test_derive_action_id_refuses_it_too(self) -> None:
        """The refusal sits at the DERIVATION, not just at the assembly of the carrier: the owner calls
        `derive_action_id` directly (`kukai/api/admin_kir.py`), and a substitution
        left there would bring the defect back through a second door."""
        with self.assertRaises(ValueError):
            derive_action_id("", "c1", "t")

    def test_control_a_named_turn_still_passes(self) -> None:
        """FAIL CONTROL in reverse: ONE condition is changed — the turn is NAMED — and everything
        must work. Otherwise the "fix" would just be a prohibition."""
        ид = OperationIdentity.for_payload(turn_id="T1", **ВЫЗОВ)
        self.assertEqual(ид.turn_id, "T1")
        self.assertEqual(len(ид.action_id), 36)
        self.assertEqual(len(ид.payload_hash), 64)


class TwoTurnsAreTwoIdentities(unittest.TestCase):

    def test_two_named_turns_never_share_an_identity(self) -> None:
        a = OperationIdentity.for_payload(turn_id="T1", **ВЫЗОВ)
        b = OperationIdentity.for_payload(turn_id="T2", **ВЫЗОВ)
        self.assertNotEqual(a.turn_id, b.turn_id)
        self.assertNotEqual(a.action_id, b.action_id)
        self.assertNotEqual(a.operation_id, b.operation_id)

    def test_a_redelivery_of_one_turn_keeps_its_identity(self) -> None:
        """The second half of the module's law: «identical redelivery changes only
        attempt_id». It is precisely the argument against generating a uuid inside the derivation."""
        a = OperationIdentity.for_payload(turn_id="T1", **ВЫЗОВ)
        b = OperationIdentity.for_payload(turn_id="T1", **ВЫЗОВ)
        self.assertEqual(a.action_id, b.action_id)
        self.assertEqual(a.operation_id, b.operation_id)
        self.assertEqual(a.payload_hash, b.payload_hash)

    def test_the_field_and_the_derivation_read_the_same_turn(self) -> None:
        """🔴 A PROPERTY, NOT A SPECIAL CASE, AND IT CATCHES ANY FUTURE SUBSTITUTION.

        The law: a turn is named ONCE — whatever is written into the `turn_id` field is
        exactly what `action_id` is derived from. It is checked on EVERY turn that the
        module AGREED to accept; a refusal here is a legitimate answer, while accepting
        a discrepancy is not.

        The old code took the turn from DIFFERENT sources (`uuid.uuid4()` in the field,
        `'turn-unknown'` in the derivation) and on a nameless turn produced exactly this
        discrepancy — this test is red on it. It will be red on any
        new literal substitution too, whatever it might be."""
        for ход in ("T1", "run-42", "0" * 128, "", "   ", "turn-unknown"):
            try:
                ид = OperationIdentity.for_payload(turn_id=ход, **ВЫЗОВ)
            except ValueError:
                continue          # the refusal is an honest answer, there is no discrepancy
            self.assertEqual(
                ид.action_id,
                derive_action_id(ид.turn_id, "c1", "t"),
                f"поле и вывод читают РАЗНЫЙ ход при turn_id={ход!r} "
                f"— это и был RT-29")
            self.assertEqual(
                ид.operation_id,
                derive_operation_id(ид.action_id, "m", ид.payload_hash))

    def test_a_turn_literally_named_turn_unknown_is_just_a_turn(self) -> None:
        """A second, smaller branch of the same defect: while the literal stood in the derivation,
        a turn NAMED `turn-unknown` received the identity of a nameless one. Now it is an
        ordinary named turn and coincides with nothing."""
        назван = OperationIdentity.for_payload(turn_id="turn-unknown", **ВЫЗОВ)
        другой = OperationIdentity.for_payload(turn_id="T1", **ВЫЗОВ)
        self.assertNotEqual(назван.action_id, другой.action_id)
        with self.assertRaises(ValueError):
            OperationIdentity.for_payload(turn_id="", **ВЫЗОВ)


if __name__ == "__main__":
    unittest.main()
