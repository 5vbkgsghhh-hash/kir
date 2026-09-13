"""Bind one Connector response before interpreting its KIR result.

The transport must already be the selected authenticated channel. Matching
fields is consistency checking, not authentication or proof of design intent.
No lookup/retry/dispatch occurs here; unknown never grants replay permission.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import re
from typing import Any, TYPE_CHECKING

from kir.bridge_result import (WriteResultAssessment, assess_write_result,
                              assess_saved_level_update_result, assess_saved_create_result)
from kir.outcome import ExecutionState, execution_unconfirmed, program_not_started
from kir.revit_connector import (
    CONNECTOR_PROTOCOL, MAX_FRAME_BYTES, ConnectorPreparationError,
    ContextPrecondition, PreparedExecution, RuntimeTarget, SessionCredentials,
    _uuid,
)

if TYPE_CHECKING:
    from kir.saved_execution import SavedExecutionRecord


MAX_RESULT_BYTES = 6 * 1024 * 1024
_RECEIPT_FIELDS = frozenset({
    "target", "operation_id", "source_sha256", "document_key", "precondition",
    "state", "started", "may_retry", "transaction_evidence", "semantic_evidence",
    "result_json", "result_truncated", "result_error", "error", "changes", "timestamp_utc",
})
_BEFORE_START = frozenset({"rejected_before_start", "context_changed_before_start", "cancelled_before_start"})
#: The connector's terminal state "a document outside the bound one was
#: touched" (`ReceiptStates.ForeignDocumentChanged`, ExecutionEngine).
#: 🔴 WHY IT IS NAMED HERE. An unknown state name would be read by this parser
#: as "terminal not confirmed" — safe, but nameless: the loudest thing the
#: engine can say arrived here as an ordinary "unclear". Retry is forbidden
#: FOREVER, and not out of caution: the foreign edit is already on its own
#: undo stack; our transaction never held it, and there is nothing for it to
#: roll back.
_FOREIGN_DOCUMENT_CHANGED = "foreign_document_changed"
_RESPONSE_FIELDS = frozenset({"protocol", "request_id", "target", "session_id", "ok",
                              "status", "error", "context", "receipt"})
_CONTEXT_FIELDS = frozenset({
    "has_document", "document_key", "document_title", "revit_version", "revision",
    "active_view_id", "selection_digest", "selection_count", "is_family_document",
    "is_read_only", "is_modifiable", "complete",
})


class _InvalidEvidence(ValueError):
    pass


def _json(source: Any, budget: int):
    if not isinstance(source, (str, bytes)):
        raise _InvalidEvidence("wire evidence must be UTF-8 JSON bytes or text")
    raw = source.encode("utf-8") if isinstance(source, str) else source
    if not raw or len(raw) > budget:
        raise _InvalidEvidence("JSON evidence is empty or exceeds its byte budget")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise _InvalidEvidence("duplicate JSON object key")
            result[key] = value
        return result

    def number(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise _InvalidEvidence("nonfinite JSON number")
        return parsed

    def constant(_value):
        raise _InvalidEvidence("nonfinite JSON constant")

    result = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                        parse_float=number, parse_constant=constant)
    # Escaped lone surrogates otherwise survive json.loads despite a valid
    # UTF-8 transport. Validate decoded strings without replacing their bytes.
    json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")

    def depth(value, level=0):
        if level > 64:
            raise _InvalidEvidence("JSON evidence exceeds native nesting limit")
        if isinstance(value, dict):
            for child in value.values():
                depth(child, level + 1)
        elif isinstance(value, list):
            for child in value:
                depth(child, level + 1)
    depth(result)
    return result, raw


def _target(value):
    if not isinstance(value, dict) or set(value) != {"journal_id", "instance_id", "revit_version"}:
        raise _InvalidEvidence("incomplete or unknown runtime target fields")
    return RuntimeTarget(**value)


def require_connector_ready_response(response: str | bytes, *, credentials: SessionCredentials,
                                     request_id: str) -> None:
    """Require one exact ping/ready response; no context or execution authority.

    The caller owns the selected authenticated transport. This check does not
    refresh a document observation or promise that the next request will run.
    Native errors and untrusted fields are never copied into its diagnostic.
    """
    try:
        if type(credentials) is not SessionCredentials:
            raise _InvalidEvidence("session credentials required")
        expected_request = _uuid(request_id, "request_id")
        payload, _ = _json(response, MAX_FRAME_BYTES)
        if (type(payload) is not dict or set(payload) != _RESPONSE_FIELDS
                or payload["protocol"] != CONNECTOR_PROTOCOL
                or payload["request_id"] != expected_request
                or _target(payload["target"]) != credentials.target
                or payload["session_id"] != credentials.session_id
                or payload["ok"] is not True or payload["status"] != "ready"
                or payload["error"] is not None or payload["context"] is not None
                or payload["receipt"] is not None):
            raise _InvalidEvidence("ready response does not match selected request")
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ConnectorPreparationError(
            "connector_not_ready", "Connector readiness was not confirmed for the selected session.") from None


def _precondition(value):
    if not isinstance(value, dict) or set(value) != {"document_key", "revision", "active_view_id", "selection_digest"}:
        raise _InvalidEvidence("incomplete or unknown context precondition fields")
    return ContextPrecondition(**value)


def _receipt_matches_input(artifact, receipt) -> bool:
    """Shared identity consistency only; not receipt validity or authentication."""
    return (isinstance(receipt, dict) and set(receipt) == _RECEIPT_FIELDS
            and _target(receipt["target"]) == artifact.target
            and _uuid(receipt["operation_id"], "receipt operation_id") == artifact.operation_id
            and isinstance(receipt["source_sha256"], str)
            and receipt["source_sha256"].lower() == artifact.source_sha256
            and receipt["document_key"] == artifact.precondition.document_key
            and _precondition(receipt["precondition"]) == artifact.precondition)


def validate_saved_receipt_binding(record, receipt) -> None:
    """Check inert receipt identity claims without credentials or compilation.

    Historical storage readers may use this to detect corruption. It cannot
    authenticate a channel, qualify state/commit/UIDs, or authorize replay.
    """
    try:
        if not _receipt_matches_input(_saved_input(record), receipt):
            raise ValueError("saved receipt binding differs from its input")
    except (ValueError, TypeError, KeyError) as error:
        raise ConnectorPreparationError("binding_mismatch", "saved receipt identity claims do not match") from error


def _manifest(value) -> bool:
    """Return whether named changes exist, not whether all effects were found."""
    if not isinstance(value, dict) or set(value) != {"added", "modified", "deleted", "transaction_names", "truncated"}:
        raise _InvalidEvidence("incomplete or unknown change manifest fields")
    if type(value["truncated"]) is not bool:
        raise _InvalidEvidence("change manifest truncation must be boolean")
    for name in ("added", "modified", "deleted"):
        if not isinstance(value[name], list) or any(
                type(i) is not int or not -(1 << 63) <= i < (1 << 63) for i in value[name]):
            raise _InvalidEvidence("change manifest IDs must be int64 arrays")
    if not isinstance(value["transaction_names"], list) or any(
            not isinstance(name, str) for name in value["transaction_names"]):
        raise _InvalidEvidence("transaction names must be a text array")
    return any(value[name] for name in ("added", "modified", "deleted"))


def _consistent_before_start(receipt: dict) -> bool:
    """Shared closed no-invocation evidence, after route/binding validation."""
    return (receipt["state"] in _BEFORE_START and receipt["started"] is False
            and receipt["may_retry"] is True and receipt["changes"] is None
            and receipt["transaction_evidence"] == "not_observed"
            and receipt["result_json"] is None and receipt["result_error"] is None
            and receipt["result_truncated"] is False)


def _receipt_metadata_valid(receipt):
    return (all(type(receipt[key]) is bool for key in ("started", "may_retry", "result_truncated"))
            and receipt["semantic_evidence"] == "unverified"
            and isinstance(receipt["timestamp_utc"], str) and bool(receipt["timestamp_utc"].strip())
            and all(receipt[key] is None or isinstance(receipt[key], str)
                    for key in ("error", "result_error", "result_json")))


def _response_reports_receipt(payload):
    """Outer receipt status barrier, separate from native content semantics."""
    return payload["ok"] is True and payload["status"] == "receipt" and payload.get("error") is None


def native_receipt_terminal_state(receipt) -> str | None:
    """Recognize a coherent terminal state claim, not commit/intent or a channel.

    RunningUnknown/OperationConflict/LegacyUnbound can be unpersisted responses
    and never qualify as a terminal journal receipt here. This reuses the same
    native metadata/manifest rules as response assessment; no model is queried.
    """
    try:
        if type(receipt) is not dict or set(receipt) != _RECEIPT_FIELDS or not _receipt_metadata_valid(receipt):
            return None
        state = receipt["state"]
        if state in _BEFORE_START:
            return state if _consistent_before_start(receipt) else None
        if receipt["started"] is not True or receipt["may_retry"] is not False:
            return None
        changes = receipt["changes"]
        changed = False if changes is None else _manifest(changes)
        expected = "not_observed" if changes is None else "changes_observed" if changed else "changes_not_observed"
        if receipt["transaction_evidence"] != expected:
            return None
        if state == "invocation_completed":
            return state if changes is not None and receipt["error"] is None else None
        if state in ("failed_after_observed_change", "failed_after_start_unknown"):
            if (receipt["error"] is not None and receipt["result_json"] is None
                    and receipt["result_error"] is None and receipt["result_truncated"] is False
                    and (changed if state == "failed_after_observed_change" else not changed)):
                return state
        if state == _FOREIGN_DOCUMENT_CHANGED:
            # A named terminal, not "unknown": the op started, retry
            # is forbidden (`may_retry is False` checked above), the reason is
            # named as an error, and the result is NOT published — a partial
            # effect must not look like a success. The bound document's
            # manifest may still be empty here: it describes ITS OWN
            # document, not someone else's.
            if (receipt["error"] is not None and receipt["result_json"] is None
                    and receipt["result_error"] is None and receipt["result_truncated"] is False):
                return state
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    return None


@dataclass(frozen=True, slots=True)
class ConnectorResultAssessment:
    assessment: WriteResultAssessment
    binding_matches: bool
    diagnostic_code: str
    raw_response: bytes = field(repr=False)
    _receipt_json: str | None = field(default=None, repr=False)
    archive_digest: str | None = None

    @property
    def ok(self) -> bool:
        return self.binding_matches and self.assessment.ok

    @property
    def outcome(self):
        return self.assessment.outcome

    @property
    def receipt(self) -> dict | None:
        """Detached original native receipt, including manifest completeness."""
        return json.loads(self._receipt_json) if self._receipt_json is not None else None


@dataclass(frozen=True, slots=True)
class ConnectorQueryAssessment:
    """A bound query payload, not validation of its operation-specific fields.

    Consumers must validate the requested observation's schema and completeness.
    The retained precondition is the one checked before this query, including
    when an old receipt is returned; it is never replaced by a newer context.
    No successful read grants permission to repeat an uncertain mutation.
    """

    result_available: bool
    binding_matches: bool
    diagnostic_code: str
    raw_response: bytes = field(repr=False)
    precondition: ContextPrecondition | None = None
    _receipt_json: str | None = field(default=None, repr=False)
    _result_json: str | None = field(default=None, repr=False)

    @property
    def result(self) -> dict | None:
        return json.loads(self._result_json) if self._result_json is not None else None

    @property
    def receipt(self) -> dict | None:
        return json.loads(self._receipt_json) if self._receipt_json is not None else None


@dataclass(frozen=True, slots=True)
class ConnectorSavedResultAssessment:
    """A response bound to archived input, not fresh compilation or BIM success.

    Availability does not validate the saved plan's per-op results, original
    element ownership, commit/intent, or change-manifest completeness. Those
    remain explicit obligations of the archived-publication consumer.
    """

    result_available: bool
    binding_matches: bool
    diagnostic_code: str
    archive_digest: str
    raw_response: bytes = field(repr=False)
    _receipt_json: str | None = field(default=None, repr=False)
    _result_json: str | None = field(default=None, repr=False)

    @property
    def result(self) -> dict | None:
        return json.loads(self._result_json) if self._result_json is not None else None

    @property
    def receipt(self) -> dict | None:
        return json.loads(self._receipt_json) if self._receipt_json is not None else None


@dataclass(frozen=True, slots=True)
class _ExecutionInput:
    """Private projection of an authoritative fresh artifact OR checked archive.

    No compiler evidence, source execution method, loader or write authority.
    """
    target: RuntimeTarget
    operation_id: str
    source_sha256: str
    precondition: ContextPrecondition
    family: str


def _prepared_input(artifact):
    if type(artifact) is not PreparedExecution:
        raise ConnectorPreparationError("invalid_input", "exact prepared artifact required")
    return _ExecutionInput(artifact.target, artifact.operation_id, artifact.source_sha256,
                           artifact.precondition, artifact.planned.family.value)


def assess_connector_write_response(artifact: PreparedExecution, response: str | bytes,
                                    *, credentials: SessionCredentials, request_id: str,
                                    recovery: bool = False) -> ConnectorResultAssessment:
    """Check route A/B and original binding before applying the common D1 logic.

    A successful invocation is not a commit. A complete typed KIR result may
    establish commit and its own witnesses, never independent BIM acceptance.
    Truncated native change manifests remain available, explicitly truncated;
    KIR witness satisfaction does not prove preservation of unrelated elements.
    """
    return _assess_connector_execution_response(_prepared_input(artifact), response, credentials=credentials,
        request_id=request_id, recovery=recovery, query=False, planned=artifact.planned)


def assess_connector_query_response(artifact: PreparedExecution, response: str | bytes,
                                    *, credentials: SessionCredentials,
                                    request_id: str) -> ConnectorQueryAssessment:
    """Require a bound query receipt and complete, empty native change manifest.

    Availability means that a JSON object from this exact query can be inspected,
    not that any requested element/value exists or that its fields are complete.
    Query errors/not-found rows remain payload for their typed consumer. This
    function performs no transport, context refresh, recovery or model write.
    """
    return _assess_connector_execution_response(_prepared_input(artifact), response, credentials=credentials,
        request_id=request_id, recovery=False, query=True)


def assess_connector_saved_write_response(record: SavedExecutionRecord, response: str | bytes, *,
        credentials: SessionCredentials, request_id: str, recovery: bool = False) -> ConnectorSavedResultAssessment:
    """Inspect a write receipt against saved input without recompilation.

    The record must have passed SavedExecutionRecord.create/load validation.
    Neither its retained plan claims nor this result become PreparedExecution.
    A recovered B response still has to carry the original A execution binding.
    No dispatch, retry, context refresh, source execution or archive mutation.
    """
    return _assess_connector_execution_response(_saved_input(record), response, credentials=credentials,
        request_id=request_id, recovery=recovery, query=False, archive_digest=record.digest)


def _saved_input(record):
    from kir.saved_execution import SavedExecutionRecord
    if type(record) is not SavedExecutionRecord:
        raise ConnectorPreparationError("invalid_input", "checked SavedExecutionRecord required")
    data = record.to_dict()
    binding = data["binding"]
    return _ExecutionInput(_target(binding["target"]), binding["operation_id"], binding["source_sha256"],
                           _precondition(binding["precondition"]), data["plan_evidence"]["family"])


def assess_connector_saved_create_response(record: SavedExecutionRecord, response: str | bytes, *,
        credentials: SessionCredentials, request_id: str, recovery: bool = False) -> ConnectorResultAssessment:
    """D1 for a retained flat CREATE publication, not native UID qualification."""
    from kir.saved_execution import PROJECT_ARCHIVE_SCHEMA
    expected = _saved_input(record)
    if record.to_dict()["schema"] != PROJECT_ARCHIVE_SCHEMA:
        raise ConnectorPreparationError("invalid_input", "Archive/2 project publication required")
    return _assess_connector_execution_response(expected, response, credentials=credentials,
        request_id=request_id, recovery=recovery, query=False, saved_create=record)


def assess_connector_saved_level_update_response(record: SavedExecutionRecord, response: str | bytes, *,
        credentials: SessionCredentials, request_id: str, recovery: bool = False) -> ConnectorResultAssessment:
    """D1 for checked Archive/3, not a reconstructed plan or accepted baseline.

    Uses the same route/native/D1/rollback-scope checks as fresh execution, with
    the closed retained single-setter result contract. The returned archive
    digest names the evidence origin; no historical compiler replay is implied.
    """
    from kir.saved_execution import UPDATE_ARCHIVE_SCHEMA
    expected = _saved_input(record)
    if record.to_dict()["schema"] != UPDATE_ARCHIVE_SCHEMA:
        raise ConnectorPreparationError("invalid_input", "Archive/3 level update required")
    return _assess_connector_execution_response(expected, response, credentials=credentials,
        request_id=request_id, recovery=recovery, query=False, saved_update=record)


@dataclass(frozen=True, slots=True)
class _NativeContentAssessment:
    assessment: WriteResultAssessment | None
    diagnostic_code: str
    result: Any = None


def _assess_native_receipt_content(receipt, *, query=False, inspect_saved=False,
                                   planned=None, saved_update=None, saved_create=None):
    """Shared content-only native/D1 rules, AFTER independent binding checks."""
    def unknown(code, detail):
        return _NativeContentAssessment(WriteResultAssessment(execution_unconfirmed(),
            {"code": code, "message": detail}), code)
    try:
        if not isinstance(receipt, dict) or set(receipt) != _RECEIPT_FIELDS or not _receipt_metadata_valid(receipt):
            return unknown("invalid_receipt", "unsupported semantic, timestamp or result metadata")
        state = receipt["state"]
        if state in _BEFORE_START:
            if not _consistent_before_start(receipt):
                return unknown("contradictory_before_start", "before-start receipt conflicts with execution evidence")
            return _NativeContentAssessment(WriteResultAssessment(program_not_started()), "not_started")
        if state == _FOREIGN_DOCUMENT_CHANGED:
            # The refusal is NAMED by its own name, not dumped into the general
            # "state does not confirm a return". The BOUND document's outcome
            # is genuinely unknown here, so the kind of outcome stays the same.
            return unknown(_FOREIGN_DOCUMENT_CHANGED,
                           "a document outside the bound one was changed; retry is forbidden")
        if (state != "invocation_completed" or receipt["started"] is not True
                or receipt["may_retry"] is not False or receipt["error"] is not None):
            return unknown("native_state_unconfirmed", "return/commit is not established by this native state")
        changed = _manifest(receipt["changes"])
        if receipt["transaction_evidence"] != ("changes_observed" if changed else "changes_not_observed"):
            return unknown("contradictory_change_manifest", "native change marker disagrees with its manifest")
        if receipt["result_truncated"] or receipt["result_error"] is not None:
            return unknown("incomplete_result", "native result was truncated or could not be serialized")
        result, _ = _json(receipt["result_json"], MAX_RESULT_BYTES)
        if inspect_saved:
            if not isinstance(result, dict):
                return unknown("invalid_saved_result", "saved write result must be a JSON object")
            return _NativeContentAssessment(None, "saved_result_available", result)
        if query:
            if changed or receipt["changes"]["truncated"] or receipt["changes"]["transaction_names"]:
                return unknown("query_changes_unconfirmed", "query observation needs a complete empty change manifest")
            if not isinstance(result, dict):
                return unknown("invalid_query_result", "query result must be a JSON object")
            return _NativeContentAssessment(None, "query_result_available", result)
        assessment = (assess_saved_level_update_result(result, saved_update) if saved_update is not None
                      else assess_saved_create_result(result, saved_create) if saved_create is not None
                      else assess_write_result(result, planned))
        if assessment.outcome.execution is ExecutionState.ROLLED_BACK and (
                changed or receipt["changes"]["truncated"]):
            return unknown("rollback_scope_unconfirmed", "inner rollback does not account for the native observed-change scope")
        if saved_update is not None and assessment.diagnostic is not None and assessment.diagnostic.get("code") == "unsupported_saved_update_profile":
            return _NativeContentAssessment(assessment, "unsupported_saved_update_profile", result)
        if saved_create is not None and assessment.diagnostic is not None and assessment.diagnostic.get("code") == "unsupported_saved_create_profile":
            return _NativeContentAssessment(assessment, "unsupported_saved_create_profile", result)
        return _NativeContentAssessment(assessment, "kir_result_assessed", result)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
        return unknown("invalid_evidence", str(error))


def assess_saved_create_receipt(record: SavedExecutionRecord, receipt) -> WriteResultAssessment:
    """Re-derive native content/D1 consistency, not authentication or dispatch.

    This does not replace the response route/status barrier or authenticate a
    stored receipt. Bound-response callers must preserve the outer assessment
    barrier: a discrepancy cannot upgrade an unknown outcome.
    """
    from kir.saved_execution import SavedExecutionRecord, PROJECT_ARCHIVE_SCHEMA
    if type(record) is not SavedExecutionRecord:
        raise ConnectorPreparationError("invalid_input", "checked Archive/2 required")
    checked = SavedExecutionRecord._from_bytes(record._raw)
    if checked.digest != record.digest or checked.to_dict()["schema"] != PROJECT_ARCHIVE_SCHEMA:
        raise ConnectorPreparationError("invalid_input", "checked Archive/2 identity differs")
    validate_saved_receipt_binding(checked, receipt)
    return _assess_native_receipt_content(receipt, saved_create=checked).assessment


def _assess_connector_execution_response(artifact, response, *, credentials,
                                         request_id, recovery, query, planned=None, archive_digest=None,
                                         saved_update=None, saved_create=None):
    """One native validator; fresh and retained update D1 share rollback checks."""
    if type(artifact) is not _ExecutionInput or type(credentials) is not SessionCredentials:
        raise ConnectorPreparationError("invalid_input", "exact expected input and session credentials required")
    if type(recovery) is not bool:
        raise ConnectorPreparationError("invalid_input", "recovery must be bool")
    expected_request = _uuid(request_id, "request_id")
    if not recovery and artifact.target != credentials.target:
        raise ConnectorPreparationError("target_mismatch", "operation belongs to a different runtime/journal")
    raw, receipt, bound = b"", None, False

    def finish(assessment, code):
        encoded = json.dumps(receipt, ensure_ascii=False, separators=(",", ":")) if receipt is not None else None
        if archive_digest is not None:
            return ConnectorSavedResultAssessment(False, bound, code, archive_digest, raw, encoded)
        if query:
            return ConnectorQueryAssessment(False, bound, code, raw, _receipt_json=encoded)
        origin = saved_update if saved_update is not None else saved_create
        return ConnectorResultAssessment(assessment, bound, code, raw, encoded,
                                         origin.digest if origin is not None else None)

    def unknown(code, detail):
        assessment = None if query or archive_digest is not None else WriteResultAssessment(execution_unconfirmed(),
                      {"code": code, "message": detail})
        return finish(assessment, code)

    try:
        if isinstance(response, str):
            raw = response.encode("utf-8")
        elif isinstance(response, bytes):
            raw = response
        if len(raw) > MAX_FRAME_BYTES:
            raw = b""  # Do not retain over-budget input as an evidence archive.
            return unknown("response_budget_exceeded", "response exceeds native frame budget")
        payload, raw = _json(response, MAX_FRAME_BYTES)
        if not isinstance(payload, dict) or set(payload) != _RESPONSE_FIELDS:
            return unknown("invalid_envelope", "incomplete or unknown Connector response fields")
        if payload["context"] is not None:
            return unknown("invalid_envelope", "an execution receipt cannot also be a context response")
        if (payload.get("protocol") != CONNECTOR_PROTOCOL
                or payload.get("request_id") != expected_request
                or _target(payload.get("target")) != credentials.target
                or payload.get("session_id") != credentials.session_id):
            return unknown("route_mismatch", "response is not from the expected protocol/request/runtime/session")
        if type(payload.get("ok")) is not bool or not isinstance(payload.get("status"), str):
            return unknown("invalid_envelope", "response requires explicit typed status and ok")
        if artifact.family != ("query" if query else "write"):
            return unknown("query_plan_required" if query else "write_plan_required",
                           "query and write results require separate contracts")
        receipt = payload.get("receipt")
        if not isinstance(receipt, dict):
            receipt = None
            # Includes not_found, compile_rejected, timeout and recovery_busy.
            # A duplicate request may still have been queued or started.
            return unknown("receipt_unavailable", "no original bound receipt; do not replay from absence")
        if set(receipt) != _RECEIPT_FIELDS:
            return unknown("invalid_receipt", "incomplete or unknown native receipt fields")
        if not _receipt_matches_input(artifact, receipt):
            return unknown("binding_mismatch", "receipt belongs to a different original execution input")
        bound = True
        if not _receipt_metadata_valid(receipt):
            return unknown("invalid_receipt", "unsupported semantic, timestamp or result metadata")
        if not _response_reports_receipt(payload):
            return unknown("native_state_unconfirmed", "transport does not report a terminal receipt")
        content = _assess_native_receipt_content(receipt, query=query, inspect_saved=archive_digest is not None,
            planned=planned, saved_update=saved_update, saved_create=saved_create)
        if content.diagnostic_code == "saved_result_available":
            return ConnectorSavedResultAssessment(True, bound, content.diagnostic_code, archive_digest, raw,
                json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                json.dumps(content.result, ensure_ascii=False, separators=(",", ":")))
        if content.diagnostic_code == "query_result_available":
            return ConnectorQueryAssessment(True, bound, content.diagnostic_code, raw,
                artifact.precondition,
                json.dumps(receipt, ensure_ascii=False, separators=(",", ":")),
                json.dumps(content.result, ensure_ascii=False, separators=(",", ":")))
        return finish(content.assessment, content.diagnostic_code)
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError) as error:
        # No fallback string matching and no exception-derived rollback.
        # Bounded raw bytes and any already decoded native receipt are retained
        # for inspection, without upgrading malformed evidence to a verdict.
        return unknown("invalid_evidence", str(error))


@dataclass(frozen=True, slots=True)
class ConnectorContextAssessment:
    """Bound read response, not an authenticated channel or a document lease.

    A complete no-document capture is a successful observation but cannot yield
    a precondition. Family/read-only/modifiable flags remain observations, not
    permission to write. The native execution boundary must capture again.
    """

    target: RuntimeTarget
    session_id: str
    request_id: str
    binding_matches: bool
    diagnostic_code: str
    raw_response: bytes = field(repr=False)
    _snapshot_json: str | None = field(default=None, repr=False)

    @property
    def snapshot(self) -> dict | None:
        """Detached typed snapshot, including an explicitly incomplete capture."""
        return json.loads(self._snapshot_json) if self._snapshot_json is not None else None

    @property
    def read_complete(self) -> bool:
        value = self.snapshot
        return self.binding_matches and value is not None and value["complete"] is True

    def require_precondition(self, *, bind_view: bool, bind_selection: bool) -> ContextPrecondition:
        """Use the opaque open-document identity; never infer it from a title.

        Both UI choices must be explicit. False means intentionally omit that
        condition, not that the UI cannot change. No grounding census, write
        readiness, persisted BIM identity or observation freshness is implied.
        """
        if type(bind_view) is not bool or type(bind_selection) is not bool:
            raise ConnectorPreparationError("invalid_input", "view/selection binding choices must be booleans")
        value = self.snapshot
        if not self.read_complete or value is None or not value["has_document"]:
            raise ConnectorPreparationError("context_unavailable", "a complete bound open-document capture is required")
        return ContextPrecondition(value["document_key"], value["revision"],
            value["active_view_id"] if bind_view else None,
            value["selection_digest"] if bind_selection else None)


def _context_snapshot(value, target: RuntimeTarget) -> dict:
    if not isinstance(value, dict) or set(value) != _CONTEXT_FIELDS:
        raise _InvalidEvidence("incomplete or unknown context fields")
    flags = ("has_document", "is_family_document", "is_read_only", "is_modifiable", "complete")
    if any(type(value[key]) is not bool for key in flags):
        raise _InvalidEvidence("context flags must be explicit booleans")
    if any(not isinstance(value[key], str) for key in (
            "document_key", "document_title", "revit_version", "selection_digest")):
        raise _InvalidEvidence("context text fields must be strings")
    for key, low, high in (("revision", 0, (1 << 63) - 1),
                           ("active_view_id", -(1 << 63), (1 << 63) - 1),
                           ("selection_count", 0, (1 << 31) - 1)):
        if type(value[key]) is not int or not low <= value[key] <= high:
            raise _InvalidEvidence("context counter/id has an invalid type or range")
    if ((value["revit_version"] and value["revit_version"] != target.revit_version)
            or (value["complete"] and value["revit_version"] != target.revit_version)):
        raise _InvalidEvidence("context version differs from the selected runtime")
    if not value["complete"]:
        return value  # Retain the observation; it cannot become a precondition.
    if value["has_document"]:
        if (not value["document_key"].strip()
                or re.fullmatch(r"[0-9a-f]{64}", value["selection_digest"]) is None):
            raise _InvalidEvidence("complete document capture lacks its opaque identity or selection digest")
        if ((value["selection_count"] == 0)
                != (value["selection_digest"] == hashlib.sha256(b"").hexdigest())):
            raise _InvalidEvidence("selection count contradicts its native empty-selection digest")
    elif any(value[key] != empty for key, empty in (
            ("document_key", ""), ("document_title", ""), ("revision", 0),
            ("active_view_id", 0), ("selection_digest", ""), ("selection_count", 0),
            ("is_family_document", False), ("is_read_only", False), ("is_modifiable", False))):
        raise _InvalidEvidence("no-document capture contains contradictory document fields")
    return value


def assess_connector_context_response(response: str | bytes, *, credentials: SessionCredentials,
                                      request_id: str) -> ConnectorContextAssessment:
    """Parse the actual ContextSnapshot DTO on the explicitly selected route.

    Uses the same bounded strict JSON decoder as write receipts. The caller
    must establish the authenticated transport; these bytes alone cannot prove
    when or where a capture happened. No retry, lookup or compilation occurs.
    """
    if type(credentials) is not SessionCredentials:
        raise ConnectorPreparationError("invalid_input", "exact session credentials required")
    expected_request = _uuid(request_id, "request_id")
    raw, snapshot, bound = b"", None, False

    def finish(code):
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")) if snapshot is not None else None
        return ConnectorContextAssessment(credentials.target, credentials.session_id, expected_request,
                                          bound, code, raw, encoded)

    try:
        if isinstance(response, str):
            raw = response.encode("utf-8")
        elif isinstance(response, bytes):
            raw = response
        if len(raw) > MAX_FRAME_BYTES:
            raw = b""
            return finish("response_budget_exceeded")
        payload, raw = _json(response, MAX_FRAME_BYTES)
        if (not isinstance(payload, dict) or set(payload) != _RESPONSE_FIELDS
                or payload["receipt"] is not None
                or type(payload["ok"]) is not bool or not isinstance(payload["status"], str)
                or (payload["error"] is not None and not isinstance(payload["error"], str))):
            return finish("invalid_envelope")
        if (payload["protocol"] != CONNECTOR_PROTOCOL or payload["request_id"] != expected_request
                or _target(payload["target"]) != credentials.target
                or payload["session_id"] != credentials.session_id):
            return finish("route_mismatch")
        bound = True
        if payload["ok"] is not True or payload["status"] != "context" or payload["error"] is not None:
            return finish("context_unavailable")
        snapshot = _context_snapshot(payload["context"], credentials.target)
        return finish("context_incomplete" if not snapshot["complete"] else
                      "context_captured" if snapshot["has_document"] else "no_document")
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        # Never interpolate an untrusted document title/token into diagnostics.
        return finish("invalid_context_evidence")


__all__ = ["ConnectorResultAssessment", "assess_connector_write_response",
           "ConnectorQueryAssessment", "assess_connector_query_response",
           "ConnectorSavedResultAssessment", "assess_connector_saved_write_response",
           "assess_connector_saved_create_response", "assess_saved_create_receipt",
           "validate_saved_receipt_binding",
           "native_receipt_terminal_state",
           "assess_connector_saved_level_update_response",
           "ConnectorContextAssessment", "assess_connector_context_response",
           "require_connector_ready_response"]
