"""THE RECORD SURFACE: the switch collapses the DECLARATION, not the
capability.

THE MEASUREMENT THAT BOUGHT THIS FILE (17.08.2026, `prod-live` tree
`7fb8b8b8`, environment captured from the live process — otherwise
`transport_verdict()` lies and the number drifts by 3.8x, which is
what happened on the first attempt):

    the revit_ir tool as a whole    99,825 B  ≈ 24,956 tokens ON EVERY TURN
      description (prose)           47,357 B   47%
      program    (JSON form)        51,365 B   51%
      program_py (SCRIPT)              238 B    0%

The expensive half is WEAKER than the cheap one: the script counts up
to `MAX_SCRIPT_OPS = 5000` operations against the program's authored
`MAX_OPS_PER_PROGRAM`, and its space already holds `preview` /
`design_check` / `score` / `phase`. Because of the surface's cost,
`revit_ir_enabled()` requires an explicit mode and an admin device —
and live recording goes around it: `design/review.py`, over the shadow
judge's corpus, shows 4 out of 423 calls to writing tools going to
`revit_ir`, that is, 0.9%.

WHAT IS GUARDED HERE, AND WHY EXACTLY THIS:

1. the default is BYTE-FOR-BYTE the previous one (unknown means
   previous behavior);
2. the switch removes at least 40,000 B (otherwise "collapsed" and
   "not collapsed" would look the same, and that is our own named
   defect class);
3. not a single capability is removed: both fields remain in place;
4. the collapsed declaration NAMES what is missing from it and where
   to get it — "nothing in silence" at the cheapest place where it
   applies;
5. THE LANGUAGE HAS NOT MOVED: `schema_gen.program_schema()` is
   byte-for-byte identical under both positions of the switch. This
   is the proof that what was touched is the DECLARATION, not the
   runtime;
6. the switch is read in EXACTLY ONE place in the tree — a structural
   guarantee that it cannot quietly affect anything else.

A FAIL control was run by hand before the commit: a collapsed schema
stripped of its explanation fails item 4; a collapsed schema the size
of the original fails item 2.
"""
# 🔴 NAMES WERE UPDATED ON 28.08.2026 TOGETHER WITH THE VARIABLES
# THEMSELVES (`kir/env.py`). The old `KUKAI_*` used to stand here. The
# test did not "break" — it caught exactly what it was set up for: the
# refusal must name the variable the reader will set RIGHT NOW, not
# the one it used to be called. The old names are still read, and that
# is guarded by `test_env_names_belong_to_the_language.py`; HERE the
# subject is different — the TEXT a human being will see.

from __future__ import annotations

import json
import os
import pathlib
import unittest

import pytest

from kir import schema_transport
from kir.schema_gen import program_schema


#: 🔴 THE SCRATCH DIRECTORY'S NAME, NOT A PATH (13.09.2026). The fixtures below
#: create a file inside a directory with this name to prove the scanner SKIPS it —
#: that is their whole subject, so the name cannot be dropped. Written as a bare
#: name because `test_no_test_reaches_outside_the_tree` reads a path-shaped
#: literal (`.work/…`) as a test reaching into the commit tree's own scratch
#: space. These fixtures never do: every path below is built under a temporary
#: directory, and the name is joined to it here.
SCRATCH_DIR = ".work"

FLAG = "KIR_SCRIPT_FIRST"


