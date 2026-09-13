"""Independent discrepancy controls through the real observation parser.

All wire contents are synthetic. Actual planning/archive association and query
field validation are exercised; no native type definition or live freshness is
inferred from a captured identity or a matched link.
"""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir.create_publication import bind_create_receipt
from kir.create_type_discrepancy import assess_create_type_discrepancies, CreateTypeDiscrepancyError
from kir.geometry_materialization import materialize_selection
from kir.project import ModuleInstance, ProjectRevision, output_id
from kir.project_selection import select_project_instances
from kir.project_submission import bind_selected_project_submission
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.revit_observation import ObservationRefusal
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_create_type_discrepancy import scenario, observation, assess, bind, consumer, project
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_revit_observation import identity


@pytest.mark.parametrize("own_type", ["observed", "unavailable"])
def test_expected_native_type_output_cannot_itself_claim_an_instance_type(tmp_path, own_type):
    case = scenario(tmp_path)
    def change(rows):
        if own_type == "observed":
            rows["uid-wall-type"]["type_state"] = {"status": "observed", **identity(1777, "other-type")}
        else:
            rows["uid-wall-type"]["type_state"] = {"status": "unavailable", "element_identity": None,
                "element_identity_status": "unavailable", "element_identity_reason": "identity_unreadable"}
    observed = observation(case, mutate=change)  # Accepted by the existing generic owner.
    data = assess(case, observed).to_dict()
    assert consumer(data)["state"] != "matched", data


def test_replayed_revision_bound_observation_does_not_claim_current_freshness(tmp_path):
    case = scenario(tmp_path)
    recorded_read = observation(case)
    first = assess(case, recorded_read)
    again = assess(case, recorded_read)
    assert again.digest == first.digest  # This pure API has no current-runtime input.
    data = again.to_dict()
    assert data["claims"].get("current_model_state") == "not_established", data["claims"]
    assert not data["claims"]["comparison"].startswith("fresh_")
    assert not consumer(data)["diagnostic"].startswith("fresh_")


@pytest.mark.parametrize("key,seed", [("floor", 400), ("contour", 400), ("wall-0", 100)])
def test_each_consumer_compares_created_type_output_not_seed_selector(tmp_path, key, seed):
    case = scenario(tmp_path, both_floors=True)
    def assign_seed(rows):
        rows["uid-" + key]["type_state"] = {"status": "observed", **identity(seed, "seed-" + str(seed))}
    data = assess(case, observation(case, mutate=assign_seed)).to_dict()
    row = consumer(data, key)
    assert row["state"] == "mismatch"
    assert row["observed_assigned_type_identity"]["element_id"] == seed
    assert row["original_expected_type_identity"]["element_id"] in (800, 801)
    assert data["counts"] == {"matched": 2, "mismatch": 1, "unavailable": 0, "conflict": 0}


@pytest.mark.parametrize("fault", ["missing", "refused", "stale-refusal", "internal", "duplicate-uid"])
def test_historical_consumer_failure_remains_in_denominator_despite_matching_read(tmp_path, fault):
    case = scenario(tmp_path, walls=3, both_floors=True)
    observed = observation(case)
    oid = case["ids"]["wall-1"]
    if fault == "missing": del case["result"][oid]
    elif fault == "refused": case["result"][oid] = {"refused": "controlled refusal"}
    elif fault == "stale-refusal": case["result"][oid]["refused"] = "controlled refusal after stale capture"
    elif fault == "internal": case["result"][oid]["internal"] = True
    else: case["result"]["unexpected"] = deepcopy(case["result"][oid])
    data = assess(case, observed).to_dict()
    assert data["consumer_count"] == 5 and len(data["outputs"]) == 5
    assert consumer(data, "wall-1")["state"] == ("conflict" if fault == "duplicate-uid" else "unavailable")
    assert sum(data["counts"].values()) == 5
    assert data["counts"]["matched"] == 4


def test_reused_type_changed_version_and_historical_failure_do_not_imply_preservation_or_ownership(tmp_path):
    case = scenario(tmp_path)
    case["result"][case["ids"]["wall-type"]]["duplicated"] = False
    case["response"]["receipt"]["changes"]["added"].remove(800)
    case["response"]["receipt"]["changes"]["modified"] = [800]
    case["result"]["postcondition_violations"] = ["stored layer witness failed"]
    def changed(rows):
        rows["uid-wall-type"]["name"] = "Definition edited since publication"
        rows["uid-wall-type"]["element_identity"]["version_guid"] = "b" * 32
        rows["uid-wall-0"]["type_state"]["element_identity"]["version_guid"] = "b" * 32
        rows["uid-wall-0"]["element_identity"]["version_guid"] = "c" * 32
    data = assess(case, observation(case, mutate=changed)).to_dict()
    row = consumer(data)
    assert row["state"] == "matched" and row["type_publication_state"] == "reused_existing"
    assert row["original_expected_type_identity"]["version_guid"] != row["observed_expected_type_identity"]["version_guid"]
    assert data["historical"]["outcome"]["witness"] == "violated"
    assert data["historical"]["outcome"]["acceptance"] != "accepted"
    for field in ("layers", "type_definition", "geometry", "engineering", "historical_type_assignment"):
        assert data["claims"][field] == "not_evaluated"
    assert data["claims"]["exclusive_type_ownership"] == "not_established"
    assert data["claims"]["update_permission"] == data["claims"]["retry_permission"] == "none"


