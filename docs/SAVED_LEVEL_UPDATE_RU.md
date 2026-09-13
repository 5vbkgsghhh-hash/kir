# Archive/3: preserved single-Level update binding

Status: fresh binder, codec, and archive-before-send dispatcher implemented.
File save and read by a new Python process are verified on the local
Linux filesystem; Windows, power loss, and live Revit are not verified. Independent
source-review of the file path is complete; no independent rerun has happened.
Assessment of a saved update after a Python restart is implemented. No Revit update
was sent.

`bind_level_update_submission(update, prepared)` checks the fresh plan, guards,
precondition, and preparation. It saves a compact binding:

- the original publication binding and references to its archive/receipt;
- the before-observation with the original runtime/revision/UID/type/level fields;
- R0/R1 and the target value, protected/affected scope;
- the exact new execution binding and explicit identity guards.

Full Project snapshots and BRep are not copied: their history stays with ProjectStore.
Hashes and saved claims are not native attestation.

`SavedExecutionRecord.create_update_new(path, prepared, submission)` adds
an explicit schema `kir-saved-execution/3`, reusing the previous immutable SQLite
writer and its NEW path/flush/readback rules. There is no new store or table.
Old Archive/1–2 do not migrate and get no new null fields.

`record.update_submission` returns detached claims. `require_matches` for /3
requires a fresh `level_update=...`; loading does not create a `LevelElevationUpdatePlan`,
`ElementObservation`, or `PreparedExecution`, and does not add an execute API.
Receipt/recovery requests continue to address the original operation/runtime.

The codec checks internal references, the exact guard set, matching before-rows,
target/value/parameter/revision, and the invariance of the declared boundaries. Loss of a guard,
substitution of UID/revision/scope/value, or an upgrade of claims is not accepted even after
recomputing nested hashes. This is consistency validation of saved claims,
not new proof of executing a compiler/kernel/native operation.

The initial 16 in-memory controls and the full ЖК2023/26 authoring run passed with
Python file writes/subprocess forbidden. Control Archive/1 bytes before/after
matched. These runs did not test the file writer; a separate subsequent
file-based check is described below.

The `publish_level_update` dispatcher is wired: prepare + fresh binder, request
serialization, NEW Archive/3, and an exact match precede the single execute. Context
is not refreshed, a lost reply does not trigger a retry. The returned attempt holds exactly
the sent PreparedExecution for a separate later acceptance.
Six in-memory ordering/failure controls passed with stand-in storage/transport
seams. In the subsequent file-based check the storage is already real; the transport remains
a stand-in: calling exchange does not mean delivery to a real Connector.

Additionally checked with real SQLite `:memory:`: INSERT/COMMIT and the production
`_read_record` preserve the exact Archive/3 bytes, ROLLBACK leaves no accessible
record, query_only forbids modification, and wrong DB identity/version/schema and
BLOB instead of TEXT are rejected. Six controls passed with disk SQLite and
Python filesystem writes forbidden. This is SQL/codec compatibility, not an fsync/journal/header
or restart/power-loss test of the file writer.

## File-based check, September 5, 2026

`kir/tests/test_saved_level_update.py`: 10 cases use the real NEW SQLite
writer and `load`, not a stand-in for the archive API. The original authoring fixture and native
observations are still synthetic.

- Create/commit/flush/readback → a different Python process → the same bytes, binding,
  guards, and association. In the child process, calls to compile/plan/prepare
  and Python filesystem writes are forbidden; file contents and mtime are unchanged.
- An existing archive is not overwritten; two parallel creators of the same path
  yield a single winner. Existing journal/WAL/SHM files are preserved with a failure.
- An incompatible fresh preparation is rejected before the file is created.
- A stand-in `_flush_created` failure after a real SQLite COMMIT leaves
  a readable archive, but `publish_level_update` does not call exchange. Retrying with the same
  path does not become permission to send.
- Before the single stand-in exchange, the archive is already opened through a real
  `load`. A lost response leaves this file available for receipt lookup with no retry.

10 file-based + 38 related memory/codec/SQL/ordering tests: **48 passed, 5.23 s**.
All new fixtures: `.work/runs/archive3-files-Wp4UidP3`, total size after
the run **464 KiB**. Old `/tmp` artifacts were not deleted.

This is not a check of sudden power loss, Windows VFS, a real native
receipt, or recovery of an accepted BIM revision. After restart, the saved
association gives lookup identity and, with the new check below, a field assessment,
but not a fresh plan. This initial strip did not check the R1→R2 repeat cycle itself;
its later implementation is described below.

Previously, the advertisement-deadline and PipeClient-presence check ran only
inside `exchange`, after the update archive was created. This limitation is removed:
the publisher now checks the real request bytes and local inputs, then performs a
bound ping **before the archive and reservation**. No ready response — no new pending.
A ping does not update the saved observation/context and does not authorize execution:
the transport repeats its input checks, the native runtime keeps its pre-effect guard.
Failure/expiry after the probe is still possible; such a race gives no automatic retry
or deletion of an already-created pending. A retention policy is not yet implemented.

