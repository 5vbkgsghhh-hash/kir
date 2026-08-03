"""Server-side Code-CAD geometry generation.

Bridges Gemini's "make a complex shape" intent to native Revit DirectShape
by executing user-written CadQuery code in a sandboxed subprocess, parsing
the resulting STL mesh, and emitting C# that builds a Revit
TessellatedShape → DirectShape inside the active family document.

This is KUKI's "any-complexity" path — complementary to the V3 primitive
toolkit (parametric box/cylinder/sweep/blend/revolve). Gemini picks per
task:
    - parametric chair/cabinet/door → V3 primitives + labeled dims
    - Rolls-Royce body / ornament / freeform sculpture → CadQuery

The mesh that comes back is geometry-only — no parametric flex. The
final-phase `inspect_family + parametrize` step still wraps it with
Width/Depth/Height labeled dimensions on the bounding box, so the
imported solid behaves like a real Revit family for placement.

Architecture (Phase 1 — server-side runner shipped):
    Gemini ──┐
             │ CadQuery Python code
             ▼
    `cadquery_runner.run_to_stl(code)` (subprocess, timeout, size cap)
             │
             │ STL bytes
             ▼
    `stl_parser.parse_binary_stl(bytes)` → triangles
             │
             ▼
    `family_codecad.family_generate_complex` tool handler
             │ generates C# with inline triangles + TessellatedShape
             ▼
    Bridge `execute` → Roslyn compile → Revit
             │
             ▼
    DirectShape in family document
"""
