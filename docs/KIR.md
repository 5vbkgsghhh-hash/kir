# KIR language and compiler

KIR is a compact typed program for a building. A program is an ordered set of
operations with explicit identities and references; its meaning comes from the
registry rather than from a prompt or a code template.

## Authoring surface

The Python SDK is a convenience layer over the registry. It can compose loops,
functions, parameterized modules and numerical geometry in Python, but it
cannot introduce a hidden operation or bypass a KIR validation rule. The
lowered result is ordinary KIR JSON, suitable for storage, inspection and
deterministic compilation.

KIR models use millimetres as their public length unit. Host-specific units,
API names and version conditions are handled below the IR boundary.

### Environment diagnostics

`kir doctor --env` lists known legacy aliases and currently present `KIR_*`
names. It shows which name supplies the value and distinguishes unset, empty
and nonempty values; the values themselves are never printed. An explicitly
empty new name still overrides its former name. This is not a complete settings
registry: absent settings without aliases, call-site defaults and whether a
present unregistered name is consumed are not inferred. The command does not
compile a program or contact a host.

## Compilation pipeline

### Read-only clash report for a saved project

```sh
kir project clash-report project.sqlite --revision <revision-id> --exact --clearance-mm 50
```

This reads a `ProjectStore`, not a folded-tree JSON or a live Revit document,
and prints the existing project-body clash report. Omit `--revision` to analyze
the head read by the analyzer. The returned `revision` identifies the analyzed
snapshot even if another process later advances the head. Clearance must be
finite and nonnegative; zero declares no clearance requirement. Exit 0 means a
report was obtained, **not** that the project is clash-free. Keep `findings`,
`not_evaluated`, body counts and `analysis_limits` together; `possible` is not
an exact intersection, and an empty evaluated scope is not building acceptance.
Store, revision and analysis errors return exit 2 with a named JSON error,
not a fabricated empty report. Argument-syntax errors follow the existing CLI
policy: usage on stderr and exit 2.

The command neither changes the store/head nor builds a viewer scene or executes
anything in Revit. It is a local CLI computation and may run for a long time;
historical-revision analysis currently audits the stored history. Exact-phase
limits and unavailable geometry remain explicit. No MCP filesystem-read tool or
background-job API is introduced by this command.

### From source to emitted code

1. Parse and validate the envelope against registry-generated schema.
2. Resolve references and ground symbolic selectors against supplied model
   facts. Ambiguity becomes a named refusal with candidates.
3. Build a dependency graph and transaction plan.
4. Choose version-specific emitter paths for Revit 2021–2026.
5. Produce C# and typed diagnostics; execution is a host concern.

Step 5 ends at emitted text. Compiling that text with Roslyn against real Revit
reference assemblies is a separate gate (`kir/instruments/compile_gate_offline.py`)
and is not run in this repository — see border B1 in
[PROMISES_RU.md](PROMISES_RU.md).

An operation has a declared effect, parameter kinds, identity cardinality and
capability set. The same registry feeds schema generation, the SDK, planning,
documentation helpers and emitters, so these layers do not maintain independent
lists of operations.

## Capability contract

Meaning is not the same question as reach. The registry says what an operation
*means*; five separate axes say what the tree can *do* with it, and each axis
has exactly one live carrier:

| axis | question | carrier |
|---|---|---|
| `backend` | does the op compile to C#, and through which emitter | `authoring._EMITTERS` + `authoring._SOLO_PROGRAMS` + the `query_*` branches of `compiler._emit_op` |
| `preview` | is the op drawn in the pre-transaction plan | `preview._program_shape` |
| `witness` | does a post-commit obligation check it | `translation_cert.REFINEMENT` |
| `reverse` | is the op lifted back out of a model as the same op | `reverse_contract.REVERSE_CONTRACTS`, dispatched by `decompile.lift.LIFTER_TABLE` |
| `clash` | does the op give the building a body | `clash_bundle.OP_NO_BODY` over `clash.hulls.KIND_TABLE` |