Preflight/readiness strip: **231 passed /77.86s** (real portable pipes,
an existing helper without a rebuild), separately **18 passed /15.54s**, including
an actual failed attempt to connect to a missing pipe. In the latter
case, no archive/pending is created. Runs overlap; this is not Windows/Revit
authentication or a successful model mutation. The native guard after the ping is mandatory.

## Assessment after a Python restart

`assess_connector_saved_level_update_response(record, response, credentials=...,
request_id=..., recovery=False)` uses the common native → D1 → rollback-scope
path. It differs from `assess_connector_saved_write_response` deliberately:
the generic saved API only gives payload availability, the new one interprets
a strictly qualified single-Level setter. `archive_digest` on the result
marks the saved provenance of the evidence.

Before D1, a current IR version, matching registry contract digest,
result metadata, family/effect, the original one-op/non-macro profile, absence of a
reserved result ID, and current baseline/setter tolerances are required. A mismatch returns
`unsupported_saved_update_profile`, but does not prevent reading the old archive through the
generic saved API. Neither `PlannedProgram` nor `PreparedExecution` is
restored from the archive. Registry compatibility does not prove the authenticity of the historical
compilation; the caller must obtain the response over a chosen trusted transport.

`assess_saved_level_update(record, response, credentials=..., request_id=...,
after=..., recovery=False)` использует ту же проверку target/height/protected
fields/change manifest, что и fresh `assess_level_update`. Отчёт имеет отдельную
schema `kir-saved-level-update-acceptance/1`, `baseline_evidence=retained_archive_claims`,
archive digest, `project_revision_promoted=false`, `may_retry=false`.

Working sequence for the caller:

1. `SavedExecutionRecord.load` and a read-only receipt/recovery lookup.
2. A new `observe_elements` for the UID scope from the before-observation, with an explicitly chosen
   original runtime/document and UI binding policy. A new query can be compiled;
   the old write program does not need to be recompiled/resent.
3. `assess_saved_level_update` separately shows execution and field acceptance.
   Unknown/error does not trigger a retry, and a successful report does not itself change ProjectStore.

Restarting Revit is a different situation: server B can supply a historical
receipt A, but its observation B does not become a continuation of revision A.
A historical commit can be installed while after-checks remain
`not_evaluated`. Rebinding the document is not implemented.

An adversarial source review found two false-positive paths in the shared
consumer. MAIN reproduced the RED and fixed both:

- an after with the previous UID but a numeric ID8001 confirmed the receipt setter ID901;
  now `target_identity_address_changed`, without requiring an unchanged VersionGuid;
- extra `error`, `commit_status`, `ok`, or `state` inside the setter row were hidden
  behind the correct id/param. Now only id/param and an optional
  string/null value of the actual emitter are allowed. A D1 commit does not turn into a rollback.

Final strip of 12 files: **293 passed, 2 skipped, 27 subtests, 14.17 s**,
including 42 new recovery/acceptance cases, a real file-based Python restart, and
a composite residential memory case. Two host-mode tests are skipped due to the absence of
the `llm.turn_context` port; these are not Revit checks. An independent reviewer confirmed
the source fix but did not run the tests themselves. Native receipts/after responses are synthetic.
New run root `.work/runs/saved-update-recovery-0jr8SazS` takes up **7.3 MiB**,
including saved RED/rerun fixtures; there were no deletions and no .NET builds.

## Iterations through a scoped ProjectStore/3

The outer Archive/3 stays the same. Inside it, the first update saves
`kir-submitted-level-update/1`; the next one has an explicit nested `/2` and
`baseline_ref={store_id, stream_id, checkpoint_digest, base_revision}`.
The original binding R0 is unchanged. Old `/1` submissions are not rewritten.

`qualify_level_settlement` accepts a checked archive, a bound response, and a fresh
after-observation, not an imported green report. The result contains
full after-rows and a receipt with an explicit scope `observed_level_fields_only`.
Saved data is checked by `validate_level_settlement_claims`, but is not
restored into a `QualifiedLevelSettlement` or a new observation.

ProjectStore/3 saves the exact archive bytes and pending until send. Settlement
advances only the scoped checkpoint and clears only the matching pending
in a single SQL transaction. The authoring head is independent and may already contain an R2 draft.
Exact redelivery does not rewind the checkpoint and does not authorize resending.
A new arbitrary original-binding cannot bypass UID ownership within this DB;
there is no global lock between different ProjectStores.

Correct checkpoint/store IDs are not enough for an iteration: the SQL owner compares
the submitted before-observation against the real stored checkpoint.after. This matters,
because the public `RecordedLevelBaseline` is only an inert carrier. History
does not lose an unresolved archive when the pending pointer is lost: a hot read checks
correspondence of pending and unfinished records, not just one pointer's metadata.

