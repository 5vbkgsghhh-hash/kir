"""TurnContext — the immutable-ish descriptor of ONE chat turn's prepared inputs.

Golden-path decomposition, B2 (2026-07-12, /root/kukai-golden-path-plan.md).

`prepare_turn` (kukai/api/chat_ws.py) runs the turn's front half — validation,
tenant/auth/rate-limit, document context, skill/QA detection, the zero-LLM
shortcut, session state + project memory, the model passport, the grounding /
query-semantic steer, and stream init (thinking mode, the first status bubble,
the reasoning trace) — and hands the round engine EVERYTHING it needs as this
one value. Every field here is a local that was assigned in that prepare region
and read AFTER the cut line (the stream_chat call + the async-for fold +
post-loop) in the original monolithic `_handle_chat`.

THE ISOLATION LAW (seed): this module is DEPENDENCY-LIGHT on purpose — stdlib +
typing only, no `kukai.*` imports. Handles that WOULD pull a capability import
(the app state, telemetry metrics, the WebSocket, the model context, the
retrieval-health record, the reasoning trace, the bridge/status closures) are
typed `Any`. The future RoundEngine takes a TurnContext and never reaches back
into chat_ws. `tests/test_turn_import_law.py` enforces the no-capability-import
rule against the AST of every kukai/turn/*.py file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(kw_only=True)
class TurnContext:
    """All prepared inputs for one chat turn (see module docstring)."""

    # ── Identity / transport ────────────────────────────────────────────────
    ws: Any                       # the WebSocket connection (outbound frames)
    turn_id: str                  # stable across provider retries for this user turn
    ws_id: str                    # per-connection id (push registry, bridge, trace)
    device_id: str                # raw client device id (WS registry / audit / trace)
    tenant_id: str                # EFFECTIVE isolation key (Step 11; == device_id flag OFF)
    session_id: str               # conversation/session id (ownership, persistence, memory)

    # ── Request ─────────────────────────────────────────────────────────────
    message_text: str             # the user's (guard-sanitized) message
    preferences: Any              # client preferences dict (thinking, units, extension, ...)
    units: str                    # unit system ("metric"/...) forwarded to the LLM
    active_extension: str         # active extension id from preferences ("" if none)
    extension_profile: str        # loaded extension system-prompt profile ("" if none)

    # ── App handles ─────────────────────────────────────────────────────────
    state: Any                    # app state (state.llm / state.db / state.bridge)
    settings: Any                 # resolved settings (llm_model / api keys / base)
    metrics: Any                  # RequestMetrics telemetry row (mutated during the fold), or None

    # ── Conversation / model context ────────────────────────────────────────
    llm_messages: Any             # built LLM history (+ grounding/steer system nudges)
    context: Any                  # Revit model context for this session, or None
    has_document: bool            # whether a live model/document context is present
    use_tools: bool               # whether tools are enabled for this turn
    session_st: Any               # per-session SessionState (working set, tool memory), or None

    # ── Skills / QA / discovery ─────────────────────────────────────────────
    skill_name: str               # active skill display name ("" if none)
    skill_prompt: str             # active skill system prompt ("" if none)
    qa_context: Optional[dict[str, Any]]        # QA/QC package + checks, or None
    discovery_context: Optional[dict[str, Any]]  # preflight category/params, or None

    # ── Prompt blocks ───────────────────────────────────────────────────────
    session_state_block: str      # session-state (+ project memory) prompt block
    notes_context: str            # sanitized user notes soft-context ("" if none)
    model_passport_md: Any        # ~20K-token model passport markdown, or None
    project_name: str             # memory key "name|path" ("" if no document)

    # ── Stream init ─────────────────────────────────────────────────────────
    thinking_mode: bool           # UI/family-editor thinking mode → model selection
    reasoning_trace: Any          # per-turn ReasoningTrace accumulator, or None
    _flush_reasoning_trace: Any   # flush_trace callable for the reasoning trace, or None

    # ── Per-turn bookkeeping / closures ─────────────────────────────────────
    request_start: float          # monotonic turn start (latency / first-token timing)
    _turn_health: Any             # per-turn retrieval_health record, or None
    ws_bridge_callback: Any       # async bridge round-trip closure (execute/export/...)
    _status_seen: Any             # set[str] of already-emitted status bubbles (dedup)
    _status_once: Any             # async closure: emit a status bubble once per turn


@dataclass(kw_only=True)
class TurnRunResult:
    """Everything `run_turn`'s stream-retry fold produced that `finalize_turn`
    reads (golden-path B2 chunk 2, 2026-07-13).

    `run_turn` (kukai/api/chat_ws.py) runs the turn's engine half — the
    stream_chat → `async for` fold → silent-retry loop — and hands the post-loop
    tail EVERYTHING it accumulated as this one value. Every field here is a
    fold-LOCAL that was assigned inside the loop and read AFTER it (mute guard,
    skill markers, auto-nav/reveal/vision, grounding post-hoc, final persistence)
    in the original monolithic `_handle_chat`. State that already lived on
    `TurnContext` (metrics, status-dedup set, reasoning trace, ...) flows through
    `ctx` and is NOT duplicated here.

    THE ISOLATION LAW (seed): like `TurnContext`, this module stays stdlib +
    typing only — the ToolObservation elements of `turn_observations` are typed
    `Any` so `kukai.llm.tool_observation` is never imported here.
    """

    # ── Assistant output / mute-guard signals ───────────────────────────────
    collected_text: str           # accumulated assistant text (empty ⇒ mute-guard)
    tool_invoked: bool             # a tool_start fired this turn (mute-guard input)
    error_emitted: bool            # an error event was surfaced this turn (mute-guard input)

    # ── Tool-evidence structures (grounding / auto-show / reveal) ────────────
    turn_tool_names: list[str]     # names of executed tools, in tool_end order
    turn_write_ok: bool            # a WRITE tool returned non-error (witnessed auto-show/reveal)
    turn_lookup_norm_results: list[Any]  # raw lookup_norm results (aligned to lookup_norm in names)
    turn_observations: list[Any]   # unified per-turn ToolObservation list (nav_v2/reveal/shadow-compare)
    turn_found_ids: list[str]      # ids of the latest find (reveal present block)

    # ── Deferred loop exception (exact try/except/finally semantics) ─────────
    pending_exc: Optional[BaseException] = None  # loop exception captured by run_turn;
    #                                              finalize_turn re-raises it INSIDE its
    #                                              try so it flows through the SAME
    #                                              except/finally as the original in-line loop


@dataclass(kw_only=True)
class RoundState:
    """Everything the agent ROUND LOOP carries across rounds (golden-path C1,
    2026-07-13).

    `LLMClient._init_round_state` (kukai/llm/client.py) runs the round-loop
    init block — counters, budgets, the M2 router/convergence overrides,
    truth-gate bookkeeping, the turn wall-clock — and hands the loop EVERYTHING
    it carries as this one value. Every field here is a loop-CARRIED local of
    the original monolithic `_stream_chat_inner`: assigned in that init region
    (or mutated in one round) and read in a LATER round or in the loop's
    post-loop `else:` tail. Round-LOCAL state (the per-round tool-call
    accumulator, the leak-guard state, the open-bubble/collected-text locals)
    is reset at the top of every round and deliberately NOT here.

    THE ISOLATION LAW (seed): like `TurnContext`, this module stays stdlib +
    typing only — `full_messages` and `route` are typed `Any` so neither the
    provider message shape nor `kukai.agents.router.Route` is imported here.
    Field names = the original locals minus the leading underscore; the four
    UPPER_CASE fields were the loop's per-turn constants and keep their casing
    so the moved comments/scars still read true.
    """

    # ── Round budget / progress ──────────────────────────────────────────────
    full_messages: Any            # the turn's LLM message list (appended every round)
    tool_round: int               # rounds consumed so far
    effective_max_rounds: int     # round cap after skill/family-editor/router overrides

    # ── Provider / router ────────────────────────────────────────────────────
    gemini_failed_mid_stream: bool  # Gemini failed mid-conversation → stick to litellm
    route: Any                    # M2 router decision (Route), or None (was: _route)
    reasoning_effort_override: Optional[str]  # router's per-turn reasoning effort
    conv_on: bool                 # M2 convergence controller active (was: _conv_on)

    # ── Retry discipline / dedup ─────────────────────────────────────────────
    consecutive_errors: dict[str, int]  # per-tool consecutive-failure counters
    seen_tool_sigs: dict[str, int]      # tool-call signature → times seen this turn
    errored_sigs: set[str]              # sigs whose last identical call errored (retry allowed)
    dedup_count: int                    # duplicate tool calls suppressed this turn

    # ── Completion guarantee ─────────────────────────────────────────────────
    continuations: int            # length/empty continuations used (was: _continuations)
    MAX_CONTINUATIONS: int        # continuation cap (was: _MAX_CONTINUATIONS)
    carry_bubble: bool            # keep the stream bubble open across continuations

    # ── Code-salvage keystone ────────────────────────────────────────────────
    code_salvage_used: int        # corrective code-salvage rounds fired this turn
    MAX_CODE_SALVAGE: int         # per-turn cap (was: _MAX_CODE_SALVAGE)
    code_salvage_on: bool         # AGENT_CODE_SALVAGE flag (was: _code_salvage_on)

    # ── Truth gate (Step 8) ──────────────────────────────────────────────────
    world_tools_ok: int           # successful world-tool calls this turn
    turn_tool_calls_total: int    # all tool calls issued this turn
    truth_text_parts: list[str]   # answer text across length-continuations
    truth_witness_parts: list[str]  # Tier-1: tool result texts (claim witnesses)
    truth_gate_corrections: int   # corrective rounds fired (at most ONE per turn)
    truth_force_required: bool    # next round forces tool_choice="required" (one-shot)

    # ── Wall-clock budgets ───────────────────────────────────────────────────
    TOOL_BUDGET_S: float          # per-tool wall cap (was: _TOOL_BUDGET_S)
    TURN_BUDGET_S: float          # whole-turn deadline (was: _TURN_BUDGET_S)
    turn_start: float             # time.monotonic() at round-loop start
