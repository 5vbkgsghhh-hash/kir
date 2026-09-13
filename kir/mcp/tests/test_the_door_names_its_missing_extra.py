"""A DOOR WITH NOTHING TO RISE ON SAYS SO OUT LOUD, AND WITH A SINGLE NUMBER.

🔴 MEASURED 04.09.2026, A CLEAN venv FROM THE WHEEL, `pip install kir_building-…whl`
WITHOUT the `[mcp]` extra — the outside person's path, word for word:

    $ python -m kir.mcp
    INFO kir.mcp: поверхность: kir_author, kir_spec, kir_compile, …
    INFO kir.mcp: схема: схема СВЁРНУТА в $defs (6.99x, 427064->61132 Б): …
    Traceback (most recent call last):
      … 16 кадров, из них 13 в anyio и asyncio …
    ModuleNotFoundError: No module named 'mcp'
    RC=1

Three properties of this output are the defect, and each is closed by its own run
below:

  1. THE SURFACE LISTING PRINTED BEFORE THE CRASH. The door announced seven
     instruments to a launch that would have none of them. On stdio, the model's
     client has nothing but these lines and the return code.

  2. THE WORDS `kir-building[mcp]` NEVER APPEARED ONCE. The failure named a
     FOREIGN library (`No module named 'mcp'`) instead of OUR extra, and the import
     name and the distribution name differ here — a person would go install
     `pip install mcp`, which is the wrong thing. This is exactly the class already
     named in this tree: a refusal is required to name the NEXT MOVE, not a cause
     in someone else's vocabulary.

  3. A RAW STACK INSTEAD OF A REFUSAL, and thirteen of the sixteen frames pointed
     at libraries that had nothing to do with it.

🔴 WHAT THIS FILE DOES NOT CLAIM, AND WHY. It does NOT claim that "the return code
was 0." The report that started the fix said exactly that, and a recheck refuted
it THREE TIMES: a direct run in prod — 1, a direct run in a clean venv from the
wheel — 1, `PIPESTATUS[0]` — 1. The zero appears at exactly one way of
measuring — THROUGH A PIPE (`python -m kir.mcp 2>&1 | tail`), where `$?` belongs
to the tail, not to python. This is a kind of mistake already known to this tree
("the return code gets lost on the pipe"), and it is recorded here so the fix is
not credited to a number that never existed.

The code changes from 1 to 2 for a DIFFERENT reason: in this tree, 1 is already
taken by a SUBSTANTIVE refusal ("the program was read and rejected"), while a door
that never came up read nothing at all. The shape is `kir/__main__.py`: 0 answered
· 1 refused · 2 did not happen.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from kir.mcp import server

#: How to shadow the SDK WITHOUT REMOVING IT. The run must behave identically for
#: someone who has installed `[mcp]` and someone who has not: otherwise the
#: instrument stays silent exactly where the subject exists. The finder RAISES
#: ImportError rather than returning None — otherwise the real finder standing
#: behind it would find the module.
_BLOCK = """
import sys

class _Block:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "mcp" or fullname.startswith("mcp.") \\
                or fullname == "mcp_types" or fullname.startswith("mcp_types."):
            raise ImportError(f"дополнение [mcp] не поставлено ({fullname})")
        return None

sys.meta_path.insert(0, _Block())
for name in [n for n in sys.modules if n == "mcp" or n.startswith("mcp.")
             or n == "mcp_types" or n.startswith("mcp_types.")]:
    del sys.modules[name]

