# Connector execution protocol v4 (offline integration)

This is a local Connector contract, not a BIM acceptance or arbitrary-code
security guarantee. Native execution and Windows transport still need separate
acceptance. App bootstrap, journal ownership, target-bound service, per-session
discovery and execution admission are integrated. Portable linked tests exercise
their actual lifecycle with narrow Revit/Windows-permission seams. No live result,
Windows transport/ACL acceptance or deployed add-in release is claimed.

All requests use `protocol: "kir-revit-connector/4"`, session `token`, a
`request_id`, `kind`, `session_id` and `target`. Missing/older protocol versions
are rejected. Context collection
and execution run through their existing Revit ExternalEvent schedulers.
The request ID must be nonblank. Wire JSON is strict UTF-8 without a BOM and
duplicate-free at every depth, including escape-equivalent property names;
ambiguous conditions are refused before deserialization can choose a last value.

The pipe is one-shot: connect, write one request frame, read exactly one framed
response, then **close the connection**. Do not wait for server EOF/ReadToEnd
before closing your end. The server waits for client EOF after the response so
it does not disconnect a Windows pipe with unread response bytes. Pipelining
multiple requests on one connection is unsupported. Read/write/EOF operations
use cancellation and a separate 30-second connection-I/O deadline; a stalled
frame read can return `transport_io_timeout` when an error frame is deliverable.
Timeout after a response starts closes the connection, not a second response
frame. A failed/partial response always needs original-journal reconciliation.
The I/O timer is not running while the service awaits compilation/execution.
Neither a connection-I/O timeout nor closing the pipe cancels an already admitted
invocation or proves rollback. Session admission remains the write boundary.

The persistent `target` is `{journal_id, instance_id, revit_version}`: canonical
nonempty UUIDs for the original journal and process instance, plus a shipped
Revit year (2021–2026). A document token is a separate identity. Every request
must match the service's actual target and current session before compilation
or context capture. Native context/invocation additionally check the actual
document's Revit version. Responses carry the actual route `target` and
`session_id`; receipts carry their original execution `target`.

`session_id`, token, pipe name and expiry are transient routing fields, not
members of the persistent operation binding. Renewing a transport session must
not invent another operation identity. The durable operation address is the
pair `(journal_id, operation_id)`, never a UUID searched in whichever Revit
process happens to be reachable.

1. `kind: "context"` obtains a complete document snapshot. Its document key is
   an opaque open-document token, not a path or persistent BIM identity. Revision
   counts observed DocumentChanged events, including commit/undo/redo.
2. `kind: "execute"` supplies `operation_id` (UUID), `source`, exact UTF-8
   `source_sha256`, and `precondition` with `document_key`, mandatory integer
   `revision >= 0`, optional `active_view_id` and `selection_digest`.
3. `kind: "receipt"` supplies the same operation ID to look up durable evidence.
   A lost response does not authorize repeating a mutation with a new ID.
4. `kind: "recover_receipt"` targets the current service B but additionally
   supplies the full original `recovery_target` A and operation ID. It acquires
   A's exclusive journal lease and performs read-only recovery. The response
   route remains B, while a recovered receipt retains A. No writable adoption
   or rebinding to B occurs. If A is the current owner, its own index is used.

The immutable execution binding consists of the original target, operation ID, normalized lowercase
source SHA, document key, revision, view condition and selection condition.
UUID spelling is canonicalized. Source text is hashed without whitespace or
newline normalization. View/selection null means no UI constraint; a changed
supplied value or nullness changes the binding. A precondition is copied before
compilation/enqueue; later DTO/byte-array mutation cannot change queued input.
Unknown request/precondition JSON fields are rejected, not silently interpreted
as supported conditions. These hashes are integrity identifiers, not signatures.

Before a fresh invocation the complete current context must match the captured
precondition. Before that context check, an existing operation is handled as
follows:

