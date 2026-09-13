"""Qualified field evidence for settling one reserved native Level update.

This is not a whole-building realization, engineering approval or retry ticket.
Only the factory creates fresh qualification; persisted payloads remain claims.
The ProjectStore owner separately checks source history and pending/head CAS.
"""
from dataclasses import dataclass, field

from kir.connector_result import (_json, MAX_FRAME_BYTES, _target, _precondition,
                                  _RECEIPT_FIELDS, _manifest)
from kir.level_update_acceptance import assess_saved_level_update
from kir.project import _canonical, _hash, _object, _thaw
from kir.revit_connector import _uuid, CONNECTOR_PROTOCOL
from kir.revit_observation import ElementObservation, _validate_row
from kir.saved_execution import SavedExecutionRecord, UPDATE_ARCHIVE_SCHEMA


SETTLEMENT_SCHEMA = "kir-qualified-level-settlement/1"
MAX_SETTLEMENT_BYTES = 32 * 1024 * 1024
_CLAIMS = {"scope": "observed_level_fields_only", "geometry": "not_established",
           "engineering": "not_established", "retry_permission": "none"}


class LevelSettlementRefusal(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(value, code="invalid_level_settlement"):
    if not value:
        raise LevelSettlementRefusal(code)


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names.split()))


def _digest(value):
    _require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value))


@dataclass(frozen=True, slots=True, init=False)
class QualifiedLevelSettlement:
    digest: str
    record: SavedExecutionRecord = field(repr=False)
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use qualify_level_settlement; stored claims are not fresh qualification")

    def to_dict(self):
        return {**_thaw(self._payload), "settlement_digest": self.digest}


def qualify_level_settlement(record, response, *, after, credentials, request_id,
                             recovery=False) -> QualifiedLevelSettlement:
    """Qualify a reserved archive's field outcome; never touch store or Revit.

    A new parsed after-observation is mandatory even after Python restart. The
    same original runtime/document must still be observed; recovery route B
    does not rebind A's document. Failed/unknown scope cannot create settlement.
    """
    _require(type(record) is SavedExecutionRecord and type(after) is ElementObservation,
             "level_settlement_inputs_required")
    _require(record.to_dict()["schema"] == UPDATE_ARCHIVE_SCHEMA, "level_update_archive_required")
    assessment = assess_saved_level_update(record, response, credentials=credentials,
        request_id=request_id, after=after, recovery=recovery)
    _require(assessment.scope_satisfied, "level_scope_not_satisfied")
    native_response, _ = _json(response, MAX_FRAME_BYTES)
    submitted = record.update_submission
    update = submitted["update"]
    payload = {"schema": SETTLEMENT_SCHEMA, "archive_digest": record.digest,
        "original_binding_digest": submitted["original_publication"]["binding_digest"],
        "project_id": submitted["original_publication"]["project"]["project_id"],
        "base_revision": update["base_revision"], "proposed_revision": update["proposed_revision"],
        "execution": record.binding_dict(), "response": native_response,
        "after": {"target": after.target.to_dict(), "precondition": after.precondition.to_dict(),
            "operation_id": after.operation_id, "source_sha256": after.source_sha256, "rows": after.rows},
        "assessment": assessment.to_dict(), "claims": dict(_CLAIMS)}
    settled = object.__new__(QualifiedLevelSettlement)
    object.__setattr__(settled, "record", record)
    object.__setattr__(settled, "digest", _hash(payload))
    object.__setattr__(settled, "_payload", _object(payload, "level_settlement"))
    validate_level_settlement_claims(settled.to_dict(), record)
    return settled


