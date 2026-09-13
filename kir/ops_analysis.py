"""ops_analysis — loads (KR, structural design) and the evacuation route (AR,
architectural design): a family that, before this wave, had NEITHER AN OP,
NOR A REFUSAL, NOR A MENTION.

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

────────────────────────────────────────────────────────────────────────────
WHAT THIS WAS MEASURED WITH. Everything below is taken from REFERENCE BUILDS
────────────────────────────────────────────────────────────────────────────

Every signature and every readable property was compiled with a live Roslyn
against the real `RevitAPI.dll` 2021-2026 BEFORE the emitter was written.
`data/revit_api_db.json` is provably incomplete and was not consulted here;
`RevitAPI.xml` was read directly, but the compiler, not the document, was the arbiter.

────────────────────────────────────────────────────────────────────────────
THE MAIN MEASUREMENT: LOADS HAVE AN API SURFACE BREAK AT 2024, AND IT IS COMPLETE
────────────────────────────────────────────────────────────────────────────

A free (NOT HOSTED) load can only be expressed on 2021-2023:

  PointLoad.Create(Document, XYZ point, XYZ force, XYZ moment,
                   PointLoadType, SketchPlane)                2021-2023, 3/6
  LineLoad.Create(Document, XYZ start, XYZ end, XYZ force,
                  XYZ moment, LineLoadType, SketchPlane)      2021-2023, 3/6
  AreaLoad.Create(Document, IList<CurveLoop>, XYZ force,
                  AreaLoadType)                               2021-2023, 3/6

On 2024-2026 these overloads DO NOT EXIST AT ALL (`CS1503`/`CS1501`,
measured), and this is not a rename: Autodesk removed the very possibility
of creating a load without a host. ALL the remaining overloads take, as
their first argument after the document, an `ElementId hostElemId` — "The
AnalyticalElement host element for the load" — i.e. they require an
ANALYTICAL element, which we have neither in the snapshot nor in the
reference language.

WHY `ElementId.InvalidElementId` CANNOT SIMPLY BE PASSED. It compiles —
verified. But the 2024/2025/2026 documentation states verbatim, for this
same argument, an `ArgumentException` "hostElemId is not permitted for this
type of load," and NOWHERE does it say that an invalid id means "without a
host." A guess about behavior that cannot be checked without a live Revit is
exactly the invention forbidden by the law of tolerances — only about call
semantics rather than a number. So on 2024-2026 the three load operations
refuse TYPED (`KIR-E003`) and name the reason, rather than build "something."

WHAT WOULD LIFT THE REFUSAL (named so the next session does not start from
zero): a pool of analytical elements in the snapshot
(`AnalyticalMember`/`AnalyticalPanel`, both classes exist since 2023) plus
ONE live run showing that `PointLoad.IsValidHostId` answers true for them and
the built load reads back with the same witness as here. Until that run, a
hosted load is not "unfinished" — it is NOT MEASURED.

────────────────────────────────────────────────────────────────────────────
THE WORK PLANE IS AUTHORED BY US, NOT TAKEN FROM THE ACTIVE VIEW
────────────────────────────────────────────────────────────────────────────

The point-load and line-load overloads accept a `SketchPlane plane`, and
Autodesk writes: "Set null to use default plane." The default here is the
user's ACTIVE VIEW, i.e. an input the program does not have. Handing it the
load's elevation would mean building an element whose position depends on
which tab the person last opened in Revit — and this is not theory:
execution travels through the bridge, and the active view on that machine is
unknown to us.

So the emitter BUILDS THE PLANE ITSELF (`SketchPlane.Create` +
`Plane.CreateByNormalAndOrigin`, both 6/6) — through the given point for a
point load, through both ends for a line load. The consequence is checkable:
`PointLoad.Point` and `StartPoint`/`EndPoint` must match the ones ordered,
and the witness demands this. For an area load, the rings themselves define
the plane; it has no plane argument.

────────────────────────────────────────────────────────────────────────────
THE ORIENTATION IS PINNED, OTHERWISE THE FORCE VECTOR MEANS NOTHING
────────────────────────────────────────────────────────────────────────────

`ForceVector` is documented verbatim as "oriented according to OrientTo
setting." That is, the same three numbers mean DIFFERENT things depending on
the load's frame of reference, and "1000 N down" on a sloped work plane is
not down. A witness that only checks the numbers would not notice a swapped
frame of reference at all: it would read the same triple.

So after creation the emitter sets `OrientTo = LoadOrientTo.Project`
(documented as permitted for a non-hosted load), and AFTER THAT writes the
force vector once more — now in the pinned frame — and the witness checks
BOTH facts: that the frame of reference is the project one, and that the
vector is the right one. The order "frame first, then vector" is not
accidental: if Revit recomputed the numbers when the frame changed, the
check would be catching its own recomputation.

────────────────────────────────────────────────────────────────────────────
UNITS: WE ASK REVIT, WE DO NOT REMEMBER A COEFFICIENT
────────────────────────────────────────────────────────────────────────────

Revit's internal unit of force is not the newton, and its value is not
recorded anywhere in this package, and it will not be. The conversion goes
through `UnitUtils.ConvertToInternalUnits(..., UnitTypeId.Newtons |
UnitTypeId.NewtonMeters | UnitTypeId.NewtonsPerMeter |
UnitTypeId.NewtonsPerSquareMeter)` — all four compile 6/6 — meaning Revit
itself knows the coefficient. A hardcoded multiplier here would be the same
class of defect as a hardcoded tolerance.

────────────────────────────────────────────────────────────────────────────
TOLERANCES: GEOMETRY — FROM REVIT, FORCE — DERIVED FROM BOUNDS AND IEEE-754
────────────────────────────────────────────────────────────────────────────

GEOMETRY. Not a single number, either in the registry or in C#: points are
compared against `doc.Application.VertexTolerance` — Revit's own tolerance,
"two points closer than this are considered one," read from the running
application at check time. Not a new technique: this is exactly how
`create_dimension` has been measuring since 08-09 (see its docstring — "no
tolerance is invented for it, and none is registered"). We ourselves author
the work plane and ourselves place the points, so Revit has no reason to
move them; if a live run shows that it does, the check must be replaced by a
MEASURED shift, not weakened to taste. The direction of error here is safe:
too tight a tolerance gives a LOUD false refusal with a rollback, not a
quiet acceptance.

FORCE. The number is derived, not assigned:

  * the registry declares |f| <= 1e8 (N, N/m, N/m²) — a garbage ceiling, not an engineering one;
  * the value's path is `x -> x·k -> (x·k)/k`, two operations in double, each
    with error <= 0.5 ulp; accounting for the representation of x itself, the
    relative error does not exceed 3·2^-53 ≈ 3.3e-16;
  * at the upper bound of the range this is 1e8 · 3.3e-16 = 3.3e-8;
  * the nearest round decade strictly above it is 1e-6, with a margin of about 30x.

The moment is computed the same way and against the same bound, so its number is the same.

────────────────────────────────────────────────────────────────────────────
THE LOAD CASE IS REQUIRED, AND THIS IS NOT PEDANTRY
────────────────────────────────────────────────────────────────────────────

`load_case` is declared `required=True`, even though the API does not
require it: without an explicit setting, Revit will place the load into the
default case of its own nature. This is exactly the silently-wrong outcome
the compiler exists for — the load stands, looks correct on screen, and
participates in combinations under the wrong case (or does not participate
at all). Indistinguishable from correctly done work from the outside. So the
AUTHOR names the case, the emitter writes it (`LoadBase.LoadCaseId` is
writable, 6/6), and the witness reads `LoadCaseId` back from the BUILT element.

The `load_natures` pool is DELIBERATELY NOT SET UP: the load's nature is an
input to the CASE-CREATION operation (`LoadCase.Create`), which this wave
does not have, and the closed enumeration `query_types` by construction
lists the pools AGAINST WHICH writing ops' selectors GROUND. A pool that
nothing grounds against would be the first exception to this rule.

────────────────────────────────────────────────────────────────────────────
WHAT IS NOT HERE AND WHY (rejected deliberately, not forgotten)
────────────────────────────────────────────────────────────────────────────

1. `Autodesk.Revit.Creation.Document.NewPointBoundaryConditions` — THERE IS
   NO OPERATION, because its single host argument IS NOT ADDRESSABLE BY THIS
   LANGUAGE. There is exactly one overload across all six versions, and it
   takes an `Autodesk.Revit.DB.Reference` — verbatim "A Geometry reference to
   a Beam's, Brace's or Column's analytical line END." KIR's frozen reference
   dialect — `{"by": "name"|"element_id"|"ref"}` — knows how to name
   ELEMENTS; "the end of the analytical line of that column over there" has
   NO WAY AT ALL to be named. The same case as the rejected `create_wire`
   with its `Connector`: not "inconvenient for now" but inexpressible by construction.

2. `NewLineBoundaryConditions` / `NewAreaBoundaryConditions` in the FROM-AN-
   ELEMENT form — are addressable (they take an `Element`: "A Beam" and "A
   Wall, Slab or Slab Foundation"), compile 6/6, and the operation is STILL
   absent. There is exactly one reason, and it is about the witness: the
   ENTIRE professional meaning of a support is its six degrees of freedom
   (Fixed/Release/Spring across three translations and three rotations), and
   there is NOTHING to read them back with. `BoundaryConditions` has not a
   single property about degrees of freedom: there is `HostElementId`,
   `Point`, `GetCurve`, `GetLoops`, `GetBoundaryConditionsType`,
   `GetDegreesOfFreedomCoordinateSystem` — and not one
   `TranslationRotationValue`. The built-in parameters
   (`BOUNDARY_RESTRAINT_*`, `BOUNDARY_LINEAR_RESTRAINT_*`,
   `BOUNDARY_AREA_RESTRAINT_*`) exist on all six versions, but store an
   INTEGER whose correspondence to the members of `TranslationRotationValue`
   Autodesk documents nowhere. A witness that signs "the support on this beam
   exists" in a case where an ordered pinned support could have become
   fixed is a showroom, not proof: in a structural model this is the
   difference between a structure that works and one that does not. WHAT
   WOULD LIFT THE REFUSAL: one live run that sets three known values and
   reads the parameter back — after it, the correspondence is MEASURED, and
   the witness is written mechanically.

3. The moment for a line load and an area load. For the line load it is
   passed as ZERO (the argument is required), the area load does not have it
   at all. Zero in any units is zero, so the question of a moment-per-meter
   unit does not arise here, and a torsional line load remains a NAMED gap, not a silent one.
"""
# 🔴 PROVENANCE WAS MOVED OUT OF THE DOCSTRING ON 2026-09-01 — THE DOOR
# VERSUS THE JOURNAL. A module's docstring is a PUBLIC DOOR: `help()` prints
# it to a reader of the published package, and our machine's address tells
# them nothing. The knowledge is not erased — it is here, in the journal, where it belongs:
#     the live Roslyn against which the signatures were checked — localhost:52412
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/...)

