"""Application configuration — all settings from environment variables."""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All configuration is loaded from env vars or .env file.
    No hardcoded secrets anywhere."""

    # --- Server ---
    host: str = "127.0.0.1"
    port: int = 52411
    debug: bool = False
    remote_mode: bool = False
    cors_origins: str = "http://127.0.0.1:52411"  # Restrict by default; set "*" in .env for dev
    public_url: str = "https://revit-kukai.org"

    # --- Bridge ---
    bridge_host: str = "127.0.0.1"
    bridge_port: int = 52410
    bridge_timeout: float = 900.0
    bridge_execute_timeout: float = 9000.0

    # --- LLM ---
    llm_model: str = "gemini/gemini-3-flash-preview"
    # Thinking-mode model (UI "думающий" toggle). Fast=DeepSeek V4 Flash (llm_model).
    # TEMPORARY: operator is personally trialling Nemotron-3-Ultra here; to roll back,
    # set this to "openrouter/deepseek/deepseek-v4-pro" (or override via prod .env
    # KUKAI_LLM_THINKING_MODEL).
    llm_thinking_model: str = "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"
    llm_api_key: str = ""
    llm_api_base: Optional[str] = None
    llm_max_tokens: int = 16384
    llm_temperature: float = 0.3
    llm_max_tool_rounds: int = 50  # ceiling raised from 12 (operator, осознанно): hard tasks may grind toward this; bounded by the whole-turn wall-clock budget (KUKAI_TURN_BUDGET_S)
    llm_timeout: float = 1800.0  # Быстрый режим (30 мин)
    llm_thinking_timeout: float = 9000.0  # Думающий режим (2.5 часа)
    # --- Free Google AI Studio fallback pool (2 independent AIza keys) ---
    # Each is a separate Google AI Studio account, gives ~15 RPM independent
    # quota. Layer 2 = backup, Layer 3 = fallback. Both used with model prefix
    # ``gemini/...`` (NOT ``vertex_ai/...``) so AIza key is actually used by
    # litellm — see _do_fallback_call. Both routed through WARP proxy because
    # generativelanguage.googleapis.com is geo-blocked for KZ/RU IPs.
    # --- Antigravity Pro proxy (paid subscription via OAuth, OpenAI-compat endpoint) ---
    # Hosted on user's CH machine, exposed via Cloudflare named tunnel.
    # Uses Google AI Pro subscription quota (paid $20/mo). Should be highest-priority
    # layer (cheapest per-call, largest quota) before Vertex.
    llm_antigravity_url: str = ""        # e.g. https://antigravity.revit-kukai.org
    llm_antigravity_api_key: str = ""    # local proxy auth key (sk-...)
    llm_antigravity_model: str = "gemini-3-flash-preview"  # model name used by Antigravity proxy
    llm_antigravity_timeout: float = 90.0
    # --- agy CLI proxy (THINKING-mode primary) ---
    # OpenAI-compat HTTP wrapper around Antigravity CLI 2.0 (agy).
    # Provides access to gemini-3.5-flash via user's Pro subscription.
    # Higher latency (~7-8s due to agy startup) but much larger quota.
    # Used as PRIMARY for thinking_mode requests when configured.
    llm_agy_url: str = ""               # e.g. https://agy.revit-kukai.org
    llm_agy_api_key: str = ""           # agy_proxy auth key (sk-...)
    llm_agy_model: str = "gemini-3.5-flash"
    llm_agy_timeout: float = 180.0
    llm_google_backup_api_key: str = ""   # AIza* key #1 (1st AIza fallback)
    llm_google_fallback_api_key: str = ""  # AIza* key #2 (2nd AIza fallback)
    # Extra AIza keys, comma-separated. Tried sequentially after #1, #2 fail.
    # Each adds ~15 RPM of free Google AI Studio quota from an independent
    # account. Format: "AIzaSyXXX,AIzaSyYYY,AIzaSyZZZ"
    llm_google_extra_api_keys: str = ""
    llm_fallback_model: str = "openrouter/deepseek/deepseek-v4-flash"  # Emergency only — different model, cheap
    llm_fallback_api_key: str = ""  # OpenRouter key (sk-or-v1-*)
    llm_fallback_timeout: float = 4500.0  # Fallback (75 мин)

    # NOTE: last_resort_* config fields below are retained for backward
    # compatibility with existing .env files but are NO LONGER USED by the
    # fallback chain. _do_fallback_call now has 3 levels only:
    # AIza backup → AIza fallback → OpenRouter DeepSeek emergency.
    llm_last_resort_model: str = ""  # DEPRECATED
    llm_last_resort_api_key: str = ""  # DEPRECATED
    llm_last_resort_api_base: str = ""  # DEPRECATED

    # --- Gemini OAuth (free via Pro subscription) ---
    gemini_oauth_enabled: bool = False  # DISABLED: using OpenRouter instead
    gemini_model: str = "gemini-3.1-pro-preview-customtools"  # Primary model
    gemini_thinking_model: str = "gemini-3.1-pro-preview-customtools"  # Thinking model (20-30s, deep reasoning)
    gemini_fallback_model: str = "gemini-3-flash-preview"  # Fallback when primary is rate-limited
    gemini_tokens_dir: str = "data/gemini_tokens"  # Directory with accountN.json files

    # --- RAG Embeddings ---
    openai_api_key: str = ""  # For RAG semantic search (OpenAI legacy)
    embedding_model: str = "text-embedding-3-large"
    embedding_api_base: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""  # Falls back to openai_api_key if empty
    embedding_dimensions: int = 3072
    # Cosine relevance cutoff for embedding RAG (API ref + norms). Was hardcoded
    # 0.25 in two places, tuned to text-embedding-3-large (nonsense ~0.18 / real
    # ~0.32). Centralized + env-tunable (KUKAI_EMBEDDING_SIM_THRESHOLD) so it
    # tracks the embedding model instead of being a duplicated magic number.
    embedding_sim_threshold: float = 0.25

    # --- Auth ---
    api_key: str = ""  # Empty = auth disabled (local mode)
    admin_token: str = ""
    auth_enabled: bool = False
    server_secret: str = ""  # For signing device tokens (auto-generated if empty)

    # --- Storage ---
    # Legacy SQLite path — kept for migration tooling; not used at runtime.
    db_path: str = "data/kukai.db"
    # PostgreSQL DSN — primary runtime database. Use 127.0.0.1 by default
    # because `localhost` on Windows can prefer IPv6 and add ~40s per
    # connect() while the IPv6 attempt times out.
    database_url: str = "postgresql://kukai:kukai@127.0.0.1:5432/kukai"
    db_pool_min: int = 2
    db_pool_max: int = 20
    session_ttl_days: int = 30
    # --- Files ---
    file_ttl_hours: int = 24  # Auto-cleanup generated files older than this

    # --- Rate limiting ---
    # 3 tiers: free=30/week, pro=100/day, ultra=300/day
    free_daily_limit: int = 30
    free_window_hours: int = 168  # 7 days
    pro_window_hours: int = 24
    pro_window_limit: int = 100
    ultra_window_limit: int = 300
    max_file_size_mb: int = 10

    # --- Model Passport ---
    detailed_context: bool = True  # KUKAI_DETAILED_CONTEXT — enable rich model passport (~20K tokens)
    # KUKAI_PASSPORT_V2 — replace the shallow always-on quick passport with the
    # lean high-signal v2 core (glossary + ALL type names + key params) for G1
    # grounding. Default OFF (prod unchanged until A/B-validated + flipped).
    passport_v2: bool = False
    # KUKAI_QUERY_MODEL — expose the declarative query_model tool (G3): reliable
    # element discovery via a version-safe backend template instead of ad-hoc C#.
    # Additive (model only uses it if it chooses). Default OFF for gated rollout.
    query_model: bool = False
    # KUKAI_PLAN_ONE_SCRIPT — G4 directive: plan in the reasoning channel, gather
    # facts up front (passport + query_model), then emit ONE script instead of N
    # inspect→act round-trips. Planning is KEPT (it helps DeepSeek), just rerouted.
    # HIGH blast radius (changes output behavior) → default OFF, A/B before flip.
    plan_one_script: bool = False
    # KUKAI_RAG_MEMBERS — G2 generation-side: inject REAL version-correct class
    # members (from the api_surface) into RAG instead of the corpus's methods[:6],
    # to PREVENT CS1061 (not just repair it). Default OFF (test/A/B before flip;
    # adds prompt size → measure, cache-reorder later neutralizes the cost).
    rag_members: bool = False
    # KUKAI_RAG_VERSION_FILTER — plan 012 (IRON 4/5): drop/strip API entries that
    # the connected Revit version does not have, using {introduced, removed_in}
    # diffed from the per-version api_surface files (data/api_versions.json).
    # Fail-open: with no version-truth artifact every check is a no-op, so OFF
    # behaves identically to the legacy `since`-only filter. Default ON — the
    # acceptance tests pin the removal facts to measured DLL ground truth.
    rag_version_filter: bool = True
    # KUKAI_PROMPT_LAYERED — plan 013 (injection spine): assemble the system prompt
    # as stable-prefix / per-turn-trailing layers so the provider prompt cache hits
    # across turns (the ~10x multi-turn input-cost win). Default OFF — the legacy
    # single-block assembly is byte-identical; flip after the live cache measurement.
    prompt_layered: bool = False
    # KUKAI_RAG_RANK_TYPE_MODE — plan 018 (IRON 4): how the post-RRF type-priority
    # prior is applied. "hard" (default) = the legacy sort where classes/recipes
    # always outrank categories/parameters (byte-identical); "tiebreak" = type only
    # breaks equal RRF scores; "weight" = type folds into the RRF score scaled by
    # rag_type_weight_other. Any non-default mode must clear the benchmark decision
    # rule before it ships; the rank-ablation measured all three as a null result.
    rag_rank_type_mode: str = "hard"
    rag_type_weight_other: float = 0.9
    # KUKAI_RAG_DEMOTE_SIGNATURES — anti-overconfidence ("memory knows its
    # edges"): after RRF/ranking, stable-partition class entries whose ONLY
    # example is a bare signature (e.g. "public void Foo(...)") BELOW substantive
    # entries (real recipe / rich example / negative-knowledge edge) for the same
    # query, so a signature can't masquerade as a verified pattern. NO-OP when no
    # signature-only entry is in the result set — and byte-identical to legacy
    # when OFF.
    # DEFAULT OFF: test_rag.py stays green with it ON, but the plan-018 parity
    # contract test_ranking_value.py::test_search_equals_retrieve_hard asserts
    # search() == the raw retrieve() pipeline; the demotion intentionally diverges
    # them. Per the spec's "otherwise default OFF and report" rule, the live path
    # stays legacy until the operator either flips this on (and adjusts that parity
    # test) or relocates the demotion into retrieval.rank_candidates (the single
    # measured ranking policy — outside this change's file scope). Set =1 to enable.
    rag_demote_signatures: bool = False

    # KUKAI_SCHEDULING_AI_INFERENCE — Scheduler v2 AI dependency-inference tier
    # (Pillar: AI-inferred sequencing). Adds LLM calls to schedule builds
    # (slower, costs tokens). The semantic ГЭСН matcher is NOT gated by this —
    # it only needs an OpenAI embeddings key.
    # DEFAULT OFF (2026-06-12): the LLM dep-inference tier is disabled by default
    # (operator decision — wiring stays, set KUKAI_SCHEDULING_AI_INFERENCE=1 to
    # re-enable).
    scheduling_ai_inference: bool = False

    # --- Context management ---
    max_context_tokens: int = 500_000  # Max tokens for conversation history
    compact_threshold: int = 400_000  # Compact when history exceeds this
    keep_recent_messages: int = 30  # Never compact the most recent N messages
    db_message_limit: int = 500  # Max messages to load from DB
    # KUKAI_COMPACT_CACHE — persist the rolling compaction summary per session
    # (summary + watermark in the compact_cache table) so long chats REUSE the
    # stored summary and only fold in messages that appeared AFTER the
    # watermark, instead of re-summarizing the whole prefix with an LLM call
    # on EVERY turn (IQ-moments #1: hidden per-turn latency+cost tax).
    # DEFAULT OFF: the legacy per-turn full summarization path is taken
    # unchanged (byte-identical context, zero new DB calls). Operator flips
    # to 1 after review.
    compact_cache: bool = False

    # --- Execution ---
    max_execute_timeout: int = 9000  # Absolute max timeout in seconds for code execution (2.5 hours)

    # --- Modules ---
    modules: str = "audit,commands"  # Comma-separated list of modules to load (KUKAI_MODULES). vor+rascenka archived 2026-06-10.

    # --- Paths ---
    static_dir: str = ""  # Auto-detected if empty
    prompts_dir: str = ""  # Auto-detected if empty
    files_dir: str = "data/files"

    def get_effective_host(self) -> str:
        """Return effective host — 0.0.0.0 for remote mode, configured value otherwise."""
        if self.remote_mode:
            return "0.0.0.0"
        return self.host

    _cached_secret: str = ""

    def get_server_secret(self) -> str:
        """Return server secret, generating one if not configured.

        In production (remote_mode=True), this MUST be set via env var.
        In local mode, a random secret is generated once and persisted to
        data/.server_secret so that device tokens survive server restarts.
        """
        if self.server_secret:
            return self.server_secret
        if self.remote_mode:
            raise ValueError(
                "KUKAI_SERVER_SECRET must be set when remote_mode is enabled. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        # Local mode: generate once and cache + persist to file
        if self._cached_secret:
            return self._cached_secret

        secret_file = self._get_data_base() / "data" / ".server_secret"
        try:
            if secret_file.exists():
                stored = secret_file.read_text(encoding="utf-8").strip()
                if stored:
                    self._cached_secret = stored
                    return self._cached_secret
        except OSError:
            pass

        # Generate new secret and persist
        self._cached_secret = secrets.token_hex(32)
        try:
            secret_file.parent.mkdir(parents=True, exist_ok=True)
            secret_file.write_text(self._cached_secret, encoding="utf-8")
        except OSError:
            pass  # If we can't persist, at least we cached in-memory

        return self._cached_secret

    def get_modules_list(self) -> list[str]:
        """Parse comma-separated module names into a list."""
        return [m.strip() for m in self.modules.split(",") if m.strip()]

    def get_cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        if self.cors_origins == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = {
        "env_prefix": "KUKAI_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    def get_static_dir(self) -> Path:
        """Resolve static files directory."""
        if self.static_dir:
            return Path(self.static_dir)
        # Default: project root (where kukai_chat_v5.html lives)
        return Path(__file__).parent.parent.parent

    def get_prompts_dir(self) -> Path:
        """Resolve prompts directory."""
        if self.prompts_dir:
            return Path(self.prompts_dir)
        return Path(__file__).parent.parent / "prompts"

    def _get_data_base(self) -> Path:
        """Return the base directory for writable data files.

        When running from Program Files (installed mode), use
        %LOCALAPPDATA%/KUKI so we don't hit permission errors.
        In dev mode (not in Program Files), use backend/ as before.
        """
        backend_dir = Path(__file__).parent.parent
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        if str(backend_dir).startswith(prog_files):
            local_app_data = os.environ.get(
                "LOCALAPPDATA",
                Path.home() / "AppData" / "Local",
            )
            return Path(str(local_app_data)) / "KUKI"
        return backend_dir

    def get_db_path(self) -> Path:
        """Resolve database path."""
        p = Path(self.db_path)
        if not p.is_absolute():
            p = self._get_data_base() / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def get_files_dir(self) -> Path:
        """Resolve generated files directory."""
        p = Path(self.files_dir)
        if not p.is_absolute():
            p = self._get_data_base() / p
        p.mkdir(parents=True, exist_ok=True)
        return p

    def get_gemini_tokens_dir(self) -> Path:
        """Resolve Gemini OAuth tokens directory."""
        p = Path(self.gemini_tokens_dir)
        if not p.is_absolute():
            p = self._get_data_base() / p
        return p

    @property
    def bridge_url(self) -> str:
        return f"http://{self.bridge_host}:{self.bridge_port}"


def _resolve_env_files() -> tuple[str, ...]:
    """Build the list of .env files to load, in priority order.

    Checks:
    1. .env in the current working directory (dev mode)
    2. .env next to the backend code (installed mode, if writable)
    3. %LOCALAPPDATA%/KUKI/.env (installed mode, user-writable location)
    """
    candidates: list[str] = [".env"]
    backend_dir = Path(__file__).parent.parent
    backend_env = backend_dir / ".env"
    if backend_env.exists():
        candidates.append(str(backend_env))

    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        user_env = Path(local_app_data) / "KUKI" / ".env"
        if user_env.exists():
            candidates.append(str(user_env))

    return tuple(candidates)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton settings instance."""
    env_files = _resolve_env_files()
    return Settings(_env_file=env_files)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 1 (revit-coder pilot) — module-level config
