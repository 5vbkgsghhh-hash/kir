"""THE BATCH JUDGE WAS BLIND TO ROOMS WHEN THE LEVEL WAS NOT CREATED IN THAT BATCH.

🔴 MEASUREMENT ON A LIVE REVIT, 03.09.2026. The "housing" recipe apartment
was built — 23 elements, five rooms with real ids (`room1..room5`). The
building judge, in the same receipt:

    0 of 20 rules · blocking HAB000
    «model has no rooms — empty or failed extraction; nothing was verified»

The cause is the same as with `built_verdict.datum_ops` (measured 17.08):
`spatial_model_from_program` resolves the level selector ONLY against a
`create_level` FROM THE SAME PROGRAM. A level created by a PAST turn does
not land in the batch — the room is thrown out as "level outside the
document", and ALL twenty housing rules stay silent. "Not evaluated" reads
as "nothing bad was found": a false zero on the building's feedback.

THE BATCH LEGITIMATELY LOSES THE LEVEL, AND THAT IS NOT FIXED BY THE BATCH.
`standing()` subtracts side stages: a program that never reached the model
(`running_unknown`) is no longer a design intent — and rightly so. But its
DATUM remains a fact about the document: the level stands, whatever
happened to the program that declared it. The journal already knows
this — `SessionJournal.datums` accumulates `create_level`/`create_grid`
from ALL records, including the dropped ones. The judge never asked it.

THE NUMBER OF MOVEMENT THIS FILE TAKES: rules 0 -> 9 on a single room.
"""
from __future__ import annotations

import unittest

from kir import design_check as _dc
from kir.live import journal as _journal
from kir.live import verdict as _verdict

УРОВЕНЬ = "Э1"
_ЛВЛ = {"by": "name", "value": УРОВЕНЬ}
_W, _D, _H = 6000, 5000, 3000
_КВАДРАТ = [(0, 0), (_W, 0), (_W, _D), (0, _D)]


def уровень_оп() -> dict:
    return {"op": "create_level", "id": "l1", "name": УРОВЕНЬ, "elev_mm": 0}


