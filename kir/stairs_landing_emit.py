"""stairs_landing_emit — A SKETCHED STAIR LANDING (the stairs wave, 10.08.2026).

WHY THIS OPERATION EXISTS.  Before it, the compiler could handle exactly one flight —
straight or spiral — and a stair without a landing is a single-flight stair.
A real building is not built that way: an intermediate landing sits between floors, and
the language had NOTHING to say this with.  A capability census (10.08,
`tools/api_capability_census.py`) found the entire landing family had never once
been considered; here we take ONE factory — the one whose witness reads the
RESULT and can fail — while the other four are refused BY NAME below.

────────────────────────────────────────────────────────────────────────────
API MEASUREMENT (compiled against :52412, against real 2021-2026 assemblies, 10.08.2026;
the arbiter is the compiler, not RevitAPI.xml — see CLAUDE.md on SpatialElementTag)
────────────────────────────────────────────────────────────────────────────

  StairsLanding.CreateSketchedLanding(Document, ElementId,
                CurveLoop, Double)                 -> StairsLanding    → 6/6
  StairsLanding.CreateSketchedLandingWithSlopeData(Document, ElementId,
                IList<SketchedStairsCurveData>, Double)                → 6/6
  StairsLanding.CanCreateAutomaticLanding(Document, ElementId×2)       → 6/6
  StairsRun.CreateSketchedRun(Document, ElementId, Double,
                IList<Curve>×3)                                        → 6/6
  StairsRun.CreateSketchedRunWithSlopeData(Document, ElementId, Double,
                IList<SketchedStairsCurveData>, IList<Curve>×2)        → 6/6
  new SketchedStairsCurveData(Curve, Double, SketchedCurveSlopeOption) → 6/6
  StairsEditScope.Start(ElementId stairsId)   — SINGLE-ARGUMENT         → 6/6
  StairsEditScope.Start(ElementId base, ElementId top)                 → 6/6
  StairsEditScope.IsPermitted / Stairs.IsInEditMode()                  → 6/6
  Stairs.GetStairsLandings() / .GetStairsRuns()                        → 6/6
  Stairs.ActualRiserHeight / .BaseElevation / .TopElevation            → 6/6
  StairsLanding.GetFootprintBoundary() -> CurveLoop                    → 6/6
  StairsLanding.BaseElevation / .Thickness / .IsAutomaticLanding       → 6/6
  StairsLanding.GetStairs() / .GetStairsPath()                         → 6/6
  StairsLanding.SetSketchedLandingBoundaryAndPath(Document, CurveLoop×2)→ 6/6
  doc.Application.VertexTolerance                                      → 6/6

  StairsLanding lg = ...CreateAutomaticLanding(doc, r1, r2)  → 0/6  CS1061
      (the actual return type is `IList<ElementId>`, confirmed by a separate line:
       `IList<ElementId> x = CreateAutomaticLanding(...)` compiles 6/6)
  BuiltInParameter.STAIRS_LANDING_ELEVATION                  → 0/6  CS0117
  ElementTypeGroup.StairsLandingType                         → 0/6  CS0117

THE LAST THREE LINES ARE NOT PEDANTRY, each one closed off a separate temptation.
The landing's elevation is read via the PROPERTY `BaseElevation`: no BuiltInParameter
chain exists for it on any version, and a witness written through a BIP
would not compile anywhere.  Asking the document "what is your default landing type"
IS IMPOSSIBLE BY CONSTRUCTION — `ElementTypeGroup` carries no such member — and so
the operation has NO `type` parameter at all: the landing's type is determined by the
stair's type (Autodesk: «The landing type … is determined by stairs type»), meaning the
choice has already been made by the owner and there should be no second input for it.  And
`CreateAutomaticLanding` returns a LIST of identifiers, not an element — that is
exactly why the census flagged it as "invisible from its return type", and exactly why
it is refused below with a separate reason.

────────────────────────────────────────────────────────────────────────────
THE LANDING NEEDS THE SAME EDIT SCOPE AS THE FLIGHT — THIS IS A MEASUREMENT, NOT A GUESS
────────────────────────────────────────────────────────────────────────────
RevitAPI.xml states for `CreateSketchedLanding`, verbatim and identically across all
six versions: `InvalidOperationException` — «The stairs element represented
by stairsId is not in an active StairsEditScope.  New components cannot be
added to it.»  So the edit scope is mandatory, and the question "couldn't we just
place the landing next to the flight in one program" is resolved NOT by weakening
the solo-op law, but by a second fact from the same measurement: `StairsEditScope.Start`
has a SINGLE-ARGUMENT overload (`Start(ElementId stairsId)`, 6/6), which
opens an edit scope on an ALREADY EXISTING stair.

Hence the design: `create_stairs_landing` is ITSELF a solo-op (`spec.SOLO_OPS`), with
its own program template, and it addresses the stair by its `element_id`.  The price of
a landing is a SEPARATE PROGRAM, exactly as the price of a multi-story turned out to be two
programs (`datum_emit.emit_multistory_stairs`).  The batch law is not weakened by even
a byte here: Revit does not open two edit scopes in one document at the same time
(«there already is a stairs edit mode active in the document» — the same exception
text), so the coexistence of two stair ops is inexpressible BY REVIT, not
by our taste.

────────────────────────────────────────────────────────────────────────────
REFUSED BY NAME, WITH A REASON (the census separately counts the "named without
a reason" bucket — every line below keeps it small)
────────────────────────────────────────────────────────────────────────────

`StairsLanding.CreateAutomaticLanding` — REFUSED.  Not because it does not exist
    (it does, 6/6), but because it requires TWO ALREADY-BUILT FLIGHTS of one
    stair, while the compiler today builds EXACTLY ONE flight per stair
    (`create_stairs`: either straight or spiral, exactly one call).  There is nowhere
    to get a second flight from, meaning the operation would only be callable on
    a stair we did not build and cannot verify from outside.  Plus its return
    type is `IList<ElementId>` (the measurement above): Autodesk writes "landing(s)",
    Revit chooses the number of landings, and we have no witness for the COUNT — the
    author never named any count, and demanding a specific one would mean
    repeating the `height_mm` defect (31.07, correctly built walls were being
    rolled back).  WHAT THIS OPENS: a multi-flight run in `create_stairs`;
    then the automatic landing would gain both an entry point and a meaningful witness.

`StairsLanding.CreateSketchedLandingWithSlopeData` — REFUSED.  It differs from
    the one we took by exactly one thing: instead of `CurveLoop` it takes an
    `IList<SketchedStairsCurveData>`, where EVERY edge has its own height and
    `SketchedCurveSlopeOption` (Sloped/Flat).  This is a THIRD COORDINATE for the
    contour, and CONTOUR is a flat sub-language by construction (the canon, item 1:
    edges [(p0_mm, p1_mm, bulge)], all the trigonometry happens at compile time, z is set by
    the consumer).  Introducing a per-edge slope here would mean either extending
    CONTOUR (a LANGUAGE change, not an operation), or introducing a SECOND way
    to specify a profile — exactly what the canon forbids.  WHAT THIS OPENS: a
    slopes wave in CONTOUR; the same door is needed for a sloped ceiling, whose slope
    is likewise currently named as absent.

`StairsRun.CreateSketchedRun` — REFUSED.  It takes THREE independent lists
    of curves (the boundary, the risers, the path line), tied together by
    conditions that Autodesk does not spell out in any of the six
    RevitAPI.xml files: how many risers there must be, exactly where they cross the
    boundary, whether the path line must lie inside.  None of these conditions is
    checkable by the compiler, and a witness on the RESULT would have to be built on
    a guess about what Revit will do with an inconsistent triple.  The straight and
    spiral flights already give the flight's SHAPE through one meaningful input; a sketched
    run is a drawing, not a shape.  WHAT THIS OPENS: a live measurement on a real
    stair — exactly what `GetFootprintBoundary`/`GetStairsPath` hand back
    for a sketched run built by hand.

`StairsRun.CreateSketchedRunWithSlopeData` — REFUSED TWICE: it carries both
    reasons named above at once (the triple of inconsistent lists AND a per-edge
    slope).  It needs no separate reason, but it is not passed over silently either.

`StairsLanding.SetSketchedLandingBoundaryAndPath` — REFUSED as an OPERATION
    (6/6, it exists).  This is an EDIT of an already-standing landing, not a creation, i.e.
    the `set_param`/`move_elements` family, which has its own contract for
    exact mutations (`acceptance_mutation.py`: a predicate for the exact final
    state, proofs via ElementId+UniqueId+VersionGuid).  Tacking an edit onto the
    creating operation would mean bypassing this contract.  WHAT THIS
    OPENS: a sketch-editing wave, shared with the opening and the floor.
"""
from __future__ import annotations

