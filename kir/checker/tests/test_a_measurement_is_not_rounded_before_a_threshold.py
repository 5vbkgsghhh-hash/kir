"""ROUNDING IS FINE FOR DISPLAY. BEFORE A COMPARISON WITH A THRESHOLD — IT IS NOT.

WHAT HAPPENED (29.08.2026; audit findings F-040, F-256, F-336). Four of the
judge's landings rounded the measured value to 0.01 m² BEFORE it reached the
rule. A rounded number changes the VERDICT, not the printing precision, and
all three misses go in one direction:

    F-040  habitable 7995x1000 mm: exact area 7.995 < 8.0 -> violation,
           round(7.995, 2) = 8.0            -> HAB020 STAYS SILENT
    F-336  room 10 m², glazing 1.246: ratio 0.1246 < 1/8 -> violation,
           round(1.246, 2) = 1.25           -> ratio exactly 0.125, HAB031 STAYS SILENT
    F-256  two windows 1000x546: exact sum 1.092 < 1.09375 -> violation,
           0.55 + 0.55 = 1.10               -> HAB031 STAYS SILENT

One direction is not a coincidence: rounding to the nearest, for a value that
is compared against a LOWER threshold, systematically lifts it above the
threshold. The building looks better than it is, and by exactly as much as
the threshold is fine-grained.

THERE ARE TWO GUARDS HERE, AND THEY DIFFER IN NATURE:
  * BEHAVIORAL — a room with an exact area of 7.995 is obligated to yield
    7.995 and drop HAB020. It catches the loss of precision on the live path;
  * SOURCE (AST) — an assignment to a value with `_area` in its name has no
    right to be a call to `round`. It catches the RETURN of rounding at a new
    location that the behavioral test has not yet reached. Either without the
    other is leaky: the rule can be bypassed by a new landing, and the source
    guard by a new way to round.
"""
from __future__ import annotations

import ast
import os
import pathlib
import unittest
from unittest import mock

import networkx as nx

from kir.checker.derive import derive
from kir.checker.rules import light
from kir.checker.spatial_model import Level, Room, RoomFunction, SpatialModel
from kir.checker.thresholds import Thresholds

_V2 = mock.patch.dict(os.environ, {"KIR_CHECKER_V2": "1"})

#: The modules where a measured value is born and from which it travels to the rules.
_MEASURING_SOURCES = ("kir/checker/derive.py", "kir/checker/extractor.py")

#: THE SOURCE GUARD'S DENOMINATOR. How many places where a value with `area`
#: in its name is born it is OBLIGATED to inspect, for its "no offenders" to
#: mean anything.
#:
#: 🔴 WHY A NUMBER, AND NOT `offenders == []` (measured 02.09.2026). The FILES
#: read below are already two out of two — and that is not enough: the file
#: is in place, but the bodies moved out. That is exactly how the emitter
#: guard went blind on 02.09 — it read the live file and saw 35 names out of
#: 72, because 32 bodies had moved into satellites. It stayed GREEN. An empty
#: inspection yields an empty list of offenders, and that reads as "clean."
#:
#: Measurement of 02.09.2026: `derive.py` + `extractor.py` yield **32**
#: places — 20 assignments, 5 dictionary keys, 7 keyword arguments. The floor
#: is set below the measurement by exactly enough to survive a single
#: deletion, but not a relocation of the kind: both censuses that went blind
#: that day lost MORE THAN HALF.
МЕСТ_РОЖДЕНИЯ_ПЛОЩАДИ_НЕ_МЕНЬШЕ = 28


def _tree_root() -> pathlib.Path:
    import kir
    return pathlib.Path(kir.__file__).resolve().parent.parent


