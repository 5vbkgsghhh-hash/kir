"""AGREEMENT IS PRINTED ONLY WHERE A COMPARISON ACTUALLY HAPPENED.

Three spots of the verdict about WHAT WAS BUILT said "everything matches"
where there was no comparison or where the wrong thing was asked. All three
are one law, written down twice in this tree and left unfinished both
times: **zero of an UNCOMPUTED quantity is printed as a WORD, not a
number**, because a false refusal is visible, while empty agreement reads
as a check.

Measurement before the fix (2026-09-04, `/opt/kir`, `python3.12`):

    LD-06  note()                three states — one line byte for byte
                                 (product output, quoted verbatim):
                                 «… · расхождений с заявленным НЕТ»
                                 (healthy · verdict comparator crashed ·
                                  geometry comparator crashed)
    HR-09  compare_geometry()    two NON-EMPTY models, NOT ONE room matched
                                 -> 0 divergences -> render_comparison
                                 prints «РАСХОЖДЕНИЙ НЕТ.» (product output)
    HR-10  compare_geometry()    three rooms, fractions outside the declared
                                 [0, 0, 1] -> median 0.0000 -> classed as
                                 "match": a room that moved ENTIRELY is
                                 declared agreement

WHY EACH ROAD IS SEPARATE. LD-06 is the one line that survives history
compaction: the prose in `_message` has asked this question since 09-04
(F-125), while the flat `note` kept lying, meaning the fix landed on ONE of
the two carriers. HR-09 and HR-10 are read by `built_verdict`, and its
verdict is the constitution metric's main channel.

FAIL CONTROL. Each class carries a check in THE OTHER DIRECTION: a healthy
turn must still say "NO divergences", matched addresses must stay silent, a
correctly built room (a boundary at the inner faces, an opening cut to wall
thickness) must remain classed as "match". Without them, green would be
green by construction.
"""
from __future__ import annotations

import pathlib
import types
import unittest

import kir
from kir import built_verdict
from kir.checker.spatial_model import Level, Room, RoomFunction, SpatialModel
from kir.design_check import (
    _ROOM_OUTSIDE_TOL,
    СВЕРКА,
    compare_geometry,
    render_comparison,
)

# SUBJECT OF THE MEASUREMENT. Next door sits an installed copy of `kir` from
# `~/.local`, and an instrument that measured IT would be right about a
# different subject. What is asked is not the literal path `/opt/kir` but
# identity: the package must be the very one this file lives in — then the
# check works on a frozen copy too.
assert (pathlib.Path(kir.__file__).resolve().parent
        == pathlib.Path(__file__).resolve().parent.parent), (
    "замер не состоялся: импортирован ЧУЖОЙ `kir` (%s)" % kir.__file__)


# ── LD-06: a crashed comparison used to print as agreement ─────────────────

_СУДИМ = {"state": "judged", "elements_read": 3, "elements_asked": 3,
          "divergences": [], "geometry_divergences": []}


class УпавшаяСверкаНеЧитаетсяКакСогласие(unittest.TestCase):

    def test_здоровый_ход_по_прежнему_говорит_что_расхождений_нет(self):
        """A CONTROL IN THE OTHER DIRECTION: without failures the line must stay."""
        строка = built_verdict.note(_СУДИМ)
        self.assertIn("расхождений с заявленным НЕТ", строка)
        self.assertNotIn("СВЕРКА НЕ ВЫПОЛНЯЛАСЬ", строка)

    def test_каждый_сорвавшийся_сравнитель_меняет_строку(self):
        """🔴 DECISIVE: before the fix all three lines matched BYTE FOR BYTE."""
        здоровая = built_verdict.note(_СУДИМ)
        for ключ in ("compare_error", "compare_geometry_error"):
            with self.subTest(сравнитель=ключ):
                строка = built_verdict.note(
                    {**_СУДИМ, ключ: "ValueError: сравнитель упал"})
                self.assertNotEqual(
                    строка, здоровая,
                    f"{ключ}: сорвавшаяся сверка печатается ДОСЛОВНО как "
                    f"согласие — читатель различить их не может ничем")
                self.assertNotIn(
                    "расхождений с заявленным НЕТ", строка,
                    "«расхождений нет» — утверждение о величине, которую "
                    "здесь никто не вычислял")
                self.assertIn("СВЕРКА НЕ ВЫПОЛНЯЛАСЬ", строка)
                self.assertIn("ValueError", строка,
                              "причина обязана быть названа дословно")

    def test_уцелевший_сравнитель_назван_а_несуществующий_не_обещан(self):
        один = built_verdict.note({**_СУДИМ, "compare_error": "ValueError: A"})
        self.assertIn("сравнитель геометрии отработал", один)
        оба = built_verdict.note({**_СУДИМ, "compare_error": "ValueError: A",
                                  "compare_geometry_error": "KeyError: Б"})
        self.assertNotIn("отработал", оба,
                         "сорвались оба — обещать уцелевшего нельзя")
        self.assertIn("ValueError: A", оба)
        self.assertIn("KeyError: Б", оба)

    def test_найденные_расхождения_не_прячут_сорвавшуюся_вторую_сверку(self):
        """The absence of a "verdict N divergences" line reads as zero."""
        блок = {**_СУДИМ,
                "geometry_divergences": [{"kind": "геометрия",
                                          "subject": "ось стены",
                                          "program": "совпало 1",
                                          "parse": "2 общих"}],
                "compare_error": "ValueError: сравнитель вердиктов упал"}
        строка = built_verdict.note(блок)
        self.assertIn("СВЕРКА НЕПОЛНАЯ", строка)
        self.assertIn("ValueError", строка)
        self.assertIn("геометрия расходится в 1", строка,
                      "числа уцелевшей сверки обязаны остаться на месте")

    def test_строка_осталась_ПЛОСКОЙ(self):
        """The whole point of `note` is to survive compaction: there can be no line break."""
        for лишнее in ({}, {"compare_error": "ValueError: A"},
                       {"compare_error": "ValueError: A",
                        "compare_geometry_error": "KeyError: Б"}):
            with self.subTest(состояние=sorted(лишнее)):
                строка = built_verdict.note({**_СУДИМ, **лишнее})
                self.assertIsInstance(строка, str)
                self.assertNotIn("\n", строка)


