"""KIR v1 compiler — query family (SPEC_V1 §4B, §5).

Stages for queries: parse -> typecheck -> emit. (No ground round-trip: the
kind table is static; query_inspect resolves its target IN the emitted C#
with explicit not_found/ambiguous results — fail-closed without an extra
bridge hop. No plan stage: queries are read-only, transaction-free.)

Emitted dialect: C# 7.3 (Revit 2021-2024 = .NET Framework 4.8 ceiling), which
compiles unchanged on .NET 8 (2025-2026). The emit API is per-version anyway
(emit_for_version) so the authoring family can diverge later.

Fail-closed everywhere: unknown op, unknown field, wrong type, out-of-bounds
number (schema bounds are documentation; THIS is the enforcement point,
SPEC 12.9), kind escape value -> typed Diagnostic list, never an exception.
"""
from __future__ import annotations

import difflib
import hashlib
import logging
import re
from collections import Counter

import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional, Sequence

from kir.revit_read_helpers import element_level_helpers_cs
from kir import faceref, geom as _geom, relate, spec
from kir.contracts import ElementIdentityProof
from kir.diag import (
    Diagnostic, KirRefusal,
    PARSE_NOT_OBJECT, PARSE_UNKNOWN_OP, PARSE_UNKNOWN_FIELD, PARSE_BAD_VERSION,
    PARSE_MISSING_FIELD, PARSE_DUP_ID, PARSE_EXCLUSIVE_FIELDS,
    GROUND_UNSUPPORTED_KIND, GROUND_BAD_SELECTOR,
    GROUND_MODEL_BINDING, TYPE_BAD_TYPE, TYPE_BAD_ENUM, TYPE_BOUNDS, PLAN_LIMIT,
    PLAN_OP_CONTRACT, PLAN_PHASE_SHAPE, PLAN_SOLO_OP,
    # 🔴 FIVE CODES THAT USED TO LIVE HERE AS BARE LITERALS (01.09.2026).
    # A bare literal is invisible to the collision guard — it looks for
    # "NAME = literal" pairs — and because of this `KIR-L004` meant TWO
    # different refusals for two months: a reference kind here and a
    # run's slope in `route_mep`. Names are taken from the registrar,
    # not written anew.
    PLAN_REF_ORDER, PLAN_REF_KIND, PLAN_BULK_MISMATCH,
    PLAN_HOST_MOVED_VERTICALLY, PLAN_REF_DELETED,
    PLAN_DESTRUCTIVE_UNCONFIRMED, INTERNAL_PANIC,
)
from kir.emit_utils import (ELEMENT_ID_MAX, cs_identifier_fragment,
                                 cs_line_comment_fragment, cs_string_literal)
from kir.midend import (
    LINEAGE_FORM,
    _valid_ground_marker,
    FieldOrigin,
    GroundedProgram,
    GroundingContext,
    NestedOpContract,
    OperationFamily,
    OpProvenance,
    PlanEncodingError,
    PlannedOp,
    PlannedProgram,
    ProgramFamily,
)
from kir.op_contract import OpContractError, contract_for

logger = logging.getLogger(__name__)

# 🔴 BUDGETS ALIGNED PER THE OWNER'S DIRECTIVE ON 18.08.2026: 1000
# EVERYWHERE.
#
# WHY. The unit of assertion per the constitution is the BUILDING, while
# the budget was permitting a room. And the costs were against us: a
# turn costs ~14 s fixed plus ~45 ms per op (measured 18.08), meaning an
# op is almost free while a turn is expensive — it pays to build with
# ONE large program, yet only a hundred ops were allowed.
#
# THE WHOLE CHAIN WAS RAISED, NOT THE FIRST NUMBER. Raising only the
# authored budget would have been decoration: the program would pass
# the author's check and then hit the post-macro ceiling of 320, and
# the builder `dsl.py` itself cut at 300 BEFORE any door at all —
# meaning the author could not physically assemble a program larger
# than 300 ops, no matter what the canon declared.
#
# 🔴 A SEAM WAS LEFT, AND THIS IS A DEPARTURE FROM "1000 EVERYWHERE" —
# NAMED, NOT SILENT.
#
# The first edition set 1000 for the internal one too. It was refuted
# by SOMEONE ELSE'S test (`test_a_script_may_exceed_the_authored_budget`),
# and the argument in its docstring outweighs literal execution: "a
# script that can do exactly twenty operations is strictly worse than
# twenty done by hand." The `program_py` door is valuable exactly for
# its MARGIN over the authored budget — equalizing them would zero out
# the door's purpose, not lift a limit.
#
# So: THE AUTHORED budget (what the model writes by hand in JSON) —
# 1000, as instructed. THE INTERNAL budget (reassembly and the scripted
# door's margin) — 10,000.
#
# 🔴 THE DEBT WAS CLOSED ON 21.08.2026: chunking of a direct turn is
# WIRED INTO the production door (`serving._drive_chunked_program`; the
# law of splitting is `kir/chunking.py`). A program that fits in the
# bridge's frame still travels as ONE transaction, byte for byte; one
# that does not fit travels as contiguous slices in authored order, and
# its atomicity is named in the receipt as `per_chunk`, not passed over
# in silence.
#
# THE DISCLOSURE CEILINGS ARE LEFT ABOVE ON PURPOSE. They protect not
# against large programs but against macro BLOAT: lowering them to
# 1000 would mean forbidding a macro for a 40-story building, that is,
# constraining the author more, not less.
# 🔴🔴 RAISED ON 20.08.2026 BY THE OWNER'S DECISION: 1000 -> 100,000.
# Verbatim: "expand it to a 100k cap, everywhere, and make sure this
# doesn't come up again." The previous ladder, 100 -> 300 -> 1000, is
# described below; this is the fourth step and the largest.
#
# WHAT THIS CHANGES IN SUBSTANCE. The authored budget stops being a
# design decision and becomes A GUARD AGAINST A RUNAWAY: 100,000 is not
# "this much fits," but "the program is never larger than this,
# meaning the loop has run away." The real limits are now further down
# the pipeline and physical: the size of the emitted C#, the bridge's
# frame, the Revit transaction's duration. Those are what should be
# named to the author, not a number.
#
# ⚠️ A MEASUREMENT THAT MUST STAND ALONGSIDE THIS: 1000 surface ops
# produce 147,099 lines and 10.2 MB of C# (20.08). Linearly that is 1
# GB at 100,000 — while the websocket frame is 16 MB. SO RAISING THE
# NUMBER DID NOT BY ITSELF GRANT THE CAPABILITY — the capability came
# from CHUNKING OF THE DIRECT TURN, wired into the door on 21.08.2026:
# programs of that size travel as slices of <=8 MB each, and the
# service's peak memory drops from 3723 MB to 250 MB on the same
# 100,000 ops. The transport wall that had nothing to name it is gone;
# the cost is named and there is exactly one — atomicity became
# `per_chunk`.
# THE LADDER MUST BE STRICTLY INCREASING, and the project's own test
# caught this right after the raise: `MAX_BULK_OPS > MAX_OPS_PER_PROGRAM`
# — the scripted door's margin, "the whole value of `program_py` is
# that the builder is wider than manual enumeration." Equalizing them
# would have zeroed out the door's purpose without my noticing.
MAX_OPS_PER_PROGRAM = 100_000   # author budget (BEFORE macro expansion)
MAX_BULK_OPS = 200_000          # internal batch AND headroom of the program_py door
MAX_VALIDATED_OPS = 400_000     # post-macro ceiling (anti-bloat, NOT the author's budget)

# TWO BUDGETS — AND A REFUSAL MUST NAME WHICH ONE IS EXHAUSTED.
#
# 🔴🔴 THE NUMBERS IN THIS BLOCK HAVE BEEN INVALID SINCE 18.08.2026. READ THIS
# NOTE FIRST. The block describes the 15.08 revision and carries 100, 300,
# and 320; the numbers in force are 100000, 200000, and 400000 — they are
# declared ABOVE, at the constants themselves, along with the argument for
# them.
#
# 🔴 THIS VERY NOTE HAS GONE STALE, AND THIS IS THE THIRD GENERATION OF ONE
# DEFECT (measured 25.08.2026). Until today it named 1000, 10000, and 22000
# as the numbers in force — a revision that no longer existed. That is, a
# retraction written against stale numbers went stale itself and misled the
# reader in exactly the way it stands against.
#
# The lesson is that a note is ALSO A CARRIER of a value, and the tree's
# general rule applies to it too: a value repeated in prose must either be
# generated or have a guard. The guard is in place:
# `tests/test_retraction_marker_names_live_numbers.py`.
# The numbers are left in NOT out of carelessness: the canon's rule says that
# what is retracted is called wrong, not erased, because it carries a
# pattern of form. Here the pattern is this: the argument AGAINST the raise
# was measured and remained valid, and the decision was made otherwise
# anyway — that is a legitimate outcome, and scrubbing the numbers would
# have erased, along with them, the only evidence that the argument was ever
# voiced.
#
# The note stands ABOVE the block, not below it, and that too is a rule
# bought on 18.08: a retraction the reader never reached is not a
# retraction. The numbers are written solid so that grep finds them BY
# NUMBER: a search by phrase catches a retracted WORDING, while an invalid
# NUMBER is caught only by searching for the number itself.
#
# There are two of them not by oversight, but because the inputs differ in
# nature:
#   * THE AUTHOR'S (MAX_OPS_PER_PROGRAM, then 100, now 1000) measures a
#     program WRITTEN by the model.
#
#     🔴 RAISED FROM 20 TO 100 BY THE OWNER'S DECISION ON 15.08.2026. The
#     earlier value stood not by oversight, and the argument against raising
#     it is recorded right here: 210 of 586 live refusals on 30.07 were this
#     very budget, and it worked as a signal that "the wrong form was
#     chosen" (repetition belongs in a macro, stages belong in separate
#     programs). The argument has NOT been retracted and remains valid; the
#     owner accepted it and decided otherwise anyway, because the product's
#     goal is authorship of the building, not protection against verbosity.
#
#     WHAT THE RAISE DOES NOT CHANGE, and this matters more than the number
#     itself:
#       * the post-macro ceiling `MAX_VALIDATED_OPS` (then 320, now 22000)
#         is untouched — it is the emitter's limit, not a policy, and 100 <
#         320 with room to spare;
#       * the FORM of the `program_py` enumeration budget was not raised and
#         is not raised now: a script that produced more than
#         `MAX_OPS_PER_PROGRAM` operations refuses with the same typed
#         refusal (`test_program_py_door`);
#       * "asking for bulk" from chat is still impossible BY CONSTRUCTION:
#         `handle_revit_ir` has no budget parameter (`test_op_budget_seam`).
#     That is, exactly one threshold was raised, and exactly on the public
#     door.
#   * THE INTERNAL one (MAX_BULK_OPS, then 300, now 10000) measures the
#     MATERIALIZER's CHUNK, which no one
#     wrote by hand: it is assembled from parsing a live model, where 6 343
#     elements is the norm, not the author's intent.
# Both are capped from above by ONE shared post-macro ceiling,
# MAX_VALIDATED_OPS — nobody raises it, ever: it is the emitter's limit, not
# a policy.
#
# Live measurement on 30.07 (Snowdon Towers): the parser cut at 250, the
# only live door measured with the author's budget of 20 — 6 343 elements
# cost 318 rounds instead of 26. A seam, not the language. That is why
# budget names are constants, not prose: a refusal that does not name the
# exhausted budget reads the same in both cases and steers the repair the
# wrong way.
BUDGET_AUTHORED = "authored"
BUDGET_INTERNAL_BULK = "internal_bulk"

def _incident_log_ref(value: Any) -> str:
    """Return a bounded digest of caller-controlled correlation input."""
    if not isinstance(value, str) or not value:
        return "-"
    digest = hashlib.sha256(
        value.encode("utf-8", errors="surrogatepass")
    ).hexdigest()
    return f"sha256:{digest[:16]}"


def _incident_revit_version_ref(value: Any) -> str:
    """Expose only canonical system-owned target tokens; hash every caller value."""
    if isinstance(value, str) and value in spec.REVIT_VERSIONS:
        return value
    return _incident_log_ref(value)


def _incident_input_type(value: Any) -> str:
    """Describe the public input shape without trusting a custom class name."""
    if isinstance(value, PlannedProgram):
        return "PlannedProgram"
    value_type = type(value)
    if value_type in (dict, list, tuple, str, int, float, bool, type(None)):
        return value_type.__name__
    return "other"


def pre_macro_budget(*, bulk: bool) -> tuple[str, int]:
    """The name and the value of the pre-macro budget are ONE point of truth.

    The pair "what it's called" / "how much it is" lives together so a
    refusal cannot name one budget and measure another."""
    return ((BUDGET_INTERNAL_BULK, MAX_BULK_OPS) if bulk
            else (BUDGET_AUTHORED, MAX_OPS_PER_PROGRAM))


@dataclass
class CompileOutput:
    ok: bool
    csharp: Optional[str] = None                 # emitted Execute-body (doc in scope)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    # 🔴 `per_version` REMOVED ON 04.09.2026 — A DECLARED FIELD THAT NOBODY
    # WROTE TO. It stood here as `dict[str, str] = field(default_factory=dict)`,
    # and not one line in the tree ever assigned to it: grep for `.per_version`
    # gave EXACTLY one hit — the declaration itself. The reader always got
    # `{}`.
    #
    # A measurement of an outside person's path (04.09, clean venv, package
    # from the network) caught the cost: the person compiled a house, saw
    # `out.per_version == {}`, and concluded that six versions had failed —
    # then went through the versions by hand. An empty dict reads as "it was
    # measured, nothing came of it," but there is nothing to measure here:
    # `compile_program` compiles ONE version, the one it was told to.
    #
    # The meaning of "per version" does exist, but for a DIFFERENT op: the
    # MCP door (`kir/mcp/server.py`) walks the versions itself and builds
    # its own `per_version` with a status and text for each. The field here
    # was a shadow of that output-side dict, and it does not walk versions.
    #
    # Removed, not filled in: filling it in would mean placing the same
    # 31 597 characters of C# a second time next to `csharp`. A missing
    # attribute is an honest `AttributeError`; an empty dict is a quiet
    # falsehood.
    # Immutable typed mid-end accepted by this compilation.  C# is merely one
    # lowering of this exact plan; acceptance/evidence bind to plan_digest.
    planned: Optional[PlannedProgram] = None
    # Immutable model-dependent child of ``planned``.  Legacy consumers keep
    # receiving detached ``grounded_ops`` below; this object is the evidence
    # authority for exact ground OUTPUT and cannot be changed through either
    # compatibility view.  It is not a ContextSnapshot identity/revision
    # witness; the current ground input has no such authoritative contract.
    grounded: Optional[GroundedProgram] = None
    # Any-Query invariant (SPEC §14): when the refusal is out-of-coverage rather
    # than malformed, handoff names the tail route so the caller falls through
    # to the recipe/wiki path instead of erroring at the user.
    handoff: Optional[dict] = None
    # RECEIPT OF A NAMED DEFAULT: choices that the COMPILER made, not the
    # program's author. A choice the caller cannot see is indistinguishable
    # from `.FirstOrDefault()` — and that is exactly how the C# arm silently
    # took 1 door type out of 62 (measured 02.08.2026). The echo of an
    # author's selector does not land here: there the author made the
    # decision, and there is nothing to report.
    grounding_report: list[dict] = field(default_factory=list)
    # GROUNDED VIEW OF THE LOWERING — exactly the dicts the emitter
    # assembled `csharp` from, and nothing else. Needed by ONE consumer: the
    # translation certificate (`translation_cert.certify_program`), which
    # checks witnesses STATICALLY and therefore must look at the very same
    # operation that went into the C# — otherwise it would be certifying a
    # neighboring program.
    #
    # THIS IS NOT THE PLAN. Acceptance and all evidence hang off
    # `planned.plan_digest`; this is a detached view of the lowering that no
    # one has the right to present as intent (the same caveat stands next to
    # `normed` inside `compile_program`). It is NOT part of `as_dict()`: the
    # receipt does not change by one byte from this field's existing.
    grounded_ops: list[dict] = field(default_factory=list)
    # REVIT TRANSACTION ISOLATION under which `csharp` was emitted:
    # `"atomic"` — the whole program in one transaction, one op's failure
    # rolls back its NEIGHBORS; `"per_op"` — each op in its own
    # SubTransaction, and a failure costs exactly its own op.
    #
    # THE NAME IS DELIBERATELY NOT `isolation`. This same tree already has
    # `serving._sandbox_receipt`, which reads `isolation` off the result of
    # the PYTHON SANDBOX (`namespaces`/`filesystem`/`network_probe`) — a
    # different subject under the same word. On 13.08.2026 this homonym
    # nearly produced the conclusion "isolation is already being recorded."
    # A MISSING FIELD STAYS SILENT, A HOMONYM ANSWERS — and is therefore
    # more dangerous.
    #
    # WHY IT TRAVELS ON FURTHER, INTO THE WITNESS ROW:
    # `tools/live_op_rates.py` counts four buckets, and one of them is
    # "collateral" (someone else's violation rolled back the transaction).
    # **Under `per_op` there is no such thing as collateral, BY
    # CONSTRUCTION.** As long as isolation is not recorded, the corpus mixes
    # two populations with different bucket semantics, and there is nothing
    # to separate them with. The field is not there out of curiosity:
    # without it, the main per-op rate instrument is interpretable only for
    # `atomic` rows, and which rows are `atomic` is unknown.
    txn_isolation: str = "atomic"

    #: TABLE OF INTENT UNITS from the program's envelope, as the author
    #: wrote it (`course.unit()`). The compiler does NOT INTERPRET it: it
    #: changes neither the emission, nor the plan, nor the lowering — it
    #: only rides along to the receipt, so that an observation about arity N
    #: can name the intent, not a list of ops.
    units: list = field(default_factory=list)

    def as_dict(self) -> dict:
        d = {"ok": self.ok, "csharp": self.csharp,
             "diagnostics": [x.as_dict() for x in self.diagnostics]}
        if self.planned is not None:
            d["plan_digest"] = self.planned.plan_digest
        if (self.ok and self.grounded is not None
                and self.grounded.planned.family is ProgramFamily.WRITE):
            d["ground_digest"] = self.grounded.ground_digest
            d["context_digest"] = self.grounded.context.context_digest
            d["context_execution_bound"] = (
                self.grounded.context.execution_bound)
            d["context_authoritative"] = (
                self.grounded.context.authoritative)
        if self.handoff:
            d["handoff"] = self.handoff
        if self.grounding_report:
            d["grounding_report"] = self.grounding_report
        if self.units:
            # 🔴 THIS IS WHERE THE INTENT USED TO BREAK OFF. An operation's
            # provenance rides as far as `PlannedOp.to_evidence_dict` and
            # gets signed with `plan_digest`, but `to_dict`/`to_ops` CUT IT
            # OFF, and nothing reached the outside, into the receipt: the
            # model wrote in a composite and got back a list of ops. The
            # unit table rides along in the response in full — it is small
            # (one line per unit) — and without it an observation about
            # arity N is addressed by the number `u0`, which means nothing
            # to the reader.
            d["units"] = self.units
        return d


# ── C# helpers emitted once per program (7.3-safe, read-only) ────────────────
# CONCATENATION IN PARENTHESES: the trailing `.strip("\n")` applies to THE
# WHOLE EXPRESSION, not to the last chunk. Without the parentheses, the
# leading newline of the first literal rode into the emission and got
# pinned by the fixtures — my own garbage, in bytes.
_PREAMBLE = (r"""
// KIR query program — generated; read-only by construction (no txn, no writes).
// 🔴 ТИП ИЗОБРАЖЕНИЯ ЦЕЛИКОМ, А НЕ ЕГО ИМЯ (S-07, 30.08.2026). Признак
// подложки обязан спрашивать РОД (`Source`) и САМ ФАЙЛ (`Path`), потому что имя
// типа редактируется пользователем и Ревит дописывает к нему суффиксы страницы
// («… .pdf - 1») и дубля («… .pdf (2)»). Возвращается `null`, если элемент не
// изображение — вызывающий обязан это проверить.
Func<Element, ImageType> __ImageTypeOf = (Element __e) =>
{
    try
    {
        var __tid = __e.GetTypeId();
        if (__tid == null || __tid == ElementId.InvalidElementId) return null;
        return doc.GetElement(__tid) as ImageType;
    }
    catch { return null; }
};
Func<Element, string> __TypeNameOf = (Element __e) =>
{
    try
    {
        var __tid = __e.GetTypeId();
        if (__tid == null || __tid == ElementId.InvalidElementId) return "";
        var __te = doc.GetElement(__tid);
        return (__te != null && __te.Name != null) ? __te.Name : "";
    }
    catch { return ""; }
};
""" + element_level_helpers_cs("doc") + r"""
Func<Element, string> __LevelNameOf = (Element __e) =>
{
    // 🔴 ОДИН СУДЬЯ УРОВНЯ НА ВСЁ ДЕРЕВО. До 25.08 здесь стояла СВОЯ цепочка
    // на четыре BuiltInParameter, и её комментарий утверждал «the SAME 4-BIP
    // fallback chain», тогда как авторитет держит СЕМЬ и ветвится иначе
    // (`__holdsLevel`: параметр обязан быть рода ElementId, а не просто
    // иметь значение). Разница видна на балке: копия останавливалась на
    // SCHEDULE_LEVEL_PARAM (HasValue=True, AsElementId=-1) и отдавала пустую
    // строку. Замер 03.08: 2367 балок, 116 лестниц, 21 ограждение с
    // level_id=null — запрос `where level_name=…` молча отбрасывал их все.
    // Теперь цепочка приходит из `revit_read_helpers`, как у экстрактора
    // и у приёмки; своей здесь нет и быть не может.
    var __le = __ElementLevel(__e);
    return (__le != null && __le.Name != null) ? __le.Name : "";
};
Func<Element, string> __NameOf = (Element __e) =>
{
    try { return __e.Name ?? ""; } catch { return ""; }
};
Func<Element, long> __IdOf = (Element __e) =>
{
    long __value;
    return (__e != null && long.TryParse(__e.Id.ToString(), out __value))
        ? __value : long.MaxValue;
};
""").strip("\n")


def _cs_str(s: str) -> str:
    """Return one C# string literal through the shared KIR boundary."""
    return cs_string_literal(s)


# ── parse + typecheck ────────────────────────────────────────────────────────

def _fail(diags: list, **kw) -> None:
    diags.append(Diagnostic(**kw))


def _unknown_field_ru(op_name: str, field_name: str, known: set) -> str:
    """KIR-P003 on the JSON door now begins to name the NEXT TURN, not just the reason.

    THE MEASUREMENT THAT BOUGHT THIS (a live turn of the owner's,
    16.08.2026, a flash model). In ONE turn two refusals landed side by
    side, and they behaved in OPPOSITE ways:

      * `KIR-T002` on `create_roof.slopes` — «slopes без единого угла — это
        плоская крыша, просто не задавай поле». The model sent back a
        corrected program in FOUR SECONDS (10:45:45 -> 10:45:49);
      * `KIR-P003` on `create_door` — «неизвестное поле». The turn DIED.

    The difference is exactly one thing: the first text carries the next
    turn, the second — the reason.

    WHY NOT THE HANDWRITTEN REFERENCE THAT WAS REQUESTED. A handwritten list
    of fields will drift out of sync with the registry on the very first
    new operation, and it will drift SILENTLY — in this tree, EVERY
    handwritten list has drifted, and NOT ONE generated one has. That is why
    the next turn is DERIVED: slot names, their kinds, bounds, and defaults
    are printed by `dsl._call_form` DIRECTLY FROM THE REGISTRY.

    WHY IT CALLS SOMEONE ELSE'S GENERATOR INSTEAD OF WRITING ITS OWN.
    `_call_form` has already been bought by a measurement on a WEAK model
    (04.08: 13 refusals out of 27 were a bare `TypeError`, and the model
    learned the signature ONE BIT AT A TIME, eleven turns in a row). A
    second copy of the same text here would be a second opinion on the op's
    shape, and it would diverge from the first exactly when both get read
    back to back.

    THE IMPORT IS LOCAL ON PURPOSE: `dsl` imports `compiler` (`dsl.py:67`),
    a top-level import would close a cycle. The path is cold — it is the
    refusal branch.
    """
    from kir.dsl import _call_form  # local: cycle, see the docstring

    near = difflib.get_close_matches(field_name, sorted(known), n=2, cutoff=0.6)
    head = f"неизвестное поле {field_name!r} у {op_name}"
    if near:
        head += f". Похоже на {', '.join(repr(n) for n in near)}"
    try:
        form = _call_form(spec.OPS[op_name])
    except Exception:  # noqa: BLE001 — help text has no right to cost a refusal
        return head + ". СЛЕДУЮЩИЙ ХОД: убери поле — у этого опа его нет."
    return (
        f"{head}.\nВСЕ слоты этого опа — из реестра, других нет:\n{form}\n"
        f"СЛЕДУЮЩИЙ ХОД: убери лишнее поле либо возьми имя из списка выше "
        f"(размеры почти везде идут с суффиксом `_mm`), и СРАЗУ сверь "
        f"остальные слоты — они все перечислены здесь, один ход вместо "
        f"одного слота за ход.")


