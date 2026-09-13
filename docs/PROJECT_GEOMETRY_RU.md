# Persistable project geometry: body-owned outputs

The Foundation branch, 2026-09-05. Storage, core/materialization, and
displaying the authored DirectShape mesh are accepted in a verified offline
slice. A separate standalone consumer supports an explicit approximate
profile-proxy for a limited subset of `create_solid_blend`. This is a new
display contract, not a fix to the legacy renderer and not proof of native
equivalence for a blend.

## Who owns the shape

`BodyRepresentation(bundle_sha256, body_sha256)` inside `NamedOutput.geometry`
refers to an immutable `GeometryBundle`. Such an output's operation is only
the `create_directshape` template with `category`/`name`, without a second
authored `mesh`. The body, the frame, the units, and the tessellation
settings belong to the pinned bundle. Ordinary mesh-only outputs remain
legitimate; they do not claim to have a BRep.

`ProjectRevision.to_program()` and `plan()` do not substitute a saved
preview in place of a missing body implementation: a body-owned output
requires an explicit `kir.geometry_materialization.materialize_project(project, bundles)`.
This call reads the BRep, re-derives the mesh and the measurements, applies
the frame to the mesh once, and returns a single program/plan for
downstream consumers. Measurements are tagged `body_local`, the mesh is
tagged `project`; the units are millimeters. Before tessellation, built-in
polygonal caches are stripped from a separately read copy of the BRep:
otherwise the incremental mesher could reuse old triangles that contradict
the surfaces. The original bytes are not modified; a face cache that
survives the cleanup triggers a named refusal.

`validate_geometry_bindings` checks, without native parsing, the exact
digests, the project/instance/output address, the parameters, and the
declared recipe pin. With `module.recipe=None`, a recipe match is not
claimed; a source bundle is not renamed into the product of a different
function. Matching declarations does not prove that the saved Python was
actually executed.

## Two explicit schema changes

The authored `/1` preserves the previous JSON bytes and hash. For new
body-owned outputs, a `/2` revision is created first via
`project.upgrade_schema(...)` with an expected revision. This is a new
record with a parent, not a rewrite of the past. The `output_id` namespace
stays the same. Ordinary subsequent `revise` calls preserve the schema; the
store does not allow a `/2 → /1` transition backward in history.

Storage `/2` is a separate version of the internal SQLite format. An
explicit `store.upgrade_schema("kir-project-store/2", expected_revision=head_id)`
adds an assets table but does not change the authored revision or the head.
The default for a new store remains `/1`; a new body-owned root needs an
explicit `/2`.

```python
from kir.project_store import ProjectStore, GEOMETRY_STORE_SCHEMA
from kir.geometry_materialization import materialize_project

# project — уже созданный /2 root; bundle — его закреплённое тело.
store = ProjectStore.create(
    "new-project.sqlite", project,
    schema=GEOMETRY_STORE_SCHEMA, assets=[bundle])

# proposed.parent_revision == project.revision_id.
store.commit(proposed, expected_revision=project.revision_id,
             assets=[new_bundle])  # только новые/используемые proposed assets

reopened = ProjectStore.open("new-project.sqlite")  # read-only
head = reopened.head()
assets = {out.geometry.bundle_sha256: reopened.get_asset(out.geometry.bundle_sha256)
          for _, out, _ in head.geometry_references()}
realized = materialize_project(head, assets)
program = realized.to_program()   # detached view; не native write plan
planned = realized.planned        # тот же материализованный program
```

This is a fragment of the API with ready-made input values, not a complete
design example. A `commit` without new assets reuses the ones already
saved. An unchanged bundle is not copied into every revision. No separate
second database appears.

## The persistence boundary

New assets, the revision, and the head CAS are written in one SQLite
transaction. A losing concurrent edit leaves no assets behind. A foreign
address, a wrong body hash, a mismatch of parameters/recipe, and a missing
body all produce a named refusal. An inert store can save consistent
declarations for a stale preview; this risk is fixed by the mandatory
derivation from the BRep, not by an extra hash.

