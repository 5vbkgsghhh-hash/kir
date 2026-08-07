"""Typed result contract of the in-process KIR forward compiler."""
from __future__ import annotations

from dataclasses import dataclass, field

from kukai.ir.diag import Diagnostic
from kukai.ir.emitted_artifact import EmittedArtifact
from kukai.ir.lowering import LoweredProgram
from kukai.ir.midend import GroundedProgram, PlannedProgram


@dataclass
class CompileOutput:
    """One compile outcome plus immutable stage values retained internally.

    ``csharp`` and the digest fields exposed by :meth:`as_dict` are legacy wire
    compatibility.  Trusted downstream code consumes the typed stage objects;
    the constructor rejects a chain assembled from unrelated parents.
    """

    ok: bool
    csharp: str | None = None
    diagnostics: list[Diagnostic] = field(default_factory=list)
    per_version: dict[str, str] = field(default_factory=dict)
    planned: PlannedProgram | None = None
    grounded: GroundedProgram | None = None
    lowered: LoweredProgram | None = None
    emitted: EmittedArtifact | None = None
    handoff: dict | None = None
    grounding_report: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.ok, bool):
            raise TypeError("compile output ok flag must be bool")
        if (not isinstance(self.diagnostics, list)
                or any(not isinstance(item, Diagnostic)
                       for item in self.diagnostics)):
            raise TypeError("compile diagnostics must be a list of Diagnostic")
        if self.grounded is not None and (
            self.planned is None or self.grounded.planned is not self.planned
        ):
            raise ValueError("compile grounding disagrees with planned parent")
        if self.lowered is not None and (
            self.grounded is None or self.lowered.grounded is not self.grounded
        ):
            raise ValueError("compile lowering disagrees with grounded parent")
        if self.emitted is not None:
            if (self.lowered is None
                    or self.emitted.lowered is not self.lowered):
                raise ValueError(
                    "emitted artifact disagrees with lowered parent")
            if self.csharp != self.emitted.source:
                raise ValueError(
                    "legacy csharp field disagrees with emitted artifact")

    def as_dict(self) -> dict:
        """Legacy additive wire shape; internal stage digests stay private."""

        payload = {
            "ok": self.ok,
            "csharp": self.csharp,
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }
        if self.planned is not None:
            payload["plan_digest"] = self.planned.plan_digest
        if self.grounded is not None:
            payload["ground_digest"] = self.grounded.ground_digest
        if self.handoff:
            payload["handoff"] = self.handoff
        if self.grounding_report:
            payload["grounding_report"] = self.grounding_report
        return payload


__all__ = ["CompileOutput"]
