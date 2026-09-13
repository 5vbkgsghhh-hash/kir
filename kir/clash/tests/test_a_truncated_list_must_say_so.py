"""A LIST THAT LOOKS COMPLETE IS THE SAME LIE AS A SILENT ZERO (F-147).

`_build_move` was iterating over the bodies an element would enter
AFTER the move, and stopping at the eighth — the `break` was cutting
off not the print, but the COUNT. `Move` carried neither a total nor a
truncation mark, and the designer read

    «НО после переноса элемент входит в ТРЕТЬЕ тело … (тела: e0 … e7)»

understanding "eight." There were sometimes 357 of them.

🔴 CORPUS MEASUREMENT (77 buildings, a run of the actual
`_build_move`): 2,196 pairs with a confirmed shortfall across 53 of 77
buildings, a maximum of 357 true bodies against the declared EIGHT
(`k4_geom_wave2`). A dedicated check on two buildings, already with the
fix: `k4_geom_wave2` 5 truncated lists out of 243 moves, maximum 18;
`len_ar_me_r24_v1` 11 out of 293, maximum 40.

The number eight was, on top of that, sitting as a LITERAL DIGIT IN A
CONDITION — in a module where `BUDGET_FACTOR`, `BUDGET_FLOOR_MM`,
`MAX_CELLS_PER_HULL`, and `MAX_EXIT_PIECE_PAIRS` are declared and
justified right next to it. It is now `MAX_NAMED_HITS`, and it is about
the LENGTH OF THE PRINTED LINE, not about correctness: a ceiling on
PRINTING is lawful; a ceiling on the COUNT, passed off as the full
count, is not.

A neighboring module already holds the same law: `review.build_review`
names the cutoff with the field `elements_truncated_to` — "a truncated
list that looks complete is the same lie as a silent zero."
"""

from __future__ import annotations

import dataclasses
import textwrap
import unittest

from kir.clash import resolve as R


def _move(total: int, *, legal: bool = False) -> R.Move:
    """A move with `total` third bodies, named according to the
    module's rule."""
    named = tuple(f"e{i}" for i in range(min(total, R.MAX_NAMED_HITS)))
    return R.Move("p1", "труба", "OST_PipeCurves", (0., -1., 0.), 10.0,
                  (0., -10., 0.), True, legal,
                  blockers=("hits_third_body",) if total else (),
                  hits=named, hits_total=total,
                  hits_truncated=total > len(named))


def _line(move: R.Move) -> str:
    return R.to_russian(R.Proposal("f", "move", move, None, None, "absent"))


class ЧислоТелСчитаетсяВсегда(unittest.TestCase):

    def test_the_ceiling_is_a_named_constant(self):
        """A number written as a literal digit in a condition can be
        neither disputed nor found.

        🔴 THE NUMBER IS CHECKED, NOT THE SHAPE OF THE WRITING. The
        first edition searched for the substring `">= 8"` — and the
        "put the digit back" control passed GREEN, because the mutation
        wrote `< 8`. A guard that can be dodged by reshaping the
        wording guards nothing; so here the SYNTAX is parsed, and any
        numeric literal 8 in the function body is searched for.
        """
        import ast
        import inspect
        self.assertEqual(R.MAX_NAMED_HITS, 8)
        source = inspect.getsource(R._build_move)
        tree = ast.parse(textwrap.dedent(source))
        literals = [n for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and n.value == 8
                    and not isinstance(n.value, bool)]
        self.assertEqual(literals, [],
                         "потолок снова вписан ЧИСЛОМ в тело `_build_move`")
        self.assertIn("MAX_NAMED_HITS", source,
                      "названная константа больше не используется")

    def test_the_row_carries_the_total_and_the_truncation(self):
        fields = {f.name for f in dataclasses.fields(R.Move)}
        self.assertIn("hits_total", fields)
        self.assertIn("hits_truncated", fields)
        row = _move(9).as_dict()
        self.assertEqual(row["hits_total"], 9)
        self.assertIs(row["hits_truncated"], True)
        self.assertEqual(len(row["hits"]), 8, "названных обязано остаться 8")

    def test_the_named_list_stays_the_same_key_with_the_same_meaning(self):
        """An ADDITIVE fix: `hits` are still the NAMED ones, and both
        the receipt and the Russian sentence read it. The meaning of
        the published field on its own does not change."""
        row = _move(40).as_dict()
        self.assertEqual(row["hits"], [f"e{i}" for i in range(8)])


