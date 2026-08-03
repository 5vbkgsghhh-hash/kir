"""Multi-agent layer for KUKI RAG pipeline.

Pre-flight (parallel, before main code-gen):
  - IntentClassifier — classifies query intent/complexity/domain
  - QueryReformulator — RU -> EN reformulation for better RAG hit
  - RagReranker — promotes most-relevant retrieved entries to top-5

Post-flight (parallel, after main code-gen, before compile):
  - CodeCritic — catches API hallucination / missing Transaction / wrong args
  - VersionChecker — cross-version (2021-2026) API compatibility check

Conditional (only when compile fails, in repair loop):
  - ErrorInterpreter — turns CS error into actionable fix hint

All agents use ``gemini-3.5-flash`` with ``thinkingLevel=medium`` and
``maxOutputTokens=64000`` (no artificial cap — see plan §Token budget policy).
Routing: Vertex AI (paid, primary) -> Studio (free, fallback). OpenRouter
is intentionally EXCLUDED from the agent fallback chain (per user direction
2026-05-11); only Main Gemini Flash uses OpenRouter as last-resort.

Public API (lazy-loaded via __getattr__):
  AgentBase, AgentResult, AgentTimeoutError, AgentFailedError
  IntentClassifier, QueryReformulator, RagReranker
  CodeCritic, VersionChecker, ErrorInterpreter
"""

from __future__ import annotations

__all__ = [
    # Base
    "AgentBase",
    "AgentResult",
    "AgentTimeoutError",
    "AgentFailedError",
    # Pre-flight
    "IntentClassifier",
    "QueryReformulator",
    "RagReranker",
    # Post-flight
    "CodeCritic",
    "VersionChecker",
    # Conditional
    "ErrorInterpreter",
]


def __getattr__(name: str):
    """Lazy import of base + concrete agents.

    Allows the package to be importable before all agents are implemented,
    so Phase 0.1 (skeleton) can land before Phase 0.2 (AgentBase) and the
    Phase 1-5 concrete agents.
    """
    if name in ("AgentBase", "AgentResult", "AgentTimeoutError", "AgentFailedError"):
        from . import base
        return getattr(base, name)
    if name == "IntentClassifier":
        from .intent_classifier import IntentClassifier
        return IntentClassifier
    if name == "QueryReformulator":
        from .query_reformulator import QueryReformulator
        return QueryReformulator
    if name == "RagReranker":
        from .rag_reranker import RagReranker
        return RagReranker
    if name == "CodeCritic":
        from .code_critic import CodeCritic
        return CodeCritic
    if name == "VersionChecker":
        from .version_checker import VersionChecker
        return VersionChecker
    if name == "ErrorInterpreter":
        from .error_interpreter import ErrorInterpreter
        return ErrorInterpreter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
