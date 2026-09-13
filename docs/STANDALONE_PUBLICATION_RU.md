# First publication and continuation after a lost response

`kir.standalone_publish.publish_program` links existing components into
one explicit first send. This is a Python API, not yet an installed application with a
publish button. A Windows connection and independent acceptance of a real model
remain mandatory separate checks.

## Sequence of actions

1. The caller explicitly selects the advertisement of a specific target/session and an allowed
   opaque document key. The file name is not used as a substitute for identity.
2. A fresh context for exactly this process is requested through the client. A foreign,
   incomplete, or no-document response does not allow compilation or an archive.
3. The open-document key is compared to `expected_document_key`. Only
   after a match is the program compiled for the selected target's year.
4. Write-family, credential-bearing request, advertisement deadline, and the
   existence of an absolute client path are checked. Then a single bound `ping` is performed:
   an exact `ready` response of the selected runtime/session, with no context/receipt, is required.
   An error before this point does not create an archive. This is readiness, not write authorization;
   the transport repeats its own input checks before every send.
5. `SavedExecutionRecord.create_new` saves the full source material to a
   **new** SQLite file. A successful save confirmation and an exact
   `require_matches` against the prepared artifact are required.
6. Exactly one transport call is made with the execute request. The response is parsed by the
   existing `assess_connector_write_response`, not a new interpreter.

The native runtime still checks document/revision before the effect: no
preliminary context query freezes the document. The semantic plan and the
byte stream also do not prove the building's independent engineering fitness.

## Call after setting up a real connection

Below, `selected`, `authorized_document_key`, and `coordinator_operation_id` are
explicit coordinator/UI decisions, not an automatically chosen first discovery
record and not a new UUID on every retry after an error.

```python
from kir.standalone_publish import publish_program

attempt = publish_program(
    program,
    advertisement=selected,
    client_path=installed_pipe_client,
    archive_path=new_private_archive_path,
    expected_document_key=authorized_document_key,
    operation_id=coordinator_operation_id,
    bind_view=True,
    bind_selection=True,
)

print(attempt.execution_contract_satisfied)
print(attempt.result.outcome)
assert attempt.intent_verified is False
```

`bind_view` and `bind_selection` are mandatory. `False` deliberately lifts only
the corresponding UI condition, not the document/revision check. The source program
is passed by the caller: the helper does not import the recipe, does not choose geometry assets, and
does not regenerate the authoring project. A previously explicitly materialized KIR is
allowed. Query programs are not routed through this write-only workflow.

For a saved project, explicit materialization is performed first, then
**`materialized.planned`** and `bulk=materialized.planned.bulk` are passed. The
`ProjectRevision` and `GeometryMaterialization` objects themselves are not an input to
this compiler. Repreparing from `planned.to_ops()` may lose
macro/default provenance, even with the same C#; this is not a substitute for the original plan.

Archive/1 binds the execution input, but not the chosen authoring revision:
two projects differing only in metadata can yield the same plan and C#.
So this raw-KIR entry point cannot yet be declared a full publication of a
specific ProjectRevision. A separate path is added below for that; appending an
arbitrary revision ID after sending is not enough.

## Publication of a chosen authoring revision

`publish_materialized_project(project, materialized, ...)` uses the same
internal send order, but saves a fresh `SubmittedProjectBinding` together
with the execution input in **one Archive/2 record before execute**. The pipeline has no
arbitrary callback that could substitute the prepared program.

```python
from kir.standalone_publish import publish_materialized_project

attempt = publish_materialized_project(
    project, materialized,
    advertisement=selected,
    client_path=installed_pipe_client,
    archive_path=new_private_archive_path,
    expected_document_key=authorized_document_key,
    operation_id=coordinator_operation_id,
    bind_view=True,
    bind_selection=True,
)
association = attempt.record.project_submission
assert association["project"]["revision_id"] == project.revision_id
```

