#!/usr/bin/env python3
"""STAGE-2 BENCH: WHICH SCHEMA SHAPE LETS THE MODEL REACH AN ACCEPTED PROGRAM.

    python tools/mcp_schema_bench.py surface --arm A --work <dir>
    python tools/mcp_schema_bench.py call kir_author <args.json> --work <dir>
    python tools/mcp_schema_bench.py score --work <dir>

TWO ARMS, AND EXACTLY ONE THING TELLS THEM APART — SCHEMA VOLUME:

    A  EXPANDED    the surface as-is: `kir_compile` gets the full
                   program schema (~61 KB with folding into `$defs`)
    B  COLLAPSED   `kir_compile` gets, instead of the schema, a
                   reference "ask `kir_spec`" (~0.3 KB). The dictionary
                   of operations does not disappear anywhere: it is in
                   the tool description and available by name.

The tool descriptions, the task, and the doors are THE SAME for both
arms. Otherwise what would be measured is not the schema's shape but a
difference in tasks.

🔴 THE COUNT IS TAKEN FROM THE JOURNAL ON DISK, NOT FROM THE MODEL'S
WORDS. This rule was paid for dearly, and not here: on this tree an
instrument lied four times in one shift, and each time it was caught
only by a different instrument. A model reporting "I built it" and a
journal where `kir_compile` returned 0/6 are different claims; the
second one is correct.

🔴 WHAT THIS BENCH DOES NOT MEASURE, NAMED BEFORE THE NUMBERS. The
schema reaches the model AS TEXT (via `surface`), not as a tool
declaration, the way the real `tools/list` carries it. The delivery
channel differs, the content is the same. So the bench answers the
question "can the model handle this volume of schema", NOT the question
"does the host deliver it the same way". Only a live client can close
the second question.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from kir.mcp import server, surface  # noqa: E402

#: The task. ONE for both arms, and it is about the BUILDING, not about
#: the language: a wording that hints at ops would measure the reading
#: of a hint.
BRIEF = """\
Построй программу KIR для одноэтажного дома в осях 12 000 × 8 000 мм:

  * один уровень на отметке 0;
  * наружные стены по периметру, высота 3000 мм;
  * две внутренние перегородки, делящие дом на три помещения;
  * плита пола по всему контуру;
  * четыре окна в наружных стенах и одна входная дверь.

