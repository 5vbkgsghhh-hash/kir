"""A refusal on a unit's member prints the line of the FAILED operation,
not the line of `with`.

🔴 THIS WAS A WRONG ADDRESS, NOT A MISSING ONE, AND THE DIFFERENCE IS
DECISIVE. Measurement of 27.08.2026 before the fix, verbatim:

    sidecar          members[wall2] -> [5]      the line is CORRECT
    the refusal printed  author_line = 3        the line of `with`

A loss stays silent, a substitution LIES: the author would go fix a line
that has no error in it (form 44 — a plausible value is not argued with).
And `unit()` is a technique the course RECOMMENDS for an apartment, so the
hole sat on the recommended path.

WHAT IS PINNED HERE IS THE READ. The data is pinned by the neighbor
(`test_group_members_keep_their_author_line`): the sidecar carries a
member under the key `members[<id>]`. This file guards the other half —
that the reader (`serving._frames_for`) PREFERS this key, leaving the
group's key as a fallback.

THE SHAPE OF THE ADDRESS IS NOT TYPED OUT EITHER HERE OR IN THE READER. It
is minted by `compiler._group_member_diagnostic`, which already has THREE
carriers; a fourth literal would drift from them at the first edit. The
reader asks the minter (`serving._member_path_shape`), and this file
checks what it asks.
"""
from __future__ import annotations

import unittest
from unittest import mock

from kir import compiler, dsl
from kir.diag import Diagnostic, TYPE_BAD_TYPE
from kir.serving import (_frames_for, _member_path_shape,
                         _name_the_author_line)

_SNAP = {"levels": [{"id": 1, "name": "L01"}]}

#: Three walls in a LOOP inside a unit, the error is in the SECOND one.
#: Line numbers matter: `with` is on line 3, the wall call is on line 5.
_IN_UNIT = '''from kir.dsl import create_wall
from kir.course import unit
with unit("кв"):
    for h in [3000, "высокая", 3000]:
        create_wall(p0_mm=[0,0], p1_mm=[1000,0], level={"by":"name","value":"L01"}, height_mm=h)
'''

#: The same error OUTSIDE a unit: the fallback path must remain intact.
#: The wall fails on line 3.
_NO_UNIT = '''from kir.dsl import create_wall
create_wall(p0_mm=[0,0], p1_mm=[1000,0], level={"by":"name","value":"L01"}, height_mm=3000)
create_wall(p0_mm=[0,0], p1_mm=[1000,0], level={"by":"name","value":"L01"}, height_mm="высокая")
'''


def _refuse(src: str) -> tuple[list[dict], dict, object]:
    """Execute AS A SANDBOX, compile, read the refusal.

    The file name `<kir-script>` is not decoration: `sandbox.author_frames`
    selects frames by matching it EXACTLY. Without it the sidecar would be
    empty, and this whole file would pass green on emptiness, having
    checked nothing.
    """
    dsl.reset()
    dsl.take_lineage()                      # isolation from someone else's sidecar
    exec(compile(src, "<kir-script>", "exec"), {"__name__": "__main__"})
    ops, lineage = dsl.take_ops(), dsl.take_lineage()
    out = compiler.compile_program(ops, revit_version="2023",
                                   snapshot=_SNAP, bulk=True)
    assert not out.ok, "фикстура обязана ОТКАЗАТЬ, иначе тест ни о чём"
    named = _name_the_author_line(out.diagnostics, lineage,
                                  source={3: "with unit(…)", 5: "create_wall(…)"})
    return named, lineage, out.diagnostics[0]


class ЧитательПредпочитаетЧлена(unittest.TestCase):

    def test_the_refusal_names_the_line_of_the_failing_member(self):
        named, lineage, diag = _refuse(_IN_UNIT)

        # preconditions — so that red speaks about the SUBJECT, not the fixture
        self.assertEqual(diag.op_id, "group1",
                         "фикстура не дала диагностику ЧЛЕНА")
        self.assertEqual(lineage.get("group1"), [3],
                         "групповой ключ съехал — строки ниже проверяют не то")

        self.assertEqual(named[0].get("author_line"), 5,
                         f"назвал не ту строку: {named[0].get('author_line')}")
        self.assertNotEqual(named[0].get("author_line"), 3,
                            "напечатана строка `with`, а не упавшей операции")
        self.assertIn("строка 5", named[0]["message_ru"])

    def test_the_group_line_stays_reachable(self):
        """The group address is not discarded: it addresses `with` itself."""
        _named, lineage, _d = _refuse(_IN_UNIT)
        self.assertEqual(lineage.get("group1"), [3])

    def test_an_op_outside_a_unit_still_finds_its_own_line(self):
        """THE FALLBACK PATH IS INTACT. Otherwise fixing the member would break everything else."""
        named, lineage, diag = _refuse(_NO_UNIT)
        self.assertEqual(diag.field_name, "height_mm",
                         "фикстура дала диагностику НЕ верхнего опа")
        self.assertEqual(named[0].get("author_line"), 3)
        self.assertNotIn("members[", " ".join(lineage))


class КонтрольFAIL(unittest.TestCase):
    """The preference LOAD-BEARS: without it the address falls back to the
    group.

    The mutation hits the SHAPE asked of the minter: an empty prefix turns
    off the member branch, leaving the fallback path untouched. This is
    exactly what it was before the fix — meaning a red here is a red FOR
    THE RIGHT REASON, not for a missing key in the sidecar.
    """

    def test_without_the_preference_the_address_returns_to_the_group(self):
        _member_path_shape.cache_clear()
        with mock.patch("kir.serving._member_path_shape",
                        return_value=("", "")):
            named, _lineage, _d = _refuse(_IN_UNIT)
        _member_path_shape.cache_clear()
        self.assertEqual(named[0].get("author_line"), 3,
                         "мутация не вернула прежнее поведение — она бьёт "
                         "не по тому, и контроль ничего не различает")


class ФормаСпрошенаУЧеканщика(unittest.TestCase):

    def test_the_shape_is_minted_not_typed(self):
        """The shape wrapper is the same one the compiler mints for a live member."""
        head, tail = _member_path_shape()
        minted = compiler._group_member_diagnostic(
            Diagnostic(code=TYPE_BAD_TYPE, field_name="height_mm",
                       message_ru="—"),
            group_id="g", group_index=0, member_id="wall2", member_index=1)
        path = minted.field_name.split(".", 1)[0]
        self.assertTrue(path.startswith(head) and path.endswith(tail),
                        f"читатель и чеканщик разошлись: {head!r}…{tail!r} "
                        f"против {path!r}")

    def test_a_plain_op_named_like_a_field_does_not_steal_the_address(self):
        """A DISCRIMINATOR WITHOUT WHICH THE FIX WOULD INTRODUCE ITS OWN
        FORM 44.

        A bare cut at the first dot would take `contour` out of the
        compound field `contour.holes` — and if the author named THEIR OWN
        op that way, the refusal would print the line of someone else's
        operation. Plausible and wrong.
        """
        d = Diagnostic(code=TYPE_BAD_TYPE, field_name="contour.holes",
                       message_ru="—", op_id="F1")
        frames = _frames_for(d, {"contour": [9], "F1": [4]})
        self.assertEqual(frames, [4],
                         "первый сегмент составного поля украл адрес")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
