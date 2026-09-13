# Explicit wall and floor assemblies for a section

`examples.residential_typed_section` continues the saved schematic refinement:
a separate `section-types` instance introduces two explicitly declared types, and
12 walls and 3 slabs of the section get references to them. Three levels and three rooms
keep their outputs. This is a substantive authorial decision about the assembly, but not
proof of native BIM or engineering fitness.

## Authoring path

```python
from examples.residential_typed_section import add_section_types, edit_section

typed = add_section_types(
    section, source=historical_concept, expected_revision=section.revision_id,
    wall_name="Exterior wall — option A",
    wall_layers=[{"width_mm": 250, "function": "Structure"},
                 {"width_mm": 150, "function": "Insulation"}],
    wall_source_type=wall_seed_selector,
    floor_name="Floor — option A",
    floor_layers=[{"width_mm": 220, "function": "Structure"}],
    floor_source_type=floor_seed_selector,
)
store.commit(typed, expected_revision=section.revision_id)

changed = edit_section(
    typed, source=historical_concept, expected_revision=typed.revision_id,
    height_mm=4200, setback_mm=1200,
)
store.commit(changed, expected_revision=typed.revision_id)
```

Here `section` is an already saved refined snapshot, and source is its exact
historical concept. `wall_seed_selector` and `floor_seed_selector` are supplied by the
caller explicitly: `by:name` or `by:element_id`. The example does not pick "the first type" and
does not hard-code the numeric ID of an observed UniqueId. Names and layers are stored in
the authored type operations; separate `backend_seed_selectors` are named and
checked against these operands on continuation.

For reopening, there is `continue_section(store, expected_revision=...,
height_mm=..., setback_mm=...)`: the source is read from the saved history,
then the generator is explicitly run and a CAS commit is performed. A regular load/read
of the project still generates nothing.

## Preserving decisions and owners

- The library precedes `tower-a` in authoring order. References are obtained
  through a shared `output_id`, not manual temporary IDs.
- The section keeps 21 outputs and the prior typed refinement lineage. Types are not
  mixed into the list of its levels/walls/slabs/rooms.
- The new host generator has a separate sealed module and a declared RecipePin
  for its source, with the dependency digest of the prior geometry generator and SDK.
  Old source/pins/history are not rewritten. This is not a sandbox receipt and not
  a full environment lock.
- Continuation checks the pin and the prior outputs; unknown fields/custom
  geometry are not discarded for the sake of regeneration. Editing height/setback does not change
  the type library, neighboring instances, or their geometry.
- `selected_instance_program` includes the necessary type declarations before
  the section. The planner checks 23 operations; the XY consumer measures only
  the original 21 outputs and does not include foreign walls in the partition.

## What this path does not promise

Material without an explicit `material` does not automatically become concrete. The material
name requires later resolution in the backend. Seed properties outside
CompoundStructure remain partially inherited, including the EndCap on a floor.
Observed type/layer readback and reverse library recovery are not finished.

A separate boundary: the factory checks the created type, but this is not a check
that every wall/slab retained the expected `GetTypeId()`. The current general readback
reads an optional type_name; the name and a successful reference compile do not replace
a check of consumer type identity. This remains a future runtime obligation.

Assemblies have not yet been turned into a physical solids preview with joins/openings. The section
remains with conditional authored reference surfaces; assigning a type does not automatically
improve geometry accuracy or clash coverage.

**Re-publishing a changed section natively is not implemented by this example.**
The exact creation marker depends on the program; after an edit, attempting to create the
same named type may get an intentional refusal. A separate observed
binding/reconciliation is needed, not disabling the ownership guard, re-changing a
shared type, or automatic renaming. Preserving the authoring revision
and compilation are not represented as a safe native update.

For existing lowering, floor holes get an explicit `KIR-E003` on Revit 2021;
openings are not removed to work around the limitation. The 2022-2026 matrix is checked
separately from live execution. Live acceptance for 2023/2026 remains open.

## Completed offline acceptance

MAIN: **156 passed /38.84 s** across the typed section, selected program,
independent selection, section XY, refinement, and podium regression files.
Separately, selected/diff/XY: **104 /8.21 s**; selected + actual two-worker pilot:
**20 /64.50 s**. These runs overlap and do not add up. The helper's author
independently ran their own narrow set, **22 /6.00 s**. Another agent's source
review found no blocker; this is not an additional runtime test.

Matrix complete 23-op section: **12 passed /52.09 s**, no skips.
10 actual CodePolicy/Roslyn compiles for 2022-2026 x atomic/per_op;
2 exact 2021 refusals relate specifically to `contour.holes`, with no C# emitted.
The fixture includes material-bearing layers of both types. It does not check the
actual consumer TypeId, physical geometry, or native execution.

The history with a real OCCT podium is preserved, reopened, and changed;
the prior revisions, library, neighboring snapshots, and BRep bundles are preserved
byte for byte. Stale CAS and an incorrect height do not change SQLite. A separate independent
XY counterexample proves that a foreign wall could have hidden a gap in the shared
set, but the selected-section assessment still reports a violation.
