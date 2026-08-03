"""kukai.rag.wiki_router — dormant capability-router (Wiki-LLM) alternative RAG path.

Ported from /root/kukai-wiki/nav/{wiki_query,capability_router}.py (see
those files' docstrings for the design/measurement reports this implements).

Only ever exercised when the environment variable KUKAI_RAG_WIKI_ROUTER is
"shadow" or "on" — see the seam in
kukai/llm/prompts.py::PromptAssembler.build_prompt_components(). With the
flag unset/off (today's prod default), nothing in this package runs: the
seam's default branch never imports this package at all, and even a bare
import of it (e.g. from a healthcheck) has no side effects beyond parsing
these modules — no page load, no network, no writes.

Public surface: get_wiki_router() — a lazy process-wide singleton adapter
exposing .ensure_loaded() / .inject(user_message, revit_version, frame) /
.shadow_log(record).
"""
from __future__ import annotations

from .adapter import WikiRouter, get_wiki_router

__all__ = ["WikiRouter", "get_wiki_router"]
