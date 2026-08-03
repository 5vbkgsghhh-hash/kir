"""Pillar C — grounding / anti-fabrication gate.

The study (data/study_2026-06-07.md) found DeepSeek's most dangerous failure
mode: open-ended persona/normcontrol prompts bypass tools entirely and the
model fabricates (s30 — 0 tool calls, invented GOST clauses + a fake "560
warnings"). This gate is a SOFT post-loop check: on an ANALYSIS turn it

  * REPROMPTS once if the model answered with NO grounding tool call at all;
  * ANNOTATES (non-destructive caveat) if a specific norm clause is cited
    without a lookup_norm result backing it.

It NEVER blocks a grounded answer, and is a no-op on non-analysis turns
(counts, filters, writes). Pure functions → unit-testable without LLM/DB.

Plan: /root/.claude/plans/recursive-inventing-lecun.md (Milestone 1).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

# Norm documents (ГОСТ/СП/СНиП/ПУЭ/ФЗ) followed by a numeric code, OR an explicit
# clause reference (п. / пункт N). A bare "СП"/"по нормам" with NO number is NOT
# a fabricable citation and must not match (keeps false-positives near zero).
_NORM_DOC_RE = re.compile(
    r"\b(?:ГОСТ|СП|СНиП|СНИП|ПУЭ|ФЗ)\s*(?:Р\s*)?\d[\d.\-–]*",
    re.IGNORECASE,
)
_CLAUSE_RE = re.compile(
    r"\b(?:п\.?|пункт[а-я]*|статья|ст\.?)\s*\d+(?:[.\d]*)",
    re.IGNORECASE,
)

# Persona / normcontrol / advisory openings that invite an ungrounded essay.
_PERSONA_RE = re.compile(
    r"(действуй\s+как|выступи\s+как|нормоконтрол|на\s+соответстви|"
    r"дай\s+рекомендац|порекомендуй|проверь\s+(?:модель|проект).*(?:по\s+сп|по\s+гост|норм)|"
    r"отчёт\s+о|отчет\s+о)",
    re.IGNORECASE,
)

_GROUNDING_TOOLS = {
    "query_model", "execute_revit_code", "get_model_info", "get_model_details",
    "lookup_norm", "lookup_gesn", "apply_revit_write", "select_elements",
    "highlight_elements", "build_schedule", "generate_report",
}


@dataclass
class GateResult:
    verdict: str           # "pass" | "reprompt" | "annotate"
    reason: str = ""


def cited_norm_clauses(text: str) -> list[str]:
    """Specific, fabricable norm citations in the answer (doc+number or п.N)."""
    if not text:
        return []
    return _NORM_DOC_RE.findall(text) + _CLAUSE_RE.findall(text)


def has_grounding_tool_call(messages: list[dict[str, Any]]) -> bool:
    """True if any tool actually ran this turn (a role=tool result exists, or an
    assistant message carried tool_calls)."""
    for m in messages or []:
        role = m.get("role")
        if role == "tool":
            return True
        if role == "assistant" and m.get("tool_calls"):
            return True
    return False


def lookup_norm_results_present(messages: list[dict[str, Any]]) -> bool:
    """True if a lookup_norm tool result is in the message history.

    NOTE: this checks only that the tool was CALLED — kept for back-compat and
    for callers that only have tool names. Grounding decisions must use
    ``lookup_norm_hit`` (which requires a real, non-empty result)."""
    for m in messages or []:
        if m.get("role") != "tool":
            continue
        name = m.get("_tool_name") or m.get("name") or ""
        if name == "lookup_norm":
            return True
    return False


def _result_is_norm_hit(raw: Any) -> bool:
    """True only when a lookup_norm RESULT actually found a norm.

    B2 — the anti-fabrication gate must distinguish a real hit from a call that
    missed (``found: 0``) or errored (``error: true``). The executor returns
    ``{"found": N, "results": [...]}`` on success and ``{"found": 0, ...}`` /
    ``{"error": true, ...}`` otherwise (kukai/llm/tool_handlers/norms.py). Accepts
    a dict or a JSON string (tool results arrive serialized on the wire)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return False
    if not isinstance(raw, dict):
        return False
    if raw.get("error"):
        return False
    found = raw.get("found")
    if isinstance(found, bool):  # guard: bool is an int subclass
        return found
    if isinstance(found, int):
        return found > 0
    return bool(raw.get("results"))


def lookup_norm_hit(messages: list[dict[str, Any]]) -> bool:
    """True if a lookup_norm tool result in the history actually RETURNED a norm
    (``found > 0``) — not merely that lookup_norm was called and missed. The
    result payload is read from ``_result`` (dict) or ``content`` (JSON str)."""
    for m in messages or []:
        if m.get("role") != "tool":
            continue
        name = m.get("_tool_name") or m.get("name") or ""
        if name == "lookup_norm" and _result_is_norm_hit(m.get("_result", m.get("content"))):
            return True
    return False


def is_analysis_turn(user_msg: str, intent_meta: Optional[dict] = None) -> bool:
    """Whether this turn is analysis/persona/normcontrol (gate applies) vs a
    concrete count/filter/write (gate is a no-op)."""
    if not user_msg:
        return False
    if intent_meta and intent_meta.get("intent") == "diagnose":
        return True
    if _PERSONA_RE.search(user_msg):
        return True
    # A request that itself references a specific norm (СП/ГОСТ/п.N) is a
    # normcontrol turn regardless of phrasing ("проверь по СП 118... п.4.6").
    if cited_norm_clauses(user_msg):
        return True
    try:  # reuse the existing QA-trigger detector as an extra signal
        from kukai.qa_checks import detect_qa_trigger
        if detect_qa_trigger(user_msg):
            return True
    except Exception:  # noqa: BLE001 — best-effort; persona regex already covered
        pass
    return False


def evaluate_grounding(
    user_msg: str,
    collected_text: str,
    messages: list[dict[str, Any]],
    intent_meta: Optional[dict] = None,
) -> GateResult:
    """Decide pass / reprompt / annotate for the just-produced answer."""
    if not is_analysis_turn(user_msg, intent_meta):
        return GateResult("pass", "not an analysis turn")
    if not has_grounding_tool_call(messages):
        return GateResult("reprompt", "analysis turn with zero grounding tool calls")
    # B2: a norm clause is grounded only by a lookup_norm HIT (found>0), not by a
    # call that missed/errored — otherwise a fabricated citation after an empty
    # lookup slips through unflagged.
    if cited_norm_clauses(collected_text) and not lookup_norm_hit(messages):
        return GateResult("annotate", "norm clause cited without a lookup_norm hit")
    return GateResult("pass", "grounded")