def _check_filters(where: Any, i: int, oid: str, diags: list,
                   op_kind: Optional[str] = None) -> dict:
    if where is None:
        return {}
    if not isinstance(where, dict):
        _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="where",
              expected="object", got=type(where).__name__,
              message_ru="where должен быть объектом {фильтр: значение}")
        return {}
    out = {}
    kind = op_kind
    for k, v in where.items():
        fs = spec.FILTERS.get(k)
        if fs is None:
            _fail(diags, code=PARSE_UNKNOWN_FIELD, op_index=i, op_id=oid, field_name=f"where.{k}",
                  candidates=sorted(spec.FILTERS), message_ru=f"неизвестный фильтр '{k}'")
        elif fs["type"] is bool and not isinstance(v, bool):
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=f"where.{k}",
                  expected="bool", got=type(v).__name__,
                  message_ru=f"фильтр '{k}' — true/false")
        elif fs["type"] is str and (isinstance(v, bool) or not isinstance(v, str)):
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=f"where.{k}",
                  expected="str", got=type(v).__name__,
                  message_ru=f"фильтр '{k}' должен быть строкой")
        elif fs.get("kinds") and kind is not None and kind not in fs["kinds"]:
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name=f"where.{k}",
                  expected=list(fs["kinds"]), got=kind,
                  message_ru=f"фильтр '{k}' применим только к {list(fs['kinds'])}")
        else:
            out[k] = v
    return out


# ═════════════════════════════════════════════════════════════════════════
# KIND NAME: A RESOLUTION LADDER AND A REFUSAL THAT NAMES THE NEIGHBOR
#
# THE MEASUREMENT THIS GREW OUT OF (14.08.2026, `data/telemetry/
# kir_rejections.jsonl`, 1558 lines / 314 authorship attempts). The
# "unknown kind" refusal — 28.3% OF ATTEMPTS, the second-largest class. But
# breaking down WHAT exactly was being asked for showed that this is
# mostly NOT a missing capability:
#
#   kind exists under a DIFFERENT SPELLING   42 lines   railings/railing,
#                                                        structural framing/
#                                                        structural_framing,
#                                                        levels/level, cable trays
#   kind exists EXACTLY                       8 lines   (fossils: asked
#                                                        before the kind
#                                                        existed)
#   kind does not exist at all               59 lines   incl. Russian names
#
# TWO HALVES OF THE FIX, AND BOTH ARE MANDATORY.
#
# 1. THE LADDER. Exact name -> the SINGLE match of the canonical form
#    (case, spaces/dots/hyphens -> underscore, plural) -> refusal. This is
#    NOT a guess and not a second dictionary: it is the same set, closed,
#    and literally the same technique that `ground.py` already uses to
#    resolve `by=name` ("exact match after trim; if none — ONE
#    case-insensitive match"). The resolution is VISIBLE to the author
#    without a separate receipt: the emission puts
#    `__r["kind"] = "<resolved kind>"` into the request's response, i.e.,
#    the choice is presented right where the result is.
#
# 2. THE REFUSAL NAMES THE NEIGHBOR, NOT THE LIST. `candidates` still
#    carries the WHOLE closed set — narrowing it would take away from the
#    model the very thing it repairs itself with — but the refusal text now
#    points at something specific:
#      * `column` -> «уточни: column_architectural | column_structural»
#        (a live refusal, most recently 14.08: in Revit, the CATEGORY
#        decides a column's kind, and it cannot be guessed on the author's
#        behalf — see KINDS, where they are deliberately kept apart);
#      * `wall_type` -> «это ПУЛ ТИПОВ; типы спрашивают
#        query_types(pool=…)» (a live refusal from 14.08: the ladder was
#        confused, not the name);
#      * otherwise — the nearest matches by spelling, not 51 names in a
#        row.
# ═════════════════════════════════════════════════════════════════════════


def _canon_kind(raw: str) -> str:
    """The canonical form of a kind name — ONLY for comparison, never for storage.

    The plural is stripped as the LAST step, because `levels` and `level`
    are one name typed two ways, not two kinds.
    """
    text = re.sub(r"[\s.\-]+", "_", raw.strip().lower())
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:-1] if text.endswith("s") else text


def _kind_canon_index() -> dict[str, list[str]]:
    """Canonical form -> the kinds that reduce to it.

    A list, not a single name: a collision must be VISIBLE and must refuse,
    rather than picking the first one. There are no empty lists here by
    construction — the index is built from the table itself.
    """
    index: dict[str, list[str]] = {}
    for name in spec.KINDS:
        index.setdefault(_canon_kind(name), []).append(name)
    return {key: sorted(value) for key, value in index.items()}


def _kind_hint(raw: str) -> str:
    """What to end the refusal with: a pointer to something specific, not a list."""
    canon = _canon_kind(raw)
    family = sorted(n for n in spec.KINDS if _canon_kind(n).startswith(canon + "_"))
    if family:
        return (f" — вид уточняется: {' | '.join(family)}. "
                f"Общего вида «{raw}» нет намеренно: выбрать за автора нельзя")
    pools = set(spec.OPS["query_types"].params[0].choices)
    if raw.strip() in pools or raw.strip() + "s" in pools:
        return (f" — «{raw}» это ПУЛ ТИПОВ, а не вид элемента. Каталог типов "
                f"спрашивают `query_types(pool=…)`; `kind` перечисляет "
                f"построенные элементы")
    near = difflib.get_close_matches(canon, sorted(spec.KINDS), n=3, cutoff=0.6)
    if near:
        return f" — ближайшие: {', '.join(near)}"
    # 🔴 THE EMPTINESS HERE WAS A HOLE, AND THE MEASUREMENT NAMED IT. All
    # three branches above look for a LATIN neighbor: both `_canon_kind` and
    # `get_close_matches` compare against `spec.KINDS`, where the names are
    # in Latin script. The user here writes in Russian, and the model
    # follows suit, so `kind='стенка'` gives NOT A SINGLE match: the
    # refusal came out as exactly «неизвестный kind 'стенка'», three words.
    # In the production corpus, `KIR-G001` — 32 live refusals, the fourth
    # most frequent.
    #
    # This does not violate the "something specific instead of a list"
    # decision (docstring above): that decision says WHAT to print when
    # something specific EXISTS. When it doesn't, the choice is not between
    # a list and a pointer, but between a list and SILENCE — and a silent
    # refusal kills the turn (measured 16.08: `KIR-T002` with a named next
    # turn produced a fix in 4 s, `KIR-P003` without one — the turn died).
    #
    # The list is CLOSED and is printed IN FULL (53 names, 662 characters):
    # truncating it would bring back the same disease — the model cannot
    # know whether the name it needs is hiding behind the ellipsis, and
    # will spend a turn checking.
    return (f" — ни одно имя закрытой таблицы не похоже. ВСЕ виды, других "
            f"нет: {', '.join(sorted(spec.KINDS))}. СЛЕДУЮЩИЙ ХОД: возьми имя "
            f"из списка; вида «прочее» нет намеренно, выбрать за автора нельзя")


def _pool_hint(raw: object) -> str:
    """Refusal by pool name: the NEIGHBOR and the next turn instead of thirty-five names.

    🔴 A NIGHT-BENCH MEASUREMENT FROM 16.08.2026, AND IT DISPROVED THE
    DIRECTOR'S EXPECTATION. The hypothesis was: "the refusal that TEACHES is
    the one that ENUMERATES what's allowed." The production corpus
    (`kir_rejections.jsonl`, 1959 lines, 295 in night windows) shows the
    opposite: enumerating refusals repeat within the same turn in **51.4%**
    of cases, against **29.5%** for refusals that name only the kind.
    `KIR-T003 query_types.pool` — the fourth most costly: 24 refusals, 11
    repeats, and its text printed ALL 35 names (691 characters) without a
    single word about what to do.

    A long closed list does not teach: the model already knows WHAT it
    needs, and cannot match its intent against a dictionary. So the same
    ladder as `_kind_hint`'s works here: first the NEIGHBOR, and only on a
    complete miss — the whole list, because then the choice is between the
    list and SILENCE, and a silent refusal kills the turn.

    And the mirror that was missing: `_kind_hint` can say «это ПУЛ ТИПОВ,
    а не вид», but there was no branch the other way — someone asking
    `pool='walls'` got a list. The pair must exist in both directions.
    """
    choices = sorted(spec.OPS["query_types"].params[0].choices)
    whole = (f" ВСЕ пулы, других нет: {', '.join(choices)}. "
             f"СЛЕДУЮЩИЙ ХОД: возьми имя из списка")
    if not isinstance(raw, str) or not raw.strip():
        return "поле не написано." + whole
    canon = _canon_kind(raw)
    family = [c for c in choices if _canon_kind(c).startswith(canon + "_")]
    if family:
        # Asked by KIND («walls»), but the type pool is called «wall_types».
        return (f"«{raw}» — это вид элемента, а пул типов зовётся иначе. "
                f"Ближайшие: {' | '.join(family)}. СЛЕДУЮЩИЙ ХОД: возьми "
                f"оттуда; построенные элементы перечисляет query_count(kind=…)")
    near = difflib.get_close_matches(canon, [_canon_kind(c) for c in choices],
                                     n=3, cutoff=0.6)
    if near:
        back = [c for c in choices if _canon_kind(c) in set(near)]
        return (f"«{raw}» нет среди пулов. Ближайшие: {' | '.join(back)}. "
                f"СЛЕДУЮЩИЙ ХОД: возьми одно из них")
    return f"«{raw}» нет среди пулов." + whole


def _check_kind(op: dict, i: int, oid: str, diags: list) -> Optional[str]:
    kind = op.get("kind")
    if kind == spec.KIND_ESCAPE:
        # Escape enum (SPEC 12.8): typed handoff to the recipe path, not a guess.
        _fail(diags, code=GROUND_UNSUPPORTED_KIND, op_index=i, op_id=oid, field_name="kind",
              got=spec.KIND_ESCAPE, candidates=sorted(spec.KINDS),
              message_ru="kind='other' — вне закрытой таблицы; маршрут: recipe/вики-путь")
        return None
    if isinstance(kind, str):
        if kind in spec.KINDS:
            return kind
        matches = _kind_canon_index().get(_canon_kind(kind), ())
        if len(matches) == 1:
            # The same ladder as `ground.by=name`'s: a single match within
            # a CLOSED set is the same name typed differently, not a choice
            # between two.
            #
            # 🔴 A DEBT NAMED ON 15.08.2026, NOT DISCOVERED LATER. This
            # branch CORRECTS the author's spelling and says NOTHING about
            # it: no diagnostics, no line in the receipt. By this tree's
            # law, «a choice the caller cannot see is a `.FirstOrDefault()`
            # with a good reputation», and that is exactly why `ground` must
            # print `grounding_report`, and a named default — `runner_up`.
            #
            # Why it isn't fixed here: parsing has no NON-REFUSAL diagnostic
            # channel — `_fail` raises a refusal, and correcting a spelling
            # is not a refusal. The channel is opened in a separate wave;
            # until then the fact of the correction is visible only from
            # the mismatch between `kind` in the input and in the
            # normalized program.
            #
            # The measurement that recorded this debt: `'Wall '` and
            # `'WALL'` are folded together silently
            # (`tests/test_any_query.py`), `'wall​'` is not, because `\s`
            # does not strip zero-width characters. That is, the ladder is
            # NOT all-consuming, and that is its strength; the silence is
            # its weakness.
            return matches[0]
    if not isinstance(kind, str):
        # 🔴 THE MOST FREQUENT CASE WAS THE MOST SILENT. The entire name
        # resolution ladder and the entire closed list hung on
        # `isinstance(kind, str)`, meaning they worked when the author made
        # a TYPO, and stayed silent when the author SIMPLY DID NOT WRITE the
        # field. The refusal came out as exactly «неизвестный kind None» —
        # three words, no reason, no next turn.
        #
        # A measurement on 16.08.2026 of the production corpus
        # (`kir_rejections.jsonl`, 1959 lines, 295 of them in the
        # night-bench windows): `KIR-G001 count.kind` — FIRST by inability
        # to teach, 16 repeats of the same refusal within one turn, and 11
        # of 21 night refusals of this kind carry exactly `kind None`. A
        # refusal without a next turn kills the turn outright; a refusal
        # with one fixes the program in 4 seconds (measured the same day).
        missing = "kind" not in op
        _fail(diags, code=GROUND_UNSUPPORTED_KIND, op_index=i, op_id=oid,
              field_name="kind", got=kind, candidates=sorted(spec.KINDS),
              message_ru=(
                  ("поле kind не написано" if missing else
                   f"kind должен быть строкой, получено {type(kind).__name__}")
                  + f". ВСЕ виды, других нет: {', '.join(sorted(spec.KINDS))}."
                  + " СЛЕДУЮЩИЙ ХОД: возьми имя из списка; вида «прочее» нет"
                    " намеренно, выбрать за автора нельзя"))
        return None
    _fail(diags, code=GROUND_UNSUPPORTED_KIND, op_index=i, op_id=oid, field_name="kind",
          got=kind, candidates=sorted(spec.KINDS),
          message_ru=f"неизвестный kind {kind!r}" + _kind_hint(kind))
    return None


def _validate_op(op: Any, i: int, diags: list) -> Optional[dict]:
    """Returns a normalized op dict or None (diags appended)."""
    if not isinstance(op, dict):
        _fail(diags, code=PARSE_NOT_OBJECT, op_index=i, message_ru="op должен быть объектом")
        return None
    name = op.get("op")
    raw_oid = op.get("id", None)
    oid = f"q{i}"
    if "id" in op:
        if not isinstance(raw_oid, str):
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, field_name="id",
                  expected="string", got=type(raw_oid).__name__,
                  message_ru="id опа должен быть строкой")
        elif not (1 <= len(raw_oid) <= 64):
            _fail(diags, code=TYPE_BOUNDS, op_index=i, field_name="id",
                  expected="1..64 символа", got=len(raw_oid),
                  message_ru="id опа должен содержать 1..64 символа")
        # 🔴 AN ID THAT CANNOT BE CALLED A REFERENCE (30.08.2026, finding
        # F-022). The reference path normalizes the value with `.strip()`
        # (`authoring_validation.py` and five more places in the same
        # file), but id intake does not. Two measures of the same name
        # diverged, and that produced TWO outcomes, the second of which is
        # worse than the first:
        #   1. `{"by":"ref","value":<the same id>}` refused with KIR-L003,
        #      and named the ALREADY-TRIMMED value (`got='W1'` for the
        #      author's `' W1 '`), i.e. hiding its own cause;
        #   2. if the program has a NEIGHBORING op whose id equals the
        #      trimmed value, the reference SILENTLY landed on it. Measured
        #      30.08: a program made of `'W1'` (a wall at x=0) and `' W1'`
        #      (a wall at x=20000) gives `ok=True`, 0 diagnostics, and in
        #      the C# the mark is bound to `__el_W1` — twenty meters off,
        #      silently, without a single word.
        # What counts as whitespace here is exactly what `str.strip()`
        # strips: an ordinary space, \t, \n, NBSP U+00A0, narrow U+202F,
        # ideographic U+3000. A homegrown list would have diverged from it
        # on the very first Python patch — the measure is taken from the
        # very thing that applies it.
        # The id cannot be trimmed ON THE AUTHOR'S BEHALF: two legitimate
        # DIFFERENT ids would become one, and we, not the author, would be
        # deciding which one is real. Hence a REFUSAL, and it names the
        # next turn.
        elif raw_oid != raw_oid.strip():
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, field_name="id",
                  expected=raw_oid.strip(), got=raw_oid,
                  message_ru=(
                      f"id опа {raw_oid!r} начинается или кончается пробельным "
                      f"символом, а ссылка на оп ({{'by': 'ref', 'value': ...}}) "
                      f"такие символы срезает — на этот оп нельзя сослаться, и "
                      f"хуже: ссылка молча найдёт СОСЕДНИЙ оп с id "
                      f"{raw_oid.strip()!r}, если он есть. СЛЕДУЮЩИЙ ХОД: "
                      f"убрать пробелы по краям, id={raw_oid.strip()!r}. "
                      f"Внутри id пробелы законны и не трогаются."))
        elif raw_oid in spec.PROGRAM_RESULT_METADATA_KEYS:
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, field_name="id",
                  got=raw_oid, expected="operation id outside program result metadata",
                  message_ru=(f"id опа {raw_oid!r} занят метаданными результата программы; "
                              "выбери другое id, иначе readback элемента будет перезаписан"))
        else:
            oid = raw_oid
    if not isinstance(name, str) or name not in spec.OPS:
        # 🔴 THE KNOWLEDGE LIVED IN THE FIELD, THE TEXT ABOUT IT WAS SILENT
        # (23.08.2026). `candidates` was filled with ALL the language's
        # names, while the message was «неизвестный op 'x'» — and the
        # model, reading the text, did not recognize a single name. The
        # muteness measurement (`tools/refusal_muteness.py`) named this
        # code twice in one probe out of forty-seven: "the knowledge field
        # is filled, and message_ru says not a word about it" and "print
        # candidates as a list."
        #
        # THE NEAREST MATCH IS PRINTED, NOT THE WHOLE LIST. There are 79
        # names; dumped as a wall of text they would cost the turn as much
        # as the answer itself, and would drown out the reason. The full
        # list stays in the `candidates` field and is obtained by calling
        # `op_names()` — this is stated in words, not implied.
        near = difflib.get_close_matches(name if isinstance(name, str) else "",
                                         sorted(spec.OPS), n=5, cutoff=0.0)
        # field_name="op" (25.08.2026, measured by the mission
        # instrument): the field with the wrong value is the ENVELOPE's
        # `op`, not the payload. It used to be silent here, and the
        # instrument used to read it as "there is no address at all," even
        # though the address was known from the first line
        # (`op.get("op")` already held a bad value) — it just wasn't
        # named. `expected` carries the nearest neighbors: that is the
        # FORM itself ("what to coerce to" — one of these names), not just
        # the message text.
        _fail(diags, code=PARSE_UNKNOWN_OP, op_index=i, op_id=oid,
              field_name="op", got=name, expected=", ".join(near) or None,
              candidates=sorted(spec.OPS),
              message_ru=(f"неизвестный op {name!r}. Ближайшие по написанию: "
                          f"{', '.join(near)}. СЛЕДУЮЩИЙ ХОД: возьми имя "
                          f"отсюда либо спроси весь перечень — `op_names()`, "
                          f"всего имён {len(spec.OPS)}"))
        return None
    # Synthetic fields are STRIPPED, not accepted: see spec.SYNTHETIC_FIELDS
    # (there — why they are specifically stripped, and why the silence here
    # hides nothing). We strip them ONLY on owner ops: `__host_wall__` on
    # `create_wall` belongs to nobody, and refusing it is still correct.
    stripped = {k for k, owners in spec.SYNTHETIC_FIELDS.items()
                if k in op and name in owners}
    if stripped:
        op = {k: v for k, v in op.items() if k not in stripped}
    # spec.ENVELOPE_FIELDS (not a hand-written {"op","id"}): one source for
    # "what is addressable in an op at all," shared with the mission
    # instrument (registry_base.py, the comment next to ENVELOPE_FIELDS).
    known = spec.ENVELOPE_FIELDS | {p.name for p in spec.OPS[name].params}
    for k in op:
        if k not in known:
            _fail(diags, code=PARSE_UNKNOWN_FIELD, op_index=i, op_id=oid, field_name=k,
                  candidates=sorted(known),
                  message_ru=_unknown_field_ru(name, k, known))
    if spec.OPS[name].family in spec.WRITE_FAMILIES:
        from kir import authoring
        return authoring.validate(op, name, i, oid, diags)
    norm: dict[str, Any] = {"op": name, "id": oid}

    if name in ("query_count", "query_list"):
        kind = _check_kind(op, i, oid, diags)
        if kind:
            norm["kind"] = kind
        norm["where"] = _check_filters(op.get("where"), i, oid, diags, op_kind=kind)

    if name == "query_count":
        group_by = op.get("group_by")
        if group_by is not None:
            choices = next(p.choices for p in spec.OPS["query_count"].params
                           if p.name == "group_by")
            if not isinstance(group_by, str) or group_by not in choices:
                _fail(diags, code=TYPE_BAD_ENUM, op_index=i, op_id=oid, field_name="group_by",
                      expected=sorted(choices), got=group_by,
                      message_ru=f"group_by должен быть одним из {sorted(choices)}")
            else:
                norm["group_by"] = group_by

    if name == "query_level_plan":
        # 🔴 СЕЛЕКТОР ПРОВЕРЯЕТСЯ ЗДЕСЬ, ПОТОМУ ЧТО ЧИТАЮЩИЕ ОПЫ НЕ ХОДЯТ ЧЕРЕЗ
        # `authoring.validate` (см. `spec.WRITE_FAMILIES` двадцатью строками
        # выше): ветка `p.kind == "sel"` там до нас не доезжает, и если не
        # положить `level` в `norm` самому, эмиттер получит op БЕЗ поля — панику
        # вместо отказа. Так и вышло на первом прогоне: `KeyError: 'level'`
        # превратился в KIR-P000, то есть в «внутренняя ошибка компилятора» там,
        # где автору надо было сказать про уровень.
        lvl = op.get("level")
        if not isinstance(lvl, dict) or set(lvl) != {"by", "value"}:
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="level",
                  expected={"by": "name|element_id", "value": "имя или номер"}, got=lvl,
                  message_ru=("level — селектор {by, value}: by=name со строкой "
                              "или by=element_id с номером"))
        elif lvl["by"] == "ref":
            # РЕФ ОТКАЗАН ПО ИМЕНИ, а не молча. Это ЧТЕНИЕ существующего
            # документа: ссылаться на результат соседнего опа значило бы читать
            # фон вокруг того, что ещё не построено.
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="level",
                  expected={"by": "name|element_id"}, got=lvl,
                  message_ru=("level.by=ref здесь не годится: оп читает фон "
                              "СУЩЕСТВУЮЩЕГО документа, а ref называет результат "
                              "соседнего опа, которого в модели ещё нет — "
                              "назови уровень по имени или по element_id"))
        elif lvl["by"] == "name":
            if not isinstance(lvl["value"], str) or not lvl["value"].strip():
                _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                      field_name="level.value", expected="непустое имя уровня",
                      got=lvl["value"], message_ru="level.value — непустое имя уровня")
            else:
                norm["level"] = {"by": "name", "value": lvl["value"].strip()}
        elif lvl["by"] == "element_id":
            v = lvl["value"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                      field_name="level.value", expected="положительное целое",
                      got=v, message_ru="level.value — положительный element_id уровня")
            else:
                norm["level"] = {"by": "element_id", "value": v}
        else:
            _fail(diags, code=TYPE_BAD_ENUM, op_index=i, op_id=oid, field_name="level.by",
                  expected=["name", "element_id"], got=lvl["by"],
                  message_ru="level.by — name или element_id")

        # 🔴 СЛОВАРЬ ПЕЧАТАЕТСЯ, А НЕ УПОМИНАЕТСЯ. Тот же урок, что двадцатью
        # строками ниже у `fields` (26.08.2026, живой ход): сообщение обязано
        # назвать и закрытый набор, и то ЧУЖОЕ значение, из-за которого отказ.
        include = op.get("include", list(spec.LEVEL_PLAN_INCLUDE))
        if (not isinstance(include, list) or not include
                or not all(isinstance(x, str) and x in spec.LEVEL_PLAN_INCLUDE
                           for x in include)):
            чужие = ([x for x in include
                      if not isinstance(x, str) or x not in spec.LEVEL_PLAN_INCLUDE]
                     if isinstance(include, list) else [])
            хвост = ("; чужое здесь: %s" % ", ".join("«%s»" % str(x) for x in чужие)
                     ) if чужие else ""
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="include",
                  expected=list(spec.LEVEL_PLAN_INCLUDE), got=include,
                  message_ru=("include — непустой список из %s%s"
                              % (list(spec.LEVEL_PLAN_INCLUDE), хвост)))
        elif len(set(include)) != len(include):
            _fail(diags, code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="include",
                  got=include, message_ru="include не должен содержать дубликаты")
        else:
            # ПОРЯДОК НОРМАЛИЗУЕТСЯ по словарю реестра, а не по тому, как автор
            # набрал: иначе include=["floors","walls"] и ["walls","floors"] дали
            # бы разные БАЙТЫ одной и той же программы, и паритет стал бы шумом.
            norm["include"] = [x for x in spec.LEVEL_PLAN_INCLUDE if x in include]
        detail = op.get("detail", "box")
        if detail not in spec.LEVEL_PLAN_DETAIL:
            _fail(diags, code=TYPE_BAD_ENUM, op_index=i, op_id=oid, field_name="detail",
                  expected=list(spec.LEVEL_PLAN_DETAIL), got=detail,
                  message_ru=("detail — одно из %s: box — габарит (дёшево), "
                              "sketch — контур с дырами (дорого)"
                              % list(spec.LEVEL_PLAN_DETAIL)))
        else:
            norm["detail"] = detail
        limit = op.get("limit", spec.LEVEL_PLAN_LIMIT_DEFAULT)
        if isinstance(limit, bool) or not isinstance(limit, int):
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="limit",
                  expected="int", got=type(limit).__name__,
                  message_ru="limit — целое число")
        elif not 1 <= limit <= spec.LEVEL_PLAN_LIMIT_MAX:
            _fail(diags, code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="limit",
                  expected=f"1..{spec.LEVEL_PLAN_LIMIT_MAX}", got=limit,
                  message_ru=(f"limit — от 1 до {spec.LEVEL_PLAN_LIMIT_MAX}: "
                              f"потолок назван, чтобы отказ мог его напечатать"))
        else:
            norm["limit"] = limit

    if name == "query_list":
        fields = op.get("fields", list(spec.LIST_FIELDS))
        if not isinstance(fields, list) or not fields or \
                not all(isinstance(f, str) and f in spec.LIST_FIELDS for f in fields):
            # 🔴 THE SET IS NAMED, NOT MERELY MENTIONED (26.08.2026, a live
            # turn).
            #
            # The earlier text — "fields — a non-empty list from a closed
            # set" — REPORTED THAT the set EXISTED without giving it. An
            # author cannot fix that in one turn: they know neither which
            # of the submitted names is foreign, nor what to replace it
            # with, and are forced either to guess or to spend a round
            # reading the contract. Our form 43: the message must print the
            # very value the verdict was based on.
            #
            # A neighboring branch of THIS SAME function (`group_by`, twenty
            # lines above) does print its own closed set: `must be one of
            # {sorted(choices)}`. One law, two carriers, and they diverged —
            # the diagnostic's `expected` was filled in correctly from the
            # start, but the set never made it into the Russian text the
            # model reads.
            #
            # Bought by my own mistake: running query_list with
            # `["id", "length_mm"]` produced this refusal, and there was no
            # way to see from it that exactly `length_mm` was foreign while
            # `id` was legitimate.
            чужие = ([f for f in fields
                      if not isinstance(f, str) or f not in spec.LIST_FIELDS]
                     if isinstance(fields, list) else [])
            хвост = ("; чужое здесь: %s" % ", ".join("«%s»" % str(f)
                                                     for f in чужие)) if чужие else ""
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="fields",
                  expected=list(spec.LIST_FIELDS), got=fields,
                  message_ru=("fields — непустой список из %s%s"
                              % (list(spec.LIST_FIELDS), хвост)))
        elif len(set(fields)) != len(fields):
            _fail(diags, code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="fields",
                  got=fields, message_ru="fields не должен содержать дубликаты")
        else:
            norm["fields"] = fields
        limit = op.get("limit", spec.LIST_LIMIT_DEFAULT)
        # Numeric bounds enforced HERE (12.9) — bool is an int subclass, exclude it.
        if isinstance(limit, bool) or not isinstance(limit, int):
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="limit",
                  expected="int", got=type(limit).__name__, message_ru="limit — целое число")
        elif not (1 <= limit <= spec.LIST_LIMIT_MAX):
            _fail(diags, code=TYPE_BOUNDS, op_index=i, op_id=oid, field_name="limit",
                  expected=f"1..{spec.LIST_LIMIT_MAX}", got=limit,
                  suggested_replacement=min(max(limit, 1), spec.LIST_LIMIT_MAX),
                  applicability="maybe-incorrect",
                  message_ru=f"limit вне границ 1..{spec.LIST_LIMIT_MAX}")
        else:
            norm["limit"] = limit

    # `query_surface` shares with `query_inspect` EXACTLY the target
    # selector and its laws (including "searching by name requires kind");
    # everything that is its own — the u_count/v_count pair below, in its
    # own file.
    if name in ("query_inspect", "query_surface"):
        tgt = op.get("target")
        if not isinstance(tgt, dict) or tgt.get("by") not in ("element_id", "name"):
            _fail(diags, code=GROUND_BAD_SELECTOR, op_index=i, op_id=oid, field_name="target",
                  expected={"by": "element_id|name", "value": "...",
                            "kind": "required when by=name"},
                  got=tgt, message_ru="target — селектор {by, value[, kind]}")
        else:
            by, val = tgt["by"], tgt.get("value")
            allowed = ({"by", "value"} if by == "element_id"
                       else {"by", "value", "kind"})
            extra = set(tgt) - allowed
            if extra:
                _fail(diags, code=PARSE_UNKNOWN_FIELD, op_index=i, op_id=oid,
                      field_name=f"target.{sorted(extra)[0]}", message_ru="лишние поля селектора")
            if by == "element_id":
                if (isinstance(val, bool) or not isinstance(val, int)
                        or not (1 <= val <= ELEMENT_ID_MAX)):
                    _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                          field_name="target.value",
                          expected=f"целое 1..{ELEMENT_ID_MAX}", got=val,
                          message_ru="element_id — положительное 64-битное целое")
                else:
                    norm["target"] = {"by": by, "value": val}
            else:  # by == "name": needs kind to bound the search (no doc-wide name scans)
                kind = tgt.get("kind")
                if not isinstance(val, str) or not val.strip():
                    _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid,
                          field_name="target.value", expected="непустая строка", got=val,
                          message_ru="имя — непустая строка")
                elif not isinstance(kind, str) or kind not in spec.KINDS:
                    _fail(diags, code=GROUND_UNSUPPORTED_KIND, op_index=i, op_id=oid,
                          field_name="target.kind", got=kind, candidates=sorted(spec.KINDS),
                          message_ru="поиск по имени требует валидный kind")
                else:
                    norm["target"] = {"by": by, "value": val.strip(), "kind": kind}

    if name == "query_element_state":
        from kir.element_query import validate_element_query
        norm.update(validate_element_query(op, oid, diags, _fail))

    if name == "query_surface":
        from kir import surface_query
        surface_query.validate_grid(op, oid, diags, _fail)
        for _f in ("u_count", "v_count"):
            if isinstance(op.get(_f), int) and not isinstance(op[_f], bool):
                norm[_f] = op[_f]

    if name == "query_types":
        # fix/g102-disambiguate (2026-07-17): the G102-AMBIGUOUS enumeration
        # companion — "what types/families of X exist" asked BEFORE a by=name
        # selector, or after a G102 refusal to see the full candidate set (the
        # refusal itself now also carries {id,name} candidates directly, see
        # ground.py — this op is the standalone ask-first/ask-again path).
        pool = op.get("pool")
        choices = spec.OPS["query_types"].params[0].choices
        if not isinstance(pool, str) or pool not in choices:
            _fail(diags, code=TYPE_BAD_ENUM, op_index=i, op_id=oid, field_name="pool",
                  expected=sorted(choices), got=pool,
                  message_ru="pool: " + _pool_hint(pool))
        else:
            norm["pool"] = pool
    return norm


