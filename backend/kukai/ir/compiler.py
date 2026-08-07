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

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from kukai.ir import relate, spec
from kukai.ir.compile_output import CompileOutput
from kukai.ir.contracts import ElementIdentityProof
from kukai.ir.diag import (
    Diagnostic, KirRefusal,
    PARSE_NOT_OBJECT, PARSE_UNKNOWN_OP, PARSE_UNKNOWN_FIELD, PARSE_BAD_VERSION,
    PARSE_MISSING_FIELD, PARSE_DUP_ID, PARSE_EXCLUSIVE_FIELDS,
    GROUND_UNSUPPORTED_KIND, GROUND_BAD_SELECTOR,
    GROUND_MODEL_BINDING, TYPE_BAD_TYPE, TYPE_BAD_ENUM, TYPE_BOUNDS, PLAN_LIMIT,
    PLAN_SOLO_OP,
)
from kukai.ir.emit_utils import (ELEMENT_ID_MAX, cs_identifier_fragment,
                                 cs_line_comment_fragment, cs_string_literal)
from kukai.ir.hosted_geometry import hosted_offset_check
from kukai.ir.lowering import lower_program
from kukai.ir.midend import (
    FieldOrigin,
    OperationFamily,
    OpProvenance,
    PlanEncodingError,
    PlannedOp,
    PlannedProgram,
    ProgramFamily,
)

logger = logging.getLogger(__name__)

MAX_OPS_PER_PROGRAM = 20    # user-authored (pre-macro-expansion) op budget
MAX_BULK_OPS = 300          # internal bulk (decompile/rebuild) pre-macro budget
MAX_VALIDATED_OPS = 320     # post-expansion ceiling (macros.MAX_EXPANDED_OPS + margin)

# ДВА БЮДЖЕТА — И ОТКАЗ ОБЯЗАН НАЗЫВАТЬ, КАКОЙ ИЗ НИХ ИСЧЕРПАН.
#
# Их два не по недосмотру, а по разной природе входа:
#   * АВТОРСКИЙ (MAX_OPS_PER_PROGRAM=20) меряет программу, НАПИСАННУЮ моделью.
#     Он мал намеренно: 210 из 586 живых отказов 30.07 — именно он, и это
#     работающий сигнал «выбрана не та форма» (повтор — в макрос, этапы — в
#     разные программы). Модель, которой разрешили писать по 300 операций, —
#     другой продукт с другими рисками.
#   * ВНУТРЕННИЙ (MAX_BULK_OPS=300) меряет ЧАНК МАТЕРИАЛИЗАТОРА, который никто
#     не писал руками: он собран из разбора живой модели, где 6 343 элемента
#     это норма, а не замысел автора.
# Оба ограничены сверху ОДНИМ послемакросным потолком MAX_VALIDATED_OPS — его
# не поднимает никто и никогда: это предел эмиттера, а не политика.
#
# Живой замер 30.07 (Snowdon Towers): разборщик резал по 250, единственная
# живая дверь мерила авторским бюджетом 20 — 6 343 элемента стоили 318 раундов
# вместо 26. Стык, а не язык. Поэтому имена бюджетов — константы, а не проза:
# отказ, который не называет исчерпанный бюджет, читается одинаково в обоих
# случаях и уводит ремонт не туда.
BUDGET_AUTHORED = "authored"
BUDGET_INTERNAL_BULK = "internal_bulk"


def pre_macro_budget(*, bulk: bool) -> tuple[str, int]:
    """Имя и величина предмакросного бюджета — ОДНА точка истины.

    Пара «как называется» / «сколько это» живёт вместе, чтобы отказ не мог
    назвать один бюджет, а померить другой."""
    return ((BUDGET_INTERNAL_BULK, MAX_BULK_OPS) if bulk
            else (BUDGET_AUTHORED, MAX_OPS_PER_PROGRAM))


