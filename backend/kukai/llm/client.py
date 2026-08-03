"""LLM client — litellm-based with streaming and multi-round tool calling."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any, AsyncIterator, Callable, Coroutine, Optional

import litellm

from kukai.bridge.client import BridgeClient
from kukai.bridge.models import BridgeError
from kukai import audit_trace
from kukai.llm.envelope import (
    ErrCode,
    attach_err,
    classify_bridge_error,
    extract_cs_codes,
    result_is_error,
)
from kukai.llm.tools import get_tool_definitions
from kukai.llm.prompts import PromptAssembler
from kukai.bridge.models import ContextResult
from kukai.knowledge.mode import KnowledgeMode, knowledge_mode
# [archived 2026-06-12] Gemini OAuth chain → kukai/_archive/llm_gemini/ (disconnected
# from prod; the chain was already inert: gemini_oauth_enabled=False + openrouter primary)
from kukai.llm.turn_state import begin_turn, end_turn, current_turn

# Type alias for the bridge callback function:
#   async def callback(method: str, params: dict) -> dict
BridgeCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]

logger = logging.getLogger(__name__)

# ── Decomposition re-exports (2026-07-04, Step 1 — pure relocation) ─────────
# The symbols below moved to focused sibling modules; bodies are byte-identical.
# They are re-imported here so that (a) every existing importer
# (`from kukai.llm.client import X`) keeps working unchanged and (b) internal
# call sites keep using the same bare names. ContextVar IDENTITY is
# load-bearing: chat_ws.py binds `_active_session_id` and
# revit_execution_pipeline.py reads the plan-019 capture vars through THIS
# module — the objects live in kukai.llm.turn_context and are the same here.
from kukai.llm.turn_context import (  # noqa: F401
    _active_device_id,
    _active_session_id,
    _active_ws,
    _exec_pipeline_active,
    _pf2_deadline,
    _preflight_v2_enabled,
    _turn_intent_metadata,
)
from kukai.llm.stream_events import StreamEvent, _extract_usage  # noqa: F401
from kukai.llm.tool_call_leak_guard import LeakGuardState, guard_delta
from kukai.llm.loop_policy import (  # noqa: F401
    _ALWAYS_WRITE_TOOLS,
    _CONSECUTIVE_ERROR_LIMIT,
    _FAMILY_READ_ONLY_TOOLS,
    _MAX_EXECUTE_TIMEOUT_MS,
    _MODEL_WIDE_PATTERNS,
    _MUST_ACT_INTENTS,
    _WRITE_PATTERNS,
    _bump_tool_error,
    _calculate_execute_timeout,
    _invalidate_dedup_after_write,
    _looks_like_unexecuted_csharp,
    _reset_tool_error,
    _should_dedup,
    _smart_truncate,
    _tool_call_is_write,
    _tool_choice_for,
)
from kukai.llm.repair_knowledge import (  # noqa: F401
    _CS_ERROR_TRANSLATIONS,
    _RUNTIME_ERROR_HINTS,
    _enrich_runtime_error,
    _get_repair_hint,
    _is_compilation_error,
)
# Step 2: local tool-handler bodies moved to kukai.llm.tool_handlers.* — the
# modules are imported here so LLMClient can rebind them as class attributes
# (see the rebinding block inside the class). None of them imports client.py.
from kukai.llm.tool_handlers import files_excel as _th_files_excel
from kukai.llm.tool_handlers import norms as _th_norms
from kukai.llm.tool_handlers import revit_verbs as _th_revit_verbs
# Step 3: provider transport (fallback chains + ProviderChain rotation) moved
# to kukai.llm.transport — same rebinding pattern; state stays on LLMClient.
from kukai.llm import transport as _transport
from kukai.llm.transport import _GeminiFallbackIterator  # noqa: F401

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True

# ── Fix 1 (KUKAI_CONVERSE_FASTPATH) — converse fast-path gate + counter ─────────
# Smalltalk/help turns ("ты как?", "привет", "что умеешь") never need the
# Wiki pipeline or world tools — yet today they pay the full prompt assembly +
# wiki-frame round-trip before the first token. The fast-path skips that heavy prep
# and builds a LEAN prompt, so the first token comes ~instantly.
_FASTPATH_TAKEN_COUNT = 0


def _fastpath_intent_gate(meta: Optional[dict]) -> bool:
    """True ONLY for a ``converse`` turn — the single intent that never needs
    retrieval or tools. Deliberately narrow: a wrong True would strip enrichment
    from a real task, so it fires for converse and NOTHING else (verified by
    test_gate_rejects_* against the entire gold set)."""
    return isinstance(meta, dict) and meta.get("intent") == "converse"


def _inject_per_turn_tools(panel: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add the tools whose gate can only be answered DURING a turn.

    ``self._tools`` is built once in ``__init__`` — at import time, on a shared
    client, with no turn and therefore no device bound. Any tool gated on the
    turn's device is evaluated there as "no" and is missing from the cached list
    for the life of the process. That is how ``revit_ir`` stayed invisible in
    chat while ``KUKAI_KIR_TOOL=stage2`` was set, the compiler worked, and
    admin-driven KIR writes landed: the flag was never the problem, the cache
    was. Asked to build with it, the model answered "в текущем сеансе недоступен
    revit_ir" — correctly, four turns running (2026-07-27).

    Gate shut ⇒ the panel is returned UNCHANGED (same object), so every other
    user's turn stays byte-identical and ``_resolve_tools`` keeps its cached
    identity contract.
    """
    try:
        from kukai.ir.serving import (
            ADMIN_DEVICE, inject_revit_ir_schema, revit_ir_enabled,
            _turn_device_id,
        )

        # Оба входа гейта в лог. «Почему KIR не виден» — вопрос, который уже
        # стоил дня: флаг стоял, компилятор работал, админские записи ложились,
        # а модель четыре хода подряд отвечала «в текущем сеансе недоступен».
        # Гейт — конъюнкция двух условий, и без их значений отличить «флаг не
        # тот» от «устройство не то» нельзя ничем, кроме догадок.
        if not revit_ir_enabled():
            logger.debug(
                "KIR gate shut: flag=%r turn_device=%r admin=%r",
                os.environ.get("KUKAI_KIR_TOOL", "off"),
                _turn_device_id(), ADMIN_DEVICE)
            return panel
        out = list(panel)                      # never mutate the shared cache
        inject_revit_ir_schema(out)
        logger.info("KIR gate open: revit_ir injected (%d tools)", len(out))
        return out
    except Exception:  # noqa: BLE001 — a tool gate must never break the turn
        logger.debug("per-turn tool injection skipped", exc_info=True)
        return panel


