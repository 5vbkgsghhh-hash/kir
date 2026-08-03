"""Tool RESPONSE contracts — the documented shape of what each tool returns to
the model (as distinct from :mod:`kukai.llm.tools`, which describes the REQUEST
schema the model calls with).

This is a minimal seed created by plan 004 (the structured execution/error
envelope). It documents ONLY the ``execute_revit_code`` response contract,
including the new envelope fields (``err``, ``execution``) that the harness now
attaches additively. The full per-tool response-contract set is a separate task
— do not assume every tool is described here.

The contract is data (a plain dict tree), not enforcement: it is the canonical
prose the system prompt / tool documentation can render so the model knows how
to ACT on ``err.code`` and ``execution.final_code``. Codes referenced here are
the canonical members of :class:`kukai.llm.envelope.ErrCode`; this module
imports them so the documentation can never drift from the taxonomy.
"""

from __future__ import annotations

from typing import Any

from kukai.llm.envelope import ErrCode

# How the model should ACT on each err.code it may receive from
# execute_revit_code. Keyed by the wire value (ErrCode.value) so it matches the
# string the model actually sees in `err.code`.
EXECUTE_REVIT_CODE_ERR_GUIDANCE: dict[str, str] = {
    ErrCode.COMPILE_CS_ERROR.value: (
        "Your C# did not compile. The system will attempt automatic repair; if "
        "you receive this code back, fix the named CS#### error — do not resend "
        "the identical code."
    ),
    ErrCode.COMPILE_FAILED_AFTER_REPAIRS.value: (
        "Compilation failed even after the system's repair attempts. Do NOT "
        "resend — change your approach (different API / different strategy)."
    ),
    ErrCode.SECURITY_BLOCKED_PATTERN.value: (
        "The code was refused by the security policy. NEVER retry it. Explain to "
        "the user what was blocked and propose a safe alternative."
    ),
    ErrCode.RUNTIME_REVIT_EXCEPTION.value: (
        "The code compiled and ran but Revit raised an exception. Read the "
        "message; a corrected approach may work."
    ),
    ErrCode.TRANSPORT_BRIDGE_DISCONNECTED.value: (
        "Transient infrastructure issue (Revit bridge not connected). The same "
        "code may succeed once the connection is restored — do not rewrite it."
    ),
    ErrCode.TRANSPORT_BRIDGE_TIMEOUT.value: (
        "Transient timeout. The same code may succeed on retry; do not resend "
        "identical code in a tight loop — let the system retry."
    ),
    ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED.value: (
        "The tool exceeded its time budget. Completion is UNCONFIRMED — the "
        "operation in Revit may still be running or may already have committed. "
        "Do NOT assume it was aborted and do NOT blindly re-issue a write; first "
        "VERIFY the model state, then proceed."
    ),
}

# The execute_revit_code RESPONSE contract (envelope-aware).
EXECUTE_REVIT_CODE_RESPONSE: dict[str, Any] = {
    "tool": "execute_revit_code",
    "description": (
        "Returns the bridge execution result. On error, `error: true` and a "
        "prose `message` are kept for backward compatibility; a machine-readable "
        "`err` block is ADDED. When the harness rewrote your code before it ran, "
        "an `execution` block reports the code that actually executed."
    ),
    "fields": {
        "error": "bool — true on failure (legacy; preserved).",
        "message": "str — human-readable detail (legacy; preserved).",
        "err": {
            "code": (
                "str — one of the ErrCode taxonomy values. Act per "
                "EXECUTE_REVIT_CODE_ERR_GUIDANCE."
            ),
            "retryable": "bool — whether another attempt could plausibly help.",
            "transient": (
                "bool — whether this is a flaky-infra case (the SAME code may "
                "work on retry). retryable-but-not-transient means change the "
                "code first."
            ),
            "cs_codes": "list[str] — C# compiler codes (CS####) when extractable.",
            "detail": "optional — structured extras when a producer supplies them.",
        },
        "execution": {
            "final_code": (
                "str — the C# that ACTUALLY ran after the system's silent "
                "repairs. Treat this, not your original, as the authoritative "
                "pattern for your next code. Present ONLY when the code was "
                "modified (to bound token cost)."
            ),
            "was_modified": "bool — true when final_code differs from your input.",
            "repairs": (
                "list[{attempt:int, fix_source:str}] — the repair trail "
                "(fix_source ∈ {deterministic, llm_repair}). Note: the chat_ws "
                "pre-flight fixer also mutates code before execution but is "
                "invisible from here — its provenance is deferred to the C# phase."
            ),
        },
        "budget": {
            "rounds_used": "int — tool rounds consumed this turn.",
            "rounds_max": "int — the round cap for this turn (self-pace against it).",
        },
    },
    "err_guidance": EXECUTE_REVIT_CODE_ERR_GUIDANCE,
}
