"""stairs_run_emit — SECOND RUN OF AN ALREADY-STANDING STAIRCASE (stairs wave, 15.08.2026).

WHY THIS OPERATION EXISTS — A NUMBER TAKEN FROM A REAL BUILDING.
`LEN_AR_ME_R24`, the owner's residential building:

    total staircases                      19
    expressible in KIR before this wave    2   (10.5 %)
    NOT expressible                       17   (89.5 %)
    runs per staircase: 1r:2 · 2r:4 · 3r:2 · 4r:10 · 5r:1   — MODE IS FOUR RUNS
    61 runs · 40 landings · 522 railings across 19 staircases

`create_stairs` emits `Stairs.Create` plus EXACTLY ONE run
(`authoring.emit_stairs_program`), `create_stairs_landing` lands on an
already-standing staircase.  Run + landing were expressible with two
programs; run + landing + run was NOT, because the op adding a SECOND run was
missing from the registry.  A hole in the LANGUAGE, not in the documentation,
and it kept the residential building inexpressible for 89.5 %.

────────────────────────────────────────────────────────────────────────────
API MEASUREMENT (compiled against :52412, against real 2021-2026 builds,
15.08.2026; the arbiter is the compiler, not RevitAPI.xml, see CLAUDE.md on
SpatialElementTag)
────────────────────────────────────────────────────────────────────────────

  StairsRun.CreateStraightRun(Document, ElementId, Line,
             StairsRunJustification)                              → 6/6
  StairsRunJustification.Center / .Left / .Right                  → 6/6 each
  StairsRun.BaseElevation / .TopElevation / .Height                → 6/6
  StairsRun.GetStairs() / .GetStairsPath() / .ActualRunWidth      → 6/6
  Stairs.GetStairsRuns() / .BaseElevation / .ActualRiserHeight    → 6/6

RevitAPI.xml for `CreateStraightRun` (all six versions, verbatim):
  ArgumentException — «The stairsId is not a valid stairs element. -or- The
      input locationPath is not a bound line. -or- The input locationPath is
      not a valid location path line for straight run. -or- The locationPath
      is not valid line used as stairs path (probably it's too short).»
  InvalidOperationException — «The stairs element represented by stairsId is
      not in an active StairsEditScope.  New components cannot be added to it.»

────────────────────────────────────────────────────────────────────────────
WHY A SEPARATE OP, NOT A MULTI-VALUED OPERAND ON `create_stairs`
────────────────────────────────────────────────────────────────────────────
The fork is resolved by an API MEASUREMENT, not by taste.  `CreateStraightRun`
takes `stairsId` as its first argument — that is, it adds a run to an ALREADY
EXISTING staircase, and requires an active edit scope.  A "runs" arm on
`create_stairs` would describe only the case "the staircase is being created
right now" and would be INEXPRESSIBLE for the most common case of real work
— a staircase already standing in the document.  The shape of the API and
the shape of the task coincide here, and the coincidence is not accidental:
a run in Revit is a COMPONENT of the staircase, not its parameter.

A SOLO OP, AND THIS IS A MEASUREMENT, NOT SYMMETRY WITH THE LANDING.  The
`InvalidOperationException` phrase above is the very same one as for
`CreateSketchedLanding`: an edit scope is mandatory.  Revit does not open two
scopes at once («there already is a stairs edit mode active in the
document»), so the coexistence of two staircase ops is inexpressible BY
REVIT.  Hence `spec.SOLO_OPS`.

────────────────────────────────────────────────────────────────────────────
THE ELEVATION IS RELATIVE, AND THIS HAS TWO REASONS, NOT ONE
────────────────────────────────────────────────────────────────────────────
1. `CreateStraightRun` HAS NO elevation argument at all — it is carried by
   the Z of the `locationPath` points.  An absolute Z would require knowing
   `Stairs.BaseElevation` at COMPILE TIME, i.e. a live Revit where there is
   none.
2. The author thinks "the second run starts on the landing", i.e. FROM THE
   STAIRCASE.  The landing's elevation is built the very same way, and the
   same meaning is expressed the same way.

`BaseElevation` is read by C# at runtime; the grid of admissible elevations
is an integer multiple of THIS staircase's `ActualRiserHeight`, and a run
starting mid-riser gets a TYPED REFUSAL with the two nearest candidates,
rather than an exception.  The device and the rationale are the same as for
the landing.

🔴 THIS OP WAS NOT VERIFIED LIVE, AND THE REASON IS NAMED.  On 15.08.2026
`create_stairs` on the owner's real building committed and BLOCKED Revit's
flow with a modal window nobody could click; the owner dismissed the window
by hand.  The staircase incident, considered closed, is NOT closed for THIS
path, so the whole wave is offline: the registry, the emission, the
six-version gate, the golden. Live proof — a separate pass, after the modal
window is untangled. The `tool_doc` line UNPROVEN stands for exactly this
reason, not out of forgetfulness.
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _AUTH_PREAMBLE, _cs, _document_binding_guard, _eid,
    _element_identity_guard, _indent, _program_stamp, _safe,
    _stamp_block, _stamp_readback, _with_program_helpers,
)
from kir.diag import Diagnostic, KirRefusal, PLAN_SOLO_OP
from kir.emit_utils import (
    cs_line_comment_fragment,
    failure_channel_reset_cs,
    failure_preprocessor_cs,
    failure_warnings_into_results_cs,
)

#: An in-program reference on a solo op is unresolvable by construction — the
#: same code and the same rationale as for the landing: it is one fact («the
#: op owns its own transaction and is therefore solitary»), so it is one code.
RUN_SOLO_REF = PLAN_SOLO_OP

#: CLOSED REVIT ENUM -> MEMBER NAME, NOT A NUMBER.
#: This tree's canon directly requires emitting the enum MEMBER NAME in C#:
#: then the Revit assemblies become the authority (a typo fails to compile),
#: not our table.  Exactly one resident writes a bare number in the registry
#: — `WALL_LOCATION_LINE_ORDINALS`, and it is named in the canon as the sole
#: remaining one.  We are not adding a second.
JUSTIFICATION_MEMBERS: dict[str, str] = {
    "center": "Center",
    "left": "Left",
    "right": "Right",
}


def _n(value: float) -> str:
    """A number into a C# literal without losing digits (the same device as for the landing)."""
    return repr(float(value) + 0.0)


