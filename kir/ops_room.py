"""ops_room — a room boundary defined by something OTHER THAN A WALL.

Registry module — operations are added HERE, not in spec.py; the emitter
lives in the paired room_emit.py (exactly like ops_arch.py + arch_emit.py
for the ceilings wave and ops_struct.py + struct_emit.py for the framing
wave). spec.py gets one line in the module list, authoring.py gets one in
_EMITTERS. This way N waves add ops IN PARALLEL without colliding in one
file.

WHY A SEPARATE MODULE, NOT A LINE IN ops_arch.py. The header of ops_arch.py
declares that file the territory of the ceilings-and-railings wave; writing
into someone else's territory exactly while two other waves are running in
parallel is the very fight over a file for whose sake the registry was once
split apart. Besides, the room boundary is its own family: next to the room
separator stand the MEP space separator (NewSpaceBoundaryLines, 6/6) and the
area boundary (NewAreaBoundaryLine, 6/6), and they belong right here, not in
the ceilings.

═══ WHY THIS WAVE (a measurement, not a wish) ═══

The offline habitability verdict is written and works, but on a real
building it STAYS SILENT. The census k2_ar_rd_v9 (13A-RD-AR-K2, 59 floors),
taken by the instrument over L0.jsonl, reproduced independently:

    rooms                                          2,442
    bounded ONLY by walls                             936   ← and today's
                                                              language can
                                                              close only
                                                              these
    among the boundary elements there is a SEPARATOR 1,091
    walls + structural columns, no separators          126
    not a single boundary element (room not placed)    289

(1,091 + 126 = 1,217 — exactly the "also bounded by separators/columns"
already recorded in the header of design_check.py; here it is split into
two addends, because they are fixed by different waves.)

    OST_RoomSeparationLines in L0                  2,313
      of these bound EXACTLY TWO rooms                 749  ← ready-made
                                                              edges of the
                                                              adjacency
                                                              graph
      bound one                                       1,358
      bound three                                         34
      bound none                                          172

As long as the separator is not in the language, a program written by a
human closes a room with walls OR NOT AT ALL, and 2,313 elements go to
atoms with the reason `no_lifter` — "the operation does not exist," and that
was the truth.

═══ THE API NAME — THE TRAP INDEX AND COMPILATION, NEVER MEMORY ═══

Verified against data/api_traps/revit_api_traps.sqlite (35,516 members × 6
versions) and confirmed by a live compile on :52412 (2021-2026):

    Autodesk.Revit.Creation.Document.NewRoomBoundaryLines(
        SketchPlane, CurveArray, View) -> ModelCurveArray      6/6
        index traps: ArgumentException "sketch plane does not exist in
        the given document", ArgumentException "view does not exist in the
        given document" — both about DOCUMENT MEMBERSHIP, both closed by
        the fact that we take both the plane and the view from THIS doc;
    SketchPlane.Create(Document, ElementId)                    6/6
        index summary: "Creates a sketch plane from a grid, reference
        plane, or LEVEL" — meaning the plane is taken FROM THE LEVEL
        ITSELF, and there is no need to compute the elevation by hand at
        all;
    ViewPlan.GenLevel / IsTemplate / ViewType.FloorPlan        6/6
    Element.LevelId                                            6/6
    new ElementId(BuiltInCategory.…)                           6/6
    Category.BuiltInCategory                     ONLY 2023-2026 (4/6)
    ElementId.IntegerValue                        MISSING on 2026 (5/6)

The last two lines are not a footnote: they determine the SHAPE of the
witness. The created segment's category has to be checked via `Category.Id`
against `new ElementId(BuiltInCategory.OST_RoomSeparationLines)`; the
convenient `Category.BuiltInCategory` would drop 2021-2022, and the
familiar `Id.IntegerValue` would drop 2026 (measured: CS1061).

The operation has NO version axis: all six lines above live on all six
versions.

═══ THE OP'S SHAPE AND WHY EXACTLY THIS ═══

`path` — an OPEN POLYLINE of 2..64 points [x,y] mm, the same parameter kind
as create_railing.path, and NOT the floor's `outline`/`pts`. Three
arguments, each measured:

1. `pts` requires >=3 points AND NON-ZERO AREA (authoring_validation.py),
   i.e. it describes a RING by construction. A separator is almost never a
   ring: in K2 EVERY ONE of the 2,313 elements is a single segment, and the
   most common case ("plug a gap between two walls") is two points and
   zero area. Under `pts` it would be rejected as a degenerate contour.
2. A ring IS expressible as a polyline: a path whose last point coincides
   with the first gives a closed loop (5 points → 4 segments). The reverse
   is not true — an open polyline cannot be obtained from a ring. The more
   general kind wins.
3. The API asks for EXACTLY THIS: NewRoomBoundaryLines accepts a
   CurveArray, i.e. a batch of curves in one call, and returns a
   ModelCurveArray. A polyline of n points is n-1 curves in one call, with
   no translation at all.

The polyline does NOT imply a closing segment (the shared contour helper
`_loop_pts` closes via `(k+1)%n` and DOES NOT FIT here): a line that is not
in the source would cut off a piece of the room that nobody asked for.

`level` — REQUIRED and grounded against the `levels` pool. The separator's
elevation is set by the level and only by it: SketchPlane.Create(doc,
levelId) builds the level's own plane, and the curve points are placed at
MM(level.Elevation), read AT RUNTIME. The compiler does not know the
elevation of a level addressed by name or by reference; substituting its
own number would mean building the separator in the wrong place.

`type` — THERE IS NONE, AND THIS IS NOT FORGETFULNESS. NewRoomBoundaryLines
has no type-or-line-style argument at all; the style is assigned by the
document. Introducing a `type` parameter with a made-up pool would mean
promising something the API does not deliver. This also matches the
source: for all 2,313 K2 separators in L0, `type_id` and `type_name` are
EMPTY.

`offset_mm` — THERE IS NONE OF THAT EITHER, and this cost a measurement.
The separator's elevation in K2 coincides with its level's elevation for
2,309 of 2,313 elements; for the remaining four it is 30 mm lower. There is
no way to specify an offset in the API (the plane is the LEVEL's plane), so
the honest answer is not a parameter but a lifter REFUSAL on an offset
separator, exactly as with create_railing and its plane_z. The four
elements remain atoms with a named reason; a made-up parameter would have
silently returned them "approximately there."

═══ THE RESULT: MANY IDENTITIES, NOT ONE ═══

A polyline of n points creates n-1 ModelCurve elements, and each is an
independent element with its own ElementId. Hence `identity_cardinality =
MANY` and the field `segment_ids`, rather than the usual RESULT_ELEMENT.
Declaring ONE identity would mean: (a) lying about everything except a
straight segment; (b) hiding created elements that the receipt did not
name — and created-but-not-shown is indistinguishable from garbage in the
model, and A5 checks ownership precisely by the ids from the receipt (the
same lesson taught by the Railing.Create overload with a collection).
Later ops cannot reference the separator (`referenceable = False`): the
operation has no ONE identity a reference could point to.

═══════════════════════════════════════════════════════════════════════════
THE MODULE'S SECOND OPERATION (10.08.2026): create_space — AN MEP SPACE
═══════════════════════════════════════════════════════════════════════════

WHY HERE, AND NOT NEXT TO create_room. This module's header has, since
03.08, declared the MEP space family its own ("next to the room separator
stand the MEP space separator and the area boundary, and they belong right
here"), while `create_room` lives in ops_authoring.py — the busiest file in
the registry, written to by every wave at once. A space is kin to a
separator in substance: both are about the BOUNDARY of a volume, both are
SpatialElement, and neither has a type.

═══ WHY THIS WAVE (a corpus measurement, not a wish) ═══

Measurement from 10.08 across 76 saved decompiles
(`backend/data/decompile/*/L0.jsonl`, the `category_status` and
`document.census` records):

    decompiles where extraction looked at OST_MEPSpaces AT ALL   44 of 76
    decompiles with a non-zero space count                          6
    buildings with spaces                                           3
      Snowdon Towers Sample Electrical    (snowdon_elec_v1)        80
      Snowdon Towers Sample Plumbing      (snowdon_plumb_v1..4)    43
      Snowdon Towers Sample Architectural (snowdon_plumb_v5)       46
                                                                 ----
                                                                  169

    A CORRECTION FROM 11.08 TO THIS WAVE'S OWN MEASUREMENT, AND IT IS MORE
    INSTRUCTIVE THAN THE NUMBER. It used to say "126 spaces across two
    buildings," and both halves were wrong for one reason: THE FOLDER NAME
    WAS MISTAKEN FOR THE DOCUMENT NAME. The folder `snowdon_plumb_v5`
    carries `doc_name: "Snowdon Towers Sample Architectural"` in its L0
    header — this is a THIRD document, not a fifth plumbing revision, and
    it has no passport.json at all. The canon already warned about this
    from the other side ("the journal's key is the FILE NAME, save-as CUTS
    the history in two"); here the same mistake is mirrored — one folder
    prefix was mistaken for one building. Only `doc_name` in the L0 header
    names the document.

    extracted_count == expected_count, state=complete for ALL SIX — i.e.
    READING has already been able to handle a space, and has been able to
    the whole time.

    but the lifter has not: in `lift.py` the candidate table knows
    "OST_Rooms" and does NOT know "OST_MEPSpaces" (grep, 10.08). All 126
    elements go to atoms with the reason "the operation does not exist" —
    exactly the same class of hole for whose sake create_room_separator was
    introduced, and the same truth: the operation genuinely did not
    exist.

WHAT THIS WAVE DOES NOT DO, AND WHY. There is NO lifter here:
`decompile/**` is foreign territory for this session (the graph wave). A
forward path without a reverse one is not half the work but the correct
order: the reverse contract is declared as a `CAPTURE_GAP` rather than
invented, and the next wave will get an op it can write a lift for.

═══ THE API NAME — COMPILATION AND REFLECTION, NEVER DOCUMENTATION ═══

The arbiter is the ASSEMBLIES, not `RevitAPI.xml`: Autodesk's documentation
diverges from its own DLLs (`SpatialElementTag.SpatialElement` — in all six
XML files and in none of the assemblies). Measured on 10.08 by two
independent instruments: reflection against `RevitAPI.dll`
(`data/api_surface/api_signatures_*.json`) and a LIVE compile on the Roslyn
service :52412 — a SEPARATE run for each of the six versions, not one text
checked against six targets.

    doc.Create.NewSpace(Level, UV)        -> Space              6/6
    doc.Create.NewSpace(Level, Phase, UV) -> Space              6/6
    doc.Create.NewSpace(Phase)            -> Space              6/6
    THERE IS NO ARGUMENT-LESS OVERLOAD: CS1501 "No overload for method
        'NewSpace' takes 0 arguments" on all six

    THE RETURN TYPE IS PROVEN BY A COMPILER ERROR, NOT BY PROSE:
    substituting `int __x = doc.Create.NewSpace(lv, uv);` gives on all six
    CS0029 "Cannot implicitly convert type
    'Autodesk.Revit.DB.Mechanical.Space' to 'int'".

    Space.Location / .Area / .Volume / .Number / .Name /
        .LevelId / .Level / .Perimeter / .ClosedShell           6/6
    SpatialElement.GetBoundarySegments(SpatialElementBoundaryOptions),
        BoundarySegment.GetCurve()/.ElementId                   6/6
    BuiltInCategory.OST_MEPSpaces                               6/6
    BuiltInParameter.ROOM_NAME / ROOM_NUMBER / ROOM_AREA        6/6

    Space.Unplace()  —  MISSING ON ALL SIX: CS1061 "'Space' does not
        contain a definition for 'Unplace'", even though Room.Unplace()
        exists 6/6. This is the FIRST difference between Room and Space,
        and it matters more than the similarities: the API does not allow
        un-placing a space, meaning "created and then silently unplaced" is
        not a fallback path — there is none here.

THE OPERATION HAS NO VERSION AXIS, AND THIS IS A MEASUREMENT, NOT A HOPE:
all three overloads exist on all six versions with identical signatures. So
the emitter DOES NOT BRANCH by version. `Floor.Create` vs
`doc.Create.NewFloor` branches not out of caution, but because there the
measurement showed a DIFFERENCE; here the same kind of measurement showed
its absence, and a branch would be code unreachable on any target.

WHY THE "LEVEL + POINT" OVERLOAD WAS CHOSEN. `NewSpace(Phase)` creates a
space KNOWN IN ADVANCE TO BE UNPLACED — that is its declared purpose,
meaning its result is located nowhere. The overload with a phase and a
point requires CHOOSING A PHASE, and a phase cannot be read from the
program: it is a property of the document, and taking the first one found
would just be `.FirstOrDefault()` with better PR — exactly what the NAMED
DEFAULT (ground.py) was set up against. Level plus point chooses nothing on
the author's behalf.

═══ WHAT IS NOT IN v1: `name` AND `number` ═══

NOT TAKEN, and the argument is not "just in case" but a paid-for rollback
of a live build. Measured 04.08 on a live Revit 2026, recorded in the
create_room emitter:

    rm.Name = "KIR_GAP_ROOM_1";
    rm.Name                ->  "KIR_GAP_ROOM_1 1"   (name AND number)
    ROOM_NAME.AsString()   ->  "KIR_GAP_ROOM_1"

meaning a witness that checked the getter against the requested name would
roll back EVERY correctly built room (`KIR-X004: RM: name mismatch`).

WHETHER `Space` BEHAVES THE SAME WAY IS NOT SETTLED OFFLINE, but the
measurement narrows the question down to one line. Reflection across the
six assemblies (declared members of EACH class separately): `Name` and
`Number` are declared EXACTLY ONCE — on `Autodesk.Revit.DB.SpatialElement`
— and neither `Room` nor `Space` overrides them (Room's own properties are
only BaseOffset, ClosedShell, LimitOffset, UnboundedHeight, UpperLimit,
Volume; Space has 53 of its own properties, and none of them is Name or
Number). So the "name+number" concatenation, measured live on Room, is a
property of the very same member that Space uses. This is not proof of
behavior (Revit's implementation is native and is free to branch by
subclass internally), but the stakes are asymmetric: an error in this
direction kills a CORRECTLY built structure, while the absence of a
parameter kills nothing.

A SECOND ARGUMENT, from the reading side, and it is measured outright: for
all 126 spaces in the corpus, `params` is empty, and `type_id`/`type_name`
are empty strings. The source carries neither a name, nor a number, nor a
type. A parameter that reading never brings in would, in v1, serve only
composition, not reassembly.

═══ THE OP'S SHAPE ═══

`xy` + `level` — exactly what the chosen overload accepts, and not a field
more. There is NO `type`: `NewSpace` has no type argument at all, and for
all 126 spaces in the corpus `type_id` is empty — a made-up pool would
promise something the API does not deliver (the same argument as for the
separator above).

`referenceable`: THE RESULT IS REFERENCEABLE (RESULT_ELEMENT) — unlike the
separator, a space has EXACTLY ONE identity, and a subsequent op may
reference it (a space tag, set_param).

═══ TWO STATES THAT MUST NOT BE CONFUSED ═══

A space (like a room) has TWO different bad outcomes, and they are fixed
differently, which is why the compiler responds to them differently:

  * NOT PLACED (`Location == null`) — the element was created but IS
    LOCATED NOWHERE. The operation asked for a space AT A POINT; what was
    asked for did not happen. This is a TYPED REFUSAL with a named reason,
    and it costs exactly its own op under `per_op`. A green witness here
    would be a lie (there is nothing to check on an unplaced element:
    neither level, nor point, nor area), and a silent rollback is
    indistinguishable from breakage.
  * PLACED BUT NOT CLOSED (`Location != null`, `Area == 0`) — the operation
    did exactly what was asked: the space stands at the given point on the
    given level. What failed to hold is the PROMISE ("a closed volume"),
    and the MODEL is at fault, not the call. This is a POSTCONDITION
    VIOLATION — the same fork and the same response as with create_room.

`create_room` does NOT DISTINGUISH between these two states: an unplaced
room falls, for it, into the check `__loc == null || …` with the message
"room placement mismatch (geometry)," meaning "not placed" reads as
"missed the point." Here this is split, and split DELIBERATELY.
"""
from __future__ import annotations

