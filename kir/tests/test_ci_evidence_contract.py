"""Ratchets for commit-bound KIR CI evidence and branch coverage."""
from __future__ import annotations

import importlib.util
import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from types import SimpleNamespace
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


#: 🔴 REPOSITORY ROOT — FROM THE PACKAGE'S LOCATION (2026-08-28). This used to be
#: `parents[4]`: before the split, counted from `backend/kukai/ir/tests/x.py`, that was
#: the product repository root. After 08.27 the same count from `kir/kir/tests/x.py` gives
#: the FILESYSTEM ROOT, and all five checks failed with
#: `FileNotFoundError: '/.github/...'` — a refusal about US, in the voice of a CI assertion.
#: The `.github` directory sat in place the whole time, in `/opt/kir`.
ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kir-evidence.yml"
MANIFEST = ROOT / ".github/scripts/kir_evidence_manifest.py"
SECRET_BOUNDARY = ROOT / ".github/scripts/kir_secret_boundary.py"
SECURITY_WORKFLOW = ROOT / ".github/workflows/kir-security.yml"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(
        name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest_module():
    return _load_module(MANIFEST, "kir_evidence_manifest_contract")


def _secret_boundary_module():
    return _load_module(SECRET_BOUNDARY, "kir_secret_boundary_contract")


def test_evidence_runs_for_the_standalone_public_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main]" in text
    assert "prod-live" not in text


def test_every_file_in_the_evidence_digest_triggers_both_events():
    text = WORKFLOW.read_text(encoding="utf-8")
    manifest = _manifest_module()
    for prefix in manifest.SOURCE_PREFIXES:
        assert text.count(f"- '{prefix}**'") == 2, prefix
    for path in sorted(manifest.SOURCE_FILES):
        assert text.count(f"- '{path}'") == 2, path


def test_secret_boundary_owns_and_triggers_for_the_same_source_set():
    text = SECURITY_WORKFLOW.read_text(encoding="utf-8")
    manifest = _manifest_module()
    boundary = _secret_boundary_module()
    for prefix in manifest.SOURCE_PREFIXES:
        assert prefix in boundary.KIR_PREFIXES
        assert text.count(f"- '{prefix}**'") == 2, prefix
    for raw_path in sorted(manifest.SOURCE_FILES):
        path = Path(raw_path)
        assert boundary.is_kir_owned(path), path
        assert text.count(f"- '{raw_path}'") == 2, raw_path
    for path in boundary.FORBIDDEN_TRACKED_PATHS:
        assert text.count(f"- '{path.as_posix()}'") == 2, path


def test_secret_boundary_rules_detect_each_supported_credential_family():
    boundary = _secret_boundary_module()
    samples = {
        "private-key": b"-----BEGIN " + b"PRIVATE KEY-----",
        "aws-access-key": b"AKIA" + b"A" * 16,
        "google-api-key": b"AIza" + b"A" * 32,
        "github-token": b"ghp_" + b"A" * 36,
        "provider-api-key": b"sk-" + b"A" * 32,
        "telegram-bot-token": b"123456789:" + b"A" * 32,
    }
    assert {name for name, _pattern in boundary.CONTENT_RULES} == set(samples)
    for name, pattern in boundary.CONTENT_RULES:
        assert pattern.search(samples[name]), name


def test_provenance_job_depends_on_both_proof_jobs_and_uses_commit_sha():
    text = WORKFLOW.read_text(encoding="utf-8")
    job = _job("provenance")
    needs = re.search(r"needs: \[([^]]+)\]", job)
    assert needs is not None
    assert {name.strip() for name in needs[1].split(",")} == {
        "workflow", "lint", "offline", "generated-csharp-6x", "connector", "release-gate", "windows-wheel"}
    assert "\n    if:" not in job, "provenance must require success of every dependency"
    assert "kir-evidence-${{ github.sha }}-${{ github.run_attempt }}" in text
    manifest = _manifest_module()
    assert manifest.SCHEMA == "kukai.kir.ci-evidence/1"


#: 🔴 13.09.2026. A check stood here that the `frontend` job built the standalone
#: viewer and compared it, file by file, with the copy packaged in the wheel. The
#: browser window was removed by the owner's word together with
#: `frontend/standalone/**` and `kir/app/viewer/dist/**`; there is no second copy
#: to compare and no bundle to build, so the job and this check went with it.


