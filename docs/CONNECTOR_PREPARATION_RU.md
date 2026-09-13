# Preparing an exact artefact for the standalone Connector

Foundation branch, 2026-09-05. `kir.revit_connector` is a pure Python layer for
preparing the source and the requests. It sends nothing and opens no Revit. The
native `/4` wire has an offline acceptance; this API's existence does not make a
Windows/live connection ready. The legacy MCP/HTTP Bridge is not replaced by the
new port.

## Separated identifiers

- `RuntimeTarget`: a persisted `journal_id`, the original `instance_id`, the Revit
  version. Two processes of the same user are two different targets.
- `ContextPrecondition`: an opaque token of the open document, the mandatory
  revision, and the exact optional view/selection conditions. This is not a
  project revision and not a fingerprint by file name.
- `SessionCredentials`: the target of a currently open door, the `session_id`, and
  a secret token. Changing the session does not change the source SHA or the
  original execution binding.

These Python values do not by themselves prove where the context came from. The
authoritative check of the native target/document/revision before an effect
remains the Connector's job. The token is not part of the credentials' repr or of
the artefact, but it is unavoidably present in a detached wire request: such a
request must not be written to an ordinary log.

## Preparation and addressing

`prepare_execution(program, target=..., precondition=..., operation_id=...)` calls
the existing compiler for the target's year. The result stores the exact immutable
`PlannedProgram`, its `GroundedProgram`, the full C# wrapper, and the SHA-256 of
that full source. The source cannot be replaced by mutating the exported
dictionary. The public constructor/loader does not turn saved claims into a fresh
compilation. Frozen Python is not protection against hostile Python in the same
process: native policy and input binding are still mandatory.

This slice has no parameter for an external grounding snapshot: the old census
carrier does not prove its own binding to a Connector token/revision. Legitimate
compiler refusals are preserved. `bulk` does not change the policy of an
already-built plan.

`expected_identities=Sequence[ElementIdentityProof]` lets you pass the existing
compiler guard the expected ElementId/UniqueId/VersionGuid. The sequence is copied
into a tuple before compilation; wrong types are rejected. The guard becomes part
of the full source and its SHA, so changing the expected identity changes the
execution input and is checked by the saved archive. Contradictory proofs for one
ID are rejected by the compiler. For a query, an explicit argument (even an empty
one) is rejected: the query emitter does not yet apply this guard. Ordinary
preparation without the argument keeps the previous source.

`PreparedExecution.expected_identities` keeps a frozen tuple of exactly the
explicit guard inputs that were passed to the compiler. This is not a new native
observation. The field is not added automatically to old Archive/1–2: their wire
stays the same, and the guard is already bound by the full source SHA. The new
update binder does not need to parse the C# to check whether every guard of the
plan was passed.

These are the caller's input conditions, not proof of how the elements were
actually read. Revit's `VersionGuid` describes the version between saves/syncs,
not every in-session edit. When acting on previously read values, you must save
the **precondition of that exact observed document revision**; you cannot read the
values, then refresh the context, and pass them off as fresh. The API
documentation recommends DocumentChanged for observing in-session changes; the
Connector already keeps that counter, but wiring a fresh element readback to it is
not yet implemented. The first-send publisher is not an update workflow and does
not get the new argument automatically. This primitive does not close R03.

`execute_request()` and the ordinary `receipt_request()` require a session of the
same target. Passing an old artefact to a different runtime is rejected. An
explicit `recovery_request()` may go through a new session B, but it keeps a
separate `recovery_target=A` and carries no source: it is only a read of the
original journal, not a re-execution or the assignment of an old operation to a
new model.

The preparation module has no automatic retries, no reading of discovery, no
Windows NamedPipe, and no receipt assessment. Discovery and response assessment
are separate accepted boundaries, not an automatic send or proof of execution. The
C# source limit is counted in UTF-16 code units, as in .NET; the frame is counted
in actual UTF-8 bytes of the JSON with credentials. This is a limit on the
assembled request, not a sandbox, and not a cap on all of the compiler's costs.

## Getting a context without guessing the document's name

`credentials.context_request(request_id=...)` builds one read-only request to an
explicitly chosen target/session. Sending it, establishing a trusted OS channel,
and the deadline must be provided by the transport; this helper opens no
connection.

`assess_connector_context_response(raw, credentials=..., request_id=...)` checks
the same bounded strict JSON as a write receipt: the exact envelope,
target/session/request, the 12 fields of the actual `ContextSnapshot`,
types/counters, and a version match. A wrong, foreign, or incomplete response does
not produce a usable precondition. A full "document not open" response has
`read_complete=True`, but it likewise does not allow obtaining a document
precondition.

`result.require_precondition(bind_view=True, bind_selection=True)` saves the
opaque token of the open document and its revision. Both UI decisions must be
explicit; `False` deliberately drops exactly that condition. The document's name
is not used as an identity. Family/read-only/modifiable flags are available as
observations: this method itself does not grant write permission and does not
prove the document is still in the same state. The native boundary must check
again. The context is not a grounding census, a project revision, or a saved BIM
identity. Matching JSON fields likewise does not prove transport authenticity or
the freshness of the observation.

MAIN: 76 new context tests + the previous result 85/preparation 37 — 198 passed.
The associated strip context 76/discovery 28/actual replay 17 — 121 passed / 8.56 s.
Seven new actual replay cases use the production Collector/Tracker/Service/
JsonFraming, but the Revit objects/events are **stubbed**, the model's code is not
executed. Checked: no-document, real DTO flags, sorting of the selection digest,
two revision events, and the public context→prepare path. This is not live Revit
and not a Windows test.