Готово, когда `kir_compile` вернул 6/6 зелёных версий.
"""

_COLLAPSED_PROGRAM = {
    "type": "object",
    "description": (
        "Программа KIR (операции JSON). Полная схема НЕ вложена: контракт "
        "нужной операции спрашивается инструментом `kir_spec` по имени."),
}


def _surface_for(arm: str) -> list[dict]:
    tools = [dict(t) for t in surface.tools()]
    if arm == "A":
        return tools
    if arm != "B":
        raise SystemExit(f"рука «{arm}» не заведена: есть A и B")
    for tool in tools:
        props = tool["input_schema"].get("properties") or {}
        if "program" in props and tool["name"] == "kir_compile":
            props = dict(props)
            props["program"] = dict(_COLLAPSED_PROGRAM)
            tool["input_schema"] = dict(tool["input_schema"])
            tool["input_schema"]["properties"] = props
    return tools


#: THE CONTENT THE TASK REQUIRES. A green compile BY ITSELF means
#: nothing: "just a level" compiles 6/6 on both arms. An instrument
#: counting the first green was crediting a hit where there was not yet
#: a house — and this is not a hypothesis: run B1 reported green on a
#: "level + wall" probe, while its full program stayed red. The
#: instrument was right ABOUT A DIFFERENT SUBJECT.
#: 🔴 A KIND, NOT AN OP NAME (review 02.09.2026). It had
#: `"create_floor": 1`, while the task asks for "a floor slab over the
#: whole outline" — and the registry gives TWO equally valid paths for
#: this (`create_floor` and `create_floor_by_contour`). A run that
#: built exactly what was ordered, via the second one, got
#: `built_the_brief: false`: a false red inside the very instrument
#: whose own header demands taking the count from the journal, not
#: from hope.
BRIEF_COMPOSITION: dict[str, tuple[tuple[str, ...], int]] = {
    "уровень": (("create_level",), 1),
    "стены": (("create_wall",), 6),
    "плита": (("create_floor", "create_floor_by_contour"), 1),
    "окна": (("create_window", "place_family"), 4),
    "дверь": (("create_door", "place_family"), 1),
}


def _composition(program: object) -> dict[str, int]:
    out: dict[str, int] = {}
    ops = program.get("ops") if isinstance(program, dict) else None
    for op in ops or []:
        name = op.get("op") if isinstance(op, dict) else None
        if name:
            out[name] = out.get(name, 0) + 1
    return out


def _covers_brief(comp: dict[str, int]) -> bool:
    return all(sum(comp.get(op, 0) for op in ops) >= n
               for ops, n in BRIEF_COMPOSITION.values())


def _journal(work: pathlib.Path) -> pathlib.Path:
    work.mkdir(parents=True, exist_ok=True)
    return work / "journal.jsonl"


def _append(work: pathlib.Path, row: dict) -> None:
    with _journal(work).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def cmd_surface(args: argparse.Namespace) -> int:
    work = pathlib.Path(args.work)
    tools = _surface_for(args.arm)
    payload = json.dumps(tools, ensure_ascii=False, indent=2)
    _append(work, {"t": time.time(), "kind": "surface", "arm": args.arm,
                   "bytes": len(payload)})
    print("=== ЗАДАНИЕ ===")
    print(BRIEF)
    print("=== ПРОЗА О ЯЗЫКЕ (instructions сервера) ===")
    print(surface.instructions())
    print("=== ИНСТРУМЕНТЫ (рука %s) ===" % args.arm)
    print(payload)
    return 0


def cmd_call(args: argparse.Namespace) -> int:
    work = pathlib.Path(args.work)
    payload = json.loads(pathlib.Path(args.args_file).read_text("utf-8"))
    # 🔴 `dispatch` BECAME A COROUTINE (ca83e90), and this call stayed
    # the same as before — meaning the bench that the `ground.py` fix
    # CITED as the source of its numbers stopped running, in that very
    # same commit. Caught by review on 02.09.2026. The lesson is not
    # about `async`: while changing the signature, I fixed TWO calls
    # inside the instruments and did not look for a third one outside
    # them.
    body, crashed = asyncio.run(server.dispatch(args.tool, payload))
    green = None
    comp: dict[str, int] = {}
    causes: list[str] = []
    if args.tool == "kir_compile" and isinstance(body, dict):
        green = (body.get("versions") or {}).get("score")
        comp = _composition(payload.get("program"))
        # 🔴 THE CAUSE OF A COMPILE REFUSAL LIVES IN `per_version`, NOT
        # AT THE TOP, and before 02.09.2026 it did not make it into the
        # journal at all: `err` at the top is empty, and every failed
        # compile looked equally nameless. A measurement that did not
        # record WHY answers only "how many", leaving nothing to
        # investigate with afterward.
        for row in (body.get("per_version") or {}).values():
            for text in (row.get("diagnostics") or [])[:3]:
                code = re.search(r"KIR-[A-Z]{1,2}\d{3}", str(text))
                if code and code.group(0) not in causes:
                    causes.append(code.group(0))
    _append(work, {
        "t": time.time(), "kind": "call", "arm": args.arm, "tool": args.tool,
        "ok": bool(body.get("ok")), "crashed": crashed,
        "err": (body.get("err") or {}).get("code"),
        "ops": body.get("ops"), "score": green,
        "composition": comp, "covers_brief": _covers_brief(comp) if comp else None,
        "causes": causes,
    })
    # The response is printed WHOLE, except for drawings and C#: the
    # model must see the refusal verbatim, and huge bodies have nothing
    # to do with the decision.
    slim = dict(body)
    for sheet in slim.get("sheets") or []:
        sheet.pop("svg", None)
    for row in (slim.get("per_version") or {}).values():
        row.pop("csharp", None)
    print(json.dumps(slim, ensure_ascii=False, indent=2)[:20000])
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    work = pathlib.Path(args.work)
    path = _journal(work)
    rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()
            if line.strip()] if path.exists() else []
    calls = [r for r in rows if r.get("kind") == "call"]
    green_at = None          # any green compile — including a mini-probe
    brief_at = None          # green ON THE TASK, and only this one counts
    # 🔴 A JOURNAL OLDER THAN THE FIELD MEANS "NOT RECORDED", NOT "DID
    # NOT BUILD IT". The `covers_brief` field was introduced on
    # 02.09.2026; runs from before it do not carry it, and printing
    # `built_the_brief: false` for them would mean passing off a lack
    # of data as a finding. The same class of error this bench catches
    # in models — which it then immediately repeated in itself.
    recorded = any("covers_brief" in r for r in calls
                   if r.get("tool") == "kir_compile")
    for i, r in enumerate(calls, 1):
        if r.get("tool") != "kir_compile" or r.get("score") != "6/6":
            continue
        if green_at is None:
            green_at = i
        if r.get("covers_brief") and brief_at is None:
            brief_at = i
    out = {
        "arm": (rows[0].get("arm") if rows else None),
        "built_the_brief": (brief_at is not None) if recorded else None,
        "composition_recorded": recorded,
        "brief_green_at_call": brief_at,
        "any_green_at_call": green_at,
        "calls_total": len(calls),
        "spec_calls": sum(1 for r in calls if r.get("tool") == "kir_spec"),
        "author_calls": sum(1 for r in calls if r.get("tool") == "kir_author"),
        "compile_calls": sum(1 for r in calls if r.get("tool") == "kir_compile"),
        "refusals": sum(1 for r in calls if not r.get("ok")),
        "causes_seen": sorted({c for r in calls for c in (r.get("causes") or [])}),
        "server_crashes": sum(1 for r in calls if r.get("crashed")),
        "surface_bytes": next((r.get("bytes") for r in rows
                               if r.get("kind") == "surface"), None),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # `--work` is declared AT EVERY subcommand, not once at the top: at
    # the top, argparse accepts it ONLY before the subcommand's name,
    # and a call like `surface --arm A --work X` would fail with
    # "required" — a refusal that reads as "forgot the argument", even
    # though the argument was given. The trap cost a run.
    parser = argparse.ArgumentParser(prog="mcp_schema_bench")
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("surface", help="что модель видит")
    s.add_argument("--work", required=True, help="каталог прогона")
    s.add_argument("--arm", required=True, choices=["A", "B"])
    s.set_defaults(func=cmd_surface)

    c = sub.add_parser("call", help="позвать дверь")
    c.add_argument("--work", required=True, help="каталог прогона")
    c.add_argument("tool")
    c.add_argument("args_file")
    c.add_argument("--arm", default="?")
    c.set_defaults(func=cmd_call)

    sc = sub.add_parser("score", help="числа из ЖУРНАЛА")
    sc.add_argument("--work", required=True, help="каталог прогона")
    sc.set_defaults(func=cmd_score)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
