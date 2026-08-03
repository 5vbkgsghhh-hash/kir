"""Versioned, deterministic knowledge layer used by the live Revit path.

Offline historical benchmarks may still import archived retrieval modules.
The production knowledge contract lives here: one immutable release containing
the Wiki pages, routing index, Revit API surfaces and extension catalogue.
"""

from .mode import KnowledgeMode, knowledge_mode
from .release import KnowledgeRelease, KnowledgeReleaseError, current_release

__all__ = [
    "KnowledgeMode",
    "KnowledgeRelease",
    "KnowledgeReleaseError",
    "current_release",
    "knowledge_mode",
]
