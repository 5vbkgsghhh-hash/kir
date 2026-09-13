"""Selected authored programs retain dependency operands, not whole projects."""
from dataclasses import replace

import pytest

from kir.compiler import plan_program
from kir.diag import KirRefusal
from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                         NamedOutput, PROJECT_SCHEMA_V2, ProjectRevision, output_id)
from kir.project_selection import ProjectSelectionError, selected_instance_program


def ref(instance, key):
    return {"by": "ref", "value": output_id("p", instance, key)}


def project(*, wall_changes=None, reorder=False):
    library = ModuleInstance("types", "m", {
        "wall": {"op": "create_wall_type", "source_type": {"by": "element_id", "value": 4001},
                 "new_name": "Explicit wall", "layers": [{"width_mm": 300, "function": "Structure"}]},
        "unused": {"op": "unimplemented_future_op"}})
    levels = ModuleInstance("levels", "m", {"L": {"op": "create_level", "name": "L", "elev_mm": 0}})
    section = ModuleInstance("section", "m", {
        "wall": {"op": "create_wall", "level": ref("levels", "L"), "type": ref("types", "wall"),
                 "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000, **(wall_changes or {})}})
    door = ModuleInstance("door", "m", {"entry": {"op": "create_door", "host": ref("section", "wall"),
                                                        "offset_mm": 2000}})
    unrelated = ModuleInstance("body", "m", [NamedOutput("solid", {"op": "create_directshape", "category": "mass"},
                                                       BodyRepresentation("a" * 64, "b" * 64))])
    instances = [library, levels, section, door, unrelated]
    if reorder:
        instances[0], instances[2] = instances[2], instances[0]
    return ProjectRevision("p", [ModuleDefinition("m")], instances, schema=PROJECT_SCHEMA_V2)


def test_transitive_closure_preserves_exact_order_operands_and_ignores_unrelated_drafts_and_body():
    original = project()
    before = original.dumps()
    program = selected_instance_program(original, "door")
    assert [op["id"] for op in program["ops"]] == [output_id("p", i, k) for i, k in
        [("types", "wall"), ("levels", "L"), ("section", "wall"), ("door", "entry")]]
    assert program["ops"][0]["source_type"] == {"by": "element_id", "value": 4001}
    assert program["ops"][2]["type"] == ref("types", "wall")
    assert plan_program(program).plan_digest
    program["ops"][0]["layers"][0]["width_mm"] = 999
    assert original.dumps() == before


@pytest.mark.parametrize("changes,reason", [
    ({"type": ref("absent", "type")}, "unresolved_reference"),
    ({"type": ref("levels", "L")}, "incompatible_reference_kind"),
    ({"type": {"by": "ref", "value": []}}, "malformed_reference"),
    ({"type": ref("types", "unused")}, "producer_contract_unknown"),
])
def test_invalid_dependency_is_not_silently_removed(changes, reason):
    with pytest.raises(ProjectSelectionError, match=reason):
        selected_instance_program(project(wall_changes=changes), "section")


def test_forward_reference_is_not_repaired_by_reordering():
    with pytest.raises(ProjectSelectionError, match="reference_not_earlier"):
        selected_instance_program(project(reorder=True), "section")


def test_selected_body_requires_explicit_materialization():
    with pytest.raises(ProjectSelectionError, match="materialization"):
        selected_instance_program(project(), "body")


def test_body_dependency_cannot_be_substituted_with_empty_template():
    original = project()
    consumer = ModuleInstance("consumer", "m", {"probe": {"op": "set_param", "target": ref("body", "solid"),
                                                          "param": "Comments", "value": "changed"}})
    changed = original.with_instances([*original.instances, consumer], expected_revision=original.revision_id)
    with pytest.raises(ProjectSelectionError, match="materialization"):
        selected_instance_program(changed, "consumer")


def test_unknown_opcode_and_wrong_version_refuse():
    with pytest.raises(ProjectSelectionError, match="unknown_or_macro_operation"):
        selected_instance_program(project(), "types")
    with pytest.raises(ProjectSelectionError, match="uninterpreted_ir_version"):
        selected_instance_program(replace(project(), ir_version="future"), "section")


@pytest.mark.parametrize("key", ["absent", None, [], True])
def test_absent_or_invalid_instance_refuses(key):
    with pytest.raises(ProjectSelectionError, match="absent"):
        selected_instance_program(project(), key)


def test_closure_does_not_claim_semantic_validation_or_strip_unknown_fields():
    original = project(wall_changes={"nonsense": ref("absent", "fake")})
    selected = selected_instance_program(original, "section")
    assert selected["ops"][-1]["nonsense"] == ref("absent", "fake")
    with pytest.raises(KirRefusal):
        plan_program(selected)
