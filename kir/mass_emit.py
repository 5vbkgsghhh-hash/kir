"""mass_emit — emission of `create_face_wall` (a file paired with ops_mass.py).

`authoring.py` gets from here only an import and one line in `_EMITTERS` —
the same minimal seam the waves for the site, profiles, and solids
connected through.

WHY THERE IS NO OWN FACE SELECTION HERE. The face is chosen by
`faceref.resolve_cs` — LITERALLY the same code as the named-faces wave
uses: the same two native Revit tests (cross product via
`IsZeroLength`, the sign of `DotProduct`), the same cardinality law (one —
take it, zero — refusal, two or more — refusal WITH A NUMBER), and the
same refusal texts. Writing a second selection here would mean
introducing a second mechanism alongside the existing one and ending up
with two places where the law could be weakened independently.

A SECOND SELECTOR STAGE IS NOT INTRODUCED HERE, AND THAT IS A DIFFERENT
MATTER. The `KUKAI_IR_FACE_REF` flag gates the SELECTOR FORM
`{"by": "face", ...}` — an extension of the frozen reference dialect that
the schema and every one of its consumers see. `create_face_wall`
introduces no new selector at all: it has an ordinary vector parameter,
`face_normal`, exactly like `side` on `create_slab_edge`, and what stays
shared are the TRAVERSAL HELPERS. So the operation works with the flag
off, and that is not bypassing the gate, but the difference between "a
new kind of reference" and "reused geometry traversal."

WHY TWO REVIT PRE-FLIGHTS, AND NOT OWN CHECKS. `FaceWall` is the only
factory in this chapter that brought ITS OWN validators:
`IsWallTypeValidForFaceWall` and `IsValidFaceReferenceForFaceWall`, both
6/6. Each is asked BEFORE the effect, so "Revit will not take this type"
and "Revit will not take this face" arrive as a TYPED REFUSAL with a
named next move, rather than as an exception the receipt would record as
`internal`. A check of our own in their place would be a guess at rules
Autodesk has nowhere listed in full: the documentation names three
conditions for the face («face of a massing instance», «planar», «normal
must not be vertical or horizontal»), and for the type, none at all.

THE COORDINATE SYSTEM IS THE ONE PLACE WHERE THIS WAVE COULD HAVE LIED
QUIETLY. The host is a `FamilyInstance`, and the face of its solid lives
in SYMBOLIC coordinates (`GeometryInstance`); the built wall is an
ordinary project element, its faces in MODEL coordinates. So the witness
NEVER reads coordinates via a reference to the mass's face: the normal is
checked against the REQUESTED vector (and its being aligned with the
face's model-space normal was already certified by REVIT ITSELF during
selection — by the same `IsZeroLength`), the position against the HOST's
bounding box, which Revit hands over in model coordinates. Not one
transform of ours between the systems.
"""
from __future__ import annotations

from kir import faceref
from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _stamp_block, _stamp_readback,
)
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import (
    Diagnostic, EMIT_UNSUPPORTED_ENUM, KirRefusal, PARSE_MISSING_FIELD)
from kir.ops_mass import FACE_WALL_LOCATION_LINES

#: `location_line` outside the closed set. A belt over the braces, exactly
#: as with the profiles wave (`sweep_emit`, the same shared code):
#: `enum`-choices already catches this at `authoring.validate()`, and here
#: stands defense in depth — whoever extends the dictionary without adding
#: the branch will fail LOUDLY, rather than silently build the wrong
#: thing.

#: A human-readable name of the operation, for refusal texts. A human
#: reads the refusal, and «FaceWall.Create returned null» sends them off to
#: read Autodesk's documentation instead of their own program.
_HUMAN = "стена по грани массы"


def _host_resolve_cs(op: dict, s: str, ver: str, oid: str,
                     isolation: str) -> str:
    """Resolution of the host into `__hsrc_<s>` (the declaration is in `decl`).

    There is DELIBERATELY NO cast to a class here, and this is not an
    omission. The validity of the host is decided not by our `as`, but by
    `IsValidFaceReferenceForFaceWall`, which is asked below and knows the
    whole rule («face of a massing instance»). Our own `as FamilyInstance`
    would reject, for instance, an in-place mass, which is not always a
    `FamilyInstance` — that is, it would forbid what Revit allows, and
    explain it in terms of a class rather than of a mass.
    """
    sel = op["host"]
    if sel.get("by") == "ref":
        return f"__hsrc_{s} = __el_{_safe(sel['value'])};\n"
    return (f"__hsrc_{s} = doc.GetElement({_eid(sel['value'], ver, oid)});\n"
            f"if (__hsrc_{s} == null) {{ "
            + refuse_stmt(oid, _cs(
                f"{_HUMAN}: носитель не найден (модель изменилась после "
                f"grounding)"), isolation) + " }\n")