#: Fields a program may set once for all its ops. Restricted to selectors on
#: purpose: a default that moved geometry would hide the shape somewhere other
#: than the op that draws it, and the whole point of KIR is that an op says what
#: it does. Selectors are the opposite case — a tower repeats ONE beam type
#: across 128 ops, and the 2026-07-27 dojo run measured what that costs: the
#: model omitted `level`/`symbol` hoping for a default, and a project with more
#: than one candidate refused all 20 ops (KIR-G102 ×40) rather than guess.
DEFAULTABLE = ("level", "symbol", "type", "top_level")


def _apply_defaults_with_trace(
    defaults: Any,
    ops: list,
    diags: list[Diagnostic],
) -> tuple[list, tuple[tuple[str, ...], ...]]:
    """Fill selector defaults and report exactly which fields were injected."""
    no_defaults = tuple(() for _ in ops)
    if defaults is None:
        return ops, no_defaults
    if not isinstance(defaults, dict):
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, field_name="defaults",
                                expected="object", got=type(defaults).__name__,
                                message_ru="defaults должен быть объектом"))
        return ops, no_defaults
    unknown = [k for k in defaults if k not in DEFAULTABLE]
    if unknown:
        diags.append(Diagnostic(
            code=PARSE_UNKNOWN_FIELD, field_name="defaults",
            got=sorted(unknown), candidates=list(DEFAULTABLE),
            message_ru="в defaults можно задавать только селекторы "
                       f"{list(DEFAULTABLE)}"))
        return ops, no_defaults
    out, traces, accepted_anywhere = [], [], set()
    for op in ops:
        if not isinstance(op, dict):
            out.append(op)
            traces.append(())
            continue
        ospec = spec.OPS.get(op.get("op"))
        if ospec is None:            # _validate_op reports it properly
            out.append(op)
            traces.append(())
            continue
        accepted = {p.name for p in ospec.params}
        accepted_anywhere |= accepted & set(defaults)
        # 🔴 GROUP MEMBERS ARE ALSO PROGRAM OPS (25.08.2026, an audit
        # finding, reproduced by a run). The traversal only went over the
        # TOP level, and `create_group` has no `level` parameter — so an
        # envelope with `defaults: {level: ...}` was declared DEAD ("no op
        # in the program accepts it"), even though a member did accept it.
        # The refusal was wrong twice over: first about a dead key, then
        # about "level is required" on the very member that level was
        # meant for.
        #
        # Measured 22.08: 82.6 % of the operations of a real building live
        # INSIDE groups. A traversal blind to them is a traversal blind to
        # the building.
        for член in (op.get("members") or ()):
            if not isinstance(член, dict):
                continue
            мспек = spec.OPS.get(член.get("op"))
            if мспек is not None:
                accepted_anywhere |= {p.name for p in мспек.params} & set(defaults)
        fill = {k: v for k, v in defaults.items()
                if k in accepted and k not in op}
        out.append({**op, **fill} if fill else op)
        traces.append(tuple(sorted(fill)))
    # Dead means NO op could ever take it — a typo that would otherwise do
    # nothing at all, the silent-no-op failure mode KIR exists to refuse. An op
    # naming its own value is not dead: overriding the envelope is the point.
    dead = sorted(set(defaults) - accepted_anywhere)
    if dead:
        diags.append(Diagnostic(
            code=PARSE_UNKNOWN_FIELD, field_name="defaults", got=dead,
            candidates=sorted({p.name for o in ops if isinstance(o, dict)
                               and spec.OPS.get(o.get("op"))
                               for p in spec.OPS[o["op"]].params
                               if p.name in DEFAULTABLE}),
            message_ru="ни один оп программы не принимает эти defaults: "
                       f"{dead}"))
    return out, tuple(traces)


def _apply_defaults(defaults: Any, ops: list, diags: list[Diagnostic]) -> list:
    """Legacy list API; the compiler itself consumes the traced variant."""
    return _apply_defaults_with_trace(defaults, ops, diags)[0]


_POINT_KINDS = ("pt_xy", "pt_xyz", "pts", "pts_xyz", "pts_list")


def _number_points(value) -> list[list[float]]:
    """All numeric points inside a value of point kind (RELATE addresses —
    dicts — are skipped: their numbers appear at ground, see the
    boundary)."""
    if isinstance(value, list) and value and all(
            isinstance(c, (int, float)) and not isinstance(c, bool) for c in value):
        return [list(map(float, value))]
    if isinstance(value, list):
        out: list[list[float]] = []
        for item in value:
            out.extend(_number_points(item))
        return out
    return []


def reject_move_beyond_scene(ops: list, idx: int, move_op: dict,
                             byid: dict, diags: list) -> bool:
    """The scene limit (COORD_LIMIT_MM) — ONE law, a SECOND path to it.

    07.09.2026, F1/C03 "large coordinates." A literal beyond ±16 000 000 mm
    was refused (KIR-T002), while the very same point, REACHED via
    `move_elements` within the same program, was not: a wall at 15,95 km +
    a 100 m shift = 16,05 km compiled clean. Revit does accept such
    geometry live, but loses precision beyond the working extent —
    silently. Here the order of ops and the author's target coordinates
    are known, so the FINAL position is computed
    (`geom.same_program_shift`, up to and including this shift). Targets
    given by `element_id` are not checked: their position is unknown to
    the compiler.
    """
    from kir.registry_base import COORD_LIMIT_MM
    ok = True
    for j, t in enumerate(move_op.get("targets") or ()):
        if not (isinstance(t, dict) and t.get("by") == "ref"):
            continue
        target = byid.get(t.get("value"))
        tspec = spec.OPS.get(target.get("op")) if isinstance(target, dict) else None
        if tspec is None:
            continue                      # an unknown ref is judged by KIR-L003
        sx, sy, sz = _geom.same_program_shift(ops, idx + 1, str(t.get("value")))
        for p in tspec.params:
            if p.kind not in _POINT_KINDS:
                continue
            for pt in _number_points(target.get(p.name)):
                moved = [pt[0] + sx, pt[1] + sy] + ([pt[2] + sz] if len(pt) > 2 else [])
                over = next((c for c in moved if abs(c) > COORD_LIMIT_MM), None)
                if over is None:
                    continue
                diags.append(Diagnostic(
                    code=TYPE_BOUNDS, op_index=idx, op_id=move_op["id"],
                    field_name=f"targets[{j}]",
                    expected=f"|координата| <= {COORD_LIMIT_MM:.0f} мм ПОСЛЕ сдвига",
                    got={"target": t.get("value"), "param": p.name,
                         "coordinate_mm": over},
                    message_ru=(f"после сдвига «{t.get('value')}» его {p.name} "
                                f"оказывается на {over:.0f} мм от начала координат "
                                f"— за пределом сцены ({COORD_LIMIT_MM:.0f} мм); "
                                f"литерал в этой точке отказывается тем же законом, "
                                f"сдвиг ту же границу не обходит")))
                ok = False
                break
            if not ok:
                break
    return ok


def hosted_offset_check(hosted: dict, wall: dict, host_id: str,
                        idx: int | None, diags: list,
                        shift: tuple[float, float, float] = (0.0, 0.0, 0.0)
                        ) -> bool:
    """"a door past the wall's edge" — ONE judge, TWO call sites.

    `shift` — the host's cumulative shift by the same program BEFORE the
    hosted op (`geom.same_program_shift`): the host's shape is applied at
    its position AS OF the door, not at the author's. A shift along Z is a
    named refusal (KIR-L009): a door's height is measured from the level,
    not from the wall.

    The law reads the NUMBERS of the wall's endpoints. While the endpoints
    were literals, it lived entirely at the plan stage. With RELATE, a
    wall's endpoint can arrive from a snapshot — and then the numbers only
    appear after ground. An instrument that went silent on this part of the
    range would be more dangerous than a missing one: a door past the edge
    of the addressed wall would have ridden into the transaction, where a
    failure costs a full round trip.

    That is why there is one implementation, called by two:
    `_parse_and_check_internal` (literal endpoints) and `ground.ground`
    (endpoints resolved from grids). The side effect is the same one —
    `__host_wall__` for the emitter.
    """
    import math as _math
    arc = wall.get("arc")
    if isinstance(arc, dict):
        length = abs(float(arc["radius_mm"]) * (
            float(arc["end_angle_rad"]) - float(arc["start_angle_rad"])))
    else:
        length = _math.hypot(wall["p1_mm"][0] - wall["p0_mm"][0],
                             wall["p1_mm"][1] - wall["p0_mm"][1])
    offset = hosted.get("offset_mm", 0)
    if offset > length:
        diags.append(Diagnostic(
            code="KIR-T002", op_index=idx, op_id=hosted["id"],
            field_name="offset_mm", expected=f"0..{length:.0f}", got=offset,
            message_ru=(f"offset {offset}мм за пределами стены "
                        f"«{host_id}» ({length:.0f}мм)")))
        return False
    sx, sy, sz = (float(shift[0]), float(shift[1]), float(shift[2]))
    if sz != 0.0:
        diags.append(Diagnostic(
            code=PLAN_HOST_MOVED_VERTICALLY, op_index=idx, op_id=hosted["id"],
            field_name="host", expected="хост без сдвига по Z до этого опа",
            got={"host": host_id, "dz_mm": sz},
            message_ru=(f"стена-хост «{host_id}» сдвинута по Z на {sz:g}мм "
                        f"этой же программой до «{hosted['id']}»: высота "
                        "двери/окна считается от уровня, а не от стены — "
                        "сдвинь хост отдельной программой или до его "
                        "создания задай нужный уровень")))
        return False

    # The shape is computed by ONE law (`geom.shifted_host_shape`); the
    # control `midend._assert_payload_refinement` independently recomputes
    # the very same one.
    host_shape = _geom.shifted_host_shape(wall, (sx, sy, 0.0))
    # The name is taken from the AUTHORITY: the writer and its four readers
    # must all be talking about the same field, and the only way to
    # guarantee that is to let no one write its name on their own.
    #
    # The agreement over "who reaches here" and "who is declared the
    # owner" is held by a TEST
    # (`tests/test_synthetic_fields_have_one_authority.py`), not by an
    # `assert` here. I tried `assert` — and it showed exactly its own
    # unfitness: under `python -O` it disappears, meaning the invariant
    # would vanish first exactly where it is most expensive; and before
    # that, it arrives NOT as a refusal but as a compiler PANIC
    # (incident_id, stage=plan) — that is, on a path where there is
    # nothing to refuse, and the caller reads a crash instead of a
    # diagnosis.
    hosted[spec.SYNTHETIC_HOST_WALL] = host_shape
    return True


@dataclass(frozen=True, slots=True)
class _OpPlanTrace:
    source_index: int
    source_op: str | None
    source_id: str | None
    macro_name: str | None
    expanded_fields: frozenset[str]
    defaulted_fields: tuple[str, ...]


_GROUND_ID_RULES = frozenset({
    "element_id", "name", "name+disambiguate_by", "family_type",
    "sole_entry", "sole_entry+disambiguate_by", "most_used",
    "most_used+disambiguate_by",
})


def _authored_selector_from_grounded(value: Any) -> Any:
    """Turn a legacy internal selector into a fully validated public form.

    Native-group producers historically embedded grounder output directly in
    ``members``.  Accepting that object as-is skipped every member validator.
    We retain wire compatibility by reducing a *strictly valid* marker to an
    equivalent explicit selector and then sending it through ``plan_program``.
    Thus the marker is never a shortcut around type/bounds/op contracts.
    """

    if isinstance(value, list):
        return [_authored_selector_from_grounded(item) for item in value]
    if not _valid_ground_marker(value):
        return value
    detail = value.get("__grounded__")
    assert isinstance(detail, dict)
    via = detail.get("via")
    if via == "doc_default":
        if (set(detail) != {"id", "name", "via", "in_emit"}
                or detail.get("id") is not None
                or detail.get("name") is not None
                or detail.get("in_emit") != "__doc_default__"):
            return value
        return {"by": "default"}
    identifier = detail.get("id")
    if (via not in _GROUND_ID_RULES
            or isinstance(identifier, bool)
            or not isinstance(identifier, int)
            or not (1 <= identifier <= ELEMENT_ID_MAX)):
        return value
    name = detail.get("name")
    if name is not None and not isinstance(name, str):
        return value
    return {"by": "element_id", "value": identifier}


def _member_for_validation(member: dict[str, Any]) -> dict[str, Any]:
    """Detach a group member and decode only declared grounded selectors."""

    candidate = {key: value for key, value in member.items()}
    op_spec = spec.OPS.get(candidate.get("op"))
    if op_spec is None:
        return candidate
    for field_name, _pool, _required in op_spec.grounded:
        if field_name in candidate:
            candidate[field_name] = _authored_selector_from_grounded(
                candidate[field_name])
    return candidate


def _group_member_diagnostic(
    diagnostic: Diagnostic,
    *,
    group_id: str,
    group_index: int,
    member_id: str,
    member_index: int,
) -> Diagnostic:
    suffix = diagnostic.field_name
    name = member_id or member_index
    member_path = f"members[{name}]"
    return replace(
        diagnostic,
        op_index=group_index,
        op_id=group_id,
        field_name=(f"{member_path}.{suffix}" if suffix else member_path),
        message_ru=_member_addressed_message(
            diagnostic.message_ru, group_id=group_id, member=name),
    )


#: The member-address prefix. The key is `«`, because a member's name comes
#: from the author's `id`, and in guillemet quotes it would look like
#: someone else's quotation.
_MEMBER_ADDRESS = "член «{member}» группы «{group}»: "


def _member_addressed_message(message: Any, *, group_id: str,
                              member: Any) -> Any:
    """Put the member's address INTO THE TEXT, as the first line.

    🔴 WHY THIS IS HERE, AND NOT IN A SEPARATE FIELD (measured 27.08.2026).

    The member's address ALREADY exists and is already correct — in
    `field_name` (`members[w2].height_mm`); all three pipeline stages put
    it there through this same function. The first statement of the task
    said "the refusal doesn't name the member," and it was WRONG: the
    instrument was only looking at `op_id`.

    Exactly one thing is missing — the address IN THE TEXT. And that is
    not cosmetic:

      * `diag.KirRefusal.__init__` assembles the exception string from
        `code` and `message_ru`, and `field_name` does not enter it AT
        ALL. And across the process boundary (the author script's
        sandbox), only the text is able to travel — that is what
        `KirRefusal`'s own docstring says. So wherever the text travels,
        the member's address was lost entirely;
      * `with unit(...)` — a technique that `course` RECOMMENDS for an
        apartment. With twenty walls, the model got "height_mm — a number
        in mm" with no indication of which of the twenty.

    WHY NOT A NEW `member_id` FIELD. It would become a SECOND carrier of
    the same knowledge alongside `field_name`, and the two would have
    drifted apart on the very first edit — that is a named defect of this
    tree. One carrier is machine-facing (`field_name`), one is
    human-facing (the text), and the second is DERIVED from the same
    arguments as the first, in one function.

    WHAT THIS FIX DOES NOT TOUCH, AND THAT IS A DECISION:
      * `op_id` remains the GROUP's name — it is keyed by provenance
        substitution (`serving._name_the_author_line`), acceptance, the
        receipt, the witness feed;
      * `field_name` remains `members[<id>].<slot>` — pinned by
        `test_nested_grounding_integrity` and
        `test_member_path_gets_no_foreign_advice`;
      * no new refusal codes are introduced.

    IDEMPOTENT ON PURPOSE: a diagnostic that has already passed through
    the seam does not get a second prefix. Otherwise a nested pass would
    produce «член «w2» группы «g»: член «w2» группы «g»: …», and the text
    would lie about two levels of nesting where there is only one.
    """
    if not isinstance(message, str) or not message:
        return message
    if message.startswith("член «"):
        return message
    return _MEMBER_ADDRESS.format(member=member, group=group_id) + message


def _plan_group_members(
    members: list[dict[str, Any]],
    *,
    group_id: str,
    group_index: int,
    defaults: dict[str, Any] | None = None,
) -> tuple[PlannedOp, ...]:
    """Fully plan every group member as an independent create operation."""

    planned: list[PlannedOp] = []
    diagnostics: list[Diagnostic] = []
    candidates: list[tuple[int, str, dict[str, Any]]] = []
    for member_index, raw_member in enumerate(members):
        member_id = (
            raw_member.get("id")
            if isinstance(raw_member.get("id"), str) else str(member_index)
        )
        op_name = raw_member.get("op")
        op_spec = spec.OPS.get(op_name) if isinstance(op_name, str) else None
        supported = bool(
            op_spec is not None
            and op_spec.family == "authoring"
            and op_spec.effect.value == "create"
            and op_spec.result.identity_cardinality.value == "one"
            and op_name != "create_group"
            and op_name not in spec.SOLO_OPS
        )
        if not supported:
            diagnostics.append(Diagnostic(
                code=TYPE_BAD_TYPE,
                op_index=group_index,
                op_id=group_id,
                field_name=f"members[{member_id}].op",
                got=op_name,
                message_ru=(
                    "член группы должен быть одиночным create-authoring op, "
                    "который материализует один Element; query, modify/delete, "
                    "собственная транзакция и вложенная create_group запрещены"
                ),
            ))
            continue
        candidates.append((member_index, member_id, _member_for_validation(raw_member)))

    # A GROUP IS A SMALL PROGRAM IN ITS OWN NAMESPACE.
    #
    # Previously each member was planned as a SEPARATE one-op program
    # (`"ops": [candidate]`), and that made a reference to a fellow group
    # member unexpressible BY CONSTRUCTION: the nested program held
    # exactly one op, so `ref` had nowhere to point. A door addresses its
    # wall only through `ref` — so a floor with both walls AND doors could
    # not be assembled as a group.
    #
    # **The cost of this, measured 12.08.2026:** 41.1% of the elements of
    # a real 59-story tower live inside groups (walls 94.9%, load-bearing
    # columns 100%, curtain-wall panels 99.3%, doors 91.4%), because a
    # human models ONE floor and places it as a group. The only form
    # available to us was enumeration, and it runs into the ceiling of 300
    # at a real floor's median of 796 ops — hence 151 programs per
    # building, which the model had to cut up by hand.
    #
    # We plan all members as ONE nested program. Then order, reference
    # kinds, and KIR-L003/L004 all work under exactly the same rules as in
    # a normal program, with no exception whatsoever: "an earlier op"
    # inside a group means "a member declared above." Nothing special
    # needs to be known about `ref` — the members just need the shared
    # program they did not have before.
    if candidates:
        try:
            nested = plan_program({
                "ir_version": spec.IR_VERSION,
                "intent": f"members of {group_id}",
                # 🔴 THE MEMBER ENVELOPE CARRIES `defaults` (25.08.2026).
                # Without this key, the nested program was assembled
                # WITHOUT the author's defaults, and a member that relied
                # on the envelope got "level is required" — about a field
                # the author HAD SET. Defaults are idempotent: only what is
                # missing gets filled in, and a member that named its own
                # value keeps it.
                **({"defaults": defaults} if defaults else {}),
                "ops": [candidate for _, _, candidate in candidates],
            })
        except KirRefusal as refusal:
            by_index = {index: (mid, midx)
                        for midx, (index, mid, _) in enumerate(candidates)}
            for item in refusal.diagnostics:
                position = item.op_index if item.op_index is not None else 0
                member_id, member_index = by_index.get(
                    position, (str(position), position))
                diagnostics.append(_group_member_diagnostic(
                    item,
                    group_id=group_id,
                    group_index=group_index,
                    member_id=member_id,
                    member_index=member_index,
                ))
        else:
            if (nested.family is not ProgramFamily.WRITE
                    or len(nested.ops) != len(candidates)
                    or any(planned_op.op_id != mid
                           for planned_op, (_, mid, _) in zip(nested.ops,
                                                              candidates))):
                raise RuntimeError(
                    "group member planner violated member identity")
            planned.extend(nested.ops)
    if diagnostics:
        raise KirRefusal(diagnostics)
    return tuple(planned)


