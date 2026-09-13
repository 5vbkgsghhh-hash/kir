"""Pure preparation for the standalone, target-bound Connector protocol.

No discovery, network, Revit invocation or implicit retry occurs here. Native
code owns the authoritative runtime/document checks immediately before effect.
These Python values carry requested identities, not proof of their provenance.
Session credentials are transient and are never part of the prepared artifact.

This first preparation seam accepts no external grounding snapshot: the legacy
census carrier does not prove its binding to a Connector document revision.
Existing compiler refusals still apply. Reference compilation is not live BIM
acceptance; CodePolicy is enforced by the actual Connector, not copied here.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping
from uuid import UUID

from kir.compiler import compile_program
from kir.contracts import ElementIdentityProof
from kir.midend import GroundedProgram, PlannedProgram
from kir.spec import REVIT_VERSIONS


CONNECTOR_PROTOCOL = "kir-revit-connector/4"
MAX_SOURCE_CHARS = 6 * 1024 * 1024  # .NET UTF-16 code units, not Python len()
MAX_FRAME_BYTES = 16 * 1024 * 1024
EXECUTION_ASSOCIATION_PREFIX = "// kir-execution-association/1 sha256:"
_INT64_MAX = (1 << 63) - 1


#: 🔴 OPS THAT NEED A SECOND DOCUMENT — A REFUSAL BEFORE SENDING, NOT A POLICY.
#:
#: The standalone connector binds EXACTLY ONE document, and the policy
#: barrier (`CodePolicy.cs`) does not let generated code even NAME a second
#: one. So three ops of the language have no execution here in principle —
#: and preparation itself must say so, by its own name, rather than leaving
#: it to Roslyn at the other end of the wire with a foreign diagnostic about
#: `Application.Documents`.
#:
#: WHY EXACTLY THESE THREE, AND THIS IS A MEASUREMENT, NOT A LIST FROM
#: MEMORY. A walk over 77 emitters (`_EMITTERS` 72 + `_SOLO_PROGRAMS` 5)
#: reading each one's SOURCE (2026-09-06) gives exactly two of their own:
#: `transfer_material` (`doc.Application.Documents`) and `load_family`
#: (`LoadFamily(` — a FILE, not a second open document, so it is not here).
#: Three solo emitters are thin wrappers, and the markers sit in their
#: modules: `family_author_emit.py` (`NewFamilyDocument` x5 — CREATES a
#: second document), `family_transfer_emit.py` (`Application.Documents` x2,
#: `EditFamily` x2). Stairs carry zero markers.
#:
#: WHAT THIS REFUSAL DOES NOT DO. It does not touch the host path
#: (`serving`): there, any number of documents is fine, and the op is legal.
#: It is about ONE door — standalone.
SECOND_DOCUMENT_OPS = frozenset({
    "author_family",        # Application.NewFamilyDocument -> a second document
    "transfer_family",      # Application.Documents + Document.EditFamily
    "transfer_material",    # Application.Documents -> ElementTransformUtils.CopyElements
})

#: The refusal code. Introduced in `kir/diag.py` (family `connector`, fault
#: `environment`: not the author's to fix — the environment has no second
#: document).
CONNECTOR_SECOND_DOCUMENT_UNAVAILABLE = "KIR-C001"


class ConnectorPreparationError(ValueError):
    def __init__(self, code: str, message: str, *, diagnostics=()):
        self.code = code
        self.diagnostics = tuple(diagnostics)
        super().__init__(f"{code}: {message}")


def _checked_association_digest(value):
    if (type(value) is not str or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)):
        raise ConnectorPreparationError("invalid_association_digest", "expected a lowercase SHA-256 commitment")
    return value


def source_association_digest(source: str) -> str | None:
    """Read an exact generated prefix, not authenticate arbitrary C# or its intent.

    A staged binder must independently derive and check the expected commitment.
    The source hash binds the header bytes; the header itself proves no lowering
    correctness, document state, compiler provenance or execution permission.
    """
    if type(source) is not str:
        raise ConnectorPreparationError("invalid_input", "source must be text")
    if not source.startswith(EXECUTION_ASSOCIATION_PREFIX):
        return None
    line, separator, _ = source.partition("\n")
    if not separator:
        raise ConnectorPreparationError("invalid_association_digest", "association prefix must end with a newline")
    return _checked_association_digest(line[len(EXECUTION_ASSOCIATION_PREFIX):])


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConnectorPreparationError("invalid_input", f"{name} must be nonempty text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ConnectorPreparationError("invalid_input", f"{name} contains unpaired Unicode surrogates") from exc
    return value


def _uuid(value: Any, name: str) -> str:
    _text(value, name)
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ConnectorPreparationError("invalid_input", f"{name} must be a UUID") from exc


def _integer(value: Any, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ConnectorPreparationError("invalid_input", f"{name} must be an integer in [{low}, {high}]")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeTarget:
    journal_id: str
    instance_id: str
    revit_version: str

    def __post_init__(self):
        object.__setattr__(self, "journal_id", _uuid(self.journal_id, "journal_id"))
        object.__setattr__(self, "instance_id", _uuid(self.instance_id, "instance_id"))
        if UUID(self.journal_id).int == 0 or UUID(self.instance_id).int == 0:
            raise ConnectorPreparationError("invalid_input", "runtime identity UUIDs must be nonzero")
        if not isinstance(self.revit_version, str) or self.revit_version not in REVIT_VERSIONS:
            raise ConnectorPreparationError("unsupported_version", "target must name a supported Revit year")

    def to_dict(self) -> dict:
        return {"journal_id": self.journal_id, "instance_id": self.instance_id,
                "revit_version": self.revit_version}


@dataclass(frozen=True, slots=True)
class ContextPrecondition:
    document_key: str
    revision: int
    active_view_id: int | None = None
    selection_digest: str | None = None

    def __post_init__(self):
        _text(self.document_key, "document_key")
        _integer(self.revision, "revision", 0, _INT64_MAX)
        if self.active_view_id is not None:
            _integer(self.active_view_id, "active_view_id", -_INT64_MAX - 1, _INT64_MAX)
        if self.selection_digest is not None:
            # Preserve null vs empty and exact ordinal comparison, like native
            # OperationInputBinding. This is not an assertion of a valid capture.
            if not isinstance(self.selection_digest, str):
                raise ConnectorPreparationError("invalid_input", "selection_digest must be text or null")
            _text(self.selection_digest or "empty", "selection_digest")

    def to_dict(self) -> dict:
        return {"document_key": self.document_key, "revision": self.revision,
                "active_view_id": self.active_view_id, "selection_digest": self.selection_digest}


@dataclass(frozen=True, slots=True)
class SessionCredentials:
    target: RuntimeTarget
    session_id: str
    token: str = field(repr=False)

    def __post_init__(self):
        if type(self.target) is not RuntimeTarget:
            raise ConnectorPreparationError("invalid_input", "session target must be a RuntimeTarget")
        object.__setattr__(self, "session_id", _uuid(self.session_id, "session_id"))
        if UUID(self.session_id).int == 0:
            raise ConnectorPreparationError("invalid_input", "session_id must be nonzero")
        _text(self.token, "token")

    def context_request(self, *, request_id: str, timeout_ms: int = 30000) -> dict:
        """Prepare one read-only context request for this exact runtime/session.

        No connection or capture occurs here. A returned snapshot still needs
        response binding checks and the native pre-effect context recheck.
        """
        return _request(self, request_id, "context", timeout_ms)

    def ping_request(self, *, request_id: str, timeout_ms: int = 30000) -> dict:
        """Prepare a read-only readiness request, without model/context work.

        The response still requires exact route/session validation. Readiness
        does not renew an observation, authorize execution, or promise liveness
        after this particular response.
        """
        return _request(self, request_id, "ping", timeout_ms)


def _request(credentials, request_id, kind, timeout_ms, **fields) -> dict:
    if type(credentials) is not SessionCredentials:
        raise ConnectorPreparationError("invalid_input", "explicit session credentials are required")
    request = {"protocol": CONNECTOR_PROTOCOL, "request_id": _uuid(request_id, "request_id"),
               "target": credentials.target.to_dict(), "session_id": credentials.session_id,
               "token": credentials.token, "kind": kind,
               "timeout_ms": _integer(timeout_ms, "timeout_ms", 1000, 300000), **fields}
    wire = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(wire) > MAX_FRAME_BYTES:
        raise ConnectorPreparationError("frame_budget_exceeded", "encoded request exceeds Connector frame limit")
    return request


def wrap_connector_source(body: str) -> str:
    """Wrap a generated Execute body; this is NOT a validator for arbitrary C#."""
    _text(body, "Execute body")
    # Several current emitters close Execute, append nested helper types and
    # leave a padding method open. Their existing contract needs three closing
    # braces as well; don't parse/strip/rewrite their braces here.
    return ("using System;\nusing System.Collections.Generic;\nusing System.Linq;\nusing System.Text;\n"
            "using Autodesk.Revit.DB;\nusing Autodesk.Revit.UI;\n"
            "namespace Kir.Generated { public static class UserCode { "
            "public static object Execute(Document doc, UIDocument uidoc) {\n"
            + body + "\n} } }\n")


