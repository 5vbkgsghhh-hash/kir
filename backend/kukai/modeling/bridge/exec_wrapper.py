"""Canonical C# exec wrapper — the SINGLE source of truth for how a user-code
snippet is wrapped into the ``Kukai.UserCode.Execute(Document, UIDocument)`` class
before it is compiled/run by the live bridge.

WHY THIS EXISTS (critic M-1, made real):
The live exec path (backend ``_bridge_callback`` for method "execute", which the
``/admin/remote/exec`` channel also uses) wraps the snippet with HEADER/FOOTER and
then the bridge compiles+runs it — ``doc``/``uidoc`` are in scope, usings are
present. The standalone compile-service (port 52412), by contrast, compiles the
code *exactly as given* (``ParseText`` + ``OutputKind.Dll``) — it does NOT inject
``doc`` or usings and forbids top-level statements. So to make L3 (compile gate)
validate EXACTLY what L4 (execute) runs, the compile gate must apply this identical
wrapper itself.

The constants are aliases of :mod:`kukai.compiler_unit`, which also owns the
provenance-aware KIR compile-unit transform.  ``wrap_execute`` intentionally
retains its legacy concatenation semantics because its callers pass an already
indented epilogue body.
"""
from __future__ import annotations

from kukai.compiler_unit import (
    WRAPPER_FOOTER,
    WRAPPER_HEADER,
    WRAPPER_LINE_OFFSET,
)


def wrap_execute(snippet: str) -> str:
    """Wrap a method-body snippet into the canonical Kukai.UserCode.Execute class,
    exactly as the live bridge does before compile/execute."""
    return WRAPPER_HEADER + snippet + WRAPPER_FOOTER


def unwrap_line(wrapped_line: int) -> int:
    """Map a 1-based line number reported against the wrapped code back to the
    user snippet (mirrors chat_ws's offset arithmetic for repair-loop diagnostics)."""
    return wrapped_line - WRAPPER_LINE_OFFSET
