"""KIR as an MCP server: the language of buildings, presented to any host.

Stage 1 — OFFLINE: no Revit, no license, no product. Five doors:
`kir_author` (python → IR operations), `kir_spec` (an op's contract),
`kir_compile` (C# by version), `kir_rehearse` (what will NOT be checked),
`kir_preview` (an SVG floor plan).

    pip install "kir-building[mcp]"
    python -m kir.mcp

The surface (`surface.py`) does not depend on the protocol SDK in a single
line: it is a fact of this tree, and the gate judges it without `mcp`
installed.
"""
from kir.mcp import surface

__all__ = ["surface"]
