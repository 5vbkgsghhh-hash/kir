"""Full authored source -> selected geometry -> associated retained input."""
from copy import copy
from dataclasses import replace

import pytest

from kir.geometry_materialization import GeometryMaterialization, materialize_project, materialize_selection
from kir.occt_geometry import GeometryRefusal
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id, _hash
from kir.project_selection import ProjectSelectionError, select_project_instances, selected_instance_program
from kir.project_submission import (ProjectSubmissionError, bind_project_submission, bind_selected_project_submission,
                                    validate_submission_claims, validate_submission_source)
from kir.revit_connector import ContextPrecondition, RuntimeTarget, prepare_execution
from kir.saved_execution import SavedExecutionRecord, PROJECT_ARCHIVE_SCHEMA


TARGET = RuntimeTarget("be3e4ce4-9420-4c96-b2d7-8f3a61f5c4c1", "45a9d9bf-1843-4a0f-9e69-0410d44f7f68", "2026")
CONTEXT = ContextPrecondition("synthetic-selection-contract-not-a-native-observation", 7)


def prepare(program):
    return prepare_execution(program, target=TARGET, precondition=CONTEXT,
        operation_id="6f468142-2b23-43d5-8736-4174c7caf3f9")


def source_project():
    project_id = "selected-publication"
    return ProjectRevision(project_id, [ModuleDefinition("m")], [
        ModuleInstance("datums", "m", {"level": {"op": "create_level", "elev_mm": 0}}),
        ModuleInstance("section", "m", {"wall": {"op": "create_wall", "p0_mm": [0, 0],
            "p1_mm": [5000, 0], "height_mm": 3000,
            "level": {"by": "ref", "value": output_id(project_id, "datums", "level")}}}),
        ModuleInstance("unselected", "m", {"level": {"op": "create_level", "elev_mm": 9000}}),
    ], intent="One selected section inside the complete authored project")


def test_cropped_revision_cannot_pose_as_full_selected_publication_source():
    source = source_project()
    selected = selected_instance_program(source, "section")
    assert [op["id"] for op in selected["ops"]] == [
        output_id(source.project_id, "datums", "level"), output_id(source.project_id, "section", "wall")]
    cropped = source.revise(expected_revision=source.revision_id, instances=source.instances[:2])
    materialized = materialize_project(cropped, {})
    assert materialized.to_program() == selected  # Same executable values, DIFFERENT authored source.
    prepared = prepare(materialized.planned)
    assert bind_project_submission(cropped, materialized, prepared).to_dict()["project"]["revision_id"] == cropped.revision_id
    with pytest.raises(ProjectSubmissionError) as failure:
        bind_project_submission(source, materialized, prepared)
    assert failure.value.code == "submission_project_mismatch"
    assert cropped.revision_id != source.revision_id


def test_valid_subset_execution_cannot_be_claimed_as_whole_project_coverage():
    source = source_project()
    whole = materialize_project(source, {})
    valid = bind_project_submission(source, whole, prepare(whole.planned))
    assert len(valid.to_dict()["outputs"]) == 3
    selected = selected_instance_program(source, "section")
    prepared = prepare(selected)
    assert len(prepared.planned.ops) == 2  # Cross-instance level dependency is retained.
    with pytest.raises(ProjectSubmissionError) as failure:
        bind_project_submission(source, whole, prepared)
    assert failure.value.code == "submission_plan_mismatch"


def test_absent_body_geometry_cannot_be_claimed_as_whole_materialization():
    from kir.tests.test_geometry_materialization import capture, project_for

    selected_asset = capture(1000)
    other_asset = capture(1500, instance_key="unselected-body")
    selected_project = project_for(selected_asset)
    other_instance = replace(project_for(other_asset).instances[0], module_key="m")
    full = selected_project.revise(expected_revision=selected_project.revision_id,
                                   instances=(*selected_project.instances, other_instance))
    with pytest.raises(GeometryRefusal) as missing:
        materialize_project(full, {selected_asset.digest: selected_asset})
    assert missing.value.code == "missing_asset"
    # A valid derivation for ONE body cannot be relabelled as the complete project.
    selected_derivation = materialize_project(selected_project, {selected_asset.digest: selected_asset})
    with pytest.raises(GeometryRefusal) as forged:
        GeometryMaterialization(full, selected_derivation.program, selected_derivation.planned,
                                selected_derivation.sources)
    assert forged.value.code == "invalid_materialization"
    assert len(full.geometry_references()) == 2


