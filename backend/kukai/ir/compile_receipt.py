"""Strict, content-addressed receipt for a successful Roslyn full emit.

The receipt binds three independently checkable facts:

* the immutable KIR :class:`~kukai.ir.emitted_artifact.EmittedArtifact`;
* the exact wrapped UTF-8 compilation unit;
* the packaged Revit target profile and compiler manifest.

It deliberately contains no operation id or Revit execution claim.  Those
belong to the later operation receipt, which can reference ``receipt_digest``.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from kukai.compiler_contract import (
    load_archived_target_profile_manifest,
    load_target_profile_manifest,
)
from kukai.compiler_unit import (
    EXECUTE_WRAPPER_CONTRACT,
    unwrap_execute_body,
    wrap_execute_body,
)
from kukai.ir.emitted_artifact import (
    AUTHORING_EMITTER_CONTRACT,
    EMITTED_ARTIFACT_SCHEMA,
    EmittedArtifact,
)


COMPILE_RECEIPT_SCHEMA = "kir-compile-receipt/1"
COMPILER_CONTRACT = "roslyn-full-emit/1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class CompileReceiptError(ValueError):
    """A compile receipt is malformed, forged, or bound to another artifact."""


def _digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompileReceiptError(
            f"compile receipt is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


def _object(
    value: Any,
    *,
    path: str,
    fields: frozenset[str],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompileReceiptError(f"{path} must be an object")
    keys = frozenset(value)
    missing = sorted(fields - keys)
    extra = sorted(keys - fields)
    if missing or extra:
        raise CompileReceiptError(
            f"{path} fields mismatch: missing={missing}, extra={extra}")
    return value


def _string(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise CompileReceiptError(f"{path} must be a non-empty string")
    return value


def _sha256(value: Any, *, path: str) -> str:
    result = _string(value, path=path)
    if _SHA256_RE.fullmatch(result) is None:
        raise CompileReceiptError(f"{path} must be lowercase SHA-256")
    return result


def _positive_int(value: Any, *, path: str) -> int:
    if type(value) is not int or value <= 0:
        raise CompileReceiptError(f"{path} must be a positive integer")
    return value


_TARGET_FIELDS = frozenset({
    "profile_id",
    "revit_year",
    "profile_digest",
    "manifest_digest",
})
_RECEIPT_FIELDS = frozenset({
    "schema",
    "artifact",
    "compile_unit",
    "target",
    "compiler_contract",
    "receipt_digest",
})


def _target_values(value: Any) -> tuple[str, str, str, str]:
    obj = _object(value, path="target", fields=_TARGET_FIELDS)
    return (
        _string(obj["profile_id"], path="target.profile_id"),
        _string(obj["revit_year"], path="target.revit_year"),
        _sha256(obj["profile_digest"], path="target.profile_digest"),
        _sha256(obj["manifest_digest"], path="target.manifest_digest"),
    )


def _validate_target_against_manifest(
    *,
    profile_id: str,
    revit_year: str,
    profile_digest: str,
    manifest_digest: str,
    manifest: Any,
    contract_description: str,
) -> None:
    try:
        profile = manifest.profile_for_year(revit_year)
    except ValueError as exc:
        raise CompileReceiptError(
            f"unsupported receipt target Revit {revit_year!r}") from exc
    if (
        profile_id != profile.profile_id
        or profile_digest != profile.profile_digest
        or manifest_digest != manifest.manifest_digest
    ):
        raise CompileReceiptError(
            f"receipt target disagrees with {contract_description}")


def _receipt_object(value: Any) -> Mapping[str, Any]:
    return _object(value, path="receipt", fields=_RECEIPT_FIELDS)


@dataclass(frozen=True, slots=True)
class ArtifactBinding:
    """Source-free copy of the emitted artifact's content address."""

    schema: str
    lower_digest: str
    target_profile_digest: str
    emitter_contract: str
    source_encoding: str
    source_sha256: str
    source_bytes: int
    artifact_digest: str = field(default="")

    def __post_init__(self) -> None:
        if self.schema != EMITTED_ARTIFACT_SCHEMA:
            raise CompileReceiptError("unsupported emitted artifact schema")
        _sha256(self.lower_digest, path="artifact.lower_digest")
        _sha256(
            self.target_profile_digest,
            path="artifact.target_profile_digest",
        )
        if self.emitter_contract != AUTHORING_EMITTER_CONTRACT:
            raise CompileReceiptError("unsupported authoring emitter contract")
        if self.source_encoding != "utf-8":
            raise CompileReceiptError("artifact source encoding must be utf-8")
        _sha256(self.source_sha256, path="artifact.source_sha256")
        _positive_int(self.source_bytes, path="artifact.source_bytes")

        computed = _digest(self._unsigned_dict())
        if self.artifact_digest and self.artifact_digest != computed:
            raise CompileReceiptError(
                "artifact.artifact_digest disagrees with artifact binding")
        object.__setattr__(self, "artifact_digest", computed)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "lower_digest": self.lower_digest,
            "target_profile_digest": self.target_profile_digest,
            "emitter_contract": self.emitter_contract,
            "source_encoding": self.source_encoding,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["artifact_digest"] = self.artifact_digest
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "ArtifactBinding":
        fields = frozenset({
            "schema",
            "lower_digest",
            "target_profile_digest",
            "emitter_contract",
            "source_encoding",
            "source_sha256",
            "source_bytes",
            "artifact_digest",
        })
        obj = _object(value, path="artifact", fields=fields)
        return cls(
            schema=_string(obj["schema"], path="artifact.schema"),
            lower_digest=_sha256(
                obj["lower_digest"], path="artifact.lower_digest"),
            target_profile_digest=_sha256(
                obj["target_profile_digest"],
                path="artifact.target_profile_digest",
            ),
            emitter_contract=_string(
                obj["emitter_contract"], path="artifact.emitter_contract"),
            source_encoding=_string(
                obj["source_encoding"], path="artifact.source_encoding"),
            source_sha256=_sha256(
                obj["source_sha256"], path="artifact.source_sha256"),
            source_bytes=_positive_int(
                obj["source_bytes"], path="artifact.source_bytes"),
            artifact_digest=_sha256(
                obj["artifact_digest"], path="artifact.artifact_digest"),
        )

    @classmethod
    def from_emitted(cls, artifact: EmittedArtifact) -> "ArtifactBinding":
        if not isinstance(artifact, EmittedArtifact):
            raise TypeError("compile receipt needs an EmittedArtifact")
        return cls.from_dict(artifact.to_evidence_dict())


