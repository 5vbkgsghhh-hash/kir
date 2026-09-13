# Control residential complex: parallel work and a repeated edit

The pilot uses an existing project: three towers, an OCCT stylobate with an
atrium opening, and a three-story schematic section A. The recipes were
prepared by the development team. A reproducible driver launches real
worker/coordinator processes, **but does not call an LLM and is not an
autonomous designer**.

## Running it

From a source checkout, with the project/OCCT dependencies installed and the
Linux recipe sandbox (including libseccomp):

```sh
PYTHONPATH=. python -m examples.residential_agent_workflow demo NEW_PROJECT.sqlite
```

A new path is needed. An error after work has started may leave a saved
prefix; it must not be deleted or blindly re-executed. The command prints a
JSON report with baseline/concurrent/final revision IDs, task states, two
authored diffs, and the results of the selected checks. Revit is not called.

The project preserves the original five revisions of the old example. The
coordinator then adds two as-yet-unused module slots; the building outputs do
not change. This way the two independent edits do not compete for a shared
module-addition order. These slots are not additional BIM elements or a
second geometry.

## What happens

1. Starting from one base, assignments for section A and tower B are issued,
   with separate instance/module grants. Source/parameters/outputs are saved
   in a `recipe-input` checkpoint.
2. Two processes reach a readiness barrier. The parent checks that both are
   still alive and releases them. Each runs isolated Python and saves a
   proposal; they share the same base.
3. A new coordinator process accepts B, then A on top of the new head. For A,
   the CURRENT→merged check protects the already-accepted B rather than
   treating it as a foreign violation relative to the old shared base.
4. A third proposal of A from the old base yields a saved authored conflict;
   the head does not change because of it.
5. A new A assignment starts on the merged revision. The other processes
   compute and accept the repeated edit. In the happy path, nine revisions
   result: the old prefix, the allocation, and three accepted changes; the
   conflict does not create a revision.

| Scope | Joint result | After continuation |
| --- | --- | --- |
| A, three stories | Story height 4500 mm, top setback 1200 mm | 4800 mm and 1600 mm |
| B, conceptual massing | 8 × 4100 = 32800 mm, rotation −24°, taper 0.82 | Unchanged |
| C | Original tower | Unchanged |
| Podium | Original BRep/bundle bytes, frame, geometry reference | Unchanged |

The section preserves 21 named outputs, exact level refs, and a 2 × 2 m
opening on three floors. The original typed refinement link, named losses,
and the inactive `twist_deg` are preserved. The schematic section does **not**
preserve A's original rotation/taper; this is the same, previously and
explicitly named, redesign, not a lossless conversion.

## What the coordinator checks

Before the authoring decision, the selected operations go through a real
planner. The analytic request check compares the requested heights and
profiles against the outputs' actual fields, not against changed
labels/parameters. The set and order of outputs must match the explicit
request.

For A, exact subject sets and counts are additionally checked: 21 retained
subjects, 3 room-axis enclosures, 3 room seeds within the slab's material XY
area, 3 preserved openings, 2 continuity links between them, and all
protected instances. A missing predicate or `not_evaluated` in a mandatory
group does not become a success. Native/engineering and the other
out-of-scope axes remain `not_evaluated`.

This is the example's policy, not a universal ProjectStore engineering gate.
The report ties together exact current/proposed/source revisions;
`decide_task` then checks the task/project CAS. If they changed during
review, there is no automatic retry of the decision. The XY gate does not
record a false accepted decision on refusal.

Negative control: a second-floor room seed at `[6000, 4000]`, inside a
preserved opening, passes KIR codegen for 2023/2026 and typed lineage. The XY
check rejects it before the decision, leaving the task/head bytes unchanged.
Two more controls separate a matching size from a valid operation and exact
coverage: an unknown field is refused at the planner, an extra output at the
coverage gate.

## Viewing the result

The display is exported explicitly, not in place of the authored project:

```python
from examples.residential_with_podium import materialize_saved
from kir.project_store import ProjectStore
from kir.viewer.standalone_export import export_standalone_scene
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.reference_surfaces import SURFACE_CAPABILITY

store = ProjectStore.open("NEW_PROJECT.sqlite")
display = export_standalone_scene(materialize_saved(store),
    consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY, SURFACE_CAPABILITY])
with open("pilot-display.json", "x", encoding="utf-8") as stream:
    stream.write(display.dumps())
```

The written file carries the frozen revision, its link to the Store, and the
varying precision of the representations; `load_display_artifact` reads it back
and `_project_status` joins it to one Store snapshot. The concept towers are approximate profile
proxies, the podium is real conveyed mesh triangles, not native BIM. The
opt-in display/2 shows [the section's design surfaces without
thickness](REFERENCE_SURFACES_RU.md): walls and floors with openings. These
are not physical BIM solids. The old display/1 remains wireframe; the new
export does not change the program or the project for the sake of the
picture.

## Acceptance boundaries

What is checked: real process parallelism, save/restart, an authored merge, a
conflict, a repeated edit, the invariance of C/the podium, source lineage, and
the selected XY/analytic predicates. The browser checks real WebGL vertices,
raycast, materials, source hashes, and the Store's current revision.

Not confirmed: finished apartments/windows/MEP, physical room boundaries,
structural safety, clash coverage, native bodies/readback, Revit load,
LOD300 level, quality of autonomous LLM design, and product-market fit.
This is a control project and a working program cycle, not a finished residential complex.

Final acceptance September 6, 2026: **272 Python tests /99.70s** in the linked
pilot/recipe/XY/refinement/task/merge strips and **1 Chromium scenario /39.9s**
on the final code. This is not the full pytest corpus. Real viewer screenshots and
fixtures are kept in `.work/pilot-938hPI`; Python worker tests are not a test of the
LLM scheduler, and C# emission is not a test of Revit execution.