`kir.capability` projects those five into one answer per operation —
`capabilities(op)` and `limits(op)` — and it is a projection, not a sixth
table: no operation name is copied into it from a carrier. The single record
it owns is `PREVIEW_LIMITS`, because the preview axis had no carrier at all:
64 of 83 registry ops fall into `OmitReason.OP_NOT_DRAWN`, and silence there
reads as "everything is drawn".

Two laws hold this together, and both are executable
(`kir/tests/test_the_registry_owns_every_capability.py`):

* **closed outcome** — every op, on every axis, is either capable or carries a
  named reason why not. A limit without a reason is a blind spot nobody
  declared;
* **registry veto** — an axis may not claim a capability the registry rules
  out. A reading op writes nothing, so it has no body, no witness and no
  lift. This law exists because a capability set expressed as the *complement*
  of a hand-kept table cannot tell "we forgot to name the reason" from "it can
  do it": on 2026-09-07 `query_element_state` — a `query`/`READ` op — was
  declared body-making for exactly that reason, the third name to fall out of
  that one table.

An axis whose declaration and measurement read the same carrier cannot fail.
Both one-sided axes (`reverse`, `clash`) are therefore held by a perturbing
oracle that drops a name from the manual copy in-process and requires the law
to go red.

## Expression power

KIR is intentionally not a replacement for Python. Python is the authoring
language for algorithms, repetition, parameter search and reusable functions.
KIR is the typed execution envelope. This keeps a complex building concise for
an AI while keeping the target-facing part deterministic and inspectable.

DirectShape-style geometry remains a supported carrier for geometry that has no
honest native-BIM representation yet. Promotion to native BIM is a separate,
evidence-bound revision rather than a silent replacement.

### Stable program identity

Use `sdk.program(lineage="residential-project")` in ordinary Python, or
`program(lineage="residential-project")` in the injected authoring DSL. The
optional JSON envelope field is the same `lineage`: 1–64 ASCII letters, digits
or `._:-`. Keep it stable across revisions. Project materialization uses the
project ID automatically. SDK `None` omits the field; malformed supplied values
are not converted to an anonymous program.

Lineage survives typed planning and contributes to the plan digest. New plans
with explicit lineage use evidence schema `/5`; anonymous plans retain `/4`.
Old archives are not upgraded on read or given a new owner. A stable ownership
marker does not permit overwriting an existing type's different composition.
The standalone sandbox still uses its injected DSL; `import kir` is not enabled
there by this addition. Normal Python SDK scripts run outside that sandbox.

### First Level edit after a stored selected publication

`kir.stored_level_update.publish_first_stored_level_update` completes a bounded
Python workflow: look up the original stored CREATE receipt, read the requested
UIDs, plan one explicit Level elevation change, reserve and send it once, then
read back and settle the named fields. It accepts flat whole/selected submissions,
not staged imports. The authored proposal must already be saved as a direct child
of the CREATE source, with the explicit handoff performed before CREATE.

Supply the store, `create_archive_digest`, `proposed_revision_id`, `expected_head`,
`target=(instance_key, output_key)`, explicit `protected_outputs`, the selected
Connector `advertisement`/`client_path`, original `expected_target` and
`expected_document_key`, a new `archive_path`, and caller-owned `operation_id`.
The expected authored head is checked again inside the pending-reservation
transaction; it is not locked for the duration of native execution. Existing
publication selection remains explicit: unselected conceptual source stays in
the authored project without being recreated in the native model.

`reconcile_stored_level_update` accepts the store, `stream_id`,
`expected_pending_archive`, and the same runtime/transport/document inputs.
After a restart or lost response it looks up that exact setter, performs read-only
queries, and records a qualifying settlement. It never sends CREATE or the setter
again. Unknown receipts leave pending intact. Confirmed no-start uses the separate
explicit Level resolution workflow; it is not an automatic retry signal.

