"""Pure CREATE identities; native rows are synthetic, never actual Revit effects."""
from copy import deepcopy, copy
from dataclasses import FrozenInstanceError, replace
import json
from uuid import uuid4

import pytest

from kir.contracts import ElementIdentityProof
from kir.create_publication import bind_create_receipt, assess_create_identities, CreatePublicationError, CreateIdentityAssessment
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id, _hash, _object
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_revit_level_update import make_case
from kir.tests.test_saved_create_result import project as levels_project


def bind(case, *, response=None, credentials=None, recovery=False):
    response = deepcopy(case["response"] if response is None else response)
    response["receipt"]["result_json"] = json.dumps(case["result"])
    return bind_create_receipt(case["record"], json.dumps(response), credentials=credentials or case["credentials"],
                              request_id=response["request_id"], recovery=recovery)


def report(case, **kwargs):
    return assess_create_identities(case["project"], case["record"], bind(case, **kwargs)).to_dict()


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path, project=levels_project())


def coverage_project():
    from kir.viewer.tests.test_live_scene_mesh import _VAULT
    from examples.residential_project import concept
    pid = "identity-coverage"
    level = {"by":"ref", "value":output_id(pid,"i","level")}
    wt = {"by":"ref", "value":output_id(pid,"i","wall-type")}
    ft = {"by":"ref", "value":output_id(pid,"i","floor-type")}
    blend = {key:value for key,value in concept().to_program()["ops"][0].items() if key != "id"}
    return ProjectRevision(pid, [ModuleDefinition("m")], [ModuleInstance("i","m", {
        "level":{"op":"create_level", "elev_mm":0},
        "wall-type":{"op":"create_wall_type", "host_kind":"wall", "source_type":{"by":"element_id","value":100}, "new_name":"Identity wall", "layers":[{"width_mm":200,"function":"Structure"}]},
        "floor-type":{"op":"create_wall_type", "host_kind":"floor", "source_type":{"by":"element_id","value":400}, "new_name":"Identity floor", "layers":[{"width_mm":200,"function":"Structure"}]},
        "wall":{"op":"create_wall", "p0_mm":[0,0], "p1_mm":[5000,0], "height_mm":3000, "level":level,"type":wt},
        "floor":{"op":"create_floor", "outline":[[0,0],[5000,0],[5000,5000],[0,5000]],"level":level,"type":ft},
        "contour":{"op":"create_floor_by_contour", "contour":{"outer":{"shape":"rect","origin":[0,0],"size_mm":[5000,5000]}},"level":level,"type":ft},
        "room":{"op":"create_room", "xy":[1000,1000], "name":"Room", "level":level},
        "mesh":{"op":"create_directshape", "mesh":_VAULT,"category":"mass","name":"Mesh"},
        "blend":blend,
        "grid":{"op":"create_grid", "p0_mm":[0,0], "p1_mm":[10000,0], "name":"Axis"},
    })])


@pytest.fixture
def covered(tmp_path):
    value = make_case(tmp_path, project=coverage_project())
    for index, op in enumerate(value["prepared"].planned.ops):
        row = value["result"][op.op_id]
        row.update(element_identity=ElementIdentityProof(700+index,"uid-"+op.op_id,"a"*32).to_dict(), element_identity_status="captured", element_identity_reason=None)
        if op.op_name == "create_wall_type": row["duplicated"] = True
    return value


def test_created_facts_are_immutable_not_bim_acceptance(case, monkeypatch):
    bound = bind(case)
    before = case["record"]._raw, bound.to_dict()
    import kir.compiler
    monkeypatch.setattr(kir.compiler,"compile_program",lambda *a,**k:pytest.fail("assessment compiled"))
    monkeypatch.setattr(kir.compiler,"plan_program",lambda *a,**k:pytest.fail("assessment planned"))
    assessed = assess_create_identities(case["project"],case["record"],bound)
    data = assessed.to_dict()
    assert [row["state"] for row in data["outputs"]] == ["created_here","created_here"]
    assert data["outcome"]["execution"] == "committed" and data["manifest_complete"]
    assert data["claims"]["global_ownership"] == "not_established"
    assert data["claims"]["geometry"] == data["claims"]["layers"] == data["claims"]["engineering"] == "not_evaluated"
    assert not any(key in data for key in ("accepted", "ok", "may_retry"))
    data["outputs"].clear()
    assert len(assessed.to_dict()["outputs"]) == 2
    assert before == (case["record"]._raw,bound.to_dict())
    with pytest.raises(FrozenInstanceError): assessed.digest="x"
    with pytest.raises(TypeError): CreateIdentityAssessment()