# ── C# helpers emitted once per program (7.3-safe, read-only) ────────────────
_PREAMBLE = r"""
// KIR query program — generated; read-only by construction (no txn, no writes).
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
Func<Element, string> __LevelNameOf = (Element __e) =>
{
    // audit F2: bare Element.LevelId is InvalidElementId for whole categories
    // whose level binding lives in a parameter (the extractor's __ElementLevel
    // proved this with the SAME 4-BIP fallback chain — mirrored here so a
    // level_name filter/field never silently undercounts).
    try
    {
        ElementId __lid = null;
        try { __lid = __e.LevelId; } catch { }
        if (__lid == null || __lid == ElementId.InvalidElementId)
        {
            Parameter __lp = null;
            try { __lp = __e.get_Parameter(BuiltInParameter.WALL_BASE_CONSTRAINT); } catch { }
            if (__lp == null || !__lp.HasValue)
                try { __lp = __e.get_Parameter(BuiltInParameter.LEVEL_PARAM); } catch { }
            if (__lp == null || !__lp.HasValue)
                try { __lp = __e.get_Parameter(BuiltInParameter.SCHEDULE_LEVEL_PARAM); } catch { }
            if (__lp == null || !__lp.HasValue)
                try { __lp = __e.get_Parameter(BuiltInParameter.FAMILY_LEVEL_PARAM); } catch { }
            if (__lp != null && __lp.HasValue)
                __lid = __lp.AsElementId();
        }
        if (__lid == null || __lid == ElementId.InvalidElementId) return "";
        var __le = doc.GetElement(__lid) as Level;
        return (__le != null && __le.Name != null) ? __le.Name : "";
    }
    catch { return ""; }
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
""".strip("\n")


def _cs_str(s: str) -> str:
    """Return one C# string literal through the shared KIR boundary."""
    return cs_string_literal(s)


# ── parse + typecheck ────────────────────────────────────────────────────────

def _fail(diags: list, **kw) -> None:
    diags.append(Diagnostic(**kw))


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


def _check_kind(op: dict, i: int, oid: str, diags: list) -> Optional[str]:
    kind = op.get("kind")
    if kind == spec.KIND_ESCAPE:
        # Escape enum (SPEC 12.8): typed handoff to the recipe path, not a guess.
        _fail(diags, code=GROUND_UNSUPPORTED_KIND, op_index=i, op_id=oid, field_name="kind",
              got=spec.KIND_ESCAPE, candidates=sorted(spec.KINDS),
              message_ru="kind='other' — вне закрытой таблицы; маршрут: recipe/вики-путь")
        return None
    if not isinstance(kind, str) or kind not in spec.KINDS:
        _fail(diags, code=GROUND_UNSUPPORTED_KIND, op_index=i, op_id=oid, field_name="kind",
              got=kind, candidates=sorted(spec.KINDS),
              message_ru=f"неизвестный kind {kind!r}")
        return None
    return kind


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
        else:
            oid = raw_oid
    if not isinstance(name, str) or name not in spec.OPS:
        _fail(diags, code=PARSE_UNKNOWN_OP, op_index=i, op_id=oid, got=name,
              candidates=sorted(spec.OPS), message_ru=f"неизвестный op {name!r}")
        return None
    known = {"op", "id"} | {p.name for p in spec.OPS[name].params}
    for k in op:
        if k not in known:
            _fail(diags, code=PARSE_UNKNOWN_FIELD, op_index=i, op_id=oid, field_name=k,
                  candidates=sorted(known), message_ru=f"неизвестное поле '{k}' у {name}")
    if spec.OPS[name].family in spec.WRITE_FAMILIES:
        from kukai.ir import authoring
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

    if name == "query_list":
        fields = op.get("fields", list(spec.LIST_FIELDS))
        if not isinstance(fields, list) or not fields or \
                not all(isinstance(f, str) and f in spec.LIST_FIELDS for f in fields):
            _fail(diags, code=TYPE_BAD_TYPE, op_index=i, op_id=oid, field_name="fields",
                  expected=list(spec.LIST_FIELDS), got=fields,
                  message_ru="fields — непустой список из закрытого набора")
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

    if name == "query_inspect":
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
                  message_ru=f"pool должен быть одним из {sorted(choices)}")
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


@dataclass(frozen=True, slots=True)
class _OpPlanTrace:
    source_index: int
    source_op: str | None
    source_id: str | None
    macro_name: str | None
    expanded_fields: frozenset[str]
    defaulted_fields: tuple[str, ...]


