"""Fresh source association, including macro 1:N; never stored/native authority."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from uuid import uuid4

import pytest

from kir.geometry_materialization import GeometryMaterialization, materialize_project
from kir.project import (ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision,
                         _canonical, _hash, _object, _thaw, output_id)
from kir.project_submission import (ProjectSubmissionError, SubmittedProjectBinding, bind_project_submission)
from kir.revit_connector import ConnectorPreparationError, ContextPrecondition, RuntimeTarget, prepare_execution
from kir.saved_execution import SavedExecutionRecord


TARGET = RuntimeTarget("be3e4ce4-9420-4c96-b2d7-8f3a61f5c4c1", "45a9d9bf-1843-4a0f-9e69-0410d44f7f68", "2026")
CONTEXT = ContextPrecondition("original-opaque-document", 7)
OPERATION = "6f468142-2b23-43d5-8736-4174c7caf3f9"


def prepare(materialized):
    return prepare_execution(materialized.planned, target=TARGET, precondition=CONTEXT,
                             operation_id=OPERATION, bulk=materialized.planned.bulk)


def project(*operations):
    return ProjectRevision("submission", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput(f"out-{index}", operation) for index, operation in enumerate(operations)])])


@pytest.fixture
def simple():
    value = project({"op": "create_level", "elev_mm": 0})
    materialized = materialize_project(value, {})
    return value, materialized, prepare(materialized)


def test_binding_covers_actual_snapshot_instance_operation_and_execution_without_payload_duplication(simple):
    value, materialized, prepared = simple
    binding = bind_project_submission(value, materialized, prepared)
    data = binding.to_dict()
    assert data["project"] == {"project_id": value.project_id, "schema": value.schema, "revision_id": value.revision_id}
    assert data["execution"] == prepared.binding_dict()
    assert data["materialization_digest"] == materialized.to_dict()["materialization_digest"]
    assert data["materialized_program_digest"] == _hash(materialized.to_program())
    assert data["instances"] == [{"instance_key": "i", "module_key": "m", "instance_snapshot_digest": _hash(value.instances[0].to_dict()),
                                  "module_definition_digest": value.modules[0].definition_digest}]
    output = data["outputs"][0]
    op = materialized.planned.ops[0]
    assert output["output_id"] == output_id("submission", "i", "out-0")
    assert output["authored_output_digest"] == _hash(value.instances[0].outputs[0].to_dict())
    assert output["materialized_op_digest"] == _hash(materialized.to_program()["ops"][0])
    assert output["compiled_ops"][0]["op_id"] == op.op_id
    assert output["compiled_ops"][0]["result"] == op.to_evidence_dict()["result"]
    assert not any(key in data for key in ("source", "program", "mesh", "recipe", "token", "session_id"))
    assert data["claims"]["project_persistence"] == data["claims"]["native_execution"] == "not_established"
    assert data["claims"]["native_element_mapping"] == "not_created"
    assert binding.digest == _hash({key: item for key, item in data.items() if key != "submission_digest"})
    assert json.loads(binding.dumps()) == data
    data["outputs"].clear()
    assert len(binding.to_dict()["outputs"]) == 1
    with pytest.raises(FrozenInstanceError): binding.digest = "0" * 64
    with pytest.raises(TypeError): SubmittedProjectBinding()
    assert not any(hasattr(binding, method) for method in ("loads", "from_dict", "execute_request", "to_prepared"))


@pytest.mark.parametrize("kind", ["project_metadata", "instance_metadata", "parameters"])
def test_same_archive_input_can_have_distinct_authored_revisions_but_binding_names_the_exact_one(simple, tmp_path, kind):
    original, materialized, prepared = simple
    if kind == "project_metadata":
        other = original.revise(expected_revision=original.revision_id, metadata={"review": "different chosen revision"})
    else:
        instance = original.instances[0]
        replacement = replace(instance, **{"metadata" if kind == "instance_metadata" else "parameters": {"author_note": "changed"}})
        other = original.replace_instance(replacement, expected_revision=original.revision_id)
    next_materialized = materialize_project(other, {})
    next_prepared = prepare(next_materialized)
    assert original.revision_id != other.revision_id
    assert _canonical(materialized.to_program()) == _canonical(next_materialized.to_program())
    assert prepared.source == next_prepared.source and prepared.planned.plan_digest == next_prepared.planned.plan_digest
    SavedExecutionRecord.create_new(tmp_path / "original.sqlite", prepared).require_matches(next_prepared)
    first = bind_project_submission(original, materialized, prepared).to_dict()
    second = bind_project_submission(other, next_materialized, next_prepared).to_dict()
    assert first["submission_digest"] != second["submission_digest"]
    # Native binding does not contain project revision/submission digest: the
    # distinct caller associations are not distinct native receipt attestations.
    assert first["execution"] == second["execution"]
    assert first["claims"]["native_execution"] == second["claims"]["native_execution"] == "not_established"
    assert (first["instances"][0]["instance_snapshot_digest"] == second["instances"][0]["instance_snapshot_digest"]) == (kind == "project_metadata")
    with pytest.raises(ProjectSubmissionError, match="submission_project_mismatch"):
        bind_project_submission(other, materialized, prepared)


@pytest.mark.parametrize("position", [0, 1, 2])
def test_json_or_wrong_input_type_never_becomes_fresh_binding(simple, position):
    args = list(simple)
    args[position] = args[position].to_dict() if hasattr(args[position], "to_dict") else {}
    with pytest.raises(ProjectSubmissionError, match="submission_input_required"):
        bind_project_submission(*args)


def test_prepared_different_program_cannot_bind_to_materialized_output(simple):
    value, materialized, _ = simple
    another = project({"op": "create_level", "elev_mm": 100})
    prepared = prepare(materialize_project(another, {}))
    with pytest.raises(ProjectSubmissionError, match="submission_plan_mismatch"):
        bind_project_submission(value, materialized, prepared)


def test_original_macro_has_one_to_many_output_coverage_and_replanning_expansion_refuses():
    value = project({"op": "stack", "levels": 2, "floor": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]})
    materialized = materialize_project(value, {})
    prepared = prepare(materialized)
    data = bind_project_submission(value, materialized, prepared).to_dict()
    assert len(data["outputs"]) == 1 and len(data["outputs"][0]["compiled_ops"]) == 4
    assert [op["op"] for op in data["outputs"][0]["compiled_ops"]] == ["create_level", "create_level", "create_wall", "create_wall"]
    assert {op["op_id"] for op in data["outputs"][0]["compiled_ops"]} == {op.op_id for op in prepared.planned.ops}
    repeated = prepare_execution({"ir_version": prepared.planned.ir_version, "intent": prepared.planned.intent,
        "lineage": prepared.planned.lineage, "ops": prepared.planned.to_ops()},
        target=TARGET, precondition=CONTEXT, operation_id=OPERATION)
    assert prepared.source == repeated.source
    assert prepared.planned.plan_digest != repeated.planned.plan_digest
    with pytest.raises(ProjectSubmissionError, match="submission_plan_mismatch"):
        bind_project_submission(value, materialized, repeated)


def test_units_cannot_hide_behind_equal_source_and_plan_digest(simple):
    value, materialized, prepared = simple
    with_units = replace(materialized.planned, units=({"id": "another-label"},))
    another = prepare_execution(with_units, target=TARGET, precondition=CONTEXT, operation_id=OPERATION)
    assert prepared.source == another.source and prepared.planned.plan_digest == another.planned.plan_digest
    with pytest.raises(ProjectSubmissionError, match="submission_plan_mismatch"):
        bind_project_submission(value, materialized, another)


@pytest.mark.parametrize("kind", ["group", "network"])
def test_group_and_network_cardinality_is_copied_from_real_plan_contracts(kind):
    if kind == "group":
        operation = {"op": "create_group", "placements": [[10000, 0, 0]], "members": [
            {"op": "create_level", "id": "L", "elev_mm": 0},
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [5000, 0], "height_mm": 3000,
             "level": {"by": "ref", "value": "L"}}]}
        value = project(operation)
    else:
        level_id = output_id("submission", "i", "out-0")
        operation = {"op": "route_duct_system", "nodes": [{"id": "a", "xyz_mm": [0, 0, 3000]},
            {"id": "b", "xyz_mm": [3000, 0, 3000]}, {"id": "c", "xyz_mm": [6000, 0, 3000]}],
            "segments": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
            "level": {"by": "ref", "value": level_id}, "diameter_mm": 200,
            # Explicit source selectors qualify preparation without a census.
            # No fixture claims these native ElementIds actually exist.
            "duct_type": {"by": "element_id", "value": 501},
            "system_type": {"by": "element_id", "value": 601}}
        value = project({"op": "create_level", "elev_mm": 0}, operation)
        implicit = {key: item for key, item in operation.items() if key not in ("duct_type", "system_type")}
        with pytest.raises(ConnectorPreparationError) as refused:
            prepare(materialize_project(project({"op": "create_level", "elev_mm": 0}, implicit), {}))
        assert any(item.code == "KIR-G103" for item in refused.value.diagnostics)
    materialized = materialize_project(value, {})
    prepared = prepare(materialized)
    data = bind_project_submission(value, materialized, prepared).to_dict()
    row = data["outputs"][-1]["compiled_ops"]
    assert len(row) == 1
    assert row[0]["result"] == prepared.planned.ops[-1].to_evidence_dict()["result"]
    if kind == "group":
        assert row[0]["nested_contract_count"] == 2 and row[0]["result"]["identity_cardinality"] == "one"
    else:
        assert row[0]["nested_contract_count"] == 0 and row[0]["result"]["identity_cardinality"] == "many"
        assert row[0]["result"]["identity_field"] == "segment_ids"
    assert data["claims"]["native_element_mapping"] == "not_created"


def test_multiple_macros_keep_separate_original_output_owners():
    value = project({"op": "stack", "levels": 2, "floor": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]},
        {"op": "grid_array", "nx": 2, "ny": 2})
    materialized = materialize_project(value, {})
    data = bind_project_submission(value, materialized, prepare(materialized)).to_dict()
    assert [len(row["compiled_ops"]) for row in data["outputs"]] == [4, 4]
    for index, output in enumerate(data["outputs"]):
        expected = {op.op_id for op in materialized.planned.ops if op.provenance.source_index == index}
        assert {row["op_id"] for row in output["compiled_ops"]} == expected
        assert output["output_id"] == output_id(value.project_id, "i", f"out-{index}")


def test_missing_compiled_source_coverage_is_refused():
    value = project({"op": "create_level", "elev_mm": 0}, {"op": "create_level", "elev_mm": 3000})
    materialized = materialize_project(value, {})
    prepared = prepare(materialized)
    altered = replace(materialized.planned, ops=materialized.planned.ops[1:], plan_digest="")
    object.__setattr__(materialized, "planned", altered)
    object.__setattr__(prepared, "planned", altered)
    object.__setattr__(prepared, "grounded", None)
    with pytest.raises(ProjectSubmissionError, match="no compiled source coverage"):
        bind_project_submission(value, materialized, prepared)


@pytest.mark.parametrize("field,value", [("source_index", 99), ("source_id", "foreign"), ("source_op", "create_wall"), ("macro_name", "stack")])
def test_origin_mismatch_cannot_be_hidden_by_equal_mutated_plan_values(simple, field, value):
    project_value, materialized, prepared = simple
    # Simulate an upstream in-process regression AFTER normal constructors.
    # This is a consistency test, not a hostile-Python security claim.
    op = materialized.planned.ops[0]
    altered = replace(op, provenance=replace(op.provenance, **{field: value}))
    bad_plan = replace(materialized.planned, ops=(altered,), plan_digest="")
    object.__setattr__(materialized, "planned", bad_plan)
    object.__setattr__(prepared, "planned", bad_plan)
    object.__setattr__(prepared, "grounded", None)
    with pytest.raises(ProjectSubmissionError, match="submission_origin_mismatch"):
        bind_project_submission(project_value, materialized, prepared)


@pytest.mark.parametrize("change", ["count", "payload", "source_hash"])
def test_materialized_or_prepared_internal_inconsistency_is_refused(simple, change):
    value, materialized, prepared = simple
    if change == "source_hash": object.__setattr__(prepared, "source_sha256", "0" * 64)
    else:
        program = materialized.to_program()
        if change == "count": program["ops"].clear()
        else: program["ops"][0]["elev_mm"] = 2500
        object.__setattr__(materialized, "program", _object(program, "fault"))
    with pytest.raises(ProjectSubmissionError): bind_project_submission(value, materialized, prepared)


@pytest.fixture
def body():
    from kir.tests.test_geometry_materialization import capture, project_for
    bundle = capture()
    value = project_for(bundle)
    materialized = materialize_project(value, {bundle.digest: bundle})
    return bundle, value, materialized, prepare(materialized)


def test_body_association_retains_existing_digests_not_brep_or_mesh_payload(body):
    bundle, value, materialized, prepared = body
    data = bind_project_submission(value, materialized, prepared).to_dict()
    row = data["outputs"][0]["body"]
    assert row["descriptor"] == value.instances[0].outputs[0].geometry.to_dict()
    assert row["descriptor"]["bundle_sha256"] == bundle.digest
    assert row["descriptor"]["body_sha256"] == bundle.body_digest
    assert row["mesh_digest"] == _hash(materialized.to_program()["ops"][0]["mesh"])
    assert row["materialization_sidecar_digest"] == _hash(materialized.sources[0])
    assert "vertices_mm" not in _canonical(data) and "brep_base64" not in _canonical(data)
    assert "source" not in data and "parameters" not in data


@pytest.mark.parametrize("field", ["source_bundle_sha256", "source_body_sha256", "mesh_sha256", "duplicate", "missing", "coherent_mesh_not_in_plan"])
def test_body_descriptor_and_sidecar_inconsistency_cannot_bind(body, field):
    _, value, materialized, prepared = body
    sources = [_thaw(item) for item in materialized.sources]
    if field == "duplicate": sources *= 2
    elif field == "missing": sources = []
    elif field == "coherent_mesh_not_in_plan":
        program = materialized.to_program()
        program["ops"][0]["mesh"]["vertices_mm"][0][0] += 1000
        sources[0]["mesh_sha256"] = _hash(program["ops"][0]["mesh"])
        object.__setattr__(materialized, "program", _object(program, "fault"))
    else: sources[0][field] = "0" * 64
    object.__setattr__(materialized, "sources", tuple(_object(item, "fault") for item in sources))
    with pytest.raises(ProjectSubmissionError, match="submission_body_mismatch"):
        bind_project_submission(value, materialized, prepared)


def test_binding_never_reexecutes_recipe_kernel_compiler_or_writes_files(body, monkeypatch, tmp_path):
    _, value, materialized, prepared = body
    from kir.occt_geometry import GeometryBundle
    from kir import compiler
    def forbidden(*args, **kwargs): raise AssertionError("association executed a backend")
    monkeypatch.setattr(GeometryBundle, "read_body", forbidden)
    monkeypatch.setattr(GeometryBundle, "rederive_preview", forbidden)
    monkeypatch.setattr(compiler, "plan_program", forbidden)
    monkeypatch.setattr(compiler, "compile_program", forbidden)
    previous = value.dumps(), materialized.to_dict(), prepared.binding_dict()
    bind_project_submission(value, materialized, prepared)
    assert (value.dumps(), materialized.to_dict(), prepared.binding_dict()) == previous
    assert list(tmp_path.iterdir()) == []


def test_saved_composite_old_submission_does_not_become_the_edited_project(tmp_path):
    pytest.importorskip("OCP")
    from examples import residential_refinement as workflow
    from examples.residential_with_podium import materialize_saved
    store = workflow.create_store(tmp_path / "project.sqlite")
    before = store.head()
    materialized = materialize_saved(store)
    prepared = prepare(materialized)
    original = bind_project_submission(before, materialized, prepared).to_dict()
    workflow.continue_section(store, expected_revision=before.revision_id, height_mm=4500., setback_mm=1200.)
    after = store.head()
    next_materialized = materialize_saved(store)
    changed = bind_project_submission(after, next_materialized, prepare(next_materialized)).to_dict()
    assert original["project"]["revision_id"] == before.revision_id != changed["project"]["revision_id"]
    first = {row["instance_key"]: row for row in original["instances"]}
    second = {row["instance_key"]: row for row in changed["instances"]}
    assert first["tower-a"]["instance_snapshot_digest"] != second["tower-a"]["instance_snapshot_digest"]
    assert all(first[key] == second[key] for key in ("tower-b", "tower-c", "podium"))
    assert original["execution"]["source_sha256"] != changed["execution"]["source_sha256"]
    with pytest.raises(ProjectSubmissionError, match="submission_project_mismatch"):
        bind_project_submission(after, materialized, prepared)
    assert original["claims"]["native_element_mapping"] == "not_created"