class LLMClient:
    """Handles LLM calls with streaming, tool calling, and multi-round execution."""

    def __init__(
        self,
        model: str,
        api_key: str = "",
        api_base: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 6,
        timeout: float = 90.0,
        prompt_assembler: Optional[PromptAssembler] = None,
        bridge_client: Optional[BridgeClient] = None,
        fallback_model: str = "",
        fallback_api_key: str = "",
        fallback_timeout: float = 120.0,
        antigravity_url: str = "",         # Optional Antigravity Pro proxy URL (lbjlaq)
        antigravity_api_key: str = "",     # Antigravity proxy auth key
        antigravity_model: str = "gemini-3-flash-preview",
        antigravity_timeout: float = 90.0,
        agy_url: str = "",                 # agy CLI proxy URL (thinking primary)
        agy_api_key: str = "",
        agy_model: str = "gemini-3.5-flash",
        agy_timeout: float = 180.0,
        google_backup_api_key: str = "",   # 1st AIza Google AI Studio key
        google_fallback_api_key: str = "",  # 2nd AIza Google AI Studio key
        google_extra_api_keys: Optional[list[str]] = None,  # 3rd+ AIza keys (sequential cascade)
        revit_version: str = "",
        gemini_pool: Optional[GeminiTokenPool] = None,
        thinking_model: str = "",
        thinking_timeout: float = 360.0,
        last_resort_model: str = "",
        last_resort_api_key: str = "",
        last_resort_api_base: str = "",
        reasoning_effort: str = "",
    ):
        self._model = model
        self._thinking_model = thinking_model  # OpenRouter model for thinking mode
        self._thinking_timeout = thinking_timeout
        self._api_key = api_key
        self._api_base = api_base
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._max_tool_rounds = max_tool_rounds
        self._timeout = timeout
        self._prompt_assembler = prompt_assembler
        self._bridge = bridge_client
        self._fallback_model = fallback_model
        self._fallback_api_key = fallback_api_key
        self._fallback_timeout = fallback_timeout
        self._antigravity_url = (antigravity_url or "").rstrip("/")
        self._antigravity_api_key = antigravity_api_key
        self._antigravity_model = antigravity_model or "gemini-3-flash-preview"
        self._antigravity_timeout = antigravity_timeout
        self._agy_url = (agy_url or "").rstrip("/")
        self._agy_api_key = agy_api_key
        self._agy_model = agy_model or "gemini-3.5-flash"
        self._agy_timeout = agy_timeout
        self._google_backup_api_key = google_backup_api_key
        self._google_fallback_api_key = google_fallback_api_key
        # Extra AIza keys: tried sequentially after #1, #2. Dedup + drop empty
        # + drop the two already-handled primary/fallback to avoid retrying
        # the same key on cascading failure.
        _seen = {self._api_key, self._google_backup_api_key, self._google_fallback_api_key, ""}
        self._google_extra_api_keys: list[str] = []
        for k in (google_extra_api_keys or []):
            k = (k or "").strip()
            if k and k not in _seen:
                self._google_extra_api_keys.append(k)
                _seen.add(k)
        # Pre-derive the gemini/* model name from primary vertex_ai/* model.
        # Used for AIza-keyed fallback calls so litellm actually uses the
        # api_key (not silently SA-JSON fall-through which keeps the same Vertex
        # quota and makes AIza levels theatrical). Example transform:
        #   vertex_ai/gemini-3-flash-preview -> gemini/gemini-3-flash-preview
        if model and model.startswith("vertex_ai/"):
            self._google_aistudio_model = "gemini/" + model.split("/", 1)[1]
        elif model and model.startswith("gemini/"):
            self._google_aistudio_model = model
        else:
            # Unknown primary — disable AIza levels so we don't send to wrong endpoint
            self._google_aistudio_model = ""
        # NOTE: _last_resort_* still stored for backward-compat. Not used.
        self._last_resort_model = last_resort_model
        self._last_resort_api_key = last_resort_api_key
        self._last_resort_api_base = last_resort_api_base
        # Reasoning depth knob. Currently informational only — actual reasoning
        # is enabled via Vertex-native `thinking_config` in _litellm_response
        # (Vertex Gemini rejects litellm's normalized `reasoning_effort`).
        self._reasoning_effort = reasoning_effort
        # Startup default Revit version. The per-TURN value lives in TurnState
        # (see the _revit_version property below) so concurrent users on
        # different Revit versions never cross-contaminate code-gen.
        self._revit_version_default: str = revit_version
        self._module_registry = None  # Set via set_module_registry() after startup
        self._tools = get_tool_definitions()
        self._gemini_pool = gemini_pool

        from kukai.llm.circuit_breaker import CircuitBreaker
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            slow_threshold_s=15.0,
            cooldown_s=120.0,
        )

        # Step 9 (KUKAI_PROVIDER_CHAIN): per-provider health chain for OpenRouter
        # routing. Lazily constructed on first flag-ON OpenRouter call (see
        # _get_provider_chain); stays None — never constructed or consulted —
        # while the flag is OFF, so the legacy request path is untouched.
        self._provider_chain = None

        # Cap concurrent LLM API calls to prevent provider rate-limiting.
        # Users beyond the limit wait (not rejected) until a slot frees up.
        # Raised to 300 to support 10 Gemini Pro accounts (10,000 RPM total).
        self._llm_semaphore = asyncio.Semaphore(300)

        # NOTE: per-request state (_last_large_result, _last_generated_excel_bytes/
        # _filename, _last_uploaded_file_bytes, _revit_version) is NOT stored on
        # self.* — LLMClient is a process-wide singleton, so that leaked across
        # concurrent users. It now lives in a per-asyncio-task TurnState, exposed
        # via the properties just below. See kukai/llm/turn_state.py.

        # OpenAI client for embeddings (used by RAG matchers, including
        # scheduler v2 ГЭСН matcher). Lazy-instantiated on first access.
        # Reads KUKAI_OPENAI_API_KEY then OPENAI_API_KEY (matches existing
        # pattern in this file ~line 1878).
        self._openai_client = None  # type: ignore[assignment]
        self._vor_store = None  # set by main.py at startup if available

    # ── Per-turn state (isolated per asyncio task — see turn_state.py) ─────
    # These properties redirect the former self._* per-request fields to the
    # current task's TurnState. Every existing call site keeps working verbatim
    # (`self._x = v` → setter; `getattr(self, "_x", default)` → getter); the only
    # change is that concurrent users no longer share/overwrite each other's data.
    @property
    def _revit_version(self) -> str:
        return current_turn().revit_version or self._revit_version_default

    @_revit_version.setter
    def _revit_version(self, value: str) -> None:
        current_turn().revit_version = value or ""

    @property
    def _last_large_result(self) -> Any:
        return current_turn().last_large_result

    @_last_large_result.setter
    def _last_large_result(self, value: Any) -> None:
        current_turn().last_large_result = value

    @property
    def _last_generated_excel_bytes(self) -> Optional[bytes]:
        return current_turn().last_generated_excel_bytes

    @_last_generated_excel_bytes.setter
    def _last_generated_excel_bytes(self, value: Optional[bytes]) -> None:
        current_turn().last_generated_excel_bytes = value

    @property
    def _last_generated_excel_filename(self) -> Optional[str]:
        return current_turn().last_generated_excel_filename

    @_last_generated_excel_filename.setter
    def _last_generated_excel_filename(self, value: Optional[str]) -> None:
        current_turn().last_generated_excel_filename = value

    @property
    def _last_uploaded_file_bytes(self) -> Optional[bytes]:
        return current_turn().uploaded_file_bytes

    @_last_uploaded_file_bytes.setter
    def _last_uploaded_file_bytes(self, value: Optional[bytes]) -> None:
        current_turn().uploaded_file_bytes = value

    @property
    def openai_client(self):
        """Lazy OpenAI singleton for embeddings (text-embedding-3-large).

        Used by kukai.scheduling.api.build_schedule for ГЭСН RAG matching.
        Returns None if no key configured — callers must handle gracefully.
        """
        if self._openai_client is not None:
            return self._openai_client
        try:
            from openai import OpenAI as _OAI
        except ImportError:
            return None
        key = os.environ.get("KUKAI_OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
        if not key:
            return None
        self._openai_client = _OAI(api_key=key)
        return self._openai_client

    async def chat_completion(self, messages, response_format=None, max_tokens=None):
        """Adapter for kukai.scheduling.ai.dep_inferrer.apply_ai_rules.

        Returns an object with `.text` attribute (raw content string), matching
        the contract apply_ai_rules expects. Uses the same litellm.acompletion
        path as the rest of this client (Gemini primary + fallback chain).
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens or 16384,
            "stream": False,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base

        response = await self._call_llm_with_fallback(**kwargs)
        content = ""
        if response and getattr(response, "choices", None):
            content = response.choices[0].message.content or ""

        class _Resp:
            def __init__(self, t: str):
                self.text = t

        return _Resp(content)

    def set_module_registry(self, registry) -> None:
        """Inject the module registry after app startup.

        Rebuilds the tool list to include module-contributed tools.
        Also builds a handler lookup for module tool dispatch.
        """
        self._module_registry = registry
        self._tools = get_tool_definitions(module_registry=registry)
        # Build handler map: tool_name -> async handler
        self._module_handlers: dict[str, Any] = {}
        for tool_def in registry.get_all_tools():
            self._module_handlers[tool_def.name] = tool_def.handler

    def get_extension_profile(self, extension_id: str) -> str:
        """Get extension profile text by ID. Returns empty string if not found."""
        from kukai.knowledge.extensions import get_extension_profile

        return get_extension_profile(extension_id)

    def get_extensions_list(self) -> list[dict[str, str]]:
        """Get list of available extensions."""
        from kukai.knowledge.extensions import get_extensions_list

        return get_extensions_list()

    async def _call_llm_with_fallback(self, **kwargs: Any) -> Any:
        """Call the LLM with concurrency limit, circuit breaker, and automatic fallback."""
        async with self._llm_semaphore:
            return await self._call_llm_with_fallback_inner(**kwargs)

    # ── Step 3 (2026-07-04 decomposition): transport moved to
    # kukai.llm.transport — pure relocation. Bodies are byte-identical and keep
    # ``self`` as their first parameter; rebinding them as plain class
    # attributes makes them the SAME methods as before. ALL transport state
    # stays on this instance (``_circuit_breaker``, ``_provider_chain``,
    # ``_llm_semaphore``, the fallback/antigravity/google config fields), so
    # every test that constructs an LLMClient and inspects/stubs those
    # attributes is untouched. ``_call_llm_with_fallback`` (the semaphore
    # wrapper above) stays here — it is the seam tests stub.
    _OR_PROVIDER = _transport._OR_PROVIDER
    _pin_openrouter = _transport._pin_openrouter
    _provider_chain_enabled = staticmethod(_transport._provider_chain_enabled)
    _get_provider_chain = _transport._get_provider_chain
    provider_chain_health = _transport.provider_chain_health
    _call_llm_with_provider_chain = _transport._call_llm_with_provider_chain
    _do_fallback_call_chained = _transport._do_fallback_call_chained
    _call_llm_with_fallback_inner = _transport._call_llm_with_fallback_inner
    _do_fallback_call = _transport._do_fallback_call

    def _resolve_tools(self, context: Optional[ContextResult] = None) -> list[dict[str, Any]]:
        """Compute the tool list for THIS request, gated by context.

        - Without context (or project doc): returns the cached `self._tools` (no extra cost).
        - In family editor mode (is_family_editor=True): rebuilds via get_tool_definitions
          which hides project-only tools (Excel/VOR/Schedule/CAD/PDF) and adds the 10
          family_* purpose-built tools.

        Per-request rebuild is cheap (O(N) over a fixed tool list) and keeps the
        shared LLMClient instance race-free (no mutation of self._tools).
        """
        # Tool Palette v2 + per-intent masking (KUKAI_TOOLS_V2 / KUKAI_TOOL_MASKING,
        # both default OFF → resolve_tool_panel returns the base list UNCHANGED).
        from kukai.llm.tool_masking import resolve_tool_panel
        if context is None or not getattr(context, "is_family_editor", False):
            panel = resolve_tool_panel(self._tools, module_registry=self._module_registry, context=context)
        else:
            from kukai.llm.tools import get_tool_definitions
            panel = resolve_tool_panel(get_tool_definitions(module_registry=self._module_registry, context=context), module_registry=self._module_registry, context=context)
        return _inject_per_turn_tools(panel)

    # Moved to kukai.llm.loop_policy (2026-07-04 decomposition, Step 1 — pure
    # relocation). The class attributes below rebind the SAME objects so the
    # public `LLMClient._MUST_ACT_INTENTS` / `LLMClient._tool_choice_for` /
    # `LLMClient._should_dedup` surface (used by tests and the loop) is
    # unchanged. The bare names resolve to the module-level re-imports above.
    _MUST_ACT_INTENTS = _MUST_ACT_INTENTS
    _tool_choice_for = staticmethod(_tool_choice_for)
    _should_dedup = staticmethod(_should_dedup)

    async def _get_streaming_response(
        self,
        full_messages: list[dict[str, Any]],
        should_use_tools: bool,
        force_litellm: bool = False,
        on_gemini_fallback: Optional[Callable] = None,
        thinking_mode: bool = False,
        context: Optional[ContextResult] = None,
        reasoning_effort: Optional[str] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Get a streaming response from Gemini pool or litellm.

        Cascade: [V3.2 cached path] → Gemini OAuth pool → OpenRouter (litellm).
        thinking_mode=False: Flash (fast, 2-3s) → OpenRouter
        thinking_mode=True: Pro 3.1 (thinking, 20-30s) → OpenRouter
        Returns an async iterator of chunks.
        """
        # thinking_mode flows through from the caller (UI toggle / family-editor
        # auto-override). When True we select the configured thinking model
        # (self._thinking_model = settings.llm_thinking_model for the litellm leg,
        # self._gemini_pool._thinking_model for the Gemini leg) — no hardcoded
        # model id here, per the model-agnostic principle. Previously this was
        # hard-zeroed, which made the UI "thinking" toggle a no-op and ran
        # everything on the fast model.
        # ─── V3.2: Try cached-content path (family editor, feature-flagged) ──
        # When KUKAI_GEMINI_CONTEXT_CACHE_ENABLED=1 AND context is family editor,
        # we attempt a generation that references a pre-built CachedContent.
        # This saves ~75% input cost on the cached prefix (~16K tokens).
        # On ANY failure inside, we fall through silently to the regular path.
        # Flag is read directly from env so config.py schema doesn't need to
        # ship the field (avoids stomping on prod's diverged Settings schema).
        # [archived 2026-06-12] Gemini cached-content path → kukai/_archive/llm_gemini/

        # [archived 2026-06-12] Gemini OAuth pool path → kukai/_archive/llm_gemini/
        # (self._gemini_pool is always None now; admin_api still reads the attribute)

        # Fallback to litellm (OpenRouter) — match model to thinking mode
        return await self._litellm_response(full_messages, should_use_tools, thinking_mode=thinking_mode, context=context, reasoning_effort=reasoning_effort, tool_choice=tool_choice)

    async def _litellm_response(
        self,
        full_messages: list[dict[str, Any]],
        should_use_tools: bool,
        thinking_mode: bool = False,
        context: Optional[ContextResult] = None,
        reasoning_effort: Optional[str] = None,
        tool_choice: str = "auto",
    ) -> Any:
        """Get streaming response via litellm (OpenRouter etc.).

        Uses thinking_model for thinking mode, default model for fast mode.
        """
        # ── Optional Codex-subscription primary (isolated module, flag-gated) ──
        # Premium TOP layer for allow-listed devices under a per-user budget: try
        # the operator's Codex subscription (local CLIProxyAPI) FIRST; on decline
        # OR any failure fall straight through to the normal mimo path below +
        # its full existing fallback cascade (mimo stays the floor, untouched).
        # Master kill-switch: KUKAI_CODEXPROXY_ENABLED != "1" → enabled() is False →
        # this whole block is a no-op (cheap env check, zero overhead).
        # Everything Codex-specific lives in kukai/llm/codex_route.py; delete that
        # file + this block to fully undo the scheme.
        from kukai.llm import codex_route
        if codex_route.enabled():
            _cx_tools = None
            if should_use_tools:
                # Give Codex the FULL panel. Intent masking picks one toolset for the
                # whole turn from the router's first guess, but a real multi-step task
                # crosses intents ("создай спецификацию" → schedule, "выгрузи в Excel"
                # → export): by the last step the tool it needs is simply absent.
                # mimo works around a thin panel; Codex-family models stop and report
                # the step as impossible — observed live 2026-07-26 (0 tool calls,
                # 67-char answer, while the same prompt offline with all 15 tools ran
                # 4 tool rounds). Use the sanctioned per-turn unmask that
                # request_more_tools already uses; mimo turns keep masking untouched.
                try:
                    from kukai.llm.tool_masking import mark_unmasked
                    mark_unmasked()
                except Exception:  # noqa: BLE001 — panel width must never kill a turn
                    logger.debug("codex: could not unmask tool panel", exc_info=True)
                _cx_tools = self._resolve_tools(context)
            _cx = await codex_route.try_stream(
                full_messages, self._max_tokens, self._temperature,
                _cx_tools, tool_choice, _active_session_id.get(),
            )
            if _cx is not None:
                return _cx
        use_model = self._model
        # Thinking mode: prefer agy (Antigravity Pro CLI, gemini-3.5-flash) as PRIMARY.
        # Falls back to Vertex thinking model via standard fallback chain on agy error.
        use_agy_as_primary = thinking_mode and self._agy_url and self._agy_api_key
        if thinking_mode and self._thinking_model:
            use_model = self._thinking_model
        if use_agy_as_primary:
            use_model = f"openai/{self._agy_model}"
        kwargs: dict[str, Any] = {
            "model": use_model,
            "messages": full_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": True,  # agy_proxy ≥v1.1 fake-streams as single SSE chunk
            "timeout": self._agy_timeout if use_agy_as_primary else (self._thinking_timeout if thinking_mode else self._timeout),
            # Safety net: if a param is unsupported by the resolved provider,
            # litellm DROPS it (+warns) instead of raising UnsupportedParamsError.
            # Converts the whole "provider rejects a param → empty user answer"
            # failure class into graceful degradation. Propagates to every
            # fallback leg via {**kwargs}.
            "drop_params": True,
        }
        if use_agy_as_primary:
            kwargs["api_base"] = f"{self._agy_url}/v1"
            kwargs["api_key"] = self._agy_api_key
            # Pass session_id as OpenAI `user` field — agy_proxy uses it for
            # sticky per-session pinning to one of the rotated Pro accounts.
            sid = _active_session_id.get()
            if sid:
                kwargs["user"] = sid
            # Skip thinking_config — agy already handles thinking via Pro subscription
            logger.info("LLM CALL: agy (gemini-3.5-flash) via Antigravity Pro (session=%s)",
                        (sid or "ephemeral")[:8])
            return await self._call_llm_with_fallback(**kwargs)
        # Product-level mode mapping:
        #   Fast mode    → primary model (gemini-3-flash-preview), no reasoning
        #                   stream, model uses its small built-in budget only.
        #   Thinking mode → thinking model (gemini-3.5-flash) with adaptive
        #                   thinking_budget=-1 and include_thoughts so the UI
        #                   can render reasoning live, like ChatGPT o1 reveal.
        # Other providers (e.g. OpenRouter DeepSeek-R1) get the litellm-normalized
        # `thinking` param; Vertex rejects it, so we branch on model prefix.
        if thinking_mode:
            if use_model.startswith("vertex_ai/gemini-"):
                kwargs["thinking_config"] = {
                    "include_thoughts": True,
                    # -1 = dynamic budget: model scales reasoning to task
                    # complexity (trivial → ~0 thoughts, hard → up to model cap).
                    "thinking_budget": -1,
                }
            elif use_model.startswith("openrouter/"):
                # OpenRouter REJECTS the Anthropic-style `thinking` param
                # (litellm.UnsupportedParamsError: "openrouter does not support
                # parameters: ['thinking']"). It killed the primary AND every
                # fallback leg that inherited it → empty "ИИ-сервис недоступен"
                # answer (prod thinking_mode = 100% failure, 2026-06). Reasoning
                # for OpenRouter is requested via extra_body.reasoning.effort,
                # set in the `openrouter/` block below — do NOT add `thinking`.
                pass
            else:
                # Anthropic-native extended thinking (anthropic/claude-*, bedrock
                # claude, etc.) — these accept the litellm-normalized `thinking`.
                kwargs["thinking"] = {"type": "enabled", "budget_tokens": 8192}
        # Fast mode: NO thinking_config / thinking param — model answers without
        # surfacing thoughts. Built-in tiny thinking budget keeps responses snappy.
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        # OpenRouter hardening (verified live 2026-06-04, 5/5 clean): the bare
        # deepseek-v4-flash route was unstable in prod — OpenRouter sprayed
        # requests across providers (Baidu → Chinese/garbage/null) and as a
        # reasoning model it burned the whole token budget on reasoning →
        # native_finish="length" → empty content (the "mute turn" outage).
        # Fix:
        #   - pin reliable providers (allow_fallbacks keeps resilience if down),
        #   - reasoning.effort=high ('adaptive' is rejected by OpenRouter),
        #   - raise max_tokens so reasoning has headroom and never starves the
        #     answer content.
        # Reasoning is returned via reasoning_content (→ reasoning_chunk event),
        # so it is NOT leaked into the user-facing answer.
        if use_model.startswith("openrouter/"):
            # Model-aware provider + max_tokens (2026-07-07). On OpenRouter BOTH are
            # ROUTING FILTERS: OpenRouter routes only to an endpoint that serves the
            # model AND can satisfy max_tokens — a wrong provider or too-high
            # max_tokens returns "No endpoints found" = the model becomes UNCALLABLE.
            # So each model gets ITS providers + a max_tokens its endpoints serve.
            # Probed live 2026-07-07:
            #   deepseek → DeepInfra pool ($0.09/$0.18 in, 99.9% uptime), serves 32k.
            #   xiaomi/mimo-v2.5 → Xiaomi NATIVE endpoint ($0.435/$0.87, 99.88%,
            #     reliable tool-calls @16k AND @32k). DeepInfra prices MiMo ~10x higher
            #     ($1/$3, 92.6%, caps 16k) → NOT used for MiMo; AtlasCloud 404s for us.
            # allow_fallbacks stays False so a rare provider outage hard-fails to the
            # deepseek fallback tier rather than a garbage mirror (Baidu lesson).
            _reasoning = {"effort": (reasoning_effort or getattr(self, "_reasoning_effort", None) or "high")}
            if "deepseek" in use_model:
                _provider = {"order": ["DeepInfra", "Fireworks", "Parasail", "GMICloud"], "allow_fallbacks": False}
                kwargs["max_tokens"] = max(kwargs.get("max_tokens") or 0, 32768)
            else:
                # xiaomi/mimo-v2.5 provider routing. TWO hard exclusions:
                #  • Xiaomi — its native endpoint 441-blocks our whole account
                #    (2026-07-12 risk_control) → every turn hard-failed = the "hang".
                #  • DeepInfra — $2.00/Mtok output (7× the others) AND only ~20 tps, so
                #    high-effort reasoning streams painfully slowly. Dropped 2026-07-12
                #    (operator: worst tariff + slow stream).
                # Pin to the CHEAP endpoints ($0.28/Mtok out) with IN-LIST rotation:
                # DigitalOcean → Parasail → Venice. Their per-provider health FLAPS
                # (OpenRouter status 0↔-5 hour-to-hour, occasional 429), so listing 3
                # lets OpenRouter fall to the next healthy one; allow_fallbacks=False
                # keeps it OFF Xiaomi/DeepInfra. If all 3 flap down, the model-level
                # deepseek fallback catches the turn. max_tokens <= 16384 keeps
                # DigitalOcean (ctx 32000) eligible; real turns use ~2.5k completion +
                # ~1.8k reasoning tokens, so 16384 never truncates.
                _provider = {"order": ["DigitalOcean", "Parasail", "Venice"], "allow_fallbacks": False}
                kwargs["max_tokens"] = min(kwargs.get("max_tokens") or 16384, 16384)
            kwargs["extra_body"] = {"provider": _provider, "reasoning": _reasoning}
        # Plan 013 (IRON 10): ask the provider to emit a final usage-bearing
        # chunk so we can read prompt / cached / completion token counts and
        # finally populate the W4 prompt-cache telemetry columns. This is the
        # only authoritative answer to "what is the prompt cache saving". The
        # agy_proxy path fake-streams a single SSE chunk and must NOT receive
        # stream_options — it returned above. Kill-switch: KUKAI_STREAM_USAGE=0.
        if os.environ.get("KUKAI_STREAM_USAGE", "1") == "1":
            kwargs["stream_options"] = {"include_usage": True}
        if should_use_tools:
            kwargs["tools"] = self._resolve_tools(context)
            kwargs["tool_choice"] = tool_choice
        return await self._call_llm_with_fallback(**kwargs)

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        context: Optional[ContextResult] = None,
        preferences: Optional[dict[str, Any]] = None,
        units: str = "metric",
        use_tools: Optional[bool] = None,
        has_document: Optional[bool] = None,
        bridge_callback: Optional[BridgeCallback] = None,
        discovery_context: Optional[dict[str, Any]] = None,
        qa_context: Optional[dict[str, Any]] = None,
        session_state_block: str = "",
        notes_context: str = "",
        active_extension: Optional[str] = None,
        extension_profile: Optional[str] = None,
        thinking_mode: bool = False,
        model_passport: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        skill_name: str = "",
        ws_send: Any = None,
        user_tier: str = "free",
        turn_id: str = "",
        uploaded_file_bytes: Optional[bytes] = None,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a chat completion with tool calling.

        Yields StreamEvent objects for the WebSocket to forward.
        Handles multi-round tool calls (up to max_tool_rounds).

        Args:
            thinking_mode: If True, use Pro 3.1 (thinking model). If False, use Flash (fast).
            use_tools: If False, Revit tools are not sent to the LLM.
                       Defaults to bridge.connected if not specified.
            has_document: If False, adds a note to the system prompt that no
                         Revit document is open. Defaults to True if context is present.
            bridge_callback: Optional async callback for bridge operations.
                           When provided, tool execution routes through this
                           callback instead of the BridgeClient HTTP client.
                           Signature: async def(method, params) -> dict
            discovery_context: Discovery result dict from bridge with real
                             parameter names for the relevant category.
            qa_context: Optional QA/QC context dict with package name and check
                       definitions. When present, instructs the LLM to run each
                       check's C# code via execute_revit_code and compile a report.
            ws_send: WebSocket for sending file deliveries to the correct client.
                    Scoped per-call via ContextVar to prevent race conditions.
        """
        # Set per-task WebSocket reference + bind a FRESH per-turn state. Both are
        # isolated via the asyncio task context; begin_turn() always installs a new
        # TurnState so a concurrent user's data is never inherited (see turn_state.py).
        _ws_token = _active_ws.set(ws_send)
        _turn_token = begin_turn(
            revit_version=self._revit_version_default,
            uploaded_file_bytes=uploaded_file_bytes,
        )
        try:
            async for event in self._stream_chat_inner(
                messages=messages, context=context, preferences=preferences,
                units=units, use_tools=use_tools, has_document=has_document,
                bridge_callback=bridge_callback, discovery_context=discovery_context,
                qa_context=qa_context, session_state_block=session_state_block,
                notes_context=notes_context, active_extension=active_extension,
                extension_profile=extension_profile, thinking_mode=thinking_mode,
                model_passport=model_passport, skill_prompt=skill_prompt,
                skill_name=skill_name, user_tier=user_tier, turn_id=turn_id,
            ):
                yield event
        finally:
            _active_ws.reset(_ws_token)
            end_turn(_turn_token)

    async def _stream_chat_inner(
        self,
        messages: list[dict[str, Any]],
        context: Optional[ContextResult] = None,
        preferences: Optional[dict[str, Any]] = None,
        units: str = "metric",
        use_tools: Optional[bool] = None,
        has_document: Optional[bool] = None,
        bridge_callback: Optional[BridgeCallback] = None,
        discovery_context: Optional[dict[str, Any]] = None,
        qa_context: Optional[dict[str, Any]] = None,
        session_state_block: str = "",
        notes_context: str = "",
        active_extension: Optional[str] = None,
        extension_profile: Optional[str] = None,
        thinking_mode: bool = False,
        model_passport: Optional[str] = None,
        skill_prompt: Optional[str] = None,
        skill_name: str = "",
        user_tier: str = "free",
        turn_id: str = "",
    ) -> AsyncIterator[StreamEvent]:
        """Inner implementation of stream_chat (called with ContextVar already set)."""
        # Audit tracing: publish session id so deep request modules can tag
        # traces. No-op unless KUKAI_AUDIT_TRACE=1 AND the session is an
        # audit-prefixed session — production traffic is never traced.
        _audit_sid = _active_session_id.get() or ""
        audit_trace.set_session(_audit_sid)
        # Reset the per-turn intent capture fresh for THIS turn so a reused
        # asyncio task can never carry a prior turn's metadata.
        _turn_intent_metadata.set(None)
        # Extract the latest REAL user message for Wiki routing and verified-
        # recipe collection. Skip synthetic messages injected by chat_ws on retry:
        #   - "[continue from where you stopped — complete the task]"
        #     (chat_ws.py:1446, injected after silent_retry to nudge the LLM)
        #   - "[SYSTEM_AUTO_GREET]..." (initial project-description greeting)
        # Without this guard, Wiki routes the synthetic prompt (no useful
        # signal) and recipe telemetry gets polluted with continuation
        # placeholders instead of the actual user intent. Audit on 2026-05-13
        # showed 130/256 recipes (51%) were "[continue...]" placeholders.
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            if "continue from where you stopped" in content:
                continue
            if content.lstrip().startswith("[SYSTEM_AUTO_GREET]"):
                continue
            user_message = content
            break

        # One authoritative switch controls Revit knowledge for this turn.
        # Wiki is the only automatic corpus.
        _knowledge_mode = knowledge_mode()

        # Update Revit version from context (used in repair loop)
        if context and context.document and context.document.revit_version:
            self._revit_version = context.document.revit_version

        # Phase 7.2: optional request-level intent classification.
        # Best-effort. Flags default OFF (see kukai/config.py AGENT_USE_*).
        # On any agent failure, the deterministic Wiki router remains available.
        # NOTE: intent_metadata MUST be a local — LLMClient is a process-wide
        # singleton shared across all WebSocket sessions. Storing as self.*
        # would let concurrent requests cross-contaminate intent context.
        agent_intent_metadata: dict | None = None
        try:
            from kukai import config as _kcfg
            if user_message and _kcfg.AGENT_USE_INTENT_CLASSIFIER:
                import asyncio as _asyncio
                tasks = []
                slot_names = []
                if _kcfg.AGENT_USE_INTENT_CLASSIFIER:
                    async def _classify():
                        try:
                            from kukai.agents.intent_classifier import IntentClassifier
                            from kukai.agents.base import AgentError
                            ic = IntentClassifier()
                            return await ic.run(query=user_message, timeout=6.0)
                        except Exception as _e:  # noqa: BLE001
                            return _e
                    tasks.append(_classify())
                    slot_names.append("classifier")
                preflight_results = await _asyncio.gather(*tasks)
                for name, res in zip(slot_names, preflight_results):
                    if isinstance(res, Exception):
                        logger.info("agent pre-flight %s failed: %s", name, res)
                        continue
                    if name == "classifier":
                        agent_intent_metadata = res.value
                        logger.info("agent intent: %s", res.value)
        except Exception as e:  # noqa: BLE001
            logger.info("agent pre-flight import/setup failed: %s", e)

        # plan-019: stash per-turn intent so the capture site
        # (_execute_tool → record_verified_recipe) can read it without widening
        # _execute_tool's signature. Task-scoped ContextVar — never store on
        # self (a singleton — see the cross-tenant note above).
        _turn_intent_metadata.set(agent_intent_metadata)

        # ── KUKAI_PREFLIGHT_V2: launch the router's IntentClassifier leg NOW,
        # so it runs concurrently with local Wiki prompt assembly instead of
        # serially after it (the inline call at the router site is
        # a real LLM round-trip in prod — DeepSeek-homed, 6s cap — because the
        # pre-flight stage is off and agent_intent_metadata is None every turn).
        # Launch condition mirrors the router site exactly: ROUTER on +
        # treatment + no pre-flight metadata. The task NEVER raises (wrapped);
        # its result feeds ONLY the router's overlay — never
        # _turn_intent_metadata / telemetry — identical to today's inline call.
        # Flag OFF ⇒ this whole block is three no-op locals.
        _pf2_on = _preflight_v2_enabled()
        _pf2_intent_task: Optional[asyncio.Task] = None
        _pf2_intent_t0 = 0.0
        _pf2_intent_deadline = _pf2_deadline("KUKAI_INTENT_DEADLINE_S", 6.0)
        if _pf2_on and agent_intent_metadata is None and user_message:
            try:
                from kukai import config as _kcfg_pf2
                from kukai.agents.rollout import in_treatment as _in_treat_pf2
                _pf2_treat = (
                    _kcfg_pf2.AGENT_TEST_PERCENT >= 100
                    or _in_treat_pf2(_audit_sid, _kcfg_pf2.AGENT_TEST_PERCENT)
                    or str(_audit_sid).startswith("audit-")
                )
                if bool(_kcfg_pf2.AGENT_USE_ROUTER) and _pf2_treat:
                    async def _pf2_run_intent():
                        try:
                            from kukai.agents.intent_classifier import IntentClassifier
                            return await IntentClassifier().run(
                                query=user_message, timeout=_pf2_intent_deadline,
                            )
                        except Exception:  # noqa: BLE001 — same fail-open as inline
                            return None
                    _pf2_intent_task = asyncio.create_task(_pf2_run_intent())
                    _pf2_intent_t0 = time.monotonic()
            except Exception:  # noqa: BLE001 — never block the turn; router falls back inline
                _pf2_intent_task = None

        # W1-A (2026-07-10, /root/kukai-rag-audit/SPEC_W1A_single_classify.md):
        # bridge the pf2 IntentClassifier's result into the wiki-router adapter
        # as a threaded frame, so build_prompt_components (below, run inside
        # asyncio.to_thread) does not pay for its OWN second, serial classify
        # call. concurrent.futures.Future (not asyncio.Future) — the consumer
        # runs in a worker thread with no running event loop
        # (prompts.py::build_prompt_components), so it needs a Future it can
        # block on with .result(timeout=...) from off the event loop; the
        # producer side (this done-callback) runs ON the event loop via
        # asyncio.Task.add_done_callback. Only created when the wiki router is
        # actually active.  A completed regular pre-flight classifier result is
        # converted immediately; otherwise a launched pf2 task resolves it. If
        # neither exists, the Wiki router uses its deterministic evidence index
        # and never starts a second classifier call. The callback body
        # is fully fail-open: any exception resolves the future to None rather
        # than propagating into the event loop or leaving it unset (which
        # would hang the consumer's bounded .result(timeout=...) wait).
        _wiki_frame_future: Optional[concurrent.futures.Future] = None
        if _knowledge_mode is KnowledgeMode.WIKI and (
            agent_intent_metadata is not None or _pf2_intent_task is not None
        ):
            try:
                _wiki_frame_future = concurrent.futures.Future()

                if agent_intent_metadata is not None:
                    from kukai.rag.wiki_router.adapter import frame_from_classifier_value
                    _wiki_frame_future.set_result(
                        frame_from_classifier_value(agent_intent_metadata)
                    )

                def _pf2_to_wiki_frame(task: "asyncio.Task", _fut=_wiki_frame_future) -> None:
                    try:
                        val = getattr(task.result(), "value", None)
                        from kukai.rag.wiki_router.adapter import frame_from_classifier_value
                        _fut.set_result(
                            frame_from_classifier_value(val) if isinstance(val, dict) else None)
                    except Exception:  # noqa: BLE001 — fail-open, never raise into the event loop
                        try:
                            _fut.set_result(None)
                        except Exception:  # noqa: BLE001 — already resolved/cancelled, ignore
                            pass
                if _pf2_intent_task is not None and not _wiki_frame_future.done():
                    _pf2_intent_task.add_done_callback(_pf2_to_wiki_frame)
            except Exception:  # noqa: BLE001 — deterministic Wiki routing remains available
                _wiki_frame_future = None

        # Fix 1 (KUKAI_CONVERSE_FASTPATH): a converse turn (smalltalk/help) needs no
        # knowledge injection or tools — skip Wiki prep and build a LEAN
        # prompt so the FIRST TOKEN comes ~instantly. Resolve the intent within a short
        # deadline (reuse the concurrent PF2 classifier when it launched one; else a
        # bounded classify; else quick_classify), and FAIL-OPEN to the full path on any
        # miss/timeout — a wrong fast-path would strip enrichment from a real task.
        _fastpath = False
        if (os.environ.get("KUKAI_CONVERSE_FASTPATH", "0") == "1"
                and user_message and self._prompt_assembler):
            # Latency-safe intent resolution. quick_classify (microseconds) catches
            # greeting-converse outright. Otherwise: an ACTION-verb turn (the bulk —
            # every "найди/вставь/сравни/создай") is definitely NOT converse, so we
            # skip the slow LLM classifier entirely (ZERO added latency). ONLY a
            # no-action-verb turn (a possible "ты как?" smalltalk the rules default to
            # "modify") is worth confirming with the classifier, within a short
            # deadline; fail-open to the full path on timeout/miss.
            _fp_hav = None
            try:
                from kukai.agents.intent_rules import (
                    quick_classify as _fp_qc, _has_action_verb as _fp_hav)
                _fp_meta = _fp_qc(user_message)
            except Exception:  # noqa: BLE001
                _fp_meta = None
            if _fastpath_intent_gate(_fp_meta):
                _fastpath = True
            elif _fp_hav is not None:
                try:
                    _has_verb = _fp_hav(user_message)
                except Exception:  # noqa: BLE001
                    _has_verb = True
                if not _has_verb:
                    try:
                        _fp_dl = float(os.environ.get("KUKAI_INTENT_DEADLINE_S", "0.4"))
                    except (ValueError, TypeError):
                        _fp_dl = 0.4
                    try:
                        if _pf2_intent_task is not None:
                            _fp_r = await asyncio.wait_for(
                                asyncio.shield(_pf2_intent_task), _fp_dl)
                        else:
                            from kukai.agents.intent_classifier import IntentClassifier as _FPIC
                            _fp_r = await asyncio.wait_for(_FPIC().run(user_message), _fp_dl)
                        if _fp_r is not None and getattr(_fp_r, "value", None):
                            _fastpath = _fastpath_intent_gate(_fp_r.value)
                    except Exception:  # noqa: BLE001 — slow/failed ⇒ fail-open (full path)
                        pass
            if _fastpath:
                global _FASTPATH_TAKEN_COUNT
                _FASTPATH_TAKEN_COUNT += 1
                logger.info("CONVERSE FASTPATH: lean prompt, retrieval skipped")

        # Wiki consumes the original user text.  There is deliberately no
        # translation, expansion, vector search, rerank or retrieval carry-over
        # between intent resolution and prompt assembly.
        audit_trace.trace(_audit_sid, "translate", {
            "orig": user_message[:160], "en": "", "changed": False,
            "via": "wiki_original_text",
            "knowledge_mode": _knowledge_mode.value,
        })

        # Build the system prompt. Wiki always receives the original message.
        #
        # build_system_prompt is fully synchronous but does blocking I/O deep
        # inside it (Wiki parsing and the independently scoped norms source).
        # Keep it in a worker thread so filesystem work cannot stall the event
        # loop for other connected users. asyncio.to_thread copies contextvars.
        # Plan 013: layered cacheable prompt assembly (flag KUKAI_PROMPT_LAYERED,
        # default OFF → byte-identical legacy path). When OFF, the whole system
        # prompt + the four per-turn suffixes go into messages[0] as today. When
        # ON, only the STABLE components form messages[0] (the cacheable prefix);
        # the PER_TURN components + the four suffixes are appended as ONE trailing
        # system message AFTER the history (mimicking the four proven
        # trailing-message sites already in this file / chat_ws.py), so the first
        # per-query byte no longer invalidates the provider cache for the history.
        _layered = False
        try:
            from kukai.config import get_settings as _gs_pl
            _settings_pl = _gs_pl()
            _layered_env = os.getenv("KUKAI_PROMPT_LAYERED")
            if _layered_env is not None:
                _layered = _layered_env.strip().lower() in {
                    "1", "true", "on", "yes",
                }
            else:
                _layered = bool(getattr(_settings_pl, "prompt_layered", False))
        except Exception:
            _layered = os.getenv("KUKAI_PROMPT_LAYERED", "0").strip().lower() in {
                "1", "true", "on", "yes",
            }

        system_prompt = ""
        _assembled = None  # plan-013 AssembledPrompt (layered path only)
        _per_turn_block = ""  # plan-013 PER_TURN components (layered path only)
        if self._prompt_assembler:
            if _layered:
                _assembled = await asyncio.to_thread(
                    self._prompt_assembler.build_prompt_components,
                    context=context, preferences=preferences, units=units,
                    user_message=user_message,
                    user_message_original=user_message,
                    discovery_context=discovery_context,
                    extension_profile=extension_profile,
                    active_extension=active_extension,
                    model_passport=model_passport,
                    skill_prompt=skill_prompt,
                    skill_name=skill_name,
                    wiki_frame_future=_wiki_frame_future,
                    **({"skip_enrichment": True} if _fastpath else {}),
                )
                _assembled = _drop_conflicting_components(_assembled)
                system_prompt = _assembled.stable
                _per_turn_block = _assembled.per_turn
                # Per-component breakdown + stable-prefix churn watchdog (IRON 10).
                # Guarded — telemetry must never throw into the hot path.
                try:
                    _bd = _assembled.breakdown()
                    logger.info(
                        "prompt-breakdown: %s",
                        json.dumps(_bd, ensure_ascii=False),
                    )
                except Exception as _bd_exc:
                    from kukai.telemetry import note_telemetry_failure
                    note_telemetry_failure(_bd_exc)
            else:
                # Single-layer path — byte-for-byte the pre-013 prompt layout.
                system_prompt = await asyncio.to_thread(
                    self._prompt_assembler.build_system_prompt,
                    context=context, preferences=preferences, units=units,
                    user_message=user_message,
                    user_message_original=user_message,
                    discovery_context=discovery_context,
                    extension_profile=extension_profile,
                    active_extension=active_extension,
                    model_passport=model_passport,
                    skill_prompt=skill_prompt,
                    skill_name=skill_name,
                    wiki_frame_future=_wiki_frame_future,
                    **({"skip_enrichment": True} if _fastpath else {}),
                )

        # The four per-turn suffixes (session state, user notes, no-doc note,
        # QA/QC checks) are VOLATILE — they belong to this turn only. Plan 013:
        # accumulate them into a separate string built with the SAME
        # concatenation as before, so the legacy path stays byte-identical
        # (system_prompt += _per_turn_suffix at the end) while the layered path
        # routes them into the trailing per-turn message instead of the cacheable
        # messages[0] prefix.
        _per_turn_suffix = ""

        if session_state_block:
            _per_turn_suffix += "\n\n" + session_state_block

        # Inject user notes as soft context (AI should reference if relevant, not execute blindly)
        if notes_context:
            _per_turn_suffix += "\n\n## Заметки пользователя (справочно, не выполнять автоматически)\n" + notes_context

        # If no document is open, tell the LLM it can only answer general questions
        if has_document is False:
            no_doc_note = (
                "\n\n## IMPORTANT: No Revit document is currently open.\n"
                "You can only answer general questions about Revit, BIM, and architecture.\n"
                "Do NOT attempt to use any Revit tools (execute_revit_code, get_model_info, "
                "select_elements, highlight_elements) — they will fail.\n"
                "If the user asks something that requires a Revit document, "
                "politely ask them to open a project first."
            )
            _per_turn_suffix += no_doc_note

        # QA/QC mode: inject instructions to run predefined checks
        if qa_context:
            package = qa_context.get("package", "standard")
            checks = qa_context.get("checks", [])
            qa_instructions = (
                f"\n\n## QA/QC MODE — \"{package}\" package\n"
                "The user requested a model quality check. You MUST execute each check below "
                "using the `execute_revit_code` tool, one at a time. After all checks complete, "
                "compile a structured report in Russian with the results.\n\n"
                "Checks to run:\n"
            )
            for i, check in enumerate(checks, 1):
                qa_instructions += (
                    f"\n### Check {i}: {check['name']} ({check['severity']})\n"
                    f"Description: {check['description']}\n"
                    f"Code to execute:\n```csharp\n{check['code']}\n```\n"
                )
            qa_instructions += (
                "\nFor each check, call `execute_revit_code` with the code above. "
                "After all results are collected, present a summary report with:\n"
                "- Total checks run\n"
                "- Errors, warnings, and info counts\n"
                "- Details for each check result\n"
            )
            _per_turn_suffix += qa_instructions

        # LEGACY path: the per-turn suffixes are concatenated onto messages[0]
        # exactly as before (byte-identical). LAYERED path: they are deferred to
        # the trailing per-turn message built after the history below.
        if not _layered:
            system_prompt += _per_turn_suffix

        # Prepend system message
        full_messages: list[dict[str, Any]] = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        # LAYERED path: append ONE trailing system message carrying all the
        # PER_TURN prompt components + the four per-turn suffixes, AFTER the
        # history (so they cost only themselves and never pollute the cacheable
        # history prefix). This is exactly the trailing-message pattern the
        # grounding-gate / query-semantic / EN-interpretation sites already use.
        if _layered:
            _trailing = "\n\n".join(p for p in (_per_turn_block, _per_turn_suffix.strip()) if p)
            if _trailing:
                full_messages.append({"role": "system", "content": _trailing})

        # ── Golden-path C1 (2026-07-13): the ROUND-LOOP INIT block that lived
        # here (counters, budgets, M2 router/convergence overrides, truth-gate
        # bookkeeping, wall-clock budgets) moved VERBATIM to _init_round_state
        # (defined right after this generator). Every loop-carried local is now
        # ONE explicit RoundState value — the round loop below reads/writes it
        # as `state.*`; round-LOCAL state stays in plain locals inside the loop.
        state = await self._init_round_state(
            full_messages=full_messages,
            context=context,
            skill_prompt=skill_prompt,
            user_message=user_message,
            agent_intent_metadata=agent_intent_metadata,
            _audit_sid=_audit_sid,
            _pf2_intent_task=_pf2_intent_task,
            _pf2_intent_deadline=_pf2_intent_deadline,
            _pf2_intent_t0=_pf2_intent_t0,
        )

        # Turn-level budget for re-nudging the model after an unrecoverable
        # tool-call leak (bounded so a persistently-mangling provider can't loop).
        _leak_retries = 0
        _plan_continues = 0
        # On the Codex route the whole answer arrives at once (that path is
        # non-streaming), so nothing is lost by holding the text until the round
        # ends — and it buys the ability to DROP a draft. Without this the user
        # watches "Сделаю в 1 шаг…", then "Сделаю в 2 шага…", then the real answer:
        # every plan the harness rejected is already on screen, so a run that was
        # methodical underneath reads as the model flailing.
        # DISABLED 2026-07-27 after it ate a real answer: the flush I added sits
        # inside the `if has_content:` completion branch, and buffering keeps
        # has_content False — so the branch never ran and a 697-char reply reached
        # the user as 0 chars. The draft-suppression it bought is cosmetic; losing
        # answers is not. Re-enable only together with moving the flush out of that
        # branch (`if has_content or _held_text:`) and a test that asserts a
        # tool-less answer still reaches the client.
        _buffer_text = False
        _held_text: list[str] = []
        _MAX_PLAN_CONTINUES = int(os.getenv("KUKAI_PLAN_CONTINUE_MAX", "3"))
        # ── look at what you built before saying you are done ────────────────
        # Witnesses answer "did it land, how many, where" — they cannot answer
        # "is this what was asked for". The Eiffel run made that concrete: 48
        # beams, every witness green, and a silhouette that is not the tower.
        # So a turn that CHANGED the model does not get to finish on its own
        # word: it gets handed a picture of the result and has to look before it
        # is allowed to end. Bounded — it is a check, not a rabbit hole.
        _wrote_this_turn = False
        # A fresh slate per turn: last turn's building must not be
        # reviewed against this turn's work.
        from kukai.design import review as _kir_review
        _kir_review.reset()
        _self_checks = 0
        _reviews = 0
        _bridge_silent = 0
        _size_before: Optional[int] = None
        _MAX_SELF_CHECKS = int(os.getenv("KUKAI_SELFCHECK_MAX", "2"))
        while state.tool_round < state.effective_max_rounds:
            # Harness guarantee: if the whole turn exceeds its budget, stop and
            # synthesize an answer from what we have (covers slow tools + loops).
            if state.conv_on and (time.monotonic() - state.turn_start) > state.TURN_BUDGET_S:
                logger.warning("Turn budget %.0fs exceeded — forcing synthesis", state.TURN_BUDGET_S)
                async for _ev in self._forced_synthesis(state.full_messages, context):
                    yield _ev
                break
            # Include tools when bridge is connected and document is open.
            # use_tools overrides the default bridge.connected check.
            # Always enable tools — some tools (price_vor, lookup_gesn, generate_report)
            # work without Revit. Bridge-dependent tools handle missing bridge internally.
            should_use_tools = use_tools if use_tools is not None else True
            if state.route is not None and state.route.use_tools_override is False:
                should_use_tools = False  # router: converse → answer directly, no tools
                # …unless the user just said "делай" to an action the assistant had
                # proposed. The router sees one bare word, calls it chit-chat and
                # strips every tool, so the turn CANNOT act however willing the model
                # is — it can only answer "запись в модель недоступна", which reads as
                # a permissions failure and traps the user in a loop: propose → "делай"
                # → "недоступно" (observed live 2026-07-26 on «делай», «давай», «ну»,
                # «а щас»). Attaching tools never forces their use, so a genuine
                # chit-chat "да" loses nothing. Kill-switch: KUKAI_GOAHEAD_KEEPS_TOOLS=0.
                if os.environ.get("KUKAI_GOAHEAD_KEEPS_TOOLS", "1") == "1" and (
                    _is_go_ahead(state.full_messages) or _is_keep_going(state.full_messages)
                ):
                    should_use_tools = use_tools if use_tools is not None else True
                    logger.info("router said converse, but the turn is a go-ahead — keeping tools")

            try:
                has_content = state.carry_bubble  # carry open bubble across continuations
                collected_text = ""
                last_finish: Optional[str] = None
                tool_calls_accumulator: dict[int, dict[str, Any]] = {}
                # 2026-07-12: a provider serving MiMo sometimes fails to translate
                # the model's own native tool-call syntax into the structured
                # `tool_calls` field, leaking it into `delta.content` as raw text
                # instead (confirmed live: `<｜DSML｜tool_calls>...` + full C#
                # dumped into chat, nothing executed). Guard every content delta
                # through the shared gate before it reaches the user.
                _leak_guard_state = LeakGuardState()
                _leak_guard_recovered_idx = -1
                # A tool-call-shaped leak this round that could NOT be recovered
                # (unclosed/unparseable markup → dropped). It means the model
                # INTENDED a tool call but the provider mangled its syntax so we
                # lost it — the call never executed (live 2026-07-16: import_cad
                # vanished this way). Instead of ending the turn empty, nudge the
                # model to re-emit it as a structured call. Bounded by leak_retries.
                _leak_dropped_call = False

                # --- Choose provider: Gemini OAuth pool → litellm (OpenRouter) ---
                # C1: was a `nonlocal _gemini_failed_mid_stream` closure — the flag
                # now lives on RoundState; same one-way latch, same call sites.
                def _mark_gemini_failed():
                    state.gemini_failed_mid_stream = True

                # H2: force a tool call on the first round of an action intent so
                # the model can't narrate a plan and stop; 'auto' afterwards.
                _tool_choice = self._tool_choice_for(
                    getattr(state.route, "intent", None) if state.route is not None else None,
                    state.tool_round,
                    should_use_tools,
                )
                # Step 8 (KUKAI_TRUTH_GATE=enforce): the ONE corrective round after
                # a fake-готово detection must actually produce a tool call — same
                # forcing verb _tool_choice_for uses on round 0. One-shot: the
                # override consumes itself, so it can never force a later round.
                # Flag OFF → _truth_force_required is always False (byte-identical).
                if state.truth_force_required:
                    _tool_choice = "required"
                    state.truth_force_required = False
                response = await self._get_streaming_response(
                    state.full_messages, should_use_tools,
                    force_litellm=state.gemini_failed_mid_stream,
                    on_gemini_fallback=_mark_gemini_failed,
                    thinking_mode=thinking_mode,
                    context=context,
                    reasoning_effort=state.reasoning_effort_override,
                    tool_choice=_tool_choice,
                )

                reasoning_active = False

                async for chunk in response:
                    if chunk.choices and chunk.choices[0].finish_reason:
                        last_finish = chunk.choices[0].finish_reason
                    # Plan 013 (IRON 10): the usage-bearing final chunk (from
                    # stream_options.include_usage) has empty choices → delta is
                    # None → it would be dropped by the short-circuit below. Read
                    # it FIRST and emit an internal "usage" event for the chat_ws
                    # loop to fold into the W4 telemetry columns. Never throws.
                    try:
                        _usage = _extract_usage(chunk)
                    except Exception:
                        _usage = None
                    if _usage is not None:
                        yield StreamEvent("usage", _usage)
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue

                    # Reasoning/thinking content (from reasoning models like MiMo, DeepSeek-R1)
                    reasoning_text = getattr(delta, 'reasoning_content', None) or ""
                    if not reasoning_text:
                        # OpenRouter uses reasoning_details array
                        details = getattr(delta, 'reasoning_details', None)
                        if details and isinstance(details, list):
                            reasoning_text = "".join(
                                d.get("text", "") if isinstance(d, dict) else str(d)
                                for d in details
                            )
                    if reasoning_text:
                        if not reasoning_active:
                            yield StreamEvent("reasoning_start")
                            reasoning_active = True
                        yield StreamEvent("reasoning_chunk", reasoning_text)

                    # Text content — routed through the leak guard first (see
                    # _leak_guard_state above). Normal text is untouched (fast
                    # path, no regex): the events list is a single passthrough
                    # equal to delta.content itself in that case.
                    if delta.content:
                        for _ev in guard_delta(_leak_guard_state, delta.content):
                            if _ev.passthrough:
                                if reasoning_active:
                                    yield StreamEvent("reasoning_end")
                                    reasoning_active = False
                                if _buffer_text:
                                    _held_text.append(_ev.passthrough)
                                    collected_text += _ev.passthrough
                                else:
                                    if not has_content:
                                        yield StreamEvent("stream_start")
                                        has_content = True
                                    yield StreamEvent("stream_chunk", _ev.passthrough)
                                    collected_text += _ev.passthrough
                            elif _ev.resolved_call is not None:
                                # A leaked tool call was recovered — inject it as
                                # if it had arrived via the native tool_calls
                                # field, so the existing execution pipeline below
                                # runs completely unchanged.
                                tool_calls_accumulator[_leak_guard_recovered_idx] = {
                                    "id": f"recovered_leak_{-_leak_guard_recovered_idx}",
                                    "function": {
                                        "name": _ev.resolved_call["name"],
                                        "arguments": _ev.resolved_call["arguments"],
                                    },
                                }
                                _leak_guard_recovered_idx -= 1
                                logger.warning(
                                    "TOOL CALL LEAK recovered: name=%s (provider leaked native "
                                    "tool-call syntax into content instead of the tool_calls field)",
                                    _ev.resolved_call["name"],
                                )
                            elif _ev.dropped:
                                _leak_dropped_call = True
                                logger.warning(
                                    "TOOL CALL LEAK dropped: unrecognized/unclosed leaked markup "
                                    "in delta.content — suppressed instead of shown raw"
                                )

                    # Tool calls (accumulated from chunks) — C1: fold moved
                    # verbatim to _accumulate_tool_call_delta (module level).
                    if delta.tool_calls:
                        _accumulate_tool_call_delta(tool_calls_accumulator, delta.tool_calls)

                # Process accumulated tool calls
                if tool_calls_accumulator:
                    # End any ongoing reasoning/text stream before tool execution
                    if reasoning_active:
                        yield StreamEvent("reasoning_end")
                        reasoning_active = False
                    if has_content:
                        yield StreamEvent("stream_end")
                        has_content = False

                    # Add assistant message with tool calls to history — C1:
                    # dict built verbatim by _build_assistant_tool_msg (module level).
                    assistant_msg: dict[str, Any] = _build_assistant_tool_msg(
                        collected_text, tool_calls_accumulator)
                    state.full_messages.append(assistant_msg)

                    # Execute each tool call
                    for tc_data in tool_calls_accumulator.values():
                        tool_name = tc_data["function"]["name"]
                        tool_call_id = tc_data["id"]

                        yield StreamEvent("tool_start", tool_name)
                        state.turn_tool_calls_total += 1  # Step 8: turn-level issue count
                        try:
                            _log_keys = list(json.loads(tc_data["function"]["arguments"] or "{}").keys()) if tc_data["function"]["arguments"] else []
                        except Exception:  # malformed args must not kill the turn — the guarded parse below returns a typed error to the model
                            _log_keys = ["<malformed-json>"]
                        logger.info("TOOL CALL: %s, args_keys=%s", tool_name, _log_keys)
                        audit_trace.trace(_audit_sid, "tool", {
                            "name": tool_name, "round": state.tool_round,
                            "args": str(tc_data["function"]["arguments"])[:1500],
                        })

                        # Bind per-iteration so the structure-first is_error check
                        # below can't read a stale dict from a previous tool call on
                        # the except paths (where the call raised before assigning).
                        tool_result: Any = None
                        try:
                            args_str = tc_data["function"]["arguments"]
                            try:
                                tool_args = json.loads(args_str) if args_str else {}
                            except json.JSONDecodeError as je:
                                logger.warning("Tool %s: malformed JSON args: %s", tool_name, je)
                                result_str = json.dumps({
                                    "error": True,
                                    "message": f"Malformed tool arguments: {je}",
                                })
                                # Count malformed-args failures in the per-tool error
                                # counter — the most common weak-model failure must not
                                # be invisible to the loop's only retry discipline.
                                _malformed_content = result_str
                                if _bump_tool_error(state.consecutive_errors, tool_name):
                                    _malformed_content = json.dumps({
                                        "error": True,
                                        "message": (
                                            result_str[:500] +
                                            "\n\n[SYSTEM: This tool has failed 3 times in a row. "
                                            "Do NOT retry. Instead: explain the error to the user, "
                                            "suggest a different approach, or break the task into smaller steps.]"
                                        ),
                                    })
                                yield StreamEvent("tool_end", {"tool": tool_name, "result": result_str, "arguments": "{}"})
                                state.full_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": _malformed_content,
                                    "_tool_name": tool_name,
                                })
                                continue
                            # M2 dedup (error-aware): skip a repeat of a tool call
                            # that already ran AND SUCCEEDED this turn. A prior error
                            # → legit retry, allow it. All tools (Fable review):
                            # prevents duplicate writes AND unblocks failed retries.
                            # _sig is recorded ok/errored after execution below.
                            _sig = None
                            if state.conv_on:
                                _sig = _dedup_signature(tool_name, args_str)
                                state.seen_tool_sigs[_sig] = state.seen_tool_sigs.get(_sig, 0) + 1
                                if self._should_dedup(state.seen_tool_sigs[_sig], _sig in state.errored_sigs):
                                    state.dedup_count += 1
                                    _nudge = json.dumps({"error": False, "deduped": True, "message": (
                                        "[SYSTEM: Этот инструмент уже вызывался с такими же аргументами "
                                        "в этом запросе. НЕ повторяй его. Сформулируй ответ из уже "
                                        "полученных данных; если их не хватает — вызови ДРУГОЙ инструмент "
                                        "или ответь пользователю.]")}, ensure_ascii=False)
                                    yield StreamEvent("tool_end", {"tool": tool_name, "result": _nudge, "arguments": args_str})
                                    state.full_messages.append({"role": "tool", "tool_call_id": tool_call_id,
                                                          "content": _nudge, "_tool_name": tool_name})
                                    continue
                            if state.conv_on:
                                # Per-tool wall cap so one slow tool can't block the
                                # turn-deadline (audit_model ran 496s). Abort → tell the
                                # model to answer from what it has; do NOT crash/retry.
                                # Step 7 (KUKAI_EXEC_PIPELINE): for execute_revit_code the
                                # cap is derived from the SAME TurnBudget the pipeline
                                # enforces internally (+slack) — the flat 90s strangled the
                                # 120-360s execute tiers and manufactured running_unconfirmed
                                # for every legitimate heavy write. Flag OFF → 90s unchanged.
                                _tool_cap_s = state.TOOL_BUDGET_S
                                if (
                                    tool_name == "execute_revit_code"
                                    and _exec_pipeline_active()
                                ):
                                    try:
                                        from kukai.llm.revit_execution_pipeline import (
                                            compute_tool_budget_s,
                                        )
                                        _tool_cap_s = compute_tool_budget_s(tool_args)
                                    except Exception:  # noqa: BLE001 — budget calc must never kill a turn
                                        _tool_cap_s = state.TOOL_BUDGET_S
                                try:
                                    tool_result = await asyncio.wait_for(
                                        self._execute_tool(
                                            tool_name, tool_args, bridge_callback,
                                            active_extension=active_extension,
                                            user_query=user_message,
                                            system_context=system_prompt,
                                            user_tier=user_tier,
                                            turn_id=turn_id,
                                            tool_call_id=tool_call_id,
                                        ),
                                        timeout=_tool_cap_s)
                                except asyncio.TimeoutError:
                                    # bridge-truth: the Python wait_for timed out, but the C# on
                                    # the Revit side may STILL be executing (and a write may still
                                    # commit). The harness has NO real cancellation here, so the
                                    # old "и прерван" (aborted) text was a lie the model acted on.
                                    # Report honest running_unconfirmed semantics: completion could
                                    # not be confirmed — do NOT assume it was aborted, and do NOT
                                    # blindly re-issue a write. Non-blocking (error: False stays).
                                    logger.warning(
                                        "Tool %s exceeded %.0fs — completion unconfirmed (convergence); "
                                        "C# may still be running", tool_name, _tool_cap_s)
                                    tool_result = attach_err(
                                        {
                                            "error": False,
                                            "tool_timeout": True,
                                            "state": "running_unconfirmed",
                                            "message": (
                                                f"[SYSTEM: инструмент '{tool_name}' не уложился в "
                                                f"{int(_tool_cap_s)}с. Выполнение НЕ подтверждено и НЕ отменено — "
                                                "операция в Revit могла продолжиться и даже завершиться/закоммититься. "
                                                "НЕ считай, что она прервана; НЕ повторяй вслепую запись (write). "
                                                "Сначала ПРОВЕРЬ состояние модели; затем сформулируй ответ из уже "
                                                "собранных данных или предложи сузить запрос.]")
                                        },
                                        ErrCode.TRANSPORT_TOOL_BUDGET_EXCEEDED,
                                    )
                            else:
                                tool_result = await self._execute_tool(
                                    tool_name, tool_args, bridge_callback,
                                    active_extension=active_extension,
                                    user_query=user_message,
                                    system_context=system_prompt,
                                    user_tier=user_tier,
                                    turn_id=turn_id,
                                    tool_call_id=tool_call_id,
                                )
                            # Budget block — C1: comment + setdefault moved
                            # verbatim to _attach_round_budget (module level).
                            if isinstance(tool_result, dict):
                                _attach_round_budget(state, tool_result)
                            result_str = json.dumps(tool_result, ensure_ascii=False, default=str)
                        except BridgeError as e:
                            # `tool_result` is NOT in scope on this except path (the call
                            # raised); build the dict, add the machine-readable err +
                            # budget, then serialize. Legacy keys (error/code/message/data)
                            # are preserved exactly.
                            _bridge_err = attach_err(
                                {
                                    "error": True,
                                    "code": e.code,
                                    "message": e.error_message,
                                    "data": e.data,
                                },
                                classify_bridge_error(e.error_message),
                                cs_codes=extract_cs_codes(e.error_message or ""),
                            )
                            _attach_round_budget(state, _bridge_err)
                            result_str = json.dumps(_bridge_err, default=str)
                        except Exception as e:
                            logger.exception("Tool execution error: %s", tool_name)
                            _exc_err = attach_err(
                                {
                                    "error": True,
                                    "message": str(e),
                                },
                                ErrCode.INTERNAL_UNHANDLED,
                            )
                            _attach_round_budget(state, _exc_err)
                            result_str = json.dumps(_exc_err, default=str)

                        # Track consecutive errors to prevent retry loops.
                        # Structure-first: prefer the typed `error is True` flag on the
                        # dict; fall back to the substring scan because the except
                        # branches stringify before this point (tool_result not in scope
                        # there) and some handlers stringify early.
                        # `result_is_error` widens the old `error is True` rule to
                        # the typed refusals KUKAI actually emits (`ok: false`,
                        # `refused: true`, string `error`). Before it, a refused
                        # KIR write folded into the turn as a SUCCESS — measured
                        # live on the tower run 29.07.
                        is_error = (
                            result_is_error(tool_result)
                            or '"error": true' in result_str
                            or '"error":true' in result_str
                        )
                        audit_trace.trace(_audit_sid, "tool_result", {
                            "name": tool_name, "ok": not is_error,
                            "result": result_str[:1500],
                        })
                        # Step 8 Tier-1 (truth gate): every tool result the model saw
                        # this turn is a claim WITNESS — error results too (a number
                        # echoed from an error text is echoed, not fabricated). Pure
                        # bookkeeping; capped so a pathological result can't balloon.
                        state.truth_witness_parts.append(result_str[:200_000])
                        if is_error:
                            if _sig is not None:
                                state.errored_sigs.add(_sig)  # last identical call failed → allow a retry
                            # A SILENT bridge is not a tool failure — it is the
                            # whole device not answering, and retrying costs the
                            # full bridge timeout every time. Measured live on
                            # 2026-07-29: six executes in a row, 40 s each, all
                            # unanswered, and the user sat through 10.5 minutes
                            # of nothing before writing "завис". The per-tool
                            # 3-strike hint could not help — by the time it fires
                            # two minutes of silence are already spent, and the
                            # hint tells the model to try something ELSE, when
                            # nothing at all can reach Revit.
                            if _looks_like_a_silent_bridge(result_str):
                                _bridge_silent += 1
                                if _bridge_silent >= _MAX_BRIDGE_SILENCE:
                                    logger.warning(
                                        "bridge silent %d× — прекращаю ход, "
                                        "Revit не отвечает", _bridge_silent)
                                    state.full_messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call_id,
                                        "content": json.dumps({
                                            "error": True,
                                            "message": _BRIDGE_SILENT_HINT,
                                        }, ensure_ascii=False),
                                        "_tool_name": tool_name,
                                    })
                                    yield StreamEvent("tool_end", {
                                        "tool": tool_name, "result": result_str,
                                        "arguments": args_str})
                                    continue
                            # Per-tool consecutive-error counter (NOT global): an
                            # execute fail + an unrelated lookup fail must not sum to a
                            # false "this tool failed 3 times". _bump_tool_error resets
                            # the streak when it fires, so a later error still shows the
                            # real detail instead of re-firing the truncated hint.
                            # plan-020 Evaluator v1 (SHADOW): record the error-side
                            # verdict BEFORE the 3-strike hint may `continue`. The
                            # flag-level check inside the call makes this a no-op at
                            # level 0; error rows never probe. Never blocks, never throws.
                            try:
                                from kukai.will.shadow import shadow_evaluate
                                await shadow_evaluate(
                                    tool_name, tool_args, tool_result,
                                    is_error=True,
                                    bridge_callback=bridge_callback,
                                    revit_version=self._revit_version,
                                )
                            except Exception as _ev_exc:  # noqa: BLE001 — shadow never breaks a turn
                                from kukai.telemetry import note_telemetry_failure
                                note_telemetry_failure(_ev_exc)
                            if _bump_tool_error(state.consecutive_errors, tool_name):
                                # Inject a hint — force the model to stop retrying THIS
                                # tool and explain. Note: do NOT increment tool_round
                                # here — the single increment after the for-loop covers
                                # this round (avoids charging one bad round twice).
                                state.full_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call_id,
                                    "content": json.dumps({
                                        "error": True,
                                        "message": (
                                            result_str[:500] +
                                            "\n\n[SYSTEM: This tool has failed 3 times in a row. "
                                            "Do NOT retry. Instead: explain the error to the user, "
                                            "suggest a different approach, or break the task into smaller steps.]"
                                        ),
                                    }),
                                    "_tool_name": tool_name,
                                })
                                yield StreamEvent("tool_end", {"tool": tool_name, "result": result_str, "arguments": args_str})
                                continue
                        else:
                            _reset_tool_error(state.consecutive_errors, tool_name)
                            _bridge_silent = 0
                            # Step 8 — C1: world-witness count (comments included)
                            # moved verbatim to _count_world_tool_success (module level).
                            _count_world_tool_success(state, tool_name)
                            if _looks_like_a_write(tool_name, result_str):
                                if not _wrote_this_turn and bridge_callback is not None:
                                    # Baseline for "did this turn LOSE anything".
                                    # Taken right after the first write, so the
                                    # first op's own delta is inside it — the
                                    # prompt says so rather than pretending.
                                    _size_before = await _model_size(bridge_callback)
                                _wrote_this_turn = True
                            if _sig is not None:
                                state.errored_sigs.discard(_sig)  # success → an identical repeat now dedups
                            # Dedup ignores world state: a write changes the model, so
                            # a re-query issued to VERIFY it (look→act→see) must not be
                            # suppressed as a duplicate of the identical pre-write read.
                            # Clear read sigs on write success — but KEEP the write's OWN
                            # sig so an identical write repeated right after is still
                            # caught (Fable review: prevent double-write).
                            if state.conv_on and _tool_call_is_write(tool_name, tool_args):
                                _invalidate_dedup_after_write(state.seen_tool_sigs, keep_sig=_sig)

                        # plan-020 Evaluator v1 (SHADOW): deterministic verdict over
                        # this write's change-set — observe & record only. Never
                        # blocks, never edits the result, model never sees it.
                        if _tool_call_is_write(tool_name, tool_args):
                            try:
                                from kukai.will.shadow import shadow_evaluate
                                await shadow_evaluate(
                                    tool_name, tool_args, tool_result,
                                    is_error=False,
                                    bridge_callback=bridge_callback,
                                    revit_version=self._revit_version,
                                )
                            except Exception as _ev_exc:  # noqa: BLE001 — shadow never breaks a turn
                                from kukai.telemetry import note_telemetry_failure
                                note_telemetry_failure(_ev_exc)

                        # Store large results for generate_report to use directly
                        # (bypasses Gemini context — data flows backend→Excel, not backend→Gemini→Excel)
                        if tool_name == "execute_revit_code" and len(result_str) > 5000:
                            try:
                                parsed = json.loads(result_str)
                                if isinstance(parsed, (list, dict)):
                                    self._last_large_result = parsed
                                    logger.info("Stored large tool result (%d chars) for generate_report bypass", len(result_str))
                            except (json.JSONDecodeError, TypeError):
                                pass

                        yield StreamEvent("tool_end", {"tool": tool_name, "result": result_str, "arguments": args_str})

                        # Add tool result to messages
                        # Limit tool result size to prevent memory explosion
                        truncated_result = _smart_truncate(result_str)
                        state.full_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": truncated_result,
                            "_tool_name": tool_name,  # Used by Gemini pool for functionResponse
                        })

                        # Hand the model the picture it just asked for. Model-DRIVEN:
                        # it calls export_view when it wants to check its work (after a
                        # floor, at the end), instead of a critic firing after every
                        # single write — the agent decides, and images are only paid for
                        # when they are actually wanted. Kill-switch: KUKAI_VISION_INLINE=0.
                        _img_b64 = _pending_view_image.get()
                        if _img_b64:
                            _pending_view_image.set(None)
                            if os.environ.get("KUKAI_VISION_INLINE", "1") == "1":
                                state.full_messages.append({
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": (
                                            "Снимок текущего вида Revit по твоему запросу. "
                                            "Оцени результат: получилось ли задуманное, "
                                            "нет ли ошибок размещения. Если что-то не так — исправь."
                                        )},
                                        {"type": "image_url", "image_url": {
                                            # The shot may come back as JPEG when
                                            # the PNG is too heavy — label it by
                                            # what it actually is, not by habit.
                                            "url": f"data:{_image_mime(_img_b64)};base64," + _img_b64}},
                                    ],
                                })
                                logger.info("vision: снимок отдан модели как изображение (%d КБ)",
                                            len(_img_b64) * 3 // 4 // 1024)

                    # M2 stall break: repeated duplicate calls → stop spinning,
                    # synthesize from what we have (study s27: 31-call re-scan loop).
                    if state.conv_on and state.dedup_count >= 3:
                        logger.warning("Convergence: %d duplicate tool calls — forcing synthesis", state.dedup_count)
                        async for _ev in self._forced_synthesis(state.full_messages, context):
                            yield _ev
                        break
                    state.tool_round += 1
                    # Continue loop for next LLM call with tool results
                    continue

                # No tool calls — decide: done, continue (truncated), or retry (empty)
                # Keystone (convergence/code-salvage): the model wrote C# code as
                # chat TEXT instead of calling execute_revit_code — nothing runs in
                # Revit and the user gets "ничего не сделано". Force ONE corrective
                # round that actually executes it. Gated + capped; instant rollback
                # via KUKAI_AGENT_CODE_SALVAGE=0.
                if (state.conv_on and state.code_salvage_on and should_use_tools
                        and state.code_salvage_used < state.MAX_CODE_SALVAGE
                        and _looks_like_unexecuted_csharp(collected_text)):
                    state.code_salvage_used += 1
                    if has_content:
                        yield StreamEvent("stream_end")
                        has_content = False
                    state.full_messages.append({"role": "assistant", "content": collected_text})
                    state.full_messages.append({"role": "user", "content": (
                        "Ты написал C#-код в тексте ответа, но НЕ вызвал инструмент "
                        "execute_revit_code — код в чате НЕ исполняется в Revit. "
                        "ВЫПОЛНИ его сейчас: вызови execute_revit_code с этим кодом "
                        "(если задача из нескольких шагов — вызывай по шагам). "
                        "Выводи ТОЛЬКО вызов инструмента, без прозы и без markdown."
                    )})
                    logger.info(
                        "Convergence/code-salvage: code-in-text, no tool call — "
                        "forcing execution (%d/%d)", state.code_salvage_used, state.MAX_CODE_SALVAGE)
                    audit_trace.trace(_audit_sid, "code_salvage",
                                      {"used": state.code_salvage_used,
                                       "chars": len(collected_text)})
                    collected_text = ""
                    state.tool_round += 1
                    continue
                if has_content:
                    if last_finish == "length" and state.continuations < state.MAX_CONTINUATIONS:
                        # Truncated by the token cap — do NOT serve a cut-off
                        # answer. Continue in the SAME bubble until the model
                        # finishes naturally (delivery guarantee).
                        state.continuations += 1
                        state.carry_bubble = True
                        # Step 8: keep the already-streamed prefix so the truth
                        # gate below scans the COMPLETE answer, not just the tail
                        # of the last continuation. Pure bookkeeping.
                        state.truth_text_parts.append(collected_text)
                        state.full_messages.append({"role": "assistant", "content": collected_text})
                        state.full_messages.append({"role": "user", "content": (
                            "Твой предыдущий ответ оборвался по лимиту токенов. "
                            "Продолжи РОВНО с места обрыва — без приветствий и без "
                            "повтора уже написанного."
                        )})
                        logger.info("Completion-guarantee: finish=length, continuing %d/%d",
                                    state.continuations, state.MAX_CONTINUATIONS)
                        state.tool_round += 1
                        continue
                    # ── Step 8 (KUKAI_TRUTH_GATE): Tier-0 fake-готово detector ──
                    # THE truth-layer socket: the turn is ending naturally with
                    # assistant text. Fires only when (action intent) AND (zero
                    # successful world tools) AND (completion/observation claim)
                    # — see kukai/will/truth_gate.py. Flag read at CALL time:
                    #   OFF (default) → gate_mode()=="" → nothing runs, turn
                    #     byte-identical; "shadow" → record only; "enforce" →
                    #     record + at most ONE corrective round (never when
                    #     code-salvage fired this turn — no ping-pong; if the
                    #     corrective round still yields no tools we record
                    #     "gave_up" and stop — never loops).
                    # Placed AFTER the code-salvage check (its `continue` above
                    # wins) and AFTER the length-continuation (full text only).
                    # Fail-open: any error is logged and swallowed.
                    try:
                        from kukai.will import truth_gate as _tg
                        _tg_mode = _tg.gate_mode()
                        if _tg_mode:
                            # ONE combined pass (2026-07-10): Tier-0 fake-готово
                            # (corrects) + Tier-1 fabricated_count (shadow) in a
                            # single evaluation. At most ONE corrective round —
                            # no latency stacking across detectors.
                            _tg_final = "".join(state.truth_text_parts) + collected_text
                            _tg_res = _tg.evaluate(
                                intent=getattr(state.route, "intent", None) if state.route is not None else None,
                                world_tool_successes=state.world_tools_ok,
                                tool_calls_total=state.turn_tool_calls_total,
                                final_text=_tg_final,
                                tool_result_texts=state.truth_witness_parts,
                                # Pushed model context is real world state — a
                                # number echoed from it is witnessed, not made up.
                                context_texts=[system_prompt] if system_prompt else None,
                            )
                            _tg_corr = _tg_res.get("correction")
                            # The single correction fires only in enforce + guards.
                            _tg_apply = (
                                _tg_corr is not None
                                and _tg_mode == "enforce"
                                and state.truth_gate_corrections < 1   # ONE corrective round, ever
                                and state.code_salvage_used == 0       # disjoint from code-salvage
                                and should_use_tools              # tools must be available
                                and state.tool_round + 1 < state.effective_max_rounds  # round budget left
                            )
                            # Record EVERY fired tier in this one pass.
                            for _sig in _tg_res.get("signals", []):
                                _is_corrector = (
                                    _tg_corr is not None
                                    and _sig.get("tier", 0) == _tg_corr.get("tier"))
                                _sig["action"] = (
                                    ("corrective_round" if _tg_apply
                                     else ("gave_up" if _tg_mode == "enforce" else "recorded"))
                                    if _is_corrector else "recorded")
                                _sig["mode"] = _tg_mode
                                _sig["tools_available"] = bool(should_use_tools)
                                _sig["session_id"] = str(_audit_sid)[:64]
                                _tg.record(_sig)
                                audit_trace.trace(_audit_sid, "truth_gate", dict(_sig))
                                # Internal event → chat_ws folds it into the
                                # reasoning trace; NEVER forwarded to the plugin.
                                yield StreamEvent("truth_gate", dict(_sig))
                                logger.info(
                                    "truth-gate[%s] tier-%s: %s (intent=%s tools=%d/%d) → %s",
                                    _tg_mode, _sig.get("tier", 0), _sig.get("signal"),
                                    _sig.get("intent"), state.world_tools_ok,
                                    state.turn_tool_calls_total, _sig["action"])
                            # Apply the ONE correction (if it fired).
                            if _tg_apply:
                                state.truth_gate_corrections += 1
                                if has_content:
                                    yield StreamEvent("stream_end")
                                    has_content = False
                                state.carry_bubble = False
                                state.full_messages.append({"role": "assistant", "content": collected_text})
                                state.full_messages.append({"role": "user", "content": _tg_corr["prompt"]})
                                state.truth_force_required = bool(_tg_corr.get("force_tools"))
                                collected_text = ""
                                state.tool_round += 1
                                continue
                    except Exception:  # noqa: BLE001 — the truth gate must NEVER break a turn
                        logger.debug("truth_gate hook failed (non-fatal)", exc_info=True)
                    # Announced a plan, executed nothing → push it to act instead of
                    # ending the turn. Bounded (KUKAI_PLAN_CONTINUE_MAX) so a model
                    # that keeps narrating can never loop forever, and scoped to the
                    # Codex route: this is its failure mode, and mimo's behaviour
                    # must not shift underneath the fleet.
                    if (not tool_calls_accumulator
                            and _plan_continues < _MAX_PLAN_CONTINUES
                            and _looks_like_plan(collected_text)):
                        try:
                            from kukai.llm import codex_route as _cx_plan
                            _cx_turn = _cx_plan.device_eligible()
                        except Exception:  # noqa: BLE001
                            _cx_turn = False
                        if _cx_turn:
                            _plan_continues += 1
                            logger.info("plan-only answer (%d/%d) — pushing the model to execute",
                                        _plan_continues, _MAX_PLAN_CONTINUES)
                            _held_text.clear()  # the draft never reaches the user
                            if has_content:
                                yield StreamEvent("stream_end")
                                has_content = False
                            state.carry_bubble = False
                            state.full_messages.append({"role": "assistant", "content": collected_text})
                            state.full_messages.append({"role": "user", "content": (
                                "Ты описал план, но не выполнил его. Выполни его СЕЙЧАС, "
                                "вызывая инструменты — по шагам, до конца. Не пересказывай "
                                "план заново и не спрашивай подтверждения."
                            )})
                            collected_text = ""
                            state.tool_round += 1
                            continue

                    # Changed the model and now calling it done? The checklist
                    # runs BEFORE the picture, because a picture answers "does
                    # it look right" and the checklist answers "does it hold
                    # together" — and the second is what a model cannot see in
                    # its own work. Measured 2026-07-28: a 10 134-element tower
                    # whose every element was witnessed green had 404 columns
                    # off their slab and a frame tapering half as fast as its
                    # envelope. Nothing in the turn objected.
                    if (not tool_calls_accumulator
                            and _wrote_this_turn
                            and _reviews < _kir_review.MAX_REVIEWS
                            and _kir_review.enabled()):
                        _findings = _kir_review.findings()
                        if _findings:
                            _reviews += 1
                            logger.info("review %d/%d: чек-лист не закрыт, %d пунктов",
                                        _reviews, _kir_review.MAX_REVIEWS, len(_findings))
                            if has_content:
                                yield StreamEvent("stream_end")
                                has_content = False
                            state.carry_bubble = False
                            state.full_messages.append(
                                {"role": "assistant", "content": collected_text})
                            state.full_messages.append(
                                {"role": "user",
                                 "content": _kir_review.message(_findings)})
                            collected_text = ""
                            state.tool_round += 1
                            continue

                    # Checklist closed (or nothing to check). Now look at it.
                    # The turn gets a picture of what it built and has to answer
                    # against the ORIGINAL request. Anything wrong, it keeps
                    # working; nothing wrong, it says so and the turn ends.
                    if (not tool_calls_accumulator
                            and _wrote_this_turn
                            and _self_checks < _MAX_SELF_CHECKS
                            and os.getenv("KUKAI_SELFCHECK_AFTER_WRITE", "1") != "0"
                            and bridge_callback is not None):
                        _shot = await _shot_via_exec(bridge_callback)
                        _img = (_shot or {}).get("image_base64") if isinstance(_shot, dict) else None
                        if _img:
                            _self_checks += 1
                            logger.info("self-check %d/%d: показываю модели, что она построила",
                                        _self_checks, _MAX_SELF_CHECKS)
                            if has_content:
                                yield StreamEvent("stream_end")
                                has_content = False
                            state.carry_bubble = False
                            state.full_messages.append({"role": "assistant", "content": collected_text})
                            # The balance line. Witnesses only ever prove that
                            # what you DID landed; nothing proves you did not
                            # destroy something good on the way. The tower run
                            # ended 49 beams → 28 with every witness green.
                            _size_now = await _model_size(bridge_callback)
                            _delta = ""
                            if _size_before is not None and _size_now is not None:
                                _d = _size_now - _size_before
                                if _d < 0:
                                    _delta = (
                                        f"\nВНИМАНИЕ: элементов модели стало МЕНЬШЕ на {-_d} "
                                        f"({_size_before} → {_size_now}, считая от момента "
                                        "первой твоей записи). Если удаление входило в задачу — "
                                        "скажи прямо, что и зачем удалил. Если нет — верни "
                                        "утраченное, прежде чем заканчивать."
                                    )
                                elif _d > 0:
                                    _delta = f"\nЭлементов модели прибавилось на {_d} ({_size_before} → {_size_now})."
                            state.full_messages.append({"role": "user", "content": [
                                {"type": "text", "text": (
                                    "Ты изменил модель и считаешь, что закончил. Вот что "
                                    "получилось. СНАЧАЛА посмотри на снимок, потом сверь с "
                                    "исходной задачей: получилось ли именно то, что просили — "
                                    "форма, пропорции, расположение, ничего не висит в воздухе "
                                    "и не пересекается?\n"
                                    "Если есть что доработать — молча продолжай работать "
                                    "инструментами, не спрашивай разрешения.\n"
                                    "Если всё верно — коротко скажи, что проверил по снимку, "
                                    "и на этом закончи." + _delta
                                )},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:{_image_mime(_img)};base64,{_img}"}},
                            ]})
                            collected_text = ""
                            state.tool_round += 1
                            continue
                        logger.info("self-check пропущен: снимок не получился (%s)",
                                    str((_shot or {}).get("message"))[:90] if _shot else "нет ответа")
                    if _held_text:
                        # Kept back until we knew this was the real answer, not a
                        # draft the harness was about to reject.
                        if not has_content:
                            yield StreamEvent("stream_start")
                            has_content = True
                        yield StreamEvent("stream_chunk", "".join(_held_text))
                        _held_text.clear()
                    yield StreamEvent("stream_end")
                    state.carry_bubble = False
                elif _leak_dropped_call and not tool_calls_accumulator and _leak_retries < 1:
                    # A tool call the model MEANT to make was mangled by the
                    # provider and dropped (import_cad vanished this way). Don't
                    # end the turn on a lost intent — re-ask for a structured call.
                    _leak_retries += 1
                    if has_content:
                        yield StreamEvent("stream_end")
                        has_content = False
                    state.full_messages.append({"role": "user", "content":
                        "Твой предыдущий вызов инструмента пришёл в некорректном "
                        "формате и не был выполнен. Повтори его как СТРУКТУРНЫЙ "
                        "вызов инструмента (tool call), не текстом."})
                    logger.warning(
                        "TOOL CALL LEAK: unrecoverable dropped call — nudging model "
                        "to re-emit structurally (leak_retry %d)", _leak_retries)
                    state.tool_round += 1
                    continue
                elif not collected_text and not tool_calls_accumulator:
                    # Empty response — retry once before giving the user nothing.
                    if state.continuations < 1:
                        state.continuations += 1
                        state.full_messages.append({"role": "user", "content":
                            "Ответь на запрос пользователя выше."})
                        logger.info("Completion-guarantee: empty response, retrying once")
                        state.tool_round += 1
                        continue
                    logger.warning(
                        "Completion-guarantee: empty after retry; forcing synthesis instead of empty stream"
                    )
                    async for _ev in self._forced_synthesis(state.full_messages, context):
                        yield _ev
                audit_trace.trace(_audit_sid, "finish", {
                    "finish_reason": last_finish,
                    "chars": len(collected_text),
                    "continuations": state.continuations,
                    "tool_rounds": state.tool_round,
                    "had_content": bool(has_content),
                })
                break

            except asyncio.TimeoutError:
                logger.warning("LLM call timed out after %.0fs (round %d/%d)", self._timeout, state.tool_round + 1, state.effective_max_rounds)
                if has_content:
                    yield StreamEvent("stream_end")
                if state.tool_round > 0:
                    yield StreamEvent("error", f"Запрос превысил время ожидания после {state.tool_round} попыток. Попробуйте упростить запрос.")
                else:
                    yield StreamEvent("error", "ИИ-сервис не ответил вовремя. Попробуйте повторить запрос.")
                break
            except Exception as e:
                logger.exception("LLM error (round %d/%d): %s", state.tool_round + 1, state.effective_max_rounds, e)
                if has_content:
                    yield StreamEvent("stream_end")
                error_hint = str(e)[:200] if str(e) else "Неизвестная ошибка"
                if "rate" in error_hint.lower() or "429" in error_hint:
                    yield StreamEvent("error", "Превышен лимит запросов к ИИ-провайдеру. Подождите минуту и повторите.")
                elif state.tool_round > 0:
                    yield StreamEvent("error", f"Ошибка ИИ после {state.tool_round} попыток выполнения. Попробуйте переформулировать запрос.")
                else:
                    yield StreamEvent("error", "ИИ-сервис временно недоступен. Попробуйте позже.")
                break
        else:
            # While loop exhausted (max_tool_rounds reached without a final text response)
            logger.warning("Max tool rounds (%d) reached without final text", state.effective_max_rounds)
            if state.conv_on:
                # M2: answer from gathered data instead of the dead-end string.
                async for _ev in self._forced_synthesis(state.full_messages, context):
                    yield _ev
            else:
                yield StreamEvent("stream_start")
                yield StreamEvent("stream_chunk", "Достигнут лимит выполнения операций. Попробуйте упростить запрос.")
                yield StreamEvent("stream_end")

    async def _init_round_state(
        self,
        *,
        full_messages: list[dict[str, Any]],
        context: Optional[ContextResult],
        skill_prompt: Optional[str],
        user_message: str,
        agent_intent_metadata: Optional[dict],
        _audit_sid: str,
        _pf2_intent_task: Optional[asyncio.Task],
        _pf2_intent_deadline: float,
        _pf2_intent_t0: float,
    ) -> RoundState:
        """Golden-path C1 (2026-07-13): the agent round loop's INIT block —
        counters, budgets, the M2 router/convergence overrides, truth-gate
        bookkeeping, the turn wall-clock — moved VERBATIM out of
        `_stream_chat_inner` (its old L1614-1765 region) and returned as ONE
        explicit RoundState. Parameter names deliberately keep the original
        local names (leading underscores included) so the moved body below is
        byte-identical. Mutates `full_messages` in place (the diagnose
        grounding directive) exactly like the inline original;
        `RoundState.full_messages` aliases the SAME list object. The runtime
        import lives here (not in the module import block) so everything above
        the preflight zone stays byte-untouched — the annotations are lazy
        under `from __future__ import annotations`.
        """
        from kukai.turn.context import RoundState

        tool_round = 0
        # Consecutive tool failures, tracked PER TOOL NAME (not one global counter):
        # an execute failure followed by an unrelated lookup failure must NOT add up
        # to a false "this tool failed 3 times". Reset for a tool on its own success.
        _consecutive_errors: dict[str, int] = {}
        _gemini_failed_mid_stream = False  # If Gemini fails mid-conversation, stick to litellm

        # Skills need more tool rounds (8-10 steps: inventory, sheets, annotations, export, send)
        # Family editor mode also needs more rounds — a typical "build chair/table"
        # compound query chains inspect_family + skeleton + 5-7 geometry tools + materials.
        _is_family_editor_mode = bool(context and getattr(context, "is_family_editor", False))
        if skill_prompt:
            effective_max_rounds = 12
        elif _is_family_editor_mode:
            effective_max_rounds = 15  # bumped from 6 to allow chair/table/cabinet composition
        else:
            effective_max_rounds = self._max_tool_rounds

        # Completion guarantee: never serve a truncated (finish_reason=length)
        # or empty answer. Continue generation in-place until the model finishes
        # naturally, so the user always receives the COMPLETE response.
        _continuations = 0
        _MAX_CONTINUATIONS = 5
        _carry_bubble = False  # keep the stream bubble open across continuations

        # --- M2 convergence controller (flag-gated by AGENT_USE_CONVERGENCE +
        #     AGENT_USE_ROUTER; DEFAULT ON for all users as of 2026-06-12, W1).
        #     Turns the dead-end "Достигнут лимит" string into a synthesized
        #     answer, and stops duplicate-tool-call loops (study: s24/s27 timed
        #     out, s27 = 31 calls). Rollback: env KUKAI_AGENT_CONVERGE=0 /
        #     KUKAI_AGENT_ROUTER=0, or KUKAI_AGENT_TEST_PCT=0 (control for all).
        _route = None
        _reasoning_effort_override: Optional[str] = None
        try:
            from kukai import config as _kcfg
            from kukai.agents.rollout import in_treatment as _in_treat
            # Treatment gate. By default (AGENT_TEST_PERCENT=100) EVERY turn is in
            # treatment — including sessionless/anonymous traffic, which the A/B
            # bucketer intentionally excludes — so the validated discipline is the
            # standard path for all users. A bucketed A/B (1..99) and the
            # eval-harness "audit-" sessions still resolve to treatment; setting
            # AGENT_TEST_PERCENT=0 returns everyone to the control/baseline path.
            _treat = (_kcfg.AGENT_TEST_PERCENT >= 100
                      or _in_treat(_audit_sid, _kcfg.AGENT_TEST_PERCENT)
                      or str(_audit_sid).startswith("audit-"))
            _conv_on = bool(_kcfg.AGENT_USE_CONVERGENCE) and _treat
            if bool(_kcfg.AGENT_USE_ROUTER) and _treat:
                from kukai.agents.intent_rules import quick_classify, overlay
                from kukai.agents.router import decide_route
                # Overlay the LLM classifier (PRIMARY) over the keyword fallback —
                # reuse the pre-flight result if present, else run it now (gated to
                # treatment; DeepSeek-homed, verified working). Fixes the IQ-audit
                # bug where the router ran on quick_classify (the dictionary) alone.
                _llm_meta = agent_intent_metadata
                if _llm_meta is None and _pf2_intent_task is not None:
                    # Step 9B: the classifier was launched pre-translate and has
                    # been running concurrently with local Wiki prompt assembly.
                    # Await only its remaining budget (it self-bounds at
                    # _pf2_intent_deadline from launch; +0.5s parse grace); on
                    # timeout/failure fall open to the rule-based quick_classify
                    # — exactly the inline except path below.
                    try:
                        _pf2_remaining = max(
                            0.25,
                            _pf2_intent_deadline + 0.5
                            - (time.monotonic() - _pf2_intent_t0),
                        )
                        _ic = await asyncio.wait_for(
                            _pf2_intent_task, timeout=_pf2_remaining,
                        )
                        _llm_meta = _ic.value if _ic else None
                    except Exception:  # noqa: BLE001 — keep the deterministic guess
                        _pf2_intent_task.cancel()
                        _llm_meta = None
                elif _llm_meta is None:
                    try:
                        from kukai.agents.intent_classifier import IntentClassifier
                        _ic = await IntentClassifier().run(query=user_message or "", timeout=6.0)
                        _llm_meta = _ic.value if _ic else None
                    except Exception:  # noqa: BLE001 — keep the deterministic guess
                        _llm_meta = None
                _meta = overlay(quick_classify(user_message or ""), _llm_meta)
                _route = decide_route(
                    _meta,
                    base_max_rounds=effective_max_rounds,
                    is_family_editor=_is_family_editor_mode,
                    has_skill=bool(skill_prompt),
                )
                # max_rounds==0 = "converse" (answer directly): the loop still needs
                # >=1 iteration to emit text, so floor at 1 + disable tools (below).
                effective_max_rounds = _route.max_rounds if _route.max_rounds > 0 else 1
                # "не останавливайся / доведи до конца" is a work order, not small
                # talk. Routed as converse it gets 1 round and no tools, so the turn
                # answers nothing and stops — precisely what the user told it not to
                # do (live 2026-07-27: 74 s, 0 chars). Restore a real working budget.
                if effective_max_rounds <= 1 and _is_keep_going(full_messages):
                    _kg = max(8, int(os.getenv("KUKAI_KEEP_GOING_ROUNDS", "25")))
                    logger.info("keep-going instruction: rounds %d→%d, tools restored",
                                effective_max_rounds, _kg)
                    effective_max_rounds = _kg
                    if _route is not None:
                        try:
                            _route.use_tools_override = None
                        except Exception:  # noqa: BLE001 — frozen route → tools handled below
                            pass
                _reasoning_effort_override = _route.reasoning_effort
                logger.info("router: intent=%s complexity=%s rounds=%d effort=%s src=%s",
                            _route.intent, _route.complexity, effective_max_rounds,
                            _route.reasoning_effort, _meta.get("source"))
                # Per-intent tool masking (KUKAI_TOOL_MASKING): publish THIS
                # turn's intent + fresh mask state for _resolve_tools.
                from kukai.llm.turn_context import publish_route_intent
                publish_route_intent(getattr(_route, "intent", None))
                # Semantic anti-fabrication gate (IQ-fix): on an ANALYSIS/normcontrol
                # turn (LLM intent=diagnose — catches paraphrases the regex missed),
                # require grounding before answering + forbid fabricated norm clauses.
                if _route.intent == "diagnose":
                    full_messages.append({"role": "system", "content": (
                        "Это аналитический/нормоконтрольный запрос. ОБЯЗАТЕЛЬНО вызови хотя бы "
                        "один инструмент заземления (get_model_info / query_model / lookup_norm) "
                        "ПЕРЕД финальным ответом — не отвечай из общих знаний. НЕ цитируй конкретный "
                        "пункт нормы (ГОСТ/СП/СНиП/п.N), если его не вернул lookup_norm; если нормы "
                        "не нашлись — честно скажи это, НЕ выдумывай."
                    )})
                    logger.info("grounding directive (semantic, intent=diagnose) applied")
        except Exception:  # noqa: BLE001 — never block the chat on the router/gate
            _conv_on = False
        # "Посмотри" means look. See _asks_to_look for the two runs that answered
        # with a confident silhouette and zero screenshots.
        try:
            if (os.getenv("KUKAI_LOOK_DIRECTIVE", "1") != "0"
                    and _asks_to_look(full_messages)):
                full_messages.append({"role": "system", "content": (
                    "Пользователь просит ПОСМОТРЕТЬ. Сначала получи изображение "
                    "(export вида), и только потом описывай увиденное. "
                    "Габариты, отметки и количества из query_model/execute_revit_code — "
                    "это НЕ взгляд: по ним нельзя судить о силуэте, ломаности контура, "
                    "ступенчатости или композиции. Если снимок получить не удалось — "
                    "скажи об этом прямо и опиши только то, что подтверждено числами."
                )})
                logger.info("look directive applied (user asked to look)")
        except Exception:  # noqa: BLE001 — a directive must never break the turn
            logger.debug("look directive skipped", exc_info=True)
        _seen_tool_sigs: dict[str, int] = {}
        _errored_sigs: set[str] = set()  # sigs whose last identical call errored → retry allowed
        _dedup_count = 0
        # Keystone (code-salvage): cap how many times per turn we force a
        # "code-in-text → execute_revit_code" corrective round (avoid ping-pong).
        _code_salvage_used = 0
        _MAX_CODE_SALVAGE = 2
        try:
            from kukai import config as _kcfg_cs
            _code_salvage_on = bool(getattr(_kcfg_cs, "AGENT_CODE_SALVAGE", True))
        except Exception:  # noqa: BLE001
            _code_salvage_on = True
        # Step 8 (KUKAI_TRUTH_GATE): per-turn truth-layer bookkeeping. These are
        # pure in-memory counters — always maintained (behavior-neutral); the
        # detector itself only runs when the flag is set (read at CALL time in
        # truth_gate.gate_mode(), so flag OFF keeps the turn byte-identical).
        _world_tools_ok = 0          # successful world-tool calls this turn
        _turn_tool_calls_total = 0   # all tool calls issued this turn
        _truth_text_parts: list[str] = []  # answer text across length-continuations
        _truth_witness_parts: list[str] = []  # Tier-1: tool result texts (claim witnesses)
        _truth_gate_corrections = 0  # enforce: at most ONE corrective round/turn
        _truth_force_required = False  # enforce: next round forces tool_choice
        # Harness "always answer" guarantee: a per-tool wall cap (a single tool —
        # audit_model — ran 496s on a heavy model) + a whole-turn deadline that
        # forces synthesis from gathered data instead of leaving the user with
        # nothing. Both convergence-gated; tunable.
        _TOOL_BUDGET_S = 90.0
        _TURN_BUDGET_S = float(os.getenv("KUKAI_TURN_BUDGET_S", "300"))
        # Autonomous Codex sessions get their own, far larger envelope: the goal is
        # an agent that keeps building for an hour, and 300 s / 25 rounds cuts that
        # off mid-task. Raised ONLY for allow-listed Codex devices — the fleet keeps
        # the tight budget, because one runaway turn there would hold a worker for
        # an hour while 50 people wait. Convergence detection, the empty-response
        # guard and the per-user quota still apply, so this widens the ceiling
        # without removing any brake.
        try:
            from kukai.llm import codex_route as _cx_budget
            if _cx_budget.device_eligible():
                _TURN_BUDGET_S = float(os.getenv("KUKAI_CODEXPROXY_TURN_BUDGET_S", "3600"))
                _cx_rounds = int(os.getenv("KUKAI_CODEXPROXY_MAX_ROUNDS", "200"))
                if _cx_rounds > effective_max_rounds:
                    logger.info("autonomous Codex turn: rounds %d→%d, budget %.0fs",
                                effective_max_rounds, _cx_rounds, _TURN_BUDGET_S)
                    effective_max_rounds = _cx_rounds
        except Exception:  # noqa: BLE001 — budget widening must never break a turn
            logger.debug("codex autonomous budget check failed", exc_info=True)  # was 210.0; operator-raised whole-turn wall-clock cap (pairs with rounds_max=50)
        _turn_start = time.monotonic()
        # Step 7 (KUKAI_EXEC_PIPELINE): publish the turn's absolute deadline so
        # the RevitExecutionPipeline derives its TurnBudget from the SAME wall
        # (turn ≥ pipeline ≥ attempt ≥ bridge-wait — one hierarchy). Flag-gated;
        # pure bookkeeping, never affects the legacy path.
        if _exec_pipeline_active():
            try:
                from kukai.llm.revit_execution_pipeline import set_turn_deadline
                set_turn_deadline(_turn_start + _TURN_BUDGET_S)
            except Exception:  # noqa: BLE001 — deadline plumbing must never kill a turn
                pass

        return RoundState(
            full_messages=full_messages,
            tool_round=tool_round,
            effective_max_rounds=effective_max_rounds,
            gemini_failed_mid_stream=_gemini_failed_mid_stream,
            route=_route,
            reasoning_effort_override=_reasoning_effort_override,
            conv_on=_conv_on,
            consecutive_errors=_consecutive_errors,
            seen_tool_sigs=_seen_tool_sigs,
            errored_sigs=_errored_sigs,
            dedup_count=_dedup_count,
            continuations=_continuations,
            MAX_CONTINUATIONS=_MAX_CONTINUATIONS,
            carry_bubble=_carry_bubble,
            code_salvage_used=_code_salvage_used,
            MAX_CODE_SALVAGE=_MAX_CODE_SALVAGE,
            code_salvage_on=_code_salvage_on,
            world_tools_ok=_world_tools_ok,
            turn_tool_calls_total=_turn_tool_calls_total,
            truth_text_parts=_truth_text_parts,
            truth_witness_parts=_truth_witness_parts,
            truth_gate_corrections=_truth_gate_corrections,
            truth_force_required=_truth_force_required,
            TOOL_BUDGET_S=_TOOL_BUDGET_S,
            TURN_BUDGET_S=_TURN_BUDGET_S,
            turn_start=_turn_start,
        )

    async def _forced_synthesis(self, full_messages: list[dict[str, Any]], context: Any = None):
        """M2 convergence: one NO-TOOLS LLM call that answers from the context
        already gathered, when the tool loop hits the round cap or stalls —
        replacing the dead-end "Достигнут лимит" string. Yields StreamEvents.
        Falls back to the canned string only if synthesis produces nothing.
        """
        try:
            msgs = list(full_messages) + [{"role": "user", "content": (
                "Достигнут лимит шагов выполнения. НЕ вызывай инструменты. "
                "Сформулируй лучший возможный ответ на исходный запрос, опираясь на "
                "уже собранные выше данные. Если данных не хватило — кратко скажи, что "
                "удалось узнать и чего не хватает. Отвечай по-русски, без выдумок."
            )}]
            response = await self._get_streaming_response(
                msgs, False, force_litellm=True, thinking_mode=False, context=context,
            )
            _emitted = False
            # This leg is explicitly NO-TOOLS (the prompt above says so) — a
            # leaked tool-call-shaped fragment here has nowhere to be executed,
            # so just suppress it instead of showing raw markup (same shared
            # gate as the main loop, see kukai.llm.tool_call_leak_guard).
            _leak_guard_state = LeakGuardState()
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue
                if getattr(delta, "content", None):
                    for _ev in guard_delta(_leak_guard_state, delta.content):
                        if _ev.passthrough:
                            if not _emitted:
                                yield StreamEvent("stream_start")
                                _emitted = True
                            yield StreamEvent("stream_chunk", _ev.passthrough)
                        elif _ev.dropped or _ev.resolved_call is not None:
                            logger.warning(
                                "TOOL CALL LEAK in forced_synthesis (no-tools leg) — suppressed"
                            )
            if _emitted:
                yield StreamEvent("stream_end")
                return
        except Exception as e:  # noqa: BLE001 — degrade to the canned string
            logger.warning("Forced synthesis failed: %s", e)
        # Last resort — preserve today's behavior if synthesis yielded nothing.
        yield StreamEvent("stream_start")
        yield StreamEvent("stream_chunk", "Достигнут лимит выполнения операций. Попробуйте упростить запрос.")
        yield StreamEvent("stream_end")

    # Premium tier gating disabled — all tools are free during current rollout.
    _PREMIUM_TOOLS: frozenset[str] = frozenset()

    async def _execute_revit_code_via_revit_coder(
        self,
        args: dict,
        bridge_callback,
    ) -> dict:
        """Phase 1 routing: revit-coder generates code, Roslyn validates, Bridge executes.

        Single retry on compile failure. NO fallback to Gemini-as-coder
        (Phase 1 explicitly opted out — see spec).

        See docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md
        """
        import time

        from kukai.revit_coder.client import generate_code
        from kukai.revit_coder.compile_check import compile_check
        from kukai.revit_coder.metrics import log_call, log_failure
        from kukai.revit_coder.types import ModelContext, RevitCoderError

        task: str = args["task"]
        ctx_dict = args.get("model_context") or {}
        # Auto-fill Revit version from session if not provided
        if "revit_version" not in ctx_dict and getattr(self, "_revit_version", None):
            ctx_dict["revit_version"] = self._revit_version
        # Filter out keys that ModelContext doesn't accept (defensive)
        allowed_ctx_keys = {
            "revit_version", "active_view_id", "active_view_type",
            "project_units", "selected_element_ids", "document_title",
        }
        ctx = ModelContext(**{k: v for k, v in ctx_dict.items() if k in allowed_ctx_keys})

        previous_code = args.get("previous_code")
        dry_run = bool(args.get("dry_run"))

        attempts: list[dict] = []
        codegen_total_ms = 0
        compile_total_ms = 0

        # ─── Attempt 1: generate ───
        try:
            result = await generate_code(
                task=task,
                model_context=ctx,
                previous_code=previous_code,
            )
            codegen_total_ms += result.latency_ms
            code = result.code
        except RevitCoderError as e:
            return {
                "error": True,
                "message": "Сервис генерации кода временно недоступен. Попробуйте через минуту.",
                "details": str(e),
            }

        # ─── Compile check 1 ───
        compile_result = await compile_check(code)
        compile_total_ms += compile_result.latency_ms
        compile_ok_first_try = compile_result.ok
        attempts.append({
            "code": code,
            "error": compile_result.stderr if not compile_result.ok else None,
        })

        # ─── Attempt 2 (one retry on fail) ───
        retries = 0
        if not compile_result.ok:
            retries = 1
            try:
                result = await generate_code(
                    task=task,
                    model_context=ctx,
                    error_to_fix=compile_result.stderr,
                    broken_code=code,
                    previous_code=previous_code,
                )
                codegen_total_ms += result.latency_ms
                code = result.code
            except RevitCoderError as e:
                log_failure(task=task, attempts=attempts)
                return {
                    "error": True,
                    "message": "Сервис генерации кода временно недоступен.",
                    "details": str(e),
                }

            compile_result = await compile_check(code)
            compile_total_ms += compile_result.latency_ms
            attempts.append({
                "code": code,
                "error": compile_result.stderr if not compile_result.ok else None,
            })

            if not compile_result.ok:
                log_failure(task=task, attempts=attempts)
                # Log metrics for the failed run too
                log_call(
                    task_preview=task,
                    code_length=len(code),
                    compile_success_first_try=compile_ok_first_try,
                    retries=retries,
                    latency_codegen_ms=codegen_total_ms,
                    latency_compile_ms=compile_total_ms,
                    latency_execute_ms=0,
                    exec_success=False,
                )
                return {
                    "error": True,
                    "message": "Не удалось сгенерировать рабочий код. Попробуй переформулировать.",
                    "details": compile_result.stderr,
                }

        # ─── dry_run: return code without executing ───
        if dry_run:
            log_call(
                task_preview=task,
                code_length=len(code),
                compile_success_first_try=compile_ok_first_try,
                retries=retries,
                latency_codegen_ms=codegen_total_ms,
                latency_compile_ms=compile_total_ms,
                latency_execute_ms=0,
                exec_success=True,
            )
            return {"ok": True, "code": code, "dry_run": True}

        # ─── Execute via Bridge ───
        t_exec_start = time.monotonic()
        try:
            bridge_result = await bridge_callback(
                "execute",
                {"code": code, "estimated_elements": args.get("estimated_elements")},
            )
        except Exception as e:
            execute_ms = int((time.monotonic() - t_exec_start) * 1000)
            log_call(
                task_preview=task,
                code_length=len(code),
                compile_success_first_try=compile_ok_first_try,
                retries=retries,
                latency_codegen_ms=codegen_total_ms,
                latency_compile_ms=compile_total_ms,
                latency_execute_ms=execute_ms,
                exec_success=False,
            )
            return {"error": True, "message": f"Ошибка выполнения в Revit: {e}"}

        execute_ms = int((time.monotonic() - t_exec_start) * 1000)
        exec_ok = (
            isinstance(bridge_result, dict)
            and bridge_result.get("ok", True)
            and not bridge_result.get("error")
        )

        log_call(
            task_preview=task,
            code_length=len(code),
            compile_success_first_try=compile_ok_first_try,
            retries=retries,
            latency_codegen_ms=codegen_total_ms,
            latency_compile_ms=compile_total_ms,
            latency_execute_ms=execute_ms,
            exec_success=exec_ok,
        )
        return bridge_result

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        bridge_callback: Optional[BridgeCallback] = None,
        active_extension: Optional[str] = None,
        user_query: str = "",
        system_context: str = "",
        user_tier: str = "free",
        turn_id: str = "",
        tool_call_id: str = "",
    ) -> dict[str, Any]:
        """Execute a tool call by dispatching to the bridge callback, bridge client, or local handlers.

        Priority:
        0. Premium tier gate — premium tools rejected for free users
        1. Module handlers (from KUKAI module registry) — checked first
        2. Local handlers (generate_report) — always handled locally
        3. bridge_callback (V+ WebSocket proxy) — if provided, routes through WebSocket
        4. self._bridge (legacy HTTP bridge client) — fallback
        """

        # Tool-name normalization — Gemini occasionally hallucinates a namespace
        # prefix like "kuki_revit_family:inspect_family" or "tools.family_extrude".
        # Strip anything before the LAST `:` or `.` so dispatch still finds the
        # real handler. Idempotent for already-clean names.
        if tool_name and (":" in tool_name or "." in tool_name):
            cleaned = tool_name.rsplit(":", 1)[-1].rsplit(".", 1)[-1]
            if cleaned != tool_name:
                logger.info("Tool name namespace prefix stripped: %r → %r", tool_name, cleaned)
                tool_name = cleaned

        # Tool Palette v2 + request_more_tools (KUKAI_TOOLS_V2/KUKAI_TOOL_MASKING):
        # merged tools LOWER onto the legacy branches below; both flags OFF → None
        # for every name → dispatch byte-identical. See tool_handlers/palette_v2.py.
        from kukai.llm.tool_handlers import palette_v2 as _palette_v2
        _v2_result = await _palette_v2.maybe_dispatch(
            self, tool_name, args, bridge_callback, active_extension=active_extension,
            user_query=user_query, system_context=system_context, user_tier=user_tier)
        if _v2_result is not None:
            return _v2_result

        # Premium tier gate — free users see paywall message, LLM relays it
        if tool_name in self._PREMIUM_TOOLS and (user_tier or "free").lower() == "free":
            logger.info("Premium tool %s blocked for free tier", tool_name)
            return {
                "error": True,
                "tier_required": "pro",
                "message": (
                    "Эта функция недоступна на бесплатном тарифе. "
                    "Перейдите на Pro чтобы пользоваться расценкой ВОР, "
                    "графиком работ и аудитом модели."
                ),
            }

        # Module handler dispatch — tools contributed by loaded KUKAI modules
        module_handler = getattr(self, "_module_handlers", {}).get(tool_name)
        if module_handler is not None:
            try:
                return await module_handler(args, None)
            except Exception as exc:
                logger.exception("Module tool %s failed", tool_name)
                return {"error": True, "message": f"Module tool error: {exc}"}

        # ─── Family-editor tools (V2) ──────────────────────────────────────
        # 10 purpose-built tools (inspect_family + 9 build/modify tools) that
        # generate compliant C# from verified-API server-side templates,
        # bypassing LLM hallucination on parametric flex code. Dispatch
        # BEFORE the generic execute_revit_code path.
        try:
            from kukai.llm.tool_handlers import family_tools as _family_tools
        except ImportError:
            _family_tools = None  # type: ignore
        if _family_tools is not None and _family_tools.is_family_tool(tool_name):
            try:
                return await _family_tools.dispatch(tool_name, args, bridge_callback)
            except Exception as exc:
                logger.exception("Family tool %s failed", tool_name)
                return {"error": True, "message": f"Family tool error: {exc}"}

        if tool_name == "generate_report":
            return await self._execute_generate_report(args)

        if tool_name == "modify_excel":
            return await self._execute_modify_excel(args)

        if tool_name == "excel_script":
            return await self._execute_excel_script(args)








        if tool_name == "lookup_norm":
            # Step 5: sync np.load(46MB) + search — offload so it can't freeze the loop.
            return await asyncio.to_thread(self._execute_lookup_norm, args, active_extension=active_extension)

        if tool_name == "add_user_note":
            # This tool is handled client-side — we return a special result
            # that chat_ws.py will forward as an add_note WS message
            return {
                "success": True,
                "action": "add_note",
                "text": args.get("text", ""),
                "message": "Заметка добавлена",
            }

        if tool_name == "send_local_file":
            return await self._execute_send_local_file(args)

        if tool_name == "export_sheets_pdf":
            return await self._execute_export_sheets_pdf(args, bridge_callback)

        # For Revit tools, we need either a bridge_callback or a bridge client
        if not bridge_callback and not self._bridge:
            return {"error": True, "message": "Revit не подключён"}

        # ─── Phase 1 (revit-coder pilot) integration ───
        # When USE_REVIT_CODER=1 and `task` is provided, route through revit-coder.
        # Falls through to legacy handler in all other cases.
        # See docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md
        from kukai.config import USE_REVIT_CODER

        if (
            tool_name == "execute_revit_code"
            and USE_REVIT_CODER
            and args.get("task")
        ):
            return await self._execute_revit_code_via_revit_coder(args, bridge_callback)

        if tool_name == "execute_revit_code":
            _destructive = _deletion_guard(args)
            if _destructive is not None:
                return _destructive
            # Bind one user-visible action to every concrete execution payload.
            # Compile repair changes operation_id (payload hash) but preserves
            # action_id; transport retries preserve both and change attempt_id
            # only inside bridge_protocol._bridge_callback.
            operation_bridge = bridge_callback
            if bridge_callback is not None:
                from kukai.operations.protocol import OperationIdentity

                async def _operation_bridge(method: str, params: dict[str, Any]) -> dict[str, Any]:
                    if method != "execute":
                        return await bridge_callback(method, params)
                    # Trusted evaluator/census reads carry an in-process
                    # capability.  They must not be converted back into writes
                    # merely because they share the execute transport.
                    from kukai.operations.effects import (
                        ReadOnlyContractViolation,
                        is_authorized_read_only,
                    )
                    try:
                        if is_authorized_read_only(params):
                            return await bridge_callback(method, params)
                    except ReadOnlyContractViolation as exc:
                        return {
                            "error": True,
                            "message": f"Read-only execution rejected: {exc}",
                        }
                    identity = OperationIdentity.for_payload(
                        turn_id=turn_id or str(uuid.uuid4()),
                        tool_call_id=tool_call_id or "legacy-tool-call",
                        tool_name=tool_name,
                        method=method,
                        params=params,
                    )
                    enriched = dict(params)
                    enriched["_operation"] = identity.to_mapping()
                    return await bridge_callback(method, enriched)

                operation_bridge = _operation_bridge

            # ── Step 7 (KUKAI_EXEC_PIPELINE): flag-gated single-owner pipeline ──
            # When ON, the whole validate→fix(once)→compile→execute→repair→
            # verdict→record chain runs in kukai/llm/revit_execution_pipeline.py
            # (one fixer, un-latched compile gate, one timeout hierarchy,
            # de-obfuscated error feedback, TurnRecord telemetry). Env is read
            # DIRECTLY (not via kukai.config — deliberate, see module docstring).
            # Default OFF → the legacy inline path below runs unchanged.
            if (
                operation_bridge is not None
                and _exec_pipeline_active()
            ):
                from kukai.llm.revit_execution_pipeline import RevitExecutionPipeline

                _pipe = RevitExecutionPipeline.from_llm_client(self, operation_bridge)
                _pipe_record = await _pipe.run(
                    args, user_query=user_query, system_context=system_context
                )
                return _pipe_record.to_tool_result()

            code = args.get("code", "")

            # Stage 0: Python-side pre-validation (defense-in-depth).
            # Catches obvious violations early, before a round-trip to the bridge.
            from kukai.security.validation import validate_code_safety
            violations = validate_code_safety(code)
            if violations:
                return {
                    "error": True,
                    "message": "Код заблокирован проверкой безопасности",
                    "violations": violations,
                }

            # Stage 0b: Apply deterministic fixes proactively (path-A hardening).
            # Previously fix() was only invoked in the repair loop, so simple
            # mistakes (Console.WriteLine, OST_Walls without prefix, FEC.Cast)
            # always cost a bridge round-trip. Apply on attempt 1 too.
            # Re-validate after fix in case a transformation introduced
            # a forbidden pattern.
            from kukai.security.code_fixer import RevitCodeFixer
            try:
                _preflight_fixer = RevitCodeFixer(revit_version=self._revit_version)
                _fixed_code = _preflight_fixer.fix(code)
                if _fixed_code != code:
                    if not validate_code_safety(_fixed_code):
                        logger.info("Pre-flight fixer applied changes")
                        code = _fixed_code
            except Exception as _fix_exc:
                logger.debug("Pre-flight fixer failed (non-fatal): %s", _fix_exc)

            # Stage 0c+0d: Multi-agent post-flight review (Phase 7.4).
            # CodeCritic looks for hallucinated APIs / missing Transaction.
            # VersionChecker flags cross-version-incompatible APIs.
            # Both flag-gated, default OFF. Failures are non-fatal — fall
            # through to bridge execute on any agent error.
            try:
                from kukai import config as _kcfg
                if _kcfg.AGENT_USE_CRITIC or _kcfg.AGENT_USE_VERSION_CHECKER:
                    import asyncio as _asyncio
                    post_tasks = []
                    slot_names = []
                    # Ground the critic with verified cards from the active Wiki
                    # release. This is deterministic and never loads old vectors.
                    _critic_examples: list[dict] = []
                    if _kcfg.AGENT_USE_CRITIC and self._prompt_assembler and user_query:
                        try:
                            from kukai.rag.wiki_router import get_wiki_router

                            _critic_examples = await asyncio.to_thread(
                                get_wiki_router().recipe_examples,
                                user_query,
                                max_examples=5,
                            )
                        except Exception:
                            _critic_examples = []  # non-fatal
                    if _kcfg.AGENT_USE_CRITIC:
                        async def _do_critic():
                            try:
                                from kukai.agents.code_critic import CodeCritic
                                cc = CodeCritic()
                                return await cc.run(
                                    query=user_query or "",
                                    code=code,
                                    examples=_critic_examples,
                                    timeout=12.0,
                                )
                            except Exception as _e:  # noqa: BLE001
                                return _e
                        post_tasks.append(_do_critic())
                        slot_names.append("critic")
                    if _kcfg.AGENT_USE_VERSION_CHECKER:
                        async def _do_version():
                            try:
                                from kukai.agents.version_checker import VersionChecker
                                vc = VersionChecker()
                                return await vc.run(code=code, timeout=12.0)
                            except Exception as _e:  # noqa: BLE001
                                return _e
                        post_tasks.append(_do_version())
                        slot_names.append("version")
                    post_results = await _asyncio.gather(*post_tasks)
                    for name, res in zip(slot_names, post_results):
                        if isinstance(res, Exception):
                            logger.info("agent post-flight %s failed: %s", name, res)
                            continue
                        if name == "critic":
                            verdict = res.value.get("verdict")
                            issues = res.value.get("issues", [])
                            fixed = res.value.get("fixed_code")
                            logger.info("CodeCritic verdict=%s issues=%d had_fix=%s",
                                        verdict, len(issues), bool(fixed))
                            if verdict == "FIX_NEEDED" and fixed and isinstance(fixed, str):
                                # Sanity: must be valid Revit code (no security violations).
                                if not validate_code_safety(fixed):
                                    code = fixed
                                    logger.info("CodeCritic applied fix")
                        elif name == "version":
                            n_issues = len(res.value.get("issues", []))
                            if n_issues > 0:
                                logger.info("VersionChecker flagged %d cross-version issues (logged, not auto-fixed)", n_issues)
            except Exception as _post_exc:  # noqa: BLE001
                logger.debug("agent post-flight setup failed (non-fatal): %s", _post_exc)

            estimated_elements = args.get("estimated_elements")
            from kukai.config import get_settings as _get_settings
            max_timeout_ms = _get_settings().max_execute_timeout * 1000
            timeout_ms = _calculate_execute_timeout(code, estimated_elements, max_timeout_ms=max_timeout_ms)

            # Execute with repair loop (up to 3 attempts on compilation failure)
            current_code = code
            # Repair trail: the model never sees what the harness silently
            # rewrote before/during execution, so it re-emits the same broken
            # pattern and pays the repair tax again. Track every in-loop
            # mutation so the `execution` block can report final_code + provenance.
            original_code = code
            _repair_trail: list[dict[str, Any]] = []
            result: dict[str, Any] = {"error": True, "message": "No execution attempt was made"}
            _exec_ms = 0  # plan-019: duration of the final successful execution
            for attempt in range(1, 4):
                _exec_t0 = time.monotonic()  # plan-019: per-attempt exec timer
                if operation_bridge:
                    # attempt=1 → bridge skips serverside compile-check (saves 200-500ms on happy path).
                    # attempt>=2 → bridge runs server compile-check first to give the LLM rich CS-code
                    # diagnostics for repair (the whole reason we have a serverside Roslyn at all).
                    result = await operation_bridge("execute", {"code": current_code, "timeout_ms": timeout_ms, "attempt": attempt})
                else:
                    bridge_result = await self._bridge.execute(current_code, timeout_ms=timeout_ms)  # type: ignore[union-attr]
                    result = bridge_result.model_dump()
                # plan-019: each attempt overwrites — the recorded value is the
                # final (successful) execution's wall-clock duration.
                _exec_ms = int((time.monotonic() - _exec_t0) * 1000)

                # Check if it's a compilation error that can be repaired
                if (
                    isinstance(result, dict)
                    and result.get("error") is True
                    and attempt < 3
                    and self._is_compilation_error(result)
                ):
                    error_msg = result.get("message", "")
                    logger.info(
                        "Compilation failed (attempt %d/3), trying repair: %s",
                        attempt, error_msg[:200],
                    )
                    audit_trace.trace(audit_trace.current_session(), "repair", {
                        "attempt": attempt, "error": str(error_msg)[:500],
                    })

                    # Try deterministic fix first (no LLM needed)
                    from kukai.security.code_fixer import RevitCodeFixer
                    det_fixer = RevitCodeFixer(revit_version=self._revit_version)
                    det_fix = det_fixer.fix_from_error(current_code, error_msg)
                    if det_fix and det_fix != current_code:
                        # Re-validate
                        det_violations = validate_code_safety(det_fix)
                        if not det_violations:
                            current_code = det_fix
                            _repair_trail.append({"attempt": attempt, "fix_source": "deterministic"})
                            logger.info("Deterministic fix applied for: %s", error_msg[:100])
                            continue

                    # Attempt 3: reroute the immutable Wiki with error context for
                    # an alternate verified pattern. No vector/embedding fallback.
                    repair_context = system_context
                    if attempt >= 2 and self._prompt_assembler and user_query:
                        try:
                            from kukai.rag.wiki_router import get_wiki_router

                            alt_query = f"{user_query} {error_msg[:200]}"
                            alt_wiki, alt_telemetry = await asyncio.to_thread(
                                get_wiki_router().inject,
                                alt_query,
                                revit_version=self._revit_version,
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
                                    "Repair attempt %d: Wiki reroute pages=%s release=%s",
                                    attempt,
                                    alt_telemetry.get("routed_pages"),
                                    alt_telemetry.get("release_id"),
                                )
                        except Exception:
                            pass  # Fall back to original context

                    # G2.3: deterministic API-surface facts for member/type errors
                    # (CS0117/CS1061/CS0246) — real members of the named type for
                    # THIS Revit version + fuzzy "did you mean" + cross-version note.
                    # Built from tools/api-extractor surfaces; no model opt-in.
                    try:
                        from kukai.llm.api_members import enrich_compile_error
                        _api_hint = enrich_compile_error(error_msg, self._revit_version)
                        if _api_hint:
                            repair_context = repair_context + "\n\n" + _api_hint
                            logger.info("Repair attempt %d: injected real-API facts", attempt)
                    except Exception as _api_exc:  # noqa: BLE001
                        logger.debug("api_members enrich failed (non-fatal): %s", _api_exc)

                    repaired = await self._repair_code(
                        current_code, error_msg, attempt,
                        user_query=user_query,
                        system_context=repair_context,
                    )
                    if repaired:
                        # Apply deterministic fixes to repaired code too —
                        # repair LLM may reproduce the same mistakes that fixer handles
                        from kukai.security.code_fixer import RevitCodeFixer
                        repair_fixer = RevitCodeFixer(revit_version=self._revit_version)
                        repaired = repair_fixer.fix(repaired)
                        # Re-validate repaired code
                        repair_violations = validate_code_safety(repaired)
                        if repair_violations:
                            logger.warning("Repaired code failed safety check")
                            break
                        current_code = repaired
                        _repair_trail.append({"attempt": attempt, "fix_source": "llm_repair"})
                        continue

                # Success or non-repairable error
                # For runtime errors, add hints so Gemini can self-correct
                if isinstance(result, dict) and result.get("error"):
                    result["message"] = _enrich_runtime_error(result.get("message", ""))
                else:
                    # Verified-recipe collection — closing the prod-feedback loop.
                    # NOTE (corpus-integrity, 2026-07-07): this LEGACY inline path
                    # is dead in prod (KUKAI_EXEC_PIPELINE=1 returns via the
                    # pipeline before this branch) AND computes no expects-witness,
                    # so it captures on "not error" as before. The WITNESSED,
                    # gated capture lives in RevitExecutionPipeline._maybe_record_recipe
                    # (KUKAI_RECIPE_WITNESS). Do not add unwitnessed corpus writes here.
                    # Best-effort: never block the response on collection failure.
                    # Capture execution evidence without coupling the write path
                    # back to retired retrieval telemetry.
                    try:
                        from kukai.recipes_collector import record_verified_recipe
                        record_verified_recipe(
                            query_ru=user_query or "",
                            query_en=None,
                            code=current_code,
                            intent_metadata=_turn_intent_metadata.get(),
                            revit_version=self._revit_version,
                            session_id=_active_session_id.get(),
                            exec_time_ms=_exec_ms,
                            n_repairs=attempt - 1,
                            query_id=None,
                            retrieval_keys=None,
                        )
                    except Exception as _rec_exc:  # noqa: BLE001
                        logger.debug("verified-recipe write failed (non-fatal): %s",
                                     _rec_exc)
                # Envelope (additive): machine err.code on error returns +
                # execution.final_code whenever the harness rewrote the model's
                # code before it ran (so the model treats final_code, not its
                # original, as the authoritative pattern next turn).
                if isinstance(result, dict):
                    if result.get("error"):
                        _msg = result.get("message", "")
                        attach_err(
                            result,
                            ErrCode.COMPILE_CS_ERROR if self._is_compilation_error(result)
                            else ErrCode.RUNTIME_REVIT_EXCEPTION,
                            cs_codes=extract_cs_codes(_msg),
                        )
                    if current_code != original_code:
                        result["execution"] = {
                            "final_code": current_code,
                            "was_modified": True,
                            "repairs": _repair_trail,
                        }
                return result

            # If all repair attempts failed, provide a helpful error to the LLM
            if isinstance(result, dict) and result.get("error"):
                original_error = result.get("message", "Unknown error")
                result["message"] = (
                    f"Код не удалось скомпилировать после 3 попыток исправления. "
                    f"Ошибка: {original_error[:300]}. "
                    f"Попробуй другой подход к решению задачи."
                )
                # Add Russian translation for common C# error codes
                cs_match = re.search(r'(CS\d{4})', original_error)
                if cs_match:
                    error_code = cs_match.group(1)
                    if error_code in _CS_ERROR_TRANSLATIONS:
                        result["message"] += f" ({_CS_ERROR_TRANSLATIONS[error_code]})"
                # Exhausted the repair budget — NOT retryable; the model must
                # change approach (the prose already says so; here it's machine
                # readable). cs_codes from the ORIGINAL error, before we wrapped
                # the message in the "попробуй другой подход" prose.
                attach_err(
                    result,
                    ErrCode.COMPILE_FAILED_AFTER_REPAIRS,
                    cs_codes=extract_cs_codes(original_error),
                )
                if current_code != original_code:
                    result["execution"] = {
                        "final_code": current_code,
                        "was_modified": True,
                        "repairs": _repair_trail,
                    }
            return result

        elif tool_name == "get_model_info":
            if bridge_callback:
                return await bridge_callback("context", {})
            else:
                result = await self._bridge.context()  # type: ignore[union-attr]
                return result.model_dump()

        elif tool_name == "get_model_details":
            # On-demand full passport. Served locally from the session's cached
            # detailed passport (chat_ws intercepts this method — no Revit
            # round-trip). The brief passport is injected by default; this is
            # how the LLM pulls the heavy ~20K detail only when it needs it.
            section = (args.get("section") or "full").strip().lower()
            if bridge_callback:
                return await bridge_callback("get_model_details", {"section": section})
            return {"error": True, "message": "Детальный паспорт недоступен (нет активной сессии)."}

        elif tool_name == "select_elements":
            element_ids = args.get("element_ids", [])
            if bridge_callback:
                return await bridge_callback("select", {"element_ids": element_ids})
            else:
                result = await self._bridge.select(element_ids)  # type: ignore[union-attr]
                return result.model_dump()

        elif tool_name == "highlight_elements":
            element_ids = args.get("element_ids", [])
            color = args.get("color")
            clear_previous = args.get("clear_previous", True)
            if bridge_callback:
                return await bridge_callback("highlight", {
                    "element_ids": element_ids,
                    "color": color or {"r": 255, "g": 0, "b": 0},
                    "clear_previous": clear_previous,
                })
            else:
                result = await self._bridge.highlight(element_ids, color, clear_previous)  # type: ignore[union-attr]
                return result.model_dump()

        elif tool_name == "apply_revit_write":
            # NAV-V2 part 4 (KUKAI_NAV_V2, default OFF): hide_or_isolate has no
            # 'select' verb of its own (generate_hide_or_isolate_code only emits
            # HideElements/IsolateElementsTemporary), so an implicit isolate — the
            # user never said "изолируй"/"isolate" this turn — is REDIRECTED to a
            # plain select (mirrors the select_elements tool) instead of relabeling
            # an argument. This is the single funnel both isolate paths dispatch
            # through, and `user_query` (the turn's text) is already in scope here
            # — no new plumbing needed. Fail-open: any error falls through to the
            # untouched apply_revit_write path. The empty-element-set guard inside
            # _execute_apply_revit_write is untouched (only a non-empty set coerces).
            try:
                from kukai.llm import nav_v2 as _nav_v2
                if (_nav_v2.nav_v2_enabled() and isinstance(args, dict)
                        and args.get("operation") == "hide_or_isolate"
                        and _nav_v2.should_coerce_hide_or_isolate(
                            args.get("view_action") or "hide",
                            args.get("element_ids"), user_query)):
                    logger.info("NAV_V2: isolate->select coerced (hide_or_isolate)")
                    _sel_ids = args.get("element_ids", [])
                    if bridge_callback:
                        _sel_res = await bridge_callback("select", {"element_ids": _sel_ids})
                    else:
                        _sel_res = (await self._bridge.select(_sel_ids)).model_dump()  # type: ignore[union-attr]
                    if isinstance(_sel_res, dict):
                        _sel_res.setdefault("action", "selected")
                        _sel_res["coerced_from"] = "isolate"
                    return _sel_res
            except Exception:  # noqa: BLE001 — coercion must never break the write
                logger.debug("NAV_V2 isolate coercion (hide_or_isolate) skipped", exc_info=True)
            return await self._execute_apply_revit_write(args, bridge_callback)

        elif tool_name == "query_model":
            # NAV-V2 part 4: query_model's own `action` enum already has "select" —
            # a pure string swap, no redirect needed. Same funnel/rationale as above.
            try:
                from kukai.llm import nav_v2 as _nav_v2
                if (_nav_v2.nav_v2_enabled() and isinstance(args, dict)
                        and (args.get("action") or "").strip().lower() == "isolate"):
                    _coerced, _was_coerced = _nav_v2.coerce_query_model_action("isolate", user_query)
                    if _was_coerced:
                        logger.info("NAV_V2: isolate->select coerced (query_model)")
                        args = {**args, "action": _coerced}
            except Exception:  # noqa: BLE001 — coercion must never break the query
                logger.debug("NAV_V2 isolate coercion (query_model) skipped", exc_info=True)
            # KIR shadow (KUKAI_KIR_TOOL=shadow, default off): observe-only
            # applicability probe, ABSOLUTE fail-open — the real query below
            # runs identically whether this succeeds, refuses, or explodes.
            try:
                from kukai.ir import shadow as _kir_shadow
                _kir_shadow.observe_query_model(
                    args, revit_version=self._revit_version, user_query=user_query)
            except Exception:  # noqa: BLE001 — shadow must never touch the turn
                logger.debug("KIR shadow skipped", exc_info=True)
            return await self._execute_query_model(args, bridge_callback)

        elif tool_name == "revit_ir":
            # KIR stage 2 (device-gated). Handler is ABSOLUTE fail-open and
            # returns typed dicts only — a refusal carries handoff and the
            # turn continues on the recipe path.
            try:
                import hashlib as _hl
                from kukai.ir import serving as _kir_serving
                return await _kir_serving.handle_revit_ir(
                    args, self, bridge_callback,
                    query_id=_hl.sha1((user_query or "").encode(
                        "utf-8", "replace")).hexdigest()[:16])
            except Exception:  # noqa: BLE001 — never break the turn
                logger.exception("revit_ir dispatch failed")
                return {"ok": False, "error": "internal",
                        "message_ru": "KIR недоступен — используй обычные инструменты"}

        elif tool_name == "inspect":
            return await self._execute_inspect(args, bridge_callback)

        elif tool_name == "export_view":
            filename = args.get("filename", "kukai_export.png")
            fmt = args.get("format", "png")
            if bridge_callback:
                _shot = await _shot_via_exec(bridge_callback)
                if _shot is None:
                    _shot = await bridge_callback(
                        "export_view", {"filename": filename, "format": fmt})
                # The PNG must reach the model as an IMAGE, not as base64 inside a
                # tool result: that text is truncated by _smart_truncate anyway, so
                # today it costs tokens and shows nothing. Hold it here; the round
                # loop attaches it as a real image message right after this result.
                if isinstance(_shot, dict) and _shot.get("image_base64"):
                    try:
                        _pending_view_image.set(str(_shot["image_base64"]))
                    except Exception:  # noqa: BLE001
                        pass
                    _shot = {k: v for k, v in _shot.items() if k != "image_base64"}
                    _shot["message"] = "Снимок вида сделан — изображение приложено следующим сообщением."
                return _shot
            elif self._bridge:
                result = await self._bridge.export_view(filename, fmt)
                return result.model_dump()
            return {"error": True, "message": "Revit не подключён"}

        elif tool_name == "import_cad":
            file_path = args.get("file_path", "")
            if not file_path:
                return {"error": True, "message": "Укажите путь к файлу"}
            if not file_path.lower().endswith((".dwg", ".dxf")):
                return {"error": True, "message": "Поддерживаются только файлы .dwg и .dxf"}
            if bridge_callback:
                return await bridge_callback("import_cad", {"file_path": file_path})
            elif self._bridge:
                result = await self._bridge.import_cad(file_path)
                return result.model_dump()
            return {"error": True, "message": "Revit не подключён"}

        elif tool_name == "process_uploaded_file":
            return await self._execute_process_file(args)

        else:
            return {"error": True, "message": f"Неизвестный инструмент: {tool_name}"}

    # ── Step 2 (2026-07-04 decomposition): the local tool handlers moved to
    # kukai.llm.tool_handlers.{revit_verbs,files_excel,norms} — pure relocation.
    # Bodies are byte-identical and keep ``self`` as their first parameter, so
    # rebinding them as plain class attributes makes them the SAME bound
    # methods as before for the dispatcher (_execute_tool), the tests, and any
    # external caller. Instance-level stubbing (client._execute_X = ...) keeps
    # overriding these exactly as it did the original defs.
    _execute_query_model = _th_revit_verbs._execute_query_model
    _execute_inspect = _th_revit_verbs._execute_inspect
    _execute_apply_revit_write = _th_revit_verbs._execute_apply_revit_write
    _execute_export_sheets_pdf = _th_revit_verbs._execute_export_sheets_pdf
    _execute_process_file = _th_files_excel._execute_process_file
    # _execute_generate_report stays IN client.py (not moved):
    # tests/test_step6_bridge_cancel.py::test_generate_report_filename_is_sanitized
    # pins the filename-sanitization line to THIS file's source text — the same
    # freeze class as test_repair_loop's getsource pin on _execute_tool.
    async def _execute_generate_report(self, args: dict[str, Any]) -> dict[str, Any]:
        """Generate an Excel report via FileProcessor and return a download URL."""
        from kukai.files.processor import FileProcessor
        from kukai.config import get_settings

        sheets = args.get("sheets", [])
        data = args.get("data", [])
        # Step 6: the filename is LLM-controlled and flows into files_dir/{id}_{name};
        # strip ALL directory components so an embedded ../ can't escape files_dir.
        # (os is module-level; Path is only imported locally in other methods.)
        filename = os.path.basename(args.get("filename", "report.xlsx") or "report.xlsx") or "report.xlsx"
        sheet_name = args.get("sheet_name", "Report")
        sort_by = args.get("sort_by", "")
        sort_order = args.get("sort_order", "asc")
        operations = args.get("operations", [])

        # If we have stored large result from previous execute_revit_code — prefer it
        # over Gemini's truncated data. Gemini only sees ~20 rows in context but the
        # full dataset (thousands of rows) is stored in _last_large_result.
        stored = getattr(self, '_last_large_result', None)
        if stored and not sheets:
            stored_list = None
            if isinstance(stored, list):
                stored_list = stored
            elif isinstance(stored, dict):
                for v in stored.values():
                    if isinstance(v, list) and (not stored_list or len(v) > len(stored_list)):
                        stored_list = v
            # Use stored data if it has more rows than what Gemini sent
            if stored_list and len(stored_list) > len(data):
                logger.info("generate_report: using stored large result (%d items vs %d from Gemini)", len(stored_list), len(data))
                data = stored_list
                self._last_large_result = None

        # Multi-sheet mode
        MAX_ROWS_PER_SHEET = 50_000
        if sheets:
            valid_sheets = [s for s in sheets if s.get("data")]
            if not valid_sheets:
                return {"error": True, "message": "No data in any sheet"}
        elif data:
            valid_sheets = [{"name": sheet_name, "data": data}]
        else:
            return {"error": True, "message": "No data provided for report generation"}

        # Cap row count to prevent OOM on huge datasets
        for sheet in valid_sheets:
            if len(sheet.get("data", [])) > MAX_ROWS_PER_SHEET:
                sheet["data"] = sheet["data"][:MAX_ROWS_PER_SHEET]

        if not filename.endswith(".xlsx"):
            filename += ".xlsx"

        settings = get_settings()
        processor = FileProcessor(files_dir=settings.get_files_dir())

        try:
            import base64
            if len(valid_sheets) == 1:
                file_id, file_path = processor.generate_excel(
                    data=valid_sheets[0]["data"], filename=filename,
                    sheet_name=valid_sheets[0].get("name", "Report"),
                )
            else:
                file_id, file_path = processor.generate_multi_sheet_excel(
                    sheets=valid_sheets, filename=filename,
                )
            # Read file bytes
            file_bytes = file_path.read_bytes() if hasattr(file_path, 'read_bytes') else open(str(file_path), 'rb').read()

            # Apply Excel operations (sort, pivot, conditional format, etc.)
            all_ops = list(operations) if operations else []
            if sort_by:
                all_ops.insert(0, {"type": "sort", "column": sort_by, "order": sort_order})
            if all_ops:
                try:
                    from kukai.files.excel_ops import apply_excel_operations
                    file_bytes = apply_excel_operations(file_bytes, all_ops)
                    # Save modified file back to disk
                    with open(str(file_path), 'wb') as f:
                        f.write(file_bytes)
                    logger.info("Applied %d Excel operations to %s", len(all_ops), filename)
                except Exception as ops_err:
                    logger.warning("Excel operations failed (file still usable): %s", ops_err)

            # Store for modify_excel post-processing
            self._last_generated_excel_bytes = file_bytes
            self._last_generated_excel_filename = filename

            file_b64 = base64.b64encode(file_bytes).decode('ascii')
            total_rows = sum(len(s.get("data", [])) for s in valid_sheets)

            # Send file to client via WebSocket (save_file message triggers download)
            _ws = _active_ws.get()
            if _ws:
                try:
                    await _ws.send_text(json.dumps({
                        "type": "save_file",
                        "filename": filename,
                        "data": file_b64,
                    }, ensure_ascii=False))
                    logger.info("Sent save_file WS message: %s (%d bytes)", filename, len(file_bytes))
                except Exception as ws_err:
                    logger.warning("Failed to send save_file via WS: %s", ws_err)

            # Return summary to LLM WITHOUT the base64 blob
            return {
                "success": True,
                "filename": filename,
                "rows_count": total_rows,
                "sheets_count": len(valid_sheets),
                "message": f"Файл {filename} готов и отправлен на скачивание ({total_rows} строк, {len(valid_sheets)} листов).",
            }
        except Exception as e:
            logger.exception("Report generation error")
            return {"error": True, "message": "Ошибка генерации отчёта. Попробуйте позже."}

    _execute_modify_excel = _th_files_excel._execute_modify_excel
    _execute_excel_script = _th_files_excel._execute_excel_script
    _execute_send_local_file = _th_files_excel._execute_send_local_file
    _execute_lookup_norm = staticmethod(_th_norms._execute_lookup_norm)

    # The former RU→EN translation/cache/bilingual-join block lived here.
    # It was part of vector RAG's 10-second pre-token critical path. Wiki uses
    # the original request directly, so keeping that callable network path in
    # the production client would be both dead code and an accidental rollback
    # hazard. Offline legacy retrieval experiments remain isolated under
    # kukai.rag; LLMClient deliberately exposes no translation seam.
    async def _simple_completion(self, messages: list[dict]) -> str:
        """Simple non-streaming LLM completion for internal use (VOR experts)."""
        try:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 65536,
                "stream": False,
            }
            if self._api_key:
                kwargs["api_key"] = self._api_key
            if self._api_base:
                kwargs["api_base"] = self._api_base

            response = await self._call_llm_with_fallback(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.warning("Simple completion failed: %s", e)
            return ""

    # Moved to kukai.llm.repair_knowledge (2026-07-04 decomposition, Step 1 —
    # pure relocation). Rebound as staticmethods so `self._is_compilation_error`
    # / `self._get_repair_hint` and the `LLMClient._X` test surface are
    # unchanged. The bare names resolve to the module-level re-imports above.
    _is_compilation_error = staticmethod(_is_compilation_error)
    _get_repair_hint = staticmethod(_get_repair_hint)

    async def _repair_code(
        self,
        original_code: str,
        error: str,
        attempt: int,
        user_query: str = "",
        system_context: str = "",
    ) -> Optional[str]:
        """Attempt to repair failed C# code using the SAME knowledge as the original LLM.

        Uses the original system prompt (with Wiki knowledge, model passport and
        all rules), plus compile-error facts and a verified recipe example.
        """
        # Build error-specific hint
        error_hint = self._get_repair_hint(error)

        # Structural repair hint from a routed, verified Wiki card. A concrete
        # compiling example anchors the repair without touching legacy vectors.
        if (os.environ.get("KUKAI_WIKI_STRUCTURAL_REPAIR", "1") != "0"
                and self._prompt_assembler and user_query):
            try:
                from kukai.rag.wiki_router import get_wiki_router

                examples = await asyncio.to_thread(
                    get_wiki_router().recipe_examples,
                    f"{user_query} {error[:300]}",
                    max_examples=1,
                )
                if examples and examples[0].get("example_code"):
                    example = examples[0]
                    structural = (
                        "\n\nПРОВЕРЕННЫЙ WIKI-ЭТАЛОН "
                        f"({example.get('name')}, {example.get('compiles')}):\n"
                        "Адаптируй паттерн под задачу; не копируй лишние операции.\n"
                        f"```csharp\n{example['example_code']}\n```"
                    )
                    error_hint = (error_hint or "") + structural
                    logger.info(
                        "Wiki structural repair example applied: %s release=%s",
                        example.get("name"), example.get("release_id"),
                    )
            except Exception as _exc:
                logger.debug("Wiki structural repair hint failed (non-fatal): %s", _exc)

        # Use the ORIGINAL system prompt that the main LLM had.
        # This includes code_generation.md, Wiki context, passport and version info.
        # Repair now knows EVERYTHING the original LLM knew, plus the specific error.
        repair_instruction = (
            "РЕЖИМ ИСПРАВЛЕНИЯ КОДА.\n"
            "Код ниже не скомпилировался. Исправь ТОЛЬКО ошибку. "
            "Не переписывай весь код — измени минимум.\n"
            "Верни ТОЛЬКО чистый C# код (тело метода). "
            "БЕЗ ```markdown```. БЕЗ using/namespace/class.\n"
            + (f"\n{error_hint}" if error_hint else "")
        )

        if system_context:
            # Full context: original system prompt + repair instructions
            system_content = system_context + "\n\n" + repair_instruction
        else:
            # Fallback if system_context not available
            system_content = (
                f"Ты исправляешь C# код для Revit {self._revit_version or ''}. "
                "Код = тело метода Execute(Document doc, UIDocument uidoc).\n"
                + repair_instruction
            )

        repair_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": (
                f"Код не скомпилировался.\n\n"
                + (f"Оригинальный запрос пользователя: {user_query}\n\n" if user_query else "")
                + f"Ошибка:\n{error}\n\n"
                f"Код:\n```csharp\n{original_code}\n```\n\n"
                f"Попытка {attempt} из 3.\n"
                f"Исправь и верни только код."
            )},
        ]

        repair_kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": repair_messages,
            "max_tokens": 8192,  # was 2048 — starved repairs to "no code in response"
            "temperature": 0.1,
            "timeout": 60.0,
            "stream": False,
        }
        if self._api_key:
            repair_kwargs["api_key"] = self._api_key
        if self._api_base:
            repair_kwargs["api_base"] = self._api_base

        # Repair on the brain that wrote the code. See codex_route.side_call_kwargs
        # for the measurement that motivated this (112s repairs that returned no
        # code at all, while the proxy answers in 2-5s).
        try:
            from kukai.llm import codex_route as _cx

            _overlay = _cx.side_call_kwargs()
        except Exception:  # noqa: BLE001 — repair must never break on its own router
            _overlay = None
        if _overlay:
            repair_kwargs.update(_overlay)
            logger.info("REPAIR on codex (attempt %d, same model that wrote the code)", attempt)

        try:
            response = await self._call_llm_with_fallback(**repair_kwargs)

            content = response.choices[0].message.content or ""

            # Extract code from response (may be wrapped in ```csharp ... ```)
            code_match = re.search(r'```(?:csharp|cs)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            if code_match:
                repaired = code_match.group(1).strip()
                logger.info("REPAIR SUCCESS (attempt %d):\n%s", attempt, repaired[:300])
                return repaired

            # If no code block, use the entire response if it looks like code
            # Strip any stray backticks/markdown that LLM might include
            content = re.sub(r'^```(?:csharp|cs)?\s*\n?', '', content.strip())
            content = re.sub(r'\n?```\s*$', '', content.strip())
            content = content.strip()
            if content and ("return" in content or "var " in content):
                logger.info("REPAIR SUCCESS raw (attempt %d):\n%s", attempt, content[:300])
                return content

            logger.warning("REPAIR FAILED (attempt %d): no code in response", attempt)
            return None
        except Exception:
            logger.warning("Repair LLM call failed (attempt %d)", attempt)
            return None

    async def simple_chat(
        self,
        messages: list[dict[str, Any]],
        context: Optional[ContextResult] = None,
        preferences: Optional[dict[str, Any]] = None,
        units: str = "metric",
        active_extension: Optional[str] = None,
        extension_profile: Optional[str] = None,
        image_attachments: Optional[list[dict[str, str]]] = None,
        uploaded_file_bytes: Optional[bytes] = None,
    ) -> str:
        """Non-streaming chat completion (HTTP fallback). Returns full text response.

        Collects stream_chunk text AND tool call results into a single string.

        ``image_attachments`` — optional list of ``{"data_url": "...", "filename": "..."}``
        dicts. When present, the LAST user message in ``messages`` is rewritten
        from a plain string into the multimodal content list Gemini expects
        (text part + image_url parts). The rest of the pipeline (tool loop,
        RAG, repair) keeps working because litellm accepts both string and
        list-shaped ``content``.
        """
        if image_attachments:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    text_part = messages[i].get("content", "")
                    parts: list[dict[str, Any]] = []
                    if isinstance(text_part, str) and text_part:
                        parts.append({"type": "text", "text": text_part})
                    elif isinstance(text_part, list):
                        parts.extend(text_part)
                    for att in image_attachments:
                        url = att.get("data_url")
                        if not url:
                            continue
                        parts.append({
                            "type": "image_url",
                            "image_url": {"url": url},
                        })
                    messages[i] = {**messages[i], "content": parts}
                    break

        # Honour the UI-selected mode (fast/thinking) on the HTTP path too,
        # so /chat behaves the same as the WebSocket path for smoke tests
        # and any clients that fall back to HTTP.
        # Family-editor auto-override: forces thinking mode when context shows
        # is_family_editor=True (matches the WS path behaviour in chat_ws.py).
        _user_thinking_pref = bool((preferences or {}).get("thinking", False))
        _is_family_editor = bool(context and getattr(context, "is_family_editor", False))
        _thinking_mode = _user_thinking_pref or _is_family_editor

        full_text = ""
        tool_results: list[str] = []
        async for event in self.stream_chat(
            messages,
            context,
            preferences,
            units,
            active_extension=active_extension,
            extension_profile=extension_profile,
            thinking_mode=_thinking_mode,
            uploaded_file_bytes=uploaded_file_bytes,
        ):
            if event.type == "stream_chunk":
                full_text += event.data
            elif event.type == "tool_end" and isinstance(event.data, dict):
                # Collect tool results so they appear in the final response
                tool_results.append(json.dumps(event.data, ensure_ascii=False))
            elif event.type == "error":
                raise RuntimeError(event.data)
        # If LLM called tools but produced no text, return tool results summary
        if not full_text.strip() and tool_results:
            full_text = "\n".join(tool_results)
        return full_text


# ── Golden-path C1 (2026-07-13): non-yielding ROUND-LOOP segments, extracted ─
# from _stream_chat_inner's agent round loop as named module-level functions.
# Bodies are byte-identical to the inline originals (their comments moved with
# them); segments that YIELD stay inline — moving a yielding loop into a
# sub-generator would change asend/athrow semantics, so the loop itself stays
# a loop and only non-yielding concerns became named functions of RoundState.
# NOTE: `RoundState` (kukai/turn/context.py) appears below only in annotations
# (lazy under `from __future__ import annotations`); the one runtime import
# lives inside `_init_round_state` so the module import block above the
# preflight zone stays byte-untouched.


def _dedup_signature(tool_name: str, args_str: Optional[str]) -> str:
    """M2 dedup: whitespace-normalized, case-folded signature of ONE tool call
    (C1: the inline expression from the round loop, verbatim)."""
    return tool_name + "|" + " ".join((args_str or "").split()).lower()


def _attach_round_budget(state: RoundState, result: dict[str, Any]) -> None:
    # Budget block: every dict tool result carries the turn's
    # round accounting so the model can self-pace. setdefault →
    # never overwrite a budget a producer already set.
    result.setdefault(
        "budget",
        {"rounds_used": state.tool_round, "rounds_max": state.effective_max_rounds},
    )


def _count_world_tool_success(state: RoundState, tool_name: str) -> None:
    # Step 8: count this SUCCESSFUL call toward the turn's
    # world-witness total (fake-готово fires only at zero).
    # Fail-open in the counting direction: if the classifier
    # import breaks, COUNT the call — that can only suppress
    # a detection, never manufacture one.
    try:
        from kukai.will.truth_gate import is_world_tool as _tg_is_world
        if _tg_is_world(tool_name):
            state.world_tools_ok += 1
    except Exception:  # noqa: BLE001 — never break the turn
        state.world_tools_ok += 1


# Screenshot produced by export_view in THIS round, waiting to be handed to the
# model as an actual image. Per-turn ContextVar, not an attribute on the shared
# client: two users' turns run concurrently on one LLMClient.
_pending_view_image: ContextVar[Optional[str]] = ContextVar("_kukai_pending_view_image", default=None)


# ── the shot ────────────────────────────────────────────────────────────────
#
# What the model was being handed (pulled and looked at, 2026-07-27): a
# hidden-line WIREFRAME in which the building occupied ~8% of the frame, the
# rest a fan of level lines. Nothing reads a silhouette off that — and the turn
# then burns rounds trying to fix the view itself (measured: 7 exports / 219s in
# one "посмотри на здание" turn; earlier the same day it hid 10 categories to
# clean the picture and had to restore them afterwards).
#
# Three corrections, all measured on the operator's live model:
#   * SHADE a wireframe/HLR view for the duration of the shot, then put the
#     user's style back. This is the big one — line drawing → solid massing.
#   * TRIM the empty margins server-side. Revit's ExportImage fits the view's
#     own extents and ignores both the UI zoom (ZoomAndCenterRectangle) and a
#     section box — verified, the exported bytes were identical with and
#     without both. Cropping the render is the one framing lever that actually
#     works: 18% of the frame → the building filling it.
#   * Render at 2200px (0.6s on this model) so the trimmed crop still carries
#     ~700px of detail.
#
# It also goes through `execute` rather than the `export_view` bridge method,
# because that method returns "produced no new image" while the SAME
# ImageExportOptions run through execute writes the file every time (verified
# repeatedly, 2026-07-27). Falls back to the bridge method if this path fails.
_SHOT_FLAG = "KUKAI_VISION_SHOT"          # "exec" (default) | "bridge"
_SHOT_PIXELS = "KUKAI_VISION_SHOT_PIXELS"  # render width before trimming

_SHOT_CS = """
var res = new Dictionary<string,object>();
var v = doc.ActiveView;
if (v == null) { res["error"] = true; res["message"] = "Нет активного вида"; return res; }
res["view"] = v.Name; res["view_type"] = v.ViewType.ToString();

string styleWas = v.DisplayStyle.ToString();
bool shaded = false;
if (v is View3D && (v.DisplayStyle == DisplayStyle.Wireframe || v.DisplayStyle == DisplayStyle.HLR)) {
    try {
        using (var t = new Transaction(doc, "KUKAI: shade for inspection")) {
            t.Start(); v.DisplayStyle = DisplayStyle.ShadingWithEdges; t.Commit();
        }
        shaded = true;
    } catch (Exception se) { res["shade_error"] = se.Message; }
}
res["shaded"] = shaded; res["style_was"] = styleWas;

string dir = System.IO.Path.Combine(
    Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), "KUKI", "exports");
