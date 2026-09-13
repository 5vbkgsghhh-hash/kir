"""P03: order, recipe, output-key rename, and parameters — NAMED SEPARATELY.

The P03 registry requires "changes to order/recipe/parameters/metadata
named separately" and "unknown dependencies named." A measurement on
07.09.2026 against `bd37579` showed that of the four subjects, only ONE is
named separately:

| subject | before the fix |
|---|---|
| instance output reordering | `operation_order_changed` with an address — holds |
| module recipe change | `instance_module_digest_changed` — the recipe is not named, no cause given |
| output key rename | `removed`+`added`, the pair is not named |
| instance parameter edit | `instance_parameters_changed` — the parameter's NAME is not named |

None of the probes below executes KIR or touches Revit.
"""
from __future__ import annotations

from kir import sdk
from kir.project import (ModuleDefinition, ModuleInstance, ProjectRevision,
                         RecipePin, output_id)
from kir.project_diff import diff_projects


def oid(key, instance="a"):
    return output_id("p", instance, key)


def level(elevation=0, name="Level"):
    return sdk.create_level(elev_mm=elevation, name=name)


def wall(level_key="level"):
    return sdk.create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000,
                           level=sdk.ref(oid(level_key)))


def row(report, op_id):
    return next(item for item in report["outputs"] if item["op_id"] == op_id)


def recipe_project(source="def build(): return 1", environment="a" * 64,
                   entrypoint="build", dependencies=None):
    module = ModuleDefinition("m", "sealed_evaluation", RecipePin(
        source, environment, entrypoint, dependencies or {}))
    return ProjectRevision("p", [module], [ModuleInstance("a", "m", {"level": level()})])


def revised_recipe(before, **pin):
    fields = {"source": "def build(): return 1", "environment": "a" * 64,
              "entrypoint": "build", "dependencies": {}, **pin}
    module = ModuleDefinition("m", "sealed_evaluation", RecipePin(
        fields["source"], fields["environment"], fields["entrypoint"], fields["dependencies"]))
    return before.revise(expected_revision=before.revision_id, modules=[module],
                         instances=[ModuleInstance("a", "m", {"level": level()})])


# --- (a) reordering ----------------------------------------------------------

def test_reordering_outputs_of_one_instance_is_named_order_not_a_payload_change():
    """Reordering WITHOUT editing values remains `unchanged` under load."""
    outputs = {"one": level(0, "One"), "two": level(3000, "Two"), "three": level(6000, "Three")}
    before = ProjectRevision("p", [ModuleDefinition("m")], [ModuleInstance("a", "m", outputs)])
    after = before.replace_instance(
        ModuleInstance("a", "m", {key: outputs[key] for key in ("three", "two", "one")}),
        expected_revision=before.revision_id)
    plan = diff_projects(before, after)
    report = plan.to_dict()
    assert plan.changed == ()
    assert set(plan.affected) == {oid(key) for key in ("one", "two", "three")}
    assert report["operation_order"]["reordered"] == list(plan.affected)
    for key in ("one", "two", "three"):
        record = row(report, oid(key))
        assert record["payload_status"] == "unchanged"
        assert record["reasons"] == ["operation_order_changed"]
        assert (record["instance_key"], record["output_key"]) == ("a", key)


# --- (b) recipe ---------------------------------------------------------------

def test_recipe_source_change_is_named_with_its_cause_not_only_a_digest():
    before = recipe_project()
    after = revised_recipe(before, source="def build(): return 2")
    record = row(diff_projects(before, after).to_dict(), oid("level"))
    assert "module_recipe_source_changed" in record["reasons"]
    assert "instance_module_digest_changed" in record["reasons"]


def test_each_recipe_field_gets_its_own_cause_and_they_do_not_leak():
    cases = {
        "module_recipe_source_changed": {"source": "def build(): return 2"},
        "module_recipe_environment_digest_changed": {"environment": "b" * 64},
        "module_recipe_entrypoint_changed": {"entrypoint": "make"},
        "module_recipe_dependencies_changed": {"dependencies": {"numpy": "c" * 64}},
    }
    before = recipe_project()
    for expected, change in cases.items():
        record = row(diff_projects(before, revised_recipe(before, **change)).to_dict(), oid("level"))
        named = {reason for reason in record["reasons"] if reason.startswith("module_recipe_")}
        assert named == {expected}, (expected, named)


