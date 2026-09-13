"""A FULL RUN AS AN INSTRUMENT, NOT AS A FEAT.

    python3.12 tools/wave_run.py                  # HEAD
    python3.12 tools/wave_run.py --ref a93d221    # any ref: a control on the past
    python3.12 tools/wave_run.py --self-check     # FAIL control of the instrument itself

🔴 WHY, AND THIS IS A ONE-DAY MEASUREMENT (02.09.2026). A wave of twelve
commits passed with a GREEN 15-file gate after each one. The full run found
**23 reds**, of which **nine files are red ALONE**, and **six code ones were
brought in by edits from THAT SAME DAY**:

    the ring limit was raised in ONE carrier — eight places still spoke the
        old one, and the worst of the eight was the MODEL'S PERMANENT DOC:
        it was told, on every turn, a boundary that no longer exists
    the layer wave removed 29 of 41 wrappers — a satellite sweep found 0
        places instead of 6
    the module moved — the debt stayed at the dead address
    the FAIL control substituted a MODULE ATTRIBUTE, while the registry
        holds an OBJECT: the substitution reached nowhere, and the control
        gutted nothing
    an op entered SOLO_OPS without a sample — the SAME kind, a SECOND time

The 15-file gate does not see the trace of its own wave: all six lived
OUTSIDE the gate. So the full run must be part of the routine, not a feat
performed once a week — and it must be ONE COMMAND, because assembled by
hand it takes six steps and two traps, and I caught both of those on
myself that day.

🔴 TWO TRAPS PAID FOR BY EXECUTION, AND BOTH CLOSED HERE

    cwd IS STRONGER THAN PYTHONPATH.  `cd /opt/kir && PYTHONPATH=<copy>
        python -c "import kir"` gives the TREE, not the copy: for `-c`/`-m`
        the empty string (the current directory) sits in `sys.path` BEFORE
        PYTHONPATH. The measurement would silently describe the wrong
        subject.
    A FOREIGN `kir.py` SITS IN /tmp.  Measuring from a "neutral" directory
        is also not allowed: a stray file shadows the whole package.

So the subject is checked by TWO questions before the run (`kir.__file__`
and `sandbox._backend_root()` — the root the sandbox's CHILD takes), and a
mismatch is a loud refusal, not a footnote at the end.

FOUR OUTCOMES FOR EACH RED, NOT TWO
------------------------------------

    CODE          red ALONE both on the copy and on the live tree — a defect
    COMPANY       green alone, red in the joint run — state leakage between
                  files; the subject of separate work, not this one
    ARTIFACT      red on the copy, GREEN on the live tree, AND THE REF IS
                  HEAD — meaning the wrong thing was measured (a copy
                  without `.git`, no host port)
    CODE ON REF   red on the copy, green on the live tree, BUT THE REF IS
                  NOT HEAD: there is NOTHING here to distinguish "fixed
                  later" from "artifact," and both halves are named instead
                  of picking one
    NOT RESOLVED  the solo run of the file itself did not happen (timeout,
                  build failure) — the outcome IS NAMED, not merged into
                  "code"

Summing them would be exactly the lie in the direction of "we're worse off
than we are," and silently dropping artifacts would be the lie in the
direction of "better."

🔴 A FIFTH OUTCOME WAS PAID FOR BY ITS OWN CONTROL (02.09.2026, at the hour
the instrument was born). The first edition always checked "is the file
red" against the LIVE TREE. A control on `--ref a93d221` — a run with an
answer known by hand (9 code, 3 company) — gave **1 code and 9 artifacts**:
nine defects FIXED LATER THAT SAME DAY, the live tree showed as green, and
the instrument declared them "not defects." An instrument that checks the
past against the present grows more confident the more gets fixed. Now it
asks whether the ref is HEAD, and on a historical ref it NAMES both halves.

🔴 AND SECOND, FOUND BY THAT SAME CONTROL: THE FULL RUN IS NOT BIT-FOR-BIT
REPRODUCIBLE. Two runs of ONE frozen ref gave `23 failed / 9781 passed` and
`24 failed / 9780 passed`. The difference is exactly one test, and it is a
TIME test (`test_long_run_memory_and_time`, a 4 ms budget per program): it
turns red under a neighbor's load. So the red count is comparable between
days ONLY up to the load-dependent guards, and they need to be known by
name (E-114).

WHAT THE INSTRUMENT DOES NOT DO
---------------------------------
It does not fix, does not commit, does not touch the working tree.
Uncommitted work IS NOT MEASURED, and this is stated as a number: the
subject is `git archive <ref>`, i.e. exactly what will ship to a neighbor
and into the wheel.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time

ДЕРЕВО = pathlib.Path(__file__).resolve().parent.parent

#: It is held outside the run BY A MEMORY MEASUREMENT, not by taste. It is
#: held HERE, in one place, and printed in the report — otherwise the "full
#: run" would quietly stop being full.
#:
#: 🔴 NARROWED ON 03.09.2026: THE EXCLUSION WAS WIDER THAN ITS OWN REASON,
#: AND BOTH HALVES TURNED OUT WRONG. The reason stated was "a 6 942 MB peak
#: was produced by SIX tests of ONE file." Measured one by one,
#: `/usr/bin/time -f %M`, under lock:
#:
#:   BulkFlag::test_exactly_the_internal_budget_with_bulk_ok   6 584 MB, OOM
#:   BulkFlag::test_one_over_the_internal_budget_refused…        251 MB, passed
#:   BulkFlag::test_one_over_the_authored_budget_is_refused…     152 MB, passed
#:   BulkFlag::test_program_id_is_internal_bulk_metadata_only     56 MB, passed
#:   kir/tests/test_program_py_door.py, all 34                    44 MB, 0.53 s
#:
#: That is, exactly ONE test is heavy, while `-k "not BulkFlag"` removed
#: SEVEN across the whole tree. And `test_program_py_door.py` was held
#: outside the run for a reason that described A DIFFERENT file: it is
#: skipped entirely (it needs the host port `serving._turn_device_id`) and
#: costs 44 MB — verified with the host's tree on `PYTHONPATH` too, the skip
#: is the same, because the path is not the same thing as
#: `kir_ports.install()`.
#:
#: That very named class: the number is correct, its subject belongs to
#: someone else.
ДЕРЖИМ_ВНЕ = ("--deselect",
              "kir/decompile/tests/test_materialize.py::BulkFlag"
              "::test_exactly_the_internal_budget_with_bulk_ok")

ИТОГ = re.compile(
    r"(?:(\d+) failed)?[, ]*(?:(\d+) passed)?[, ]*(?:(\d+) skipped)?"
    r"[, ]*(?:(\d+) deselected)?[, ]*(?:(\d+) xfailed)?[, ]*(?:(\d+) errors?)?")
КРАСНАЯ = re.compile(r"^(FAILED|ERROR|SUBFAILED)(?:\([^)]*\))?\s+(\S+)")


class ЗамерНеСостоялся(SystemExit):
    """Instrument refusal. A zero from here would be a fact about the
    instrument, not about the tree."""


def _венв() -> str:
    """The interpreter ONLY from the venv, and this was paid for TWICE, in
    different ways.

    On 22.08 the system python gave a phantom SyntaxError of a different
    version; on 01.09 the system one turned out to have `pytest-randomly`,
    which the production venv does not have — the «28·12·18·7·22» red
    series was taken under a forbidden interpreter and did NOT describe the
    tree. The order in the venv is fixed, and the numbers are comparable
    between days.
    """
    if sys.prefix == sys.base_prefix:
        raise ЗамерНеСостоялся(
            "ОТКАЗ: прибор запущен НЕ из venv (sys.prefix == sys.base_prefix).\n"
            "  У системного python стоит pytest-randomly, которого в боевом\n"
            "  venv нет: порядок поедет, и красные будут о ПОРЯДКЕ, а не о\n"
            "  дереве. Зови venv-питоном явно.")
    return sys.executable


def _sha(ref: str) -> str:
    p = subprocess.run(["git", "-C", str(ДЕРЕВО), "rev-parse", "--short", ref],
                       capture_output=True, text=True)
    if p.returncode:
        raise ЗамерНеСостоялся(f"ОТКАЗ: ref {ref!r} не разрешается: {p.stderr.strip()}")
    return p.stdout.strip()


def _грязь() -> list[str]:
    p = subprocess.run(["git", "-C", str(ДЕРЕВО), "status", "--porcelain"],
                       capture_output=True, text=True)
    return [l for l in p.stdout.splitlines() if l.strip()]


def заморозить(ref: str, куда: pathlib.Path) -> str:
    """`git archive` — the subject is taken FROM GIT, not from the tree.

    Three measurements in one shift (26.08) described a MIX of committed
    work with someone else's uncommitted work; it is cured by exactly one
    command.
    """
    sha = _sha(ref)
    куда.mkdir(parents=True, exist_ok=True)
    arch = subprocess.Popen(["git", "-C", str(ДЕРЕВО), "archive", ref],
                            stdout=subprocess.PIPE)
    tar = subprocess.Popen(["tar", "-x", "-C", str(куда)], stdin=arch.stdout)
    arch.stdout.close()
    tar.communicate()
    if tar.returncode:
        raise ЗамерНеСостоялся(f"ОТКАЗ: распаковка {sha} вернула {tar.returncode}")
    return sha


def сверить_предмет(копия: pathlib.Path, py: str) -> list[str]:
    """TWO questions, and both BEFORE the run. If the answer is wrong — a
    loud refusal."""
    код = ("import json, kir; from kir import sandbox;"
           "print(json.dumps({'kir': kir.__file__,"
           "'ребёнок': str(sandbox._backend_root())}))")
    p = subprocess.run([py, "-c", код], cwd=str(копия), capture_output=True,
                       text=True, env={**os.environ, "PYTHONPATH": str(копия)})
    if p.returncode:
        raise ЗамерНеСостоялся(
            "ОТКАЗ: предмет не отвечает на вопрос о себе:\n" + p.stderr.strip()[-600:])
    где = json.loads(p.stdout.strip().splitlines()[-1])
    чужое = [f"{k}={v}" for k, v in где.items()
             if not str(v).startswith(str(копия))]
    if чужое:
        raise ЗамерНеСостоялся(
            "ОТКАЗ: ПРЕДМЕТ НЕ ТОТ — прогон описал бы другое дерево:\n  "
            + "\n  ".join(чужое)
            + f"\n  ожидалось внутри {копия}\n"
            "  (cwd стоит в sys.path РАНЬШЕ PYTHONPATH; из корня дерева\n"
            "   замер молча мерит дерево, а в /tmp лежит чужой kir.py)")
    return [f"{k} -> {v}" for k, v in где.items()]


#: The box lock. One wide suite at a time: on 03.09.2026 THREE full runs at
#: once drove swap to 100% and killed a neighbor's run with an OOM. An
#: instrument running 10 000 tests must take the lock FIRST — otherwise it
#: is itself that third run.
ЗАМОК = "/opt/kukai-rebuild1/backend/tools/suite_lock.py"


def _прогон(py: str, корень: pathlib.Path, цель: list[str], лог: pathlib.Path,
            таймаут: int, *, под_замком: bool = False) -> int:
    """The return code is taken WITHOUT A PIPE: `| tail` returns 0 even on
    an OOM."""
    с = [py, "-m", "pytest", *цель, "-q", "-p", "no:cacheprovider", "-rfEs"]
    if под_замком and os.path.exists(ЗАМОК):
        # `run` releases the lock itself, even on a crash — hence a wrapper,
        # not an acquire/release pair: with that pair, the lock is left
        # hanging when the lead is killed.
        с = [py, ЗАМОК, "run", "--"] + с
    with open(лог, "w", encoding="utf-8") as fh:
        try:
            p = subprocess.run(с, cwd=str(корень), stdout=fh,
                               stderr=subprocess.STDOUT, timeout=таймаут,
                               env={**os.environ, "PYTHONPATH": str(корень)})
        except subprocess.TimeoutExpired:
            return -1
    return p.returncode


def _красные(лог: pathlib.Path) -> tuple[list[tuple[str, str]], str]:
    текст = лог.read_text(encoding="utf-8", errors="replace").replace("\0", "")
    строки = текст.splitlines()
    красные = []
    for l in строки:
        m = КРАСНАЯ.match(l)
        if m:
            красные.append((m.group(1), m.group(2)))
    итог = ""
    for l in reversed(строки):
        if " passed" in l or " failed" in l or " error" in l:
            итог = l.strip()
            break
    return красные, итог


def назвать(соло: int, живой: int | None, реф_это_head: bool) -> str:
    """A PURE outcome function — so it can be checked without a run.

    `соло` is the return code of the file run ALONE on the copy; `живой` is
    the same on the live tree (`None` if not asked). The parsing was moved
    out here precisely because its first edition was wrong, and catching
    that was only possible with a control whose answer was known.
    """
    if соло == -1:
        return "НЕ РАЗОБРАН (таймаут в одиночку)"
    if соло == 0:
        return "КОМПАНИЯ"
    if живой:
        return "КОД"
    if реф_это_head:
        return "АРТЕФАКТ ЗАМЕРА (зелен на живом дереве)"
    return "КОД НА РЕФЕ (на HEAD зелен: починено позже ЛИБО артефакт)"


def разобрать(py: str, копия: pathlib.Path, красные: list[tuple[str, str]],
              таймаут: int, реф_это_head: bool) -> dict[str, str]:
    """Every red FILE is run alone — on the copy, then on the tree.

    The order is exactly this: "alone on the copy" separates CODE from
    COMPANY, and "on the live tree" separates a defect from an ARTIFACT —
    but ONLY when the ref is HEAD. On a historical ref the live tree is a
    different subject, and its answer is different; see the fifth outcome
    in the header.
    """
    файлы = sorted({путь.split("::")[0] for _род, путь in красные})
    исход: dict[str, str] = {}
    for f in файлы:
        лог = копия / f"_solo_{f.replace('/', '_')}.log"
        код = _прогон(py, копия, [f], лог, таймаут)
        живой_код: int | None = None
        if код > 0:
            живой = ДЕРЕВО / f"_solo_live_{f.replace('/', '_')}.log"
            try:
                живой_код = _прогон(py, ДЕРЕВО, [f], живой, таймаут)
            finally:
                живой.unlink(missing_ok=True)
        исход[f] = назвать(код, живой_код, реф_это_head)
    return исход


def отчёт(sha: str, грязь: list[str], предмет: list[str], итог: str,
          красные: list[tuple[str, str]], исход: dict[str, str],
          секунды: float, код: int) -> int:
    печать = ["═" * 72,
              f"ПОЛНЫЙ ПРОГОН ВОЛНЫ · предмет {sha} · {секунды/60:.1f} мин",
              "═" * 72]
    for s in предмет:
        печать.append(f"  предмет: {s}")
    печать.append(f"  держим вне прогона: {' '.join(ДЕРЖИМ_ВНЕ)}")
    печать.append(f"  НЕ МЕРЕНО (незакоммичено в дереве): {len(грязь)} файлов")
    печать.append(f"  код возврата прогона (без трубы): {код}")
    печать.append("")
    печать.append(f"  ИТОГ pytest: {итог}")
    печать.append("")
    по_исходу: dict[str, list[str]] = {}
    for f, i in sorted(исход.items()):
        по_исходу.setdefault(i.split(" (")[0], []).append(f)
    for имя in ("КОД", "КОД НА РЕФЕ", "КОМПАНИЯ", "АРТЕФАКТ ЗАМЕРА",
                "НЕ РАЗОБРАН"):
        файлы = по_исходу.get(имя, [])
        печать.append(f"  {имя}: {len(файлы)} файлов")
        for f in файлы:
            тесты = [p for r, p in красные if p.split("::")[0] == f]
            печать.append(f"     {f}  ({len(тесты)} тестов)")
    кодовых = len(по_исходу.get("КОД", [])) + len(по_исходу.get("КОД НА РЕФЕ", []))
    неразобранных = len(по_исходу.get("НЕ РАЗОБРАН", []))
    печать.append("")
    печать.append(f"  🔴 КОДОВЫХ КРАСНЫХ ФАЙЛОВ: {кодовых}"
                  + (f" · НЕ РАЗОБРАНО: {неразобранных}" if неразобранных else ""))
    print("\n".join(печать))
    return 0 if (кодовых == 0 and неразобранных == 0) else 1


def самопроверка() -> int:
    """A FAIL CONTROL FOR THE INSTRUMENT, NOT FOR THE SUBJECT UNDER TEST.

    Three parses, each on an input with a KNOWN answer taken from real runs
    on 02.09.2026. An instrument whose parsing nobody has checked is just as
    much a source of a plausible-looking number as anything else.
    """
    ошибки: list[str] = []
    образцы = [
        ("19 failed, 9830 passed, 207 skipped, 7 deselected, 3 xfailed, "
         "11595 subtests passed in 3300.34s (0:55:00)", "19 failed"),
        ("23 failed, 9781 passed, 207 skipped, 7 deselected, 3 xfailed, "
         "28 warnings, 11563 subtests passed in 3430.26s (0:57:10)", "23 failed"),
        ("117 passed, 22 skipped, 479 subtests passed in 49.52s", "117 passed"),
    ]
    with tempfile.TemporaryDirectory() as d:
        for текст, ждём in образцы:
            лог = pathlib.Path(d) / "x.log"
            лог.write_text(текст + "\n", encoding="utf-8")
            _, итог = _красные(лог)
            if ждём not in итог:
                ошибки.append(f"итог не разобран: {итог!r}, ждали {ждём!r}")
        лог = pathlib.Path(d) / "y.log"
        лог.write_text(
            "FAILED kir/tests/a.py::K::t1\n"
            "SUBFAILED(op='transfer_family') kir/tests/b.py::K::t2\n"
            "ERROR kir/tests/c.py::K::t3\n"
            "не строка отказа: FAILED в середине\n"
            "12 failed, 3 passed in 1.0s\n", encoding="utf-8")
        красные, _ = _красные(лог)
        пути = [p for _r, p in красные]
        ждали = ["kir/tests/a.py::K::t1", "kir/tests/b.py::K::t2",
                 "kir/tests/c.py::K::t3"]
        if пути != ждали:
            ошибки.append(f"строки отказа разобраны как {пути}, ждали {ждали}")

    # ── OUTCOME: five cases, and the fifth is the one on which the
    # instrument lied
    случаи = [
        ("зелен в одиночку", (0, None, True), "КОМПАНИЯ"),
        ("таймаут в одиночку", (-1, None, True), "НЕ РАЗОБРАН"),
        ("красен всюду", (1, 1, True), "КОД"),
        ("красен на копии, зелен на HEAD", (1, 0, True), "АРТЕФАКТ ЗАМЕРА"),
        # 🔴 IT IS FOR THIS CASE THAT THE PARSING WAS MOVED INTO A PURE
        # FUNCTION. The first edition answered "ARTIFACT" here and declared
        # nine defects fixed later "not defects."
        ("красен на историческом рефе, зелен на HEAD", (1, 0, False),
         "КОД НА РЕФЕ"),
    ]
    for имя, (соло, живой, head), ждём in случаи:
        дано = назвать(соло, живой, head)
        if not дано.startswith(ждём):
            ошибки.append(f"{имя}: исход {дано!r}, ждали {ждём!r}")
    if ошибки:
        print("🔴 САМОПРОВЕРКА ПРИБОРА НЕ ПРОШЛА:")
        for e in ошибки:
            print("   ", e)
        return 1
    print("самопроверка прибора: разбор итога 3/3, разбор строк отказа 3/3, "
          "посторонняя строка не принята за отказ, исход 5/5 "
          "(включая исторический реф — случай, на котором прибор соврал)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="wave_run")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--keep", action="store_true",
                    help="не удалять замороженную копию и логи")
    ap.add_argument("--timeout", type=int, default=7200)
    ap.add_argument("--solo-timeout", type=int, default=900)
    ap.add_argument("--self-check", action="store_true")
    a = ap.parse_args(argv)
    if a.self_check:
        return самопроверка()

    py = _венв()
    грязь = _грязь()
    корень = pathlib.Path(tempfile.mkdtemp(prefix="kir-wave-"))
    копия = корень / "tree"
    начало = time.time()
    try:
        sha = заморозить(a.ref, копия)
        # 🔴 A FROZEN COPY HAS NO `.git`, AND AN INSTRUMENT ASKING FOR THE
        # REVISION DEGENERATES. Measured on 03.09: `test_the_block_does_not_
        # chase_its_own_commit` turned red on EVERY run of the wave — not
        # about the tree, but about the fact that `git rev-parse` in a
        # `tar -x` copy has nothing to answer with. A red with no subject
        # becomes background noise, and right next to it stood a REAL red
        # of the same file, with nothing to tell them apart.
        # The revision is known by exactly this instrument — and it is the
        # one obliged to pass it along.
        os.environ["KIR_FROZEN_SHA"] = sha
        предмет = сверить_предмет(копия, py)
        лог = корень / "full.log"
        код = _прогон(py, копия, ["kir", *ДЕРЖИМ_ВНЕ], лог, a.timeout,
                      под_замком=True)
        if код == -1:
            raise ЗамерНеСостоялся(
                f"ОТКАЗ: полный прогон не уложился в {a.timeout} с. "
                "Числа отсюда были бы фактом о таймауте.")
        красные, итог = _красные(лог)
        # 🔴 AN EMPTY RESULT IS A REFUSAL, NOT A GREEN. Paid for on
        # 03.09.2026: the run was turned away by the lock after 12 seconds,
        # no pytest summary appeared in the log at all, and the report
        # printed «КОДОВЫХ КРАСНЫХ ФАЙЛОВ: 0» — that is, a MEASUREMENT THAT
        # DID NOT HAPPEN was presented as a clean tree. Zero reds and zero
        # runs are indistinguishable exactly where the cost of a mistake is
        # highest.
        if not (итог or "").strip():
            хвост = лог.read_text(encoding="utf-8", errors="replace")[-600:]
            raise ЗамерНеСостоялся(
                "ОТКАЗ: pytest не оставил сводки — прогон НЕ СОСТОЯЛСЯ, и ноль\n"
                "  красных отсюда был бы фактом о приборе, а не о дереве.\n"
                f"  код возврата: {код}\n  хвост лога:\n{хвост}")
        исход = разобрать(py, копия, красные, a.solo_timeout,
                          реф_это_head=(sha == _sha("HEAD")))
        if a.keep:
            print(f"(копия и логи оставлены: {корень})")
        return отчёт(sha, грязь, предмет, итог, красные, исход,
                     time.time() - начало, код)
    finally:
        if not a.keep:
            shutil.rmtree(корень, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
