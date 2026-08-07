#!/usr/bin/env python3
"""Offline compile matrix for the audit rules' C# (kukai/audit/rules/*.py).

Every ``AuditRule.check_code`` is raw C# that ``AuditEngine._execute_rule``
hands to ``BridgeClient.execute`` verbatim (kukai/audit/engine.py:121) — there
is no version rewrite anywhere on that path. So a member Autodesk removed in a
newer Revit does not degrade the audit, it kills the rule outright: the bridge
fails to compile and the engine returns "Bridge execution failed: …" as the
finding (engine.py:133-140).

This matrix is the gate that path never had. It wraps each rule with the
pipeline's canonical wrapper (byte-identical to what the bridge's
TemplateRenderer builds) and compiles it against RevitAPI 2021-2026 through the
local Roslyn compile service (http://localhost:52412).

Usage:  venv/bin/python3.12 scripts/audit_rules_compile_matrix.py
Exit 0 = every cell compiled; non-zero = at least one failure (printed).
No Revit, no bridge, no model — pure offline proof.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kukai.audit.rules import load_all_rules  # noqa: E402
from kukai.llm.revit_execution_pipeline import wrap_user_code  # noqa: E402

COMPILE_URL = "http://localhost:52412/compile"
VERSIONS = ["2021", "2022", "2023", "2024", "2025", "2026"]


def compile_one(wrapped: str, version: str) -> tuple[bool, str]:
    body = json.dumps({"code": wrapped, "revitVersion": version}).encode("utf-8")
    req = urllib.request.Request(
        COMPILE_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("success"):
        return True, ""
    errs = data.get("errors") or []
    msg = "; ".join(f"{e.get('code')}: {e.get('message')} (line {e.get('line')})"
                    for e in errs[:3])
    return False, msg


def main() -> int:
    rules = load_all_rules()
    failures = 0
    for rule in rules:
        wrapped = wrap_user_code(rule.check_code)
        row = []
        for v in VERSIONS:
            ok, msg = compile_one(wrapped, v)
            row.append(f"{v}:{'OK  ' if ok else 'FAIL'}")
            if not ok:
                failures += 1
                print(f"FAIL {rule.id} [{v}] {msg}")
        print(f"{rule.id:9s} {'  '.join(row)}")
    total = len(rules) * len(VERSIONS)
    print(f"\nMATRIX: {total - failures}/{total} cells compiled "
          f"({len(rules)} rules x {len(VERSIONS)} Revit versions)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