def test_supported_creators_and_unknown_producer_keep_source_order(covered):
    data = report(covered)
    assert [row["output_id"] for row in data["outputs"]] == [row["output_id"] for row in covered["record"].project_submission["outputs"]]
    assert [row["state"] for row in data["outputs"][:-1]] == ["created_here"]*9
    assert data["outputs"][-1]["diagnostic"] == "producer_capture_unsupported"


@pytest.mark.parametrize("fault", ["missing","scalar","refused","malformed-refusal","missing-capture","bad-primary","blank-uid","control"])
def test_incomplete_rows_do_not_erase_neighbors(case,fault):
    oid = list(case["result"])[-1]
    if fault == "missing": del case["result"][oid]
    elif fault == "scalar": case["result"][oid]=None
    elif fault == "refused": case["result"][oid]={"refused":"controlled"}
    elif fault == "malformed-refusal": case["result"][oid]={"refused":False}
    elif fault == "missing-capture": case["result"][oid]={"id":"701"}
    elif fault == "bad-primary": case["result"][oid]["id"]="0701"
    elif fault == "blank-uid": case["result"][oid]["element_identity"]["unique_id"]="  "
    else: case["result"][oid]["ok"]=False
    data=report(case)
    assert data["outcome"]["execution"]=="committed"
    assert data["outputs"][0]["state"]=="created_here"
    assert data["outputs"][1]["state"] in ("unavailable","refused")
    assert data["outputs"][1]["element_identity"] is None


@pytest.mark.parametrize("fault", ["not-added","deleted","truncated"])
def test_survival_needs_complete_manifest(case,fault):
    changes=case["response"]["receipt"]["changes"]
    if fault=="not-added": changes["added"].remove(700)
    elif fault=="deleted": changes["deleted"]=[700]
    else: changes["truncated"]=True
    data=report(case)
    assert data["outputs"][0]["state"]=="unavailable"
    assert data["outputs"][1]["state"]==("unavailable" if fault=="truncated" else "created_here")


@pytest.mark.parametrize("fault", ["id","uid","extra","refused-id","malformed-uid-claim"])
def test_global_conflicts_downgrade_all_participants(case,fault):
    first,second=[case["result"][key] for key in list(case["result"])[1:]]
    if fault=="id": second["id"]=first["id"]
    elif fault=="uid": second["element_identity"]["unique_id"]=first["element_identity"]["unique_id"]
    elif fault=="extra": case["result"]["unknown-output"]=deepcopy(first)
    elif fault=="malformed-uid-claim":
        second["element_identity"].update(unique_id=first["element_identity"]["unique_id"],version_guid="invalid")
    else: second.clear();second.update(refused="failed",id=first["id"])
    data=report(case)
    assert data["outputs"][0]["state"]=="conflict"
    assert any(item["code"]=="identity_conflict" for item in data["diagnostics"])
    if fault!="extra": assert data["outputs"][1]["state"]=="conflict"


@pytest.mark.parametrize("kind", ["wall-type","floor-type"])
@pytest.mark.parametrize("fault", [None,"added","deleted","missing-flag"])
def test_reused_type_is_not_new_creation(covered,kind,fault):
    oid=output_id(covered["project"].project_id,"i",kind)
    row=covered["result"][oid];row["duplicated"]=False
    changes=covered["response"]["receipt"]["changes"]
    if fault!="added": changes["added"].remove(int(row["id"]))
    if fault=="deleted": changes["deleted"].append(int(row["id"]))
    if fault=="missing-flag": del row["duplicated"]
    data=report(covered)
    result=next(item for item in data["outputs"] if item["output_id"]==oid)
    assert result["state"]==("reused_existing" if fault is None else "unavailable")
    assert data["claims"]["exclusive_type_ownership"]=="not_established"
    assert data["claims"]["dispatch_permission"]==data["claims"]["retry_permission"]=="none"


