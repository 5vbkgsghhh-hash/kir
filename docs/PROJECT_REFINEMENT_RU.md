# G03: explicit authored 1:N decomposition

The first limited contract links one past conceptual `create_solid_blend` to
several named outputs of the current instance. This is `schematic_redesign`:
the author declares the roles and the losses. The contract does not prove
preservation of geometry, correctness of the layout, load-bearing function,
LOD, or native BIM.

## One carrier, two different addresses

The data lives in the already existing
`ModuleInstance.metadata["refinement"]`. The Project/Store schema and IR are
unchanged. The new nested record has its own
`schema="kir-schematic-refinement/1"` and contains:

- Source: the exact project/revision/instance/output keys and the digest of
  the whole `NamedOutput.to_dict()`, not just the stable operation ID.
- Members: a full ordered list of the current output keys with assigned
  roles; no skipped, no extra/duplicate member.
- `kind="schematic_redesign"`, a strict boolean `geometry_preserved=false`,
  named losses, and existing parameters explicitly marked inactive.

The target revision ID is not placed inside its own content-hashed snapshot.
The target is determined by the containing instance and ProjectRevision; an
external report computes its revision ID, output IDs, and actual output
digests.

The legacy `metadata["refines"]` is kept only as a checkable derived
projection of the source address. The unmodified example generator needs
it; an arbitrary substitution or a missing alias does not pass the typed
reader. This is not a second owner of the truth. Old JSON/revisions are not
rewritten and do not get a new hash.

## API and the exact boundaries of the checks

`kir.project_refinement.annotate_schematic_refinement` receives the finished
replacement and the exact source ProjectRevision. It annotates the
snapshot; it does not run the recipe and does not change the outputs,
parameters, order, or module digest. An identical repeated annotation is
allowed; a conflicting typed record is not overwritten. Old loose
declarations are allowed as annotation input only with consistent
kind/losses/geometry/inactive fields.

`carry_schematic_refinement(previous, replacement)` checks the structure and
roles of the previous record, preserves it with no new source attribution,
and refuses on a change of owner, of the output-key/order/role set, or on a
conflicting annotation replacement. Carry by itself does not check the
payload of the historical source: `refinement_view(project, instance_key, source=...)`
is needed for that.

`refinement_view` always re-checks the recognized schema, members, alias,
and the exact supplied source. A matching stable output ID under a
different source revision is not enough; a matching revision reference
under a different output digest is also not enough. The source need not be
the direct parent of the target. The report is detached; changing the
returned dict does not change the project.

The first role subset is deliberately limited:

| Role | Qualified operation |
| --- | --- |
| level | create_level |
| slab | create_floor_by_contour |
| wall | create_wall |
| space | create_room |

The actual registry create effect, a single result, the category, and the
reference kind are checked. The string `wall` cannot qualify
`create_level`. This is a check of the role's compatibility with the output
contract, not full validation of the operation's parameters, and not proof
that the native element exists.

The Project/Store continue to save arbitrary inert drafts. The presence of a
metadata block in the JSON, or the fact of a successful commit, do not
replace calling the typed reader. The report honestly keeps
`ancestry="not_checked"`, `binding_status="exact_supplied_source"`,
`roles_and_losses="authored_assertions"`. The recipe, the compiler,
geometry, and native execution are not run; an exhaustive list of every
possible geometric loss is not proven.

## A public workflow with no change to the source pins

[The new wrapper](../examples/residential_refinement.py) calls the existing
`residential_project.develop_section` with its previous recipe-pin check. It
does not change the source of this generator or of the podium generator.

1. Concept → section: the finished replacement gets `annotate` with the
   snapshot from before the redesign. All 21 outputs of A have roles: 3
   levels, 3 slabs, 12 walls, 3 spaces. Twist/taper are explicitly named as
   lost.
2. Height/setback edit: the wrapper first checks the historical source
   through the typed view, then generates the replacement and calls
   `carry`.
3. The outcome is a direct child of the source base through
   `replace_instance`. The intermediate candidate is not saved; historical
   revision bytes are not rewritten.
4. B/C, the podium, their assets, and all pins remain unchanged.

```python
from examples.residential_refinement import continue_section
from kir.project_store import ProjectStore
from kir.project_refinement import refinement_view

store = ProjectStore.open("typed-refinement.sqlite", readonly=False)
changed = continue_section(store, expected_revision=store.head().revision_id,
                           height_mm=4500., setback_mm=1200.)
source_id = changed.instances[0].metadata["refinement"]["source"]["revision_id"]
report = refinement_view(changed, "tower-a", source=store.get(source_id))
```

With optional OCCT dependencies, a separate NEW SQLite example can be
created: `PYTHONPATH=. python examples/residential_refinement.py --store NEW.sqlite`.
It saves root → upgrade → podium → typed section → changed section. This is
several explicit commits, not one shared transaction: on a late refusal, a
saved prefix can remain. An existing file is not adopted.

Important: the old generator by itself does not save a typed block. Its
legitimate legacy result gets `legacy_unbound_refinement` when a new typed
view is requested, rather than being silently treated as a continuation of
G03. This guarantee requires either the new wrapper or explicit
annotate/carry/read calls.

## Merge and ancestry are separate guarantees

Roles, parameters, and outputs belong to one whole-instance snapshot. A
grant on `tower-a` sets the accepting caller; a grant on B does not permit
changing A. `ChangeProposal`/merge do not split them into independently
mergeable fields. `clean` means authoring compatibility, not engineering
correctness.

The historical source can be obtained through `store.get`. Checking the
whole chain belongs to `store.history` and proposal acceptance, not to the
source dict. The G03 report does not promote the supplied snapshot to an
automatically verified ancestor. The proposal branch log and task grants are
not hidden inside the refinement metadata.

## What stays outside the G03 slice

No new BuildingGraph relation kinds or native bindings have been added. The
historical source reference is provenance, not a runtime `by:ref`
dependency; existing level refs remain in the actual authored operations.

A geometric oracle, requirements for materials/thicknesses/rooms,
structural adequacy, faithful geometry-to-BIM, and Revit readback are
separate future work. Their absence cannot be offset by a green count of
roles or a successful metadata validation.