@dataclass(frozen=True, slots=True, init=False)
class PreparedExecution:
    """Fresh in-process preparation; no loader turns serialized claims into it.

    Frozen Python values prevent accidental mutation, not hostile in-process
    Python. Native target/binding/policy/journal checks remain mandatory.
    """
    target: RuntimeTarget
    precondition: ContextPrecondition
    operation_id: str
    source: str = field(repr=False)
    source_sha256: str
    planned: PlannedProgram = field(repr=False)
    grounded: GroundedProgram | None = field(repr=False)
    # Retain exactly the explicit inputs forwarded to the compiler. This is
    # not native capture/freshness evidence; future submission binders need to
    # distinguish omitted guards without parsing generated C#.
    expected_identities: tuple[ElementIdentityProof, ...] = field(repr=False)
    association_digest: str | None

    def __init__(self, *args, **kwargs):
        raise TypeError("use prepare_execution(); a stored record is not fresh compiler evidence")

    def binding_dict(self) -> dict:
        return {"target": self.target.to_dict(), "operation_id": self.operation_id,
                "source_sha256": self.source_sha256, "precondition": self.precondition.to_dict()}

    def execute_request(self, credentials: SessionCredentials, *, request_id: str,
                        timeout_ms: int = 120000) -> dict:
        self._same_target(credentials)
        return _request(credentials, request_id, "execute", timeout_ms,
                        operation_id=self.operation_id, source=self.source,
                        source_sha256=self.source_sha256, precondition=self.precondition.to_dict())

    def receipt_request(self, credentials: SessionCredentials, *, request_id: str) -> dict:
        self._same_target(credentials)
        return _request(credentials, request_id, "receipt", 30000, operation_id=self.operation_id)

    def recovery_request(self, credentials: SessionCredentials, *, request_id: str) -> dict:
        # The serving session may be B after a restart. The original operation
        # still belongs to A; this explicitly read-only API never rebinds it.
        return _request(credentials, request_id, "recover_receipt", 30000,
                        recovery_target=self.target.to_dict(), operation_id=self.operation_id)

    def _same_target(self, credentials):
        if type(credentials) is not SessionCredentials or credentials.target != self.target:
            raise ConnectorPreparationError("target_mismatch", "operation belongs to a different runtime/journal")


