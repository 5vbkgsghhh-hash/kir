"""Long lawful parent/member identities survive macro lowering without scope capture."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from kir import macros
from kir.compiler import compile_program, plan_program
from kir.diag import KirRefusal, PARSE_DUP_ID
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, _canonical, output_id


CASES = {
    "stack": {"op": "stack", "levels": 2, "floor": [
        {"op": "create_wall", "id": "w", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]},
    "grid_array": {"op": "grid_array", "nx": 2, "ny": 2},
    "series": {"op": "series", "count": 2, "track": {"x": [[0, 0], [1, 5000]]}, "items": [
        {"op": "create_grid", "id": "g", "p0_mm": ["$x", 0], "p1_mm": ["$x", 5000]}]},
}
# Captured BEFORE this macro fix from the unchanged short-ID public compiler.
# These are not regenerated goldens; altered source bytes require review.
BASELINE = {
    "stack": ("623f0bc281d4469b53fa3904b4c1a4ee55b9df8332b322f00370e6728f88aea1", "be4430659f0b3644b215714f686b45de01057aac512b4e730f4c42613f2b8c35"),
    "grid_array": ("c1d8394467cb8e553b2dc759a94a5e4fd9f125f45c5e55847274b56e92d78f0d", "04fe35f508b5ef4958c7fa083b2f0d1d2f99188be2f9cfcb5977865a0d1593fd"),
    "series": ("22585187ff7a30ef926c8cb77d76a9214f5b3c141ba057ead6d5c154c31cd1d2", "c51b87708b1cc8ae680fdaf99f5302bbd9313fd726acbeb99680095e081bd0be"),
}
# 🔴 PIN PROVENANCE (07.09.2026, measured on `3c9ed6e`). The previous
# values (2023 `246e31af…`, 2026 `aa0c4808…`) were not produced by ANY tree
# in the history: they were introduced together with this very file in
# `878947f` and were red in that same commit. That same `878947f` added TWO
# named capabilities to the emission — a readback receipt of the source
# identity (`element_identity_readback_cs`) and a check of the assigned
# type (`type_assignment_*`, for typed ops like `create_wall`) — and the
# C# bytes for `stack` moved from `be4430…` (parent `73f9911`) to the
# values below. The year now DIFFERS: 2026 reads `ElementId.Value`, 2023 —
# `(long)ElementId.IntegerValue`.
STACK_CAPTURE_CSHARP = {
    "2023": "af1070597e4dd43c2b2aca871c784f656f591e09d70abba1c01f45400fb15cd5",
    "2026": "2dd284629bd643149f1598c56e6c645b9943eba2ad43cda85b653eb42657209e",
}
# `BASELINE[...][1]` — the bytes BEFORE that fix, and they are NOT touched:
# stripping both added capabilities below must reproduce them byte for
# byte, otherwise the fix is not "additive." The earlier version stripped
# the receipt only for `create_level` (2 ops out of 4) and did not strip
# the type check at all — the reference was unreachable, and additivity
# was checked by nothing.


def _without_type_assignment(cs, op_id, variable):
    """Strip the assigned-type check with the SAME emitters that set it."""
    from kir.emit_core import _safe, type_assignment_declarations, type_assignment_readback_cs

    readback = type_assignment_readback_cs(variable, op_id)
    if readback not in cs:
        return cs  # an op without a type: nothing to strip
    cs = cs.replace(readback, "", 1)
    cs = cs.replace(type_assignment_declarations(op_id) + "\n", "", 1)
    safe = re.escape(_safe(op_id))
    cs, removed = re.subn(
        r"        int __operationPostStart_" + safe + r" = __post\.Count;\n"
        r".*?\n        if \(__post\.Count > __operationPostStart_" + safe + r"\).*?\n\n",
        "", cs, flags=re.S)
    assert removed == 1, op_id
    return cs


def program(name, parent="s", **changes):
    op = dict(deepcopy(CASES[name]), id=parent)
    op.update(changes)
    return {"ir_version": "1.0", "intent": "macro-legacy-parity", "ops": [op]}


@pytest.mark.parametrize("schema", ["kir-authoring-project/1", "kir-authoring-project/2"])
@pytest.mark.parametrize("name", list(CASES))
def test_full_project_output_ids_plan_and_compile_with_original_source_provenance(schema, name):
    project = ProjectRevision("macro-project", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput("generated", deepcopy(CASES[name]))])], schema=schema)
    parent = output_id(project.project_id, "i", "generated")
    before = project.dumps()
    assert len(parent) == 64
    materialized = materialize_project(project, {})
    assert len(materialized.to_program()["ops"]) == 1
    assert len(materialized.planned.ops) == (2 if name == "series" else 4)
    for op in materialized.planned.ops:
        assert len(op.op_id) <= 64
        assert op.provenance.source_index == 0 and op.provenance.source_id == parent
        assert op.provenance.macro_name == name
    for year in ("2023", "2026"):
        result = compile_program(materialized.planned, revit_version=year)
        assert result.ok, [d.as_dict() for d in result.diagnostics]
        assert result.planned is materialized.planned
    assert project.dumps() == before and project.to_program()["ops"][0]["id"] == parent


def test_synthetic_level_cannot_be_captured_by_short_body_local_name():
    envelope = program("stack", levels=1, floor=[
        {"op": "create_wall", "id": "s_L1", "p0_mm": [0, 0], "p1_mm": [5000, 0]}])
    flat = macros.expand(envelope["ops"])
    assert flat[0]["id"] == "s_L1" and flat[1]["id"] == "s_L1_s_L1"
    assert flat[1]["level"] == {"by": "ref", "value": flat[0]["id"]}
    assert plan_program(envelope).ops


def test_synthetic_hashed_level_cannot_be_captured_by_body_local_name():
    parent = "a" * 64
    # Exact documented identity recipe, independent of calling the helper.
    identity = ["kir-macro-derived-id/1", "stack", parent, "level", 1, None]
    level_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    envelope = program("stack", parent, levels=1, floor=[
        {"op": "create_wall", "id": level_id, "p0_mm": [0, 0], "p1_mm": [5000, 0]}])
    flat = macros.expand(envelope["ops"])
    assert flat[0]["id"] == level_id
    assert flat[1]["id"] != level_id and flat[1]["level"]["value"] == level_id
    assert plan_program(envelope).ops


@pytest.mark.parametrize("name", list(CASES))
def test_short_valid_expansion_and_csharp_bytes_are_unchanged(name):
    from kir.emit_core import _safe, element_identity_readback_cs

    envelope = program(name)
    flat_hash = hashlib.sha256(_canonical(macros.expand(envelope["ops"])).encode()).hexdigest()
    assert flat_hash == BASELINE[name][0]
    for year in ("2023", "2026"):
        result = compile_program(envelope, revit_version=year)
        assert result.ok
        historical = result.csharp
        if name == "stack":
            assert hashlib.sha256(historical.encode()).hexdigest() == STACK_CAPTURE_CSHARP[year]
            for op in result.planned.ops:
                variable = "__el_" + _safe(op.op_id)
                reader = element_identity_readback_cs(variable, revit_version=year)
                assert historical.count(reader) == 1, op.op_id
                historical = historical.replace(reader, "")
                for caught in ('{ __rb["id"] = null; }', "{ }"):
                    historical = historical.replace(
                        f'    try {{ __rb["id"] = {variable}.Id.ToString(); }} catch {caught}\n',
                        f'    __rb["id"] = {variable}.Id.ToString();\n')
                historical = _without_type_assignment(historical, op.op_id, variable)
        assert hashlib.sha256(historical.encode()).hexdigest() == BASELINE[name][1]


@pytest.mark.parametrize("name,role,member,extra", [
    ("stack", "level", None, 3), ("stack", "member", "w", 5),
    ("grid_array", "x", None, 3), ("grid_array", "y", None, 3),
    ("series", "member", "g", 4)])
@pytest.mark.parametrize("length", [63, 64, 65])
def test_exact_legacy_length_boundary(name, role, member, extra, length):
    parent = "p" * (length - extra)
    ordinal = 0 if name == "series" else 1
    expected = (f"{parent}_L1" + ("_w" if member else "") if name == "stack" else
        f"{parent}_{role.upper()}1" if name == "grid_array" else f"{parent}_0_g")
    assert len(expected) == length
    derived = macros._derived_id(name, parent, role, ordinal, member)
    assert len(derived) <= 64
    assert derived == expected if length <= 64 else derived != expected
    assert plan_program(program(name, parent)).ops


@pytest.mark.parametrize("name", ["stack", "series"])
def test_long_members_hosts_nested_selectors_and_external_strings_share_final_map(name):
    wall_name, side_name, door_name, external_level = "w" * 64, "v" * 64, "d" * 64, "L" * 64
    wall = {"op": "create_wall", "id": wall_name, "p0_mm": [0, 0], "p1_mm": [5000, 0], "height_mm": 3000}
    side = {"op": "create_wall", "id": side_name,
        "p0_mm": {"at_element": {"by": "ref", "value": wall_name}, "point": "end"},
        "p1_mm": [5000, 5000], "height_mm": 3000}
    door = {"op": "create_door", "id": door_name, "host": {"by": "ref", "value": wall_name},
        "offset_mm": 1000, "symbol": {"by": "name", "value": wall_name}}
    if name == "stack":
        envelope = program(name, "s", floor=[wall, side, door])
    else:
        wall.update(p0_mm=["$x", 0], p1_mm=["$x", 5000], level={"by": "ref", "value": external_level})
        side.update(p1_mm=[6000, 5000], level={"by": "ref", "value": external_level})
        envelope = program(name, "s", items=[wall, side, door])
        envelope["ops"].insert(0, {"op": "create_level", "id": external_level, "elev_mm": 0})
    before = _canonical(envelope)
    flat = macros.expand(envelope["ops"])
    planned = plan_program(envelope)
    assert len(planned.ops) == len(flat)
    copies = [op for op in flat if op["op"] != "create_level"]
    for index in range(0, len(copies), 3):
        current_wall, current_side, current_door = copies[index:index+3]
        assert len(current_wall["id"]) == len(current_side["id"]) == len(current_door["id"]) == 64
        assert current_side["p0_mm"]["at_element"]["value"] == current_wall["id"]
        assert current_door["host"]["value"] == current_wall["id"]
        assert current_door["symbol"] == {"by": "name", "value": wall_name}
        assert "level" not in current_door
        if name == "series":
            assert current_wall["level"]["value"] == current_side["level"]["value"] == external_level
    assert _canonical(envelope) == before


@pytest.mark.parametrize("name", list(CASES))
def test_appending_steps_and_reordering_other_source_nodes_does_not_rename_children(name):
    envelope = program(name, "x" * 64)
    original, origins = macros.expand_with_origins(envelope["ops"])
    extended = deepcopy(envelope)
    field = {"stack": "levels", "grid_array": "nx", "series": "count"}[name]
    extended["ops"][0][field] += 1
    if name == "series": extended["ops"][0]["track"]["x"][-1] = [2, 10000]
    grown, _ = macros.expand_with_origins(extended["ops"])
    assert {op["id"] for op in original} <= {op["id"] for op in grown}
    reordered, moved_origins = macros.expand_with_origins([
        {"op": "create_level", "id": "unrelated", "elev_mm": -3000}, *envelope["ops"]])
    assert _canonical(reordered[1:]) == _canonical(original)
    assert all(origin.source_index == 1 and origin.source_id == "x" * 64 for origin in moved_origins[1:])
    assert all(origin.source_index == 0 for origin in origins)
    assert plan_program(extended).ops


def test_same_output_identity_keeps_ids_when_geometry_parameters_change():
    a = program("stack", "p" * 64)
    b = program("stack", "p" * 64, h_mm=4200, base_elev_mm=-1200,
        transform={"scale_xy_top": [.8, .9], "twist_deg_total": 15,
                   "offset_mm_top": [100, 200], "pivot_mm": [2500, 0]})
    assert [op["id"] for op in macros.expand(a["ops"])] == [op["id"] for op in macros.expand(b["ops"])]
    short = deepcopy(b); short["ops"][0]["id"] = "s"
    def numerical(value):
        if isinstance(value, dict): return {key: numerical(item) for key, item in value.items() if key not in ("id", "level")}
        if isinstance(value, list): return [numerical(item) for item in value]
        return value
    assert numerical(macros.expand(b["ops"])) == numerical(macros.expand(short["ops"]))
    assert plan_program(b).ops


def test_forced_hash_collision_uses_existing_compiler_duplicate_id_gate(monkeypatch):
    monkeypatch.setattr(macros, "_derived_id", lambda *args, **kwargs: "f" * 64)
    with pytest.raises(KirRefusal) as error:
        plan_program(program("grid_array", "p" * 64))
    assert any(d.code == PARSE_DUP_ID for d in error.value.diagnostics)


def test_explicit_authored_id_collision_is_not_silently_uniquified():
    envelope = program("grid_array", "p" * 64)
    child_id = macros.expand(envelope["ops"])[0]["id"]
    envelope["ops"].insert(0, {"op": "create_level", "id": child_id, "elev_mm": 0})
    with pytest.raises(KirRefusal) as error: plan_program(envelope)
    assert any(d.code == PARSE_DUP_ID for d in error.value.diagnostics)


def test_structured_identity_distinguishes_ambiguous_legacy_concatenation():
    # Same hypothetical legacy string, different structured origin tuple.
    parent = "p" * 60
    a = macros._derived_id("stack", parent, "member", 1, "L1_w")
    b = macros._derived_id("stack", parent + "_L1", "member", 1, "w")
    assert len(a) == len(b) == 64 and a != b


def test_fresh_process_expansion_is_byte_deterministic():
    envelope = program("stack", "p" * 64)
    expected = _canonical(macros.expand(envelope["ops"]))
    root = Path(__file__).resolve().parents[2]
    child = subprocess.run([sys.executable, "-c", "import json,sys;from kir.macros import expand;from kir.project import _canonical;print(_canonical(expand(json.load(sys.stdin)['ops'])))"],
        input=json.dumps(envelope), capture_output=True, text=True, timeout=15,
        env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == expected


@pytest.mark.parametrize("outer", ["stack", "series", "group"])
def test_id_fix_does_not_admit_nested_macros_or_groups(outer):
    nested = dict(CASES["grid_array"], id="nested")
    if outer == "stack": envelope = program("stack", "p" * 64, floor=[nested])
    elif outer == "series": envelope = program("series", "p" * 64, items=[nested])
    else: envelope = {"ops": [{"op": "create_group", "id": "g", "members": [nested], "placements": [[0, 0, 0]]}]}
    with pytest.raises(KirRefusal): plan_program(envelope)
