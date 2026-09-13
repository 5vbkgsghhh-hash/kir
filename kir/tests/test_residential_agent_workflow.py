"""Pilot gate distinguishes matching dimensions from compiler-valid operations."""
from dataclasses import replace

import pytest

from examples import residential_agent_workflow as pilot, residential_project as original
from examples.residential_recipes import tower_recipe
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_tasks import read_task, submit_task, task_history


@pytest.mark.parametrize("invalid", [False, "unknown_field", "extra_output"])
def test_selected_program_is_planned_before_pilot_decision(tmp_path, invalid):
    store = pilot.initialize(tmp_path / "project.sqlite")
    base = store.head()
    descriptor = tower_recipe(base)
    task = pilot.assign_recipe_task(store, "tower-review", descriptor, actor="manual-worker",
                                   expected_revision=base.revision_id)
    outputs = original.generate_outputs(base.project_id, "tower-b", descriptor["parameters"])
    if invalid == "unknown_field":
        outputs["concept-volume"]["unsupported_input_field"] = "must not be silently accepted"
    elif invalid == "extra_output":
        outputs["unrequested-level"] = {"op": "create_level", "elev_mm": 3000, "name": "Unrequested"}
    instance = next(item for item in base.instances if item.key == "tower-b")
    candidate = base.replace_instance(replace(instance, outputs=outputs, parameters=descriptor["parameters"]),
                                      expected_revision=base.revision_id)
    change = ChangeProposal(base, candidate, ProposalScope(instances=("tower-b",)), "manual-worker", "Selected shape request")
    task = submit_task(store, "tower-review", change, request_id="manual-proposal", expected_version=task["version"],
                       generation=0, actor="manual-worker")["task"]
    # Unknown fields alone do not change the dimension comparison. Unexpected
    # named outputs require a separate coverage guard even when compiler-valid.
    if invalid != "extra_output":
        assert all(row["status"] == "evaluated" for row in pilot._request_geometry(candidate, descriptor)["rows"])
    before = store.path.read_bytes()
    if invalid:
        code = "request_output_coverage_mismatch" if invalid == "extra_output" else "pilot_geometry_not_interpretable"
        with pytest.raises(pilot.PilotRefusal, match=code):
            pilot.accept_task(store, "tower-review", expected_revision=base.revision_id)
        assert store.path.read_bytes() == before and read_task(store, "tower-review") == task
        assert not any(event["kind"] == "decide" for event in task_history(store, "tower-review"))
    else:
        accepted = pilot.accept_task(store, "tower-review", expected_revision=base.revision_id)
        assert accepted["decision"]["task"]["state"] == "accepted"
        assert len(accepted["selected_plan_digest"]) == 64
        assert store.head().revision_id == candidate.revision_id
