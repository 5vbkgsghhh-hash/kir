"""ENABLING `KUKAI_IR_OPEN_MODEL_PREFLIGHT` SILENTLY DISABLES A NAMED
DEFAULT.

Found offline on 11.08.2026, on the LIVE path, without Revit. The fork sits
in `serving._handle_revit_ir_inner`:

    if not _open_model_preflight_enabled():
        snapshot = cand                      # RAW bridge dict
    else:
        ...
        snapshot = open_model.to_ground_snapshot()   # via the typed profile

The `instances` counter, on which `ground._most_used` relies, is placed by
emission into the RAW row (`open_model.py`, inside
`if ((__e as FamilySymbol) != null)`). The typed row `ModelCatalogEntry` has
NO field for it, and `to_ground_row()` assembles its answer from an
explicit list of keys that also lacks it. So the "raw -> profile ->
snapshot" loop LOSES the counter.

WHAT THIS MEANS IN PRACTICE. `_most_used` returns `None` if even one pool
row lacks a counter — deliberately, "the old bridge must preserve its
previous behavior byte-for-byte". So with the preflight enabled, EVERY
ambiguity stops getting a named default and `KIR-G102` refuses instead. A
flag whose purpose is to make grounding STRICTER incidentally disables a
delivered capability, and this is reported nowhere.

This is the same class as the whole list in `ir/CLAUDE.md`: a value is
DECLARED in one place (emission puts `instances`) and READ in another (a
typed contract that has no such field), and nothing forces them to agree.
The peculiarity is that the trap is ARMED IN ADVANCE: the preflight is off
by default, they are planning to turn it on, and on the day it is turned on
`most_used` will fall silent.

WHAT THIS TEST DOES NOT CLAIM: it does NOT say the counter must travel in
`binding_digest` — that signs the row's IDENTITY, while the placement count
is its CONTENT (exactly the same caveat applies to the `section` field).
Exactly where to put the counter is a decision, not a consequence; the test
only records that RIGHT NOW it gets lost.
"""
from __future__ import annotations

import unittest

from kir import ground
from kir.open_model import OpenModelProfile


def _raw_snapshot_with_counters() -> dict:
    """A raw dict of exactly the shape the bridge sends: with counters."""
    return {
        "door_symbols": [
            {"id": 101, "name": "ДГ 21-8 П", "unique_id": "u-101",
             "class_name": "FamilySymbol", "category": "OST_Doors",
             "family_name": "Дверь", "type_name": "ДГ 21-8 П",
             "instances": 500},
            {"id": 102, "name": "ДГ 21-9 Л", "unique_id": "u-102",
             "class_name": "FamilySymbol", "category": "OST_Doors",
             "family_name": "Дверь", "type_name": "ДГ 21-9 Л",
             "instances": 272},
        ],
    }


class TheCounterMustSurviveTheTypedRoundTrip(unittest.TestCase):

    def test_most_used_fires_on_the_raw_bridge_snapshot(self) -> None:
        """Control: on the raw dict the rule works, 500 against 272 — that
        is 1.8x, above `MOST_USED_MIN_RATIO`. Without this test the next one
        would be green even for a rule that is completely broken."""
        raw = _raw_snapshot_with_counters()
        chosen = ground._most_used(raw["door_symbols"], "door_symbols", None)
        self.assertIsNotNone(chosen, "правило не сработало на сырых данных")
        self.assertEqual(chosen["id"], 101)
        self.assertEqual(chosen["via"], "most_used")
        self.assertEqual(chosen["rule_detail"]["instances"], 500)
        self.assertEqual(chosen["rule_detail"]["runner_up"], 272)

    def test_the_typed_profile_round_trip_drops_the_counter(self) -> None:
        """REFUTATION. The same snapshot through the typed profile — and the
        rule falls silent, because the row no longer has a counter."""
        raw = _raw_snapshot_with_counters()
        profile = OpenModelProfile.from_ground_snapshot(raw)
        through = profile.to_ground_snapshot()

        rows = through["door_symbols"]
        self.assertEqual(len(rows), 2, rows)
        self.assertTrue(all("instances" not in row for row in rows),
                        f"счётчик неожиданно уцелел: {rows}")

        chosen = ground._most_used(rows, "door_symbols", None)
        self.assertIsNone(
            chosen,
            "правило сработало — значит счётчик доехал, и этот тест пора "
            "снимать вместе с находкой")

    def test_the_entry_contract_has_no_field_for_it(self) -> None:
        """Cause, not symptom: the typed row has no such field.

        Red here = the field was added, and then both checks above must
        turn red along with it — that is the signal that the trap has been
        removed.
        """
        import dataclasses
        from kir.open_model import ModelCatalogEntry

        fields = {f.name for f in dataclasses.fields(ModelCatalogEntry)}
        self.assertNotIn("instances", fields)
        self.assertNotIn("instance_count", fields)


if __name__ == "__main__":
    unittest.main()
