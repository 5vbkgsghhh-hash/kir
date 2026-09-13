# -*- coding: utf-8 -*-
"""FINAL RESULT of the mandate, walked through on ONE saved apartment complex,
step by step.

    python examples/final_result_walkthrough.py --root NEW_DIR

Mandate `.work/stabilize-SujqrS/OFFLINE_KIR_MARATHON_RU.md`, section "Final
result and the boundary of honesty," requires verbatim: "One complex saved
apartment complex goes through creation/opening, a geometric change,
refinement, analysis/repair, team editing, application shutdown, and
continuation."

🔴 WHAT IS HERE. Exactly these eight steps on ONE project file, through
PUBLIC entry points: the example CLI, `ProjectStore`, the authored-script
sandbox, `kir.geometry_authoring`, `kir.project_refinement`,
`kir.clash.project_analysis`, `kir.project_fix`, `kir.bureau`,
`kir.bureau`. There is no manual modeling: not a single shape is
typed into the project file by hand, bodies are built by OCCT from registry
operations. This file does not edit product modules.

🔴 WHAT IS NOT HERE, AND THIS IS PRINTED AT EVERY STEP. Revit is not
launched, there is no native execution, no observed BIM model, no real LLM
in the tree (the bureau's responder is a cassette, `provider_id=tape/
deterministic`, real calls: 0). Not a single green step CLOSES live
acceptance or DECLARES the full product: the honesty row of every step
carries a `not_run` field.

🔴 RED STEPS ARE NOT BYPASSED. Where the public path does NOT HOLD, the step
returns `red` with a tree address and words of refusal — this is the main
result of the run, not an obstacle to it. The list of red steps is printed
at the end as a separate block.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: 🔴 13.09.2026. The documented command is `python examples/final_result_walkthrough.py`,
#: and a script run puts its OWN directory on `sys.path`, not the checkout root.
#: Steps 4 and 5 import `examples.residential_project` / `examples.residential_typed_section`
#: IN THIS process, so on a stranger's checkout they failed with
#: `ModuleNotFoundError: No module named 'examples'` while every other step was green
#: (measured on the sdist of `d010941`: 11 steps, 9 held, 2 red; with
#: `PYTHONPATH=<root>` the same run gave 11 of 11). Child processes were already
#: given the root through `_child_env()`; the parent asks for the same right here,
#: so that the command from the docstring is the command that works.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PROJECT = "residential-foundation"
#: The file name inside the workspace directory.
STORE_NAME = "zhk"

#: SOURCE edits used to test refinement. The numbers are authored, not
#: computed by the product: the atrium is brought to the axis of the north
#: wall (y=9000), the facade curves by −800 mm.
ATRIUM_TO_THE_WALL = {"kind": "atrium_contour",
                      "hole_mm": [[4500.0, 2500.0], [7500.0, 9500.0]],
                      "why": "атриум доведён до стены"}
FACADE_CURVE = {"kind": "facade_curve", "outer_dy_mm": -800.0,
                "why": "изгиб фасада изменён"}
#: The THIRD edit — already after the application closes, and it is the
#: SECOND FACADE. The side is named by a word
#: (`kir/project_refinement.py:_FACADE_SIDES`), the default is the previous
#: `min_y`, so the first two edits have not moved by a single byte.
THIRD_CHANGE = {"kind": "facade_curve", "outer_dy_mm": 600.0, "side": "max_y",
                "why": "второй фасад: южная сторона вынесена"}
#: The axis of the second facade BEFORE the edit. Walls on it are required to
#: move by `outer_dy_mm`.
SECOND_FACADE_Y_MM = 9000.0

#: Terraces: number of setback storeys and the step between them. The
#: generator's default is 1 storey and step 0, i.e. exactly the previous
#: behavior; here two storeys are EXPLICITLY requested.
TERRACE_STOREYS = 2
TERRACE_STEP_MM = 600

#: The parking ramp: a BOX in instance parameters is the only shape that
#: `raise_clear` can move (see `kir/clash/repair_profile.py`). It
#: deliberately sinks into the podium by 1500 mm: that is exactly the finding
#: that step 6 fixes.
RAMP_BOX = [[52000.0, -4000.0, -1500.0], [58000.0, -2000.0, 2000.0]]

#: Tower C's authored script. It runs IN THE SANDBOX (separate process,
#: chroot, zero network) and cannot import OCP: the trusted caller builds
#: bodies from the same registry operations that the script named.
TOWER_C_SCRIPT = '''
project_id = param("project_id", "p")
instance_key = param("instance_key", "i")
radius = param("atrium_radius_mm", 3000)
low = __LOW__
top = __TOP__
envelope(intent=param("project_intent", ""))
create_solid_blend(profile={"shape": "poly", "points_mm": low},
                   profile_top={"shape": "poly", "points_mm": top},
                   height_mm=param("height_mm", 25200), base_z_mm=0, category="mass",
                   name="Башня C: криволинейная оболочка",
                   id=project_output_id(project_id, instance_key, "shell"))
create_solid_boolean(operation="difference",
                     profile={"shape": "poly", "points_mm": low},
                     height_mm=param("plinth_height_mm", 3600), base_z_mm=0,
                     parts=[{"shape": "cylinder", "center_mm": [55000, 4500, 1800],
                             "radius_mm": radius,
                             "height_mm": param("plinth_height_mm", 3600)}],
                     category="mass", name="Башня C: стилобат с атриумом",
                     id=project_output_id(project_id, instance_key, "plinth"))
'''

#: THE CURVED SHELL: the top profile is ROTATED by 15° around the footprint's
#: center, SCALED to 0.82, and SHIFTED. Such a body is not a right prism: the
#: lateral surface is ruled, and the volume is computed by Simpson's
#: prismatoid formula (the cross-section area is linear in the vertices,
#: hence quadratic in height — the formula is EXACT, not an approximation).
#: The numbers are declared here, and the oracle takes them from the same
#: place.
TOWER_C_FOOTPRINT = [[48000.0, 0.0], [62000.0, 0.0], [62000.0, 9000.0], [48000.0, 9000.0]]
TOWER_C_TWIST_DEG = 15.0
TOWER_C_TAPER = 0.82
TOWER_C_SHIFT_MM = (1000.0, 700.0)
TOWER_C_HEIGHT_MM = 25200
TOWER_C_PLINTH_HEIGHT_MM = 3600
TOWER_C_ATRIUM_RADIUS_MM = 3000

#: THE CURVED BRIDGE between sections A and B: the same technique, its own
#: body, its own instance. The span hangs between the towers (z 7200..10800)
#: and touches nothing — this is checked by the number of findings, not by a
#: promise.
BRIDGE_FOOTPRINT = [[15000.0, 1000.0], [23000.0, 1000.0], [23000.0, 8000.0], [15000.0, 8000.0]]
BRIDGE_TWIST_DEG = 10.0
BRIDGE_TAPER = 1.0
BRIDGE_SHIFT_MM = (400.0, -300.0)
BRIDGE_BASE_Z_MM = 7200
BRIDGE_HEIGHT_MM = 3600

BRIDGE_SCRIPT = '''
project_id = param("project_id", "p")
instance_key = param("instance_key", "i")
low = __LOW__
top = __TOP__
envelope(intent=param("project_intent", ""))
create_solid_blend(profile={"shape": "poly", "points_mm": low},
                   profile_top={"shape": "poly", "points_mm": top},
                   height_mm=param("height_mm", 3600),
                   base_z_mm=param("base_z_mm", 0),
                   category="mass", name="Переход A-B: криволинейный пролёт",
                   id=project_output_id(project_id, instance_key, "span"))
'''


def authored_source(template: str, low, top) -> str:
    """Profiles go IN THE TEXT of the authored program, not through a sandbox knob.

    🔴 THIS IS THE SANDBOX BOUNDARY, NAMED BY THE SANDBOX ITSELF. `param()`
    accepts a NUMBER, a STRING, or a FLAG; a list is never a knob (`KIR-B014`:
    "this is a second source, and it is not signed"). So the outline belongs
    to the TEXT of the program — the very thing the recipe pin signs. The
    caller computes the same numbers with its own arithmetic and substitutes
    them into the source, so the volume oracle and the built body look at ONE
    outline, not at two similar ones.
    """
    return (template.replace("__LOW__", json.dumps(low))
                    .replace("__TOP__", json.dumps(top)))


def twisted(points, *, angle_deg: float, taper: float, shift) -> list:
    """Profile -> a ROTATED, scaled, and shifted profile. Plain arithmetic."""
    import math

    cx = sum(x for x, _ in points) / len(points)
    cy = sum(y for _, y in points) / len(points)
    angle = math.radians(angle_deg)
    out = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        out.append([round(cx + taper * (dx * math.cos(angle) - dy * math.sin(angle))
                          + shift[0], 6),
                    round(cy + taper * (dx * math.sin(angle) + dy * math.cos(angle))
                          + shift[1], 6)])
    return out


#: The bureau "worker's" answer. There is no real LLM in the tree, and the
#: cassette does not hide this: `provider_id` arrives as `tape/deterministic`,
#: and the honest row of step 7 carries `real_llm_calls: 0`.
WORKER_ANSWER = ("program = {'ir_version': '1.0', 'intent': 'bureau', 'ops': [\n"
                 "  {'op': 'create_solid_blend', 'id': 'concept-volume',"
                 " 'height_mm': 21600},\n]}\n")

NOT_RUN = {"native_execution": "not_run", "live_model_observed": False,
           "revit_started": False, "real_llm_calls": 0,
           "whole_project_acceptance": "not_established"}


class StepFailed(RuntimeError):
    """A step did not hold. Carries a tree address so red has an owner."""

    def __init__(self, address: str, detail: str):
        super().__init__(f"{address}: {detail}")
        self.address, self.detail = address, detail


def _row(step, instrument, numbers, proved, *, red=None, not_run=None):
    """The honesty row for one step: what is proved by a NUMBER and what was NOT run."""
    return {"step": step, "instrument": instrument, "numbers": numbers,
            "proved": proved, "red": red,
            "not_run": {**NOT_RUN, **(not_run or {})},
            "holds": red is None}


def _child_env():
    return dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1",
                PYTHONNOUSERSITE="1")


def _counts(store) -> dict:
    """Head/history/outputs/bodies — in one measurement, so steps count the same way."""
    head = store.head()
    return {"head": head.revision_id, "history": len(store.history()),
            "instances": len(head.instances),
            "outputs": sum(len(item.outputs) for item in head.instances),
            "bodies": len(head.geometry_references())}


def _instance(store, key):
    return next(item for item in store.head().instances if item.key == key)


def _bytes_of(store, key) -> bytes:
    """Bytes of one instance — this is how "the untouched did not move" becomes a number."""
    from kir.project import _canonical

    return _canonical(_instance(store, key).to_dict())


# ── 1. CREATION: the example's public CLI, not assembling objects in memory ─
def step_create(path: Path) -> dict:
    done = subprocess.run([sys.executable, "examples/residential_refinement.py",
                           "--store", str(path)], cwd=ROOT, env=_child_env(),
                          capture_output=True, text=True, timeout=900)
    if done.returncode != 0:
        raise StepFailed("examples/residential_refinement.py",
                         (done.stderr or done.stdout).strip()[-400:])
    reported = json.loads(done.stdout.strip().splitlines()[-1])
    from kir.project_store import ProjectStore

    counts = _counts(ProjectStore.open(path))
    if reported["project_revision_id"] != counts["head"]:
        raise StepFailed("examples/residential_refinement.py",
                         "CLI назвал не ту голову, что лежит в файле")
    return _row("1. создание", "python examples/residential_refinement.py --store",
                counts,
                "ЖК сохранён CLI примера: три башни, подиум с телом OCCT, "
                "детализированная секция и её ПОВТОРНОЕ изменение — "
                f"{counts['history']} ревизий одной историей",
                not_run={"bim_semantics": "absent"})


# ── 2. OPENING: by another process, which has none of our memory ──────────
def step_open(path: Path, created: dict) -> dict:
    code = ("import json,sys; sys.path.insert(0, %r);"
            "from kir.project_store import ProjectStore;"
            "s=ProjectStore.open(%r);h=s.head();"
            "print(json.dumps({'head':h.revision_id,'history':len(s.history()),"
            "'instances':len(h.instances),"
            "'outputs':sum(len(i.outputs) for i in h.instances),"
            "'bodies':len(h.geometry_references())}))") % (str(ROOT), str(path))
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=_child_env(),
                          capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise StepFailed("kir/project_store.py", (done.stderr or "").strip()[-400:])
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    if seen != created["numbers"]:
        raise StepFailed("kir/project_store.py",
                         f"новый процесс увидел другое: {seen} против {created['numbers']}")
    return _row("2. открытие", "ProjectStore.open в ДРУГОМ процессе", seen,
                "все числа сошлись с только что созданным файлом")


# ── 3. GEOMETRIC CHANGE: script -> sandbox -> proposal -> OCCT bodies ──────
def step_geometry(path: Path) -> dict:
    from kir.geometry_authoring import attach_recipe_bodies
    from kir.project import output_id
    from kir.project_merge import accept_proposal
    from kir.project_recipe import bind_recipe_result
    from kir.project_store import ProjectStore
    from kir.sandbox import SandboxPolicy, execute_author_script

    store = ProjectStore.open(path, readonly=False)
    base = store.head()
    before = _counts(store)
    parameters = {"project_id": base.project_id, "instance_key": "tower-c",
                  "atrium_radius_mm": TOWER_C_ATRIUM_RADIUS_MM,
                  "project_intent": base.intent,
                  "height_mm": TOWER_C_HEIGHT_MM,
                  "plinth_height_mm": TOWER_C_PLINTH_HEIGHT_MM}
    low = [list(point) for point in TOWER_C_FOOTPRINT]
    top = twisted(TOWER_C_FOOTPRINT, angle_deg=TOWER_C_TWIST_DEG,
                  taper=TOWER_C_TAPER, shift=TOWER_C_SHIFT_MM)
    source = authored_source(TOWER_C_SCRIPT, low, top)
    result = execute_author_script(source,
                                   policy=SandboxPolicy(dsl_module="kir.recipe_language"),
                                   params=parameters)
    if not result.ok:
        raise StepFailed("kir/sandbox.py", f"песочница отказала: {result.refusal}")
    binding = bind_recipe_result(
        base, instance_key="tower-c", module_key="tower-c-authored-v1",
        source=source, parameters=parameters,
        output_bindings={key: output_id(base.project_id, "tower-c", key)
                         for key in ("shell", "plinth")},
        result=result, author="автор ЖК", reason="башня C: настоящая геометрия")
    if binding.projection_refusal is not None:
        raise StepFailed("kir/project_recipe.py", str(binding.projection_refusal))
    proposal, assets = attach_recipe_bodies(binding)
    acceptance = accept_proposal(store, proposal, expected_revision=base.revision_id,
                                 authorized_scope=proposal.scope,
                                 assets=list(assets.values()))
    if not acceptance.merge.clean:
        raise StepFailed("kir/project_merge.py", "слияние авторской геометрии не чисто")
    ramp = _add_ramp(store)
    bridge = _add_curved_bridge(store)
    after = _counts(store)
    volumes = {bundle.to_dict()["manifest"]["binding"]["output_key"]:
               bundle.to_dict()["manifest"]["measurements"]["volume_mm3"]
               for bundle in assets.values()}
    faces = {bundle.to_dict()["manifest"]["binding"]["output_key"]:
             bundle.to_dict()["manifest"]["measurements"]["face_count"]
             for bundle in assets.values()}
    numbers = {"bodies_before": before["bodies"], "bodies_after": after["bodies"],
               "history": after["history"], "shell_volume_mm3": volumes["shell"],
               "plinth_volume_mm3": volumes["plinth"], "ramp_bundle": ramp[:12],
               "bridge_volume_mm3": bridge["volume_mm3"],
               "bridge_bundle": bridge["bundle"][:12],
               "shell_twist_deg": TOWER_C_TWIST_DEG,
               "shell_shift_mm": list(TOWER_C_SHIFT_MM),
               "shell_face_count": faces["shell"], "plinth_face_count": faces["plinth"]}
    return _row("3. геометрическое изменение",
                "sandbox -> bind_recipe_result -> attach_recipe_bodies -> accept_proposal",
                numbers,
                "КРИВОЛИНЕЙНАЯ оболочка (лофт с поворотом профиля на "
                f"{TOWER_C_TWIST_DEG}° и сдвигом) и булева разность из АВТОРСКОГО "
                f"скрипта доехали телами OCCT: тел в проекте {before['bodies']} -> "
                f"{after['bodies']}; отдельным экземпляром добавлен криволинейный "
                "переход A-B, пандус паркинга — коробкой в параметрах экземпляра",
                not_run={"revit_geometry_equivalence": "not_claimed",
                         "native_join": "not_run",
                         "sandbox_param_kinds": "scalar_only: обвод контура едет "
                                                "текстом программы, не ручкой"})


def _ramp_operation(box) -> dict:
    (x0, y0, z0), (x1, y1, z1) = box
    return {"op": "create_solid_extrusion", "id": "ramp",
            "profile": {"shape": "poly",
                        "points_mm": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]},
            "base_z_mm": z0, "height_mm": z1 - z0,
            "category": "mass", "name": "Пандус паркинга"}


def _ramp_pin():
    from kir.project import RecipePin

    return RecipePin("kir.geometry_authoring.build_body(create_solid_extrusion)",
                     "b" * 64, entrypoint="ramp")


def rebuild_ramp(output_key, box, parameters, *, frame=None):
    """Recompute the ramp body — a callback for `kir.project_fix`. The author knows the shape."""
    from kir.geometry_authoring import build_body
    from kir.occt_geometry import IDENTITY_FRAME, capture_body

    return capture_body(build_body(_ramp_operation(box)), project_id=PROJECT,
                        instance_key="parking-ramp", output_key=output_key,
                        recipe=_ramp_pin(), parameters=parameters,
                        frame=tuple(frame) if frame else IDENTITY_FRAME,
                        linear_deflection_mm=40.)


def _add_ramp(store) -> str:
    from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                             NamedOutput)

    base = store.head()
    parameters = {"ramp": [list(RAMP_BOX[0]), list(RAMP_BOX[1])]}
    bundle = rebuild_ramp("ramp", RAMP_BOX, parameters)
    instance = ModuleInstance(
        "parking-ramp", "parking-ramp-v1",
        [NamedOutput("ramp", {"op": "create_directshape", "category": "mass",
                              "name": "Пандус паркинга"},
                     BodyRepresentation(bundle.digest, bundle.body_digest))],
        parameters, metadata={"bim_semantics": "absent", "native_execution": "not_run"})
    candidate = base.revise(
        expected_revision=base.revision_id,
        modules=[*base.modules,
                 ModuleDefinition("parking-ramp-v1", "sealed_evaluation", _ramp_pin())],
        instances=[*base.instances, instance])
    store.commit(candidate, expected_revision=base.revision_id, assets=[bundle])
    return bundle.digest


def _add_curved_bridge(store) -> dict:
    """A NEW instance with a body THROUGH THE SANDBOX: placeholder -> evaluation -> body.

    🔴 WHY A PLACEHOLDER. By construction, `bind_recipe_result` REPLACES one
    already existing complete instance ("The first profile replaces one
    existing complete instance"), meaning a recipe cannot establish a new
    address. So the author establishes the address with an ordinary revision,
    and the recipe fills it with a body. This is not a workaround of the
    contract but a reading of it: by evaluation time the new instance already
    has a key, a module, and an output.
    """
    from kir.geometry_authoring import attach_recipe_bodies
    from kir.project import (ModuleDefinition, ModuleInstance, NamedOutput, output_id)
    from kir.project_merge import accept_proposal
    from kir.project_recipe import bind_recipe_result
    from kir.sandbox import SandboxPolicy, execute_author_script

    base = store.head()
    placeholder = ModuleInstance(
        "sky-bridge", "sky-bridge-v1",
        [NamedOutput("span", {"op": "create_level", "elev_mm": BRIDGE_BASE_Z_MM,
                              "name": "Переход A-B: отметка"})],
        metadata={"role": "address_for_the_authored_span",
                  "native_execution": "not_run"})
    seeded = base.revise(
        expected_revision=base.revision_id,
        modules=[*base.modules, ModuleDefinition("sky-bridge-v1")],
        instances=[*base.instances, placeholder])
    store.commit(seeded, expected_revision=base.revision_id)

    seeded = store.head()
    parameters = {"project_id": seeded.project_id, "instance_key": "sky-bridge",
                  "project_intent": seeded.intent,
                  "base_z_mm": BRIDGE_BASE_Z_MM, "height_mm": BRIDGE_HEIGHT_MM}
    source = authored_source(
        BRIDGE_SCRIPT, [list(point) for point in BRIDGE_FOOTPRINT],
        twisted(BRIDGE_FOOTPRINT, angle_deg=BRIDGE_TWIST_DEG,
                taper=BRIDGE_TAPER, shift=BRIDGE_SHIFT_MM))
    result = execute_author_script(source,
                                   policy=SandboxPolicy(dsl_module="kir.recipe_language"),
                                   params=parameters)
    if not result.ok:
        raise StepFailed("kir/sandbox.py", f"песочница отказала переходу: {result.refusal}")
    binding = bind_recipe_result(
        seeded, instance_key="sky-bridge", module_key="sky-bridge-v1",
        source=source, parameters=parameters,
        output_bindings={"span": output_id(seeded.project_id, "sky-bridge", "span")},
        result=result, author="автор ЖК", reason="криволинейный переход A-B")
    if binding.projection_refusal is not None:
        raise StepFailed("kir/project_recipe.py", str(binding.projection_refusal))
    proposal, assets = attach_recipe_bodies(binding)
    acceptance = accept_proposal(store, proposal, expected_revision=seeded.revision_id,
                                 authorized_scope=proposal.scope,
                                 assets=list(assets.values()))
    if not acceptance.merge.clean:
        raise StepFailed("kir/project_merge.py", "слияние перехода не чисто")
    bundle = next(iter(assets.values()))
    return {"bundle": bundle.digest,
            "volume_mm3": bundle.to_dict()["manifest"]["measurements"]["volume_mm3"]}


# ── 4. TERRACES: a section setback is proved by a NUMBER, not by appearance ─
def step_terraces(path: Path) -> dict:
    """Different slab width across levels and its trace in a facade edit's deviation.

    🔴 WHAT IS A NUMBER HERE, AND WHAT IS A PICTURE. A "terrace" is NOT a top
    view, it is two different slab outlines at different levels and a
    different response of those levels to the same facade edit. Both facts
    are taken from the saved project and checked against a closed-form
    formula: shifting the facade by `dy` changes the floor area by exactly
    `width * |dy|`, and the setback upper floor has a width smaller by the
    setback. The product does not derive any of these numbers.
    """
    from kir.project import _thaw, output_id
    from kir.project_refinement import refine_after_source_change
    from kir.project_store import ProjectStore

    store = ProjectStore.open(path, readonly=False)
    terraced = _add_terraced_section(store)
    section = _instance(store, "tower-a")
    parameters = _thaw(section.parameters)
    widths, holes = [], 0
    for output in section.outputs:
        operation = _thaw(output.operation)
        if operation["op"] != "create_floor_by_contour":
            continue
        points = operation["contour"]["outer"]["points_mm"]
        widths.append(round(max(x for x, _ in points) - min(x for x, _ in points), 6))
        holes += len(operation["contour"].get("holes") or ())
    distinct = sorted(set(widths))
    setback = float(parameters["terrace_setback_mm"])
    full = float(parameters["width_mm"])

    report = refine_after_source_change(store, store.head(),
                                        source_output_id=output_id(
                                            PROJECT, "tower-a-concept", "concept-volume"),
                                        change=FACADE_CURVE)
    shift = abs(float(FACADE_CURVE["outer_dy_mm"]))
    deviation = sorted(float(value) for value in (report.deviation["value"] or ()))
    expected = sorted([full * shift] * (len(widths) - 1) + [(full - setback) * shift])
    matches = (len(deviation) == len(expected)
               and all(abs(a - b) <= 1e-6 * max(1.0, abs(b))
                       for a, b in zip(deviation, expected)))
    red = None
    if len(distinct) < 2:
        red = {"address": "examples/residential_project.py:generate_outputs",
               "what": f"уступа нет вовсе: у всех {len(widths)} полов один обвод "
                       f"{distinct}"}
    if len(terraced["widths"]) != len(set(terraced["widths"])):
        red = {"address": "examples/residential_project.py:generate_outputs",
               "what": f"ярусов просили {TERRACE_STOREYS}, а обводы совпали: "
                       f"{terraced['widths']}"}
    numbers = {"floors": len(widths), "slab_widths_mm": distinct,
               "terraced_instance": terraced["key"],
               "terraced_widths_mm": terraced["widths"],
               "terraced_distinct": len(set(terraced["widths"])),
               "terraced_storeys": TERRACE_STOREYS,
               "terraced_step_mm": TERRACE_STEP_MM,
               "default_section_untouched": distinct == [12200.0, 14000],
               "levels_per_width": {str(width): widths.count(width) for width in distinct},
               "terrace_steps": len(distinct) - 1,
               "setback_mm": setback, "atrium_holes": holes,
               "facade_shift_mm": shift,
               "deviation_mm2": deviation, "expected_mm2": expected,
               "deviation_matches_closed_formula": matches,
               "recomputed": len(report.recomputed),
               "preserved": len(report.preserved),
               "needs_decision": len(report.needs_decision)}
    if not matches:
        raise StepFailed("kir/project_refinement.py:_deviation_of",
                         f"отклонение {deviation} не сошлось с формулой {expected}")
    return _row("4. террасы", "обводы плит + refine_after_source_change(фасад)",
                numbers,
                f"{len(widths)} пола секции несут {len(distinct)} разных обвода "
                f"({distinct}); одна и та же правка фасада меняет площадь уступчатого "
                f"уровня на {(full - setback) * shift:.0f} мм², а полных — на "
                f"{full * shift:.0f} мм², и оба числа совпали с замкнутой формулой",
                red=red,
                not_run={"slab_edge_geometry": "declared_not_native",
                         "typed_section_input_keys": "закрытый список "
                         "`examples/residential_typed_section.py:_INPUT_KEYS` не "
                         "принимает `terrace_storeys`, поэтому ярусы живут "
                         "отдельным экземпляром, а не в типизированной секции"})


def _add_terraced_section(store) -> dict:
    """A SECTION WITH TWO SETBACK STOREYS — using the same public example generator.

    🔴 WHY A SEPARATE INSTANCE, NOT AN EDIT OF tower-a. Storeys are requested
    through the OPTIONAL key `terrace_storeys`, while the typed section reads
    a CLOSED list of inputs (`residential_typed_section._INPUT_KEYS`) and
    rejects any extra key with `unsupported_section_snapshot`. Putting
    storeys into tower-a would mean breaking step 5 for the sake of step 4.
    Storeys therefore live at their own address, and the closed list is named
    in the honesty row as what stands in the way.
    """
    from examples import residential_project as towers
    from kir.project import _thaw

    base = store.head()
    if any(item.key == "tower-d" for item in base.instances):
        instance = _instance(store, "tower-d")
    else:
        parameters = {"representation": "section", "x_mm": 72000,
                      "width_mm": 14000, "depth_mm": 9000, "storeys": 3,
                      "storey_height_mm": 3600, "terrace_setback_mm": 1800,
                      "twist_deg": 0, "terrace_storeys": TERRACE_STOREYS,
                      "terrace_setback_step_mm": TERRACE_STEP_MM}
        instance = towers.instance("tower-d", parameters, project_id=base.project_id)
        store.commit(base.revise(expected_revision=base.revision_id,
                                 instances=[*base.instances, instance]),
                     expected_revision=base.revision_id)
        instance = _instance(store, "tower-d")
    widths = []
    for output in instance.outputs:
        operation = _thaw(output.operation)
        if operation["op"] != "create_floor_by_contour":
            continue
        points = operation["contour"]["outer"]["points_mm"]
        widths.append(round(max(x for x, _ in points) - min(x for x, _ in points), 6))
    return {"key": "tower-d", "widths": widths}


# ── 4. REFINEMENT: source edit, a question to the human, an answer, a second change ─
def step_refinement(path: Path) -> dict:
    from kir.project import output_id
    from kir.project_refinement import (answer_question, answered_decisions,
                                        apply_source_change, open_questions,
                                        record_pending_change,
                                        refine_after_source_change)
    from kir.project_store import ProjectStore

    store = ProjectStore.open(path, readonly=False)
    typed = _declare_section_types(store)
    source_id = output_id(PROJECT, "tower-a-concept", "concept-volume")
    head_before = store.head().revision_id
    untouched = _bytes_of(store, "tower-b")

    report = refine_after_source_change(store, store.head(),
                                        source_output_id=source_id,
                                        change=ATRIUM_TO_THE_WALL)
    record_pending_change(store, store.head(), source_output_id=source_id,
                          change=ATRIUM_TO_THE_WALL)
    asked = [question.question_id for question in open_questions(store)]
    if not asked:
        raise StepFailed("kir/project_refinement.py",
                         "правка до стены не спросила человека ни о чём")
    for question_id in asked:
        if any(item.question_id == question_id for item in open_questions(store)):
            answer_question(store, question_id, "keep_wall_and_shrink_atrium")
    still_open = len(open_questions(store))
    decisions = answered_decisions(store)
    if still_open:
        raise StepFailed(
            "kir/project_refinement.py:_still_open/_shrunk_atrium",
            f"после ответа на все {len(asked)} вопросов открытыми остались "
            f"{still_open}: цикл решения не сходится, и `apply_source_change` "
            f"после этого отказывает `decision_required` навсегда")
    head_after_answer = store.head().revision_id
    second = apply_source_change(store, store.head(), source_output_id=source_id,
                                 change=FACADE_CURVE)
    kept = answered_decisions(store)
    if [row["question_id"] for row in kept] != [row["question_id"] for row in decisions]:
        raise StepFailed("kir/project_refinement.py:answered_decisions",
                         "второе изменение источника потеряло решение человека")
    if _bytes_of(store, "tower-b") != untouched:
        raise StepFailed("kir/project_refinement.py",
                         "refinement сдвинул башню B, которой не касался")
    numbers = {"typed_head": typed[:12], "recomputed": len(report.recomputed),
               "preserved": len(report.preserved),
               "needs_decision": len(report.needs_decision),
               "questions_asked": len(asked), "answers_given": len(decisions),
               "questions_left": still_open,
               "conceded_mm": [row["conceded_mm"] for row in decisions],
               "head_moved_on_answer": head_after_answer != head_before,
               "head_moved_on_second_change": second != head_after_answer,
               "residue": len(report.residue)}
    return _row("5. refinement", "record_pending_change -> open_questions -> "
                "answer_question -> apply_source_change",
                numbers,
                f"правка источника до стены разложила {len(report.recomputed)}+"
                f"{len(report.preserved)}+{len(report.needs_decision)} выходов, "
                f"спросила {len(asked)} раз, ответ записан решением и ПЕРЕЖИЛ "
                "второе изменение источника",
                not_run={"geometry_preservation": "not_claimed",
                         "loss_inventory": "not_proven_exhaustive"})


def _declare_section_types(store) -> str:
    """Declared wall/floor layers of the section. Without them, the answer cannot prove the gap."""
    from examples import residential_typed_section as typed
    from kir.project import _digest
    from kir.tests.fixtures import GROUND_SNAPSHOT

    head = store.head()
    section = _instance(store, "tower-a")
    source_id = _digest(section.metadata["refinement"]["source"]["revision_id"],
                        "source.revision_id")
    candidate = typed.add_section_types(
        head, source=store.get(source_id), expected_revision=head.revision_id,
        wall_name="KIR_Section_Wall_230",
        wall_layers=[{"width_mm": 15, "function": "Finish1"},
                     {"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                     {"width_mm": 15, "function": "Finish2"}],
        wall_source_type={"by": "element_id",
                          "value": GROUND_SNAPSHOT["wall_types"][0]["id"]},
        floor_name="KIR_Section_Floor_260",
        floor_layers=[{"width_mm": 200, "function": "Structure", "material": "Бетон М300"},
                      {"width_mm": 50, "function": "Substrate"},
                      {"width_mm": 10, "function": "Finish1"}],
        floor_source_type={"by": "element_id",
                           "value": GROUND_SNAPSHOT["floor_types"][0]["id"]})
    store.commit(candidate, expected_revision=head.revision_id)
    return store.head().revision_id


# ── 5. ANALYSIS: discrepancies of the saved complex, by address ───────────
def _pair(report, finding) -> str:
    keys = getattr(report, "body_keys", {}) or {}

    def name(oid):
        row = keys.get(oid)
        return "/".join(row) if row else oid[:12]

    return " x ".join(sorted((name(finding.a_output_id), name(finding.b_output_id))))


def step_analysis(path: Path) -> dict:
    from kir.clash.project_analysis import analyze_project

    report = analyze_project(path)
    rows = sorted([finding.relation, finding.status, _pair(report, finding),
                   round(float(finding.depth_mm or 0.0), 6)]
                  for finding in report.findings)
    numbers = {"bodies_declared": report.bodies_declared,
               "bodies_with_geometry": report.bodies_with_geometry,
               "findings": len(report.findings), "pairs": rows}
    if report.bodies_declared != report.bodies_with_geometry:
        raise StepFailed("kir/clash/project_analysis.py",
                         f"объявлено тел {report.bodies_declared}, прочитано "
                         f"{report.bodies_with_geometry}")
    return _row("6. анализ", "kir.clash.project_analysis.analyze_project", numbers,
                f"{report.bodies_with_geometry} тел прочитаны из сохранённых бандлов и "
                f"судимы; названо {len(report.findings)} пар с адресами и глубиной",
                not_run={"exact_phase": "rough_hulls_unless_asked",
                         "mep_profile": "not_declared"})


# ── 6. REPAIR: an addressed fix, checking the RESULT, re-analysis ──────────
def step_repair(path: Path) -> dict:
    """Two findings — two lifting strategies, each at its own address.

    🔴 THE CALLER NAMES THE STRATEGY, THE MODULE DOES NOT GUESS IT.
    `raise_clear` edits the AUTHORED PARAMETER (the box under the output's
    name) and calls the author's callback; `raise_clear_body` moves the BODY
    ITSELF by translating the frame and does not touch parameters — this is
    what fixes a body that came from an authored program which has no shape
    in a box at all. The default still REFUSES on such a shape, and here that
    is a negative control: the refusal is required to name the second
    strategy, otherwise it leaves the human without a way out.
    """
    from kir.clash.project_analysis import analyze_project, reanalyze_after_fix
    from kir.project import output_id
    from kir.project_fix import RAISE_CLEAR_BODY, apply_fix, propose_fix
    from kir.project_store import ProjectStore

    before = analyze_project(path)
    ramp_id = output_id(PROJECT, "parking-ramp", "ramp")
    hits = [item for item in before.findings
            if ramp_id in (item.a_output_id, item.b_output_id)]
    if not hits:
        raise StepFailed("examples/final_result_walkthrough.py",
                         "пандус не столкнулся с подиумом — сцена не та")
    store = ProjectStore.open(path)
    untouched = {key: _bytes_of(store, key) for key in ("tower-a", "tower-b", "podium")}

    # (a) AUTHORED PARAMETER: the ramp's box is edited, the author recomputes the body.
    proposal, bundle = propose_fix(path, before, hits[0].finding_id,
                                   move=ramp_id, rebuild=rebuild_ramp)
    head = apply_fix(path, proposal, assets=[bundle], verify=True)
    middle = reanalyze_after_fix(path)
    if len(middle.findings) != len(before.findings) - len(hits):
        raise StepFailed("kir/project_fix.py",
                         f"после починки пандуса находок {len(middle.findings)}, ожидалось "
                         f"{len(before.findings) - len(hits)}")

    # (b) AUTHORED BODY: the shape is given by registry operations, there is no box.
    plinth_id = output_id(PROJECT, "tower-c", "plinth")
    shell_id = output_id(PROJECT, "tower-c", "shell")
    authored = [item for item in middle.findings
                if {item.a_output_id, item.b_output_id} == {plinth_id, shell_id}]
    if not authored:
        raise StepFailed("examples/final_result_walkthrough.py",
                         "вложение стилобата в оболочку не найдено — сцена не та")
    refusal = _default_strategy_refuses_and_names_the_other(path, middle,
                                                            authored[0], plinth_id)
    sibling_before = _body_digest(ProjectStore.open(path), "tower-c", "shell")
    body_proposal, body_bundle = propose_fix(path, middle, authored[0].finding_id,
                                             move=plinth_id, strategy=RAISE_CLEAR_BODY)
    body_head = apply_fix(path, body_proposal, assets=[body_bundle], verify=True)
    after = reanalyze_after_fix(path)
    store = ProjectStore.open(path)
    moved = sorted(key for key, value in untouched.items()
                   if _bytes_of(store, key) != value)
    if moved:
        raise StepFailed("kir/project_fix.py",
                         f"исправление сдвинуло непричастное: {moved}")
    sibling_after = _body_digest(store, "tower-c", "shell")
    if sibling_after != sibling_before:
        raise StepFailed("kir/project_fix.py",
                         "подъём одного тела сменил бандл СОСЕДА по экземпляру")
    if any({item.a_output_id, item.b_output_id} == {plinth_id, shell_id}
           for item in after.findings):
        raise StepFailed("kir/project_fix.py", "починенная пара осталась в отчёте")
    red = None
    if not refusal["names_the_other_strategy"]:
        red = {"address": "kir/project_fix.py:propose_fix",
               "what": "отказ умолчания не называет `raise_clear_body` — человек "
                       "остаётся без выхода: " + refusal["text"][:200]}
    numbers = {"findings_before": len(before.findings),
               "findings_after_ramp": len(middle.findings),
               "findings_after_authored": len(after.findings),
               "ramp_lift_mm": round(float(proposal.world_lift_mm), 3),
               "ramp_depth_mm": round(float(hits[0].depth_mm), 3),
               "authored_lift_mm": round(float(body_proposal.world_lift_mm), 3),
               "authored_relation": authored[0].relation,
               "default_strategy_refused": refusal["refused"],
               "refusal_names_raise_clear_body": refusal["names_the_other_strategy"],
               "sibling_bundle_unchanged": sibling_after == sibling_before,
               "head_moved": head != before.revision and body_head != head,
               "untouched_instances_identical": len(untouched)}
    return _row("7. анализ/repair",
                "propose_fix(raise_clear) + propose_fix(raise_clear_body) -> "
                "apply_fix(verify=True) -> reanalyze_after_fix",
                numbers,
                f"пара пандус×подиум ({hits[0].depth_mm:.3f} мм) исправлена правкой "
                f"авторского параметра на {proposal.world_lift_mm:.3f} мм, пара "
                f"стилобат×оболочка ({authored[0].relation}) — переносом ТЕЛА на "
                f"{body_proposal.world_lift_mm:.3f} мм; находок "
                f"{len(before.findings)} -> {len(middle.findings)} -> "
                f"{len(after.findings)}, бандл соседа по экземпляру тот же",
                red=red, not_run={"native_update": "not_run"})


def _body_digest(store, instance_key, output_key) -> str:
    """The digest of the sibling instance's body: a lift has no right to change it."""
    instance = _instance(store, instance_key)
    output = next(item for item in instance.outputs if item.key == output_key)
    return output.geometry.bundle_sha256


def _default_strategy_refuses_and_names_the_other(path, report, finding, target_id) -> dict:
    """NEGATIVE CONTROL: the default on this shape is required to REFUSE.

    The contract "shape given by a recipe -> refuse by name, not adjust" is
    held by `kir/tests/test_a_fix_survives_a_restart.py::
    test_the_strategy_refuses_a_shape_it_cannot_raise`. A silent fallback to
    the second strategy would turn a named refusal into a silent success, so
    the refusal stays — but it is required to NAME a way out.
    """
    from kir.project_fix import FixError, propose_fix

    try:
        propose_fix(path, report, finding.finding_id, move=target_id,
                    rebuild=rebuild_ramp)
    except FixError as caught:
        return {"refused": True, "text": str(caught),
                "names_the_other_strategy": "raise_clear_body" in str(caught)}
    return {"refused": False, "text": "", "names_the_other_strategy": False}


# ── 7. TEAM EDITING: an assignment, an answer, a proposal (not accepted) ───
def step_team(path: Path, cassette: Path) -> dict:
    from kir.bureau import TapeProvider, TeamBudget, assign, work
    from kir.project import _thaw
    from kir.project_handoff import handoff_instance_to_explicit
    from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
    from kir.project_tasks import read_task

    store = ProjectStore.open(path, readonly=False)
    head = store.head()
    store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=head.revision_id)
    head = store.head()
    sealed = next(module for module in head.modules
                  if module.key == _instance(store, "tower-b").module_key)
    handoff = handoff_instance_to_explicit(head, "tower-b",
                                           new_module_key="tower-b-explicit",
                                           expected_revision=head.revision_id)
    store.commit(handoff, expected_revision=head.revision_id)
    before_height = _thaw(_instance(store, "tower-b").outputs[0].operation)["height_mm"]
    cassette.parent.mkdir(parents=True, exist_ok=True)
    provider = TapeProvider(cassette, mode="record",
                            generator=lambda _request: WORKER_ANSWER)
    task_id = assign(store, "Башня B: поднять объём до 21600 мм", worker_id="worker-1",
                     base_revision=store.head().revision_id, instance_key="tower-b",
                     outputs=["concept-volume"])
    result = work(store, task_id, provider=provider,
                  budget=TeamBudget(max_calls=4, max_tokens=40000))
    if result.refusal is not None:
        raise StepFailed("kir/bureau/attempt.py", f"работа отказала: {result.refusal}")
    task = read_task(store, task_id)
    if task["state"] != "submitted" or not task.get("proposal"):
        raise StepFailed("kir/bureau/runner.py",
                         f"поручение в состоянии {task['state']} без предложения")
    # The SECOND assignment is NOT worked: it stays waiting in the queue and
    # serves as a negative control for step 8 — rejecting a waiting one does
    # not move the head.
    spare_id = assign(store, "Башня B: проверить инсоляцию нижних этажей",
                      worker_id="worker-2", base_revision=store.head().revision_id,
                      instance_key="tower-b", outputs=["concept-volume"])
    spare = read_task(store, spare_id)
    numbers = {"sealed_before_handoff": sealed.owner == "sealed_evaluation",
               "task_id": task_id, "state": task["state"],
               "spare_task_id": spare_id, "spare_state": spare["state"],
               "calls": result.calls,
               "tokens": result.tokens, "provider_id": result.provider_id,
               "tower_b_height_before": before_height,
               "cassette_bytes": cassette.stat().st_size,
               "store_schema": store.schema}
    return _row("8. командное редактирование",
                "handoff -> assign -> work(TapeProvider) — БЕЗ приёма",
                numbers,
                "запечатанный экземпляр отдан явному владельцу, работник ответил "
                f"программой, предложение лежит в поручении {task_id[:12]} и ЖДЁТ "
                "решения человека",
                not_run={"real_llm_calls": 0, "provider_identity": "tape/deterministic",
                         "proposal_accepted": "not_yet"})


