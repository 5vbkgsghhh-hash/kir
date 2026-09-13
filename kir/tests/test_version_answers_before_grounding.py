"""THE VERSION EXPLAINS THE EMPTY POOL — SO IT ANSWERS FIRST.

Found by a live run on 2026-08-13 on Revit 2023: `create_topography
variety=toposolid` answered with `KIR-G104` "toposolid_types: empty in the
model," even though the compiler KNEW the truth — `KIR-E003` about the
version stood in the emission, and pool grounding runs earlier. The refusal
that fired first won.

The cost is not inaccuracy but the INFEASIBILITY of the advice: "empty in
the model" reads as "define a type," and the LLM went off to define a
toposolid type on a version where toposolids do not exist at all. KIR's main
user is not a human but a model; it will not guess.

Both halves stand side by side ON PURPOSE: without the second, the check
would be green by construction for any op that does not compile at all.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program
from kir.ops_site import TOPOSOLID_MIN_VERSION

_POINTS = [[0, 0, 0], [8000, 0, 0], [8000, 6000, 0], [0, 6000, 500]]


def _prog(variety: str = "toposolid") -> dict:
    return {"ir_version": "1.0", "intent": "ось версий", "ops": [
        {"op": "create_topography", "id": "T1", "variety": variety,
         "points_mm": _POINTS,
         "level": {"by": "element_id", "value": 42}}]}


def _codes(out) -> list[str]:
    return [d.code for d in (out.diagnostics or [])]


class VersionAnswersBeforeTheEmptyPool(unittest.TestCase):

    def test_below_the_threshold_the_version_answers_and_the_pool_is_silent(
            self) -> None:
        # WITHOUT a snapshot and WITHOUT a pinned type — exactly the input on
        # which "empty in the model" arrived live.
        for ver in ("2021", "2022", "2023"):
            with self.subTest(ver=ver):
                out = compile_program(_prog(), revit_version=ver,
                                      query_id="t")
                self.assertFalse(out.ok)
                codes = _codes(out)
                self.assertIn("KIR-E003", codes,
                              f"версия промолчала на {ver}: {codes}")
                self.assertNotIn("KIR-G104", codes,
                                 "пустой пул снова отвечает вперёд версии")

    def test_with_a_real_snapshot_the_empty_pool_still_does_not_answer_first(
            self) -> None:
        """A LIVE CONDITION FROM 08.13: a snapshot EXISTS, and the pool is
        empty — and it is empty not because no type was defined in the
        document, but because on this version toposolids do not occur at
        all. This is exactly where `KIR-G104` used to arrive."""
        # The snapshot is assembled HERE, not imported from a neighboring
        # test: that one sets `KIR_REJECTIONS_PATH` on import, and this
        # conftest's environment guard rightly catches the leak. Exactly two
        # fields are needed here.
        snap = {
            "__document_fingerprint": {
                "title": "KIR Test Model",
                "path_name": "C:\\models\\kir-test.rvt",
                "project_uid": "kir-test-project-uid"},
            "levels": [{"id": 42, "name": "Этаж 1", "elevation_mm": 0.0}],
            "toposolid_types": [],
        }

        out = compile_program(_prog(), revit_version="2023",
                              snapshot=snap, query_id="t")
        codes = _codes(out)
        self.assertIn("KIR-E003", codes, f"версия промолчала: {codes}")
        self.assertNotIn("KIR-G104", codes,
                         "«пусто в модели» снова отвечает вперёд версии")

        # And the control-FAIL of this same half: on 2026 the same empty pool
        # MUST answer on its own — there, emptiness is a fact about the
        # document, not about the version, and substituting the version for
        # it would be exactly the same lie in reverse.
        out26 = compile_program(_prog(), revit_version="2026",
                                snapshot=snap, query_id="t")
        codes26 = _codes(out26)
        self.assertNotIn("KIR-E003", codes26)
        self.assertTrue(
            any(c.startswith("KIR-G") for c in codes26),
            f"на 2026 пустой пул обязан отказать сам: {codes26}")

    def test_the_refusal_names_the_version_and_the_next_move(self) -> None:
        out = compile_program(_prog(), revit_version="2023", query_id="t")
        msg = next(d.message_ru for d in out.diagnostics
                   if d.code == "KIR-E003")
        self.assertIn("2023", msg)              # ITS version, not an abstract one
        self.assertIn(TOPOSOLID_MIN_VERSION, msg)
        # The next move is named, and named as a DIFFERENT element, not a
        # replacement.
        self.assertIn("surface", msg)

    def test_at_and_above_the_threshold_the_version_says_NOTHING(self) -> None:
        # Control-FAIL of the check: without it, it would be green for any op
        # that simply does not compile.
        for ver in ("2024", "2025", "2026"):
            with self.subTest(ver=ver):
                out = compile_program(_prog(), revit_version=ver,
                                      query_id="t")
                self.assertNotIn("KIR-E003", _codes(out),
                                 f"версия отказала там, где толща законна"
                                 f" ({ver})")

    def test_the_other_variety_is_untouched_on_every_version(self) -> None:
        # `surface` lives on all six; the guard must not touch it.
        for ver in ("2021", "2023", "2026"):
            with self.subTest(ver=ver):
                self.assertNotIn(
                    "KIR-E003",
                    _codes(compile_program(_prog("surface"),
                                           revit_version=ver, query_id="t")))


class TheGuardLivesWithItsThreshold(unittest.TestCase):
    """The threshold and the refusal live in one place; two call sites, zero
    copies of the text."""

    def test_the_emitter_does_not_carry_its_own_copy_of_the_message(
            self) -> None:
        import inspect
        from kir import site_emit
        src = inspect.getsource(site_emit)
        self.assertEqual(
            src.count("тип появился только"), 0,
            "текст отказа снова размножен по эмиттеру")

    def test_the_snapshot_builder_says_why_it_compares_by_name(self) -> None:
        # Without this note, the next reader will replace the string with
        # typeof out of tidiness and break the snapshot on three of the six
        # versions.
        import inspect
        from kir import open_model
        src = inspect.getsource(open_model)
        head = src[:src.index('__AddPool("toposolid_types"')]
        self.assertIn("typeof(ToposolidType)", head[-1200:],
                      "у строковой сверки не сказано, почему она строковая")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