from kir import contour as C
from kir.emit_core import (  # noqa: F401
    _AUTH_PREAMBLE, _cs, _document_binding_guard, _eid,
    _element_identity_guard, _indent, _program_stamp, _safe,
    _stamp_block, _stamp_readback, _with_program_helpers,
)
from kir.diag import (
    Diagnostic, EMIT_CONTOUR_HOLES, KirRefusal, PLAN_SOLO_OP)
from kir.emit_utils import (
    cs_line_comment_fragment,
    failure_channel_reset_cs,
    failure_preprocessor_cs,
    failure_warnings_into_results_cs,
)

#: A second ring for the landing is inexpressible: `CreateSketchedLanding` takes a SINGLE
#: `CurveLoop`, and there is no second loop argument in the signature on any of the six
#: versions.  The code is the same one used for the opening and
#: for the beam system — the shared `diag.EMIT_CONTOUR_HOLES`: one class
#: of defect — one code.

#: An in-program reference for a solo-op is unresolvable by construction.  The registry already
#: refuses it at parse time (`ref_kinds=()`); this is the last line of defense — the same
#: technique and the SAME CODE as `authoring._lvl_pin` for `create_stairs`: it is
#: one fact ("the op owns its own transaction and is therefore solitary"), so it is one code.
LANDING_SOLO_REF = PLAN_SOLO_OP


