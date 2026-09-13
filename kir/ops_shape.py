"""ops_shape — arbitrary mesh geometry (DirectShape).

Registry module — operations are added HERE, not in spec.py. The emitter
lives in shape_emit.py (a paired file, exactly like ops_arch.py + arch_emit.py
for the AR wave); authoring.py gets only the import and one line in
_EMITTERS. The laws of mesh shape are in mesh.py.

WHY THIS WAVE. KIR is designed as an exoskeleton for a neural network: the
model invents geometry, the tool takes off it the Revit versions,
transactions, types, hosts, units, and rollback. But all 32 registry
operations are building-centric — levels, walls, rooms, contours — and the
model cannot express an arbitrary shape (a shell, a lattice, a twisted
tower) by ANY of them. A wall stands exactly where the model's strength is
greatest.

═══ HONEST LABEL ═══════════════════════════════════════════════════════

DirectShape is GEOMETRY WITHOUT BIM MEANING. This is not fine print, but
the main property of the operation, and it is obligated to state it
itself:

  * NO TYPE. The element has neither a type nor its parameters. Therefore
    the operation has no `type` parameter and has NOT A SINGLE pool in
    `grounded` — not from an oversight, but because there is nothing to
    substitute. The only registry operation without grounding, and this is
    a fact about DirectShape, not about our laziness.
  * NO PARAMETERS. Thickness, layer material, fire resistance — none of
    this exists for a mesh. A schedule against such an element will count
    units, not square meters of wall.
  * A HUMAN CANNOT EDIT IT. A wall is dragged by its grip and its type
    changed; a mesh can only be deleted and rebuilt. This is a one-way
    door.

Hence two constructive matters that are settled, both against lying:

1. THE CAPABILITY CELL is («create», «geometry»), and NOT («create»,
   «element»). All other writing operations of the registry declare
   «element»; the coverage cube will show this one — and only this one —
   as creating GEOMETRY. This way "we can do this" will not turn, in a
   report, into "we can create elements of this kind".

2. CATEGORIES ARE LIMITED TO THOSE THAT DO NOT PASS THEMSELVES OFF AS
   SOMETHING ELSE (see the table). BuiltInCategory.OST_Walls compiles
   (measured 6/6), and the temptation to allow it is great: "the user
   asked for a wall — here is a wall." But a mesh in the walls category
   reads as a wall in EVERY filter, schedule, and export, without being
   anything a wall is: no layers, no joins, no openings, no height. From
   the outside this is indistinguishable from success — the very Goodhart
   effect that, in this house, cost 96.77% of the groups. KIR has real
   create_wall/create_floor/create_roof/create_column/create_beam; where
   they exist, a mesh has no business under their sign. The refusal names
   them by name.

API MEASUREMENTS (live compile service :52412, 2021-2026, 29.07 — names of
ours are checked by compilation, not by memory):

  DirectShape.CreateElement(doc, ElementId categoryId)      → 6/6
  DirectShape.CreateElement(doc, catId, string, string)     → 0/6  ← MEMORY
      CS1501 No overload for method 'CreateElement' takes 4 arguments
  DirectShape.IsValidCategoryId(ElementId, Document)        → 6/6
  DirectShape.GetValidCategoryIds(Document)                 → 0/6
      CS0117 'DirectShape' does not contain a definition for it
  TessellatedShapeBuilder + OpenConnectedFaceSet/AddFace/
      CloseConnectedFaceSet/Build/GetBuildResult             → 6/6
  new TessellatedFace(IList<XYZ>, ElementId)                → 6/6
  new TessellatedFace(IList<XYZ>)                           → 0/6
      CS1729 does not contain a constructor that takes 1 arguments
  TessellatedShapeBuilderTarget.{AnyGeometry,Mesh,Solid}    → 6/6
  TessellatedShapeBuilderFallback.{Abort,Mesh,Salvage}      → 6/6
  TessellatedShapeBuilderOutcome.{Nothing,Mesh,Solid}       → 6/6
  ElementId.IntegerValue                                    → 5/6  (missing in 2026)

MEASUREMENT FOR THE SURFACE WITNESS (the same service, 09.08):

  Mesh.NumTriangles / Mesh.get_Triangle(int)                → 6/6
  MeshTriangle.get_Vertex(int) / Mesh.Vertices              → 6/6
  List<long[]>.Sort(Comparison<long[]>)                     → 6/6
  long.ToString(CultureInfo.InvariantCulture)               → 6/6
  System.Security.Cryptography.SHA256.Create()              → 4/6  ← MEMORY
      2025, 2026: CS1069 the type is forwarded to an assembly outside the reference closure
  System.Security.Cryptography.SHA256Managed                → 4/6  (the same)
  SHA256.HashData(byte[])                                   → 0/6

Hashing cannot be done in emitted C# on two of the six versions, so the
witness compares the PREIMAGE of the digest, not the digest itself — the
analysis is in the shape_emit.py header.

The four-argument CreateElement is exactly the case the extract.py header
warns about: from memory it gets written first (that is how almost all
DirectShape code on the internet and in old API versions looks), the
compiler would have accepted it silently had it existed, and we would have
learned of the trouble live. It does not exist on any of the six versions.
Checking by compilation, not by memory, is not a ritual.

WHAT IS NOT HERE AND WHY:

* MATERIAL. TessellatedFace accepts materialId, and passing
  ElementId.InvalidElementId there is the only thing we can prove offline.
  A material parameter would require its own pool and its own grounding;
  introducing it "just in case" with guessed behavior is the same class of
  error as the ceiling slope in the AR wave. For now the face is built
  with the default material.
* SOLID. TessellatedShapeBuilderTarget.Solid compiles, but requires a
  closed body, and an open shell is half of meaningful meshes. Solid is a
  separate wave with its own live measurement, not a flag here.

  THE WAVE TOOK PLACE ON 09.08 — and not as a flag, but as A DIFFERENT
  DOOR: `ops_solid.py` builds a body with seven `GeometryCreationUtilities`
  factories (two of the seven are used — extrusion and revolution), rather
  than the tessellator. The reason for changing doors is stronger than the
  original one: for a parametric body, the volume is computed ANALYTICALLY
  at compile time from the CONTOUR profile, i.e. the witness verifies a
  quantity that was not in the input — which a mesh cannot do by
  construction (there, the bounding box and triangle count are verified,
  i.e. our own input). The Target=Solid flag never appeared here and never
  will: it would give a closed mesh, not parametrics, and would not
  strengthen the witness.

A MEASUREMENT THE GATE DOES NOT CATCH (and is therefore recorded
separately). The pair Target=Mesh + Fallback=Abort compiles 6/6 and IS NOT
a supported one: the RevitAPI.xml of the reference package, the note on
TessellatedShapeBuilder.Build, verbatim and identical in 2021 and in
2026 —

    Currently only "Solid/Abort", "AnyGeometry/Mesh" and "Mesh/Salvage"
    target/fallback combinations are supported.

The emitter therefore sets Mesh/Salvage, and the silence of Salvage ("use
all suitable data") is closed by the face-count witness, not by hope. A
detailed analysis is in the shape_emit.py header. Conclusion for future
waves: a green gate proves the code WILL COMPILE, and says nothing about
whether Revit will accept it; for the latter there is RevitAPI.xml and a
live run.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: `category` in words <-> BuiltInCategory members. ONE table for the
#: emitter and the lift, so the two directions do not diverge — the same
#: technique as RAILING_PLACEMENT_MEMBERS in the AR wave and
#: WALL_LOCATION_LINE_ORDINALS for walls.
#:
#: The set is CLOSED and deliberately narrow: it includes only categories
#: that, in native Revit itself, mean "volume without a BIM role".
#: Categories for which KIR has a real operation (walls, floors, roofs,
#: columns, framing) are absent deliberately — see item 2 of the header.
#: All members are measured 6/6.
DIRECTSHAPE_CATEGORIES = {
    "generic_model": "OST_GenericModel",
    "mass": "OST_Mass",
    "site": "OST_Site",
    "entourage": "OST_Entourage",
    "specialty_equipment": "OST_SpecialityEquipment",
    "furniture": "OST_Furniture",
}

#: Categories that compile but are forbidden here, and the operation that
#: does the same thing HONESTLY. It reads as a refusal, so the user learns
#: not "you can't", but "here is what does this".
IMPERSONATION_ROUTES = {
    "walls": "create_wall",
    "floors": "create_floor / create_floor_by_contour",
    "roofs": "create_roof",
    "columns": "create_column",
    "structural_columns": "create_column",
    "structural_framing": "create_beam",
    "ceilings": "create_ceiling",
    "stairs": "create_stairs",
}

OPS = [
    OpSpec(
            name="create_directshape",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # A mesh is ONE value, not two parallel lists. Otherwise
                # the schema would allow the state "vertices exist,
                # triangles don't", i.e. exactly the class where absence
                # turns into zero. Indices without a vertex array are not
                # verifiable in principle, so they must travel together.
                ParamSpec("mesh", "mesh", required=True),
                ParamSpec("category", "enum", required=True,
                          choices=tuple(DIRECTSHAPE_CATEGORIES)),
                # The name is MANDATORY. For an element without a type, the
                # name is the only thing that distinguishes it from a
                # nameless blob in the project tree; a person who opens the
                # model a year later reads exactly this. An optional name
                # would mean "silence is also fine".
                ParamSpec("name", "str", required=True, max_val=64),
            ),
            # GEOMETRY, NOT AN ELEMENT — see item 1 of the header. The only
            # writing operation of the registry with this cell.
            capability=(("create", "geometry"),),
            # What is promised is exactly what is checked, and every
            # promise reads the RESULT, not our call: the bounding box, the
            # triangle count, and the surface itself are read from the
            # element's built geometry.
            post=("direct shape exists (materialized or typed refusal); "
                  "bbox extents == mesh vertex extents in XYZ (±5mm, "
                  "geometry); "
                  "built mesh triangle count == triangles count (geometry); "
                  "built mesh surface multiset == authored surface multiset "
                  "on the ±0.5mm canon grid (geometry)"),
            writes_model=True,
            # EMPTY, AND THAT IS MEANINGFUL: DirectShape has no type, so it
            # has neither a pool nor grounding. The only writing operation
            # of the registry without grounded — see "HONEST LABEL".
            grounded=(),
            # TWO TOLERANCES, AND THE SECOND ONE IS NOT DERIVED HERE.
            # `surface_canon_mm` is `GEOM_CANON_MM` from decompile/schema.py,
            # the frozen Tier-G grid on which the content-addressable
            # geometry store and the live post-commit idempotency-rig
            # predicate already stand. The surface witness must quantize
            # EXACTLY the same way, otherwise it would be comparing two
            # different canons. The number is not copied here as an
            # opinion: the equality of the registry value and the constant
            # is nailed down by a test
            # (`test_shape.py::SurfaceWitness...canon_grid...`), because
            # importing `decompile.schema` from the registry would mean
            # pulling the whole decompile package (measured 09.08: +0.57 s
            # on import) into the service's startup.
            #
            # WHY THE GRID IS ITSELF THE TOLERANCE. The comparison is exact
            # (string==string), but the QUANTIZED coordinates are what get
            # compared, so detectability is set by the step: a vertex shift
            # of ≥0.5 mm along any axis GUARANTEED changes the cell number
            # (cells exactly 1 unit wide), a shift of <0.25 mm from the
            # cell center NEVER changes it.
            tolerances={"bbox_mm": 5.0, "surface_canon_mm": 0.5},
        ),
]
