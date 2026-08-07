"""Живая частота по ОПЕРАЦИЯМ — с честным ответом «кто именно отказал».

ЗАЧЕМ ЭТО ОТДЕЛЬНЫЙ ИНСТРУМЕНТ
-------------------------------
Число «оп X работает в N% случаев» — первое, что спросят снаружи, и первое,
чем сами меряем готовность. До 31.07 оно считалось приписыванием провала ВСЕЙ
программе: если в программе были `create_wall` и `create_door`, а отказала
дверь, провал записывался обоим. Замер по корпусу дал `create_wall` 64.2% —
при том, что стена в тех прогонах построилась, и это видно в самой строке
корпуса, в поле `witness.geometry_ok`.

Ошибка не в арифметике, а в том, что у измерителя не было СВЯЗИ между списком
операций и списком нарушений: первый держал имена (`create_door`), второй —
идентификаторы (`PD`). Связь добавлена в `witness_feed._op_id`; здесь она
потребляется.

ЧЕТЫРЕ КОРЗИНЫ ВМЕСТО ДВУХ
---------------------------
«Успех/провал» на программе не переводится в «успех/провал» на операции без
потери правды. Транзакция откатывается ЦЕЛИКОМ: когда дверь нарушила
постусловие, стена тоже не осталась в модели — но стена при этом не сделала
ничего плохого. Считать это её провалом — клевета; считать успехом — ложь.
Поэтому корзин четыре:

  ПОСТРОЕНО      — программа закоммичена, операция не названа в нарушениях;
  ОБВИНЕНА       — операция названа в нарушении (её собственное постусловие
                   не сошлось). Единственная корзина, которая является
                   провалом ОПЕРАЦИИ;
  ПОПУТНО ОТКАЧЕНА — программа откатилась из-за ЧУЖОГО нарушения. Операция
                   не виновата и не построена;
  ПРОГРАММА УПАЛА — исполнение кончилось до пооперационного вердикта (X003,
                   X999, таймаут). Про операцию не известно ничего.

Частота операции = ПОСТРОЕНО / (ПОСТРОЕНО + ОБВИНЕНА). Две другие корзины
печатаются рядом и никогда не прячутся: их размер — это отдельный факт о
системе (много «попутно откачено» = программы слишком крупные для отладки;
много «программа упала» = беда до исполнения, а не в операции).

ПОЧЕМУ НИЖНЯЯ ГРАНИЦА, А НЕ ПРОЦЕНТ
------------------------------------
`create_grid` в корпусе — один прогон, один успех. Написать «100%» значит
соврать интонацией: одно наблюдение не отличает оп с частотой 99% от опа с
частотой 40%. Поэтому рядом с долей печатается нижняя граница Вильсона (95%
доверия) — то число, ниже которого частота почти наверняка НЕ лежит. Для
одного успеха из одного она равна 20.7%, и это честный ответ «мы не знаем».
Заявление «оп выше 95%» имеет право звучать только когда 95% перешагнула
ГРАНИЦА, а не доля.

Отсюда следует цена заявления, и её полезно знать заранее: граница переходит
95% на **73 успехах подряд** (замерено `wilson_lower(n, n)`, не выведено из
памяти). Шестьдесят дают 94.0%, сто — 96.3%. То есть цель
«каждый базовый оп выше 95%» — это не столько починка, сколько НАБОР
СВИДЕТЕЛЬСТВ, и набирается он не отдельной кампанией прогонов, а обычной
пересборкой здания: один круг по образцу Snowdon — это 6343 исполнения
операций, каждое со своим постусловием.

КОРПУС ДЕРЖИТ ПРОШЛОЕ, А НЕ НАСТОЯЩЕЕ — ГЛАВНАЯ ЛОВУШКА ЭТОГО ЧИСЛА
------------------------------------------------------------------
Журнал дописывается и никогда не переписывается. Значит частота, посчитанная
по всему корпусу, смешивает поведение ДО починки и ПОСЛЕ неё — и тем ниже,
чем усерднее чинили.

Замерено 31.07, и цена ошибки видна на самом остром примере. Десять живых
отказов `create_beam` («level binding mismatch») датированы 27.07 с 13:05 по
13:22. Коммит, снявший этот свидетель, лёг в 13:23:40 — через 53 секунды
после последнего отказа. Все четыре отказа `create_door` по флипам — 21.07,
починки — 22.07 и 27.07. То есть два класса из трёх, на которые смотрел
разбор, были закрыты ещё до того, как их начали разбирать; в корпусе они
живут только потому, что корпус ничего не забывает.

Отсюда правило: **заголовочное число берётся с ОДНОГО свежего прогона, а не
со всей истории.** `--since` режет корпус по дате; отчёт всегда печатает
границы времени, чтобы «за месяц» нельзя было прочитать как «сейчас».

ОГОВОРКА, КОТОРУЮ ГРАНИЦА НЕ УЧИТЫВАЕТ. Вильсон считает испытания
независимыми. Двести пятьдесят стен одного чанка независимы не полностью:
одна модель, один тип, одна транзакция. Они РАЗНЫЕ вызовы API с раздельными
постусловиями — поэтому считаются раздельно, — но разнообразия в них меньше,
чем в двухстах пятидесяти стенах из разных зданий. Число говорит «на таких
данных оп не падает»; оно не говорит «оп не падает на любых данных». Эту
разницу держать в строке манифеста, а не в голове.

НЕПРИПИСЫВАЕМОЕ, И ЧТО ИЗ НЕГО ВСЁ-ТАКИ ИЗВЛЕКАЕТСЯ
---------------------------------------------------
Строки корпуса, записанные до 31.07, идентификаторов не несут — все 1014
живых. Восстановить их нечем, и инструмент НЕ ВОССТАНАВЛИВАЕТ: восстановленное
число, поданное как измеренное, — ровно тот обман, против которого всё
построено. Но два честных ответа из этих строк добываются без единой догадки,
и печатаются они РАЗНЫМИ разделами, чтобы не могли слиться:

  ОДНА ОПЕРАЦИЯ В ПРОГРАММЕ — если операция в программе одна, вердикт
  программы и есть её вердикт. Приписывание точное, идентификатор не нужен.
  Это ИЗМЕРЕНИЕ, просто по узкой выборке;

  ПРОГРАММНЫЙ УРОВЕНЬ — провал приписан всем операциям программы. Так и
  считалось раньше. Числу нельзя верить как частоте операции, но оно
  осмысленно как НИЖНЯЯ ГРАНИЦА: приписать лишнее эта схема может, пропустить
  чужой провал — нет. «`create_wall` не ниже 64.2%» — утверждение верное;
  равенство было ложью.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import os
import pathlib
import sys

DEFAULT_CORPUS = pathlib.Path(__file__).resolve().parents[1] / "data" / "telemetry" / "kir_witness.jsonl"

BUILT = "built"
BLAMED = "blamed"
COLLATERAL = "collateral"
PROGRAM_FAILED = "program_failed"

_RU = {
    BUILT: "построено",
    BLAMED: "обвинена",
    COLLATERAL: "попутно откачено",
    PROGRAM_FAILED: "программа упала",
}


def wilson_lower(successes: int, total: int, z: float = 1.96) -> float:
    """Нижняя граница доли при 95% доверия. Ноль наблюдений → 0.0."""
    if total <= 0:
        return 0.0
    p = successes / total
    denom = 1.0 + z * z / total
    centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (centre - margin) / denom)


def blamed_ids(row: dict) -> set:
    """Идентификаторы, названные в нарушениях. Форма нарушения — `«<id>: текст»`
    (см. `authoring.py`, `__post.Add(oid + ": …")`). Всё, что не разбирается,
    в обвинение НЕ попадает: клевета дороже пропуска."""
    out = set()
    for v in row.get("violations") or []:
        head = str(v).split(":", 1)[0].strip()
        if head:
            out.add(head)
    return out


def classify(row: dict) -> tuple[list[tuple[str, str]], str | None]:
    """→ (пары «оп, корзина», причина непричисляемости)."""
    ops = row.get("ops") or []
    if not ops:
        return [], "нет операций в строке"
    if any(o.get("id") is None for o in ops if isinstance(o, dict)):
        # Одна безымянная операция обесценивает разбор всей строки: нельзя
        # знать, не ей ли принадлежит нарушение.
        return [], "строка без идентификаторов операций (до 31.07)"

    blamed = blamed_ids(row)
    committed = bool(row.get("ok"))
    pairs = []
    for o in ops:
        if not isinstance(o, dict):
            continue
        name = o.get("op") or "(без имени)"
        if o.get("id") in blamed:
            pairs.append((name, BLAMED))
        elif committed:
            pairs.append((name, BUILT))
        elif blamed:
            pairs.append((name, COLLATERAL))
        else:
            pairs.append((name, PROGRAM_FAILED))
    return pairs, None


def span(rows) -> tuple[str | None, str | None]:
    """Границы времени корпуса. Печатаются ВСЕГДА: «за месяц» не должно
    читаться как «сейчас»."""
    stamps = sorted(str(r.get("ts")) for r in rows if r.get("ts"))
    return (stamps[0][:19], stamps[-1][:19]) if stamps else (None, None)


def tally(rows, *, live_only: bool = True) -> dict:
    per = collections.defaultdict(collections.Counter)
    skipped = collections.Counter()
    seen = considered = 0
    for row in rows:
        seen += 1
        if live_only and not (row.get("duration_ms") or 0) > 0:
            skipped["не доехало до Revit (duration_ms = 0)"] += 1
            continue
        pairs, why = classify(row)
        if why:
            skipped[why] += 1
            continue
        considered += 1
        for name, bucket in pairs:
            per[name][bucket] += 1
    return {"per_op": per, "skipped": skipped,
            "rows_seen": seen, "rows_considered": considered}


def tally_solo(rows, *, live_only: bool = True) -> dict:
    """Точное приписывание БЕЗ идентификаторов: операция в программе одна.

    Годится и для исторических строк. Выборка узкая, зато вердикт не спорный:
    если оп в программе один, провал программы принадлежит ему и никому ещё."""
    per = collections.defaultdict(collections.Counter)
    considered = 0
    for row in rows:
        if live_only and not (row.get("duration_ms") or 0) > 0:
            continue
        ops = [o for o in (row.get("ops") or []) if isinstance(o, dict)]
        if row.get("ops_truncated"):
            continue
        names = {o.get("op") for o in ops}
        if len(names) != 1 or not ops:
            continue
        considered += 1
        name = ops[0].get("op") or "(без имени)"
        per[name][BUILT if row.get("ok") else BLAMED] += 1
    return {"per_op": per, "rows_considered": considered}


def tally_program_level(rows, *, live_only: bool = True) -> dict:
    """Нижняя граница: провал программы приписан КАЖДОЙ её операции."""
    per = collections.defaultdict(collections.Counter)
    considered = 0
    for row in rows:
        if live_only and not (row.get("duration_ms") or 0) > 0:
            continue
        names = {o.get("op") for o in (row.get("ops") or [])
                 if isinstance(o, dict) and o.get("op")}
        if not names:
            continue
        considered += 1
        for name in names:
            per[name][BUILT if row.get("ok") else BLAMED] += 1
    return {"per_op": per, "rows_considered": considered}


def report(res: dict, *, min_runs: int) -> dict:
    rows = []
    for name, c in res["per_op"].items():
        built, blamed = c[BUILT], c[BLAMED]
        judged = built + blamed
        rows.append({
            "op": name,
            "built": built,
            "blamed": blamed,
            "collateral": c[COLLATERAL],
            "program_failed": c[PROGRAM_FAILED],
            "judged": judged,
            "rate": (built / judged) if judged else None,
            "lower95": wilson_lower(built, judged) if judged else None,
            "enough": judged >= min_runs,
        })
    rows.sort(key=lambda r: (r["lower95"] if r["lower95"] is not None else -1.0,
                             r["judged"]))
    return {"ops": rows,
            "rows_seen": res.get("rows_seen"),
            "rows_considered": res["rows_considered"],
            "skipped": dict(res.get("skipped") or {}),
            "min_runs": min_runs}


def render(rep: dict, *, collateral: bool = True) -> str:
    out = []
    out.append(f"Причислено строк: {rep['rows_considered']}"
               + (f" из {rep['rows_seen']}" if rep.get("rows_seen") else ""))
    for why, n in sorted(rep["skipped"].items(), key=lambda kv: -kv[1]):
        out.append(f"  не причислено {n:5}  — {why}")
    out.append("")
    head = f"{'операция':26} {'постр':>6} {'обвин':>6} {'доля':>7} {'ниж.95':>7}"
    out.append(head + (f"  {'попут':>6} {'прогр':>6}" if collateral else ""))
    out.append("-" * (76 if collateral else 62))
    for r in rep["ops"]:
        if r["judged"]:
            rate = f"{100*r['rate']:6.1f}%"
            low = f"{100*r['lower95']:6.1f}%"
            mark = "" if r["enough"] else "  ← мало прогонов"
        else:
            rate = low = "      —"
            mark = "  ← ни одного вердикта"
        line = f"{r['op']:26} {r['built']:6} {r['blamed']:6} {rate} {low}"
        if collateral:
            line += f"  {r['collateral']:6} {r['program_failed']:6}"
        out.append(line + mark)
    out.append("")
    solid = [r for r in rep["ops"]
             if r["enough"] and r["lower95"] is not None and r["lower95"] >= 0.95]
    out.append(f"Опов с НИЖНЕЙ границей выше 95% при ≥{rep['min_runs']} "
               f"вердиктах: {len(solid)}"
               + (" — " + ", ".join(r["op"] for r in solid) if solid else ""))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--min-runs", type=int, default=20,
                    help="сколько вердиктов нужно, чтобы доля вообще о чём-то "
                         "говорила (по умолчанию 20)")
    ap.add_argument("--since", default=None,
                    help="отбросить строки старше этой отметки (префикс ISO, "
                         "напр. 2026-07-31). Заголовочное число берётся с "
                         "ОДНОГО свежего прогона, а не со всей истории — "
                         "корпус дописывается и помнит поведение до починок")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    path = pathlib.Path(args.corpus)
    if not path.exists():
        print(f"корпус не найден: {path}", file=sys.stderr)
        return 2
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    total_before = len(rows)
    if args.since:
        rows = [r for r in rows if str(r.get("ts", "")) >= args.since]
    lo, hi = span(rows)
    exact = report(tally(rows), min_runs=args.min_runs)
    solo = report(tally_solo(rows), min_runs=args.min_runs)
    prog = report(tally_program_level(rows), min_runs=args.min_runs)
    if args.json:
        print(json.dumps({"корпус": {"строк": len(rows), "всего_в_файле": total_before,
                                     "от": lo, "до": hi, "since": args.since},
                          "по_идентификаторам": exact,
                          "одна_операция_в_программе": solo,
                          "программный_уровень_нижняя_граница": prog},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"Корпус: {len(rows)} строк из {total_before}"
          + (f", отсечка --since {args.since}" if args.since else "")
          + f"\nВремя:  {lo} … {hi}")
    if lo and hi and lo[:10] != hi[:10]:
        print("        ВНИМАНИЕ: промежуток охватывает больше одного дня — "
              "значит и правки кода. Частота по такому корпусу смешивает\n"
              "        поведение до починок и после; заголовочное число "
              "берут с одного свежего прогона.")
    print()
    print("=" * 76)
    print("ПО ИДЕНТИФИКАТОРАМ — точное приписывание нарушения операции")
    print("=" * 76)
    print(render(exact))
    print()
    print("=" * 76)
    print("ОДНА ОПЕРАЦИЯ В ПРОГРАММЕ — точное приписывание без идентификаторов")
    print("=" * 76)
    print(render(solo, collateral=False))
    print()
    print("=" * 76)
    print("ПРОГРАММНЫЙ УРОВЕНЬ — НИЖНЯЯ ГРАНИЦА, не частота операции")
    print("=" * 76)
    print(render(prog, collateral=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
