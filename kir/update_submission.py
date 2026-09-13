"""Fresh association for a prepared single-Level mutation; no storage or dispatch.

Serialized values retain claims and the exact baseline needed for recovery.
Validation of those claims does not reconstruct a fresh update/observation or
prove that a native operation ran. Full Project history remains caller-owned.
"""
from dataclasses import dataclass, field
import math

from kir.project import _canonical, _hash, _object, _thaw, _key, output_id, PROJECT_SCHEMA, PROJECT_SCHEMA_V2
from kir.revit_connector import PreparedExecution, _uuid
from kir.connector_result import _precondition, _target
from kir.revit_level_update import (LevelElevationUpdatePlan, ORIGINAL_BINDINGS_SCHEMA,
                                    LEGACY_ORIGINAL_BINDINGS_SCHEMA, _ORIGINAL_CLAIMS,
                                    _UPDATE_PLAN_CLAIMS, _CAPTURE)
from kir.revit_observation import _validate_row
from kir.contracts import ElementIdentityProof


UPDATE_SUBMISSION_SCHEMA = "kir-submitted-level-update/1"
ITERATIVE_UPDATE_SUBMISSION_SCHEMA = "kir-submitted-level-update/2"
_CLAIMS = {"association": "matched_fresh_update_preparation", "project_persistence": "not_established",
    "native_execution": "not_established", "dispatch_state": "not_recorded", "retry_permission": "none",
    "retained_evidence": "claims_not_fresh_observation", "engineering_acceptance": "not_established"}


class UpdateSubmissionError(ValueError):
    pass


def _require(value, message):
    if not value:
        raise UpdateSubmissionError(message)


def _fields(value, names):
    _require(type(value) is dict and set(value) == set(names.split()), "invalid update submission fields")


def _digest(value):
    _require(type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value), "invalid update submission digest")


def _hashed(value, field_name):
    _digest(value[field_name])
    _require(_hash({k: v for k, v in value.items() if k != field_name}) == value[field_name], "update evidence digest mismatch")


@dataclass(frozen=True, slots=True, init=False)
class SubmittedLevelUpdate:
    digest: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use bind_level_update_submission; stored claims are not a fresh binding")

    def to_dict(self):
        return {**_thaw(self._payload), "submission_digest": self.digest}


def bind_level_update_submission(update, prepared) -> SubmittedLevelUpdate:
    _require(type(update) is LevelElevationUpdatePlan and type(prepared) is PreparedExecution,
             "fresh update plan and preparation required")
    _require(prepared.target == update.target and prepared.precondition == update.precondition
             and prepared.expected_identities == update.expected_identities
             and _canonical(prepared.planned.to_evidence_dict()) == _canonical(update.planned.to_evidence_dict())
             and _canonical(prepared.planned.units) == _canonical(update.planned.units),
             "prepared mutation differs from update plan/baseline/guards")
    before = update.before_observation
    payload = {"schema": UPDATE_SUBMISSION_SCHEMA, "execution": prepared.binding_dict(),
        "plan_digest": prepared.planned.plan_digest, "update": update.to_dict(),
        "original_publication": update.original_binding,
        "before_observation": {"target": before.target.to_dict(), "precondition": before.precondition.to_dict(),
            "operation_id": before.operation_id, "source_sha256": before.source_sha256, "rows": before.rows},
        "expected_identities": [proof.to_dict() for proof in prepared.expected_identities], "claims": dict(_CLAIMS)}
    if update.baseline is not None:
        payload.update(schema=ITERATIVE_UPDATE_SUBMISSION_SCHEMA, baseline_ref={
            "store_id": update.baseline.store_id, "stream_id": update.baseline.stream_id,
            "checkpoint_digest": update.baseline.checkpoint_digest,
            "base_revision": update.baseline.baseline_revision})
    submitted = object.__new__(SubmittedLevelUpdate)
    object.__setattr__(submitted, "digest", _hash(payload))
    object.__setattr__(submitted, "_payload", _object(payload, "level_update_submission"))
    validate_update_submission_claims(submitted.to_dict(), execution=prepared.binding_dict(),
                                      plan_evidence=prepared.planned.to_evidence_dict(), planned_units=list(prepared.planned.units))
    return submitted