def _canon(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _source_paths(root):
    """Prune local artifacts before traversal, without hiding product modules."""
    everywhere = {".git", ".work", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules"}
    at_root = {"build", "dist", "cache", ".cache", "venv", ".venv", ".tox"}
    for current, directories, files in os.walk(root, followlinks=False):
        parent = pathlib.Path(current)
        directories[:] = sorted(name for name in directories
            if name not in everywhere and not (parent == root and name in at_root)
            and not (parent / name / "pyvenv.cfg").is_file())
        for name in sorted(files):
            if name.endswith(".py"):
                yield parent / name


class _FlagCase(unittest.TestCase):
    """The switch is shared mutable process state: set it and restore
    WHAT WE FOUND, not a remembered constant (this mistake has already
    been paid for once)."""

    def setUp(self) -> None:
        self._had = FLAG in os.environ
        self._was = os.environ.get(FLAG)

    def tearDown(self) -> None:
        if self._had:
            os.environ[FLAG] = self._was or ""
        else:
            os.environ.pop(FLAG, None)

    def _tool(self) -> dict:
        from kir import serving
        tools: list = []
        serving.inject_revit_ir_schema(tools)
        return tools[0]


class ScriptFirstSurface(_FlagCase):

    def test_default_is_the_previous_behaviour_byte_for_byte(self):
        os.environ.pop(FLAG, None)
        collapse, why = schema_transport.script_first_verdict()
        self.assertFalse(collapse, why)
        self.assertIn(FLAG, why, "причина обязана называть виновника")

    def test_the_flag_collapses_the_expensive_half(self):
        os.environ.pop(FLAG, None)
        before = len(_canon(self._tool()).encode())
        os.environ[FLAG] = "1"
        after = len(_canon(self._tool()).encode())
        self.assertGreater(
            before - after, 40_000,
            f"свёртка не сэкономила: {before} -> {after}. Замер 17.08 давал "
            f"экономию 50 597 Б; если реестр усох — перемерь и подвинь порог, "
            f"но не молча")

    def test_no_capability_is_removed(self):
        """Both input forms SURVIVED the collapse — what's checked is
        presence, not composition.

        🔴 THE PREDICATE WAS FIXED ON 17.08.2026, and it wasn't the
        author who caught it. Here there used to be
        `assertEqual(sorted(props), ["program", "program_py"])` —
        equality of COMPOSITION for a claim of "no capability
        removed." These are different quantities: removing a field
        and ADDING a field are different events, and equality goes
        red on both. A neighboring session that same day added a
        third property, `example` (a corpus sample), to this very
        schema and asked BEFORE merging; equality would have gone red
        on it, and it would have looked like its own defect, though
        the defect was here — in a test whose predicate is broader
        than its own name.

        Form 12 of the canon is exactly about this: compare SETS, not
        length. What is needed here is a SUBSET check: the collapse
        has no right to drop either of the two forms, and no one
        forbids other waves from expanding the palette.
        """
        os.environ[FLAG] = "1"
        props = self._tool()["function"]["parameters"]["properties"]
        self.assertLessEqual(
            {"program", "program_py"}, set(props),
            "свёртка уронила форму входа: она обязана трогать ОБЪЯВЛЕНИЕ, "
            "а не способность")

    def test_the_collapse_names_what_it_removed_and_where_to_get_it(self):
        """The text's address changed on 18.08 together with the fix
        to the envelope's form.

        While the collapse LIED to the runtime (`type: array`), the
        description hung on the `program` field itself. An honest
        collapse preserves the envelope and collapses what is
        expensive — `ops` and `defaults` — so the text lives on them.
        The test looks for it WHERE IT ACTUALLY IS, and does not pin
        itself to one node: silence about signatures having moved is
        exactly what makes a collapse indistinguishable from a loss.
        """
        os.environ[FLAG] = "1"
        props = self._tool()["function"]["parameters"]["properties"]
        program = props["program"]
        texts = [program.get("description", "")]
        texts += [v.get("description", "")
                  for v in (program.get("properties") or {}).values()
                  if isinstance(v, dict)]
        text = "\n".join(t for t in texts if t)
        for token in ("spec(", "program_py"):
            self.assertIn(token, text,
                          "свёрнутое объявление обязано называть, где взять "
                          "сигнатуру: молчаливая свёртка неотличима от потери")

    def test_the_language_itself_does_not_move(self):
        """What was touched is the declaration, not the runtime — and
        this is PROVEN, not promised."""
        os.environ.pop(FLAG, None)
        flat_off = _canon(program_schema())
        os.environ[FLAG] = "1"
        flat_on = _canon(program_schema())
        self.assertEqual(flat_off, flat_on,
                         "рубильник сдвинул генератор схемы — это уже не "
                         "объявление, а язык")

    def test_the_collapsed_declaration_agrees_with_the_runtime(self):
        """🔴 A GUARD THAT DID NOT EXIST, AND ITS ABSENCE ALMOST
        SHIPPED TO PROD.

        The first edition of the collapsed schema declared
        `{"type": "array"}` — the program as a LIST — whereas the
        runtime requires an envelope object with
        `required ["ir_version","ops"]`. A model that OBEYED the
        declaration got `KIR-P001`. Bought by an A/B pilot: **14
        times over 6 runs, and only for the arm** that was handed the
        collapsed schema. Meanwhile the docstring right beside it
        claimed "the runtime accepts it the way it always did."

        The schema and the runtime are two places that must agree,
        and before this test NOTHING reconciled them. Here they are
        reconciled by EXECUTION: a program written strictly to the
        declaration must compile.
        """
        from kir.compiler import compile_program

        for position in ("0", "1"):
            with self.subTest(flag=position):
                os.environ[FLAG] = position
                declared, _ = schema_transport.program_schema_for_tool()
                flat = program_schema()
                # THE ENVELOPE'S FORM — a contract the runtime CHECKS.
                for key in ("type", "required", "additionalProperties"):
                    self.assertEqual(
                        declared.get(key), flat.get(key),
                        "свёртка подменила %r: объявление и рантайм стали "
                        "двумя грамматиками одного языка" % key)
                self.assertEqual(
                    sorted(declared.get("properties") or {}),
                    sorted(flat.get("properties") or {}),
                    "свёртка уронила поле конверта — модель не узнает о нём")
                # AND, MOST IMPORTANTLY: not a comparison of forms,
                # but EXECUTION.
                prog = {"ir_version": "1.0",
                        "ops": [{"op": "create_level", "id": "l1",
                                 "elev_mm": 3000}]}
                out = compile_program(prog, revit_version="2026", snapshot={})
                self.assertTrue(
                    getattr(out, "ok", False),
                    "программа, написанная ПО ОБЪЯВЛЕНИЮ, не компилируется: "
                    "%s" % [getattr(d, "code", "?")
                            for d in (getattr(out, "diagnostics", None) or [])])

    def test_the_flag_is_read_in_exactly_one_place(self):
        """A structural guarantee is stronger than a checked one: one
        READER — one effect.

        🔴 THE PREDICATE WAS REWRITTEN ON 18.08.2026, AND THE
        PREVIOUS ONE WAS FORM 7 — THE PROBE MATCHED THE LABEL, NOT
        THE SUBJECT. It looked for the flag's NAME as a substring in
        any file and went red on `tools/design/mission_bench.py`,
        where the name appeared in order to SET the flag AND RESTORE
        IT around building the tool (`_schema_form`). A test rig does
        not decide the product's behavior — it MEASURES it,
        presenting both forms of the schema in turn.

        The red would have been "fixed" by one of two wrong ways: an
        exception list (it would drift out of sync) or deleting the
        check (it is load-bearing). The correct fix is to change the
        KIND of probe: parse the AST and distinguish **reading**
        (`os.environ.get(F)` / `os.getenv(F)`) from **writing**
        (`os.environ[F] = ...`). There must be exactly one reader —
        it IS the authority; there can be any number of writers, but
        each one must be VISIBLE, not silent, so they are listed in
        the refusal text.

        The flag's name sits in the files as a constant, not as a
        literal at the call site, so the constants are resolved by
        module: `F = "KUKAI_..."` at the top, and `F` at the call.
        A probe looking for a literal at the call site would have
        found NOT A SINGLE reader and would have been green by
        construction (form 8).
        """
        import ast

        # 🔴 THE ROOT IS THE PACKAGE, NOT TWO STEPS UP (28.08.2026).
        # `parents[2]` from `/opt/kir/kir/schema_transport.py` gives
        # `/opt` — the directory where our package sits next to other
        # trees: the scan was looking for readers somewhere other
        # than us. The same class of bug fixed in `install_paths` on
        # 27.08 and in three more parsing tests on 28.08.
        root = pathlib.Path(schema_transport.__file__).resolve().parent.parent
        readers: list[str] = []
        writers: list[str] = []

        def _names_bound_to_flag(tree: ast.AST) -> set[str]:
            """Module-level names whose value is exactly the flag's
            string."""
            out = {FLAG}
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    value = node.value
                    if isinstance(value, ast.Constant) and value.value == FLAG:
                        targets = (node.targets if isinstance(node, ast.Assign)
                                   else [node.target])
                        for t in targets:
                            if isinstance(t, ast.Name):
                                out.add(t.id)
            return out

        def _is_flag(node: ast.AST, names: set[str]) -> bool:
            if isinstance(node, ast.Constant):
                return node.value == FLAG
            return isinstance(node, ast.Name) and node.id in names

        for path in _source_paths(root):
            if "/tests/" in str(path) or path.name.startswith("test_"):
                continue
            try:
                src = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if FLAG not in src:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            names = _names_bound_to_flag(tree)
            rel = str(path.relative_to(root))
            for node in ast.walk(tree):
                # READ: os.environ.get(F) or os.getenv(F)
                if isinstance(node, ast.Call) and node.args \
                        and _is_flag(node.args[0], names) \
                        and isinstance(node.func, ast.Attribute) \
                        and node.func.attr in ("get", "getenv"):
                    readers.append(rel)
                # READ: os.environ[F] in a VALUE position
                elif isinstance(node, ast.Subscript) \
                        and _is_flag(node.slice, names) \
                        and isinstance(node.ctx, ast.Load):
                    readers.append(rel)
                # WRITE: os.environ[F] = ... or del os.environ[F]
                elif isinstance(node, ast.Subscript) \
                        and _is_flag(node.slice, names) \
                        and isinstance(node.ctx, (ast.Store, ast.Del)):
                    writers.append(rel)

        # THE BOUNDARY IS DRAWN BY PRODUCT, NOT BY AN EXCEPTION LIST.
        # The package holds what ships to prod, and there the reader
        # must be EXACTLY ONE: two authorities for one behavior is our
        # own named defect. `tools/` holds offline instruments, which
        # never execute in prod at all.
        #
        # 🔴 THE PREFIX WAS `kukai/` AND STAYED THAT WAY AFTER THE
        # SPLIT ON 27.08 — and that directory no longer exists. The
        # selection always returned EMPTY, while the expectation was
        # already saying `kir/…`, and the test went red with "more
        # than one reader" while showing zero. A bug in the selection
        # reads as a finding about the subject — our own named form.
        # Fixed on 28.08 together with the move of the variable names.
        _PKG = "kir/"
        product = sorted({r for r in set(readers) if r.startswith(_PKG)})
        self.assertEqual(
            product, ["kir/schema_transport.py"],
            "у рубильника больше одного ЧИТАТЕЛЯ В ПРОДУКТЕ — значит у "
            "поведения больше одного авторитета, и они разъедутся: %s" % product)

        # AND THIS IS NOT AN INDULGENCE FOR INSTRUMENTS, BUT THE
        # SECOND HALF OF THE REQUIREMENT. An instrument that READS a
        # flag and does not WRITE it silently depends on whatever
        # someone else left in the environment — and measures
        # something other than what it thinks it measures. Whoever
        # touches the flag must also RESTORE it. Bought by exactly
        # this case: a flag leaking from one rig arm into another gave
        # the expanded arm the collapsed arm's budget (14,438 against
        # 43,030) with a fingerprint from the expanded one.
        borrowers = sorted({r for r in set(readers)
                            if not r.startswith(_PKG)})
        givers_back = {w for w in set(writers) if not w.startswith(_PKG)}
        silent = [b for b in borrowers if b not in givers_back]
        self.assertEqual(
            silent, [],
            "прибор ЧИТАЕТ рубильник и никогда не ПИШЕТ его: значит он зависит "
            "от среды, которую не контролирует, и его замер описывает "
            "конфигурацию, которой он не выбирал. Такие: %s" % silent)


def test_source_scan_ignores_artifact_copies_but_catches_another_real_reader(tmp_path, monkeypatch):
    content = 'import os\nos.getenv("KIR_SCRIPT_FIRST")\n'
    for relative in ("kir/schema_transport.py",
                     f"{SCRATCH_DIR}/frozen/kir/schema_transport.py",
                     "build/copy.py", "cache/copy.py", "venv/copy.py",
                     "tools/custom-env/copy.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (tmp_path / "tools/custom-env/pyvenv.cfg").write_text("home = synthetic\n", encoding="utf-8")
    monkeypatch.setattr(schema_transport, "__file__", str(tmp_path / "kir/schema_transport.py"))
    check = ScriptFirstSurface("test_the_flag_is_read_in_exactly_one_place")
    check.test_the_flag_is_read_in_exactly_one_place()
    # A legitimate product module named cache remains in scope.
    real = tmp_path / "kir/cache/another_reader.py"
    real.parent.mkdir()
    real.write_text(content, encoding="utf-8")
    with pytest.raises(AssertionError, match="another_reader"):
        check.test_the_flag_is_read_in_exactly_one_place()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
