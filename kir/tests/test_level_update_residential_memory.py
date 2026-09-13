"""Real residential authoring/OCCT -> pure update; no filesystem/native Revit.

Archive codec runs in memory: this is NOT a SQLite persistence/restart test.
Publication and observation payloads are explicitly synthetic native evidence.
The FULL publication profile includes the retained concept as physical geometry
alongside the developed section. This checks that legacy profile's mechanics,
not whether that is the appropriate physical-publication selection.
"""
from dataclasses import replace
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from examples import residential_project as towers
from examples import residential_refinement as refinement
from examples import residential_with_podium as composed
from kir.geometry_materialization import materialize_project
from kir.project import PROJECT_SCHEMA_V2, ProjectRevision, _canonical, _thaw, output_id
from kir.project_handoff import handoff_instance_to_explicit
from kir.project_refinement import refinement_view
from kir.project_submission import bind_project_submission
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.contracts import ElementIdentityProof
from kir.revit_level_update import (LevelUpdateRefusal, bind_original_publication,
                                    plan_level_elevation_update, prepare_level_update)
from kir.revit_observation import prepare_element_observation, parse_element_observation
from kir.level_update_acceptance import assess_level_update
from kir.update_submission import bind_level_update_submission
from kir.saved_execution import SavedExecutionRecord, _capture
from kir.tests.test_revit_observation import row as observed_row, unavailable
from kir.tests.test_revit_level_update import response_for


