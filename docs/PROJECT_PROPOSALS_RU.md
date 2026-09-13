# Agent proposals and authored merge

`kir.project_merge` merges **authored ProjectRevision snapshots**, not
observed Revit elements. The first scope is a whole module or instance;
within an instance, the parameters, outputs, their order, and the recipe
pin are indivisible. That way two edits do not create a combination of
parameters and computed result that no agent ever supplied. This is not
yet an executable native update plan.

## Owners of the truth

| Contract | Owner |
| --- | --- |
| The exact authored data, versions, addresses, and pins | `ProjectRevision` |
| The proposal's input, reason, and declared write scope | `ChangeProposal` |
| The write scope authorized for the agent | The accepting caller, a separate `authorized_scope` |
| Explicit ref dependencies and the conservative affected scope | `project_diff` and the registry |
| Linear history, lineage/assets checking, and atomic CAS | `ProjectStore` |
| Geometry, norms, protected engineering constraints, native bindings | Not checked by this merge |

Scope is not agent authentication: the caller must obtain the grant from a
trusted task assignment, not simply copy `proposal.scope` from someone
else's file. An independent change to the serialized scope does not extend
the caller's grant. The loader checks hashes, but they do not prove
authorship or that the recipe ran. The recipe's source code and body
assets are not executed during a merge.

## Usage

```python
from kir.project_merge import ChangeProposal, ProposalScope, accept_proposal

# These values are set by the task coordinator, not by JSON returned by the agent.
grant = ProposalScope(instances=("tower-b",))
proposal = ChangeProposal(base, candidate, grant, "facade-agent",
                          "Уточнить фасад tower-b, сохранив остальные секции")

# proposal.dumps()/loads() is a portable inert artifact with an exact base.
result = accept_proposal(store, proposal,
                         expected_revision=coordinator_observed_head,
                         authorized_scope=grant)
if not result.merge.clean:
    conflicts = result.merge.to_dict()["conflicts"]
    # Replan on a fresh base; not "force ours/theirs".
```

`accept_proposal` first checks the full saved history and the exact common
base. The ancestry check is O(history), including an inert check of the
assets, not a constant-time hot path. Between the read and the write,
another process can manage to change the head: a new divergent append
refuses on the final SQLite CAS. A matching redelivery of an already
accepted snapshot does not create a new revision and does not rewind the
head; this is **not** execution idempotency in Revit. If a competitor has
already managed to save the same snapshot and advance the history further,
an exact redelivery returns `inserted=False` and the actually observed
`commit.head_revision`. It can differ from `merge.revision.revision_id`:
what is confirmed is a previously accepted result, not a promise that it
is still the head.

A clean `merge_proposal` does not read the storage; its report directly
marks the common ancestor as `caller_asserted`. Only `accept_proposal`
changes this status to `verified_stored_history`. On a conflict there is
no result revision: a partially merged variant is not returned disguised
as fit for writing.

## CLI

The CLI uses the same parser/merge/store with no new data owner:

```sh
kir project proposal-inspect proposal.json
kir project proposal-accept project.sqlite proposal.json --expected REVISION --allow-instance tower-a
```

The grant is set by the accepting side with the `--allow-instance`,
`--allow-module`, and `--allow-field` flags (repeatable). With no allow
flags, the grant is empty, not full. These permissions cannot be copied
from an untrusted proposal and counted as authentication. `--asset FILE`
explicitly passes a GeometryBundle for atomic store acceptance; the native
kernel is not run on load. The proposal can come through stdin as `-`;
assets are separate files.

On an authoring conflict, exit code 1 and JSON with `merge.conflicts`,
`commit=null`. Malformed/read/store errors do not become a success. A
success returns the IDs and `native_published=false`,
`proposal_log_persisted=false`: what is saved in SQLite is the accepted
snapshot, not an inbox/decision log. The original proposal/report is still
kept by the caller. The CLI performs no implicit create, schema upgrade, or
Revit dispatch.

## What conflicts

- Different edits of the same instance/module, including delete/modify and
  add/add.
- An edit to the project intent/metadata with no separate permission for
  that field.
- Conflicting orders of modules/instances. Even dissimilar new instances
  are not appended in an arbitrary alphabetical order: the order can set
  the sequence of effects. Adding/removing requires a grant on order.
- An overlap of the explicit dependent scope under diverging edits. For
  example, a changed level and a parallel edit of a dependent wall; or two
  edits affecting a shared downstream output.
  The closure is computed over the union of the explicit edges of both
  branches: a new wall from the proposal must also conflict with a level
  that was removed/moved only in the current branch. Separate analysis of
  each delta is not enough for this.
- An incomplete dependency analysis under an actual divergent merge: an
  unknown operation, an unanalyzed nested scope, or a selector requiring
  grounding. This is a named conflict, not a declaration that the
  operation is forbidden in the language. A one-sided draft can be saved
  with no claim of KIR validity.
- A schema/IR mismatch. Migration is performed separately, not through a
  merge.

Saving an authored result that is already identically present is a no-op,
not a re-check of its engineering meaning. Conservative analysis can ask
for a replan even under changes that are compatible in intent; in
particular, the overlapping part of two broader edits can cross the
affected scope.

## The durable task path and neighboring mechanisms

Store/5 now provides a separate [task lifecycle](PROJECT_TASKS_RU.md) on
top of the same ChangeProposal/ProposalScope/merge. It saves an
independent coordinator grant, checkpoints, received proposals, and an
atomic decision + authored head. `task-submit/task-decide` do not replace
the old `proposal-accept`: the latter keeps its previous authoring-only
contract and still does not write a task log.

`decompile.merge3` is preserved: it compares multisets of canonical
operations of observed buildings and, when a tree is present, checks
source identity. `merge_guard` decides whether a delta rebuild can
continue. `BuildingJournal` protects the recorded keep/absent/hole
decisions in its own addressing. The source authored instances, with
recipe pins and order, cannot be reconstructed from these carriers, so the
new layer does not replace them and does not pass off their guarantees as
its own.

The old `accept_proposal` path saves the accepted revision, but **does
not** save the branch/candidate and the merge reason as a separate,
automatically durable record. The proposal and the report are
serializable; in this old path, saving them is the caller's
responsibility. A durable proposal/decision log and assignments with
generation fencing are implemented through the Store/5 task path.
Protected engineering constraints, a full UI workflow, and launching and
continuing a long-running harness remain the next part of P04/A01. We do
not hide this in free-form project metadata, and we do not call P04
entirely finished.

The first slice's tests check the actual planner for positive examples,
whole-snapshot conflict, dependency overlap, sealed recipe pins, inert /2
body references, redelivery, a stale base, and two actual SQLite
processes. Semantic/geometric verification of the whole result, and Revit,
are separate boundaries after the authored merge, not the value of
`clean`.

An independent adversary reproduced a bug in the original per-branch
closure: both inputs were planned separately, but the merge produced a
dangling reference or changed the base level of a newly added wall. Two
public regressions first failed, then passed with a union closure and an
additional check of the completeness of the explicit-reference analysis of
the resulting divergent revision.