def emit_stairs_run_program(
    op: dict, ver: str, intent: str = "", *, stamp_scope: str = "", lineage: str = "",
    expected_document=None, expected_identities=None,
) -> str:
    """A separate template for a WHOLE program: a second run on its own staircase.

    The device mirrors `stairs_landing_emit.emit_stairs_landing_program`, and
    this is NOT a copy-paste for symmetry's sake, but one and the same Revit
    law: `StairsEditScope` owns its own transactions and does not nest inside
    a shared one.  What is shared is the shape of the edit scope (Start on an
    existing staircase, the double witness, `StairsEditScope.Commit`); what
    is its own is the factory call, parsing the run's axis, and the witness
    over the run's path.
    """
    oid = op["id"]
    s = _safe(oid)
    stamp = _program_stamp([op], stamp_scope, lineage)

    tgt = op["stairs"]
    if tgt.get("by") == "ref":
        raise KirRefusal([Diagnostic(
            code=RUN_SOLO_REF, op_id=oid, field_name="stairs",
            message_ru=("stairs: ref недопустим в соло-программе "
                        "create_stairs_run — предшествующих опов у неё нет "
                        "по построению; назовите element_id лестницы"))])

    p0 = op["p0_mm"]
    p1 = op["p1_mm"]
    elev = float(op["base_elevation_mm"])
    justification = JUSTIFICATION_MEMBERS[op.get("justification", "center")]

    pre_doc_guard = _document_binding_guard(expected_document, rollback="")
    pre_identity_guard = _element_identity_guard(
        expected_identities, ver, rollback="")
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
        symbol_prefix="__kirRunTxnBinding")
    txn_identity_guard = (_indent(txn_identity_guard_raw, "        ") + "\n"
                          if txn_identity_guard_raw else "")

    # THE WITNESS READS THE RESULT, NOT THE FACT OF THE CALL.  The same
    # double run as for the landing: inside the transaction (a violation
    # rolls back everything) and AFTER `StairsEditScope.Commit`, on objects
    # freshly re-read from the document — the old managed wrapper must not
    # impersonate the live result.
    #
    # Z IS NOT COMPARED along the run's path: Revit assigns it from the
    # staircase's base, and demanding an authored number from it would mean
    # chasing the witness after something Revit does not promise (exactly the
    # beam-level mistake recorded in the canon).  The run's elevation is
    # checked SEPARATELY, via its own `BaseElevation`.
    witness_cs = (
        f"Action<Autodesk.Revit.DB.Architecture.StairsRun, "
        f"Autodesk.Revit.DB.Architecture.Stairs> __check_{s} = "
        f"(__run_{s}, __stairs_{s}) =>\n"
        f"{{\n"
        f"    if (__run_{s} == null)\n"
        f"    {{ __post.Add({_cs(oid + ': марш не найден при свежем чтении (identity)')}); return; }}\n"
        f"    if (__stairs_{s} == null)\n"
        f"        __post.Add({_cs(oid + ': лестница не найдена при свежем чтении (identity)')});\n"
        f"    try\n"
        f"    {{\n"
        f"        var __own_{s} = __run_{s}.GetStairs();\n"
        f"        if (__stairs_{s} == null || __own_{s} == null || "
        f"__own_{s}.Id.ToString() != __stairs_{s}.Id.ToString())\n"
        f"            __post.Add({_cs(oid + ': марш принадлежит не той лестнице (topology)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': владелец марша нечитаем (topology)')}); }}\n"
        f"    bool __inSet_{s} = false;\n"
        f"    try\n"
        f"    {{\n"
        f"        if (__stairs_{s} != null)\n"
        f"            foreach (ElementId __ri_{s} in __stairs_{s}.GetStairsRuns())\n"
        f"                if (__ri_{s}.ToString() == __run_{s}.Id.ToString()) "
        f"__inSet_{s} = true;\n"
        f"    }}\n"
        f"    catch {{ }}\n"
        f"    if (!__inSet_{s})\n"
        f"        __post.Add({_cs(oid + ': марша нет в GetStairsRuns своей лестницы (topology)')});\n"
        # ── the run's axis in PLAN: endpoints, without Z ─────────────────────────────
        f"    bool __pathRead_{s} = false; bool __pathHit_{s} = false;\n"
        f"    try\n"
        f"    {{\n"
        f"        foreach (Curve __pc_{s} in __run_{s}.GetStairsPath())\n"
        f"        {{\n"
        f"            __pathRead_{s} = true;\n"
        f"            double __ax_{s} = MM(__pc_{s}.GetEndPoint(0).X);\n"
        f"            double __ay_{s} = MM(__pc_{s}.GetEndPoint(0).Y);\n"
        f"            double __zx_{s} = MM(__pc_{s}.GetEndPoint(1).X);\n"
        f"            double __zy_{s} = MM(__pc_{s}.GetEndPoint(1).Y);\n"
        f"            bool __fwd_{s} = Math.Abs(__ax_{s} - {_n(p0[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__ay_{s} - {_n(p0[1])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zx_{s} - {_n(p1[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zy_{s} - {_n(p1[1])}) <= __dt_{s};\n"
        f"            bool __rev_{s} = Math.Abs(__ax_{s} - {_n(p1[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__ay_{s} - {_n(p1[1])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zx_{s} - {_n(p0[0])}) <= __dt_{s}\n"
        f"                && Math.Abs(__zy_{s} - {_n(p0[1])}) <= __dt_{s};\n"
        f"            if (__fwd_{s} || __rev_{s}) __pathHit_{s} = true;\n"
        f"        }}\n"
        f"    }}\n"
        f"    catch {{ __pathRead_{s} = false; }}\n"
        f"    if (!__pathRead_{s})\n"
        f"        __post.Add({_cs(oid + ': путь марша нечитаем (geometry)')});\n"
        f"    else if (!__pathHit_{s})\n"
        f"        __post.Add({_cs(oid + ': ось марша в плане не совпала с заявленной (geometry)')});\n"
        # ── elevation of the run's bottom ──────────────────────────────────────────
        f"    try\n"
        f"    {{\n"
        # 🔴 ONE VALUE WAS BEING READ IN TWO FRAMES OF REFERENCE (30.08.2026,
        # audit finding F-271). The witness compared `StairsRun.BaseElevation`
        # against the ABSOLUTE sum `__sbz + __elevNorm`, while the receipt
        # puts the very same read value NEXT TO `base_elevation_normalized_mm`,
        # i.e. in the RELATIVE frame. Both cannot be right: on a staircase
        # with a non-zero base the numbers diverge by exactly `__sbz`, and if
        # the API is relative, then EVERY legitimate run was failing the
        # postcondition and being rolled back. Measured reach of the
        # finding: 15 buildings, 621 runs out of 1205.
        #
        # 🔴 WHAT I DO NOT KNOW AND DO NOT INVENT: which of the two frames is
        # correct — that is a question about the LIVE Revit API, and the
        # compiler only answers «the member exists» (the arbiter here is the
        # compiler, see the file's header). So the witness NO LONGER CHOOSES
        # the frame on Revit's behalf: a mismatch on BOTH counts as a
        # violation, and the matching frame IS NAMED in the receipt
        # (`base_elevation_frame`). The false rollback is removed, and the
        # answer to the API question will come from the VERY FIRST live run
        # — by measurement, not by guesswork.
        f"        double __built_{s} = MM(__run_{s}.BaseElevation);\n"
        f"        bool __relOk_{s} = "
        f"Math.Abs(__built_{s} - __elevNorm_{s}) <= __dt_{s};\n"
        f"        bool __absOk_{s} = "
        f"Math.Abs(__built_{s} - (__sbz_{s} + __elevNorm_{s})) <= __dt_{s};\n"
        f"        __frame_{s} = __relOk_{s} ? \"relative\" "
        f": (__absOk_{s} ? \"absolute\" : \"mismatch\");\n"
        f"        if (!__relOk_{s} && !__absOk_{s})\n"
        f"            __post.Add({_cs(oid + ': отметка низа марша не совпала с заявленной ни в относительной, ни в абсолютной рамке (geometry)')});\n"
        f"    }}\n"
        f"    catch {{ __post.Add({_cs(oid + ': отметка марша нечитаема (geometry)')}); }}\n"
        f"}};\n")

    body = (
        f"{_AUTH_PREAMBLE}\n"
        f"// create_stairs_run {cs_line_comment_fragment(oid)} — "
        f"sole-op program, StairsEditScope owns transactions\n"
        + pre_doc_guard + pre_identity_guard +
        # ── host staircase, BEFORE the edit scope ──────────────────────────
        f"Element __tg_{s} = doc.GetElement({_eid(tgt['value'], ver, oid)});\n"
        f"if (__tg_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"лестница не найдена (модель изменилась после grounding)\");\n"
        f"Autodesk.Revit.DB.Architecture.Stairs __st_{s} = "
        f"__tg_{s} as Autodesk.Revit.DB.Architecture.Stairs;\n"
        f"if (__st_{s} == null)\n"
        f"    return __Refuse({_cs(oid)}, \"указанный элемент — не лестница\");\n"
        # The tolerance is DERIVED from the document, not assigned by the
        # registry: the same device and the same reason as for the landing.
        f"double __dt_{s} = MM(doc.Application.VertexTolerance) + 0.5;\n"
        # THE GRID OF ELEVATIONS IS A LIVE QUANTITY OF THIS STAIRCASE, and
        # the refusal NAMES the nearest legal values.  A run starting
        # mid-riser is not a staircase; but the step cannot be invented at
        # compile time.
        f"double __rh_{s} = MM(__st_{s}.ActualRiserHeight);\n"
        f"if (!(__rh_{s} > 0.0))\n"
        f"    return __Refuse({_cs(oid)}, \"высота подступенка лестницы "
        f"нечитаема или ноль — отметку марша не к чему привязать\");\n"
        f"double __elevQ_{s} = {_n(elev)} / __rh_{s};\n"
        f"double __elevNorm_{s} = Math.Round(__elevQ_{s}) * __rh_{s};\n"
        f"double __elevLower_{s} = Math.Floor(__elevQ_{s}) * __rh_{s};\n"
        f"double __elevUpper_{s} = Math.Ceiling(__elevQ_{s}) * __rh_{s};\n"
        f"if (Math.Abs({_n(elev)} - __elevNorm_{s}) > __dt_{s})\n"
        f"    return __Refuse({_cs(oid)}, \"base_elevation_mm должна быть "
        f"целым кратным ActualRiserHeight; ближайшие кандидаты: \" + "
        f"Math.Round(__elevLower_{s}, 3) + \" мм и \" + "
        f"Math.Round(__elevUpper_{s}, 3) + \" мм\");\n"
        f"double __sbz_{s} = MM(__st_{s}.BaseElevation);\n"
        f"ElementId __stairsId_{s} = __st_{s}.Id;\n"
        # 🔴 DECLARED BEFORE THE LAMBDA AND BEFORE THE RECEIPT — both read
        # it, and C# only captures what is declared ABOVE the lambda
        # expression. The same lesson bought by the gate on F-257 an hour
        # earlier: scope decides, not textual proximity.
        f"string __frame_{s} = \"неизмерено\";\n"
        + witness_cs +
        # ── edit scope ─────────────────────────────────────────────
        f"var __ess = new StairsEditScope(doc, "
        f"{_cs(('KIR run: ' + (intent or oid))[:60])});\n"
        f"if (!__ess.IsPermitted)\n"
        f"    return __Refuse({_cs(oid)}, \"StairsEditScope запрещён текущим состоянием документа\");\n"
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
        f"ElementId __runId_{s} = null;\n"
        f"Autodesk.Revit.DB.Architecture.StairsRun __rn_{s} = null;\n"
        f"try\n"
        f"{{\n"
        f"    __sid_{s} = __ess.Start(__stairsId_{s});\n"
        f"    if (__sid_{s} == null || __sid_{s}.ToString() != __stairsId_{s}.ToString())\n"
        f"    {{\n"
        f"        if (!__cancel_{s}(__ess))\n"
        f"            throw new InvalidOperationException(\"StairsEditScope.Start target mismatch and cancellation is unproven\");\n"
        f"        throw new InvalidOperationException(\"StairsEditScope.Start returned a different stairs id\");\n"
        f"    }}\n"
        f"    using (Transaction __t = new Transaction(doc, \"KIR: stairs run\"))\n"
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
        + txn_doc_guard + txn_identity_guard +
        # The axis's Z is FROM THE STAIRCASE, not from the author: see the module's header.
        f"        Line __path_{s} = Line.CreateBound(\n"
        f"            new XYZ(U({_n(p0[0])}), U({_n(p0[1])}), "
        f"U(__sbz_{s} + __elevNorm_{s})),\n"
        f"            new XYZ(U({_n(p1[0])}), U({_n(p1[1])}), "
        f"U(__sbz_{s} + __elevNorm_{s})));\n"
        # Autodesk lists four different ArgumentExceptions for this call
        # (not a bound line, not a valid straight-run axis, too short) —
        # none of them is predictable from the snapshot, and all of them must
        # become a NAMED refusal, not an «internal error».
        f"        try\n"
        f"        {{\n"
        f"            __rn_{s} = Autodesk.Revit.DB.Architecture.StairsRun"
        f".CreateStraightRun(doc, __sid_{s}, __path_{s}, "
        f"Autodesk.Revit.DB.Architecture.StairsRunJustification.{justification});\n"
        f"        }}\n"
        f"        catch (Exception __ex_{s})\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateStraightRun failed and rollback/cancel is unproven\", __ex_{s});\n"
        f"            return __Refuse({_cs(oid)}, \"CreateStraightRun: \" + __ex_{s}.Message);\n"
        f"        }}\n"
        f"        if (__rn_{s} == null)\n"
        f"        {{\n"
        f"            if (!__rollbackCancel_{s}(__t, __ess))\n"
        f"                throw new InvalidOperationException(\"CreateStraightRun returned null and rollback/cancel is unproven\");\n"
        f"            return __Refuse({_cs(oid)}, \"CreateStraightRun вернул null\");\n"
        f"        }}\n"
        f"        doc.Regenerate();\n"
        f"        " + _stamp_block(f"__rn_{s}", f"{stamp}:{oid}") + "\n"
        f"        __runId_{s} = __rn_{s}.Id;\n"
        f"        __post.Clear();\n"
        f"        __check_{s}(__rn_{s}, __st_{s});\n"
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
        f"var __freshRn_{s} = __runId_{s} == null ? null : "
        f"doc.GetElement(__runId_{s}) as "
        f"Autodesk.Revit.DB.Architecture.StairsRun;\n"
        f"__post.Clear();\n"
        f"__check_{s}(__freshRn_{s}, __freshSt_{s});\n"
        f"// witness (fresh post-scope readback)\n"
        f"var __rb_{s} = new Dictionary<string, object>();\n"
        f"__rb_{s}[\"stairs_id\"] = __stairsId_{s}.ToString();\n"
        f"if (__runId_{s} != null) __rb_{s}[\"id\"] = __runId_{s}.ToString();\n"
        f"if (__freshRn_{s} != null)\n"
        f"{{\n"
        + _indent(_stamp_readback(f"__freshRn_{s}", f"__rb_{s}"), "    ") + "\n"
        f"    try {{ __rb_{s}[\"base_elevation_requested_mm\"] = {_n(elev)};\n"
        f"          __rb_{s}[\"base_elevation_normalized_mm\"] = Math.Round(__elevNorm_{s}, 3);\n"
        f"          __rb_{s}[\"base_elevation_built_mm\"] = "
        f"Math.Round(MM(__freshRn_{s}.BaseElevation), 3);\n"
        f"          __rb_{s}[\"riser_height_mm\"] = Math.Round(__rh_{s}, 2); }} catch {{ }}\n"
        # WHICH FRAME Revit returned `BaseElevation` in is a measured fact,
        # not our assumption. `mismatch` means «neither one», and then a
        # postcondition violation stands next to it (F-271).
        f"    __rb_{s}[\"base_elevation_frame\"] = __frame_{s};\n"
        f"    __rb_{s}[\"base_elevation_lower_candidate_mm\"] = Math.Round(__elevLower_{s}, 3);\n"
        f"    __rb_{s}[\"base_elevation_upper_candidate_mm\"] = Math.Round(__elevUpper_{s}, 3);\n"
        f"    try {{ __rb_{s}[\"top_elevation_mm\"] = "
        f"Math.Round(MM(__freshRn_{s}.TopElevation), 2); }} catch {{ }}\n"
        f"    try {{ __rb_{s}[\"run_width_mm\"] = "
        f"Math.Round(MM(__freshRn_{s}.ActualRunWidth), 2); }} catch {{ }}\n"
        f"    __rb_{s}[\"justification\"] = {_cs(justification)};\n"
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
        # THE SAME SUPPRESSION AS FOR THE RUN AND THE LANDING: we suppress
        # the warning so it does not pop up as a dialog and freeze Revit's UI
        # thread; a genuine ERROR is still handed to Revit. The handler sits
        # both on the transaction and on `StairsEditScope.Commit` — the
        # warning can surface even outside the transaction.
        + failure_preprocessor_cs("__KirStairsFailures")
        +         f"\n"
        f"private static class __KirPad\n"
        f"{{  // pad scope: the fixed wrapper footer closes __KirPad, UserCode, namespace"
    )

    return _with_program_helpers(body)
