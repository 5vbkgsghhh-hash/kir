#!/usr/bin/env python3
"""CROSS-CHECKING "WHAT SHIPPED" AGAINST "WHAT WE HAVE" — FROM TWO
DIFFERENT CARRIERS.

    python tools/installed_matches_revision.py --sha <revision> --venv <venv root>
                                         [--repo /opt/kir]

The left side  — `git archive <sha>`: what we INTENDED to ship.
The right side — the site-packages of a venv installed FROM THE
NETWORK: what actually shipped.

🔴 WHY EXACTLY THIS WAY, AND WHY ANY OTHER PAIR IS MEANINGLESS.
A cross-check where both halves are taken from the TREE is an identity:
it is green by construction and cannot turn red. This class of mistake
was paid for twice in one day — on 01.09.2026 the "outside person's"
gate measured `/opt/kir` with all three of its halves, while what
actually shipped to people was the `publish/*` branch; on 02.09.2026
the release preflight guard read the gate manifest from the tree and so
would not have seen that the wheel was built from the live tree and
carried off someone's uncommitted change (7,773 bytes, caught by a
neighboring session, not by an instrument).

The rule: **the second side is taken FROM WHAT ACTUALLY SHIPPED** —
from the wheel, from the publish branch, from an install in a clean
venv.

🔴 THE VERDICT HERE IS NOT "THE FILES MATCHED". They cannot and should
not match: packaging DELIBERATELY selects tests (`tool.kir.wheel.keep`) and
excludes internal notes (`exclude-package-data`). The verdict is
different, and stricter:

    every discrepancy is DECLARED by the packaging; none are undeclared.

An undeclared shortfall is a silent loss; an extra file is a silent
addition; a discrepancy in content is exactly what this instrument was
introduced for.

🔴 WHAT THIS INSTRUMENT DOES NOT DO: it does not judge whether the code
is CORRECT (that is the gate's job), and it does not check that the
install actually works (that is the "outside person's" gate's job). It
answers one question — "did what we think shipped actually ship".

Return codes: 0 — everything is accounted for · 1 — something is
unexplained · 2 — the measurement did not happen.

🔴 WHERE THIS INSTRUMENT SITS IN THE RELEASE ORDER, AND HOW IT DIFFERS
FROM PREFLIGHT. `preflight.py` judges the WHEEL before it is sent:
metadata, contents, the absence of our topology and keys. This one
judges the INSTALL AFTER it is sent — that is, it answers a question
preflight cannot ask: "did that very thing arrive". It must be run
AFTER `twine upload` and after the index has caught up (on 03.09.2026
the first install from the network failed: `twine` returned 0, but
`pip` did not yet see the version — the uploader's return code and "a
person can install it" are different claims).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter

IMPORT_NAME = "kir"


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk(root: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in root.rglob("*"):
        if path.is_dir() or "__pycache__" in path.parts:
            continue
        out[str(path.relative_to(root))] = _digest(path)
    return out


def _is_test(rel: str) -> bool:
    parts = rel.split("/")
    return "tests" in parts or parts[-1].startswith("test_")


def _wheel_keep(root: pathlib.Path) -> set[str]:
    """Read current packaging configuration or an archived pre-migration revision."""
    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    wheel = config.get("tool", {}).get("kir", {}).get("wheel")
    if wheel is not None:
        return set(wheel["keep"])
    return set(json.loads((root / "WHEEL_KEEP.json").read_text("utf-8")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sha", required=True, help="ревизия, из которой собрано")
    ap.add_argument("--venv", required=True, help="корень venv с установкой ИЗ СЕТИ")
    ap.add_argument("--repo", default="/opt/kir")
    args = ap.parse_args()

    site = sorted(pathlib.Path(args.venv).glob("lib/python*/site-packages"))
    if not site:
        print("🔴 site-packages не найден — замер не состоялся"); return 2
    installed = site[0] / IMPORT_NAME
    if not installed.is_dir():
        print(f"🔴 в установке нет пакета «{IMPORT_NAME}» — замер не состоялся"); return 2

    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(["git", "archive", args.sha],
                              cwd=args.repo, capture_output=True)
        if proc.returncode != 0:
            print(f"🔴 git archive отказал: {proc.stderr.decode()[:200]}"); return 2
        subprocess.run(["tar", "-x", "-C", tmp], input=proc.stdout, check=True)
        root = pathlib.Path(tmp)
        keep = _wheel_keep(root)
        left = _walk(root / IMPORT_NAME)
        right = _walk(installed)

        # Absences declared by the packaging are READ, not remembered.
        excluded = set()
        pyproject = (root / "pyproject.toml").read_text("utf-8")
        for line in pyproject.splitlines():
            if "exclude-package-data" in line:
                continue
            if line.strip().startswith(('kir =', '"kir"', '"kir.')) and "[" in line:
                excluded.update(x.strip().strip('"\'')
                                for x in line.split("[", 1)[1].rstrip("]").split(","))

        def why_absent(rel: str) -> str | None:
            if _is_test(rel) and f"{IMPORT_NAME}/{rel}" not in keep:
                return "тест вне отбора колеса"
            if pathlib.Path(rel).name in excluded:
                return "exclude-package-data"
            return None

        only_left = sorted(set(left) - set(right))
        only_right = sorted(set(right) - set(left))
        differ = sorted(k for k in set(left) & set(right) if left[k] != right[k])
        named = {r: why_absent(r) for r in only_left}
        unexplained = sorted(r for r, w in named.items() if w is None)

        print(f"ревизия {args.sha} · файлов {len(left)} → в установке {len(right)}")
        for why, n in Counter(w or "🔴 НЕ ОБЪЯСНЕНО" for w in named.values()).most_common():
            print(f"   {why:<28} {n}")
        if only_right:
            print(f"🔴 ЛИШНИЕ в установке: {len(only_right)} {only_right[:5]}")
        if differ:
            print(f"🔴 РАСХОДЯТСЯ СОДЕРЖИМЫМ: {len(differ)} {differ[:5]}")
        if unexplained:
            print(f"🔴 недостачи без объяснения: {unexplained[:10]}")

        bad = bool(unexplained or only_right or differ)
        print("🔴 ЕСТЬ НЕОБЪЯСНЁННОЕ" if bad
              else "каждое расхождение НАЗВАНО упаковкой")
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