# ── HR-09 and HR-10: room comparison ────────────────────────────────────────

_УРОВЕНЬ = Level(id="L1", name="1 этаж", elevation_mm=0.0, index=0)


def _комната(rid: str, контур: list[tuple[float, float]]) -> Room:
    xs = [x for x, _ in контур]
    ys = [y for _, y in контур]
    ширина = max(xs) - min(xs)
    высота = max(ys) - min(ys)
    return Room(id=rid, name=rid, level_id="L1", function=RoomFunction.ЖИЛАЯ,
                area_m2=ширина * высота / 1_000_000.0, height_mm=2700.0,
                boundary=контур)


def _прямоугольник(x0: float, y0: float, x1: float, y1: float):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _модель(комнаты: list[Room], building_id: str = "b-1") -> SpatialModel:
    return SpatialModel(building_id=building_id, levels=[_УРОВЕНЬ],
                        rooms=комнаты)


def _напечатать(parse: SpatialModel, program: SpatialModel) -> str:
    """What a human will see. `render_comparison` reads exactly two fields
    off the verdict — `building_id` and `verdict` — so the substitution is
    honest: the subject here is the LIST OF DIVERGENCES, not the verdict."""
    сторона = types.SimpleNamespace(building_id=parse.building_id,
                                    verdict=None)
    return render_comparison(сторона, сторона, compare_geometry(parse, program))


class НепересекающиесяПомещенияЭтоОтказСверки(unittest.TestCase):
    """HR-09. An empty intersection with NON-EMPTY sides is a finding, not agreement."""

    def _разные(self):
        parse = _модель([_комната("R1", _прямоугольник(0, 0, 4000, 3000)),
                         _комната("R2", _прямоугольник(5000, 0, 9000, 3000))])
        program = _модель([_комната("R8", _прямоугольник(0, 0, 4000, 3000)),
                           _комната("R9", _прямоугольник(5000, 0, 9000, 3000))])
        return parse, program

    def test_пустое_пересечение_названо_а_не_промолчано(self):
        parse, program = self._разные()
        self.assertTrue(parse.rooms and program.rooms, "контроль вырожден")
        строки = compare_geometry(parse, program)
        self.assertEqual([d.subject for d in строки], ["помещения не сведены"])
        self.assertEqual(строки[0].kind, "адрес")
        self.assertIn("пусто", строки[0].cause.lower())
        # ADDRESS: same shape as with walls, carrying an example from both sides.
        self.assertIn("`R1`", строки[0].parse)
        self.assertIn("`R8`", строки[0].program)

    def test_человеку_больше_не_печатается_РАСХОЖДЕНИЙ_НЕТ(self):
        """🔴 DECISIVE: exactly the line a human read before the fix."""
        parse, program = self._разные()
        self.assertNotIn("РАСХОЖДЕНИЙ НЕТ.", _напечатать(parse, program))

    def test_КОНТРОЛЬ_комнат_нет_вовсе_это_законная_пустота(self):
        """Emptiness ON BOTH SIDES stays silent: the guard asks about NON-EMPTINESS."""
        пусто = _модель([])
        self.assertEqual(compare_geometry(пусто, пусто), [])
        self.assertIn("РАСХОЖДЕНИЙ НЕТ.", _напечатать(пусто, пусто))

    def test_КОНТРОЛЬ_совпавшие_адреса_сторожа_не_будят(self):
        """The guard fires from a MEASUREMENT, not always."""
        одна = _модель([_комната("R1", _прямоугольник(0, 0, 4000, 3000))])
        строки = compare_geometry(одна, одна)
        self.assertFalse([d for d in строки if d.kind == "адрес"],
                         "адреса совпали, а сторож всё равно заговорил")


