# Building Graph and reverse compiler

The reverse pipeline turns a captured model into a typed, navigable building
representation without pretending that every native element has a perfect KIR
equivalent.

## Pipeline

```
L0 capture -> extraction indexes -> L1 lift -> fold -> materialize / rebuild
```

- **L0** is an observed capture boundary: source facts, categories, geometry,
  identifiers and capture completeness stay explicit.
- **Lift** maps known structures to typed operations and relationships.
- **Fold** detects regularity and reusable structure without erasing source
  lineage.
- **Materialize/rebuild** produces planned KIR programs and retains the link
  from source elements through lifted nodes to planned operations.

The Building Graph is a persistent semantic/topological representation, not a
dump of triangles and not an LLM guess. It carries identity, containment,
hosting, adjacency, dependencies and provenance where those facts were
observed.

## Honest residuals

Some source elements cannot be reconstructed as a native KIR operation. KIR
keeps them as typed atoms or residuals with a reason, instead of silently
dropping them or claiming a lossy conversion is exact. A derived lineage row
only joins runtime element IDs when plan, document and execution evidence bind
unambiguously.

## Why it matters

This makes an existing building editable as a program: an AI can retrieve a
small task-conditioned slice, propose a Python/KIR change, then compare the
observed result with the intended delta. The graph remains observed state;
intent, alternatives and acceptance live in the caller's task layer.

## Authored revision vs observed graph: one discrepancy report

`kir/discrepancy.py` compares one authoring revision with one observed
Building Graph and returns a single report. It is a pure consumer: no
transport, planning, materialization, native execution or persistence.

### The join is a UniqueId, never a name

The only bridge is the Revit `UniqueId`. On the authored side it comes from
the original CREATE receipt (`assess_create_identities`, states
`created_here` / `reused_existing`); on the observed side from a node's
`DefinitionIdentity` (`document + element_unique_id`). Names, categories,
numeric `ElementId` values and geometric proximity are never used to match.

### Six outcomes per address

| outcome | meaning |
|---|---|
| `authored_only` | the authored address has no element in the observation |
| `observed_only` | an observed element no authored address claims |
| `both_agree` | a named field was compared and the values are equal |
| `both_differ` | a named field differs: field, both values, units |
| `identity_unknown` | there is an address but no identity — nothing to compare |
| `both_unmeasured` | identities matched, but the field cannot be compared, and the reason is named |

The sixth is not decoration. `WALL_USER_HEIGHT_PARAM` stops being the truth
about a wall's top as soon as that top is constrained to a level — a
measurement from 29.07.2026 that also lives in `design_check._wall_span`. On
the corpus (MNVNK, 22.08.2026, 10 646 walls) **7 007 walls (65.8 %)** are
constrained that way and another **2 801** never had their wall parameter
block read at all. Folding those into `both_agree` would claim agreement
where nothing was compared; folding them into `both_differ` would blame the
building for our own blindness. The report reads the graph's existing
`top_constrained_to_level` edge and reports the named reason instead.

### An absence claim requires full coverage

`authored_only` is a statement about absence, so it is only issued when
`BuildingGraph.identity_authoritative` holds — every node readable. One
identity-incomplete node and the row becomes `identity_unknown`: "not found"
would otherwise be indistinguishable from "could not read". Measured on the
offline demo capture (`capture_api.write_demo_capture`): with no identity
context the graph yields **4 nodes, 0 authoritative, 4 incomplete**, gap
`legacy_context_absent`; with `DocumentIdentity`/`FederationContext` supplied,
**4 of 4 authoritative** with real UniqueIds.

A missing receipt row is *not* an absence claim either: without an address
nothing can be proved about the model, so it stays `identity_unknown`. Only a
receipt that positively reports a refused operation yields `authored_only`.

### The observation fingerprint is an explicit input

A `BuildingGraph` carries no revision and no fingerprint: its representation
is schema, `doc_name`, document identity, federation context, census, nodes
and edges. `change_stamp` lives in the L0 header and the snapshot digest is
computed by `capture_edit._snapshot_digest`; neither reaches the graph. So
`ObservedRevision{document_identity, change_stamp, l0_sha256}` is passed in
explicitly, exactly as `document_identity` is passed to `graph_from_l0`, and
for the same reason: a fingerprint inferred from a directory name or from the
graph itself would be a fingerprint of our own assumption.

What is checked: the declared document identity must be the identity of the
supplied graph, otherwise `observation_revision_mismatch`. What is **not**
checked, and is therefore named in `claims`: the binding between the
observation and the publication's open document. The authored side holds an
opaque `document_key`; the capture side has none, so that link is declared
`not_established` rather than invented.

