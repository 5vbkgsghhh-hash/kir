"""Independent selected-source checks; hashes are integrity, not kernel proof."""
from copy import copy, deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import standalone_publish as publisher
from kir.compiler import plan_program
from kir.geometry_materialization import GeometryMaterialization, materialize_selection
from kir.occt_geometry import GeometryBundle, GeometryRefusal
from kir.project import ProjectRevision, _canonical, _hash
from kir.project_selection import ProjectSelectionError, select_project_instances
from kir.project_submission import (ProjectSubmissionError, bind_selected_project_submission,
                                    validate_submission_source)
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_selected_project_submission import source_project, prepare, validate_retained


def case():
    source = source_project()
    source = source.revise(expected_revision=source.revision_id,
        instances=(source.instances[0], source.instances[2], source.instances[1]))
    choice = select_project_instances(source, instance_keys=("section",))
    materialized = materialize_selection(source, choice, {})
    prepared = prepare(materialized.planned)
    binding = bind_selected_project_submission(source, materialized, prepared)
    return source, choice, materialized, prepared, binding


def resign(data):
    data["submission_digest"] = _hash({key: value for key, value in data.items() if key != "submission_digest"})
    return data


def test_rehashed_ordinary_program_digest_must_match_available_full_source():
    source, _, _, prepared, binding = case()
    data = binding.to_dict()
    data["materialized_program_digest"] = "0" * 64
    resign(data)
    validate_retained(data, prepared)  # It has no original Project payload.
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(source, data)


@pytest.mark.parametrize("fault", ["root_changed", "root_widened", "root_duplicate", "root_noncanonical_order",
    "count_bool", "count_wrong", "index_bool", "index_float", "index_other_valid_position",
    "missing_dependency_row", "missing_foreign_instance", "foreign_instance_digest", "ordinary_payload"])
def test_rehashed_scope_claims_cannot_pass_both_retained_and_actual_source_checks(fault):
    source, _, _, prepared, binding = case()
    data = binding.to_dict()
    if fault == "root_changed": data["selection"]["root_instance_keys"] = ["unselected"]
    elif fault == "root_widened": data["selection"]["root_instance_keys"] = ["unselected", "section"]
    elif fault == "root_duplicate": data["selection"]["root_instance_keys"] = ["section", "section"]
    elif fault == "root_noncanonical_order": data["selection"]["root_instance_keys"] = ["section", "datums"]
    elif fault == "count_bool": data["selection"]["source_output_count"] = True
    elif fault == "count_wrong": data["selection"]["source_output_count"] += 1
    elif fault == "index_bool": data["outputs"][0]["project_source_index"] = False
    elif fault == "index_float": data["outputs"][0]["project_source_index"] = 0.0
    elif fault == "index_other_valid_position": data["outputs"][1]["project_source_index"] = 1
    elif fault == "missing_dependency_row": data["outputs"].pop(0)
    elif fault == "missing_foreign_instance": data["instances"].pop(1)
    elif fault == "foreign_instance_digest": data["instances"][1]["instance_snapshot_digest"] = "0" * 64
    elif fault == "ordinary_payload": data["outputs"][1]["materialized_op_digest"] = "0" * 64
    resign(data)
    with pytest.raises(ProjectSubmissionError):
        validate_retained(data, prepared)
        validate_submission_source(source, data)


def test_cropped_project_with_equal_executable_values_cannot_replace_full_source():
    source, choice, materialized, prepared, binding = case()
    cropped = source.revise(expected_revision=source.revision_id,
        instances=(source.instances[0], source.instances[2]))
    cropped_choice = select_project_instances(cropped, instance_keys=("section",))
    cropped_materialized = materialize_selection(cropped, cropped_choice, {})
    assert cropped_materialized.to_program() == materialized.to_program()
    assert cropped.revision_id != source.revision_id
    for project, projection in ((source, cropped_materialized), (cropped, materialized)):
        with pytest.raises(ProjectSubmissionError, match="submission_project_mismatch"):
            bind_selected_project_submission(project, projection, prepared)
    altered = copy(choice)
    object.__setattr__(altered, "project", cropped)
    with pytest.raises(ProjectSelectionError):
        materialize_selection(source, altered, {})
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(cropped, binding.to_dict())


