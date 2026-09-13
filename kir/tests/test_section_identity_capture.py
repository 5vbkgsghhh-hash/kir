"""Capture is observation, not proof that a reused native type was created.

SQLite Archive/2, preparation, source binding and response parsing are real.
Native rows/change manifests below are deliberately synthetic; no Revit runs.
These controls protect the existing Level-only original-publication workflow
while newly instrumented section emitters add supplementary identity fields.
"""
from copy import deepcopy

import pytest

from kir.contracts import ElementIdentityProof
from kir.compiler import compile_program
from kir.emit_core import _readback_block, _safe
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id
from kir.tests.test_revit_level_update import make_case, bind
from kir.revit_level_update import LevelUpdateRefusal


LEVEL = ("section", "level")


def type_case(tmp_path, kind, *, capture=True, duplicated=False, added=False):
    project = ProjectRevision("section-capture", [ModuleDefinition("explicit")], [
        ModuleInstance("types", "explicit", {"type": {
            "op": "create_wall_type", "host_kind": kind,
            "source_type": {"by": "element_id", "value": 100 if kind == "wall" else 400},
            "new_name": "CallerSelectedType", "layers": [{"width_mm": 200, "function": "Structure"}]}}),
        ModuleInstance("section", "explicit", {"level": {"op": "create_level", "elev_mm": 1200}}),
    ])
    case = make_case(tmp_path, project=project, required=(LEVEL,))
    oid = output_id(project.project_id, "types", "type")
    row = case["result"][oid]
    row["duplicated"] = duplicated
    if capture:
        row.update(element_identity=ElementIdentityProof(int(row["id"]), "type-original-object", "a" * 32).to_dict(),
                   element_identity_status="captured", element_identity_reason=None)
    if not added:
        case["response"]["receipt"]["changes"]["added"].remove(int(row["id"]))
    return case, row


@pytest.mark.parametrize("kind", ["wall", "floor"])
def test_optional_reused_type_capture_does_not_break_original_level_binding(tmp_path, kind):
    case, row = type_case(tmp_path, kind, capture=False)
    archived = case["path"].read_bytes()
    old = bind(case)
    assert len(old.rows) == 1 and old.rows[0]["source_op"] == "create_level"
    row.update(element_identity=ElementIdentityProof(int(row["id"]), "type-original-object", "a" * 32).to_dict(),
               element_identity_status="captured", element_identity_reason=None)
    observed = bind(case)
    assert observed.rows == old.rows
    assert observed.to_dict()["receipt_digest"] != old.to_dict()["receipt_digest"]
    assert all(item["element_identity"]["unique_id"] != "type-original-object" for item in observed.rows)
    assert case["path"].read_bytes() == archived


@pytest.mark.parametrize("kind", ["wall", "floor"])
def test_optional_new_type_capture_also_preserves_the_level_only_scope(tmp_path, kind):
    case, _ = type_case(tmp_path, kind, duplicated=True, added=True)
    observed = bind(case)
    assert len(observed.rows) == 1 and observed.rows[0]["source_op"] == "create_level"


@pytest.mark.parametrize("kind", ["wall", "floor"])
@pytest.mark.parametrize("added", [False, True])
def test_reused_type_is_never_qualified_as_originally_created(tmp_path, kind, added):
    case, _ = type_case(tmp_path, kind, duplicated=False, added=added)
    with pytest.raises(LevelUpdateRefusal):
        bind(case, required_outputs=(("types", "type"),))


@pytest.mark.parametrize("duplicated", [None, 0, 1, "false", "true"])
def test_malformed_duplicate_flag_cannot_claim_new_creation(tmp_path, duplicated):
    case, _ = type_case(tmp_path, "wall", duplicated=duplicated, added=True)
    with pytest.raises(LevelUpdateRefusal):
        bind(case)


def test_reused_added_contradiction_and_duplicate_uid_remain_global_refusals(tmp_path):
    case, row = type_case(tmp_path, "wall", added=True)
    with pytest.raises(LevelUpdateRefusal):
        bind(case)
    case["response"]["receipt"]["changes"]["added"].remove(int(row["id"]))
    level_row = case["result"][output_id(case["project"].project_id, *LEVEL)]
    row["element_identity"]["unique_id"] = level_row["element_identity"]["unique_id"]
    with pytest.raises(LevelUpdateRefusal):
        bind(case)


@pytest.mark.parametrize("kind", ["wall", "floor"])
def test_unavailable_optional_capture_preserves_old_level_readability(tmp_path, kind):
    case, row = type_case(tmp_path, kind)
    row.update(element_identity=None, element_identity_status="unavailable",
               element_identity_reason="identity_unreadable")
    before = deepcopy(case["result"])
    assert len(bind(case).rows) == 1
    assert case["result"] == before