def test_gaining_and_losing_a_recipe_are_two_different_named_events():
    explicit = ProjectRevision("p", [ModuleDefinition("m")], [ModuleInstance("a", "m", {"level": level()})])
    sealed = explicit.revise(
        expected_revision=explicit.revision_id,
        modules=[ModuleDefinition("m", "sealed_evaluation", RecipePin("def build(): return 1", "a" * 64))],
        instances=[ModuleInstance("a", "m", {"level": level()})])
    gained = row(diff_projects(explicit, sealed).to_dict(), oid("level"))["reasons"]
    lost = row(diff_projects(sealed, explicit).to_dict(), oid("level"))["reasons"]
    assert "module_recipe_added" in gained and "module_owner_changed" in gained
    assert "module_recipe_removed" in lost and "module_owner_changed" in lost


# --- (c) key rename ------------------------------------------------------------

def test_rekey_stays_remove_add_but_the_pair_is_named_with_both_addresses():
    before = ProjectRevision("p", [ModuleDefinition("m")],
                             [ModuleInstance("a", "m", {"level": level(), "wall": wall()})])
    after = before.replace_instance(ModuleInstance("a", "m", {"renamed": level(), "wall": wall()}),
                                    expected_revision=before.revision_id)
    plan = diff_projects(before, after)
    report = plan.to_dict()
    assert plan.removed == (oid("level"),) and plan.added == (oid("renamed"),)
    assert report["rekeyed"] == [{
        "before_instance_key": "a", "before_output_key": "level", "before_op_id": oid("level"),
        "after_instance_key": "a", "after_output_key": "renamed", "after_op_id": oid("renamed")}]
    assert "output_rekeyed" in row(report, oid("level"))["reasons"]
    assert "output_rekeyed" in row(report, oid("renamed"))["reasons"]


def test_two_identical_bodies_renamed_at_once_are_not_paired_by_guess():
    outputs = {"one": level(), "two": level(), "wall": wall("one")}
    before = ProjectRevision("p", [ModuleDefinition("m")], [ModuleInstance("a", "m", outputs)])
    after = before.replace_instance(
        ModuleInstance("a", "m", {"first": level(), "second": level(), "wall": wall("one")}),
        expected_revision=before.revision_id)
    report = diff_projects(before, after).to_dict()
    assert len(report["added"]) == len(report["removed"]) == 2
    assert report["rekeyed"] == []
    assert all("output_rekeyed" not in item["reasons"] for item in report["outputs"])


# --- (d) a parameter the outputs do not depend on -------------------------------

def test_parameter_change_names_the_parameter_and_the_undeclared_dependency():
    before = ProjectRevision("p", [ModuleDefinition("m")], [ModuleInstance(
        "a", "m", {"level": level(), "wall": wall()}, {"note_only": 1, "storey_height_mm": 3000})])
    after = before.replace_instance(ModuleInstance(
        "a", "m", {"level": level(), "wall": wall()}, {"note_only": 2, "storey_height_mm": 3000}),
        expected_revision=before.revision_id)
    plan = diff_projects(before, after)
    report = plan.to_dict()
    assert plan.changed == ()
    assert set(plan.affected) == {oid("level"), oid("wall")}
    for key in ("level", "wall"):
        record = row(report, oid(key))
        assert record["changed_parameters"] == ["note_only"]
        assert "instance_parameters_changed" in record["reasons"]
    assert any("parameter" in text for text in report["analysis"]["limitations"])


def test_untouched_instance_carries_no_parameter_names():
    outputs = {"level": level()}
    before = ProjectRevision("p", [ModuleDefinition("m")], [
        ModuleInstance("a", "m", outputs, {"note_only": 1}),
        ModuleInstance("b", "m", {"other": level(3000, "Other")}, {"note_only": 1})])
    after = before.replace_instance(ModuleInstance("a", "m", outputs, {"note_only": 2}),
                                    expected_revision=before.revision_id)
    report = diff_projects(before, after).to_dict()
    assert row(report, oid("level", "a"))["changed_parameters"] == ["note_only"]
    assert "changed_parameters" not in row(report, oid("other", "b"))
