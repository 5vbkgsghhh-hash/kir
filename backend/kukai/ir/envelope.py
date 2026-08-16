"""The structured execution/error envelope — KUKAI's one machine-readable
contract for "what just happened" in a tool result.

Today every consequence the model perceives is prose: bridge errors arrive in
at least four different shapes that all reduce to ``{error: True, message:
"<string>"}``, and the loop's own error detection is a substring scan. The
model cannot tell *retryable* (bridge disconnected) from *fatal*
(security-blocked) without parsing Russian/English sentences, and the harness
silently rewrites the model's code before/during execution without ever
telling it what actually ran.

This module introduces one envelope, applied **additively** (no existing key is
ever removed or renamed), that gives the model:

  * ``err``       — a machine-readable :class:`ErrCode` with ``retryable`` /
                    ``transient`` flags (and ``cs_codes`` when extractable);
  * ``execution`` — the ``final_code`` that actually ran plus its repair trail,
                    attached by the repair loop only when the code was modified;
  * ``budget``    — the turn's round accounting, appended by the tool loop.

The closed taxonomy below is now a **contract**. A later C# bridge release will
emit ``err.code`` natively from the plugin; until then
:func:`classify_bridge_error` is the best-effort fallback for legacy prose.
Keep it even after the bridge adopts codes — old plugin versions still send
prose.

Everything here is pure and synchronous; it never imports the bridge, the LLM
client, or FastAPI, so it is safe to use from any producer site and trivially
unit-testable offline.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


class ErrCode(str, Enum):
    """Closed v1 taxonomy of execution/error outcomes.

    A ``str`` enum so members serialize as their dotted string value
    (``"compile.cs_error"``) straight through ``json.dumps`` — the wire form the
    model reads. Group prefixes (``transport`` / ``compile`` / ``security`` /
    ``runtime`` / ``tool`` / ``internal``) are stable; downstream code may match
    on the prefix.
    """

    # transport — the path to/from Revit, not the code itself
    TRANSPORT_BRIDGE_DISCONNECTED = "transport.bridge_disconnected"
    TRANSPORT_BRIDGE_TIMEOUT = "transport.bridge_timeout"
    # Revit's single-threaded ExternalEvent is busy with a prior op OR stuck Pending —
    # the code is fine; the path to Revit is occupied. "Failed to raise ExternalEvent".
    TRANSPORT_BRIDGE_BUSY = "transport.bridge_busy"
    TRANSPORT_TOOL_BUDGET_EXCEEDED = "transport.tool_budget_exceeded"
    # The client accepted or may have started a side effect, but its terminal
    # receipt has not arrived. Retrying the write would be unsafe.
    TRANSPORT_EXECUTION_UNKNOWN = "transport.execution_unknown"

    # compile — the code did not become a runnable assembly
    COMPILE_CS_ERROR = "compile.cs_error"
    # Our OWN server-side declarative template failed to compile. Distinct
    # from COMPILE_CS_ERROR on purpose: that one is the model's code and is
    # rightly retryable, this one is ours and the model cannot influence it.
    INTERNAL_TEMPLATE_FAILED = "internal.template_failed"
    COMPILE_FAILED_AFTER_REPAIRS = "compile.failed_after_repairs"

    # security — the code was refused on policy grounds
    SECURITY_BLOCKED_PATTERN = "security.blocked_pattern"

    # runtime — the code compiled and ran but Revit raised
    RUNTIME_REVIT_EXCEPTION = "runtime.revit_exception"
    # The process cannot run our code AT ALL — an assembly version collision in
    # Revit's shared AppDomain, where every add-in loads together. Deliberately
    # NOT a member of the compile.* or runtime.* families: nothing compiled and
    # nothing ran, so both of those names would send the model looking for a
    # mistake of its own that does not exist. Observed live on the operator's
    # Revit 2026, 2026-08-12.
    ENVIRONMENT_ASSEMBLY_CONFLICT = "environment.assembly_conflict"
    # Ход сняли — оператором, сервером или пользователем — ДО того, как Revit
    # начал исполнение. Не исключение Revit и не вина кода: 7 свежих случаев за
    # 30 дней помечались `runtime.revit_exception`, чья подсказка утверждает
    # «код скомпилировался и выполнился», хотя сообщение прямо гласит
    # «cancelled before Revit started it».
    TRANSPORT_CANCELLED = "transport.cancelled"

    # tool — the call itself was malformed
    TOOL_INVALID_ARGS = "tool.invalid_args"

    # internal — an unhandled harness fault
    INTERNAL_UNHANDLED = "internal.unhandled"

    # kir — the typed compiler/runtime refusals of the IR path. Deliberately a
    # group of their own rather than a reuse of ``runtime.revit_exception``:
    # a KIR refusal is STRUCTURAL (it names the op, the violated postcondition,
    # the unmet precondition), so a consumer can act on it without parsing
    # prose — which is the whole claim the IR path makes over raw C#. Folding
    # them into the C# codes would erase exactly that difference.
    KIR_PROGRAM_REFUSED = "kir.program_refused"
    KIR_PRECONDITION_UNMET = "kir.precondition_unmet"
    KIR_RUNTIME_REFUSED = "kir.runtime_refused"
    KIR_POSTCONDITION_VIOLATED = "kir.postcondition_violated"
    KIR_UNCONFIRMED = "kir.unconfirmed"


# (retryable, transient) for each code.
#   retryable  — could another attempt plausibly help? (repair / resend / wait)
#   transient  — is this a flaky-infra case (vs. a deterministic code/policy
#                fault)? transient implies the SAME code may work on retry; a
#                retryable-but-not-transient case needs the code/approach changed
#                first (e.g. a repairable compile error).
ERR_PROPS: dict[ErrCode, tuple[bool, bool]] = {
    ErrCode.TRANSPORT_BRIDGE_DISCONNECTED: (True, True),
    ErrCode.TRANSPORT_BRIDGE_TIMEOUT: (True, True),
    # bridge busy/stuck: the SAME code will run once Revit frees the ExternalEvent
    # (transient) — so wait+resend, NEVER repair the code (it isn't the fault).
    ErrCode.TRANSPORT_BRIDGE_BUSY: (True, True),
    # budget exceeded: NOT retryable THIS turn (the loop is out of rounds /
    # the tool was cut off); the C# may even still be running.
    ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED: (False, False),
    ErrCode.TRANSPORT_EXECUTION_UNKNOWN: (False, True),
    # a CS error is fixable via repair, but the SAME code won't suddenly
    # compile — so retryable, not transient.
    ErrCode.COMPILE_CS_ERROR: (True, False),
    # A broken server template is not repairable by the model and not a flake:
    # marking it retryable is what produced 93 identical compiles in twenty
    # minutes on 2026-07-30.
    ErrCode.INTERNAL_TEMPLATE_FAILED: (False, False),
    # exhausted the repair budget: change approach, don't resend.
    ErrCode.COMPILE_FAILED_AFTER_REPAIRS: (False, False),
    ErrCode.SECURITY_BLOCKED_PATTERN: (False, False),
    # a Revit runtime exception MAY be retryable (transaction race, transient
    # model state) but is never an infra flake.
    ErrCode.RUNTIME_REVIT_EXCEPTION: (True, False),
    # malformed args: retryable once the args are corrected.
    ErrCode.TOOL_INVALID_ARGS: (True, False),
    ErrCode.INTERNAL_UNHANDLED: (False, False),
    # KIR refusals are deterministic: the SAME program refused for the SAME
    # reason will refuse again, so none of them is transient. They are
    # retryable in the sense that matters — the model can fix the PROGRAM and
    # send a different one, which is precisely what a structural refusal buys.
    ErrCode.KIR_PROGRAM_REFUSED: (True, False),
    ErrCode.KIR_PRECONDITION_UNMET: (True, False),
    ErrCode.KIR_RUNTIME_REFUSED: (True, False),
    ErrCode.KIR_POSTCONDITION_VIOLATED: (True, False),
    # unconfirmed: the write may have committed. Re-sending it risks a
    # duplicate build — read the model back first, never resend blindly.
    ErrCode.KIR_UNCONFIRMED: (False, True),
    # Not retryable: the offending assembly is already loaded and no number of
    # attempts can unload it. Not unconfirmed: execution never began, so no
    # write can be half-committed.
    ErrCode.ENVIRONMENT_ASSEMBLY_CONFLICT: (False, False),
    # Не retryable: причина отмены снаружи хода, повтор её не отменит.
    # Не unconfirmed: сказано «до того как Revit начал», значит не выполнялось.
    ErrCode.TRANSPORT_CANCELLED: (False, False),
}


_CS_CODE_RE = re.compile(r"CS\d{4}")

# The single definition of "this is a compile error". It used to exist TWICE,
# with different contents: `repair_knowledge._is_compilation_error` included
# "does not contain a definition" and "not found in type"; `classify_bridge_error`
# did not. So on one of the two pipeline paths those messages were stamped
# `runtime.revit_exception`, whose guidance says the code «скомпилировался и
# выполнился, но Revit бросил исключение» — false on both counts, and it sends
# the model hunting a modelling mistake instead of fixing the name it misspelled.
#
# Measured 2026-08-12 against 30 days of fleet messages: 10 occurrences across
# 8 distinct sessions. Small, but every one of them was a user being told a
# confident wrong story. The other pipeline path (revit_execution_pipeline:1453)
# already classified them as compile errors, so unifying here removes a
# disagreement rather than introducing a behaviour.
_COMPILE_KEYWORDS = (
    "compilation failed",
    "compile",
    "cs0",  # C# error codes like CS0103, CS0246
    "cs1",
    "syntax error",
    "not found in type",
    "does not contain a definition",
)


def extract_cs_codes(message: str) -> list[str]:
    """Return the C# compiler codes (``CS####``) found in ``message``,
    de-duplicated and in first-seen order.

    Used to surface the structured codes the bridge flattened into prose so the
    model (and telemetry) can match on them without re-parsing sentences.
    """
    if not message:
        return []
    seen: dict[str, None] = {}
    for m in _CS_CODE_RE.findall(message):
        seen.setdefault(m, None)
    return list(seen.keys())


# ── environment failures: real, and not the model's fault ────────────────────
#
# Revit loads every add-in into ONE AppDomain. Roslyn 4.9.2 wants a particular
# System.Collections.Immutable; whoever loaded a different one first wins for
# everybody, and our compiler then dies in its static constructor. On the
# operator's Revit 2026 (2026-08-12) this killed every code execution.
#
# The Bridge reports it as a CompilationException, which ChatWindow.cs formats
# as "Compilation failed: …" — so the substring match in `_is_compilation_error`
# fired, the repair loop ran, and the model rewrote perfectly good code against
# a wall it cannot move. That is the 93-compile storm of 2026-07-30 in a new
# costume.
#
# The patterns below are kept NARROW on purpose. A false positive here tells the
# model "your code is fine" when it is not, which buries a real bug — strictly
# worse than the failure being fixed. So: only the explicit marker our own 1.4.7
# client emits, and the two .NET texts actually observed. No general
# "could not load file or assembly", because user code can provoke that too.


# .NET notices a version mismatch at different moments and reports each moment
# through a different exception. Covering one surface and not the others is how
# the first version of this detector passed every test it had and still missed
# the failure that was live on the operator's machine while it was written
# (2026-08-12, 10:02:52): a mismatched Roslyn that LOADED fine and only failed
# later, at the member level — "does not have an implementation".
_BINDING_FAILURE_SHAPES = (
    # ── английские ──────────────────────────────────────────────────────────
    "type initializer for",              # static ctor threw — the 2025/2026 classic
    "could not load file or assembly",   # never resolved
    "could not load type",               # resolved, type absent
    "does not have an implementation",   # resolved, member absent (MissingMethodException)
    "method not found",
    "missingmethodexception",
    "typeloadexception",
    "fileloadexception",
    # ── русские ─────────────────────────────────────────────────────────────
    # .NET локализует сообщения исключений по языку СИСТЕМЫ, а система у наших
    # пользователей русская — рынок именно такой. Замер по 1199 трейсам (12.08,
    # уже ПОСЛЕ выкладки первой версии этого детектора): русских «Метод не
    # найден» — 9, английских «Method not found» — 0. Живой формой была русская,
    # а знали мы только английскую: восемь свежих случаев за 30 дней помечались
    # `runtime.revit_exception` с `retryable: true`, то есть агенту предлагалось
    # повторять то, что измениться не может. Третий за сутки случай прибора,
    # покрывающего часть диапазона.
    "инициализатор типа",
    "не удалось загрузить файл или сборку",
    "не удается загрузить тип",
    "не удалось загрузить тип",
    "метод не найден",
)

# Our compiler's own dependency closure. This half is what keeps the predicate
# honest: an ordinary fault in user code can produce any shape above, and calling
# THAT an environment defect would tell the model its code is fine when it is not
# — burying a real bug, which is strictly worse than the failure being fixed.
_OUR_CLOSURE = (
    "microsoft.codeanalysis",
    "system.collections.immutable",
    "system.reflection.metadata",
    # Зависимость самого моста, а не компилятора — но класс отказа тот же:
    # общий AppDomain, чужая версия победила, наш код не запускался. Держать для
    # этого второй детектор значило бы дважды описывать один дефект.
    # Живьём: 8 случаев за 30 дней, «Метод не найден: System.Text.Json…».
    "system.text.json",
)


def is_environment_failure(message: str) -> bool:
    """True when the process could not run our code at all, for a reason no
    change to that code can affect.

    A PRODUCT of two conditions, never either alone: a .NET binding-failure
    shape AND one of the assemblies in our own Roslyn closure. Our 1.4.7+ client
    also emits an explicit marker, which needs no second half because we wrote it
    ourselves and it means exactly this.

    Shared by the classifier and by the repair gate so the two cannot drift: a
    message classified as an environment defect must also be one that repair
    declines, or the model gets a correct label and a pointless retry loop.
    """
    if not message:
        return False
    low = message.lower()
    if "internal.roslyn_init" in low:            # our own marker, 1.4.7+
        return True
    return any(sh in low for sh in _BINDING_FAILURE_SHAPES) and any(
        asm in low for asm in _OUR_CLOSURE
    )


# «ИСХОД НЕИЗВЕСТЕН» — САМОЕ ДОРОГОЕ, ЧТО МОЖЕТ СКАЗАТЬ КЛИЕНТ, И ДО 16.08.2026
# ЭТО СЛОВО ТЕРЯЛОСЬ ЦЕЛИКОМ.
#
# Клиент отвечает такой прозой ровно тогда, когда Ревит уже поработал, а
# долговечная квитанция об этом НЕ ЛЕГЛА НА ДИСК (`ChatWindow.cs:1767`, `:1805`,
# `:824`, `:974`). Слой операций читает это правильно: `_bridge_callback`
# при `receipt is None` и `error is True` ставит `RUNNING_UNKNOWN`, не шлёт ACK
# и прямо запрещает слепой повтор (`api/bridge_protocol.py:886-905`).
#
# 🔴 А конверт в тот же миг говорил модели ДРУГОЕ. Замер 16.08.2026 на этой
# ветке, прод-venv: все четыре сообщения падали в `runtime.revit_exception`,
# у которого `ERR_PROPS` даёт `retryable=True`. То есть на живом случае
# 14.08 (трижды «Недостаточно места на диске», клиент записал FATAL себе)
# модель получала ровно два неверных совета сразу: «ошибка в твоём C#» —
# и «повтори». Повтор здесь строит ВТОРОЙ экземпляр уже построенного;
# `TRANSPORT_EXECUTION_UNKNOWN` заведён с текстом «операция в Revit могла
# продолжиться и завершиться» именно про это.
#
# Это именной дефект проекта в чистом виде: величина УТВЕРЖДАЕТСЯ в одном
# месте (слой операций: повтор запрещён) и ЧИТАЕТСЯ в другом (конверт:
# retryable), и совпасть их не заставляло ничто.
#
# ПОЧЕМУ МАРКЕР ИМЕННО «durable receipt», А НЕ ПЕРЕЧЕНЬ ФРАЗ. Соседняя строка
# `ChatWindow.cs:785` — «Durable operation journal is unavailable; execution was
# **not started**» — описывает ОБРАТНЫЙ случай: эффекта не было, повторять
# безопасно. Она отличается словом `journal` против `receipt`, и это
# различение проверяется контролем, а не соблюдается на память
# (`tests/test_unknown_outcome_is_not_retryable.py` читает НАСТОЯЩИЙ `.cs`).
_UNKNOWN_OUTCOME_RE = re.compile(
    r"durable receipt|outcome is unknown", re.IGNORECASE)


def _outcome_is_unknown(message: str) -> bool:
    """Сказал ли клиент «эффект мог случиться, а улики о нём нет»."""

    return bool(_UNKNOWN_OUTCOME_RE.search(message))


def classify_bridge_error(message: str) -> ErrCode:
    """Best-effort classification of legacy bridge prose into an :class:`ErrCode`.

    A fallback until the C# bridge emits codes natively. Heuristics (checked in
    priority order):

      * "durable receipt" / "outcome is unknown"       → ``transport.execution_unknown``
      * any ``CS####`` present                         → ``compile.cs_error``
      * "compilation failed" / "compile" / "syntax"    → ``compile.cs_error``
      * "not connected" / "disconnected"               → ``transport.bridge_disconnected``
      * "timed out" / "timeout" / "не ответил вовремя"  → ``transport.bridge_timeout``
      * otherwise                                      → ``runtime.revit_exception``
    """
    if not message:
        return ErrCode.RUNTIME_REVIT_EXCEPTION
    # BEFORE the compile heuristic: the Bridge wraps this failure in
    # "Compilation failed: …", so the compile branch would otherwise claim it
    # and mark it retryable.
    if is_environment_failure(message):
        return ErrCode.ENVIRONMENT_ASSEMBLY_CONFLICT
    if _outcome_is_unknown(message):
        return ErrCode.TRANSPORT_EXECUTION_UNKNOWN
    low = message.lower()
    if _CS_CODE_RE.search(message) or any(kw in low for kw in _COMPILE_KEYWORDS):
        return ErrCode.COMPILE_CS_ERROR
    if "not connected" in low or "disconnected" in low or "не подключ" in low:
        return ErrCode.TRANSPORT_BRIDGE_DISCONNECTED
    if (
        "timed out" in low
        or "timeout" in low
        or "timed-out" in low
        or "не ответил вовремя" in low
    ):
        return ErrCode.TRANSPORT_BRIDGE_TIMEOUT
    # Revit's ExternalEvent is busy/stuck — NOT a code fault. "Failed to raise
    # ExternalEvent: Pending". Must not be treated as a runtime code error (which
    # would send the model off repairing perfectly-good code).
    if "externalevent" in low or "failed to raise" in low:
        return ErrCode.TRANSPORT_BRIDGE_BUSY
    return ErrCode.RUNTIME_REVIT_EXCEPTION


# «Отменено ДО того, как Revit начал» — сообщение само сообщает, что ничего не
# выполнялось. Отдельно от общей отмены: важна именно граница «не начиналось».
_CANCELLED_RE = re.compile(
    r"cancelled before revit started|отменено до начала|cancelled by operator")


def classify_execution_error(result: Any) -> "ErrCode":
    """Which of the three things went wrong when generated code was executed.

    The execute path had this as an inline binary — compile or runtime — copied
    at three sites. A binary cannot express the case where the process could not
    run our code AT ALL, so an environment conflict fell through to
    ``runtime.revit_exception`` and the model was told its code had run.

    Order matters: the Bridge wraps the environment failure in
    "Compilation failed: …", so the environment test has to come first or the
    compile branch claims it.
    """
    msg = str(result.get("message", "")).lower() if isinstance(result, dict) else ""
    if is_environment_failure(msg):
        return ErrCode.ENVIRONMENT_ASSEMBLY_CONFLICT
    if _CANCELLED_RE.search(msg):
        return ErrCode.TRANSPORT_CANCELLED
    if any(kw in msg for kw in _COMPILE_KEYWORDS):
        return ErrCode.COMPILE_CS_ERROR
    return ErrCode.RUNTIME_REVIT_EXCEPTION


def friendly_bridge_message(code: "ErrCode", raw: str) -> str:
    """User-facing text for a bridge error the model should relay as-is. Bridge-busy is
    the confusing one: the code is fine, Revit is just occupied or stuck — so tell the
    user what to actually DO instead of leaking the raw "Failed to raise ExternalEvent"."""
    if code == ErrCode.TRANSPORT_BRIDGE_BUSY:
        return ("Revit сейчас занят другой операцией или подвис (это НЕ ошибка кода). "
                "Подожди пару секунд и повтори; если не отвечает — перезапусти Revit.")
    return raw


def result_is_error(result: Any) -> bool:
    """Did this tool result report a FAILURE? The one predicate the turn loop
    and the audit fold should share.

    Both production sites grew the same two legacy rules independently
    (``kukai/llm/client.py:1569``, ``kukai/api/chat_ws.py:2007``) and both
    reduce to ``result.get("error") is True`` — a *boolean* flag. That misses
    every typed refusal KUKAI actually emits today:

      * ``{"ok": false, "error": "ops_unaccounted"}``   — ``error`` is a STRING,
        and ``"x" is True`` is False, so a real refusal read as success;
      * ``{"ok": false, "diagnostics": [...]}``          — the KIR envelope has
        no ``error`` key at all.

    Measured on the tower run (29.07): a refused KIR write was folded into the
    turn as ``ok: true``. Silent success is the one outcome this codebase
    refuses to ship, so the predicate is widened here, once, additively.

    Deliberately NOT a rule: "an ``err`` block is present". The tool-budget
    timeout attaches ``err`` while keeping ``error: False`` on purpose
    (``client.py:1506`` — "Non-blocking (error: False stays)") because the C#
    may still be running and must not be re-sent. It carries no ``ok`` key, so
    it stays non-blocking here too. Pure; never raises.
    """
    if not isinstance(result, dict):
        return False
    err = result.get("error")
    if err is True:
        return True
    if isinstance(err, str) and err.strip():
        return True
    if result.get("ok") is False:
        return True
    if result.get("refused") is True:
        return True
    return False


# What the model should DO about each code — the remedy, not the diagnosis.
#
# This text existed since plan 004 in `tool_contracts.EXECUTE_REVIT_CODE_ERR_GUIDANCE`
# and was measured on 2026-08-12 to have ZERO importers: written, never
# delivered, so the model had never seen one of these sentences. It lives here
# now, beside ERR_PROPS, for the same reason `retryable` does — it is a property
# OF THE CODE, and putting it in the funnel is what stops a producer forgetting
# it.
#
# The rule these follow: name the ROUTE, not the refusal. A dead end ("limit
# exhausted") leaves the user with nothing; what a stuck turn needs is the next
# thing to try.
ERR_GUIDANCE: dict["ErrCode", str] = {
    # 10 случаев в корпусе (7 за 30 дней), и все — НАШИ падения Python,
    # уезжавшие агенту дословно: «'str' object has no attribute 'get'»,
    # «'NoneType' object has no attribute 'get'». Из такого сообщения нельзя
    # понять, что править, и модель повторяла один и тот же вызов до четырёх
    # раз. Сказать правду («это наша поломка») дешевле, чем позволить ей
    # искать несуществующую ошибку у себя.
    # Самый опасный код из всех: он означает «мы НЕ ЗНАЕМ, прошла запись или
    # нет». Слепой повтор здесь строит второй экземпляр того же. В корпусе 38
    # сообщений прямо предупреждают «операция в Revit могла продолжиться и
    # завершиться» — это не фигура речи, а состояние модели пользователя.
    ErrCode.TRANSPORT_EXECUTION_UNKNOWN: (
        "Связь оборвалась, и подтверждения не пришло: операция в Revit МОГЛА "
        "выполниться и записаться. НЕ ПОВТОРЯЙ вслепую — повтор построит "
        "дубликат. Сначала ПРОЧИТАЙ модель (query_model / inspect) и проверь, "
        "появилось ли то, что ты создавал. Если появилось — просто сообщи "
        "результат; если нет — тогда повтори."
    ),
    ErrCode.INTERNAL_UNHANDLED: (
        "Это сбой НА СЕРВЕРЕ КУКИ, а не ошибка твоего запроса — сообщение выше "
        "техническое и адресовано разработчикам. Повторять тот же вызов "
        "бессмысленно. Зайди иначе: тот же результат другим инструментом или "
        "меньшими шагами; если обойти нельзя — скажи пользователю, что это "
        "внутренняя ошибка сервиса, и предложи, что можно сделать вместо."
    ),
    ErrCode.TRANSPORT_CANCELLED: (
        "Ход был остановлен ДО того, как Revit начал выполнение — оператором, "
        "сервером или самим пользователем. Твой код не выполнялся, модель не "
        "менялась, ошибки в коде нет. Не повторяй молча: коротко скажи "
        "пользователю, что операция была прервана, и спроси, повторить ли её."
    ),
    # Russian, unlike its neighbours, because this one is meant to be relayed to
    # the user almost verbatim: it asks THEM to do something (restart Revit),
    # which no rewrite by the model can substitute for.
    ErrCode.ENVIRONMENT_ASSEMBLY_CONFLICT: (
        "Твой код НЕ выполнялся и даже не компилировался: в этом процессе Revit "
        "конфликт версий сборок между плагинами, компилятор не смог "
        "инициализироваться. Это дефект среды, а не твоего кода. "
        "НЕ переписывай код — результат будет тот же. "
        "Что делать: (1) скажи пользователю перезапустить Revit — порядок "
        "загрузки плагинов может смениться, и конфликта не будет; "
        "(2) передай пользователю строку «Загружено сейчас: …» — по ней видно, "
        "чья версия победила; (3) пока код недоступен, ЧИТАТЬ модель всё ещё "
        "можно — inspect и остальные инструменты чтения работают, они не "
        "компилируют C#. Сделай через них всё, что можно сделать без кода."
    ),
    ErrCode.COMPILE_CS_ERROR: (
        "Your C# did not compile. The system will attempt automatic repair; if "
        "you receive this code back, fix the named CS#### error — do not resend "
        "the identical code."
    ),
    ErrCode.COMPILE_FAILED_AFTER_REPAIRS: (
        "Compilation failed even after the system's repair attempts. Do NOT "
        "resend — change your approach (different API / different strategy)."
    ),
    ErrCode.SECURITY_BLOCKED_PATTERN: (
        "The code was refused by the security policy. NEVER retry it. Explain to "
        "the user what was blocked and propose a safe alternative."
    ),
    ErrCode.RUNTIME_REVIT_EXCEPTION: (
        "The code compiled and ran but Revit raised an exception. Read the "
        "message; a corrected approach may work."
    ),
    ErrCode.TRANSPORT_BRIDGE_DISCONNECTED: (
        "Transient infrastructure issue (Revit bridge not connected). The same "
        "code may succeed once the connection is restored — do not rewrite it."
    ),
    ErrCode.TRANSPORT_BRIDGE_TIMEOUT: (
        "Transient timeout. The same code may succeed on retry; do not resend "
        "identical code in a tight loop — let the system retry."
    ),
    ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED: (
        "The tool exceeded its time budget. Completion is UNCONFIRMED — the "
        "operation in Revit may still be running or may already have committed. "
        "Do NOT assume it was aborted and do NOT blindly re-issue a write; first "
        "VERIFY the model state, then proceed."
    ),
    ErrCode.INTERNAL_TEMPLATE_FAILED: (
        "This is OUR server-side template, not your code — repeating the call "
        "cannot help and the repair loop has nothing to fix. Use the general "
        "path instead: execute_revit_code (or query_model for a read) answers "
        "the same question. Also tell the user to report it to the operator."
    ),
}


def attach_err(
    result: dict[str, Any],
    code: ErrCode,
    *,
    cs_codes: list[str] | None = None,
    detail: Any = None,
) -> dict[str, Any]:
    """Add the machine-readable ``err`` block to an existing result dict and
    return the SAME dict (mutated in place).

    **Strictly additive — the whole safety contract of the envelope.** This
    NEVER removes or rewrites an existing key: ``error`` (bool *or* string),
    ``message``, ``code`` (the legacy numeric JSON-RPC code), ``success``,
    ``violations`` etc. all survive untouched. It only writes the new ``err``
    key (overwriting a prior ``err`` only if a producer re-classifies, which is
    intentional).

    ``retryable`` / ``transient`` are derived from :data:`ERR_PROPS`. ``cs_codes``
    and ``detail`` are included only when provided (no noisy nulls beyond the
    documented schema slot).
    """
    retryable, transient = ERR_PROPS[code]
    err: dict[str, Any] = {
        "code": code.value,
        "retryable": retryable,
        "transient": transient,
    }
    hint = ERR_GUIDANCE.get(code)
    if hint:
        err["hint"] = hint
    if cs_codes:
        err["cs_codes"] = cs_codes
    if detail is not None:
        err["detail"] = detail
    result["err"] = err
    return result