#
# Activated via KUKAI_USE_REVIT_CODER=1. When inactive (default),
# KUKI behaves exactly as before — these constants add optional capability.
#
# Kept as module-level constants (not Settings fields) for two reasons:
#   1. Easier to override in tests via importlib.reload + patched env.
#   2. Phase 2.5 cleanup will remove these wholesale; isolating them here
#      makes that removal a single delete-block operation.
#
# See: docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md
# ═══════════════════════════════════════════════════════════════════════════

# ─── Master switch ────────────────────────────────────────────────────────
USE_REVIT_CODER: bool = os.getenv("KUKAI_USE_REVIT_CODER", "0") == "1"

# ─── Router connection (VPS Cloudflare-tunneled router on coder subdomain) ──
REVIT_CODER_URL: str = os.getenv(
    "KUKAI_REVIT_CODER_URL",
    "https://coder.revit-kukai.org/v1",
)
REVIT_CODER_API_KEY: str = os.getenv("KUKAI_REVIT_CODER_API_KEY", "")
REVIT_CODER_MODEL: str = os.getenv(
    "KUKAI_REVIT_CODER_MODEL",
    "hf.co/schauh11/revit-coder-14b",
)
REVIT_CODER_TIMEOUT_SEC: float = float(os.getenv("KUKAI_REVIT_CODER_TIMEOUT_SEC", "120"))