# ── 8. CLOSING THE PROCESS AND CONTINUING ─────────────────────────────────
#: 🔴 13.09.2026. THIS STEP USED TO RUN THE BROWSER WINDOW. It started
#: `python -m kir.app` in one process, read the page's session token, closed the
#: process with a real SIGTERM, started a second one on another port and accepted
#: the waiting proposal through `/api/task/accept`. The owner removed the window
#: («убрать точно»), and the step was rewritten rather than dropped: what it
#: measures is that HEAD, HISTORY, ANSWERED DECISIONS and a WAITING assignment
#: survive the death of the process that made them — a property of the DISK, not
#: of a window. Each half now runs in its own child process, with nothing shared
#: but the file.
#:
#: WHAT WENT WITH THE WINDOW, AND IT IS NAMED: the 409 `head_moved_since_read`
#: refusal lived in `kir/app/server.py::act_accept`, not in the product API —
#: `coordinate()` takes no expected head. The comparison below is made by this
#: example, and it is therefore NOT a product guard. The product's own identity
#: guard on the same path is kept and exercised: `revoke_task` refuses a stale
#: `expected_version` by name.
def _child_json(code: str, address: str, timeout: int = 600) -> dict:
    """Run one step half in its own process; the file is all that is shared."""
    done = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=_child_env(),
                          capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise StepFailed(address, (done.stderr or done.stdout).strip()[-400:])
    return json.loads(done.stdout.strip().splitlines()[-1])


