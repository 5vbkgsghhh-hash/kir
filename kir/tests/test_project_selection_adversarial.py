"""Selected dependency planning must not enlarge the XY evidence scope."""
from dataclasses import replace

from examples import residential_project as towers, residential_refinement as refinement
from kir.compiler import plan_program
from kir.design_check import spatial_model_from_ops
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, _hash, _thaw, output_id
from kir.project_selection import selected_instance_program
from kir.section_plan_acceptance import assess_section_plan_change


def test_foreign_wall_cannot_repair_selected_section_gap_or_change_xy_digest_scope():
    source = towers.concept()
    before = refinement.develop_section(source)
    section = before.instances[0]
    wall_key = "storey-02-wall-0"
    wall = next(item for item in section.outputs if item.key == wall_key)
    wall_type_id = output_id(before.project_id, "catalogue", "wall-type")
    library = ModuleInstance("catalogue", "catalogue-module", {
        "wall-type": {"op": "create_wall_type", "new_name": "Selected wall type",
                      "source_type": {"by": "element_id", "value": 4001},
                      "layers": [{"width_mm": 250., "function": "Structure"}]}})
    outputs = []
    for output in section.outputs:
        operation = _thaw(output.operation)
        if operation["op"] == "create_wall":
            operation["type"] = {"by": "ref", "value": wall_type_id}
        if output.key == wall_key:
            # The foreign wall below supplies precisely this missing segment.
            operation["p1_mm"][0] -= 2000.
        outputs.append(replace(output, operation=operation))
    selected = replace(section, outputs=outputs)
    closing_wall = _thaw(wall.operation)
    closing_wall["p0_mm"][0] = closing_wall["p1_mm"][0] - 2000.
    foreign = ModuleInstance("foreign", "catalogue-module", [NamedOutput("wall", closing_wall)])
    proposed = before.revise(expected_revision=before.revision_id,
        modules=[*before.modules, ModuleDefinition("catalogue-module")],
        instances=[library, selected, *before.instances[1:], foreign])
    frozen = proposed.dumps()
    program = selected_instance_program(proposed, selected.key)
    planned = plan_program(program)
    selected_ids = {output_id(proposed.project_id, selected.key, output.key) for output in selected.outputs}
    foreign_id = output_id(proposed.project_id, foreign.key, "wall")
    assert {op["id"] for op in program["ops"]} == selected_ids | {wall_type_id}
    assert program["ops"][0]["id"] == wall_type_id
    assert foreign_id not in {op["id"] for op in program["ops"]}

    # Positive counterfactual: including this real authored foreign wall really
    # does hide the gap. Thus a smaller test that merely counts IDs is weaker.
    contaminated = {**program, "ops": [*program["ops"], {**closing_wall, "id": foreign_id}]}
    assert plan_program(contaminated).plan_digest
    full_model, _ = spatial_model_from_ops(contaminated, building_id=before.project_id, close_tol_mm=0.)
    room_id = output_id(before.project_id, selected.key, "storey-02-space")
    assert any(room.id == room_id and room.boundary for room in full_model.rooms)

    report = assess_section_plan_change(before, proposed, source=source, instance_key=selected.key,
        required_void_chain=[f"storey-{i:02d}-slab" for i in (1, 2, 3)],
        protected_instances=["tower-b", "tower-c"]).to_dict()
    row = next(row for row in report["rows"]
               if row["predicate"] == "room_axis_enclosure" and row["subject"] == "storey-02-space")
    assert row["status"] == "violated"
    assert row["reason"] == "room_not_enclosed_by_authored_axes"
    # Report explicitly binds the PLANNING closure, although XY only interprets
    # the original selected operations. This is not a whole-project digest.
    assert report["section_plans"]["proposed"] == planned.plan_digest
    assert report["section_program_digests"]["proposed"] == _hash(program)
    assert proposed.dumps() == frozen
