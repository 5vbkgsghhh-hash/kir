🇷🇺 [Русская версия](2026-07-a-building-is-a-program.ru.md)

# A Building Is a Program

**A typed, compilable IR for Autodesk Revit**

---

## 1. The layer that was missing

Language models write code well. They do not write buildings well, and the reason is structural
rather than a matter of training scale.

A building does not fit in a context window: one of the models we measure against holds **90 758
elements**. The work is stateful — a wall must exist before a door can be hosted in it — and the
state lives in an application, not in a file you can diff. It is re-entrant: the same instruction
issued twice must not produce two doors. And it is versioned six ways: the same intent compiles
differently against Revit 2021 and Revit 2026.

So the practice today is to have the model write Revit C# directly, and the arithmetic of that
practice is available to us. Aggregated across four old-server log files we counted **85 374
occurrences of CS error codes** — occurrences, not unique errors, and not deduplicated per pipeline
run. Two codes account for **48.4%** of them — `CS1061` (32.3%) and `CS0117` (16.1%) — and both are
the same failure: *a member of the Revit API that does not exist*. Another ~10% (`CS0104`/`CS0012`)
are namespace and assembly-reference problems. So roughly **60% of that error mass is spent fighting
the surface of an API**, not describing a building. (Source: `PROD_OP_DISTRIBUTION.md`, with that
report's own caveats about log completeness and double-counting.)

**KIR is an attempt to build it**: the model concentrates on
3D, geometry and composition; units, transactions, API versions, hosts, witnesses and rollbacks
belong to a compiler.

## 2. The whole thing in one picture

```
        ┌─────────────┐   typed ops (JSON)   ┌──────────────────────┐
        │   Python    │ ───────────────────► │       KIR            │
        │   brains    │                      │  parse → ground →    │
        │ (numpy,     │ ◄─────────────────── │  typecheck → plan →  │
        │  shapely,   │  typed refusal with  │  emit(per version) → │
        │  the model) │  candidates & route  │  gate → execute      │
        └─────────────┘                      └───────────┬──────────┘
                                                         │ C#, one TransactionGroup
                                                         ▼
   ┌────────────────┐   L0 → L1 → fold → materialize   ┌──────────────┐
   │  typed program │ ◄─────────────────────────────── │  live Revit  │
   │  + typed atoms │        (the reverse spine)       │  2021–2026   │
   └────────────────┘                                  └──────┬───────┘
                                                              │ read-back
                                            witness {geometry_ok,      │
                                                     semantic_ok,      │
                                                     topology_ok} ◄────┘
```

Two properties matter more than the boxes.

**Every call ends in exactly one of two typed outcomes.** Either `{ok, per_op_results, witness}` — a
result carrying a read-back proof — or `{refused, diagnostics}` — a machine-readable refusal with
candidates and a route to a fallback path. A silently-wrong answer is the single forbidden state;
`ok:true` wrapping a nested error is a permanent regression case with its own test.

**The IR runs in both directions.** Forward, a typed program becomes per-version C# that Revit
executes and then reads back. Reverse, a live model is decompiled into the same typed program, and
anything the lifter cannot express becomes a **typed atom with a reason code**, never a silent drop.
The reverse direction is what turns "we can build" into "we can edit what already exists".

Here is a real program, produced by the Python SDK and printed verbatim:

```json
{
  "ir_version": "1.0",
  "intent": "one bay: wall + door + window",
  "ops": [
    {"op": "create_wall", "id": "wall1",
     "p0_mm": [0, 0], "p1_mm": [6000, 0],
     "level": {"by": "name", "value": "Level 1"}, "height_mm": 3300},
    {"op": "create_door", "id": "door1",
     "host": {"by": "ref", "value": "wall1"},
     "offset_mm": 1200, "sill_mm": -100,
     "symbol": {"by": "name", "value": "0915 x 2134mm"},
     "mirrored": false, "hand_flipped": false, "facing_flipped": false}
  ]
}
```

Note what is *not* expressible. A door has no `xyz`: it is `host` + `offset_mm` along the host +
`sill_mm`. "A window floating in the air" is not a case we validate — it is a sentence the language
cannot form. Every length is millimetres; feet do not exist in the IR. Coordinates the model would
have to compute are computed by the compiler.

## 3. Five threads of one solution

### 3.1 Expressiveness and compression

The unit the model writes is not the element. A program envelope holds **20 authored ops** and
expands to at most **320** (`compiler.MAX_OPS_PER_PROGRAM` / `MAX_VALIDATED_OPS`; the macro layer's
own ceiling is 300). Measured today with the Python SDK: one authored `stack` op carrying twelve
columns on a typical floor, stacked over 20 levels with a twist, expands to **260 ops / 240
elements** — one op the model wrote, 260 the compiler will run. Several ops carry a plural operand
of their own (`member_ops`, `placements`, `graph_nodes`/`graph_segments`, `refs_w`), so this is a
property of the language, not of one macro.

```python
import numpy as np
from kukai.ir import sdk

p = sdk.program(intent="tower with a waist")
with p.stack(levels=20, h_mm=3600,
             transform=sdk.transform(scale_xy_top=[0.8, 0.8],
                                     twist_deg_total=24)) as floor:
    for a in np.linspace(0, 2 * np.pi, 12, endpoint=False):
        floor.add(sdk.create_column(xy=[20000 * np.cos(a), 20000 * np.sin(a)],
                                    level=sdk.BY_MACRO, symbol="К 300x300"))

p.stats()   # {'ops_written': 1, 'ops_expanded': 260, 'elements': 240}
out = p.compile(version="2023", snapshot=snap)
```

Two design rules keep this honest. The SDK contains **no hand-written builders** — one Python
function per op is generated from the registry at import time, so a signature cannot drift from the
spec. And the SDK adds **no semantics**: it cannot express anything the registry does not have, and
cannot hide a refusal. Correctness has exactly one owner.

### 3.2 Six versions, one program

`emit` is per-version by construction: the emitter branches (`Floor.Create` vs
`doc.Create.NewFloor`), and an op a version cannot support is a typed `KIR-E-VERSION` refusal rather
than a runtime surprise. Emitting once and grepping the same text against six targets invents
failures that do not exist — we did that, and stopped.

The enforcement is a gate: **every write program in the corpus is compiled against real Revit
reference assemblies for 2021 through 2026**, and since 2026-07-28 in both isolation modes
(whole-program `atomic` and `per_op`). Current state, as the gate runner reports it: **1 056 live
Roslyn compilations, PASS**.
Adding the `per_op` axis immediately surfaced two defects that had lived for weeks — a `CS0136` in
`load_family` and a branch of `in_view` that could never compile — neither visible on the `atomic`
axis.

The gate also taught us to be careful about what a gate proves. **Compiling on six versions and
building in Revit are two different claims** and must never be quoted as one; we keep them in
separate corpora, and re-derive the live one from telemetry rather than memory.

### 3.3 A substrate, not a feature

Once the IR exists, capabilities that would each be a project become endpoints over one substrate.
Four are wired live today: **`/run`** (execute a typed program with witnesses), **`/decompile`** (read
a live model into typed ops plus typed atoms), **`/rebuild`** (build the decompiled program back,
chunked, under host-atomicity laws), and **`/idempotence`** (run the same program twice and prove the
second run adds nothing — op ids are stamped into the model in the same transaction, so a retry is
idempotent and resume-from-op-K is just "skip what is stamped"). A fifth, the **mission bench**
(§3.4), is an offline application of the same compiler used as a judge. None of them needed a new
engine.

## What is measured today

Everything in this table is derived from an instrument on the date shown, not from memory, and every
row has an entry in `docs/articles/publication_manifest.json` giving the commit, the command and the
artifact it can be re-derived from.

| Fact | Value | Date / source |
|---|---|---|
| Writing ops in the committed registry | 31 (+4 query) | 2026-07-28, `spec.OPS` |
| Writing ops with ≥1 successful live run + witness | **31 of 31** | union of `data/telemetry/kir_witness.jsonl` (rows with `ok` + `family=write` + `duration_ms>0`; includes the 2026-07-28 runs P8/P10v2/P11 and the night P9) and the 2026-07-27 live-matrix artifact (adds `create_floor`, `create_room`) |
| Last op to close | `move_elements` — 2026-07-28 night, Revit 2026: a *connected* cable-tray pair moved +500 mm Z, witness 3/3, connection verified alive by an independent read | same |
| Six-version compile gate | **1 056 live Roslyn compilations, PASS** — quoted as the gate runner reports it | 2026-07-28 |
| Test suite, language side | **980 passed / 2 678 subtests** | 2026-07-28, `pytest kukai/ir` |
| Test suite, decompile side | **901 passed / 215 subtests** | 2026-07-28 |
| Categories the reverse direction reads | **48** | 2026-07-28 |
| Coverage, model A (R2023, 1 383 elements) | **93.28%** (raw 77.30%) | 2026-07-27, `coverage_matrix.py` |
| Coverage, model B (R2026, 90 758 elements) | **92.83%** (raw 56.94%) | 2026-07-27 |
| Production CS-code occurrences fought over API surface | **≈60%** of 85 374 occurrences | `PROD_OP_DISTRIBUTION.md` |

## Open-core, and what we want from you

**The framework goes open-source on August 9, 2026.** That is a plan statement — a commitment to a
date, not a result already achieved. What ships is the compiler core: the registry, the schema and
grammar generators, the staged pipeline, the per-version emitters, the witness machinery, the
decompile spine, and the specs that govern them (`SPEC_V1.md`, `KIR_DECOMPILE_SPEC.md`) — which, as
of 2026-07-28, finally live inside the repository rather than beside it.

Three things we would genuinely like from anyone who reads the code:

1. **Break a witness.** Find an op whose postcondition passes while Revit did something else. That is
   the highest-value bug in this system, and the reason every check now has to name the axis it reads.
2. **Run the reverse direction on a building we have never seen.** Coverage on our own models is a
   number about us. Coverage on yours is a number about the compiler — and every refusal is written
   to a queue that decides what the language learns next.
3. **Argue with a bound.** Every numeric bound in the registry that was authored by reasoning instead
   of measurement is a future silent atom. If one is wrong for your projects, we would rather learn
   it from your model than from ours.

We will keep publishing the numbers that go down. A building is a program — and a program you cannot
verify is just a very expensive suggestion.

---

*KIR is developed inside KUKAI. Live writing is gated to devices on an operator's allow-list; the
compiler itself contains no device ids, install paths or localised category keys — that is a lint,
not a promise.*
