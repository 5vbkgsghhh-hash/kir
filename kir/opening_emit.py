"""opening_emit — emission of `create_opening` (the paired file to
`ops_opening.py`, exactly as `struct_emit.py` pairs with `ops_struct.py` and
`arch_emit.py` with `ops_arch.py`).

Its own wave zone: this module does not touch any foreign `ops_*.py` and no
foreign `*_emit.py`. `authoring.py` receives an additive import and ONE line
in `_EMITTERS` — the same minimal seam through which the framing,
architecture, and shape waves were plugged in.

Reused from `authoring.py` WITHOUT CHANGES (by import, not by copy): `_cs`,
`_eid`, `_safe`, `_stamp_block`, `_readback_block`. The same list and the same
caveat as in the headers of `struct_emit.py`/`arch_emit.py`: some of the
names are private, and the clean seam is fixed by promoting them in
`authoring.py`, not by copying their bodies here.

═══ WHAT MATTERS HERE MOST: THE WITNESS CHECKS THE RESULT, NOT THE CALL'S ECHO ══════

Both branches read THREE facts FROM THE BUILT ELEMENT:

  1. the opening exists — `NewOpening` returned non-null, otherwise a typed
     refusal (`refuse_stmt`, never a silent skip). This same spot catches the
     LEGITIMATE Revit refusal «Slanted stacked walls do not support
     rectangular openings» — it must arrive loudly;
  2. the opening BELONGS TO the REQUESTED host — `Opening.Host.Id` is checked
     against the id of the element WE OURSELVES just resolved. Not against
     the program's argument, but against the resolved element of the document;
  3. the extent matches — `Opening.BoundaryRect` is read (a rectangular
     opening) or `Opening.BoundaryCurves` (a profiled one). Both members 6/6.

There is exactly one tolerance, and it arrives ONLY as the `emit_model.tolerance`
object (the LAW OF PROVENANCE, `emit_model.py`): a number typed by hand
nearby will not build a witness.

═══ WHAT THE WITNESS DELIBERATELY DOES NOT CHECK, AND WHY ═══════════════════════

`wall_rect`: the top and bottom elevations (Z) and the opening's WIDTH
(horizontal distance between the corners) are compared ABSOLUTELY. The
opening's position ALONG the wall in absolute X/Y is NOT checked, and this
is not an oversight.

Revit projects both given points onto the wall's location plane. The
location plane is not necessarily the one the given points lie on: a wall
has a thickness and a `WALL_KEY_REF_PARAM` setting (centerline, interior
face, exterior face...), so the X/Y of the built rectangle LEGITIMATELY
differ from the given ones by half the wall's thickness or more. Comparing
them verbatim would mean rolling back a CORRECTLY built opening — exactly
the defect that made `create_beam` demand a promise from Revit that
"reference level == the one passed," and which cost the rollback of correct
beams (see the comment in `struct_emit.emit_beam`).

Projection onto a VERTICAL plane (and a rectangular opening cannot have any
other — sloped walls do not support them per the spec) preserves EXACTLY two
quantities: the Z coordinate and the component along the wall. Both are
checked. What remains unpinned — the shift along the wall — is named here, not hidden.

`host_face`: the extent is checked DIFFERENTLY for the two cuts, and this
follows from the documentation, not from caution:
  * `cut="vertical"` — the profile is cut vertically, i.e. the opening's plan
    IS our contour: EQUALITY of extents is checked;
  * `cut="perpendicular"` — the profile is cut perpendicular to the host's
    face, and on a slope its plan is WIDER than the contour (on a flat host
    it coincides). INCLUSION is checked: the opening's extent must cover the
    contour. Requiring equality here would mean rejecting a correct opening
    on any sloped roof.
A lower bound instead of equality is not a concession but this house's
`Certainty.AT_LEAST`, named verbatim in `OpSpec.post`.

═══ THE CONTOUR SKETCH: WHAT THE CUT WITNESS IS ENTITLED TO ASSERT (2026-08-09) ═══════

`host_face` received a SECOND profile input — a `contour` of kind `region`
(a rect/l/poly sketch with small arcs and axis-intersection points).
Emission diverges in exactly two places: assembling the `CurveArray`
(straight segments versus Line/Arc from canonical edges) and the NUMBER
against which the extent is checked. Everything else — resolving the host,
Regenerate, the profile's elevation, the null refusal, the stamp, ownership
by the host, the receipt — is shared, and this is not saving lines: two
copies of the tail drift apart, and a drifted witness means nothing.

THE MAIN QUESTION OF THIS WAVE WAS NOT "HOW TO BUILD" BUT "WHAT CAN HONESTLY
BE READ FROM THE CUT AFTER THE COMMIT." The answer is measured against
reference XML, not derived by reasoning, and it is NARROWER than for a slab
or a ceiling:

  * `Opening.Host` (6/6) — ownership. Full strength, read from the opening.
  * `Opening.BoundaryCurves` (6/6) — «geometry information for
    non-rectangular openings in project documents». This is the PLAN
    BOUNDARY and nothing more.
  * `Curve.GetEndPoint(int)` (6/6) — a curve's end EXACTLY.
  * `Curve.Evaluate(double, bool)` (6/6) — «the point that matches a
    parameter along the curve», i.e. a point GUARANTEED TO BE ON the boundary.

What is NOT in this set, and therefore not promised:

  1. Nothing reads the CUT DEPTH or the fact "MATERIAL WAS REMOVED."
     `Opening` is a void: it has no body, and the documentation does not
     promise `get_BoundingBox` for it (`Ceiling`/`Floor` do have an extent,
     and that is why their witness is STRONGER — there the extent of THE
     ELEMENT ITSELF is checked). Asserting that the host has been cut through
     can only be done by a live Revit, from its body's volume before and
     after; no such assertion exists offline, and it must not be invented here.
  2. EQUALITY OF EXTENT WITH AN ARCED SKETCH. An arc's extremum lies INSIDE
     the curve, not at its end, and is only obtained by sampling along the
     parameter; the sample is finite, and the `Evaluate` API makes no promise
     about density. The extent read is therefore a LOWER bound on the real
     one, and demanding an exact `edges_bbox` from it would mean assigning a
     tolerance for sampling density, i.e. inventing a number (this house's
     class of defect: `docspace._SHEET_LIMIT_MM`, `create_door.sill_mm`).

Therefore the sketch's extent is checked as a BAND, and both of its bounds
are promises from the API, not our own assumptions:

     edges_vertex_bbox  <=  the extent read  <=  edges_bbox      (± tolerance)
     ^^^^ vertices, given EXACTLY by GetEndPoint   ^^^^ no boundary point of
          => this is the LOWER bound, and it              the vertical cut is
          must be covered                                 allowed to stick out
                                                            beyond it

For a profile WITHOUT ARCS, both bounds coincide, and the band degenerates
into EQUALITY — exactly what the straight branch does. That is, the contour
branch is not "weaker," it generalizes the straight one and coincides with
it wherever the straight one is right.

THE NAMED RESIDUE: within the band (this is exactly the arc's sagitta) the
witness cannot tell the difference — a boundary reproduced with a chord
instead of an arc would pass both checks. What IS caught, and the reason
sampling is emitted at all: an arc bulged the WRONG WAY or to the WRONG
size goes past the upper bound and fails loudly — that is, what ends up
under control is our own `bulge`-sign trigonometry, computed in Python.
Sampling is emitted ONLY when the profile has an arc: for straight segments
the ends are already the extrema, and extra points would add not a single fact.

`cut="perpendicular"` remains a LOWER bound in the contour branch too: on a
slope the cut's plan is legitimately wider than the profile, so the upper
bound is not required there — its absence is named, not forgotten.

═══ THE PROFILE'S ELEVATION — GIVEN BY THE HOST, NOT BY ZERO ═════════════════════════

`outline` is the contour IN PLAN (mm), without Z. Placing it at elevation 0
would be a quiet lie: a 17th-floor slab does not sit there, and the profile
would simply not intersect the host. The golden code of both reference
implementations places the profile ON THE HOST'S PLANE (the Autodesk SDK's
`NewOpenings` builds it from the points of the element's own sketch; BHoM
explicitly projects: `hole.IProject(slabPlane)`).

So the elevation is read LIVE from the host itself: the midpoint of its
extent along Z. This is not a guess but a consequence: for a connected,
slab-like body, the extent's midplane intersects the body at ANY slope, i.e.
the profile is guaranteed to land inside the host. No extent — a typed
refusal, not a zero.
"""
from __future__ import annotations