from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: The category EVERY created segment must end up in. ONE line per
#: emitter, witness, and lift — so that the forward and reverse pass do
#: not diverge on the name of what they build and read.
ROOM_SEPARATOR_CATEGORY = "OST_RoomSeparationLines"

#: The same for an MEP space: one line for the emitter, the witness, the
#: result-category registry, and acceptance.
MEP_SPACE_CATEGORY = "OST_MEPSpaces"

#: CATEGORIES OF SPATIAL ELEMENTS whose creation resolves the enclosing
#: region AT CALL TIME (`NewRoom`/`NewSpace`), and therefore requires that
#: everything created earlier has already been regenerated. The list is
#: CATEGORIES, not ops: an op that tomorrow starts building a room via a
#: different call will fall under the rule by its result category, not by
#: its name.
SPATIAL_ENCLOSURE_CATEGORIES = ("OST_Rooms", "OST_MEPSpaces")

OPS = [
    OpSpec(
        name="create_room_separator",
        effect=EffectKind.CREATE,
        # MANY identities — see "RESULT" in the module header. The spec is
        # declared here, not in registry_base.py: introducing a shared
        # RESULT_* for a single consumer would mean touching the shared file
        # without need.
        result=ResultSpec(IdentityCardinality.MANY, "segment_ids"),
        family="authoring",
        params=(
            # An open polyline of 2..64 points. A separate kind from `pts` —
            # see "OP SHAPE" in the module header.
            ParamSpec("path", "path", required=True),
            ParamSpec("level", "sel", required=True,
                      ref_kinds=(ReferenceKind.LEVEL,)),
        ),
        capability=(("create", "room_separator"),),
        # THE SEMICOLON SEPARATES COMMITMENTS: translation_cert.py splits
        # post exactly on it and requires a witness for EVERY piece. What is
        # promised is exactly what is checked, and not a word more.
        post=("room separator segments exist (materialized or typed refusal) (materialize); "
              "созданных сегментов ровно на один меньше, чем точек path "
              "(identity); "
              "каждый созданный сегмент лежит в категории "
              "OST_RoomSeparationLines, а не в обычных модельных линиях "
              "(topology); "
              "level binding == resolved level у каждого сегмента (topology); "
              "концы каждого сегмента == соседняя пара точек path (±5mm) "
              "(geometry)"),
        writes_model=True,
        grounded=(("level", "levels", True),),
        # The same endpoint tolerance as for a wall, pipe, grid, and beam:
        # it is one and the same promise about one and the same quantity,
        # and a different number here would mean two judges disagreeing on
        # what "the same endpoint" means.
        tolerances={"endpoint_mm": 5.0},
    ),
    OpSpec(
        name="create_space",
        effect=EffectKind.CREATE,
        # ONE identity, and it is REFERENCEABLE — unlike the separator
        # above. `NewSpace` returns exactly one `Space` (the type is proved
        # by CS0029 on all six versions), so the next op is entitled to
        # reference it.
        result=RESULT_ELEMENT,
        family="authoring",
        params=(
            # Exactly what the chosen overload accepts, and not a field
            # more. `name`/`number`/`type` — see the module header: the
            # first two cost create_room a rollback of the CORRECT room, the
            # API has no such thing as the third.
            ParamSpec("xy", "pt_xy", required=True),
            ParamSpec("level", "sel", required=True,
                      ref_kinds=(ReferenceKind.LEVEL,)),
        ),
        # The same capability dictionary as create_room: for the model this
        # is one and the same question of "what describes a room/space".
        capability=(("create", "room_space"),),
        # THE SEMICOLON SEPARATES COMMITMENTS: translation_cert.py cuts
        # `post` exactly on it and requires a witness for EVERY piece. What
        # is promised is exactly what is checked.
        #
        # THERE IS NO CATEGORY IN THIS LIST, AND THAT IS A DECISION, NOT AN
        # OMISSION. For the separator, the category witness is the heart of
        # the operation: there, `NewRoomBoundaryLines` returns a ModelCurve,
        # and whether "this is a separator or an ordinary model line" is an
        # open question. Here the return type IS `Space` (CS0029, 6/6), and
        # the correspondence of the Space class to the OST_MEPSpaces
        # category is an invariant of Revit itself. A check that cannot fail
        # to agree is `plate_z_doubling` in different clothes: it always
        # passes and proves nothing, while inflating the appearance of
        # proof. The category is nonetheless NOT WITHOUT OVERSIGHT: it is
        # verified by ACCEPTANCE against the census
        # (`spec.OP_RESULT_CATEGORIES["create_space"]`), i.e. an independent
        # judge on an independent read — that is where it belongs.
        post=("space exists and is placed (materialized or typed refusal); "
              "LevelId == resolved level (topology); "
              "LocationPoint == xy (±5mm) (geometry); "
              "Area > 0 — пространство замкнуто, а не создано впустую "
              "(geometry); "
              "GetBoundarySegments даёт хотя бы одну непустую петлю границы "
              "(topology)"),
        writes_model=True,
        grounded=(("level", "levels", True),),
        # The same tolerance as create_room: it is one and the same promise
        # about one and the same quantity (the placement point of the
        # spatial element), and a different number here would mean two
        # judges.
        tolerances={"location_mm": 5.0},
    ),
]
