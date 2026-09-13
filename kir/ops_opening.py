"""ops_opening — AN OPENING AS A SEPARATE ELEMENT (`Autodesk.Revit.DB.Opening`).

Registry module — see REGISTRY_MODULES.md. Operations are added HERE, not
in spec.py. The emitter lives in `opening_emit.py` (a companion file,
exactly like `struct_emit.py` is to `ops_struct.py` and `arch_emit.py` is
to `ops_arch.py`); `authoring.py` gets only the import and one line in
`_EMITTERS`.

═══ THE REASON: THE ONE SILENT LOSS IN THE WHOLE PIPELINE ═══════════════════

A sweep of eight real buildings (2026-08-03) found EXACTLY ONE loss that
produces no refusal, no atom, no line in the cause map. An opening in Revit
is made by TWO different mechanisms:

  * an inner loop of the HOST'S OWN sketch — we have known how to do this
    for a long time (60 `create_floor` calls with a non-empty `holes` across
    three buildings);
  * a SEPARATE `Opening` element — this did not exist IN ANY FORM. A grep
    across all of the package's `.py` and `.cs`: zero mentions of
    `OST_ShaftOpening`, `OST_SWallRectOpening`, `OST_FloorOpening`,
    `OST_RoofOpening`, `Opening`, `NewOpening`. No reading, no operation, no
    refusal.

Census: 35 elements across 3 of 6 buildings — `OST_FloorOpening` 10,
`OST_ShaftOpening` 9, `OST_SWallRectOpening` 9, `OST_RoofOpening` 7.

WHY THIS IS THE WORST CLASS OF DEFECT. The element is not extracted ⇒ it
yields no atom ⇒ it appears in no ranking at all. But the HOST, meanwhile,
is lifted by an ordinary `create_floor`/`create_wall` and rebuilt SOLID. L2
acceptance does not catch this by construction: `acceptance.py` states
outright that it DOES NOT LOOK AT GEOMETRY AT ALL. From the outside, a
silently wrong result is indistinguishable from success.

═══ API MEASUREMENT (trap index + the six packages' reference XML) ═════════

    Creation.Document.NewOpening(Element, CurveArray, eRefFace)      6/6
    Creation.Document.NewOpening(Element, CurveArray, bool)          6/6
    Creation.Document.NewOpening(Level, Level, CurveArray)           6/6
    Creation.Document.NewOpening(Wall, XYZ, XYZ)                     6/6
    Creation.FamilyItemFactory.NewOpening(Element, CurveArray)       6/6  (family document, not project)
    Opening.Host                                                     6/6
    Opening.IsRectBoundary / .BoundaryRect / .BoundaryCurves         6/6
    Opening.SketchId                                           2022-2026 (5/6)

The operation has NO version seam: everything it uses lives across
2021-2026. `Opening.SketchId` is the only member with a seam (absent on
2021), and we do not use it in either direction; this is written down here
so the next person does not start building a read on it without seeing the
seam.

Verbatim spec remarks that change behavior:
  * «Slanted stacked walls do not support rectangular openings» — Revit's
    refusal on a slanted/stacked wall is LEGITIMATE, and it must arrive
    LOUDLY (NewOpening will return null or throw an ArgumentException ⇒ a
    typed refusal, not a silent no-op);
  * `bPerpendicularFace`: «True if the profile is cut perpendicular to the
    intersecting face of the host. False if the profile is cut vertically»
    — the meaning is DOCUMENTED, so the parameter is expressed (see `cut`
    below), unlike a ceiling's slope, whose second argument the
    documentation does not explain and which is therefore not introduced
    in `create_ceiling` at all.

The call shape was checked not only against the documentation but against
GOLDEN CODE:
  * Autodesk SDK `NewOpenings/CS/ProfileWall.cs:65` —
    `m_docCreator.NewOpening(m_data, p1, p2)` (a wall, two points);
  * Autodesk SDK `NewOpenings/CS/ProfileFloor.cs:101` —
    `m_docCreator.NewOpening(m_data, curves, true)`, where `curves` is
    assembled as a closed polyline with an EXPLICIT closing segment;
  * BHoM `Revit_Core_Engine/Convert/Physical/ToRevit/Floor.cs:114,127` —
    the same call in production, and there the profile IS PROJECTED ONTO
    THE SLAB'S PLANE (`hole.IProject(slabPlane)`). Consequence for our
    emission: the profile's elevation cannot be taken as zero — it must be
    given by the HOST ITSELF — it is read live as the midpoint of its
    bounding box along Z (`opening_emit._emit_host_face`).

═══ SHAPE: TWO KINDS OUT OF FOUR, AND THIS IS A DECISION ════════════════════

The four overloads are four DIFFERENT kinds of opening, not four entries
for one. They are split by the `variety` field — the same trick and the
same name as `create_foundation` uses (the registry reserves the word
"kind" for the dictionary of Revit object kinds, SPEC 12.8; NAMING NOTE in
`ops_struct.py`).

TWO ARE TAKEN, EACH WITH A FULL WITNESS (existence + belonging to the
requested host + bounding box, and all three are read FROM THE BUILT
ELEMENT):

  variety="wall_rect"  — a rectangular opening in a wall,
      `NewOpening(Wall, XYZ, XYZ)`. Witness: `Opening.Host.Id` == the
      requested wall (topology), `Opening.IsRectBoundary` == true, and the
      corners of `Opening.BoundaryRect` hold the requested band along Z and
      the requested width (geometry; why NOT absolute X/Y is explained in
      `opening_emit.py`'s header). Census: `OST_SWallRectOpening` 9.

  variety="host_face" — a profile-based opening in a floor/roof/ceiling,
      `NewOpening(Element, CurveArray, bool)`. Witness: `Opening.Host.Id`
      == the requested host (topology) + the opening's bounding box against
      `outline` (geometry). Census: `OST_FloorOpening` 10 +
      `OST_RoofOpening` 7 = 17.

TWO ARE NOT TAKEN, AND THE REASON FOR EACH IS NAMED (`VARIETIES_NOT_TAKEN`
below — one table for the header, the emitter's refusal, and the reading
refusal, so the three texts do not drift apart). In brief:

  "shaft"   — `NewOpening(Level, Level, CurveArray)`. Easy to build, but
      NOTHING TO CHECK IT WITH: a shaft has no host element (`Opening.Host`
      is not the host for it), and the `BuiltInParameter` for a shaft's
      base and top constraint is not documented IN ANY of the six packages
      (verified by searching ALL documented `BuiltInParameter` members of
      each version — 3338/3383/3493/3583/3665/3739 members across
      2021...2026 — ZERO matches for the word "shaft"). The only thing that
      could confirm the pair of levels would be the Z-extent matching the
      levels' elevations, and that is a GUESS about something the API does
      not promise — exactly the defect that made `create_beam` roll back
      CORRECTLY built beams by requiring a promise Revit never gave. §18.1
      forbids building without a witness. Census: `OST_ShaftOpening` 9.

  "framing" — `NewOpening(Element, CurveArray, eRefFace)`, an opening in a
      beam, brace, or column. `eRefFace` is CenterX/CenterY/CenterZ,
      meaning the profile must lie ON THE ELEMENT'S CENTER FACE, and its
      basis (origin and two axes) cannot be derived from a flat `outline`:
      it would require reading the host's geometry and deciding which of
      the three faces was meant. A bounding box without a basis is not
      checkable. Plus a measurement: the eight-building census found ZERO
      elements of this kind.

The selection rule is taken verbatim: better two kinds with a full witness
than four with promises.

═══ THE SECOND SHAPE INPUT: A CONTOUR SKETCH (2026-08-09) ═══════════════════

`variety="host_face"` gained a SECOND profile input — an optional `contour`
of the `region` kind, i.e. the whole sketch language from `contour.py`
(rect/l/poly with small arcs, points as literals or grid intersections).
Four things, each checked, not assumed:

1. `outline` STAYED and did not change by one byte. The reverse pass for an
   opening is still a `CAPTURE_GAP` (`reverse_contract`), but the house has
   one rule: explicit points are what materialize speaks, and they cannot
   be taken away from the other side EVEN while it stays silent. A
   replacement would break the loop on exactly the day L0 learns to carry
   an opening's boundary.
2. AN ARC IS NOT DECORATION. A round opening for a riser or a rounded
   cutout in a slab is inexpressible with a polyline: it produces a
   DIFFERENT shape, not an approximation. This exact class stood in the
   refusal map a wave earlier — "polygon ops cannot represent an arc
   profile," 27 elements.
3. THE SKETCH HAS NO VERSION SEAM, AND THIS WAS RE-CHECKED ON 08-09
   AGAINST THE REFERENCE ASSEMBLIES, NOT FROM MEMORY: `NewOpening(Element,
   CurveArray, bool)` 6/6, `Arc.Create(XYZ, XYZ, XYZ)` 6/6,
   `Line.CreateBound` 6/6, `CurveArray.Append` 6/6, `Curve.Evaluate(double,
   bool)` 6/6, `Curve.GetEndPoint(int)` 6/6, `Curve.IsBound` 6/6. Not one
   member of the contour branch has a seam — UNLIKE a ceiling, which on
   2021 has no creation path at all. So NO version-based typed refusal is
   introduced here: a refusal the API does not require is just as much a
   lie as silence where a refusal is needed.
4. HOLES IN AN OPENING ARE INEXPRESSIBLE, AND THIS IS A REFUSAL, NOT AN
   OMISSION — see `CONTOUR_HOLES_NOT_EXPRESSIBLE` below.

WHAT THE CUT WITNESS CAN AND CANNOT DO (the full account is in
`opening_emit.py`'s header; here is the upshot, because `post` must promise
exactly this): an opening hands back its PLAN BOUNDARY
(`Opening.BoundaryCurves`) and its host (`Opening.Host`) — and nothing
else. The opening's bounding box is checked as a BAND, not an equality:
from below it must be covered by the VERTICES (their `GetEndPoint` is
exact), from above it must not exceed the exact bounding box of the sketch
with its arcs included (`edges_bbox`). Between these two bounds lies the
arc's sagitta, and there the witness DOES NOT DISCRIMINATE: sampling via
`Curve.Evaluate` is finite, and its API does not promise a density —
assigning a number there would mean inventing a tolerance. The cut's depth
and the very fact that "material was removed" are not readable AT ALL: an
`Opening` is a void — it has no body and no documented bounding box; this
is checkable only with a live Revit.

═══ WHY THE OPERATION HAS NO TYPE, NO LEVEL, AND NO POOL ════════════════════

None of the four overloads accepts either an `ElementType` or a `Level`
(except for the shaft, where the levels ARE the signature). `Opening` has
no type at all. Hence `grounded=()`: setting up a snapshot pool for an
operation that does not use one would mean promising a resolution that
never happens. This is the registry's second write op with no grounding
(the first is `create_directshape`).

An opening's level is derived by Revit from the host; we neither set it
nor promise it.
"""
from __future__ import annotations