# ─── Temporarily FROZEN tools — excluded from the tool list in ALL modes ─────
# Reversible via env (KUKAI_FROZEN_TOOLS="" to unfreeze). audit_model is frozen
# (2026-06-07): pathologically slow (~496s) — the harness caps it, but the model
# still wastes a long round choosing it. Unfreeze once the tool itself is fixed.
FROZEN_TOOLS: set[str] = {
    t.strip() for t in os.getenv("KUKAI_FROZEN_TOOLS", "audit_model").split(",") if t.strip()
}

# ─── Semantic category fallback (IQ-fix P1) ──────────────────────────────────
# On a category DICTIONARY miss, resolve by embedding similarity (meaning) so
# synonyms/typos/unlisted phrasings don't hard-fail query_model. Default OFF
# (reversible); embeddings are a separate budget from DeepSeek. Conservative
# threshold → low-confidence falls through to None (today's behavior).
CATEGORY_SEMANTIC: bool = os.getenv("KUKAI_CATEGORY_SEMANTIC", "0") == "1"
CATEGORY_SEMANTIC_THRESHOLD: float = float(os.getenv("KUKAI_CATEGORY_SEMANTIC_THRESHOLD", "0.50"))

# ─── A2: model-derived passport glossary ─────────────────────────────────────
# Enrich the passport glossary with each wall type's REAL structural material +
# WallType.Function via a one-time live query (cached per document) — instead of
# the name-substring heuristic. Default OFF (reversible). Backend-only (no plugin).
PASSPORT_MATERIAL: bool = os.getenv("KUKAI_PASSPORT_MATERIAL", "0") == "1"

