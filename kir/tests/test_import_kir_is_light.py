"""THE PACKAGE DOES NOT DRAG IN THE COMPILER — ASKED VIA EXECUTION, NOT
TRAVERSAL.

🔴 WHY THIS WAS STARTED (02.09.2026). `kir/__init__.py` imported `compiler`,
`midend`, `schema_gen`, `spec` with ordinary imports, and `import kir` loaded
THIRTY-EIGHT modules. The cost was not in milliseconds but in LAYERING:
anyone touching anything at all inside `kir/` executed a compiler load.
Three packages carried an apology in their headers — "we import nothing at
module level because `kir/__init__` drags in the compiler" (`live`,
`viewer`, `course`) — meaning the layering was held together by NEIGHBORS'
POLITENESS, not by design.

WHAT THIS TEST DOES NOT ASSERT. It does not say there is no path to the
compiler: the path exists and must exist — `from kir import compile_program`
works, the module simply loads at the moment of DEMAND. The import
traversal (`capability_graph`) still sees this edge, and sees it correctly;
what is asked here is a different quantity — whether the path EXECUTES on
its own.

WHY A SEPARATE PROCESS. In the current one, the compiler is already imported
by the suite itself, and "does it load" is indistinguishable from "is it
already loaded." The measurement window must start from a clean interpreter
— otherwise the test answers about the suite, not about the package.
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

TREE = Path(__file__).resolve().parents[2]

#: The public door: the names that must remain openable after decoupling.
#: The list is NOT handwritten — it is taken from the package itself, so as
#: not to become a second carrier of the same quantity.
_DOOR = "from kir import _PUBLIC; print(' '.join(sorted(_PUBLIC)))"


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, env={"PYTHONPATH": str(TREE),
                                          "PATH": "/usr/bin:/bin"})


class ImportingThePackageIsLight(unittest.TestCase):

    #: The ceiling is ASSIGNED, not measured, and named as such: today
    #: `import kir` loads EXACTLY ONE module (the package itself). Headroom
    #: up to five is left for future cheap neighbors (e.g., a version
    #: declaration), but not for the compiler: any of the solvers is caught
    #: by a separate assertion below, BY NAME.
    CEILING = 5

    def test_import_kir_loads_at_most_the_ceiling(self) -> None:
        out = _run("import sys, kir;"
                   "print(len([m for m in sys.modules "
                   "if m=='kir' or m.startswith('kir.')]))")
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        loaded = int(out.stdout.strip())
        self.assertLessEqual(loaded, self.CEILING,
                             f"`import kir` грузит {loaded} модулей при потолке "
                             f"{self.CEILING}: пакет снова тянет соседей")

    def test_import_kir_loads_no_decider(self) -> None:
        """A solver, named explicitly, is a stronger red than a mere number."""
        out = _run(
            "import sys, kir;"
            "d={'kir.compiler','kir.ground','kir.authoring','kir.midend',"
            "'kir.emit_model','kir.serving','kir.sandbox','kir.dsl','kir.macros',"
            "'kir.authoring_validation','kir.schema_gen','kir.spec'};"
            "print(sorted(set(sys.modules)&d))")
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip(), "[]",
                         f"`import kir` загрузил решателей: {out.stdout.strip()}")

    def test_the_public_door_still_opens(self) -> None:
        """Decoupling has no right to cost a single public name."""
        names = _run(_DOOR)
        self.assertEqual(names.returncode, 0, names.stderr[-2000:])
        public = names.stdout.split()
        self.assertIn("compile_program", public)
        out = _run("from kir import " + ", ".join(public) + "; print('ok')")
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertEqual(out.stdout.strip(), "ok")

    def test_an_unknown_name_refuses_like_python_does(self) -> None:
        """The refusal for an unknown name is the language's own, not our
        second dictionary."""
        out = _run("import kir\n"
                   "try:\n"
                   "    kir.нет_такого_имени\n"
                   "except AttributeError as e:\n"
                   "    print('ОТКАЗ', e)\n")
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        self.assertIn("has no attribute", out.stdout)


if __name__ == "__main__":
    unittest.main()
