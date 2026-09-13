"""A GUARD FOR THE CLASS "A TEST REACHES BACK INTO THE COMMIT TREE" (2026-09-08).

🔴 WHAT HAPPENED on 2026-09-07. A strip run on a FROZEN copy of the commit
tree (git archive: no `.work/`, no frontend build, no absolute paths from the
development machine) found three red tests and two silent skips that the
live tree had NEVER shown:
  * `E2MigrationContract` had the auditor read from `.work/marathon-…/left/…py`;
  * two viewer tests required `frontend/standalone/dist` (unbuilt);
  * the race/identity-replacement probes ran from `.work/` with the path
    `/root/kir-foundation`, and on a clean clone the test silently did
    `pytest.skip`.
Every one of these would be red or empty for the owner on a clean clone, and
green for us: the MEASUREMENT happened on a tree that has scratch space and
a build.

THE LAW. In test CODE (docstrings and comments do not count — a path there
may just be history), there must never be:
  * development-machine paths — `/root/kir-foundation`, `/tmp/kir-m…`: neither
    in strings, nor in child scripts that the test writes and runs; the root
    is taken from `__file__`, and passed to the child process via the
    environment;
  * paths into the `.work/…` scratch space and into the foreign tree
    `/opt/kir/…`, as paths (a string with no spaces and no Cyrillic — something
    that looks like a path, not a message).

Error messages where a path is named in words, and synthetic, nonexistent
paths containing Cyrillic, are not this guard's concern: it catches what gets
OPENED, not what gets talked about.

Controls: PASS — the tree with no findings; FAIL — a synthetic file with
each kind of literal gives exactly one finding of its own kind (test below).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: Development-machine paths are ALWAYS illegal in test code.
MACHINE = re.compile(r"/root/kir-foundation|/tmp/kir-m\d")
#: Scratch space and the foreign tree are illegal when the literal LOOKS LIKE A PATH.
SCRATCH = re.compile(r"(^|[^\w])\.work/|/opt/kir/")
CYRILLIC = re.compile(r"[А-Яа-яЁё]")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                    and isinstance(first.value.value, str):
                ids.add(id(first.value))
    return ids


def offending_literals(source: str) -> list[tuple[int, str, str]]:
    """(line, kind, literal) for every code string literal that reaches back into the tree."""
    tree = ast.parse(source)
    docs = _docstring_ids(tree)
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)) or id(node) in docs:
            continue
        text = node.value
        if MACHINE.search(text):
            found.append((node.lineno, "machine_path", text[:80]))
        elif SCRATCH.search(text) and not re.search(r"\s", text) and not CYRILLIC.search(text):
            found.append((node.lineno, "scratch_path", text[:80]))
    return found


def _test_files() -> list[Path]:
    return sorted(p for p in ROOT.glob("kir/**/*.py")
                  if ("/tests/" in p.as_posix() or p.name.startswith("test_"))
                  and p.name != Path(__file__).name)


def test_no_test_reaches_outside_the_tree():
    hits = []
    for path in _test_files():
        for line, kind, text in offending_literals(path.read_text(encoding="utf-8")):
            hits.append(f"{path.relative_to(ROOT)}:{line} [{kind}] {text!r}")
    assert not hits, (
        "тест тянется за дерево коммита — на чистом клоне он красный или пустой:\n  "
        + "\n  ".join(hits))


def test_the_scan_covers_the_tree_and_not_a_sample():
    files = _test_files()
    assert len(files) >= 800, len(files)  # 931 on 2026-09-08; a sharp drop means the walk is broken
    assert any("mcp/tests" in p.as_posix() for p in files) and any("decompile/tests" in p.as_posix() for p in files)


def test_the_guard_catches_each_kind_and_ignores_prose():
    sample = '''"""Докстрока может помнить /root/kir-foundation и .work/ — это история."""
import subprocess
def test_x():
    child = "import sys; sys.path.insert(0, '/root/kir-foundation')"   # путь машины
    probe = ".work/marathon/probe.py"                                    # скрэтч как путь
    msg = "см. отчёт в .work/ рядом с коммитом"                          # проза — не предмет
    fake = "/opt/kir/нет-такого.json"                                    # синтетика с кириллицей — не предмет
    tmp = "/tmp/kir-m7/x"                                                # машина
'''
    kinds = [kind for _, kind, _ in offending_literals(sample)]
    assert kinds == ["machine_path", "scratch_path", "machine_path"], kinds
