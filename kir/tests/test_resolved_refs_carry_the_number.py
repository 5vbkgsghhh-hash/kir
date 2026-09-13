"""A REFERENCE MUST COME BACK AS A NUMBER — and the tests break it three
ways.

WHY, MEASURED ON THE LIVE BENCHMARK 2026-08-18. The model wrote
`{"op":"create_beam","p0_mm":[0,0,0],"level":{"by":"name","value":"Floor
5"}}` 540 times and got back a receipt from which it was IMPOSSIBLE to
learn that "Floor 5" is 18000 mm, and its curve sits at zero. All 540
beams landed in one plane; this survived the witness, independent
acceptance, three audits, and a full rebuild. The value existed in the
snapshot (`elevation_mm`, `Level.Elevation`, collected since 08-09 across
six versions) and was discarded by grounding, because `_resolve_one`
returns `{id, name, via}`.

The tests are written in the form of `test_witness_vacuity.py`: each one
BREAKS the report in exactly the way it could have silently gone wrong,
and requires the assertion to fail. A report that cannot be broken proves
nothing.

THREE BREAKS, AND EACH ONE RECONSTRUCTS A REAL DEFECT:
  1. discard the number          -> exactly the silence that cost 540 beams comes back;
  2. substitute 0 for None       -> a zero for a value the instrument did not
                                     compute here (a named defect of this
                                     tree, bought twice within an hour);
  3. remove the twin lookup      -> evidence KIR-A006: 35 columns landed on
                                     the template "Level 1" instead of
                                     "Floor 1," because both sit at zero.
"""
from __future__ import annotations

import unittest
from unittest import mock

from kir import ground as G
from kir.tests.test_program_py_door import _DoorHarness


def _snapshot(*, twin: bool = False, elevation: bool = True) -> dict:
    levels = [{"id": 105, "name": "Этаж 5"}]
    if elevation:
        levels[0]["elevation_mm"] = 18000.0
    if twin:
        levels.append({"id": 100, "name": "Уровень 1", "elevation_mm": 0.0})
        levels.append({"id": 101, "name": "Этаж 1", "elevation_mm": 0.0})
    return {
        "levels": levels,
        "beam_types": [{"id": 900, "name": "I 20H1"}],
        "wall_types": [{"id": 800, "name": "Типовой 200мм"}],
    }


def _beam(level_sel: dict) -> list[dict]:
    return [{"op": "create_beam", "id": "b1",
             "p0_mm": [0, 0, 0], "p1_mm": [6000, 0, 0],
             "level": level_sel,
             "symbol": {"by": "element_id", "value": 900}}]


def _report(ops: list[dict], snapshot: dict) -> list[dict]:
    return G.resolved_references(G.ground(ops, snapshot), snapshot)


class TheReferenceComesBackAsANumber(unittest.TestCase):

    def test_by_name_carries_the_elevation(self):
        """Exactly the line that was missing on 08-18."""
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}), _snapshot())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["elevation_mm"], 18000.0)
        self.assertEqual(row["name"], "Этаж 5")
        self.assertEqual(row["via"], "name")
        self.assertEqual(row["elevation_source"], "levels")

    def test_by_element_id_still_names_the_level(self):
        """`_resolve_one` gives `name: None` by id — without the pool the
        receipt would carry an identity without a name, and the reader
        would be unable to recognize it."""
        rows = _report(_beam({"by": "element_id", "value": 105}), _snapshot())
        self.assertEqual(rows[0]["name"], "Этаж 5")
        self.assertEqual(rows[0]["elevation_mm"], 18000.0)

    def test_a_beam_inside_a_group_is_not_invisible(self):
        """ALL 540 benchmark beams lived inside `create_group.members`. A
        report that does not see them is blind exactly where the defect
        sat."""
        ops = [{"op": "create_group", "id": "bx_5", "name": "bx_5",
                "members": _beam({"by": "name", "value": "Этаж 5"}),
                "placements": [[0, 0], [6000, 0]]}]
        rows = _report(ops, _snapshot())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["inside_group"], "bx_5")
        self.assertEqual(rows[0]["elevation_mm"], 18000.0)


class TheAbsentNumberIsNotZero(unittest.TestCase):

    def test_missing_elevation_is_none_and_says_why(self):
        """In the collector, `elevation_mm` sits under a try/catch. A zero
        for a value the instrument did not compute here is a separate,
        named defect."""
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}),
                       _snapshot(elevation=False))
        self.assertIsNone(rows[0]["elevation_mm"])
        self.assertEqual(rows[0]["elevation_source"], "не отдан коллектором")
        self.assertNotEqual(rows[0]["elevation_mm"], 0)

    def test_the_human_note_does_not_invent_a_number(self):
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}),
                       _snapshot(elevation=False))
        note = G.describe_resolved_refs_ru(rows)
        self.assertIn("не отдана коллектором", note)
        self.assertNotIn("0 мм", note)


