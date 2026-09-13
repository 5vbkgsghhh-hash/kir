"""Generated type factories through actual Connector policy and 2021–2026 refs.

Opt in with KIR_TYPE_CONFORMANCE_RUNNER pointing to a freshly built local
CompilerConformance.Tests.dll. This lane never restores packages, builds into
the source tree, loads a Revit assembly, or executes generated model code.
The C# runner reads reference assembly identity metadata and emits only in RAM.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from kir import compile_program
from kir.revit_connector import wrap_connector_source
from kir.tests.fixtures import GROUND_SNAPSHOT


ROOT = Path(__file__).resolve().parents[2]
VERSIONS = tuple(str(year) for year in range(2021, 2027))


@pytest.fixture(scope="module")
def type_conformance_runner():
    configured = os.environ.get("KIR_TYPE_CONFORMANCE_RUNNER")
    if not configured:
        pytest.skip("actual type compile lane requires explicit KIR_TYPE_CONFORMANCE_RUNNER DLL")
    runner = Path(configured)
    assert runner.is_absolute() and runner.is_file() and runner.suffix == ".dll", configured
    dotnet = shutil.which("dotnet")
    assert dotnet is not None, "configured type compiler runner requires the .NET host"
    cache = Path(os.environ.get("KIR_TYPE_REVIT_API_CACHE", "/root/.nuget/packages/revit_all_main_versions_api_x64"))
    net48 = Path(os.environ.get("KIR_TEST_NET48_REFS", "/root/.nuget/packages/microsoft.netframework.referenceassemblies.net48/1.0.3/build/.NETFramework/v4.8"))
    net8 = Path(os.environ.get("KIR_TEST_NET8_REFS", "/usr/share/dotnet/packs/Microsoft.NETCore.App.Ref/8.0.29/ref/net8.0"))
    for path in (cache, net48, net8):
        assert path.is_dir(), f"configured reference directory missing: {path}"
    compiler = (ROOT / "connector/revit/src/Kir.Revit.CompilerHost/Compiler.cs").read_text(encoding="utf-8")
    section = compiler.split("AllowedReferenceNames", 1)[1].split("public static CompilerResponse", 1)[0]
    allowed = set(re.findall(r'"([A-Za-z0-9.]+)"', section))
    assert {"mscorlib", "System.Runtime", "RevitAPI", "RevitAPIUI"} <= allowed

    def run(version, sources):
        legacy = int(version) <= 2024
        framework = net48 if legacy else net8
        references = {path.stem: path for path in framework.glob("*.dll") if path.stem in allowed}
        for path in (framework / "Facades").glob("*.dll"):
            if path.stem in allowed:
                references.setdefault(path.stem, path)
        api_dir = cache / (version + ".0.0") / "lib" / ("net48" if legacy else "net8.0")
        for name in ("RevitAPI", "RevitAPIUI"):
            path = api_dir / (name + ".dll")
            assert path.is_file(), f"actual API reference missing: {path}"
            references[name] = path
        requests = [{"source": source, "reference_paths": [str(references[name]) for name in sorted(references)]}
                    for source in sources]
        result = subprocess.run([dotnet, str(runner)], input=json.dumps(requests),
            text=True, capture_output=True, timeout=120, cwd=ROOT)
        assert result.returncode == 0, result.stdout + result.stderr
        rows = json.loads(result.stdout)
        assert len(rows) == len(sources)
        for row in rows:
            assert set(row["revit_references"]) == {"RevitAPI", "RevitAPIUI"}
            assert all(int(value.split(".")[0]) == int(version) - 2000
                       for value in row["revit_references"].values()), (version, row)
        return rows
    return run


def programs():
    for kind, pool in (("wall", "wall_types"), ("floor", "floor_types"),
                       ("roof", "roof_types"), ("ceiling", "ceiling_types")):
        yield kind, {"ops": [{"op": "create_wall_type", "id": "type-" + kind, "host_kind": kind,
            "source_type": {"by": "element_id", "value": GROUND_SNAPSHOT[pool][0]["id"]},
            "new_name": "KIR exact owned " + kind,
            "layers": [{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                       {"width_mm": 20, "function": "Finish1"}]}]}
    for category in ("structural", "architectural"):
        yield "family-" + category, {"ops": [{"op": "create_type", "id": "type-" + category,
            "category": category,
            "source_type": {"by": "element_id", "value": GROUND_SNAPSHOT["column_symbols_" + category][0]["id"]},
            "new_name": "KIR exact owned " + category, "width_mm": 400, "depth_mm": 500,
            "param_width_name": "b", "param_depth_name": "h", "material": "Бетон М300"}]}


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_type_factories_compile_with_real_policy_and_all_api_versions(version, isolation, type_conformance_runner):
    cases = list(programs())
    sources = []
    for name, program in cases:
        result = compile_program(program, revit_version=version, snapshot=GROUND_SNAPSHOT,
                                 isolation=isolation)
        assert result.ok, (name, version, isolation, result.diagnostics)
        # Ensure this is the changed factory path, not a source-less policy probe.
        assert "StringComparison.Ordinal" in result.csharp
        assert "ALL_MODEL_TYPE_COMMENTS" in result.csharp
        assert "Type ownership stamp" in result.csharp
        sources.append(wrap_connector_source(result.csharp))
    failures = [(name, row) for (name, _), row in zip(cases, type_conformance_runner(version, sources), strict=True)
                if row["ok"] is not True or row["assembly_bytes"] <= 0]
    assert not failures, (version, isolation, failures)


@pytest.mark.parametrize("version", VERSIONS)
def test_actual_policy_and_compiler_reject_negative_controls(version, type_conformance_runner):
    sources = [wrap_connector_source("return doc.GetType();"), wrap_connector_source("return (1 + );")]
    rows = type_conformance_runner(version, sources)
    for row, expected in zip(rows, ("runtime type discovery is not allowed", "CS"), strict=True):
        assert row["ok"] is False and row["assembly_bytes"] == 0, (version, row)
        assert any(expected in message for message in row["diagnostics"]), (version, row)