def _parse_and_check_internal(
    program: Any,
    *,
    bulk: bool = False,
) -> tuple[list[dict], tuple[_OpPlanTrace, ...]]:
    diags: list[Diagnostic] = []
    if not isinstance(program, dict):
        raise KirRefusal([Diagnostic(code=PARSE_NOT_OBJECT,
                                     message_ru="программа должна быть JSON-объектом")])
    if program.get("ir_version") != spec.IR_VERSION:
        diags.append(Diagnostic(code=PARSE_BAD_VERSION, field_name="ir_version",
                                expected=spec.IR_VERSION, got=program.get("ir_version"),
                                message_ru="ir_version обязателен и должен быть '1.0'"))
    known_top = {"ir_version", "intent", "allow_destructive", "ops", "defaults"}
    # Internal A5 materialization binds each deterministic chunk to its durable
    # journal receipt.  This metadata is accepted only on the trusted ``bulk``
    # path; it is deliberately absent from the user/LLM schema and has no
    # emission semantics.
    if bulk:
        known_top.add("program_id")
    for k in program:
        if k not in known_top:
            diags.append(Diagnostic(code=PARSE_UNKNOWN_FIELD, field_name=k,
                                    candidates=sorted(known_top),
                                    message_ru=f"неизвестное поле конверта '{k}'"))
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
    if not isinstance(ops, list) or not ops:
        diags.append(Diagnostic(code=PARSE_NOT_OBJECT, field_name="ops",
                                message_ru="ops — непустой список"))
        raise KirRefusal(diags)
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
        # Отказ НАЗЫВАЕТ исчерпанный бюджет — и словом, и стабильным токеном.
        # Число ВНУТРЕННЕГО бюджета в авторский отказ не течёт намеренно:
        # сказанное модели «300» уже стоило раунда и переписи программы (замер
        # 27.07, башня) — она сочла чужой бюджет своим.
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
        raise KirRefusal(diags)
    # macro layer: deterministic expansion BEFORE validation (SPEC 12.3)
    from kukai.ir import macros
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
        raise KirRefusal(diags)
    seen_ids: set[str] = set()
    normed = []
    plan_traces: list[_OpPlanTrace] = []
    for i, op in enumerate(ops):
        n = _validate_op(op, i, diags)
        if n:
            if n["id"] in seen_ids:
                diags.append(Diagnostic(code=PARSE_DUP_ID, op_index=i, op_id=n["id"],
                                        field_name="id", message_ru="дубликат id"))
            seen_ids.add(n["id"])
            normed.append(n)
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
        diags.append(Diagnostic(code="KIR-L002", field_name="ops",
                                got=sorted(families),
                                message_ru="смешение query и write-опов в одной программе не поддерживается в v1"))
    # plan: op owning its own transaction scope is SOLE (KIR-L002, spec.SOLO_OPS).
    #
    # ЗДЕСЬ, А НЕ ТОЛЬКО В ЭМИТТЕРЕ, и это разница между «правило есть» и
    # «правило достижимо». Отказ жил ровно в одном месте — `emit_program`, то
    # есть ПОСЛЕ заземления. Значит песочница собирала программу, план её
    # принимал, и о стене модель узнавала только на живом устройстве, где
    # круглый рейс стоит дороже всего. Замер 04.08: `plan_program` принимал
    # `[create_stairs, create_wall]` молча. Живого Revit для этого правила не
    # нужно — оно о ФОРМЕ ПРОГРАММЫ, и потому обязано быть видно офлайн.
    # Отказ в эмиттере ОСТАЁТСЯ дословно: это последний рубеж, а не дубль.
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
                refs.extend((f"{p.name}[{j}]", item.get("value"), p)
                            for j, item in enumerate(value)
                            if isinstance(item, dict) and item.get("by") == "ref")
        for key, ref, param_spec in refs:
            if ref not in created:
                diags.append(Diagnostic(
                    code="KIR-L003", op_index=idx, op_id=n["id"], field_name=key,
                    got=ref, candidates=sorted(created),
                    message_ru=(f"ref «{ref}» не указывает на более ранний "
                                "оп с единичным referenceable-результатом")))
            elif not param_spec.accepts_reference(
                    created[ref].result.reference_kind):
                expected = [kind.value for kind in param_spec.ref_kinds]
                actual = created[ref].result.reference_kind
                diags.append(Diagnostic(
                    code="KIR-L004", op_index=idx, op_id=n["id"], field_name=key,
                    expected=expected,
                    got=actual.value if actual is not None else None,
                    message_ru=(f"ref «{ref}» должен указывать на результат "
                                "совместимого типизированного рода")))
        if ospec.result.referenceable:
            created[n["id"]] = ospec
        # place_family: ровно ОДИН способ задать положение.
        #
        # У Revit это две разные перегрузки NewFamilyInstance — по точке и по
        # кривой, — и выбирает между ними не автор программы, а само
        # семейство: у CurveBased-экземпляра LocationPoint не существует.
        # Поэтому «и то и другое» и «ни того ни другого» одинаково
        # неоднозначны, и оба обязаны быть отказом, а не догадкой. Половина
        # кривой — тоже не кривая: одна точка отрезок не задаёт.
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
            # Обязательность УСЛОВНА и потому живёт здесь, а не в схеме.
            #
            # Точечный вариант вызывает NewFamilyInstance(point, symbol,
            # LEVEL, …) — без уровня вызова нет. Кривой вызывает
            # NewFamilyInstance(REFERENCE, line, symbol) — уровня не
            # принимает вовсе, а вот без хоста не существует.
            #
            # Почему именно так, замерено 27.07 на живой модели ЭОМ:
            # перегрузка с уровнем спроецировала вертикальный отрезок на
            # плоскость уровня и схлопнула его в точку, а перегрузка по
            # ссылке честно отказала «line does not coincide with the input
            # face», когда отрезок не лежал на грани хоста. Кривое семейство
            # БЕЗ хоста обслуживает create_beam — у него своя перегрузка и
            # свой пул типов.
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
        # topology — "дверь за краем стены" is unexpressible, SPEC §4)
        if n["op"] in ("create_window", "create_door"):
            host = n.get("host") or {}
            wall = byid.get(host.get("value"))
            if wall is not None and wall.get("op") == "create_wall" \
                    and "p0_mm" in wall and "p1_mm" in wall \
                    and not relate.is_address(wall["p0_mm"]) \
                    and not relate.is_address(wall["p1_mm"]):
                # Адресованный хост проверяется ТЕМ ЖЕ судьёй в `ground`,
                # когда его концы станут числами — см. hosted_offset_check.
                hosted_offset_check(n, wall, str(host.get("value")), idx, diags)
    # policy-gate on the plan (SPEC 12.2): destructive ops need explicit opt-in
    if any(n["op"] == "delete" for n in normed) and program.get("allow_destructive") is not True:
        diags.append(Diagnostic(
            code="KIR-D001", field_name="allow_destructive",
            expected=True, got=program.get("allow_destructive"),
            message_ru="delete требует allow_destructive=true в конверте программы"))
    if diags:
        raise KirRefusal(diags)
    return normed, tuple(plan_traces)


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
                code="KIR-L005",
                field_name="bulk",
                expected=program.bulk,
                got=bulk,
                message_ru=("политика bulk не совпадает с уже построенным "
                            "неизменяемым планом"),
            )])
        return program

    normed, traces = _parse_and_check_internal(program, bulk=bulk)
    if len(normed) != len(traces):
        raise RuntimeError("normalised operations lost their planning trace")
    planned_ops: list[PlannedOp] = []
    for payload, trace in zip(normed, traces):
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
            planned_ops.append(PlannedOp.from_dict(
                payload,
                family=OperationFamily(ospec.family),
                effect=ospec.effect,
                result=ospec.result,
                provenance=provenance,
            ))
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
        ir_version=program["ir_version"],
        family=family,
        ops=tuple(planned_ops),
        intent=program.get("intent", ""),
        allow_destructive=program.get("allow_destructive") is True,
        bulk=bulk,
        source_op_count=len(program["ops"]),
        program_id=program.get("program_id"),
    )


