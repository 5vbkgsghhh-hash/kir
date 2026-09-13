"""ops_sweep — applied profiles: sweep/reveal on a wall and a drip edge
along a slab's edge (wave/sweep, 2026-08-09).

Registry module — Add ops HERE, not in spec.py. The paired emission file
is `sweep_emit.py`, exactly as `ops_site.py` ↔ `site_emit.py`.

BEFORE THIS WAVE THE FAMILY OF APPLIED PROFILES HAD NEVER BEEN EXAMINED:
the registry census found not a single operation creating a `WallSweep`,
`SlabEdge`, `Fascia`, or `Gutter`. This is a whole class of facade and
roof trim — cornices, string courses, reveal-rustication, drip edges
along slab edges — that was expressed by NOTHING.

API MEASUREMENT (live compile service :52412, six reference assemblies
2021-2026, 09.08.2026). Not a single line below is written from memory,
and none is taken from `backend/data/revit_api_db.json` (this database is
demonstrably incomplete — 30 of 93 members of `ElementTypeGroup`, and it
does not know `NewSlabEdge` at all). Each is checked by assignment to a
DECLARED type: `var __x = ...` compiles for ANY type on the right and
proves nothing — the lesson of the railings wave.

    WallSweep.Create(Wall, ElementId, WallSweepInfo)          6/6  (since 2012)
    WallSweep.WallAllowsWallSweep(Wall)                       6/6
    WallSweep.GetHostIds() -> ICollection<ElementId>          6/6
    WallSweep.GetWallSweepInfo() -> WallSweepInfo             6/6
    WallSweep.GetTypeId() / .Id / (Element)                   6/6
    WallSweepInfo..ctor(WallSweepType, bool vertical)         6/6
    WallSweepInfo.IsVertical (READ)                           6/6
    WallSweepInfo.IsVertical (WRITE)          NOT ON ANY (CS0200)
    WallSweepInfo.Id — this is an `int`, NOT an ElementId      6/6 (CS0029)
    WallSweepInfo.DistanceMeasuredFrom : DistanceMeasuredFrom 6/6
    WallSweep -> HostedSweep (cast)            NOT ON ANY (CS0030)
    ElementTypeGroup.RevealType / .EdgeSlabType               6/6
    BuiltInCategory.OST_Cornices / OST_Reveals                6/6
    doc.Create.NewSlabEdge(SlabEdgeType, Reference)           6/6
    doc.Create.NewSlabEdge(SlabEdgeType, ReferenceArray)      6/6
    doc.Create.NewFascia / NewGutter (both overloads)         6/6
    SlabEdge.SlabEdgeType -> SlabEdgeType                     6/6
    SlabEdge.GetTypeId()                                      6/6
    SlabEdge -> HostedSweep: Length/Angle/HorizontalOffset/
                VerticalOffset/get_ReferenceCurve(Reference)  6/6
    HostObjectUtils.GetTopFaces / GetBottomFaces              6/6
    Face.EdgeLoops -> EdgeArrayArray; Edge.Reference          6/6
    Category.GetCategory(Document, BuiltInCategory)           6/6

FIVE FACTS THAT WOULD HAVE OVERTURNED THESE OPS HAD THEY NOT BEEN
MEASURED:

1. A NAMED, WEAKER GUARANTEE FOR THE WALL PROFILE. `RevitAPI.xml` of all
   SIX versions carries, at `WallSweep.Create`, the verbatim remark:

       "The wall sweep's profile and type are taken from the wall sweep type
       properties.  The values set in the WallSweepInfo are ignored."

   This is not a footnote but the main fact of the operation: the
   profile's position is set by the TYPE, pre-loaded into the document,
   not by the call. This means the operation HAS NO, AND CANNOT HAVE, an
   "at what height" parameter: introducing a `distance_mm` that the API
   documentedly ignores would mean building exactly the silently-wrong
   outcome this whole house is written to forbid (the author asks for a
   string course at 900, gets one at the type's elevation, and from the
   outside this is indistinguishable from success). So the honest witness
   is EXISTENCE, HOST, and TYPE, and this is written into `post`
   verbatim, not as a paraphrase.
2. `WallSweepInfo.IsVertical` is a READ-ONLY PROPERTY (CS0200 on all
   six). The only orientation channel is the CONSTRUCTOR argument, and it
   is mandatory. That is why the operation has an `orientation`, WITHOUT
   A DEFAULT, and it is the ONLY field of `WallSweepInfo` that the
   operation exposes at all: substituting it on the author's behalf would
   mean introducing "a default that nobody stated" — the same class of
   defect as `height_mm=3000` for a wall. A witness is put on it
   (`GetWallSweepInfo().IsVertical`), and this is DELIBERATELY SAFER than
   staying silent: if live Revit extends the remark above to the
   constructor as well, the program will get a typed failure — not a
   silently built horizontal string course instead of a reveal.
3. `WallSweepInfo.Id` is an `int`, not an `ElementId` (CS0029 on all
   six), and the documentation requires `-1` for a non-fixed profile
   («The WallSweepInfo id must be set to -1 for a non-fixed wall sweep» —
   an ArgumentException condition). The emitter sets it explicitly;
   relying on the constructor's default would mean handing an entire
   class of ArgumentException over to runtime.
4. `WallSweep` is NOT a `HostedSweep` (CS0030 on all six), whereas
   `SlabEdge`, `Fascia`, and `Gutter` ARE. That is,
   `Length`/`Angle`/`HorizontalOffset` DO NOT EXIST for the wall profile,
   but do for the edge profile. Two elements that look like kin in
   Revit's interface stand in different hierarchies in the API, and their
   witnesses are therefore of DIFFERENT STRENGTH — see each one's `post`.
5. THE EDGE PROFILE HAS A READ-BACK, AND THIS IS THE MAIN MEASUREMENT OF
   THIS WAVE. The wave's task carried the question "does `SlabEdge` have
   even one getter beyond the base `Element` and `AddSegment(Reference)`;
   a previous inspection found none". THE ANSWER: FOUR KINDS WERE FOUND,
   all 6/6 — the own property `SlabEdge.SlabEdgeType`, the base
   `GetTypeId()`, and, through the base class `HostedSweep` —
   `Length`/`Angle`/`HorizontalOffset`/`VerticalOffset` and the indexable
   `get_ReferenceCurve(Reference)`. The last one is the real witness: the
   BUILT profile is asked for the curve it laid along EACH reference we
   named, and `null` means Revit did not take that reference. The earlier
   conclusion "there is nothing to read" would have been a refusal of an
   operation that does have a witness.

WHY THE EDGE PROFILE HAS NO "WHICH EDGE" PARAMETER — AND THIS IS NOT A
SIMPLIFICATION. `NewSlabEdge` accepts a geometric REFERENCE to an edge,
and KIR's frozen reference dialect addresses ELEMENTS; the second-tier
selector that appeared on 09.08 (`faceref.py`, `{"by": "face", ...}`)
names a FACE, not an EDGE. Introducing a third kind of second tier here
would mean writing a second mechanism alongside the existing one — flatly
forbidden by the wave's task.

So the operation takes not "an edge" but the WHOLE PERIMETER OF THE NAMED
FACE, and both tiers are resolved by CARDINALITY, not by iteration order
— the same law as in `faceref.py` ("the description filters, cardinality
decides"):

    the side (`side`) -> HostObjectUtils.GetTopFaces/GetBottomFaces
        exactly 1 face   -> take it
        0 faces          -> a typed refusal
        >= 2 faces       -> a typed refusal, WITH THE COUNT
    that face's contours -> Face.EdgeLoops
        exactly 1 contour -> take ALL of its edges
        otherwise         -> a typed refusal, WITH THE COUNT of contours
                             (a slab with a hole honestly refuses: which
                             of the rings to trace around is the author's
                             decision, not ours)

There is no "first matching one" at any point, so the undocumented order
of faces and edges has NO EFFECT AT ALL on the result. That is the whole
trick.

WHAT IS DELIBERATELY NOT HERE:

* `NewFascia` and `NewGutter` (both 6/6, same signature, the same
  `HostedSweep` result) are NOT WIRED IN. There is exactly one reason and
  it is not laziness: each takes ITS OWN type class
  (`Architecture.FasciaType`, `Architecture.GutterType`), and `grounded`
  in the registry is a static triple (parameter, pool, requiredness),
  i.e. one `type` parameter cannot be grounded into three different
  pools depending on the value of a neighboring field. There are two
  honest ways out — three separate pools with three operations, or one
  merged pool with a runtime category check — and both are separate work
  with separate reference cases, not "one more enum value". And slipping
  a `FasciaType` into `NewSlabEdge` is not possible: the signature
  demands exactly `SlabEdgeType` (the same reason the strip foundation
  has its own `wall_foundation_types` rather than reusing
  `foundation_symbols`);
* the overload `NewSlabEdge(type, Reference)` — a single edge — is not
  wired in: this operation's only input is a perimeter, and there is no
  way to name a single edge without a second-tier selector (see above);
* `HostedSweep.HorizontalOffset` / `VerticalOffset` / `Angle` are NOT
  exposed as parameters, even though they read 6/6. These are SETTERS on
  an already-created element, i.e. work for `set_param`, not a second way
  to create the same element.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/DEFAULTS/...)

#: The orientation of a wall profile. A closed enumeration WITHOUT a
#: default: there is exactly one channel (the `WallSweepInfo` constructor
#: argument, writing to the property is impossible — CS0200 on all six),
#: and substituting it on the author's behalf would mean building a
#: string course where a reveal was requested, and staying silent about
#: it.
SWEEP_ORIENTATIONS = ("horizontal", "vertical")

#: The side of the host along whose perimeter the edge profile is
#: placed. The names are NOT ours: Revit itself gives them, in
#: `HostObjectUtils` — so they have no tolerance and cannot have one. A
#: subset of `faceref.SIDES` (which also has exterior/interior, which a
#: horizontal host never has).
SLAB_EDGE_SIDES = ("top", "bottom")

#: The value of `WallSweepInfo.Id` that the documentation requires for a
#: NON-fixed profile: «The WallSweepInfo id must be set to -1 for a
#: non-fixed wall sweep» (an ArgumentException condition, in all six
#: XMLs). It lives here, not as a literal in the emitter, for the same
#: reason as `TOPOSOLID_MIN_VERSION` in the site wave: this number is
#: read by both the test and the emitter.
WALL_SWEEP_NON_FIXED_ID = -1

OPS = [
    OpSpec(
        name="create_wall_sweep",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # THE HOST IS AN EXISTING WALL, and `target_w` is here for the
            # same reason as for an opening: a cornice is hung on what is
            # ALREADY STANDING ("run a string course along this wall"),
            # and a wall built by this same program is a special case.
            # `ref_kinds` are deliberately broad: the real class is
            # checked at runtime (`as Wall`) with a typed refusal, not by
            # a guess at parse time.
            ParamSpec("host", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT, ReferenceKind.WALL)),
            # ORIENTATION WITHOUT A DEFAULT — see fact 2 in the module
            # header.
            ParamSpec("orientation", "enum", required=True,
                      choices=SWEEP_ORIENTATIONS),
            # The profile type. There is ONE pool for cornices and
            # reveals (OST_Cornices + OST_Reveals), because a
            # `WallSweepType`-as-ElementType class does not exist in the
            # API at all: `WallSweepType` is an ENUM {Sweep, Reveal}, and
            # the type itself lives as an ordinary `ElementType` in one of
            # the two categories (measured). Which of the two enum values
            # to pass is DERIVED by the emitter from the resolved type's
            # category, rather than asked of the author: asking would
            # mean introducing a field that could CONTRADICT the type,
            # and by the remark from fact 1 the type would win — i.e. the
            # answer given to the author would silently be a different
            # one.
            ParamSpec("type", "sel"),
        ),
        # THE BODY EXISTS, BUT THE OPERATION HAS NO COORDINATES: the cell
        # ("create", "geometry") here would be over-promising by exactly
        # the quantity the named, weaker guarantee describes. The same
        # position as create_railing (only ("create", "element")).
        capability=(("create", "element"),),
        post=("wall sweep exists on 2021-2026 (WallSweep.Create, since 2012); "
              "a wall that may not host a sweep is a typed refusal from "
              "WallAllowsWallSweep BEFORE the call, never a raw "
              "ArgumentException; "
              "GetHostIds() re-read contains the requested wall (topology); "
              "GetTypeId() re-read == resolved wall sweep type (topology); "
              "GetWallSweepInfo().IsVertical == requested orientation "
              "(semantic); "
              "NAMED WEAKER GUARANTEE, documented by Autodesk in all six "
              "RevitAPI.xml: \"The wall sweep's profile and type are taken "
              "from the wall sweep type properties. The values set in the "
              "WallSweepInfo are ignored.\" — the placement distance, the "
              "wall offset and the profile therefore come ENTIRELY from the "
              "pre-loaded type, this op exposes no field for any of them, "
              "and none of them is witnessed or witnessable here"),
        writes_model=True,
        grounded=(("type", "wall_sweep_types", False),),
        # NOT A SINGLE TOLERANCE, AND THIS IS A CONSEQUENCE, NOT A GAP.
        # All three witnesses are exact: id membership in a set, id
        # equality, boolean-value equality. There is no number in this
        # operation that could be compared against a tolerance at all —
        # precisely because the profile's position is set by the type
        # (fact 1). Introducing a tolerance here could not be done
        # honestly: there is nothing to measure.
        tolerances={},
    ),
    OpSpec(
        name="create_slab_edge",
        effect=EffectKind.CREATE,
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # THE HOST IS AN EXISTING FLOOR OR ROOF. `ref_kinds` is
            # ELEMENT only: both `Floor` and `RoofBase` are `HostObject`
            # (measured 6/6), but they have no dedicated ReferenceKind,
            # and narrowing to WALL would be flatly wrong.
            ParamSpec("host", "target_w", required=True,
                      ref_kinds=(ReferenceKind.ELEMENT,)),
            # THE SIDE HAS NO DEFAULT. A drip edge along the top and
            # along the bottom are different elements in different
            # places, and "usually the top" is a guess about someone
            # else's project.
            ParamSpec("side", "enum", required=True, choices=SLAB_EDGE_SIDES),
            ParamSpec("type", "sel"),
        ),
        # HERE THE GEOMETRY CELL IS EARNED, unlike for the wall profile:
        # the edge profile's position is set BY US (with a set of edges),
        # and it is read back from the built element
        # (`get_ReferenceCurve`).
        capability=(("create", "element"), ("create", "geometry")),
        post=("slab edge exists on 2021-2026 "
              "(Autodesk.Revit.Creation.Document.NewSlabEdge, which returns "
              "null rather than throwing on failure — the null is a typed "
              "refusal here); "
              "the named side resolves to exactly ONE face and that face to "
              "exactly ONE edge loop, and any other cardinality is a typed "
              "refusal NAMING THE COUNT — never a first match, so the "
              "undocumented order of faces and edges cannot affect the "
              "result; "
              "every perimeter edge handed to the call is bound in the BUILT "
              "sweep: get_ReferenceCurve(edge) is non-null for each of them "
              "(geometry); "
              "GetTypeId() re-read == resolved slab edge type (topology)"),
        writes_model=True,
        grounded=(("type", "slab_edge_types", False),),
        # THERE ARE NO TOLERANCES, AND AGAIN FOR GOOD REASON. The edge
        # witness is BOOLEAN (the reference is bound or not), not
        # metric. `HostedSweep.Length` reads 6/6, and it would be
        # tempting to check it against the sum of the edge lengths — but
        # at the joints Revit miters the profile, and by HOW MUCH exactly
        # nobody has measured. Checking them against an invented
        # tolerance would mean accusing a correctly built drip edge; so
        # the length travels into the RECEIPT as an observation, not into
        # the verdict — the same technique as `slab_shape_vertices: -1`
        # for the terrain solid.
        tolerances={},
    ),
]
