"""A PROBE TURN IS A THIRD KIND OF ANSWER, NOT A REFUSAL.

WHAT BOUGHT THIS, WITH FULL PROVENANCE.

A measurement on 17.08.2026 (overnight bench, three wings): the
language's door was approached **463 times**, and `KIR-B007` accounted
for **176 of them, 38 %**, the language's most expensive refusal by a
factor of five (the runner-up gives 36). The program came out legitimate
in only 33 % of cases.

A RE-MEASUREMENT on 18.08.2026, tree `prod-live` @ `08552c99`,
interpreter `backend/venv/bin/python` (3.12.13). The corpus is **627
scripts** written by the subject on the overnight bench
(`/home/claude/night/work*/**/*.py`, machine-local), run through the
REAL `execute_author_script`, not through the internals:

    total scripts                 627
    assembled a program           171
    KIR-B007                      365   (every single one kind=EmptyProgram)
    KIR-B006 (exception)           78   ← most have `model.*` with no catalog
    KIR-B004 / B005                13

    of the 365 B007 refusals:
      PRINTED a response          357   97.8 %   median print 1791 characters
      STAYED SILENT                 8    2.2 %

All eight that stayed silent are deliberately cleaned-up drafts, whose
OWN text says exactly that ("scratch file, not a program", «черновик
разведки, не часть здания»). That is, real authorial failures in the
`KIR-B007` basket number **zero**, and `kind=NoOps` did not occur even
ONCE across the whole corpus.

🔴 THE BOUNDARY OF THIS MEASUREMENT, NAMED, NOT DISCOVERED LATER. The
corpus was run WITHOUT a document catalog, so a probe that asks
`model.levels()` raises an exception and goes into `KIR-B006` even
BEFORE the program is assembled. Live, where a catalog is supplied,
these turns would have landed in B007 — meaning the share of probes
among B007 here is UNDERSTATED, not overstated. The direction of the
bias is known, its size is not.

THE DISCRIMINATOR IS PRINTING, AND IT HAS BOTH HALVES (otherwise this is
a control that is green by construction — form 8). The signal "the
script touched `model`/`spec`" was the first idea and was REFUTED BY
MEASUREMENT: such a turn never reaches the point of assembly. What is
observed is exactly "it answered", and that is also the only thing that
gives the MODEL anything: an answer nobody printed does not exist for
the next turn.
"""
from __future__ import annotations

import unittest

from kir.diag import SANDBOX_NO_OPS, SANDBOX_RECON
from kir.sandbox import execute_author_script
from kir.outcome import AcceptanceState, ExecutionState, WitnessState
from kir import serving


#: Turns that ASKED and printed an answer.
RECON = {
    "спросил контракт опа": 'print(spec("create_wall"))',
    "напечатал два контракта": 'print(spec("create_wall"))\nprint(spec("create_level"))',
    "посчитал и напечатал": 'xs = [i * 500 for i in range(4)]\nprint("XS:", xs)',
}

#: Turns that did NOT build and did NOT ask. Must remain a refusal.
SILENT = {
    "арифметика в стол": "x = 1 + 1",
    "голый комментарий": "# ничего",
    "присвоение без печати": 'note = "черновик"',
}


def _run(source: str):
    return execute_author_script(source)


