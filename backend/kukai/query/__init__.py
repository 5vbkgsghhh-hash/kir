"""Declarative model-query layer (query_model tool, G3).

Turns a JSON spec into ONE verified, version-safe read-only C# template so the
LLM never writes ad-hoc discovery C# (the #1 source of compile errors / repair
rounds — see audit 2026-06-06). Mirrors the kukai.write declarative path.
"""
