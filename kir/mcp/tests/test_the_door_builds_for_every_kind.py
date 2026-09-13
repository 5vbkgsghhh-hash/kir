"""THE DOOR BUILDS — the two calls H measured as broken on HEAD on 13.09.2026.

A new parameter kind (`identity`, fc6ef65) passed the registry and the compiler and
dropped `surface.tools()` with «unknown param kind identity» in `kir/schema_gen.py`.
The class is locked on the language side
(`kir/tests/test_the_schema_knows_every_kind_the_registry_names.py`); this file is the
door-side half, kept HERE because it imports the door and the language's tests may not
(`test_the_language_never_mentions_the_door`).
"""
from __future__ import annotations


def test_the_door_itself_builds():
    from kir import schema_transport
    from kir.mcp import surface

    assert surface.tools(), "the palette must not be empty"
    schema, _digest = schema_transport.program_schema_for_tool()
    assert schema
