#!/usr/bin/env python3
"""EVERY EXAMPLE ON THE CHEAT SHEET IS COMPILED, FOR EVERY SUPPORTED VERSION.

    python3.12 tools/cheatsheet_check.py            # check
    python3.12 tools/cheatsheet_check.py --list     # only list the blocks

🔴 WHY. `docs/KIR_CHEATSHEET.md` is the whole reference a reader — a person or a
model — is given before writing a program. A reference whose examples do not
compile teaches the wrong language, and nobody notices until someone tries. So
the examples are not quoted from memory: this instrument extracts every fenced
`python` block, runs it, and compiles the program it builds for EACH supported
Revit version. A block that stops compiling turns this check red.

WHAT A BLOCK MUST DO. Build a program and leave it in a name:

    from kir.dsl import envelope, create_level, build
    envelope(intent="...")
    create_level(elev_mm=0, name="Level 1")
    program = build()
    snapshot = {...}        # optional, when names are resolved against a catalogue

The block does not compile anything itself: this instrument does, so the page
stays about the language and not about the harness.

WHAT IS ALSO CHECKED. The page's size against the budget the experiment fixed
(40 000 characters): a reference that grew past its budget is not the reference
the arms were promised.

THE RETURN CODE IS SPLIT BY MEANING, like `kir.selftest`'s:
    0  the check RAN, every block compiled, the budget holds
    1  the check RAN, there is red
    2  the check DID NOT RUN (no page, no blocks, an unreadable block)
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
PAGE = REPO / "docs" / "KIR_CHEATSHEET.md"
VERSIONS = ("2023", "2026")
#: The budget fixed for the RQ7 arms. The Revit API extract handed to the other
#: arm is cut to the same length, so this number is part of the experiment's
#: fairness, not a style preference.
CHARACTER_BUDGET = 40_000

PASSED, FAILED, NOT_RUN = 0, 1, 2

BLOCK = re.compile(r"^```python\n(.*?)^```$", re.M | re.S)
HEADING = re.compile(r"^#{2,4}\s+(.+?)\s*$", re.M)


def blocks(text: str) -> list[tuple[str, str]]:
    """Every fenced python block, named by the heading above it."""
    found = []
    for match in BLOCK.finditer(text):
        heads = HEADING.findall(text[: match.start()])
        found.append((heads[-1] if heads else "?", match.group(1)))
    return found


def compile_block(source: str, title: str) -> list[str]:
    """Run one block, compile what it built, and return this block's reds."""
    from kir import compile_program
    import kir.dsl as dsl

    dsl.reset()
    namespace: dict = {}
    try:
        exec(compile(source, f"<{title}>", "exec"), namespace)
    except Exception as error:                      # noqa: BLE001 - reported, not raised
        return [f"{title}: блок не исполнился — {type(error).__name__}: {error}"]
    program = namespace.get("program")
    if program is None:
        return [f"{title}: блок не оставил имени `program` — проверять нечего"]
    snapshot = namespace.get("snapshot")
    reds = []
    for version in VERSIONS:
        out = compile_program(program, revit_version=version,
                              snapshot=snapshot, bulk=True)
        if not out.ok:
            first = out.diagnostics[0] if out.diagnostics else None
            reason = (f"{first.code}: {first.message_ru.splitlines()[0]}"
                      if first is not None else "ok=False без диагностики")
            reds.append(f"{title} · Revit {version}: {reason}")
    return reds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tools/cheatsheet_check.py",
                                     description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="перечислить примеры и выйти")
    parser.add_argument("--page", type=pathlib.Path, default=PAGE)
    args = parser.parse_args(argv)

    if not args.page.is_file():
        print(f"🔴 ПРОВЕРКА НЕ СОСТОЯЛАСЬ: нет страницы {args.page}")
        return NOT_RUN
    text = args.page.read_text(encoding="utf-8")
    examples = blocks(text)
    if not examples:
        print("🔴 ПРОВЕРКА НЕ СОСТОЯЛАСЬ: на странице нет ни одного блока ```python")
        return NOT_RUN

    if args.list:
        for title, source in examples:
            print(f"  {title}  ({len(source.splitlines())} строк)")
        return PASSED

    size = len(text)
    #: 🔴 13.09.2026: `--page` exists so that the page can be checked WHERE THE
    #: READER FINDS IT — inside an unpacked sdist, for instance — and there
    #: `relative_to(REPO)` raised `ValueError` and the check died before running
    #: a single example. The address is printed as it was given when it lies
    #: outside the tree.
    try:
        shown = args.page.resolve().relative_to(REPO)
    except ValueError:
        shown = args.page
    print(f"ШПАРГАЛКА · {shown} · {size} знаков "
          f"из {CHARACTER_BUDGET} · примеров {len(examples)}\n")

    reds: list[str] = []
    for title, source in examples:
        block_reds = compile_block(source, title)
        mark = "ДА " if not block_reds else "НЕТ"
        print(f"  {mark}  {title}")
        reds.extend(block_reds)

    print()
    if size > CHARACTER_BUDGET:
        reds.append(f"страница больше бюджета: {size} > {CHARACTER_BUDGET} знаков")
    if reds:
        print("🔴 КРАСНОЕ:")
        for red in reds:
            print(f"   {red}")
        print("\nШПАРГАЛКА: НЕТ — пример со страницы не компилируется "
              "(или бюджет превышен).")
        return FAILED
    print(f"ШПАРГАЛКА: ДА — все {len(examples)} примеров компилируются для "
          f"{', '.join(VERSIONS)}, бюджет соблюдён.")
    return PASSED


if __name__ == "__main__":
    sys.exit(main())