from kir.record_ratchet import STANDS, Entry, Ledger
from kir.registry_base import *  # noqa: F401,F403 (OpSpec/ParamSpec/...)

#: The opening kinds this wave does NOT TAKE, and why — ONE table for all
#: three places where the reason must be spoken: the module header, the
#: emitter's typed refusal (`diag.EMIT_UNSUPPORTED_ENUM`), and the read
#: side's refusal. Three separately typed-up texts drift apart — this
#: codebase already paid for that with the ceiling/railing category pairing
#: on 07-29.
#:
#: BOTH LINES WERE RE-CHECKED ON 08-09 BY INSTRUMENT, NOT BY READING
#: (`record_ratchet`). "shaft": the claim "the BuiltInParameter for a
#: shaft's base and top constraint is not documented in any of the six
#: packages" was recomputed across all six RevitAPI.xml files — 3339 /
#: 3384 / 3494 / 3584 / 3666 / 3740 BuiltInParameter members across
#: 2021…2026, ZERO matches for the word "shaft" in all six. (The numbers
#: recorded in the module header, 3338/3383/…, are exactly one lower in
#: each version — the counting method differs, not the fact; it does not
#: affect the conclusion, but let the discrepancy stand written down rather
#: than silently fixed.)
#: "framing": the center face's basis cannot be derived from a flat
#: `outline` — this is a property of the `NewOpening(Element, CurveArray,
#: eRefFace)` signature, not a temporary state of the tree.
#:
#: Both verdicts are `stands-because`, and BY CONSTRUCTION they have no
#: deadline: only Autodesk (by documenting the parameter) or a new selector
#: stage can close them — that is not work that has a deadline. They are
#: kept alive by re-confirming `decided_on`, and that is exactly what was
#: done today.
_VARIETIES_NOT_TAKEN_ENTRIES: dict[str, Entry] = {
    # 🔴 BOTH WERE CONFIRMED ON 2026-09-03 BY RE-MEASUREMENT, NOT BY MOVING
    # THE DATE. The ratchet `test_record_ratchet` demanded that a decision
    # older than 30 days be "confirmed or reconsidered," and its own
    # docstring names the wrong move: "move the date without making a
    # decision — that is how a ledger turns into a graveyard." So each one
    # was re-measured by its OWN instrument across all six API packages,
    # and the result is recorded AS A NUMBER next to the decision.
    "shaft": Entry(STANDS, "2026-09-03", "", (
        "шахта между уровнями (NewOpening(Level, Level, CurveArray), 6/6) "
        "строится, но НЕ ПРОВЕРЯЕТСЯ: элемента-хозяина у неё нет, а "
        "BuiltInParameter базового и верхнего ограничения шахты не "
        "документирован ни в одном из шести пакетов API — подтверждать пару "
        "уровней совпадением Z-габарита значило бы требовать от Revit "
        "обещания, которого он не давал (дефект create_beam), и откатывать "
        "правильно построенные шахты. ПЕРЕМЕР 03.09.2026: "
        "grep -io 'BuiltInParameter\\.[A-Za-z0-9_]*shaft[A-Za-z0-9_]*' по "
        "RevitAPI.xml всех шести версий 2021…2026 — совпадений НОЛЬ на "
        "каждой. Решение стоит")),
    "framing": Entry(STANDS, "2026-09-03", "", (
        "проём в балке/связи/колонне (NewOpening(Element, CurveArray, "
        "eRefFace), 6/6) требует профиль НА СРЕДИННОЙ ГРАНИ хоста: базис этой "
        "грани из плоского outline не выводится, а без базиса габарит "
        "непроверяем; в переписи восьми зданий этого рода ноль элементов. "
        "ПЕРЕМЕР 03.09.2026: члены eRefFace в RevitAPI.xml — ровно три и те "
        "же на 2021 и на 2026 (CenterX, CenterY, CenterZ), то есть грань "
        "по-прежнему только СРЕДИННАЯ, и базис по-прежнему не выводится. "
        "Решение стоит")),
}