def _parse_and_check_internal(
    program: Any,
    *,
    bulk: bool = False,
) -> tuple[
    list[dict],
    tuple[_OpPlanTrace, ...],
    tuple[tuple[PlannedOp, ...], ...],
]:
    diags: list[Diagnostic] = []
    if not isinstance(program, dict):
        # 🔴 A REFUSAL MUST NAME THE NEXT TURN, NOT JUST THE DIAGNOSIS.
        #
        # Measured 21.08 on the author's live loop: the model regularly
        # puts a BARE LIST of operations into `program`. The history of
        # this is known — the collapsed schema, before 18.08, declared
        # `type: array` and taught this habit (`schema_transport`,
        # "KIR-P001 14 times over 6 runs") — but the declaration was fixed
        # while the habit remained, and on the baseline it cost a whole
        # round trip.
        #
        # The earlier text said WHAT was missing ("must be a JSON object")
        # and was silent about WHAT TO DO. The difference is not
        # stylistic: KIR's invariant is that the compiler owns
        # correctness, REFUSES, and names the next turn. A refusal without
        # a turn shifts the guessing onto the author and is paid for with
        # a round trip.
        got = type(program).__name__
        if isinstance(program, list):
            hint = ("получен СПИСОК операций. Оберни его: "
                    '{"ops": [...]} — конверт несёт не только операции, '
                    "но и `intent`, `defaults`, `allow_destructive`, и "
                    "без него их сказать негде")
        else:
            hint = f"получено значение типа `{got}`"
        raise KirRefusal([Diagnostic(
            code=PARSE_NOT_OBJECT,
            message_ru=f"программа должна быть JSON-объектом: {hint}")])
    # ─── ENVELOPE VERSION: ABSENCE IS NOT AN ERROR, A MISMATCH IS AN ERROR ───────
    #
    # 🔴 BEFORE 17.08.2026, WHAT STOOD HERE WAS A TAX, NOT A PROTECTION.
    # The condition was `program.get("ir_version") != spec.IR_VERSION`,
    # meaning the ABSENCE of the field was punished the same as a wrong
    # value. There is EXACTLY ONE version in the registry
    # (`registry_base.IR_VERSION = "1.0"`), so requiring it to be printed
    # protects against nothing: the only thing it could distinguish was
    # "the model forgot the ritual" from "the model performed it."
    #
    # THE COST WAS MEASURED, NOT ASSUMED (17.08, the flash model
    # `deepseek-v4-flash`, an offline ring, two series of 10 rounds per
    # hand): **16 rounds out of 27 produced NOT A SINGLE operation**, with
    # codes `KIR-P001` ×15, `KIR-P003` ×12, `KIR-P004` ×5. That is, more
    # than half of the model's turns died on the ENVELOPE, never reaching
    # the building. A round trip costs 17–18 s, of which 84.6 % is waiting
    # on the model; every such round is a wasted round trip.
    #
    # WHAT IS FULLY PRESERVED: a named WRONG version still refuses. The
    # relaxation is strictly one-sided — what is accepted is exactly what
    # used to mean the same thing and nothing else. Should a second
    # version appear, this same refusal is where it will announce itself.
    declared_version = program.get("ir_version")
    if declared_version is not None and declared_version != spec.IR_VERSION:
        diags.append(Diagnostic(code=PARSE_BAD_VERSION, field_name="ir_version",
                                expected=spec.IR_VERSION, got=declared_version,
                                message_ru="ir_version назван и не совпал: "
                                           "ожидается '%s'" % spec.IR_VERSION))
    # `units` — A LEGITIMATE PART OF THE ENVELOPE, AND THE DECISION HERE IS
    # MADE EXPLICITLY.
    #
    # The table of intent units (`course.unit()`) describes HOW TO READ the
    # set of ops; it has zero effect on execution — not one byte of
    # emission, not one transaction, not one checkpoint. In this it differs
    # fundamentally from `phases`, which refuses below: a phase PROMISES a
    # checkpoint, and gluing phases into one program would mean declaring a
    # checkpoint that isn't there. A unit promises execution nothing, so a
    # program with units is an ordinary program, and there is nothing to
    # refuse it for.
    #
    # WHY NOT JUST "IGNORE IT." A key silently skipped is indistinguishable
    # from an unknown one, and an unknown one here is a typed refusal. The
    # name was added to the list KNOWING what it means, and that decision
    # is recorded right next to it.
    known_top = {"ir_version", "intent", "allow_destructive", "ops", "defaults",
                 "units", "lineage"}
    # Internal A5 materialization binds each deterministic chunk to its durable
    # journal receipt.  This metadata is accepted only on the trusted ``bulk``
    # path; it is deliberately absent from the user/LLM schema and has no
    # emission semantics.
    if bulk:
        known_top.add("program_id")
    for k in program:
        if k not in known_top:
            # A PLAN IS NOT A PROGRAM, AND THE REFUSAL MUST SAY EXACTLY
            # THAT. `phases` is a legitimate part of the envelope, built by
            # `course.phase()`; what's illegitimate here is something
            # else — handing a plan to a function that executes ONE
            # transaction. This is the last line of defense: the live door
            # cuts a plan into a batch (`split_phases`) ABOVE this point,
            # and a plan only reaches here for whoever did not do the
            # cutting. A generic "unknown field" would send such a reader
            # off to remove the field, i.e. to lose the checkpoints — the
            # most expensive fix possible.
            message = (
                "программа с планом фаз (`phases`) не исполняется как ОДНА "
                "программа: фаза — это отдельная транзакция и отдельный "
                "чекпойнт, а здесь их одна на всё. Тихо склеить фазы значило "
                "бы объявить чекпойнт, которого нет. Режь план на пачку — "
                "`compiler.split_phases(program)` — и веди звенья по одному"
                if k == "phases" else f"неизвестное поле конверта '{k}'")
            diags.append(Diagnostic(code=PARSE_UNKNOWN_FIELD, field_name=k,
                                    candidates=sorted(known_top),
                                    message_ru=message))
    if "lineage" in program:
        # 🔴 D-1: `lineage` — a STABLE ADDRESS of the author's program,
        # from which the type-ownership marker is built. This is a
        # DECLARATION, not proof of authorship — exactly like the marker
        # itself ("exact creation marker, not an authentication proof",
        # `_type_owner_guard`). That's why what's checked is the FORM, not
        # the right: an empty string and garbage are rejected with a typed
        # refusal, so the address cannot be obtained by accident.
        _lineage = program.get("lineage")
        if not isinstance(_lineage, str) or not LINEAGE_FORM.fullmatch(_lineage):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE, field_name="lineage",
                expected="строка 1..64 из [A-Za-z0-9._:-]", got=_lineage,
                message_ru=("lineage — устойчивая личность авторской программы "
                            "(у Project-пути это project_id); она даёт адрес "
                            "владения типом и потому обязана быть непустой "
                            "строкой названной формы")))
    if "intent" in program:
        intent = program.get("intent")
        if not isinstance(intent, str):
            diags.append(Diagnostic(code=TYPE_BAD_TYPE, field_name="intent",
                                    expected="string", got=type(intent).__name__,
                                    message_ru="intent должен быть строкой"))
        elif len(intent) > 2000:
            diags.append(Diagnostic(code=TYPE_BOUNDS, field_name="intent",
                                    expected="<=2000 символов", got=len(intent),
                                    message_ru="intent длиннее 2000 символов"))
    if "allow_destructive" in program and not isinstance(program.get("allow_destructive"), bool):
        diags.append(Diagnostic(code=TYPE_BAD_TYPE, field_name="allow_destructive",
                                expected="bool", got=type(program.get("allow_destructive")).__name__,
                                message_ru="allow_destructive должен быть true/false"))
    if "program_id" in program:
        program_id = program.get("program_id")
        if (not isinstance(program_id, str)
                or re.fullmatch(r"[0-9a-f]{64}", program_id) is None):
            diags.append(Diagnostic(
                code=TYPE_BAD_TYPE,
                field_name="program_id",
                expected="64 lowercase hex chars",
                got=program_id,
                message_ru="program_id должен быть sha256 hex"))
    ops = program.get("ops")
    # A SINGLE OPERATION, WRITTEN WITHOUT A LIST, MEANS EXACTLY ONE
    # THING — and since 17.08.2026 it is accepted. This is not a relaxed
    # check but the removal of an ambiguity that WAS NEVER THERE:
    # `{"ops": {"op": "create_wall", …}}` cannot mean anything except a
    # one-element list, and refusing it here cost the model a whole round
    # trip (measured the same day — `KIR-P001` ×15 over 27 rounds). An
    # empty list, a missing field, and any other form still refuse AS
    # BEFORE: there the intent is unknown, and it must not be guessed.
    if isinstance(ops, dict) and ops.get("op"):
        ops = [ops]
    if not isinstance(ops, list) or not ops:
        diags.append(Diagnostic(code=PARSE_NOT_OBJECT, field_name="ops",
                                message_ru="ops — непустой список операций "
                                           "(одна операция может быть написана "
                                           "и без списка)"))
        _refusal = KirRefusal(diags)
        # The muteness seam must read THE SAME list against which indices
        # were assigned, not the author's envelope (see
        # `KirRefusal.expanded_ops`).
        # 🔴 `list(ops)` ONLY WHEN `ops` IS A SEQUENCE (25.08.2026). The
        # paragraph above promises, word for word: "an empty list, an
        # ABSENT FIELD, and any other form still refuse AS BEFORE." An
        # empty list did refuse correctly — `KIR-P001`, with exemplary
        # text. But when the `ops` key was ABSENT it came out as `None`,
        # and `list(None)` raised RIGHT HERE, turning an already-ready
        # typed refusal into `KIR-P000` — a compiler panic with no cause,
        # no address, and no next turn.
        #
        # Our named defect in pure form: a value is DECLARED in prose two
        # lines above and READ by code that does not enforce it.
        # `test_negative` caught it on `{}` and on `{"ir_version": "1.0"}`
        # — and it stayed red, because it was not the only red thing in
        # the file (form 35: the cost of a red is not the defect it names,
        # but the ones it hides while it stays red).
        #
        # THE OTHER THREE `list(ops)` IN THIS FILE (`:1334`, `:1353`,
        # `:1770` at the time of this fix) STAND BELOW the type check, and
        # by then `ops` is already a list — `None` is unreachable there.
        # Left untouched on purpose: extending the fix beyond what was
        # measured means fixing something unmeasured. Named, not passed
        # over in silence — if the checks are ever reordered, look here.
        _refusal.expanded_ops = list(ops) if isinstance(ops, (list, tuple)) else []
        raise _refusal
    # `bulk` raises the pre-macro cap to MAX_BULK_OPS for INTERNAL callers only
    # (the decompile materializer, the dry rebuild gate, the A5 runner and — as
    # of 2026-07-30 — serving's INTERNAL door `handle_revit_ir_bulk`, reachable
    # from /admin/kir/* alone). It is never part of the LLM schema and never
    # reachable from the CHAT door `handle_revit_ir`, whose signature has no
    # switch for it, so a user-authored program keeps the tight
    # MAX_OPS_PER_PROGRAM budget. The post-expansion MAX_VALIDATED_OPS
    # ceiling below is UNCHANGED — bulk cannot exceed the emitter's real limit.
    budget_name, pre_macro_cap = pre_macro_budget(bulk=bulk)
    if len(ops) > pre_macro_cap:
        # The refusal NAMES the exhausted budget — both in words and as a
        # stable token. The INTERNAL budget's number deliberately does not
        # flow into the author's refusal: telling the model "300" already
        # cost a round and a program rewrite (measured 27.07, the tower) —
        # it took someone else's budget for its own.
        if bulk:
            message_ru = (
                "слишком много опов в программе (до экспансии макросов): "
                f"исчерпан ВНУТРЕННИЙ bulk-бюджет чанка ({budget_name}) — "
                f"{pre_macro_cap} опов, пришло {len(ops)}. Бюджета два: "
                f"авторский ({BUDGET_AUTHORED}, {MAX_OPS_PER_PROGRAM}) меряет "
                "программы модели и здесь НЕ применяется, внутренний меряет "
                "чанки материализатора — режь разбор меньшим chunk_target")
        else:
            message_ru = (
                "слишком много опов в программе (до экспансии макросов): "
                f"исчерпан АВТОРСКИЙ бюджет программы ({budget_name}) — "
                f"{pre_macro_cap} опов, пришло {len(ops)}. Повторяющееся "
                "собирают макросом, разнородное разводят по нескольким "
                "программам")
        diags.append(Diagnostic(code=PLAN_LIMIT, field_name="ops",
                                expected=f"<={pre_macro_cap}", got=len(ops),
                                message_ru=message_ru))
        _refusal = KirRefusal(diags)
        # The muteness seam must read THE SAME list against which indices
        # were assigned, not the author's envelope (see
        # `KirRefusal.expanded_ops`).
        _refusal.expanded_ops = list(ops)
        raise _refusal
    # macro layer: deterministic expansion BEFORE validation (SPEC 12.3)
    from kir import macros
    ops, expansion_origins = macros.expand_with_origins(ops)
    expanded_fields = tuple(
        frozenset(op) if isinstance(op, dict) else frozenset()
        for op in ops
    )
    # After expansion, so macro-generated ops inherit the envelope too, and
    # before validation, so a filled field is checked like any hand-written one.
    ops, defaulted_fields = _apply_defaults_with_trace(
        program.get("defaults"), ops, diags)
    if len(ops) > MAX_VALIDATED_OPS:
        diags.append(Diagnostic(code=PLAN_LIMIT, field_name="ops", got=len(ops),
                                message_ru="экспансия макросов превысила бюджет"))
        _refusal = KirRefusal(diags)
        # The muteness seam must read THE SAME list against which indices
        # were assigned, not the author's envelope (see
        # `KirRefusal.expanded_ops`).
        _refusal.expanded_ops = list(ops)
        raise _refusal
    # id → the index of the FIRST op with this id: without it, the refusal
    # could only name the reason ("duplicate id"), and the author had to
    # hunt for the match by eye through the program.
    seen_ids: dict[str, int] = {}
    normed = []
    plan_traces: list[_OpPlanTrace] = []
    nested_member_plans: list[tuple[PlannedOp, ...]] = []
    for i, op in enumerate(ops):
        n = _validate_op(op, i, diags)
        if n:
            if n["id"] in seen_ids:
                # 🔴 "DUPLICATE ID" — A REASON WITH NO CULPRIT AND NO NEXT
                # TURN (23.08). `op_id` and `field_name` were filled in,
                # the text was two words. The cost is not about
                # politeness: an id resolves `by_ref` references, and two
                # identical ones make a reference ambiguous — meaning the
                # author is fixing not a typo but an addressing problem,
                # and must know BOTH locations. expected (25.08.2026,
                # measured by the mission instrument): the FORM is a
                # concrete constraint on the value, not the name of a
                # kind. Here it names it precisely: this op's id must
                # differ from the id of op №seen_ids[...], rather than
                # "give it a different one" in words with nothing to point
                # at.
                diags.append(Diagnostic(
                    code=PARSE_DUP_ID, op_index=i, op_id=n["id"],
                    field_name="id",
                    expected=f"id != {n['id']!r} (занят опом №{seen_ids[n['id']]})",
                    message_ru=(
                        f"дубликат id {n['id']!r}: он уже занят опом "
                        f"№{seen_ids[n['id']]}. СЛЕДУЮЩИЙ ХОД: дай ЭТОМУ опу "
                        f"другой id — по id разрешаются ссылки `by_ref`, и "
                        f"два одинаковых делают ссылку неоднозначной")))
            seen_ids.setdefault(n["id"], i)
            member_plans: tuple[PlannedOp, ...] = ()
            if n["op"] == "create_group" and isinstance(n.get("members"), list):
                try:
                    member_plans = _plan_group_members(
                        n["members"], group_id=n["id"], group_index=i,
                        defaults=program.get("defaults")
                        if isinstance(program.get("defaults"), dict) else None)
                    n["members"] = [item.to_dict() for item in member_plans]
                except KirRefusal as refusal:
                    diags.extend(refusal.diagnostics)
            normed.append(n)
            nested_member_plans.append(member_plans)
            origin = expansion_origins[i]
            plan_traces.append(_OpPlanTrace(
                source_index=origin.source_index,
                source_op=origin.source_op,
                source_id=origin.source_id,
                macro_name=origin.macro_name,
                expanded_fields=expanded_fields[i],
                defaulted_fields=defaulted_fields[i],
            ))
    # plan: query is exclusive (read-only invariant must stay provable);
    # write families (authoring+modify) share one transaction and may mix.
    families = {spec.OPS[n["op"]].family for n in normed}
    if "query" in families and len(families) > 1:
        # 🔴 THE REASON WAS NAMED, THE NEXT TURN WAS NOT (23.08.2026,
        # bought by a live turn). The text said "not supported in v1" and
        # fell silent; the author, whose reconnaissance and writing sit in
        # one script, could not learn from it either what to do or that
        # reconnaissance does NOT COST A TURN — it is the third
        # legitimate kind of response (KIR-B013) and costs zero. The
        # refusal sent the author off to rewrite the program where all
        # that was needed was to split it into two turns.
        _чтения = sorted({n["op"] for n in normed
                          if spec.OPS[n["op"]].family == "query"})
        _записи = sorted({n["op"] for n in normed
                          if spec.OPS[n["op"]].family != "query"})
        diags.append(Diagnostic(
            code="KIR-L002", field_name="ops", got=sorted(families),
            message_ru=(
                "смешение query и write-опов в одной программе не "
                "поддерживается в v1: чтение обязано быть доказуемо "
                f"read-only, а запись идёт транзакцией. Чтения здесь: "
                f"{', '.join(_чтения)}; записи: {', '.join(_записи[:6])}"
                f"{'…' if len(_записи) > 6 else ''}. "
                "СЛЕДУЮЩИЙ ХОД: сними чтения из ЭТОЙ программы и спроси их "
                "ОТДЕЛЬНЫМ ходом — разведочный ход засчитывается третьим "
                "родом ответа и программы не требует. Форму опа можно "
                "прочесть и вовсе не тратя хода: print(<имя_опа>.__doc__)")))
    # plan: op owning its own transaction scope is SOLE (KIR-L002, spec.SOLO_OPS).
    #
    # HERE, NOT ONLY IN THE EMITTER, and that is the difference between
    # "the rule exists" and "the rule is reachable." The refusal used to
    # live in exactly one place — `emit_program`, that is, AFTER
    # grounding. That meant the sandbox would assemble the program, the
    # plan would accept it, and the model would only learn about the wall
    # on a live device, where a round trip costs the most. Measured 04.08:
    # `plan_program` silently accepted `[create_stairs, create_wall]`.
    # This rule needs no live Revit — it is about the SHAPE OF THE
    # PROGRAM, and so it must be visible offline. The refusal in the
    # emitter STAYS, verbatim: it is the last line of defense, not a
    # duplicate.
    solo = sorted({n["op"] for n in normed} & spec.SOLO_OPS)
    if solo and len(normed) > 1:
        neighbours = sorted({n["op"] for n in normed} - spec.SOLO_OPS)
        diags.append(Diagnostic(
            code=PLAN_SOLO_OP, field_name="ops",
            expected="1", got=len(normed),
            candidates=neighbours,
            message_ru=(
                f"{solo[0]} — единственный оп своей программы (владеет "
                f"собственными транзакциями); соседей здесь {len(normed) - 1}. "
                f"Здание — это ПАЧКА программ: тело отдельно, лестницы "
                f"отдельно. Уровень, созданный программой тела, доступен "
                f"лестничной по ИМЕНИ: base_level=\"Этаж 1\"")))
    # DAG: every ref-bearing registry param resolves to an EARLIER typed
    # reference producer.  Producer identity is declared by ResultSpec; op
    # spelling (historically startswith("create_")) has no semantics.
    created: dict[str, spec.OpSpec] = {}
    # The hosted-offset static geometry check still needs the normalized
    # producer body, independently of whether that producer is referenceable.
    byid = {n["id"]: n for n in normed}
    # 🔴 A DELETED THING IS NOT ADDRESSABLE (07.09.2026, F1 "an unknown
    # effect gets no success"). `delete X →
    # move_elements/change_type/delete X` compiled clean: live, it's a
    # "stale id" refusal at the cost of a round trip, while the plan
    # already knows the order of ops. BOTH addresses of a target are
    # tracked: `ref` to an op of this program, and `element_id` of an
    # already-standing element.
    deleted_refs: dict[str, str] = {}      # ref  -> id of the op that deleted it
    deleted_eids: dict[int, str] = {}      # element_id -> id of the op that deleted it
    for idx, n in enumerate(normed):
        ospec = spec.OPS[n["op"]]
        # A slanted column is a curve from base to top; without a top level
        # its upper end has no elevation, and guessing one would place the
        # column somewhere plausible and wrong.
        if n["op"] == "create_column" and "top_xy" in n and "top_level" not in n:
            diags.append(Diagnostic(
                code="KIR-T002", op_index=idx, op_id=n["id"],
                field_name="top_xy", expected="top_level",
                got=None,
                message_ru="top_xy задаёт наклонную колонну — нужен top_level, "
                           "иначе верх колонны не определён"))
        refs: list[tuple[str, Any, spec.ParamSpec]] = []
        for p in ospec.params:
            value = n.get(p.name)
            if p.kind in ("sel", "target_w") and isinstance(value, dict):
                if value.get("by") == "ref":
                    refs.append((p.name, value.get("value"), p))
            elif p.kind == "refs_w" and isinstance(value, list):
                for j, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    if item.get("by") == "ref":
                        refs.append((f"{p.name}[{j}]", item.get("value"), p))
                        continue
                    # THE SELECTOR'S SECOND STAGE (`{"by": "face", "of":
                    # ...}`).
                    #
                    # THE GRAPH EDGE IS TAKEN FROM INSIDE, AND THAT IS
                    # MANDATORY, NOT TIDY. The traversal below is not
                    # generic: it looks at exactly the TOP level of the
                    # list element. A reference that has moved one level
                    # deeper (into `of`) would become invisible to it —
                    # and then KIR-L003 ("ref does not point to an earlier
                    # op") and KIR-L004 (the result kind) would stop
                    # firing SILENTLY, and the emitter would reference a
                    # C# variable with no guarantee that the producing op
                    # comes earlier. That is exactly why the second stage
                    # carries the WHOLE selector, not a bare op id: the
                    # edge stays expressible in the same terms, and there
                    # is exactly one place that needs to know this — right
                    # here.
                    inner = item.get("of")
                    if (item.get("by") == faceref.BY_FACE
                            and isinstance(inner, dict)
                            and inner.get("by") == "ref"):
                        refs.append((f"{p.name}[{j}].of", inner.get("value"), p))
        # RELATE, AN ADDRESS FROM AN ELEMENT: the reference lives INSIDE
        # the value of a point-kind parameter, i.e. exactly one level
        # deeper — the level the block above warns about. The edge is
        # captured here, and captured as a SEPARATE list, not mixed into
        # `refs`: the kind check (KIR-L004) asks `param_spec.ref_kinds`,
        # and for the `pt_xy`/`pt_xyz` kind it is EMPTY by construction (a
        # point accepts no references) — so the shared branch would
        # refuse EVERY correct address. Kind is irrelevant here: the
        # address does not pass a reference into the C#, it READS the
        # numbers of the addressed op at compile time, and the only
        # requirement on the target is to stand ABOVE it. Which
        # operations are addressable at all is decided by
        # `relate.ELEMENT_GEOMETRY` at the ground stage: this list is
        # about order, not about geometry.
        for key, ref in relate.element_address_refs(n):
            if ref not in created:
                diags.append(Diagnostic(
                    code=PLAN_REF_ORDER, op_index=idx, op_id=n["id"],
                    field_name=f"{key}.at_element", got=ref,
                    candidates=sorted(created),
                    message_ru=(
                        f"адрес от элемента: «{ref}» не указывает на более "
                        f"ранний оп этой программы. Адрес читает числа, "
                        f"которые автор уже написал, поэтому адресуемый оп "
                        f"обязан стоять ВЫШЕ адресующего")))
        for key, ref, param_spec in refs:
            if ref not in created:
                # 🔴 THE MOST FREQUENT CASE IS NAMED BY NAME (26.08.2026).
                #
                # A measurement over the live corpus `kir_rejections.jsonl`:
                # this refusal happened 291 times, and in 290 of them
                # (99.7 %) the reference's value is NOT an operation name
                # but an ELEMENT IDENTIFIER with an `e` prefix:
                # «e11844649», «e12171249», «e11852152». By op: `create_tag`
                # 280, `create_door` 11. Of these, 96% are turns by the
                # MODEL, not our own admin sweeps, meaning this hits the
                # product, not the bench.
                #
                # In these cases the author meant to reference something
                # ALREADY BUILT — to hang a tag on an existing wall, to
                # hang a door in an existing opening — and picked the
                # wrong selector form. The earlier text was TRUE TO THE
                # LETTER ("ref points to an op of THIS program") and
                # silent about what to do: the `candidates` list offered
                # operations of the current program, among which the
                # needed one is not, and cannot be, present.
                #
                # A refusal that names the trouble and stays silent about
                # the cure is half the job; here the second half costs one
                # branch, because the author's intent reads straight off
                # the value.
                хвост = ""
                ядро = str(ref)[1:] if str(ref)[:1].lower() == "e" else str(ref)
                if ядро.isdigit() and len(ядро) >= 4:
                    хвост = (f". СЛЕДУЮЩИЙ ХОД: «{ref}» выглядит как "
                             f"идентификатор УЖЕ ПОСТРОЕННОГО элемента, а `ref` "
                             f"адресует только операции ЭТОЙ программы — "
                             f"напиши {{\"by\": \"element_id\", \"value\": "
                             f"{ядро}}}")
                diags.append(Diagnostic(
                    code=PLAN_REF_ORDER, op_index=idx, op_id=n["id"], field_name=key,
                    got=ref, candidates=sorted(created),
                    message_ru=(f"ref «{ref}» не указывает на более ранний "
                                f"оп с единичным referenceable-результатом"
                                f"{хвост}")))
            elif ref in deleted_refs:
                diags.append(Diagnostic(
                    code=PLAN_REF_DELETED, op_index=idx, op_id=n["id"],
                    field_name=key, got=ref,
                    expected="цель, не удалённая раньше в этой программе",
                    message_ru=(f"ref «{ref}» удалён опом «{deleted_refs[ref]}» "
                                f"раньше в этой же программе — эффект над "
                                f"удалённым невозможен. СЛЕДУЮЩИЙ ХОД: убери "
                                f"ссылку или поставь delete ПОСЛЕ последнего "
                                f"использования «{ref}»")))
            elif not param_spec.accepts_reference(
                    created[ref].reference_kind):
                expected = [kind.value for kind in param_spec.ref_kinds]
                actual = created[ref].reference_kind
                diags.append(Diagnostic(
                    code=PLAN_REF_KIND, op_index=idx, op_id=n["id"], field_name=key,
                    expected=expected,
                    got=actual.value if actual is not None else None,
                    message_ru=(f"ref «{ref}» должен указывать на результат "
                                "совместимого типизированного рода")))
        # THE RESULT KIND IS TAKEN FROM THE CALL, NOT FROM THE OP
        # (24.08.2026). `create_wall_type` produces four different kinds
        # depending on `host_kind`; reading `ospec.result` here would mean
        # recording a roof type in the table as "wall" and letting the
        # substitution slip through silently — exactly what the narrow
        # kind exists to prevent.
        # The same law applies to already-standing elements: an
        # `element_id` deleted earlier by this same program is no longer
        # addressable.
        if deleted_eids:
            for p in ospec.params:
                value = n.get(p.name)
                items = ([(p.name, value)] if p.kind in ("sel", "target_w")
                         else [(f"{p.name}[{j}]", it) for j, it in enumerate(value)]
                         if p.kind == "refs_w" and isinstance(value, list) else [])
                for key, item in items:
                    if not (isinstance(item, dict) and item.get("by") == "element_id"):
                        continue
                    try:
                        eid = int(item.get("value"))
                    except (TypeError, ValueError):
                        continue
                    if eid in deleted_eids:
                        diags.append(Diagnostic(
                            code=PLAN_REF_DELETED, op_index=idx, op_id=n["id"],
                            field_name=key, got=eid,
                            expected="элемент, не удалённый раньше в этой программе",
                            message_ru=(f"element_id {eid} удалён опом "
                                        f"«{deleted_eids[eid]}» раньше в этой же "
                                        f"программе — эффект над удалённым "
                                        f"невозможен. СЛЕДУЮЩИЙ ХОД: убери ссылку "
                                        f"или поставь delete ПОСЛЕ последнего "
                                        f"использования")))
        if n["op"] == "delete" and isinstance(n.get("target"), dict):
            _tgt = n["target"]
            if _tgt.get("by") == "ref":
                deleted_refs.setdefault(str(_tgt.get("value")), n["id"])
            elif _tgt.get("by") == "element_id":
                try:
                    deleted_eids.setdefault(int(_tgt.get("value")), n["id"])
                except (TypeError, ValueError):
                    pass
        _rspec = ospec.result_for(n)
        if _rspec.referenceable:
            created[n["id"]] = _rspec
        # CONTOUR: a straight polyline OR a typed sketch — exactly one.
        #
        # For an operation that can do both, the shape would be specified
        # TWICE, and "both at once" is exactly as ambiguous as "neither":
        # in the first case it's unclear which of the two descriptions is
        # true, in the second there is nothing to build. Both must be a
        # typed refusal, not a guess — the same law and the same code
        # KIR-P007 as `place_family` below.
        #
        # `outline` could not be replaced with `contour`: the reverse path
        # (decompile/materialize.py) emits exactly straight points, and
        # the substitution would have broken the loop open. Hence the
        # parallel field, hence this rule.
        #
        # THE RULE IS READ FROM THE REGISTRY, NOT FROM A LIST OF OP NAMES:
        # the pair is the `pts`-kind parameter and the `region`-kind
        # parameter of one operation. The next operation to get a sketch
        # will get the check bundled with the field, not as a separate
        # "we forgot" commit.
        #
        # THE HALF OF THE RULE THE PLAN HAS NO RIGHT TO STATE (09.08.2026,
        # the opening wave). "Both at once" is ALWAYS ambiguous and
        # refuses here. "Neither" is not: for an operation with a
        # `variety` fork (a closed set of Revit overloads; the
        # discriminator name is a registry convention, a NAMING NOTE in
        # `ops_struct.py`), whether the shape is required is CONDITIONAL
        # ON KIND, and the plan does not parse kinds. For create_opening,
        # the `wall_rect` kind has no shape at all — it is given by two
        # angles — and a blanket "shape not given" refusal would accuse a
        # correct program. The lower half of this mutual requirement
        # therefore lives in the kind's branch
        # (`opening_emit._emit_host_face`, a typed KIR-P005 naming BOTH
        # inputs), through exactly the same seam by which `create_railing`
        # and `create_foundation` hold their conditionally required
        # fields.
        outline_p = next((p.name for p in ospec.params if p.kind == "pts"), None)
        region_p = next((p.name for p in ospec.params if p.kind == "region"), None)
        variety_dispatched = any(p.name == "variety" for p in ospec.params)
        if outline_p and region_p:
            # A field that has already been called out more specifically
            # (a broken contour, a broken region) is not retold here in a
            # second, more generic voice.
            named = {d.field_name for d in diags if d.op_id == n["id"]}
            has_outline, has_region = outline_p in n, region_p in n
            if not (named & {outline_p, region_p}):
                if has_outline and has_region:
                    diags.append(Diagnostic(
                        code=PARSE_EXCLUSIVE_FIELDS, op_index=idx,
                        op_id=n["id"], field_name=region_p,
                        expected=f"{outline_p} ЛИБО {region_p}",
                        got=f"и {outline_p}, и {region_p}",
                        message_ru=(
                            f"{n['op']}: форма задана дважды — {outline_p} "
                            f"(прямая ломаная) и {region_p} (эскиз CONTOUR). "
                            f"Нужно ровно одно из двух: какое из описаний "
                            f"истинно, компилятор угадывать не станет")))
                elif not has_outline and not has_region and not variety_dispatched:
                    diags.append(Diagnostic(
                        code=PARSE_EXCLUSIVE_FIELDS, op_index=idx,
                        op_id=n["id"], field_name=outline_p,
                        expected=f"{outline_p} ЛИБО {region_p}", got=None,
                        message_ru=(
                            f"{n['op']}: форма не задана — нужен либо "
                            f"{outline_p} (ломаная из "
                            f"{_geom.MIN_RING_POINTS}..{_geom.MAX_RING_POINTS} точек), либо "
                            f"{region_p} (эскиз CONTOUR: rect/l/poly, дуги, "
                            f"отверстия)")))
            if has_region:
                # A region has its OWN holes (region.holes). Accepting a
                # flat `holes` alongside it as well would mean taking one
                # description of the openings and silently discarding the
                # other.
                for p in ospec.params:
                    if p.kind == "pts_list" and p.name in n:
                        diags.append(Diagnostic(
                            code=PARSE_EXCLUSIVE_FIELDS, op_index=idx,
                            op_id=n["id"], field_name=p.name,
                            expected=f"{p.name} ЛИБО {region_p}",
                            got=f"и {p.name}, и {region_p}",
                            message_ru=(
                                f"{n['op']}: {p.name} несовместим с "
                                f"{region_p} — у эскиза отверстия свои "
                                f"({region_p}.holes), и держать два описания "
                                f"проёмов сразу значит потерять одно из них")))
        # SPIRAL STAIR: straight endpoints OR a spiral — exactly one.
        #
        # The same law and the same code KIR-P007 as CONTOUR above and
        # place_family below, and for the same reason: for an operation
        # that can take either form, "both at once" is just as ambiguous
        # as "neither" — in the first case it's unclear which of the two
        # stair forms is true, in the second there is nothing to build. A
        # guess here would silently mean A DIFFERENT staircase.
        #
        # THE RULE IS READ FROM THE REGISTRY: the pair is the
        # `spiral`-kind parameter and the segment endpoints (kind
        # `pt_xy`) of one operation. The second op to get a spiral will
        # get the check bundled with the field, not as a separate "we
        # forgot" commit.
        #
        # Straight endpoints could not be replaced with a spiral: the
        # reverse path (decompile/lift.py::_lift_stairs) emits exactly
        # `p0_mm`/`p1_mm`.
        spiral_p = next((p.name for p in ospec.params if p.kind == "spiral"),
                        None)
        if spiral_p:
            ends = [p.name for p in ospec.params if p.kind == "pt_xy"]
            present_ends = [k for k in ends if k in n]
            has_spiral = spiral_p in n
            # A field that has already been called out more specifically
            # (a broken point, a broken spiral) is not retold here in a
            # second, more generic voice.
            named = {d.field_name for d in diags if d.op_id == n["id"]}
            if not (named & ({spiral_p} | set(ends))
                    or any(isinstance(f, str) and f.startswith(spiral_p + ".")
                           for f in named)):
                if present_ends and has_spiral:
                    diags.append(Diagnostic(
                        code=PARSE_EXCLUSIVE_FIELDS, op_index=idx,
                        op_id=n["id"], field_name=spiral_p,
                        expected=f"{'/'.join(ends)} ЛИБО {spiral_p}",
                        got=f"и {'/'.join(present_ends)}, и {spiral_p}",
                        message_ru=(
                            f"{n['op']}: марш задан дважды — "
                            f"{'/'.join(ends)} (прямой) и {spiral_p} "
                            f"(винтовой). Нужно ровно одно из двух: какая из "
                            f"двух форм истинна, компилятор угадывать не "
                            f"станет")))
                elif not present_ends and not has_spiral:
                    diags.append(Diagnostic(
                        code=PARSE_EXCLUSIVE_FIELDS, op_index=idx,
                        op_id=n["id"], field_name=ends[0],
                        expected=f"{'/'.join(ends)} ЛИБО {spiral_p}", got=None,
                        message_ru=(
                            f"{n['op']}: марш не задан — нужны либо оба конца "
                            f"{'/'.join(ends)} (прямой марш), либо "
                            f"{spiral_p} (винтовой: center_mm, radius_mm, "
                            f"start_angle_deg, included_angle_deg, "
                            f"clockwise)")))
                elif len(present_ends) == 1:
                    # Half of a straight flight is not a flight: one
                    # endpoint of a segment does not define a line (the
                    # same argument as `place_family`'s).
                    diags.append(Diagnostic(
                        code=PARSE_EXCLUSIVE_FIELDS, op_index=idx,
                        op_id=n["id"], field_name=present_ends[0],
                        expected=f"{'/'.join(ends)} вместе",
                        got=present_ends[0],
                        message_ru=(
                            f"{n['op']}: одна точка марша не задаёт прямую "
                            f"лестницу — нужны оба конца "
                            f"{'/'.join(ends)}, либо винтовой {spiral_p} "
                            f"вместо них")))
        # place_family: exactly ONE way to give a position.
        #
        # In Revit these are two different NewFamilyInstance overloads —
        # by point and by curve — and the choice between them is not made
        # by the program's author but by the family itself: a CurveBased
        # instance has no LocationPoint. So "both" and "neither" are
        # equally ambiguous, and both must be a refusal, not a guess. Half
        # a curve is also not a curve: one point does not define a
        # segment.
        if n["op"] == "place_family":
            has_point = "xyz" in n
            ends = [k for k in ("p0_mm", "p1_mm") if k in n]
            if len(ends) == 1:
                diags.append(Diagnostic(
                    code=PARSE_EXCLUSIVE_FIELDS, op_index=idx, op_id=n["id"],
                    field_name=ends[0], expected="p0_mm и p1_mm вместе",
                    got=ends[0],
                    message_ru="одна точка отрезка не задаёт кривую: нужны "
                               "оба конца p0_mm и p1_mm"))
            elif has_point and ends:
                diags.append(Diagnostic(
                    code=PARSE_EXCLUSIVE_FIELDS, op_index=idx, op_id=n["id"],
                    field_name="xyz", expected="xyz ЛИБО p0_mm/p1_mm",
                    got="и точка, и кривая",
                    message_ru="place_family ставится либо в точку (xyz), "
                               "либо по кривой (p0_mm/p1_mm) — вместе они "
                               "неоднозначны"))
            elif not has_point and not ends:
                diags.append(Diagnostic(
                    code=PARSE_EXCLUSIVE_FIELDS, op_index=idx, op_id=n["id"],
                    field_name="xyz", expected="xyz ЛИБО p0_mm/p1_mm",
                    got=None,
                    message_ru="place_family не задано положение: нужна "
                               "точка xyz или кривая p0_mm/p1_mm"))
            # The requirement is CONDITIONAL, and that's why it lives
            # here, not in the schema.
            #
            # The point variant calls NewFamilyInstance(point, symbol,
            # LEVEL, …) — there is no call without a level. The curve
            # variant calls NewFamilyInstance(REFERENCE, line, symbol) —
            # it does not accept a level at all, but cannot exist without
            # a host.
            #
            # Why exactly this way, measured 27.07 on a live ЭОМ model:
            # the level overload projected a vertical segment onto the
            # level's plane and collapsed it into a point, while the
            # reference overload honestly refused with "line does not
            # coincide with the input face" when the segment did not lie
            # on the host's face. A curve-based family WITHOUT a host is
            # served by create_beam — it has its own overload and its own
            # type pool.
            if has_point and "level" not in n:
                diags.append(Diagnostic(
                    code=PARSE_MISSING_FIELD, op_index=idx, op_id=n["id"],
                    field_name="level", expected="селектор уровня",
                    message_ru="place_family в точку требует level"))
            if ends and "host" not in n:
                diags.append(Diagnostic(
                    code=PARSE_MISSING_FIELD, op_index=idx, op_id=n["id"],
                    field_name="host", expected="селектор хоста",
                    message_ru="place_family по кривой требует host: Revit "
                               "ставит такое семейство по ссылке на грань "
                               "хоста, а не на уровень"))
        # hosted ops: offset must fit INSIDE the host wall (compile-time
        # topology — "a door past the wall's edge" is unexpressible, SPEC §4)
        if n["op"] in ("create_window", "create_door"):
            host = n.get("host") or {}
            wall = byid.get(host.get("value"))
            if wall is not None and wall.get("op") == "create_wall" \
                    and "p0_mm" in wall and "p1_mm" in wall \
                    and not relate.is_address(wall["p0_mm"]) \
                    and not relate.is_address(wall["p1_mm"]):
                # The addressed host is checked by THE SAME judge in
                # `ground`, once its endpoints become numbers — see
                # hosted_offset_check.
                hosted_offset_check(
                    n, wall, str(host.get("value")), idx, diags,
                    shift=_geom.same_program_shift(normed, idx, str(host.get("value"))))
        if n["op"] == "move_elements":
            reject_move_beyond_scene(normed, idx, n, byid, diags)
    # policy-gate on the plan (SPEC 12.2): destructive ops need explicit opt-in
    if any(n["op"] == "delete" for n in normed) and program.get("allow_destructive") is not True:
        diags.append(Diagnostic(
            code=PLAN_DESTRUCTIVE_UNCONFIRMED, field_name="allow_destructive",
            expected=True, got=program.get("allow_destructive"),
            message_ru="delete требует allow_destructive=true в конверте программы"))
    if diags:
        _refusal = KirRefusal(diags)
        # The muteness seam must read THE SAME list against which indices
        # were assigned, not the author's envelope (see
        # `KirRefusal.expanded_ops`).
        _refusal.expanded_ops = list(ops)
        raise _refusal
    return normed, tuple(plan_traces), tuple(nested_member_plans)


