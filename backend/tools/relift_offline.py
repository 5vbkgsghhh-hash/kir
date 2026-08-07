"""Lift a persisted decompile run again, offline, with the current compiler.

L0 is the boundary. Everything below it -- lift, fold, canon -- is pure Python
over bytes already on disk, so a whole real building can be re-lifted without
Revit, without the bridge, and without the operator awake. That was true all
along and nobody had a way to do it: every path into the lifter ran through
live extraction, so the only numbers anyone ever quoted came from whichever
run happened to be live at the time.

That is why "100% roundtrip" was measured on 887 of 90 758 elements, and why
place_family was verified on 327 of the 53 791 placements the building
actually contains. Not a missing capability -- a missing measurement.

Point it at a decompile directory (the one holding L0.jsonl) and it reports
what the lifter makes of every element: which ops, which atoms, and why.

    python tools/relift_offline.py backend/data/decompile/демо-v3
    python tools/relift_offline.py <dir> --json out.json
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
from typing import Any


def _load_side_index(directory: pathlib.Path, name: str, key: str) -> Any:
    """A side index, or None when that stage never ran for this document."""
    from kukai.ir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)

    path = directory / name
    if not snapshot_file_exists(path):
        return None
    try:
        payload = json.loads(read_snapshot_text(path))
    except (OSError, ValueError):
        return None
    return payload.get(key, payload) if isinstance(payload, dict) else None


def _load_envelope(directory: pathlib.Path, name: str) -> Any:
    """Весь персистентный конверт индекса (со схемой и квитанциями)."""
    from kukai.ir.decompile.snapshot_io import (
        read_snapshot_text, snapshot_file_exists)

    path = directory / name
    if not snapshot_file_exists(path):
        return None
    try:
        payload = json.loads(read_snapshot_text(path))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


_SIDE_INDEX_FILES = (
    ("curve", "curve.index.json"),
    ("curtain", "curtain.index.json"),
    ("sketch", "sketch.index.json"),
    ("family_placement", "family_placement.index.json"),
    ("group", "group.index.json"),
    # Стадия оформления. Строка добавлена ВМЕСТЕ со стадией и не позже:
    # инструмент без неё показывал бы текстовые примечания атомами при том,
    # что живой конвейер их поднимает, — ровно та слепая зона замера, что
    # уже стоила нам групп (задача #34).
    ("annotation", "annotation.index.json"),
    ("mep_system", "mep_system.index.json"),
)


def _side_receipts(directory: pathlib.Path) -> dict[str, Any]:
    """Агрегат ``failures`` всех пяти боковых индексов, лежащих на диске.

    Читается СЫРОЙ JSON, а не разобранный объект: инструмент обязан работать
    и на разборе, снятом другой версией компилятора, — иначе он перестанет
    отвечать на вопрос «что там намеряли» ровно тогда, когда этот вопрос
    задают (после смены схемы).
    Разбивка СЧИТАЕТСЯ ТЕМ ЖЕ КОДОМ, что и живой прогон
    (:func:`summarize_side_failures`), а не второй его копией. Копия здесь
    была, и разошлась с оригиналом ровно в том месте, ради которого
    инструмент и читают: обе складывали в одно число и срезы, и определения.
    """
    import types

    from kukai.ir.decompile.side_contract import (
        receipts_summary_ru, summarize_side_failures,
    )

    extractions: dict[str, Any] = {}
    for stage, name in _SIDE_INDEX_FILES:
        payload = _load_envelope(directory, name)
        if not isinstance(payload, dict):
            continue
        failures = payload.get("failures")
        if not isinstance(failures, list) or not failures:
            continue
        # Сырые словари, а не разобранные квитанции: файл мог быть снят
        # схемой, которой сегодняшний строгий парсер не знает, и тогда
        # ответить «сколько намеряли» важнее, чем отказать целиком.
        extractions[stage] = types.SimpleNamespace(
            failures=tuple(f for f in failures if isinstance(f, dict)))
    summary = summarize_side_failures(extractions)
    summary["side_cuts_summary_ru"] = receipts_summary_ru(summary)
    return summary


def load_document(directory: pathlib.Path):
    """Rebuild the frozen L0Document from L0.jsonl.

    The header record carries the document metadata; every later record
    carries one element. The two are validated by the real schema, so a file
    this refuses is one the live pipeline would have refused too.
    """
    from kukai.ir.decompile.schema import L0Document, L0Element
    from kukai.ir.decompile.snapshot_io import open_snapshot

    path = directory / "L0.jsonl"
    header: dict[str, Any] | None = None
    elements: list[Any] = []
    # Статусы категорий нужны переписи (§18.1): недобор по категории со
    # статусом partial — это ОТКАЗАВШАЯ СТРАНИЦА, а не «категория прочитана
    # не полностью по неизвестной причине». Различие типизировано, и терять
    # его офлайн значит отдавать инструменту менее точную причину, чем та,
    # которая лежит в том же файле строкой ниже.
    statuses: list[Any] = []
    with open_snapshot(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            kind = row.get("record")
            if kind == "header":
                header = row["document"]
            elif kind == "element":
                elements.append(L0Element.from_dict(row["element"]))
            elif kind == "category_status":
                statuses.append(row["status"])
    if header is None:
        raise SystemExit(f"{path}: no header record — not a frozen L0 file")
    document = L0Document.from_dict({
        **header, "elements": [], "category_status": statuses})
    return document, tuple(elements)


def relift(directory: pathlib.Path) -> dict[str, Any]:
    from kukai.ir.decompile import lift
    import dataclasses

    document, elements = load_document(directory)
    document = dataclasses.replace(document, elements=elements)

    # §18.1: знаменатель. Пока инструмент считал проценты от ЧИСЛА ЭЛЕМЕНТОВ
    # В L0, он мерил долю выборки таблицы категорий, а не долю здания, и
    # молчал о том, чего не смотрели вовсе. Перепись в разборе может
    # отсутствовать (снят до этой волны) — тогда так и печатается, а не
    # подменяется нулём.
    from kukai.ir.decompile.census import reconcile_census
    balance = reconcile_census(document)

    # §18.2: индекс размещений передаётся КОНВЕРТОМ целиком, а не голым
    # словарём строк. Голый словарь терял ``failures``, и лифт не мог назвать
    # причину отказа из квитанции — все срезанные элементы получали одинаковое
    # «absent from the family placement side index».
    family_payload = _load_envelope(directory, "family_placement.index.json")
    if family_payload is None:
        family_payload = _load_side_index(
            directory, "family_placement.index.json",
            "family_placement_index")
    result = lift.lift_document_detailed(
        document,
        _load_side_index(directory, "sketch.index.json", "sketch_index"),
        family_payload,
        wall_curve_index=_load_side_index(
            directory, "curve.index.json", "curve_index"),
        # Индекс витражей передаётся КОНВЕРТОМ: у него есть версия схемы, и
        # разбор, снятый до появления адреса ячейки, обязан читаться как
        # «адреса нет», а не как «ячейка в (0,0)».
        curtain_index=_load_envelope(directory, "curtain.index.json"),
        # Индекс оформления — тоже КОНВЕРТОМ: у него своя версия схемы, и
        # слепок, снятый до стадии, обязан читаться как «индекса нет», то
        # есть давать прежний source_contract_gap дословно.
        annotation_index=_load_envelope(directory, "annotation.index.json"),
        # Индекс марок — КОНВЕРТОМ, как и остальные. Забыть его здесь
        # значит мерить компилятор на деградированном представлении: разбор
        # СО стадией дал бы марки, а офлайновый переподъём того же разбора
        # показал бы source_contract_gap — и это списали бы на лифтер.
        tag_index=_load_envelope(directory, "tag.index.json"),
        mep_system_index=_load_envelope(directory, "mep_system.index.json"),
    )

    # §18.2: квитанции боковых индексов — то, что «мы смотрели и не
    # досмотрели». Без них процент покрытия неотличим от процента умения:
    # стена, чью дугу срезал бюджет, поднимается хордой и идёт в статистику
    # как успех (M5 аудита 28.07).
    receipts = _side_receipts(directory)

    # Раздел документа выводится из СОСТАВА его категорий, а не из имени
    # файла: имя врёт легко (тренировочная копия, «отсоединено», чужой
    # шаблон), состав не врёт. Нужен для того, чтобы число покрытия всегда
    # несло с собой, НА ЧЁМ оно замерено — 27.07 «покрытие стабильно между
    # зданиями» было сказано по двум документам, оба архитектурные, и на
    # первой же не-АР модели утверждение рухнуло.
    from kukai.ir.decompile.extract import _CATEGORY_SPECS
    _disc_of = {c.name: c.discipline for c in _CATEGORY_SPECS}
    disciplines: collections.Counter[str] = collections.Counter()
    for element in elements:
        disciplines[_disc_of.get(element.category, "shared")] += 1

    ops: collections.Counter[str] = collections.Counter()
    atoms: collections.Counter[str] = collections.Counter()
    atom_detail: collections.Counter[str] = collections.Counter()
    # Nodes are plain L1 dicts: an op carries ``op_name``, an atom carries the
    # reason it could not become one.
    for node in getattr(result, "nodes", ()):
        if not isinstance(node, dict):
            continue
        if node.get("kind") == "op":
            ops[str(node.get("op_name") or "?")] += 1
            continue
        # An atom's reason is a NESTED dict ({"code": ..., "detail": ...}), not
        # two sibling keys.  Reading it as siblings left ``atom_details`` empty
        # on every run ever made with this tool while ``atoms`` printed whole
        # stringified dicts — the detail is the only part that names the rule
        # that refused, so pooling reasons across models was impossible.
        raw = node.get("reason")
        if isinstance(raw, dict):
            code = raw.get("code") or raw.get("kind") or "?"
            detail = raw.get("detail") or raw.get("message")
        else:
            code = raw or node.get("code") or node.get("kind")
            detail = node.get("detail") or node.get("message")
        atoms[str(code)] += 1
        if detail:
            atom_detail[str(detail)[:120]] += 1

    total = sum(ops.values()) + sum(atoms.values())
    return {
        "directory": str(directory),
        "doc_name": document.doc_name,
        "disciplines": dict(disciplines.most_common()),
        # Раздел документа = тот, чьих НЕ-общих элементов в нём больше всего.
        # «shared» (уровни, оси, обобщённые модели) исключён намеренно: он
        # есть у всех и потому ничего не различает.
        "discipline": (max(
            ((d, n) for d, n in disciplines.items() if d != "shared"),
            key=lambda item: item[1], default=("shared", 0))[0]),
        "revit_version": document.revit_version,
        "elements": len(elements),
        "lifted_nodes": total,
        "ops": dict(ops.most_common()),
        "op_total": sum(ops.values()),
        "atoms": dict(atoms.most_common()),
        "atom_total": sum(atoms.values()),
        # No cap: a reason that is rare HERE may be the dominant one on the
        # next building, and truncating hides exactly that.
        "atom_details": dict(atom_detail.most_common()),
        "lifted_pct": round(100.0 * sum(ops.values()) / total, 2) if total else 0.0,
        # A generated child is not a gap: a parent family already creates it,
        # and lifting it individually would duplicate geometry.  Leaving those
        # in the denominator understates coverage by whatever share of the
        # building happens to be nested families — 0.1% on one document, 17% on
        # the next — so the honest figure is the only one comparable ACROSS
        # models, which is the only comparison that says anything.
        "generator_children": atoms.get("generator_child", 0),
        "honest_pct": (
            round(100.0 * sum(ops.values())
                  / (total - atoms.get("generator_child", 0)), 2)
            if total - atoms.get("generator_child", 0) > 0 else 0.0),
        # Две базы печатаются рядом намеренно: «от прочитанного» отвечает на
        # вопрос о компиляторе, «от документа» — о здании. Одна вместо другой
        # и есть подмена, которую §18.1 запрещает.
        **balance.to_dict(),
        "census_summary_ru": balance.summary_ru(),
        "document_pct": balance.document_pct(sum(ops.values())),
        **receipts,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=pathlib.Path)
    parser.add_argument("--json", type=pathlib.Path, default=None,
                        help="also write the full report here")
    args = parser.parse_args(argv)

    report = relift(args.directory)

    print(f"{report['doc_name']} (Revit {report['revit_version']})")
    # §18.1: строка переписи стоит ПЕРЕД процентами — знаменатель называется
    # раньше числителя.
    print(f"  перепись:            {report['census_summary_ru']}")
    if report["census_present"]:
        # Печатается ВЕСЬ ``top``, а не срез из него: остаток посчитан от
        # границы top-N, и любой более короткий показ уронил бы строки в
        # щель между показанным и «прочими». Замер: 5 показанных строк при
        # TOP_N=8 прятали 193 элемента, которые не попадали ни туда, ни сюда.
        for row in report["unscanned_by_category"]["top"]:
            print(f"      {row['unscanned']:>8}  {row['category']}"
                  f"  ({row['reason']})")
        if report["unscanned_by_category"]["other_categories"]:
            print(f"      {report['unscanned_by_category']['other_elements']:>8}"
                  f"  прочие "
                  f"{report['unscanned_by_category']['other_categories']}"
                  " категорий")
        if not report["census_balanced"]:
            print(f"  ⚠ ТОЖДЕСТВО НЕ СХОДИТСЯ: "
                  f"{report['census_balance_errors']}")
    # §18.2: строка квитанций стоит между переписью и процентами — «чего не
    # смотрели вовсе», «что смотрели и не досмотрели», и только потом доля.
    print(f"  квитанции срезов:    {report['side_cuts_summary_ru']}")
    if report["side_failures_by_stage"]:
        # По стадиям печатается РАЗБИВКА, а не одна сумма. Пока стояла сумма,
        # ``curtain 14343`` читался как «витражи провалены на 14 тысячах
        # элементов», хотя срезов там 19, а 14 324 — ответы «стена не
        # витражная», у каждого из которых есть ещё и строка индекса.
        cuts_by_stage = report.get("side_cuts_by_stage") or {}
        determined_by_stage = report.get("side_determinations_by_stage") or {}
        detail = ", ".join(
            f"{stage} {cuts_by_stage.get(stage, 0)}"
            f"+{determined_by_stage.get(stage, 0)}отв"
            for stage, _ in sorted(report["side_failures_by_stage"].items()))
        print(f"  квитанций в индексах: {report['side_failures_total']}"
              f"  (срезов+ответов: {detail})")
    print(f"  элементов в L0:      {report['elements']}")
    print(f"  поднято в опы:       {report['op_total']}  "
          f"({report['lifted_pct']}% от прочитанного"
          + (f", {report['document_pct']}% от документа)"
             if report["document_pct"] is not None
             else ", от документа — переписи нет)"))
    print(f"  осталось атомами:    {report['atom_total']}")
    if report["generator_children"]:
        print(f"  из них порождаемых:  {report['generator_children']}"
              f"  ⇒ честное покрытие {report['honest_pct']}%")
    print("\n  опы:")
    for op, count in report["ops"].items():
        print(f"    {count:>8}  {op}")
    if report["atoms"]:
        print("\n  атомы по причине:")
        for reason, count in report["atoms"].items():
            print(f"    {count:>8}  {reason}")
        print("\n  чаще всего:")
        for detail, count in list(report["atom_details"].items())[:8]:
            print(f"    {count:>8}  {detail}")

    if args.json is not None:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nотчёт: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
