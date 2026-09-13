"""Selected generated KIR -> actual Connector policy/compiler -> real API refs.

This optional lane does not load Revit or invoke the emitted assemblies. Legacy
PathName guard refusal is a known incompatibility, NOT an accepted live path.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from kir import compile_program
from kir.revit_connector import (ContextPrecondition, RuntimeTarget,
                                 prepare_execution, wrap_connector_source)


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "connector/revit/tests/CompilerConformance.Tests"
VERSIONS = tuple(str(year) for year in range(2021, 2027))


wrap = wrap_connector_source


def prepared(program, version, *, bulk):
    return prepare_execution(program, bulk=bulk,
        target=RuntimeTarget("835730cf-e0ba-4603-ad2b-613ae92f8dce",
                             "ca974323-cdfe-4fe6-88ac-2c16bcaa80ac", version),
        precondition=ContextPrecondition("test-native-context-not-a-live-document", 3),
        operation_id="39d6aa12-4860-4a64-b23b-59fd2e6d30a4")


@pytest.fixture(scope="module")
def conformance_runner():
    # 🔴 THIS STRIP NO LONGER STAYS SILENT ON A BOX WHERE THE ASSEMBLIES
    # EXIST. Before 07.09 the fixture required three env vars and, without
    # them, called `pytest.skip` "not configured". Meanwhile the
    # assemblies for all six versions WERE SITTING in the NuGet cache, and
    # the silence read as "the strip is clean": the env vars alone
    # immediately produced 2 reds that nobody saw. The search is now done
    # by `tools/revit_refs.py`, the env var remains FIRST in priority, and
    # a skip must name the reason and the PLACES that were searched.
    if shutil.which("dotnet") is None:
        pytest.skip(".NET SDK is unavailable; actual Connector compiler not checked")
    # 🔴 SPECIFICALLY `kir.instruments`, NOT `tools`. The boundary gate
    # calls `tests/... -> tools` the core leaking outward; that is why the
    # instrument lives in the package, and `tools/revit_refs.py` is a thin
    # CLI on top of it.
    from kir.instruments import revit_refs
    print("\n" + revit_refs.describe(VERSIONS))
    build = subprocess.run(["dotnet", "build", str(RUNNER / "CompilerConformance.Tests.csproj"),
        "--configuration", "Release", "--nologo", "-p:NuGetAudit=false"],
        text=True, capture_output=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    # Select test references from the REAL allowlist; don't create a second
    # permissive reference set that the production compiler would never admit.
    source = (ROOT / "connector/revit/src/Kir.Revit.CompilerHost/Compiler.cs").read_text()
    allowed_section = source.split("AllowedReferenceNames", 1)[1].split("public static CompilerResponse", 1)[0]
    allowed = set(re.findall(r'"([A-Za-z0-9.]+)"', allowed_section))
    assert {"mscorlib", "System.Runtime", "RevitAPI", "RevitAPIUI"} <= allowed

    def run(version, cases):
        try:
            pair, origin = revit_refs.require([version])[version]
            framework = revit_refs.framework_references(version)
        except revit_refs.ReferencesUnavailable as error:
            # The reason and the places are in the skip itself. "Not
            # configured" is not a reason.
            pytest.skip(str(error))
        references = {path.stem: path for path in framework.glob("*.dll") if path.stem in allowed}
        # net48 facade references are optional, not a replacement for mscorlib.
        for path in (framework / "Facades").glob("*.dll"):
            if path.stem in allowed and path.stem not in references:
                references[path.stem] = path
        for name in ("RevitAPI", "RevitAPIUI"):
            path = pair[name]
            assert path.is_file(), f"actual Revit reference is missing: {path} (source: {origin})"
            references[name] = path
        requests = [{"source": case, "reference_paths": [str(path) for path in references.values()]}
                    for case in cases]
        process = subprocess.run(["dotnet", str(RUNNER / "bin/Release/net8.0/CompilerConformance.Tests.dll")],
            input=json.dumps(requests), text=True, capture_output=True, timeout=120)
        assert process.returncode == 0, process.stderr
        rows = json.loads(process.stdout)
        assert len(rows) == len(cases)
        for row in rows:
            identities = row["revit_references"]
            assert set(identities) == {"RevitAPI", "RevitAPIUI"}
            assert all(int(value.split(".")[0]) == int(version) - 2000
                       for value in identities.values()), (version, identities)
        return rows
    return run


@pytest.mark.parametrize("version", VERSIONS)
def test_selected_generated_programs_and_negative_controls(version, conformance_runner):
    from examples.residential_project import concept, develop_section
    from kir.viewer.tests.test_live_scene_mesh import _VAULT

    level = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0, "name": "Ground"}]}
    concept_project = concept()
    section = develop_section(concept_project)
    programs = [level, concept_project.to_program(), section.to_program(),
        {"ops": [{"op": "create_directshape", "id": "M", "mesh": _VAULT,
                  "name": "Mesh", "category": "mass"}]}]
    cases, expectations = [], []
    for index, program in enumerate(programs):
        generated = compile_program(program, revit_version=version, bulk=True)
        if version == "2021" and index == 2:
            # The section contains floor holes: the existing backend explicitly
            # refuses these on 2021. Still exercise the remaining cases against
            # 2021 references; refusal is not a successful native compilation.
            assert not generated.ok
            assert any(item.code == "KIR-E003" for item in generated.diagnostics)
            continue
        assert generated.ok, generated.diagnostics
        artifact = prepared(generated.planned, version, bulk=generated.planned.bulk)
        assert artifact.planned.plan_digest == generated.planned.plan_digest
        cases.append(artifact.source)
        expectations.append((True, ""))
    guarded = compile_program(level, revit_version=version, bulk=True,
        expected_document={"title": "A", "path_name": "", "project_uid": "pinned-project"})
    assert guarded.ok, guarded.diagnostics
    cases.append(wrap(guarded.csharp))
    expectations.append((False, "blocked Document member: PathName"))
    # 🔴 X-2 (audit 06.09.2026) HAD NO NEGATIVE CONTROL, AND THAT WAS THE WHOLE
    # FINDING. The audit's scenario is generated code that reaches a SECOND open
    # document — `doc.Application.Documents` — opens a Transaction on it and
    # deletes there: a mutation the receipt cannot see, in a model nobody bound.
    # The mechanism against it was in `CodePolicy.cs` (an allowlist for
    # ApplicationServices members, `ValidateDocumentBinding`, and the whole
    # `Autodesk.Revit.UI` namespace closed to member access), but the four probes
    # below it exercised System.IO, Document.Close, GetType and a while-loop —
    # never a foreign document. A guard nobody shoots at is a guard nobody knows
    # is loaded. These three shapes are the audit's own, and the owner's Revit
    # really does hold a second open document (LIVE_2023_READINESS), so the risk
    # was never theoretical. Offline only, by the lead's word 13.09: this code
    # must NEVER be sent through the KUKAI bridge, whose door does not run
    # CodePolicy and would execute what it is given.
    for body, diagnostic in (
            ('return System.IO.File.ReadAllText("C:/not-executed");', "blocked namespace: System.IO"),
            ("doc.Close(false); return null;", "blocked Document member: Close"),
            ("return doc.GetType();", "runtime type discovery is not allowed"),
            ("while (true) { } return null;", "WhileStatement is not allowed"),
            ('foreach (Document __d in doc.Application.Documents) '
             '{ using (var __t = new Transaction(__d, "x")) '
             '{ __t.Start(); __d.Delete(new ElementId(1)); __t.Commit(); } } return null;',
             "Application member outside the read-only allowlist: Documents"),
            ('var __ui = uidoc.Application.ActiveUIDocument; return __ui == null ? "" : "x";',
             "blocked member of namespace Autodesk.Revit.UI: ActiveUIDocument"),
            ('var __any = new FilteredElementCollector(doc).FirstElement(); '
             'var __d = __any.Document; return __d.Title;',
             "a Document expression must be the bound `doc` parameter"),
            ("return (1 + );", "CS")):
        cases.append(wrap(body))
        expectations.append((False, diagnostic))
    cases.append(wrap("return null;").replace("namespace Kir.Generated", "namespace Wrong"))
    expectations.append((False, "wrapper type Kir.Generated.UserCode was not found"))
    rows = conformance_runner(version, cases)
    for index, (row, (ok, diagnostic)) in enumerate(zip(rows, expectations, strict=True)):
        assert row["ok"] is ok, (version, index, row)
        assert (row["assembly_bytes"] > 0) is ok, (version, index, row)
        if not ok:
            assert any(diagnostic in item for item in row["diagnostics"]), (version, index, row)


@pytest.fixture(scope="module")
def composed_plans():
    pytest.importorskip("OCP")
    from examples.residential_with_podium import workflow
    from kir.geometry_materialization import materialize_project

    revisions, bundle = workflow()
    return tuple(materialize_project(revision, {bundle.digest: bundle}).planned
                 for revision in revisions[2:])


@pytest.mark.parametrize("version", ["2023", "2026"])
def test_composed_podium_refined_and_changed_compile_under_actual_policy(
        version, conformance_runner, composed_plans):
    sources = []
    for planned in composed_plans:
        artifact = prepared(planned, version, bulk=planned.bulk)
        assert artifact.planned.plan_digest == planned.plan_digest
        sources.append(artifact.source)
    for stage, row in zip(("podium", "refined", "changed"),
                          conformance_runner(version, sources), strict=True):
        assert row["ok"] is True, (version, stage, row)
        assert row["assembly_bytes"] > 0, (version, stage, row)


@pytest.mark.parametrize("version", VERSIONS)
def test_prepared_identity_guard_passes_actual_policy_and_reference_compiler(version, conformance_runner):
    from kir.contracts import ElementIdentityProof

    program = {"ops": [{"op": "set_param", "id": "edit", "param": "Comments",
                        "target": {"by": "element_id", "value": 700}, "value": "reviewed"}]}
    artifact = prepare_execution(program,
        target=RuntimeTarget("835730cf-e0ba-4603-ad2b-613ae92f8dce",
                             "ca974323-cdfe-4fe6-88ac-2c16bcaa80ac", version),
        precondition=ContextPrecondition("synthetic-observation-context", 17),
        operation_id="39d6aa12-4860-4a64-b23b-59fd2e6d30a4",
        expected_identities=[ElementIdentityProof(700, "observed-element", "a" * 32)])
    assert "observed-element" in artifact.source
    row, = conformance_runner(version, [artifact.source])
    assert row["ok"] is True, (version, row)
    assert row["assembly_bytes"] > 0


@pytest.mark.parametrize("version", VERSIONS)
def test_uid_element_state_query_passes_actual_policy_and_reference_compiler(version, conformance_runner):
    program = {"ops": [
        {"op": "query_element_state", "id": "level", "unique_id": "original-level"},
        {"op": "query_element_state", "id": "protected", "unique_id": 'UID-Ж😀"\\opaque'},
    ]}
    artifact = prepared(program, version, bulk=False)
    row, = conformance_runner(version, [artifact.source])
    assert row["ok"] is True, (version, row)
    assert row["assembly_bytes"] > 0
