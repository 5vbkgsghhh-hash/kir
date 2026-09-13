# Macro derived IDs: a full parent with no overflow of child addresses

`Project.output_id` remains the same full 64-length SHA-256; the Project
schema, namespace, and source pins were not changed. The fix sits with the
owner of the `kir.macros` expansion, not in Project or in post-processing C#.

## Confirmed refusal

Each of `stack`, `grid_array`, `series` took a parent of length 64, then
appended a suffix. In Project `/1` and `/2`, all three legitimate macro
inputs got child IDs of length 67–69 and `KIR-T002` during actual planning.
For stack, the related `KIR-L003` followed: references could not resolve
into invalid ops. Six Project regressions first turned red, then passed.

## A single derived-identity algorithm

If the previous child ID has length ≤64, **it is preserved byte for byte**:

- `stack`: `parent_Lk`, `parent_Lk_member`;
- `grid_array`: `parent_Xk`, `parent_Yk`;
- `series`: `parent_k_member`.

Only a longer, previously invalid ID is replaced with the SHA-256 of a
canonical UTF-8 JSON array:

```text
["kir-macro-derived-id/1", macro_kind, original_parent,
 child_role, ordinal, local_member_or_null]
```

The role distinguishes level/member/X/Y. The ordinal is the previous index
(starting at 1 for stack/grid, at 0 for series). A structured tuple is
hashed, not an ambiguous concatenation. Geometry, parameters, the number of
subsequent floors, and the source's position in the overall envelope are not
part of the identity.

Collisions are not "fixed" with an ordinal suffix: the ordinary compiler
duplicate-ID gate remains authoritative and refuses. SHA-256 is not a
mathematical promise of no collisions or of native BIM identity.

## Scope of local references and the synthetic level

Stack/series first build a full map of local members to final child IDs; the
`id` assignment and the existing selector rewrite use exactly this map.
`by:ref` inside hosted selectors and `at_element` get the ID of the member of
their own floor/step. Arbitrary strings — for example a family symbol name
that happens to match a local ID — are not rewritten. External refs outside
the map remain unchanged.

In stack, the synthetic `level` is now assigned **after** the local-member
rewrite. Previously a legitimate member `id="s_L1"` intercepted the
automatically created reference to level `s_L1`, and the wall referenced
itself. After ID-bounding alone, the same defect reproduced with a member ID
equal to the hashed level ID. Both controls were RED specifically on the
self-reference and became GREEN after the order was fixed. A hosted
door/window does not get a separate level: it stays with the host.

`expand_with_origins` preserves the previous original source ID/index/macro
name for each expanded op and remains the public way to get the actual
derived child IDs. No new macro grammar, cross-document addresses, or global
rewrite of all program lines has been added. A previously invalid, long,
concatenated child ID does not become an alternative alias for the bounded
ID.

## Compatibility and verified boundaries

The profile's tests check:

- Project `/1` and `/2` → materialize/real plan → compile 2023/2026 for three
  macros;
- legacy child lengths of 63/64/65 and long local members;
- internal level/host/nested `at_element` refs and external/literal controls;
- parameters/transforms remain unchanged, IDs are preserved on a late append
  and on rearranging other source nodes;
- a forced hash collision and an explicit authored collision produce a
  compiler refusal;
- identical expansion in a separate Python process;
- the SHA of the expanded JSON and C# fixed **before the fix** for all three
  short-ID macros; existing golden files are not overwritten.

Nested macros and `create_group` inside a macro body are not allowed by this
fix; macros inside `create_group.members` also remain outside the current
contract. The budget, the order of ref dependencies, and the
geometry-transform limits are not lifted.

Compilation is offline validation/code generation, not Revit execution. A
stable macro child ID does not prove native element reuse on the next
publication and does not mean the macro can be reconstructed from arbitrary
BIM.

## Provenance of the C# byte pins (09/07/2026)

The pin on the full C# bytes for `stack` (`STACK_CAPTURE_CSHARP` in
`kir/tests/test_macro_derived_ids.py`) was **red in its own commit**: the
values `246e31af…` / `aa0c4808…` were introduced together with the test
itself in `878947f`, and no history tree had ever produced them. That same
`878947f` added two named capabilities to the emission — a receipt of source
identity (`element_identity_readback_cs`) and a check of the assigned type
(`type_assignment_declarations` / `type_assignment_witness` /
`type_assignment_readback_cs`) — which is why `stack`'s bytes moved from
`be4430…` (parent `73f9911`) to `af1070…` (2023) and `2dd284…` (2026). The
years diverged because 2026 reads `ElementId.Value`, while 2023 reads
`(long) ElementId.IntegerValue`.

The pin `BASELINE[...][1] = be4430…` (the bytes BEFORE the fix) **was not
changed**: it remains the reference for additivity. The test takes both
capabilities with the same public emitters that produce them, and must
reproduce `be4430…` byte for byte for both years. Verified: for `stack`,
commit `878947f` is 198 added lines and **not one removed**, apart from four
`__rb["id"] = …` lines replaced with their own `try/catch` form. The previous
normalization only took the receipt for `create_level` (2 ops out of 4) and
did not take the type check at all — the reference was unreachable, and no
one was checking additivity.
