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

# 🔴 WHAT THIS SET IS OBLIGED TO COVER, AND WHY THE ANSWER IS NOT TAKEN OFF THE
# TOP OF ONE'S HEAD.
#
# The manifest signs ONE claim: "the green runs above apply to exactly this
# tree, at exactly this commit." So it is obliged to cover exactly what is
# CAPABLE OF CHANGING THE OUTCOME of those runs — no more and no less. More,
# and the digest moves on edits the gate never checked; less, and an edit that
# changes the answer does NOT MOVE the digest, so the signature stands over
# someone else's tree.
#
# Such a set is already named in this repository, and not here: it is the
# evidence job's `paths:` filters. Both lists answer ONE question ("what does
# the gate's answer depend on"), so a second hand-written copy would drift —
# NAKAZ item 4. What stands here is a REFLECTION of that list, and the match is
# guarded by a number:
# `kir/tests/test_ci_evidence_contract.py::test_every_file_in_the_evidence_
# digest_triggers_both_events` requires that every prefix and every file from
# here stand in BOTH `paths:` blocks of the workflow.
#
# 🔴 THE NUMBER BEFORE (measured 04.09.2026). Five prefixes and eleven files of
# the PRE-SPLIT layout stood here: `backend/kukai/ir/`, `src/Kukai.Revit.Bridge/`
# and kin. Paths starting with `kir/` numbered **ZERO** — meaning the digest
# covered NOT ONE FILE of the compiler this whole file was written for.
# `tracked_source_paths()` still returned a non-empty list (four `.github/…`
# files), so the "set is not empty" check was green, and self-consistency with
# the workflow was too: both described the very same dead tree. Two green
# instruments, and neither about the subject.
#
# 🔴 DEBT LEFT NAMED HERE, NOT CLOSED (04.09.2026). The same ratchet requires
# that this whole set be recognized as its own by the secret guard
# (`test_secret_boundary_owns_and_triggers_for_the_same_source_set`), yet
# `.github/scripts/kir_secret_boundary.py` and `.github/workflows/kir-security.yml`
# STILL describe the pre-split layout: `KIR_PREFIXES` there is the same five
# `backend/…`, and the secret scanner does not look at a single file of the
# package in this repository. Both files lay outside this shift's plot, so the
# edit was not made, and the ratchet is RED and says so plainly. A red that
# names what is real beats a green that agrees about what does not exist: until
# today both lists were dead, and dead things agree.
#
# 🔴 WHAT IS DELIBERATELY NOT HERE: `docs/`, `README.md`, `KIR_PLAN.md`,
# `assets/`. Measured 04.09: of six tests that mention `docs/`, zero READ it —
# all six mentions stand in docstrings (narration, not a route). An edit there
# does not move the run's outcome, so it has no business in the signature.
SOURCE_PREFIXES = (
    "kir/",
    "tools/",
    "connector/",
    # `kir/tests/test_sdk.py` COMPILES them and measures length — an input, not a showroom.
    "examples/",
    "build_support/",
)

SOURCE_FILES = {
    ".github/scripts/kir_ci_suites.py",
    ".github/scripts/Kir.CI.References.csproj",
    # What ships into the wheel and how: three tests read these files.
    "pyproject.toml",
    "MANIFEST.in",
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