def prepare_execution(program: Any, *, target: RuntimeTarget,
                      precondition: ContextPrecondition, operation_id: str,
                      bulk: bool = False,
                      isolation: str = "atomic",
                      association_digest: str | None = None,
                      expected_identities: Sequence[ElementIdentityProof] | None = None) -> PreparedExecution:
    """Compile one exact plan for its target, without dispatch or a legacy guard.

    The native runtime enforces precondition, not generated doc.PathName code.
    Source SHA covers the FULL wrapped source. Rotating session credentials do
    not change it or the original binding. No external snapshot is accepted by
    this first seam; no snapshot-to-native-context equivalence is invented.
    Bulk changes the operation budget only. Transaction isolation is a separate
    explicit policy; its emitted code is included in the bound source hash.

    Optional element identities are caller-supplied guard inputs, not proof of
    capture. Their existing compiler guard is included in the source hash.
    VersionGuid does not detect individual in-session edits: a write based on
    observed values must retain that observation's precondition, not replace
    it with a later context. Explicit identity guards are write-only because
    the current compiler does not emit them for queries.
    """
    if type(target) is not RuntimeTarget or type(precondition) is not ContextPrecondition:
        raise ConnectorPreparationError("invalid_input", "typed target and precondition are required")
    if type(bulk) is not bool:
        raise ConnectorPreparationError("invalid_input", "bulk must be bool")
    if type(isolation) is not str or isolation not in ("atomic", "per_op"):
        raise ConnectorPreparationError("invalid_input", "isolation must be atomic or per_op")
    if association_digest is not None:
        _checked_association_digest(association_digest)
    identities = None
    if expected_identities is not None:
        if (isinstance(expected_identities, (str, bytes, bytearray))
                or not isinstance(expected_identities, Sequence)):
            raise ConnectorPreparationError("invalid_identities", "expected typed element identity sequence")
        identities = tuple(expected_identities)
        if any(type(item) is not ElementIdentityProof for item in identities):
            raise ConnectorPreparationError("invalid_identities", "expected typed element identity sequence")
    identifier = _uuid(operation_id, "operation_id")
    result = compile_program(program, revit_version=target.revit_version, bulk=bulk, isolation=isolation,
                             expected_identities=identities)
    if not result.ok:
        raise ConnectorPreparationError("compile_refused", "KIR compiler refused the requested program",
                                        diagnostics=result.diagnostics)
    if not result.csharp or result.planned is None:
        raise ConnectorPreparationError("compiler_incomplete", "compiler returned no source or exact plan")
    if identities is not None and result.planned.family.value != "write":
        raise ConnectorPreparationError("identity_guard_requires_write", "query emission does not enforce element identities")
    second_document = tuple(sorted({op.op_name for op in result.planned.ops
                                    if op.op_name in SECOND_DOCUMENT_OPS}))
    if second_document:
        # The refusal happens HERE, not as a receipt from the other end:
        # nothing is assembled into an artifact, nothing is sent, and the
        # OP is named, not a Revit API member.
        raise ConnectorPreparationError(
            CONNECTOR_SECOND_DOCUMENT_UNAVAILABLE,
            "оп требует второго документа; недоступен на standalone-коннекторе: "
            + ", ".join(second_document))
    source = wrap_connector_source(result.csharp)
    if association_digest is not None:
        source = EXECUTION_ASSOCIATION_PREFIX + association_digest + "\n" + source
    if len(source.encode("utf-16-le")) // 2 > MAX_SOURCE_CHARS:
        raise ConnectorPreparationError("source_budget_exceeded", "wrapped source exceeds Connector UTF-16 limit")
    artifact = object.__new__(PreparedExecution)
    for name, value in {"target": target, "precondition": precondition, "operation_id": identifier,
                        "source": source, "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        "planned": result.planned, "grounded": result.grounded,
                        "association_digest": association_digest,
                        "expected_identities": identities or ()}.items():
        object.__setattr__(artifact, name, value)
    return artifact


__all__ = ["CONNECTOR_PROTOCOL", "ConnectorPreparationError", "RuntimeTarget",
           "SECOND_DOCUMENT_OPS", "CONNECTOR_SECOND_DOCUMENT_UNAVAILABLE",
           "ContextPrecondition", "SessionCredentials", "PreparedExecution",
           "prepare_execution", "wrap_connector_source", "source_association_digest",
           "EXECUTION_ASSOCIATION_PREFIX"]
