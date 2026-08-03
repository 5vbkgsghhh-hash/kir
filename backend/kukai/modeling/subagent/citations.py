"""Inline `// RAG:#snippet_id` citation extraction and validation.

Per spec Section 11 + audit reversal: every non-trivial API call in
Subagent-generated C# must carry an inline `// RAG:#id` comment that
references a snippet from the retrieved set. The `rag_citations` field
must mirror those inline marks. This validation runs at proposal acceptance.
"""
from __future__ import annotations
import re
from collections.abc import Iterable

from kukai.modeling.schemas.llm import InlineRagCitation


class CitationValidationError(ValueError):
    """RAG citation validation failure."""


# Spec: //{any whitespace}RAG{any whitespace}:{any whitespace}#{any whitespace}<id>
# id is non-whitespace and not '*' (to avoid block-comment confusion)
_INLINE_PATTERN = re.compile(r"//\s*RAG\s*:\s*#\s*([^\s\*]+)")

# Same shape, but captures the WHOLE citation token (not just the id) so we can
# terminate it with a newline.
_CITATION_TOKEN = re.compile(r"(//\s*RAG\s*:\s*#\s*[^\s\*]+)")


def extract_inline_citation_ids(code: str) -> list[str]:
    """Return all snippet_ids referenced inline, preserving order and duplicates."""
    return _INLINE_PATTERN.findall(code)


def normalize_inline_citations(code: str) -> str:
    """Terminate every inline `// RAG:#id` citation with a newline.

    A `//` comment in C# runs to the end of the LINE. When the model emits the
    whole method body on a SINGLE physical line (which DeepSeek sometimes does in
    JSON mode), the first `// RAG:#id` comment swallows ALL the code that follows
    it — the element-creation call, the Transaction commit, the `__result__`
    append — producing code that neither compiles nor satisfies the invariants.

    Inserting a newline immediately after the citation id is always semantically
    safe: the citation comment is only ever the `// RAG:#id` token itself, so the
    code that followed it on the same line was never meant to be commented out.
    Idempotent in effect on already-multi-line code (just adds a blank line)."""
    return _CITATION_TOKEN.sub(r"\1\n", code)


def validate_citations(
    code: str,
    cited: Iterable[InlineRagCitation],
    retrieved_snippet_ids: set[str],
) -> None:
    """Verify proposal's inline + declared citations match retrieved set.

    Raises CitationValidationError on any of:
    - no inline citations at all
    - inline citation id missing from `cited` list
    - declared id missing inline
    - declared id not in retrieved snippet set
    """
    inline_ids = extract_inline_citation_ids(code)
    if not inline_ids:
        raise CitationValidationError(
            "no inline citation found in csharp_code; "
            "every non-trivial API call must carry // RAG:#snippet_id"
        )
    inline_set = set(inline_ids)
    cited_ids = {c.snippet_id for c in cited}

    extras_inline = inline_set - cited_ids
    if extras_inline:
        raise CitationValidationError(
            f"inline not in rag_citations: {sorted(extras_inline)}"
        )

    extras_declared = cited_ids - inline_set
    if extras_declared:
        raise CitationValidationError(
            f"rag_citations has id not present inline: {sorted(extras_declared)}"
        )

    not_retrieved = cited_ids - retrieved_snippet_ids
    if not_retrieved:
        raise CitationValidationError(
            f"cited snippet id not in retrieved set: {sorted(not_retrieved)}"
        )
