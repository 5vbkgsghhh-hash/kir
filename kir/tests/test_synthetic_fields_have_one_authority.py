"""Compiler synthetic fields: ONE authority, five readers.

WHAT THIS FIELD IS AND WHY THE TEST. `__host_wall__` is the host's shape,
lifted by the plan from the actual wall of the same program and passed to
the emitter. The author cannot write it: the language has no such slot.
Before 12.08.2026 the name lived as a LITERAL in four places — the writer
`compiler.hosted_offset_check` and three readers (`midend`, `effects`,
`authoring`) — and nothing forced them to agree.

**THE COST OF THE GAP WAS NOT COSMETIC.** A fifth place that was supposed to
know the field had no literal for it at all — op parsing
(`compiler._validate_op`). Group members pass through the plan TWICE (the
second time from `ground._ground_members`); the first pass attached the
field, the second refused it with KIR-P003 "unknown field". The result:
**a floor with walls AND doors would not assemble into a group AT ALL** —
`KIR-T001` — even though 41.1% of the elements of the real tower live in
groups.

THE KIND OF LIST: `SYNTHETIC_FIELDS` — **CLOSED, NOT COMPLETE BY
CONSTRUCTION.** There is no one to compute it from: a synthetic field
appears when someone writes an assignment inside an op, not when it is
declared. So completeness is held not by inference but by
`test_no_second_authority_hides_in_the_tree`: a literal of such a name is
permitted EXACTLY ONCE in the non-test tree, and it is in the authority
itself. Should someone introduce a second synthetic field by literal, the
test will go red.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from kir import compiler, sandbox, spec
from kir.tests.test_course import GROUND_SNAPSHOT, POLICY, _program

IR_ROOT = pathlib.Path(__file__).resolve().parents[1]

LVL = {"by": "name", "value": "Этаж 1"}
WALL = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0], "p1_mm": [5000, 0],
        "level": LVL, "height_mm": 3000}
#: The fake is DELIBERATELY far from the real wall: if it ever reaches the
#: emitter, the coordinate 999000 will land in the C# and cannot be mistaken
#: for anything else.
FORGED = {"p0_mm": [999000, 999000], "p1_mm": [999000, 1000000]}


def _program_json(ops):
    return {"ir_version": spec.IR_VERSION, "intent": "контроль", "ops": ops}


class TheAuthorityIsSingle(unittest.TestCase):
    def test_every_owner_is_a_real_op(self):
        for field, owners in spec.SYNTHETIC_FIELDS.items():
            self.assertTrue(owners, f"{field}: владельцев ноль — запись мёртвая")
            for op in owners:
                self.assertIn(op, spec.OPS,
                              f"{field}: владелец {op!r} не оп реестра")

    def test_no_synthetic_name_collides_with_a_registry_slot(self):
        """The synthetic name must not collide with an author's slot.

        Otherwise stripping at parse time would eat a field the author is
        ENTITLED to supply, and that would be a silently-wrong outcome
        instead of a refusal.
        """
        slots = {p.name for op in spec.OPS.values() for p in op.params}
        for field in spec.SYNTHETIC_FIELDS:
            self.assertNotIn(field, slots,
                             f"{field} совпал с параметром реестра")

    def test_no_second_authority_hides_in_the_tree(self):
        """A literal of the name is permitted EXACTLY ONCE — in the
        authority itself.

        FAIL CONTROL for this test: put the literal back in any of the five
        spots (`midend`, `effects`, `authoring`, `compiler` × 2) — the count
        becomes 2.
        """
        for field in spec.SYNTHETIC_FIELDS:
            needle = f'"{field}"'
            hits = []
            for path in IR_ROOT.rglob("*.py"):
                if "tests" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                if needle in text:
                    hits.append(
                        f"{path.relative_to(IR_ROOT)}:{text.count(needle)}")
            self.assertEqual(
                hits, [f"registry_base.py:1"],
                f"{field}: литерал имени обязан быть ровно один и в власти; "
                f"нашлось: {hits}")


class TheFieldCannotBeSuppliedFromOutside(unittest.TestCase):
    """Parsing STRIPS the field, and the plan re-derives it from the actual
    wall.

    🔴 THE BOUNDARY OF THE FIRST TEST, NAMED HONESTLY, BECAUSE THE NAME
    PROMISES MORE. It shows that the fake does NOT reach the emitter. It
    does NOT show that we owe this to the stripping: the mutation "accept
    the field instead of stripping it" left all six tests green — on this
    path `hosted_offset_check` overwrites the value with the real wall
    anyway, so accept and strip are INDISTINGUISHABLE here. This was
    checked by direct mutation, not by reasoning.

    So the choice of stripping is justified not by this test but by the
    order of remedies (`registry_base.SYNTHETIC_FIELDS`): re-derivation
    happens at two spots, both conditional, and the path outside both
    conditions is neither built nor proven unreachable. The test holds the
    CONSEQUENCE, and that is work too — but let no one read it as proof
    that stripping is necessary.
    """

    def test_a_forged_host_shape_never_reaches_the_emitter(self):
        door = {"op": "create_door", "id": "d1",
                "host": {"by": "ref", "value": "w1"}, "offset_mm": 1500,
                spec.SYNTHETIC_HOST_WALL: FORGED}
        res = compiler.compile_program(
            _program_json([WALL, door]), revit_version="2024",
            snapshot=GROUND_SNAPSHOT, bulk=True)
        self.assertTrue(res.ok, [d.message_ru for d in (res.diagnostics or [])])
        cs = res.csharp or ""
        self.assertNotIn("999000", cs, "подделка доехала до эмиттера")
        self.assertIn("5000", cs, "настоящая стена не доехала — зонд слеп")

    def test_the_field_on_a_non_owner_op_is_still_refused(self):
        """A FAIL CONTROL for the stripping: we strip ONLY from owners.

        `__host_wall__` on `create_wall` belongs to no one, and KIR-P003
        must remain — otherwise stripping would turn into a refusal
        silencer.
        """
        bad = dict(WALL)
        bad[spec.SYNTHETIC_HOST_WALL] = FORGED
        res = compiler.compile_program(
            _program_json([bad]), revit_version="2024",
            snapshot=GROUND_SNAPSHOT, bulk=True)
        self.assertFalse(res.ok)
        codes = {d.code for d in (res.diagnostics or [])}
        self.assertIn("KIR-P003", codes)


class AFloorWithDoorsIsOneGroup(unittest.TestCase):
    """THE NUMBER THAT CLOSES `KIR-T001`.

    A door addresses its wall only via `ref`; as long as a group member
    could not reference a neighbor, a floor with walls AND doors was
    ungroupable BY CONSTRUCTION, and all that remained was enumeration
    running into the ceiling of 300.
    """

    SCRIPT = ('LVL = {"by": "name", "value": "Этаж 1"}\n'
              'with unit("Блок", placements=[(3000, 0), (6000, 0)]):\n'
              '    w = create_wall(p0_mm=(0, 0), p1_mm=(5000, 0), '
              'level=LVL, height_mm=3000)\n'
              '    create_door(host=w, offset_mm=1500)\n'
              '    create_window(host=w, offset_mm=3500, sill_mm=900)\n')

    def test_it_compiles_on_every_version(self):
        result = sandbox.execute_author_script(self.SCRIPT, policy=POLICY)
        self.assertTrue(result.ok,
                        result.refusal and result.refusal.render())
        program = _program(result)
        for version in spec.REVIT_VERSIONS:
            with self.subTest(version=version):
                res = compiler.compile_program(
                    program, revit_version=version,
                    snapshot=GROUND_SNAPSHOT, bulk=True)
                self.assertTrue(
                    res.ok,
                    [d.message_ru for d in (res.diagnostics or [])])
                names = set(re.findall(r"__el_[A-Za-z0-9_]+", res.csharp or ""))
                # Three members, each in the namespace of its own group.
                self.assertEqual(
                    len({n for n in names if "__m__" in n}), 3, sorted(names))


if __name__ == "__main__":
    unittest.main()