if (!System.IO.Directory.Exists(dir)) System.IO.Directory.CreateDirectory(dir);
string stem = "kukai_shot_" + Guid.NewGuid().ToString("N").Substring(0, 8);
try {
    var o = new ImageExportOptions {
        FilePath = System.IO.Path.Combine(dir, stem),
        ExportRange = ExportRange.SetOfViews,
        ZoomType = ZoomFitType.FitToPage,
        FitDirection = FitDirectionType.Horizontal,
        PixelSize = __PIXELS__,
        ImageResolution = ImageResolution.DPI_72,
        HLRandWFViewsFileType = ImageFileType.PNG,
        ShadowViewsFileType = ImageFileType.PNG };
    o.SetViewsAndSheets(new List<ElementId> { v.Id });
    doc.ExportImage(o);
} catch (Exception ee) { res["export_error"] = ee.GetType().Name + ": " + ee.Message; }

string made = null;
foreach (var f in System.IO.Directory.GetFiles(dir, stem + "*")) { made = f; break; }
if (made != null) {
    try {
        var bytes = System.IO.File.ReadAllBytes(made);
        res["image_base64"] = Convert.ToBase64String(bytes);
        res["bytes"] = bytes.Length;
        try { System.IO.File.Delete(made); } catch {}
    } catch (Exception re) { res["read_error"] = re.Message; }
} else {
    res["error"] = true;
    res["message"] = "ExportImage не создал файл для вида '" + v.Name + "'";
}