# ─── Tier-0: model-health "vitals" in the passport ───────────────────────────
# A one-time live query (cached per document) for the cheap, high-signal health
# scalars — warnings, CAD imports, pinned grids/levels, rooms (unnamed/unplaced),
# design options, worksharing, MEP presence, mandatory-param coverage — rendered
# as a health header. The anti-fabrication anchor (s30/s19/s28). Default OFF.
PASSPORT_VITALS: bool = os.getenv("KUKAI_PASSPORT_VITALS", "0") == "1"

# ─── Wave 1: perception "suit" — graph LOD-0 gestalt + inspect verb ───────────
# The semantic spine (Building→Levels→Zones→Systems from REAL relationships) in the
# always-on passport + the `inspect(element_id)` drill verb. One live graph query,
# cached per content-fingerprint (model_cache). Default OFF (zero prod impact).
PERCEPTION: bool = os.getenv("KUKAI_PERCEPTION", "0") == "1"

# ─── Tools disabled in revit-coder mode (heavy pipelines + duplicates) ──────
DISABLED_TOOLS_REVIT_CODER_MODE: set[str] = {
    "apply_revit_write",        # duplicates execute_revit_code
    "audit_model",              # heavy multi-agent pipeline
    "price_vor",                # heavy VOR pricing pipeline
    "lookup_norm",              # not needed for code-gen testing
}


