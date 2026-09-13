"""THE PACKAGE HAS A DOOR, AND EVERY ONE OF ITS COMMANDS OPENS.

🔴 WHAT IS BEING PINNED DOWN, AND WHY THIS IS NOT A TEST FOR THE TEST'S SAKE.
On 04.09.2026 the package gained `kir/__main__.py` and `[project.scripts]
kir`. Measurement of the entry point before that:

    [project.scripts]                  EMPTY — not a single command
    kir/__main__.py                    DID NOT EXIST
    public names in kir/__init__.py    9

This file is the CONSEQUENCE of that change, and it asks exactly the
properties that change promised an outside person. Each of them has already
broken somewhere else in this tree, and so is checked by a run, not by
reasoning:

  1. A SUBCOMMAND THAT HELP ADVERTISES MUST BE EXECUTABLE. The list is
     taken FROM THE PARSER ITSELF, not written here: a hand-written list
     would fall behind on the very first new command and stay silent about
     it. Advertising the unreachable is a known kind of defect in this
     tree ("a pointer and its reachability are one thing",
     `kir/course/__init__.py`).

  2. THE DEMO COMPILES WITHOUT A SNAPSHOT ON ALL VERSIONS. This is not
     decoration: `course.lessons.PLAN_DEMO_OPS` — the program on which the
     course shows the plan — is REJECTED by the compiler (`KIR-P003`: the
     registry calls for slot `xy`, the lesson writes `point_mm`), and this
     was only discovered when someone first tried to COMPILE it. A program
     printed to a person as a sample must be a sample.

  3. THE LOOP CLOSES. `kir demo --json` prints a program; `kir build` must
     accept that same program WITHOUT A SINGLE EXTRA ARGUMENT. Otherwise
     the outside person's first step after the demo is a refusal.

  4. THE RETURN CODE IS SPLIT BY MEANING. "The program was read and
     rejected" (1) and "there was nothing to read" (2) are different
     events, and collapsing them would mean saying "the program is bad"
     where there is no file at all.

WHAT THIS FILE DOES NOT CLAIM: nothing about behavior in Revit. The door
works without Revit, without a network, and without a single port — that
is its condition, not its limitation.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kir import __main__ as door
from kir import revit_version

TREE = Path(__file__).resolve().parents[2]


def _call(argv: list[str]) -> tuple[int, str, str]:
    """The door IN THIS process: return code and both streams, separately."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        код = door.main(argv)
    return код, out.getvalue(), err.getvalue()


def _subcommands() -> set[str]:
    """Subcommand names — AT THE PARSER, not from a list next to it."""
    for action in door.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return set(action.choices)
    raise AssertionError("у разборщика двери нет ни одной подкоманды")


class EveryAdvertisedCommandRuns(unittest.TestCase):
    """Every help command has an executable example."""

    #: The argument for each command. The keys are cross-checked against the
    #: parser by the test below, so a new command without an argument turns
    #: the suite red instead of slipping through silently.
    ДОВОДЫ: dict[str, list[str]] = {
        "demo": ["demo"],
        "ops": ["ops"],
        "skill": ["skill"],
        "course": ["course"],
        "doctor": ["doctor"],
        "build": [],          # its own check below: it needs a file
        "project": [],        # the file and both actions: test_project_workflow.py
        # 🔴 A FOREIGN COMMAND, ADDED BY MEASUREMENT, NOT FROM MEMORY (06.09.2026).
        # `connector` was set up by the Codex team; the table did not
        # follow it, and the file stood red (audit: C-6 / Y1-7 / Y4-3,
        # «три собственных теста волны красны»). Measurement —
        # `python -m kir --help`:
        #     connector  read-only discovery и контекст выбранной сессии
        # and `kir connector --help`: two actions, `list` and `context`.
        # There are NO arguments on purpose: both actions have required
        # parameters (a declarations directory, an exact session), and a
        # bare `kir connector` prints usage and answers with a NON-ANSWERED
        # code. Checking its content is the subject of that command's
        # owner, not of this pin: it guards the COMPLETENESS of the table,
        # i.e. "not a single package door was left unnamed."
        "connector": [],
        # 🔴 A FOREIGN DOOR, ADDED BY MEASUREMENT (07.09.2026). `capture` is
        # declared in the parser, but it is PARSED by
        # `kir.decompile.capture_api`: the tail goes there untouched, and
        # the return codes are its own too (refusal = 2, not REFUSED).
        # There are no arguments on purpose: a bare `kir capture` prints
        # the foreign parser's usage and answers with a NON-ANSWERED code.
        # Checking its content is the subject of
        # `kir/tests/test_the_package_door_opens_a_capture.py`; this pin
        # guards the COMPLETENESS of the table, i.e. "the door is named."
        "capture": [],
    }

    def test_the_table_below_covers_exactly_the_parser(self) -> None:
        self.assertEqual(set(self.ДОВОДЫ), _subcommands())

    def test_every_command_answers_and_prints_something(self) -> None:
        for имя, argv in self.ДОВОДЫ.items():
            if not argv:
                continue
            with self.subTest(команда=имя):
                код, вывод, _ = _call(argv)
                self.assertEqual(код, door.ANSWERED,
                                 f"«kir {имя}» не ответила")
                self.assertGreater(len(вывод), 200,
                                   f"«kir {имя}» напечатала пустоту")

    def test_a_named_op_prints_its_registry_contract(self) -> None:
        код, вывод, _ = _call(["ops", "create_wall"])
        self.assertEqual(код, door.ANSWERED)
        # The contract is printed IN FULL: the terminal has no sandbox
        # channel, and the tolerances and the postcondition stand AT THE
        # END (the argument is at `course._CUT_FMT`).
        self.assertIn("ПОСТУСЛОВИЕ", вывод)
        self.assertNotIn("ОБРЕЗАНО", вывод)

    def test_an_unknown_op_refuses_with_candidates(self) -> None:
        код, _, сводка = _call(["ops", "create_stenka"])
        self.assertEqual(код, door.NOT_DONE)
        self.assertIn("KIR-P002", сводка)
        self.assertIn("create_stairs", сводка)     # closest by wording

    def test_an_unknown_lesson_refuses_and_lists_the_topics(self) -> None:
        код, _, сводка = _call(["course", "стенка"])
        self.assertEqual(код, door.NOT_DONE)
        self.assertIn("вердикт", сводка)           # theme from ORDER


