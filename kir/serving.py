"""KIR serving — the `revit_ir` tool (INTEGRATION_PLAN_D5 §2, stage 2).

Exposure: KUKAI_KIR_TOOL=stage2 AND the turn's device is in the installation's
allow-list (KUKAI_ADMIN_DEVICES; empty = live path off, §18.5) →
inject_revit_ir_schema() adds the tool (create_element additive-gating
contract: flag-off turns are byte-identical). Dispatch re-checks the gate
(defense in depth) and is ABSOLUTE fail-open: any internal exception becomes
a typed result dict — never an exception into the turn, and a refusal is a
NORMAL tool result carrying `handoff` so the model falls back to the recipe
path itself («handoff не ломает turn»).

Execution: the emitted C# goes through RevitExecutionPipeline.run_declarative
(create_element's transport — compile-checked, timeout-safe, NO LLM repair
loop: KIR emit is compiler-owned; a repair mutation would break the witness
assumptions). Authoring/modify programs first fetch a ground snapshot via one
read-only declarative round-trip (_SNAPSHOT_CS below, 6/6 gate-checked).

Selection is NOT KIR's job: query results carry element ids — the model
chains show_elements (the existing selection tool) on them (D5 §1 note).
"""
from __future__ import annotations

import asyncio
import json
import functools
import logging
import math
import os
from kir import env  # noqa: E402
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from kir import ports

from kir.a5_recovery import (
    A5Journal,
    A5JournalError,
    A5Lease,
    A5LeaseError,
    A5Phase,
    stamp_scope as _a5_stamp_scope,
)
from kir.envelope import ErrCode, attach_err
from kir.contracts import (CommitReceipt, DocumentFingerprint,
                                RevisionProof, RunId)
from kir.bridge_result import extract_error as _extract_error
from kir.bridge_result import is_unconfirmed as _is_unconfirmed_outcome
from kir.bridge_result import (
    expected_results as _expected_results,
    explicit_commit_status as _explicit_commit_status,
    postcondition_violations as _postcondition_violations,
    result_contract_diagnostic as _result_contract_diagnostic,
)
from kir import revit_version as _rv
from kir.acceptance_journal import AcceptanceJournalError
from kir.acceptance_runtime import (
    AcceptanceRuntimeError,
    AcceptanceSession,
    execution_operation_identity,
    prepare_acceptance,
)
from kir.acceptance_evidence import (
    REGULAR_WRITE_EXECUTION_LANE,
    ExecutionArtifactBinding,
)
from kir.open_model import (
    GROUND_SNAPSHOT_CS as _OPEN_MODEL_SNAPSHOT_CS,
    OpenModelProfile,
    OpenModelProfileError,
    open_model_preflight_enabled as _open_model_preflight_enabled,
    preflight_programs as _preflight_open_model,
    prune_ground_snapshot,
)
from kir import diag  # the refusal's outcome is read from the DISPATCHER, not from a table
from kir.diag import (
    CERT_UNPROVEN,
    CERT_VACUOUS,
    Diagnostic,
    SANDBOX_RECON,
    W_POSTCONDITIONS_COMMITTED,
)
from kir.outcome import (
    AcceptanceState,
    ExecutionState,
    ProgramOutcome,
    WitnessState,
    execution_unconfirmed,
    independently_assessed,
    program_not_started,
    query_accepted,
    write_committed,
    write_rolled_back,
)

logger = logging.getLogger(__name__)

# ─── §18.5, deployment neutrality: the allow-list belongs to the DEPLOYMENT ──
#
# The live reverse path (revit_ir / revit_decompile / revit_rebuild / A5)
# stands on two conditions: a stage flag AND a device from the operator's
# list. The second condition used to be the literal below — the code
# author's own machine id, because of which the reverse path was FOREVER
# unrunnable for a third-party developer, and the refusal gave no hint what
# to configure.
#
# The carrier of the constraint changed, the meaning did not: the list is
# set by the deployment's operator through KUKAI_ADMIN_DEVICES
# (comma-separated). The variable set and empty ⇒ the live path is switched
# off entirely (this is a legal way to ship the compiler with no live Revit
# at all).
_ADMIN_DEVICES_ENV = "KUKAI_ADMIN_DEVICES"
# THE SENTENCE WAS CARRIED OUT ON 15.08.2026. A RAW MACHINE IDENTIFIER used
# to stand here (`_MIGRATION_ADMIN_DEVICE`) — a fallback for the case where
# the variable is unset. The canon had already called it a leak on 09.08:
# this file ships out as a separate open-source repository under Apache-2.0,
# and a stranger's machine id inside it is not a TODO.
#
# The condition for lifting it is not resolve but a MEASUREMENT: on 15.08
# the variable was explicitly set in the prod `.env`, the service was
# restarted gracefully, the live path was verified BY EXECUTION (`ok:true`,
# 9657 walls). The carrier of the constraint is the deployment's
# configuration, and it alone.
#
# The variable NOT set ⇒ an empty list ⇒ the live path is switched off, and
# the refusal NAMES `KUKAI_ADMIN_DEVICES` (`admin_gate_message_ru`). This is
# a legitimate way to ship the compiler with no live Revit, not a
# malfunction: the refusal must not be silent, but we no longer have the
# right to guess someone else's device either.
_FLAG = "KIR_TOOL"
_QUERY_TIMEOUT_MS = 30_000
_WRITE_TIMEOUT_MS = 120_000
_SNAPSHOT_TIMEOUT_MS = 30_000


def _effective_timeout_ms(family: str, requested: int | None) -> int:
    """What timeout the turn will get: the one the caller ordered, or ours by kind.

    🔴 WHY THIS HAS A NAME. The decision used to live as a nameless
    conjunction inside `_handle_revit_ir_inner`, and there was nothing to
    pin it with — the same argument by which this tree hoisted out
    `green_is_earned`. While it had no name, the admin door DOCUMENTED
    `timeout_ms` twice and never read it once (measured live 24.08: a write
    with `timeout_ms: 120` went through in full), and there was nothing for
    that to turn red on.

    🔴 A SECOND BELT, AND IT IS DELIBERATELY SILENT. The bounds are named by
    the DOOR (`admin_kir._timeout_ceiling_ms`) — the same place where the
    bridge's ceiling is reachable, and there the refusal is typed. An unfit
    number should not reach here; if it does, we fall back to the default
    rather than throw: the tool's body NEVER throws, every outcome is
    typed, and crashing the turn for the sake of validation would mean
    replacing a typed refusal with a stack trace.
    """
    default = _WRITE_TIMEOUT_MS if family == "write" else _QUERY_TIMEOUT_MS
    if isinstance(requested, bool) or not isinstance(requested, int):
        return default
    return requested if requested > 0 else default


def _diagnostics_total(diagnostics, shown: int) -> dict:
    """`{"diagnostics_total": N}` — or EMPTY, when everything fit.

    WHY. The refusal receipt carried a slice `[:8]`/`[:4]` and did NOT say
    how many diagnostics there were. The model fixes what it is shown and
    resends, not knowing about the remainder — that is, the decision is
    made over a truncated set that looks complete. This is the third
    currency of the same trick in one day: there the contract's prose was
    trimmed, there the census's category names, here — the list of what
    needs fixing.

    THE RADIUS IS MEASURED, NOT ASSUMED (`data/telemetry/kir_rejections.jsonl`,
    1 496 events, 16.07–11.08): attempts carried 1 diagnostic in 16 cases,
    and **12 diagnostics** in one more — that is, the `[:8]` threshold was
    already being exceeded in prod, and when that happened, the model saw 8
    out of 12 with not a single sign that there were more.

    EMPTY WHEN IT FIT — deliberately: a field in EVERY receipt would train
    people to ignore it, and it is paid for in tokens on every refusal.
    """
    try:
        total = len(diagnostics)
    except TypeError:                                          # noqa: PERF203
        return {}
    return {"diagnostics_total": total} if total > shown else {}


def _turn_device_id() -> Optional[str]:
    try:
        turn_context = ports.need(ports.TURN_CONTEXT)
        getter = getattr(turn_context, "get_active_device_id", None)
        if callable(getter):
            return getter()
        return turn_context._active_device_id.get()
    except Exception:  # noqa: BLE001 — fail-CLOSED for exposure
        return None


def admin_devices() -> tuple[str, ...]:
    """The list of devices this DEPLOYMENT allows (§18.5).

    The source is the env var ``KUKAI_ADMIN_DEVICES`` (comma-separated) and
    NOTHING ELSE.

    🔴 THERE HAS BEEN NO FALLBACK SINCE 15.08.2026. An unset variable used
    to mean "this machine's historical device is active," and this
    machine's id used to stand here as a literal — in a file that is
    published as a separate repository. Now an unset variable and one set
    to empty mean ONE AND THE SAME THING: an empty list, the live path
    switched off, the refusal names the variable
    (``admin_gate_message_ru``). We have no right to guess someone else's
    device.
    """
    raw = os.environ.get(_ADMIN_DEVICES_ENV)
    if raw is None:
        return ()
    return tuple(
        item.strip() for item in raw.split(",") if item.strip())


def __getattr__(name: str):
    """``serving.ADMIN_DEVICE`` — the FIRST device the deployment allows.

    The name is kept for compatibility (``kukai/llm/client.py`` logs the
    expected device when the gate is closed; the test suites also read it).
    But this is no longer A CONSTANT WITH SOMEONE ELSE'S id: the value is
    derived from the configuration at the moment of access, and when the
    list is empty, the answer is ``None``, not a made-up device. New code
    must ask ``admin_devices()`` / ``is_admin_device()``; this is an answer
    to "who would the gate let through," not a source of truth.
    """
    if name == "ADMIN_DEVICE":
        devices = admin_devices()
        return devices[0] if devices else None
    raise AttributeError(
        "module %r has no attribute %r" % (__name__, name))


def is_admin_device(device_id: Optional[str]) -> bool:
    """Whether the turn's device is on the allow-list. Doubt ⇒ no."""
    if not device_id:
        return False
    return device_id in admin_devices()


def admin_gate_message_ru(instrument: str, *, flag: str = _FLAG,
                          needs_mode: bool = True) -> str:
    """A gate refusal that NAMES what to configure (§18.5, audit B2).

    THERE ARE THREE CAUSES, AND THE REFUSAL MUST NAME THE ONE THAT REFUSED.
    Until 13.08.2026 the text was one for all three and pointed at the
    DEVICE LIST. After the gate got a third condition
    (`kir_mode_active`), a refusal over the mode arrived as "add the
    device id to KUKAI_ADMIN_DEVICES" — and anyone who read that would add
    the id, and nothing would change.

    Found by the GATE on 13.08 while triaging 110 red results: it went
    straight to checking `admin_devices()` first, because the message
    pointed there, and spent a separate pass on an innocent module. This is
    our named class in the diagnostic channel: the quantity that named the
    cause is not the one that decided.

    The order of checks here is THE SAME as in the gate, and that is not a
    coincidence: should they diverge, the message would again start naming
    the wrong thing. The condition for revisiting this: **if a condition is
    added to the gate, it must appear here too**, otherwise the diagnostic
    will silently slide back into the old defect.

    THERE ARE TWO GATES, AND THIS IS NOT ONE GATE WITH TWO NAMES. The first
    edition of this fix (13.08) hard-wired the conditions of
    `revit_ir_enabled` in here — the `KUKAI_KIR_TOOL` flag and the mode —
    while the function is shared by FIVE call sites of two different gates:
    `revit_decompile`/`revit_rebuild`/`revit_idempotence` stand behind
    `revit_decompile_enabled` (flag `KUKAI_KIR_DECOMPILE`, NO mode). The
    decompile refusal started naming the wrong flag and a condition that
    does not exist for it. **The fix committed exactly the defect it was
    fixing, one floor up: the message asserted a gate it had not asked.**
    Caught by the GATE via `test_gate_refusal_names_the_env_variable`.

    So the gate is named by the CALLER — with the same constants that guard
    it. The default (`_FLAG`, mode required) describes the `revit_ir` gate
    and is therefore safe for its call sites.
    """
    # 🔴 ДИАГНОСТИКА ЧИТАЕТ ФЛАГ ТЕМ ЖЕ СПОСОБОМ, ЧТО ГЕЙТ (13.09.2026).
    #
    # Здесь стояло `os.environ.get(flag, "off")` — НАПРЯМУЮ, мимо таблицы
    # синонимов, которой читает гейт (`env.get(_FLAG)` → `kir/env.py`:
    # `"KIR_TOOL": "KUKAI_KIR_TOOL"`). В проде выставлен `KUKAI_KIR_TOOL`,
    # поэтому текст видел `off` и ВСЕГДА уходил в ветвь флага — какое бы из
    # трёх условий ни упало.
    #
    # ЭТО СРАБОТАЛО НА ВЛАДЕЛЬЦЕ 13.09 в 19:10:52→19:13:37Z («построй
    # коробку»): модель собрала программу 7 опов, окно её показало, человек
    # нажал «Одобрить» — и перенос ответил «revit_ir недоступен: режим не
    # включён — KIR_TOOL=stage2», хотя флаг стоял, а упал РЕЖИМ. Человеку
    # велели выставить уже выставленное. Замер: `env.get("KIR_TOOL")` →
    # `stage2`, `os.environ.get("KIR_TOOL")` → `off`.
    #
    # Аудит H назвал это заранее (§1.6.2, ОТК-41/43): «если кто-то выставит
    # НОВОЕ имя без старого, гейт откроется, а прибор будет печатать off».
    # Прибор, читающий не тем именем, которым решает гейт, — это наш именной
    # дефект: величина, назвавшая причину, не та, что приняла решение.
    if env.get(flag, "off") != "stage2":
        return (f"{instrument} недоступен: режим не включён — "
                f"{flag}=stage2")
    mode = True
    if needs_mode:
        try:
            mode = ports.need(ports.TURN_CONTEXT).kir_mode_active()
        except Exception:  # noqa: BLE001 — failed to ask ⇒ treat it as "not the mode"
            mode = False
    if not mode:
        return (f"{instrument} — отдельный РЕЖИМ, а не инструмент обычного "
                f"чата: в этом ходе признак режима не выставлен. Открывается "
                f"кнопкой КИР, не переменной окружения")
    if not admin_devices():
        return (f"{instrument} недоступен: список допущенных устройств пуст — "
                f"задай {_ADMIN_DEVICES_ENV} (id устройств через запятую)")
    return (f"{instrument} недоступен на этом устройстве — добавь его id в "
            f"{_ADMIN_DEVICES_ENV}")


def _kir_hold_active() -> bool:
    """Whether the turn is pinned to the plan. Could not ask — we assume NO.

    The default is chosen in favor of the PREVIOUS behavior: an unread flag
    has no right to silently turn a working write into a sketch. The error
    in the other direction ("did not write, though asked to") is quieter
    and therefore more dangerous — it is visible only through the absence
    of elements.
    """
    try:
        return ports.need(ports.TURN_CONTEXT).kir_hold_active()
    except Exception:  # noqa: BLE001 — the flag has no right to bring down the turn
        return False


def _plan_writes(plan: Any) -> bool:
    """Whether the PLAN will WRITE. Doubt ⇒ yes, and the asymmetry is the
    whole argument.

    🔴 BOUGHT BY A LIVE TURN, 13.09.2026 21:10Z. The model first sent a
    program of four `query_types` and NOTHING ELSE — a pure reading. The
    product held it at «Одобрить» in the KIR window, because the hold asked
    only "is there a plan", never "does it write". A READING waited for a
    human's word; the model did not wait, and built by defaults blindly.
    Reading is the cheapest way for an agent to stop guessing, and holding it
    turns the cheap move into the expensive one.

    THE TWO ERRORS ARE NOT THE SAME SIZE, so the default is not symmetric:
      * holding a reading costs a DELAY — and, as measured, a blind build;
      * failing to hold a write puts an UNAPPROVED change into the document.
    Therefore an unreadable plan counts as writing.

    THE MIXED CASE DOES NOT EXIST, and this is the language's decision, not
    ours: `ProgramFamily` has exactly two members (QUERY, WRITE), and the
    compiler refuses a mix BY NAME before any of this runs — `KIR-L002`,
    «смешение query и write-опов в одной программе не поддерживается в v1…
    СЛЕДУЮЩИЙ ХОД: сними чтения из ЭТОЙ программы и спроси их ОТДЕЛЬНЫМ
    ходом». So there is no writing half to hold inside a reading program.
    """
    try:
        from kir.midend import ProgramFamily

        family = getattr(plan, "family", None)
        if family is None and isinstance(plan, dict):
            family = plan.get("family")
        if family is None:
            return True
        if family is ProgramFamily.QUERY:
            return False
        return getattr(family, "value", family) != ProgramFamily.QUERY.value
    except Exception:  # noqa: BLE001 — an unreadable plan is a writing one
        return True


def revit_ir_enabled() -> bool:
    """The gate: the stage2 flag AND an admin device AND an EXPLICIT KIR
    MODE on this turn. Any doubt — the tool does not exist.

    The third condition was added on 13.08 by the operator's decision: KIR
    is a separate mode (a button, a separate window), not an ordinary
    chat tool. An ordinary turn never sets this flag, so in ordinary work
    with Revit, KIR is unreachable BY CONSTRUCTION, not by configuration —
    bringing the flag back no longer opens it by itself.
    """
    if env.get(_FLAG, "off") != "stage2":
        return False
    try:
        if not ports.need(ports.TURN_CONTEXT).kir_mode_active():
            return False
    except Exception:  # noqa: BLE001 — could not ask ⇒ we treat it as not the mode
        return False
    return is_admin_device(_turn_device_id())


def inject_revit_ir_schema(tools: list) -> None:
    """Append the tool def (idempotent). Schema generated from the registry."""
    if any(t.get("function", {}).get("name") == "revit_ir" for t in tools):
        return
    from kir.schema_transport import program_schema_for_tool
    from kir.schema_dedup import lift_property_defs
    from kir.tool_doc import (build_tool_description_brief,
                              build_tool_description,
                                   created_schema, example_schema,
                                   rehearse_schema,
                                   program_py_schema)
    # SCHEMA DEDUPLICATION. `program_schema()` spells the selector out
    # verbatim for every selector parameter of every op, and across 41 ops
    # that is 42 390 tokens on the PROVIDER's count per turn (measured
    # 09.08 on live openrouter). Hoisting the repeats into `$defs` yields
    # 11 751 — the same operations, not one of them hidden. The form is
    # chosen by `schema_transport` based on a MEASUREMENT of the transport,
    # and it always names the reason; the generator itself stays flat (one
    # source of truth about the language, `schema_dedup` is a clean
    # post-pass over its result).
    program, schema_note = program_schema_for_tool()
    logger.debug("revit_ir tool: %s", schema_note)
    tools.append({
        "type": "function",
        "function": {
            "name": "revit_ir",
            # GENERATED — see kir/tool_doc.py. The op inventory is built
            # from spec.OPS because the hand-written string it replaces named
            # 7 of the 28 writing ops: a model reading it could not know KIR
            # authors beams, ducts, cable trays, groups, family types or
            # annotations at all. Prose has no ratchet, so the inventory must
            # not be prose. The measured authoring idioms (seven building tasks
            # given to the model) and the live-matrix traps live there too,
            # each with its provenance; test_tool_doc pins both.
            # 🔴 ЧАТ-ДВЕРИ — КРАТКАЯ СПРАВКА, А НЕ СПРАВОЧНИК (13.09.2026).
            # Слово владельца: «дипсик можем в ревите строить. значит он должен
            # это делать в КИР и делать это еще успешнее» — то есть режим КИР
            # не имеет права быть ТЯЖЕЛЕЕ обычного хода той же модели. Замер:
            # обычный ход несёт `execute_revit_code` описанием 931 знак; ход
            # КИР нёс 29 874. Живой исход этой разницы — ход `530f4ed7`:
            # 174 291 мс, 0 вызовов, модель 77 раз пересказала себе правила.
            # Полный текст не удалён и служит MCP-двери; оба порождаются из
            # одного реестра операций, так что двух источников правды нет.
            "description": build_tool_description_brief(),
            "parameters": lift_property_defs({
                "type": "object",
                # TWO INPUT FORMS, EXACTLY ONE AT A TIME.
                #
                # WHY NOT `oneOf`/`required` AT THE TOP LEVEL. "Exactly one
                # of two" is expressed in JSON Schema only by `oneOf`, and
                # that would be true — but `oneOf` AT THE ROOT of
                # `parameters` has not been carried by any tool of this
                # deployment yet, and a provider that rejects the whole
                # tool bundle breaks the TURN, not one capability. The cost
                # of the error is asymmetric: an unaccepted schema is a
                # dead turn at the admin device, a missing `required` is
                # one typed refusal that TEACHES (`_authored_input` below).
                # So the rule is named in words, and held by the runtime.
                "description": (
                    "Программа задаётся РОВНО ОДНИМ из двух полей: `program` "
                    "(операции JSON) либо `program_py` (питон, который их "
                    "порождает). Оба сразу или ни одного — типизированный "
                    "отказ."),
                "properties": {
                    "program": program,
                    "program_py": program_py_schema(),
                    # THE THIRD FIELD IS NOT A THIRD FORM OF THE PROGRAM,
                    # BUT A DIFFERENT QUESTION. `example` builds nothing: it
                    # shows a FLOOR of a real project as source, so the
                    # model does not write from a blank page. The rule
                    # "exactly one of two" above stays literally true — it
                    # is about the PROGRAM, and a sample is not a program
                    # and is given WITHOUT one (`serving._example_only`).
                    "example": example_schema(),
                    # THE FOURTH FIELD, AND AGAIN NOT A FORM OF THE PROGRAM.
                    # `rehearse` is supplied ALONGSIDE the program and
                    # writes nothing: it answers a question the author has
                    # so far had no tool to ask — "which of this will
                    # nobody check."
                    "rehearse": rehearse_schema(),
                    # THE FIFTH FIELD, a reading one: the journal of what
                    # this session created. It had been written since 17.08
                    # and read by no one until 19.08.
                    "created": created_schema(),
                },
            }, "program"),
        },
    })


# The typed open-model boundary is the single source for the 2021-2026
# read-only collector.  Keep this private compatibility alias because tests
# and operational probes historically import ``serving._SNAPSHOT_CS``.
_SNAPSHOT_CS = _OPEN_MODEL_SNAPSHOT_CS


def _snapshot_parameter_names(program: Any) -> list[str]:
    """Collect requested parameter names without trusting the raw program.

    The snapshot precedes compiler validation, so this scan is deliberately
    bounded.  The compiler still owns the real selector-shape refusal.
    """
    names: set[str] = set()
    stack = [program]
    seen = 0
    while stack and seen < 2_000 and len(names) < 20:
        value = stack.pop()
        seen += 1
        if isinstance(value, dict):
            disambiguator = value.get("disambiguate_by")
            if isinstance(disambiguator, dict):
                name = disambiguator.get("param")
                if isinstance(name, str) and 0 < len(name.strip()) <= 128:
                    names.add(name.strip())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return sorted(names)


def _snapshot_cs(program: Any) -> str:
    from kir.emit_utils import cs_string_literal

    names = _snapshot_parameter_names(program)
    if not names:
        return _SNAPSHOT_CS
    literals = ", ".join(cs_string_literal(name) for name in names)
    return _SNAPSHOT_CS.replace(
        "var __ParamNames = new string[0];",
        f"var __ParamNames = new string[] {{ {literals} }};",
        1)


#: REUSE OF THE GROUNDING SNAPSHOT — AN OPERATOR GATE, OFF BY DEFAULT.
#:
#: 🔴 WHY. The snapshot is taken AFRESH for EVERY program and is not
#: amortized. Measured 23.08.2026, migrating the K3 building into
#: «Проект1» (55 programs, 12 127 operations): 3 s -> 16 s -> 126 s -> 250 s
#: -> after that it does not come up at all, with the refusal «мост вернул
#: ошибку при получении снапшота модели». Once this took down the service
#: itself too.
#:
#: The cause is NOT the size but UNCACHEABILITY. The snapshot's text is
#: byte-for-byte THE SAME across all 55 programs (one sha256), but
#: `obfuscate_code_with_map` is NON-DETERMINISTIC — five obfuscations of one
#: text give five different results — and a different source arrives in
#: Revit every time. The plugin cannot cache the assembly, and .NET does
#: not unload dynamic assemblies from the process: 55 programs means 55
#: Roslyn compilations of 35 KB each, and all of them stay in Revit
#: forever. Hence the PROGRESSIVE degradation that size alone does not
#: explain.
#:
#: A FLAG, NOT AN `args` FIELD: this door deliberately has no switches in
#: its input (see the `handle_revit_ir` docstring), and this rule is not
#: broken here.
_GROUND_REUSE_FLAG = "KUKAI_IR_GROUND_REUSE"


def _ground_reuse_enabled() -> bool:
    return os.getenv(_GROUND_REUSE_FLAG, "").strip().lower() in (
        "1", "true", "yes", "on")


#: CAPABILITY PAIRS THAT NAME THE CREATION OF A GROUNDING-POOL TENANT.
#:
#: Derived from the registry, not written as a list of op names:
#: `capability` is the same carrier by which the registry already tells
#: creating a type apart from creating an instance. A list of names would
#: drift from the registry at the very first new op.
#:
#: 🔴 A PAIR, NOT AN OBJECT, AND THIS WAS PAID FOR BY A BUG. The first
#: edition matched ONLY the object and caught wrong cases both ways:
#:   * `create_wall` carries `('create', 'category')` — that is "creates an
#:     element OF a category," not "creates a category";
#:   * `place_family` carries `('place', 'family')` — a DIFFERENT VERB, and
#:     it places an instance, not loads a family.
#: Both would have passed as "writes the catalog," and reuse would NEVER
#: have kicked in — that is, the fix would have looked done and not worked.
#: Caught by control cases with a known answer, not by reading the code.
_CATALOG_CAPABILITIES = frozenset({
    ("create", "level"),
    ("create", "grid"),
    ("create", "type"),
    ("create", "wall_type"),
    ("create", "family"),
})


def _program_writes_catalog(program: Any) -> bool:
    """Whether the program changes the CATALOG — what the grounding snapshot is made of.

    🔴 WHY REUSE IS LEGITIMATE AT ALL. Measured 23.08: all 36 pools of
    `required_grounding_pools()` are CATALOG pools (types, type sizes,
    levels, grids, materials, sets, phases). Not one INSTANCE pool. A
    program that places walls and doors cannot change the snapshot by
    construction.

    So the question of freshness reduces to one thing: whether the program
    creates a CATALOG entity. The answer is taken from `capability`.

    `delete` lands here DELIBERATELY, even though its capability says
    `('delete', 'element')`: both a type and a level can be deleted, and
    there is nothing to tell them apart BEFORE execution. The error here
    should lean toward an extra snapshot — an extra one costs seconds, a
    missed one gives grounding against a stale catalog, that is, a
    silently-wrong outcome.
    """
    from kir import spec

    ops = program.get("ops") if isinstance(program, Mapping) else None
    if not isinstance(ops, list):
        return True                      # an unrecognized program is not cached
    for op in ops:
        name = op.get("op") if isinstance(op, Mapping) else None
        if not isinstance(name, str):
            return True
        if name == "delete":
            return True
        op_spec = spec.OPS.get(name)
        if op_spec is None:
            return True
        for pair in (op_spec.capability or ()):
            if tuple(pair) in _CATALOG_CAPABILITIES:
                return True
    return False


#: A snapshot per document. The key is the document's IDENTITY, not the
#: socket: the socket is recreated on every reconnect (measured 19.08: 2716
#: reconnects over 32 h), and a key on it would not survive a single run.
#: THE DOCUMENT-IDENTITY PROBE is the same field carried by the full
#: snapshot, and nothing more. ~1 KB against 35 KB: grounding against a
#: reused snapshot must prove EVERY TIME that it is the same window,
#: otherwise one could ground against document A and write into B — exactly
#: the failure the full snapshot already guards against
#: (`_snapshot_document_fingerprint`).
#:
#: 🔴 WHAT THIS PROBE DOES NOT PROVE IS SAID OUT LOUD: it proves it is THE
#: SAME DOCUMENT, not THE SAME CATALOG. The catalog's freshness is held by
#: invalidation on capability (`_program_writes_catalog`), and one
#: uncovered case remains — a human edits types by hand in Revit in the
#: middle of the run. It is not covered by anything cheap: the revision
#: fingerprint (`pipeline._REVISION_FINGERPRINT_CS`) hashes ALL elements,
#: and every program in the run adds walls, so it would always change and
#: zero out the reuse. So the gate is OFF by default, and any grounding
#: failure resets the cache entirely.
_GROUND_IDENTITY_CS = """
var __documentFingerprint = new Dictionary<string, object>();
try { __documentFingerprint["title"] = doc.Title ?? ""; }
catch { __documentFingerprint["title"] = ""; }
try { __documentFingerprint["path_name"] = doc.PathName ?? ""; }
catch { __documentFingerprint["path_name"] = ""; }
try
{
    __documentFingerprint["project_uid"] = doc.ProjectInformation == null
        ? "" : (doc.ProjectInformation.UniqueId ?? "");
}
catch { __documentFingerprint["project_uid"] = ""; }
__documentFingerprint["schema_version"] = "document-fingerprint/1";
return new Dictionary<string, object> {
    {"__document_fingerprint", __documentFingerprint}
};
""".strip()

_GROUND_SNAPSHOT_CACHE: dict[str, dict] = {}
_GROUND_SNAPSHOT_CACHE_MAX = 4


def _ground_cache_key(fingerprint: DocumentFingerprint) -> str:
    return "\x1f".join((
        fingerprint.title or "",
        fingerprint.path_name or "",
        fingerprint.project_uid or "",
    ))


def _ground_cache_drop(key: str | None = None) -> None:
    """Reset the snapshot. With no key — all of it: that is what every failure does.

    A grounding failure resets the cache IN FULL and does NOT try to guess
    which document is to blame. A stale snapshot must be cured by a retry,
    not by reasoning: a retry costs seconds, reasoning costs a
    silently-wrong building.
    """
    if key is None:
        _GROUND_SNAPSHOT_CACHE.clear()
    else:
        _GROUND_SNAPSHOT_CACHE.pop(key, None)


async def _reused_ground_snapshot(llm_client, bridge_callback) -> dict | None:
    """The cached snapshot for THIS document, or None.

    The document's identity is proven EVERY time by a light probe: without
    it, grounding could read document A while the transaction executes in
    B. A probe failure is not a turn failure: we return None, and the
    caller takes the full snapshot the ordinary way.
    """
    if not _GROUND_SNAPSHOT_CACHE:
        return None
    try:
        probe = await _run_declarative(
            llm_client, bridge_callback, _GROUND_IDENTITY_CS,
            "ground_identity", _SNAPSHOT_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — the probe has no right to bring down the turn
        logger.debug("ground identity probe failed", exc_info=True)
        return None
    if _extract_error(probe) is not None:
        # 🔴 TWO DIFFERENT REFUSALS, AND ONE OF THEM IS OUR OWN (29.08.2026,
        # audit finding E-11). A BRIDGE refusal is an ordinary thing, that
        # is exactly why the probe is wrapped, and swallowing it is
        # correct. But `refused_pre_effect` means that OUR OWN guard forbade
        # the send: the pair (tool, op) is not named in the host's closed
        # list of unbound dispatches (`UNBOUND_DISPATCH_OPS`). Such a
        # refusal will repeat on EVERY turn and switch off the grounding
        # cache FOREVER, while staying invisible: the value exists, the
        # output is not printed, and this kind of finding does not exist in
        # a single report — the whole named series at once.
        #
        # Here it gets A VOICE. Behavior does not change by a single byte:
        # the turn still takes the full snapshot, the probe still does not
        # bring down the turn.
        if (isinstance(probe, Mapping)
                and probe.get("execution_artifact_refused_pre_effect") is True):
            logger.error(
                "ground identity probe refused BEFORE effect: отправка "
                "('revit_ir','ground_identity') не названа в закрытом списке "
                "несвязанных отправок хозяина. Кэш заземления не сработает "
                "НИ РАЗУ, пока это не исправлено")
        return None
    payload = probe.get("result", probe) if isinstance(probe, dict) else None
    if not isinstance(payload, Mapping):
        return None
    try:
        fingerprint = _snapshot_document_fingerprint(payload)
    except (TypeError, ValueError):
        return None
    return _GROUND_SNAPSHOT_CACHE.get(_ground_cache_key(fingerprint))


def _snapshot_document_fingerprint(
    snapshot: Mapping[str, Any],
) -> DocumentFingerprint:
    """Require the identity that binds a live ground read to its write.

    Exact element identity is a stronger, separately gated preflight.  The
    active-document identity is not experimental: without it the compiler can
    ground against document A and execute the resulting transaction in
    document B.  The live collector always emits this field, so absence means
    an incomplete/legacy bridge payload and must refuse before mutation.
    """

    fingerprint = DocumentFingerprint.from_dict(
        snapshot.get("__document_fingerprint"))
    if (not fingerprint.title
            or not (fingerprint.path_name or fingerprint.project_uid)):
        raise ValueError(
            "document fingerprint must bind title and path/project uid")
    return fingerprint


def _program_writes(program: Any, *, bulk: bool = False) -> bool:
    """Classify through the compiler mid-end, not a second macro parser."""
    try:
        from kir.compiler import plan_program
        from kir.midend import ProgramFamily
        return plan_program(program, bulk=bulk).family is ProgramFamily.WRITE
    except Exception:  # noqa: BLE001
        # The real compile call below owns the typed refusal.  Returning false
        # here prevents any write attempt for an unclassifiable program.
        return False


async def _run_declarative(llm_client, bridge_callback, code: str, op: str,
                           timeout_ms: int) -> Any:
    RevitExecutionPipeline = ports.need(ports.EXECUTION).RevitExecutionPipeline
    pipe = RevitExecutionPipeline.from_llm_client(llm_client, bridge_callback)
    binding = _REGULAR_WRITE_ARTIFACT_BINDING.get()
    record = await pipe.run_declarative(
        code,
        tool="revit_ir",
        op=op,
        args={},
        timeout_ms=timeout_ms,
        execution_artifact_binding=binding,
        execution_lane=(
            REGULAR_WRITE_EXECUTION_LANE if op == "write" else None),
    )
    return record.to_tool_result()


_REGULAR_WRITE_ARTIFACT_BINDING: ContextVar[
    ExecutionArtifactBinding | None
] = ContextVar("_kir_regular_write_artifact_binding", default=None)


#: WHERE THE TURN PLACED ITS PROGRAM IN THE BUILDING JOURNAL —
#: `(session key, seq)`.
#:
#: Set at the moment of publishing, read in `_with_outcome` — the one and
#: only funnel where the TYPED outcome flows to. There is no other way: the
#: journal fills up BEFORE the call to Revit, and how it ended is known a
#: dozen and a half `return`s later. The same argument as with
#: `_building_watch`: carrying a value through every exit can be forgotten,
#: but drifting from a ContextVar cannot happen.
_TURN_JOURNAL_SLOT: ContextVar[tuple[Any, int] | None] = ContextVar(
    "_kir_turn_journal_slot", default=None)

# An internal chunk is not the outcome of the whole authored program. The
# driver folds all the chunks together and only then moves the shared
# journal once.
_JOURNAL_STAGE_DEFERRED: ContextVar[bool] = ContextVar(
    "_kir_journal_stage_deferred", default=False)
_JOURNAL_STAGE_OVERRIDE: ContextVar[str | None] = ContextVar(
    "_kir_journal_stage_override", default=None)
#: 🔴 WHY THE STAGE DID NOT MOVE — AS A FIELD, NOT AS SILENCE (03.09.2026).
#: Measured on live prod: an apartment of 23 elements was built,
#: `outcome.execution = committed`, while the building judge in the SAME
#: receipt prints «ПОСТРОЕНО В REVIT: НИ ОДНОЙ ПРОГРАММЫ. Судится ЗАМЫСЕЛ, а
#: не модель» — because `built` counts journal stages, and not one record
#: reached `committed`. There are EXACTLY FOUR reasons for not moving, and
#: from the outside all four looked the same: nothing at all. This is the
#: same law by which a silent verdict carries `verdict_silent_because`.
_JOURNAL_STAGE_NOTE: ContextVar[str | None] = ContextVar(
    "_kir_journal_stage_note", default=None)
#: THE GROUNDING SNAPSHOT OF THIS TURN — for the sake of one question: which
#: levels ARE PRESENT in the document. The self-check judges the turn's
#: program, while a live write almost always builds on a level that is
#: already there; the journal knows only the levels of THIS session, and
#: until 03.09.2026 everything older than the session was invisible to the
#: judge.
_TURN_GROUND_SNAPSHOT: ContextVar[Any] = ContextVar(
    "_kir_turn_ground_snapshot", default=None)

#: OUTCOME -> JOURNAL STAGE. A closed table, and both sides are closed:
#: `ExecutionState` is a closed Enum, `journal.STAGES` is a closed tuple. A
#: missing key means "do not move the stage," not "move it somewhere."
#:
#: `unconfirmed` -> `running_unknown`, and NOT "not built": there is no
#: evidence, the write may have gone through, and a retry is forbidden
#: (`transport.execution_unknown`). Collapsing the unknown into a negation
#: would mean lying in the direction that looks safe.
_EXECUTION_TO_STAGE = {
    "committed": "committed",
    "rolled_back": "rolled_back",
    "not_started": "refused_pre_effect",
    "unconfirmed": "running_unknown",
}


def _stage_the_journal(outcome: ProgramOutcome) -> None:
    """Tell the building journal how this turn's program ended.

    Never throws and never changes the result: outcome telemetry has no
    right to cost the build. But it cannot stay silent either — a silent
    journal turns the building's judge into a judge of what was DECLARED,
    and that is exactly the defect the stages were introduced to fix.
    """
    try:
        if _JOURNAL_STAGE_DEFERRED.get():
            _JOURNAL_STAGE_NOTE.set("отложено: стадию ставит внешний вызов чанков")
            return
        slot = _TURN_JOURNAL_SLOT.get()
        if slot is None:
            _JOURNAL_STAGE_NOTE.set(
                "слота нет: замысел не публиковался в живой журнал этого хода "
                "(читающий ход, удержание, либо публикация не состоялась)")
            return
        исход = str(getattr(outcome.execution, "value", outcome.execution) or "")
        stage = _JOURNAL_STAGE_OVERRIDE.get() or _EXECUTION_TO_STAGE.get(исход)
        if stage is None:
            _JOURNAL_STAGE_NOTE.set(
                f"исход «{исход}» стадии не назначает — таблица закрыта нарочно")
            return
        from kir.live import journal as _live_journal
        двинулось = _live_journal.advance(slot[0], slot[1], stage)
        _JOURNAL_STAGE_NOTE.set(
            f"стадия: {stage}" if двинулось else
            f"стадия «{stage}» ОТВЕРГНУТА журналом: запись вытеснена либо "
            f"переход запрещён законом монотонности")
    except Exception as exc:  # noqa: BLE001 — the journal is younger than the build
        _JOURNAL_STAGE_NOTE.set(f"стадия не поставлена: {type(exc).__name__}")
        logger.debug("journal stage advance failed", exc_info=True)



def _bind_turn_operation_id(
    binding: ExecutionArtifactBinding,
    wrapped_source: str,
) -> str | None:
    """Link the operation id and mark the dispatch before sending the write.

    The building's live journal is an observer and stays fail-open for the
    build path. So a missing or wrong link cannot invent a failure or a
    success; it only means that a future late receipt will not lift this
    record's uncertainty, and it must remain ``running_unknown``. When a
    durable store is available, both lines are written before the Bridge;
    a failure of the store itself does not block Revit and is therefore not
    passed off here as durability.
    """

    try:
        slot = _TURN_JOURNAL_SLOT.get()
        if slot is None:
            return None
        identity = execution_operation_identity(binding, wrapped_source)
        from kir.live import journal as _live_journal
        if not _live_journal.bind_operation_id(
                slot[0], slot[1], identity.operation_id):
            logger.debug(
                "journal operation identity was not bound: %s",
                identity.operation_id,
            )
            return None
        # The link is set immediately before the one and only dispatch. If
        # the process dies inside the Bridge and both lines reached an
        # enabled store, restore will bring up `running_unknown`, not
        # `planned`; otherwise the whole write, or its chunk, would look as
        # if it had not started yet and could be resent.
        _live_journal.advance(slot[0], slot[1], "dispatched")
        return identity.operation_id
    except Exception:  # noqa: BLE001 — journal remains an observer
        logger.debug("journal operation identity bind failed", exc_info=True)
        return None


# ── v1.1: runtime-outcome translation (SACTOR, SPEC 12.7) ────────────────────
# The slab saga (FULL_BUILDING_TEST.md, находка №1): a Revit runtime refusal
# came back as {"ok": true, "result": {"error": true}} — the outer ok lied.
# Contract now: EXACTLY one typed outcome. Any error signal in the exec
# result -> ok:false + KIR-X* diagnostic bound to op_id where known; the raw
# Revit message survives only inside `detail`, never as the only signal.

#: Codes whose ROLLBACK IS PROVEN by the shape of the refusal, not by assumption.
#:
#: They used to stand as a literal tuple inside `_handle_revit_ir_inner`,
#: and splitting X003 into two codes (drift / runtime refusal) would have
#: passed it by silently: X009 would have fallen out of "rolled back" and
#: become `unconfirmed`, meaning the code split would have WEAKENED the
#: knowledge of the effect. Both codes come from `refuse_stmt`, and by
#: contract it renders RollBack+return (atomic) or throw (per_op) BEFORE
#: the commit — meaning they prove a rollback equally. The constant stands
#: here so that this argument can be checked by a test, not by rereading.
_ROLLBACK_PROVEN_CODES = ("KIR-X003", "KIR-X004", "KIR-X009")

_X_PATTERNS = (
    ("KIR-X001", ("curve length is too small", "shortcurvetolerance")),
    ("KIR-X002", ("loops intersect", "curve loops")),
    ("KIR-X006", ("already in use", "уже используется")),
    ("KIR-X005", ("transaction", "транзакци")),
)


#: THE `detail` CEILING ON A RUNTIME REFUSAL.
#:
#: 🔴 WHAT IT COST (26.08.2026, a live run). This used to say `[:300]` with
#: not a single sign of truncation. On that same day the grid-collision
#: refusal learned to name the axis and list the OCCUPIED coordinates along
#: with the distance («расстояние 0 мм и есть причина») — and EXACTLY 300
#: characters reached the reader, cut off in the middle of the second id:
#: neither the line with zero distance, nor the next move. The fix looked
#: done, the gate was green, the golden was updated — and the benefit never
#: arrived.
#:
#: 🔴 THE CEILING STOOD ONLY ON THE RUNTIME PATH, AND THAT IS AN OVERSIGHT,
#: NOT A POLICY. Measured over 35 live `detail`s from this shift:
#: COMPILATION refusals travel a different road and know no ceiling at
#: all — the longest one ran **389 characters**
#: (`levels: 26 вариантов … ПОКАЗАНЫ 12 ИЗ 26 …`, the `_candidates_note`
#: idiom) and is considered normal in this tree. Exactly 300 out of the 35
#: measurements showed TWO cases, and both were grid collisions. That is,
#: 300 was not protecting against overspend: the neighboring path already
#: carries more. It was tearing apart the one path that has no limit.
#:
#: THE NUMBER IS DERIVED FROM THE STRUCTURE OF THE AUTHORED TEXT, NOT FROM A
#: HISTOGRAM, and there is NOWHERE to get a histogram here: the witness
#: corpus does not store `detail` at all (see the argument at
#: `_X_PATTERNS` below — "38 live X003 lines were left without a cause
#: forever"). Worst-case arithmetic for our longest refusal, the grid one:
#:
#:     the constant part (the requested direction and point · axis parsing
#:     · line count · the next move · the note about the unshown)     552
#:     one listing line, the vertical axis (wider than the horizontal)  77
#:     showing the nearest ones                                          6
#:     ------------------------------------------------------------------
#:     552 + 6*77 + 5*2 (separators)                                = 1024
#:
#: A ceiling of 1200 leaves ~180 characters of margin for the prefix's
#: spread. The listing is limited in C# (`_GRID_OCC_HELPER_CS`), and this is
#: THE SECOND HALF of the same fix: raising the ceiling without limiting the
#: listing would mean trading a silent truncation for a loud overspend —
#: this tree already fixed a refusal today that was carrying 18 KB to no
#: purpose (`6d09726b`).
#:
#: THE CEILING STAYS, AND THIS IS NOT CAUTION. A Revit exception message is
#: SOMEONE ELSE'S text, bounded by nothing; without the ceiling, the very
#: first long trace would carry the whole model off with it.
_RUNTIME_DETAIL_CAP = 1200


def _cut_and_say(text: str, cap: int) -> str:
    """Truncate to ``cap``, NAMING the remainder. There is no silent truncation here.

    🔴 ONE ALGORITHM CARRIER FOR TWO DIFFERENT CEILINGS. This idiom already
    lived in this file — inside :func:`witness_note` — and the runtime
    refusal simply was not given it. A copy would have been a named defect
    of this tree, so there is one algorithm here and two ceilings, and they
    are about DIFFERENT things:

    * :data:`_RUNTIME_DETAIL_CAP` (1200) — the `detail` of a runtime
      refusal, where part of the text is SOMEONE ELSE'S (a Revit exception
      message) and is bounded by nothing;
    * :data:`_NOTE_CAP` (300) — a witness's axis listing line, entirely
      OURS and bounded by construction, and additionally cut further
      downstream by someone else's literal 120 (`chat_helpers.py`).

    The previous values matching (both were 300) was exactly a
    coincidence; they must not be folded into one ceiling.
    """
    if len(text) <= cap:
        return text
    mark = "…[+%d знаков]"
    keep = cap - len(mark % len(text))
    return text[:keep] + mark % (len(text) - keep)


def _translate_runtime(err: dict) -> dict:
    layer = err["layer"]
    # 🔴 ONE KNIFE FOR BOTH CARRIERS, VERIFIED. `detail` travels to the
    # reader twice — `kir.diagnostics[i].detail` and `kir.err.detail` — but
    # the second is not independent: `_stamp_refusal` takes it from the
    # LEAD diagnostic (`lead.get("detail")`), that is, from this same
    # string. Truncating here fixes both; there is NO second place to cut,
    # and one must not be introduced.
    raw = _cut_and_say(
        str(layer.get("message") or layer.get("message_ru") or err["error"]),
        _RUNTIME_DETAIL_CAP)
    op_id = layer.get("op_id")
    marker = str(err["error"]).lower()
    if marker == "postconditions_violated":
        code, msg = "KIR-X004", "постусловия нарушены — транзакция откатена, модель не изменена"
    elif marker == "stale_or_failed":
        # `__Refuse` marks EVERY typed refusal from the emitter with ONE
        # marker, not only a failed null-guard on a grounded-id. Asserting
        # «элемент исчез» over "NewFamilyInstance вернул null" or
        # "NewElbowFitting: failed to insert elbow" is a lie: nothing had
        # disappeared, and the user was sent off chasing model drift (both
        # lines caught live on 27.07). The real case is recognized by the
        # signature that the null-guards themselves write.
        #
        # 09.08.2026: the signature now selects the CODE, not just the
        # text. While both worlds traveled under X003, the ONLY thing that
        # told them apart was `detail`, and `detail` was not written into
        # the witness corpus — and 38 live X003 lines were left without a
        # cause forever. One code for two worlds is a taxonomy defect, and
        # fixing the text does not cure it: a reader of the corpus sees the
        # code, not the prose.
        drift = "после grounding" in raw
        code = "KIR-X003" if drift else "KIR-X009"
        msg = ("элемент/тип исчез между grounding и исполнением — откат"
               if drift else
               "оп отказан в рантайме Revit — причина в detail; транзакция откатена")
    elif marker == "timeout_unconfirmed" or _is_unconfirmed_outcome(layer):
        # 🔴 A SECOND CARRIER OF THE SAME DEFECT, FOUND IN THE SAME FILE ON
        # 24.08.2026. This used to say only `marker == "timeout_unconfirmed"`,
        # while `marker = str(err["error"]).lower()`, and on the bridge's
        # live envelope that is `'true'`. Meaning the branch was NEVER
        # taken, and a timeout rode off into the `else`:
        #
        #   execution_unknown -> KIR-X999 «рантайм-отказ Revit (неклассифицирован)»
        #   bridge_timeout    -> KIR-X999   the same
        #
        # Models were told that REVIT REFUSED, when Revit was not
        # responding at all, and were not told the one move that saves
        # them — «проверь модель query-запросом». It was written right
        # here and reachable only through a shape the bridge does not
        # produce.
        #
        # Heavier than its neighboring carrier (`decided_refusal`) by the
        # MISSION METRIC: there, a journal record was corrupted; here, the
        # model learns the wrong thing within the turn.
        code, msg = "KIR-X007", "исполнение не подтверждено за таймаут — проверь модель query-запросом"
    else:
        low = raw.lower()
        code = next((c for c, pats in _X_PATTERNS
                     if any(p in low for p in pats)), "KIR-X999")
        msg = {
            "KIR-X001": "нулевое/слишком короткое ребро контура в рантайме Revit",
            "KIR-X002": "контуры пересекаются/касаются в рантайме Revit",
            "KIR-X006": "имя уже занято в документе",
            "KIR-X005": "сбой транзакции Revit",
        }.get(code, "рантайм-отказ Revit (неклассифицирован)")
    d = {"code": code, "message_ru": msg, "detail": raw}
    if op_id:
        d["op_id"] = op_id
    if code == "KIR-X004" and isinstance(layer.get("violations"), list):
        d["violations"] = layer["violations"][:10]
        # 🔴 THE MEASURED VALUE IS LIFTED INTO THE MESSAGE, NOT LEFT SITTING
        # IN A LIST INSIDE A LIST (25.08.2026, found by a live run of 80
        # fences).
        #
        # A postcondition violation is named here TEXTBOOK-STYLE — axis,
        # measured value, authored value, tolerance, and op_id:
        #   q16: bbox extents mismatch (geometry): [… | 719175,0 719250,0]
        #        против авторских [… | 719200.0 719200.0] при допуске 50.0 мм
        # And the model was getting exactly «постусловия нарушены —
        # транзакция откатена». The value was computed, recorded, and never
        # arrived.
        #
        # Why the list does not save it: it sits in
        # `diagnostics[i].violations`, that is, A LIST INSIDE A LIST, and
        # the history collapser replaces every list with "collapsed" (canon
        # form 27). NOTHING reaches the model's next turn — and the turn
        # burns out, because there is nothing to fix.
        #
        # The same class was already fixed today on the `handoff` branch of
        # the same file: the cause exists, is computed, and is erased by
        # generic text at the last step. The second carrier of the same
        # defect is here; caught exactly because the search was done IN THE
        # SAME FILE right after the first fix.
        первое = str(d["violations"][0]).strip() if d["violations"] else ""
        if первое:
            ещё = len(d["violations"]) - 1
            хвост = (" (и ещё %d нарушени%s — см. violations)"
                     % (ещё, "е" if ещё == 1 else "й")) if ещё > 0 else ""
            d["message_ru"] = "%s: %s%s" % (msg, первое, хвост)
    return d


def revit_warnings_of(payload: Any) -> list[dict]:
    """What Revit SAID while the program was heading toward a green commit.

    🔴 WHY THIS FIELD EXISTS. Until 20.08.2026 the refusal preprocessor (all
    FOUR of its copies) dropped Revit's warning BEFORE it reached the
    receipt: `continue` stood before `Seen.Add`. Dropping it is correct and
    stays that way — there is nobody to click the modal dialog, and Revit
    parks on the UI thread. What was wrong was FORGETTING: Revit says
    «твой замок я выбросил» (`DimensionUnlocked`, `UndeletedConstraints`),
    the program commits GREEN, and the building does not carry the declared
    relationship. A silently-wrong outcome is exactly what the cardinal
    invariant forbids.

    A MISSING KEY AND AN EMPTY LIST ARE ONE AND THE SAME FACT, and this is
    justified, not merely convenient: emission asks Revit ALWAYS and sets
    the key ONLY when there were warnings. So "no key" here is an honest
    zero, not "we did not ask" (form 4 does not apply, by the construction
    of emission).
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("revit_warnings")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _axis_marked(item: str, axis: str) -> bool:
    """Whether a violation line carries this axis's tag.

    🔴 THE TAG IS `(axis)` OR `(axis, refinement)`, AND THE SECOND FORM WAS
    PAID FOR BY A MEASUREMENT ON 22.08.2026. The previous edition searched
    for the EXACT substring `(geometry)`, while `authoring.py` has five
    messages living with a refinement inside the same parentheses: four
    `(geometry, tolerance 0.1deg)` and one `(geometry, Revit подгоняет под
    контент)`. None of them matched, and the violation rode off into
    SEMANTICS — that is, an arc wall with the wrong center and a family
    rotated the wrong way reported `geometry_ok: True`, while the wrong
    axis turned red.

    The cost in numbers, from the MNVNK breakdown: `create_wall` (arc) +
    `place_family` (rotation) + `create_column` (rotation) — **13 187
    operations out of 19 041, 69%** of the real building.

    A PREFIX match here would have been broader than the truth:
    `(geometryX)` is not a tag. So after the axis name there must be either
    `)` or `,` — a census of all of `authoring.py`'s parenthesized forms (9
    kinds) satisfies this rule completely.
    """
    return f"({axis})" in item or f"({axis}," in item


def _axes_from_violations(violations: Sequence[str]) -> dict:
    """Break down postcondition violations along THREE AXES (SPEC §11.4).

    The marker lives IN THE VIOLATION LINE ITSELF — `(geometry)` or `(topology)`,
    and anything marked as neither is semantic. The rule was written out
    VERBATIM twice (`_witness_for_success` and `_derive_witness`); two copies
    of one rule can drift apart silently and neither fails on its own, so there is one copy.
    What counts as a marker is also one place, `_axis_marked`.

    `False` means "this axis is violated", `True` means "it is not among the violations".
    Whether the axis was CHECKED AT ALL is not asserted by this function: that is judged
    separately by `_unwitnessed_axes`, and conflating these two questions is the whole point of the finding.
    """
    return {
        "geometry_ok": not any(
            _axis_marked(item, "geometry") for item in violations),
        "topology_ok": not any(
            _axis_marked(item, "topology") for item in violations),
        "semantic_ok": not any(
            not _axis_marked(item, "geometry")
            and not _axis_marked(item, "topology")
            for item in violations),
    }


def _unwitnessed_axes(op_names: Sequence[str]):
    """Axes whose green NOBODY PROMISED TO CHECK.

    The triple of axes is entirely green on success, and it has one justification:
    the intra-transaction gate proved ALL postconditions before Commit. The argument is valid
    only to the extent that postconditions for the axis are DECLARED AT ALL, and about this
    it says nothing. A measurement against `translation_cert.REFINEMENT` (the table
    is complete — all 64 writing ops): 11 ops have no geometry obligations, 15 have none
    for topology, 25 have none for semantics. For them `geometry_ok=True` is a form, not
    a measurement, and the consumer had no way to tell one from the other.

    THE ANSWER IS A TRI-STATE, by the same law as `hulls_coincide` and `Judged.proven`:
    `{}` — every op in the program declared obligations on all three axes;
    a non-empty dict — axis -> the OPS that declared nothing for it;
    `None` — there is nothing to judge by (empty program, an op outside the table, the table
    failed to load). `None` is NOT "everything is fine".

    THE AXIS NAMES THE CULPRIT, AND THIS IS A FIX FROM THE SELF-REVIEW OF 10.08. Originally
    a LIST of axes was returned here, and on a mixed program it lied badly:
    `create_wall` (declares all three) together with `set_param` (declares none
    at all) produced `["geometry","semantic","topology"]` — exactly the same as what
    a SINGLE `set_param` produces. The reader could not tell "nothing was checked" from "one
    of the two operations promised nothing", though they need different fixes. A signal
    that fails to distinguish these two cases is the same defect against which
    the field itself was set up. Op names are truncated at ten, like `violations`.

    THE FIELD IS ADDITIVE, THE THREE BOOLEANS ARE UNTOUCHED. Redefining them would mean
    changing the meaning under a consumer already written against them and turning today's
    green into red; the consumer is free not to read the new field, but if it does read it —
    it will see the truth. This function produces no refusals at all.

    WHAT IS NOT DECIDED HERE AND IS NOT DECIDED HERE. Obligations come in six kinds, while
    there are three axes. `geometry`/`topology`/`semantic` map one to one, while
    `materialize` (present on all 64) is about the element having come into existence at all, and it
    is not covered by any of the three axes. Two are disputed: `parameter` (9 of them, "param
    == value after commit") and `identity` (4 of them, "Name == name"); both
    resemble semantics but are named differently. Whether to count them as semantics is a question
    for the owner of the table, not for this file, so a STRICT reading is adopted here:
    an axis is counted as declared only if the obligation is named
    by its own name. The strict reading errs on the side of "saying that
    it wasn't measured", rather than the other way around, and it refuses no record. Loosening
    it is one line, but not silently: then `set_param`, `create_pipe`,
    `create_duct`, `create_cable_tray`, `create_type`, `create_grid`,
    `create_level`, `create_room`, and `create_room_separator` will stop
    showing semantics as undeclared.
    """
    if not op_names:
        return None
    try:
        from kir.translation_cert import _ensure_table
        table = _ensure_table()
    except Exception:  # noqa: BLE001 — the table belongs to someone else; its silence is not our green
        return None
    missing: dict[str, list[str]] = {}
    for name in op_names:
        refinement = table.get(name)
        if refinement is None:
            # An op outside the obligations table — there is nothing to say about its axes, and
            # it cannot be presented as "all declared".
            return None
        declared = {obligation.kind for obligation in refinement.obligations}
        for axis in ({"geometry", "topology", "semantic"} - declared):
            names = missing.setdefault(axis, [])
            if name not in names:
                names.append(name)
    return {axis: sorted(names)[:10]
            for axis, names in sorted(missing.items())}


def _witness_for_success(family: str, payload: Any,
                         op_names: Sequence[str] = ()) -> dict:
    """Witness for a committed program — accounting for violations.

    Transaction success (``ok=True``) is a fact: the write took place.  But if
    postconditions are violated and merely "reported", the triple of axes must
    show it, otherwise the consumer will read the result as clean.

    ``unwitnessed_axes`` answers the SECOND question that the triple did not know:
    not "is the axis violated" but "did it even undertake to check". See
    `_unwitnessed_axes`.

    🔴 WHAT IS NOT READ HERE, AND THIS IS NAMED, NOT IMPLIED (C-1,
    06.09.2026). ``postcondition_violations`` is a list of violations by elements that SURVIVED
    the commit; lines from a REFUSED op do not go into it. A refusal
    of one operation in ``per_op`` mode lives ONLY in its own row
    ``__results[oid] = {"refused": …}``, and this function does not see it at all:
    the refusal reaches the outcome EARLIER and through a different channel — via
    ``bridge_result``, where a program without a typed identity for one of
    the keys becomes ``committed`` + ``INCOMPLETE``. That is, an ordinary
    refused row yields committed/incomplete, and NOT ``VIOLATED``; VIOLATED
    remains an assertion about COMMITTED geometry. Before fix C-1 the gate
    at the operation stage left the message of a rolled-back op in the shared ``__post``,
    and this same path declared the entire correct program VIOLATED.
    """
    if family == "query":
        return {"read_only": True}
    vio = _postcondition_violations(payload)
    unwitnessed = _unwitnessed_axes(op_names)
    # A NAMED ABSENCE IS A SEPARATE FIELD, NOT PART OF `unwitnessed_axes`, and
    # this is a measurement, not a matter of taste. The axis instrument judges by AXIS ("did the op declare even
    # one obligation of this kind"), while a named absence lives at the CLAUSE level.
    # An op with a bounding-box obligation and a named unwitnessable SHAPE within
    # the same axis is indistinguishable to the axis instrument from one fully checked: a measurement
    # from 20.08.2026 — `create_site_subregion` gives `unwitnessed_axes = {}` while
    # the shape's absence is declared, and there are EIGHT such ops out of sixteen. Merging
    # the two fields would mean setting up one code for two outcomes — exactly what
    # both were set up against.
    #
    # 🔴 AND WHY AT ALL: before this fix `_NON_WITNESSABLE_CLAUSES` had ZERO
    # live readers — the only consumer was the static
    # `audit_registry_coverage`. Honesty existed and never reached the one
    # it was set up for; our named class "a produced fact with no reader",
    # applied to the honesty mechanism itself.
    from kir.translation_cert import named_absences as _named_absences
    absences = _named_absences(op_names)
    # THE WORD REVIT IS PART OF THE WITNESS, NOT A REMARK. The three axes answer
    # "did what was built match what was declared"; the warning answers
    # a different question — "did Revit undo something declared, along the way".
    # A green triple with a discarded lock is honest on every axis and lies
    # as a whole, so the field lives NEXT TO the triple, not inside it.
    warned = revit_warnings_of(payload)
    if not vio:
        witness = {"geometry_ok": True, "semantic_ok": True,
                   "topology_ok": True,
                   "unwitnessed_axes": unwitnessed,
                   "named_absences": absences}
    else:
        witness = {
            **_axes_from_violations(vio),
            "committed": True,
            "violations": vio[:10],
            "unwitnessed_axes": unwitnessed,
            "named_absences": absences,
        }
    if warned:
        witness["revit_warnings"] = warned
    return witness


def _derive_witness(ok: bool, family: str, diag: Optional[dict]) -> dict:
    """SPEC §11.4 triple, now in EVERY tool result (находка №3). On success
    the in-txn gate proved all postconditions before Commit; on X004 the
    violation strings carry their axis markers."""
    if family == "query":
        return {"read_only": True}
    if ok:
        return {"geometry_ok": True, "semantic_ok": True, "topology_ok": True}
    w = {"geometry_ok": True, "semantic_ok": True, "topology_ok": True,
         "committed": False}
    if diag and diag.get("code") == "KIR-X004":
        # The same axis breakdown as on success — by ONE function.
        w.update(_axes_from_violations(diag.get("violations", [])))
    else:
        w["geometry_ok"] = w["semantic_ok"] = w["topology_ok"] = None
    return w


def green_is_earned(
    *,
    violations,
    family: str,
    has_acceptance_session: bool,
    acceptance: AcceptanceState,
    journal_error: Optional[str],
) -> bool:
    """THE CARDINAL INVARIANT AS ONE FUNCTION: when ``ok`` is allowed to be True.

    🔴 WHY THIS IS A SEPARATE FUNCTION AND NOT AN EXPRESSION IN THE BODY (15.08.2026).
    Before that day the condition lived as a conjunction inside ``_handle_revit_ir_inner`` —
    1125 lines — and was held together by a BUNDLE OF LOCAL VARIABLES. That day's measurement:
    ``acceptance_session`` occurs in the module 37 times and **NOT ONCE in the entire
    test tree**. That is, the product's main promise — "zero
    silently-wrong outcomes" — was checked by nothing, and any cut of this
    function was unverifiable IN PRINCIPLE.

    **A condition that has no name cannot be pinned down.** So the name
    was set up before the cut: behavior did not change by a single bit (a pure
    extraction), but the invariant gained an address to which a
    FAIL control can be attached.

    What is asserted here, along the axes of ``ProgramOutcome``:

    * **any postcondition violation closes off green** — for reads too;
    * **a read** is green on its own: it has its own contract, there is no acceptance;
    * **a write** is green ONLY when all three conditions have been met — an acceptance session
      existed, independent acceptance said ACCEPTED, and the terminal
      record landed on disk (``journal_error is None``).

    The third condition is not decorative: acceptance measured in memory is not
    irrefutable evidence. Green whose terminal record has not been fsynced
    does not go out to the world.

    **FAIL-CLOSED BY CONSTRUCTION.** A future write path that forgets to prepare
    a session will not become successful merely because ``has_acceptance_session`` remained
    false: a falsehood here closes off green rather than letting it through.
    """
    if violations:
        return False
    if family == "query":
        return True
    return (
        has_acceptance_session
        and acceptance is AcceptanceState.ACCEPTED
        and journal_error is None
    )


def _with_outcome(result: dict, outcome: ProgramOutcome) -> dict:
    """Attach the closed outcome without flattening its independent axes.

    AND THE SAME OUTCOME GOES INTO THE BUILDING JOURNAL. The place was not chosen for convenience: this is
    the ONLY funnel through which every typed outcome of this module passes.
    A second point of writing the stage would mean two values
    that must coincide, with nothing to enforce that — the named defect of this
    project in its pure form.
    """

    result["outcome"] = outcome.to_dict()
    _JOURNAL_STAGE_NOTE.set(None)
    # 🔴 A HOLD IS NOT A REFUSAL, AND ITS STAGE IS ALREADY CORRECT (24.08.2026,
    # an audit finding, reproduced from the code).
    #
    # The product mode "build in KIR, not in Revit" returns
    # `program_not_started()` — honestly: there was no execution. But the stage map
    # translates `not_started` into `refused_pre_effect`, and that is a SIDE AND
    # TERMINAL stage ("from a side stage — NOWHERE"). An intent published
    # to the journal as `planned` and WAITING for the "move to Revit" button, immediately
    # disappeared from `standing()` and could NEVER be moved — that is, pressing
    # the button had no chance of being reflected in the journal. The pack judge, in the same turn,
    # printed `dropped_from_pack: 1` with the caption "refused before write or rolled back"
    # about a program that nobody had refused.
    #
    # The correct stage of a hold is `planned`, and it has ALREADY been set since publication.
    # So the fix here is not "set a different one" but DO NOT TOUCH: the single funnel
    # remains single, and the exception is named by ONE feature of the result.
    if not result.get("held_in_kir"):
        # The first committed part forbids retrying the whole program, but does not
        # make unexecuted chunks built. A separate terminal/non-built
        # stage preserves both facts instead of a false shared ``committed``.
        partial = (
            result.get("stage") == "chunked"
            and result.get("ok") is not True
            and outcome.execution is ExecutionState.COMMITTED
        )
        override_token = _JOURNAL_STAGE_OVERRIDE.set(
            "committed_partial" if partial else None)
        try:
            _stage_the_journal(outcome)
        finally:
            _JOURNAL_STAGE_OVERRIDE.reset(override_token)
    #: The reason travels IN THE RECEIPT, not into the debug log: `built: 0` from the
    #: building judge reads as "nothing was built", and there was no way from outside to tell it apart from "the journal
    #: was not told".
    заметка = _JOURNAL_STAGE_NOTE.get()
    if заметка:
        result["journal_stage"] = заметка
    #: 🔴 A FOREIGN JOURNAL WITH THE SAME NAME — INTO THE RECEIPT, NOT INTO THE DEBUG LOG
    #: (08.09.2026). Before the fix, 194 foreign programs were silently loaded at this
    #: same spot; now they are NOT loaded, and a person must learn why —
    #: otherwise "the building is empty" becomes indistinguishable from "the journal wasn't loaded".
    подъём = _journal_restore_diagnosis()
    if подъём:
        result["journal_restore"] = подъём
    return result


def _typed_error(stage: str, message: str, *,
                 outcome: ProgramOutcome | None = None) -> dict:
    result = {"ok": False, "error": stage, "message_ru": message,
              "handoff": "recipe-path"}
    _with_outcome(result, outcome or program_not_started())
    return _stamp_refusal(result)


# ── a refusal must CARRY its reason machine-readably ─────────────────────────────────
# A live measurement of the tower (29.07) on the KIR side: `err_code: null`. We had the reason
# and it reached the MODEL (KIR-* diagnostics sit in the envelope verbatim), but not the
# SYSTEM: the `err` block — the only contract for "what happened"
# (kukai/llm/envelope.py) — was NEVER set on the KIR path. So the evaluator
# (will/evaluator.py:144), the receipt (bridge_protocol.py:1138), and the
# turn-error detector (client.py:1569) read emptiness, and a failed write
# collapsed into the turn as a success.
#
# We set it ONCE at the exit point (see `handle_revit_ir`), not at every
# `return`: the rule is structural, so a new refusal path gets `err`
# for free and cannot "forget" it.

# ═════════════════════════════════════════════════════════════════════════
# 🔴 THE OUTCOME IS READ FROM THE REGISTRAR. THE SIX TABLES ARE GONE FROM HERE (02.09.2026)
#
# WHAT STOOD HERE. Six handwritten dictionaries `_KIR_{X,W,A,K,R,B}_TO_ERRCODE` plus
# six defaults BY THE CODE'S LETTER. The outcome lived TWICE: as the `taxonomy` column at the
# registrar (`kir/diag.py`) and as a decision here. Two values that must
# coincide — the named defect of this tree; they only stayed in sync because the
# guard `test_one_registrar_of_refusal_codes` checked them by CALLING both.
#
# WHAT THIS BOUGHT. A run on 02.09.2026 over 106 registered codes: **8 codes**
# (`B011 E002 E005 G107 G111 G116 L007 P000`) had a fix that was NOT ON THE AUTHOR (blame
# `ours`/`environment`), yet received `KIR_PROGRAM_REFUSED` here — "fix
# your program". The worst — `KIR-P000`, a compiler panic: the author of a CORRECT program
# was ordered to rewrite it because of our own failure, and with `retryable=True` at that, that is,
# an invitation to send the same program and get the same panic. Not one of the
# eight was a typo: the code's letter knows nothing about blame, and the default by
# letter could not have answered otherwise.
#
# WHAT THE PLAN PROMISED AND WHAT WAS DISPROVEN. The stage 3.1 plan said "derive
# `ErrCode` FROM BLAME". A function of blame DOES NOT EXIST, and this is a measurement, not an opinion:
# blame `environment` has five different outcomes, `ours` has five, `author` has two; the pair
# (blame, registrar) leaves 4 ambiguous combinations out of 37, covering
# 19 codes. Blame answers "WHO fixes it", the taxonomy answers "WHAT happened to the world", and
# `KIR-X003` versus `KIR-X007` (both `environment`) is "retry" versus
# "retrying is FORBIDDEN, the write may have landed".
#
# WHAT WAS DONE INSTEAD. There is ONE carrier: the outcome sits at the registrar, the consumer
# READS it (`diag.taxonomy_of`). Blame, meanwhile, FORBIDS one outcome —
# `diag.register()` refuses at import time a row where the fix is not on the author, yet
# the outcome says "fix the program". The debt is closed BY CONSTRUCTION, not by a list.
#
# WHAT REMAINS A TABLE AND WHY THIS IS NOT A REGRESSION. `_UNREGISTERED_LETTER_FALLBACK`
# below speaks ONLY about codes that the registrar DOES NOT HAVE (a foreign bridge version,
# a code from the future). It never makes a claim about a registered code, and this
# is pinned by a test. `_FLAT_ERROR_TO_ERRCODE` is a different matter: it translates
# a FLAT `error` string, not a `KIR-*` code.
# ═════════════════════════════════════════════════════════════════════════

#: Default for a code that the REGISTRAR DOES NOT HAVE. The values are exactly the ones that
#: served as defaults in the six removed tables, so an unknown code reads as
#: it did before. A letter that is not present here falls through below — to the flat `error` string and
#: to a generic "program refused", just as before the fix.
_UNREGISTERED_LETTER_FALLBACK = {
    # runtime: the bridge executed the program and refused
    "KIR-X": ErrCode.KIR_RUNTIME_REFUSED,
    # a witness can follow a confirmed commit; the safety
    # of a retry is carried by `outcome`, not this code
    "KIR-W": ErrCode.KIR_RUNTIME_REFUSED,
    "KIR-A": ErrCode.KIR_RUNTIME_REFUSED,
    # an unknown K-code is more likely a new form of binding than a new breakage of ours
    "KIR-K": ErrCode.KIR_PROGRAM_REFUSED,
    # translation certificate: there is no effect, by construction
    "KIR-R": ErrCode.KIR_PRECONDITION_UNMET,
    # an unknown B-code is more likely a new author error than a new breakage of ours, and
    # erring this way is cheaper: the model gets the next turn
    "KIR-B": ErrCode.KIR_PROGRAM_REFUSED,
}


# The flat form `{"ok": false, "error": "<string>"}` is how
# `_typed_error` and `rebuild_runner` refuse. The string already NAMES the reason; the table only
# tells the reader what to do with it.
_FLAT_ERROR_TO_ERRCODE = {
    # execution is not confirmed — retrying the write blindly is dangerous
    "revision_unconfirmed": ErrCode.KIR_UNCONFIRMED,
    "sweep_unconfirmed": ErrCode.KIR_UNCONFIRMED,
    "timeout_unconfirmed": ErrCode.KIR_UNCONFIRMED,
    # the world is not in the state the program assumed
    "gate": ErrCode.KIR_PRECONDITION_UNMET,
    "ground": ErrCode.KIR_PRECONDITION_UNMET,
    "open_model_preflight": ErrCode.KIR_PRECONDITION_UNMET,
    "no_run": ErrCode.KIR_PRECONDITION_UNMET,
    "run_in_progress": ErrCode.KIR_PRECONDITION_UNMET,
    "materializer_pending": ErrCode.KIR_PRECONDITION_UNMET,
    "idempotence_pending": ErrCode.KIR_PRECONDITION_UNMET,
    "no_decompile": ErrCode.KIR_PRECONDITION_UNMET,
    "no_metadata": ErrCode.KIR_PRECONDITION_UNMET,
    "partial_read": ErrCode.KIR_PRECONDITION_UNMET,
    "snapshot_non_authoritative": ErrCode.KIR_PRECONDITION_UNMET,
    "missing_program_identity": ErrCode.KIR_PRECONDITION_UNMET,
    "live_rebuild_unimplemented": ErrCode.KIR_PRECONDITION_UNMET,
    # a single operation does not fit into the bridge's frame: there is nothing to split, the AUTHOR fixes it —
    # a sparser grid, fewer checkpoints, a shorter path (KIR-K001)
    "chunk_op_too_big": ErrCode.KIR_PROGRAM_REFUSED,
    # execution started and failed
    "rebuild_exec": ErrCode.KIR_RUNTIME_REFUSED,
    "delete_exec": ErrCode.KIR_RUNTIME_REFUSED,
    "sweep_exec": ErrCode.KIR_RUNTIME_REFUSED,
    "ops_unaccounted": ErrCode.KIR_RUNTIME_REFUSED,
    "journal_write_failed": ErrCode.KIR_RUNTIME_REFUSED,
    # A LOST CONNECTION IS NOT OUR BREAKAGE, and the model sees the difference via the retry flag.
    # `internal.unhandled` is declared (retryable=False, transient=False), meaning
    # "retrying is pointless". A severed bridge means exactly
    # the opposite. A measurement from 03.08.2026: 4571 drops (close_code=1006) over 2h 45m, and
    # for every one of them KIR answered "internal error". See `_transport_stage`.
    "bridge_disconnected": ErrCode.TRANSPORT_BRIDGE_DISCONNECTED,
    "bridge_timeout": ErrCode.TRANSPORT_BRIDGE_TIMEOUT,
    # CALL SHAPE: `program` and `program_py` both at once, neither one, or the script not
    # given as text. There was no program at all — fixed by editing the arguments, a retry
    # is safe by construction.
    "program_form": ErrCode.TOOL_INVALID_ARGS,
    "internal": ErrCode.INTERNAL_UNHANDLED,
}


#: Names of exception classes that signify a DROP. Recognition by name, rather than by
#: import, is deliberate: `websockets` is a third-party package, and a hard import would make
#: the KIR core unable to start where it is absent (an open slice, a test
#: environment). The class name is more stable than its path, meanwhile: `ConnectionClosed`
#: has moved between `websockets` modules at least twice.
_DISCONNECT_CLASS_NAMES = frozenset({
    "ConnectionClosed", "ConnectionClosedError", "ConnectionClosedOK",
    "WebSocketDisconnect", "ClientConnectionError", "ServerDisconnectedError",
})

#: Built-in drop types. `ConnectionError` is the common ancestor of `ConnectionReset`/
#: `BrokenPipe`/`ConnectionAborted`, so the whole family is caught at once.
_DISCONNECT_TYPES: tuple[type[BaseException], ...] = (ConnectionError,)

#: Silence instead of a drop: the bridge is alive but did not respond in time.
_TIMEOUT_TYPES: tuple[type[BaseException], ...] = (TimeoutError,)

#: Depth of the cause-chain traversal. A drop almost never arrives bare: it
#: is wrapped in the pipeline stage's own RuntimeError. A limit is needed because
#: the chain can be CYCLICAL (a repeated `raise ... from ...` in the recovery
#: loop), and an unbounded traversal would hang the refusal handler — that is,
#: would break exactly the path that exists in order to break nothing.
_CAUSE_DEPTH = 8


def _transport_stage(exc: BaseException | None) -> Optional[str]:
    """Flat-refusal stage if the exception is a LOST CONNECTION, otherwise None.

    WHY SEPARATE FROM `classify_bridge_error`. That one parses the bridge's PROSE and
    works when the bridge HAS RESPONDED. A dropped socket brings no prose at all — it
    arrives as an exception, bypasses the classifier, and falls into the shared
    `except Exception`, where it becomes an "internal error". So here
    the TYPE is examined, not the text.

    THE BOUNDARY IS NARROW, AND THAT IS HALF THE RULE'S VALUE. A `KeyError` or `TypeError`
    named as transport would send the model to retry a program that is broken
    deterministically — one lie would be replaced by another. Anything not confidently
    recognized stays `internal`.
    """
    seen: set[int] = set()
    current = exc
    for _ in range(_CAUSE_DEPTH):
        if current is None or id(current) in seen:
            return None
        seen.add(id(current))
        # The order of checks matters: `asyncio.TimeoutError` in Python 3.11+ IS
        # `TimeoutError`, and `TimeoutError` is a subclass of `OSError`, but NOT
        # `ConnectionError`, so there is no overlap with a drop.
        if isinstance(current, _TIMEOUT_TYPES):
            return "bridge_timeout"
        if isinstance(current, _DISCONNECT_TYPES) or (
                type(current).__name__ in _DISCONNECT_CLASS_NAMES):
            return "bridge_disconnected"
        current = current.__cause__ or current.__context__
    return None


def _failure_stage(exc: BaseException, what: str) -> tuple[str, str]:
    """(stage, message) for the shared `except` — ONE point for three handlers.

    Three handlers wrote "internal error" independently of one another, and
    fixing them separately would mean setting up three diverging rules. Here
    the decision is made once; the message tells the user WHAT to do,
    because "internal error" says nothing.
    """
    stage = _transport_stage(exc)
    if stage == "bridge_disconnected":
        return (stage, f"связь с Revit оборвалась во время {what} — "
                       "модель не изменялась, повтори через несколько секунд")
    if stage == "bridge_timeout":
        return (stage, f"Revit не ответил вовремя во время {what} — "
                       "повтори; если повторяется, перезапусти Revit")
    return ("internal", f"внутренняя ошибка {what}")


def _fix_hint(diag: dict) -> Optional[str]:
    """WHAT EXACTLY to change in the program — where the refusal knows this.

    This is exactly the advantage of a structured refusal over C# exception text: the reason
    is named not by prose but by fields (`op_id`, `field_name`, `expected`, `got`,
    `suggested_replacement`), so the hint is assembled deterministically, not
    guessed by the model from Revit's message."""
    if not isinstance(diag, dict):
        return None
    if diag.get("script_line") is not None:
        # A sandbox refusal is addressed NOT by an operation but by a line of MODEL SOURCE:
        # there are no operations yet, but the place to fix is already known exactly.
        text = str(diag.get("script_line_text") or "").strip()
        head = f"в скрипте, строка {diag['script_line']}"
        return f"{head}: {text}" if text else head
    where = diag.get("op_id") or (
        f"оп #{diag['op_index']}" if diag.get("op_index") is not None else None)
    field = diag.get("field_name")
    repl = diag.get("suggested_replacement")
    if repl is not None:
        target = f"{where}.{field}" if where and field else (where or field or "программе")
        applic = diag.get("applicability")
        sure = "" if applic == "machine-applicable" else " (проверь по месту)"
        return f"в {target} поставь {repl!r}{sure}"
    if diag.get("expected") is not None or diag.get("got") is not None:
        target = f"{where}.{field}" if where and field else (where or field or "программе")
        return (f"в {target}: ожидалось {diag.get('expected')!r}, "
                f"получено {diag.get('got')!r}")
    if diag.get("candidates"):
        target = f"{where}.{field}" if where and field else (where or field or "программе")
        return f"в {target} допустимо: {', '.join(map(str, diag['candidates'][:8]))}"
    if diag.get("violations"):
        return ("нарушены постусловия: "
                + "; ".join(map(str, diag["violations"][:5]))
                + " — исправь геометрию/параметры этих опов")
    return None


def _classify_refusal(res: dict) -> tuple[ErrCode, Optional[dict]]:
    """(taxonomy code, lead diagnostic) for a finished KIR refusal."""
    diags = res.get("diagnostics")
    lead = diags[0] if isinstance(diags, list) and diags and isinstance(diags[0], dict) else None
    kir_code = str(lead.get("code", "")) if lead else ""
    if kir_code:
        if kir_code == SANDBOX_RECON:
            # LOUD, IF REACHED. Reconnaissance does not reach here by
            # construction, so landing here is evidence of a breakage of our
            # own guard, and it cannot be kept silent.
            #
            # 🔴 A LOG RECORD, NOT AN EXCEPTION, AND THIS IS NOT CAUTION. The only
            # caller (`_stamp_refusal`) is wrapped in `except Exception` with
            # `logger.debug` — "diagnostics must not break the turn". Raising
            # from here would be SWALLOWED and settle into debug, meaning a loud
            # refusal would end up quieter than a quiet one. The ERROR level survives this
            # wrapper, because it is not an exception.
            logger.error(
                "KIR-B013 доехал до таксономии: структурный сторож "
                "`_stamp_refusal` (res['recon'] is True) не сработал. "
                "Разведочный ход сейчас будет объявлен НАШИМ дефектом — "
                "это правда о поломке, а не приговор автору скрипта")
        # 🔴 ONE CARRIER: THE OUTCOME IS ASKED FROM THE REGISTRAR.
        # Not "the table here matches the registry" but "there is no table here".
        named = diag.taxonomy_of(kir_code)
        if named is not None:
            return ErrCode[named], lead
        # The code is NOT REGISTERED with the registrar — only then does the by-letter default apply.
        # The guard `test_every_code_the_tree_emits_is_registered` keeps this
        # state unreachable for OUR tree; what reaches here is foreign.
        fallback = _UNREGISTERED_LETTER_FALLBACK.get(kir_code[:5])
        if fallback is not None:
            logger.warning(
                "KIR-код %s не заведён у распорядителя (`kir.diag.register`) "
                "— исход взят умолчанием по букве (%s). Заведи код, назвав "
                "вину и исход: умолчание не знает, чей это ремонт",
                kir_code, fallback.name)
            return fallback, lead
    flat = res.get("error")
    if isinstance(flat, str) and flat in _FLAT_ERROR_TO_ERRCODE:
        return _FLAT_ERROR_TO_ERRCODE[flat], lead
    if lead is not None:
        # the compiler rejected the program BEFORE the bridge — the model can fix it
        return ErrCode.KIR_PROGRAM_REFUSED, lead
    if isinstance(flat, str) and flat:
        return ErrCode.KIR_PROGRAM_REFUSED, lead
    return ErrCode.KIR_PROGRAM_REFUSED, lead


def _resolved_revit_version(llm_client: Any) -> "_rv.Resolved":
    """The version of THIS turn plus its provenance — one question, one answer.

    Before 13.08.2026 there were TWO copied blocks here, each with three
    independent paths to the literal "2026" (empty / exception / the regex found
    no year), and none of the six left a trace. Reads of `_revit_version`
    are unaffected by this: `getattr` under `except` keeps the same fail-open. What changes
    is exactly that the default stops being SILENT.

    Why not a refusal on unknown — `write/create_element.py:340`:
    `_revit_version` is empty in EVERY session that has never reported an
    open document, and a guard that refuses on unknown breaks all of them.
    """
    try:
        raw = getattr(llm_client, "_revit_version", None)
    except Exception:  # noqa: BLE001 — a foreign object, reading must not break the turn
        raw = None
    return _rv.resolve(raw)


def _stamp_revit_version(res: Any, llm_client: Any) -> Any:
    """Stamp the version's provenance on ANY outcome. Additive and fail-open.

    As a wrapper, not by editing every `return`, for the same reason as `err`
    (see `handle_revit_ir`): there are more than a dozen exit paths and they keep growing.

    It is placed on success AND on refusal DELIBERATELY. A refusal "op unavailable on Revit 2021"
    reads completely differently depending on whether the bridge REPORTED this
    version or we substituted it: in the first case the work is on the program's author, in the
    second — on the channel. Staying silent here would leave the reader with exactly the
    fork the module was written to resolve.

    On an honestly reported version the field `revit_version_provenance` does NOT appear
    (`Resolved.as_receipt`), so an ordinary turn stays byte-for-byte the same.
    """
    try:
        if not isinstance(res, dict):
            return res
        resolved = _resolved_revit_version(llm_client)
        if not resolved.is_guess:
            return res
        for key, value in resolved.as_receipt().items():
            res.setdefault(key, value)
    except Exception:  # noqa: BLE001 — diagnostics must not break the turn
        logger.debug("revit version provenance stamp failed", exc_info=True)
    return res


#: 🔴 СЛЕДУЮЩИЙ ХОД У ОТКАЗА — ОДИН НОСИТЕЛЬ НА ВСЮ ПРОДУКТОВУЮ ДВЕРЬ (13.09.2026).
#:
#: КУПЛЕНО ЖИВЫМ ХОДОМ ВЛАДЕЛЬЦА. 13.09 в 17:14:34→17:18:03Z ход в режиме КИР
#: («огороди электрощитовую») кончился 0 элементов, и ни одна из двух квитанций
#: отказа НЕ НЕСЛА следующего хода: `author_script` дал `handoff: null`, а
#: `ground` — одну причину «мост вернул ошибку при получении снапшота модели».
#: Конституция требует от отказа ДВЕ вещи: причину И СЛЕДУЮЩИЙ ХОД. Ход спасло
#: то, что ход назвала МОДЕЛЬ в финальном тексте, — то есть среда свою работу
#: переложила на того, кого обязана вести.
#:
#: ЭТО ТОТ ЖЕ КЛАСС Р1.2, что закрыт у MCP-двери (`kir/mcp/live.py:NO_READER_RU`),
#: и лечится он так же: ОДНИМ носителем, а не пятью правками. Палитра режима КИР
#: закрыта и мала — `revit_ir`, `revit_ir_bulk`, `ask_user`
#: (`kukai/llm/tool_masking.py:253`), поэтому названный ход обязан быть одним из
#: НИХ. Живой замер палитры того же хода: `панель режима = ['ask_user','revit_ir']`.
#:
#: 🔴 УМОЛЧАНИЕ — «СКАЖИ ЧЕЛОВЕКУ», А НЕ «ПОПРАВЬ ПРОГРАММУ». Реестр отказов
#: (`kir/diag.register`) уже ЗАПРЕЩАЕТ по построению строку, где ремонт не у
#: автора, а исход велит переписать программу; умолчание «author» вернуло бы
#: этот запрет через заднюю дверь для всякого кода, которого реестр не знает.
_NEXT_MOVE_BY_BLAME_RU = {
    "author": ("поправь программу по названной диагностике (`diagnostics`: код, "
               "строка, текст строки) и пришли `revit_ir` снова"),
    "caller": ("поправь вызов по названной диагностике — саму программу менять "
               "не нужно — и пришли `revit_ir` снова"),
    "environment": ("эту причину программой не исправить: скажи человеку ровно "
                    "эту строку через `ask_user` — документ и Revit видит он, "
                    "а не ты"),
    "ours": ("это наш дефект, а не твоей программы: чинить его тебе нечем. "
             "Скажи человеку ровно эту строку через `ask_user`"),
}

#: Когда повтор БЕЗОПАСЕН, молчать об этом нельзя: агент, не знающий, что
#: исполнение не начиналось, либо не повторит верную программу, либо повторит
#: ВСЛЕПУЮ там, где повтор удваивает. Ось `retry` уже посчитана
#: (`ProgramOutcome`), здесь она только произносится.
_RETRY_SAFE_RU = "Исполнение не начиналось — повтор той же программы безопасен."


def _next_move_ru(res: Any) -> str:
    """ЧТО ДЕЛАТЬ ДАЛЬШЕ — из того, что УЖЕ решено, а не из нового источника.

    Вина берётся по очереди у тех, кто её уже назвал: диагностика песочницы
    несёт `blame` полем, реестр знает её по коду (`diag.blame_of`). Своей
    таблицы кодов здесь не заводится: две таблицы, обязанные совпадать, — это
    именной дефект этого дерева.
    """
    try:
        from kir import diag as _diag

        вина = None
        ведущая = None
        diagnostics = res.get("diagnostics")
        if isinstance(diagnostics, list) and diagnostics:
            ведущая = diagnostics[0] if isinstance(diagnostics[0], dict) else None
        if ведущая is not None:
            вина = ведущая.get("blame") or _diag.blame_of(str(ведущая.get("code") or ""))
        if not вина:
            err = res.get("err")
            if isinstance(err, dict):
                вина = _diag.blame_of(str(err.get("kir_code") or ""))
        # `sandbox` — вина ПЕСОЧНИЦЫ, то есть наша; у реестра это `ours`.
        if вина == "sandbox":
            вина = "ours"
        ход = _NEXT_MOVE_BY_BLAME_RU.get(str(вина or ""),
                                         _NEXT_MOVE_BY_BLAME_RU["environment"])
        outcome = res.get("outcome")
        if isinstance(outcome, dict) and outcome.get("retry") == "safe":
            ход = ход + ". " + _RETRY_SAFE_RU
        return ход
    except Exception:  # noqa: BLE001 — подсказка не имеет права стоить хода
        logger.debug("next move for a refusal failed", exc_info=True)
        return _NEXT_MOVE_BY_BLAME_RU["environment"]


def _stamp_next_move(res: Any) -> Any:
    """Проставить `next_ru`, если его нет. Строго additive и fail-open.

    СТРУКТУРНО, А НЕ СПИСКОМ МЕСТ — тем же приёмом, что штампует `err`: список
    `return`-ов можно забыть, структурное правило забыть нельзя. Уже
    проставленный `next_ru` НЕ переписывается: ветка, знающая свой ход точнее
    (например «пришли программу полем `program`»), знает его лучше умолчания.
    """
    try:
        if not isinstance(res, dict) or res.get("ok") is not False:
            return res
        if res.get("recon") is True:
            return res
        if str(res.get("next_ru") or "").strip():
            return res
        res["next_ru"] = _next_move_ru(res)
    except Exception:  # noqa: BLE001
        logger.debug("next move stamping failed", exc_info=True)
    return res


def _stamp_refusal(res: Any) -> Any:
    """Stamp the `err` block on a KIR refusal. STRICTLY additive and fail-open.

    Does not touch success (`ok` is not False) and does not overwrite an already-stamped `err`:
    a diagnostics repair cannot be the cause of a turn failing."""
    try:
        if not isinstance(res, dict) or res.get("ok") is not False:
            return res
        # RECONNAISSANCE IS NOT AN ERROR, AND THIS IS HELD BY CONSTRUCTION, NOT BY A TABLE.
        # The default of `_classify_refusal` for an unknown B-code is
        # `KIR_PROGRAM_REFUSED`, meaning the table would declare a reconnaissance turn
        # a refusal silently. This cannot be caught by writing it into the table: then two
        # values (the table and the fork above) would have to coincide, and nothing forces
        # them to — the named defect of this tree. So here
        # it is a STRUCTURAL refusal that stamps `err`.
        #
        # 🔴 THE SECOND HALF OF THIS REASONING HAS BEEN FIXED: the previous wording
        # said "and `KIR-B013` is deliberately NOT entered into the table", and that did not
        # protect anything — the `.get()` default silently returned `KIR_PROGRAM_REFUSED`,
        # exactly the outcome the row was withheld to forbid.
        # Now the row exists, its value is "OUR defect", and landing there
        # is printed at the ERROR level. The guard stayed here and remained
        # structural; the table does not duplicate it but DECLARES what will happen
        # if it fails.
        if res.get("recon") is True:
            return res
        # СЛЕДУЮЩИЙ ХОД СТАВИТСЯ ДО РАННИХ ВОЗВРАТОВ: квитанция с уже
        # проставленным `err` — такой же отказ, и молчать о ходе ей нельзя.
        _stamp_next_move(res)
        if isinstance(res.get("err"), dict) and res["err"].get("code"):
            return res
        code, lead = _classify_refusal(res)
        detail = None
        if lead is not None:
            detail = lead.get("detail") or lead.get("message_ru")
        elif res.get("message_ru"):
            detail = res.get("message_ru")
        attach_err(res, code, detail=detail)
        err = res["err"]
        err["kir"] = True
        if lead is not None:
            if lead.get("code"):
                err["kir_code"] = lead["code"]
            if lead.get("op_id"):
                err["op_id"] = lead["op_id"]
            if lead.get("violations"):
                err["violations"] = lead["violations"][:10]
        elif isinstance(res.get("error"), str) and res["error"]:
            err["kir_code"] = res["error"]
        msg = res.get("message_ru") or (lead or {}).get("message_ru")
        if msg:
            err["message"] = msg
        fix = _fix_hint(lead) if lead is not None else None
        if fix is None and res.get("violations"):
            fix = _fix_hint({"violations": res["violations"]})
        if fix:
            err["fix"] = fix
        outcome = res.get("outcome")
        if isinstance(outcome, dict) and outcome.get("retry") in (
                "verify_first", "forbidden"):
            # The shared envelope classifies a corrected KIR program as
            # retryable in general.  A program that already committed (or may
            # have committed) is the strict exception: retrying it can create
            # duplicates, so the concrete execution outcome wins.
            err["retryable"] = False
            res["handoff"] = None
    except Exception:  # noqa: BLE001 — diagnostics must not break the turn
        logger.debug("KIR refusal stamping failed", exc_info=True)
    return res


def _created_count(payload: Any) -> int:
    """How many elements the program created — for the report line shown to the human.

    We count from the execution receipt, not from the program: the program says what
    WAS REQUESTED, the receipt says what resulted. The number only goes on screen, so
    any uncertainty is more honestly rounded to zero («программа выполнена») than to
    a made-up figure."""
    if not isinstance(payload, dict):
        return 0
    total = 0
    for key in ("created_ids", "element_ids", "ids"):
        v = payload.get(key)
        if isinstance(v, list):
            total += len(v)
    rows = payload.get("results") or payload.get("rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key in ("created_ids", "element_ids", "ids"):
                v = row.get(key)
                if isinstance(v, list):
                    total += len(v)
    return total


def _program_note(program: Any) -> str:
    """A short caption for "what this was" — based on the program's most frequent operation.
    To a human, «построено 240 элементов — стены» is clearer than a bare number."""
    try:
        ops = (program or {}).get("ops") or []
        if not ops:
            return ""
        from collections import Counter
        names = Counter(o.get("op") for o in ops if isinstance(o, dict) and o.get("op"))
        if not names:
            return ""
        top, _n = names.most_common(1)[0]
        return str(top).replace("create_", "").replace("_", " ")
    except Exception:  # noqa: BLE001
        return ""


#: THE HONESTY OUTCOME OF A HOLD. Not removed and not softened: a held program
#: wrote NOTHING, there is no witness, and the receipt itself must say so.
#: It moved to the SECOND line — below the subject and the next turn — because
#: a person who reads «исполнения не было» as the first line closes the window, while
#: the cube, meanwhile, stands ready to be transferred (measurement from 08.09, below).
def _transfer_button_ru() -> str:
    """Надпись кнопки одобрения — У НЕЁ ОДИН АВТОР, и это не этот файл.

    Импорт ленивый по той же причине, что и всюду в этом модуле: `preview`
    тяжёл, а квитанция придержки собирается на горячем пути. Промах импорта
    не имеет права стоить квитанции — тогда человек не узнает ни причины, ни
    следующего хода, а это хуже неточного слова.
    """
    try:
        from kir.preview import TRANSFER_BUTTON_RU
        return TRANSFER_BUTTON_RU
    except Exception:  # noqa: BLE001
        return "Одобрить"


HELD_HONESTY_RU = (
    "В Revit НИЧЕГО НЕ ЗАПИСАНО и свидетеля нет — исполнения не было: "
    "программа удержана в KIR и ждёт вашего слова.")


def _held_receipt(program: Any, *, ops: int,
                  document_fingerprint: Any = None) -> dict[str, Any]:
    """THE HOLD RECEIPT: the subject on the first line, the instrument on the second.

    🔴 BOUGHT BY THE OWNER'S LIVE TURN ON 08.09.2026. He wrote "make a cube".
    The program was accepted and held — that is, the cube STOOD READY — while
    the receipt began with the words «Программа принята и показана в окне КИР».
    Accepted WHAT? No size, no kind, no count: the subject was not in the receipt
    at all. Next to it, the card was spewing out a census of a foreign journal slice (94 of 98,
    124 ops, 195 programs — not one number about his cube). The owner's word:
    "what kind of garbage is it dumping into my chat… I asked it to build a cube — it can't".

    WHAT STOOD HERE BEFORE AND WHY THAT IS NOT ENOUGH. The button was named correctly
    (fix from 16.08: «Отправить в Revit» → «перенести в Revit», the guard
    `test_a_silent_reason_for_an_empty_panel` and the comment above). But
    a named turn without a named SUBJECT answers the human's second question
    without answering the first: "but what actually got built?". The constitution requires
    telling it in units of the model and the human — size in millimeters and the kind
    of the body are exactly those units.

    THE ORDER OF THE LINES IS THE FIX ITSELF:
      1) `куб 3000×3000×3000 мм · уровень программы — «Уровень 1» · 1 операция`
      2) `Следующий ход: ⇣ перенести в Revit (1 оп) — кнопка в окне КИР.`
      3) the honesty outcome (`HELD_HONESTY_RU`) — not lost, but second.
    The census numbers, the instrument's words, and the full signature all live in `details`: the window
    can collapse them but cannot lose them.

    FAIL-OPEN DELIBERATELY. The card is decoration on top of the hold, and a crash
    of the renderer has no right to cost the human their program: on any error
    the previous text is returned, and the hold happens regardless.

    🔴 THE THIRD AND FOURTH LINES (08.09.2026) — MEMORY AND ADDRESS, BOTH IN RUSSIAN.
    Wave 9 carried the journal-load diagnosis through to the `journal_restore` field and
    stopped there: the field exists in the receipt, but the text a human would read
    in chat does not. Here it is unfolded by `preview.journal_note_ru`, while the
    instrument's words (the refusal name, the store key, the path) stay in `details`.

    `document_fingerprint` is the identity of the document read by THE BRIDGE. It
    is known to the caller (grounding happens BEFORE the hold) and nowhere else: it
    arrives here as an argument, rather than being obtained by a second traversal, because
    a second traversal of the same fact is the named defect of this file
    (`_turn_session_context`). A mismatch with the WINDOW's document is named
    (`_document_identity_crosscheck`), rather than passed over in silence.
    """
    receipt: dict[str, Any] = {
        "ok": True,
        "kir": True,
        "stage": "planned",
        "held_in_kir": True,
        "ops": ops,
        # 🔴 THE NEXT TURN MUST NAME SOMETHING THAT EXISTS. The button now
        # reads «Одобрить» (13.09.2026, the owner: labels of two words at
        # most). The word is not typed here twice: it comes from
        # `preview.TRANSFER_BUTTON_RU`, the single author of that label, and
        # `backend/tests/test_held_receipt_names_a_real_button.py` holds the
        # two sides together.
        "message_ru": (
            "Программа принята и показана в окне КИР. "
            + HELD_HONESTY_RU
            + " Перенос в Revit — отдельное действие: "
            f"кнопка «{_transfer_button_ru()}» в окне КИР."),
        "handoff": None,
    }
    сверка = None
    if document_fingerprint is not None:
        try:
            сверка = _document_identity_crosscheck(document_fingerprint)
        except Exception:  # noqa: BLE001 — the crosscheck has no right to cost the turn
            logger.debug("document identity crosscheck failed", exc_info=True)
    if сверка is not None and сверка.get("refused"):
        logger.warning("KIR %s: окно «%s», мост «%s» (поле %s)",
                       DOCUMENT_IDENTITY_MISMATCH, сверка.get("socket"),
                       сверка.get("bridge"), сверка.get("checked"))
    try:
        from kir.preview import program_card
        card = program_card(program, ops=ops,
                            journal_restore=_journal_restore_diagnosis())
    except Exception:  # noqa: BLE001 — the card has no right to cost the turn
        logger.debug("held card failed (fail-open)", exc_info=True)
        if сверка is not None:
            receipt["document_identity"] = сверка
        return receipt
    details = dict(card.get("details") or {})
    details["honesty_ru"] = HELD_HONESTY_RU
    receipt["summary"] = card.get("summary")
    receipt["summary_ru"] = card.get("summary_ru")
    receipt["levels"] = card.get("levels")
    receipt["details"] = details
    строки = [str(card.get("summary_ru", "")), HELD_HONESTY_RU]
    if сверка is not None:
        receipt["document_identity"] = сверка
        details["document_identity"] = сверка
        if сверка.get("message_ru"):
            # LAST, BUT NOT IN `details`: an address mismatch is the only
            # line of this receipt after which a human MUST NOT press
            # the button without thinking.
            строки.append(str(сверка["message_ru"]))
    receipt["message_ru"] = "\n".join(строки)
    return receipt


def _acceptance_diagnostic(
    evidence: Any,
    *,
    durability_error: str | None = None,
) -> dict[str, Any]:
    """Translate the independent judge without interpreting its evidence."""

    if durability_error is not None:
        return {
            "code": "KIR-A008",
            "message_ru": (
                "запись закоммичена, но доказательство приёмки не удалось "
                "надёжно сохранить — успех не объявлен"),
            "detail": durability_error,
        }
    state = getattr(evidence, "state", None)
    if state is AcceptanceState.REJECTED:
        scope_verdict = getattr(evidence, "verdict", None)
        mutation_verdict = getattr(evidence, "mutation_verdict", None)
        mismatches = []
        if scope_verdict is not None:
            mismatches.extend({"axis": "scope", **item.to_dict()}
                              for item in scope_verdict.mismatches)
        if mutation_verdict is not None:
            mismatches.extend({"axis": "mutation", **item.to_dict()}
                              for item in mutation_verdict.mismatches)
        mismatches = mismatches[:10]
        details = []
        if scope_verdict is not None and scope_verdict.mismatches:
            details.append(scope_verdict.summary_ru())
        if mutation_verdict is not None and mutation_verdict.mismatches:
            details.append(
                "mutation predicates differ: "
                f"{len(mutation_verdict.mismatches)}")
        return {
            "code": "KIR-A006",
            "message_ru": (
                "запись закоммичена, но независимое повторное чтение "
                "обнаружило расхождение — проверь модель"),
            "detail": "; ".join(details) or "independent acceptance rejected",
            "mismatches": mismatches,
        }
    reason = getattr(getattr(evidence, "reason", None), "value", "unknown")
    # 🔴 "NOT COMPLETED" COMES IN TWO KINDS, AND ONE OF THEM IS NOT ABOUT THE AUTHOR
    # (24.08, bought by a live run). The census is blind to part of the ops BY
    # CONSTRUCTION: for `author_family` the category is brought by a template file from the
    # user's machine, and the census cell is not derived from the program at all. Such
    # an op returns `inconclusive` ALWAYS — even with a commit that took place and
    # a satisfied witness.
    #
    # The previous text said the same thing to both cases: "check the model". To an author
    # whose program ran successfully, this is an address to nowhere, and he follows it
    # honestly: in the 24.08 measurement `author_family` burned ten and eleven
    # turns in two consecutive runs, without ever building anything — while
    # the ONLY refusal he could actually fix lay elsewhere.
    #
    # Blindness must name ITSELF, not send someone off to hunt for someone else's defect.
    # `retry: forbidden` is already set in the outcome — now it is also said in words.
    # 🔴 WE READ THE HOME OF THE LAW, NOT ONE OF ITS THREE CARRIERS (24.08, a second
    # purchase of the same form within a day). The previous line asked
    # `expectation.blind_ops` — the CENSUS carrier. For a live `create_type` it
    # is empty, while the MUTATION carrier is full, and the text fell into the shared "check
    # the model" branch — exactly the address to nowhere that `cb8ad6d6` was written to fix.
    # The fix was green in the test and dead in prod: the test's double was filling
    # exactly the carrier that the function read.
    registration = getattr(evidence, "registration", None)
    blind = tuple(getattr(registration, "blind_ops", ()) or ())
    if blind:
        named = "; ".join(
            f"{getattr(b, 'op_name', '?')} ({getattr(b, 'op_id', '?')}): "
            f"{getattr(b, 'reason', '')}" for b in blind[:3])
        return {
            "code": "KIR-A007",
            "message_ru": (
                "запись ЗАКОММИЧЕНА, свидетель её принял; независимая "
                "ПЕРЕПИСЬ к этому опу слепа ПО ПОСТРОЕНИЮ — поэтому успех "
                "не объявлен. Это граница нашего прибора, а не дефект твоей "
                "программы: повторять её НЕ НАДО (retry: forbidden), "
                "построенное уже в модели"),
            "detail": (f"independent acceptance is inconclusive: {reason}; "
                       f"blind ops: {named}"),
            "acceptance_reason": reason,
            "blind_ops": [b.to_dict() if hasattr(b, "to_dict")
                          else str(b) for b in blind],
        }
    return {
        "code": "KIR-A007",
        "message_ru": (
            "запись закоммичена, но независимая приёмка не завершена — "
            "успех не объявлен; проверь модель"),
        "detail": f"independent acceptance is inconclusive: {reason}",
        "acceptance_reason": reason,
    }


# ═════════════════════════════════════════════════════════════════════════════
# TRANSLATION CERTIFICATE ON THE LIVE PATH — AFTER COMPILATION, BEFORE THE FIRST EFFECT
#
# WHY AT ALL. A green write in this system stands on four legs: the commit
# is confirmed, the compiler's internal witness is satisfied, an independent
# re-read accepted the pre-registered predicate, the terminal evidence
# is durable. The second leg rests on the witness being CAPABLE of failing.
# A mutation on 09.08.2026 showed that this did not follow from anything: a substituted
# verdict `if (false) __post.Add("never")` left `certify_op(...).proven ==
# True`, meaning "postconditions are not violated" would be true by tautology.
# A program with such a witness must not write AT ALL: its green would mean
# nothing, and `ok:true` without independent confirmation is a forbidden
# state.
#
# WHY EXACTLY HERE, AND NOT IN `compile_program`.
#   * This is the ONLY point where the plan becomes an effect, and through it
#     pass all three doors (chat, admin bulk, a Python script) — the same
#     argument by which the live-plan splice and the
#     preflight check of the open model sit here. A splice into the compiler
#     would force the dry gate (1212 compilations ×6 versions) and
#     offline decompiles, where there is no effect at all, to pay the cost too.
#   * Nothing has HAPPENED here yet: the ground snapshot is a read, there is no transaction,
#     no prepared journal event exists. A refusal from here costs zero effects.
#   * EXACTLY the operation that went into C# is certified (`out.grounded_ops` —
#     the grounded view of the lowering from which the emitter assembled `out.csharp`), not
#     a neighboring one.
#
# COST MEASUREMENT (09.08.2026, this box, python3.12, median of 5 runs):
# a corpus of 32 grounded programs — p50 7.1 ms per program, maximum
# 34.6 ms, ≈4 ms per operation; the largest program the compiler allows at all
# (299 ops, the MAX_BULK_OPS ceiling) — 1206 ms, with 74 ms for the whole
# compilation. Against a live write to Revit taking tens of seconds, this is 3–5% on
# the largest chunk and a fraction of a percent on a chat-sized program. THERE IS NO CACHE AND IT IS NOT
# NEEDED, and this too is a measurement, not an opinion: on that same 299-op program 1199
# witness fragments produced 1199 distinct digests — a cache on the digest
# of the emitted text would have had EXACTLY ZERO hits (every witness carries
# the operation's id and its coordinates). A cache that never fires is just
# another dark path, not an optimization.
#
# WHAT WAS ABSENT REMAINED ABSENT, AND THIS IS A MEASUREMENT, NOT A PROMISE (09.08.2026):
# a digest of THE ENTIRE emission — 188 lowerings (32 corpus programs × up to 6 versions
# of Revit), each with `plan_digest`, the sha256 of the emitted C#, and the sha256 of the receipt
# `CompileOutput.as_dict()` — with the flag off matched before and after this splice:
#   b50da8a10ddbe82079102d3780fabe1161535dc483f158a0c46c3eefd9722e54
# (measured on the tree BEFORE and on the tree AFTER with the same script; the field
# `grounded_ops` is not included in the receipt for exactly this reason).
# ═════════════════════════════════════════════════════════════════════════════

#: How many certificate diagnostics ride along in the receipt (as with the compiler).
_CERT_DIAGNOSTIC_LIMIT = 8


def _certificate_diagnostics(certificate: Any,
                             grounded_ops: Sequence[dict]) -> list[dict]:
    """Certificate breaks → typed diagnostics, TIED TO THE OP.

    The certificate names the operation by ITS NAME (`create_wall`), while the fix
    is addressed by its IDENTIFIER in the program. The order of `ProgramCertificate.ops`
    matches the order of the grounded operations (`certify_program` goes through them
    in sequence), so the index recovers both `op_id` and `op_index`.
    """

    out: list[dict] = []
    for index, op_cert in enumerate(getattr(certificate, "ops", ())):
        source = grounded_ops[index] if index < len(grounded_ops) else {}
        op_id = source.get("id") if isinstance(source, dict) else None
        for finding in op_cert.vacuous:
            out.append(Diagnostic(
                code=CERT_VACUOUS,
                op_index=index,
                op_id=op_id,
                field_name=finding.obligation_key,
                got=finding.kind,
                message_ru=finding.describe(),
            ).as_dict())
        for verdict in op_cert.clauses:
            if not verdict.required or verdict.discharged:
                continue
            out.append(Diagnostic(
                code=CERT_UNPROVEN,
                op_index=index,
                op_id=op_id,
                field_name=verdict.kind,
                got=verdict.reason,
                message_ru=(
                    f"{op_cert.op}: обязательство не разряжено "
                    f"[{verdict.kind}] {verdict.clause} ({verdict.reason})"),
            ).as_dict())
    return out


def _certify_translation(out: Any, revit_version: str) -> dict:
    """Translation certificate receipt for a single compiled program.

    Always returns a dict (never raises): the certifier is an instrument, and
    a broken instrument has no right to reject a correct write.

    ``status``:
      * ``proven``          — every obligation is discharged by a live witness;
      * ``vacuous``         — the witness exists and is provably dead (A FINDING);
      * ``unproven``        — an obligation without a witness (A FINDING);
      * ``uncertifiable``   — the registry has outrun the obligations table: THE INSTRUMENT
        IS SILENT, and this is not a finding;
      * ``instrument_failed`` — the certifier itself crashed: also not a finding.

    ONLY THE FIRST TWO CLASSES REFUSE, AND ONLY IN ``refuse`` MODE. The difference
    between "the instrument found a defect" and "the instrument fell short" is exactly the difference
    on which correct rooms were rolled back for months: acceptance broke on
    Cyrillic, meaning it REJECTED CORRECT work by its own internal bookkeeping.
    An instrument's silence must be NAMED in the receipt and passed through, not presented
    as a finding.
    """

    from kir import translation_cert as _cert

    mode = _cert.certificate_mode()
    grounded = list(getattr(out, "grounded_ops", ()) or ())
    receipt: dict[str, Any] = {
        "mode": mode,
        "revit_version": revit_version,
        "ops": len(grounded),
    }
    started = time.perf_counter()
    try:
        if not grounded:
            # A writing program without a grounded view is not a finding but
            # an absence of material to judge by (this is what paths look like that do not
            # pass through the compiler's authoring branch).
            receipt["status"] = "uncertifiable"
            receipt["detail"] = "нет заземлённого вида нижения"
        else:
            certificate = _cert.certify_program(grounded, revit_version)
            vacuous = bool(certificate.vacuous)
            if certificate.proven:
                receipt["status"] = "proven"
            else:
                receipt["status"] = "vacuous" if vacuous else "unproven"
                # THE TOTAL RIDES ALONGSIDE THE TRUNCATED LIST. Cutting at eight and
                # staying silent about it means asserting "here are all the diagnostics"
                # where there were twenty: the reader sees a list that looks complete
                # and has no reason to doubt it at all. It's the same
                # form as the rest of the series — a value is asserted in
                # one place and read in another — and the same remedy as
                # the collision check uses: name the COUNT, rather than show a tail.
                _diagnostics = _certificate_diagnostics(certificate, grounded)
                receipt["diagnostics"] = _diagnostics[:_CERT_DIAGNOSTIC_LIMIT]
                receipt["diagnostics_total"] = len(_diagnostics)
            partial = sorted({
                key for op_cert in certificate.ops
                for key in op_cert.vacuity_partial})
            if partial:
                # "Read in full" and "read in pieces" are different facts,
                # and the second must not be read as proof of cleanliness.
                receipt["vacuity_partial"] = partial[:_CERT_DIAGNOSTIC_LIMIT]
                # AND ESPECIALLY HERE. The comment one line above says that
                # "read in pieces" must not be read as proof
                # of cleanliness — yet the list carrying that very fact was silently truncated.
                receipt["vacuity_partial_total"] = len(partial)
    except _cert.CertificateSchemaError as exc:
        receipt["status"] = "uncertifiable"
        receipt["detail"] = str(exc)[:300]
    except Exception as exc:  # noqa: BLE001 — the instrument must not break the write
        logger.debug("translation certificate failed", exc_info=True)
        receipt["status"] = "instrument_failed"
        receipt["detail"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    receipt["duration_ms"] = round(
        (time.perf_counter() - started) * 1000.0, 3)
    receipt["refused"] = bool(
        mode == _cert.CERT_MODE_REFUSE
        and receipt["status"] in ("vacuous", "unproven"))
    return receipt


def _record_pre_effect(
    stage: str,
    diagnostics: Any,
    ops: Any,
    *,
    query_id: str = "",
    turn_id: str = "",
    action_id: str = "",
    query_fingerprint: str = "",
    source_kind: str = "unknown",
    revit_version: str = "2026",
) -> None:
    """Record a typed refusal that happened before the first Revit effect.

    These rows belong to the rejection corpus, not the witness corpus: no
    write reached Revit.  Telemetry remains fail-open and can never change
    the refusal it describes.
    """
    try:
        from kir import coverage_feed

        typed: list[Diagnostic] = []
        for item in diagnostics or ():
            if isinstance(item, Diagnostic):
                typed.append(item)
            elif isinstance(item, dict) and item.get("code"):
                typed.append(Diagnostic(**{
                    key: value for key, value in item.items()
                    if key in Diagnostic.__dataclass_fields__
                }))
        if not typed:
            return
        coverage_feed.record_rejections(
            typed,
            list(ops or ()),
            query_id=query_id,
            revit_version=revit_version,
            stage=stage,
            turn_id=turn_id,
            action_id=action_id,
            query_fingerprint=query_fingerprint,
            source_kind=source_kind,
        )
    except Exception:  # noqa: BLE001 — telemetry cannot break a refusal
        logger.debug("pre-effect rejection telemetry failed", exc_info=True)


def _certificate_refusal(receipt: dict) -> dict:
    """Refusal BEFORE THE EFFECT over an uncertified certificate.

    ``handoff`` is deliberately ``None``. Letting this write proceed to free-form C# would mean
    executing it with no witness at all — amplifying exactly the defect that
    caused the refusal (the same argument stands behind the refusal to prepare acceptance).
    """

    message = (
        "внутренний свидетель программы не доказан: "
        + ("свидетель есть и доказуемо не может сработать"
           if receipt.get("status") == "vacuous"
           else "у обещанного постусловия нет свидетеля")
        + " — запись не запускалась")
    diagnostics = receipt.get("diagnostics") or [Diagnostic(
        code=(CERT_VACUOUS if receipt.get("status") == "vacuous"
              else CERT_UNPROVEN),
        message_ru=message).as_dict()]
    return _with_outcome({
        "ok": False,
        "kir": True,
        "refused": True,
        "stage": "translation_certificate",
        "diagnostics": diagnostics,
        "message_ru": message,
        "handoff": None,
        "certificate": receipt,
    }, program_not_started())


# ═════════════════════════════════════════════════════════════════════════════
# THE SOURCE-LANGUAGE GATEWAY — Python becomes operations EXACTLY HERE
#
# The model writes either a program made of operations (`program`), or a script that
# generates it (`program_py`). The script is executed in a separate process
# (`kir/sandbox.py`), NEVER touches Revit, and emits exactly
# one thing — a list of IR operations.
#
# AND FROM HERE THE SAME PATH BEGINS AS FOR JSON: `plan_program`, grounding,
# emission, the witness in the transaction, independent acceptance, the journal. Below the gateway there is
# NOT A SINGLE "what if it was a script" branch — because the boundary of safety and
# provability runs along the IR, not along the language the IR was written in. The
# conversion point is one, and it is HERE, before entry into the body: the body must not be able to tell the difference.
#
# WHAT IS ADDED TO THE PROOF. `plan_digest` signs the program;
# `author_digest` signs the SOURCE that generated it. Together they read as
# "this program was generated by this exact script" — a reproducibility that does
# not exist at all on the JSON path. Hence `replay_check` below as well: a signature that
# nobody checked is a promise, not a proof.
# ═════════════════════════════════════════════════════════════════════════════

_SCRIPT_FIELD = "program_py"

#: Sandbox policy for the prod path.
#:
#: `replay_check=True` — AND THIS IS THE MAIN DECISION HERE. The script is executed TWICE
#: and the digests of the two programs are compared. The cost is measured: the happy path costs
#: ~170 ms for 104 operations, meaning the repeat adds ~0.2% to the turn (a live write
#: to Revit takes tens of seconds). The price for `author_digest` ceasing to be
#: a promise: the signature of a non-deterministic script certifies NOTHING, and
#: we are the ones obligated to find that out, not the reader of the receipt six months later.
#: The sandbox's screens (object addresses in the output, the ban on random/time/os) catch
#: only what leaves a trace; the run-to-run comparison catches everything that changes the OUTPUT.
_AUTHOR_SANDBOX_POLICY: dict = {}   # lazy initialization: see _sandbox_policy


def _sandbox_policy():
    """Sandbox policy. Lazy, so that importing serving does not pull in the sandbox.

    THE IMPORT ALLOWLIST IS READ LIVE, ON EVERY TURN. Before 09.08 there was
    a single cached object here, and the operator toggle's position was fixed by
    the very first request after the service started — meaning "flipped the flag on" would mean
    "restart the four workers", while "flipped it off" would mean nothing at all.
    A toggle that does not take effect immediately reads as disagreement with the service; the same
    rule is upheld by `checker.flags.checker_v2_enabled`.

    The cache remains, but THE LIST ITSELF SERVES AS THE KEY: `SandboxPolicy` is a frozen
    dataclass, and its two states live side by side without any contradiction."""
    from kir.sandbox import SandboxPolicy, allowed_imports_for_env
    allowed = allowed_imports_for_env()
    policy = _AUTHOR_SANDBOX_POLICY.get(allowed)
    if policy is None:
        policy = SandboxPolicy(replay_check=True, allowed_imports=allowed)
        _AUTHOR_SANDBOX_POLICY[allowed] = policy
    return policy


@dataclass(frozen=True)
class _AuthoredInput:
    """What defines the program — and what signs it.

    ``args`` is what goes into the tool's body: always the ordinary
    ``{"program": {...}}``, regardless of whether the model wrote it or Python did.
    """

    args: Any
    refusal: Optional[dict] = None
    from_script: bool = False
    author_digest: str = ""
    #: The signature of the ENVIRONMENT in which the script executed (see `sandbox.environment_signature`).
    #: It travels alongside `author_digest` everywhere the latter travels: a source signature without
    #: an environment signature certifies exactly half.
    env_digest: str = ""
    #: The signature of the document CATALOG fed to the script. A third signature alongside
    #: the first two, and for the same reason: one source over different buildings
    #: yields different programs, and without it, editing the script is indistinguishable from drift in the
    #: model.
    model_digest: str = ""
    #: The signature of the SUBMITTED PARAMETERS — a fourth signature of the same kind. It was
    #: set up for the sake of the slider: the pair "the same author_digest + a different params_digest"
    #: reads as "the handle was moved", and this is the ONLY way to tell it apart from
    #: editing the definition, because the program differs in both cases.
    params_digest: str = ""
    #: THE FIFTH SIGNATURE — the building catalog fed to the script. The four siblings above
    #: have reached here from the very start, while this one was computed by the sandbox and
    #: was read by NO ONE: zero reads across the whole package (measurement from 27.08.2026).
    #:
    #: 🔴 WHY THE `SandboxResult.as_dict` FIX DID NOT SAVE IT. `model_digest`
    #: is also missing from `as_dict` and reaches its destination fine — because `_AuthoredInput`
    #: is assembled FROM THE OBJECT, and `as_dict()` is never called in prod at all. That
    #: fix repaired the receipt, not the evidence; the evidence is fixed here.
    building_digest: str = ""
    #: PROVENANCE OF THE OPERATIONS: `{op id: [script lines, outside-in]}`.
    #:
    #: A sidecar, not a field of the program: the compiler rejects `_lineage` in the
    #: envelope with `KIR-P003` (verified by execution), and rightly so —
    #: provenance must not change `plan_digest`.
    lineage: dict = field(default_factory=dict)
    #: The source lines that `lineage` points to, and only those:
    #: `{number: text}`. There is no need to keep the whole script for the sake of three lines.
    source_lines: dict = field(default_factory=dict)
    receipt: Optional[dict] = None


def _form_refusal(message: str) -> dict:
    """A CALL-SHAPE refusal: it is not the program that is wrong, but the way it was given.

    `handoff` is empty here deliberately. "recipe-path" means "the task is outside KIR's
    scope" — but here the task is exactly within it, and the next turn is fixed with one
    edit to the arguments. Advice to go to other tools would be false."""
    return _with_outcome(
        {"ok": False, "kir": True, "refused": True, "error": "program_form",
         "message_ru": message, "handoff": None},
        program_not_started())


def _lines_named_by(source: Any, lineage: Any) -> dict:
    """The source lines that the sidecar points to — and only those.

    There is no need to keep the whole script for the sake of three lines, and putting it into the receipt is
    even less necessary: it is already signed by `author_digest`."""
    if not isinstance(lineage, dict) or not lineage:
        return {}
    if not isinstance(source, str) or not source:
        return {}
    wanted: set[int] = set()
    for frames in lineage.values():
        if isinstance(frames, (list, tuple)):
            wanted.update(n for n in frames if isinstance(n, int)
                          and not isinstance(n, bool) and n > 0)
    if not wanted:
        return {}
    rows = source.splitlines()
    return {n: rows[n - 1] for n in sorted(wanted) if 0 < n <= len(rows)}


@functools.lru_cache(maxsize=1)
def _member_path_shape() -> tuple[str, str]:
    """A wrapper for the address form of a unit member — ASKED FROM THE MINTER, not typed out.

    The form `members[<id>]` is minted by `compiler._group_member_diagnostic`, and it
    already has THREE carriers (there, in `course._UnitContext.__exit__`, and in
    `authoring_validation`). A fourth literal here would drift apart from them at the
    very first edit — the named defect of this tree — so the prefix and the tail
    are obtained with ONE call to the minter itself, using sentinel names.

    Why the form is needed at all, rather than a bare split at the first dot: without it
    ANY first segment would become the key, and an ordinary diagnostic with a compound
    field (`contour.holes`, `where.kind`) would end up in the sidecar if the author
    named their op `contour`. That would produce a PLAUSIBLE BUT WRONG line —
    shape 44, exactly what is being fixed here.
    """
    from kir.compiler import _group_member_diagnostic
    # 🔴 `Diagnostic` IS NOT IMPORTED HERE — IT ALREADY EXISTS AT MODULE LEVEL (line 70,
    # from the same `kir.diag`), and a local copy of the name was SHADOWING: the same
    # object under the same name, but bound anew. A reader of the function cannot
    # tell this apart from a swap for a different class without going up top — and that
    # is exactly what a real swap looks like. The guard
    # `test_authority_boundaries::test_no_function_local_import_shadows_a_module_import`
    # catches this; three carriers of the class were removed on 27.08 (97e4b91), this one was the fourth
    # and arrived the same day with `_member_path_shape` (2d915f0).
    # `TYPE_BAD_TYPE` is NOT imported at module level, so it stays here.
    from kir.diag import TYPE_BAD_TYPE

    minted = _group_member_diagnostic(
        Diagnostic(code=TYPE_BAD_TYPE, field_name="", message_ru=""),
        group_id="__g__", group_index=0, member_id="__m__", member_index=0)
    head, _sep, tail = (minted.field_name or "").partition("__m__")
    return head, tail


def _frames_for(d: Any, lineage: Any) -> Any:
    """Author frames for ONE diagnostic: the unit member first, the op as fallback.

    🔴 THIS WAS A WRONG ADDRESS, NOT A MISSING ONE. Measurement from 27.08.2026: three
    walls in a loop inside `with unit(...)`, an error in the second one (line 5) — the refusal
    printed "line 3", the line of the `with` statement itself. A plausible value is more dangerous
    than an absence: nobody argues with it, and the author went off to fix a line that had no error.
    And `unit()` is a technique the course RECOMMENDS for an apartment, meaning the hole
    lay on the recommended path.

    There was one cause: the `op_id` of a member's diagnostic is the GROUP
    (that is exactly how `compiler._group_member_diagnostic` mints it), while the sidecar carries
    the member under a separate key. The lookup was by `op_id` exactly, and it found the group.

    THE GROUP KEY REMAINS AS A FALLBACK, rather than being discarded: it addresses the
    `with` itself, and that is a separate, legitimate fact for a diagnostic about the group itself.
    """
    if not isinstance(lineage, dict):
        return None
    field = getattr(d, "field_name", None) or ""
    if field:
        head, tail = _member_path_shape()
        # The member's path is the FIRST segment; the guard
        # `test_group_members_keep_their_author_line.ФормаАдресаОдна`
        # breaks it down the same way, by asking the minter.
        cand = field.split(".", 1)[0]
        if head and cand.startswith(head) and cand.endswith(tail) \
                and cand in lineage:
            return lineage[cand]
    return lineage.get(getattr(d, "op_id", None))


def _name_the_author_line(diagnostics: Any, lineage: Any,
                          source: Any = None) -> list[dict]:
    """Append the author script's line to a COMPILER refusal.

    THE KEY CHOICE LIVES IN `_frames_for` — its rationale is there too: for a MEMBER's diagnostic
    of a unit the `op_id` is the GROUP, and looking up by it alone printed the `with` line
    instead of the line of the failed operation.

    🔴 ONLY AN EXACT KEY MATCH. The sidecar's key is the op's author-given `id`;
    the diagnostic's key is the `id` AFTER macro expansion. Measured on 27.08.2026
    by execution: a single author `stack` with three levels expands into
    SIX operations with keys `S1_L1`…`S1_L3_W`, whereas the sidecar carries `S1`.
    A prefix match would name a line the author never wrote — and that is
    worse than silence (shape 44: a plausible value is more dangerous than an absence,
    because nobody argues with it).

    THE BOUNDARY IS NAMED, NOT CLOSED: a legitimate bridge exists —
    `PlannedOp.provenance.source_id` gives `S1` for all six expanded ops
    (verified) — but on a REFUSAL it is unreachable: `CompileOutput.planned` there is
    `None`. Closing this requires a fix to the compiler, not to this file.

    THE COST OF THIS BOUNDARY IS MEASURED AND SMALL: the macros (`stack`, `grid_array`,
    `series`) are NOT in `dsl.__all__`, meaning from the script door — the only one
    where the sidecar exists at all — a macro cannot be written. On the JSON door the sidecar
    is empty by construction. So on the live path an exact match is COMPLETE.

    THE FORMAT IS NOT SET UP A SECOND TIME: it is printed by `SandboxRefusal.render()`,
    and exactly that is what is built here (see `_rendered_with_line`). A homegrown
    `f"строка {n}"` would become a third carrier of the same knowledge and would drift apart from
    the first two at the very first edit to the output.
    """
    rows = source if isinstance(source, dict) else {}
    out: list[dict] = []
    for d in diagnostics or ():
        row = d.as_dict()
        frames = _frames_for(d, lineage)
        clean = [n for n in frames if isinstance(n, int)
                 and not isinstance(n, bool) and n > 0] \
            if isinstance(frames, (list, tuple)) else []
        if clean:
            inner = clean[-1]
            row["message_ru"] = _rendered_with_line(
                d.message_ru, inner, rows.get(inner), clean)
            row["author_line"] = inner
            if len(clean) > 1:
                row["author_frames"] = list(clean)
        out.append(row)
    return out


def _rendered_with_line(message: str, line: int, text: Any,
                        frames: list) -> str:
    """The same text that `SandboxRefusal.render()` prints — using ITS OWN code.

    The refusal is built with an empty `code`, so `render()` returns `": <msg>…"`;
    the first two characters are stripped. The trick is ugly and deliberate: the alternative
    is to rewrite the format here, that is, to set up a second carrier."""
    from kir.sandbox import SandboxRefusal

    rendered = SandboxRefusal(
        code="", message_ru=message, kind="compiler",
        line=line, line_text=text if isinstance(text, str) else None,
        script_frames=list(frames),
    ).render()
    return rendered[2:] if rendered.startswith(": ") else rendered


def _authorship_receipt(result: Any, *, source_bytes: int) -> dict:
    """The receipt block for "this program was generated by this exact script".

    Travels alongside `plan_digest` on both success and refusal: the signature of a source
    that did NOT compile is just as much evidence as the signature of one that did.

    `stdout` here is not decoration. Form samples (`tower_numpy.py`) print
    the deviation of the polyline from the curve it approximates AS A NUMBER; cutting this
    channel off would mean returning to "said sine, built a polyline, said nothing" — exactly
    the silently-wrong answer that the whole house stands against.

    `environment` is THE SECOND HALF OF THE SIGNATURE, and it is here in full, not as a single
    digest. `author_digest` says WHAT the program was written with; `environment`
    says WHAT IT WAS COMPUTED ON (the interpreter and the versions of everything the script could
    have imported). Without it, two receipts for the same script that diverged because of
    a library update read as the same turn with a different outcome —
    "one building, two signatures" on a layer that was not signed at all
    before 09.08. An auditor looks into the receipt, so the block lives in the receipt; into the
    corpus recorded to disk (`witness_feed`) goes its digest."""
    isolation = dict(getattr(result, "isolation", None) or {})
    environment = dict(getattr(result, "environment", None) or {})
    receipt = {
        "language": "python",
        "author_digest": getattr(result, "author_digest", "") or "",
        "op_count": len(getattr(result, "ops", None) or []),
        "source_bytes": source_bytes,
        "duration_ms": round(float(getattr(result, "duration_s", 0.0)) * 1000.0, 1),
        # A measurement, not an intent: what the sandbox ACTUALLY DID on this run.
        "isolation": {key: isolation[key]
                      for key in ("namespaces", "filesystem", "network_probe")
                      if key in isolation},
        "replay_checked": bool(isolation.get("replay_checked")),
    }
    if environment:
        # Empty exactly when the child never ran (an empty or too-large
        # source): there is nothing to sign, and an empty block would say
        # "environment unknown" instead of "the script was not executed".
        receipt["environment"] = environment
    params = list(getattr(result, "params", None) or [])
    if params:
        # THE HANDLE LEDGER — what the slider is drawn from. It travels only when
        # handles are declared: an empty block would read as "handles exist, but empty".
        receipt["params"] = params
    params_sig = getattr(result, "params_digest", "") or ""
    if params_sig:
        receipt["params_digest"] = params_sig
    model_digest = getattr(result, "model_digest", "") or ""
    if model_digest:
        # THE THIRD SIGNATORY. Empty means the catalog was not fed to this turn (offline,
        # the bridge was silent, or the program was given as plain JSON); a missing key and
        # an empty string would read equally wrongly here, so the key
        # simply is not there.
        receipt["model_digest"] = model_digest
    digest = getattr(result, "program_digest", "") or ""
    if digest:
        receipt["program_digest"] = digest
    stdout = getattr(result, "stdout", "") or ""
    if stdout:
        receipt["stdout"] = stdout
    # 🔴 PROGRAMS LEFT BEHIND ARE NAMED. The door builds the CURRENT
    # program of the script; `reset()` starts a new one, and the previous one will never be
    # built by anyone. Our own "жильё" recipe is written as two programs — as
    # `KIR-L002` dictates ("a staircase owns its own transactions") — and the staircase
    # was disappearing SILENTLY: no refusal, no field. The judge later honestly printed "HAB011:
    # `create_stairs` was never called" and sent the author off to fix a program in
    # which the call IS present.
    #
    # Only non-empty, by the same law as the read ledger: an empty block
    # would read as "nothing was left behind", while a single-program script did not
    # leave anything behind either.
    оставлено = [dict(item) for item in
                 (getattr(result, "left_behind", None) or [])]
    if оставлено:
        receipt["left_behind"] = оставлено
        receipt["left_behind_note_ru"] = (
            "🔴 ПОСТРОЕНА ТОЛЬКО ПОСЛЕДНЯЯ ПРОГРАММА СКРИПТА. Оставлено "
            + str(len(оставлено)) + ": "
            + "; ".join(
                f"«{item.get('intent') or 'без замысла'}» ({item.get('ops')} оп)"
                for item in оставлено[:4])
            + ". `reset()` начинает новую программу, и прежнюю дверь уже не "
              "построит — отправь её отдельным ходом либо собери всё в одну "
              "программу.")
    reads = list(getattr(result, "course_reads", None) or [])
    if reads:
        # WHAT THE COURSE GAVE TO THIS TURN. Only non-empty: "the course was not called" must
        # look like an absence of calls, not like an empty block. In the
        # sink recorded to disk (`coverage_feed.record_course_uptake`) even a
        # zero value travels — there, zero is exactly the main number being measured.
        receipt["course_reads"] = reads
    return receipt


def _script_refusal_result(refusal: Any, receipt: dict, *,
                          turn_id: str = "", query_id: str = "") -> dict:
    """A sandbox refusal outward — typed, with THE MODEL'S LINE NUMBER.

    Not a single frame of ours: it is ONE'S OWN script that needs fixing, and the refusal must show
    the place in it. `render()` already assembles "code: gist / line N: text";
    the fields are duplicated machine-readably, because `err.fix` is assembled from them, and
    not from prose."""
    diagnostic: dict[str, Any] = {
        "code": refusal.code,
        "message_ru": refusal.render(),
        "kind": refusal.kind,
        # WHOSE ERROR THIS IS — as a separate field, not a guess from the code:
        # "author" is fixed by the model, "sandbox" is fixed by us.
        "blame": refusal.blame,
    }
    if refusal.line is not None:
        diagnostic["script_line"] = refusal.line
        diagnostic["script_line_text"] = refusal.line_text
    if refusal.script_frames:
        diagnostic["script_frames"] = list(refusal.script_frames)
    if refusal.detail:
        diagnostic["detail"] = dict(refusal.detail)
    message = refusal.render()

    # 🔴 AN AUTHOR'S REFUSAL IS RECORDED — BEFORE 20.08.2026 IT WAS RECORDED NOWHERE.
    # That day's measurement: the corpus `kir_rejections.jsonl` (2395 lines, window
    # 16.07 → 19.08) carries ZERO lines from the sandbox; `KIR-B004`, `sandbox`, and
    # "sandboxes" occur in it zero times each. This path was returning a
    # typed receipt and never once called the write, so the question "what
    # does the model trip on when writing Python" had NO source AT ALL — and
    # the makeup of the import allowlist had to be declared a DECISION, not a measurement.
    # A separate sink (not the contract feed) with the cause named at the
    # function itself; the source is never written, only its signature.
    try:
        from kir.coverage_feed import record_author_refusal
        from kir.sandbox import allowed_imports_for_env
        record_author_refusal(
            refusal,
            source_digest=str((receipt or {}).get("author_digest") or ""),
            allowed_imports=allowed_imports_for_env(),
            turn_id=turn_id, query_id=query_id)
    except Exception:  # noqa: BLE001 — telemetry must not change the refusal
        logger.debug("author refusal telemetry failed", exc_info=True)

    # 🔴 RECONNAISSANCE IS A THIRD KIND OF ANSWER, AND IT IS NOT A REFUSAL.
    #
    # WHAT THIS BOUGHT. `KIR-B007` was the language's top refusal, five times ahead of the next —
    # 176 of 463 calls (measurement from 17.08). A re-measurement on 18.08 on the nightly
    # rig's corpus through the REAL sandbox: 365 B007 refusals, of which 357 (97.8%)
    # PRINTED a response, and all 8 that stayed silent were deliberately blanked drafts,
    # whose own comment reads "scratch file, not a program".
    # There are ZERO genuine author failures in this bucket.
    #
    # WHAT CHANGES AND WHAT DOES NOT. `ok` stays false: green in this tree
    # is earned by PRODUCING EVIDENCE of a write (`green_is_earned`), and a question
    # has no such evidence and cannot have any. What changes are the NAME and the ACCOUNTING: `refused` is no
    # longer true, `recon` appears, and the `err` block is not stamped at all
    # (see `_stamp_refusal`) — because there was no error.
    #
    # THE OUTCOME IS LEFT UNTOUCHED, AND THIS IS NOT LAZINESS. All three axes of `ProgramOutcome` describe
    # EXECUTION, and reconnaissance never reached execution: `program_not_started()`
    # already tells the exact truth about it. Setting up a fourth axis for a fact about
    # AUTHORSHIP would mean extending a closed algebra with the wrong question.
    if refusal.code == SANDBOX_RECON:
        return _with_outcome({
            "ok": False, "kir": True, "refused": False, "recon": True,
            "stage": "author_script",
            "diagnostics": [diagnostic],
            "message_ru": message,
            "handoff": None,
            "program_source": receipt,
        }, program_not_started())

    следующий_ход = ""
    if refusal.blame == "sandbox":
        # OUR DEFECT — and the model needs to be told what to do, because there is
        # nothing for it to fix. The sandbox cannot utter this phrase: it does not know that
        # the tool has a second input form. The gateway knows, and says so here.
        message += ("\nЭто дефект песочницы, а не скрипта. Ту же программу "
                    "можно прислать полем `program` (операциями) — путь "
                    "исполнения ниже от этого не меняется.")
        diagnostic["message_ru"] = message
        # 🔴 ХОД НАЗЫВАЕТСЯ ИНСТРУМЕНТОМ, А НЕ ТОЛЬКО ПОЛЕМ. Первая редакция
        # говорила «пришли … полем `program`» и не называла ДВЕРЬ — а поле без
        # инструмента не есть ход, который агент может сделать: у него в
        # палитре имена, а не поля. Поймано пином
        # `test_every_refusal_of_the_author_stage_names_a_next_move[sandbox]`.
        следующий_ход = ("это дефект песочницы, а не твоего скрипта: пришли ту "
                         "же программу инструментом `revit_ir`, но полем "
                         "`program` (операциями), а не скриптом — путь "
                         "исполнения от этого не меняется")
    # 🔴 ДВА АДРЕСАТА — ДВА СЛОЯ, И ПУТАТЬ ИХ НЕЛЬЗЯ (13.09.2026, куплено живым
    # ходом владельца). `render()` даёт текст ГЛАЗАМИ МОДЕЛИ: код диагностики,
    # суть и МЕСТО В ЕЁ ИСХОДНИКЕ. Автору это необходимо. Но с 13.09 панель
    # Ревита печатает `message_ru` верхнего уровня ЧЕЛОВЕКУ (V §3 п.1), и в
    # чат владельца уехало, дословно:
    #
    #     KIR-B015: каталог документа не подан этому запуску: спрашивать нечего…
    #     строка 1: print("LEVELS:", [l for l in model.levels()])
    #
    # — код прибора и СТРОКА ЧУЖОГО ИСХОДНИКА в чате человека, который просил
    # огородить электрощитовую. Это ровно та «свалка в чат», на которую владелец
    # ругался 08.09, только с другой стороны.
    #
    # НИЧЕГО НЕ ПОТЕРЯНО, И ЭТО ГЛАВНОЕ. Полный текст автора — с кодом, номером
    # и текстом строки — уже лежит в `diagnostics[0]` (`message_ru`,
    # `script_line`, `script_line_text`, `script_frames`) и приезжает модели в
    # той же квитанции. Наверх поднимается СУТЬ (`refusal.message_ru` — проза
    # без кода и без исходника), а место остаётся прибору. Тот же раздел, что
    # `program_card`: человеку — предмет, прибору — `details`.
    человеку = str(getattr(refusal, "message_ru", "") or "").strip() or message
    return _stamp_next_move(_with_outcome({
        "ok": False, "kir": True, "refused": True, "stage": "author_script",
        "diagnostics": [diagnostic],
        "message_ru": человеку,
        "handoff": None,
        "next_ru": следующий_ход,
        "program_source": receipt,
    }, program_not_started()))


def _stamp_authorship(result: Any, authored: _AuthoredInput) -> Any:
    """Stamp the source's signature on THE RECEIPT. Additive and fail-open.

    One place for all outcomes, rather than editing every `return`, using the same trick
    that stamps the `err` block: a list of places can be forgotten, a structural rule
    cannot."""
    try:
        if (not authored.from_script or not isinstance(result, dict)
                or not authored.receipt):
            return result
        result.setdefault("program_source", authored.receipt)
    except Exception:  # noqa: BLE001 — the receipt must not break the turn
        logger.debug("KIR authorship stamping failed", exc_info=True)
    return result


#: The input field "rehearse and DO NOT WRITE". A third mode alongside `example`, and for the
#: same reason: a call with no write is legitimate, and refusing it on form grounds would be a lie.
_REHEARSE_FIELD = "rehearse"


def _rehearse_only(args: Any) -> bool:
    """A call to "show what will and will NOT be checked" — the program exists, there is no write.

    The same strictness as `_example_only`: `rehearse` TOGETHER with an intent
    to write would mean the caller wants both in one turn, and silently
    picking one would mean deciding for them. Here, however, a program is needed —
    there is nothing to rehearse without it — so the presence of ANY form is checked.
    """
    if not isinstance(args, dict):
        return False
    if not args.get(_REHEARSE_FIELD):
        return False
    return (args.get("program") is not None
            or args.get(_SCRIPT_FIELD) is not None
            or "ops" in args)


#: The input field "what have I already created" — a reading mode, no write.
_CREATED_FIELD = "created"


def _created_only(args: Any) -> bool:
    """A call to "show the log of what was created". There must NOT be a program.

    As with `example`: together with a program this is two intents in one turn, and silently
    picking one would mean deciding for the caller.
    """
    if not isinstance(args, dict):
        return False
    if not args.get(_CREATED_FIELD):
        return False
    return (args.get("program") is None
            and args.get(_SCRIPT_FIELD) is None
            and "ops" not in args)


def _op_kinds_of(planned: Any) -> dict[str, str] | None:
    """`{op id -> op NAME}` from the plan — and NOTHING more (F-297).

    From the program only the KIND of operation is taken, and nothing else: what an operation created
    is stated by the bridge's response, not by the plan. Taking declared ops from the plan would mean
    recording as created something that was rolled back.

    🔴 ALL OR NOTHING. On any surprise, `None` is returned, not a
    partial map: a partial one would drop the rows of ops that were not
    found in it — that is, it would lose the ids of live elements, and that is exactly the
    harm that fix F-297 prevents from the other side.
    """
    try:
        ops = getattr(planned, "ops", None)
        if not ops:
            return None
        out: dict[str, str] = {}
        for op in ops:
            op_id = getattr(op, "op_id", None)
            op_name = getattr(op, "op_name", None)
            if not op_id or not op_name:
                return None
            out[str(op_id)] = str(op_name)
        return out or None
    except Exception:  # noqa: BLE001 — the registry matters more than the map's completeness
        return None


def _created_answer() -> dict:
    """The log of what this session created. Writes nothing and never goes to Revit."""
    from kir import created_ledger as _cl
    # The document is asked for TOGETHER with the device: the registry is shared across the fleet, and the
    # owner routinely has two Revits open (F-299).
    got = _cl.created_for_session(_turn_device_id() or "",
                                  _turn_journal_document())
    # 🔴 `ok` IS ABOUT WHETHER WE COULD LOOK, NOT ABOUT WHETHER EVERYTHING IS INTACT
    # (30.08.2026, F-298). Skipped broken lines are named in `refusal` and do not
    # make the response unsuccessful: the lines that do exist ARRIVED. Previously, one
    # corrupted byte at the end of the file both zeroed out the response and dropped `ok`.
    _посмотрели = bool(got.get("rows")) or not got.get("refusal")
    out: dict[str, Any] = {
        "ok": _посмотрели,
        "kir": True,
        "wrote_nothing": True,
        "created_ledger": {
            "schema": _cl.SCHEMA_VERSION,
            "created_count": got.get("created_count", 0),
            "rows": got.get("rows", ()),
            # Lines with no binding to a device are not ours and are not returned.
            # They are counted separately, so that "they don't exist" and "they exist, but foreign" stay distinct.
            "unattributable": got.get("unattributable", 0),
            # Lines from THIS device, written BEFORE the document key
            # was set up: they are ours, but which building they are about is unknown.
            # It sits alongside `unattributable`, because this is a THIRD kind of emptiness,
            # not a variant of the second.
            "unscoped_to_document": got.get("unscoped", 0),
        },
    }
    if got.get("refusal"):
        out["created_ledger"]["refusal"] = got["refusal"]
    # 🔴 ALWAYS SET. The registry is written BEFORE acceptance — it is acceptance itself that declares
    # failure in `KIR-A006`/`KIR-A007` on a write that DID take place. So an id here
    # means "Revit built this", not "the program accepted this".
    out["created_ledger_note_ru"] = (
        f"создано по журналу: {got.get('created_count', 0)} элементов. "
        "🔴 «в журнале» НЕ равно «принято»: запись идёт до приёмки, и вердикта "
        "по этим элементам журнал не знает"
        + (f". Строк без привязки к устройству: {got['unattributable']} — "
           "они написаны до заведения привязки и никому не приписываются"
           if got.get("unattributable") else "")
        + (f". Строк этого устройства БЕЗ ключа документа: {got['unscoped']} "
           "— они написаны до заведения ключа, и про какое здание, не знает "
           "никто; в ответ они не попали"
           if got.get("unscoped") else "")
        # TWO DIFFERENT KINDS IN ONE FIELD (F-298): with non-empty lines this is
        # a warning "not everything was read", with empty ones it is a genuine refusal.
        # The text must say which of the two it is, otherwise the reader will mistake
        # a partial answer for a failure.
        + ((f". ПРОЧИТАНО НЕ ВСЁ: {got['refusal']} — показанные строки годны"
            if got.get("rows") else
            f". ПОСМОТРЕТЬ НЕ УДАЛОСЬ: {got['refusal']}")
           if got.get("refusal") else ""))
    return out


def _rehearsal_block(program: Any) -> Optional[dict]:
    """A PROGRAM REHEARSAL: what will be checked and what will NOT — without a single round trip.

    🔴 WHY, BY A MEASUREMENT ON 18–19.08.2026 ON A LIVE BENCHMARK. The model worked a shift
    on KIR in a live Revit and built a terraced tower. Two out of three major
    failures were not geometry errors but obligations that NEVER RAN, and
    the silence about it:

      * 420 columns landed at 2500 mm instead of 3600–4500. The obligation "top
        constraint == resolved top_level" is CONDITIONAL: required only if the author
        passed `top_level`. The author omitted it — the witness stayed silent, acceptance
        accepted it, and three audits did not see it;
      * 540 beams out of 540 landed at z=0 while "Floor 5" was written: for `create_beam`
        the level is derived by Revit from the curve's elevation, the argument decides nothing.

    Both classes are DERIVABLE BEFORE THE WRITE from machine tables that already sit in the
    tree — and sat right where the program's author does not look. This showroom does not
    mine any new knowledge, it just stops losing what already existed.

    🔴 THREE CAUSES OF SILENCE ARE KEPT SEPARATE, AND THIS IS NOT PEDANTRY. One word for three
    different troubles is not a measurement: `gate` is fixed by the author with their own line, `named` is
    a project decision with a reason, `thin_axes` is a hole in the language that the author
    cannot close at all. Merging them into one list would mean asking the author to fix
    something that is not theirs.

    🔴 NOISE IS COLLAPSED, NOT DISCARDED. A skipped `arc` on a straight wall is normal, but
    "did not show it at all" and "showed it as one line with a count" are different things.

    Returns `None` only if the rehearsal physically could not be assembled (no
    program, an import failed). An empty rehearsal returns a block with ALL
    lists empty: silence would be indistinguishable from "it was never checked", and that is not the case.
    """
    if not isinstance(program, dict):
        return None
    try:
        # The import is functional, and this is where it comes from: `tools/` depends on `kukai/` (38
        # files), the reverse direction is a single case in this tree. The showroom lives
        # here, while the ONE carrier of the decompile logic lives there; a copy of its logic would
        # be exactly the defect this showroom exposes: a value
        # declared in one place and read in another, with nothing forcing them to
        # agree. The debt is named: the decompiler belongs in `kir/`, the tool should be a thin
        # printer on top of it.
        from kir.rehearsal import rehearse  # noqa: PLC0415
        r = rehearse(program)
    except Exception:  # noqa: BLE001 — the showroom has no right to break the turn
        logger.debug("KIR rehearsal failed (fail-open)", exc_info=True)
        return None
    quiet = r.get("optional_unused") or []
    return {
        "schema": "kir-rehearsal/1",
        "ops_declared": r.get("ops_declared"),
        # The count is AFTER expanding `create_group.members × placements`. For the
        # benchmark's programs, 4220 declared operations produced 7206 elements, and 2986 of them
        # were invisible to the instrument — the entire building frame lived inside groups.
        "elements_total": r.get("elements_total"),
        "value_overwritten_by_revit": r.get("authority_ignored") or [],
        "will_not_be_checked": {
            "gate": r.get("authority_transfer") or [],
            "named": r.get("named_absences") or {},
            "thin_axes": r.get("thin_axes") or {},
        },
        "unwitnessed_ops": r.get("unwitnessed_ops") or [],
        "optional_unused": {"obligations": sum(q.get("count", 0) for q in quiet),
                            "reasons": len(quiet)},
    }


def _rehearsal_note_ru(block: Optional[dict]) -> str:
    """The human-readable line for the rehearsal. It is NEVER empty: see `_rehearsal_block`."""
    if not isinstance(block, dict):
        return ""
    parts: list[str] = []
    for d in block.get("value_overwritten_by_revit") or []:
        parts.append(
            f"🔴 {d.get('op')}.{d.get('param')} ×{d.get('count')}: присланное "
            f"значение Ревит перепишет — оно не решает ничего")
    # ONE CAUSE — ONE LINE. Omitting `top_level` on a wall lifts TWO
    # obligations AT ONCE (the top constraint and the vertical span), and printing them
    # as two nearly identical paragraphs means paying in bytes for one thought.
    _gate: dict[tuple, list] = {}
    for g in (block.get("will_not_be_checked") or {}).get("gate") or []:
        key = (g.get("op"), g.get("because"), g.get("transfers"), g.get("count"))
        _gate.setdefault(key, []).append(str(g.get("clause")))
    for (op, because, transfers, count), clauses in _gate.items():
        parts.append(
            f"🔴 {op} ×{count}: {because} — не будет проверено: "
            + "; ".join(clauses)
            + f". Вместо программы решает: {transfers}")
    thin = (block.get("will_not_be_checked") or {}).get("thin_axes") or {}
    if thin:
        parts.append("под присмотром ровно одна ось у: " + ", ".join(
            f"{op} ({axis})" for op, axis in sorted(thin.items())))
    if not parts:
        parts.append("нечего: всё, что реестр умеет проверять у этих операций, "
                     "будет проверено")
    q = block.get("optional_unused") or {}
    if q.get("obligations"):
        parts.append(f"необязательные возможности не использованы — "
                     f"{q['obligations']} обязательств по {q['reasons']} "
                     f"поводам (норма, не находка)")
    return " · ".join(parts)


def _stamp_rehearsal(result: Any, program: Any) -> Any:
    """Stamp the rehearsal onto THE RECEIPT — one place for all outcomes.

    It is set on refusal too: a refusal plus a rehearsal is exactly that "before the write" case
    when the author can still fix the line. Additive and fail-open — the showroom has no
    right to break the turn, since at this line the transaction may already be committed.
    """
    try:
        if not isinstance(result, dict):
            return result
        block = _rehearsal_block(program)
        if block is None:
            return result
        result.setdefault("rehearsal", block)
        note = _rehearsal_note_ru(block)
        if note:
            result.setdefault("rehearsal_note_ru", note)
    except Exception:  # noqa: BLE001
        logger.debug("KIR rehearsal stamping failed", exc_info=True)
    return result


#: The self-check ceiling in OPERATIONS. The same order as the verdict about the building
#: (`live/verdict.py`), and for the same reason: `check_ops` computes in Python under the
#: GIL. A measurement on 01.09.2026 on a six-operation apartment — 5.9 ms on a warm
#: call, meaning ~1 ms per operation; at 1200 operations that is a second, and
#: paying it on EVERY turn is not acceptable. Exceeding the ceiling IS NAMED (`_self_check_block`
#: returns silence with a reason), rather than being dropped silently.
_SELF_CHECK_OPS_CAP = 1200


#: The ceiling for listing bodies in the receipt. A count costs bytes, a list costs a lot.
_FREE_GEOMETRY_LIST_CAP = 6


def _free_geometry_the_judge_missed(program: Any) -> Optional[dict]:
    """BODIES THE JUDGE CANNOT SEE — INTO THE RECEIPT, NOT ONLY INTO `design_check()`.

    🔴 WHY HERE, AND NOT ONLY IN THE COURSE — BY THE SAME MEASUREMENT THAT SET UP THE ENTIRE
    SELF-CHECK. `design_check()` was called in THREE out of 323 live scripts. That means
    knowledge that lives only behind this call never reaches the model. And by the owner's word
    from 02.09.2026, the language's main user is not a human writing Python but the
    MULTI-AGENT ENVIRONMENT, and it reads THE RECEIPT.

    Without this block, free form arrives over the wire like this: the judge applied
    not a single rule, `silent_because` explains that it did not
    read the program — and NOT A WORD about the program containing four bodies that would have become
    walls with a single call. The silence looks like "there is nothing to say".

    THE COST IS MEASURED, NOT ESTIMATED (02.09.2026): a one-time warm-up of `kir.promote` at the
    PARENT costs 170 ms and +8 modules on top of `kir.serving`; reading 20 bodies costs 4.21 ms per
    turn. For comparison, the already-accepted cost of the self-check itself is 457 ms once and
    5.9 ms per turn.

    ⚠️ A LAYERING DEBT IS NAMED: `kir.promote` pulls in `kir.course.rhino`, meaning the service
    gains an edge into the COURSE package that it did not have before. The pure reading of
    geometry (`faces`, `section`, `_loft_mesh`) lives inside the course — this is
    a carrier on a foreign floor, and moving it lower will remove the edge entirely. The import
    is lazy: at the PARENT this is legitimate (in the sandbox it would not be allowed — there `chroot`
    is applied after warm-up, and a lazy import there would hit the author with someone else's refusal code).
    """
    if not isinstance(program, dict):
        return None
    try:
        from kir import promote as _promote  # noqa: PLC0415
        записи = _promote.unpromoted(program.get("ops"))
    except Exception:  # noqa: BLE001 — the showroom has no right to break the turn
        logger.debug("KIR free-geometry read failed (fail-open)", exc_info=True)
        return None
    if not записи:
        return None
    роды: dict[str, int] = {}
    причины: dict[str, int] = {}
    непрочитано = 0
    for z in записи:
        род = z.get("role")
        if род:
            роды[str(род)] = роды.get(str(род), 0) + 1
        elif z.get("unreadable"):
            непрочитано += 1
        else:
            # A KEY, not text: see `_codes` below — the same receipt law.
            ключ = str(z.get("reason_key") or "не названа")
            причины[ключ] = причины.get(ключ, 0) + 1
    out: dict = {"bodies": len(записи)}
    if роды:
        out["would_be"] = dict(sorted(роды.items()))
    if причины:
        out["not_native"] = dict(sorted(причины.items()))
    if непрочитано:
        # Bodies whose shape the environment cannot read. Staying silent about them would mean
        # gaining confidence precisely from one's own inability.
        out["unread"] = непрочитано
    имена = [str(z.get("id") or z.get("op")) for z in записи]
    out["ids"] = имена[:_FREE_GEOMETRY_LIST_CAP]
    if len(имена) > _FREE_GEOMETRY_LIST_CAP:
        out["ids_truncated"] = len(имена) - _FREE_GEOMETRY_LIST_CAP
    return out


def _session_datums() -> list[dict]:
    """Datums of THIS session: levels and grids declared by earlier turns.

    🔴 WHY THE SELF-CHECK NEEDS OTHER OPS' DATA (measurement on a live Revit, 03.09.2026).
    The judge takes elevations only from `create_level` in THE SAME program, while a live
    write almost always builds on a level that ALREADY EXISTS — this argument
    is recorded at `built_verdict.datum_ops` back on 17.08 and closed there for the judge
    of the re-read. For the self-check it had not been closed: an apartment with five
    built rooms was getting "SELF-CHECK DID NOT HAPPEN: the judge applied
    not a single rule out of 20 (HAB000: model has no rooms)" — that is,
    the most-read line of the receipt was silent on the product's MAIN use case.

    THE BOUNDARY IS NAMED: what lands here are datums declared by THIS SESSION. A level
    that stood in the document before it is unknown to the journal, and the self-check
    still stays silent about it — honestly, via the same `silent_because`.
    """
    собрано: list[dict] = []
    имена: set[str] = set()

    def взять(ops: Any) -> None:
        for op in (ops or ()):
            if not isinstance(op, Mapping):
                continue
            имя = str(op.get("name") or "")
            if имя and имя in имена:
                continue
            if имя:
                имена.add(имя)
            собрано.append(dict(op))

    try:
        slot = _TURN_JOURNAL_SLOT.get()
        if slot is not None:
            from kir.live import journal as _live_journal    # noqa: PLC0415
            взять(getattr(_live_journal.get(slot[0]), "datums", None))
    except Exception:  # noqa: BLE001 — the showroom has no right to break the turn
        logger.debug("session datums unavailable", exc_info=True)
    try:
        снимок = _TURN_GROUND_SNAPSHOT.get()
        if снимок is not None:
            from kir import built_verdict as _built          # noqa: PLC0415
            взять(_built.datum_ops(снимок))
    except Exception:  # noqa: BLE001 — the same law
        logger.debug("document datums unavailable", exc_info=True)
    return собрано


def _self_check_block(program: Any) -> Optional[dict]:
    """A VERDICT ABOUT WHAT WAS DECLARED — on every door and on every outcome.

    🔴 WHY, BY A MEASUREMENT ON 01.09.2026. The sandbox's pointer tells the model verbatim:
    "`design_check()` — a verdict on the design's fitness without Revit. Call it BEFORE
    sending". Across 323 of the owner's live scripts (the `kir_course_uptake` feed, window
    23–26.08) it called it in **3 scripts**, `preview` in 1, `score` in 0.
    The constitution's main metric — "how many times checkability CHANGED the model's
    decision" — stands at 17 out of 560 turns on the same owner's logs.

    There is one conclusion from this pair of numbers: **a channel that must be CALLED does not work**.
    The capability is built, declared, and unused. So the environment answers
    ON ITS OWN, unasked, and puts the answer where the model already reads anyway — into the
    receipt, next to the rehearsal.

    ═══ THIS IS NOT A SECOND JUDGE OF ONE QUESTION. THE SUBJECTS ARE DIFFERENT ═══

        `building` (`_stamp_building_verdict`)  a verdict about the BUILDING, assembled
                                               by the session's JOURNAL; the chat door
        `self_check` (here)                    a verdict about the PROGRAM that
                                               the author DECLARED in this turn

    The first answers "what did everything built come together into", the second — "is what
    you just wrote any good". The first requires a journal and therefore the chat door; the second
    requires neither a journal, nor Revit, nor execution — it judges the text, and is therefore
    legitimate on ANY door and for ANY outcome, including a refusal. A refusal plus
    a verdict about what was declared is exactly that "before the write" case, when the author can still
    fix the line.

    WHY HERE, AND NOT IN THE SANDBOX — DECIDED BY MEASUREMENT, NOT TASTE (01.09.2026).
    The first idea was to append the answer into the child's `stdout`. The cost was measured:

        child     +431 ms ON EVERY RUN and 555 new modules — because
                  `os.chroot` into an empty root is applied AFTER warm-up, and
                  importing `kir.design_check`/`kir.preview` there afterward is
                  impossible: they would have to be warmed up EVERY TIME, including reconnaissance turns
        child     +2430 characters against the author's ceiling `MAX_STDOUT_CHARS`
                  of 4000 — meaning the environment would eat 60% of the author's feedback
        parent    457 ms ONCE per the service's lifetime (modules are lazy here too),
                  then 5.9 ms per turn afterward

    And a third thing that settles it for good: at the parent, the auto-answer does NOT PASS through
    `course._note_read`, meaning the read ledger stays THE AUTHOR'S, and the number
    "3 out of 323" stays comparable with tomorrow's. An auto-answer in the sandbox would
    make it 323 out of 323 by construction and would destroy the very subject being measured.

    SILENCE IS ALWAYS NAMED. A return with no `verdict` key does not mean
    "empty", but a named reason in `silent_because`: an empty program, exceeding the
    ceiling, no judge present, a decompile refusal. The reader must be able to tell "it was judged
    and nothing was found" apart from "it was not judged" — that is the named defect of this tree.
    """
    if not isinstance(program, dict):
        return None
    ops = program.get("ops")
    if not isinstance(ops, list) or not ops:
        return None
    if len(ops) > _SELF_CHECK_OPS_CAP:
        return {"schema": "kir-self-check/1",
                "silent_because": f"операций {len(ops)} при потолке "
                                  f"{_SELF_CHECK_OPS_CAP}: самопроверка не "
                                  f"запускалась"}
    try:
        from kir import design_check as _dc  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return {"schema": "kir-self-check/1",
                "silent_because": f"модуль вердикта недоступен "
                                  f"({type(exc).__name__})"}
    # Session datums are fed IN BEFORE the turn's operations — the same way
    # `built_verdict` feeds them to both of its sides. They do not count against the ceiling
    # (it is about the AUTHOR's program), so they are checked separately and are silently
    # dropped if their sum exceeds it: a verdict without datums is poorer, but
    # honest, whereas a ceiling refusal caused by OUR OWN ops would be a lie about the program.
    датумы = [op for op in _session_datums()
              if str(op.get("id") or "") not in {str(o.get("id") or "")
                                                 for o in ops}]
    судимое = program
    if датумы and len(ops) + len(датумы) <= _SELF_CHECK_OPS_CAP:
        судимое = {**program, "ops": датумы + list(ops)}
    try:
        v = _dc.check_ops(судимое, building_id="программа этого хода")
    except _dc.VerdictInputError as exc:
        # The program's form does not suit the judge. This is AN ANSWER, not a breakage: we write
        # the reason in its own words, not in our own retelling.
        return {"schema": "kir-self-check/1",
                "silent_because": str(exc)[:_NOTE_CAP]}
    except _dc.DesignCheckUnavailable as exc:
        # The v1 path gives neither a three-valued verdict nor coverage; silently returning
        # it in place of the stage's verdict would mean substituting the claim.
        return {"schema": "kir-self-check/1",
                "silent_because": f"судья недоступен: {exc}"[:_NOTE_CAP]}
    except Exception as exc:  # noqa: BLE001 — the showroom has no right to break the turn
        logger.debug("KIR self-check failed (fail-open)", exc_info=True)
        return {"schema": "kir-self-check/1",
                "silent_because": f"самопроверка сорвалась "
                                  f"({type(exc).__name__})"}
    report = getattr(v, "report", None)
    witness = getattr(v, "witness", None)
    # 🔴 "0 OF 20 RULES" IS THE JUDGE'S SILENCE, NOT A VERDICT ON THE BUILDING, AND
    # PRESENTING IT AS A VERDICT MEANS TEACHING THE MODEL SOMETHING WRONG (measurement from 01.09.2026).
    #
    # A run over 73 goldens: all 73 receive a verdict, and almost all carry
    # `blocking: HAB000` with `rules_applied: 0`. HAB000 says verbatim
    # "model has no rooms; nothing was verified" — meaning the judge did NOT READ
    # the program, rather than condemning it. The reason is legitimate and named in `course`
    # (`_hab000_names_the_real_cause`): the judge takes elevations only from
    # `create_level` of THIS SAME program, while the model builds the building IN PARTS —
    # `create_stairs` must be the only op of its own program (KIR-L002).
    # So a partial program would get a BLOCKING verdict on the most
    # readable line of the receipt, while being entirely correct.
    #
    # This is our named class in pure form: a plausible number is more dangerous than zero.
    # Zero rules raises a question; "BLOCKING: HAB000" closes it with a wrong
    # answer.
    #
    # WHY THE REASON'S TEXT IS NOT COPIED HERE. The full explanation with the fix
    # ("declare the levels within this same program") is already written ONCE, in
    # `course._hab000_names_the_real_cause`, and is printed to the author when
    # `design_check()` is called. A second copy would drift apart from the first — the named defect
    # of this tree — and `serving` moreover does not import `kir.course` in even
    # a single line, and setting up this edge for the sake of text is not allowed.
    applied = getattr(v, "rules_applied", None)
    if not applied:
        причина = ""
        for row in (getattr(report, "blocking", None) or ()):
            msg = getattr(row, "msg", "") or ""
            причина = f"{getattr(row, 'rule_id', '?')}: {msg}"
            break
        тихо = {"schema": "kir-self-check/1",
                # How many session datums were fed in: without this number, "the judge did not
                # read" is indistinguishable from "the judge was given nothing to read".
                "datums_seen": len(датумы),
                "silent_because": (
                    f"судья не применил ни одного правила из "
                    f"{getattr(v, 'rules_total', '?')} — программу он не "
                    f"прочитал, а не осудил"
                    + (f" ({причина})" if причина else "")
                    + ". Полная причина и следующий ход — у `design_check()`"
                )[:_NOTE_CAP]}
        # 🔴 AND THIS IS EXACTLY WHERE THE BLOCK IS NEEDED MOST. A program made of
        # free-form geometry alone ALWAYS gives "0 rules": the judge reads the kinds
        # of operations, and it has no BIM bodies. Silence without this line reads as
        # "nothing to say", even though there is something to say and a fix follows from it.
        свободная = _free_geometry_the_judge_missed(program)
        if свободная:
            тихо["free_geometry"] = свободная
        return тихо
    # CODES, NOT TEXTS. Violation texts live with the judge and are printed in full by
    # `render_verdict`; here it is the receipt, and it is trimmed first. The code distinguishes
    # findings, text only lengthens it.
    def _codes(rows: Any) -> list[str]:
        out: list[str] = []
        for r in (rows or ()):
            code = getattr(r, "rule_id", None)
            if code and code not in out:
                out.append(str(code))
        return out
    block: dict = {
        "schema": "kir-self-check/1",
        "source": "declared_program",
        "verdict": getattr(getattr(v, "verdict", None), "value",
                           str(getattr(v, "verdict", ""))),
        "rules_applied": getattr(v, "rules_applied", None),
        "rules_total": getattr(v, "rules_total", None),
        "blocking": _codes(getattr(report, "blocking", None)),
        "warnings": _codes(getattr(report, "warnings", None)),
    }
    counts = getattr(witness, "counts", None)
    if isinstance(counts, dict) and counts:
        # What the judge ACTUALLY READ. Without this line, "7 of 20 rules" is indistinguishable
        # from "the program is empty": the numbers are the same, the subjects are different.
        block["read"] = {k: v2 for k, v2 in sorted(counts.items()) if v2}
    свободная = _free_geometry_the_judge_missed(program)
    if свободная:
        block["free_geometry"] = свободная
    return block


def _self_check_note_ru(block: Optional[dict]) -> str:
    """The model's line about the self-check. Short: it sits in the HEAD of the receipt.

    The head is what survives truncation (`_order_receipt`), and space in it
    is paid for in bytes on every turn. So here go the summary, the rule count, and CODES, while
    the breakdown lives in the block next to it.
    """
    if not isinstance(block, dict):
        return ""

    def _свободная() -> str:
        """One short remark about what the judge could not see. Or empty."""
        fg = block.get("free_geometry")
        if not isinstance(fg, dict) or not fg.get("bodies"):
            return ""
        части = [f"СУДЬЯ НЕ ВИДЕЛ СВОБОДНОЙ ГЕОМЕТРИИ: тел {fg['bodies']}"]
        стало = fg.get("would_be")
        if стало:
            части.append("после `promote(форма)` это "
                         + ", ".join(f"{k} {v}" for k, v in стало.items()))
        if fg.get("unread"):
            части.append(f"формы {fg['unread']} среда не читает")
        return " · " + " · ".join(части)

    silent = block.get("silent_because")
    if silent:
        return f"САМОПРОВЕРКА НЕ СОСТОЯЛАСЬ: {silent}" + _свободная()
    итог = {"pass": "ПРИГОДЕН", "fail": "НЕ ПРИГОДЕН",
            "not_evaluated": "ИТОГ НЕ ОЦЕНЕН"}.get(
        str(block.get("verdict")), str(block.get("verdict")))
    parts = [f"САМОПРОВЕРКА ЗАЯВЛЕННОГО: {итог}; правил "
             f"{block.get('rules_applied')} из {block.get('rules_total')}"]
    if block.get("blocking"):
        parts.append("блокирующие: " + ", ".join(block["blocking"]))
    if block.get("warnings"):
        parts.append("предупреждения: " + ", ".join(block["warnings"]))
    parts.append("судится ЗАЯВЛЕННОЕ, не построенное")
    return " · ".join(parts) + _свободная()


def _stamp_self_check(result: Any, program: Any) -> Any:
    """Stamp the verdict about what was declared onto THE RECEIPT — one place for all outcomes.

    `setdefault`, not an assignment: if the body ever starts judging
    what was declared on its own, its word will be closer to the subject and will take precedence.
    """
    try:
        if not isinstance(result, dict):
            return result
        block = _self_check_block(program)
        if block is None:
            return result
        result.setdefault("self_check", block)
        note = _self_check_note_ru(block)
        if note:
            result.setdefault("self_check_note_ru", note)
    except Exception:  # noqa: BLE001 — the showroom has no right to break the turn
        logger.debug("KIR self-check stamping failed", exc_info=True)
    return result


def _turn_journal_document() -> str:
    """The document under which THIS turn's journal lives.

    🔴 A SEPARATE NAME, NOT A DIRECT CALL TO `_turn_document_title`, AND HERE IS WHY.
    TWO carriers know the turn's title, and they appear at DIFFERENT TIMES:

        `_turn_document_title()`                   declared by the door/plugin,
                                                 available IMMEDIATELY
        `_snapshot_document_fingerprint(...).title`  `Document.Title` FROM THE BRIDGE,
                                                 available AFTER the round trip for the snapshot

    The journal is written EARLIER than the snapshot (`publish` sits higher in the body of
    `_handle_revit_ir_inner` than the fingerprint), so the bridge's title is
    physically unavailable here, and there is nothing to substitute for it. This is a NAMED boundary, not an
    oversight: trust has to be placed in whoever CHOSE the window — exactly the same
    carrier that has held the document choice for the building index and for the
    `/admin/kir/run` door since 24.08.2026.

    WHAT THIS DOES NOT CLOSE, and this must be said out loud: if the declared
    title diverges from the bridge's, the journal will end up under a FOREIGN document, and
    this is not visible here. Cross-checking the two carriers is separate work, and it has NOT
    been done; see `kir/tests/test_document_identity_is_not_the_device.py`.
    """
    return _turn_document_title()


def _turn_document_identity() -> str:
    """THE IDENTITY of this turn's document — the thing an identically-named neighbor lacks.

    🔴 WHY IT WAS NEEDED AT ALL (08.09.2026, the owner's live Revit).
    The journal key was `(device, document NAME)`, and `Проект1` is the default name of
    EVERY new Revit document. The owner opened a NEW Revit, and
    the empty `Проект1` inherited 194 programs from a DIFFERENT document a week
    old («Сарай», «Кровля сарая»): on "make a cube" the preview drew 98
    elements of a foreign building. In full — in the docstring of `journal.doc_key_for`.

    WHERE THIS COMES FROM, AND THIS IS VERIFIED FROM THE PLUGIN'S SOURCE, NOT ASSUMED.
    The plugin already computes the document's identity itself and already sends it in the
    socket context — `ExecutionContextGuard.ComputeDocumentKey` (`Kukai.Revit.Bridge/
    Execution/ExecutionContextPrecondition.cs:275`): sha256 of
    `project-information:<ProjectInformation.UniqueId>` and `path:<PathName>`.
    This is exactly what was asked for: two documents named `Проект1` have different
    `UniqueId`s, while a reopened instance of the same building has the same one. The field reaches
    `_session_contexts[ws_id]` without loss (`ws_registry._handle_context`
    puts a full copy of the sent context there), so NOTHING NEW IS REQUIRED FROM
    THE PLUGIN.

    THE ORDER OF SOURCES AND WHY IT IS EXACTLY THIS:
      1. `document_key` — the only carrier that SURVIVES REOPENING
         the document. It is exactly what is needed: the journal must be findable when the building is opened
         again.
      2. `document_path` — the identity of a saved document, for when the plugin
         is old and does not send `document_key`. Worse than the first (empty for an
         unsaved document), but better than the name.
      3. EMPTY — "by name, without identity", that is, the previous behavior.
         Same-name collisions are then NOT cured, and the journal says so out loud
         (`journal.FOREIGN_JOURNAL_REFUSAL`), rather than pretending to be healthy.

    WHAT IS DELIBERATELY ABSENT HERE: `document_instance_key`. It is the identity of ONE
    OPENING SESSION (a runtime GUID on the `Document` object), and a reopened building
    would get a new key — the journal would be lost every time Revit closed.
    The cure is worse than the disease.
    """
    ctx = _turn_session_context()
    if not ctx:
        return ""
    # There is no document at all — there is nowhere for an identity to come from, and inventing
    # one is not allowed: "no document" and "a document we know nothing about" are
    # two different facts.
    if ctx.get("has_document") is False:
        return ""
    execution = ctx.get("execution_context")
    if not isinstance(execution, Mapping):
        execution = {}
    document_key = str(ctx.get("document_key")
                       or execution.get("document_key") or "").strip()
    if document_key:
        # 16 hex digits from the plugin's sha256: the key travels into the log, into the
        # store, and into the receipt, and the full 64 digits would make them unreadable.
        # 64 bits with dozens of documents per device — a collision is
        # practically impossible, and the cost of a collision is the same as it was BEFORE
        # the fix, not a new one.
        return "dk:" + document_key.lower()[:16]
    path = str(ctx.get("document_path") or "").strip()
    if path:
        import hashlib as _hashlib
        # The same normalization as the plugin's (`Normalize`): separators and
        # case do not make it a different document.
        stable = path.replace("\\", "/").casefold()
        return "path:" + _hashlib.sha256(
            stable.encode("utf-8")).hexdigest()[:16]
    return ""


#: THE NAME OF THE MISMATCH. Set up as a string, not assembled on the spot: it is a code
#: that is read from outside, and one assembled from pieces would drift apart silently.
DOCUMENT_IDENTITY_MISMATCH = "socket_document_is_not_the_grounded_document"


def _document_identity_crosscheck(fingerprint: Any) -> Optional[dict]:
    """Cross-check the SOCKET's document against the BRIDGE's document. `None` means there is nothing to check.

    🔴 "NOT DONE" ITEM #5 OF WAVE 9, VERBATIM: "After grounding, the turn has on hand
    `project_uid` — the document's exact identity. There is nothing to cross-check it against `dk:` from
    the socket context with, and the mismatch is silent today." It is silent exactly in
    the class of case that is more costly than all others in this tree: the journal is kept
    against the WINDOW's document, while the program writes into the document that THE BRIDGE read.
    If the two diverge, the human gets a confident, correctly-looking answer ABOUT
    A DIFFERENT BUILDING (`test_a_journal_belongs_to_a_document_not_to_a_name`).

    🔴 WHAT IS MISSING HERE AND WHY. `dk:` is the PLUGIN's sha256
    (`ExecutionContextGuard.ComputeDocumentKey`) of
    `project-information:<UniqueId>` and `path:<PathName>`. It CANNOT be recomputed from
    `DocumentFingerprint.project_uid`: the exact byte assembly on our
    side is unknown, and an "approximately the same" assembly would produce a mismatch on
    matching documents — that is, an instrument crying wolf at something healthy. So
    what is cross-checked is NOT the hash but the two values that both sides carry EXPLICITLY:

      1. `path:` — computed by US (source #2, `_turn_document_identity`), and
         the bridge's `path_name` is run through the SAME normalization. This is an exact
         equality: both sides are ours.
      2. PATH and TITLE — the socket context's `document_path`/`document_name`
         against the bridge's `path_name`/`title`. Different paths mean different documents,
         whatever they are keyed by.

    An unsaved document (empty `path_name`) is cross-checked by title: this is
    weaker, and so the outcome carries `field` rather than a bare "mismatch".

    THE OUTCOME IS A WARNING, NOT A TURN REFUSAL. A held program writes
    nothing; taking it away from the human over a mismatch they do not yet know about
    would mean curing silence with lost work.
    """
    title = str(getattr(fingerprint, "title", "") or "")
    path_name = str(getattr(fingerprint, "path_name", "") or "")
    if not title and not path_name:
        return None
    ctx = _turn_session_context()
    if not ctx:
        return None

    def _norm(value: Any) -> str:
        return str(value or "").strip().replace("\\", "/").casefold()

    сокет_путь = _norm(ctx.get("document_path"))
    мост_путь = _norm(path_name)
    сокет_имя = str(ctx.get("document_name") or "").strip()
    if сокет_путь and мост_путь:
        поле, слева, справа = "document_path", сокет_путь, мост_путь
    elif сокет_имя and title:
        поле, слева, справа = "document_title", сокет_имя, title.strip()
    else:
        # There is nothing to check against — and this is NOT "a match". A silent "yes" here would be
        # the same defect as a silent "no".
        return None
    итог: dict[str, Any] = {
        "checked": поле,
        "agree": слева == справа,
        "socket": слева,
        "bridge": справа,
        "journal_identity": _turn_document_identity(),
    }
    if итог["agree"]:
        return итог
    итог["refused"] = DOCUMENT_IDENTITY_MISMATCH
    итог["message_ru"] = (
        "ВНИМАНИЕ: окно Ревита и модель, которую прочитал мост, — это РАЗНЫЕ "
        f"документы (окно: «{слева}», мост: «{справа}»). Журнал и превью "
        "этого хода ведутся по документу ОКНА. Проверьте, тот ли документ "
        "активен, прежде чем переносить программу в Revit.")
    return итог


def _turn_journal_doc_key() -> str:
    """`doc_key` of THE LIVE JOURNAL — the sole author of the document's makeup.

    🔴 WHY SEPARATE FROM `_turn_journal_document`, AND NOT IN ITS PLACE. The document's
    name has FIVE readers in this file, and they need DIFFERENT things:

        `plan_stream.publish` / `remember_sections`  a JOURNAL key — identity
        `_turn_journal_key` (the journal session key)  a JOURNAL key — identity
        `created_ledger.record_created`           a name, readable by a human
        `witness_feed.record_witness`             a name: the TASK carrier in the metric

    Substituting identity everywhere at once would mean breaking the tree's main metric:
    in the witness corpus `doc_key` IS the TASK, and `Проект1\\x1fdk:…` there
    would read as a new task on every save of the document. So
    the journal key is its own function, and it is read exactly by those who key the journal.

    THE CLOSURE OF THE LIST IS HELD BY THE SAME INSTRUMENT as on 27.08: the guard
    `test_serving_computes_the_journal_key_in_exactly_one_place` forbids
    a second author of `key_for`, while
    `test_a_journal_belongs_to_a_document_not_to_a_name` forbids a second author
    of `doc_key`'s makeup.
    """
    from kir.live import journal as _live_journal

    return _live_journal.doc_key_for(
        _turn_journal_document(), _turn_document_identity())


def _journal_restore_diagnosis() -> Optional[dict]:
    """What loading the journal SAID about this key — for the receipt, not for the log.

    Returns the load's named refusal (today there is exactly one:
    `journal_of_another_document_with_the_same_name`), or `None`. The reason
    is exactly the same as why `journal_stage` travels alongside: "0 programs" from the
    building judge reads as "nothing was built", and telling this apart from "the journal
    of the same-named document was NOT loaded" is impossible from outside.
    """
    try:
        from kir.live import journal as _live_journal

        return _live_journal.restore_note(_turn_journal_key())
    except Exception:  # noqa: BLE001 — the receipt has no right to break the turn
        logger.debug("journal restore note failed", exc_info=True)
        return None


def _turn_journal_key() -> Any:
    """The live journal key of THIS turn — THE SOLE AUTHOR.

    🔴 WHY A FUNCTION FOR THE SAKE OF ONE LINE. Before 27.08.2026 the key was computed in THREE
    places in this file, and all three took only the device:

        `_building_watch()`                 `key_for(_turn_device_id())`
        `_TURN_JOURNAL_SLOT.set(...)`       `key_for(_turn_device_id())`
        `plan_stream.publish(device_id=…)`   doc_key stayed at its default of ""

    And `journal.key_for` accepts the document as its SECOND argument, and the showroom's
    readers (`viewer/live_scene.py`, `viewer/compilability.py`) pass it
    honestly. The result was two-fold, and the second half was found only by measurement:
    two programs of DIFFERENT buildings on one device landed in ONE record, while
    a reader with the document's real name found NOTHING and honestly stayed silent.

    The docstring of `key_for` itself names this outcome verbatim: "the writer and
    the readers must land in the same record… would drift apart SILENTLY". So
    the fix is not to add the argument in three places — it is to make the number of places
    become ONE. Three places that must agree — the named defect of the tree;
    the closure of the list is held by
    `test_serving_computes_the_journal_key_in_exactly_one_place`.
    """
    from kir.live import journal as _live_journal

    # 🔴 IDENTITY, NOT NAME (08.09.2026). The second argument used to be the
    # document's name, and `Проект1` is the default name of EVERY new
    # Revit document: a new empty document was loading 194 programs of a foreign
    # building from the store. The makeup is computed by `_turn_journal_doc_key` — and only it.
    return _live_journal.key_for(_turn_device_id(), _turn_journal_doc_key())


def _building_watch() -> tuple[Any, int]:
    """A mark for "how many programs the building had BEFORE this turn".

    Taken BEFORE the body and compared AFTER — that way the question "did this turn
    add anything to the building?" is answered by the JOURNAL, not by a flag that the body would have
    to carry through a dozen and a half `return`s. Forgetting to carry a flag through
    is possible; diverging from the journal is not.
    """
    from kir.live import verdict as _building

    key = _turn_journal_key()
    return key, _building.programs_seen(key)


#: The ceiling for the flat address-map string. The same argument as for `DIGEST_LIMIT`:
#: a top-level scalar survives collapsing whole only up to 120 characters
#: (`chat_helpers._summarize_tool_result` cuts anything longer by a HARD-CODED literal,
#: independent of the configurable cap). The string must fit on ITS OWN, rather than
#: relying on the collapser's leniency.
ELEMENT_MAP_NOTE_LIMIT = 120


def element_map_note(mapping: Mapping[str, Any],
                     limit: int = ELEMENT_MAP_NOTE_LIMIT) -> str:
    """The "operation → element" map as A FLAT STRING that survives history.

    🔴 A MEASUREMENT FROM 15.08.2026 with the real collapser on the PROD shape of the receipt:

        {"element_map": {"w1": ["9001"], "d1": ["5"]}}
                                    ->  "<объект, 2 полей — свёрнуто>"
        {"assembly_note": "сборка: …"}          ->  the whole string

    A dict collapses AT ANY LEVEL — being top-level does not save it, because
    the collapser replaces every dict and list, and preserves only scalars.
    So the `op_id → element_id` bridge, for the sake of which two waves were spent, was evaporating
    after thirty messages: the model uses it within the turn and cannot
    reference what was built afterward. Exactly the same defect that
    `lift_assembly_note` fixed, in the neighboring field.

    TWO FORMS OF ONE FACT, AND BOTH ARE LEGITIMATE. The dict remains: it is machine-oriented, it is
    read within the turn, and it has no ceiling. The string is for memory, and it is
    deliberately poorer: the operation's address and the addresses of its elements, with no structure.

    IT NEVER LOOKS COMPLETE WHILE BEING TRUNCATED — the `+N` tail is computed
    IN ADVANCE and counts against the ceiling together with the string (the same trick as in
    `assembly_view.digest`). A string that was silently cut off is worse than a missing one:
    decisions are made from it as if it were complete.

    An empty map and a map that FAILED TO ASSEMBLE are different facts, and the second does not
    land here at all: it is carried by `element_map_error`, which is itself
    a top-level scalar and survives history without any help from us.
    """
    if not mapping:
        return "элементы: не названы"

    head = "элементы: "
    parts: list[str] = []
    shown = 0
    for op_id, value in mapping.items():
        ids = [str(v) for v in value] if isinstance(value, (list, tuple)) \
            else [str(value)]
        piece = "%s=%s" % (op_id, ",".join(ids))
        candidate = head + "; ".join(parts + [piece])
        reserve = len(" +%d" % (len(mapping) - shown - 1))
        if len(candidate) + reserve > limit:
            break
        parts.append(piece)
        shown += 1

    out = head + "; ".join(parts) if parts else head.strip()
    hidden = len(mapping) - shown
    if hidden > 0:
        out += " +%d" % hidden
    return out


def lift_element_map(result: dict) -> dict:
    """Place the flat form of the map next to the dict. One owner of the form.

    It is called AT THE SAME PLACE where the map itself is placed, so that the test can call exactly what
    prod calls. As long as the load-up sat as a line inside the body, the only
    way to test it would be to rewrite the receipt's form by hand — that is,
    to guard the fixture rather than the path (shape 27).
    """
    mapping = result.get("element_map")
    if isinstance(mapping, Mapping) and mapping:
        result.setdefault("element_map_note", element_map_note(mapping))
    return result


#: How many named absences are printed BY NAME; the rest are counted
#: as a number. The value is ASSIGNED, not measured.
_ABSENCE_SHOWN = 2

#: The ceiling for THE WHOLE string. It is declared here because before 20.08.2026 it lived only
#: in a test — and the test measured a HAND-BUILT SET that never touched the new cost at all.
#: That day's measurement: on a program of sixteen ops with named absences
#: the line came out to 463 characters, and 246 of them were paid for by the AXIS half, written
#: long before. That is, the ceiling was already breached without the new field, and the guard did not
#: see this by construction (shape 18: green with no act of distinguishing).
#:
#: Truncation NAMES itself and names the remainder. A silent `body[:cap] + "…"` is
#: our own named case: the docstring of `_summarize_tool_result` promised
#: "we never hand back a truncated prefix" three lines above the code that
#: was doing exactly that.
_NOTE_CAP = 300


def witness_note(witness: Mapping[str, Any]) -> str:
    """The triple of axes AND NAMED ABSENCES — as one flat string.

    🔴 THE TRI-STATE `unwitnessed_axes` MUST SURVIVE CONVERSION TO A STRING, otherwise
    the loading will become exactly the defect the field itself was set up against.
    There are three values and they are DIFFERENT: `{}` — every op declared obligations on all
    three axes; a non-empty dict — the axis and the CULPRITS; `None` — there is nothing to judge by
    (an empty program, an op outside the table, the table failed to load). The last one is NOT
    "everything is fine", and merging it with the first would mean returning to the reader the same
    indistinguishability that the field appeared to eliminate.
    """
    if witness.get("read_only"):
        return ""
    axes = [("геометрия", "geometry_ok"), ("смысл", "semantic_ok"),
            ("топология", "topology_ok")]
    triple = " ".join(
        "%s%s" % (ru, "+" if witness.get(key) else "-") for ru, key in axes)
    unwit = witness.get("unwitnessed_axes")
    if unwit is None:
        tail = " · НЕ ОБЕЩАНО: судить нечем (обязательства не поднялись)"
    elif not unwit:
        tail = " · обязательства объявлены по всем трём осям"
    elif isinstance(unwit, Mapping):
        parts = ", ".join(
            "%s: %s" % (axis, ", ".join(str(op) for op in ops[:4]))
            for axis, ops in sorted(unwit.items()))
        tail = " · 🔴 НЕ ОБЕЩАНО ПРОВЕРЯТЬ — %s" % parts
    else:
        tail = " · НЕ ОБЕЩАНО: форма поля неизвестна"
    # A NAMED ABSENCE MUST SURVIVE THE COLLAPSING OF HISTORY IN EXACTLY THE SAME WAY
    # as the triple of axes and `unwitnessed_axes`: `_summarize_tool_result` keeps
    # only TOP-level scalars, and replaces every dict with "свёрнуто" (collapsed).
    # Honesty that dies after thirty messages is not honesty.
    #
    # The tri-state is preserved in the conversion: `None` — the table was not consulted,
    # `{}` — it was consulted, there are no absences, non-empty — nobody looked here.
    # AN EMPTY DICT IS DELIBERATELY NOT PRINTED: this is the most frequent outcome, and a line
    # about it would be paid for on EVERY writing turn while saying nothing. This is exactly how it
    # differs from `unwitnessed_axes`, where `{}` IS printed, because there it is
    # a STRONG assertion about the completeness of obligations on all three axes.
    # 🔴 WE SHOW TWO, AND COUNT THE REST — AND THIS IS A MEASUREMENT, NOT CAUTION.
    # The first version printed four with the clause's full name, and on a program with
    # all sixteen ops carrying absences it produced 463 characters against the declared
    # ceiling of 300; the contribution of EXACTLY this field was 217 of them (246 -> 463). The clause
    # stays in the line, because it carries all the value: "this was not looked at" without
    # a subject is noise. And the tail NAMES how much is hidden: a silent
    # truncation would read as "there are exactly two absences".
    absences = witness.get("named_absences")
    if absences is None:
        tail += " · НЕ СМОТРЕЛИ: таблица отсутствий не спрошена"
    elif absences and isinstance(absences, Mapping):
        rows = [(op, entries[0][0])
                for op, entries in sorted(absences.items()) if entries]
        if rows:
            named = ", ".join("%s: %s" % row for row in rows[:_ABSENCE_SHOWN])
            hidden = len(rows) - _ABSENCE_SHOWN
            more = " и ещё %d" % hidden if hidden > 0 else ""
            tail += " · 🔴 СЮДА НИКТО НЕ СМОТРЕЛ — %s%s" % (named, more)
    # THE WORD REVIT MUST SURVIVE THE COLLAPSING OF HISTORY for the same reason as
    # the triple and the named absences: `_summarize_tool_result` leaves only
    # TOP-level scalars, and replaces a list of dicts with "свёрнуто". If
    # the warning lives only inside the structure, the model learns about it for exactly one
    # turn, and afterward builds green again on top of a discarded lock.
    #
    # 🔴 AND IT COMES FIRST IN THE TAIL — THIS IS A MEASUREMENT, NOT TASTE. The product's
    # collapser cuts a string field at a HARD-CODED literal of 120 characters
    # (`chat_helpers.py`), independent of our own `_NOTE_CAP = 300`: two
    # ceilings on one field, and the smaller one does not belong to us. What was appended at the end
    # was cut off exactly at it — a measurement on 20.08 with a real pair of prod functions gave
    # «REVIT СКАЗАЛ (5): Ограничения не выпол…», meaning the subject was lost, while
    # the most frequent and least informative tail ("obligations declared
    # on all three axes") was eating the budget. The order in the string IS the priority for
    # the reader: "Revit undid what was declared" matters more than "we promised to look".
    # A COUNT and ONE piece of text are printed: the count keeps a truncation from reading as
    # "there was exactly one warning", the text names the subject.
    warned = witness.get("revit_warnings")
    if isinstance(warned, list) and warned:
        first = ""
        for row in warned:
            if isinstance(row, Mapping):
                first = str(row.get("text") or row.get("guid") or "")
                break
        more = " и ещё %d" % (len(warned) - 1) if len(warned) > 1 else ""
        tail = " · 🔴 REVIT СКАЗАЛ (%d): %s%s%s" % (
            len(warned), first[:60], more, tail)
    # Truncation NAMES itself — using the shared `_cut_and_say` idiom, not its own copy.
    # A copy lived here since 20.08 and was the ONLY place in the file where truncation
    # spoke about itself; the runtime refusal next to it cut silently. The argument for why the ceilings
    # stay DIFFERENT sits at the function itself.
    return _cut_and_say("оси: %s%s" % (triple, tail), _NOTE_CAP)


def lift_witness_note(result: dict) -> dict:
    """THE VERDICT ABOUT THE AXES — ONTO THE TOP LEVEL, FOR THE SAME REASON AS THE MAP.

    The full argument sits at `lift_assembly_note` and is NOT REPEATED here: a third
    statement of the same reason is a third carrier, which will one day drift apart
    from the first two. In short: `_summarize_tool_result` preserves only
    TOP-LEVEL SCALARS, replacing every dict with "свёрнуто" (collapsed).

    A MEASUREMENT FROM 19.08.2026 WITH THE REAL COLLAPSER, the input assembled by the prod function
    `_witness_for_success`, not by hand:

        before:  {"geometry_ok": true, "semantic_ok": true, "topology_ok": true,
                 "unwitnessed_axes": {"topology": ["create_group"]}}
        after:   "witness": "<объект, 4 полей — свёрнуто>"

    That is, after thirty messages the model loses BOTH the verdict on the three axes AND
    the only field by which the program declares WHAT IT DID NOT PROVE. For
    a file whose cardinal invariant is "zero silently-wrong outcomes", this is
    the worst possible place to lose it: the green survives, but the caveat attached to it does not.

    WHY ONLY THE SUCCESS PATH, AND THIS IS NAMED, NOT PASSED OVER IN SILENCE. On refusal paths
    the receipt carries `err`/`diagnostics` at the top level, and they survive
    collapsing on their own; there the reader already knows the write did not happen. What is dangerous
    is precisely success: the triple is green, while there could have been not a single obligation on the axis —
    the `_unwitnessed_axes` measurement gives 11 ops with no geometry, 15 with no topology,
    25 with no semantics, out of 64 writing ops.

    `setdefault`, like its neighbors: if the body ever speaks about the axes on its own,
    its word is closer to the subject and should take precedence.
    """
    witness = result.get("witness")
    if isinstance(witness, Mapping):
        note = witness_note(witness)
        if note:
            result.setdefault("witness_note", note)
    return result


def lift_assembly_note(result: dict, block: Mapping[str, Any]) -> dict:
    """THE ASSEMBLY DIGEST — ONTO THE TOP LEVEL OF THE RECEIPT, OTHERWISE IT DOES NOT SURVIVE.

    `chat_helpers._summarize_tool_result` preserves ONLY TOP-LEVEL
    SCALARS, replacing every dict and list with "свёрнуто". The digest used to sit
    inside `building`, that is, one level deeper — and it was disappearing at exactly the
    collapsing it was written to survive (`assembly_view.digest`
    returns a FLAT string for exactly this reason, rather than a structure).

    A measurement from 15.08.2026 with the real collapser on two real shapes:

        {"building": {"assembly_note": …}}   ->  "<объект, 7 полей — свёрнуто>"
        {"assembly_note": …}                 ->  the whole string

    Test Ш2 was pinned to the SECOND shape, which prod does not produce: it was guarding
    the fixture rather than the path, and was green with an open loop. Our named
    defect — a value declared in one place and read in another.

    WHY A SEPARATE FUNCTION. So that the receipt's form has ONE owner and
    the test can call exactly what prod calls. As long as the load-up sat as a line
    inside the body, the only way to test it was to rewrite the form
    by hand — that is, to guard the fixture again.

    `assembly` (the structure) DELIBERATELY stays only inside `building`: it is read
    by the model within the turn, and a copy at the top would be paid for on every turn. What goes to the top
    is exactly what must survive history.
    """
    note = block.get("assembly_note")
    if isinstance(note, str) and note:
        result.setdefault("assembly_note", note)
    return result


#: THE ORDER OF THE RECEIPT'S KEYS IS THE ORDER OF SURVIVAL, NOT FORMATTING.
#:
#: 🔴 SET UP ON 26.08.2026 BY MEASUREMENT, NOT BY TASTE. A live KIR-G101 refusal on a
#: real building (AVT3_KR_MBPB, 18 floors) weighs 21,064 characters. The copy
#: of the receipt that stays in the turn's HISTORY is cut to 5,000
#: (`chat_ws.TOOL_RESULT_HISTORY_CHARS`), and it is cut by PREFIX: the truncator
#: returns `{"truncated": true, "preview": "<первые ~3600 символов>", …}`.
#:
#: So a key placed earlier reaches the model, and one placed later does not. This
#: makes INSERTION ORDER a carrier of meaning. Before this fix it formed on its
#: own from the sequence of stamps, and the refusal's reason survived BY CHANCE — simply
#: `diagnostics` happened to be the third key. A measurement of the same refusal:
#:
#:      arrived:    ok · refused · diagnostics · message_ru · outcome
#:      cut off:    inside `building` (18,022 characters, 86% of the receipt)
#:      did not arrive: err · rehearsal · rehearsal_note_ru
#:
#: `err` carries `kir_code` and a ready-made `fix` string — that is, THE NEXT TURN — and
#: it did not arrive while 18 KB describing what was built did. Swap two
#: stamps and the model would get 3,600 characters of clashes instead of the refusal's
#: reason, and not a single test would turn red.
#:
#: THE ORDER IS DERIVED FROM ONE QUESTION: what does the author need in order to make
#: THE NEXT TURN. First the verdict (tens of bytes), then the reason and the fix,
#: then what was built, and only at the end — the description of the building's state, the
#: largest and least decisive. Keys not named here keep their mutual
#: order and travel between the named ones and `building`: an unknown field has no
#: right either to push out the refusal's reason or to end up after the largest one.
#: 🔴 THE FIRST VERSION NAMED THE ORDER ONLY FOR A REFUSAL (the evening of 26.08.2026).
#: The measurement was taken on a refusal, and exactly the keys a refusal has
#: ended up in the head. On a SUCCESSFUL build the receipt carries something quite different — the judge's verdict
#: on what was built, a sign of a transaction rollback, violated postconditions — and all
#: of it fell into an UNNAMED MIDDLE, where the order is again determined by
#: insertion sequence. That is, exactly the randomness for whose elimination
#: the list was set up kept living on for the second of the two outcomes.
#:
#: A successful receipt is cut by the same truncation and for the same reasons: `building`
#: on an executed turn is legitimate and weighs the same 18 KB, meaning the 5,000-character threshold
#: is always exceeded, and the order settles it the same way.
_RECEIPT_ORDER_HEAD = (
    # 1. THE TURN'S VERDICT — tens of bytes, decides everything else.
    "ok", "refused", "rolled_back",
    # 2. WHAT IS WRONG AND WHAT TO DO NEXT.
    "err", "diagnostics", "postconditions_violated", "handoff",
    "message_ru",
    # 3. THE TURN'S STATE: execution, witness, acceptance.
    "outcome", "acceptance",
    # 4. WHAT WAS BUILT AND HOW THE JUDGE READ IT. `built`/`built_note` is the verdict
    #    on elements RE-READ from the document, that is, the one place where
    #    "declared" is checked against "built". Nothing on a successful turn is more
    #    valuable, and in the first version it was not in the list at all.
    "result", "element_map", "element_map_error", "element_map_note",
    "built", "built_note",
    # 5. THE WITNESS AND ITS BOUNDARIES.
    "witness", "witness_note",
    # 6. HONESTY ABOUT INCOMPLETENESS AND ABOUT SUBSTITUTIONS — short lines, but without them
    #    the reader mistakes the partial for the complete.
    "is_partial_read", "partial_read_note_ru",
    "defaults_note_ru", "resolved_refs", "resolved_refs_note_ru",
    # `omissions_note_ru` sits HERE, not in the tail, and this is a decision made by MEASUREMENT:
    # silence about authority over a field having passed to THE TYPE cost 420 columns, silently
    # landing at 2500 instead of 3600-4500. A line that gets cut first would not
    # have prevented a single one of them.
    "omitted_authorities", "omissions_note_ru",
    "rehearsal", "rehearsal_note_ru",
    # `self_check` sits RIGHT NEXT TO THE REHEARSAL, and this is not a coincidental neighboring but
    # a single pair: the rehearsal says WHAT will be checked, the self-check says WHAT
    # the judge has already found in what was declared. Apart, each half reads as
    # complete. They are in the head because both are available BEFORE the write and both change
    # THE NEXT line the author writes; anything cut before them the author can no longer
    # fix.
    "self_check", "self_check_note_ru",
    # The reason why there IS NO verdict about the building. It sits in the head, while
    # `building` itself is in the tail, and this is not a contradiction: the block is cut first by
    # weight (86% of the receipt), while the line about its absence weighs tens of bytes and
    # without it, the empty space reads as "it was judged and nothing was found".
    "verdict_silent_because",
)

#: The tail is what gets cut first. Only `building` is here: 86% of the receipt's
#: weight, and not a single field without which the next turn cannot be made.
_RECEIPT_ORDER_TAIL = ("building",)


def _order_receipt(result: Any) -> Any:
    """Reorder the receipt's keys into the order they survive truncation in.

    Deletes nothing and adds nothing: the same set of keys, a different
    order. A non-dict is returned as is.
    """
    if not isinstance(result, dict):
        return result
    голова = [k for k in _RECEIPT_ORDER_HEAD if k in result]
    хвост = [k for k in _RECEIPT_ORDER_TAIL if k in result]
    названные = set(голова) | set(хвост)
    середина = [k for k in result if k not in названные]
    return {k: result[k] for k in (*голова, *середина, *хвост)}


def _verdict_is_silent(result: Any, why: str) -> Any:
    """NAME THE SILENCE OF THE BUILDING VERDICT. Returns the same receipt.

    🔴 WHY, AND THIS IS NOT DECORATION. `building` has four legitimate reasons not to
    appear — the turn was not executed, the journal did not grow, the judge returned empty due to the
    ceiling, the stamp failed — and before 01.09.2026 all four looked, from outside,
    IDENTICAL: the key is simply absent. That is, "it was judged and nothing was found" was indistinguishable
    from "it was not judged", and this is the named defect of this tree (a false zero), and it
    stood here on the most costly field — the model's feedback.

    The idiom is taken ready-made from `install_paths.install_root_refusal`: an emptiness
    that cannot be enumerated is A NAMED REFUSAL, not an emptiness.

    CHEAP BY CONSTRUCTION: one short line instead of a block worth kilobytes, and
    only where the block is ABSENT. `setdefault` — so that the body's word, if it
    ever appears, remains senior.
    """
    if isinstance(result, dict):
        result.setdefault("verdict_silent_because", why[:_NOTE_CAP])
    return result


async def _stamp_building_verdict(result: Any, watch: tuple[Any, int]) -> Any:
    """THE VERDICT ABOUT THE BUILDING — onto THE RECEIPT, one place for all outcomes.

    WHAT THIS FIXES. The session's bundle was going out to the showroom and the executor — the human and
    Revit — but it never reached the judge: `check_bundle` had exactly one
    prod caller, `course.design_check` inside the sandbox. Meanwhile the building
    is built IN PARTS by Revit's own law (`create_stairs` must be the only
    op of its own program), so a verdict about one link always speaks about the wrong thing.

    ONLY IF THE JOURNAL GREW. A reading turn does not belong to the building (measurement from 29.07 —
    176 reads per 5 writes), and repeating yesterday's verdict on it would mean
    teaching the model on a number it can no longer change.

    IN THE STREAM, NOT IN THE EVENT LOOP. `check_bundle` computes in Python under the GIL (measured: ~0.4
    ms per operation), and holding the event loop on it would mean hanging other
    people's turns on someone else's building.

    `setdefault`, not an assignment: if the body ever starts speaking about the
    building on its own, it will be closer to the subject and its word will take precedence.
    """
    try:
        if not isinstance(result, dict):
            return result
        # 🔴 THE VERDICT ABOUT THE BUILDING TRAVELS ONLY WITH A TURN THAT TOUCHED THE BUILDING
        # (26.08.2026, measurement through the live door on AVT3_KR_MBPB, 18 floors).
        #
        # A grounding refusal — `execution: not_started`, not a single operation
        # was executed, the document was untouched — was carrying EXACTLY THIS:
        #
        #     the whole receipt      21,415 characters
        #     building               18,022      84%
        #        of which clash      14,385      67% of THE WHOLE receipt
        #     diagnostics             ~1,300     the refusal's reason and the next turn
        #
        # The copy of the receipt in the turn's history is cut to 5,000, and at that size
        # the truncator degenerates into a raw prefix. That is, 84% of the space was taken by
        # a description of what this turn did NOT CHANGE, and it was pushing out the very thing
        # the receipt is read for.
        #
        # WORSE STILL IS WHAT IT WAS ACTUALLY DESCRIBING. The same measurement: the verdict judged
        # 363 programs and 9,750 operations, of which exactly ONE WAS BUILT, and 309
        # of the earliest were pushed out of the journal. Fourteen kilobytes of clashes
        # were counted against WHAT WAS DECLARED, not what was built, and were delivered to an author
        # who built nothing on this turn.
        #
        # WHY THE GATE IS HERE, AND NOT AT THE COUNTER: `programs_seen` counts
        # DECLARED programs, and a refusal duly advances it — the program
        # was declared, simply not executed. The counter is right about its own subject;
        # what was wrong was the inference "if it was declared, then there is something to judge".
        #
        # THE BOUNDARY IS NAMED AND MEASURED: EXACTLY `not_started` is suppressed. A read
        # (`read_completed`) was checked through the same door and is already clean — the answer to
        # `query_count` weighs 676 characters, `building` in it is empty. The states
        # `committed`/`rolled_back`/`unconfirmed` mean that the building
        # was touched, and a verdict is due to them: a rollback is a building event too.
        #
        # BOTH DOORS, NOT ONE. There are TWO stamps here — the verdict and the clashes — and
        # putting the gate on only one would mean buying our named defect of
        # "fixed the copy, left the original": clashes weigh 14 KB out of 18 and
        # would still be delivered to the author regardless.
        _исполнение = (result.get("outcome") or {}).get("execution")
        if _исполнение == "not_started":
            return _verdict_is_silent(
                result, "ход не дошёл до исполнения: здания он не коснулся")
        from kir.live import verdict as _building

        key, before = watch
        if _building.programs_seen(key) <= before:
            return _verdict_is_silent(
                result, "журнал сессии не вырос: этот ход зданию ничего не "
                        "добавил")
        # THE TURN'S BOUNDARY IS THE SAME MARK AS THE WATCH, and it travels to BOTH doors.
        # In chat this matters more than on the admin door: here the receipt is read by THE MODEL,
        # and "45 clashes", of which 45 predated it, it will either set out to fix
        # (editing someone else's geometry), or will report as a breakage of the building.
        block = await asyncio.to_thread(
            functools.partial(_building.judge, key, since_seq=before))
        if block:
            result.setdefault("building", block)
            lift_assembly_note(result, block)
        else:
            # `judge` returned empty: either the verdict's ceiling was exceeded, or there is
            # nothing to judge. It has a reason, it just was not surfacing outward.
            _verdict_is_silent(result, "судья о здании не дал блока: перебор "
                                       "потолка вердикта либо нечего судить")
    except Exception:  # noqa: BLE001 — the verdict must not break a turn involving Revit
        logger.debug("KIR building verdict stamping failed", exc_info=True)
        _verdict_is_silent(result, "штамп вердикта о здании сорвался")
    return result


async def _stamp_building_clash(result: Any, watch: tuple[Any, int]) -> Any:
    """CLASH AUDIT AT THE ADMIN DOOR — where whole buildings are assembled.

    WHAT THIS FIXES. The product is "the engineer presses SEND TO REVIT, and
    the building compiles as a whole"; that button goes into
    `handle_revit_ir_bulk`. Measurement: `_stamp_building_verdict` is called
    from exactly two lines, both on the `bulk=False` path. That is, the ONLY
    route by which whole buildings get built is exactly the one the clash
    check never saw.

    WHY THIS IS A SEPARATE FUNCTION, NOT A CALL TO THE VERDICT. Excluding the
    admin door from the VERDICT remains valid and justified (`live/verdict.py`:
    the author here is a materializer, not the model, and there is no one to
    teach). The clash does not inherit that argument: the verdict is feedback
    to the MODEL, the clash is a BUILDING AUDIT, and a rebuild with mutually
    intersecting geometry is broken regardless of whether anyone is being
    taught. So this calls `verdict.clash_only`, which builds no verdict at
    all.

    THE `building` KEY IS LEFT UNTOUCHED. The block travels under its own
    name, `clash`: at the chat door findings sit INSIDE `building`, and if
    the admin door put them there too, the `building` key would show up
    where no verdict exists — the reader would read "the building was
    judged."

    FLAG OFF ⇒ NOT ONE NEW BYTE. `clash_only` returns `None` when
    `KUKAI_IR_CLASH` is off (the only way out of `bundle_clash_report`), and
    `None` never reaches `setdefault`.

    ONLY IF THE JOURNAL GREW — under the same watch as the verdict: a
    read-only turn does not belong to the building.

    IN THE STREAM, NOT IN THE LOOP: the check counts in Python under the GIL
    (measured 10.08 — 0.5 s per building for 31 971 operations), and running
    the event loop on it would mean hanging other people's turns on someone
    else's building.
    """
    try:
        if not isinstance(result, dict):
            return result
        # 🔴 THE BUILDING VERDICT TRAVELS ONLY WITH A TURN THAT TOUCHED THE
        # BUILDING (26.08.2026, measured live at the door on AVT3_KR_MBPB, 18
        # floors).
        #
        # A grounding refusal — `execution: not_started`, not one operation
        # executed, the document untouched — was carrying THIS:
        #
        #     whole receipt          21 415 characters
        #     building               18 022      84 %
        #        of which clash      14 385      67 % of the WHOLE receipt
        #     diagnostics             ~1 300     refusal reason and next turn
        #
        # The receipt copy in turn history is truncated at 5 000, and at that
        # size the truncator degenerates into a raw prefix. That is, 84 % of
        # the space was taken by a description of what this turn did NOT
        # change, crowding out the very thing the receipt is read for.
        #
        # WORSE STILL IS WHAT IT WAS ACTUALLY DESCRIBING. Same measurement:
        # the verdict judged 363 programs and 9 750 operations, of which ONE
        # was built, and the 309 earliest were pushed out of the journal.
        # Fourteen kilobytes of clashes were counted from the DECLARED, not
        # the built, and arrived at the author who built nothing this turn.
        #
        # WHY THE GATE IS HERE, NOT AT THE COUNTER: `programs_seen` counts
        # DECLARED programs, and the refusal duly advances it — the program
        # is declared, simply not executed. The counter is right about its
        # own subject; the wrong conclusion was "declared implies something
        # to judge."
        #
        # THE BOUNDARY IS NAMED AND MEASURED: it is quenched at EXACTLY
        # `not_started`. Reading (`read_completed`) was checked at the same
        # door and is already clean — the answer to `query_count` weighs 676
        # characters, `building` in it is empty. The states
        # `committed`/`rolled_back`/`unconfirmed` mean the building was
        # touched, and a verdict is owed: a rollback is a building event too.
        #
        # BOTH DOORS, NOT ONE. There are TWO stamps here — verdict and
        # clashes — and gating only one would buy our own named defect,
        # "fixed the copy, left the original": clashes weigh 14 KB out of 18
        # and would still travel to the author unchanged.
        _исполнение = (result.get("outcome") or {}).get("execution")
        if _исполнение == "not_started":
            return result
        from kir.live import verdict as _building

        key, before = watch
        if _building.programs_seen(key) <= before:
            return result
        # THE TURN BOUNDARY IS THE SAME MARK AS THE WATCH. `before` is
        # already taken before the body and means "how many programs the
        # building had BEFORE this turn"; the records with `seq >= before`
        # are exactly the ones it declared. No second "what's new" tally is
        # kept — it would drift out of sync with the watch within a week.
        block = await asyncio.to_thread(
            functools.partial(_building.clash_only, key, since_seq=before))
        if block:
            result.setdefault("clash", block)
    except Exception:  # noqa: BLE001 — THE AUDIT MUST NOT COST A TURN WHERE REVIT
        # IS ALREADY WRITING. The same absolute fail-open used by the
        # verdict and by `clash_bundle` itself: a false refusal of a correct
        # build costs more here than a missed finding, and both modules'
        # contracts record that.
        logger.debug("KIR bulk clash stamping failed", exc_info=True)
    return result


async def _document_catalogue(llm_client: Any, bridge_callback: Any) -> Any:
    """The open document's catalogue FOR THE SCRIPT — a separate read, before
    emission.

    WHY SEPARATE, NOT THE SAME ONE. The grounding snapshot is taken AFTER the
    program is assembled (`_snapshot_cs(program)` substitutes into the body
    the parameter names the program named), while the script needs the
    catalogue BEFORE that: it is the one writing it. So this reads the
    GENERAL `_SNAPSHOT_CS` body — the same one that already passes the gate,
    without narrowing by program.

    THE COST IS NAMED: one extra round trip to the bridge, and only on turns
    with `program_py`. The regular JSON path pays nothing — it never comes
    through here.

    A BRIDGE FAILURE DOES NOT ABORT THE TURN. The catalogue is a
    convenience, not a precondition: without it the script gets the name
    `model`, which WILL NAME the reason, and can still name types by hand,
    as it always did. Aborting the turn over a failed auxiliary read would
    make a new capability mandatory after the fact.

    THE AUTHORITY STAYS WITH GROUNDING. This catalogue affects nothing
    except what the script MANAGED to read: the program is still grounded
    by `ground` from its OWN, fresh snapshot, and that is what refuses if
    the assumption broke.
    """
    if llm_client is None or bridge_callback is None:
        return None
    try:
        result = await _run_declarative(
            llm_client, bridge_callback, _SNAPSHOT_CS,
            "script_catalogue", _SNAPSHOT_TIMEOUT_MS)
    except Exception:                       # noqa: BLE001 — see "failure does not abort"
        return None
    if _extract_error(result) is not None:
        return None
    payload = result.get("result", result) if isinstance(result, dict) else None
    # "levels" is the same marker of a genuine snapshot that the grounding
    # branch below uses to recognize it; no second definition of "snapshot"
    # is kept here.
    return payload if isinstance(payload, dict) and "levels" in payload else None


#: The name the trip for the catalogue is paid for. One; its identity with
#: the script's namespace is held by `test_catalogue_roundtrip_is_asked_for`,
#: not by convention: rename it in the sandbox and the ratchet turns red —
#: the trip won't start being skipped silently.
_CATALOGUE_NAME = "model"

#: The name the building index is assembled for. The same technique and the
#: same ratchet as the catalogue's — and the same identity with
#: `sandbox.HOST_NAMES`.
_BUILDING_NAME = "building"


def _script_may_read_catalogue(source: str) -> bool:
    """Whether THIS script can read the document catalogue at all.

    WHY. The trip for the catalogue costs **3262 and 3675 ms** (measured
    16.08.2026 from two `EXEC_PIPELINE_RECORD op=script_catalogue` records
    in the prod journal) and was being paid on EVERY `program_py` turn —
    even when the script never touches the catalogue. The turn breakdown
    for the same day: model 84.6 %, bridge and Revit 13.1 %, our Python
    0.44 %. So the extra trip to the bridge is the second-largest chunk of
    the turn after waiting for the model, and that is a pure loss, not the
    price of a capability.

    WHY THE CHECK IS SOUND, NOT MERELY CONVENIENT. The catalogue reaches the
    script by EXACTLY one route — a name in the namespace
    (`sandbox.HOST_NAMES`). There is no other way to get at it: `globals`
    and `locals` are FORBIDDEN to the script as builtins, modules are not
    injected, and there is nothing for `getattr` to hook. A script that
    never named it CANNOT read the catalogue — so skipping the trip changes
    not one observable value, including the catalogue's signature in the
    receipt.

    WHY A SUBSTRING CHECK, NOT AN `ast` PARSE. An error here is tolerable in
    exactly one direction: an extra trip is today's price, a missed one is a
    lost capability for the author who asked for it. A substring check errs
    ONLY toward an extra trip: it will match on a comment, on a string
    literal, and on an unrelated name like `my_model`. Parsing is more
    precise but fails on syntactically invalid source — and such source does
    arrive here (the sandbox parses it ITSELF and answers `KIR-B001`), which
    would push the decision into an exception handler, exactly where it is
    easiest to get wrong.

    WHAT THIS DOES NOT CHANGE. The authority stays with grounding: the
    program is still grounded by `ground` from its own, fresh snapshot, and
    that is what refuses with `KIR-G101` if the assumption broke. A skipped
    trip cannot make a build silent — it can only withhold from the script
    data it never asked for.
    """
    return _CATALOGUE_NAME in source


def _script_may_read_building(source: str) -> bool:
    """Whether THIS script can read the building index at all.

    The same technique and the same argument as for the catalogue
    (`_script_may_read_catalogue`): the index reaches the script by EXACTLY
    a name in the namespace, `globals` and `locals` are forbidden to the
    script as builtins — so a script that never named it CANNOT read it,
    and assembling the index changes not one observable value. A substring
    check, not `ast`, for the same reason: the only tolerable error is
    toward extra work, while parsing would fail on syntactically invalid
    source, which does arrive here.

    THE COST HERE IS DIFFERENT, AND THAT MATTERS. The catalogue cost A TRIP
    TO THE BRIDGE (3262 and 3675 ms), the index costs NONE AT ALL: the
    document name comes from the turn context the plugin already sent
    itself, and the elements are read from disk out of a stored parse. The
    check is still needed — reading the corpus and parsing L0 are not free
    — but what is saved is not a trip, it is work.
    """
    return _BUILDING_NAME in source


#: The ceiling above which the judge's observations are NOT counted in the
#: turn and are instead declared a NAMED ABSENCE. The value is ASSIGNED, and
#: assigned from the measured slope: about 0.27 s per megabyte of L0 (four
#: parses, 1.4 … 88.4 MB, 20.08.2026), i.e. 16 MB ≈ four seconds within a
#: 14–18 s turn. The median corpus parse weighs 3.0 MB and costs a quarter
#: second; the tower weighs 88.4 MB and would triple the turn.
#:
#: 🔴 WHY THE CEILING IS ON L0, NOT ON ELEMENT COUNT: bytes are known BEFORE
#: the work, with a single `stat`, while the element count is known only
#: after reading them. A threshold that requires paying the measured cost to
#: decide whether to pay it is not a threshold.
_OBSERVATIONS_MAX_L0_BYTES = 16 * 1024 * 1024


def observations_budget(l0_bytes: int) -> Optional[str]:
    """Whether the judge's observations fit in the turn: `None` — yes,
    otherwise a REASON in words.

    🔴 THE DECISION IS DELIBERATELY FACTORED INTO A PURE FUNCTION (form 33).
    Checking the threshold by CALLING the guarded action would mean learning
    about it at the price of the action itself: on the tower that is 24
    seconds and 356 MB for a single test run. Here the input is faked, the
    outcome is read, and the heavy parse NEVER happens.

    The return value is a reason, not a boolean, precisely because the
    reason travels to the model: it must distinguish "no violations" from
    "they were never looked for," and a boolean carries none of that.
    """
    if l0_bytes <= _OBSERVATIONS_MAX_L0_BYTES:
        return None
    return ("наблюдения судьи по этому зданию не считались: L0 весит %.1f МБ "
            "при потолке %.1f МБ, а цена около 0.27 с на мегабайт (замер "
            "20.08) — это утроило бы ход. Это НЕ «нарушений нет»: их не "
            "искали. Посчитанные один раз и закэшированные лежат в "
            "`/api/viewer/normcontrol`"
            % (l0_bytes / 1e6, _OBSERVATIONS_MAX_L0_BYTES / 1e6))


def _building_index_for_turn(source: str) -> Optional[dict]:
    """The index of the EXISTING building for the script — or a named
    refusal reason.

    🔴 NOT ONE TRIP TO THE BRIDGE. The open document's title arrives with
    the plugin's context push and sits in the socket registry; the parse is
    taken from disk. Live re-reading of the document for the index is
    separate work with a separate cost, and it is NOT done here (see
    `building_index.index_from_run`, where this boundary is named).

    THREE OUTCOMES, AND NONE OF THEM STAYS SILENT:

    * the index exists — it arrives together with the source's freshness;
    * there is no parse — `refused` with a reason in words. An empty index
      would read as "there is nothing in the building," and that is a fact
      about OUR reading, not about the building;
    * a parse exists, but of a different document — it is dropped inside
      `resolve_run` on an identity MISMATCH, and the reason names that.

    FRESHNESS IS NOT PROVEN, AND THAT IS A MEASUREMENT, NOT CAUTION. The
    live document and the parse share exactly one common key — the title; a
    match does not prove "the same file," a mismatch proves "a different
    file." The asymmetry and the source resolution are taken from
    `clash.existing.resolve_run` wholesale: a second resolver would be a
    second place obliged to agree.

    🔴 THE AUTHORITY STAYS WITH GROUNDING. The index is data for reading,
    not a source of truth for selectors: the program is still grounded by
    `ground` from its own, fresh snapshot, and that is what refuses with
    `KIR-G101` if the assumption broke. A script that branches on index
    data will produce a different program — and it will pass the same
    grounding control as any other.
    """
    if not _script_may_read_building(source):
        return None
    try:
        from kir.clash.existing import resolve_run
        from kir.building_index import index_from_run

        title, revit_version = _turn_document_context()
        if not title:
            return {"refused": (
                "заголовок открытого документа этому ходу неизвестен — плагин "
                "ещё не прислал контекст. Это факт о НАШЕМ чтении, а не о "
                "здании")}
        # 🔴 THE VERSION NARROWS THE CHOICE. Without it, the identity rank is
        # ZERO for every candidate (`_identity_rank` returns 0 when
        # `project_uid` is empty), and the only remaining discriminator is
        # the catalogue's last-write time: same-named parses are picked
        # effectively at random.
        #
        # A BOUNDARY, NAMED, NOT SILENCED: `project_uid` is UNAVAILABLE here
        # — it needs a document fingerprint from `ground`, and this seam
        # runs BEFORE grounding. So the rejection on identity MISMATCH that
        # the door's docstring promises is still unreachable at this call,
        # and the version does not replace it: it narrows, but does not
        # prove.
        run, why, freshness = resolve_run(title, revit_version=revit_version)
        if run is None:
            # BORROWED TEXT IS NAMED AS BORROWED, NOT TRIMMED. The
            # `resolve_run` reason is written for the clash and ends with
            # the words «сравнивать со стоящим не с чем» — here that would
            # read as being about something else. Cutting it by substring
            # would mean matching the LABEL instead of the subject (the very
            # pattern this project has already been caught on), so the
            # borrowing is declared, and its own consequence is stated
            # separately.
            return {"refused": (
                "индекс здания собрать не из чего. Резолвер источника (общий "
                "с клешем) говорит: «%s». Для скрипта это значит одно: разбор "
                "ЭТОГО документа не снимался, и поэлементно ответить нечем — "
                "факт о НАШЕМ чтении, а не о здании"
                % (why or ("разбор документа «%s» не разрешился" % title)))}
        # 🔴 THE JUDGE'S OBSERVATIONS WERE TRAVELING EMPTY BECAUSE OF ONE
        # DEFAULT. `index_from_run` can hand back a parse TOGETHER WITH the
        # judge's observations, and that name already sits on the model's
        # surface (`building.observations()`). Here the form was called
        # WITHOUT them — that is, the capability was built, wired in, and
        # switched off by default, while **an empty list is indistinguishable
        # from "the building is clean"**. Exactly the outcome this
        # function's three named outcomes are written against.
        #
        # THE COST IS MEASURED, NOT ESTIMATED (20.08.2026,
        # `KUKAI_CHECKER_V2=1`, the condition lives in the command, not in
        # memory: without the flag the judge stays silent and returns zero
        # observations on ANY building):
        #
        #     parse                L0 MB   without   with obs   COST    obs  silent
        #     sob62_r23_v5          1.4    0.44s     1.30s      0.86s    84    144
        #     sob62_fas_r23_v6      3.0    0.41s     0.65s      0.24s     0    277
        #     snowdon_plumb_v3      5.2    0.62s     1.26s      0.64s     0    277
        #     k2_ar_rd_v15         88.4   10.93s    34.76s     23.83s   660    144
        #
        # The slope is about 0.27 s per megabyte of L0, process peak RSS
        # 356 MB. A turn costs 14–18 s in total, so a tower would triple it,
        # while the median corpus parse (3.0 MB) costs a quarter second.
        #
        # AND SEPARATELY — WHY THIS AT ALL, BEYOND THE OBSERVATION COUNT:
        # the two buildings above have ZERO observations while
        # `observations_silent` = 277. There, zero means "COULD NOT JUDGE,"
        # not "no violations," and without the other half of the pair the
        # reader will read the first as the second.
        l0 = os.path.join(str(run), "L0.jsonl")
        from kir.decompile.snapshot_io import (snapshot_file_exists,
                                               snapshot_raw_size)
        # 🔴 "NO FILE" PASSES ANY THRESHOLD, AND THAT IS THE SAME DEFECT
        # `snapshot_raw_size` IS WRITTEN AGAINST. Its docstring states the
        # rule directly: zero means "neither raw NOR compressed exists," and
        # "distinguishing this case is the job of `snapshot_file_exists`,
        # not the value." Here the companion was never asked: zero went
        # into the budget, the budget answered "fits," and a missing parse
        # read as "observations are cheap."
        if not snapshot_file_exists(l0):
            # A refusal through the SAME DOOR as "too large": the turn then
            # continues down the common path, and `doc_title`/`freshness`
            # are not lost. The only difference is in the reason text — and
            # that is exactly the subject of this fix.
            too_big = (
                f"L0 разбора не найден ({l0}): судить не по чему. Это факт о "
                f"МАШИНЕ, а не о здании — «наблюдений нет» здесь означало бы "
                f"«смотрели и не нашли»")
        else:
            size = snapshot_raw_size(l0)
            too_big = observations_budget(size)
        if too_big is None:
            payload = index_from_run(str(run), with_observations=True)
        else:
            # A NAMED ABSENCE, NOT AN EMPTY LIST. The `observations` key is
            # not set at all: empty it would mean "looked and found
            # nothing."
            payload = index_from_run(str(run))
            payload["observations_refused"] = too_big
        payload["source_run"] = run.name
        payload["doc_title"] = title
        if freshness is not None:
            payload["freshness"] = freshness.to_dict()
        return payload
    except Exception as exc:  # noqa: BLE001 — assembling the index does NOT break the turn
        # The refusal arrives NAMED and lands in the same three outcomes:
        # the script learns there was nothing to look at, instead of an
        # empty index that reads as "empty."
        return {"refused": "индекс здания не собрался (%s: %s)"
                           % (type(exc).__name__, str(exc)[:200])}


def _turn_document_context() -> tuple[str, str]:
    """This turn's document title AND ITS REVIT VERSION.

    🔴 AS A PAIR, NOT SEPARATELY — MEASURED 25.08.2026. The version lives in
    the SAME `_session_contexts[ws_id]` the name is taken from, and the
    neighboring code in the tree reads it exactly that way. As long as it
    went unasked, `resolve_run` was called with a SINGLE title: without
    `project_uid` the identity rank is zero for every candidate, the
    version was never asked for, and the only remaining discriminator was
    the catalogue's last-write time. Same-named parses recorded within the
    same second were picked effectively at random — and a script branching
    on index data got the index of SOMEONE ELSE'S building.

    Returning them separately would mean running two passes over the same
    dictionary that are obliged to agree — this tree's own named defect.

    🔴 AND EXACTLY THIS DEFECT WAS PLANTED HERE BEFORE ANYONE NOTICED. The
    first edition (25.08.2026) did not call `_turn_document_title`, it
    REPEATED its body: the same `turn_document_title()`, the same
    `newest_first` scan, the same rule "the declarer outranks the scan."
    Two carriers of one choice, and one of them — `_turn_document_title`
    itself — was left WITHOUT A SINGLE CALLER. The comment inside it says,
    word for word: "a copy of the rule would drift out of sync here,
    silently" — and the copy was made that very same day.

    This was found not by grep but by THREE RED TESTS that were patching
    `_turn_document_title`: you can patch dead code all you like, and they
    went blind — an instrument that cannot turn red. The live path kept
    working meanwhile, because the copy happened to be correct. A correct
    copy is a delay, not a fix.

    NOW THE NAME IS TAKEN FROM THE SINGLE CARRIER, and the scan here
    remains for exactly one purpose — to find the VERSION of the session
    whose name MATCHED the chosen one. No match — no version is set:
    someone else's version is worse than none.
    """
    # 🔴 THE NAME IS OBTAINED OUTSIDE THE SHARED `try` (28.08.2026), AND
    # THIS IS A FIX.
    #
    # Previously the whole block sat under a single
    # `except Exception -> ("", "")`. The ports below are needed ONLY FOR
    # THE VERSION, but their absence (`PortMissing` on a standalone KIR)
    # also wiped out the NAME that had already been obtained. Measured
    # 28.08: `_turn_document_context()` returned `("", "")` even when
    # `_turn_document_title()` had honestly handed back a title — that is,
    # the promise "name and version AS A PAIR" turned into "neither name
    # nor version."
    #
    # The `except` cleanup stays, but each value is now lost separately: no
    # version means no version, while the name stays a name.
    try:
        имя = _turn_document_title()
    except Exception:  # noqa: BLE001 — a missing name does not break the turn
        return "", ""
    if not имя:
        return "", ""
    return имя, str(_turn_session_context().get("revit_version") or "")


def _turn_session_context() -> Mapping[str, Any]:
    """The SOCKET context whose document this turn selected. Empty — none
    found.

    🔴 ONE SCAN FOR EVERYONE, AND THIS IS NOT ABOUT SAVING LINES
    (08.09.2026). This dictionary now has two askers — the Revit VERSION
    (`_turn_document_context`) and the document's IDENTITY
    (`_turn_document_identity`) — and the `newest_first` scan with
    selection by name match IS the RULE for "whose socket this is." Two
    carriers of it would drift apart silently, and there was something for
    them to drift over: the version and the identity would come from
    DIFFERENT windows, routinely open in pairs for the owner (the NAKAZ,
    clause 19). The same argument that closed the list of authors for the
    journal key on 27.08 (`_turn_journal_key`) — and it was bought right
    here, by the copy of `_turn_document_title`'s body (see above).

    THE PORTS MAY BE ABSENT ENTIRELY (a standalone KIR): then an empty
    dictionary, and each asker loses EXACTLY its own value — version or
    identity — while the document name stays a name.
    """
    try:
        имя = _turn_document_title()
    except Exception:  # noqa: BLE001 — a missing name does not break the turn
        return {}
    if not имя:
        return {}
    try:
        _session_contexts = ports.need(ports.SESSION_CONTEXTS)._session_contexts
        _ws = ports.need(ports.WS_REGISTRY)
        _device_websockets = _ws._device_websockets
        newest_first, ws_id_of = _ws.newest_first, _ws.ws_id_of

        device = _turn_device_id()
        if not device:
            return {}
        for ws in newest_first(list(_device_websockets.get(device) or ())):
            ws_id = ws_id_of(ws)
            if not ws_id:
                continue
            ctx = _session_contexts.get(ws_id) or {}
            if str(ctx.get("document_name") or "") == имя:
                return ctx if isinstance(ctx, Mapping) else {}
        return {}
    except Exception:  # noqa: BLE001 — no context, the turn continues
        return {}


def _turn_document_title() -> str:
    """This turn's document title — WITHOUT a trip to the bridge.

    The plugin sends the context itself (`ws_registry._handle_context`),
    and the title already sits in the registry. Asking the bridge for it
    would mean paying 3.5 s for something we were already told.
    """
    try:
        # 🔴 ASK THE ONE WHO CHOSE, FIRST (24.08.2026, an audit finding).
        # The `/admin/kir/run` door selects a window by `doc_contains` and,
        # since 24.08, DECLARES it. Before that, a SECOND, independent
        # choice ran here — a scan over the SET of sockets
        # (`ws_ids_for_device` iterates a `set`, order undefined) returning
        # the FIRST non-empty name. On the admin machine TWO Revits are
        # routinely open, and that is a coin flip: the write goes to one
        # window, while the BUILDING INDEX for the author's script is
        # assembled from the title of the OTHER one. The script got the
        # levels and grids of SOMEONE ELSE'S building, and the refusal
        # arrived as «уровень не найден» — the wrong reason.
        объявленный = ports.need(ports.TURN_CONTEXT).turn_document_title()
        if объявленный:
            return объявленный

        _session_contexts = ports.need(ports.SESSION_CONTEXTS)._session_contexts
        _ws = ports.need(ports.WS_REGISTRY)
        _device_websockets = _ws._device_websockets
        newest_first, ws_id_of = _ws.newest_first, _ws.ws_id_of

        device = _turn_device_id()
        if not device:
            return ""
        # THE ORDER IS THE SAME FOR ALL DOORS. When there is no declarer
        # (the chat path), we take the FRESHEST connection by the same rule
        # as the other doors: `newest_first` was introduced with the
        # argument "a non-deterministic choice among candidates of which
        # exactly one is correct is a coin flip on every turn." A copy of
        # the rule here would drift out of sync silently.
        for ws in newest_first(list(_device_websockets.get(device) or ())):
            ws_id = ws_id_of(ws)
            if not ws_id:
                continue
            name = str((_session_contexts.get(ws_id) or {}).get(
                "document_name") or "")
            if name:
                return name
        return ""
    except Exception:  # noqa: BLE001 — a missing name does not break the turn
        return ""


#: The "show a sample from the corpus" field. A query string: "residential
#: tower," "kindergarten," a document name.
_EXAMPLE_FIELD = "example"


def _example_only(args: Any) -> bool:
    """A "show a sample" call — a sample is named, and no program in ANY
    form.

    The strictness here is not pedantry: `example` TOGETHER WITH a program
    would mean the caller wants both in one turn, and silently picking one
    would mean deciding for them. Such a call takes the ordinary path and
    is refused on form, rather than silently dropping one of the two
    intents.
    """
    if not isinstance(args, dict):
        return False
    if not str(args.get(_EXAMPLE_FIELD) or "").strip():
        return False
    return (args.get("program") is None
            and args.get(_SCRIPT_FIELD) is None
            and "ops" not in args)


def _example_for_turn(query: Any) -> dict:
    """A PRODUCTION-BUILDING SAMPLE — WHOLE, AND IN THE LANGUAGE THE MODEL
    WRITES IN.

    🔴 WHY THIS EXISTS AT ALL, IN ONE MEASUREMENT. Starting from a blank
    page the model writes **11 operations per attempt**; a real floor of a
    residential tower carries **1000**, the median production building is
    1363. It writes little NOT BECAUSE IT IS WEAK: given a real floor, it
    took 433 s to work out the unit layout and found three defects in
    someone else's production project. It writes little because it has
    never seen production — and production sits right here on our disk, 52
    parses of ten documents.

    WHY THE SAMPLE TRAVELS IN THE RECEIPT, NOT IN THE SANDBOX. The first
    edition of this work put the sample into the script as a third object
    alongside `model` and `building`. That would have been wrong BY
    CONSTRUCTION: the script runs in a SEPARATE PROCESS, hands operations
    outward, and **the model never sees its variables**. Handing the
    sample to the script means handing it to no one: the script is written
    by the very same model that has not read the sample yet. The only
    channel to the model is the receipt.

    THE COST IS MEASURED (17.08.2026, tower `k2_ar_rd_v8`, 59 floors,
    tree.json 216 MB)::

        corpus catalogue (52 .md cards)             0.010 s
        reading the tree + picking a floor + print  2.95 s
        sample size                                 186 364 B (~55K tokens)

    A neighboring door of the same corpus —
    `building_index.index_from_query` — costs **11.7 s** on the same tower
    and hands back a CENSUS instead of elements. The sample is four times
    cheaper as source and carries incomparably more.

    The size is NOT trimmed by default, and that is the owner's
    requirement, verbatim: "116K tokens is the norm for a production
    building; saving context is exactly the mechanism that produces a
    shed." The ceiling stands at twice the measured floor and trims only
    pathology — with the trimmed COUNT stated.

    THREE OUTCOMES: a sample · "several found" (name them, don't pick) · a
    refusal naming the DICTIONARY you can use to get in. A refusal that
    gives no next move is, to an LLM, the same as silence: it cannot see
    the screen.
    """
    text = str(query or "").strip()
    out: dict = {"ok": False, "kir": True, "example": True, "query": text}
    try:
        from kir import corpus_catalog as _cc
        from kir.decompile import program_source as _ps
    except Exception as exc:  # noqa: BLE001 — the module failed to load: that is a REFUSAL
        out["refused"] = True
        out["message_ru"] = ("образец недоступен: %s: %s"
                             % (type(exc).__name__, str(exc)[:160]))
        return out
    try:
        found = _cc.search(text)
    except Exception as exc:  # noqa: BLE001
        out["refused"] = True
        out["message_ru"] = ("каталог корпуса не собрался (%s: %s). Это факт о "
                             "НАШЕМ складе, а не об отсутствии зданий"
                             % (type(exc).__name__, str(exc)[:160]))
        return out
    if found.outcome != _cc.FOUND_ONE:
        out["refused"] = True
        out["outcome"] = found.outcome
        if found.matched:
            out["matched"] = [b.to_dict() for b in found.matched]
            out["message_ru"] = (
                "по запросу «%s» подошло %d зданий — назови одно точнее. "
                "Подошли: %s" % (text, len(found.matched),
                                 ", ".join(b.doc_name for b in found.matched)))
        else:
            out["message_ru"] = found.refused
        return out

    building = found.matched[0]
    run_dir = os.path.join(found.root, building.chosen.run)
    got = _ps.floor_source(run_dir)
    if "refused" in got:
        out["refused"] = True
        out["message_ru"] = got["refused"]
        return out

    out["ok"] = True
    out["building"] = building.to_dict()
    out.update({k: v for k, v in got.items() if k != "source"})
    out["program_py"] = got["source"]
    out["message_ru"] = (
        "ОБРАЗЕЦ: «%s», этаж %s (%s; всего этажей %d). %s\n"
        "Это настоящий продакшн-проект, напечатанный на `program_py` — той же "
        "поверхности, на которой пишешь ты. Читай размеры, типы и связи: "
        "снаружи стены толще, внутри тоньше, у двери есть хозяин, у помещения "
        "имя. Твоя программа пишется ЗДЕСЬ ЖЕ, следующим вызовом."
        % (got.get("document") or building.doc_name, got["level"],
           got["rule"], got["levels_total"], got["report_ru"]))
    return out


async def _authored_input(args: Any, llm_client: Any = None,
                          bridge_callback: Any = None, *,
                          turn_id: str = "", query_id: str = ""
                          ) -> _AuthoredInput:
    """The ONLY place where Python becomes operations.

    Returns either a ready `{"program": {...}}` for the tool body, or a
    typed refusal. It raises nothing: a sandbox failure is a result too.
    """
    if not isinstance(args, dict):
        return _AuthoredInput(args=args, refusal=_form_refusal(
            "аргументы инструмента должны быть объектом с полем `program` "
            "либо `program_py`"))

    program = args.get("program")
    if program is None and "ops" in args:
        program = args                    # tolerate un-nested programs
    source = args.get(_SCRIPT_FIELD)

    if source is None:
        if program is None:
            # NOT A SINGLE FORM. Before, such a call used to reach the
            # compiler and get back «программа отклонена компилятором» — a
            # falsehood: no program had been sent at all, and what needs
            # fixing is the CALL, not the program.
            return _AuthoredInput(args=args, refusal=_form_refusal(
                "не задано ни `program`, ни `program_py`: программа — это "
                "либо операции (`program`), либо питон, который их порождает "
                "(`program_py`). Ровно одно из двух"))
        if args.get("params") is not None:
            # The slider is a capability of the SOURCE: there is nothing to
            # bind a value to, the program is already given as operations.
            # Silently swallowing it would mean accepting the order and
            # building the old thing anyway.
            return _AuthoredInput(args=args, refusal=_form_refusal(
                "`params` задан без `program_py`: ползунок объявляется в "
                "скрипте вызовом param(имя, умолчание), а программе, поданной "
                "операциями, связывать его не с чем"))
        return _AuthoredInput(args=args)   # the regular JSON path, nothing changed
    if program is not None:
        return _AuthoredInput(args=args, refusal=_form_refusal(
            "заданы СРАЗУ `program` и `program_py`. Форма ровно одна за вызов: "
            "либо программа операциями, либо скрипт, который их порождает — "
            "иначе непонятно, что подписывать квитанцией"))
    if not isinstance(source, str):
        return _AuthoredInput(args=args, refusal=_form_refusal(
            f"`program_py` — это ТЕКСТ скрипта на питоне, а пришло "
            f"{type(source).__name__}"))

    from kir.sandbox import execute_author_script

    # A separate thread: the sandbox is synchronous (subprocess + wall),
    # and running the event loop on it would mean hanging other people's
    # turns on someone else's loop.
    #
    # A TRIP ONLY FOR WHAT THE SCRIPT ASKED FOR — see
    # `_script_may_read_catalogue`.
    catalogue = (await _document_catalogue(llm_client, bridge_callback)
                 if _script_may_read_catalogue(source) else None)
    # THE BUILDING INDEX — by the same "only for what was asked" rule, but
    # with no trip at all: the document name was already sent by the
    # plugin, the elements sit on disk. Before 16.08.2026 this argument was
    # never passed by ANYONE, and on a live turn `building.*` always
    # answered «индекс не подан» — the capability had been built and never
    # wired up on the same day it was written.
    building = await asyncio.to_thread(_building_index_for_turn, source)
    supplied = args.get("params")
    if supplied is not None and not isinstance(supplied, dict):
        return _AuthoredInput(args=args, refusal=_form_refusal(
            f"`params` — это объект «имя ползунка -> значение», а пришло "
            f"{type(supplied).__name__}"))
    result = await asyncio.to_thread(
        execute_author_script, source, policy=_sandbox_policy(),
        model=catalogue, building=building, params=supplied)
    receipt = _authorship_receipt(
        result, source_bytes=len(source.encode("utf-8", "surrogatepass")))

    # 🔴 THE SEAM MEASURING COURSE UPTAKE. It sits HERE and only here:
    # every author run and both of its outcomes pass through this point —
    # the one that built a program, and the exploratory one (`KIR-B013`),
    # which by construction never reaches `record_witness`. The reason
    # this sink exists belongs to the function itself.
    try:
        from kir.coverage_feed import record_course_uptake
        # 🔴 THE TURN IS PASSED THROUGH, NOT LOST (23.08.2026, sink
        # measurement). `turn_id`/`query_id` had been in
        # `record_course_uptake`'s signature from the very start and
        # arrived EMPTY: 46 of 46 refusal rows and all 49 uptake rows
        # carried `null`. Only `source_digest` was filled in. The cost is
        # exactly one thing, and it is total: consecutive attempts by ONE
        # author in prod have nothing to link them by, and without that the
        # mission's main metric — "how many times checkability changed a
        # decision" — can only be counted on the bench, never on live
        # turns. Both doors (`handle_revit_ir`, `handle_revit_ir_bulk`)
        # hold these values and pass them to FIVE other places; here they
        # were not passed.
        record_course_uptake(result,
                             source_digest=str(receipt.get("author_digest") or ""),
                             turn_id=turn_id, query_id=query_id)
    except Exception:  # noqa: BLE001 — telemetry must not change the turn
        logger.debug("course uptake telemetry failed", exc_info=True)

    if not result.ok:
        return _AuthoredInput(
            args=args, from_script=True, author_digest=result.author_digest,
            env_digest=result.env_digest, model_digest=result.model_digest,
            params_digest=result.params_digest,
            building_digest=result.building_digest, receipt=receipt,
            refusal=_script_refusal_result(result.refusal, receipt,
                                          turn_id=turn_id,
                                          query_id=query_id))

    # The envelope the script set (`intent`/`defaults`/`allow_destructive`/
    # `ir_version`) arrives WHOLE: reassembling it here by eye would mean
    # losing what the author named explicitly.
    program = result.to_program()
    # PROVENANCE TRAVELS ONLY FROM HERE. On the sandbox-refusal path there
    # are no operations at all — there is nothing to attach the line to,
    # and an empty sidecar there is more honest than an empty dictionary
    # passed off as an answer.
    lineage = dict(result.lineage or {})
    return _AuthoredInput(
        args={"program": program}, from_script=True,
        author_digest=result.author_digest, env_digest=result.env_digest,
        model_digest=result.model_digest,
        params_digest=result.params_digest,
        building_digest=result.building_digest,
        lineage=lineage,
        source_lines=_lines_named_by(source, lineage),
        receipt=receipt)


# ═════════════════════════════════════════════════════════════════════════════
# BUILD-PLAN EXECUTOR — STEP 2
# ═════════════════════════════════════════════════════════════════════════════
#
# WHAT THIS CLOSES. Before this wave, a building could not be written as
# one script AT ALL: a script with `phase()` assembled fine in the
# sandbox, but on the compiler got two refusals at once — KIR-P003
# («неизвестное поле конверта 'phases'») and KIR-L002 («create_stairs —
# единственный оп своей программы»). The marking had been done and was
# UNREACHABLE, so `phase` was deliberately kept out of `POINTER`:
# advertising half a path costs the model a round the same way advertising
# a nonexistent name does. Here the second half is put in place, and the
# name enters the pointer together with it.
#
# WHAT EXACTLY IS LIFTED FROM THE MODEL. Exactly three things, each a
# measured refusal (corpus `kir_rejections.jsonl`, 1469 lines = 349
# authorship ATTEMPTS, 105 of them a program boundary):
#   * WHERE TO CUT. The budget and the solo-op limit are measured per
#     phase, not per script (`course.phase()`);
#   * WHAT IS ALREADY BUILT. A reference to a previous phase's element is
#     substituted IN BY ITSELF, with the real ElementId from that phase's
#     receipt — instead of retyping the id from the previous turn by hand;
#   * HOW MANY TURNS. A building of N phases is ONE model turn, not N.
#
# WHAT IS NOT HERE. No second door into Revit is added: every link goes
# through the same `_handle_revit_ir_inner` body as any single program
# does — with its own planning, grounding, witness inside the transaction,
# independent acceptance, and journal. The budget is not raised by a
# single unit. The `by=ref` reference still does not cross the boundary —
# what crosses it is the substituted `element_id`.
#
# A CHECKPOINT IS A PROMISE, AND IT IS KEPT LITERALLY. A phase is atomic;
# the failure of phase K does NOT roll back phases 0..K-1 — they are
# committed and stay. So the receipt must say WHICH phase to continue
# from: a plan repeated in full would build what was already built a
# second time. This is exactly what `resume_from` below is for, and
# exactly why `retryable` on such a refusal is FALSE.

PLAN_SCHEMA = "kir-plan/1"


def _plan_payload(result: Any) -> dict:
    """The bridge receipt, addressed by op ids — or empty.

    The same path `_result_contract_diagnostic` reads it by: the body's
    `result` carries the bridge's whole answer, and inside it the useful
    part sits under the key `result`. No parsing of its own is kept here.
    """
    if not isinstance(result, dict):
        return {}
    raw = result.get("result")
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("result", raw)
    return inner if isinstance(inner, dict) else {}


def _plan_step(link: Any, result: Any) -> dict:
    """One phase-report line. Numbers are machine numbers; nothing is interpreted."""
    outcome = result.get("outcome") if isinstance(result, dict) else None
    return {
        "index": link.index,
        "name": link.name,
        "ops": len(link.program.get("ops") or ()),
        "ok": bool(isinstance(result, dict) and result.get("ok")),
        # "Committed" is taken from the typed outcome, not from `ok`: a
        # write can be committed and NOT accepted (a violated
        # postcondition in `report` mode), and for the question "should
        # this phase be built again," it is the former that decides.
        "committed": bool(isinstance(outcome, dict)
                          and outcome.get("execution") == "committed"),
    }


def _plan_receipt(result: Any, steps: list[dict], total: int) -> Any:
    """Attach the `plan` block and SAY which phase to continue from.

    The receipt returned is that OF THE PHASE the plan ended on (the last
    one, if all of them passed) — whole, with all its fields. This is not
    an economy: `witness`, `outcome`, `acceptance`, and `certificate`
    describe ONE transaction, and folding them across several would mean
    inventing an outcome that none of them actually had. What belongs to
    the plan as a whole lives in `plan`, and only there.
    """
    if not isinstance(result, dict):
        return result
    built = [s for s in steps if s["committed"]]
    # WHERE THE PLAN STOPPED IS `ok`, NOT `committed`, AND THOSE ARE TWO
    # DIFFERENT NOTIONS OF "DONE." `_run_plan` stops on `ok`; the pointer
    # used to be computed from `committed`, and nothing forced them to
    # agree. Measured 11.08: a phase that WROTE and was NOT ACCEPTED (a
    # postcondition violated in `report` mode) produced a `resume_from`
    # pointing at the NEXT one — that is, the receipt told you to jump over
    # the phase that had stopped the plan, and the name on that same line
    # belonged to the previous one: "phase #2 b," where `b` is phase 1.
    stopped = next((s for s in steps if not s["ok"]), None)
    block = {
        "schema": PLAN_SCHEMA,
        "phases": total,
        "committed": len(built),
        # "NEVER RAN" IS ITS OWN COUNT. Phases the plan never reached are
        # absent from `steps`, and the reader used to have to subtract it
        # out themselves; and "failed" versus "never ran" have been
        # different facts this whole marathon.
        "never_started": max(0, total - len(steps)),
        "steps": steps,
    }
    resume = None
    if stopped is not None:
        block["stopped_at"] = stopped["index"]
        if stopped["committed"]:
            # THE ONE CASE WHERE THE POINTER WOULD BE A LIE EITHER WAY:
            # repeating the phase duplicates what was built, skipping it
            # leaves a violated postcondition in the building and says
            # nothing. Here a DECISION from the author is needed, and the
            # receipt must demand it rather than substitute a number.
            block["needs_decision"] = stopped["index"]
        else:
            resume = stopped["index"]
    elif len(steps) < total:
        # All phases reached were accepted, but the plan ended before the
        # table did.
        resume = len(steps)
    if resume is not None:
        block["resume_from"] = resume
    result["plan"] = block
    # THE RANGE OF WHAT WAS BUILT IS NAMED BY THE COUNT OF WHAT WAS BUILT,
    # NOT BY ARITHMETIC ON THE POINTER. This used to read `0..{resume - 1}`,
    # and on a refusal of phase ZERO the receipt printed "phases 0..-1
    # already in the model" — a claim about a range that cannot exist.
    kept = (f"фазы 0..{len(built) - 1} уже в модели" if built
            else "в модель ещё ничего не легло")
    tail = (f": построено фаз {len(built)} из {total}"
            + (f", не запускалось {block['never_started']}"
               if block["never_started"] else "")
            + f". ПОСТРОЕННОЕ ОСТАЁТСЯ — фаза атомарна, план нет. ПОВТОРЯТЬ "
              f"ПЛАН ЦЕЛИКОМ НЕЛЬЗЯ: {kept}, и второй прогон построит их "
              f"второй раз.")
    if stopped is None and resume is None:
        head = (f"ПЛАН ПОСТРОЕН ЦЕЛИКОМ: {total} фаз, "
                f"{sum(s['ops'] for s in steps)} операций, каждая фаза — своя "
                f"транзакция")
    elif stopped is not None and stopped["committed"]:
        # NEITHER REPEAT NOR SKIP. A pointer here would be a lie either way,
        # so there is none — instead there is a named question for the
        # author.
        head = (f"ФАЗА №{stopped['index']} «{stopped['name']}» ЗАПИСАЛА В "
                f"МОДЕЛЬ И НЕ БЫЛА ПРИНЯТА{tail} ЭТУ ФАЗУ НЕЛЬЗЯ НИ "
                f"ПОВТОРИТЬ (продублирует построенное), НИ ПРОПУСТИТЬ "
                f"(нарушенное постусловие останется в здании). НУЖНО РЕШЕНИЕ: "
                f"посмотри, что фаза построила, и либо доведи её правкой "
                f"модели, либо удали построенное ею и пришли план С НЕЁ.")
    else:
        at = stopped if stopped is not None else None
        index = at["index"] if at is not None else resume
        name = f" «{at['name']}»" if at is not None else ""
        head = (f"ПЛАН ВСТАЛ НА ФАЗЕ №{index}{name}{tail} СЛЕДУЮЩИЙ ХОД: "
                f"почини фазу №{index} и пришли план С НЕЁ.")
    result["message_ru"] = f"{head}\n{result.get('message_ru') or ''}".strip()
    if built and not result.get("ok"):
        # Repeating the plan in full would duplicate what was built. The
        # shared envelope treats a corrected KIR program as repeatable;
        # here it is the same strict case as a committed record, and
        # "build again" is decided not by the last link's outcome but by
        # the fact that the previous ones are already in the model.
        result["handoff"] = None
        _stamp_refusal(result)
        err = result.get("err")
        if isinstance(err, dict):
            err["retryable"] = False
    return result


def max_plan_phases() -> int:
    """The ceiling on the plan's PHASE COUNT — DERIVED from the session
    journal's capacity.

    WHAT THIS CLOSES (measured 11.08.2026, when the authored budget was 20;
    today it is 100, and that only strengthens the argument):
    `MAX_OPS_PER_PROGRAM` measures ONE link, and measures it correctly, but
    no one measured the number of links. So a plan bypassed the authored
    budget by multiplication: `split_phases` accepted 10 000 phases of 20
    ops each — 200 000 operations in 236 ms, without a single refusal.

    WHERE THE NUMBER COMES FROM. Every writing phase becomes ONE journal
    program (`plan_stream.publish` is called from the shared body on every
    phase), and the journal evicts the oldest ones. A plan longer than the
    journal EVICTS ITS OWN BEGINNING before it even finishes building, and
    everything that reads the journal then reads a building without a
    beginning: the verdict judges the tail, the clash batch loses its base,
    the viewer's `base_digest` diverges. This is exactly the boundary of
    the reasonable, and it was never assigned.

    ASKED FOR, NOT COPIED. The number lives with the journal and is
    configured by its own variable; a copy here would drift from the
    original on the very first edit — exactly the class of defect this
    series has spent all week closing.

    WHAT THE CEILING DOES NOT PROMISE: that eviction will not happen. A
    session that declared programs BEFORE the plan has already eaten part
    of the capacity, so the condition is NECESSARY, not sufficient; the
    after-the-fact truth is told by `programs_evicted`, and it stays in
    place.
    """
    from kir.live import journal as _live_journal

    return _live_journal._max_programs()


async def _run_plan(program: Any, llm_client, bridge_callback, *,
                    query_id: str, authored: "_AuthoredInput",
                    turn_id: str = "", action_id: str = "",
                    query_fingerprint: str = "",
                    source_kind: str = "unknown") -> dict:
    """Run the plan phase by phase: one phase — one program — one
    transaction.

    ORDER IS MANDATORY, AND IT IS THE AUTHOR'S OWN. Phases run in the
    order the script wrote them; there is nothing here to sort "by
    dependency" and no reason to — the order is ALREADY checked when each
    phase closes (`course._refuse_use_before_produce`: a producer must
    stand before its consumer), and a second sort would mean the author
    does not know in what order their building gets built.

    STOP ON THE FIRST FAILURE. Continuing after a failed phase is not
    allowed: the next one may reference its result, and "nothing to
    substitute" is, at best, a refusal, and at worst a wall built against
    the wrong element.
    """
    from kir import compiler as _compiler
    from kir.diag import KirRefusal as _KirRefusal

    # THE PHASE-COUNT CEILING — BEFORE A SINGLE WRITE. A refusal after the
    # first built phase would mean half the building in the model plus a
    # refusal chasing it; here nothing has started yet, and
    # `program_not_started()` is the truth, not a hope.
    _phases = program.get("phases") if isinstance(program, dict) else None
    _count = len(_phases) if isinstance(_phases, list) else 0
    if _count > max_plan_phases():
        return _with_outcome(
            {"ok": False, "kir": True, "refused": True, "stage": "plan",
             "diagnostics": [],
             "message_ru": (
                 f"ПЛАН ИЗ {_count} ФАЗ НЕ ПРИНЯТ: это больше вместимости "
                 f"журнала сессии ({max_plan_phases()} программ). Каждая "
                 f"пишущая фаза — одна программа журнала, поэтому такой план "
                 f"вытеснил бы СОБСТВЕННОЕ НАЧАЛО, ещё не достроившись: "
                 f"вердикт судил бы хвост здания, пачка коллизий потеряла бы "
                 f"базу, живой вид потребовал бы пересинхронизации посреди "
                 f"стройки. Бюджет ОДНОЙ фазы "
                 f"({_compiler.MAX_OPS_PER_PROGRAM} операций) при этом не "
                 f"меняется — режь здание на планы покороче и веди их "
                 f"последовательно."),
             "handoff": None},
            program_not_started())
    try:
        links = _compiler.split_phases(program)
    except _KirRefusal as refusal:
        return _with_outcome(
            {"ok": False, "kir": True, "refused": True, "stage": "plan",
             "diagnostics": [d.as_dict() for d in refusal.diagnostics],
             "message_ru": "\n".join(d.message_ru for d in refusal.diagnostics),
             "handoff": None},
            program_not_started())

    products: dict[str, int] = {}
    steps: list[dict] = []
    result: Any = None
    for link in links:
        try:
            body = _compiler.substitute_phase_results(link.program, products)
        except _KirRefusal as refusal:
            result = _with_outcome(
                {"ok": False, "kir": True, "refused": True, "stage": "plan",
                 "diagnostics": [d.as_dict() for d in refusal.diagnostics],
                 "message_ru": "\n".join(d.message_ru
                                         for d in refusal.diagnostics),
                 "handoff": None},
                program_not_started())
            steps.append({**_plan_step(link, result), "ok": False})
            break
        result = await _handle_revit_ir_inner(
            {"program": body}, llm_client, bridge_callback,
            query_id=query_id, bulk=False,
            turn_id=turn_id, action_id=action_id,
            query_fingerprint=query_fingerprint,
            source_kind=source_kind,
            authored_in_python=authored.from_script,
            author_digest=authored.author_digest,
            env_digest=authored.env_digest,
            lineage=authored.lineage,
            source_lines=authored.source_lines)
        step = _plan_step(link, result)
        steps.append(step)
        if not step["ok"]:
            break
        products.update(_compiler.phase_products(
            body.get("ops") or (), _plan_payload(result)))
    return _plan_receipt(result, steps, len(links))


# ═════════════════════════════════════════════════════════════════════════
# ОДОБРЕНИЕ СЛИВАЕТСЯ В ЗДАНИЕ, А НЕ КЛАДЁТСЯ ПОВЕРХ НЕГО
#
# 🔴 СЛОВО ВЛАДЕЛЬЦА 13.09.2026, дословно: «когда мы тыкаем во вьюере одобрить,
# то оно грамотно мержится в основное здание». «Грамотно» здесь — это ровно
# одно проверяемое свойство: одобрение программы, чьи выходы В ЭТОМ ДОКУМЕНТЕ
# УЖЕ СТОЯТ, не имеет права построить их второй раз.
#
# ВТОРОГО ИСТОЧНИКА ПРАВДЫ ЗДЕСЬ НЕТ И НЕ ЗАВОДИТСЯ. Решение keep/update/
# create/replace/delete принимает `project_republish.plan_republish` (надел S),
# производную программу собирает `project_republish_program.republish_program`
# (S), прошлую публикацию выводит из store `republish_archive.
# previous_from_stored_publication` (N). Эта функция не решает НИЧЕГО — она
# только соединяет три готовых звена и переводит их числа в русскую фразу.
# Повторить их решение здесь значило бы завести ровно тот дефект, против
# которого весь модуль повторной публикации и написан.
#
# 🔴 ЧЕГО НА ЭТОМ ТРАКТЕ СЕГОДНЯ НЕТ — И ЭТО СКАЗАНО ВСЛУХ, А НЕ ОБОЙДЕНО.
# Перенос исполняет ОПЕРАЦИИ прямо в Ревит (`revit_ir`), а не публикацию в
# `ProjectStore`: замерено 13.09.2026 — `grep -rn "ProjectStore|create_publication"
# backend/kukai/**/*.py` даёт НОЛЬ непроверочных вхождений. Значит адреса
# прошлой публикации этого документа у двери просто нет, и без неё сравнивать
# не с чем. Такой случай называется `no_previous_publication` и ведёт себя
# как сегодня — обычный перенос create, — но ГОВОРИТ об этом человеку:
# молчание тут читается как «повтор безопасен», а он не безопасен.
# ─────────────────────────────────────────────────────────────────────────

#: Что вернулось из слияния — закрытый список, чтобы «неизвестно» было
#: непроизносимо.
REPUBLISH_ACTIONS = ("no_previous_publication", "nothing_to_send", "merged")


def _republish_counts_ru(counts: dict) -> str:
    """Числа плана — фразой. Порядок: что построится, что обновится, что
    останется нетронутым. Нетронутое названо НЕ в последнюю очередь из
    вежливости: «уже стоит 5» — это и есть ответ на «не построит ли оно
    вторую стену поверх первой»."""
    части = []
    for ключ, слово in (("create", "построится"), ("update", "обновится"),
                        ("replace", "пересоздастся"), ("delete", "удалится"),
                        ("keep", "уже стоит и не тронется")):
        число = int(counts.get(ключ) or 0)
        if число:
            части.append(f"{слово}: {число}")
    return " · ".join(части) or "изменений нет"


def republish_for_transfer(program, previous=None, *, store=None,
                           publication_digest: str = "") -> dict:
    """Программа к переносу + прошлая публикация этого документа → что слать.

    `previous` — уже прочитанная прошлая публикация (`{"program": …,
    "identity": …}`), либо `None`. `publication_digest` вместе со `store` —
    адрес прошлой публикации, который будет прочитан ПРОДУКТОВЫМ путём
    (`republish_archive.previous_from_stored_publication`), а не заново
    выведен здесь.

    Возвращает словарь с `action` из `REPUBLISH_ACTIONS`, программой к
    отправке, числами плана и русской фразой. Отказ звена приходит полем
    `refusal` — по ИМЕНИ и со следующим ходом, а не исключением наружу:
    одобрение, упавшее молча, человек читает как «кнопка не работает».
    """
    пусто = {"ok": True, "action": "no_previous_publication", "program": program,
             "counts": {}, "plan_digest": "",
             "message_ru": ("прошлой публикации этого документа не записано — "
                            "переносится как новое; если это повтор, "
                            "одобрение построит вторую копию"),
             "next_ru": ("Следующий ход: если программа уже переносилась, "
                         "отклоните и постройте её заново одним ходом — "
                         "сравнить не с чем.")}
    if not isinstance(program, dict) or not isinstance(program.get("ops"), list):
        # Не программа — не наше дело: пусть об этом скажет тот, чья это
        # проверка. Молча «починить» вход здесь значило бы спрятать чужой отказ.
        return {**пусто, "action": "no_previous_publication", "program": program}
    if previous is None and not (store is not None and publication_digest):
        return пусто

    from kir.project_republish import RepublishError, plan_republish
    from kir.project_republish_program import (RepublishProgramError,
                                               republish_program)
    from kir.republish_archive import (RepublishArchiveError,
                                       previous_from_stored_publication)

    def _refusal(code: str, ru: str, next_ru: str) -> dict:
        return {"ok": False, "action": "refused", "refusal_code": code,
                "refusal": _typed_error("republish", ru),
                "message_ru": ru, "next_ru": next_ru}

    try:
        if previous is None:
            previous = previous_from_stored_publication(store, publication_digest)
        plan = plan_republish(store, program, previous)
        derived = republish_program(plan, program)
    except RepublishArchiveError as failure:
        return _refusal(
            getattr(failure, "code", "previous_publication_unreadable"),
            f"прошлую публикацию прочитать не удалось: {failure}",
            "Следующий ход: сверьте адрес прошлой публикации; считать её "
            "несуществующей и строить заново — это дубль поверх стоящего.")
    except RepublishError as failure:
        return _refusal(
            getattr(failure, "code", "republish_plan_refused"),
            f"план повторной публикации отказал: {failure}",
            "Следующий ход: отклоните это одобрение и постройте программу "
            "заново — она перестала быть повтором прежней.")
    except RepublishProgramError as failure:
        return _refusal(
            getattr(failure, "code", "republish_program_refused"),
            f"производную программу собрать не удалось: {failure}",
            "Следующий ход: отклоните одобрение; слияние без дублей "
            "невозможно, а перенос как есть построил бы вторую копию.")

    counts = dict(plan.counts())
    ops = list((derived.program or {}).get("ops") or ())
    фраза = _republish_counts_ru(counts)
    if not ops:
        # ОТПРАВЛЯТЬ НЕЧЕГО — ЭТО ИСХОД, А НЕ ОШИБКА. Программа уже стоит в
        # документе целиком; выполнить её значило бы построить её второй раз.
        return {"ok": True, "action": "nothing_to_send", "program": derived.program,
                "counts": counts, "plan_digest": plan.digest,
                "message_ru": ("это уже стоит в модели — переносить нечего "
                               f"({фраза}). В Revit НИЧЕГО НЕ ЗАПИСАНО."),
                "next_ru": ("Следующий ход: менять нечего; если нужно другое — "
                            "скажите, что именно поменять.")}
    return {"ok": True, "action": "merged", "program": derived.program,
            "counts": counts, "plan_digest": plan.digest,
            "expected_identities": len(derived.expected_identities),
            "destructive": bool(derived.destructive),
            "message_ru": (f"сливается в существующее здание — {фраза}; "
                           "поверх стоящего ничего не создаётся"),
            "next_ru": ""}


async def handle_revit_ir(args: Any, llm_client, bridge_callback,
                          query_id: str = "", *,
                          turn_id: str = "", action_id: str = "",
                          query_fingerprint: str = "",
                          source_kind: str = "unknown",
                          timeout_ms: int | None = None,
                          previous_publication: Any = None,
                          publication_store: Any = None,
                          publication_digest: str = "") -> dict:
    """THE CHAT DOOR — the tool's public entry point. A thin wrapper over
    the body: the ONLY place where a refusal gets the machine-readable
    `err` block.

    A wrapper, not an edit to every `return`, because refusal paths here
    number more than a dozen and keep growing: a structural rule cannot be
    forgotten when applied, a list of places can be (and that is exactly
    how `err` never showed up on any of them).

    THE BUDGET HERE IS ALWAYS THE AUTHORED ONE
    (`compiler.MAX_OPS_PER_PROGRAM`; on this tree it is **100**, measured
    17.08.2026 — the number is deliberately NOT hard-coded here as a
    literal precisely because the previous literal, "20," went stale and
    outlived its truth). This function HAS NO parameter that could raise
    it — and that is not an oversight, it is by design: an agreement "don't
    pass the flag" gets forgotten, an absent parameter does not. Everything
    the model puts into the input lands in `args`; not one `args` field is
    read here as a budget switch, so "asking for bulk" from chat is
    impossible BY CONSTRUCTION (see tests/test_op_budget_seam.py).

    A CAVEAT TO READ TOGETHER WITH THE PREVIOUS PARAGRAPH: `program_py`
    raises the PRE-MACRO budget to the internal one — see
    `authored_in_python` in the body, where the justification also lives.
    The paragraph above stays true word for word: no field raises the
    ENUMERATION budget, because enumeration is exactly what that budget
    measures.

    THE SECOND MODE — `example`: SHOW A SAMPLE WITHOUT WRITING ANYTHING.
    The justification is in `_example_for_turn`; the one thing that
    matters here is that it stands BEFORE `_authored_input`, because that
    one refuses a call with no program on form, while "show a sample" is a
    legitimate call without a program."""
    if _example_only(args):
        # 🔴 THE GATE STANDS HERE TOO, AND THIS IS NOT DUPLICATION. The
        # body (`_handle_revit_ir_inner`) checks three gate conditions, and
        # a sample never reaches the body — it is returned one line above
        # it. Measured 17.08.2026: with an EMPTY list of admitted devices,
        # a `program` call was refused by the gate, while an `example`
        # call handed back the corpus.
        #
        # There is no live path to it today — the tool schema is not
        # inlined while the gate is closed (`llm/client.py`), and the
        # admin route pins the device itself. That is exactly why the hole
        # survived: "won't reach the door" is a claim about the CALLERS,
        # not about the door, and it stops being true the day a third
        # caller appears. And what we hand back meanwhile is the SOURCE of
        # someone else's production building from the corpus.
        if not revit_ir_enabled():
            return _stamp_refusal(
                _typed_error("gate", admin_gate_message_ru("revit_ir")))
        return await asyncio.to_thread(_example_for_turn, args.get("example"))
    # THE FOURTH MODE — "WHAT HAVE I ALREADY CREATED." It stands next to
    # the sample and for the same reason: it needs no program, and a call
    # without a program is legitimate.
    if _created_only(args):
        # 🔴 THE GATE BELONGS HERE TOO — BY THE SAME ARGUMENT AS THE LINE
        # ABOVE (30.08.2026, audit finding F-013). The body
        # (`_handle_revit_ir_inner`) NEVER REACHES this mode: it returns
        # earlier, just like the sample does. The tree already caught
        # exactly this defect on 17.08 and closed it for `example`, naming
        # the reason directly: "'won't reach the door' is a claim about
        # the CALLERS, not about the door, and it stops being true the day
        # a third caller appears." The `created` mode was introduced AFTER
        # that fix and repeated the hole word for word.
        #
        # COVERAGE MEASURED ON THE LIVE REGISTRY (30.08.2026, 1990 lines,
        # 44 086 elements): the unclosed door handed back up to 200 lines /
        # 165 elements — of ITS OWN device, not someone else's (the scope
        # is narrowed by F-299). Not a fleet leak, but not zero either:
        # data leaves wherever the gate refuses.
        if not revit_ir_enabled():
            return _stamp_refusal(
                _typed_error("gate", admin_gate_message_ru("revit_ir")))
        return _created_answer()
    authored = await _authored_input(args, llm_client, bridge_callback,
                                     turn_id=turn_id, query_id=query_id)
    if authored.refusal is not None:
        return _stamp_refusal(_stamp_authorship(authored.refusal, authored))
    # THE THIRD MODE — "REHEARSE AND DON'T WRITE." It stands AFTER
    # `_authored_input`, not next to `example`: there is nothing to
    # rehearse without a program, and that is exactly where Python becomes
    # operations. Neither a trip nor a transaction follows from here.
    if _rehearse_only(args):
        _prog = authored.args.get("program") if isinstance(
            authored.args, dict) else None
        _block = _rehearsal_block(_prog)
        if _block is None:
            return _stamp_authorship(_form_refusal(
                "репетиция не собралась: программа не разобрана"), authored)
        return _stamp_authorship(
            {"ok": True, "kir": True, "wrote_nothing": True,
             "rehearsal": _block,
             "rehearsal_note_ru": _rehearsal_note_ru(_block)}, authored)
    # The mark is taken BEFORE the body: the journal write sits inside it,
    # and "did the journal grow" is the only honest answer to "did this
    # turn add to the building." For a plan it must span ALL phases: the
    # building is judged as a batch, and a verdict after each phase
    # separately would speak of an unfinished house.
    # ── ОДОБРЕНИЕ СЛИВАЕТСЯ, А НЕ НАКЛАДЫВАЕТСЯ (13.09.2026) ──────────────
    # Только для `source_kind="transfer"`: это ход ЧЕЛОВЕКА, нажавшего
    # «Одобрить» в окне КИР, и только у него есть смысл спрашивать «а это
    # уже стоит?». Ход модели идёт прежним путём БАЙТ В БАЙТ: у него нет ни
    # адреса прошлой публикации, ни права её выбирать.
    republish = None
    if source_kind == "transfer" and isinstance(authored.args, dict):
        republish = republish_for_transfer(
            authored.args.get("program"), previous_publication,
            store=publication_store, publication_digest=publication_digest)
        if republish.get("refusal") is not None:
            # Отказ звена повторной публикации — по ИМЕНИ и со следующим
            # ходом. Построить «как есть» после такого отказа значило бы
            # сделать ровно то, от чего он защищает.
            отказ = dict(republish["refusal"])
            отказ["republish"] = {k: v for k, v in republish.items()
                                  if k != "refusal"}
            отказ.setdefault("next_ru", republish.get("next_ru", ""))
            return _stamp_refusal(_stamp_authorship(отказ, authored))
        if republish.get("action") == "nothing_to_send":
            # НЕЧЕГО СЛАТЬ — ЭТО ИСХОД. Ни поездки, ни транзакции: программа
            # уже стоит в документе целиком, и «выполнить» её значит
            # построить второй раз.
            return _stamp_refusal(_stamp_authorship({
                "ok": True, "kir": True, "wrote_nothing": True,
                "republish": {k: v for k, v in republish.items()
                              if k not in ("refusal", "program")},
                "message_ru": republish["message_ru"],
                "next_ru": republish["next_ru"],
            }, authored))
        if republish.get("action") == "merged":
            # ИСПОЛНЯЕТСЯ ПРОИЗВОДНАЯ, А НЕ СЫРАЯ. Подменяется именно то,
            # что поедет в компилятор, — иначе «слито без дублей» было бы
            # словами о программе, которую никто не запускал.
            authored.args["program"] = republish["program"]
    watch = _building_watch()
    # PLAN OR PROGRAM — THE ENVELOPE DECIDES, NOT AN INPUT FLAG. The
    # `phases` table is placed by `course.take_ops()` when the author drew
    # at least one boundary; its absence leaves the path BYTE FOR BYTE
    # unchanged, and that is a condition, not a taste
    # (`test_phases`: "absence stays absence").
    program = authored.args.get("program") if isinstance(
        authored.args, dict) else None
    if isinstance(program, dict) and program.get("phases") is not None:
        return _order_receipt(_stamp_self_check(_stamp_rehearsal(_stamp_revit_version(_stamp_refusal(
            _stamp_authorship(
                await _stamp_building_verdict(
                    await _run_plan(program, llm_client, bridge_callback,
                                    query_id=query_id, authored=authored,
                                    turn_id=turn_id, action_id=action_id,
                                    query_fingerprint=query_fingerprint,
                                    source_kind=source_kind),
                    watch),
                authored)), llm_client), program), program))
    outcome = _order_receipt(_stamp_self_check(_stamp_rehearsal(_stamp_revit_version(_stamp_refusal(
        _stamp_authorship(
            await _stamp_building_verdict(
                await _handle_revit_ir_inner(
                    authored.args, llm_client, bridge_callback,
                    query_id=query_id, bulk=False,
                    turn_id=turn_id, action_id=action_id,
                    query_fingerprint=query_fingerprint,
                    source_kind=source_kind,
                    timeout_ms=timeout_ms,
                    authored_in_python=authored.from_script,
                    author_digest=authored.author_digest,
                    env_digest=authored.env_digest,
                    lineage=authored.lineage,
                    source_lines=authored.source_lines),
                watch),
            authored)), llm_client), program), program))
    if republish is not None and isinstance(outcome, dict):
        # СЛОВА О СЛИЯНИИ ЕДУТ С КВИТАНЦИЕЙ, А НЕ ВМЕСТО НЕЁ. Ставится
        # additive: ветка, знающая свой текст точнее, не переписывается —
        # то же правило, что у `next_ru`.
        outcome["republish"] = {k: v for k, v in republish.items()
                                if k not in ("refusal", "program")}
        if republish.get("message_ru") and not str(
                outcome.get("message_ru") or "").strip():
            outcome["message_ru"] = republish["message_ru"]
    return outcome


async def handle_revit_ir_bulk(args: Any, llm_client, bridge_callback,
                               query_id: str = "", *,
                               turn_id: str = "", action_id: str = "",
                               query_fingerprint: str = "",
                               source_kind: str = "unknown",
                               timeout_ms: int | None = None) -> dict:
    """THE INTERNAL DOOR — the same prod path, but the materializer's chunk
    budget.

    WHY. Parsing the Snowdon Towers sample gave 6 343 elements and chunks
    of 250 ops each (`decompile.materialize`), while the one live door
    measured them against the authored budget of 20 — the live rebuild on
    30.07 cost 318 rounds instead of 26. Two halves of the system were
    counting against different budgets. Measured against a stored parse
    (`snowdon_plumb_v2/tree.json`, 6 544 L1 leaves): chunk_target=20 gives
    317 programs, the materializer's default gives 26, ops in both cases:
    6 335.

    WHY A SEPARATE FUNCTION, NOT A FLAG ON `handle_revit_ir`. A flag on the
    public door is an input field, and an input field sooner or later
    arrives from the tool's arguments. A separate NAME cannot be uttered by
    accident: the chat loop (`kukai/llm`) does not know it, and that is
    checked by a test, not a promise.

    BOUNDARIES. Available only to the admin route `/admin/kir/*`. Two
    checkpoints: the shared stage-2 gate (flag + admin device, same as the
    chat door) and a SEPARATE admin-device check here — it keeps the door
    closed even where the shared gate is someday loosened.

    WHAT CHANGES. Only the pre-macro budget and the chunk compilation
    policy (`compiler.compile_rebuild_chunk`: bulk + per_op + de-join — one
    fact, named once). The post-macro ceiling `MAX_VALIDATED_OPS` is
    touched by NOTHING here: that is the emitter's limit, not a policy."""
    if not is_admin_device(_turn_device_id()):
        # The second checkpoint. Separate from revit_ir_enabled(): that one
        # also reads the tool flag, while "internal entry only from the
        # admin device" is a claim that must not depend on the flag's
        # value.
        return _typed_error("gate", admin_gate_message_ru("revit_ir (bulk)"))
    authored = await _authored_input(args, llm_client, bridge_callback,
                                     turn_id=turn_id, query_id=query_id)
    if authored.refusal is not None:
        return _stamp_refusal(_stamp_authorship(authored.refusal, authored))
    # The mark is taken BEFORE the body — under exactly the same watch as
    # the chat door: the journal write sits inside the body, and "did the
    # journal grow" is the only honest answer to "did this turn add to the
    # building." There is no VERDICT here, and there will not be (the
    # author is a materializer, the receipt has no reader), but there IS a
    # CLASH AUDIT: these are different things, and `live/verdict.py` keeps
    # them apart.
    watch = _building_watch()
    # THE THIRD MODE here too: an unattended door must also be able to
    # rehearse without writing. Otherwise the benches are left without
    # their one free check.
    if _rehearse_only(args):
        _prog = authored.args.get("program") if isinstance(
            authored.args, dict) else None
        _block = _rehearsal_block(_prog)
        if _block is None:
            return _stamp_authorship(_form_refusal(
                "репетиция не собралась: программа не разобрана"), authored)
        return _stamp_authorship(
            {"ok": True, "kir": True, "wrote_nothing": True,
             "rehearsal": _block,
             "rehearsal_note_ru": _rehearsal_note_ru(_block)}, authored)
    # SELF-CHECK APPLIES HERE TOO, UNLIKE THE BUILDING VERDICT. Excluding
    # the admin door from the verdict is a decision that stands, with its
    # own argument ("the author here is a rebuild materializer, not the
    # model, and the receipt has no reader," `live/verdict.py`). That
    # argument does NOT carry over to self-check, for the same reason it
    # did not carry over to the clash: it judges not the accumulated
    # building but the DECLARED program, and a rebuild that declared
    # something unfit is broken regardless of whether anyone is being
    # taught. The cost is named: 5.9 ms per program, the
    # `_SELF_CHECK_OPS_CAP` ceiling quenches chunks larger than 1200 ops,
    # NAMED.
    return _stamp_self_check(_stamp_rehearsal(_stamp_revit_version(_stamp_refusal(_stamp_authorship(
        await _stamp_building_clash(
            await _handle_revit_ir_inner(
                authored.args, llm_client, bridge_callback,
                query_id=query_id, bulk=True,
                turn_id=turn_id, action_id=action_id,
                query_fingerprint=query_fingerprint,
                source_kind=source_kind,
                timeout_ms=timeout_ms,
                authored_in_python=authored.from_script,
                author_digest=authored.author_digest,
                env_digest=authored.env_digest,
                lineage=authored.lineage,
                source_lines=authored.source_lines),
            watch),
        authored)), llm_client), (authored.args or {}).get("program")
        if isinstance(authored.args, dict) else None),
        (authored.args or {}).get("program")
        if isinstance(authored.args, dict) else None)


# ═════════════════════════════════════════════════════════════════════════════
# THE DIRECT-TURN CHUNK DRIVER
#
# The law of chunking lives in `kir/chunking.py` and is NOT repeated here:
# a chunk is a contiguous slice in AUTHORED order, because an authored
# program's references always point backward. Here it is plan execution
# and ONE receipt for the whole program.
#
# THREE INPUT FORMS, ONE CUT POINT. The chat door, the admin
# `handle_revit_ir_bulk`, and the scripted one (`program_py`) converge on
# one body, and they converge ALREADY AS OPERATIONS: Python becomes them
# in `_authored_input`, that is, BEFORE the body. So a script's output is
# chunked by the same code, and it needs no separate tap of its own — and
# this is stated here, not in the body, because the body is structurally
# forbidden to know the language of origin.
#
# 🔴 THE MAIN THING THIS RECEIPT MUST SAY IS WHAT IT NO LONGER HAS. A
# program has stopped being one transaction: a Revit transaction lives
# inside a single C# execution and does not survive a trip to the bridge,
# and neither does `TransactionGroup`. So a refusal on chunk k means
# chunks 1..k-1 are ALREADY IN THE MODEL and NOT ROLLED BACK. A silent
# "built halfway" is the worst outcome this compiler allows, and it is
# forbidden here by THREE TOP-LEVEL SCALARS (`atomicity`,
# `atomicity_note_ru`, `chunked_note_ru`), not by a dictionary: measured
# 15.08.2026 against the real history collapser, it showed that ANY
# dictionary at ANY level turns into "<object, N fields — collapsed>,"
# while a scalar gets through. A weakening named only inside the
# `chunked` block would evaporate after thirty messages — that is, it
# would be named exactly where no one will read it.
# ═════════════════════════════════════════════════════════════════════════════

#: Schema of the `chunked` block in the receipt.
CHUNKED_SCHEMA = "kir-forward-chunking/1"

#: A reference across a chunk boundary was not resolved by previous
#: chunks' receipts. A separate code from KIR-K001 («операция крупнее
#: бюджета»), because the fix differs: keep the op and its readers in one
#: chunk, or address the element explicitly by `element_id`.
KIR_CHUNK_BIND_FAILED = "KIR-K002"

#: The chunk was refused, while the previous ones are already in the model.
KIR_CHUNK_PARTIAL = "KIR-K003"


def _chunk_sub_args(args: Any, ops: list) -> dict:
    """Arguments for ONE chunk: the author's envelope in full, operations —
    only the slice.

    The envelope (`intent`, `defaults`, `allow_destructive`, `ir_version`)
    travels into EVERY chunk verbatim: it is the author's declaration
    about the whole program, and losing it on a slice would mean building
    chunks by different rules than what was written.

    What does NOT travel, and why: `program_py` (the script has already
    become operations — a second carrier of the same intent), `params`
    (the slider is a capability of the SOURCE, there is nothing to bind it
    to in a slice), and a non-nested top-level `ops` field (otherwise the
    slice would have two carriers of operations, and which one is the
    truth would be decided by read order).
    """
    program = args.get("program") if isinstance(args, dict) else None
    if program is None and isinstance(args, dict) and "ops" in args:
        program = args
    envelope = (
        {k: v for k, v in program.items()
         if k not in ("ops", "program", _SCRIPT_FIELD, "params")}
        if isinstance(program, Mapping) else {}
    )
    sub: dict = dict(args) if isinstance(args, dict) else {}
    sub.pop(_SCRIPT_FIELD, None)
    sub.pop("params", None)
    sub.pop("ops", None)
    sub["program"] = {**envelope, "ops": list(ops)}
    return sub


def _fold_chunk_outcomes(outcomes: Sequence[Any], *,
                         all_ok: bool) -> ProgramOutcome:
    """One outcome for the program, assembled from its chunks' outcomes.

    THERE IS ONE RULE, AND IT FAVORS SAFETY AGAINST REPEATS: if even one
    chunk is committed, the program is `committed`, i.e. `retry:
    forbidden`. Repeating it whole would duplicate what was built, and
    `unconfirmed` (`verify_first`) would be WEAKER KNOWLEDGE THAN WHAT WE
    ALREADY HAVE: we know for certain that the model was changed.
    Knowledge about the effect must not be weakened for the sake of a tidy
    aggregate.
    """
    execs: list = []
    wits: list = []
    accs: list = []
    for item in outcomes:
        if not isinstance(item, Mapping):
            continue
        try:
            execs.append(ExecutionState(str(item.get("execution"))))
            wits.append(WitnessState(str(item.get("witness"))))
            accs.append(AcceptanceState(str(item.get("acceptance"))))
        except ValueError:                 # a foreign shape — we don't guess
            continue
    if not execs:
        return program_not_started()

    if ExecutionState.COMMITTED in execs:
        execution = ExecutionState.COMMITTED
    elif ExecutionState.UNCONFIRMED in execs:
        execution = ExecutionState.UNCONFIRMED
    elif ExecutionState.ROLLED_BACK in execs:
        execution = ExecutionState.ROLLED_BACK
    elif ExecutionState.READ_COMPLETED in execs:
        execution = ExecutionState.READ_COMPLETED
    else:
        return program_not_started()

    if all_ok and wits and all(w is WitnessState.SATISFIED for w in wits):
        witness = WitnessState.SATISFIED
    elif WitnessState.VIOLATED in wits:
        witness = WitnessState.VIOLATED
    else:
        witness = WitnessState.INCOMPLETE
    if execution is ExecutionState.UNCONFIRMED:
        # Outcome algebra: an unconfirmed execution has no right to carry
        # a verdict.
        witness = WitnessState.INCOMPLETE

    named = [a for a in accs if a is not AcceptanceState.NOT_APPLICABLE]
    if execution is ExecutionState.READ_COMPLETED:
        acceptance = AcceptanceState.NOT_APPLICABLE
    elif (all_ok and named and witness is WitnessState.SATISFIED
            and execution is ExecutionState.COMMITTED
            and all(a is AcceptanceState.ACCEPTED for a in named)):
        acceptance = AcceptanceState.ACCEPTED
    elif (AcceptanceState.REJECTED in named
            and execution is ExecutionState.COMMITTED):
        acceptance = AcceptanceState.REJECTED
    elif named and all(a is AcceptanceState.NOT_RUN for a in named):
        acceptance = AcceptanceState.NOT_RUN
    elif not named:
        acceptance = AcceptanceState.NOT_RUN
    else:
        acceptance = AcceptanceState.INCONCLUSIVE

    try:
        return ProgramOutcome(execution, witness, acceptance)
    except (TypeError, ValueError):
        # The aggregate has NO RIGHT to downgrade a build that already
        # happened. We fall back to the strongest knowledge of the effect
        # that we have.
        logger.debug("chunked outcome fold refused by the algebra",
                     exc_info=True)
        if execution is ExecutionState.COMMITTED:
            return write_committed(witness=WitnessState.INCOMPLETE)
        return execution_unconfirmed()


def _chunked_note_ru(total: int, executed: int,
                     failed_at: int | None) -> str:
    """The weakening of atomicity as A FLAT STRING that survives history.

    The word `per_chunk` is a label; this is its consequence. The author
    must learn not the term but the fact: what stands in the model right
    now, and what a repeat will do.
    """
    if failed_at is None:
        return (
            "чанков %d, построены все: программа шла %d ТРАНЗАКЦИЯМИ, а не "
            "одной — если понадобится отменить, отменять придётся каждую"
            % (total, total))
    return (
        "ОТКАЗ НА ЧАНКЕ %d ИЗ %d. Чанки 1..%d (%d из %d) УЖЕ В МОДЕЛИ и НЕ "
        "ОТКАЧЕНЫ: программа шла отдельными транзакциями, и прежнего «всё или "
        "ничего» здесь нет. Их элементы названы в `element_map` этой "
        "квитанции. ПОВТОР ПРОГРАММЫ ЦЕЛИКОМ ПРОДУБЛИРУЕТ ПОСТРОЕННОЕ — "
        "продолжай с чанка %d либо убери за собой по этим номерам"
        % (failed_at + 1, total, failed_at, executed, total, failed_at + 1))


async def _drive_chunked_program(plan, *, args, llm_client, bridge_callback,
                                 query_id: str, bulk: bool, turn_id: str,
                                 action_id: str, query_fingerprint: str,
                                 source_kind: str, authored_in_python: bool,
                                 author_digest: str, env_digest: str,
                                 lineage: dict | None = None,
                                 source_lines: dict | None = None) -> dict:
    """Execute the chunk plan IN ORDER and assemble ONE receipt.

    Order is part of the intent (Revit is not indifferent to it: a room
    needs walls already standing), so chunks run strictly by index and
    the first refusal STOPS the program. Continuing after a refusal would
    mean building on top of what never got built — and accumulating a
    discrepancy in silence.

    Between chunks, a BACKWARD reference becomes a number: `bind_refs`
    substitutes the `element_id` from the accumulated map of receipts. A
    reference within a chunk stays a reference — the compiler resolves
    it, as it always has.
    """
    from kir import chunking as _chunking

    total = len(plan.chunks)
    element_map: dict = {}
    rows: list[dict] = []
    outcomes: list = []
    failed_at: int | None = None
    failed_diag: dict | None = None

    for chunk in plan.chunks:
        row: dict = {"index": chunk.index, "ops": len(chunk.ops),
                     "est_bytes": chunk.est_bytes, "reason": chunk.reason,
                     "needs": list(chunk.needs)}
        try:
            bound = _chunking.bind_refs(chunk, element_map)
        except (KeyError, ValueError) as exc:
            message = str(exc.args[0] if exc.args else exc)
            row.update({"ok": False, "stage": "bind_refs",
                        "message_ru": message})
            rows.append(row)
            failed_at = chunk.index
            failed_diag = {"code": KIR_CHUNK_BIND_FAILED,
                           "op_id": None,
                           "message_ru": message}
            break
        stage_token = _JOURNAL_STAGE_DEFERRED.set(True)
        try:
            res = await _handle_revit_ir_inner(
                _chunk_sub_args(args, bound), llm_client, bridge_callback,
                query_id=query_id, bulk=bulk, turn_id=turn_id,
                action_id=action_id, query_fingerprint=query_fingerprint,
                source_kind=source_kind, authored_in_python=authored_in_python,
                author_digest=author_digest, env_digest=env_digest,
                # PROVENANCE SURVIVES THE CHUNK BOUNDARY: the sidecar is
                # keyed by the op's `id`, and slicing does not touch `id`.
                # A chunk carries the WHOLE dictionary — a surplus key is
                # harmless, a lost one would cost the author an address
                # exactly where the program is large and searching costs
                # the most.
                lineage=lineage, source_lines=source_lines,
                chunk_of=(chunk.index, total))
        finally:
            _JOURNAL_STAGE_DEFERRED.reset(stage_token)
        res = res if isinstance(res, Mapping) else {}
        row["ok"] = res.get("ok") is True
        row["stage"] = res.get("stage") or "execute"
        if res.get("witness") is not None:
            row["witness"] = res.get("witness")
        if isinstance(res.get("outcome"), Mapping):
            outcomes.append(res["outcome"])
        chunk_map = res.get("element_map")
        if isinstance(chunk_map, Mapping) and chunk_map:
            element_map.update(chunk_map)
            row["element_map"] = dict(chunk_map)
            row["elements_note_ru"] = element_map_note(chunk_map)
        elif res.get("element_map_error"):
            row["element_map_error"] = res.get("element_map_error")
        rows.append(row)
        if not row["ok"]:
            diags = res.get("diagnostics")
            head = diags[0] if isinstance(diags, list) and diags else {}
            failed_at = chunk.index
            failed_diag = {
                "code": (head.get("code") if isinstance(head, Mapping)
                         else None) or KIR_CHUNK_PARTIAL,
                "op_id": (head.get("op_id") if isinstance(head, Mapping)
                          else None),
                "message_ru": (res.get("message_ru")
                               or (head.get("message_ru")
                                   if isinstance(head, Mapping) else "")
                               or "чанк отказал без сообщения"),
            }
            break

    executed = sum(1 for r in rows if r.get("ok"))
    all_ok = failed_at is None and executed == total
    outcome = _fold_chunk_outcomes(outcomes, all_ok=all_ok)

    note = _chunked_note_ru(total, executed, failed_at)
    result: dict = {
        "ok": all_ok,
        "kir": True,
        "stage": "chunked",
        "witness": outcome.witness.value,
        # THE THREE TOP-LEVEL SCALARS — see the section header above. The
        # `chunked` dictionary below is machine-generated and complete;
        # these three survive history collapsing.
        "atomicity": plan.atomicity,
        "atomicity_note_ru": plan.atomicity_note_ru,
        "chunked_note_ru": note,
        "chunked": {
            "schema": CHUNKED_SCHEMA,
            "chunks": total,
            "executed": executed,
            "failed_chunk": failed_at,
            "atomicity": plan.atomicity,
            "atomicity_note_ru": plan.atomicity_note_ru,
            "budget_bytes": plan.budget_bytes,
            "est_bytes_total": plan.est_bytes_total,
            "per_chunk": rows,
        },
    }
    if element_map:
        # The map is CONTINUOUS across the whole program: "operation →
        # Revit elements" for every chunk that got built. This is exactly
        # the named enumeration of what stayed in the model after the
        # refusal.
        result["element_map"] = element_map
        lift_element_map(result)
    if all_ok:
        result["message_ru"] = (
            "построено %d операций %d чанками; программа шла %d транзакциями "
            "(atomicity=per_chunk)" % (
                sum(len(c.ops) for c in plan.chunks), total, total))
    else:
        result["rolled_back"] = False if executed else None
        # Repeating it whole would duplicate what was built — handing the
        # turn to the retry path would mean offering exactly that.
        result["handoff"] = None
        result["message_ru"] = (
            "чанк %d из %d отказал; построено %d чанков, и они В МОДЕЛИ: %s"
            % (int(failed_at) + 1 if failed_at is not None else 0, total,
               executed, (failed_diag or {}).get("message_ru", "")))
        result["diagnostics"] = [{
            **(failed_diag or {"code": KIR_CHUNK_PARTIAL}),
            "detail": note,
            "chunk": failed_at,
            "chunks_committed": executed,
        }]
    return _with_outcome(result, outcome)


async def _handle_revit_ir_inner(args: Any, llm_client, bridge_callback,
                                 query_id: str = "", *,
                                 bulk: bool = False,
                                 turn_id: str = "",
                                 action_id: str = "",
                                 query_fingerprint: str = "",
                                 source_kind: str = "unknown",
                                 authored_in_python: bool = False,
                                 author_digest: str = "",
                                 env_digest: str = "",
                                 lineage: dict | None = None,
                                 source_lines: dict | None = None,
                                 chunk_of: tuple[int, int] | None = None,
                                 timeout_ms: int | None = None,
                                 ) -> dict:
    """The tool handler. NEVER raises; every outcome is a typed dict.

    ``bulk`` is set by the CALLING DOOR, never by anything inside ``args``:
    the two doors above are the only two callers, and the chat one passes
    False literally.

    ``chunk_of`` is set by the CHUNK DRIVER (`_drive_chunked_program`), and
    likewise never by `args`: an input field sooner or later arrives from
    the tool's arguments, and this switch cancels chunk planning and the
    live publication of intent. Not `None` means exactly one thing —
    «I am slice (k, N) of someone else's program, the whole has been
    published and planned for me.»"""
    acceptance_session: AcceptanceSession | None = None
    write_execution_started = False
    last_write_outcome: ProgramOutcome | None = None
    try:
        if not revit_ir_enabled():
            # defense in depth: schema should be absent, but a stale prompt
            # cache may still name the tool — refuse politely, hand off.
            return _typed_error("gate", admin_gate_message_ru("revit_ir"))
        program = args.get("program") if isinstance(args, dict) else None
        if program is None and isinstance(args, dict) and "ops" in args:
            program = args                    # tolerate un-nested programs
        from kir.compiler import compile_program, plan_program
        # The import is lazy: the certificate drags in the emitter table,
        # and `kukai/llm/client.py` imports this module at process start.
        from kir.translation_cert import certificate_enabled

        # 🔴🔴 THE NUMBERS IN THIS BLOCK HAVE BEEN INVALID SINCE 18.08.2026.
        # READ THIS NOTE FIRST. Measured 25.08: the block carries FIVE dead
        # values — the authored budget «20», `MAX_VALIDATED_OPS` «320»,
        # "refuses at the 300th," "caps out at 20," and "macros give 320
        # after expansion." What is actually in effect: authored 100000,
        # internal batch 200000, the post-macro ceiling 400000, the macro
        # expansion budget 20000 — all declared at the constants
        # themselves, with the argument right there too.
        #
        # One consequence is named separately, because it removes the
        # paragraph's whole POINT: the argument "the authored budget is
        # small on purpose, so it cannot be used to measure the
        # materializer's chunk" rested on the DIFFERENCE between budgets.
        # The difference the paragraph was written for no longer exists:
        # the author's pre-macro budget of 100000 against the internal
        # batch of 200000 is not "20 against a hundred."
        #
        # The numbers are NOT erased: the canon's rule states that what is
        # superseded gets named wrong, not removed — it is a sample of the
        # form. The neighboring `compiler.py` block is built the same way,
        # and it also records why the note stands ABOVE the block: a
        # cancellation the reader never reached is not a cancellation.
        #
        # THE UNIT OF AUTHORSHIP DECIDES WHICH BUDGET MEASURES IT.
        #
        # The authored budget (20) measures ENUMERATION written by the
        # model, and it is small on purpose: 210 of 586 live refusals on
        # 30.07 were exactly this one, and it is a working signal that
        # "the wrong form was chosen." When the model sent a SCRIPT, the
        # authored thing is twelve lines of Python, while the front end
        # wrote a hundred and four operations; measuring them against the
        # authored budget is the same mistake as measuring them against
        # the materializer's chunk, and that seam already cost 318 rounds
        # instead of 26 (30.07, Snowdon Towers).
        #
        # WHAT THIS DOES NOT WEAKEN, stated directly:
        #   * `MAX_VALIDATED_OPS` (320, post-macro) is touched by nothing —
        #     that is the emitter's limit, not a policy;
        #   * `dsl._append` itself refuses at the 300th operation, naming
        #     direct-turn chunking as the next piece of work — that is,
        #     the ceiling stands in the language too, not only here;
        #   * THE COMPILATION POLICY DOES NOT CHANGE: a script goes
        #     through `compile_program` (one transaction, strict
        #     postconditions, full rollback), NOT `compile_rebuild_chunk`
        #     with per-op isolation and `report`. Exactly the budget was
        #     raised, and nothing else;
        #   * enumeration still caps out at 20: this line's `program`
        #     field never sees it.
        # Allowing the model THREE HUNDRED operations from one loop is not
        # the same as letting it type them by hand; macros (`stack`/
        # `series`) already give 320 after expansion today, and the
        # regularity there is of the same nature.
        pre_macro_bulk = bulk or authored_in_python

        # Planning does not need a model snapshot.  Keep the accepted object so
        # family routing, open-model preflight, lowering and result validation
        # all share one semantic program. Invalid input is compiled below to
        # preserve the public typed-refusal/coverage-feed path.
        try:
            routed_plan = plan_program(program, bulk=pre_macro_bulk)
        except Exception:  # noqa: BLE001 — compile_program owns the refusal
            routed_plan = None

        # THE ONLY LIVE-PLAN WRITE POINT. One line, one tap.
        #
        # WHY HERE, NOT AT THE DOORS. There are three input forms (the
        # chat `handle_revit_ir`, the admin `handle_revit_ir_bulk`, and
        # the Python one via `_authored_input`), and all three converge
        # exactly in this body. Four taps would have drifted apart within
        # a month — that already happened with the rebuild policy, which
        # three callers independently forgot on 21.07. Uniqueness is
        # checked by an `ast` walk over the whole tree, not by agreement
        # (`tests/test_live_plan_stream.py::test_single_publish_call_site`).
        #
        # WHY EXACTLY AT THIS POINT. It comes AFTER planning (macros
        # expanded, defaults filled in, budget checked — the sheet gets
        # exactly what will go downstream) and BEFORE the first call to
        # the bridge. One line below, the ground snapshot begins, and it
        # requires a live Revit: wire the stream in there, and an offline
        # run would produce not a single frame. Meanwhile, writing has not
        # started yet — the journal holds the INTENT and is marked
        # `planned`.
        #
        # WRITES ONLY. The journal is the source code OF THE BUILDING, and
        # a query does not belong to the building: 176 reads against 5
        # writes in a single turn (measured 29.07) would scatter the
        # history into trash. We ask the mid-end for the family using the
        # same function as the rest of the path — there is no second
        # classifier here.
        #
        # The stream LEAVES FROM HERE AND DOES NOT RETURN: `publish` is
        # synchronous, with not a single point of waiting, and its
        # exceptions never surface outward.
        #
        # A SLICE DOES NOT PUBLISH ITSELF: for a chunked program, the
        # OUTER call publishes the intent — whole, before the first chunk.
        # Publish every slice instead, and the window would show the last
        # of forty-two instead of the program, and `_TURN_JOURNAL_SLOT`
        # would point at a piece instead of the whole — that is, the
        # building's judge would be judging one forty-second of the
        # intent.
        try:
            if (chunk_of is None
                    and routed_plan is not None
                    and _program_writes(routed_plan, bulk=pre_macro_bulk)):
                from kir.live import plan_stream as _plan_stream
                # THE DOCUMENT IS IN THE KEY, NOT JUST ONE DEVICE: the
                # owner routinely has two Revits open (the NAKAZ, clause
                # 19), and a record without the document would fold two
                # buildings' programs into one journal line.
                _published_seq = _plan_stream.publish(
                    device_id=_turn_device_id(),
                    # THE SAME COMPOSITION AS `_turn_journal_key`: using
                    # the document name as the key would mean a new
                    # `Проект1` writes into the journal of ANOTHER,
                    # same-named building (08.09.2026).
                    doc_key=_turn_journal_doc_key(),
                    program=routed_plan,
                    author_digest=author_digest,
                    source="bulk" if bulk else "chat")
                # THE NUMBER IS REMEMBERED HERE AND ONLY HERE: the outcome
                # will not be known until a dozen and a half `return`
                # statements later, and without the slot the record would
                # stay `planned` forever — that is, the building's judge
                # would keep judging the declared, not the built.
                #
                # 🔴 THE KEY IS TAKEN FROM THE SINGLE AUTHOR. Computing it
                # here again would mean splitting apart THE WRITE and THE
                # LATER RECORDING OF THE OUTCOME: `publish` would land
                # under the document, the slot would point at an empty
                # key, and the stage would stay `planned` FOREVER —
                # silently, exactly as `journal.key_for`'s docstring
                # warns.
                if _published_seq is not None:
                    _TURN_JOURNAL_SLOT.set((
                        _turn_journal_key(), _published_seq))
        except Exception:  # noqa: BLE001 — the screen must not break the build
            logger.debug("live plan publish failed (fail-open)", exc_info=True)

        revit_version = _resolved_revit_version(llm_client).version

        snapshot = None
        open_model = None
        document_fingerprint = None
        model_preflight = None
        ground_context = None
        if _program_writes(
                routed_plan if routed_plan is not None else program,
                bulk=pre_macro_bulk):
            try:
                # SNAPSHOT REUSE (the gate is OFF by default). A program
                # that creates a catalog item neither takes the snapshot
                # from the cache nor puts one into it: it is the one
                # changing it.
                _writes_catalog = _program_writes_catalog(program)
                cand = None
                if _ground_reuse_enabled():
                    if _writes_catalog:
                        _ground_cache_drop()
                    else:
                        cand = await _reused_ground_snapshot(
                            llm_client, bridge_callback)
                if cand is None:
                    snap_res = await _run_declarative(
                        llm_client, bridge_callback, _snapshot_cs(program),
                        "ground_snapshot", _SNAPSHOT_TIMEOUT_MS)
                    if _extract_error(snap_res) is not None:
                        # A grounding refusal drops the cache ENTIRELY: a
                        # stale snapshot must be cured by retrying, not by
                        # reasoning about it.
                        _ground_cache_drop()
                        return _typed_error(
                            "ground", "мост вернул ошибку при получении снапшота модели")
                    cand = snap_res.get("result", snap_res) if isinstance(snap_res, dict) else None
                    if (_ground_reuse_enabled() and not _writes_catalog
                            and isinstance(cand, dict) and "levels" in cand):
                        try:
                            _key = _ground_cache_key(
                                _snapshot_document_fingerprint(cand))
                            if len(_GROUND_SNAPSHOT_CACHE) >= _GROUND_SNAPSHOT_CACHE_MAX:
                                _GROUND_SNAPSHOT_CACHE.clear()
                            _GROUND_SNAPSHOT_CACHE[_key] = cand
                        except (TypeError, ValueError):
                            pass
                if isinstance(cand, dict) and "levels" in cand:
                    # Document identity and exact element identity are
                    # deliberately separate gates.  The first is mandatory:
                    # otherwise grounding may read document A and the write
                    # may execute in document B.  The second can refuse a
                    # legitimate pinned id when a large pool is truncated and
                    # remains opt-in until certified on live models.
                    try:
                        document_fingerprint = (
                            _snapshot_document_fingerprint(cand))
                        # THE DOOR TO THE STANDING BUILDING. The
                        # document's identity is knowable exactly here;
                        # the clash check uses it to find THIS document's
                        # parse and compare the batch against what is
                        # already standing. Without this line the
                        # capability exists but has no door to it — that
                        # is exactly how `sdk.py` sat unused for five
                        # weeks. `title` is the same `Document.Title` that
                        # the parse writes into
                        # `passport.json::doc_name` (`extract.py:1014`).
                        from kir import clash_bundle as _clash_bundle

                        _clash_bundle.remember_turn_document(
                            document_fingerprint.title)
                    except (TypeError, ValueError):
                        logger.debug(
                            "KIR ground snapshot has no bound document identity",
                            exc_info=True)
                        return _typed_error(
                            "ground",
                            "снапшот открытой модели не содержит обязательную "
                            "идентичность документа")
                    if not _open_model_preflight_enabled():
                        snapshot = cand
                    else:
                        try:
                            open_model = OpenModelProfile.from_ground_snapshot(
                                cand)
                            model_preflight = _preflight_open_model(
                                routed_plan, open_model)
                        except OpenModelProfileError as _profile_exc:
                            # 🔴 THE REASON WAS GOING INTO `logger.debug`,
                            # WHILE THE SERVICE RUNS AT `--log-level info`
                            # — THAT IS, NOWHERE. Measured live on 24.08:
                            # `KUKAI_IR_OPEN_MODEL_PREFLIGHT=1` turned back
                            # EVERY writing program on a real document, and
                            # the entire text that reached the model was
                            # «нарушает типизированный контракт» — no
                            # field, no value, no next move. The author of
                            # such a refusal can fix NOTHING: our own law,
                            # "X != Y must print X," was broken in the
                            # very refusal that shuts the whole product
                            # down.
                            logger.warning(
                                "KIR open-model profile validation failed: %s",
                                _profile_exc, exc_info=True)
                            return _typed_error(
                                "ground",
                                "снапшот открытой модели нарушает "
                                "типизированный контракт: %s" % _profile_exc)
                        if not model_preflight.ready:
                            return _with_outcome({
                                "ok": False,
                                "refused": True,
                                "error": "open_model_preflight",
                                "message_ru": (
                                    "открытая модель не содержит точную "
                                    "привязку для программы — транзакция не "
                                    "запускалась"),
                                "preflight": model_preflight.to_dict(),
                                "handoff": "recipe-path",
                            }, program_not_started())
                        snapshot = open_model.to_ground_snapshot()
                else:
                    return _typed_error(
                        "ground", "не удалось получить снапшот модели для ground-стадии")
                # The snapshot becomes available to self-check HERE, where
                # both branches that obtain it have already converged, and
                # read-only.
                _TURN_GROUND_SNAPSHOT.set(snapshot)
                from kir.midend import GroundingContext
                ground_context = GroundingContext.from_snapshot(
                    snapshot,
                    source="trusted_bridge",
                    trusted_source=True,
                    profile_digest=(
                        open_model.digest if open_model is not None else None),
                    profile_authoritative=(
                        open_model.authoritative
                        if open_model is not None else False),
                    revision_proof=(
                        open_model.revision_proof
                        if open_model is not None else None),
                )
                # TYPE GEOMETRY — INTO THE SESSION JOURNAL. Wall thickness
                # and column cross-section live in the TYPE and are
                # knowable exactly here, on the live document; the readers
                # (the building verdict, the clash check) need them later
                # and on the BATCH. Only the pruned part travels
                # (`prune_ground_snapshot`), and the trip is synchronous,
                # with no waiting, swallowing any error: a screen must not
                # cost the build.
                try:
                    from kir.live import plan_stream as _plan_stream
                    # THE SAME KEY AS `publish`'s: sections filed under an
                    # empty document would end up in SOMEONE ELSE'S
                    # building's verdict.
                    _plan_stream.remember_sections(
                        device_id=_turn_device_id(),
                        doc_key=_turn_journal_doc_key(),
                        sections=prune_ground_snapshot(snapshot))
                except Exception:  # noqa: BLE001
                    logger.debug("live plan sections failed (fail-open)",
                                 exc_info=True)
            except Exception:  # noqa: BLE001
                logger.debug("KIR snapshot fetch failed", exc_info=True)
                return _typed_error(
                    "ground", "снапшот модели недоступен (мост не ответил)")

        # ═════ BUILD IN KIR, NOT IN REVIT ═════════════════════════════════════
        #
        # THE CUT MOVED HERE ON 14.08, AND IT MOVED BY MEASUREMENT, NOT BY
        # TASTE. It used to sit one line after publishing the intent —
        # before grounding. The logic was sound ("don't start writing"),
        # but the consequence was not: the document's type snapshot is
        # taken EXACTLY during grounding, and without it the viewer builds
        # bodies for almost no one. Live, it looked like this: the owner
        # pressed the button, saw an empty window, and "build in KIR"
        # turned out incompatible with "see what was built." The two
        # halves of the intent were canceling each other out.
        #
        # Grounding is READING the document. It changes nothing in the
        # model, but it gives the scene its types and the program its
        # real ids. So the hold sits AFTER it and BEFORE compilation with
        # execution: we read, we show, we do not write.
        # ONLY WHAT ACTUALLY HAPPENED CAN BE HELD.
        #
        # The first edition held ANY turn and answered "program accepted
        # and shown." Measured 14.08 on a live session: a program with
        # the field `outline_mm` instead of `outline` was REJECTED by the
        # planner, the plan came out `None`, nothing landed in the
        # journal — and the receipt said `ok: true` anyway. A
        # silently-wrong result, in code written specifically against
        # silently-wrong results.
        #
        # `plan_program` swallows the refusal on purpose: «compile_program
        # owns the refusal» — a rejected program must still go through
        # compilation so the human sees a TYPED refusal with a field and
        # a fix. The hold was cutting off that road. Now, without a plan,
        # it simply does not trigger: there will be no execution anyway —
        # compilation refuses first.
        if _kir_hold_active() and routed_plan is not None and _plan_writes(routed_plan):
            _held_ops = getattr(routed_plan, "ops", None)
            if _held_ops is None and isinstance(routed_plan, dict):
                _held_ops = routed_plan.get("ops")
            # THE BRIDGE DOCUMENT'S IDENTITY IS HANDED TO THE RECEIPT.
            # Grounding sits ABOVE the hold, so it is already known here
            # (or `None` — for a non-writing program the bridge was never
            # asked at all).
            held = _held_receipt(routed_plan, ops=len(_held_ops or []),
                                 document_fingerprint=document_fingerprint)
            return _with_outcome(held, program_not_started())

        expected_document = (
            document_fingerprint.compiler_guard()
            if document_fingerprint is not None
            else None
        )
        expected_identities = None
        if (model_preflight is not None
                and all(
                    binding.unique_id is not None
                    and binding.version_guid is not None
                    for binding in model_preflight.bindings)):
            expected_identities = model_preflight.exact_identity_proofs()
        open_profile = (
            open_model
            if open_model is not None and open_model.identity_bound
            else None
        )
        compile_input = routed_plan if routed_plan is not None else program

        # 🔴 DIRECT-TURN CHUNKING — WIRED IN HERE (21.08.2026).
        #
        # WHAT STOOD HERE BEFORE. A temporary guard,
        # `program_too_large_for_one_send`: it bounced the program BEFORE
        # compilation if the plan said `split`, and honestly stated that
        # chunking had been built but not wired in. The guard was the
        # truth about US, not about the program: an author who wrote five
        # thousand walls got a refusal on an intent the compiler was
        # perfectly able to execute.
        #
        # WHY SPLIT AT ALL — measured 20.08.2026 (do not re-measure):
        #
        #     ops     compile   C# MB   peak RSS MB
        #      1000      1.0 s     3.4          69
        #      5000      5.0 s    16.9         222
        #     20000     20.8 s    68.0         830
        #    100000    101   s   343         3723
        #
        # A websocket frame is 16 MB, and there is no length guard on the
        # bridge at all. That is, behind the 1000-op ceiling stood not
        # the budget (it has been raised to 100 000) but an UNNAMED
        # transport wall. In chunks, that same 100 000 runs in 94 s at a
        # peak RSS of 250 MB — fixing not only the frame but the
        # service's memory, fifteenfold.
        #
        # WHY THE CUT SITS EXACTLY HERE, NOT HIGHER UP. Strictly after
        # three things:
        #   * THE HOLD (`_kir_hold_active`) — a held program does not
        #     write at all, and chunking it would mean building what was
        #     held back;
        #   * GROUNDING and `model_preflight` — the whole is checked for
        #     binding to the open document ONCE, before the first chunk,
        #     not forty-two times;
        #   * `plan_program` — macros are expanded, and what we split is
        #     what will actually go downstream, not what was written.
        # The cost of the placement is named: an outer-call snapshot
        # after the cut is unnecessary — one extra read trip per split
        # program. It is cheaper than forty-two intent publications and
        # losing the pre-setup on the whole.
        #
        # ONE POINT FOR ALL INPUT FORMS, AND THERE WILL BE NO SECOND TAP.
        # Every caller converges on this body WITH OPERATIONS; the body
        # does not know, and has no right to know, what produced them
        # (`test_the_gate_is_the_only_place_that_knows_about_python` — a
        # structural guard, not an agreement). So chunking gets EVERY
        # input for free, and none of them can "forget" it — by
        # construction, not by a list of places.
        #
        # 🔴 ONLY AN ADMITTED PROGRAM GETS CHUNKED, AND THIS IS NOT
        # CAUTION, IT IS A FIX FOR OUR OWN DEFECT (caught 21.08.2026 by
        # our own suite, `test_op_budget_seam`, BEFORE a live run).
        #
        # `routed_plan is None` means `plan_program` REFUSED: the budget
        # was exhausted, the form was broken, a macro failed to expand.
        # In that case `compile_input` is the author's RAW program, and
        # the first edition of this hook honestly pulled `ops` out of it,
        # split it, and EXECUTED it. That is, a program of 200 001
        # operations, which should have gotten a typed budget refusal
        # (KIR-L001), traveled to Revit instead as eighty-four chunks.
        # Chunking fixes TRANSPORT; it is granted no right whatsoever to
        # bypass budget and validation.
        #
        # A refusal is still handed down by `compile_program` below —
        # byte for byte the same as before chunking was wired in.
        _plan = None
        if chunk_of is None and routed_plan is not None:
            try:
                from kir import chunking as _chunking
            except ImportError:                # the module is younger than the door
                _chunking = None
            if _chunking is not None:
                # 🔴 THE INPUT HERE COMES IN TWO KINDS, and the guard's
                # first edition overlooked that: `compile_input` is either
                # a raw program as a dict, or a `PlannedProgram` (when the
                # plan was built by the router), and inside a plan the
                # operations themselves are `PlannedOp`, not mappings.
                # `to_ops()` is the standard translator that turns a plan
                # back into dicts. Caught by a live run on 5 000 walls,
                # not by reading: the offline input had always been a
                # dict.
                if hasattr(compile_input, "to_ops"):
                    _ops_for_size = list(compile_input.to_ops() or [])
                elif hasattr(compile_input, "get"):
                    _ops_for_size = list(compile_input.get("ops") or [])
                else:
                    _ops_for_size = []
                if len(_ops_for_size) > 1:
                    try:
                        _plan = _chunking.plan_chunks(_ops_for_size)
                    except _chunking.ChunkTooBig as _too_big:
                        # ONE operation is larger than the chunk budget:
                        # there is nothing to split, and the fix is
                        # different — simplify the operation itself.
                        # Previously this exception fell into the body's
                        # shared `except Exception` and became
                        # «внутренней ошибкой KIR» — that is, the named
                        # refusal (KIR-K001) lost its own name along the
                        # way.
                        return _typed_error(
                            "chunk_op_too_big", str(_too_big))
        if _plan is not None and _plan.split:
            return await _drive_chunked_program(
                _plan,
                args=args,
                llm_client=llm_client,
                bridge_callback=bridge_callback,
                query_id=query_id,
                bulk=bulk,
                turn_id=turn_id,
                action_id=action_id,
                query_fingerprint=query_fingerprint,
                source_kind=source_kind,
                lineage=lineage,
                source_lines=source_lines,
                authored_in_python=authored_in_python,
                author_digest=author_digest,
                env_digest=env_digest,
            )

        def _compile_for_serving(identity_proofs):
            if bulk:
                # THE ONE compilation policy for a rebuild chunk — not a
                # set of flags improvised on the spot. The same helper
                # that the DRY gate (`handle_revit_rebuild`) and the live
                # A5-runner compile with: bulk + per_op + de-join (the
                # justification is in compile_rebuild_chunk).
                from kir.compiler import compile_rebuild_chunk
                return compile_rebuild_chunk(
                    compile_input,
                    revit_version=revit_version,
                    query_id=query_id,
                    turn_id=turn_id,
                    action_id=action_id,
                    query_fingerprint=query_fingerprint,
                    source_kind=source_kind,
                    snapshot=snapshot,
                    ground_context=ground_context,
                    expected_document=expected_document,
                    expected_identities=identity_proofs,
                    open_model_profile=open_profile,
                )
            return compile_program(
                compile_input,
                revit_version=revit_version,
                query_id=query_id,
                snapshot=snapshot,
                ground_context=ground_context,
                turn_id=turn_id,
                action_id=action_id,
                query_fingerprint=query_fingerprint,
                source_kind=source_kind,
                # Only the pre-macro budget. Isolation stays "atomic,"
                # postconditions stay strict: a script does not buy the
                # right to a partially committed program.
                bulk=pre_macro_bulk,
                expected_document=expected_document,
                expected_identities=identity_proofs,
                open_model_profile=open_profile,
            )

        out = _compile_for_serving(expected_identities)
        if not out.ok:
            # 🔴 THE ADDRESS IS IN THE AUTHOR'S SOURCE. A compiler refusal
            # arrives AFTER Python has already succeeded: the program is
            # assembled, and the forty-first operation out of sixty
            # fails. Before 27.08.2026 the model got an `op_id` and had
            # no way to know which line of ITS OWN code had produced that
            # op.
            _named = _name_the_author_line(
                out.diagnostics, lineage or {}, source=source_lines or {})
            res: dict = {"ok": False, "refused": True,
                         "diagnostics": _named[:8],
                         **_diagnostics_total(out.diagnostics, 8)}
            if out.handoff:
                res["handoff"] = out.handoff["route"]
                # 🔴 THE REASON COMES BEFORE THE ROUTE, AND THIS IS NOT
                # WORD ORDER.
                #
                # A single shared text used to sit here for every refusal
                # carrying `handoff`, and it WAS OVERWRITING specific
                # diagnostics. Found 25.08 by a live run:
                # `query_count(kind="column")` is refused by the compiler
                # with maximal precision — «вид уточняется:
                # column_architectural | column_structural; общего вида
                # column нет намеренно: выбрать за автора нельзя» — while
                # the model was getting «запрос вне покрытия KIR, выполни
                # обычным инструментом». That is, the precise answer
                # existed, was computed, and was thrown away at the last
                # step.
                #
                # Why a diagnostics list does not save it: `message_ru`
                # is a TOP-LEVEL SCALAR, while the history collapser
                # replaces every list with «свёрнуто» (canon form 27). A
                # reason living only in `diagnostics[]` never reaches the
                # model's next turn at all.
                #
                # And the route still exists: «вне покрытия» remains a
                # possible outcome, it is just now the SECOND half, not
                # the only one.
                причина = ""
                if out.diagnostics:
                    причина = str(getattr(out.diagnostics[0], "message_ru", "")
                                  or "").strip()
                res["message_ru"] = (
                    (причина + " " if причина else "")
                    + "Если операция вне покрытия KIR — выполни обычным "
                      "инструментом (query_model/execute_revit_code).")
            else:
                res["message_ru"] = ("программа отклонена компилятором — исправь "
                                     "по диагностике и повтори, либо используй "
                                     "обычные инструменты")
            return _with_outcome(res, program_not_started())

        # Snapshot presence was historically used as a proxy. The typed plan
        # is now the authority: transport and result contracts must classify
        # the same program the compiler actually lowered.
        family = out.planned.family.value
        timeout = _effective_timeout_ms(family, timeout_ms)

        # THE TRANSLATION CERTIFICATE — THE ONLY INSERTION POINT, AND IT
        # IS HERE.
        #
        # Compilation is behind us (witnesses have been emitted), the
        # first effect does not exist yet: no transaction, no prepared
        # journal event, no second call to the bridge. A program whose
        # witness is provably unable to fire has no right to reach the
        # write — its green would mean nothing. The justification for
        # the placement, the cost, and the modes is in the block above
        # `_certify_translation`; WHAT a failure does (refuse, or record
        # in the receipt) is decided by the flag's mode, not by this
        # line.
        #
        # WRITES ONLY: a query has neither a witness nor obligations, and
        # `REFINEMENT` knows nothing about it, by construction.
        #
        # WHY BEFORE THE REPEAT LOWERING (`guarded_out`), NOT AFTER.
        # Recompiling under exact identity adds ONE programmatic guard
        # (`_element_identity_guard`, authoring.py:4943) and touches no
        # witness at all: the certificate reissues verdicts from
        # `_EMITTERS[op](op, ver, stamp)`, and identity proofs are never
        # passed in there. So the certificate for the first lowering is
        # also valid for the second — and certifying earlier means
        # paying neither an acceptance read nor a prepared journal event
        # for a program that is not going anywhere regardless.
        #
        # A SECOND ARGUMENT USED TO STAND HERE, AND IT WAS A REFERENCE TO
        # A DEAD CONDITION: "the equality of `plan_digest` between the
        # two lowerings is checked further down this body as a condition
        # for continuing." That check below did exist, but could never
        # fire — identity proofs never enter the fingerprint at all (see
        # the comment where it stands) — and it was removed on 07.08.
        # The argument above never needed it: it rests on the fact that
        # `_EMITTERS` is never passed identity proofs, and that is still
        # true.
        #
        # Flag off ⇒ we never enter here at all: no call, no receipt
        # field, not one extra millisecond.
        certificate_receipt = None
        if family == "write" and certificate_enabled():
            certificate_receipt = _certify_translation(out, revit_version)
            if certificate_receipt["refused"]:
                _record_pre_effect(
                    "translation_certificate",
                    certificate_receipt.get("diagnostics"),
                    getattr(out, "grounded_ops", ()) or (),
                    query_id=query_id,
                    turn_id=turn_id,
                    action_id=action_id,
                    query_fingerprint=query_fingerprint,
                    source_kind=source_kind,
                    revit_version=revit_version,
                )
                return _certificate_refusal(certificate_receipt)

        # Independent acceptance belongs to every write that enters this
        # serving body.  In particular, the admin bulk door is reachable
        # directly from /admin/kir/run; it is not automatically enclosed by
        # A5's stronger revision-bound state machine.  Treating ``bulk`` as an
        # acceptance exemption therefore created a real unmeasured write
        # path.  A5 uses its own runner and never enters this body.
        if family == "write":
            async def _acceptance_reader(
                code: str,
                phase: str,
                timeout_ms: int,
            ) -> Any:
                return await _run_declarative(
                    llm_client, bridge_callback, code, phase, timeout_ms)

            try:
                assert snapshot is not None
                assert document_fingerprint is not None
                assert out.grounded is not None
                acceptance_session = await prepare_acceptance(
                    out.grounded,
                    snapshot,
                    document_fingerprint,
                    _acceptance_reader,
                    revit_version=revit_version,
                    timeout_ms=_SNAPSHOT_TIMEOUT_MS,
                )
            except AcceptanceRuntimeError as exc:
                _record_pre_effect(
                    "acceptance_prepare",
                    [exc.diagnostic()],
                    getattr(out, "grounded_ops", ()) or (),
                    query_id=query_id,
                    turn_id=turn_id,
                    action_id=action_id,
                    query_fingerprint=query_fingerprint,
                    source_kind=source_kind,
                    revit_version=revit_version,
                )
                return _with_outcome({
                    "ok": False,
                    "kir": True,
                    "refused": True,
                    "stage": "acceptance_prepare",
                    "diagnostics": [exc.diagnostic()],
                    "message_ru": exc.message_ru,
                    # Falling through to an unmeasured write would defeat the
                    # very precondition that refused this one.
                    "handoff": None,
                }, program_not_started())

            # The independent baseline is also a transaction-entry identity
            # proof.  Re-lower the SAME immutable plan with UniqueId +
            # VersionGuid guards, so another actor cannot edit/reuse a target
            # during the fsync interval and have our post-read claim its work.
            acceptance_proofs = acceptance_session.execution_identity_proofs
            if acceptance_proofs:
                combined = {}
                contradictory = None
                for proof in tuple(expected_identities or ()) + tuple(
                        acceptance_proofs):
                    previous = combined.get(proof.element_id)
                    if previous is not None and previous != proof:
                        contradictory = proof.element_id
                        break
                    combined[proof.element_id] = proof
                guarded_out = (
                    _compile_for_serving(tuple(
                        combined[key] for key in sorted(combined)))
                    if contradictory is None else None
                )
                # WHAT IS CHECKED HERE — TWO THINGS, AND BOTH ARE NAMED.
                # `guarded_out is None` — two DIFFERENT proofs for one
                # `element_id` (`contradictory`): the caller and the
                # session disagree about which element they consider the
                # target, and there is no gluing them together. `not
                # guarded_out.ok` — the re-lowering with the
                # UniqueId+VersionGuid guards failed to compile.
                #
                # THE THIRD CHECK IS GONE, AND THIS IS A FIX, NOT AN
                # OVERSIGHT. It used to read
                # `guarded_out.planned.plan_digest !=
                # out.planned.plan_digest`, and it COULD NEVER FIRE, NOT
                # ONCE. `plan_digest` is the sha256 of
                # `Planned._unsigned_evidence` (midend), which binds
                # schema, ir_version, family, intent, allow_destructive,
                # bulk, source_op_count, program_id, and ops — and NOT A
                # SINGLE identity proof. Both compilations run from the
                # same `compile_input`, and `expected_identities` only
                # reaches as far as `authoring.emit_program`, meaning it
                # changes `csharp` and nothing else: `planned` is
                # assembled before the proofs are even read. So the two
                # sides of the comparison are ALWAYS equal whenever the
                # first compilation succeeded. The condition read like a
                # safeguard without being one — and a line like that is
                # worse than none: it occupies the place where a real one
                # would go.
                #
                # The real difference between the two builds lives in
                # `csharp`, and a fingerprint OVER THE EMISSION could
                # judge it. There is none today; introducing one here, on
                # the refusal path, would mean installing a new lock in a
                # place that has never once been checked live. The gap is
                # named in words, not papered over with the appearance of
                # one.
                if (guarded_out is None
                        or not guarded_out.ok
                        or guarded_out.grounded is None
                        or guarded_out.grounded.ground_digest
                        != acceptance_session.registration.ground_digest):
                    outcome = program_not_started()
                    registration = acceptance_session.registration_wire()
                    detail = {
                        "stage": "acceptance_identity_bind",
                        "contradictory_element_id": contradictory,
                    }
                    if guarded_out is not None and not guarded_out.ok:
                        detail["compiler_diagnostics"] = [
                            item.as_dict() for item in guarded_out.diagnostics[:8]
                        ]
                        detail.update(
                            _diagnostics_total(guarded_out.diagnostics, 8))
                    elif (guarded_out is not None
                          and (guarded_out.grounded is None
                               or guarded_out.grounded.ground_digest
                               != acceptance_session.registration.ground_digest)):
                        detail["ground_digest_mismatch"] = True
                    try:
                        acceptance_session.abort_before_artifact(
                            outcome, detail=detail)
                        registration = acceptance_session.registration_wire()
                        registration["journal_finalized"] = True
                        registration["journal_checksum"] = (
                            acceptance_session.journal.state.checksum)
                    except AcceptanceJournalError as journal_exc:
                        registration["journal_finalized"] = False
                        registration["journal_error"] = str(journal_exc)
                    identity_diagnostic = {
                        "code": "KIR-A009",
                        "message_ru": (
                            "точную идентичность целей не удалось "
                            "встроить в транзакцию — запись не запускалась"),
                    }
                    _record_pre_effect(
                        "acceptance_identity_bind",
                        [identity_diagnostic],
                        getattr(out, "grounded_ops", ()) or (),
                        query_id=query_id,
                        turn_id=turn_id,
                        action_id=action_id,
                        query_fingerprint=query_fingerprint,
                        source_kind=source_kind,
                        revit_version=revit_version,
                    )
                    return _with_outcome({
                        "ok": False,
                        "kir": True,
                        "refused": True,
                        "stage": "acceptance_identity_bind",
                        "diagnostics": [{**identity_diagnostic,
                                         "detail": detail}],
                        "message_ru": (
                            "точную идентичность целей не удалось встроить "
                            "в транзакцию — запись не запускалась"),
                        "handoff": None,
                        "acceptance_registration": registration,
                    }, outcome)
                out = guarded_out

        # 🔴 MEASUREMENT INSTEAD OF ESTIMATION — THE LAST POINT WHERE THE
        # NUMBER IS STILL REAL AND NOTHING HAS STARTED YET (29.08.2026,
        # F-332).
        #
        # The plan prices the cost APPROXIMATELY (`chunking.cost_of` — an
        # estimate by operation kind) and, by construction, can miss on a
        # kind whose size is set by its content. Here `out.csharp` has
        # already been printed — and printed FINALLY, together with the
        # re-lowering under identity proofs — so its length is not an
        # estimate, it is a FACT.
        #
        # Measured 29.08: 38 legitimate `create_directshape` calls with a
        # mesh at the size ceiling produce 12 710 386 bytes of C#, that
        # is 16 947 184 after AES+base64 — 169 968 MORE than the
        # 16 777 216 frame, against a plan estimate of 418 190 and ONE
        # chunk. There is no length guard on outgoing `execute` in either
        # `bridge_protocol` or `chat_ws` (checked by grep 29.08), so
        # without this check the author got not a refusal but a DROPPED
        # CONNECTION.
        #
        # THERE IS NO FLAG HERE ON PURPOSE: today's behavior on this
        # input is a dropped connection, and "leave it as it was, behind
        # a flag" would mean leaving exactly that turned on. No one would
        # choose a dropped connection deliberately.
        #
        # THE PLACEMENT IS NOT ARBITRARY: further down the body, an
        # execution-artifact binding is set up
        # (`_REGULAR_WRITE_ARTIFACT_BINDING`) and
        # `write_execution_started` is raised. A refusal FROM THERE would
        # leave an unclosed binding and an unfinished acceptance; here
        # the write has not started yet, and the refusal is honestly
        # `program_not_started`.
        try:
            from kir import chunking as _chunk_guard
        except ImportError:                    # the module is younger than the door
            _chunk_guard = None
        if _chunk_guard is not None and getattr(out, "csharp", None):
            _emitted = len(out.csharp.encode("utf-8"))
            _over_wire = 4 * ((_emitted + 2) // 3)   # the base64 lower bound
            if _over_wire > _chunk_guard.FRAME_BYTES:
                _est = _plan.est_bytes_total if _plan is not None else 0
                _oversize_ru = (
                    f"{_chunk_guard.CHUNK_OP_TOO_BIG}: напечатано {_emitted} "
                    f"байт C#, это {_over_wire} байт в кадре моста при "
                    f"пределе {_chunk_guard.FRAME_BYTES}. Оценка плана "
                    f"была {_est} — сравни её с напечатанным, чтобы увидеть, "
                    f"на сколько план промахнулся. Упрости операции (реже "
                    f"сетка меша, меньше контрольных точек) либо раздели "
                    f"программу вручную")
                _oversize_outcome = program_not_started()
                _oversize_diag = {"code": _chunk_guard.CHUNK_OP_TOO_BIG,
                                  "message_ru": _oversize_ru,
                                  "emitted_bytes": _emitted,
                                  "over_wire_bytes": _over_wire,
                                  "frame_bytes": _chunk_guard.FRAME_BYTES,
                                  "estimated_bytes": _est}
                _record_pre_effect(
                    "emitted_program_too_large",
                    [_oversize_diag],
                    getattr(out, "grounded_ops", ()) or (),
                    query_id=query_id,
                    turn_id=turn_id,
                    action_id=action_id,
                    query_fingerprint=query_fingerprint,
                    source_kind=source_kind,
                    revit_version=revit_version,
                )
                if acceptance_session is not None:
                    _oversize_reg = acceptance_session.registration_wire()
                    try:
                        acceptance_session.abort_before_artifact(
                            _oversize_outcome,
                            detail={"stage": "emitted_program_too_large",
                                    "emitted_bytes": _emitted,
                                    "over_wire_bytes": _over_wire,
                                    "frame_bytes": _chunk_guard.FRAME_BYTES,
                                    "estimated_bytes": _est})
                        _oversize_reg = (
                            acceptance_session.registration_wire())
                        _oversize_reg["journal_finalized"] = True
                        _oversize_reg["journal_checksum"] = (
                            acceptance_session.journal.state.checksum)
                    except AcceptanceJournalError as _journal_exc:
                        _oversize_reg["journal_finalized"] = False
                        _oversize_reg["journal_error"] = str(_journal_exc)
                    return _with_outcome({
                        "ok": False,
                        "kir": True,
                        "refused": True,
                        "error": "chunk_op_too_big",
                        "stage": "emitted_program_too_large",
                        "diagnostics": [_oversize_diag],
                        "message_ru": _oversize_ru,
                        "handoff": None,
                        "acceptance_registration": _oversize_reg,
                    }, _oversize_outcome)
                return _typed_error("chunk_op_too_big", _oversize_ru,
                                    outcome=_oversize_outcome)

        async def _complete_independent_acceptance(
            base_outcome: ProgramOutcome,
        ) -> tuple[ProgramOutcome, Any | None, str | None]:
            """Post-read, derive the axis, then fsync before success escapes."""

            if acceptance_session is None:
                return base_outcome, None, None
            evidence = await acceptance_session.assess_after(
                _acceptance_reader, timeout_ms=_SNAPSHOT_TIMEOUT_MS)
            acceptance_state = acceptance_session.outcome_state(
                evidence, base_outcome.witness)
            assessed = independently_assessed(
                base_outcome, acceptance_state)
            try:
                acceptance_session.finalize(assessed, evidence=evidence)
                return assessed, evidence, None
            except AcceptanceJournalError as exc:
                # A valid in-memory measurement is not immutable evidence.
                # Never let an otherwise-green verdict escape as success when
                # its terminal record was not fsynced.
                if assessed.acceptance is AcceptanceState.ACCEPTED:
                    assessed = ProgramOutcome(
                        assessed.execution,
                        assessed.witness,
                        AcceptanceState.INCONCLUSIVE,
                    )
                return assessed, evidence, str(exc)

        import time as _time
        _t0 = _time.perf_counter()
        artifact_token = None
        if family == "write":
            assert acceptance_session is not None
            wrap_user_code = ports.need(ports.EXECUTION).wrap_user_code
            try:
                # ``out`` is already the identity-guarded re-lowering.  Bind
                # the pipeline's FINAL wrapper, fsync it, then recompute the
                # complete typed binding immediately before the only dispatch.
                wrapped_source = wrap_user_code(out.csharp)
                execution_binding = (
                    acceptance_session.bind_execution_artifact(
                        wrapped_source,
                        execution_lane=REGULAR_WRITE_EXECUTION_LANE,
                        tool="revit_ir",
                        op="write",
                    )
                )
                execution_binding = (
                    acceptance_session.require_execution_artifact(
                        wrap_user_code(out.csharp),
                        execution_lane=REGULAR_WRITE_EXECUTION_LANE,
                        tool="revit_ir",
                        op="write",
                    )
                )
                _bind_turn_operation_id(execution_binding, wrapped_source)
            except AcceptanceRuntimeError as exc:
                outcome = program_not_started()
                registration = acceptance_session.registration_wire()
                try:
                    detail = {
                        "stage": "execution_artifact_bind",
                        "diagnostic_code": exc.code,
                    }
                    if acceptance_session.execution_artifact_binding is None:
                        acceptance_session.abort_before_artifact(
                            outcome, detail=detail)
                    else:
                        acceptance_session.finalize(
                            outcome, evidence=None, detail=detail)
                    registration = acceptance_session.registration_wire()
                    registration["journal_finalized"] = True
                    registration["journal_checksum"] = (
                        acceptance_session.journal.state.checksum)
                except AcceptanceJournalError as journal_exc:
                    registration["journal_finalized"] = False
                    registration["journal_error"] = str(journal_exc)
                _record_pre_effect(
                    "execution_artifact_bind",
                    [exc.diagnostic()],
                    getattr(out, "grounded_ops", ()) or (),
                    query_id=query_id,
                    turn_id=turn_id,
                    action_id=action_id,
                    query_fingerprint=query_fingerprint,
                    source_kind=source_kind,
                    revit_version=revit_version,
                )
                return _with_outcome({
                    "ok": False,
                    "kir": True,
                    "refused": True,
                    "stage": "execution_artifact_bind",
                    "diagnostics": [exc.diagnostic()],
                    "message_ru": exc.message_ru,
                    "handoff": None,
                    "acceptance_registration": registration,
                }, outcome)
            artifact_token = _REGULAR_WRITE_ARTIFACT_BINDING.set(
                execution_binding)
            write_execution_started = True
        try:
            exec_res = await _run_declarative(
                llm_client, bridge_callback, out.csharp, family, timeout)
        finally:
            if artifact_token is not None:
                _REGULAR_WRITE_ARTIFACT_BINDING.reset(artifact_token)
        _dur_ms = (_time.perf_counter() - _t0) * 1000.0
        # THE TRACE OF WHAT WAS CREATED — HERE AND NOWHERE LATER.  Further
        # down the body the outcome can still turn into a failure
        # (`KIR-A006`/`KIR-A007`: acceptance diverged or never finished
        # on a write that DID HAPPEN), and the ids used to disappear
        # along with it: on 13.08 two elements stayed in the live model,
        # and neither the witness, nor the acceptance journal, nor the
        # refusals keep their ids. We write before acceptance, we read
        # the PAYLOAD, not the program, and we do not look at `ok`.
        # Details and boundaries are in `created_ledger`'s docstring.
        try:
            from kir import created_ledger as _cl
            # Binding to the session — without it the row cannot be
            # attributed, and the registry is shared across the fleet:
            # that is exactly why it had no reader.
            _cl.record_created(
                exec_res,
                query_id=query_id, turn_id=turn_id, action_id=action_id,
                revit_version=revit_version, family=family,
                device_id=_turn_device_id() or "",
                # 🔴 THE DOCUMENT, NOT JUST ONE DEVICE (29.08.2026,
                # F-299). The owner ROUTINELY has two Revits open (the
                # NAKAZ, clause 19), and the registry is shared across
                # the fleet. Without this key, rows from TWO buildings
                # landed in one answer to the reader, and `created_index`
                # handed back op id `W1` from whichever building's turn
                # happened later: the `op_id -> element_id` map was
                # addressing SOMEONE ELSE'S element.
                #
                # The same defect and the same fix as `_turn_journal_key`
                # on 27.08 (`serving.py`, `_turn_journal_document`'s
                # docstring): there the key was computed in three places
                # and left at the default "" in one of them. The tree has
                # already adopted this form; here it is applied, not
                # invented.
                doc_key=_turn_journal_document(),
                # 🔴 KIND, NOT CONTENT (29.08.2026, F-297). Without the
                # map, the scanner took the UNION of identity fields
                # across all creating ops, and `set_param`/`change_type`
                # — operations on an ALREADY EXISTING element — got
                # recorded as belonging to the turn. The `id` field is
                # legitimate both on 59 creating ops AND on
                # `change_type`.
                op_kinds=_op_kinds_of(out.planned),
                plan_digest=getattr(out.planned, "plan_digest", "") or "")
        except Exception:  # noqa: BLE001 — the write to Revit already happened
            logger.exception("created_ledger: след созданного не записан")
        from kir import witness_feed as _wf   # wave A6: fail-open corpus
        err = _extract_error(exec_res)
        if err is not None:
            artifact_refused_pre_effect = bool(
                isinstance(exec_res, Mapping)
                and exec_res.get("execution_artifact_refused_pre_effect") is True
            )
            if artifact_refused_pre_effect:
                diag = {
                    "code": "KIR-A010",
                    "message_ru": (
                        "точный исполняемый артефакт не совпал с "
                        "зарегистрированным — запись не запускалась"),
                    "detail": str(exec_res.get("message", ""))[:300],
                }
            else:
                diag = _translate_runtime(err)
            # Even a structural refusal code names a REASON, but it is
            # not evidence of the transaction's status. A rollback is
            # proven only when that same typed response carries an exact
            # `commit_status=RolledBack`. A timeout, a query error, a
            # generic bridge/API error, or a bare KIR-X code all leave
            # the outcome unknown: `true` would turn that unknown into a
            # false guarantee that a retry is safe.
            rolled_back = (True if not artifact_refused_pre_effect
                           and family == "write"
                           and diag["code"] in _ROLLBACK_PROVEN_CODES
                           and _explicit_commit_status(exec_res) == "RolledBack"
                           else None)
            if artifact_refused_pre_effect:
                outcome = program_not_started()
                write_execution_started = False
            elif rolled_back:
                outcome = write_rolled_back(
                    witness=(WitnessState.VIOLATED
                             if diag["code"] == "KIR-X004"
                             else WitnessState.INCOMPLETE))
            else:
                outcome = execution_unconfirmed()
            if family == "write":
                last_write_outcome = outcome
            acceptance_registration = None
            if acceptance_session is not None:
                acceptance_registration = acceptance_session.registration_wire()
                try:
                    acceptance_session.finalize(
                        outcome,
                        evidence=None,
                        detail={
                            "stage": "execute",
                            "diagnostic_code": diag["code"],
                        },
                    )
                    acceptance_registration["journal_finalized"] = True
                    acceptance_registration["journal_checksum"] = (
                        acceptance_session.journal.state.checksum)
                except AcceptanceJournalError as journal_exc:
                    acceptance_registration["journal_finalized"] = False
                    acceptance_registration["journal_error"] = str(journal_exc)
            _wf.record_witness(
                program=out.planned, family=family,
                # THE TURN'S IDENTITY — the same set that goes into the
                # refusal feed from this same function. Without a shared
                # key, the two corpora cannot be reconciled.
                query_id=query_id, turn_id=turn_id, action_id=action_id,
                # THE TASK CARRIER for the mission's main metric: the
                # task IS THE DOCUMENT. It is taken from the single
                # author of the document name — the same one that keys
                # the live journal (see `witness_feed.record_witness`).
                doc_key=_turn_journal_document(),
                # REVIT TRANSACTION isolation, under which the C# was
                # emitted. The distinction from the SANDBOX's
                # identically-named field is in
                # `CompileOutput.txn_isolation`'s docstring, NOT here:
                # this function's body is structurally forbidden to
                # mention the scripting layer, and both of this
                # comment's first two editions broke that very guard —
                # first with one forbidden word, then with a second,
                # named in the guard's own name. Without this field the
                # corpus mixes two populations: under the `per_op` bucket
                # there is no such thing as "incidental," by
                # construction.
                txn_isolation=getattr(out, "txn_isolation", None),
                revit_version=revit_version,
                ok=False, witness=_derive_witness(False, family, diag),
                duration_ms=_dur_ms, diag_code=diag["code"],
                diag_op_id=diag.get("op_id"),
                # The refusal's full identity: the code names the CLASS,
                # while the field and the text ARE the refusal itself.
                # The diagnostics already carried all of this, and the
                # corpus was throwing it away.
                diag_field=diag.get("field_name"),
                diag_message=diag.get("message_ru"),
                diag_detail=diag.get("detail"),
                violations=diag.get("violations"),
                outcome=outcome.to_dict(),
                author_digest=author_digest,
                env_digest=env_digest,
                acceptance_evidence=acceptance_registration,
                ground_context=(
                    out.grounded.context
                    if out.grounded is not None else None))
            # A screen report for a REFUSAL too. The first version only
            # reported success — and a live turn on 29.07 caught this
            # immediately: the program failed (`state: failed`), and the
            # human saw nothing at all — exactly the silence this whole
            # thing was built against. The moment of failure is exactly
            # when "it didn't work, trying something else" matters most:
            # without it, a pause for repair is indistinguishable from a
            # hang.
            try:
                _tp = ports.need(ports.TURN_PROGRESS)
                await _tp.report_failure(diag.get("message_ru") or diag.get("code") or "")
            except Exception:  # noqa: BLE001 — the screen must not break the turn
                logger.debug("turn progress failure report failed", exc_info=True)
            result = {"ok": False, "kir": True, "stage": "execute",
                 "diagnostics": [diag],
                 "witness": _derive_witness(False, family, diag),
                 "message_ru": diag["message_ru"],
                 "rolled_back": rolled_back,
                 "handoff": (None if artifact_refused_pre_effect
                             or diag["code"] == "KIR-X007"
                             else "recipe-path")}
            if acceptance_registration is not None:
                result["acceptance_registration"] = acceptance_registration
            return _with_outcome(result, outcome)
        contract_diag = _result_contract_diagnostic(
            exec_res, family, out.planned)
        if contract_diag is not None:
            payload = (exec_res.get("result", exec_res)
                       if isinstance(exec_res, dict) else None)
            commit_confirmed = (
                family == "write"
                and isinstance(payload, dict)
                and payload.get("ok") is True
            )
            if commit_confirmed:
                outcome = write_committed(witness=WitnessState.INCOMPLETE)
            elif family == "query" and isinstance(payload, dict):
                outcome = ProgramOutcome(
                    ExecutionState.READ_COMPLETED,
                    WitnessState.INCOMPLETE,
                    AcceptanceState.NOT_APPLICABLE,
                )
            else:
                outcome = execution_unconfirmed()
            if family == "write":
                last_write_outcome = outcome
            acceptance_evidence = None
            acceptance_journal_error = None
            acceptance_wire = None
            if acceptance_session is not None:
                if commit_confirmed:
                    (outcome,
                     acceptance_evidence,
                     acceptance_journal_error) = (
                        await _complete_independent_acceptance(outcome))
                    last_write_outcome = outcome
                    acceptance_wire = acceptance_session.evidence_wire(
                        acceptance_evidence)
                else:
                    acceptance_wire = acceptance_session.registration_wire()
                    try:
                        acceptance_session.finalize(
                            outcome,
                            evidence=None,
                            detail={
                                "stage": "result_contract",
                                "diagnostic_code": contract_diag["code"],
                            },
                        )
                        acceptance_wire["journal_finalized"] = True
                        acceptance_wire["journal_checksum"] = (
                            acceptance_session.journal.state.checksum)
                    except AcceptanceJournalError as journal_exc:
                        acceptance_journal_error = str(journal_exc)
                        acceptance_wire["journal_finalized"] = False
                        acceptance_wire["journal_error"] = (
                            acceptance_journal_error)
            _wf.record_witness(
                program=out.planned, family=family,
                # THE TURN'S IDENTITY — the same set that goes into the
                # refusal feed from this same function. Without a shared
                # key, the two corpora cannot be reconciled.
                query_id=query_id, turn_id=turn_id, action_id=action_id,
                # THE TASK CARRIER for the mission's main metric: the
                # task IS THE DOCUMENT. It is taken from the single
                # author of the document name — the same one that keys
                # the live journal (see `witness_feed.record_witness`).
                doc_key=_turn_journal_document(),
                # REVIT TRANSACTION isolation, under which the C# was
                # emitted. The distinction from the SANDBOX's
                # identically-named field is in
                # `CompileOutput.txn_isolation`'s docstring, NOT here:
                # this function's body is structurally forbidden to
                # mention the scripting layer, and both of this
                # comment's first two editions broke that very guard —
                # first with one forbidden word, then with a second,
                # named in the guard's own name. Without this field the
                # corpus mixes two populations: under the `per_op` bucket
                # there is no such thing as "incidental," by
                # construction.
                txn_isolation=getattr(out, "txn_isolation", None),
                revit_version=revit_version,
                ok=False, witness=_derive_witness(False, family, contract_diag),
                duration_ms=_dur_ms, certificate=certificate_receipt,
                diag_code=contract_diag["code"],
                diag_op_id=contract_diag.get("op_id"),
                diag_field=contract_diag.get("field_name"),
                diag_message=contract_diag.get("message_ru"),
                diag_detail=contract_diag.get("detail"),
                outcome=outcome.to_dict(),
                author_digest=author_digest,
                env_digest=env_digest,
                result_payload=(payload if commit_confirmed else None),
                acceptance_evidence=acceptance_wire,
                ground_context=(
                    out.grounded.context
                    if out.grounded is not None else None))
            diagnostics = [contract_diag]
            if acceptance_journal_error is not None:
                diagnostics.append(_acceptance_diagnostic(
                    acceptance_evidence,
                    durability_error=acceptance_journal_error))
            result = {"ok": False, "kir": True, "stage": "execute",
                 "diagnostics": diagnostics,
                 "witness": _derive_witness(False, family, contract_diag),
                 "message_ru": contract_diag["message_ru"],
                 "rolled_back": False if commit_confirmed else None,
                 # Retrying a committed/unknown write risks duplication.
                 "handoff": None}
            if acceptance_wire is not None:
                result["acceptance"] = acceptance_wire
            return _with_outcome(result, outcome)
        _payload = exec_res.get("result", exec_res) if isinstance(exec_res, dict) else None
        # ``report`` mode commits, folding violations into the result.
        # We read them: a silent "success" over a violated postcondition
        # is a lie (§3.6).
        _violations = _postcondition_violations(_payload)
        # OP NAMES — THE ONLY INPUT THAT SHOWS WHAT WAS PROMISED TO BE
        # CHECKED. They are read defensively: failing here would mean
        # bringing down a write THAT ALREADY HAPPENED, and the honesty
        # of the witness is not worth that price — on any surprise,
        # `_unwitnessed_axes` returns `None`.
        _planned = getattr(out, "planned", None)
        _op_names = tuple(
            op.op_name for op in (getattr(_planned, "ops", ()) or ()))
        _witness = _witness_for_success(family, _payload, _op_names)
        _outcome = (
            query_accepted()
            if family == "query"
            else write_committed(
                witness=(WitnessState.VIOLATED
                         if _violations else WitnessState.SATISFIED))
        )
        if family == "write":
            # Knowledge of a confirmed commit is monotonic.  A later
            # acceptance/journal/telemetry bug may weaken proof of the final
            # state, but it must never rewrite a known effect to unconfirmed.
            last_write_outcome = _outcome
        _acceptance_evidence = None
        _acceptance_journal_error = None
        _acceptance_wire = None
        if acceptance_session is not None:
            (_outcome,
             _acceptance_evidence,
             _acceptance_journal_error) = (
                await _complete_independent_acceptance(_outcome))
            last_write_outcome = _outcome
            _acceptance_wire = acceptance_session.evidence_wire(
                _acceptance_evidence)

        # ``ok`` may no longer outrun the closed state.  Queries retain their
        # read contract; every write through this body is green only after a
        # confirmed commit, satisfied witness, independent acceptance, and a
        # durable terminal evidence record.  Keep the condition fail-closed:
        # a future write route that forgets to prepare a session cannot become
        # successful merely because ``acceptance_session`` stayed ``None``.
        _accepted = green_is_earned(
            violations=_violations,
            family=family,
            has_acceptance_session=acceptance_session is not None,
            acceptance=_outcome.acceptance,
            journal_error=_acceptance_journal_error,
        )
        # ═══ THE REFUSAL REASON TRAVELS TO BOTH READERS: THE MODEL AND
        # THE CORPUS ═══
        #
        # 🔴 Before 24.08, acceptance diagnostics were computed ~250
        # lines BELOW and never made it into the journal at all.
        # Measured on the live corpus (3712 lines): of 180 records with
        # `execution=committed` and `ok:false`, 164 have no refusal
        # code. That does NOT mean the model was never told the reason —
        # it means there was nothing to measure our own honesty with,
        # using our OWN corpus, and the very first analysis read that
        # absence as a fact about the product.
        #
        # The condition is exactly the same one the branch that hands
        # the model its diagnostics uses, and it now lives HERE ALONE:
        # further down, `_acceptance_diag` is read, not a copy of the
        # condition.
        _acceptance_diag = None
        if (acceptance_session is not None
                and (_outcome.acceptance is not AcceptanceState.ACCEPTED
                     or _acceptance_journal_error is not None)):
            _acceptance_diag = _acceptance_diagnostic(
                _acceptance_evidence,
                durability_error=_acceptance_journal_error,
            )
        _wf.record_witness(
            program=out.planned, family=family,
            # THE TURN'S IDENTITY — the same set that goes into the
            # refusal feed from this same function. Without a shared
            # key, the two corpora cannot be reconciled.
            query_id=query_id, turn_id=turn_id, action_id=action_id,
            # THE TASK CARRIER for the mission's main metric: the task
            # IS THE DOCUMENT. It is taken from the single author of the
            # document name — the same one that keys the live journal
            # (see `witness_feed.record_witness`).
            doc_key=_turn_journal_document(),
            diag_code=(_acceptance_diag or {}).get("code"),
            diag_message=(_acceptance_diag or {}).get("message_ru"),
            diag_detail=(_acceptance_diag or {}).get("detail"),
            # REVIT TRANSACTION isolation, under which the C# was
            # emitted. The distinction from the SANDBOX's
            # identically-named field is in
            # `CompileOutput.txn_isolation`'s docstring, NOT here: this
            # function's body is structurally forbidden to mention the
            # scripting layer, and both of this comment's first two
            # editions broke that very guard — first with one forbidden
            # word, then with a second, named in the guard's own name.
            # Without this field the corpus mixes two populations: under
            # the `per_op` bucket there is no such thing as "incidental,"
            # by construction.
            txn_isolation=getattr(out, "txn_isolation", None),
            revit_version=revit_version,
            ok=_accepted, witness=_witness,
            duration_ms=_dur_ms, violations=_violations or None,
            certificate=certificate_receipt,
            result_payload=_payload if isinstance(_payload, dict) else None,
            outcome=_outcome.to_dict(),
            author_digest=author_digest,
            env_digest=env_digest,
            acceptance_evidence=_acceptance_wire,
            ground_context=(
                out.grounded.context
                if out.grounded is not None else None))
        # The turn's end-of-turn review reads what was actually built, so only
        # a program that reached this point — compiled, executed, witnessed —
        # is recorded. A refused or rolled-back program never happened.
        if family == "write":
            try:
                _review = ports.need(ports.DESIGN_REVIEW)
                _review.record(program)
            except Exception:  # noqa: BLE001 — a review must never break a turn
                logger.debug("review record failed", exc_info=True)
        # A live report to the screen. The operator, 29.07: "several
        # minutes with a blank screen, people won't understand what's
        # happening." On every round the model calls the tool IN SILENCE
        # (measured: 8 calls, 0 characters of text), so the server
        # speaks instead — it alone knows whether the program actually
        # executed and how long that took.
        try:
            _tp = ports.need(ports.TURN_PROGRESS)
            if family == "write" and _accepted:
                await _tp.report_write(_created_count(_payload),
                                       int(_dur_ms), _program_note(program))
            elif family == "write":
                failure = (
                    _acceptance_diag["message_ru"]
                    if _acceptance_diag is not None else
                    "KIR не подтвердил независимую приёмку записи")
                await _tp.report_failure(failure)
            else:
                await _tp.report_read()
        except Exception:  # noqa: BLE001 — the screen must not break the turn
            logger.debug("turn progress report failed", exc_info=True)
        # 🔴 THROUGH THE FUNNEL, NOT AROUND IT (03.09.2026, found by a
        # LIVE TURN). A dict literal with `"outcome":
        # _outcome.to_dict()` used to sit here, and it was the ONLY
        # successful write path. `_with_outcome`'s docstring calls itself
        # "THE ONLY FUNNEL THROUGH WHICH EVERY TYPED OUTCOME OF THIS
        # MODULE PASSES" — and it was wrong exactly where the outcome
        # matters most. The cost is measured on live prod: a 23-element
        # apartment was built, `execution: committed`, while the
        # building's judge, in that SAME receipt, printed
        # «ПОСТРОЕНО В REVIT: НИ ОДНОЙ ПРОГРАММЫ. Судится ЗАМЫСЕЛ, а не
        # модель». `built` counts journal stages, no one ever told the
        # journal, and `committed` never happened, NOT ONCE, across 92
        # records of the session.
        out_result = _with_outcome({"ok": _accepted, "kir": True,
                                    "witness": _witness,
                                    "result": exec_res}, _outcome)
        # A FLAT FORM NEXT TO THE DICTIONARY — the same law as the map one
        # line below: a dictionary collapses when history folds, AT ANY
        # LEVEL, a string survives. Called HERE, where the witness is
        # laid down, so the test can call exactly what prod calls.
        lift_witness_note(out_result)
        # ═══ THE INTENT REACHES THE RECEIPT, NOT HALFWAY THERE ═══
        #
        # 🔴 25.08.2026, THE THIRD BREAK IN ONE CHAIN, and it was found
        # by a live turn. The units table (`course.unit()`) was fixed
        # twice in one hour: first the PLAN learned to carry it (without
        # it the live door lost it on the way into the compiler), then
        # `_units_of` learned to read it. A live run showed a third
        # break: `CompileOutput.units` is filled in, but the MODEL'S
        # RECEIPT never copies it. The field had ZERO readers anywhere
        # in the tree.
        #
        # Without this line, a model that wrote a composite "apartment"
        # gets back a list of ops and a number, `u0`, that means nothing
        # to it.
        #
        # ABSENCE STAYS ABSENCE: an empty `units` in the receipt would
        # read as "the intent was empty," when it was never declared at
        # all.
        _units = getattr(out, "units", None)
        if _units:
            out_result["units"] = list(_units)
        # THE BRIDGE BETWEEN TWO ADDRESS SPACES, HANDED TO THE MODEL
        # EXPLICITLY.
        #
        # `_result_contract_diagnostic` above already REFUSES TO RELEASE
        # a successful writing program in which even one operation lacks
        # a typed identity (KIR-X008). That is, the map "operation id →
        # Revit element" exists on every such receipt, GUARANTEED — and
        # before this line NOBODY who needed it was reading it: the
        # "declared versus built" comparator
        # (`design_check.compare_geometry`) stated in its own docstring
        # that no correspondence exists for an authored program,
        # `assembly_view` was forced to carry `address_space` around, and
        # the `materializer` could not link a synthetic id to an
        # element.
        #
        # The form is a LIST of any arity, the argument is in
        # `address.receipt_map`. Defensively: the map is a reading
        # convenience, and failing on it would mean bringing down a
        # write THAT ALREADY HAPPENED for the sake of convenience.
        # THE ABSENCE OF THE MAP IS NAMED, NOT SILENT: an empty map and
        # an unassembled map are different facts, and the second cannot
        # be read as "no elements."
        if isinstance(_payload, Mapping) and out.planned is not None:
            try:
                from kir import address as _address
                out_result["element_map"] = _address.receipt_map(
                    out.planned.to_ops(), _payload, strict=False)
                # A FLAT FORM NEXT TO THE DICTIONARY: a dictionary
                # collapses when history folds, at ANY level, a string
                # survives.
                lift_element_map(out_result)
            except Exception as _map_exc:  # noqa: BLE001 — the map does not break the write
                logger.debug("element_map failed", exc_info=True)
                out_result["element_map_error"] = (
                    "карта «операция → элемент» не собралась (%s): адреса "
                    "построенных элементов в этой квитанции НЕ НАЗВАНЫ — это "
                    "не значит, что элементов нет"
                    % type(_map_exc).__name__)
        # ═══ AN ARROW THAT DID NOT EXIST: WHAT WAS BUILT GETS REREAD
        # AND JUDGED ═══
        #
        # Before 17.08.2026 the product judged what the program DECLARED
        # and called that checking the result. The address map one line
        # above existed and was read by NOBODY; `design_check.compare`
        # and `compare_geometry` — a ready-made machine for reconciling
        # declared against built — were called only by tests.
        #
        # THE COST IS MEASURED BEFORE THE HOOK, not estimated: a narrow
        # read costs **1.04–1.17 s** on a live document of 310 558
        # elements, and **the slope over N is ZERO** (−0.34 ms/element
        # over 1…200): the `reextract` body walks the document and only
        # then filters, so what is paid for is the walk, not the count
        # of ids. That is +6.3 % of a turn against the 16.08 measurement
        # of 17–18 s, of which the model takes 84.6 %.
        #
        # HERE, NOT AT THE `client.py::_WRITE_TOOLS` SEAM (99 % of
        # writes against 0.9 %): the "declared against built"
        # discrepancy exists only where there IS a DECLARED, and
        # `execute_revit_code` carries no program. The radius equals
        # KIR's radius BY CONSTRUCTION, not by cost.
        #
        # IT REPORTS, IT DOES NOT HOLD (the owner's decision, 17.08): the
        # block travels alongside `ok`, cancels nothing, and does not
        # drop the turn. The instrument is young, and the rate of its
        # false alarms is unknown.
        if out.planned is not None and out_result.get("element_map"):
            try:
                from kir import built_verdict as _built

                async def _built_reader(code: str, phase: str,
                                        timeout_ms: int) -> Any:
                    return await _run_declarative(
                        llm_client, bridge_callback, code, phase, timeout_ms)

                _built_block = await _built.judge(
                    reader=_built_reader,
                    element_map=out_result.get("element_map"),
                    ops=out.planned.to_ops(),
                    snapshot=snapshot,
                    doc_name=getattr(document_fingerprint, "title", "") or "",
                    revit_version=revit_version,
                )
                if _built_block:
                    out_result["built"] = _built_block
                    # A FLAT STRING NEXT TO THE DICTIONARY — canon form
                    # 27: the history collapser replaces EVERY
                    # dictionary with «свёрнуто», and a verdict that
                    # exists only in structure never reaches the model
                    # through history.
                    out_result["built_note"] = _built.note(_built_block)
            except Exception:  # noqa: BLE001 — the write already happened; the judge is younger
                logger.debug("built verdict stamping failed", exc_info=True)
        if out.grounded is not None:
            context = out.grounded.context
            out_result["ground_context"] = {
                "schema": "kir-grounding-context/1",
                "context_digest": context.context_digest,
                "snapshot_digest": context.snapshot_digest,
                "document_digest": context.document_digest,
                "revision_digest": context.revision_digest,
                "profile_digest": context.profile_digest,
                "execution_bound": context.execution_bound,
                "authoritative": context.authoritative,
                "selector_resolution_replayed": (
                    out.grounded.selector_resolution_replayed),
                "derived_artifacts_verified": (
                    out.grounded.derived_artifacts_verified),
                # 🔴 A NUMBER NEXT TO THE FLAG (F-103).
                # `selector_resolution_replayed` is true EXACTLY when
                # there is nothing to resolve, and reads as the
                # opposite. Without this number, "there was nothing to
                # replay" and "there was something to replay, and we
                # didn't" look identical.
                "selector_resolutions": out.grounded.selector_resolutions,
            }
        # A NAMED DEFAULT: a choice the compiler makes on behalf of an
        # author who said nothing must be DISCLOSED. A choice the caller
        # cannot see is indistinguishable from `.FirstOrDefault()` — and
        # that is exactly what the C# side silently used on 02.08.2026
        # to take 1 door type out of 62 in a live document. The report
        # is machine-made, the note is human; the note is empty when
        # there was nothing to choose from.
        from kir import receipt_fold as _receipt_fold
        _fold_stats: list = []
        if out.grounding_report:
            from kir.ground import (attach_runtime_choices,
                                         describe_choices_ru)
            # HERE AND ONLY HERE DOES THE NAME OF THE TYPE THE DOCUMENT
            # CHOSE EXIST. `create_wall` without a `type` asks the
            # document itself for a type inside emission
            # (`GetDefaultElementTypeId`), so at the grounding stage the
            # receipt carries only the rule and a pointer. A live turn
            # on 10.08.2026 returned `chosen: {id: null, name: null}`
            # for a wall that was actually built as «111_Кирпич 380» —
            # the rule was named, the result was unknown, and that is
            # exactly "a choice the caller cannot see." We connect it
            # with a readback of the built element: by this point the
            # result contract has already required `ok:true`, meaning
            # the transaction is committed and the name read back
            # describes an element that exists.
            _report = attach_runtime_choices(out.grounding_report, _payload)
            # 🔴 FOLDING A REPEAT, NOT TRIMMING DETAIL. Measured 21.08
            # on a live program of 100 walls: `grounding_report` — 100
            # records, essentially ONE, repeated; `resolved_refs` — the
            # same; together 44 KB out of 85. The fold states the fact
            # once, counts it, and lists EVERY `op_id` — nothing is
            # lost. What differs is never folded, ever
            # (`test_receipt_fold`).
            _report, _fold_gr = _receipt_fold.fold_rows(_report)
            out_result["grounding_report"] = _report
            _defaults_note = describe_choices_ru(_report)
            if _defaults_note:
                _defaults_note, _fold_dn = _receipt_fold.fold_sentences(
                    _defaults_note)
                out_result["defaults_note_ru"] = _defaults_note
                _fold_stats.append(("defaults_note_ru", _fold_dn))
            _fold_stats.append(("grounding_report", _fold_gr))
        # THE NUMBER A REFERENCE TURNED INTO. Kept separate from
        # `grounding_report` on purpose: that one answers "what the
        # compiler chose on behalf of a silent author" and does not show
        # ordinary `by=name` resolutions — the author named those
        # themselves. Here the question is different: "what did the
        # thing I named turn into." The measurement that bought this
        # line: 540 beams out of 540 landed at z=0 while "Floor 5"
        # (18000 mm) was what had been written, and not one receipt
        # named that discrepancy — the model learned about it from a
        # human a full day later.
        if snapshot is not None and out.grounded is not None:
            from kir.ground import (describe_resolved_refs_ru,
                                         resolved_references)
            try:
                _refs = resolved_references(out.grounded.to_ops(), snapshot)
            except Exception:  # noqa: BLE001
                # The showroom HAS NO RIGHT to bring down a building
                # that was built: by this line the transaction is
                # already committed. A missing report shows up as a
                # missing field, and that is more honest than failing
                # after the write.
                logger.debug("resolved_references failed (fail-open)",
                             exc_info=True)
                _refs = []
            if _refs:
                _refs, _fold_rr = _receipt_fold.fold_rows(_refs)
                out_result["resolved_refs"] = _refs
                _fold_stats.append(("resolved_refs", _fold_rr))
                _refs_note = describe_resolved_refs_ru(_refs)
                if _refs_note:
                    _refs_note, _fold_rn = _receipt_fold.fold_sentences(
                        _refs_note)
                    out_result["resolved_refs_note_ru"] = _refs_note
                    _fold_stats.append(("resolved_refs_note_ru", _fold_rn))
        # WHAT GETS DECIDED WITHOUT THE AUTHOR, BECAUSE THEY SAID
        # NOTHING. A third question next to the two above, and kept
        # separate by MEASUREMENT, not by taste: a run on 27.08 produced
        # `grounding_report == []` BOTH with `top_level` omitted AND
        # with it given. That report tells you what the compiler CHOSE;
        # an omission is what it never chose — authority passed to the
        # type or to Revit instead. And of the eight fields with
        # `omission_transfers`, only THREE are grounded: the other five
        # are `str`/`mm`, and there will NEVER be a line about them
        # there.
        #
        # The cost of the silence is measured live: 420 columns came
        # out at 2500 instead of 3600-4500, because `top_level` was
        # omitted and the height came from the TYPE's default. No
        # refusal, no line in the receipt; three audits walked right
        # past it.
        if out.grounded is not None:
            from kir.ground import (describe_omissions_ru,
                                         omitted_authorities)
            try:
                _omit = omitted_authorities(out.grounded.to_ops())
            except Exception:  # noqa: BLE001
                # The same law as its neighbor's: by this line the
                # transaction is already committed, and the showroom has
                # no right to bring down what was built.
                logger.debug("omitted_authorities failed (fail-open)",
                             exc_info=True)
                _omit = []
            if _omit:
                _omit, _fold_om = _receipt_fold.fold_rows(_omit)
                out_result["omitted_authorities"] = _omit
                _fold_stats.append(("omitted_authorities", _fold_om))
                _omit_note = describe_omissions_ru(_omit)
                if _omit_note:
                    _omit_note, _fold_on = _receipt_fold.fold_sentences(
                        _omit_note)
                    out_result["omissions_note_ru"] = _omit_note
                    _fold_stats.append(("omissions_note_ru", _fold_on))
        # The reader must learn about the folding FROM THE RECEIPT, not
        # from knowledge of the code: a silently shortened receipt reads
        # as a complete one.
        _fold_note = _receipt_fold.fold_note_ru(_fold_stats)
        if _fold_note:
            out_result["receipt_folded_ru"] = _fold_note
        diagnostics = []
        if _violations:
            out_result["postconditions_violated"] = True
            out_result["rolled_back"] = False
            out_result["handoff"] = None
            diagnostics.append({
                "code": W_POSTCONDITIONS_COMMITTED,
                "message_ru": ("постусловия нарушены, но программа "
                               "закоммичена (режим report) — проверь модель"),
                "violations": _violations[:10],
            })
            out_result["message_ru"] = (
                f"записано с нарушением постусловий: {len(_violations)}")
        if _acceptance_diag is not None:
            acceptance_diag = _acceptance_diag
            diagnostics.append(acceptance_diag)
            out_result["rolled_back"] = False
            out_result["handoff"] = None
            out_result["message_ru"] = acceptance_diag["message_ru"]
        if diagnostics:
            out_result["diagnostics"] = diagnostics
        if _acceptance_wire is not None:
            out_result["acceptance"] = _acceptance_wire
        # THE RECEIPT MUST CARRY WHAT EXACTLY HAPPENED. A certificate
        # refusal carries this itself (`_certificate_refusal`); here is
        # the rule's other half: `ok:true` names the instrument that
        # made this green meaningful, and its mode. A finding that was
        # recorded but let through (`mode: record`) is visible right
        # inside the success — otherwise an observation-only mode would
        # be silence, and silence is indistinguishable from cleanliness.
        if certificate_receipt is not None:
            out_result["certificate"] = certificate_receipt
        return out_result
    except Exception:  # noqa: BLE001 — absolute fail-open (never break the turn)
        logger.exception("revit_ir handler internal error")
        fallback_outcome = last_write_outcome or (
            execution_unconfirmed()
            if write_execution_started else program_not_started()
        )
        acceptance_registration = None
        if acceptance_session is not None:
            acceptance_registration = acceptance_session.registration_wire()
            if not acceptance_session.journal.state.finalized:
                try:
                    if acceptance_session.execution_artifact_binding is None:
                        acceptance_session.abort_before_artifact(
                            fallback_outcome,
                            detail={"stage": "internal_exception"},
                        )
                    else:
                        acceptance_session.finalize(
                            fallback_outcome,
                            evidence=None,
                            detail={"stage": "internal_exception"},
                        )
                    acceptance_registration = (
                        acceptance_session.registration_wire())
                    acceptance_registration["journal_finalized"] = True
                    acceptance_registration["journal_checksum"] = (
                        acceptance_session.journal.state.checksum)
                except AcceptanceJournalError as journal_exc:
                    acceptance_registration["journal_finalized"] = False
                    acceptance_registration["journal_error"] = str(journal_exc)
        result = _typed_error(
            "internal",
            "внутренняя ошибка KIR — используй обычные инструменты",
            # The exception may have happened after the bridge accepted a
            # write.  Unknown is safer than fabricating a non-started state.
            outcome=fallback_outcome)
        if acceptance_registration is not None:
            # A raw fallback would bypass the registered-acceptance boundary.
            result["handoff"] = None
            result["acceptance_registration"] = acceptance_registration
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Wave A1 — decompile/rebuild admin instruments (KUKAI_KIR_DECOMPILE=stage2)
#
# Same gate shape as revit_ir (flag AND admin device, re-checked in dispatch,
# absolute fail-open → typed dict).  ``revit_decompile`` drives the live
# pipeline as ONE asyncio task per process (a second concurrent start is a
# typed refusal); ``revit_rebuild`` is a thin wrapper over the A3 materializer
# (built by a parallel wave — imported behind try, typed refusal when absent).
# ─────────────────────────────────────────────────────────────────────────────

_DECOMPILE_FLAG = "KIR_DECOMPILE"
_ATOM_ESCROW_FLAG = "KIR_ATOM_ESCROW"
_DECOMPILE_OUT_ROOT = env.get(
    "KIR_DECOMPILE_DATA", "backend/data/decompile")


def revit_decompile_enabled() -> bool:
    """Stage-2 gate for the decompile/rebuild instruments: flag AND admin."""
    if env.get(_DECOMPILE_FLAG, "off") != "stage2":
        return False
    return is_admin_device(_turn_device_id())


def atom_escrow_enabled() -> bool:
    """Explicit default-off gate for geometry-only atom materialization."""

    return env.get(_ATOM_ESCROW_FLAG, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _load_atom_escrow_bundle(
    out_dir: str,
    leaves: Sequence[Mapping[str, Any]],
):
    """Load the exact typed Tier-G bundle and return it with its byte digest."""

    import hashlib as _hashlib
    import pathlib as _pathlib
    from kir.decompile.geom_extract import (
        GeometryArtifactProof,
        GeometryExtraction,
        GeometryPayloadError,
    )

    path = _pathlib.Path(out_dir) / "geometry.bundle.json"
    raw = path.read_bytes()
    with (_pathlib.Path(out_dir) / "geometry.proof.json").open(
            "r", encoding="utf-8") as source:
        artifact_proof = GeometryArtifactProof.from_dict(json.load(source))
    with (_pathlib.Path(out_dir) / "revision.proof.json").open(
            "r", encoding="utf-8") as source:
        revision_proof = RevisionProof.from_dict(json.load(source))
    artifact_proof.verify(
        change_stamp=revision_proof.change_stamp,
        revision_fingerprint=revision_proof.fingerprint,
        geometry_bundle=raw,
        leaves=leaves,
    )
    categories_by_id = {
        leaf["source_element_id"]: leaf["category"]
        for leaf in leaves
        if isinstance(leaf, Mapping)
        and leaf.get("kind") == "atom"
        and isinstance(leaf.get("source_element_id"), str)
        and isinstance(leaf.get("category"), str)
    }
    geometry = GeometryExtraction.from_json(
        raw.decode("utf-8"), categories_by_id=categories_by_id)
    expected_ids = {
        leaf["source_element_id"]
        for leaf in leaves
        if isinstance(leaf, Mapping)
        and leaf.get("kind") == "atom"
        and not (
            isinstance(leaf.get("reason"), Mapping)
            and leaf["reason"].get("code") == "generator_child")
    }
    accounted_ids = {
        record.element_id for record in geometry.index
    } | {
        failure.element_id for failure in geometry.failures
    }
    if accounted_ids != expected_ids:
        raise GeometryPayloadError(
            "geometry bundle does not account for the exact atom contract")
    return geometry, _hashlib.sha256(raw).hexdigest()


# One running task per process.  ``_active_run`` holds (task, out_dir, stamp).
_active_run: dict[str, Any] = {}


def _record_dead_decompile_run(task: Any, *, out_dir: str, doc_stamp: str) -> None:
    """The parse background died (or was cancelled) — the trace MUST land
    in ``status.json``.

    🔴 MEASURED 08.09.2026 on the owner's live Revit («Проект1», a KUKAI
    build with KIR 0.6.0): `start` answered «прогон запущен» twice,
    while the background kept dying before the first page — and
    `status` said «нет активного прогона» twice: no file, no log line,
    no directory. `ensure_future` with no exception observer is a
    falsely-green receipt in its purest form. Here is the observer: a
    dead background writes `stage: failed` with the exception's name (or
    `cancelled`) into the SAME `status.json` that `action=status` reads,
    and it does not touch a status the run managed to finish on its own.
    """
    try:
        if task.cancelled():
            exc, state = None, "cancelled"
        else:
            exc = task.exception()
            if exc is None:
                return
            state = "failed"
    except Exception:  # noqa: BLE001 — the observer must not bring down the loop
        return
    from pathlib import Path as _Path
    from kir.decompile import pipeline as _pipe
    try:
        current = _pipe.read_status(out_dir) or {}
    except Exception:  # noqa: BLE001
        current = {}
    if current.get("stage") in ("done", "failed", "cancelled"):
        return
    payload = {**current, "stage": state, "state": state,
               "error": (f"{type(exc).__name__}: {exc}" if exc is not None else "cancelled"),
               "background_died": exc is not None, "doc_stamp": doc_stamp,
               "updated_at": time.time()}
    try:
        _Path(out_dir).mkdir(parents=True, exist_ok=True)
        _pipe._atomic_write_json(_Path(out_dir) / _pipe._STATUS_NAME, payload)
    except Exception:  # noqa: BLE001
        logger.exception("decompile: статус умершего фона не записан (%s)", out_dir)
    if exc is not None:
        logger.error("decompile: фон умер без статуса — %s: %s (out_dir=%s)",
                     type(exc).__name__, exc, out_dir)


# ─────────────────────────────────────────────────────────────────────────────
# THE SNAPSHOT IS READ THROUGH `snapshot_io`, NOT A BARE `open` (21.08.2026)
# ─────────────────────────────────────────────────────────────────────────────
#
# 🔴 `tools/snapshot_janitor.py` compresses cooled-down parses IN PLACE,
# and as of this wave its list holds not six names but ten: alongside
# `L0.jsonl` and the side indexes, `passport.json` (1001 MB across 28
# parses), `tree.json` (416 MB), `verify.json` (342 MB), and
# `named.json` (422 MB) were added. A bare `open` on a compressed parse
# raises `FileNotFoundError`, and a bare `os.path.isfile` answers False
# — and THAT IS WORSE THAN A CRASH: the service prints «нет декомпайла
# для этого doc_stamp — сначала запусти decompile» about a parse that
# is sitting right there and simply cooled off. Exactly this way — "two
# shelves were covering for each other's defects" — the reader stayed
# intact for exactly as long as the janitor stayed dead.
#
# `touch=True` (the default) is CORRECT here and is not an oversight:
# this is a prod path, not a measuring instrument, and its reads must
# extend the parse's reprieve from the janitor — the `.last_access`
# mark is exactly what defines "nobody reads this."
def _snapshot_exists(path) -> bool:
    """Whether the parse artifact exists — RAW OR COMPRESSED."""
    from kir.decompile.snapshot_io import snapshot_file_exists
    return snapshot_file_exists(path)


def _open_snapshot(path, mode: str = "rt", *, encoding: str | None = None):
    """Open the parse artifact: raw, or if that's missing, the same path + `.gz`."""
    from kir.decompile.snapshot_io import open_snapshot
    return open_snapshot(path, mode, encoding=encoding)


def _decompile_out_dir(doc_stamp: str) -> str:
    safe_full = "".join(
        ch if (ch.isalnum() or ch in "-_.") else "_" for ch in doc_stamp)
    # Preserve historical paths for ordinary safe stamps. Whenever sanitizing
    # or truncating is lossy, append a digest of the FULL stamp so distinct
    # documents cannot share one artifact directory.
    if (safe_full == doc_stamp and 0 < len(safe_full) <= 120
            and safe_full not in (".", "..")):
        leaf = safe_full
    else:
        import hashlib as _hashlib
        digest = _hashlib.sha256(doc_stamp.encode("utf-8")).hexdigest()[:16]
        prefix = safe_full[:103] or "document"
        leaf = f"{prefix}-{digest}"
    return os.path.join(_DECOMPILE_OUT_ROOT, leaf)


def _make_executor(llm_client, bridge_callback):
    """Return an ``async (code, *, timeout_ms) -> raw`` executor.

    Wraps RevitExecutionPipeline.run_declarative (the same read-only transport
    revit_ir uses); no LLM repair, snapshot-grade timeout.  The extractor
    unwraps the serving envelope itself, so this returns the raw tool result.
    """
    async def _executor(code: str, *, timeout_ms: int = _SNAPSHOT_TIMEOUT_MS) -> Any:
        return await _run_declarative(
            llm_client, bridge_callback, code, "decompile_read", timeout_ms)
    return _executor


async def handle_revit_decompile(args: Any, llm_client, bridge_callback,
                                 query_id: str = "") -> dict:
    """Admin decompile driver. NEVER raises; every outcome is a typed dict.

    ``args``: {action: "start"|"status"|"cancel", doc_stamp?}.  ``start``
    launches the single per-process run; ``status`` reads ``status.json``;
    ``cancel`` sets the cancel flag (a clean stop between batches).
    """
    try:
        if not revit_decompile_enabled():
            return _typed_error("gate", admin_gate_message_ru(
                "revit_decompile",
                # The gate names the CALLER: these three stand behind
                # `revit_decompile_enabled` — a different flag, there is
                # no mode.
                flag=_DECOMPILE_FLAG, needs_mode=False))
        from kir.decompile import pipeline as _pipe

        action = args.get("action") if isinstance(args, dict) else None
        doc_stamp = args.get("doc_stamp") if isinstance(args, dict) else None

        if action == "status":
            if not isinstance(doc_stamp, str) or not doc_stamp:
                run = _active_run.get("run")
                out_dir = _active_run.get("out_dir")
            else:
                out_dir = _decompile_out_dir(doc_stamp)
            if not out_dir:
                return {"ok": True, "status": None,
                        "message_ru": "нет активного прогона"}
            status = _pipe.read_status(out_dir)
            if status is None and _active_run.get("out_dir") == out_dir:
                active = _active_run.get("task")
                if active is not None and not active.done():
                    # The background is alive, but there is no first
                    # page yet: that is "starting up," not "no active
                    # run" (08.09.2026 — the latter read as silence and
                    # sent the owner off to restart it).
                    status = {"stage": "starting", "state": "starting",
                              "background_alive": True}
            reply = {"ok": True, "status": status, "out_dir": out_dir}
            # §18.4: incompleteness of the read is not a detail buried
            # inside status.json, it is the first thing anyone asking
            # "how's the run going" must see.
            partial = _partial_read_state(out_dir)
            reply["is_partial_read"] = bool(partial["is_partial_read"])
            if partial["is_partial_read"]:
                reply["worksets_closed"] = partial["worksets_closed"]
                reply["message_ru"] = (
                    "ЧАСТИЧНОЕ ЧТЕНИЕ: закрытых рабочих наборов "
                    f"{partial['worksets_closed']} — прочитана часть модели; "
                    "открой все ворксеты и перечитай")
            return reply

        if action == "cancel":
            out_dir = (
                _decompile_out_dir(doc_stamp)
                if isinstance(doc_stamp, str) and doc_stamp
                else _active_run.get("out_dir"))
            if not out_dir:
                return {"ok": False, "error": "no_run",
                        "message_ru": "нет прогона для отмены"}
            found = _pipe.request_cancel(out_dir)
            return {"ok": bool(found), "cancel_requested": bool(found),
                    "out_dir": out_dir,
                    "message_ru": ("отмена запрошена" if found
                                   else "нет status.json для этого прогона")}

        if action == "start":
            if not isinstance(doc_stamp, str) or not doc_stamp:
                return _typed_error("args", "start требует непустой doc_stamp")
            existing = _active_run.get("task")
            if existing is not None and not existing.done():
                return {"ok": False, "refused": True, "error": "run_in_progress",
                        "message_ru": "прогон уже идёт — дождись завершения или отмени",
                        "out_dir": _active_run.get("out_dir")}
            out_dir = _decompile_out_dir(doc_stamp)
            executor = _make_executor(llm_client, bridge_callback)
            import asyncio as _asyncio
            # What can be snapshotted is the LINK, not the host
            # document: linked documents are already open in the
            # session, and a link's snapshot is separate, with its own
            # stamp. The name comes from the caller and travels into C#
            # as a literal.
            link_title = (args.get("link_title")
                          if isinstance(args, dict) else None)
            if link_title is not None and (
                    not isinstance(link_title, str) or not link_title.strip()):
                return _typed_error(
                    "args", "link_title должен быть непустой строкой")
            task = _asyncio.ensure_future(_pipe.run_decompile(
                executor, out_dir=out_dir, change_stamp=doc_stamp,
                link_title=link_title))
            task.add_done_callback(functools.partial(
                _record_dead_decompile_run, out_dir=out_dir, doc_stamp=doc_stamp))
            _active_run.clear()
            _active_run.update({"task": task, "out_dir": out_dir,
                                "stamp": doc_stamp})
            return {"ok": True, "started": True, "out_dir": out_dir,
                    "message_ru": "прогон запущен — опрашивай action=status"}

        return _typed_error("args", "action должен быть start|status|cancel")
    except Exception as exc:  # noqa: BLE001 — absolute fail-open
        logger.exception("revit_decompile handler internal error")
        return _typed_error(*_failure_stage(exc, "декомпайла"))


def source_catalogue_snapshot(out_dir: str) -> dict | None:
    """The source-model catalogue as a ground snapshot, or None.

    Grounding needs the snapshot to resolve selectors by name and by
    default. A live chat gets it from the bridge in one batch; the
    internal rebuild paths (the dry rebuild gate, the dry A5 gate, the
    live A5 runners) never call the bridge for this — and without the
    catalogue the compiler used to refuse whole chunks with KIR-G103.

    Measured 28.07 on ЭОМ: with the catalogue, ALL 543 operations
    compile; without it, 43. That is, the refusal was reporting not on
    the program but on the caller's blindness.

    The catalogue sits next to the parse (`open_model.profile.json`) —
    saved by the same run as L0/L1, and for A5 it is ALSO the
    authenticity-checked document snapshot
    (`_load_a5_snapshot_manifest`). Levels are taken from L0: the
    profile has none, and grounding levels requires them.

    The function lives at module level on purpose: this same defect was
    planted twice, from scratch, in two places, because the knowledge
    sat inside a single function.
    """
    try:
        import json as _json
        prof_path = os.path.join(out_dir, "open_model.profile.json")
        if not os.path.isfile(prof_path):
            return None
        with open(prof_path, "r", encoding="utf-8") as fh:
            prof = _json.load(fh)
        snapshot = {
            pool["name"]: [
                {"id": entry.get("element_id"), "name": entry.get("name")}
                for entry in (pool.get("entries") or [])
            ]
            for pool in (prof.get("pools") or [])
            if isinstance(pool, dict) and pool.get("name")
        }
        l0_path = os.path.join(out_dir, "L0.jsonl")
        if _snapshot_exists(l0_path):
            with _open_snapshot(l0_path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    row = _json.loads(line)
                    if "document" in row:
                        snapshot.setdefault("levels", [
                            {"id": int(lv["id"]), "name": lv["name"]}
                            for lv in (row["document"].get("levels") or [])
                        ])
                        break
        return snapshot
    except Exception:  # noqa: BLE001 — the gate must not fail because of the catalogue
        return None


#: A named value of `base_doc_stamp` meaning "the previous revision of
#: this same building, per the journal." A VALUE, deliberately, not a
#: default: a base picked silently is `.FirstOrDefault()` with good PR,
#: and picking the wrong delta base can cost more than picking the
#: wrong door type.
JOURNAL_BASE_TOKEN = "@journal"


def _resolve_base_from_journal(
    out_dir: str, doc_stamp: str,
) -> tuple[str | None, dict | None]:
    """`@journal` → the stamp of this building's previous revision, or a
    REFUSAL.

    Answers a question the system was missing: parses of one building
    sit in neighboring directories, but before the journal, nothing
    linked them to each other, and `base_doc_stamp` was pulled from the
    operator's memory. Here it is taken from a recorded fact — and the
    resolved name MUST travel into the answer, because a choice the
    asker cannot see cannot be checked.

    Every refusal is typed and never falls back to a full rebuild: they
    asked for a delta from the previous revision — a silent "I'll build
    the whole building" would be an answer to a different question.
    """

    import json as _json
    import os as _os

    from kir.decompile.journal import journal_enabled

    if not journal_enabled():
        return None, {
            "ok": False, "refused": True, "error": "journal_disabled",
            "message_ru": (
                "base_doc_stamp='@journal', но журнал здания выключен — "
                "включи KUKAI_IR_JOURNAL"),
        }
    passport_path = _os.path.join(out_dir, "passport.json")
    try:
        with _open_snapshot(passport_path, "rt", encoding="utf-8") as handle:
            doc_name = str(_json.load(handle).get("doc_name") or "")
    except (OSError, ValueError, AttributeError):
        doc_name = ""
    if not doc_name:
        return None, {
            "ok": False, "refused": True, "error": "journal_no_doc_name",
            "message_ru": (
                "в разборе нет passport.json с именем документа — journal не "
                "знает, к какому зданию относится этот прогон"),
        }
    from kir.decompile.journal import JournalError
    from kir.decompile.journal_store import load_log, log_path, \
        previous_stamp
    path = log_path(_os.path.dirname(out_dir), doc_name)
    try:
        log = load_log(path)
    except (JournalError, KeyError, TypeError, ValueError) as exc:
        # A broken journal is a refusal, not "no history": confusing
        # the two means slipping in a base chosen by a broken
        # instrument.
        return None, {
            "ok": False, "refused": True, "error": "journal_unreadable",
            "message_ru": "журнал здания не читается — база не разрешена",
            "detail": f"{type(exc).__name__}: {exc}"[:400],
            "doc_name": doc_name,
        }
    if log is None:
        return None, {
            "ok": False, "refused": True, "error": "journal_absent",
            "message_ru": (
                "у этого здания ещё нет журнала — предыдущей ревизии не "
                "существует; назови base_doc_stamp явно"),
            "doc_name": doc_name,
        }
    stamp, reason = previous_stamp(log, doc_stamp)
    if reason == "not_in_journal":
        return None, {
            "ok": False, "refused": True, "error": "journal_no_revision",
            "message_ru": (
                "этого разбора нет в журнале здания — он снят до включения "
                "журнала либо относится к другому документу"),
            "doc_name": doc_name,
        }
    if reason == "is_base_revision":
        return None, {
            "ok": False, "refused": True, "error": "journal_no_previous",
            "message_ru": (
                "это первая ревизия здания в журнале — предыдущей нет, "
                "пересобирать дельтой не от чего"),
            "doc_name": doc_name,
        }
    return stamp, None


_REBUILD_SUMMARY_SCHEMA = "rebuild-summary/2"
_MATERIALIZATION_ACCOUNTING_SCHEMA = "materialization-accounting/2"
_ACCOUNTING_FIELDS = frozenset({
    "schema_version", "input_digest", "programs_digest", "counts",
    "records", "receipt_digest",
})
_ACCOUNTING_COUNT_FIELDS = frozenset({
    "input_leaves", "emitted_semantic_ops", "atom_escrows",
    "datum_policy_pins", "typed_residuals", "programs", "emitted_ops",
})
_ACCOUNTING_RECORD_FIELDS = frozenset({
    "source_id", "leaf_id", "leaf_kind", "category", "disposition",
    "reason", "op_id", "program_index", "element_id", "evidence_state",
})


def _canonical_materialization_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _materialization_digest(value: Any) -> str:
    import hashlib
    return hashlib.sha256(
        _canonical_materialization_json(value).encode("utf-8")
    ).hexdigest()


def _materialization_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _normalize_materialization_skip(record: Any) -> dict[str, str]:
    if isinstance(record, Mapping):
        if set(record) != {"source_id", "category", "reason"}:
            raise ValueError("skip record has an unknown or missing field")
        source_id = record.get("source_id")
        category = record.get("category")
        reason = record.get("reason")
    else:
        source_id = getattr(record, "source_id", None)
        category = getattr(record, "category", None)
        reason = getattr(record, "reason", None)
    if not all(isinstance(value, str) and value
               for value in (source_id, category, reason)):
        raise ValueError("skip record must contain three non-empty strings")
    return {
        "source_id": source_id,
        "category": category,
        "reason": reason,
    }


def _accounting_stat(stats: Any, name: str) -> int:
    value = stats.get(name) if isinstance(stats, Mapping) \
        else getattr(stats, name, None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"materialization stats.{name} is missing or untyped")
    return value


def _verify_materialization_accounting(
    leaves: Sequence[Mapping[str, Any]],
    programs: Any,
    materialized: Any,
) -> dict[str, Any]:
    """Independently verify the v2 total-accounting receipt at the wire seam."""

    from kir.decompile.geom_extract import GeometryFailureReason
    from kir.decompile.l1_schema import AtomReason

    atom_reason_codes = frozenset(reason.value for reason in AtomReason)
    atom_residual_reasons = frozenset({
        *("atom:" + reason for reason in atom_reason_codes),
        "atom_escrow:not_selected",
        "atom_escrow:missing_geometry_evidence",
        "atom_escrow:tier_a_no_geometry",
        "atom_escrow:category_identity_mismatch",
        "atom_escrow:geometry_refused",
        "atom_escrow:mesh_refused",
        *("atom_escrow:geometry_failure:" + reason.value
          for reason in GeometryFailureReason),
        "atom_escrow:geometry_failure:unavailable",
    })

    accounting = getattr(materialized, "accounting", None)
    if hasattr(accounting, "as_dict"):
        accounting = accounting.as_dict()
    if not isinstance(accounting, Mapping):
        raise ValueError("typed materialization accounting is missing")
    payload = dict(accounting)
    if set(payload) != _ACCOUNTING_FIELDS:
        raise ValueError("materialization accounting has an unknown or missing field")
    if payload["schema_version"] != _MATERIALIZATION_ACCOUNTING_SCHEMA:
        raise ValueError("materialization accounting schema version is unsupported")
    if (not _materialization_sha256(payload["input_digest"])
            or not _materialization_sha256(payload["programs_digest"])
            or not _materialization_sha256(payload["receipt_digest"])):
        raise ValueError("materialization accounting digest is untyped")
    unsigned = {key: payload[key] for key in (
        "schema_version", "input_digest", "programs_digest", "counts",
        "records",
    )}
    if payload["receipt_digest"] != _materialization_digest(unsigned):
        raise ValueError("materialization accounting receipt digest mismatch")

    counts = payload["counts"]
    if not isinstance(counts, Mapping) or set(counts) != _ACCOUNTING_COUNT_FIELDS:
        raise ValueError("materialization accounting counts have wrong shape")
    counts = dict(counts)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in counts.values()):
        raise ValueError("materialization accounting counts must be integers")

    canonical_leaves: list[Mapping[str, Any]] = []
    leaves_by_source: dict[str, Mapping[str, Any]] = {}
    leaf_ids: set[str] = set()
    for index, leaf in enumerate(leaves):
        if not isinstance(leaf, Mapping):
            raise ValueError(f"input leaf {index} is not an object")
        source_id = leaf.get("source_element_id")
        leaf_id = leaf.get("_id")
        kind = leaf.get("kind")
        if (not isinstance(source_id, str) or not source_id
                or not isinstance(leaf_id, str) or not leaf_id
                or kind not in {"op", "atom"}):
            raise ValueError("input leaf identity or kind is untyped")
        if source_id in leaves_by_source:
            raise ValueError("input repeats source_element_id")
        if leaf_id in leaf_ids:
            raise ValueError("input repeats L1 _id")
        if kind == "op":
            if (not isinstance(leaf.get("op_name"), str)
                    or not leaf["op_name"]):
                raise ValueError("input op leaf has no typed op_name")
        else:
            reason = leaf.get("reason")
            reason_code = (
                reason.get("code") if isinstance(reason, Mapping) else None)
            if reason_code not in atom_reason_codes:
                raise ValueError("input atom reason is outside the closed set")
            if (not isinstance(leaf.get("category"), str)
                    or not leaf["category"]):
                raise ValueError("input atom category is untyped")
        leaves_by_source[source_id] = leaf
        leaf_ids.add(leaf_id)
        canonical_leaves.append(leaf)
    canonical_leaves.sort(key=lambda leaf: (
        leaf["source_element_id"], leaf["_id"]))
    if payload["input_digest"] != _materialization_digest(canonical_leaves):
        raise ValueError("materialization accounting is bound to other leaves")

    if (isinstance(programs, (str, bytes, bytearray))
            or not isinstance(programs, Sequence)):
        raise ValueError("materialized programs are not a sequence")
    programs = list(programs)
    if payload["programs_digest"] != _materialization_digest(programs):
        raise ValueError("materialization accounting is bound to other programs")
    wire_ops: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for program_index, program in enumerate(programs):
        if not isinstance(program, Mapping) \
                or not isinstance(program.get("ops"), list):
            raise ValueError("materialized program has an untyped ops wire")
        for op in program["ops"]:
            if not isinstance(op, Mapping):
                raise ValueError("materialized op is not an object")
            op_id = op.get("id")
            if not isinstance(op_id, str) or not op_id:
                raise ValueError("materialized op id is untyped")
            if op_id in wire_ops:
                raise ValueError("materialized wire repeats an op id")
            wire_ops[op_id] = (program_index, op)

    raw_records = payload["records"]
    if not isinstance(raw_records, list):
        raise ValueError("materialization accounting records must be a list")
    records: list[dict[str, Any]] = []
    records_by_source: dict[str, dict[str, Any]] = {}
    record_leaf_ids: set[str] = set()
    accounted_op_ids: set[str] = set()
    for raw_record in raw_records:
        if not isinstance(raw_record, Mapping) \
                or set(raw_record) != _ACCOUNTING_RECORD_FIELDS:
            raise ValueError("materialization accounting record has wrong shape")
        record = dict(raw_record)
        source_id = record["source_id"]
        leaf_id = record["leaf_id"]
        leaf_kind = record["leaf_kind"]
        category = record["category"]
        disposition = record["disposition"]
        reason = record["reason"]
        op_id = record["op_id"]
        program_index = record["program_index"]
        element_id = record["element_id"]
        evidence_state = record["evidence_state"]
        if (not isinstance(source_id, str) or not source_id
                or not isinstance(leaf_id, str) or not leaf_id
                or not isinstance(category, str) or not category
                or leaf_kind not in {"op", "atom"}
                or disposition not in {
                    "emitted_semantic_op", "atom_escrow",
                    "datum_policy_pin", "typed_residual"}):
            raise ValueError("materialization accounting record is untyped")
        if source_id in records_by_source or leaf_id in record_leaf_ids:
            raise ValueError("materialization accounting repeats a leaf")
        leaf = leaves_by_source.get(source_id)
        if leaf is None or leaf.get("_id") != leaf_id \
                or leaf.get("kind") != leaf_kind:
            raise ValueError("materialization accounting record is unbound")
        expected_category = (
            leaf.get("op_name") if leaf_kind == "op" else leaf.get("category"))
        if category != expected_category:
            raise ValueError("materialization accounting category mismatch")
        expected_op_id = "e" + source_id
        location = wire_ops.get(expected_op_id)

        if disposition == "emitted_semantic_op":
            if (leaf_kind != "op" or op_id != expected_op_id
                    or isinstance(program_index, bool)
                    or not isinstance(program_index, int)
                    or program_index < 0 or reason is not None
                    or element_id is not None or evidence_state is not None
                    or location is None or location[0] != program_index
                    or location[1].get("op") != category):
                raise ValueError("emitted semantic accounting is not exact")
            accounted_op_ids.add(expected_op_id)
        elif disposition == "atom_escrow":
            if (leaf_kind != "atom" or op_id != expected_op_id
                    or isinstance(program_index, bool)
                    or not isinstance(program_index, int)
                    or program_index < 0 or reason is not None
                    or element_id is not None
                    or evidence_state != "pending_runtime_witness"
                    or location is None or location[0] != program_index
                    or location[1].get("op") != "create_directshape"):
                raise ValueError("atom escrow accounting is not exact")
            accounted_op_ids.add(expected_op_id)
        elif disposition == "datum_policy_pin":
            try:
                source_element_id = int(source_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("datum pin source is not an ElementId") from exc
            if (leaf_kind != "op"
                    or leaf.get("op_name") not in {"create_level", "create_grid"}
                    or op_id is not None or program_index is not None
                    or reason != "datum_pinned_existing"
                    or isinstance(element_id, bool)
                    or element_id != source_element_id
                    or evidence_state != "same_document_unproven"
                    or location is not None):
                raise ValueError("datum pin accounting is not exact")
        else:
            if (op_id is not None or program_index is not None
                    or element_id is not None or evidence_state is not None
                    or not isinstance(reason, str) or not reason
                    or location is not None):
                raise ValueError("typed residual accounting is not exact")
            if leaf_kind == "atom":
                if reason not in atom_residual_reasons:
                    raise ValueError("atom residual reason is outside closed set")
                if reason.startswith("atom:") and reason.split(":", 1)[1] != \
                        leaf["reason"]["code"]:
                    raise ValueError("atom residual reason disagrees with leaf")
            elif (not reason.startswith("host_unmaterialized:")
                  or not reason.split(":", 1)[1]):
                raise ValueError("semantic residual reason is untyped")
        records_by_source[source_id] = record
        record_leaf_ids.add(leaf_id)
        records.append(record)

    if set(records_by_source) != set(leaves_by_source):
        raise ValueError("materialization accounting is missing an input leaf")
    if accounted_op_ids != set(wire_ops):
        raise ValueError("materialized wire has a missing or duplicate source")
    if records != sorted(
            records, key=lambda row: (row["source_id"], row["leaf_id"])):
        raise ValueError("materialization accounting record order is non-canonical")

    derived_counts = {
        "input_leaves": len(records),
        "emitted_semantic_ops": sum(
            row["disposition"] == "emitted_semantic_op" for row in records),
        "atom_escrows": sum(
            row["disposition"] == "atom_escrow" for row in records),
        "datum_policy_pins": sum(
            row["disposition"] == "datum_policy_pin" for row in records),
        "typed_residuals": sum(
            row["disposition"] == "typed_residual" for row in records),
        "programs": len(programs),
        "emitted_ops": len(wire_ops),
    }
    if counts != derived_counts:
        raise ValueError("materialization accounting counts disagree with wire")

    skip_rows = [
        _normalize_materialization_skip(record)
        for record in (getattr(materialized, "skipped", ()) or ())
    ]
    if len({row["source_id"] for row in skip_rows}) != len(skip_rows):
        raise ValueError("skip evidence repeats a source")
    expected_skips = sorted(
        (row["source_id"], row["category"], row["reason"])
        for row in records
        if row["disposition"] in {"datum_policy_pin", "typed_residual"})
    actual_skips = sorted(
        (row["source_id"], row["category"], row["reason"])
        for row in skip_rows)
    if expected_skips != actual_skips:
        raise ValueError("skip evidence disagrees with accounting")

    escrow_evidence = list(getattr(materialized, "escrowed", ()) or ())
    escrow_by_source: dict[str, Any] = {}
    for evidence in escrow_evidence:
        source_id = (evidence.get("source_id")
                     if isinstance(evidence, Mapping)
                     else getattr(evidence, "source_id", None))
        if not isinstance(source_id, str) or not source_id \
                or source_id in escrow_by_source:
            raise ValueError("escrow evidence identity is missing or duplicate")
        escrow_by_source[source_id] = evidence
    expected_escrow_sources = {
        row["source_id"] for row in records
        if row["disposition"] == "atom_escrow"}
    if set(escrow_by_source) != expected_escrow_sources:
        raise ValueError("escrow evidence disagrees with accounting")
    for source_id in expected_escrow_sources:
        evidence = escrow_by_source[source_id]
        get_value = evidence.get if isinstance(evidence, Mapping) \
            else lambda name: getattr(evidence, name, None)
        record = records_by_source[source_id]
        if (get_value("op_id") != record["op_id"]
                or get_value("program_index") != record["program_index"]
                or get_value("acceptance_state") != "pending_runtime_witness"):
            raise ValueError("escrow pending evidence is not bound to its op")

    expected_stats = {
        "op_leaves": sum(row["leaf_kind"] == "op" for row in records),
        "materialized_ops": len(wire_ops),
        "programs": len(programs),
        "atoms_skipped": sum(
            row["leaf_kind"] == "atom"
            and row["disposition"] == "typed_residual" for row in records),
        "atoms_escrowed": len(expected_escrow_sources),
        "datums_skipped": sum(
            row["disposition"] == "datum_policy_pin" for row in records),
        "semantic_ops_skipped": sum(
            row["leaf_kind"] == "op"
            and row["disposition"] == "typed_residual" for row in records),
    }
    stats = getattr(materialized, "stats", None)
    for name, expected in expected_stats.items():
        if _accounting_stat(stats, name) != expected:
            raise ValueError(f"materialization stats.{name} mismatch")

    return {
        "payload": payload,
        "records": records,
        "skip_rows": skip_rows,
        "escrow_evidence": escrow_evidence,
    }


async def handle_revit_rebuild(args: Any, llm_client, bridge_callback,
                               query_id: str = "") -> dict:
    """Admin rebuild driver (thin).  NEVER raises; typed dict only.

    ``args``: {doc_stamp, dry_run?, offset_mm?}.  Loads the persisted decompile
    leaves for ``doc_stamp`` and hands them to the A3 materializer
    (``leaves_to_program``).  The materializer is built by a PARALLEL wave; when
    it is absent this returns a typed ``materializer_pending`` refusal.  With
    ``dry_run=True`` it only compile-gates every chunk (no execution) and
    returns a per-chunk ok/refused summary.
    """
    try:
        if not revit_decompile_enabled():
            return _typed_error("gate", admin_gate_message_ru(
                "revit_rebuild",
                # The gate names the CALLER: these three stand behind
                # `revit_decompile_enabled` — a different flag, there is
                # no mode.
                flag=_DECOMPILE_FLAG, needs_mode=False))
        try:
            from kir.decompile.materialize import (  # type: ignore
                leaves_to_program,
            )
        except Exception:  # noqa: BLE001 — wave A3 not merged yet
            return {"ok": False, "refused": True, "error": "materializer_pending",
                    "message_ru": "материализатор (волна A3) ещё не подключён"}

        if not isinstance(args, dict):
            return _typed_error("args", "rebuild args должен быть объектом")
        doc_stamp = args.get("doc_stamp")
        if not isinstance(doc_stamp, str) or not doc_stamp:
            return _typed_error("args", "rebuild требует непустой doc_stamp")
        dry_run = args.get("dry_run", True)
        if not isinstance(dry_run, bool):
            return _typed_error("args", "dry_run должен быть JSON boolean")
        allow_partial = args.get("allow_partial", False)
        if not isinstance(allow_partial, bool):
            return _typed_error(
                "args", "allow_partial должен быть JSON boolean")
        base_doc_stamp = args.get("base_doc_stamp")
        if base_doc_stamp is not None and (
                not isinstance(base_doc_stamp, str) or not base_doc_stamp):
            return _typed_error(
                "args", "base_doc_stamp должен быть непустой строкой")
        current_doc_stamp = args.get("current_doc_stamp")
        if current_doc_stamp is not None and (
                not isinstance(current_doc_stamp, str)
                or not current_doc_stamp):
            return _typed_error(
                "args", "current_doc_stamp должен быть непустой строкой")
        allow_conflicts = args.get("allow_conflicts", False)
        if not isinstance(allow_conflicts, bool):
            return _typed_error(
                "args", "allow_conflicts должен быть JSON boolean")
        if current_doc_stamp is not None and base_doc_stamp is None:
            # The guard compares the document AGAINST THE BASE. Without
            # a base there is nothing to compare against, and accepting
            # the argument while doing nothing with it would mean
            # answering "checked" for something that was never checked.
            return _typed_error(
                "args",
                "current_doc_stamp без base_doc_stamp бессмыслен — страж "
                "сравнивает документ с базой дельты")

        out_dir = _decompile_out_dir(doc_stamp)
        import json as _json
        import os as _os
        tree_path = _os.path.join(out_dir, "tree.json")
        if not _snapshot_exists(tree_path):
            return {"ok": False, "error": "no_decompile",
                    "message_ru": "нет декомпайла для этого doc_stamp — сначала запусти decompile"}
        # §18.4, the law of contagion: a rebuild from a parse taken
        # with closed worksets builds PART of the building and says
        # nothing about it. The gate used to stand only on A5 — an
        # instrument that MEASURES; here is an instrument that WRITES,
        # and before this wave it passed such a parse through without a
        # single word. The carve-out is named and lands in the report,
        # just like A5's.
        partial_read = _partial_read_state(out_dir)
        if partial_read["is_partial_read"] and not allow_partial:
            return {
                "ok": False,
                "error": "partial_read",
                "message_ru": (
                    "модель прочитана неполно — закрытые рабочие наборы "
                    f"({partial_read['worksets_closed']}); открой все "
                    "ворксеты и перечитай (или передай allow_partial=true, "
                    "и пометка уйдёт в отчёт)"),
                "worksets_closed": partial_read["worksets_closed"],
                "is_partial_read": True,
            }
        with _open_snapshot(tree_path, "rt", encoding="utf-8") as handle:
            tree = _json.load(handle)

        from kir.decompile.fold import iter_l1_leaves
        leaves = list(iter_l1_leaves(tree))

        # ── REBUILDING BY DELTA, NOT THE WHOLE BUILDING ─────────────────────
        # Before this wave, the one live rebuild entry point took ALL
        # leaves of `tree.json` and rematerialized the whole building
        # from scratch — even when the previous parse of that same
        # building sat right there and the edit was one floor. The
        # `rebuild` layer has been able to compute a delta since 27.07,
        # but nobody called it; here it gets a caller.
        #
        # Three refusals instead of a silent full rebuild — because a
        # delta applied to the wrong A is a silently wrong result:
        #   * a base is named, but the flag is off — the carve-out must
        #     not turn itself on;
        #   * there is no base on disk — "nothing to compare against"
        #     is not "no differences";
        #   * the delta does not take state(A) to state(B) —
        #     `DeltaApplyError`.
        # None of these silently falls back to a full rebuild: the
        # operator asked for a delta and must be told when they won't
        # get one.
        delta_report: dict | None = None
        if base_doc_stamp is not None:
            from kir.decompile.rebuild import rebuild_enabled
            if not rebuild_enabled():
                return {
                    "ok": False, "refused": True,
                    "error": "rebuild_delta_disabled",
                    "message_ru": (
                        "base_doc_stamp задан, но дельта-пересборка выключена "
                        "— включи KUKAI_IR_REBUILD"),
                }
            # `@journal` — the base is NOT named by the operator, it is
            # taken from the building's recorded history. Resolved
            # BEFORE any base checks, so that from here on the path is
            # exactly the one an explicitly named base would take: the
            # "delta from the journal" branch has no right to be
            # weaker.
            base_source = "named"
            if base_doc_stamp == JOURNAL_BASE_TOKEN:
                resolved, refusal = _resolve_base_from_journal(
                    out_dir, doc_stamp)
                if refusal is not None:
                    return refusal
                base_doc_stamp = resolved
                base_source = "journal"
            base_dir = _decompile_out_dir(base_doc_stamp)
            base_tree_path = _os.path.join(base_dir, "tree.json")
            if not _snapshot_exists(base_tree_path):
                return {
                    "ok": False, "error": "no_base_decompile",
                    "message_ru": (
                        "нет разбора для base_doc_stamp — дельту не от чего "
                        "считать"),
                    "base_doc_stamp": base_doc_stamp,
                }
            from kir.decompile.rebuild import RebuildError
            from kir.decompile.rebuild_plan import (
                delta_rebuild_plan, plan_report,
            )
            with _open_snapshot(base_tree_path, "rt", encoding="utf-8") as handle:
                base_tree = _json.load(handle)
            try:
                plan = delta_rebuild_plan(
                    base_tree, tree,
                    label_a=base_doc_stamp, label_b=doc_stamp)
            except (RebuildError, KeyError, TypeError, ValueError) as exc:
                return {
                    "ok": False, "refused": True,
                    "error": "delta_not_applicable",
                    "message_ru": (
                        "дельта не переводит состояние базы в состояние цели "
                        "— пересборка от этой базы отказана"),
                    "detail": f"{type(exc).__name__}: {exc}"[:400],
                    "base_doc_stamp": base_doc_stamp,
                }
            wanted = plan.materialize_source_ids
            leaves = [
                leaf for leaf in leaves
                if leaf["source_element_id"] in wanted]
            delta_report = plan_report(plan)
            delta_report["base_doc_stamp"] = base_doc_stamp
            # A choice the compiler makes must be DISCLOSED, not merely
            # made (the same law as the named default in ground.py):
            # the answer must show whether the base was named or pulled
            # from the journal, and exactly which one was pulled.
            delta_report["base_source"] = base_source
            # Removing old delta elements NAMES the action but does not perform
            # it: the previously built copy has no "sheet A → ElementId" map,
            # and inventing one here would mean deleting blind. The list rides
            # in the report for exactly that reason — staying silent about it
            # would be a promise that the building will converge, when only
            # the added part will.
            delta_report["retire_not_executed"] = True
            # The one thing the compiler CANNOT check: whether the target
            # document actually holds the base state. The theorem is proved
            # about state(A), and that the document IS A is a claim made by the
            # operator, made by the very fact of `base_doc_stamp`. This cannot
            # be left unsaid: a delta built against someone else's document
            # will build exactly the diff and stay silent about the fact that
            # there is no building underneath it.
            delta_report["precondition_ru"] = (
                "дельта верна, только если в документе уже стоит здание "
                f"{base_doc_stamp}; проверить это офлайн компилятор не может")

            # ── guard: will the delta erase someone else's work ────────────
            # The one place where live reassembly can SILENTLY give the wrong
            # outcome: the operator edited the document after the base was
            # taken off it. The delta will build exactly the diff A→B and stay
            # silent about the fact that what's under it is no longer A. A
            # fresh decompile of the same document turns `precondition_ru`
            # from a promise into a measurement.
            if current_doc_stamp is not None:
                from kir.decompile.merge3 import merge_enabled
                if not merge_enabled():
                    return {
                        "ok": False, "refused": True,
                        "error": "merge_guard_disabled",
                        "message_ru": (
                            "current_doc_stamp задан, но страж слияния "
                            "выключен — включи KUKAI_IR_MERGE3"),
                    }
                # `@journal` is deliberately NOT supported here: the head of
                # the journal is almost always the target itself, and the
                # guard would compare the target against itself, getting "no
                # conflicts". A false "checked" is worse than an honest
                # "not checked", so a fresh decompile of the document is
                # named explicitly — like any other decompile.
                if current_doc_stamp in (doc_stamp, JOURNAL_BASE_TOKEN):
                    return _typed_error(
                        "args",
                        "current_doc_stamp обязан называть СВЕЖИЙ разбор "
                        "документа, а не цель пересборки: сравнение цели с "
                        "собой всегда даёт «конфликтов нет»")
                current_tree_path = _os.path.join(
                    _decompile_out_dir(current_doc_stamp), "tree.json")
                if not _snapshot_exists(current_tree_path):
                    return {
                        "ok": False, "error": "no_current_decompile",
                        "message_ru": (
                            "нет разбора для current_doc_stamp — состояние "
                            "документа не с чем сравнить"),
                        "current_doc_stamp": current_doc_stamp,
                    }
                from kir.decompile.merge_guard import (
                    VERDICT_CONFIRMED, guard_report,
                )
                with _open_snapshot(current_tree_path, "rt", encoding="utf-8") as handle:
                    current_tree = _json.load(handle)
                guard = guard_report(
                    base_tree, current_tree, tree,
                    base_label=base_doc_stamp,
                    current_label=current_doc_stamp,
                    target_label=doc_stamp)
                delta_report["merge_guard"] = guard
                if not guard.get("ok"):
                    return {
                        "ok": False, "refused": True,
                        "error": "merge_guard_failed",
                        "message_ru": (
                            "страж слияния не смог сравнить документ с базой "
                            "— пересборка отказана, а не проведена вслепую"),
                        "merge_guard": guard,
                    }
                if guard["verdict"] == VERDICT_CONFIRMED:
                    # The whole reason the guard exists: the condition is
                    # CHECKED.
                    delta_report["precondition_ru"] = (
                        f"в документе стоит здание {base_doc_stamp} — "
                        f"проверено свежим разбором {current_doc_stamp}")
                    delta_report["precondition_verified"] = True
                else:
                    # It diverged — and that too is a MEASUREMENT, not the old
                    # ignorance: it states by how much the document has drifted
                    # and whether it conflicts with the delta. The base
                    # condition is NOT satisfied in this case, and lying about
                    # it with the word "checked" is not allowed.
                    delta_report["precondition_verified"] = False
                    delta_report["precondition_ru"] = (
                        f"в документе НЕ здание {base_doc_stamp}: свежий "
                        f"разбор {current_doc_stamp} ушёл от базы на "
                        f"{guard['auto_merged']} правок, спорных с дельтой — "
                        f"{guard['conflicts_total']}")
                if guard["verdict"] != VERDICT_CONFIRMED \
                        and guard["conflicts_total"] and not allow_conflicts:
                    # A refusal, not a warning: a conflict means two edits to
                    # the same thing, and ours would erase the other one.
                    # Only someone who explicitly agreed to it has the right
                    # to live through that silently.
                    return {
                        "ok": False, "refused": True,
                        "error": "merge_conflicts",
                        "message_ru": guard["message_ru"],
                        "merge_guard": guard,
                    }

        raw_offset = args.get("offset_mm")
        offset_mm = None
        if raw_offset is not None:
            import math as _math
            if (not isinstance(raw_offset, list) or len(raw_offset) != 3
                    or any(isinstance(value, bool)
                           or not isinstance(value, (int, float))
                           or not _math.isfinite(float(value))
                           for value in raw_offset)):
                return _typed_error(
                    "args", "offset_mm должен быть [dx,dy,dz] конечных чисел")
            offset_mm = tuple(float(value) for value in raw_offset)
        # A3's leaves_to_program returns a MaterializeResult; the compiler-ready
        # KIR programs live on its ``.programs`` field (iterating the result
        # object itself raises TypeError).
        materialize_kwargs: dict[str, Any] = {"mode": "same_document"}
        materialize_mode = "same_document"
        if atom_escrow_enabled():
            geometry_path = _os.path.join(out_dir, "geometry.bundle.json")
            if not _os.path.isfile(geometry_path):
                return {
                    "ok": False,
                    "refused": True,
                    "error": "atom_escrow_missing",
                    "message_ru": (
                        "KIR atom escrow включён, но geometry.bundle.json "
                        "отсутствует — перечитай модель новым decompile"),
                }
            try:
                geometry, _geometry_digest = _load_atom_escrow_bundle(
                    out_dir, leaves)
            except FileNotFoundError:
                return {
                    "ok": False,
                    "refused": True,
                    "error": "atom_escrow_missing",
                    "message_ru": (
                        "KIR atom escrow требует geometry.bundle.json и "
                        "его revision-bound geometry.proof.json — перечитай "
                        "модель новым decompile"),
                }
            except Exception as exc:  # noqa: BLE001 — typed evidence refusal
                return {
                    "ok": False,
                    "refused": True,
                    "error": "atom_escrow_invalid",
                    "message_ru": (
                        "geometry.bundle.json не прошёл typed KIR boundary"),
                    "detail": f"{type(exc).__name__}: {exc}"[:400],
                }
            materialize_mode = "escrow"
            materialize_kwargs.update({
                "mode": materialize_mode,
                "geometry": geometry,
            })
        if offset_mm is not None:
            materialize_kwargs["offset_mm"] = offset_mm
        materialized = leaves_to_program(leaves, **materialize_kwargs)
        programs = materialized.programs
        try:
            verified_accounting = _verify_materialization_accounting(
                leaves, programs, materialized)
        except Exception as exc:  # noqa: BLE001 — untrusted result boundary
            return {
                "schema_version": _REBUILD_SUMMARY_SCHEMA,
                "ok": False,
                "refused": True,
                "complete": False,
                "partial": False,
                "error": "materialization_accounting_invalid",
                "materialize_mode": materialize_mode,
                "message_ru": (
                    "пересборка отказана: versioned materialization receipt "
                    "не доказывает ровно один исход для каждого входного листа"),
                "detail": f"{type(exc).__name__}: {exc}"[:400],
            }

        accounting_payload = verified_accounting["payload"]
        accounting_records = verified_accounting["records"]
        skip_rows = verified_accounting["skip_rows"]
        escrow_evidence = verified_accounting["escrow_evidence"]
        skip_by_source = {row["source_id"]: row for row in skip_rows}
        policy_records = [
            row for row in accounting_records
            if row["disposition"] == "datum_policy_pin"]
        atom_residual_records = [
            row for row in accounting_records
            if (row["leaf_kind"] == "atom"
                and row["disposition"] == "typed_residual")]
        semantic_residual_records = [
            row for row in accounting_records
            if (row["leaf_kind"] == "op"
                and row["disposition"] == "typed_residual")]
        escrow_records = [
            row for row in accounting_records
            if row["disposition"] == "atom_escrow"]
        policy_skips = [
            skip_by_source[row["source_id"]] for row in policy_records]
        atom_residuals = [
            skip_by_source[row["source_id"]]
            for row in atom_residual_records]
        blocking_skips = [
            skip_by_source[row["source_id"]]
            for row in semantic_residual_records]

        # ``all([])`` is true.  Therefore zero programs are acceptable only
        # when there was no materializable semantic op (an empty model, datum
        # policy pins, or atom-only residual input).  This is the exact bug
        # that previously made a disappeared create_dimension look green.
        materializable_intent = sum(
            row["leaf_kind"] == "op"
            and row["disposition"] != "datum_policy_pin"
            for row in accounting_records)
        empty_chunk_indices = [
            index for index, program in enumerate(programs)
            if not isinstance(program, dict)
            or not isinstance(program.get("ops"), list)
            or not program["ops"]
        ]
        emitted_ops = accounting_payload["counts"]["emitted_ops"]
        empty_materialization = (
            materializable_intent > 0 and emitted_ops == 0)
        # A retained plan is only an optimisation.  The raw program remains
        # authoritative: replan it here, then reuse a retained immutable plan
        # only when source receipt, plan check and freshly derived plan digest
        # all agree.  A positional tuple can no longer compile a sibling raw
        # program by accident.
        materialized_plans = getattr(materialized, "plans", ()) or ()
        materialized_plan_checks = (
            getattr(materialized, "plan_checks", ()) or ())

        from kir.compiler import compile_rebuild_chunk, plan_program
        from kir.midend import PlannedProgram
        revit_version = _resolved_revit_version(llm_client).version

        # Source catalog for the DRY gate — one shared function, see its
        # docstring: without the catalog the gate refused whole chunks
        # (KIR-G103).
        dry_snapshot = source_catalogue_snapshot(out_dir)

        chunks: list[dict] = []
        for index, program in enumerate(programs):
            # Single rebuild policy point (bulk+per_op+de-join) — the dry-run
            # gate must compile EXACTLY what the live rebuild will run.
            retained_plan = (
                materialized_plans[index]
                if index < len(materialized_plans)
                else None
            )
            retained_check = (
                materialized_plan_checks[index]
                if index < len(materialized_plan_checks)
                else None
            )
            plan_binding = "replanned_raw"
            try:
                exact_plan = plan_program(program, bulk=True)
            except Exception:  # compile raw below for its typed diagnostics
                compile_input = program
                plan_binding = "raw_plan_refused"
            else:
                def _check_value(name: str) -> Any:
                    if isinstance(retained_check, Mapping):
                        return retained_check.get(name)
                    return getattr(retained_check, name, None)

                source_digest = _materialization_digest(program)
                retained_is_exact = (
                    isinstance(retained_plan, PlannedProgram)
                    and _check_value("program_index") == index
                    and _check_value("accepted") is True
                    and _check_value("source_digest") == source_digest
                    and _check_value("plan_digest") == exact_plan.plan_digest
                    and retained_plan.plan_digest == exact_plan.plan_digest
                )
                if retained_is_exact:
                    compile_input = retained_plan
                    plan_binding = "retained_verified"
                else:
                    compile_input = exact_plan
            out = compile_rebuild_chunk(
                compile_input,
                revit_version=revit_version,
                snapshot=dry_snapshot,
            )
            chunk = {
                "chunk": index,
                "ok": bool(out.ok),
                "refused": not out.ok,
                "diagnostics": ([d.as_dict() for d in out.diagnostics][:4]
                                if not out.ok else []),
                **(_diagnostics_total(out.diagnostics, 4) if not out.ok else {}),
                "plan_binding": plan_binding,
            }
            if out.planned is not None:
                chunk["plan_digest"] = out.planned.plan_digest
            chunks.append(chunk)
        ok_count = sum(1 for c in chunks if c["ok"])
        chunks_compile_ok = all(c["ok"] for c in chunks)
        summary_ok = (
            chunks_compile_ok
            and not blocking_skips
            and not empty_chunk_indices
            and not empty_materialization
        )
        summary = {"schema_version": _REBUILD_SUMMARY_SCHEMA,
                   "ok": summary_ok,
                   "dry_run": dry_run, "chunks_total": len(chunks),
                   "chunks_ok": ok_count, "chunks": chunks[:50],
                   "materialize_mode": materialize_mode,
                   "offset_mm": (list(offset_mm)
                                 if offset_mm is not None else None)}
        summary["refused"] = not summary_ok
        summary["materializable_intent"] = materializable_intent
        summary["materialized_ops"] = emitted_ops
        summary["skips_total"] = len(skip_rows)
        summary["semantic_skips"] = len(blocking_skips)
        summary["policy_skips"] = len(policy_skips)
        summary["residual_skips"] = len(atom_residuals)
        summary["atom_residuals"] = len(atom_residuals)
        pending_acceptance = len(escrow_records)
        datum_binding_unproven = bool(policy_records)
        partial_reasons: list[str] = []
        if atom_residuals:
            partial_reasons.append("atom_residuals")
        if pending_acceptance:
            partial_reasons.append("pending_runtime_witness")
        if partial_read["is_partial_read"]:
            partial_reasons.append("partial_read")
        summary["complete"] = bool(
            summary_ok
            and not partial_reasons
            and not datum_binding_unproven)
        # A datum pin with unproved active-document identity is incomplete but
        # is not a partial semantic model.  Atoms, escrow awaiting runtime and
        # a permitted partial read are genuinely partial.
        summary["partial"] = bool(partial_reasons)
        summary["partial_reasons"] = partial_reasons
        summary["datum_binding_state"] = (
            "same_document_unproven"
            if datum_binding_unproven else "not_applicable")
        summary["pending_acceptance_evidence"] = bool(pending_acceptance)
        summary["pending_acceptance_evidence_count"] = pending_acceptance
        summary["fidelity_state"] = (
            "refused" if not summary_ok
            else "partial" if partial_reasons
            else "incomplete_unproven_binding" if datum_binding_unproven
            else "complete"
        )
        summary["skips"] = skip_rows[:50]
        summary["skips_truncated"] = len(skip_rows) > 50
        summary["empty_chunks"] = empty_chunk_indices[:50]
        if blocking_skips:
            summary["error"] = "semantic_skips"
        elif empty_materialization:
            summary["error"] = "empty_materialization"
        elif empty_chunk_indices:
            summary["error"] = "empty_chunk"
        elif not chunks_compile_ok:
            summary["error"] = "compile_refused"
        summary["atoms_escrowed"] = accounting_payload["counts"][
            "atom_escrows"]
        summary["atoms_skipped"] = len(atom_residuals)
        summary["escrow_evidence"] = [
            (record.as_dict() if hasattr(record, "as_dict") else dict(record))
            for record in escrow_evidence[:50]
            if hasattr(record, "as_dict") or isinstance(record, Mapping)
        ]
        summary["materialization_accounting"] = {
            "schema_version": accounting_payload["schema_version"],
            "receipt_digest": accounting_payload["receipt_digest"],
            "input_digest": accounting_payload["input_digest"],
            "programs_digest": accounting_payload["programs_digest"],
            "counts": dict(accounting_payload["counts"]),
        }
        # §18.4: a derived artifact of a partial read carries a mark — both
        # when the operator explicitly allowed the carve-out, and when the
        # read was complete (False, not the absence of a key: "not marked" and
        # "not measured" are different things).
        # The delta is not a detail inside the chunks, but the first thing
        # whoever is asking "what does this rebuild cost" is entitled to see.
        # An absent key and `null` are different things: the key is always
        # present, a null value means "the whole building was rebuilt".
        summary["delta"] = delta_report
        if delta_report is not None:
            summary["message_delta_ru"] = (
                f"дельта от {delta_report['base_doc_stamp']}: "
                f"{delta_report['delta_leaves']} листьев вместо "
                f"{delta_report['full_leaves']}")
        summary["is_partial_read"] = bool(partial_read["is_partial_read"])
        summary["worksets_closed"] = partial_read["worksets_closed"]
        if partial_read["is_partial_read"]:
            summary["allow_partial"] = bool(allow_partial)
            summary["partial_read_note_ru"] = (
                "результат построен на ЧАСТИЧНОМ чтении: закрытых рабочих "
                f"наборов {partial_read['worksets_closed']}")
        if summary_ok and (atom_residuals or pending_acceptance):
            summary["message_ru"] = (
                f"dry-run компайл-гейт: {ok_count}/{len(chunks)} чанков ok; "
                "результат ЧАСТИЧНЫЙ: "
                f"atom residual={len(atom_residuals)}, "
                f"pending runtime witness={pending_acceptance}")
        elif summary_ok and partial_read["is_partial_read"]:
            summary["message_ru"] = (
                f"dry-run компайл-гейт: {ok_count}/{len(chunks)} чанков ok; "
                "результат ЧАСТИЧНЫЙ из-за неполного чтения")
        elif summary_ok and policy_skips:
            summary["message_ru"] = (
                f"dry-run компайл-гейт: {ok_count}/{len(chunks)} чанков ok; "
                f"{len(policy_skips)} datum-листьев явно pinned existing, "
                "но binding активного документа не доказан; complete=false")
        elif summary_ok:
            summary["message_ru"] = (
                f"dry-run компайл-гейт: {ok_count}/{len(chunks)} чанков ok")
        elif blocking_skips:
            summary["message_ru"] = (
                "пересборка отказана: материализатор не выразил "
                f"{len(blocking_skips)} семантических листьев; причины в skips")
        elif empty_materialization:
            summary["message_ru"] = (
                "пересборка отказана: вход содержал "
                f"{materializable_intent} материализуемых листьев, но ни один "
                "исполняемый оп не получен")
        elif empty_chunk_indices:
            summary["message_ru"] = (
                "пересборка отказана: материализатор вернул пустой чанк")
        else:
            summary["message_ru"] = (
                f"dry-run компайл-гейт: {ok_count}/{len(chunks)} чанков ok")
        if not summary_ok:
            return summary
        if dry_run:
            return summary
        # Live execution stays behind the same admin gate.
        return {"ok": False, "refused": True, "error": "live_rebuild_unimplemented",
                "message_ru": "живой rebuild будет включён после live-приёмки A3",
                "dry_run_summary": summary}
    except Exception as exc:  # noqa: BLE001 — absolute fail-open
        logger.exception("revit_rebuild handler internal error")
        return _typed_error(*_failure_stage(exc, "rebuild"))


# ─────────────────────────────────────────────────────────────────────────────
# Wave A5 — live idempotence («decompile → rebuild reproduces the building»)
#
# The northern-star measurement, WRITE-bearing (rebuild + delete), so it is
# gated exactly like rebuild (flag + admin) AND additionally fail-closed on a
# live ``doc.Title`` copy guard (Д3): the live path REFUSES unless the currently
# open document is confirmed a COPY.  Executed through the SAME ``_run_declarative``
# bridge path as ``handle_revit_rebuild`` — mocked in tests.  The last run's
# exact% / date is stashed for the dashboard.
# ─────────────────────────────────────────────────────────────────────────────

# The write-bearing A5 adapter is isolated from generic tool dispatch.  These
# imports intentionally preserve every historical ``serving.<name>`` seam.
from kir.a5_live import (
    _A5Recovery,
    _A5_SWEEP_SCHEMA_VERSION,
    _DOCUMENT_PROBE_CS,
    _ORPHAN_SWEEP_TEMPLATE,
    _TITLE_PROBE_CS,
    _a5_payload,
    _a5_sweep_payload,
    _active_a5_runs,
    _active_a5_runs_guard,
    _bind_read_to_document,
    _claim_a5_document,
    _cleanup_covers,
    _cleanup_receipt_from_sweep,
    _document_mismatch_expr,
    _document_refusal_cs,
    _new_a5_stamp_scope,
    _op_results,
    _orphan_sweep_cs,
    _receipt_from_journal,
    _release_a5_document,
    build_sweep_payload,
    collect_op_refusals,
    count_ops_without_element,
)
# Last-run metric for the operator dashboard (last run, exact%, date).  Fail-open
# in-memory cache; a persisted mirror is written next to the decompile out_dir.
_last_idempotence: dict[str, Any] = {}


def last_idempotence_metric() -> Optional[dict[str, Any]]:
    """Summary of the LAST A5 run IN THIS PROCESS, or `None`.

    THERE IS NO CONSUMER, and this is stated here, not implied. Previously
    this said "Dashboard hook", i.e. the docstring described a live wiring
    that does not exist anywhere in the tree (measured 11.08.2026: zero
    callers). An instrument whose name and description promise a connection
    is the easiest kind to mistake for working — and that is exactly why the
    promise was removed rather than backed by an invented consumer.

    WHAT DOES WORK, AND WHY NOTHING WAS DELETED:

    * runs DID happen. `idempotence.json` sits next to eight decompiles, the
      most recent, `sob62_fas_r23_v18` from 29.07.2026 — 44 keys,
      `raw_exact_pct` 85.808. The archived note `NOTES_A5.md` claims the
      opposite ("no live run has ever been executed"), but it PREDATES the
      runs;
    * `_last_idempotence` carries a PROPERTY OF CORRECTNESS, not just a value:
      a run whose cleanup failed must leave it EMPTY, and this is held by a
      test. Deleting the dict would drop the requirement.

    THE GAP WHOEVER WIRES IT UP MUST CLOSE. The dict lives in process memory,
    while the data lives on disk (`idempotence.json`). After a restart this is
    `None` even though eight runs have happened, i.e. `None` means TWO
    different facts AT ONCE: "there were no runs in this process" and "there
    were never any runs". Telling them apart means reading the artifact, and
    that needs `doc_stamp`: there are eight decompiles, and the function takes
    no arguments. Adding a signature for a nonexistent consumer is refused
    here: that would be a guess about what it will ask for.
    """
    return dict(_last_idempotence) if _last_idempotence else None


# Pure A5 scope/evidence identity is independent of tool dispatch and bridge
# transport.  Re-export the historical private names for compatibility.
from kir.a5_contract import (
    _a5_request_hash,
    _a5_scope_digest,
    _atom_escrow_source_ids_for_scope,
    _iter_host_refs,
    _load_a5_open_model_profile,
    _load_a5_snapshot_manifest,
    _scope_leaves,
)


async def _probe_document_fingerprint(
    llm_client,
    bridge_callback,
) -> Optional[DocumentFingerprint]:
    """Return the active live-document identity, or None on any uncertainty."""
    try:
        res = await _run_declarative(
            llm_client, bridge_callback, _DOCUMENT_PROBE_CS,
            "idempotence_document", _SNAPSHOT_TIMEOUT_MS)
        payload = res.get("result", res) if isinstance(res, dict) else None
        if isinstance(payload, dict):
            fields = [payload.get(key) for key in (
                "title", "path_name", "project_uid")]
            if all(isinstance(value, str) for value in fields):
                return DocumentFingerprint(*fields)
    except Exception:  # noqa: BLE001 — failed probe means unbound document
        logger.debug("A5 document fingerprint probe failed", exc_info=True)
    return None


async def _probe_doc_title(llm_client, bridge_callback) -> Optional[str]:
    """Compatibility wrapper for callers that need only the copy-guard title."""

    fingerprint = await _probe_document_fingerprint(llm_client, bridge_callback)
    return fingerprint.title if fingerprint is not None else None


async def _probe_a5_document_revision(
    llm_client,
    bridge_callback,
    document_fingerprint: DocumentFingerprint,
) -> Optional[str]:
    """Read the exact revision algorithm used by decompile, identity-bound."""

    try:
        from kir.decompile.pipeline import _REVISION_FINGERPRINT_CS
        code = _bind_read_to_document(
            _REVISION_FINGERPRINT_CS + "\nreturn __KirDocumentRevision();",
            document_fingerprint)
        envelope = await _run_declarative(
            llm_client, bridge_callback, code, "idempotence_revision",
            _SNAPSHOT_TIMEOUT_MS)
        value: Any = envelope
        if isinstance(value, dict) and "result" in value:
            value = value["result"]
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 — uncertainty cannot verify a snapshot
        logger.debug("A5 document revision probe failed", exc_info=True)
        return None


def _default_a5_lease_store():
    return ports.need(ports.APP_STATE).get_app_state().db


async def handle_revit_idempotence(
    args: Any,
    llm_client,
    bridge_callback,
    query_id: str = "",
    *,
    lease_store=None,
) -> dict:
    """Admin idempotence driver.  NEVER raises; every outcome is a typed dict.

    ``args``: {doc_stamp, dry_run?, confirm_token?}.  Loads the persisted
    decompile (``tree.json`` + ``passport.json`` metadata) for ``doc_stamp`` and
    runs :func:`kir.idempotence.run_idempotence`.  ``dry_run`` (default True)
    compile-gates the Δ-programs offline — no writes, no title probe.  The LIVE
    path (``dry_run=False``) first probes ``doc.Title`` and fails closed via the
    orchestrator's :class:`SafetyContext` unless the title confirms a copy.
    """
    claimed_doc_stamp: Optional[str] = None
    lease: Optional[A5Lease] = None
    try:
        if not revit_decompile_enabled():
            return _typed_error("gate", admin_gate_message_ru(
                "revit_idempotence",
                # The gate names the CALLER: these three stand behind
                # `revit_decompile_enabled` — a different flag, there is no
                # mode.
                flag=_DECOMPILE_FLAG, needs_mode=False))
        try:
            from kir.idempotence import (  # type: ignore
                SafetyContext, build_reextract_cs, run_idempotence)
        except Exception:  # noqa: BLE001 — orchestrator absent
            return {"ok": False, "refused": True, "error": "idempotence_pending",
                    "message_ru": "оркестратор идемпотентности (A5) ещё не подключён"}

        if not isinstance(args, dict):
            return _typed_error("args", "idempotence args должен быть объектом")
        doc_stamp = args.get("doc_stamp")
        if not isinstance(doc_stamp, str) or not doc_stamp:
            return _typed_error("args", "idempotence требует непустой doc_stamp")
        dry_value = args.get("dry_run", True)
        keep_value = args.get("keep", False)
        whole_value = args.get("whole_model", False)
        # §18.4: the carve-out of a partial read is an EXPLICIT statement by
        # the operator, not an omission. The value goes into the report (see
        # below).
        allow_partial_value = args.get("allow_partial", False)
        for field_name, value in (
                ("dry_run", dry_value), ("keep", keep_value),
                ("whole_model", whole_value),
                ("allow_partial", allow_partial_value)):
            if not isinstance(value, bool):
                return _typed_error(
                    "args", f"{field_name} должен быть JSON boolean")
        dry_run = dry_value
        keep_delta = keep_value
        whole_model = whole_value
        allow_partial = allow_partial_value
        confirm_token = args.get("confirm_token")
        if confirm_token is not None and not isinstance(confirm_token, str):
            return _typed_error("args", "confirm_token должен быть строкой")

        # Δ-offset of the copy. Defaults to DELTA_MM (200 m), but the operator
        # sets whatever is convenient for comparison next to it, so the value
        # is parametric. It IS part of the request digest: two runs with a
        # different Δ are different runs, and the journal of one must not be
        # allowed to continue the other.
        from kir.idempotence import DELTA_MM as _DEFAULT_DELTA_MM
        raw_delta = args.get("offset_mm")
        if raw_delta is None:
            delta_mm = _DEFAULT_DELTA_MM
        else:
            if (not isinstance(raw_delta, (list, tuple))
                    or len(raw_delta) != 3
                    or not all(isinstance(v, (int, float))
                               and not isinstance(v, bool)
                               and math.isfinite(float(v)) for v in raw_delta)):
                return _typed_error(
                    "args", "offset_mm должен быть [dx,dy,dz] конечных чисел")
            delta_mm = tuple(float(v) for v in raw_delta)

        limit_ops = args.get("limit_ops")
        only_kinds = args.get("only_kinds")
        level_scope = args.get("level_scope")
        scope_keys = {
            key for key in ("limit_ops", "only_kinds", "level_scope")
            if key in args
        }
        if whole_model and scope_keys:
            return _typed_error(
                "args", "whole_model нельзя смешивать с ограниченным scope")
        if not whole_model and not scope_keys:
            return _typed_error(
                "args", "нужен явный scope или whole_model=true")
        if "limit_ops" in scope_keys and (
                isinstance(limit_ops, bool) or not isinstance(limit_ops, int)
                or limit_ops <= 0):
            return _typed_error("args", "limit_ops должен быть целым > 0")
        if "only_kinds" in scope_keys:
            from kir import spec as _spec
            if (not isinstance(only_kinds, list) or not only_kinds
                    or any(not isinstance(item, str) or item not in _spec.OPS
                           for item in only_kinds)):
                return _typed_error(
                    "args", "only_kinds должен быть непустым списком известных op")
        if "level_scope" in scope_keys:
            if not isinstance(level_scope, str) or not level_scope.strip():
                return _typed_error(
                    "args", "level_scope должен быть непустой строкой")
            level_scope = level_scope.strip()
        use_atom_escrow = atom_escrow_enabled()
        if (use_atom_escrow and not whole_model
                and limit_ops is None and level_scope is None):
            return _typed_error(
                "atom_escrow_scope_required",
                "Tier-G atom escrow нельзя привязать только к only_kinds: "
                "у atom нет op_name; укажи limit_ops, level_scope или "
                "whole_model=true")

        out_dir = _decompile_out_dir(doc_stamp)
        import json as _json
        import os as _os
        tree_path = _os.path.join(out_dir, "tree.json")
        passport_path = _os.path.join(out_dir, "passport.json")
        if not _snapshot_exists(tree_path) or not _snapshot_exists(passport_path):
            return {"ok": False, "error": "no_decompile",
                    "message_ru": "нет декомпайла для этого doc_stamp — сначала запусти decompile"}
        try:
            partial_categories = _partial_l0_categories(out_dir)
        except Exception as exc:  # noqa: BLE001 — coverage uncertainty blocks A5
            return {
                "ok": False,
                "error": "snapshot_non_authoritative",
                "message_ru": "A5 заблокирован: coverage-пруф L0 невалиден",
                "coverage_error": repr(exc)[:300],
            }
        if partial_categories:
            return {
                "ok": False,
                "error": "snapshot_non_authoritative",
                "message_ru": "A5 заблокирован: L0 содержит partial-категории",
                "partial_categories": partial_categories,
            }
        # §18.4, the law of contagion: leaves raised from a partial read
        # describe PART of the model. An idempotence check against them cannot
        # be honest: the missing cannot be told apart from the mismatched, and
        # the percentage ends up being about the file-open dialog, not about
        # the compiler.
        partial_read = _partial_read_state(out_dir)
        if partial_read["is_partial_read"] and not allow_partial:
            return {
                "ok": False,
                "error": "partial_read",
                "message_ru": (
                    "модель прочитана неполно — закрытые рабочие наборы "
                    f"({partial_read['worksets_closed']}); открой все "
                    "ворксеты и перечитай (или передай allow_partial=true, "
                    "и пометка уйдёт в отчёт)"),
                "worksets_closed": partial_read["worksets_closed"],
                "is_partial_read": True,
            }
        with _open_snapshot(tree_path, "rt", encoding="utf-8") as handle:
            tree = _json.load(handle)
        from kir.decompile.fold import iter_l1_leaves
        all_leaves = list(iter_l1_leaves(tree))
        atom_geometry = None
        geometry_bundle_digest = None
        if use_atom_escrow:
            try:
                atom_geometry, geometry_bundle_digest = \
                    _load_atom_escrow_bundle(out_dir, all_leaves)
            except FileNotFoundError:
                return {
                    "ok": False,
                    "error": "atom_escrow_missing",
                    "message_ru": (
                        "KIR atom escrow включён, но geometry bundle/proof "
                        "отсутствует — перечитай модель новым decompile"),
                }
            except Exception as exc:  # typed geometry is a hard boundary
                return {
                    "ok": False,
                    "error": "atom_escrow_invalid",
                    "message_ru": (
                        "geometry.bundle.json не прошёл typed KIR boundary"),
                    "detail": f"{type(exc).__name__}: {exc}"[:400],
                }
        leaves = all_leaves
        # Optional scope for a SMALL first live run — a whole-building rebuild is
        # ~51k per-op writes (hours).  Datums remain context, hosts are
        # reached by closure.  Atoms always remain in the denominator; the
        # separate stable allow-list below bounds which of them may become
        # Tier-G writes when that default-off feature is enabled.
        leaves = _scope_leaves(
            leaves,
            limit_ops=None if whole_model else limit_ops,
            only_kinds=None if whole_model else only_kinds,
            level_scope=None if whole_model else level_scope)
        try:
            scope_digest = _a5_scope_digest(leaves)
        except A5JournalError as exc:
            return _typed_error("scope_identity_invalid", str(exc))
        atom_escrow_source_ids = None
        if use_atom_escrow:
            try:
                atom_escrow_source_ids = _atom_escrow_source_ids_for_scope(
                    leaves,
                    whole_model=whole_model,
                    limit_ops=limit_ops,
                    level_scope=level_scope,
                )
            except A5JournalError as exc:
                return _typed_error("atom_escrow_scope_invalid", str(exc))
        # L0 datum context (levels/grids/rooms) for the re-lift.  The frozen
        # L0.jsonl header carries the authoritative L0Document metadata block;
        # the passport does NOT persist it, so read the header first and keep the
        # passport read only as a fallback for older runs.
        with _open_snapshot(passport_path, "rt", encoding="utf-8") as handle:
            passport = _json.load(handle)
        metadata = (_metadata_from_l0_header(out_dir, doc_stamp)
                    or _metadata_from_passport(passport, doc_stamp))
        if metadata is None:
            return {"ok": False, "error": "no_metadata",
                    "message_ru": "L0-метаданные (уровни/сетки/комнаты) не найдены для re-lift"}

        if not dry_run:
            if not _claim_a5_document(doc_stamp):
                return _typed_error(
                    "run_in_progress",
                    "для этого doc_stamp уже выполняется live A5")
            claimed_doc_stamp = doc_stamp

        gate_ok = revit_decompile_enabled()
        # Live path: bind the run to the active document before any write.
        doc_title = None
        document_fingerprint = None
        journal = None
        recovery = None
        recovered_report = None
        source_open_model = None
        rebuild_runner = read_executor = delete_runner = sweep_runner = None
        run_stamp_prefix = None
        #: 🔴 REASON FOR `find_resumable`'S SILENCE, CARRIED THROUGH TO THE
        #: READER (29.08.2026, debt MUTE_SOURCES, location
        #: `kir/a5_recovery.py::find_resumable`). The companion
        #: `resumable_absence_reason()` was written and CALLED BY NO live path
        #: WHATSOEVER — only by its own test, i.e. it proved exactly what runs
        #: (E-7, word for word). Here it gets a live caller, and
        #: `find_resumable`'s answer does not change at all.
        resumable_absence_ru = None
        expected_token = os.environ.get("KUKAI_A5_CONFIRM_TOKEN") or None
        if not dry_run:
            document_fingerprint = await _probe_document_fingerprint(
                llm_client, bridge_callback)
            if document_fingerprint is not None:
                doc_title = document_fingerprint.title
        # `disposable_copy` is the operator's explicit statement that THIS
        # document is disposable. The naming convention remained the first
        # route; the statement counts only together with the exact
        # confirm_token (see SafetyContext).
        declared_copy = args.get("disposable_copy", False)
        if not isinstance(declared_copy, bool):
            return _typed_error("args", "disposable_copy должен быть true/false")
        safety = SafetyContext(
            doc_title=doc_title, gate_ok=gate_ok,
            confirm_token=confirm_token if isinstance(confirm_token, str) else None,
            expected_token=expected_token,
            operator_declared_copy=declared_copy)
        logger.info("A5 safety: proof=%r title=%r declared_copy=%s",
                    safety.copy_proof(), doc_title, declared_copy)

        # Refused live calls never create a journal or acquire a lease.  Once
        # safety admits writes, both are mandatory — there is no process-local
        # fallback for production.
        if (not dry_run and document_fingerprint is not None
                and safety.refusal() is None):
            try:
                manifest = _load_a5_snapshot_manifest(
                    out_dir, doc_stamp=doc_stamp,
                    document_fingerprint=document_fingerprint)
                source_open_model = _load_a5_open_model_profile(
                    out_dir,
                    doc_stamp=doc_stamp,
                    document_fingerprint=document_fingerprint,
                    revision_proof=manifest.revision_proof,
                )
                request_hash = _a5_request_hash(
                    doc_stamp=doc_stamp,
                    revision=manifest.revision_proof,
                    keep_delta=keep_delta,
                    whole_model=whole_model,
                    limit_ops=limit_ops,
                    only_kinds=only_kinds,
                    level_scope=level_scope,
                    revit_version=metadata.revit_version,
                    scope_digest=scope_digest,
                    delta_mm=delta_mm,
                    atom_escrow=use_atom_escrow,
                    geometry_bundle_digest=geometry_bundle_digest,
                    atom_escrow_source_ids=atom_escrow_source_ids)
                journal = A5Journal.find_resumable(
                    out_dir,
                    document_digest=document_fingerprint.digest,
                    request_hash=request_hash)
                if journal is None:
                    # THE ANSWER DOES NOT CHANGE, BUT THE SILENCE GAINS A
                    # REASON. `None` here means two DIFFERENT things: "there
                    # have been no A5 runs here" (true, we start a new one)
                    # and "the a5_runs directory was WIPED OUT" (evidence of
                    # the past run is lost, and the new run will write over
                    # empty ground). The A5 protocol exists for the sake of
                    # evidence after a failure, so a silent zero costs more
                    # here than usual; the suspicion is resolved by the
                    # READER, not the instrument, and so it rides in the
                    # report in words, not in the log.
                    try:
                        resumable_absence_ru = (
                            A5Journal.resumable_absence_reason(out_dir))
                    except OSError as _absence_exc:
                        # Silence must be MEASURABLE: the companion's own
                        # failure is also a reason, and swallowing it would
                        # mean planting a silent value here in place of the
                        # previous unknown. It cannot become a failure of the
                        # whole run: the companion is diagnostic, it does not
                        # decide the answer.
                        resumable_absence_ru = (
                            f"причину тишины спросить не удалось: "
                            f"{_absence_exc!r}")
                run_id = journal.state.run_id if journal is not None else RunId.new()
                stamp_scope, run_stamp_prefix = _a5_stamp_scope(doc_stamp, run_id)
                store = lease_store if lease_store is not None \
                    else _default_a5_lease_store()
                lease = await A5Lease.acquire(
                    store,
                    fingerprint_digest=document_fingerprint.digest,
                    run_id=run_id)
                if journal is not None:
                    journal.repair_torn_tail()
                if journal is None:
                    await lease.ensure_held()
                    active_revision = await _probe_a5_document_revision(
                        llm_client, bridge_callback, document_fingerprint)
                    if active_revision != manifest.revision_proof.fingerprint:
                        raise A5JournalError(
                            "active document revision differs from decompile proof")
                    import hashlib as _hashlib
                    journal = A5Journal.create(
                        out_dir,
                        run_id=run_id,
                        prepared_proof={
                            "doc_stamp_sha256": _hashlib.sha256(
                                doc_stamp.encode("utf-8")).hexdigest(),
                            "request_digest": request_hash,
                            "stamp_prefix": run_stamp_prefix,
                            "document_fingerprint": (
                                document_fingerprint.to_dict()),
                        })
                elif journal.state.prepared.get("stamp_prefix") \
                        != run_stamp_prefix:
                    raise A5JournalError(
                        "resumable journal has an invalid stamp prefix")
                journal.transition(A5Phase.SNAPSHOT_VERIFIED, {
                    "snapshot_manifest": manifest.to_dict()})

                async def _revision_runner() -> Optional[str]:
                    await lease.ensure_held()
                    return await _probe_a5_document_revision(
                        llm_client, bridge_callback, document_fingerprint)

                (rebuild_runner, read_executor, delete_runner,
                 preview_runner, sweep_runner) = _a5_runners(
                    llm_client, bridge_callback, metadata.revit_version,
                    stamp_scope=stamp_scope,
                    stamp_prefix=run_stamp_prefix,
                    document_fingerprint=document_fingerprint,
                    journal=journal, lease=lease,
                    revision_runner=_revision_runner,
                    open_model_profile=source_open_model,
                    ground_snapshot=source_catalogue_snapshot(out_dir))

                recovery = _A5Recovery(
                    journal, lease,
                    stamp_prefix=run_stamp_prefix,
                    preview_runner=preview_runner,
                    sweep_runner=sweep_runner,
                    revision_runner=_revision_runner)
                await recovery.recover_pending_effects()
                active_revision = await _revision_runner()
                if active_revision != recovery.expected_document_revision:
                    raise A5JournalError(
                        "active document revision differs from confirmed A5 state")
                if recovery.completed_during_recovery:
                    recovered_report = recovery.recovered_report()
            except A5LeaseError as exc:
                code = ("run_in_progress" if "active A5 lease" in str(exc)
                        else "lease_unavailable")
                return _typed_error(code, str(exc))
            except Exception as exc:  # no complete proof means no live writes
                return _typed_error(
                    "recovery_unavailable",
                    f"durable A5 recovery недоступен: {exc!r}")

        if recovered_report is not None:
            report = recovered_report
        else:
            report = await run_idempotence(
                leaves, metadata, doc_stamp=doc_stamp, safety=safety,
                rebuild_runner=rebuild_runner, read_executor=read_executor,
                delete_runner=delete_runner, sweep_runner=sweep_runner,
                dry_run=dry_run, delta_mm=delta_mm,
                debug_dir=out_dir, keep_delta=keep_delta, recovery=recovery,
                ground_snapshot=source_catalogue_snapshot(out_dir),
                atom_escrow=use_atom_escrow,
                geometry=atom_geometry,
                escrow_source_ids=atom_escrow_source_ids)
        result = report.to_dict()
        # §18.4: a derived artifact of a partial read CARRIES a mark — and it
        # sits next to the percentages, not in the log. The carve-out is
        # visible in the report as the operator's conscious decision, not as
        # an absence of checking.
        result["is_partial_read"] = bool(partial_read["is_partial_read"])
        result["worksets_closed"] = partial_read["worksets_closed"]
        if partial_read["is_partial_read"]:
            result["allow_partial"] = bool(allow_partial)
            result["partial_read_note_ru"] = (
                "проценты посчитаны по видимой части модели: закрытых рабочих "
                f"наборов {partial_read['worksets_closed']}")
        if recovered_report is not None:
            result["recovered"] = True
        if run_stamp_prefix is not None:
            result["run_stamp_prefix"] = run_stamp_prefix
        if resumable_absence_ru is not None:
            # Next to the percentages, not in the log — under the same
            # discipline as `partial_read_note_ru` above: a suspicion the
            # reader must see has no right to live in debug output.
            result["resumable_absence_note_ru"] = resumable_absence_ru
        if document_fingerprint is not None:
            result["document_fingerprint"] = document_fingerprint.digest
        journal_ok = True
        if journal is not None:
            result["run_journal"] = journal.relative_path
            result["recovery_phase"] = journal.state.phase.value
            journal_ok = (
                report.error is not None or not report.cleanup_ok
                or journal.state.phase is A5Phase.COMPLETED)

        # Dashboard metric (last run, exact%, date) — recorded for real runs.
        successful = (
            report.error is None and (dry_run or report.cleanup_ok)
            and journal_ok)
        if not dry_run and successful:
            import time as _time
            _last_idempotence.clear()
            _last_idempotence.update({
                "doc_stamp": doc_stamp,
                "raw_exact_pct": result["raw_exact_pct"],
                "adjusted_exact_pct": result["adjusted_exact_pct"],
                "multiset_match": result["multiset_match"],
                "updated_at": _time.time(),
            })
            try:
                from kir.decompile.pipeline import _atomic_write_json
                _atomic_write_json(
                    __import__("pathlib").Path(out_dir) / "idempotence.json",
                    {**result, "updated_at": _last_idempotence["updated_at"]})
            except Exception:  # noqa: BLE001 — metric persistence is best-effort
                logger.debug("A5 metric persist failed", exc_info=True)
        if report.error is None and not report.cleanup_ok:
            result["error"] = {
                "code": "cleanup_failed",
                "message": "A5 comparison finished but cleanup was not proven",
                "detail": report.cleanup_detail[:400],
            }
        if not journal_ok:
            result["error"] = {
                "code": "journal_incomplete",
                "message": "A5 outcome has no durable Completed proof",
                "detail": result.get("recovery_phase", "journal absent"),
            }
        result["ok"] = successful
        return result
    except Exception as exc:  # noqa: BLE001 — absolute fail-open
        logger.exception("revit_idempotence handler internal error")
        return _typed_error(*_failure_stage(exc, "идемпотентности"))
    finally:
        if lease is not None:
            try:
                await lease.release()
            except Exception:  # expiry still prevents permanent ownership
                logger.exception("A5 durable lease release failed")
        if claimed_doc_stamp is not None:
            _release_a5_document(claimed_doc_stamp)


def _metadata_from_l0_header(out_dir: str, doc_stamp: str):
    """Reconstruct the L0Document datum context from the frozen L0.jsonl header.

    The first line of ``L0.jsonl`` is the header record ``{"document": {...}}``
    whose ``document`` is the L0Document metadata block (levels/grids/rooms/
    project_info/units) minus the element population.  This is the authoritative
    datum source for A5 re-lift.  Returns None (fail-closed) if the header is
    missing or unusable — no invented datums.
    """
    from kir.decompile.schema import L0Document, L0SchemaError
    import json as _json2
    import os as _os2
    path = _os2.path.join(out_dir, "L0.jsonl")
    # 🔴 A BARE `isfile`/`open` HERE WAS QUIETER THAN A CRASH AND MORE COSTLY
    # THAN ONE. On a compressed decompile both answered "no header", the
    # function honestly returned None — and A5 fell through to
    # `_metadata_from_passport`, which its own caller documents as NOT storing
    # this block. That is, a cooled-down decompile got a `no_metadata` refusal
    # about a building whose levels were fine. Found by the AST matcher on
    # 21.08.2026, the line-based guard did not see it: the path sits in a
    # variable.
    if not _snapshot_exists(path):
        return None
    try:
        with _open_snapshot(path, "rt", encoding="utf-8") as handle:
            header = _json2.loads(handle.readline())
        doc = header.get("document") if isinstance(header, dict) else None
        if not isinstance(doc, dict):
            return None
        return L0Document.from_dict({**doc, "change_stamp": doc_stamp,
                                     "elements": []})
    except (L0SchemaError, Exception):  # noqa: BLE001 — no usable header
        return None


def _partial_read_state(out_dir: str) -> dict:
    """Was this decompile's model known to have been read incompletely (§18.4)?

    The source is the HEADER of the saved L0 (`L0.jsonl`, first line): it is
    the one that survives the run, and it is what the leaves are loaded from.
    The passport is not fit for this — it describes what was seen, and stays
    silent about what wasn't.

    A deliberate migration: decompiles done BEFORE this wave have no
    worksharing/worksets_closed fields in the header. "No data" ⇒ "not
    measured" ⇒ the old behavior (no refusal at all): retroactively declaring
    the whole archive partial would be a lie of the same kind as staying
    silent about incompleteness.
    """
    metadata = _metadata_from_l0_header(out_dir, "probe")
    if metadata is None:
        return {"is_partial_read": False, "worksets_closed": 0,
                "measured": False}
    return {
        "is_partial_read": bool(metadata.is_partial_read),
        "worksets_closed": int(metadata.worksets_closed or 0),
        # 🔴 "MEASURED" IS A FACT ABOUT THE MEASUREMENT, NOT ITS VALUE. Before
        # 25.08 this said `bool(metadata.worksharing)`, and a single-user
        # model (no worksharing, honestly measured) was declared UNMEASURED.
        # That was a fix from OUTSIDE the schema: the fields themselves had no
        # third state, and "no key" arrived indistinguishable from "False".
        # Now the state lives in the header (`partial_read_measured`), and a
        # second carrier is not needed.
        "measured": metadata.partial_read_measured,
    }


def _partial_l0_categories(out_dir: str) -> list[str]:
    """Validate the complete L0 stream and return its partial categories."""

    import os as _os2
    from kir.decompile.extract import L0JSONLReader
    from kir.decompile.schema import CategoryState

    path = _os2.path.join(out_dir, "L0.jsonl")
    if not _snapshot_exists(path):
        raise FileNotFoundError("L0.jsonl is absent")
    statuses = tuple(L0JSONLReader(path).iter_category_status())
    return sorted(
        status.category for status in statuses
        if status.state is CategoryState.PARTIAL)


def _metadata_from_passport(passport: Any, doc_stamp: str):
    """Reconstruct the L0Document metadata (levels/grids/rooms) from a passport.

    The decompile passport persists the document metadata block; A5 re-lift needs
    only the datum context (levels/grids/rooms + names/version), never the full
    element population.  Returns None if the passport lacks a usable metadata
    block (fail-closed — no invented datums).
    """
    from kir.decompile.schema import L0Document, L0SchemaError
    if not isinstance(passport, dict):
        return None
    meta = passport.get("l0_metadata") or passport.get("metadata")
    if not isinstance(meta, dict):
        # Some passports inline the fields at the top level.
        meta = passport
    try:
        return L0Document.from_dict({
            "doc_name": meta.get("doc_name") or passport.get("doc_name") or "doc",
            # THE SEVENTH SITE, found by its own test on 13.08.2026. It
            # looked like "about the saved passport, not the live channel",
            # and that was wrong: `metadata.revit_version` goes as a parameter
            # straight into the rebuild compilation (`:4993`, `:5046`). A
            # passport with no recorded version gave "2026" with no trace —
            # the same gap on the rebuild path.
            "revit_version": _rv.resolve(
                meta.get("revit_version")
                or passport.get("revit_version")).version,
            "units": "mm",
            "change_stamp": doc_stamp,
            "levels": meta.get("levels", []),
            "grids": meta.get("grids", []),
            "rooms": meta.get("rooms", []),
            "project_info": meta.get("project_info")
            or {"name": "", "address": "", "building_type_hint": None},
            "elements": [],
        })
    except (L0SchemaError, Exception):  # noqa: BLE001 — no usable metadata
        return None


def _a5_runners(llm_client, bridge_callback, revit_version: str, *,
                stamp_scope: str, stamp_prefix: str,
                document_fingerprint: DocumentFingerprint,
                journal: A5Journal, lease: A5Lease,
                revision_runner,
                open_model_profile: OpenModelProfile | None = None,
                ground_snapshot: dict | None = None):
    """Build live runners whose writes are leased and write-ahead journaled.

    Each runner compiles its program (rebuild/delete) or ships its read-only C#
    through ``_run_declarative`` — the SAME transport ``handle_revit_rebuild``
    uses.  A compile refusal / bridge error surfaces as a non-``ok`` envelope so
    the orchestrator treats it as a rebuild failure and cleans up.
    """
    from kir.compiler import compile_rebuild_chunk
    from kir.idempotence import collect_created_ids, _deleted_id_witnesses

    counters: dict[str, int] = {}
    for effect_id in (
            *journal.state.pending_effects, *journal.state.effect_receipts):
        kind = effect_id.split(":", 1)[0]
        counters[kind] = counters.get(kind, 0) + 1

    def _next_effect(kind: str) -> str:
        ordinal = counters.get(kind, 0)
        while True:
            effect_id = f"{kind}:{ordinal:06d}"
            ordinal += 1
            if (effect_id not in journal.state.pending_effects
                    and effect_id not in journal.state.effect_receipts):
                counters[kind] = ordinal
                return effect_id

    async def _rebuild(program: dict) -> dict:
        program_id = program.get("program_id")
        if (not isinstance(program_id, str)
                or re.fullmatch(r"[0-9a-f]{64}", program_id) is None):
            return {
                "ok": False,
                "refused": True,
                "error": "missing_program_identity",
            }
        if open_model_profile is not None:
            preflight = _preflight_open_model(
                program,
                open_model_profile,
                require_exact_identity=True,
            )
            if not preflight.ready:
                return {
                    "ok": False,
                    "refused": True,
                    "error": "open_model_preflight",
                    "preflight": preflight.to_dict(),
                }
            expected_identities = preflight.exact_identity_proofs()
        else:
            expected_identities = None
        # Single rebuild policy point: bulk + per_op + disallow_wall_joins
        # (see compiler.compile_rebuild_chunk for the one statement of WHY).
        # The source catalog (`ground_snapshot`) is the same thing the dry
        # gate feeds on: without it, grounding cannot resolve selectors by
        # name, and a live run would refuse with the same KIR-G103 the dry
        # run showed.
        out = compile_rebuild_chunk(
            program, revit_version=revit_version, stamp_scope=stamp_scope,
            expected_document=document_fingerprint.compiler_guard(),
            expected_identities=expected_identities,
            open_model_profile=open_model_profile,
            snapshot=ground_snapshot)
        if not out.ok:
            return {"ok": False, "refused": True,
                    "diagnostics": [d.as_dict() for d in out.diagnostics][:4],
                    **_diagnostics_total(out.diagnostics, 4)}
        await lease.ensure_held()
        effect_id = _next_effect("rebuild")
        journal.start_effect(effect_id, {
            "kind": "rebuild", "program_id": program_id,
        })
        exec_res = await _run_declarative(
            llm_client, bridge_callback, out.csharp, "idempotence_rebuild",
            _WRITE_TIMEOUT_MS)
        created_ids = collect_created_ids([
            exec_res if isinstance(exec_res, dict) else {}])
        exec_err = _extract_error(exec_res)
        if exec_err is not None:
            # The bridge may report timeout_unconfirmed after Revit committed.
            # Do not close the write-ahead effect without a commit witness;
            # restart must reconcile its exact stamp prefix first.
            detail = None
            if isinstance(exec_res, dict):
                detail = (exec_res.get("message")
                          or exec_res.get("error")
                          or None)
            bridge_detail = (str(detail)[:4000] if detail
                             else str(exec_err)[:300])
            # A DEFINITE refusal is a KNOWN outcome, not an unknown one, but
            # it is proved only by a separate typed field
            # `commit_status=RolledBack`. The error text, the generic
            # `error:true`, and the absence of created ids are not evidence of
            # the transaction: the exception could have arisen after commit,
            # and the witness could have been lost. Without a typed rollback
            # the effect stays pending and is checked against the stamp prefix
            # before a retry.
            # 🔴 A SPELLING WAS CHECKED THAT THE BRIDGE DOES NOT PRODUCE
            # (24.08.2026). This used to say
            # `str(exec_err.get("error")) != "timeout_unconfirmed"`.
            # Measured on envelopes assembled by LIVE bridge constructors:
            #
            #   _unknown_operation_result -> err.code transport.execution_unknown,
            #                                state 'RunningUnknown'
            #   attach_err(..., TRANSPORT_BRIDGE_TIMEOUT) -> err.code
            #                                transport.bridge_timeout
            #
            # Both have `error: True`, so `extract_error` takes the first
            # branch and returns `True`; the string "timeout_unconfirmed" was
            # only ever born from a hand-built fixture with no `error` key.
            # That means ANY write timeout was declared a PROVEN ROLLBACK, the
            # effect was closed, and `recover_pending_effects` did not check
            # the stamp prefix — the very check the comment twenty lines above
            # declares mandatory.
            #
            # Now the unknown is asked about via a typed code
            # (`bridge_result.is_unconfirmed`), and the rollback is asked
            # about independently via `commit_status`. No substring closes
            # the effect anymore.
            decided_refusal = (
                not _is_unconfirmed_outcome(exec_res)
                and _explicit_commit_status(exec_res) == "RolledBack"
                and not created_ids)
            if decided_refusal:
                # The FAILURE receipt is not a hand-rolled dict but the same
                # CommitReceipt: the phase machine, replay, and cleanup need
                # one typed dict of outcomes, otherwise the third layer learns
                # about a new outcome last (measured: run #4 died AFTER the
                # cycle — "rebuild receipts do not cover the complete plan" —
                # because the hand-rolled record was not read as a receipt).
                refusal = CommitReceipt(
                    run_id=journal.state.run_id,
                    operation="rebuild",
                    element_ids=(),
                    bridge_error=True,
                    commit_confirmed=False,
                    commit_status="RolledBack",
                    program_id=program_id,
                )
                journal.finish_effect(effect_id, {
                    **refusal.to_dict(),
                    "outcome": "refused_without_commit",
                    "bridge_detail": bridge_detail,
                })
            envelope: dict[str, Any] = {
                "ok": False, "error": "rebuild_exec",
                "bridge_detail": bridge_detail}
            if decided_refusal:
                # ONE source of truth about the outcome, two readers. The
                # journal has already gotten `refused_without_commit`; the
                # orchestrator reads NOT the bridge's text but this same
                # field — otherwise "known refusal" and "unknown" would have
                # to be told apart by substring, and the chunk-level fail-soft
                # would silently swallow timeout_unconfirmed.
                envelope["outcome"] = "refused_without_commit"
            return envelope
        # The response proves the transaction, but exact restart also needs the
        # post-commit document revision.  If this probe is lost, leave the
        # write-ahead effect pending; recovery sweeps the run prefix and starts
        # a clean epoch instead of guessing.
        await lease.ensure_held()
        document_revision = await revision_runner()
        if not isinstance(document_revision, str) or not document_revision:
            return {
                "ok": False,
                "error": "revision_unconfirmed",
                "bridge_detail": "post-commit document revision is unavailable",
            }
        # THE LAW OF THE CENSUS — BEFORE building the receipt, not inside it.
        #
        # The contract will check the same thing (a second line of defense
        # for foreign callers), but if the trigger is left ONLY there, death
        # will arrive as an exception from the constructor: the effect will
        # not close, and a bare ContractSchemaError will escape outward, which
        # the orchestrator will wrap as "internal". Here, instead, the outcome
        # is typed, and — the main point — the write-ahead effect STAYS
        # PENDING, exactly as with `timeout_unconfirmed`: the transaction is
        # committed, but what became of the unaccounted-for ops we do not
        # know, and an unknown cannot be closed with a receipt. An unclosed
        # effect is itself the record of it: replay will run into "A5 phase
        # cannot advance with pending effects", and recovery will sweep the
        # run's prefix by stamp.
        op_refusals = collect_op_refusals(exec_res, program)
        ops_no_element = count_ops_without_element(exec_res)
        ops_total = len(program.get("ops") or ())
        accounted = len(created_ids) + len(op_refusals) + ops_no_element
        if ops_total and accounted != ops_total:
            return {
                "ok": False,
                "error": "ops_unaccounted",
                "bridge_detail": (
                    f"чанк закоммичен, но исходы не сходятся: учтено "
                    f"{accounted} из {ops_total} опов (создано "
                    f"{len(created_ids)}, отказало {len(op_refusals)}, без "
                    f"элемента {ops_no_element}) — есть опы без исхода"),
                "ops_total": ops_total,
                "ops_unaccounted": ops_total - accounted,
            }
        receipt = CommitReceipt(
            run_id=journal.state.run_id,
            operation="rebuild",
            element_ids=tuple(created_ids),
            bridge_error=False,
            commit_confirmed=True,
            commit_status="Committed",
            program_id=program_id,
            document_revision=document_revision,
            op_refusals=op_refusals,
            ops_total=ops_total,
            ops_no_element=ops_no_element,
        )
        try:
            journal.finish_effect(effect_id, receipt.to_dict())
        except Exception as exc:  # noqa: BLE001 — unknown durability is failure
            return {
                "ok": False, "error": "journal_write_failed",
                "bridge_detail": repr(exc)[:300], "result": _a5_payload(exec_res),
            }
        if not isinstance(exec_res, dict):
            return {"ok": False}
        # Failures ride outward TOGETHER with the chunk's success: the
        # orchestrator needs them for the report, and pulling them again from
        # the journal would mean reading what is already in hand. The key is
        # added on top of the original envelope, overwriting nothing — ids
        # are still assembled from `result`.
        return {**exec_res, "op_refusals": list(op_refusals)}

    async def _read(code: str) -> Any:
        await lease.ensure_held()
        return await _run_declarative(
            llm_client, bridge_callback,
            _bind_read_to_document(code, document_fingerprint),
            "idempotence_read",
            _SNAPSHOT_TIMEOUT_MS)

    async def _delete(program: dict) -> dict:
        # Same single policy point (de-join is a no-op for delete programs;
        # bulk + per_op best-effort cleanup are what matter here).
        out = compile_rebuild_chunk(
            program, revit_version=revit_version,
            expected_document=document_fingerprint.compiler_guard())
        if not out.ok:
            return {"ok": False, "refused": True,
                    "diagnostics": [d.as_dict() for d in out.diagnostics][:4],
                    **_diagnostics_total(out.diagnostics, 4)}
        await lease.ensure_held()
        effect_id = _next_effect("delete")
        journal.start_effect(effect_id, {
            "kind": "delete", "operation_count": len(program.get("ops", [])),
        })
        exec_res = await _run_declarative(
            llm_client, bridge_callback, out.csharp, "idempotence_delete",
            _WRITE_TIMEOUT_MS)
        deleted_ids = sorted(_deleted_id_witnesses(
            exec_res if isinstance(exec_res, dict) else {}))
        del_err = _extract_error(exec_res)
        if del_err is not None:
            # As with rebuild, an error envelope is not proof of rollback.
            # Leave the delete effect pending for idempotent prefix recovery.
            return {"ok": False, "error": "delete_exec",
                    "bridge_detail": str(del_err)[:300]}
        receipt = CommitReceipt(
            run_id=journal.state.run_id,
            operation="delete",
            element_ids=tuple(deleted_ids),
            bridge_error=False,
            commit_confirmed=True,
            commit_status="Committed",
        )
        try:
            journal.finish_effect(effect_id, receipt.to_dict())
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False, "error": "journal_write_failed",
                "bridge_detail": repr(exc)[:300], "result": _a5_payload(exec_res),
            }
        return exec_res if isinstance(exec_res, dict) else {
            "ok": False, "error": "delete_exec"}

    async def _preview() -> dict:
        await lease.ensure_held()
        return await _run_declarative(
            llm_client, bridge_callback,
            _orphan_sweep_cs(
                stamp_prefix, delete=False,
                document_fingerprint=document_fingerprint),
            "idempotence_sweep_preview", _SNAPSHOT_TIMEOUT_MS)

    async def _sweep() -> dict:
        await lease.ensure_held()
        effect_id = _next_effect("sweep")
        journal.start_effect(effect_id, {
            "kind": "stamp_sweep", "stamp_prefix": stamp_prefix,
        })
        sweep_res = await _run_declarative(
            llm_client, bridge_callback,
            _orphan_sweep_cs(
                stamp_prefix, delete=True,
                document_fingerprint=document_fingerprint),
            "idempotence_sweep", _WRITE_TIMEOUT_MS)
        sweep_err = _extract_error(sweep_res)
        if sweep_err is not None:
            return {"ok": False, "error": "sweep_exec"}
        try:
            payload = _a5_sweep_payload(
                sweep_res, stamp_prefix=stamp_prefix)
            receipt = _cleanup_receipt_from_sweep(
                payload, run_id=journal.state.run_id,
                stamp_prefix=stamp_prefix)
            journal.finish_effect(effect_id, receipt.to_dict())
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "journal_write_failed",
                    "bridge_detail": repr(exc)[:300],
                    "result": _a5_payload(sweep_res)}
        return {
            "ok": receipt.confirmed,
            "result": payload,
            "cleanup_receipt": receipt.to_dict(),
            **({} if receipt.confirmed else {"error": "sweep_unconfirmed"}),
        }

    return _rebuild, _read, _delete, _preview, _sweep