class УсечениеНазываетсяЧеловеку(unittest.TestCase):
    """A fix that reached the MACHINE and did not reach the HUMAN —
    exactly the incident that bought the rule about the prose
    ratchet."""

    def test_a_truncated_list_says_how_many_more(self):
        line = _line(_move(40))
        self.assertIn("и ещё 32", line)

    def test_exactly_eight_bodies_print_byte_for_byte_as_before(self):
        """🔴 THE SECOND OUTCOME, MANDATORY. Without it, an edit that
        always appends «и ещё N» would pass the check above."""
        self.assertEqual(
            _line(_move(8)),
            "f: сдвиньте труба p1 по −Y на 10 мм — НО после переноса элемент "
            "входит в ТРЕТЬЕ тело, с которым до переноса не пересекался "
            "(тела: e0, e1, e2, e3, e4, e5, e6, e7)")

    def test_no_third_bodies_at_all_is_unchanged(self):
        """🔴 THE THIRD OUTCOME: zero bodies — neither a blocker nor a
        tail."""
        move = _move(0, legal=True)
        self.assertEqual(move.hits_total, 0)
        self.assertIs(move.hits_truncated, False)
        self.assertEqual(move.as_dict()["blockers"], [])
        self.assertEqual(_line(move),
                         "f: сдвиньте труба p1 по −Y на 10 мм — ход свободен")


class СчётПродолжаетсяЗаПотолкомНаЖИВОМПУТИ(unittest.TestCase):
    """🔴 THE WHOLE PATH, not a hand-assembled `Move`: hulls ->
    `propose` -> `Move`. A check on a ready-made object would prove
    that the field CAN hold a number, not that `_build_move` COMPUTES
    it.

    🔴 THE RIG MUST BLOCK THE FALLBACK MOVE TOO. The first edition
    placed bodies only in the mover's path and got ZERO hits: `propose`
    found a legal move by shifting the SECOND element, and reported it
    as executable first — that is its declared behavior, not a defect.
    Until both sides are locked, the test would be silently checking
    the wrong thing, and the `skipTest` in it would be guarding thin
    air.
    """

    @staticmethod
    def _scene(count: int):
        from kir.clash import geom as G
        from kir.clash import hulls as H

        def rec(eid, hull, label="wall", category="OST_Walls",
                side="structure"):
            return H.HullRecord(source_id=eid, category=category, label=label,
                                mvp_side=side, hull=hull, grade="conservative",
                                hull_source="prism", inner=None)

        mover = rec("m", G.Aabb((0., 0., 0.), (100., 100., 100.)),
                    "pipe", "OST_PipeCurves", "mep")
        fixed = rec("f", G.Aabb((50., 0., 0.), (150., 100., 100.)))
        others = []
        for i in range(count):
            # in the PIPE's path (moving away along −X)
            others.append(rec(f"n{i}", G.Aabb((-45., i * 5.0, 0.),
                                              (-5., i * 5.0 + 4.0, 100.))))
            # in the WALL's path (the fallback move along +X)
            others.append(rec(f"q{i}", G.Aabb((155., i * 5.0, 0.),
                                              (195., i * 5.0 + 4.0, 100.))))
        return mover, fixed, R.Neighbourhood([mover, fixed] + others)

    def _chosen(self, count: int) -> R.Move:
        mover, fixed, hood = self._scene(count)
        proposal = R.propose(mover, fixed, hood=hood)
        self.assertIsNotNone(proposal.chosen, "ход не построен — стенд не туда")
        return proposal.chosen

    def test_twenty_bodies_are_counted_and_eight_are_named(self):
        move = self._chosen(20)
        self.assertEqual(move.hits_total, 20)
        self.assertEqual(len(move.hits), R.MAX_NAMED_HITS)
        self.assertIs(move.hits_truncated, True)
        self.assertIn("hits_third_body", move.blockers)
        self.assertIn("и ещё 12",
                      R.to_russian(R.Proposal("f~m", "move", move, None, None,
                                              "absent")))

    def test_exactly_eight_is_not_truncation(self):
        """🔴 THE SECOND OUTCOME ON THE LIVE PATH. Exactly the ceiling —
        not truncation."""
        move = self._chosen(8)
        self.assertEqual(move.hits_total, 8)
        self.assertEqual(len(move.hits), 8)
        self.assertIs(move.hits_truncated, False)
        self.assertNotIn("и ещё",
                         R.to_russian(R.Proposal("f~m", "move", move, None,
                                                 None, "absent")))

    def test_below_the_ceiling_names_them_all(self):
        move = self._chosen(4)
        self.assertEqual((move.hits_total, len(move.hits)), (4, 4))
        self.assertIs(move.hits_truncated, False)

    def test_a_clear_path_stays_clear(self):
        """🔴 THE THIRD OUTCOME: not a single third body — neither a
        count nor a blocker. Without it, an edit that "always counts at
        least something" would pass the checks above."""
        move = self._chosen(0)
        self.assertEqual(move.hits_total, 0)
        self.assertEqual(move.hits, ())
        self.assertIs(move.hits_truncated, False)
        self.assertNotIn("hits_third_body", move.blockers)


if __name__ == "__main__":
    unittest.main()
