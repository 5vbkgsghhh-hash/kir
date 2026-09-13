"""Real SDK -> saved project -> resumed change -> planner -> CLI/compiler.

These are offline authoring/compilation checks, not Revit execution evidence.
"""
from __future__ import annotations

import contextlib
from dataclasses import replace
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir import __main__ as cli, compile_program
from kir.project import ModuleDefinition, ModuleInstance, ProjectError, ProjectRevision, RecipePin


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "residential_project.py"


@pytest.fixture
def example():
    spec = importlib.util.spec_from_file_location("kir_residential_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call(args, source=""):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(sys, "stdin", io.StringIO(source))
            code = cli.main(args)
    return code, out.getvalue(), err.getvalue()


def _fresh(args, source=""):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, *args], input=source, text=True,
                          capture_output=True, cwd=ROOT, env=env, timeout=30)


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_all_three_saved_stages_compile_without_a_revit_snapshot(example, version):
    for project in example.workflow():
        restored = ProjectRevision.loads(project.dumps())
        assert restored.revision_id == project.revision_id
        assert restored.plan().to_ops()
        compiled = compile_program(restored.to_program(), revit_version=version)
        assert compiled.ok, [(d.code, d.message_ru) for d in compiled.diagnostics]
        assert compiled.csharp


def test_refinement_retains_other_towers_and_then_preserves_output_ids(example):
    concept, refined, changed = example.workflow()
    assert len(concept.to_program()["ops"]) == 3
    assert len(refined.to_program()["ops"]) == 23
    assert refined.parent_revision == concept.revision_id
    assert changed.parent_revision == refined.revision_id
    assert refined.instances[1:] == concept.instances[1:]
    assert changed.instances[1:] == refined.instances[1:]
    assert changed.instances[0].metadata["refines"] == refined.instances[0].metadata["refines"]
    before = {op["id"]: op for op in refined.to_program()["ops"]}
    after = {op["id"]: op for op in changed.to_program()["ops"]}
    assert before.keys() == after.keys()
    level_id = example.output_id(changed.project_id, "tower-a", "storey-02-level")
    assert before[level_id]["elev_mm"] == 3600
    assert after[level_id]["elev_mm"] == 4200
    slab_id = example.output_id(changed.project_id, "tower-a", "storey-03-slab")
    assert before[slab_id]["contour"]["outer"]["points_mm"][1][0] == 13100
    assert after[slab_id]["contour"]["outer"]["points_mm"][1][0] == 12200
    assert before[slab_id]["contour"]["holes"] == after[slab_id]["contour"]["holes"]


def test_regeneration_from_persisted_parameters_matches_saved_outputs(example):
    project = ProjectRevision.loads(example.workflow()[-1].dumps())
    for item in project.instances:
        regenerated = example.generate_outputs(project.project_id, item.key,
                                               dict(item.parameters))
        expected = {output.key: output.to_dict()["operation"] for output in item.outputs}
        assert regenerated == expected


@pytest.mark.parametrize("field", ["source", "environment_digest", "entrypoint", "dependencies"])
def test_changed_generator_cannot_claim_the_saved_recipe_produced_new_outputs(example, field):
    initial = example.concept()
    pin = initial.modules[0].recipe
    changes = {
        "source": pin.source + "\n# prior saved generator\n",
        "environment_digest": "a" * 64,
        "entrypoint": "previous_build",
        "dependencies": {"kir.sdk": "b" * 64},
    }
    old_definition = replace(initial.modules[0], recipe=replace(pin, **{field: changes[field]}))
    old_project = ProjectRevision(
        initial.project_id, [old_definition],
        [replace(item, module_digest=None) for item in initial.instances],
    )
    restored = ProjectRevision.loads(old_project.dumps())
    before = restored.dumps()
    with pytest.raises(ProjectError, match="generator definition"):
        example.develop_section(restored)
    assert restored.dumps() == before