def selected_binding(project=None, roots=("section",)):
    source = project or source_project()
    selection = select_project_instances(source, instance_keys=roots)
    materialized = materialize_selection(source, selection, {})
    prepared = prepare(materialized.planned)
    return source, selection, materialized, prepared, bind_selected_project_submission(source, materialized, prepared)


def validate_retained(binding, prepared):
    validate_submission_claims(binding, execution=prepared.binding_dict(),
        plan_evidence=prepared.planned.to_evidence_dict(), planned_units=list(prepared.planned.units),
        grounded_evidence=prepared.grounded.to_evidence_dict() if prepared.grounded is not None else None)


def test_selected_association_retains_full_source_and_sparse_project_positions():
    source = source_project()
    source = source.revise(expected_revision=source.revision_id,
        instances=(source.instances[0], source.instances[2], source.instances[1]))
    source, choice, materialized, prepared, binding = selected_binding(source)
    data = binding.to_dict()
    assert data["schema"] == "kir-submitted-project-binding/2"
    assert data["project"]["revision_id"] == source.revision_id
    assert materialized.project.dumps() == source.dumps() and materialized.selection is choice
    assert materialized.to_dict()["schema"] == "kir-geometry-materialization/2"
    assert data["selection"] == {"policy": "authored_dependency_closure/1", "root_instance_keys": ["section"],
                                  "source_output_count": 3}
    assert len(data["instances"]) == 3 and len(data["outputs"]) == 2
    assert [row["source_index"] for row in data["outputs"]] == [0, 1]
    assert [row["project_source_index"] for row in data["outputs"]] == [0, 2]
    assert [row["output_id"] for row in data["outputs"]] == list(choice.output_ids)
    assert data["claims"]["publication_scope"] == "selected_dependency_closure_only"
    assert data["claims"]["native_execution"] == "not_established"
    validate_retained(data, prepared)
    validate_submission_source(source, data)


def test_roots_are_canonical_authored_order_and_duplicates_refuse():
    source = source_project()
    choice = select_project_instances(source, instance_keys=("section", "datums"))
    assert choice.instance_keys == ("datums", "section")
    with pytest.raises(ProjectSelectionError):
        select_project_instances(source, instance_keys=("section", "section"))


@pytest.mark.parametrize("roots", [(), "section", ("missing",), (True,), ([],)])
def test_invalid_root_selection_is_not_silently_broadened(roots):
    with pytest.raises(ProjectSelectionError):
        select_project_instances(source_project(), instance_keys=roots)


def test_profiles_are_explicit_even_when_selection_covers_every_output():
    source, _, selected, prepared, _ = selected_binding(roots=("datums", "section", "unselected"))
    whole = materialize_project(source, {})
    assert whole.to_program() == selected.to_program()
    assert whole.to_dict()["schema"] == "kir-geometry-materialization/1" and "selection" not in whole.to_dict()
    with pytest.raises(ProjectSubmissionError, match="submission_profile_mismatch"):
        bind_project_submission(source, selected, prepared)
    with pytest.raises(ProjectSubmissionError, match="submission_profile_mismatch"):
        bind_selected_project_submission(source, whole, prepared)
    ordinary = bind_project_submission(source, whole, prepared).to_dict()
    assert ordinary["schema"] == "kir-submitted-project-binding/1" and "selection" not in ordinary
    validate_submission_source(source, ordinary)


