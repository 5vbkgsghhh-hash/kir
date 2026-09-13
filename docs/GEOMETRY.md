# Optional OCCT geometry: accepted first slice

This source-checkout feature retains a real boundary-representation body outside
Revit, with a separately identified triangle fallback. It uses the existing OCCT
kernel through Python, not a new CAD expression language inside KIR. A body is
not a BIM element; “exact representation” does not mean exact arithmetic.

## Run the bounded example

Install the optional dependency in a development environment, not a serving
environment:

```bash
python -m pip install -e '.[geometry]'
PYTHONPATH=. python examples/curved_podium.py --stage changed
```

The example explicitly constructs a smooth five-section loft, cuts a cylindrical
atrium, saves and loads the project and body bundle, then changes the bulge and
atrium radius. Stdout is one JSON artifact containing both values. It does not
write files or contact Revit. This low-level example is separate from the
durable [composed residential workflow](../examples/residential_with_podium.py),
which uses body-owned outputs and transactional geometry assets. Its bounded
standalone display path now combines the original binary podium mesh with
explicitly opted-in approximate tower profile proxies. Native BIM and live
acceptance remain unverified; walls/rooms may be ghosts and slab/level omissions
remain visible. See the [display contract](PROJECT_GEOMETRY_RU.md#составной-жк-новый-standalone-путь).

`kir.occt_geometry.capture_body` accepts an OCCT shape and returns an immutable
`GeometryBundle`. `loads` checks a bounded JSON manifest, hashes and encoding;
it does not import OCP, parse native geometry or execute saved Python.
`read_body` and `measure` explicitly parse the retained BRep with the pinned
kernel. They are not a sandbox for hostile native input.

## Authored path: registry ops, not a trusted example (2026-09-07)

Until this date rich geometry entered a project through exactly one route: a
trusted Python example (`examples/curved_podium.py`, `examples/podium_passage.py`)
that imported OCP itself and called `capture_body` on a shape it had built by
hand. Neither `kir.dsl`, nor `kir.sdk`, nor a sandboxed author script could
reach it: their output is flat IR. Measured before the change: a `kir.dsl`
program with `create_solid_blend` + `create_solid_boolean`, saved into a
`ProjectStore`, reported `bodies_declared 0 / bodies_with_geometry 0`.

`kir.geometry_authoring` evaluates the EXISTING registry ops
(`create_solid_extrusion`, `create_solid_blend`, `create_solid_boolean`) with
OCCT and captures each body through the same `capture_body`. No new op, no new
expression language, no field outside `ParamSpec` is read.

```python
from kir import dsl
from kir.geometry_authoring import author_project

program = dsl.build()                        # ordinary KIR JSON
revision, assets = author_project(program, project_id=..., recipe=pin,
                                  parameters=inputs)
```

The real authoring workflow keeps the sandbox boundary intact:
`sandbox.execute_author_script` (separate process, chroot, no network, no OCP)
-> `project_recipe.bind_recipe_result` -> `geometry_authoring.attach_recipe_bodies`
-> `project_merge.accept_proposal`. The author script never executes native code;
the trusted caller builds the bodies from the ops the script named.

What this does NOT establish: that Revit will build the same solid. The blend
side surface is `BRepOffsetAPI_ThruSections` with a ruled section here, while
Revit's `CreateLoftGeometry` documents only "blending smoothly". No volume
equivalence is claimed or checked. Profiles with arcs/splines, rotated `rect`,
a non-default `plane` and reflected frames are REFUSED BY NAME, not silently
approximated.

Named refusals of the evaluator: `unsupported_op`, `unsupported_profile`,
`empty_boolean_result` (a difference/intersection that consumed the body -
never a silent empty compound), `degenerate_body` (volume below the tolerance
cubed), `thin_body` (a bounding-box extent at or below the tolerance),
`kernel_boolean_failed` / `kernel_loft_failed` / `kernel_capture_failed`.

## One geometry, three readers (G02, 2026-09-07)

`kir.geometry_readers.one_geometry` folds the standalone scene descriptor, the
clash analysis report and the materialized emission rows into ONE identity per
body: `bundle_sha256`, `body_sha256`, `revision`, `frame`,
`modeling_tolerance_mm`. Disagreement is `reader_disagreement` naming the field
and both values. A field a reader does not state is recorded in `unnamed_by`;
it is never borrowed from a neighbour.

`modeling_tolerance_mm` now travels in the materialization source rows, so the
scene and the emission both state it. The clash report still states neither the
bundle/body digest nor the modelling tolerance, and keeps the frame only as an
object field outside `to_dict()`; that gap is named in `unnamed_by`, not hidden.

## Authority and limits

| Value | Establishes | Does not establish |
| --- | --- | --- |
| BRep bytes and body digest | Identity of a retained OCCT representation | BIM category, engineering adequacy or stable face names across edits |
| Recipe/environment pin | Declared source and dependency identity | That the source executed, or complete environment reproducibility |
| Saved measurements | Assertions made when captured | Trustworthy current facts after arbitrary reconstruction of a bundle |
| Explicit `measure()` | Facts recomputed from the parsed body | Equivalence to its saved preview |
| Saved preview | A bounded triangle representation and its digest | A measured maximum deviation from the body |
| `fallback_op()` | Existing KIR DirectShape operation from the saved preview | A native editable wall/slab, or revalidation against BRep |

The first capture contract requires one valid solid without stray topology.
Coordinates are local millimetres; the frame is a right-handed rigid transform
to project millimetres. Scale, shear and reflection are refused. The frame is
applied to fallback vertices and preserved when the example is regenerated.

Tessellation deflection and modelling tolerance are requested kernel settings,
not a measured Hausdorff/error bound. `measured_upper_bound_mm` is explicitly
unknown. Exceeding a triangle/vertex budget refuses instead of silently
coarsening. The normal KIR fallback budget remains 4,096 vertices and triangles;
larger adapter budgets do not enlarge the compiler contract.

The bundle has bounded ASCII V3 BRep bytes without attached triangulation, a
manifest, and a saved preview. Face identity is bundle-local. Native parsing and
construction currently have no process-level CPU or memory isolation. The
optional binding is pinned in the `geometry` extra in `pyproject.toml`; it is not a new
mandatory dependency of the core package.

## Ownership boundary of this first slice

A consistently rehashed JSON bundle can contain a BRep for a 2,000 mm box and a
saved preview for a 1,000 mm box. Inert loading accepts the assertions; explicit
measurement sees the larger body, but `fallback_op()` still uses the smaller
preview. Hash agreement is not evidence of geometric derivation.

This first example also puts the fallback mesh into an ordinary project output
and stores its bundle separately. This low-level contract alone does not qualify
body-owned publication: that requires a typed body reference and an explicit
geometry realization boundary deriving the published/viewed mesh from the
pinned body. Another digest or metadata flag would not close this gap. JSON
loading and authoring diff remain inert; they do not start native geometry work.

The [body-owned successor](PROJECT_GEOMETRY_RU.md) now implements that descriptor,
explicit derivation and transactional asset storage. Its separate acceptance
does not retroactively strengthen this first example's ordinary mesh output or
the low-level `fallback_op()` contract. The standalone inspector is a new
capability-aware consumer, not a repaired legacy renderer: original native blend
operations are retained, and approximate proxies are separate display records,
never native-equivalent surfaces or clash inputs. Four composed visibility
requirements now run through that explicit path, including saved SQLite reopen
and continued editing; the legacy-only incompleteness remains a negative control.

## Recorded verification — 2026-09-05

- 55 focused tests plus 5 independent adversarial tests passed after the
  placement correction. They include real OCCT construction, analytic bodies,
  invalid topology, budgets, strict persistence and fresh-process resumed edits.
- Independent review found that atrium regeneration reset the saved frame.
  The corrected example preserves a 90-degree rotation and a 100 m translation;
  previously saved artifacts remain unchanged.
- A related project/geometry strip passed 224 tests before that correction;
  these overlapping counts are not additive or a full repository suite.
- Both initial and changed example programs pass the existing Python compiler
  for Revit 2023 and 2026. This slice has not been executed in Revit, and those
  compiler checks are not actual C# assembly or native-body verification.

See [the project contract](PROJECT.md) and [the delivery registry](DELIVERY_PLAN_RU.md)
for the remaining geometry ownership, semantic refinement and live acceptance work.
