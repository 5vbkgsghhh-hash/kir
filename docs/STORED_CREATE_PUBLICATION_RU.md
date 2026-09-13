# Initial publication from a saved project

Status: the local Python/CLI path has passed independent verification in the named scope.
The Store/7 addition and explicit cancel/resolve have passed a separate independent
offline verification; native Windows/Revit and hardware crash-durability have not been checked.
The transport tests use a real portable Connector service and SQLite,
but with **substituted native results**, without executing the generated C# in Revit.
This is not confirmation of element creation, Windows authentication, or BIM acceptance.

## What is saved

`ProjectStore/6-7` stores the full original `ProjectRevision`, an immutable Archive/2
for a specific attempt, the occupied scope outputs, and the obtained native receipts.
Selecting part of the project uses the existing dependency closure: the selected
outputs have both a dense source index and the original project source index.
The revision is not replaced by a trimmed project. Unselected geometry bodies
are not materialized; dependencies can widen the selected scope.

Order of the first submission: fresh context -> compile/guard -> frame/preflight ->
atomically save input and owners -> exactly one execute -> save the receipt.
Repeating the reservation does not permit another submission. An error/lost ACK after
saving the input leaves it for a separate lookup and recovery.
The receipt is saved even for a partial result; the authored revision does not change.

The scope is unique within `(journal, runtime instance, Revit version, document key)`
by the authored output ID, not only within a single revision. This is not a global ownership
guarantee across copied databases or freshly opened native namespaces.
Owners are **not released automatically**, even with a no-start receipt. Store/7
has a separate explicit resolution: a verified no-start receipt + an immutable
resolution marker + deleting only the owners of that archive, in a single transaction.
Input, the native UUID, and receipts are preserved. An old UUID does not become free;
repeating the resolution does not remove the owners of a newer publication.

## CLI

The existing database is first explicitly upgraded; publication itself does not migrate it:

```text
python -m kir project create-upgrade PROJECT.sqlite --expected REVISION
```

`connector list` and `connector context` give the explicitly selected target/session and
the observed document key. The CREATE command requires separate authorization to submit:

```text
python -m kir project create-publish PROJECT.sqlite \
  --expected REVISION --instance section \
  --directory DISCOVERY --journal-id JOURNAL --instance-id RUNTIME \
  --revit-version 2023 --session-id SESSION --client PIPECLIENT \
  --document-key DOCUMENT --operation-id OPERATION_UUID \
  --bind-view yes --bind-selection yes --confirm-create
```

`--instance` is repeated for multiple roots. `--all-instances` is a separate
explicit alternative. `--bulk` raises the internal operation budget but does not change
the transaction mode. `--isolation per_op` separately allows partial results;
`atomic` is used by default. This is only a flat CREATE,
not a general reconcile/update of an existing BIM model; unsupported groups/macros
and other operations get no silent approximation.

Keep `OPERATION_UUID` until the call is made. If the answer is lost, the archive digest
is recovered without Revit, the compiler, or a repeated execute:

```text
python -m kir project create-status PROJECT.sqlite \
  --journal-id JOURNAL --operation-id OPERATION_UUID
```

Then, a separate native lookup by the found archive digest:

```text
python -m kir project create-receipt PROJECT.sqlite --archive ARCHIVE_SHA256 \
  --directory DISCOVERY --journal-id JOURNAL --instance-id RUNTIME \
  --revit-version 2023 --session-id SESSION --client PIPECLIENT
```

To search through a different explicitly selected runtime, `create-recover` is used
with the same arguments. The response must preserve the link to the original input;
this is not moving the program to a new runtime and not permission to execute it again.
`create-status` is retained facts, not a fresh model observation. A missing
input/receipt does not mean it is safe to resubmit the publication.

### Cancellation before start and releasing the scope

These are two separate explicit actions. `create-cancel-before-start` sends a
source-free control request to the original runtime: it may prevent the start,
but it does not stop execution that has already begun and does not roll back model changes.
A plain cancel/receipt/recover never releases local owners by itself.

```text
python -m kir project create-upgrade PROJECT.sqlite --expected REVISION \
  --enable-no-start-resolution

python -m kir project create-cancel-before-start PROJECT.sqlite --archive ARCHIVE_SHA256 \
  --directory DISCOVERY --journal-id JOURNAL --instance-id RUNTIME \
  --revit-version 2023 --session-id SESSION --client PIPECLIENT

python -m kir project create-resolve-not-started PROJECT.sqlite --archive ARCHIVE_SHA256 \
  --directory DISCOVERY --journal-id JOURNAL --instance-id RUNTIME \
  --revit-version 2023 --session-id SESSION --client PIPECLIENT
```

