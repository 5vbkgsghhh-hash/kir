# Checking a change to the authored section plan

`kir.section_plan_acceptance` checks a small set of falsifiable XY
properties after a schematic refinement. This is not a "the building is
fit" verdict, not a geometry-to-BIM proof, and not a Revit simulation. The
result **contains no overall pass/accepted**.

## Input and the accepting caller's policy

```python
from kir.section_plan_acceptance import assess_section_plan_change

result = assess_section_plan_change(
    before, proposed, source=original_concept_revision, instance_key="tower-a",
    required_void_chain=["storey-01-slab", "storey-02-slab", "storey-03-slab"],
    protected_instances=["tower-b", "tower-c", "podium"])
report = result.to_dict()
```

All three snapshots are exact `ProjectRevision` instances. `before` and
`proposed` must have a qualified authored refinement of the selected
instance; both links are re-checked through `refinement_view` with the
supplied source. The source can be historical, not the direct parent. This
is not an ancestry check in the store.

`required_void_chain` is one **explicitly chosen** chain of at least two
distinct floor-output keys. All keys must exist as slabs in the baseline;
the order must increase by the actual elevations of the levels the
operations reference. A repeated key, a non-floor, equal/reversed
elevations, an unknown protected key in the baseline, and protecting the
very section being edited produce a named `invalid_section_policy`. An
unresolved selector is not a guessed elevation of 0: the corresponding
continuity check remains `not_evaluated`.

The caller decides that these openings represent a shaft to be preserved
vertically. The consumer does not infer this from the word `slab`, a floor
number, metadata, or the presence of any hole. For the first subset, each
selected slab must have exactly one straight-edged hole; multiple holes
are not matched by similarity.

Removing a known required hole from proposed (`holes=[]`) is a definite
`violated: selected_void_missing`, also for neighboring continuity pairs.
This is not unmeasurability. If the hole was already absent in the
baseline, its existence is not invented: retention remains
`not_evaluated: no_void_in_floor`.

## The real owners of the geometry

The input program of the selected section is assembled from the existing
NamedOutputs and `output_id`, with no regeneration and no substitution of
width/depth/height parameters. The podium outside the section is not
materialized, and OCP is not called.

1. `project_selection.selected_instance_program` adds the transitive
   explicit dependencies of the selected outputs: for example, wall/floor
   type declarations from a separate instance. The registry-slot analysis
   from project_diff is used; the project's order and all operands are
   preserved. Missing/late/wrong-kind refs, unknown selected operations,
   and body-owned dependencies produce a refusal; the latter require a
   separate materialization. External backend selectors remain in the
   program for grounding, rather than being removed for the sake of the XY
   check. The actual `compiler.plan_program` is called for both selected
   programs together with their dependencies; the program/plan digests
   relate to this closure. Invalid operations produce
   `invalid_section_program` with the source compiler refusal. Important:
   `design_check.spatial_model_from_ops` by itself checks only SOLO_OPS
   mixing through `_refuse_if_unbuildable`, not the whole compiler
   contract.
2. The geometric scope remains **only the outputs of the selected
   instance**, not all the added dependencies: an outside wall cannot
   silently close off its room. The existing public
   `spatial_model_from_ops` builds rooms from the actual wall axes through
   polygonize. `close_tol_mm=0` is passed: extending by the standard
   100 mm here could hide a gap in the authored plan.
3. `contour.validate_region` checks the actual floor outer/holes; then
   `edges_are_straight`/`edges_vertices` qualify the polygon for Shapely.
   Arcs and splines are not turned into chords for the sake of a green
   result.
4. Room/slab association is built from the actual
   `level={by:ref,value:<level-op>}`, not from output naming. `by:name`,
   external selectors, and ambiguous slabs remain a limitation. If an
   unresolved floor could belong to any level, the consumer does not
   silently pick a different slab.

## What the report's rows establish

| Predicate | Property checked |
| --- | --- |
| named_subject_retained | The baseline/proposed named outputs did not vanish and were not added unnoticed |
| room_axis_enclosure | The room's point belongs to one closed face of authored axes, with no wall extension |
| room_seed_in_slab_xy_region | The point is strictly inside the single slab region of this level, with holes subtracted |
| selected_void_footprint_retained | The explicitly selected hole footprint is geometrically equal to the baseline |
| selected_void_chain_xy_continuity | The footprints of neighboring explicitly selected holes match in XY |
| protected_instance_snapshot | The protected whole instance, including parameters/outputs/metadata/module pin, is unchanged |

Statuses: `evaluated` — the specific predicate was checked and holds;
`violated` — a counterexample; `not_evaluated` — a named insufficiency of
the input/method. Lists of expected subjects are included in the report. A
room/slab that disappeared does not shrink the denominator; the absence of
rooms in both inputs at once does not give a vacuous success.

Lengths are project-local mm, areas are mm². The metadata frame/units do
not transform the operations. Void equality is topological equality of
planar sets, not string equality of the vertex order; the symmetric
difference is reported as a diagnostic. This is a strict program-level
profile with no construction tolerance and no promise of clearance. A
point on the boundary is not counted as a confirmed interior point.

## Permanently unchecked axes

**Always** `not_evaluated`: vertical placement, room boundary-hole
exclusion, native realization, structural safety, runtime liveness, and
engineering adequacy. Declared offsets are listed for vertical placement,
but not evaluated.

For example, `base_offset_mm=500` can leave the correct XY closure intact.
This does not mean the wall physically stands at the right level: the
existing SpatialModel keeps a height, not the wall's full absolute Z
geometry. And point-in-slab checks only the seed, not the full boundary of
a Revit Room and not the shaft enclosure. Floor height, slab
thickness/type, and clear height are not proven.

## Refuting controls

Three legitimate operations preserve valid lineage/roles and pass the
actual planner, but turn red regardless of the generator:

- The end of a middle-level wall is shortened by 1000 mm: 2 of 3 rooms are
  enclosed.
- The middle room's point `[6000,4000]` lands in the shaft hole: enclosure
  by walls is 3/3, but one point is outside the slab material XY region.
- The middle slab's opening is shifted by 3000 mm in X: enclosure and room
  seeds are correct, but two adjacent symmetric differences equal
  8,000,000 mm².

Separate controls preserve an equivalent ring under a change of
direction/starting point, name unknown levels/curves/multiple holes, and
show the offset's invisibility to the XY checks. This is not an attempt to
declare the list a complete engineering audit.

## Preservation and authority

The consumer writes nothing: there is no store commit, artifact mutation,
or Revit calls. A saved snapshot can be loaded, a proposed prepared, and
evaluated before the accepting caller's decision to commit. A proposal
that does not pass does not change the head/assets.

The report contains the exact before/proposed revisions, the source output
digest, the selected program/plan digests, and the caller's policy. The
full project is not compiled, and bodies outside the section are not
read. `to_dict` is detached; `dumps` only carries assertions across, and is
not proof of a new execution. No source pin, Project/Store schema, or
BuildingGraph relation is added.
