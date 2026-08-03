"""Knowledge-routing namespace.

The production path is :mod:`kukai.rag.wiki_router` and must stay import-cheap.
Legacy vector-index exports remain lazy for offline audit utilities only; merely
importing this package or the Wiki router never imports embedding/RAG modules.
"""
from __future__ import annotations

from typing import Any


_LEGACY_EXPORTS = frozenset({"RevitApiIndex", "ApiEntry", "RagPromptEnricher"})
__all__: list[str] = []


def __getattr__(name: str) -> Any:
    if name in {"RevitApiIndex", "ApiEntry"}:
        from kukai.rag.revit_api_index import ApiEntry, RevitApiIndex

        return {"RevitApiIndex": RevitApiIndex, "ApiEntry": ApiEntry}[name]
    if name == "RagPromptEnricher":
        from kukai.rag.rag_prompt import RagPromptEnricher

        return RagPromptEnricher
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _LEGACY_EXPORTS)
