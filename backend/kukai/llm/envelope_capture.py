"""Wave 2 — request-envelope capture for offline shadow-replay + cache measurement.

Persists the FULL LLM request envelope (messages + model + provider params + tool names)
and the outcome (finish_reason / tool_calls / usage) so scripts/shadow_replay.py can
re-issue real prod requests against candidate configs OFFLINE, and so we can read the
provider `usage` for cache-hit tokens (the only authoritative answer to "what would
prompt caching save").

⚠️ PII / sensitivity: the messages contain USER CONTENT. This is OFF by default
(KUKAI_CAPTURE_ENVELOPES=1 to enable), SAMPLED (KUKAI_CAPTURE_SAMPLE, default 1.0), and
written to a local JSONL the operator controls. Treat data/request_envelopes.jsonl as
sensitive — retention/redaction are an explicit operator decision; do not enable broadly
without it. Capture is best-effort and never raises into the LLM hot path.

NOTE on usage: capture runs right after litellm.acompletion returns. The MAIN chat path
streams (stream=True), so at that moment .usage/.choices are not yet populated → outcome.usage
is null for streamed calls (non-streaming agent/simple calls do record usage). The request
half (messages/model/tools/params) IS always captured → replay works. To answer "does the
provider cache", probe directly: 2× non-stream acompletion with the same prefix and read
usage.prompt_tokens_details.cached_tokens (measured 2026-06-10: DeepInfra returned ~99% of a
~17k-token prefix from cache on the repeat call — automatic provider caching works).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

_counter = {"n": 0}


def _config() -> tuple[bool, float]:
    on = os.getenv("KUKAI_CAPTURE_ENVELOPES", "0") == "1"
    try:
        rate = float(os.getenv("KUKAI_CAPTURE_SAMPLE", "1.0"))
    except (TypeError, ValueError):
        rate = 1.0
    return on, max(0.0, min(1.0, rate))


def _path() -> Path:
    p = os.getenv("KUKAI_CAPTURE_PATH", "")
    if p:
        return Path(p)
    # backend/data (parents[2] = backend; this file is backend/kukai/llm/...).
    return Path(__file__).resolve().parents[2] / "data" / "request_envelopes.jsonl"


def _cached_tokens(usage: Any) -> Any:
    """Provider cache-hit prompt tokens, if reported (shape varies by provider/litellm)."""
    for attr in ("prompt_tokens_details", "cache_read_input_tokens", "cached_tokens"):
        v = getattr(usage, attr, None)
        if v is not None:
            return getattr(v, "cached_tokens", v) if hasattr(v, "cached_tokens") else v
    return None


def _outcome(response: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        ch = response.choices[0]
        out["finish_reason"] = getattr(ch, "finish_reason", None)
        msg = getattr(ch, "message", None)
        out["has_text"] = bool(getattr(msg, "content", None))
        tc = getattr(msg, "tool_calls", None) if msg else None
        out["tool_calls"] = len(tc) if tc else 0
    except Exception:
        pass
    try:
        u = response.usage
        out["usage"] = {
            "prompt_tokens": getattr(u, "prompt_tokens", None),
            "completion_tokens": getattr(u, "completion_tokens", None),
            "cached_tokens": _cached_tokens(u),
        }
    except Exception:
        pass
    return out


def capture(model: Any, messages: Any, tools: Any, params: dict[str, Any], response: Any) -> None:
    """Best-effort, flag-gated, sampled write of one request envelope. Never raises."""
    on, rate = _config()
    if not on:
        return
    _counter["n"] += 1
    if rate < 1.0 and (_counter["n"] % max(1, round(1.0 / rate))) != 0:
        return
    try:
        tool_names = [
            t.get("function", {}).get("name")
            for t in (tools or []) if isinstance(t, dict)
        ]
        rec = {
            "ts": time.time(),
            "model": model,
            "messages": messages,          # PII — user content
            "tool_names": tool_names,
            "params": params,
            "outcome": _outcome(response),
        }
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # measurement must never break a real request
