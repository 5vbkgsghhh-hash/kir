"""A CLASS: A ROOT COUNTED BY STEPS UPWARD IS CORRECT FOR EXACTLY ONE LAYOUT.

This shape has been bought THREE TIMES, and each time ONE carrier was fixed:

    f518b05   sandbox._backend_root() counted three steps up; after the
              split it gave `/opt`, the sandbox child imported a half-package
              and crashed with `partially initialized module kir.spec`. The
              author, in turn, got "the KIR language failed to load" — the
              language was blamed for a defect in its OWN packaging.

    2e9bff5   install_paths counted `parents[3]`. The arithmetic went wrong
              back at the `kukai/ir` -> `kir` rename: the docstring was
              fixed, the arithmetic was not. `install_root()` answered
              `None` ALWAYS, and eight consumers silently fell into their
              None policy — six telemetry feeds WENT SILENT, acceptance
              started refusing pre-effect.

    here      the walk found further carriers, and `agreements`, because of
              one of them, walked a directory that did not exist: the
              agreement on reverse-path entry points reported "no
              findings," having read NOT A SINGLE file (0 against 223).

🔴 WHY A GUARD, AND NOT THREE FIXES. The canon's rule: having caught a shape —
look for its SECOND CARRIER RIGHT HERE. Neither of the two previous times did
this, and both times the shape came back. Here it is pinned by a WALK, not
by memory.

🔴 AND THE WALK ITSELF CARRIED THE VERY SHAPE IT HUNTS, TWICE, both caught
before publication:

    edition 1   searched only for expressions whose ROOT is the literal
                `__file__`, and missed `axes_census`, where the root is put
                into a module-level variable. An instrument covering PART OF
                THE RANGE;
    edition 2   kept a closed list of wrappers ("Path","PurePath",...) and
                lost `clash_bundle`, where the constructor is imported as
                `_Path`. A name is a convention, not an authority (shape 7).

So the walk unfolds wrappers BY SHAPE (a call with one positional argument),
not by name, and resolves names to a fixed point.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import tempfile
import unittest

import kir

#: A rise of ONE level is the module's own directory; it is stable under any
#: layout. A rise of TWO or more counts as a carrier: it leaves the module
#: and thereby encodes how deep the module sits inside the tree.
CARRIER_FROM = 2

_PKG = pathlib.Path(kir.__file__).resolve().parent
_REPO = _PKG.parent

#: The guard's scope is the PACKAGE. CI scripts, examples, and instruments
#: outside the package live their own life and do not ship in the wheel;
#: their carriers are named in the wave's report, but are not held by a
#: ratchet: the list is CLOSED AND NOT COMPLETE, and this is stated here so
#: that an empty cell does not read as "clean over there."
_SCAN_ROOT = _PKG

#: Carriers left in SOMEONE ELSE'S files at the moment the guard was set up.
#: Each is an unclosed debt with a named owner, not a resolution.
#:
#: `kir/instruments/` — a neighbor's uncommitted wave; this wave had no
#: right to touch it. Once that wave lands, the lines will either leave here
#: or be fixed by their own author.
KNOWN_FOREIGN: dict[str, str] = {
    "instruments/bounds_audit.py": "untracked волна соседа (27.08)",
    "instruments/capability_graph.py": "untracked волна соседа (27.08)",
    "instruments/content_coverage.py": "untracked волна соседа (27.08)",
}

_ASCEND_CALLS = ("dirname",)
_PASSTHROUGH_CALLS = ("resolve", "absolute", "expanduser", "abspath",
                      "realpath", "normpath")


def _peel(node: ast.AST) -> tuple[ast.AST, int]:
    """Take the rise off an expression -> (root, number of levels)."""
    depth = 0
    n = node
    for _ in range(64):
        if isinstance(n, ast.Attribute) and n.attr == "parent":
            depth += 1
            n = n.value
            continue
        if (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute)
                and n.value.attr == "parents"):
            idx = n.slice
            depth += (idx.value if (isinstance(idx, ast.Constant)
                                    and isinstance(idx.value, int)) else 99)
            n = n.value.value
            continue
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in _ASCEND_CALLS and n.args):
            depth += 1
            n = n.args[0]
            continue
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            if isinstance(n.right, ast.Constant) and n.right.value == "..":
                depth += 1
            n = n.left
            continue
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr in _PASSTHROUGH_CALLS):
            n = n.args[0] if n.args else n.func.value
            continue
        # A wrapper unfolds BY SHAPE, not by name: `Path(x)`, `pathlib.Path(x)`,
        # `_Path(x)`, `str(x)` — all of these are one argument, no keywords.
        # A closed list of names has already lost a carrier here before.
        if (isinstance(n, ast.Call) and len(n.args) == 1 and not n.keywords
                and isinstance(n.func, (ast.Name, ast.Attribute))):
            n = n.args[0]
            continue
        break
    return n, depth


def _seed_depth(node: ast.AST, bound: dict[str, int]) -> int | None:
    """The rise's depth, if the root is `__file__` or a name derived from it."""
    root, depth = _peel(node)
    if isinstance(root, ast.Name):
        if root.id == "__file__":
            return depth
        if root.id in bound:
            return depth + bound[root.id]
    return None


