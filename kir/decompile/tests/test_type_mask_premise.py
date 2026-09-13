"""CONTROL OF THE PREMISE "first-instance mask = type mask".

🔴 THIS FILE EXISTS SO THAT THE PREMISE CANNOT BE ACCEPTED AGAIN.

It stood in `axes_census.BLIND_SPOTS` as "not proven, but accepted," and on
it rests the ×4.4…×20.9 multiplier of the "type first" protocol.
Measurement on 15.08.2026 across four buildings REFUTED it, and the
failure runs in the dangerous direction: an instance can carry a key that
the first one did not have, and the live protocol will NOT ASK about it —
the value will leave L0 SILENTLY.

    sob62_r23_v5      1 type out of 71,    7 keys,   0.46 % of elements
    k2_ar_rd_v8       6 types out of 486, 2908 keys, 1.27 % of elements

A MECHANISM, not chance: `WALL_HEIGHT_TYPE` (the wall-top binding) is
present on 7 instances of one type and absent on 5, because the top is
bound to a level not for all of them. The existence of the parameter is a
property of INSTANCE STATE.

WHAT THESE TESTS SPECIFICALLY HOLD. Not the count of discrepancies on the
corpus — the corpus is machine-local, and a test that requires it will say
"clean" on someone else's machine exactly where it simply saw nothing.
They hold TWO things, both checkable anywhere:

 1. the census COUNTS the discrepancy and returns it alongside the
    multiplier;
 2. on an input with a discrepancy it FINDS that discrepancy, and on one
    without — it does not invent one. Control in both directions: a test
    that turns red in only one direction does not distinguish a working
    instrument from one that always cries wolf.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir.decompile import axes_census


def _l0(path: pathlib.Path, elements: list[dict]) -> None:
    """Minimal L0: only element records — the census requires nothing more."""
    with path.open("w", encoding="utf-8") as handle:
        for element in elements:
            handle.write(json.dumps({"record": "element", "element": element}) + "\n")


def _element(eid: str, type_id: str, params: dict) -> dict:
    return {"element_id": eid, "type_id": type_id, "category": "OST_Walls",
            "type_name": "T", "params": params}


class ПерепaverСчитаетЦенуПремиссы(unittest.TestCase):
    """A discrepancy must reach the report line, not stay in someone's head."""

    def _census(self, elements: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            directory = pathlib.Path(tmp)
            _l0(directory / "L0.jsonl", elements)
            row = axes_census.census(directory, budget=38)
        assert row is not None, "перепись отказалась читать собранный L0"
        return row

    def test_расхождение_найдено_когда_оно_есть(self):
        """The second instance carries a key that the first one did not have.

        This is exactly the `WALL_HEIGHT_TYPE` case: the live protocol
        will not ask about it.
        """
        row = self._census([
            _element("1", "T1", {"A": 1, "B": 2}),
            _element("2", "T1", {"A": 1, "B": 2, "WALL_HEIGHT_TYPE": 9}),
        ])
        self.assertEqual(row["mask_diverged_types"], 1)
        self.assertEqual(row["mask_lost_keys"], 1)
        self.assertEqual(row["mask_lost_instances"], 1)

    def test_расхождения_НЕТ_когда_маски_совпадают(self):
        """CONTROL IN THE REVERSE DIRECTION.

        Without it the previous test cannot distinguish an instrument
        that COUNTS from one that always cries wolf. Exactly the form
        this file is devoted to: green without an act of discrimination.
        """
        row = self._census([
            _element("1", "T1", {"A": 1, "B": 2}),
            _element("2", "T1", {"A": 7, "B": 8}),
        ])
        self.assertEqual(row["mask_diverged_types"], 0)
        self.assertEqual(row["mask_lost_keys"], 0)

    def test_лишний_ключ_у_первого_НЕ_считается_потерей(self):
        """The first has the key, the second does not — that is an extra probe, not a loss.

        The difference costs differently: overspend is visible in the
        count, a loss is visible to NO ONE. Conflating them would lose the
        very distinction this counter exists for.
        """
        row = self._census([
            _element("1", "T1", {"A": 1, "B": 2}),
            _element("2", "T1", {"A": 1}),
        ])
        self.assertEqual(row["mask_lost_keys"], 0,
                         "избыток у первого посчитан как потеря")

    def test_потеря_копится_по_всем_экземплярам(self):
        row = self._census([
            _element("1", "T1", {"A": 1}),
            _element("2", "T1", {"A": 1, "X": 2}),
            _element("3", "T1", {"A": 1, "Y": 3}),
        ])
        self.assertEqual(row["mask_lost_keys"], 2)
        self.assertEqual(row["mask_lost_instances"], 2)
        self.assertEqual(row["mask_diverged_types"], 1)


class ГраницаНазываетОпровержение(unittest.TestCase):
    """The instrument must CARRY the refutation, not merely remember it.

    The number ×20.9 will outlive any conversation; the text next to it is
    the only thing that keeps it from being read as a work plan.
    """

    def test_границы_называют_премиссу_опровергнутой(self):
        text = axes_census.BLIND_SPOTS
        self.assertIn("ОПРОВЕРГНУТА", text)
        self.assertIn("WALL_HEIGHT_TYPE", text,
                      "механизм не назван — останется догадкой")
        self.assertIn("ВЕРХНЯЯ ГРАНИЦА", text,
                      "не сказано, чем стали два множителя после опровержения")

    def test_границы_называют_и_вторую_половину(self):
        """A dead pair is a fact about the PROJECT, not about the Revit schema.

        Measured across four buildings: 19 live pairs in the union, 4
        common to all. A static list taken from one project would discard
        live ones on another.
        """
        self.assertIn("ФАКТ О ПРОЕКТЕ", axes_census.BLIND_SPOTS)


if __name__ == "__main__":
    unittest.main()