from kir.mcp.server import main
sys.exit(main(__ARGV__))
"""


def _run_without_extra(argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _BLOCK.replace("__ARGV__", argv)],
        capture_output=True, text=True, timeout=180,
        # The directory is NOT the tree's root: the outside person launches the
        # door from wherever they happen to be, and `kir/` is not sitting on
        # their sys.path.
        cwd=str(pathlib.Path.home()))


@pytest.mark.parametrize("argv", ["[]", "['--http']", "['--log-level', 'ERROR']"])
def test_the_absent_extra_is_a_named_refusal_not_a_traceback(argv: str) -> None:
    """A refusal instead of a stack, our name instead of someone else's, and the
    "did not happen" code."""
    p = _run_without_extra(argv)

    assert p.returncode == 2, (
        f"«дверь не поднялась» обязано быть отдельным кодом (2), а пришло "
        f"{p.returncode}\n{p.stderr}")
    # NO RAW STACK. Checked against both pieces of evidence at once: the python
    # header and the exception name — one alone is not enough, the output could
    # carry just half.
    assert "Traceback (most recent call last)" not in p.stderr, p.stderr
    assert "ModuleNotFoundError" not in p.stderr, p.stderr
    # OUR EXTRA IS NAMED IN FULL, quotes included: without them the shell eats the
    # brackets, and the command copied from the refusal does not work.
    assert 'pip install "kir-building[mcp]"' in p.stderr, p.stderr
    assert "СЛЕДУЮЩИЙ ХОД" in p.stderr, p.stderr
    # `--log-level ERROR` has no right to mute the refusal: it is printed, not
    # logged. The same run checks exactly this — via the parameter above.
    assert "ОТКАЗ" in p.stderr, p.stderr


def test_the_surface_is_not_announced_before_the_wire_is_checked() -> None:
    """The promise is not printed before checking what it will be fulfilled with.

    The list of instruments IS A PROMISE; printing it and then crashing means
    lying to the reader who has nothing but these lines.
    """
    p = _run_without_extra("[]")
    assert "поверхность:" not in p.stderr, p.stderr
    for tool in server.surface.names():
        assert tool not in p.stderr, (tool, p.stderr)


def test_stdout_stays_empty_because_the_wire_owns_it() -> None:
    """Not a single character on stdout: on stdio that is where the JSON-RPC frame
    lives, and our line would corrupt it.

    The refusal is required to travel on the same stream as the logs (stderr) —
    otherwise fixing one defect grows a second, quieter one.
    """
    p = _run_without_extra("[]")
    assert p.stdout == "", repr(p.stdout)


def test_the_guard_is_silent_when_the_sdk_is_there(tmp_path, monkeypatch) -> None:
    """CONTROL IN THE OTHER DIRECTION: a guard that ALWAYS refuses is green for
    nothing. With both modules present, it is required to stay silent — on
    `--http` too.

    The modules are stand-ins, and that is enough: the guard asks about PRESENCE,
    not working order (bringing up the SDK just to ask "is it installed" is
    expensive and unnecessary; working order is judged by the neighboring files in
    this directory).
    """
    for name in ("mcp", "mcp_types", "uvicorn"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib
    importlib.invalidate_caches()

    assert server._protocol_sdk_absent(http=False) is None
    assert server._protocol_sdk_absent(http=True) is None


def test_our_own_package_shadowing_the_sdk_is_named_not_reported_absent(
        monkeypatch) -> None:
    """SHADOWING BY NAME IS A SEPARATE FAILURE, NOT "NOT INSTALLED."

    Our package is named `kir/mcp`, and as soon as the `kir/` directory lands on
    sys.path (which pytest does from the rootdir), `import mcp` resolves TO US.
    The full argument is in the header of `build_server`, where this same case
    already cost a false "defect in our own file." Declaring the SDK absent here
    would be worse than silence: the person would go install something already
    installed.
    """
    monkeypatch.syspath_prepend(str(pathlib.Path(server.__file__).parents[1]))
    # Exercise fresh resolution, not a previously loaded real SDK's __spec__.
    monkeypatch.delitem(sys.modules, "mcp", raising=False)
    import importlib
    importlib.invalidate_caches()

    отказ = server._protocol_sdk_absent(http=False)
    assert отказ is not None
    assert "ЭТОТ пакет" in отказ, отказ
    assert "sys.path" in отказ, отказ
    # AND NOT A WORD ABOUT INSTALLING: advice to install the extra here would be a
    # false next move.
    assert "pip install" not in отказ, отказ
