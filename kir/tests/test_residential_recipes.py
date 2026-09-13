"""Actual sandbox recipes over saved ЖК; SQLite/OCCT are real, no Revit.

Compiler assertions are offline planning/code generation, not native execution
or proof of engineering adequacy. Recipe descriptors never invoke the kernel.
"""
from dataclasses import replace
import hashlib
import math

import pytest
from shapely.geometry import Polygon

from examples import residential_project as original
from examples import residential_recipes as recipes
from examples import residential_refinement as workflow
from kir.compiler import compile_program, plan_program
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, _canonical, output_id
from kir.project_merge import ProposalScope, merge_proposal
from kir.project_recipe import bind_recipe_result
from kir.project_refinement import refinement_view
from kir.project_store import ProjectStore
from kir.sandbox import execute_author_script
from kir.task_recipe_runner import RECIPE_POLICY


POLICY = replace(RECIPE_POLICY, probe_network=False)  # Required isolation unchanged.


def instances(project):
    return {instance.key: instance for instance in project.instances}


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    pytest.importorskip("OCP")
    store = workflow.create_store(tmp_path_factory.mktemp("residential") / "project.sqlite")
    previous = store.head()
    base = previous.revise(expected_revision=previous.revision_id, modules=(
        *previous.modules, ModuleDefinition(recipes.SECTION_MODULE), ModuleDefinition(recipes.TOWER_MODULE)))
    store.commit(base, expected_revision=previous.revision_id)
    assets = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
              for _, output, _ in base.geometry_references()}
    return store, base, assets


def evaluate(base, descriptor, actor):
    result = execute_author_script(descriptor["source"], policy=POLICY, params=descriptor["parameters"])
    assert result.ok, result.as_dict()
    assert result.isolation["namespaces"] == "user+mount+net"
    assert result.isolation["filesystem"] == "chroot"
    assert {entry["name"] for entry in result.params} == set(descriptor["parameters"])
    assert all(not entry["used_default"] for entry in result.params)
    bound = bind_recipe_result(base, instance_key=descriptor["instance_key"], module_key=descriptor["module_key"],
        source=descriptor["source"], parameters=descriptor["parameters"],
        output_bindings={key: output_id(base.project_id, descriptor["instance_key"], key)
                         for key in descriptor["output_keys"]}, result=result,
        author=actor, reason="Explicit evaluated residential recipe")
    assert bound.projection_refusal is None, bound.to_dict()
    assert bound.evaluation["program"] == result.to_program()
    assert set(result.to_program()) == {"ir_version", "intent", "ops"}
    assert plan_program(result.to_program()).ops
    return result, bound


@pytest.fixture(scope="module")
def evaluated(saved):
    _, base, _ = saved
    return {"tower-a": evaluate(base, recipes.section_recipe(base), "section-worker"),
            "tower-b": evaluate(base, recipes.tower_recipe(base), "tower-worker")}


