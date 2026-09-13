"""RED FROM THE CODE OR RED FROM A NEIGHBOR — ONLY THIS INSTRUMENT TELLS THEM APART.

🔴 WHY IT WAS SET UP (01.09.2026, integrity review).

This tree has `pytest-randomly` installed: the test order is shuffled on
EVERY run. A measurement, not a guess — the same lever, the same six files,
five random orders:

    28 · 12 · 18 · 7 · 22 reds, and all five COMPOSITIONS are different
    with `-p no:randomly`:  13 · 13 · 13, the composition is byte-identical
    each file ALONE:  2 out of the same 13

Hence a rule more valuable than the number itself: **a red count without a
named seed is not a number, it is a single draw from a distribution.**
Comparing two runs ("it got better", "the change added reds") on such a
count means nothing: this very shift I myself got 50 against 56 and nearly
attributed the difference to the lever's change, though a fixed order showed
that the lever moves NOT A SINGLE test.

WHAT THIS INSTRUMENT ANSWERS, WITH THREE NUMBERS

    alone        the file run ALONE, in a fixed order. This red belongs to
                 the CODE: there were no neighbors able to make a mess
    together     all files in one run, in a fixed order. The difference from
                 the first is the cost of STATE LEAKAGE between tests
    by seed      N runs with random order: the spread. It shows how large
                 the part of the count is that is not about the tree at all

WHAT THE INSTRUMENT DOES NOT DO, AND WHY

  * it does not fix the leak and does not name the culprit: "who exactly
    made the mess" is a question for a pair of tests, not for the count, and
    is resolved by bisecting the order, not here;
  * it does not declare the fixed order to be the correct one. The random
    order is included PRECISELY so the leak can be SEEN. Hiding it forever
    behind the `-p no:randomly` flag would buy a stable number at the price
    of blindness. The correct arrangement: the gate's number is taken in a
    fixed order (otherwise it is not comparable), and the leak is caught by
    a SEPARATE run over seeds — here both are done;
  * it does not count skips and collection errors: they have their own
    cause, and adding them to the reds would mean summing two currencies
    into one ranking.

RUN

    python3.12 tools/suite_leak_census.py <file|dir> ...
    python3.12 tools/suite_leak_census.py --seeds 8 kir/tests/test_open_model.py
    python3.12 tools/suite_leak_census.py --from-failed <file with a list of paths>
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
_COUNT = re.compile(r"(\d+) failed")
_SEED = re.compile(r"randomly seed: (\d+)", re.I)


def _run(paths: list[str], *, fixed: bool, seed: int | None = None) -> tuple[int, str]:
    """Run and the red count. `-1` means the run DID NOT HAPPEN, and that is
    not zero.

    🔴 Distinguishing this is mandatory: pytest that failed at collection
    prints zero reds exactly the same as a green tree. The pattern "the
    measurement may not have happened" has been paid for by this tree three
    times.
    """
    cmd = [sys.executable, "-m", "pytest", "-q", *paths]
    if fixed:
        cmd += ["-p", "no:randomly"]
    elif seed is not None:
        cmd += [f"--randomly-seed={seed}"]
    env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin:/usr/local/bin"}
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                           text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        return -1, "бюджет 3600 с истёк"
    out = p.stdout + p.stderr
    # 🔴 WHETHER "THE MEASUREMENT HAPPENED" IS DECIDED BY PYTEST'S RETURN
    # CODE, NOT BY SEARCHING FOR A WORD. The first edition took the
    # substring "error" in the absence of "collected" as the sign of a
    # measurement that did not happen. Under `-q` pytest does not print
    # "collected", and any red test brings "AssertionError" — and the
    # instrument declared a perfectly healthy run of «1 failed, 165 passed»
    # to NOT HAVE HAPPENED. Caught on the very first call, on its own tree.
    #
    # pytest's codes are closed and mean exactly this:
    #   0 all green · 1 THERE ARE REDS · 2 interrupted · 3 internal error
    #   4 usage error · 5 NO TEST WAS COLLECTED AT ALL
    # The five stands apart and is NOT equal to zero reds: "no tests were
    # found" is a fact about the CALL, and adding it to a green tree means
    # constructing a false zero.
    if p.returncode == 5:
        return -1, "не собрано ни одного теста — это НЕ ноль красных"
    if p.returncode not in (0, 1):
        последняя = (out.strip().splitlines() or ["вывода нет"])[-1]
        return -1, f"pytest вернул {p.returncode}: {последняя[:110]}"
    m = _COUNT.search(out)
    if m:
        return int(m.group(1)), ""
    if p.returncode == 0:
        return 0, ""
    return -1, "код 1, но сводки с числом красных нет — замер несравним"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="*", help="файлы или каталоги тестов")
    ap.add_argument("--from-failed", metavar="ФАЙЛ",
                    help="взять пути из файла, по одному в строке")
    ap.add_argument("--seeds", type=int, default=5,
                    help="сколько случайных порядков прогнать (0 — не гонять)")
    args = ap.parse_args()

    paths = list(args.paths)
    if args.from_failed:
        paths += [ln.strip() for ln in
                  pathlib.Path(args.from_failed).read_text(encoding="utf-8").split("\n")
                  if ln.strip()]
    paths = [p for p in paths if (ROOT / p).exists()]
    if not paths:
        print("🔴 ЗАМЕР НЕ СОСТОЯЛСЯ: не дано ни одного существующего пути.")
        print("Это факт О ВЫЗОВЕ, а не «красных ноль».")
        return 2

    print(f"дерево  {ROOT}")
    print(f"путей   {len(paths)}\n")

    print(f"{'файл':<58}{'в одиночку':>12}")
    print("─" * 70)
    alone_total, broken = 0, []
    for p in paths:
        n, why = _run([p], fixed=True)
        if n < 0:
            broken.append((p, why))
            print(f"{pathlib.Path(p).name:<58}{'НЕ СОСТОЯЛСЯ':>12}  {why}")
            continue
        alone_total += n
        print(f"{pathlib.Path(p).name:<58}{n:>12}")

    together, why_t = _run(paths, fixed=True)
    print("─" * 70)
    print(f"{'СУММА ПО ОДИНОЧКЕ — красное принадлежит КОДУ':<58}{alone_total:>12}")
    if together < 0:
        print(f"{'ВМЕСТЕ — замер не состоялся':<58}{'—':>12}  {why_t}")
    else:
        print(f"{'ВМЕСТЕ, фиксированный порядок':<58}{together:>12}")
        leak = together - alone_total
        знак = "+" if leak > 0 else ""
        print(f"{'РАЗНИЦА — цена ПРОТЕЧКИ СОСТОЯНИЯ между тестами':<58}"
              f"{знак}{leak:>11}")

    if args.seeds:
        print()
        counts = []
        for i in range(args.seeds):
            n, why = _run(paths, fixed=False, seed=1000 + i)
            counts.append(n)
            print(f"  семя {1000 + i}: красных {n if n >= 0 else 'НЕ СОСТОЯЛСЯ'}"
                  f"{'  ' + why if n < 0 else ''}")
        ок = [c for c in counts if c >= 0]
        if ок:
            print(f"\nразброс по {len(ок)} семенам: {min(ок)}…{max(ок)}")
            if min(ок) != max(ок):
                print("🔴 СЧЁТ КРАСНЫХ ЗАВИСИТ ОТ ПОРЯДКА. Число, снятое без "
                      "названного семени, НЕСРАВНИМО с любым другим прогоном.")

    if broken:
        print(f"\n🔴 не состоялось прогонов: {len(broken)} — это НЕ ноль красных")
        for p, why in broken:
            print(f"   {p}: {why}")
    return 0 if (together == alone_total == 0 and not broken) else 1


if __name__ == "__main__":
    sys.exit(main())