from kir import contour as C
from kir.emit_core import (  # noqa: F401
    _cs, _eid, _safe, _stamp_block,
    _readback_block,
)
from kir.emit_model import WitnessCheck, tolerance
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import (
    Diagnostic, EMIT_CONTOUR_HOLES, EMIT_UNSUPPORTED_ENUM, KirRefusal,
    PARSE_EXCLUSIVE_FIELDS, PARSE_MISSING_FIELD)
from kir.ops_opening import (
    CONTOUR_HOLES_NOT_EXPRESSIBLE, CUT_PERPENDICULAR_FACE, VARIETIES_NOT_TAKEN)

#: An opening kind outside the closed set {wall_rect, host_face}.
#: A belt over the suspenders: `ParamSpec`'s `enum`-choices already catches
#: this at `authoring.validate()` (KIR-T001), and this check is defense in
#: depth inside the emitter itself, exactly like `FOUNDATION_UNSUPPORTED_KIND`
#: for the framing wave and `RAILING_UNSUPPORTED_VARIETY` for the
#: architecture wave. Whoever extends `choices` without adding a branch will
#: land here: let it fail LOUDLY, rather than silently build the wrong
#: thing. The reason for each untaken kind is taken from the ONE
#: `ops_opening.VARIETIES_NOT_TAKEN` table, not typed up again here.

