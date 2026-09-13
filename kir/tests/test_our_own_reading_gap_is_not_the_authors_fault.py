"""A gap in OUR OWN reading must never arrive at the model as its fault.

🔴 MEASURED 25.08.2026, BY A RUN THROUGH THE SANDBOX. Five questions about
the model and the building, to which we never read an answer, arrived
indistinguishable from `1/0`:

    probe                    code       BLAME    text
    building not supplied    KIR-B006   author   building index not supplied…
    census not supplied      KIR-B006   author   building index not supplied…
    building levels          KIR-B006   author   building index not supplied…
    catalog not supplied     KIR-B006   author   document catalog not supplied…
    element by address       KIR-B006   author   building index not supplied…
    CONTROL 1/0              KIR-B006   author   division by zero

Meanwhile the refusal text says THE EXACT OPPOSITE, verbatim: "This is a fact
about OUR reading, not about the building." The prose knew the truth, the
blame field lied.

WHY THIS IS COSTLY. `blame` is documented right there: "author — fix the
model." A modeler, getting "author" on a correct script, will go rewrite
it — and will not fix anything, because there is nothing to fix: the index
was not supplied BY US, whether in an offline run or at a turn where the
plugin has not yet sent context. One whole turn of the loop burns for
nothing, and the next one burns the same way.

THIS IS A NAMED FORM ALREADY BOUGHT BY THE TREE ON 24.08: an instrument's
blindness about ITSELF is presented as a statement about the SUBJECT, and
"check the model" is said instead of "I don't know how".

WHY A CODE, NOT JUST THE BLAME FIELD. `KIR-B006` is "any other script
exception"; leaving it as is would mean telling our own gap apart from the
author's mistake ONLY by prose, and the receipt is not read by one eye alone.
`KIR-B015` gives it a machine identity, and it must be CLASSIFIED in the
door's taxonomy: a code with no row there gets `KIR_PROGRAM_REFUSED` by
`.get()`'s default — that is, exactly "the author's fault", silently. This is
checked here by a separate test.
"""
from __future__ import annotations

import unittest

from kir import diag
from kir.sandbox import execute_author_script

НАШИ_ПРОБЕЛЫ = {
    "здание не подано":  'стены = building.find(cat="Walls")\n',
    "перепись":          'print(building.census())\n',
    "уровни здания":     'print(building.levels())\n',
    "каталог не подан":  'print(model.levels())\n',
    "элемент по адресу": 'print(building.get("12345"))\n',
}


class ПробелЧтенияНеВинаАвтора(unittest.TestCase):

    def test_ни_один_наш_пробел_не_свален_на_автора(self) -> None:
        свалили = []
        for имя, исходник in НАШИ_ПРОБЕЛЫ.items():
            d = execute_author_script(исходник).refusal
            if d.blame == "author":
                свалили.append(f"{имя}: {d.code} blame={d.blame}")
        self.assertEqual(свалили, [], msg=(
            "\n🔴 НАШ ПРОБЕЛ ЧТЕНИЯ ПРИЕХАЛ КАК ВИНА МОДЕЛИ.\n"
            "`blame=author` документирован как «чинит модель» — а чинить\n"
            "нечего: индекс не подан НАМИ. Модель перепишет исправный скрипт.\n"
            + "\n".join(свалили)))

    def test_у_нашего_пробела_свой_код(self) -> None:
        """A difference visible only in prose is invisible to the machine."""
        чужие = []
        for имя, исходник in НАШИ_ПРОБЕЛЫ.items():
            d = execute_author_script(исходник).refusal
            if d.code != diag.SANDBOX_UNREAD:
                чужие.append(f"{имя}: {d.code}")
        self.assertEqual(чужие, [], msg=(
            f"\n🔴 ОЖИДАЛСЯ {diag.SANDBOX_UNREAD}: " + "; ".join(чужие)))

    def test_код_классифицирован_дверью(self) -> None:
        """A code NOT REGISTERED with the dispatcher gets "author's fault"
        SILENTLY.

        Lesson from `KIR-B013`: the omission protected against nothing — it
        gave exactly the outcome we feared, and gave it by default.

        🔴 ASKED OF THE DISPATCHER SINCE 02.09.2026. A check against
        `serving._KIR_B_TO_ERRCODE` stood here — one of six handwritten
        tables where the outcome lived a SECOND time. The tables are gone,
        the question is the same: is this code's outcome named on purpose.
        """
        self.assertIsNotNone(
            diag.taxonomy_of(diag.SANDBOX_UNREAD),
            "код не заведён у распорядителя — исход возьмётся умолчанием")
        self.assertEqual(diag.taxonomy_of(diag.SANDBOX_UNREAD),
                         "KIR_PRECONDITION_UNMET")

    # ── controls: the instrument must be able to say "this is YOURS" ─────────────────

    def test_ошибка_автора_осталась_виной_автора(self) -> None:
        d = execute_author_script("x = 1/0\n").refusal
        self.assertEqual(d.blame, "author")
        self.assertEqual(d.code, diag.SANDBOX_RUNTIME)

    def test_опечатка_в_имени_осталась_виной_автора(self) -> None:
        """Control against OVER-CLAIMING: not every RuntimeError is now
        ours."""
        d = execute_author_script("нет_такого_имени()\n").refusal
        self.assertEqual(d.blame, "author")

    def test_подан_индекс_и_вопрос_отвечен(self) -> None:
        """The main control: the gap must DISAPPEAR once we have read it.

        Without it, everything above would be green even for an instrument
        that simply always says "ours".
        """
        from kir import building_index as bi

        class _El:
            def __init__(s, eid):
                s.element_id, s.category = eid, "OST_Walls"
                s.level_name, s.type_name = "L1", "К200"
                s.p0_mm = s.bbox_min_mm = (0, 0, 0)
                s.p1_mm = s.bbox_max_mm = (1000, 0, 0)
                s.host_id, s.params = None, {}

        r = execute_author_script(
            'print("ВСЕГО", building.found(cat="Walls"))\n'
            'create_wall(p0_mm=[0,0], p1_mm=[1,0], level="L1")\n',
            building=bi.build_index([_El(str(i)) for i in range(3)]))
        self.assertTrue(r.ok, r.refusal and r.refusal.render())
        self.assertIn("ВСЕГО 3", r.stdout)


if __name__ == "__main__":
    unittest.main()
