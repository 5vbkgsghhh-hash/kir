"""«NOT CAPTURED» AND «CAPTURED, THE BUILDING ANSWERED NO» ARE DIFFERENT OUTCOMES.

WHY THIS FILE, BY THE 20.08.2026 MEASUREMENT. `vacuous_reason` was a
CONSTANT of the specification, that is, it described ONE emptiness.
`HAB050` has three, and two of them are OPPOSITE in meaning:

    not captured                  our own reading hole
    captured, the answer is NO    a fact about the building
    a mixed input                 a claim about the part that was read

While the reason was a single line, «no structural walls flagged» was
printed in all three cases. This is exactly what has already been worked
through for doors: collapsing `refused` and `no_room_in_phase` into one
column means losing the distinction between ourselves and the subject.

The same day's live measurement: `WALL_STRUCTURAL_SIGNIFICANT` arrives for
7845 walls out of 10 646 and is EVERYWHERE zero. Yesterday the same line
meant «we did not ask»; today — «we asked, and the building answered NO».
The line did not change.

And `HAB011`: three of the four values are live (24 out of 24 stairs), what
is missing is the FLIGHT WIDTH — and not because it was not asked, but
because `Stairs` simply does NOT HAVE it (it lives on
`StairsRun.ActualRunWidth`; the flight IS read by a side stage — the path is
captured for 48 out of 48 — it is specifically the WIDTH that is not
captured, measured 22.08.2026). The coverage line requires all three at
once, so the rule still stays silent — but "not a single value was measured"
became an UNDERSTATEMENT, and the verdict is obligated to say what it judged
by.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

import networkx as nx

from kir.checker.engine import (_V2Context, _stair_vacuity,
                                           _structural_vacuity)
from kir.checker.spatial_model import SpatialModel


def _ctx(**payload) -> _V2Context:
    base = {"building_id": "b1",
            "levels": [{"id": "L1", "name": "L1", "elevation_mm": 0.0, "index": 0}]}
    base.update(payload)
    model = SpatialModel.model_validate(base)
    return _V2Context(model=model, drep=None, graph=nx.Graph(), apartments=[])


def _wall(wid: str, structural):
    return {"id": wid, "level_id": "L1", "curve": ((0.0, 0.0), (1000.0, 0.0)),
            "height_mm": 2700.0, "is_structural": structural}


def _stair(sid: str, **over):
    row = {"id": sid, "base_level_id": "L1", "top_level_id": "L1",
           "base_z": 0.0, "top_z": 3000.0, "run_width_mm": None,
           "riser_count": None, "tread_depth_mm": None, "footprint": [],
           "kind": "element"}
    row.update(over)
    return row


class ТриПустотыHAB050Различимы(unittest.TestCase):

    def test_не_захвачено_названо_НАШЕЙ_дырой(self):
        text = _structural_vacuity(_ctx(walls=[_wall("w1", None), _wall("w2", None)]))
        self.assertIn("НЕ ЗАХВАЧЕНО", text)
        self.assertIn("наша дыра", text)
        # The discriminator is an ASSERTION, not a substring: both reasons
        # mention «a fact about the building», one affirming it, the other
        # DENYING it («not a fact about the building»). Checking for the
        # phrase's absence would mean matching by label, not by subject —
        # form 7, caught on its own test.
        self.assertNotIn("ЗДАНИЕ ОТВЕТИЛО НЕТ", text)

    def test_захвачено_и_отрицательно_названо_ФАКТОМ_О_ЗДАНИИ(self):
        text = _structural_vacuity(_ctx(walls=[_wall("w1", False), _wall("w2", False)]))
        self.assertIn("ЗДАНИЕ ОТВЕТИЛО НЕТ", text)
        self.assertIn("факт о здании", text)
        self.assertNotIn("НЕ ЗАХВАЧЕНО", text)

    def test_две_причины_НЕ_СОВПАДАЮТ_дословно(self):
        """The file's main assertion: the distinction exists, not merely declared.

        Were the texts to match, the field would have three possible values,
        yet the reader would still fail to distinguish its own hole from a
        fact about the building.
        """
        unknown = _structural_vacuity(_ctx(walls=[_wall("w1", None)]))
        negative = _structural_vacuity(_ctx(walls=[_wall("w1", False)]))
        self.assertNotEqual(unknown, negative)

    def test_смешанный_вход_называет_ОБЕ_величины(self):
        text = _structural_vacuity(_ctx(walls=[_wall("w1", None), _wall("w2", False)]))
        self.assertIn("смешанный", text)
        self.assertIn("1", text)

    def test_стен_нет_вовсе_это_третий_исход(self):
        self.assertIn("стен нет вовсе", _structural_vacuity(_ctx(walls=[])))


class HAB011ГоворитПоЧемуСудил(unittest.TestCase):

    def test_две_величины_из_трёх_НЕ_читаются_как_ни_одной(self):
        text = _stair_vacuity(_ctx(stairs=[
            _stair("s1", riser_count=17, tread_depth_mm=300.0),
            _stair("s2", riser_count=17, tread_depth_mm=300.0)]))
        self.assertIn("судили по", text)
        self.assertIn("riser count у 2 из 2", text)
        self.assertIn("tread depth у 2 из 2", text)
        self.assertIn("НЕ «геометрия не измерена»", text)

    def test_отсутствие_ширины_названо_ИМЕНЕМ_а_не_долгом(self):
        """A named absence: the value is not where we are looking for it.

        This is not work that was forgotten — it is a fact about the API,
        and the reader is obligated to distinguish it from a capture that
        was never done.
        """
        text = _stair_vacuity(_ctx(stairs=[_stair("s1", riser_count=17)]))
        self.assertIn("StairsRun.ActualRunWidth", text)
        self.assertIn("не снимается именно ШИРИНА", text,
                      "«марш не читается вовсе» было шире правды: боковая "
                      "стадия снимает его путь у 48 из 48")

    def test_ни_одной_величины_это_ДРУГОЙ_текст(self):
        text = _stair_vacuity(_ctx(stairs=[_stair("s1")]))
        self.assertIn("НИ ОДНА величина не прочитана", text)
        self.assertNotIn("судили по", text)

    def test_выведенные_связи_не_выдаются_за_лестницы(self):
        text = _stair_vacuity(_ctx(stairs=[_stair("s1", kind="inferred")]))
        self.assertIn("выведенные связи", text)

    def test_лестниц_нет_вовсе(self):
        self.assertIn("лестниц нет вовсе", _stair_vacuity(_ctx(stairs=[])))


class ПричинаВЫЧИСЛЯЕТСЯ_аНеБерётсяКонстантой(unittest.TestCase):
    """Mechanism: `RuleSpec.reason_for` is obligated to call the function when one is given."""

    def test_строка_остаётся_строкой(self):
        from kir.checker.engine import RuleSpec
        spec = RuleSpec(lambda *a: [], "X", lambda c: 0, "просто строка",
                        lambda c: False)
        self.assertEqual(spec.reason_for(_ctx()), "просто строка")

    def test_функция_зовётся_с_контекстом(self):
        from kir.checker.engine import RuleSpec
        spec = RuleSpec(lambda *a: [], "X", lambda c: 0,
                        lambda c: "стен %d" % len(c.model.walls), lambda c: False)
        self.assertEqual(spec.reason_for(_ctx(walls=[_wall("w1", None)])), "стен 1")

    def test_оба_правила_переведены_на_функцию(self):
        """Otherwise the fix would be a mechanism with no application."""
        from kir.checker.engine import RULE_SPECS_V2
        by_id = {s.rule_id: s for s in RULE_SPECS_V2}
        for rid in ("HAB050", "HAB011"):
            self.assertTrue(callable(by_id[rid].vacuous_reason),
                            f"{rid} всё ещё несёт константу")


class ПустотаКупленнаяНастоящимЗданием(unittest.TestCase):
    """🔴 THE FIRST RUN OF 20 RULES AGAINST THE PRODUCTION MODEL, 22.08.2026.

    MNVNK, 33 944 elements, 1 102 rooms, 30 levels. Verdict FAIL, BLOCKING
    24 — and NOT A SINGLE ONE of the 24 was a fact about the building. After
    these two fixes: BLOCKING 0, verdict NOT_EVALUATED.
    """

    def test_нуль_лестниц_НЕ_делает_предусловие_верным(self):
        """23 false «the floor hangs with no connection to the ground» stood here.

        The difference between sets is empty when there are zero stairs: the
        left-hand set is empty, there is nothing to subtract, the
        precondition holds VACUOUSLY. The guard was set up specifically
        against this very formulation (measured 03.08 on snowdon) and was
        losing to exactly the emptiness it guards against.
        """
        from kir.checker.engine import PRECONDITIONS
        holds, _ = PRECONDITIONS["stair_landings_complete"]
        self.assertFalse(holds(_ctx(stairs=[])),
                         "без единой лестницы вертикальных рёбер нет ПО "
                         "ПОСТРОЕНИЮ, и «этаж висит» неотличимо от "
                         "«спускаться нечему»")

    def test_причина_называет_ИМЕННО_ту_пустоту_что_случилась(self):
        from kir.checker.engine import _precondition_reason
        нет_лестниц = _precondition_reason("stair_landings_complete",
                                           _ctx(stairs=[]))
        нет_разметки = _precondition_reason(
            "stair_landings_complete",
            _ctx(stairs=[_stair("s1")], rooms=[]))
        self.assertIn("НЕТ НИ ОДНОЙ", нет_лестниц)
        self.assertIn("witness.drop", нет_лестниц,
                      "читателя надо послать к отказам съёма — на MNVNK "
                      "лестниц 24 и отброшены все 24")
        self.assertIn("разметк", нет_разметки)
        self.assertNotEqual(нет_лестниц, нет_разметки,
                            "две разные пустоты — две разные починки")

    def test_HAB021_считает_СВОИХ_субъектов_а_не_измеренные_контуры(self):
        """Coverage printed «EVALUATED n=473, 0 нарушений» with ZERO subjects.

        The rule's body only takes functions with a width threshold; all
        1 102 rooms of MNVNK carry OTHER. The counter stood for "how many
        had their contour measured" — a quantity that has no bearing on the
        rule's subject.
        """
        from kir.checker.spatial_model import RoomFunction
        from kir.checker.engine import RULE_SPECS_V2
        spec = {s.rule_id: s for s in RULE_SPECS_V2}["HAB021"]

        def _room(rid, fn):
            return {"id": rid, "level_id": "L1", "name": rid,
                    "function": fn.value, "area_m2": 9.0, "height_mm": 2700.0,
                    "boundary": [(0.0, 0.0), (3000.0, 0.0),
                                 (3000.0, 3000.0), (0.0, 3000.0)]}

        прочее = _ctx(rooms=[_room("r%d" % i, RoomFunction.ПРОЧЕЕ)
                             for i in range(5)])
        self.assertEqual(spec.subjects(прочее), 0,
                         "«проверено 5, нарушений нет» тут было бы ложью")
        жилые = _ctx(rooms=[_room("r1", RoomFunction.ЖИЛАЯ),
                            _room("r2", RoomFunction.КОРИДОР),
                            _room("r3", RoomFunction.ПРОЧЕЕ)])
        self.assertEqual(spec.subjects(жилые), 2)

    def test_счётчик_HAB021_не_расходится_с_фильтром_своего_тела(self):
        """Two carriers of one piece of knowledge — the set of functions. We hold them together.

        The neighboring `_n_area_rule_subjects` for HAB020 was done
        correctly and, on the same building, honestly went to
        NOT_EVALUATED; it was the two of them that diverged, not the rule.
        """
        import inspect
        from kir.checker.rules import dimensions
        from kir.checker import engine
        тело = inspect.getsource(dimensions.check_hab021)
        счётчик = inspect.getsource(engine._n_width_rule_subjects)
        for имя in ("ЖИЛАЯ", "КОРИДОР", "КУХНЯ", "САНУЗЕЛ"):
            with self.subTest(функция=имя):
                self.assertEqual(имя in тело, имя in счётчик,
                                 f"{имя}: тело правила и его счётчик "
                                 "разошлись — ровно та форма, что дала "
                                 "«EVALUATED n=473» при нуле субъектов")


if __name__ == "__main__":
    unittest.main()
