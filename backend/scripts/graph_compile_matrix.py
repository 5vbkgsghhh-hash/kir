#!/usr/bin/env python3
"""Offline compile matrix for the perception-graph C# queries.

Wraps GRAPH_CS (v1), GRAPH_CS_V2 and GRAPH_CS_V3 with the pipeline's canonical
wrapper and compiles each against RevitAPI 2021-2026 via the local Roslyn
compile service (http://localhost:52412) — the API-correctness gate BEFORE any
live run. GRAPH_CS_V3 carries the geometry census (bbox banding, ElementId
category map, ProjectElevation, Grid axis extraction) — the risky C#.

Usage:  venv/bin/python scripts/graph_compile_matrix.py
Exit 0 = every cell compiled; non-zero = at least one failure (printed).
No Revit, no bridge, no model — pure offline proof.
"""
from __future__ import annotations

import json
import sys
import urllib.request

sys.path.insert(0, ".")

from kukai.llm.revit_execution_pipeline import wrap_user_code  # noqa: E402
from kukai.query.model_graph import GRAPH_CS, GRAPH_CS_V2  # noqa: E402
from kukai.query.model_graph_v3 import GRAPH_CS_V3  # noqa: E402

COMPILE_URL = "http://localhost:52412/compile"
VERSIONS = ["2021", "2022", "2023", "2024", "2025", "2026"]

ARTIFACTS = [("GRAPH_CS", GRAPH_CS), ("GRAPH_CS_V2", GRAPH_CS_V2),
             ("GRAPH_CS_V3", GRAPH_CS_V3)]


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
                    for e in errs[:5])
    return False, msg


def main() -> int:
    failures = 0
    for name, code in ARTIFACTS:
        wrapped = wrap_user_code(code)
        row = []
        for v in VERSIONS:
            ok, msg = compile_one(wrapped, v)
            row.append(f"{v}:{'OK' if ok else 'FAIL'}")
            if not ok:
                failures += 1
                print(f"FAIL {name} [{v}] {msg}")
        print(f"{name:15s} {'  '.join(row)}")
    total = len(ARTIFACTS) * len(VERSIONS)
    print(f"\nMATRIX: {total - failures}/{total} cells compiled "
          f"({len(ARTIFACTS)} queries x {len(VERSIONS)} Revit versions)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
