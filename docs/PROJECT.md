# Persistent authoring project: first foundation

This implementation adds a saved authoring model **above** the existing KIR
operation compiler. It does not turn the observed Building Graph into a second
authoring authority, and it does not replace the compiler or the Python SDK.

```text
Python generator (explicitly run by its caller)
    → module-instance snapshots with named outputs
    → immutable ProjectRevision ↔ canonical JSON
    → existing KIR envelope → semantic plan → backend compiler
```

## Authority and guarantees

| Value | Owns | Does not establish |
| --- | --- | --- |
| `ModuleDefinition` | Explicit or sealed-evaluation ownership; optional declared recipe | A callable interpreter or a reusable parametric body |
| `RecipePin` | Inert source text, source hash, declared dependency/environment hashes | That this code ran, or that the environment is fully reproducible |
| `ModuleInstance` | One complete evaluated/authored snapshot, parameters, ordered named outputs, exact definition pin | Automatic regeneration when parameters change |
| `ProjectRevision` | Modules, instances, intent, metadata, IR version, parent hash, content hash | A history database, concurrent file CAS, native element bindings |
| `ProjectStore` | One local SQLite project history and transactional expected-head acceptance | Distributed storage, automatic merge, native publication |
| `ProjectDiff` | Addressed payload differences and conservative explicit-reference impact | An executable Revit patch or proof of unchanged geometry |
| Existing semantic plan | Registry types, references, operation order and compiler rules | Document grounding, Revit execution or design adequacy |

Output identity is a 64-character SHA-256 of the project, instance and output
keys, namespaced for this schema. It is independent of position and operation
content. Renaming a key changes identity. These are **top-level operation IDs**:
a macro or array can produce many BIM elements with separate identity rules.
References are explicit SDK refs to these IDs; lowering does not guess their
meaning, rewrite dictionaries or reorder effects.

The snapshot is deeply immutable, and exported dictionaries are detached copies.
Loading checks the schema, exact fields, content hash and module-definition pins;
duplicate JSON keys and non-finite numbers are refused. The recorded IR version
survives loading instead of changing to the installed compiler's current version.
Hashes detect inconsistency, not malicious authorship.

Replacing a module definition cannot silently relabel existing bound snapshots
as products of the new recipe. Supply complete newly evaluated instances for the
changed definition. Evaluation remains an explicit caller responsibility.
The residential example additionally refuses regeneration if its current source
or declared environment differs from the saved definition. It does not silently
upgrade the provenance of the untouched towers.

## Python API

```python
from kir import sdk
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, output_id

project_key, instance_key = "example", "section-a"
level = sdk.ref(output_id(project_key, instance_key, "ground-level"))
section = ModuleInstance(instance_key, "section", {
    "ground-level": sdk.create_level(elev_mm=0, name="Ground"),
    "south-wall": sdk.create_wall(
        p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000, level=level),
})
project = ProjectRevision(project_key, [ModuleDefinition("section")], [section])
restored = ProjectRevision.loads(project.dumps())
restored.plan()                 # semantic validation, not grounding or execution
program = restored.to_program() # lowering alone does not validate
```

`replace_instance(new_snapshot, expected_revision=project.revision_id)` creates
a new revision and records its parent. `revise` replaces complete fields;
`with_instances` replaces the ordered instance collection. An expected-revision
check applies to the immutable value receiving the call, **not** to a shared
file that another process might overwrite. Persist all revisions separately if
history is required: a parent hash alone cannot reconstruct the old snapshot.

Parameters and metadata are JSON. A frame or unit label in metadata does not
transform coordinates; operation values must already follow their registry
contract. Cross-instance references must respect the existing planner's order.
Semantically invalid drafts can be saved and inspected but cannot be exported
as validated programs.

## CLI and residential example

From the checkout, using Python 3.12+ with the project dependencies installed:

```bash
PYTHONPATH=. python examples/residential_project.py --stage changed | PYTHONPATH=. python -m kir project inspect -
PYTHONPATH=. python examples/residential_project.py --stage changed | PYTHONPATH=. python -m kir project export - | PYTHONPATH=. python -m kir build - --revit 2026
```

`project inspect FILE` checks persistence integrity and reports counts. Its JSON
explicitly says semantic validation and execution were not run. `project export
FILE` runs the actual semantic planner, writes a KIR envelope to stdout and a
scope notice to stderr. Both accept `-` for stdin; neither executes saved Python
source, contacts Revit, writes a project store or publishes a change.
Export uses the same non-bulk operation budget as `kir build`; the Python API's
explicit bulk planning option does not enlarge that CLI policy.
Export is not the entire compiler pipeline: downstream geometry validation or
document grounding can still refuse the exported program. For example, a hole
outside its outer contour passes the typed plan but is refused by the compiler
with `KIR-T004`, before any C# is emitted.