def _job(name):
    text = WORKFLOW.read_text(encoding="utf-8")
    result = re.search(r"^  " + re.escape(name) + r":\n(.*?)(?=^  [a-z][\w-]*:\n|\Z)",
                       text, re.M | re.S)
    assert result is not None, name
    return result[1]


def _job_level_env_lines() -> list[tuple[str, str]]:
    """Every mapping line written under a JOB-level `env:`, as (job, line).

    Hand-parsed for the same reason as `_job` above: a YAML loader would accept
    the file that GitHub rejects, so the check reads the bytes that are sent.
    """
    pairs: list[tuple[str, str]] = []
    job: str | None = None
    in_jobs = False
    in_env = False
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if not in_jobs:
            continue
        if re.fullmatch(r"  [a-z][\w-]*:", line):
            job, in_env = line.strip().rstrip(":"), False
            continue
        if job is None or not line.strip() or line.lstrip().startswith("#"):
            continue
        if line == "    env:":
            in_env = True
            continue
        if not line.startswith("      "):
            in_env = False
            continue
        if in_env:
            pairs.append((job, line))
    return pairs


def _suite_module():
    return _load_module(ROOT / ".github/scripts/kir_ci_suites.py", "kir_ci_suites_contract")


def test_required_offline_lanes_partition_collected_items_without_losing_any():
    module = _suite_module()
    paths = ["kir/tests/test_alpha.py", "kir/tests/test_beta.py",
             "kir/decompile/tests/test_reverse.py", "kir/decompile/tests/test_materialize.py",
             "kir/app/tests/test_editor.py", "kir/future/tests/new_test.py"]
    # Parametrized cases share a file, but each distinct collected item survives.
    items = [SimpleNamespace(path=ROOT / path) for path in paths for _ in range(3)]
    selected = []
    for lane in module.LANES:
        candidate = list(items)
        removed = []
        config = SimpleNamespace(hook=SimpleNamespace(
            pytest_deselected=lambda items: removed.extend(items)))
        selector = module.LaneSelection(lane)
        selector.pytest_collection_modifyitems(config, candidate)
        assert len(candidate) + len(removed) == len(items)
        assert not {id(item) for item in candidate} & {id(item) for item in removed}
        assert selector.selected == len(candidate)
        selected.extend(candidate)
    assert len(selected) == len(items)
    assert {id(item) for item in selected} == {id(item) for item in items}
    assert module.lane_for(paths[3]) == "materialize"
    assert module.lane_for(paths[-1]) == "product", "new product suites cannot fall out of CI"
    with pytest.raises(ValueError):
        module.lane_for("../foreign/test_case.py")
    with pytest.raises(ValueError):
        module.LaneSelection("nonexistent")


def test_a_lane_does_not_import_another_lanes_test_modules(tmp_path):
    """File selection precedes collection, so deselected import effects cannot leak."""
    module = _suite_module()
    product = tmp_path / "kir/app/tests/test_product.py"
    product.parent.mkdir(parents=True)
    product.write_text("def test_product():\n    assert True\n", encoding="utf-8")
    foreign = tmp_path / "kir/tests/test_foreign.py"
    foreign.parent.mkdir(parents=True)
    foreign.write_text(
        "raise RuntimeError('a foreign lane was imported')\n",
        encoding="utf-8")

    selected = module.paths_for_lane("product", tmp_path)
    assert selected == (product,)
    assert module.main(["product"], root=tmp_path) == 0


def test_offline_workflow_requires_every_lane_and_does_not_soften_failures():
    module = _suite_module()
    job = _job("offline")
    lanes = re.search(r"lane: \[([^]]+)\]", job)
    assert lanes is not None
    assert tuple(name.strip() for name in lanes[1].split(",")) == module.LANES
    assert ".github/scripts/kir_ci_suites.py" in job
    assert "gate_manifest.json" not in job
    assert "timeout-minutes: 240" in job
    assert "fail-fast: false" in job
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "continue-on-error:" not in text


