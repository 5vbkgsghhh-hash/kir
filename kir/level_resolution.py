"""Bound native not-started evidence; no timeout inference or mutation replay.

Only a fresh qualification can clear a matching stored pending operation. The
store owns that atomic transition; historical payloads remain inert claims.
"""
from dataclasses import dataclass, field
import json

from kir.connector_result import (ConnectorResultAssessment, assess_connector_saved_level_update_response, _json,
    MAX_FRAME_BYTES, _target, _precondition, _RECEIPT_FIELDS, _consistent_before_start)
from kir.outcome import ExecutionState
from kir.project import _canonical, _hash, _object, _thaw
from kir.revit_connector import CONNECTOR_PROTOCOL, _uuid
from kir.saved_execution import SavedExecutionRecord, UPDATE_ARCHIVE_SCHEMA


RESOLUTION_SCHEMA = "kir-qualified-level-not-started/1"
MAX_RESOLUTION_BYTES = MAX_FRAME_BYTES + 16384
_CLAIMS = {"scope": "bound_native_not_started", "checkpoint_advance": "none", "retry_permission": "none"}


class LevelResolutionRefusal(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(value, code="invalid_level_resolution"):
    if not value:
        raise LevelResolutionRefusal(code)


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names.split()))


def _digest(value):
    _require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True, slots=True, init=False)
class QualifiedLevelNotStarted:
    digest: str
    record: SavedExecutionRecord = field(repr=False)
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use qualify_level_not_started; imported claims are not fresh qualification")

    def to_dict(self):
        return {**_thaw(self._payload), "resolution_digest": self.digest}


@dataclass(frozen=True, slots=True)
class LevelCancellationAttempt:
    """Outcome of journal control, not model rollback or mutation retry authority."""
    record: SavedExecutionRecord = field(repr=False)
    request_id: str
    response: bytes = field(repr=False)
    result: ConnectorResultAssessment = field(repr=False)
    resolution_digest: str | None = None
    storage_acknowledgement: str = "not_attempted"

    @property
    def resolution_recorded(self):
        # A later independent reservation may already exist; this is not a
        # claim that the stream's current pending slot is still empty.
        return self.resolution_digest is not None

    @property
    def may_retry(self):
        return False


def request_cancel_pending_level_update(store, *, stream_id, expected_pending_archive, advertisement, client_path,
                                       request_id, timeout_ms=30000) -> LevelCancellationAttempt:
    """Cancel only the explicitly named pending input in its original runtime.

    One journal-control exchange; no context read, compilation, model invocation
    or mutation retry. Only a bound NOT_STARTED response may resolve pending.
    A returned existing committed/started/unknown outcome needs its own readback
    or reconciliation path and leaves local pending untouched by this call.
    """
    from kir.project_store import ProjectStore, _RESOLUTION_SCHEMAS, StoreConflict, StoreCommitUnknown
    from kir.revit_discovery import DiscoveryAdvertisement
    from kir.revit_transport import exchange

    _require(type(store) is ProjectStore and not store.readonly, "writable_project_store_required")
    _require(store.schema in _RESOLUTION_SCHEMAS, "resolution_store_upgrade_required")
    _require(type(advertisement) is DiscoveryAdvertisement, "explicit_advertisement_required")
    _digest(expected_pending_archive)
    baseline = store.level_baseline(stream_id)
    _require(baseline.pending_archive_digest is not None, "no_pending_level_update")
    _require(baseline.pending_archive_digest == expected_pending_archive, "pending_level_update_changed")
    record = store.get_level_update_archive(baseline.pending_archive_digest)
    request_id = _uuid(request_id, "request_id")
    request = record.cancel_before_start_request(advertisement.credentials, request_id=request_id,
                                                 timeout_ms=timeout_ms)
    raw = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    response = exchange(advertisement, raw, client_path=client_path, timeout_ms=timeout_ms)
    assessment = assess_connector_saved_level_update_response(record, response,
        credentials=advertisement.credentials, request_id=request_id)
    if not (assessment.binding_matches and assessment.diagnostic_code == "not_started"
            and assessment.outcome.execution is ExecutionState.NOT_STARTED):
        return LevelCancellationAttempt(record, request_id, assessment.raw_response, assessment)
    qualified = qualify_level_not_started(record, response, credentials=advertisement.credentials,
                                         request_id=request_id)
    try:
        committed = store.commit_level_not_started(qualified, expected_checkpoint=baseline.checkpoint_digest,
                                                   expected_pending_archive=record.digest)
        digest = committed.resolution_digest
        acknowledgement = "committed" if committed.inserted else "already_recorded"
    except (StoreConflict, StoreCommitUnknown):
        # Another controller or a lost COMMIT acknowledgement may have recorded
        # the SAME native receipt through a different response request ID. Read
        # exact archived evidence; never retry a write or clear a newer pending.
        existing = store.get_level_resolution_for_archive(record.digest)
        if existing is None or existing["receipt_digest"] != qualified.to_dict()["receipt_digest"]:
            raise
        digest, acknowledgement = existing["resolution_digest"], "read_back"
    return LevelCancellationAttempt(record, request_id, assessment.raw_response, assessment, digest, acknowledgement)