def test_real_residential_handoff_and_one_level_update_in_memory():
    concept = towers.concept()
    upgraded = concept.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=concept.revision_id)
    source, bundle = composed.add_podium(upgraded)
    sealed = refinement.develop_section(source)
    base = handoff_instance_to_explicit(sealed, "tower-a", new_module_key="tower-a-explicit",
                                       expected_revision=sealed.revision_id)
    base = ProjectRevision.loads(base.dumps())
    untouched = {item.key: _canonical(item.to_dict()) for item in base.instances if item.key != "tower-a"}
    asset_before = bundle.dumps()
    materialized = materialize_project(base, {bundle.digest: bundle})
    section_addresses = tuple(("tower-a", f"storey-{number:02d}-{part}")
        for number in (1, 2, 3)
        for part in ("level", "slab", "wall-0", "wall-1", "wall-2", "wall-3", "space"))
    retained_concept = ("tower-a-concept", "concept-volume")
    expected_addresses = (*section_addresses, ("tower-b", "concept-volume"),
        ("tower-c", "concept-volume"), ("podium", "atrium-volume"), retained_concept)
    assert tuple((instance.key, output.key) for instance, output, _ in base.addressed_outputs()) == expected_addresses
    expected_ids = tuple(output_id(base.project_id, *address) for address in expected_addresses)
    assert materialized.selection is None
    assert tuple(operation.op_id for operation in materialized.planned.ops) == expected_ids
    retained_id = output_id(base.project_id, *retained_concept)
    assert retained_id == "0749c4721edb6cabca403e5fcd410b0bca363d6cad486284e0ea35d4fb7725f6"
    retained_instance = next(item for item in base.instances if item.key == retained_concept[0])
    assert retained_instance.metadata["role"] == "preserved_conceptual_source"
    retained_operation = next(op for op in materialized.planned.to_ops() if op["id"] == retained_id)
    assert retained_operation["op"] == "create_solid_blend" and retained_operation["category"] == "mass"
    selected = ("tower-a", "storey-02-level")
    protected = (("tower-b", "concept-volume"), ("tower-c", "concept-volume"), ("podium", "atrium-volume"))

    instance = next(item for item in base.instances if item.key == selected[0])
    changed = replace(instance, outputs=tuple(replace(output, operation={**_thaw(output.operation), "elev_mm": 3800.0})
        if output.key == selected[1] else output for output in instance.outputs))
    proposed = base.replace_instance(changed, expected_revision=base.revision_id)
    proposed = ProjectRevision.loads(proposed.dumps())

    for year in ("2023", "2026"):
        target = RuntimeTarget(str(uuid4()), str(uuid4()), year)
        credentials = SessionCredentials(target, str(uuid4()), "synthetic-credential")
        original = prepare_execution(materialized.planned, target=target, precondition=ContextPrecondition("synthetic-document", 8),
                                     operation_id=str(uuid4()), bulk=materialized.planned.bulk)
        submission = bind_project_submission(base, materialized, original)
        # Exercise the real checked archive codec without calling any file API.
        record = SavedExecutionRecord._from_bytes(_capture(original, submission=submission))
        payload = {"ok": True}
        for index, operation in enumerate(original.planned.ops):
            row = {"id": str(700 + index)}
            if operation.op_name in {"create_level", "create_solid_blend", "create_directshape"}:
                row.update(element_identity=ElementIdentityProof(700 + index, "original-" + operation.op_id, "a" * 32).to_dict(),
                    element_identity_status="captured", element_identity_reason=None)
            payload[operation.op_id] = row
        created_ids = [int(payload[operation.op_id]["id"]) for operation in original.planned.ops]
        assert len(set(created_ids)) == len(expected_ids)
        response = response_for(original, credentials, payload, changes={"added": created_ids,
            "modified": [], "deleted": [], "transaction_names": ["synthetic creation"], "truncated": False})
        # This fixture supplies affirmative proofs for three levels and four
        # conceptual/body outputs, not for the other eighteen primary IDs.
        # Every such proof must agree with the complete creation manifest,
        # including the retained concept outside the requested update scope.
        capture_addresses = (*(address for address in section_addresses if address[1].endswith("-level")),
            *expected_addresses[len(section_addresses):])
        captured_ids = {int(payload[operation.op_id]["id"]) for operation in original.planned.ops
            if "element_identity" in payload[operation.op_id]}
        assert captured_ids == {int(payload[output_id(base.project_id, *address)]["id"])
            for address in capture_addresses}
        assert int(payload[retained_id]["id"]) in captured_ids
        for omitted_id in sorted(captured_ids):
            incomplete = deepcopy(response)
            incomplete["receipt"]["changes"]["added"].remove(omitted_id)
            with pytest.raises(LevelUpdateRefusal) as refused:
                bind_original_publication(base, record, json.dumps(incomplete), required_outputs=(selected, *protected),
                    credentials=credentials, request_id=incomplete["request_id"])
            assert refused.value.code == "original_creation_unconfirmed"
        bound = bind_original_publication(base, record, json.dumps(response), required_outputs=(selected, *protected),
            credentials=credentials, request_id=response["request_id"])
        query = prepare_element_observation([row["element_identity"]["unique_id"] for row in bound.rows],
            target=target, precondition=ContextPrecondition("synthetic-document", 9), operation_id=str(uuid4()))
        rows = {}
        for index, binding in enumerate(bound.rows):
            uid = binding["element_identity"]["unique_id"]
            row = observed_row(uid, is_level=index == 0)
            row["element_identity"] = ElementIdentityProof(8000 + index, uid, "b" * 32).to_dict()
            if index == 0:
                row["level"].update(project_elevation_mm=3600.0, reported_elevation_mm=3600.0)
                row["level"]["elevation_parameter"]["value_internal_feet"] = 3600.0 / 304.8
            else:
                row["type_state"] = {"status": "none", **unavailable()}
            rows[f"observe_{index}"] = row
        observed_response = response_for(query, credentials, rows, changes={"added": [], "modified": [], "deleted": [],
            "transaction_names": [], "truncated": False})
        observed = parse_element_observation(query, json.dumps(observed_response), credentials=credentials,
                                             request_id=observed_response["request_id"])
        update = plan_level_elevation_update(base, proposed, publication=bound, observation=observed,
                                             target=selected, protected_outputs=protected)
        prepared = prepare_level_update(update, operation_id=str(uuid4()))
        assert prepared.expected_identities == update.expected_identities
        update_submission = bind_level_update_submission(update, prepared)
        update_record = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=update_submission))
        update_record.require_matches(prepared, level_update=update_submission)
        assert update_record.update_submission["before_observation"]["rows"] == observed.rows
        assert len(update_record.update_submission["original_publication"]["outputs"]) == 4
        # This entrypoint cannot silently substitute a later context or drop
        # one of the identity guards when the caller prepares the mutation.
        for overrides in ({"precondition": ContextPrecondition("synthetic-document", 10)},
                          {"expected_identities": ()}, {"target": target}):
            try:
                prepare_level_update(update, operation_id=str(uuid4()), **overrides)
            except TypeError:
                pass
            else:
                raise AssertionError("update preparation accepted a binding override")
        assert len(prepared.planned.ops) == 1 and prepared.planned.ops[0].op_name == "set_param"
        assert "Level.Create" not in prepared.source and "DirectShape.CreateElement" not in prepared.source
        assert "Set(U(3800.0))" in prepared.source
        assert prepared.precondition is observed.precondition
        report = update.to_dict()
        assert len(report["affected_output_ids"]) == 6 and len(report["protected_output_ids"]) == 3
        assert not set(report["affected_output_ids"]) & set(report["protected_output_ids"])
        assert {item.unique_id for item in update.expected_identities} >= {row["element_identity"]["unique_id"] for row in bound.rows}
        after_query = prepare_element_observation([binding["element_identity"]["unique_id"] for binding in bound.rows],
            target=target, precondition=ContextPrecondition("synthetic-document", 10), operation_id=str(uuid4()))
        after_rows = deepcopy(rows)
        after_level = after_rows["observe_0"]["level"]
        after_level.update(project_elevation_mm=3800.0, reported_elevation_mm=3800.0)
        after_level["elevation_parameter"]["value_internal_feet"] = 3800.0 / 304.8
        after_response = response_for(after_query, credentials, after_rows, changes={"added": [], "modified": [],
            "deleted": [], "transaction_names": [], "truncated": False})
        after = parse_element_observation(after_query, json.dumps(after_response), credentials=credentials,
                                          request_id=after_response["request_id"])
        mutation_op = prepared.planned.to_ops()[0]
        mutation_response = response_for(prepared, credentials, {"ok": True, mutation_op["id"]: {
            "id": "8000", "param": mutation_op["param"], "value": "synthetic display"}},
            changes={"added": [], "modified": [8000], "deleted": [], "transaction_names": ["synthetic setter"], "truncated": False})
        checked = assess_level_update(update, prepared, json.dumps(mutation_response), credentials=credentials,
            request_id=mutation_response["request_id"], after=after)
        assert checked.scope_satisfied and checked.target_satisfied
        assert checked.to_dict()["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"]
    assert {item.key: _canonical(item.to_dict()) for item in proposed.instances if item.key != "tower-a"} == untouched
    assert bundle.dumps() == asset_before
    assert refinement_view(proposed, "tower-a", source=source)["binding_status"] == "exact_supplied_source"
