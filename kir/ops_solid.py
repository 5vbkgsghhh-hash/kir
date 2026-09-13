"""ops_solid — PARAMETRIC BODY (GeometryCreationUtilities → DirectShape).

Registry module — operations are added HERE, not in spec.py. The emitter
lives in solid_emit.py (a paired file, like ops_shape.py + shape_emit.py
for the mesh wave).

═══ WHY THIS WAVE, IF THE MESH ALREADY EXISTS ══════════════════════════════

The header of ops_shape.py left a note: «SOLID. TessellatedShapeBuilderTarget.Solid
compiles, but requires a closed body… Solid is a separate wave with its own LIVE
MEASUREMENT, not a flag here». This is that wave — and the door turned out to be a
different one: the body is built not by the tessellator but by SEVEN
`GeometryCreationUtilities` FACTORIES, and they have a property that a mesh
fundamentally does not have.

THE BOUNDARY OF THE MEASUREMENT, STATED UP FRONT so it does not need to be
hunted for: everything below is measured by COMPILATION against real
2021-2026 assemblies, not by live Revit. There is NOT A SINGLE live run for
these two ops (they sit in `tool_doc.UNPROVEN`), and compiles ≠ will build
— the same law recorded in the shape_emit.py header.

**THE EXTRUSION VOLUME IS COMPUTED ANALYTICALLY AT COMPILE TIME.** The
CONTOUR profile is lowered into a closed list of edges, Green's theorem
over the boundary gives the area EXACTLY (with arcs — as a closed form,
not by sampling), the prism's volume = area × height. The witness compares
this number against `Solid.Volume`, read FROM THE BUILT element. A mesh
has nothing like this: there, the bounding box and triangle count are
checked — i.e. exactly what we ourselves sent, recomputed. Here, a
QUANTITY that was not present in the input in any form is checked.

A solid of revolution gives the same through the first Pappus–Guldinus
theorem, or more precisely, through its derivation: the volume of a solid
obtained by rotating a planar region around an axis by an angle θ equals
θ·∬x dA (cylindrical coordinates, Fubini's theorem). The moment ∬x dA is,
again, a boundary integral, again a closed form (contour.py).

═══ API MEASUREMENT (live Roslyn :52412 against real assemblies, 2021-2026, 09.08)

Not a single discrepancy between versions: EVERY member named below
compiles on all six, so both ops have NO VERSION AXIS at all — a rarity
for this package (floors, roofs, ceilings, and tags have one). Pinned by
the test `test_solid.py::SixVersionsEmitTheSameSurface`: the emission must
match byte for byte on 2021-2026, otherwise someone introduced a branch
without saying so.

  CreateExtrusionGeometry(IList<CurveLoop>, XYZ, double)          → 6/6
  CreateExtrusionGeometry(..., SolidOptions)                      → 6/6
  CreateRevolvedGeometry(Frame, IList<CurveLoop>, double, double) → 6/6
  CreateRevolvedGeometry(..., SolidOptions)                       → 6/6
  CreateSweptGeometry(CurveLoop, int, double, IList<CurveLoop>)   → 6/6
  CreateBlendGeometry(CurveLoop, CurveLoop, ICollection<VertexPair>) → 6/6
  CreateSweptBlendGeometry(Curve, IList<double>, IList<CurveLoop>,
                           IList<ICollection<VertexPair>>)        → 6/6
  CreateLoftGeometry(IList<CurveLoop>, SolidOptions)              → 6/6
  CreateFixedReferenceSweptGeometry(CurveLoop, int, double,
                                    IList<CurveLoop>, XYZ)        → 6/6
  Solid.{Volume,SurfaceArea,Faces,Edges,GetBoundingBox,ComputeCentroid} → 6/6
  PlanarFace.{FaceNormal,Area}, Face.GetEdgesAsCurveLoops         → 6/6
  CurveLoop.CreateViaTransform / Transform.Identity+basis setters → 6/6
  Frame(XYZ, XYZ, XYZ, XYZ)                                       → 6/6
  DirectShape.SetShape(IList<GeometryObject>)                     → 6/6
  doc.Application.{VertexTolerance,ShortCurveTolerance}           → 6/6
  DirectShapeType.Create(doc, string, ElementId) + SetTypeId      → 6/6
  FreeFormElement.Create(doc, Solid)                              → 6/6 (compiles!)

  CreateSweptBlendGeometry(..., SolidOptions) as the 4th argument → 0/6
      CS1503 cannot convert from 'SolidOptions' to
      'IList<ICollection<VertexPair>>'  ← MEMORY: the overload does NOT look like this
  Autodesk.Revit.DB.IFC.ExporterIFCUtils                          → 0/6
      CS0234 not in the reference closure — we have NO ready-made
      "compute the area of CurveLoops", so the area is computed by our own
      closed form, not borrowed from the exporter

TWO ELEMENT FACTORIES, BOTH REFUSED WITH A REASON:

* `FreeFormElement.Create` COMPILES on all six and is still NOT USED —
  exactly the class of thing shape_emit.py warns about ("compiles is not
  the same as will build"): RevitAPI.xml on all six versions spells out,
  verbatim, the throw condition — *«document is not a family document, nor
  a document editing an in-place family»*. KIR writes into a PROJECT
  document, so the call is guaranteed to throw. A refusal by documentation,
  not by a live crash. WHAT THIS OPENS UP: a wave of its own for family
  editing; in a project document — nothing.

* `DirectShapeType.Create(doc, name, categoryId)` + `DirectShape.SetTypeId`
  compiles 6/6 and would have given the body a TYPE, i.e. removed half of
  the "honest label". It is refused not out of caution but because it
  breaks the COUNTING LAYER: one op would create TWO elements (the type
  and the instance), while the §18.1 census derives the expectation from
  category×level for ONE element per op (`acceptance._category_of_op`),
  and the type element would fall into the same category cell. L2
  acceptance would declare a discrepancy on every body. WHAT THIS OPENS
  UP: a `_OP_DERIVED` branch in acceptance.py declaring a derived type
  element — and then typing bodies would become a separate wave with an
  honest type-identity witness. Introducing it along the way would mean
  breaking acceptance for the sake of one field in the project tree.

═══ HONEST LABEL — THE SAME AS FOR THE MESH ════════════════════════════════

A DirectShape with a solid inside is still GEOMETRY WITHOUT BIM MEANING: no
type, no parameters, a human cannot edit it. Therefore:

  * the capability cell is («create», «geometry»), NOT («create»,
    «element»);
  * `grounded` is EMPTY, and that is meaningful (there is nothing to
    substitute);
  * the categories are the SAME closed table `DIRECTSHAPE_CATEGORIES` from
    ops_shape.py, by IMPORT, not by copy. A body in the walls category
    would read as a wall in every filter and every schedule, without being
    anything a wall is. KIR has real create_wall/create_floor/create_roof
    — `IMPERSONATION_ROUTES` names them by name, and as of 09.08 this
    table is finally READ by the refusal (before that day it had ZERO
    importers: it described a law that nobody spoke).

THESE OPS MUST NOT BE USED TO MAKE UP FOR WALLS/FLOORS/ROOFS. The
temptation here is stronger than for the mesh: an extruded contour LOOKS
like a slab and has the correct volume. It still has neither layers, nor
joins, nor openings, nor a schedule entry.

═══ WHAT IS NOT HERE AND WHY (five factories out of seven) ═════════════════

The law of the wave: A FACTORY SHIPS ONLY WITH AN HONEST WITNESS.
Extrusion and revolution have a closed form for the volume; the other five
do NOT, and signing off with a bounding box that "we built what you asked
for" would mean putting in a check that cannot fail on a swapped shape.

  * `CreateSweptGeometry` / `CreateFixedReferenceSweptGeometry` — the
    volume of a sweep along a NON-PLANAR path has no closed form: Pappus's
    theorem holds only when the path is planar and does not intersect the
    region, and RevitAPI.xml explicitly permits "The path may be planar or
    non-planar". Computing the volume by sampling the path would mean
    introducing our own error into the witness and baking it into the
    tolerance — exactly the "tolerance was invented" defect this compiler
    catches. WHAT THIS OPENS UP: restricting the path to a single plane +
    proof of non-intersection, then V = A·L(centroid) — a separate wave.
  * `CreateBlendGeometry` / `CreateSweptBlendGeometry` / `CreateLoftGeometry`
    — the surface between profiles is built by Revit ITSELF ("blending
    smoothly", "the function chooses vertex connections"), i.e. the shape
    of the lateral surface is not uniquely determined by the input. None
    of the three has a closed form for the volume; linear interpolation
    (Simpson's prismatoid) is exact only for a ruled lateral surface, and
    Revit does not promise it will be one. WHAT THIS OPENS UP: a live
    measurement of `Solid.Volume` against the prismatoid formula on a
    dozen pairs of profiles — if it converges, the witness is honest.

═══ TOLERANCE: DERIVED FROM REVIT ITSELF, NOT ASSIGNED ═════════════════════

`tolerances` is EMPTY, and that is not a gap. The tolerance number here
cannot be a registry constant by construction: it depends on the size of
the body. The witness computes it IN EMISSION from two derived quantities:

  δ = MM(doc.Application.VertexTolerance) + <coordinate emission quantum>

`VertexTolerance` is Revit's own number: "Two points within this distance
are considered coincident". RevitAPI.xml warns, in the same place: *«Do
not use this value to set the distance between two points»* — and we do
not use it to set distances, we use it to COMPARE, i.e. exactly as
intended. A body whose entire boundary lies within δ of the reference one
consists of points that Revit itself considers coincident; shifting the
boundary by δ changes the volume by no more than (surface area)·δ, and the
area by no more than (length of face boundaries)·δ. Hence two tolerances,
both DERIVED and both dependent on the geometry of the op.

The emission quantum is `contour.EMIT_COORD_QUANTUM_MM`: `emit_loop_cs`
prints coordinates with two decimal digits, so our own boundary already
differs from the ideal one by the size of this quantum, and adding it to δ
is mandatory.

THE BAN ON VACUOUSNESS (the law that "a check that cannot fail is worse
than none at all"). A derived tolerance can turn out larger than the
quantity being measured itself — for a sheet a millimeter thick, or an
opening the size of the tolerance. Then the witness formally exists but
cannot fail. Emission places a RUNTIME REFUSAL right next to it: if the
volume tolerance is not smaller than the volume of the smallest DECLARED
element of the profile (the profile itself, or the smallest opening) — the
op issues a named refusal instead of signing off. The threshold is not
invented: "tolerance ≥ quantity" is exactly the definition of vacuousness.

═══ WHAT AWAITS LIVE REVIT ══════════════════════════════════════════════════

RevitAPI.xml, `Solid.Volume`, verbatim and IDENTICAL on all six versions:
*«Revit attempts to compute the volume analytically, if possible. If an
analytical solution is not possible, it uses tessellated faces… The
calculated volume may be slightly underestimated or overestimated if
curved surfaces are present.»* The magnitude of this "slightly" is not
documented anywhere. Our tolerance models a SYMMETRIC perturbation of the
boundary — exactly what this sentence is talking about — so the volume
witness always ships.

`Solid.SurfaceArea`, in the same place: *«Will slightly underestimate if
curved surfaces are present»* — this is a SYSTEMATIC BIAS, and a bias is
not modeled by a boundary perturbation. So there is NO witness for the
total surface area here at all; in its place ships a witness for PLANAR
FACES (`PlanarFace.Area`), which never touches curved surfaces and is
therefore free of this caveat. This is not caution but the law of this
house: a witness signs off only on the axis it actually read.

The receipt carries the RAW PAIR (expectation and measurement, in
mm³/mm²) — the first live run thereby MEASURES the remainder, rather than
estimating it.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)
from kir.ops_shape import DIRECTSHAPE_CATEGORIES

#: Both ops put the body into a DirectShape, so their category set is ONE
#: and the SAME and is taken by import. A copy here would mean the ban on
#: passing a body off as a wall could be lifted in one file and go
#: unnoticed in the other.
SOLID_CATEGORIES = tuple(DIRECTSHAPE_CATEGORIES)

#: The extrusion/radius limit.
#:
#: 🔴 WAS 100.0 "FOR CONSISTENCY WITH THE PROFILE". LOWERED TO 1.0 BY A
#: MEASUREMENT ON 21.08.2026 — LIVE, NOT BY REASONING.
#:
#: The previous argument: "the same order of magnitude as
#: `contour._validate_shape` (shape side 100..500 000 mm): a body whose
#: height lives by different rules than its own profile is two coordinate
#: systems in one operation".
#:
#: The argument turned out to be wrong about the SUBJECT MATTER. The
#: extrusion height is not a side of the profile. A glass panel has a
#: profile of 1200×2100 (both sides much larger than 100 mm), and it has
#: EXACTLY ONE thin quantity — the height. Demanding of it a minimum
#: derived from the profile's sides means forbidding an entire class of
#: real things: glass, shelves, countertops, cladding panels.
#:
#: THE COST OF THE BAN IS MEASURED: an extraction of family recipes from a
#: real building — **55 shapes were rejected by the code
#: `height_out_of_bounds`, and ALL of them were below 100 mm**: 1 · 10 ·
#: 20 · 30 · 40 · 60 · 70 · 75 mm, maximum 76.2. Revit rejected NONE of
#: them — we did.
#:
#: MEASUREMENT ON LIVE REVIT (Project1, 2026, a sketch on a vertical
#: plane, profile 1200×2100):
#:
#:      1 mm  built · witness satisfied · volume 2 519 999.9999994
#:      3 mm  built · witness satisfied · volume 7 559 999.9999983
#:     10 mm  built · witness satisfied · volume 25 199 999.999999
#:     20 mm  built · witness satisfied · volume 50 399 999.999999
#:     50 mm  built · witness satisfied · volume 125 999 999.99999
#:     76 mm  built · witness satisfied · volume 191 520 000.00000
#:
#: WHY EXACTLY 1.0, AND NOT LOWER. Revit's short-curve threshold is 1/256
#: of a foot, i.e. ≈0.794 mm; below it an edge degenerates and the body
#: stops building. 1.0 mm lies ABOVE this limit with a margin of 1.26x and
#: is the smallest value BUILT live. Numbers below 1 mm were not checked
#: in this measurement — the threshold itself cut them off — and so
#: nothing is asserted about them here.
#:
#: WHAT REMAINS A DISCREPANCY, NAMED AS SUCH: the PROFILE side is still a
#: minimum of 100 mm (`contour.SHAPE_SIDE_MIN_MM`). This is not a
#: forgotten half of the fix: the profile is a flat figure, and a
#: degenerately narrow strip in it is almost always the author's slip, not
#: their intent. The height is a different quantity, and the decision
#: about it was made separately, by this very measurement.
MIN_EXTENT_MM = 1.0
MAX_EXTENT_MM = 500_000.0

OPS = [
    OpSpec(
            name="create_solid_extrusion",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # THE PROFILE IS OF KIND `region`, not its own format.
                # CONTOUR already knows rect/l/poly, arcs, openings, and
                # grid binding, and ground.py lowers ANY parameter of kind
                # `region` (the rule is addressed to the kind, not to the
                # op's name — 09.08). A dedicated profile format would be a
                # second home for the same laws.
                ParamSpec("profile", "region", required=True),
                # Height is the EXTRUSION DISTANCE along +Z. Direction is
                # not a parameter: a slanted prism has a closed-form volume
                # (A·d·|d̂·ẑ|), but its lateral faces stop being the
                # rectangles the tolerance is computed from, and the
                # end-face witness stops distinguishing an end face from a
                # side face by its normal. Slant is a separate wave with
                # its own derivation.
                ParamSpec("height_mm", "mm", required=True,
                          min_val=MIN_EXTENT_MM, max_val=MAX_EXTENT_MM),
                # The elevation of the profile plane. OPTIONAL and WITHOUT
                # A DEFAULT: absence means the Z=0 plane of the internal
                # origin, and emission then prints NOT A SINGLE transform
                # (absent stays absent).
                #
                # THERE IS NO LEVEL HERE DELIBERATELY: DirectShape has no
                # binding to a level, and a `level` selector would promise
                # a connection that does not exist in the built element —
                # the same lie as the wall category for the mesh, only
                # quieter.
                ParamSpec("base_z_mm", "mm",
                          min_val=-MAX_EXTENT_MM, max_val=MAX_EXTENT_MM),
                # THE SKETCH PLANE (21.08.2026) — OPTIONAL, WITHOUT A
                # DEFAULT, and MUTUALLY EXCLUSIVE with `base_z_mm`.
                # Absence means exactly today's behavior: the profile in
                # world XY, extrusion along +Z, and emission prints the
                # same bytes it printed before the wave.
                #
                # WHY — BY THE ARITHMETIC OF A REAL BUILDING, not "for the
                # sake of generality". The 20.08 extraction of recipes
                # rejected 73 shapes out of 283 with the code
                # `sketch_plane_not_horizontal`, and this is the LARGEST
                # refusal of the extraction. The shape of a window or door
                # lives on the FACE OF A WALL; as long as extrusion only
                # knows +Z, there is no way to say it.
                #
                # THIS DOES NOT OPEN UP SLANTED EXTRUSION, and the caveat
                # about `height_mm` above remains in force verbatim: the
                # body is still a RIGHT prism, only its axis is the
                # plane's normal, rather than +Z. An oblique prism (profile
                # in one plane, travel toward another side) remains just
                # as inexpressible as before — its side faces stop being
                # the rectangles the tolerance is derived from, and the
                # end-face witness stops distinguishing an end face from a
                # side face by its normal.
                ParamSpec("plane", "plane"),
                ParamSpec("category", "enum", required=True,
                          choices=SOLID_CATEGORIES),
                # The name is mandatory for the same reason as the mesh:
                # for an element without a type, the name is the only
                # thing that distinguishes it from a blob.
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            capability=(("create", "geometry"),),
            post=("solid direct shape exists (materialized or typed refusal); "
                  "built geometry holds exactly one solid (geometry); "
                  "solid volume == profile area * extrusion height, both "
                  "closed-form at compile time (geometry); "
                  "planar cap area == twice the profile area (geometry); "
                  "bbox extents == profile bbox by base_z..base_z+height in "
                  "XYZ, or the support hull of the profile carried onto the "
                  "declared plane when one is given (geometry)"),
            writes_model=True,
            # EMPTY BY CONSTRUCTION: DirectShape has no type — there is
            # nothing to ground.
            grounded=(),
            # EMPTY BY CONSTRUCTION: the tolerance here is a function of
            # the op's geometry and Revit's own number, not a constant.
            # The analysis is in the header.
            tolerances={},
        ),
    OpSpec(
            name="create_solid_blend",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # TWO PROFILES, BOTH OF KIND `region`. A second home for
                # the laws of shape is not introduced: CONTOUR already
                # knows rect/l/poly, arcs, openings, and grid binding, and
                # `ground.py` lowers EVERY parameter of kind `region` (the
                # rule is addressed to the kind, not to the op's name).
                ParamSpec("profile", "region", required=True),
                ParamSpec("profile_top", "region", required=True),
                # The distance between the profile planes. The same range
                # as the extrusion height: a body whose transition lives
                # by different rules than a prism is two measurement
                # systems in one wave.
                ParamSpec("height_mm", "mm", required=True,
                          min_val=MIN_EXTENT_MM, max_val=MAX_EXTENT_MM),
                ParamSpec("base_z_mm", "mm",
                          min_val=-MAX_EXTENT_MM, max_val=MAX_EXTENT_MM),
                # THE SAME PLANE AND FOR THE SAME REASON as extrusion: both
                # blend profiles lie in PARALLEL planes, and the distance
                # between them is measured along the normal. One frame
                # plus a height is a limitation of the CURRENT KIR, not of
                # the Revit factory: `CreateBlendGeometry` allows
                # non-parallel planes (RevitAPI.xml 2023, secondLoop; the
                # official 2026 API). A separate frame for the upper
                # profile is not yet in this contract.
                ParamSpec("plane", "plane"),
                ParamSpec("category", "enum", required=True,
                          choices=SOLID_CATEGORIES),
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            capability=(("create", "geometry"),),
            # 🔴 THERE IS NO VOLUME IN THIS LIST, AND THIS IS A NAMED
            # ABSENCE, NOT FORGETFULNESS. The lateral surface between the
            # profiles is built by Revit ITSELF according to an
            # undocumented smoothing rule, so Simpson's prismatoid is
            # exact only for a ruled lateral surface, which Revit does not
            # promise. What is proven is what is declared: the end faces
            # (i.e. the profiles) and their position on the boundary of
            # the built body.
            post=("blend direct shape exists (materialized or typed refusal); "
                  "built geometry holds exactly one solid (geometry); "
                  "planar cap area == bottom profile area plus top profile "
                  "area, both closed-form at compile time (geometry); "
                  "every declared profile vertex lies on the built solid "
                  "boundary within the derived tolerance (geometry); "
                  "bbox extents contain the union of both profile bboxes over "
                  "base_z..base_z+height, outward-tolerant because the lateral "
                  "surface is chosen by Revit (geometry)"),
            writes_model=True,
            grounded=(),
            tolerances={},
        ),
    # ── SWEEP (20.08.2026). Two Revit factories under ONE op ────────────
    #
    # WHY ONE OP, NOT TWO. `CreateSweptGeometry` and
    # `CreateFixedReferenceSweptGeometry` differ in EXACTLY one thing: how
    # the profile's rotation around the path's axis is set. Everything
    # else — the path, the anchor point, the profile, the preconditions,
    # the witness — is identical between them down to the letter. Two ops
    # would mean two copies of one law, and copies drift apart silently;
    # `variety` names the difference in one word, as with `create_railing`
    # (path|hosted).
    #
    # WHAT CHANGED AGAINST THE REFUSAL IN THIS FILE'S HEADER. It says
    # there: «a sweep's volume has no closed form… WHAT THIS OPENS UP:
    # restricting the path + proof of non-intersection, then
    # V = A·L(centroid)». It opened up — and more than promised: the
    # path's planarity turned out not to be needed at all. It is enough to
    # place the profile's CENTROID on the path, and then the profile's
    # first moment is zero in every direction, the whisker correction at
    # every node vanishes to zero, and V = A·L becomes exact for ANY
    # spatial polyline. The full derivation is in the `sweep_path.py`
    # header.
    OpSpec(
            name="create_solid_sweep",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # THE ROTATION KIND is a closed set of TWO overloads, not
                # of tastes:
                #   frame            — Revit chooses the rotation (minimal
                #                      twist along the path);
                #   fixed_reference  — the profile line perpendicular to
                #                      `ref_dir` stays perpendicular to it
                #                      along the whole path. The example
                #                      from RevitAPI.xml, verbatim — a
                #                      railing whose top must stay
                #                      horizontal.
                ParamSpec("variety", "enum", required=True,
                          choices=("frame", "fixed_reference")),
                # The profile in ITS OWN coordinates. Which POINT of it
                # travels along the path is named by `anchor_uv_mm` below;
                # by default — the centroid.
                ParamSpec("profile", "region", required=True),
                # 🔴 OFFSETTING THE PROFILE FROM THE PATH (21.08.2026) — THE
                # PROFILE POINT THAT TRAVELS ALONG THE PATH, in its own
                # (u, v).
                #
                # WHY IT WAS INTRODUCED. Before this date the op placed the
                # CENTROID on the path, and the profile had no other place
                # to go. A measurement over 110 families of a real
                # building: for 55 sweeps out of 55, the centroid does NOT
                # lie on the path (closest 10.3 mm, farthest 505 mm). That
                # is, the op expressed NOT ONE family sweep, and a
                # cornice, a drip edge, and a door frame are exactly an
                # offset profile.
                #
                # WHAT THIS COST THE LANGUAGE. Exactly one term in the
                # volume law: `V = A·(L + Σ whisker corrections)`, the
                # derivation and measurement are in the `sweep_path.py`
                # header. The law `V = A·L` is not repealed, it became a
                # special case at zero offset.
                #
                # WHY A PROFILE POINT, AND NOT "OFFSET FROM THE PATH". Both
                # notations are arithmetically equivalent and NOT
                # equivalent when read back: Revit returns the profile
                # sketch in a frame whose origin LIES ON THE PATH
                # (measured: 49 of 49, distance exactly 0), so this point
                # is known to the extractor directly, whereas the offset
                # would have to be computed by subtracting the centroid —
                # i.e. it would introduce a second carrier of the same
                # fact.
                #
                # THE DEFAULT IS THE CENTROID, and this is not a "safe
                # value" but the earlier law: at zero offset the
                # correction is identically zero, for ANY rotation.
                ParamSpec("anchor_uv_mm", "pt_xy"),
                # The path is a SPATIAL POLYLINE. There are no arcs in the
                # path in v1, and this is not a loss of expressiveness: a
                # helix, an arc, and a spiral are built by a PYTHON LOOP on
                # the author's side, and the volume stays exact for any
                # number of segments (V = A·L does not know anything about
                # the path's shape at all). The `path3` kind already
                # rejects coincident points and segments shorter than a
                # millimeter — a second such check is not introduced here.
                ParamSpec("path_mm", "path3", required=True),
                # THE REFERENCE DIRECTION IS MANDATORY, and it deliberately
                # has NO DEFAULT. The default [0,0,1] looks harmless right
                # up until the first vertical path, where it is collinear
                # with the travel direction and the profile plane is not
                # determined by it. A choice the author does not see is,
                # in this house, indistinguishable from `.FirstOrDefault()`.
                #
                # 🔴 THE `pt_xyz` KIND HERE IS A LIE, AND IT IS A LIVE ONE
                # (measured 21.08.2026). This is a DIRECTION, not a point
                # in millimeters, and the reverse-pass printer treats it
                # like a point:
                #     `program_source._round_mm`  [0.7071, 0.7071, 0] -> [1, 1, 0]
                #     `program_source._shift`     [-1, 0, 0] -> [-1001, -500, 0]
                # Both values LOOK LEGITIMATE and crash nowhere — exactly
                # the fourth of the four homes of the value kind that "is
                # never recalled" (`plane.py`, header). There it was closed
                # off for `normal`/`x_dir` — but BY THE NAMES OF NESTED
                # KEYS (`FREE_KEYS`), and a top-level parameter cannot be
                # protected that way.
                #
                # WHY IT IS NOT FIXED HERE, AND WHAT WOULD FIX IT. The real
                # cure is a `dir_xyz` KIND alongside `pt_xyz`: a
                # dimensionless vector that is not rounded to a millimeter
                # and not shifted into a local frame. This is a
                # coordination-level change (`spec.PARAM_KINDS` plus three
                # independent locks: `schema_gen`, `authoring_validation`,
                # the registry import), and two more fields live by the
                # same lie — `ops_mass.create_*.face_normal` and `ref_dir`
                # in `ops_authoring`. A patch by field NAME in
                # `program_source` would introduce a second carrier of the
                # same knowledge — the named-defect class of this tree,
                # bought four times over in August.
                #
                # WHY THIS IS NOT ON FIRE TODAY: the reverse pass of this
                # op is `CAPTURE_GAP` (`reverse_contract`), and family
                # recipes are not yet wired into program printing. The
                # value will go bad on the day they are.
                ParamSpec("ref_dir", "dir_xyz", required=True),
                # 🔴 THERE IS NO `plane` HERE, AND THIS IS A NAMED ABSENCE
                # (21.08.2026). The plane of a sweep's profile is NOT
                # FREE: it is perpendicular to the path at the anchor
                # point, and the rotation around it is already set by
                # `variety` and `ref_dir`. Giving a `plane` here would mean
                # introducing a SECOND carrier of the same frame — and the
                # very first discrepancy between them, Revit would resolve
                # silently, in its own favor.
                #
                # THE CONSEQUENCE FOR EXTRACTION, AND IT IS THE OPPOSITE OF
                # WHAT ONE WOULD EXPECT: for a family sweep, the profile
                # sketch is almost NEVER horizontal — it is perpendicular
                # to the path. So the horizontality check that stood in
                # the extractor across ALL four kinds was rejecting sweeps
                # that this op already expresses today. The refusal was
                # FALSE, and it is lifted in the extractor, not here.
                ParamSpec("category", "enum", required=True,
                          choices=SOLID_CATEGORIES),
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            capability=(("create", "geometry"),),
            # THERE IS A VOLUME HERE — unlike the blend, the loft, and the
            # swept blend. The difference is not boldness but the fact
            # that the shape of a sweep is DETERMINED by the input: Revit
            # does not choose the lateral surface, it drives the given
            # profile along the given path. The only thing it chooses for
            # `variety="frame"` is the profile's rotation around the axis,
            # and the volume does not depend on the rotation (the Jacobian
            # does not see it).
            post=("swept direct shape exists (materialized or typed refusal); "
                  "built geometry holds exactly one solid (geometry); "
                  "solid volume == profile area times the path length plus the "
                  "closed-form miter correction of the centroid offset, exact "
                  "at compile time and zero-correction when the anchor is the "
                  "centroid (geometry); "
                  "bbox extents lie inside the path bbox grown by the profile "
                  "circumradius ABOUT THE ANCHOR, one-sided because the roll "
                  "of the profile is chosen by Revit for variety=frame "
                  "(geometry)"),
            writes_model=True,
            grounded=(),
            tolerances={},
        ),
    OpSpec(
            name="create_solid_revolve",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # The profile is read IN AXIAL COORDINATES: the contour's x
                # is the RADIUS from the axis, the contour's y is the
                # elevation along the axis. This is what Revit itself
                # requires («The loops must lie in the xz coordinate plane
                # of the input coordinate frame… on the "right" side of the
                # z axis (where x >= 0)»), and there is no need to retrain
                # the author onto a third coordinate system for the sake of
                # one operation.
                ParamSpec("profile", "region", required=True),
                # The axis is a VERTICAL line through this plan point.
                # There is no slanted axis in v1: it would have to be
                # given by a second vector, and a profile defined in that
                # axis's plane would become unverifiable by eye. The
                # bounding-box witness for the annular sector is derived
                # specifically for a vertical axis.
                ParamSpec("axis_xy_mm", "pt_xy", required=True),
                # 🔴 THERE IS NO `plane` HERE FOR THE SAME REASON AS THE
                # SWEEP. The plane of the revolution's profile must
                # CONTAIN the axis, i.e. it is entirely derived from
                # `axis_xy_mm` (this is exactly the XZ frame that
                # `solid_emit` builds as a `Transform` since 19.08). There
                # is no free degree here — there is a SLANTED AXIS, and
                # that is a different parameter and a different wave
                # (caveat below).
                #
                # And the same false refusal as the sweep: the revolution
                # sketch is VERTICAL by construction, so the horizontality
                # check in the extractor was rejecting legitimate solids
                # of revolution.
                ParamSpec("base_z_mm", "mm",
                          min_val=-MAX_EXTENT_MM, max_val=MAX_EXTENT_MM),
                # The rotation angle, in degrees. ALWAYS measured from the
                # world +X axis: there is no starting-angle parameter, and
                # this is not a default but the absence of a degree of
                # freedom — the frame is set by us, so 0 is a definition,
                # not a guess made on the author's behalf.
                ParamSpec("sweep_deg", "num", required=True,
                          min_val=1, max_val=360),
                ParamSpec("category", "enum", required=True,
                          choices=SOLID_CATEGORIES),
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            capability=(("create", "geometry"),),
            post=("revolved direct shape exists (materialized or typed "
                  "refusal); "
                  "built geometry holds exactly one solid (geometry); "
                  "solid volume == sweep radians * profile first moment about "
                  "the axis, closed-form at compile time (geometry); "
                  "planar cap area == twice the profile area for a sector and "
                  "zero for a full turn (geometry); "
                  "bbox extents == the swept annular sector of the profile in "
                  "XYZ (geometry)"),
            writes_model=True,
            grounded=(),
            tolerances={},
        ),
]
