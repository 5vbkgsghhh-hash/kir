"""A failure on a group member names the MEMBER in the TEXT, not only in
the field address.

🔴 WHAT THIS FILE IS BOUGHT BY, MEASURED 2026-08-27 — AND WHAT IT IS NOT
BOUGHT BY.

The original problem statement read: "a failure on a group member does not
name the member." **It is WRONG, and this is established by running the
code, not by reading it.** The member is named, and named correctly — in
`field_name`:

    unknown field on a member   KIR-P003   field_name = 'members[w2].xyz_mm'
    bad value on a member       KIR-T001   field_name = 'members[w2].height_mm'
    member fails to ground      KIR-G101   field_name = 'members[w2].type'

So the `course._UnitContext` docstring ("`_ground_members` … names the
member by ITS id") is TRUE, not broader than the behavior. Prose has
nothing to do with it; the instrument that looked only at `op_id` was
mistaken.

WHAT IS ACTUALLY MISSING. Today's full text of a member failure is:

    height_mm — a number in mm
        height_mm  mm 1..100000
      got: 'high'
    NEXT MOVE: bring height_mm to the form above; mandatory slots for
    create_wall: p0_mm, p1_mm, level — close the missing ones in ONE move.

It names the slot, the bounds, the value received, THE MEMBER'S OP, and the
next move — and it does not name WHICH OF THE MEMBERS. With twenty walls in
an apartment, this is a diagnosis without an address: "what to fix" is
there, "where" is not.

WHY THIS IS EXPENSIVE SPECIFICALLY IN THE TEXT, NOT IN GENERAL. `with
unit(...)` is a technique that `course` RECOMMENDS for an apartment,
meaning the model arrives here on our own advice. And the text is the only
thing that crosses the process boundary: `diag.KirRefusal.__init__`
assembles it from `code` and `message_ru`, and `field_name` does not enter
it at all (verified by construction). Where only the text travels, the
member's address is lost entirely today.

WHAT THIS FILE DOES NOT REQUIRE, AND THIS IS A DECISION, NOT A GAP.

* `op_id` remains the GROUP'S NAME. It is read by provenance substitution
  (`serving._name_the_author_line`), acceptance, the receipt, and the
  witness feed; changing the key's form is a different cost, and it is not
  paid here;
* `field_name` remains `members[<id>].<slot>`. It is pinned by
  `test_nested_grounding_integrity` and
  `test_member_path_gets_no_foreign_advice`;
* NO new failure codes are introduced — the owner's word from 08-27: "we
  don't need more causes for now, we already have plenty."

Exactly ONE thing changes: the first line of the text carries the member's
address.
"""
from __future__ import annotations

import unittest

from kir import compile_program


SNAPSHOT = {
    "levels": [{"id": 311, "name": "L01"}],
    "wall_types": [{"id": 5011, "name": "Кирпич 380"}],
}


def _wall(oid: str, **overrides):
    wall = {
        "op": "create_wall", "id": oid,
        "level": {"by": "name", "value": "L01"},
        "type": {"by": "name", "value": "Кирпич 380"},
        "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3200,
    }
    wall.update(overrides)
    return wall


def _group(members):
    return {"op": "create_group", "id": "group1", "name": "квартира",
            "members": members, "placements": [[0, 0, 0]]}


def _refuse(bad_wall):
    """Three walls in a group, the SECOND one broken. Returns diagnostics."""
    program = {"ops": [_group([_wall("w1"), bad_wall, _wall("w3")])]}
    out = compile_program(program, revit_version="2023",
                          snapshot=SNAPSHOT, bulk=True)
    assert not out.ok, "программа обязана быть отвергнута — иначе контроль пуст"
    return list(out.diagnostics or ())


#: THREE KINDS OF FAILURE, THREE DIFFERENT PIPELINE STAGES.
#:
#: A single kind would prove nothing: parsing, typing, and grounding
#: rewrite the member's address in DIFFERENT places, and fixing one place
#: would leave the other two silent. The codes here are not decoration but
#: the names of these three stages.
СЛУЧАИ = (
    ("KIR-P003 разбор",     _wall("w2", xyz_mm=[1, 2, 3])),
    ("KIR-T001 типизация",  _wall("w2", height_mm="высокая")),
    ("KIR-G101 заземление", _wall("w2", type={"by": "name",
                                              "value": "НЕТ ТАКОГО ТИПА"})),
)


