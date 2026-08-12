"""Typed honesty: ``Verified[T]`` guarded against ACCIDENTAL construction.

WITHDRAWN 2026-08-11, WITH THE MEASUREMENT THAT WITHDREW IT.  This module used
to open with "``Verified[T]`` unconstructible without a proof" and to state an
"Invariant UNFORGEABLE: there is no path to a ``Verified[T]`` that bypasses a
verifier -- tested adversarially".  That promise is not one Python can keep,
and it took two lines from outside the module to break.  Every attack below was
EXECUTED on 2026-08-11 from a process whose only privilege was the right to
import this file:

  * ``Proof(..., _token=verified._MINT_KEY)``                      -> SUCCEEDS
  * ``... _token=vars(verified)["_MINT_KEY"]``                     -> SUCCEEDS
  * ``... _token=prove_round_trip.__globals__["_MINT_KEY"]``       -> SUCCEEDS
  * ``object.__new__(Proof)`` + ``object.__setattr__``             -> SUCCEEDS
  * ``Verified(value=..., proof=<forged>, subject_hash=...)``      -> SUCCEEDS

Moving the sentinel into a CLOSURE is the repair that looks obvious, and it was
measured on an identical toy guard rather than assumed:
``Guard.__init__.__closure__[i].cell_contents`` hands the secret over, and
``object.__new__(Guard)`` skips ``__init__`` entirely.  That second line is the
general result: **no placement of a sentinel can matter, because a constructor
guard can be bypassed without calling the constructor.**  A closure would have
been a delay, not a fix.

The suite did not catch this because it tried the neighbouring doors: V1
constructs ``Proof`` with NO token and ``Verified`` with the string
``"not a proof"``.  Both are refused, so the tests proved the lock rejects a
WRONG key -- never that the key is out of reach, which is what the claim
actually said.  A check signing an axis it did not read, on the one axis this
module exists for.

WHAT IS TRUE, and it is stated as the whole of it.  Three properties survive,
and not one of them depends on secrecy:

1. **Accidental construction is refused, loudly.**  A caller who writes
   ``Proof(...)`` instead of routing through a ``prove_*`` verifier gets a
   typed ``ForgeryError``, not a silent claim.  This is the guard's real and
   only security value, and ``PROTECTION`` below says so in code.
2. **A proof is bound to its subject.**  ``ProofMismatchError`` stops a
   LEGITIMATE proof from being replayed onto another building.  That is about
   misapplication, not forgery, so an attacker was never its subject.
3. **A verifier RUNS its check.**  Each ``prove_*`` calls a real offline
   assertion and mints nothing when it raises, so a proof obtained honestly
   does mean the check passed.

Against a hostile process that may import this module there is no defence here
and there cannot be one in this language; deployment-level isolation is the
only place that question can be answered.  Do not re-add the word
"unforgeable".

The existing honesty contract carries verdicts as VALUES — ``EquivalenceClaim``
has a ``state`` field anyone can set to ``VERIFIED`` without having verified
anything.  That is forgeable.  This wave makes "verified" unforgeable BY
CONSTRUCTION: a ``Verified[T]`` wrapper whose only constructor requires a
``Proof``, and a ``Proof`` that can only be minted by an actual verifier that
RUNS a real offline check (the assert_* functions of waves 1/5/6/9/10 and the
translation certificate of wave 2).

Mechanics (a Python analog of a witness / phantom type, enforced at runtime):

* ``Proof.__init__`` requires a module-level capability sentinel, so an
  ACCIDENTAL ``Proof(...)`` raises ``ForgeryError``.  The sentinel is private
  by convention only; see the measured bypasses at the top of this file.
* Each ``prove_*`` verifier RUNS the real check (e.g. ``assert_round_trip``);
  if it does not raise, it mints a ``Proof``; otherwise the check's exception
  propagates and NO proof is produced — there is no "claim without running".
* ``Verified[T]`` requires a ``Proof`` whose ``subject_hash`` equals the
  subject of the value, so a proof for building X cannot be re-glued onto
  building Y (a replay forgery) — ``ProofMismatchError``.

Discipline (forks in TYPED_HONESTY_SPEC.md): inert, additive, opt-in
(``verified_enabled()`` default OFF; the honesty module is untouched); frozen
L0 untouched.

SERIALIZATION CARRIES NO TRUST, and that clause used to describe half a
contract.  It promised "``from_dict`` re-proves rather than believing a stored
'verified' flag (Р7)", and ``test_verified.py``'s header repeats it as V7.
Measured 2026-08-11: there is NO ``from_dict`` anywhere in this module, while
``Verified.to_dict`` stamped ``"verified": True`` into the payload.  The
forgeable direction shipped and the re-proving direction never existed.

It could not have existed as written: ``to_dict`` carries ``subject_hash`` and
evidence STRINGS, never the library and tree a ``prove_*`` verifier needs, so
re-proving from the payload alone is impossible by construction.  So the flag
goes rather than a reader arriving -- a boolean nothing downstream can
re-derive is worse crossing a process boundary than no boolean at all.  The
payload now says ``"trust": "not_carried"`` and keeps the evidence, so a reader
must re-run a verifier with the real subject in hand to trust anything.
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

# A unique, module-level sentinel.  It is not exported, and that is the whole
# of its strength: "private" here is a naming convention, not a capability.
# Measured bypasses are listed in KNOWN_BYPASSES below.
_MINT_KEY = object()

#: What this guard actually protects against.  Named in code, not in prose, so
#: a future reader is stopped by a constant rather than by a paragraph.
PROTECTION = "accidental_construction_only"

#: CLOSED list of measured ways to obtain a Proof without a verifier
#: (2026-08-11, executed from outside the module).  It is closed on purpose:
#: a sixth entry must force a decision about PROTECTION rather than quietly
#: widen an unstated claim.
KNOWN_BYPASSES = (
    "module_attribute",          # verified._MINT_KEY
    "module_vars",               # vars(verified)["_MINT_KEY"]
    "function_globals",          # prove_round_trip.__globals__["_MINT_KEY"]
    "object_new",                # object.__new__(Proof) -- skips __init__
    "closure_cell_contents",     # would defeat the "move it to a closure" fix
)


@dataclass(frozen=True, slots=True)
class Proof:
    """A witness that a specific offline check passed.

    Construct ONLY via a ``prove_*`` verifier in this module; a direct
    ``Proof(...)`` without the mint key raises ``ForgeryError``.  That guard
    stops an ACCIDENT, not an adversary -- see ``PROTECTION`` and
    ``KNOWN_BYPASSES``.  The word "unforgeable" was withdrawn on 2026-08-11
    after five bypasses were executed from outside this module.
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
    """A value carrying the proof that it was verified.

    ``subject_hash`` names the artifact the value is a verdict ABOUT (a tree
    hash, a transition hash, ...).  The constructor requires a ``Proof`` whose
    ``subject_hash`` equals it; otherwise the wrapper cannot exist — a proof for
    one subject cannot verify a verdict about another.  That binding is real
    and does not rest on secrecy: it stops a LEGITIMATE proof from being
    replayed onto another building.  It does NOT make the wrapper unforgeable,
    and the "exists IFF a real check passed" reading it used to carry was
    withdrawn with the measurement at the top of this file.
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
        # NO boolean trust flag.  Nothing downstream can re-derive it (there
        # is no from_dict, and the payload does not carry the subject a
        # verifier would need), so shipping `"verified": true` would send a
        # forgeable claim across a process boundary with nothing behind it.
        return {"value": value_dict, "subject_hash": self.subject_hash,
                "proof": self.proof.to_dict(), "trust": "not_carried"}


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
    "KNOWN_BYPASSES",
    "PROTECTION",
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