if (shaded) {
    try {
        using (var t = new Transaction(doc, "KUKAI: restore view style")) {
            t.Start(); v.DisplayStyle = (DisplayStyle)Enum.Parse(typeof(DisplayStyle), styleWas); t.Commit();
        }
        res["style_restored"] = true;
    } catch (Exception re2) { res["restore_error"] = re2.Message; }
}
return res;
"""


def _codex_base_prompt() -> Optional[str]:
    """The Codex route's own base prompt, or None to keep the shared one.

    Written deliberately from the failure classes measured on 2026-07-27 rather
    than grown by accretion: announce-instead-of-act, ask-permission-for-what-was-
    asked, fake-the-result-when-blocked, destroy-good-work-while-cleaning,
    describe-what-was-never-seen, reach-for-C#-when-a-typed-op-exists, report
    "Готово" unverified, retry blind instead of reading the diagnostic.

    It is a REPLACEMENT for the shared `base`, not an addition: 8k chars against
    17k, because half the old text argues for a workflow (one big script, plan
    first) that the typed path and the self-check loop replaced. The per-turn
    data blocks — passport, model context, version notes, wiki — are untouched:
    those are facts, not behaviour.

    This is the fleet's future prompt being proven on one device first. When
    mimo goes, it becomes the only one.
    """
    if os.getenv("KUKAI_CODEX_PROMPT", "1") == "0":
        return None
    try:
        from kukai.llm import codex_route as _cx

        if not _cx.device_eligible():
            return None
        from pathlib import Path as _P

        p = _P(__file__).resolve().parent.parent.parent / "prompts" / "system_codex.md"
        text = p.read_text(encoding="utf-8").strip()
        return text or None
    except Exception:  # noqa: BLE001 — a missing file must not break the turn
        logger.debug("codex base prompt unavailable — keeping the shared one",
                     exc_info=True)
        return None


#: Prompt components that contradict how a given route is asked to behave.
#: Not a second system prompt — one base, minus the paragraphs that fight the
#: route's own instructions.
_ROUTE_CONFLICTS: dict[str, tuple[str, ...]] = {
    # G4 `g4_plan` tells the model to think the whole plan first and then do the
    # job in ONE script, explicitly discouraging "осмотр→действие→осмотр". The
    # Codex route is then handed the opposite instruction (act now, call tools
    # one after another, finish the task) — and everything built today assumes
    # iteration: the self-check loop, KIR's ≤20-op programs, look-then-fix. So
    # the same prompt said X and not-X, and the model that follows instructions
    # most literally lost: measured 2026-07-27, four turns in a row answering
    # "Сделаю в 3 шага: …" with zero tool calls. mimo ignores the directive and
    # iterates, which is why only Codex looked "lazy". Remove the contradiction
    # instead of shouting over it.
    "codex": ("g4_plan",),
}


def _drop_conflicting_components(assembled: Any) -> Any:
    """Give the Codex route its own base prompt and drop what argues with it."""
    if os.getenv("KUKAI_ROUTE_PROMPT_TRIM", "1") == "0":
        return assembled
    try:
        from kukai.llm import codex_route as _cx

        if not _cx.device_eligible():
            return assembled                      # every other turn untouched
        drop = _ROUTE_CONFLICTS["codex"]
        own_base = _codex_base_prompt()
        kept: list[Any] = []
        swapped = False
        for c in assembled.components:
            name = getattr(c, "name", "")
            if name in drop:
                continue
            if name == "base" and own_base:
                kept.append(type(c)("base", own_base, c.layer))
                swapped = True
                continue
            kept.append(c)
        if len(kept) == len(assembled.components) and not swapped:
            return assembled
        logger.info("route prompt codex: %s%s",
                    "своя база" if swapped else "база общая",
                    f", убрано: {', '.join(drop)}" if len(kept) != len(assembled.components) else "")
        return type(assembled)(components=kept)
    except Exception:  # noqa: BLE001 — prompt assembly must never break the turn
        logger.debug("route prompt trim skipped", exc_info=True)
        return assembled


_SIZE_CS = """
var res = new Dictionary<string,object>();
int n = 0;
foreach (Element e in new FilteredElementCollector(doc).WhereElementIsNotElementType()) {
    var c = e.Category;
    if (c == null || c.CategoryType != CategoryType.Model) continue;
    n++;
}
res["model_elements"] = n;
return res;
"""


async def _model_size(bridge_callback) -> Optional[int]:
    """How many model elements the document holds. None if it cannot be read."""
    try:
        from kukai.operations.effects import ReadOnlySource, mark_read_only

        params = mark_read_only({"code": _SIZE_CS, "timeout_ms": 30000},
                                ReadOnlySource.MODEL_CENSUS)
        r = await bridge_callback("execute", params)
        n = (r or {}).get("model_elements") if isinstance(r, dict) else None
        return int(n) if isinstance(n, (int, float)) else None
    except Exception:  # noqa: BLE001 — a counter must never break the turn
        logger.debug("model size probe failed", exc_info=True)
        return None


_DELETE_CS_RE = re.compile(r"\bdoc\s*\.\s*Delete\s*\(", re.IGNORECASE)


def _deletion_guard(args: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Make raw C# say it means to delete — the way KIR already has to.

    KIR's `delete` op refuses without `allow_destructive: true` in the program
    envelope, so removing elements through the typed path is always a decision.
    Free-form C# had no such gate, and that asymmetry cost real work: asked to
    reshape the tower, the model swept 42 structural members in ONE call
    (`legacyMembersDeleted: 42`) plus six more, and the answer reported only
    "удалены 6 оставшихся элементов" — 49 beams became 28 (2026-07-27). Every
    witness was green, because a delete that lands IS a successful operation.
    This does not forbid deleting; it forbids deleting by accident.

    Returns a typed refusal, or None to let the call through.
    """
    if os.getenv("KUKAI_DELETE_GUARD", "1") == "0":
        return None
    code = str(args.get("code") or "")
    if not _DELETE_CS_RE.search(code):
        return None
    if args.get("allow_destructive") is True:
        logger.info("deletion guard: allow_destructive=true — удаление разрешено явно")
        return None
    logger.info("deletion guard: в коде есть doc.Delete без allow_destructive — отклонено")
    return {
        "error": True,
        "err": {"code": "guard.destructive", "retryable": True, "transient": False},
        "message": (
            "В коде есть doc.Delete, но не заявлено намерение удалять. Удаление — "
            "решение, а не побочный эффект правки.\n"
            "• Если удалять НЕ нужно — убери doc.Delete и повтори.\n"
            "• Если нужно — сначала СКАЖИ пользователю, что и сколько удаляешь, "
            "и передай allow_destructive: true этим же вызовом.\n"
            "• Лучше: удаляй через revit_ir оп `delete` — он требует "
            "allow_destructive в конверте программы и даёт свидетеля."
        ),
    }


