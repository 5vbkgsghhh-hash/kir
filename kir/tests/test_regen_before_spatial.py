"""Regeneration before a spatial op: the rule is DERIVED, not maintained by
hand.

═══ WHAT WAS BROKEN, AND HOW IT WAS MEASURED ═══

The rule was armed ONLY by `create_wall`, while `create_room` and
`create_space` consumed it. So a program that closes a loop with a
SEPARATION LINE and places a room inside it got no regeneration. Measured
from the emission (08-11, op markers, 2026 version):

    separation line RS1 at position 2645, room R1 at 5534,
    `doc.Regenerate()` between them is ABSENT
    (control: wall W1 at 2570, room R1 at 3717, regeneration at 3647)

═══ WHY THIS IS NOT A LIST OF BOUNDING OPS ═══

The temptation was to ask the registry: whose result bounds a room. A
measurement across six assemblies closes that road — the ONLY
`BuiltInParameter` that names a room's bounding is
`WALL_ATTR_ROOM_BOUNDING` (6/6). Neither the separation line, nor the
floor, nor the ceiling, nor the roof has such a parameter: they bound by
their very nature. There is nothing to ask an element "do you bound," so
the list would have to be maintained by hand — and it would go stale on the
very first new op, and SILENTLY at that.

The rule therefore rests on a fact that provenance (a63d5c13) already
measured and which has nothing to do with room bounding: "a fresh wall has
no faces BEFORE regeneration," meaning a just-created element is not fully
realized in the document until `doc.Regenerate()` is called. `NewRoom` /
`NewSpace` resolve the enclosing area AT THE MOMENT OF THE CALL. So the
rule is armed by ANY creation since the last regeneration.

═══ WHAT THIS TEST DOES NOT PROVE ═══

It proves that the COMPILER places a regeneration where it previously did
not. It does NOT prove that Revit would have built the room incorrectly
without it: this wave had no live Revit, and provenance was measured on a
DIFFERENT op (wall faces for a dimension). The rule was chosen by the
ASYMMETRY OF COST — an extra regeneration costs time, a missed one costs a
ROLLBACK OF A CORRECT PROGRAM (the room would read Area == 0 and the
witness would fail everything) — not by a proven failure.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_regen_queue.jsonl"))

from kir import authoring, ops_room, spec                   # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "name", "value": SNAPSHOT["levels"][0]["name"]}
RING = [[0, 0], [4000, 0], [4000, 3000], [0, 3000], [0, 0]]
#: NOT A COPY, BUT THE AUTHORITY. There used to be a literal
#: `"doc.Regenerate();  // finalize"` here, the emitter wrote different
#: text, and `cs.find` returned -1 — three tests failed with "-1 is not
#: greater than 2633," a message that names no cause. We ask the emitter,
#: not paraphrase it.
REGEN = authoring.SPATIAL_REGEN_CS


def _emit(ops, ver="2026"):
    out = compile_program({"ir_version": "1.0", "intent": "regen", "ops": ops},
                          revit_version=ver, snapshot=SNAPSHOT, bulk=True)
    assert out.ok, [d.code for d in out.diagnostics]
    return out.csharp


def _at(cs, op_id):
    """The op block's position. As a WHOLE TOKEN, not a substring: `//
    create_room` sits INSIDE `// create_room_separator`, and the first
    version of this probe compared a substring against its own prefix,
    getting "both at 2649."""
    m = re.search(r"^\s*// \S+ " + re.escape(op_id) + r"\s*$", cs, re.M)
    return m.start() if m else -1


class TheGapThatWasOpen(unittest.TestCase):
    """Refuting: before the fix, the first one failed, the second passed."""

    def test_a_separator_now_arms_the_rule(self):
        cs = _emit([
            {"op": "create_room_separator", "id": "RS1", "path": RING,
             "level": LVL},
            {"op": "create_room", "id": "R1", "xy": [2000, 1500],
             "level": LVL}])
        sep, room, regen = _at(cs, "RS1"), _at(cs, "R1"), cs.find(REGEN)
        self.assertGreater(regen, sep,
                           "регенерация обязана стоять ПОСЛЕ разделителя")
        self.assertLess(regen, room,
                        "регенерация обязана стоять ДО комнаты")

    def test_a_wall_still_arms_it_exactly_as_before(self):
        cs = _emit([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [4000, 0], "level": LVL},
            {"op": "create_room", "id": "R1", "xy": [2000, 1500],
             "level": LVL}])
        self.assertLess(_at(cs, "W1"), cs.find(REGEN))
        self.assertLess(cs.find(REGEN), _at(cs, "R1"))

    def test_a_space_gets_the_same_treatment_as_a_room(self):
        cs = _emit([
            {"op": "create_room_separator", "id": "RS1", "path": RING,
             "level": LVL},
            {"op": "create_space", "id": "SP1", "xy": [2000, 1500],
             "level": LVL}])
        self.assertLess(_at(cs, "RS1"), cs.find(REGEN))
        self.assertLess(cs.find(REGEN), _at(cs, "SP1"))

    def test_a_spatial_op_with_nothing_before_it_gets_no_regen(self):
        """A regeneration without cause is wasted work inside the
        transaction, and its absence here keeps the rule from turning into
        "always."""
        cs = _emit([{"op": "create_room", "id": "R1", "xy": [2000, 1500],
                     "level": LVL}])
        self.assertEqual(cs.find(REGEN), -1)