def plan_program(program: Any, *, bulk: bool = False) -> PlannedProgram:
    """Parse/typecheck/plan once and return the immutable semantic program.

    Unlike :func:`compile_program`, this planning API intentionally raises
    :class:`KirRefusal`: it is the composable mid-end boundary used by trusted
    KIR stages.  The public compile facade still converts every refusal to a
    ``CompileOutput``.
    """
    if isinstance(program, PlannedProgram):
        if program.bulk is not bulk:
            raise KirRefusal([Diagnostic(
                code=PLAN_BULK_MISMATCH,
                field_name="bulk",
                expected=program.bulk,
                got=bulk,
                message_ru=("политика bulk не совпадает с уже построенным "
                            "неизменяемым планом"),
            )])
        # Archived typed plans predate some wire-contract corrections. Do not
        # lower a formerly admitted ID that the flat result would overwrite.
        collisions = [Diagnostic(
            code=TYPE_BAD_TYPE, op_index=i, op_id=op.op_id, field_name="id",
            got=op.op_id, expected="operation id outside program result metadata",
            message_ru=f"id опа {op.op_id!r} занят метаданными результата программы; нужен новый план с другим id",
        ) for i, op in enumerate(program.ops)
            if op.op_id in spec.PROGRAM_RESULT_METADATA_KEYS]
        if collisions:
            raise KirRefusal(collisions)
        return program

    normed, traces, nested_plans = _parse_and_check_internal(
        program, bulk=bulk)
    if len(normed) != len(traces) or len(normed) != len(nested_plans):
        raise RuntimeError("normalised operations lost their planning trace")
    planned_ops: list[PlannedOp] = []
    for payload, trace, member_plans in zip(normed, traces, nested_plans):
        ospec = spec.OPS[payload["op"]]
        registry_defaults = {
            param.name for param in ospec.params
            if param.default is not None and param.name not in trace.expanded_fields
        }
        origins: list[tuple[str, FieldOrigin]] = []
        for field_name in sorted(payload):
            if field_name in trace.defaulted_fields:
                origin = FieldOrigin.ENVELOPE_DEFAULT
            elif field_name not in trace.expanded_fields:
                origin = (
                    FieldOrigin.REGISTRY_DEFAULT
                    if field_name in registry_defaults
                    else FieldOrigin.COMPILER_DERIVED
                )
            elif trace.macro_name is not None:
                origin = FieldOrigin.MACRO_DERIVED
            else:
                origin = FieldOrigin.EXPLICIT
            origins.append((field_name, origin))
        provenance = OpProvenance(
            source_index=trace.source_index,
            source_op=trace.source_op,
            source_id=trace.source_id,
            macro_name=trace.macro_name,
            field_origins=tuple(origins),
        )
        try:
            op_contract = contract_for(ospec.name)
            planned_ops.append(PlannedOp.from_dict(
                payload,
                family=OperationFamily(ospec.family),
                effect=ospec.effect,
                # The result kind belongs to THIS payload, not merely to
                # the op's name. ``create_wall_type`` is one op with four
                # typed results, selected by `host_kind`; the static
                # default here used to record a floor/roof/ceiling type as
                # a wall type in the immutable plan, even though typecheck
                # and ground already read the payload-bound contract.
                result=ospec.result_for(payload),
                contract_digest=op_contract.digest,
                provenance=provenance,
                nested_contracts=tuple(
                    NestedOpContract.from_planned_op(item)
                    for item in member_plans
                ),
            ))
        except OpContractError as exc:
            # A write without a complete lowering/refinement contract is not
            # an unexpected compiler panic and is never safe to execute.  It
            # is a named pre-effect planning refusal: no snapshot read or
            # Bridge dispatch is needed to prove that the compiler cannot
            # bind this operation to its promised witnesses.
            raise KirRefusal([Diagnostic(
                code=PLAN_OP_CONTRACT,
                op_index=trace.source_index,
                op_id=payload.get("id"),
                field_name="op",
                expected="complete canonical operation contract",
                got=ospec.name,
                message_ru=(
                    "операция не имеет полного канонического контракта "
                    "понижения и поэтому не может быть исполнена"),
            )]) from exc
        except PlanEncodingError as exc:
            # A nested NaN historically slipped through a few deep validators
            # and failed later as an internal compiler panic. The typed plan is
            # a JSON IR boundary: non-canonical data is a typed input refusal.
            raise KirRefusal([Diagnostic(
                code=TYPE_BAD_TYPE,
                op_index=len(planned_ops),
                op_id=payload.get("id"),
                field_name="op",
                got=str(exc)[:200],
                message_ru=("нормализованный op содержит не-JSON или "
                            "неконечное числовое значение"),
            )]) from exc

    family = (
        ProgramFamily.QUERY
        if planned_ops[0].family is OperationFamily.QUERY
        else ProgramFamily.WRITE
    )
    return PlannedProgram(
        # 🔴 `.get(...) or` — NOT AN INDEX, AND THIS WAS BOUGHT BY A PANIC
        # WITHIN THE SAME HOUR. On 17.08 the "print `ir_version`" ritual was
        # lifted from envelope parsing, but here the key was still read by
        # DIRECT INDEXING — and the very first program without it dropped
        # the compiler into `KIR-P000`. A default implied in one place and
        # not materialized in another is our named defect: the value is
        # ASSERTED at parsing and READ at planning, and nothing tied the
        # two together.
        ir_version=program.get("ir_version") or spec.IR_VERSION,
        family=family,
        ops=tuple(planned_ops),
        intent=program.get("intent", ""),
        allow_destructive=program.get("allow_destructive") is True,
        bulk=bulk,
        # INTENT RIDES ON PAST THE PLAN (25.08.2026). Without this line the
        # live door lost the unit table: it passes `PlannedProgram` down,
        # not a dict, and `_units_of` returned empty ALWAYS.
        units=tuple(_units_of(program)),
        # The same basis as the version line above: a single operation
        # written without a list has been legitimate since 17.08, and its
        # count cannot be taken via `len` of the dict — that would return
        # the number of the operation's KEYS instead of one.
        source_op_count=(1 if isinstance(program.get("ops"), dict)
                         else len(program.get("ops") or ())),
        program_id=program.get("program_id"),
        lineage=program.get("lineage"),
    )


def _parse_and_check(program: Any, *, bulk: bool = False) -> list[dict]:
    """Compatibility shim for legacy ground/emitter tests.

    New downstream code must consume :func:`plan_program`; this returns fresh
    dicts so a legacy caller cannot mutate the immutable plan.
    """
    return plan_program(program, bulk=bulk).to_ops()


# ═════════════════════════════════════════════════════════════════════════════
# CONSTRUCTION PLAN — ONE SCRIPT IS CUT INTO A BATCH OF PROGRAMS
# ═════════════════════════════════════════════════════════════════════════════
#
# WHAT THIS CLOSES, BY THE NUMBER. Today a building cannot be written as
# one script AT ALL: a script with `phase()` gets TWO refusals AT ONCE —
# KIR-P003 ("unknown envelope field 'phases'") and KIR-L002 ("create_stairs
# — the sole op of its own program") — and the second refusal itself
# advises exactly the work the model has to do in its head: "a building is
# a BATCH of programs: the body separate, the stairs separate; the level
# is available to the stair program BY NAME." A measurement over the
# refusal corpus (`data/telemetry/kir_rejections.jsonl`, 1469 lines,
# 16.07–04.08, counted by authorship attempts, not lines: 349 attempts
# when the lines of one compilation are glued together —
# `coverage_feed.record_rejections` writes them one after another, each
# with its own now()):
# in 105 of 349 attempts (30.1%), the refusal is a PROGRAM BOUNDARY, and
# none of its four kinds is a geometry error:
#
#     program budget (KIR-L001)             50 attempts
#     cross-boundary reference (KIR-L003)   44
#     level not found BY NAME               10   ← exactly the advice above
#     a solo op with a neighbor (KIR-L002)   1
#
# The author already draws the boundary markup (`course.phase()`, 09.08).
# What stands here is the SECOND half: the plan turns into a BATCH of
# programs — the very unit the building already is for the judge
# (`design_check.check_bundle`), for the drawing (`preview`), and for the
# showroom (`live/plan_stream`). No second mechanism is introduced: both
# the input (the `phases` table) and the output (the batch) already
# existed.
#
# WHAT IS NOT HERE AND WILL NOT BE. The `MAX_OPS_PER_PROGRAM` budget is
# not raised by a single unit: every link of the batch goes through the
# same `plan_program` and is measured by the same budget. The plan does
# not let you write a BIGGER program — it lets you write a BUILDING,
# without tallying the boundary in your head.


@dataclass(frozen=True)
class PhaseLink:
    """One link of the plan: the phase's name, its number, and its
    PROGRAM.

    The name rides ALONGSIDE the program, not inside it, and that is not
    a style choice: the program envelope is closed (`known_top`), and an
    extra field in it is a typed refusal, KIR-P003. A link must be a
    program indistinguishable from one written by hand, or "the same
    thing gets executed" would stop being true.
    """

    index: int
    name: str
    program: dict


def _refuse_plan(message: str, **fields: Any) -> KirRefusal:
    return KirRefusal([Diagnostic(code=PLAN_PHASE_SHAPE,
                                  message_ru=message, **fields)])