def test_shard_executes_actual_cases_and_empty_lane_cannot_turn_green(tmp_path):
    suite = _suite_module()
    target = tmp_path / "kir/tests/test_chosen.py"
    target.parent.mkdir(parents=True)
    target.write_text("def test_runs():\n    assert True\n\ndef test_refutes():\n    assert False\n",
                      encoding="utf-8")
    other = tmp_path / "kir/new_product/tests/test_other.py"
    other.parent.mkdir(parents=True)
    other.write_text("def test_not_in_this_lane():\n    assert False\n", encoding="utf-8")
    selected_lane = suite.lane_for("kir/tests/test_chosen.py")
    helper = ROOT / ".github/scripts/kir_ci_suites.py"
    prefix = (
        "import importlib.util, pathlib, pytest; "
        f"s=importlib.util.spec_from_file_location('ci_lanes', {str(helper)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
    )
    for lane, expected in ((selected_lane, 1), ("materialize", 5)):
        code = prefix + (
            f"raise SystemExit(pytest.main(['-q', '-c', {os.devnull!r}, '-p', 'no:cacheprovider', "
            f"'--confcutdir={tmp_path}', {str(tmp_path / 'kir')!r}], "
            f"plugins=[m.LaneSelection({lane!r}, pathlib.Path({str(tmp_path)!r}))]))"
        )
        run = subprocess.run([sys.executable, "-c", code], cwd=tmp_path,
                             capture_output=True, text=True, timeout=30)
        assert run.returncode == expected, run.stdout + run.stderr
        if expected == 1:
            assert "1 failed, 1 passed, 1 deselected" in run.stdout
        else:
            assert "3 deselected" in run.stdout


def test_reference_lane_declares_all_six_exact_versions_and_executes_drivers():
    from kir import spec
    project = ET.parse(ROOT / ".github/scripts/Kir.CI.References.csproj")
    downloads = {row.attrib["Include"]: row.attrib["Version"]
                 for row in project.iter("PackageDownload")}
    assert downloads["Revit_All_Main_Versions_API_x64"].split(";") == [
        f"[{version}.0.0]" for version in spec.REVIT_VERSIONS]
    job = _job("generated-csharp-6x")
    assert "dotnet build connector/revit/tests/CompilerConformance.Tests/CompilerConformance.Tests.csproj" in job
    assert "revit_refs.require(versions)" in job
    assert '"KIR_TYPE_CONFORMANCE_RUNNER": runner' in job
    for name in ("test_connector_compiler_conformance.py", "test_type_creation_conformance.py",
                 "test_consumer_type_conformance.py", "test_typed_section_conformance.py",
                 "test_an_opening_is_judged_against_the_profile_before_any_effect.py"):
        assert (ROOT / "kir/tests" / name).is_file()
        assert f"kir/tests/{name}" in job
    assert 'assert cases, "no actual compiler tests ran"' in job
    assert 'assert not list(result.iter("skipped"))' in job


def test_connector_console_and_packaging_checks_are_actually_executed():
    job = _job("connector")
    assert 'mkdir -p "$RUNNER_TEMP/kir-connector-tests"' in job
    assert 'KIR_TEST_ARTIFACT_ROOT=$RUNNER_TEMP/kir-connector-tests' in job
    for project in ("ContextLifecycle.Tests", "CompilerHostLifecycle.Tests"):
        assert f"dotnet run --project connector/revit/tests/{project}/{project}.csproj" in job
    for script in ("Run.ps1", "Install.Tests.ps1", "Space.Tests.ps1"):
        assert f"pwsh -NoLogo -NoProfile -File connector/revit/tests/Packaging.Tests/{script}" in job
    for driver in ("test_revit_transport.py", "test_connector_protocol_replay.py", "test_native_no_start_failure.py"):
        assert f"kir/tests/{driver}" in job
    assert "dotnet test " not in "\n".join(line for line in job.splitlines() if not line.lstrip().startswith("#"))


def test_workflow_context_validation_uses_the_pinned_upstream_validator():
    job = _job("workflow")
    assert "rhysd/actionlint/releases/download/v1.7.12/" in job
    assert "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8" in job
    assert '"$RUNNER_TEMP/actionlint" -shellcheck= -pyflakes= .github/workflows/*.yml' in job