def _type_resolve_cs(op: dict, s: str, oid: str, ver: str,
                     isolation: str) -> str:
    """Resolution of the wall type into `__ty_<s>` plus REVIT'S OWN
    PRE-FLIGHT.

    There is no `doc_default` branch here, for the same reason as with the
    edge profile: a wall type substituted on the author's behalf is
    indistinguishable from success from the outside. An omitted `type`
    resolves `ground` by the general rule "the sole one in the pool, or
    else a typed question with candidates," and the author WILL SEE that
    question.
    """
    sel = op.get("type")
    g = _gid(op, "type") if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=(f"{_HUMAN}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    return (
        f"__ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) as WallType;\n"
        f"if (__ty_{s} == null) {{ "
        + refuse_stmt(oid, _cs(
            f"{_HUMAN}: тип не найден или он не WallType (модель изменилась "
            f"после grounding)"), isolation) + " }\n"
        # REVIT'S PRE-FLIGHT. Autodesk gives no full list of admissible
        # types anywhere, so we ask Revit itself, rather than guess the
        # rule.
        f"bool __tyok_{s} = false;\n"
        f"try {{ __tyok_{s} = FaceWall.IsWallTypeValidForFaceWall("
        f"doc, __ty_{s}.Id); }} catch {{ }}\n"
        f"if (!__tyok_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: Revit не принимает этот тип стены по грани (")
            + f" + __ty_{s}.Name + " + _cs(
                "). Правило целиком Autodesk нигде не перечислил, поэтому "
                "спрошен сам Revit (IsWallTypeValidForFaceWall) — и он "
                "ответил «нет» ДО эффекта, а не исключением после. "
                "СЛЕДУЮЩИЙ ХОД: назови другой тип стены; query_types kind="
                "wall_types покажет пул"),
            isolation) + " }\n")


