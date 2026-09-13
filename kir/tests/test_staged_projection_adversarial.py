"""Independent staged lowering: real plans/codecs, synthetic parsed native facts.

No archive persistence, ProjectStore reservation, native execution or ownership
is established here. Imported history and C0 are explicit distinct evidence.
"""
from copy import copy, deepcopy
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from kir.create_publication import bind_create_receipt
from kir.geometry_materialization import materialize_project, materialize_selection
from kir.project import ModuleInstance, NamedOutput, ProjectRevision, _hash, _object, _thaw, output_id
from kir.project_execution_partition import partition_project_execution
from kir.project_selection import select_project_instances
from kir.project_submission import bind_project_submission, bind_selected_project_submission, ProjectSubmissionError
from kir.revit_connector import ContextPrecondition, prepare_execution, source_association_digest
from kir.saved_execution import SavedExecutionRecord
from kir.staged_create_projection import bind_staged_create_projection, prepare_staged_create, StagedProjectionError
from kir.tests.test_staged_create_projection import case, project as bind_case, observe_rows
from kir.tests.test_revit_level_update import response_for


def partition_for(source, imports):
    materialized = materialize_selection(source, select_project_instances(source, instance_keys=("B",)), {})
    return partition_project_execution(source, materialized, import_output_ids=tuple(imports))


def read_only_type_import(transaction_names):
    value = case(revision=8)
    current = value["project"]
    type_id = output_id(current.project_id, "shared", "type")
    shared = current.instances[0]
    typed = next(output for output in shared.outputs if output.key == "type")
    # Genuine closed type-only original input, not a fake partial/Level archive.
    old = ProjectRevision(current.project_id, current.modules,
        [ModuleInstance("shared", shared.module_key, [typed], parameters=shared.parameters)])
    materialized = materialize_project(old, {})
    original = prepare_execution(materialized.planned, target=value["credentials"].target,
        precondition=ContextPrecondition("native-doc", 8), operation_id=str(uuid4()))
    archive = SavedExecutionRecord.capture_project(original, bind_project_submission(old, materialized, original))
    current_row = value["observed_rows"]["uid-1"]
    result = {"ok": True, type_id: {"id": str(current_row["element_identity"]["element_id"]),
        "duplicated": False, "element_identity": current_row["element_identity"],
        "element_identity_status": "captured", "element_identity_reason": None}}
    response = response_for(original, value["credentials"], result, changes={
        "added": [], "modified": [], "deleted": [], "transaction_names": transaction_names, "truncated": False})
    bound = bind_create_receipt(archive, json.dumps(response), credentials=value["credentials"],
        request_id=response["request_id"])
    imports = {type_id: (old, archive, bound)}
    observation = observe_rows({"uid-1": current_row}, value["credentials"], revision=8)
    return partition_for(current, imports), imports, observation


@pytest.mark.parametrize("names", [["KIR"], [""]])
def test_equal_C0_reuse_cannot_ignore_observed_document_change_event_names(names):
    partition, imports, observation = read_only_type_import(names)
    with pytest.raises(StagedProjectionError, match="staged_import_observation_too_old"):
        bind_staged_create_projection(partition, import_sources=imports, observation=observation)


def test_equal_C0_truly_event_free_readonly_type_reuse_remains_lawful():
    partition, imports, observation = read_only_type_import([])
    projected = bind_staged_create_projection(partition, import_sources=imports, observation=observation)
    assert projected.precondition is observation.precondition and projected.precondition.revision == 8
    assert projected.runtime_plan.source_op_count == 2
    assert projected.core["import_lineage"][0]["original_identity_state"] == "reused_existing"
    assert projected.to_dict()["claims"]["native_birth"] == "not_established"


def test_only_imported_typed_slots_change_new_export_refs_and_other_fields_survive():
    value = case()
    source = value["project"]
    top_id = output_id(source.project_id, "shared", "new-top")
    shared = source.instances[0]
    source = source.replace_instance(replace(shared, outputs=(*shared.outputs,
        NamedOutput("new-top", {"op": "create_level", "elev_mm": 4000}))), expected_revision=source.revision_id)
    body = source.instances[-1]
    wall = _thaw(body.outputs[0].operation)
    wall.update(top_level={"by": "ref", "value": top_id}, base_offset_mm=120,
                top_offset_mm=-80, location_line="finish_face_exterior")
    source = source.replace_instance(replace(body, outputs=(NamedOutput("body", wall),)), expected_revision=source.revision_id)
    source = source.revise(expected_revision=source.revision_id,
        metadata={"inert-not-selector": {"by": "ref", "value": next(iter(value["imports"]))}})
    partition = partition_for(source, value["imports"])
    originals = source.dumps(), partition.to_dict(), value["archive"]._raw
    projection = bind_staged_create_projection(partition, import_sources=value["imports"], observation=value["observation"])
    runtime = projection.runtime_program["ops"]
    assert len(runtime) == projection.runtime_plan.source_op_count == 2
    assert partition.to_dict()["closure_output_count"] == 4
    assert runtime[0] == {"op": "create_level", "id": top_id, "elev_mm": 4000}
    expected_wall = {**wall, "id": output_id(source.project_id, "B", "body"),
        "level": {"by": "element_id", "value": 1700}, "type": {"by": "element_id", "value": 1701}}
    assert runtime[1] == expected_wall
    assert runtime[1]["top_level"] == {"by": "ref", "value": top_id}
    assert [row["field"] for row in projection.core["projection_table"]] == ["level", "type"]
    assert originals == (source.dumps(), partition.to_dict(), value["archive"]._raw)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    assert prepared.precondition is value["observation"].precondition
    # The old closure binder MUST NOT pretend the 4->2 projection is its 1:1 profile.
    with pytest.raises(ProjectSubmissionError, match="submission_plan_mismatch"):
        bind_selected_project_submission(source, partition.materialization, prepared)


