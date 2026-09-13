# Original identity of a created element

The new compilations `create_level`, `create_directshape`, and
`create_solid_blend` add to their own per-op readback a reading of **the exact
object that create returned**, after a successful commit in the same Execute.
The read does not recover the object through a numeric ElementId. The other
create operations, the general stamp readback, and old saved C# archives do
not change their contract.

Full result:

```json
{
  "element_identity_status": "captured",
  "element_identity_reason": null,
  "element_identity": {
    "schema_version": "revit-element-identity/1",
    "element_id": 700,
    "unique_id": "original-element-unique-id",
    "version_guid": "abcde123456789abcdef0123456789ab"
  }
}
```

This is the existing `ElementIdentityProof` wire, not a new identity model. The
number is taken from `ElementId.IntegerValue` for Revit 2021–2023 and from
`Value` for 2024–2026. UniqueId must be non-empty; the numeric id must be
positive. VersionGuid is serialized in the `N` format, without hyphens.

If the object is missing, the data is incomplete, or the getter threw an
exception, the fields read `element_identity: null`,
`element_identity_status: unavailable`. Closed reason codes: `element_missing`,
`identity_incomplete`, `identity_unreadable`. The native exception's text is
never copied outward. The old `id` field on these three paths is separately
protected from a read error and returns `null` if it is unreachable.

An identity-readback error does not trigger a rollback, does not add a
postcondition failure, and does not change the commit result. This is an
ordinary receipt, **incomplete for a later automatic update**. The completeness
of other readbacks, and handling of every prior getter, is not proven by this
change. In particular, the old readers of Name, Elevation, and geometric
measurements are not rewritten here.

## Boundary of the guarantees

`captured` means the completeness of this specific read, not freshness,
general project ownership, or permission for a future write. VersionGuid is
not a counter of every transaction. An update still needs the original
receipt, the same runtime document, a fresh revision-bound observation, and a
pre-effect guard; a stable Project output ID does not by itself reuse an
Element.

The shared `element_identity_readback_cs` also works for a UID query, but the
provenance is decided by the calling code: a query lookup does not become
proof of original creation. An old receipt with only a numeric id is not
promoted to an original identity by a later lookup: that id may already
belong to a different element.

In the saved townhouse example, the capture covers three levels of section A,
two conceptual blend towers B/C, and the podium's DirectShape. Walls, floors,
and rooms are not claimed as covered. Blend and mesh remain geometry inside a
DirectShape, not full-fledged native BIM components.

## Checks

`test_created_element_identity.py` checks the chosen original-object
variables, the readback's position after commit, the unchanged behavior of
uncovered paths, a saved ProjectStore → materialize → compiler round trip, and
both versions of the numeric id. A separate executable C# stand checks null,
incompleteness, getter errors, and a 64-bit id; it runs only the reader
against a fake Element, **not Revit**. The optional checks of the real
Connector CodePolicy/Compiler use real Revit 2023/2026 reference assemblies,
but do not perform a build inside Revit. Live reading of originally created
objects is not yet checked.

Only the four affected C# goldens are updated: `stack_two_storeys`,
`full_house_v1`, `place_family_placement_kinds`, `auth_directshape_tower`. The
checks of the previous short macro child IDs remain; the new C# hashes for
`stack` account for the deliberately added readback and the ElementId API
difference between 2023 and 2026. Recipe pins, Project IDs, and saved
SourceArchives are not rewritten.

## Replacing a native identity: an explicit policy (07.09.2026)

`Element.ChangeTypeId` is documented by the assemblies as: "In rare cases,
applying a change in type will result in a new element being created. The
ONLY active examples of this are when applying a normal wall type to a
curtain panel, or converting such a wall back to a curtain panel. In this
situation the new element id is returned. Also, this element becomes
invalid." That means one authored output's native identity can change
**without the author's involvement**: the old `UniqueId` is dead, and a new
element exists, claimed by no one.

### What was measured

The emission already carried the fact of a replacement, in four fields —
`replacement_element_id` (the transaction unit), `new_element_created`
(`change_type`), `panel_replaced`, and `returned_panel_id` (a curtain-wall
cell). **They had zero consumers.** The consequences, measured 07.09 on real
reports:

| instrument | without a replacement | after a replacement (before this work) |
|---|---|---|
| `authored↔observed` discrepancy report | `both_agree = 1` | `authored_only = 1` + `observed_only = 1` |
| type-link report | `matched = 1` | `unavailable = 1`, `consumer_observation_unavailable` |
| republication (`staged`) | links up | refusal, `staged_import_observation_missing` |
| the created-elements registry | — | the new element left NO trace (`change_type` is `MUTATE`) |

The first row is the most expensive one: one building split in two, into "the
author lied" and "there is someone else's element in the model," and neither
half was true.

### The replacement ledger, `kir-create-identity-replacement/1`

`create_publication.assess_identity_replacement(project, record, bound_receipt,
observation, *, claims)` assembles the ledger. A claim is
`{old_unique_id, new_unique_id, reason}`, with the reason drawn from the closed
list `REPLACEMENT_REASONS` (today, `change_type_replacement`).

**A claim is not taken on faith.** Confirmation is a property of ONE snapshot
at ONE revision: the old uid answers `not_found`, the new one answers
`observed` with a captured identity. Two snapshots at different revisions
cannot serve as confirmation: someone else's turn could have passed between
them, and "disappeared" would stop meaning "replaced." Any other outcome is a
named refusal, `replacement_unconfirmed`. A snapshot from a different
runtime/document is `observation_runtime_or_document_mismatch`; a snapshot
from before the publication is `observation_not_after_publication`; a
foreign uid is `replacement_old_identity_unqualified`.

