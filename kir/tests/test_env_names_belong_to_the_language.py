"""AN ENVIRONMENT VARIABLE NAME BELONGS TO THE LANGUAGE, NOT TO A FOREIGN PRODUCT.

WHY, IN THE OWNER'S OWN WORDS OF 27.08.2026: "anyone can download and stand it up themselves."
Someone who installs the `kir` package under Apache-2.0 ends up checking the variable
`KUKAI_CHECKER_V2` — the name of a product they have never heard of and do not
have. **Whoever fails to stand it up builds ZERO buildings**, so this is not cosmetics.

MEASUREMENT OF 28.08.2026, and it corrected my own earlier number. The plan had recorded
"81 names `KUKAI_*`" — that is a count of STRING OCCURRENCES, not of names actually read. The real figure:

    the package (excluding tests)   12 names at 12 read sites
    of which about the LANGUAGE     10   -> moved, `kir/env.py::RENAMED`
    product-specific                 1   -> `KUKAI_A5_CONFIRM_TOKEN`, the A5 lease: a foreign
                                subject, and renaming it would mean declaring
                                it our own. A BOUNDARY debt, fixed by a port
    not a read at all                1   -> `KUKAI_X` in a comment in `capability_graph.py`
    tests                           36   -> set the environment themselves; the double read does not touch them

🔴 AND THE FIRST INSTRUMENT HERE LIED, WHICH IS WORTH RECORDING. `grep -rh … | grep -v
/tests/` does not filter out tests AT ALL: `-h` strips the file name, and the filter looks at
the matched TEXT. It gave "43 names" instead of 12. So below, the SYNTAX is read
(`ast`), not lines of text: a comment or a docstring is not a reference to the environment.

WHY TWO NAMES ARE READ RATHER THAN ONE RENAMED. The `/opt/kir` tree
is installed into the live service's venv as EDITABLE (`KIR_PLAN.md` §0.1): there is no build
and no release between saving a file and `kukai-backend.service`. A clean
rename would devalue the environment of running units at the very moment
the file hit the disk.

Run: pytest kir/tests/test_env_names_belong_to_the_language.py -q
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest

from kir import env

_PKG = pathlib.Path(__file__).resolve().parent.parent

#: A direct read of the old name, left in INTENTIONALLY and with a rationale.
ALLOWED_DIRECT: dict[str, str] = {
    "KUKAI_A5_CONFIRM_TOKEN": "аренда A5 — понятие ПРОДУКТА; долг границы, не имени",
}


def _string_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level string constants: `_FLAG = "KUKAI_…"`.

    🔴 WHY, AND THIS IS A HOLE IN THE FIRST DRAFT OF THIS SAME FILE (28.08.2026). It
    used to read only the LITERAL at the point of the call itself — `os.environ.get("KUKAI_…")` — and
    declared "not a single moved name is read directly." The promise was
    false: in the package, **52 environment reads go THROUGH A VARIABLE**
    (`os.environ.get(_FLAG)`, where `_FLAG` is declared one line above), and among them
    sixteen more `KUKAI_*` names turned up.

    The form is exactly the one the header warns about: the instrument answered TRUTHFULLY to
    its own question ("no literals") and was read as an answer to a different one ("no
    reads at all"). The third correction of the same number in one shift — 43, then 12,
    now 28 — and each time the one at fault was not the subject, but the instrument.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            out[node.targets[0].id] = node.value.value
    return out


def _env_reads(tree: ast.AST) -> list[str]:
    """Names READ from the environment — by syntax, not by string matching.

    Both ways are allowed: a literal at the call site and a module-level constant.

    🔴 THE GUARD WAS BLIND TO AN ENTIRE READING METHOD (01.09.2026). It caught
    `os.environ.get/setdefault/pop` and `os.environ[...]` — and did NOT catch
    `os.getenv(...)`, which `compile_client.py` reads with. The blindness was found not by
    reading, but by the fact that adding the `KIR_COMPILE_REQUIRED_VERSIONS` pair to
    `env.RENAMED` was SUPPOSED to turn this ratchet red and did NOT: the
    run gave `10 passed` while the old name was still being read directly, live.
    The declared control turned out mute, and this is exactly the form the
    ratchet is written against — "a guard pinned to the shape of the first case."

    What is asked is the PROPERTY "the name came from the environment," not the call's shape: two entry
    points (`os.environ` and `os.getenv`) — one door.
    """
    found: list[str] = []
    consts = _string_constants(tree)

    def is_environ(node: ast.AST) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
            isinstance(node, ast.Name) and node.id == "environ")

    def name_of(arg: ast.AST) -> str | None:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        if isinstance(arg, ast.Name):
            return consts.get(arg.id)
        return None

    def is_getenv(func: ast.AST) -> bool:
        """`os.getenv(...)` and a bare `getenv(...)` after `from os import getenv`."""
        return (isinstance(func, ast.Attribute) and func.attr == "getenv") or (
            isinstance(func, ast.Name) and func.id == "getenv")

    for node in ast.walk(tree):
        arg: ast.AST | None = None
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("get", "setdefault", "pop") \
                and is_environ(node.func.value) and node.args:
            arg = node.args[0]
        elif isinstance(node, ast.Call) and is_getenv(node.func) and node.args:
            arg = node.args[0]
        elif isinstance(node, ast.Subscript) and is_environ(node.value):
            arg = node.slice
        if arg is not None:
            got = name_of(arg)
            if got:
                found.append(got)
    return found


# --------------------------------------------------------------- TABLE

def test_the_table_moves_only_from_KUKAI_to_KIR():
    assert env.RENAMED, "таблица пуста — проверять нечего"
    for new, legacy in env.RENAMED.items():
        assert new.startswith("KIR_"), new
        assert legacy.startswith("KUKAI_"), legacy
    assert len(set(env.RENAMED.values())) == len(env.RENAMED), \
        "одно прежнее имя отдано двум новым — читалось бы через раз"
    assert env.LEGACY_NAMES == frozenset(env.RENAMED.values())


# --------------------------------------------------------------- READING TWO NAMES

@pytest.fixture
def clean_env(monkeypatch):
    for name in ("KIR_CHECKER_V2", "KUKAI_CHECKER_V2"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_the_former_name_keeps_working(clean_env):
    """🔴 THE LIVE SERVICE DOES NOT NOTICE THE FIX — that is exactly why it is all done this way."""
    clean_env.setenv("KUKAI_CHECKER_V2", "1")
    assert env.get("KIR_CHECKER_V2", "0") == "1"


def test_the_new_name_wins_even_when_it_says_zero(clean_env):
    """A set NEW name is a CHOICE, and it is not obliged to yield to the old one.

    The reverse order would make the new name impossible to turn off: someone who set
    `KIR_CHECKER_V2=0` on a service that still had the old `=1` could not disable anything.
    """
    clean_env.setenv("KUKAI_CHECKER_V2", "1")
    clean_env.setenv("KIR_CHECKER_V2", "0")
    assert env.get("KIR_CHECKER_V2", "x") == "0"


def test_an_empty_new_name_is_a_value_not_an_absence(clean_env):
    clean_env.setenv("KUKAI_CHECKER_V2", "1")
    clean_env.setenv("KIR_CHECKER_V2", "")
    assert env.get("KIR_CHECKER_V2", "x") == ""


def test_neither_set_gives_the_default(clean_env):
    assert env.get("KIR_CHECKER_V2", "0") == "0"


def test_a_name_with_no_past_reads_nothing_extra(clean_env):
    assert env.get("KIR_NEVER_EXISTED", "d") == "d"


def test_the_flag_itself_honours_both_names(clean_env):
    """Not just the helper, but its CONSUMER too: the helper could be standing aside unused."""
    from kir.checker.flags import checker_v2_enabled

    clean_env.setenv("KUKAI_CHECKER_V2", "1")
    assert checker_v2_enabled() is True
    clean_env.setenv("KIR_CHECKER_V2", "0")
    assert checker_v2_enabled() is False


def test_legacy_in_use_names_what_still_holds_on_the_old_name(clean_env):
    clean_env.setenv("KUKAI_CHECKER_V2", "1")
    assert "KUKAI_CHECKER_V2" in env.legacy_in_use()
    clean_env.setenv("KIR_CHECKER_V2", "1")
    assert "KUKAI_CHECKER_V2" not in env.legacy_in_use(), \
        "имя переехало — докладывать о нём больше нечего"


# --------------------------------------------------------------- RATCHET

def test_no_module_of_the_package_reads_a_renamed_name_directly():
    """🔴 RATCHET: the moved name is not read from the environment DIRECTLY anywhere.

    Without it, the fix rests on attentiveness alone: the next `os.environ.get(
    "KUKAI_…")` will slip past `kir/env.py`, and one person in one environment
    will discover it as a refusal that nobody else can reproduce.

    Tests are deliberately NOT checked: they set their own environment, and nobody
    forbids them from reading it by the old name — the double read makes that harmless.
    """
    #: 🔴 THE RATCHET'S DENOMINATOR, MEASURED 02.09.2026: **299** package files outside
    #: `tests` and outside `env.py`. The ratchet is one-sided — it can say
    #: "found" and cannot say "I went blind"; zero violators from a walk that
    #: lost the tree reads exactly like a clean tree. The neighboring test
    #: below is guarded differently (a two-way check against `ALLOWED_DIRECT`); this one
    #: has nothing to check against — its expectation is EMPTY by design.
    ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ = 250
    offenders: list[str] = []
    прочитано = 0
    for path in sorted(_PKG.rglob("*.py")):
        if "/tests/" in str(path) or path.name == "env.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                     # noqa: PERF203 — not our file
            continue
        прочитано += 1
        for name in _env_reads(tree):
            if name in env.LEGACY_NAMES and name not in ALLOWED_DIRECT:
                offenders.append(f"{path.relative_to(_PKG)}: {name}")
    assert прочитано >= ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ, (
        f"обход прочёл {прочитано} файлов при поле {ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ} "
        f"(замер 02.09.2026 — 299). Это заявление о ХОДОКЕ, а не о дереве: "
        f"пустой список нарушителей ниже НИЧЕГО не означает")
    assert not offenders, (
        "прежнее имя читается в обход kir/env.py — среда чужого человека "
        f"его не задаёт: {offenders}")


def test_the_named_exception_is_still_exactly_one_and_still_there():
    """The exception MUST EXIST, otherwise the ratchet is green by construction.

    If `KUKAI_A5_CONFIRM_TOKEN` ever moves behind a port, this test will turn red and
    demand the entry be removed from `ALLOWED_DIRECT` — that is, the exception cannot
    outlive its own reason silently.
    """
    seen: list[str] = []
    for path in sorted(_PKG.rglob("*.py")):
        if "/tests/" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        seen += [n for n in _env_reads(tree) if n in ALLOWED_DIRECT]
    assert sorted(set(seen)) == sorted(ALLOWED_DIRECT), (
        f"названное исключение исчезло или размножилось: {sorted(set(seen))}")
