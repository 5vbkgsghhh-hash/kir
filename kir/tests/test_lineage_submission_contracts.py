"""Signed native lineage must agree across project and staged archive readers."""
from copy import deepcopy
import hashlib
from uuid import uuid4

import pytest

from kir.project import _canonical, _hash
from kir.project_submission import ProjectSubmissionError
from kir.saved_execution import SavedExecutionRecord


def resign(value, key):
    value[key] = _hash({k: v for k, v in value.items() if k != key})


def validate(record):
    from kir.project_submission import validate_submission_claims
    validate_submission_claims(record["project_submission"], execution=record["binding"],
        plan_evidence=record["plan_evidence"], planned_units=record["planned_units"],
        grounded_evidence=record["grounded_evidence"], source=record["source"])


def bind_plan_hashes(record):
    plan, data = record["plan_evidence"], record["project_submission"]
    resign(plan, "plan_digest")
    data["plan_digest"] = plan["plan_digest"]
    ground = record["grounded_evidence"]
    if ground is not None:
        ground["plan_digest"] = plan["plan_digest"]
        resign(ground, "ground_digest")
        data["grounded_evidence_digest"] = ground["ground_digest"]


@pytest.mark.parametrize("selected", [False, True])
def test_foreign_signed_native_owner_cannot_belong_to_the_same_project(selected, monkeypatch):
    from kir import project_submission as owner
    from kir.geometry_materialization import materialize_project, materialize_selection
    from kir.project_selection import select_project_instances
    from kir.tests.test_project_submission import project, prepare

    source = project({"op": "create_level", "elev_mm": 0})
    materialized = (materialize_selection(source, select_project_instances(source, instance_keys=["i"]), {})
                    if selected else materialize_project(source, {}))
    prepared = prepare(materialized)
    binder = owner.bind_selected_project_submission if selected else owner.bind_project_submission
    record = SavedExecutionRecord.capture_project(prepared, binder(source, materialized, prepared)).to_dict()
    validate(record)
    record["plan_evidence"]["lineage"] = "foreign-project"
    bind_plan_hashes(record)
    resign(record["project_submission"], "submission_digest")
    with pytest.raises(ProjectSubmissionError, match="signed native lineage differs"):
        validate(record)
    # All other retained digests are coherent: removing THIS check is a real hole.
    original = owner._require
    def omit(check, code, message):
        if message != "signed native lineage differs from authored project":
            original(check, code, message)
    monkeypatch.setattr(owner, "_require", omit)
    validate(record)


def staged_record():
    from kir.tests.test_staged_create_projection import case, project
    from kir.staged_create_projection import prepare_staged_create
    from kir.staged_submission import bind_staged_project_submission
    projection = project(case())
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    binding = bind_staged_project_submission(projection, prepared)
    return SavedExecutionRecord.capture_project(prepared, binding).to_dict()


def resign_staged(record):
    """Resign the retained association graph, NOT native execution evidence."""
    bind_plan_hashes(record)
    data = record["project_submission"]
    resign(data["logical_plan_evidence"], "plan_digest")
    mat = data["materialization"]
    mat["plan_digest"] = data["logical_plan_evidence"]["plan_digest"]
    resign(mat, "materialization_digest")
    data["materialization_digest"] = mat["materialization_digest"]
    part = data["partition"]
    part["materialization_digest"] = mat["materialization_digest"]
    resign(part, "partition_digest")
    projection = data["projection"]
    previous = projection["association_digest"]
    core = projection["association_core"]
    core["partition_digest"] = part["partition_digest"]
    core["runtime_plan_digest"] = record["plan_evidence"]["plan_digest"]
    core["runtime_program_digest"] = _hash(projection["runtime_program"])
    projection["association_digest"] = _hash(core)
    record["source"] = record["source"].replace(previous, projection["association_digest"], 1)
    record["binding"]["source_sha256"] = hashlib.sha256(record["source"].encode()).hexdigest()
    data["execution"] = deepcopy(record["binding"])
    resign(data, "submission_digest")


@pytest.mark.parametrize("old_side", ["logical", "runtime"])
def test_mixed_staged_lineage_contracts_are_not_a_legacy_archive(old_side, monkeypatch):
    from kir import staged_submission as owner
    record = staged_record()
    validate(record)
    data = record["project_submission"]
    plan = data["logical_plan_evidence"] if old_side == "logical" else record["plan_evidence"]
    plan["schema"] = "kir-planned-program/4"
    del plan["lineage"]
    if old_side == "runtime":
        del data["projection"]["runtime_program"]["lineage"]
    resign_staged(record)
    with pytest.raises(ProjectSubmissionError, match="mixed logical/runtime lineage contracts"):
        validate(record)
    original = owner._need
    monkeypatch.setattr(owner, "_need", lambda check, message:
        original(check, message) if message != "mixed logical/runtime lineage contracts" else None)
    validate(record)


def test_current_staged_archive_round_trips_with_explicit_unchanged_identity():
    record = staged_record()
    assert all(row["identity_replacement"] is None
               for row in record["project_submission"]["projection"]["association_core"]["import_lineage"])
    validate(record)
    raw = _canonical(record).encode("utf-8")
    loaded = SavedExecutionRecord._from_bytes(raw)
    assert loaded._raw == raw and loaded.to_dict() == record


def test_a_replacement_summary_is_not_persisted_as_a_confirmed_ledger():
    record = staged_record()
    row = record["project_submission"]["projection"]["association_core"]["import_lineage"][0]
    row["identity_replacement"] = {"ledger_digest": "a" * 64}
    resign_staged(record)
    with pytest.raises(ProjectSubmissionError, match="identity replacement persistence"):
        validate(record)
