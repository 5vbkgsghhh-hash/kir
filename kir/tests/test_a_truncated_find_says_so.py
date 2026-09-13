"""A building `find()` that hits the ceiling must SAY SO.

🔴 MEASURED ON 25.08.2026, BY A RUN THROUGH THE SANDBOX AND A REAL INDEX. A
building of 250 walls, ceiling `DEFAULT_FIND_LIMIT = 200`:

    walls = building.find(cat='Walls')   ->  RETURNED 200
    repr(walls) speaks of truncation      ->  NO
    building.found(cat='Walls')          ->  250

The model received 80% of the building and HAD NO WAY of knowing it without
asking a second question it was never told it needed to ask. This is exactly
the silently-wrong outcome the package is written to forbid: a loop over
`walls` will run 200 times and look complete.

`find`'s DOCSTRING ALREADY PROMISED THIS AND DID NOT DELIVER, verbatim:
"Truncation is DECLARED: if more than `limit` is found, the extra does not
silently vanish — `found()` returns the full count, and the list is named as
truncated in the query result's `__repr__`." What was returned was a bare
`tuple`, with Python's own `__repr__`. A promise in a docstring is not a
mechanism; this is the shape of "declared in one place, not done in
another," a named defect of the tree.

TWO CASES ARE DISTINGUISHED, AND THE DISTINCTION HERE IS THE MAIN POINT:

    a DEFAULT ceiling      the model did not know about it — it must be SAID
                           aloud, into a channel the model reads
    an explicit `limit=`   the model named the limit itself — we don't shout
                           aloud, but `__repr__` is still honest

Shouting about an explicit limit would mean making noise at a correctly
written script, and a guard that makes noise gets switched off.
"""
from __future__ import annotations

import unittest

from kir import building_index as bi
from kir import sandbox


class _El:
    """A stand-in for `L0Element` — exactly the fields the index reads."""

    def __init__(self, eid, cat="OST_Walls", lvl="L1", tname="Кирпич 200мм"):
        self.element_id, self.category = eid, cat
        self.level_name, self.type_name = lvl, tname
        self.p0_mm = self.bbox_min_mm = (0, 0, 0)
        self.p1_mm = self.bbox_max_mm = (1000, 0, 0)
        self.host_id, self.params = None, {}


def _здание(сколько: int):
    idx = bi.build_index([_El(str(i)) for i in range(сколько)])
    assert idx["tier"] == bi.TIER_FULL, "тест обязан идти по ПОЛНОМУ индексу"
    return idx


ХВОСТ = "\ncreate_wall(p0_mm=[0,0], p1_mm=[1,0], level='L1')\n"


def _отказной(тело: str, сколько: int = 50):
    """A run whose refusal is the EXPECTED outcome.

    Kept separate from `_run`: that one requires `ok` and so, on a
    refusal-probing test, fails an assert INSIDE the helper, hiding the
    test's real subject behind someone else's line. Two different
    expectations — two different helpers.
    """
    return sandbox.execute_author_script(тело + ХВОСТ, building=_здание(сколько))


def _прогон(тело: str, сколько: int = 250):
    r = sandbox.execute_author_script(тело + ХВОСТ, building=_здание(сколько))
    assert r.ok, r.refusal and r.refusal.render()
    return r


