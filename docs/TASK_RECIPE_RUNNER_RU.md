# Executable recipe step of a saved task

`evaluate_task_recipe` connects the existing sandbox, ProjectRevision, and the task
journal. Python is genuinely executed in a separate process; the full IR and
the receipt are saved. A compatible result can be submitted as a ChangeProposal
and accepted by a different process without recomputation. This is one tool adapter,
not a ready-made LLM scheduler and not a BIM publication.

## Path

1. The coordinator issues a grant for the instance and, if needed, the recipe module/
   module order. `author.python` is explicitly allowed in `tools`; an integer
   `max_tool_calls` is mandatory. The actor string is still not authentication.
2. `tool_begin` atomically saves the source, parameters, output addresses, and all fields
   of SandboxPolicy. One call is spent at this point. Recording the reservation
   does not mean Python has already started.
3. Outside the SQLite transaction, the runner calls the existing `execute_author_script`.
   The recipe profile uses `kir.recipe_language`: this is the earlier course language
   plus a clean `project_output_id`, with no extension of the import/builtin allowlist.
4. The binder saves the full `SandboxResult.to_program()` and a detached receipt.
   A successful projection produces a sealed ModuleDefinition/RecipePin, an instance snapshot,
   and a ChangeProposal. It does not itself commit the authored head.
5. `tool_finish` saves the output. `submit_evaluated_recipe` picks the exact
   saved proposal and links it to the original tool request. Then the existing
   `decide_task` checks both versions and atomically accepts/rejects the change.

The tool must finish first, then checkpoint/submit or the next tool. This does
not hold a write lock during computation and lets different tasks
execute in parallel. The reservation count is checked before every call,
is not reset by reassignment, and is not refunded when Python fails.
LLM tokens are **not counted** by this adapter: it does not call the model.

## Recipe and addresses

The runner takes two scalar parameters, `project_id` and `instance_key`. They must be
declared through the existing `param`; explicitly passed values that do not match are
rejected. The remaining parameters must also be declared by the recipe.

```python
p = param("project_id", "missing")
i = param("instance_key", "missing")
h = param("height_mm", 3000.0)
program = {
    "ir_version": "<exact IR version of the source project>",
    "intent": "<exact intent of the source project>",
    "ops": [{"op": "create_level", "id": project_output_id(p, i, "level"),
             "elev_mm": h, "name": "Recipe level"}],
}
```

Replace the placeholders with the exact base values. `project_output_id` uses the
existing Project namespace; the number of outputs does not require the same number of
scalar parameters. Python loops can compute a set of named IDs.
The runner receives the desired `output_keys`, and the binder checks a full exact
match against the emitted IDs. The order is preserved from the program; refs are not rewritten
by string match. In NamedOutput, only its own top-level `id` is removed;
Project lowering returns the same canonical ID.

## CLI

```sh
python -m kir project task-evaluate project.sqlite facade-a recipe.py \
  --instance tower-a --module tower-a-recipe --output level \
  --parameters params.json --expected-task-version TASK_SHA \
  --generation 0 --actor facade-worker --request-id evaluate-1
python -m kir project task-submit-evaluation project.sqlite facade-a \
  --tool-request-id evaluate-1 --expected-task-version NEW_TASK_SHA \
  --generation 0 --actor facade-worker --request-id submit-1
```

`params.json` is a JSON object. `--output` can be repeated. After submit, the
usual `task-decide` applies with the exact task version/proposal ID and the authored head.
The CLI accepts no flags to disable network/chroot and does not trigger an automatic
submit/decide. The Python API allows only an explicitly chosen trusted-host profile;
it must be distinguished from an LLM's authority to choose tools.

## Failure and continuation

An exact repeat of the evaluate request **never calls Python again**. It returns
the saved output or `reserved` if there is no result yet. This is also how the window
"Python already computed a result, but the process died before tool_finish" behaves. Neither
the absence of a result nor an observation timeout proves that the computation never started.

`task-abandon-tool` closes the reservation as `abandoned_unresolved`, without claiming
the process was stopped. Reassign/revoke mark an unfinished old call as
`superseded_unresolved`; a late result is not recorded into the new generation.
The call's expenditure remains. A new run requires a separate explicit request ID and
available budget, not automatic redelivery.

After losing the ACK of a saved tool_finish, the result is read from the journal. If
the result cannot fit into the event budget, a named refusal is saved without a
successful proposal; the whole oversized result is never declared saved.