class TheDemoIsAnActualBuilding(unittest.TestCase):
    """A sample that does not compile is a promise, not a sample."""

    def test_it_compiles_on_every_supported_version_without_a_snapshot(self):
        from kir import compile_program

        for версия in revit_version.supported():
            with self.subTest(revit=версия):
                out = compile_program(door.demo_program(), revit_version=версия)
                self.assertTrue(
                    out.ok,
                    "демонстрация отказала: "
                    + ", ".join(d.code for d in out.diagnostics))
                self.assertGreater(len(out.csharp), 10_000)

    def test_no_slot_of_it_needs_a_document_snapshot(self) -> None:
        """KIR-G103 is a legal refusal, but it turns an outside person's
        first command into a refusal. The demo must manage without a
        snapshot."""
        from kir import compile_program

        out = compile_program(door.demo_program(), snapshot=None)
        self.assertNotIn("KIR-G103", [d.code for d in out.diagnostics])

    def test_the_verdict_of_the_demo_is_the_point_of_the_demo(self) -> None:
        """The judge must SPEAK UP about the demo, not stay silent.

        A rule's silence is indistinguishable from its consent — this tree
        has already paid for that (`course.design_check`). Here the
        speaking up is checked concretely: a room without a window fails
        HAB030.
        """
        текст = door._verdict_text(door.demo_program())
        self.assertIn("HAB030", текст)
        self.assertIn("НЕПРИГОДЕН", текст)


class TheShownSourceIsTheSourceThatRan(unittest.TestCase):
    """The source shown and the source executed are ONE carrier.

    🔴 WHY EXACTLY THIS (measured 04.09.2026, an outside person's path in a
    clean venv on a package FROM THE NETWORK):

        via `kir.sdk` — what the README recommends   17 turns, 3 hints
        via `kir.dsl` — documented nowhere            6 turns, refusals ZERO

    The demo must show the SHORT road, and show it in exactly the form it
    was executed: a second copy of these nine lines would silently diverge
    from what actually runs, and a person would be copying something that
    does not work.
    """

    def test_the_printed_source_is_valid_python_on_its_own(self) -> None:
        исходник = door._author_source()
        # `return` outside a function is a syntax error; the snippet must
        # compile IN A FOREIGN FILE, not only inside ours.
        compile(исходник, "<kir demo>", "exec")

    def test_it_is_written_through_the_short_road(self) -> None:
        исходник = door._author_source()
        self.assertIn("from kir.dsl import", исходник)
        # Not a single raw selector: the language fills the level slot
        # ITSELF, and it was exactly on this one that a raw path cost three
        # refusals in a row.
        self.assertNotIn('"by"', исходник)

    def test_the_language_filled_the_level_slot_itself(self) -> None:
        """The property this road was chosen for is checked concretely."""
        ops = door.demo_program()["ops"]
        уровни = [o["level"] for o in ops if "level" in o]
        self.assertTrue(уровни, "ни один оп демонстрации не адресует уровень")
        for селектор in уровни:
            self.assertEqual(селектор["by"], "ref")

    def test_authoring_twice_gives_the_same_program(self) -> None:
        """`kir.dsl` accumulates the program inside the module; the door
        must start from zero.

        Otherwise a second call in one process (and `kir demo` calls
        authoring both to print and to measure the doctor) would give
        fourteen ops instead of seven — and nobody would notice.
        """
        self.assertEqual(door.demo_program(), door.demo_program())