@dataclass(frozen=True, slots=True)
class CompileUnitBinding:
    """Content address of the full source passed to Roslyn."""

    wrapper_contract: str
    source_encoding: str
    source_sha256: str
    source_bytes: int

    def __post_init__(self) -> None:
        if self.wrapper_contract != EXECUTE_WRAPPER_CONTRACT:
            raise CompileReceiptError("unsupported execute wrapper contract")
        if self.source_encoding != "utf-8":
            raise CompileReceiptError("compile-unit encoding must be utf-8")
        _sha256(self.source_sha256, path="compile_unit.source_sha256")
        _positive_int(self.source_bytes, path="compile_unit.source_bytes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "wrapper_contract": self.wrapper_contract,
            "source_encoding": self.source_encoding,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CompileUnitBinding":
        fields = frozenset({
            "wrapper_contract",
            "source_encoding",
            "source_sha256",
            "source_bytes",
        })
        obj = _object(value, path="compile_unit", fields=fields)
        return cls(
            wrapper_contract=_string(
                obj["wrapper_contract"],
                path="compile_unit.wrapper_contract",
            ),
            source_encoding=_string(
                obj["source_encoding"], path="compile_unit.source_encoding"),
            source_sha256=_sha256(
                obj["source_sha256"], path="compile_unit.source_sha256"),
            source_bytes=_positive_int(
                obj["source_bytes"], path="compile_unit.source_bytes"),
        )

    @classmethod
    def from_source(cls, source: str) -> "CompileUnitBinding":
        if not isinstance(source, str) or not source:
            raise CompileReceiptError(
                "wrapped compile-unit source must be non-empty")
        encoded = source.encode("utf-8")
        return cls(
            wrapper_contract=EXECUTE_WRAPPER_CONTRACT,
            source_encoding="utf-8",
            source_sha256=hashlib.sha256(encoded).hexdigest(),
            source_bytes=len(encoded),
        )


@dataclass(frozen=True, slots=True)
class CompileReceiptWireValidation:
    """Manifest-neutral validation result for persisted receipt wire data.

    This value proves only the receipt's closed shape and content-address
    relationships.  Its target is deliberately an unresolved four-field
    selector: the value is neither current compiler authority nor historical
    archive evidence and exposes no executable-source APIs.
    """

    artifact: ArtifactBinding
    compile_unit: CompileUnitBinding
    target: Mapping[str, str]
    schema: str = COMPILE_RECEIPT_SCHEMA
    compiler_contract: str = COMPILER_CONTRACT
    receipt_digest: str = field(default="")

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactBinding):
            raise TypeError("receipt wire artifact binding must be typed")
        if not isinstance(self.compile_unit, CompileUnitBinding):
            raise TypeError("receipt wire unit binding must be typed")
        if self.schema != COMPILE_RECEIPT_SCHEMA:
            raise CompileReceiptError("unsupported compile receipt schema")
        if self.compiler_contract != COMPILER_CONTRACT:
            raise CompileReceiptError("unsupported compiler contract")
        profile_id, revit_year, profile_digest, manifest_digest = (
            _target_values(self.target)
        )
        normalized_target = {
            "profile_id": profile_id,
            "revit_year": revit_year,
            "profile_digest": profile_digest,
            "manifest_digest": manifest_digest,
        }
        object.__setattr__(self, "target", MappingProxyType(normalized_target))
        if self.artifact.target_profile_digest != profile_digest:
            raise CompileReceiptError(
                "artifact and receipt target profile digests disagree")

        computed = _digest(self._unsigned_dict())
        if self.receipt_digest and _sha256(
            self.receipt_digest,
            path="receipt.receipt_digest",
        ) != computed:
            raise CompileReceiptError(
                "receipt_digest disagrees with compile receipt")
        object.__setattr__(self, "receipt_digest", computed)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "artifact": self.artifact.to_dict(),
            "compile_unit": self.compile_unit.to_dict(),
            "target": dict(self.target),
            "compiler_contract": self.compiler_contract,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["receipt_digest"] = self.receipt_digest
        return payload


