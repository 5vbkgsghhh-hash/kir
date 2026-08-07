"""KIR diagnostics — the typed error contract (SPEC_V1 §6, §12.7).

Every stage failure is a Diagnostic, never a raw exception escaping to the
caller and never a raw Roslyn message: C# errors are translated back to the
originating IR op (SACTOR pattern) before a model or a user ever sees them.
Shape follows rustc --error-format=json: code, span (op_index/op_id), message,
optional machine-applicable suggestion.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# Code namespaces (SPEC §6): P parse, G ground/kind, T typecheck, L plan/limits,
# E emit/version, C compile-gate, X execute, W witness.
PARSE_NOT_OBJECT = "KIR-P001"        # program is not a JSON object / ops not a list
PARSE_UNKNOWN_OP = "KIR-P002"        # op name not in registry
PARSE_UNKNOWN_FIELD = "KIR-P003"     # additionalProperties violation (fail-closed)
PARSE_BAD_VERSION = "KIR-P004"       # ir_version missing/unsupported
PARSE_MISSING_FIELD = "KIR-P005"     # required param absent
PARSE_DUP_ID = "KIR-P006"            # duplicate op id inside one program
# «одно из двух» схемой JSON не выражается (oneOf ломает additionalProperties
# fail-closed), поэтому взаимное исключение параметров — отдельный типизированный
# отказ. Первый носитель: place_family, который ставится ЛИБО в точку (xyz),
# ЛИБО по кривой (p0_mm/p1_mm) — у Revit это две разные перегрузки, и угадать
# за автора нельзя.
PARSE_EXCLUSIVE_FIELDS = "KIR-P007"  # mutually exclusive params: both or neither given
GROUND_UNSUPPORTED_KIND = "KIR-G001" # KindEnum escape value / unknown kind -> recipe-path handoff
GROUND_BAD_SELECTOR = "KIR-G002"     # selector shape invalid
GROUND_MODEL_BINDING = "KIR-G107"    # exact open-model dependency proof failed
TYPE_BAD_TYPE = "KIR-T001"           # wrong JSON type for a param
TYPE_BOUNDS = "KIR-T002"             # numeric outside compiler-enforced bounds (§12.9)
TYPE_BAD_ENUM = "KIR-T003"           # value not in closed enum (non-kind enums)
PLAN_LIMIT = "KIR-L001"              # program/op budget exceeded
PLAN_SOLO_OP = "KIR-L002"            # op requires its own program (own transaction scope)
EMIT_VERSION = "KIR-E001"            # op unsupported on a requested Revit version
COMPILE_FAIL = "KIR-C001"            # compile-gate rejected emitted C# (compiler-bug territory)
TYPE_GEOM_RELATION = "KIR-T003"      # inter-contour geometry (hole vs outline, self-intersection)
# X-stage: runtime outcomes translated to typed codes (SACTOR, SPEC 12.7) —
# a raw Revit message never reaches the model untyped (v1.1, slab-saga fix).
X_SHORT_CURVE = "KIR-X001"           # ShortCurveTolerance / zero-length edge at runtime
X_LOOPS_INTERSECT = "KIR-X002"       # curve loops intersect (T003-caught; runtime backstop)
X_STALE = "KIR-X003"                 # stale_or_failed (model drifted post-ground)
X_POSTCONDITIONS = "KIR-X004"        # in-txn commit-gate rolled back on violations
X_TXN = "KIR-X005"                   # transaction failed to start/commit
X_DUPLICATE_NAME = "KIR-X006"        # name already in use (level/grid rename throw)
X_TIMEOUT = "KIR-X007"               # execution unconfirmed (timeout)
X_UNCLASSIFIED = "KIR-X999"          # typed envelope for the rest; raw kept in detail
# Witness-stage distinction: unlike X004, this state is observed AFTER a
# successful commit in report/per-op mode.  Reusing X004 would claim rollback
# and make a repair retry look safe even though the model already changed.
W_POSTCONDITIONS_COMMITTED = "KIR-W004"

# ─── B: sandBox — исполнение АВТОРСКОГО СКРИПТА (kukai/ir/sandbox.py) ────────
#
# ПОЧЕМУ НОВАЯ БУКВА, А НЕ P/T/L. Стадия предшествует разбору программы: на
# ней программы ЕЩЁ НЕТ, есть питон, который её пишет. Отказ адресован другому
# ремонту — модель чинит СВОЙ скрипт, а не операцию IR, — и указывает на
# строку исходника, а не на op_index. Смешать это с P (разбор JSON) значило бы
# послать ремонт не туда, ровно как смешение двух бюджетов в KIR-L001.
# Занятые буквы на 03.08.2026 (замер грепом по репозиторию): A C D E G L M P S
# T W X. Свободна B, и она читается: sandBox.
SANDBOX_SYNTAX = "KIR-B001"             # исходник не разобран Python
SANDBOX_TIMEOUT = "KIR-B002"            # не завершился: процессорное время/стена
SANDBOX_MEMORY = "KIR-B003"             # превышен предел памяти (RLIMIT_AS)
SANDBOX_FORBIDDEN_IMPORT = "KIR-B004"   # импорт вне белого списка
SANDBOX_FORBIDDEN_BUILTIN = "KIR-B005"  # open/eval/exec/id/... — с причиной
SANDBOX_RUNTIME = "KIR-B006"            # любое другое исключение скрипта
SANDBOX_NO_OPS = "KIR-B007"             # отработал, но программы не выдал
SANDBOX_BAD_RESULT = "KIR-B008"         # выдал не-IR / не JSON-представимое
SANDBOX_OUTPUT_LIMIT = "KIR-B009"       # транспортный потолок (НЕ бюджет автора)
SANDBOX_NONDETERMINISM = "KIR-B010"     # адрес объекта в выходе / разные прогонки
SANDBOX_CRASH = "KIR-B011"              # процесс умер, не сказав ничего
SANDBOX_UNAVAILABLE = "KIR-B012"        # НАШ дефект: изоляция/язык недоступны


@dataclass
class Diagnostic:
    code: str
    message_ru: str
    op_index: Optional[int] = None
    op_id: Optional[str] = None
    field_name: Optional[str] = None
    expected: Optional[Any] = None
    got: Optional[Any] = None
    candidates: list = field(default_factory=list)
    # rustc-style suggestion: applicability is "machine-applicable" only when the
    # fix is provably safe to auto-apply; otherwise "maybe-incorrect".
    suggested_replacement: Optional[Any] = None
    applicability: Optional[str] = None
    # Present only for an unexpected internal failure.  It is safe to expose
    # on the wire and correlates the refusal with the full server-side
    # traceback without leaking exception text or source payloads.
    incident_id: Optional[str] = None

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, [])}


class KirRefusal(Exception):
    """Internal control-flow: carries diagnostics out of a stage. Never leaks —
    compile_program() catches it and returns a refused CompileOutput."""

    def __init__(self, diags: list[Diagnostic]):
        # ТЕКСТ ИСКЛЮЧЕНИЯ НЕСЁТ ПРИЧИНУ, а не её количество.
        #
        # Замер 03.08: отказ САМОГО ЯЗЫКА (`dsl.py` поднимает `DslRefusal` —
        # наследника этого класса — на дубле id, на неадресуемой ручке, на
        # исчерпанном bulk-бюджете) уходит из песочницы через `str(exc)`, и
        # модель получала «DslRefusal: 1 diagnostic(s)»: место есть, причины
        # нет. Пересекать границу процесса умеет только текст, поэтому текст
        # обязан быть содержательным. Коды и сообщения ведущих диагностик
        # стоят здесь ровно затем; полный список остаётся в `.diagnostics` и
        # никуда не девается для тех, кто ловит исключение целиком.
        head = "; ".join(
            f"{d.code}: {d.message_ru}" if getattr(d, "message_ru", "")
            else str(getattr(d, "code", "")) for d in diags[:3])
        if len(diags) > 3:
            head += f" (и ещё {len(diags) - 3})"
        super().__init__(head or f"{len(diags)} diagnostic(s)")
        self.diagnostics = diags
