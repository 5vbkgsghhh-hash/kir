"""ops_annotation — annotation tirage; holds the whole family (KIR_DOC_SPEC.md).

create_dimension / create_tag / create_text: the ops_annotation.md family
0% -> tirage. VIEW-SPACE core (PtView2D vs PtModel3D, VIEW-BINDING LAW) lives
in docspace.py and is REUSED here, never reinvented (per KIR_DOC_SPEC.md
"the emitter clones the core, not the coordinate model, from scratch").

in_view / target / refs[] are write-target selectors (kind="target_w": pinned
element_id OR an intra-program `ref` to an earlier create_* op) — there is no
`views`/`sheets` snapshot pool yet (KIR_DOC_SPEC.md GROUND §: "add to serving
_SNAPSHOT_CS — right now there are view/sheet KINDS in query, a pool for
ground is needed" — that pool is a Fable-level registry_base.py change, NOT
made here). Resolution is therefore id-pinned/ref only, exactly like `target`
in set_param/delete and `host` in create_window/create_door — no new snapshot
pool, no grounded=(...) entry needed for this v1 tirage.

FLAGGED GAP (not invented around): dim_type/tag_type/text_type are spec'd as
"the project's catalog on ground (sole-entry/candidates)" — that needs a
dimension_types/tag_types/text_note_types snapshot pool, which does not exist
in known_pools (registry_base.py, Fable-level). These three params are
therefore ALSO plain target_w (element_id-pinned only, optional) here, NOT
sole-entry-resolved; when omitted the emitter falls back to the document's
default type (GetDefaultElementTypeId, same in-emit-default pattern as
create_wall's `type`). This is a real, flagged gap versus the spec's GROUND
ambition, not a silent guess — see KIR_ANNOTATION_GAPS note in this module's
tests for the follow-up.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

──────────────────────────────────────────────────────────────────────────────
WHAT THIS WAVE (09.08.2026) DID NOT DO, AND WHY — BY MEASUREMENT, NOT BY TASTE
──────────────────────────────────────────────────────────────────────────────
Written here, not in the report, because the next wave does not read the
report, but it does read this file. Every line was verified by compiling
against :52412 on six REFERENCE ASSEMBLIES (2021-2026), not against
documentation: see below the case where the XML describes a member that
exists in none of the DLLs.

1. ELEVATION MARKER (``ElevationMarker``) — REFUSED, reason:
   "a marker by itself draws nothing".
   * ``ElevationMarker.CreateElevationMarker(Document, ElementId, XYZ, int)``
     compiles 6/6 — the question is not API availability.
   * A freshly created marker has ``CurrentViewCount == 0`` and
     ``HasElevations() == false`` BY CONSTRUCTION: the drawing product is the
     VIEWS on the marker, not the marker itself. The only honest
     postcondition for a single op would be "an empty marker exists," i.e.
     an op that can never be carried through to a drawing. This is exactly
     the "built but useless" case that the house avoids.
   * WHAT A SECOND OP WOULD REQUIRE, and it is NOT ENTIRELY EXPRESSIBLE
     TODAY: ``ElevationMarker.CreateElevation(Document, ElementId viewPlanId,
     int index)`` — 6/6. **The name ``CreateElevationView`` DOES NOT EXIST:
     CS1061 on all six** (a trap: a plausible name that does not exist).
     Inputs: ``marker`` — target_w (element_id | ref to the marker op),
     expressible; ``in_plan`` — the id of the PLAN the marker is visible on,
     expressible in exactly the same way as ``in_view`` below (there is
     still no view pool); ``index`` — int, 0..``MaximumViewCount``-1, guarded
     by ``IsAvailableIndex``.
     ONE THING IS INEXPRESSIBLE TODAY, AND IT IS A LANGUAGE ISSUE:
     ``CreateElevation`` returns ``ViewSection``, meaning the registry would,
     for the first time, gain an op that CREATES A VIEW — while the typed
     refusal ``authoring._annot_view_res`` for ``in_view: ref`` rests on the
     assertion "no KIR op creates a View." After such an op this refusal
     would become FALSE (``ViewSection`` legitimately casts to ``View``),
     meaning a new ``ReferenceKind.VIEW`` would be needed along with a
     revision of the refusal — a change to the LANGUAGE, not to an
     operation.
   * The range of ``initialViewScale`` is 1..24,000, and this is NOT our
     number: it is stated in RevitAPI.xml itself ("The denominator X of the
     view scale 1/X must be in the range 1 to 24,000"). Recorded here so
     that the next wave does not invent its own.

2. ``NewModelText`` — REFUSED PERMANENTLY for project documents, and this is
   a MEASUREMENT: ``doc.Create.NewModelText`` gives **CS1061 on all six**
   (``Autodesk.Revit.Creation.Document`` has no such member at all), while
   ``doc.FamilyCreate.NewModelText`` exists but lives on
   ``FamilyItemFactory``, i.e. ONLY in the family editor, and its signature
   is SIX arguments (``string, ModelTextType, SketchPlane, XYZ,
   HorizontalAlign, double``; attempting seven gives CS1501 6/6). KIR writes
   project documents, so it can never have 3D text on any version. DO NOT
   PROPOSE THIS AGAIN.

3. A DOCUMENTATION TRAP caught by this wave:
   ``FilledRegion.IsRegionCreationEnabledInView`` IS DESCRIBED in
   RevitAPI.xml 2026 ("since 2012") and gives **CS0117 on all six DLLs**.
   Exactly case #78 from the canon: Autodesk's documentation diverges from
   Autodesk's own assemblies, and the compiler is the judge. Therefore there
   is no view-precheck for the fill region, and its role is played by a
   typed refusal on the exception from ``Create`` itself.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

OPS = [
    # dimension — a size between >=2 refs (elements or grids), drawn in
    # in_view's 2D plane at line_at [u,v]. VIEW-BINDING LAW (semantic witness):
    # every ref must be visible in in_view — checked post-commit (no snapshot
    # visibility pool exists yet; witness is the only layer that can prove it).
    OpSpec(
        name="create_dimension",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("refs", "refs_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("line_at", "pt_view2d", required=True),
            ParamSpec("dim_type", "target_w"),          # optional catalog type-size
        ),
        capability=(("create", "dimension"),),
        # 28.07 (live E5 measurement, FAS_R23 Revit 2023): the "line_at
        # reproduced" clause is retired — once the dimension line's own
        # direction became geometry-derived (the first reference's face
        # normal, not a fixed view axis), "offset along a fixed axis" is no
        # longer a meaningful invariant, and Dimension.Curve stays ALWAYS
        # UNBOUND regardless (Revit API Developer Guide) — see
        # _emit_dimension's docstring for the full law.
        # 09.08: the value clause REVERSES the 28.07 "receipt-only" note.
        # That note was true while the emitter picked an arbitrary planar
        # face; it stopped being true once the resolver started knowing which
        # PLANE it hands to NewDimension. The gated claim is not "the number
        # the operator wanted" (no compiler can know exterior vs interior) —
        # it is "the number Revit printed is the distance between the
        # geometry this dimension is bound to", which the witness re-derives
        # from those planes. No tolerance is registered for it: the
        # comparison runs against Revit's own Application.VertexTolerance,
        # read at runtime, so there is no number here to drift.
        post=("dimension exists in in_view (materialize); References bound "
              "to all refs, none empty (topology); every ref visible in "
              "in_view (semantic, VIEW-BINDING LAW); measured value equals "
              "the distance between the geometry the references name "
              "(geometry)"),
        writes_model=True,
    ),
    # angular dimension — the ANGLE between exactly two non-parallel refs,
    # drawn in in_view. AngularDimension.Create is 2017-era API and compiles
    # on ALL SIX shipped versions (measured 09.08 against the reference
    # assemblies via the live Roslyn service, not against docs) — unlike the
    # rest of that family: LinearDimension/RadialDimension/ArcLengthDimension
    # .Create are 2025-2026 only, and NewDiameterDimension/NewRadialDimension
    # /NewAngularDimension live on FamilyItemFactory alone (doc.FamilyCreate)
    # — family editor only, so unusable for the project documents KIR writes.
    #
    # EXACTLY TWO refs, and that bound is derived, not chosen: the API demands
    # "at least two, non parallel and rays of the arc passed", and the arc's
    # vertex is the intersection of the two referenced planes — a third plane
    # has no place in that construction. So the refs_w bound for this op is
    # (2, 2) in authoring_validation, beside create_dimension's own (2, 16).
    #
    # `at` is ONE view-space point and it carries three jobs at once, which is
    # why there is no radius parameter and no centre parameter: it fixes the
    # arc's radius (distance from the derived vertex), and it picks WHICH of
    # the four ray combinations is measured (each ray is signed toward it).
    # Same law as create_dimension.line_at — the author points at the drawing,
    # the compiler derives the geometry.
    OpSpec(
        name="create_angular_dimension",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("refs", "refs_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("dim_type", "target_w"),
        ),
        capability=(("create", "dimension"),),
        post=("angular dimension exists in in_view (materialize); References "
              "bound to all refs, none empty (topology); every ref visible in "
              "in_view (semantic, VIEW-BINDING LAW); measured angle equals "
              "the sweep of the arc built from those references (geometry)"),
        writes_model=True,
    ),
    # tag — a mark on target, drawn in in_view. `at` is REQUIRED (not
    # defaulted): IndependentTag.Create has no point-less overload on either
    # version branch, and a compile-time "near the target" default would need
    # the target's 2D position in in_view — unavailable without a witness/
    # geometry round-trip. A human places the tag point explicitly in the
    # Revit UI; the IR asks for the same (no invented auto-placement).
    OpSpec(
        name="create_tag",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("target", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("leader", "bool"),
            ParamSpec("tag_type", "target_w"),
        ),
        capability=(("create", "tag"),),
        # PROSE MUST NAME THE BOUNDARY, NOT THE INTENT (13.08.2026).
        # It used to say "TaggedLocalElementId == target" — true for
        # `IndependentTag` and SILENTLY false for a room, area, and space
        # tag: for those the link is read off their own subclass
        # (`RoomTag.Room` / `AreaTag.Area` / `SpaceTag.Space`), while the
        # base member `SpatialElementTag.SpatialElement` DOES NOT EXIST in
        # the shipped assemblies on any of the six versions. The obligation
        # is the same one — "the tag is linked to its target" — but the
        # member that checks it depends on the class, and the prose is not
        # allowed to name only one of the two.
        # THE SEMICOLON HERE IS AN OBLIGATION SEPARATOR, not a punctuation
        # mark: `translation_cert` splits `post` on it and requires a
        # witness for EVERY piece. The explanation about the tag's class
        # therefore rides INSIDE the obligation, via a comma. The first
        # draft of this fix put a ";" and immediately got "promised clause
        # not witnessed by any obligation" — the instrument caught the
        # author red-handed within the same minute.
        post=("tag exists in in_view, marked element == target (semantic, "
              "VIEW-BINDING LAW: target must be visible in in_view, связь "
              "читается у КЛАССА марки — IndependentTag свои цели, "
              "RoomTag/AreaTag/SpaceTag свой подкласс); at "
              "reproduced ±tol in view-space (geometry)"),
        writes_model=True,
        # 03.08: "±tol" got an address — the tag head is checked in the
        # view's axes against the same 10 mm that was a literal in
        # _emit_tag.
        tolerances={"head_mm": 10.0},
    ),
    # text — a note (± leader) in in_view at view-space `at`; width_mm
    # (optional, TextNote.Width — the ONE per-instance sheet-space size Revit
    # exposes; font HEIGHT is TextNoteType-owned, not per-instance, so it is
    # NOT modeled here, see module docstring) is compiler-owned size-from-
    # intent via the resolved view's own Scale, read at RUNTIME from in_view
    # (docspace.view_scale_to_model_mm mirrors the SAME formula as a pure-
    # python proof/test helper — the compiler cannot know view_scale at
    # python-emit-time, only after the view is resolved in C#, exactly like
    # emit_view2d_to_xyz_cs never hardcodes a basis).
    OpSpec(
        name="create_text",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("at", "pt_view2d", required=True),
            ParamSpec("content", "str_long", required=True),
            ParamSpec("width_mm", "mm", min_val=1.0, max_val=5000.0),
            ParamSpec("text_type", "target_w"),
            ParamSpec("leader_to", "target_w",
                      ref_kinds=(ReferenceKind.ELEMENT,)),
        ),
        capability=(("create", "text_note"),),
        post=("text note exists in in_view at `at` ±tol (geometry); content "
              "matches verbatim (semantic) (re-read); when leader_to given, "
              "a leader exists, its endpoint matches the target's in-view "
              "bounding-box center, and leader_to is visible in in_view "
              "(VIEW-BINDING LAW)"),
        writes_model=True,
        # 03.08: "±tol" of the insertion point — the same 5 mm as in
        # _emit_text.
        # NAMED HONESTLY: the width tolerance (`__wmm * 0.15 + 5.0`) is NOT
        # brought in here — it is a relative correction for Revit's fitting
        # to content, not a `post` promise; bringing it in would mean
        # passing off as contract something the contract does not promise.
        tolerances={"location_mm": 5.0},
    ),
    # ── FILL REGION (09.08.2026): 2D contour hatching living ON THE VIEW ──────
    #
    # `FilledRegion.Create(Document, ElementId typeId, ElementId viewId,
    # IList<CurveLoop>)` — 6/6 against the reference assemblies. The first
    # operation where TWO sub-languages meet: CONTOUR gives the shape,
    # docspace gives the space.
    #
    # THE CONTOUR LIES IN THE VIEW'S PLANE, NOT IN THE MODEL'S XY, and this
    # is not a stylistic choice: RevitAPI.xml says of the call itself that
    # the loop must lie "in a plane parallel to the view's detail sketch
    # plane," meaning the ready-made `contour.emit_loop_cs` (it assembles the
    # loop at z=0 in world XY) is correct ONLY on views with a horizontal
    # sketch plane — on plans — and is rejected by Revit on any section or
    # elevation. "Grounding and checking come for free" was confirmed:
    # `ground.py` drops ANY `region` kind, and all the shape laws (closure,
    # self-intersections, arcs, holes inside) work here without a single
    # line of code. But the ASSEMBLY of the loop did not come for free — it
    # went through the view's basis, using the same expression by which
    # `create_text`/`create_tag` place their one point.
    #
    # THE CONSEQUENCE, WHICH MUST BE A REFUSAL AND NOT A FOOTNOTE: contour
    # points are [u,v] mm of VIEW SPACE. An address from the grid (`at_grid`)
    # gives a MODEL-space coordinate pair, and on a plan with a world basis
    # these numbers coincide, while on a section they silently mean a
    # different place. Exactly the confusion of spaces that docspace.py
    # exists to make INEXPRESSIBLE, which is why the emitter refuses on
    # `at_grid` inside `contour`.
    OpSpec(
        name="create_filled_region",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("contour", "region", required=True),
            ParamSpec("type", "sel"),
        ),
        capability=(("create", "geometry"),),
        # WHAT IS NOT PROMISED HERE, AND THIS IS A GENRE BOUNDARY, NOT A
        # SHORTCOMING: the 2D fill region asserts NOTHING about the
        # building. It does not prove that what it colors is what lies
        # beneath it (there is no "fill region ↔ element beneath it" link in
        # the API at all), it does not prove landing inside the view's crop
        # region (a fill region outside the crop box exists and passes all
        # checks while staying invisible on the sheet — but the crop region
        # gets moved, and refusing on it would mean forbidding something
        # legitimate), and it does not prove the APPEARANCE of the hatching:
        # pattern, color, and line weight belong to `FilledRegionType`, so
        # what is proven is the type's id, not what that type draws.
        post=("filled region exists on in_view (materialize); OwnerViewId == "
              "in_view (topology); GetTypeId == the resolved filled region "
              "type (semantic); GetBoundaries reproduces the authored loops "
              "in view space — loop count, curve count, and every authored "
              "edge matched exactly once by its endpoints and its mid-point "
              "±1.0 (geometry)"),
        writes_model=True,
        grounded=(("type", "filled_region_types", False),),
        # THE TOLERANCE IS DERIVED, NOT ASSIGNED: 1.0 mm is
        # `contour._EDGE_TOL`, i.e. the sub-language's OWN resolution on
        # points. CONTOUR statically rejects an edge shorter than that as
        # zero-length, meaning that for this language two points closer than
        # 1 mm are ONE point. A witness that distinguishes what the language
        # itself cannot distinguish would demand of Revit a precision it
        # does not itself express. A lock on equality sits in the tests.
        tolerances={"boundary_mm": 1.0},
    ),
]