_READ_STATE = """
import json, sys
sys.path.insert(0, %r)
from kir.project_store import ProjectStore
from kir.project_tasks import list_tasks
store = ProjectStore.open(%r)
head = store.head()
print(json.dumps({
    "head": head.revision_id,
    "history": len(store.history()),
    "submitted": [t["task_id"] for t in list_tasks(store)["tasks"]
                  if t["state"] == "submitted"],
}))
"""

_DECIDE = """
import json, sys
sys.path.insert(0, %r)
from kir.project import _thaw
from kir.project_store import ProjectStore
from kir.project_tasks import read_task, revoke_task
from kir.bureau.runner import TeamBudget, coordinate
store = ProjectStore.open(%r, readonly=False)
before = store.head().revision_id
spare = read_task(store, %r)
# CONTROL: the product's own identity guard. A decision taken against a version
# that has moved is refused BY NAME, and nothing is written.
stale_refusal = None
try:
    revoke_task(store, %r, request_id="stale-control",
                expected_version="0" * 64, generation=spare["generation"],
                actor="bureau-coordinator", reason="контроль устаревшей версии")
except Exception as error:
    stale_refusal = type(error).__name__ + ": " + str(error)[:120]
after_stale = store.head().revision_id
# A rejection does NOT move the head. Checked by a number, not by a promise.
revoke_task(store, %r, request_id="reject-" + spare["version"][:16],
            expected_version=spare["version"], generation=spare["generation"],
            actor="bureau-coordinator", reason="контроль отклонения")
after_reject = store.head().revision_id
decisions = coordinate(store, budget=TeamBudget(max_calls=8, max_tokens=200000))
after = store.head().revision_id
instance = next(i for i in store.head().instances if i.key == "tower-b")
print(json.dumps({
    "head_before": before, "after_stale": after_stale, "after_reject": after_reject,
    "stale_refusal": stale_refusal,
    "accepted": len((decisions.to_dict().get("accepted") or ())),
    "head_after": after, "head_moved": after != before,
    "history": len(store.history()),
    "height_mm": _thaw(instance.outputs[0].operation)["height_mm"],
}))
"""


