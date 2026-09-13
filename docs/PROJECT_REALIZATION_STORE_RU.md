# Store/3–4: saved streams of Level changes

This is one local SQLite `ProjectStore` owner, not a second BIM graph and
not proof that the whole building has been realized. The
`kir-project-store/3` schema keeps all the /2 tables, including the
geometry assets. Creating /3 or transitioning through
`upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=...)` is
explicit. Old ProjectRevision payloads, their hashes, and the authoring
head are not rewritten. Downgrading the schema is forbidden; a migration
failure does not leave a partial set of tables.

## Two independent sequences

The authoring history remains one chain of ProjectRevision. It can already
contain further drafts while the native change has not yet been accepted.
A separate scoped stream is addressed by `original_binding_digest` and
stores:

- the immutable source publication claims;
- an accepted checkpoint, initially `None`;
- one pending archive, until its result is qualified;
- the exact canonical archive bytes and the immutable settlement evidence.

Settlement does not move the authoring head. Acceptance relates only to the
selected Level fields and the checked protection area. Geometry and
engineering properties are not declared established.

## Reservation ahead of the single send

```python
from kir.project_store import REALIZATION_STORE_SCHEMA

store.upgrade_schema(REALIZATION_STORE_SCHEMA,
                     expected_revision=store.head().revision_id)
reserved = store.reserve_level_update(record, expected_checkpoint=None)
# This is a storage operation, NOT a send, and NOT a standalone grant to execute.
```

`record` is an exact checked `SavedExecutionRecord` with an Archive/3
update association. The Store checks its bytes again, then, in a single
`BEGIN IMMEDIATE` transaction, checks the checkpoint/pending, writes the
stream/scope/archive, and the pending pointer. The base/proposed must
already be in this database, be a direct child, and describe exactly the
declared elevation replacement of one explicit Level. The source
publication addresses and hashes are checked against the source saved
ProjectRevision.

The initial nested `kir-submitted-level-update/1` requires
`expected_checkpoint=None` and the base of the source publication. The
iterative nested `/2` requires an exact `baseline_ref`: `store_id`,
`stream_id`, `checkpoint_digest`, `base_revision`. The base must be
accepted.proposed. The before-observation is compared against **the actual
SQL checkpoint**: runtime/document, a native revision no lower than
accepted after, the exact UID scope, and the observed fields. A
substituted public baseline DTO does not replace this check.

A different pending item blocks a new update. An exact repeat of the same
reservation returns `inserted=False` and the current checkpoint/pending,
without changing them. This is not permission to repeat the send. An
unknown result, a timeout, or a failed qualification do not clear the
pending item automatically.

Within one database, the native UID of the selected runtime/document is
locked to one stream. You cannot bypass a pending item with a different
original binding digest that has an overlapping source UID scope.
Repeating the native `(journal_id, operation_id)` with a different archive
is also forbidden. There is no such guarantee between different databases.

## Accepting evidence

```python
settled = store.commit_level_settlement(
    qualified,
    expected_checkpoint=previous_checkpoint,
    expected_pending_archive=record.digest,
)
```

Only a factory-created `QualifiedLevelSettlement` is accepted, not a dict
and not a previously read settlement. The qualifier separately checks the
bound execution, a fresh parsed after-read, and field/manifest acceptance.
The Store checks the retained relations and the exact match of
`qualified.record` against the pending bytes. In one SQL transaction the
settlement is recorded, the scoped checkpoint is advanced, and exactly its
own pending item is cleared.

An exact redelivery returns `inserted=False` and the current state. An old
settlement does not roll back a newer checkpoint and does not clear a
different current reservation. On a lost COMMIT confirmation,
`StoreCommitUnknown` is raised: you must read the state, or repeat **the
save operation with the same identities**, not a native mutation. All
receipt carriers have `may_retry=False`.

## Read-only recovery

`level_baseline(stream_id)` returns `RecordedLevelBaseline`: the
store/project ID, the source claims, the accepted settlement, the
checkpoint/pending digests, and `baseline_revision`. This is not an
`ElementObservation`, not a fresh plan, and not an execute API. The getters
return detached data. `get_level_update_archive(digest)` reads the checked
source archive for an explicit read-only receipt lookup;
`get_level_settlement(digest)` returns only historical claims.

Missing files are not created; a read-only open does not update the schema
and does not run recovery. Hot Level reads check the selected checkpoint,
pending item, scope, and unsettled archive identities. A lost pending
pointer does not authorize a new send. `history()` additionally checks all
settlement/archive chains, the absence of orphan reservations, SQLite
integrity, and foreign keys. No forged fresh objects are built from
persisted payloads.
The full ledger TEXT rows are additionally bounded through SQLite's
`SQLITE_LIMIT_LENGTH` before being passed to Python; the limit applies only
to the corresponding SELECT and is then restored, with no change to the
allowed sizes of authored snapshots/geometry assets.