A project/materialization mismatch fails even before the context query. Then the
original `materialized.planned` and its bulk-policy are used; the binder checks,
among other things, macro 1:N, instance/module/output digests, and the body sidecar. Even a different
archive association with **the same C# and native binding** does not pass the match before
execute. The Project's history and assets must be preserved by the caller separately:
the compact execution archive does not duplicate it and does not prove its existence.

`SavedExecutionRecord.load(path).project_submission` returns a retained dict,
not a fresh binding. A full Archive/2 match requires `fresh_prepared` and an exact
fresh `submission`: `record.require_matches(fresh_prepared, submission=submission)`.
Readonly receipt/recovery remains available after a match failure. After the
ProjectStore head changes, the old archive continues to name the originally chosen revision.

This is a caller-side association, not native attestation of project metadata or a global
CAS association between arbitrary archive paths. Stable output IDs do not make a
repeated create-program a native update. Independent readback and reconciliation
are still needed; `intent_verified` remains `False`.

`timeout_ms` limits each transport exchange, not the whole CPU time of
compilation/saving. `execution_contract_satisfied` means only the result of the
common binding/witness assessment. This function has no independent native
readback, so the `intent_verified` field never becomes true.

## Errors and the archive

- An existing archive path is not overwritten and is not a ticket for a repeat
  send. Repeating the same call with this path fails before execute.
- A COMMIT/flush error or a mismatch between the archive and the fresh preparation does not allow
  execute. The file may remain for diagnostics; its presence does not equal a successful
  confirmation of write durability.
- After saving, the transport may lose the response. The function does not catch this
  in order to retry the mutation or generate a new operation identity.
- A corrupted/unbound response is not counted as a successful publication. The common
  assessment keeps `unconfirmed` and the need for a read-only check.
- This is not a global coordinator/dispatch CAS: a manual retry with a different archive
  name does not become an authorized retry. Final execution identity/conflict
  remains in the native journal.

To continue after a failure, the archive can be opened to form only a lookup:

```python
from kir.saved_execution import SavedExecutionRecord

record = SavedExecutionRecord.load(saved_archive_path)
request = record.receipt_request(fresh_same_target_credentials,
                                 request_id=new_lookup_request_id)
# Через новую дверь B: record.recovery_request(credentials_b, request_id=...)
# recovery_target при этом остаётся исходным A.
```

The archive does not give `execute_request` or `to_prepared`. To assess an old response
with a fresh plan, `record.require_matches(fresh_prepared)` is needed first, including
plan provenance, units, and grounded evidence. A single C# match is not enough.
Without a matched artifact, the raw receipt remains material for analysis, not a
confirmed D1 result. The absence of a receipt does not authorize a repeat write.

The source content may be confidential, even without credentials fields.
The archive should be stored privately, not added to Git, and not sent to telemetry.

## Checked and unchecked

MAIN: the first 16 scenarios together with transport29 — 45 passed; after adding
query/no-document/incomplete/foreign/malformed context — the overall run
publication21/transport29/context77/result85: 212 passed / 31.06 s.
An independent reviewer checked the order and five more negative probes, including
an actual request-encoder budget before the archive. Positive pipe scenarios use
real local processes/SQLite and the production Collector/Service/JsonFraming,
but API objects/events are stubbed, and the write receipt is **explicitly seeded**.

Loss of a response is modeled after a real exchange completes; a further
lookup gets the original seeded receipt, without a second execute send.
This is a proof of order/persistence/addressing, not of a native level creation.
Installation, a Windows PID/SID, an actual switch of the Revit document, an
independent readback, and the full user interface are not yet accepted by this run.

Project-aware integration: 8 new scenarios + raw21 — MAIN 29 passed / 30,19 s.
The overall final strip Archive2(47)/Archive1(59)/binder(30)/project-publication(8)/
raw-publication(21): 165 passed / 112,26 s. The test pipe-server only gained the
ability to read an explicitly synthetic `seed-result.json`, not to interpret C#
or create Revit elements. Both first-send variants use one transport.