def test_operation_assignment_and_final_type_are_not_conflated(case):
    oid=list(case["result"])[1]
    case["result"][oid].update(type_assignment={"scope":"operation_end_before_commit","requested_type_id":"1","observed_type_id":"1"},type_id="2",type_id_status="captured",type_id_reason=None)
    bound=bind(case)
    data=assess_create_identities(case["project"],case["record"],bound).to_dict()
    row=json.loads(bound.receipt["result_json"])[oid]
    assert row["type_assignment"]["observed_type_id"]=="1" and row["type_id"]=="2"
    assert data["claims"]["type_assignment"]=="not_evaluated"


def test_recovery_outer_session_does_not_change_fact(case):
    first=bind(case)
    credentials=SessionCredentials(RuntimeTarget(str(uuid4()),str(uuid4()),"2026"),str(uuid4()),"other-test-token")
    response=deepcopy(case["response"])
    response.update(target=credentials.target.to_dict(),session_id=credentials.session_id,request_id=str(uuid4()))
    recovered=bind(case,response=response,credentials=credentials,recovery=True)
    assert recovered.receipt_digest==first.receipt_digest
    assert assess_create_identities(case["project"],case["record"],recovered).digest==assess_create_identities(case["project"],case["record"],first).digest


def test_source_and_rehashed_fact_mismatch_refuse(case):
    bound=bind(case)
    source=case["project"].revise(expected_revision=case["project"].revision_id,metadata={"different":True})
    with pytest.raises(ValueError): assess_create_identities(source,case["record"],bound)
    forged=copy(bound);payload=bound.to_dict();payload.pop("receipt_digest")
    payload["native_receipt"]["result_json"]="{}"
    object.__setattr__(forged,"_payload",_object(payload,"forged"))
    object.__setattr__(forged,"receipt_digest",_hash({"archive_digest":case["record"].digest,"native_receipt":payload["native_receipt"]}))
    with pytest.raises(CreatePublicationError,match="create_assessment_mismatch"):
        assess_create_identities(case["project"],case["record"],forged)


@pytest.mark.parametrize("fault", ["result-truncated","malformed-result","not-committed","bad-manifest"])
def test_unavailable_raw_fact_is_retained(case,fault):
    response=deepcopy(case["response"])
    if fault=="result-truncated": response["receipt"]["result_truncated"]=True
    elif fault=="malformed-result": response["receipt"]["result_json"]="not-json"
    elif fault=="not-committed": response["receipt"]["result_json"]="{}"
    else: response["receipt"]["changes"]={}
    bound=bind_create_receipt(case["record"],json.dumps(response),credentials=case["credentials"],request_id=response["request_id"])
    data=assess_create_identities(case["project"],case["record"],bound).to_dict()
    assert bound.receipt==response["receipt"]
    assert all(row["state"]=="unavailable" and row["element_identity"] is None for row in data["outputs"])


def test_before_start_fact_has_no_manifest_or_creation(case):
    response=deepcopy(case["response"])
    response["receipt"].update(state="cancelled_before_start",started=False,may_retry=True,
        transaction_evidence="not_observed",result_json=None,result_error=None,result_truncated=False,changes=None)
    bound=bind_create_receipt(case["record"],json.dumps(response),credentials=case["credentials"],request_id=response["request_id"])
    data=assess_create_identities(case["project"],case["record"],bound).to_dict()
    assert bound.not_started and data["outcome"]["execution"]=="not_started"
    assert data["manifest_complete"] is False
    assert all(row["state"]=="unavailable" for row in data["outputs"])
    assert not any(item["code"]=="change_manifest_truncated" for item in data["diagnostics"])


def test_unsupported_profile_keeps_fact_but_does_not_qualify_captures(tmp_path):
    source=levels_project({"mutate":{"op":"set_param","target":{"by":"element_id","value":777},"param":"Comments","value":"x"}})
    value=make_case(tmp_path,project=source)
    oid=list(value["result"])[1]
    value["result"][oid].update(element_identity=ElementIdentityProof(700,"mutated-not-created","a"*32).to_dict(),
                                element_identity_status="captured",element_identity_reason=None)
    bound=bind(value)
    assert bound.assessment.diagnostic_code=="unsupported_saved_create_profile"
    data=assess_create_identities(source,value["record"],bound).to_dict()
    assert data["outputs"][0]["state"]=="unavailable" and data["outputs"][0]["element_identity"] is None
    assert data["outputs"][0]["diagnostic"]=="producer_capture_unsupported"


