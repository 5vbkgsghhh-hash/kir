# Execution, result, and acceptance

Foundation branch, September 5, 2026. This is a description of checked
contracts, not permission to write into an actual document.

## Authoring input: D4

`SandboxResult.to_program()` returns a detached full IR: `ops`, version,
intent, defaults, organizational units, and execution phases. Phases are not
mixed together: the one-step compiler still requires an explicit
`split_phases`. Unknown JSON fields reach a compiler refusal, rather than
disappearing during harvest.

MCP `kir_author` returns `program` and a separate `authorship`: the exact
source, parameters, and the sandbox's actual digests/environment/lineage/
losses. This information is not added to the compiler IR. Serving uses the
same `to_program()`. The carrier remains mutable for the existing
replay/stamping, but a program changed after the digest was computed is not
retrieved under the old consistency signature. This is not a cryptographic
signature and not a full immutable/persisted AuthorResult.

## Write response: D1

`kir.bridge_result` owns the clean check of the expected results of an exact
`PlannedProgram`, explicit transaction status, and witness evidence. Serving
re-exports the historical names of these helpers; MCP uses the shared
`assess_write_result()` and the existing `ProgramOutcome`.

| Evidence obtained | execution / witness | Retry |
| --- | --- | --- |
| Emptiness, unknown state, contradictory statuses, timeout | unconfirmed / incomplete | Check the model first; do not retry automatically |
| An exact post-Commit `ok=true`, but the typed identity of at least one result is missing | committed / incomplete | Retrying this write is forbidden; a new plan is needed |
| Commit with named postcondition violations | committed / violated | Fix with a separate plan |
| An explicit, non-contradictory `RolledBack`, with no conflicting post-Commit marker | rolled_back / violated or incomplete | The fact of the rollback itself allows a retry; the cause of the refusal still needs fixing |
| A full typed readback with no known violations | committed / satisfied | Do not repeat a write that was already applied |

In every case, the independent `acceptance` stays `not_run`. A positive MCP
response contains `success_scope="execution_contract"` and
`intent_verified=false`. This is not a claim that the geometry, the
engineering meaning, or the whole design intent has been checked. The
source receipt is preserved in full.

A direct legacy KIR result and up to two `result` wrappers are supported. An
ambiguous mixing of an operation row and a transport control is rejected.
Postcondition violations are collected from all allowed wrappers. Malformed
evidence does not become satisfied. A missing exact plan does not turn into
an empty list of obligations.

A raw Connector receipt is not counted as a KIR result:
`invocation_completed` only means the call returned. A separate adapter is
needed to tie the response to the operation/source/context and to check the
completeness of `result_json`. This path, the MCP effect boundary, and
durable recovery are still in progress: D2/R01–R04 are not closed.

The flat result has one more fix: the operation IDs `ok`,
`postcondition_violations`, `revit_warnings`, `revit_errors_resolved`,
`post`, `residual_effect` get a named compiler refusal before lowering.
Otherwise the program's metadata could overwrite the result row. The schema
takes the same list from the registry. An old typed plan with such an ID
also does not compile; the archive is not renamed automatically. Other
names, including `result`, are not forbidden merely for the transport
parser's convenience.

## Census coverage: D6

`check_acceptance()` keeps `upper_bound_groups`: the merged category groups
for which an upper bound was included. The `upper_bound_coverage` field
distinguishes `none`, `partial`, `full` relative to the checked category
groups. The compatible wire key `upper_bounds_checked` is true only for
nonempty full coverage.

`AT_LEAST` remains a lower bound: a million hosted railings by itself does
not violate this contract, but no longer gets an invented "upper bound
checked" mark. An exact overshoot still refuses. Mixed, derived, unknown,
and overlapping categories are distinguished by the actual scope. This is
not coverage of every level, of geometry, or of engineering requirements.

The internal Python `Verdict` constructor now accepts groups instead of
`upper_bounds_checked=`; the old keyword is incompatible in this form. In
the available tree, the single runtime constructor has been updated.
Historical journal payloads remain archived bytes: the new fields do not
recompute their hashes and do not retroactively fix old false marks. The
external frontend has not been checked.

## Checks and boundaries

- D4: 100 passed / 1 skipped; an independent, overlapping run of 65 passed /
  1 skipped / 2 subtests. An actual MCP stdio wire is absent from the check:
  the optional SDK is not installed. The subprocess sandbox and public
  dispatch are checked. The old fork-limit test produces KIR-B012 even on
  the unchanged base; this is not a D4 regression, but OS isolation is not
  proven by it.
- The shared D1/D4/D6 strip and neighboring runtime/acceptance contracts:
  318 passed / 3 skipped / 91 subtests, 18 files, 23.02 s. The skips relate
  to existing host-gate scenarios, not to live Revit.
- The compiler/schema/SDK strip: 436 passed / 10 subtests, 7 files,
  273.09 s. The archival typed-plan negative was added after it and checked
  in the shared strip above. The runs overlap; their numbers cannot be
  added together.

These are selected offline checks, not the whole repository suite and not
Revit execution. The next native requirements are in
[CONNECTOR_RUNTIME_GAPS_RU.md](CONNECTOR_RUNTIME_GAPS_RU.md).
