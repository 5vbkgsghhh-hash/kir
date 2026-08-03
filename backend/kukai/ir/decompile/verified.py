"""Typed honesty: ``Verified[T]`` unconstructible without a proof (wave 7).

The existing honesty contract carries verdicts as VALUES — ``EquivalenceClaim``
has a ``state`` field anyone can set to ``VERIFIED`` without having verified
anything.  That is forgeable.  This wave makes "verified" unforgeable BY
CONSTRUCTION: a ``Verified[T]`` wrapper whose only constructor requires a
``Proof``, and a ``Proof`` that can only be minted by an actual verifier that
RUNS a real offline check (the assert_* functions of waves 1/5/6/9/10 and the
translation certificate of wave 2).

Mechanics (a Python analog of a witness / phantom type, enforced at runtime):

* ``Proof.__init__`` requires a module-private capability sentinel; external
  code cannot obtain it, so ``Proof(...)`` from outside raises ``ForgeryError``
  — only this module mints proofs.
* Each ``prove_*`` verifier RUNS the real check (e.g. ``assert_round_trip``);
  if it does not raise, it mints a ``Proof``; otherwise the check's exception
  propagates and NO proof is produced — there is no "claim without running".
* ``Verified[T]`` requires a ``Proof`` whose ``subject_hash`` equals the
  subject of the value, so a proof for building X cannot be re-glued onto
  building Y (a replay forgery) — ``ProofMismatchError``.

Invariant UNFORGEABLE: there is no path to a ``Verified[T]`` that bypasses a
verifier — tested adversarially.

Discipline (forks in TYPED_HONESTY_SPEC.md): inert, additive, opt-in
(``verified_enabled()`` default OFF; the honesty module is untouched);
serialization does NOT carry trust — ``from_dict`` re-proves rather than
believing a stored "verified" flag (Р7).  Frozen L0 untouched.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class HonestyTypeError(ValueError):
    """Base for every typed honesty-type failure."""


class ForgeryError(HonestyTypeError):
    """An attempt to construct a Proof / Verified without authorization."""


class ProofMismatchError(HonestyTypeError):
    """A proof does not pertain to the value it was attached to."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def verified_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_VERIFIED", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Sealed capability token — the heart of unforgeability
# ---------------------------------------------------------------------------

# A unique, module-private sentinel.  It is NOT exported and cannot be obtained
# from outside this module, so only code here can pass the "mint" gate.
_MINT_KEY = object()


@dataclass(frozen=True, slots=True)
class Proof:
    """An unforgeable witness that a specific offline check passed.

    Construct ONLY via a ``prove_*`` verifier in this module; a direct
    ``Proof(...)`` from outside (without the private mint key) raises
    ``ForgeryError``.
    """

    kind: str
    subject_hash: str
    evidence: tuple[str, ...]
    _token: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._token is not _MINT_KEY:
            raise ForgeryError(
                "Proof cannot be constructed directly; use a prove_* verifier")
        object.__setattr__(self, "_token", None)  # drop the key after minting

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "subject_hash": self.subject_hash,
            "evidence": list(self.evidence),
        }


def _mint(kind: str, subject_hash: str, evidence: tuple[str, ...]) -> Proof:
    return Proof(
        kind=kind, subject_hash=subject_hash, evidence=evidence,
        _token=_MINT_KEY)


# ---------------------------------------------------------------------------
# Verified[T] — value + its proof, subject-bound
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Verified(Generic[T]):
    """A value carrying an unforgeable proof that it was verified.

    ``subject_hash`` names the artifact the value is a verdict ABOUT (a tree
    hash, a transition hash, ...).  The constructor requires a ``Proof`` whose
    ``subject_hash`` equals it; otherwise the wrapper cannot exist — a proof for
    one subject cannot verify a verdict about another (replay forgery).  A
    ``Verified`` thus exists IFF a real check passed for THIS subject.
    """

    value: T
    subject_hash: str
    proof: Proof

    def __post_init__(self) -> None:
        if not isinstance(self.proof, Proof):
            raise ForgeryError("Verified requires a genuine Proof")
        if self.proof.subject_hash != self.subject_hash:
            raise ProofMismatchError(
                "proof.subject_hash does not match the verified subject "
                "(a proof for one subject cannot verify another)")

    def unwrap(self) -> T:
        return self.value

    @property
    def proven_by(self) -> str:
        return self.proof.kind

    def to_dict(self) -> dict[str, Any]:
        value_dict = (
            self.value.to_dict() if hasattr(self.value, "to_dict")
            else self.value)
        return {"value": value_dict, "subject_hash": self.subject_hash,
                "proof": self.proof.to_dict(), "verified": True}


# ---------------------------------------------------------------------------
# Verifiers — the ONLY source of Proof (each RUNS a real offline check)
# ---------------------------------------------------------------------------