def _bindings(tree: ast.AST) -> dict[str, int]:
    """Names bound to an expression derived from `__file__`, to a fixed point."""
    bound: dict[str, int] = {}
    for _ in range(6):
        grew = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            if node.value is None:
                continue
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target])
            d = _seed_depth(node.value, bound)
            if d is None:
                continue
            for t in targets:
                if isinstance(t, ast.Name) and bound.get(t.id) != d:
                    bound[t.id] = d
                    grew = True
        if not grew:
            break
    return bound


def carriers_in_source(source: str) -> list[tuple[int, int, str]]:
    """Carriers within one source file: (line, rise, text)."""
    tree = ast.parse(source)
    bound = _bindings(tree)
    best: dict[int, tuple[int, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Attribute, ast.Subscript, ast.Call,
                                 ast.BinOp)):
            continue
        d = _seed_depth(node, bound)
        if d is None or d < CARRIER_FROM:
            continue
        ln = node.lineno
        if ln not in best or d > best[ln][0]:
            best[ln] = (d, ast.unparse(node)[:92])
    return sorted((ln, d, t) for ln, (d, t) in best.items())


#: 🔴 THE WALK'S DENOMINATOR, MEASURED 02.09.2026: **300** package files
#: outside `tests` and outside `test_*`. It stands INSIDE the walk, because
#: its main consumer is one-sided: `offenders` is `hits` minus
#: `KNOWN_FOREIGN`, and empty `hits` give empty offenders — "no step-counted
#: findings in the package" sounds the same whether that is actually true or
#: the walk read nothing at all. The neighboring test on stale foreign debt
#: would turn red, but it is about a DIFFERENT subject, and relying on its
#: refusal would mean holding the guard up by a side effect.
_ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ = 250


