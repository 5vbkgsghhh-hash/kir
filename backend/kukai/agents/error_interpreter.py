"""ErrorInterpreter — turns a compiler/runtime error into a structured fix hint.

Phase 5 of the multi-agent RAG layer. Fires CONDITIONALLY in the repair loop:
when the generated code fails to compile (or throws at runtime), the raw error
string is fed here together with the code and the retrieved API examples. The
agent emits a small JSON object that the repair loop injects into the next
code-gen attempt's prompt:

  {
    "error_explanation": "<one sentence>",
    "fix_strategy": "<one or two sentences>",
    "suggested_api": "<Class.Method or full signature>" | null
  }

Design notes:
- Tighter timeout (10s) vs post-flight agents (12-15s): we are in the repair
  loop and the user is already waiting on the second attempt.
- ``suggested_api`` may be null when the fix is not "call X instead of Y" but
  rather a transformation (e.g. "wrap the mutation in a Transaction").
- ``error_explanation`` and ``fix_strategy`` are REQUIRED and non-empty —
  an interpreter response with nothing to say is useless to the repair loop
  and we'd rather raise than silently degrade it.
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from .base import AgentBase, parse_json_block


_CODE_MAX_CHARS = 2500
_ERROR_MAX_CHARS = 1000
_EXAMPLES_MAX = 3
_EXAMPLE_CODE_MAX_CHARS = 400


class ErrorInterpreter(AgentBase):
    """LLM-based interpreter of compiler / runtime errors for the repair loop."""

    name = "error_interpreter"
    model = "gemini-3.5-flash"
    thinking_level = "medium"
    max_tokens = 64000  # no cap per Token budget policy
    timeout_s = 10.0    # conditional, in repair loop — tighter than post-flight
    prompt_file = "error_interpreter"

    def build_user_message(
        self,
        code: str,
        error: str,
        examples: Sequence[dict] | None = None,
    ) -> str:
        """Serialize ``{code, error, examples}`` as JSON.

        Caps:
          - code[:2500]
          - error[:1000]
          - examples: max 3 entries, each example_code[:400]
        """
        ex_capped: list[dict] = []
        for e in (examples or [])[:_EXAMPLES_MAX]:
            ec = e.get("example_code") or e.get("example") or ""
            if isinstance(ec, list):
                # Some entries store as a list — join into one string
                ec = "\n".join(str(x) for x in ec)
            ex_capped.append({
                "name": str(e.get("name", "?")),
                "namespace": str(e.get("namespace", e.get("ns", ""))),
                "description": (str(e.get("description", "")))[:300],
                "example_code": str(ec)[:_EXAMPLE_CODE_MAX_CHARS],
            })

        payload = {
            "code": (code or "")[:_CODE_MAX_CHARS],
            "error": (error or "")[:_ERROR_MAX_CHARS],
            "examples": ex_capped,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def parse_response(self, text: str) -> dict[str, Any]:
        data = parse_json_block(text)
        if not isinstance(data, dict):
            raise ValueError(f"expected JSON object, got: {type(data).__name__}")

        explanation = data.get("error_explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError(
                f"error_explanation must be a non-empty string: {explanation!r}"
            )

        strategy = data.get("fix_strategy")
        if not isinstance(strategy, str) or not strategy.strip():
            raise ValueError(
                f"fix_strategy must be a non-empty string: {strategy!r}"
            )

        suggested = data.get("suggested_api", None)
        if suggested is not None:
            if not isinstance(suggested, str):
                raise ValueError(
                    f"suggested_api must be string or null: {suggested!r}"
                )
            # Normalize empty string to null — empty is meaningless
            if not suggested.strip():
                suggested = None

        return {
            "error_explanation": explanation.strip(),
            "fix_strategy": strategy.strip(),
            "suggested_api": suggested,
        }
