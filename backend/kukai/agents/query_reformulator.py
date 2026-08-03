"""QueryReformulator — Russian (or English) Revit query → one-line English search prompt.

Runs in the pre-flight parallel stage (alongside IntentClassifier and RagReranker).
The output is plain English text — NOT JSON — with canonical Revit API class
names embedded for downstream RAG retrieval (BM25 + semantic search against
the API class catalog).

Why this exists: the production RAG corpus is in English, and BM25 only fires
on exact token matches. A naive Russian query ("создай стену") never hits the
"Wall" / "Wall.Create" tokens that point to the right recipes. This agent
rewrites the query into English with the canonical class names spelled out
so BM25 can lock onto them.

Output contract (see prompts/query_reformulator.md):
  A single non-empty line of English text. No JSON, no markdown, no quotes.
"""
from __future__ import annotations

from .base import AgentBase


_QUERY_MAX_CHARS = 800
_OUTPUT_MAX_CHARS = 600

# Surrounding-quote characters that the model occasionally wraps the answer in.
# We strip these from both ends. Includes ASCII ' " ` plus common Unicode
# curly quotes and guillemets.
_QUOTE_CHARS = ''.join((
    '"', "'", "`",
    "‘", "’",  # single curly quotes ' '
    "“", "”",  # double curly quotes " "
    "„", "‟",  # German-style low/high double quotes „ ‟
    "‚", "‛",  # German-style low/high single quotes ‚ ‛
    "«", "»",  # guillemets « »
    "‹", "›",  # single guillemets ‹ ›
))


class QueryReformulator(AgentBase):
    """Translate a Revit query into one English line of search text."""

    name = "query_reformulator"
    model = "gemini-3.5-flash"
    thinking_level = "medium"
    max_tokens = 64000  # no cap per Token budget policy
    timeout_s = 6.0     # pre-flight stage; fast
    prompt_file = "query_reformulator"

    def build_user_message(self, query: str) -> str:
        """Pass through the (trimmed) raw query — the prompt has all the structure."""
        return (query or "")[:_QUERY_MAX_CHARS].strip()

    def parse_response(self, text: str) -> str:
        """Return ONE clean line of English text.

        Steps:
          1. Strip outer whitespace.
          2. Take the first non-empty line (model may emit multiple).
          3. Strip surrounding quote characters (ASCII + Unicode curly/guillemet).
          4. Strip whitespace again.
          5. Cap length at _OUTPUT_MAX_CHARS.
          6. Raise ValueError if the result is empty.
        """
        if text is None:
            raise ValueError("response is None")

        # 1+2: take first non-empty line
        first_line = ""
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped:
                first_line = stripped
                break

        if not first_line:
            # Maybe the model returned a single line without trailing newline
            # that was all whitespace — already handled. If we got here the
            # entire response is empty / whitespace-only.
            raise ValueError("empty response")

        # 3: strip surrounding quote characters (potentially nested, e.g. "'x'")
        cleaned = first_line
        while len(cleaned) >= 2 and cleaned[0] in _QUOTE_CHARS and cleaned[-1] in _QUOTE_CHARS:
            cleaned = cleaned[1:-1].strip()
            if not cleaned:
                break

        # 4: final whitespace strip
        cleaned = cleaned.strip()

        if not cleaned:
            raise ValueError("empty response after quote/whitespace strip")

        # 5: defensive cap (output should be short already)
        if len(cleaned) > _OUTPUT_MAX_CHARS:
            cleaned = cleaned[:_OUTPUT_MAX_CHARS].rstrip()

        return cleaned
