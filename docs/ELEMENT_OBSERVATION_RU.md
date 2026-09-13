# Reading a native element for the next edit

A limited read path is implemented: UID → KIR query → generated C# → a typed
observation parser. This is not permission to mutate and not full BIM
acceptance. Native execution in Revit has not been checked yet.

## Language query

```python
from kir import sdk

op = sdk.query_element_state(unique_id=previously_captured_uid, id="level_state")
program = {"ops": [op]}
```

The operation is declared in the shared registry, so the SDK and the JSON
Schema get it from the same contract. `unique_id` is a non-empty opaque
string of up to 512 characters. It is not trimmed, not case-converted, and
not turned into a lookup by name/numeric ID. `doc.GetElement(string)` looks
in the **already selected document**: the UID itself does not determine the
document and does not prove original creation.

The query reads:

- the identity of the element itself and separately of its type;
- name/category, the Level flag;
- for a Level — `ProjectElevation` and `Elevation` in millimeters, with no
  rounding;
- the Elevation Base from the level type;
- the actual builtin elevation parameter: ID, name, storage, read-only, raw
  feet;
- the count of same-named parameters and whether the single one found
  matches the builtin.

The parameter-identity read is compared against the actual Revit enum before
the observed Level is formed. The parameter name is not guessed from the
interface language. ProjectElevation relative to the project origin is kept
separate from the reported Elevation, which depends on the Elevation Base.
A shared/unknown basis, read-only, and an ambiguous name are kept as facts,
not automatically declared valid for a setter.

## Partial reading

`kir-element-state/1` has separate statuses for the element, identity, type,
and Level. A UID that is not found stays an explicit `not_found` string,
rather than disappearing from the result. A lookup/getter failure gets a
closed reason; the exception text is not copied. If identity was read but
the Level parameters are unavailable, these two facts are not mixed. There
is no hidden zero standing in for a missing elevation, and no lookup of a
different element.

Before the lookup, `Document.IsModifiable` is checked: true produces
unavailable / document_modifiable with no element reading; a getter error
produces document_state_unavailable. This guards against a deliberately
mutable intermediate state, not proof that no transaction is open at all: the
API allows IsModifiable=false even inside a transaction during
regeneration/failure processing. Correctness of native event scheduling and
the boundaries of committed-state observation remain live criteria.

The shared identity reader is also used at creation time, but the provenance
differs: a UID query does not become original-create evidence. An old
id-only receipt is not promoted to a trustworthy source binding by this
query.

## Binding to the executable query

`prepare_element_observation(unique_ids, target=..., precondition=...,
operation_id=...)` builds an ordinary `PreparedExecution` for a query
PlannedProgram. The source and its SHA are formed by the existing compiler;
there is no invented plan layered over arbitrary C#. Source/data/budget
refusals are preserved.

The budget for one helper request is 128 unique UIDs. This is not a
limitation of the building: a larger scope requires separate requests
against the same unchanged document revision and an explicit shared coverage
check. Automatic splitting/assembly of a large scope is not implemented yet.
The budget was checked with an actual source/frame construction for 128 UIDs
of 512 characters each, with astral Unicode; the global compiler limits
apply independently.

`parse_element_observation(prepared, raw_response, credentials=...,
request_id=...)` first calls the shared query response adapter: the exact
runtime/session/request/source/operation/document/precondition, a completed
call, a fully empty change manifest. It then checks the exact set of output
IDs, all fields/types/substates of each element, and the link between the
requested UID and its identity. A missing scope row, someone else's UID, or a
newer revision are rejected.

The `ElementObservation` result holds the source precondition and immutable
JSON. `rows` returns detached data; `require_identity(uid)` requires an
observed element, `require_level(uid)` also requires full Level fields and
type identity. The latter method **does not** authorize a write: the planner
must check the basis, parameter ambiguity/read-only, the actual baseline
against R0, and the source ownership. Reading an old receipt keeps the old
revision; it does not refresh it.

## Checks and boundaries

- Planning/SDK/schema/source and the actual Connector CodePolicy/reference
  compile for 2021–2026. Reference assemblies are not executed.
- The executable C# rig runs an actual query fragment against a fake API:
  found/missing/throws, a numeric-ID change under the same UID, type/getter
  failures, Project/Shared basis, BIP/storage/value/name ambiguity,
  nonfinite and 64-bit IDs.
- All 72 results of these executed scenarios pass through the actual field
  parser; missing data does not get defaults. Individual corruptions produce
  a refusal.
- A full wrapper, real native getters, DocumentChanged timing, Windows
  channel authentication, and the actual preservation of the model are not
  proven by this rig.

This read path uses ordinary generated-code execution. The existing legacy
runtime limits the number of assembly loads in Revit 2021–2024; the query
also spends from this budget. Long-running work with no restarts and large
scopes require further runtime/scaling work; they are not closed by this
query.

The next consumer is the [addressed update plan](NATIVE_UPDATE_RU.md), which
will connect the source publication, the authoring diff, and this
observation. The overall R03 task remains open.

## Obtaining a current observation

`observe_elements` combines two exchanges: context → query over the selected
UIDs. The advertisement/client, the expected runtime/document key, the
operation ID, and both UI-binding decisions are required. A wrong target
refuses before the exchange; a wrong document refuses before the query. The
query keeps the revision of the obtained context, not refreshing it after an
admission refusal. There are no automatic retries, no cleanup, and no
writing to the source archive.

On the wire, the query uses the existing `kind=execute`, but the formed KIR
plan has family=query and contains no model-write ops. This is a property of
the trusted compiler path, not a new read-only ACL on the native execute
endpoint itself. Six controls with a synthetic transport checked the order
and the refusals with no files/subprocesses; the real transport of the new
wrapper has not been checked yet.
