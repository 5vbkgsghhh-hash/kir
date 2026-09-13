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
* The gate must feed the lift the SAME set of side indexes as the live path,
  and must ground against the CAPTURED catalogue, not its own reconstruction.
  While it did neither (before 2026-08-10), any engineering building refused
  outright, and the refusal looked like a defect in the language. Measured:
  ``snowdon_plumb_v3`` — the very Autodesk sample that assembled live, 318 of
  318 programs, on 07-30 — gave **0 of 156** program-versions, all 26
  programs with ``KIR-G104 piping_system_types: empty in the model`` on every
  version. Details and the refuting test:
  ``kukai/ir/decompile/tests/test_offline_gate_grounding.py``.

First clean run over демо-v3 (LOT31, 90 758 elements, 51 676 lifted ops):
207 programs, 1 242 program-versions emitted, 1 242 Roslyn checks, 0 failures.
(демо-v3 carries NO catalogue — the one building in the corpus without one,
which is exactly why reconstruction from L0 looked sufficient for so long.)

    python tools/compile_gate_offline.py backend/data/decompile/демо-v3
"""

from __future__ import annotations

import argparse
from collections import Counter
import asyncio
import collections
import dataclasses
import inspect
import json
import pathlib
import textwrap
import time
from typing import Any

from kir.registry_base import REVIT_VERSIONS
from kir.instruments.relift_offline import (
    IncompleteSnapshot, load_document, side_indexes_for,
    _load_envelope, _load_side_index)

#: 🔴 DERIVED FROM THE AUTHORITY, NOT COPIED OUT BY HAND (2026-09-01) — the
#: same reasoning as in `compile_client`: one set of six for the whole tree,
#: or a divergence will only show up on someone else's Revit version.
VERSIONS = REVIT_VERSIONS

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
    """The grounding snapshot and the NAME of its source.

    The source model's catalogue is read by the SHARED function
    ``serving.source_catalogue_snapshot`` — the very one set up on 07-28
    (``0bdb0cef``) against this same class of defect in two other places:
    "the dry rebuild gate and the live runners compiled WITHOUT a model
    snapshot and refused whole chunks with KIR-G103 — reporting their own
    blindness rather than the program" (measured then: 43 compilable ops out
    of 543 against 543). Here it was set up for the THIRD time, because the
    gate had its own copy of the knowledge, and the copy was weaker than the
    original: a system type is NOT an L0 element, so the ``piping_system_types``
    pool cannot be assembled from L0 in principle — no matter how many
    categories get added to ``_POOL_BY_CATEGORY``.

    Reconstruction from L0 remains a FALLBACK path and must be NAMED:
    ``демо-v3`` has no catalogue at all, and a silent substitution would make
    the gate's number incomparable between buildings — "207 programs, no
    refusals" means different things on a building with a catalogue and on
    one without.
    """
    from kir.serving import source_catalogue_snapshot

    catalogue = source_catalogue_snapshot(str(directory))
    if not catalogue:
        if document is None or elements is None:
            document, elements = load_document(directory)
        return snapshot_from_l0(document, elements), "L0 (каталога нет)"
    # Grids live in L0's HEADER, not in the pool catalogue, and these too are
    # captured bytes, not a guess: CONTOUR grounding by grids would refuse without them.
    if "grids" not in catalogue:
        if document is None:
            document, elements = load_document(directory)
        catalogue["grids"] = [
            {"id": int(g.id), "name": g.name} for g in document.grids]
    return catalogue, "open_model.profile.json"


class _FeedCaptured(Exception):
    """The feed is caught — there is nothing further to count, compilation is not run."""

    def __init__(self, got: dict):
        super().__init__("feed captured")
        self.got = got


def verify_feed(directory: pathlib.Path) -> dict:
    """WHAT ACTUALLY REACHED `lift_document_detailed` on this decompile.

    🔴 A PROBE ON THE PATH, NOT ON THE SPELLING OF THE CALL (2026-08-30). Set
    up after a defect in SOMEONE ELSE'S probe, and the defect is worth naming
    because it is a named class: a probe from the F-303/F-304 package looked
    in the gate's SOURCE for the literal `name=` and treated anything not
    found in that exact form as not passed. After the F-304 fix
    (`lift.lift_document_detailed(..., **feed)`) there were no more literals,
    and the probe declared all ten NOT PASSED — including `group_index`,
    which the very line above puts into `feed` by hand in that same source.
    The probe was lying in plain sight of its own output: it was aimed at the
    HELPER (the spelling of the write), not at the PATH (what actually gets through).

    Here the path is what is asked: the real call is intercepted, positional
    arguments are mapped to names BY THE SIGNATURE (otherwise the probe would
    start lying the exact same way it was written to catch), and the feed is
    read off from what actually arrived. The spelling of the call can change
    freely — the answer does not move.

    Compilation is NOT RUN: as soon as the feed is caught, the walk stops —
    the question here is about the feed, not about the compiler, and there
    is no reason to pay minutes for it.
    """
    from kir.decompile import lift

    accepted = set(inspect.signature(
        lift.lift_document_detailed).parameters) - {"document"}
    names = [p for p in inspect.signature(
        lift.lift_document_detailed).parameters if p != "document"]
    original = lift.lift_document_detailed

    def spy(document, *args, **kw):
        got = dict(zip(names, args))
        got.update(kw)
        raise _FeedCaptured(got)

    lift.lift_document_detailed = spy
    refused = None
    try:
        _emitted, stats = emit_all(directory, 250)
    except _FeedCaptured as caught:
        got = caught.got
    else:
        # 🔴 IT NEVER GOT TO THE LIFT — AND THAT IS A DIFFERENT ANSWER, NOT "THE
        # FEED IS EMPTY". The gate rejects an incompletely-read snapshot
        # BEFORE feeding it (F-303), and without this distinction the probe
        # would print "10 failed to arrive" — a truth about delivery, read as
        # a verdict on the FEED. Exactly the defect it was written against,
        # only committed by itself.
        got = {}
        refused = stats.get("snapshot_refused")
    finally:
        lift.lift_document_detailed = original

    return {"accepted": sorted(accepted), "delivered": sorted(got),
            "missing": [] if refused else sorted(accepted - set(got)),
            "non_empty": sorted(k for k, v in got.items() if v is not None),
            "snapshot_refused": refused}


def emit_all(
    directory: pathlib.Path,
    chunk: int,
    *,
    atom_escrow: bool = False,
) -> tuple[list, dict]:
    from kir.decompile import lift, materialize
    # THE ONE policy point for rebuild, not its own set of flags.
    # MEASURED 07-28: the gate compiled with `bulk=True` alone, without
    # `isolation="per_op"`, and so emitted THE WRONG PROGRAM — not the one
    # live A5 executes. The live run failed with `CS0103: __pfh_… does not
    # exist in the current context` — a scoping seam that appears ONLY in the
    # per-op wrapper; the gate never saw that seam and reported 228/228 with
    # no failures. The gate must compile exactly what will go into the model.
    from kir.compiler import compile_rebuild_chunk

    # 🔴 THE GATE JUDGES THE COMPILER BY THE BUILDING, WHICH MEANS IT MUST ASK
    # WHETHER THE BUILDING IS WHOLE (F-303, 2026-08-30). The `load_document`
    # reader is LENIENT by default and stays that way: it is used to fix
    # broken decompiles, and a reader that refuses to look at broken input is
    # useless exactly when it is needed. But HERE A VERDICT is being handed
    # down, and on an incompletely-read snapshot "zero refusals" is a
    # statement about OUR OWN READING, passed off as a statement about the compiler.
    #
    # Measured against the live corpus, 2026-08-30: 81 headers, 77 footers.
    # Four genuine buildings sit incompletely read, and on all four the live
    # pipeline's canonical reader (`extract.L0JSONLReader`) REFUSES, while the
    # gate reported success: `k4_geom_wave_15aug` passed as 993 elements,
    # `k2_ar_rd_v4` as 18,489, `sklnk_eom_r26_v3` as 1,937.
    #
    # The fallback path `gate_snapshot` is DELIBERATELY left lenient: it does
    # not judge, it fills out the catalogue, and demanding a footer there
    # would strip the gate of its ability to work on a building with no
    # source catalogue at all.
    try:
        document, elements = load_document(directory, require_committed=True)
    except IncompleteSnapshot as exc:
        # `compiler_ready=False` here means NOT "the compiler is not ready"
        # but "there is nothing to judge by", and `snapshot_refused` must
        # travel RIGHT ALONSIDE it: collapsing them into one flag would mean
        # blaming the compiler for our own reading — the same mistake being
        # fixed, only with the sign flipped.
        return [], {"ops": 0, "programs": 0, "refused": {},
                    "compiler_ready": False,
                    "snapshot_refused": str(exc),
                    "refusal_rows": []}
    # 🔴 THE FEED'S COMPOSITION IS NO LONGER ASSEMBLED HERE BY HAND (F-304, 2026-08-30).
    #
    # There used to be a hand-written list of SEVEN indexes here and a
    # comment asserting "ALL seven side indexes, exactly as passed by
    # `relift_offline.relift` and the live pipeline". Both assertions were
    # false: `relift_offline` supplied eight, `orchestrator.decompile` ten,
    # and this very comment itself named the cost of the miss — "an index
    # forgotten here does not fail the gate, it SILENTLY drops it to a
    # degraded representation" (measured 08-10 on `snowdon_plumb_v3`: without
    # the systems index, 6,343 ops and none with `system_type`; with it,
    # 6,369 and 3,236 with a named system type).
    #
    # The reach of the miss, measured against the live corpus on 2026-08-30
    # (81 decompiles with L0): `group.index.json` is present for 67
    # decompiles, `dimension.index.json` for 10, `join.index.json` for 7.
    # Sixty-seven buildings out of eighty-one were judged by the gate on a
    # representation in which `create_group` operations could not appear at all.
    #
    # Adding three more names here would mean setting up a FOURTH
    # hand-written list that falls behind tomorrow. The composition lives in
    # `side_indexes_for`, and completeness is held by the agreement
    # `состав_подачи_лифту_полон` — by a number, not by attention.
    feed = side_indexes_for(directory)
    # Parsing is the caller's responsibility, and this is written into the
    # feed's docstring: the lift needs `group_index` already parsed, and the
    # composed feed does not do that.
    from kir.decompile.group_extract import parse_group_index
    feed["group_index"] = parse_group_index(feed["group_index"])
    result = lift.lift_document_detailed(
        dataclasses.replace(document, elements=elements), **feed)
    leaves = [n for n in result.nodes if isinstance(n, dict)]
    snapshot, snapshot_source = gate_snapshot(directory, document, elements)
    # 🔴 `joins` — ANOTHER HAND-WRITTEN LIST OF THE SAME KIND (F-304).
    # `leaves_to_program` accepts `joins`, the gate was not passing it, and
    # folding judged joints by their absence. The index has already been read
    # by the feed above — it is not read from disk a second time.
    materialize_kwargs: dict[str, Any] = {"chunk_target": chunk,
                                          "joins": feed["join_index"]}
    if atom_escrow:
        from kir.decompile.geom_extract import GeometryExtraction
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
    #: A REFUSAL IS AN INTERFACE, AND THE INSTRUMENT MUST PRESERVE IT
    #: (2026-08-11). Only `d.code` used to be collected here, and
    #: `field_name`/`message_ru`/`candidates` — computed by the compiler and
    #: carrying the NEXT MOVE — were discarded. Across a corpus of 55
    #: buildings, the difference between "something refuses somewhere" and
    #: "refuses HERE and here is why" is the whole value of the corpus;
    #: without it every finding has to be dug up again with a separate probe.
    #: A measurement that cost two runs: `sob62_r23_v6` printed
    #: `('2021', ('KIR-G102',))`, while the compiler, at that very moment,
    #: was saying "piping_system_types: several options … clarify via
    #: {"by": "element_id", …}" with five candidates.
    diagnosed: list[tuple[str, Any]] = []
    # THE PROGRAM'S COMPOSITION, NOT JUST ITS NUMBER. An emission refusal
    # drops the WHOLE PROGRAM, not the offending op: measured 2026-08-13 on
    # `k2_ar_rd_v7` — three ops not expressible on Revit 2021 (floor
    # openings, a ceiling) dropped 11 programs out of 150. Without the
    # composition, this cost is counted as an AVERAGE over programs ("roughly
    # 7% of the building"), and an average reads like a measurement while not
    # being one. With the composition it reads exactly, and the same number
    # proves the payoff of pulling a version-fragile op out solo (law Д5,
    # precedent `create_stairs`).
    def _op_count(prog: Any) -> int:
        """How many ops are in the program. We ASK THE PROGRAM rather than
        count by average: its shape is not guaranteed, so we try the known
        ones and honestly return 0 if we could not tell — a zero is visible
        in the report, an average is not."""
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
        # The number for whose sake a forgotten index stops being silent: an
        # op with a system type NAMED BY NAME is the one thing that tells
        # apart an engineering building that can be assembled from one that
        # refuses outright with KIR-G102/G104.
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
        # THE COST OF A REFUSAL IN ELEMENTS, BY VERSION. The decision is made
        # in ops, not in programs: eleven programs sound minor for exactly as
        # long as nobody says how many ops were inside them.
        "ops_lost_by_version": dict(lost_ops),
        "ops_per_program": program_ops,
        "refusal_rows": refusal_rows(diagnosed),
    }


def refusal_rows(diagnosed: "list[tuple[str, Any]]") -> list[dict]:
    """Refusals folded BY REASON, with the next move preserved.

    The key is (code, field, message), NOT (version, code): the same refusal
    on six versions is ONE reason, and six rows would read as six findings,
    inflating any ranking. Versions are not lost in the process — they travel
    as a list, because a refusal on 2021 with silence on the other five is a
    fact about VERSION COVERAGE (`KIR-E003` on the facade), not noise.

    `candidates` is deliberately folded down to A NUMBER: their content
    belongs to a specific building, while a ranking row belongs to the
    reason. The number tells the reader whether the refusal offers a choice a
    human could make.
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
    from kir.compile_client import CompileClient
    # 2026-08-27: this instrument's only product touchpoint goes through the port.
    from kir import ports as _п
    BP = _п.need(_п.BRIDGE_PROTOCOL)

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
        "--verify-feed", action="store_true",
        help="что РЕАЛЬНО доезжает до лифта на этом разборе, и выйти; "
             "спрашивает ПУТЬ исполнением, а не форму записи грепом")
    parser.add_argument(
        "--atom-escrow", action="store_true",
        help="compile Tier-G atom DirectShape candidates (default off)")
    args = parser.parse_args(argv)

    if args.verify_feed:
        feed = verify_feed(args.directory)
        if feed["snapshot_refused"]:
            print(f"🔴 СОСТАВ НЕ ЗАМЕРЕН: до лифта дело не дошло — "
                  f"{feed['snapshot_refused']}")
            print("   Это ответ о СЛЕПКЕ, а не о составе подачи.")
            return 2
        print(f"лифт принимает:  {len(feed['accepted'])}")
        print(f"РЕАЛЬНО ДОЕХАЛО: {len(feed['delivered'])}  "
              f"{', '.join(feed['delivered'])}")
        print(f"НЕ ДОЕХАЛО:      {', '.join(feed['missing']) or '—'}")
        print(f"непустых на этом разборе: "
              f"{', '.join(feed['non_empty']) or '—'}")
        return 1 if feed["missing"] else 0

    emitted, stats = emit_all(
        args.directory, args.chunk, atom_escrow=args.atom_escrow)
    # 🔴 A SNAPSHOT REFUSAL IS PRINTED FIRST, BEFORE THE NUMBERS (F-303). The
    # same convention as `relift_offline.main` and
    # `bounds_audit.print_measurement`: the reader is stopped by the HEADER,
    # not by a footnote under the table. On such a decompile the numbers
    # below read "0 ops, 0 programs", and without the reason they would read
    # as "the building is empty". Return code 2, not 1: `1` already means
    # "the gate judged and found refusals", `2` means "the gate DID NOT
    # JUDGE", and the next move differs.
    if stats.get("snapshot_refused"):
        print(f"🔴 СУДИТЬ НЕ ПО ЧЕМУ: {stats['snapshot_refused']}")
        print("   Ворота НЕ вынесли суждения о компиляторе: покраснели ВОРОТА, "
              "а не компилятор.")
        return 2
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