class МедианаНеВидитКомнатуУехавшуюЦеликом(unittest.TestCase):
    """HR-10. TWO questions are asked of one number, not one."""

    def _три(self, третья_программная):
        parse = _модель([_комната("R1", _прямоугольник(0, 0, 4000, 3000)),
                         _комната("R2", _прямоугольник(5000, 0, 9000, 3000)),
                         _комната("R3", _прямоугольник(10000, 0, 14000, 3000))])
        program = _модель([_комната("R1", _прямоугольник(0, 0, 4000, 3000)),
                           _комната("R2", _прямоугольник(5000, 0, 9000, 3000)),
                           _комната("R3", третья_программная)])
        return compare_geometry(parse, program)

    def test_одна_из_трёх_целиком_не_на_месте_это_геометрия(self):
        """Fractions outside the declared [0, 0, 1]: median 0, and the room moved."""
        строки = {d.subject: d for d in
                  self._три(_прямоугольник(10000, 50000, 14000, 53000))}
        строка = строки["контур помещения (IoU)"]
        self.assertEqual(
            строка.kind, "геометрия",
            "комната, вышедшая из своего места ЦЕЛИКОМ, объявлена согласием")
        # THE MEDIAN IS IN PLACE AND ITS ARGUMENT IS UNTOUCHED: it honestly
        # says 0.0000, and it is NOT the one catching the one that moved —
        # this is exactly what proves there are now two questions.
        self.assertIn("вне заявленного медиана 0.0000", строка.program)
        self.assertIn("ВНЕ СВОЕГО МЕСТА 1 из 3", строка.program)
        self.assertIn("`R3`", строка.program,
                      "расхождение без адреса — половина находки")

    def test_КОНТРОЛЬ_совпавшие_контуры_остаются_сверкой(self):
        строка = {d.subject: d for d in
                  self._три(_прямоугольник(10000, 0, 14000, 3000))
                  }["контур помещения (IoU)"]
        self.assertEqual(строка.kind, СВЕРКА)
        self.assertNotIn("ВНЕ СВОЕГО МЕСТА", строка.program)

    def test_КОНТРОЛЬ_вырез_на_толщину_стены_по_прежнему_НЕ_расхождение(self):
        """🔴 THE MEDIAN'S ARGUMENT IS INTACT. Live measurement 2026-08-27: a
        room 4.0 x 3.5 m, 200 mm walls. Declared — an axis boundary 4000 x
        3500 (14.00 m²), built — a boundary at the inner faces 3800 x 3300
        (12.54 m²). `IoU` = 0.896, and NOTHING moved outside: this is a
        correctly built room, and the second question must stay silent
        about it just as the first does."""
        parse = _модель([_комната("R1", _прямоугольник(100, 100, 3900, 3400))])
        program = _модель([_комната("R1", _прямоугольник(0, 0, 4000, 3500))])
        строка = {d.subject: d for d in compare_geometry(parse, program)
                  }["контур помещения (IoU)"]
        self.assertIn("IoU медиана 0.896", строка.program,
                      "стенд не тот: это не живой замер 27.08")
        self.assertEqual(
            строка.kind, СВЕРКА,
            "второй вопрос завалил правильно построенную комнату — значит "
            "порог взят не тот, и весь довод про осевые линии сломан")
        self.assertNotIn("ВНЕ СВОЕГО МЕСТА", строка.program)

    def test_порог_второго_вопроса_ТОТ_ЖЕ_и_он_различает(self):
        """The threshold is not invented: `_ROOM_OUTSIDE_TOL` is calibrated ON ONE room.

        Checked by an act of discrimination — just below the threshold it
        stays silent, noticeably above it it speaks. Otherwise "the
        threshold exists" would be a word with no measurement behind it.
        """
        сторона = 4000.0
        for доля, ждём in ((_ROOM_OUTSIDE_TOL / 2.0, СВЕРКА),
                           (0.1333, "геометрия")):
            сдвиг = сторона * доля
            parse = _модель([_комната(
                "R1", _прямоугольник(сдвиг, 0, сторона + сдвиг, 3000))])
            program = _модель([_комната(
                "R1", _прямоугольник(0, 0, сторона, 3000))])
            строка = {d.subject: d for d in compare_geometry(parse, program)
                      }["контур помещения (IoU)"]
            with self.subTest(доля_наружу=round(доля, 4)):
                self.assertEqual(строка.kind, ждём, строка.program)


if __name__ == "__main__":
    unittest.main()