def capture_program():
    return {"ops": [
        {"op": "create_wall_type", "id": "WT", "host_kind": "wall", "new_name": "Capture wall type",
         "source_type": {"by": "element_id", "value": 100}, "layers": [{"width_mm": 200, "function": "Structure"}]},
        {"op": "create_wall_type", "id": "FT", "host_kind": "floor", "new_name": "Capture floor type",
         "source_type": {"by": "element_id", "value": 400}, "layers": [{"width_mm": 200, "function": "Structure"}]},
        {"op": "create_level", "id": "L", "elev_mm": 1200},
        {"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [5000, 0],
         "level": {"by": "ref", "value": "L"}, "type": {"by": "ref", "value": "WT"}},
        {"op": "create_floor", "id": "F", "outline": [[0, 0], [5000, 0], [5000, 4000], [0, 4000]],
         "level": {"by": "ref", "value": "L"}, "type": {"by": "ref", "value": "FT"}},
        {"op": "create_floor_by_contour", "id": "C", "contour": {
            "outer": {"shape": "rect", "origin": [0, 0], "size_mm": [5000, 4000]}},
         "level": {"by": "ref", "value": "L"}, "type": {"by": "ref", "value": "FT"}},
        {"op": "create_room", "id": "R", "xy": [2500, 2000], "name": "Space",
         "level": {"by": "ref", "value": "L"}},
    ]}


@pytest.mark.parametrize("version", ["2021", "2022", "2023", "2024", "2025", "2026"])
@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_selected_emitters_capture_original_variables_post_commit_without_changing_duplicate_flag(version, isolation):
    built = compile_program(capture_program(), revit_version=version, isolation=isolation)
    assert built.ok, built.diagnostics
    source = built.csharp
    assert source.count('["element_identity_status"] = "captured"') == len(built.planned.ops)
    assert source.index("__t.Commit()") < source.index('["element_identity_status"]')
    for op in capture_program()["ops"]:
        name = _safe(op["id"])
        assert f"Element __kirIdentityEl = __el_{name};" in source
        if op["op"] != "create_level":
            assert f'try {{ __rb["id"] = __el_{name}.Id.ToString(); }} catch {{ }}' in source
        if op["op"] == "create_wall_type":
            assert f'__rb["duplicated"] = __dupd_{name};' in source
    assert ("__kirIdentityId.IntegerValue" in source) is (int(version) <= 2023)
    assert ("__kirIdentityId.Value" in source) is (int(version) >= 2024)


@pytest.mark.parametrize("kind", ["roof", "ceiling"])
def test_type_capture_does_not_silently_expand_to_other_factory_variants(kind):
    op = capture_program()["ops"][1]
    op.update(host_kind=kind)
    built = compile_program({"ops": [op]})
    assert built.ok, built.diagnostics
    assert '"element_identity"' not in built.csharp


def test_generic_readback_identity_extension_is_explicit_not_global():
    old = _readback_block("x", "x", "kir:example")
    assert old == _readback_block("x", "x", "kir:example", identity_version=None)
    assert "element_identity" not in old
    selected = _readback_block("x", "x", "kir:example", identity_version="2026")
    assert "Element __kirIdentityEl = __el_x;" in selected
    assert 'try { __rb["id"] = __el_x.Id.ToString(); } catch { }' in selected


@pytest.mark.parametrize("op_name", ["create_wall", "create_floor", "create_floor_by_contour", "create_room"])
def test_new_instance_capture_does_not_expand_legacy_required_scope(tmp_path, op_name):
    level_id = output_id("instance-capture", "section", "level")
    source = next(op for op in capture_program()["ops"] if op["op"] == op_name).copy()
    source.pop("id")
    source.pop("type", None)
    source["level"] = {"by": "ref", "value": level_id}
    project = ProjectRevision("instance-capture", [ModuleDefinition("explicit")], [
        ModuleInstance("section", "explicit", {"level": {"op": "create_level", "elev_mm": 1200}, "body": source})])
    case = make_case(tmp_path, project=project, required=(LEVEL,))
    oid = output_id(project.project_id, "section", "body")
    row = case["result"][oid]
    row.update(element_identity=ElementIdentityProof(int(row["id"]), "body-created-object", "a" * 32).to_dict(),
               element_identity_status="captured", element_identity_reason=None)
    assert len(bind(case).rows) == 1
    with pytest.raises(LevelUpdateRefusal, match="original_output_unsupported"):
        bind(case, required_outputs=(("section", "body"),))


def test_actual_selected_typed_section_has_complete_capture_without_changing_lineage():
    from examples import residential_project, residential_refinement, residential_typed_section
    from kir.project_selection import selected_instance_program

    source = residential_project.concept()
    section = residential_refinement.develop_section(source)
    project = residential_typed_section.add_section_types(section, source=source, expected_revision=section.revision_id,
        wall_name="Captured wall", wall_layers=[{"width_mm": 200, "function": "Structure"}],
        wall_source_type={"by": "element_id", "value": 100},
        floor_name="Captured floor", floor_layers=[{"width_mm": 200, "function": "Structure"}],
        floor_source_type={"by": "element_id", "value": 400})
    before = project.dumps()
    selected = selected_instance_program(project, "tower-a")
    assert len(selected["ops"]) == 23
    assert sum(op["op"] == "create_room" for op in selected["ops"]) == 3
    for year in ("2023", "2026"):
        built = compile_program(selected, revit_version=year)
        assert built.ok, built.diagnostics
        for op in built.planned.ops:
            assert f"Element __kirIdentityEl = __el_{_safe(op.op_id)};" in built.csharp
        assert built.csharp.count('["element_identity_status"] = "captured"') == len(selected["ops"])
    assert project.dumps() == before
