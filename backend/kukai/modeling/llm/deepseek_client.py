"""DeepSeekModelingClient — LLMClient over our prod model (DeepSeek via OpenRouter
+ litellm), replacing VertexGeminiClient for the live KUKAI model.

Keeps the framework's CodeProposal contract unchanged (schema-in-prompt comes from
subagent.persona; strict Pydantic validation on the way back). Mirrors the live
product's OpenRouter provider-pin + reasoning effort, and — critic finding H-3 —
robustly handles DeepSeek reasoning leakage (``<think>...</think>`` blocks and
trailing prose around the JSON), which the Vertex parser did not.

Keep VertexGeminiClient too: a factory picks Vertex-vs-DeepSeek so we stay
model-agnostic (never hardcode to one model).
"""
from __future__ import annotations
import json
import logging
import os
import re
import time
from typing import Any

import litellm

from kukai.modeling.llm.client import LLMClient  # noqa: F401  (protocol marker)
from kukai.modeling.llm.vertex_client import _assemble_prompt  # reuse — do not duplicate
from kukai.modeling.schemas.llm import CodeProposal, LLMPromptInputs
from kukai.modeling.subagent.persona import SCHEMA_SPEC_MARKER

logger = logging.getLogger(__name__)

# Resolved lazily so tests don't need prod env. The live prod model id is read from
# the environment (memory: model-id drifts — never hardcode a single value blindly).
_DEFAULT_MODEL = (
    os.environ.get("KUKAI_MODELING_LLM_MODEL")
    or os.environ.get("KUKAI_LLM_MODEL")
    or "openrouter/deepseek/deepseek-v4-flash"
)
# OpenRouter provider pin (mirrors the live client.py — prevents fallback to a
# garbage provider; matches memory's deepseek-empty-incident fix).
_PROVIDER_ORDER = ["DeepInfra", "Novita", "AtlasCloud"]


class DeepSeekModelingClient:
    """LLMClient implementation backed by DeepSeek via OpenRouter (litellm)."""

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 32768,
        timeout_seconds: float = 90.0,
        reasoning_effort: str = "high",
    ):
        self._model = model or _DEFAULT_MODEL
        self._api_key = api_key or os.environ.get("OPENROUTER_API_KEY") or os.environ.get("KUKAI_LLM_API_KEY")
        self._api_base = api_base or os.environ.get("KUKAI_LLM_API_BASE")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._reasoning_effort = reasoning_effort
        # Budget-guard contract (Wave 6B): append on entry, mirrors VertexGeminiClient.calls.
        self.calls: list[dict[str, Any]] = []

    async def generate_code_proposal(self, inputs: LLMPromptInputs) -> CodeProposal:
        self.calls.append({"method": "generate_code_proposal", "model": self._model, "ts": time.monotonic()})
        if SCHEMA_SPEC_MARKER not in inputs.persona_prompt:
            logger.warning(
                "DeepSeekModelingClient: persona_prompt missing CodeProposal schema spec; "
                "use subagent.persona.build_llm_prompt_inputs to construct LLMPromptInputs."
            )
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": inputs.persona_prompt},
                {"role": "user", "content": _assemble_prompt(inputs)},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "timeout": self._timeout,
            "response_format": {"type": "json_object"},
        }
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if str(self._model).startswith("openrouter/"):
            kwargs["extra_body"] = {
                "provider": {"order": _PROVIDER_ORDER, "allow_fallbacks": False},
                "reasoning": {"effort": self._reasoning_effort},
            }
        resp = await litellm.acompletion(**kwargs)
        text = _content_of(resp)
        if not text:
            raise RuntimeError("DeepSeek returned empty response")
        return _parse_code_proposal_robust(text)


def _content_of(resp: Any) -> str:
    """Pull message.content from a litellm ModelResponse; ignore any reasoning field
    (H-3: reasoning must not be parsed as the answer)."""
    try:
        return (resp.choices[0].message.content or "").strip()
    except Exception:
        try:
            return (resp["choices"][0]["message"]["content"] or "").strip()
        except Exception:
            return ""


_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?```", re.DOTALL)


def _parse_code_proposal_robust(text: str) -> CodeProposal:
    """Parse DeepSeek output into CodeProposal, tolerating reasoning leakage:
    strip <think>…</think>, unwrap ```json fences, and if still not pure JSON
    extract the LAST balanced {…} object (handles trailing prose)."""
    s = _THINK.sub("", text or "").strip()
    if s.startswith("```"):
        m = _FENCE.search(s)
        if m:
            s = m.group(1).strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError:
        obj = _last_json_object(s)
        if obj is None:
            raise RuntimeError(f"DeepSeek returned non-JSON; first 400 chars: {s[:400]}")
        data = json.loads(obj)
    return CodeProposal.model_validate(data)


def _last_json_object(s: str) -> str | None:
    """Greedy-brace: return the last balanced {...} substring that json-parses."""
    end = s.rfind("}")
    while end != -1:
        depth = 0
        for i in range(end, -1, -1):
            c = s[i]
            if c == "}":
                depth += 1
            elif c == "{":
                depth -= 1
                if depth == 0:
                    cand = s[i:end + 1]
                    try:
                        json.loads(cand)
                        return cand
                    except json.JSONDecodeError:
                        break
        end = s.rfind("}", 0, end)
    return None