Repeating a save returns the previous record without rewinding the head. A
corrupted existing asset is not "repaired" by re-delivering good bytes.
Decisions about saving are made over the canonical decoded
`ProjectRevision`, not by methods of a passed-in Python subclass. Returned
bundles are immutable; exported dicts are detached.

`head/get/commit` check the addressed data and the assets it needs, not the
entire past history. `history()` separately checks the chain, the
authored-schema transitions, and every saved asset. Corruption of an unused
old body can only be caught at lookup/audit time. This is the same old
hot-path boundary, not a promise of a constant full scan of the database.

Real, separate processes have been tested: competing CAS, a crash after an
asset, after a revision, and after a commit, the read-only refusal of the
hot journal, and explicit writable recovery. In a fresh process, native
imports are forbidden by a control hook: load/head/get/history/get_asset
remain inert. This is not a test of a physical power cut and not a
guarantee for network filesystems.

## The body arrives from the AUTHORED program (07.09.2026)

`kir/geometry_authoring.py` computes three already-existing registry ops
(`create_solid_extrusion`, `create_solid_blend`, `create_solid_boolean`)
with the OCCT kernel and hands them to the same `capture_body`. There is no
new language: only the `ParamSpec` fields are read.

The full path, with no relaxation of the sandbox:

```
скрипт модели -> sandbox.execute_author_script (процесс, chroot, ноль сети)
             -> project_recipe.bind_recipe_result   (запечатанная оценка)
             -> geometry_authoring.attach_recipe_bodies (доверенный вызывающий)
             -> project_merge.accept_proposal        (ProjectStore /2 + активы)
```

Measured 07.09: before the fix, the same program gave
`bodies_with_geometry 0`; after, `2` with `hull_source = brep`. Volumes were
checked against a quantity that was not in the input: a prismatoid for the
blend, a cylinder's volume for the void.

### The shape is read by a SINGLE carrier of the law (07.09.2026)

Before this fix, `geometry_authoring` parsed the profile with its OWN
reader and knew two forms out of five. Measured seven inputs, legal per
`contour.SHAPE_FORMS` and per the `ops_solid` registry:

| input | before | after |
|---|---|---|
| `rect` | body | body |
| `rect` + `rotation_deg` | `unsupported_profile` | body |
| `poly` + `arcs` | `unsupported_profile` | body (arc through three points) |
| `poly` + `splines` | `unsupported_profile` | `unsupported_profile` (deliberate) |
| `l` | `unsupported_profile` | body |
| `{outer, holes}` | `unsupported_profile` | body with an opening |
| a tilted `plane` | `unsupported_op` | body (extrusion along the normal) |

The profile is now read by `contour.validate_region` — the SAME call the
compiler uses to read it in `ground.py`. There is no longer a second
dictionary of shapes anywhere in the tree. The arc is built by
`GC_MakeArcOfCircle(start, point-on-arc, end)` using the SAME three points
that the emission prints (`Arc.Create`); the midpoint is taken from
`contour.bulge_midpoint`. The sketch plane is read from `kir.plane.frame` —
the single carrier of the O·X·Y·N triple.

THE SPLINE REMAINS A NAMED REFUSAL, but on 08.09.2026 the refusal's REASON
CHANGED, and this is not a copy-edit. Previously the body evaluator gave
ITS OWN argument — "CONTOUR samples Catmull-Rom, while the emission prints
`HermiteSpline.Create`; these are different curves." The argument is true,
but it is the SECOND one: the real, single law lives in
`contour.SPLINE_WITNESSED_OPS`. Measured 08.09 on the compiler:

| program | the language's answer |
|---|---|
| `create_solid_extrusion` + `splines` | `ok=False`, **KIR-E010** (the `ground.py` guard) |
| `create_solid_blend` + `holes` | `ok=False`, **KIR-T004** (`solid_emit.py`) |
| the 0.005 mm boolean plate (further below) | `ok=True`, 0 diagnostics |