Exit codes follow the existing CLI: 0 for the requested operation completed,
1 for semantic refusal, 2 for an unreadable or malformed project. Successful
export is not a successful building realization.

[`residential_project.py`](../examples/residential_project.py) exercises:

1. Three twisted concept volumes, with separate stable instance addresses.
2. Replacing tower A with a three-storey section: levels, slabs with openings,
   perimeter walls and spaces. Towers B and C remain unchanged concept volumes.
3. Saving and loading that revision, then changing storey height and terrace
   setback. Existing section output IDs and opening coordinates are preserved.

The `refines` metadata names the removed concept output; the parent revision
identifies the prior snapshot. This is a declared lineage link, **not** geometric
equivalence or an automatic freeform-to-BIM reconstruction. The developed
section is a deliberately simple new design, not a faithful native conversion
of its twisted concept volume. Section metadata explicitly names the removed
twist and top taper and marks the retained `twist_deg` input inactive. Dimensions
that cannot contain its fixed shaft are refused. There is no podium, complete circulation,
structure, MEP or claimed LOD 300 in this example.

## Local history and addressed differences

The next layer is `kir.project_store.ProjectStore`: a local SQLite file containing
one project's linear, append-only revision history. It is separate from existing
observed-graph artifacts, reverse-compiler Merkle histories and execution journals.

```bash
PYTHONPATH=. python examples/residential_project.py --stage changed --store /tmp/kir-residential-demo.sqlite
PYTHONPATH=. python -m kir project history /tmp/kir-residential-demo.sqlite
PYTHONPATH=. python -m kir project head /tmp/kir-residential-demo.sqlite | PYTHONPATH=. python -m kir project inspect -
```

`--store` requires a new path and saves all ancestors through the selected stage.
It refuses to replace an existing file. If a later stage cannot be committed,
the previously saved prefix remains and the command reports that possibility.

The general CLI supports `project init DATABASE ROOT.json`, `head DATABASE`,
`history DATABASE`, `checkout DATABASE REVISION`, and `commit DATABASE NEXT.json
--expected BASE_REVISION`. Checkout only reads; it does not move head. Init and
commit are explicit writes; read commands do not create missing databases or
perform writable recovery. Commands accepting project JSON also accept stdin.

```python
from kir.project_store import ProjectStore
from kir.project_diff import diff_projects
from examples.residential_project import develop_section

store = ProjectStore.open("/tmp/kir-residential-demo.sqlite", readonly=False)
base = store.head()
proposed = develop_section(base, height_mm=4400, setback_mm=1800)
report = diff_projects(base, proposed)
print("changed:", len(report.changed), "reconsider:", len(report.affected))
receipt = store.commit(proposed, expected_revision=base.revision_id)
```

Snapshot insertion and head advance share a SQLite write transaction. Two writers
based on the same head cannot silently overwrite each other. Exact redelivery of
an already stored revision is acknowledged without rewinding head; the receipt
distinguishes `revision_id`, observed `head_revision` and `inserted`.

`ProjectStore.open` is read-only by default; `get` validates the addressed payload
and `head` validates the current head. `history()` intentionally reads and audits
the entire chain; normal head/get/commit do not scan all historical payloads.
This is local-filesystem durability relying on SQLite, working filesystem locks
and flushes, not a network-filesystem or physical-power-loss guarantee. Read-only
access may refuse a hot rollback journal; explicit writable open allows recovery.
Never delete the journal to bypass that refusal. No branching, pruning
or distributed storage are implemented here. A later explicit storage `/1 → /2`
upgrade for body assets is documented in [PROJECT_GEOMETRY_RU.md](PROJECT_GEOMETRY_RU.md);
opening an existing database still never migrates it implicitly.

`project diff BEFORE.json AFTER.json` and `diff_projects` compare authoring
snapshots, including drafts. Added/removed/changed operation payloads are separate
from `affected`: equal-payload outputs requiring reconsideration due to explicit
dependencies, owner/parameter/context changes or operation reorder. For example,
changing a level can affect a wall whose selector and authored coordinates did
not change. Old and new dependency edges both participate in this analysis.

