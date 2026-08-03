"""CodeJudge — LLM-as-Judge for CodeProposal grading.

Per CodeJudge (arXiv:2410.02184). Returns a JudgeVerdict with score 1-5, the
list of FailureCategory values the judge flagged, severity, suggestions, and
a natural-language rationale.

Phase 1 scope: standalone module. Foreman wire-up lives in Phase 2 (Reflexion
loop consumes judge failures as repair triggers).
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Protocol

from kukai.modeling.schemas.judge import JudgeSeverity, JudgeVerdict
from kukai.modeling.schemas.llm import CodeProposal, FailureCategory
from kukai.modeling.schemas.tasks import TaskBrief

# Re-export JudgeSeverity/JudgeVerdict for callers who expect them from the
# judge module (golden scenarios + repair_loop tests).
__all__ = ["CodeJudge", "JudgeSeverity", "JudgeVerdict"]


_DEFAULT_PROMPT_PATH = Path(__file__).parent / "prompts" / "structural_judge.md"


class _RawTextLLMLike(Protocol):
    async def generate_raw_text(self, prompt: str) -> str: ...


def _extract_json_object(text: str) -> str:
    """Extract a single JSON object literal from arbitrary LLM raw-text output.

    Handles fenced code blocks (```json...```, ```JSON...```, etc.), prose
    before/after the JSON, indented fences, and trailing whitespace. The
    contract is permissive on input and strict on output: returns the
    substring covering one valid JSON object. Caller then feeds this to
    json.loads().

    Audit N8: previously used find('{') + rfind('}') which fails when the LLM
    emits multiple sibling objects (e.g. thinking trace { ... } then verdict
    { ... }). Now uses json.JSONDecoder.raw_decode from the first '{' to
    consume exactly one valid JSON value and ignore trailing content.

    Raises ValueError if no `{...}` object boundary can be found or no
    parseable object exists at any candidate position.
    """
    if not text or not text.strip():
        raise ValueError("LLM returned empty text")
    decoder = json.JSONDecoder()
    pos = text.find("{")
    while pos != -1:
        try:
            _, end_pos = decoder.raw_decode(text, pos)
            return text[pos:end_pos]
        except json.JSONDecodeError:
            # Try the next candidate '{' — handles "{ broken } { valid }"
            pos = text.find("{", pos + 1)
    raise ValueError(
        f"no parseable JSON object found in LLM response: {text[:200]!r}"
    )


class CodeJudge:
    """LLM-as-Judge harness.

    The LLM client supplied here is a simpler shape than the modeling
    LLMClient protocol (which is bolted to CodeProposal) — judge needs raw-text
    output so we accept any object with `async generate_raw_text(prompt)`.
    """

    def __init__(
        self,
        llm: _RawTextLLMLike,
        prompt_path: Path | str | None = None,
    ):
        self._llm = llm
        path = Path(prompt_path) if prompt_path else _DEFAULT_PROMPT_PATH
        self._prompt_template = path.read_text(encoding="utf-8")

    async def judge(
        self,
        proposal: CodeProposal,
        brief: TaskBrief,
    ) -> JudgeVerdict:
        """Run the judge against a single proposal.

        Raises:
            ValueError: LLM returned no JSON object literal (empty or non-JSON).
            json.JSONDecodeError: LLM produced text that looks like JSON but is malformed.
            pydantic.ValidationError: JSON parsed but didn't match JudgeVerdict schema.
        """
        prompt = self._build_prompt(proposal, brief)
        raw = await self._llm.generate_raw_text(prompt)
        body = _extract_json_object(raw)
        data = json.loads(body)
        return JudgeVerdict.model_validate(data)

    # ---- helpers ----

    def _build_prompt(self, proposal: CodeProposal, brief: TaskBrief) -> str:
        taxonomy_lines = "\n".join(
            f"- {c.value}: {self._taxonomy_blurb(c)}" for c in FailureCategory
        )
        sections = [
            self._prompt_template,
            "\n---\n## Task Context\n",
            f"```json\n{brief.model_dump_json(indent=2)}\n```",
            "\n## Generated C# code\n",
            f"```csharp\n{proposal.csharp_code}\n```",
            "\n## Full FailureCategory taxonomy\n",
            taxonomy_lines,
            "\n## Your verdict (JSON only)\n",
        ]
        return "".join(sections)

    @staticmethod
    def _taxonomy_blurb(c: FailureCategory) -> str:
        """One-line description for the prompt taxonomy section."""
        return _BLURBS[c]


# Keyed by enum value so adding categories doesn't require editing this file.
_BLURBS_BY_VALUE: dict[str, str] = {
    "unit_mismatch": "feet vs millimeters mixed",
    "parameter_name_drift": "parameter name does not match Revit version",
    "family_not_activated": "FamilySymbol used without Activate()",
    "transaction_nesting": "nested Transaction blocks",
    "missing_null_guard": "GetElement / FirstOrDefault unguarded",
    "stale_element_id": "ElementId reused after Commit",
    "wrong_namespace": "non-Revit / non-System namespace",
    "duplicate_mark": "two elements with the same Mark parameter",
    "wrong_host_category": "host element category mismatch",
    "wrong_level_binding": "wrong base/top level pair",
    "geometry_out_of_range": "coords outside project envelope",
    "invalid_overload_selection": "wrong NewFamilyInstance overload",
    "missing_regenerate": "geometry mutated without Regenerate",
    "cyrillic_name_match": "non-NFC-normalized Cyrillic compare",
    "version_api_mismatch": "API only exists in another Revit major",
    "silent_no_op": "code runs but creates zero elements",
    "idempotency_violation": "duplicates on re-run",
    "scope_creep": "touches elements outside task scope",
    "cross_discipline_contamination": "structural code modifies architectural elements",
    "view_dependent_filter_failure": "filter ignores view-active state",
    "parallel_safety_violation": "non-thread-safe Revit API access",
}


def _default_blurb(value: str) -> str:
    """Fallback blurb when a FailureCategory has no curated description."""
    return value.replace("_", " ")


_BLURBS: dict[FailureCategory, str] = {
    c: _BLURBS_BY_VALUE.get(c.value, _default_blurb(c.value))
    for c in FailureCategory
}