def test_schematic_redesign_records_the_concept_geometry_it_does_not_preserve(example):
    """Four facts are alive — but they are declared by a SCHEMA-BEARING
    RECORD, not by the generator.

    🔴 WHY THE TEST WAS REWRITTEN (81bc166,
    `examples/residential_project.py:107-114`). Before that commit,
    `instance()` itself put a loose `refinement` of four bare fields into
    metadata — with no schema, no source, and no members. This shape is
    rejected by name by `kir.project_refinement`
    (`legacy_unbound_refinement`, `_LEGACY_FIELDS`), meaning ONE fact had
    two carriers, and only one of them was readable. The previous
    version of the test was pinning down exactly the loose carrier: it
    read `section.metadata["refinement"]` directly and so failed with
    `KeyError: 'refinement'` as soon as the generator was forbidden from
    writing it.

    The property has NOT been lost by the product. The only legitimate
    writer of kinship is `annotate_schematic_refinement`, and it declares
    ALL FOUR facts (`kind`, `geometry_preserved`, `losses`,
    `inactive_parameters`) plus what the loose record could not carry: a
    schema, the source's address, and a named list of members. The test
    goes through this path — the public API, not a direct write to
    metadata — and at the end checks that the declared loss is BEHAVIOR:
    `twist_deg` really does not affect the section's outputs.
    """
    from kir.project_refinement import REFINEMENT_SCHEMA, annotate_schematic_refinement

    initial, refined, changed = example.workflow()
    for project in (refined, changed):
        section = project.instances[0]
        assert "refinement" not in section.metadata  # the generator does NOT declare the shape
        annotated = annotate_schematic_refinement(
            initial, section,
            source_instance_key=section.key, source_output_key="concept-volume",
            roles={output.key: example._ROLE_BY_OP[output.operation["op"]]
                   for output in section.outputs},
            losses=("concept_twist_removed", "concept_top_taper_removed"),
            inactive_parameters=("twist_deg",))
        refinement = annotated.metadata["refinement"]
        assert refinement["schema"] == REFINEMENT_SCHEMA
        assert refinement["kind"] == "schematic_redesign"
        assert refinement["geometry_preserved"] is False
        assert set(refinement["losses"]) == {"concept_twist_removed", "concept_top_taper_removed"}
        assert refinement["inactive_parameters"] == ("twist_deg",)
        # What the loose record did not carry: whose descendant this is and which outputs it covered.
        assert refinement["source"]["instance_key"] == section.key
        assert refinement["source"]["output_key"] == "concept-volume"
        assert {member["output_key"] for member in refinement["members"]} == {
            output.key for output in section.outputs}
        # A declared loss is not a word but behavior: `twist_deg` is inert.
        other_twist = dict(section.parameters, twist_deg=47)
        assert example.generate_outputs(project.project_id, section.key, other_twist) == {
            output.key: output.to_dict()["operation"] for output in section.outputs
        }


@pytest.mark.parametrize("width,depth", [(6000, 4000), (7900, 9000), (14000, 5000)])
def test_example_refuses_a_shaft_outside_or_touching_the_section(example, width, depth):
    original = example.concept().instances[0]
    parameters = dict(original.parameters, representation="section", width_mm=width, depth_mm=depth)
    with pytest.raises(ValueError, match="shaft must be strictly inside"):
        example.instance(original.key, parameters)


def test_example_accepts_a_shaft_strictly_inside_the_smallest_storey(example):
    project = example.concept()
    original = project.instances[0]
    parameters = dict(original.parameters, representation="section", width_mm=7901, depth_mm=5001)
    replacement = example.instance(original.key, parameters)
    assert project.replace_instance(replacement, expected_revision=project.revision_id).plan().to_ops()


def test_saved_section_can_be_changed_in_a_fresh_process(example):
    _, refined, expected = example.workflow()
    result = _fresh(["-c", (
        "import sys; from kir.project import ProjectRevision; "
        "from examples.residential_project import develop_section; "
        "p = ProjectRevision.loads(sys.stdin.read()); "
        "print(develop_section(p, height_mm=4200, setback_mm=1800).dumps())"
    )], refined.dumps())
    assert result.returncode == 0, result.stderr
    changed = ProjectRevision.loads(result.stdout)
    assert changed.revision_id == expected.revision_id
    assert changed.parent_revision == refined.revision_id
    assert changed.instances[1:] == refined.instances[1:]


