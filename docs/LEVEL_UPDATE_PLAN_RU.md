# First addressed Level update: a plan, not a dispatch

`kir.revit_level_update` qualifies the source publication and plans a change
to one elevation. Saving the update association, a one-shot send, and
separate fresh/saved field acceptance are implemented: see
[SAVED_LEVEL_UPDATE_RU.md](SAVED_LEVEL_UPDATE_RU.md).
Scoped settlement and the next R1→R2 are implemented through an explicit
ProjectStore/3; this is a check of the fields of the selected elements, not
"the whole BIM revision is implemented." Store/3 goes through a separate
file-level acceptance. Full R03 and live Revit are not accepted.

## Source publication

`bind_original_publication(project, record, response, required_outputs=...,
credentials=..., request_id=..., recovery=False)` requires a checked
Archive/2 and the exact source ProjectRevision. It checks the
instance/module/output digests, order, body descriptors, and the native
response binding. The archive is not recompiled and is not turned into a
fresh PlannedProgram.

The first profile is `original-flat-create/1`: flat create ops with a
one/id result, with no macros, nested contracts, mutations, or separate
planned units. A direct flat result with ok=true, full primary rows, no
errors/violated postconditions, and a full change manifest are required.
Native error resolutions require a separate review. What is not supported is
not silently unfolded.

For the selected create_level/create_directshape/create_solid_blend, an
original capture is required: the identity matches the primary id, the ID is
present in added and absent from deleted. Reassigning an ID/UID to a
different create output is rejected. A body-owned podium is allowed when the
source descriptor matches, with no re-run of the kernel. This is a selected
mapping, not full acceptance of the building or native attestation of
Project metadata/global uniqueness of ownership between different archives.

## The new change

`plan_level_elevation_update(base, proposed, publication=..., observation=...,
target=(instance_key, output_key), protected_outputs=...)` requires:

- the exact R0 of the source publication and a direct child R1 for the first
  step;
- an explicit module with no recipe and exactly one change to
  create_level.elev_mm;
- no other changes to metadata/parameters/modules/outputs/order;
- the same runtime/open-document key and the full selected-scope original
  UIDs;
- a Project basis, a writable Double builtin parameter, its observed
  unambiguous name, and a match between the actual baseline and the value of
  the authoring base revision;
- no overlap between the protected outputs and the target, and explicitly
  affected dependencies.

The numeric ID is taken from the observation and can change; the UID remains
the source one. If compiler normalization changes the parameter name, the
plan refuses.

For the next step, `baseline=store.level_baseline(stream_id)` is used
instead of `publication=...`. An accepted checkpoint and the absence of a
pending item are required, `base == checkpoint.proposed_revision`, a direct
child, and a new parsed observation of the same runtime/document with a
revision no lower than checkpoint.after. The observed fields of the whole
selected scope must match checkpoint.after. The original publication still
names R0 and is not reconstructed as a fresh binding.

`RecordedLevelBaseline` is a public inert carrier, not permission to send.
That is why the Store again compares the archived before-observation with
the actual accepted.after **inside the reserve transaction**. A correct
checkpoint digest with substituted carrier fields does not bypass this
check. The planner itself can work with a historical snapshot; sending
always requires the current store CAS.

`publish_level_update(..., project_store=store)` saves the archive, reserves
a pending item against the expected checkpoint, and then permits one
exchange. An iterative plan requires a store with the same store_id. At the
first step the legacy no-store API is still available, but gives no
guarantees of stream ownership. A separate
`qualify_level_settlement(..., after=...)` requires a full pass of the
selected field checks; `store.commit_level_settlement` atomically saves this
evidence, advances the checkpoint, and clears exactly its own pending item.
The authoring head does not change.

Unknown, a lost reply, and a failed field acceptance do not clear the
pending item. For a fully confirmed bound `not_started`,
`qualify_level_not_started` and `store.commit_level_not_started` are
implemented after an explicit transition to Store/4. This transition does
not advance the checkpoint; a new plan/context and reservation are performed
explicitly. Store/3 continues its previous behavior with no release of the
pending item. A confirmed rollback and the remaining started/unknown
outcomes require a separate further path. There are no TTLs or new
operation IDs to bypass unknown execution. The result is one new set_param
PlannedProgram, the previous observation precondition, target/type/protected
object guards, and a dependency-impact report.

`prepare_level_update(update, operation_id=...)` prepares exactly this new
plan. It automatically passes the target, the observation precondition, and
all identity guards; there are no arguments here to substitute them.
Preparation does not save the archive, does not send the request, and does
not refresh the context. `operation_id` is set explicitly.

Do not pass it to the ordinary first-send publisher, which obtains a new
context: the update must preserve the baseline observation. The report is
not a saved update association or permission to repeat execute. The six
dependent outputs are not declared unchanged; the safety of the remaining
objects requires an after-readback.

## Evidence and open boundaries

The initial agent slice: 61 tests with synthetic native data; independent
acceptance of the whole module is not finished yet. MAIN added a check of an
actual three-tower authoring residential complex, an OCCT podium, and a
typed refinement of section A: handoff → JSON reload → materialization →
archive codec → original binding → observation → a new elevation of
3600→3800 → guarded source 2023/26.

24 source operations produce one mutation with no repeated
Level.Create/DirectShape.CreateElement. B/C/podium and the asset bytes are
preserved; 6 affected and 3 protected outputs are named. During the control
run, Python file writes and subprocesses are forbidden by the audit hook.

The archive codec runs in memory, not through SQLite: this is not a
restart/durability test. The receipt and the observation are synthetic, not
a Revit readback. The generated C# in this control is not executed and not
checked by Roslyn. Shipping requires a saved update workflow, an independent
after-readback, and live Revit 2023/2026.
Test: `test_level_update_residential_memory.py`.

## Checking the supplied after-observation

`level_update_acceptance.assess_level_update` compares the prepared artifact
against the plan, including the guards and the observation precondition, and
reuses the shared write-response adapter. The execution result is stored
separately: a check violated after the commit does not become an invented
rollback.

Separate checks: the execution target/parameter, the new elevation, the
observed protected fields, and the absence of protected IDs in the full
invocation manifest. A foreign/stale/incomplete after scope, unavailable
fields, and remapped addresses do not produce an overall PASS. Missing
before fields are not counted as proof of a subsequent change. VersionGuid
is not used as an oracle of geometric equality.

`target_satisfied` and `scope_satisfied` relate only to these checks;
dependent geometry, protected geometry, and engineering are explicitly
not_evaluated. With an empty protected scope, its checks are not performed.
The check reads nothing from Revit, does not send or repeat requests, and
saves no files.

The initial 17 in-memory controls and an authoring residential complex with a
synthetic after-response passed with no Python file writes/subprocess. The
subsequent overall acceptance includes 337 tests, real SQLite/a Python
restart, and both residential-complex iterations; the source review is
finished for the named scope. Native behavior is still not proven. The exact
strip and limits are in
[SAVED_LEVEL_UPDATE_RU.md](SAVED_LEVEL_UPDATE_RU.md).