def validate_update_submission_claims(value, *, execution, plan_evidence, planned_units):
    """Check retained relations only; never re-plan, read Revit or grant replay."""
    try:
        iterative = type(value) is dict and value.get("schema") == ITERATIVE_UPDATE_SUBMISSION_SCHEMA
        _fields(value, "schema execution plan_digest update original_publication before_observation expected_identities claims submission_digest"
                + (" baseline_ref" if iterative else ""))
        _require(value["schema"] in (UPDATE_SUBMISSION_SCHEMA, ITERATIVE_UPDATE_SUBMISSION_SCHEMA)
                 and value["claims"] == _CLAIMS, "unsupported update claims")
        _hashed(value, "submission_digest")
        _require(_canonical(value["execution"]) == _canonical(execution), "update execution binding differs")
        _require(value["plan_digest"] == plan_evidence["plan_digest"] and plan_evidence["family"] == "write"
                 and len(plan_evidence["ops"]) == 1 and planned_units == [], "update requires the exact one-op write profile")
        op = plan_evidence["ops"][0]["payload"]
        _fields(op, "id op param target value")
        _fields(op["target"], "by value")
        _fields(op["value"], "type v")
        _require(type(op["id"]) is str and 1 <= len(op["id"]) <= 64
                 and op["id"] == op["id"].strip(), "invalid retained mutation id")
        _require(type(op["param"]) is str and bool(op["param"].strip()), "invalid retained parameter name")
        _require(type(op["target"]["value"]) is int and 0 < op["target"]["value"] < (1 << 63), "invalid retained element id")
        _require(type(op["value"]["v"]) in (int, float) and math.isfinite(op["value"]["v"]), "invalid retained mm value")
        _require(op["op"] == "set_param" and op["target"]["by"] == "element_id" and op["value"]["type"] == "mm", "unsupported update mutation")
        report = value["update"]
        _fields(report, "schema original_binding_digest base_revision proposed_revision target_output_id old_elev_mm new_elev_mm baseline_tolerance_mm setter_tolerance_mm observation target_identity protected_output_ids affected_output_ids mutation_plan_digest claims")
        _require(report["schema"] == "kir-level-elevation-update-plan/1" and report["mutation_plan_digest"] == value["plan_digest"], "update report plan differs")
        _require(report["claims"] == _UPDATE_PLAN_CLAIMS, "update report cannot upgrade execution/acceptance claims")
        for key in ("base_revision", "proposed_revision", "target_output_id", "original_binding_digest"):
            _digest(report[key])
        for key in ("old_elev_mm", "new_elev_mm", "baseline_tolerance_mm", "setter_tolerance_mm"):
            _require(type(report[key]) in (int, float) and math.isfinite(report[key]), "invalid update numeric claim")
        _require(report["baseline_tolerance_mm"] > 0 and report["setter_tolerance_mm"] > 0
                 and report["old_elev_mm"] != report["new_elev_mm"] and report["base_revision"] != report["proposed_revision"], "empty or invalid update claim")
        _require(report["new_elev_mm"] == op["value"]["v"], "update target value differs from mutation")
        original = value["original_publication"]
        # 🔴 TWO SHAPES, ONE READER, AND NEITHER MAY BE GUESSED. A `/2` binding
        # carries what it refused; a `/1` one predates the possibility of
        # refusing anything and therefore asserts a complete binding. Accepting
        # the extended key set for BOTH would let a `/1` record omit the fields
        # and read as "no refusals" by accident instead of by its own claim.
        legacy = original.get("schema") == LEGACY_ORIGINAL_BINDINGS_SCHEMA
        _fields(original, "schema profile project archive_digest submission_digest receipt_digest"
                          " execution outputs warnings claims binding_digest"
                          + ("" if legacy else " refused_outputs binding_completeness"))
        _require(original["schema"] in (ORIGINAL_BINDINGS_SCHEMA, LEGACY_ORIGINAL_BINDINGS_SCHEMA)
                 and original["profile"] == "original-flat-create/1", "unsupported original profile")
        if not legacy:
            _require(original["binding_completeness"] in ("complete", "partial"),
                     "invalid binding completeness")
            refused_rows = original["refused_outputs"]
            _require(type(refused_rows) is list, "invalid refused outputs")
            _require((original["binding_completeness"] == "partial") == bool(refused_rows),
                     "binding completeness disagrees with the refused outputs it lists")
            for refused_row in refused_rows:
                _require(type(refused_row) is dict and type(refused_row.get("state")) is str
                         and refused_row["state"].startswith("original_")
                         and type(refused_row.get("reason")) is str
                         and type(refused_row.get("address")) is list,
                         "invalid refused output row")
        _require(original["claims"] == _ORIGINAL_CLAIMS, "original binding cannot upgrade authority claims")
        _hashed(original, "binding_digest")
        for key in ("archive_digest", "submission_digest", "receipt_digest"):
            _digest(original[key])
        _fields(original["project"], "project_id schema revision_id")
        _key(original["project"]["project_id"], "project_id")
        _require(original["project"]["schema"] in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2), "unsupported original project schema")
        _fields(original["execution"], "target operation_id source_sha256 precondition")
        _require(_uuid(original["execution"]["operation_id"], "original operation_id") == original["execution"]["operation_id"], "noncanonical original operation")
        _digest(original["execution"]["source_sha256"])
        _precondition(original["execution"]["precondition"])
        _digest(original["project"]["revision_id"])
        _require(original["binding_digest"] == report["original_binding_digest"], "original source binding differs")
        if iterative:
            reference = value["baseline_ref"]
            _fields(reference, "store_id stream_id checkpoint_digest base_revision")
            _require(type(reference["store_id"]) is str and len(reference["store_id"]) == 32
                     and all(c in "0123456789abcdef" for c in reference["store_id"]), "invalid baseline store identity")
            for key in ("stream_id", "checkpoint_digest", "base_revision"):
                _digest(reference[key])
            _require(reference["stream_id"] == original["binding_digest"]
                     and reference["base_revision"] == report["base_revision"]
                     and report["base_revision"] != original["project"]["revision_id"], "iterative baseline reference differs")
        else:
            _require(original["project"]["revision_id"] == report["base_revision"], "original source revision differs")
        before = value["before_observation"]
        _fields(before, "target precondition operation_id source_sha256 rows")
        _require(_uuid(before["operation_id"], "observation operation_id") == before["operation_id"], "noncanonical observation operation")
        _digest(before["source_sha256"])
        _require(type(before["rows"]) is dict and bool(before["rows"]), "missing before observation")
        _require(_canonical({k: before[k] for k in ("target", "precondition", "operation_id", "source_sha256")})
                 == _canonical(report["observation"]), "before observation reference differs")
        _require(_target(before["target"]) == _target(execution["target"])
                 == _target(original["execution"]["target"]), "update crosses original runtime")
        _require(_precondition(before["precondition"]) == _precondition(execution["precondition"])
                 and before["precondition"]["document_key"] == original["execution"]["precondition"]["document_key"], "update changes observed document/revision")
        outputs = original["outputs"]
        _require(type(outputs) is list and bool(outputs), "original output scope missing")
        original_ids = set()
        for row in outputs:
            _fields(row, "instance_key output_key output_id source_op authored_output_digest module_key compiled_op_id element_identity")
            _require(row["source_op"] in _CAPTURE and row["compiled_op_id"] == row["output_id"], "unsupported original output claim")
            _digest(row["output_id"])
            _digest(row["authored_output_digest"])
            for key in ("instance_key", "output_key", "module_key"):
                _key(row[key], key)
            _require(row["output_id"] == output_id(original["project"]["project_id"], row["instance_key"], row["output_key"]), "original output address differs")
            _fields(row["element_identity"], "schema_version element_id unique_id version_guid")
            proof = ElementIdentityProof.from_dict(row["element_identity"])
            _require(proof.element_id not in original_ids, "original native address repeats")
            original_ids.add(proof.element_id)
        by_output = {row["output_id"]: row for row in outputs}
        uids = {row["element_identity"]["unique_id"] for row in outputs}
        _require(len(by_output) == len(outputs) == len(uids) and set(before["rows"]) == uids, "original/before scope differs or repeats")
        protected, affected = report["protected_output_ids"], report["affected_output_ids"]
        _require(type(protected) is list and type(affected) is list and len(set(protected)) == len(protected)
                 and len(set(affected)) == len(affected), "invalid dependency/protection claims")
        for digest in protected + affected:
            _digest(digest)
        _require(set(by_output) == {report["target_output_id"], *protected}
                 and report["target_output_id"] not in protected and not set(protected) & set(affected), "update protection scope differs")
        target_uid = by_output[report["target_output_id"]]["element_identity"]["unique_id"]
        _require(by_output[report["target_output_id"]]["source_op"] == "create_level", "update target was not an authored Level")
        guards, guard_uids = {}, {}
        for uid, row in before["rows"].items():
            _validate_row(row, uid)
            _require(row["status"] == "observed" and row["type_state"]["status"] in {"observed", "none"}, "unqualified before identity")
            proofs = [row["element_identity"]]
            if row["type_state"]["status"] == "observed": proofs.append(row["type_state"]["element_identity"])
            for proof in proofs:
                parsed = ElementIdentityProof.from_dict(proof)
                _require(guards.get(parsed.element_id, proof) == proof and guard_uids.get(parsed.unique_id, proof) == proof, "conflicting retained guards")
                guards[parsed.element_id] = proof
                guard_uids[parsed.unique_id] = proof
        _require(type(value["expected_identities"]) is list
                 and _canonical(value["expected_identities"]) == _canonical([guards[key] for key in sorted(guards)]), "retained guard set differs from observation")
        target = before["rows"][target_uid]
        _require(_canonical(report["target_identity"]) == _canonical(target["element_identity"])
                 and op["target"]["value"] == target["element_identity"]["element_id"], "mutation targets another observed element")
        _require(target["level_status"] == "observed" and target["type_state"]["status"] == "observed", "target lacks observed level/type")
        level, parameter = target["level"], target["level"]["elevation_parameter"]
        _require(level["elevation_base"] == 0 and parameter["name"] == op["param"] and parameter["is_read_only"] is False
                 and parameter["name_match_count"] == 1 and parameter["name_resolves_builtin"] is True, "retained parameter cannot support this update")
        _require(all(abs(number - report["old_elev_mm"]) <= report["baseline_tolerance_mm"] for number in (
            level["project_elevation_mm"], level["reported_elevation_mm"], parameter["value_internal_feet"] * 304.8)), "retained baseline differs")
    except UpdateSubmissionError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise UpdateSubmissionError("invalid retained update submission") from error


__all__ = ["UPDATE_SUBMISSION_SCHEMA", "ITERATIVE_UPDATE_SUBMISSION_SCHEMA", "UpdateSubmissionError", "SubmittedLevelUpdate",
           "bind_level_update_submission", "validate_update_submission_claims"]
