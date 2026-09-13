#!/usr/bin/env python3
"""Enforce the tracked-secret boundary for KIR and its runtime adapters.

Only KIR-owned source and explicitly named backend credential files are in
scope.  Findings report a path and rule identifier but never the matched
bytes, so CI cannot amplify a leaked value.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAX_TEXT_BYTES = 5 * 1024 * 1024

FORBIDDEN_TRACKED_PATHS = {
    Path("backend/.env"),
    Path("backend/.antigravity-proxy-key"),
}

# 🔴 THE LAYOUT WAS PRE-SPLIT, AND THE SECRET SCANNER LOOKED AT NOT A SINGLE
# FILE OF THE PACKAGE (measured 04.09.2026). Five prefixes stood here —
# `backend/kukai/ir/`, `backend/compile-service/`, `src/Kukai.Revit.Bridge/`
# and kin — with ZERO paths of this repository among them. The number: the
# scanner's own files numbered **4** (all `.github/…`), under `kir/` — **0**.
# That is, 1090 compiler files were not checked for a leaked key AT ALL, while
# the job was green: it honestly scanned an empty set.
#
# The ratchet `test_secret_boundary_owns_and_triggers_for_the_same_source_set`
# catches this drift — but before 04.09 it stayed silent for the same reason
# the scanner itself did: the evidence manifest described the SAME dead
# layout, and the two lists were IN AGREEMENT ABOUT SOMETHING THAT DID NOT
# EXIST. Agreement between two dead lists is indistinguishable from agreement
# between two live ones — that is the price of a second carrier.
#
# The list now REFLECTS the manifest (`kir_evidence_manifest.SOURCE_PREFIXES`),
# and the match is guarded by the same ratchet in both directions.
KIR_PREFIXES = (
    "kir/",
    "tools/",
    "connector/",
    "examples/",
    "build_support/",
)

# The files named individually are the same as in the evidence manifest: the
# package root and both jobs' own scripts. The seven `backend/…` paths were
# dropped for the same reason as the prefixes: not one of them exists in this
# repository (checked with `git ls-files`).
KIR_FILES = {
    ".github/scripts/kir_ci_suites.py",
    ".github/scripts/Kir.CI.References.csproj",
    ".github/scripts/kir_evidence_manifest.py",
    ".github/scripts/kir_secret_boundary.py",
    ".github/workflows/kir-evidence.yml",
    ".github/workflows/kir-security.yml",
    "MANIFEST.in",
    "pyproject.toml",
}

CONTENT_RULES: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("google-api-key", re.compile(rb"\bAIza[A-Za-z0-9_-]{30,}\b")),
    ("github-token", re.compile(rb"\bgh[opusr]_[A-Za-z0-9]{30,}\b")),
    ("provider-api-key", re.compile(rb"\bsk-(?:proj-|or-v1-)?[A-Za-z0-9_-]{24,}\b")),
    ("telegram-bot-token", re.compile(rb"\b[0-9]{8,12}:[A-Za-z0-9_-]{30,}\b")),
)


def tracked_paths() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [Path(raw.decode("utf-8")) for raw in output.split(b"\0") if raw]


def is_kir_owned(path: Path) -> bool:
    text = path.as_posix()
    return text in KIR_FILES or text.startswith(KIR_PREFIXES)


def content_violations(path: Path) -> list[str]:
    absolute = ROOT / path
    try:
        if not absolute.is_file() or absolute.stat().st_size > MAX_TEXT_BYTES:
            return []
        payload = absolute.read_bytes()
    except OSError:
        return []
    if b"\0" in payload:
        return []
    return [name for name, pattern in CONTENT_RULES if pattern.search(payload)]


def main() -> int:
    failures: list[tuple[Path, str]] = []
    for path in tracked_paths():
        if path in FORBIDDEN_TRACKED_PATHS:
            failures.append((path, "tracked-runtime-credential"))
        elif is_kir_owned(path):
            failures.extend((path, rule) for rule in content_violations(path))

    if failures:
        print("KIR secret boundary failed:")
        for path, rule in failures:
            print(f"- {path.as_posix()}: {rule}")
        print("Rotate the credential and remove it from Git before retrying.")
        return 1

    print("KIR secret boundary OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