def validate_level_settlement_claims(value, record):
    """Check retained storage relations, NOT replay/authenticate qualification.

    No credential, observation or write plan is reconstructed. A consistent
    record can be returned as historical data, never QualifiedLevelSettlement.
    Hashes and internal links detect corruption, not a malicious store rewrite.
    """
    try:
        _require(type(record) is SavedExecutionRecord, "level_update_archive_required")
        _require(record.to_dict()["schema"] == UPDATE_ARCHIVE_SCHEMA, "level_update_archive_required")
        _fields(value, "schema archive_digest original_binding_digest project_id base_revision proposed_revision execution response after assessment claims settlement_digest")
        _require(value["schema"] == SETTLEMENT_SCHEMA and value["claims"] == _CLAIMS)
        _require(len(_canonical(value).encode("utf-8")) <= MAX_SETTLEMENT_BYTES, "level_settlement_budget_exceeded")
        for key in ("archive_digest", "original_binding_digest", "base_revision", "proposed_revision", "settlement_digest"):
            _digest(value[key])
        _require(value["settlement_digest"] == _hash({k: v for k, v in value.items() if k != "settlement_digest"}))
        submitted = record.update_submission
        original, update = submitted["original_publication"], submitted["update"]
        binding = record.binding_dict()
        _require(value["archive_digest"] == record.digest
                 and value["original_binding_digest"] == original["binding_digest"]
                 and value["project_id"] == original["project"]["project_id"]
                 and value["base_revision"] == update["base_revision"]
                 and value["proposed_revision"] == update["proposed_revision"]
                 and _canonical(value["execution"]) == _canonical(binding))
        after = value["after"]
        _fields(after, "target precondition operation_id source_sha256 rows")
        _require(_uuid(after["operation_id"], "after operation_id") == after["operation_id"])
        _digest(after["source_sha256"])
        _require(_target(after["target"]) == _target(binding["target"]))
        context, before = _precondition(after["precondition"]), _precondition(binding["precondition"])
        _require(context.document_key == before.document_key and context.revision > before.revision)
        _require(type(after["rows"]) is dict and set(after["rows"]) == set(submitted["before_observation"]["rows"]))
        for uid, row in after["rows"].items():
            _validate_row(row, uid)
            _require(row["status"] == "observed")
        report = value["assessment"]
        _fields(report, "schema mutation_plan_digest operation_id execution execution_diagnostic checks after not_evaluated may_retry archive_digest baseline_evidence project_revision_promoted receipt_digest")
        _require(report["schema"] == "kir-saved-level-update-acceptance/1"
                 and report["mutation_plan_digest"] == submitted["plan_digest"]
                 and report["operation_id"] == binding["operation_id"]
                 and report["archive_digest"] == record.digest
                 and report["baseline_evidence"] == "retained_archive_claims"
                 and report["may_retry"] is False and report["project_revision_promoted"] is False
                 and report["execution_diagnostic"] == "kir_result_assessed"
                 and report["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"])
        _require(report["execution"] == {"schema_version": "kir-program-outcome/1", "execution": "committed",
            "witness": "satisfied", "acceptance": "not_run", "retry": "forbidden"})
        _require(_canonical(report["after"]) == _canonical({k: v for k, v in after.items() if k != "rows"}))
        _fields(report["checks"], "execution_target target_elevation protected_fields protected_changes")
        _require(all(type(check) is dict and check.get("status") == "satisfied" for check in report["checks"].values()))
        response = value["response"]
        _fields(response, "protocol request_id target session_id ok status error context receipt")
        _require(response["protocol"] == CONNECTOR_PROTOCOL
                 and _uuid(response["request_id"], "request_id") == response["request_id"]
                 and _uuid(response["session_id"], "session_id") == response["session_id"])
        _target(response["target"])
        _require(response["ok"] is True and response["status"] == "receipt" and response["error"] is None
                 and response["context"] is None and type(response["receipt"]) is dict)
        _require(report["receipt_digest"] == _hash(response["receipt"]))
        receipt = response["receipt"]
        _require(set(receipt) == _RECEIPT_FIELDS and receipt["state"] == "invocation_completed"
                 and receipt["started"] is True and receipt["may_retry"] is False
                 and receipt["error"] is None and receipt["result_error"] is None
                 and receipt["result_truncated"] is False and receipt["semantic_evidence"] == "unverified")
        changed = _manifest(receipt["changes"])
        _require(receipt["changes"]["truncated"] is False
                 and receipt["transaction_evidence"] == ("changes_observed" if changed else "changes_not_observed"))
        _require(all(_canonical(receipt.get(k)) == _canonical(v) for k, v in binding.items())
                 and receipt.get("document_key") == before.document_key)
    except LevelSettlementRefusal:
        raise
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError) as error:
        raise LevelSettlementRefusal("invalid_level_settlement") from error


__all__ = ["SETTLEMENT_SCHEMA", "MAX_SETTLEMENT_BYTES", "LevelSettlementRefusal",
           "QualifiedLevelSettlement", "qualify_level_settlement", "validate_level_settlement_claims"]
