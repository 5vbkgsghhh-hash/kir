"""One atomic live reread for all independent KIR acceptance predicates.

The L2 census and exact-mutation probe are separate pure authorities, but they
must observe one document state.  This adapter composes their C# fragments into
one bridge execution and strictly splits the resulting closed envelope back
into typed observations.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from kukai.ir import spec
from kukai.ir.acceptance import Expectation
from kukai.ir.acceptance_live import (
    ScopeCensusObservation,
    parse_scope_census,
    scope_census_fragment,
)
from kukai.ir.acceptance_mutation import (
    MutationExpectation,
    MutationObservation,
    mutation_probe_fragment,
    parse_mutation_observation,
)
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.document_guard import bind_read_to_document


ACCEPTANCE_OBSERVATION_SCHEMA_VERSION = "kir-independent-observation/1"
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_ID_RE = re.compile(r"[0-9a-f]{32}\Z")
_PHASES = frozenset({"before", "after"})
_FIELDS = frozenset({
    "schema_version",
    "run_id",
    "phase",
    "plan_digest",
    "document_digest",
    "revit_version",
    "scope_census",
    "mutations",
})


class AcceptanceProbeError(ValueError):
    """The composite live reread violates its closed binding contract."""


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise AcceptanceProbeError(f"{name} must be lowercase SHA-256")
    return value


def _run_id(value: Any) -> str:
    if not isinstance(value, str) or _RUN_ID_RE.fullmatch(value) is None:
        raise AcceptanceProbeError("acceptance run_id is malformed")
    return value


def _phase(value: Any) -> str:
    if value not in _PHASES:
        raise AcceptanceProbeError(
            f"acceptance phase must be one of {sorted(_PHASES)}")
    return str(value)


def _version(value: Any) -> str:
    if value not in spec.REVIT_VERSIONS:
        raise AcceptanceProbeError(
            "acceptance Revit version is outside the shipped matrix")
    return str(value)


@dataclass(frozen=True, slots=True)
class AcceptanceObservation:
    run_id: str
    phase: str
    plan_digest: str
    document_digest: str
    revit_version: str
    scope_census: ScopeCensusObservation | None
    mutations: MutationObservation | None

    def __post_init__(self) -> None:
        _run_id(self.run_id)
        _phase(self.phase)
        _sha256(self.plan_digest, "plan_digest")
        _sha256(self.document_digest, "document_digest")
        _version(self.revit_version)
        if self.scope_census is None and self.mutations is None:
            raise AcceptanceProbeError(
                "acceptance observation must carry at least one predicate")
        for observation in (self.scope_census, self.mutations):
            if observation is None:
                continue
            if observation.run_id != self.run_id:
                raise AcceptanceProbeError(
                    "nested acceptance observation has another run_id")
            if observation.phase != self.phase:
                raise AcceptanceProbeError(
                    "nested acceptance observation has another phase")
            if observation.document_digest != self.document_digest:
                raise AcceptanceProbeError(
                    "nested acceptance observation has another document")


def build_acceptance_probe_cs(
    *,
    plan_digest: str,
    scope_expectation: Expectation,
    mutation_expectation: MutationExpectation,
    document: DocumentFingerprint,
    run_id: str,
    phase: str,
    revit_version: str,
) -> str:
    """Build one read-only bridge program covering every checkable predicate."""

    accepted_plan = _sha256(plan_digest, "plan_digest")
    accepted_run = _run_id(run_id)
    accepted_phase = _phase(phase)
    accepted_version = _version(revit_version)
    if not isinstance(scope_expectation, Expectation):
        raise TypeError("acceptance probe requires a typed scope expectation")
    if not isinstance(mutation_expectation, MutationExpectation):
        raise TypeError("acceptance probe requires a typed mutation expectation")
    if not isinstance(document, DocumentFingerprint):
        raise TypeError("acceptance probe requires DocumentFingerprint")
    if not scope_expectation.checkable and not mutation_expectation.checkable:
        raise AcceptanceProbeError("acceptance probe has no checkable predicate")

    fragments = []
    scope_value = "null"
    mutation_value = "null"
    if scope_expectation.checkable:
        fragments.append(scope_census_fragment(
            scope_expectation,
            document,
            run_id=accepted_run,
            phase=accepted_phase,
            result_var="__kirCompositeScope",
        ))
        scope_value = "__kirCompositeScope"
    if mutation_expectation.checkable:
        fragments.append(mutation_probe_fragment(
            mutation_expectation,
            document,
            run_id=accepted_run,
            phase=accepted_phase,
            revit_version=accepted_version,
            result_var="__kirCompositeMutations",
        ))
        mutation_value = "__kirCompositeMutations"
    fragments.append(f"""
