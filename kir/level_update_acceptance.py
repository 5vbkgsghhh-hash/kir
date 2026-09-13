"""Independent field/manifest acceptance for the single-Level update profile.

No model read, write, retry, rollback, persistence or current-context refresh.
Geometry and engineering remain unevaluated even when this narrow scope passes.
"""
from dataclasses import dataclass, field
import json

from kir.connector_result import assess_connector_write_response, assess_connector_saved_level_update_response
from kir.project import _canonical, _hash, _object, _thaw
from kir.revit_connector import PreparedExecution, ContextPrecondition, RuntimeTarget
from kir.revit_level_update import LevelElevationUpdatePlan, LevelUpdateRefusal
from kir.revit_observation import ElementObservation


@dataclass(frozen=True, slots=True, init=False)
class LevelUpdateAcceptance:
    _report: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use assess_level_update; an imported report is not fresh acceptance")

    @property
    def scope_satisfied(self):
        return all(row["status"] == "satisfied" for row in self._report["checks"].values())

    @property
    def target_satisfied(self):
        return all(self._report["checks"][key]["status"] == "satisfied"
                   for key in ("execution_target", "target_elevation"))

    def to_dict(self):
        return _thaw(self._report)


def _fields(row):
    """Only observed fields; VersionGuid is not a geometry/change oracle."""
    if row["status"] != "observed" or (row["is_level"] and row["level_status"] != "observed"):
        return None
    typed = row["type_state"]
    if typed is None or typed["status"] == "unavailable":
        return None
    return {"name": row["name"], "category_id": row["category_id"], "is_level": row["is_level"],
        "type_uid": typed["element_identity"]["unique_id"] if typed["status"] == "observed" else None,
        "level_status": row["level_status"], "level": row["level"]}


def assess_level_update(update, prepared, response, *, credentials, request_id, after) -> LevelUpdateAcceptance:
    """Retain execution outcome while separately assessing the selected scope.

    A mismatching after-read never changes a committed execution into rollback.
    The native change manifest covers the invocation, not every external edit
    between the two observations. Observed field equality is not body equality.
    """
    if type(update) is not LevelElevationUpdatePlan or type(prepared) is not PreparedExecution or type(after) is not ElementObservation:
        raise LevelUpdateRefusal("update_acceptance_inputs_required", "expected fresh plan/preparation and parsed after-observation")
    if (prepared.target != update.target or prepared.precondition != update.precondition
        or prepared.expected_identities != update.expected_identities
        or _canonical(prepared.planned.to_evidence_dict()) != _canonical(update.planned.to_evidence_dict())
        or _canonical(prepared.planned.units) != _canonical(update.planned.units)):
        raise LevelUpdateRefusal("update_preparation_mismatch", "preparation does not retain the planned mutation/baseline/guards")
    execution = assess_connector_write_response(prepared, response, credentials=credentials, request_id=request_id)
    return _assess_level_fields(expected=update.to_dict(), op=update.planned.to_ops()[0],
        before_rows=update.before_observation.rows, before_precondition=update.precondition,
        target=update.target, publication_rows=update.original_binding["outputs"],
        operation_id=prepared.operation_id, execution=execution, after=after)


def assess_saved_level_update(record, response, *, credentials, request_id, after,
                               recovery=False) -> LevelUpdateAcceptance:
    """Assess a recovered update against retained baseline and a fresh read.

    No Plan/Observation is reconstructed from archived claims. The after-read
    must still be from the ORIGINAL runtime/document; a new recovery server is
    a receipt route, not proof that it reopened the same live document. The
    report cannot by itself promote a ProjectStore revision or authorize replay.
    """
    from kir.saved_execution import SavedExecutionRecord, UPDATE_ARCHIVE_SCHEMA
    if type(record) is not SavedExecutionRecord or type(after) is not ElementObservation:
        raise LevelUpdateRefusal("saved_update_acceptance_inputs_required", "checked archive and parsed after-observation required")
    data = record.to_dict()
    if data["schema"] != UPDATE_ARCHIVE_SCHEMA:
        raise LevelUpdateRefusal("saved_update_archive_required", "Archive/3 update association required")
    execution = assess_connector_saved_level_update_response(record, response, credentials=credentials,
        request_id=request_id, recovery=recovery)
    submission, binding = data["update_submission"], data["binding"]
    return _assess_level_fields(expected=submission["update"], op=data["plan_evidence"]["ops"][0]["payload"],
        before_rows=submission["before_observation"]["rows"],
        before_precondition=ContextPrecondition(**binding["precondition"]),
        target=RuntimeTarget(**binding["target"]), publication_rows=submission["original_publication"]["outputs"],
        operation_id=binding["operation_id"], execution=execution, after=after, archive_digest=record.digest)


