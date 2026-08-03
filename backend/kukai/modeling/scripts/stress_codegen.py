#!/usr/bin/env python3
"""Stress-test ONLY the codegen model (DeepSeek): can it write working complex
parametric Revit C#? Single-shot (no fix-loop) to measure RAW ability. For each
prompt: DeepSeek -> exec (compile+run) -> aim+screenshot. Human (Claude) judges the
PNGs. This closes the #1 vibeCAD risk before building the loop."""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from vibecad_loop import codegen, op_exec, aim_shoot, GROUND_CS, AUTHORIZED

DEVICE = "a6d7d14340bc599817ae7e6896182ca0"
assert DEVICE in AUTHORIZED

PROMPTS = [
    ("simple", "A 3x4 regular grid of square columns (cross-section 500x500 mm), each 7000 mm tall, "
               "with 5000 mm spacing in both directions, the grid origin at x=140000 y=40000 z=0 mm. "
               "Build each column as a DirectShape box. Return all ids."),
    ("medium", "A twisting tower: 16 square floor plates 9000x9000 mm and 250 mm thick, stacked every "
               "3500 mm vertically, each plate rotated 11 degrees more than the one below it about the "
               "tower's vertical centre axis. Centre axis at x=175000 y=40000, base at z=0. DirectShape. Return ids."),
    ("hard",   "A vertical RING / arch (torus segment): a circular tube of cross-section radius 6000 mm "
               "swept along a 300-degree circular arc (radius 30000 mm) lying in a VERTICAL plane, leaving a "
               "60-degree gap at the bottom for two feet. Arc centre at x=220000 y=40000 z=32000 mm. "
               "Build as a DirectShape (segment it into ~50 box pieces along the arc if a clean sweep is hard). Return ids."),
]

ground = json.dumps(op_exec(DEVICE, GROUND_CS), ensure_ascii=False)[:1200]
print("GROUND:", ground[:200], "\n")
results = []
for name, p in PROMPTS:
    print(f"===== {name} =====")
    code = codegen(p, ground, [])
    res = op_exec(DEVICE, code) or {}
    ok = isinstance(res, dict) and not res.get("error")
    ids = res.get("ids") if ok else None
    png = None
    if ok and ids:
        png = aim_shoot(DEVICE, ids, f"/tmp/stress_{name}.png")
    line = {"form": name, "compiled_and_ran": bool(ok), "n_ids": len(ids) if ids else 0,
            "png": png, "detail": (res.get("note") if ok else str(res.get("message") or res.get("error"))[:220]),
            "code_len": len(code)}
    print(json.dumps(line, ensure_ascii=False), "\n")
    results.append(line)
print("SUMMARY:", json.dumps([{k: r[k] for k in ("form","compiled_and_ran","n_ids","png")} for r in results], ensure_ascii=False))