None of the three `BODY_OPS` is in `SPLINE_WITNESSED_OPS`: they have a
bounding-box witness, and a spline's bounding box is UNDERESTIMATED
(`contour.edges_bbox`). So if the evaluator built the curve, the project
would get a BODY FOR A PROGRAM THE LANGUAGE DOES NOT COMPILE: the same
disease of "two readers of one shape" that this file was cured of on
07.09, only running in the opposite direction. Now the refusal READS the
registry: add the op to `SPLINE_WITNESSED_OPS`, and the refusal's text
changes on its own, rather than after someone remembers there's a second
file (pin `test_the_spline_refusal_changes_its_reason_when_the_registry_changes`).

🔴 A SIDE FINDING FROM THE SAME MEASUREMENT, NOT CLOSED HERE. The
`SPLINE_WITNESSED_OPS` registry holds up not only the witness's honesty but
the COMPILER ITSELF: add `create_solid_extrusion` to it, and compiling the
same program crashes with **KIR-P000** ("internal compiler error"), stage
`emit_authoring`, because `solid_emit` calls `contour.region_measures`, and
a spline has no measure (`SplineMeasureUnavailable`). In other words,
between a spline in a volumetric op and a compiler panic stands EXACTLY ONE
frozenset. The place to fix it is `kir/solid_emit.py` (not this wave's
holding), and this is stated outright, not implied.