## Boundaries of the evidence

The tests use actual local SQLite files, separate Python processes,
competing writers, and process exit before/after COMMIT. Revit receipts and
observations in these tests are synthetic; native BIM execution is not
confirmed. The existing SQLite DELETE journal / synchronous=EXTRA
guarantees of the ProjectStore and the filesystem/VFS limits apply. This is
not a physical power-loss proof, not a distributed lock, and not
protection against a malicious rewrite of the database and hashes.

Store/3 cannot resolve `not_started`; the explicit transition to /4 is
described below. For started/unknown/failed-after-start there is still no
abort/reject settlement. Such a pending item remains unresolved: this is a
limitation, not a finished runtime recovery workflow. There is no
cleanup/pruning, cross-store ownership, automatic sending, restarting
Revit, reopening a document by name, or geometry acceptance.

Scoped tests are run only with a new directory under `.work/runs`, passed
simultaneously as `TMPDIR`, `TMP`, `TEMP`, and a separate pytest
`--basetemp`; cache and bytecode are disabled. No .NET builds or global
`/tmp` fixtures are needed.

## Store/4: proven not_started, with no automatic retry

`RESOLUTION_STORE_SCHEMA = "kir-project-store/4"` adds an immutable
`level_resolutions` table. `commit_level_not_started(qualified, expected_checkpoint=...,
expected_pending_archive=...)` accepts only a factory-created
`QualifiedLevelNotStarted`: an exact bound native before-start receipt, not
a timeout, not the absence of a receipt, and not an arbitrary dict. In one
transaction the source evidence is saved and only the matching pending item
is cleared. The accepted checkpoint, the authoring head, the native
operation ID, and the source archive are not changed.

An exact repeat of the resolution returns `inserted=False` and the current
state, without clearing a different reservation.
`get_level_resolution(digest)` reads inert claims;
`get_level_resolution_for_archive(archive_digest)` allows recovery after a
lost acknowledgement with no missing response: `None` for a registered
archive with no resolution, `StoreNotFound` for an unknown archive. No read
reconstructs a fresh qualification or grants execute/retry.

After the first not_started, a stream can exist with no accepted item and
no pending item — only when a consistent resolution is present. A new
attempt needs an explicitly prepared update with a new operation ID. The
initial nested `/1` remains bound to the source publication; the iterative
nested `/2` to the same accepted checkpoint and a fresh observation.
Repeating an old archive still returns reservation.inserted=False. The send
workflow must refuse in this case, rather than treating the resolution as
permission to re-execute the old operation ID.

Hot reads distinguish settled/resolved/pending and reject a double terminal
outcome, a lost pending item, or a resolution attributed to a different
stream/checkpoint. The evidence of unsuccessful attempts at the current
checkpoint is checked in full: the cost is proportional to the number of
these attempts, not to the whole history of the building. Old resolution
payloads are additionally checked by `history()`. This is not an infinitely
cheap refusal log; there is no pruning.

### Explicit migration /1–3 → /4

The /3 schema and its ordinary reader are preserved unchanged. In /3, the
`UNIQUE(stream_id, expected_checkpoint)` constraint does not allow
re-reserving a new operation on C1 after not_started. That is why /4 has a
separate canonical DDL: an ordinary lookup index instead of this
constraint, while preserving the uniqueness of `(journal_id,
operation_id)`. A separate index was added for the resolution lookup.

Only an explicit migration transaction temporarily disables foreign keys
**before BEGIN**. The /3 transition creates a new table, performs a SQL
`INSERT SELECT`, compares the counts and the exact rows in both directions
through `EXCEPT`, then deletes the old table and renames the new one.
Python does not deserialize the whole database in order to copy it. Before
COMMIT, `foreign_key_check` is run; after COMMIT/rollback, foreign keys are
turned back on. Ordinary transactions always run with FK ON. There is no
first-rename-old, no writable_schema, no deleting journals, and no
rewriting the source ProjectRevision/asset payloads. If the rollback itself
is not confirmed and the transaction is still active,
`StoreCommitUnknown` is preserved and the connection is closed: a failed
attempt to turn FK on inside an active transaction must not hide the
original uncertainty.

A failure after DROP/RENAME is rolled back by the regular SQLite
transaction; the loss of confirmation of an already-performed COMMIT is
named `StoreCommitUnknown`. The migration requires free space for the new
table and the rollback journal. It does not prove physical power-loss
resilience, the Windows loader/native execution, or the completeness of
recovery for every possible started outcome.
