"""Actual type-factory create + ALL post fragments against a deliberately fake API.

No Revit assemblies or models are loaded. The stub transactions only model
rollback; this is evidence about emitted branch choice, reads and writes, not
Revit transaction behaviour, document-wide idempotency or stamp authenticity.
Existing shared types must remain read-only even when their stamp matches.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from kir.authoring import _emit_create_type, _emit_create_wall_type
from kir.compiler import compile_program
from kir.emit_core import _program_stamp
from kir.tests.fixtures import GROUND_SNAPSHOT


PROFILES = ("legacy_atomic", "legacy_per_op", "a5_atomic", "a5_per_op")
MATERIAL = "Бетон М300"


def _fragments(profile, version="2026", *, only=None):
    isolation = "per_op" if profile.endswith("per_op") else "atomic"
    scope_a = "a5:111111111111:aaaaaaaaaaaaaaaa" if profile.startswith("a5") else ""
    scope_b = "a5:111111111111:bbbbbbbbbbbbbbbb" if profile.startswith("a5") else ""
    wall = {"op": "create_wall_type", "id": "TB",
            "source_type": {"by": "element_id", "value": 4001},
            "new_name": "SharedWall", "layers": [{"width_mm": 350., "function": "Structure"}]}
    family = {"op": "create_type", "id": "FB", "category": "structural",
              "source_type": {"by": "element_id", "value": 500},
              "new_name": "SharedFamily", "width_mm": 450., "depth_mm": 500.}
    specs = {
        "WallA": ({**wall, "id": "TA", "layers": [{"width_mm": 200., "function": "Structure"}]}, scope_a),
        "WallB": (wall, scope_b),
        "FamilyB": (family, scope_b),
        "WallMaterial": ({**wall, "id": "TM", "layers": [{**wall["layers"][0], "material": MATERIAL}]}, scope_b),
        "FamilyMaterial": ({**family, "id": "FM", "material": MATERIAL}, scope_b),
    }
    fragments = {}
    for name, (op, scope) in specs.items():
        if only is not None and name not in only:
            continue
        compiled = compile_program({"ir_version": "1.0", "ops": [op]},
                                   revit_version=version, snapshot=GROUND_SNAPSHOT,
                                   stamp_scope=scope, isolation=isolation)
        assert compiled.ok, compiled.diagnostics
        stamp = _program_stamp(compiled.grounded_ops, scope)
        emitter = _emit_create_wall_type if op["op"] == "create_wall_type" else _emit_create_type
        decl, create, checks, _ = emitter(compiled.grounded_ops[0], version, stamp, isolation=isolation)
        expected_keys = ({"type_reread", "type_name", "layer_count", "layers", "layer_material", "total_width"}
                         if op["op"] == "create_wall_type" else
                         {"width", "depth"} | ({"material"} if "material" in op else set()))
        assert {check.obligation_key for check in checks} == expected_keys
        # The fragments come through the public compiler too. Indentation is
        # wrapper-dependent; no emitted logic is rewritten for this fixture.
        normalized = re.sub(r"\s+", " ", compiled.csharp)
        for fragment in (create, *(check.reader_cs + check.verdict_cs for check in checks)):
            assert re.sub(r"\s+", " ", fragment).strip() in normalized
        fragments[name] = {"decl": decl, "create": create,
                           "post": "\n".join(check.reader_cs + check.verdict_cs for check in checks),
                           "stamp": stamp + ":" + op["id"], "id": op["id"]}
    return fragments


def _render_method(name, data):
    # Create has its own scope, like per-op emission: a post reader cannot
    # accidentally see a create-local material variable in this harness.
    return (f"static Result {name}(Document doc) {{\n"
            "var __post = new List<string>(); var __t = new Transaction(doc);\ntry {\n"
            + data["decl"] + "\n{\n" + data["create"] + "\n}\n" + data["post"]
            + "\nif (__post.Count > 0) { __t.RollBack(); return new Result { Ok=false, "
              "Violations=__post.Count, Reason=string.Join(\";\", __post) }; }\n"
            + "__t.Commit(); return new Result { Ok=true, Duplicated=__dupd_" + data["id"] + " };\n"
              "} catch (Exception error) { __t.RollBack(); return new Result { Ok=false, "
              "Reason=error.GetType().Name + \":\" + error.Message }; }\n}\n")


@pytest.fixture(scope="module")
def ownership_rows(tmp_path_factory):
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK unavailable; emitted type behaviour not executed")
    root = tmp_path_factory.mktemp("type-creation-runtime")
    source = Path(__file__).with_name("type_creation_runtime.cs").read_text(encoding="utf-8")
    methods, calls = [], []
    for profile in PROFILES:
        fragments = _fragments(profile)
        methods.extend(_render_method(profile + "_" + name, data) for name, data in fragments.items())
        functions = ", ".join(profile + "_" + name for name in
                              ("WallB", "FamilyB", "WallMaterial", "FamilyMaterial"))
        stamps = ", ".join(json.dumps(fragments[name]["stamp"]) for name in
                           ("WallA", "WallB", "FamilyB", "WallMaterial", "FamilyMaterial"))
        calls.append(f"RunSuite({json.dumps(profile)}, {functions}, {stamps});")
        for version in ("2021", "2022", "2026"):
            data = fragments["FamilyB"] if version == "2026" else _fragments(
                profile, version, only={"FamilyB"})["FamilyB"]
            name = profile + "_FamilyDimensions_" + version
            methods.append(_render_method(name, data))
            calls.append(f"RunDimensions({json.dumps(profile)}, {version}, {name}, {json.dumps(data['stamp'])});")
    (root / "Generated.cs").write_text(source.replace("/* METHODS */", "\n".join(methods))
                                      .replace("/* SUITES */", "\n".join(calls)), encoding="utf-8")
    (root / "Ownership.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
        '<OutputType>Exe</OutputType><Nullable>disable</Nullable><ImplicitUsings>disable</ImplicitUsings>'
        '<UseAppHost>false</UseAppHost><UseSharedCompilation>false</UseSharedCompilation>'
        '<EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup>'
        '<ItemGroup><Compile Include="Generated.cs" /></ItemGroup></Project>', encoding="utf-8")
    (root / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>', encoding="utf-8")
    for name in ("empty.props", "empty.targets"):
        (root / name).write_text("<Project/>", encoding="utf-8")
    env = {**os.environ, "DOTNET_CLI_HOME": str(root / "cli"), "NUGET_PACKAGES": str(root / "packages"),
           "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root),
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
           "DOTNET_NOLOGO": "1", "DOTNET_CLI_USE_MSBUILD_SERVER": "0"}
    build = subprocess.run([dotnet, "build", str(root / "Ownership.csproj"), "-c", "Release", "--nologo",
                            "-p:NuGetAudit=false", f"-p:DirectoryBuildPropsPath={root / 'empty.props'}",
                            f"-p:DirectoryBuildTargetsPath={root / 'empty.targets'}"],
                           cwd=root, env=env, capture_output=True, text=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([dotnet, str(root / "bin/Release/net8.0/Ownership.dll")],
                         cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, run.stdout + run.stderr
    assert not run.stderr
    rows = json.loads(run.stdout)
    assert len(rows) == len({(row["profile"], row["name"]) for row in rows})
    assert {row["profile"] for row in rows} == set(PROFILES)
    return rows


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("group,count", [("wall_existing", 6), ("family_existing", 7),
                                         ("new_stamp", 10), ("material", 16)])
def test_type_creation_preserves_existing_ownership_and_values(ownership_rows, profile, group, count):
    rows = [row for row in ownership_rows if row["profile"] == profile and row["group"] == group]
    assert len(rows) == count
    assert all(row["pass"] for row in rows), [row for row in rows if not row["pass"]]


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("version", ["2021", "2022", "2026"])
def test_width_and_depth_require_observed_length_dimension(ownership_rows, profile, version):
    rows = [row for row in ownership_rows if row["profile"] == profile and row["group"] == "dimension_" + version]
    assert len(rows) == 32
    assert all(row["pass"] for row in rows), [row for row in rows if not row["pass"]]
