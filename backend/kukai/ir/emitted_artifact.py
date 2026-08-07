"""Immutable output of KIR authoring emission.

The generated source is still returned through ``CompileOutput.csharp`` for
wire compatibility.  Internally, later compile/receipt stages consume this
parent-bound artifact so source text cannot be substituted after lowering
without changing its content address.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from kukai.ir.lowering import LoweredProgram


EMITTED_ARTIFACT_SCHEMA = "kir-emitted-artifact/1"
AUTHORING_EMITTER_CONTRACT = "kukai-authoring-csharp/1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


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
        raise ValueError(
            f"emitted artifact is not canonical JSON: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EmittedArtifact:
    """Exact UTF-8 Execute-body source emitted from one lowering."""

    lowered: LoweredProgram
    source: str = field(repr=False)
    emitter_contract: str = AUTHORING_EMITTER_CONTRACT
    source_sha256: str = ""
    source_bytes: int = 0
    artifact_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.lowered, LoweredProgram):
            raise TypeError("emitted artifact needs a LoweredProgram parent")
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("emitted source must be a non-empty string")
        if self.emitter_contract != AUTHORING_EMITTER_CONTRACT:
            raise ValueError("unsupported authoring emitter contract")

        encoded = self.source.encode("utf-8")
        computed_source_hash = hashlib.sha256(encoded).hexdigest()
        if self.source_sha256:
            if (_SHA256_RE.fullmatch(self.source_sha256) is None
                    or self.source_sha256 != computed_source_hash):
                raise ValueError("source_sha256 disagrees with emitted source")
        object.__setattr__(self, "source_sha256", computed_source_hash)
        if self.source_bytes not in (0, len(encoded)):
            raise ValueError("source_bytes disagrees with emitted source")
        object.__setattr__(self, "source_bytes", len(encoded))

        computed_artifact_digest = _digest(self._unsigned_evidence())
        if (self.artifact_digest
                and self.artifact_digest != computed_artifact_digest):
            raise ValueError(
                "artifact_digest disagrees with emitted artifact")
        object.__setattr__(
            self, "artifact_digest", computed_artifact_digest)

    def _unsigned_evidence(self) -> dict[str, Any]:
        return {
            "schema": EMITTED_ARTIFACT_SCHEMA,
            "lower_digest": self.lowered.lower_digest,
            "target_profile_digest": (
                self.lowered.target_profile.profile_digest),
            "emitter_contract": self.emitter_contract,
            "source_encoding": "utf-8",
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
        }

    def to_evidence_dict(self) -> dict[str, Any]:
        """Return provenance without copying source code into receipts."""

        payload = self._unsigned_evidence()
        payload["artifact_digest"] = self.artifact_digest
        return payload
