#!/usr/bin/env python3
"""Offline compile matrix for emitted C# OUTSIDE kukai/audit/.

`scripts/audit_rules_compile_matrix.py` proves one subsystem's C# compiles on
every Revit we support. It is hard-wired to `kukai/audit/rules/*.py` because
that is where the 2026 blindness was found. The class of defect is not confined
there: any module that hands C# to `bridge_callback("execute", …)` is dispatched
RAW — no `RevitCodeFixer`, no version rewrite, no repair loop — so a member
Autodesk added or removed in some year is a COMPILE failure, i.e. the capability
is simply absent on those Revits.

`tests/emitted_csharp_api_scan.py` finds such members by NAME against the trap
index. That is a necessary check and a cheap one, but it reasons about text. It
cannot tell you that the replacement you wrote actually compiles — only a
compiler can, and only against the real assemblies. This file is that half.

Both halves are needed and neither substitutes for the other:
    scan   — "we NAME a member that does not exist on 2021"   (text, instant)
    matrix — "the whole snippet BUILDS on all six"            (Roslyn, ~1s/cell)

WHAT IS COMPILED
----------------
The REAL production strings, imported from the module under test — not copies,
not approximations. A matrix over a transcribed snippet proves something about
the transcription. Each body is wrapped with `wrap_user_code`, the pipeline's
canonical wrapper, which the docstring of the audit matrix records as
byte-identical to what the bridge's TemplateRenderer builds.

`norm_control` exposes its C# as module constants and is imported directly. The
family handlers do not: they interpolate f-strings from tool arguments and hand
the result straight to `_dispatch_code`, so the only place the finished string
exists is the bridge call. It is captured THERE — a fake `bridge_callback` that
keeps `params["code"]` — rather than transcribed, because a matrix over a
transcription proves something about the transcription. The arguments are
shape-bearing only; what is compiled is the template.

WHAT THIS CATCHES THAT THE SCAN CANNOT
--------------------------------------
Both defects found on 2026-08-03 that the scan is structurally blind to:
  * `new ElementId((long)x)` — CS1503 on 2021-2023, because the `long` overload
    is 2024+ and it binds to `ElementId(BuiltInParameter)` before then. A
    constructor has no member name for the index to resolve.
  * dead capabilities that are not a version question at all — a template
    naming an API that exists on NO version fails all six cells at once, which
    reads very differently from a version hole and is worth just as much.

WHAT IS COVERED (four suites; add a suite rather than widening one)
-------------------------------------------------------------------
    norm_control      kukai/norm_control.py — 6 category extractors
    family            kukai/llm/tool_handlers/family_tools.py + family_codecad
    model_snapshot    kukai/query/model_snapshot.py — census + relations
    write_operations  kukai/write/operations.py — the apply_revit_write templates

COVERAGE IS THE WHOLE GAME, and it is not what anyone assumes. Two rules learned
the hard way on 2026-08-03, both of which cost a false alarm before they were
written down:

  "NOT MENTIONED" IS NOT "NOT COVERED". An instrument can take its input by
  IMPORT rather than by name — `kukai/ir/gate_runner.py` compiles every program
  in `kukai.ir.tests.test_golden.PROGRAMS`, so grepping gate_runner.py for a
  op name honestly returns zero while the coverage is real and green. It also
  has a SECOND input source, its own hand-written programs, and checking only
  one of the two is how a covered thing gets reported as a gap. Enumerate every
  input source of an instrument before calling anything uncovered.

  A SYMMETRIC FAILURE IS USUALLY YOUR ARGUMENT, NOT THEIR BUG. Red on all six at
  once means the text does not compile ANYWHERE, which is far more often a
  fragment rendered without its context or an argument in the wrong vocabulary
  than a real dead capability. Asymmetric red — some versions green, some not —
  is the version mine. Check the arguments before raising a defect on symmetric
  red; both `curtain_cell_address_cs` (a helper FRAGMENT, CS0161 standalone, and
  compiled properly in whole programs by gate_runner) and
  `generate_create_schedule_code("Walls")` (wants the `OST_Walls` token) looked
  exactly like dead capabilities and were neither.

Usage:
    venv/bin/python3.12 scripts/emitted_csharp_compile_matrix.py
    venv/bin/python3.12 scripts/emitted_csharp_compile_matrix.py --only norm_control
Exit 0 = every cell compiled. No Revit, no bridge, no model — pure offline proof.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kukai.llm.revit_execution_pipeline import wrap_user_code  # noqa: E402

COMPILE_URL = "http://localhost:52412/compile"
VERSIONS = ["2021", "2022", "2023", "2024", "2025", "2026"]


# ── suites ───────────────────────────────────────────────────────────────────

def suite_norm_control(version: str) -> dict[str, str]:
    """The six per-category extractors, imported live.

    `kukai/norm_tree.py:run_tree_audit` sends each of these to
    `bridge_call("execute", …)` verbatim, one compilation per category. This is
    the deterministic norm-control path — no model in the loop — so a snippet
    that will not build has nothing to repair it and the category is reported as
    "не удалось извлечь".

    Version-independent: these are module constants, the same text everywhere.
    The parameter is part of the suite contract (see `run_suite`), not used.
    """
    from kukai.norm_control import _CAT_EXTRACTORS
    return dict(_CAT_EXTRACTORS)


#: Arguments that drive each family tool down its C#-emitting path. The values
#: are shape-bearing, not meaningful: what is compiled is the TEMPLATE, and the
#: template is the same whatever the numbers say.
_RECT = [{"type": "line", "p1": [0, 0], "p2": [450, 0]},
         {"type": "line", "p1": [450, 0], "p2": [450, 450]},
         {"type": "line", "p1": [450, 450], "p2": [0, 450]},
         {"type": "line", "p1": [0, 450], "p2": [0, 0]}]
_TRI = [[0, 0], [100, 0], [100, 100]]

_FAMILY_ARGS: dict[str, dict] = {
    "family_add_parameter": {"name": "Width"},
    "family_new_type": {"name": "T1", "param_values": {"Width": 450.0}},
    "family_extrude": {},
    "family_cylinder": {},
    "family_void_cut": {"shape": "circle"},
    "family_extrude_polygon": {"points_mm": _TRI},
    "family_blend": {"bottom_points_mm": _TRI,
                     "top_points_mm": [[10, 10], [90, 10], [90, 90]]},
    "family_revolve": {"profile_points_mm": [[0, 0], [100, 0], [100, 200]]},
    "family_delete_element": {"element_id": 555},
    "family_move_element": {"element_id": 555, "dx_mm": 10},
    "family_create_reference_plane": {"name": "Left"},
    "family_regenerate": {},
    "family_create_dimension": {"ref_plane_id_a": 111, "ref_plane_id_b": 222,
                                "family_param_name": "Width"},
    # family_set_parameter_value renders a DIFFERENT statement per value shape —
    # the branch is chosen in Python, so one sample proves one branch and no
    # more. All four are here because the shape that was broken for the whole
    # life of the tool (a C# `switch` with every case rendered from the same
    # literal) is exactly the shape a single sample cannot see.
    "family_set_parameter_value": {"param_name": "Width", "value": 450.0},
    "family_set_parameter_value:int": {"param_name": "Count", "value": 3},
    "family_set_parameter_value:bool": {"param_name": "Visible", "value": True},
    "family_set_parameter_value:str": {"param_name": "Mark", "value": 'A"1'},
    # Likewise family_add_parameter: the spec/group constants it interpolates
    # have four different version windows between them, and the DEFAULT pair
    # (Length + Dimensions) is the only one that is all-six on the modern side.
    # A single default sample would miss every 2021 hole in the other nine.
    "family_add_parameter:yesno": {"name": "Flag", "spec_type": "YesNo",
                                   "group": "Visibility"},
    "family_add_parameter:text": {"name": "Note", "spec_type": "Text",
                                  "group": "Identity"},
    "family_add_parameter:material": {"name": "Mat", "spec_type": "Material",
                                      "group": "Materials"},
    "family_add_parameter:integer": {"name": "N", "spec_type": "Integer",
                                     "group": "Constraints"},
    # V3 unified extrude — in HANDLERS since V3 and never in this matrix.
    "family_extrude_advanced": {
        "profile": {"outer_loop": [
            {"type": "line", "p1": [0, 0], "p2": [450, 0]},
            {"type": "line", "p1": [450, 0], "p2": [450, 450]},
            {"type": "line", "p1": [450, 450], "p2": [0, 450]},
            {"type": "line", "p1": [0, 450], "p2": [0, 0]}]},
        "depth_mm": 100.0, "is_solid": True, "subcategory": "Seat"},
    "family_extrude_advanced:arc_hole": {
        "profile": {"outer_loop": [
            {"type": "line", "p1": [0, 0], "p2": [450, 0]},
            {"type": "line", "p1": [450, 0], "p2": [450, 450]},
            {"type": "line", "p1": [450, 450], "p2": [0, 450]},
            {"type": "line", "p1": [0, 450], "p2": [0, 0]}],
            "inner_loops": [[
                {"type": "arc", "center": [225, 225], "radius": 50,
                 "start_deg": 0, "end_deg": 180},
                {"type": "arc", "center": [225, 225], "radius": 50,
                 "start_deg": 180, "end_deg": 360}]]},
        "sketch_plane": {"origin_mm": [0, 0, 0], "normal": [0, 0, 1]},
        "depth_mm": 100.0, "is_solid": False},
    "family_assign_material": {"material_name": "Steel"},
    "family_create_subcategory": {"name": "Seat"},
    "family_set_visibility": {"element_id": 555},
    "family_create_model_lines": {"lines_mm": [[[0, 0, 0], [100, 0, 0]]]},
    "family_create_symbolic_lines": {"lines_mm": [[[0, 0, 0], [100, 0, 0]]]},
    "family_create_array": {"source_element_ids": [123], "array_type": "radial",
                            "count": 6},
    "family_create_array_linear": {"source_element_ids": [123],
                                   "array_type": "linear", "count": 4,
                                   "translation_step_mm": [100, 0, 0]},
    "family_sweep": {"path_curves": [{"type": "line", "p1": [0, 0],
                                      "p2": [1000, 0]}],
                     "profile_loop": _RECT},
    "family_swept_blend": {"path_curve": {"type": "line", "p1": [0, 0],
                                          "p2": [1000, 0]},
                           "start_profile": _RECT, "end_profile": _RECT},
    "family_create_alignment": {"anchor": {"type": "reference_plane", "id": 111},
                                "target": {"type": "extrusion_face",
                                           "element_id": 222,
                                           "face_normal": [0, 0, 1]}},
}


def suite_family(version: str) -> dict[str, str]:
    """Real emitted C#, captured at the seam it is dispatched from.

    `_dispatch_code` does exactly one thing — `await bridge_callback("execute",
    {"code": code, …})` — so a callback that keeps `params["code"]` and returns
    nothing yields the production string with no Revit, no bridge and no LLM.
    That rawness is also the reason this matrix matters: `client.py` routes
    family tools at line ~2672 and returns, ~140 lines BEFORE the branch that
    would build a `RevitCodeFixer`. Nothing rewrites this text for the running
    Revit's version, so whatever does not compile is simply a dead capability.

    VERSION-AWARE, and it has to be. `family_add_parameter` picks its
    `AddParameter` overload from `_turn_revit_year()`, because the 2021 spelling
    and the 2022+ spelling share no common form. An emitter that branches on the
    year is invisible to a matrix that renders once and compiles the same text
    six times — it would only ever see the default branch and would report the
    other one as proven when it had never been compiled at all. So the turn's
    version is bound around the dispatch and the suite is rebuilt per column.
    A label whose text does not depend on the year simply comes back identical.
    """
    import asyncio

    from kukai.llm.tool_handlers import family_tools as ft
    from kukai.llm.turn_state import begin_turn, end_turn

    snippets: dict[str, str] = {}

    async def gather() -> None:
        # Inside the coroutine: begin_turn binds a ContextVar to the RUNNING
        # task, which is the one that dispatches.
        token = begin_turn(revit_version=version)
        try:
            for label, args in _FAMILY_ARGS.items():
                # "tool:variant" — several arg shapes drive the same handler
                # down different rendering paths.
                tool = label.split(":", 1)[0]
                if tool.endswith("_linear"):
                    tool = "family_create_array"
                captured: dict[str, str] = {}

                async def fake(method: str, params: dict, _c=captured):
                    if method == "execute":
                        _c["code"] = params.get("code", "")
                    return {}

                try:
                    await ft.dispatch(tool, dict(args), fake)
                except Exception as exc:                    # noqa: BLE001
                    snippets[label] = f"#ERROR {type(exc).__name__}: {exc}"
                    continue
                if "code" in captured:
                    snippets[label] = captured["code"]
                else:
                    # A handler that returned before dispatching emits nothing.
                    # Silence here used to drop the label from the matrix
                    # entirely, which reads as "not covered" but looked like
                    # "no problem". Make it a visible cell instead.
                    snippets[label] = "#NOCODE handler returned before dispatch"
        finally:
            end_turn(token)

    asyncio.run(gather())

    from kukai.codecad.stl_parser import Triangle
    from kukai.llm.tool_handlers.family_codecad import (
        _render_multi_part_directshape_cs,
    )
    snippets["codecad_multi_part"] = _render_multi_part_directshape_cs(
        [("base", [Triangle((0, 0, 0), (1, 0, 0), (0, 1, 0))], (0.1, 0.2, 0.8))],
        "demo")
    return snippets


def suite_model_snapshot(version: str) -> dict[str, str]:
    """The model passport — the most-emitted C# in the whole product.

    `build_census_cs()` is dispatched RAW from `chat_ws.py:945` on the snapshot
    path of EVERY chat turn (memoised per `world_version`, so a write
    invalidates it and the next turn re-runs it), and `build_relations_cs()` the
    same way from `palette_v2.py:471-477` for graph-scope queries. Both go
    through `mark_read_only(...)` and `ws_bridge_callback("execute", …)` — no
    RevitCodeFixer, no repair loop, exactly like the family tools.

    Until 2026-08-03 neither had EVER been compiled against any Revit assembly
    by any automated check. There are Python tests over the strings, but a
    Python test cannot tell you that C# builds. Frequency times zero coverage
    made this the most expensive blind spot in the emitter surface, which is why
    it is now its own suite rather than a line in someone else's.

    Both are module constants (`INVENTORY_CS`, `RELATIONS_CS`) with no
    interpolation, so they are version-independent; the parameter is contract.
    NOTE `build_census_cs()` returns `INVENTORY_CS` — the same constant
    `build_inventory_cs()` returns. `build_inventory_cs` itself has no caller;
    the constant is emphatically live through the census.
    """
    from kukai.query.model_snapshot import build_census_cs, build_relations_cs
    return {
        "census": build_census_cs(),
        "relations": build_relations_cs(),
    }


def suite_write_operations(version: str) -> dict[str, str]:
    """`kukai/write/operations.py` — the apply_revit_write templates.

    Dispatched RAW and SINGLE-SHOT by `revit_verbs._execute_apply_revit_write`:
    one bridge round-trip, no fixer, no repair. `generate_create_recovery_code`
    is deliberately absent — `scripts/create_element_compile_matrix.py` already
    proves that one, and a second copy of a proof is a maintenance cost, not a
    second proof.

    Arguments are shape-bearing; what is compiled is the template. Where a
    generator branches on an argument (`action`, `mode`, an optional `category`
    that switches target selection from an id list to a collector) each branch
    gets its own row, because a template is only proven for the branch that was
    rendered.

    ONE TRAP, worth stating because it cost a false alarm during this work: the
    `category` arguments are BuiltInCategory TOKENS (`"OST_Walls"`), and
    `revit_verbs.py:143` passes exactly that. Feeding a friendly name like
    `"Walls"` renders `BuiltInCategory.Walls` and fails CS0117 on all six — a
    symmetric failure that looks exactly like a dead capability and is only a
    bad argument. Symmetric red on a NEW row means "check the arguments first".
    """
    from kukai.write import operations as ops
    return {
        "set_parameter": ops.generate_set_parameter_code(
            [111, 222], "Comments", "kuki"),
        "set_parameter:category": ops.generate_set_parameter_code(
            [], "Comments", "kuki", category="OST_Walls"),
        "create_schedule": ops.generate_create_schedule_code(
            "OST_Walls", "KUKI Schedule", ["Length", "Area"]),
        "create_schedule:defaults": ops.generate_create_schedule_code(
            "OST_Walls"),
        "hide_or_isolate:hide": ops.generate_hide_or_isolate_code(
            [111], "hide"),
        "hide_or_isolate:isolate": ops.generate_hide_or_isolate_code(
            [111], "isolate"),
        "rename:exact": ops.generate_rename_code([111], "Nm", "exact"),
        "rename:prefix": ops.generate_rename_code([111], "Nm", "prefix"),
        "rename:suffix": ops.generate_rename_code([111], "Nm", "suffix"),
        "delete_elements": ops.generate_delete_elements_code([111, 222]),
        "copy_elements": ops.generate_copy_elements_code(
            [111], 100.0, 0.0, 0.0),
        "move_elements": ops.generate_move_elements_code(
            [111], 100.0, 0.0, 0.0),
    }


SUITES = {
    "norm_control": suite_norm_control,
    "family": suite_family,
    "model_snapshot": suite_model_snapshot,
    "write_operations": suite_write_operations,
}


# ── the compiler ─────────────────────────────────────────────────────────────

def compile_one(wrapped: str, version: str) -> tuple[bool, str]:
    body = json.dumps({"code": wrapped, "revitVersion": version}).encode("utf-8")
    req = urllib.request.Request(
        COMPILE_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("success"):
        return True, ""
    errs = data.get("errors") or []
    msg = "; ".join(f"{e.get('code')}: {e.get('message')} (line {e.get('line')})"
                    for e in errs[:2])
    return False, msg


def run_suite(name: str, build) -> tuple[int, int, list[tuple[str, int, str]]]:
    """Compile every artifact of one suite on every version.

    Returns (ok_cells, total_cells, rows) where each row is
    (label, versions_alive, first_error) — the census shape.
    """
    print(f"\n=== {name} ===")
    # Rebuild per column: a version-conditional emitter renders different text
    # per year, and compiling one rendering six times would prove nothing about
    # the other five.
    per_version = {v: build(v) for v in VERSIONS}
    labels = sorted(set().union(*(d.keys() for d in per_version.values())))

    ok_cells = 0
    rows: list[tuple[str, int, str]] = []
    for label in labels:
        row, first_err, alive = [], "", 0
        for v in VERSIONS:
            body = per_version[v].get(label)
            if body is None:
                row.append(f"{v}:----")
                if not first_err:
                    first_err = "not emitted for this version"
                continue
            ok, msg = compile_one(wrap_user_code(body), v)
            row.append(f"{v}:{'OK  ' if ok else 'FAIL'}")
            if ok:
                ok_cells += 1
                alive += 1
            elif not first_err:
                first_err = msg
        print(f"{label:32s} {'  '.join(row)}")
        if first_err:
            print(f"{'':32s} ↳ {first_err}")
        rows.append((label, alive, first_err))
    return ok_cells, len(labels) * len(VERSIONS), rows


def main(argv: list[str]) -> int:
    only = None
    if "--only" in argv:
        only = argv[argv.index("--only") + 1]
    total_ok = total = 0
    all_rows: list[tuple[str, int, str]] = []
    for name, build in SUITES.items():
        if only and name != only:
            continue
        ok, cells, rows = run_suite(name, build)
        total_ok += ok
        total += cells
        all_rows += rows

    # ── the census ───────────────────────────────────────────────────────────
    # "Dead on ALL SIX" and "broken on the newest" are different diseases with
    # different cures: the first was never once true and is a bug in what we
    # wrote, the second is Autodesk moving under us. Counting them together
    # hides which of the two we actually have, so they are printed apart.
    dead_all = [r for r in all_rows if r[1] == 0]
    partial = [r for r in all_rows if 0 < r[1] < len(VERSIONS)]
    print("\n" + "=" * 78)
    print(f"CENSUS over {len(all_rows)} artifacts x {len(VERSIONS)} versions")
    print("=" * 78)
    print(f"  alive on all {len(VERSIONS)}          "
          f"{len(all_rows) - len(dead_all) - len(partial)}")
    print(f"  alive on SOME (version hole) {len(partial)}")
    print(f"  DEAD ON ALL SIX (never worked) {len(dead_all)}")
    for group, title in ((dead_all, "DEAD ON ALL SIX — never worked on any version"),
                         (partial, "VERSION HOLE — works somewhere, not everywhere")):
        if group:
            print(f"\n{title}:")
            for label, alive, err in sorted(group):
                print(f"  {label:32s} {alive}/{len(VERSIONS)}  {err[:110]}")
    print(f"\nMATRIX: {total_ok}/{total} cells compiled "
          f"({len(VERSIONS)} Revit versions)")
    return 0 if total_ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