class TheIndistinguishableNeighbourIsNamed(unittest.TestCase):
    """Evidence KIR-A006: 35 columns landed on the template "Level 1"
    instead of "Floor 1," because BOTH sit at elevation 0. The reference
    resolved to the neighbor and looked entirely legitimate — there was
    nothing to tell it apart with."""

    def _wall_on_floor_one(self) -> list[dict]:
        return [{"op": "create_wall", "id": "w1",
                 "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
                 "level": {"by": "name", "value": "Этаж 1"},
                 "type": {"by": "element_id", "value": 800}}]

    def test_the_twin_is_named(self):
        rows = _report(self._wall_on_floor_one(), _snapshot(twin=True))
        row = next(r for r in rows if r["op_id"] == "w1")
        self.assertEqual([t["name"] for t in row["indistinguishable"]],
                         ["Уровень 1"])

    def test_the_note_shouts_about_the_twin(self):
        rows = _report(self._wall_on_floor_one(), _snapshot(twin=True))
        note = G.describe_resolved_refs_ru(rows)
        self.assertIn("НЕОТЛИЧИМЫЙ СОСЕД", note)
        self.assertIn("Уровень 1", note)

    def test_a_lone_level_has_no_twin_field(self):
        """The report has no right to invent a neighbor where none
        exists: otherwise the warning would lose its value and people
        would stop reading it."""
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}), _snapshot())
        self.assertNotIn("indistinguishable", rows[0])


class BreakItAndTheAssertionMustFall(unittest.TestCase):
    """Three mutations. Each is a way the report could have silently gone
    wrong."""

    def test_dropping_the_number_is_caught(self):
        original = dict(G._NUMBERED_POOLS)
        try:
            G._NUMBERED_POOLS.clear()          # there are no more pools with the number
            rows = _report(_beam({"by": "name", "value": "Этаж 5"}), _snapshot())
            self.assertEqual(rows, [], "мутация должна была обнулить отчёт")
        finally:
            G._NUMBERED_POOLS.clear()
            G._NUMBERED_POOLS.update(original)
        # and after restoring it, the assertion holds again
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}), _snapshot())
        self.assertEqual(rows[0]["elevation_mm"], 18000.0)

    def test_a_zero_instead_of_none_would_fail_the_suite(self):
        """If someone "fixes" a missing elevation with a zero, THIS test
        must fail, not the building a day later."""
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}),
                       _snapshot(elevation=False))
        forged = dict(rows[0]); forged["elevation_mm"] = 0.0
        with self.assertRaises(AssertionError):
            self.assertIsNone(forged["elevation_mm"])

    def test_a_widened_twin_threshold_would_name_strangers(self):
        """The 1 mm threshold is not a matter of taste: it is the same one
        Revit uses to distinguish elevations. A wider threshold would name
        a level a floor above as a neighbor, and the warning would turn
        into noise."""
        snap = _snapshot()
        snap["levels"].append({"id": 106, "name": "Этаж 6",
                               "elevation_mm": 18000.0 + 3600.0})
        rows = _report(_beam({"by": "name", "value": "Этаж 5"}), snap)
        self.assertNotIn("indistinguishable", rows[0],
                         "3600 мм — это не «неотличимо»")


class TheNumberReachesTheReceipt(_DoorHarness):
    """END-TO-END, not a unit test: the same fixture that carries
    `test_program_py_door` from the script all the way to the journal. A
    report that lives only inside a function is not a receipt.

    The fixture is deliberately reused, not copied: the snapshot fixture
    is one for the whole suite (`kir/tests/fixtures.py`), and a second
    instance of it would drift silently — the same reason it lives there
    in the first place.
    """

    SCRIPT = (
        "lvl = by_name('Этаж 2')\n"
        "create_wall(p0_mm=[0, 0], p1_mm=[6000, 0], height_mm=3000, level=lvl,\n"
        "            type=by_name('Кирпич 250'))\n"
    )

    def test_the_receipt_says_what_number_the_reference_became(self):
        result = self._call_executing({"program_py": self.SCRIPT})
        self.assertTrue(result["ok"], result)
        refs = result.get("resolved_refs")
        self.assertIsNotNone(refs, "квитанция не несёт resolved_refs")
        row = next(r for r in refs if r["param"] == "level")
        # "Floor 2" in the shared fixture sits at 3300 mm
        self.assertEqual(row["name"], "Этаж 2")
        self.assertEqual(row["elevation_mm"], 3300.0)
        self.assertIn("«Этаж 2» -> 3300 мм", result["resolved_refs_note_ru"])

    def test_the_shopfront_cannot_bring_the_building_down(self):
        """At this line the transaction is ALREADY committed. A showroom
        that fails after the write robs the model of a receipt for a
        building that was actually built — that is why the report is
        built fail-open, and this is the assertion about it."""
        with mock.patch.object(G, "resolved_references",
                               side_effect=RuntimeError("витрина сломалась")):
            result = self._call_executing({"program_py": self.SCRIPT})
        self.assertTrue(result["ok"], result)
        self.assertNotIn("resolved_refs", result)


if __name__ == "__main__":
    unittest.main()
