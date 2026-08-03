"""One KIR authority for binding generated Revit code to a document.

Document identity is a correctness boundary shared by regular authoring,
independent acceptance, and A5 recovery. Keeping the generated comparison in
one low-level module prevents those paths from acquiring different definitions
of "the same open model".

This module is deliberately pure: it formats C# and has no bridge, filesystem,
or orchestration dependencies.
"""
from __future__ import annotations

from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.emit_utils import cs_string_literal


DOCUMENT_PROBE_CS = r"""
var __fp = new Dictionary<string, object>();
try { __fp["title"] = doc.Title ?? ""; } catch { __fp["title"] = ""; }
try { __fp["path_name"] = doc.PathName ?? ""; } catch { __fp["path_name"] = ""; }
try
{
    __fp["project_uid"] = doc.ProjectInformation == null
        ? "" : (doc.ProjectInformation.UniqueId ?? "");
}
catch { __fp["project_uid"] = ""; }
return __fp;
""".strip()


def document_mismatch_expr(fingerprint: DocumentFingerprint) -> str:
    """Return the exact ordinal C# predicate for a document switch."""

    if not isinstance(fingerprint, DocumentFingerprint):
        raise TypeError("document guard requires DocumentFingerprint")
    guard = fingerprint.compiler_guard()
    return (
        f"!String.Equals(doc.Title ?? \"\", "
        f"{cs_string_literal(guard['title'])}, "
        "StringComparison.Ordinal) || "
        f"!String.Equals(doc.PathName ?? \"\", "
        f"{cs_string_literal(guard['path_name'])}, "
        "StringComparison.Ordinal) || "
        "!String.Equals(doc.ProjectInformation == null ? \"\" : "
        "(doc.ProjectInformation.UniqueId ?? \"\"), "
        f"{cs_string_literal(guard['project_uid'])}, "
        "StringComparison.Ordinal)")


def document_refusal_cs(
    fingerprint: DocumentFingerprint,
    *,
    rollback: str = "",
) -> str:
    """Return a typed early-return guard, optionally rolling back first."""

    if not isinstance(rollback, str):
        raise TypeError("document guard rollback fragment must be a string")
    return (
        f"if ({document_mismatch_expr(fingerprint)})\n"
        "{\n"
        f"    {rollback}return new Dictionary<string, object> {{"
        " {\"error\", \"document_mismatch\"},"
        f" {{\"expected_fingerprint\", "
        f"{cs_string_literal(fingerprint.digest)}}} }};\n"
        "}\n")


def bind_read_to_document(
    code: str,
    fingerprint: DocumentFingerprint,
) -> str:
    """Prepend the identity guard to one read-only generated program."""

    if not isinstance(code, str) or not code:
        raise TypeError("document-bound read code must be non-empty")
    return document_refusal_cs(fingerprint) + code


# Historical serving/A5 seams. New code imports the public names above.
_DOCUMENT_PROBE_CS = DOCUMENT_PROBE_CS
_TITLE_PROBE_CS = DOCUMENT_PROBE_CS
_document_mismatch_expr = document_mismatch_expr
_document_refusal_cs = document_refusal_cs
_bind_read_to_document = bind_read_to_document


__all__ = [
    "DOCUMENT_PROBE_CS",
    "bind_read_to_document",
    "document_mismatch_expr",
    "document_refusal_cs",
]
