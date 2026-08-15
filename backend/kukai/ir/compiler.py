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

import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Sequence

from kukai.ir import faceref, relate, spec
from kukai.ir.contracts import ElementIdentityProof
from kukai.ir.diag import (
    Diagnostic, KirRefusal,
    PARSE_NOT_OBJECT, PARSE_UNKNOWN_OP, PARSE_UNKNOWN_FIELD, PARSE_BAD_VERSION,
    PARSE_MISSING_FIELD, PARSE_DUP_ID, PARSE_EXCLUSIVE_FIELDS,
    GROUND_UNSUPPORTED_KIND, GROUND_BAD_SELECTOR,
    GROUND_MODEL_BINDING, TYPE_BAD_TYPE, TYPE_BAD_ENUM, TYPE_BOUNDS, PLAN_LIMIT,
    PLAN_OP_CONTRACT, PLAN_PHASE_SHAPE, PLAN_SOLO_OP,
)
from kukai.ir.emit_utils import (ELEMENT_ID_MAX, cs_identifier_fragment,
                                 cs_line_comment_fragment, cs_string_literal)
from kukai.ir.midend import (
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
from kukai.ir.op_contract import OpContractError, contract_for

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
    """Имя и величина предмакросного бюджета — ОДНА точка истины.

    Пара «как называется» / «сколько это» живёт вместе, чтобы отказ не мог
    назвать один бюджет, а померить другой."""
    return ((BUDGET_INTERNAL_BULK, MAX_BULK_OPS) if bulk
            else (BUDGET_AUTHORED, MAX_OPS_PER_PROGRAM))


@dataclass
class CompileOutput:
    ok: bool
    csharp: Optional[str] = None                 # emitted Execute-body (doc in scope)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    per_version: dict[str, str] = field(default_factory=dict)
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
    # КВИТАНЦИЯ НАЗВАННОГО УМОЛЧАНИЯ: выборы, которые сделал КОМПИЛЯТОР, а не
    # автор программы. Выбор, которого вызывающий не видит, неотличим от
    # `.FirstOrDefault()` — а именно им плечо C# молча взяло 1 тип двери из 62
    # (замер 02.08.2026). Эхо авторского селектора сюда не попадает: там
    # решение принял автор, и отчитываться не о чем.
    grounding_report: list[dict] = field(default_factory=list)
    # ЗАЗЕМЛЁННЫЙ ВИД НИЖЕНИЯ — ровно те словари, из которых эмиттер собрал
    # `csharp`, и ничего кроме. Нужен ОДНОМУ потребителю: сертификату перевода
    # (`translation_cert.certify_program`), который проверяет свидетелей
    # СТАТИЧЕСКИ и потому обязан смотреть на ту же операцию, что ушла в C#, —
    # иначе он сертифицировал бы соседнюю программу.
    #
    # ЭТО НЕ ПЛАН. Приёмка и все доказательства висят на `planned.plan_digest`;
    # здесь — отсоединённый вид нижения, который никто не имеет права
    # предъявлять как замысел (та же оговорка стоит у `normed` внутри
    # `compile_program`). В `as_dict()` НЕ входит: от появления этого поля
    # квитанция не меняет ни одного байта.
    grounded_ops: list[dict] = field(default_factory=list)
    # ИЗОЛЯЦИЯ ТРАНЗАКЦИИ РЕВИТА, под которой эмитирован `csharp`:
    # `"atomic"` — вся программа в одной транзакции, отказ одного опа
    # откатывает СОСЕДЕЙ; `"per_op"` — каждый оп в своей SubTransaction, и
    # отказ стоит ровно своего опа.
    #
    # ИМЯ НАРОЧНО НЕ `isolation`. В этом же дереве уже есть
    # `serving._sandbox_receipt`, читающий `isolation` у результата ПЕСОЧНИЦЫ
    # PYTHON (`namespaces`/`filesystem`/`network_probe`) — другой предмет под
    # тем же словом. 13.08.2026 на этом омониме едва не был сделан вывод
    # «изоляция уже записывается». ОТСУТСТВУЮЩЕЕ ПОЛЕ МОЛЧИТ, ОМОНИМ ОТВЕЧАЕТ,
    # и потому опаснее.
    #
    # ЗАЧЕМ ОНО ЕЗДИТ ДАЛЬШЕ, В СТРОКУ СВИДЕТЕЛЯ: `tools/live_op_rates.py`
    # считает четыре корзины, и одна из них — «сопутствующий» (чужое нарушение
    # откатило транзакцию). **Под `per_op` сопутствующего не бывает ПО
    # ПОСТРОЕНИЮ.** Пока изоляция не записана, корпус смешивает две популяции
    # с разной семантикой корзины, и разделить их нечем. Поле нужно не для
    # любопытства: без него главный прибор по-оповых ставок интерпретируем
    # только для `atomic`-строк, а какие из них `atomic` — неизвестно.
    txn_isolation: str = "atomic"

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
        return d


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
    # Синтетические поля СНИМАЮТСЯ, а не принимаются: см. spec.SYNTHETIC_FIELDS
    # (там же — почему именно снимаются, и почему молчание здесь ничего не
    # прячет). Снимаем ТОЛЬКО у опов-владельцев: `__host_wall__` на
    # `create_wall` не принадлежит никому, и отказ ему по-прежнему верен.
    stripped = {k for k, owners in spec.SYNTHETIC_FIELDS.items()
                if k in op and name in owners}
    if stripped:
        op = {k: v for k, v in op.items() if k not in stripped}
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


def hosted_offset_check(hosted: dict, wall: dict, host_id: str,
                        idx: int | None, diags: list) -> bool:
    """«дверь за краем стены» — ОДИН судья, ДВЕ площадки вызова.

    Закон читает ЧИСЛА концов стены. Пока концы были литералами, он целиком
    жил на плане. С RELATE конец стены может приехать из снапшота — и тогда
    числа появляются только после ground. Прибор, замолчавший на этой части
    диапазона, был бы опаснее отсутствующего: дверь за краем адресованной
    стены уехала бы в транзакцию, где отказ стоит круглого рейса.

    Поэтому реализация одна, а вызывают её двое: `_parse_and_check_internal`
    (литеральные концы) и `ground.ground` (концы, разрешённые от осей).
    Побочный эффект тот же самый — `__host_wall__` для эмиттера.
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
    host_shape = {"p0_mm": wall["p0_mm"], "p1_mm": wall["p1_mm"]}
    if isinstance(arc, dict):
        host_shape["arc"] = arc
    # Имя берётся у ВЛАСТИ: писатель и четверо читателей обязаны говорить об
    # одном поле, и единственный способ это обеспечить — не давать никому
    # писать его имя от себя.
    #
    # Согласие «кто сюда доходит» и «кто объявлен владельцем» держит ТЕСТ
    # (`tests/test_synthetic_fields_have_one_authority.py`), а не `assert`
    # здесь. Пробовал `assert` — и он показал ровно свою негодность: под
    # `python -O` он исчезает, то есть инвариант пропал бы первым там, где
    # дороже всего; а до того он приезжает НЕ отказом, а ПАНИКОЙ компилятора
    # (incident_id, stage=plan) — то есть на путь, где отказывать нечему,
    # и вызывающий читает аварию вместо диагноза.
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
    member_path = f"members[{member_id or member_index}]"
    return replace(
        diagnostic,
        op_index=group_index,
        op_id=group_id,
        field_name=(f"{member_path}.{suffix}" if suffix else member_path),
    )


def _plan_group_members(
    members: list[dict[str, Any]],
    *,
    group_id: str,
    group_index: int,
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

    # ГРУППА — ЭТО МАЛЕНЬКАЯ ПРОГРАММА В СВОЁМ ПРОСТРАНСТВЕ ИМЁН.
    #
    # Раньше каждый член планировался ОТДЕЛЬНОЙ программой из одного опа
    # (`"ops": [candidate]`), и это делало ссылку на соседа по группе
    # невыразимой ПО ПОСТРОЕНИЮ: во вложенной программе стоял ровно один оп,
    # так что `ref` не мог указать никуда. Дверь адресует свою стену только
    # через `ref` — значит этаж со стенами И дверьми группой не собирался.
    #
    # **Цена этого, замерена 12.08.2026:** 41.1% элементов настоящей 59-этажной
    # башни живут внутри групп (стены 94.9%, несущие колонны 100%, панели
    # витража 99.3%, двери 91.4%), потому что человек моделирует ОДИН этаж и
    # ставит его группой. Единственной доступной нам формой оставалось
    # перечисление, а оно упирается в потолок 300 при медиане настоящего этажа
    # 796 опов — отсюда 151 программа на здание, которые модель резала вручную.
    #
    # Планируем всех членов ОДНОЙ вложенной программой. Тогда порядок, роды
    # ссылок и KIR-L003/L004 работают ровно теми же правилами, что и в обычной
    # программе, без единого исключения: «более ранний оп» внутри группы
    # означает «член, объявленный выше». Ничего специального про `ref` знать не
    # нужно — нужно лишь дать членам общую программу, которой у них не было.
    if candidates:
        try:
            nested = plan_program({
                "ir_version": spec.IR_VERSION,
                "intent": f"members of {group_id}",
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
            # ПЛАН — НЕ ПРОГРАММА, И ОТКАЗ ОБЯЗАН СКАЗАТЬ ИМЕННО ЭТО.
            # `phases` — законная часть конверта, которую собирает `course.
            # phase()`; незаконно здесь другое — отдать план функции, которая
            # исполняет ОДНУ транзакцию. Это последний рубеж: живая дверь режет
            # план на пачку (`split_phases`) ВЫШЕ этого места, и сюда план
            # доезжает только у того, кто резать не стал. Общее «неизвестное
            # поле» посылало бы такого читателя убирать поле, то есть терять
            # чекпойнты, — самая дорогая из возможных починок.
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
    nested_member_plans: list[tuple[PlannedOp, ...]] = []
    for i, op in enumerate(ops):
        n = _validate_op(op, i, diags)
        if n:
            if n["id"] in seen_ids:
                diags.append(Diagnostic(code=PARSE_DUP_ID, op_index=i, op_id=n["id"],
                                        field_name="id", message_ru="дубликат id"))
            seen_ids.add(n["id"])
            member_plans: tuple[PlannedOp, ...] = ()
            if n["op"] == "create_group" and isinstance(n.get("members"), list):
                try:
                    member_plans = _plan_group_members(
                        n["members"], group_id=n["id"], group_index=i)
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
                for j, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    if item.get("by") == "ref":
                        refs.append((f"{p.name}[{j}]", item.get("value"), p))
                        continue
                    # ВТОРАЯ СТУПЕНЬ СЕЛЕКТОРА (`{"by": "face", "of": ...}`).
                    #
                    # РЕБРО ГРАФА БЕРЁТСЯ ИЗНУТРИ, И ЭТО ОБЯЗАТЕЛЬНО, А НЕ
                    # АККУРАТНО. Обход ниже — не родовой: он смотрит ровно на
                    # ВЕРХНИЙ уровень элемента списка. Ссылка, уехавшая на
                    # уровень глубже (в `of`), стала бы для него невидимой — и
                    # тогда KIR-L003 («ref не указывает на более ранний оп») и
                    # KIR-L004 (род результата) перестали бы срабатывать МОЛЧА,
                    # а эмиттер сослался бы на переменную C# без гарантии, что
                    # производящий оп стоит раньше. Именно поэтому вторая
                    # ступень несёт ЦЕЛЫЙ селектор, а не голый id опа: ребро
                    # остаётся выразимым в тех же терминах, и учить об этом
                    # надо ровно одно место — вот это.
                    inner = item.get("of")
                    if (item.get("by") == faceref.BY_FACE
                            and isinstance(inner, dict)
                            and inner.get("by") == "ref"):
                        refs.append((f"{p.name}[{j}].of", inner.get("value"), p))
        # RELATE, АДРЕС ОТ ЭЛЕМЕНТА: ссылка живёт ВНУТРИ значения точечного
        # параметра, то есть ровно на том уровне глубже, о котором предупреждает
        # блок выше. Ребро берётся здесь, и берётся ОТДЕЛЬНЫМ списком, а не
        # подмешиванием в `refs`: проверка рода (KIR-L004) спрашивает
        # `param_spec.ref_kinds`, а у рода `pt_xy`/`pt_xyz` он ПУСТ по
        # построению (точка не принимает ссылок), — значит общая ветка отказала
        # бы КАЖДОМУ верному адресу. Род здесь и не при чём: адрес не передаёт
        # ссылку в C#, он ЧИТАЕТ числа адресуемого опа на компиляции, и
        # единственное требование к цели — стоять ВЫШЕ. Какие операции вообще
        # адресуемы, решает `relate.ELEMENT_GEOMETRY` на стадии ground: этот
        # список — про порядок, а не про геометрию.
        for key, ref in relate.element_address_refs(n):
            if ref not in created:
                diags.append(Diagnostic(
                    code="KIR-L003", op_index=idx, op_id=n["id"],
                    field_name=f"{key}.at_element", got=ref,
                    candidates=sorted(created),
                    message_ru=(
                        f"адрес от элемента: «{ref}» не указывает на более "
                        f"ранний оп этой программы. Адрес читает числа, "
                        f"которые автор уже написал, поэтому адресуемый оп "
                        f"обязан стоять ВЫШЕ адресующего")))
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
        # CONTOUR: прямая ломаная ЛИБО типизированный эскиз — ровно одно.
        #
        # У операции, которая умеет и то и другое, форма задана ДВАЖДЫ, и
        # «оба сразу» ровно так же неоднозначны, как «ни одного»: в первом
        # случае непонятно, какое из двух описаний истинно, во втором строить
        # нечего. Оба обязаны быть типизированным отказом, а не догадкой —
        # тот же закон и тот же код KIR-P007, что у place_family ниже.
        #
        # Заменить `outline` на `contour` было нельзя: обратный ход
        # (decompile/materialize.py) эмитирует именно прямые точки, и замена
        # разомкнула бы круг. Отсюда параллельное поле, отсюда и это правило.
        #
        # ПРАВИЛО ЧИТАЕТСЯ ИЗ РЕЕСТРА, А НЕ ИЗ СПИСКА ИМЁН ОПОВ: пара — это
        # параметр рода `pts` и параметр рода `region` у одной операции.
        # Следующая операция, которой достанется эскиз, получит проверку
        # вместе с полем, а не отдельным коммитом «мы забыли».
        #
        # ПОЛОВИНА ПРАВИЛА, КОТОРУЮ ПЛАН СКАЗАТЬ НЕ ВПРАВЕ (09.08.2026,
        # волна проёма). «Оба сразу» неоднозначны ВСЕГДА и отказывают здесь.
        # «Ни одного» — нет: у операции с развилкой `variety` (закрытое
        # множество перегрузок Revit; имя дискриминатора — соглашение
        # реестра, NAMING NOTE в `ops_struct.py`) обязательность формы
        # УСЛОВНА ПО РОДУ, а план родов не разбирает. У create_opening род
        # `wall_rect` формы не имеет вовсе — он задаётся двумя углами, — и
        # общий отказ «форма не задана» обвинял бы верную программу. Нижняя
        # половина взаимной обязательности живёт поэтому в ветке рода
        # (`opening_emit._emit_host_face`, типизированный KIR-P005,
        # называющий ОБА входа), ровно тем же швом, которым `create_railing`
        # и `create_foundation` держат свои условно обязательные поля.
        outline_p = next((p.name for p in ospec.params if p.kind == "pts"), None)
        region_p = next((p.name for p in ospec.params if p.kind == "region"), None)
        variety_dispatched = any(p.name == "variety" for p in ospec.params)
        if outline_p and region_p:
            # Поле, о котором уже сказано конкретнее (кривой контур, битый
            # регион), здесь не пересказывается вторым, более общим голосом.
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
                            f"{outline_p} (ломаная из 3..64 точек), либо "
                            f"{region_p} (эскиз CONTOUR: rect/l/poly, дуги, "
                            f"отверстия)")))
            if has_region:
                # Отверстия у региона СВОИ (region.holes). Принять рядом с
                # ним ещё и плоский `holes` значило бы взять одно описание
                # проёмов и молча выбросить другое.
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
        # ВИНТОВОЙ МАРШ: прямые концы ЛИБО винт — ровно одно.
        #
        # Тот же закон и тот же код KIR-P007, что у CONTOUR выше и у
        # place_family ниже, и по той же причине: у операции, умеющей обе
        # формы, «оба сразу» так же неоднозначны, как «ни одного» — в первом
        # случае непонятно, какая из двух форм марша истинна, во втором
        # строить нечего. Догадка здесь означала бы ТИХО ДРУГУЮ лестницу.
        #
        # ПРАВИЛО ЧИТАЕТСЯ ИЗ РЕЕСТРА: пара — это параметр рода `spiral` и
        # концы отрезка (род `pt_xy`) у одной операции. Второй оп, которому
        # достанется винт, получит проверку вместе с полем, а не отдельным
        # коммитом «мы забыли».
        #
        # Заменить прямые концы винтом было нельзя: обратный ход
        # (decompile/lift.py::_lift_stairs) эмитирует именно `p0_mm`/`p1_mm`.
        spiral_p = next((p.name for p in ospec.params if p.kind == "spiral"),
                        None)
        if spiral_p:
            ends = [p.name for p in ospec.params if p.kind == "pt_xy"]
            present_ends = [k for k in ends if k in n]
            has_spiral = spiral_p in n
            # Поле, о котором уже сказано конкретнее (битая точка, битый
            # винт), здесь не пересказывается вторым, более общим голосом.
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
                    # Половина прямого марша — не марш: одна точка отрезка не
                    # задаёт кривую (тот же довод, что у place_family).
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
                code="KIR-L005",
                field_name="bulk",
                expected=program.bulk,
                got=bulk,
                message_ru=("политика bulk не совпадает с уже построенным "
                            "неизменяемым планом"),
            )])
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
                result=ospec.result,
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


# ═════════════════════════════════════════════════════════════════════════════
# ПЛАН СТРОИТЕЛЬСТВА — ОДИН СКРИПТ РЕЖЕТСЯ НА ПАЧКУ ПРОГРАММ
# ═════════════════════════════════════════════════════════════════════════════
#
# ЧТО ЭТО ЗАКРЫВАЕТ, ЧИСЛОМ. Здание сегодня нельзя написать одним скриптом
# ВООБЩЕ: скрипт с `phase()` получает СРАЗУ ДВА отказа — KIR-P003 («неизвестное
# поле конверта 'phases'») и KIR-L002 («create_stairs — единственный оп своей
# программы»), — и второй отказ сам же советует то, что и есть работа, которую
# модель делает в уме: «здание — это ПАЧКА программ: тело отдельно, лестницы
# отдельно; уровень доступен лестничной по ИМЕНИ». Замер по корпусу отказов
# (`data/telemetry/kir_rejections.jsonl`, 1469 строк, 16.07–04.08, попытками
# авторства, а не строками: 349 попыток при склейке строк одной компиляции —
# `coverage_feed.record_rejections` пишет их подряд, каждую со своим now()):
# в 105 попытках из 349 (30.1%) отказ — это ГРАНИЦА ПРОГРАММЫ, и ни один из
# четырёх её видов не является ошибкой в геометрии:
#
#     бюджет программы (KIR-L001)          50 попыток
#     ссылка через границу (KIR-L003)      44
#     уровень по ИМЕНИ не найден           10   ← ровно тот совет, что выше
#     соло-оп с соседом (KIR-L002)          1
#
# Разметку границ автор уже рисует (`course.phase()`, 09.08). Здесь стоит
# ВТОРАЯ половина: план превращается в ПАЧКУ программ — ту самую единицу,
# которой здание уже является для судьи (`design_check.check_bundle`), для
# чертежа (`preview`) и для витрины (`live/plan_stream`). Второго механизма не
# заводится: и вход (таблица `phases`), и выход (пачка) уже существовали.
#
# ЧЕГО ЗДЕСЬ НЕТ И НЕ БУДЕТ. Бюджет `MAX_OPS_PER_PROGRAM` не поднимается ни на
# единицу: каждое звено пачки идёт через тот же `plan_program` и меряется тем
# же бюджетом. План не даёт написать программу БОЛЬШЕ — он даёт написать
# ЗДАНИЕ, не считая границы в уме.


@dataclass(frozen=True)
class PhaseLink:
    """Одно звено плана: имя фазы, её номер и её ПРОГРАММА.

    Имя едет РЯДОМ с программой, а не внутри неё, и это не стиль: конверт
    программы закрыт (`known_top`), и лишнее поле в нём — типизированный отказ
    KIR-P003. Звено обязано быть программой, неотличимой от написанной руками,
    иначе «исполняется то же самое» перестало бы быть правдой.
    """

    index: int
    name: str
    program: dict


def _refuse_plan(message: str, **fields: Any) -> KirRefusal:
    return KirRefusal([Diagnostic(code=PLAN_PHASE_SHAPE,
                                  message_ru=message, **fields)])


def split_phases(program: Any) -> list[PhaseLink]:
    """Программа с таблицей `phases` -> ПАЧКА программ, по одной на фазу.

    ЧИСТАЯ ФУНКЦИЯ: ничего не исполняет, ничего не заземляет, ни одного опа не
    трогает. Опы уезжают в звенья ПОБАЙТОВО теми же — их дайджест подписывает
    замысел, и переписанный по дороге оп сделал бы подпись подписью не того.

    ЗАКОН, КОТОРЫЙ ЗДЕСЬ ПРОВЕРЯЕТСЯ, РОВНО ОДИН — РАЗБИЕНИЕ. `op_ids` всех
    фаз, сцепленные по порядку, обязаны быть ТЕМ ЖЕ списком id, что и `ops`
    программы: тот же порядок, каждый ровно один раз. Всё остальное —
    бюджет, соло-оп, DAG ссылок, границы чисел — проверяет `plan_program` НАД
    КАЖДЫМ ЗВЕНОМ, и повторять его здесь значило бы завести второй экземпляр
    правила, который разойдётся с первым на первой же правке реестра.

    ПОЧЕМУ ПРОВЕРЯЕТСЯ ХОТЬ ЧТО-ТО, если таблицу строит `course.phase()`,
    который уже её и держит. Потому что таблица приезжает в КОНВЕРТЕ, а конверт
    может прислать кто угодно: `serving` не отличает конверт, собранный
    песочницей, от конверта, набранного руками. Разбиение — единственный факт,
    который здесь нельзя восстановить ниоткуда ещё, и молча съеденный лишний
    оп означал бы элемент, который никто не построит и о котором никто не
    скажет.
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
    for op in ops:
        if not isinstance(op, dict) or not isinstance(op.get("id"), str):
            raise _refuse_plan(
                "план режется ПО ИДЕНТИФИКАТОРАМ опов, и оп без строкового "
                "`id` в нём неадресуем",
                field_name="ops", got=type(op).__name__)
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
        missing = [oid for oid in written if oid not in set(flat)]
        twice = sorted({oid for oid in flat if flat.count(oid) > 1})
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
    """id опа -> ElementId, взятый из КВИТАНЦИИ ИСПОЛНЕНИЯ этой фазы.

    ЧТО СЧИТАЕТСЯ ПРОДУКТОМ. Только результат, который реестр объявил
    ССЫЛАЕМЫМ (`ResultSpec.referenceable`) — то есть ровно то, на что внутри
    программы законен `by=ref`. Группа и удаление несут идентичность и
    ссылаемыми НЕ являются, и это записано в докстроке самого `ResultSpec`:
    подставить их id в селектор следующей фазы значило бы разрешить через
    границу больше, чем разрешено внутри программы.

    ГДЕ ЛЕЖИТ ЧИСЛО — ГОВОРИТ РЕЕСТР (`identity_field`), а не догадка по имени
    ключа. Ключ сегодня всюду `"id"`, но он объявлен полем спецификации, и
    зашитая строка `"id"` разошлась бы с реестром молча.

    МОЛЧАНИЕ ЗДЕСЬ ЗАКОННО: строка без идентичности просто не становится
    продуктом. Отказ поднимает ПОТРЕБИТЕЛЬ (`substitute_phase_results`), когда
    метка ищет продукта и не находит, — потому что только там известно, что
    его действительно ждали.
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
            number = int(value)                     # мост шлёт и "42", и 42
        except (TypeError, ValueError):
            continue
        if 1 <= number <= ELEMENT_ID_MAX:
            products[str(op["id"])] = number
    return products


def substitute_phase_results(program: Any, products: Any) -> dict:
    """Метки `phase_result` -> `{"by": "element_id", "value": <int>}`.

    ЭТО И ЕСТЬ ТО ЕДИНСТВЕННОЕ, ЧТО ПЕРЕСЕКАЕТ ГРАНИЦУ ПРОГРАММЫ. `by=ref`
    через границу НЕ проходит и проходить не может: соседняя фаза исполнена
    ОТДЕЛЬНОЙ транзакцией, и внутрипрограммной ссылки на её элемент к этому
    моменту не существует. Что существует — настоящий ElementId в квитанции
    той фазы; подстановка переносит его туда, куда автор поставил метку, и
    ровно этим снимает с автора перепечатывание id из прошлой квитанции.

    НЕНАЙДЕННЫЙ ПРОДУКТ — ТИПИЗИРОВАННЫЙ ОТКАЗ, А НЕ ПРОПУСК. Метка есть
    ОБЯЗАТЕЛЬСТВО подставить: оставить её как есть значило бы отправить в
    `plan_program` форму селектора, которой в языке нет, и получить отказ,
    указывающий не на ту причину.
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
    # wave/mep-electrical (2026-08-09) — зеркало трёх новых __AddPool в
    # open_model.GROUND_SNAPSHOT_CS (два места, один закон; ворота компилируют
    # обе таблицы независимо, так что расхождение видно, а не тихо).
    "conduit_types": ".OfClass(typeof(Autodesk.Revit.DB.Electrical.ConduitType))",
    "flex_duct_types": ".OfClass(typeof(Autodesk.Revit.DB.Mechanical.FlexDuctType))",
    "flex_pipe_types": ".OfClass(typeof(Autodesk.Revit.DB.Plumbing.FlexPipeType))",
    # wave/analysis (2026-08-09) — зеркало четырёх новых __AddPool в
    # open_model.GROUND_SNAPSHOT_CS (два места, один закон; ворота компилируют
    # обе таблицы независимо, так что расхождение видно, а не тихо). Спросить
    # каталог ДО попытки здесь важнее обычного: в реальном расчётном проекте
    # случаев загружения десятки, и `by=name` без предварительного списка —
    # это KIR-G101/G102 ходом позже.
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
    # wave/framing (2026-08-09) — зеркало нового __AddPool в
    # open_model.GROUND_SNAPSHOT_CS (два места, один закон; ворота компилируют
    # обе таблицы независимо, так что расхождение видно, а не тихо).
    # ЖИВОЙ ЗАМЕР 10.08.2026: `TrussType` компилируется 6/6 и ЕСТЬ в API,
    # но Revit 2023 бросает на нём в рантайме («exists in the API, but not
    # in Revit's native object model — try FamilySymbol»). Снимок собирается
    # ОДНИМ телом, поэтому падал весь снимок и с ним ЛЮБАЯ живая запись.
    "truss_types": (".OfClass(typeof(FamilySymbol))"
                    ".OfCategory(BuiltInCategory.OST_Truss)"),
    # wave/sweep (2026-08-09). `slab_edge_types` — обычный сбор по классу.
    # `wall_sweep_types` — ЕДИНСТВЕННАЯ строка этой таблицы, собранная по
    # категориям, и это не вкус: класса `WallSweepType`-как-ElementType в API
    # НЕТ ВОВСЕ (`WallSweepType` — перечисление {Sweep, Reveal}, замерено
    # компиляцией на шести версиях), а сам тип профиля живёт обычным
    # ElementType в OST_Cornices либо OST_Reveals. `WhereElementIsElementType`
    # обязателен: без него в пул попали бы и сами построенные профили.
    "slab_edge_types": ".OfClass(typeof(SlabEdgeType))",
    "wall_sweep_types": (".WherePasses(new ElementMulticategoryFilter("
                         "new List<BuiltInCategory> { "
                         "BuiltInCategory.OST_Cornices, "
                         "BuiltInCategory.OST_Reveals }))"
                         ".WhereElementIsElementType()"),
    # wave/detail (2026-08-09) — зеркало нового __AddPool в
    # open_model.GROUND_SNAPSHOT_CS (два места, один закон; ворота компилируют
    # обе таблицы независимо, так что расхождение видно, а не тихо). ПО
    # КЛАССУ, а не по категории: OST_FilledRegion держит и сами заливки, и их
    # типы, то есть категорийный каталог показал бы модели строки, которые
    # `FilledRegion.Create` отвергнет.
    "filled_region_types": ".OfClass(typeof(FilledRegionType))",
    # ═══ 12.08.2026. Восемь пулов, в которые компилятор УМЕЛ ПИСАТЬ, не умея
    # ЧИТАТЬ. Идиома каждого не сочинена здесь, а взята ДОСЛОВНО у второго
    # носителя того же закона — `open_model.GROUND_SNAPSHOT_CS`, где эти пулы
    # снимок собирает УЖЕ (`__AddPool(...)`). Две таблицы намеренно ведут
    # порознь и обе компилирует гейт, так что расхождение видно, а не тихо —
    # это записанное решение файла, и оно здесь соблюдено, а не обойдено.
    "ceiling_types": ".OfClass(typeof(CeilingType))",
    "railing_types": (".OfClass(typeof("
                      "Autodesk.Revit.DB.Architecture.RailingType))"),
    # Толща рельефа: своего типа у неё в API нет на всех шести версиях,
    # поэтому отбор идёт по ИМЕНИ типа среди HostObjAttributes — ровно тем же
    # выражением, каким его собирает снимок.
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
        # ВЕРСИЯ ОБЪЯСНЯЕТ ПУСТОЙ ПУЛ, ПОЭТОМУ ОТВЕЧАЕТ ПЕРВОЙ (13.08.2026).
        #
        # Стоит ИМЕННО ЗДЕСЬ — после нормализации, до заземления. Пока
        # проверка жила только в эмиссии, автор на Revit 2023 получал
        # «toposolid_types: пусто в модели» и уходил заводить тип толщи
        # рельефа на версии, где толщ рельефа не бывает: заземление бежит
        # раньше, и побеждал отказ, сработавший первым.
        #
        # Список адресный, а не механизм: замерено, что версионно заперт РОВНО
        # ОДИН пул из 36 (`ToposolidType` отсутствует в эталонных сборках
        # 2021-2023). Таблица «способность -> версия» стала бы третьей копией
        # знания, живущего в эмиттерах, и разошлась бы с ними.
        from kukai.ir.ops_site import toposolid_version_refusal
        _version_refusals = [
            d for d in (toposolid_version_refusal(op, revit_version)
                        for op in normed) if d is not None]
        if _version_refusals:
            raise KirRefusal(_version_refusals)
        if normed and spec.OPS[normed[0]["op"]].family in spec.WRITE_FAMILIES:
            from kukai.ir import authoring, ground as ground_mod
            stage = "ground"
            typed_open_model = None
            if open_model_profile is not None:
                from kukai.ir.open_model import (
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
                from kukai.ir.open_model import (
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
                expected_document=expected_document,
                expected_identities=guarded_identities)
            return CompileOutput(
                ok=True, csharp=cs, planned=planned,
                grounded=grounded_program,
                grounding_report=ground_mod.compiler_choices(grounded),
                grounded_ops=grounded,
                txn_isolation=isolation)
        stage = "emit_query"
        cs = emit_for_version(normed, revit_version)
        return CompileOutput(ok=True, csharp=cs, planned=planned,
                             txn_isolation=isolation)
    except KirRefusal as r:
        out = CompileOutput(ok=False, diagnostics=r.diagnostics)
        raw_ops = (program.to_ops() if isinstance(program, PlannedProgram)
                   else program.get("ops") if isinstance(program, dict)
                   else [])
        from kukai.ir import coverage_feed
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
        return CompileOutput(ok=False, diagnostics=[Diagnostic(
            code="KIR-P000",
            message_ru="внутренняя ошибка компилятора",
            incident_id=incident_id,
        )])


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
                           open_model_profile=open_model_profile,
                           ground_context=ground_context,
                           turn_id=turn_id,
                           action_id=action_id,
                           query_fingerprint=query_fingerprint,
                           source_kind=source_kind)
