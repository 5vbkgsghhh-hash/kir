# Offline editing of a saved building: without KUKAI and without a running Revit

Here is one complete circuit: **open → read an element and its links → change a
door → change an opening (in a floor or in a wall) → look at the diff and the
constraints → save → close the process → continue with a second change → export
C#**.

None of this needs the KUKAI backend, a socket, or a live Revit: it reads a
decompile catalog (`capture`) and writes a NEW catalog next to it. The original
run is only ever read — writing into it is refused by name
(`target_inside_capture`).

Every command below is checked by the guard
`kir/decompile/tests/test_a_scenario_survives_a_new_process.py`: it runs exactly
this scenario with real processes.

## 0. Environment

```bash
export KIR=/root/kir-foundation                 # root of the KIR tree
export PY=/root/kir-foundation-venv/bin/python  # this tree's interpreter
export PYTHONPATH=$KIR
export W=/tmp/capture-demo                      # example working directory
mkdir -p $W
```

Check that the door is in place:

```bash
$PY -m kir.decompile.capture_api --help
```

The same thing is available through the package door — `$PY -m kir capture …`
(the same `capture_api` parsing: the same flags, the same output, the same exit
codes, refusal = 2), so any command below can also be typed that way.

## 1. A building to try it on

A real decompile lives in the corpus (for example
`/opt/kukai-rebuild1/backend/backend/data/decompile/bench_A`) — its directory
works as `--capture` unchanged. If there is no corpus on the machine, a
synthetic building is written with one command: one wall, two doors in it, a
floor slab with an opening.

```bash
$PY -m kir.decompile.capture_api demo --out $W/capture
```

The response names the addresses: `door=1002`, `second_door=1004`,
`floor=1003`, `wall=1001`.

With the `--wall-opening` flag, a fifth element is added — an OPENING IN THE
WALL (`wall_opening=1005`):

```bash
$PY -m kir.decompile.capture_api demo --out $W/capture --wall-opening
```

🔴 **Why a wall opening has to be looked at on a synthetic building, not on the
corpus.** Census 08.09.2026: wall openings account for 3 runs out of 93
(`mnvnk_k1_layers` 120, `k4_geom_wave2` 51, `bench_A` 12 — 183 elements), and
**not one of the 183 rises into an operation**. A scan of all 1508 corpus files:
occurrences of `opening_is_rect` and `opening_boundary_mm` — zero. The reason is
the date: the opening-boundary reader (`extract._opening_boundary_reader_cs`)
was set up on 04.09.2026, and the corpus was captured in August. On a real run, a
wall opening therefore yields a NAMED REFUSAL, `wall_opening_not_captured`,
which names both what is missing (`Opening.BoundaryRect`) and what stands in
for it (a bounding box), and how it is fixed (recapture the snapshot, not edit
the contract).

## 2. Open it, and see what the capture is bound to

```bash
$PY -m kir.decompile.capture_api open --capture $W/capture
```

This prints identity (`lineage`), integrity (`integrity`), which side indexes
were read, and `source_binding` — FIVE fields that bind the edit to THIS
building (`lineage`, `source_sha256`, `source_version`, `profiles`,
`capture_revision`). A patch taken from a different capture refuses by name,
`patch_binds_to_another_capture`, rather than landing on a matching address by
coincidence.

`capture_revision` and `revision_binding` are printed alongside it.

