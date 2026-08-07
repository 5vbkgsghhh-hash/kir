"""Ratchets for commit-bound KIR CI evidence and branch coverage."""
from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
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


def test_evidence_runs_for_main_and_prod_live_pushes():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main, prod-live]" in text


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
    assert "needs: [offline, generated-csharp-6x]" in text
    assert "kir-evidence-${{ github.sha }}-${{ github.run_attempt }}" in text
    manifest = _manifest_module()
    assert manifest.SCHEMA == "kukai.kir.ci-evidence/1"