def test_export_uses_the_same_operation_budget_as_the_build_command(monkeypatch):
    from kir import compiler

    monkeypatch.setattr(compiler, "MAX_OPS_PER_PROGRAM", 2)
    monkeypatch.setattr(compiler, "MAX_BULK_OPS", 4)
    project = ProjectRevision("budget", [ModuleDefinition("m")], [ModuleInstance(
        "i", "m", {f"level-{i}": {"op": "create_level", "name": str(i), "elev_mm": i * 3000}
                   for i in range(3)})])
    assert len(project.plan(bulk=True).to_ops()) == 3
    code, output, error = _call(["project", "export", "-"], project.dumps())
    assert code == cli.REFUSED
    assert not output and "KIR-L001" in error


def test_project_cli_inspection_does_not_claim_semantic_or_native_verification(example):
    project = example.concept()
    code, output, error = _call(["project", "inspect", "-"], project.dumps())
    assert code == cli.ANSWERED and not error
    summary = json.loads(output)
    assert summary["project_id"] == project.project_id
    assert summary["revision_id"] == project.revision_id
    assert summary["outputs"] == 3
    assert summary["integrity"] == "consistent"
    assert summary["semantic_validation"] == "not_run"
    assert summary["execution"] == "not_run"


def test_export_and_build_are_composable_real_cli_commands(example):
    project = example.workflow()[-1]
    exported = _fresh(["-m", "kir", "project", "export", "-"], project.dumps())
    assert exported.returncode == cli.ANSWERED, exported.stderr
    assert json.loads(exported.stdout) == project.to_program()
    assert "не выполнялись" in exported.stderr
    built = _fresh(["-m", "kir", "build", "-", "--revit", "2026"], exported.stdout)
    assert built.returncode == cli.ANSWERED, built.stderr
    assert "Wall.Create" in built.stdout


def test_example_itself_is_a_fresh_process_project_producer():
    authored = _fresh([str(EXAMPLE), "--stage", "refined"])
    assert authored.returncode == 0, authored.stderr
    loaded = ProjectRevision.loads(authored.stdout)
    assert len(loaded.to_program()["ops"]) == 23
    inspected = _fresh(["-m", "kir", "project", "inspect", "-"], authored.stdout)
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["revision_id"] == loaded.revision_id


def test_inert_recipe_never_runs_on_load_inspect_or_export():
    recipe = RecipePin("raise RuntimeError('must never run')", "a" * 64)
    project = ProjectRevision("inert", [ModuleDefinition("m", "sealed_evaluation", recipe)],
                              [ModuleInstance("i", "m", {
                                  "ground": {"op": "create_level", "elev_mm": 0,
                                             "name": "Ground"}})])
    for action in ("inspect", "export"):
        result = _fresh(["-m", "kir", "project", action, "-"], project.dumps())
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("source", ["", "{", "null", "[]", '{"schema":1,"schema":2}'])
def test_malformed_project_has_named_read_failure_and_no_partial_output(source):
    code, output, error = _call(["project", "inspect", "-"], source)
    assert code == cli.NOT_DONE
    assert not output and "проект не прочитан" in error


def test_tampered_project_refuses_before_export(example):
    data = json.loads(example.concept().dumps())
    data["intent"] = "not the hashed intent"
    code, output, error = _call(["project", "export", "-"], json.dumps(data))
    assert code == cli.NOT_DONE
    assert not output and "integrity" in error


def test_invalid_semantic_draft_can_be_inspected_but_not_exported():
    project = ProjectRevision("draft", [ModuleDefinition("m")], [ModuleInstance(
        "i", "m", {"bad": {"op": "unknown_building_operation"}})])
    assert _call(["project", "inspect", "-"], project.dumps())[0] == cli.ANSWERED
    code, output, error = _call(["project", "export", "-"], project.dumps())
    assert code == cli.REFUSED
    assert not output and "KIR-P002" in error


def test_missing_or_non_utf8_project_is_a_read_failure(tmp_path):
    missing = tmp_path / "absent.json"
    assert _call(["project", "inspect", str(missing)])[0] == cli.NOT_DONE
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(b"\xff\xfe")
    code, output, error = _call(["project", "inspect", str(invalid)])
    assert code == cli.NOT_DONE
    assert not output and "проект не прочитан" in error