def step_continuation(path: Path, cassette: Path, task_id: str, spare_id: str) -> dict:
    before = _child_json(_READ_STATE % (str(ROOT), str(path)), "kir/project_store.py")
    if task_id not in before["submitted"]:
        raise StepFailed("kir/bureau/runner.py",
                         "поручение, ждавшее решения, не видно новому процессу")
    decided = _child_json(_DECIDE % (str(ROOT), str(path), spare_id, spare_id, spare_id),
                          "kir/bureau/runner.py")
    after = _child_json(_READ_STATE % (str(ROOT), str(path)), "kir/project_store.py")

    numbers = {
        "head_before_close": before["head"],
        "history_before_close": before["history"],
        "submitted_before": len(before["submitted"]),
        "head_after_reopen": decided["head_before"],
        "head_survived": decided["head_before"] == before["head"],
        "stale_version_refusal": decided["stale_refusal"],
        "stale_moved_head": decided["after_stale"] != decided["head_before"],
        "reject_moved_head": decided["after_reject"] != decided["head_before"],
        "accepted_tasks": decided["accepted"],
        "head_moved_on_accept": decided["head_moved"],
        "final_head": after["head"], "final_history": after["history"],
        "tower_b_height_after": decided["height_mm"],
        "processes": 3,
    }
    if not numbers["head_survived"]:
        raise StepFailed("kir/project_store.py", "новый процесс увидел другую голову")
    if numbers["stale_version_refusal"] is None:
        raise StepFailed("kir/project_tasks.py:revoke_task",
                         "решение по устаревшей версии поручения прошло молча")
    if numbers["stale_moved_head"] or numbers["reject_moved_head"]:
        raise StepFailed("kir/project_tasks.py:revoke_task", "отклонение сдвинуло голову")
    if not numbers["head_moved_on_accept"]:
        raise StepFailed("kir/bureau/runner.py", "принятое предложение не сдвинуло голову")
    return _row("9. закрытие процесса и продолжение",
                "ProjectStore/bureau в ТРЁХ процессах: чтение -> решение -> перечитывание",
                numbers,
                "голова, история и ЖДАВШЕЕ поручение пережили смерть процесса; "
                "другой процесс принял предложение, и башня B стала "
                f"{decided['height_mm']} мм",
                not_run={"live_model_observed": False,
                         "browser_window": "removed 13.09.2026",
                         "whole_project_acceptance": "not_established"})