#: A sketch WITH HOLES for the opening: `NewOpening` has exactly one profile,
#: there is no such thing as a list of loops. Not "not done yet" but "nothing
#: to say" — the reason is taken from the ONE
#: `ops_opening.CONTOUR_HOLES_NOT_EXPRESSIBLE` table, so the registry's
#: header and the emitter's refusal do not drift apart. A separate code, not
#: E007: that one means "this opening kind is not taken," and conflating
#: "no such kind" with "the taken kind has no such form" would send the
#: author to fix the wrong thing.


def _host_id_cs(op: dict, ver: str, oid: str) -> str:
    """The C# expression for the host's id: a pinned id, or a reference within the program.

    Both paths go through `doc.GetElement(...)` DELIBERATELY, not by casting
    a neighboring op's variable directly: `__el_<ref> as Wall` for a
    reference to a slab is a cross-kind cast (CS0039), i.e. a C# COMPILER
    failure instead of a typed KIR refusal. Going through `Id` always
    compiles, and the wrong kind is caught by a live `as Wall` check below —
    where the refusal can be given a human name.
    """
    host = op.get("host") or {}
    if host.get("by") == "ref":
        return "__el_" + _safe(str(host.get("value"))) + ".Id"
    return _eid(host["value"], ver, oid)


def _require(op: dict, field: str, message: str) -> None:
    """A conditionally required field: a typed KIR-P005, not a bare KeyError.

    The same seam and the same reason as in `emit_foundation`/`emit_railing`:
    `ParamSpec.required` cannot express "required only for this kind," and a
    bare KeyError would surface as KIR-P000 "internal error" — fail-closed,
    but with worse diagnostics.
    """
    if op.get(field) is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name=field,
            message_ru=message)])


def _host_witness(s: str, oid: str, host_var: str, human: str) -> WitnessCheck:
    """"The opening BELONGS TO the REQUESTED host" — topology read from the
    opening itself (`Opening.Host`, 6/6), not from our intent.

    ``human`` is a READY-MADE case-inflected form («запрошенной стене»,
    «запрошенному носителю»), not a bare stem: gluing a Russian message
    together from «запрошенному» plus a noun means printing «запрошенному
    стене». A diagnostic one would be ashamed of reads as carelessness elsewhere too.
    """
    return WitnessCheck(
        obligation_key="host",
        reader_cs=f"    var __hh_{s} = __el_{s}.Host;\n",
        verdict_cs=(
            f"    if (__hh_{s} == null)\n"
            f"        __post.Add({_cs(oid + ': у проёма нет носителя (topology)')});\n"
            f"    else if (__hh_{s}.Id.ToString() != {host_var}.Id.ToString())\n"
            f"        __post.Add({_cs(oid + ': проём не принадлежит ' + human + ' (topology)')});\n"),
        message=f"проём не принадлежит {human} (topology)",
        style="else_block")


# ── variety="wall_rect" ─────────────────────────────────────────────────────