An independent review found a missing reverse check: a non-zero selection count
could carry the hash of an empty selection. MAIN confirmed the RED and fixed the
relationship in both directions. The final associated strip context 77/result
85/preparation 37/replay 17/discovery 28: 244 passed / 11.76 s. This checks internal
count/digest consistency, not the recovery of an unknown list of selected
ElementIds.

## Response to a compiled query

`assess_connector_query_response(prepared, raw, credentials=..., request_id=...)`
uses the same validator for the native route/receipt/binding as the write adapter,
but a separate result contract. It requires a query PlannedProgram, a successful
call, and a full **empty** change manifest — including the absence of transaction
names. A truncated manifest or any changes yield no usable query result. A write
plan is not accepted by the read adapter, and vice versa.

`ConnectorQueryAssessment.result_available` means only that a linked JSON object
is available to the next typed consumer. It does **not** mean "the element was
found," "every field was read," or "the intent was checked": even `{}` or the
string `not_found` inside the result are preserved for a separate parser.
`result` and `receipt` return detached values; the native receipt and errors are
never rewritten into an invented commit/rollback. The `ok` field is deliberately
absent here.

When a result is available, `precondition` keeps the original document
key/revision that the Connector checks before the query. Reading an old receipt
does not make this baseline fresh and does not substitute for a later context. The
next mutation must satisfy exactly that revision, or perform a fresh full read.
The contract does not attest to the working of Revit events, OS authentication, or
the absence of side effects invisible to the native change tracker.

The internal positive transport tests use a real portable pipe and the native
Service/Journal/serializer, but the result JSON is explicitly seeded: the
generated C# is not invoked, and reading real Revit is not thereby proven.
Specialized UID/Level query and a field-level parser are now implemented
separately: [ELEMENT_OBSERVATION_RU.md](ELEMENT_OBSERVATION_RU.md). They do not
turn the general availability of a payload into an automatic permission to
mutate.

## Receipt for a saved source

`assess_connector_saved_write_response(record, raw, credentials=...,
request_id=..., recovery=False)` accepts a checked `SavedExecutionRecord` of
Archive/1 or /2. The common native validator checks the response against the
archive's binding, without recompiling the old project and without building a
`PreparedExecution` or a `PlannedProgram` from the saved claims. The fresh
write/query APIs still do not accept a loaded record in place of a fresh
artefact.

`ConnectorSavedResultAssessment` returns `result_available`, `binding_matches`,
`archive_digest`, and a detached `result` and `receipt`. A payload's presence does
not mean a commit, satisfied postconditions, original element ownership, or a
right to retry. So `{}`, `ok:false`, and a correct but truncated change manifest
may all be available for inspection; the next original-publication consumer must
refuse if its stronger conditions are not met. The `ok` and `outcome` fields and an
execute method are absent here.

An ordinary lookup requires the original runtime target. With `recovery=True` the
response may go through the current session B, but the inner receipt must still
match the original target A, operation, source SHA, and precondition from the
archive. No new context is substituted in. The absence of a receipt does not
become permission to repeat the operation. The adapter itself sends nothing and
does not modify the archive file.

Checked: Archive/1–2 reload/inspection in a fresh process with the
compiler/planner/PreparedExecution constructors forbidden, plus an actual portable
receipt lookup after publishing a seeded fixture. This is not a native attestation
of the saved Project metadata and not execution of C# inside Revit.

## Actual compiler conformance

`connector/revit/tests/CompilerConformance.Tests` links the real `Compiler.cs` and
`CodePolicy.cs`, it does not copy the validator into Python. The optional strip
gets the licensed reference DLLs through explicitly named paths; the versions of
both Revit APIs are checked by AssemblyName metadata, not by folder name.
Assemblies are generated in memory and are not executed.

The lead checked the public preparation path: 37 Python tests (independently
repeated) and 8 parametrized compiler cases (65.48 s) against the real APIs
2021–2026. Checked: create_level, conceptual towers, a section, a mesh, and a
composite podium/refined/changed for 2023/2026, plus real policy/syntax/wrapper
refusals. The strip before the wrapper was moved into public preparation was also
independently repeated: 8 passed / 70 s. The numbers overlap and do not add up.

A section with holes gives the existing `KIR-E003` on 2021 — that is a refusal,
not a successfully compiled section. The old `expected_document` guard via
`doc.PathName` remains a deliberately red policy control. The new source does not
lift this ban: the document is checked by the native runtime against the
precondition. The full guarded live pipeline is not yet accepted, and D3/R01/R02
are not closed by this matrix.

`kir.connector_result` checks the route and the original binding before the
common `assess_write_result`: 85 tests and 396 independent mutations are
accepted. The actual Service/Journal/JsonFraming replay fixture also passes (now
17 cases, including discovery/context), but its original receipt is explicitly
seeded. This is wire/recovery compatibility, not proof of Revit invocation or of
the Windows transport.

An independent check of the actual serializer found a capacity gap: a Unicode
source within 6 Mi UTF-16 units can pass the Python frame limit of ≤16 MiB, yet
exceed the internal CompilerRequest limit because of native JSON escaping. An
encoder-only fix is not enough for astral symbols. A separate internal frame
profile and process supervision are now implemented and have passed MAIN's
original controls; independent lifecycle acceptance is still pending. The external
frame limit was not changed. The forwarding itself does not prove a successful
compilation or a BIM result obtained. The example, the separate budgets, and the
state of the fix are in DELIVERY_PLAN_RU.md and connector/revit/PROTOCOL.md.
