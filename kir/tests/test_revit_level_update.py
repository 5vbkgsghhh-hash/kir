"""Original publication mapping + one pure Level edit; all native rows are synthetic."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from uuid import uuid4

import pytest

from kir.compiler import compile_program
from kir.contracts import ElementIdentityProof
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, RecipePin, _canonical, _thaw, output_id
from kir.project_handoff import handoff_instance_to_explicit
from kir.project_submission import bind_project_submission
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.revit_level_update import (LevelUpdateRefusal, OriginalPublicationBindings, LevelElevationUpdatePlan,
                                    bind_original_publication, plan_level_elevation_update)
from kir.revit_observation import parse_element_observation, prepare_element_observation
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_revit_observation import row as observed_row, unavailable


TARGET_ADDRESS = ("section", "upper-level")
PROTECTED = (("protected", "volume"),)


def initial(*, explicit=True):
    from kir.viewer.tests.test_live_scene_mesh import _VAULT

    level_id = output_id("level-update", *TARGET_ADDRESS)
    sealed = ProjectRevision("level-update", [ModuleDefinition("m", "sealed_evaluation",
        RecipePin("raise AssertionError('never execute recipe during update')", "a" * 64))], [
        ModuleInstance("section", "m", [
            NamedOutput("upper-level", {"op": "create_level", "elev_mm": 3000.0, "name": "Upper"}),
            NamedOutput("other-level", {"op": "create_level", "elev_mm": 0.0, "name": "Lower"}),
            NamedOutput("wall", {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [5000, 0],
                                 "height_mm": 3200, "level": {"by": "ref", "value": level_id}}),
        ], parameters={"height_mm": 3200}),
        ModuleInstance("protected", "m", [NamedOutput("volume", {"op": "create_directshape",
            "mesh": _VAULT, "category": "mass", "name": "protected"})]),
    ])
    return (handoff_instance_to_explicit(sealed, "section", new_module_key="explicit-section", expected_revision=sealed.revision_id)
            if explicit else sealed)


def response_for(prepared, credentials, result, *, changes):
    receipt = {**prepared.binding_dict(), "document_key": prepared.precondition.document_key,
        "state": "invocation_completed", "started": True, "may_retry": False,
        "transaction_evidence": "changes_observed" if any(changes[k] for k in ("added", "modified", "deleted")) else "changes_not_observed",
        "semantic_evidence": "unverified", "result_json": json.dumps(result), "result_truncated": False,
        "result_error": None, "error": None, "changes": changes, "timestamp_utc": "2026-09-05T12:00:00Z"}
    return {"protocol": "kir-revit-connector/4", "request_id": str(uuid4()), "target": credentials.target.to_dict(),
            "session_id": credentials.session_id, "ok": True, "status": "receipt", "error": None,
            "context": None, "receipt": receipt}


def make_case(tmp_path, *, version="2026", project=None, bundles=None, required=None, credentials=None):
    project = project or initial()
    materialized = materialize_project(project, bundles or {})
    if credentials is None:
        credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), version), str(uuid4()), "synthetic-private-token")
    target = credentials.target
    assert target.revit_version == version
    prepared = prepare_execution(materialized.planned, target=target, precondition=ContextPrecondition("native-doc", 8),
                                 operation_id=str(uuid4()), bulk=materialized.planned.bulk)
    submission = bind_project_submission(project, materialized, prepared)
    path = tmp_path / "original.sqlite"
    SavedExecutionRecord.create_project_new(path, prepared, submission)
    record = SavedExecutionRecord.load(path)
    result = {"ok": True}
    for index, op in enumerate(prepared.planned.ops):
        value = {"id": str(700 + index)}
        if op.op_name in ("create_level", "create_directshape", "create_solid_blend"):
            value.update(element_identity=ElementIdentityProof(700 + index, "original-" + op.op_id, "a" * 32).to_dict(),
                         element_identity_status="captured", element_identity_reason=None)
        result[op.op_id] = value
    changes = {"added": list(range(700, 700 + len(prepared.planned.ops))), "modified": [], "deleted": [],
               "transaction_names": ["KIR"], "truncated": False}
    response = response_for(prepared, credentials, result, changes=changes)
    return {"project": project, "materialized": materialized, "prepared": prepared, "record": record,
            "path": path, "credentials": credentials, "response": response, "result": result,
            "required": required or (TARGET_ADDRESS, *PROTECTED)}


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path)


def bind(case, **kwargs):
    case["response"]["receipt"]["result_json"] = json.dumps(case["result"])
    args = {"required_outputs": case["required"], "credentials": case["credentials"],
            "request_id": case["response"]["request_id"]}
    args.update(kwargs)
    return bind_original_publication(case["project"], case["record"], json.dumps(case["response"]), **args)


def proposed(project, target=TARGET_ADDRESS, value=3800.0):
    instance = next(i for i in project.instances if i.key == target[0])
    outputs = tuple(replace(o, operation={**_thaw(o.operation), "elev_mm": value}) if o.key == target[1] else o for o in instance.outputs)
    return project.replace_instance(replace(instance, outputs=outputs), expected_revision=project.revision_id)


def observation(case, publication, *, target_address=TARGET_ADDRESS, mutate=None, runtime=None, document_key="native-doc"):
    source = case["project"]
    target_id = output_id(source.project_id, *target_address)
    old_value = next(o.operation["elev_mm"] for i, o, oid in source.addressed_outputs() if oid == target_id)
    query = prepare_element_observation([r["element_identity"]["unique_id"] for r in publication.rows],
        target=runtime or publication.target, precondition=ContextPrecondition(document_key, 9), operation_id=str(uuid4()))
    auth = SessionCredentials(query.target, case["credentials"].session_id, case["credentials"].token)
    rows = {}
    for index, binding in enumerate(publication.rows):
        is_level = binding["source_op"] == "create_level"
        uid = binding["element_identity"]["unique_id"]
        current = observed_row(uid, is_level=is_level)
        current["element_identity"] = ElementIdentityProof(901 if binding["output_id"] == target_id
            else binding["element_identity"]["element_id"], uid, "b" * 32).to_dict()
        if is_level:
            value = old_value if binding["output_id"] == target_id else 0
            current["level"].update(project_elevation_mm=value, reported_elevation_mm=value)
            current["level"]["elevation_parameter"]["value_internal_feet"] = value / 304.8
        else:
            current["type_state"] = {"status": "none", **unavailable()}
        rows[f"observe_{index}"] = current
    if mutate:
        mutate(rows)
    response = response_for(query, auth, rows, changes={"added": [], "modified": [], "deleted": [],
        "transaction_names": [], "truncated": False})
    return parse_element_observation(query, json.dumps(response), credentials=auth, request_id=response["request_id"])


def plan(case, publication=None, observed=None, next_project=None, **kwargs):
    publication = publication or bind(case)
    observed = observed or observation(case, publication)
    return plan_level_elevation_update(case["project"], next_project or proposed(case["project"]),
        publication=publication, observation=observed, target=TARGET_ADDRESS, protected_outputs=PROTECTED, **kwargs)


def test_original_archive_mapping_is_inert_complete_selected_and_detached(case, monkeypatch):
    import kir.compiler
    import kir.revit_connector

    before = case["path"].read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("binding replayed original compiler/plan")
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.compiler, "compile_program", forbidden)
    monkeypatch.setattr(kir.revit_connector, "prepare_execution", forbidden)
    binding = bind(case)
    assert binding.source_revision_id == case["project"].revision_id
    assert binding.target == case["prepared"].target and binding.document_key == "native-doc"
    assert [(r["instance_key"], r["output_key"]) for r in binding.rows] == list(case["required"])
    assert binding.to_dict()["archive_digest"] == case["record"].digest
    assert binding.to_dict()["claims"]["native_project_attestation"] == "not_established"
    detached = binding.rows
    detached[0]["element_identity"]["unique_id"] = "foreign"
    assert binding.rows != detached and case["path"].read_bytes() == before
    with pytest.raises(TypeError): OriginalPublicationBindings()
    with pytest.raises(FrozenInstanceError): binding.document_key = "other"


@pytest.mark.parametrize("fault", ["legacy", "unavailable", "missing_reason", "wrong_schema", "extra_identity", "id_mismatch",
                                    "duplicate_uid_outside", "duplicate_primary_outside", "not_added", "deleted", "truncated"])
def test_original_identity_or_manifest_cannot_be_upgraded_by_available_payload(case, fault):
    oid = output_id(case["project"].project_id, *TARGET_ADDRESS)
    row = case["result"][oid]
    outside = case["result"][output_id(case["project"].project_id, "section", "other-level")]
    if fault == "legacy":
        for key in list(row):
            if key.startswith("element_identity"): del row[key]
    elif fault == "unavailable": row.update(**unavailable())
    elif fault == "missing_reason": row.pop("element_identity_reason")
    elif fault == "wrong_schema": row["element_identity"]["schema_version"] = "future"
    elif fault == "extra_identity": row["element_identity"]["owner"] = "invented"
    elif fault == "id_mismatch": row["element_identity"]["element_id"] = 999
    elif fault == "duplicate_uid_outside": outside["element_identity"]["unique_id"] = row["element_identity"]["unique_id"]
    elif fault == "duplicate_primary_outside": outside["id"] = row["id"]
    elif fault == "not_added": case["response"]["receipt"]["changes"]["added"].remove(int(row["id"]))
    elif fault == "deleted": case["response"]["receipt"]["changes"]["deleted"] = [int(row["id"])]
    else: case["response"]["receipt"]["changes"]["truncated"] = True
    # 🔴 E5 (2026-09-13) SPLIT THIS ASSERTION IN TWO, AND THE SPLIT IS THE POINT.
    # An identity that is absent or unavailable is a fact about ONE output; a
    # contradicted manifest, a duplicated id/UID or a deleted element is a fact
    # about the WHOLE receipt. Before E5 both threw away every mapping in the
    # publication, so elements really created in the model lost their identity
    # because a neighbour had none. Now the per-output faults refuse per output,
    # BY THE SAME NAME, and leave the neighbours bound; the global faults still
    # refuse everything, because there is nothing trustworthy left to bind.
    if fault in ("legacy", "unavailable"):
        bound = bind(case)
        refused = {tuple(row["address"]): row for row in bound.refused_rows}
        assert TARGET_ADDRESS in refused, refused
        assert refused[TARGET_ADDRESS]["state"] == "original_identity_unavailable"
        assert bound.completeness == "partial"
        # the neighbour kept its mapping — that is what was being destroyed
        assert bound.rows and all(row["output_id"] != oid for row in bound.rows)
        assert TARGET_ADDRESS not in {(row["instance_key"], row["output_key"]) for row in bound.rows}
    else:
        with pytest.raises(LevelUpdateRefusal): bind(case)


@pytest.mark.parametrize("fault", ["false", "missing_ok", "error", "err", "wrapper", "missing_row", "row_error", "post_violation",
                                    "post_malformed", "resolved_errors", "row_scalar"])
def test_narrow_flat_profile_does_not_copy_or_bypass_d1(case, fault):
    oid = output_id(case["project"].project_id, *TARGET_ADDRESS)
    if fault == "false": case["result"]["ok"] = False
    elif fault == "missing_ok": case["result"].pop("ok")
    elif fault in ("error", "err"): case["result"][fault] = "failure"
    elif fault == "wrapper": case["result"] = {"ok": True, "result": case["result"]}
    elif fault == "missing_row": case["result"].pop(oid)
    elif fault == "row_error": case["result"][oid]["error"] = "failure"
    elif fault == "post_violation": case["result"]["postcondition_violations"] = ["wrong geometry"]
    elif fault == "post_malformed": case["result"]["postcondition_violations"] = False
    elif fault == "resolved_errors": case["result"]["revit_errors_resolved"] = [{"resolution": "detach walls"}]
    else: case["result"][oid] = "700"
    with pytest.raises(LevelUpdateRefusal): bind(case)


def test_source_revision_and_metadata_are_not_inferred_from_equal_source(case):
    altered = case["project"].revise(expected_revision=case["project"].revision_id, metadata={"review": "different choice"})
    case["project"] = altered
    with pytest.raises(LevelUpdateRefusal, match="source_project_mismatch"): bind(case)


@pytest.mark.parametrize("fault", ["source", "operation", "document", "revision"])
def test_original_binding_axes_are_checked_against_archive_not_current_context(case, fault):
    receipt = case["response"]["receipt"]
    if fault == "source": receipt["source_sha256"] = "f" * 64
    elif fault == "operation": receipt["operation_id"] = str(uuid4())
    elif fault == "document": receipt["document_key"] = "another"
    else: receipt["precondition"]["revision"] = 9
    with pytest.raises(LevelUpdateRefusal, match="original_receipt_unavailable"): bind(case)


def test_macro_source_is_named_unsupported_not_flattened_into_a_fake_original(case, tmp_path):
    project = ProjectRevision("macro", [ModuleDefinition("m")], [ModuleInstance("section", "m", [
        NamedOutput("stack", {"op": "stack", "levels": 1, "floor": [
            {"op": "create_wall", "id": "wall", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]})])])
    root = tmp_path / "macro"
    root.mkdir()
    values = make_case(root, project=project, required=(("section", "stack"),))
    with pytest.raises(LevelUpdateRefusal, match="original_profile_unsupported"): bind(values)


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_only_new_level_mutation_is_planned_and_guarded_without_native_creates(tmp_path, version):
    values = make_case(tmp_path, version=version)
    original = bind(values)
    observed = observation(values, original)
    update = plan(values, original, observed)
    assert update.precondition is observed.precondition and update.target == observed.target
    assert len(update.planned.ops) == 1 and update.planned.ops[0].op_name == "set_param"
    op = update.planned.to_ops()[0]
    assert op["target"] == {"by": "element_id", "value": 901}
    assert op["param"] == "Отметка"
    assert {p.unique_id for p in update.expected_identities} >= {r["element_identity"]["unique_id"] for r in original.rows}
    generated = compile_program(update.planned, revit_version=version, expected_identities=update.expected_identities)
    assert generated.ok, generated.diagnostics
    assert "Level.Create" not in generated.csharp and "DirectShape.CreateElement" not in generated.csharp
    assert 'Set(U(3800.0))' in generated.csharp
    # 🔴 WAS `index("VersionGuid")` — a stand-in for the guard's position that
    # stopped pointing at the guard once the version half became opt-in (the
    # first `VersionGuid` in the source is now the WITNESS capture, which sits
    # AFTER the mutation, so the old line asserted the opposite of its intent).
    # The guard is asked for by name.
    assert (generated.csharp.index("identity_changed_since_read")
            < generated.csharp.index("// set_param update_level_elevation"))
    assert len(update.to_dict()["affected_output_ids"]) == 1
    assert update.to_dict()["claims"]["native_execution"] == "not_run"
    assert not hasattr(update, "execute_request")
    with pytest.raises(TypeError): LevelElevationUpdatePlan()


@pytest.mark.parametrize("fault", ["shared", "unknown_basis", "read_only", "duplicate", "wrong_named", "trim_name",
                                    "project_baseline", "reported_baseline", "parameter_baseline", "type_unavailable", "target_not_found"])
def test_observed_parameter_and_baseline_must_support_the_exact_setter(case, fault):
    original = bind(case)
    def mutate(rows):
        row = rows["observe_0"]
        level = row["level"]
        parameter = level["elevation_parameter"]
        if fault in ("shared", "unknown_basis"): level["elevation_base"] = 1 if fault == "shared" else 2
        elif fault == "read_only": parameter["is_read_only"] = True
        elif fault == "duplicate": parameter.update(name_match_count=2, name_resolves_builtin=False)
        elif fault == "wrong_named": parameter["name_resolves_builtin"] = False
        elif fault == "trim_name": parameter["name"] = " Отметка "
        elif fault == "project_baseline": level["project_elevation_mm"] = 3100
        elif fault == "reported_baseline": level["reported_elevation_mm"] = 3100
        elif fault == "parameter_baseline": parameter["value_internal_feet"] = 3100 / 304.8
        elif fault == "type_unavailable": row["type_state"] = {"status": "unavailable", **unavailable()}
        else:
            row.update(status="not_found", reason=None, name=None, category_id=None, is_level=None,
                       type_state=None, level_status="not_evaluated", level_reason=None, level=None, **unavailable())
    observed = observation(case, original, mutate=mutate)
    with pytest.raises(LevelUpdateRefusal): plan(case, original, observed)


@pytest.mark.parametrize("fault", ["metadata", "parameters", "name", "other_output", "module", "not_child", "bool", "huge", "same_numeric"])
def test_only_one_exact_authored_field_change_is_qualified(case, fault):
    changed = proposed(case["project"])
    section = changed.instances[0]
    if fault == "metadata": changed = replace(changed, metadata={"another": True})
    elif fault == "parameters": changed = replace(changed, instances=(replace(section, parameters={"height_mm": 4000}), *changed.instances[1:]))
    elif fault == "module": changed = replace(changed, modules=(*changed.modules, ModuleDefinition("another")))
    elif fault == "not_child": changed = replace(changed, parent_revision=None)
    elif fault in ("bool", "huge", "same_numeric"):
        changed = proposed(case["project"], value=True if fault == "bool" else 10**400 if fault == "huge" else 3000)
    else:
        key = "upper-level" if fault == "name" else "other-level"
        changed = replace(changed, instances=(replace(section, outputs=tuple(
            replace(o, operation={**_thaw(o.operation), "name": "changed"}) if o.key == key else o for o in section.outputs)), *changed.instances[1:]))
    with pytest.raises(LevelUpdateRefusal): plan(case, next_project=changed)


def test_sealed_source_cannot_receive_manual_native_edit_under_old_recipe(tmp_path):
    values = make_case(tmp_path, project=initial(explicit=False))
    with pytest.raises(LevelUpdateRefusal, match="level_output_not_explicit"):
        plan(values)


@pytest.mark.parametrize("required", [None, [], [TARGET_ADDRESS, TARGET_ADDRESS], [("missing", "output")], [("section", "wall")]])
def test_required_scope_is_explicit_complete_and_supported(case, required):
    with pytest.raises(LevelUpdateRefusal): bind(case, required_outputs=required)


@pytest.mark.parametrize("wrong", ["runtime", "document"])
def test_original_runtime_document_cannot_be_rebound_by_new_observation(case, wrong):
    original = bind(case)
    observed = observation(case, original, runtime=RuntimeTarget(str(uuid4()), str(uuid4()), "2026") if wrong == "runtime" else None,
                           document_key="different" if wrong == "document" else "native-doc")
    with pytest.raises(LevelUpdateRefusal, match="observation_document_mismatch"):
        plan(case, original, observed)


def test_scopes_cannot_drop_protected_outputs_or_protect_target(case):
    original = bind(case)
    observed = observation(case, original)
    for protected in ([], [TARGET_ADDRESS]):
        with pytest.raises(LevelUpdateRefusal):
            plan_level_elevation_update(case["project"], proposed(case["project"]), publication=original,
                observation=observed, target=TARGET_ADDRESS, protected_outputs=protected)


def test_archive_one_is_not_upgraded_to_project_original_ownership(case, tmp_path):
    record = SavedExecutionRecord.create_new(tmp_path / "legacy.sqlite", case["prepared"])
    case["record"] = record
    with pytest.raises(LevelUpdateRefusal, match="project_archive_required"): bind(case)


def test_a_binding_that_maps_nothing_is_an_absence_not_a_partial_success(case):
    """E5 keeps neighbours, but it does not invent a mapping out of nothing.

    Partial binding exists so one bad output cannot erase the identities of the
    others. When NO required output binds there are no others: returning an
    empty «partial» binding would hand the caller a record that maps nothing
    while reading as success. That is refused by name, and the name carries the
    per-output states that produced it.
    """
    for oid in list(case["result"]):
        row = case["result"][oid]
        if isinstance(row, dict):
            for key in [k for k in row if k.startswith("element_identity")]:
                del row[key]
    with pytest.raises(LevelUpdateRefusal) as refused:
        bind(case)
    assert refused.value.code == "original_binding_empty"
    assert "original_identity_unavailable" in str(refused.value)


def test_a_saved_partial_binding_proves_what_it_refused(case):
    """Schema /2: the retained record carries the refusals, and `digest` covers them.

    On 13.09 partiality lived only on the object, so a stored submission could
    prove which outputs bound and could not prove which were refused — a record
    that quietly forgets it was incomplete. This is the guard for that: the
    refusals survive serialisation, they are inside the digest, and a reader
    that strips them no longer gets the same record.
    """
    oid = output_id(case["project"].project_id, *TARGET_ADDRESS)
    row = case["result"][oid]
    for key in [k for k in row if k.startswith("element_identity")]:
        del row[key]

    bound = bind(case)
    assert bound.completeness == "partial"
    stored = bound.to_dict()
    assert stored["schema"] == "kir-original-publication-bindings/2"
    assert stored["binding_completeness"] == "partial"
    refused = stored["refused_outputs"]
    assert [tuple(item["address"]) for item in refused] == [TARGET_ADDRESS]
    assert refused[0]["state"] == "original_identity_unavailable"

    # read back: the same refusals, not a reconstruction
    assert [dict(item) for item in bound.refused_rows] == refused
    assert {(r["instance_key"], r["output_key"]) for r in stored["outputs"]}.isdisjoint(
        {tuple(item["address"]) for item in refused})

    # and the digest is what makes it a proof rather than a note
    from kir.project import _hash
    stripped = {k: v for k, v in stored.items()
                if k not in ("binding_digest", "refused_outputs", "binding_completeness")}
    assert _hash(stripped) != stored["binding_digest"], (
        "digest must cover the refusals; otherwise dropping them keeps the record valid")
    forged = {k: v for k, v in stored.items() if k != "binding_digest"}
    forged["refused_outputs"] = []
    forged["binding_completeness"] = "complete"
    assert _hash(forged) != stored["binding_digest"]


def test_a_complete_binding_says_so_in_the_record(case):
    bound = bind(case)
    stored = bound.to_dict()
    assert bound.completeness == "complete"
    assert stored["binding_completeness"] == "complete" and stored["refused_outputs"] == []


@pytest.mark.parametrize("op_name,extra", [
    ("set_param", {"param": "Comments", "value": "v"}),
    ("change_type", {"type": {"by": "element_id", "value": 100}}),
    ("delete", {}),
])
def test_a_write_target_may_be_named_by_the_only_address_that_survives(op_name, extra):
    """`{by: unique_id}` on the mutating ops — the address that outlives a session.

    An ElementId is an address inside one document and Revit reuses it after a
    deletion, so a program editing what a PREVIOUS publication created cannot
    honestly name its target by number. Until 13.09.2026 the only op in the
    language that consumed a UniqueId was `query_element_state`: reading by
    identity was expressible, writing by it was not.
    """
    from kir import compile_program
    from kir.tests.fixtures import GROUND_SNAPSHOT

    uid = "7ff4b512-b299-4d75-8107-62effd492f45-00042fe4"
    program = {"ops": [{"op": op_name, "id": "m",
                        "target": {"by": "unique_id", "value": uid}, **extra}]}
    if op_name == "delete":
        program["allow_destructive"] = True
    result = compile_program(program, revit_version="2023",
                             snapshot=GROUND_SNAPSHOT, isolation="atomic")
    assert result.ok, result.diagnostics
    assert f'doc.GetElement("{uid}")' in result.csharp
    # a number can be reused, a UniqueId cannot: the document is asked to
    # confirm the identity it just returned
    assert f'.UniqueId != "{uid}"' in result.csharp
    assert "query_element_state" in result.csharp, "the refusal must name the next move"


def test_a_malformed_unique_id_is_refused_with_the_place_to_get_a_real_one():
    from kir import compile_program
    from kir.tests.fixtures import GROUND_SNAPSHOT

    result = compile_program(
        {"ops": [{"op": "set_param", "id": "m", "param": "Comments", "value": "v",
                  "target": {"by": "unique_id", "value": "294076"}}]},
        revit_version="2023", snapshot=GROUND_SNAPSHOT, isolation="atomic")
    assert not result.ok
    message = result.diagnostics[0].message_ru
    assert "UniqueId" in message and "element_identity.unique_id" in message


UID_A = "7ff4b512-b299-4d75-8107-62effd492f45-00042fe4"
GUID_A = "7ff4b512b2994d75810762effd492f45"


def _compiled(op, **program):
    from kir import compile_program
    from kir.tests.fixtures import GROUND_SNAPSHOT

    result = compile_program({"ops": [op], **program}, revit_version="2023",
                             snapshot=GROUND_SNAPSHOT, isolation="atomic")
    return result


@pytest.mark.parametrize("op_name,extra", [
    ("set_param", {"param": "Комментарии", "value": "v"}),
    ("change_type", {"type": {"by": "element_id", "value": 100}}),
])
def test_a_write_declares_the_base_it_was_planned_against(op_name, extra):
    """`expected_identity` — the element the author READ, not the one to change.

    Without it a second edit computed from a stale read silently overwrites the
    first; that is the whole T10 subject. The check sits at the OP, so the
    refusal names which op's base went stale, and it carries the next move — a
    refusal that does not say what to do next sends the reader nowhere.
    """
    result = _compiled({"op": op_name, "id": "m",
                        "target": {"by": "element_id", "value": 274502},
                        "expected_identity": {"unique_id": UID_A, "version_guid": GUID_A},
                        **extra})
    assert result.ok, result.diagnostics
    # 🔴 WAS 2 («identity and version»), IS 1 — AND THAT IS THE POINT, NOT A
    # LOOSENED THRESHOLD. Both halves used to refuse with the same code, so a
    # document SAVE (which advances VersionGuid on every element and changes
    # none) was reported as the element having been swapped. The version half is
    # now opt-in and carries its own code; a base that does not ask for it emits
    # exactly ONE identity refusal, on the UniqueId.
    assert result.csharp.count("identity_changed_since_read") == 1, "только личность"
    assert "identity_version_differs_after_save" not in result.csharp, (
        "версия по умолчанию НЕ сверяется")
    assert 'VersionGuid.ToString("N")' not in result.csharp
    assert "query_element_state" in result.csharp


def test_one_read_base_cannot_describe_several_targets():
    result = _compiled({"op": "move_elements", "id": "mv", "delta_mm": [100, 0, 0],
                        "targets": [{"by": "element_id", "value": 274502},
                                    {"by": "element_id", "value": 274503}],
                        "expected_identity": {"unique_id": UID_A, "version_guid": GUID_A}})
    assert not result.ok
    assert "expected_identity" in result.diagnostics[0].message_ru


@pytest.mark.parametrize("value,expected,kind", [
    ("new", "old", "str"),
    ({"value": 3300, "unit": "mm"}, {"value": 3000, "unit": "mm"}, "mm"),
    ({"value": 2, "unit": "raw"}, {"value": 1, "unit": "raw"}, "raw"),
])
def test_a_parameter_write_can_be_pinned_to_the_value_that_was_read(value, expected, kind):
    """Compare-and-set, and it is the half that works on an unsaved document.

    `expected_identity` leans on VersionGuid, which on an unsaved document
    returns the DOCUMENT's episode — identical for every element (ОТК-26). The
    parameter's own value does not have that blindness.
    """
    result = _compiled({"op": "set_param", "id": "m", "param": "P",
                        "target": {"by": "element_id", "value": 274502},
                        "value": value, "expected_current": expected})
    assert result.ok, result.diagnostics
    assert "value_changed_since_read" in result.csharp
    assert "query_element_state" in result.csharp
    if kind == "mm":
        # the op's OWN ruler, not a second one invented for the comparison
        from kir.emit_model import tolerances
        assert str(tolerances("set_param")["length_mm"].cs) in result.csharp


def test_a_reference_value_refuses_compare_and_set_by_name():
    result = _compiled({"op": "set_param", "id": "m", "param": "P",
                        "target": {"by": "element_id", "value": 274502},
                        "value": {"material": "Бетон М300"},
                        "expected_current": {"material": "Кирпич керамический"}})
    assert not result.ok
    assert "expected_current" in result.diagnostics[0].message_ru


def test_deleting_names_its_circle_of_consequences_before_it_acts():
    """38 elements went with one delete on 13.09; the author saw it afterwards.

    `doc.Delete` returns the full list — after the fact. `GetDependentElements`
    is a read, so the same circle can be named BEFORE the effect; both numbers
    now sit in the receipt and their disagreement is its own field, because a
    prediction that quietly differs from the outcome is worse than none.
    """
    result = _compiled({"op": "delete", "id": "d",
                        "target": {"by": "element_id", "value": 274502}},
                       allow_destructive=True)
    assert result.ok, result.diagnostics
    source = result.csharp
    assert "GetDependentElements(null)" in source
    assert source.index("GetDependentElements(null)") < source.index("doc.Delete(")
    for field in ("dependents_predicted", "dependents_predicted_count",
                  "dependents_actual_count", "dependents_prediction_matched"):
        assert f'"{field}"' in source, field