def split_phases(program: Any) -> list[PhaseLink]:
    """A program with a `phases` table -> a BATCH of programs, one per
    phase.

    A PURE FUNCTION: it executes nothing, grounds nothing, touches not a
    single op. Ops ride into the links BYTE-FOR-BYTE unchanged — their
    digest signs the intent, and an op rewritten along the way would make
    the signature the signature of something else.

    THE LAW CHECKED HERE IS EXACTLY ONE — THE PARTITION. The `op_ids` of
    all phases, concatenated in order, must be THE SAME list of ids as
    the program's `ops`: the same order, each exactly once. Everything
    else — budget, solo-op, the reference DAG, number bounds — is checked
    by `plan_program` OVER EACH LINK, and repeating it here would mean
    setting up a second instance of the rule, one that will diverge from
    the first on the very next registry edit.

    WHY ANYTHING IS CHECKED AT ALL, given that the table is built by
    `course.phase()`, which already holds it. Because the table arrives
    in the ENVELOPE, and anyone can send an envelope: `serving` cannot
    tell an envelope assembled by the sandbox from one typed by hand. The
    partition is the one fact that cannot be recovered from anywhere else
    here, and a silently swallowed extra op would mean an element that
    nobody builds and that nobody reports.
    """
    if not isinstance(program, dict):
        raise _refuse_plan("план строительства — это программа с таблицей "
                           "`phases` в конверте",
                           field_name="program",
                           got=type(program).__name__)
    phases = program.get("phases")
    ops = program.get("ops")
    if not isinstance(ops, list) or not ops:
        raise _refuse_plan("ops — непустой список", field_name="ops")
    if not isinstance(phases, list) or not phases:
        raise _refuse_plan(
            "у плана строительства обязана быть непустая таблица `phases`",
            field_name="phases", got=type(phases).__name__)
    flat: list[str] = []
    links: list[PhaseLink] = []
    envelope = {key: value for key, value in program.items()
                if key not in ("ops", "phases")}
    by_id = {}
    for позиция, op in enumerate(ops):
        if not isinstance(op, dict) or not isinstance(op.get("id"), str):
            raise _refuse_plan(
                "план режется ПО ИДЕНТИФИКАТОРАМ опов, и оп без строкового "
                "`id` в нём неадресуем",
                field_name="ops", got=type(op).__name__)
        if op["id"] in by_id:
            # 🔴 THIS IS NOT A SECOND INSTANCE OF THE RULE, BUT THE
            # PARTITION LAW ITSELF (24.08.2026, an audit finding,
            # reproduced by a run).
            #
            # The check below compared LISTS OF NAMES (`flat != written`) —
            # that is, it read the SHAPE, not the SUBJECT. On two ops
            # sharing one id it saw ['a','a'] against ['a','a'] and stayed
            # silent, while `by_id` had by then ALREADY swallowed the
            # first op. Measured verbatim:
            #
            #     ops    = [create_level id=a "Floor 1", create_level id=a "Floor 2"]
            #     phases = [{0: [a]}, {1: [a]}]
            #     -> two links, "Floor 2" IN BOTH. NOBODY builds "Floor 1",
            #        "Floor 2" is built TWICE, each in its own
            #        transaction, and NOT A SINGLE diagnostic.
            #
            # The partition is a mapping of ops, not of names: two
            # DIFFERENT ops with one address make the partition impossible
            # by construction, and it is this very check's job to say so,
            # not a neighboring one's.
            #
            # `plan_program` over a link can NEVER catch this: inside each
            # link the id is already unique. Hence it's here — and the
            # same code is used (`PARSE_DUP_ID`), so the author sees a
            # familiar refusal, not a new kind.
            raise KirRefusal([Diagnostic(
                code=PARSE_DUP_ID, op_index=позиция, op_id=op["id"],
                field_name="id",
                expected=(f"id != {op['id']!r} "
                          f"(занят опом №{list(by_id).index(op['id'])})"),
                message_ru=(
                    f"дубликат id {op['id']!r}: он уже занят опом "
                    f"№{list(by_id).index(op['id'])}, а план режется ПО "
                    f"ИДЕНТИФИКАТОРАМ — два опа с одним адресом сделали бы "
                    f"разбиение невозможным: одна фаза построила бы чужой оп "
                    f"дважды, а первый не построил бы никто. СЛЕДУЮЩИЙ ХОД: "
                    f"дай ЭТОМУ опу другой id"))])
        by_id[op["id"]] = op
    for position, row in enumerate(phases):
        if not isinstance(row, dict):
            raise _refuse_plan(
                f"строка `phases[{position}]` — не объект",
                field_name="phases", got=type(row).__name__)
        if row.get("index") != position:
            raise _refuse_plan(
                f"фазы плана нумеруются подряд с нуля, а `phases[{position}]` "
                f"назвалась номером {row.get('index')!r}. Номер фазы — её "
                f"адрес в отчёте и в метке `{spec.CROSS_PHASE_BY}`, и пропуск "
                f"в нумерации сделал бы этот адрес неоднозначным",
                field_name="phases", expected=position, got=row.get("index"))
        name = row.get("name")
        if not isinstance(name, str) or not name.strip():
            raise _refuse_plan(
                f"у фазы №{position} нет имени: отказ и отчёт называют фазу, "
                f"на которой план встал, и безымянное звено нечем назвать",
                field_name="phases", got=repr(name))
        op_ids = row.get("op_ids")
        if not isinstance(op_ids, list) or not op_ids:
            raise _refuse_plan(
                f"фаза «{name}» (№{position}) не назвала ни одной операции. "
                f"Пустая фаза — это пустая транзакция и лишний чекпойнт",
                field_name="phases", got=op_ids)
        link_ops = []
        for oid in op_ids:
            if not isinstance(oid, str) or oid not in by_id:
                raise _refuse_plan(
                    f"фаза «{name}» (№{position}) называет операцию "
                    f"{oid!r}, которой в программе нет",
                    field_name="phases", got=oid,
                    candidates=sorted(by_id)[:12])
            link_ops.append(by_id[oid])
        flat.extend(op_ids)
        links.append(PhaseLink(
            index=position, name=name.strip(),
            program={**envelope, "ops": link_ops}))
    written = [op["id"] for op in ops]
    if flat != written:
        # Count once even on a malformed building-sized phase table.
        named = Counter(flat)
        missing = [oid for oid in written if oid not in named]
        twice = sorted(oid for oid, count in named.items() if count > 1)
        raise _refuse_plan(
            f"таблица `phases` не является РАЗБИЕНИЕМ программы: она называет "
            f"{len(flat)} адресов при {len(written)} операциях"
            + (f"; не попали в план: {', '.join(missing[:8])}" if missing else "")
            + (f"; названы дважды: {', '.join(twice[:8])}" if twice else "")
            + (""
               if (missing or twice) else
               "; порядок фаз разошёлся с порядком операций в скрипте"),
            field_name="phases", expected=len(written), got=len(flat),
            candidates=(missing or twice)[:12])
    return links


def phase_products(ops: Sequence[Any], payload: Any) -> dict[str, int]:
    """An op's id -> the ElementId taken from this phase's EXECUTION
    RECEIPT.

    WHAT COUNTS AS A PRODUCT. Only a result the registry has declared
    REFERENCEABLE (`ResultSpec.referenceable`) — that is, exactly what
    `by=ref` is legitimately allowed to target inside a program. A group
    and a deletion carry identity and are NOT referenceable, and that is
    recorded in `ResultSpec`'s own docstring: substituting their id into
    the next phase's selector would mean allowing more across the
    boundary than is allowed inside a program.

    WHERE THE NUMBER LIVES IS STATED BY THE REGISTRY (`identity_field`),
    not guessed from a key's name. Today the key is `"id"` everywhere,
    but it is declared as a spec field, and a hardcoded `"id"` string
    would have silently diverged from the registry.

    SILENCE HERE IS LEGITIMATE: a row without identity simply does not
    become a product. The refusal is raised by the CONSUMER
    (`substitute_phase_results`) when a tag looks for a product and does
    not find it — because only there is it known that it was actually
    expected.
    """
    products: dict[str, int] = {}
    if not isinstance(payload, dict):
        return products
    for op in ops:
        if not isinstance(op, dict):
            continue
        ospec = spec.OPS.get(op.get("op"))
        if ospec is None or not ospec.result.referenceable:
            continue
        row = payload.get(op.get("id"))
        if not isinstance(row, dict):
            continue
        value = row.get(ospec.result.identity_field)
        if isinstance(value, bool):
            continue
        try:
            number = int(value)                     # the bridge sends both "42" and 42
        except (TypeError, ValueError):
            continue
        if 1 <= number <= ELEMENT_ID_MAX:
            products[str(op["id"])] = number
    return products


def substitute_phase_results(program: Any, products: Any) -> dict:
    """`phase_result` tags -> `{"by": "element_id", "value": <int>}`.

    THIS IS THE ONE AND ONLY THING THAT CROSSES A PROGRAM BOUNDARY.
    `by=ref` does NOT cross the boundary and cannot: the neighboring
    phase is executed as a SEPARATE transaction, and by this point there
    is no in-program reference to its element. What does exist is the
    real ElementId in that phase's receipt; the substitution carries it
    to wherever the author placed the tag, and by doing exactly that it
    relieves the author of retyping the id from a past receipt.

    A PRODUCT NOT FOUND IS A TYPED REFUSAL, NOT A PASS-THROUGH. A tag is
    an OBLIGATION to substitute: leaving it as-is would mean sending
    `plan_program` a selector form that doesn't exist in the language,
    and getting a refusal that points at the wrong cause.
    """
    if not isinstance(program, dict):
        raise _refuse_plan("звено плана — программа", field_name="program",
                           got=type(program).__name__)
    table = products if isinstance(products, dict) else {}

    def walk(value: Any, oid: str) -> Any:
        if isinstance(value, dict):
            if value.get("by") == spec.CROSS_PHASE_BY:
                producer = str(value.get("value"))
                number = table.get(producer)
                if number is None:
                    raise _refuse_plan(
                        f"оп `{oid}` ссылается на результат фазы "
                        f"№{value.get('phase')} (оп `{producer}`), а та фаза "
                        f"не вернула его ElementId. Подставить нечего: "
                        f"свидетель произведшей фазы такого продукта не "
                        f"назвал",
                        field_name="by=" + spec.CROSS_PHASE_BY, op_id=oid,
                        got=producer, candidates=sorted(table)[:12])
                return {"by": "element_id", "value": number}
            return {key: walk(item, oid) for key, item in value.items()}
        if isinstance(value, list):
            return [walk(item, oid) for item in value]
        return value

    ops = []
    for op in program.get("ops") or ():
        if not isinstance(op, dict):
            ops.append(op)
            continue
        oid = str(op.get("id"))
        ops.append({key: (item if key in ("op", "id") else walk(item, oid))
                    for key, item in op.items()})
    return {**{k: v for k, v in program.items() if k != "ops"}, "ops": ops}


# ── emit ─────────────────────────────────────────────────────────────────────

def _emit_collector(kind: str, where: dict, var: str) -> str:
    ks = spec.KINDS[kind]
    preds = []
    if ks.where_cs:
        preds.append(ks.where_cs)
    if "name_contains" in where:
        preds.append(f"__NameOf(e).IndexOf({_cs_str(where['name_contains'])}, "
                     f"StringComparison.OrdinalIgnoreCase) >= 0")
    if "structural" in where:
        want = "1" if where["structural"] else "0"
        preds.append("(e.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT) != null "
                     f"&& e.get_Parameter(BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT).AsInteger() == {want})")
    if "level_name" in where:
        preds.append(f"__LevelNameOf(e).Trim() == {_cs_str(where['level_name'].strip())}")
    chain = f"new FilteredElementCollector(doc){ks.collector_cs}.Cast<Element>()"
    if preds:
        chain += "".join(f"\n    .Where(e => {p})" for p in preds)
    # FilteredElementCollector does not promise enumeration order.  Sorting
    # before Take() makes paging/limits deterministic instead of allowing the
    # same document to return a different prefix between runs.
    return f"var {var} = {chain}\n    .OrderBy(e => __IdOf(e))\n    .ToList();"


#: Оценка веса одной строки в байтах. ЧИСЛО ОЦЕНОЧНОЕ, и названо так нарочно:
#: точный вес известен только после сериализации, а отказывать надо ДО того, как
#: 8 MiB уже лежат в памяти Ревита владельца. Оценка завышена (самая тяжёлая
#: строка — `sketch`-контур), поэтому предел срабатывает раньше настоящего, а не
#: позже: ошибаться здесь можно только в сторону отказа.
_LEVEL_PLAN_ROW_BYTES = {"walls": 220, "floors": 160, "columns": 180, "openings": 220}
_LEVEL_PLAN_SKETCH_POINT_BYTES = 24

#: Потолок ответа. Тот же, что у песочницы (`kir/sandbox.py`
#: `MAX_RESULT_BYTES = 8 * 1024 * 1024`) — и это не совпадение, а причина:
#: перешагнув его, ответ всё равно был бы усечён ниже по тракту, но БЕЗ имени.
_LEVEL_PLAN_MAX_BYTES = 8 * 1024 * 1024


def _emit_level_plan(op: dict, oid: str, revit_version: str) -> str:
    """`query_level_plan` — плановый след уровня ПАЧКОЙ, за один вызов.

    🔴 ТРИ СВОЙСТВА, КОТОРЫЕ ЗДЕСЬ НЕСУЩИЕ, И НИ ОДНО ИЗ НИХ НЕ УКРАШЕНИЕ.

    1. СЧЁТ ИДЁТ ДО ИЗВЛЕЧЕНИЯ ГЕОМЕТРИИ. Коллекторы считаются дёшево
       (`.Count` по `ToElementIds`), сумма сверяется с `limit`, и только потом
       читается хоть один `LocationCurve`. Отказ, наступивший после того, как
       геометрия этажа уже собрана в память, — это не предел, а отчёт о
       превышении. Правило оплачено живьём 13.09.2026 в шаге §4 окна: круг
       последствий называется ДО эффекта.
    2. ПОРЯДОК СТАБИЛЬНЫЙ ПО `element_id` — ответ W 2. Лист перерисовывается
       каждым кадром, выделение в окне работает по `data-el`, и при плавающем
       порядке узлы тасуются: клик слетает, а каждый кадр читается как
       изменение здания. Сортировка здесь, а не у W: два источника правды о
       порядке — это уже наш именованный дефект.
    3. ОТСУТСТВИЕ ≠ ПУСТОТА ≠ УСЕЧЕНИЕ. `rows: []` — читали, на уровне ничего
       нет; `truncated: true` + `limit_hit` — читали не всё; а отсутствия
       `result` этот оп вообще не производит (его производит невызов). Правило
       не моё: так уже записано в докстроке `open_model.prune_ground_snapshot`
       («empty means "we asked, there are no sections", absence means "we didn't
       ask"»). Половина фона не имеет права выглядеть как весь фон.
    """
    sel = op["level"]
    include = list(op.get("include") or spec.LEVEL_PLAN_INCLUDE)
    detail = op.get("detail", "box")
    limit = int(op.get("limit", spec.LEVEL_PLAN_LIMIT_DEFAULT))
    v = cs_identifier_fragment(oid)
    r = f"__lp_{v}"

    if sel["by"] == "name":
        find = (f'    Level {r}Lv = new FilteredElementCollector(doc).OfClass(typeof(Level))\n'
                f'        .Cast<Level>().FirstOrDefault(__x => (__x.Name ?? "").Trim() == '
                f'{_cs_str(str(sel["value"]).strip())});\n')
    else:
        # Литерал ElementId — версионно-зависимый (32 бита до 2024, 64 после),
        # и берётся у единственного его автора, а не собирается здесь заново.
        from kir.emit_core import _eid as _eid_literal
        find = (f'    Level {r}Lv = doc.GetElement('
                f'{_eid_literal(int(sel["value"]), revit_version, oid)}) as Level;\n')

    # Категории по родам следов. Проёмы — своими строками (ответ W 4): проём,
    # выведенный из хозяина, был бы вторым источником правды о том, где он стоит.
    cats = {"walls": "BuiltInCategory.OST_Walls",
            "floors": "BuiltInCategory.OST_Floors",
            "columns": "BuiltInCategory.OST_Columns",
            "openings": None}
    counts, extract = [], []
    for grp in include:
        g = f"{r}_{grp}"
        if grp == "openings":
            counts.append(
                f'    var {g} = new FilteredElementCollector(doc)\n'
                f'        .WherePasses(new ElementMulticategoryFilter(new List<BuiltInCategory> {{\n'
                f'            BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows }}))\n'
                f'        .WhereElementIsNotElementType().Cast<Element>()\n'
                f'        .Where(__x => __x.LevelId != null && __x.LevelId == {r}Lv.Id).ToList();\n')
        else:
            counts.append(
                f'    var {g} = new FilteredElementCollector(doc)\n'
                f'        .OfCategory({cats[grp]}).WhereElementIsNotElementType().Cast<Element>()\n'
                f'        .Where(__x => __x.LevelId != null && __x.LevelId == {r}Lv.Id).ToList();\n')
        extract.append(g)

    # 🔴 СУММА СЧИТАЕТСЯ ЗДЕСЬ, И ЗДЕСЬ ЖЕ ОТКАЗ — ни одной координаты выше.
    total = " + ".join(f"{g}.Count" for g in extract) or "0"
    guard = (
        f'    int {r}Total = {total};\n'
        f'    {r}["total"] = {r}Total;\n'
        f'    if ({r}Total > {limit})\n'
        f'    {{\n'
        f'        {r}["error"] = "level_plan_too_many_elements";\n'
        f'        {r}["message"] = "на уровне " + {r}Total.ToString() + " элементов, предел limit = {limit}"\n'
        f'            + "; следующий ход: сузь include (сейчас {", ".join(include)}) '
        f'либо подними limit (максимум {spec.LEVEL_PLAN_LIMIT_MAX})";\n'
        f'        {r}["rows"] = new List<object>(); {r}["truncated"] = true;\n'
        f'        {r}["limit_hit"] = "elements";\n'
        f'        __results[{_cs_str(oid)}] = {r};\n'
        f'    }}\n'
        f'    else\n'
        f'    {{\n')

    rows = [f'        var {r}Rows = new List<Dictionary<string, object>>();\n'
            f'        int {r}Bytes = 0; bool {r}Cut = false;\n']
    for grp in include:
        g = f"{r}_{grp}"
        est = _LEVEL_PLAN_ROW_BYTES[grp]
        rows.append(
            f'        foreach (var __e in {g})\n'
            f'        {{\n'
            f'            if ({r}Cut) break;\n'
            f'            var __row = new Dictionary<string, object>();\n'
            f'            __row["kind"] = {_cs_str(_LEVEL_PLAN_KIND[grp])};\n'
            f'            __row["element_id"] = __e.Id.ToString();\n'
            f'            __row["unique_id"] = __e.UniqueId ?? "";\n'
            + _LEVEL_PLAN_BODY[grp](detail) +
            f'            {r}Bytes += {est};\n'
            f'            if ({r}Bytes > {_LEVEL_PLAN_MAX_BYTES}) {{ {r}Cut = true; break; }}\n'
            f'            {r}Rows.Add(__row);\n'
            f'        }}\n')

    tail = (
        f'        {r}["rows"] = {r}Rows\n'
        f'            .OrderBy(__x => {{ long __n; return long.TryParse(Convert.ToString(__x["element_id"]), out __n) ? __n : long.MaxValue; }})\n'
        f'            .Select(__x => (object)__x).ToList();\n'
        f'        {r}["returned"] = {r}Rows.Count;\n'
        f'        {r}["truncated"] = {r}Cut;\n'
        f'        {r}["limit_hit"] = {r}Cut ? "bytes" : null;\n'
        f'        if ({r}Cut)\n'
        f'            {r}["message"] = "ответ перешёл предел {_LEVEL_PLAN_MAX_BYTES} байт '
        f'(level_plan_too_large); следующий ход: возьми detail=box либо раздели include на два вызова";\n'
        f'        __results[{_cs_str(oid)}] = {r};\n'
        f'    }}\n')

    return (f"// {op['op']} {cs_line_comment_fragment(oid)}\n"
            f"{{\n"
            f'    var {r} = new Dictionary<string, object>();\n'
            f'    {r}["detail"] = {_cs_str(detail)};\n'
            f'    {r}["include"] = new List<object> {{ {", ".join(_cs_str(x) for x in include)} }};\n'
            + find
            + f'    if ({r}Lv == null)\n'
              f'    {{\n'
              f'        {r}["error"] = "not_found";\n'
              f'        {r}["message"] = "уровень не найден: фон не прочитан, и это НЕ пустой уровень";\n'
              f'        __results[{_cs_str(oid)}] = {r};\n'
              f'    }}\n'
              f'    else\n'
              f'    {{\n'
            + f'    {r}["level"] = new Dictionary<string, object> {{\n'
              f'        {{ "name", {r}Lv.Name ?? "" }}, {{ "element_id", {r}Lv.Id.ToString() }},\n'
              f'        {{ "unique_id", {r}Lv.UniqueId ?? "" }} }};\n'
            + "".join(counts)
            + guard
            + "".join(rows)
            + tail
            + f'    }}\n'
              f"}}")


_LEVEL_PLAN_KIND = {"walls": "wall", "floors": "floor",
                    "columns": "column", "openings": "opening"}


def _lp_mm(expr: str) -> str:
    return f"Math.Round(UnitUtils.ConvertFromInternalUnits({expr}, UnitTypeId.Millimeters), 1)"


def _lp_wall(detail: str) -> str:
    """Стена — отрезок с толщиной. Кривая НАЗЫВАЕТСЯ, а не выпрямляется.

    🔴 Врать прямым отрезком нельзя: на листе это другое здание. `LocationCurve`
    бывает `Arc`, поэтому род едет в `curve`, а точки — тесселяцией с НАЗВАННЫМ
    пределом (`geom.MAX_RING_POINTS`). Не поддержанный род приходит с
    `curve: "unsupported"` и габаритом — это ФАКТ строки, а не её отсутствие.
    """
    from kir.geom import MAX_RING_POINTS
    return (
        '            __row["curve"] = "unsupported"; __row["polyline_mm"] = new List<object>();\n'
        '            try { var __w = __e as Wall;\n'
        '                if (__w != null) {\n'
        '                    var __p = __w.get_Parameter(BuiltInParameter.WALL_ATTR_WIDTH_PARAM);\n'
        f'                    if (__p != null) __row["width_mm"] = {_lp_mm("__p.AsDouble()")};\n'
        '                    var __lc = __w.Location as LocationCurve;\n'
        '                    if (__lc != null && __lc.Curve != null) {\n'
        '                        var __c = __lc.Curve;\n'
        '                        __row["curve"] = (__c is Line) ? "line" : ((__c is Arc) ? "arc" : "other");\n'
        f'                        var __pts = (__c is Line) ? __c.Tessellate().ToList()\n'
        f'                            : __c.Tessellate().Take({MAX_RING_POINTS}).ToList();\n'
        '                        var __poly = new List<object>();\n'
        '                        foreach (var __q in __pts) __poly.Add(new double[] {\n'
        f'                            {_lp_mm("__q.X")}, {_lp_mm("__q.Y")} }});\n'
        '                        __row["polyline_mm"] = __poly;\n'
        '                        __row["tessellated"] = !(__c is Line);\n'
        '                    } } } catch { }\n')


def _lp_floor(detail: str) -> str:
    """Перекрытие: габарит или контур — и `detail` едет В СТРОКЕ (условие W 1).

    Без `detail` в строке кадр не отличил бы габарит от контура и залил бы
    прямоугольник там, где у Г-образной плиты крыла нет.
    """
    box = (
        '            __row["detail"] = "box";\n'
        '            try { var __bb = __e.get_BoundingBox(null);\n'
        '                if (__bb != null) { var __d = new Dictionary<string, object>();\n'
        f'                    __d["min"] = new double[] {{ {_lp_mm("__bb.Min.X")}, {_lp_mm("__bb.Min.Y")} }};\n'
        f'                    __d["max"] = new double[] {{ {_lp_mm("__bb.Max.X")}, {_lp_mm("__bb.Max.Y")} }};\n'
        '                    __row["bbox_mm"] = __d; } } catch { }\n')
    if detail == "box":
        return box
    from kir.geom import MAX_RING_POINTS
    return (
        '            __row["detail"] = "sketch";\n'
        '            var __outer = new List<object>(); var __holes = new List<object>();\n'
        '            try {\n'
        '                var __opts = new Options(); __opts.ComputeReferences = false;\n'
        '                var __geo = __e.get_Geometry(__opts);\n'
        '                if (__geo != null) foreach (var __go in __geo) {\n'
        '                    var __solid = __go as Solid; if (__solid == null) continue;\n'
        '                    foreach (Face __f in __solid.Faces) {\n'
        '                        var __pf = __f as PlanarFace; if (__pf == null) continue;\n'
        '                        if (Math.Abs(__pf.FaceNormal.Z) < 0.99) continue;\n'
        '                        int __li = 0;\n'
        '                        foreach (EdgeArray __loop in __pf.EdgeLoops) {\n'
        '                            var __ring = new List<object>(); int __n = 0;\n'
        '                            foreach (Edge __ed in __loop) {\n'
        f'                                if (__n++ >= {MAX_RING_POINTS}) break;\n'
        '                                var __pt = __ed.AsCurve().GetEndPoint(0);\n'
        f'                                __ring.Add(new double[] {{ {_lp_mm("__pt.X")}, {_lp_mm("__pt.Y")} }});\n'
        '                            }\n'
        '                            if (__li++ == 0) __outer = __ring; else __holes.Add(__ring);\n'
        '                        }\n'
        '                        break;\n'
        '                    }\n'
        '                    if (__outer.Count > 0) break;\n'
        '                } } catch { }\n'
        '            __row["outer_mm"] = __outer; __row["holes_mm"] = __holes;\n'
        # Контур мог не сняться — тогда честнее сказать это полем и дать габарит,
        # чем прислать пустое кольцо, которое кадр нарисует как ничто.
        '            if (__outer.Count == 0) { __row["detail"] = "box"; __row["sketch_unavailable"] = true;\n'
        + box.replace('            __row["detail"] = "box";\n', "") +
        '            }\n')


def _lp_column(detail: str) -> str:
    return (
        '            try { var __lp = __e.Location as LocationPoint;\n'
        f'                if (__lp != null) __row["point_mm"] = new double[] {{ '
        f'{_lp_mm("__lp.Point.X")}, {_lp_mm("__lp.Point.Y")} }};\n'
        '                if (__lp != null) __row["rotation_deg"] = Math.Round(__lp.Rotation * 180.0 / Math.PI, 1);\n'
        '            } catch { }\n'
        '            try { var __bb = __e.get_BoundingBox(null);\n'
        '                if (__bb != null) { var __d = new Dictionary<string, object>();\n'
        f'                    __d["min"] = new double[] {{ {_lp_mm("__bb.Min.X")}, {_lp_mm("__bb.Min.Y")} }};\n'
        f'                    __d["max"] = new double[] {{ {_lp_mm("__bb.Max.X")}, {_lp_mm("__bb.Max.Y")} }};\n'
        '                    __row["bbox_mm"] = __d; } } catch { }\n')


