"""SELF-TEST OF THE INSTALLED PACKAGE: "KIR stands without KUKAI" — verifiable
BY WHOEVER INSTALLED IT.

    python -m kir.selftest            # run the gate suite from the install
    python -m kir.selftest --list     # only list the suite and its fate

🔴 WHY THIS WAS INTRODUCED (2026-09-01). The claim "the language stands
without the product" rested on a suite of fifteen files, and that suite's
manifest said, verbatim: paths are "relative to the INSTALLED package". A
measurement showed that only someone with the tree could check this:

    the manifest sat in the repository ROOT, not in the package -> it never
        rode into the wheel
    an outside person's install DOES have the suite            -> 15 of 15
        files
    but they have no list of WHAT EXACTLY to run                -> nothing
        to run it with

That is, the instrument existed, the proof existed, and there was no way to
show it to the person who installed the package. The manifest moved into
the package (`kir/gate_manifest.json`), and this module is the door to it.

WHAT THIS SELF-TEST DOES NOT DO, NAMED RATHER THAN FORGOTTEN:

  * It does NOT check behaviour inside Revit. The 6/6 gate needs the host
    port (`llm.revit_execution_pipeline`) and a compilation service; an
    outside person has neither BY CONSTRUCTION, and a refusal here would be
    a refusal of the environment, not of the package;
  * It does NOT replace the source tree's full suite: that stays with whoever
    maintains the language. It runs the selected files declared by the manifest;
  * It does NOT read the decompile corpus and does not touch the network.

🔴 THE EXIT CODE IS SPLIT BY MEANING, not by "succeeded / failed" — the same
shape as `kir.gate_runner`'s (`ed14ba8`): collapsing "not judged" into
"judged and found" would say "the suite found red" in a case where it never
even ran.

    0   JUDGED and everything green
    1   JUDGED and there is red
    2   NOT JUDGED AT ALL (no manifest, no files, no pytest) — with a reason
        and a next move
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import subprocess
import sys

#: The manifest file's name INSIDE the package. One carrier: the suite's
#: file list is not retyped here in prose — it is read from where it lives.
MANIFEST_NAME = "gate_manifest.json"

#: Outcomes named by a word, not by a number at the call site.
JUDGED_GREEN = 0
JUDGED_RED = 1
NOT_JUDGED = 2


def package_root() -> pathlib.Path:
    """The installed package's directory — from `kir.__file__`, not from `cwd`.

    Counting steps upward from this file is not allowed: that same shape
    ("counting steps upward") has already cost this tree thirteen carriers
    and a whole day of investigation.
    """
    import kir
    return pathlib.Path(kir.__file__).resolve().parent


def read_manifest(root: pathlib.Path) -> tuple[list[str], str | None]:
    """The suite's contents, or a reason in words.

    Returns `(names, refusal)`. An empty list with `None` is impossible: a
    manifest declaring an empty suite is a refusal, not a green suite of
    zero files (the "zero built from honest refusals" shape).
    """
    path = root / MANIFEST_NAME
    if not path.is_file():
        return [], (
            f"манифеста набора нет: {path}\n"
            "   Это не «набор пуст», а «спрашивать не у кого»: пакет собран без "
            "своего манифеста.\n"
            "   СЛЕДУЮЩИЙ ХОД: поставить колесо, собранное из дерева "
            "(`python -m build`), — манифест едет в пакете.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = list(data["набор"])
    except Exception as exc:                                    # noqa: BLE001
        return [], f"манифест не читается ({path}): {exc}"
    if not names:
        return [], f"манифест объявляет ПУСТОЙ набор: {path}"
    return names, None


def missing(root: pathlib.Path, names: list[str]) -> list[str]:
    """Suite files that are NOT in the install. An empty list means all arrived."""
    return [n for n in names if not (root / n).is_file()]


def pytest_present() -> bool:
    """Whether there is anything to run with. Asked via the SPEC, not an import.

    Importing `pytest` inside a process that is itself running under pytest
    would answer "yes" about a DIFFERENT install, while the question is
    about this one.
    """
    return importlib.util.find_spec("pytest") is not None


def _header(root: pathlib.Path, names: list[str]) -> str:
    """The instrument names its OWN SUBJECT and its OWN INVOCATION. A number
    without them is not a number."""
    import kir
    return (
        "САМОТЕСТ KIR — набор ворот из УСТАНОВЛЕННОГО пакета\n"
        f"  пакет         {root}\n"
        f"  версия        {getattr(kir, '__version__', 'нет атрибута')}\n"
        f"  интерпретатор {sys.executable}\n"
        f"  файлов набора {len(names)}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m kir.selftest",
        description="Прогнать набор ворот KIR из установленного пакета.")
    ap.add_argument("--list", action="store_true",
                    help="перечислить состав набора и не гонять")
    ap.add_argument("pytest_args", nargs="*",
                    help="доводы, передаваемые pytest как есть")
    args = ap.parse_args(argv)

    root = package_root()
    names, refusal = read_manifest(root)
    if refusal is not None:
        print("🔴 ОТКАЗ: набор НЕ ПРОГНАН.")
        print("   " + refusal)
        return NOT_JUDGED

    print(_header(root, names))

    gone = missing(root, names)
    if args.list:
        for n in names:
            print(f"  {'ЕСТЬ ' if (root / n).is_file() else 'НЕТ  '} {n}")
        if gone:
            print(f"\n🔴 в установке нет {len(gone)} из {len(names)} файлов набора")
            return NOT_JUDGED
        return JUDGED_GREEN

    if gone:
        print("🔴 ОТКАЗ: набор НЕ ПРОГНАН — в установке нет файлов, "
              f"объявленных манифестом ({len(gone)} из {len(names)}):")
        for n in gone:
            print(f"     {n}")
        print("   Это факт о СБОРКЕ колеса, а не о языке: колесо собрано без "
              "своего набора.\n"
              "   СЛЕДУЮЩИЙ ХОД: собрать колесо из дерева (`python -m build`) — "
              "состав отбирается `pyproject.toml: tool.kir.wheel.keep`.")
        return NOT_JUDGED

    if not pytest_present():
        print("🔴 ОТКАЗ: набор НЕ ПРОГНАН — в этом окружении нет `pytest`.")
        print("   Файлы набора на месте (все "
              f"{len(names)}), гонять их нечем.\n"
              '   СЛЕДУЮЩИЙ ХОД: pip install "kir-building[dev]"')
        return NOT_JUDGED

    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           *args.pytest_args, *[str(root / n) for n in names]]
    print("прогон: " + " ".join(cmd[:6]) + f" … ({len(names)} файлов)\n")
    proc = subprocess.run(cmd, cwd=str(root.parent))

    # 🔴 PYTEST'S CODE IS TRANSLATED, NOT PASSED THROUGH AS-IS. For pytest,
    # `2` means "interrupted", `5` means "no test collected"; our `2` means
    # "not judged". Passing a five through as zero would declare green a
    # suite that never was.
    if proc.returncode == 0:
        print("\nСАМОТЕСТ: набор ПРОГНАН, красных нет.")
        return JUDGED_GREEN
    if proc.returncode == 1:
        print("\nСАМОТЕСТ: набор ПРОГНАН, есть красные (см. вывод выше).")
        return JUDGED_RED
    print(f"\n🔴 ОТКАЗ: набор НЕ СОСТОЯЛСЯ — pytest вернул {proc.returncode} "
          "(2 прервано · 3 внутренняя ошибка · 4 ошибка вызова · "
          "5 не собрано ни одного теста).")
    print("   Это НЕ «ноль красных».")
    return NOT_JUDGED


if __name__ == "__main__":
    sys.exit(main())
