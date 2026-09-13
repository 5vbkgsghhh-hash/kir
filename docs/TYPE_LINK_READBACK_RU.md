# Readback of consumer → type links

Status: the Python/CLI path and batching/orchestration have passed independent offline acceptance.
The pure report was accepted separately. This is not a general BIM acceptance and not a check
of the actual model in Windows/Revit: the current integration tests use
real compiler/parser/SQLite and synthetic native responses.

## User path

```text
python -m kir project create-readback-types PROJECT.sqlite --archive ARCHIVE_SHA256 \
  --directory DISCOVERY --journal-id JOURNAL --instance-id RUNTIME \
  --revit-version 2023 --session-id SESSION --client PIPECLIENT \
  --document-key DOCUMENT --bind-view yes --bind-selection yes
```

The exact runtime and the document of the original publication are selected. Python API:
`readback_stored_create_types` in `kir/stored_type_readback.py`.

1. The original Archive/2 and its stored authored revision are read from Store/6-7.
2. The original native receipt is requested; the fact of it is saved in SQLite.
3. UIDs of the selected publication are taken from the qualified CREATE/reuse identities.
4. The context is read once. All read-only queries use this same full
   precondition; large scopes are split by128UID per request.
5. The addressed report compares the observed assignment with the type output of the authoring program.

CREATE is not compiled and not resubmitted. The authoring head, reservations,
and schema are not changed. The path **is not read-only for SQLite**: a
receipt is saved; the native runtime may also log read queries.

## What a match means

If seed type100 was copied into type800, the wall must reference800, not100.
The expected UID is taken from the qualified created or reused type output,
linked via the authored `type.by:ref`. A wall/floor with a different type gets
`mismatch`. Missing/unavailable/conflicting observations do not reduce the denominator.
So far, direct wall/floor/contour-floor and wall/floor type factories are supported;
an unsupported selector/profile gets a named limitation.

Pure API: `assess_create_type_discrepancies(project, record, bound_receipt, observation)`.
Results: `matched`, `mismatch`, `unavailable`, `conflict`. A positive CLI
exit code means a report was obtained, **including a report with mismatch**, not that the BIM
matches the project. The counts and addressed outputs should be read.

The comparison relates to the observed revision, not to the model's state now.
Re-rendering the same observation is allowed and deterministic.
`current_model_state=not_established`; the observation timestamp is not invented.
Same UID / changed VersionGuid does not prove that layers or the type definition
are preserved. Type definition, layers, geometry, and engineering are `not_evaluated` here.
Reuse is a valid reference, but not exclusive ownership or update permission.

The source of comparison is the **archived publication**, not a newer authored head.
The report separately shows `authored_head_seen_before_lookup` and whether it matches
the source revision. This is not a co-snapshot and not a promise that the head stays current after reading.

## Batching and refusals

`ElementObservationSet` combines only real parsed observations with the
same target and a full precondition. Exact non-overlapping UID
coverage and consistent numeric ID/UID/VersionGuid are required, including shared types.
Separate `query_inputs` are kept; a single fictitious operation ID/source hash
is not created. `require_identity` uses an index rather than re-parsing the entire
JSON for every element.

The16MiB aggregate budget limits a specific observation, not the size of the building.
An error, drift, an incomplete response, or exceeding the budget do not turn into a full
partial snapshot; the original context is not refreshed and the request is not retried
automatically. The receipt facts remain saved. If there is no qualified UID,
a native query is not invented: `type_discrepancy=null` with an explicit reason.
`timeout_ms` limits a single exchange, not the time of the whole workflow.

The query scope is currently conservative: all qualified native outputs of the selected
publication, including non-typeable elements. This is not a doc-wide scan and not a search
by names/assumed numeric IDs. Reattaching to another runtime/model requires
separate proof and is not performed by this API.

## Checks and next boundaries

Pure report: independent55passed, including3RED→GREEN for an erroneous matched
on an unverified type-state and unconfirmed currentness.
Batched observation owner:155passed with129/257UID and a stop after the second
failed chunk. MAIN102passed combines readback (2/130walls), the pure report,
and batching. An additional independent strip of66passed checks full/selected
source, the allowed SQLite write-set, the second chunk failure, and CLI answer vs acceptance.
After integration, MAIN62passed covers the earlier publication/cancel/resolve/CLI and the new
readback. The strips overlap; the numbers do not add up.

Not checked by this slice: live Revit, the layers/materials/geometry of the type themselves,
overall Building Graph reconciliation, UI viewer integration, and multi-process
reattach. Obtaining the real catalog of seed types and binding the selection to the original
catalog context remain a separate next step; ID100/400 from fixtures
must not be carried over into a user document as supposedly found values.