# ── 10. THIRD SOURCE CHANGE, ALREADY AFTER THE APPLICATION CLOSED ─────────
def step_third_change(path: Path) -> dict:
    """The project keeps living: a third source edit over someone else's bureau edits.

    🔴 WHY EXACTLY HERE. The first two edits went against a freshly created
    project. This one goes against a project that has ALREADY survived the
    application closing, accepting someone else's proposal, and rejecting
    another. What is being asked is exactly what this whole history is for:
    does the human's decision hold when someone else's moves stood between it
    and the next edit.
    """
    from kir.project import _thaw, output_id
    from kir.project_refinement import (answered_decisions, apply_source_change,
                                        open_questions, refine_after_source_change)
    from kir.project_store import ProjectStore

    store = ProjectStore.open(path, readonly=False)
    source_id = output_id(PROJECT, "tower-a-concept", "concept-volume")
    before_decisions = [row["question_id"] for row in answered_decisions(store)]
    before_head = store.head().revision_id
    untouched = {key: _bytes_of(store, key)
                 for key in ("podium", "sky-bridge", "parking-ramp")}
    report = refine_after_source_change(store, store.head(),
                                        source_output_id=source_id,
                                        change=THIRD_CHANGE)
    red = None
    moved = None
    if report.needs_decision:
        red = {"address": "kir/project_refinement.py:refine_after_source_change",
               "what": f"третья правка требует решения по {len(report.needs_decision)} "
                       f"адресам; продолжение истории упирается в вопрос"}
    else:
        moved = apply_source_change(store, store.head(), source_output_id=source_id,
                                    change=THIRD_CHANGE)
    after_decisions = [row["question_id"] for row in answered_decisions(store)]
    store = ProjectStore.open(path)
    disturbed = sorted(key for key, value in untouched.items()
                       if _bytes_of(store, key) != value)
    if disturbed:
        raise StepFailed("kir/project_refinement.py",
                         f"третья правка сдвинула непричастное: {disturbed}")
    if after_decisions != before_decisions:
        raise StepFailed("kir/project_refinement.py:answered_decisions",
                         "третья правка потеряла решение первого изменения")
    facade = _second_facade_moved(store)
    numbers = {"change_kind": THIRD_CHANGE["kind"],
               "facade_side": THIRD_CHANGE["side"],
               "walls_on_the_second_facade": facade["walls"],
               "second_facade_y_mm": facade["y_mm"],
               "free_ends": facade["free_ends"],
               "recomputed": len(report.recomputed),
               "preserved": len(report.preserved),
               "needs_decision": len(report.needs_decision),
               "open_questions": len(open_questions(store)),
               "decisions_before": len(before_decisions),
               "decisions_after": len(after_decisions),
               "head_moved": bool(moved) and moved != before_head,
               "history": len(store.history()),
               "untouched_instances_identical": len(untouched)}
    return _row("10. третье изменение после reopen",
                "refine_after_source_change -> apply_source_change (новый процесс)",
                numbers,
                f"третья правка источника ({THIRD_CHANGE['kind']}) пересчитала "
                f"{len(report.recomputed)} выходов поверх чужих ходов бюро; решение "
                f"первого изменения цело ({len(after_decisions)}), подиум, переход и "
                "пандус побайтно те же",
                red=red,
                not_run={"facade_sides": "закрытый список min_y/max_y; сторона "
                                          "называется словом, а не углом"})