def test_section_actual_geometry_named_members_and_refinement_are_preserved(saved, evaluated):
    store, base, _ = saved
    result, bound = evaluated["tower-a"]
    before, after = instances(base)["tower-a"], instances(bound.proposal.candidate)["tower-a"]
    assert len(after.outputs) == 21
    assert [output.key for output in after.outputs] == [output.key for output in before.outputs]
    assert bound.proposal.scope == ProposalScope(instances=("tower-a",), modules=(recipes.SECTION_MODULE,))
    operations = {output.key: output.to_dict()["operation"] for output in after.outputs}
    # Reference baseline generator is an independent unchanged source file;
    # explicit geometry measurements below are not merely ID/count checks.
    assert operations == original.generate_outputs(base.project_id, "tower-a", dict(after.parameters))
    for number in range(1, 4):
        prefix = f"storey-{number:02d}"
        level = operations[prefix + "-level"]
        assert level["elev_mm"] == (number - 1) * 4500
        assert level["name"] == f"tower-a: этаж {number}"
        slab = operations[prefix + "-slab"]
        holes = slab["contour"]["holes"]
        assert len(holes) == 1 and Polygon(holes[0]["points_mm"]).area == 4_000_000
        assert Polygon(holes[0]["points_mm"]).bounds == (5000, 3000, 7000, 5000)
        exterior = Polygon(slab["contour"]["outer"]["points_mm"])
        assert exterior.contains(Polygon(holes[0]["points_mm"]))
        assert exterior.bounds == (0, 0, 12800 if number == 3 else 14000, 9000)
        for suffix in ("slab", "wall-0", "wall-1", "wall-2", "wall-3", "space"):
            assert operations[prefix + "-" + suffix]["level"] == {
                "by": "ref", "value": output_id(base.project_id, "tower-a", prefix + "-level")}
        assert all(operations[prefix + f"-wall-{side}"]["height_mm"] == 4500 for side in range(4))
    assert after.parameters["twist_deg"] == before.parameters["twist_deg"] == 12
    assert _canonical(after.metadata["refinement"]) == _canonical(before.metadata["refinement"])
    source = store.get(before.metadata["refinement"]["source"]["revision_id"])
    report = refinement_view(bound.proposal.candidate, "tower-a", source=source)
    assert report["binding_status"] == "exact_supplied_source"
    assert report["geometry_preservation"] == "not_claimed"
    assert report["inactive_parameters"] == ["twist_deg"]
    assert bound.evaluation["sandbox_receipt"]["author_digest"] == hashlib.sha256(recipes.section_recipe(base)["source"].encode()).hexdigest()


def test_tower_actual_profiles_reproduce_rotation_taper_and_height(saved, evaluated):
    _, base, _ = saved
    _, bound = evaluated["tower-b"]
    candidate = bound.proposal.candidate
    after = instances(candidate)["tower-b"]
    assert [output.key for output in after.outputs] == ["concept-volume"]
    assert bound.proposal.scope == ProposalScope(instances=("tower-b",), modules=(recipes.TOWER_MODULE,))
    operation = after.outputs[0].to_dict()["operation"]
    assert operation == original.generate_outputs(base.project_id, "tower-b", dict(after.parameters))["concept-volume"]
    bottom, top = (operation[name]["outer"]["points_mm"] for name in ("profile", "profile_top"))
    assert Polygon(bottom).bounds == (24000, 0, 38000, 9000)
    assert Polygon(top).area / Polygon(bottom).area == pytest.approx(0.82 ** 2)
    assert Polygon(top).centroid.x == pytest.approx(31000)
    assert Polygon(top).centroid.y == pytest.approx(4500)
    angle = math.degrees(math.atan2(top[1][1] - top[0][1], top[1][0] - top[0][0]))
    assert angle == pytest.approx(-24)
    assert operation["height_mm"] == 8 * 4100 and operation["base_z_mm"] == 0
    assert operation["name"] == "tower-b" and operation["category"] == "mass"