class AMeasurementIsNotRoundedBeforeAThreshold(unittest.TestCase):

    def test_an_exact_area_survives_derivation(self) -> None:
        """7995 x 1000 mm — an area of exactly 7.995 m², and it is obligated to arrive."""
        lvl = Level(id="L1", name="L1", elevation_mm=0, index=0)
        room = Room(id="r1", name="жилая", level_id="L1",
                    function=RoomFunction.ЖИЛАЯ, area_m2=7.995, height_mm=2700.0,
                    boundary=[(0, 0), (7995, 0), (7995, 1000), (0, 1000)])
        model = SpatialModel(building_id="b", levels=[lvl], rooms=[room])
        with _V2:
            _dmodel, drep = derive(model, Thresholds())
        derived = drep.rooms["r1"].derived_area_m2
        self.assertIsNotNone(derived)
        self.assertLess(
            derived, 8.0,
            f"площадь доехала как {derived!r}: округление до 0.01 м² подняло "
            f"7.995 над порогом 8.0, и HAB020 замолчал")
        self.assertAlmostEqual(derived, 7.995, places=3)

    def test_the_stored_number_decides_the_daylight_verdict(self) -> None:
        """Why precision is LOAD-BEARING, not cosmetic: the same room,
        differing only in the stored number, gets different verdicts."""
        thr = Thresholds()

        def лучится(area_m2: float, window_m2: float) -> list[str]:
            room = Room(id="r", name="жилая", level_id="L1",
                        function=RoomFunction.ЖИЛАЯ, area_m2=area_m2,
                        height_mm=2700.0, has_window=True,
                        window_area_m2=window_m2,
                        boundary=[(0, 0), (5000, 0), (5000, 2000), (0, 2000)])
            lvl = Level(id="L1", name="L1", elevation_mm=0, index=0)
            model = SpatialModel(building_id="b", levels=[lvl], rooms=[room])
            return [v.rule_id for v in light.check_hab031(model, nx.Graph(), thr)]

        # F-336: the 1:8 threshold for a 10 m² room is exactly 1.25 m².
        self.assertEqual(лучится(10.0, 1.246), ["HAB031"])
        self.assertEqual(лучится(10.0, 1.25), [],
                         "round(1.246, 2) = 1.25 гасит правило ровно на пороге")
        # F-256: two windows 1000x546, exact sum 1.092 against a threshold of 1.09375.
        self.assertEqual(лучится(8.75, 1.092), ["HAB031"])
        self.assertEqual(лучится(8.75, 1.10), [],
                         "0.55 + 0.55 — округление ДО суммы — гасит правило")

    def test_no_measured_area_is_assigned_a_rounded_value(self) -> None:
        """SOURCE GUARD: catches the return of rounding at a NEW location.

        It searches for ANY place where a value with `area` in its name
        receives a value that contains a call to `round` somewhere inside it.

        🔴 THE GUARD'S FIRST EDITION CAUGHT 2 LANDINGS OUT OF 4, and this came
        out through a FAIL control, not through eyeballing. It checked
        whether the assignment's VALUE was itself a call to `round` — and it
        missed both indirect forms:

            derive.py:447     derived_area = round(...) if p else None   ternary
            extractor.py:221  {"window_area_m2": round(...)}             dict

        That is, the guard against rounding would itself have been bypassed
        by the two most ordinary ways of writing the same thing. It now walks
        the value's SUBTREE, and dictionaries are handled separately: a key
        with `area` in its name is just as much a place where a value is born
        as a variable's name.

        The boundaries are named: a `round` inside an f-string is display,
        and it is not caught, because it does not assign a value; the
        grouping quantization in `extractor` (`cx`, `cy`) does not carry
        `area` in its name.
        """
        root = _tree_root()
        checked = 0
        осмотрено = 0          # DENOMINATOR: places where a value is born, TOTAL
        offenders: list[str] = []

        def _rounds(node: ast.AST | None) -> bool:
            """Whether there is a call to `round` anywhere in this expression.

            `None` is a legitimate input: `x: float` with no value is an
            AnnAssign with `value=None`, and `ast.walk(None)` crashes the
            traversal outright. The first edition did not know this and
            raised AttributeError on a live file: a guard that crashes on
            itself is indistinguishable from a guard that found nothing —
            neither gives an answer.
            """
            if node is None:
                return False
            return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == "round" for n in ast.walk(node))

        for rel in _MEASURING_SOURCES:
            path = root / rel
            self.assertTrue(path.is_file(), f"нет файла {rel}")
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            checked += 1
            for node in ast.walk(tree):
                # (a) assignment to a variable or an attribute
                targets: list[ast.AST] = []
                if isinstance(node, ast.Assign):
                    targets = list(node.targets)
                elif isinstance(node, ast.AnnAssign):
                    targets = [node.target]
                if targets:
                    names = [t.id if isinstance(t, ast.Name) else
                             t.attr if isinstance(t, ast.Attribute) else ""
                             for t in targets]
                    if any("area" in n.lower() for n in names):
                        осмотрено += 1
                        if _rounds(node.value):
                            offenders.append(f"{rel}:{node.lineno} {'/'.join(names)}")
                # (b) a value in a dictionary under a value-named key
                if isinstance(node, ast.Dict):
                    for key, value in zip(node.keys, node.values):
                        if (isinstance(key, ast.Constant)
                                and isinstance(key.value, str)
                                and "area" in key.value.lower()):
                            осмотрено += 1
                            if _rounds(value):
                                offenders.append(
                                    f"{rel}:{getattr(value, 'lineno', node.lineno)} "
                                    f"ключ {key.value!r}")
                # (c) a keyword argument of a call
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg and "area" in kw.arg.lower():
                            осмотрено += 1
                            if _rounds(kw.value):
                                offenders.append(
                                    f"{rel}:{getattr(kw.value, 'lineno', node.lineno)} "
                                    f"аргумент {kw.arg}")
        offenders = sorted(set(offenders))
        # DENOMINATOR FIRST: zero files read would give "clean" vacuously.
        self.assertEqual(checked, len(_MEASURING_SOURCES))
        # ...and two files read WITHOUT BODIES would give the same thing silently.
        self.assertGreaterEqual(
            осмотрено, МЕСТ_РОЖДЕНИЯ_ПЛОЩАДИ_НЕ_МЕНЬШЕ,
            f"сторож осмотрел {осмотрено} мест рождения величины при поле "
            f"{МЕСТ_РОЖДЕНИЯ_ПЛОЩАДИ_НЕ_МЕНЬШЕ} (замер 02.09.2026 — 32). "
            f"Это заявление о ХОДОКЕ, а не о коде: файлы на месте, а величина "
            f"в них больше не рождается — значит тела уехали, и пустой список "
            f"нарушителей ниже НИЧЕГО не означает")
        self.assertEqual(
            offenders, [],
            f"измеренная площадь присвоена округлённой: {offenders}. "
            f"Округлять можно только для ПОКАЗА — округлённое число меняет "
            f"вердикт, а не точность печати")