def test_metadata_only_wrong_full_revision_cannot_replace_selected_source():
    source, _, materialized, prepared, binding = selected_binding()
    changed = source.revise(expected_revision=source.revision_id, metadata={"different-source": True})
    assert selected_instance_program(source, "section") == selected_instance_program(changed, "section")
    with pytest.raises(ProjectSubmissionError):
        bind_selected_project_submission(changed, materialized, prepared)
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(changed, binding.to_dict())


def test_tampered_typed_selection_cannot_omit_dependency_or_add_unrelated_output():
    source, choice, _, _, _ = selected_binding()
    for indices, ids in [((1,), (output_id(source.project_id, "section", "wall"),)),
                          ((False, True), choice.output_ids),
                          ((0,1,2), tuple(oid for _, _, oid in source.addressed_outputs()))]:
        forged = copy(choice)
        object.__setattr__(forged, "output_ids", ids)
        object.__setattr__(forged, "project_source_indices", indices)
        with pytest.raises(ProjectSelectionError):
            materialize_selection(source, forged, {})


def test_rehashed_retained_root_claim_needs_actual_source_recheck():
    source, _, _, prepared, binding = selected_binding()
    forged = binding.to_dict()
    forged["selection"]["root_instance_keys"] = ["unselected"]
    forged["submission_digest"] = _hash({key:value for key,value in forged.items() if key != "submission_digest"})
    validate_retained(forged, prepared)  # Archive cannot invent the omitted full source payload.
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(source, forged)


@pytest.mark.parametrize("field,value", [("project_source_index", -1), ("project_source_index", True),
                                         ("project_source_index", 99), ("source_index", 9)])
def test_rehashed_invalid_indices_are_rejected_by_inert_reader(field, value):
    _, _, _, prepared, binding = selected_binding()
    forged = binding.to_dict()
    forged["outputs"][0][field] = value
    forged["submission_digest"] = _hash({key:item for key,item in forged.items() if key != "submission_digest"})
    with pytest.raises(ProjectSubmissionError):
        validate_retained(forged, prepared)


def test_selected_input_uses_existing_archive2_and_load_does_not_recompile(tmp_path, monkeypatch):
    source, _, _, prepared, binding = selected_binding()
    record = SavedExecutionRecord.create_project_new(tmp_path / "selected.sqlite", prepared, binding)
    assert record.to_dict()["schema"] == PROJECT_ARCHIVE_SCHEMA
    assert record.project_submission["schema"] == "kir-submitted-project-binding/2"
    import kir.compiler as compiler
    def forbidden(*args, **kwargs):
        raise AssertionError("inert archive/source verification must not compile")
    monkeypatch.setattr(compiler, "plan_program", forbidden)
    loaded = SavedExecutionRecord.load(tmp_path / "selected.sqlite")
    loaded.require_matches(prepared, submission=binding)
    validate_submission_source(source, loaded.project_submission)
    assert loaded.digest == record.digest


def body_source():
    from kir.tests.test_geometry_materialization import capture, project_for
    body = capture(1000)
    other = capture(1500, instance_key="unselected-body")
    source = project_for(body)
    source = source.revise(expected_revision=source.revision_id,
        modules=(*source.modules, ModuleDefinition("plain")),
        instances=(*source.instances, project_for(other).instances[0], ModuleInstance("consumer", "plain", {
            "set": {"op":"set_param", "target":{"by":"ref","value":body.op_id}, "param":"Comments", "value":"checked"}})))
    return source, body, other


def test_selected_body_dependency_uses_owner_without_requiring_unrelated_asset(monkeypatch):
    from kir.occt_geometry import GeometryBundle
    source, body, other = body_source()
    choice = select_project_instances(source, instance_keys=("consumer",))
    original = GeometryBundle.rederive_preview
    derived = []
    def traced(asset, **kwargs):
        derived.append(asset.digest)
        assert asset.digest != other.digest, "unselected body entered native derivation"
        return original(asset, **kwargs)
    monkeypatch.setattr(GeometryBundle, "rederive_preview", traced)
    with pytest.raises(GeometryRefusal, match="missing_asset"):
        materialize_selection(source, choice, {})
    materialized = materialize_selection(source, choice, {body.digest:body})
    assert derived == [body.digest]
    assert [row["op_id"] for row in materialized.sources] == [body.op_id]
    binding = bind_selected_project_submission(source, materialized, prepare(materialized.planned))
    validate_submission_source(source, binding.to_dict())
    assert binding.to_dict()["outputs"][0]["body"]["descriptor"]["bundle_sha256"] == body.digest
    assert materialized.project.revision_id == source.revision_id


