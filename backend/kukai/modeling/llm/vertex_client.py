"""VertexGeminiClient — real LLMClient implementation using Vertex AI Gemini Flash.

## Architectural Decision Record (post-Plan 6)

**Transport:** Direct `httpx.post` to `aiplatform.googleapis.com`, NOT litellm's
`vertex_ai/*` model prefix.

**Why:** KUKAI uses Vertex AI Express Mode (key format `AQ.A...`), which is API-key
auth (header `x-goog-api-key`), not service-account-JSON auth. litellm's
`vertex_credentials=KEY` path runs `json.loads(credentials)` on the value and
crashes when it's an Express Mode key string. The production-validated pattern
is implemented in this module — see `_call_with_failover` for the
x-goog-api-key + httpx.post shape. Any future LLMClient implementations
targeting KUKAI's Vertex billing MUST follow this pattern, not litellm's
vertex_ai provider.

**Fallback chain:** Vertex → Google AI Studio (KUKAI_LLM_API_KEY env). Both share
the same Gemini Flash family; the Studio path uses `generativelanguage.googleapis.com`.

**Schema contract:** The CodeProposal output schema spec lives in
`subagent/persona.CODE_PROPOSAL_SCHEMA_SPEC` and is included automatically by
`build_llm_prompt_inputs`. Do NOT duplicate the schema text in this module —
that was the Plan 6 anti-pattern that this client's refactor (Plan 7) removed.

**Cascade routing model IDs (Phase 4 Task 2):**
- ``FLASH_MODEL_ID = "gemini-3.1-flash-lite"`` (default; cheap, fast)
- ``PRO_MODEL_ID = "gemini-3.1-pro"`` (used by Foreman.dispatch_task when
  the router selects ``ModelChoice.PRO`` — tier-3 parametric, repair attempts,
  many-dimension elements, large element counts).

The Foreman is expected to construct TWO VertexGeminiClient instances with
these model IDs and pass both to its constructor (`subagent` + `pro_subagent`).

Per spec Section 5.4 + Plan 6 vertical-slice validation. Uses litellm-free
direct HTTP because Vertex Express Mode is incompatible with litellm's
vertex_ai provider (Plan 6 finding).
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import time
from typing import Any

import httpx

from kukai.modeling.llm.client import LLMClient  # noqa: F401  (protocol marker)
from kukai.modeling.llm.env_config import VertexAIConfig, get_vertex_config
from kukai.modeling.schemas.llm import CodeProposal, LLMPromptInputs
from kukai.modeling.subagent.persona import SCHEMA_SPEC_MARKER


logger = logging.getLogger(__name__)


_VERTEX_URL_TMPL = (
    "https://aiplatform.googleapis.com/v1/publishers/google/models/"
    "{model}:generateContent"
)
_STUDIO_URL_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)


# Phase 4 Task 2 — cascade routing model IDs pinned for KUKAI Foreman.
FLASH_MODEL_ID = "gemini-3.1-flash-lite"
PRO_MODEL_ID = "gemini-3.1-pro"


class VertexGeminiClient:
    """LLMClient implementation backed by Vertex AI Gemini Flash (Express Mode)."""

    def __init__(
        self,
        config: VertexAIConfig | None = None,
        model: str = "gemini-3.1-flash-lite",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        timeout_seconds: float = 60.0,
    ):
        self._config = config or get_vertex_config()
        if not self._config.available:
            raise EnvironmentError(
                "Vertex AI credentials missing — set KUKAI_VERTEX_AI_API_KEY, "
                "KUKAI_VERTEX_AI_PROJECT, KUKAI_VERTEX_AI_LOCATION"
            )
        # Accept both bare names ("gemini-2.0-flash-001") and prefixed
        # ("vertex_ai/gemini-2.0-flash-001"). Strip the prefix for the URL.
        if "/" in model:
            model = model.split("/", 1)[1]
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        # Wave 6B (Fix B#4): expose .calls so ForemanBudgetGuard._count can
        # observe per-phase LLM invocations and trip the llm cap in production.
        # Mirrors MockLLMClient.calls contract — append on entry to each
        # external-work method, before any await.
        self.calls: list[dict[str, Any]] = []

    async def generate_code_proposal(
        self, inputs: LLMPromptInputs
    ) -> CodeProposal:
        # Wave 6B (Fix B#4): record on entry so a retry-spiral on this
        # client is visible to the BudgetGuard even if every attempt later
        # raises (e.g., Vertex 429s + Studio fallback also fails).
        self.calls.append({
            "method": "generate_code_proposal",
            "args_summary": (
                f"model={self._model} persona_len={len(inputs.persona_prompt)} "
                f"rag_snippets={len(inputs.rag_snippets)}"
            ),
            "ts": time.monotonic(),
        })
        if SCHEMA_SPEC_MARKER not in inputs.persona_prompt:
            logger.warning(
                "VertexGeminiClient: persona_prompt does not contain CodeProposal "
                "schema spec; downstream prompt will reference a non-existent system "
                "message section. Use subagent.persona.build_llm_prompt_inputs to "
                "construct LLMPromptInputs correctly."
            )
        prompt_text = _assemble_prompt(inputs)
        body = {
            "systemInstruction": {"parts": [{"text": inputs.persona_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
            "generationConfig": {
                "temperature": self._temperature,
                "maxOutputTokens": self._max_tokens,
                "responseMimeType": "application/json",
            },
        }

        text = await self._call_with_failover(body)
        if not text:
            raise RuntimeError("Vertex Gemini returned empty response")
        return _parse_code_proposal(text)

    async def _call_with_failover(self, body: dict[str, Any]) -> str:
        """Try Vertex Express first; fall back to Studio if KUKAI_LLM_API_KEY set."""
        vertex_url = _VERTEX_URL_TMPL.format(model=self._model)
        vertex_headers = {
            "x-goog-api-key": self._config.api_key,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as cl:
            try:
                r = await cl.post(vertex_url, json=body, headers=vertex_headers)
                if r.status_code == 200:
                    return _extract_text(r.json())
                logger.warning(
                    "Vertex Express returned %s: %s", r.status_code, r.text[:300]
                )
                last_err = f"vertex_http_{r.status_code}: {r.text[:300]}"
            except Exception as e:  # noqa: BLE001
                last_err = f"vertex_exc: {type(e).__name__}: {e}"
                logger.warning("Vertex Express call failed: %s", last_err)

            # Studio fallback
            studio_key = os.environ.get("KUKAI_LLM_API_KEY")
            if studio_key:
                studio_url = _STUDIO_URL_TMPL.format(model=self._model, key=studio_key)
                try:
                    r = await cl.post(
                        studio_url, json=body, headers={"Content-Type": "application/json"}
                    )
                    if r.status_code == 200:
                        logger.info("Studio fallback succeeded")
                        return _extract_text(r.json())
                    last_err = (
                        f"studio_http_{r.status_code}: {r.text[:300]} "
                        f"(after vertex: {last_err})"
                    )
                except Exception as e:  # noqa: BLE001
                    last_err = (
                        f"studio_exc: {type(e).__name__}: {e} "
                        f"(after vertex: {last_err})"
                    )

            raise RuntimeError(f"All Gemini endpoints failed: {last_err}")


class VertexFinishReasonError(RuntimeError):
    """Audit N6 — raised when Gemini returned an empty candidate due to a finishReason
    other than STOP/MAX_TOKENS (e.g. SAFETY, RECITATION, BLOCKLIST). Without this,
    a SAFETY-blocked response was silently treated as empty text downstream.
    """
    def __init__(self, reason: str, ratings: Any = None):
        self.reason = reason
        self.ratings = ratings
        msg = f"Gemini stopped with finishReason={reason!r}"
        if ratings:
            msg += f"; safetyRatings={ratings!r}"
        super().__init__(msg)


def _extract_text(response_json: dict[str, Any]) -> str:
    """Extract text from Gemini generateContent response shape."""
    try:
        candidates = response_json.get("candidates", [])
        if not candidates:
            return ""
        first = candidates[0]
        parts = first.get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if text:
            return text
        # Audit N6 — empty text + non-STOP finishReason = surface, don't swallow.
        finish_reason = first.get("finishReason")
        if finish_reason and finish_reason not in ("STOP", "MAX_TOKENS", "FINISH_REASON_UNSPECIFIED"):
            raise VertexFinishReasonError(finish_reason, first.get("safetyRatings"))
        return ""
    except VertexFinishReasonError:
        raise
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Failed to extract text from Gemini response: {e}; raw: {str(response_json)[:500]}"
        ) from e


def _assemble_prompt(inputs: LLMPromptInputs) -> str:
    """Build the user-side prompt body.

    Persona + schema spec go in the SYSTEM message (assembled by
    subagent.persona.build_llm_prompt_inputs). User message contains:
    skill content, task brief, RAG snippets, failure catalog.

    Per Plan 7 (Plan 6 findings refactor): schema spec is no longer duplicated
    here — it's part of inputs.persona_prompt now.
    """
    snippets_block = "\n\n".join(
        f"### RAG Snippet #{sid}\nTitle: {title}\n\n{body}"
        for (sid, title, body) in inputs.rag_snippets
    ) or "(no RAG snippets provided for this task)"

    return (
        "## Skill Methodology\n\n"
        f"{inputs.skill_content}\n\n"
        "## RAG Snippets (cite by id inline as `// RAG:#<id>`)\n\n"
        f"{snippets_block}\n\n"
        "## Failure Category Catalog (you MUST attest each in failure_mode_checks)\n\n"
        f"{inputs.failure_catalog_summary}\n\n"
        "## Task Brief (JSON)\n\n"
        f"```json\n{inputs.task_brief_json}\n```\n\n"
        "## Output\n\n"
        "Respond with a single JSON object matching CodeProposal schema EXACTLY (see system message). "
        "No prose. No markdown wrapper. Just JSON.\n"
    )


def _parse_code_proposal(text: str) -> CodeProposal:
    """Parse Gemini's response into CodeProposal.

    Handles cases where Gemini wraps response in ```json ... ``` despite
    `responseMimeType` request.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL)
        if m:
            cleaned = m.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Vertex Gemini returned non-JSON response: {e}; first 500 chars: {cleaned[:500]}"
        ) from e
    return CodeProposal.model_validate(data)