Results separate `mutation_execution`, `scope_satisfied`, and
`storage_acknowledgement`. A committed setter remains committed if after-readback
or local settlement fails; neither failure permits mutation retry. An
`already_settled` result acknowledges historical storage, not a fresh observation.
Acceptance covers the Level and explicitly protected fields only, not dependent
geometry, whole-building preservation or engineering approval. This is a Python
API workflow; no native-edit UI/MCP command is implied.

### Explicit staged publication

`kir.staged_publish.publish_staged_project` sends one already qualified
`StagedCreateProjection`. Supply a writable Store/8, the expected authored
revision and document key, selected Connector advertisement/client, and a stable
operation UUID. The existing partition/projection factories require original
CREATE receipts plus fresh Level/type observations for imported dependencies.
Their original inputs and receipts must already be retained in the store.

Only new exports are reserved and created; imported levels/types are not created
again. Import links and output ownership are committed before the first send.
The projection's observed context is never replaced with a newer one. After a
lost response, use the same store's operation lookup and
`kir.standalone_publish.recover_stored_create`; do not call publication again.

This is an explicit Python stage, not an automatic whole-building sequencer.
The supported profile is direct levels, host types, walls and floors. It does not
split a giant instance, persist identity-replacement ledgers, or bypass the actual
source/transport budgets. Independent stages need not be globally blocked by an
unrelated pending stage. Execution receipts do not establish engineering or
whole-building acceptance.

## MCP HTTP access and output files

Stdio keeps its existing local-client contract. HTTP is separately enabled:

```sh
python -m kir.mcp --http --token-file /private/path/kir-mcp.token --out-root /path/to/outputs
```

The token file must contain a randomly generated 32–4096-character ASCII bearer
token without whitespace (a final newline is accepted); on POSIX it must not be
readable by the group or other users. `KIR_MCP_TOKEN` is an alternative. Token
values do not belong in command arguments, URLs, repository files or logs.
Every HTTP request requires `Authorization: Bearer …`; stdio does not. The SDK's
Host/Origin and request-body protections remain active, and no permissive CORS
policy is added.

Non-loopback binding additionally requires `--allow-remote` and
`--public-origin https://your-host[:port]`. This profile requires a TLS-terminating
proxy: the public Host and Origin must match, and the ASGI request scheme must
be HTTPS. The same explicit remote profile can keep `--host 127.0.0.1` behind a
local TLS proxy; it does not require an externally reachable backend socket.
Do not expose the internal HTTP port or trust forwarded headers from
arbitrary peers; configure the proxy and Uvicorn's trusted proxy addresses as
part of deployment. The KIR command does not provision TLS, network isolation,
per-user authorization or credential rotation. A bearer token grants access to
the configured tools, including any separately enabled host capabilities.

For HTTP, `out_dir` is confined to `--out-root` (the current directory if omitted).
Relative paths start at that root. Output files are created exclusively: existing
files and symbolic-link traversal are refused. Each version reports its file
result; the HTTP response separates `native_model_effect` from aggregate
`filesystem_effect` and lists `files_created`. `wrote_nothing` is false after
a created file or uncertain file attempt. Previously created files are not deleted
on a later failure. Platforms
without `dir_fd` and no-follow directory handles explicitly refuse HTTP file
output; inline responses and the existing stdio path remain available. This does
not claim isolation from a hostile local process with control of the same files.

Both the app and MCP reject non-finite JSON input before invoking an action.
An invalid result after invocation is different: `response_schema_failure`,
`effect: unknown`, `retry_safe: false`, correlation IDs in `context`, and an
explicitly partial diagnostic projection with `invalid_paths` and truncation
flags. A reported `committed` value inside `reported_result` is preserved as a
report, not re-certified by the encoder. A missing/invalid response does not undo
an action: inspect the original operation and saved state before retrying.