#: The ceiling of a force component's magnitude. Not an engineering bound but
#: a bound on GARBAGE: 1e8 N is a hundred thousand tonnes-force, orders of
#: magnitude above anything that occurs in a project. The number nonetheless
#: WORKS rather than decorates: the force tolerance is derived from it (see
#: the module header — 1e8 · 3.3e-16 = 3.3e-8, the nearest round decade above
#: it is 1e-6). Lowering the bound would obligate lowering the tolerance too.
_FORCE_LIMIT = 100_000_000

#: The force/moment tolerance, DERIVED from `_FORCE_LIMIT` and binary
#: floating-point arithmetic. The same for all three loads, because the
#: derivation is the same one: they share the range's bound and the value's
#: path through UnitUtils.
_FORCE_TOL = 1e-6

OPS = [
    # ── Point load ──────────────────────────────────────────────────
    # The simplest of the three and therefore first: it sets the shape for
    # the whole wave — its own work plane, a pinned frame of reference, a
    # force vector in SI, a named load case, and a witness that reads
    # `Point` / `ForceVector` / `MomentVector` / `OrientTo` / `LoadCaseId` /
    # `GetTypeId` from the BUILT element, rather than confirming that the call happened.
    OpSpec(
        name="create_point_load",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("xyz", "pt_xyz", required=True),
            ParamSpec("fx_n", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fy_n", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fz_n", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("mx_nm", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("my_nm", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("mz_nm", "num", min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("load_case", "sel", required=True),
            ParamSpec("load_type", "sel"),   # omitted -> sole entry, else AMBIGUOUS
        ),
        capability=(("create", "load"),),
        post=("point load exists; Point of the built element == xyz "
              "(VertexTolerance, 3D, geometry); OrientTo of the built element "
              "== Project (semantic); ForceVector of the built element == "
              "[fx_n, fy_n, fz_n] newtons (±0.000001, semantic); MomentVector "
              "of the built element == [mx_nm, my_nm, mz_nm] newton-metres "
              "(±0.000001, semantic); load case of the built element == "
              "resolved load_case (semantic); load_type of the built element "
              "== resolved load_type (semantic)"),
        writes_model=True,
        grounded=(("load_case", "load_cases", True),
                  ("load_type", "point_load_types", False)),
        tolerances={"force_n": _FORCE_TOL, "moment_nm": _FORCE_TOL},
    ),
    # ── Line load ──────────────────────────────────────────────────
    # Both ends are THREE-DIMENSIONAL, for the same reason as in create_beam:
    # a linear load also lies on a sloped element, and a silently appended
    # zero Z would place it at absolute elevation 0. The work plane is built
    # through BOTH ends (horizontal if the elevations are equal; vertical
    # containing the segment otherwise) — computed in Python, literals travel to C#.
    #
    # `IsUniform` is read back and checked separately: the overload accepts
    # ONE force vector, i.e. uniformity is a promise of OUR call shape, and
    # if Revit did not preserve it, the load came out different while the geometry stayed green.
    OpSpec(
        name="create_line_load",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("p0_mm", "pt_xyz", required=True),
            ParamSpec("p1_mm", "pt_xyz", required=True),
            ParamSpec("fx_n_per_m", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fy_n_per_m", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fz_n_per_m", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("load_case", "sel", required=True),
            ParamSpec("load_type", "sel"),
        ),
        capability=(("create", "load"),),
        post=("line load exists; StartPoint and EndPoint of the built element "
              "== p0_mm and p1_mm (VertexTolerance, 3D, geometry); OrientTo of "
              "the built element == Project (semantic); ForceVector1 of the "
              "built element == [fx_n_per_m, fy_n_per_m, fz_n_per_m] newtons "
              "per metre (±0.000001, semantic); IsUniform of the built element "
              "(semantic); load case of the built element == resolved "
              "load_case (semantic); load_type of the built element == "
              "resolved load_type (semantic)"),
        writes_model=True,
        grounded=(("load_case", "load_cases", True),
                  ("load_type", "line_load_types", False)),
        tolerances={"force_n_per_m": _FORCE_TOL},
    ),
    # ── Area load ─────────────────────────────────────────────────
    # The ring is flat and horizontal at elevation `elev_mm`: the overload
    # takes an `IList<CurveLoop>` and derives the plane from them itself, so
    # it has no plane argument and there is nothing to author.
    #
    # THE WITNESS READS THE RINGS, NOT THE AREA. `AreaLoad.Area` travels into
    # the receipt, but it is NOT a requirement: it is a quantity Revit
    # DERIVES from the very rings the witness has already pinned
    # vertex-by-vertex — checking it separately would mean introducing a
    # second (area) tolerance for the sake of a consequence of an already-
    # checked fact. The vertex check, meanwhile, is NOT POSITIONAL:
    # `CurveLoop` canonicalizes the ring (the starting vertex and the
    # traversal direction are Revit's business), so every ordered vertex is
    # searched for AMONG the returned ones, and only their COUNT is required to match.
    OpSpec(
        name="create_area_load",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("outline", "pts", required=True),
            ParamSpec("elev_mm", "mm", required=True,
                      min_val=-1_000_000, max_val=1_000_000),
            ParamSpec("fx_n_per_m2", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fy_n_per_m2", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("fz_n_per_m2", "num",
                      min_val=-_FORCE_LIMIT, max_val=_FORCE_LIMIT),
            ParamSpec("load_case", "sel", required=True),
            ParamSpec("load_type", "sel"),
        ),
        capability=(("create", "load"),),
        post=("area load exists; GetLoops of the built element returns one "
              "loop whose vertices are the outline at elev_mm, same count "
              "(VertexTolerance, 3D, geometry); OrientTo of the built element "
              "== Project (semantic); ForceVector1 of the built element == "
              "[fx_n_per_m2, fy_n_per_m2, fz_n_per_m2] newtons per square "
              "metre (±0.000001, semantic); load case of the built element == "
              "resolved load_case (semantic); load_type of the built element "
              "== resolved load_type (semantic)"),
        writes_model=True,
        grounded=(("load_case", "load_cases", True),
                  ("load_type", "area_load_types", False)),
        tolerances={"force_n_per_m2": _FORCE_TOL},
    ),
    # ── Path of Travel ───────────────────────────────────────────────────────
    # The ONLY operation of this wave alive on all six versions
    # (`PathOfTravel.Create` has existed since 2020 and hasn't changed), and the
    # only one whose GEOMETRY IS NOT COMPUTED BY US. Hence the honest boundary
    # of the promise, written out right here:
    #
    # WHAT IS ASSERTED. The calculation finished successfully (the
    # `PathOfTravelCalculationStatus` enum is identical across all six
    # versions, and everything except `Success` is a typed refusal BEFORE
    # postconditions); the route belongs to the ordered view; its ends are the
    # ordered points; the route is non-empty and its total length is NOT LESS
    # than the straight line between the ends.
    #
    # WHAT IS NOT ASSERTED, AND WHY. The route's shape is Revit's output given
    # the view's obstacles, and "did it go around them correctly" is
    # inexpressible: we have no independent model of the obstacles, and
    # comparing Revit's output to Revit's output is meaningless. Length is
    # checked by INEQUALITY, not equality, and this is not a weakness of the
    # check but its exact boundary: "path shorter than the straight line" is a
    # geometrically impossible state, i.e. a genuine refusal, whereas any
    # specific expected number would have been invented.
    #
    # THE Z COORDINATE IS NOT CHECKED PER DOCUMENTATION, NOT OUT OF LENIENCY:
    # Autodesk states verbatim that "The input Z coordinates are ignored and
    # set to the view's level elevation". That is why the parameter kind here
    # is `pt_xy`: the fact that "this operation has no third coordinate" is
    # written into the TYPE, not into prose that might go unread.
    OpSpec(
        name="create_path_of_travel",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            ParamSpec("in_view", "target_w", required=True),
            ParamSpec("p0_mm", "pt_xy", required=True),
            ParamSpec("p1_mm", "pt_xy", required=True),
        ),
        capability=(("create", "path_of_travel"),),
        post=("path of travel exists and its calculation status is Success; "
              "PathStart and PathEnd of the built element == p0_mm and p1_mm "
              "in plan (VertexTolerance, geometry, Z excluded — the API "
              "replaces it with the view level elevation); the route read back "
              "is non-empty and no shorter than the straight line between the "
              "requested points (geometry); OwnerViewId of the built element "
              "== in_view (topology)"),
        writes_model=True,
    ),
]