@pytest.mark.parametrize("attribute,value", [("instance_keys", ["section"]), ("output_ids", []),
    ("project_source_indices", (False, 2)), ("project_source_indices", (0, 2.0)),
    ("project_source_indices", (0, 1)), ("instance_keys", ("unselected",))])
def test_typed_selection_mutation_is_rechecked_before_any_native_derivation(monkeypatch, attribute, value):
    source, choice, _, _, _ = case()
    altered = copy(choice)
    object.__setattr__(altered, attribute, value)
    def forbidden(*args, **kwargs):
        raise AssertionError("malformed selection reached native derivation")
    monkeypatch.setattr(GeometryBundle, "rederive_preview", forbidden)
    with pytest.raises(ProjectSelectionError):
        materialize_selection(source, altered, {})


@pytest.fixture(scope="module")
def body_case():
    from kir.tests.test_geometry_materialization import capture, project_for
    selected, other = capture(1000), capture(1800, instance_key="unselected-body")
    source = project_for(selected)
    source = source.revise(expected_revision=source.revision_id,
        instances=(*source.instances, project_for(other).instances[0]))
    choice = select_project_instances(source, instance_keys=("body",))
    return source, choice, selected, other


def test_missing_or_unselected_assets_never_trigger_extra_native_derivation(body_case, monkeypatch):
    source, choice, selected, other = body_case
    called = []
    original = GeometryBundle.rederive_preview
    def tracked(bundle, **kwargs):
        called.append(bundle.digest)
        assert bundle.digest == selected.digest
        return original(bundle, **kwargs)
    monkeypatch.setattr(GeometryBundle, "rederive_preview", tracked)
    with pytest.raises(GeometryRefusal, match="missing_asset"):
        materialize_selection(source, choice, {other.digest: other})
    assert called == []
    class Assets(dict):
        def get(self, key, *args):
            assert key != other.digest, "unselected asset was inspected"
            return super().get(key, *args)
        def __getitem__(self, key):
            assert key != other.digest, "unselected asset was read"
            return super().__getitem__(key)
    # Even an unusable unselected value must remain untouched.
    materialized = materialize_selection(source, choice, Assets({selected.digest: selected, other.digest: object()}))
    assert called == [selected.digest] and len(materialized.sources) == 1
    assert materialized.project.dumps() == source.dumps()


@pytest.mark.parametrize("fault", ["descriptor", "body_hash", "mesh_hash", "extra_sidecar", "authored_name"])
def test_selected_body_binding_cannot_be_relabelled_or_partially_rehashed(body_case, fault):
    source, choice, selected, other = body_case
    materialized = materialize_selection(source, choice, {selected.digest: selected})
    if fault == "descriptor":
        instance = source.instances[0]
        output = replace(instance.outputs[0], geometry=replace(instance.outputs[0].geometry, body_sha256=other.body_digest))
        wrong = source.replace_instance(replace(instance, outputs=(output,)), expected_revision=source.revision_id)
        wrong_choice = select_project_instances(wrong, instance_keys=("body",))
        with pytest.raises(GeometryRefusal, match="binding_mismatch"):
            materialize_selection(wrong, wrong_choice, {selected.digest: selected})
        return
    data = materialized.to_program()
    sources = deepcopy(materialized.to_dict()["sources"])
    if fault == "body_hash": sources[0]["source_body_sha256"] = other.body_digest
    elif fault == "mesh_hash": sources[0]["mesh_sha256"] = "0" * 64
    elif fault == "extra_sidecar": sources.append({**sources[0], "op_id": other.op_id})
    elif fault == "authored_name": data["ops"][0]["name"] = "not the authored body"
    with pytest.raises(GeometryRefusal):
        GeometryMaterialization(source, data, materialized.planned, tuple(sources), choice)


