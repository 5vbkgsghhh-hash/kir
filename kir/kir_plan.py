"""REHEARSAL PRINTER: a human-readable view of the `kir.rehearsal` decompile.

    PYTHONPATH=. venv/bin/python kir/kir_plan.py program.json [--json]

The decompile does NOT LIVE HERE and must not: it lives in `kir/rehearsal.py`,
because the instrument showroom calls it, and the tree's dependencies run
`tools/` → `kukai/`, not the other way round. This file only prints.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from kir.rehearsal import rehearse


def render(r: dict) -> str:
    L = [f"РЕПЕТИЦИЯ · объявлено операций {r['ops_declared']}, "
         f"элементов после разворота групп {r['elements_total']}, "
         f"рейсов в Ревит 0", ""]
    L.append("ПО ОПЕРАЦИЯМ")
    for name, n in sorted(r["counts"].items(), key=lambda kv: -kv[1]):
        L.append(f"  {str(name):28} ×{n}")

    L += ["", "🔴 ПРИСЛАННОЕ ЗНАЧЕНИЕ РЕВИТ ПЕРЕПИШЕТ (authority=DERIVED_BY_REVIT)"]
    if r["authority_ignored"]:
        for d in r["authority_ignored"]:
            L.append(f"  ×{d['count']:<5} {d['op']}.{d['param']} — "
                     f"твоё значение НЕ РЕШАЕТ НИЧЕГО, Revit выведет своё")
    else:
        L.append("  нет")

    L += ["", "🔴 ВЛАСТЬ МОЛЧА УХОДИТ ДРУГОМУ МЕХАНИЗМУ (пропущено поле)"]
    if r["authority_transfer"]:
        for g in r["authority_transfer"]:
            L.append(f"  ×{g['count']:<5} {g['op']}: {g['because']}")
            L.append(f"         не проверится: {g['clause']}")
            L.append(f"         вместо программы решает: {g['transfers']}")
    else:
        L.append("  нет")

    L += ["", "⚪ НЕ БУДЕТ ПРОВЕРЕНО — НАЗВАНО ПРОЕКТОМ (решение с причиной)"]
    if r["named_absences"]:
        for name, items in r["named_absences"].items():
            for it in items:
                L.append(f"  {name}: {it['clause']}")
                L.append(f"         {it['why'][:150]}")
    else:
        L.append("  нет")

    L += ["", "⚠️  ПИШЕТ, А ПОД ПРИСМОТРОМ РОВНО ОДНА ОСЬ (заявка на разбор)"]
    if r["thin_axes"]:
        for name, axis in sorted(r["thin_axes"].items()):
            L.append(f"  {name}: только [{axis}]")
    else:
        L.append("  нет")

    if r["unwitnessed_ops"]:
        L += ["", "🔴 ОПЕРАЦИИ БЕЗ ТАБЛИЦЫ ОБЯЗАТЕЛЬСТВ (прибор НЕ ОТВЕЧАЕТ за них)"]
        for n in r["unwitnessed_ops"]:
            L.append(f"  {n}")
    if r["macro_ops"]:
        L += ["", "макросы (разворачивает компилятор, поля до разворота не наши): "
              + ", ".join(r["macro_ops"])]

    # Noise is printed COLLAPSED and last — but it IS printed, because "not
    # shown at all" and "shown as one line" are different things.
    if r["optional_unused"]:
        tot = sum(q["count"] for q in r["optional_unused"])
        L += ["", f"необязательные возможности не использованы — {tot} обязательств "
              f"по {len(r['optional_unused'])} поводам (норма, не находка):"]
        L.append("  " + " · ".join(f"{q['op']}/{q['because']}×{q['count']}"
                                   for q in r["optional_unused"][:8]))
        if len(r["optional_unused"]) > 8:
            L.append(f"  … и ещё {len(r['optional_unused']) - 8}")

    L += ["", "БУДЕТ ПРОВЕРЕНО"]
    for k, v in r["will_check"].items():
        L.append(f"  ×{v:<5} {k}")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(prog="kir_plan")
    ap.add_argument("program", help="файл программы KIR (JSON)")
    ap.add_argument("--json", action="store_true", help="машинный вывод")
    a = ap.parse_args()
    prog = json.loads(pathlib.Path(a.program).read_text(encoding="utf-8"))
    if isinstance(prog, dict) and "program" in prog and "ops" not in prog:
        prog = prog["program"]
    r = rehearse(prog)
    print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else render(r))
    # Non-zero exit code when there are obligations discharged by GATES: that
    # is something the author can fix themselves, and there must be no silent pass here.
    return 1 if (r["authority_transfer"] or r["authority_ignored"]) else 0


if __name__ == "__main__":
    sys.exit(main())
