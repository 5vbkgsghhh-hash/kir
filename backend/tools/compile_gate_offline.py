"""Compile a whole persisted building, on every supported Revit version.

The pipeline is end-to-end offline: L0 -> lift -> materialize -> the KIR
compiler -> Roslyn against the real Revit reference assemblies. No Revit, no
bridge, no live document. It answers the question the round trip never did —
would the rebuild of this building even compile, for every customer we ship to.

Grounding no longer needs a live snapshot either: the type pools are recovered
from L0's own type_id/type_name distribution, so a frozen decompile directory
is self-sufficient.

Two things this learned the hard way, both worth keeping:

* Materialized chunks are multi-op programs and the compiler refuses those
  unless ``bulk=True``. Without it every single program is rejected KIR-L001,
  which reads like a catastrophe and is a flag.
* The C# must be EMITTED PER VERSION. A first run emitted once (defaulting to
  2026) and sent the same text to all six compilers; it duly "found" 16
  failures of ``Floor.Create`` on 2021 — the exact API divergence the emitter
  already handles correctly at authoring.py's ``if ver >= "2022"``. A gate that
  does not traverse the version branches is testing one surface six times.

First clean run over демо-v3 (LOT31, 90 758 elements, 51 676 lifted ops):
207 programs, 1 242 program-versions emitted, 1 242 Roslyn checks, 0 failures.

    python tools/compile_gate_offline.py backend/data/decompile/демо-v3
"""

from __future__ import annotations

import argparse
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
    result = lift.lift_document_detailed(
        dataclasses.replace(document, elements=elements),
        _load_side_index(directory, "sketch.index.json", "sketch_index"),
        _load_side_index(
            directory, "family_placement.index.json", "family_placement_index"),
        wall_curve_index=_load_side_index(
            directory, "curve.index.json", "curve_index"),
        curtain_index=_load_envelope(directory, "curtain.index.json"),
    )
    leaves = [n for n in result.nodes if isinstance(n, dict)]
    snapshot = snapshot_from_l0(document, elements)
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
    return emitted, {
        "ops": sum(leaf.get("kind") == "op" for leaf in leaves),
        "atoms": sum(leaf.get("kind") == "atom" for leaf in leaves),
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
    }


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
    for key, count in stats["refused"].items():
        print(f"   отказ эмиссии {count:>5}  {key}")

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