def test_consistently_rebound_mesh_is_data_binding_not_a_kernel_execution_attestation(body_case):
    source, choice, selected, _ = body_case
    materialized = materialize_selection(source, choice, {selected.digest: selected})
    program = materialized.to_program()
    for point in program["ops"][0]["mesh"]["vertices_mm"]:
        point[0] *= .5
    sources = materialized.to_dict()["sources"]
    sources[0]["mesh_sha256"] = _hash(program["ops"][0]["mesh"])
    # Deliberately public constructor, NOT materialize_selection's native path.
    rebound = GeometryMaterialization(source, program, plan_program(program), tuple(sources), choice)
    prepared = prepare(rebound.planned)
    binding = bind_selected_project_submission(source, rebound, prepared)
    validate_retained(binding.to_dict(), prepared)
    validate_submission_source(source, binding.to_dict())
    assert max(p[0] for p in program["ops"][0]["mesh"]["vertices_mm"]) == pytest.approx(500.)
    assert binding.to_dict()["claims"]["kernel_execution"] == "not_established"
    assert binding.to_dict()["claims"]["native_execution"] == "not_established"


def test_actual_archive_load_and_source_validation_are_inert_in_a_fresh_process(tmp_path):
    source, _, _, prepared, binding = case()
    path = tmp_path / "selected.sqlite"
    record = SavedExecutionRecord.create_project_new(path, prepared, binding)
    before = path.read_bytes()
    script = r'''
import importlib.abc,json,sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname=='OCP' or fullname.startswith('OCP.'):
            raise AssertionError('archive loading imported the native kernel')
sys.meta_path.insert(0,NoNative())
import kir.compiler as compiler
from kir.project import ProjectRevision
from kir.saved_execution import SavedExecutionRecord
from kir.project_submission import validate_submission_source
from kir.occt_geometry import GeometryBundle
def forbidden(*args,**kwargs): raise AssertionError('inert load compiled or derived geometry')
compiler.plan_program=compiler.compile_program=forbidden
GeometryBundle.rederive_preview=forbidden
def audit(event,args):
    if event=='open' and ((isinstance(args[1],str) and any(c in args[1] for c in 'wax+')) or
        (isinstance(args[2],int) and args[2] & 3)):
        raise AssertionError('Python write during load')
    if event.startswith('subprocess.'): raise AssertionError('child process during load')
sys.addaudithook(audit)
source=ProjectRevision.loads(sys.stdin.read())
loaded=SavedExecutionRecord.load(sys.argv[1])
validate_submission_source(source,loaded.project_submission)
import kir.project_submission as submission
submission.select_project_instances=forbidden
validate_submission_source(source,loaded.project_submission,selection_policy='retained')
assert not any(name=='OCP' or name.startswith('OCP.') for name in sys.modules)
assert not hasattr(loaded,'execute_request')
print(loaded.digest)
'''
    process = subprocess.run([sys.executable, "-c", script, str(path)], input=source.dumps(),
        capture_output=True, text=True, timeout=30, cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == record.digest and path.read_bytes() == before


def test_old_whole_project_publisher_cannot_archive_selected_profile_as_whole(tmp_path, monkeypatch):
    from kir.tests.test_revit_transport import advertisement, ready_response
    from kir.tests.test_connector_context import case as context_case
    source, _, materialized, _, _ = case()
    advert = advertisement()
    calls = []
    def exchange(record, raw, **kwargs):
        request = json.loads(raw)
        calls.append(request["kind"])
        if request["kind"] == "ping": return json.dumps(ready_response(request)).encode()
        assert request["kind"] == "context", "selected input reached execute through whole publisher"
        _, _, response, _ = context_case.__wrapped__()
        response.update(target=advert.credentials.target.to_dict(), session_id=advert.credentials.session_id,
                        request_id=request["request_id"])
        return json.dumps(response).encode()
    monkeypatch.setattr(publisher, "exchange", exchange)
    path = tmp_path / "must-not-be-created.sqlite"
    with pytest.raises(ProjectSubmissionError, match="submission_profile_mismatch"):
        publisher.publish_materialized_project(source, materialized, advertisement=advert, client_path=sys.executable,
            archive_path=path, expected_document_key="opaque-open-document-A", operation_id=str(uuid4()),
            bind_view=False, bind_selection=False)
    assert "execute" not in calls and not path.exists()
