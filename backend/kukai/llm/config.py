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
    # Fast mode (default, cheap): Gemini 3 Flash Preview, no thinking surcharge.
    llm_model: str = "vertex_ai/gemini-3-flash-preview"
    # Thinking mode: Gemini 3.5 Flash with reasoning_effort=high — engaged when
    # the WS chat payload sends `thinking_mode: true` or `mode: "thinking"`.
    llm_thinking_model: str = "vertex_ai/gemini-3.5-flash"
    llm_api_key: str = ""
    llm_api_base: Optional[str] = None
    llm_max_tokens: int = 16384
    llm_temperature: float = 0.3
    llm_max_tool_rounds: int = 12
    llm_timeout: float = 1800.0  # Быстрый режим (30 мин)
    llm_thinking_timeout: float = 9000.0  # Думающий режим (2.5 часа)
    llm_google_fallback_api_key: str = ""  # Second Google AI Studio key (tried before OpenRouter)
    llm_fallback_model: str = "openrouter/deepseek/deepseek-v4-flash"
    llm_fallback_api_key: str = ""  # Uses same api_key if empty
    llm_fallback_timeout: float = 4500.0  # Fallback (75 мин)
    # Reasoning effort APPLIED ONLY TO THE THINKING MODEL (Gemini 3.5 Flash).
    # The fast model (3 Flash Preview) is called without reasoning_effort to
    # stay cheap. Override via KUKAI_LLM_REASONING_EFFORT.
    # Values: "low" | "medium" | "high".
    llm_reasoning_effort: str = "high"

    # --- Gemini OAuth (free via Pro subscription) ---
    gemini_oauth_enabled: bool = False  # DISABLED: using OpenRouter instead
    gemini_model: str = "gemini-3.1-pro-preview-customtools"  # Primary model
    gemini_thinking_model: str = "gemini-3.1-pro-preview-customtools"  # Thinking model (20-30s, deep reasoning)
    gemini_fallback_model: str = "gemini-3.5-flash"  # Fallback when primary is rate-limited
    gemini_tokens_dir: str = "data/gemini_tokens"  # Directory with accountN.json files

    # --- RAG Embeddings ---
    openai_api_key: str = ""  # For RAG semantic search (OpenAI legacy)
    embedding_model: str = "text-embedding-3-large"
    embedding_api_base: str = "https://api.openai.com/v1"
    embedding_api_key: str = ""  # Falls back to openai_api_key if empty
    embedding_dimensions: int = 3072
    # Augment deterministic _RAG_QUERY_EXPANSION keyword expansion with
    # semantic similarity (text-embedding-3-large + cosine sim) so queries
    # that miss the keyword map still get correct API class boosts.
    # Disable to fall back to keyword-only expansion (legacy behavior).
    rag_semantic_expansion_enabled: bool = True
    rag_semantic_expansion_top_k: int = 3  # Number of class names to add
    rag_semantic_expansion_min_sim: float = 0.30  # Cosine sim threshold (OpenAI 3-large)

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

    # --- W4: Prompt caching via stable-prefix restructure ---
    # When True, the system message contains only the byte-identical stable
    # prefix (system_base.md + code_generation.md + revit_api_reference.md),
    # and ALL per-request blocks (Revit version, session state, notes,
    # qa_instructions, model_passport, RAG context, …) are emitted as separate
    # user-role messages right after it. This restructure lets Gemini's
    # implicit caching engage on the stable prefix (≥~1024 tokens → 10× cheaper
    # cached_read pricing). Set False to fall back to the legacy monolithic
    # `build_system_prompt` path. Override via KUKAI_PROMPT_CACHE_ENABLED.
    prompt_cache_enabled: bool = Field(
        default=True,
        description=(
            "Restructure prompts for implicit caching (W4). Set False to fall "
            "back to old monolithic prompt."
        ),
    )

    # --- Context management ---
    max_context_tokens: int = 500_000  # Max tokens for conversation history
    compact_threshold: int = 400_000  # Compact when history exceeds this
    keep_recent_messages: int = 30  # Never compact the most recent N messages
    db_message_limit: int = 500  # Max messages to load from DB

    # --- Execution ---
    max_execute_timeout: int = 9000  # Absolute max timeout in seconds for code execution (2.5 hours)

    # --- Modules ---
    modules: str = "vor,audit,commands,rascenka"  # Comma-separated list of modules to load (KUKAI_MODULES)

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

# ─── Tools disabled in revit-coder mode (heavy pipelines + duplicates) ──────
DISABLED_TOOLS_REVIT_CODER_MODE: set[str] = {
    "apply_revit_write",        # duplicates execute_revit_code
    "audit_model",              # heavy multi-agent pipeline
    "price_vor",                # heavy VOR pricing pipeline
    "lookup_gesn",              # supports VOR
    "lookup_norm",              # not needed for code-gen testing
    "build_schedule",           # heavy CPM pipeline
    "update_schedule_progress",
    "update_activity_override",
    "list_schedule_versions",
    "render_portfolio",
    "generate_schedule_legacy",
}

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
# A/B routing — hash session_id, percent < KUKAI_AGENT_TEST_PCT -> treatment.
# 0 disables A/B entirely (all baseline). 100 = all treatment.
AGENT_TEST_PERCENT: int = int(os.getenv("KUKAI_AGENT_TEST_PCT", "0"))

# Per-agent telemetry log path
AGENT_TELEMETRY_LOG_PATH: str = os.getenv(
    "KUKAI_AGENT_TELEMETRY_PATH",
    "backend/data/agent_telemetry.jsonl",
)
