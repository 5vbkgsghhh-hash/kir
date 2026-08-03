"""Property tests for typed honesty — Verified[T] unforgeable (verified.py).

The heart is adversarial: a Verified/Proof must be impossible to construct
without a real check having run, and a proof for one subject must not verify a
verdict about another.

Numbering matches TYPED_HONESTY_SPEC §5:
  V1 unconstructible (direct Proof / Verified with fake proof -> ForgeryError)
  V2 honest path (prove_* -> Proof -> verify_equivalence -> Verified)
  V3 the check really runs (broken input -> propagates, no proof)
  V4 subject-bound (proof for X + verdict about Y -> ProofMismatchError)
  V5 every verifier honest (correct -> proof; broken -> raises)
  V6 Verified cannot carry FAILED
  V7 serialization does not carry trust (from_dict re-proves)
  V8 determinism (same subject -> same subject_hash; cross-process)
  V9 flag default OFF
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_verified_queue.jsonl"))

from kukai.ir.decompile.component import (  # noqa: E402
    ComponentLibrary,
    build_library,
)
from kukai.ir.decompile.honesty import (  # noqa: E402
    EquivalenceClaim,
    EquivalenceScope,
    EquivalenceState,
)
from kukai.ir.decompile.merkle import build_index  # noqa: E402
from kukai.ir.decompile.rebuild import delta_between  # noqa: E402
from kukai.ir.decompile.journal import new_journal, commit_trees  # noqa: E402
from kukai.ir.decompile.merge3 import merge3_trees  # noqa: E402
from kukai.ir.decompile.verified import (  # noqa: E402
    ForgeryError,
    HonestyTypeError,
    Proof,
    ProofMismatchError,
    Verified,
    prove_journal_integrity,
    prove_merge_clean,
    prove_round_trip,
    prove_transition,
    verified_enabled,
    verify_equivalence,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _cluster_building,
    _fold,
    _grid_building,
)


def _tree(floors=3):
    return _fold(_grid_building(floors=floors))


def _lib_and_tree(floors=3):
    tree = _tree(floors)
    return build_library(build_index(tree, label="a")), tree


def _proof(floors=3):
    lib, tree = _lib_and_tree(floors)
    return prove_round_trip(lib, tree), lib, tree


class Unforgeable(unittest.TestCase):
    def test_v1_direct_proof_is_forgery(self) -> None:
        with self.assertRaises(ForgeryError):
            Proof(kind="round_trip", subject_hash="x", evidence=())

    def test_v1_verified_with_non_proof_is_forgery(self) -> None:
        claim = EquivalenceClaim.unverified(EquivalenceScope.FORM)
        with self.assertRaises(ForgeryError):
            Verified(value=claim, subject_hash="x",
                     proof="not a proof")  # type: ignore[arg-type]

    def test_v4_subject_mismatch_is_rejected(self) -> None:
        proof, _lib, _tree = _proof()
        claim = EquivalenceClaim.unverified(EquivalenceScope.FORM)
        with self.assertRaises(ProofMismatchError):
            Verified(value=claim, subject_hash="deadbeef", proof=proof)

    def test_v4_foreign_proof_cannot_verify_other_subject(self) -> None:
        # A proof about building A, bound to a Verified declaring building B's
        # subject, must fail.
        proof_a, _la, _ta = _proof(floors=3)
        from kukai.ir.decompile.merkle import merkle_hash
        other_subject = merkle_hash(_tree(floors=2))
        self.assertNotEqual(proof_a.subject_hash, other_subject)
        claim = EquivalenceClaim.unverified(EquivalenceScope.FORM)
        with self.assertRaises(ProofMismatchError):
            Verified(value=claim, subject_hash=other_subject, proof=proof_a)


class HonestPath(unittest.TestCase):
    def test_v2_prove_then_verify(self) -> None:
        proof, _lib, _tree = _proof()
        claim = EquivalenceClaim.unverified(EquivalenceScope.FORM)
        verified = verify_equivalence(claim, proof)
        self.assertIsInstance(verified, Verified)
        self.assertEqual(verified.value.state, EquivalenceState.VERIFIED)
        self.assertEqual(verified.proven_by, "round_trip")
        self.assertEqual(verified.unwrap().scope, EquivalenceScope.FORM)

    def test_v3_broken_input_yields_no_proof(self) -> None:
        # A one-floor building has singletons; dropping one breaks round-trip.
        tree = _tree(1)
        lib = build_library(build_index(tree, label="a"))
        self.assertTrue(lib.singletons_leaves)
        broken = ComponentLibrary(
            definitions=lib.definitions, place_ops=lib.place_ops,
            singletons_leaves=lib.singletons_leaves[:-1])
        from kukai.ir.decompile.component import ComponentRoundTripError
        with self.assertRaises(ComponentRoundTripError):
            prove_round_trip(broken, tree)


class EveryVerifier(unittest.TestCase):
    def test_v5_transition_proof(self) -> None:
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_grid_building(floors=3, name="B", stretch_wall_on_floor=1))
        program = delta_between(a, b)
        proof = prove_transition(program, a, b)
        self.assertEqual(proof.kind, "transition")
        # A program that does not transition a into c -> the check raises.
        c = _fold(_grid_building(floors=3, name="C", drop_wall_on_floor=2))
        from kukai.ir.decompile.rebuild import RebuildError
        with self.assertRaises(RebuildError):
            prove_transition(program, a, c)

    def test_v5_journal_integrity_proof(self) -> None:
        a = _fold(_grid_building(floors=3, name="R0"))
        b = _fold(_grid_building(floors=3, name="R1", stretch_wall_on_floor=1))
        journal = commit_trees(new_journal(a), a, b)
        proof = prove_journal_integrity(journal)
        self.assertEqual(proof.kind, "journal")

    def test_v5_merge_clean_proof(self) -> None:
        base = _fold(_grid_building(floors=3, name="O"))
        ours = _fold(_grid_building(
            floors=3, name="A", extra_furniture_on_floor=0))
        theirs = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2))
        clean = merge3_trees(base, ours, theirs)
        self.assertTrue(clean.clean)
        proof = prove_merge_clean(clean)
        self.assertEqual(proof.kind, "merge")

    def test_v5_merge_with_conflict_yields_no_proof(self) -> None:
        # A conflicted merge cannot be proven clean.
        from kukai.ir.decompile.tests.test_merge3 import _one_wall_building
        base = _one_wall_building(6000.0, "O")
        ours = _one_wall_building(6500.0, "A")
        theirs = _one_wall_building(7000.0, "B")
        conflicted = merge3_trees(base, ours, theirs, policy="ours")
        self.assertFalse(conflicted.clean)
        with self.assertRaises(HonestyTypeError):
            prove_merge_clean(conflicted)


class FailedVerdict(unittest.TestCase):
    def test_v6_failed_claim_cannot_be_verified(self) -> None:
        proof, _lib, _tree = _proof()
        failed = EquivalenceClaim(
            scope=EquivalenceScope.FORM,
            state=EquivalenceState.FAILED, detail="did not verify")
        with self.assertRaises(ForgeryError):
            verify_equivalence(failed, proof)


class SerializationTrust(unittest.TestCase):
    def test_v7_dict_has_no_constructible_trust(self) -> None:
        proof, _lib, _tree = _proof()
        claim = EquivalenceClaim.unverified(EquivalenceScope.FORM)
        verified = verify_equivalence(claim, proof)
        payload = verified.to_dict()
        # The dict records verified:true for audit, but its proof dict cannot be
        # turned back into a Proof (no mint key) — trust does not survive
        # serialization.
        self.assertTrue(payload["verified"])
        with self.assertRaises(ForgeryError):
            Proof(**{k: v for k, v in payload["proof"].items()})


class Determinism(unittest.TestCase):
    def test_v8_same_subject_same_hash(self) -> None:
        p1, _l1, _t1 = _proof(3)
        p2, _l2, _t2 = _proof(3)
        self.assertEqual(p1.subject_hash, p2.subject_hash)

    def test_v8_different_subject_different_hash(self) -> None:
        p1, _l1, _t1 = _proof(3)
        p2, _l2, _t2 = _proof(2)
        self.assertNotEqual(p1.subject_hash, p2.subject_hash)


class Flag(unittest.TestCase):
    def test_v9_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_VERIFIED", None)
        try:
            self.assertFalse(verified_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_VERIFIED"] = previous

    def test_v9_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_VERIFIED")
        os.environ["KUKAI_IR_VERIFIED"] = "1"
        try:
            self.assertTrue(verified_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_VERIFIED"]
            else:
                os.environ["KUKAI_IR_VERIFIED"] = previous


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
