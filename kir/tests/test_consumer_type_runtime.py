"""Actual consumer creates, all posts and readbacks against a small fake API.

The fixture models straight-wall/floor geometry, not native geometry or Revit
transactions. A by:ref type is a seeded preceding output, not a reimplemented
type factory. Creates precede ALL posts as in the production emitter, including
the legal later change_type control. Actual staged render/guard helpers schedule
operation checks before the next create. For diagnostic inspection the fixture
also runs raw readbacks after a final geometry violation; it does NOT claim
those readbacks would be published by the real transaction executor.
No Autodesk assemblies/packages are used.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from kir import authoring
from kir.compiler import compile_program
from kir.emit_core import _MESH_CANON_HELPER_CS, _program_stamp
from kir.emit_model import render_staged_post
from kir.tests.fixtures import GROUND_SNAPSHOT


KINDS = ("create_wall", "create_floor", "create_floor_by_contour")
SELECTORS = ("default", "name", "element_id", "ref")
GEOMETRY_KEYS = {
    "create_wall": {"endpoints", "base_constraint", "height"},
    "create_floor": {"level_binding", "structural", "bbox", "sketch_loops"},
    "create_floor_by_contour": {"level_binding", "bbox", "sketch_loops"},
}
SCENARIOS = ("same", "wrong_same_name", "null", "invalid", "throws", "geometry_drift",
             "late_null", "late_throws", "late_wrong")


def _fragments(kind, selector, isolation, version, *, later_change=False, second_change=False):
    rectangle = [[0, 0], [6000, 0], [6000, 4000], [0, 4000]]
    op = {"op": kind, "id": "C", "level": {"by": "element_id", "value": 42}}
    if kind == "create_wall":
        op.update(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000)
    elif kind == "create_floor":
        op["outline"] = rectangle
    else:
        op["contour"] = {"outer": {"shape": "poly", "points_mm": rectangle}}
    type_id = 100 if kind == "create_wall" else 400
    type_name = "Кирпич 250" if kind == "create_wall" else "Монолит 200"
    prefix = []
    if selector == "ref":
        prefix = [{"op": "create_wall_type", "id": "T", "new_name": "Fixture authored type",
                   "host_kind": "wall" if kind == "create_wall" else "floor",
                   "source_type": {"by": "element_id", "value": type_id},
                   "layers": [{"width_mm": 200., "function": "Structure"}]}]
        op["type"] = {"by": "ref", "value": "T"}
    elif selector != "default":
        op["type"] = {"by": selector, "value": type_name if selector == "name" else type_id}
    ops = [*prefix, op]
    if later_change:
        ops.append({"op": "change_type", "id": "Swap", "target": {"by": "ref", "value": "C"},
                    "type": {"by": "element_id", "value": 101}})
    if second_change:
        assert later_change
        ops.append({"op": "change_type", "id": "Swap2", "target": {"by": "ref", "value": "C"},
                    "type": {"by": "element_id", "value": 102}})
    compiled = compile_program({"ir_version": "1.0", "ops": ops}, revit_version=version,
                               snapshot=deepcopy(GROUND_SNAPSHOT), isolation=isolation)
    assert compiled.ok, compiled.diagnostics
    stamp = _program_stamp(compiled.grounded_ops, "")
    normalized = re.sub(r"\s+", " ", compiled.csharp)
    fragments = []
    for grounded in compiled.grounded_ops:
        if grounded["id"] == "T":
            continue
        emitter = {"create_wall": authoring._emit_wall, "create_floor": authoring._emit_floor,
                   "create_floor_by_contour": authoring._emit_floor_contour,
                   "change_type": authoring._emit_change_type}[grounded["op"]]
        decl, create, checks, readback = emitter(grounded, version, stamp, isolation=isolation)
        operation_cs, final_cs = render_staged_post(grounded["id"], checks)
        guarded_create = create + authoring.operation_check_gate(grounded["id"], operation_cs, isolation)
        for fragment in (create, readback, *(check.reader_cs + check.verdict_cs for check in checks)):
            assert re.sub(r"\s+", " ", fragment).strip() in normalized
        for fragment in (guarded_create, final_cs):
            assert re.sub(r"\s+", " ", fragment).strip() in normalized
        if grounded["id"] == "C":
            assert GEOMETRY_KEYS[kind] <= {check.obligation_key for check in checks}
        fragments.append((grounded["id"], decl, guarded_create, final_cs, readback))
    # The public compiler itself must also place each operation observation
    # before later effects, not merely render a correctly labelled fragment.
    for left, right in zip(fragments, fragments[1:]):
        assert normalized.index("// operation " + left[0]) < normalized.index("// change_type " + right[0])
    return fragments


def _method(name, kind, fragments):
    declarations = "\n".join(item[1] for item in fragments)
    creates = "\n".join("{\n" + item[2] + "\n}" for item in fragments)
    posts = []
    for oid, _, _, final_cs, _ in fragments:
        count = f"__probe_count_{oid}"
        posts.append(f"int {count}=__post.Count;\n" + final_cs
                     + f"\n__checks[{json.dumps(oid + ':final')}] = __post.Skip({count}).ToArray();\n")
    readbacks = "\n".join(item[4] for item in fragments)
    type_class = "WallType" if kind == "create_wall" else "FloorType"
    return (f"static ProbeResult {name}(Document doc) {{\n"
            "var __post=new List<string>(); var __checks=new Dictionary<string,string[]>();\n"
            "var __results=new Dictionary<string,object>(); var __t=new Transaction();\n"
            + _MESH_CANON_HELPER_CS + "\n"
            + f"{type_class} __el_T=({type_class})doc.GetElement(new ElementId(700));\n"
            + declarations + "\ntry {\n" + creates + "\ndoc.Regenerate();\n"
            + "\n".join(posts) + "\ndoc.BeginFinalReadback();\n" + readbacks
            + "\nreturn new ProbeResult { Post=__post, Checks=__checks, Readback=__results };\n"
            "} catch(Exception error) { return new ProbeResult { Post=__post, Checks=__checks, Readback=__results, "
            "Failure=error.GetType().Name+\":\"+error.Message }; }\n}\n")


def _mutation_method(name, version, isolation, *, chain):
    ops = [{"op": "change_type", "id": "Swap", "target": {"by": "element_id", "value": 800},
            "type": {"by": "element_id", "value": 101}}]
    if chain:
        ops.append({"op": "change_type", "id": "Swap2", "target": {"by": "element_id", "value": 800},
                    "type": {"by": "element_id", "value": 102}})
    compiled = compile_program({"ops": ops}, revit_version=version,
                               snapshot=deepcopy(GROUND_SNAPSHOT), isolation=isolation)
    assert compiled.ok, compiled.diagnostics
    normalized = re.sub(r"\s+", " ", compiled.csharp)
    stamp = _program_stamp(compiled.grounded_ops, "")
    declarations, creates, posts, readbacks, captures, eligibility = [], [], [], [], [], []
    for op in compiled.grounded_ops:
        oid = op["id"]
        decl, create, checks, readback = authoring._emit_change_type(op, version, stamp, isolation)
        operation_cs, final_cs = render_staged_post(oid, checks)
        create += authoring.operation_check_gate(oid, operation_cs, isolation)
        if isolation == "per_op":
            decl += f"\nbool __ok_{oid} = false;"
            create = authoring._wrap_create_per_op(op, oid, create, False, {item["id"] for item in ops})
            final_cs = f"if (__ok_{oid})\n{{\n" + authoring._indent(final_cs, "    ") + "\n}"
            readback = f"if (__ok_{oid})\n{{\n" + authoring._indent(readback, "    ") + "\n}"
            eligibility.append(f'{{"{oid}", __ok_{oid}}}')
        for fragment in (decl, create, final_cs, readback):
            assert re.sub(r"\s+", " ", fragment).strip() in normalized
        declarations.append(decl)
        creates.append(create)
        posts.append(final_cs)
        readbacks.append(readback)
        captures.append(f'{{"{oid}", __assignedType_{oid} == null ? null : __assignedType_{oid}.ToString()}}')
    return (f"static ProbeResult {name}(Document doc) {{\n"
            "var __post=new List<string>(); var __results=new Dictionary<string,object>(); var __t=new Transaction();\n"
            + "\n".join(declarations) + "\ntry {\n" + "\n".join(creates)
            + "\ndoc.Regenerate();\n" + "\n".join(posts) + "\n" + "\n".join(readbacks)
            + "\nreturn new ProbeResult { Post=__post, Readback=__results, "
            + "Captured=new Dictionary<string,string>{" + ",".join(captures) + "}, "
            + "Eligibility=new Dictionary<string,bool>{" + ",".join(eligibility) + "} };\n"
            "} catch(Exception error) { return new ProbeResult { Post=__post, Readback=__results, "
            "Failure=error.GetType().Name+\":\"+error.Message }; }\n}\n")


@pytest.fixture(scope="module")
def _runtime_rows(tmp_path_factory):
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK absent; consumer fragments were not executed")
    root = tmp_path_factory.mktemp("consumer-types")
    source = Path(__file__).with_name("consumer_type_runtime.cs").read_text(encoding="utf-8")
    methods, calls = [], []
    for version in ("2023", "2026"):
        for isolation in ("atomic", "per_op"):
            for kind in KINDS:
                for selector in SELECTORS:
                    name = f"Run_{version}_{isolation}_{kind}_{selector}"
                    fragments = _fragments(kind, selector, isolation, version)
                    methods.append(_method(name, kind, fragments))
                    calls.append(f"Probe({name}, {json.dumps(version)}, {json.dumps(isolation)}, "
                                 f"{json.dumps(kind)}, {json.dumps(selector)}, false);")
            name = f"Run_{version}_{isolation}_later_change"
            methods.append(_method(name, "create_wall", _fragments("create_wall", "element_id", isolation, version,
                                                                    later_change=True)))
            calls.append(f"Probe({name}, {json.dumps(version)}, {json.dumps(isolation)}, \"create_wall\", \"element_id\", true);")
            name += "_twice"
            methods.append(_method(name, "create_wall", _fragments("create_wall", "element_id", isolation, version,
                                                                    later_change=True, second_change=True)))
            calls.append(f"Probe({name}, {json.dumps(version)}, {json.dumps(isolation)}, \"create_wall\", \"element_id\", true, 2);")
            name = f"Run_{version}_{isolation}_standalone_mutation"
            methods.append(_mutation_method(name, version, isolation, chain=False))
            calls.append(f"ProbeMutation({name}, {json.dumps(version)}, {json.dumps(isolation)}, false);")
        name = f"Run_{version}_per_op_mutation_chain"
        methods.append(_mutation_method(name, version, "per_op", chain=True))
        calls.append(f"ProbeMutation({name}, {json.dumps(version)}, \"per_op\", true);")
    (root / "Generated.cs").write_text(source.replace("/* METHODS */", "\n".join(methods))
                                      .replace("/* CALLS */", "\n".join(calls)), encoding="utf-8")
    (root / "Probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
        '<OutputType>Exe</OutputType><Nullable>disable</Nullable><ImplicitUsings>disable</ImplicitUsings>'
        '<UseAppHost>false</UseAppHost><UseSharedCompilation>false</UseSharedCompilation>'
        '<EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup>'
        '<ItemGroup><Compile Include="Generated.cs" /></ItemGroup></Project>', encoding="utf-8")
    (root / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>', encoding="utf-8")
    for name in ("empty.props", "empty.targets"):
        (root / name).write_text("<Project/>", encoding="utf-8")
    env = {**os.environ, "DOTNET_CLI_HOME": str(root / "cli"), "NUGET_PACKAGES": str(root / "packages"),
           "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root), "DOTNET_NOLOGO": "1",
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
           "DOTNET_CLI_USE_MSBUILD_SERVER": "0"}
    build = subprocess.run([dotnet, "build", str(root / "Probe.csproj"), "-c", "Release", "--nologo",
                            "-p:NuGetAudit=false", f"-p:DirectoryBuildPropsPath={root / 'empty.props'}",
                            f"-p:DirectoryBuildTargetsPath={root / 'empty.targets'}"],
                           cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([dotnet, str(root / "bin/Release/net8.0/Probe.dll")], cwd=root, env=env,
                         capture_output=True, text=True, timeout=30)
    assert run.returncode == 0 and not run.stderr, run.stdout + run.stderr
    rows = json.loads(run.stdout)
    assert len(rows) == 2 * 2 * (3 * 4 * len(SCENARIOS) + 2 * 4) + 2 * 2 * 7 + 2 * 5
    return rows


@pytest.fixture(scope="module")
def consumer_rows(_runtime_rows):
    rows = [row for row in _runtime_rows if row["kind"] in KINDS]
    assert len(rows) == 2 * 2 * (3 * 4 * len(SCENARIOS) + 2 * 4)
    return rows


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("selector", SELECTORS)
def test_wrong_or_unreadable_native_type_cannot_be_hidden_by_matching_geometry(consumer_rows, kind, selector):
    rows = [row for row in consumer_rows if row["kind"] == kind and row["selector"] == selector and not row["laterChange"]]
    assert len(rows) == 4 * len(SCENARIOS)
    for row in rows:
        result = row["result"]
        assert row["requestedType"] == (700 if selector == "ref" else 100 if kind == "create_wall" else 400), row
        assert row["defaultLookups"] == (1 if selector == "default" else 0), row
        if row["scenario"] in ("wrong_same_name", "null", "invalid", "throws"):
            # These same geometry fixtures passed all original posts in the
            # saved pre-fix runtime. Now the actual operation guard refuses
            # before final posts/readbacks, even under per_op/report mode.
            assert result["Failure"] and "type assignment mismatch or unavailable (operation)" in result["Failure"], row
            assert "C" not in result["Readback"], row
            continue
        assert result["Failure"] is None, row
        if row["scenario"] == "geometry_drift":
            assert result["Checks"]["C:final"], row
        else:
            assert result["Post"] == [], row
        readback = result["Readback"]["C"]
        assert readback["element_identity_status"] == "captured" and readback["element_identity_reason"] is None, row
        assert readback["element_identity"] == {"schema_version": "revit-element-identity/1",
            "element_id": int(readback["id"]), "unique_id": "fixture-element-" + readback["id"],
            "version_guid": "abcde123456789abcdef0123456789ab"}, row
        expected = str(row["requestedType"])
        assert readback["type_assignment"] == {"scope": "operation_end_before_commit",
            "requested_type_id": expected, "observed_type_id": expected}, row
        if row["scenario"] in ("late_null", "late_throws"):
            assert readback["type_id"] is None and readback["type_id_status"] == "unavailable", row
            assert readback["type_id_reason"] == ("type_id_missing" if row["scenario"] == "late_null"
                                                   else "type_id_unreadable"), row
        else:
            assert readback["type_id"] == ("999" if row["scenario"] == "late_wrong" else expected), row
            assert readback["type_id_status"] == "captured" and readback["type_id_reason"] is None, row


def test_explicit_later_change_type_remains_a_legal_positive_control(consumer_rows):
    rows = [row for row in consumer_rows if row["laterChange"] and row["expectedChanges"] == 1 and row["scenario"] == "same"]
    assert len(rows) == 4
    for row in rows:
        assert row["result"]["Failure"] is None and row["result"]["Post"] == [], row
        assert row["result"]["Readback"]["Swap"]["type_id"] == "101"
        assert row["result"]["Readback"]["C"]["type_assignment"]["observed_type_id"] == "100"
        assert row["result"]["Readback"]["C"]["type_id"] == "101"
        assert row["changeCalls"] == 1


def test_two_explicit_type_changes_do_not_assert_the_first_type_is_held_forever(consumer_rows):
    rows = [row for row in consumer_rows if row["laterChange"] and row["expectedChanges"] == 2 and row["scenario"] == "same"]
    assert len(rows) == 4
    for row in rows:
        assert row["result"]["Failure"] is None and row["result"]["Post"] == [], row
        assert row["result"]["Readback"]["Swap2"]["type_id"] == "102"
        for oid, expected in (("C", "100"), ("Swap", "101"), ("Swap2", "102")):
            readback = row["result"]["Readback"][oid]
            assert readback["type_assignment"] == {"scope": "operation_end_before_commit",
                "requested_type_id": expected, "observed_type_id": expected}
            assert readback["type_id"] == "102" and readback["type_id_status"] == "captured"
        assert row["changeCalls"] == 2


def test_failed_creation_assignment_stops_before_later_type_changes(consumer_rows):
    rows = [row for row in consumer_rows if row["laterChange"] and row["scenario"] != "same"]
    assert len(rows) == 24
    for row in rows:
        assert row["result"]["Failure"] and "type assignment mismatch or unavailable (operation)" in row["result"]["Failure"], row
        assert row["changeCalls"] == 0, row
        assert not row["result"]["Readback"], row


def test_standalone_type_change_observes_replacement_and_refuses_bad_assignments(_runtime_rows):
    rows = [row for row in _runtime_rows if row["kind"] == "mutation" and not row["chain"]]
    assert len(rows) == 28
    for row in rows:
        result = row["result"]
        assert row["changeCalls"] == 1, row
        if row["scenario"] in ("normal", "replacement"):
            assert result["Failure"] is None and result["Post"] == [], row
            receipt = result["Readback"]["Swap"]
            assert receipt["id"] == ("900" if row["scenario"] == "replacement" else "800"), row
            assert receipt["new_element_created"] is (row["scenario"] == "replacement"), row
            assert receipt["type_assignment"] == {"scope": "operation_end_before_commit",
                "requested_type_id": "101", "observed_type_id": "101"}, row
            assert receipt["type_id"] == "101" and receipt["type_id_status"] == "captured", row
            if row["scenario"] == "replacement":
                assert row["typeReadIds"] and set(row["typeReadIds"]) == {900}, row
        elif row["isolation"] == "atomic":
            assert result["Failure"] and not result["Readback"], row
        else:
            assert result["Failure"] is None and result["Eligibility"] == {"Swap": False}, row
            receipt = result["Readback"]["Swap"]
            assert "refused" in receipt and not {"id", "type_id", "type_assignment"} & receipt.keys(), row
            assert row["subCommits"] == 0 and row["rollbackCalls"] == 1, row
            assert row["state"] == {"800": "100"}, row  # explicitly STUB checkpoint restoration


@pytest.mark.parametrize("scenario", ["normal", "second_no_op", "second_throw", "second_commit_rollback", "second_commit_throw"])
def test_actual_per_op_wrapper_suppresses_failed_second_capture(_runtime_rows, scenario):
    rows = [row for row in _runtime_rows if row["kind"] == "mutation" and row["chain"] and row["scenario"] == scenario]
    assert len(rows) == 2
    for row in rows:
        result = row["result"]
        assert result["Failure"] is None and row["changeCalls"] == 2, row
        assert row["subStarts"] == row["subDisposals"] == 2, row
        first = result["Readback"]["Swap"]
        assert result["Eligibility"]["Swap"] is True
        assert first["type_assignment"]["requested_type_id"] == first["type_assignment"]["observed_type_id"] == "101"
        if scenario == "normal":
            assert result["Eligibility"] == {"Swap": True, "Swap2": True}
            assert result["Post"] == [] and row["state"] == {"800": "102"}
            assert first["type_id"] == "102" and result["Readback"]["Swap2"]["type_id"] == "102"
        else:
            assert result["Eligibility"]["Swap2"] is False
            second = result["Readback"]["Swap2"]
            assert "refused" in second and not {"id", "type_id", "type_assignment"} & second.keys(), row
            if scenario == "second_commit_throw":
                assert second.get("internal") is True and "refused_op_id" not in second, row
            else:
                assert second.get("refused_op_id") == "Swap2" and "internal" not in second, row
            assert row["state"] == {"800": "101"} and first["type_id"] == "101", row
            if scenario.startswith("second_commit"):
                # Ordinary C# capture remains 102 even though the modelled
                # transaction rolled back. Only actual __ok gates keep it out
                # of the public receipt; clearing locals would hide this bug.
                assert result["Captured"]["Swap2"] == "102", row
                assert row["subCommits"] == 2, row
            else:
                assert row["subCommits"] == 1, row
            if scenario == "second_throw":
                assert row["mutationEffects"] == 2 and row["rollbackCalls"] == 1, row