def test_current_UID_proof_wins_over_an_original_numeric_id_reused_by_another_element():
    def add_reused_numeric(rows):
        other = deepcopy(rows["uid-1"])
        other["requested_unique_id"] = "unrelated-now-at-700"
        other["element_identity"].update(element_id=700, unique_id="unrelated-now-at-700")
        other["name"] = other["type_definition"]["value"]["name"] = "Unrelated type"
        rows["unrelated-now-at-700"] = other
    value = case(mutate_observed=add_reused_numeric)
    projection = bind_case(value)
    assert projection.core["import_lineage"][0]["original_identity"]["element_id"] == 700
    assert projection.runtime_program["ops"][0]["level"]["value"] == 1700
    assert 700 not in {proof.element_id for proof in projection.expected_identities}
    assert "unrelated-now-at-700" in projection.core["observation"]["rows"]


@pytest.mark.parametrize("fault", ["archive", "receipt", "project", "loaded-source"])
def test_swapped_original_history_components_cannot_qualify_imports(fault):
    value, foreign = case(), case()
    imports = dict(value["imports"])
    oid = next(iter(imports))
    project, archive, receipt = imports[oid]
    if fault == "archive": archive = foreign["archive"]
    elif fault == "receipt": receipt = foreign["bound"]
    elif fault == "project": project = project.revise(expected_revision=project.revision_id, metadata={"foreign": True})
    else: receipt = receipt.to_dict()
    imports[oid] = (project, archive, receipt)
    with pytest.raises(ValueError): bind_case(value, import_sources=imports)


@pytest.mark.parametrize("fault", ["raw-number-type", "module-key"])
def test_import_source_ownership_changes_do_not_disappear_under_normalization(fault):
    value = case()
    source = value["project"]
    if fault == "raw-number-type":
        shared = source.instances[0]
        typed = shared.outputs[1]
        raw = _thaw(typed.operation)
        raw["layers"][0]["width_mm"] = 200.0  # Same normalized value, different exact retained source.
        source = source.replace_instance(replace(shared, outputs=(shared.outputs[0], replace(typed, operation=raw))),
                                         expected_revision=source.revision_id)
    else:
        from kir.project import ModuleDefinition
        replacement = ModuleDefinition("other-owner")
        shared = replace(source.instances[0], module_key=replacement.key, module_digest=None)
        source = source.revise(expected_revision=source.revision_id, modules=(*source.modules, replacement),
                               instances=(shared, *source.instances[1:]))
    partition = partition_for(source, value["imports"])
    with pytest.raises(StagedProjectionError, match="staged_import_source_mismatch"):
        bind_staged_create_projection(partition, import_sources=value["imports"], observation=value["observation"])


@pytest.mark.parametrize("uid", ["type-uid", "material-uid"])
def test_coherently_rehashed_guard_omission_still_fails_source_rederivation(uid):
    value = case(material=True)
    original = bind_case(value)
    changed = copy(original)
    guards = tuple(proof for proof in original.expected_identities if proof.unique_id != uid)
    assert len(guards) == len(original.expected_identities) - 1
    core = original.core
    core["expected_identities"] = [proof.to_dict() for proof in guards]
    object.__setattr__(changed, "expected_identities", guards)
    object.__setattr__(changed, "_core", _object(core, "changed"))
    object.__setattr__(changed, "association_digest", _hash(core))
    with pytest.raises(StagedProjectionError, match="staged_projection_mismatch"):
        prepare_staged_create(changed, operation_id=str(uuid4()))


def test_same_numeric_runtime_with_swapped_logical_projection_claims_is_not_prepareable():
    original = bind_case(case())
    changed, core = copy(original), original.core
    core["projection_table"][0]["import_output_id"], core["projection_table"][1]["import_output_id"] = (
        core["projection_table"][1]["import_output_id"], core["projection_table"][0]["import_output_id"])
    object.__setattr__(changed, "_core", _object(core, "changed"))
    object.__setattr__(changed, "association_digest", _hash(core))
    assert changed.runtime_program == original.runtime_program
    with pytest.raises(StagedProjectionError, match="staged_projection_mismatch"):
        prepare_staged_create(changed, operation_id=str(uuid4()))


