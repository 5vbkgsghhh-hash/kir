"""WIRE GATE: the door is checked by a REAL client, not a function call.

🔴 WHY IT WAS SET UP (03.09.2026). Fifty of the door's instruments call
`server.dispatch` directly — that is, they check the BODY, not the WIRE.
Everything known about the protocol itself (the 2026-07-28 agreement, the
`tools/list` shape, `ttlMs`/`cacheScope`, confirmation via MRTR) was proven by
scripts in a temporary directory that die together with the session.

The difference is not theoretical: a live run on that same day found a defect
that none of the fifty had seen — a reading probe did not even compile, because
the fake transport accepted ANY string. An instrument that checks the route is
blind to the language on the other end.

WHAT THIS FILE DOES NOT DO: it does not go into Revit. The live hand is checked
by the host and a live document; here what is checked is that the door SPEAKS
the protocol.
"""
from __future__ import annotations

import os
import sys

import pytest

pytest.importorskip("mcp_types", reason="дополнение [mcp] не поставлено")
anyio = pytest.importorskip("anyio", reason="дополнение [mcp] не поставлено")

SRC = """
envelope(intent="ворота провода")
L = create_level(elev_mm=0, name="Этаж 1")
create_wall(p0_mm=(0, 0), p1_mm=(8000, 0), level=L, height_mm=3000)
"""


def _drive(work):
    """Bring the door up as a SEPARATE PROCESS and talk to it with the SDK
    client."""
    from mcp import Client, StdioServerParameters

    async def main():
        env = dict(os.environ)
        # 🔴 THE PATH IS TAKEN FROM THE PACKAGE, NOT A LITERAL: the outside
        # person has no tree, but does have an install, and the instrument is
        # required to work for them too.
        import kir
        root = os.path.dirname(os.path.dirname(os.path.abspath(kir.__file__)))
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "kir.mcp"], env=env)
        async with Client(params) as client:
            return await work(client)

    return anyio.run(main)


def test_the_protocol_and_the_tool_list_are_what_we_claim():
    async def work(c):
        listed = await c.list_tools()
        return (c.protocol_version, [t.name for t in listed.tools],
                listed.ttl_ms, listed.cache_scope, listed.result_type)

    version, names, ttl, scope, kind = _drive(work)
    assert version == "2026-07-28", "дверь согласовала не ту ревизию протокола"
    assert names == ["kir_author", "kir_spec", "kir_compile", "kir_rehearse",
                     "kir_open", "kir_write", "kir_preview"]
    # The listing cache is a SEP-2549 requirement, not a convenience: without it
    # the client re-requests 65 KB of schema on every turn.
    assert ttl and ttl > 0 and scope == "public"
    assert kind == "complete"


def test_a_refusal_travels_as_a_normal_result_not_as_an_error():
    """🔴 A LAW CARRIED OVER FROM `serving.py` AND CHECKED ONLY HERE.

    A typed refusal TEACHES the next move; `isError` says "the tool broke" and
    cuts reasoning off. This difference cannot be seen through `dispatch`: it is
    born at the translation into the protocol's result.
    """
    async def work(c):
        return await c.call_tool("kir_author", {"program_py": "нет_такого_опа(1)"})

    res = _drive(work)
    assert res.is_error is False, "отказ уехал как поломка инструмента"
    body = res.structured_content
    assert body["ok"] is False and body["wrote_nothing"] is True
    assert body["err"]["code"].startswith("KIR-"), "код отказа не из реестра"


def test_the_offline_chain_builds_a_house_over_the_wire():
    async def work(c):
        authored = await c.call_tool("kir_author", {"program_py": SRC})
        program = authored.structured_content["program"]
        compiled = await c.call_tool("kir_compile", {"program": program})
        return compiled.structured_content

    body = _drive(work)
    asked = body["versions"]["asked"]
    assert body["versions"]["score"] == f"{len(asked)}/{len(asked)}"


def test_the_app_resource_is_reachable_over_the_wire():
    """The tool's reference and the served document are checked against each
    other THROUGH THE PROTOCOL.

    In the tree, the same thing is checked by two carriers (`surface` against
    `served_resources`); here, by what the host can actually fetch.
    """
    from kir.mcp import app

    async def work(c):
        tools = (await c.list_tools()).tools
        prev = next(t for t in tools if t.name == "kir_preview")
        uri = ((prev.meta or {}).get("ui") or {}).get("resourceUri")
        listed = [str(r.uri) for r in (await c.list_resources()).resources]
        doc = await c.read_resource(uri) if uri else None
        return uri, listed, doc

    uri, listed, doc = _drive(work)
    assert uri == app.APP_URI and uri in listed
    assert doc.contents[0].mime_type == app.APP_MIME_TYPE
    assert "ui/initialize" in doc.contents[0].text
