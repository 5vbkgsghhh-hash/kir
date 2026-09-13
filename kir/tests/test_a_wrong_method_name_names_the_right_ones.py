"""A miss on a building or catalog METHOD name is obligated to name the ones that exist.

🔴 MEASUREMENT 2026-08-25. A sweep of every surface available to the script
found the last unfixable refusal of the kind "the model is right, nothing to fix":

    model.wall_types()  ->  AttributeError: 'ModelCatalog' object has no
                            attribute 'wall_types'   (KIR-B006, blame=author)

The blame is named CORRECTLY — the method really does not exist, it was made
up. The FORM is unfit: the refusal does not name a single one of the
existing names. The model goes into the next turn to guess, and it has
nowhere to guess from — the catalog is closed and it cannot enumerate it
with anything but `dir()`, which does not exist in the sandbox.

THE PROJECT HAS LONG HAD A FORM OF ANSWER FOR THIS, AND IT WAS NOT APPLIED
HERE. `_resolve` in the course answers «рецепт «X» не существует. Есть:
витраж, здание, санузел…»; `_op_spec_of` answers «БЛИЖАЙШИЕ ПО НАПИСАНИЮ: …».
The reasoning there is on record: a refusal with no list is a second round —
the model will not guess the spelling, it will try a synonym.

THE BLAME STAYS ON THE AUTHOR, and that is checked right here: a made-up
name is not our own reading gap, and it must not be confused with
`KIR-B015`. What gets fixed is the FORM, not the address of the repair.
"""
from __future__ import annotations

import unittest

from kir import building_index as bi
from kir.sandbox import execute_author_script


class _El:
    def __init__(self, eid):
        self.element_id, self.category = eid, "OST_Walls"
        self.level_name, self.type_name = "L1", "К200"
        self.p0_mm = self.bbox_min_mm = (0, 0, 0)
        self.p1_mm = self.bbox_max_mm = (1000, 0, 0)
        self.host_id, self.params = None, {}


class ПромахМетодаНазываетСуществующие(unittest.TestCase):

    def test_каталог_называет_свои_методы(self) -> None:
        d = execute_author_script('print(model.wall_types())\n').refusal
        текст = d.message_ru or ""
        self.assertIn("wall_types", текст, "промах назван дословно")
        for имя in ("levels", "grids", "pools"):
            self.assertIn(имя, текст,
                          f"существующий метод `{имя}` не назван — модели "
                          f"нечем починиться, и она пойдёт угадывать")

    def test_здание_называет_свои_методы(self) -> None:
        d = execute_author_script(
            'print(building.walls())\n',
            building=bi.build_index([_El("1")])).refusal
        текст = d.message_ru or ""
        self.assertIn("walls", текст)
        for имя in ("find", "found", "census", "levels"):
            self.assertIn(имя, текст, f"существующий метод `{имя}` не назван")

    def test_вина_остаётся_авторской(self) -> None:
        """A made-up name is NOT our own reading gap.

        Confusing it with `KIR-B015` would mean telling the model "this isn't
        yours" in a place where fixing it is exactly its job. The address of
        the repair is correct here and does not change — only the form is fixed.
        """
        d = execute_author_script('print(model.wall_types())\n').refusal
        self.assertEqual(d.blame, "author")
        self.assertNotEqual(d.code, "KIR-B015")

    def test_существующее_имя_работает(self) -> None:
        """CONTROL: `__getattr__` must not intercept live methods.

        Without this, everything above would go green on a surface that
        always refuses — and that would be a fix worse than the defect.
        """
        r = execute_author_script(
            'print("УРОВНЕЙ", len(building.levels()))\n'
            'create_wall(p0_mm=[0,0], p1_mm=[1,0], level="L1")\n',
            building=bi.build_index([_El("1")]))
        self.assertTrue(r.ok, r.refusal and r.refusal.render())
        self.assertIn("УРОВНЕЙ 1", r.stdout)

    def test_несуществующее_приватное_имя_тоже_названо(self) -> None:
        """A miss is a miss, no matter how the name looks.

        🔴 THE FIRST EDITION OF THIS TEST WAS WRONG, and it is worth
        recording: it took `model._pools` — a name that DOES EXIST (it is in
        `__slots__`). There is no miss there, `__getattr__` is never called
        at all, and the test went red on correct code. What must be checked
        is something absent, not something that merely looks internal.
        """
        d = execute_author_script('print(model._нет_такого_поля)\n').refusal
        self.assertIn("_нет_такого_поля", (d.message_ru or ""))
        self.assertEqual(d.blame, "author")


if __name__ == "__main__":
    unittest.main()