def _emit_wall_rect(op: dict, ver: str, stamp: str,
                    isolation: str) -> tuple[str, str, list, str]:
    """A rectangular opening in a wall.

    `Autodesk.Revit.Creation.Document.NewOpening(Wall, XYZ, XYZ)` — 6/6, the
    form checked against the Autodesk SDK's golden sample
    (`NewOpenings/CS/ProfileWall.cs:65`: `m_docCreator.NewOpening(m_data,
    p1, p2)`).
    """
    oid = op["id"]
    s = _safe(oid)
    # THIS KIND HAS NOTHING TO SAY TO A SKETCH, AND IT CANNOT BE SILENTLY DROPPED.
    # `NewOpening(Wall, XYZ, XYZ)` does not accept a profile at all — the
    # opening's kind is given by two corners. Accepting a `contour` and not
    # looking at it would mean building a rectangle where the author wrote an
    # arc, and staying silent about it: exactly the silent outcome the
    # opening wave was set up to forbid. The refusal is typed and uses the
    # mutual-exclusion code — the kind and the sketch really are incompatible.
    if op.get("contour") is not None:
        raise KirRefusal([Diagnostic(
            code=PARSE_EXCLUSIVE_FIELDS, op_id=oid, field_name="contour",
            expected="variety=host_face", got="variety=wall_rect",
            message_ru=(
                "create_opening(variety=wall_rect): contour несовместим с "
                "этим родом — NewOpening(Wall, XYZ, XYZ) профиля не "
                "принимает вообще, прямоугольный проём в стене задаётся "
                "двумя противоположными углами (p0_mm/p1_mm). Эскиз "
                "работает у variety=host_face"))])
    _require(op, "host",
             "create_opening(variety=wall_rect): host обязателен — это и есть "
             "стена, в которой режется проём")
    _require(op, "p0_mm",
             "create_opening(variety=wall_rect): p0_mm обязателен — угол "
             "прямоугольника")
    _require(op, "p1_mm",
             "create_opening(variety=wall_rect): p1_mm обязателен — "
             "противоположный угол прямоугольника")
    p0, p1 = op["p0_mm"], op["p1_mm"]
    host_id = _host_id_cs(op, ver, oid)
    decl = (f"Opening __el_{s} = null;\n"
            f"Wall __hw_{s} = null;")
    create = (
        f"// create_opening(wall_rect) {cs_line_comment_fragment(oid)}\n"
        f"__hw_{s} = doc.GetElement({host_id}) as Wall;\n"
        f"if (__hw_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('носитель проёма не читается как стена (модель изменилась после grounding или id указывает не на стену)'), isolation)} }}\n"
        # REGENERATE BEFORE THE CUT, and this is not decoration. The host can
        # be created BY THIS SAME program (`host: {by: ref}`), and NewOpening
        # cuts against geometry that an unregenerated element does not have yet.
        # Production BHoM does exactly this (`ToRevit/Floor.cs:108` —
        # `document.Regenerate()` right before NewOpening).
        # Placed unconditionally, not only on the ref branch: different
        # emission for two forms of the same selector is an unnecessary
        # branch point, and an extra Regenerate inside an already-open
        # transaction costs nothing.
        f"doc.Regenerate();\n"
        f"__el_{s} = doc.Create.NewOpening(__hw_{s}, "
        f"P({p0[0]}, {p0[1]}, {p0[2]}), P({p1[0]}, {p1[1]}, {p1[2]}));\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание прямоугольного проёма в стене вернуло null (наклонные и многослойные стены прямоугольных проёмов не поддерживают — ремарка спеки)'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    tol = tolerance("create_opening", "bbox_mm")
    zmin, zmax = min(p0[2], p1[2]), max(p0[2], p1[2])
    width = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
    checks: list[WitnessCheck] = [
        _host_witness(s, oid, f"__hw_{s}", "запрошенной стене"),
        WitnessCheck(
            obligation_key="rect_extent",
            # THE BOUNDARY OF THE OPENING ITSELF IS READ. `BoundaryRect` is
            # documented as «geometry information if the opening boundary is
            # a rect» and as null when `IsRectBoundary == false`, so both
            # values are taken together: rectangularity is a result just like
            # the size. Indexing with [0]/[1] and Linq's `Count()` work on
            # both `IList<XYZ>` and an array — the documentation does not
            # name the kind of collection, and `var` on its own proves
            # nothing (a lesson from the railings wave: `var __r = ...`
            # compiles for any type).
            reader_cs=(
                f"    var __br_{s} = __el_{s}.BoundaryRect;\n"
                f"    int __brn_{s} = __br_{s} == null ? 0 : "
                f"System.Linq.Enumerable.Count(__br_{s});\n"),
            verdict_cs=(
                f"    if (!__el_{s}.IsRectBoundary || __brn_{s} != 2)\n"
                f"        __post.Add({_cs(oid + ': граница проёма не прямоугольник (geometry)')});\n"
                f"    else\n    {{\n"
                f"        double __bz0_{s} = Math.Min(MM(__br_{s}[0].Z), MM(__br_{s}[1].Z));\n"
                f"        double __bz1_{s} = Math.Max(MM(__br_{s}[0].Z), MM(__br_{s}[1].Z));\n"
                f"        double __bw_{s} = Math.Sqrt(\n"
                f"            Math.Pow(MM(__br_{s}[0].X) - MM(__br_{s}[1].X), 2)\n"
                f"          + Math.Pow(MM(__br_{s}[0].Y) - MM(__br_{s}[1].Y), 2));\n"
                f"        if (Math.Abs(__bz0_{s} - {zmin}) > {tol} || Math.Abs(__bz1_{s} - {zmax}) > {tol}\n"
                f"            || Math.Abs(__bw_{s} - {width}) > {tol})\n"
                f"            __post.Add({_cs(oid + ': rect extents mismatch (geometry)')});\n"
                f"    }}\n"),
            message="rect extents mismatch (geometry)",
            tol=tol, style="else_block"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


# ── variety="host_face" ─────────────────────────────────────────────────────

def _profile_curve_array(outline: list, name: str, z_var: str) -> list[str]:
    """A CLOSED profile in a `CurveArray` at the RUNTIME elevation `z_var`.

    Its own helper, not `_loop_pts`: that one builds a `CurveLoop` (required
    by `Floor.Create`/`Ceiling.Create`), while `NewOpening` accepts a
    `CurveArray` — a different type, and there is nothing to substitute one
    for the other with. Also, the elevation here is an EXPRESSION, not a
    literal: `P(x, y, z)` would pass it through `U()` a second time, and it
    is already in internal units (read from the host).

    The closing segment is added EXPLICITLY — exactly as in the Autodesk
    golden sample (`ProfileFloor.cs:95-99` appends the last segment from the
    last point back to the first). The ring here MUST be closed: this is a
    cut-out profile, not a railing path.

    THE ELEVATION'S UNITS CHANGED AT THE MERGE ON 2026-08-09, and the
    docstring above about "already in internal units" was true exactly up
    until then. `__z_` is now in MILLIMETERS — converted by `MM(...)` at the
    source — because the op's second branch moved to the shared
    `contour._edge_curve_cs` assembler, which expects millimeters, like the
    rest of the language. Two branches of ONE op with different elevation
    units is a silently-wrong result waiting for its first opening above the
    ground floor; hence `U()` is applied here too.
    """
    out = [f"CurveArray {name} = new CurveArray();"]
    n = len(outline)
    for k in range(n):
        a, b = outline[k], outline[(k + 1) % n]
        out.append(
            f"{name}.Append(Line.CreateBound("
            f"new XYZ(U({a[0]}), U({a[1]}), U({z_var})), "
            f"new XYZ(U({b[0]}), U({b[1]}), U({z_var}))));")
    return out


def _boundary_extents_reader(s: str, samples: int) -> str:
    """C# that takes the PLAN extent from the boundary of THE OPENING ITSELF.

    `Opening.BoundaryCurves` is read — «geometry information for
    non-rectangular openings in project documents» — meaning that for a
    profiled opening it IS FILLED IN BY SPECIFICATION, whereas the
    documentation promises nothing about `get_BoundingBox` on an `Opening`.
    A witness must read what the API promises to return.

    ``samples`` is how many points are taken FROM EACH curve:

      * ``0`` — endpoints only (`GetEndPoint`, 6/6). For a profile WITHOUT
        ARCS this is sufficient IN SUBSTANCE: every segment is straight, and
        any point on it lies within the extent of its own endpoints. This is
        exactly the emission that stood here before 08-09 — the straight
        branch must remain byte-for-byte the same;
      * ``N > 0`` — `Evaluate(k/N, true)`, «the point that matches a
        parameter along the curve» (6/6), i.e. points GUARANTEED TO BE ON the
        boundary, including the interior of an arc. They are needed EXACTLY
        for the band's upper bound (see the module header): a point that
        strays past the sketch's extent is a loud refusal, and this is
        exactly how an arc bulged the wrong way is caught.

    The density N is taken from `contour.ARC_SAMPLES` — the same number the
    canon uses to unroll an arc in its own static laws. A new number here
    would be a second answer to the question "how many points do we look at an arc with."

    ``IsBound`` (6/6) — because `Evaluate(..., normalized: true)` throws on an
    unbounded curve per the documentation. An unbounded curve simply yields
    no points; if NOT A SINGLE ONE yields any, `__on_` stays zero and the
    verdict says so LOUDLY, rather than quietly accepting an empty extent.

    ONE DECLARATOR PER STATEMENT, not ``double a = 0, b = 0;``. This is not a
    style choice: the scope contract (`_DECL` in test_emitter_scope_contract)
    reads the declaration with a regex and sees only the FIRST name in the
    list — the rest would look "declared nowhere," i.e. the contract would
    silently weaken exactly where the emitter grows more complex.
    """
    if samples:
        walk = (f"            if (!__c_{s}.IsBound) continue;\n"
                f"            for (int __k_{s} = 0; __k_{s} <= {samples}; __k_{s}++)\n            {{\n"
                f"                var __pt_{s} = __c_{s}.Evaluate(__k_{s} / {samples}.0, true);\n")
    else:
        walk = (f"            for (int __k_{s} = 0; __k_{s} < 2; __k_{s}++)\n            {{\n"
                f"                var __pt_{s} = __c_{s}.GetEndPoint(__k_{s});\n")
    return (
        f"    var __bc_{s} = __el_{s}.BoundaryCurves;\n"
        f"    double __ox0_{s} = 0;\n"
        f"    double __ox1_{s} = 0;\n"
        f"    double __oy0_{s} = 0;\n"
        f"    double __oy1_{s} = 0;\n"
        f"    int __on_{s} = 0;\n"
        f"    if (__bc_{s} != null)\n    {{\n"
        f"        foreach (Curve __c_{s} in __bc_{s})\n        {{\n"
        + walk +
        f"                double __px_{s} = MM(__pt_{s}.X);\n"
        f"                double __py_{s} = MM(__pt_{s}.Y);\n"
        f"                if (__on_{s} == 0) {{ __ox0_{s} = __px_{s}; __ox1_{s} = __px_{s};"
        f" __oy0_{s} = __py_{s}; __oy1_{s} = __py_{s}; }}\n"
        f"                else {{ __ox0_{s} = Math.Min(__ox0_{s}, __px_{s});"
        f" __ox1_{s} = Math.Max(__ox1_{s}, __px_{s});\n"
        f"                       __oy0_{s} = Math.Min(__oy0_{s}, __py_{s});"
        f" __oy1_{s} = Math.Max(__oy1_{s}, __py_{s}); }}\n"
        f"                __on_{s}++;\n"
        f"            }}\n        }}\n    }}\n")


def _emit_host_face(op: dict, ver: str, stamp: str,
                    isolation: str) -> tuple[str, str, list, str]:
    """A profile-based opening in a slab, roof, or ceiling.

    `Autodesk.Revit.Creation.Document.NewOpening(Element, CurveArray, bool)` —
    6/6, «Creates a new opening in a roof, floor and ceiling». The form
    checked against the Autodesk SDK's golden sample
    (`NewOpenings/CS/ProfileFloor.cs:101`) and against production BHoM
    (`ToRevit/Floor.cs:114,127`).
    """
    oid = op["id"]
    s = _safe(oid)
    _require(op, "host",
             "create_opening(variety=host_face): host обязателен — это и есть "
             "перекрытие/кровля/потолок, в котором режется проём")
    # THE SHAPE IS STATED EXACTLY ONCE. "Both at once" is refused by the plan
    # (KIR-P007, the rule is read from the registry: a parameter of kind
    # `pts` and a parameter of kind `region` on one operation). "Neither one"
    # THE PLAN CANNOT SAY: for an operation with a `variety` branch,
    # requiredness is conditional on the kind, and the compiler does not
    # parse kinds — `wall_rect` has no shape in any form, and a blanket "no
    # shape given" refusal would blame a correct program. So the lower half
    # of the mutual requirement lives HERE, in the kind's branch, and names
    # BOTH inputs: an author who forgot the shape must learn about both.
    region = op.get("__region__")
    if region is None and op.get("outline") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="outline",
            expected="outline ЛИБО contour",
            message_ru=(
                f"create_opening(variety=host_face): форма проёма не задана "
                f"— нужен либо outline (замкнутая ломаная из "
                f"{C.MIN_RING_POINTS}..{C.MAX_RING_POINTS} точек в плане), "
                f"либо contour (эскиз CONTOUR: rect/l/poly, малые дуги, "
                f"точки-пересечения осей)"))])
    if region is not None and region["holes"]:
        # NOT A SKIP BUT A REFUSAL, and the reason comes from ONE registry table.
        raise KirRefusal([Diagnostic(
            code=EMIT_CONTOUR_HOLES, op_id=oid, field_name="contour.holes",
            got=len(region["holes"]),
            message_ru=(f"create_opening(variety=host_face): отверстия внутри "
                        f"эскиза невыразимы — {CONTOUR_HOLES_NOT_EXPRESSIBLE}"))])
    _require(op, "cut",
             "create_opening(variety=host_face): cut обязателен — "
             "вертикальный и перпендикулярный рез совпадают ТОЛЬКО на плоском "
             "носителе, а на скате дают разные проёмы; выбрать один за автора "
             "значило бы построить не то и промолчать")
    # A belt over the suspenders, like for the `variety` branch:
    # `enum`-choices already closed the set at parse time, but the cuts table
    # and the choices list live side by side and can drift apart. A bare
    # KeyError would surface as KIR-P000 "internal error" — fail-closed, but
    # with worse diagnostics.
    if op["cut"] not in CUT_PERPENDICULAR_FACE:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="cut",
            got=op["cut"], candidates=sorted(CUT_PERPENDICULAR_FACE),
            message_ru=(f"create_opening: рез {op['cut']!r} не поддержан — у "
                        f"NewOpening(Element, CurveArray, bool) ровно два "
                        f"значения третьего аргумента"))])
    perpendicular = CUT_PERPENDICULAR_FACE[op["cut"]]
    host_id = _host_id_cs(op, ver, oid)
    decl = (f"Opening __el_{s} = null;\n"
            f"Element __hst_{s} = null;")
    if region is not None:
        # The CONTOUR sketch. All arc trigonometry is computed in Python at
        # the ground stage: three LITERAL points per arc travel to C#
        # (Arc.Create(start, end, point-on-arc), 6/6), so the versions do not
        # diverge here. The profile's elevation is the same runtime
        # expression as in the straight branch: it is given by the host, not by zero.
        edges = region["outer"]
        geo = C.emit_curvearray_cs(edges, f"__ca_{s}",
                                   z=f"__z_{s}").split("\n")
    else:
        geo = _profile_curve_array(op["outline"], f"__ca_{s}", f"__z_{s}")
    create = (
        f"// create_opening(host_face) {cs_line_comment_fragment(oid)}\n"
        f"__hst_{s} = doc.GetElement({host_id});\n"
        f"if (__hst_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('носитель проёма не найден (модель изменилась после grounding)'), isolation)} }}\n"
        f"doc.Regenerate();\n"
        f"var __hbb_{s} = __hst_{s}.get_BoundingBox(null);\n"
        f"if (__hbb_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('у носителя проёма нет габарита — отметку профиля взять неоткуда, а нулевая была бы тихой неправдой'), isolation)} }}\n"
        # UNITS ARE CONVERTED HERE, AT THE SOURCE (merge 2026-08-09).
        # `BoundingBoxXYZ` returns INTERNAL units, while the shared edge
        # assembler `contour._edge_curve_cs` assembles a point via `P()`,
        # i.e. it expects MILLIMETERS — like the other branch of the same
        # helper (framing puts in `MM(__lv.Elevation)`). Without `MM` here,
        # the elevation would go through `U()` a second time: the profile
        # would end up roughly 304.8 times too high, C# would compile
        # identically on all six versions, and this could only be seen on a
        # live model above the ground floor.
        f"double __z_{s} = MM((__hbb_{s}.Min.Z + __hbb_{s}.Max.Z) / 2.0);\n"
        + "\n".join(geo) + "\n"
        f"__el_{s} = doc.Create.NewOpening(__hst_{s}, __ca_{s}, {perpendicular});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание проёма по профилю вернуло null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    tol = tolerance("create_opening", "bbox_mm")
    if region is not None:
        # THE SKETCH'S EXTENT IS A BAND BETWEEN TWO API PROMISES, not one
        # number (the analysis is in the module header):
        #   * `edges_bbox` knows the arcs' cardinal extrema and is therefore
        #     the UPPER bound: a boundary point of the vertical cut does not
        #     go past it;
        #   * `edges_vertex_bbox` takes only the vertices and is therefore
        #     the LOWER one: `GetEndPoint` gives a vertex EXACTLY, with no sampling at all.
        # For a profile without arcs, both coincide, and the band degenerates
        # into equality — exactly the check the straight branch performs.
        ex0, ey0, ex1, ey1 = (round(v, 1) for v in C.edges_bbox(edges))
        vx0, vy0, vx1, vy1 = (round(v, 1)
                              for v in C.edges_vertex_bbox(edges))
        # Sampling ONLY when there is an arc: for straight segments the ends
        # are already the extrema, and extra points would add not a single
        # fact — but would split the emission of two equivalent profiles apart.
        samples = (C.ARC_SAMPLES
                   if any(abs(b) >= C.STRAIGHT_BULGE_EPS for _p0, _p1, b in edges) else 0)
        if op["cut"] == "vertical":
            human_verdict = "opening extents leave the contour band (geometry)"
            compare = (
                f"        if (__ox0_{s} < {ex0} - {tol} || __ox0_{s} > {vx0} + {tol}\n"
                f"            || __ox1_{s} > {ex1} + {tol} || __ox1_{s} < {vx1} - {tol}\n"
                f"            || __oy0_{s} < {ey0} - {tol} || __oy0_{s} > {vy0} + {tol}\n"
                f"            || __oy1_{s} > {ey1} + {tol} || __oy1_{s} < {vy1} - {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents leave the contour band (geometry)')});\n")
        else:
            # A perpendicular cut on a slope is legitimately WIDER than the
            # profile, so there is no upper bound here — only the lower one
            # remains, and this is named, not forgotten.
            human_verdict = "opening extents do not cover the contour (geometry)"
            compare = (
                f"        if (__ox0_{s} > {vx0} + {tol} || __ox1_{s} < {vx1} - {tol}\n"
                f"            || __oy0_{s} > {vy0} + {tol} || __oy1_{s} < {vy1} - {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents do not cover the contour (geometry)')});\n")
        obligation_key = "bbox_contour"
    else:
        outline = op["outline"]
        samples = 0
        xs = [pt[0] for pt in outline]
        ys = [pt[1] for pt in outline]
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        if op["cut"] == "vertical":
            human_verdict = "opening extents mismatch (geometry)"
            compare = (
                f"        if (Math.Abs(__ox0_{s} - {xmin}) > {tol} || Math.Abs(__ox1_{s} - {xmax}) > {tol}\n"
                f"            || Math.Abs(__oy0_{s} - {ymin}) > {tol} || Math.Abs(__oy1_{s} - {ymax}) > {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents mismatch (geometry)')});\n")
        else:
            # A perpendicular cut on a slope gives a plan WIDER than the
            # contour — INCLUSION is checked, not equality (see the module
            # header). The same tolerance.
            human_verdict = "opening extents do not cover the outline (geometry)"
            compare = (
                f"        if (__ox0_{s} > {xmin} + {tol} || __ox1_{s} < {xmax} - {tol}\n"
                f"            || __oy0_{s} > {ymin} + {tol} || __oy1_{s} < {ymax} - {tol})\n"
                f"            __post.Add({_cs(oid + ': opening extents do not cover the outline (geometry)')});\n")
        obligation_key = "bbox"
    checks: list[WitnessCheck] = [
        _host_witness(s, oid, f"__hst_{s}", "запрошенному носителю"),
        WitnessCheck(
            # THE KEYS ARE DIFFERENT FOR THE TWO SHAPE INPUTS, and this is
            # not pedantry: a conditional requirement is discharged exactly
            # by the ABSENCE of its own witness (`certify_op`), so a shared
            # key across two mutually exclusive branches would declare the
            # neighboring branch's witness "extra." The same reasoning is why
            # the extent keys `rect_extent` and `bbox` for the two opening
            # kinds are also different.
            obligation_key=obligation_key,
            # THE BOUNDARY OF THE OPENING ITSELF IS READ, not the element's
            # extent — the analysis and both sampling modes are in
            # `_boundary_extents_reader`.
            reader_cs=_boundary_extents_reader(s, samples),
            verdict_cs=(
                f"    if (__on_{s} == 0)\n"
                f"        __post.Add({_cs(oid + ': у проёма нет граничных кривых (geometry)')});\n"
                f"    else\n    {{\n"
                + compare +
                f"    }}\n"),
            # The message is branch-specific: equality and inclusion have
            # DIFFERENT verdicts, and one text for both would lie to the
            # audit about what was checked.
            message=human_verdict,
            tol=tol, style="else_block"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


# ── the branch ────────────────────────────────────────────────────────────────

def emit_opening(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """The branch over the closed set {wall_rect, host_face}.

    A value outside the set is a typed refusal that NAMES the reason for the
    kinds the wave deliberately did not take (`VARIETIES_NOT_TAKEN`): "not
    supported" without a reason is indistinguishable from "forgotten," and an
    untaken kind must be distinguishable from a nonexistent one.
    """
    variety = op.get("variety")
    if variety == "wall_rect":
        return _emit_wall_rect(op, ver, stamp, isolation)
    if variety == "host_face":
        return _emit_host_face(op, ver, stamp, isolation)
    _nt = VARIETIES_NOT_TAKEN.get(variety)
    why = _nt.reason if _nt else None
    raise KirRefusal([Diagnostic(
        code=EMIT_UNSUPPORTED_ENUM, op_id=op.get("id"),
        field_name="variety", got=variety,
        candidates=["wall_rect", "host_face"],
        message_ru=(f"create_opening: род проёма {variety!r} не поддержан — {why}"
                    if why else
                    f"create_opening: род проёма {variety!r} не поддержан "
                    f"(взяты wall_rect и host_face — у остальных перегрузок "
                    f"NewOpening нет полного свидетеля, см. ops_opening.py)"))])


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (2026-09-02).
#: Before, the "op -> body" correspondence lived in the hand-written
#: `authoring._EMITTERS`, while the body lived here, and a thin wrapper in
#: the hub linked them (41 of them across 19 satellites). Two records of one
#: fact in different files — this tree's own named defect; now there is ONE
#: record, and the hub ASKS it.
EMITTERS = {
    "create_opening": emit_opening,
}