def test_disjoint_candidates_merge_then_repeat_section_from_saved_parameter_context(saved, evaluated):
    store, base, assets = saved
    source_bytes = {key: value.dumps() for key, value in assets.items()}
    section = evaluated["tower-a"][1].proposal
    tower = evaluated["tower-b"][1].proposal
    first = merge_proposal(section, base, authorized_scope=section.scope)
    second = merge_proposal(tower, first.revision, authorized_scope=tower.scope)
    assert first.clean and second.clean
    store.commit(first.revision, expected_revision=base.revision_id)
    store.commit(second.revision, expected_revision=first.revision.revision_id)
    resumed = ProjectStore.open(store.path, readonly=False)
    merged = resumed.head()
    descriptor = recipes.section_recipe(merged, height_mm=4800., setback_mm=1600.)
    assert descriptor["parameters"]["project_id"] == merged.project_id
    _, repeated = evaluate(merged, descriptor, "section-worker-next")
    assert repeated.proposal.scope == ProposalScope(instances=("tower-a",))
    changed = repeated.proposal.candidate
    resumed.commit(changed, expected_revision=merged.revision_id)
    for key in ("tower-b", "tower-c", "podium"):
        assert _canonical(instances(changed)[key].to_dict()) == _canonical(instances(merged)[key].to_dict())
    for key in ("tower-c", "podium"):
        assert _canonical(instances(changed)[key].to_dict()) == _canonical(instances(base)[key].to_dict())
    for definition in base.modules:
        if definition.key not in (recipes.SECTION_MODULE, recipes.TOWER_MODULE):
            assert definition.to_dict() == next(item.to_dict() for item in changed.modules if item.key == definition.key)
    assert [identifier for _, _, identifier in changed.addressed_outputs()] == [identifier for _, _, identifier in base.addressed_outputs()]
    assert instances(changed)["tower-a"].parameters["twist_deg"] == 12
    for digest, data in source_bytes.items():
        assert resumed.get_asset(digest).dumps() == data
    source = resumed.get(instances(changed)["tower-a"].metadata["refinement"]["source"]["revision_id"])
    assert refinement_view(changed, "tower-a", source=source)["geometry_preservation"] == "not_claimed"
    materialized = materialize_project(changed, {digest: resumed.get_asset(digest) for digest in assets})
    for version in ("2023", "2026"):
        compiled = compile_program(materialized.planned, revit_version=version)
        assert compiled.ok, compiled.diagnostics


def test_descriptors_only_read_detached_inputs_and_source(saved, monkeypatch):
    _, base, _ = saved
    import kir.sandbox
    import kir.geometry_materialization
    def forbidden(*args, **kwargs):
        pytest.fail("descriptor unexpectedly executed a recipe/kernel")
    monkeypatch.setattr(kir.sandbox, "execute_author_script", forbidden)
    monkeypatch.setattr(kir.geometry_materialization, "materialize_project", forbidden)
    before = base.dumps()
    descriptor = recipes.section_recipe(base)
    descriptor["parameters"]["twist_deg"] = 999
    assert recipes.section_recipe(base)["parameters"]["twist_deg"] == 12
    assert base.dumps() == before


@pytest.mark.parametrize("case", ["unknown_parameter", "missing_parameter", "foreign_context", "missing_module", "changed_members"])
def test_unsupported_baseline_is_not_silently_projected(saved, case):
    _, base, _ = saved
    instance = instances(base)["tower-a"]
    parameters = dict(instance.parameters)
    if case == "unknown_parameter": parameters["unconsumed_design_intent"] = 200
    if case == "missing_parameter": parameters.pop("twist_deg")
    if case == "foreign_context": parameters["project_id"] = "foreign-project"
    replacement = replace(instance, parameters=parameters,
                          outputs=instance.outputs[:-1] if case == "changed_members" else instance.outputs)
    changed = base.replace_instance(replacement, expected_revision=base.revision_id)
    if case == "missing_module":
        changed = changed.revise(expected_revision=changed.revision_id,
            modules=tuple(item for item in changed.modules if item.key != recipes.SECTION_MODULE))
    with pytest.raises(recipes.ResidentialRecipeError): recipes.section_recipe(changed)


@pytest.mark.parametrize("kind,key,value", [
    ("section", "storey_height_mm", 0), ("section", "depth_mm", 5000),
    ("section", "terrace_setback_mm", 7000), ("section", "storeys", 4),
    ("tower", "storeys", 0), ("tower", "storeys", 8.5),
    ("tower", "storey_height_mm", True), ("tower", "twist_deg", float("inf")),
])
def test_actual_sandbox_names_invalid_dimensions_without_a_program(saved, kind, key, value):
    _, base, _ = saved
    descriptor = recipes.section_recipe(base) if kind == "section" else recipes.tower_recipe(base)
    descriptor["parameters"][key] = value
    result = execute_author_script(descriptor["source"], policy=POLICY, params=descriptor["parameters"])
    assert not result.ok and result.refusal is not None and not result.ops
