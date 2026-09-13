"""IS THIS INTERPRETER FIT FOR THE SUITE — ASKED ONCE, AND OUT LOUD.

🔴 WHY IT WAS SET UP (01.09.2026). Within one shift, two independent
measurements declared the tree broken, when what was broken was the
LAUNCH:

    the system python3.12   shapely -> ~/.local/... (USER site)
    python3.12 -s           ModuleNotFoundError
    venv/bin/python -s      sees it

The sandbox calls the child with `[exe, "-s", "-B", "-c", ...]`
(`sandbox.py:1754`), and `-s` discards the user site DELIBERATELY: the
neighboring test `test_no_isolation_layer_was_relaxed` guards this
isolation, and it must not be weakened. So an interpreter whose permitted
library sits in the USER site rather than its own is NOT FIT for this
suite: the parent sees it, the child does not.

THE COST, MEASURED, NOT ASSUMED: seven reds in two files of author
libraries under the system python, and ZERO under the production venv.
On top of that, the shift's overall count of "34 real reds" turned out to
be inflated twofold — for the same reason.

🔴 WHY THIS WASN'T CAUGHT. Each of the seven refusals was HONEST and named
its cause verbatim ("the library is PERMITTED, but NOT INSTALLED in this
environment"). An honest refusal looks like the instrument working
correctly, and so it gets read as a fact ABOUT THE TREE. What was missing
was not text but ONE PLACE where the question is asked BEFORE the run, and
just once.

WHAT THIS TEST DOES NOT DO

  * it does not fix `-s` and does not touch the allowlist: the isolation is
    correct, and it is guarded separately;
  * it does not skip itself silently when the library is absent EVERYWHERE.
    That is a legitimate case (a bare machine belonging to a stranger), and
    then the parent does not see it either — there is no discrepancy, and
    so there is no finding;
  * it does not answer "is there a defect in the tree." It answers the
    prior question: "can this run be trusted at all."

🔴 WHAT IS WEAK HERE, AND NAMED HONESTLY: the test prints a NAMED red, but
it is still red — while the correct outcome is a third one, "the
measurement did not take place," which in pytest is expressed by an exit
code, not by a test. A session-level failure (`pytest.UsageError`, code 4)
would do this cleanly; it is DELIBERATELY not set up today, because four
forks were running in the tree in parallel and such a failure would cut
their runs short. The decision is left to the lead of the next shift.
"""
from __future__ import annotations

import subprocess
import sys
import unittest

from kir import sandbox


def _видит(exe: str, модуль: str, изолированно: bool) -> bool:
    """Whether THIS interpreter sees the module — with isolation or
    without.

    Asked by EXECUTING a separate process, not by `importlib.util.find_spec`
    in this one: `-s` changes `sys.path` AT STARTUP, and its effect cannot
    be reproduced inside an already-running process.
    """
    argv = [exe, "-s"] if изолированно else [exe]
    argv += ["-c", f"import {модуль}"]
    return subprocess.run(argv, capture_output=True, timeout=120).returncode == 0


class ИнтерпретаторГоденДляПесочницы(unittest.TestCase):

    def test_дитя_песочницы_видит_то_же_что_родитель(self):
        расхождение = []
        for модуль in sandbox.GEOMETRY_IMPORTS:
            родитель = _видит(sys.executable, модуль, изолированно=False)
            дитя = _видит(sys.executable, модуль, изолированно=True)
            if родитель and not дитя:
                расхождение.append(модуль)

        self.assertEqual(
            расхождение, [],
            "🔴 ЭТОТ ИНТЕРПРЕТАТОР НЕ ГОДЕН ДЛЯ НАБОРА, И ЭТО ФАКТ О ЗАПУСКЕ, "
            f"А НЕ О ДЕРЕВЕ.\n\n  интерпретатор : {sys.executable}\n"
            f"  видит родитель, НЕ видит дитя песочницы: {', '.join(расхождение)}\n\n"
            "Песочница зовёт дитя с `-s` (изоляция УМЫШЛЕННА, её стережёт "
            "test_no_isolation_layer_was_relaxed), а эти библиотеки лежат в "
            "ПОЛЬЗОВАТЕЛЬСКОМ site, который `-s` выбрасывает. Каждый тест, "
            "чей скрипт их импортирует, покраснеет ЧЕСТНЫМ KIR-B004 — и это "
            "будет красное о ЗАПУСКЕ, а не о коде.\n\n"
            "СЛЕДУЮЩИЙ ХОД: гнать интерпретатором, у которого зависимости "
            "лежат в СВОЁМ site. На этой машине это venv хозяина:\n"
            "  PYTHONPATH=/opt/kir /opt/kukai-rebuild1/backend/venv/bin/python "
            "-m pytest -q -p no:randomly <пути>\n"
            "У чужого человека это его собственный venv после "
            "`pip install kir-building` — там расхождения нет по построению.")

    def test_контроль_вопрос_не_вырожден(self):
        """🔴 A GATE THAT CANNOT GO RED GUARDS NOTHING.

        The assertion above is also green when there is nothing to ask
        about: an empty list of modules would give an empty discrepancy.
        What is checked here is that the subject of the question is
        non-empty, and that the probe itself DISTINGUISHES its own
        outcomes.
        """
        self.assertTrue(sandbox.GEOMETRY_IMPORTS,
                        "список библиотек пуст — вопрос выше вакуумен")
        # `sys` exists for any interpreter, `-s` included; a nonexistent
        # module exists in neither. The probe must distinguish these two
        # cases.
        self.assertTrue(_видит(sys.executable, "sys", изолированно=True))
        self.assertFalse(
            _видит(sys.executable, "модуля_такого_нет_ни_у_кого", изолированно=True),
            "проба отвечает ДА на несуществующий модуль — она сломана, и все "
            "её ответы выше ничего не значат")


if __name__ == "__main__":
    unittest.main()
