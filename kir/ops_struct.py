"""ops_struct — structural ops (beams/foundations/rebar). wave/struct
(2026-07-17): create_beam + create_foundation. Rebar stays STUB (out of this
wave's scope — see wave report).

Registry module — see REGISTRY_MODULES.md. Add ops HERE, not in spec.py.

create_beam: FamilyInstance over a line, StructuralType.Beam — the same
NewFamilyInstance(Line, FamilySymbol, Level, StructuralType) overload the
gold SDK sample CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs
uses (PlaceBeam(), verified locally at
the Revit SDK samples snapshot,
Samples/CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs
lines 376-388: `Line line = Line.CreateBound(...); ... NewFamilyInstance(line,
beamType, topLevel, StructuralType.Beam);` with an IsActive/Activate() guard
— exactly authoring.py's existing _symbol_res() helper). Version-safe
2021-2026: same overload family create_column already relies on, only the
StructuralType enum member differs.

p0_mm/p1_mm are REQUIRED 3D (pt_xyz, like create_pipe) rather than 2D-plus-
level-elevation (like create_wall): a beam's two ends commonly sit at
DIFFERENT elevations (sloped beam / connecting columns whose tops differ),
so silently defaulting a missing Z to 0 (authoring._pt3's existing behavior
for a bare-2D point) would place a beam at absolute Z=0 while the resolved
level sits at its own elevation — a silent-wrong floating beam, exactly the
class of bug this project exists to kill. authoring.validate()'s dims-by-
name dispatch (`dims = (3,) if name in ("create_pipe", "create_duct",
"create_cable_tray") else (2, 3)`) is name-hardcoded to a tuple that does
NOT include create_beam; "create_beam" must be appended to that tuple for
the 3D requirement to actually be enforced (currently a (2,3) fallthrough
would silently accept a 2D point here too). This is a ONE-TOKEN additive
touch to a shared line in authoring.py, made alongside the _EMITTERS
registration (same file already gets touched per every prior wave's
precedent — see wave/mep's authoring.py diff) — flagged explicitly in the
wave report as a real, unavoidable shared-file dependency, not invented
scope-creep.

create_foundation: TWO real, distinct structural varieties, discriminated by
`variety` (NOT named "kind" — see naming note below):
  - variety="isolated" (a spread footing under a column/point): FamilyInstance placed
    at a point, StructuralType.Footing. Mirrors create_column's point-
    placement shape exactly (NewFamilyInstance(XYZ, FamilySymbol, Level,
    StructuralType)), enum member swapped Column->Footing. StructuralType.
    Footing verified as a REAL enum member via local SDK grep (BoundaryConditions/
    CS/{BoundaryConditionsData,Command}.cs read/filter it off existing
    instances — no local sample CREATES one, so the create-side call is
    confident-by-overload-analogy + enum-verified, not sample-verified;
    flagged in the wave report per the task's own escape hatch).
  - variety="slab" (strip/mat — modeled as a structural mat/strip
    footing, i.e. a structural Floor by contour): this IS create_floor's
    existing structural=True path (create_floor's own post-condition already
    says "structural flag == requested (semantic)" — a foundation slab is
    that op with structural forced True). Reused, not duplicated: struct_emit.
    _emit_foundation_slab mirrors _emit_floor's 2022+/2021 structural path at
    the same fidelity (see struct_emit.py's module docstring for why it's a
    mirror, not a cross-import of a private function). No new C# geometry
    logic invented for this variant.
  - a true ribbon/grillage foundation (real grillage geometry: varying
    width along a beam-like path, stepped sections) is NOT modeled: no
    confident single-call Revit API shape and no local gold sample to check
    against. FOUNDATION_UNSUPPORTED_KIND (struct_emit.py) is the typed
    refusal for any variety outside the closed {isolated, slab} enum — never
    a silent guess.

create_wall_foundation: A NEW OP, NOT A THIRD VARIETY OF create_foundation
— and this is a decision, not a taste. A strip (wall) foundation
(WallFoundation) shares NOT ONE parameter with create_foundation: it has
neither a point, nor a contour, nor a level — its entire input is the HOST
WALL, which itself carries the level, the path, and the extent. And
`create_foundation.level` is declared required=True; a third branch would
force loosening it to optional (as had to be done for
`create_railing.level`), and then a missing level on the isolated/slab
branches would stop being the hard refusal "level is required" and would
travel by the general rule "the only one in the pool" — i.e. it would be
silently substituted in a model with a single level. Extending the
enumeration would TAKE AWAY strictness from branches that already work,
for the sake of a branch that does not need a level at all; a separate op
takes nothing away.

API MEASUREMENT (compiled on :52412, 2021-2026, 09.08 — the arbiter here is
the compiler, not the XML; see CLAUDE.md on SpatialElementTag):

  WallFoundation.Create(Document, ElementId typeId, ElementId wallId)  → 6/6
  WallFoundation.WallId                                                → 6/6
  ElementTypeGroup.WallFoundationType                                  → 6/6
  FilteredElementCollector(doc).OfClass(typeof(WallFoundationType))    → 6/6
  WallFoundation.GetHostIds()                    → 0/6  CS1061, DOES NOT EXIST
  WallFoundation.WallAllowsWallFoundation(Wall)  → 0/6  CS0117, DOES NOT EXIST

The last two lines are a correction of the input task, not pedantry. Both
names exist, but on a DIFFERENT class: `WallSweep.GetHostIds()` and
`WallSweep.WallAllowsWallSweep(Wall)` (grepped across RevitAPI.xml of all
six versions, confirmed by compilation). This means there is no
PRE-FLIGHT check at all in the API for "can a foundation be hung on this
wall", and it must not be invented: the only available protection is a
typed refusal after the fact (`as Wall` gives null, or Create returns
null).

WHY THE PARAMETER IS CALLED `wall`, NOT `host`. This is how the API itself
names it (the argument `wallId`, the property `WallFoundation.WallId`), so
the witness reads a property with the same name as the parameter. There is
also a second consequence, stated outright so it does not read as a way
around the rule: authoring_validation.py holds the rule "`host` is
ref-only" with a named list of exceptions, and it concerns HOSTING BY
GEOMETRY (door/window/panel/opening/railing — the emitter itself computes
the insertion point inside the host). A strip foundation has not a single
line of placement geometry: the wall is an ordinary call argument. Both
roads (the name `wall`, or `host` plus a line in the exception list) give
ONE AND THE SAME semantics of "ref OR element_id", and it is mandatory
here: a foundation is placed under an EXISTING wall no less often than
under one built by this same program — the same argument by which
create_opening fought off the ref-only requirement.

THE GEOMETRY IS NOT CHECKED, AND THIS IS STATED IN `post`. There is
deliberately NO bounding-box witness here: the relationship of the footing
to the wall (side overhang, extension past the ends, bottom elevation) is
NOT MEASURED on any building — across all 60+ saved decompiles on disk
there is NOT A SINGLE WallFoundation (checked by grep on 09.08), so there
is nowhere to take a number from. A tolerance derived by reasoning is
exactly `create_door.sill_mm min_val=0` (140 negative elevations out of
151 in a real building) and `_SHEET_LIMIT_MM` (10 m on a building where
walls stand at 82-110 m). A missing check is more honest than an invented
one, and a check that cannot fail is worse than none at all. Closing this
gap takes ONE live run, not another hour of reasoning.

WHAT REMAINS CLOSED: FOUNDATION_UNSUPPORTED_KIND on create_foundation is
UNTOUCHED. A grillage foundation and a pile are still refused:
`Autodesk.Revit.DB.Foundation` has not a single documented method, and
there is no "Grillage"/"Pile" factory anywhere in the API. This wave
closes exactly the strip case — the one that has a single call, and it is
identical on all six versions.

create_beam_system / create_truss: THE FRAMING WAVE (09.08.2026). The
census found both operations NEVER CONSIDERED, and both close one and the
same hole: before them the only way to say "there is a framing system by
sketch here" was a batch of separate create_beam calls with fixed
coordinates — i.e. the loss of the OBJECT itself and of its layout.

API MEASUREMENT (compiled on :52412 against real assemblies 2021-2026,
09.08 — the arbiter is the compiler, not the XML):

  BeamSystem.Create(Document, IList<Curve>, Level, XYZ, bool)        → 6/6
  BeamSystem.Create(Document, IList<Curve>, Level, int, bool)        → 6/6
  BeamSystem.Create(Document, IList<Curve>, SketchPlane, XYZ, bool)  → 6/6
  BeamSystem.Create(Document, IList<Curve>, SketchPlane, int)        → 6/6
  BeamSystem.Profile (CurveArray) / GetBeamIds() (ICollection)       → 6/6
  BeamSystem.Direction / .Elevation / .Level / .LayoutRule           → 6/6
  BeamSystem.BeamType — read AND WRITTEN (FamilySymbol)              → 6/6
  Truss.Create(Document, ElementId, ElementId sketchPlaneId, Curve)  → 6/6
  Truss.Curves (CurveArray) / Truss.Members (ICollection<ElementId>) → 6/6
  TrussType : FamilySymbol (IsActive/Activate/Family)                → 6/6
  SketchPlane.Create(Document, ElementId of the level)               → 6/6
  BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM               → 6/6
  ElementTypeGroup.BeamSystemType                                    → 6/6

  IList<Curve> x = beamSystem.Profile          → 0/6  CS0266 (this is CurveArray)
  truss.Members.Size                           → 0/6  CS1061 (not ElementIdSet)
  ElementTypeGroup.TrussType                   → 0/6  CS0117, DOES NOT EXIST
  ElementTypeGroup.StructuralFramingType       → 0/6  CS0117, DOES NOT EXIST
  BuiltInParameter.BEAM_SYSTEM_LEVEL_PARAM     → 0/6  CS0117, DOES NOT EXIST
  BuiltInParameter.BEAM_SYSTEM_ELEVATION_PARAM → 0/6  CS0117, DOES NOT EXIST

The bottom six lines are not pedantry, each closed off a temptation. The
level of a beam system is read as a PROPERTY (it has no BIP chain at
all); the truss type and the "default beam type" cannot be asked of the
document BY CONSTRUCTION (as with the door and the window — see NAMED
DEFAULT in ir/CLAUDE.md), and `Members` is counted with `.Count`, not
`.Size`.

THE BEAM SYSTEM'S PROFILE IS A NATURAL CONSUMER OF CONTOUR, AND THIS IS A
MEASUREMENT, NOT AN ANALOGY. The canonical form of CONTOUR is a closed
list of edges [(p0,p1,bulge)], with a Line when bulge==0 and Arc.Create
from three literal points otherwise; the `profile` argument of
`BeamSystem.Create` is an `IList<Curve>` made of exactly such curves.
Everything matches, except for ONE thing: a region has `holes`, and the
call has no second-ring argument on any version. So `profile` is declared
of kind `region` (and gets, for free, point addressing from grids, the
laws of arcs, zero-length edges, self-intersection, and degenerate area —
ground.py lowers ANY parameter of this kind), and holes are refused with a
type (KIR-E008). A truss does not need CONTOUR at all: its input is ONE
straight line (`Curve`, «must be a line, must not be vertical, must be
within the sketch plane»), i.e. p0/p1 + a level.

WHAT REVIT COMPUTES IS NOT CHECKED — and this is stated in `post` as a
separate clause. The number and spacing of the beams is chosen by
`LayoutRule`, which NO argument of `Create` sets: the author named no
quantity, and demanding one would mean repeating the `height_mm` defect
(31.07, correctly built facade walls were rolled back). What is checked is
the RESULT ordered by the very fact of the operation: `GetBeamIds()` is
not empty, `Members` is not empty. Zero is a genuine outcome (the profile
is smaller than the layout spacing), and from the outside it is
indistinguishable from success.

create_area_reinforcement: THE REINFORCEMENT WAVE (10.08.2026). The census
found `Rebar`, `AreaReinforcement`, `PathReinforcement`, `FabricArea`,
`FabricSheet`, `StructuralConnectionHandler`, and three kinds of
`BoundaryConditions` NEVER CONSIDERED. All nine were measured (table
below), and ONE was taken — the one whose witness reads the RESULT and can
FAIL.

API MEASUREMENT (compiled on :52412 against real assemblies 2021-2026,
10.08 — the arbiter is the compiler, not the XML; see CLAUDE.md on
SpatialElementTag):

  AreaReinforcement.Create(Document, Element, XYZ, ElementId×3)      → 6/6
  AreaReinforcement.Create(Document, Element, IList<Curve>, XYZ, ×3) → 6/6
  AreaReinforcement.GetHostId() / .GetTypeId()                       → 6/6
  AreaReinforcement.GetRebarInSystemIds() / .GetBoundaryCurveIds()   → 6/6
  AreaReinforcement.Direction / .AreaReinforcementType               → 6/6
  RebarHostData.IsValidHost(Element)  — A PRE-FLIGHT check!          → 6/6
  ReinforcementSettings.GetReinforcementSettings(doc)
      .HostStructuralRebar                                          → 6/6
  RebarInSystem.GetTypeId() / .SystemId / .GetHookTypeId(int)        → 6/6
  ElementTypeGroup.AreaReinforcementType / .RebarBarType             → 6/6
  FilteredElementCollector by AreaReinforcementType / RebarBarType /
      RebarHookType                                                  → 6/6

  AreaReinforcement.GetNumberOfLines()          → 0/6 (2021 CS1061, 2022+
                                                  requires AreaReinforcement-
                                                  LayerType — which does NOT
                                                  exist at all on 2021,
                                                  CS0103)
  AreaReinforcement.GetLayerDirection(int)      → 5/6 (absent on 2021)
  BuiltInParameter.REBAR_BAR_TYPE               → 0/6  CS0117, DOES NOT EXIST

The bottom three lines are not pedantry. THE ENTIRE PER-LAYER SLICE OF THE
API (line count, layer direction, layer activity) is absent on 2021, and
on 2022+ it is keyed by an enum that does not exist on 2021: a witness
that reads the layer would work on five versions out of six — exactly an
"instrument for part of the range", which in this house is more dangerous
than a missing one. So there is NO per-layer witness here, and this is
stated, not silently omitted. The bar type is asked not through a
parameter (there is none), but from the bar itself —
`RebarInSystem.GetTypeId()`.

THE OVERLOAD BY HOST BOUNDARY WAS TAKEN, NOT BY CURVES, and this is a
decision about HONESTY. Both compile 6/6. But the overload with
`IList<Curve>` requires the curves to LIE IN THE PLANE OF THE HOST FACE,
and CONTOUR is a horizontal flat sketch without an elevation: its Z would
have to be derived at runtime from the floor's own sketch plane (level +
FLOOR_HEIGHTABOVELEVEL), i.e. introducing YET ANOTHER unmeasured seam for
a shape nobody has checked. The overload by host boundary has no such
seam at all: the boundary is computed by Revit from the host itself, and
there is not a single quantity of authored geometry in the operation.
"Reinforce this slab" is exactly the basic RC (reinforced-concrete) case.

THIS OP HAS NOT A SINGLE TOLERANCE, AND THIS IS A MEASUREMENT, NOT AN
OMISSION. All four checks are id equalities and a counter, i.e. topology
and semantics, not measurement. There is deliberately no geometric
witness here: across 38 saved decompiles with a census on disk there are
ZERO elements of OST_AreaRein, OST_PathRein, OST_Rebar, OST_FabricAreas,
and OST_FabricReinforcement (measured 10.08 from the census records of the
whole corpus), so there is nowhere to take a number from. A tolerance
derived by reasoning is exactly `create_door.sill_mm min_val=0` (140
negative elevations out of 151) and `_SHEET_LIMIT_MM` (10 m on a building
with walls at 82-110 m). A missing check is more honest than an invented
one.

WHY THE "BARS ARE PLACED" WITNESS IS CONDITIONAL, NOT UNCONDITIONAL.
Autodesk writes about `GetRebarInSystemIds` in plain text: «The
RebarInSystem elements are only created if
ReinforcementSettings.HostStructuralRebar is set to true. If that setting
is false, this function returns an empty array». An unconditional
"non-empty" would reject CORRECTLY built reinforcement in every document
where this setting is off — i.e. it would be a check that rejects working
behavior (the class of "acceptance broke on Cyrillic"). The setting is
read from the document by the same call and decides whether to require
it; its value and the bar count always go into the receipt, so a bar
count of zero is never silent.

WHY THE HOST MUST BE HORIZONTAL (`Floor`), AND THIS IS A REFUSAL, NOT A
LIMITATION OUT OF LAZINESS. A wall's `majorDirection` must lie IN THE
PLANE OF THE WALL — a vertical one. A plan angle does not determine it:
for a wall along Y, an angle of 0° projects to ZERO (Revit throws an
exception — that is the lucky case), and for a wall at 45° it projects to
something nonzero and NOT what the author meant — i.e. it silently gives
a wrong result. Reinforcing a wall requires addressing direction in its
own plane; that is separate work, not a field of this op. The refusal is
typed (AREA_REINF_HOST_NOT_HORIZONTAL) and names the next move.

WHAT IS REFUSED BY NAME IN THIS WAVE (each refusal with a MEASURED
reason):

  * `Rebar` — the factories exist (`CreateFromCurves` 6/6 in the long
    overload, `CreateFromRebarShape` 6/6, `CreateFreeForm` 6/6), the
    witness is excellent (`GetCenterlineCurves` 6/6 reads the bar's real
    centerline). NOT TAKEN because of the `norm` argument — the normal to
    the bar's plane: for a STRAIGHT bar it is not determined by anything
    (there are infinitely many perpendiculars to a segment), and choosing
    it on the author's behalf means assigning a quantity that determines
    the orientation of the hooks and the bar's cross-sectional view. The
    short overload, where this role is taken by `BarTerminationsData`,
    exists ONLY on 2026 (1/6, CS0246 on 2021-2025 — measured). The op will
    become legitimate when KIR gains a way to name the plane, not when
    someone picks a vector for it.
  * `PathReinforcement` — `Create` 6/6, `GetHostId`/`GetCurveElementIds`/
    `GetRebarInSystemIds` 6/6. NOT TAKEN: it has NO overload without
    curves on any version, and the curves must lie in the plane of the
    host face — the very same unmeasured Z seam because of which the
    contour overload of area reinforcement was also refused here. Exactly
    one live run closes both.
  * `FabricArea` — `Create` 6/6 for both overloads, `HostId` /
    `GetFabricSheetElementIds` / `GetTotalSheetMass` 6/6. NOT TAKEN by
    PRIORITY, not by impossibility: its shape matches the taken operation
    one-to-one (host + major direction + two types), and a second copy of
    the same skeleton before the first live run of the first one is five
    plausible things instead of one proven thing. The line is held back
    until the run.
  * `FabricSheet` — `Create(Document, Element, ElementId)` 6/6, but the
    call has NOT A SINGLE position argument: exactly where the sheet
    lands is decided by Revit, and it can only be shifted with
    `PlaceInHost(Element, Transform)` — an argument of kind `Transform`,
    which KIR does not have at all (measured: XYZ does not convert to it,
    CS1503 6/6). The author cannot name the position, so there is nothing
    to check it against either.
  * `StructuralConnectionHandler` — `Create` 6/6, `CreateGenericConnection`
    6/6, `GetConnectedElementIds` 6/6. And this is the ONLY candidate of
    the wave that has live elements in the corpus (OST_StructConnections:
    3,396 of them in a single building, across 12 decompiles). NOT TAKEN,
    because the witness is DEGENERATE: `GetConnectedElementIds()` returns
    exactly the list that was fed into `Create` — a check that cannot
    fail, and such a check is worse than none at all. Everything else
    about the connection (`IsCustom()`/`IsDetailed()` — METHODS, not
    properties, measured CS0119 6/6) describes the type, not the result.
    Plus a documented refusal, «Missing detailed structural connection
    service implementation»: detailed connections require the Steel
    Connections add-on, whose presence cannot be read from the snapshot.
  * `BoundaryConditions` (three kinds) — `NewLineBoundaryConditions` and
    `NewAreaBoundaryConditions` take an `Element` 6/6, but
    `NewPointBoundaryConditions` HAS NO overload with `Element` at all
    (CS1503 6/6): it needs a geometric `Reference` to the END OF AN
    ANALYTICAL LINE. There is NO idiom that gives such a reference on all
    six versions: `AnalyticalModel` is inaccessible on 2023-2026 (CS0122),
    and `AnalyticalMember` is absent on 2021 (CS0234) and inaccessible on
    2022 (CS0122) — the analytical world split apart in 2023, and the op
    would have to be written in two different languages. On top of that,
    the API itself says: «This method will only function with the
    Autodesk Revit Structure application» — a precondition the compiler
    checks nothing about. There are ZERO OST_BoundaryConditions elements
    in the corpus.

NAMING NOTE: the discriminator param is "variety", not "kind" — this
registry reserves "kind" as a vocabulary word for ParamSpec.kind=="kind_enum"
(the closed Revit-object-kind table wall/door/floor/.../other, SPEC 12.8),
and test_invariants.py's test_schema_generates_and_is_closed asserts BY
PROPERTY NAME that any op-schema field literally called "kind" carries
spec.KIND_ESCAPE in its enum — a real, deliberate safety invariant (every
closed-kind-enum must have an escape hatch so an unrecognized category never
silently guesses) enforced by name-match rather than by ParamSpec.kind value.
A param named "kind" holding {"isolated","slab"} (no escape value — this
wave has no honest escape/other bucket for foundation variety, unlike a
Revit-object-kind table) would collide with that invariant and is a correct
FAIL, not a test bug to route around by loosening the shared test. Renamed
instead — the honest fix.
"""
# 🔴 PROVENANCE MOVED OUT OF THE DOCSTRING ON 01.09.2026 — THE DOOR VERSUS
# THE JOURNAL. A module docstring is a PUBLIC DOOR: `help()` prints it to
# the reader of the published package, and our machine's address tells
# them nothing. The knowledge is not erased — it is here, in the journal,
# where it belongs:
#     the local copy of the SDK samples against which PlaceBeam() was
#     checked:
#     /root/27B/harvest/sdk_samples/snapshot/2025/Samples/
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/LIST_*/...)
from kir.geom import MAX_RING_POINTS  # authority over the ring boundary

