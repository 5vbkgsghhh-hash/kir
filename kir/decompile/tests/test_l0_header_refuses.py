"""THE L0 HEADER REFUSES TO IMPERSONATE THE DOCUMENT.

🔴 WHAT PAID FOR THIS FILE. The trap "`metadata()` hands back the header,
`elements` is empty BY CONSTRUCTION" is recorded verbatim in the root
`CLAUDE.md`, in the list of "CALL-SHAPE TRAPS". On 18.08.2026 it was stepped
on THREE TIMES IN ONE DAY — the topology wave, the honest-comparison
instrument, and the director, who had read this very list that same
morning:

    rooms 2442 · doors 0   on a building with 2096 doors
    rooms 2442 · walls 0   on a building with 15 323 walls

The answer looked WORKING, because the rooms do come through: they sit in
the header.

Run:
    venv/bin/python -m pytest kir/decompile/tests/test_l0_header_refuses.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.schema import L0HeaderMisread, UnloadedElements


class AHeaderWithACensusRefusesToBeRead(unittest.TestCase):
    """A non-empty census ⇒ "zero elements" is IMPOSSIBLE, and this is a
    refusal."""

    def setUp(self) -> None:
        self.elements = UnloadedElements(310_558, census_taken=True)

    def test_len_refuses(self):
        with self.assertRaises(L0HeaderMisread):
            len(self.elements)

    def test_iteration_refuses(self):
        with self.assertRaises(L0HeaderMisread):
            list(self.elements)

    def test_truthiness_refuses(self):
        """`if not document.elements:` — the quietest of the three ways."""
        with self.assertRaises(L0HeaderMisread):
            bool(self.elements)

    def test_the_refusal_names_the_census_and_the_next_move(self):
        try:
            len(self.elements)
        except L0HeaderMisread as exc:
            text = str(exc)
        else:  # pragma: no cover
            self.fail("отказа не было")
        self.assertIn("310558", text.replace(" ", ""),
                      "отказ обязан назвать ЧИСЛО, которое противоречит нулю")
        self.assertIn("iter_elements", text,
                      "отказ, не называющий СЛЕДУЮЩИЙ ХОД, не учит — а канон "
                      "требует, чтобы всякий отказ называл причину И что делать")


class AnEmptyDocumentPassesInSilence(unittest.TestCase):
    """🔴 THE REFUSAL CATCHES THE IMPOSSIBLE, NOT THE RARE.

    A document whose census is genuinely zero must be read silently:
    otherwise the guard would become a ban on a legitimate case — exactly
    what we criticize other people's thresholds for.
    """

    def setUp(self) -> None:
        # 🔴 "THE CENSUS WAS TAKEN" IS SAID EXPLICITLY, AND THAT IS THE
        # MEANING OF THIS CLASS. Before 25.08 this said `UnloadedElements(0)`,
        # and the rig read as "the document is empty" — even though, by the
        # law of the `census` field, an empty census means "there WAS NO
        # census". The test was holding the LEGITIMATE case (a census was
        # taken and counted zero), but was expressing it in a form that also
        # covered the illegitimate one: a snapshot without a census was
        # silent in exactly the same way.
        # There is no weakening here — there is precision: the case is the
        # same, it is now stated directly.
        self.elements = UnloadedElements(0, census_taken=True)

    def test_len_is_zero(self):
        self.assertEqual(len(self.elements), 0)

    def test_iteration_is_empty(self):
        self.assertEqual(list(self.elements), [])

    def test_it_is_falsy(self):
        self.assertFalse(self.elements)


class TheGuardIsOneAndItLivesInTheType(unittest.TestCase):

    def test_it_is_a_tuple_so_the_declared_shape_does_not_move(self):
        """The guard does not change the field's DECLARED type — only its
        silence."""
        self.assertIsInstance(UnloadedElements(1, census_taken=True), tuple)

    def test_the_header_built_by_the_reader_carries_the_guard(self):
        """Wire: the header of a real decompile carries the guard, not a bare
        tuple.

        This test's FAIL control was run by hand: return `"elements": []`
        in `_read_header` → the test goes red; return the guard → green.
        """
        import pathlib

        from kir.decompile.extract import L0JSONLReader

        run = (pathlib.Path(__file__).resolve().parents[4]
               / "backend/data/decompile/13a-rd-ar-k2_v33_kuklev.d.s/L0.jsonl")
        if not run.exists():
            self.skipTest("корпуса разборов нет на этой машине — не «прошло»")
        header = L0JSONLReader(run).metadata()
        self.assertIsInstance(header.elements, UnloadedElements)
        self.assertTrue(header.rooms, "комнаты обязаны быть: они и есть ловушка")
        with self.assertRaises(L0HeaderMisread):
            len(header.elements)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