def qualify_level_not_started(record, response, *, credentials, request_id,
                              recovery=False) -> QualifiedLevelNotStarted:
    """Require a complete, bound native before-start receipt, never absence.

    NOT_STARTED describes this exact operation identity. It neither grants
    replay nor proves that the surrounding model is unchanged/current. A new
    mutation needs an explicit fresh plan/context and a new reservation.
    """
    _require(type(record) is SavedExecutionRecord and record.to_dict()["schema"] == UPDATE_ARCHIVE_SCHEMA,
             "level_update_archive_required")
    assessment = assess_connector_saved_level_update_response(record, response, credentials=credentials,
        request_id=request_id, recovery=recovery)
    _require(assessment.binding_matches and assessment.diagnostic_code == "not_started"
             and assessment.outcome.execution is ExecutionState.NOT_STARTED, "bound_not_started_required")
    native_response, _ = _json(response, MAX_FRAME_BYTES)
    submitted = record.update_submission
    original, update = submitted["original_publication"], submitted["update"]
    payload = {"schema": RESOLUTION_SCHEMA, "archive_digest": record.digest,
        "original_binding_digest": original["binding_digest"], "project_id": original["project"]["project_id"],
        "base_revision": update["base_revision"], "proposed_revision": update["proposed_revision"],
        "execution": record.binding_dict(), "response": native_response,
        "receipt_digest": _hash(assessment.receipt), "claims": dict(_CLAIMS)}
    result = object.__new__(QualifiedLevelNotStarted)
    object.__setattr__(result, "digest", _hash(payload))
    object.__setattr__(result, "record", record)
    object.__setattr__(result, "_payload", _object(payload, "level_not_started"))
    validate_level_not_started_claims(result.to_dict(), record)
    return result


def validate_level_not_started_claims(value, record):
    """Validate historical links/shape without manufacturing fresh authority.

    The response route can be recovery B while its receipt must name original
    A. A stored route is not authentication; fresh qualification takes explicit
    selected credentials and reuses the Connector's route/binding validator.
    """
    try:
        _require(type(record) is SavedExecutionRecord and record.to_dict()["schema"] == UPDATE_ARCHIVE_SCHEMA,
                 "level_update_archive_required")
        _fields(value, "schema archive_digest original_binding_digest project_id base_revision proposed_revision execution response receipt_digest claims resolution_digest")
        _require(value["schema"] == RESOLUTION_SCHEMA and value["claims"] == _CLAIMS)
        _require(len(_canonical(value).encode("utf-8")) <= MAX_RESOLUTION_BYTES, "level_resolution_budget_exceeded")
        for key in ("archive_digest", "original_binding_digest", "base_revision", "proposed_revision", "receipt_digest", "resolution_digest"):
            _digest(value[key])
        _require(value["resolution_digest"] == _hash({k: v for k, v in value.items() if k != "resolution_digest"}))
        submitted = record.update_submission
        original, update, binding = submitted["original_publication"], submitted["update"], record.binding_dict()
        _require(value["archive_digest"] == record.digest and value["original_binding_digest"] == original["binding_digest"]
                 and value["project_id"] == original["project"]["project_id"]
                 and value["base_revision"] == update["base_revision"] and value["proposed_revision"] == update["proposed_revision"]
                 and _canonical(value["execution"]) == _canonical(binding))
        response = value["response"]
        _fields(response, "protocol request_id target session_id ok status error context receipt")
        _require(response["protocol"] == CONNECTOR_PROTOCOL and response["ok"] is True
                 and response["status"] == "receipt" and response["error"] is None and response["context"] is None)
        _target(response["target"])
        _require(_uuid(response["request_id"], "request_id") == response["request_id"]
                 and _uuid(response["session_id"], "session_id") == response["session_id"])
        receipt = response["receipt"]
        _require(type(receipt) is dict and set(receipt) == _RECEIPT_FIELDS
                 and value["receipt_digest"] == _hash(receipt))
        _require(_consistent_before_start(receipt))
        _require(receipt["semantic_evidence"] == "unverified"
                 and type(receipt["timestamp_utc"]) is str and bool(receipt["timestamp_utc"].strip())
                 and (receipt["error"] is None or type(receipt["error"]) is str))
        _require(_target(receipt["target"]) == _target(binding["target"]))
        _require(_precondition(receipt["precondition"]) == _precondition(binding["precondition"])
                 and receipt["document_key"] == binding["precondition"]["document_key"]
                 and receipt["operation_id"] == binding["operation_id"]
                 and type(receipt["source_sha256"]) is str
                 and receipt["source_sha256"].lower() == binding["source_sha256"])
    except LevelResolutionRefusal:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise LevelResolutionRefusal("invalid_level_resolution") from error


__all__ = ["RESOLUTION_SCHEMA", "MAX_RESOLUTION_BYTES", "QualifiedLevelNotStarted", "LevelResolutionRefusal",
           "qualify_level_not_started", "validate_level_not_started_claims", "LevelCancellationAttempt",
           "request_cancel_pending_level_update"]
