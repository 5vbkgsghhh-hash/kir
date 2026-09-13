"""THE METRIC ACCESSOR: THE MECHANISM WORKS, THE DOCSTRING'S PROMISE DOES NOT.

MEASURED 11.08.2026 — three facts, and each one cancels part of the
suspicion:

  1. THE MECHANISM IS ALIVE. `idempotence.json` sits alongside eight parses,
     the freshest, `sob62_fas_r23_v18`, from 29.07.2026: 44 keys of real
     data, `raw_exact_pct` 85.808, `multiset_match` False. Runs DID happen.
     (The archived note `docs/archive/NOTES_A5.md` says "no live run has
     been executed" — it is OLDER than the runs, just as the corpus was
     older than the `host_source` wave.)
  2. THE MEMORY-RESIDENT DICTIONARY CARRIES A CORRECTNESS PROPERTY, not just
     a value: `test_serving_idempotence.test_cleanup_failure_is_top_level_failure_and_
     not_dashboard_success` requires that `_last_idempotence` REMAIN EMPTY
     when cleanup fails. A run whose cleanup did not succeed must not appear
     on the panel as a success. Deleting the dictionary would lift this
     requirement.
  3. EXACTLY ONE THING IS NEVER CALLED — the two-line accessor
     `last_idempotence_metric()`. It costs zero (a copy of the dictionary on
     request), so the argument "more expensive than computing zero" does not
     apply to it.

SO WHAT IS ACTUALLY BROKEN. The docstring: "Dashboard hook: the last A5 run's
exact% and date (or None)" describes LIVE WIRING that does not exist — and
this is a neighboring family of our own class: an instrument that is easy to
believe works, because its name and docstring describe something that
doesn't exist.

AND A SECOND THING, WORSE THAN THE FIRST, AND THIS ONE IS ALREADY OUR CLASS.
The dictionary lives IN THE PROCESS'S MEMORY, while the artifact lives on
disk. After a restart, the accessor will return `None` even with eight
completed runs behind it. That is, `None` means TWO different facts AT ONCE:
"there were no runs in this process" and "there were never any runs at all."
Exactly the indistinguishability the whole marathon has been untangling: an
instrument's silence versus a clean result.

SO NEITHER WIRING IT UP NOR DELETING IT CAN BE DONE SILENTLY HERE. Deleting
it would remove the one NAMED read path (a consumer would have to reach into
the private dictionary). Wiring it up for real means deciding whether the
accessor reads the disk, and that needs a `doc_stamp`: there are eight
parses, and it takes no arguments. That would be a signature written for a
nonexistent consumer — a guess.

So what gets locked down here is EXACTLY WHAT WAS MEASURED: while there are
no callers, the docstring must say so; once a caller appears, the test will
force the docstring to be rewritten, rather than left carrying yesterday's
promise.
"""
from __future__ import annotations

import ast
import inspect
import os
import pathlib
import re
import tempfile
import unittest

import kir
from kir import serving as S



#: 🔴 THE SCRATCH DIRECTORY'S NAME, NOT A PATH (13.09.2026). The fixtures below
#: create a file inside a directory with this name to prove the scanner SKIPS it —
#: that is their whole subject, so the name cannot be dropped. Written as a bare
#: name because `test_no_test_reaches_outside_the_tree` reads a path-shaped
#: literal (`.work/…`) as a test reaching into the commit tree's own scratch
#: space. These fixtures never do: every path below is built under a temporary
#: directory, and the name is joined to it here.
SCRATCH_DIR = ".work"

_ROOT = pathlib.Path(kir.__file__).resolve().parent
#: Files where mentioning the name is NOT a call: the definition and this test.
_NOT_A_CALLER = {"serving.py", "test_idempotence_metric_wiring.py"}
#: The marker by which the docstring acknowledges the absence of a consumer.
_DISCLAIMER = "THERE IS NO CONSUMER"


#: 🔴 THE TRAVERSAL'S DENOMINATOR, MEASURED 02.09.2026: **981** `*.py` files
#: under the root. It stands INSIDE the traversal, not at the callers,
#: because both consumers of `_callers()` read its EMPTINESS as a fact about
#: the tree: the "no callers" branch demands that the docstring acknowledge
#: `NO CONSUMER` — and today it does. So a traversal that lost the tree
#: yields an empty list, falls into this branch, and GOES GREEN. That is
#: exactly how the emitter guard stayed green on 02.09.
_ФАЙЛОВ_ПОД_КОРНЕМ_НЕ_МЕНЬШЕ = 700


