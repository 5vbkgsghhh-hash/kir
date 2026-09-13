"""THE MCP SURFACE GATE. Every check was bought by a defect of this same
shift (02.09.2026).

The instrument deliberately does not bring up the server and does not
require `mcp` to be installed: the surface is a fact of THIS tree, and it
must be judged by whoever installed KIR, not by whoever delivered the
extra.
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from kir.mcp import surface

#: 🔴 A RATCHET CEILING, AND IT IS NOT HYGIENE. The first build of the
#: surface came out at 1,284,912 bytes: the program schema went out in
#: THREE copies — at `kir_compile`, `kir_rehearse`, and `kir_preview`.
#: Taken separately, each door looked correct, and the defect would have
#: slipped through silently. Then it stood at 65,329 B — one copy, at
#: `kir_compile`.
#:
#: 🔴 LOWERED 13.09.2026 TO 25,000, MEASURED 13,204. The one remaining
#: copy was itself the surface: of 437,934 B of flat program schema,
#: `ops` was 431,095 B — every slot of every op, in a listing paid for on
#: every cold start. It moved to `kir_spec`, which exists for exactly that
#: question (`surface._program_outline`). The ratchet only ever goes DOWN;
#: raising it back means the per-op detail came back into the listing,
#: and that is the thing to catch.
SURFACE_MAX_BYTES = 25_000


def _surface_json() -> str:
    return json.dumps(surface.tools(), ensure_ascii=False, sort_keys=True)


def test_two_listings_are_byte_identical():
    """The 2026-07-28 spec asks for a deterministic order for the sake of
    the client's cache.

    Nondeterminism here breaks nothing visible — it silently misses the
    cache for EVERY client. This tree has already paid for exactly this
    kind of defect with the obfuscator: five obfuscations of one text gave
    five different sources, Revit could not cache the build, and the K3
    transfer degraded 3 s -> 16 -> 126 -> 250 -> refusal.
    """
    assert _surface_json() == _surface_json()


def test_order_is_fixed():
    assert surface.names() == (
        "kir_author", "kir_spec", "kir_compile", "kir_rehearse",
        "kir_open", "kir_write", "kir_preview")


def test_surface_fits_under_the_ratchet():
    size = len(_surface_json())
    assert size <= SURFACE_MAX_BYTES, (
        f"поверхность {size} Б превысила храповик {SURFACE_MAX_BYTES} Б — "
        f"проверь, не уехала ли схема программы второй копией")


def test_every_tool_is_wired_to_a_door():
    """A name the dispatcher does not have is a promise the runtime will reject."""
    from kir.mcp import server
    assert set(surface.names()) == set(server._DOORS)


#: Where to look for the door's body. TWO modules, not one: the live half
#: lives in its own file, and an instrument that only knows `server.py`
#: would silently stop checking exactly the doors that write into the
#: model.
def _door_modules() -> list[str]:
    from kir.mcp import live, server
    return [server.__file__, live.__file__]


def _door_reads(fn_name: str) -> set[str]:
    """What `args` fields the door reads — by PARSING, not by reading line
    numbers.

    An instrument keyed on line numbers would lie at the very first edit
    of the file (this tree already has 80 files with that ailment). An
    AST survives both an edit and a function's relocation.

    🔴 WHAT THIS INSTRUMENT DOES NOT SEE, AND THIS IS NAMED, NOT PASSED
    OVER IN SILENCE: an `args.get(...)` reference pulled out into a
    HELPER. On 02.09.2026 there was such a helper here (`_programs_of`),
    and the `program` field never entered its field of view — the
    instrument showed green, having checked nothing about it. The helper
    is removed, all references are direct. The check is ONE-SIDED
    (`read <= declared`): an unread reference gives a false GREEN; there
    is no such thing as a false red.
    """
    fn = None
    for path in _door_modules():
        tree = ast.parse(pathlib.Path(path).read_text("utf-8"))
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == fn_name), None)
        if fn is not None:
            break
    assert fn is not None, f"двери «{fn_name}» нет ни в одном модуле двери"
    seen: set[str] = set()
    for node in ast.walk(fn):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "args"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            seen.add(node.args[0].value)
    return seen


def server_module_path() -> str:
    from kir.mcp import server
    return server.__file__


@pytest.mark.parametrize("tool_name,door", [
    ("kir_author", "_author"),
    ("kir_spec", "_spec"),
    ("kir_compile", "_compile"),
    ("kir_rehearse", "_rehearse"),
    ("kir_preview", "_preview"),
    ("kir_open", "open_building"),
    ("kir_write", "write_program"),
])
def test_a_door_reads_only_what_its_schema_declares(tool_name, door):
    """🔴 BOUGHT BY A DEFECT ON 02.09.2026, AND IT WOULD HAVE BEEN
    INVISIBLE IN PYTHON TESTS.

    `_compile` read `args.get("out_dir")`, but the schema never declared
    this field — with `additionalProperties: false` the client would have
    rejected the call BEFORE the door. The instrument compares two sets:
    what the door reads and what the schema promises.
    """
    tool = next(t for t in surface.tools() if t["name"] == tool_name)
    declared = set(tool["input_schema"].get("properties") or {})
    read = _door_reads(door)
    assert read <= declared, (
        f"{tool_name}: дверь читает поля, которых схема не объявляет: "
        f"{sorted(read - declared)}")


def test_required_fields_are_declared_properties():
    for tool in surface.tools():
        schema = tool["input_schema"]
        props = set(schema.get("properties") or {})
        req = set(schema.get("required") or ())
        assert req <= props, f"{tool['name']}: required вне properties: {req - props}"


def test_the_prose_is_not_copied_into_every_tool():
    """Prose about the language lives in the server's `instructions`,
    rather than in five copies.

    Measured: 29,944 B of description; a copy at each of the five doors
    would cost 149,720 B for one `tools/list`.
    """
    prose = surface.instructions()
    assert len(prose) > 10_000, "описание из реестра внезапно пусто"
    for tool in surface.tools():
        assert prose not in tool["description"]