def _lp_opening(detail: str) -> str:
    """Проём — точка вставки И ХОЗЯИН ПО ЛИЧНОСТИ, а не по номеру.

    Хозяин назван и `element_id`, и `unique_id`: номер живёт внутри одного
    документа и переиспользуется Ревитом после удаления, поэтому связать фон с
    публикацией по нему одному нельзя.
    """
    return (
        '            try { var __fi = __e as FamilyInstance;\n'
        '                if (__fi != null) {\n'
        '                    var __lp = __fi.Location as LocationPoint;\n'
        f'                    if (__lp != null) __row["point_mm"] = new double[] {{ '
        f'{_lp_mm("__lp.Point.X")}, {_lp_mm("__lp.Point.Y")} }};\n'
        '                    if (__fi.Host != null) {\n'
        '                        __row["host_element_id"] = __fi.Host.Id.ToString();\n'
        '                        __row["host_unique_id"] = __fi.Host.UniqueId ?? "";\n'
        '                    }\n'
        '                    var __cat = __fi.Category;\n'
        '                    if (__cat != null) __row["kind"] =\n'
        '                        (__cat.Id.ToString() == ((int)BuiltInCategory.OST_Doors).ToString())\n'
        '                            ? "door" : "window";\n'
        '                    var __wp = __fi.Symbol == null ? null :\n'
        '                        __fi.Symbol.get_Parameter(BuiltInParameter.DOOR_WIDTH);\n'
        f'                    if (__wp != null) __row["width_mm"] = {_lp_mm("__wp.AsDouble()")};\n'
        '                } } catch { }\n')


_LEVEL_PLAN_BODY = {"walls": _lp_wall, "floors": _lp_floor,
                    "columns": _lp_column, "openings": _lp_opening}


def _emit_row(fields: list[str], src: str) -> list[str]:
    out = [f'var __row = new Dictionary<string, object>();']
    emitters = {
        "id": f'__row["id"] = {src}.Id.ToString();',   # .ToString(): the only 2021-2026-safe id form
        "name": f'__row["name"] = __NameOf({src});',
        "category": f'try {{ __row["category"] = ({src}.Category != null) ? {src}.Category.Name : ""; }} catch {{ __row["category"] = ""; }}',
        "type_name": f'__row["type_name"] = __TypeNameOf({src});',
        "level_name": f'__row["level_name"] = __LevelNameOf({src});',
    }
    out += [emitters[f] for f in fields]
    return out


# fix/g102-disambiguate (2026-07-17): query_types' collector idiom per pool.
# Deliberately 1:1 with serving.py's _SNAPSHOT_CS (same C# idiom, same class/
# category per pool name) — NOT re-derived from it programmatically, because
# _SNAPSHOT_CS builds ALL pools in one round-trip inside a single emitted
# program (the ground-stage snapshot contract, one bridge hop for every
# authoring op), while query_types is its own standalone query-family
# program emitted through the ordinary _emit_op path (no snapshot, no write
# family) that fetches exactly ONE pool on demand. Two call sites, same
# closed set of Revit collector idioms — the KINDS table accepts the same
# duplication for read collectors elsewhere in this module, so this mirrors
# an already-accepted pattern rather than inventing a new one. If a pool's
# collector idiom ever changes, update BOTH tables (gate_runner.py's 6/6
# check compiles this table's emitted C# independently of _SNAPSHOT_CS, so a
# drift is gate-visible, not silent).
_TYPE_POOL_COLLECTOR_CS: dict[str, str] = {
    "levels": ".OfClass(typeof(Level))",
    "wall_types": ".OfClass(typeof(WallType))",
    "floor_types": ".OfClass(typeof(FloorType))",
    "roof_types": ".OfClass(typeof(RoofType))",
    "pipe_types": ".OfClass(typeof(Autodesk.Revit.DB.Plumbing.PipeType))",
    "piping_system_types": ".OfClass(typeof(Autodesk.Revit.DB.Plumbing.PipingSystemType))",
    "duct_types": ".OfClass(typeof(Autodesk.Revit.DB.Mechanical.DuctType))",
    "duct_system_types": ".OfClass(typeof(Autodesk.Revit.DB.Mechanical.MechanicalSystemType))",
    "cable_tray_types": ".OfClass(typeof(Autodesk.Revit.DB.Electrical.CableTrayType))",
    # wave/mep-electrical (2026-08-09) — a mirror of three new __AddPool
    # calls in open_model.GROUND_SNAPSHOT_CS (two places, one law; the
    # gate compiles both tables independently, so a divergence is
    # visible, not silent).
    "conduit_types": ".OfClass(typeof(Autodesk.Revit.DB.Electrical.ConduitType))",
    "flex_duct_types": ".OfClass(typeof(Autodesk.Revit.DB.Mechanical.FlexDuctType))",
    "flex_pipe_types": ".OfClass(typeof(Autodesk.Revit.DB.Plumbing.FlexPipeType))",
    # wave/analysis (2026-08-09) — a mirror of four new __AddPool calls in
    # open_model.GROUND_SNAPSHOT_CS (two places, one law; the gate
    # compiles both tables independently, so a divergence is visible, not
    # silent). Asking the catalog BEFORE attempting here matters more than
    # usual: a real analysis project has dozens of load cases, and
    # `by=name` without first listing them is KIR-G101/G102 one turn
    # later.
    "load_cases": ".OfClass(typeof(Autodesk.Revit.DB.Structure.LoadCase))",
    "point_load_types": ".OfClass(typeof(Autodesk.Revit.DB.Structure.PointLoadType))",
    "line_load_types": ".OfClass(typeof(Autodesk.Revit.DB.Structure.LineLoadType))",
    "area_load_types": ".OfClass(typeof(Autodesk.Revit.DB.Structure.AreaLoadType))",
    "column_symbols_structural": (".OfClass(typeof(FamilySymbol))"
                                  ".OfCategory(BuiltInCategory.OST_StructuralColumns)"),
    "column_symbols_architectural": (".OfClass(typeof(FamilySymbol))"
                                     ".OfCategory(BuiltInCategory.OST_Columns)"),
    "window_symbols": ".OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Windows)",
    "door_symbols": ".OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Doors)",
    "family_symbols": ".OfClass(typeof(FamilySymbol))",
    # The only pool filtered by PLACEMENT TYPE — a mirror of the same
    # filter in open_model.GROUND_SNAPSHOT_CS (two places, one law; the
    # gate compiles both tables independently, so a divergence is
    # visible). create_beam emits NewFamilyInstance(Line, …), which
    # returns null on a point-based family: let the catalog simply not
    # show something the op cannot use.
    "beam_types": (".OfClass(typeof(FamilySymbol))"
                   ".OfCategory(BuiltInCategory.OST_StructuralFraming)"
                   ".Cast<FamilySymbol>()"
                   ".Where(__bfs => { try { var __pt = __bfs.Family.FamilyPlacementType;"
                   " return __pt == FamilyPlacementType.CurveDrivenStructural"
                   " || __pt == FamilyPlacementType.CurveBased; } catch { return false; } })"),
    "foundation_symbols": (".OfClass(typeof(FamilySymbol))"
                            ".OfCategory(BuiltInCategory.OST_StructuralFoundation)"),
    # wave/framing (2026-08-09) — a mirror of a new __AddPool call in
    # open_model.GROUND_SNAPSHOT_CS (two places, one law; the gate
    # compiles both tables independently, so a divergence is visible, not
    # silent). LIVE MEASUREMENT 10.08.2026: `TrussType` compiles 6/6 and
    # IS in the API, but Revit 2023 throws on it at runtime ("exists in
    # the API, but not in Revit's native object model — try
    # FamilySymbol"). The snapshot is assembled as ONE body, so the
    # entire snapshot failed, and with it ANY live write.
    "truss_types": (".OfClass(typeof(FamilySymbol))"
                    ".OfCategory(BuiltInCategory.OST_Truss)"),
    # wave/sweep (2026-08-09). `slab_edge_types` is an ordinary collection
    # by class. `wall_sweep_types` is the ONE row of this table collected
    # by category, and that is not a matter of taste: there is NO
    # `WallSweepType`-as-ElementType class in the API AT ALL
    # (`WallSweepType` is an enum {Sweep, Reveal}, verified by compiling
    # against six versions), and the profile type itself lives as an
    # ordinary ElementType under OST_Cornices or OST_Reveals.
    # `WhereElementIsElementType` is mandatory: without it, the pool would
    # also catch the built profiles themselves.
    "slab_edge_types": ".OfClass(typeof(SlabEdgeType))",
    "wall_sweep_types": (".WherePasses(new ElementMulticategoryFilter("
                         "new List<BuiltInCategory> { "
                         "BuiltInCategory.OST_Cornices, "
                         "BuiltInCategory.OST_Reveals }))"
                         ".WhereElementIsElementType()"),
    # wave/detail (2026-08-09) — a mirror of a new __AddPool call in
    # open_model.GROUND_SNAPSHOT_CS (two places, one law; the gate
    # compiles both tables independently, so a divergence is visible, not
    # silent). BY CLASS, not by category: OST_FilledRegion holds both the
    # filled regions themselves and their types, meaning a category-based
    # catalog would show the model rows that `FilledRegion.Create` would
    # reject.
    "filled_region_types": ".OfClass(typeof(FilledRegionType))",
    # ═══ 12.08.2026. Eight pools the compiler KNEW HOW TO WRITE TO
    # without being able to READ. Each one's idiom was not invented here
    # but taken VERBATIM from the second carrier of the same law —
    # `open_model.GROUND_SNAPSHOT_CS`, where these pools are ALREADY
    # collected by the snapshot (`__AddPool(...)`). The two tables are
    # deliberately kept separate and the gate compiles both, so a
    # divergence is visible, not silent — that is this file's recorded
    # decision, and it is honored here, not worked around.
    "ceiling_types": ".OfClass(typeof(CeilingType))",
    "railing_types": (".OfClass(typeof("
                      "Autodesk.Revit.DB.Architecture.RailingType))"),
    # Topography slab thickness: it has no type of its own in the API
    # across all six versions, so selection goes by the type's NAME among
    # HostObjAttributes — using exactly the same expression the snapshot
    # collects it with.
    "toposolid_types": (".OfClass(typeof(HostObjAttributes)).Cast<Element>()"
                        ".Where(__tse => { try { return __tse.GetType().Name"
                        " == \"ToposolidType\"; } catch { return false; } })"),
    "building_pad_types": ".OfClass(typeof(BuildingPadType))",
    "wall_foundation_types": ".OfClass(typeof(WallFoundationType))",
    "area_reinforcement_types": (".OfClass(typeof("
                                 "Autodesk.Revit.DB.Structure."
                                 "AreaReinforcementType))"),
    "rebar_bar_types": (".OfClass(typeof("
                        "Autodesk.Revit.DB.Structure.RebarBarType))"),
    "rebar_hook_types": (".OfClass(typeof("
                         "Autodesk.Revit.DB.Structure.RebarHookType))"),
}


def _emit_op(op: dict, revit_version: str) -> str:
    name, oid = op["op"], op["id"]
    var = "__c_" + cs_identifier_fragment(oid)
    if name == "query_count":
        group_by = op.get("group_by")
        if group_by:
            row = "\n        ".join(_emit_row([group_by], "__e"))
            return (f"// {name} {cs_line_comment_fragment(oid)}\n"
                    + _emit_collector(op["kind"], op["where"], var) + "\n"
                    + f"{{\n"
                      f"    var __groups = new Dictionary<string, int>();\n"
                      f"    foreach (var __e in {var})\n"
                      f"    {{\n"
                      f"        {row}\n"
                      f'        var __gk = Convert.ToString(__row["{group_by}"]) ?? "";\n'
                      f"        if (!__groups.ContainsKey(__gk)) __groups[__gk] = 0;\n"
                      f"        __groups[__gk]++;\n"
                      f"    }}\n"
                      f'    var __r = new Dictionary<string, object>(); __r["kind"] = {_cs_str(op["kind"])}; '
                      f'__r["group_by"] = {_cs_str(group_by)}; __r["count"] = {var}.Count;\n'
                      f'    __r["groups"] = __groups.OrderByDescending(kv => kv.Value)'
                      f".ThenBy(kv => kv.Key, StringComparer.Ordinal)\n"
                      f'        .Select(kv => {{ var __gd = new Dictionary<string, object>(); '
                      f'__gd["key"] = kv.Key; __gd["count"] = kv.Value; return (object)__gd; }}).ToList();\n'
                      f"    __results[{_cs_str(oid)}] = __r;\n}}")
        return (f"// {name} {cs_line_comment_fragment(oid)}\n"
                + _emit_collector(op["kind"], op["where"], var) + "\n"
                + f'{{ var __r = new Dictionary<string, object>(); __r["kind"] = {_cs_str(op["kind"])}; '
                  f'__r["count"] = {var}.Count; __results[{_cs_str(oid)}] = __r; }}')
    if name == "query_level_plan":
        return _emit_level_plan(op, oid, revit_version)
    if name == "query_list":
        rows = "\n        ".join(_emit_row(op["fields"], "__e"))
        return (f"// {name} {cs_line_comment_fragment(oid)}\n"
                + _emit_collector(op["kind"], op["where"], var) + "\n"
                + f"{{\n"
                  f"    var __rows = new List<object>();\n"
                  f"    foreach (var __e in {var}.Take({op['limit']}))\n"
                  f"    {{\n        {rows}\n        __rows.Add(__row);\n    }}\n"
                  f'    var __r = new Dictionary<string, object>(); __r["kind"] = {_cs_str(op["kind"])}; '
                  f'__r["total"] = {var}.Count; __r["returned"] = __rows.Count; __r["rows"] = __rows;\n'
                  f"    __results[{_cs_str(oid)}] = __r;\n}}")
    if name == "query_element_state":
        from kir.element_query import emit_element_state
        return emit_element_state(op, revit_version)
    if name == "query_inspect":
        tgt = op["target"]
        tv = "__t_" + cs_identifier_fragment(oid)
        rows = "\n        ".join(_emit_row(list(spec.LIST_FIELDS), tv))
        bbox = (
            f'try {{ var __bb = {tv}.get_BoundingBox(null); if (__bb != null) {{\n'
            '        var __bbd = new Dictionary<string, object>();\n'
            '        __bbd["min"] = new double[] { Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Min.X, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Min.Y, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Min.Z, UnitTypeId.Millimeters), 1) };\n'
            '        __bbd["max"] = new double[] { Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Max.X, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Max.Y, UnitTypeId.Millimeters), 1), Math.Round(UnitUtils.ConvertFromInternalUnits(__bb.Max.Z, UnitTypeId.Millimeters), 1) };\n'
            '        __row["bbox_mm"] = __bbd; } } catch { }')
        if tgt["by"] == "element_id":
            val = tgt["value"]
            if val <= 0x7FFFFFFF:
                # int32 id: ElementId(int) exists on all six versions.
                find = (f"Element {tv} = null;\n"
                        f"try {{ {tv} = doc.GetElement(new ElementId({val})); }} catch {{ }}")
            elif revit_version >= "2024":
                # 64-bit ids exist only since 2024 (ElementId(Int64)).
                find = (f"Element {tv} = null;\n"
                        f"try {{ {tv} = doc.GetElement(new ElementId({val}L)); }} catch {{ }}")
            else:
                # Pre-2024 id space is 32-bit: such an element cannot exist —
                # typed not_found by construction, no unrepresentable literal.
                find = f"Element {tv} = null; // id exceeds 32-bit ElementId space on Revit {revit_version}"
        else:
            ks = spec.KINDS[tgt["kind"]]
            base = f"new FilteredElementCollector(doc){ks.collector_cs}.Cast<Element>()"
            if ks.where_cs:
                base += f".Where(e => {ks.where_cs})"
            find = (f"var __m_{tv} = {base}\n"
                    f"    .Where(e => __NameOf(e).Trim().Equals({_cs_str(tgt['value'])}, StringComparison.OrdinalIgnoreCase))\n"
                    f"    .OrderBy(e => __IdOf(e))\n"
                    f"    .ToList();\n"
                    f"Element {tv} = (__m_{tv}.Count == 1) ? __m_{tv}[0] : null;")
        not_found = (
            f'var __r = new Dictionary<string, object>();\n'
            + (f'    if (__m_{tv}.Count > 1) {{ __r["error"] = "ambiguous"; '
               f'__r["candidates"] = __m_{tv}.Take(5).Select(e => __NameOf(e)).ToList(); }}\n'
               f'    else {{ __r["error"] = "not_found"; }}\n'
               if tgt["by"] == "name" else '    __r["error"] = "not_found";\n')
            + f'    __results[{_cs_str(oid)}] = __r;')
        # NOTE: `rows` (from _emit_row) already declares __row — do not re-declare.
        return (f"// {name} {cs_line_comment_fragment(oid)}\n{find}\n"
                f"if ({tv} == null)\n{{\n    {not_found}\n}}\nelse\n{{\n"
                f"    {rows}\n    {bbox}\n"
                f"    __results[{_cs_str(oid)}] = __row;\n}}")
    if name == "query_surface":
        from kir import surface_query
        return surface_query.emit_query_surface(op, revit_version)

    if name == "query_types":
        # fix/g102-disambiguate (2026-07-17): G102-enumeration companion —
        # returns {id, name} for every element in the requested closed pool
        # (the same identity space Sel<K> by=name/by=element_id resolve
        # against in ground.py). No `where`/`limit`/`fields` params by design
        # (v1 scope: the caller wants the FULL disambiguation set — these
        # pools are small, hundreds not thousands, unlike query_list's
        # doc-wide element scans that need paging).
        collector_cs = _TYPE_POOL_COLLECTOR_CS[op["pool"]]
        family_fields = ""
        if op["pool"] == "family_symbols":
            family_fields = (
                f"        var __fs = __e as FamilySymbol;\n"
                f"        if (__fs != null)\n        {{\n"
                f"            try {{ var __cat = __fs.Category; int __catId; if (__cat != null && Int32.TryParse(__cat.Id.ToString(), out __catId)) __row[\"category\"] = Enum.GetName(typeof(BuiltInCategory), __catId) ?? __catId.ToString(); }} catch {{ }}\n"
                f"            try {{ __row[\"family_name\"] = __fs.FamilyName ?? \"\"; }} catch {{ }}\n"
                f"            try {{ __row[\"type_name\"] = __fs.Name ?? \"\"; }} catch {{ }}\n"
                # WHAT THIS TYPE IS EVEN PLACED WITH. Without this field
                # the `family_symbols` pool cannot answer the one question
                # that comes to it from `place_family`: does the symbol
                # hold a point. Measured live 04.08 («Проект1», 320
                # units): 279 ViewBased, 20 OneLevelBased, 16
                # OneLevelBasedHosted, 4 TwoLevelsBased. Neither the name
                # nor the category tells you this — `MullionType` id 407
                # was named «50 x 150 мм» and, when placed by point, ended
                # up at (0,0,0), while the system panel returned
                # LocationPoint == null.
                f"            try {{ __row[\"placement\"] = __fs.Family != null ? __fs.Family.FamilyPlacementType.ToString() : \"\"; }} catch {{ }}\n"
                f"        }}\n")
        return (f"// {name} {cs_line_comment_fragment(oid)}\n"
                f"var {var} = new FilteredElementCollector(doc){collector_cs}"
                f".Cast<Element>().OrderBy(e => __IdOf(e)).ToList();\n"
                f"{{\n"
                f"    var __rows = new List<object>();\n"
                f"    foreach (var __e in {var})\n"
                f"    {{\n"
                f'        var __row = new Dictionary<string, object>();\n'
                f'        __row["id"] = __e.Id.ToString();\n'
                f'        __row["name"] = __NameOf(__e);\n'
                + family_fields +
                f"        __rows.Add(__row);\n"
                f"    }}\n"
                f'    var __r = new Dictionary<string, object>(); __r["pool"] = {_cs_str(op["pool"])}; '
                f'__r["total"] = __rows.Count; __r["rows"] = __rows;\n'
                f"    __results[{_cs_str(oid)}] = __r;\n}}")
    raise AssertionError(f"unreachable: {name}")


def emit(normed_ops: list[dict], revit_version: str = "2026") -> str:
    body = "\n\n".join(_emit_op(op, revit_version) for op in normed_ops)
    return (f"{_PREAMBLE}\n"
            f"var __results = new Dictionary<string, object>();\n\n"
            f"{body}\n\n"
            f"return __results;")


def emit_for_version(normed_ops: list[dict], revit_version: str) -> str:
    """Per-version emit axis (SPEC 11.2). First real divergence: 64-bit
    element ids exist only since 2024 (ElementId(Int64)); pre-2024 an over-int32
    id is emitted as typed not_found — the unrepresentable literal never
    reaches Roslyn (gate-caught bug, 2026-07-16)."""
    if revit_version not in spec.REVIT_VERSIONS:
        raise KirRefusal([Diagnostic(code="KIR-E001", field_name="revit_version",
                                     expected=list(spec.REVIT_VERSIONS), got=revit_version,
                                     message_ru="неизвестная версия Revit")])
    return emit(normed_ops, revit_version)


def _units_of(program: Any) -> list:
    """The table of intent units from the envelope — WITHOUT
    interpretation.

    As a separate function, not an expression duplicated in two places:
    two copies of the same read are a named defect of this tree, and it
    would cost exactly what is being fixed here (one door carries the
    intent, the other loses it).
    """
    if isinstance(program, Mapping):
        rows = program.get("units")
        return list(rows) if isinstance(rows, (list, tuple)) else []
    # 🔴 THE SECOND INPUT IS THE PLAN, AND THAT IS EXACTLY WHAT ARRIVES
    # FROM THE LIVE DOOR (25.08.2026). The docstring above promised "one
    # door carries the intent, the other loses it" as FIXED; in reality
    # the function only knew about a dict, while prod passes
    # `PlannedProgram`. The promise stood, the reading did not.
    rows = getattr(program, "units", None)
    return list(rows) if isinstance(rows, (list, tuple)) else []


