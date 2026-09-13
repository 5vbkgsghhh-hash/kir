# Creating types is not the same as changing existing types

Before wiring explicit types into the section, two existing factories were checked:
`create_type` for FamilySymbol and `create_wall_type(host_kind=...)` for
wall/floor/roof/ceiling. This work does not introduce a new type IR.

## Confirmed defect

The previous `create_wall_type` accepted a same-named type by the shared `kir:` prefix
in the type comments. `create_type` accepted any same-named sibling of the same Family,
with no marker check at all. Both factories then modified the found type.
This affected every existing element of that type. Checks of the requested
values after the write could not detect the takeover of someone else's resource.

A control with actually generated C# and in-memory Revit stubs reproduced
overwriting a wall type 200->350 mm with `duplicated=false` and zero postcheck violations.
This is not a test of a live document, but emitter fragments were executed, not
a guard model rewritten in Python.

## New contract

- A same-named resource must be unique within its scope: the Family for
  FamilySymbol, the specific HostObjAttributes class for a system type.
- Reuse requires the exact full `{program_stamp}:{op_id}`,
  compared ordinally. A shared `kir:` prefix or a similar name does not grant reuse rights.
- Even a matched resource is used **read-only**. The factory does not call
  SetCompoundStructure, dimension/material Set, Activate, or restamping on it.
- The new postchecks re-read the current values and apply the declared
  tolerances. A mismatch gives a refusal, not an implicit drift fix.
- Only the new Duplicate result receives the assembly/parameters and the marker. Writing
  the marker and reading it back are mandatory; an absent/read-only/failed Set
  is not hidden by a successful creation. The outer transaction is responsible for rollback.
- Material names for FamilySymbol now require a single exact
  match, same as layer materials; the first element of an ambiguous set
  is no longer picked automatically.
- Width/depth require an observed `StorageType.Double` and the `Length` spec before
  writing to the corresponding parameter and on read-only reuse. For 2021,
  `Definition.GetSpecTypeId()` is read; for 2022-2026, `GetDataType()`. A missing
  definition/spec or a read error give a named refusal, not a guess about units.

Separately, the matrix found an old `per_op` defect: the Material local was declared
in the create block but used by an external postcondition. All six APIs
got a CS0103. Now the reference is declared in the shared decl scope; the material
itself is still resolved in the create phase. The format and meaning of the layers are unchanged.

Another confirmed defect is an arbitrary dimension-parameter name. Previously,
a Double parameter of type Number/Area/Angle received `U(width_mm)`, while the check
`MM(AsDouble())` confirmed the same number without checking the physical dimension.
In an executed control C#, a Number parameter requesting 450 mm received a value of
1.47637795 with a successful postcheck. Now such a parameter does not get a Set.
If depth is invalid, the width of the new duplicate could have been written before the refusal;
the outer transaction must roll back the creation. For an existing type, any
writes remain forbidden.

## Checks of the current generation

MAIN: **136 passed + 364 subtests / 9.23 s** across six files: the pre-existing
`test_create_wall_type`, `test_families`, `test_golden`,
`test_element_is_not_a_supertype_of_types`, `test_type_sections`, and the new
`test_type_creation_ownership`. Only the corresponding family golden was changed,
after reviewing the C# diff; the other goldens were not regenerated.

Independent runtime lane: **28 passed / 6.57 s**, overlapping with the new file
included in MAIN; the numbers do not add up. It executes create and all original
post fragments against a public compiler in a deliberately fake API: 156 ownership/material
scenarios plus 384 dimension scenarios (legacy/A5 x atomic/per_op, API branch
2021/2022/2026). Wrong dimension, String storage, null, and a getter exception
are refused; the positive Length controls do not let through an implementation
that refuses everything. Before the guard, the new grouped checks gave **12 failed**, while
the previous 16 stayed green. This is a counterexample, not just a new snapshot.

The dimension check **does not prove** that this parameter drives the width
or depth of the family's actual geometry. Such a geometric witness remains a
separate obligation. The stub rollback is likewise not live proof.

Matrix `test_type_creation_conformance`: **18 passed / 78.08 s**, no skips.
72 wrapped programs pass actual CodePolicy/Roslyn and reference assemblies for
Revit 2021-2026 (six factory variants x two isolation modes x six versions),
12 policy/syntax counterexamples are rejected. The rerun included the new
version-aware Length guard. Runner: `.work/type-conformance-BrDk3F/bin/CompilerConformance.Tests.dll`,
results: `.work/type-conformance-BrDk3F/pytest-length-guard`.

## Important limitations

The translation certificate checks values, not the absence of write events.
Claims about foreign-name refusal/read-only reuse and the absence of restamping carry
explicit notes: they are backed by construction guards and negative tests with
call counters, not a post-value witness. An unchanged stamp after a Set
does not prove that Set was never called at all. This gap is not masked by a
new string marker in the certificate.

The previous legacy/A5 stamp format and its readers are preserved. The legacy program hash
remains a short SHA-1 fragment, **not** a cryptographic identity or
owner authentication. Read-only reuse protects against changing an existing
type even when the marker matches; a matching marker does not prove the whole history
or the invariance of the seed's unobserved properties.

The stamp covers the entire program. Editing a different op can change the marker even
when the type definition is unchanged. Such a request does not gain the right to overwrite the type:
it needs either a new explicit name or a separate observed binding to the existing resource.
This slice does not implement a general ensure/update type protocol. Changing a shared type
will require an explicit plan and checking every affected element.

Compound layers are declared explicitly, but the whole type is not yet independent of the template:
Duplicate inherits properties outside CompoundStructure, and floor/roof/ceiling also
use the EndCap seed. The source type is chosen explicitly; an element_id without a separate
observation does not prove its UniqueId. A layer material without `material` remains
unassigned rather than automatically becoming "concrete".

Full observed layer readback and reverse reconstruction of floor types are not
closed yet: precommit checks of the assembly and a durable type model are different tasks.
The fix applies to the new C# generation. Already saved sources/archives
are not rewritten and do not get new guarantees retroactively. Unknown executions
of an old source must not be authorized by blindly rerunning it.

Live Revit documents were not modified. The matrix with actual API references checks
compilation/policy; the in-memory stubs check code branches; neither replaces
live acceptance on agreed test documents for 2023/2026.
