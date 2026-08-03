"""Document identity uses the one safe C# literal authority."""
from __future__ import annotations

from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.document_guard import (
    bind_read_to_document,
    document_mismatch_expr,
    document_refusal_cs,
)


def _nasty_document() -> DocumentFingerprint:
    return DocumentFingerprint(
        title='COPY\u2028"title',
        path_name='C:\\models\\line\nnext.rvt',
        project_uid="uid-'\\value",
    )


def test_document_guard_escapes_every_csharp_line_terminator_and_quote():
    expression = document_mismatch_expr(_nasty_document())
    assert "\u2028" not in expression
    assert "\\u2028" in expression
    assert '\\"title' in expression
    assert "line\\nnext" in expression
    assert "StringComparison.Ordinal" in expression


def test_read_and_transaction_guards_share_the_same_refusal():
    document = _nasty_document()
    read = bind_read_to_document("return 1;", document)
    write = document_refusal_cs(document, rollback="tx.RollBack(); ")
    assert document.digest in read
    assert document.digest in write
    assert "tx.RollBack(); return" in write
