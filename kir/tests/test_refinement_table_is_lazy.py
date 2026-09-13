"""`translation_cert.REFINEMENT` IS EMPTY until the first access through the
accessor.

DEFECT CLASS: a value is ASSERTED in one place and READ in another, and
nothing forces them to agree. Here the assertion is the exported name
`REFINEMENT` in `__all__` and the module docstring's line "``REFINEMENT`` is
the machine form of the prose ``OpSpec.post``"; the read is the module-level
dict, which on a fresh interpreter holds ZERO entries and only fills as a
side effect of `_ensure_table()` (called by `certify_op`, `certify_program`,
`audit_registry_coverage`).

WHY THIS IS BAD SPECIFICALLY HERE. A direct reader does not get an error —
it gets EMPTY, i.e. "no obligations," which is indistinguishable from "the
op promises nothing." Measured 08-11 on a fresh process:

    from kir.translation_cert import REFINEMENT
    len(REFINEMENT)              -> 0
    REFINEMENT["create_wall"]    -> KeyError

The only direct reader in the tree was `tests/test_space.py` (the
create_space wave, 08-10). Under `pytest-randomly`, which shuffles order
DELIBERATELY, it passed or failed depending on whether something had
already called `certify_op` earlier. The test has been fixed to use the
accessor; this file holds the trap itself, so the next one does not start a
second reader of this kind.

WHY THE CHECK RUNS IN A SEPARATE PROCESS. Module state is global: clearing
it in this process would break neighboring tests under random ordering —
that is, fixing one instance of the defect class while starting another.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import unittest


def _fresh(code: str) -> str:
    # 🔴 THREE STEPS, NOT FOUR (2026-08-28). The fourth one led into `/opt`
    # — and `PYTHONPATH=/opt` made `import kir` resolve to the NAMESPACE
    # package `/opt/kir` (it has no `__init__.py`), which left `kir.spec`
    # partially initialized: "partially initialized module … circular
    # import." The failure looked like a cycle in OUR code, but it was the
    # run layout.
    root = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))
    env = dict(os.environ)
    env["PYTHONPATH"] = root
    env.setdefault("KIR_REJECTIONS_PATH", os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "kir_lazy_probe.jsonl"))
    out = subprocess.run([sys.executable, "-c", textwrap.dedent(code)],
                         capture_output=True, text=True, cwd=root, env=env)
    return (out.stdout + out.stderr).strip()


class TheTableIsEmptyUntilTouched(unittest.TestCase):

    def test_a_bare_import_sees_no_obligations_at_all(self):
        """Not an error but EMPTY — and that is worse: "no obligations" is
        indistinguishable from "the op promises nothing."""
        self.assertEqual(
            _fresh("""
                from kir.translation_cert import REFINEMENT
                print(len(REFINEMENT))
            """).splitlines()[-1], "0")

    def test_indexing_it_raises_rather_than_answering(self):
        self.assertIn("KeyError", _fresh("""
            from kir.translation_cert import REFINEMENT
            try:
                REFINEMENT["create_wall"]
                print("answered")
            except KeyError:
                print("KeyError")
        """).splitlines()[-1])

    def test_the_accessor_is_what_fills_it(self):
        last = _fresh("""
            from kir import translation_cert as tc
            before = len(tc.REFINEMENT)
            tc._ensure_table()
            print(before, len(tc.REFINEMENT))
        """).splitlines()[-1].split()
        self.assertEqual(last[0], "0")
        self.assertGreater(int(last[1]), 60)

    def test_no_test_in_the_tree_reads_the_bare_name(self):
        """There must be no second reader of this kind. The rule is narrow:
        indexing or iterating BY THE NAME `REFINEMENT` without
        `_ensure_table()` alongside it."""
        import pathlib
        import re
        # 🔴 THE WALK'S DENOMINATOR, MEASURED 2026-09-02: **397** `test_*.py`
        # files under this directory, excluding itself. The rule is narrow,
        # the expectation is EMPTY — meaning a walk that loses the tree
        # gives the same answer as a clean tree, and simply will not see
        # tomorrow's second reader.
        ТЕСТОВЫХ_ФАЙЛОВ_НЕ_МЕНЬШЕ = 300
        here = pathlib.Path(__file__).resolve().parent
        offenders = []
        прочитано = 0
        for path in sorted(here.rglob("test_*.py")):
            if path.name == pathlib.Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            прочитано += 1
            for m in re.finditer(r"\bREFINEMENT\s*\[", text):
                window = text[max(0, m.start() - 400):m.start()]
                if "_ensure_table()" not in window:
                    offenders.append("%s:%d" % (
                        path.name, text[:m.start()].count("\n") + 1))
        self.assertGreaterEqual(
            прочитано, ТЕСТОВЫХ_ФАЙЛОВ_НЕ_МЕНЬШЕ,
            f"обход прочёл {прочитано} тестовых файлов при поле "
            f"{ТЕСТОВЫХ_ФАЙЛОВ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 397). Это "
            f"заявление о ХОДОКЕ, а не о читателях")
        self.assertEqual(
            offenders, [],
            "читают REFINEMENT по голому имени (на свежем процессе он ПУСТ): "
            + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
