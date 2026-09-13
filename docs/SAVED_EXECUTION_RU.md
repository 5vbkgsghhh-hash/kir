# Archive of the source execution before the first send

`kir.saved_execution` saves exactly one execution input into a separate NEW
SQLite file. It exists so that after a Python crash you do not lose the
source address of the operation and the full C# source. This is not a
ProjectStore migration, not a task queue, not a dispatch CAS, and not an
execution-phase journal. The native journal remains the owner of
idempotent execution; the absence of a receipt does not authorize a retry.

## API

```python
from kir.saved_execution import SavedExecutionRecord

# prepared is a fresh result of prepare_execution, not loaded JSON.
saved = SavedExecutionRecord.create_new("NEW-execution.sqlite", prepared)
saved.require_matches(prepared)
# Only the coordinator separately decides whether execute can be sent for the first time.

reopened = SavedExecutionRecord.load("NEW-execution.sqlite")
request = reopened.receipt_request(fresh_credentials_A, request_id=new_request_id)
# Or explicitly request the old operation A through a new serving session B:
recovery = reopened.recovery_request(fresh_credentials_B, request_id=another_request_id)
```

A loaded record has no `execute_request`, `to_prepared`, `planned`, or any
other path to recover fresh compiler authority. The loader does not call
recompile, registry replay, OCP, or source execution. Both read-only
request builders receive fresh credentials as an argument; they are not
written into the archive.

`receipt_request` requires the same original runtime target.
`recovery_request` explicitly keeps `recovery_target=A`, even when the
route target and the session belong to B. A new transport request ID does
not change the original operation ID. The builders only return requests;
they do not call the network themselves.

## What is saved and what is compared

The canonical JSON has `schema=kir-saved-execution/1`, its own digest, and
includes:

- Original target: journal/instance UUID, Revit version, operation UUID.
- The full precondition: opaque document key, revision, view/selection with
  an exact distinction between `null`, `0`, and an empty string.
- The full wrapped C# source, the SHA-256 of exactly the UTF-8 bytes, the
  byte length, and the UTF-16 code-unit length matching the Connector's
  limit.
- The exact `plan.to_evidence_dict()` and separately `planned.units`, which
  is not part of the compiler plan digest.
- `grounded.to_evidence_dict()` or an explicit `null`.
- Explicit weak claims: retained evidence, native execution is not
  established, dispatch state is not recorded, retry permission is absent.

No project binding is added on top of the previous Archive/1; a separate,
explicit [Archive/2](SAVED_PROJECT_EXECUTION_RU.md) can hold a caller
association. The session ID/token, credentials, grants, and the execution
phase are not added in either version. `to_dict` and `binding_dict` return
detached values. `repr` does not reveal the source. But the C# can contain
sensitive user strings: the absence of credential fields **does not make
the archive public data**.

`require_matches(fresh)` compares the whole source/binding, the plan
evidence, the units, and the grounded evidence, not just the code's SHA. An
actual control with `stack` shows: repreparing from `first.planned.to_ops()`
produces the same C# but a different plan digest, due to lost macro/default
provenance. Such a recompile is not counted as the source plan. Lookup
remains available after a match refusal; you cannot D1-evaluate an old
result with a new, non-matching plan.

The nested plan/ground evidence is stored as assertions with checked
envelope/digests, rather than being executed or re-qualified by the current
registry. A foreign archive that has been consistently recomputed does not
become authentic compiler evidence: this is caught by comparison against a
separate fresh artifact, where one is available. A hash is not the
author's signature or proof of execution.

## The portable saving boundary

Storage is one `saved_execution` table and one canonical TEXT record, with
a separate SQLite application ID `KIRS` and user_version 1. No
project-specific identity/schema helpers are used, and no legacy
`DocumentFingerprint` is invented.

Creation order:

1. Check/fix the payload in memory, including the byte budgets.
2. Check that no recovery sidecars exist and exclusively create the NEW
   path through `O_CREAT|O_EXCL`; an existing file/directory/symlink is
   not adopted.
3. SQLite `BEGIN IMMEDIATE`, `journal_mode=DELETE`, `synchronous=EXTRA`,
   create the schema and write the record, check the written bytes, then
   `COMMIT`.
4. A file flush and, on POSIX, a directory fsync; a read-only check of the
   saved record. Only after this does `create_new` return a successful
   result.

On an initialization failure, the file and sidecars remain for inspection.
Nothing is deleted, overwritten, or repaired. An error after COMMIT, or an
undetermined write confirmation, produces
`archive_durability_unconfirmed`; the accepting caller **must not send
execute** after any exception from `create_new`. The file being readable
after an error does not restore the previous flush acknowledgement and
does not grant permission to repeat the execution.

Load uses a URI-escaped filesystem path, SQLite `mode=ro`, `query_only=ON`,
`trusted_schema=OFF`, and checks the header/schema/single record and
hashes. A symlink, a foreign schema, an extra table/row, a torn payload,
and any `-journal/-wal/-shm` get a refusal with no recovery. A trusted,
caller-controlled directory is required; protection against a hostile
substitution of ancestor directories/file in a race is not claimed.

Budgets: 64 MiB canonical record, 80 MiB SQLite file, depth 64, and 2
million JSON items; the record size is checked before it is extracted into
Python. The source also obeys the existing Connector UTF-16 limit. These
are limits of this archive, not an extension of the native transport frame
budget and not a limit on KIR's expressiveness.

On POSIX, the new file is created with mode 0600. On Windows we keep the
SQLite/VFS protocol, but ACL privacy and the behavior of the actual
Windows filesystem have not been checked yet: the caller chooses a private
directory. A successful SQLite/OS flush is not a physical power-loss test.
Network filesystems are not qualified.

## Checked boundaries

The tests run actual separate Python processes: two exclusive writers;
stopping before INSERT, after INSERT, and after COMMIT; a fresh read-only
lookup with no OCP/compilation. Checked: the unchanged state of
existing/corrupt/sidecar files, every axis of the original binding, strict
JSON/scalar traps, a source+SHA mismatch, plan provenance and units, a
refusal after a flush failure.

This is not live Revit and not U02 dispatch acceptance. The archive stores
the source input, not proof that it was ever sent, that the native commit
happened, or that the engineering intent was fulfilled.