# ═══════════════════════════════════════════════════════════════════════════
#  GEMINI CONTEXT CACHING (V3.2) — flags moved to env-var reads
# ═══════════════════════════════════════════════════════════════════════════
#
# V3.2 cache flags are intentionally NOT pydantic Settings fields — they live
# as module-level env reads inside `kukai.llm.gemini_context_cache` and its
# users. This keeps config.py footprint small and lets us ship V3 without
# disturbing prod's existing Settings schema (which has diverged from local
# in other unrelated areas).
#
# Flags:
#   KUKAI_GEMINI_CONTEXT_CACHE_ENABLED  (default 0)  — master switch
#   KUKAI_GEMINI_CACHE_TTL_MINUTES      (default 60) — cache lifetime
#   KUKAI_FAMILY_MODE_RAG_ENABLED       (default 0)  — restore old RAG behaviour

# ─── Uptime monitor ──────────────────────────────────────────────────────
UPTIME_POLL_INTERVAL_SEC: float = float(os.getenv("KUKAI_UPTIME_POLL_SEC", "30"))
UPTIME_LOG_PATH: str = os.getenv(
    "KUKAI_UPTIME_LOG_PATH",
    "backend/data/kaggle_uptime.jsonl",
)

# ─── Metrics ────────────────────────────────────────────────────────────
METRICS_LOG_PATH: str = os.getenv(
    "KUKAI_CODER_METRICS_LOG_PATH",
    "backend/data/coder_metrics.jsonl",
)
FAILURES_LOG_PATH: str = os.getenv(
    "KUKAI_CODER_FAILURES_LOG_PATH",
    "backend/data/coder_failures.jsonl",
)

