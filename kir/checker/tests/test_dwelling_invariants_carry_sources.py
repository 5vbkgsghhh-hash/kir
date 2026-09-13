"""AN INVARIANT WITHOUT A SOURCE IS AN OPINION, AND THE REGISTRY MUST TELL THE DIFFERENCE.

WHY THIS FILE (20.08.2026). Three topological definitions of "public" died
in one evening, and what killed them was COMPOSITION: "core touching" improved both prior measures
(singles 518 → 300, orphans 366 → 39) yet produced 39 apartments with two kitchens. The task
inverts — not guessing public nodes, but searching for a partition that
SATISFIES the invariant.

The first pass is not an algorithm but a LIST with provenance. Three things are held here, and
each catches its own kind of trouble:

    the source is named and its kind is declared   otherwise "sounds reasonable" becomes law
    every invariant CAN say NO                       otherwise the registry is decoration
    a refusal is a FIRST-CLASS outcome                otherwise a kindergarten yields confident nonsense

🔴 AND A CAVEAT THAT THE INSTRUMENT PRINTS, NOT ONE THE AUTHOR KEEPS IN MIND. There is no
oracle for an apartment. A partition that satisfies the invariants means "does not contradict
what we know how to check", NOT "correctly derived". The test holds that this
distinction stands in the REPORT.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir.checker.dwelling_invariants import (INVARIANTS,
                                                        UNSOURCED_CANDIDATES,
                                                        VERDICT_BANNER,
                                                        Invariant,
                                                        check_invariants,
                                                        feasibility)
from kir.checker.spatial_model import RoomFunction, SpatialModel


def _model(functions: dict[str, RoomFunction]) -> SpatialModel:
    return SpatialModel.model_validate({
        "building_id": "b1",
        "levels": [{"id": "L1", "name": "L1", "elevation_mm": 0.0, "index": 0}],
        "rooms": [{"id": rid, "name": rid, "level_id": "L1",
                   "function": f.value, "area_m2": 12.0,
                   "height_mm": 3000.0, "boundary": []}
                  for rid, f in functions.items()],
    })


class ProvenanceIsMandatory(unittest.TestCase):

    def test_каждый_инвариант_несёт_источник_объявленного_рода(self):
        self.assertTrue(INVARIANTS)
        for inv in INVARIANTS:
            with self.subTest(инвариант=inv.id):
                self.assertIn(inv.source_kind,
                              ("decision_fired", "rule", "definition"))
                self.assertGreater(len(inv.source), 40,
                                   "источник обязан быть ссылкой, а не словом")
                self.assertTrue(inv.statement)

    def test_нерод_источника_ОТКАЗЫВАЕТ_на_построении(self):
        """Control: "sounds reasonable" cannot be entered even by accident."""
        with self.assertRaises(ValueError) as caught:
            Invariant(id="x", statement="s", source_kind="здравый смысл",
                      source="…", holds=lambda ids, f: True)
        self.assertIn("источником не", str(caught.exception))

    def test_кандидаты_без_источника_названы_и_НЕ_в_реестре(self):
        """A silently missing requirement will return as "obvious" within a week."""
        self.assertTrue(UNSOURCED_CANDIDATES)
        registered = {inv.id for inv in INVARIANTS}
        for name, why in UNSOURCED_CANDIDATES:
            with self.subTest(кандидат=name):
                self.assertNotIn(name, registered)
                self.assertGreater(len(why), 60,
                                   "отказ во внесении обязан называть ПРИЧИНУ")

    def test_идентификаторы_не_повторяются(self):
        ids = [inv.id for inv in INVARIANTS]
        self.assertEqual(len(ids), len(set(ids)))


class КаждыйИнвариантУмеетСказатьНЕТ(unittest.TestCase):
    """A registry none of whose members can ever fire is decoration.

    Each case below VIOLATES exactly one invariant and must be caught
    by that exact one: a broad red would be a sign of a blunt probe.
    """

    def _violations(self, functions, component):
        model = _model(functions)
        return check_invariants(model, [frozenset(component)]).violations

    def test_две_кухни_ловятся_и_только_ими(self):
        v = self._violations(
            {"k1": RoomFunction.КУХНЯ, "k2": RoomFunction.КУХНЯ},
            ["k1", "k2"])
        self.assertEqual(v["one_kitchen"], 1)
        self.assertEqual(v["one_prihozhaya"], 0)
        self.assertEqual(v["is_a_dwelling"], 0)

    def test_две_прихожие_ловятся_и_только_ими(self):
        v = self._violations(
            {"p1": RoomFunction.ПРИХОЖАЯ, "p2": RoomFunction.ПРИХОЖАЯ,
             "k1": RoomFunction.КУХНЯ},
            ["p1", "p2", "k1"])
        self.assertEqual(v["one_prihozhaya"], 1)
        self.assertEqual(v["one_kitchen"], 0)

    def test_не_жилище_ловится_и_только_им(self):
        v = self._violations(
            {"z1": RoomFunction.ЖИЛАЯ, "z2": RoomFunction.ЖИЛАЯ},
            ["z1", "z2"])
        self.assertEqual(v["is_a_dwelling"], 1)
        self.assertEqual(v["one_kitchen"], 0)
        self.assertEqual(v["one_prihozhaya"], 0)

    def test_здоровая_компонента_не_нарушает_НИЧЕГО(self):
        """Degeneracy control: the registry can also stay silent."""
        v = self._violations(
            {"k": RoomFunction.КУХНЯ, "s": RoomFunction.САНУЗЕЛ,
             "p": RoomFunction.ПРИХОЖАЯ, "z": RoomFunction.ЖИЛАЯ},
            ["k", "s", "p", "z"])
        self.assertEqual(set(v.values()), {0})


class ОтказЭтоИсходПервогоКласса(unittest.TestCase):
    """A kindergarten is not a dwelling, and the correct answer there is "no apartments", not the worst partition."""

    def test_без_кухонь_и_санузлов_искать_НЕЧЕГО(self):
        f = feasibility(_model({"t": RoomFunction.ТЕХ, "k": RoomFunction.КОРИДОР}))
        self.assertFalse(f.searchable)
        self.assertIn("ИСКАТЬ НЕЧЕГО", f.render())

    def test_пустая_модель_тоже_отказ_а_не_ноль_квартир(self):
        self.assertFalse(feasibility(_model({})).searchable)

    def test_при_жилищных_помещениях_искать_МОЖНО(self):
        """Control in the other direction: the refusal does not fire always."""
        f = feasibility(_model({"k": RoomFunction.КУХНЯ}))
        self.assertTrue(f.searchable)

    def test_отказ_БЕЗ_ПОРОГА_а_не_по_доле(self):
        """A ratio would be a solution tailored to the building.

        One kitchen for a thousand technical rooms is still "searchable":
        we do not refuse below the definition — we count and print instead.
        """
        rooms = {f"t{i}": RoomFunction.ТЕХ for i in range(50)}
        rooms["k"] = RoomFunction.КУХНЯ
        self.assertTrue(feasibility(_model(rooms)).searchable)


class ОтчётНесётОговоркуОбОракуле(unittest.TestCase):

    def test_баннер_стоит_в_КАЖДОМ_выводе(self):
        model = _model({"k": RoomFunction.КУХНЯ})
        for components in ([], [frozenset(["k"])]):
            with self.subTest(компонент=len(components)):
                self.assertIn(VERDICT_BANNER,
                              check_invariants(model, components).render())

    def test_баннер_говорит_ИМЕННО_про_разницу_двух_утверждений(self):
        self.assertIn("НЕ значит", VERDICT_BANNER)
        self.assertIn("не противоречит", VERDICT_BANNER)

    def test_чистый_вывод_НЕ_объявляется_верным(self):
        model = _model({"k": RoomFunction.КУХНЯ, "s": RoomFunction.САНУЗЕЛ})
        report = check_invariants(model, [frozenset(["k", "s"])])
        self.assertTrue(report.clean)
        self.assertIn("НЕ значит «выведено верно»", report.render())

    def test_пустой_вывод_не_читается_как_чистый(self):
        report = check_invariants(_model({"k": RoomFunction.КУХНЯ}), [])
        self.assertFalse(report.clean, "ноль компонент — не «нарушений нет»")


if __name__ == "__main__":
    unittest.main()