## What this projection does not yet express

One existing instance, a program exactly `{ir_version, intent, ops}` with the same
version/intent as the base. `defaults`, `phases`, `units`, `allow_destructive`,
and unknown fields **remain in the saved evaluation.program**, but the projection
into the current Project refuses. This is a limitation of the adapter, not a ban on KIR constructs.
Discarding the envelope for the binder's convenience is not allowed; extending the composition/
program-context remains further P05 work and is not considered done here.

A changed recipe pin does not re-bind other instances of a shared module. It needs a
separate/new module and a matching grant. When a grant is missing, the computed
program is saved, but no proposal is offered. Unconfirmed source/params/
environment/namespace/IDs also give a named refusal of the projection.

The sandbox call is observed by a trusted runner, but the publicly constructed
SandboxResult and its hashes are not cryptographic proof of the run.
The environment signature describes Python/observed libraries, **not** the full
dependency closure, the KIR source tree, or a reproducible container image.
Policy is saved entirely, separately; it is not mixed with the env digest.

A new run with changed parameters is checked; this is not a continuation of the Python stack.
`memory_mb` limits the additional addressable volume after trusted imports,
not the RSS of the whole process. CPU uses an integer OS soft limit and a hard grace;
the wall limit applies to each run separately. `replay_check=True` performs
two child runs, not one physical interpretation. The parent's setup and
output buffers did not get a shared RSS budget in this implementation.

An invalid network enum is now rejected before launch; mandatory chroot and
RLIMIT failures do not reach author code. The default profile requires
user/mount/network namespaces and filesystem isolation. This is checked on the current
Linux; Windows portability and hostile-code containment are not claimed at all.