| Durable record | Exact execute retry / lookup |
|---|---|
| Matching v4 terminal | Original detached receipt, without recompiling, invoking or requiring that document to remain active. |
| Matching v4 start only | `running_unknown`, no permission to replay. This also applies after recovery. |
| Different bound input on execute | `operation_conflict`, original journal bytes and receipt unchanged. |
| Legacy schema 0/3 archive | `legacy_unbound`; no v4 target is inferred and owned-runtime use refuses it. |
| No durable record | Lookup returns `not_found`, explicitly **not** proof of absence from the queue. |
| Unhealthy journal | `journal_unavailable` at service admission/lookup; writes disabled. |

Receipt lookup is by operation ID and therefore returns the original binding;
it does not validate a different proposed source. Consumers must inspect the
receipt's original `target`, `precondition` and `source_sha256`. Transport `ok: true` with
`status: "receipt"` means a receipt is present, not that the model is correct.
The receipt's state, started/retry flags, transaction evidence, serialized
result and `semantic_evidence: "unverified"` remain distinct.

The first terminal result is authoritative, including a before-start rejection.
Repeating that exact ID retrieves its receipt; `may_retry: true` on a durable
before-start rejection does not make that ID a resettable execution slot. A
changed plan/context is a new request after the caller has established that no
previous invocation is unresolved. A deadline only stops waiting for a response:
it does not cancel accepted work. Session disable/expiry is a different boundary:
the work item's shared `SessionAdmission` serializes closure against the durable
`TryStart`. Closure first produces `cancelled_before_start` without invocation;
durable start first allows the invocation and its receipt to finish. It does not
interrupt generated code, imply transaction rollback, or promise a hard deadline.

Authentication/target/session matching remains mandatory after closure. A direct
call through an old service may still read original receipts/start-only evidence
or answer an exact prior execute retry; it cannot admit a fresh execute, context
or ping. In the actual App, disable also removes that pipe/discovery session, so
this is not a promise of an indefinitely reachable expired listener. A new session
of the same runtime uses the same journal/target and can retrieve those receipts.

The append-only journal uses record schema 4 with the complete binding and checked
start/terminal transitions. Unknown schema, incomplete binding, duplicate JSON
keys, contradictory receipts or a torn tail make it unavailable. A complete
JSON object without its final newline delimiter is also an incomplete record;
recovery refuses it without appending a delimiter or rewriting the file. Reads and
appends detach returned data. An append error poisons the in-memory index even
if the filesystem received a complete record; recovery determines what is
actually present without re-invoking it. No automatic truncation or silent
migration occurs. Legacy schema 0/3 lines are retained byte-for-byte for archival
inspection only; targetless readers cannot append, and an owned v4 journal refuses
legacy lines. Neither old global journals nor their operation IDs acquire a new
owner merely by deserialization.
Journal and metadata readers share the wire's strict UTF-8/duplicate-key policy.
Malformed byte sequences cannot be replaced with U+FFFD, and BOM-marked UTF-16,
UTF-32 or UTF-8 files are not implicitly converted or repaired. Rejected bytes
remain unchanged. Correctly encoded Unicode, including a literal U+FFFD, is
legal data; rejecting malformed encoding is not a ban on those characters.

An owned journal uses `journals/{journal_id}/owner.lock`, immutable `owner.json`
(schema 1 with the exact target), and `operations.jsonl`. Creation is exclusive;
recovery never creates missing files and verifies metadata plus every record's
bound target. Swapping a valid B journal into A's container fails closed. The
lease file is never deleted. Recovery cannot acquire a live owner's lease and
reports `journal_lease_unavailable`; this may also indicate an I/O/access problem,
not proof of a live process. Missing/corrupt ownership is `journal_unavailable`,
wrong metadata/records are `journal_target_mismatch`, and absence of a requested
record in a verified original journal is `not_found_unconfirmed`, never replay
permission. There is no automatic writable adoption or repair.

## Internal compiler-host transfer

The external/default frame and compiler-response limit stays 16 MiB. Only the
typed Connector-to-CompilerHost request uses a separate bounded profile:
`6 * MaxSourceChars + 1 MiB + 4096 bytes` (38,801,408 bytes). Source still permits
six Mi UTF-16 units. The multiplier covers JSON's worst-case six-byte escaping
per UTF-16 unit, including astral surrogate pairs. The default encoder is
unchanged; merely relaxing escaping would not preserve astral-input capacity.