def _has_metric_call(source):
    """A call expression, including a normal imported alias, not quoted history."""
    tree = ast.parse(source)
    aliases = {"last_idempotence_metric"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {"kir.serving", "serving"}:
            aliases.update(alias.asname or alias.name for alias in node.names
                           if alias.name == "last_idempotence_metric")
    return any(isinstance(node, ast.Call) and (
        isinstance(node.func, ast.Name) and node.func.id in aliases or
        isinstance(node.func, ast.Attribute) and node.func.attr == "last_idempotence_metric")
        for node in ast.walk(tree))


def _scan_callers(root):
    """KIR package source inventory, with callers restricted to production code.

    The retained inventory floor counts readable package Python, including test
    sources; tests themselves do not establish a product consumer. External host
    callers are outside this scan and remain unknown, not certified absent.
    """
    hits: list[str] = []
    прочитано = 0
    excluded = {"build", "dist", "venv", "site-packages", "node_modules", "__pycache__"}

    def failed(error):
        raise error

    for directory, directories, files in os.walk(root, topdown=True, followlinks=False, onerror=failed):
        directories[:] = sorted(name for name in directories
                                if name not in excluded and not name.startswith(".")
                                and not pathlib.Path(directory, name).is_symlink())
        for name in sorted(files):
            path = pathlib.Path(directory, name)
            if path.suffix != ".py" or path.is_symlink() or name in _NOT_A_CALLER:
                continue
            text = path.read_text(encoding="utf-8")
            прочитано += 1
            relative = path.relative_to(root)
            if "tests" in relative.parts or name.startswith("test_"):
                continue
            if _has_metric_call(text):
                hits.append(str(relative))
    return sorted(hits), прочитано


def _callers() -> list[str]:
    """Known callers inside the imported KIR only; host wiring is not measured."""
    hits, прочитано = _scan_callers(_ROOT)
    assert прочитано >= _ФАЙЛОВ_ПОД_КОРНЕМ_НЕ_МЕНЬШЕ, (
        f"обход прочёл {прочитано} файлов при поле "
        f"{_ФАЙЛОВ_ПОД_КОРНЕМ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 981). Пустой "
        f"список вызывающих ниже был бы заявлением о ХОДОКЕ, а прочтён был "
        f"бы как факт о проводке")
    return hits


class TheDocstringMatchesTheWiring(unittest.TestCase):
    """Check the historical disclaimer against KIR wiring, not unknown external hosts."""

    def test_scope_is_the_imported_package_and_foreign_copies_cannot_be_callers(self):
        self.assertEqual(_ROOT, pathlib.Path(kir.__file__).resolve().parent)
        with tempfile.TemporaryDirectory(prefix="kir-metric-callers-") as directory:
            parent = pathlib.Path(directory)
            package = parent / "kir"
            files = {
                "kir/visible.py": "S.last_idempotence_metric()\n",
                "kir/alias.py": "from kir.serving import last_idempotence_metric as metric\nmetric()\n",
                "kir/history.py": '"S.last_idempotence_metric()"\n# last_idempotence_metric()\n',
                "kir/tests/test_consumer.py": "S.last_idempotence_metric()\n",
                "copy/kir/consumer.py": "S.last_idempotence_metric()\n",
                f"kir/{SCRATCH_DIR}/consumer.py": "S.last_idempotence_metric()\n",
                "kir/venv/lib/site-packages/kir/consumer.py": "S.last_idempotence_metric()\n",
            }
            for relative, text in files.items():
                path = parent / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            callers, inventoried = _scan_callers(package)
            self.assertEqual(callers, ["alias.py", "visible.py"])
            self.assertEqual(inventoried, 4)

    def test_the_docstring_admits_it_has_no_consumer(self):
        doc = inspect.getdoc(S.last_idempotence_metric) or ""
        if _callers():
            self.assertNotIn(
                _DISCLAIMER, doc,
                f"потребитель появился ({_callers()}), а докстринг всё ещё "
                f"говорит, что его нет")
        else:
            self.assertIn(
                _DISCLAIMER, doc,
                "вызывающих нет, а докстринг обещает живую проводку")

    def test_the_summary_line_no_longer_claims_a_hook(self):
        """What is checked is the FIRST LINE, not the whole text: a
        docstring must retain the right to quote a retracted promise while
        explaining what exactly was retracted. It is the summary line that
        asserts on the function's behalf."""
        doc = inspect.getdoc(S.last_idempotence_metric) or ""
        summary = doc.splitlines()[0] if doc else ""
        self.assertNotIn("hook", summary.lower())
        self.assertNotIn("Dashboard", summary)

    def test_the_restart_hole_is_named(self):
        """`None` after a restart and `None` when there were no runs are
        different facts, and while they remain indistinguishable, that must
        be WRITTEN DOWN."""
        doc = inspect.getdoc(S.last_idempotence_metric) or ""
        self.assertIn("idempotence.json", doc)
        self.assertIn("restart", doc.lower())


class TheMechanismItselfStaysAlive(unittest.TestCase):
    """There was NOTHING to delete: both the dictionary and the persistence
    carry real work."""

    def test_the_in_memory_summary_still_exists(self):
        self.assertIsInstance(S._last_idempotence, dict)

    def test_an_empty_metric_is_none_not_an_empty_dict(self):
        """`None` and `{}` are different answers; an empty dictionary would
        read as "a run happened and turned out empty."""
        saved = dict(S._last_idempotence)
        S._last_idempotence.clear()
        try:
            self.assertIsNone(S.last_idempotence_metric())
        finally:
            S._last_idempotence.update(saved)

    def test_the_accessor_hands_out_a_copy_not_the_dict(self):
        """Handing out the dictionary itself would let the reader mutate the
        metric."""
        saved = dict(S._last_idempotence)
        S._last_idempotence.clear()
        S._last_idempotence.update({"doc_stamp": "d", "raw_exact_pct": 1.0})
        try:
            out = S.last_idempotence_metric()
            out["doc_stamp"] = "подменено"
            self.assertEqual(S._last_idempotence["doc_stamp"], "d")
        finally:
            S._last_idempotence.clear()
            S._last_idempotence.update(saved)


if __name__ == "__main__":
    unittest.main()
