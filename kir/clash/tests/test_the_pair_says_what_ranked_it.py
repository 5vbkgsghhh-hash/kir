"""NETWORKS RANK AGAINST EACH OTHER BY AREA, BUT CLASS WAS DECIDING — AND THE
BASIS WAS LYING.

The module declares three laws, and the second reads: "THE SMALLER
CROSS-SECTION YIELDS TO THE LARGER. Networks rank against each other by
CROSS-SECTION AREA… Where there is no number, there is nothing to compare, and
the order is decided by class; this is stated by the `rank_basis` field, not
hidden in a default."

The body read it backwards. `MOVE_CLASS` contains ONLY networks — `duct` 1,
`tray` 2, `pipe` 3, `conduit` 4; construction does not enter it at all and
gets class 0 through `IMMOVABLE`. So `if ca != cb` decided by CLASS FIRST
exactly where the law requires AREA, and a pipe with r=100 yielded the right
of way to a pipe with r=10.

The second half of the defect is quieter and worse: `rank_basis` was taken
from ONE record (`mobility_of(mover)[2]`), where it means "what THIS hull is
grounded on". The record honestly carried `section_radius_mm` — even when the
order was decided by class. The report named a basis that was not there.

🔴 WHAT WAS MEASURED ON THE CORPUS (30.08.2026, 81 buildings, read-only), so
that the next reader does not mistake this file for a fix of a made-up case:

    buildings with CROSS-CLASS MEP categories          13 out of 81
    of which different classes geometrically clash      5 (bench_A, snowdon_plumb_v1..v4)
    real cross-class findings                          35
    the LARGER cross-section yielded (law violation)    24
    matched by accident                                11
    rank_basis lied                                    35 out of 35 — WITHOUT EXCEPTION

The counters of that measurement prove that the live path was called, not a
reconstruction: `_order` 36, `mobility_of` 308, `evaluate_with_reason` 83.

🔴 THE FIRST TEST IN THE FILE IS "A CASE FOR THE SUBJECT". Without it the
whole check is green BY CONSTRUCTION: if `duct` and `conduit` were in the same
class, law 1 and law 2 would give the same answer, and the file would be
guarding thin air.
"""
from __future__ import annotations

import math
import unittest

from kir.clash import geom as G
from kir.clash import hulls as H
from kir.clash import resolve as R


def _rec(sid: str, label: str, r: float | None,
         *, x: float = 0.0) -> H.HullRecord:
    """A network record with a known (or missing) cross-section."""
    hull = G.Capsule(path=((x, 0.0, 0.0), (x + 1000.0, 0.0, 0.0)),
                     radius=(r if r else 1.0))
    return H.HullRecord(
        source_id=sid, category="OST_PipeCurves", label=label, mvp_side=None,
        hull=hull, grade="fine", hull_source="axis_section",
        section_radius_mm=r, section_round=True,
        section_source=("p" if r else None))


def _wall(sid: str) -> H.HullRecord:
    """Construction: class 0 through `IMMOVABLE`, there is no cross-section by nature."""
    hull = G.Aabb(lo=(0.0, 0.0, 0.0), hi=(1000.0, 200.0, 3000.0))
    return H.HullRecord(
        source_id=sid, category="OST_Walls", label="wall", mvp_side=None,
        hull=hull, grade="fine", hull_source="profile")


class СлучайПоПредмету(unittest.TestCase):
    """Without this class the whole file is green by construction."""

    def test_две_сети_разных_классов_с_разными_сечениями_существуют(self):
        # If the classes matched, law 1 and law 2 could not diverge,
        # and there would be nothing to check.
        self.assertIn("duct", R.MOVE_CLASS)
        self.assertIn("conduit", R.MOVE_CLASS)
        self.assertNotEqual(
            R.MOVE_CLASS["duct"], R.MOVE_CLASS["conduit"],
            "случай не по предмету: сети в ОДНОМ классе — расхождения "
            "закона 1 и закона 2 не существует, файл сторожил бы воздух")
        # And the area is required to disagree with the class: the class says
        # "yields to conduit", the area says "yields to duct". Otherwise there
        # is likewise nothing to catch.
        duct, cond = _rec("D1", "duct", 10.0), _rec("C1", "conduit", 100.0)
        _, area_d, _ = R.mobility_of(duct)
        _, area_c, _ = R.mobility_of(cond)
        self.assertLess(area_d, area_c)
        self.assertGreater(R.MOVE_CLASS["conduit"], R.MOVE_CLASS["duct"],
                           "класс и площадь обязаны указывать на РАЗНЫЕ "
                           "стороны, иначе случай вырожден")

    def test_конструкция_вне_таблицы_классов(self):
        # Law 1 does not rest on MOVE_CLASS but on IMMOVABLE. If a wall
        # ends up in the network table, "class" will stop meaning "not a network".
        self.assertNotIn("wall", R.MOVE_CLASS)
        self.assertIn("wall", R.IMMOVABLE)
        cls, area, _ = R.mobility_of(_wall("W1"))
        self.assertEqual((cls, area), (0, 0.0))


