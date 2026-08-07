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
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from kukai.ir.a5_recovery import (
    A5Journal,
    A5JournalError,
    A5Lease,
    A5LeaseError,
    A5Phase,
    stamp_scope as _a5_stamp_scope,
)
from kukai.llm.envelope import ErrCode, attach_err
from kukai.ir.contracts import (CommitReceipt, DocumentFingerprint,
                                RevisionProof, RunId)
from kukai.ir.bridge_result import extract_error as _extract_error
from kukai.ir.acceptance_journal import AcceptanceJournalError
from kukai.ir.acceptance_runtime import (
    AcceptanceRuntimeError,
    AcceptanceSession,
    prepare_acceptance,
)
from kukai.ir.open_model import (
    GROUND_SNAPSHOT_CS as _OPEN_MODEL_SNAPSHOT_CS,
    OpenModelProfile,
    OpenModelProfileError,
    open_model_preflight_enabled as _open_model_preflight_enabled,
    preflight_programs as _preflight_open_model,
)
from kukai.ir.diag import W_POSTCONDITIONS_COMMITTED
from kukai.ir.outcome import (
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

# ─── §18.5, нейтральность поставки: список допуска принадлежит УСТАНОВКЕ ─────
#
# Живой обратный путь (revit_ir / revit_decompile / revit_rebuild / A5) стоит на
# двух условиях: флаг стадии И устройство из операторского списка. Раньше вторым
# условием был литерал ниже — id машины автора кода, из-за которого у стороннего
# разработчика обратный путь неисполним НАВСЕГДА, а отказ не подсказывал, что
# настраивать.
#
# Носитель ограничения сменился, смысл — нет: список задаёт оператор установки
# через KUKAI_ADMIN_DEVICES (через запятую). Переменная задана и пуста ⇒ живой
# путь выключен целиком (это законный способ поставить компилятор без живого
# Revit вообще).
_ADMIN_DEVICES_ENV = "KUKAI_ADMIN_DEVICES"
# ПРИГОВОР: фолбэк умирает при опенсорс-срезе; §18.5: пусто = живой путь
# выключен. Он существует ровно потому, что прод-.env этой установки трогать
# нельзя, а поведение прода обязано сохраниться байт-в-байт: переменная не
# задана ⇒ работает историческое устройство этой машины и ничьё больше.
_MIGRATION_ADMIN_DEVICE = "a6d7d14340bc599817ae7e6896182ca0"
# Совместимость: kukai/llm/client.py логирует ожидаемое устройство при закрытом
# гейте. Имя оставлено, чтобы его импорт не сломал панель инструментов; новый
# код обязан спрашивать admin_devices()/is_admin_device().
ADMIN_DEVICE = _MIGRATION_ADMIN_DEVICE
_FLAG = "KUKAI_KIR_TOOL"
_QUERY_TIMEOUT_MS = 30_000
_WRITE_TIMEOUT_MS = 120_000
_SNAPSHOT_TIMEOUT_MS = 30_000


def _turn_device_id() -> Optional[str]:
    try:
        from kukai.llm import turn_context
        getter = getattr(turn_context, "get_active_device_id", None)
        if callable(getter):
            return getter()
        return turn_context._active_device_id.get()
    except Exception:  # noqa: BLE001 — fail-CLOSED for exposure
        return None


def admin_devices() -> tuple[str, ...]:
    """Список допущенных устройств этой УСТАНОВКИ (§18.5).

    Источник — env ``KUKAI_ADMIN_DEVICES`` (через запятую). Переменная НЕ
    задана ⇒ миграционный дефолт (историческое устройство этой машины: см.
    приговор у ``_MIGRATION_ADMIN_DEVICE``). Переменная задана и пуста ⇒
    пустой список, то есть живой путь выключен.
    """
    raw = os.environ.get(_ADMIN_DEVICES_ENV)
    if raw is None:
        return (_MIGRATION_ADMIN_DEVICE,)
    return tuple(
        item.strip() for item in raw.split(",") if item.strip())


def is_admin_device(device_id: Optional[str]) -> bool:
    """Входит ли устройство хода в список допуска. Сомнение ⇒ нет."""
    if not device_id:
        return False
    return device_id in admin_devices()


def admin_gate_message_ru(instrument: str) -> str:
    """Отказ гейта, который НАЗЫВАЕТ, что настраивать (§18.5, B2 аудита)."""
    if not admin_devices():
        return (f"{instrument} недоступен: список допущенных устройств пуст — "
                f"задай {_ADMIN_DEVICES_ENV} (id устройств через запятую)")
    return (f"{instrument} недоступен на этом устройстве — добавь его id в "
            f"{_ADMIN_DEVICES_ENV}")


def revit_ir_enabled() -> bool:
    """Stage-2 gate: flag AND admin device. Any doubt -> tool absent."""
    if os.environ.get(_FLAG, "off") != "stage2":
        return False
    return is_admin_device(_turn_device_id())


def inject_revit_ir_schema(tools: list) -> None:
    """Append the tool def (idempotent). Schema generated from the registry."""
    if any(t.get("function", {}).get("name") == "revit_ir" for t in tools):
        return
    from kukai.ir.schema_gen import program_schema
    from kukai.ir.tool_doc import build_tool_description, program_py_schema
    tools.append({
        "type": "function",
        "function": {
            "name": "revit_ir",
            # GENERATED — see kukai/ir/tool_doc.py. The op inventory is built
            # from spec.OPS because the hand-written string it replaces named
            # 7 of the 28 writing ops: a model reading it could not know KIR
            # authors beams, ducts, cable trays, groups, family types or
            # annotations at all. Prose has no ratchet, so the inventory must
            # not be prose. The measured authoring idioms (seven building tasks
            # given to the model) and the live-matrix traps live there too,
            # each with its provenance; test_tool_doc pins both.
            "description": build_tool_description(),
            "parameters": {
                "type": "object",
                # ДВЕ ФОРМЫ ВХОДА, РОВНО ОДНА ЗА РАЗ.
                #
                # ПОЧЕМУ НЕ `oneOf`/`required` НА ВЕРХНЕМ УРОВНЕ. «Ровно одно
                # из двух» выражается в JSON Schema только `oneOf`, и это
                # была бы правда — но `oneOf` В КОРНЕ `parameters` ни один
                # инструмент этой установки ещё не возил, а поставщик,
                # отвергший пачку инструментов целиком, ломает ХОД, а не одну
                # способность. Цена ошибки несимметрична: непринятая схема —
                # мёртвый ход у админского устройства, отсутствующий
                # `required` — один типизированный отказ, который УЧИТ
                # (`_authored_input` ниже). Поэтому правило названо словами, а
                # держится рантаймом.
                "description": (
                    "Программа задаётся РОВНО ОДНИМ из двух полей: `program` "
                    "(операции JSON) либо `program_py` (питон, который их "
                    "порождает). Оба сразу или ни одного — типизированный "
                    "отказ."),
                "properties": {
                    "program": program_schema(),
                    "program_py": program_py_schema(),
                },
            },
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
    from kukai.ir.emit_utils import cs_string_literal

    names = _snapshot_parameter_names(program)
    if not names:
        return _SNAPSHOT_CS
    literals = ", ".join(cs_string_literal(name) for name in names)
    return _SNAPSHOT_CS.replace(
        "var __ParamNames = new string[0];",
        f"var __ParamNames = new string[] {{ {literals} }};",
        1)


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
        from kukai.ir.compiler import plan_program
        from kukai.ir.midend import ProgramFamily
        return plan_program(program, bulk=bulk).family is ProgramFamily.WRITE
    except Exception:  # noqa: BLE001
        # The real compile call below owns the typed refusal.  Returning false
        # here prevents any write attempt for an unclassifiable program.
        return False


async def _run_declarative(llm_client, bridge_callback, code: str, op: str,
                           timeout_ms: int) -> Any:
    from kukai.llm.revit_execution_pipeline import RevitExecutionPipeline
    pipe = RevitExecutionPipeline.from_llm_client(llm_client, bridge_callback)
    record = await pipe.run_declarative(
        code, tool="revit_ir", op=op, args={}, timeout_ms=timeout_ms)
    return record.to_tool_result()


# ── v1.1: runtime-outcome translation (SACTOR, SPEC 12.7) ────────────────────
# The slab saga (FULL_BUILDING_TEST.md, находка №1): a Revit runtime refusal
# came back as {"ok": true, "result": {"error": true}} — the outer ok lied.
# Contract now: EXACTLY one typed outcome. Any error signal in the exec
# result -> ok:false + KIR-X* diagnostic bound to op_id where known; the raw
# Revit message survives only inside `detail`, never as the only signal.

_X_PATTERNS = (
    ("KIR-X001", ("curve length is too small", "shortcurvetolerance")),
    ("KIR-X002", ("loops intersect", "curve loops")),
    ("KIR-X006", ("already in use", "уже используется")),
    ("KIR-X005", ("transaction", "транзакци")),
)


def _translate_runtime(err: dict) -> dict:
    layer = err["layer"]
    raw = str(layer.get("message") or layer.get("message_ru") or err["error"])[:300]
    op_id = layer.get("op_id")
    marker = str(err["error"]).lower()
    if marker == "postconditions_violated":
        code, msg = "KIR-X004", "постусловия нарушены — транзакция откатена, модель не изменена"
    elif marker == "stale_or_failed":
        # `__Refuse` помечает ОДНИМ маркером всякий типизированный отказ
        # эмиттера, а не только провалившийся null-guard по grounded-id.
        # Утверждать «элемент исчез» на «NewFamilyInstance вернул null» или
        # «NewElbowFitting: failed to insert elbow» — ложь: ничего не исчезало,
        # а пользователя отправляли искать дрейф модели (обе строки пойманы
        # живьём 27.07). Настоящий случай узнаётся по подписи, которую пишут
        # сами null-guard'ы; всё остальное честно называется рантайм-отказом,
        # а причина уже лежит в `detail`.
        code = "KIR-X003"
        drift = "после grounding" in raw
        msg = ("элемент/тип исчез между grounding и исполнением — откат"
               if drift else
               "оп отказан в рантайме Revit — причина в detail; транзакция откатена")
    elif marker == "timeout_unconfirmed":
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
    return d


def _postcondition_violations(payload: Any) -> list[str]:
    """Нарушения, записанные режимом ``postconditions="report"``.

    В этом режиме программа КОММИТИТ, сложив нарушения в
    ``__results["postcondition_violations"]`` (authoring.py).  До арх-разбора
    2026-07-25 (§3.6) этот ключ не читал никто — нарушенное постусловие
    спокойно уживалось с вердиктом «успех».
    """
    if not isinstance(payload, dict):
        return []
    raw = payload.get("postcondition_violations")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]


def _witness_for_success(family: str, payload: Any) -> dict:
    """Свидетельство для закоммиченной программы — с учётом нарушений.

    Успех транзакции (``ok=True``) — факт: запись состоялась.  Но если
    постусловия нарушены и лишь «зарепорчены», тройка осей обязана это
    показать, иначе потребитель прочитает результат как чистый.
    """
    if family == "query":
        return {"read_only": True}
    vio = _postcondition_violations(payload)
    if not vio:
        return {"geometry_ok": True, "semantic_ok": True, "topology_ok": True}
    return {
        "geometry_ok": not any("(geometry)" in item for item in vio),
        "topology_ok": not any("(topology)" in item for item in vio),
        "semantic_ok": not any(
            "(geometry)" not in item and "(topology)" not in item
            for item in vio),
        "committed": True,
        "violations": vio[:10],
    }


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
        v = " ".join(diag.get("violations", []))
        vio = diag.get("violations", [])
        w["geometry_ok"] = not any("(geometry)" in x for x in vio)
        w["topology_ok"] = not any("(topology)" in x for x in vio)
        w["semantic_ok"] = not any(
            "(geometry)" not in x and "(topology)" not in x for x in vio)
    else:
        w["geometry_ok"] = w["semantic_ok"] = w["topology_ok"] = None
    return w


def _expected_results(planned: Any) -> list[tuple[str, Any]]:
    """Result identities declared by the exact plan lowered to C#."""
    from kukai.ir.midend import PlannedProgram
    if not isinstance(planned, PlannedProgram):
        return []
    return [(op.op_id, op.result) for op in planned.ops]


def _result_contract_diagnostic(exec_res: Any, family: str,
                                planned: Any) -> Optional[dict]:
    """Reject missing/incomplete execution evidence instead of blessing it.

    Every emitted query returns a dictionary keyed by normalized op id. Every
    emitted write additionally returns ``ok: true`` only after the transaction
    committed.  A bridge payload that does not carry those keys is an unknown
    execution outcome, never a successful witness.
    """
    if not isinstance(exec_res, dict):
        detail = f"bridge payload type={type(exec_res).__name__}"
        payload = None
    else:
        payload = exec_res.get("result", exec_res)
        detail = "result payload is not an object"
    if not isinstance(payload, dict):
        return {"code": "KIR-X008",
                "message_ru": "результат исполнения не подтверждён — проверь модель query-запросом",
                "detail": detail}
    if family == "write" and payload.get("ok") is not True:
        return {"code": "KIR-X008",
                "message_ru": "commit не подтверждён результатом исполнения — проверь модель query-запросом",
                "detail": "write result lacks exact ok=true"}
    expected = _expected_results(planned)
    missing = [oid for oid, _result_spec in expected
               if oid not in payload or not isinstance(payload.get(oid), dict)]
    if missing:
        return {"code": "KIR-X008",
                "message_ru": "readback исполнения неполон — проверь модель query-запросом",
                "detail": "missing/non-object result keys: " + ", ".join(missing[:10])}
    if family == "write":
        unidentified = [
            oid for oid, result_spec in expected
            if not result_spec.identity_present(payload[oid])
        ]
        if unidentified:
            return {"code": "KIR-X008",
                    "message_ru": "readback исполнения не содержит идентичности элементов — проверь модель query-запросом",
                    "detail": "result keys without typed identity: " +
                              ", ".join(unidentified[:10])}
    return None


def _with_outcome(result: dict, outcome: ProgramOutcome) -> dict:
    """Attach the closed outcome without flattening its independent axes."""

    result["outcome"] = outcome.to_dict()
    return result


def _typed_error(stage: str, message: str, *,
                 outcome: ProgramOutcome | None = None) -> dict:
    result = {"ok": False, "error": stage, "message_ru": message,
              "handoff": "recipe-path"}
    _with_outcome(result, outcome or program_not_started())
    return _stamp_refusal(result)


# ── отказ обязан НЕСТИ причину машиночитаемо ─────────────────────────────────
# Живой замер башни (29.07) на KIR-плече: `err_code: null`. Причина у нас была
# и доезжала до МОДЕЛИ (диагностика KIR-* лежит в конверте дословно), но не до
# СИСТЕМЫ: блок `err` — единственный контракт «что случилось»
# (kukai/llm/envelope.py) — на пути KIR не ставился НИКОГДА. Поэтому оценщик
# (will/evaluator.py:144), квитанция (bridge_protocol.py:1138) и детектор
# ошибки хода (client.py:1569) читали пустоту, а провалившаяся запись
# сворачивалась в ход как успех.
#
# Ставим ОДИН раз на выходе (см. `handle_revit_ir`), а не по месту каждого
# `return`: правило структурное, поэтому новый путь отказа получает `err`
# даром и не может «забыть» его.

# Тонкозернистый KIR-код → группа закрытой таксономии.
_KIR_X_TO_ERRCODE = {
    "KIR-X004": ErrCode.KIR_POSTCONDITION_VIOLATED,
    "KIR-X007": ErrCode.KIR_UNCONFIRMED,
}
_KIR_W_TO_ERRCODE = {
    W_POSTCONDITIONS_COMMITTED: ErrCode.KIR_POSTCONDITION_VIOLATED,
}
_KIR_A_TO_ERRCODE = {
    # Pre-effect independent-read/durability prerequisites.
    "KIR-A001": ErrCode.KIR_PRECONDITION_UNMET,
    "KIR-A002": ErrCode.KIR_PRECONDITION_UNMET,
    "KIR-A005": ErrCode.KIR_PRECONDITION_UNMET,
    "KIR-A009": ErrCode.KIR_PRECONDITION_UNMET,
    # The write is already committed; retrying would duplicate effects.
    "KIR-A003": ErrCode.KIR_UNCONFIRMED,
    "KIR-A004": ErrCode.KIR_UNCONFIRMED,
    "KIR-A006": ErrCode.KIR_RUNTIME_REFUSED,
    "KIR-A007": ErrCode.KIR_UNCONFIRMED,
    "KIR-A008": ErrCode.KIR_UNCONFIRMED,
}

# ПЕСОЧНИЦА ИСХОДНОГО ЯЗЫКА (`KIR-B*`, kukai/ir/sandbox.py).
#
# ОТВЕТ НА «RETRYABLE?» — И ОН НЕ ПО АНАЛОГИИ, А ПО ДВУМ ФАКТАМ.
#
# ФАКТ ПЕРВЫЙ, РЕШАЮЩИЙ: НИЧЕГО НЕ ПРОИЗОШЛО. Песочница стоит ДО компилятора,
# ДО моста и ДО любой транзакции; её единственный выход — список операций, и
# при отказе его нет. Значит запрет на повтор здесь нечего защищать: `retryable
# = false` в этой системе означает ровно одно — «эффект мог случиться, повтор
# задвоит» (`kir.unconfirmed`, `transport.execution_unknown`). Скрипт, упавший
# на синтаксисе, не создал ни одного элемента, и следующий ход обязан быть.
#
# ФАКТ ВТОРОЙ: ОТКАЗ ДЕТЕРМИНИРОВАН. Тот же исходник даст ту же ошибку —
# на этом и стоит `author_digest`. Поэтому `transient=false` у всех: ждать и
# слать то же самое бессмысленно, чинить надо ИСХОДНИК. Это в точности
# семантика `kir.program_refused` (retryable=True, transient=False), а не
# `transport.*`: код отказа называет строку скрипта, то есть адрес правки.
#
# ЕДИНСТВЕННОЕ ИСКЛЮЧЕНИЕ — `KIR-B012`, и оно противоположно по причине.
# Это НАШ дефект (`blame="sandbox"`): не создалось пространство имён, не
# загрузился язык, ребёнок не отдал результата. Модель чинить тут нечего, и
# сказать ей «retryable» значило бы отправить её переписывать исправный
# скрипт. `internal.unhandled` (False, False) говорит правду: повторять
# бессмысленно. Что делать — сказано текстом отказа: ту же программу можно
# прислать полем `ops`, путь исполнения от этого не меняется.
#
# B002/B003/B011 (стена/память/смерть процесса) взвешены отдельно и НАМЕРЕННО
# оставлены не-transient: они выглядят «плавающими», но их причина — цикл без
# выхода или накопление в памяти, то есть свойство скрипта. Объявить их
# transient значит посоветовать модели прислать тот же вечный цикл ещё раз.
_KIR_B_TO_ERRCODE = {
    "KIR-B001": ErrCode.KIR_PROGRAM_REFUSED,   # синтаксис
    "KIR-B002": ErrCode.KIR_PROGRAM_REFUSED,   # не завершился
    "KIR-B003": ErrCode.KIR_PROGRAM_REFUSED,   # память
    "KIR-B004": ErrCode.KIR_PROGRAM_REFUSED,   # импорт вне белого списка
    "KIR-B005": ErrCode.KIR_PROGRAM_REFUSED,   # закрытый builtin
    "KIR-B006": ErrCode.KIR_PROGRAM_REFUSED,   # исключение скрипта
    "KIR-B007": ErrCode.KIR_PROGRAM_REFUSED,   # программы не выдал
    "KIR-B008": ErrCode.KIR_PROGRAM_REFUSED,   # выдал не-IR
    "KIR-B009": ErrCode.KIR_PROGRAM_REFUSED,   # транспортный потолок
    "KIR-B010": ErrCode.KIR_PROGRAM_REFUSED,   # недетерминизм
    "KIR-B011": ErrCode.KIR_PROGRAM_REFUSED,   # процесс умер молча
    "KIR-B012": ErrCode.INTERNAL_UNHANDLED,    # НАШ дефект, см. выше
}

# Плоская форма `{"ok": false, "error": "<строка>"}` — так отказывают
# `_typed_error` и `rebuild_runner`. Строка уже НАЗЫВАЕТ причину; таблица лишь
# сообщает читателю, что с ней делать.
_FLAT_ERROR_TO_ERRCODE = {
    # исполнение не подтверждено — повторять запись вслепую опасно
    "revision_unconfirmed": ErrCode.KIR_UNCONFIRMED,
    "sweep_unconfirmed": ErrCode.KIR_UNCONFIRMED,
    "timeout_unconfirmed": ErrCode.KIR_UNCONFIRMED,
    # мир не в том состоянии, которое программа предполагала
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
    # исполнение началось и отказало
    "rebuild_exec": ErrCode.KIR_RUNTIME_REFUSED,
    "delete_exec": ErrCode.KIR_RUNTIME_REFUSED,
    "sweep_exec": ErrCode.KIR_RUNTIME_REFUSED,
    "ops_unaccounted": ErrCode.KIR_RUNTIME_REFUSED,
    "journal_write_failed": ErrCode.KIR_RUNTIME_REFUSED,
    # ПОТЕРЯ СВЯЗИ — НЕ НАША ПОЛОМКА, и разница видна модели по флагу повтора.
    # `internal.unhandled` объявлен (retryable=False, transient=False), то есть
    # означает «повторять бессмысленно». Оборванный мост означает ровно
    # обратное. Замер 03.08.2026: 4571 обрыв (close_code=1006) за 2 ч 45 мин, и
    # на каждый из них KIR отвечал «внутренняя ошибка». См. `_transport_stage`.
    "bridge_disconnected": ErrCode.TRANSPORT_BRIDGE_DISCONNECTED,
    "bridge_timeout": ErrCode.TRANSPORT_BRIDGE_TIMEOUT,
    # ФОРМА ВЫЗОВА: `program` и `program_py` сразу, ни одного, или скрипт не
    # текстом. Программы не было вовсе — чинится правкой аргументов, повтор
    # безопасен по построению.
    "program_form": ErrCode.TOOL_INVALID_ARGS,
    "internal": ErrCode.INTERNAL_UNHANDLED,
}


#: Имена классов исключений, означающих ОБРЫВ. Опознание по имени, а не по
#: импорту, намеренно: `websockets` — сторонний пакет, и жёсткий импорт сделал
#: бы ядро KIR незапускаемым там, где его нет (открытый срез, тестовое
#: окружение). Имя класса при этом стабильнее его пути: `ConnectionClosed`
#: переезжал между модулями `websockets` минимум дважды.
_DISCONNECT_CLASS_NAMES = frozenset({
    "ConnectionClosed", "ConnectionClosedError", "ConnectionClosedOK",
    "WebSocketDisconnect", "ClientConnectionError", "ServerDisconnectedError",
})

#: Встроенные типы обрыва. `ConnectionError` — общий предок `ConnectionReset`/
#: `BrokenPipe`/`ConnectionAborted`, поэтому ловится всё семейство разом.
_DISCONNECT_TYPES: tuple[type[BaseException], ...] = (ConnectionError,)

#: Молчание вместо обрыва: мост жив, но не ответил в срок.
_TIMEOUT_TYPES: tuple[type[BaseException], ...] = (TimeoutError,)

#: Глубина обхода цепочки причин. Обрыв почти никогда не приходит голым: его
#: заворачивают в свой RuntimeError стадии конвейера. Предел нужен потому, что
#: цепочка бывает ЦИКЛИЧЕСКОЙ (повторный `raise ... from ...` в петле
#: восстановления), и обход без предела повесил бы обработчик отказа — то есть
#: сломал бы ровно тот путь, который existует, чтобы ничего не ломать.
_CAUSE_DEPTH = 8


def _transport_stage(exc: BaseException | None) -> Optional[str]:
    """Стадия плоского отказа, если исключение — ПОТЕРЯ СВЯЗИ, иначе None.

    ЗАЧЕМ ОТДЕЛЬНО ОТ `classify_bridge_error`. Тот разбирает ПРОЗУ моста и
    работает, когда мост ОТВЕТИЛ. Оборванный сокет прозы не приносит вовсе — он
    приходит исключением, минует классификатор и падает в общий
    `except Exception`, где становится «внутренней ошибкой». Поэтому здесь
    смотрят на ТИП, а не на текст.

    ГРАНИЦА УЗКАЯ, И ЭТО ПОЛОВИНА ЦЕННОСТИ ПРАВИЛА. `KeyError` или `TypeError`,
    названные транспортом, отправили бы модель повторять программу, сломанную
    детерминированно, — одна ложь заменилась бы другой. Всё, что не опознано
    уверенно, остаётся `internal`.
    """
    seen: set[int] = set()
    current = exc
    for _ in range(_CAUSE_DEPTH):
        if current is None or id(current) in seen:
            return None
        seen.add(id(current))
        # Порядок проверок значим: `asyncio.TimeoutError` в Python 3.11+ ЕСТЬ
        # `TimeoutError`, а `TimeoutError` — наследник `OSError`, но НЕ
        # `ConnectionError`, так что пересечения с обрывом нет.
        if isinstance(current, _TIMEOUT_TYPES):
            return "bridge_timeout"
        if isinstance(current, _DISCONNECT_TYPES) or (
                type(current).__name__ in _DISCONNECT_CLASS_NAMES):
            return "bridge_disconnected"
        current = current.__cause__ or current.__context__
    return None


def _failure_stage(exc: BaseException, what: str) -> tuple[str, str]:
    """(стадия, сообщение) для общего `except` — ОДНА точка на три обработчика.

    Три обработчика писали «внутренняя ошибка» независимо друг от друга, и
    поправить их порознь значило бы завести три расходящихся правила. Здесь
    решение принимается один раз; сообщение говорит пользователю, ЧТО делать,
    потому что «внутренняя ошибка» не говорит ничего.
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
    """ЧТО ИМЕННО поменять в программе — там, где отказ это знает.

    Это и есть перевес структурного отказа над текстом исключения C#: причина
    названа не прозой, а полями (`op_id`, `field_name`, `expected`, `got`,
    `suggested_replacement`), поэтому подсказка собирается детерминированно, а
    не угадывается моделью по сообщению Revit."""
    if not isinstance(diag, dict):
        return None
    if diag.get("script_line") is not None:
        # Отказ песочницы адресуется НЕ операцией, а строкой ИСХОДНИКА МОДЕЛИ:
        # операций ещё нет, а место правки уже известно точно.
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
    """(код таксономии, ведущая диагностика) для готового отказа KIR."""
    diags = res.get("diagnostics")
    lead = diags[0] if isinstance(diags, list) and diags and isinstance(diags[0], dict) else None
    kir_code = str(lead.get("code", "")) if lead else ""
    if kir_code.startswith("KIR-X"):
        # рантайм: мост исполнял программу и отказал
        return _KIR_X_TO_ERRCODE.get(kir_code, ErrCode.KIR_RUNTIME_REFUSED), lead
    if kir_code.startswith("KIR-W"):
        # Witness refusal may follow a confirmed commit; execution state is
        # carried independently in ``outcome`` and controls retry safety.
        return _KIR_W_TO_ERRCODE.get(
            kir_code, ErrCode.KIR_RUNTIME_REFUSED), lead
    if kir_code.startswith("KIR-A"):
        return _KIR_A_TO_ERRCODE.get(
            kir_code, ErrCode.KIR_RUNTIME_REFUSED), lead
    if kir_code.startswith("KIR-B"):
        # Песочница исходного языка: ничего не исполнялось (см. таблицу).
        # Умолчание — «отказ программы», а не «наш дефект»: неизвестный
        # B-код скорее новая ошибка автора, чем новая наша поломка, и
        # ошибиться в эту сторону дешевле (модель получит следующий ход).
        return _KIR_B_TO_ERRCODE.get(
            kir_code, ErrCode.KIR_PROGRAM_REFUSED), lead
    flat = res.get("error")
    if isinstance(flat, str) and flat in _FLAT_ERROR_TO_ERRCODE:
        return _FLAT_ERROR_TO_ERRCODE[flat], lead
    if lead is not None:
        # компилятор отклонил программу ДО моста — модель может её починить
        return ErrCode.KIR_PROGRAM_REFUSED, lead
    if isinstance(flat, str) and flat:
        return ErrCode.KIR_PROGRAM_REFUSED, lead
    return ErrCode.KIR_PROGRAM_REFUSED, lead


def _stamp_refusal(res: Any) -> Any:
    """Поставить блок `err` на отказ KIR. СТРОГО аддитивно и fail-open.

    Не трогает успех (`ok` не False) и не переписывает уже поставленный `err`:
    ремонт диагностики не может быть причиной падения хода."""
    try:
        if not isinstance(res, dict) or res.get("ok") is not False:
            return res
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
    except Exception:  # noqa: BLE001 — диагностика не может ломать ход
        logger.debug("KIR refusal stamping failed", exc_info=True)
    return res


def _created_count(payload: Any) -> int:
    """Сколько элементов создала программа — для строки доклада человеку.

    Считаем из квитанции исполнения, а не из программы: программа говорит, что
    ПРОСИЛИ, квитанция — что получилось. Число идёт только на экран, поэтому
    любая неясность честнее округляется в ноль («программа выполнена»), чем в
    выдуманную цифру."""
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
    """Короткая подпись «что это было» — по самой частой операции программы.
    Человеку «построено 240 элементов — стены» понятнее, чем голое число."""
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
    return {
        "code": "KIR-A007",
        "message_ru": (
            "запись закоммичена, но независимая приёмка не завершена — "
            "успех не объявлен; проверь модель"),
        "detail": f"independent acceptance is inconclusive: {reason}",
        "acceptance_reason": reason,
    }


# ═════════════════════════════════════════════════════════════════════════════
# ШЛЮЗ ИСХОДНОГО ЯЗЫКА — питон становится операциями РОВНО ЗДЕСЬ
#
# Модель пишет либо программу операциями (`program`), либо скрипт, который её
# порождает (`program_py`). Скрипт исполняется в отдельном процессе
# (`kukai/ir/sandbox.py`), НИКОГДА не касается Revit и выпускает наружу ровно
# одну вещь — список операций IR.
#
# И ДАЛЬШЕ НАЧИНАЕТСЯ ТОТ ЖЕ ПУТЬ, ЧТО У JSON: `plan_program`, заземление,
# эмиссия, свидетель в транзакции, независимая приёмка, журнал. Ниже шлюза нет
# НИ ОДНОЙ ветки «а если это был скрипт» — потому что граница безопасности и
# доказуемости проходит по IR, а не по языку, на котором IR написали. Место
# конверсии одно, и оно ЗДЕСЬ, до входа в тело: тело не должно уметь отличать.
#
# ЧТО ДОБАВЛЯЕТСЯ К ДОКАЗАТЕЛЬСТВУ. `plan_digest` подписывает программу;
# `author_digest` подписывает ИСХОДНИК, её породивший. Вместе они читаются как
# «эта программа порождена вот этим скриптом» — воспроизводимость, которой на
# пути JSON не бывает вовсе. Отсюда же `replay_check` ниже: подпись, которую
# никто не проверял, — обещание, а не доказательство.
# ═════════════════════════════════════════════════════════════════════════════

_SCRIPT_FIELD = "program_py"

#: Политика песочницы прод-пути.
#:
#: `replay_check=True` — И ЭТО ГЛАВНОЕ РЕШЕНИЕ ЗДЕСЬ. Скрипт исполняется ДВАЖДЫ
#: и дайджесты двух программ сверяются. Цена замерена: счастливый путь стоит
#: ~170 мс на 104 операции, то есть повтор добавляет к ходу ~0.2% (живая запись
#: в Revit — десятки секунд). Плата за то, что `author_digest` перестаёт быть
#: обещанием: подпись недетерминированного скрипта не удостоверяет НИЧЕГО, и
#: узнать об этом обязаны мы, а не читатель квитанции через полгода.
#: Экраны песочницы (адрес объекта в выходе, запрет random/time/os) ловят
#: только то, что оставляет след; сверка прогонок ловит всё, что меняет ВЫХОД.
_AUTHOR_SANDBOX_POLICY = None       # ленивая инициализация: см. _sandbox_policy


def _sandbox_policy():
    """Политика песочницы. Ленивая, чтобы импорт serving не тянул песочницу."""
    global _AUTHOR_SANDBOX_POLICY
    if _AUTHOR_SANDBOX_POLICY is None:
        from kukai.ir.sandbox import SandboxPolicy
        _AUTHOR_SANDBOX_POLICY = SandboxPolicy(replay_check=True)
    return _AUTHOR_SANDBOX_POLICY


@dataclass(frozen=True)
class _AuthoredInput:
    """Чем задана программа — и чем это подписано.

    ``args`` — то, что уходит в тело инструмента: всегда обычный
    ``{"program": {...}}``, независимо от того, написала его модель или питон.
    """

    args: Any
    refusal: Optional[dict] = None
    from_script: bool = False
    author_digest: str = ""
    receipt: Optional[dict] = None


def _form_refusal(message: str) -> dict:
    """Отказ ФОРМЫ ВЫЗОВА: неверна не программа, а способ её задать.

    `handoff` тут пуст намеренно. «recipe-path» означает «задача вне области
    KIR» — а здесь задача как раз внутри, и следующий ход чинится одной
    правкой аргументов. Совет уйти к другим инструментам был бы ложным."""
    return _with_outcome(
        {"ok": False, "kir": True, "refused": True, "error": "program_form",
         "message_ru": message, "handoff": None},
        program_not_started())


def _authorship_receipt(result: Any, *, source_bytes: int) -> dict:
    """Блок квитанции «эта программа порождена вот этим скриптом».

    Едет рядом с `plan_digest` и на успехе, и на отказе: подпись исходника,
    который НЕ собрался, — такое же свидетельство, как подпись собравшегося.

    `stdout` здесь не украшение. Образцы формы (`tower_numpy.py`) печатают
    ЧИСЛОМ расхождение ломаной с кривой, которую они приближают; отрезать этот
    канал значит вернуть «сказал синус, построил ломаную, промолчал» — ровно
    тот молчаливо-неверный ответ, против которого стоит весь дом."""
    isolation = dict(getattr(result, "isolation", None) or {})
    receipt = {
        "language": "python",
        "author_digest": getattr(result, "author_digest", "") or "",
        "op_count": len(getattr(result, "ops", None) or []),
        "source_bytes": source_bytes,
        "duration_ms": round(float(getattr(result, "duration_s", 0.0)) * 1000.0, 1),
        # Замер, а не намерение: что песочница СДЕЛАЛА на этом запуске.
        "isolation": {key: isolation[key]
                      for key in ("namespaces", "filesystem", "network_probe")
                      if key in isolation},
        "replay_checked": bool(isolation.get("replay_checked")),
    }
    digest = getattr(result, "program_digest", "") or ""
    if digest:
        receipt["program_digest"] = digest
    stdout = getattr(result, "stdout", "") or ""
    if stdout:
        receipt["stdout"] = stdout
    return receipt


def _script_refusal_result(refusal: Any, receipt: dict) -> dict:
    """Отказ песочницы наружу — типизированным, с НОМЕРОМ СТРОКИ МОДЕЛИ.

    Ни одного нашего кадра: чинить надо СВОЙ скрипт, и отказ обязан показывать
    место в нём. `render()` уже складывает «код: суть / строка N: текст»;
    поля дублируются машиночитаемо, потому что `err.fix` собирается из них, а
    не из прозы."""
    diagnostic: dict[str, Any] = {
        "code": refusal.code,
        "message_ru": refusal.render(),
        "kind": refusal.kind,
        # ЧЬЯ ЭТО ОШИБКА — отдельным полем, а не догадкой по коду:
        # "author" чинит модель, "sandbox" чиним мы.
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
    if refusal.blame == "sandbox":
        # НАШ ДЕФЕКТ — и модели надо сказать, что делать, потому что чинить ей
        # нечего. Песочница этой фразы произнести не может: она не знает, что
        # у инструмента есть вторая форма входа. Знает шлюз, здесь и говорит.
        message += ("\nЭто дефект песочницы, а не скрипта. Ту же программу "
                    "можно прислать полем `program` (операциями) — путь "
                    "исполнения ниже от этого не меняется.")
        diagnostic["message_ru"] = message
    return _with_outcome({
        "ok": False, "kir": True, "refused": True, "stage": "author_script",
        "diagnostics": [diagnostic],
        "message_ru": message,
        "handoff": None,
        "program_source": receipt,
    }, program_not_started())


def _stamp_authorship(result: Any, authored: _AuthoredInput) -> Any:
    """Поставить подпись исходника на КВИТАНЦИЮ. Аддитивно и fail-open.

    Одно место на все исходы, а не правка каждого `return`, — тем же приёмом,
    которым ставится блок `err`: список мест забыть можно, структурное правило
    нельзя."""
    try:
        if (not authored.from_script or not isinstance(result, dict)
                or not authored.receipt):
            return result
        result.setdefault("program_source", authored.receipt)
    except Exception:  # noqa: BLE001 — квитанция не может ломать ход
        logger.debug("KIR authorship stamping failed", exc_info=True)
    return result


def _building_watch() -> tuple[Any, int]:
    """Отметка «сколько программ у здания было ДО этого хода».

    Снимается ДО тела и сравнивается ПОСЛЕ — так вопрос «этот ход что-нибудь
    добавил зданию?» отвечается ЖУРНАЛОМ, а не флагом, который тело обязано
    было бы протащить через полтора десятка `return`. Забыть протащить флаг
    можно, разойтись с журналом — нет.
    """
    from kukai.live import journal as _live_journal
    from kukai.live import verdict as _building

    key = _live_journal.key_for(_turn_device_id())
    return key, _building.programs_seen(key)


async def _stamp_building_verdict(result: Any, watch: tuple[Any, int]) -> Any:
    """ВЕРДИКТ О ЗДАНИИ — на КВИТАНЦИЮ, одним местом на все исходы.

    ЧТО ЭТО ЧИНИТ. Пачка сессии уезжала витрине и исполнителю — человеку и
    Revit'у, — а к судье не приходила никогда: у `check_bundle` был ровно один
    прод-вызывающий, `course.design_check` внутри песочницы. Здание при этом
    строится ПО ЧАСТЯМ по закону Revit (`create_stairs` обязан быть единственным
    опом своей программы), поэтому вердикт о звене всегда говорит не о том.

    ТОЛЬКО ЕСЛИ ЖУРНАЛ ВЫРОС. Читающий ход зданию не принадлежит (замер 29.07 —
    176 чтений на 5 записей), и повторять на нём вчерашний вердикт значило бы
    учить модель на числе, которое она уже не меняет.

    В ПОТОКЕ, А НЕ В ЦИКЛЕ. `check_bundle` считает питоном под GIL (замер: ~0.4
    мс на операцию), и держать на нём цикл событий значило бы подвесить чужие
    ходы на чужом здании.

    `setdefault`, а не присваивание: если тело когда-нибудь начнёт говорить о
    здании само, оно окажется ближе к предмету и его слово будет старше.
    """
    try:
        if not isinstance(result, dict):
            return result
        from kukai.live import verdict as _building

        key, before = watch
        if _building.programs_seen(key) <= before:
            return result
        block = await asyncio.to_thread(_building.judge, key)
        if block:
            result.setdefault("building", block)
    except Exception:  # noqa: BLE001 — вердикт не может ломать ход, где Revit
        logger.debug("KIR building verdict stamping failed", exc_info=True)
    return result


async def _authored_input(args: Any) -> _AuthoredInput:
    """ЕДИНСТВЕННОЕ место, где питон становится операциями.

    Возвращает либо готовый `{"program": {...}}` для тела инструмента, либо
    типизированный отказ. Ничего не бросает: сбой песочницы — тоже результат.
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
            # НИ ОДНОЙ ФОРМЫ. Раньше такой вызов доезжал до компилятора и
            # получал «программа отклонена компилятором» — неправду: никакой
            # программы не присылали, и чинить надо ВЫЗОВ, а не программу.
            return _AuthoredInput(args=args, refusal=_form_refusal(
                "не задано ни `program`, ни `program_py`: программа — это "
                "либо операции (`program`), либо питон, который их порождает "
                "(`program_py`). Ровно одно из двух"))
        return _AuthoredInput(args=args)   # обычный путь JSON, ничего не менялось
    if program is not None:
        return _AuthoredInput(args=args, refusal=_form_refusal(
            "заданы СРАЗУ `program` и `program_py`. Форма ровно одна за вызов: "
            "либо программа операциями, либо скрипт, который их порождает — "
            "иначе непонятно, что подписывать квитанцией"))
    if not isinstance(source, str):
        return _AuthoredInput(args=args, refusal=_form_refusal(
            f"`program_py` — это ТЕКСТ скрипта на питоне, а пришло "
            f"{type(source).__name__}"))

    from kukai.ir.sandbox import execute_author_script

    # Отдельный поток: песочница синхронна (subprocess + стена), и держать на
    # ней цикл событий значило бы подвесить чужие ходы на чужом цикле.
    result = await asyncio.to_thread(
        execute_author_script, source, policy=_sandbox_policy())
    receipt = _authorship_receipt(
        result, source_bytes=len(source.encode("utf-8", "surrogatepass")))

    if not result.ok:
        return _AuthoredInput(
            args=args, from_script=True, author_digest=result.author_digest,
            receipt=receipt,
            refusal=_script_refusal_result(result.refusal, receipt))

    # Конверт, выставленный скриптом (`intent`/`defaults`/`allow_destructive`/
    # `ir_version`), доезжает ЦЕЛИКОМ: пересобирать его здесь на глазок значило
    # бы потерять то, что автор назвал явно.
    program = {**(result.envelope or {}), "ops": result.ops}
    return _AuthoredInput(
        args={"program": program}, from_script=True,
        author_digest=result.author_digest, receipt=receipt)


async def handle_revit_ir(args: Any, llm_client, bridge_callback,
                          query_id: str = "") -> dict:
    """ЧАТ-ДВЕРЬ — публичный вход инструмента. Тонкая обёртка над телом:
    ЕДИНСТВЕННОЕ место, где отказ получает машиночитаемый блок `err`.

    Обёртка, а не правка каждого `return`, потому что путей отказа здесь
    больше десятка и они растут: структурное правило нельзя забыть применить,
    список мест — можно (и именно так `err` не появился ни на одном из них).

    БЮДЖЕТ ЗДЕСЬ ВСЕГДА АВТОРСКИЙ (compiler.MAX_OPS_PER_PROGRAM = 20). У этой
    функции НЕТ параметра, которым его можно поднять, — и это не забывчивость,
    а замысел: договорённость «не передавать флаг» забывается, отсутствующий
    параметр — нет. Всё, что модель кладёт во вход, попадает в `args`; ни одно
    поле `args` здесь не читается как переключатель бюджета, поэтому «попросить
    bulk» из чата нельзя ПО ПОСТРОЕНИЮ (см. tests/test_op_budget_seam.py).

    ОГОВОРКА, КОТОРУЮ НАДО ЧИТАТЬ ВМЕСТЕ С ПРЕДЫДУЩИМ АБЗАЦЕМ: `program_py`
    поднимает ПРЕДМАКРОСНЫЙ бюджет до внутреннего — см. `authored_in_python`
    в теле, там же обоснование. Абзац выше остаётся правдой дословно: ни одно
    поле не поднимает бюджет ПЕРЕЧИСЛЕНИЯ, потому что перечисление и есть то,
    что этот бюджет меряет."""
    authored = await _authored_input(args)
    if authored.refusal is not None:
        return _stamp_refusal(_stamp_authorship(authored.refusal, authored))
    # Отметка снимается ДО тела: врезка журнала стоит внутри него, и «вырос ли
    # журнал» — единственный честный ответ на «добавил ли этот ход зданию».
    watch = _building_watch()
    return _stamp_refusal(_stamp_authorship(
        await _stamp_building_verdict(
            await _handle_revit_ir_inner(
                authored.args, llm_client, bridge_callback,
                query_id=query_id, bulk=False,
                authored_in_python=authored.from_script,
                author_digest=authored.author_digest),
            watch),
        authored))


async def handle_revit_ir_bulk(args: Any, llm_client, bridge_callback,
                               query_id: str = "") -> dict:
    """ВНУТРЕННЯЯ ДВЕРЬ — тот же прод-путь, но бюджет чанка материализатора.

    ЗАЧЕМ. Разбор образца Snowdon Towers дал 6 343 элемента и чанки по 250
    опов (`decompile.materialize`), а единственная живая дверь мерила их
    авторским бюджетом 20 — живая пересборка 30.07 стоила 318 раундов вместо
    26. Половины системы считали по разным бюджетам. Замер по сохранённому
    разбору (`snowdon_plumb_v2/tree.json`, 6 544 листа L1): chunk_target=20
    даёт 317 программ, умолчание материализатора — 26, опов в обоих 6 335.

    ПОЧЕМУ ОТДЕЛЬНАЯ ФУНКЦИЯ, А НЕ ФЛАГ У `handle_revit_ir`. Флаг у публичной
    двери — это входное поле, а входное поле рано или поздно приезжает из
    аргументов инструмента. Отдельное ИМЯ нельзя произнести случайно: чат-петля
    (`kukai/llm`) его не знает, и это проверяется тестом, а не обещанием.

    ГРАНИЦЫ. Доступна только админскому маршруту `/admin/kir/*`. Два рубежа:
    общий гейт stage-2 (флаг + админское устройство, как у чат-двери) и
    ОТДЕЛЬНАЯ проверка админского устройства здесь — она держит дверь закрытой
    даже там, где общий гейт когда-нибудь ослабят.

    ЧТО МЕНЯЕТСЯ. Только предмакросный бюджет и политика компиляции чанка
    (`compiler.compile_rebuild_chunk`: bulk + per_op + de-join — один факт,
    названный один раз). Послемакросный потолок `MAX_VALIDATED_OPS` НЕ трогается
    ничем: это предел эмиттера, а не политика."""
    if not is_admin_device(_turn_device_id()):
        # Второй рубеж. Отдельно от revit_ir_enabled(): тот читает ещё и флаг
        # инструмента, а «внутренний вход только с админского устройства» —
        # утверждение, которое не должно зависеть от значения флага.
        return _typed_error("gate", admin_gate_message_ru("revit_ir (bulk)"))
    authored = await _authored_input(args)
    if authored.refusal is not None:
        return _stamp_refusal(_stamp_authorship(authored.refusal, authored))
    return _stamp_refusal(_stamp_authorship(
        await _handle_revit_ir_inner(
            authored.args, llm_client, bridge_callback,
            query_id=query_id, bulk=True,
            authored_in_python=authored.from_script,
            author_digest=authored.author_digest),
        authored))


async def _handle_revit_ir_inner(args: Any, llm_client, bridge_callback,
                                 query_id: str = "", *,
                                 bulk: bool = False,
                                 authored_in_python: bool = False,
                                 author_digest: str = "") -> dict:
    """The tool handler. NEVER raises; every outcome is a typed dict.

    ``bulk`` is set by the CALLING DOOR, never by anything inside ``args``:
    the two doors above are the only two callers, and the chat one passes
    False literally."""
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
        from kukai.ir.compiler import compile_program, plan_program

        # ЕДИНИЦА АВТОРСТВА РЕШАЕТ, КАКОЙ БЮДЖЕТ ЕЁ МЕРЯЕТ.
        #
        # Авторский бюджет (20) меряет ПЕРЕЧИСЛЕНИЕ, написанное моделью, и
        # мал намеренно: 210 из 586 живых отказов 30.07 — именно он, и это
        # работающий сигнал «выбрана не та форма». Когда модель прислала
        # СКРИПТ, авторская вещь — двенадцать строк питона, а сто четыре
        # операции написал фронт-энд; мерить их авторским бюджетом — то же
        # самое, что мерить им чанк материализатора, а этот стык уже стоил
        # 318 раундов вместо 26 (30.07, Snowdon Towers).
        #
        # ЧТО ЭТО НЕ ОСЛАБЛЯЕТ, названо прямо:
        #   * `MAX_VALIDATED_OPS` (320, послемакросный) не трогается ничем —
        #     это предел эмиттера, а не политика;
        #   * `dsl._append` сам отказывает на 300-й операции, называя
        #     чанкование прямого хода следующей работой, — то есть потолок
        #     стоит и в языке, а не только здесь;
        #   * ПОЛИТИКА КОМПИЛЯЦИИ НЕ МЕНЯЕТСЯ: скрипт идёт `compile_program`
        #     (одна транзакция, строгие постусловия, откат целиком), а НЕ
        #     `compile_rebuild_chunk` с per-op изоляцией и `report`. Поднят
        #     ровно бюджет, и ничего кроме;
        #   * перечисление по-прежнему упирается в 20: поле `program` этой
        #     строки не видит.
        # Разрешить модели ТРИСТА операций из одного цикла — не то же самое,
        # что разрешить ей набрать их руками; макросы (`stack`/`series`) дают
        # 320 после раскрытия уже сегодня, и природа регулярности там та же.
        pre_macro_bulk = bulk or authored_in_python

        # Planning does not need a model snapshot.  Keep the accepted object so
        # family routing, open-model preflight, lowering and result validation
        # all share one semantic program. Invalid input is compiled below to
        # preserve the public typed-refusal/coverage-feed path.
        try:
            routed_plan = plan_program(program, bulk=pre_macro_bulk)
        except Exception:  # noqa: BLE001 — compile_program owns the refusal
            routed_plan = None

        # ЕДИНСТВЕННАЯ ВРЕЗКА ЖИВОГО ПЛАНА. Одна строка, один кран.
        #
        # ПОЧЕМУ ЗДЕСЬ, А НЕ У ДВЕРЕЙ. Форм входа три (чат `handle_revit_ir`,
        # админская `handle_revit_ir_bulk` и питоновская через
        # `_authored_input`), и все три сходятся ровно в этом теле. Четыре
        # крана разъехались бы за месяц — так уже было с политикой пересборки,
        # которую три вызывающих независимо забыли 21.07. Единственность
        # проверяется обходом `ast` по всему дереву, а не договорённостью
        # (`tests/test_live_plan_stream.py::test_single_publish_call_site`).
        #
        # ПОЧЕМУ ИМЕННО В ЭТОЙ ТОЧКЕ. Она ПОСЛЕ планирования (макросы
        # раскрыты, умолчания проставлены, бюджет проверен — на лист попадает
        # то, что пойдёт вниз) и ДО первого обращения к мосту. Строкой ниже
        # начинается ground-снапшот, а он требует живого Revit: врежься поток
        # туда, и в офлайн-прогоне не было бы ни одного кадра. Запись при этом
        # ещё не начиналась — журнал хранит ЗАМЫСЕЛ и помечен `planned`.
        #
        # ТОЛЬКО ПИШУЩИЕ. Журнал — исходный код ЗДАНИЯ, а запрос зданию не
        # принадлежит: 176 чтений против 5 записей за один ход (замер 29.07)
        # разнесли бы историю в мусор. Семью спрашиваем у мидэнда той же
        # функцией, что и остальной путь, — второго классификатора здесь нет.
        #
        # Поток отсюда УХОДИТ И НЕ ВОЗВРАЩАЕТСЯ: `publish` синхронный, без
        # единой точки ожидания, и его исключения не выходят наружу.
        try:
            if routed_plan is not None and _program_writes(
                    routed_plan, bulk=pre_macro_bulk):
                from kukai.live import plan_stream as _plan_stream
                _plan_stream.publish(
                    device_id=_turn_device_id(),
                    program=routed_plan,
                    author_digest=author_digest,
                    source="bulk" if bulk else "chat")
        except Exception:  # noqa: BLE001 — экран не может ломать стройку
            logger.debug("live plan publish failed (fail-open)", exc_info=True)

        try:
            revit_version = llm_client._revit_version or "2026"
        except Exception:  # noqa: BLE001
            revit_version = "2026"
        import re as _re
        m = _re.search(r"20\d\d", str(revit_version))
        revit_version = m.group(0) if m else "2026"

        snapshot = None
        open_model = None
        document_fingerprint = None
        model_preflight = None
        if _program_writes(
                routed_plan if routed_plan is not None else program,
                bulk=pre_macro_bulk):
            try:
                snap_res = await _run_declarative(
                    llm_client, bridge_callback, _snapshot_cs(program),
                    "ground_snapshot", _SNAPSHOT_TIMEOUT_MS)
                if _extract_error(snap_res) is not None:
                    return _typed_error(
                        "ground", "мост вернул ошибку при получении снапшота модели")
                cand = snap_res.get("result", snap_res) if isinstance(snap_res, dict) else None
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
                        except OpenModelProfileError:
                            logger.debug(
                                "KIR open-model profile validation failed",
                                exc_info=True)
                            return _typed_error(
                                "ground",
                                "снапшот открытой модели нарушает "
                                "типизированный контракт")
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
            except Exception:  # noqa: BLE001
                logger.debug("KIR snapshot fetch failed", exc_info=True)
                return _typed_error(
                    "ground", "снапшот модели недоступен (мост не ответил)")

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
        def _compile_for_serving(identity_proofs):
            if bulk:
                # ЕДИНСТВЕННАЯ политика компиляции чанка пересборки — не набор
                # флагов по месту. Тот же помощник, которым компилирует СУХОЙ
                # гейт (`handle_revit_rebuild`) и живой A5-раннер: bulk +
                # per_op + de-join (обоснование — в compile_rebuild_chunk).
                from kukai.ir.compiler import compile_rebuild_chunk
                return compile_rebuild_chunk(
                    compile_input,
                    revit_version=revit_version,
                    query_id=query_id,
                    snapshot=snapshot,
                    expected_document=expected_document,
                    expected_identities=identity_proofs,
                    open_model_profile=open_profile,
                )
            return compile_program(
                compile_input,
                revit_version=revit_version,
                query_id=query_id,
                snapshot=snapshot,
                # Только предмакросный бюджет. Изоляция остаётся "atomic",
                # постусловия — строгими: скрипт не покупает права на
                # частично закоммиченную программу.
                bulk=pre_macro_bulk,
                expected_document=expected_document,
                expected_identities=identity_proofs,
                open_model_profile=open_profile,
            )

        out = _compile_for_serving(expected_identities)
        if not out.ok:
            res: dict = {"ok": False, "refused": True,
                         "diagnostics": [d.as_dict() for d in out.diagnostics][:8]}
            if out.handoff:
                res["handoff"] = out.handoff["route"]
                res["message_ru"] = ("запрос вне покрытия KIR — выполни обычным "
                                     "инструментом (query_model/execute_revit_code)")
            else:
                res["message_ru"] = ("программа отклонена компилятором — исправь "
                                     "по диагностике и повтори, либо используй "
                                     "обычные инструменты")
            return _with_outcome(res, program_not_started())

        # Snapshot presence was historically used as a proxy. The typed plan
        # is now the authority: transport and result contracts must classify
        # the same program the compiler actually lowered.
        family = out.planned.family.value
        timeout = _WRITE_TIMEOUT_MS if family == "write" else _QUERY_TIMEOUT_MS

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
                acceptance_session = await prepare_acceptance(
                    out.grounded,
                    snapshot,
                    document_fingerprint,
                    _acceptance_reader,
                    revit_version=revit_version,
                    timeout_ms=_SNAPSHOT_TIMEOUT_MS,
                )
            except AcceptanceRuntimeError as exc:
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
                if (guarded_out is None or not guarded_out.ok
                        or guarded_out.planned.plan_digest
                        != out.planned.plan_digest
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
                    try:
                        acceptance_session.finalize(
                            outcome, evidence=None, detail=detail)
                        registration["journal_finalized"] = True
                        registration["journal_checksum"] = (
                            acceptance_session.journal.state.checksum)
                    except AcceptanceJournalError as journal_exc:
                        registration["journal_finalized"] = False
                        registration["journal_error"] = str(journal_exc)
                    return _with_outcome({
                        "ok": False,
                        "kir": True,
                        "refused": True,
                        "stage": "acceptance_identity_bind",
                        "diagnostics": [{
                            "code": "KIR-A009",
                            "message_ru": (
                                "точную идентичность целей не удалось "
                                "встроить в транзакцию — запись не запускалась"),
                            "detail": detail,
                        }],
                        "message_ru": (
                            "точную идентичность целей не удалось встроить "
                            "в транзакцию — запись не запускалась"),
                        "handoff": None,
                        "acceptance_registration": registration,
                    }, outcome)
                out = guarded_out

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
        if family == "write":
            write_execution_started = True
        exec_res = await _run_declarative(
            llm_client, bridge_callback, out.csharp, family, timeout)
        _dur_ms = (_time.perf_counter() - _t0) * 1000.0
        from kukai.ir import witness_feed as _wf   # волна A6: fail-open корпус
        err = _extract_error(exec_res)
        if err is not None:
            diag = _translate_runtime(err)
            # Only structured refusals emitted after an explicit RollBack()
            # prove rollback. A timeout, query error, or generic bridge/API
            # error does not; claiming `true` there turns uncertainty into a
            # false safety guarantee.
            rolled_back = (True if family == "write"
                           and diag["code"] in ("KIR-X003", "KIR-X004")
                           else None)
            if rolled_back:
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
                revit_version=revit_version,
                ok=False, witness=_derive_witness(False, family, diag),
                duration_ms=_dur_ms, diag_code=diag["code"],
                violations=diag.get("violations"),
                outcome=outcome.to_dict(),
                author_digest=author_digest,
                acceptance_evidence=acceptance_registration)
            # Доклад на экран и об ОТКАЗЕ тоже. Первая версия рапортовала
            # только об успехе — и живой ход 29.07 это сразу поймал: программа
            # упала (`state: failed`), а человек не увидел ничего, то есть
            # ровно ту тишину, от которой всё затевалось. Момент неудачи —
            # как раз тот, когда «не получилось, пробую иначе» важнее всего:
            # без него пауза на ремонт неотличима от зависания.
            try:
                from kukai.llm import turn_progress as _tp
                await _tp.report_failure(diag.get("message_ru") or diag.get("code") or "")
            except Exception:  # noqa: BLE001 — экран не может ломать ход
                logger.debug("turn progress failure report failed", exc_info=True)
            result = {"ok": False, "kir": True, "stage": "execute",
                 "diagnostics": [diag],
                 "witness": _derive_witness(False, family, diag),
                 "message_ru": diag["message_ru"],
                 "rolled_back": rolled_back,
                 "handoff": (None if diag["code"] == "KIR-X007"
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
                revit_version=revit_version,
                ok=False, witness=_derive_witness(False, family, contract_diag),
                duration_ms=_dur_ms, diag_code=contract_diag["code"],
                outcome=outcome.to_dict(),
                author_digest=author_digest,
                result_payload=(payload if commit_confirmed else None),
                acceptance_evidence=acceptance_wire)
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
        # Режим ``report`` коммитит, сложив нарушения в результат.  Читаем их:
        # молчаливый «успех» поверх нарушенного постусловия — ложь (§3.6).
        _violations = _postcondition_violations(_payload)
        _witness = _witness_for_success(family, _payload)
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
        _accepted = (
            not _violations
            and (
                family == "query"
                or (
                    acceptance_session is not None
                    and
                    _outcome.acceptance is AcceptanceState.ACCEPTED
                    and _acceptance_journal_error is None
                )
            )
        )
        _wf.record_witness(
            program=out.planned, family=family,
            revit_version=revit_version,
            ok=_accepted, witness=_witness,
            duration_ms=_dur_ms, violations=_violations or None,
            result_payload=_payload if isinstance(_payload, dict) else None,
            outcome=_outcome.to_dict(),
            author_digest=author_digest,
            acceptance_evidence=_acceptance_wire)
        # The turn's end-of-turn review reads what was actually built, so only
        # a program that reached this point — compiled, executed, witnessed —
        # is recorded. A refused or rolled-back program never happened.
        if family == "write":
            try:
                from kukai.design import review as _review
                _review.record(program)
            except Exception:  # noqa: BLE001 — a review must never break a turn
                logger.debug("review record failed", exc_info=True)
        # Живой доклад на экран. Оператор 29.07: «несколько минут с пустым
        # экраном, люди не будут понимать что происходит». Модель на каждом
        # раунде вызывает инструмент МОЛЧА (замер: 8 вызовов, 0 символов
        # текста), поэтому говорит сервер — он один знает, что программа
        # действительно исполнилась и сколько это заняло.
        try:
            from kukai.llm import turn_progress as _tp
            if family == "write" and _accepted:
                await _tp.report_write(_created_count(_payload),
                                       int(_dur_ms), _program_note(program))
            elif family == "write":
                failure = (
                    _acceptance_diagnostic(
                        _acceptance_evidence,
                        durability_error=_acceptance_journal_error,
                    )["message_ru"]
                    if _acceptance_evidence is not None else
                    "KIR не подтвердил независимую приёмку записи")
                await _tp.report_failure(failure)
            else:
                await _tp.report_read()
        except Exception:  # noqa: BLE001 — экран не может ломать ход
            logger.debug("turn progress report failed", exc_info=True)
        out_result = {"ok": _accepted, "kir": True,
                      "witness": _witness,
                      "result": exec_res,
                      "outcome": _outcome.to_dict()}
        # НАЗВАННОЕ УМОЛЧАНИЕ: выбор, сделанный компилятором за промолчавшего
        # автора, обязан быть ПРЕДЪЯВЛЕН. Выбор, которого вызывающий не видит,
        # неотличим от `.FirstOrDefault()` — а именно им плечо C# 02.08.2026
        # молча взяло 1 тип двери из 62 в живом документе. Отчёт машинный,
        # примечание человеческое; второе пусто, когда выбирать было не из чего.
        if out.grounding_report:
            from kukai.ir.ground import describe_choices_ru
            out_result["grounding_report"] = out.grounding_report
            _defaults_note = describe_choices_ru(out.grounding_report)
            if _defaults_note:
                out_result["defaults_note_ru"] = _defaults_note
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
        if (acceptance_session is not None
                and (_outcome.acceptance is not AcceptanceState.ACCEPTED
                     or _acceptance_journal_error is not None)):
            acceptance_diag = _acceptance_diagnostic(
                _acceptance_evidence,
                durability_error=_acceptance_journal_error,
            )
            diagnostics.append(acceptance_diag)
            out_result["rolled_back"] = False
            out_result["handoff"] = None
            out_result["message_ru"] = acceptance_diag["message_ru"]
        if diagnostics:
            out_result["diagnostics"] = diagnostics
        if _acceptance_wire is not None:
            out_result["acceptance"] = _acceptance_wire
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
                    acceptance_session.finalize(
                        fallback_outcome,
                        evidence=None,
                        detail={"stage": "internal_exception"},
                    )
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

_DECOMPILE_FLAG = "KUKAI_KIR_DECOMPILE"
_ATOM_ESCROW_FLAG = "KUKAI_IR_ATOM_ESCROW"
_DECOMPILE_OUT_ROOT = os.environ.get(
    "KUKAI_DECOMPILE_DATA", "backend/data/decompile")


def revit_decompile_enabled() -> bool:
    """Stage-2 gate for the decompile/rebuild instruments: flag AND admin."""
    if os.environ.get(_DECOMPILE_FLAG, "off") != "stage2":
        return False
    return is_admin_device(_turn_device_id())


def atom_escrow_enabled() -> bool:
    """Explicit default-off gate for geometry-only atom materialization."""

    return os.environ.get(_ATOM_ESCROW_FLAG, "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _load_atom_escrow_bundle(
    out_dir: str,
    leaves: Sequence[Mapping[str, Any]],
):
    """Load the exact typed Tier-G bundle and return it with its byte digest."""

    import hashlib as _hashlib
    import pathlib as _pathlib
    from kukai.ir.decompile.geom_extract import (
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
            return _typed_error("gate", admin_gate_message_ru("revit_decompile"))
        from kukai.ir.decompile import pipeline as _pipe

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
            reply = {"ok": True, "status": status, "out_dir": out_dir}
            # §18.4: неполнота чтения — не деталь внутри status.json, а первое,
            # что обязан увидеть спрашивающий «как там прогон».
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
            # Снимать можно СВЯЗЬ, а не хозяина: связанные документы уже
            # открыты в сессии, и слепок связи — отдельный, со своим
            # штампом. Имя приходит от вызывающего и едет в C# литералом.
            link_title = (args.get("link_title")
                          if isinstance(args, dict) else None)
            if link_title is not None and (
                    not isinstance(link_title, str) or not link_title.strip()):
                return _typed_error(
                    "args", "link_title должен быть непустой строкой")
            task = _asyncio.ensure_future(_pipe.run_decompile(
                executor, out_dir=out_dir, change_stamp=doc_stamp,
                link_title=link_title))
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
    """Каталог модели-источника как ground-снимок, или None.

    Заземлению нужен снимок, чтобы резолвить селекторы по имени и умолчанию.
    Живой чат берёт его с моста одним батчем; внутренние пути перестроения
    (сухой гейт rebuild, сухой гейт A5, живые бегуны A5) моста для этого не
    зовут — и без каталога компилятор отказывал целым чанкам с KIR-G103.

    Замер 28.07 на ЭОМ: с каталогом компилируются ВСЕ 543 операции, без него —
    43. То есть отказ сообщал не о программе, а о слепоте вызывающего.

    Каталог лежит рядом с разбором (`open_model.profile.json`) — его сохранил
    тот же прогон, что и L0/L1, и для A5 он ЖЕ является проверенным на
    подлинность снимком документа (`_load_a5_snapshot_manifest`). Уровни
    берём из L0: в профиле их нет, а заземление уровней требует.

    Функция живёт на уровне модуля намеренно: этот же дефект дважды заводился
    заново в двух местах, потому что знание сидело внутри одной функции.
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
        if os.path.isfile(l0_path):
            with open(l0_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    row = _json.loads(line)
                    if "document" in row:
                        snapshot.setdefault("levels", [
                            {"id": int(lv["id"]), "name": lv["name"]}
                            for lv in (row["document"].get("levels") or [])
                        ])
                        break
        return snapshot
    except Exception:  # noqa: BLE001 — гейт не смеет падать из-за каталога
        return None


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
            return _typed_error("gate", admin_gate_message_ru("revit_rebuild"))
        try:
            from kukai.ir.decompile.materialize import (  # type: ignore
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

        out_dir = _decompile_out_dir(doc_stamp)
        import json as _json
        import os as _os
        tree_path = _os.path.join(out_dir, "tree.json")
        if not _os.path.isfile(tree_path):
            return {"ok": False, "error": "no_decompile",
                    "message_ru": "нет декомпайла для этого doc_stamp — сначала запусти decompile"}
        # §18.4, закон заражения: пересборка из разбора, снятого при закрытых
        # рабочих наборах, строит ЧАСТЬ здания и об этом молчит. Гейт стоял
        # только на A5 — на инструменте, который МЕРЯЕТ; здесь инструмент,
        # который ПИШЕТ, и до этой волны он проходил такой разбор без единого
        # слова. Карваут именной и попадает в отчёт, как у A5.
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
        with open(tree_path, "r", encoding="utf-8") as handle:
            tree = _json.load(handle)

        from kukai.ir.decompile.fold import iter_l1_leaves
        leaves = list(iter_l1_leaves(tree))
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
        # New materializers retain the exact immutable plan accepted at the
        # reverse boundary.  getattr keeps older/mocked MaterializeResult
        # shapes compatible; a missing/refused plan is safely replanned by the
        # compiler and cannot bypass validation.
        materialized_plans = getattr(materialized, "plans", ()) or ()

        from kukai.ir.compiler import compile_rebuild_chunk
        try:
            revit_version = str(llm_client._revit_version or "2026")
        except Exception:  # noqa: BLE001
            revit_version = "2026"
        import re as _re
        m = _re.search(r"20\d\d", revit_version)
        revit_version = m.group(0) if m else "2026"

        # Каталог источника для СУХОГО гейта — одна общая функция, см. её
        # докстринг: без каталога гейт отказывал целым чанкам (KIR-G103).
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
            out = compile_rebuild_chunk(
                retained_plan if retained_plan is not None else program,
                revit_version=revit_version,
                snapshot=dry_snapshot,
            )
            chunk = {
                "chunk": index,
                "ok": bool(out.ok),
                "refused": not out.ok,
                "diagnostics": ([d.as_dict() for d in out.diagnostics][:4]
                                if not out.ok else []),
            }
            if out.planned is not None:
                chunk["plan_digest"] = out.planned.plan_digest
            chunks.append(chunk)
        ok_count = sum(1 for c in chunks if c["ok"])
        summary = {"ok": all(c["ok"] for c in chunks) if chunks else True,
                   "dry_run": dry_run, "chunks_total": len(chunks),
                   "chunks_ok": ok_count, "chunks": chunks[:50],
                   "materialize_mode": materialize_mode,
                   "offset_mm": (list(offset_mm)
                                 if offset_mm is not None else None)}
        materialize_stats = getattr(materialized, "stats", None)
        summary["atoms_escrowed"] = int(
            getattr(materialize_stats, "atoms_escrowed", 0) or 0)
        summary["atoms_skipped"] = int(
            getattr(materialize_stats, "atoms_skipped", 0) or 0)
        escrow_evidence = getattr(materialized, "escrowed", ()) or ()
        summary["escrow_evidence"] = [
            record.as_dict() for record in escrow_evidence[:50]
            if hasattr(record, "as_dict")
        ]
        # §18.4: производный артефакт частичного чтения несёт пометку — и
        # тогда, когда оператор явно разрешил карваут, и тогда, когда чтение
        # было полным (False, а не отсутствие ключа: «не помечено» и «не
        # измерялось» — разные вещи).
        summary["is_partial_read"] = bool(partial_read["is_partial_read"])
        summary["worksets_closed"] = partial_read["worksets_closed"]
        if partial_read["is_partial_read"]:
            summary["allow_partial"] = bool(allow_partial)
            summary["partial_read_note_ru"] = (
                "результат построен на ЧАСТИЧНОМ чтении: закрытых рабочих "
                f"наборов {partial_read['worksets_closed']}")
        if dry_run:
            summary["message_ru"] = (
                f"dry-run компайл-гейт: {ok_count}/{len(chunks)} чанков ok")
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
from kukai.ir.a5_live import (
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
    """Dashboard hook: the last A5 run's exact% and date (or None)."""
    return dict(_last_idempotence) if _last_idempotence else None


# Pure A5 scope/evidence identity is independent of tool dispatch and bridge
# transport.  Re-export the historical private names for compatibility.
from kukai.ir.a5_contract import (
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
        from kukai.ir.decompile.pipeline import _REVISION_FINGERPRINT_CS
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
    from kukai.main import get_app_state
    return get_app_state().db


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
    runs :func:`kir_idempotence.run_idempotence`.  ``dry_run`` (default True)
    compile-gates the Δ-programs offline — no writes, no title probe.  The LIVE
    path (``dry_run=False``) first probes ``doc.Title`` and fails closed via the
    orchestrator's :class:`SafetyContext` unless the title confirms a copy.
    """
    claimed_doc_stamp: Optional[str] = None
    lease: Optional[A5Lease] = None
    try:
        if not revit_decompile_enabled():
            return _typed_error("gate", admin_gate_message_ru("revit_idempotence"))
        try:
            from kir_idempotence import (  # type: ignore
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
        # §18.4: карваут частичного чтения — ЯВНОЕ заявление оператора, а не
        # умолчание. Значение попадает в отчёт (см. ниже).
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

        # Δ-смещение копии. По умолчанию — DELTA_MM (200 м), но оператор
        # ставит рядом столько, сколько ему удобно сравнивать, поэтому
        # величина параметрическая. Она ВХОДИТ в дайджест запроса: два прогона
        # с разным Δ — разные прогоны, и журнал одного не смеет продолжать
        # другой.
        from kir_idempotence import DELTA_MM as _DEFAULT_DELTA_MM
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
            from kukai.ir import spec as _spec
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
        if not _os.path.isfile(tree_path) or not _os.path.isfile(passport_path):
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
        # §18.4, закон заражения: листья, поднятые из частичного чтения,
        # описывают ЧАСТЬ модели. Сверка идемпотентности на них честной быть
        # не может: недостающее не отличить от несовпавшего, а процент выйдет
        # про диалог открытия файла, а не про компилятор.
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
        with open(tree_path, "r", encoding="utf-8") as handle:
            tree = _json.load(handle)
        from kukai.ir.decompile.fold import iter_l1_leaves
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
        # ~51k per-op writes (hours).  Датумы остаются контекстом, хосты
        # дотягиваются замыканием.  Atoms always remain in the denominator; the
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
        with open(passport_path, "r", encoding="utf-8") as handle:
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
        expected_token = os.environ.get("KUKAI_A5_CONFIRM_TOKEN") or None
        if not dry_run:
            document_fingerprint = await _probe_document_fingerprint(
                llm_client, bridge_callback)
            if document_fingerprint is not None:
                doc_title = document_fingerprint.title
        # `disposable_copy` — явное заявление оператора, что ЭТОТ документ
        # расходный. Соглашение об имени осталось первым маршрутом; заявление
        # засчитывается только вместе с точным confirm_token (см. SafetyContext).
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
        # §18.4: производный артефакт частичного чтения НЕСЁТ пометку — и она
        # стоит рядом с процентами, а не в логе. Карваут виден в отчёте как
        # осознанное решение оператора, а не как отсутствие проверки.
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
                from kukai.ir.decompile.pipeline import _atomic_write_json
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
    from kukai.ir.decompile.schema import L0Document, L0SchemaError
    import json as _json2
    import os as _os2
    path = _os2.path.join(out_dir, "L0.jsonl")
    if not _os2.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            header = _json2.loads(handle.readline())
        doc = header.get("document") if isinstance(header, dict) else None
        if not isinstance(doc, dict):
            return None
        return L0Document.from_dict({**doc, "change_stamp": doc_stamp,
                                     "elements": []})
    except (L0SchemaError, Exception):  # noqa: BLE001 — no usable header
        return None


def _partial_read_state(out_dir: str) -> dict:
    """Читалась ли модель этого разбора заведомо неполно (§18.4).

    Источник — ЗАГОЛОВОК сохранённого L0 (`L0.jsonl`, первая строка): именно
    он переживает прогон и именно из него грузятся листья. Паспорт для этого
    не годится — он описывает то, что увидели, и о невидимом молчит.

    Осознанная миграция: у разборов, сделанных ДО этой волны, полей
    worksharing/worksets_closed в заголовке нет. «Нет данных» ⇒ «не измерялось»
    ⇒ прежнее поведение (никакого отказа): ретроактивно объявлять весь архив
    частичным было бы ложью того же сорта, что и молчание о неполноте.
    """
    metadata = _metadata_from_l0_header(out_dir, "probe")
    if metadata is None:
        return {"is_partial_read": False, "worksets_closed": 0,
                "measured": False}
    return {
        "is_partial_read": bool(metadata.is_partial_read),
        "worksets_closed": int(metadata.worksets_closed),
        "measured": bool(metadata.worksharing),
    }


def _partial_l0_categories(out_dir: str) -> list[str]:
    """Validate the complete L0 stream and return its partial categories."""

    import os as _os2
    from kukai.ir.decompile.extract import L0JSONLReader
    from kukai.ir.decompile.schema import CategoryState

    path = _os2.path.join(out_dir, "L0.jsonl")
    if not _os2.path.isfile(path):
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
    from kukai.ir.decompile.schema import L0Document, L0SchemaError
    if not isinstance(passport, dict):
        return None
    meta = passport.get("l0_metadata") or passport.get("metadata")
    if not isinstance(meta, dict):
        # Some passports inline the fields at the top level.
        meta = passport
    try:
        return L0Document.from_dict({
            "doc_name": meta.get("doc_name") or passport.get("doc_name") or "doc",
            "revit_version": (meta.get("revit_version")
                              or passport.get("revit_version") or "2026"),
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
    from kukai.ir.compiler import compile_rebuild_chunk
    from kir_idempotence import collect_created_ids, _deleted_id_witnesses

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
        # Каталог источника (`ground_snapshot`) — то же, чем питается сухой
        # гейт: без него заземление не резолвит селекторы по имени, и живой
        # прогон отказал бы теми же KIR-G103, что показал сухой.
        out = compile_rebuild_chunk(
            program, revit_version=revit_version, stamp_scope=stamp_scope,
            expected_document=document_fingerprint.compiler_guard(),
            expected_identities=expected_identities,
            open_model_profile=open_model_profile,
            snapshot=ground_snapshot)
        if not out.ok:
            return {"ok": False, "refused": True,
                    "diagnostics": [d.as_dict() for d in out.diagnostics][:4]}
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
            # ОПРЕДЕЛЁННЫЙ отказ — исход ИЗВЕСТНЫЙ, а не неизвестный.
            #
            # Оговорка выше — про `timeout_unconfirmed`: ответа нет, и Revit
            # мог зафиксировать. Но когда Revit ОТВЕТИЛ («transaction commit
            # status: RolledBack») и ни одного id не создано, писать это в
            # журнал как незакрытый эффект значит лгать о неизвестности:
            # при следующем чтении журнала такая запись роняет весь разбор
            # («A5 phase cannot advance with pending effects»), то есть
            # отказ ОДНОЙ программы отравляет прогон задним числом.
            #
            # Замер 28.07 (пересборка №3): solo-программа откатилась, и
            # именно этот незакрытый эффект сделал бы невозможным мягкое
            # продолжение. Закрывается ТОЛЬКО определённый отказ без
            # созданных id; неизвестность по-прежнему остаётся висеть.
            decided_refusal = (
                str(exec_err.get("error")) != "timeout_unconfirmed"
                and not created_ids)
            if decided_refusal:
                # Квитанция ОТКАЗА — не самодельный словарь, а тот же
                # CommitReceipt: фазовой машине, replay и уборке нужен один
                # типизированный словарь исходов, иначе третий слой узнаёт о
                # новом исходе последним (замер: прогон №4 умер уже ПОСЛЕ
                # цикла — «rebuild receipts do not cover the complete plan»,
                # потому что самодельная запись не читалась как квитанция).
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
                # ОДИН источник истины об исходе, два читателя. Журнал уже
                # получил `refused_without_commit`; оркестратор читает НЕ
                # текст моста, а это же поле — иначе «известный отказ» и
                # «неизвестность» пришлось бы различать по подстроке, и
                # чанковый fail-soft молча съедал бы timeout_unconfirmed.
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
        # ЗАКОН ПЕРЕПИСИ — ДО постройки квитанции, а не внутри неё.
        #
        # Контракт проверит то же самое (второй рубеж для чужих вызывающих),
        # но если оставить срабатывание ТОЛЬКО там, смерть придёт исключением
        # из конструктора: эффект не закроется, а наружу уйдёт голый
        # ContractSchemaError, который оркестратор завернёт в «internal».
        # Здесь же исход типизирован, и — главное — write-ahead эффект
        # ОСТАЁТСЯ ВИСЕТЬ, ровно как при `timeout_unconfirmed`: транзакция
        # закоммичена, но что стало с неучтёнными опами, мы не знаем, а
        # неизвестность закрывать квитанцией нельзя. Незакрытый эффект и есть
        # запись о ней: реплей упрётся в «A5 phase cannot advance with pending
        # effects», а восстановление сметёт префикс прогона по штампу.
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
        # Отказы едут наружу ВМЕСТЕ с успехом чанка: оркестратору они нужны
        # для отчёта, и брать их повторно из журнала значило бы читать то, что
        # уже в руках. Ключ добавляется поверх исходного конверта, ничего не
        # затирая — id по-прежнему собираются из `result`.
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
                    "diagnostics": [d.as_dict() for d in out.diagnostics][:4]}
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
