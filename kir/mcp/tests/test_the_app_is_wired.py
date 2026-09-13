"""STAGE 3 GATE: the MCP app is tied to the tool and to nothing external.

Every instrument here guards a defect that has ALREADY happened somewhere
else in this tree — so the list is short and free of "just in case."
"""
from __future__ import annotations

import asyncio
import json
import re

import pytest

from kir.mcp import app, server, surface

def _program() -> dict:
    """The program is assembled by the AUTHOR'S CONSTRUCTOR, not by
    hand-written JSON.

    🔴 BOUGHT RIGHT HERE, 02.09.2026: a hand-written fixture with
    `level={"by":"ref"}` gave a census of six considered and ZERO sheets —
    the instrument reddened, and it was right. A selector's shape is
    knowledge of the registry, and copying it from memory into a test
    means testing one's own memory, not the door.
    """
    from kir import sdk

    program = sdk.program(intent="коробка 8x5 для ворот приложения")
    level = program.add(sdk.create_level(elev_mm=0, name="Этаж 1"))
    pts = [(0, 0), (8000, 0), (8000, 5000), (0, 5000)]
    for i in range(4):
        program.add(sdk.create_wall(p0_mm=pts[i], p1_mm=pts[(i + 1) % 4],
                                    level=level, height_mm=3000))
    return program.to_dict()


PROGRAM = _program()


def _preview_tool() -> dict:
    return next(t for t in surface.tools() if t["name"] == "kir_preview")


def test_the_tool_points_at_the_document_we_actually_serve():
    """🔴 A CLOSED LOOP, NOT TWO MATCHING LITERALS.

    The same kind of defect as `out_dir` on 02.09.2026: one half promised,
    the other did not know. Here the tool REFERENCES `ui://`, and the
    server is the one that SERVES that `ui://`; they have nothing to drift
    apart by, only if they are cross-checked.
    """
    uri = _preview_tool()["meta"]["ui"]["resourceUri"]
    served = {r["uri"] for r in server.served_resources()}
    assert uri in served, (
        f"инструмент ссылается на {uri}, а дверь отдаёт {sorted(served)}")
    assert uri.startswith("ui://"), "хост отличает документ приложения по схеме"
    body = next(r for r in server.served_resources() if r["uri"] == uri)
    assert body["mime_type"] == app.APP_MIME_TYPE and body["text"].strip()


def test_our_mime_and_extension_id_match_the_sdk():
    """TWO CARRIERS OF ONE VALUE WOULD DRIFT APART SILENTLY.

    Our literals are our own by the boundary's law (the SDK lives in one
    file of the door), and precisely for that reason it is an instrument,
    not courtesy, that must cross-check them.
    """
    # 🔴 THE ABSENCE OF AN INSTRUMENT IS A CATEGORY THAT MUST NOT BE
    # CONFUSED WITH A FINDING (02.09.2026, named by a neighboring session
    # from a full run). The `[mcp]` extra is OPTIONAL, and a stranger may
    # legitimately not have it — exactly as it was absent from the prod
    # venv. A red here would mean "found a discrepancy," though all that
    # was found was the SDK's absence. A skip NAMES what is missing; a red
    # lies about the subject.
    pytest.importorskip(
        "mcp.server.apps",
        reason="дополнение [mcp] не поставлено: сверять литералы не с чем")
    from mcp.server.apps import APP_MIME_TYPE, EXTENSION_ID
    assert app.APP_MIME_TYPE == APP_MIME_TYPE
    assert app.UI_EXTENSION_ID == EXTENSION_ID


def test_the_document_asks_for_nothing_outside_itself():
    """The host's CSP will silently fail to load anything external — so there must be nothing external."""
    html = app.HTML
    for pattern in (r'src\s*=\s*["\']https?://', r'href\s*=\s*["\']https?://',
                    r"<link\b", r"@import\b", r"\bfetch\s*\(", r"XMLHttpRequest"):
        assert not re.search(pattern, html, re.I), f"документ тянется наружу: {pattern}"


def test_the_document_speaks_the_ext_apps_handshake():
    html = app.HTML
    for method in ("ui/initialize", "ui/notifications/initialized",
                   "ui/notifications/tool-result"):
        assert method in html, f"в документе нет {method}"


def test_the_census_reaches_a_client_without_the_app():
    """🔴 DEGRADATION IS A PROPERTY OF THE RESPONSE, NOT A HOPE (SEP-2133).

    Before 02.09.2026 the census lived ONLY inside the SVG's
    `<metadata>`: a text-only client got a huge string of drawing and not
    one word about what is not on it. Law #4 must reach through both
    channels.
    """
    body, crashed = asyncio.run(server.dispatch("kir_preview", {"program": PROGRAM}))
    assert not crashed and body["ok"]
    census = body["census"]
    assert census["considered"] > 0
    assert census["considered"] == census["drawn"] + census["omitted_total"], (
        "ЗАКОН №4: рассмотренное обязано раскладываться на нарисованное плюс "
        "названные причины")
    assert body["sheets"] and "census" in body["sheets"][0]
    assert body["assertion"] == "self_reported", (
        "план из ПРОГРАММЫ — самопроверка; сила утверждения обязана быть видна")


def test_the_drawing_is_byte_identical_twice():
    """Stage 3 gate. A nondeterministic drawing breaks both the cache and the
    "before/after" comparison, and any hash built on top of the receipt."""
    first, _ = asyncio.run(server.dispatch("kir_preview", {"program": PROGRAM}))
    second, _ = asyncio.run(server.dispatch("kir_preview", {"program": PROGRAM}))
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_wire_serves_exactly_one_resource_and_it_is_the_app():
    """The wire is assembled for real: the SDK server, not our own representations."""
    # 🔴 GUARD ON `mcp_types`, NOT ON `mcp` (03.09.2026, full run).
    # `importorskip("mcp")` PASSED where the SDK was absent: the name `mcp` was
    # taken by our own `kir/mcp`, as soon as the `kir/` directory landed on sys.path.
    # A presence guard fooled by its own package is not a guard.
    # `mcp_types` is a separate SDK distribution and never collides with us.
    pytest.importorskip("mcp_types", reason="дополнение [mcp] не поставлено")
    built = server.build_server()
    assert built.extensions == {app.UI_EXTENSION_ID: {}}
    assert "resources/read" in built._request_handlers
    assert "resources/list" in built._request_handlers
