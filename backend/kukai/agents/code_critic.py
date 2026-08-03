"""CodeCritic — pre-compile review of generated C# Revit code.

Catches the F3+F4 utilization/faithfulness failure modes (56% of all
compile failures per the 2026-05-11 diagnostic):
  - API hallucination (method that doesn't exist)
  - Missing Transaction wrapping for write operations
  - SDK example leftovers (commandData, m_revit, m_app)
  - Argument mismatch vs retrieved example signatures
  - Cross-version mistakes (Toposolid pre-2024, IntegerValue post-2026)
  - Query↔code alignment (count query producing a Wall, etc.)

Output JSON contract (see prompts/code_critic.md):
  {
    "verdict": "OK" | "FIX_NEEDED",
    "issues": ["...", ...],
    "fixed_code": "<full fixed C#>" | null,
    "confidence": "high" | "medium" | "low"
  }
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from .base import AgentBase, parse_json_block


_VALID_VERDICTS = {"OK", "FIX_NEEDED"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


class CodeCritic(AgentBase):
    """LLM-based pre-compile reviewer."""

    name = "code_critic"
    model = "gemini-3.5-flash"
    thinking_level = "medium"
    max_tokens = 64000  # no cap per Token budget policy
    timeout_s = 15.0    # post-flight stage, parallel with VersionChecker
    prompt_file = "code_critic"

    def build_user_message(
        self,
        query: str,
        code: str,
        examples: Sequence[dict] | None = None,
    ) -> str:
        """Serialize as JSON for clear structure.

        Caps:
          - query[:500]
          - code[:3000]
          - examples: max 5 entries, each example_code[:500]
        """
        ex_capped: list[dict] = []
        for e in (examples or [])[:5]:
            ec = e.get("example_code") or e.get("example") or ""
            if isinstance(ec, list):
                # Some entries store as a list
                ec = "\n".join(str(x) for x in ec)
            ex_capped.append({
                "name": str(e.get("name", "?")),
                "namespace": str(e.get("namespace", e.get("ns", ""))),
                "description": (str(e.get("description", "")))[:300],
                "example_code": str(ec)[:500],
            })

        payload = {
            "query": (query or "")[:500],
            "code": (code or "")[:3000],
            "examples": ex_capped,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def parse_response(self, text: str) -> dict[str, Any]:
        data = parse_json_block(text)
        verdict = data.get("verdict")
        if verdict not in _VALID_VERDICTS:
            raise ValueError(f"invalid verdict {verdict!r}; expected OK or FIX_NEEDED")
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            raise ValueError(f"issues must be a list: {issues!r}")
        fixed_code = data.get("fixed_code")
        if fixed_code is not None and not isinstance(fixed_code, str):
            raise ValueError(f"fixed_code must be string or null: {fixed_code!r}")
        confidence = data.get("confidence", "medium")
        if confidence not in _VALID_CONFIDENCE:
            confidence = "medium"
        return {
            "verdict": verdict,
            "issues": [str(x) for x in issues],
            "fixed_code": fixed_code,
            "confidence": confidence,
        }