API details and the remaining terminal-resolution gate —
[LEVEL_UPDATE_PLAN_RU.md](LEVEL_UPDATE_PLAN_RU.md) and
[PROJECT_REALIZATION_STORE_RU.md](PROJECT_REALIZATION_STORE_RU.md).
Full R03, native geometry preservation, and live Revit are not closed by this.

Final iteration acceptance: MAIN reran **337 tests /67.63s** across 12 related
files, including new Store37, qualifier25, iteration6, and a real OCCT residential
case. The child Python continues R1→R2 without the original publication object; storage
history, reservations, and both checkpoints are real. All native evidence remains
synthetic. A source review separately confirmed the owner-side recheck baseline and
protection against a lost pending pointer. This is not new readiness for the whole product.

## Confirmed absence of a start: Store/4

`qualify_level_not_started(record, response, credentials=..., request_id=...,
recovery=False)` requires an existing bound native `NOT_STARTED`, not a timeout,
not the absence of a receipt, and not a helper flag about delivery. The common native validator
checks state/started/may_retry/changes/result; the qualification does not compile
the program and does not assert that the surrounding model has not changed.

After an explicit `upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=...)`:

```python
resolved = store.commit_level_not_started(
    qualified,
    expected_checkpoint=previous_checkpoint,
    expected_pending_archive=record.digest,
)
```

In a single transaction, the resolution is saved and only the matching
pending is cleared. The accepted checkpoint and the authoring head are unchanged. An old
resolution is reconfirmed without clearing a new pending operation. Through
`get_level_resolution_for_archive(archive_digest)` the saved result can be recovered
after losing the acknowledgement, without knowing the lost resolution digest.

The next attempt is a new explicit operation with a new ID and fresh inputs, not a replay
of the old archive. From C1 the previous accepted checkpoint is used. Before the first
settlement, C0 remains the original R0: the caller re-qualifies the original publication
and observes the model, rather than inventing an accepted R1.

Store/4 preserves existing rows and lifts the UNIQUE on stream/checkpoint that blocks new
attempts, while preserving native operation identity uniqueness. The migration
follows the create/copy/check/drop/rename procedure with an FK check before commit, from
[the official SQLite documentation](https://www.sqlite.org/lang_altertable.html).
There is no automatic migration on read-only open; the old Store/3 DDL is unchanged.

MAIN independently reran **412 tests /63.25s** across 12 files, with no skips: new
qualifier39, Store4 30, integration3, and the previous store/geometry/assessors.
Real SQL migration/faults, processes, and Python restart; native receipts
remain synthetic. Reproduced and fixed a misattributed terminal join
and masking of `StoreCommitUnknown` after a failed rollback. A separate source review
confirmed these boundaries. Physical power loss and live Revit are not checked.

## Explicit cancellation before start

`record.cancel_before_start_request(credentials, request_id=..., timeout_ms=...)`
prepares a journal-control request for the **original runtime**: CORE and the exact
operation ID, source SHA, precondition. The original C# is not transmitted, no execute API
appears on the loaded archive. This is a journal write request, not a read-only
lookup; recovery B does not get the right to cancel journal operation A.

`request_cancel_pending_level_update(store, stream_id=..., expected_pending_archive=...,
advertisement=..., client_path=..., request_id=...)` performs one such exchange.
The mandatory expected archive protects against a stale UI retry: it cannot
cancel the next operation of the same stream. The context is not reread and the old
write plan is not compiled. Only a bound NOT_STARTED allows a Store/4 resolution.
An existing committed/started/unknown result is returned without clearing the pending.

If another controller has already recorded **the same native receipt** through a different response
ID, or the COMMIT acknowledgement is lost, a read-only lookup by archive
digest is performed and the receipt digest is compared. `resolution_recorded` means the
historical resolution exists, not that "the current pending is empty"; the new
reservation is not cleared. A different receipt or a missing resolution leave a conflict/
uncertainty, with no automatic command retry.

MAIN reran **174 Python tests /65.04s** through a new isolated PipeClient,
including a real Service/journal cancel→late execute and an unchanged committed
receipt. Separately, **16 C# cases /0 failed**: an actual Engine/Queue with Revit stubs,
TryStart/cancel races, session/owner shutdown, partial append, and lost ACK.
The same generated fixture, without cancellation, does change the stub counter once;
with cancellation before queue/drain — zero. This is not live Revit and not physical power loss.

The native Protocol/Service/PipeClient source has changed. Previously saved final
packets do not yet contain this command: they remain historical artifacts,
not a current deployment of the new feature. The old server/helper must reject an
unknown kind; such a rejection does not authorize clearing pending.

Final DTO correction accepted: native 124/0, new Python/helper 174/83.22s,
compile-only matrix 2021–2026 with no warnings/errors, checking assembly metadata.
`JsonFraming.Write/WriteAsync` now produce the exact cancel DTO without changing the old
kinds. Details and limitations — [CONNECTOR_CANCELLATION_RU.md](CONNECTOR_CANCELLATION_RU.md).
