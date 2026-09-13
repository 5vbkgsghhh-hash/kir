"""ops_site — site and terrain (wave/site, 2026-08-09).

Registry module — Add ops HERE, not in spec.py. The paired emission file is
`site_emit.py`, exactly as `ops_arch.py` ↔ `arch_emit.py`.

BEFORE THIS WAVE THE SITE FAMILY WAS EMPTY: no terrain, no building pad, no
sub-region. The building stood in a void, and "put the house on the
terrain" — the most ordinary phrase from a client — was expressed by
NOTHING.

API MEASUREMENT (live compile service :52412, 2021-2026, 09.08.2026). Not a
single line below is written from memory; each is checked by assignment to
a DECLARED type (`var __x = ...` compiles for any type on the right and
proves nothing — the lesson of the railings wave, where such a probe
missed `ICollection<ElementId>`):

    TopographySurface.Create(doc, IList<XYZ>)                6/6
    TopographySurface.GetPoints()                            6/6
    TopographySurface.IsSiteSubRegion                        6/6
    Toposolid.Create(doc, IList<XYZ>, typeId, levelId)       2024-2026
    Toposolid.Create(doc, IList<CurveLoop>, typeId, levelId) 2024-2026
    Toposolid.Create(doc, profiles, points, typeId, levelId) 2024-2026
    Toposolid.GetSlabShapeEditor()                           2024-2026
    Toposolid.GetPoints()                                    NOT ON ANY
    SlabShapeEditor.SlabShapeVertices / SlabShapeVertex.Position  6/6
    BuildingPad.Create(doc, typeId, levelId, IList<CurveLoop>)    6/6
    BuildingPad.GetBoundary() / .AssociatedTopographySurfaceId    6/6
    SiteSubRegion.Create(doc, IList<CurveLoop>)              6/6
    SiteSubRegion.Create(doc, IList<CurveLoop>, ElementId)   6/6
    SiteSubRegion.GetBoundary() / .HostId / .TopographySurface    6/6
    ElementTypeGroup.BuildingPadType                         6/6
    ElementTypeGroup.ToposolidType                           NOT ON ANY
    ToposolidType (a type)            2024-2026 (2023: CS0122, internal)

FOUR FACTS THAT WOULD HAVE OVERTURNED THESE OPS HAD THEY NOT BEEN MEASURED:

1. `SiteSubRegion` is NOT an `Element`. It has neither `.Id` nor
   `get_Parameter` (CS0029/CS1061 on all six). The sub-region's element is
   its `.TopographySurface`, and it is exactly this that gets stamped,
   read into the receipt, and witnessed. Writing `__sr.Id` would be a
   sixfold CS1061; worse — there is nothing to write `__sr` into the
   receipt with, and a receipt without an id is indistinguishable from
   garbage in the model, because A5 verifies ownership precisely by it.
2. `ElementTypeGroup.BuildingPadType` EXISTS on all six, even though
   `backend/data/revit_api_db.json` does not know it (our database carries
   30 of 93 members of `ElementTypeGroup`). The database is documentation,
   the judge is the compiler; the same priority by which 30.07 settled
   `SpatialElementTag.SpatialElement`. That is why a building pad HAS a
   default type (like a wall), while a terrain solid has none by
   construction (like a railing).
3. `Toposolid.GetPoints()` DOES NOT EXIST (CS1061 on 2024/2025/2026, where
   the type itself exists). There is no symmetrically strong witness for
   the solid; in its place is `GetSlabShapeEditor().SlabShapeVertices`,
   which COMPILES, but whose NON-emptiness, for a solid built from points,
   cannot be checked offline (see below "WHAT IS NOT PROVEN HERE").
4. `BuiltInCategory.OST_Toposolid` appeared in 2023 — a YEAR before the
   `Toposolid` class itself (2024). This means the category name cannot be
   used as a version marker, and a collector of solid types cannot be
   written through `OfCategory`.

ONE TERRAIN OPERATION, NOT TWO, AND HERE IS ONE SENTENCE WHY: a surface and
a solid are TWO VARIETIES of one intent, "lay down terrain", exactly like
the spread-footing and slab varieties of `create_foundation`, so the
AUTHOR names the variety (`variety`, a closed enumeration with no
default), while the conditionally mandatory fields — the level and the
type, needed only by the solid — are held by the emitter as a typed
refusal, the way `struct_emit.emit_foundation` holds `xy` against
`outline`.

Why this is NOT "one operation with automatic selection by version": the
solid and the surface are DIFFERENT elements of DIFFERENT categories
(`OST_Toposolid` versus `OST_Topography`), with different witnesses and
different binding to the level. Substituting one for the other by version
number would mean building something other than what was asked, and from
the outside this is indistinguishable from success — exactly what is
forbidden. Therefore `variety="toposolid"` on 2021-2023 is a typed
refusal, KIR-E003, NAMING the next move (`variety="surface"`), not a
silent swap.

WHAT IS DELIBERATELY NOT HERE:

* a solid by CONTOUR (`Toposolid.Create(doc, IList<CurveLoop>, ...)` and
  the "profiles + points" overload) is not wired in: the operation has one
  shape input — points — and calling the five-argument overload with an
  empty profile list would mean passing the API a shape whose behavior is
  undocumented. This is separate future work with its own witness, not
  "one more optional parameter";
* the building pad has NO `host` parameter: `BuildingPad.Create` does not
  accept a host at all — Revit looks for it itself. So "no host" is
  caught by a pre-check in the emitter (see site_emit.py), rather than by
  a field.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)

#: The varieties of terrain. A closed enumeration WITHOUT a default:
#: substituting one for the author would mean choosing an element of a
#: different category on their behalf.
TOPOGRAPHY_VARIETIES = ("surface", "toposolid")

#: The earliest Revit version where the `Toposolid` class exists
#: (measured). It lives here, not as a literal in the emitter: the same
#: number is read by both the version-axis test and the gate table.
TOPOSOLID_MIN_VERSION = "2024"


def toposolid_version_refusal(op, ver: str):
    """Version refusal for a terrain solid — or None. Lives NEXT TO the threshold.

    WHY A SEPARATE FUNCTION, NOT A LINE IN THE EMITTER (13.08.2026, found by
    a LIVE run on Revit 2023). The check stood ONLY in emission, while pool
    grounding runs earlier — and on 2023 the author got

        KIR-G104  «toposolid_types: пусто в модели»

    instead of the truth. The pool there is empty NOT because no type was
    set up in the document, but because on Revit 2021-2023 terrain solids
    do not exist at all: the `ToposolidType` class is absent from the
    reference assemblies of these three versions (checked against the API
    surface; `open_model.py` knew this all along and worked around it by
    comparing the type name AS A STRING — otherwise the snapshot would not
    have assembled).

    The cost was not inaccuracy but the advice being impossible to follow:
    «пусто в модели» reads as "set up a type", and the LLM would go off to
    set up a terrain-solid type on versions where terrain solids do not
    exist. Neither of the named roads led anywhere.

    The rule that follows from this, and that stands wider than this op:
    **the version is a fact about the world, the pool is a fact about the
    document; when the former EXPLAINS the latter, the former answers.**
    It is measured that there is exactly ONE such pool out of 36, so this
    is an addressed function, not a mechanism: a "capability → version"
    table would become a third copy of knowledge that already lives in the
    emitters.
    """
    from kir.diag import Diagnostic, EMIT_UNSUPPORTED

    if not isinstance(op, dict) or op.get("op") != "create_topography":
        return None
    if op.get("variety") != "toposolid" or ver >= TOPOSOLID_MIN_VERSION:
        return None
    return Diagnostic(
        code=EMIT_UNSUPPORTED, op_id=op.get("id"), field_name="variety",
        got="toposolid", candidates=["surface"],
        message_ru=(
            f"толща рельефа (Toposolid) не создаётся на Revit {ver}: "
            f"тип появился только в {TOPOSOLID_MIN_VERSION} — "
            f"замерено компиляцией на шести версиях. Следующий ход: "
            f"variety=\"surface\" (TopographySurface, 2021-2026) — но "
            f"это ДРУГОЙ элемент другой категории, поэтому подменить "
            f"его за вас компилятор не станет"))

OPS = [
    OpSpec(
            name="create_topography",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # THE AUTHOR NAMES THE VARIETY. The name `variety`, not
                # `kind` — the same registry constraint as create_foundation:
                # `kind` is reserved for kind_enum, and test_invariants
                # requires an escape value for a field with that name, which
                # terrain honestly does not have.
                ParamSpec("variety", "enum", required=True,
                          choices=TOPOGRAPHY_VARIETIES),
                # TERRAIN POINTS ARE THREE-DIMENSIONAL, AND THIS IS NOT A
                # CONVENIENCE. For terrain, the elevation lives IN THE POINT
                # ITSELF: TopographySurface.Create does not accept a level
                # at all, and the Z of each point IS the ground height. The
                # flat `pts` kind ([x,y]) would flatten the terrain into a
                # plane — i.e. silently build a DIFFERENT terrain.
                ParamSpec("points_mm", "pts_xyz", required=True),
                # LEVEL — ONLY FOR THE SOLID, and this is a genuine
                # divergence of signatures, not an emitter branch:
                # Toposolid.Create REQUIRES levelId, TopographySurface.Create
                # does not accept it. required=False at the schema level for
                # the same reason as create_railing.level: a static
                # required=True would have demanded a level from the surface
                # too, which needs it NOWHERE. The conditional requirement
                # is held by the emitter (KIR-P005).
                ParamSpec("level", "sel",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # TYPE — ONLY FOR THE SOLID. It has no document default BY
                # CONSTRUCTION: ElementTypeGroup.ToposolidType does not
                # exist on any of the six versions (measured), asking Revit
                # "what is your default terrain solid" is impossible. A
                # missing type resolves ground by the general rule "the
                # only one in the pool, otherwise a typed question" — the
                # same seam as the railing.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("variety=surface: topography surface exists on 2021-2026 "
                  "(TopographySurface.Create, no level — elevation lives in "
                  "each point's Z); "
                  "variety=toposolid: toposolid exists on 2024-2026 only, and "
                  "below that the whole op is a typed refusal naming "
                  "variety=surface as the next move — never a substituted "
                  "element of another category; "
                  "described terrain points are re-read FROM the built "
                  "element (±1mm): GetPoints() on the surface, "
                  "SlabShapeEditor vertices on the toposolid (geometry); "
                  "bbox XY extents == points XY extents (±50mm, geometry); "
                  "level binding == resolved level when variety=toposolid "
                  "(topology)"),
            writes_model=True,
            grounded=(("level", "levels", False),
                      ("type", "toposolid_types", False)),
            # ±1mm — DERIVED, not assigned: this is `contour._EDGE_TOL`,
            # i.e. Revit's own static ShortCurveTolerance. Revit does not
            # distinguish two points closer than this at all, so a match
            # between the read point and the described one within 1 mm is
            # the MOST PRECISE statement that makes any sense at all on
            # this platform. Shrinking it to the noise of unit conversion
            # (≈1e-9 mm) would mean blaming correct terrain for a rounding
            # we did not measure.
            #
            # ±50mm — INHERITED, and this is said outright: exactly the
            # number that already sits in the registry for
            # create_floor_by_contour, create_ceiling, and create_foundation
            # under the same key `bbox_mm`, for the same predicate over the
            # same reader `get_BoundingBox`. It is ASSIGNED (`assigned` in
            # bounds_audit terms), not measured; introducing our own number
            # here would mean adding a fourth boundary assigned by
            # reasoning — the class of defect this house is built against.
            tolerances={"point_mm": 1.0, "bbox_mm": 50.0},
        ),
    OpSpec(
            name="create_building_pad",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # CONTOUR IS THE NATIVE INPUT OF THIS OPERATION, not an
                # alternative to the polyline: BuildingPad.Create accepts
                # IList<CurveLoop>, i.e. exactly what contour.emit_loop_cs
                # already builds. There is no flat `outline` here at all —
                # introducing a second shape input where there is no
                # reverse pass (materialize) would mean introducing a
                # mutual obligation for no one.
                ParamSpec("contour", "region", required=True),
                # The level is MANDATORY at the API level itself (the
                # four-argument Create), so here required=True without
                # qualification.
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # A missing type resolves ground by the general rule "the
                # only one in the pool, otherwise a typed question". A
                # default document type for the pad DOES EXIST
                # (ElementTypeGroup.BuildingPadType, 6/6 — measured despite
                # our own API database), but is NOT used: see the analysis
                # in site_emit._grounded_type_cs. In short — "the default
                # pad" on someone else's building is almost never the right
                # one, and a type substitution is indistinguishable from
                # success from the outside; the author will see a typed
                # question with candidates, but will not see a
                # substitution.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("building pad exists on 2021-2026 (BuildingPad.Create); "
                  "a pad with no hosting topography anywhere in the document "
                  "is a typed refusal naming create_topography as the next "
                  "move, never a raw InvalidOperationException; "
                  "level binding == resolved level (topology); "
                  "GetBoundary() re-read bbox == contour lowered-edges bbox "
                  "(±50mm, arc extremes included, geometry); "
                  "AssociatedTopographySurfaceId holds a real element id "
                  "(topology)"),
            writes_model=True,
            grounded=(("level", "levels", True),
                      ("type", "building_pad_types", False)),
            # ±50mm — the same inherited `bbox_mm` as above, and here it
            # has a DERIVABLE component: the reader is not the body's
            # bounding box but the boundary itself, `GetBoundary()`,
            # unrolled by `Curve.Tessellate()`. The unrolled points lie ON
            # the curve, so the only inherent reading error is the sagitta
            # of a single tessellation segment, and it is orders of
            # magnitude smaller than 50 mm for any building. The rest of
            # the margin is an inherited assignment, not a measurement.
            tolerances={"bbox_mm": 50.0},
        ),
    OpSpec(
            name="create_site_subregion",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("contour", "region", required=True),
                # THE HOST IS OPTIONAL, because there are TWO overloads
                # (both 6/6): without a host, Revit looks for the surface
                # itself; with a host, it takes the named one. This
                # selector deliberately has no pool: a pool of
                # topo-surfaces does not exist in the snapshot, and
                # introducing one for `by:name` would mean promising
                # resolution by name where a surface's name in Revit is not
                # its address. `by:element_id` and `by:ref` work — the same
                # seam and the same reason as create_railing.host.
                ParamSpec("host", "sel",
                          ref_kinds=(ReferenceKind.ELEMENT,)),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            post=("site subregion exists on 2021-2026 "
                  "(SiteSubRegion.Create); "
                  "the created surface reports IsSiteSubRegion (semantic); "
                  "GetBoundary() re-read bbox == contour lowered-edges bbox "
                  "(±50mm, arc extremes included, geometry); "
                  "HostId holds a real element id, and equals host when host "
                  "is given (topology)"),
            writes_model=True,
            grounded=(),
            tolerances={"bbox_mm": 50.0},
        ),
]