def test_wrong_selected_body_asset_is_not_replaced_by_cached_preview():
    source, body, other = body_source()
    choice = select_project_instances(source, instance_keys=("body",))
    with pytest.raises(GeometryRefusal, match="binding_mismatch"):
        materialize_selection(source, choice, {body.digest:other})


def test_selected_mesh_is_rederived_from_brep_not_stale_saved_preview():
    from kir.tests.test_geometry_materialization import capture, project_for, resized_claim
    small, larger = capture(1000), capture(2000)
    data = larger.to_dict()
    data["preview_mesh"] = small.to_dict()["preview_mesh"]
    data["manifest"]["preview"]["sha256"] = _hash(data["preview_mesh"])
    stale = resized_claim(data)
    source = project_for(stale)
    choice = select_project_instances(source, instance_keys=("body",))
    materialized = materialize_selection(source, choice, {stale.digest: stale})
    mesh = materialized.to_program()["ops"][0]["mesh"]
    assert max(point[0] for point in stale.fallback_op(name="cached")["mesh"]["vertices_mm"]) == 1000
    assert max(point[0] for point in mesh["vertices_mm"]) == pytest.approx(2000)
    assert materialized.sources[0]["stored_preview_bytes_equal"] is False
    prepared = prepare(materialized.planned)
    binding = bind_selected_project_submission(source, materialized, prepared)
    assert binding.to_dict()["outputs"][0]["body"]["mesh_digest"] == _hash(mesh)
    validate_retained(binding.to_dict(), prepared)


def test_source_recheck_rejects_rehashed_ordinary_payload_claim():
    source, _, _, _, binding = selected_binding()
    data = binding.to_dict()
    data["outputs"][0]["materialized_op_digest"] = "0" * 64
    data["submission_digest"] = _hash({key:value for key,value in data.items() if key != "submission_digest"})
    with pytest.raises(ProjectSubmissionError, match="ordinary materialized payload"):
        validate_submission_source(source, data)


@pytest.mark.parametrize("operation", [
    {"op":"stack", "levels":2, "floor":[{"op":"create_level", "id":"l", "elev_mm":0}]},
    {"op":"create_group", "members":[], "placements":[]},
])
def test_selected_macro_or_group_remains_named_unsupported(operation):
    source = ProjectRevision("unsupported-selection", [ModuleDefinition("m")],
                             [ModuleInstance("i", "m", {"out":operation})])
    with pytest.raises(ProjectSelectionError, match="dependency closure"):
        select_project_instances(source, instance_keys=("i",))


def test_historical_source_recheck_survives_current_registry_unavailability(tmp_path, monkeypatch):
    import kir.compiler as compiler
    import kir.project_diff as dependencies
    import kir.project_submission as submissions
    source, _, _, prepared, binding = selected_binding()
    record = SavedExecutionRecord.create_project_new(tmp_path / "historical.sqlite", prepared, binding)
    def unavailable(*args, **kwargs):
        raise ProjectSelectionError("current registry policy unavailable")
    def forbidden(*args, **kwargs):
        raise AssertionError("historical evidence read invoked compiler/dependency policy")
    monkeypatch.setattr(submissions, "select_project_instances", unavailable)
    monkeypatch.setattr(dependencies, "_dependencies", forbidden)
    monkeypatch.setattr(compiler, "plan_program", forbidden)
    loaded = SavedExecutionRecord.load(tmp_path / "historical.sqlite")
    validate_submission_source(source, loaded.project_submission, selection_policy="retained")
    assert loaded.digest == record.digest
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(source, loaded.project_submission)  # New admission still checks today's policy.


