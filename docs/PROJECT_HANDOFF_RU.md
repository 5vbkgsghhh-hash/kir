# Handing off a sealed evaluation to explicit authoring

`handoff_instance_to_explicit(project, instance_key, *, new_module_key,
expected_revision)` creates one new ProjectRevision. This is an explicit
change of ownership of the source authoring snapshot, **not a publication or
a change in Revit**.

```python
from kir.project_handoff import handoff_instance_to_explicit

base = store.head()
proposal = handoff_instance_to_explicit(
    base, "tower-a", new_module_key="tower-a-explicit",
    expected_revision=base.revision_id,
)
# Handoff itself saves nothing. The Store performs its own expected-head CAS.
store.commit(proposal, expected_revision=base.revision_id)
```

The owner of truth is the existing `ModuleDefinition.owner`. The helper adds
a new module `owner="explicit", recipe=None`; the selected instance gets its
key and definition digest. The old modules, including the full RecipePin with
the source code and the environment/dependency digests, remain literally
unchanged. Other instances continue to reference their previous definitions.

The instance key, all output keys/IDs, their order and payload, the parameter
values, the remaining metadata, and the project intent/units/frame/IR/schema
are preserved. Inherited `refinement` and `refines` are not rewritten. So a
change of ownership does not turn a schematic redesign into a geometrically
correct conversion. Parameters are now **historical inputs**, not active
commands to the previous generator. The existing residential-complex
generator will refuse if asked to regenerate such an instance under the
previous recipe: its module pin is already different.

## Historical reference

An entry `kir-instance-ownership-handoff/1` is added to the free slot
`instance.metadata["ownership_handoff"]`:

- `source`: project/revision/instance, the digest of the source instance, the
  module key/definition digest, and the digest of the ordered outputs;
- `target`: the new explicit module key/definition digest;
- `parameters_role`: `historical_inputs_not_generation_controls`;
- boundaries: the recipe/compiler/geometry/native execution were not run,
  the helper does not establish history preservation.

This is a compact reference to the old evaluation, not a copy of the recipe
and not a new database. The old revision ID does not depend on the content of
the new revision, so there is no cyclical reference to its own content hash.
The record describes **the moment of handoff**: a later legitimate explicit
edit of the outputs does not mean they still equal the source evaluation. The
Project JSON itself remains an inert draft; a loaded or manually written
metadata block is not proof that the helper ran. A consumer of the historical
link must check the actual source snapshot and its digests, not trust the
single word `schema`.

## Refusals and boundaries

`HandoffError.code` names a missing instance, a wrong key, a taken module
key, an owner that is not `sealed_evaluation`, a taken metadata slot, or
body-owned outputs. Even `ownership_handoff=None` cannot be silently
overwritten. A stale `expected_revision` preserves the Project's existing
`RevisionConflict`. Body-owned outputs refuse in the first slice, because
their assets have a separate recipe/module binding. The podium is not handed
off to a different owner.

The presence of a recipe on the source sealed evaluation is not proof it was
run. A source `recipe=None` is also allowed: the unknown provenance stays in
the previous definition rather than being filled in with an invented pin.
Compiler validity and the native/engineering fitness of the outputs are not
checked; a legitimate inert draft and an unknown IR are not promoted to a
valid model here.

For the first native-update pilot the order is: sealed A → handoff → save →
**first** publication of explicit R0 → a separate proposal to change a
level. The helper does not re-bind an already-published sealed A to the
native model. Resubmitting all create operations is not an update and can
create duplicates.

## Checks

`test_project_handoff.py` checks /1 and /2, the exact payload/IDs/pins,
scalar types, order, the bans on overwrite/body-owned/stale input, and the
absence of compiler/kernel/runtime imports in a fresh process. A real saved
residential complex passes through:

1. The podium and typed schematic section A → handoff with no write to the
   Store.
2. An explicit commit; a competing proposal from the old head is refused.
3. A new Python process opens the Store without OCP and changes only the
   second level's mark 3600 → 3800 mm as explicit authoring, then explicitly
   saves it.
4. The diff shows 1 changed, 6 affected, 17 unchanged; B/C/podium, assets,
   and the previous pins are unchanged; the existing `refinement_view`
   remains correct.

These are authoring/history checks. Native publication, update, readback,
and engineering sufficiency are not proven by them.
