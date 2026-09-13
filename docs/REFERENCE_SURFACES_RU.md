# Design surfaces of walls and floors

A section can be displayed using the actually specified axes, outlines, and
levels, even when Revit types have not yet been chosen. These are
**surfaces with no thickness**, not physical BIM bodies: the green material
and the inspector explicitly call the thickness, joins, and hosted openings
unrepresented. The source native KIR operations are preserved.

## Enabling it

```python
from kir.viewer.standalone_export import export_standalone_scene
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.reference_surfaces import SURFACE_CAPABILITY

artifact = export_standalone_scene(materialized_project,
    consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY, SURFACE_CAPABILITY])
```

`SURFACE_CAPABILITY = display_authored_reference_surfaces/1` turns on the new
display/2 and transport/2. The old branch with no capability remains
display/1. Given the same upstream codec snapshot, its bytes do not change
because of the new producer; two independent calls to the old scene builder
can differ in `timing_ms`. This is not a guarantee of deterministic
reassembly.

To see the surfaces on an old project, an explicit new display export is
needed. Loading the old display/1 and refreshing the Store panel do not run
geometry or the recipe and do not draw in data that is not in the file.

## Geometric contract

The producer `preview_reference_surfaces(program, bulk=False)` plans the
whole batch once and returns previews or addressed refusals. Source hashes
relate to the source operations; effective defaults are read from the
current compiler contract.

- Straight wall: a vertical surface over the literal XY axis. The bottom is
  base level + base offset. A free top is bottom + height; an attached top is
  top level + top offset, with no default height added.
- Floor: a flat area at level + height offset. The polygon can be concave and
  have several straight-edged openings. The triangles must lie entirely
  within the area, and their union must match the whole area.
- Levels: only exact references to a preceding, directly recorded
  `create_level` with a literal elevation. A name, a Revit ID, a grounded
  selector, or an unknown/later level are not replaced with zero.
- Curves, effectful/query programs, macros/nested scopes, and phases/units/
  defaults outside this profile get a named refusal. An orphan top offset
  also refuses. Other CREATE ops can be present, but their native side
  effects are not modeled.

This is a picture of the source operands, not the result of executing the
whole model. A wall does not get an invented thickness; a floor does not turn
into a slab solid. The surfaces do not take part in clash detection, are not
compiled, and do not replace KIR. Metadata transforms are not applied:
coordinates remain in authored project mm.

## Transport and display

Display/2 keeps the original binary scene blob separate from `surfaces` and
`surface_refusals`. Exactly one of these results is required for each direct
wall/floor output. A refusal is not hidden behind a healthy empty array.

The preview contains the source operation digest, the full plan digest, and
1–2 level dependencies; for a floor, exactly one. The exporter checks the
match against the plan of the source materialization. The loader ties the
hashes and the order of dependencies to the source table. The original
Python canonical bytes are transmitted separately, so JavaScript does not try
to reconstruct Python numeric formatting through JSON.stringify.

The renderer replaces only the identically named `no_body` glyph. Known scene
representations and blend proxies are not displaced; the source fidelity
codes in the blob are unchanged. For surfaces, the scene origin is
subtracted exactly once, then mm are converted to meters. Floor openings
have been checked not just against the mesh but against actual canvas
picking in the browser: the podium below was selected through three
openings.

Limits: 4096 vertices/triangles per preview, plus the overall loader/renderer
budgets. These are runtime limits, not limits of the language. The GPU uses
float32; native geometric tolerance or correspondence to native faces are
not confirmed.

## What the loader checks, and what it does not

It checks the structure, capability, number types, index bounds, hashes,
source/plan bindings, the order of level dependencies, cardinality, and
coverage. It **does not** run the compiler, triangulation, the recipe, OCP,
or Revit.

So a deliberately altered mesh with consistently recomputed hashes does not
become proven geometry of the source. A re-signed filled-in opening can pass
the inert loader; this is separately captured by a boundary test. Belonging
to the dependency source table does not prove the choice of a specific level
from the raw operands. Full geometric derivation is checked at the producer,
and the authenticity of execution/file is not established by this protocol.

## Confirmed fixes in this wave

- The planner removes a legitimate `height_mm=null` from the normalized
  wall. The producer now uses the same registry fallback as the emitter,
  instead of `KeyError`.
- The loader and the JS require one level dependency for a floor; the
  previous tolerance of two was actually reproduced on re-signed data and
  fixed.
- The old codec contains a build time: the legacy compatibility test is
  fixed to compare against one captured snapshot, with no invented
  determinism claim.

On the control residential complex, 12 wall and 3 floor reference surfaces
were obtained; three more room glyphs remain conditional. Levels remain
among the omissions. This is an improvement to the visual check of the
scheme, not the completion of the section's BIM development.

Final check on September 6, 2026: **256 Python tests /23.66s** in the
related strips, after a small exporter refactor — **108 /13.26s**
(overlapping). **26 Node tests /5.71s**, a new Chromium scenario
**1 /37.2s**, the previous browser scenarios **7 /1.7m**. Source/plan/units
bindings, offsets, holes, representation priority, and actual WebGL/picking
were checked. This is not the whole suite, Revit execution, or confirmation
of engineering fitness.