def test_identity_facts_do_not_hide_violated_d1_witness(case):
    case["result"]["postcondition_violations"]=["controlled geometry discrepancy"]
    data=report(case)
    assert data["outcome"]["witness"]=="violated"
    assert all(row["state"]=="created_here" for row in data["outputs"])
    assert data["claims"]["geometry"]=="not_evaluated"


def test_another_checked_archive_cannot_adopt_the_same_bound_receipt(case,tmp_path):
    other_path=tmp_path/"other";other_path.mkdir()
    other=make_case(other_path,project=case["project"])
    with pytest.raises(ValueError):
        assess_create_identities(case["project"],other["record"],bind(case))


def test_existing_d1_wrapper_rules_are_reused_without_manual_unwrapping(case):
    response=deepcopy(case["response"])
    response["receipt"]["result_json"]=json.dumps({"result":case["result"]})
    bound=bind_create_receipt(case["record"],json.dumps(response),credentials=case["credentials"],request_id=response["request_id"])
    data=assess_create_identities(case["project"],case["record"],bound).to_dict()
    assert all(row["state"]=="created_here" for row in data["outputs"])


def test_selected_full_source_maps_only_its_archived_dependency_closure(tmp_path):
    from kir.tests.test_selected_project_submission import selected_binding
    from kir.tests.test_revit_level_update import response_for
    from kir.saved_execution import SavedExecutionRecord
    source, _, _, prepared, submission = selected_binding()
    record=SavedExecutionRecord.create_project_new(tmp_path/"selected.sqlite",prepared,submission)
    credentials=SessionCredentials(prepared.target,str(uuid4()),"selected-test-token")
    result={"ok":True}
    for index,output in enumerate(submission.to_dict()["outputs"]):
        result[output["output_id"]]={"id":str(800+index),"element_identity":ElementIdentityProof(800+index,"selected-"+str(index),"a"*32).to_dict(),
                                    "element_identity_status":"captured","element_identity_reason":None}
    response=response_for(prepared,credentials,result,changes={"added":[800,801],"modified":[],"deleted":[],"transaction_names":["KIR"],"truncated":False})
    bound=bind_create_receipt(record,json.dumps(response),credentials=credentials,request_id=response["request_id"])
    data=assess_create_identities(source,record,bound).to_dict()
    assert len(source.addressed_outputs())==3 and len(data["outputs"])==2
    assert all(row["state"]=="created_here" for row in data["outputs"])
    assert data["project"]["revision_id"]==source.revision_id


@pytest.mark.parametrize("control", ["internal","serialization_error","receipt","outcome","started","may_retry","refused_op_id"])
def test_per_operation_control_fields_cannot_qualify_stale_capture(case,control):
    first=list(case["result"])[1]
    case["result"][first][control]=True
    data=report(case)
    assert data["outputs"][0]["state"]=="unavailable"
    assert data["outputs"][1]["state"]=="created_here"


def test_forged_outcome_cannot_remove_original_outer_response_barrier(case):
    from kir.bridge_result import WriteResultAssessment
    from kir.outcome import write_committed, WitnessState
    response=deepcopy(case["response"])
    response["ok"]=False
    original=bind_create_receipt(case["record"],json.dumps(response),credentials=case["credentials"],request_id=response["request_id"])
    assert original.assessment.outcome.execution.value=="unconfirmed"
    forged=copy(original)
    # Both PUBLIC derived outcome and raw_response are overwritten. The actual
    # original response remains separately retained, and is not in the fact digest.
    altered=replace(original.assessment, assessment=WriteResultAssessment(write_committed(witness=WitnessState.SATISFIED)),
                    raw_response=json.dumps(case["response"]).encode())
    object.__setattr__(forged,"assessment",altered)
    with pytest.raises(CreatePublicationError,match="original response barrier"):
        assess_create_identities(case["project"],case["record"],forged)
    assert original.receipt==forged.receipt and original.receipt_digest==forged.receipt_digest


def test_shared_native_content_assessment_is_consistency_not_outer_authentication(case):
    from kir.connector_result import assess_saved_create_receipt
    response=deepcopy(case["response"])
    response["ok"]=False
    bound=bind_create_receipt(case["record"],json.dumps(response),credentials=case["credentials"],request_id=response["request_id"])
    content=assess_saved_create_receipt(case["record"],bound.receipt)
    assert content.outcome.execution.value=="committed"
    assert bound.assessment.outcome.execution.value=="unconfirmed"
    with pytest.raises(CreatePublicationError):
        assess_create_identities(case["project"],case["record"],bound)
