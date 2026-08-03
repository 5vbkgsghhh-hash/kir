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
    COMPILE_FAILED_AFTER_REPAIRS = "compile.failed_after_repairs"

    # security — the code was refused on policy grounds
    SECURITY_BLOCKED_PATTERN = "security.blocked_pattern"

    # runtime — the code compiled and ran but Revit raised
    RUNTIME_REVIT_EXCEPTION = "runtime.revit_exception"

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
}


_CS_CODE_RE = re.compile(r"CS\d{4}")


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


def classify_bridge_error(message: str) -> ErrCode:
    """Best-effort classification of legacy bridge prose into an :class:`ErrCode`.

    A fallback until the C# bridge emits codes natively. Heuristics (checked in
    priority order):

      * any ``CS####`` present                         → ``compile.cs_error``
      * "compilation failed" / "compile" / "syntax"    → ``compile.cs_error``
      * "not connected" / "disconnected"               → ``transport.bridge_disconnected``
      * "timed out" / "timeout" / "не ответил вовремя"  → ``transport.bridge_timeout``
      * otherwise                                      → ``runtime.revit_exception``
    """
    if not message:
        return ErrCode.RUNTIME_REVIT_EXCEPTION
    low = message.lower()
    if _CS_CODE_RE.search(message) or any(
        kw in low for kw in ("compilation failed", "compile", "syntax error")
    ):
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
    if cs_codes:
        err["cs_codes"] = cs_codes
    if detail is not None:
        err["detail"] = detail
    result["err"] = err
    return result