def _parse_and_check(program: Any, *, bulk: bool = False) -> list[dict]:
    """Compatibility shim for legacy ground/emitter tests.

    New downstream code must consume :func:`plan_program`; this returns fresh
    dicts so a legacy caller cannot mutate the immutable plan.
    """
    return plan_program(program, bulk=bulk).to_ops()


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
    "column_symbols_structural": (".OfClass(typeof(FamilySymbol))"
                                  ".OfCategory(BuiltInCategory.OST_StructuralColumns)"),
    "column_symbols_architectural": (".OfClass(typeof(FamilySymbol))"
                                     ".OfCategory(BuiltInCategory.OST_Columns)"),
    "window_symbols": ".OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Windows)",
    "door_symbols": ".OfClass(typeof(FamilySymbol)).OfCategory(BuiltInCategory.OST_Doors)",
    "family_symbols": ".OfClass(typeof(FamilySymbol))",
    # Единственный пул с фильтром по ТИПУ РАЗМЕЩЕНИЯ — зеркало того же
    # фильтра в open_model.GROUND_SNAPSHOT_CS (два места, один закон; гейт
    # компилирует обе таблицы независимо, так что расхождение видно).
    # create_beam эмитит NewFamilyInstance(Line, …), который на точечном
    # семействе возвращает null: пусть каталог сразу не показывает то, чем
    # оп воспользоваться не может.
    "beam_types": (".OfClass(typeof(FamilySymbol))"
                   ".OfCategory(BuiltInCategory.OST_StructuralFraming)"
                   ".Cast<FamilySymbol>()"
                   ".Where(__bfs => { try { var __pt = __bfs.Family.FamilyPlacementType;"
                   " return __pt == FamilyPlacementType.CurveDrivenStructural"
                   " || __pt == FamilyPlacementType.CurveBased; } catch { return false; } })"),
    "foundation_symbols": (".OfClass(typeof(FamilySymbol))"
                            ".OfCategory(BuiltInCategory.OST_StructuralFoundation)"),
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
                # ЧЕМ ЭТОТ ТИПОРАЗМЕР ВООБЩЕ РАЗМЕЩАЮТ. Без этого поля пул
                # `family_symbols` не отвечает на единственный вопрос,
                # который к нему приходит от `place_family`: держит ли
                # символ точку. Замер живьём 04.08 («Проект1», 320 штук):
                # 279 ViewBased, 20 OneLevelBased, 16 OneLevelBasedHosted,
                # 4 TwoLevelsBased. Ни имя, ни категория этого не говорят —
                # `MullionType` id 407 назывался «50 x 150 мм» и при
                # размещении точкой уехал в (0,0,0), а системная панель
                # вернула LocationPoint == null.
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