class TheCircleCloses(unittest.TestCase):
    """`kir demo --json` -> a file -> `kir build` without a single extra argument."""

    def test_demo_json_is_a_program_build_accepts(self) -> None:
        код, программа_json, _ = _call(["demo", "--json"])
        self.assertEqual(код, door.ANSWERED)
        программа = json.loads(программа_json)
        self.assertEqual(программа, door.demo_program())

        with tempfile.TemporaryDirectory() as каталог:
            файл = Path(каталог) / "дом.kir.json"
            файл.write_text(программа_json, encoding="utf-8")
            код, csharp, сводка = _call(["build", str(файл)])
        self.assertEqual(код, door.ANSWERED, сводка)
        self.assertIn("UnitUtils.ConvertToInternalUnits", csharp)
        # THE SUMMARY IN `stderr`, THE SUBJECT IN `stdout`: `kir build … > дом.cs`
        # must give a C# file, not a C# file with a summary in its header.
        self.assertNotIn("ПРИНЯТО", csharp)
        self.assertIn("ПРИНЯТО", сводка)


class ExitCodesAreSeparatedByMeaning(unittest.TestCase):
    """"The program was rejected" and "there was nothing to read" are different events."""

    def test_a_missing_file_is_not_a_refused_program(self) -> None:
        код, _, сводка = _call(["build", "/нет/такого/файла.json"])
        self.assertEqual(код, door.NOT_DONE)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", сводка)

    def test_broken_json_names_the_place(self) -> None:
        with tempfile.TemporaryDirectory() as каталог:
            файл = Path(каталог) / "битый.json"
            файл.write_text('{"ops": [', encoding="utf-8")
            код, _, сводка = _call(["build", str(файл)])
        self.assertEqual(код, door.NOT_DONE)
        self.assertIn("не JSON", сводка)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", сводка)

    def test_a_refused_program_returns_one_and_names_the_code(self) -> None:
        программа = {"ops": [{"op": "create_wall", "id": "w",
                              "p0_mm": [0, 0], "p1_mm": [6000, 0],
                              "height_mm": 3000,
                              "level": {"by": "name", "value": "Этаж 1"}}]}
        with tempfile.TemporaryDirectory() as каталог:
            файл = Path(каталог) / "отказ.json"
            файл.write_text(json.dumps(программа, ensure_ascii=False),
                            encoding="utf-8")
            код, csharp, сводка = _call(["build", str(файл)])
        self.assertEqual(код, door.REFUSED)
        self.assertEqual(csharp, "")               # C# is not printed at all
        self.assertIn("KIR-G103", сводка)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", сводка)     # carried by the diagnostic itself

    def test_an_unsupported_revit_version_is_not_a_refused_program(self) -> None:
        with tempfile.TemporaryDirectory() as каталог:
            файл = Path(каталог) / "дом.kir.json"
            файл.write_text(json.dumps(door.demo_program(), ensure_ascii=False),
                            encoding="utf-8")
            код, _, сводка = _call(["build", str(файл), "--revit", "2019"])
        self.assertEqual(код, door.NOT_DONE)
        self.assertIn("2026", сводка)              # list of supported ones


class TheDoorOpensFromAFreshInterpreter(unittest.TestCase):
    """`python -m kir` — not just `main()` in an already warmed-up process.

    In the current process half the package is already imported by the
    suite itself, and "does the door open" is indistinguishable from "is
    it already loaded". The measurement window must start from a clean
    interpreter.
    """

    def test_python_dash_m_kir_demo_builds_a_house(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "kir", "demo"],
            capture_output=True, text=True, cwd=str(TREE),
            env={"PYTHONPATH": str(TREE), "PATH": "/usr/bin:/bin",
                 "LANG": "C.UTF-8"})
        self.assertEqual(proc.returncode, door.ANSWERED, proc.stderr[-2000:])
        for версия in revit_version.supported():
            self.assertIn(версия, proc.stdout)
        self.assertIn("знаков C#", proc.stdout)
        self.assertIn("ВЕРДИКТ О ЗАМЫСЛЕ", proc.stdout)

    def test_bare_kir_prints_help_and_does_not_fail(self) -> None:
        """A question without a topic is not a refusal: a non-zero code
        here would fail other people's scripts exactly where nothing
        broke."""
        код, вывод, _ = _call([])
        self.assertEqual(код, door.ANSWERED)
        for имя in _subcommands():
            self.assertIn(имя, вывод)


class ThePackagingDeclaresTheCommand(unittest.TestCase):
    """`[project.scripts]` is the sole carrier of the command's name."""

    def test_pyproject_points_the_kir_command_at_this_module(self) -> None:
        pyproject = TREE / "pyproject.toml"
        if not pyproject.exists():           # an install without the tree — legal
            self.skipTest("pyproject.toml рядом с пакетом нет (установка)")
        import tomllib
        данные = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        scripts = данные["project"].get("scripts", {})
        self.assertEqual(scripts.get("kir"), "kir.__main__:main",
                         "команда `kir` не объявлена или ведёт не сюда")


if __name__ == "__main__":
    unittest.main()
