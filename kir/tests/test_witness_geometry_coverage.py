"""Every op that builds geometry must have a witness that can see geometry.

Three times in one night a postcondition passed over wrong geometry, and each
time for the same reason: the witness checked what the emitter had just set
rather than what the author had asked for.

* a wall's location line — compared an enum ordinal, while the wall body stood
  where it always had;
* a slanted column — demanded back a level parameter the emitter deliberately
  never wrote;
* a pitched roof — asked whether the roof had gained ANY height, and accepted
  one built at 38 degrees instead of 45.

A witness written in the same hour, by the same hand, as the emission it
guards inherits that emission's blind spots. The only obligation that does not
is one phrased against geometry Revit reports back independently: a location,
a curve endpoint, a bounding box, an elevation.

So this is a structural rule, not a review habit: an emitter that creates
geometry must reference at least one of those. The allowlist below is for ops
that genuinely create none, and every entry states why.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from kir.record_ratchet import CLOSE_BY, Entry, Ledger

_IR_DIR = pathlib.Path(__file__).resolve().parents[1]

#: Helpers whose whole purpose is a geometric obligation.
#:
#: ``_network_geometry_post`` joined the list on 2026-08-09, and the delay is
#: the lesson. It has read every created segment's ``LocationCurve`` endpoints
#: back since 2026-07-27 (commits ``97892ce5``/``557d55fc``), but the emitters
#: consume it as ``seg, dia, etol, dtol = _network_geometry_post(...)`` and the
#: delegation rule below only follows ``return f(...)``. So the detector could
#: not see a witness that was there, reported the two route ops as naked, and
#: the debt list below froze that phantom by name — where it then survived two
#: audits, because a name on a debt list reads as a measurement.
#:
#: An instrument that covers part of its range is worse than an absent one: it
#: answers, and the answer is believed. The rule for this tuple is therefore
#: narrow on purpose — a helper belongs here only if its WHOLE purpose is a
#: geometric obligation. Following every call transitively instead was measured
#: on 2026-08-09 and rejected: it clears ``_emit_wall_foundation_struct`` too,
#: whose geometry genuinely is not witnessed, so the loosening buys two true
#: answers at the price of one false one.
#:
#: ``emit_xyz_to_view2d_cs(`` joined on 2026-08-09 and satisfies the narrow
#: rule above exactly: its WHOLE purpose is to read a point off a BUILT element
#: back into the owner view's axes (``rel = P − Origin; u = rel·Right;
#: v = rel·Up``). It exists because the annotation family's inverse must be
#: IDENTICAL to its forward map, not merely similar, and one law cannot live in
#: three emitters.
#:
#: 🔴 FIVE COLLECTORS OF THE SOLIDS WAVE (2026-08-21), AND THIS IS AN
#: INSTRUMENT FIX, NOT A RELAXATION. The rule had declared `_emit_solid_boolean`,
#: `_emit_solid_sweep`, and `_emit_surface` "naked" — that is, it said their
#: wrong shape commits silently. MEASUREMENT says the opposite: compiling a
#: real sweep gives FOUR `__post.Add`, among them two reads of `Volume` and
#: one `get_BoundingBox` — witnesses reading the BUILT body back.
#:
#: It was the instrument that went blind, not the emitters: the 08.20 wave
#: brought in ITS OWN kind of collector (`_solid_count_check`,
#: `_sweep_volume_check`, `_sweep_containment_check`, `_cap_area_check`,
#: `_bbox_check` in `solid_emit.py`), while the marker list only knew four
#: names from the earlier waves. A false "naked" costs more than a miss: it
#: opens a debt against a working witness and draws the eye away from the
#: real ones.
#:
#: The names were taken by MEASURING the bodies of `emit_solid_sweep` /
#: `emit_solid_boolean`, not by guessing what they might be called.
_GEOMETRY_HELPERS = ("_solid_count_check(", "_sweep_volume_check(",
                     "_sweep_containment_check(", "_cap_area_check(",
                     "_bbox_check(",
                     "endpoint_witness(", "bbox_extents_witness(",
                     # 🔴 THE INSTRUMENT WAS WIDENED, NOT WEAKENED (2026-08-26),
                     # and the reason is a FALSE POSITIVE it found itself.
                     # `create_railing` lost its dimension obligation: it
                     # checked the railing's BODY (posts, handrail) against
                     # the path LINE and was non-deterministic on a quantity
                     # equal to the tolerance. Removing it was correct — but
                     # the guard declared the op "naked," even though right
                     # next to it stands `path_points_witness`, which reads
                     # the re-read `GetPath()` and compares edge endpoints on
                     # a ±1 mm grid, that is, MORE PRECISELY than what was
                     # removed.
                     #
                     # The dimension had been MASKING this blindness: as long
                     # as it was in the body, the guard saw geometry through
                     # it and never asked about the second helper. Our own
                     # named form — an instrument covering PART of the
                     # range — turned against itself here.
                     "path_points_witness(",
                     "_network_geometry_post(", "emit_xyz_to_view2d_cs(")

#: Properties Revit computes from the model itself, so an emitter cannot
#: satisfy them merely by having written a parameter.
#:
#: A NAKED ``Origin`` WAS REMOVED ON 2026-08-09, AND THIS IS NOT A
#: RELAXATION BUT A FIX. It was rescuing exactly two emitters, and in BOTH
#: it coincided with ``__vw_{s}.Origin`` — the VIEW's origin, that is, the
#: input to the computation, not a read of the built element. Exactly the
#: same defect the loads wave found on 2026-08-09 in ``create_line_load``
#: (``Plane.CreateByNormalAndOrigin`` contains the substring "Origin") — and
#: this time it was hiding not a false miss but a FALSE PASS:
#: ``_emit_angular_dimension`` and ``_emit_tag`` were being declared
#: witnessed by a word appearing in the CREATION ARGUMENT.
#:
#: Both are genuinely witnessed, and their real witnesses stand here instead
#: of the coincidence:
#:   ``.Value ?? double.NaN`` — ``Dimension.Value``/``AngularDimension.Value``:
#:       the distance (angle) between REFERENCES, which Revit computes from
#:       the model itself, and it is signed ``(geometry)``. The form is
#:       deliberately narrow: a bare ``.Value`` would coincide with the
#:       ``ElementId.Value`` idiom of 2024-26 and would again hand out
#:       "witnessed" by coincidence;
#:   ``.TagHeadPosition``  — the position of the BUILT tag's head.
#:
#: 🔴 TWO SURFACE READS (2026-08-21). `emit_surface` builds its witnesses not
#: through a helper but as five `WitnessCheck` right in the body (6
#: `__post.Add`), and it reads the built solid via `__sol.Faces.Size`,
#: `__sol.Faces`, `Face.GetSurface()`. Not one of these idioms was on the
#: list, so the one op with a free-form NURBS surface was recorded as
#: "naked." The form is narrow on purpose, like `.Value ?? double.NaN`
#: above: `.Faces` are the faces of a SOLID read back from the document,
#: and there is nothing for it to coincide with.
_GEOMETRY_READS = (
    ".Faces", ".GetSurface(",
    "Location", "get_BoundingBox", "GetEndPoint", ".Point",
    "FacingOrientation", "HandOrientation", ".Elevation",
    ".Value ?? double.NaN", ".TagHeadPosition",
    # wave/analysis (08.09). THE INSTRUMENT WAS WIDENED, NOT WEAKENED, and
    # the reason is a false MISS it found itself: `create_line_load` was
    # passing the check only because the string
    # `Plane.CreateByNormalAndOrigin` contains "Origin" — that is, by a
    # substring coincidence in the CREATION ARGUMENT, not by its real
    # witness. Its real one is `StartPoint`/`EndPoint`; the evacuation
    # path's is `PathStart`/`PathEnd`/`GetCurves`; the area load's is
    # `GetLoops`. All of them are exactly the kind the list exists for (the
    # module's header: "location, curve endpoint, bounding box, elevation"):
    # Revit returns them from the BUILT element, and the emitter cannot
    # satisfy them simply by writing a parameter.
    ".StartPoint", ".EndPoint", ".PathStart", ".PathEnd",
    "GetCurves", "GetLoops",
    # wave/site (2026-08-09). Three reads of THE SAME CLASS as everything
    # above: the element itself hands back its geometry, and the emitter
    # cannot satisfy them by having written a parameter.
    #   GetBoundary()        — the boundary of the pad/subregion, that is,
    #                          the sketch that Revit SAVED (not the one we
    #                          passed in: the comparison happens after
    #                          Curve.Tessellate unrolls it);
    #   GetPoints()          — the points of the built toposurface;
    #   SlabShapeVertices    — the vertices of a toposolid's shape (it has no
    #                          GetPoints() on any version — measured).
    # The list is extended ONLY this way: by a new INDEPENDENT read, not by
    # the name of a parameter the emitter writes itself.
    "GetBoundary", "GetPoints", "SlabShapeVertices",
    # wave/sweep (2026-08-09). A READ OF EXACTLY THE SAME CLASS, and this is
    # worth stating precisely, because the name looks like a parameter
    # accessor and is not one: `HostedSweep.get_ReferenceCurve(Reference)` is
    # an indexed property of a BUILT hosted sweep, returning the curve it
    # LAID along the named edge reference. The emitter cannot satisfy it by
    # anything: it passed a reference, and the element returned the curve,
    # and `null` means Revit did not take the reference — that is, the
    # profile is tracing THE WRONG perimeter from the one requested. Exactly
    # what the list exists for.
    "get_ReferenceCurve",
    # wave/datums (2026-08-09): a BODY, computed by Revit. The list above
    # only knew points and a world-axis bounding box, while an extruded roof
    # is measured ALONG THE NORMAL of its own work plane — the normal is
    # horizontal but arbitrary, and an axis-aligned bbox would mix the
    # extrusion's travel with the profile's spread. Traversing the body
    # (`get_Geometry` -> Solid -> Edge -> `Tessellate`) is the strongest form
    # of independent reading available here: the emitter cannot satisfy it
    # by writing a parameter. An instrument that knows part of the range is
    # more dangerous than an absent one — hence the list is EXTENDED, not
    # bypassed with an exception.
    "get_Geometry", "Tessellate",
    # wave/detail (2026-08-09). THE INSTRUMENT WAS WIDENED AGAIN OVER A FALSE
    # PASS IT FOUND ITSELF, and the reason is the same as with the loads
    # wave: the tag and the text passed this check ONLY because of the
    # substring "Origin" in `__vw_<s>.Origin` — that is, by the VIEW's own
    # origin, which the emitter takes itself, not by anything read from the
    # built element. The coincidence surfaced when the inverse formula moved
    # into docspace and "Origin" disappeared from the tag emitter's text: the
    # detector declared `_emit_tag` naked, even though its witness
    # (`TagHeadPosition`) had not changed by a single byte. The real
    # independent reads of this family are named here:
    #   TagHeadPosition — where Revit PLACED the tag's head;
    #   .Coord          — where Revit PLACED the text note;
    #   GetBoundaries   — the boundary of the built fill region.
    "TagHeadPosition", ".Coord", "GetBoundaries",
)

#: Ops that create no geometry at all. Each entry is a claim that has to stay
#: true, not a way to silence the check.
_NO_GEOMETRY = {
    "_emit_create_type": "creates a TYPE; no instance exists to measure",
    # ── THREE CATALOG AND VIEW EMITTERS (2026-08-24) ──────────────────────
    #
    # `_emit_create_type` in its pure form, and the claim is the same: not
    # one of the three sets a single coordinate in the model. A wall type
    # describes the LAYER STACK — layer thicknesses, re-read by the witness
    # by name (`layers`, `total_width`) — but no instance ever appears whose
    # shape could be measured; a floor plan is a way of LOOKING; a material
    # arrives as a library element.
    #
    # THE CLAIM THAT MUST STAY TRUE (the same contract as its neighbors on
    # the list): the day any of the three starts naming a coordinate — an
    # insertion point, an outline, an offset — the entry becomes a lie and
    # must go, because from then on a wrong shape could commit silently.
    "_emit_create_wall_type": "creates a host-object TYPE (wall/floor/roof/"
                              "ceiling); its layer pie is re-read per layer, "
                              "but no instance exists to measure",
    "_emit_floor_plan": "creates a VIEW — a way of looking at the building; "
                        "it places no geometry at all",
    "_emit_transfer_material": "copies a Material from a neighbouring open "
                               "document; a material is a PROPERTY of bodies, "
                               "not a body — the op carries no coordinate",
    "_emit_load_family": "loads a family file; places nothing",
    "_emit_setparam": "writes a parameter on an element it did not create",
    "_emit_delete": "removes elements; the absence is checked by count",
    # GEOMETRY JOIN (2026-08-18) — `set_param` in its pure form.
    #
    # The op's whole input: TWO ELEMENT SELECTORS. No point, no curve, no
    # outline, no offset. The op cannot put anything in the wrong place
    # because it names no "place" at all: it merely declares that two
    # already-standing bodies share their volume. Both shapes were
    # determined by the ops that built them, and each has its own geometric
    # witness.
    #
    # THE CLAIM THAT MUST STAY TRUE (the same contract as its neighbors on
    # the list): the day the op gains even one coordinate — a cut order, an
    # offset, a face choice — this entry becomes a lie and must go, because
    # from then on a wrong shape could commit silently. Today, though, its
    # witness is exact and tolerance-free: `AreElementsJoined` re-read from
    # the document, boolean against boolean.
    "_emit_join_elements": "declares that two EXISTING solids share volume; "
                           "the op carries no coordinate at all — its witness "
                           "is exact and tolerance-free (AreElementsJoined "
                           "re-read from the document)",
    # ``_emit_pipe_system`` left this list on 2026-08-09. Its entry claimed the
    # op "declares a system" and creates no geometry of its own — but the op
    # calls ``Pipe.Create`` once per authored edge, so it builds every metre of
    # pipe in the network. The claim was false, and it needed no exemption
    # anyway: the same ``_network_geometry_post`` the route ops use reads those
    # segments' endpoints back. An exemption resting on a false claim is worse
    # than no exemption, because it survives review by sounding like one.
    # set_curtain_panel carries no coordinate at all: host + cell address +
    # type. The cell's shape is cut by the host's curtain grid, which this op
    # neither creates nor moves — exactly set_param's position, one level up
    # (a TYPE instead of a value). The claim that has to stay true: the day
    # this op gains a coordinate (a grid line, an offset), this entry is false
    # and must go, because then a wrong shape could commit silently.
    "_emit_set_curtain_panel": "assigns a TYPE to an existing grid cell; the "
                               "op carries no coordinate and cuts no grid",
    # wave/datums (2026-08-09). A multi-story stair DOES genuinely produce
    # geometry — runs at every connected level. But the op's entire input is
    # ONE element reference and A SET of level references: the author names
    # not one coordinate, and Revit copies the runs' shape from the
    # original. There is NOTHING to compare the resulting geometry against —
    # any comparison would reduce to "level equals level," that is, to a
    # check that cannot fail, and such a check is worse than none.
    # What is checked instead: EXACT equality of the level sets, re-read
    # from the document, with no tolerance.
    # THE CLAIM THAT MUST STAY TRUE: the day the op gains even one
    # coordinate, this entry becomes a lie and must go.
    "emit_multistory_stairs": "replicates an EXISTING stair across "
                                     "named levels; the op carries no "
                                     "coordinate at all, so no authored "
                                     "number exists to compare geometry "
                                     "against",
    # CLASH-починка (28.07): change_type is set_param's own exemption one
    # level up — a TYPE change on an element it did not create, no
    # coordinate anywhere in the op. Its witness (GetTypeId() re-read) is
    # semantic/identity, not geometric, on purpose: Element.ChangeTypeId
    # moves nothing (the rare new-element case is still the SAME location,
    # per RevitAPI.xml — a curtain-panel<->wall type swap, not a move). The
    # claim that has to stay true: the day this op gains a coordinate
    # (e.g. a re-host), this entry is false and must go.
    "_emit_change_type": "changes an element's TYPE; no coordinate — the "
                         "rare new-element case (RevitAPI.xml) still commits "
                         "the SAME location, so nothing here moves",
    # wave/sweep (2026-08-09). THIS IS THE ONE EXEMPTION IN THIS DICTIONARY
    # RESTING ON A DOCUMENTED API FACT RATHER THAN ON OUR OWN OP'S DESIGN,
    # and it is worth reading in full before "fixing."
    #
    # A wall sweep does have a body. The OPERATION has no coordinates, and
    # none can be added: the RevitAPI.xml of all SIX versions states, word
    # for word, of `WallSweep.Create`: "The wall sweep's profile and type are
    # taken from the wall sweep type properties. The values set in the
    # WallSweepInfo are ignored." That is, the distance and offset are set
    # by the TYPE, preloaded into the document, not by the call; the
    # operation has no field for them at all, and there is nothing to read
    # back. The position is exactly the same as `_emit_set_curtain_panel`'s:
    # a host + a type, and not one coordinate.
    #
    # WHAT IS NOT CLAIMED HERE: that the sweep's shape does not matter. What
    # is claimed is that it is chosen by the TYPE'S AUTHOR, not by this
    # program, and that presenting a witness over someone else's choice
    # would mean presenting a check that cannot fail — by this house's law,
    # worse than none.
    #
    # THE CLAIM THAT MUST STAY TRUE: the day the operation gains even one
    # coordinate (a distance, an offset from the wall, an angle), this line
    # becomes false and must go — because from that day a wrong shape could
    # commit silently.
    "emit_wall_sweep": "hangs a profile whose position is taken ENTIRELY "
                        "from the pre-loaded type (RevitAPI.xml, all six "
                        "versions); the op carries no coordinate at all",
}


def _all_function_bodies() -> dict[str, str]:
    """Every top-level function in the IR package, keyed by bare name.

    Emitters delegate freely -- doors and windows to the hosted emitter, beams
    and foundations into struct_emit -- so an analysis that stops at
    authoring.py reports four false defects. It did, before this followed them.
    """
    out: dict[str, str] = {}
    for path in sorted(_IR_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        starts = [(m.group(1), m.start())
                  for m in re.finditer(r"^def (\w+)\(", src, re.M)]
        for i, (name, start) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else len(src)
            out.setdefault(name, src[start:end])
    return out


def _emitters() -> dict[str, str]:
    r"""Op emitters are ASKED OF THE TABLE-OBJECT, not read out of text.

    ``_emit_`` is unreliable as a marker: compiler.py has ``_emit_collector``
    and ``_emit_row``, which build query C# and place nothing. The authority
    is ``authoring._EMITTERS``.

    🔴 THIS USED TO READ THE SOURCE: ``read_text(authoring.py)``, then
    ``index("_EMITTERS = {")``, a bracket walk, and the regex
    ``:\s*(_emit_\w+)``. The instrument rested on THREE assumptions about
    SPELLING, not one of them a property of the subject: that the table is
    declared as a dict literal, that the declaration begins on exactly this
    line, and that every value is a bare function name. Any one of the three
    stops being true the moment the table starts being ASSEMBLED (from
    spoke emitters, from a registry) — which is exactly what is happening
    now: the bodies of 32 of 72 emitters have already moved into the
    ``*_emit.py`` satellites. The instrument would not have gone red:
    ``assert names`` only catches emptiness, and a partial regex match would
    have given FEWER names and FEWER found defects — that is, a green bought
    with blindness.

    Bodies are still taken from the SOURCE, and this is not inconsistency:
    the subject of the analysis below is the emitter's own text (which
    calls it makes), and there is no object one could ask this of instead.
    TEXT is taken from the text; COMPOSITION is taken from the authority.
    """
    from kir import authoring  # noqa: PLC0415 — an authority, not text
    names = {f.__name__ for f in authoring._EMITTERS.values()
             if getattr(f, "__name__", None)}
    assert names, "таблица эмиттеров пуста — спрашивать не у кого"
    bodies = _all_function_bodies()
    return {n: bodies[n] for n in sorted(names) if n in bodies}


#: ``return other(...)`` or ``return mod.other(...)`` and nothing else of
#: substance: the obligation lives in the callee.
_DELEGATION = re.compile(r"return\s+(?:\w+\.)?(\w+)\(", re.M)


#: A Python comment line and a triple-quoted docstring are PROSE, not code.
_PROSE = re.compile(r'^\s*#.*$|"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\'', re.M)


def _code_only(body: str) -> str:
    """A function body with no comments and no docstrings.

    THE REASON THIS APPEARED ON 2026-08-09 MATTERS MORE THAN THE FUNCTION
    ITSELF. ``_emit_dimension`` — 361 lines, the most heavily parsed op that
    day — was passing the geometric-honesty check ON A SINGLE COINCIDENCE,
    and the coincidence was with the word ``Origin`` inside English PROSE:

        # position of Origin ALONG the line — is an emergent property of where

    That is not even emitted C#. The instrument answered "witnessed" from a
    comment, and the answer would have been believed, because a named
    instrument is more convincing than a human. Exactly what the canon warns
    against: an instrument covering PART of its range is more dangerous than
    an absent one.

    The fix has one direction, deliberately: stripping prose can make an
    emitter appear NAKED (a false alarm — cheap), but it cannot make a naked
    one appear witnessed.
    """
    return _PROSE.sub("", body)


def _has_geometric_witness(body: str, depth: int = 2) -> bool:
    code = _code_only(body)
    if (any(h in code for h in _GEOMETRY_HELPERS)
            or any(t in code for t in _GEOMETRY_READS)):
        return True
    if depth <= 0:
        return False
    bodies = _all_function_bodies()
    return any(_has_geometric_witness(bodies[target], depth - 1)
               for target in _DELEGATION.findall(code)
               if target in bodies)


#: Known debt, frozen by name.
#:
#: ``_emit_route_pipe_system`` and ``_emit_route_duct_system`` LEFT this list on
#: 2026-08-09, and the correction is worth more than the removal. Their entry
#: said the two ops "verify none of it geometrically: a pipe laid along the
#: wrong path satisfies every postcondition they have". That was untrue when it
#: was written and stayed untrue for thirteen days: both ops have re-read every
#: created segment's ``LocationCurve`` endpoints against the authored node pair
#: since 2026-07-27, and the corpus proves the witness bites — on live Revit
#: 2026 at 2026-07-30T13:49:56 ``route_duct_system`` rolled back on
#: ``R1: segment 0/1/2 endpoints (geometry)``, and the same op ran clean at
#: 14:38:08. What was missing was not the witness but the detector's ability to
#: see it (see ``_GEOMETRY_HELPERS``).
#:
#: The entry that was genuinely open on those two — never named here — was the
#: reference LEVEL: a required authored parameter that both emitters pass
#: straight into ``Pipe.Create``/``Duct.Create`` and neither read back, while
#: ``acceptance._LEVEL_FROM_PARAM`` already built its post-commit census on the
#: claim that it holds. Closed 2026-08-09 by the ``reference_level`` witness.
#:
#: A wall foundation DOES build a solid, so ``_NO_GEOMETRY`` would be a lie
#: here — this is debt, and it is named as such. What is missing is not the
#: code but the NUMBER: how far the footing projects past its wall and where
#: its underside sits have never been measured (zero WallFoundation instances
#: across every stored decompile, grep 2026-08-09), so any bbox comparison
#: would be a bound authored by reasoning — the defect class this repository
#: names in its own canon. Its topology witness is exact and tolerance-free
#: (WallId equality re-read from the document), which is why the op is safe to
#: ship naked-of-geometry and not safe to ship with an invented tolerance.
#: One live run closes this; another hour of reasoning cannot.
#:
#: SINCE 2026-08-09 THIS IS A JOURNAL, NOT A SET OF NAMES (``record_ratchet``),
#: and the reason is the story two lines above. A name on a debt list READS AS
#: A MEASUREMENT: two audits in a row read ``route_pipe_system`` exactly that
#: way, while a live witness had stood there since 07.27. A set of names can
#: say neither when a decision was made nor who is due to answer by which
#: day — and without that, an honest entry lives only as long as it is
#: remembered.
#: 🔴 KEYS RENAMED 2026-09-02, AND THIS IS NOT A RELAXATION BUT THE RETURN OF
#: THE SUBJECT. Debt and exemption entries had been keyed on WRAPPER NAMES
#: from `authoring.py` (`_emit_wall_sweep`, `_emit_wall_foundation_struct`,
#: `_emit_multistory_stairs_datum`). Wrappers are pure delegation into a
#: satellite (`return sweep_emit.emit_wall_sweep(...)`), and since this wave
#: the `_EMITTERS` table is ASSEMBLED from spokes and carries the satellites'
#: bodies directly. So a key written against a wrapper stopped naming
#: anyone: the rule was looking at `emit_wall_sweep`, while the debt was
#: recorded against `_emit_wall_sweep`, and there was NOT ONE match. The
#: entries' reasons are untouched, to the word — they are about the OP, and
#: remain true; only the name this op is called by has changed.
_KNOWN_NAKED = Ledger(
    "witness_geometry._KNOWN_NAKED",
    {
        "emit_wall_foundation": Entry(
            CLOSE_BY, "2026-08-09", "2026-09-08",
            "лента строит настоящее тело, поэтому _NO_GEOMETRY здесь был бы "
            "ложью: не хватает не кода, а ЧИСЛА — свес подошвы за стену и "
            "отметка низа не замерены ни разу (ноль экземпляров WallFoundation "
            "во всех сохранённых разборах, grep 09.08), а допуск, выведенный "
            "рассуждением, — тот самый класс дефекта, которым этот дом уже "
            "заворачивал верные постройки. Топология точна и без допуска "
            "(WallId перечитан из документа). Закрывает ОДИН живой прогон"),
    },
    instrument=(
        "_has_geometric_witness() над телом эмиттера из таблицы _EMITTERS: "
        "строка держится, пока имя стоит в naked; прибор чинили дважды "
        "(09.08 — делегирование распаковкой кортежа и совпадение по прозе)"))


class EveryGeometryOpIsWitnessedGeometrically(unittest.TestCase):
    def test_no_new_emitter_guards_only_what_it_set(self):
        naked = {name for name, body in _emitters().items()
                 if name not in _NO_GEOMETRY
                 and not _has_geometric_witness(body)}

        self.assertEqual(
            sorted(naked - set(_KNOWN_NAKED)), [],
            "these emitters create geometry and no postcondition can see it, "
            "so a wrong shape commits silently: "
            + ", ".join(sorted(naked - set(_KNOWN_NAKED))))

    def test_the_debt_list_shrinks_and_never_goes_stale(self):
        # A ratchet: once an emitter earns a geometric witness its name has to
        # leave this list, or the list stops describing anything real.
        naked = {name for name, body in _emitters().items()
                 if name not in _NO_GEOMETRY
                 and not _has_geometric_witness(body)}

        self.assertEqual(
            sorted(set(_KNOWN_NAKED) - naked), [],
            "these are listed as debt but are witnessed now — drop them: "
            + ", ".join(sorted(set(_KNOWN_NAKED) - naked)))

    def test_the_allowlist_names_only_real_emitters(self):
        # An entry left behind after a rename would silently exempt nothing —
        # or worse, keep exempting an op that has since grown geometry.
        missing = sorted(set(_NO_GEOMETRY) - set(_emitters()))

        self.assertEqual(missing, [], f"allowlist names no such emitter: {missing}")

    def test_every_exemption_carries_a_reason(self):
        for name, reason in _NO_GEOMETRY.items():
            with self.subTest(emitter=name):
                self.assertGreater(
                    len(reason.split()), 3,
                    f"{name} is exempt without saying why")

    def test_the_detector_recognises_a_naked_emitter(self):
        # Guard the guard: if the token list stopped matching, the check above
        # would pass vacuously for every op forever.
        self.assertFalse(_has_geometric_witness(
            'checks = [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]'))

    def test_a_word_in_prose_is_not_a_witness(self):
        """A REFUTING TEST FOR A REAL DEFECT, found 2026-08-09.

        A verbatim line from ``_emit_dimension`` — an English comment
        containing the word ``Origin``. Before the fix, the instrument used
        it to declare the whole emitter geometrically witnessed. The body
        deliberately ALSO contains the same op's real witness: the test must
        prove that it is specifically the PROSE that was removed, not that
        ``Origin`` stopped existing.
        """
        prose_only = (
            'def _emit_x(op):\n'
            '    """Docstring: get_BoundingBox is discussed, never called."""\n'
            '    # position of Origin ALONG the line — is an emergent property\n'
            '    return [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]\n')
        self.assertFalse(
            _has_geometric_witness(prose_only),
            "слово в комментарии засчитано как свидетель — прибор снова меряет "
            "часть своего диапазона и отвечает «одет» тому, кто гол")

        real = prose_only.replace(
            'verdict_cs="__el.get_Parameter(X)"',
            'verdict_cs="__got = __el.Value ?? double.NaN;"')
        self.assertTrue(
            _has_geometric_witness(real),
            "вычёркивание прозы съело и настоящий свидетель — починка не "
            "имеет права двигать вердикт на исправном коде")

    def test_the_view_origin_is_an_input_and_never_a_witness(self):
        """A second kind of the same defect: a coincidence in the CREATION
        ARGUMENT.

        ``__vw_.Origin`` is the VIEW's origin, an input to the computation.
        The emitter satisfies it merely by having read it itself, so by the
        module header's own definition it cannot be a witness. The same form
        as ``Plane.CreateByNormalAndOrigin``, found by the loads wave.
        """
        self.assertFalse(_has_geometric_witness(
            'code = f"XYZ __aO_{s} = __vw_{s}.Origin;\\n"\n'
            'checks = [WitnessCheck(verdict_cs="__el.get_Parameter(X)")]'))

    def test_every_debt_entry_carries_a_decision_and_a_deadline(self):
        """A ratchet of form. Debt with no day by which someone must answer
        is not bookkeeping but an archive: this is exactly how
        ``route_pipe_system`` stood here for thirteen days with a live
        witness."""
        from kir import record_ratchet as rr
        self.assertEqual(
            rr.check_form(_KNOWN_NAKED.entries,
                          verdicts=_KNOWN_NAKED.verdicts,
                          standing=_KNOWN_NAKED.standing), [])
        overdue, stale = rr.check_expiry(_KNOWN_NAKED.entries)
        self.assertEqual(
            [n for n, _ in overdue], [],
            "срок вышел: перемерить прибором и закрыть, удалить либо написать "
            "решение заново — но не подвинуть дату")
        self.assertEqual(
            [n for n, _ in stale], [],
            "решение старше REVIEW_DAYS — подтвердить или пересмотреть")

    def test_the_detector_follows_one_delegation(self):
        # _emit_door is three lines long and hands everything to the hosted
        # emitter; treating it as naked was the detector's own first bug.
        self.assertTrue(_has_geometric_witness(
            "def _emit_door(op, ver, stamp):\n"
            "    return _emit_hosted(op, ver, stamp, 'door')\n"))

    def test_the_detector_accepts_each_geometric_form(self):
        for token in _GEOMETRY_HELPERS + _GEOMETRY_READS:
            with self.subTest(token=token):
                self.assertTrue(_has_geometric_witness(f"checks = [{token}]"))


if __name__ == "__main__":
    unittest.main()