_WRITE_TOOLS = ("apply_revit_write", "execute_revit_code", "revit_ir")


#: Two, not three: each unanswered call costs a full bridge timeout (~40 s), so
#: the third attempt buys nothing but another 40 s of silence. One retry covers
#: the genuinely transient case.
_MAX_BRIDGE_SILENCE = 2

_BRIDGE_SILENT_HINT = (
    "Revit не отвечает: подряд несколько операций не получили ответа. "
    "Это не ошибка кода — до Revit вообще ничего не доходит. "
    "ПРЕКРАТИ вызывать инструменты и скажи пользователю: обычно так бывает, "
    "когда в Revit открыт диалог, ждущий ответа, или идёт долгая операция. "
    "Попроси проверить окно Revit, закрыть диалог и повторить. "
    "Не пытайся обойти это другим кодом."
)


def _looks_like_a_silent_bridge(result_str: str) -> bool:
    """Revit never answered — as opposed to answering with an error.

    Both markers come from the same place (`bridge_protocol` on timeout): the
    typed code and the sentence the user-facing layer builds from it. Matching
    either keeps this working if one of them is reworded.
    """
    blob = result_str or ""
    return ("timeout_unconfirmed" in blob
            or "TRANSPORT_BRIDGE_TIMEOUT" in blob
            or "transport.bridge_timeout" in blob
            or "не подтвердил завершение" in blob)