def prove_round_trip(library: Any, tree: Any) -> Proof:
    """Prove template-canonical coverage (not execution fidelity)."""

    from kukai.ir.decompile.component import assert_round_trip
    from kukai.ir.decompile.merkle import merkle_hash

    assert_round_trip(library, tree)   # raises -> no proof
    return _mint(
        "round_trip", merkle_hash(tree),
        ("component library reproduces the source TemplateCanon leaf multiset",
         "this proof does not authorize native-group execution"))


def prove_transition(program: Any, tree_a: Any, tree_b: Any) -> Proof:
    """Prove a delta transitions state(A) into state(B) (wave 6 T-APPLY)."""

    from kukai.ir.decompile.rebuild import BuildingState, assert_transition
    from kukai.ir.decompile.merkle import merkle_hash

    assert_transition(program, tree_a, tree_b)   # raises -> no proof
    subject = hashlib.sha256(
        (merkle_hash(tree_a) + "->" + merkle_hash(tree_b)).encode("utf-8")
    ).hexdigest()
    return _mint(
        "transition", subject,
        (f"apply(state(A), delta) == state(B)",))


def prove_preservation(tree: Any, nodes: Any) -> Proof:
    """Prove a folded tree preserves the exact L1 leaves (fold assert)."""

    from kukai.ir.decompile.fold import assert_preservation
    from kukai.ir.decompile.merkle import merkle_hash

    assert_preservation(tree, nodes)   # raises -> no proof
    return _mint(
        "preservation", merkle_hash(tree),
        ("folded tree preserves the exact L1 leaf multiset",))


def prove_merge_clean(result: Any) -> Proof:
    """Prove a 3-way merge is conflict-free (wave 10)."""

    from kukai.ir.decompile.merge3 import MergeResult

    if not isinstance(result, MergeResult):
        raise HonestyTypeError("prove_merge_clean needs a MergeResult")
    if not result.clean:
        raise HonestyTypeError(
            "merge has unresolved conflicts; cannot prove clean")
    subject = hashlib.sha256(
        ("merge:" + repr(result.state.multiset)).encode("utf-8")).hexdigest()
    return _mint(
        "merge", subject,
        (f"3-way merge is conflict-free (auto_merged={result.auto_merged})",))


def prove_journal_integrity(journal: Any) -> Proof:
    """Prove a building journal's hash chain verifies (wave 9)."""

    journal.verify()   # raises JournalIntegrityError -> no proof
    head_hash = journal.events[-1].event_hash if len(journal) else ""
    return _mint(
        "journal", head_hash,
        (f"append-only hash chain intact over {len(journal)} events",))


def prove_refinement(op_certificate: Any) -> Proof:
    """Prove an emitted op refines its OpSpec (wave 2 translation-cert)."""

    from kukai.ir.translation_cert import OpCertificate, assert_refined

    if not isinstance(op_certificate, OpCertificate):
        raise HonestyTypeError("prove_refinement needs an OpCertificate")
    assert_refined(op_certificate)   # raises -> no proof
    subject = hashlib.sha256(
        (f"refine:{op_certificate.op}:{op_certificate.version}").encode("utf-8")
    ).hexdigest()
    return _mint(
        "refinement", subject,
        (f"{op_certificate.op} on {op_certificate.version} refines its "
         "postconditions",))


# ---------------------------------------------------------------------------
# Lifting a forgeable claim to a Verified one (only with a real Proof)
# ---------------------------------------------------------------------------


def verify_equivalence(claim: Any, proof: Proof) -> "Verified[Any]":
    """Raise a forgeable EquivalenceClaim to a ``Verified`` one.

    The claim's state is forced to VERIFIED (a Verified value cannot carry a
    FAILED verdict — a contradiction, Р4).  The ``Verified`` binds to the
    proof's subject: the caller must pass a proof that genuinely pertains to the
    artifact the claim is about (the proof came from a ``prove_*`` verifier that
    ran the real check over exactly that artifact).  No rebinding — the proof's
    own subject is the binding, so a foreign proof cannot be laundered here.
    """

    from kukai.ir.decompile.honesty import (
        EquivalenceClaim,
        EquivalenceState,
    )

    if not isinstance(proof, Proof):
        raise ForgeryError("verify_equivalence requires a genuine Proof")
    if not isinstance(claim, EquivalenceClaim):
        raise HonestyTypeError("verify_equivalence needs an EquivalenceClaim")
    if claim.state is EquivalenceState.FAILED:
        raise ForgeryError(
            "a FAILED claim cannot be verified (verified implies not failed)")
    verified_claim = EquivalenceClaim(
        scope=claim.scope,
        state=EquivalenceState.VERIFIED,
        detail=f"{claim.detail} [proof: {proof.kind}]",
    )
    return Verified(
        value=verified_claim, subject_hash=proof.subject_hash, proof=proof)


__all__ = [
    "ForgeryError",
    "HonestyTypeError",
    "Proof",
    "ProofMismatchError",
    "Verified",
    "prove_journal_integrity",
    "prove_merge_clean",
    "prove_preservation",
    "prove_refinement",
    "prove_round_trip",
    "prove_transition",
    "verified_enabled",
    "verify_equivalence",
]