@pytest.mark.parametrize("axis", ["id", "uid", "version_guid"])
def test_contradictory_fresh_primary_and_assigned_type_are_refused_by_actual_parser(tmp_path, axis):
    case = scenario(tmp_path)
    def contradiction(rows):
        field = "element_id" if axis == "id" else "unique_id" if axis == "uid" else axis
        value = 1777 if axis == "id" else "another-type" if axis == "uid" else "b" * 32
        rows["uid-wall-0"]["type_state"]["element_identity"][field] = value
    with pytest.raises(ObservationRefusal, match="conflicting_element_identity"):
        observation(case, mutate=contradiction)


def selected_case():
    selected = project(walls=2, both_floors=True)
    # The unselected wall has a legal literal type selector, but must NOT be
    # counted as an unavailable selected consumer merely because source is full.
    source = ProjectRevision(selected.project_id, selected.modules, (*selected.instances,
        ModuleInstance("outside", "explicit", {"foreign-wall": {
            "op": "create_wall", "p0_mm": [0, 20000], "p1_mm": [5000, 20000], "height_mm": 3000,
            "level": {"by": "ref", "value": output_id(selected.project_id, "section", "level")},
            "type": {"by": "element_id", "value": 999}}})))
    selection = select_project_instances(source, instance_keys=("section",))
    materialized = materialize_selection(source, selection, {})
    credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "synthetic-selected")
    prepared = prepare_execution(materialized.planned, target=credentials.target,
        precondition=ContextPrecondition("native-doc", 8), operation_id=str(uuid4()))
    record = SavedExecutionRecord.capture_project(prepared,
        bind_selected_project_submission(source, materialized, prepared))
    result, ids = {"ok": True}, {}
    for index, output in enumerate(record.project_submission["outputs"]):
        key, oid = output["output_key"], output["output_id"]
        number = 800 if key == "wall-type" else 801 if key == "floor-type" else 900 + index
        ids[key] = oid
        result[oid] = {"id": str(number), **identity(number, "uid-" + key)}
        if output["source_op"] == "create_wall_type": result[oid]["duplicated"] = True
    response = response_for(prepared, credentials, result, changes={
        "added": [int(value["id"]) for value in result.values() if type(value) is dict],
        "modified": [], "deleted": [], "transaction_names": ["KIR"], "truncated": False})
    return dict(project=source, record=record, prepared=prepared, credentials=credentials,
                result=result, response=response, ids=ids)


def test_selected_denominator_is_exact_archived_scope_not_full_project_or_observation_subset():
    case = selected_case()
    observed = observation(case, omit=("wall-1",))
    data = assess(case, observed).to_dict()
    outputs = case["record"].project_submission["outputs"]
    assert data["selected_output_count"] == len(outputs) == 7
    assert len(list(case["project"].addressed_outputs())) == 8
    assert data["consumer_count"] == 4
    assert data["counts"] == {"matched": 3, "mismatch": 0, "unavailable": 1, "conflict": 0}
    assert {row["output_id"] for row in (*data["outputs"], *data["excluded_outputs"])} == {row["output_id"] for row in outputs}
    assert not any(row["instance_key"] == "outside" for row in (*data["outputs"], *data["excluded_outputs"]))
    assert consumer(data, "wall-1")["diagnostic"] == "consumer_observation_missing"


def test_recovery_outer_runtime_does_not_authorize_observation_in_that_runtime(tmp_path):
    case = scenario(tmp_path)
    recovery = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "synthetic-recovery")
    response = deepcopy(case["response"])
    response["receipt"]["result_json"] = json.dumps(case["result"])
    response.update(target=recovery.target.to_dict(), session_id=recovery.session_id, request_id=str(uuid4()))
    recovered = bind_create_receipt(case["record"], json.dumps(response), credentials=recovery,
                                    request_id=response["request_id"], recovery=True)
    assert consumer(assess(case, observation(case), recovered).to_dict())["state"] == "matched"
    with pytest.raises(CreateTypeDiscrepancyError, match="observation_runtime_or_document_mismatch"):
        assess(case, observation(case, runtime=recovery.target), recovered)


@pytest.mark.parametrize("revision", [7, 8])
def test_new_query_operation_id_alone_cannot_make_prepublication_context_fresh(tmp_path, revision):
    case = scenario(tmp_path)
    read = observation(case, revision=revision)
    assert read.operation_id != case["prepared"].operation_id
    with pytest.raises(CreateTypeDiscrepancyError, match="observation_not_after_publication"):
        assess(case, read)
