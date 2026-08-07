"""Byte contract for the C# compilation unit executed by the Revit bridge.

KIR emits an ``Execute`` method body.  Roslyn and the bridge consume a full
``Kukai.UserCode`` source file, so this module owns the one deterministic
body-to-compilation-unit transformation used by provenance-aware paths.

Keep this module dependency-free: compiler contracts, the LLM pipeline and the
bridge protocol all sit above it.
"""
from __future__ import annotations


EXECUTE_WRAPPER_CONTRACT = "kukai-revit-execute-wrapper/1"

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
WRAPPER_LINE_OFFSET = WRAPPER_HEADER.count("\n")


def wrap_execute_body(source: str) -> str:
    """Return the exact UTF-8 text compiled and executed for one method body."""

    if not isinstance(source, str):
        raise TypeError("execute body must be a string")
    indented = "\n".join(
        "            " + line if line.strip() else line
        for line in source.split("\n")
    )
    return WRAPPER_HEADER + indented + WRAPPER_FOOTER


def unwrap_execute_body(compilation_unit: str) -> str:
    """Recover a body only when ``compilation_unit`` is canonical byte-for-byte.

    This is intentionally stricter than a C# parser.  A semantically equivalent
    wrapper is a different compile unit and therefore cannot satisfy a receipt
    produced for this wrapper contract.
    """

    if not isinstance(compilation_unit, str):
        raise TypeError("compilation unit must be a string")
    if (
        not compilation_unit.startswith(WRAPPER_HEADER)
        or not compilation_unit.endswith(WRAPPER_FOOTER)
    ):
        raise ValueError("compilation unit has a non-canonical wrapper")

    indented = compilation_unit[
        len(WRAPPER_HEADER):len(compilation_unit) - len(WRAPPER_FOOTER)
    ]
    lines: list[str] = []
    prefix = " " * 12
    for line in indented.split("\n"):
        if line.strip():
            if not line.startswith(prefix):
                raise ValueError(
                    "non-empty execute-body line lacks canonical indentation")
            line = line[len(prefix):]
        lines.append(line)
    source = "\n".join(lines)
    if wrap_execute_body(source) != compilation_unit:
        raise ValueError("compilation unit is not a canonical wrapper image")
    return source


__all__ = [
    "EXECUTE_WRAPPER_CONTRACT",
    "WRAPPER_FOOTER",
    "WRAPPER_HEADER",
    "WRAPPER_LINE_OFFSET",
    "unwrap_execute_body",
    "wrap_execute_body",
]