def _second_facade_moved(store) -> dict:
    """Whether the SECOND facade moved and whether the outline tore. Both numbers by measurement.

    Free ends are counted by the same meter the neighboring edit instrument
    uses (`kir/project_refinement._free_ends`): a second counter of its own
    would diverge from it on the very first change.
    """
    from kir.project import _thaw
    from kir.project_refinement import _free_ends
    from kir.project_selection import selected_instance_program

    program = selected_instance_program(store.head(), "tower-a")
    operations = [_thaw(operation) for operation in program["ops"]]
    expected = SECOND_FACADE_Y_MM + float(THIRD_CHANGE["outer_dy_mm"])
    walls = sum(1 for operation in operations
                if operation["op"] == "create_wall"
                and abs(float(operation["p0_mm"][1]) - expected) <= 1e-9
                and abs(float(operation["p1_mm"][1]) - expected) <= 1e-9)
    return {"walls": walls, "y_mm": expected, "free_ends": len(_free_ends(operations))}


# ── 11. REPAIR AFTER THE THIRD CHANGE: the loop closes again ──────────────
def step_repair_again(path: Path) -> dict:
    """One more finding, one more fix, one more check of the RESULT."""
    from kir.clash.project_analysis import analyze_project, reanalyze_after_fix
    from kir.project_fix import RAISE_CLEAR_BODY, apply_fix, propose_fix
    from kir.project_store import ProjectStore

    before = analyze_project(path)
    if not before.findings:
        return _row("11. repair после третьего изменения", "analyze_project", {
            "findings_before": 0},
            "чинить нечего: после шага 7 находок не осталось",
            red={"address": "examples/final_result_walkthrough.py",
                 "what": "сцена не оставила находки для второго круга починки"})
    from kir.project import output_id
    from kir.project_fix import FixError

    shell_id = output_id(PROJECT, "tower-c", "shell")
    finding = next((item for item in before.findings
                    if shell_id in (item.a_output_id, item.b_output_id)),
                   before.findings[0])
    target = shell_id if shell_id in (finding.a_output_id, finding.b_output_id) \
        else finding.a_output_id
    store = ProjectStore.open(path)
    untouched = {key: _bytes_of(store, key)
                 for key in ("tower-a", "tower-b", "sky-bridge", "parking-ramp")}
    try:
        proposal, bundle = propose_fix(path, before, finding.finding_id, move=target,
                                       strategy=RAISE_CLEAR_BODY)
    except FixError as refusal:
        # 🔴 RED IS NOT BYPASSED AND LOSES NO NUMBERS. The same strategy at
        # step 7 RAISED the boolean prism's body; here it refuses on the
        # LOFT's body.
        return _row("11. repair после третьего изменения",
                    "propose_fix(raise_clear_body)",
                    {"findings_before": len(before.findings),
                     "findings_after": len(before.findings),
                     "pair": _pair(before, finding), "relation": finding.relation,
                     "target": "tower-c/shell" if target == shell_id else target[:12],
                     "refusal": str(refusal)[:200],
                     "same_strategy_worked_on_a_prism_body_at_step_7": True},
                    "не доказано",
                    red={"address": "kir/project_fix.py:_move_authored_body",
                         "what": "перенос КРИВОЛИНЕЙНОГО тела (лофт "
                                 "`BRepOffsetAPI_ThruSections`) меняет его BRep, и "
                                 "подъём отказывает `authored_body_needs_recipe_rebind`. "
                                 "На теле булевой призмы (шаг 7) тот же "
                                 "`raise_clear_body` работает — значит перенос не "
                                 "инвариантен именно для лофта, и второй круг "
                                 "починки на криволинейной оболочке НЕ замыкается. "
                                 f"Отказ: {str(refusal)[:160]}"},
                    not_run={"native_update": "not_run"})
    auto_lift = round(float(proposal.world_lift_mm), 3)
    blocked = None
    try:
        head = apply_fix(path, proposal, assets=[bundle], verify=True)
    except FixError as first:
        # 🔴 THE AUTOMATIC DEPTH WAS NOT ENOUGH, AND THIS IS NOT A WORKAROUND
        # BUT A SECOND QUESTION. The lift is computed from THIS pair's
        # overlap, while a third body stands above the target — the podium,
        # raised at step 7. The `fix_creates_new_conflict` guard correctly
        # rejects worsening a neighbor; the human's way out is DECLARED — name
        # the lift directly (`lift_mm`), and here it is computed from the
        # shells' own dimensions, not eyeballed.
        blocked = str(first)[:200]
        if "fix_creates_new_conflict" not in blocked:
            raise
        lift = _lift_over_everything_above(before, target)
        proposal, bundle = propose_fix(path, before, finding.finding_id, move=target,
                                       strategy=RAISE_CLEAR_BODY, lift_mm=lift)
        head = apply_fix(path, proposal, assets=[bundle], verify=True)
    except FixError as refusal:
        # 🔴 THE GUARD IS RIGHT, AND THERE IS NO WAY OUT. The only remaining
        # pair is the shell touching the podium at elevation 0; it cannot be
        # separated by a lift, because a podium raised at step 7 already
        # stands ABOVE the shell. The fix has no strategy other than lifting
        # along +z: it can neither lower the neighbor nor shift it
        # horizontally. The `fix_creates_new_conflict` refusal is the correct
        # refusal (worsening a neighbor is not accepted), but the loop on this
        # pair does NOT close, and this is the step's red, not its success.
        return _row("11. repair после третьего изменения",
                    "propose_fix(raise_clear_body) -> apply_fix(verify=True)",
                    {"findings_before": len(before.findings),
                     "findings_after": len(before.findings),
                     "pair": _pair(before, finding), "relation": finding.relation,
                     "target": "tower-c/shell" if target == shell_id else target[:12],
                     "lift_mm": round(float(proposal.world_lift_mm), 3),
                     "refusal": str(refusal)[:220],
                     "proposal_built": True},
                    "не доказано",
                    red={"address": "kir/project_fix.py (стратегии подъёма)",
                         "what": "у починки есть только подъём по +z. Оставшаяся "
                                 "пара — касание оболочки с подиумом на отметке 0; "
                                 "подъём оболочки на 50 мм заводит НОВУЮ пару с "
                                 "поднятым на шаге 7 стилобатом, и сторож "
                                 "`fix_creates_new_conflict` его отвергает — верно, "
                                 "но выхода человеку не остаётся: опустить соседа, "
                                 "сдвинуть по горизонтали или развести иначе "
                                 "стратегия не умеет. Второй круг НЕ замыкается: "
                                 f"находок {len(before.findings)} -> "
                                 f"{len(before.findings)}"},
                    not_run={"native_update": "not_run"})
    after = reanalyze_after_fix(path)
    store = ProjectStore.open(path)
    disturbed = sorted(key for key, value in untouched.items()
                       if _bytes_of(store, key) != value)
    if disturbed:
        raise StepFailed("kir/project_fix.py",
                         f"второй круг починки сдвинул непричастное: {disturbed}")
    if len(after.findings) != len(before.findings) - 1:
        raise StepFailed("kir/project_fix.py",
                         f"находок {len(after.findings)}, ожидалось "
                         f"{len(before.findings) - 1}")
    numbers = {"findings_before": len(before.findings),
               "findings_after": len(after.findings),
               "pair": _pair(before, finding), "relation": finding.relation,
               "target": "tower-c/shell" if target == shell_id else target[:12],
               "automatic_lift_mm": auto_lift,
               "automatic_lift_refused": blocked is not None,
               "refusal_of_the_automatic_lift": blocked,
               "lift_mm": round(float(proposal.world_lift_mm), 3),
               "head_moved": head != before.revision,
               "untouched_instances_identical": len(untouched)}
    return _row("11. repair после третьего изменения",
                "propose_fix(raise_clear_body) -> apply_fix(verify=True) -> "
                "reanalyze_after_fix",
                numbers,
                f"пара {_pair(before, finding)} ({finding.relation}) разведена "
                f"подъёмом {proposal.world_lift_mm:.3f} мм; находок "
                f"{len(before.findings)} -> {len(after.findings)}, соседние "
                "экземпляры побайтно те же",
                not_run={"native_update": "not_run"})