**`capture_revision` is the DOCUMENT's revision that the capture was taken
from.** It is read from `revision.proof.json`, which the decompile itself lays
down (80 of the corpus's 81 runs have it — only `demo-v3` does not), and which
the product uses to judge the live model. The binding's first four fields answer
the question "will the SAME THING rise" — they contain exactly what the
elevator reads. The elevator never reads the revision at all, and before
07.09.2026, substituting `revision.proof.json` (measured: `bench_A`'s revision
was replaced with `k4_geom_wave2`'s, with `L0.jsonl` and every side index
byte-identical) went through SILENTLY: the edit replayed, and `integrity` kept
answering `pinned:source_version`. This is now a named refusal,
`capture_revision_moved`.

`capture_revision` has three states, and they are DISTINGUISHABLE: the revision
itself, `absent:no_revision_proof` (the file is missing — the run predates the
check), and `unreadable:…` (the file exists and cannot be read). Treating
"absent" the same as "unreadable" would mean claiming there was no data where
in fact there is, and it is corrupted.

`revision_binding` says what the EDITS are bound to: `none` — there are none;
`pinned` — every journal line names the revision it relied on; `unpinned` — the
journal has lines from an OLD record, made before 07.09.2026, where the
revision was not named. Such a record is read with its own, WEAKER guarantee:
refusing it would mean declaring every capture saved before that date
unreadable, and calling it pinned would mean reporting a guard that is not
actually in it.

## 3. Read an element: values, host, dependencies, field states

```bash
$PY -m kir.decompile.capture_api read --capture $W/capture --element 1002
```

In the response:

* `supported` — the L0 fields that MADE IT into the IR (state `represented`);
* `op_params` — the parameters of the operation the element became
  (`create_door`);
* `host` — the host (`hosted_by`, proved by `L0.host_id`);
* `depends_on` / `referenced_by` — what the element refers to, and who refers
  to it (`L1.params.host.ref` and `L0.host_id`);
* `fields` — EVERY non-empty L0 field with its own state per the
  `kir.decompile.field_ledger` register: `represented | approximate |
  source_data | unknown`, with a reason (`why`) and a carrier (`carrier`);
* `editable_fields` — what this contract can change on this category.

Storing a value in an opaque block (`source_data`) is NOT proof that it gets
reconstructed in the BIM; that is stated outright as a state, not hidden.

## 3a. Ledger of the WHOLE building: four states as numbers

`read` answers about ONE element. A number for the whole building is given by
`ledger`:

```bash
$PY -m kir.decompile.capture_api ledger --capture $W/capture --limit 20
```

In the response, `by_state` gives the four states as SUMS, `by_why` gives the
kinds of reasons, `rows` gives the losses as ADDRESSES (`element_id`,
`unique_id`, field, state, carrier), and `rows_total`/`truncated` say how many
rows there are in total and how many were not printed (`--limit -1` prints all
of them). The sums must add up:
`represented + approximate + source_data + unknown = nonempty`, and
`represented = nonempty − lost`.

🔴 THE NUMBER IS A PROPERTY OF THE READ MODE, and the response names this with
the `profiles` field. Measured on `bench_A` on 07.09.2026 (4,223 elements,
58,451 non-empty fields):

| `--profiles` | represented | approximate | source_data | unknown |
|---|---|---|---|---|
| `none` | 26,330 | 1,695 | 2,940 | 27,486 |
| `editable` (default) | **26,282** | **1,647** | **2,940** | **27,582** |
| `all` | 26,272 | 1,638 | 2,940 | 27,601 |

The more sketch index is fed to the elevator, the FEWER represented fields
there are: the index makes nodes richer, and some fields lose their named
carrier. So a ledger without a named read mode is incomplete.

## 4. Look at the consequences without writing anything

```bash
$PY -m kir.decompile.capture_api propose --capture $W/capture \
  --edit '{"element_id":"1002","change":{"offset_mm":4000.0}}' \
  --edit '{"element_id":"1003","change":{"opening_index":0,"opening_contour_mm":[[2500,2500],[5500,2500],[5500,5500],[2500,5500]]}}'
```

This prints `admissible`, the ACTUAL `diff` by the node's leaves, `notes`, and
`open_questions` (what this edit does NOT resolve). `propose` writes neither to
memory nor to disk — the guard checks the sha256 of every file in the catalog
before and after.

An invalid edit refuses BY NAME and the exit code becomes `2`:

```bash
$PY -m kir.decompile.capture_api propose --capture $W/capture \
  --element 1002 --patch '{"offset_mm": 1e9}'   # offset_out_of_host
```

## 5. Apply the edits and save into a NEW catalog

```bash
$PY -m kir.decompile.capture_api apply --capture $W/capture \
  --edit '{"element_id":"1002","change":{"offset_mm":4000.0},"before":{"offset_mm":3000.0}}' \
  --edit '{"element_id":"1003","change":{"opening_index":0,"opening_contour_mm":[[2500,2500],[5500,2500],[5500,5500],[2500,5500]]}}' \
  --out $W/step1
```

`before` is the expected PRIOR value. If it has drifted, the edit refuses with
`edit_before_value_mismatch`, and NOTHING is saved: the target stays
non-existent, and the exit code is `2`.

`--out` must be a new catalog OUTSIDE any run. There are TWO names for this
refusal, and they are about different things: saving inside the SAME run that
is open is `target_inside_source`; inside SOMEONE ELSE's run is
`target_inside_capture`. A non-empty target is `target_not_empty`, a target
without write permission is `target_not_writable`.

## 6. Close the process and continue with a second change

Between steps, nothing remains except the `$W/step1` catalog.

```bash
$PY -m kir.decompile.capture_api apply --capture $W/step1 \
  --element 1004 --patch '{"offset_mm": 8000.0}' --out $W/step2
```

The response has `edits: 3` — the two earlier edits are in place, and a third
has been added. To check it by eye:

```bash
$PY -m kir.decompile.capture_api read --capture $W/step2 --element 1002 | grep -A2 offset_mm
```

## 7. Export C#

```bash
$PY -m kir.decompile.capture_api export --capture $W/step2 --csharp-dir $W/cs
ls $W/cs
```

This prints `programs`, `compiled`, and `refusals`. **`compiled` being less
than `programs` is not a launch error, it is a named compiler refusal**:
`bench_A` has two programs (ducts and pipes) that require a live-model
snapshot to resolve names, and they honestly refuse with `KIR-G103`. An empty
`refusals` list means "there are no refusals," not "we did not look."

## Exit codes

| code | meaning |
|---|---|
| 0 | done |
| 2 | NAMED REFUSAL: `refusal.code` in the response (`offset_out_of_host`, `edit_before_value_mismatch`, `patch_binds_to_another_capture`, `target_not_empty`, `wall_opening_not_captured`, `wall_opening_degenerate`, `wall_opening_variety_not_editable`, …) |
| 1 | the tool broke — that is a crash, not a refusal |

## What this contract can change

| category | edit fields | how the language states it |
|---|---|---|
| `OST_Doors` | `offset_mm`, `sill_mm`, `symbol` | `create_door` |
| `OST_Floors`, `OST_Ceilings` | `opening_index`, `opening_contour_mm` | a ring in the inner loop of the HOST's OWN sketch (`create_floor`/`create_ceiling`) |
| `OST_SWallRectOpening` | `opening_p0_mm`, `opening_p1_mm` | `create_opening(variety="wall_rect")` — `NewOpening(Wall, XYZ, XYZ)` |

A wall opening is a **separate element**, not "an opening of a different
category": for a floor opening you edit the FLOOR and its ring, for a wall
opening you edit the OPENING ITSELF and its two opposite corners. The two
corners are the opening's entire size and entire position: `NewOpening(Wall,
XYZ, XYZ)` has no other shape inputs.

What a wall opening deliberately does NOT have is a check that it stays
"inside the wall." The forward-pass emitter refused to pin a shift along the
wall, based on measurement: Revit projects the given points onto the wall's
location plane, and the absolute X/Y legitimately drift by half its thickness.
A containment check of its own would refuse exactly the edits the forward pass
considers correct. A C# witness judges the opening — by the top and bottom
elevations of the strip and its width along the wall, with the op's `bbox_mm`
tolerance.

Example of editing size and position:

```bash
$PY -m kir.decompile.capture_api apply --capture $W/capture --element 1005 \
    --patch '{"opening_p0_mm": [6000, 0, 800], "opening_p1_mm": [7500, 0, 2200]}'
```

## What this circuit does not do

* it never writes to the source run — never, under any permissions;
* it makes no promise of lossless reconstruction: whatever the operation
  language cannot express is named as a field state (`unknown`/`source_data`)
  with an address, not passed over in silence;
* it sets up no second agent runtime and keeps no DB of its own: the edit runs
  through the same `capture_edit.edit_element`/`save`, and the adaptation to
  `ProjectRevision`/`ChangeProposal` is described by the existing contracts in
  the header of `kir/decompile/capture_api.py`.
