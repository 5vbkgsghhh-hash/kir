"""THE DOOR'S BOUNDARY IS KEPT BY A NUMBER, NOT A PROMISE. The subject is `kir/mcp/BOUNDARY.md`.

The owner's word on 02.09.2026: "MCP needs to be separated out into KIR a bit, so it
doesn't confuse us and the project is clearer." A separation held only by
agreement is voided by the very next convenient import; that is why here it is
held by instruments.

🔴 WHY THREE DIFFERENT INSTRUMENTS, NOT ONE. They measure DIFFERENT things, and
each one alone gives a false green:
  * source parsing sees what is written, but not what is ACTUALLY LOADED
    (an import inside a function, `importlib`, a re-export);
  * in-process measurement sees what got loaded, but only along the branches that ran;
  * the closed list sees INTENT and catches growth that both of the first two
    consider legitimate.
The same argument is recorded at the KIR↔KUKAI split gate (`split_gate`): "works
without X" must FIRST prove that X isn't there.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

import pytest

KIR_ROOT = pathlib.Path(__file__).resolve().parents[2]
DOOR = KIR_ROOT / "mcp"

#: 🔴 THE CLOSED LIST: what the door is allowed to call in the language. Taken from
#: parsing on 02.09.2026, not written from memory. Growing it is a DECISION: every new
#: module is a new promise to the outside person that they have it. This is exactly
#: how the stage that "stands offline" would stop being true — silently, without
#: breaking anything.
ALLOWED_KIR_MODULES = frozenset({
    "kir.wire_json",      # pure strict encoding; app/MCP share one post-effect diagnostic law
    "kir.compiler",       # kir_compile: program -> C#
    "kir.ports",          # a live door NAMES its transport, rather than hiding it
    "kir.course",         # kir_spec: the op's contract, the same text as in the sandbox
    "kir.preview",        # kir_preview: floor plan
    "kir.registry_base",  # the list of Revit versions per the authority
    "kir.rehearsal",      # kir_rehearse
    "kir.sandbox",        # kir_author
    # 🔴 THE REGISTRY IS THE AUTHORITY ON AN OP'S KIND. Added 02.09.2026 after review:
    # the confirmation screen counted writing ops via `startswith("create_")` and
    # showed "0 elements" for a program of 500 deletions. The kind is asked of the
    # registry, because the op's name does not carry it.
    "kir.spec",
    # 🔴 WHAT AN OP CANNOT DO — FIVE AXES IN ONE PROJECTION. Added 07.09.2026:
    # `kir_spec` returned the contract ("what the op means") and said nothing about
    # what the surrounding tree can do with it — whether it draws in the plan, whether
    # it rises back up, whether the body gives a clash. Silence reads as "can do
    # everything". This does NOT expand the promise to the outside person:
    # `kir.capability` is a projection, not a sixth table; it has no names of its own,
    # it asks the carriers live, and it arrives at the door as a ready-made dictionary
    # "axis -> reason".
    "kir.capability",
    # 🔴 THE LANGUAGE'S SINGLE DOOR TO THE ENVIRONMENT. Added 02.09.2026, not for
    # convenience: on that day `install_paths` stopped being a SECOND door, and
    # environment reads across the whole package (73 -> 15) moved onto `env.get`. The
    # MCP door reads the environment the same way as everything else — otherwise it
    # would have grown a third way, and "the host's names are read in one place"
    # would stop being true exactly on it. This does NOT expand the promise to the
    # outside person: `kir.env` is a dependency-free submodule, and it already
    # travels everywhere the language travels.
    "kir.env",
    # 🔴 PARSING THE BRIDGE RECEIPT — ONE PARSER FOR THE WHOLE LANGUAGE. Added
    # 04.09.2026 per RT-04: `kir_write` returned `{"ok": True, …, "receipt": receipt}`
    # without reading the receipt in a SINGLE line, and the bridge's substantive
    # refusal (`postconditions_violated`, `stale_or_failed`) rode out as a success.
    # Writing the parsing inside the door itself would mean growing a SECOND failure
    # semantics for the bridge, alongside the one `bridge_result` exists to keep
    # unique (its header: "keeping that parser here prevents either orchestrator from
    # inventing its own failure semantics"). This does not expand the promise to the
    # outside person: the module depends only on `kir.envelope` and
    # `kir.operations.protocol`, and even that lazily.
    "kir.bridge_result",
    "kir.schema_dedup",   # hoisting schema repeats into $defs
    "kir.schema_gen",     # program schema from the registry
    "kir.tool_doc",       # prose about the language -> server instructions
    # 🔴 A TYPED OUTCOME. Added 06.09.2026: the door stopped answering
    # "succeeded / didn't succeed" and names the OUTCOME (`ExecutionState`), because
    # "a response arrived" and "the outcome is known" are different things, and the
    # double write (E6/b2) stood on their conflation. Does not expand the promise to
    # the outside person: `kir.outcome` is enumerations and one dataclass, with no
    # dependencies.
    "kir.outcome",
    # 🔴 `kir.install_paths` STOOD HERE FOR ONE ROUND AND WAS REMOVED THE SAME DAY.
    # The durable record of an unclosed submission (E6) was first addressed via the
    # INSTALLATION authority — and that was wrong twice over: a PyPI install has no
    # root at all (the write door refused the outside person by default), and for a
    # host install, the LANGUAGE's record would have landed in the PRODUCT's tree.
    # Now the directory belongs to the user (`$XDG_DATA_HOME/kir/mcp`), and this
    # module's door does not call it at all. The line was not removed silently: it
    # was removed by the live guard against dead entries in this same file — that
    # guard is itself the proof that the list guards in both directions.
})

#: The protocol SDK lives EXACTLY here. One file, with the import inside the
#: function: otherwise the absence of the `[mcp]` extra would become an import
#: failure for the whole module, and the surface would stop being readable exactly
#: where it needs to be judged.
SDK_HOME = "server.py"

#: DENOMINATORS OF THE TWO SOURCE SWEEPS. The first sweeps the WHOLE package and
#: asks "does the language know about the door"; the second sweeps the files OF
#: THE DOOR ITSELF.
#:
#: 🔴 WHY NUMBERS (measured 02.09.2026). "LANGUAGE -> DOOR = 0" is a claim about a
#: ZERO, and it has exactly two sources: either the language is genuinely clean, or
#: the sweep read nothing. Without a denominator the two are indistinguishable, and
#: the second reads as the first. The same argument by which THREE instruments, not
#: one, are set up in this same file: each one alone gives a false green.
#:
#: Measured 02.09.2026: **967** `*.py` files in the package, **13** at the door, of
#: which **8** are outside `tests`. The floor for the first is set with a large
#: margin (the tree is alive and growing), the floor for the second sits two files
#: below the measurement.
_ФАЙЛОВ_ЯЗЫКА_НЕ_МЕНЬШЕ = 800
_ФАЙЛОВ_ДВЕРИ_НЕ_МЕНЬШЕ = 6


def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py")
                  if "__pycache__" not in p.parts)


def _door_sources() -> list[pathlib.Path]:
    """Files OF THE DOOR ITSELF — instruments excluded.

    🔴 WHY INSTRUMENTS ARE OUT OF THE COUNT, AND THIS IS NOT A CONCESSION. Everything
    measured in this file is a promise to the OUTSIDE PERSON: "installed KIR without
    the extra — the door reads, pulls in nothing extra, asks for no ports." Its
    instruments don't run (there is nothing to run them with), and the instrument
    that checks the WIRE needs the SDK by its very subject: without it, it would be
    checking not the wire but its own representations of it. The exception is named
    ONCE here, rather than as three `continue`s scattered in place.
    """
    return [p for p in _py_files(DOOR) if p.parent.name != "tests"]


def _imported_modules(path: pathlib.Path) -> set[str]:
    """All module names that the file imports — including imports inside the body."""
    tree = ast.parse(path.read_text("utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_the_language_never_mentions_the_door():
    """LANGUAGE -> DOOR = 0. The direction is one-way by construction.

    A reference running the other way from here would mean the language does not
    build without the door — that is, that the `[mcp]` extra stopped being an extra.
    """
    # 🔴 THE COMMAND-LINE DOOR IS ALSO A DOOR, NOT THE LANGUAGE (04.09.2026).
    # `kir/__main__.py` appeared that day (`kir demo` gets the outside person home in
    # two turns instead of seventeen), and its `kir doctor` NAMES the missing extra:
    # «python -m kir.mcp откажет с кодом 2. Ставится: pip install "kir-building[mcp]"».
    # This is a MENTION IN A STRING FOR THE HUMAN, not a dependency.
    #
    # This file's law is "the language is not required to build without the door,"
    # and it is about a DEPENDENCY. So the exception is not silent: below stands a
    # COUNTER-REQUIREMENT — the command line is required NOT TO IMPORT the door.
    # Remove it, and the exception becomes a hole; keep it, and the law stands more
    # intact than before, because now it asks about the import, not the text.
    КОМАНДНАЯ_СТРОКА = KIR_ROOT / "__main__.py"
    if КОМАНДНАЯ_СТРОКА.is_file():
        ввозит = _imported_modules(КОМАНДНАЯ_СТРОКА)
        дверные = sorted(m for m in ввозит if m == "kir.mcp"
                         or m.startswith("kir.mcp."))
        assert дверные == [], (
            f"командная строка ИМПОРТИРУЕТ дверь: {дверные}. Упоминание в "
            f"строке для человека законно, зависимость — нет: с ней "
            f"дополнение `[mcp]` перестало бы быть дополнением")

    guilty: list[str] = []
    прочитано = 0
    for path in _py_files(KIR_ROOT):
        if DOOR in path.parents or path == DOOR or path == КОМАНДНАЯ_СТРОКА:
            continue
        text = path.read_text("utf-8")
        прочитано += 1
        if "kir.mcp" in text or "from kir import mcp" in text:
            guilty.append(str(path.relative_to(KIR_ROOT.parent)))
    # DENOMINATOR FIRST: zero files read gives exactly the same empty
    # `guilty` as a clean language.
    assert прочитано >= _ФАЙЛОВ_ЯЗЫКА_НЕ_МЕНЬШЕ, (
        f"обход прочёл {прочитано} файлов языка при поле "
        f"{_ФАЙЛОВ_ЯЗЫКА_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 954 из 967 без "
        f"двери). Это заявление о ХОДОКЕ: «язык не знает про дверь» ниже "
        f"НИЧЕГО не означает")
    assert guilty == [], f"язык знает про дверь: {guilty}"


def test_importing_the_language_does_not_load_the_door():
    """A MEASUREMENT, NOT AN ARGUMENT: a fresh process, `import kir`, a census of
    `sys.modules`.

    Source parsing would not show this: a re-export in `__init__` or a lazy import
    in someone else's module would slip right past it.
    """
    code = ("import kir, sys; "
            "print([m for m in sys.modules if m.startswith('kir.mcp')])")
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, cwd=str(KIR_ROOT.parent))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]", (
        f"`import kir` притянул дверь: {proc.stdout.strip()}")


def test_the_protocol_sdk_lives_in_exactly_one_file():
    """The protocol SDK is one file of the door. Instruments are out of the count:
    see `_door_sources`."""
    # DENOMINATOR FIRST: an empty door would give `homes == []`, while
    # `[SDK_HOME]` is expected — but for the three sweeps further down the file, the
    # same `_door_sources()` is checked against a list that passes empty too. The
    # number is planted here, at the set's first reader.
    источники = _door_sources()
    assert len(источники) >= _ФАЙЛОВ_ДВЕРИ_НЕ_МЕНЬШЕ, (
        f"обход нашёл {len(источники)} файлов двери при поле "
        f"{_ФАЙЛОВ_ДВЕРИ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 8 вне `tests` из 13). "
        f"Это заявление о ХОДОКЕ, а не о двери")
    homes = []
    for path in источники:
        mods = _imported_modules(path)
        if any(m == "mcp" or m.startswith("mcp.") or m.startswith("mcp_types")
               for m in mods):
            homes.append(path.name)
    assert homes == [SDK_HOME], (
        f"SDK протокола расползся по файлам: {homes}; предмет — {SDK_HOME}")


def test_the_sdk_is_imported_inside_a_function_not_at_module_level():
    """The extra may be absent — and then the surface is still required to read."""
    tree = ast.parse((DOOR / SDK_HOME).read_text("utf-8"))
    top_level = set()
    for node in tree.body:                      # top level of the module only
        if isinstance(node, ast.Import):
            top_level.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module)
    offenders = {m for m in top_level
                 if m == "mcp" or m.startswith("mcp.") or m.startswith("mcp_types")}
    assert offenders == set(), (
        f"SDK импортируется на верхнем уровне {SDK_HOME}: {offenders}")


def test_the_door_calls_only_the_closed_list():
    """DOOR -> LANGUAGE: enumerated, not forbidden. Growth is a DECISION, not a side
    effect."""
    touched: set[str] = set()
    for path in _door_sources():
        for module in _imported_modules(path):
            if not module.startswith("kir"):
                continue
            if module == "kir" or module.startswith("kir.mcp"):
                continue
            # `from kir import course` gives both "kir" and "kir.course" — we take
            # the one that actually names the language module.
            parts = module.split(".")
            touched.add(".".join(parts[:2]))
    extra = touched - ALLOWED_KIR_MODULES
    assert extra == set(), (
        f"дверь потянула модули вне закрытого списка: {sorted(extra)} — "
        f"это решение, а не побочный эффект: впиши их в ALLOWED_KIR_MODULES "
        f"вместе с причиной либо убери обращение")


def test_the_closed_list_has_no_dead_entries():
    """A list that has outlived its content lies the same way an unclosed one does.

    The same kind of defect that `record_ratchet` guards against in `tool_doc`: a
    record that has outlived its truth costs more than a missing one.
    """
    touched: set[str] = set()
    for path in _door_sources():
        for module in _imported_modules(path):
            if module.startswith("kir.") and not module.startswith("kir.mcp"):
                touched.add(".".join(module.split(".")[:2]))
    dead = ALLOWED_KIR_MODULES - touched
    assert dead == set(), f"в списке лежат модули, которых дверь не зовёт: {sorted(dead)}"


#: The file that is allowed to ask for a port, and the ONE port it is allowed to
#: ask for. A pair, not two lists: "who asks" and "what is asked for" would drift
#: apart, and then one day the live door would pull in the product's `EXECUTION`,
#: without violating either of the two lists on its own.
_PORT_ASKER = ("live.py", "ports.MCP_REVIT")


def test_only_the_live_door_asks_a_port_and_only_its_own():
    """🔴 THIS INSTRUMENT'S TARGET CHANGED ON 02.09.2026, AND THAT IS A DECISION.

    Before stage 4 it required ZERO ports across the whole door — correctly,
    because the whole door was offline. Now it has two halves, and the "zero"
    requirement would be a lie about one of them: the live door IS REQUIRED to
    name its transport, otherwise it would be hiding it.

    The requirement is therefore different, and still checkable by a number: the
    port is asked for by EXACTLY ONE file, and EXACTLY ITS OWN. Five offline doors
    are required to stand without a host — that is exactly the promise to the
    outside person.
    """
    askers = []
    for path in _door_sources():
        text = path.read_text("utf-8")
        if "ports.need(" in text or "ports.ask(" in text:
            askers.append(path.name)
    assert askers == [_PORT_ASKER[0]], (
        f"порт хозяина спрашивают: {askers}; позволено только "
        f"{_PORT_ASKER[0]}")
    live = (DOOR / _PORT_ASKER[0]).read_text("utf-8")
    asked = {line.split("ports.need(")[1].split(")")[0].strip()
             for line in live.splitlines() if "ports.need(" in line}
    assert asked == {_PORT_ASKER[1]}, (
        f"живая дверь спрашивает {sorted(asked)}, а ей позволен только "
        f"{_PORT_ASKER[1]} — порт продукта сюда не переносится")


def test_the_offline_doors_ask_nothing():
    """Five offline doors are required to stand without a host — by EXECUTION.

    Source parsing would not show this: it sees that `ports` is not named, but it
    does not see that the door would fail without it anyway, along a different
    branch.
    """
    import asyncio

    from kir.mcp import server
    from kir import ports as _p

    assert _p.MCP_REVIT not in _p.supplied(), "прибор негоден: порт поставлен"
    for name, args in (("kir_spec", {"op": "create_wall"}),
                       ("kir_compile", {"program": {"ops": []}}),
                       ("kir_rehearse", {"program": {"ops": []}}),
                       ("kir_preview", {"program": {"ops": []}})):
        body, crashed = asyncio.run(server.dispatch(name, args))
        assert not crashed, f"{name} упала без хозяина"
        assert (body.get("err") or {}).get("code") != "no_transport", (
            f"{name} потребовала транспорт — она обязана стоять офлайн")


def test_the_surface_reads_without_the_sdk_installed(monkeypatch):
    """The surface is judged by someone who installed KIR WITHOUT the `[mcp]`
    extra."""
    import importlib
    for name in [m for m in list(sys.modules) if m == "mcp" or m.startswith("mcp.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [
        _BlockMCP()] + list(sys.meta_path))
    module = importlib.reload(importlib.import_module("kir.mcp.surface"))
    assert len(module.tools()) == 7
    with pytest.raises(ImportError):
        importlib.import_module("mcp")


class _BlockMCP:
    """Import guard: pretends the extra is not installed on the machine."""

    def find_module(self, fullname, path=None):  # old protocol, harmless
        return None

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp."):
            raise ImportError(f"дополнение [mcp] не поставлено ({fullname})")
        return None