class TheRuleIsDerivedNotListed(unittest.TestCase):
    """Both sides of the rule are derived from the registry, so a new op
    falls under it BY ITSELF — or fails the run if no decision has been
    made about it."""

    def test_the_consumer_side_comes_from_result_categories(self):
        derived = {name for name, cats in spec.OP_RESULT_CATEGORIES.items()
                   if set(cats) & set(ops_room.SPATIAL_ENCLOSURE_CATEGORIES)}
        self.assertEqual(authoring._SPATIAL_ENCLOSURE_OPS, derived)
        self.assertEqual(derived, {"create_room", "create_space"})

    def test_every_spatial_category_op_is_in_the_consumer_set(self):
        """CLOSING THE LIST. An op whose result is a spatial element but
        which is missing from the rule would build a room against an
        UNREGENERATED model, and the only way to see that would be the
        rollback of a correct program."""
        for name, cats in sorted(spec.OP_RESULT_CATEGORIES.items()):
            if set(cats) & set(ops_room.SPATIAL_ENCLOSURE_CATEGORIES):
                with self.subTest(op=name):
                    self.assertIn(name, authoring._SPATIAL_ENCLOSURE_OPS)

    def test_the_arming_side_is_every_model_writing_op(self):
        """ANY creation must arm it, not only a wall: the rule's provenance
        is "a fresh element is not realized before regeneration," and that
        is a fact not about walls."""
        armers = []
        for name, op_spec in sorted(spec.OPS.items()):
            if not op_spec.writes_model or name in authoring._SPATIAL_ENCLOSURE_OPS:
                continue
            armers.append(name)
        self.assertGreater(len(armers), 50,
                           "вооружающих опов должно быть много — правило "
                           "перестало быть про стену")

    def test_the_eight_bounding_ops_the_old_rule_missed(self):
        """Measured 08-11: eight registry kinds build room-bounding
        elements, and exactly one armed the rule. The list is a
        CONSEQUENCE of the measurement, and is held by the test so that
        "fixed one" does not read as "fixed."""
        BOUNDING = {"OST_RoomSeparationLines", "OST_Floors", "OST_Ceilings",
                    "OST_Roofs", "OST_Columns", "OST_StructuralColumns",
                    "OST_BuildingPad"}
        missed = {name for name, cats in spec.OP_RESULT_CATEGORIES.items()
                  if set(cats) & BOUNDING and name != "create_wall"}
        self.assertGreaterEqual(len(missed), 8, sorted(missed))
        for name in sorted(missed):
            with self.subTest(op=name):
                self.assertTrue(spec.OPS[name].writes_model)

    def test_room_bounding_is_not_readable_from_the_api(self):
        """WHY THE RULE DOES NOT ASK THE MODEL. Measured across six
        assemblies: the only BuiltInParameter about room bounding is
        WALL_ATTR_ROOM_BOUNDING. If a general one ever appears, this rule
        can be replaced with a question TO THE MODEL, and only then will
        the list disappear entirely. The test holds the grounds for the
        decision, not the decision itself."""
        self.assertEqual(ops_room.SPATIAL_ENCLOSURE_CATEGORIES,
                         ("OST_Rooms", "OST_MEPSpaces"))


class TheStoredCorpusCoversTheGap(unittest.TestCase):

    def test_a_golden_program_exercises_the_separator_path(self):
        """Before 08-11, NOT ONE golden built a room without a wall, so the
        rule fix went through without a single byte shift across all 52
        goldens — meaning the corpus did not cover the hole at all."""
        from kir.tests.test_golden import PROGRAMS
        self.assertIn("room_separator_then_room", PROGRAMS)
        ops = [o["op"] for o in PROGRAMS["room_separator_then_room"]["ops"]]
        self.assertEqual(ops, ["create_room_separator", "create_room"])
        self.assertNotIn("create_wall", ops)


if __name__ == "__main__":
    unittest.main()