VARIETIES_NOT_TAKEN = Ledger(
    "ops_opening.VARIETIES_NOT_TAKEN", _VARIETIES_NOT_TAKEN_ENTRIES,
    instrument=(
        "перепись членов BuiltInParameter по всем шести RevitAPI.xml: "
        "grep -io 'BuiltInParameter\\.[A-Za-z0-9_]*shaft[A-Za-z0-9_]*' — "
        "непустой результат хотя бы на одной версии опровергает строку shaft"))

#: A HOLE INSIDE AN OPENING IS INEXPRESSIBLE — one reason shared by the
#: module header and the emitter's typed refusal
#: (`diag.EMIT_CONTOUR_HOLES`), the same trick as `VARIETIES_NOT_TAKEN`
#: above: two separately typed-up texts drift apart.
#:
#: The sketch language carries up to 8 holes, and for a ceiling or a slab
#: they make it all the way to `IList<CurveLoop>` — there, loops are a
#: LIST. An opening has exactly one profile: `NewOpening(Element,
#: CurveArray, bool)` accepts ONE `CurveArray`, and the documentation calls
#: it "Profile of the opening," singular. Appending a second loop into the
#: same array would mean handing Revit a self-intersecting profile and
#: hoping for the best; silently dropping it would lose a description the
#: author wrote. An island inside an opening is a DIFFERENT thing (an
#: untouched patch of the host), and it is expressed as two openings around
#: it, not one with a hole in it.
CONTOUR_HOLES_NOT_EXPRESSIBLE = (
    "у проёма профиль РОВНО ОДИН: NewOpening(Element, CurveArray, bool) "
    "принимает один CurveArray («Profile of the opening», единственное "
    "число), а не список петель, как Floor.Create/Ceiling.Create. Вторая "
    "петля в том же массиве — самопересекающийся профиль, молчаливый "
    "выброс — потеря написанного. Нетронутый остров внутри выреза "
    "выражается несколькими проёмами вокруг него")

