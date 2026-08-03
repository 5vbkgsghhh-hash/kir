"""RevitExecutionPipeline — single owner of the execute_revit_code chain (step 7).

Extracts the pipeline that was previously split across two files with duplicated
stages (``LLMClient._execute_tool``'s inline execute branch in
``kukai/llm/client.py`` and the prepare-half of ``chat_ws._bridge_callback`` in
``kukai/api/chat_ws.py``) into ONE owned module:

    Validate → Fix (once) → PostFlight (critic, flag-gated) → Wrap →
    CompileCheck (un-latched gate) → Obfuscate → Execute (transport) →
    Repair (≤3 attempts) → Verdict → Record

Known defects this extraction fixes (all verified against live code, see the
2026-07-02 all-fronts audit):

* **Fixer ran TWICE** (client.py Stage 0b + chat_ws Step 0, with a *different*
  revit_version source) and the repair trail only saw the client-side mutation,
  so ``execution.final_code`` could lie to the model. Here the fixer runs ONCE
  and every mutation lands in the trail.
* **Contradictory timeout ladder** — the flat 90s convergence tool cap sat
  *under* the 120/240/360s execute tiers computed three lines later, making the
  tier system dead code and turning every legitimate heavy write into
  ``running_unconfirmed``. :class:`TurnBudget` derives ONE hierarchy:
  ``turn deadline ≥ pipeline total ≥ per-attempt execute timeout``; the same
  number propagates into ``timeout_ms`` (which chat_ws' future-wait and the C#
  clamp already derive from).
* **Compile gate latched OFF forever** — ``CompileClient._available`` is a
  one-way latch restored only by a startup health call. :class:`CompileGate`
  ignores the latch: always-try with a short timeout, a small breaker
  (N consecutive failures → cooldown), and automatic re-probe after cooldown.
* **Corrupted repair feedback** — client-side (in-Revit Roslyn) errors carry
  wrapped, unshifted line numbers and obfuscated ``_0x…`` identifiers.
  :func:`normalize_error_message` de-obfuscates via the rename map (the
  obfuscator now returns it) and shifts compile-diagnostic line numbers by the
  wrapper offset on ALL paths, not just the server pre-flight.

Flag gate
---------
Everything here is behind ``KUKAI_EXEC_PIPELINE=1`` (read directly from the
environment — deliberately NOT via ``kukai.config``). Default OFF: the legacy
inline path in client.py/chat_ws.py runs byte-identically. The transport half
of ``chat_ws._bridge_callback`` recognises the ``_pipeline_prepared`` marker and
skips its duplicate prepare stages (encrypt → send → await only).

Output contract
---------------
:class:`TurnRecord` folds tool outcome, repairs, errors, timings and budget —
the row the currently-dead telemetry columns (``repair_attempts`` et al.) and
the future Evaluator consume. It is logged as one structured line
(``EXEC_PIPELINE_RECORD``), optionally appended as JSONL
(``KUKAI_EXEC_PIPELINE_RECORD_PATH``), and exposed per-turn via
:func:`last_turn_record` (ContextVar) so chat_ws can fold it into metrics
without widening any signature. ``TurnRecord.to_tool_result()`` returns the
EXACT legacy-shaped dict for the model (behaviour-preserving; the record itself
is not injected into model context).

The Verdict stage is the Evaluator socket: ``PipelineDeps.verdict_hook`` is
where ``kukai.will`` plugs in. The deterministic default only classifies the
outcome; it never blocks. NOTE: the tool loop in client.py still owns the
``shadow_evaluate`` calls (unchanged), so the pipeline does NOT call it — no
double evaluation while both live.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from kukai.llm.envelope import (
    ErrCode,
    attach_err,
    classify_bridge_error,
    extract_cs_codes,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Flag
# ─────────────────────────────────────────────────────────────────────────────

def pipeline_enabled() -> bool:
    """KUKAI_EXEC_PIPELINE=1 turns the extracted pipeline on.

    Read directly from the environment on every call (cheap; allows per-process
    A/B without importing kukai.config — that module is intentionally not
    touched by this step).
    """
    return os.environ.get("KUKAI_EXEC_PIPELINE", "0") == "1"


def recipe_capture_decision(
    expects_verdict: Optional[str], witness_enabled: bool
) -> tuple[bool, Optional[str]]:
    """Corpus-integrity gate (KUKAI_RECIPE_WITNESS) — the one policy decision.

    Returns ``(should_capture, witness_verdict_to_persist)``.

    * witness OFF → ``(True, None)``: legacy behavior — the caller already
      established the execute did not error, so capture it, and persist NO
      witness (keeps flag-off rows byte-identical to pre-gate rows).
    * witness ON → refuse a recipe whose DECLARED contract was witnessed NOT
      met (``fail``/``partial``): that is an executed-but-wrong write, exactly
      the poison the corpus/federation must not inherit. Any other verdict
      (``pass``/``unverifiable``/unknown/None = no contract to contradict) is
      captured, stamped with the witnessed verdict for downstream promotion.
    """
    if not witness_enabled:
        return True, None
    if expects_verdict in ("fail", "partial"):
        return False, expects_verdict
    return True, expects_verdict


def _expects_probe_timeout_s() -> float:
    """Per-probe wall for the expects-contract count probes (IQ N2).

    Deliberately TIGHT (default 4s each, ≤2 probes per execute turn): the
    witness must never stretch the write path — on timeout the contract
    degrades to `unverifiable` and the turn proceeds. Env-tunable
    (KUKAI_EXPECTS_PROBE_TIMEOUT_S), read at call time."""
    try:
        return float(os.environ.get("KUKAI_EXPECTS_PROBE_TIMEOUT_S", "4.0"))
    except (TypeError, ValueError):
        return 4.0


# ─────────────────────────────────────────────────────────────────────────────
# C# wrapper (single source of truth for the pipeline path)
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: chat_ws.py keeps its own literal copy for the legacy path because
# kukai/modeling/tests/bridge/test_exec_wrapper_sync.py AST-parses chat_ws
# source for the literals (drift guard). tests/test_revit_execution_pipeline.py
# carries the equivalent AST sync guard for THIS copy, so the three copies
# (chat_ws, modeling, pipeline) are pairwise-guarded. At legacy cutover the
# chat_ws literals go away and this module becomes the only owner.

WRAPPER_HEADER = (
    "using System;\n"
    "using System.Linq;\n"
    "using System.Collections.Generic;\n"
    "using System.Text;\n"
    "using System.Text.RegularExpressions;\n"
    "using Autodesk.Revit.DB;\n"
    "using Autodesk.Revit.DB.Architecture;\n"
    "using Autodesk.Revit.DB.Structure;\n"
    "using Autodesk.Revit.DB.Mechanical;\n"
    "using Autodesk.Revit.DB.Electrical;\n"
    "using Autodesk.Revit.DB.Plumbing;\n"
    "using Autodesk.Revit.UI;\n"
    "\n"
    "namespace Kukai\n"
    "{\n"
    "    public class UserCode\n"
    "    {\n"
    "        public static object Execute(Document doc, UIDocument uidoc)\n"
    "        {\n"
)
WRAPPER_FOOTER = (
    "\n"
    "        }\n"
    "    }\n"
    "}\n"
)
# Derived (never hardcoded): user code line N appears in wrapped code at
# line N + WRAPPER_LINE_OFFSET.
WRAPPER_LINE_OFFSET = WRAPPER_HEADER.count("\n")


def wrap_user_code(code: str) -> str:
    """Wrap the LLM's method body into the compilable Kukai.UserCode class.

    Byte-identical to the legacy chat_ws wrapping (12-space indent on non-empty
    lines) so compile diagnostics and the C# TemplateRenderer contract match.
    """
    indented = "\n".join(
        "            " + line if line.strip() else line
        for line in code.split("\n")
    )
    return WRAPPER_HEADER + indented + WRAPPER_FOOTER


# ─────────────────────────────────────────────────────────────────────────────
# Turn deadline plumbing (set once per turn by the tool loop)
# ─────────────────────────────────────────────────────────────────────────────

_turn_deadline: ContextVar[Optional[float]] = ContextVar(
    "_exec_pipeline_turn_deadline", default=None
)


def set_turn_deadline(deadline_monotonic: float) -> None:
    """Record the turn's absolute deadline (time.monotonic() reference).

    Called by ``_stream_chat_inner`` at loop start so every execute inside the
    turn derives its budget from the SAME wall — the top of the single timeout
    hierarchy (turn ≥ pipeline ≥ attempt ≥ bridge-wait ≥ C# clamp).
    """
    _turn_deadline.set(float(deadline_monotonic))


def turn_remaining_s() -> Optional[float]:
    """Seconds left until the turn deadline, or None when no deadline was set."""
    d = _turn_deadline.get()
    if d is None:
        return None
    return d - time.monotonic()


# ─────────────────────────────────────────────────────────────────────────────
# TurnBudget — ONE coherent timeout hierarchy
# ─────────────────────────────────────────────────────────────────────────────

# Floors/slack (seconds). _MIN_TOTAL_S keeps parity with the legacy 90s cap as
# the *minimum* a read gets; heavy writes now get their tier honoured instead
# of being strangled at 90s.
_MIN_TOTAL_S = 90.0
_MIN_FLOOR_S = 30.0
_OUTER_SLACK_S = 5.0          # outer wait_for = pipeline total + this slack
_TRANSPORT_OVERHEAD_S = 12.0  # fix+compile+encrypt+WS overhead per attempt
_MIN_DISPATCH_MS = 5_000      # don't dispatch an execute with less than this


@dataclass
class TurnBudget:
    """The single deadline hierarchy for one execute_revit_code tool call.

    ``total_s``            — hard wall for the whole pipeline run (all attempts
                             + repairs). The tool loop's outer ``wait_for`` uses
                             ``total_s + _OUTER_SLACK_S`` so the pipeline always
                             finishes (and reports honestly) BEFORE the harness
                             abandons it — the old 90s-vs-360s contradiction is
                             structurally impossible here.
    ``execute_timeout_ms`` — tier-calculated per-attempt Revit deadline (the
                             existing ``_calculate_execute_timeout`` scaffolding,
                             now actually reachable). Propagated as the request's
                             ``timeout_ms``: chat_ws waits tier+10s on the bridge
                             future, C# clamps its own cts from the same number.
    """

    total_s: float
    execute_timeout_ms: int
    compile_check_timeout_s: float = 3.0
    repair_llm_timeout_s: float = 60.0
    transport_overhead_s: float = _TRANSPORT_OVERHEAD_S
    started: float = field(default_factory=time.monotonic)

    @classmethod
    def for_execute(
        cls,
        code: str,
        estimated_elements: Optional[int] = None,
        max_timeout_ms: Optional[int] = None,
        turn_remaining: Optional[float] = None,
    ) -> "TurnBudget":
        """Derive the budget from the code's tier + the turn's remaining time.

        total = clamp(tier + repair_allowance, min=_MIN_TOTAL_S,
                      max=turn_remaining) with an absolute floor of
        _MIN_FLOOR_S so a turn-end execute still gets a fast read through.
        """
        # Reuse the existing tier estimator — same scaffolding as the legacy
        # path (lazy import: client.py is heavy and imports us lazily too).
        from kukai.llm.client import _calculate_execute_timeout

        tier_ms = _calculate_execute_timeout(
            code, estimated_elements, max_timeout_ms=max_timeout_ms
        )
        allowance = float(
            os.environ.get("KUKAI_EXEC_PIPELINE_REPAIR_ALLOWANCE_S", "90")
        )
        total = max(tier_ms / 1000.0 + allowance, _MIN_TOTAL_S)
        if turn_remaining is not None and turn_remaining > 0:
            total = min(total, turn_remaining)
        total = max(total, _MIN_FLOOR_S)
        return cls(total_s=total, execute_timeout_ms=int(tier_ms))

    def remaining_s(self) -> float:
        return self.total_s - (time.monotonic() - self.started)

    def effective_execute_timeout_ms(self) -> int:
        """Per-attempt deadline: the tier, clamped by what's left of the budget
        (minus transport overhead). Below _MIN_DISPATCH_MS → do not dispatch."""
        rem_ms = int((self.remaining_s() - self.transport_overhead_s) * 1000)
        return min(self.execute_timeout_ms, max(rem_ms, 0))

    def can_dispatch(self) -> bool:
        return self.effective_execute_timeout_ms() >= _MIN_DISPATCH_MS

    def can_llm_repair(self) -> bool:
        """Enough budget left for a repair-LLM round (call + re-dispatch)."""
        return self.remaining_s() >= (self.repair_llm_timeout_s * 0.5)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_s": round(self.total_s, 1),
            "execute_timeout_ms": self.execute_timeout_ms,
            "spent_s": round(time.monotonic() - self.started, 1),
        }


def compute_tool_budget_s(tool_args: dict[str, Any]) -> float:
    """Outer wall for the tool loop's ``wait_for`` around the pipeline.

    Derived from the SAME inputs the pipeline itself uses, plus slack — so the
    outer cap can only fire after the pipeline has already returned an honest
    result on its own. Replaces the flat 90s for execute_revit_code (flag-on
    only; flat 90s stays for every other tool and for flag-off).
    """
    code = (tool_args or {}).get("code", "") or ""
    est = (tool_args or {}).get("estimated_elements")
    try:
        from kukai.config import get_settings

        max_timeout_ms: Optional[int] = get_settings().max_execute_timeout * 1000
    except Exception:  # noqa: BLE001 — budget calc must never kill a turn
        max_timeout_ms = None
    budget = TurnBudget.for_execute(
        code, est, max_timeout_ms=max_timeout_ms, turn_remaining=turn_remaining_s()
    )
    return budget.total_s + _OUTER_SLACK_S


# ─────────────────────────────────────────────────────────────────────────────
# CompileGate — un-latched pre-flight Roslyn gate
# ─────────────────────────────────────────────────────────────────────────────

class CompileGate:
    """Fail-open pre-flight compile gate WITHOUT the one-way availability latch.

    The legacy call-site consulted ``CompileClient.available`` which any single
    exception sets False forever (health() re-runs only at process start), so
    one compile-service restart silently disabled the gate until the next
    backend restart. This gate:

    * always tries (never reads the latch),
    * bounds each check with a short timeout (default 3s — a gate slower than
      that is worse than no gate),
    * opens a small breaker after ``failure_threshold`` consecutive failures
      and re-probes automatically after ``cooldown_s``,
    * skips (returns None = fail-open, same as legacy) when ``revit_version``
      is empty — an empty version manufactures the unfixable
      ``REVIT_VERSION: Revit version '' is not available`` error that used to
      burn all 3 repair attempts.
    """

    def __init__(
        self,
        client_provider: Optional[Callable[[], Any]] = None,
        failure_threshold: int = 3,
        cooldown_s: float = 60.0,
        check_timeout_s: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client_provider = client_provider
        self._threshold = failure_threshold
        self._cooldown_s = cooldown_s
        self._check_timeout_s = check_timeout_s
        self._clock = clock
        self._consecutive_failures = 0
        self._retry_at = 0.0

    def _client(self) -> Any:
        if self._client_provider is not None:
            return self._client_provider()
        try:
            from kukai.main import get_app_state

            return get_app_state().compile_client
        except Exception:  # noqa: BLE001 — app state absent (tests, tools)
            return None

    @property
    def breaker_open(self) -> bool:
        return (
            self._consecutive_failures >= self._threshold
            and self._clock() < self._retry_at
        )

    async def check(self, wrapped_code: str, revit_version: str) -> Optional[Any]:
        """Compile-check; None means "gate unavailable → fail open" (legacy
        semantics — the code proceeds to Revit which compiles authoritatively)."""
        if not revit_version:
            return None
        if self.breaker_open:
            return None
        client = self._client()
        if client is None:
            return None
        try:
            result = await asyncio.wait_for(
                client.check(wrapped_code, revit_version),
                timeout=self._check_timeout_s,
            )
        except Exception:  # noqa: BLE001 — timeout/transport/anything → fail open
            result = None
        if result is None:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold:
                self._retry_at = self._clock() + self._cooldown_s
                logger.warning(
                    "EXEC_PIPELINE compile gate: %d consecutive failures — "
                    "skipping pre-flight for %.0fs (will re-probe)",
                    self._consecutive_failures, self._cooldown_s,
                )
        else:
            if self._consecutive_failures:
                logger.info("EXEC_PIPELINE compile gate: recovered")
            self._consecutive_failures = 0
        return result


_compile_gate: Optional[CompileGate] = None


def get_compile_gate() -> CompileGate:
    """Process-wide gate (breaker state must survive across tool calls)."""
    global _compile_gate
    if _compile_gate is None:
        _compile_gate = CompileGate()
    return _compile_gate


# ─────────────────────────────────────────────────────────────────────────────
# Error feedback normalization (de-obfuscate + de-offset on ALL paths)
# ─────────────────────────────────────────────────────────────────────────────

_CS_CODE_RE = re.compile(r"CS\d{4}")
_OBF_NAME_RE = re.compile(r"_0x[0-9a-fA-F]{4}")
_LINE_NUM_RE = re.compile(r"\bline\s+(\d+)\b")


def normalize_error_message(
    message: str,
    rename_map: Optional[dict[str, str]] = None,
    line_offset: int = WRAPPER_LINE_OFFSET,
) -> str:
    """Make a bridge error refer to the code the MODEL wrote.

    * ``rename_map`` (original → obfuscated, from the obfuscator) is inverted
      and applied so ``_0x3f21`` becomes the identifier the model used.
    * Compile diagnostics from the in-Revit Roslyn report line numbers of the
      WRAPPED code (``CS0012 … (line 30, col 31)`` for a 12-line snippet);
      when the message carries a CS code, every ``line N`` with N > offset is
      shifted back to user-code coordinates. Runtime messages (no CS code) are
      left untouched — their line numbers, when present, are not wrapper-based.

    Server pre-flight messages are built already-corrected by the pipeline and
    never pass through here, so no double-shifting is possible.
    """
    if not message:
        return message
    if rename_map:
        inverse = {obf: orig for orig, obf in rename_map.items()}
        message = _OBF_NAME_RE.sub(
            lambda m: inverse.get(m.group(0), m.group(0)), message
        )
    if _CS_CODE_RE.search(message):
        def _shift(m: re.Match[str]) -> str:
            n = int(m.group(1))
            return f"line {n - line_offset}" if n > line_offset else m.group(0)

        message = _LINE_NUM_RE.sub(_shift, message)
    return message


# ─────────────────────────────────────────────────────────────────────────────
# TurnRecord — the structured output contract
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    """Everything one execute_revit_code turn produced, in one row.

    ``result`` is the legacy-shaped tool dict (what the model sees, via
    :meth:`to_tool_result`); the rest is the telemetry/Evaluator contract that
    was previously scattered or dropped (repair count, timings, budget,
    outcome state).
    """

    ok: bool
    state: str  # ok|failed|compile_failed|blocked|timeout_unconfirmed|budget_stopped
    result: dict[str, Any]
    original_code: str = ""
    final_code: str = ""
    was_modified: bool = False
    repairs: list[dict[str, Any]] = field(default_factory=list)
    attempts: int = 0
    n_bridge_roundtrips: int = 0
    n_compile_checks: int = 0
    err_code: Optional[str] = None
    cs_codes: list[str] = field(default_factory=list)
    verdict: Optional[dict[str, Any]] = None
    timings_ms: dict[str, int] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    tool: str = "execute_revit_code"
    # Declarative-op discriminator (run_declarative sets it, e.g.
    # "create_element"); None on the legacy execute_revit_code path.
    op: Optional[str] = None
    # Expects postcondition contract (KUKAI_EXPECTS_CONTRACT, IQ N2). All None/
    # empty unless the model DECLARED a contract while the flag was ON — so
    # flag-off records (and their summary() rows) stay byte-identical.
    #   expects_declared — normalized {"op","category","count"} the model sent
    #   expects_delta    — witnessed signed category-count delta (op-oriented:
    #                      create → after-before, delete → before-after)
    #   expects_verdict  — "pass"|"partial"|"fail"|"unverifiable"
    #   expects_probe    — {"before","after","probe_ms","probes_run","reason"?}
    expects_declared: Optional[dict[str, Any]] = None
    expects_delta: Optional[int] = None
    expects_verdict: Optional[str] = None
    expects_probe: dict[str, Any] = field(default_factory=dict)

    def to_tool_result(self) -> dict[str, Any]:
        """The dict the tool loop serializes for the model — legacy shape.

        Parity contract: identical keys to the inline path (bridge result +
        ``err`` + ``execution`` when the harness rewrote the code). The record's
        telemetry fields are NOT injected into model context (log/ContextVar
        only) so flag-on and flag-off turns stay shadow-comparable.
        """
        out = self.result
        if self.was_modified and isinstance(out, dict):
            out["execution"] = {
                "final_code": self.final_code,
                "was_modified": True,
                "repairs": self.repairs,
            }
        return out

    def summary(self) -> dict[str, Any]:
        """Compact loggable row (no code bodies — sha prefixes only)."""
        def _sha(s: str) -> str:
            return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12] if s else ""

        row = {
            "tool": self.tool,
            "op": self.op,
            "ok": self.ok,
            "state": self.state,
            "attempts": self.attempts,
            "repairs": self.repairs,
            "was_modified": self.was_modified,
            "original_sha": _sha(self.original_code),
            "final_sha": _sha(self.final_code),
            "err_code": self.err_code,
            "cs_codes": self.cs_codes,
            "bridge_roundtrips": self.n_bridge_roundtrips,
            "compile_checks": self.n_compile_checks,
            "verdict": self.verdict,
            "timings_ms": self.timings_ms,
            "budget": self.budget,
        }
        # Present only when a contract was declared — rows without one (and
        # every flag-off row) keep the exact pre-N2 key set.
        if self.expects_declared is not None:
            row["expects"] = {
                "declared": self.expects_declared,
                "verdict": self.expects_verdict,
                "delta": self.expects_delta,
                "probe": self.expects_probe,
            }
        return row


_last_turn_record: ContextVar[Optional[TurnRecord]] = ContextVar(
    "_exec_pipeline_last_record", default=None
)


def last_turn_record() -> Optional[TurnRecord]:
    """The turn's most recent TurnRecord (telemetry fold-in socket for chat_ws)."""
    return _last_turn_record.get()


# ─────────────────────────────────────────────────────────────────────────────
# Dependencies (injected — every seam is mockable)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineDeps:
    """Injected collaborators. ``from_llm_client`` builds the production set;
    tests inject fakes — the pipeline itself owns only sequencing + policy."""

    transport: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
    validate: Callable[[str], Optional[list[str]]]
    fix: Callable[[str], str]
    fix_from_error: Callable[[str, str], Optional[str]]
    llm_repair: Callable[..., Awaitable[Optional[str]]]
    build_repair_context: Callable[..., Awaitable[str]]
    compile_gate: CompileGate
    is_compilation_error: Callable[[dict[str, Any]], bool]
    enrich_runtime_error: Callable[[str], str]
    obfuscate: Callable[[str], tuple[str, dict[str, str]]]
    revit_version: str = ""
    record_recipe: Optional[Callable[..., None]] = None
    post_flight: Optional[Callable[[str, str], Awaitable[str]]] = None
    # Evaluator socket (kukai.will) — receives the draft TurnRecord, may return
    # a verdict dict. Never blocks the result; failures are swallowed.
    verdict_hook: Optional[
        Callable[["TurnRecord"], Awaitable[Optional[dict[str, Any]]]]
    ] = None


# ─────────────────────────────────────────────────────────────────────────────
# Expects postcondition witness (KUKAI_EXPECTS_CONTRACT, IQ moment N2)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class _ExpectsState:
    """Per-run witness state for one declared `expects` contract.

    Built only when the flag is ON and the model declared a well-formed
    contract; carries the read-only before/after category counts so the
    verdict stage can fold a world-grounded ``probe.expects_count_delta``
    check. ``countable`` is False for op=modify (no honest count witness in
    v1), a missing/invalid count, or a non-``OST_*`` category — those degrade
    straight to `unverifiable` with ZERO probe roundtrips.
    """

    declared: dict[str, Any]
    countable: bool = False
    before: Optional[int] = None
    after: Optional[int] = None
    probes_run: int = 0
    probe_ms: int = 0
    reason: Optional[str] = None  # first blocker → the check's `detail`


# ─────────────────────────────────────────────────────────────────────────────
# The pipeline
# ─────────────────────────────────────────────────────────────────────────────

class RevitExecutionPipeline:
    """Single owner of validate→fix→compile→execute→repair→verdict→record."""

    MAX_ATTEMPTS = 3

    def __init__(self, deps: PipelineDeps, budget: Optional[TurnBudget] = None):
        self._deps = deps
        self._budget = budget  # tests may pin one; prod derives per-run

    # ------------------------------------------------------------------ run
    async def run(
        self,
        args: dict[str, Any],
        user_query: str = "",
        system_context: str = "",
    ) -> TurnRecord:
        d = self._deps
        t_run0 = time.monotonic()
        timings: dict[str, int] = {}
        original_code = (args or {}).get("code", "") or ""
        code = original_code
        repairs: list[dict[str, Any]] = []
        # IQ N1: the last (error → repaired-code) transition, verified only if
        # the following attempt succeeds (KUKAI_REPAIR_MINING capture).
        pending_pair: Optional[dict[str, str]] = None
        n_bridge = 0
        n_compile = 0

        # ── Stage 0: expects contract (KUKAI_EXPECTS_CONTRACT; None when the
        # flag is OFF or nothing well-formed was declared — fully inert) ──
        expects = self._expects_parse(args)

        # ── Stage 1: Validate (defense-in-depth; no-op under WEAK_SANDBOX) ──
        violations = d.validate(code)
        if violations:
            result = attach_err(
                {
                    "error": True,
                    "message": "Код заблокирован проверкой безопасности",
                    "violations": violations,
                },
                ErrCode.SECURITY_BLOCKED_PATTERN,
            )
            if expects is not None and expects.reason is None:
                expects.reason = "not_executed"
            return await self._finalize(
                ok=False, state="blocked", result=result,
                original_code=original_code, final_code=code, repairs=repairs,
                attempts=0, n_bridge=n_bridge, n_compile=n_compile,
                budget=None, timings=timings, t_run0=t_run0,
                args=args, expects=expects,
            )

        # ── Stage 2: Fix — ONCE, recorded, truthful final_code ──────────────
        t0 = time.monotonic()
        try:
            fixed = d.fix(code)
            if fixed != code and not d.validate(fixed):
                code = fixed
                repairs.append({"attempt": 0, "fix_source": "preflight_fixer"})
                logger.info("EXEC_PIPELINE: pre-flight fixer applied changes")
        except Exception as fix_exc:  # noqa: BLE001 — fixer is best-effort (legacy parity)
            logger.debug("EXEC_PIPELINE: pre-flight fixer failed (non-fatal): %s", fix_exc)
        timings["fix_ms"] = int((time.monotonic() - t0) * 1000)

        # ── Stage 2b: post-flight agents (critic/version-checker; flags OFF) ─
        if d.post_flight is not None:
            try:
                reviewed = await d.post_flight(code, user_query)
                if reviewed and reviewed != code and not d.validate(reviewed):
                    code = reviewed
                    repairs.append({"attempt": 0, "fix_source": "code_critic"})
            except Exception as pf_exc:  # noqa: BLE001 — non-fatal, legacy parity
                logger.debug("EXEC_PIPELINE: post-flight failed (non-fatal): %s", pf_exc)

        # ── Budget: ONE hierarchy (turn ≥ pipeline ≥ attempt ≥ bridge-wait) ──
        budget = self._budget
        if budget is None:
            try:
                from kukai.config import get_settings

                max_timeout_ms: Optional[int] = (
                    get_settings().max_execute_timeout * 1000
                )
            except Exception:  # noqa: BLE001
                max_timeout_ms = None
            budget = TurnBudget.for_execute(
                code,
                (args or {}).get("estimated_elements"),
                max_timeout_ms=max_timeout_ms,
                turn_remaining=turn_remaining_s(),
            )

        # ── Stage 2c: expects witness — BEFORE count (read-only, fail-open,
        # inside the budget; 1st of ≤2 probe roundtrips this turn) ──
        if expects is not None and expects.countable:
            expects.before = await self._expects_count(expects, budget)

        # ── Stages 3-7: Wrap → CompileCheck → Obfuscate → Execute → Repair ──
        current_code = code
        result: dict[str, Any] = {
            "error": True,
            "message": "No execution attempt was made",
        }
        exec_ms = 0
        attempt = 0
        stopped_reason: Optional[str] = None  # "safety" | "budget" | None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            eff_timeout_ms = budget.effective_execute_timeout_ms()
            if not budget.can_dispatch():
                if n_bridge == 0 and n_compile == 0:
                    # Nothing ever ran — say so honestly (error: True is safe).
                    result = attach_err(
                        {
                            "error": True,
                            "message": (
                                f"[SYSTEM: бюджет инструмента ({budget.total_s:.0f}с) "
                                "исчерпан до запуска — код НЕ выполнялся в Revit. "
                                "Сузь запрос или повтори позже.]"
                            ),
                        },
                        ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED,
                    )
                stopped_reason = "budget"
                break

            t_att0 = time.monotonic()
            wrapped = wrap_user_code(current_code)

            # CompileCheck (un-latched gate; None → fail open, go to Revit)
            gate_result = await d.compile_gate.check(wrapped, d.revit_version)
            n_compile += 1
            if gate_result is not None and not getattr(gate_result, "success", True):
                errors = list(getattr(gate_result, "errors", []))[:3]
                error_msgs = "; ".join(
                    f"{e.code}: {e.message} "
                    f"(line {max(1, e.line - WRAPPER_LINE_OFFSET)})"
                    for e in errors
                )
                logger.info(
                    "EXEC_PIPELINE PRE-FLIGHT COMPILE FAILED attempt=%d: %s",
                    attempt, error_msgs[:300],
                )
                result = attach_err(
                    {"error": True, "message": f"Compilation failed: {error_msgs}"},
                    ErrCode.COMPILE_CS_ERROR,
                    cs_codes=[e.code for e in errors],
                )
            else:
                # Obfuscate (keep the map — it is the de-obfuscation key for
                # every client-side error on this attempt) and dispatch.
                obfuscated, rename_map = d.obfuscate(wrapped)
                result = await d.transport(
                    "execute",
                    {
                        "code": obfuscated,
                        "timeout_ms": eff_timeout_ms,
                        "attempt": attempt,
                        "_pipeline_prepared": True,
                    },
                )
                n_bridge += 1
                # De-obfuscate + de-offset error feedback on ALL paths — the
                # repair LLM (and the model) must see the code THEY wrote.
                if (
                    isinstance(result, dict)
                    and result.get("error")
                    and isinstance(result.get("message"), str)
                ):
                    result["message"] = normalize_error_message(
                        result["message"], rename_map
                    )
            exec_ms = int((time.monotonic() - t_att0) * 1000)

            # Repair? (legacy contract: only while attempt < 3; attempt-3
            # errors return as-is, enriched)
            if (
                isinstance(result, dict)
                and result.get("error") is True
                and attempt < self.MAX_ATTEMPTS
                and d.is_compilation_error(result)
            ):
                error_msg = result.get("message", "")
                logger.info(
                    "EXEC_PIPELINE compile failed (attempt %d/%d), trying repair: %s",
                    attempt, self.MAX_ATTEMPTS, str(error_msg)[:200],
                )
                self._audit("repair", {
                    "attempt": attempt, "error": str(error_msg)[:500],
                })

                # Deterministic fix first (no LLM round-trip)
                try:
                    det_fix = d.fix_from_error(current_code, error_msg)
                except Exception:  # noqa: BLE001
                    det_fix = None
                if det_fix and det_fix != current_code and not d.validate(det_fix):
                    pending_pair = {"error_text": str(error_msg),
                                    "broken_code": current_code,
                                    "fix_source": "deterministic"}
                    current_code = det_fix
                    repairs.append({"attempt": attempt, "fix_source": "deterministic"})
                    logger.info(
                        "EXEC_PIPELINE deterministic fix applied for: %s",
                        str(error_msg)[:100],
                    )
                    continue

                # LLM repair — only when the budget can still afford it
                if budget.can_llm_repair():
                    try:
                        repair_context = await d.build_repair_context(
                            user_query, error_msg, attempt, system_context
                        )
                    except Exception:  # noqa: BLE001 — context enrichment is best-effort
                        repair_context = system_context
                    repaired = await d.llm_repair(
                        current_code, error_msg, attempt, user_query, repair_context
                    )
                    if repaired:
                        try:
                            repaired = d.fix(repaired)
                        except Exception:  # noqa: BLE001
                            pass
                        if d.validate(repaired):
                            logger.warning(
                                "EXEC_PIPELINE: repaired code failed safety check"
                            )
                            stopped_reason = "safety"
                            break
                        pending_pair = {"error_text": str(error_msg),
                                        "broken_code": current_code,
                                        "fix_source": "llm_repair"}
                        current_code = repaired
                        repairs.append({"attempt": attempt, "fix_source": "llm_repair"})
                        continue
                    # repair LLM returned nothing → fall through, return the
                    # compile error as-is (legacy parity)
                else:
                    logger.info(
                        "EXEC_PIPELINE: budget too low for LLM repair "
                        "(%.0fs left) — returning error to the model",
                        budget.remaining_s(),
                    )

            # IQ N1: repair-success moment — persist the verified pair
            # (KUKAI_REPAIR_MINING; default OFF ⇒ no-op; always fail-open).
            if pending_pair is not None and not (
                isinstance(result, dict) and result.get("error")
            ):
                from kukai.llm.repair_knowledge import record_repair_pair

                record_repair_pair(
                    fixed_code=current_code, revit_version=d.revit_version,
                    attempts=attempt, **pending_pair,
                )

            # Success, non-repairable error, or repair declined → final result
            return await self._finalize(
                ok=not (isinstance(result, dict) and result.get("error")),
                state=None,  # derived in _finalize
                result=result,
                original_code=original_code, final_code=current_code,
                repairs=repairs, attempts=attempt,
                n_bridge=n_bridge, n_compile=n_compile,
                budget=budget, timings=timings, t_run0=t_run0,
                exec_ms=exec_ms, user_query=user_query,
                args=args, expects=expects,
            )

        # Loop exhausted via break (safety-violation or budget stop).
        if stopped_reason == "safety" and isinstance(result, dict) and result.get("error"):
            # Legacy "3 попыток" contract (reached exactly on this break path).
            original_error = result.get("message", "Unknown error")
            result["message"] = (
                f"Код не удалось скомпилировать после 3 попыток исправления. "
                f"Ошибка: {str(original_error)[:300]}. "
                f"Попробуй другой подход к решению задачи."
            )
            cs_match = re.search(r"(CS\d{4})", str(original_error))
            if cs_match:
                from kukai.llm.client import _CS_ERROR_TRANSLATIONS

                translation = _CS_ERROR_TRANSLATIONS.get(cs_match.group(1))
                if translation:
                    result["message"] += f" ({translation})"
            attach_err(
                result,
                ErrCode.COMPILE_FAILED_AFTER_REPAIRS,
                cs_codes=extract_cs_codes(str(original_error)),
            )
        return await self._finalize(
            ok=False,
            state="budget_stopped" if stopped_reason == "budget" else "compile_failed",
            result=result,
            original_code=original_code, final_code=current_code,
            repairs=repairs, attempts=attempt,
            n_bridge=n_bridge, n_compile=n_compile,
            budget=budget, timings=timings, t_run0=t_run0,
            exec_ms=exec_ms, user_query=user_query,
            reclassify=False,  # err already attached precisely on these paths
            args=args, expects=expects,
        )

    # -------------------------------------------------------- run_declarative
    async def run_declarative(
        self,
        code: str,
        *,
        tool: str,
        op: str,
        args: Optional[dict[str, Any]] = None,
        timeout_ms: int = 60_000,
        derive_extra_checks: Optional[Callable[[Any], list]] = None,
    ) -> TurnRecord:
        """Reduced chain for SERVER-RENDERED declarative writes (design
        2026-07-04 §2.5): Validate → Wrap → CompileGate → Execute → Verdict →
        Record. ONE attempt, NO fixer mutation of template output, NO
        llm_repair — a compile failure of a verified template is a *server
        bug* and must surface, not be "repaired" into something else.

        The Verdict stage is the designed Evaluator socket: when
        ``deps.verdict_hook`` is unset (production wiring), a thin adapter over
        :func:`kukai.will.evaluator.evaluate_structural` runs with the caller's
        ``derive_extra_checks(result)`` (e.g. the create's read-back checks) —
        the first tool whose Evaluator verdict rides inside the TurnRecord
        (EXEC_PIPELINE_RECORD log + JSONL + ``last_turn_record()``), i.e. in
        the truth layer's data plane, not only in shadow telemetry.
        """
        d = self._deps
        t_run0 = time.monotonic()
        timings: dict[str, int] = {}
        n_bridge = 0
        n_compile = 0
        attempts = 0
        exec_ms = 0
        state: Optional[str] = None
        result: dict[str, Any] = {
            "error": True,
            "message": "No execution attempt was made",
        }

        # ── Validate (defense-in-depth; template output must always pass) ──
        violations = d.validate(code)
        if violations:
            logger.error(
                "EXEC_PIPELINE declarative %s/%s BLOCKED by safety (server bug): %s",
                tool, op, violations,
            )
            result = attach_err(
                {
                    "error": True,
                    "message": "Код заблокирован проверкой безопасности",
                    "violations": violations,
                },
                ErrCode.SECURITY_BLOCKED_PATTERN,
            )
            state = "blocked"
            budget: Optional[TurnBudget] = None
        else:
            # ── Budget: caller-declared timeout under the turn deadline ──
            budget = self._budget
            if budget is None:
                total = max(timeout_ms / 1000.0 + _TRANSPORT_OVERHEAD_S, _MIN_FLOOR_S)
                rem = turn_remaining_s()
                if rem is not None and rem > 0:
                    total = max(min(total, rem), _MIN_FLOOR_S)
                budget = TurnBudget(total_s=total, execute_timeout_ms=int(timeout_ms))

            # ── Wrap → CompileGate (one check; failure surfaces, no repair) ──
            wrapped = wrap_user_code(code)
            gate_result = await d.compile_gate.check(wrapped, d.revit_version)
            n_compile = 1
            if gate_result is not None and not getattr(gate_result, "success", True):
                errors = list(getattr(gate_result, "errors", []))[:3]
                error_msgs = "; ".join(
                    f"{e.code}: {e.message} "
                    f"(line {max(1, e.line - WRAPPER_LINE_OFFSET)})"
                    for e in errors
                )
                logger.error(
                    "EXEC_PIPELINE declarative %s/%s TEMPLATE COMPILE FAILED "
                    "(server bug — report to operator): %s",
                    tool, op, error_msgs[:300],
                )
                result = attach_err(
                    {
                        "error": True,
                        "message": (
                            f"Внутренняя ошибка: серверный шаблон {op} не "
                            f"скомпилировался — сообщи оператору. {error_msgs}"
                        ),
                    },
                    ErrCode.COMPILE_CS_ERROR,
                    cs_codes=[e.code for e in errors],
                )
                state = "compile_failed"
            elif not budget.can_dispatch():
                result = attach_err(
                    {
                        "error": True,
                        "message": (
                            f"[SYSTEM: бюджет инструмента ({budget.total_s:.0f}с) "
                            "исчерпан до запуска — код НЕ выполнялся в Revit.]"
                        ),
                    },
                    ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED,
                )
                state = "budget_stopped"
            else:
                # ── Execute (single attempt; server code is sent unobfuscated —
                # there is nothing model-authored to hide, and error feedback
                # stays readable) ──
                attempts = 1
                t_att0 = time.monotonic()
                result = await d.transport(
                    "execute",
                    {
                        "code": wrapped,
                        "timeout_ms": budget.effective_execute_timeout_ms(),
                        "attempt": 1,
                        "_pipeline_prepared": True,
                    },
                )
                n_bridge = 1
                exec_ms = int((time.monotonic() - t_att0) * 1000)
                if (
                    isinstance(result, dict)
                    and result.get("error")
                    and isinstance(result.get("message"), str)
                ):
                    # De-offset compile line numbers (no rename map — unobfuscated).
                    result["message"] = normalize_error_message(result["message"], None)

        ok = not (isinstance(result, dict) and result.get("error"))
        err_block = result.get("err") if isinstance(result, dict) else None
        err_code = err_block.get("code") if isinstance(err_block, dict) else None
        if state is None:
            if ok:
                state = "ok"
            elif err_code in (
                ErrCode.TRANSPORT_BRIDGE_TIMEOUT.value,
                ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED.value,
                ErrCode.TRANSPORT_EXECUTION_UNKNOWN.value,
            ):
                state = "timeout_unconfirmed"
            elif err_code == ErrCode.COMPILE_CS_ERROR.value:
                state = "compile_failed"
            else:
                state = "failed"

        timings["exec_ms"] = exec_ms
        timings["total_ms"] = int((time.monotonic() - t_run0) * 1000)

        # A REFUSAL MUST CARRY ITS REASON INTO THE RECEIPT.
        # Measured on the tower run (29.07): the KIR arm recorded
        # `err_code: null` on two refused writes, while the raw-C# arm recorded
        # `runtime.revit_exception`. The reason was never missing — the
        # emitted template refuses with a STRUCTURAL marker
        # (`postconditions_violated`, `stale_or_failed`) — but nothing on this
        # arm ever called `attach_err`, so the receipt read empty and the KIR
        # path looked, in the numbers, like it refused worse than raw C#.
        # Placed AFTER the `state` derivation on purpose: `state` keeps its
        # existing meaning exactly, only the receipt gains the name.
        if not ok and err_code is None:
            _marker = ""
            if isinstance(result, dict):
                _inner = result.get("result")
                _marker = str(
                    result.get("error")
                    or (_inner.get("error") if isinstance(_inner, dict) else "")
                    or ""
                ).lower()
            _msg = str(result.get("message", "")) if isinstance(result, dict) else ""
            if _marker == "postconditions_violated":
                _code = ErrCode.KIR_POSTCONDITION_VIOLATED
            elif _marker == "stale_or_failed":
                _code = ErrCode.KIR_RUNTIME_REFUSED
            elif _marker == "timeout_unconfirmed":
                _code = ErrCode.KIR_UNCONFIRMED
            else:
                # A template that fails any other way is refused by Revit
                # itself; the prose classifier is the same one the raw-C# arm
                # uses, so both arms name the same thing the same way.
                _code = classify_bridge_error(_msg)
            if isinstance(result, dict):
                attach_err(result, _code, cs_codes=extract_cs_codes(_msg))
                err_block = result["err"]
                err_code = err_block["code"]

        record = TurnRecord(
            ok=ok,
            state=state,
            result=result if isinstance(result, dict) else {"result": result},
            original_code=code,
            final_code=code,          # declarative: never mutated, by construction
            was_modified=False,
            repairs=[],
            attempts=attempts,
            n_bridge_roundtrips=n_bridge,
            n_compile_checks=n_compile,
            err_code=err_code,
            cs_codes=(list(err_block.get("cs_codes", []))
                      if isinstance(err_block, dict) else []),
            timings_ms=timings,
            budget=budget.to_dict() if budget is not None else {},
            tool=tool,
            op=op,
        )

        # ── Verdict — the Evaluator socket (never blocks, never throws) ──
        record.verdict = {
            "source": "pipeline.deterministic",
            "state": state,
            "ok": ok,
            "attempts": attempts,
        }
        if d.verdict_hook is not None:
            try:
                hooked = await d.verdict_hook(record)
                if hooked:
                    record.verdict = hooked
            except Exception as v_exc:  # noqa: BLE001 — verdict never breaks a turn
                logger.debug("EXEC_PIPELINE verdict hook failed (non-fatal): %s", v_exc)
        else:
            try:
                from kukai.will.evaluator import evaluate_structural

                extra = None
                if derive_extra_checks is not None:
                    try:
                        extra = derive_extra_checks(result)
                    except Exception:  # noqa: BLE001 — checks are best-effort
                        extra = None
                report = evaluate_structural(
                    tool, args or {}, result,
                    is_error=not ok, extra_checks=extra,
                )
                record.verdict = {
                    "source": "kukai.will.evaluator",
                    "verdict": report.verdict,
                    "score": round(report.score, 4),
                    "checks": len(report.checks),
                    "violations": list(report.violations),
                }
            except Exception as v_exc:  # noqa: BLE001 — verdict never breaks a turn
                logger.debug(
                    "EXEC_PIPELINE declarative verdict failed (non-fatal): %s", v_exc
                )

        self._record(record)
        return record

    # ---------------------------------------------------- expects witness
    def _expects_parse(self, args: Optional[dict[str, Any]]) -> Optional[_ExpectsState]:
        """Stage 0 of the expects contract: flag + declaration → witness state.

        Returns None when KUKAI_EXPECTS_CONTRACT is OFF or nothing well-formed
        was declared — the rest of the pipeline is then byte-identical to the
        pre-N2 build. Never raises (the contract must never break the write)."""
        try:
            from kukai.llm.tools import expects_contract_enabled

            if not expects_contract_enabled():
                return None
            from kukai.will.evaluator import parse_expects
            from kukai.will.probes import category_count_cs

            declared = parse_expects(args)
            if declared is None:
                return None
            st = _ExpectsState(declared=declared)
            if declared["op"] == "modify":
                # No honest count witness for in-place mutation in v1 — do NOT
                # fake one; zero probes, verdict stays `unverifiable`.
                st.reason = "modify_not_countable"
            elif declared["count"] is None:
                st.reason = "missing_count"
            elif category_count_cs(declared["category"]) is None:
                st.reason = "invalid_category"
            else:
                st.countable = True
            return st
        except Exception:  # noqa: BLE001 — witness is strictly best-effort
            logger.debug("EXEC_PIPELINE expects parse failed (non-fatal)", exc_info=True)
            return None

    async def _expects_count(
        self, st: _ExpectsState, budget: Optional[TurnBudget]
    ) -> Optional[int]:
        """One read-only category-count roundtrip (≤2 per turn by construction).

        Tightly time-capped and budget-guarded; ANY failure → None (the
        contract degrades to `unverifiable`, the write path is untouched).
        Sent pre-wrapped with the `_pipeline_prepared` marker (chat_ws
        transport-only branch: no fixer, no compile gate, no obfuscation) and
        WITHOUT an `attempt` key (excluded from rag_execute telemetry, the
        probes.py convention)."""
        timeout_s = _expects_probe_timeout_s()
        if budget is not None and budget.remaining_s() < timeout_s + 1.0:
            if st.reason is None:
                st.reason = "budget_low"
            return None
        t0 = time.monotonic()
        st.probes_run += 1
        try:
            from kukai.will.probes import probe_category_count

            count, reason = await probe_category_count(
                st.declared.get("category"),
                self._deps.transport,
                timeout_s=timeout_s,
                transform=wrap_user_code,
                params_extra={"_pipeline_prepared": True},
            )
        except Exception:  # noqa: BLE001 — probes never break the write path
            logger.debug("EXEC_PIPELINE expects probe failed (non-fatal)", exc_info=True)
            count, reason = None, "probe_unavailable"
        st.probe_ms += int((time.monotonic() - t0) * 1000)
        if count is None and st.reason is None:
            st.reason = reason or "probe_unavailable"
        return count

    async def _expects_finalize(
        self,
        record: TurnRecord,
        st: _ExpectsState,
        budget: Optional[TurnBudget],
    ):
        """AFTER count (success only) → the world-grounded delta check + the
        TurnRecord expects_* fields. Returns the Check (or None on any
        failure) for the verdict fold. Never raises."""
        try:
            from kukai.will.evaluator import (
                expects_delta_check,
                expects_verdict_from_check,
            )

            if st.countable and record.ok and st.before is not None:
                st.after = await self._expects_count(st, budget)
            elif st.countable and not record.ok and st.reason is None:
                # The write itself failed/was blocked — a delta would witness
                # nothing attributable; save the roundtrip.
                st.reason = "execution_failed"

            check = expects_delta_check(
                st.declared, st.before, st.after, reason=st.reason
            )
            record.expects_declared = dict(st.declared)
            record.expects_verdict = expects_verdict_from_check(check)
            if isinstance(check.observed, dict):
                record.expects_delta = check.observed.get("delta")
            probe: dict[str, Any] = {
                "before": st.before,
                "after": st.after,
                "probes_run": st.probes_run,
                "probe_ms": st.probe_ms,
            }
            if st.reason:
                probe["reason"] = st.reason
            record.expects_probe = probe
            return check
        except Exception:  # noqa: BLE001 — witness must never break a turn
            logger.debug("EXEC_PIPELINE expects finalize failed (non-fatal)", exc_info=True)
            return None

    # ------------------------------------------------------------- finalize
    async def _finalize(
        self,
        *,
        ok: bool,
        state: Optional[str],
        result: dict[str, Any],
        original_code: str,
        final_code: str,
        repairs: list[dict[str, Any]],
        attempts: int,
        n_bridge: int,
        n_compile: int,
        budget: Optional[TurnBudget],
        timings: dict[str, int],
        t_run0: float,
        exec_ms: int = 0,
        user_query: str = "",
        reclassify: bool = True,
        args: Optional[dict[str, Any]] = None,
        expects: Optional[_ExpectsState] = None,
    ) -> TurnRecord:
        d = self._deps

        # Capture the transport-level classification BEFORE the legacy
        # reclassification below overwrites it (parity: the inline path also
        # re-attached COMPILE/RUNTIME over e.g. transport.bridge_timeout). The
        # RECORD keeps the honest transport truth for state derivation even
        # though the model-visible err stays legacy-shaped.
        _pre_err = result.get("err") if isinstance(result, dict) else None
        _pre_err_code = _pre_err.get("code") if isinstance(_pre_err, dict) else None

        # Legacy tail: enrich runtime errors / classify. The verified-recipe
        # capture that used to sit HERE (on `not error`) moved to AFTER the
        # verdict stage (see _maybe_record_recipe below the verdict fold): the
        # witnessed expects_verdict is not computed until _expects_finalize, so
        # capturing here conflated "executed" with "correct" — an executed write
        # whose declared contract was NOT met still seeded the corpus.
        if isinstance(result, dict) and reclassify and state != "blocked":
            if result.get("error"):
                result["message"] = d.enrich_runtime_error(result.get("message", ""))
                attach_err(
                    result,
                    ErrCode.COMPILE_CS_ERROR
                    if d.is_compilation_error(result)
                    else ErrCode.RUNTIME_REVIT_EXCEPTION,
                    cs_codes=extract_cs_codes(str(result.get("message", ""))),
                )

        err_block = result.get("err") if isinstance(result, dict) else None
        err_code = err_block.get("code") if isinstance(err_block, dict) else None
        cs_codes = (
            list(err_block.get("cs_codes", [])) if isinstance(err_block, dict) else []
        )

        if state is None:
            if ok:
                state = "ok"
            elif _pre_err_code in (
                ErrCode.TRANSPORT_BRIDGE_TIMEOUT.value,
                ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED.value,
                ErrCode.TRANSPORT_EXECUTION_UNKNOWN.value,
            ):
                # Bounded wait elapsed but Revit may still be running — honest,
                # matches the running_unconfirmed contract of the tool loop.
                # (Checked against the PRE-reclassification code: the legacy
                # tail rewrites err to runtime.revit_exception for parity.)
                state = "timeout_unconfirmed"
            elif err_code == ErrCode.COMPILE_CS_ERROR.value:
                state = "compile_failed"
            else:
                state = "failed"

        timings["exec_ms"] = exec_ms
        timings["total_ms"] = int((time.monotonic() - t_run0) * 1000)

        record = TurnRecord(
            ok=ok,
            state=state,
            result=result,
            original_code=original_code,
            final_code=final_code,
            was_modified=final_code != original_code,
            repairs=repairs,
            attempts=attempts,
            n_bridge_roundtrips=n_bridge,
            n_compile_checks=n_compile,
            err_code=err_code,
            cs_codes=cs_codes,
            timings_ms=timings,
            budget=budget.to_dict() if budget is not None else {},
        )

        # Expects witness (KUKAI_EXPECTS_CONTRACT): AFTER count + the
        # world-grounded delta check; fields land on the record BEFORE the
        # verdict stage so both the fold below and any hook see them.
        expects_check = None
        if expects is not None:
            expects_check = await self._expects_finalize(record, expects, budget)

        # Verdict stage — the Evaluator socket. Deterministic default; the
        # hook (kukai.will) may override. Never blocks, never throws.
        record.verdict = {
            "source": "pipeline.deterministic",
            "state": state,
            "ok": ok,
            "attempts": attempts,
        }
        if expects_check is not None and record.expects_declared is not None:
            # A contract was declared → fold the witnessed check through the
            # ONE verdict function (kukai.will.evaluator) so a raw-C# write
            # stops being `unverifiable` when the world was actually measured.
            try:
                from kukai.will.evaluator import evaluate_structural

                report = evaluate_structural(
                    record.tool, args or {}, result,
                    is_error=not ok,
                    extra_checks=[expects_check],
                    cost={"probes_run": expects.probes_run,
                          "probe_ms": expects.probe_ms},
                )
                record.verdict = {
                    "source": "kukai.will.evaluator",
                    "verdict": report.verdict,
                    "score": round(report.score, 4),
                    "checks": len(report.checks),
                    "violations": list(report.violations),
                    "expects_verdict": record.expects_verdict,
                }
            except Exception as e_exc:  # noqa: BLE001 — verdict never breaks a turn
                logger.debug(
                    "EXEC_PIPELINE expects verdict fold failed (non-fatal): %s", e_exc
                )
        if d.verdict_hook is not None:
            try:
                hooked = await d.verdict_hook(record)
                if hooked:
                    record.verdict = hooked
            except Exception as v_exc:  # noqa: BLE001 — verdict never breaks a turn
                logger.debug("EXEC_PIPELINE verdict hook failed (non-fatal): %s", v_exc)

        # Corpus-integrity capture (moved here from the legacy tail): the
        # witnessed expects_verdict is now on the record, so the gate can refuse
        # a recipe whose declared contract was NOT met. Flag OFF ⇒ same rows as
        # before (capture on non-error, no witness column).
        self._maybe_record_recipe(
            record,
            final_code=final_code,
            exec_ms=exec_ms,
            attempts=attempts,
            user_query=user_query,
            reclassify=reclassify,
        )

        self._record(record)
        return record

    def _maybe_record_recipe(
        self,
        record: TurnRecord,
        *,
        final_code: str,
        exec_ms: int,
        attempts: int,
        user_query: str,
        reclassify: bool,
    ) -> None:
        """Witness-gated verified-recipe capture (KUKAI_RECIPE_WITNESS).

        Preserves the legacy capture PRECONDITIONS exactly (a dep is wired, the
        legacy tail ran, the result is a non-blocked success), then applies the
        integrity gate. Best-effort — never raises into the turn.
        """
        d = self._deps
        if d.record_recipe is None:
            return
        result = record.result
        if not (isinstance(result, dict) and reclassify and record.state != "blocked"):
            return
        if result.get("error"):
            return
        from kukai.recipes_collector import recipe_witness_enabled

        should, witness_verdict = recipe_capture_decision(
            record.expects_verdict, recipe_witness_enabled()
        )
        if not should:
            logger.info(
                "EXEC_PIPELINE recipe capture SKIPPED — expects_verdict=%s "
                "(witnessed contradiction; not a verified recipe)",
                record.expects_verdict,
            )
            return
        try:
            d.record_recipe(
                code=final_code,
                exec_time_ms=exec_ms,
                n_repairs=max(0, attempts - 1),
                user_query=user_query,
                witness_verdict=witness_verdict,
            )
        except Exception as rec_exc:  # noqa: BLE001 — never block the response
            logger.debug(
                "EXEC_PIPELINE verified-recipe write failed (non-fatal): %s",
                rec_exc,
            )

    # ---------------------------------------------------------------- record
    def _record(self, record: TurnRecord) -> None:
        """Record stage: structured log line + ContextVar + optional JSONL."""
        _last_turn_record.set(record)
        try:
            summary = json.dumps(record.summary(), ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            summary = f"<unserializable: state={record.state}>"
        logger.info("EXEC_PIPELINE_RECORD %s", summary)
        path = os.environ.get("KUKAI_EXEC_PIPELINE_RECORD_PATH", "")
        if path:
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(summary + "\n")
            except Exception:  # noqa: BLE001 — telemetry must never break a turn
                pass

    def _audit(self, stage: str, data: dict[str, Any]) -> None:
        try:
            from kukai import audit_trace

            audit_trace.trace(audit_trace.current_session(), stage, data)
        except Exception:  # noqa: BLE001 — audit is best-effort
            pass

    # ------------------------------------------------------------- factory
    @classmethod
    def from_llm_client(cls, llm_client: Any, bridge_callback: Any) -> "RevitExecutionPipeline":
        """Production wiring: pull every collaborator from the existing
        scaffolding (same sources as the legacy inline path — one revit_version,
        one fixer, one validator policy)."""
        from kukai.security.code_fixer import RevitCodeFixer
        from kukai.security.obfuscator import obfuscate_code_with_map
        from kukai.security.validation import validate_code_safety

        revit_version = getattr(llm_client, "_revit_version", "") or ""
        fixer = RevitCodeFixer(revit_version=revit_version)

        async def _transport(method: str, params: dict[str, Any]) -> dict[str, Any]:
            return await bridge_callback(method, params)

        async def _llm_repair(
            code: str, error: str, attempt: int, user_query: str, system_context: str
        ) -> Optional[str]:
            return await llm_client._repair_code(
                code, error, attempt,
                user_query=user_query, system_context=system_context,
            )

        async def _build_repair_context(
            user_query: str, error_msg: str, attempt: int, system_context: str
        ) -> str:
            # Attempt>=2 → reroute the immutable Wiki using the compile error;
            # always → deterministic, versioned API-surface facts.
            repair_context = system_context
            if attempt >= 2 and user_query:
                try:
                    from kukai.knowledge.mode import KnowledgeMode, knowledge_mode
                    from kukai.rag.wiki_router import get_wiki_router

                    if knowledge_mode() is KnowledgeMode.WIKI:
                        alt_query = f"{user_query} {error_msg[:200]}"
                        alt_wiki, alt_telemetry = await asyncio.to_thread(
                            get_wiki_router().inject,
                            alt_query,
                            revit_version=revit_version,
                            skip_llm_fallback=True,
                        )
                        if alt_wiki:
                            repair_context = (
                                system_context
                                + "\n\n## Альтернативный проверенный Wiki-паттерн "
                                  "(предыдущий подход не скомпилировался)\n"
                                + alt_wiki[:7000]
                            )
                            logger.info(
                                "EXEC_PIPELINE repair attempt %d: Wiki reroute "
                                "pages=%s release=%s",
                                attempt,
                                alt_telemetry.get("routed_pages"),
                                alt_telemetry.get("release_id"),
                            )
                except Exception:  # noqa: BLE001 — fall back to original context
                    pass
            try:
                from kukai.llm.api_members import enrich_compile_error

                api_hint = enrich_compile_error(error_msg, revit_version)
                if api_hint:
                    repair_context = repair_context + "\n\n" + api_hint
                    logger.info(
                        "EXEC_PIPELINE repair attempt %d: injected real-API facts",
                        attempt,
                    )
            except Exception as api_exc:  # noqa: BLE001
                logger.debug(
                    "EXEC_PIPELINE api_members enrich failed (non-fatal): %s", api_exc
                )
            return repair_context

        def _record_recipe(
            *, code: str, exec_time_ms: int, n_repairs: int, user_query: str,
            witness_verdict: Optional[str] = None,
        ) -> None:
            # Execution witness capture is independent of retired retrieval.
            from kukai.llm import client as _client_mod
            from kukai.recipes_collector import record_verified_recipe

            record_verified_recipe(
                query_ru=user_query or "",
                query_en=None,
                code=code,
                intent_metadata=_client_mod._turn_intent_metadata.get(),
                revit_version=revit_version,
                session_id=_client_mod._active_session_id.get(),
                exec_time_ms=exec_time_ms,
                n_repairs=n_repairs,
                query_id=None,
                retrieval_keys=None,
                witness_verdict=witness_verdict,
            )

        async def _post_flight(code: str, user_query: str) -> str:
            return await _post_flight_agents(llm_client, code, user_query)

        from kukai.llm import client as _client_mod

        deps = PipelineDeps(
            transport=_transport,
            validate=validate_code_safety,
            fix=fixer.fix,
            fix_from_error=fixer.fix_from_error,
            llm_repair=_llm_repair,
            build_repair_context=_build_repair_context,
            compile_gate=get_compile_gate(),
            is_compilation_error=_client_mod.LLMClient._is_compilation_error,
            enrich_runtime_error=_client_mod._enrich_runtime_error,
            obfuscate=obfuscate_code_with_map,
            revit_version=revit_version,
            record_recipe=_record_recipe,
            post_flight=_post_flight,
        )
        return cls(deps)


# ─────────────────────────────────────────────────────────────────────────────
# Post-flight agents (critic / version checker) — legacy Stage 0c+0d parity
# ─────────────────────────────────────────────────────────────────────────────

async def _post_flight_agents(llm_client: Any, code: str, user_query: str) -> str:
    """CodeCritic + VersionChecker (Phase 7.4), both flag-gated and default OFF.

    Compact re-house of the legacy Stage 0c+0d block. Returns the (possibly
    critic-fixed) code; any failure is non-fatal and returns the input code.
    """
    try:
        from kukai import config as _kcfg
    except Exception:  # noqa: BLE001
        return code
    use_critic = bool(getattr(_kcfg, "AGENT_USE_CRITIC", False))
    use_version = bool(getattr(_kcfg, "AGENT_USE_VERSION_CHECKER", False))
    if not (use_critic or use_version):
        return code

    from kukai.security.validation import validate_code_safety

    try:
        tasks: list[Awaitable[Any]] = []
        names: list[str] = []
        critic_examples: list[dict[str, Any]] = []
        if use_critic and user_query:
            try:
                from kukai.rag.wiki_router import get_wiki_router

                critic_examples = await asyncio.to_thread(
                    get_wiki_router().recipe_examples,
                    user_query,
                    max_examples=5,
                )
            except Exception:  # noqa: BLE001
                critic_examples = []
        if use_critic:
            async def _do_critic() -> Any:
                try:
                    from kukai.agents.code_critic import CodeCritic

                    return await CodeCritic().run(
                        query=user_query or "", code=code,
                        examples=critic_examples, timeout=12.0,
                    )
                except Exception as exc:  # noqa: BLE001
                    return exc
            tasks.append(_do_critic())
            names.append("critic")
        if use_version:
            async def _do_version() -> Any:
                try:
                    from kukai.agents.version_checker import VersionChecker

                    return await VersionChecker().run(code=code, timeout=12.0)
                except Exception as exc:  # noqa: BLE001
                    return exc
            tasks.append(_do_version())
            names.append("version")
        results = await asyncio.gather(*tasks)
        for name, res in zip(names, results):
            if isinstance(res, Exception):
                logger.info("EXEC_PIPELINE post-flight %s failed: %s", name, res)
                continue
            if name == "critic":
                verdict = res.value.get("verdict")
                issues = res.value.get("issues", [])
                fixed = res.value.get("fixed_code")
                logger.info(
                    "EXEC_PIPELINE CodeCritic verdict=%s issues=%d had_fix=%s",
                    verdict, len(issues), bool(fixed),
                )
                if verdict == "FIX_NEEDED" and fixed and isinstance(fixed, str):
                    if not validate_code_safety(fixed):
                        code = fixed
                        logger.info("EXEC_PIPELINE CodeCritic applied fix")
            elif name == "version":
                n_issues = len(res.value.get("issues", []))
                if n_issues > 0:
                    logger.info(
                        "EXEC_PIPELINE VersionChecker flagged %d cross-version "
                        "issues (logged, not auto-fixed)", n_issues,
                    )
    except Exception as post_exc:  # noqa: BLE001
        logger.debug("EXEC_PIPELINE post-flight setup failed (non-fatal): %s", post_exc)
    return code
