"""What `verified.py` can and cannot promise, measured rather than asserted.

`test_verified.py` calls itself adversarial (V1: "direct Proof / Verified with
fake proof -> ForgeryError").  It tries two attacks and both are refused:
`Proof(kind=..., subject_hash="x", evidence=())` with NO token, and
`Verified(..., proof="not a proof")`.  Neither is the attack that works, so the
suite proves the lock rejects a WRONG key -- never that the key is out of
reach, which is the module's actual claim.

MEASURED 2026-08-11 on this box, every attack executed from OUTSIDE the module
in a process that merely has the right to import it:

    import kukai.ir.decompile.verified as V
    V.Proof(kind="round_trip", subject_hash="a"*40, evidence=(),
            _token=V._MINT_KEY)                                   -> SUCCEEDS
    ... _token=vars(V)["_MINT_KEY"]                               -> SUCCEEDS
    ... _token=V.prove_round_trip.__globals__["_MINT_KEY"]        -> SUCCEEDS
    object.__new__(V.Proof) + object.__setattr__                  -> SUCCEEDS
    V.Verified(value=..., proof=<forged>, subject_hash="a"*40)    -> SUCCEEDS

Moving the sentinel into a closure -- the repair that looks obvious -- was
measured too, on an identical toy guard:

    ClosureProof.__init__.__closure__[i].cell_contents            -> SUCCEEDS
    object.__new__(ClosureProof)                                  -> SUCCEEDS

The second line is why NO placement of the sentinel can work: `object.__new__`
never calls `__init__`, so every constructor-guard discipline is bypassed
regardless of where the secret lives.  Unforgeability against a process that
may import the module is therefore not attainable in Python, and a closure
would have been a delay, not a fix.

WHAT THE GUARD DOES BUY, and it is real: construction WITHOUT the token is
refused loudly.  That is protection from ACCIDENTAL construction -- a caller
who writes `Proof(...)` instead of routing through a `prove_*` verifier gets a
typed `ForgeryError` rather than a silent claim.  Two further properties
survive untouched, because neither depends on secrecy: `ProofMismatchError`
binds a proof to its subject, so a LEGITIMATE proof cannot be replayed onto
another building; and each `prove_*` verifier RUNS a real offline check, so a
proof obtained honestly means the check really passed.

The module keeps those.  What it must stop doing is claiming the one property
the language cannot give, and stamping `"verified": true` into JSON that
leaves the process with nothing behind it -- a forgeable flag crossing a
boundary is worse than no flag, by the same rule that makes a fingerprint
matching the wrong type worse than an absent one.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_verified_forge_queue.jsonl"))

import kukai.ir.decompile.verified as verified_module  # noqa: E402
from kukai.ir.decompile.verified import (  # noqa: E402
    ForgeryError,
    Proof,
    ProofMismatchError,
    Verified,
)


class TheModuleStatesItsRealSecurityModelTests(unittest.TestCase):
    """REFUTING.  The module claimed a property the language cannot provide.

    The claim was "there is no path to a `Verified[T]` that bypasses a
    verifier".  Five paths were measured, above.  A module that cannot keep a
    promise must not make it; what it CAN keep has to be named instead, and
    named in code so the next reader is stopped by a constant rather than by a
    paragraph.
    """

    def test_the_protection_level_is_declared_and_modest(self) -> None:
        self.assertEqual(
            verified_module.PROTECTION, "accidental_construction_only")

    def test_the_defeating_attacks_are_named_in_the_module(self) -> None:
        # A closed list: adding a sixth bypass forces a decision instead of
        # quietly widening an unstated claim.
        self.assertIn("module_attribute", verified_module.KNOWN_BYPASSES)
        self.assertIn("function_globals", verified_module.KNOWN_BYPASSES)
        self.assertIn("object_new", verified_module.KNOWN_BYPASSES)
        self.assertIn("closure_cell_contents", verified_module.KNOWN_BYPASSES)


class TheAttackThatWorksTests(unittest.TestCase):
    """PINS.  The suite must try the attack that works, not its neighbours.

    These assertions record the true model.  If someone later believes they
    have made the wrapper unforgeable, one of them will fail and force the
    question rather than let a false claim return.
    """

    def test_the_sentinel_is_readable_from_outside_the_module(self) -> None:
        token = getattr(verified_module, "_MINT_KEY")
        self.assertIsNotNone(token)
        forged = Proof(
            kind="round_trip", subject_hash="a" * 40,
            evidence=("forged",), _token=token)
        self.assertEqual(forged.kind, "round_trip")

    def test_a_forged_proof_wraps_any_value(self) -> None:
        token = getattr(verified_module, "_MINT_KEY")
        forged = Proof(
            kind="round_trip", subject_hash="b" * 40,
            evidence=("forged",), _token=token)
        wrapped = Verified(
            value={"anything": 1}, subject_hash="b" * 40, proof=forged)
        self.assertEqual(wrapped.unwrap(), {"anything": 1})

    def test_object_new_bypasses_every_constructor_guard(self) -> None:
        # The decisive one: __init__ is never called, so no placement of the
        # sentinel -- module attribute, closure, metaclass -- can matter.
        raw = object.__new__(Proof)
        object.__setattr__(raw, "kind", "round_trip")
        object.__setattr__(raw, "subject_hash", "c" * 40)
        object.__setattr__(raw, "evidence", ())
        object.__setattr__(raw, "_token", None)
        self.assertIsInstance(raw, Proof)


class WhatSurvivesTests(unittest.TestCase):
    """The three properties that do NOT depend on secrecy, and so are real."""

    def test_construction_without_the_token_is_refused(self) -> None:
        with self.assertRaises(ForgeryError):
            Proof(kind="round_trip", subject_hash="x" * 40, evidence=())

    def test_a_non_proof_is_refused(self) -> None:
        with self.assertRaises(ForgeryError):
            Verified(value=1, subject_hash="x" * 40,
                     proof="not a proof")  # type: ignore[arg-type]

    def test_a_proof_cannot_be_replayed_onto_another_subject(self) -> None:
        token = getattr(verified_module, "_MINT_KEY")
        proof = Proof(kind="round_trip", subject_hash="d" * 40,
                      evidence=(), _token=token)
        with self.assertRaises(ProofMismatchError):
            Verified(value=1, subject_hash="e" * 40, proof=proof)


class SerializationCarriesNoTrustTests(unittest.TestCase):
    """REFUTING.  `to_dict` stamped a trust flag no reader could re-derive.

    The module's own discipline note promised "serialization does NOT carry
    trust -- `from_dict` re-proves rather than believing a stored flag (Р7)",
    and `test_verified.py`'s header repeats it as V7.  Measured: there is NO
    `from_dict` anywhere in the module (grep: zero), while `Verified.to_dict`
    emits `"verified": True`.  Half a contract, and the wrong half -- the
    forgeable direction shipped and the re-proving direction never existed.

    Nor could it: `to_dict` stores `subject_hash` and evidence STRINGS, not the
    library and tree a `prove_*` verifier needs, so re-proving from the payload
    alone is impossible by construction.  The promise was unimplementable as
    written, which is why the flag goes rather than a reader arriving.
    """

    def _forged(self):
        token = getattr(verified_module, "_MINT_KEY")
        proof = Proof(kind="round_trip", subject_hash="f" * 40,
                      evidence=("e",), _token=token)
        return Verified(value={"a": 1}, subject_hash="f" * 40, proof=proof)

    def test_no_boolean_trust_flag_leaves_the_process(self) -> None:
        payload = self._forged().to_dict()
        self.assertNotIn("verified", payload)

    def test_the_payload_says_trust_is_not_carried(self) -> None:
        payload = self._forged().to_dict()
        self.assertEqual(payload["trust"], "not_carried")

    def test_the_evidence_still_travels(self) -> None:
        payload = self._forged().to_dict()
        self.assertEqual(payload["subject_hash"], "f" * 40)
        self.assertEqual(payload["proof"]["kind"], "round_trip")

    def test_there_is_still_no_reproving_reader(self) -> None:
        # Pinned deliberately: if someone adds `from_dict`, this fails and they
        # must decide what it re-proves and with which subject in hand.
        self.assertFalse(hasattr(Verified, "from_dict"))
        self.assertFalse(hasattr(Proof, "from_dict"))


if __name__ == "__main__":
    unittest.main()