def emit_face_wall(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A wall on a SLOPED face of a conceptual mass, Revit 2021-2026.

    `FaceWall.Create(Document, ElementId, WallLocationLine, Reference)` —
    6/6, there is NO version branch: the signature, both pre-flights,
    `HostObjectUtils`, `WallType.Width`, and `VertexTolerance` are all
    assembled the same way on all six.

    WHY THIS OPERATION EXISTS AT ALL, WHEN THE WHOLE CHAPTER IS REFUSED: it
    alone has RevitAPI.xml naming as the throw condition *«document is not
    a project document»* — the exact inverse of the refusal for the six
    mass forms, where the accessor `Document.FamilyCreate` itself throws
    («thrown when the current document is project document»). Both phrases
    were reread in EACH of the six RevitAPI.xml files, not just the two
    extremes. Analysis of the whole chapter is in the header of
    `ops_mass.py`.
    """
    oid = op["id"]
    s = _safe(oid)
    ll = op.get("location_line")
    if ll not in FACE_WALL_LOCATION_LINES:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="location_line",
            got=ll, candidates=sorted(FACE_WALL_LOCATION_LINES),
            message_ru=(f"create_face_wall: положение {ll!r} не поддержано — "
                        f"имена задаёт перечисление Revit WallLocationLine"))])
    ll_cs = FACE_WALL_LOCATION_LINES[ll]
    normal = op["face_normal"]

    # The face selector IS ASSEMBLED HERE from the vector parameter and
    # handed to `faceref.resolve_cs` in its own form. This way the
    # selection law stays in one file, and this operation does not grow a
    # second dialect.
    face_sel = {"by": faceref.BY_FACE, "of": op["host"],
                "predicate": {"normal": [float(x) for x in normal]}}

    # EVERYTHING THE WITNESS READS IS DECLARED HERE: with
    # `isolation="per_op"` create and post land in DIFFERENT scopes, and a
    # name declared inside create is invisible to the witness (CS0103 —
    # the very seam on which the guardrails wave got six gate refusals).
    # ONE DECLARATION PER LINE: the scope contract parses declarations line
    # by line.
    decl = (f"FaceWall __el_{s} = null;\n"
            f"WallType __ty_{s} = null;\n"
            f"Element __hsrc_{s} = null;\n"
            f"Reference __fr_{s} = null;\n"
            f"XYZ __want_{s} = null;\n"
            f"double __farea_{s} = 0.0;\n"
            f"double __warea_{s} = 0.0;\n"
            f"double __wwid_{s} = 0.0;\n"
            f"double __wtol_{s} = 0.0;\n"
            f"int __wfn_{s} = 0;\n"
            f"bool __inbb_{s} = false;\n"
            + faceref.walk_helpers_cs(s))

    create = (
        f"// create_face_wall {cs_line_comment_fragment(oid)}\n"
        f"doc.Regenerate();\n"
        + _host_resolve_cs(op, s, ver, oid, isolation)
        + _type_resolve_cs(op, s, oid, ver, isolation)
        # FACE SELECTION — BY FOREIGN CODE, BY OUR OWN LAW (see the
        # module header).
        + faceref.resolve_cs(
            face_sel, s=s, i=0, elem_var=f"__hsrc_{s}", out_var=f"__fr_{s}",
            oid=oid, label=f"{_HUMAN}: face_normal", isolation=isolation,
            view_var=None, refuse_stmt=refuse_stmt, cs_literal=_cs,
            # THE NEXT MOVE — IN THIS OPERATION'S OWN WORDS. `faceref`'s
            # own text refers to `predicate.side`/`predicate.normal`, that
            # is, to the second selector stage's dictionary; `create_face_wall`
            # has no such fields at all, and a refusal sending the author
            # to fix a field that does not exist costs more than having no
            # refusal.
            normal_field="face_normal",
            next_move_zero=(
                "СЛЕДУЮЩИЙ ХОД: проверь face_normal — это внешняя нормаль "
                "грани в координатах МОДЕЛИ. И помни правило самого Revit: "
                "стену по грани он строит ТОЛЬКО по наклонной грани массы, "
                "то есть у вертикальной ([0,0,±1]) и горизонтальной "
                "(z == 0) нормали кандидата не будет никогда"),
            next_move_many=(
                "СЛЕДУЮЩИЙ ХОД: у этой массы несколько РАЗНЫХ граней с одной "
                "и той же нормалью (параллельные скаты), и выбрать из них за "
                "автора нельзя. Это НАЗВАННЫЙ предел операции: сегодня одна "
                "нормаль — один скат. Строй стену по массе, у которой скат с "
                "таким направлением один")) + "\n"
        # THE AREA OF THE NAMED FACE — INTO THE RECEIPT ONLY. Area is
        # invariant under a rigid transform of the instance, so reading it
        # via this reference is LEGITIMATE; reading coordinates via it
        # would not be allowed (a symbolic system) — and we read none
        # anywhere.
        f"PlanarFace __mf_{s} = null;\n"
        f"try {{ __mf_{s} = __hsrc_{s}.GetGeometryObjectFromReference("
        f"__fr_{s}) as PlanarFace; }} catch {{ }}\n"
        f"if (__mf_{s} != null) __farea_{s} = __mf_{s}.Area;\n"
        # REVIT'S PRE-FLIGHT ON THE FACE. Autodesk names three conditions
        # verbatim, and all three are asked in ONE call — a check of our
        # own in its place would be rewriting someone else's rule from
        # memory.
        f"bool __frok_{s} = false;\n"
        f"try {{ __frok_{s} = FaceWall.IsValidFaceReferenceForFaceWall("
        f"doc, __fr_{s}); }} catch {{ }}\n"
        f"if (!__frok_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: Revit не принимает эту грань как основание для "
                f"стены по грани. Его собственное правило "
                f"(IsValidFaceReferenceForFaceWall, спрошен ДО эффекта): "
                f"грань обязана принадлежать МАССЕ, быть ПЛОСКОЙ, и её "
                f"нормаль не должна быть ни вертикальной, ни горизонтальной "
                f"— то есть стену по грани строят по НАКЛОННОЙ поверхности. "
                f"СЛЕДУЮЩИЙ ХОД: для вертикальной грани строй create_wall, "
                f"для горизонтальной — перекрытие или кровлю (пола и кровли "
                f"ПО ГРАНИ в API нет вовсе, замерено 6/6 CS1061)"),
            isolation) + " }\n"
        f"try {{ __el_{s} = FaceWall.Create(doc, __ty_{s}.Id, "
        f"WallLocationLine.{ll_cs}, __fr_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: FaceWall.Create отказал — ")
            + f" + __ex_{s}.Message", isolation) + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{_HUMAN}: создание вернуло null — Revit не принял эту "
                f"грань, хотя предполётная проверка её пропустила"),
            isolation) + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    checks: list[WitnessCheck] = [
        WitnessCheck(
            # THE TYPE OF THE BUILT ELEMENT, read back. Comparison via
            # `ToString()` — the only `ElementId` idiom that works on all
            # six: `.IntegerValue` is dead as of 2026, `.Value` does not
            # exist before 2024.
            obligation_key="face_wall_type",
            reader_cs=f"    ElementId __rt_{s} = __el_{s}.GetTypeId();\n",
            verdict_cs=(
                f"    if (__rt_{s} == null || __ty_{s} == null\n"
                f"        || __rt_{s}.ToString() != __ty_{s}.Id.ToString())\n"
                f"        __post.Add({_cs(oid + ': тип построенной стены по грани не равен запрошенному (topology)')});\n"),
            message="тип построенной стены по грани не равен запрошенному (topology)",
            style="guard"),
        WitnessCheck(
            # THE MAIN GEOMETRIC WITNESS, and it reads the BUILT wall, not
            # our call: it asks for the OUTER faces (`HostObjectUtils` —
            # the same names as `faceref` uses), and among them there must
            # be EXACTLY ONE aligned with the requested vector. Zero means
            # Revit attached the wall to the wrong place; more than one
            # means the built solid is not the prism it is taken for.
            #
            # NOT ONE TOLERANCE OF OUR OWN: parallelism is decided by the
            # native `CrossProduct(...).IsZeroLength()`, alignment by the
            # sign of `DotProduct`. The same two tests as in `faceref`, and
            # for the same reason.
            #
            # COMPARISON WITH THE REQUESTED VECTOR, RATHER THAN WITH THE
            # MASS FACE'S NORMAL — this is ONE AND THE SAME statement, and
            # REVIT ITSELF certified it: the face made it into the
            # candidates only because its MODEL-SPACE normal passed
            # exactly this equality test against the vector. Reading
            # coordinates via a reference to the instance's face would be
            # reading the symbolic system (see the module header).
            obligation_key="face_wall_normal",
            reader_cs=(
                f"    __want_{s} = new XYZ({float(normal[0])!r}, "
                f"{float(normal[1])!r}, {float(normal[2])!r});\n"
                f"    if (!__want_{s}.IsZeroLength()) __want_{s} = __want_{s}.Normalize();\n"
                f"    IList<Reference> __wsf_{s} = null;\n"
                f"    try {{ __wsf_{s} = HostObjectUtils.GetSideFaces("
                f"__el_{s}, ShellLayerType.Exterior); }} catch {{ }}\n"
                f"    BoundingBoxXYZ __hbb_{s} = null;\n"
                f"    try {{ __hbb_{s} = __hsrc_{s}.get_BoundingBox(null); }} catch {{ }}\n"
                f"    try {{ __wwid_{s} = __ty_{s}.Width; }} catch {{ }}\n"
                f"    try {{ __wtol_{s} = doc.Application.VertexTolerance; }} catch {{ }}\n"
                f"    double __grow_{s} = __wwid_{s} + __wtol_{s};\n"
                f"    if (__wsf_{s} != null)\n"
                f"        foreach (Reference __wr_{s} in __wsf_{s})\n"
                f"        {{\n"
                f"            PlanarFace __wp_{s} = null;\n"
                f"            try {{ __wp_{s} = __el_{s}.GetGeometryObjectFromReference("
                f"__wr_{s}) as PlanarFace; }} catch {{ }}\n"
                f"            if (__wp_{s} == null) continue;\n"
                f"            XYZ __wn_{s} = __wp_{s}.FaceNormal;\n"
                f"            if (__wn_{s}.IsZeroLength()) continue;\n"
                f"            __wn_{s} = __wn_{s}.Normalize();\n"
                f"            if (!__wn_{s}.CrossProduct(__want_{s}).IsZeroLength()) continue;\n"
                f"            if (__wn_{s}.DotProduct(__want_{s}) <= 0) continue;\n"
                f"            __wfn_{s}++;\n"
                f"            __warea_{s} = __wp_{s}.Area;\n"
                f"            XYZ __wo_{s} = __wp_{s}.Origin;\n"
                f"            if (__hbb_{s} != null && __wo_{s} != null\n"
                f"                && __wo_{s}.X >= __hbb_{s}.Min.X - __grow_{s}\n"
                f"                && __wo_{s}.X <= __hbb_{s}.Max.X + __grow_{s}\n"
                f"                && __wo_{s}.Y >= __hbb_{s}.Min.Y - __grow_{s}\n"
                f"                && __wo_{s}.Y <= __hbb_{s}.Max.Y + __grow_{s}\n"
                f"                && __wo_{s}.Z >= __hbb_{s}.Min.Z - __grow_{s}\n"
                f"                && __wo_{s}.Z <= __hbb_{s}.Max.Z + __grow_{s})\n"
                f"                __inbb_{s} = true;\n"
                f"        }}\n"),
            verdict_cs=(
                f"    if (__wfn_{s} != 1)\n"
                f"        __post.Add(__wfn_{s}.ToString() + \" \"\n"
                f"            + {_cs(oid + ': наружных граней построенной стены сонаправлены названной грани массы, а должна быть ровно одна (geometry)')});\n"),
            message=("наружных граней построенной стены сонаправлены названной "
                     "грани массы, а должна быть ровно одна (geometry)"),
            style="guard"),
        WitnessCheck(
            # POSITION. The bounding box is expanded by the wall's OWN
            # thickness plus Revit's own number, not one of them assigned
            # by us: the wall's solid lies entirely within a band of
            # ±thickness from the host face, and the face lies inside the
            # host's bounding box, so the statement holds for ANY
            # `location_line` and fails if the wall was built off a
            # different mass than the one named. Both sides of the
            # comparison are in MODEL coordinates.
            obligation_key="face_wall_within_host",
            reader_cs="",
            verdict_cs=(
                f"    if (!__inbb_{s})\n"
                f"        __post.Add({_cs(oid + ': наружная грань построенной стены лежит вне габарита носителя, расширенного на её собственную толщину (geometry)')});\n"),
            message=("наружная грань построенной стены лежит вне габарита "
                     "носителя, расширенного на её собственную толщину "
                     "(geometry)"),
            style="guard"),
        WitnessCheck(
            # THE BOUNDARY OF VACUITY, not a threshold: zero area means
            # nothing was built at all.
            #
            # WHAT IS READ IS THE AREA OF THE SOLID'S FACE, NOT A
            # PARAMETER, and this is NOT a stylistic choice. The first
            # edition read `HOST_AREA_COMPUTED` and signed it (geometry) —
            # that is, it certified an axis it had not actually looked at:
            # a parameter can carry anything, including a value written by
            # something other than geometry. This was caught not by a
            # human but by the house's guard
            # (`test_witness_axis_honesty::GeometryClaimsMustReadGeometry`,
            # §18.3), and it is right: «the witness signs THE AXIS IT
            # ACTUALLY READ». `__warea_` comes from `PlanarFace.Area` of
            # that very outer face of the built solid which the normal
            # witness found — geometry both by source and by signature.
            obligation_key="face_wall_area_positive",
            reader_cs="",
            verdict_cs=(
                f"    if (!(__warea_{s} > 0.0))\n"
                f"        __post.Add({_cs(oid + ': площадь наружной грани построенного тела не больше нуля — не построено ничего (geometry)')});\n"),
            message=("площадь наружной грани построенного тела не больше нуля "
                     "— не построено ничего (geometry)"),
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"location_line\"] = {_cs(ll)};\n"
        f"    __rb[\"exterior_faces_codirectional\"] = __wfn_{s};\n"
        f"    __rb[\"within_host_bbox\"] = __inbb_{s};\n"
        f"    __rb[\"wall_width_mm\"] = MM(__wwid_{s});\n"
        f"    __rb[\"vertex_tolerance_mm\"] = MM(__wtol_{s});\n"
        # A RAW PAIR, AND NEITHER OF THE TWO NUMBERS IS A VERDICT. Whether
        # Revit covers the named face in full is not said by a single word
        # in any of the six RevitAPI.xml files; asserting equality would
        # mean introducing a check that could reject sound work, and
        # assigning a tolerance is exactly the forbidden kind. A live run
        # will close the question in an hour; reasoning never will.
        f"    __rb[\"named_face_area_mm2\"] = MM(MM(__farea_{s}));\n"
        f"    __rb[\"built_face_area_mm2\"] = MM(MM(__warea_{s}));\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ if (__ty_{s} != null && __ty_{s}.Name != null) "
        f"__rb[\"type_name\"] = __ty_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" correspondence lived in a hand-written
#: `authoring._EMITTERS`, and the body here, and a thin wrapper in the hub
#: tied them together (41 of them across 19 satellites). Two records of one
#: fact in different files are a named defect of this tree; now there is
#: ONE record, and the hub ASKS it.
EMITTERS = {
    "create_face_wall": emit_face_wall,
}