A BLEND WITH AN OPENING — THE SAME ANALYSIS AND THE SAME OUTCOME.
`CreateBlendGeometry(CurveLoop, CurveLoop, …)` takes exactly ONE loop per
profile, and the emission has refused on this since 04.09.2026 (KIR-T004).
Cutting the opening with a prism AFTER `ThruSections` would mean giving the
project a body that Revit will not build from our own C#. The refusal
stays, but on 08.09 it gained a NUMBER: how much material the silence
would have cost — the area of the openings (`contour.region_measures`, a
Green's-theorem integral) times the blend's extrusion, separately for the
bottom and the top profile. On a 4000×3000 profile with a 1000×1000 opening
and a 3000 mm extrusion, that's 3,000,000,000 mm³. The next turn's refusal
names the very same op as the emission does: assemble the blend without
the openings and subtract the opening with `create_solid_boolean`.

The instrument is the REGISTRY'S POST-CONDITION verbatim ("solid volume ==
profile area * extrusion height, both closed-form at compile time"): the
area is computed by `contour.region_measures` (a Green's-theorem integral,
exact even for an arc), the volume by OCCT on the built body. File
`kir/tests/test_the_shape_the_language_accepts_becomes_a_body.py`, 25 runs
(16 on 07.09 + 9 on 08.09: the equivalence of the two readers, the number
in the blend's refusal, reading the spline registry). FAIL control by
mutation: extrusion along `+Z` instead of the normal — 1 red; an arc as a
chord — 2 reds; an opening without reversing its winding — 2 reds; a
spline refusal with ITS OWN argument instead of the registry — 2 reds; a
blend refusal without the number — 1 red.

### 🔴 A NAMED LIMIT: OCCT VOLUME ≠ REVIT VOLUME

Live Revit was launched ZERO times in this branch. So equality between the
OCCT and Revit volumes is NOT CLAIMED for any shape, and the limit is
written down here by name, not implied:

1. **The blend's lateral surface.** `BRepOffsetAPI_ThruSections` with
   straight ruling versus Revit's undocumented `CreateLoftGeometry` (see
   the header of `ops_solid.py`). The discrepancy is NOT BOUNDED ABOVE by
   anything the tree can check offline.
2. **The arc.** The three points are the same ones `Arc.Create` uses, so
   the CURVE is the same. But volume equality still isn't claimed:
   tessellation, the stitching tolerance, and the order of booleans are
   Revit's own.
3. **A tilted plane.** The body is a STRAIGHT prism along the normal,
   exactly as the registry declares. An oblique prism is inexpressible in
   either system.
4. **The boolean.** The order of operations is the same here and in the
   C#, but OCCT's and Revit's face-merging thresholds differ;
   `empty_boolean_result` only catches EMPTINESS, not a discrepancy.
5. **What IS verified offline.** The OCCT volume matches the CLOSED-FORM
   SHAPE that the compiler prints to the witness (`solid_emit`), with a
   relative difference ≤ 1e-9 across five shapes. This is KIR checked
   against ITSELF, not against Revit.
6. **What lifts the limit.** Only a live run of the `post`-clause witnesses
   in Revit; until then, any number about Revit's volume in this tree is a
   fabrication.

WHAT THIS STILL DOES NOT MEAN. A reflected FRAME is refused by name
(`invalid_frame`); a permitted reflection is a separate turn, see below. An
empty boolean and an exact zero are forbidden (`empty_boolean_result`), and
so are a thin and a degenerate body (`thin_body`, `degenerate_body`), with
thinness asked TWICE, in two different places. The DECLARED thinness is
measured by `_check_sketch` — in the SKETCH PLANE: for a 4000×3000×0.005 mm
plate at 45°, an axis-aligned box gives all three edges in meters, and a
check against the world box would have let it through SILENTLY. The
RESULTING thinness is measured by `_check_body` — as of 08.09.2026 with two
boxes, the world one and the body's own (see the section below): a
thinness BORN from the boolean in a rotated frame is something the
declared numbers know nothing about at all.

### A LIMIT LIFTED: THINNESS NO LONGER DEPENDS ON THE COORDINATE SYSTEM (08.09.2026)

Before 08.09 there stood a named limit here: **a thin plate PRODUCED by a
boolean operation in a rotated coordinate system was not being called
`thin_body`.** `_check_sketch` measures what the author NAMED (the
region's extent in the sketch plane and the extrusion distance) — it is
exact at any tilt, but it only knows the DECLARED numbers, whereas here the
thinness is BORN from the boolean. `_check_body` measured the RESULT, but
against an AXIS-ALIGNED box, i.e. against the extent of the body's SHADOW
on the world axes.

THE MEASUREMENT THAT SHOWED THE LIMIT WAS ALIVE (08.09.2026). The compiler
ACCEPTS the program (`ok=True`, zero diagnostics) — its path to Revit is
open: the intersection of two prisms over 4000×3000 rectangles, rotated 45°
in plan and offset crosswise by 2999.995 mm.

| quantity | before |
|---|---|
| result volume | 60,000 mm³ (4000 × 3000 × 0.005) |
| axis-aligned box | 2828.43 × 2828.43 × 3000 mm — all three edges in meters |
| extent along the BODY's own axes | 0.005 mm |
| modeling tolerance | 0.01 mm |
| outcome | the body was built silently |

`degenerate_body` did not trigger (60,000 mm³ ≫ 0.01³),
`empty_boolean_result` did not trigger (there is a body), `BRepCheck` did
not trigger (the topology is valid). What went unnamed was precisely the
kind "thin," and only that.

HOW IT WAS LIFTED. `_check_body` now asks about thinness with TWO boxes and
decides by the SMALLER one: the old world-aligned one and an oriented one
(`geometry_authoring._own_axes_thinnest` → `BRepBndLib::AddOBB`). The three
OBB arguments are set explicitly, and each was chosen against a named hazard:

* `theIsTriangulationUsed=False` — otherwise the answer would depend on
  whether someone had earlier called `rederive_preview` on the same
  object: the tessellation stays in the shape, and the measure would stop
  being a function of the body. Measured: the numbers with and without
  triangulation matched on all five shapes in the tree;
* `theIsOptimal=True` — a tighter box; the cost is measured: **0.3–0.4 ms**
  per body against 1.4–2.6 s for building the body itself;
* `theIsShapeToleranceUsed=False` — expanding the box by the shape's
  tolerance would make a thin body THICKER, i.e. it would weaken exactly
  the guard the measure exists for.

THE THRESHOLD IS THE SAME TOLERANCE that goes into the body manifest
(`occt_geometry.capture_body.modeling_tolerance_mm`, today 0.01 mm), not a
second number alongside it; the pin moves it in both directions.

WHAT THE MEASURE DOES NOT CLAIM. The OCCT oriented bounding box **is not
required to be the tightest one** (for curved faces it is built along the
inertia axes), so the number is an UPPER-BOUND ESTIMATE of the true thickness.
Hence the only legitimate way to use it: "small" is proof of thinness, "large"
is NOT proof of thickness. That is why the SMALLER of the two boxes is taken,
not a new one instead of the old: the edit could not weaken the previous guard
on any body, and this is a pin, not a promise
(`test_the_new_measure_never_answers_softer_than_the_old_one`).

THE INSTRUMENT is `kir/tests/test_a_thin_result_is_thin_in_any_frame.py`, 9
runs. It holds TWO independent rotations: 45° in plan (straight edges, box by
vertices) and a spherical segment 0.005 mm high on the top face of a prism laid
on a plane with normal (0, √½, √½) — there the thin side lies on no world axis,
and the face is curved. Controls: the same drawing at 0.05 mm thickness STILL
BUILDS, and its world box remains 2828 mm (meaning the new guard fired, not the
old one); a shape thin ALONG A WORLD AXIS still gets `thin_body` (the guard is
not weakened); legitimate shapes get no false refusal.

### 🔴 NAMED LIMIT: ON REPAIR THE BODY MOVES, BUT DOES NOT ROTATE

`raise_clear_body` moves the body by a TRANSLATION of the frame. Rotation is
not performed during repair, and the reason is not that rotation is hard —
`rotate_body_frame` exists in the tree and is verified — but that **THERE IS
NOTHING TO SET IT FROM: the analysis report carries no angle.** A finding
(`kir/clash/project_analysis.Finding`) carries `depth_mm`, `gap_mm`,
`overlap_volume_mm3`, `required_clearance_mm`, `deficit_mm`; the precise
detector (`kir/clash/detect.Finding`) adds
`certified_separating_translation_mm` — a certified separating
**translation**, a vector. No field of either finding carries an orientation,
an axis, or an angle. So a fixer that rotated the body would be CHOOSING the
angle itself — that is, inventing on the author's behalf a decision the
analysis never made. The limit is lifted not by fixer code but by an angle
appearing in the analysis report; until then it is recorded as a limit, not
implied.

## An authored body IS REPAIRED — by translating the frame (2026-09-07)

`raise_clear` raises the body by editing the authored parameter — a box at
`instance.parameters[output.key]`. An authored program has no such box: all
bodies of one instance share ONE set of parameters, and shape is set by
registry operations. Measurement: the pair `tower-c/plinth × tower-c/shell`
(contained, depth 3600 mm) was not fixed by anything — «raise_clear needs a
box parameter named 'plinth' on instance 'tower-c'».

Editing the shared parameters was NOT ALLOWED: `validate_geometry_bindings`
checks EVERY body's manifest against the owning instance's parameters, and
neighboring bundles would become mismatched (verified: the store answers
`parameters_mismatch`).

So a second strategy was set up, `kir.project_fix.RAISE_CLEAR_BODY`
(`"raise_clear_body"`): THE BODY ITSELF moves — by translating its frame
(`geometry_authoring.rebind_body_frame` -> `GeometryBundle.with_frame`). Shape,
recipe, parameters, binding, and tolerance do not change; `body_sha256` is
required to stay the same, and this is VERIFIED, not promised.

🔴 THE TRANSLATION DOES NOT CALL THE KERNEL, AND THAT IS THE FIX. The first
revision moved the body via `read_body()` -> `capture_body(frame=…)`. For a
flat prism the ASCII BRep survived this round-trip byte-for-byte, but for a
LOFT it did not: parsing + `BRepBuilderAPI_Copy` + writing re-issued the
B-spline side surfaces differently, `body_sha256` drifted (e09f9279814a ->
88464fb690b8), and the curved body "did not move." The bundle's BRep, preview,
and measurements are LOCAL and do not depend on the frame at all, so the
translation rewrites EXACTLY ONE manifest field plus the bundle's signature.
Verified by a probe with `_kernel` removed: the translation works, while
`measure()` refuses. Measurement: a lift of 12050.000 mm, findings 1 -> 0, the
neighboring `shell` bundle byte-for-byte the same, instance parameters the
same.

The strategy is picked ONLY by explicit name. The default `raise_clear` still
REFUSES by name and names the second strategy in the refusal text: a silent
switch would turn a named refusal into a silent success.

The named refusal `authored_body_needs_recipe_rebind` — for when translation
is not enough: a free axis `p0_mm`/`p1_mm` in the shared parameters belongs to
the instance, and shifting it for one body would carry its neighbors along.

## MEP: an authored pipe carries its own system and its own ends (2026-09-08)

The repair profile (`kir/clash/repair_profile.py`) read the language's MEP
words only from `instance.parameters` — that is, only for an element that came
FROM CAPTURE (a mass with a box and `metadata.source_category`). An authored
program places the op's fields somewhere ELSE: `author_project` copies the
operation's payload into `NamedOutput.operation` verbatim. Measurement by a
probe on 2026-09-08: a revision with the scene «slab × authored `create_duct`»
(system `ОВ приточная` by selector, axis `[1000,1000,200] -> [5000,1200,400]`,
slope 4.9937617 %) yielded `repair_profile.classify(...) is None` — the
profile treated the duct as a plain MASS, and `propose_fix` refused with the
wrong words: «raise_clear needs a box parameter named 'run' … this output's
shape is parameterised otherwise», that is, about PARAMETERIZATION where the
question was about TYPE.

A PRODUCER was set up, `kir.geometry_materialization.mep_fields`: registry
operation -> the same words the language itself uses to declare a run. Not one
new field name and not one new table:

| what it gives | the language's word | source |
|---|---|---|
| ends as connectors | `nodes` + `segments[{from,to}]` | the op's `p0_mm`/`p1_mm` (`ops_mep`) |
| axis | `p0_mm`/`p1_mm` | the same, verbatim |
| system membership | `system_type` | the op's selector (`{by,value}`) |
| slope floor | `segments[].slope_min_pct` | the op's graph, as declared (KIR-X004) |
| category | `category` | the REGISTRY, `kir.spec.op_result_categories` |

The list of ops is CLOSED and equals the registry's list: 11 operations whose
category lies on the `mep` side of the `kir.clash.hulls.KIND_TABLE` table — 6
single ones (`create_pipe`, `create_duct`, `create_cable_tray`,
`create_conduit`, and two stubs), 3 graph ones (`create_pipe_system`,
`route_pipe_system`, `route_duct_system`), and 2 flexible ones
(`create_flex_duct`, `create_flex_pipe`). The equality "11 = 11" is guarded by
a test, not by a promise
(`kir/tests/test_an_authored_pipe_carries_its_system_and_connectors.py`).

Nothing is STORED: the fields are derived from the operation on every read.
There is no second copy of the same numbers in the revision, so there is
nothing for it to drift apart from the first.

🔴 A NEW NAMED REFUSAL, `mep_axis_slope:<slope>`. For a run declared with a
slope, the refusal carries the NUMBER ITSELF in percent: in the probe above the
slope is 4.9937617 %, and the refusal reads
`repair_profile_unsupported:mep_axis_slope:4.99376`. It is printed with
`:.6g`, not `:.6f`, and that is not cosmetic: `:.6f` would turn 2.5e-14 into
"0.000000", meaning a refusal ABOUT A SLOPE would say there is no slope. The
order inside the MEP branch is: the declared slope floor (`slope_declared`,
KIR-X004) -> the slope of the declared axis (`mep_axis_slope`) -> the category
(`mep_category`). `mep_category` would say "this is a duct" where the question
was "how much is it inclined." There is NO threshold on the comparison and none
is needed: the very `z` values the author wrote are compared; equal `z` values
mean the run is declared horizontal, and the refusal again names the category.
A riser has no horizontal length, so the slope is NOT DEFINED — and there is no
number in the refusal either. For a flexible polyline axis it is not produced
at all: the chord between the ends is not an axis, and naming its slope would
mean printing a number the author never wrote.

🔴 A SIDE MEASUREMENT FROM THE SAME WAVE: THE PROFILE WAS READING THE WRONG
SHAPE. `ModuleInstance` freezes parameters (`kir/project.py`, `_object` ->
`_freeze`): a nested object becomes a `MappingProxyType`, a list becomes a
`tuple`. The profile's checks asked for EXACTLY `list` and EXACTLY `dict`, and
on a REAL instance (not a test's stand-in) they saw neither the graph nor the
slope floor:

    _segments(inst.parameters)            -> []      (a `tuple` of 2 edges lay there)
    _declared_slope(inst.parameters)      -> None    (floor 2.0 lost)
    _has_connector_graph(inst.parameters) -> False   (graph of 2 nodes lost)

A run with a system was, meanwhile, refusing with
`system_membership:'ОВ приточная'` — a name with no number; a run WITHOUT a
system and WITHOUT an MEP category passed as SUPPORTED, that is, it got a
SILENT SHIFT exactly where the profile was set up to prevent one. The defect
went uncaught because the probe checked a substring against the FULL text of
the refusal, and into that text `propose_fix` splices `describe()` with ALL
the names at once: `assert "slope_declared" in str(error)` was green for any
refusal whatsoever. Now `Mapping`/`Sequence` are read, and the probe checks the
refusal's CODE (everything up to the first `": "`), and the helper itself has a
control.

What did NOT change: a free mass segment (`free_segment_axis`) is still
SUPPORTED and travels by a world vector together with its axis — the producer
says nothing about `create_directshape`. Capturing MEP fields is still not
produced. There is no live Revit here.

## What is still not proven

There is no measured upper bound on mesh deviation from BRep, no stable face
topology across edits, no sandbox for hostile BRep, no native BIM refinement,
and no Revit execution. A saved materialization sidecar by itself is a
declaration, not new proof that the kernel ran. A single `invocation_completed`
is likewise not enough to accept a model: see the [runtime
contract](RUNTIME_RESULTS_RU.md).

The viewer displays declared DirectShape triangles regardless of whether a
clash hull or a supported clash category is present. Refusal of an
unrepresentable mesh does not corrupt the next object; display coverage and
clash coverage are named separately. This is not proof of native shape or of
clash-detection sufficiency.

## Composite residential complex: a new standalone path

The [composite example](../examples/residential_with_podium.py) preserves the
original `/1` root with three towers, an explicit `/2` upgrade, the podium
body, schematic section A, and a subsequent height/setback edit. The
sources/parameters/outputs of B/C and of the podium remain unchanged when A is
edited. Section A explicitly loses the concept twist/taper; this is a design
rework, not a faithful conversion into native BIM.

A full **stipulated display slice**, not a complete BIM model, is available
through `export_standalone_scene`: it writes one inertly verifiable file, which
`load_display_artifact` reads back. An example of continuing an already-saved
project:

```python
from examples.residential_with_podium import continue_section, materialize_saved
from kir.project_store import ProjectStore
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.standalone_export import export_standalone_scene

# NEW SQLite можно создать отдельно через example --store NEW.sqlite --stage refined.
store = ProjectStore.open("residential.sqlite", readonly=False)
continue_section(store, expected_revision=store.head().revision_id,
                 height_mm=4500., setback_mm=1200.)
materialized = materialize_saved(store)  # Явная native BRep derivation, не inspect.
display = export_standalone_scene(
    materialized, consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
with open("display.json", "x", encoding="utf-8") as stream:
    stream.write(display.dumps())
```

The file is read back by `kir.viewer.standalone.load_display_artifact`, which
verifies its bytes, schema and addresses without running the kernel, recipes or
Revit, and without editing the project. (The loopback inspector that used to
serve this file in a browser was removed on 13.09.2026.)

The artifact preserves the original binary scene and separate proxy records.
The podium remains a mesh freshly derived from the pinned BRep; B/C remain
native `create_solid_blend` in the authored program and C# lowering, and are
not silently replaced by a DirectShape mesh. Their amber profile-proxy
preserves the authored end faces and shows twist/taper with no guarantee of
Revit vertex matching, containment, clash eligibility, or native BIM. Without
an explicit capability these outputs get an addressed `capability_required`,
not approximate geometry by default.

After section refinement, the inspector shows the podium, proxy B/C, and 15
`no_body` wall/room ghosts. Six outputs — three levels and three
`create_floor_by_contour` — are listed separately as omissions. So "all towers
are visible" does not mean native walls/floors are shown or that the whole
building has been checked. The `publication_report.scene` field of the old CLI
example still describes only the legacy binary scene; it does not qualify the
whole composite display. A separate negative test records the absence of B/C
in the legacy binary and does not conflate it with the missing floor slabs.

The end-to-end acceptance includes a fresh-process SQLite reopen → section
edit → materialize → standalone export/input validation, and 2023/2026
codegen. A separate real browser also checks the saved/reopened variant:
WebGL vertices of the original B/C end faces, twist/taper, material, raycast,
and pixels; the podium's binary vertices are checked with the project-mm
origin restored. This is not live Revit acceptance.

Current test counts and open integrations are in the [delivery
registry](DELIVERY_PLAN_RU.md). The first low-level OCCT slice and its saved
preview/fallback contract are in [GEOMETRY.md](GEOMETRY.md).

## Placing an authored body: translation, ROTATION, and permitted mirroring (2026-09-07)

The bundle's frame is a rigid right-handed transform local-mm → project-mm.
BRep, preview, and measurements are LOCAL and do not depend on it, so placement
DOES NOT CALL THE KERNEL: `with_frame` rewrites one manifest field and
rehashes, and `body_sha256` stays the same BY CONSTRUCTION.

| move | what changes | `body_sha256` |
|---|---|---|
| `rebind_body_frame(world_delta_mm=…)` | the translation column | the same |
| `rotate_body_frame(degrees=…, axis=…, about_mm=…)` | rotation and translation | the same |
| `mirror_body(normal=…, through_mm=…)` | THE SHAPE ITSELF | DIFFERENT |
| a mirror recorded into the frame | — | refusal `invalid_frame` |

`rotate_body_frame` composes a Rodrigues matrix around a world axis with a
pivot point; frame validity is checked by `_frame` — the sole carrier of the
law (orthogonality, det = +1). Measurement: −37.5° after +37.5° around a
slanted axis returns `IDENTITY_FRAME` to a precision of 1e-9.

`mirror_body` is that very «separate orientation contract» demanded by the
`invalid_frame` refusal. THE BODY is mirrored (`gp_Trsf.SetMirror` about a
plane), the frame remains a right-handed triad, so none of the three readers
silently flips the normals. This is verified, not promised: volume and face
count are preserved (mirroring is an isometry; otherwise `mirror_lost_volume`),
and `body_sha256` is required to CHANGE (otherwise `mirror_did_nothing`).

A MEASURED LIMIT OF INVOLUTION. A double mirror about the same plane returns
the same SHAPE (volume, centroid, bounding box, and face count all match), but
NOT the same bytes: the "parse → `BRepBuilderAPI` → write" round trip re-issues
the ASCII BRep differently. This is the same fact that is why translating the
frame does not call the kernel at all.

The instrument: `kir/tests/test_a_placed_body_reaches_three_readers_the_same_way.py`,
13 runs — four placement moves (translation, rotation about Z, rotation about
a slanted axis, mirroring the body) pass the `geometry_readers.one_geometry`
cross-check across three readers with `limits == []` and `unnamed_by == {}`.
FAIL control: a reader left on the previous frame gives
`reader_disagreement`; rotation without a pivot point — 1 red.