class УсечениеНазвано(unittest.TestCase):

    def test_потолок_по_умолчанию_назван_вслух(self) -> None:
        """The channel to the model is the receipt's `stdout`. Silence here is exactly the defect."""
        r = _прогон("стены = building.find(cat='Walls')\n")
        self.assertIn("250", r.stdout, "полное число обязано быть названо")
        self.assertRegex(r.stdout, r"200",
                         "сколько ОТДАНО — тоже обязано быть названо")

    def test_repr_результата_называет_усечение(self) -> None:
        """The docstring's promise, finally carried out by a mechanism."""
        r = _прогон("print('REPR:', repr(building.find(cat='Walls')))\n")
        строка = [s for s in r.stdout.splitlines() if s.startswith("REPR:")][0]
        self.assertIn("250", строка)
        self.assertIn("200", строка)

    def test_как_взять_остальное_сказано(self) -> None:
        """A refusal without a next move is a second round."""
        r = _прогон("стены = building.find(cat='Walls')\n")
        self.assertIn("limit", r.stdout,
                      "модель обязана узнать, ЧЕМ поднять предел")

    # ── controls: the guard must be able to STAY SILENT ───────────────────

    def test_неусечённый_запрос_молчит(self) -> None:
        """50 walls with a ceiling of 200 — nothing to speak of."""
        r = _прогон("стены = building.find(cat='Walls')\n"
                    "print('ВЗЯЛИ', len(стены))\n", сколько=50)
        self.assertIn("ВЗЯЛИ 50", r.stdout)
        self.assertNotIn("усеч", r.stdout.lower(),
                         "шум на правильном скрипте — сторож, который выключат")

    def test_явный_предел_вслух_не_кричит(self) -> None:
        """The model named the limit itself — nothing to shout about.

        But `__repr__` is honest here too: it is a fact about the value, not
        about whether the author was surprised by it.
        """
        r = _прогон("стены = building.find(cat='Walls', limit=10)\n"
                    "print('REPR:', repr(стены))\n")
        шум = [s for s in r.stdout.splitlines() if not s.startswith("REPR:")]
        self.assertNotIn("усеч", "\n".join(шум).lower())
        строка = [s for s in r.stdout.splitlines() if s.startswith("REPR:")][0]
        self.assertIn("250", строка, "полное число честно и при явном пределе")

    # ── the fix must not break the value's shape ───────────────────────────

    def test_результат_остаётся_кортежем(self) -> None:
        """Scripts are already written. Changing the value's type would break them silently."""
        r = _прогон(
            "стены = building.find(cat='Walls')\n"
            "print('КОРТЕЖ', isinstance(стены, tuple))\n"
            "print('ДЛИНА', len(стены))\n"
            "print('ИНДЕКС', стены[0]['id'])\n"
            "print('ЦИКЛ', sum(1 for _ in стены))\n"
            "print('СРЕЗ', len(стены[:5]))\n")
        for ожидание in ("КОРТЕЖ True", "ДЛИНА 200", "ЦИКЛ 200", "СРЕЗ 5"):
            self.assertIn(ожидание, r.stdout)

    def test_found_по_прежнему_знает_полное_число(self) -> None:
        r = _прогон("print('ВСЕГО', building.found(cat='Walls'))\n")
        self.assertIn("ВСЕГО 250", r.stdout)


if __name__ == "__main__":
    unittest.main()


class ПризнакПоискаЕстьЗакрытыйНабор(unittest.TestCase):
    """A typo in a FEATURE NAME answered with emptiness — a lie about the
    BUILDING.

    🔴 MEASURED ON 25.08.2026: `building.find(catt="Walls")` on a
    fifty-wall building returned `()`. `building_index.matches`, given an
    unknown key, takes `row.get("catt")` (None), compares it to "Walls," and
    rejects EVERY row. The model reads "there are no walls in the building"
    — when the truth was about how the feature name was spelled.

    The worst kind of outcome in this tree: on a refusal the model would ask
    differently, but here it keeps building on an empty foundation and
    cannot even start fixing it.
    """

    def test_чужой_признак_отказывает_а_не_пустует(self) -> None:
        r = _отказной('print("ВЗЯЛИ", len(building.find(catt="Walls")))\n')
        self.assertFalse(r.ok, "пустой ответ на опечатку — ложь о здании")
        текст = r.refusal.message_ru or ""
        self.assertIn("catt", текст, "промах назван дословно")
        self.assertIn("cat", текст, "существующий признак назван")

    def test_счёт_закрыт_тем_же_набором(self) -> None:
        """`found` is `find`'s counterpart, and a hole in the pair is worse than a hole alone."""
        r = _отказной('print(building.found(catt="Walls"))\n')
        self.assertFalse(r.ok)
        self.assertIn("catt", r.refusal.message_ru or "")

    def test_настоящие_признаки_работают(self) -> None:
        """CONTROL: a guard that refuses EVERYTHING is a fix worse than the defect."""
        r = _прогон('print("A", building.found(cat="Walls"))\n'
                    'print("B", building.found(lvl="L1"))\n'
                    'print("C", building.found(type="Кирпич"))\n'
                    'print("D", building.found(id="7"))\n', сколько=50)
        for метка in ("A 50", "B 50", "C 50", "D 1"):
            self.assertIn(метка, r.stdout)

    def test_набор_признаков_выведен_из_строк_а_не_переписан(self) -> None:
        """A second hand-written list would silently drift from the index.

        The project's measurement on 15.08: ALL hand-written lists drifted
        and NOT ONE generated one did. Checked by execution — the refusal
        must carry the fields the index puts into a row TODAY.
        """
        r = _отказной('building.find(нетакого=1)\n')
        текст = r.refusal.message_ru or ""
        for поле in ("cat", "id", "lvl", "type", "p0", "p1"):
            self.assertIn(поле, текст, f"поле строки `{поле}` не названо")