#: `create_opening.cut` in words <-> the third argument of
#: NewOpening(Element, CurveArray, bool). ONE table for the emitter and
#: future reading — the same trick as `RAILING_PLACEMENT_MEMBERS` in the
#: railing wave. The meaning is taken VERBATIM from the `bPerpendicularFace`
#: parameter's documentation, not guessed.
CUT_PERPENDICULAR_FACE = {
    "vertical": "false",        # «False if the profile is cut vertically»
    "perpendicular": "true",    # «True if the profile is cut perpendicular
                                #   to the intersecting face of the host»
}

OPS = [
    OpSpec(
            name="create_opening",
            effect=EffectKind.CREATE,
            result=RESULT_ELEMENT,
            family="authoring",
            params=(
                # An opening's kind is a closed set of TAKEN overloads, not
                # of tastes. The kinds not taken are named in VARIETIES_NOT_TAKEN.
                ParamSpec("variety", "enum", required=True,
                          choices=("wall_rect", "host_face")),
                # THE HOST. `target_w` is the same reference kind
                # create_window uses to address its wall, and create_railing
                # its stair: both an EXISTING host ("cut an opening in this
                # slab") and one built by this same program. For an
                # opening, the first case is the main one: the hole is cut
                # into something already standing. `ref_kinds` is
                # deliberately broad: `variety` decides the host's kind, and
                # the ACTUAL class is checked at runtime (`as Wall` for
                # wall_rect) with a typed refusal, not a guess at parse time.
                ParamSpec("host", "target_w",
                          ref_kinds=(ReferenceKind.ELEMENT,
                                     ReferenceKind.WALL)),
                # variety="wall_rect": TWO OPPOSITE CORNERS of the
                # rectangle, required to be 3D (`pt_xyz`). A flat point
                # would silently land at elevation 0, and an opening's
                # height in a wall is exactly the Z axis: the sill and the
                # lintel. The same argument that makes create_beam require
                # 3D, and the same cost of getting it wrong.
                ParamSpec("p0_mm", "pt_xyz"),
                ParamSpec("p1_mm", "pt_xyz"),
                # variety="host_face": the opening's closed contour in
                # plan. EXACTLY ONE OF the two, together with `contour`
                # below; the requiredness of both is MUTUAL and additionally
                # conditional on the kind, which the schema cannot express —
                # it is held by the emitter's typed KIR-P005 ("neither one")
                # and the compiler's KIR-P007 ("both at once").
                ParamSpec("outline", "pts"),
                # variety="host_face", the SECOND shape input (08-09): a
                # CONTOUR sketch — rect/l/poly with small arcs, points as
                # literals or grid intersections. A round cutout for a
                # riser and a rounded cutout edge are INEXPRESSIBLE with a
                # polyline at all: `outline` is a polyline, and an arc under
                # it becomes a chord — that is, a DIFFERENT opening, not an
                # approximation. Holes in an opening's region are a typed
                # refusal (CONTOUR_HOLES_NOT_EXPRESSIBLE above): NewOpening
                # has exactly one profile.
                ParamSpec("contour", "region"),
                # variety="host_face": HOW to cut. Deliberately WITHOUT A
                # DEFAULT — a vertical cut and a perpendicular cut coincide
                # only on a flat host, and on a slope they give different
                # openings. Substituting one for the author would mean
                # building the wrong thing on a roof and staying silent
                # about it. Exactly the same reason `position` is required
                # for a railing on a stair.
                ParamSpec("cut", "enum",
                          choices=("vertical", "perpendicular")),
            ),
            capability=(("create", "element"),),
            # WHAT IS PROMISED IS EXACTLY WHAT IS CHECKED, and every promise
            # is read FROM THE BUILT ELEMENT, not from our own arguments.
            # A semicolon SEPARATES obligations (translation_cert.py splits
            # `post` exactly on it) — there must be none inside a clause.
            # THE PROMISE MATCHES THE WITNESS EXACTLY, including what the
            # witness does NOT pin down. For wall_rect, the ABSOLUTE top and
            # bottom elevations and the WIDTH of the opening are checked,
            # but the shift along the wall is not: Revit projects the given
            # points onto the wall's location plane, and the absolute X/Y
            # legitimately drift by half its thickness. Promising them would
            # mean rolling back a CORRECT opening — literally create_beam's
            # defect; full account in opening_emit.py's header.
            post=("opening element exists (materialized or typed refusal); "
                  "Opening.Host == the host element the program asked for "
                  "(topology); "
                  "variety=wall_rect: IsRectBoundary and the BoundaryRect "
                  "corners hold the requested Z band and the requested width "
                  "along the wall (±50mm, geometry), while the absolute shift "
                  "along the wall stays deliberately unpinned; "
                  "variety=host_face with outline: the BoundaryCurves extents "
                  "== outline extents for a vertical cut, and contain them "
                  "for a perpendicular cut (±50mm, geometry); "
                # THE SKETCH'S BOUNDING BOX IS A BAND, NOT AN EQUALITY, and
                # what is promised is exactly what the re-read returns. A
                # named remainder inside the clause: the witness does not
                # discriminate an arc's sagitta (sampling via
                # `Curve.Evaluate` is finite, and the API does not promise a
                # density — inventing a number there is forbidden), and the
                # cut's depth and the fact that "material was removed" are
                # not readable at all.
                  "variety=host_face with contour: the BoundaryCurves extents "
                  "cover the contour vertex extents and, for a vertical cut, "
                  "stay inside the contour arc-aware extents (±50mm, "
                  "geometry) — the arc sagitta between those two bounds and "
                  "the depth of the cut are deliberately unwitnessed"),
            writes_model=True,
            # Nothing to ground: an opening has neither a type nor a level
            # (see the header).
            grounded=(),
            # One number for both branches: ±50 mm — the same bounding-box
            # tolerance and the same key as for a floor, a ceiling, and a
            # foundation slab. An opening is a cut-out extent; measuring it
            # differently from the host itself would mean two truths about
            # one quantity.
            tolerances={"bbox_mm": 50.0},
        ),
]