def _name_the_next_move_at_the_seam(diags: Sequence[Any],
                                    raw_ops: Sequence[Any]) -> None:
    """Append the slot tail to EVERY refusal that pointed at a slot.

    The argument and the measurement belong at the call site. Only three
    rules here:

    * **idempotence**: text that already carries a "NEXT TURN" is left
      untouched, so refusals already enriched (`KIR-P003`, `KIR-P005`)
      remain verbatim as before and their controls don't budge;
    * **don't invent**: the op's name is taken from `raw_ops` by
      `op_index`, and the tail is built by `_slot_tail`, which itself
      returns empty for a field not in the registry (`where.*`,
      `target.value`). Advice given at random is worse than silence;
    * **the list of required fields — once per op**: on a program with
      three defects in one op, it would otherwise repeat verbatim three
      times.

    Never raises: this is the refusal branch, and letting it crash would
    mean replacing a typed refusal with an incident.
    """
    try:
        from kir.authoring_validation import _slot_tail
        # The code is taken from the refusal's OWNER (`ground.py`), not
        # written as a literal: two strings that must match are a named
        # defect of this tree.
        from kir.ground import GROUND_NOT_FOUND as _НЕ_НАЙДЕН
    except Exception:      # noqa: BLE001
        return

    # 🔴 A NAME THAT THIS SAME PROGRAM CREATES IS NAMED BY NAME
    # (26.08.2026, found in the REASONING TRACE of a real model).
    #
    # The model wanted to create its own wall type and immediately build
    # with it. It wrote `create_wall_type(new_name="МОЙ-ТИП-200")`,
    # followed by `create_wall(type={"by":"name","value":"МОЙ-ТИП-200"})`
    # — and got «wall_types: "МОЙ-ТИП-200" не найден». The refusal is
    # CORRECT: grounding runs against a snapshot taken BEFORE the
    # transaction, and the type is not there and cannot be.
    #
    # But the language CAN do this: the `type` slot's list of forms
    # includes `ref(wall_type)`, i.e. a reference to an operation of this
    # same program. The capability exists, the hint didn't — and the
    # model, not knowing the answer, spent part of the turn working
    # around the unknown. Its trace records this verbatim: «grounding
    # happens on snapshot before transaction, so newly created type
    # wouldn't resolve… Hmm, actually maybe compiler handles
    # intra-program creation. Not guaranteed.»
    #
    # A mirror of the same class as the `element_id`-for-`ref` hint
    # below: there the author wrote `ref` when `element_id` was needed;
    # here they write `name` when `ref` is needed. Both times the refusal
    # KNEW the answer and stayed silent.
    #
    # The match is searched for by EXACT name and only among operations
    # standing ABOVE the one that refused: `ref` requires the same
    # ordering, and hinting at an operation below would mean sending the
    # author into the next refusal.
    #
    # 🔴 AND THE RESULT KIND IS CHECKED AGAINST THE SLOT (26.08.2026). The
    # first revision searched for a producer BY NAME and nothing else —
    # and would send the author to reference anyone at all, so long as
    # the name matched. Reproduced live: `create_level(name="МОЙ-ТИП-200")`
    # + `create_wall(type=by name "МОЙ-ТИП-200")` gave «сошлись на него:
    # {"by":"ref","value":"lvl"}» — and TWO LINES BELOW the very same
    # refusal printed `type sel: …|ref(wall_type)`. One refusal named TWO
    # next turns that contradicted each other, and a model that followed
    # the first got `KIR-L004` on the next turn.
    #
    # This violated a law recorded in `ground.py` verbatim: "a refusal
    # that names an unworkable turn costs more than a refusal that names
    # none." So the fix is not "offer something else" but DO NOT OFFER
    # SOMETHING UNFIT: silence here is cheaper than advice.
    #
    # The kind is taken from the CALL (`result_for`), not from the op in
    # general: `create_wall_type` produces four different kinds by
    # `host_kind`, and a static `result` would have called a roof type a
    # wall. The same authority as in the reference check below.
    #
    # IDENTICAL NAMES: previously `setdefault` kept the FIRST one and
    # that was that. Now a LIST is stored in program order, and the first
    # one whose kind is FIT is chosen — meaning the old "first match"
    # became "first fit." Strictly better and never worse: an unfit
    # first one no longer shadows a fit second one.
    производители: dict[str, list[tuple[str, int, Any]]] = {}
    for _i, _op in enumerate(raw_ops or ()):
        if not isinstance(_op, Mapping):
            continue
        _oid = _op.get("id")
        if not isinstance(_oid, str) or not _oid:
            continue
        # 🔴 THE OP'S NAME IS USED AS A KEY ONLY AFTER THE KIND CHECK, and
        # this is not pedantry. The seam works on the REFUSAL path, where
        # the program can be arbitrary garbage: `{"op": ["create_wall"]}`
        # is a legitimate input for `KIR-P002`. The first draft of this
        # fix wrote `spec.OPS.get(_op.get("op"))` without checking, and
        # dropped a `TypeError: unhashable type` ON TOP OF an
        # already-ready typed refusal — replacing the refusal with an
        # incident, exactly against the docstring's promise of "never
        # raises." Caught by my own probe before the report.
        _имя_опа = _op.get("op")
        _ospec = spec.OPS.get(_имя_опа) if isinstance(_имя_опа, str) else None
        _род = None
        if _ospec is not None:
            try:
                _род = _ospec.result_for(_op).reference_kind
            except Exception:      # noqa: BLE001 — a refusal must get through, no matter what
                _род = None
        # An op whose `new_name` matches its `name` is registered ONCE:
        # two identical candidates add no choice, only noise.
        for _имя in {_op.get(_поле) for _поле in ("new_name", "name")}:
            if isinstance(_имя, str) and _имя.strip():
                производители.setdefault(_имя.strip(), []).append(
                    (_oid, _i, _род))

    roster_spent: set[str] = set()
    for d in diags or ():
        try:
            if not (getattr(d, "field_name", "") or "").strip():
                continue
            if "СЛЕДУЮЩИЙ ХОД" in (getattr(d, "message_ru", "") or ""):
                continue
            # 🔴 TWO ADDRESSES FOR AN OP, AND THE SECOND IS NOT A
            # FALLBACK BUT THE PRIMARY ONE FOR HALF THE REFUSALS. The
            # first draft only took `op_index` — and checking showed that
            # refusals born from CONTOUR checks have none at all: they
            # carry `op_id` instead. Meaning the "through the seam" fix
            # would have reached exactly the same refusals as the
            # previous one, and the measurement would not have noticed,
            # because it would have measured the same thing.
            op = None
            idx = getattr(d, "op_index", None)
            if isinstance(idx, int) and 0 <= idx < len(raw_ops):
                op = raw_ops[idx]
            else:
                oid = getattr(d, "op_id", None)
                if isinstance(oid, str) and oid:
                    for cand in raw_ops:
                        cid = (cand.get("id") if isinstance(cand, Mapping)
                               else getattr(cand, "id", None))
                        if cid == oid:
                            op = cand
                            break
            if op is None:
                continue
            name = (op.get("op") if isinstance(op, Mapping)
                    else getattr(op, "op", None))
            if not isinstance(name, str) or not name:
                continue
            # The reference hint comes BEFORE the generic slot tail: it
            # is about the SPECIFIC value, while the tail is about the
            # field's form in general.
            искомое = getattr(d, "got", None)
            if (getattr(d, "code", "") == _НЕ_НАЙДЕН
                    and isinstance(искомое, str)
                    and искомое.strip() in производители):
                # THE SLOT THE REFUSAL IS ABOUT. Fitness is asked of the
                # slot itself (`ParamSpec.accepts_reference`), not of a
                # table of kinds: a homegrown table would have drifted
                # from the registry, the way every handwritten one has
                # drifted here, and not one generated one has.
                _слот = None
                _поле_отказа = (getattr(d, "field_name", "") or "").split(".")[0]
                _cspec = spec.OPS.get(name)
                if _cspec is not None and _поле_отказа:
                    _слот = next((p for p in _cspec.params
                                  if p.name == _поле_отказа), None)
                _idx = getattr(d, "op_index", None)
                _годный = None
                # FAIL-CLOSED: fitness not proven — no advice given. A
                # field not in the registry (`where.*`), an unknown op, a
                # kind that could not be derived — all three cases are
                # the same: there is nothing to advise.
                if _слот is not None:
                    for _oid, _i, _род in производители[искомое.strip()]:
                        # Order must be PROVABLE, not assumed. The
                        # previous revision SKIPPED the check when
                        # `op_index is None`. Measured 26.08: all five
                        # places that raise `KIR-G101` in `ground.py` do
                        # set `op_index`, so there is no live path to
                        # that hole — but demanding proof is cheaper than
                        # remembering that the hole doesn't exist.
                        if not isinstance(_idx, int) or _i >= _idx:
                            continue
                        if _род is not None and _слот.accepts_reference(_род):
                            _годный = _oid
                            break
                if _годный is not None:
                    d.message_ru = (
                        (getattr(d, "message_ru", "") or "")
                        + f". СЛЕДУЮЩИЙ ХОД: «{искомое}» создаёт оп «{_годный}» "
                          f"ЭТОЙ ЖЕ программы, а по имени ищется снимок, снятый "
                          f"ДО неё — сошлись на него: "
                          f"{{\"by\": \"ref\", \"value\": \"{_годный}\"}}")
            tail = _slot_tail(name, d, with_roster=name not in roster_spent)
            if tail:
                d.message_ru = (getattr(d, "message_ru", "") or "") + tail
                roster_spent.add(name)
        except Exception:      # noqa: BLE001 — a refusal must get through, no matter what
            continue


def compile_program(program: Any, revit_version: str = "2026",
                    query_id: str = "", snapshot: Any = None,
                    *, bulk: bool = False,
                    isolation: str = "atomic",
                    disallow_wall_joins: bool = False,
                    stamp_scope: str = "",
                    expected_document: Any = None,
                    expected_identities: Sequence[
                        ElementIdentityProof] | None = None,
                    open_model_profile: Any = None,
                    ground_context: GroundingContext | None = None,
                    turn_id: str = "",
                    action_id: str = "",
                    query_fingerprint: str = "",
                    source_kind: str = "unknown") -> CompileOutput:
    """The public entry: any input -> ok+C# or refused+diagnostics(+handoff).
    Never raises (Any-Query invariant §14: the only forbidden outcome is a
    silently-wrong answer). EVERY refusal is reported to the rejection
    telemetry (contract /root/kukai-cube/KIR_QUEUE_CONTRACT.md, fail-open);
    out-of-coverage refusals additionally carry the tail route so the caller
    falls through to the recipe path.

    Authoring programs additionally require `snapshot` (census-style dict) for
    the ground stage — without it they are refused (KIR-G103), never guessed.

    `bulk` is an INTERNAL-only flag (materializer / rebuild): it raises the
    pre-macro op cap to MAX_BULK_OPS. It is deliberately absent from the LLM
    schema and from the CHAT door (`serving.handle_revit_ir` has no parameter
    that can set it) so a user-authored program keeps the tight
    MAX_OPS_PER_PROGRAM budget; the post-expansion ceiling is unchanged.
    Internal callers do not set it by hand either — they go through
    `compile_rebuild_chunk`, the single rebuild policy point below."""
    stage = "plan"
    planned: PlannedProgram | None = None
    try:
        # Accepting PlannedProgram makes the typed boundary composable: serving
        # can classify before the snapshot read, then lower this SAME object
        # after the read instead of silently planning twice.
        planned = plan_program(program, bulk=bulk)
        stage = "target_profile"
        # Grounders/emitters still operate on dicts; this is a detached lowering
        # view, never the plan object whose digest acceptance/evidence records.
        normed = planned.to_ops()
        if revit_version not in spec.REVIT_VERSIONS:
            raise KirRefusal([Diagnostic(code="KIR-E001", field_name="revit_version",
                                         expected=list(spec.REVIT_VERSIONS),
                                         got=revit_version,
                                         message_ru="неизвестная версия Revit")])
        # THE VERSION EXPLAINS AN EMPTY POOL, SO IT ANSWERS FIRST
        # (13.08.2026).
        #
        # It stands EXACTLY HERE — after normalization, before grounding.
        # While the check lived only in emission, an author on Revit 2023
        # got «toposolid_types: пусто в модели» and went off to create a
        # topography-slab type on a version where topography slabs don't
        # exist: grounding runs earlier, and whichever refusal fired
        # first won.
        #
        # The list is an address list, not a mechanism: it is measured
        # that EXACTLY ONE pool out of 36 is version-locked
        # (`ToposolidType` is absent from the reference 2021-2023
        # builds). A "capability -> version" table would become a third
        # copy of knowledge that lives in the emitters, and would drift
        # from them.
        from kir.ops_site import toposolid_version_refusal
        _version_refusals = [
            d for d in (toposolid_version_refusal(op, revit_version)
                        for op in normed) if d is not None]
        if _version_refusals:
            raise KirRefusal(_version_refusals)
        if normed and spec.OPS[normed[0]["op"]].family in spec.WRITE_FAMILIES:
            from kir import authoring, ground as ground_mod
            stage = "ground"
            typed_open_model = None
            if open_model_profile is not None:
                from kir.open_model import (
                    OpenModelProfile,
                    OpenModelProfileError,
                )

                if not isinstance(open_model_profile, OpenModelProfile):
                    raise KirRefusal([Diagnostic(
                        code=GROUND_MODEL_BINDING,
                        message_ru=(
                            "профиль открытой модели имеет неверный тип"),
                    )])
                typed_open_model = open_model_profile
                try:
                    observed_profile = OpenModelProfile.from_ground_snapshot(
                        snapshot,
                        revision_proof=typed_open_model.revision_proof,
                        required_pools=typed_open_model.required_pools,
                    )
                except (OpenModelProfileError, TypeError, ValueError) as exc:
                    raise KirRefusal([Diagnostic(
                        code=GROUND_MODEL_BINDING,
                        message_ru=(
                            "снапшот и профиль открытой модели невозможно "
                            "связать одним контрактом"),
                    )]) from exc
                if observed_profile.digest != typed_open_model.digest:
                    raise KirRefusal([Diagnostic(
                        code=GROUND_MODEL_BINDING,
                        message_ru=(
                            "снапшот принадлежит другому профилю открытой "
                            "модели"),
                    )])
            if ground_context is None:
                ground_context = GroundingContext.from_snapshot(
                    snapshot,
                    source="compiler_argument",
                    trusted_source=False,
                    profile_digest=(
                        typed_open_model.digest
                        if typed_open_model is not None else None),
                    profile_authoritative=(
                        typed_open_model.authoritative
                        if typed_open_model is not None else False),
                    revision_proof=(
                        typed_open_model.revision_proof
                        if typed_open_model is not None else None),
                )
            else:
                if not isinstance(ground_context, GroundingContext):
                    raise KirRefusal([Diagnostic(
                        code=GROUND_MODEL_BINDING,
                        message_ru=(
                            "контекст заземления имеет неверный тип"),
                    )])
                # A caller-supplied context is evidence, not authority to
                # rewrite what snapshot/profile it belongs to.  Reconstruct
                # every content-derived axis here and compare it before the
                # grounder can resolve even one selector.  In particular, a
                # valid snapshot digest must not be allowed to travel with a
                # profile/revision digest copied from another live read.
                expected_context = GroundingContext.from_snapshot(
                    snapshot,
                    source="compiler_context_recheck",
                    trusted_source=False,
                    profile_digest=(
                        typed_open_model.digest
                        if typed_open_model is not None else None),
                    profile_authoritative=(
                        typed_open_model.authoritative
                        if typed_open_model is not None else False),
                    revision_proof=(
                        typed_open_model.revision_proof
                        if typed_open_model is not None else None),
                )
                supplied_binding = (
                    ground_context.snapshot_digest,
                    ground_context.document_digest,
                    ground_context.profile_digest,
                    ground_context.profile_authoritative,
                    ground_context.revision_digest,
                )
                expected_binding = (
                    expected_context.snapshot_digest,
                    expected_context.document_digest,
                    expected_context.profile_digest,
                    expected_context.profile_authoritative,
                    expected_context.revision_digest,
                )
                if supplied_binding != expected_binding:
                    raise KirRefusal([Diagnostic(
                        code=GROUND_MODEL_BINDING,
                        message_ru=(
                            "контекст заземления не принадлежит точному "
                            "снимку и профилю открытой модели"),
                    )])
            try:
                grounded_program = ground_mod.ground_program(
                    planned, snapshot, context=ground_context)
            except ValueError as exc:
                # Do not relabel unrelated canonicalisation/grounding defects
                # as a model-binding refusal.  Only the two explicit context
                # recheck failures owned by ``ground_program`` belong here.
                if not str(exc).startswith(
                        "grounding context is bound to another "):
                    raise
                raise KirRefusal([Diagnostic(
                    code=GROUND_MODEL_BINDING,
                    message_ru=(
                        "контекст заземления не прошёл повторную привязку "
                        "к снимку открытой модели"),
                )]) from exc
            grounded = grounded_program.to_ops()
            guarded_identities = expected_identities
            if typed_open_model is not None:
                from kir.open_model import (
                    preflight_programs,
                )
                stage = "open_model_preflight"
                binding_report = preflight_programs(
                    {"ops": grounded},
                    typed_open_model,
                    require_exact_identity=True,
                )
                if not binding_report.ready:
                    raise KirRefusal([
                        Diagnostic(
                            code=GROUND_MODEL_BINDING,
                            op_index=issue.op_index,
                            op_id=issue.op_id,
                            field_name=issue.parameter,
                            got=issue.code.value,
                            message_ru=(
                                "точная привязка к открытой модели не "
                                f"подтверждена: {issue.detail}"),
                        )
                        for issue in binding_report.issues
                    ])
                derived = binding_report.exact_identity_proofs()
                guarded_identities = (
                    derived
                    if expected_identities is None
                    else tuple(expected_identities) + derived
                )
            stage = "emit_authoring"
            cs = authoring.emit_program(
                grounded, revit_version,
                planned.intent,
                isolation=isolation,
                disallow_wall_joins=disallow_wall_joins,
                stamp_scope=stamp_scope,
                # D-1: a stable address of the author's thing, if the
                # envelope carries it.
                lineage=planned.lineage or "",
                expected_document=expected_document,
                expected_identities=guarded_identities)
            return CompileOutput(
                ok=True, csharp=cs, planned=planned,
                grounded=grounded_program,
                grounding_report=ground_mod.compiler_choices(grounded),
                grounded_ops=grounded,
                units=_units_of(program),
                txn_isolation=isolation)
        stage = "emit_query"
        cs = emit_for_version(normed, revit_version)
        return CompileOutput(ok=True, csharp=cs, planned=planned,
                             units=_units_of(program),
                             txn_isolation=isolation)
    except KirRefusal as r:
        out = CompileOutput(ok=False, diagnostics=r.diagnostics)
        # 🔴 THE SEAM READS THE SAME LIST AGAINST WHICH INDICES WERE
        # ASSIGNED (25.08.2026, an audit finding). This used to hold the
        # author's own `program["ops"]` field, while `op_index` is
        # assigned AFTER normalization and macro expansion. Measurements:
        #   · `ops` AS A DICT (a form legitimized on 17.08): `len()` gave
        #     the number of KEYS, the traversal went over the key
        #     strings, and enrichment fired for NOT ONE refusal of such a
        #     program;
        #   · a program with a macro: 4 ops from 1 authored one,
        #     diagnostics carrying `op_index=2,3` — outside the bounds of
        #     the author's list.
        # Telemetry went mute along with it: `coverage_feed.record_rejections`
        # gets the same argument and was writing `op_requested=None`.
        raw_ops = getattr(r, "expanded_ops", None)
        # A refusal AFTER parsing (ground, emission) does not carry a
        # list with it — parsing has, after all, already passed. But the
        # plan is ALREADY built, and it is exactly the list against which
        # indices were assigned: `plan_program` gives 4 ops from one
        # authored `stack`, and the diagnostics arrive with
        # `op_index=3,4` and `op_id='sec_L1_W'` — a name minted by the
        # expansion.
        if raw_ops is None and planned is not None:
            raw_ops = planned.to_ops()
        if raw_ops is None:
            raw_ops = (program.to_ops() if isinstance(program, PlannedProgram)
                       else program.get("ops") if isinstance(program, dict)
                       else [])
        # A single op has been a legitimate form since 17.08. A dict
        # where a list is expected silently turns the traversal into an
        # iteration over KEYS.
        if isinstance(raw_ops, dict) and raw_ops.get("op"):
            raw_ops = [raw_ops]
        if not isinstance(raw_ops, list):
            raw_ops = []
        # 🔴 THE ONE SEAM THROUGH WHICH ALL COMPILER REFUSALS PASS.
        #
        # MEASURED 21.08.2026 (`tools/refusal_muteness.py`): of 729 live
        # refusals, 435 (59.7 %) ARE MUTE — the text names the reason and
        # leaves the knowledge in the fields. The slot tail used to be
        # appended in exactly one place
        # (`authoring_validation._name_the_next_move`), and only part of
        # the refusals reach it: widening the gate there from two codes
        # to "any with a field_name," I remeasured — and 39 of the 40
        # remaining mute ones STILL named a slot. They are born in
        # `contour`, in op checks, in the DSL — bypassing that place.
        #
        # Here ALL of them pass through, and this is also where
        # `raw_ops` lives, which is what the op's name is taken from via
        # `op_index`. A fix done site by site would have left the next
        # one unwritten silently — exactly as it left these.
        _name_the_next_move_at_the_seam(r.diagnostics, raw_ops)
        from kir import coverage_feed
        coverage_feed.record_rejections(r.diagnostics, raw_ops,
                                        query_id=query_id,
                                        revit_version=revit_version,
                                        turn_id=turn_id,
                                        action_id=action_id,
                                        query_fingerprint=query_fingerprint,
                                        source_kind=source_kind)
        unsupported = [d for d in r.diagnostics if d.code == GROUND_UNSUPPORTED_KIND]
        if unsupported:
            kinds = sorted({str(d.got) for d in unsupported if d.got is not None})
            out.handoff = {"route": "recipe-path", "reason": "unsupported_kind",
                           "kinds": kinds}
        return out
    except Exception:  # noqa: BLE001 — compiler must never panic (RISK R1/R4 discipline)
        incident_id = uuid.uuid4().hex
        query_ref = _incident_log_ref(
            query_id if isinstance(query_id, str) and query_id
            else query_fingerprint
        )
        plan_digest = (
            planned.plan_digest if isinstance(planned, PlannedProgram) else "-"
        )
        # Deliberately attach no exception object or stack information:
        # messages and traceback source lines may contain source IR, model
        # names, paths, or secrets.  incident_id is the correlation key.
        logger.error(
            "KIR compiler panic incident_id=%s stage=%s revit_version=%s "
            "query_id_or_digest=%s plan_digest=%s input_type=%s",
            incident_id,
            stage,
            _incident_revit_version_ref(revit_version),
            query_ref,
            plan_digest,
            _incident_input_type(program),
        )
        паника = Diagnostic(
            code=INTERNAL_PANIC,
            message_ru="внутренняя ошибка компилятора",
            incident_id=incident_id,
        )
        # 🔴 A PANIC IS WRITTEN INTO THE REFUSAL CORPUS, NOT ONLY INTO
        # THE SYSTEM JOURNAL (26.08.2026). The instrument was blind to
        # EXACTLY THE WORST OUTCOME.
        #
        # The measurement that bought this: a real model, over chat, got
        # `KIR-P000` on `create_room` six times in a row — including on
        # a minimal input of ONE operation — and not one of the six
        # landed in EITHER of the two standard corpora. `kir_witness.jsonl`
        # doesn't see them because execution was never reached;
        # `kir_rejections.jsonl` didn't see them because the write sat
        # only on the normal-refusal branch (twenty lines above), while
        # the panic branch returned immediately.
        #
        # The cost of the blindness is given as a number: the question
        # "how often does the compiler crash for the model" had no
        # source at all. Six crashes in one session were visible only to
        # whoever happened to be reading `journalctl` at that minute —
        # that is, to no one. A zero in the corpus read as "panics don't
        # happen."
        #
        # 🔴 ONLY THE CODE AND THE `incident_id` ARE WRITTEN, AND THIS IS
        # NOT AN OVERSIGHT. The paragraph above explains why the
        # exception and stack cannot be put here: the error text and
        # trace lines can carry the source IR, model names, paths, and
        # secrets. `incident_id` is the key for cross-checking against
        # the journal, where the full picture lives under admin
        # privileges. The corpus gets the FACT ("a panic happened, here
        # is its key"), not the contents.
        #
        # The write is wrapped in its own `except`: an instrument that
        # lets the panic handler itself crash would turn a typed refusal
        # into an unhandled exception — that is, make things exactly
        # worse than what it fixes.
        try:
            from kir import coverage_feed as _cf
            _cf.record_rejections(
                [паника], locals().get("raw_ops") or [],
                query_id=query_id, revit_version=revit_version,
                stage=stage, turn_id=turn_id, action_id=action_id,
                query_fingerprint=query_fingerprint, source_kind=source_kind)
        except Exception:  # noqa: BLE001
            logger.warning("KIR panic не записана в корпус отказов "
                           "incident_id=%s", incident_id)
        return CompileOutput(ok=False, diagnostics=[паника])


def compile_rebuild_chunk(program: Any, revit_version: str = "2026",
                          query_id: str = "", *,
                          stamp_scope: str = "",
                          expected_document: Any = None,
                          expected_identities: Sequence[
                              ElementIdentityProof] | None = None,
                          open_model_profile: Any = None,
                          ground_context: GroundingContext | None = None,
                          snapshot: Any = None,
                          turn_id: str = "",
                          action_id: str = "",
                          query_fingerprint: str = "",
                          source_kind: str = "unknown") -> CompileOutput:
    """THE single policy point for INTERNAL rebuild-chunk compilation.

    Every internal rebuild path (handle_revit_rebuild dry-run gate, the A5
    idempotence live/dry runners, and serving's internal door
    `handle_revit_ir_bulk` behind /admin/kir/*) must compile materializer chunks
    through this helper, never by calling :func:`compile_program` with
    hand-picked flags.
    The policy is one fact, stated once:

    * ``bulk=True`` — materializer chunks hold up to MAX_BULK_OPS ops; the
      default 20-op cap is the LLM-authored budget (three separate callers
      independently forgot this flag on 2026-07-21 — per-caller flags drift).
    * ``isolation="per_op"`` — each op commits in its own SubTransaction so a
      single bad op is a recorded refusal/violation, not a whole-chunk
      rollback (partial-progress honesty of the idempotence number).
    * ``disallow_wall_joins=True`` — faithful reproduction.

      🔴🔴 THE JUSTIFICATION BELOW WAS RETRACTED ON 18.08.2026. READ THIS
      NOTE FIRST. It used to say: «auto-join extends re-created walls'
      LOCATION CURVES to joined walls' centerlines by half their
      thickness (live A5 evidence 2026-07-21: ±100/125/150 mm endpoint
      shifts)». A direct measurement of both quantities before and after
      the commit on a live Revit 2023 disproves this: **the location
      curve DOES NOT SHIFT BY A SINGLE MILLIMETER** in any of the four
      states (join allowed/disallowed × before/after commit). What moves
      is the SOLID, and by exactly half the thickness: type 250 → +125,
      type 380 → +190. The earlier ±100/125/150 band is half of
      200/250/300, i.e. a measurement of the FOOTPRINT recorded as a
      measurement of the CURVE.

      WHAT THIS MEANS FOR THE FLAG, AND IT IS NOT "REMOVE IT." The flag
      may still be needed, but NOT FOR THIS REASON: it guards against
      the SOLID expanding, not against the curve's endpoints drifting.
      Someone checking CURVES will not see the discrepancy at all;
      someone checking FOOTPRINTS must know about the half-thickness.
      Until the real case is named by name, the flag remains a guard
      against the UNNAMED — it cannot be removed on this basis, but it
      cannot be proven load-bearing either.

      The lines are not erased on purpose: what is retracted is called
      wrong, not removed, because it carries a pattern of form — "a
      value taken by one instrument was recorded as the reading of
      another." Full breakdown: `kir/CLAUDE.md`, section «Revit API
      facts obtained by measurement».
    """
    return compile_program(program, revit_version, query_id,
                           bulk=True, isolation="per_op",
                           disallow_wall_joins=True,
                           # The snapshot (census) is needed by grounding
                           # for resolving by name and by default. The
                           # live path gets it from the bridge; the DRY
                           # gate has nowhere to get it from — and so it
                           # silently refused whole chunks (KIR-G103) and
                           # printed «1 из 3 чанков ok», even though all
                           # of them compile once the source catalog is
                           # available. Threading it through closes this
                           # lie: we do have the catalog, it's saved
                           # alongside the parse.
                           snapshot=snapshot,
                           stamp_scope=stamp_scope,
                           expected_document=expected_document,
                           expected_identities=expected_identities,
                           open_model_profile=open_model_profile,
                           ground_context=ground_context,
                           turn_id=turn_id,
                           action_id=action_id,
                           query_fingerprint=query_fingerprint,
                           source_kind=source_kind)
