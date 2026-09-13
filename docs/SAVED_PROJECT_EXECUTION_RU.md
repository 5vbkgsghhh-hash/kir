# Archive/2: the original execution and the chosen caller project association

The new logical schema `kir-saved-execution/2` saves a compact
`SubmittedProjectBinding` together with the previous execution input in
**the same single SQLite record**. The container is unchanged: application ID
KIRS, user_version 1, one `saved_execution` table. This is not a ProjectStore
migration and not a native Protocol/4 extension.

```python
from kir.project_submission import bind_project_submission
from kir.saved_execution import SavedExecutionRecord

submission = bind_project_submission(project, materialized, prepared)
record = SavedExecutionRecord.create_project_new(
    "NEW-project-execution.sqlite", prepared, submission)
record.require_matches(prepared, submission=submission)
```

Both objects must be fresh typed values. A plain dict, loaded claims, or
`None` are not accepted as a submission. The factory checks the references
against the exact prepared evidence before creating the file. Any refusal
before archive acknowledgement or matching means: the caller must not send
execute.

## Backward compatibility

`create_new(path, prepared)` still creates Archive/1 with the previous
canonical bytes, digest, field set, and claims; `project_submission` there is
`None`. The old `require_matches(prepared)` works without the new argument.
Submitting a submission to Archive/1 is an explicit `submission_not_archived`,
not a hidden after-the-fact assignment of a project association.

`create_project_new` does not modify an existing file, including Archive/1.
Automatic migration, overwrite, repair, and adding `project_submission:null`
to old records are absent. The SQLite storage mechanics, budgets, ACL/Windows
VFS limitations, and error semantics remain unchanged.

## What the inert loader checks

`record.project_submission` returns a detached dict, **not** a new
SubmittedProjectBinding. Through the owner, the loader's
`validate_submission_claims` checks the nested schema/hash, the exact
execution binding, plan/units/ground digests, unique and consistent
instance/output addresses, source indexes, full compiled-op coverage,
payload/result/nested-contract summaries, and the body mesh digest against
the retained plan.

Result cardinality is read from the saved plan contract, not from a second
registry. A macro source 1:N and a group nested scope are not turned into
invented native ElementIds. The compiler/recipe/OCP are not run; no
ProjectRevision, GeometryMaterialization, PreparedExecution, or fresh
submission is created.

The full Project, the recipe, BRep, and mesh are not duplicated inside the
association. So their separate snapshot/module/output/bundle/sidecar digests,
which have no source payload here, remain verified only as **claims** in
form. A fully recomputed different instance digest cannot be declared true
against this record; its mismatch with the real fresh submission is caught by
`require_matches`.

## Matching and recovery

For Archive/2, `require_matches(prepared, submission=...)` always requires a
fresh typed submission and compares the full archive payload, not just the C#
SHA/native input. A missing or different submission refuses even with an
identical source. A difference in macro provenance or units also refuses.

After a Python crash, `load(path)` stays read-only. A same-target
`receipt_request` and an explicit `recovery_request` through session B work
without recompilation and without a fresh submission: this is only an
addressed lookup of the original operation A. The record still has no execute
API. An unknown/missing receipt does not grant retry permission. A new
compiler that no longer matches the old input does not prevent reading the
original archive, but cannot pass off a different plan as the original.

## Association is not native attestation

Two metadata-only Project revisions with the same operation UUID,
precondition, plan, and source can have different Archive/2 digests and one
native execution input. The archive distinguishes **the caller's choice**,
while the native receipt still does not contain a Project revision or a
submission digest. It does not attest to this metadata and does not prove
unique original authorship.

A different NEW archive path lets you save yet another caller association;
Archive/2 is not a global per-operation association CAS, a task grant, or
permission to republish. The native journal remains the owner of execution
idempotency. The Protocol and the C# comments are unchanged here.

## Atomicity and limits

The execution and the association are inserted in a single SQLite
transaction. Real process controls stop before and after COMMIT: before the
commit the record does not qualify, after the commit both parts are read
together. Two writers get one exclusive winner; the loser does not overwrite
the association. A post-COMMIT flush failure produces
`archive_durability_unconfirmed` and does not return a successful result,
even if the file can then be read.

This is not live Revit, not a Windows power-loss test, and not proof of
native BIM or engineering fitness. Archive/2 adds no new source/recipe/
geometry guarantees on top of the existing owners.