def validate_compile_receipt_wire(value: Any) -> CompileReceiptWireValidation:
    """Validate receipt content before resolving a current/archive manifest."""

    obj = _receipt_object(value)
    return CompileReceiptWireValidation(
        schema=_string(obj["schema"], path="receipt.schema"),
        artifact=ArtifactBinding.from_dict(obj["artifact"]),
        compile_unit=CompileUnitBinding.from_dict(obj["compile_unit"]),
        target=dict(_object(obj["target"], path="target", fields=_TARGET_FIELDS)),
        compiler_contract=_string(
            obj["compiler_contract"], path="receipt.compiler_contract"),
        receipt_digest=_sha256(
            obj["receipt_digest"], path="receipt.receipt_digest"),
    )


@dataclass(frozen=True, slots=True)
class TargetBinding:
    """Exact packaged profile used to select Roslyn references."""

    profile_id: str
    revit_year: str
    profile_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        profile_id = _string(self.profile_id, path="target.profile_id")
        revit_year = _string(self.revit_year, path="target.revit_year")
        profile_digest = _sha256(
            self.profile_digest, path="target.profile_digest")
        manifest_digest = _sha256(
            self.manifest_digest, path="target.manifest_digest")

        _validate_target_against_manifest(
            profile_id=profile_id,
            revit_year=revit_year,
            profile_digest=profile_digest,
            manifest_digest=manifest_digest,
            manifest=load_target_profile_manifest(),
            contract_description="packaged compiler contract",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "revit_year": self.revit_year,
            "profile_digest": self.profile_digest,
            "manifest_digest": self.manifest_digest,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "TargetBinding":
        return cls(*_target_values(value))

    @classmethod
    def for_emitted(cls, artifact: EmittedArtifact) -> "TargetBinding":
        if not isinstance(artifact, EmittedArtifact):
            raise TypeError("target binding needs an EmittedArtifact")
        profile = artifact.lowered.target_profile
        manifest = load_target_profile_manifest()
        return cls(
            profile_id=profile.profile_id,
            revit_year=profile.revit_year,
            profile_digest=profile.profile_digest,
            manifest_digest=manifest.manifest_digest,
        )


@dataclass(frozen=True, slots=True)
class HistoricalTargetBinding:
    """Receipt target proven only through a packaged archived manifest."""

    profile_id: str
    revit_year: str
    profile_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        profile_id = _string(self.profile_id, path="target.profile_id")
        revit_year = _string(self.revit_year, path="target.revit_year")
        profile_digest = _sha256(
            self.profile_digest, path="target.profile_digest")
        manifest_digest = _sha256(
            self.manifest_digest, path="target.manifest_digest")
        _validate_target_against_manifest(
            profile_id=profile_id,
            revit_year=revit_year,
            profile_digest=profile_digest,
            manifest_digest=manifest_digest,
            manifest=load_archived_target_profile_manifest(manifest_digest),
            contract_description="packaged historical compiler archive",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "profile_id": self.profile_id,
            "revit_year": self.revit_year,
            "profile_digest": self.profile_digest,
            "manifest_digest": self.manifest_digest,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "HistoricalTargetBinding":
        return cls(*_target_values(value))


@dataclass(frozen=True, slots=True)
class CompileReceipt:
    """Deterministic claim returned only after a successful full Roslyn emit."""

    artifact: ArtifactBinding
    compile_unit: CompileUnitBinding
    target: TargetBinding
    schema: str = COMPILE_RECEIPT_SCHEMA
    compiler_contract: str = COMPILER_CONTRACT
    receipt_digest: str = field(default="")

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactBinding):
            raise TypeError("compile receipt artifact binding must be typed")
        if not isinstance(self.compile_unit, CompileUnitBinding):
            raise TypeError("compile receipt unit binding must be typed")
        if not isinstance(self.target, TargetBinding):
            raise TypeError("compile receipt target binding must be typed")
        validated = CompileReceiptWireValidation(
            schema=self.schema,
            artifact=self.artifact,
            compile_unit=self.compile_unit,
            target=self.target.to_dict(),
            compiler_contract=self.compiler_contract,
            receipt_digest=self.receipt_digest,
        )
        object.__setattr__(self, "receipt_digest", validated.receipt_digest)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "artifact": self.artifact.to_dict(),
            "compile_unit": self.compile_unit.to_dict(),
            "target": self.target.to_dict(),
            "compiler_contract": self.compiler_contract,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["receipt_digest"] = self.receipt_digest
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "CompileReceipt":
        validated = validate_compile_receipt_wire(value)
        return cls(
            schema=validated.schema,
            artifact=validated.artifact,
            compile_unit=validated.compile_unit,
            target=TargetBinding.from_dict(validated.target),
            compiler_contract=validated.compiler_contract,
            receipt_digest=validated.receipt_digest,
        )

    @classmethod
    def expected_for(cls, artifact: EmittedArtifact) -> "CompileReceipt":
        """Build the deterministic claim a successful service must return.

        This computes expected evidence; it does *not* assert that Roslyn ran.
        Only the strict compile-service success path may promote it to proof.
        """

        if not isinstance(artifact, EmittedArtifact):
            raise TypeError("compile receipt needs an EmittedArtifact")
        wrapped = wrap_execute_body(artifact.source)
        return cls(
            artifact=ArtifactBinding.from_emitted(artifact),
            compile_unit=CompileUnitBinding.from_source(wrapped),
            target=TargetBinding.for_emitted(artifact),
        )

    def verified_compile_unit(self, artifact: EmittedArtifact) -> str:
        """Return executable bytes only if every receipt binding is exact."""

        expected = type(self).expected_for(artifact)
        if self != expected:
            raise CompileReceiptError(
                "compile receipt is not bound to this emitted artifact")
        wrapped = wrap_execute_body(artifact.source)
        self.verified_wrapped_source(wrapped)
        return wrapped

    def verified_wrapped_source(self, wrapped_source: str) -> str:
        """Verify receipt against wire bytes and return their recovered body."""

        try:
            body = unwrap_execute_body(wrapped_source)
        except (TypeError, ValueError) as exc:
            raise CompileReceiptError(str(exc)) from exc
        if CompileUnitBinding.from_source(wrapped_source) != self.compile_unit:
            raise CompileReceiptError(
                "compile-unit binding disagrees with wrapped source")
        encoded = body.encode("utf-8")
        if (
            hashlib.sha256(encoded).hexdigest()
            != self.artifact.source_sha256
            or len(encoded) != self.artifact.source_bytes
        ):
            raise CompileReceiptError(
                "artifact source binding disagrees with wrapped body")
        return body


@dataclass(frozen=True, slots=True)
class HistoricalCompileReceiptEvidence:
    """Read-only receipt proof resolved against an archived package resource.

    This intentionally is not a :class:`CompileReceipt`: it has no minting,
    expected-receipt, or executable-source verification API.  Callers may use
    it solely to verify and retain evidence already persisted by an earlier
    release.
    """

    artifact: ArtifactBinding
    compile_unit: CompileUnitBinding
    target: HistoricalTargetBinding
    schema: str = COMPILE_RECEIPT_SCHEMA
    compiler_contract: str = COMPILER_CONTRACT
    receipt_digest: str = field(default="")

    def __post_init__(self) -> None:
        if not isinstance(self.artifact, ArtifactBinding):
            raise TypeError("historical receipt artifact binding must be typed")
        if not isinstance(self.compile_unit, CompileUnitBinding):
            raise TypeError("historical receipt unit binding must be typed")
        if not isinstance(self.target, HistoricalTargetBinding):
            raise TypeError("historical receipt target binding must be typed")
        validated = CompileReceiptWireValidation(
            schema=self.schema,
            artifact=self.artifact,
            compile_unit=self.compile_unit,
            target=self.target.to_dict(),
            compiler_contract=self.compiler_contract,
            receipt_digest=self.receipt_digest,
        )
        object.__setattr__(self, "receipt_digest", validated.receipt_digest)

    def _unsigned_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "artifact": self.artifact.to_dict(),
            "compile_unit": self.compile_unit.to_dict(),
            "target": self.target.to_dict(),
            "compiler_contract": self.compiler_contract,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self._unsigned_dict()
        payload["receipt_digest"] = self.receipt_digest
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "HistoricalCompileReceiptEvidence":
        validated = validate_compile_receipt_wire(value)
        return cls(
            schema=validated.schema,
            artifact=validated.artifact,
            compile_unit=validated.compile_unit,
            target=HistoricalTargetBinding.from_dict(validated.target),
            compiler_contract=validated.compiler_contract,
            receipt_digest=validated.receipt_digest,
        )


__all__ = [
    "ArtifactBinding",
    "COMPILE_RECEIPT_SCHEMA",
    "COMPILER_CONTRACT",
    "CompileReceipt",
    "CompileReceiptError",
    "CompileReceiptWireValidation",
    "CompileUnitBinding",
    "HistoricalCompileReceiptEvidence",
    "HistoricalTargetBinding",
    "TargetBinding",
    "validate_compile_receipt_wire",
]
