"""Immutable contract between KIR grounding and authoring emission.

``GroundedProgram`` proves which model-dependent addresses were selected.
``LoweredProgram`` adds every compiler-owned choice that changes the emitted
authoring program: target profile, transaction/postcondition policy, model
guards, template, and deterministic program stamp.  It deliberately does not
store rendered C# fragments; render objects still contain legacy mutable
caches, while this boundary must remain safe to hash and retain as evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kukai.compiler_contract import (
    TargetProfile,
    load_target_profile_manifest,
)
from kukai.ir import spec
from kukai.ir.contracts import DocumentFingerprint, ElementIdentityProof
from kukai.ir.midend import GroundedProgram, ProgramFamily


LOWER_SCHEMA = "kir-lowered-program/1"
_A5_STAMP_SCOPE_RE = re.compile(r"a5:[0-9a-f]{12}:[0-9a-f]{16}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class IsolationMode(str, Enum):
    ATOMIC = "atomic"
    PER_OP = "per_op"


class PostconditionMode(str, Enum):
    STRICT = "strict"
    REPORT = "report"


class AuthoringTemplate(str, Enum):
    SHARED_TRANSACTION = "shared_transaction"
    STAIRS_EDIT_SCOPE = "stairs_edit_scope"


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"lowering evidence is not canonical JSON: {exc}") from exc


def program_hash(grounded_ops: list[dict[str, Any]]) -> str:
    """Legacy eight-character authoring hash; byte contract, do not alter."""

    blob = json.dumps(
        grounded_ops, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:8]


def program_stamp(
    grounded_ops: list[dict[str, Any]],
    stamp_scope: str = "",
) -> str:
    """Return the legacy stamp or one exact A5 run-owned stamp."""

    if stamp_scope:
        if _A5_STAMP_SCOPE_RE.fullmatch(stamp_scope) is None:
            raise ValueError("invalid internal A5 stamp scope")
        return f"kir:{stamp_scope}:{program_hash(grounded_ops)}"
    return f"kir:{program_hash(grounded_ops)}"


@dataclass(frozen=True, slots=True)
class AuthoringPolicy:
    """Canonical effective policy consumed by an authoring template."""

    isolation: IsolationMode
    postconditions: PostconditionMode
    disallow_wall_joins: bool
    stamp_scope: str
    expected_document: DocumentFingerprint | None
    expected_identities: tuple[ElementIdentityProof, ...]
    open_model_profile_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.isolation, IsolationMode):
            raise TypeError("authoring isolation must be typed")
        if not isinstance(self.postconditions, PostconditionMode):
            raise TypeError("authoring postconditions must be typed")
        if not isinstance(self.disallow_wall_joins, bool):
            raise TypeError("disallow_wall_joins must be bool")
        if not isinstance(self.stamp_scope, str):
            raise TypeError("stamp_scope must be a string")
        if (self.stamp_scope
                and _A5_STAMP_SCOPE_RE.fullmatch(self.stamp_scope) is None):
            raise ValueError("invalid internal A5 stamp scope")
        if (self.expected_document is not None
                and not isinstance(
                    self.expected_document, DocumentFingerprint)):
            raise TypeError("expected_document must be typed or None")
        if (self.expected_document is not None
                and not self.expected_document.title):
            raise ValueError("expected document title must not be empty")
        if (not isinstance(self.expected_identities, tuple)
                or any(not isinstance(item, ElementIdentityProof)
                       for item in self.expected_identities)):
            raise TypeError("expected identities must be a typed tuple")
        identity_ids = tuple(
            proof.element_id for proof in self.expected_identities)
        if identity_ids != tuple(sorted(set(identity_ids))):
            raise ValueError(
                "expected identities must be canonical and unique by id")
        if (self.open_model_profile_digest is not None
                and (not isinstance(self.open_model_profile_digest, str)
                     or _SHA256_RE.fullmatch(
                         self.open_model_profile_digest) is None)):
            raise ValueError(
                "open model profile digest must be lowercase SHA-256")
        if (self.isolation is IsolationMode.PER_OP
                and self.postconditions is not PostconditionMode.REPORT):
            raise ValueError(
                "per-op isolation requires report-mode postconditions")
        if (self.isolation is IsolationMode.ATOMIC
                and self.disallow_wall_joins):
            raise ValueError(
                "wall-join suppression is effective only in per-op mode")

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "isolation": self.isolation.value,
            "postconditions": self.postconditions.value,
            "disallow_wall_joins": self.disallow_wall_joins,
            "stamp_scope": self.stamp_scope,
            "expected_document": (
                self.expected_document.to_dict()
                if self.expected_document is not None else None
            ),
            "expected_identities": [
                proof.to_dict() for proof in self.expected_identities
            ],
            "open_model_profile_digest": self.open_model_profile_digest,
        }


@dataclass(frozen=True, slots=True)
class LoweredProgram:
    """One immutable, parent-bound authoring lowering decision."""

    grounded: GroundedProgram
    target_profile: TargetProfile
    policy: AuthoringPolicy
    template: AuthoringTemplate
    program_stamp: str
    lower_digest: str = field(default="")

    def __post_init__(self) -> None:
        if not isinstance(self.grounded, GroundedProgram):
            raise TypeError("lowered program needs typed grounding")
        if self.grounded.planned.family is not ProgramFamily.WRITE:
            raise ValueError("only write programs have an authoring lowering")
        if not isinstance(self.target_profile, TargetProfile):
            raise TypeError("lowered program needs a typed target profile")
        canonical_profile = load_target_profile_manifest().profile_for_year(
            self.target_profile.revit_year)
        if self.target_profile != canonical_profile:
            raise ValueError("target profile is not the packaged contract")
        if not isinstance(self.policy, AuthoringPolicy):
            raise TypeError("lowered program needs typed authoring policy")
        if not isinstance(self.template, AuthoringTemplate):
            raise TypeError("authoring template must be typed")

        ops = self.grounded.to_ops()
        has_solo_op = any(op["op"] in spec.SOLO_OPS for op in ops)
        expected_template = (
            AuthoringTemplate.STAIRS_EDIT_SCOPE
            if has_solo_op else AuthoringTemplate.SHARED_TRANSACTION
        )
        if self.template is not expected_template:
            raise ValueError("authoring template disagrees with grounded ops")
        if has_solo_op and (
            len(ops) != 1 or ops[0]["op"] not in spec.SOLO_OPS
        ):
            raise ValueError("a sole-op template must contain exactly one op")
        if self.template is AuthoringTemplate.STAIRS_EDIT_SCOPE and (
            self.policy.isolation is not IsolationMode.ATOMIC
            or self.policy.postconditions is not PostconditionMode.STRICT
            or self.policy.disallow_wall_joins
        ):
            raise ValueError("stairs template requires its canonical policy")

        expected_stamp = program_stamp(ops, self.policy.stamp_scope)
        if self.program_stamp != expected_stamp:
            raise ValueError("program stamp disagrees with grounded payload")
        computed = hashlib.sha256(
            _canonical_json(self._unsigned_evidence()).encode("utf-8")
        ).hexdigest()
        if self.lower_digest and self.lower_digest != computed:
            raise ValueError("lower_digest disagrees with lowering payload")
        object.__setattr__(self, "lower_digest", computed)

    def _unsigned_evidence(self) -> dict[str, Any]:
        return {
            "schema": LOWER_SCHEMA,
            "ground_digest": self.grounded.ground_digest,
            "target_profile": {
                "profile_id": self.target_profile.profile_id,
                "revit_year": self.target_profile.revit_year,
                "profile_digest": self.target_profile.profile_digest,
            },
            "policy": self.policy.to_evidence_dict(),
            "template": self.template.value,
            "program_stamp": self.program_stamp,
        }

    def to_evidence_dict(self) -> dict[str, Any]:
        payload = self._unsigned_evidence()
        payload["lower_digest"] = self.lower_digest
        return payload


def _document_fingerprint(
    value: DocumentFingerprint | Mapping[str, str] | None,
) -> DocumentFingerprint | None:
    if value is None or isinstance(value, DocumentFingerprint):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("expected_document must be a mapping or typed value")
    required = {"title", "path_name", "project_uid"}
    if set(value) != required:
        raise ValueError(
            "expected_document must contain title, path_name, project_uid")
    return DocumentFingerprint(
        title=value["title"],
        path_name=value["path_name"],
        project_uid=value["project_uid"],
    )


def _identity_tuple(
    values: Sequence[ElementIdentityProof] | None,
) -> tuple[ElementIdentityProof, ...]:
    if values is None:
        return ()
    if (isinstance(values, (str, bytes, bytearray))
            or not isinstance(values, Sequence)
            or any(not isinstance(item, ElementIdentityProof)
                   for item in values)):
        raise TypeError(
            "expected_identities must contain ElementIdentityProof values")
    by_id: dict[int, ElementIdentityProof] = {}
    for proof in values:
        prior = by_id.get(proof.element_id)
        if prior is not None and prior != proof:
            raise ValueError(
                "one ElementId has contradictory expected identities")
        by_id[proof.element_id] = proof
    return tuple(by_id[element_id] for element_id in sorted(by_id))


def lower_program(
    grounded: GroundedProgram,
    target: TargetProfile | str,
    *,
    isolation: IsolationMode | str = IsolationMode.ATOMIC,
    postconditions: PostconditionMode | str = PostconditionMode.STRICT,
    disallow_wall_joins: bool = False,
    stamp_scope: str = "",
    expected_document: DocumentFingerprint | Mapping[str, str] | None = None,
    expected_identities: Sequence[ElementIdentityProof] | None = None,
    open_model_profile_digest: str | None = None,
) -> LoweredProgram:
    """Canonicalise compiler policy and bind it to one grounded program."""

    if not isinstance(grounded, GroundedProgram):
        raise TypeError("lower_program requires a GroundedProgram")
    profile = (
        load_target_profile_manifest().profile_for_year(target)
        if isinstance(target, str) else target
    )
    if not isinstance(profile, TargetProfile):
        raise TypeError("target must be a Revit year or TargetProfile")
    try:
        isolation_mode = IsolationMode(isolation)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"unsupported authoring isolation {isolation!r}") from exc
    try:
        requested_postconditions = PostconditionMode(postconditions)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"unsupported postcondition mode {postconditions!r}") from exc
    if not isinstance(disallow_wall_joins, bool):
        raise TypeError("disallow_wall_joins must be bool")

    ops = grounded.to_ops()
    has_solo_op = any(op["op"] in spec.SOLO_OPS for op in ops)
    template = (
        AuthoringTemplate.STAIRS_EDIT_SCOPE
        if has_solo_op else AuthoringTemplate.SHARED_TRANSACTION
    )
    if has_solo_op:
        # StairsEditScope owns its transactions.  These are the effective
        # semantics of the existing template, regardless of caller flags.
        isolation_mode = IsolationMode.ATOMIC
        effective_postconditions = PostconditionMode.STRICT
        effective_disallow_joins = False
    else:
        effective_postconditions = (
            PostconditionMode.REPORT
            if isolation_mode is IsolationMode.PER_OP
            else requested_postconditions
        )
        effective_disallow_joins = (
            disallow_wall_joins
            if isolation_mode is IsolationMode.PER_OP else False
        )

    policy = AuthoringPolicy(
        isolation=isolation_mode,
        postconditions=effective_postconditions,
        disallow_wall_joins=effective_disallow_joins,
        stamp_scope=stamp_scope,
        expected_document=_document_fingerprint(expected_document),
        expected_identities=_identity_tuple(expected_identities),
        open_model_profile_digest=open_model_profile_digest,
    )
    return LoweredProgram(
        grounded=grounded,
        target_profile=profile,
        policy=policy,
        template=template,
        program_stamp=program_stamp(ops, policy.stamp_scope),
    )
