"""Compile a whole persisted building, on every supported Revit version.

The pipeline is end-to-end offline: L0 -> lift -> materialize -> the KIR
compiler -> Roslyn against the real Revit reference assemblies. No Revit, no
bridge, no live document. It answers the question the round trip never did —
would the rebuild of this building even compile, for every customer we ship to.

Grounding no longer needs a live snapshot either: a frozen decompile directory
is self-sufficient. It carries the catalogue of the source model
(``open_model.profile.json``) captured by the same run, and that catalogue —
never a reconstruction — is what the gate grounds against.

Three things this learned the hard way, all worth keeping:

* Materialized chunks are multi-op programs and the compiler refuses those
  unless ``bulk=True``. Without it every single program is rejected KIR-L001,
  which reads like a catastrophe and is a flag.
* The C# must be EMITTED PER VERSION. A first run emitted once (defaulting to
  2026) and sent the same text to all six compilers; it duly "found" 16
  failures of ``Floor.Create`` on 2021 — the exact API divergence the emitter
  already handles correctly at authoring.py's ``if ver >= "2022"``. A gate that
  does not traverse the version branches is testing one surface six times.
* Гейт обязан кормить лифт ТЕМ ЖЕ набором боковых индексов, что живой ход, и
  заземлять ЗАХВАЧЕННЫМ каталогом, а не собственной реконструкцией. Пока он
  делал ни то, ни другое (до 10.08.2026), любое инженерное здание отказывало
  целиком, и отказ выглядел дефектом языка. Замер: ``snowdon_plumb_v3`` —
  тот самый образец Autodesk, что 30.07 живьём собрался 318 программами из
  318, — давал **0 из 156** программо-версий, все 26 программ с ``KIR-G104
  piping_system_types: пусто в модели`` на каждой версии. Подробности и
  опровергающий тест: ``kukai/ir/decompile/tests/test_offline_gate_grounding.py``.

First clean run over демо-v3 (LOT31, 90 758 elements, 51 676 lifted ops):
207 programs, 1 242 program-versions emitted, 1 242 Roslyn checks, 0 failures.
(демо-v3 каталога НЕ несёт — единственное здание корпуса без него, что и
объясняет, почему реконструкция из L0 так долго выглядела достаточной.)

    python tools/compile_gate_offline.py backend/data/decompile/демо-v3
"""

from __future__ import annotations

import argparse
from collections import Counter
import asyncio
import collections
import dataclasses
import json
import pathlib
import textwrap
import time
from typing import Any

from tools.relift_offline import (
    load_document, _load_envelope, _load_side_index)

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")

#: Which snapshot pool a category's types belong to. Anything else is a family
#: symbol, which is what place_family grounds against.
_POOL_BY_CATEGORY = {
    "OST_Walls": "wall_types",
    "OST_Floors": "floor_types",
    "OST_Roofs": "roof_types",
    "OST_Doors": "door_symbols",
    "OST_Windows": "window_symbols",
    "OST_StructuralColumns": "column_symbols_structural",
    "OST_Columns": "column_symbols_architectural",
}


def snapshot_from_l0(document, elements) -> dict[str, list[dict[str, Any]]]:
    """Grounding pools recovered from the frozen L0 itself."""
    pools: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    for element in elements:
        pool = _POOL_BY_CATEGORY.get(element.category, "family_symbols")
        if element.type_id and element.type_name:
            pools[pool][element.type_id] = {
                "id": int(element.type_id), "name": element.type_name}
    snapshot = {name: list(rows.values()) for name, rows in pools.items()}
    snapshot["levels"] = [
        {"id": int(l.id), "name": l.name} for l in document.levels]
    snapshot["grids"] = [
        {"id": int(g.id), "name": g.name} for g in document.grids]
    return snapshot


