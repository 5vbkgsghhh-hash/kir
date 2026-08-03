"""AgentBase — shared infrastructure for all multi-agent layer agents.

Includes optional JSONL telemetry logging (env-gated via
``KUKAI_AGENT_TELEMETRY_PATH``). Each run() appends a single line capturing
agent name, model, thinking level, latency, token counts, provider and
fallback_used.

Routing for ``gemini-3.1-flash-lite`` (validated 2026-05-11 on 200-query
diagnostic with hybrid Vertex+Studio failover, 200/200 success):

  PRIMARY:  Vertex AI Express Mode ($300 paid credit, ``KUKAI_VERTEX_AI_API_KEY``)
            -> ``https://aiplatform.googleapis.com/v1/publishers/google/models/...``
            -> auth header ``x-goog-api-key``
  FALLBACK: Google AI Studio free quota (``KUKAI_LLM_API_KEY``)
            -> ``https://generativelanguage.googleapis.com/v1beta/models/...?key=...``

Each endpoint gets 3 attempts with 0.5/1.0/1.5s backoff on 429, exponential
backoff on 5xx. The provider that answered is returned in usage telemetry
(``provider: vertex|studio``).

Token policy: ``max_tokens=64000`` default (effective no cap). At
``thinkingLevel=medium`` the reranker consumes ~200-400 thinking tokens before
emitting output; truncating mid-reasoning loses everything. Cost remains low
because actual usage is bounded by the task.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Endpoints & keys
# ---------------------------------------------------------------------------

# Module-level URLs and headers are derived lazily (env vars may be loaded after
# import in some entry points). Use _resolve_endpoints() to get current state.

_VERTEX_URL_TMPL = (
    "https://aiplatform.googleapis.com/v1/publishers/google/models/"
    "{model}:generateContent"
)
_STUDIO_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)


def _resolve_endpoints(model: str) -> list[tuple[str, str, dict[str, str]]]:
    """Returns ordered list of (provider_name, url, headers) to try.

    Ordering policy is controlled by ``KUKAI_AGENT_ENDPOINT_ORDER``:
      - ``"openrouter_first"`` (default when AIza free tier is exhausted —
        current prod state 2026-05-25): OpenRouter DeepSeek tried first
        because Studio is geo-blocked + free tier 20/day is burnt by 12:00 KZT.
        Each Studio retry burns 3s of the 6s agent timeout budget; putting
        OpenRouter first cuts pre-flight latency from ~14s to ~2s.
      - ``"studio_first"`` (legacy — restore when Google Cloud billing is
        enabled): Vertex → Studio → OpenRouter. Use this once paid quota
        lifts the 429 wall.
    """
    eps: list[tuple[str, str, dict[str, str]]] = []
    openrouter_key = os.environ.get("KUKAI_LLM_FALLBACK_API_KEY")
    openrouter_ep = None
    if openrouter_key:
        openrouter_ep = (
            "openrouter",
            "https://openrouter.ai/api/v1/chat/completions",
            {
                "Authorization": f"Bearer {openrouter_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://revit-kukai.org",
                "X-Title": "KUKI",
            },
        )

    order = os.environ.get("KUKAI_AGENT_ENDPOINT_ORDER", "openrouter_first").lower()
    if order == "openrouter_first" and openrouter_ep is not None:
        eps.append(openrouter_ep)

    vertex_key = os.environ.get("KUKAI_VERTEX_AI_API_KEY")
    if vertex_key:
        eps.append((
            "vertex",
            _VERTEX_URL_TMPL.format(model=model),
            {"x-goog-api-key": vertex_key, "Content-Type": "application/json"},
        ))
    # Prefer the dedicated Google AI Studio backup key. The historical
    # ``KUKAI_LLM_API_KEY`` slot is the placeholder ``unused-vertex-uses-sa-json``
    # in Vertex+SA setups — passing it to the AI Studio endpoint just yields
    # ``API key not valid`` and silently disables every agent.
    studio_key = (
        os.environ.get("KUKAI_LLM_GOOGLE_BACKUP_API_KEY")
        or os.environ.get("KUKAI_LLM_GOOGLE_FALLBACK_API_KEY")
        or os.environ.get("KUKAI_LLM_API_KEY")
    )
    # Filter out the well-known placeholder so it never reaches AI Studio.
    if studio_key and "unused" in studio_key.lower():
        studio_key = ""
    # Also filter out OpenRouter ``sk-or-*`` keys — they get rejected by
    # Studio with 401 and (since the agent treats 4xx-other-than-429 as
    # non-retryable) drop the endpoint, but the misleading endpoint hint
    # surfaces in telemetry. Cleaner to skip entirely.
    if studio_key and studio_key.startswith("sk-or-"):
        studio_key = ""
    if studio_key:
        eps.append((
            "studio",
            _STUDIO_URL_TMPL.format(model=model, key=studio_key),
            {"Content-Type": "application/json"},
        ))
    if order != "openrouter_first" and openrouter_ep is not None:
        eps.append(openrouter_ep)
    return eps


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AgentError(Exception):
    """Base for all agent errors."""


class AgentTimeoutError(AgentError):
    """Agent did not respond within the configured timeout."""


class AgentFailedError(AgentError):
    """Agent returned but the response could not be parsed / validated."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    """Output of an agent run with telemetry."""

    value: Any
    model: str
    latency_ms: float
    tokens_in: int = 0
    tokens_out: int = 0
    thoughts_tokens: int = 0
    thinking_level: str = "medium"
    raw_response: str = ""
    fallback_used: bool = False
    provider: str = "vertex"
    error: str | None = None


# ---------------------------------------------------------------------------
# Core Gemini Flash-Lite call (hybrid Vertex+Studio failover)
# ---------------------------------------------------------------------------


async def _gemini_lite_call(
    *,
    model: str,
    system_prompt: str,
    user_msg: str,
    thinking_level: str = "medium",
    max_tokens: int = 64000,
    timeout: float = 15.0,
) -> tuple[str, dict[str, Any]]:
    """Call a Gemini Flash-Lite-tier model with hybrid Vertex+Studio routing.

    Returns ``(text, usage_dict)`` where usage carries:
      - prompt_tokens, completion_tokens, thoughts_tokens
      - provider: "vertex" | "studio"
      - fallback_used: bool (True if vertex failed and studio succeeded)
      - attempts: int total HTTP attempts across all endpoints

    Raises ``AgentTimeoutError`` if BOTH endpoints time out, or
    ``AgentFailedError`` if BOTH return non-recoverable errors.
    """
    endpoints = _resolve_endpoints(model)
    if not endpoints:
        raise AgentFailedError(
            "no agent endpoints available — set KUKAI_VERTEX_AI_API_KEY "
            "or KUKAI_LLM_API_KEY"
        )

    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingLevel": thinking_level},
        },
    }
    # OpenRouter (DeepSeek v4 Flash) speaks OpenAI shape, not Gemini's.
    # IMPORTANT: max_tokens behavior diverges between providers. Gemini's
    # `thinkingLevel` keeps actual usage bounded even with `maxOutputTokens=64000`
    # (the cap is a safety ceiling, not a budget). DeepSeek v4 Flash has no
    # equivalent — it will happily reason for 30-60s if `max_tokens` allows.
    # Agents emit small JSON (intent <200 tokens, reranker indices <50 tokens,
    # reformulated query <300 tokens, error summary <500 tokens) — cap at 2048
    # to keep latency under the 6s pre-flight timeout. Override via
    # ``KUKAI_AGENT_OPENROUTER_MAX_TOKENS`` if a specific agent needs more.
    _or_cap = int(os.environ.get("KUKAI_AGENT_OPENROUTER_MAX_TOKENS", "2048"))
    openrouter_body = {
        "model": "deepseek/deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "max_tokens": min(max_tokens, _or_cap),
    }
    # W1-A (2026-07-10, /root/kukai-rag-audit/SPEC_W1A_single_classify.md):
    # agents emit small JSON (see the 2048-cap comment above) — the reasoning
    # phase only burned into the 6s pre-flight budget for no benefit (Opus
    # measurement 2026-07-10: reasoning-ON=6.1s vs reasoning-OFF=3-4s, JSON
    # identical at temp=0, 3/3). This is a return to the original "fast
    # pre-flight agents" design intent, not a new behavior choice, so there is
    # no default flag to gate it — but KUKAI_AGENT_OPENROUTER_REASONING=1 is a
    # no-deploy escape hatch: set it to omit the key and get today's
    # reasoning-ON body back if this ever needs a fast rollback.
    if os.environ.get("KUKAI_AGENT_OPENROUTER_REASONING", "0") != "1":
        openrouter_body["reasoning"] = {"enabled": False}

    last_err: str | None = None
    attempts_total = 0
    fallback_used = False
    # AI Studio is geo-blocked from some regions (incl. our VPS in KZ). The
    # backend itself routes Studio calls through a SOCKS proxy via litellm; the
    # agent path uses bare httpx and was previously calling Studio directly.
    # httpx ``trust_env`` does not pick up ``socks5h://`` from HTTPS_PROXY
    # without explicit ``proxy=`` (requires httpx-socks). Pass it manually.
    _proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or None
    )
    async with httpx.AsyncClient(timeout=timeout, proxy=_proxy) as cl:
        for ep_idx, (ep_name, ep_url, ep_headers) in enumerate(endpoints):
            if ep_idx > 0:
                fallback_used = True
            request_body = openrouter_body if ep_name == "openrouter" else body
            for attempt in range(3):
                attempts_total += 1
                try:
                    r = await cl.post(ep_url, json=request_body, headers=ep_headers,
                                      timeout=timeout)
                except (httpx.TimeoutException, asyncio.TimeoutError) as e:
                    last_err = f"{ep_name}_timeout: {type(e).__name__}"
                    # Try next attempt on same endpoint; if last attempt, fall
                    # through to next endpoint.
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                except Exception as e:  # noqa: BLE001
                    last_err = f"{ep_name}_exc: {type(e).__name__}: {e}"
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

                if r.status_code == 429:
                    last_err = f"{ep_name}_429"
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                if r.status_code >= 500:
                    last_err = f"{ep_name}_http_{r.status_code}"
                    await asyncio.sleep(2 ** attempt)
                    continue
                if r.status_code != 200:
                    # 4xx other than 429: not retryable on same endpoint.
                    last_err = f"{ep_name}_http_{r.status_code}: {r.text[:200]}"
                    break

                # 200 OK — parse response (shape differs by provider)
                try:
                    d = r.json()
                except Exception as e:  # noqa: BLE001
                    last_err = f"{ep_name}_json_decode: {e}"
                    break

                if ep_name == "openrouter":
                    # OpenAI-compatible shape: choices[0].message.content
                    choices = d.get("choices", [])
                    if not choices:
                        last_err = f"{ep_name}_no_choices: {str(d)[:200]}"
                        break
                    msg = choices[0].get("message", {}) or {}
                    text = (msg.get("content") or "").strip()
                    if not text:
                        finish = choices[0].get("finish_reason", "")
                        last_err = f"{ep_name}_empty_text finish={finish}"
                        break
                    u = d.get("usage", {}) or {}
                    usage = {
                        "prompt_tokens": int(u.get("prompt_tokens", 0)),
                        "completion_tokens": int(u.get("completion_tokens", 0)),
                        "thoughts_tokens": 0,
                        "provider": ep_name,
                        "fallback_used": fallback_used,
                        "attempts": attempts_total,
                    }
                    return text, usage

                # Gemini shape: candidates[0].content.parts[].text
                cands = d.get("candidates", [])
                if not cands:
                    last_err = f"{ep_name}_no_candidates: {str(d)[:200]}"
                    break
                parts = cands[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts).strip()
                if not text:
                    finish = cands[0].get("finishReason", "")
                    last_err = f"{ep_name}_empty_text finish={finish}"
                    break

                usage_meta = d.get("usageMetadata", {}) or {}
                usage = {
                    "prompt_tokens": int(usage_meta.get("promptTokenCount", 0)),
                    "completion_tokens": int(usage_meta.get("candidatesTokenCount", 0)),
                    "thoughts_tokens": int(usage_meta.get("thoughtsTokenCount", 0)),
                    "provider": ep_name,
                    "fallback_used": fallback_used,
                    "attempts": attempts_total,
                }
                return text, usage

            # Exhausted attempts on this endpoint — fall through to next.

    # Both endpoints exhausted
    if last_err and "timeout" in last_err:
        raise AgentTimeoutError(f"all endpoints timed out: {last_err}")
    raise AgentFailedError(f"all endpoints failed: {last_err}")


# ---------------------------------------------------------------------------
# JSON helper
# ---------------------------------------------------------------------------


def parse_json_block(text: str) -> dict[str, Any]:
    """Parse a Gemini response that may be wrapped in ```json ... ``` fences.

    Raises ValueError on unparseable input.
    """
    if not text or not text.strip():
        raise ValueError("empty response")
    s = text.strip()
    if s.startswith("```"):
        # Strip first line (```json or ```) and trailing ```
        lines = s.split("\n")
        if len(lines) < 2:
            raise ValueError("malformed code fence")
        # Drop opening ``` line; drop trailing ``` line if present
        if lines[-1].strip().startswith("```"):
            inner = "\n".join(lines[1:-1])
        else:
            inner = "\n".join(lines[1:])
        s = inner.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"json parse failure: {e}") from e


# ---------------------------------------------------------------------------
# AgentBase
# ---------------------------------------------------------------------------


class AgentBase:
    """Base class for all multi-agent layer agents.

    Subclasses override:
      - class attrs ``name``, ``model``, ``thinking_level``, ``max_tokens``,
        ``timeout_s``, ``prompt_file`` (optional — filename without .md)
      - ``build_user_message(*args, **kwargs) -> str``
      - ``parse_response(text: str) -> Any`` (raise ValueError on bad format)

    The base ``run()`` method handles call dispatch, timeout, telemetry, and
    error wrapping into AgentResult.
    """

    # Class-level defaults
    name: str = "agent"
    model: str = "gemini-3.1-flash-lite"
    thinking_level: str = "medium"
    max_tokens: int = 64000  # no artificial cap — see Token budget policy
    timeout_s: float = 15.0
    prompt_file: str | None = None
    system_prompt: str = ""

    def __init__(self) -> None:
        if self.prompt_file and not self.system_prompt:
            self.system_prompt = self._load_prompt(self.prompt_file)

    @staticmethod
    def _load_prompt(filename: str) -> str:
        """Load prompts/<filename>.md relative to this package."""
        p = Path(__file__).parent / "prompts" / f"{filename}.md"
        if not p.exists():
            raise FileNotFoundError(f"agent prompt not found: {p}")
        return p.read_text(encoding="utf-8")

    def build_user_message(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError

    def parse_response(self, text: str) -> Any:
        raise NotImplementedError

    async def run(self, *args: Any, timeout: float | None = None,
                   **kwargs: Any) -> AgentResult:
        """Execute the agent. Returns AgentResult; raises on timeout/parse fail."""
        effective_timeout = timeout if timeout is not None else self.timeout_s
        user_msg = self.build_user_message(*args, **kwargs)

        t0 = time.perf_counter()
        try:
            text, usage = await asyncio.wait_for(
                _gemini_lite_call(
                    model=self.model,
                    system_prompt=self.system_prompt,
                    user_msg=user_msg,
                    thinking_level=self.thinking_level,
                    max_tokens=self.max_tokens,
                    timeout=effective_timeout,
                ),
                timeout=effective_timeout,
            )
        except asyncio.TimeoutError as e:
            raise AgentTimeoutError(
                f"agent={self.name} timed out after {effective_timeout}s"
            ) from e
        latency_ms = (time.perf_counter() - t0) * 1000.0

        try:
            value = self.parse_response(text)
        except ValueError as e:
            raise AgentFailedError(
                f"agent={self.name} parse failure: {e}; raw={text[:200]!r}"
            ) from e

        result = AgentResult(
            value=value,
            model=self.model,
            latency_ms=latency_ms,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            thoughts_tokens=int(usage.get("thoughts_tokens", 0)),
            thinking_level=self.thinking_level,
            raw_response=text,
            fallback_used=bool(usage.get("fallback_used", False)),
            provider=str(usage.get("provider", "vertex")),
            error=None,
        )
        _log_agent_telemetry(self.name, result)
        return result


# ---------------------------------------------------------------------------
# Telemetry (best-effort JSONL append)
# ---------------------------------------------------------------------------


def _log_agent_telemetry(agent_name: str, result: AgentResult) -> None:
    """Append a JSONL line to the agent telemetry log if path is set.

    Honors ``KUKAI_AGENT_TELEMETRY_PATH`` env var. Silently no-ops if path
    missing or write fails (telemetry must NEVER block agent flow).
    """
    path = os.environ.get("KUKAI_AGENT_TELEMETRY_PATH", "")
    if not path:
        return
    try:
        # Defense against env-var injection: resolve and verify the path stays
        # inside a known-safe prefix. Server runs as root on VPS — a misconfig
        # like KUKAI_AGENT_TELEMETRY_PATH=../etc/cron.d/x would otherwise write
        # to arbitrary filesystem locations.
        p = Path(path).resolve()
        _safe_prefixes = (
            Path("/tmp").resolve(),
            Path.cwd().resolve(),
            (Path(__file__).resolve().parents[2] / "data").resolve(),  # backend/data
        )
        if not any(str(p).startswith(str(prefix)) for prefix in _safe_prefixes):
            # Silently no-op rather than crash — telemetry is best-effort.
            return
        record = {
            "ts": time.time(),
            "agent": agent_name,
            "model": result.model,
            "thinking_level": result.thinking_level,
            "latency_ms": round(result.latency_ms, 1),
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "thoughts_tokens": result.thoughts_tokens,
            "provider": result.provider,
            "fallback_used": result.fallback_used,
        }
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — telemetry is best-effort
        pass
