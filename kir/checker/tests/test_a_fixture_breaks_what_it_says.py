"""A FIXTURE IS OBLIGATED TO BREAK WHAT IT SAYS ABOUT ITSELF — AND EXACTLY AS MUCH AS IT BREAKS.

🔴 THIS INSTRUMENT DID NOT EXIST AT ALL. `kir/checker/fixtures/builders.py` is
the judge's sole reference: `make_good()` yields zero blockers, every `bad_*`
spoils it. Before 29.08.2026 NOT A SINGLE test in the tree imported the
fixture (`grep -rl bad_floating_floor kir --include=*.py` found only the
module itself). That is, HAB010 could have died entirely, and no check would
have noticed.

WHAT EXACTLY IS BEING PINNED HERE, AND WHY EXACTLY LIKE THIS:

  * THE TARGET FIRED. A fixture named after a rule that it does not trigger is
    an instrument that cannot turn red on its own subject. We look at ALL
    THREE buckets (blocking, warnings, info): HAB031's target is INFO,
    HAB041/HAB050's is WARNING, and demanding a blocker from them would be
    demanding the wrong thing.
  * THE SET OF BLOCKERS EQUALS THE EXPECTED ONE IN FULL. The weak form "the
    target is present in the set" was rejected: it would let the fixture
    break anything else as well, and that is exactly how the defect would
    have lived on.
  * BOTH LEVERS SEPARATELY. The v1 and v2 sets are DIFFERENT for six fixtures
    out of sixteen — one shared column would have been a lie about both.

🔴 THE MODULE'S CLAIM WAS FIXED, NOT THE FIXTURES. The header of `builders.py`
promised «breaks EXACTLY one thing», but a measurement by execution on
29.08.2026 showed: half of them break several things. This is NOT a defect of
the fixtures. Isolating a floor vertically NECESSARILY isolates it for
connectivity too (HAB001), and for the apartment rules as well
(HAB002/003/004): the set of triggered rules is a CONSEQUENCE of one broken
thing, not the thing itself. Fitting the fixture to the promise would mean
fitting the subject to the instrument. So the promise was rewritten to "one
thing IN THE BUILDING," and the contract became THIS FILE, not the docstring.

🔴 THE DEBT IS NAMED AS A NUMBER, NOT HIDDEN — see `ЦЕЛЬ_МОЛЧИТ`. Two fixtures
under v2 do not touch their target AT ALL, and the rule was nonetheless
EVALUATED (it looked at the subjects and did not fire) — that is, this is not
input starvation but a mismatch between the fixture and its rule. The debt is
pinned by a REVERSE assertion: if the target ever starts firing, the file will
turn red and demand the record be updated. It will not let itself be silently
"fixed."

Run:
    cd /opt/kir && PYTHONPATH=/opt/kir \\
      /opt/kir-audit/suite-venv/venv/bin/python -m pytest \\
      kir/checker/tests/test_a_fixture_breaks_what_it_says.py \\
      -q -p no:cacheprovider -p no:randomly --tb=short -rf
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kir.checker import engine
from kir.checker.fixtures import builders
from kir.checker.spatial_model import SpatialModel

#: Fixture -> the rule for whose sake it was created (from its own docstring).
#: `None` — the fixture has no single target: it is a NAMED REPRODUCTION of an
#: incident, not a mutator of one rule.
ЦЕЛЬ: dict[str, tuple[str, ...] | None] = {
    "bad_room_no_door": ("HAB001", "HAB004"),
    "bad_apartment_into_apartment": ("HAB002",),
    "bad_no_egress_stair": ("HAB003",),
    "bad_floating_floor": ("HAB010",),
    "bad_steep_stair": ("HAB011",),
    "bad_discontinuous_core": ("HAB012",),
    "bad_tiny_bedroom": ("HAB020",),
    "bad_narrow_corridor": ("HAB021",),
    "bad_low_ceiling": ("HAB022",),
    "bad_bedroom_no_window": ("HAB030",),
    "bad_low_daylight": ("HAB031",),
    "bad_overlapping_rooms": ("HAB040",),
    "bad_door_in_wall": ("HAB041",),
    "bad_open_envelope": ("HAB042",),
    "bad_floating_column": ("HAB050",),
    "bad_floors_hidden_by_balcony_doors": None,
}

#: The full set of BLOCKING items on each lever. Captured BY EXECUTION on
#: 29.08.2026 at `95c3862`. They diverge for six fixtures — that is why there
#: are two columns, not one.
БЛОКИРУЮЩИЕ: dict[str, dict[str, set[str]]] = {
    "bad_apartment_into_apartment": {"v1": {"HAB002"}, "v2": {"HAB002"}},
    "bad_bedroom_no_window": {"v1": {"HAB030"}, "v2": {"HAB030"}},
    "bad_discontinuous_core": {"v1": set(), "v2": set()},
    "bad_door_in_wall": {"v1": set(), "v2": set()},
    "bad_floating_column": {"v1": set(), "v2": set()},
    "bad_floating_floor": {
        "v1": {"HAB001", "HAB002", "HAB003", "HAB004", "HAB010"},
        "v2": {"HAB001", "HAB002", "HAB003", "HAB004", "HAB010"}},
    "bad_floors_hidden_by_balcony_doors": {
        "v1": {"HAB001", "HAB003", "HAB010"},
        "v2": {"HAB001", "HAB003", "HAB010"}},
    "bad_low_ceiling": {"v1": set(), "v2": set()},
    "bad_low_daylight": {"v1": set(), "v2": set()},
    "bad_narrow_corridor": {"v1": set(), "v2": set()},
    "bad_no_egress_stair": {"v1": {"HAB001", "HAB003"}, "v2": {"HAB001"}},
    "bad_open_envelope": {"v1": set(), "v2": {"HAB030", "HAB042", "HAB060"}},
    "bad_overlapping_rooms": {
        "v1": {"HAB040"},
        "v2": {"HAB001", "HAB002", "HAB003", "HAB004", "HAB030",
               "HAB040", "HAB042", "HAB060", "HAB061"}},
    "bad_room_no_door": {
        "v1": {"HAB001", "HAB002", "HAB003", "HAB004"}, "v2": {"HAB001"}},
    "bad_steep_stair": {"v1": set(), "v2": {"HAB011"}},
    "bad_tiny_bedroom": {"v1": {"HAB020"}, "v2": {"HAB020"}},
}

#: 🔴 NAMED DEBT: (fixture, lever) -> why the target stays silent. The rule
#: was nonetheless EVALUATED, meaning it looked at real subjects and did not
#: fire — so the fixture and the rule diverge, it is not that input was
#: lacking. The assertion here is REVERSED: the target is obligated NOT to
#: fire. If it starts firing, the file will turn red and demand the reason be
#: worked out, not silently accept the improvement.
ЦЕЛЬ_МОЛЧИТ: dict[tuple[str, str], str] = {
    ("bad_door_in_wall", "v2"):
        "HAB041 оценено (n=8) и молчит; вместо него срабатывает HAB061. "
        "Вероятные соседи разбора — находки F-347 и F-348 в том же правиле.",
    ("bad_no_egress_stair", "v2"):
        "HAB003 оценено (n=1) и молчит; блокирует только HAB001. Под v1 та же "
        "фикстура свою цель задевает — значит разошлись рычаги, а не фикстура.",
}


def _исходы(имя: str, рычаг: str) -> tuple[set[str], set[str], set[str], object]:
    """Running a fixture on a NAMED lever. The environment is always restored.

    `mock.patch.dict` is not decoration here: the lever is read on every call,
    and a leaked variable would bleed into neighboring files of the same
    pytest process.
    """
    with mock.patch.dict(os.environ,
                         {"KIR_CHECKER_V2": "1" if рычаг == "v2" else "0"}):
        отчёт = engine.run(SpatialModel.model_validate(getattr(builders, имя)()))
    return (
        {v.rule_id for v in отчёт.blocking},
        {v.rule_id for v in отчёт.warnings},
        {v.rule_id for v in getattr(отчёт, "info", []) or []},
        отчёт,
    )


class ФикстураЛомаетТоЧтоГоворит(unittest.TestCase):

    def test_каждая_фикстура_задевает_своё_правило(self):
        """The target is obligated to sound — in any of the three buckets, but sound."""
        for имя, цели in sorted(ЦЕЛЬ.items()):
            if цели is None:
                continue
            for рычаг in ("v1", "v2"):
                with self.subTest(фикстура=имя, рычаг=рычаг):
                    блок, предупр, свед, _ = _исходы(имя, рычаг)
                    прозвучало = блок | предупр | свед
                    долг = ЦЕЛЬ_МОЛЧИТ.get((имя, рычаг))
                    if долг is not None:
                        self.assertTrue(долг.strip(), "долг без причины")
                        self.assertFalse(
                            set(цели) & прозвучало,
                            f"{имя}/{рычаг}: цель {цели} ЗАРАБОТАЛА — долг "
                            f"закрыт, обнови запись ЦЕЛЬ_МОЛЧИТ. Было: {долг}")
                    else:
                        self.assertTrue(
                            set(цели) & прозвучало,
                            f"{имя}/{рычаг}: цель {цели} не сработала ни в "
                            f"одном ведре; прозвучало {sorted(прозвучало)}")

    def test_набор_блокирующих_равен_ожидаемому_целиком(self):
        """Not "the target is present," but EQUALITY: otherwise the fixture is free to break more."""
        for имя in sorted(ЦЕЛЬ):
            for рычаг in ("v1", "v2"):
                with self.subTest(фикстура=имя, рычаг=рычаг):
                    блок, _, _, _ = _исходы(имя, рычаг)
                    self.assertEqual(блок, БЛОКИРУЮЩИЕ[имя][рычаг],
                                     f"{имя}/{рычаг}")

    def test_эталон_остаётся_чистым(self):
        """Without this control the instrument stays green even for a change that paints everything."""
        for рычаг in ("v1", "v2"):
            with self.subTest(рычаг=рычаг):
                with mock.patch.dict(
                        os.environ,
                        {"KIR_CHECKER_V2": "1" if рычаг == "v2" else "0"}):
                    отчёт = engine.run(
                        SpatialModel.model_validate(builders.make_good()))
                self.assertEqual({v.rule_id for v in отчёт.blocking}, set(),
                                 "эталон перестал быть чистым")

    def test_таблица_накрывает_все_фикстуры(self):
        """A fixture created tomorrow is obligated to land in the table, not slip past it."""
        живые = {n for n in dir(builders) if n.startswith("bad_")}
        self.assertEqual(живые, set(ЦЕЛЬ), "таблица целей разошлась с модулем")
        self.assertEqual(живые, set(БЛОКИРУЮЩИЕ),
                         "таблица блокирующих разошлась с модулем")
        for ключ in ЦЕЛЬ_МОЛЧИТ:
            self.assertIn(ключ[0], живые, ключ)
            self.assertIn(ключ[1], ("v1", "v2"), ключ)


if __name__ == "__main__":
    unittest.main()
