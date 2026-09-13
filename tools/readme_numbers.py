"""Check the registry counts, supported versions and Python examples in README.

Run with --check to return a nonzero exit code on a mismatch. The examples
are executed in separate Python processes and only generate code; Revit is
not started. Historical benchmarks removed from README are no longer part
of this check.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
README = REPO / "README.md"
MARKER = "KIR_README_RESULT:"


def _run(code: str, observation: str) -> dict:
    source = code + "\nimport json as _json\nprint(" + repr(MARKER) + "+_json.dumps(" + observation + "))\n"
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=REPO, capture_output=True,
        text=True, timeout=120,
        env={"PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1",
             "PATH": "/usr/bin:/bin"},
    )
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout)[-1200:].strip())
    records = [line[len(MARKER):] for line in result.stdout.splitlines()
               if line.startswith(MARKER)]
    if len(records) != 1:
        raise RuntimeError("Example did not return one verification record")
    return json.loads(records[0])


def _registry() -> dict:
    return _run("from kir import spec, sdk", "{"
                "'ops': len(spec.OPS), 'builders': len(sdk.builders()), "
                "'versions': list(spec.REVIT_VERSIONS)}")


def _table_count(text: str, label: str) -> int:
    match = re.search(r"^\|\s*" + re.escape(label) + r"\s*\|\s*(\d+)\s*\|\s*$", text, re.M)
    if not match:
        raise ValueError(f"Missing numeric table row: {label}")
    return int(match[1])


def _python_example(text: str, heading: str) -> str:
    section = re.search(r"^## " + re.escape(heading) + r"\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    block = re.search(r"^```python\n(.*?)^```\s*$", section[1], re.M | re.S) if section else None
    if not block:
        raise ValueError(f"Missing Python example in: {heading}")
    return block[1]


def check() -> list[tuple[str, bool, str]]:
    text = README.read_text(encoding="utf-8")
    registry = _registry()
    rows = []
    for label, key in [("Registered operations", "ops"), ("Generated SDK builders", "builders")]:
        try:
            claimed = _table_count(text, label)
            actual = registry[key]
            rows.append((label, claimed == actual, f"README {claimed}; registry {actual}"))
        except ValueError as error:
            rows.append((label, False, str(error)))

    match = re.search(r"Revit (20\d{2})[–-](20\d{2})", text)
    declared = [str(year) for year in range(int(match[1]), int(match[2]) + 1)] if match else []
    rows.append(("Revit targets", declared == registry["versions"],
                 f"README {declared}; registry {registry['versions']}"))

    for heading, observation, expected in [
        ("Example", "{'ok': out.ok, 'has_csharp': bool(out.csharp), 'ops': len(program['ops']), "
         "'versions': [v for v in __import__('kir').spec.REVIT_VERSIONS "
         "if compile_program(program, revit_version=v, bulk=True).ok]}",
         {"ok": True, "has_csharp": True, "ops": 5, "versions": registry["versions"]}),
        ("Model references", "{'without_catalog': missing_catalog.ok, "
         "'codes': [d.code for d in missing_catalog.diagnostics], 'with_catalog': out.ok, 'has_csharp': bool(out.csharp)}",
         {"without_catalog": False, "codes": ["KIR-G103"], "with_catalog": True, "has_csharp": True}),
    ]:
        try:
            actual = _run(_python_example(text, heading), observation)
            rows.append((heading, actual == expected, f"observed {actual}"))
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
            rows.append((heading, False, str(error)))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit with code 1 if a check fails")
    args = parser.parse_args(argv)
    try:
        rows = check()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"README check could not complete: {error}")
        return 1 if args.check else 0
    for name, passed, detail in rows:
        print(f"{'OK' if passed else 'FAIL'} {name}: {detail}")
    failed = sum(not passed for _, passed, _ in rows)
    print(f"{len(rows) - failed} passed; {failed} failed")
    return 1 if args.check and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