The review found that a root-start process could fork even with
`RLIMIT_NPROC=0` already set. This limit has exceptions for real UID 0 and
privileges; the visible UID after unshare is not sufficient proof of a ban.
See [Linux getrlimit](https://www.man7.org/linux/man-pages/man2/getrlimit.2.html).
A child-only libseccomp filter for
`fork/vfork/clone/clone3` is now mandatory before author code, with NNP and synchronization of existing threads. The library
resolves syscall names for the native architecture; syscall numbers are not
hardcoded by hand. New author threads are also forbidden; trusted warm/import threads are created
before the filter. The parent process is not filtered by this feature.

`libseccomp.so.2` is an explicit system dependency of the Linux recipe worker. The library
was already installed on the box under test; no packages were installed. Absence of
the library, of NNP/TSYNC, or of filter-load gives `ProcessCreationGuardUnavailable`
before the author is launched. A successful setup is recorded in `isolation.process_creation`.
This is a narrow ban on process creation, not proof of full safety against
hostile code: the [kernel documentation](https://docs.kernel.org/userspace-api/seccomp_filter.html)
likewise separates syscall filtering from a full-fledged sandbox.

One more closed failure case: a checkpoint could pre-occupy the automatically
computed completion ID. Previously the recipe would run, and tool_finish would lose its
result on an ID conflict. Now occupancy of the completion ID is checked in the same
transaction before the call's reservation/charge; an existing exact replay is not blocked.

## Acceptance

September 6, 2026: MAIN final scoped regression -- **462 passed +15 subtests
/110.42s**. Real subprocess/SQLite checks covered recipe->proposal->restart->decision,
re-editing a parameter, preserving neighbors, no-reinvoke before/after the actual
computation on crash, a lost ACK, generation fencing, and a completion-ID collision.
The binder was checked on 70 outputs and on preserving the actual phases when the projection refuses.
The sandbox was checked with mandatory namespaces/chroot/RLIMIT/libseccomp; to
distinguish the external syscall filter from its own isolation, the final strip
was run with a separate authorization. The check is not a whole-suite, Windows,
Revit, or LLM-session check, and not proof of the model's engineering fitness.

## Recipe plan: continuation from a saved step (September 7, 2026)

`evaluate_task_recipe` can do EXACTLY ONE step. The registry called this "Partial:
persisted Python recipe step" (P05) -- "stop and continue" was claimed,
but no run ever actually continued: a crash mid-computation
left a reservation that nobody could carry through.

`recipe_plan()` and `evaluate_task_recipe_plan()` have been added.

- `recipe_plan(steps, *, seed, plan_id)` is an inert JSON: the step order and a
  `plan_digest` over ALL steps. A different seed/source/parameter is a DIFFERENT plan with
  different step addresses, not "the same plan, continued".
- `evaluate_task_recipe_plan(store, task_id, *, plan, actor, generation, policy,
  max_steps=None, task=None)` continues the plan from the first step that the
  task journal does NOT hold. The journal (`tool_begin`/`tool_finish`) owns the truth,
  not the process's memory.

Step address: `<plan_id>-s<index>-a<attempt>-<12 chars of plan_digest>`. The seed,
inputs, and dependency on the previous step live IN THE STEP ITSELF -- in the durable
`arguments["pins"]` of the reservation (`recipe_seed`, `plan_digest`, `step_index`,
`depends_on`). Redelivery is checked against these bytes: a different seed or
a different chain is a different input, and `_mutate` answers "request ID reused for
different input" rather than silently replacing what was already done.

**Pins are not part of the sandbox contract.** The recipe language refuses on an
UNDECLARED parameter (`KIR-B014`), so mixing the seed/chain into the inputs
would break EVERY existing recipe. Only the pin name that the step DECLARED in its
`parameters` reaches the script; the rest stay in
`arguments["pins"]` -- durable and checkable, but not visible to the author.

### Two signatures, and they mean different things

`evaluation_digest` and `proposal_id` carry the FULL sandbox receipt, and it contains
`duration_s` and `peak_rss_kb`: two independent EXECUTIONS of the same
source give different bytes. Declaring one signature "byte-identical" while silently
baking the duration into it would be an instrument lying, so there are two signatures:

| signature | what it's about | when it matches |
|---|---|---|
| `result_digest` | identity of the JOURNAL | for any number of processes reading the same recorded steps |
| `content_digest` | identity of the CONTENT (`program_sha256` of the steps) | for an interrupted run and an uninterrupted one, even across different processes and different times |

For the same reason, `depends_on` latches onto the CONTENT of the previous step, not
its `evaluation_digest`: otherwise the next step's input would depend on
how many milliseconds the previous one took, and no interrupted run would ever match an
uninterrupted one. The measurement showed exactly this.

Named stops: `plan_exceeds_task_journal` and
`plan_exceeds_tool_call_budget` (checked BEFORE the first step: the task journal
is limited to `MAX_EVENTS=1000`, and a step costs TWO events, so ~498 steps is the
ceiling, and truncating the plan partway would leave half the effect without a
name), `run_step_budget_exhausted` (the run budget, counting DELIVERIES, not
Python launches), `tool_call_budget_exhausted` (the same durable budget on
continuation), `step_taken_by_another_attempt` (while this process was computing,
the coordinator released the reservation or changed the owner -- the write is refused BY NAME, not
lost), `step_outcome_unresolved` (the process died mid-step),
`step_attempts_exhausted`. Delivery labels: `evaluated`, `already_delivered`
(the step is already in the journal), `already_delivered_on_replay` (an exact redelivery
of the same reservation -- the store answered `inserted=False`).

An unresolved reservation does NOT continue on its own: Python's outcome is unknown, and
calling it again is not allowed. The next attempt at the same step is taken only after an EXPLICIT
`abandon_task_tool`/`reassign_task` -- the pin
`test_pending_resume_after_hard_process_exit_never_invokes_again` has not been weakened.

### Reading numbers (same shift)

A recipe over a project of 2000 instances was paying for **5.0 full model parses and
7.2 full traversals PER ELEMENT**: `read_task`(x2), `store.get`, and two journal
writes were calling `_find_revision` on the SAME base revision without
a guarantee, and the write (`sweep_assets=True`) traversed the revision again, bypassing the
already-existing `_referenced_digests` memo.

| measurement (5 steps) | before | after |
|---|---|---|
| `ProjectRevision.loads` per element, N=250 | 5.0 | 0.0 |
| `ProjectRevision.loads` per element, N=2000 | 5.0 | 0.0 |
| `addressed_outputs` per element, N=2000 | 7.2 | 0.0 |
| seconds per element, N=250 | 0.248 | 0.096 |
| seconds per element, N=2000 | 1.508 | 0.098 |

The fix (`kir/project_store.py`) does not weaken the check and does not change the schema:
`_State` carries a handle guarantee, `_find_revision` returns the parsed snapshot
ONLY when the ENTIRE revision row matches (number, identity, project, parent,
bytes), and `_check_revision_assets` takes the set of references from
`_referenced_digests` -- the same memo that already guarded the hot read. Different
bytes give a different `revision_id`, a miss, and a full check.
