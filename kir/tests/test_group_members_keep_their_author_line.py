"""A unit member of `unit()` keeps ITS OWN address in the author's
source.

WHAT IS PINNED HERE AND WHAT IS NOT — THAT IS THE MAIN POINT OF THIS
FILE.

ONE fact is pinned: the provenance sidecar carries the line of EVERY
group member under its own key, `members[<id>]`, and this key is
resistant to name collisions.

🔴 DELIBERATELY NOT PINNED: that a refusal PRINTS this line to the
author. Today it does not — `serving._name_the_author_line` looks up
the sidecar by EXACTLY `d.op_id`, and for a member's diagnostic,
`op_id` is the group. Measured 27.08.2026, both sides:

    sidecar            members[wall2] -> [5]      the line is CORRECT
    the refusal prints author_line = 3            the GROUP's line

Pinning this here would be form 52 — a test that is green while the
defect is alive and turns red once it is fixed. So what is checked is
THE DATA, not its absence for the reader, and the boundary is named in
prose, not in an assertion.

WHAT IS MISSING TO CLOSE THE LOOP IS NAMED PRECISELY: one preference in
`serving._name_the_author_line` — when `field_name` starts with
`members[…]`, take `lineage[members[…]]`, and leave `lineage[op_id]` as
the fallback. The file belongs to someone else; the fix is not mine to
make.

WHY THIS MATTERS AT ALL. `unit()` is a technique the course recommends
for an apartment. So a model following our own advice would get, on
refusal, the `with` line instead of the line of the operation that
failed. This is not "there is no address" but a WRONG address: form 44
— nobody argues with a plausible-looking value, and the author would
go off to fix a line that has no error in it.
"""
from __future__ import annotations

import unittest

from kir import dsl


def _run(src: str) -> tuple[dict | None, dict | None]:
    """Execute the script AS A SANDBOX and grab both doors.

    The file name `<kir-script>` is not decoration: `sandbox.author_frames`
    selects frames by EXACTLY this name, and without it the sidecar
    would stay empty — the test would go green on emptiness, checking
    nothing.
    """
    exec(compile(src, "<kir-script>", "exec"), {"__name__": "__main__"})
    return dsl.take_ops(), dsl.take_lineage()


_HEAD = "from kir.dsl import create_wall\nfrom kir.course import unit\n"


def _wall(y: int, extra: str = "") -> str:
    return (f'create_wall(p0_mm=[0,{y}], p1_mm=[1000,{y}], '
            f'level={{"by":"name","value":"L01"}}, height_mm=3000{extra})')


class ЧленНесётСвоюСтроку(unittest.TestCase):

    def setUp(self) -> None:
        dsl.reset()
        dsl.take_lineage()          # isolation: there must be no foreign sidecar here

    def test_each_member_carries_its_own_line(self):
        # lines: 1-2 the header, 3 with, 4/5/6 — three walls on
        # DIFFERENT lines.
        src = _HEAD + "with unit('кв'):\n" + "".join(
            f"    {_wall(y)}\n" for y in (0, 100, 200))
        out, lineage = _run(src)

        self.assertIsNotNone(lineage, "сайдкар пуст — мерить нечего")
        members = [m["id"] for m in out["ops"][0]["members"]]
        self.assertEqual(members, ["wall1", "wall2", "wall3"])

        for oid, expected_line in zip(members, (4, 5, 6)):
            key = f"members[{oid}]"
            self.assertIn(key, lineage,
                          f"адрес члена {oid} не доехал: {sorted(lineage)}")
            self.assertEqual(lineage[key][-1], expected_line,
                             f"{key} назвал не свою строку")

    def test_the_same_name_inside_and_outside_do_not_collide(self):
        """This is exactly what the key was chosen for.

        The inner program has its own `_ids` counter, so `create_wall`
        outside and inside the unit are BOTH called `wall1`. A flat
        merge would substitute a foreign wall's line for the member's.
        """
        src = (_HEAD
               + f"{_wall(0)}\n"              # line 3, the OUTER wall1
               + "with unit('кв'):\n"          # line 4
               + f"    {_wall(500)}\n")        # line 5, the MEMBER wall1
        _out, lineage = _run(src)

        self.assertIn("wall1", lineage)
        self.assertIn("members[wall1]", lineage)
        self.assertEqual(lineage["wall1"][-1], 3)
        self.assertEqual(lineage["members[wall1]"][-1], 5)
        self.assertNotEqual(lineage["wall1"], lineage["members[wall1]"],
                            "две РАЗНЫЕ операции получили один адрес")

    def test_the_group_keeps_its_own_line(self):
        """The group key remains: it addresses the `with` itself, and
        that is a separate fact."""
        src = _HEAD + "with unit('кв'):\n" + f"    {_wall(0)}\n"
        _out, lineage = _run(src)
        self.assertIn("group1", lineage)
        self.assertEqual(lineage["group1"][-1], 3, "группа назвала не строку `with`")

    def test_without_a_group_nothing_is_addressed_as_a_member(self):
        """A DISTINGUISHING NEGATIVE: without a unit, there are NO
        `members[…]` keys at all.

        Without it, the suite would be green even in a tree where
        `members[…]` is stamped onto everything indiscriminately — that
        is, it would not tell an address apart from decoration.
        """
        src = _HEAD + f"{_wall(0)}\n{_wall(100)}\n"
        _out, lineage = _run(src)
        self.assertTrue(lineage)
        self.assertEqual([k for k in lineage if k.startswith("members[")], [])

    def test_as_group_false_addresses_members_plainly(self):
        """`as_group=False` NEVER lost the address — the ops remain in
        the outer scope.

        This is pinned so that a fix to the group does not "unify" this
        path too, along the way: there are no members there, only
        ordinary ops, and their key is the ordinary one.
        """
        src = (_HEAD + "with unit('кв', as_group=False):\n"
               + f"    {_wall(0)}\n")
        _out, lineage = _run(src)
        self.assertIn("wall1", lineage)
        self.assertEqual(lineage["wall1"][-1], 4)
        self.assertEqual([k for k in lineage if k.startswith("members[")], [])


class ФормаАдресаОдна(unittest.TestCase):
    """The sidecar key and the refusal's address are ONE shape, not
    two similar ones.

    A second carrier of the address shape would drift from the first
    at the very first fix; that is a named defect of this tree. So the
    shape is asked of THE COMPILER, rather than checked against a
    literal typed out here.
    """

    def test_the_key_is_the_form_the_compiler_mints(self):
        from kir.compiler import _group_member_diagnostic
        from kir.diag import Diagnostic, TYPE_BAD_TYPE

        minted = _group_member_diagnostic(
            Diagnostic(code=TYPE_BAD_TYPE, field_name="height_mm",
                       message_ru="—"),
            group_id="group1", group_index=0,
            member_id="wall2", member_index=1)

        # the sidecar key is exactly the prefix of the refusal's
        # address, without the field
        self.assertTrue(minted.field_name.startswith("members[wall2]"),
                        f"компилятор чеканит другую форму: {minted.field_name}")
        self.assertEqual(minted.field_name.split(".", 1)[0], "members[wall2]")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