class TheGuardItselfCanFail(unittest.TestCase):
    """FAIL CONTROL: the source guard is obligated to catch its own subject."""

    def test_it_catches_a_rounded_area_assignment(self) -> None:
        proba = ast.parse("derived_area = round(p.area / 1e6, 2)")
        node = proba.body[0]
        self.assertIsInstance(node, ast.Assign)
        self.assertTrue(any("area" in t.id.lower() for t in node.targets))
        self.assertIsInstance(node.value, ast.Call)
        self.assertEqual(node.value.func.id, "round")

    def test_it_does_not_accuse_a_rounded_display(self) -> None:
        """An f-string with rounding is display, and it must not be accused."""
        proba = ast.parse('msg = f"{round(area, 2)} m²"')
        node = proba.body[0]
        self.assertNotIsInstance(node.value, ast.Call)
        self.assertFalse(any("area" in t.id.lower() for t in node.targets),
                         "цель показа не должна нести имя величины")

    def test_it_catches_the_two_forms_the_first_edition_missed(self) -> None:
        """🔴 THAT VERY GUARD MISS: the ternary and the dictionary.

        The first edition asked "is the value a call to round" and was
        bypassed by the two most ordinary ways of writing the same thing.
        """
        тернарник = ast.parse("derived_area = round(x, 2) if p else None").body[0]
        self.assertNotIsInstance(тернарник.value, ast.Call)   # a direct check is blind
        self.assertTrue(any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "round"
                            for n in ast.walk(тернарник.value)))

        словарь = ast.parse('d = {"window_area_m2": round(x, 2)}').body[0].value
        self.assertIsInstance(словарь, ast.Dict)
        key, value = словарь.keys[0], словарь.values[0]
        self.assertIn("area", key.value.lower())
        self.assertTrue(any(isinstance(n, ast.Call) and getattr(n.func, "id", "") == "round"
                            for n in ast.walk(value)))


if __name__ == "__main__":
    unittest.main()