def _looks_like_a_write(tool_name: str, result_str: str) -> bool:
    """Did this successful call CHANGE the model?

    Deliberately conservative — a false positive costs one screenshot, a false
    negative lets an unverified change end the turn. `revit_ir` and
    `execute_revit_code` serve reads as well as writes, so the result has to
    say so: KIR marks a read `witness.read_only`, and a read-only C# run
    reports no created ids and no committed operation.
    """
    if tool_name not in _WRITE_TOOLS:
        return False
    blob = result_str or ""
    if '"read_only": true' in blob:
        return False
    if tool_name == "apply_revit_write":
        return '"error": true' not in blob
    # Every marker here must be a POSITIVE assertion that something changed.
    # `'"changed"'` was in this list and matched `"changed": null`, which the
    # bridge attaches to every result including reads — so a read turn about the
    # roof was classified as a write, the self-check fired, the size delta
    # reported a phantom loss, and the model went and posted PostableCommand.Undo
    # into the operator's live model (2026-07-27, 435s turn). A false positive
    # here is not one wasted screenshot; it is an unasked-for undo.
    return any(mark in blob for mark in (
        '"created_id', '"CommittedVerified"', '"was_modified": true',
        '"geometry_ok": true', '"changed": true', '"deleted": true',
    ))


def _image_mime(image_b64: str) -> str:
    """PNG or JPEG, decided by the magic bytes rather than by assumption."""
    try:
        import base64 as _b64

        head = _b64.b64decode(image_b64[:16] + "==", validate=False)[:3]
        return "image/jpeg" if head[:3] == b"\xff\xd8\xff" else "image/png"
    except Exception:  # noqa: BLE001
        return "image/png"