def _n(value: float) -> str:
    """A number into a C# literal without losing digits (the same technique as in datum_emit)."""
    return repr(float(value) + 0.0)


def emit_stairs_landing_program(
    op: dict, ver: str, intent: str = "", *, stamp_scope: str = "",
    expected_document=None, expected_identities=None,
) -> str:
    """A separate template for a WHOLE program: a sketched landing on its own stair.

    The design mirrors `authoring.emit_stairs_program` one-to-one, and this is
    NOT copy-paste for the sake of symmetry, but one and the same Revit law: `StairsEditScope`
    owns its own transactions and does not nest inside the program's shared
    transaction (the reason for rule `KIR-L002`).  What it shares with the flight is the
    edit-scope scaffolding, the failure pre-handler at BOTH points (the transaction and
    `StairsEditScope.Commit`), the trailing `__KirPad`; what is its own is resolving
    the host stair, the contour, and the witnesses.

    THE FAILURE PRE-HANDLER SITS IN THE SAME PLACE AND FOR THE SAME REASON (the
    27.07.2026 incident): a modal dialog freezes Revit's UI thread, and a stair
    that left one behind killed the bridge on the next six calls in a row —
    to the user this is "KUKI froze after the stairs", forever.  Everything new in
    this family must live inside the same discipline, so the warning is suppressed,
    while a REAL error is still handed back to Revit.
    """
    oid = op["id"]
    s = _safe(oid)
    stamp = _program_stamp([op], stamp_scope)

    region = op["__region__"]
    # HOLES ARE REFUSED, NOT DROPPED.  Silently dropping them
    # would build a SOLID landing where a cutout was requested.
    if region["holes"]:
        raise KirRefusal([Diagnostic(
            code=EMIT_CONTOUR_HOLES, op_id=oid, field_name="contour.holes",
            got=len(region["holes"]),
            message_ru=("create_stairs_landing: StairsLanding."
                        "CreateSketchedLanding принимает ОДНУ замкнутую петлю "
                        "— второго кольца в подписи нет ни на одной версии "
                        "2021-2026.  Вырез в площадке лестницы этой операцией "
                        "невыразим"))])

    edges = region["outer"]

    tgt = op["stairs"]
    if tgt.get("by") == "ref":
        # A solo program: there is no predecessor at all.  The registry
        # has already refused this at parse time; here is the last line of defense.
        raise KirRefusal([Diagnostic(
            code=LANDING_SOLO_REF, op_id=oid, field_name="stairs",
            message_ru=("stairs: ref недопустим в соло-программе "
                        "create_stairs_landing — предшествующих опов у неё "
                        "нет по построению; назовите element_id лестницы"))])

    elev = float(op["elevation_mm"])

    # THE SHORTEST AUTHORED EDGE — the material for the vacuity ban below.
    # It is measured by CHORD, using the same `_dist` that CONTOUR uses to measure its own edges.
    min_edge = min(C._dist(p0, p1) for p0, p1, _b in edges)

    pre_doc_guard = _document_binding_guard(expected_document, rollback="")
    pre_identity_guard = _element_identity_guard(
        expected_identities, ver, rollback="")
    # After Start, a typed refusal is only permitted if BOTH effects are
    # provably undone: the transaction returned RolledBack, and the scope, after Cancel,
    # is no longer active.  The A5 guards get exactly this fail-closed tail.
    txn_rollback = (
        f"if (!__rollbackCancel_{s}(__t, __ess)) "
        f"throw new InvalidOperationException(\"transaction rollback / "
        f"stairs scope cancellation is unproven\"); ")
    txn_doc_guard_raw = _document_binding_guard(
        expected_document, rollback=txn_rollback)
    txn_doc_guard = (_indent(txn_doc_guard_raw, "        ") + "\n"
                     if txn_doc_guard_raw else "")
    txn_identity_guard_raw = _element_identity_guard(
        expected_identities, ver, rollback=txn_rollback,
        symbol_prefix="__kirLandingTxnBinding")
    txn_identity_guard = (_indent(txn_identity_guard_raw, "        ") + "\n"
                          if txn_identity_guard_raw else "")

    # THE CONTOUR SITS ON THE STAIR'S OWN BASE ELEVATION, NOT ON ZERO.
    # Autodesk states about `GetFootprintBoundary`, verbatim: it hands back the boundary
    # «projected on the stairs base level», meaning the landing's plane is the
    # stair's plane, not the world zero.  A loop left at zero under a
    # stair at +3.000 is either rejected, or builds the landing in the wrong place —
    # the same seam and the same fix as in `create_beam_system` (the profile at
    # `MM(__lv.Elevation)`).  The elevation is known only at runtime, so what goes into
    # the `pt` formatter is a C# EXPRESSION, not a number.
    zexpr = f"__sbz_{s}"
    fmt = (lambda x, y:
           f"P({round(x, C._EMIT_DECIMALS)}, {round(y, C._EMIT_DECIMALS)}, "
           f"{zexpr})")
    loop_cs = _indent(C.emit_loop_cs(edges, f"__ol_{s}", pt=fmt), "        ")

    # THE AUTHORED CONTOUR, EMITTED INTO C# ONCE: the witness checks against IT,
    # not against whatever it itself passed into the call.  The triple (start, midpoint,
    # end) is the same shape used for the fill: a straight line and an arc between the
    # same two endpoints are indistinguishable by their endpoints alone, and the arc's
    # sagitta would otherwise remain unproven.
    triples = C.edge_witness_triples(edges)
    n_edges = len(triples)

    def _arr(name: str, values) -> str:
        return (f"double[] __{name}_{s} = new double[] {{ "
                + ", ".join(_n(round(v, C._EMIT_DECIMALS)) for v in values)
                + " };")

    author_arrays = "\n".join([
        _arr("bx0", [t[0][0] for t in triples]),
        _arr("by0", [t[0][1] for t in triples]),
        _arr("bxm", [t[1][0] for t in triples]),
        _arr("bym", [t[1][1] for t in triples]),
        _arr("bx1", [t[2][0] for t in triples]),
        _arr("by1", [t[2][1] for t in triples]),
    ])

    # The very same witness runs both before the transaction commit and AFTER
    # StairsEditScope.Commit, on objects freshly re-fetched from the Document.  This
    # does not let a stale managed wrapper impersonate the live result.
    witness_cs = (
        f"Action<Autodesk.Revit.DB.Architecture.StairsLanding, "
        f"Autodesk.Revit.DB.Architecture.Stairs> __check_{s} = "
        f"(__landing_{s}, __stairs_{s}) =>\n"
        f"{{\n"
        f"    if (__landing_{s} == null)\n"
        f"    {{ __post.Add({_cs(oid + ': площадка не найдена при свежем чтении (identity)')}); return; }}\n"
        f"    if (__stairs_{s} == null)\n"
        f"        __post.Add({_cs(oid + ': лестница не найдена при свежем чтении (identity)')});\n"
        f"    try\n"
        f"    {{\n"
        f"        var __own_{s} = __landing_{s}.GetStairs();\n"
        f"        if (__stairs_{s} == null || __own_{s} == null || "
        f"__own_{s}.Id.ToString() != __stairs_{s}.Id.ToString())\n"
        f"            __post.Add({_cs(oid + ': площадка принадлежит не той лестнице (topology)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': владелец площадки нечитаем (topology)')}); }}\n"
        f"    bool __inSet_{s} = false;\n"
        f"    try\n"
        f"    {{\n"
        f"        if (__stairs_{s} != null)\n"
        f"            foreach (ElementId __li_{s} in __stairs_{s}.GetStairsLandings())\n"
        f"                if (__li_{s}.ToString() == __landing_{s}.Id.ToString()) "
        f"__inSet_{s} = true;\n"
        f"    }}\n"
        f"    catch {{ }}\n"
        f"    if (!__inSet_{s})\n"
        f"        __post.Add({_cs(oid + ': площадки нет в GetStairsLandings своей лестницы (topology)')});\n"
        f"    try {{ if (__landing_{s}.IsAutomaticLanding)\n"
        f"              __post.Add({_cs(oid + ': построена автоматическая площадка вместо эскизной (semantic)')}); }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': признак автоматической площадки нечитаем (semantic)')}); }}\n"
        f"    int __bCurves_{s} = 0;\n"
        f"    bool __bRead_{s} = true; bool __bStray_{s} = false;\n"
        f"    int[] __bHit_{s} = new int[{n_edges}];\n"
        f"    try\n"
        f"    {{\n"
        f"        foreach (Curve __bc_{s} in __landing_{s}.GetFootprintBoundary())\n"
        f"        {{\n"
        f"            __bCurves_{s}++;\n"
        f"            double __ax_{s} = MM(__bc_{s}.GetEndPoint(0).X);\n"
        f"            double __ay_{s} = MM(__bc_{s}.GetEndPoint(0).Y);\n"
        f"            double __zx_{s} = MM(__bc_{s}.GetEndPoint(1).X);\n"
        f"            double __zy_{s} = MM(__bc_{s}.GetEndPoint(1).Y);\n"
        f"            double __mx_{s} = MM(__bc_{s}.Evaluate(0.5, true).X);\n"
        f"            double __my_{s} = MM(__bc_{s}.Evaluate(0.5, true).Y);\n"
        f"            bool __bOne_{s} = false;\n"
        f"            for (int __bk_{s} = 0; __bk_{s} < {n_edges}; __bk_{s}++)\n"
        f"            {{\n"
        f"                bool __bFwd_{s} = Math.Abs(__ax_{s} - __bx0_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__ay_{s} - __by0_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zx_{s} - __bx1_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zy_{s} - __by1_{s}[__bk_{s}]) <= __dt_{s};\n"
        f"                bool __bRev_{s} = Math.Abs(__ax_{s} - __bx1_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__ay_{s} - __by1_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zx_{s} - __bx0_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__zy_{s} - __by0_{s}[__bk_{s}]) <= __dt_{s};\n"
        f"                if ((__bFwd_{s} || __bRev_{s})\n"
        f"                    && Math.Abs(__mx_{s} - __bxm_{s}[__bk_{s}]) <= __dt_{s}\n"
        f"                    && Math.Abs(__my_{s} - __bym_{s}[__bk_{s}]) <= __dt_{s})\n"
        f"                {{ __bHit_{s}[__bk_{s}]++; __bOne_{s} = true; break; }}\n"
        f"            }}\n"
        f"            if (!__bOne_{s}) __bStray_{s} = true;\n"
        f"        }}\n"
        f"    }}\n"
        f"    catch {{ __bRead_{s} = false; }}\n"
        f"    bool __bExact_{s} = true;\n"
        f"    for (int __bj_{s} = 0; __bj_{s} < {n_edges}; __bj_{s}++)\n"
        f"        if (__bHit_{s}[__bj_{s}] != 1) __bExact_{s} = false;\n"
        f"    if (!__bRead_{s})\n"
        f"        __post.Add({_cs(oid + ': граница площадки нечитаема — GetFootprintBoundary бросил (geometry)')});\n"
        f"    else if (__bCurves_{s} != {n_edges})\n"
        f"        __post.Add({_cs(oid + ': прочитано ')} + __bCurves_{s} + "
        f"{_cs(f' рёбер границы вместо {n_edges} (geometry)')});\n"
        f"    else if (__bStray_{s} || !__bExact_{s})\n"
        f"        __post.Add({_cs(oid + ': граница площадки не совпала с заданным контуром в плане (geometry)')});\n"
        f"    try\n"
        f"    {{\n"
        f"        double __gotE_{s} = MM(__landing_{s}.BaseElevation);\n"
        f"        if (Math.Abs(__gotE_{s} - __elevNorm_{s}) > __dt_{s})\n"
        f"            __post.Add({_cs(oid + ': отметка площадки не равна нормализованному кратному подступенка (geometry)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': отметка площадки нечитаема (geometry)')}); }}\n"
        f"}};\n")

    body = (
        f"{_AUTH_PREAMBLE}\n"
        f"// create_stairs_landing {cs_line_comment_fragment(oid)} — "
        f"sole-op program, StairsEditScope owns transactions\n"
        + pre_doc_guard
        + pre_identity_guard +
        # ── the host stair, BEFORE the edit scope ──────────────────────────
        f"Element __tg_{s} = doc.GetElement({_eid(tgt['value'], ver, oid)});\n"
        f"if (__tg_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"лестница не найдена (модель изменилась после grounding)\");\n"
        f"Autodesk.Revit.DB.Architecture.Stairs __st_{s} = "
        f"__tg_{s} as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"if (__st_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"указанный элемент — не лестница\");\n"
        # ── TOLERANCES AND BOUNDS — FROM REVIT'S OWN NUMBERS, BEFORE THE TRANSACTION ────
        f"double __rh_{s} = MM(__st_{s}.ActualRiserHeight);\n"
        f"if (!(__rh_{s} > 0.0) || Double.IsNaN(__rh_{s}) || Double.IsInfinity(__rh_{s}))\n"
        f"    return __Refuse({_cs(oid)}, \"у лестницы нечитаема высота подступенка "
        f"(ActualRiserHeight не является конечным положительным числом)\");\n"
        # The exact lower bound on the elevation: Autodesk requires «equal to or greater
        # than half of the riser height».  The registry bound (0) is weaker, and
        # deliberately so; the real one is set by THIS line, and it NAMES the measured
        # number, rather than sending the author off to the documentation.
        f"if ({_n(elev)} < __rh_{s} / 2.0)\n"
        f"    return __Refuse({_cs(oid)}, \"elevation_mm = {_n(elev)} мм ниже половины "
        f"высоты подступенка этой лестницы (\" + Math.Round(__rh_{s} / 2.0, 1) + \" мм) — "
        f"Revit такую площадку не принимает\");\n"
        f"double __dt_{s} = MM(doc.Application.VertexTolerance) + "
        f"{_n(C.EMIT_COORD_QUANTUM_MM)};\n"
        # THE VACUITY BAN IS A DEFINITION, NOT A MATTER OF TASTE: a tolerance that eats up
        # half of the shortest edge makes the boundary match
        # unfailable.  A check that cannot fail is worse than
        # no check at all, which is why there is a named refusal here, not a rubber stamp.
        f"if (2.0 * __dt_{s} >= {_n(min_edge)})\n"
        f"    return __Refuse({_cs(oid)}, \"выведенный допуск границы (\" + "
        f"Math.Round(__dt_{s}, 3) + \" мм) не меньше половины самого короткого ребра "
        f"контура (ребро {_n(round(min_edge, 2))} мм, половина "
        f"{_n(round(min_edge / 2.0, 2))} мм) — свидетель границы не смог бы "
        f"провалиться\");\n"
        # Revit rounds BaseElevation to a multiple of ActualRiserHeight. We do not
        # guess the direction of the hidden rounding: we accept only an author
        # value that is already exact, and otherwise we name the two neighbors.
        f"double __elevQ_{s} = {_n(elev)} / __rh_{s};\n"
        f"double __elevK_{s} = Math.Round(__elevQ_{s}, MidpointRounding.AwayFromZero);\n"
        f"if (__elevK_{s} < 1.0) __elevK_{s} = 1.0;\n"
        f"double __elevNorm_{s} = __elevK_{s} * __rh_{s};\n"
        f"double __elevLower_{s} = Math.Max(__rh_{s}, Math.Floor(__elevQ_{s}) * __rh_{s});\n"
        f"double __elevUpper_{s} = Math.Max(__rh_{s}, Math.Ceiling(__elevQ_{s}) * __rh_{s});\n"
        f"if (Math.Abs({_n(elev)} - __elevNorm_{s}) > __dt_{s})\n"
        f"    return __Refuse({_cs(oid)}, \"elevation_mm должна быть целым кратным "
        f"ActualRiserHeight; ближайшие кандидаты: \" + "
        f"Math.Round(__elevLower_{s}, 3) + \" мм и \" + "
        f"Math.Round(__elevUpper_{s}, 3) + \" мм\");\n"
        f"{author_arrays}\n"
        f"double __sbz_{s} = MM(__st_{s}.BaseElevation);\n"
        f"ElementId __stairsId_{s} = __st_{s}.Id;\n"
        + witness_cs +
        # ── the edit scope ─────────────────────────────────────────────
        f"var __ess = new StairsEditScope(doc, "
        f"{_cs(('KIR landing: ' + (intent or oid))[:60])});\n"
        f"if (!__ess.IsPermitted)\n"
        f"    return __Refuse({_cs(oid)}, \"StairsEditScope запрещён текущим состоянием документа\");\n"
        # Cancel is considered proven only after the active -> inactive transition.
        # A scope that is already inactive is not passed off as "successfully cancelled".
        f"Func<StairsEditScope, bool> __cancel_{s} = (__scope_{s}) =>\n"
        f"{{\n"
        f"    try\n"
        f"    {{\n"
        f"        if (!__scope_{s}.IsActive) return false;\n"
        f"        __scope_{s}.Cancel();\n"
        f"        return !__scope_{s}.IsActive;\n"
        f"    }}\n"
        f"    catch {{ return false; }}\n"
        f"}};\n"
        f"Func<Transaction, StairsEditScope, bool> __rollbackCancel_{s} = "
        f"(__transaction_{s}, __scope_{s}) =>\n"
        f"{{\n"
        f"    TransactionStatus __rollbackStatus_{s};\n"
        f"    try {{ __rollbackStatus_{s} = __transaction_{s}.RollBack(); }}\n"
        f"    catch {{ return false; }}\n"
        f"    if (__rollbackStatus_{s} != TransactionStatus.RolledBack) return false;\n"
        f"    return __cancel_{s}(__scope_{s});\n"
        f"}};\n"
        f"ElementId __sid_{s} = null;\n"
        f"ElementId __landingId_{s} = null;\n"
        f"Autodesk.Revit.DB.Architecture.StairsLanding __lg_{s} = null;\n"
        f"try\n"
        f"{{\n"
        f"    __sid_{s} = __ess.Start(__stairsId_{s});\n"
        # Start is documented as returning the same stairs id. A mismatch
        # is a violation of the API contract: the scope is torn down, but the result
        # does not turn into a safe refusal without a transactional rollback.
        f"    if (__sid_{s} == null || __sid_{s}.ToString() != __stairsId_{s}.ToString())\n"
        f"    {{\n"
        f"        if (!__cancel_{s}(__ess))\n"
        f"            throw new InvalidOperationException(\"StairsEditScope.Start target mismatch and cancellation is unproven\");\n"
        f"        throw new InvalidOperationException(\"StairsEditScope.Start returned a different stairs id\");\n"
        f"    }}\n"
        f"    using (Transaction __t = new Transaction(doc, \"KIR: stairs landing\"))\n"
        f"    {{\n"
        f"        var __startStatus = __t.Start();\n"
        f"        if (__startStatus != TransactionStatus.Started)\n"
        f"        {{\n"
        f"            if (!__cancel_{s}(__ess))\n"
        f"                throw new InvalidOperationException(\"transaction did not start and scope cancellation is unproven\");\n"
        f"            throw new InvalidOperationException(\"transaction start status: \" + __startStatus.ToString());\n"
        f"        }}\n"
        + failure_channel_reset_cs("__KirStairsFailures", "        ") +
        f"        var __fho = __t.GetFailureHandlingOptions();\n"
        f"        __fho.SetFailuresPreprocessor(new __KirStairsFailures());\n"
        f"        __fho.SetForcedModalHandling(false);\n"
        f"        __fho.SetClearAfterRollback(true);\n"
        f"        __t.SetFailureHandlingOptions(__fho);\n"
        + txn_doc_guard
        + txn_identity_guard
        + f"{loop_cs}\n"
        # Autodesk lists five different ArgumentException cases for this call
        # (the loop is not closed, a curve is not Line/Arc, the stair has no landing
        # type, …) plus an ArgumentOutOfRangeException on the elevation.  None of
        # them is predictable from the snapshot, and all of them must become a NAMED
        # refusal, not an "internal error".
        f"        try\n"
        f"        {{\n"
        f"            __lg_{s} = Autodesk.Revit.DB.Architecture.StairsLanding"
        f".CreateSketchedLanding(doc, __sid_{s}, __ol_{s}, U(__elevNorm_{s}));\n"
        f"        }}\n"
        f"        catch (Exception __ex_{s})\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateSketchedLanding failed and rollback/cancel is unproven\", __ex_{s});\n"
        f"            return __Refuse({_cs(oid)}, \"CreateSketchedLanding: \" + __ex_{s}.Message);\n"
        f"        }}\n"
        f"        if (__lg_{s} == null)\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateSketchedLanding returned null and rollback/cancel is unproven\");\n"
        f"            return __Refuse({_cs(oid)}, \"CreateSketchedLanding вернул null\");\n"
        f"        }}\n"
        f"        doc.Regenerate();\n"
        f"        " + _stamp_block(f"__lg_{s}", f"{stamp}:{oid}") + "\n"
        f"        __landingId_{s} = __lg_{s}.Id;\n"
        # ── witness inside the transaction: a violation rolls back everything ───────
        f"        __post.Clear();\n"
        f"        __check_{s}(__lg_{s}, __st_{s});\n"
        f"        if (__post.Count > 0)\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"postcondition failed and rollback/cancel is unproven\");\n"
        f"            var __er = new Dictionary<string, object>();\n"
        f"            __er[\"error\"] = \"postconditions_violated\";\n"
        f"            __er[\"violations\"] = new List<string>(__post);\n"
        f"            return __er;\n"
        f"        }}\n"
        f"        var __commitStatus = __t.Commit();\n"
        f"        if (__commitStatus != TransactionStatus.Committed)\n"
        f"        {{\n"
        f"            if (!__cancel_{s}(__ess))\n"
        f"                throw new InvalidOperationException(\"transaction commit was not Committed and scope cancellation is unproven\");\n"
        f"            throw new InvalidOperationException(\"transaction commit status: \" + __commitStatus.ToString()\n"
        f"                + (__KirStairsFailures.Seen.Count > 0 ? \" | Revit: \" + String.Join(\" ; \", __KirStairsFailures.Seen) : \"\"));\n"
        f"        }}\n"
        f"    }}\n"
        f"    __ess.Commit(new __KirStairsFailures());\n"
        f"    if (__ess.IsActive)\n"
        f"        throw new InvalidOperationException(\"StairsEditScope.Commit returned but scope is still active\");\n"
        f"}}\n"
        f"catch (Exception __scopeEx_{s})\n"
        f"{{\n"
        f"    bool __cleanup_{s} = true;\n"
        f"    try\n"
        f"    {{\n"
        f"        if (__ess.IsActive)\n"
        f"        {{ __ess.Cancel(); __cleanup_{s} = !__ess.IsActive; }}\n"
        f"    }}\n"
        f"    catch {{ __cleanup_{s} = false; }}\n"
        f"    if (!__cleanup_{s})\n"
        f"        throw new InvalidOperationException(\"stairs scope cleanup is unproven\", __scopeEx_{s});\n"
        f"    throw;\n"
        f"}}\n"
        # ── FRESH witness after closing the edit scope ──────────────
        f"var __freshSt_{s} = doc.GetElement(__stairsId_{s}) as "
        f"Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"var __freshLg_{s} = __landingId_{s} == null ? null : "
        f"doc.GetElement(__landingId_{s}) as "
        f"Autodesk.Revit.DB.Architecture.StairsLanding;\n"
        f"__post.Clear();\n"
        f"__check_{s}(__freshLg_{s}, __freshSt_{s});\n"
        f"// witness (fresh post-scope readback)\n"
        f"var __rb_{s} = new Dictionary<string, object>();\n"
        f"__rb_{s}[\"stairs_id\"] = __stairsId_{s}.ToString();\n"
        f"if (__landingId_{s} != null) __rb_{s}[\"id\"] = __landingId_{s}.ToString();\n"
        f"if (__freshLg_{s} != null)\n"
        f"{{\n"
        + _indent(_stamp_readback(f"__freshLg_{s}", f"__rb_{s}"), "    ") + "\n"
        f"    try {{ __rb_{s}[\"elevation_requested_mm\"] = {_n(elev)};\n"
        f"          __rb_{s}[\"elevation_normalized_mm\"] = Math.Round(__elevNorm_{s}, 3);\n"
        f"          __rb_{s}[\"elevation_built_mm\"] = "
        f"Math.Round(MM(__freshLg_{s}.BaseElevation), 3);\n"
        f"          __rb_{s}[\"riser_height_mm\"] = Math.Round(__rh_{s}, 2); }} catch {{ }}\n"
        f"    __rb_{s}[\"elevation_lower_candidate_mm\"] = Math.Round(__elevLower_{s}, 3);\n"
        f"    __rb_{s}[\"elevation_upper_candidate_mm\"] = Math.Round(__elevUpper_{s}, 3);\n"
        f"    try {{ __rb_{s}[\"thickness_mm\"] = "
        f"Math.Round(MM(__freshLg_{s}.Thickness), 2); }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"is_automatic\"] = __freshLg_{s}.IsAutomaticLanding; }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"boundary_tolerance_mm\"] = "
        f"Math.Round(__dt_{s}, 3); }} catch {{ }}\n"
        f"    try {{ var __rl_{s} = __freshSt_{s} == null ? null : "
        f"__freshSt_{s}.GetStairsLandings();\n"
        f"          __rb_{s}[\"landings\"] = __rl_{s} == null ? 0 : __rl_{s}.Count; }} catch {{ }}\n"
        f"}}\n"
        f"__results[{_cs(oid)}] = __rb_{s};\n"
        + failure_warnings_into_results_cs("__KirStairsFailures")
        + f"__results[\"ok\"] = true;\n"
        # After commit the effect has already happened. A violation here is
        # committed but unverified, not a false X004 «rolled back», and not a reason to retry.
        f"if (__post.Count > 0)\n"
        f"    __results[\"postcondition_violations\"] = new List<string>(__post);\n"
        f"return __results;\n"
        f"}}\n"
        f"\n"
        # THE SAME SUPPRESSION AS FOR `__KirMainFailures` AND THE RUN: we
        # suppress the warning so it does not pop up as a dialog and freeze
        # Revit's UI thread; a genuine ERROR is still handed to Revit. The
        # handler sits both on the transaction and on `StairsEditScope.Commit`
        # — the warning can surface even outside the transaction.
        + failure_preprocessor_cs("__KirStairsFailures")
        +         f"\n"
        f"private static class __KirPad\n"
        f"{{  // pad scope: the fixed wrapper footer closes __KirPad, UserCode, namespace"
    )
    return _with_program_helpers(body)