def _lift_over_everything_above(report, target: str) -> float:
    """The lift at which the target ends up ABOVE every body standing over it.

    The numbers are taken from the report itself (`hull_bounds` — dimensions
    in project coordinates), not tuned by hand: the scene's ceiling plus the
    declared clearance minus the target's bottom. This way, "naming the lift
    directly" remains a measurement, not a guess.
    """
    bounds = getattr(report, "hull_bounds", None) or {}
    mine = bounds.get(target)
    if not mine:
        raise StepFailed("kir/clash/project_analysis.py",
                         f"у {target[:12]} нет габаритов в отчёте")
    ceiling = max(float(box[1][2]) for box in bounds.values())
    return ceiling + _clearance() - float(mine[0][2])


#: The default clearance belongs to the fix — a second literal would diverge from it.
def _clearance() -> float:
    from kir.project_fix import DEFAULT_CLEARANCE_MM as owner

    return float(owner)


# ── run ──────────────────────────────────────────────────────────────────────
def run(root) -> list:
    """All eight steps on ONE file. A red step does not interrupt the run."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "workspace" / f"{STORE_NAME}.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    cassette = root / "tape" / "cassette.json"
    rows = []

    def guarded(name, instrument, call):
        try:
            return call()
        except StepFailed as failure:
            return _row(name, instrument, {}, "не доказано",
                        red={"address": failure.address, "what": failure.detail})
        except Exception as failure:  # noqa: BLE001 — red with a name, not a trace
            return _row(name, instrument, {}, "не доказано",
                        red={"address": "examples/final_result_walkthrough.py",
                             "what": f"{type(failure).__name__}: {failure}"[:400]})

    created = guarded("1. создание", "CLI примера", lambda: step_create(path))
    rows.append(created)
    if not created["holds"]:
        return rows
    rows.append(guarded("2. открытие", "ProjectStore.open",
                        lambda: step_open(path, created)))
    rows.append(guarded("3. геометрическое изменение", "authoring",
                        lambda: step_geometry(path)))
    rows.append(guarded("4. террасы", "обводы плит + отклонение",
                        lambda: step_terraces(path)))
    rows.append(guarded("5. refinement", "kir.project_refinement",
                        lambda: step_refinement(path)))
    rows.append(guarded("6. анализ", "kir.clash.project_analysis",
                        lambda: step_analysis(path)))
    rows.append(guarded("7. анализ/repair", "kir.project_fix",
                        lambda: step_repair(path)))
    team = guarded("8. командное редактирование", "kir.bureau",
                   lambda: step_team(path, cassette))
    rows.append(team)
    task_id = (team["numbers"] or {}).get("task_id")
    spare_id = (team["numbers"] or {}).get("spare_task_id")
    if task_id and spare_id:
        rows.append(guarded("9. закрытие процесса и продолжение",
                            "ProjectStore/bureau в трёх процессах",
                            lambda: step_continuation(path, cassette, task_id, spare_id)))
    else:
        rows.append(_row("9. закрытие процесса и продолжение",
                         "ProjectStore/bureau в трёх процессах", {},
                         "не доказано",
                         red={"address": "kir/bureau/runner.py",
                              "what": "шаг 8 не дал поручения — продолжать нечего"}))
    rows.append(guarded("10. третье изменение после reopen", "kir.project_refinement",
                        lambda: step_third_change(path)))
    rows.append(guarded("11. repair после третьего изменения", "kir.project_fix",
                        lambda: step_repair_again(path)))
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, metavar="NEW_DIR",
                        help="новый каталог: в нём появятся проект, кассета и рабочий стол")
    args = parser.parse_args(argv)
    rows = run(args.root)
    for row in rows:
        print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    red = [row for row in rows if row["red"]]
    print(json.dumps({"schema": "kir-final-result-walkthrough/1",
                      "steps": len(rows), "held": len(rows) - len(red),
                      "red": [{"step": row["step"], **row["red"]} for row in red],
                      "claims": {"live_revit": "not_run", "full_product": "not_claimed",
                                 "real_llm_calls": 0}}, ensure_ascii=False))
    # 🔴 THE EXIT CODE CARRIES THE VERDICT. The mandate
    # (`.work/stabilize-SujqrS/OFFLINE_KIR_MARATHON_RU.md`, "Order and
    # organisation"): "If a check fails or did not execute, that is not a ДА...
    # the exit code is not lost in the pipeline." Until 13.09.2026 this
    # returned 0 with red steps printed, so a pipeline reading only the code
    # saw green. The red list stays on stdout either way: the code is a
    # SECOND carrier of the same fact, not a replacement for it.
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