def _trim_margins(image_b64: str) -> tuple[str, str]:
    """Crop the uniform border off the render. Returns (b64, note).

    Falls back to the original bytes on any problem — a worse picture beats no
    picture, and this runs inside the turn.
    """
    try:
        import base64 as _b64
        import io as _io

        from PIL import Image, ImageChops  # noqa: PLC0415

        raw = _b64.b64decode(image_b64)
        im = Image.open(_io.BytesIO(raw)).convert("RGB")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        mask = ImageChops.difference(im, bg).convert("L").point(lambda p: 255 if p > 8 else 0)
        box = mask.getbbox()
        if not box:
            return image_b64, "пусто"
        w, h = im.size
        pad = 10
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(w, box[2] + pad), min(h, box[3] + pad))
        if (box[2] - box[0]) < 40 or (box[3] - box[1]) < 40:
            return image_b64, "слишком мало содержимого"
        out = im.crop(box)
        # Cap the long side. A trimmed 2200px render came back at 2003×1032 /
        # 303 KB (measured 2026-07-27) — that is a lot of vision tokens per
        # round for detail nobody reads; 1400px keeps the massing legible.
        try:
            cap = int(os.getenv("KUKAI_VISION_SHOT_MAX_PX", "1400"))
        except Exception:  # noqa: BLE001
            cap = 1400
        if cap and max(out.size) > cap:
            scale = cap / float(max(out.size))
            out = out.resize((max(1, int(out.size[0] * scale)),
                              max(1, int(out.size[1] * scale))), Image.LANCZOS)
        buf = _io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        note = f"{w}×{h}→{out.size[0]}×{out.size[1]}"
        # A shaded 1400px render is ~1 MB as PNG (measured: 976 КБ), and that
        # payload sits in the context for the rest of the turn. JPEG carries a
        # massing render just as well at a fraction of the size. The injection
        # site labels the data URL image/png, so only swap when it pays.
        try:
            limit = int(os.getenv("KUKAI_VISION_SHOT_MAX_KB", "300")) * 1024
        except Exception:  # noqa: BLE001
            limit = 300 * 1024
        png = buf.getvalue()
        if limit and len(png) > limit:
            jbuf = _io.BytesIO()
            out.convert("RGB").save(jbuf, "JPEG", quality=82, optimize=True)
            jpg = jbuf.getvalue()
            if len(jpg) < len(png):
                return _b64.b64encode(jpg).decode(), note + f" jpeg {len(jpg)//1024}КБ"
        return _b64.b64encode(png).decode(), note
    except Exception as exc:  # noqa: BLE001 — cosmetic, never fatal
        logger.debug("trimming the shot failed (non-fatal): %s", exc)
        return image_b64, "без обрезки"