return new Dictionary<string, object> {{
    {{"schema_version", "{ACCEPTANCE_OBSERVATION_SCHEMA_VERSION}"}},
    {{"run_id", "{accepted_run}"}},
    {{"phase", "{accepted_phase}"}},
    {{"plan_digest", "{accepted_plan}"}},
    {{"document_digest", "{document.digest}"}},
    {{"revit_version", "{accepted_version}"}},
    {{"scope_census", {scope_value}}},
    {{"mutations", {mutation_value}}}
}};
""".strip())
    return bind_read_to_document("\n".join(fragments), document)


def parse_acceptance_observation(
    payload: Any,
    *,
    plan_digest: str,
    scope_expectation: Expectation,
    mutation_expectation: MutationExpectation,
    document: DocumentFingerprint,
    run_id: str,
    phase: str,
    revit_version: str,
) -> AcceptanceObservation:
    """Parse a composite response without accepting missing or widened scope."""

    if not isinstance(payload, Mapping) or set(payload) != _FIELDS:
        raise AcceptanceProbeError(
            "independent observation fields differ from the closed schema")
    expected = {
        "schema_version": ACCEPTANCE_OBSERVATION_SCHEMA_VERSION,
        "run_id": _run_id(run_id),
        "phase": _phase(phase),
        "plan_digest": _sha256(plan_digest, "plan_digest"),
        "document_digest": document.digest,
        "revit_version": _version(revit_version),
    }
    for field_name, wanted in expected.items():
        if payload.get(field_name) != wanted:
            raise AcceptanceProbeError(
                f"independent observation {field_name} binding differs")

    raw_scope = payload.get("scope_census")
    if scope_expectation.checkable:
        try:
            scope = parse_scope_census(
                raw_scope,
                scope_expectation,
                document,
                run_id=expected["run_id"],
                phase=expected["phase"],
            )
        except ValueError as exc:
            raise AcceptanceProbeError(f"scope census: {exc}") from exc
    else:
        if raw_scope is not None:
            raise AcceptanceProbeError(
                "unregistered scope census was returned")
        scope = None

    raw_mutations = payload.get("mutations")
    if mutation_expectation.checkable:
        try:
            mutations = parse_mutation_observation(
                raw_mutations,
                mutation_expectation,
                document,
                run_id=expected["run_id"],
                phase=expected["phase"],
            )
        except ValueError as exc:
            raise AcceptanceProbeError(f"mutations: {exc}") from exc
    else:
        if raw_mutations is not None:
            raise AcceptanceProbeError(
                "unregistered mutation observation was returned")
        mutations = None
    return AcceptanceObservation(
        run_id=expected["run_id"],
        phase=expected["phase"],
        plan_digest=expected["plan_digest"],
        document_digest=document.digest,
        revit_version=expected["revit_version"],
        scope_census=scope,
        mutations=mutations,
    )


__all__ = [
    "ACCEPTANCE_OBSERVATION_SCHEMA_VERSION",
    "AcceptanceObservation",
    "AcceptanceProbeError",
    "build_acceptance_probe_cs",
    "parse_acceptance_observation",
]