The last command performs a fresh lookup and requires a coherent bound no-start.
Timeout, not_found, running_unknown, committed, or rollback do not grant a release.
For lookup through a different runtime, resolve has an explicit `--via-recovery`;
cancel through a recovery-runtime is forbidden. Release requires an explicit Store/7 upgrade;
Store/6 remains supported for the earlier reservation/receipt paths.

`released_not_started` describes the old publication, not whether the namespace is free
now: another controller may already have saved a new reservation. Any subsequent
publication requires a new decision, a new UUID, a fresh context/compile, and a reservation.
After a lost local COMMIT ACK, `create-status` is read first; that is not a reason
to send CREATE again.

The CLI output contains no credentials, generated source, raw responses, or native
exception text. `execution_contract_satisfied` differs from `intent_verified`:
the latter is always false here. A nonzero exit code is not a retry ticket.

## Identity and corruption

Birth assessment re-verifies the shared native D1 contract and the original outer
response. Substituting the public derived outcome does not turn an incomplete receipt
into proof of creation. A result row with `internal`/an error does not grant birth.
The real ID/UniqueId capture must match the full added/deleted manifest;
a reuse type remains a reference to an existing type, with no ownership/update right.
Historical receipts are not turned into fresh observation evidence by loading them.

The store checks the index links of receipts, including a transfer to a different
existing input, and the full payload during an explicit history audit. For a single input,
the progress count/bytes and the terminal-receipt reserve are separately bounded. The terminal
is immutable; a later progress does not replace it. The receipt catalog scan is currently
linear and bounded to a single payload; scalability on large histories
has not yet been proven, and O(selected) is not claimed.

## Checked and remaining

- Independent identity/storage controls: 27 passed, including confirmed
  RED->GREEN across three outcome axes, an internal row, and two kinds of index substitution.
- Shared native-content refactor: 326 passed with the earlier fresh/query/saved/Level
  checks; the strips overlap and the numbers do not add up.
- Stored publisher: 7 passed, real portable IPC/SQLite, including a lost
  response and writing the receipt before/after COMMIT with a lost local ACK.
- CLI + store + the earlier connector CLI: 102 passed; a separate independent review:
  21 passed. A confirmed documentation mismatch for `--bulk` was fixed:
  the budget and the transaction mode are now chosen independently; all four
  combinations were checked against saved C#, not against mock parameters.
- After adding explicit isolation: preparation/archive/publish/CLI regression,
  143 passed. The earlier authoring/task CLI and CREATE result/store controls: 105 passed.
  A separate CLI strip of 13 passed covers publication, status, and receipt in three
  fresh Python processes. Read-only status does not replan the project.
- Extended identity capture: 168 positive actual-reference compilations for
  2021-2026, 12 negative compiler/policy controls, 2 expected opening refusals
  on 2021. Runtime checks use a fake API; Revit was not launched.
- The capture hash migration was accepted separately: 642 changed/1719 unchanged,
  all 21 refusals preserved; 22 physical goldens updated after an exact comparison.
  MAIN 62 passed/78 subtests: re-deleting strictly new capture fragments
  restores the historical 2361 hashes. Two annotation goldens separately
  contain the fixed old type-stage delta. This is not new floor-type
  hash coverage and not proof of Revit's behavior.
- Native fallback: a linked regression confirms an empty healthy journal ->
  unpersisted failure -> durable cancel -> two correctly saved receipts.
  Full headless Connector: 124 passed. The old 2023 package became stale after the fix;
  it was not installed. The new portable IPC controls use a fresh helper.
- Store/7: 33 new checks, the extended Store/task strip: 150 passed;
  an independent strip of 28 passed includes 27 new controls and a linked native regression.
  MAIN 89 passed separately checks native/no-start/Store7/CLI-diagnostics.
  MAIN 32 passed on a fresh IPC
  helper: cancel/resolve/new publication/old ACK, not_found/committed/foreign
  target, and an explicit schema gate, plus the earlier CLI/stored-publication tests.
- The general fresh no-start qualifier and the earlier identity/CLI controls: 130 passed.
  Safe compiler diagnostics give out only registered codes and a permitted
  compiled-op index, at most 20 entries; native/free-form texts are not emitted.

Still open: integration with the user viewer,
fresh native consumer/type readback and acceptance, reconciliation after a partial
CREATE, general update, a live cycle in Revit 2023/2026, scaling of history.
Before a convenient user cycle, we also still need a preview of the selected publication
scope before confirmation, obtaining real type-seed IDs, and a clear output of
qualified identity/fresh discrepancies. Demonstration type IDs are not
a catalog of a user's actual Revit document.
The accepted parts do not mean the whole regression suite or the live pipeline are green.
