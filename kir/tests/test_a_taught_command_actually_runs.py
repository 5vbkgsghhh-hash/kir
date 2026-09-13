"""A COMMAND OFFERED AS READY-TO-USE IS OBLIGATED TO RUN.

WHAT HAPPENED (2026-08-29, a stranger's gate, Phase 6). The course offers
`course("приёмы")` as a ready-to-use command. In the author's script the name
is INJECTED by the sandbox, and there it is correct. For a reader outside the
sandbox — it is not:

    from kir import course     # this is a PACKAGE, not a function
    course("дом")              -> TypeError: 'module' object is not callable

The correct form `from kir.course import course` was written NOWHERE across
the whole tree: not in the canon, not in the course, not in the docstrings.
The defect hits the VERY FIRST step of learning — the reader simply never
gets to anything past it.

The most frustrating part is that the correct call gets an EXEMPLARY answer:
«УРОК „ДОМ“ НЕДОСТУПЕН: корпуса разборов нет на этой машине… без них урок стал бы
пересказом норм по памяти». The refusal was written correctly — it was just never reached.

The tree ALREADY has the law "everything the course shows as WORKING compiles
under a test" (`skill.py:753`). It covers KIR PROGRAMS and did not cover the
commands used to call the course itself. This file closes the second half.
"""
from __future__ import annotations

import unittest


class ATaughtCommandActuallyRuns(unittest.TestCase):

    def test_the_canon_names_where_course_lives(self) -> None:
        """The CANON is asked, not the instrument's permanent text.

        🔴 THE FIRST EDITION ASKED THE PERMANENT TEXT — and the fix made for
        it blew through its ceiling: 30,067 against 30,000, with 44
        characters of margin left. The ceiling is paid for on EVERY model
        turn, and the model runs INSIDE the sandbox, where the name is
        injected: it never needs the import. The one who needs it is the
        HUMAN reading the canon — that is where the line belongs.
        """
        import pathlib

        import kir
        canon = pathlib.Path(kir.__file__).resolve().parent / "CLAUDE.md"
        self.assertTrue(canon.is_file(), f"канон не найден: {canon}")
        text = canon.read_text(encoding="utf-8")
        self.assertIn(
            "from kir.course import course", text,
            "канон предлагает `course(...)` как команду и не говорит, откуда "
            "её взять вне песочницы — читатель получит TypeError на первом "
            "же шаге")

    def test_the_permanent_text_did_not_pay_for_it(self) -> None:
        """And the other side of it: the hint has NO RIGHT to sit in the permanent
        text. Its place there would be taken from something the model needs."""
        from kir.tool_doc import build_tool_description
        self.assertLess(len(build_tool_description()), 30_000)

    def test_the_named_form_is_the_one_that_works(self) -> None:
        """Writing the form is not enough — it is obligated to run."""
        from kir.course import course
        self.assertTrue(callable(course))

    def test_the_broken_form_is_still_broken_and_that_is_why_we_name_it(self) -> None:
        """🔴 THE TRAP IS PINNED DOWN ON PURPOSE.

        `kir/course/` is a package, so `from kir import course` gives a MODULE.
        If the package ever starts handing out a function, this test will go
        red and force a re-read of the course text: at that point both forms
        would become correct, and the caveat in the course would no longer be
        needed — instead of just silently going stale.
        """
        import kir.course as as_module
        self.assertFalse(callable(as_module),
                         "kir.course стал вызываемым — перечитай оговорку в "
                         "skill.py: она объясняет ловушку, которой больше нет")

    def test_the_package_can_name_its_own_version(self) -> None:
        """The version is the FIRST thing asked in an error report."""
        import kir
        self.assertTrue(getattr(kir, "__version__", ""),
                        "kir.__version__ пуст: пакет не умеет назвать себя")


if __name__ == "__main__":
    unittest.main()