def квартира_опы() -> list[dict]:
    """A room the judge EVALUATES, if it knows the level."""
    стены = [{"op": "create_wall", "id": f"w{i + 1}",
              "p0_mm": list(_КВАДРАТ[i]),
              "p1_mm": list(_КВАДРАТ[(i + 1) % 4]),
              "level": _ЛВЛ, "height_mm": _H} for i in range(4)]
    return [
        *стены,
        {"op": "create_floor_by_contour", "id": "f1",
         "contour": {"outer": {"shape": "poly",
                               "points_mm": [list(p) for p in _КВАДРАТ]}},
         "level": _ЛВЛ},
        {"op": "create_door", "id": "d1",
         "host": {"by": "ref", "value": "w1"}, "offset_mm": 3000, "sill_mm": 0},
        {"op": "create_window", "id": "win1",
         "host": {"by": "ref", "value": "w3"}, "offset_mm": 3000,
         "sill_mm": 900},
        {"op": "create_room", "id": "r1", "xy": [_W // 2, _D // 2],
         "level": _ЛВЛ, "name": "Комната"},
    ]


class ДатумДоезжаетДоСудьи(unittest.TestCase):

    def test_число_правил_двигается_датумом(self) -> None:
        """Both sides in one run: without the datum zero, with the datum — more."""
        прог = квартира_опы()
        без = _dc.check_bundle([{"ops": прог}], building_id="без датума")
        с = _dc.check_bundle([{"ops": [уровень_оп()]}, {"ops": прог}],
                             building_id="с датумом")
        self.assertEqual(
            без.rules_applied, 0,
            "контроль сорван: уровень не в пачке, а правила всё равно "
            "оценились — значит этот файл сторожит не тот шов")
        self.assertGreater(
            с.rules_applied, 0,
            "датум подан, а правила молчат: помещение всё ещё не доехало "
            "до судьи")

    def test_датум_кладётся_отдельной_программой(self) -> None:
        """A pure function: the subject is an argument, so it can be turned red too."""
        class _Журнал:
            datums = ({"op": "create_level", "id": "l1", "name": "Э1"},)

        пачка = [{"ops": [{"op": "create_wall", "id": "w1"}]}]
        стало = _verdict._pack_with_datums(пачка, _Журнал())
        self.assertEqual(len(стало), len(пачка) + 1,
                         "датумы обязаны ехать ОТДЕЛЬНОЙ программой: пачка "
                         "несёт закон «ссылка живёт ВНУТРИ программы»")
        self.assertEqual(стало[0]["ops"], [dict(_Журнал.datums[0])])
        self.assertEqual(стало[1:], пачка, "чужие программы не тронуты")

    def test_пустые_датумы_оставляют_пачку_той_же(self) -> None:
        """Absence stays absence: an empty datum does not create a program."""
        class _Пустой:
            datums = ()

        пачка = [{"ops": [{"op": "create_wall", "id": "w1"}]}]
        self.assertIs(_verdict._pack_with_datums(пачка, _Пустой()), пачка)

    def test_число_датумов_видно_в_квитанции(self) -> None:
        """A quantity nobody sees silently becomes zero."""
        class _Журнал:
            datums = ({"op": "create_level", "id": "l1"},
                      {"op": "create_grid", "id": "g1"})

        self.assertEqual(_verdict._datums_fed(_Журнал()), 2)
        self.assertEqual(_verdict._datums_fed(object()), 0,
                         "журнал без датумов обязан дать 0, а не сорваться")

    def test_журнал_копит_датум_выпавшей_программы(self) -> None:
        """LOAD-BEARING: a side stage takes the program out of the batch, but not the datum."""
        key = _journal.key_for("сторож-датума", "док-сторожа")
        rec = _journal.append(key, {"ops": [уровень_оп()]})
        _journal.advance(key, rec.seq, "running_unknown")
        e = _journal.get(key)
        self.assertEqual(
            [r.seq for r in e.standing()], [],
            "боковая стадия обязана вынести программу из пачки")
        self.assertEqual(
            [dict(op) for op in e.datums], [уровень_оп()],
            "а датум обязан остаться: уровень стоит в документе независимо "
            "от судьбы программы, которая его объявила")


class ЛичностьДатумаЭтоИмя(unittest.TestCase):
    """🔴 THE DATUM STORE WAS STUCK AT SIX NAMES FOR ITS WHOLE HISTORY (measured 03.09).

    Deduplication went by the op's `id`, and `id` lives INSIDE the program:
    every turn that declares levels calls them `level1`/`level2`. So "the
    first level with this number wins forever", and everything later went
    into `datums_dropped` silently. Live measurement: the judge saw
    «Кровля сарая», «KIR проба», «KIR_GAP_FLOOR» — levels from long-past
    turns — while the level of TODAY'S apartment never made it into the
    store, and the five rooms that were actually built read as HAB000.

    After the fix, on the same prod: datums 6 -> 89, self-check 0 -> 11
    rules of 20.
    """

    def test_одинаковый_id_с_разными_именами_даёт_два_датума(self) -> None:
        key = _journal.key_for("личность-датума", "док-личности")
        _journal.append(key, {"ops": [{"op": "create_level", "id": "level1",
                                       "name": "Этаж 1", "elev_mm": 0}]})
        _journal.append(key, {"ops": [{"op": "create_level", "id": "level1",
                                       "name": "Этаж 5", "elev_mm": 12000}]})
        e = _journal.get(key)
        self.assertEqual([d.get("name") for d in e.datums], ["Этаж 1", "Этаж 5"],
                         "`id` программы принят за личность датума: второй "
                         "уровень отброшен как дубль первого")
        self.assertEqual(e.datums_dropped, 0)

    def test_одно_и_то_же_имя_дважды_остаётся_одним(self) -> None:
        """CONTROL IN THE OTHER DIRECTION: deduplication is not broken, it is relocated."""
        key = _journal.key_for("личность-датума-2", "док-личности-2")
        for _ in range(3):
            _journal.append(key, {"ops": [{"op": "create_level", "id": "l1",
                                           "name": "Этаж 1", "elev_mm": 0}]})
        self.assertEqual(len(_journal.get(key).datums), 1)

    def test_датум_без_имени_остаётся_при_id(self) -> None:
        """A name may be absent — then the identity is the old one, and this is named."""
        key = _journal.key_for("личность-датума-3", "док-личности-3")
        _journal.append(key, {"ops": [{"op": "create_grid", "id": "g1"}]})
        _journal.append(key, {"ops": [{"op": "create_grid", "id": "g1"}]})
        _journal.append(key, {"ops": [{"op": "create_grid", "id": "g2"}]})
        self.assertEqual([d.get("id") for d in _journal.get(key).datums],
                         ["g1", "g2"])


class СамопроверкаЗнаетДатумыСессии(unittest.TestCase):
    """The self-check judges the TURN'S PROGRAM — and stayed silent on the main case.

    A live recording almost always builds on a level that is ALREADY
    STANDING: this argument was made for `built_verdict.datum_ops` back on
    17.08 and closed there for the re-parsed judge, but was never closed
    for the self-check. An apartment with five rooms actually built got
    «САМОПРОВЕРКА НЕ СОСТОЯЛАСЬ … HAB000» — the most readable line of the
    receipt stayed silent.
    """

    def test_датумы_сессии_доезжают_до_самопроверки(self) -> None:
        from kir import serving
        key = _journal.key_for("самопроверка-датума", "док-самопроверки")
        _journal.append(key, {"ops": [уровень_оп()]})
        e = _journal.get(key)
        токен = serving._TURN_JOURNAL_SLOT.set((key, 0))
        try:
            self.assertEqual([dict(op) for op in serving._session_datums()],
                             [уровень_оп()])
            блок = serving._self_check_block(
                {"ir_version": "1.0", "ops": квартира_опы()})
        finally:
            serving._TURN_JOURNAL_SLOT.reset(токен)
        self.assertIsNotNone(блок)
        self.assertGreater(
            блок.get("rules_applied") or 0, 0,
            f"самопроверка молчит при поданных датумах: {блок}")
        self.assertEqual(len(e.datums), 1)

    def test_уровни_документа_доезжают_до_самопроверки(self) -> None:
        """🔴 THE PRODUCT'S MAIN CASE: an outside person opened THEIR OWN project.

        The journal knows levels only from THIS session. Revit's template
        level («Уровень 1») was created by none of KIR — and the self-check
        stayed silent about an apartment on it. Attribution was lifted by a
        control on a live Revit, both sides:

            level created by a past KIR session   with snapshot 11 · without 11 (journal)
            Revit's template level                 with snapshot 11 · without 0, HAB000
        """
        from kir import serving
        снимок = {"levels": [{"id": "355", "name": УРОВЕНЬ,
                              "elevation_mm": 0.0}]}
        токен_с = serving._TURN_JOURNAL_SLOT.set(None)
        токен_сн = serving._TURN_GROUND_SNAPSHOT.set(снимок)
        try:
            датумы = serving._session_datums()
            self.assertEqual([op.get("name") for op in датумы], [УРОВЕНЬ])
            блок = serving._self_check_block(
                {"ir_version": "1.0", "ops": квартира_опы()})
        finally:
            serving._TURN_GROUND_SNAPSHOT.reset(токен_сн)
            serving._TURN_JOURNAL_SLOT.reset(токен_с)
        self.assertGreater(
            блок.get("rules_applied") or 0, 0,
            f"уровень документа не доехал до судьи: {блок}")

    def test_имя_не_задваивается_журналом_и_снимком(self) -> None:
        """One level, two sources — one datum. Otherwise the judge would be
        counting floors twice, and that is no longer silence, it is a wrong
        number."""
        from kir import serving
        key = _journal.key_for("двойник-датума", "док-двойника")
        _journal.append(key, {"ops": [уровень_оп()]})
        снимок = {"levels": [{"id": "355", "name": УРОВЕНЬ,
                              "elevation_mm": 0.0}]}
        т1 = serving._TURN_JOURNAL_SLOT.set((key, 0))
        т2 = serving._TURN_GROUND_SNAPSHOT.set(снимок)
        try:
            датумы = serving._session_datums()
        finally:
            serving._TURN_GROUND_SNAPSHOT.reset(т2)
            serving._TURN_JOURNAL_SLOT.reset(т1)
        self.assertEqual([op.get("name") for op in датумы], [УРОВЕНЬ])

    def test_без_слота_самопроверка_ведёт_себя_как_прежде(self) -> None:
        """A reading turn and any door without a journal: no datums, and that is normal."""
        from kir import serving
        токен = serving._TURN_JOURNAL_SLOT.set(None)
        снимок = serving._TURN_GROUND_SNAPSHOT.set(None)
        try:
            self.assertEqual(serving._session_datums(), [])
            блок = serving._self_check_block(
                {"ir_version": "1.0", "ops": квартира_опы()})
        finally:
            serving._TURN_GROUND_SNAPSHOT.reset(снимок)
            serving._TURN_JOURNAL_SLOT.reset(токен)
        self.assertEqual(блок.get("rules_applied") or 0, 0,
                         "контроль сорван: без датумов правила не должны "
                         "оцениваться — иначе этот файл сторожит не тот шов")
        self.assertEqual(блок.get("datums_seen"), 0)


class ЖурналПереживаетПравкуАвтора(unittest.TestCase):
    """🔴 F-180, CONFIRMED BY EXECUTION 04.09.2026. The `_normalise_ops`
    docstring promised "the journal must outlive the caller", while the
    copy was SHALLOW: nested coordinates and outlines stayed shared with
    the author.

        the author edits their own dict AFTER the write
        p0_mm in the journal            [999999, 0]        got rewritten
        contour.outer.points_mm         [[777777, 0], …]   got rewritten

    The journal is what the batch judge and the viewer use to reconstruct
    the building: the author's edit silently rewrote the HISTORY of what
    had already been recorded.
    """

    def test_вложенные_носители_не_общие_с_автором(self) -> None:
        опы = [{"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                "contour": {"outer": {"points_mm": [[0, 0], [1, 1]]}}}]
        key = _journal.key_for("журнал-переживает", "док-переживает")
        _journal.append(key, {"ops": опы})
        опы[0]["p0_mm"][0] = 999999
        опы[0]["contour"]["outer"]["points_mm"][0][0] = 777777
        хранимая = _journal.get(key).records[0].ops[0]
        self.assertEqual(хранимая["p0_mm"], [0, 0],
                         "правка автора переписала запись журнала")
        self.assertEqual(хранимая["contour"]["outer"]["points_mm"][0], [0, 0],
                         "вложенный контур остался общим с автором")

    def test_чужие_объекты_копия_не_трогает(self) -> None:
        """CONTROL IN THE OTHER DIRECTION: FLAT carriers are copied, not
        everything indiscriminately — otherwise the instrument would be
        deciding for someone else's object."""
        class Чужой:
            pass

        свой = Чужой()
        self.assertIs(_journal._снимок(свой), свой)
        self.assertEqual(_journal._снимок({"a": [1, {"b": (2, 3)}]}),
                         {"a": [1, {"b": (2, 3)}]})


class НеизвестноеНеНазываетсяОтказом(unittest.TestCase):
    """🔴 F-167: A WHOLE THIRD OF THE FILTERED-OUT WAS DECLARED A REFUSAL (measured 04.09.2026).

    Live census: 117 filtered out, of which `running_unknown` — 95. The
    judge wrote of all of them: «отказ до записи либо откат; замыслом они
    больше не являются». The journal says the EXACT OPPOSITE about this
    stage, in its own words — «улики НЕТ. Не „не построено“, а „не
    знаем“» — and a retry is forbidden of it precisely because the write
    COULD have gone through.

    What changes here is ONLY THE NAME, not the batch's composition:
    whether to judge the unknown is a decision about the law, and it
    cannot be made silently.
    """

    def test_неизвестный_исход_назван_своим_именем(self) -> None:
        строка = _verdict._built_line(
            {"built": 2, "programs": 4, "dropped_from_pack": 117,
             "by_stage": {"running_unknown": 95, "rolled_back": 6,
                          "refused_pre_effect": 16}})
        self.assertIn("ИСХОД НЕИЗВЕСТЕН", строка)
        self.assertIn("95", строка)
        self.assertIn("22 — отказ до записи либо откат", строка,
                      "настоящие отказы обязаны остаться названными отдельно")

    def test_без_неизвестных_строка_прежняя(self) -> None:
        """CONTROL IN THE OTHER DIRECTION: where there are no unknowns, nothing changes."""
        строка = _verdict._built_line(
            {"built": 2, "programs": 4, "dropped_from_pack": 22,
             "by_stage": {"rolled_back": 6, "refused_pre_effect": 16}})
        self.assertIn("отказ до записи либо откат", строка)
        self.assertNotIn("ИСХОД НЕИЗВЕСТЕН", строка)

    def test_состав_пачки_не_тронут(self) -> None:
        """A line about COMPOSITION has no right to change it: `standing`
        counts stages, and `running_unknown` is still a side one."""
        key = _journal.key_for("неизвестный-исход", "док-неизвестного")
        rec = _journal.append(key, {"ops": [уровень_оп()]})
        _journal.advance(key, rec.seq, "running_unknown")
        self.assertEqual([r.seq for r in _journal.get(key).standing()], [])


if __name__ == "__main__":
    unittest.main()
