# B01: binding a submitted project to a prepared execution

`kir.project_submission.bind_project_submission(project, materialized, prepared)`
creates an immutable, factory-only `SubmittedProjectBinding`. This is
**only a pure association seam**: calling the binder itself saves and sends
nothing. An explicit `SavedExecutionRecord.create_project_new(path, prepared, binding)`
now saves the association and the source input together in
[Archive/2](SAVED_PROJECT_EXECUTION_RU.md).
The raw KIR/Archive/1 path keeps its previous behavior with no project
association. `publish_materialized_project` includes these steps before
execute in the shared first-send pipeline; see
[the order and boundaries of publication](STANDALONE_PUBLICATION_RU.md).

## Why this is needed

Two revisions that differ only in project metadata can have identical
materialized operations, plan, and full C#. The current execution archive
correctly accepts both fresh artifacts as one execution input, but does not
know which authoring revision the caller chose for publication.

The new binder ties in **the exact snapshot that was passed**, and does not
try to reconstruct the single source from the source SHA or a stable output
ID. An instance's metadata/parameters can also change without changing the
geometry payload — so the digest of the whole instance is saved, not just
the digest of its outputs.

```python
from examples.residential_with_podium import materialize_saved
from kir.project_submission import bind_project_submission
from kir.revit_connector import prepare_execution

project = store.head()
materialized = materialize_saved(store)
prepared = prepare_execution(materialized.planned, target=selected_target,
    precondition=captured_precondition, operation_id=assigned_operation_id,
    bulk=materialized.planned.bulk)
binding = bind_project_submission(project, materialized, prepared)
```

If the head has changed between the two reads, the binder refuses instead of
associating with a foreign revision. For a deliberately chosen historical
revision, materialize is called directly with this immutable snapshot and
its assets. The binder itself runs neither the compiler, the recipe, nor the
kernel.

## Checked correspondences

- The exact types ProjectRevision, GeometryMaterialization, and
  PreparedExecution; JSON and other carriers do not become a fresh binding.
- Full canonical equality of project and materialized.project, including
  revision, metadata, definitions/pins, and outputs.
- The materialized envelope/order/IDs correspond to the actual
  NamedOutputs. Body outputs add only the mesh to their declared template.
- The prepared and materialized plans match in the full
  `to_evidence_dict()` and in units; the parent of the grounded evidence and
  the full source SHA are checked separately.
- The body descriptor is consistent with the bundle/body/mesh digests
  sidecar; the mesh in the prepared plan matches the materialized mesh. This
  is not a repeated BRep derivation.
- Each planned op, through the actual source index/ID/op/macro provenance,
  belongs to exactly one NamedOutput; each source output has compiled
  coverage.

The `materialized.planned` input keeps the source plan object. `to_program()`
creates a new plan, and `planned.to_ops()` can lose provenance. A test with
`stack` gets identical C# but a different plan digest after such a replan;
the binder refuses. Units are compared separately, because the compiler
plan hash does not include them.

## A compact result, with no second body store

The binding contains the project ID/schema/revision,
materialization/program/plan digests, units/grounded digests, and the
original execution binding. For each instance — a whole-snapshot digest and
a module-definition digest. For an output — the instance/module/output keys,
the stable output ID, the authored/materialized payload digests, a list of
the compiled ops that belong to it; for a body — the descriptor, the mesh
digest, and the sidecar digest.

The full Project/recipes/parameters/refinement metadata stay with the
ProjectStore; the full mesh/BRep stay with the existing
materialization/assets; the full C#/plan evidence stays with the execution
archive. The binder does not copy these large payloads and does not prove
that the ProjectStore ever saved the passed snapshot at all.

## Arities are not mixed together

- A `stack` Project output is legitimately mapped to several planned ops
  after the accepted bounded ID expansion; the original parent ID stays in
  the provenance.
- `create_group` has one outer planned op and separate nested contracts. The
  binding stores the count/digest of these contracts, not invented global
  NamedOutput IDs for group members.
- `route_duct_system` can have one planned op with a `many/segment_ids`
  result. The result contract is read from the real plan, with no second
  table of native arity. For preparation with no census, the test
  explicitly supplies the system/duct type ElementIds; the test does not
  assert that these IDs exist in Revit.

## Honest boundaries

The native `OperationInputBinding` contains the target/operation
UUID/source SHA/precondition, but **not** a project revision or a submission
digest. So two metadata-only revisions with the same operation
UUID/precondition can have different SubmittedProjectBindings and one native
execution input. The new digest distinguishes the caller's chosen
associations, but does not force the native receipt to confirm Project
metadata or unique original authorship. Even a future Archive/2 by itself
will not give a global per-operation association CAS if the caller picks a
different archive path. Coordinator/native-binding policy remains separate
work; the protocol or the C# source comments are not changed here for the
sake of an artificial distinction in identity.

The `GeometryMaterialization` constructor checks program/plan/descriptor
consistency; it does not confirm BRep equivalence or that the recipe ran.
The binder does not strengthen this contract. Native IDs are not created or
attached, there is no dispatch/retry permission, and engineering acceptance
is not proven.

The result has `to_dict/dumps`, but not `loads/from_dict`, no execute API,
and no PreparedExecution reconstruction. JSON holds saved assertions; hashes
are not the author's signature. Frozen values are no protection against
hostile Python in the same process.

`validate_submission_claims(value, execution=..., plan_evidence=...,
planned_units=..., grounded_evidence=...)` is a separate inert algebra owned
by the Archive/2 loader. It checks the exact shape, hash, and addressed
links against the supplied retained execution facts, returns only `None` or
a named refusal, and never creates a fresh SubmittedProjectBinding. Byte/
depth budgets belong to the archive decoder. Without the full Project/BRep
in this record, the instance/output/module/materialization digests cannot
be recomputed; they remain declared references, not proven payloads. When a
fresh binding is present, the full `require_matches(..., submission=binding)`
also catches their discrepancies.

After change A, the old binding still names revision R0. In R1 you can
compare the exact instance digests B/C/podium and detect the changed A. But
payload-equal does not mean native-realization-current: a separate readback
against the original runtime/document is needed. Resubmitting a
create-program with a new operation UUID does not thereby turn, through this
link, into a native update plan.