### `building-graph/2`: the fingerprint is now measured, not declared

That migration was made on 07.09.2026, and it changes who is responsible for
the date. `build_graph_for_run` **derives** the fingerprint from the same L0 it
reads the nodes from: `change_stamp` out of the header, `l0_sha256` out of the
stream. `ObservedRevision` is therefore taken from the graph by default; an
explicit one is still accepted, but a declaration that contradicts a measured
fingerprint is `observation_revision_mismatch` — the measurement is the subject,
so it cannot lose to a claim about itself. The report says which it used:
`derived`, `declared`, or `absent`.

**The digest is over the decompressed stream, not the file bytes.** The snapshot
janitor compresses cooled runs (`L0.jsonl` → `L0.jsonl.gz`), so a file-bytes
digest would change the identity of a building because of an event that has
nothing to do with the building — and the report would then announce "another
revision" where nothing moved. `graph_store.l0_digest` reads through
`open_snapshot`, so a cooled run yields the same number as a hot one. This is
**not** `Capture.source_sha256`, which hashes the file bytes: the two count
different things and coincide only on an uncompressed snapshot. Never compare
them. The streaming digest is a second carrier of `snapshot_io.digest_bytes`
(for memory), and their equality is a control, not a promise.

**`/1` stays readable.** 76 corpus runs are on disk in the old form; declaring
them unreadable would lose the state of real buildings over a key they never
had. A `/1` artifact loads, reports `fingerprint_status: absent`, and the
discrepancy report names that as `observation_fingerprint_absent` instead of
inventing a plausible date. This compatibility lives in `graph_from_dict` /
`load_graph` on purpose: `graph_clash_query` refuses a wrong-schema artifact
before it considers rebuilding, so a hard refusal there would have taken CLASH
down with it, not just this report. A schema that is neither `/1` nor `/2` still
refuses loudly, and a `fingerprint_status` contradicting its own payload refuses
too.

`tools/graph_artifact_census.py` counts what is on a corpus disk by schema
version. It writes zero files, takes its root from `KUKAI_DECOMPILE_DATA`, and
skips with a named reason when that root is absent — a silent zero there would
read as "no old artifacts", which is our blindness dressed as a fact.

### Identity replacements: a replacement is still one thing

When a published element is superseded, the bridge accepts a replacement
ledger in either of two forms: the confirmed
`create_publication.IdentityReplacementLedger` — recognised by what it can
answer (`effective_unique_id`, `.replacements`), never by importing its class —
and a plain `kir-create-identity-replacement/1` mapping
(`superseded_uid` → `superseded_by`) for callers with no publication at hand.
The forms diverge only up to the pairs; from there one law applies to both,
which is a condition rather than a convenience: refuse two forms differently and
strictness would depend on who called rather than on what was supplied. A
confirmed ledger outranks a declared one in provenance but not in trust — cycles
and forks are rejected for both, even when the carrier says it already checked.
A report that takes another module's check on faith is not an instrument.
Without it, one replacement prints as **two** discrepancies — `authored_only` on
the old address and `observed_only` on the new — which is worse than silence: it
accuses the model twice for a change that is not a difference. With it, the pair
becomes one row carrying both addresses (`unique_id`, `resolved_unique_id`,
`superseded: true`).

Chains resolve to their last link. Anything that makes the answer ambiguous
refuses by name rather than picking: `identity_replacement_forks` (one old
address with two successors), `identity_replacement_cycle`, and
`identity_replacement_self`. A bridge that chooses between two answers is a
coin, not a bridge. The ledger moves the *address*, never the agreement: a wall
authored at 3000 mm and observed at 3200 mm is still `both_differ` after the
replacement is applied.

### Census law

The same law the graph holds for itself: every address gets a named outcome.

```
authored addresses = compared rows + excluded outputs
sum(counts)        = compared rows + observed_only rows
observed nodes     = matched + observed_only + named node refusals
```

A report whose census does not balance refuses to exist, because silent
dropout would make it look like a report with *fewer* discrepancies.

### Comparable field profile

Deliberately narrow, and everything outside it is named rather than guessed:

| op | authored field | observed parameter | units |
|---|---|---|---|
| `create_wall` | `height_mm` | `WALL_USER_HEIGHT_PARAM` | mm |

That pair is not invented here — it is exactly what `lift._lift_wall` joins,
and the parameter arrives through the closed `extract.SECTION_PARAM_NAMES`
list into `GraphNode.section`. Outputs of other operations land in
`excluded_outputs` with the reason `not_in_comparable_field_profile`.