class МеньшееСечениеУступает(unittest.TestCase):

    def test_меньшая_труба_уступает_большей_вопреки_классу(self):
        duct = _rec("D1", "duct", 10.0)        # area ~314 mm²
        cond = _rec("C1", "conduit", 100.0)    # area ~31 416 mm²
        mover, fixed, basis = R._decide(duct, cond)
        self.assertEqual(mover.source_id, "D1",
                         "уступать обязано МЕНЬШЕЕ сечение (закон 2), а не "
                         "элемент с большим MOVE_CLASS")
        self.assertEqual(fixed.source_id, "C1")
        self.assertEqual(basis, "section_radius_mm")

    def test_порядок_не_зависит_от_порядка_доводов(self):
        # A pair is a set; the answer is required to be the same from both ends.
        duct, cond = _rec("D1", "duct", 10.0), _rec("C1", "conduit", 100.0)
        a = R._decide(duct, cond)
        b = R._decide(cond, duct)
        self.assertEqual((a[0].source_id, a[1].source_id, a[2]),
                         (b[0].source_id, b[1].source_id, b[2]))

    def test_закон_1_не_сломан_сетя_уступает_конструкции(self):
        # THE OTHER SIDE: the fix must not hand the move to the wall. Here the
        # class decides LEGITIMATELY, and the basis is required to name it.
        mover, fixed, basis = R._decide(_rec("P1", "pipe", 50.0), _wall("W1"))
        self.assertEqual(mover.source_id, "P1", "труба обходит стену, не наоборот")
        self.assertEqual(fixed.source_id, "W1")
        self.assertEqual(basis, "move_class")


class ОснованиеНеЛжёт(unittest.TestCase):

    def test_основание_есть_свойство_пары_а_не_записи(self):
        # Both records honestly carry 'section_radius_mm' about themselves;
        # the order is still decided by class. Publishing a record instead of
        # the pair would be a lie.
        d1 = _rec("D1", "duct", 50.0)
        d2 = _rec("C1", "conduit", 50.0)        # areas are EQUAL
        self.assertEqual(R.mobility_of(d1)[2], "section_radius_mm")
        self.assertEqual(R.mobility_of(d2)[2], "section_radius_mm")
        mover, _, basis = R._decide(d1, d2)
        self.assertEqual(basis, "class_only",
                         "площади равны — сравнивать по ним нечем, решил "
                         "класс, и это обязано быть СКАЗАНО")
        self.assertEqual(mover.source_id, "C1")

    def test_каждое_основание_названо_в_закрытом_списке(self):
        for пара in ((_rec("D1", "duct", 10.0), _rec("C1", "conduit", 100.0)),
                     (_rec("P1", "pipe", 50.0), _wall("W1")),
                     (_rec("D1", "duct", 50.0), _rec("C1", "conduit", 50.0)),
                     (_rec("A1", "duct", None), _rec("B1", "duct", None))):
            _, _, basis = R._decide(*пара)
            self.assertIn(basis, R.RANK_BASIS,
                          "основание вне закрытого списка — то же умолчание, "
                          "от которого лечится модуль")

    def test_основание_пары_доезжает_даже_когда_запись_говорит_иначе(self):
        """🔴 THE CASE WHERE THE PAIR'S BASIS AND THE RECORD'S BASIS DIVERGE.

        Without it the whole class is blind: with different areas the pair's
        basis (`section_radius_mm`) COINCIDES with the record's basis, and
        substituting one for the other passes green. Verified by mutation —
        it passed.

        Here the areas are EQUAL: the pair was ranked by class
        (`class_only`), while both records honestly carry `section_radius_mm`
        about themselves.
        """
        a = _rec("D1", "duct", 50.0)
        b = _rec("C1", "conduit", 50.0, x=5.0)          # overlap
        self.assertEqual(R.mobility_of(a)[2], "section_radius_mm")
        self.assertEqual(R.mobility_of(b)[2], "section_radius_mm")
        p = R.propose(a, b, pair_kind="interference", with_alternative=True)
        self.assertIsNotNone(p.chosen, "пара обязана дать ход")
        self.assertEqual(
            p.chosen.rank_basis, "class_only",
            "в находку уехало основание ЗАПИСИ вместо основания ПАРЫ: "
            "отчёт назвал сечение там, где решил класс")
        if p.alternative is not None:
            self.assertEqual(
                p.alternative.rank_basis, "class_only",
                "встречный ход взял основание ВТОРОЙ записи: одна пара "
                "опубликовала два разных основания своего единственного "
                "порядка")

    def test_основание_доезжает_до_находки_и_одно_на_пару(self):
        duct = _rec("D1", "duct", 10.0)
        cond = _rec("C1", "conduit", 100.0, x=5.0)   # overlap
        p = R.propose(duct, cond, pair_kind="interference", with_alternative=True)
        self.assertIsNotNone(p.chosen, "пара обязана дать ход")
        self.assertEqual(p.chosen.rank_basis, "section_radius_mm")
        self.assertEqual(p.chosen.element_id, "D1")
        if p.alternative is not None:
            self.assertEqual(
                p.alternative.rank_basis, p.chosen.rank_basis,
                "встречный ход — та же ранжировка, прочитанная с другого "
                "конца: два основания у одного порядка быть не может")


class ОтсутствующееСечениеНеСамоеМалое(unittest.TestCase):

    def test_неизмеренный_элемент_не_обязан_уступать(self):
        # `mobility_of` returns area 0.0 for a missing cross-section.
        # Comparing it as "the thinnest" would mean forcing the one nothing
        # can be said about to yield. The law answers: "where there is no
        # number, there is nothing to compare" — and both are of the same
        # class here, so the address decides.
        нет = _rec("Z9", "duct", None)
        есть = _rec("A1", "duct", 100.0)
        self.assertEqual(R.mobility_of(нет)[1], 0.0)
        mover, _, basis = R._decide(нет, есть)
        self.assertEqual(basis, "source_id",
                         "площадь известна лишь одной стороне — по ней "
                         "ранжировать нечем")
        self.assertEqual(mover.source_id, "A1", "решил АДРЕС, а не мнимый ноль")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