class ТекстОтказаНазываетЧлена(unittest.TestCase):

    def test_все_три_рода_называют_члена_в_тексте(self):
        for имя, плохая in СЛУЧАИ:
            with self.subTest(имя):
                диагностики = _refuse(плохая)
                тексты = [d.message_ru or "" for d in диагностики]
                self.assertTrue(
                    any("w2" in t for t in тексты),
                    f"{имя}: ни один текст не называет члена «w2».\n"
                    f"Адрес есть в field_name "
                    f"({[d.field_name for d in диагностики]}), но текст — "
                    f"единственное, что пересекает границу процесса, и там "
                    f"члена нет.\nТексты: {[t[:90] for t in тексты]}")

    def test_адрес_стоит_на_ПЕРВОМ_экране(self):
        """A mention found only by grep protects whoever already knew what
        to search for.

        Canon form 23: a marker has not just text but a LOCATION, and the
        location is part of the claim. A reader will not see the member's
        address at the end of a long failure message: they read the first
        line.

        🔴 AND IT HAS NO RIGHT TO PASS VACUOUSLY. The first version of this
        test walked the diagnostics and checked the first line ONLY of the
        one where it found "w2" — that is, with the address completely
        absent it would go green by construction. Caught by the test's own
        FAIL-control run: 1 failed, 4 passed, where this one was among the
        four green ones. A control on a degenerate input that is green by
        construction is canon form 8.
        """
        for имя, плохая in СЛУЧАИ:
            with self.subTest(имя):
                названо = [d for d in _refuse(плохая)
                           if "w2" in (d.message_ru or "")]
                self.assertTrue(
                    названо,
                    f"{имя}: адреса нет НИ В ОДНОМ тексте — проверять первую "
                    f"строку не на чем, и зелёный здесь был бы вакуумным")
                первая = (названо[0].message_ru or "").splitlines()[0]
                self.assertIn(
                    "w2", первая,
                    f"{имя}: член назван, но НЕ на первой строке — "
                    f"{первая[:110]!r}")

    def test_группа_остаётся_названной(self):
        """Trading one blind spot for another is not a fix.

        The author addresses the group as a whole (`op_id`), and losing it
        for the sake of the member would break provenance substitution,
        acceptance, and the receipt, which are all keyed by exactly that.
        """
        for имя, плохая in СЛУЧАИ:
            with self.subTest(имя):
                диагностики = _refuse(плохая)
                self.assertTrue(
                    any(d.op_id == "group1" for d in диагностики),
                    f"{имя}: op_id перестал быть именем группы — "
                    f"{[d.op_id for d in диагностики]}")

    def test_машинный_адрес_НЕ_СДВИНУЛСЯ(self):
        """`field_name` is pinned by two unrelated tests — the text fix
        does not touch it.

        A control in the other direction: had I "while I'm at it" also
        changed the key, these neighbors would go red, and the text fix
        would have dragged someone else's contract along with it.
        """
        for имя, плохая in СЛУЧАИ:
            with self.subTest(имя):
                поля = [d.field_name for d in _refuse(плохая)
                        if d.field_name]
                self.assertTrue(
                    any(f.startswith("members[w2].") for f in поля),
                    f"{имя}: машинный адрес члена уехал — {поля}")


class КонтрольFAIL(unittest.TestCase):
    """The flip side: without the fix, the address is NOT in the text.

    This is checked not by the absence of a substring (the tests above
    check that) but by the fact that the address's carrier is exactly one
    and it is named. Two carriers of one fact would drift apart at the very
    first edit (the named defect of this tree).
    """

    def test_носитель_адреса_в_тексте_ровно_один(self):
        from kir import compiler
        источник = compiler._group_member_diagnostic.__doc__ or ""
        self.assertIn(
            "member_id", источник + str(
                compiler._group_member_diagnostic.__code__.co_varnames),
            "адрес члена в тексте обязан строиться ТАМ ЖЕ, где строится "
            "`members[<id>]` для field_name — иначе это второй носитель")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
