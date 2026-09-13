# Status of a saved project

```sh
python -m kir project status project.sqlite
python -m kir project status project.sqlite --limit 20 --after-stream <SHA256>
```

Python API: `ProjectStore.status(limit=20, after_stream=None)`. Status opens
one read-only SQLite transaction with a pinned store/project identity — even
if the source handle is writable. It does not run hot-journal recovery, the
compiler, the recipe, OCCT, discovery, Revit, or a write. A corrupted
database may need a separate, deliberate writable recovery; status does not
do that.

`kir-project-status/1` distinguishes:

- **authoring**: the saved head, the number of revisions, instances/outputs,
  and a preview intent of up to 1000 characters with an explicit
  `intent_truncated`;
- **pending**: a saved input is awaiting resolution; this is not proof of
  submission or execution. The archive/operation and the base/proposed
  revisions are visible;
- **checkpoint_recorded**: a historical acceptance of selected scope fields;
- **not_started_only**: only confirmed, not-yet-started attempts have
  reached the accepted checkpoint. The authoring head does not thereby
  become a native revision;
- **unavailable**: the scope cannot be read; other available rows are not
  hidden.

`planning_base_revision` and `accepted_scope_revision` differ in meaning. The
first can be the source R0 with no accepted checkpoint; the second is then
`null`. `authoring_head_matches_planning_base` is a comparison of
identifiers, not a BIM verdict. `live_model_observed=false` and
`whole_project_acceptance=not_established` are preserved under any local
checkpoints. Geometry and engineering do not get a green status from
matching revisions.

For Store/1–2 a native ledger is not supported: this is not a claim that
"the project was never published." For /3–4 an empty directory only means
there is no scope recorded here. The metadata check for orphaned
archives/settlements/resolutions/UID owners does not let a lost stream row
hide a pending item as a healthy empty directory.

## Incompleteness and errors

Page size 1–100. `catalog_complete` means a complete enumeration only for the
first request, with no continuation and no lost owners. This is separate
from `returned_scopes_readable`: a listed scope can be corrupted.
`has_more`/`next_cursor` let you keep reading, but each page is a new
snapshot. They cannot be merged into a supposedly single atomic picture.

On a corrupted scope or orphan metadata, the CLI returns JSON with an
explicit error and exit 2; it does not replace this with a healthy empty
response. A missing/unreadable database is not created automatically.
Diagnostics contain no raw source, receipts, or tokens.

The response size is limited, not the whole cost of reading: metadata
integrity scans depend on the ledger size, and the chosen checkpoint checks
its own saved evidence. This is not a benchmark of constant latency over
unbounded history. A full `history()` audit remains a separate operation.

## The display file and its Store status

```python
from kir.project_store import ProjectStore
from kir.viewer.standalone import load_display_artifact, _project_status

status = _project_status(load_display_artifact(open("display.json", "rb").read()),
                         ProjectStore.open("project.sqlite"))
```

The join keeps the original scene bytes. One mutable status snapshot is tied to the
displayed, immutable authoring revision from the same pinned Store. The
project, schema/IR/parent, the order and owners of outputs, module pins, and
body references are checked. This is a check of the declared source, not
proof that the mesh matches the body.

The panel separately shows the displayed revision, the authoring head,
historical scoped checkpoints, and pending items. Other revisions of the
same project are not hidden. References to outputs select only elements of
the current artifact; missing outputs are marked and cannot be selected. On
a read failure or a source mismatch, the previous status is cleared; the 3D
view stays unchanged. Without `--store`, the viewer explicitly reports that
no storage is connected.

This is a manual refresh of the first page of up to 20 scopes, with no
merging of pages, no live Revit, no publication, and no change to
authoring. The status API and the connected storage are available only on
the allowlisted loopback GET route.

Acceptance on September 6, 2026: the related Python strip **74 passed /
12.47s**. Actual Chromium + HTTP + SQLite: **1 passed / 7.3s**. R1 is shown
while the head is R2 and pending is R2; after a commit of R3 by another
process, only the status is refreshed, the scene revision/records and the
SHA of the source artifact do not change. An HTTP 503 clears the status
without losing the 3D view. The native evidence in the fixture is synthetic,
not live Revit. The first sandbox run blocked sockets/Chromium; the
named, successful checks were run with a separate local-run permission,
with no change to environment settings. Related Node codec/Three.js
regressions: **9 passed / 5.33s**; the initial sandbox `spawnSync EPERM`
failures were checked in a separate run with permission granted, and are not
counted as geometry errors or as passing tests.
All five previous inspector browser scenarios also passed (**5 / 50.2s**):
the stylobate, the developed section, the composite and saved residential
complex, four codec kinds, and a literal HTML label. WebGL pixels,
vertices, materials, and raycasting were checked; this is a display
regression, not acceptance of BIM in Revit. The new artifacts of this strip
take up about 8.3 MiB in `.work/u-status-mgk3si`.
