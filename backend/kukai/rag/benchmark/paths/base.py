"""RAGPath abstract base — every alternative architecture implements this.

A RAGPath is a strategy for turning a user query (and optional bridge context)
into the prompt content the LLM will see, plus optional repair-time context
injected on compile failure.

The benchmark runner treats paths as black boxes: feed query, get prompt;
feed compile error, optionally get extra repair context. This keeps the
runner agnostic to whether the path uses single-shot retrieval, multi-hop
tool-use, structurally extracted corpus, etc.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RAGResult:
    """Output of a path's retrieval/enrichment stage."""

    prompt_text: str
    """The text that gets injected into the system prompt (between code_generation
    and dynamic context). May be empty if the path delivers context via tools."""

    retrieved_ids: list[str] = field(default_factory=list)
    """Stable IDs of corpus entries retrieved. Used by the runner to compute
    Hit@K against the gold-set's expected_snippet_ids."""

    retrieved_apis: list[str] = field(default_factory=list)
    """Names of API classes/methods the path surfaced. Used to compute
    api_coverage against gold's expected_apis."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Path-specific stats: latency, tokens used, etc. Reported in metrics."""


@dataclass
class RepairHint:
    """Output of a path's repair-time enrichment (called on compile fail)."""

    extra_context: str
    """Text to append to the repair prompt — typically a reference snippet
    showing the correct pattern for the failing CS-error."""

    metadata: dict[str, Any] = field(default_factory=dict)


class RAGPath(ABC):
    """Strategy for retrieve-then-enrich. Different paths test different hypotheses."""

    name: str = "base"
    """Stable identifier used in benchmark reports."""

    @abstractmethod
    def enrich(
        self,
        query: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RAGResult:
        """Turn user query into prompt context.

        Args:
            query: User's natural-language Revit task.
            context: Optional bridge context — revit_version, project_name,
                available_walltypes, current_view, selection. Paths may use
                this for version-conditional retrieval, project-aware boost,
                etc.

        Returns:
            RAGResult with prompt_text, retrieved_ids, retrieved_apis, metadata.
        """

    def repair_hint(
        self,
        query: str,
        failed_code: str,
        compile_errors: list[dict[str, Any]],
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[RepairHint]:
        """Optional: produce repair-time context when first attempt fails.

        Default returns None, meaning no special handling — the runner falls
        back to the LLMClient's stock repair prompt.

        Path C (compiler-driven retrieval feedback) overrides this to parse
        CS-error → extract missing API → fetch reference pattern from corpus.
        """
        return None