def test_no_job_level_env_uses_the_runner_context():
    """🔴 THE FILE WAS INVALID, AND THE PRICE WAS 16 RUNS OUT OF 16.

    GitHub Actions exposes in `jobs.<id>.env` only `github`, `needs`, `strategy`,
    `matrix`, `vars`, `secrets`, `inputs` — NOT `runner`. A job-level
    `NUGET_PACKAGES: ${{ runner.temp }}/…` in `generated-csharp-6x` (added
    07.08.2026) made the WHOLE workflow fail validation: every run since 08.09
    ended `failure` with ZERO jobs started, so no job's `continue-on-error` could
    soften it and `offline` never ran. `runner` is legal inside a step, and that is
    where the value lives now. Actionlint in the `workflow` job would also catch
    this, but only once a run starts; this guard stands in the offline suite that
    runs before anything is pushed.
    """
    pairs = _job_level_env_lines()
    assert pairs, ("ни одной job-level `env:` не найдено — разбор ничего не "
                   "видит, и утверждение было бы пустым")
    guilty = [(job, line.strip()) for job, line in pairs if "runner." in line]
    assert not guilty, (
        f"контекст `runner` на уровне job — файл не пройдёт валидацию: {guilty}")


@pytest.mark.parametrize("name, class_name", [
    ("test_materialize", "TMatReal"), ("test_native_group", "RealBuilding")])
def test_optional_real_corpus_is_a_named_class_skip_not_a_collection_failure(monkeypatch, name, class_name):
    import importlib
    import pickle
    import unittest
    module = importlib.import_module("kir.decompile.tests." + name)
    real_case = getattr(module, class_name)
    for kind in (FileNotFoundError, PermissionError):
        def unavailable(kind=kind):
            raise kind("synthetic unavailable corpus")
        monkeypatch.setattr(module, "_LOT31_TREE", SimpleNamespace(read_bytes=unavailable))
        with pytest.raises(unittest.SkipTest, match=kind.__name__):
            real_case.setUpClass()
    monkeypatch.setattr(module, "_LOT31_TREE", SimpleNamespace(read_bytes=lambda: b"invalid pickle"))
    with pytest.raises(pickle.UnpicklingError):
        real_case.setUpClass()


def test_lint_is_narrow_and_recipe_names_do_not_become_global_python_builtins():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["ruff"]
    assert config["target-version"] == "py312"
    assert set(config["lint"]["select"]) == {"F82", "E9", "F63", "F7"}
    assert not config.get("builtins"), "recipe names are not defined in ordinary Python modules"
    assert config["lint"]["per-file-ignores"] == {"kir/coverage_feed.py": ["F821"]}
    job = _job("lint")
    assert 'builtins=["param", "project_output_id"]' in job
    assert "--config 'extend-exclude=[]'" in job
    assert "examples/recipes" in job
    assert "ruff format" not in job and "--fix" not in job


def test_windows_profile_is_an_installed_slice_not_a_checkout_or_claimed_full_selftest():
    job = _job("windows-wheel")
    assert "runs-on: windows-latest" in job
    assert "python -m build --outdir" in job
    assert "python -m build --wheel" not in job
    assert "python -m venv $venv" in job
    assert "if (Test-Path -LiteralPath $venv)" in job
    assert job.index("if (Test-Path -LiteralPath $venv)") < job.index("python -m venv $venv")
    assert "PYTHONUTF8: '1'" in job
    assert 'pip install "$($wheels[0].FullName)[dev]"' in job
    assert "pip install -e" not in job
    assert "Set-Location $env:RUNNER_TEMP" in job
    assert 'assert not root.is_relative_to(checkout)' in job
    assert "-m kir.selftest --list" in job
    assert '"full_selftest": False' in job
    match = re.search(r"names = (\[.*?\])", job, re.S)
    assert match is not None
    names = ast.literal_eval(match[1])
    manifest = json.loads((ROOT / "kir/gate_manifest.json").read_text(encoding="utf-8"))["набор"]
    assert len(names) == len(set(names)) == 8
    assert set(names) < set(manifest)
    assert "tests/test_a_reading_typo_does_not_erase_the_program.py" not in names
    assert all((ROOT / "kir" / name).is_file() for name in names)
    assert '"-m", "pytest"' in job and "check=True" in job
