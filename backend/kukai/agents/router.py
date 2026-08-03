"""Intent router (Milestone 2) — maps classified intent+complexity to a
per-request execution budget: max tool rounds, reasoning effort, tool gating.

Replaces the one-size-fits-all path (reasoning.effort hardcoded "high", uniform
rounds) that made simple tasks slow and let complex tasks spiral (the study's
call-amplification: 15-31 DeepSeek calls/hard-task). Pure function → unit-tested
in isolation; the LLMClient threads the decision into the loop.

Regression safety (the top router risk = misclassification starving a real
task): hard floors (tool-intent >= 4, skill >= 12, family-editor >= 15) and a
conservative None/vague fallback that preserves today's behavior exactly.

Plan: /root/.claude/plans/recursive-inventing-lecun.md (Milestone 2).
"""
from __future__ import annotations

import os

from dataclasses import dataclass
from typing import Optional


@dataclass
class RouteDecision:
    max_rounds: int
    reasoning_effort: str            # "low" | "medium" | "high"
    use_tools_override: Optional[bool]  # None = leave default; False = no tools
    discourage_writes: bool          # True for diagnose (read-heavy analysis)
    intent: str
    complexity: str
    source: str                      # "router" | "default"


def _table(intent: str, complexity: str, base: int) -> tuple[int, str]:
    """(max_rounds, effort) per intent+complexity.

    ``base`` is the configured round ceiling (``llm_max_tool_rounds``, raised to
    50). A HARD task is allowed to grind toward it; simple/composite tasks keep a
    tight budget so they stay fast. The whole-turn wall-clock budget
    (``KUKAI_TURN_BUDGET_S``) is the real backstop, so a high round ceiling only
    helps fast-progressing hard tasks and never produces a runaway turn."""
    simple = complexity in ("trivial", "simple")
    hard = complexity == "hard"
    mid = max(8, base // 2)  # composite/medium budget (~25 at base 50)
    if intent == "count":
        return (4, "low") if simple else (10, "medium")
    if intent in ("list", "filter"):
        if complexity == "simple":
            return (5, "low")
        return (base, "high") if hard else (mid, "medium")
    if intent == "tag":
        return (5, "medium") if simple else (mid, "high")
    if intent == "delete":
        return (4, "medium") if simple else (12, "high")
    if intent == "modify":
        if complexity == "simple":
            return (6, "medium")
        return (base, "high") if hard else (mid, "high")
    if intent == "create":
        if complexity == "simple":
            return (8, "medium")
        return (base, "high") if hard else (mid, "high")  # composite → mid
    if intent in ("schedule", "export"):
        return (8, "medium") if simple else (mid, "high")
    if intent == "diagnose":
        return (mid, "high")
    # Unknown intent → base ceiling, high effort.
    return (base, "high")


def decide_route(
    meta: Optional[dict],
    *,
    base_max_rounds: int,
    is_family_editor: bool,
    has_skill: bool,
) -> RouteDecision:
    """Compute the per-request budget. ``meta`` is intent metadata (rules or LLM)."""
    if not meta or not meta.get("intent"):
        return RouteDecision(
            max_rounds=base_max_rounds, reasoning_effort="high",
            use_tools_override=None, discourage_writes=False,
            intent=(meta or {}).get("intent", ""),
            complexity=(meta or {}).get("complexity", ""), source="default",
        )

    intent = meta.get("intent")
    complexity = meta.get("complexity") or "composite"

    # Conversational turns: answer directly, no tool loop.
    if intent == "converse":
        return RouteDecision(
            max_rounds=0, reasoning_effort="low", use_tools_override=False,
            discourage_writes=False, intent=intent, complexity=complexity,
            source="router",
        )

    if complexity == "vague":
        rounds, effort = max(8, base_max_rounds), "high"
    else:
        rounds, effort = _table(intent, complexity, base_max_rounds)
        # The round cap is a CEILING, not a target: a question answered in one
        # round costs one round whether the cap is 4 or 200. So a tight cap never
        # makes anything faster — it only truncates work that genuinely needed more
        # (live 2026-07-27: "посчитать" is capped at 4, a schedule at 8). Effort and
        # tool gating are the real speed levers and stay per-intent; the ceiling goes
        # generous and the wall-clock budget stays the actual backstop, exactly as
        # _table's own docstring argues. Legacy table caps: KUKAI_ROUTER_ROUND_TABLE=1.
        if os.environ.get("KUKAI_ROUTER_ROUND_TABLE", "0") != "1":
            rounds = max(rounds, base_max_rounds)

    discourage = intent == "diagnose"

    # Floors — a misclassification must never starve a real task.
    rounds = max(rounds, 4)
    if has_skill:
        rounds = max(rounds, 12)
    if is_family_editor:
        rounds = max(rounds, 15)
    # Ceiling — bound worst case without clamping the legitimate 16 max.
    rounds = min(rounds, max(16, base_max_rounds * 2))

    return RouteDecision(
        max_rounds=rounds, reasoning_effort=effort, use_tools_override=None,
        discourage_writes=discourage, intent=intent, complexity=complexity,
        source="router",
    )