async def _shot_via_exec(bridge_callback) -> Optional[dict[str, Any]]:
    """Take the screenshot through `execute`. None ⇒ caller uses the old path."""
    if os.getenv(_SHOT_FLAG, "exec").strip().lower() != "exec":
        return None
    try:
        px = int(os.getenv(_SHOT_PIXELS, "2200"))
    except Exception:  # noqa: BLE001
        px = 2200
    try:
        res = await bridge_callback(
            "execute", {"code": _SHOT_CS.replace("__PIXELS__", str(px)), "timeout_ms": 180000})
    except Exception as exc:  # noqa: BLE001
        logger.info("shot via execute failed (%s) — falling back to export_view", str(exc)[:120])
        return None
    if not isinstance(res, dict) or res.get("error") or not res.get("image_base64"):
        logger.info("shot via execute produced nothing (%s) — falling back to export_view",
                    str((res or {}).get("message") or (res or {}).get("export_error"))[:140])
        return None
    trimmed, note = _trim_margins(str(res["image_base64"]))
    logger.info("shot: view=%s shaded=%s %s (%d КБ)",
                res.get("view"), res.get("shaded"), note, len(trimmed) * 3 // 4 // 1024)
    if note == "пусто":
        # Handing over a blank frame is worse than admitting it: the model reads
        # emptiness as fact, or shoots again and again (measured: 7 exports in
        # one turn). Say what happened and what would fix it.
        return {
            "error": True,
            "view": res.get("view"),
            "message": (
                f"Вид «{res.get('view')}» отрисовался пустым — на снимке ничего нет. "
                "Скорее всего скрыты категории, включена изоляция или подрезка. "
                "Проверь видимость в этом виде или переключись на другой 3D-вид; "
                "НЕ описывай геометрию по пустому снимку."
            ),
        }
    res["image_base64"] = trimmed
    return res



_GO_AHEAD_REPLIES = frozenset({
    "да", "ага", "угу", "ну", "ок", "окей", "окей!", "хорошо", "давай", "давай!",
    "делай", "сделай", "начинай", "поехали", "продолжай", "продолжи", "дальше",
    "вперёд", "вперед", "го", "жми", "а щас", "щас", "сейчас", "валяй", "действуй",
    "yes", "ok", "okay", "go", "do it", "continue", "proceed", "sure",
})


_KEEP_GOING_MARKERS = (
    "не останавливай", "не останавливайся", "продолжай", "продолжи", "доведи",
    "до конца", "доделай", "закончи", "заверши", "не сдавайся", "дальше делай",
    "работай дальше", "keep going", "continue until", "don\'t stop", "finish it",
)


_PLAN_MARKERS = (
    "сделаю в", "сделаю за", "сейчас сделаю", "выполню", "проверю", "начну с",
    "шаг 1", "шаг 1:", "1)", "план:", "предлагаю", "буду делать", "давай сделаю",
    "i will", "let me", "here is the plan", "plan:",
)


def _looks_like_plan(text: str) -> bool:
    """Did the model ANNOUNCE work instead of doing it?

    Codex-family models end a turn with "Сделаю в 2 шага: 1) … 2) …" and zero tool
    calls — the user sees an intention and nothing happens (live 2026-07-27: it
    looked at the render, correctly diagnosed that stray elements stretch the 3D
    view, described the two-step fix, and stopped). Prompt wording alone does not
    hold it, so the harness re-asks. Only short, plan-shaped answers qualify: a
    real report of finished work is longer and past-tense."""
    if not text:
        return False
    low = text.strip().lower()
    if len(low) > 600:
        return False
    return any(m in low for m in _PLAN_MARKERS)


def _asks_to_look(messages: list[dict[str, Any]]) -> bool:
    """Did the user ask the assistant to LOOK at something?

    Measured 2026-07-27 (two identical bench runs, "посмотри на здание и коротко
    опиши его форму"): zero screenshots both times, and both answers still
    asserted visual traits — "ступенчатая композиция", "ломаный контур",
    "силуэт асимметричный" — one of them on top of a query that had returned
    count=0. A bounding box cannot yield a silhouette; the description came from
    priors. The user's own words for this: "посмотрел он в итоге или нет".
    """
    try:
        for m in reversed(messages):
            if m.get("role") != "user":
                continue
            text = m.get("content")
            if not isinstance(text, str):
                return False
            from kukai.llm.prompts import is_look_request

            return is_look_request(text)
        return False
    except Exception:  # noqa: BLE001
        return False


def _is_keep_going(messages: list[dict[str, Any]]) -> bool:
    """Is the last user message an INSTRUCTION to carry on working?

    The router scores such a message as chit-chat ("не останавливайся пока не
    получишь идеальный результат" → intent=converse) and hands the turn its
    smallest budget: one round and NO tools. The turn then cannot act at all and
    dies with an empty answer — the exact opposite of what was asked. Detect the
    intent explicitly and let the caller restore a working budget."""
    try:
        for m in reversed(messages):
            if m.get("role") != "user":
                continue
            text = m.get("content")
            if not isinstance(text, str):
                return False
            low = text.strip().lower()
            return any(mark in low for mark in _KEEP_GOING_MARKERS)
        return False
    except Exception:  # noqa: BLE001
        return False


def _is_go_ahead(messages: list[dict[str, Any]]) -> bool:
    """Is this turn a bare go-ahead for something the assistant just proposed?

    True only when the LAST user message is a short affirmative AND the assistant
    has spoken before it (i.e. there IS a proposal to green-light). Punctuation and
    case are ignored. Never raises — a misread here must not change tool policy."""
    try:
        last_user = None
        assistant_spoke = False
        for m in messages:
            role = m.get("role")
            if role == "user":
                last_user = m
            elif role == "assistant":
                assistant_spoke = True
        if last_user is None or not assistant_spoke:
            return False
        text = last_user.get("content")
        if not isinstance(text, str):
            return False
        norm = text.strip().strip(".!?,;: ").lower()
        return bool(norm) and len(norm) <= 24 and norm in _GO_AHEAD_REPLIES
    except Exception:  # noqa: BLE001
        return False


def _accumulate_tool_call_delta(
    tool_calls_accumulator: dict[int, dict[str, Any]],
    delta_tool_calls: Any,
) -> None:
    """Tool calls (accumulated from chunks) — C1: the round loop's stream-delta
    fold, verbatim; mutates the accumulator in place."""
    for tc in delta_tool_calls:
        idx = tc.index
        if idx not in tool_calls_accumulator:
            tool_calls_accumulator[idx] = {
                "id": tc.id or "",
                "function": {"name": "", "arguments": ""},
            }
        if tc.id:
            tool_calls_accumulator[idx]["id"] = tc.id
        if tc.function:
            if tc.function.name:
                tool_calls_accumulator[idx]["function"]["name"] = tc.function.name
            if tc.function.arguments:
                tool_calls_accumulator[idx]["function"]["arguments"] += tc.function.arguments
        # Preserve thought signature for Gemini round-trip
        if hasattr(tc, '_thought_signature') and tc._thought_signature:
            tool_calls_accumulator[idx]["_thought_signature"] = tc._thought_signature


def _build_assistant_tool_msg(
    collected_text: str,
    tool_calls_accumulator: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Add assistant message with tool calls to history (C1: the round loop's
    dict literal, verbatim; the caller appends it to state.full_messages)."""
    return {
        "role": "assistant",
        "content": collected_text or None,
        "tool_calls": [
            {
                "id": tc_data["id"],
                "type": "function",
                "function": tc_data["function"],
                # Preserve thought signature for Gemini round-trip
                **({
                    "_thought_signature": tc_data["_thought_signature"]
                } if "_thought_signature" in tc_data else {}),
            }
            for tc_data in tool_calls_accumulator.values()
        ],
    }
