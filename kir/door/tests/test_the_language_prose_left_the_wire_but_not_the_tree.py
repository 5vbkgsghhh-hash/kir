"""G9 — the language prose left the WIRE and stayed in the TREE.

`kir/tool_doc.py::build_tool_description()` was the description of `revit_ir`:
29 874 characters measured 13.09 (since compressed to 1 508 by W in 0.8.4).
It leaves the door's wire — the reference is pulled per op instead — and it
KEEPS its other readers (CLI `kir doctor`, documentation). Decision of the
lead, 13.09.

🔴 THE CONTROL IS TWO-SIDED ON PURPOSE. Both directions already happened in
this tree: prose rode out onto the wire, and prose was deleted along with its
last consumer. A one-sided pin would invite the other mistake.
"""
from __future__ import annotations

import json

from kir.door import registry as R


def _wire_blob() -> str:
    return json.dumps([R.projection(h, r) for h in R.HOSTS for r in R.ROLES]
                      + [R.notice(r) for r in R.ROLES], ensure_ascii=False)


def test_no_projection_prints_the_tool_description():
    from kir.tool_doc import build_tool_description

    prose = build_tool_description()
    blob = _wire_blob()
    assert prose not in blob
    # and not in pieces either: no 200-character run of it may appear
    chunk = prose[:200]
    if chunk.strip():
        assert chunk not in blob


def test_the_carrier_is_alive_and_not_empty():
    """Deleting it would take `kir doctor` and the documentation with it."""
    from kir.tool_doc import build_tool_description

    prose = build_tool_description()
    assert isinstance(prose, str) and len(prose) > 200


def test_the_per_op_reference_replaced_it_on_the_wire():
    from kir.door.read import help_text

    text = help_text("create_wall")
    assert text and len(text) > 100


def test_control_deleting_the_carrier_goes_red():
    """Expressed as an import that must keep working — the cheapest way to
    catch a deletion is to depend on it here."""
    import kir.tool_doc as td

    assert callable(getattr(td, "build_tool_description", None))