Reference limits are 256 paths, 32768 UTF-16 units per path, and 1 MiB for the
actually encoded reference-list JSON. Fixed envelope overhead is separately
checked against 4 KiB. The host checks both raw received and canonical encoded
reference budgets; whitespace-heavy raw input can therefore refuse conservatively.
The three fields `protocol`, `source`, `reference_paths` are explicit/required;
unknown/missing/null/duplicate fields and malformed Unicode cannot acquire defaults
or silently change source. An unpaired UTF-16 surrogate refuses before serialization.

`PrepareCompilerRequest` detaches/checks the entire encoded frame before process
launch. Host Program reads that same profile; all ordinary framing methods keep
their existing limit. Bundled host and add-in must be built/updated together.
Large source capacity is not a promise that every source will pass CodePolicy,
fit the separate response limit or produce a valid BIM model.

CompilerHostClient supervises one child exchange under one deadline (after size-
bounded preparation), drains stderr continuously while retaining at most 64 KiB,
requires stdout EOF after exactly one response and checks exit-code consistency.
`ok:true` requires exit 0 plus nonempty Base64-decoded bytes; `ok:false` requires
exit 2, no assembly payload and a nonblank diagnostic. Base64 validity is not PE,
CodePolicy or executable-authenticity verification. Failed forwarding produces
a named compiler diagnostic under the service's `compile_rejected` response,
before execution dispatch; no execution receipt or rollback is invented.

On timeout/cancellation/I/O failure a still-running child is killed and exit plus
I/O completion checked. If cleanup cannot be confirmed, the result explicitly
says `compiler_cleanup_unconfirmed`. Process creation has no hard cancellation
guarantee; neither this profile nor portable child tests establish Windows cleanup,
grandchild/job containment or behavior of an unkillable OS process.

## Process and session lifecycle

App startup takes the actual `ControlledApplication.VersionNumber`, creates fresh
`journal_id` and `instance_id`, and owns one exclusive journal lease until runtime
shutdown, not until the ten-minute session ends. The root is
`%LOCALAPPDATA%/KIR/connector/v4`. Files under the older global connector root are
not migrated, overwritten or assigned a new owner. Restart creates a new runtime;
read-only recovery explicitly addresses the original target, never whichever
journal happens to be current.

Each enable creates new credentials and
`v4/discovery/{instance_id}/{session_id}.json`. A complete temporary file is flushed
and moved without replacing an existing file, only after the pipe has bound.
The record includes target, session, protocol, pipe, token, process ID and UTC
expiry. These files are discovery hints, not proof of liveness or authority.
Two processes can publish concurrently; owner-specific cleanup cannot remove
another process/session's file. Crashes can leave stale discovery files: clients
must validate the native response target/session and cannot infer replay safety
from missing/unreachable pipes. No automatic stale-file cleanup is performed.

The v4 root and owned discovery directories receive current-Windows-user-only
inheritable ACLs; pipe access remains current-user-only. This is not a security
sandbox against the same account. Linux tests replace the Windows ACL operation
only, not publication/cleanup logic, and do not validate these ACLs.

Session timers carry their original session ID. A callback from an already
disposed timer cannot close a newer session. Disable closes admission before
removing resources. Shutdown closes admission, settles queued execution/context
requests while the journal owner is held, then releases ownership. A late compiler
completion cannot append through a disposed scheduler/owner: it returns unresolved
evidence with no retry permission. Reentrant shutdown inside an admitted invocation
fails closed and retains the owner until a later normal shutdown or process death;
it does not pretend that the invocation was cancelled or rolled back.

Offline evidence and remaining risks are described in
[CONNECTOR_RUNTIME_GAPS_RU.md](../../docs/CONNECTOR_RUNTIME_GAPS_RU.md) and the
[linked production test harness](tests/ContextLifecycle.Tests/README.md).
