"""sweep_emit — the emission of create_wall_sweep / create_slab_edge (the
paired file to `ops_sweep.py`, exactly as `site_emit.py` pairs with
`ops_site.py`).

Its own wave zone: the module touches no other `ops_*.py` and no other
`*_emit.py`. `authoring.py` receives an additively deferred import and two
lines in `_EMITTERS` — the same minimal seam the site, framing, and
architecture waves connected through.

Reused from `authoring.py` WITHOUT CHANGES (by import, not by copy): `_gid`,
`_eid`, `_cs`, `_safe`, `_stamp_block`, `_stamp_readback`, `EMIT_UNSUPPORTED`.
The same caveat as in the headers of `site_emit.py`/`struct_emit.py`: some
names are private, and the clean fix for the seam is promoting them to
public in `authoring.py`, not copying their bodies here.

THE MAIN THING ABOUT THIS FILE — TWO WITNESSES OF DIFFERENT STRENGTH, AND
THE DIFFERENCE IS NAMED, NOT HIDDEN. Both operations read the RESULT, not
their own call, but they assert DIFFERENT things about it:

* THE WALL PROFILE is the weakest witness in the entire registry, and this
  is a MEASUREMENT, not an unfinished job. All six versions'
  `RevitAPI.xml` write for `WallSweep.Create`, verbatim: «The wall sweep's
  profile and type are taken from the wall sweep type properties. The
  values set in the WallSweepInfo are ignored.» So it is the TYPE, not the
  call, that sets the profile's position on the wall; the operation
  accepts neither distances nor offsets at all, and there is nothing to
  assert about them. What remains is a TRIO OF EXACT facts about the
  built element — it exists, it is listed on the requested wall
  (`GetHostIds`), it has the requested type (`GetTypeId`) — plus a fourth,
  SEMANTIC one: orientation (`GetWallSweepInfo().IsVertical`), the one
  `WallSweepInfo` field the operation actually presents at all, because it
  cannot be written any other way (a read-only property, CS0200 on all
  six — exactly one channel, the constructor argument);
* THE EDGE PROFILE has a REAL geometric witness, and it exists precisely
  because the question "does `SlabEdge` have any reading at all" was
  MEASURED, not recalled from memory. `get_ReferenceCurve(Reference)` is
  an indexed property of the base `HostedSweep`, 6/6: the BUILT profile
  is asked for the curve it laid along EACH edge reference we passed it.
  `null` means Revit did not take that reference, and then the drip edge
  traces a different perimeter than the one that was ordered. There is
  nothing the emitter can do to fake this assertion: it passed the
  reference, and the element returned the curve.

THE EDGE REFERENCE IS NAMED NOT BY THE AUTHOR BUT BY CARDINALITY.
`NewSlabEdge` accepts a geometric reference, while the frozen KIR dialect
addresses ELEMENTS; the selector's second stage (`faceref.py`, 09.08) names
a FACE, but not an EDGE, and writing a third kind of second stage here
would mean starting a second mechanism next to the existing one. So the
operation takes the WHOLE PERIMETER of the named side, and both stages are
resolved by the CARDINALITY of a set, not by enumeration order — the same
law as in `faceref.py`:

    side  -> exactly one face, else a typed refusal WITH A NUMBER;
    face  -> exactly one loop, else a typed refusal WITH A NUMBER.

A slab with a hole honestly refuses with the second refusal: which of the
rings to trace is the author's decision, and "the first fitting one" under
the undocumented order of `Face.EdgeLoops` is `.FirstOrDefault()` under
another name (live measurement of 02.08: the C# arm silently took 1 door
type out of 62 and built it).

A TRAP NOT REPEATED HERE. Edge references are taken from geometry obtained
via `HostObjectUtils` + `Element.GetGeometryObjectFromReference` — that is,
from the geometry OF THE ELEMENT ITSELF. `GeometryInstance
.GetInstanceGeometry()` is NOT CALLED here AT ALL: RevitAPI.xml documents
its result as a COPY whose references are "not suitable for creating new
Revit elements referencing the original element", and this trap compiles
6/6 while failing live (the price for it was already paid by the
annotations branch, `9c5c7492`).

`NewSlabEdge` RETURNS NULL, IT DOES NOT THROW ("If successful a new slab
edge object within the project, otherwise null" — all six XML). So the
null check here is not overcaution but the sole boundary between a
refusal and a `NullReferenceException`, which the pipeline would record as
`internal` — i.e. as "something broke on our end" instead of "Revit did
not accept these edges".
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _stamp_block, _stamp_readback, EMIT_UNSUPPORTED,
)
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import (
    Diagnostic, EMIT_UNSUPPORTED_ENUM, KirRefusal, PARSE_MISSING_FIELD)
from kir.ops_sweep import (
    SWEEP_ORIENTATIONS, SLAB_EDGE_SIDES, WALL_SWEEP_NON_FIXED_ID,
)

#: Orientation/side outside the closed set. A belt over suspenders,
#: exactly as with the site wave (`site_emit`, the same shared code): the
#: `enum`-choices already catch this at authoring.validate(), and here
#: stands a defense in depth — whoever extends choices without finishing
#: the branch will fail LOUDLY, not silently build the wrong thing.

#: How a side NAMED BY REVIT ITSELF turns into a call to
#: `HostObjectUtils`. A table, not an `if`-ladder, and for the same reason
#: as `faceref._SIDE_CALL`: the list of sides is closed and lives in the
#: registry (`ops_sweep.SLAB_EDGE_SIDES`), and two places knowing it
#: separately would drift apart on the very first fix.
_SIDE_CALL: dict = {
    "top": "HostObjectUtils.GetTopFaces({ho})",
    "bottom": "HostObjectUtils.GetBottomFaces({ho})",
}


# ── shared helpers ──────────────────────────────────────────────────────────

def _host_resolve_cs(op: dict, s: str, ver: str, oid: str, isolation: str,
                     cs_class: str, human: str) -> tuple[str, str]:
    """(declaration, resolution) of the host into the variable `__ho_<s>`.

    THE HOST IS DECLARED IN THE OUTER SCOPE, not in the creation block:
    with `isolation="per_op"` create and post fall into DIFFERENT scopes,
    and a variable declared inside create is invisible to the witness
    (CS0103 — exactly the seam on which the railing wave took six gate
    failures), while the host's witness reads it.

    THE CAST GOES THROUGH `Element`, NOT DIRECTLY, and this is not
    decoration. `ref_kinds` on both ops includes ELEMENT, meaning the
    reference's source can turn out to be an op whose variable
    `__el_<id>` was declared as an UNRELATED class (`TopographySurface`,
    `Railing`, ...). A direct `__el_X as Wall` between unrelated classes
    is CS0039 on all six versions, meaning a program legal under the
    registry's typed contract would fail to compile at all. An upward
    cast to `Element` is legal for any Revit element, and `as` works from
    there.
    """
    sel = op["host"]
    decl = f"{cs_class} __ho_{s} = null;"
    if sel.get("by") == "ref":
        src = "__el_" + _safe(sel["value"])
        res = (f"Element __hsrc_{s} = {src};\n"
               f"__ho_{s} = __hsrc_{s} as {cs_class};\n")
    else:
        res = (f"Element __hsrc_{s} = doc.GetElement("
               f"{_eid(sel['value'], ver, oid)});\n"
               f"if (__hsrc_{s} == null) {{ "
               + refuse_stmt(oid, _cs(
                   f"{human}: носитель не найден (модель изменилась после "
                   f"grounding)"), isolation) + " }\n"
               f"__ho_{s} = __hsrc_{s} as {cs_class};\n")
    res += (f"if (__ho_{s} == null) {{ "
            + refuse_stmt(
                oid,
                _cs(f"{human}: носителем может быть только {human_host(cs_class)}, "
                    f"а этот элемент — ")
                + f" + __ClassName(__hsrc_{s}) + " + _cs(
                    ". СЛЕДУЮЩИЙ ХОД: назови в host элемент нужного класса"),
                isolation) + " }\n")
    return decl, res


def human_host(cs_class: str) -> str:
    """The host's class in HUMAN WORDS — for the refusal text.

    A refusal is read by a person, and "the host can only be a HostObject"
    sends them off to read Autodesk's documentation instead of their own
    program.
    """
    return {"Wall": "стена",
            "HostObject": "перекрытие, кровля, потолок или стена "
                          "(любой HostObject)"}[cs_class]


def _grounded_type_cs(op: dict, s: str, oid: str, ver: str, cs_class: str,
                      human: str, isolation: str) -> str:
    """Resolution of the type into the variable `__ty_<s>`.

    THERE IS NO doc_default BRANCH HERE, and this is VERIFIED, not
    inherited: `ElementTypeGroup.RevealType` and `.EdgeSlabType` exist on
    all six versions (measured against our own API database, which knows
    only 30 of the 93 members of this enum) — meaning asking the document
    "what is your default cornice" is technically POSSIBLE. And we still
    do not ask, for the same reason as with the ceiling and the building
    pad: a "default cornice" on someone else's building is almost never
    the right one, and a substituted type is indistinguishable from
    success from the outside. A missing `type` is resolved by `ground`
    under the general rule "the sole one in the pool, else a typed
    question with candidates" — and the author will SEE this question,
    unlike a substitution.

    A second reason, specific to this wave, is also named here: for the
    wall profile the TYPE DECIDES EVERYTHING (see the module's header), so
    a type substituted on the author's behalf is GEOMETRY substituted on
    the author's behalf, not merely a name in a schedule.
    """
    sel = op.get("type")
    g = _gid(op, "type") if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=(f"{human}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    # THE CAST DOES NOT ALWAYS EXIST, AND THE REFUSAL TEXT MUST REFLECT
    # THIS. For the edge profile, the type is a real class (`SlabEdgeType`),
    # and "it is not a SlabEdgeType" is a valid reason. For the wall
    # profile, the type is taken as an `Element`, because it has no type
    # class at all, and the same phrase would read "it is not an
    # Element" — a refusal that sends the person off to look for a
    # difference that does not exist.
    cast = "" if cs_class == "Element" else f" as {cs_class}"
    why = ("тип не найден (модель изменилась после grounding)"
           if cs_class == "Element" else
           f"тип не найден или он не {cs_class} "
           f"(модель изменилась после grounding)")
    guard = (f"\nif (__ty_{s} == null) {{ "
             + refuse_stmt(oid, _cs(f"{human}: {why}"), isolation) + " }")
    return (f"__ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}){cast};"
            + guard)


def _type_id_witness(s: str, oid: str, human: str) -> WitnessCheck:
    """THE TYPE OF THE BUILT ELEMENT, read back.

    Shared by both operations, because their assertion is word-for-word
    the same: `GetTypeId()` of the built element equals the id that
    ground resolved BEFORE the effect. Comparing via `ToString()` is the
    only `ElementId` idiom that works on all six versions:
    `.IntegerValue` is dead on 2026, `.Value` does not exist before 2024.
    """
    return WitnessCheck(
        obligation_key="sweep_type",
        reader_cs=f"    ElementId __rt_{s} = __el_{s}.GetTypeId();\n",
        verdict_cs=(
            f"    if (__rt_{s} == null || __ty_{s} == null\n"
            f"        || __rt_{s}.ToString() != __ty_{s}.Id.ToString())\n"
            f"        __post.Add({_cs(oid + f': тип построенного элемента ({human}) не равен запрошенному (topology)')});\n"),
        message=f"тип построенного элемента ({human}) не равен запрошенному (topology)",
        style="guard")


# ── create_wall_sweep ────────────────────────────────────────────────────────

def emit_wall_sweep(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A cornice/molding/reveal on a wall, Revit 2021-2026.

    `WallSweep.Create(Wall, ElementId wallSweepTypeId, WallSweepInfo)` —
    6/6, `since 2012`, there is NO version fork, and this is a fact of
    measurement, not a hope.

    THE PROFILE'S KIND IS DERIVED FROM THE TYPE'S CATEGORY, NOT ASKED OF
    THE AUTHOR. `WallSweepType` is an ENUM {Sweep, Reveal}, not a type
    class; the type itself lives as an ordinary `ElementType` in
    `OST_Cornices` (cornice) or `OST_Reveals` (reveal). Asking the author
    for the kind would mean introducing a field that could CONTRADICT the
    type — and by Autodesk's remark (the module's header) the type would
    win, meaning the answer given to the author would silently be a
    different one. The category is checked via `Category.GetCategory(doc,
    ...)` and `Id.ToString()`: a version-safe idiom on all six
    (`.IntegerValue` is dead on 2026).

    THE PREFLIGHT CHECK `WallAllowsWallSweep` IS NOT AN INVENTED GATE.
    "wall may not host a wall sweep or reveal" is in the list of
    conditions for `ArgumentException` of `Create` itself (all six XML),
    and the method's documentation lists what it excludes: curtain walls
    and a compound wall's main wall. That is, the API REQUIRES this
    refusal; without the preflight check it would have arrived as a Revit
    exception, which the pipeline would record as `internal` — "something
    broke on our end" instead of "this wall cannot carry a profile, pick
    another one".

    `WallSweepInfo.Id = -1` IS SET EXPLICITLY: "The WallSweepInfo id must
    be set to -1 for a non-fixed wall sweep" — also a condition for
    `ArgumentException`. Relying on the constructor's default would mean
    handing an entire class of exceptions to runtime for the sake of one
    unwritten line.
    """
    oid = op["id"]
    s = _safe(oid)
    orientation = op.get("orientation")
    if orientation not in SWEEP_ORIENTATIONS:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="orientation",
            got=orientation, candidates=list(SWEEP_ORIENTATIONS),
            message_ru=(f"create_wall_sweep: ориентация {orientation!r} не "
                        f"поддержана — у WallSweepInfo ровно два состояния, и "
                        f"записать их можно только конструктором"))])
    vertical = "true" if orientation == "vertical" else "false"
    human = "стенной профиль"
    host_decl, host_res = _host_resolve_cs(op, s, ver, oid, isolation,
                                           "Wall", human)
    ty = _grounded_type_cs(op, s, oid, ver, "Element", human, isolation)

    # `__hs_` IS DECLARED HERE, NOT IN THE WITNESS'S READER, AND THIS WAS
    # CAUGHT BY THE GATE, not by reasoning: the postcondition block is ITS
    # OWN scope (`// post <oid>\n{ ... }`), and the receipt stands in THE
    # NEXT one. A name declared in the reader dies at the post's closing
    # brace, and the receipt gets CS0103 on all six versions under both
    # isolations (measured 09.08: 48 live cells, 48 failures). This
    # house's scope contract is about exactly this: whatever POST or the
    # receipt reads is declared in `decl`.
    decl = (f"WallSweep __el_{s} = null;\n"
            f"Element __ty_{s} = null;\n"
            f"WallSweepInfo __wi_{s} = null;\n"
            f"bool __rev_{s} = false;\n"
            f"ICollection<ElementId> __hs_{s} = null;\n"
            + host_decl)

    create = (
        f"// create_wall_sweep {cs_line_comment_fragment(oid)}\n"
        + host_res
        + f"{ty}\n"
        # The profile's kind — from the TYPE's category. Both categories 6/6.
        f"Category __rc_{s} = Category.GetCategory(doc, BuiltInCategory.OST_Reveals);\n"
        f"Category __sc_{s} = Category.GetCategory(doc, BuiltInCategory.OST_Cornices);\n"
        f"string __tc_{s} = (__ty_{s}.Category == null) ? \"\" : __ty_{s}.Category.Id.ToString();\n"
        f"__rev_{s} = (__rc_{s} != null && __tc_{s} == __rc_{s}.Id.ToString());\n"
        f"bool __swp_{s} = (__sc_{s} != null && __tc_{s} == __sc_{s}.Id.ToString());\n"
        f"if (!__rev_{s} && !__swp_{s}) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: разрешённый тип не принадлежит ни карнизам "
                f"(OST_Cornices), ни рустам (OST_Reveals) — WallSweep.Create "
                f"строит только их. Тип: ")
            + f" + (__ty_{s}.Name ?? \"\") + " + _cs(
                ". СЛЕДУЮЩИЙ ХОД: спроси каталог операцией "
                "query_types(pool=\"wall_sweep_types\") и назови тип оттуда"),
            isolation) + " }\n"
        # The preflight check that `Create` itself REQUIRES (see the docstring).
        f"if (!WallSweep.WallAllowsWallSweep(__ho_{s})) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: эта стена не может нести профиль "
                f"(WallSweep.WallAllowsWallSweep вернул false — метод исключает "
                f"витражные стены и главную стену составной стены). СЛЕДУЮЩИЙ "
                f"ХОД: назови в host обычную стену"),
            isolation) + " }\n"
        f"__wi_{s} = new WallSweepInfo("
        f"__rev_{s} ? WallSweepType.Reveal : WallSweepType.Sweep, {vertical});\n"
        f"__wi_{s}.Id = {WALL_SWEEP_NON_FIXED_ID};\n"
        f"__el_{s} = WallSweep.Create(__ho_{s}, __ty_{s}.Id, __wi_{s});\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("создание стенного профиля вернуло null"),
                      isolation) + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    checks: list[WitnessCheck] = [
        WitnessCheck(
            # THE HOST, READ FROM THE BUILT ELEMENT. `GetHostIds()`
            # returns a LIST — a profile running along a chain of joined
            # walls has several hosts — so the assertion here is "our wall
            # is AMONG the hosts", not "there is exactly one host".
            # Demanding uniqueness would mean accusing a correctly built
            # cornice that has carried over onto a neighboring wall: Revit
            # does this itself, and the `GetHostIds` remark ("Fixed wall
            # sweeps ... will return only one host element") directly
            # implies that non-fixed ones can return more than one.
            obligation_key="sweep_host",
            reader_cs=(
                f"    try {{ __hs_{s} = __el_{s}.GetHostIds(); }} catch {{ }}\n"
                f"    bool __hh_{s} = false;\n"
                f"    if (__hs_{s} != null && __ho_{s} != null)\n"
                f"        foreach (ElementId __hq_{s} in __hs_{s})\n"
                f"            if (__hq_{s} != null && __hq_{s}.ToString() == __ho_{s}.Id.ToString())\n"
                f"            {{ __hh_{s} = true; break; }}\n"),
            verdict_cs=(
                f"    if (!__hh_{s})\n"
                f"        __post.Add({_cs(oid + ': построенный профиль не числится на запрошенной стене (topology)')});\n"),
            message="построенный профиль не числится на запрошенной стене (topology)",
            style="guard"),
        _type_id_witness(s, oid, human),
        WitnessCheck(
            # ORIENTATION IS THE ONLY THING THE AUTHOR SAID ABOUT THE
            # SHAPE, AND THEREFORE THE ONLY THING CHECKED HERE BEYOND
            # IDENTITY. Autodesk's remark ("values set in the
            # WallSweepInfo are ignored") makes the outcome UNDEFINED, not
            # certainly false: the orientation channel is a constructor
            # argument, not a "set". An undefined assertion must be
            # CHECKED, not taken on faith: if live Revit extends the
            # remark to the constructor too, the program will get a typed
            # failure — instead of a silently built horizontal molding
            # where a vertical reveal was asked for. The reader's failure
            # (`null`) is ALSO a violation, not silence: we check exactly
            # what the author stated, and "we could not read it" has no
            # right to look like "it matched".
            obligation_key="sweep_orientation",
            reader_cs=(
                f"    WallSweepInfo __ri_{s} = null;\n"
                f"    try {{ __ri_{s} = __el_{s}.GetWallSweepInfo(); }} catch {{ }}\n"),
            verdict_cs=(
                f"    if (__ri_{s} == null)\n"
                f"        __post.Add({_cs(oid + ': GetWallSweepInfo() не прочитался — подтвердить ориентацию нечем (semantic)')});\n"
                f"    else if (__ri_{s}.IsVertical != {vertical})\n"
                f"        __post.Add({_cs(oid + ': ориентация построенного профиля не та, что запрошена (semantic)')});\n"),
            message="ориентация построенного профиля не та, что запрошена (semantic)",
            style="guard"),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"sweep_kind\"] = __rev_{s} ? \"reveal\" : \"sweep\";\n"
        f"    __rb[\"orientation\"] = {_cs(orientation)};\n"
        f"    try {{ __rb[\"host_count\"] = (__hs_{s} == null) ? -1 : __hs_{s}.Count; }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ if (__ty_{s} != null && __ty_{s}.Name != null) __rb[\"type_name\"] = __ty_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


# ── create_slab_edge ─────────────────────────────────────────────────────────

def emit_slab_edge(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A drip edge / edge profile along the perimeter of a named side of
    a slab.

    `Autodesk.Revit.Creation.Document.NewSlabEdge(SlabEdgeType,
    ReferenceArray)` — 6/6, there is NO version fork.

    TWO STAGES, BOTH RESOLVED BY CARDINALITY (see the module's header). At
    no point is there a "first fitting one", so the undocumented order of
    faces and edges has no effect on the result whatsoever.

    WHY THE PERIMETER IS COMPUTED RIGHT HERE, EVEN THOUGH IT DOES NOT
    TRAVEL INTO THE VERDICT. The sum of the edge lengths is an OBSERVATION
    in the receipt, not an assertion: at the joints Revit miters the
    profile, and nobody has measured by how much exactly. Checking
    `HostedSweep.Length` against this sum could only be done with an
    assigned tolerance — exactly the class of defect this house calls its
    own ("a bound authored by reasoning"). So both numbers sit in the
    receipt, and a live run will close the question in an hour, which
    reasoning never will.
    """
    oid = op["id"]
    s = _safe(oid)
    side = op.get("side")
    if side not in SLAB_EDGE_SIDES:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED_ENUM, op_id=oid, field_name="side",
            got=side, candidates=list(SLAB_EDGE_SIDES),
            message_ru=(f"create_slab_edge: сторона {side!r} не поддержана — "
                        f"стороны НАЗЫВАЕТ САМ Revit (HostObjectUtils), и у "
                        f"горизонтального носителя их ровно две"))])
    human = "краевой профиль"
    host_decl, host_res = _host_resolve_cs(op, s, ver, oid, isolation,
                                           "HostObject", human)
    ty = _grounded_type_cs(op, s, oid, ver, "SlabEdgeType", human, isolation)
    face_call = _SIDE_CALL[side].format(ho=f"__ho_{s}")

    # `__named_`/`__bound_` — see the same comment for the wall profile:
    # they are read by THE RECEIPT, i.e. the scope following the
    # postcondition block. ONE DECLARATION PER LINE, not `int a = 0, b =
    # 0;` — the scope contract parses declarations line by line, and the
    # second variable in the list is, to it, NOT DECLARED (the same seam
    # as in site_emit._boundary_bbox_witness).
    decl = (f"SlabEdge __el_{s} = null;\n"
            f"SlabEdgeType __ty_{s} = null;\n"
            f"List<Reference> __edges_{s} = null;\n"
            f"double __plen_{s} = 0.0;\n"
            f"int __named_{s} = 0;\n"
            f"int __bound_{s} = 0;\n"
            + host_decl)

    create = (
        f"// create_slab_edge {cs_line_comment_fragment(oid)}\n"
        + host_res
        + f"{ty}\n"
        # STAGE 1: side -> exactly one face.
        # Newly created hosts have no computed side faces until regeneration.
        f"doc.Regenerate();\n"
        f"IList<Reference> __fs_{s} = null;\n"
        f"try {{ __fs_{s} = {face_call}; }} catch {{ }}\n"
        f"int __nf_{s} = (__fs_{s} == null) ? 0 : __fs_{s}.Count;\n"
        f"if (__nf_{s} == 0) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: у носителя нет грани со стороны «{side}» "
                f"(HostObjectUtils вернул пусто). СЛЕДУЮЩИЙ ХОД: проверь, что "
                f"host — плита или кровля, и назови другую сторону"),
            isolation) + " }\n"
        f"if (__nf_{s} > 1) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: со стороны «{side}» у носителя не одна грань, а ")
            + f" + __nf_{s}.ToString() + " + _cs(
                ". Компилятор НЕ выбирает за автора: порядок граней в теле не "
                "документирован, поэтому «первая подходящая» — число без "
                "смысла. СЛЕДУЮЩИЙ ХОД: краевой профиль по ступенчатому "
                "носителю строится отдельной операцией на каждую его плоскость"),
            isolation) + " }\n"
        f"Face __fc_{s} = null;\n"
        # GetGeometryObjectFromReference does not supply usable edge references.
        # Read original geometry with references and match the named face by
        # identity, without choosing by geometry or enumeration order.
        f"try {{\n"
        f"    var __wanted_{s} = __fs_{s}[0].ConvertToStableRepresentation(doc);\n"
        f"    var __options_{s} = new Options {{ ComputeReferences = true, DetailLevel = ViewDetailLevel.Fine }};\n"
        f"    var __geometry_{s} = __ho_{s}.get_Geometry(__options_{s});\n"
        f"    if (__geometry_{s} != null) foreach (GeometryObject __object_{s} in __geometry_{s}) {{\n"
        f"        Solid __solid_{s} = __object_{s} as Solid;\n"
        f"        if (__solid_{s} == null) continue;\n"
        f"        foreach (Face __candidate_{s} in __solid_{s}.Faces) {{\n"
        f"            if (__candidate_{s}.Reference != null && __candidate_{s}.Reference.ConvertToStableRepresentation(doc) == __wanted_{s}) {{\n"
        f"                __fc_{s} = __candidate_{s}; break;\n"
        f"            }}\n"
        f"        }}\n"
        f"        if (__fc_{s} != null) break;\n"
        f"    }}\n"
        f"}} catch {{ }}\n"
        f"if (__fc_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: грань со стороны «{side}» не читается как Face — "
                f"геометрию носителя прочитать не удалось"),
            isolation) + " }\n"
        # STAGE 2: face -> exactly one contour.
        f"EdgeArrayArray __ls_{s} = __fc_{s}.EdgeLoops;\n"
        f"int __nl_{s} = (__ls_{s} == null) ? 0 : __ls_{s}.Size;\n"
        f"if (__nl_{s} != 1) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: у грани со стороны «{side}» не один контур, а ")
            + f" + __nl_{s}.ToString() + " + _cs(
                " — значит в носителе есть отверстия, и какое из колец "
                "обводить, решает автор, а не компилятор. СЛЕДУЮЩИЙ ХОД: "
                "назови ребро явно, когда у операции появится второй род "
                "селектора (сегодня его нет: вторая ступень называет ГРАНЬ, "
                "не ребро)"),
            isolation) + " }\n"
        f"__edges_{s} = new List<Reference>();\n"
        f"ReferenceArray __ra_{s} = new ReferenceArray();\n"
        f"foreach (Edge __ed_{s} in __ls_{s}.get_Item(0))\n"
        f"{{\n"
        f"    Reference __er_{s} = __ed_{s}.Reference;\n"
        f"    if (__er_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: у ребра периметра нет ссылки (Edge.Reference == "
                f"null) — по такому ребру профиль проложить нечем"),
            isolation) + " }\n"
        f"    Curve __ec_{s} = __ed_{s}.AsCurve();\n"
        f"    if (__ec_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: ребро периметра не читается как кривая"),
            isolation) + " }\n"
        f"    __plen_{s} += __ec_{s}.Length;\n"
        f"    __edges_{s}.Add(__er_{s});\n"
        f"    __ra_{s}.Append(__er_{s});\n"
        f"}}\n"
        f"if (__ra_{s}.Size == 0) {{ "
        + refuse_stmt(
            oid,
            _cs(f"{human}: контур грани не дал ни одного ребра"),
            isolation) + " }\n"
        # NewSlabEdge returns null, not throws (all six XML).
        f"__el_{s} = doc.Create.NewSlabEdge(__ty_{s}, __ra_{s});\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs("создание краевого профиля вернуло null — Revit не принял "
                "эти рёбра (NewSlabEdge документирован как возвращающий null "
                "при неудаче, а не бросающий)"),
            isolation) + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    checks: list[WitnessCheck] = [
        WitnessCheck(
            # THE ACTUAL RESULT READING: the BUILT profile is asked for the
            # curve it laid along each reference passed to it. The emitter
            # cannot fake this in any way — it passed the reference, but it
            # is the element that returned the curve. `null` means Revit did
            # not accept that reference, i.e. the drip edge traces the WRONG
            # perimeter — not the one requested — and from the outside this
            # is indistinguishable from success.
            obligation_key="slab_edge_binding",
            reader_cs=(
                f"    __named_{s} = (__edges_{s} == null) ? 0 : __edges_{s}.Count;\n"
                f"    if (__edges_{s} != null)\n"
                f"        foreach (Reference __wr_{s} in __edges_{s})\n"
                f"        {{\n"
                f"            Curve __wc_{s} = null;\n"
                f"            try {{ __wc_{s} = __el_{s}.get_ReferenceCurve(__wr_{s}); }} catch {{ }}\n"
                f"            if (__wc_{s} != null) __bound_{s}++;\n"
                f"        }}\n"),
            verdict_cs=(
                f"    if (__named_{s} == 0 || __bound_{s} != __named_{s})\n"
                f"        __post.Add(__bound_{s}.ToString() + \" из \" + __named_{s}.ToString() + \" \"\n"
                f"            + {_cs(oid + ': рёбер периметра связаны в построенном профиле (geometry)')});\n"),
            message="рёбер периметра связаны в построенном профиле (geometry)",
            style="guard"),
        _type_id_witness(s, oid, human),
    ]

    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"side\"] = {_cs(side)};\n"
        f"    __rb[\"edges_named\"] = __named_{s};\n"
        f"    __rb[\"edges_bound\"] = __bound_{s};\n"
        # BOTH NUMBERS, AND NEITHER IS THE VERDICT: the perimeter is what we
        # passed in, the length is what Revit built. Their discrepancy is
        # exactly the miter-trim amount that nobody has measured; a live run
        # will close the question, while an assigned tolerance would only
        # mask it.
        f"    __rb[\"perimeter_mm\"] = MM(__plen_{s});\n"
        f"    try {{ __rb[\"sweep_length_mm\"] = MM(__el_{s}.Length); }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ if (__ty_{s} != null && __ty_{s}.Name != null) __rb[\"type_name\"] = __ty_{s}.Name; }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS — DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" mapping lived in the handwritten
#: `authoring._EMITTERS`, while the body lived here, and a thin wrapper in
#: the hub tied the two together (41 of them across 19 satellites). Two
#: records of one fact in different files is a named defect of this tree;
#: now there is ONE record, and the hub QUERIES it.
EMITTERS = {
    "create_slab_edge": emit_slab_edge,
    "create_wall_sweep": emit_wall_sweep,
}