def sweep_package() -> tuple[dict[str, list], list[tuple[str, str]]]:
    """Walk the package. -> (carriers by file, files that FAILED TO PARSE)."""
    hits: dict[str, list] = {}
    unparsed: list[tuple[str, str]] = []
    осмотрено = 0
    for f in sorted(_SCAN_ROOT.rglob("*.py")):
        rel = f.relative_to(_SCAN_ROOT)
        parts = rel.parts
        if "__pycache__" in parts:
            continue
        if "tests" in parts or f.name.startswith("test_"):
            continue
        осмотрено += 1
        try:
            rows = carriers_in_source(f.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            unparsed.append((str(rel), str(exc)))
            continue
        if rows:
            hits[str(rel)] = rows
    assert осмотрено >= _ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ, (
        f"обход осмотрел {осмотрено} файлов при поле "
        f"{_ФАЙЛОВ_ПАКЕТА_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 300). Это заявление "
        f"о ХОДОКЕ, а не о пакете: пустые находки ниже НИЧЕГО не означают")
    return hits, unparsed


class ОбходНеМожетБытьЗелёнымПоПостроению(unittest.TestCase):
    """An instrument that finds NOTHING on any input at all is not an instrument."""

    def test_the_sweep_finds_a_deliberately_planted_carrier(self):
        for source, why in (
            ("import pathlib\nR = pathlib.Path(__file__).parents[3]\n",
             "parents[N]"),
            ("import pathlib\nR = pathlib.Path(__file__).parent.parent\n",
             "цепочка .parent"),
            ("import os\nR = os.path.dirname(os.path.dirname("
             "os.path.abspath(__file__)))\n", "вложенный dirname"),
            ("import pathlib\n_H = pathlib.Path(__file__).resolve()\n"
             "R = _H.parent.parent.parent\n", "через ПЕРЕМЕННУЮ"),
            ("import pathlib as _p\nR = _p.Path(__file__).parents[2]\n",
             "обёртка под ПСЕВДОНИМОМ"),
            ("import pathlib\nR = pathlib.Path(__file__).parent / '..' / '..'\n",
             "подъём через '..'"),
        ):
            with self.subTest(why=why):
                self.assertTrue(
                    carriers_in_source(source),
                    f"обход не увидел носитель ({why}) — он зелен по построению")

    def test_the_sweep_does_not_flag_the_modules_own_directory(self):
        # One step is the module's own directory, stable under any layout.
        self.assertEqual(
            [], carriers_in_source(
                "import pathlib\nR = pathlib.Path(__file__).resolve().parent\n"))
        self.assertEqual(
            [], carriers_in_source(
                "import pathlib\nR = pathlib.Path(__file__).with_name('x.cs')\n"))

    def test_an_anchor_on_the_package_is_not_a_carrier(self):
        # `kir.__file__` is the authority: it points at the package, not at
        # the depth of the asking module. A rise from IT does not encode the
        # layout.
        self.assertEqual(
            [], carriers_in_source(
                "import kir, pathlib\n"
                "R = pathlib.Path(kir.__file__).resolve().parent.parent\n"))


class ВПакетеНетСчётаШагами(unittest.TestCase):

    def test_no_module_in_the_package_counts_steps_up(self):
        hits, unparsed = sweep_package()
        self.assertEqual(
            [], unparsed,
            "обход не разобрал файлы — отчёт ДИСКВАЛИФИЦИРОВАН, а не «чисто»: "
            f"{unparsed}")
        offenders = {f: rows for f, rows in hits.items()
                     if f not in KNOWN_FOREIGN}
        if offenders:
            lines = [f"  {f}" for f in sorted(offenders)]
            for f in sorted(offenders):
                for ln, d, txt in offenders[f]:
                    lines.append(f"    :{ln} подъём {d}  {txt}")
            self.fail(
                "корень отсчитан ШАГАМИ ВВЕРХ — верно ровно для одной "
                "раскладки:\n" + "\n".join(lines) +
                "\n\nЛЕЧЕНИЕ ПО РОДУ:\n"
                "  корень ПАКЕТА    -> якорь `kir.__file__`\n"
                "  корень УСТАНОВКИ -> `install_paths.install_data_path(...)`,\n"
                "                      причина тишины — `install_root_refusal()`\n"
                "  каталог РЯДОМ    -> `Path(__file__).with_name(...)`\n"
                "  нет по построению-> типизированный отказ, называющий\n"
                "                      переменную и следующий ход")

    def test_the_foreign_debt_is_named_and_still_real(self):
        """Debt in foreign files is CLOSED OFF BY A LIST, but does not
        pretend to be resolved.

        An entry whose file has disappeared or been fixed must leave here:
        otherwise the list ages silently and reads as "still dirty there"
        when it is already clean.
        """
        hits, _ = sweep_package()
        stale = [f for f in KNOWN_FOREIGN if f not in hits]
        self.assertEqual(
            [], stale,
            "запись о чужом долге пережила сам долг — снять её: "
            f"{stale}")


class ЯкорьПереживаетСменуРаскладки(unittest.TestCase):
    """The control that WOULD FAIL a step count: the package moves.

    This is exactly the proof that the SHAPE was cured, not the symptom. A
    step count is tied to depth; the anchor is tied to the package's
    location, and it moves along with it.
    """

    def test_anchored_paths_follow_the_package_to_another_layout(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            deep = pathlib.Path(tmp) / "a" / "b" / "c"
            deep.mkdir(parents=True)
            shutil.copytree(_PKG, deep / "kir",
                            ignore=shutil.ignore_patterns("__pycache__"))
            run_from = pathlib.Path(tmp) / "run"
            run_from.mkdir()
            probe = (
                "import pathlib, kir\n"
                "from kir import agreements as A\n"
                "from kir.decompile import lift_cache as L\n"
                "print(A._BACKEND)\n"
                "print(len(A._py_files('kir/decompile')))\n"
                "print(L._EXTRA_SOURCE_PATHS[0].exists())\n")
            out = subprocess.run(
                [sys.executable, "-c", probe], cwd=run_from,
                env={"PYTHONPATH": str(deep), "PATH": "/usr/bin:/bin"},
                capture_output=True, text=True, timeout=180)
            self.assertEqual(0, out.returncode, out.stderr[-2000:])
            backend, seen, spec_ok = out.stdout.strip().splitlines()

            self.assertEqual(str(deep), backend,
                             "якорь не поехал за пакетом")
            self.assertGreater(int(seen), 100,
                               "обход согласий ослеп в новой раскладке")
            self.assertEqual("True", spec_ok,
                             "реестр не найден от переехавшего пакета")

            # AND NOW — what the OLD count WOULD HAVE DONE on this same
            # input. Without this half, the control cannot distinguish the
            # shape: it would have been green even before the fix.
            old = (deep / "kir" / "agreements.py").resolve().parents[2]
            self.assertFalse(
                (old / "kir").exists(),
                "контроль вырожден: старый счёт дал бы ВЕРНЫЙ ответ на этой "
                "раскладке, значит он ничего не различает")


class УстановкаМолчитПРИЧИНОЙ(unittest.TestCase):
    """Silence about the installation must be something that can be asked about, not just empty."""

    def test_absent_installation_is_named_not_zero(self):
        from kir.install_paths import install_root, install_root_refusal
        if install_root() is not None:
            self.skipTest("установка названа — молчания нет, проверять нечего")
        reason = install_root_refusal()
        self.assertIsNotNone(reason)
        self.assertIn("KIR_INSTALL_ROOT", reason)

    def test_the_bridge_stand_names_its_absence(self):
        from kir.bridge import mock_server
        reason = mock_server.fixtures_refusal()
        if reason is None:
            self.skipTest("стенд назван — отсутствия нет")
        self.assertIn("KIR_BRIDGE_FIXTURES", reason)
        self.assertIn("ХОЗЯИНА", reason)


if __name__ == "__main__":
    unittest.main()
