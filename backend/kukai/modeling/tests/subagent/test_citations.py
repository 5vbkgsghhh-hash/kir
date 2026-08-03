"""Tests for inline RAG citation extraction + validation."""
from __future__ import annotations
import pytest

from kukai.modeling.schemas.llm import InlineRagCitation
from kukai.modeling.subagent.citations import (
    CitationValidationError,
    extract_inline_citation_ids,
    normalize_inline_citations,
    validate_citations,
)


class TestNormalizeInlineCitations:
    def test_single_line_body_is_recovered(self):
        # The real DeepSeek failure: whole body on one line; the `//` citation
        # would otherwise comment out the column creation + __result__ append.
        code = ('t.Commit(); // RAG:#col1 var col = doc.Create.NewFamilyInstance(p, s, l, '
                'StructuralType.Column); __result__.Add(col.Id);')
        fixed = normalize_inline_citations(code)
        assert "\n" in fixed
        # everything after the citation id is on a fresh line == live code again
        assert "var col = doc.Create.NewFamilyInstance" in fixed.split("// RAG:#col1")[1].lstrip("\n").splitlines()[0]
        assert "__result__.Add(col.Id);" in fixed
        # citation id still extractable
        assert extract_inline_citation_ids(fixed) == ["col1"]

    def test_multiline_code_unaffected_in_meaning(self):
        code = "// RAG:#a\nvar x = 1;\n// RAG:#b\nDoThing();"
        fixed = normalize_inline_citations(code)
        assert extract_inline_citation_ids(fixed) == ["a", "b"]
        assert "var x = 1;" in fixed and "DoThing();" in fixed


class TestExtractInlineCitationIds:
    def test_single_citation(self):
        code = """
        var x = 1;
        // RAG:#rag_42
        NewFamilyInstance(...);
        """
        assert extract_inline_citation_ids(code) == ["rag_42"]

    def test_multiple_citations(self):
        code = """
        // RAG:#a
        x = 1;
        // RAG:#b
        y = 2;
        // RAG:#c
        z = 3;
        """
        assert extract_inline_citation_ids(code) == ["a", "b", "c"]

    def test_duplicates_preserved(self):
        code = "// RAG:#a\nx = 1;\n// RAG:#a\n"
        assert extract_inline_citation_ids(code) == ["a", "a"]

    def test_no_citations(self):
        assert extract_inline_citation_ids("var x = 1;") == []

    def test_whitespace_tolerant(self):
        # Spaces between // and RAG and around # are fine
        code = "  //    RAG:#  rag_99\nfoo();\n"
        assert extract_inline_citation_ids(code) == ["rag_99"]

    def test_complex_ids(self):
        code = "// RAG:#snippet-2024.05.16_revit_columns_v3"
        assert extract_inline_citation_ids(code) == ["snippet-2024.05.16_revit_columns_v3"]


class TestValidateCitations:
    def test_happy_path(self):
        code = "// RAG:#a\n// RAG:#b\n"
        cited = [
            InlineRagCitation(snippet_id="a", api_called="NewFamilyInstance"),
            InlineRagCitation(snippet_id="b", api_called="Activate"),
        ]
        retrieved = {"a", "b", "c"}
        validate_citations(code, cited, retrieved)  # no raise

    def test_inline_missing_from_cited_list(self):
        code = "// RAG:#a\n// RAG:#b\n"
        cited = [InlineRagCitation(snippet_id="a", api_called="X")]
        with pytest.raises(CitationValidationError, match="inline not in rag_citations"):
            validate_citations(code, cited, {"a", "b"})

    def test_cited_not_retrieved(self):
        code = "// RAG:#a\n"
        cited = [InlineRagCitation(snippet_id="a", api_called="X")]
        with pytest.raises(CitationValidationError, match="not in retrieved set"):
            validate_citations(code, cited, retrieved_snippet_ids={"b", "c"})

    def test_no_inline_citations_raises(self):
        code = "var x = 1;"
        with pytest.raises(CitationValidationError, match="no inline citation"):
            validate_citations(code, [], retrieved_snippet_ids={"a"})

    def test_cited_without_inline(self):
        """rag_citations declares 'b' but code only cites 'a' inline."""
        code = "// RAG:#a\n"
        cited = [
            InlineRagCitation(snippet_id="a", api_called="X"),
            InlineRagCitation(snippet_id="b", api_called="Y"),
        ]
        with pytest.raises(CitationValidationError, match="rag_citations has id not present inline"):
            validate_citations(code, cited, retrieved_snippet_ids={"a", "b"})