class РазведкаОтличаетсяОтПустоты(unittest.TestCase):
    """BOTH HALVES, and the second matters more than the first."""

    def test_разведка_получает_свой_код_а_не_отказ(self):
        for name, src in RECON.items():
            with self.subTest(name):
                r = _run(src)
                self.assertFalse(r.ok, "разведка не строит — зелёной быть не может")
                self.assertIsNotNone(r.refusal)
                self.assertEqual(
                    r.refusal.code, SANDBOX_RECON,
                    f"{name}: скрипт напечатал {len(r.stdout or '')} символов — "
                    f"это ответ на заданный вопрос, а не неудача")
                self.assertEqual(r.refusal.kind, "Reconnaissance")
                self.assertTrue((r.stdout or "").strip(),
                                "разведка обязана нести свою печать наружу")

    def test_молчаливая_пустота_остаётся_отказом(self):
        """FAIL CONTROL. Without this half, the discriminator is green by construction."""
        for name, src in SILENT.items():
            with self.subTest(name):
                r = _run(src)
                self.assertFalse(r.ok)
                self.assertEqual(
                    r.refusal.code, SANDBOX_NO_OPS,
                    f"{name}: ход не построил и не спросил — это отказ")
                self.assertEqual(r.refusal.kind, "EmptyProgram")
                self.assertEqual(r.stdout or "", "")

    def test_названная_структурная_причина_сильнее_ярлыка(self):
        """The `__main__` guard swallows the program — and this is more
        useful than the label "probe".

        The script BOTH prints AND hides construction behind the guard.
        The label "probe" would be formally correct and useless: what
        needs fixing is the guard, and the refusal must name exactly
        that.
        """
        src = ('print("считаю")\n'
               'def build():\n'
               '    create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], '
               'level={"by": "default"})\n'
               'if __name__ == "__main__":\n'
               '    build()\n')
        r = _run(src)
        self.assertFalse(r.ok)
        self.assertEqual(r.refusal.code, SANDBOX_NO_OPS)
        self.assertEqual(r.refusal.kind, "NoOps")
        self.assertIn("__main__", r.refusal.message_ru)

    def test_программа_по_прежнему_собирается(self):
        """The fork must not touch the path where the program EXISTS."""
        r = _run('create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], '
                 'level={"by": "default"})')
        self.assertTrue(r.ok, "рабочий скрипт обязан остаться рабочим")
        self.assertEqual(len(r.ops or []), 1)


class РазведкаНеОшибкаНаВЫХОДЕ(unittest.TestCase):
    """The gate: `refused` is false, `err` is not set, green does not leak through."""

    def _result(self, source: str) -> dict:
        r = _run(source)
        receipt = serving._authorship_receipt(r, source_bytes=len(source))
        return serving._script_refusal_result(r.refusal, receipt)

    def test_разведка_не_отказ_и_несёт_свой_признак(self):
        res = self._result('print(spec("create_wall"))')
        self.assertIs(res["refused"], False, "разведка — не отказ")
        self.assertIs(res["recon"], True)
        self.assertIs(res["ok"], False, "и всё же НЕ зелёное: улики записи нет")
        self.assertIn("stdout", res["program_source"],
                      "ответ обязан доехать до модели")

    def test_пустота_остаётся_отказом_на_выходе(self):
        """FAIL CONTROL for the second half, already at the gate."""
        res = self._result("x = 1 + 1")
        self.assertIs(res["refused"], True)
        self.assertNotIn("recon", res)

    def test_блок_err_разведке_не_ставится(self):
        """The table's default would declare it `kir.program_refused` SILENTLY."""
        res = serving._stamp_refusal(self._result('print(spec("create_wall"))'))
        self.assertNotIn("err", res,
                         "разведка не ошибка — таксономия ошибок к ней не "
                         "применяется")

    def test_отказу_блок_err_ставится(self):
        """The second half: the structural ban did not break the common path."""
        res = serving._stamp_refusal(self._result("x = 1 + 1"))
        self.assertIn("err", res)
        self.assertTrue(res["err"].get("code"))

    def test_исход_остаётся_НЕ_НАЧАТЫМ_а_не_новой_осью(self):
        """All three axes of `ProgramOutcome` are about EXECUTION that did not happen."""
        res = self._result('print(spec("create_wall"))')
        outcome = res["outcome"]
        self.assertEqual(outcome["execution"], ExecutionState.NOT_STARTED.value)
        self.assertEqual(outcome["witness"], WitnessState.NOT_RUN.value)
        self.assertEqual(outcome["acceptance"], AcceptanceState.NOT_RUN.value)


if __name__ == "__main__":
    unittest.main()
