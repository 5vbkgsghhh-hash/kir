"""Subagent layer — LLM-driven code generation for individual elements."""
from kukai.modeling.subagent.citations import (
    CitationValidationError,
    extract_inline_citation_ids,
    validate_citations,
)
from kukai.modeling.subagent.persona import (
    FAILURE_CATALOG_SUMMARY,
    STRUCTURAL_SUBAGENT_PERSONA,
    build_llm_prompt_inputs,
)
from kukai.modeling.subagent.structural import StructuralSubagent

__all__ = [
    "CitationValidationError",
    "extract_inline_citation_ids",
    "validate_citations",
    "STRUCTURAL_SUBAGENT_PERSONA",
    "FAILURE_CATALOG_SUMMARY",
    "build_llm_prompt_inputs",
    "StructuralSubagent",
]