# ─── Multi-Agent Layer (Phase 7 — 2026-05-11) ───────────────────────────
# All flags default OFF for safe rollback. Enable individually via env vars.
# Pre-validated lift on control_audit50 with full stack + REPAIR=2:
#   baseline 0.5600 -> full stack 0.8800 (+32pp aggregate)
# See docs/superpowers/plans/2026-05-11-multi-agent-rag.md for details.
AGENT_USE_INTENT_CLASSIFIER: bool = (
    os.getenv("KUKAI_AGENT_INTENT", "0") == "1"
)
AGENT_USE_QUERY_REFORMULATOR: bool = (
    os.getenv("KUKAI_AGENT_REFORM", "0") == "1"
)
AGENT_USE_RERANKER: bool = (
    os.getenv("KUKAI_AGENT_RERANK", "0") == "1"
)
AGENT_USE_CRITIC: bool = (
    os.getenv("KUKAI_AGENT_CRITIC", "0") == "1"
)
AGENT_USE_VERSION_CHECKER: bool = (
    os.getenv("KUKAI_AGENT_VERSION", "0") == "1"
)
AGENT_USE_ERROR_INTERPRETER: bool = (
    os.getenv("KUKAI_AGENT_ERR_INTERP", "0") == "1"
)
# Reranker transport backend (only consulted when AGENT_USE_RERANKER=1):
#   "cohere" — cohere/rerank-4-fast via OpenRouter /rerank (~0.4-0.5s, reliable;
#              the current state while the gemini agent stack is DOWN — see memory
#              kukai-gemini-down-deepseek-only). Semantic reranker → caller adds
#              an essentials-floor (FilteredElementCollector/Transaction).
#   "llm"    — the gemini LLM RagReranker (task-aware, ~700ms) — only viable once
#              the gemini path is restored; on DeepSeek it is 1-68s (unusable).
AGENT_RERANK_BACKEND: str = os.getenv("KUKAI_AGENT_RERANK_BACKEND", "llm").strip().lower()
# OpenRouter rerank model (consulted for the "cohere"/"nemotron"/"openrouter"
# backends). cohere/rerank-* and nvidia nemotron-rerank share one /rerank shape,
# so the backend path is model-agnostic and the model is chosen here.
AGENT_RERANK_MODEL: str = os.getenv(
    "KUKAI_AGENT_RERANK_MODEL", "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
).strip()
# A/B routing — hash session_id, percent < KUKAI_AGENT_TEST_PCT -> treatment.
# 0 disables A/B entirely (all baseline). 100 = all treatment.
# DEFAULT 100 (2026-06-12): the convergence/router discipline (W1, +32pp on
# control_audit50) is now the standard code path for ALL users, not a dark A/B
# arm. Set KUKAI_AGENT_TEST_PCT=0 to return everyone to the control/baseline
# path, or a value 1..99 to re-enable bucketed A/B.
AGENT_TEST_PERCENT: int = int(os.getenv("KUKAI_AGENT_TEST_PCT", "100"))