def _assess_level_fields(*, expected, op, before_rows, before_precondition, target,
                         publication_rows, operation_id, execution, after, archive_digest=None):
    """One field/manifest comparison for fresh inputs and qualified saved claims."""
    checks = {key: {"status": "not_evaluated", "reason": "execution_contract_not_satisfied"}
              for key in ("execution_target", "target_elevation", "protected_fields", "protected_changes")}
    report = {"schema": "kir-level-update-acceptance/1", "mutation_plan_digest": expected["mutation_plan_digest"],
        "operation_id": operation_id, "execution": execution.outcome.to_dict(),
        "execution_diagnostic": execution.diagnostic_code, "checks": checks,
        "after": {"operation_id": after.operation_id, "source_sha256": after.source_sha256,
                  "target": after.target.to_dict(), "precondition": after.precondition.to_dict()},
        "not_evaluated": ["dependent_geometry", "protected_geometry", "engineering"], "may_retry": False}
    if archive_digest is not None:
        report.update(schema="kir-saved-level-update-acceptance/1", archive_digest=archive_digest,
                      baseline_evidence="retained_archive_claims", project_revision_promoted=False)

    def finish():
        accepted = object.__new__(LevelUpdateAcceptance)
        object.__setattr__(accepted, "_report", _object(report, "level_update_acceptance"))
        return accepted

    if not execution.ok:
        return finish()
    receipt = execution.receipt
    report["receipt_digest"] = _hash(receipt)
    target_uid = expected["target_identity"]["unique_id"]
    target_id = expected["target_identity"]["element_id"]
    returned = json.loads(receipt["result_json"])
    target_result = returned.get(op["id"]) if isinstance(returned, dict) else None
    # The single set_param emitter writes id/param and an optional localized
    # display string. Extra controls must not hide behind a valid id. This is
    # deliberately NOT a generic rule for arbitrary registry result rows.
    supported_row = (type(target_result) is dict and set(target_result) <= {"id", "param", "value"}
                     and (target_result.get("value") is None or type(target_result["value"]) is str))
    correct_target = (supported_row and target_result.get("id") == str(target_id)
                      and target_result.get("param") == op["param"]
                      and target_id not in receipt["changes"]["added"] + receipt["changes"]["deleted"])
    checks["execution_target"] = {"status": "satisfied" if correct_target else "violated",
                                    "reason": "unsupported_setter_result_row" if not supported_row else
                                    "matching_target_and_parameter" if correct_target else "result_target_or_parameter_mismatch"}
    after_rows = after.rows
    if (after.target != target or after.precondition.document_key != before_precondition.document_key
        or after.precondition.revision <= before_precondition.revision or set(after_rows) != set(before_rows)):
        for key in ("target_elevation", "protected_fields", "protected_changes"):
            checks[key]["reason"] = "after_scope_or_revision_mismatch"
        return finish()

    target = after_rows[target_uid]
    if target["status"] == "not_found":
        checks["target_elevation"] = {"status": "violated", "reason": "target_missing"}
    elif target["status"] == "observed" and target["element_identity"]["element_id"] != target_id:
        checks["target_elevation"] = {"status": "not_evaluated", "reason": "target_identity_address_changed"}
    elif target["status"] == "observed" and target["level_status"] == "observed":
        level = target["level"]
        wanted, tolerance = expected["new_elev_mm"], expected["setter_tolerance_mm"]
        matched = level["elevation_base"] == 0 and all(abs(value - wanted) <= tolerance for value in (
            level["project_elevation_mm"], level["reported_elevation_mm"],
            level["elevation_parameter"]["value_internal_feet"] * 304.8))
        checks["target_elevation"] = {"status": "satisfied" if matched else "violated",
                                      "reason": "target_value_matches" if matched else "target_value_or_basis_mismatch"}
    else:
        checks["target_elevation"]["reason"] = "target_read_incomplete"

    protected_ids = set(expected["protected_output_ids"])
    protected_uids = {row["element_identity"]["unique_id"] for row in publication_rows
                      if row["output_id"] in protected_ids}
    if not protected_uids:
        for key in ("protected_fields", "protected_changes"):
            checks[key]["reason"] = "no_protected_scope"
        return finish()
    fields_status, fields_reason = "satisfied", "observed_protected_fields_match"
    guarded_ids, addresses_stable = set(), True
    for uid in sorted(protected_uids):
        old, new = before_rows[uid], after_rows[uid]
        guarded_ids.add(old["element_identity"]["element_id"])
        if old["type_state"]["status"] == "observed":
            guarded_ids.add(old["type_state"]["element_identity"]["element_id"])
        if new["status"] == "not_found":
            fields_status, fields_reason = "violated", "protected_element_missing"
            addresses_stable = False
        elif _fields(old) is None or _fields(new) is None:
            if fields_status != "violated":
                fields_status, fields_reason = "not_evaluated", "protected_read_incomplete"
            addresses_stable = False
        else:
            if _canonical(_fields(old)) != _canonical(_fields(new)):
                fields_status, fields_reason = "violated", "observed_protected_fields_changed"
            if new["element_identity"]["element_id"] != old["element_identity"]["element_id"]:
                addresses_stable = False
            if (old["type_state"]["status"] == "observed" and new["type_state"]["status"] == "observed"
                and old["type_state"]["element_identity"]["element_id"] != new["type_state"]["element_identity"]["element_id"]):
                addresses_stable = False
    checks["protected_fields"] = {"status": fields_status, "reason": fields_reason}
    changes = receipt["changes"]
    touched = guarded_ids & set(changes["added"] + changes["modified"] + changes["deleted"])
    if touched:
        checks["protected_changes"] = {"status": "violated", "reason": "protected_ids_in_invocation_changes", "ids": sorted(touched)}
    elif changes["truncated"] or not addresses_stable:
        checks["protected_changes"]["reason"] = "change_scope_incomplete_or_addresses_remapped"
    else:
        checks["protected_changes"] = {"status": "satisfied", "reason": "protected_ids_absent_from_complete_invocation_manifest"}
    return finish()


__all__ = ["LevelUpdateAcceptance", "assess_level_update", "assess_saved_level_update"]