**Addition, not rewriting.** The old link is not erased: it travels whole,
inside the row (`original_identity`), and gets `superseded_by`. A chain of
replacements is resolved transitively (`effective_unique_id`), and a cycle is
rejected.

**A sixth state was deliberately not added to `assess_create_identities`.**
`discrepancy._QUALIFIED` and `staged_create_projection` silently treat an
unfamiliar state as unqualified, and a new name there would become a quiet
loss of the address. The replacement travels on its own separate carrier,
with its own digest.

### Who reads the ledger

| consumer | what it does |
|---|---|
| `stored_type_readback` | requests both sides of the claim within ONE observation scope, assembles the ledger, hands it to the report; an unconfirmed one is `replacement_unconfirmed` in `diagnostic_code` |
| `create_type_discrepancy` | resolves the address BEFORE reading the observation; the row gets `matched` by the new uid and the field `consumer_identity_replacement` / `expected_type_identity_replacement` |
| `staged_create_projection` | a republication links up with the replacement and **does not build a second element**; the ledger is addressed by the import's `output_id` |
| `created_ledger` | a `MUTATE` op that claims a replacement leaves the id of what was born; an ordinary edit of someone else's element still leaves nothing |

The ledger must belong to the same publication and the same snapshot:
`identity_replacement_publication_mismatch` /
`identity_replacement_observation_mismatch` (in `staged`:
`staged_replacement_publication_mismatch` / `..._observation_mismatch`).

### One refusal covered three cases

`staged_import_observation_missing` was said both when the uid was never
requested, and when the model answered "no such thing," and when the element
was replaced. Three causes call for three different actions, and one name let
you pick none of them. Now:

```
staged_import_observation_absent        the address was never requested
staged_import_observation_unavailable   it could not be read
staged_import_element_not_found         the model says: no such thing
staged_import_replacement_unconfirmed   a ledger was filed, but does not explain the addresses
```

### Storage

The ledger is a frozen carrier with a digest (`ledger_digest`), like
`CreateIdentityAssessment`. It **sets up no table** and does not move
`sqlite_schema`: `project_store._verify` checks `sqlite_schema` against an
exact set, so a new table would require schema `/9` and an edit outside this
plot. The sidecar's inert check is `validate_identity_replacement_ledger`; it
does not restore the freshness of a confirmation, it only checks that the
bytes have not drifted from the publication.

### What this work does NOT close

* `discrepancy.py` (`authored↔observed`) still joins the two sides by the raw
  `UniqueId` (`_QUALIFIED`) — the `authored_only`/`observed_only` pair on a
  replacement lives there until the graph's owner makes the edit;
* `emit_transaction_unit`, in the after-observation, still re-reads the
  element by the **old** uid (`doc.GetElement(__reassign[i])`), and on an
  actual replacement declares `after_observation_disagrees` on a successful
  turn — that is native's plot;
* the transaction-unit receipt (`kir-transaction-unit/1`) has no Python parser
  at all.

### Checks

`kir/tests/test_identity_replacement_after_change_type.py` — 27 checks: three
probes with their own controls, a FAIL control (address resolution is broken
on purpose — the probe must turn red), and a pin on F-297 (an ordinary edit of
someone else's element still does not enter the created-elements registry).

### Convergence of shapes with the transaction-unit receipt

The transaction unit (`emit_transaction_unit`) places an
`identity_replacements` field in the receipt, as rows of the contract
`IDENTITY_REPLACEMENT_ROW = ("schema", "old_unique_id", "new_unique_id",
"identity_replaced", "old_element_id", "new_element_id")`.
`assess_identity_replacement` accepts such a row AS IS — the schema name and
the field set are **imported** from `emit_transaction_unit`, not repeated as
literals: a value named in one place and read from another has no obligation
to match, and renaming it along the way would be exactly the class of error
the ledger was built to forbid.

A row with `identity_replaced: false` is NOT a claim (the type changed in
place) and is rejected by name. The unit's own bookkeeping
(`type_id_before`, `type_id_after`, `moved`) is allowed alongside it and does
not interfere. The receipt remains a **claim**: confirmation is still one
snapshot where the old uid is `not_found` and the new one is `observed`.

### Output to the discrepancy bridge

`IdentityReplacementLedger.to_bridge_dict()` hands the ledger over in the form
accepted by `discrepancy._resolve_replacements` (the graph plot):

```json
{"schema": "kir-create-identity-replacement/1",
 "replacements": [{"superseded_uid": "<old>", "superseded_by": "<new>",
                   "reason": "change_type_replacement"}]}
```

The shape is narrow ON PURPOSE: the consumer rejects an extra key in the row,
so that a mismatch of shapes surfaces as a refusal, not a silently wrong
bridge. The rest of the ledger (identities, the confirmation's revision, the
authored output's address) stays in `to_dict()`. A chain `A→B→C` is NOT
collapsed here: direct pairs travel as they are, and the resolution into `C`
is done by the bridge itself — otherwise the two sides would be counting the
same thing by two different laws.

The end-to-end probe
`test_a_native_row_travels_end_to_end_into_one_both_agree` carries one case
through all three plots: the native receipt row → the identity carrier → the
graph bridge's dictionary. The outcome is **one `both_agree` row**,
`authored_only = 0`, `observed_only = 0` (a survey before this work gave
`authored_only = 1 + observed_only = 1`).