def compile_program(program: Any, revit_version: str = "2026",
                    query_id: str = "", snapshot: Any = None,
                    *, bulk: bool = False,
                    isolation: str = "atomic",
                    disallow_wall_joins: bool = False,
                    stamp_scope: str = "",
                    expected_document: Any = None,
                    expected_identities: Sequence[
                        ElementIdentityProof] | None = None,
                    open_model_profile: Any = None) -> CompileOutput:
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
        # Grounders/emitters still operate on dicts; this is a detached lowering
        # view, never the plan object whose digest acceptance/evidence records.
        normed = planned.to_ops()
        stage = "target_profile"
        if revit_version not in spec.REVIT_VERSIONS:
            raise KirRefusal([Diagnostic(code="KIR-E001", field_name="revit_version",
                                         expected=list(spec.REVIT_VERSIONS),
                                         got=revit_version,
                                         message_ru="неизвестная версия Revit")])
        from kukai.compiler_contract import load_target_profile_manifest
        target_profile = load_target_profile_manifest().profile_for_year(
            revit_version)
        if normed and spec.OPS[normed[0]["op"]].family in spec.WRITE_FAMILIES:
            from kukai.ir import authoring, ground as ground_mod
            stage = "ground"
            grounded_program = ground_mod.ground_program(planned, snapshot)
            grounded = grounded_program.to_ops()
            guarded_identities = expected_identities
            if open_model_profile is not None:
                from kukai.ir.open_model import (
                    OpenModelProfile,
                    preflight_programs,
                )
                if not isinstance(open_model_profile, OpenModelProfile):
                    raise KirRefusal([Diagnostic(
                        code=GROUND_MODEL_BINDING,
                        message_ru=(
                            "профиль открытой модели имеет неверный тип"),
                    )])
                stage = "open_model_preflight"
                binding_report = preflight_programs(
                    {"ops": grounded},
                    open_model_profile,
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
            stage = "lower"
            lowered_program = lower_program(
                grounded_program,
                target_profile,
                isolation=isolation,
                disallow_wall_joins=disallow_wall_joins,
                stamp_scope=stamp_scope,
                expected_document=expected_document,
                expected_identities=guarded_identities,
                open_model_profile_digest=(
                    open_model_profile.digest
                    if open_model_profile is not None else None
                ),
            )
            stage = "emit_authoring"
            emitted_artifact = authoring.emit_artifact(lowered_program)
            return CompileOutput(
                ok=True, csharp=emitted_artifact.source, planned=planned,
                grounded=grounded_program,
                lowered=lowered_program,
                emitted=emitted_artifact,
                grounding_report=ground_mod.compiler_choices(grounded))
        stage = "emit_query"
        cs = emit_for_version(normed, revit_version)
        return CompileOutput(ok=True, csharp=cs, planned=planned)
    except KirRefusal as r:
        out = CompileOutput(ok=False, diagnostics=r.diagnostics)
        raw_ops = (program.to_ops() if isinstance(program, PlannedProgram)
                   else program.get("ops") if isinstance(program, dict)
                   else [])
        from kukai.ir import coverage_feed
        coverage_feed.record_rejections(r.diagnostics, raw_ops,
                                        query_id=query_id, revit_version=revit_version)
        unsupported = [d for d in r.diagnostics if d.code == GROUND_UNSUPPORTED_KIND]
        if unsupported:
            kinds = sorted({str(d.got) for d in unsupported if d.got is not None})
            out.handoff = {"route": "recipe-path", "reason": "unsupported_kind",
                           "kinds": kinds}
        return out
    except Exception as e:  # noqa: BLE001 — compiler must never panic (RISK R1/R4 discipline)
        incident_id = uuid.uuid4().hex
        logger.exception(
            "KIR compiler panic incident_id=%s stage=%s query_id=%s "
            "revit_version=%s plan_digest=%s input_type=%s",
            incident_id,
            stage,
            query_id or "-",
            revit_version,
            planned.plan_digest if planned is not None else "-",
            type(program).__name__,
        )
        return CompileOutput(ok=False, diagnostics=[Diagnostic(
            code="KIR-P000",
            message_ru=("внутренняя ошибка компилятора; сообщите "
                        f"incident_id={incident_id}"),
            incident_id=incident_id,
        )])


def compile_rebuild_chunk(program: Any, revit_version: str = "2026",
                          query_id: str = "", *,
                          stamp_scope: str = "",
                          expected_document: Any = None,
                          expected_identities: Sequence[
                              ElementIdentityProof] | None = None,
                          open_model_profile: Any = None,
                          snapshot: Any = None) -> CompileOutput:
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
    * ``disallow_wall_joins=True`` — faithful reproduction: auto-join extends
      re-created walls' location curves to joined walls' centerlines by half
      their thickness (live A5 evidence 2026-07-21: ±100/125/150mm endpoint
      shifts), so a rebuild must de-join to keep the extracted curves verbatim.
    """
    return compile_program(program, revit_version, query_id,
                           bulk=True, isolation="per_op",
                           disallow_wall_joins=True,
                           # Снимок (census) нужен заземлению для резолва по
                           # имени и умолчанию. Живой путь берёт его с моста;
                           # СУХОЙ гейт брать неоткуда — и потому он молча
                           # отказывал целым чанкам (KIR-G103) и печатал
                           # «1 из 3 чанков ok», хотя с каталогом источника
                           # компилируются все. Проброс закрывает эту ложь:
                           # каталог у нас есть, он сохранён рядом с разбором.
                           snapshot=snapshot,
                           stamp_scope=stamp_scope,
                           expected_document=expected_document,
                           expected_identities=expected_identities,
                           open_model_profile=open_model_profile)
