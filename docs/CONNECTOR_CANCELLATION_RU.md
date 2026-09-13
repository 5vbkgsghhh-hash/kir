# Cancellation before start: journal control, not rollback

Status: implemented and verified offline. The command does not touch the document,
CompilerHost, or ExternalEvent; it writes a terminal receipt to the Connector's own
journal. Code that has already started is not interrupted. Live Windows/Revit and the
new add-in packaging are not yet verified.

## Wire and authority boundaries

`cancel_before_start` is a new kind of the existing Connector/4. Exactly ten fields:
the usual protocol/request_id/target/session_id/token/kind/timeout_ms and
operation_id/source_sha256/precondition. Precondition contains all four fields,
including explicit null active_view_id/selection_digest. `source`, `recovery_target`,
and any extra fields are forbidden, even as null.

Target must match the source archive and the serving runtime. Recovery B
still only reads journal A. Credentials/session are checked before access;
a new cancellation requires an open admission. The exact prior receipt can be read
even after the session is closed, the same as an ordinary receipt lookup.

Python builder: `record.cancel_before_start_request(credentials, request_id=...)`.
It performs no I/O and does not send the saved C#. This is a builder control-plane write,
not a permission to execute and not a read-only operation on a later send.

For the C# DTO use `JsonFraming.Write` or `WriteAsync`: Encode is built specifically
to produce the exact cancel shape, preserving the mandatory internal nulls. Values of
the forbidden Source/RecoveryTarget are not silently dropped: the write refuses before
the first bytes. The general `JsonSerializer.Serialize(ConnectorRequest)` is not by
itself a cancel wire encoder. The other kinds keep their previous bytes;
the global IgnoreNull is not enabled.

## Atomicity

SessionAdmission holds the gate up to `OperationJournal.AppendTerminal`. The journal
serializes this append with TryStart:

- Cancellation won: terminal `cancelled_before_start`; a late queue returns
  this receipt, does not call the generated Execute.
- Start won: `running_unknown`, no new cancelled receipt.
- The exact terminal already exists: the original result is returned, including
  a committed one; it cannot be renamed into a cancellation.
- A different binding of the same operation ID: conflict, the original journal is not
  changed.
- Error/partial append/closed owner: unknown, not proof of cancellation.

Native `may_retry=true` in the before-start receipt keeps the previous wire convention.
The workflow does not turn it into a right to resend the old mutation.

## Working with a pending KIR

```python
from uuid import uuid4
from kir.level_resolution import request_cancel_pending_level_update

snapshot = store.level_baseline(stream_id)
assert snapshot.pending_archive_digest is not None
attempt = request_cancel_pending_level_update(
    store,
    stream_id=stream_id,
    expected_pending_archive=snapshot.pending_archive_digest,
    advertisement=selected_advertisement,
    client_path=trusted_client_path,
    request_id=str(uuid4()),
)
```

Store/4 and a writable handle are mandatory. The exact expected archive keeps an old
UI retry from cancelling a new pending. After one cancel exchange, only a bound
NOT_STARTED admits qualification and SQL resolution. Committed/started/unknown are
returned for a separate review/reconciliation, without this call clearing anything.

On a conflict or a storage loss, an ACK is only allowed as a readback resolution of
the same archive with the same native receipt digest. It does not repeat the write
and does not clear a new reservation. `resolution_recorded` is a historical fact, not
a promise that pending is currently empty. `may_retry` stays false.

## Checks, and what is not checked

MAIN rebuilt the core/helper from scratch in `.work/runs/cancel-final-Q1ezuK`. The full
native headless runner: **124 passed, 0 failed**, including 19 cancellation cases.
The actual Engine/Queue runs a tiny generated assembly against Revit stubs:
without a cancellation the mutation counter is 1, after cancellation before
enqueue/drain — 0. Checked: races, closing admission, mutating the source DTO after
capture, owner disposal, partial append, ACK loss, sync/async DTO, and old wire bytes.

Compile-only matrix 2021–2026: all six builds with no warnings/errors. The actual
AssemblyName API versions 21/22/23/24/25/26 were checked, not just folder names.
This is not a load into Revit and not Windows authentication.

Python→new PipeClient→Service→Journal is checked by a separate portable strip.
The final MAIN repeat of this strip with the new helper: **174 passed / 83.22s**,
including native cancellation integration, Python control/CAS, transport, and CLI.
Its server uses Revit stubs and seeded existing execute results; a late execute
after cancellation checks the Service/journal guard. Checking the Engine/Queue itself
is the separate headless strip above. No test building rows are passed off as a
built native BIM model.

The earlier final installation packages are kept, but **are stale relative to
this new command**. They were not rebuilt or reinstalled. A successful ping of the
old /4 server must not be taken as proof of cancel_before_start support:
an unknown-kind refusal does not permit clearing a pending.
