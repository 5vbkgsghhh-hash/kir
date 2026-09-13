# Native blend preview: a separate approximate result

`kir.viewer.blend_preview.preview_native_blend()` builds a profile-proxy,
not a native Revit shape. The authored `create_solid_blend`, its ID, the compiler,
the saved Project, and clash geometry remain unchanged.

Reason for the separate contract: the actual emitter passes `vertexPairs=null`.
Profile correspondence is chosen by Revit; an equal vertex count does not prove
that our interpolation reproduces its lateral surface. Planes in Revit
can be non-parallel; a single `plane + height` limits the current KIR,
not Revit's own API.

The first producer accepts two straight rectangular profiles without holes,
with the same orientation and a positive uniform similarity in the authored
vertex order, rotated up to ±30°. It does not guess cyclic correspondence,
does not mirror, does not straighten arcs, and does not fix an unsupported profile. Only
this preview recipe refuses: a legitimate more complex KIR operation remains legitimate.

The result contains nine cross-sections, a source-op/plan digest, the applied frame, and
explicit claims: `native_equivalence=unverified`, `containment=not_claimed`,
`mesh_error_bound=not_measured`, `clash_eligibility=none`. The end faces are copied from
the normalized authored profiles; the intermediate points are a display interpolation.
The fitting check's accuracy is not declared as a tolerance for matching the native shape.

The consumer must support `display_approximate_profile_proxy/1` and visually
distinguish such an object from the original mesh. The old external KUKAI viewer forcibly
draws every mesh as shaped; its production assets are not changed by this work.
So the producer **is not implicitly wired into `live_scene`**. A separate opt-in export is
being prepared for the new standalone consumer; its acceptance does not follow from these tests.

Verified: 27 new tests and the associated strip of 62 passing. An independent reviewer
repeated the 27, then ran 18 more analytical controls: real caps/frame/normals,
closed orientation, volume of non-twisted frusta, a negative base, a downward plane,
and a shift by 10 km. This is not live Revit, and not a comparison with its blend.
