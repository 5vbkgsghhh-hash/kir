# Agent tasks, checkpoints, and proposals

This layer saves work on the authoring project, but **does not run an LLM**.
Two worker processes can work in parallel outside a SQLite transaction, save
proposals, and finish. A new coordinator reads the tasks and accepts
compatible changes through the existing authored merge.

## Ownership and authority

Two tables, `task_heads` and `task_events`, are added by an explicit
migration, `kir-project-store/5`, into **the same ProjectStore**. The linear
history, the geometry assets, and the native ledger `/4` keep their previous
owners and identifiers. Branch candidates are not added to the linear
history until the coordinator's decision. The assets of all saved proposals,
including rejected and superseded ones, remain owned by those proposals;
`history()` checks these references too.

The host separates coordinator/worker calls. The `actor` string is a local
assignment label, not authentication. If a worker is given direct writable
access to the SQLite database or to the coordinator API, the grant does not
protect against a deliberate bypass. This layer is not presented as a
sandbox or as protection against an attacker.

The grant is stored separately from `ChangeProposal.scope`. The coordinator
sets the base, the objective, the actor, and the allowed instances/modules/
project fields. `tools` and `budgets` are a saved policy. The agent's full
budget, including LLM tokens, remains `budget_enforcement=not_established`;
the recipe adapter already checks the allowlist and counts charged tool
reservations before running. `execution=not_observed` has the scope
`assigned_worker_liveness`, and does not deny the history of individual tool
calls: recording an assignment/checkpoint by itself does not prove the
process is running right now.

## Python API

```python
from kir.project_store import ProjectStore, TASK_STORE_SCHEMA
from kir.project_merge import ProposalScope
from kir.project_tasks import create_task, read_task, submit_task, decide_task

store = ProjectStore.open("project.sqlite", readonly=False)
head = store.head()
store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=head.revision_id)
assigned = create_task(
    store, task_id="facade-a", base_revision=head.revision_id,
    actor="facade-worker", objective="Уточнить фасад башни A",
    scope=ProposalScope(instances=("tower-a",)),
    tools=("project.read", "author.python"),
    budgets={"max_tokens": 50000, "max_tool_calls": 100})["task"]

# The worker returns an ordinary ChangeProposal. Proposal.author must match
# the assigned actor; its base and scope are checked against the saved grant.
submitted = submit_task(
    store, "facade-a", proposal, request_id="submit-1",
    expected_version=assigned["version"], generation=assigned["generation"],
    actor="facade-worker", assets=[])["task"]

# The coordinator explicitly names both reviewed versions: the task's and the project's.
decision = decide_task(
    store, "facade-a", request_id="decision-1",
    expected_version=submitted["version"], generation=submitted["generation"],
    actor="coordinator", proposal_id=submitted["proposal"]["proposal_id"],
    expected_revision=store.head().revision_id)
```

The `proposal` in the example is the result of a separate authoring step,
not an automatically computed object. `checkpoint_task(..., notes={...})`
saves structured findings, questions, and the next step. `read_task`,
`task_history`, `list_tasks` open a read-only connection even from a
writable handle and do not recover the hot journal. Reading does not run
the source, the kernel, or native effects. Materialization is separate.

## CLI

```sh
python -m kir project task-upgrade project.sqlite --expected REVISION
python -m kir project task-create project.sqlite facade-a --base REVISION --actor facade-worker --objective "Уточнить фасад" --allow-instance tower-a
python -m kir project task-list project.sqlite
python -m kir project task-read project.sqlite facade-a
python -m kir project task-history project.sqlite facade-a
```

`task-checkpoint` accepts a JSON object of notes, `task-submit` a
ChangeProposal and explicit `--asset` files. For these and for
`task-reassign/revoke/decide`, `--expected-task-version`, `--generation`,
`--actor`, `--request-id` are required. `task-decide` additionally requires
`--proposal-id` and `--expected` authored head. The exact arguments are in
`python -m kir project task-decide --help` and the neighboring commands. A
missing DB is not created; task commands do not perform an implicit schema
upgrade. A saved merge conflict returns a decision JSON and exit 1; a
malformed/storage refusal returns exit 2. Reading does no upgrade and no
change to the file.

## Transitions and redelivery

- `assign → checkpoint* → submit → decide` ends in `accepted` or
  `conflicted`. The absence of authored conflicts does not mean the norms
  were met, the geometry is correct, or the BIM model was accepted.
- `reassign_task` explicitly changes the actor and generation, preserving
  the source grant/base. A different base or a different scope creates a
  new assignment/task. Old checkpoints keep the number of their own
  generation; they cannot be mistaken for a new report.
- `revoke_task` closes the assignment and increments the generation. It
  does not end the external process, does not cancel a completed Revit
  transaction, and does not delete history.
- Every new transition requires exact `expected_version` and `generation`.
  `decide_task` additionally requires the exact `expected_revision` of the
  authoring head: if it has changed, the accepting side must reconsider the
  proposal.
- The decision, the revision/assets, and the head CAS are committed in one
  SQLite transaction. A conflict saves the report and the proposal without
  creating a partially accepted revision. A no-op also gets a decision, but
  does not create a new authoring revision.
- `request_id` is an explicit idempotency key within a task. An exact
  repeat returns the previous `event` with `inserted=false` and
  **separately the current** `task` and `head_revision`. It does not roll
  the task back to a past generation and does not rewind the head. The
  same key with different input is rejected.
- After a `StoreCommitUnknown`, it is fine to read `task_history` and find
  the exact request/event. You must not declare a refusal or repeat an
  external effect just because the write's confirmation did not arrive.
  These APIs perform no external effects.

## Sizes and boundaries

Up to 1000 events per task, 32 MiB per event, and 160 MiB of total event
payload. Checkpoint up to 256 KiB. Two terminating events and 64 MiB are
reserved for checkpoint/reassign, one event and 32 MiB for submit. The
limit must not deny the coordinator the ability to finish/revoke an
assignment. History is not truncated. For `tool_begin`, three following
events and 96 MiB are reserved: finish, submit, decision.
`tool_finish/tool_abandon` leave room for submit and decision. Continuing a
finished task when the limit is exhausted is a new, explicitly created
task, not automatic deletion of old events. These are runtime limits, not
limits of the language or of the size of the whole BIM project.

Reading a specific task checks its whole chain and its actual tail, not
just the head pointer. A lost owner with events remaining is corruption,
not `not_found`. Pages of `list_tasks` are separate read snapshots, with no
promise of a single atomic picture when pages are combined. A decision
currently performs a full history audit and authored merge under a write
lock: expensive on a large history, not proof of constant latency or of
distributed scaling.

This layer does not serialize the Python stack, does not provide
continuation of an unfinished kernel call, and spends no LLM tokens. The
[recipe adapter](TASK_RECIPE_RUNNER_RU.md) now explicitly executes one
sandbox step and saves the result; an unknown retry does not call Python
again. A full runner, composition/envelope P05, LLM budgets, a user
task/approval UI, and live Revit remain future obligations.

## Checked strip

September 6, 2026: MAIN **387 passed /83.23s** in the related
Store/merge/assets/native-ledger/status regressions; the final new
task/schema/CLI/adversarial strip **69 passed /32.44s**. They overlap; the
results cannot be added together. Actual parallel worker processes, the
new coordinator, competition over one task version, process death
before/after commit, a lost ACK, a no-op, conflicts, corrupted history, and
terminal capacity were checked. A real OCCT asset is saved with the
proposal and read back after a restart with no OCP import. Neither an LLM
nor Revit was run in this acceptance; architectural completeness/
engineering fitness are not claimed.