def gate_snapshot(
    directory: pathlib.Path,
    document=None,
    elements=None,
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Снимок заземления и ИМЯ его источника.

    Каталог модели-источника читает ОБЩАЯ функция
    ``serving.source_catalogue_snapshot`` — та самая, что заведена 28.07
    (``0bdb0cef``) против этого же класса дефекта в двух других местах:
    «сухой гейт rebuild и живые бегуны компилировали БЕЗ снимка модели и
    отказывали целыми чанками с KIR-G103 — сообщая о собственной слепоте, а
    не о программе» (замер тогда: 43 компилируемых опа из 543 против 543).
    Здесь она заводилась в ТРЕТИЙ раз, потому что у гейта была своя копия
    знания, и копия была слабее оригинала: системный тип НЕ ЯВЛЯЕТСЯ
    элементом L0, поэтому пул ``piping_system_types`` из L0 не собрать в
    принципе — сколько бы категорий ни дописали в ``_POOL_BY_CATEGORY``.

    Реконструкция из L0 остаётся ЗАПАСНЫМ путём и обязана быть НАЗВАНА:
    ``демо-v3`` каталога не имеет вовсе, а молчаливая подмена сделала бы
    число гейта несравнимым между зданиями — «207 программ без отказов» на
    здании с каталогом и на здании без него означают разное.
    """
    from kukai.ir.serving import source_catalogue_snapshot

    catalogue = source_catalogue_snapshot(str(directory))
    if not catalogue:
        if document is None or elements is None:
            document, elements = load_document(directory)
        return snapshot_from_l0(document, elements), "L0 (каталога нет)"
    # Оси лежат в ШАПКЕ L0, а не в каталоге пулов, и это тоже захваченные
    # байты, а не догадка: заземление CONTOUR по осям без них отказало бы.
    if "grids" not in catalogue:
        if document is None:
            document, elements = load_document(directory)
        catalogue["grids"] = [
            {"id": int(g.id), "name": g.name} for g in document.grids]
    return catalogue, "open_model.profile.json"


def emit_all(
    directory: pathlib.Path,
    chunk: int,
    *,
    atom_escrow: bool = False,
) -> tuple[list, dict]:
    from kukai.ir.decompile import lift, materialize
    # ЕДИНАЯ точка политики пересборки, а не свой набор флагов.
    # ЗАМЕР 28.07: гейт компилировал с одним `bulk=True`, без
    # `isolation="per_op"`, и потому эмитировал НЕ ТУ программу, которую
    # исполняет живой A5. Живой прогон упал на `CS0103: __pfh_… does not
    # exist in the current context` — шов областей видимости, который
    # появляется ТОЛЬКО в per-op обёртке; гейт этого шва не видел и
    # рапортовал 228/228 без отказов. Ворота обязаны компилировать ровно то,
    # что поедет в модель.
    from kukai.ir.compiler import compile_rebuild_chunk

    document, elements = load_document(directory)
    # ВСЕ семь боковых индексов, ровно как их передаёт `relift_offline.relift`
    # и живой конвейер. Список обязан двигаться вместе с ними: индекс,
    # забытый здесь, не роняет гейт, а ТИХО опускает его на деградированное
    # представление — замер 10.08 на `snowdon_plumb_v3`: без индекса систем
    # 6 343 опа и ни одного с `system_type`, с ним 6 369 и 3 236 с системным
    # типом по имени.
    #
    # `family_placement` читается КОНВЕРТОМ, а не голым словарём: голый терял
    # `failures`, и лифт не мог назвать причину среза из квитанции — все
    # срезанные элементы получали одинаковое «absent from the family
    # placement side index» (та же причина записана в `relift_offline`).
    family_payload = _load_envelope(directory, "family_placement.index.json")
    if family_payload is None:
        family_payload = _load_side_index(
            directory, "family_placement.index.json",
            "family_placement_index")
    result = lift.lift_document_detailed(
        dataclasses.replace(document, elements=elements),
        _load_side_index(directory, "sketch.index.json", "sketch_index"),
        family_payload,
        wall_curve_index=_load_side_index(
            directory, "curve.index.json", "curve_index"),
        curtain_index=_load_envelope(directory, "curtain.index.json"),
        annotation_index=_load_envelope(directory, "annotation.index.json"),
        tag_index=_load_envelope(directory, "tag.index.json"),
        mep_system_index=_load_envelope(directory, "mep_system.index.json"),
    )
    leaves = [n for n in result.nodes if isinstance(n, dict)]
    snapshot, snapshot_source = gate_snapshot(directory, document, elements)
    materialize_kwargs: dict[str, Any] = {"chunk_target": chunk}
    if atom_escrow:
        from kukai.ir.decompile.geom_extract import GeometryExtraction
        geometry_path = directory / "geometry.bundle.json"
        if not geometry_path.is_file():
            raise ValueError(
                "--atom-escrow requires geometry.bundle.json")
        categories_by_id = {
            leaf["source_element_id"]: leaf["category"]
            for leaf in leaves if leaf.get("kind") == "atom"
        }
        materialize_kwargs.update({
            "mode": "escrow",
            "geometry": GeometryExtraction.from_json(
                geometry_path.read_text(encoding="utf-8"),
                categories_by_id=categories_by_id,
            ),
        })
    materialized = materialize.leaves_to_program(
        leaves, **materialize_kwargs)
    programs = materialized.programs
    retained_plans = materialized.plans

    emitted: list[tuple[int, str, str]] = []
    refused: collections.Counter = collections.Counter()
    #: ОТКАЗ — ЭТО ИНТЕРФЕЙС, И ПРИБОР ОБЯЗАН ЕГО СОХРАНЯТЬ (11.08.2026).
    #: Здесь собирался ТОЛЬКО `d.code`, и `field_name`/`message_ru`/`candidates`
    #: — вычисленные компилятором и несущие СЛЕДУЮЩИЙ ХОД — выбрасывались.
    #: На своде из 55 зданий разница между «где-то отказывают» и «отказывают
    #: ЗДЕСЬ и вот почему» есть вся ценность свода; без неё каждую находку
    #: приходится добывать заново отдельным зондом. Замер, стоивший двух
    #: прогонов: `sob62_r23_v6` печатал `('2021', ('KIR-G102',))`, а
    #: компилятор в тот же миг говорил «piping_system_types: несколько
    #: вариантов … уточните через {"by": "element_id", …}» с пятью кандидатами.
    diagnosed: list[tuple[str, Any]] = []
    # СОСТАВ ПРОГРАММЫ, А НЕ ТОЛЬКО ЕЁ НОМЕР. Отказ эмиссии роняет ПРОГРАММУ
    # целиком, а не виновный оп: замерено 13.08.2026 на `k2_ar_rd_v7` — три
    # опа, невыразимых на Revit 2021 (отверстия в перекрытии, потолок), уронили
    # 11 программ из 150. Без состава цена этого считается СРЕДНИМ по
    # программам («порядка 7% здания»), а среднее читается как замер и им не
    # является. С составом она читается точно, и тем же числом доказывается
    # выигрыш, если версионно-хрупкий оп вынести соло (закон Д5, прецедент
    # `create_stairs`).
    def _op_count(prog: Any) -> int:
        """Сколько опов в программе. Спрашиваем ПРОГРАММУ, а не считаем по
        среднему: форма её не гарантирована, поэтому пробуем известные и
        честно возвращаем 0, если не узнали — ноль виден в отчёте, среднее нет."""
        for attr in ("ops", "operations"):
            value = getattr(prog, attr, None)
            if value is not None:
                return len(value)
        if isinstance(prog, dict):
            return len(prog.get("ops") or ())
        return 0

    program_ops = [_op_count(prog) for prog in programs]
    lost_ops: Counter[str] = Counter()
    for index, program in enumerate(programs):
        compile_input = retained_plans[index] or program
        for version in VERSIONS:
            out = compile_rebuild_chunk(compile_input, revit_version=version,
                                        snapshot=snapshot)
            if out.ok:
                emitted.append((index, version, out.csharp))
            else:
                refused[(version, tuple(sorted(
                    {d.code for d in out.diagnostics}))[:2])] += 1
                diagnosed.extend((version, d) for d in out.diagnostics)
                lost_ops[version] += program_ops[index]
    return emitted, {
        "ops": sum(leaf.get("kind") == "op" for leaf in leaves),
        "atoms": sum(leaf.get("kind") == "atom" for leaf in leaves),
        # Число, ради которого забытый индекс перестаёт быть тихим: оп с
        # системным типом ПО ИМЕНИ — единственное, что отличает инженерное
        # здание, которое можно собрать, от того, которое отказывает
        # KIR-G102/G104 целиком.
        "named_system_type_ops": sum(
            "system_type" in (leaf.get("params") or {})
            for leaf in leaves if leaf.get("kind") == "op"),
        "snapshot_source": snapshot_source,
        "atoms_escrowed": materialized.stats.atoms_escrowed,
        "materialize_mode": (
            "escrow" if atom_escrow else "same_document"),
        "programs": len(programs),
        "compiler_ready": materialized.compiler_ready,
        "escrow_evidence": [
            record.as_dict() for record in materialized.escrowed],
        "plan_digests": [
            check.plan_digest for check in materialized.plan_checks],
        "refused": {str(key): value for key, value in refused.items()},
        # ЦЕНА ОТКАЗА В ЭЛЕМЕНТАХ, ПО ВЕРСИЯМ. Решение принимается в опах, а не
        # в программах: одиннадцать программ звучат мелко ровно до тех пор,
        # пока не сказано, сколько опов в них лежало.
        "ops_lost_by_version": dict(lost_ops),
        "ops_per_program": program_ops,
        "refusal_rows": refusal_rows(diagnosed),
    }


def refusal_rows(diagnosed: "list[tuple[str, Any]]") -> list[dict]:
    """Отказы, сведённые ПО ПРИЧИНЕ, с сохранённым следующим ходом.

    Ключ — (код, поле, сообщение), а НЕ (версия, код): один и тот же отказ на
    шести версиях есть ОДНА причина, и шесть строк читались бы как шесть
    находок, раздувая любой рейтинг. Версии при этом не теряются — они едут
    списком, потому что отказ на 2021 и молчание на остальных пяти есть факт о
    ПОКРЫТИИ ВЕРСИЙ (`KIR-E003` на фасаде), а не шум.

    `candidates` сводится к ЧИСЛУ намеренно: их содержимое принадлежит
    конкретному зданию, а строка рейтинга принадлежит причине. Число говорит
    читателю, есть ли у отказа выбор, который может сделать человек.
    """
    rows: dict[tuple, dict] = {}
    for version, diagnostic in diagnosed:
        message = str(getattr(diagnostic, "message_ru", "") or "")
        key = (str(getattr(diagnostic, "code", "")),
               getattr(diagnostic, "field_name", None), message)
        row = rows.get(key)
        if row is None:
            row = rows[key] = {
                "code": key[0], "field": key[1], "message": message,
                "candidates": len(getattr(diagnostic, "candidates", None) or ()),
                "op_id": getattr(diagnostic, "op_id", None),
                "versions": [], "count": 0,
            }
        row["count"] += 1
        if version not in row["versions"]:
            row["versions"].append(str(version))
    for row in rows.values():
        row["versions"].sort()
    return sorted(rows.values(), key=lambda r: (-r["count"], r["code"]))


async def check_all(emitted: list) -> collections.Counter:
    from kukai.compile_client import CompileClient
    from kukai.api import bridge_protocol as BP

    client = CompileClient()
    failures: collections.Counter = collections.Counter()
    started = time.time()
    for done, (_, version, csharp) in enumerate(emitted, start=1):
        wrapped = (BP._WRAPPER_HEADER
                   + textwrap.indent(csharp, "            ")
                   + BP._WRAPPER_FOOTER)
        result = await client.check(wrapped, version)
        if result is None or not result.success:
            errors = (result.errors if result else []) or []
            failures[(version,
                      errors[0].code if errors else "no reply",
                      errors[0].message[:70] if errors else "")] += 1
        if done % 150 == 0:
            print(f"  {done}/{len(emitted)} проверок, "
                  f"{time.time() - started:.0f}с, "
                  f"отказов {sum(failures.values())}", flush=True)
    await client.close()
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("directory", type=pathlib.Path)
    parser.add_argument("--chunk", type=int, default=250,
                        help="ops per materialized program (default 250)")
    parser.add_argument("--json", type=pathlib.Path, default=None)
    parser.add_argument(
        "--atom-escrow", action="store_true",
        help="compile Tier-G atom DirectShape candidates (default off)")
    args = parser.parse_args(argv)

    emitted, stats = emit_all(
        args.directory, args.chunk, atom_escrow=args.atom_escrow)
    print(f"опов: {stats['ops']}  программ: {stats['programs']}")
    print(f"эмиссия: {len(emitted)}/{stats['programs'] * len(VERSIONS)} "
          "(программа×версия)")
    for row in stats["refusal_rows"]:
        versions = ",".join(row["versions"])
        versions = "все 6" if len(row["versions"]) == len(VERSIONS) else versions
        where = f" поле {row['field']}" if row["field"] else ""
        who = f" оп {row['op_id']}" if row["op_id"] else ""
        cands = (f" кандидатов {row['candidates']}"
                 if row["candidates"] else "")
        print(f"   отказ эмиссии {row['count']:>4}  {row['code']} "
              f"[{versions}]{where}{who}{cands}")
        if row["message"]:
            print(f"        {row['message'][:300]}")

    started = time.time()
    failures = asyncio.run(check_all(emitted))
    report = {
        **stats,
        "emitted_program_versions": len(emitted),
        "checks": len(emitted),
        "seconds": round(time.time() - started),
        "failures": sum(failures.values()),
        "by": {str(k): v for k, v in failures.most_common(30)},
    }
    print(f"\nИТОГ: {report['checks']} проверок за {report['seconds']}с, "
          f"отказов {report['failures']}")
    for key, count in failures.most_common(10):
        print(f"   {count:>5}  {key}")

    if args.json is not None:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if (
        report["failures"]
        or stats["refused"]
        or not stats["compiler_ready"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