Unknown operations, unsupported IR versions and unresolved/nested references
are named in the report. Opaque metadata is not scraped for incidental `ref`
strings. The report carries `semantic_validation=not_run` and does not ground
selectors or prove all implicit spatial/backend dependencies. Do not execute its
changed IDs as a standalone native program. The compiler may require hosts or
other context absent from that subset.

## Geometry corrections in this wave

`SceneBuilder.add_mesh` stages data before appending it. Invalid geometry or a
packing/allocation failure must leave the existing scene and counters unchanged,
so the next valid mesh does not inherit rejected vertices.

Shape promotion now resolves the actual declared level elevation before removing
the source shape. Walls retain base and height; floors anchor their top (the
bottom still depends on type thickness); columns specify base and top. Unknown
live level selectors, out-of-contract offsets and unresolved tilted-roof
placement leave the original shape in place. `status` distinguishes a geometry
candidate from an authored native candidate; `verified=False` explicitly denies
live verification. The legacy `native` flag is not readback evidence.

## Deliberate limits and next acceptance step

Export is a **complete regenerated program**, not an idempotent patch to an
existing Revit document. Stable KIR IDs alone do not prevent duplicate native
elements on re-execution. Do not wire this export directly to an unattended
publish button until document identity, native bindings, reconciliation,
transactions and partial-failure handling are implemented and tested together.

An [optional OCCT slice](GEOMETRY.md) now retains and edits a real BRep outside
Revit. The first example stores body and operation mesh separately. Its typed
[body-owned successor](PROJECT_GEOMETRY_RU.md) introduces explicit materialization
and shared transactional asset history; full viewer/native integration remains open.

Not implemented here: recipe execution sandbox, automatic incremental engine,
distributed project store or automatic merge, typed refinement relations,
new Building Graph database, generalized LOD conversion, construction
simulation or camera observations. This foundation does not prove an advantage
over a strong LLM using Python and existing CAD tools.

The next useful acceptance scenario is continuing the same saved section across
sessions and applying a scoped change with an explicit diff. Native realization
must then be checked in disposable Revit 2023 and 2026 documents with readback,
including a repeated publish and an interrupted publish. Compiler success is
not a substitute for those checks. A broad competing-product benchmark is not a
prerequisite for this first internal persistence-and-change scenario.

## Recorded verification — 2026-09-05

Work was isolated from the serving checkout in branch
`codex/kir-foundation-20260905`, based on
`73f99118208d85aa1eb25055470eee459f6238af`, with a separate Python environment.

- Final targeted run: **355 tests and 221 subtests passed** across 16 files:
  project, workflow, package CLI, mid-end, seven geometry/promotion files and
  five viewer/scene files. This was not the complete repository suite.
- Persistence tests include a fresh process that loads a saved section,
  changes it and returns a new revision, not merely an in-process JSON round-trip.
- Nine newly added integration counterexamples failed before their fixes;
  independent review repeated the provenance, loss-label and CLI-budget checks.
- Real Roslyn compilation against Revit 2023 and 2026 assemblies passed for all
  three residential stages (6 checks) and four promotion placement cases
  (8 checks). Invalid-C# controls were rejected. No Revit document was executed.
- The original checkout remained clean at the base commit; all 1,181 tracked
  file hashes matched the pre-existing audit inventory. No commit, push,
  deployment or service-configuration change was performed.

These results establish the bounded authoring/compiler behavior above. They do
not establish native geometric equivalence, retry safety, performance on large
buildings, autonomous design quality or product-market fit.

Later foundation waves are recorded separately in the
[delivery registry](DELIVERY_PLAN_RU.md), [runtime result contract](RUNTIME_RESULTS_RU.md)
and [optional geometry slice](GEOMETRY.md). The counts above describe the first
wave, not the current aggregate suite.

### History/diff wave

The subsequent combined targeted run passed **480 tests and 221 subtests** across
19 files, including the earlier foundation and 125 new store/diff/CLI lifecycle
cases. An independent reviewer repeated those 125 cases. The new tests include
real competing processes, process exit before/after SQLite commit, hot-journal
recovery and a blocking reader at commit. Read-only/foreign-file guards, exact
redelivery without head rewind, malformed draft refs and unexpected SQL triggers
were checked. This is not a full repository test run or Revit execution.

A bounded synthetic run with 10,000 authored level operations and one changed
output produced one changed and 9,999 unchanged IDs: diff 1.915 s, store
create+commit+head 3.643 s, total 6.051 s, peak RSS 65,136 KiB on this Linux host.
This single-run observation is not p95, a long-history benchmark, BIM geometry
performance or a native incremental-update measurement.
