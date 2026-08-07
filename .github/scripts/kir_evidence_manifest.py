#!/usr/bin/env python3
"""Create deterministic provenance for a successful KIR evidence run.

The workflow job that invokes this script depends on both the offline suite and
the generated-C# six-version gate.  The resulting artifact therefore names the
exact commit and the exact tracked KIR source tree those green results apply to.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "kukai.kir.ci-evidence/1"
REVIT_VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

SOURCE_PREFIXES = (
    "backend/kukai/ir/",
    "backend/kukai/operations/",
    "backend/compile-service/",
    "src/Kukai.Revit.Bridge/",
    "src/Kukai.Revit.Bridge.Tests/",
)

SOURCE_FILES = {
    "backend/kir_idempotence.py",
    "backend/kukai/compile_client.py",
    "backend/kukai/llm/envelope.py",
    "backend/kukai/llm/revit_execution_pipeline.py",
    "backend/kukai/storage/database.py",
    "backend/kukai/api/bridge_protocol.py",
    "backend/kukai/api/ws_registry.py",
    ".github/scripts/kir_evidence_manifest.py",
    ".github/scripts/kir_secret_boundary.py",
    ".github/workflows/kir-evidence.yml",
    ".github/workflows/kir-security.yml",
}


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, text=True
    ).strip()


def tracked_source_paths() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    paths = [Path(value.decode("utf-8")) for value in raw.split(b"\0") if value]
    selected = [
        path
        for path in paths
        if path.as_posix() in SOURCE_FILES
        or path.as_posix().startswith(SOURCE_PREFIXES)
    ]
    return sorted(selected, key=lambda value: value.as_posix())


def source_tree_digest(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        relative = path.as_posix().encode("utf-8")
        payload_digest = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(payload_digest.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def require_success(name: str, value: str) -> str:
    normalized = value.strip().lower()
    if normalized != "success":
        raise SystemExit(f"{name} did not succeed: {value!r}")
    return normalized


def build_manifest() -> dict[str, object]:
    commit = git("rev-parse", "HEAD")
    expected_commit = os.environ.get("GITHUB_SHA", "").strip()
    if expected_commit and expected_commit != commit:
        raise SystemExit(
            f"checked-out commit {commit} disagrees with GITHUB_SHA "
            f"{expected_commit}"
        )

    if git("status", "--porcelain"):
        raise SystemExit("evidence checkout is dirty")

    offline = require_success(
        "offline KIR evidence", os.environ.get("KIR_OFFLINE_RESULT", "success")
    )
    six_version = require_success(
        "generated C# six-version evidence",
        os.environ.get("KIR_SIX_VERSION_RESULT", "success"),
    )
    paths = tracked_source_paths()
    if not paths:
        raise SystemExit("KIR evidence source set is empty")

    return {
        "schema": SCHEMA,
        "commit": commit,
        "source_tree": {
            "algorithm": "sha256(path\\0sha256(bytes)\\n)",
            "digest": source_tree_digest(paths),
            "tracked_files": len(paths),
        },
        "checks": {
            "offline": offline,
            "generated_csharp_2021_2026": six_version,
        },
        "required_revit_versions": list(REVIT_VERSIONS),
        "workflow": {
            "repository": os.environ.get("GITHUB_REPOSITORY", "local"),
            "ref": os.environ.get("GITHUB_REF", "local"),
            "event": os.environ.get("GITHUB_EVENT_NAME", "local"),
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "local"),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=Path("kir-evidence-provenance.json")
    )
    args = parser.parse_args()

    manifest = build_manifest()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    try:
        display_path = output.relative_to(ROOT)
    except ValueError:
        display_path = output
    print(f"Wrote {display_path} for commit {manifest['commit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