OPS = [
    OpSpec(
            name="create_beam",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("p0_mm", "pt_xyz", required=True),
                ParamSpec("p1_mm", "pt_xyz", required=True),
                # 19.08, A CORRECTION TO MYSELF, LIFTED BY A LIVE
                # EXPERIMENT AN HOUR LATER.
                #
                # At first I marked this field simply `DERIVED_BY_REVIT`,
                # relying on the 27.07 note ("Revit derives the reference
                # level from the curve's elevation, the argument decides
                # nothing"). The note is TRUE and INCOMPLETE, and the
                # incompleteness costs exactly what this project exists
                # for.
                #
                # A control experiment on a live model: two beams of the
                # same geometry at the «Этаж 9» elevation, differing ONLY
                # in the `level` argument.
                #   304398  level=«Этаж 9»   AGREES        -> Host = «Этаж 9»
                #   304400  level=«Кровля»   CONTRADICTS   -> Host = MISSING
                # For BOTH, `INSTANCE_REFERENCE_LEVEL_PARAM` = «Этаж 9»
                # @32700, and for both, `Element.LevelId` = -1. That is,
                # the reference level is derived from the curve identically
                # — the registry is right — but the BINDING TO THE DATUM is
                # decided by exactly the argument declared to decide
                # nothing.
                #
                # The cost: 31 beams out of 31 whose argument contradicted
                # the curve were left WITHOUT A HOST, with a green witness
                # and correct geometry. Such a beam will not travel with
                # the level — i.e. exactly the editability for which a
                # level is a RELATIONSHIP, not a number, is dead. Only the
                # building graph saw this: the witness reads the reference
                # level (it matches), the judge's read reads the geometry
                # (it is correct), and only the `host` edge diverges.
                #
                # The field remains `DERIVED_BY_REVIT`: that is the truth
                # about the VALUE of the reference level, and the witness
                # generator must keep refusing to build a comparison on it
                # (otherwise vacuousness: we send a curve, we read the
                # level derived from it). But the CONTRADICTION between the
                # argument and the curve's elevation is a separate
                # observable outcome, and it must become an obligation of
                # `host exists`, not a comment. The claim is named here,
                # the work is not done.
                ParamSpec("level", "sel", required=True,
                          authority="DERIVED_BY_REVIT",
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # named "symbol" (not "type"): a beam is a FamilyInstance, so
                # its type-selector resolves to a FamilySymbol via the SAME
                # shared _symbol_res()/IsActive-Activate() helper create_column/
                # create_window/create_door/place_family already use (which
                # hardcodes the param key "symbol") — "type" is reserved in
                # this registry for ElementType-based ops (wall/floor/roof)
                # with different resolution semantics (doc-default support a
                # FamilySymbol selector doesn't have). Consistent naming, not
                # an arbitrary choice.
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),        # omitted -> sole snapshot entry, else AMBIGUOUS
            ),
            capability=(("create", "element"),),
            post=("beam exists (materialize); LocationCurve endpoints == p0/p1 (±5mm, 3D) — "
                  "положение пришпилено целиком именно здесь (geometry); опорный уровень "
                  "СУЩЕСТВУЕТ (topology), но КАКОЙ — выводит Revit из отметки "
                  "кривой, а не из аргумента level: замерено 27.07, передан "
                  "L_01 @ 0 при кривой на Z=3000 -> привязка к L_01ДОО1_+2.500. "
                  "Полученный уровень читается в свидетель "
                  "(reference_level_id/reference_level), а не навязывается; "
                  "StructuralType == Beam (semantic) (witness)"),
            writes_model=True,
            # 03.08: the promised ±5 mm LIVE HERE.  Before this, `post`
            # promised a number the registry could not name, while the
            # emitter stamped tol_key="endpoint_mm" — a reference into a
            # void (the create_type defect, verbatim).  The number is THE
            # SAME one that stood as a literal in struct_emit.
            tolerances={"endpoint_mm": 5.0},
            grounded=(("level", "levels", True), ("symbol", "beam_types", False)),
        ),
    OpSpec(
            name="create_foundation",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                ParamSpec("variety", "enum", required=True,
                          choices=("isolated", "slab")),
                # isolated-only:
                ParamSpec("xy", "pt_xy"),
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),         # omitted -> sole snapshot entry
                # slab-only (mirrors create_floor's own outline/holes/type):
                ParamSpec("outline", "pts"),
                ParamSpec("holes", "pts_list"),     # 2022+ only, same as create_floor
                ParamSpec("type", "sel"),           # omitted -> doc default floor type
                # shared:
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
            ),
            capability=(("create", "element"),),
            post=("variety=isolated: footing exists; LocationPoint == xy (±5mm); "
                  "base level == resolved level (topology, BIP chain); "
                  "StructuralType == Footing (semantic, witness). "
                  "variety=slab: structural floor exists; level binding == resolved "
                  "level (topology); bbox XY extents == outline extents (±50mm); "
                  "sketch loop count and per-loop vertex multiset == "
                  "outline plus holes on the ±1mm canon grid (geometry); "
                  "structural flag forced true (semantic) — this IS create_floor's "
                  "structural path, reused not duplicated. "
                  "any other variety value -> typed refusal (KIR-E004), never a guess"),
            writes_model=True,
            # 03.08: both promised quantities — one per variety.
            # `location_mm` — the point of a stand-alone spread footing
            # (±5 mm), `bbox_mm` — the slab's bounding box (±50 mm, the
            # same key and the same number as create_floor: a foundation
            # slab IS a structural floor).  The numbers are the same ones
            # that stood as literals.
            tolerances={"location_mm": 5.0, "bbox_mm": 50.0,
                        "sketch_mm": 1.0},
            grounded=(("level", "levels", True),
                      ("symbol", "foundation_symbols", False),
                      ("type", "floor_types", False)),
        ),
    OpSpec(
            name="create_wall_foundation",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # The host wall. `target_w` + ref_kinds=WALL: a reference
                # into the program is allowed by the parameter's type
                # (otherwise KIR-L004 at the planning stage — a ref to a
                # non-wall is refused BEFORE emission), and element_id
                # remains legitimate because a foundation is also placed
                # under an already-standing wall. The name is from the
                # API, see the header.
                ParamSpec("wall", "target_w", required=True,
                          ref_kinds=(ReferenceKind.WALL,)),
                # A missing type -> THE DOCUMENT'S DEFAULT TYPE, as with
                # create_wall/create_floor and for the same reason: it IS
                # possible to ask Revit "what is your strip-foundation
                # type" — ElementTypeGroup.WallFoundationType compiles on
                # all six (measured above). The railing has no such branch
                # by construction, the ceiling has one and deliberately
                # does not take it; here it is taken, because the type
                # substitution is not silent: the semantic witness checks
                # the BUILT type against the requested one, and the receipt
                # carries type_name out.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"),),
            # WHAT IS PROMISED IS EXACTLY WHAT IS CHECKED, and a separate
            # clause names what is NOT checked. Staying silent about the
            # geometry would leave the reader thinking someone is guarding
            # it.
            post=("wall foundation exists (materialized or typed refusal); "
                  "WallId == host wall id, EXACT equality with no tolerance "
                  "(topology); "
                  "GetTypeId == requested wall foundation type (semantic); "
                  "geometry deliberately NOT witnessed on purpose — the "
                  "footing's projection beyond its wall and its underside "
                  "elevation are unmeasured (zero WallFoundation instances "
                  "across every stored decompile), and a bound authored by "
                  "reasoning is this compiler's own defect class"),
            writes_model=True,
            # Not a single tolerance, and this is not an omission: both
            # checks are EXACT (id equality), and there is no geometric
            # check here at all.
            tolerances={},
            grounded=(("type", "wall_foundation_types", False),),
        ),
    OpSpec(
            name="create_beam_system",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # THE PROFILE IS CONTOUR, AND THIS IS A MEASUREMENT, NOT A
                # TASTE (see the header). `region` gives, for free,
                # everything the sketch must be checked against BEFORE the
                # transaction: point addressing from grids, arcs by
                # bulge/radius, zero-length edges, self-intersection,
                # degenerate area. Its holes are REFUSED by the emitter —
                # the call does not accept them.
                ParamSpec("profile", "region", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # THE INDEX OF THE DIRECTION EDGE, not a vector. The
                # overload with `curveIndexForDirection` is chosen over the
                # overload with XYZ precisely because its precondition is
                # CHECKABLE AT COMPILE TIME: Autodesk requires the
                # direction curve to be STRAIGHT, and which edges of the
                # lowered contour are straight (bulge==0) is known in
                # Python. A vector, on the other hand, would have to be
                # checked against the witness through an angular tolerance
                # that nobody has measured.
                # The bound is DERIVED, not assigned: CONTOUR's `poly`
                # holds up to `MAX_RING_POINTS` points, i.e. no more edges
                # than that same number, and the largest index is one less.
                # 🔴 BEFORE 02.09.2026 THIS FIELD HELD `max_val=63` AS A
                # LITERAL NUMBER, and when the ring's cap was raised from
                # 64 to 256, the derived value stayed at the old one: a
                # contour of 100 points was legitimate, but edge 70 in it
                # COULD NOT be named. A derived quantity written down as a
                # number is not a derivation.
                ParamSpec("direction_edge", "int", min_val=0,
                          max_val=MAX_RING_POINTS - 1),
                # The same pool and the same name as create_beam: the
                # system's beams are ordinary structural FamilyInstances,
                # and the pool is already filtered by placement type
                # (open_model.py). A missing selector is resolved by the
                # general rule "the only one / most_used".
                ParamSpec("symbol", "sel", ref_kinds=(ReferenceKind.FAMILY_SYMBOL,)),
            ),
            capability=(("create", "element"), ("create", "geometry")),
            # WHAT IS PROMISED IS EXACTLY WHAT IS READ BACK. A separate
            # clause names what is NOT checked, and why.
            post=("beam system exists (materialized or typed refusal); "
                  "re-read Profile vertex bbox == lowered-edge vertex bbox "
                  "±50mm (geometry) — arc extrema between vertices stay "
                  "outside this witness on purpose, because C# reads the "
                  "returned curves by endpoints and the system's own "
                  "BoundingBox is a solid, not a sketch; "
                  "GetBeamIds is non-empty — Revit actually laid framing "
                  "(semantic); "
                  "BeamSystem.Level == resolved level (topology, exact id "
                  "equality); "
                  "BeamType == resolved symbol (semantic) — the emitter "
                  "assigns it, so demanding it back is fair; "
                  "beam count and spacing deliberately NOT gated (LayoutRule "
                  "is Revit's, nobody authored a number), and Direction / "
                  "Elevation ride the receipt instead of a demand; "
                  "profile loop vertex multiset == authored profile on "
                  "the ±1mm canon grid (geometry)"),
            writes_model=True,
            # ONE tolerance, and it is NOT a new number: the same key
            # `bbox_mm` = 50.0 as create_floor_by_contour and
            # create_ceiling, and the same comparison — the author's
            # sketch against the built result. Introducing our own number
            # here would mean assigning a boundary by reasoning.
            tolerances={"bbox_mm": 50.0, "sketch_mm": 1.0},
            grounded=(("level", "levels", True), ("symbol", "beam_types", False)),
        ),
    OpSpec(
            name="create_truss",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # TWO-DIMENSIONAL ENDPOINTS, AND THIS IS NOT A
                # SIMPLIFICATION. `Truss.Create` takes the sketch plane as
                # a separate argument and requires the base curve to LIE IN
                # IT; the plane here is the level's own plane
                # (SketchPlane.Create(doc, levelId)), so the endpoints' Z is
                # not a degree of freedom but a consequence. Accepting
                # pt_xyz would mean letting the author write a Z that the
                # emitter is obligated to ignore — exactly the opposite of
                # create_beam's argument, where the ends REALLY do sit at
                # different elevations.
                ParamSpec("p0_mm", "pt_xy", required=True),
                ParamSpec("p1_mm", "pt_xy", required=True),
                ParamSpec("level", "sel", required=True,
                          ref_kinds=(ReferenceKind.LEVEL,)),
                # The name is from the API (`trussTypeId`, the property
                # `Truss.TrussType`). A truss has NO default type:
                # ElementTypeGroup.TrussType does not compile on any of the
                # six versions (CS0117 6/6, measured 09.08) — exactly as
                # with the railing, and so an unresolved type here is a
                # typed refusal, not a substitution.
                ParamSpec("type", "sel"),
            ),
            capability=(("create", "element"),),
            post=("truss exists (materialized or typed refusal); "
                  "LocationCurve endpoints == p0/p1 ±5mm in plan (geometry); "
                  "both endpoint elevations == the level's own plane ±5mm "
                  "(geometry) — the sketch plane is the level's, so this is "
                  "the op's own promise and not Revit's inference; "
                  "GetTypeId == requested truss type (semantic); "
                  "Members is non-empty — Revit derived chords and webs "
                  "(semantic); "
                  "reference level link is REAL, and WHICH level rides the "
                  "receipt rather than a demand — same measured lesson as "
                  "create_beam, where forcing it rolled correct framing back; "
                  "the truss profile (chord shape, panel count, web layout) "
                  "belongs to the truss family and is deliberately ungated"),
            writes_model=True,
            # The number is THE SAME and the key is THE SAME as
            # create_beam: checking the author's segment against the
            # LocationCurve of the structural element is literally the
            # same comparison over the same quantities.
            tolerances={"endpoint_mm": 5.0},
            grounded=(("level", "levels", True), ("type", "truss_types", False)),
        ),
    OpSpec(
            name="create_area_reinforcement",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # THE HOST. `target_w` + ref_kinds=ELEMENT: reinforcement
                # is applied both to a slab built by this same program
                # (ref), and to an ALREADY-STANDING one (element_id) — the
                # latter is even more common, exactly as with
                # create_opening and create_wall_sweep. There is no
                # narrower class already: ReferenceKind only knows
                # ELEMENT/WALL/LEVEL/FAMILY_SYMBOL, and "floor" is not
                # expressible among them, so the host's horizontality is
                # checked by the EMITTER at runtime with a typed refusal,
                # not by the reference type system.
                ParamSpec("host", "target_w", required=True,
                          ref_kinds=(ReferenceKind.ELEMENT,)),
                # THE MAJOR DIRECTION IS MANDATORY, AND IT HAS NO DEFAULT.
                # The direction of the working reinforcement is the
                # professional essence of the operation: substituting it
                # silently would mean repeating the `height_mm` defect
                # (31.07), where CORRECTLY built walls were rolled back
                # over a value the author never named. A plan angle, not a
                # vector: for a horizontal host it is a single quantity,
                # whereas a vector would have to be checked against the
                # witness through an angular tolerance that nobody has
                # measured here.
                ParamSpec("direction_deg", "deg", required=True),
                # A missing type -> THE DOCUMENT'S DEFAULT TYPE:
                # ElementTypeGroup.AreaReinforcementType compiles on all
                # six (measured 10.08), exactly as for the strip
                # foundation. And the general rule "the only one in the
                # pool" would be THE WORST option here: a real RC project
                # has several reinforcement types, so an omitted `type`
                # would always refuse with KIR-G102.
                ParamSpec("type", "sel"),
                # The bar type is an ordinary pool, like `symbol` for a
                # beam: an omission is resolved by the general rule "the
                # only one / most_used", and the compiler's choice travels
                # into the receipt.
                ParamSpec("bar_type", "sel"),
                # A MISSING HOOK MEANS "NO HOOKS", and this is NOT our
                # invention: `InvalidElementId` in this argument is a
                # DOCUMENTED value of the API itself («If this parameter is
                # InvalidElementId, it means to create a rebar with no
                # hooks»). The general rule "the only one in the pool"
                # would substitute a hook here that the author never asked
                # for, and in a project with several hook types it would
                # simply refuse with KIR-G102 — losing the reinforcement
                # for nothing (the same argument as
                # create_topography.level).
                ParamSpec("hook_type", "sel"),
            ),
            capability=(("create", "element"),),
            # WHAT IS PROMISED IS EXACTLY WHAT IS READ BACK FROM THE
            # DOCUMENT, and separate clauses name what is NOT checked, and
            # why.
            post=("area reinforcement exists (materialized or typed refusal); "
                  "GetHostId == requested host id, EXACT equality with no "
                  "tolerance (topology); "
                  "GetTypeId == requested area reinforcement type (semantic); "
                  "when the document's ReinforcementSettings."
                  "HostStructuralRebar is true, GetRebarInSystemIds is "
                  "non-empty — Revit actually laid bars (semantic); zero is a "
                  "real outcome and is a VIOLATION only under that setting, "
                  "because Autodesk documents an empty array as correct when "
                  "it is false; "
                  "the bars' own GetTypeId == requested bar type (semantic) — "
                  "the emitter passes it, so demanding it back is fair; "
                  "major direction, bar count and the HostStructuralRebar "
                  "setting itself ride the receipt rather than a demand — "
                  "Revit normalises and projects the direction into the host "
                  "plane and there is no measured angular comparison rule; "
                  "geometry deliberately NOT witnessed on purpose — the "
                  "boundary is computed by Revit from the host, no dimension "
                  "is authored, and no stored decompile contains a single "
                  "reinforcement element to derive a bound from"),
            writes_model=True,
            # EMPTY, AND THAT IS MEANINGFUL: all of this op's checks are id
            # equalities and a counter. There is no number here because
            # there is nothing to measure; and introducing one "from
            # experience" would mean committing exactly the defect this
            # whole package is written against.
            tolerances={},
            grounded=(("type", "area_reinforcement_types", False),
                      ("bar_type", "rebar_bar_types", False),
                      ("hook_type", "rebar_hook_types", False)),
        ),
]