def test_full_observation_not_only_import_proofs_is_committed_to_header():
    from kir.type_definition_observation import prepare_type_definition_observation, parse_type_definition_observation
    def add_unimported(rows):
        extra = deepcopy(rows["uid-1"])
        extra["requested_unique_id"] = "unimported-type"
        extra["element_identity"].update(element_id=3333, unique_id="unimported-type")
        extra["name"] = extra["type_definition"]["value"]["name"] = "Additional type"
        rows["unimported-type"] = extra
    value = case(mutate_observed=add_unimported)
    first = bind_case(value)
    observed = deepcopy(value["observed_rows"])
    # Hold every query identity/C0 constant: the ONLY difference is an extra
    # unimported observation fact. Its loss cannot hide behind new query UUIDs.
    observed["unimported-type"]["name"] = "Changed additional type"
    observed["unimported-type"]["type_definition"]["value"]["name"] = "Changed additional type"
    original_observation = value["observation"]
    query = prepare_type_definition_observation(list(observed), target=original_observation.target,
        precondition=original_observation.precondition, operation_id=original_observation.operation_id)
    assert query.source_sha256 == original_observation.source_sha256
    response = response_for(query, value["credentials"],
        {op["id"]: observed[op["unique_id"]] for op in query.planned.to_ops()},
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    changed = parse_type_definition_observation(query, json.dumps(response), credentials=value["credentials"],
                                                 request_id=response["request_id"])
    assert changed.operation_id == original_observation.operation_id
    second = bind_case(value, observation=changed)
    assert first.runtime_program == second.runtime_program
    assert first.expected_identities == second.expected_identities
    assert first.association_digest != second.association_digest
    opid = str(uuid4())
    a, b = prepare_staged_create(first, operation_id=opid), prepare_staged_create(second, operation_id=opid)
    assert a.source_sha256 != b.source_sha256
    assert source_association_digest(a.source) == first.association_digest
    assert source_association_digest(b.source) == second.association_digest
    assert first.core["observation"] == value["observation"].to_dict()
    assert second.core["observation"] == changed.to_dict()
    assert "unimported-type" not in {proof.unique_id for proof in first.expected_identities}


@pytest.mark.parametrize("basis", [0, 1])
def test_readonly_level_parameter_is_legal_for_import_not_a_request_to_set_it(basis):
    def readonly(rows):
        rows["uid-0"]["level"]["elevation_parameter"]["is_read_only"] = True
        rows["uid-0"]["level"]["elevation_base"] = basis
    value = case(mutate_observed=readonly)
    projection = bind_case(value)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    assert [op.op_name for op in prepared.planned.ops] == ["create_wall"]
    assert projection.to_dict()["claims"]["dispatch_permission"] == "none"


@pytest.mark.parametrize("basis", [0, 1])
def test_project_elevation_match_cannot_hide_reported_elevation_used_by_actual_emitter(basis):
    def different_elevation(rows):
        level = rows["uid-0"]["level"]
        level.update(elevation_base=basis, project_elevation_mm=0, reported_elevation_mm=1000)
        level["elevation_parameter"]["value_internal_feet"] = 1000 / 304.8
    with pytest.raises(StagedProjectionError, match="staged_import_level_mismatch"):
        bind_case(case(mutate_observed=different_elevation))


@pytest.mark.parametrize("checks", [{}, {"host_kind": {"status": "matched"}}])
def test_no_incomplete_public_clause_table_can_satisfy_all_type_requirements(monkeypatch, checks):
    import kir.staged_create_projection as owner
    value = case()
    monkeypatch.setattr(owner, "compare_type_definition", lambda *_a, **_kw: {"checks": checks})
    with pytest.raises(StagedProjectionError, match="staged_import_definition_mismatch"):
        bind_case(value)


def test_current_type_uid_with_level_role_is_not_a_host_type_import():
    def changed_kind(rows):
        identity = rows["uid-1"]["element_identity"]
        rows["uid-1"] = deepcopy(rows["uid-0"])
        rows["uid-1"].update(requested_unique_id="uid-1", element_identity=identity)
    with pytest.raises(StagedProjectionError, match="staged_import_definition_mismatch"):
        bind_case(case(mutate_observed=changed_kind))


def test_inert_projection_and_observation_dicts_do_not_rehydrate_fresh_preparation():
    value = case()
    projection = bind_case(value)
    with pytest.raises(StagedProjectionError, match="staged_projection_required"):
        prepare_staged_create(projection.to_dict(), operation_id=str(uuid4()))
    with pytest.raises(StagedProjectionError, match="staged_observation_required"):
        bind_case(value, observation=value["observation"].to_dict())