@pytest.mark.parametrize("policy", ["current", "retained"])
@pytest.mark.parametrize("fault", ["index", "boolean-index", "authored-digest", "materialized-digest", "program-digest", "cropped"])
def test_both_source_policies_refuse_forged_indices_digests_or_revision(policy, fault):
    source, _, _, _, binding = selected_binding()
    data = binding.to_dict()
    if fault == "index":
        data["outputs"][1]["project_source_index"] = 2
    elif fault == "boolean-index":
        data["outputs"][0]["project_source_index"] = False
    elif fault == "authored-digest":
        data["outputs"][0]["authored_output_digest"] = "0" * 64
    elif fault == "materialized-digest":
        data["outputs"][0]["materialized_op_digest"] = "0" * 64
    elif fault == "program-digest":
        data["materialized_program_digest"] = "0" * 64
    else:
        source = source.revise(expected_revision=source.revision_id, instances=source.instances[:2])
    data["submission_digest"] = _hash({key:value for key,value in data.items() if key != "submission_digest"})
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(source, data, selection_policy=policy)


def test_retained_association_requires_all_root_outputs_but_is_not_current_closure_proof():
    source, _, _, _, binding = selected_binding()
    data = binding.to_dict()
    # Removing the root wall must fail even without current registry access.
    data["outputs"] = data["outputs"][:1]
    with pytest.raises(ProjectSubmissionError, match="omits a declared root output"):
        validate_submission_source(source, data, selection_policy="retained")
    # A historical scope cannot be reinterpreted as today's dependency proof.
    # Source-only retained validation intentionally does not reconstruct edges.
    data = binding.to_dict()
    data["outputs"] = data["outputs"][1:]
    data["outputs"][0]["source_index"] = 0
    operation = selected_instance_program(source, "section")["ops"][1]
    # D-1: the materialization envelope carries a stable project
    # identity, and the fixture must build THE SAME envelope as the
    # producer.
    data["materialized_program_digest"] = _hash({"ir_version":source.ir_version,"intent":source.intent,
                                                 "lineage":source.project_id,"ops":[operation]})
    validate_submission_source(source, data, selection_policy="retained")
    with pytest.raises(ProjectSubmissionError):
        validate_submission_source(source, data, selection_policy="current")


@pytest.mark.parametrize("policy", ["current", "retained"])
def test_body_source_recheck_rejects_missing_sidecar_and_wrong_descriptor_without_kernel(policy, monkeypatch):
    from kir.occt_geometry import GeometryBundle
    source, body, _ = body_source()
    selection = select_project_instances(source, instance_keys=("body",))
    materialized = materialize_selection(source, selection, {body.digest:body})
    binding = bind_selected_project_submission(source, materialized, prepare(materialized.planned))
    def forbidden(*args, **kwargs):
        raise AssertionError("source-only validation attempted native geometry derivation")
    monkeypatch.setattr(GeometryBundle, "rederive_preview", forbidden)
    for fault in ("missing-sidecar", "wrong-body", "wrong-index"):
        data = binding.to_dict()
        if fault == "missing-sidecar":
            del data["outputs"][0]["body"]
        elif fault == "wrong-body":
            data["outputs"][0]["body"]["descriptor"]["body_sha256"] = "0" * 64
        else:
            data["outputs"][0]["project_source_index"] = 1
        with pytest.raises(ProjectSubmissionError):
            validate_submission_source(source, data, selection_policy=policy)
    # Explicit limit: a body program checksum is NOT re-established from source
    # descriptors alone, because the materialized mesh payload is not supplied.
    data = binding.to_dict()
    data["materialized_program_digest"] = "0" * 64
    validate_submission_source(source, data, selection_policy=policy)


@pytest.mark.parametrize("policy", [None, True, "", "legacy", 0])
def test_unknown_selection_policy_refuses(policy):
    source, _, _, _, binding = selected_binding()
    with pytest.raises(ProjectSubmissionError, match="selection_policy"):
        validate_submission_source(source, binding.to_dict(), selection_policy=policy)
