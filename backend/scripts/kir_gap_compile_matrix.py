#!/usr/bin/env python3
"""Офлайн-доказательство строк живой матрицы: программа × шесть версий Revit.

ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ. `scripts/kir_live_matrix.py` описывает программы, но
проверить их может только Revit — а Revit у оператора падает, и живой сеанс
стоит дороже всего, что у нас есть. Всё, что можно доказать БЕЗ устройства,
обязано быть доказано до него: программа, которая не проходит план, не
грунтуется или не компилируется хотя бы на одной поставляемой версии, на
живое устройство ехать не должна.

ЧТО ИМЕННО КОМПИЛИРУЕТСЯ. НАСТОЯЩИЕ программы матрицы, взятые ИМПОРТОМ
(`build_gap_programs()` / `build_programs()`), а не переписанные сюда. Матрица
над переписью доказывает свойства переписи — этот закон записан в шапке
`scripts/emitted_csharp_compile_matrix.py`, и здесь он соблюдён буквально:
единственный источник текста программ — тот же модуль, который поедет живьём.

ПУТЬ ОДИН И ТОТ ЖЕ: plan_program -> ground -> emit_program внутри
`compile_program`, ровно как в `serving.handle_revit_ir`; затем
`wrap_user_code` (канонический обёртчик конвейера) и живой Roslyn на :52412 —
тот же, которым пользуются `kukai/ir/gate_runner.py` и
`scripts/emitted_csharp_compile_matrix.py`.

ТРИ ИСХОДА ЯЧЕЙКИ, И ИХ НЕЛЬЗЯ СЧИТАТЬ ВМЕСТЕ
---------------------------------------------
    OK      C# собрался этой версией API
    отказ   компилятор ОТКАЗАЛ типизированно ДО эмиссии — это исправность, а
            не провал. Единственный ожидаемый случай на сегодня:
            `create_ceiling` на Revit 2021 (KIR-E003 — `Ceiling.Create`
            появился в 2022, а legacy-пути к потолку нет ни на одной версии).
            Ожидаемые отказы перечислены в EXPECTED_REFUSALS; отказ, которого
            там нет, — красный.
    FAIL    Roslyn не собрал. Симметричный красный (все шесть) почти всегда
            означает наш аргумент, асимметричный — версионную дыру.

ГРАНИЦА ОХВАТА, СЛОВАМИ
-----------------------
Это доказательство ФОРМЫ, а не поведения. Оно говорит «текст законен на всех
шести» и не говорит НИЧЕГО о том, примет ли Revit результат: `Ceiling.Create`
может скомпилироваться и вернуть null, тип может оказаться несовместим,
помещение — незамкнутым. Ровно за этим и нужна живая матрица; здесь мы лишь
гарантируем, что живой сеанс не будет потрачен на опечатку.

Пулы разрешаются по ФИКСТУРЕ (`kukai.ir.tests.fixtures.GROUND_SNAPSHOT`) —
у неё в каждом пуле известное содержимое, поэтому `pick(...)` резолвится
детерминированно и офлайн. Живьём те же места разрешает фаза 0 каталога.

    PYTHONPATH=. venv/bin/python3.12 scripts/kir_gap_compile_matrix.py
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_gap_compile_matrix.py --set all
    PYTHONPATH=. venv/bin/python3.12 scripts/kir_gap_compile_matrix.py --only create_door
Код возврата 0 — каждая ячейка либо OK, либо ОЖИДАЕМЫЙ отказ.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from kukai.ir.compiler import compile_program                    # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT              # noqa: E402
from kukai.llm.revit_execution_pipeline import wrap_user_code    # noqa: E402

import kir_live_matrix as M                                      # noqa: E402

COMPILE_URL = "http://localhost:52412/compile"
VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

#: id, которым подменяется `dep(...)` — предшественника офлайн не существует.
#: Значение НЕСУЩЕСТВЕННО: `by: element_id` — документированный сквозной
#: проход ground.py (существование и класс перепроверяются в C# во время
#: исполнения), поэтому компилируется ФОРМА обращения, а не конкретный id.
OFFLINE_DEP_ID = 424242

#: Отказы, которые СЧИТАЮТСЯ УСПЕХОМ: (строка, версия) -> код + почему.
#: Список закрытый; отказ вне его — красный, потому что «ожидаемо» без
#: названной причины — это способ не заметить регрессию.
EXPECTED_REFUSALS: dict[tuple[str, str], tuple[str, str]] = {
    ("create_ceiling", "2021"): (
        "KIR-E003",
        "Ceiling.Create появился в 2022; legacy-пути к потолку нет ни на одной "
        "версии 2021-2026 (замерено компиляцией) — обходного пути НЕТ"),
}


def offline_catalogue() -> dict:
    """Каталог из фикстуры: тот же формат, что даёт фаза 0 (`{id, name}`)."""
    cat: dict[str, list] = {}
    for pool, rows in GROUND_SNAPSHOT.items():
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) \
                and "id" in rows[0]:
            cat[pool] = [{"id": int(r["id"]), "name": r.get("name")}
                         for r in rows]
    # В фикстуре ни один тип стены не назван витражом, а
    # `pick(curtain_wall_type, prefer=("витраж", ...))` требует совпадения по
    # имени. Подставляем ИМЯ, а не id: проверяется само правило отбора, и
    # офлайн оно обязано отработать ровно так же, как в живом каталоге.
    for row in cat.get("wall_types", []):
        if row["id"] == 101:
            row["name"] = "Витраж 200 (фикстура)"
    return cat


def _op_ids(program: dict) -> list[str]:
    return [op["id"] for op in program.get("ops", []) if isinstance(op, dict)
            and isinstance(op.get("id"), str)]


def resolved_rows(which: str, only: set[str] | None) -> list[tuple]:
    """(имя, программа, выбор) — программы с разрешёнными плейсхолдерами."""
    universe = M.base_rows() + M.build_gap_programs()
    by_name = {r.name: r for r in universe}
    if which == "base":
        keep = {r.name for r in universe if "base" in r.tags}
    elif which == "gap":
        keep = {r.name for r in universe if "base" not in r.tags}
    else:
        keep = set(by_name)
    if only:
        keep = only & set(by_name)
    cat = offline_catalogue()
    produced = {r.name: {op_id: OFFLINE_DEP_ID for op_id in _op_ids(r.program)}
                for r in universe}
    out = []
    for row in universe:
        if row.name not in keep:
            continue
        chosen: dict = {}
        try:
            program = M.resolve_picks(row.program, cat, {}, chosen)
            program = M.resolve_deps(program, produced)
        except M.Unresolved as exc:
            out.append((row.name, None, f"НЕ СОБРАНА: {exc}"))
            continue
        out.append((row.name, program, chosen))
    return out


def compile_one(wrapped: str, version: str) -> tuple[bool, str]:
    body = json.dumps({"code": wrapped, "revitVersion": version}).encode()
    req = urllib.request.Request(
        COMPILE_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("success"):
        return True, ""
    errs = data.get("errors") or []
    return False, "; ".join(
        f"{e.get('code')}: {e.get('message')} (line {e.get('line')})"
        for e in errs[:2])


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", dest="which", default="gap",
                    choices=("gap", "base", "all"))
    ap.add_argument("--only", action="append")
    ap.add_argument("--json", help="куда положить машинный отчёт")
    args = ap.parse_args(argv)

    rows = resolved_rows(args.which, set(args.only) if args.only else None)
    ok_cells = fail_cells = expected_cells = 0
    report: list[dict] = []

    print(f"{'строка':28s} " + "  ".join(VERSIONS))
    print("-" * 78)
    for name, program, chosen in rows:
        if program is None:
            print(f"{name:28s} {chosen}")
            report.append({"row": name, "unbuildable": chosen})
            fail_cells += len(VERSIONS)
            continue
        cells, notes = [], []
        for ver in VERSIONS:
            out = compile_program(program, revit_version=ver,
                                  snapshot=GROUND_SNAPSHOT)
            if not out.ok:
                codes = [d.code for d in out.diagnostics]
                exp = EXPECTED_REFUSALS.get((name, ver))
                if exp and exp[0] in codes:
                    cells.append("отказ")
                    expected_cells += 1
                    notes.append(f"{ver}: ожидаемый отказ {exp[0]} — {exp[1]}")
                else:
                    cells.append("FAIL ")
                    fail_cells += 1
                    first = (out.diagnostics[0].message_ru[:170]
                             if out.diagnostics else "без диагностики")
                    notes.append(
                        f"{ver}: НЕОЖИДАННЫЙ отказ компилятора {codes}: {first}")
                continue
            good, msg = compile_one(wrap_user_code(out.csharp), ver)
            if good:
                cells.append("OK   ")
                ok_cells += 1
            else:
                cells.append("FAIL ")
                fail_cells += 1
                notes.append(f"{ver}: Roslyn {msg[:180]}")
        print(f"{name:28s} " + " ".join(cells))
        for n in notes:
            print(f"{'':28s} ↳ {n}")
        report.append({"row": name, "cells": dict(zip(VERSIONS, cells)),
                       "notes": notes, "chosen": chosen})

    total = ok_cells + fail_cells + expected_cells
    print("\n" + "=" * 78)
    print(f"ЯЧЕЕК {total} = строк {len(rows)} × версий {len(VERSIONS)}")
    print(f"  собрано Roslyn            {ok_cells}")
    print(f"  ожидаемый отказ (годно)   {expected_cells}")
    print(f"  НЕ СОБРАНО                {fail_cells}")
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps({"ok": ok_cells, "expected_refusal": expected_cells,
                        "fail": fail_cells, "rows": report},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  отчёт -> {args.json}")
    return 0 if fail_cells == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