# --- Agent-architecture upgrade flags (2026-06-07, study-driven). Default OFF,
#     each gated by AGENT_TEST_PERCENT for safe A/B. Helpers in agents/rollout.py.
#     Plan: /root/.claude/plans/recursive-inventing-lecun.md. Evidence:
#     data/study_2026-06-07.md (Claude 22/22 vs DeepSeek 10/6/6).
# Pillar C — grounding/anti-fabrication gate (require a tool call before an
#   analysis answer; no norm clause unless from lookup_norm).
AGENT_USE_GROUNDING_GATE: bool = (
    os.getenv("KUKAI_AGENT_GATE", "0") == "1"
)
# Intent router — consume the (DeepSeek-homed) classifier to set per-request
#   max_tool_rounds / reasoning effort / tool gating.
# DEFAULT ON (2026-06-12, W1): standard code path. Roll back with
# KUKAI_AGENT_ROUTER=0 (any non-"0" value keeps it enabled).
AGENT_USE_ROUTER: bool = (
    os.getenv("KUKAI_AGENT_ROUTER", "1") != "0"
)
# Convergence controller — duplicate-tool-call dedup, forced synthesis on
#   round-cap (instead of the canned "Достигнут лимит" string), stall break.
# DEFAULT ON (2026-06-12, W1): the validated anti-looping machinery is now the
# default for all users (+32pp on control_audit50). Roll back with
# KUKAI_AGENT_CONVERGE=0 (any non-"0" value keeps it enabled). Relies on the
# dedup-vs-write fix in client.py so verify-after-write is not punished.
AGENT_USE_CONVERGENCE: bool = (
    os.getenv("KUKAI_AGENT_CONVERGE", "1") != "0"
)
# Code-salvage keystone (convergence-gated): when the model writes C# code as
# chat TEXT instead of calling execute_revit_code (so nothing runs in Revit and
# the user gets "ничего не сделано"), force ONE corrective round that actually
# executes it. Roll back with KUKAI_AGENT_CODE_SALVAGE=0. Default on.
AGENT_CODE_SALVAGE: bool = (
    os.getenv("KUKAI_AGENT_CODE_SALVAGE", "1") != "0"
)
# Pillar A — semantic query_model predicates (function/width/layer_material)
#   + NL concept map, instead of brittle type-name substring matching.
AGENT_USE_QUERY_SEMANTIC: bool = (
    os.getenv("KUKAI_AGENT_QUERY_SEMANTIC", "0") == "1"
)
# plan-020 — the Evaluator (IRON 3) in SHADOW mode: deterministic verdict per
# write, recorded to eval_verdicts.jsonl; NEVER gates, model never sees it.
#   0 = off (default) · 1 = Tier-A structural checks only (zero bridge cost)
#   2 = Tier A + read-only probes (≤2/write, ≤4/turn, 8s cap each)
EVALUATOR_SHADOW: int = int(os.getenv("KUKAI_EVALUATOR_SHADOW", "0"))

# Per-agent telemetry log path
AGENT_TELEMETRY_LOG_PATH: str = os.getenv(
    "KUKAI_AGENT_TELEMETRY_PATH",
    "backend/data/agent_telemetry.jsonl",
)
