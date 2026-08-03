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

These constants are a verbatim copy of ``kukai.api.chat_ws._WRAPPER_HEADER`` /
``_WRAPPER_FOOTER``. ``tests/bridge/test_exec_wrapper_sync.py`` reads that file's
source and asserts byte-for-byte equality so the two never drift. When the modeling
framework is folded into the backend proper, chat_ws should import FROM HERE and the
duplication collapses to one definition.
"""
from __future__ import annotations

# Verbatim copy of chat_ws._WRAPPER_HEADER — keep in sync (guarded by sync test).
WRAPPER_HEADER = (
    "using System;\n"
    "using System.Linq;\n"
    "using System.Collections.Generic;\n"
    "using System.Text;\n"
    "using System.Text.RegularExpressions;\n"
    "using Autodesk.Revit.DB;\n"
    "using Autodesk.Revit.DB.Architecture;\n"
    "using Autodesk.Revit.DB.Structure;\n"
    "using Autodesk.Revit.DB.Mechanical;\n"
    "using Autodesk.Revit.DB.Electrical;\n"
    "using Autodesk.Revit.DB.Plumbing;\n"
    "using Autodesk.Revit.UI;\n"
    "\n"
    "namespace Kukai\n"
    "{\n"
    "    public class UserCode\n"
    "    {\n"
    "        public static object Execute(Document doc, UIDocument uidoc)\n"
    "        {\n"
)
WRAPPER_FOOTER = (
    "\n"
    "        }\n"
    "    }\n"
    "}\n"
)

# Number of lines the header occupies. User-code line N appears in the wrapped
# code at line N + WRAPPER_LINE_OFFSET (so wrapped_line - offset == user_line).
WRAPPER_LINE_OFFSET = WRAPPER_HEADER.count("\n")


def wrap_execute(snippet: str) -> str:
    """Wrap a method-body snippet into the canonical Kukai.UserCode.Execute class,
    exactly as the live bridge does before compile/execute."""
    return WRAPPER_HEADER + snippet + WRAPPER_FOOTER


def unwrap_line(wrapped_line: int) -> int:
    """Map a 1-based line number reported against the wrapped code back to the
    user snippet (mirrors chat_ws's offset arithmetic for repair-loop diagnostics)."""
    return wrapped_line - WRAPPER_LINE_OFFSET
