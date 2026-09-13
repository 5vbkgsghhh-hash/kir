"""ops_mass — CONCEPTUAL MASS: the only door from it into REAL BIM.

Registry module — operations are added HERE, not in spec.py. The emitter
lives in mass_emit.py (a companion file, like ops_sweep.py + sweep_emit.py
for the profile wave).

═══ THE MAIN MEASUREMENT OF THIS WAVE: A DOOR, NOT A ROOM ═══════════════════

The 08-09 census called the "free-form shapes and masses" family nearly
blind (2 of 12) and left a hypothesis: six mass-form factories,
`DividedSurface`, `DividedPath`. A compilation measurement against the real
2021-2026 assemblies (live Roslyn :52412, 08-10) did NOT confirm this
hypothesis, and the discrepancy is not a detail — it is the whole answer.

THE SIX MASS-FORM FACTORIES ARE UNREACHABLE NOT BY A CONDITION INSIDE THE
CALL, BUT BY THE DOOR ITSELF. All six live ONLY on
`Autodesk.Revit.Creation.FamilyItemFactory`, i.e. on `doc.FamilyCreate`, and
none on `doc.Create` (CS1061 on all six):

  doc.Create.NewExtrusionForm / NewRevolveForms / NewSweptBlendForm /
  NewLoftForm / NewFormByThickenSingleSurface / NewFormByCap   → 0/6  CS1061
  doc.FamilyCreate.<the same six>                              → exists (CS7036)
  doc.Create.NewSweepForm AND doc.FamilyCreate.NewSweepForm    → 0/6  CS1061
      ← MEMORY: this member does NOT EXIST AT ALL; the swept form is NewSweptBlendForm

And the accessor `Document.FamilyCreate` itself is documented verbatim and
IDENTICALLY across ALL SIX RevitAPI.xml files (each one re-read
individually, 2021-2026, not just the two endpoints: an instrument covering
part of the range is more dangerous than none at all):
*«Thrown when the current document is project document»*. That is, the
refusal here is STRONGER than for `FreeFormElement.Create` (there the
condition is named inside the method — "document is not a family
document"): for mass forms, the DOOR ITSELF throws, before any argument. KIR
writes into a PROJECT document, so the six factories are unreachable by
construction, not by an unfinished feature. WHAT THIS OPENS UP: its own wave
of family editing; inside a project document — nothing.

The upshot on the denominator, and it matters more than any single line.
THIS WAVE DID NOT SEE THE EXACT COMPOSITION OF THOSE TWELVE: there is no
census file in the tree, and passing off our own reconstruction as its list
would be exactly the kind of unpaid-for precision this codebase catches in
itself. There is therefore one checkable claim, and it has been measured:
**seven entries of this family are unreachable from a project document BY
CONSTRUCTION** — the six shape factories plus `FreeFormElement` — and the
eighth, `NewSweepForm`, does not exist in any of the six assemblies. So "2
of 12" as an estimate of the GAP overstates the work that can be done at
all: most of the denominator is someone else's rooms, not our blind spot.

═══ API MEASUREMENT (live Roslyn :52412 against the 2021-2026 assemblies, 08-10) ═══

  FaceWall.Create(Document, ElementId, WallLocationLine, Reference)   → 6/6
  FaceWall.IsValidFaceReferenceForFaceWall(Document, Reference)       → 6/6
  FaceWall.IsWallTypeValidForFaceWall(Document, ElementId)            → 6/6
  HostObjectUtils.GetSideFaces(FaceWall, ShellLayerType.Exterior)     → 6/6
  PlanarFace.{FaceNormal, Area, Origin} / Face.GetEdgesAsCurveLoops   → 6/6
  WallType.Width / doc.Application.VertexTolerance                    → 6/6
  WallLocationLine — all six members                                  → 6/6
  BuiltInParameter.HOST_AREA_COMPUTED                                 → 6/6
  DividedSurface.{Create, CanBeDivided, HostReference, GetGridNodeUV} → 6/6
  DividedPath.{Create, NumberOfPoints, TotalPathLength}               → 6/6
  MassInstanceUtils.{AddMassLevelDataToMassInstance, GetGrossFloorArea,
                     GetGrossSurfaceArea, GetGrossVolume}             → 6/6

  FaceWall — NOT a Wall                                     → 0/6  CS0029
      MEMORY: a "face wall" does not give you a `Wall`. It is a
      `HostObject`, so it has no `LocationCurve` at all, and its faces are
      read via HostObjectUtils.
  FaceWall.WallType                                         → 0/6  CS1061
      ← MEMORY: the type is obtained as `doc.GetElement(GetTypeId()) as WallType`
  MassLevelData.GetMassFloorArea / GetMassGrossVolume / … → 0/6  CS1061
      ← MEMORY: a "mass level" itself has NOT A SINGLE geometric getter;
      of its members, only `LevelId` remains. Areas and volume live on
      `MassInstanceUtils` and belong to the MASS AS A WHOLE, not to the level.
  MassZone / MassEnergyAnalyticalModel (types)              → 3/6  CS0246
      only 2021-2023; these types are NOT in the 2024-2026 assemblies.
  doc.Create.NewFloorFaceBased / NewRoofFaceBased           → 0/6  CS1061
      confirms what was measured earlier: face-based floors and roofs are
      absent from the API.

═══ WHAT WAS TAKEN, AND WHY EXACTLY THIS ═══════════════════════════════════

`FaceWall.Create` is the ONLY factory in this whole chapter for which
RevitAPI.xml names the throw condition as *«document is not a project
document»* — verbatim and identically across all six versions, checked
against each one. This is the EXACT INVERSE of the refusal for mass forms
and `FreeFormElement`: it requires exactly the document KIR writes into.

And it is the only one that turns a free-form shape into a REAL element:
the result has a type, layers, an area in the schedule — unlike a
DirectShape, about which the solids wave and the mesh wave honestly write
"geometry without BIM meaning." The "mass → building" road in the API
consists of three moves, and after the measurement above, two remain: a
face wall (here) and a face-based curtain system (`NewCurtainSystem2`, see
below); there is no face-based floor or roof at all.

═══ WHAT IS NOT HERE, AND WHY (every reason is a measurement, not caution) ═══

* `DividedSurface.Create` COMPILES 6/6, and there is something to name a
  face with (the selector's second stage, `faceref.py`). Not taken because
  of the WITNESS: its entire readable-back surface layer —
  `NumberOfUGridlines`, `NumberOfVGridlines`, `USpacingRule`, `VSpacingRule`,
  `AllGridRotation` — is the DIVISION RULES, i.e. exactly what the author
  specified; the node values themselves (`GetGridNodeUV`,
  `GetGridNodeLocation`) lie ON THE HOST FACE BY CONSTRUCTION and therefore
  cannot diverge from anything the program is able to declare. The witness
  would come out as a recomputation of its own input — a forbidden kind.
  WHAT THIS OPENS UP: a PATTERN operation (the divided surface's tile kind
  — `TilePattern` or a curtain-panel `FamilySymbol`, verbatim per
  RevitAPI.xml); then the built panels are real elements with their own
  census, and the witness appears on them, not on the grid.

* `DividedPath.Create` compiles 6/6 and was NOT taken because of the
  REFERENCE: both overloads require an `IList<Reference>` TO CURVES OR
  EDGES ("Not all curve references in curveReferences represent a curve or
  an edge"), while the frozen dialect's second stage names a FACE, not an
  EDGE — this has already been written down by the profile wave
  (`ops_sweep.py`, `sweep_emit.py`) and is not reopened here. Introducing a
  third second-stage kind along the way would mean writing a second
  mechanism next to the existing one. WHAT THIS OPENS UP: an `edge` kind for
  the selector's second stage — a separate wave, which already has a ready
  cardinality law.

* `MassInstanceUtils.AddMassLevelDataToMassInstance` (a "mass level")
  compiles 6/6 and works in a PROJECT document — the only candidate in this
  chapter that passed the document test alongside `FaceWall`. Not taken
  because of the WITNESS, and this is a MEASUREMENT, not caution: the
  created `MassLevelData` has NOT A SINGLE geometric getter (every
  `GetMass*Area`/`GetMass*Volume` gives CS1061 on all six), and the only
  member left is `LevelId` — exactly the level we passed in ourselves. The
  witness would be reading its own input. Areas exist on the MASS AS A
  WHOLE (`GetGrossFloorArea`), but their value is derived from the mass's
  geometry, which the program did not author, so there is no expectation
  for it in any form. WHAT THIS OPENS UP: reading — these three getters
  belong in the `query_*` family, where no witness is needed at all.

* `NewCurtainSystem2(ReferenceArray, CurtainSystemType)` compiles 6/6 on
  `doc.Create` (a project document) and remains NOT TAKEN HERE because of
  the cardinality layer: it returns an `ICollection<ElementId>`, not an
  element (measured, CS0266), and RevitAPI.xml explains why — *«The number
  of CurtainSystems will be equal to the number of masses and generic
  models»*, that is, REVIT decides the number of created elements from the
  composition of faces, not the op. Census §18.1 derives its expectation
  from "one element per op." WHAT THIS OPENS UP: either the same
  `_OP_DERIVED` branch by which the solids wave deferred
  `DirectShapeType.Create`, OR a restriction to "all faces of a single
  host" — then there is exactly one element and the branch is unneeded. The
  second is cheaper and is done together with acceptance, not bypassed.

* `FreeFormElement.Create` and `DirectShapeType.Create` are decisions of
  the solids wave (`ops_solid.py`), and are NOT reopened here.

═══ WITNESS: AN HONEST LABEL FOR ITS STRENGTH ═══════════════════════════════

The solids wave has the strongest witness in the project: the volume is
computed ANALYTICALLY at build time and checked against the built element.
THERE IS NO SUCH QUANTITY HERE, and this has to be said plainly, not
disguised behind a long list of checks: the shape of a face wall is set by
the FACE OF A FOREIGN ELEMENT, which the program did not author, so neither
its area nor its volume exists in closed form, as a matter of principle.

What the witness therefore signs off on — and each item reads the RESULT:

  1. the built element's type == the one resolved before the effect
     (topology, exact);
  2. the built wall has EXACTLY ONE exterior face, co-directional with the
     named mass face (geometry). The check is EXACT, with not a single
     tolerance of its own: parallelism via the native
     `XYZ.CrossProduct(...).IsZeroLength()`, co-direction via the sign of
     `DotProduct`. The exact same two tests `faceref.py` uses to select a
     face, and for the same reason ("not a single tolerance of our own");
  3. a point of this face lies inside the HOST's bounding box, expanded by
     the wall's own thickness plus `VertexTolerance` (geometry). Both
     quantities are Revit's OWN numbers (`WallType.Width`,
     `doc.Application.VertexTolerance`), not one assigned. Expanding by
     exactly the thickness holds for ANY `location_line`: the wall's body
     lies entirely within a ±thickness band of the host face, and the host
     face lies within the host's bounding box. The claim FAILS if Revit
     built the wall against a mass other than the one named;

     WHY THE HOST'S BOUNDING BOX, NOT THE PLANE OF THE NAMED FACE — this is
     a measurement, not the easier choice. A mass in a project is a
     `FamilyInstance`, and its solid's face arrives through a
     `GeometryInstance`: `faceref` takes the REFERENCE with one accessor
     and the COORDINATES with another, through
     `GeometryInstance.Transform`, exactly because symbolic geometry has
     its own coordinate system. Reading `PlanarFace.Origin` through such a
     reference and silently treating it as a model value would mean
     introducing a third coordinate system into the witness — the same
     species of error as an assigned tolerance, only quieter. Revit hands
     back an element's bounding box in MODEL coordinates, and both sides
     of the comparison end up in one system with not a single transform of
     our own;
  4. the area of the SAME face, read from the built solid
     (`PlanarFace.Area`), is strictly greater than zero (geometry). This is
     not a threshold but the BOUNDARY OF VACUOUSNESS: zero area means
     nothing was built at all.

     THE SOLID IS READ, NOT A PARAMETER, and this is a correction, not the
     original design. The first edition took `HOST_AREA_COMPUTED` here and
     still signed it off as (geometry) — that is, it certified an axis it
     was not actually looking at. The house's own guard caught this
     (`test_witness_axis_honesty`, §18.3), and caught it exactly where such
     a substitution is invisible to the eye: a parameter NAMED FOR AREA
     looks more convincingly like geometry than many real readings do.

WHAT THE WITNESS DOES NOT SIGN OFF ON, STATED OUT LOUD: there is NO equality
here between the wall's area and the named face's area. RevitAPI.xml says
not one word about whether Revit covers the whole face, and asserting it
would mean introducing a check that could reject correct work. Instead of an
assertion, the receipt carries the RAW PAIR (face area and wall area, mm²)
— the first live run will thereby MEASURE this remainder rather than
estimate it. The same discipline as `create_slab_edge` with its perimeter,
and the solids wave with its volume.

═══ THE BOUNDARY OF THE MEASUREMENT ══════════════════════════════════════════

Everything above is measured by COMPILATION against the real assemblies and
by READING RevitAPI.xml for the throw conditions. This op has NOT ONE live
run (it stands in `tool_doc.UNPROVEN`), and compiles ≠ will build — the same
law as in shape_emit.py's header. Exactly two things are unverifiable
offline, and both are named: whether the wall covers the face entirely, and
exactly which wall types Revit allows for a face wall (for the second there
is a preflight `IsWallTypeValidForFaceWall`, asked BEFORE the effect, so the
unknown becomes a typed refusal, not an exception).
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: `create_face_wall.location_line` -> a `WallLocationLine` member. ALL SIX,
#: unlike `create_wall`, which has three. The difference is not in
#: permissiveness but in the reason: there, the narrowing is explained by
#: the LIFT (adding ordinals changes the decompile of real models and needs
#: its own coverage measurement), while a face wall has no lifter at all —
#: the reverse pass is declared a capture gap. Narrowing here would mean
#: taking away from the author a degree of freedom Revit itself accepts,
#: for a restriction whose reason does not apply to this operation.
#:
#: The names are the same words as `create_wall` uses
#: (`WALL_LOCATION_LINE_ORDINALS`), and this matters: two different
#: spellings of one concept in one registry would force the author to
#: guess whether they are the same thing.
FACE_WALL_LOCATION_LINES = {
    "wall_centerline": "WallCenterline",
    "core_centerline": "CoreCenterline",
    "finish_face_exterior": "FinishFaceExterior",
    "finish_face_interior": "FinishFaceInterior",
    "core_exterior": "CoreExterior",
    "core_interior": "CoreInterior",
}

OPS = [
    OpSpec(
        name="create_face_wall",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
                # THE HOST is an EXISTING MASS, and `target_w` is here for
                # the same reason as for an opening and for profiles: a face
                # wall is built against a mass that is ALREADY STANDING, and
                # a mass placed by this same program (`place_family`) is a
                # special case. `ref_kinds` is ELEMENT only: there is no
                # separate reference kind for a mass, and narrowing it to
                # WALL would be plainly wrong.
            ParamSpec("host", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
                # WHICH FACE — ITS OUTWARD NORMAL, in model coordinates. Not
                # an index: the order of `Solid.Faces` is not documented, and
                # "the first one that fits" is `.FirstOrDefault()` under
                # another name (a live paired measurement on 08-02 on
                # Snowdon: the C# arm silently took 1 door type out of 62).
                # The CARDINALITY of the set of matching faces decides,
                # exactly as in `faceref.py`: one — take it, zero — refuse,
                # two or more — refuse WITH THE NUMBER.
                #
                # THE SELECTION IS EXACT, NOT "CLOSEST BY ANGLE," and this is
                # a consequence, not a simplification: "closest" needs an
                # ANGULAR TOLERANCE that nobody has measured. The vector's
                # length does not matter — Revit normalizes it.
                #
                # THE KIND IS `pt_xyz`, BUT THESE ARE NOT MILLIMETERS, and
                # this cannot be left unsaid. This is exactly the same trick
                # and the same reason as `move_elements.delta_mm`: the shape
                # [x, y, z] is already RECOGNIZED by the schema, and
                # `schema_gen` is exhaustive — a new kind would mean an edit
                # in every one of its consumers for the sake of a value of
                # the same shape. The difference is named in
                # `authoring_validation`: the shared coordinate ceiling
                # (`_COORD_LIMIT_MM`) does not apply to a direction at all,
                # and a zero vector is rejected at parse time by EXACT
                # equality to zero — not a threshold: Revit itself decides
                # "nearly zero" with its own `XYZ.IsZeroLength()`, already at
                # runtime.
            ParamSpec("face_normal", "dir_xyz", required=True),
                # THE WALL'S POSITION RELATIVE TO THE FACE. REQUIRED and
                # WITHOUT A DEFAULT: this is an ARGUMENT of the call, not a
                # parameter that can be left unset — substituting it for the
                # author would mean silently deciding which side of the face
                # the solid stands on.
            ParamSpec("location_line", "enum", required=True,
                      choices=tuple(FACE_WALL_LOCATION_LINES)),
                # The wall type. The pool is the same one `create_wall`
                # uses: the same type class (`WallType`), and a second pool
                # over the same elements would mean two answers to one
                # question. Whether a SPECIFIC type is valid for a face wall
                # is decided not by the pool but by Revit itself —
                # `IsWallTypeValidForFaceWall`, asked BEFORE the effect.
            ParamSpec("type", "sel"),
        ),
            # A REAL ELEMENT, not ("create", "geometry"): a face wall has a
            # type, layers, and an area in the schedule — everything a
            # DirectShape lacks by construction. The category cell is NOT
            # declared: the category is known exactly (OST_Walls), but
            # `create_wall` already covers this cell, and a second entry for
            # the same thing adds no knowledge.
        capability=(("create", "element"),),
        post=("face wall exists (materialized or typed refusal); "
              "a wall type Revit refuses for a face wall is a typed refusal "
              "from IsWallTypeValidForFaceWall BEFORE the call, never a raw "
              "ArgumentException; "
              "a face Revit refuses as a face-wall parent is a typed refusal "
              "from IsValidFaceReferenceForFaceWall BEFORE the call; "
              "GetTypeId() re-read == resolved wall type (topology); "
              "the built wall has EXACTLY ONE exterior side face codirectional "
              "with the named mass face, by Revit's own zero-length "
              "cross-product test and the sign of the dot product, with no "
              "tolerance of ours (geometry); "
              "a point of that face lies inside the host's model-space "
              "bounding box grown by the wall's own WallType.Width plus "
              "doc.Application.VertexTolerance — both Revit's own numbers, "
              "none assigned here (geometry); "
              "the PlanarFace.Area of that same built face is strictly "
              "positive (geometry: the vacuity boundary, not a threshold — "
              "and read off the SOLID, never off a parameter, so the verdict "
              "signs the axis it actually read); "
              "NAMED ABSENCE: area equality between the wall and the named "
              "face is NOT asserted — whether Revit spans the whole face is "
              "documented nowhere, so the receipt carries the RAW PAIR and "
              "the first live run measures the remainder instead of a "
              "reasoned tolerance standing in for it"),
        writes_model=True,
        grounded=(("type", "wall_types", False),),
        # EMPTY BY CONSTRUCTION, as in the solids wave: this operation's
        # only numeric tolerance is a function of the wall itself
        # (`WallType.Width`) and Revit's own number (`VertexTolerance`), so
        # it cannot be a registry constant. Full account is in the module
        # header.
        tolerances={},
    ),
]
