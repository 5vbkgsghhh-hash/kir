"""ЕДИНИЦА ЗАМЫСЛА И ПРЕДИКАТ ЦЕЛОСТНОСТИ — арность N, на которой стоит замысел.

🔴 ЗАЧЕМ ЭТОТ ФАЙЛ СУЩЕСТВУЕТ. Весь остальной аппарат проверяемости работает на
АРНОСТИ 1: оп -> элемент -> постусловие. Замысел живёт на арности N — «эти три
стены суть одна лента», — и постусловие сказать этого не может ПО ПОСТРОЕНИЮ:
оно стоит на одном опе и про соседа не знает. Полосатая стена проходит все три
оси свидетеля, потому что каждая стена в отдельности безупречна, и владелец
видит дефект ГЛАЗАМИ — то есть ровно тем органом, которого у модели нет.

ЧЕГО ЭТОТ ФАЙЛ НЕ ДЕЛАЕТ, и это названо, чтобы не читалось шире: он не судит
ВЫБОР прочтения. Если автор объявил лентой то, что лентой быть не должно,
предикат промолчит — он проверяет ЗАЯВЛЕННОЕ прочтение. Судить замысел мог бы
только тот, кто знает задачу, а её знает автор.

ЗАКОН РЕЕСТРА ПРОЧТЕНИЙ: он ОТКРЫТ на дополнение, и каждый жилец обязан иметь
ПАРУ контролей — нарушающий вход даёт находку, здоровый вход даёт пусто.
Предикат без такой пары зелен по построению и не измеряет ничего (форма 18).
Ратчет ниже (`EveryReadingCanSayNo`) падает на добавлении имени без пары.
"""
from __future__ import annotations

import json
import unittest

from kukai.ir import dsl
from kukai.ir.assembly_view import (
    ADDRESS_CAP, OBSERVATION_CODES, UNIT_READS, UNIT_READS_RU,
    digest, observe_units, reads_continuous)
from kukai.ir.course import take_ops, unit


# ── общая утварь ────────────────────────────────────────────────────────────

_BRICK = "Кирпич 380"
#: Три пролёта встык на одной оси — «лента» в самом обычном смысле.
_RUN3 = (((0, 0), (3000, 0)), ((3000, 0), (6000, 0)), ((6000, 0), (9000, 0)))


def _program(spans, *, types=None, heights=None, reads_as="continuous",
             as_group=False, name="лента"):
    """Программа с ОДНОЙ единицей — собранная ТЕМ ЖЕ путём, что у автора.

    🔴 Программа строится языком (`dsl` + `course.unit`) и сливается
    `course.take_ops()` — то есть ровно так, как её собирает песочница. Форма
    `units` руками здесь НЕ пишется: тест, собирающий свой вход руками,
    сторожит фикстуру, а не продукт (форма 27, куплена этим же деревом 15.08).
    """
    dsl.reset()
    with dsl.program():
        level = dsl.OP_FUNCTIONS["create_level"](elev_mm=0.0, name="Этаж 1")
        with unit(name, reads_as=reads_as, as_group=as_group):
            for index, (a, b) in enumerate(spans):
                dsl.OP_FUNCTIONS["create_wall"](
                    p0_mm=list(a), p1_mm=list(b), level=level,
                    height_mm=(heights[index] if heights else 3000.0),
                    type=(types[index] if types else _BRICK))
        return take_ops()


def _observe(program):
    return observe_units([program])


# ── 1. ВОРОТА ВОЛНЫ ─────────────────────────────────────────────────────────

class TheStripedWallIsSeenAndTheHonestBandIsNot(unittest.TestCase):
    """ДВА ВОРОТА ВОЛНЫ, и второе не менее важно первого.

    Предикат, кричащий на всё, не отличается от предиката, молчащего обо всём:
    оба не несут сведений. Поэтому «полосатая даёт находку» проверяется В ПАРЕ
    с «честная не даёт».
    """

    def test_the_striped_wall_yields_an_observation_addressed_by_unit(self):
        """ГЛАВНЫЕ ВОРОТА. Три стены встык, средняя ДРУГОГО типа: геометрия
        непрерывна, прочтение — полосы. Каждая стена в отдельности безупречна,
        и именно поэтому арность 1 этого не видит."""
        program = _program(_RUN3, types=[_BRICK, "Витраж 200", _BRICK])
        found, silent = _observe(program)

        self.assertEqual(len(found), 1, (found, silent))
        observation = found[0]
        self.assertEqual(observation.code, "unit_not_continuous")
        # АДРЕС ЕДИНИЦЫ — рядом с адресами элементов, а не вместо них.
        self.assertEqual(observation.of_unit, "u0")
        self.assertTrue(observation.address, "наблюдение без адреса элементов")
        # Адресуется МЕНЬШИНСТВО: править надо полосу, а не два соседа.
        self.assertEqual(observation.address, ("wall2",), observation.address)

    def test_the_honest_band_yields_nothing(self):
        """ВТОРЫЕ ВОРОТА. Те же три стены встык, но одного типа и одной
        высоты — это законная лента, набранная из отрезков, и находкой она
        быть не должна."""
        found, silent = _observe(_program(_RUN3))
        self.assertEqual(found, [], (found, silent))

    def test_a_single_wall_band_yields_nothing(self):
        """Одна стена — тоже честная лента. И она же вырожденный вход: см.
        `TheDegenerateInputIsNamed` ниже, где проверяется, что молчание здесь
        НАЗВАНО, а не выдано за проверку."""
        found, _silent = _observe(_program((((0, 0), (9000, 0)),)))
        self.assertEqual(found, [])


# ── 2. ЧТО ИМЕННО СЧИТАЕТСЯ РАЗРЫВОМ ───────────────────────────────────────

class TheReadingNamesWhatBrokeIt(unittest.TestCase):
    """Каждый род разрыва проверяется отдельно: «не читается» без причины
    заставляет автора гадать, а канон требует, чтобы отказ называл причину И
    следующий ход."""

    def _breaks(self, spans, **kw):
        program = _program(spans, **kw)
        members = [op for op in program["ops"] if op.get("op") == "create_wall"]
        return {reason for reason, _ids in reads_continuous(members)}

    def test_a_gap_between_spans_is_a_break(self):
        self.assertEqual(
            self._breaks((((0, 0), (3000, 0)), ((3500, 0), (6000, 0)))),
            {"gap"})

    def test_a_kink_is_a_break(self):
        self.assertEqual(
            self._breaks((((0, 0), (3000, 0)), ((3000, 0), (5000, 2000)))),
            {"kink"})

    def test_a_differing_type_is_a_break(self):
        self.assertEqual(self._breaks(_RUN3, types=[_BRICK, "Витраж 200", _BRICK]),
                         {"type_differs"})

    def test_a_differing_height_is_a_break(self):
        self.assertEqual(self._breaks(_RUN3, heights=[3000.0, 4200.0, 3000.0]),
                         {"height_differs"})

    def test_a_clean_run_breaks_on_nothing(self):
        """КОНТРОЛЬ ко всем четырём: предикат, находящий разрыв везде, дал бы
        те же четыре зелёные проверки выше и не измерял бы ничего."""
        self.assertEqual(self._breaks(_RUN3), set())

    def test_the_tolerance_is_compared_in_millimetres(self):
        """Отклонение от оси считается В МИЛЛИМЕТРАХ, а не векторным
        произведением: канон называет сравнение допуска в мм с величиной в мм²
        своим ИМЕННЫМ дефектом (`_on_segment`, `_point_in_prism`).

        Полмиллиметра — это шум `anchor_mm`, измеренный fold; он обязан
        пройти. Пять миллиметров — излом, и он обязан не пройти."""
        noise = self._breaks((((0, 0), (3000, 0)), ((3000, 0), (6000, 0.5))))
        real = self._breaks((((0, 0), (3000, 0)), ((3000, 0), (6000, 5.0))))
        self.assertEqual(noise, set(), "шум 0.5 мм принят за излом")
        self.assertEqual(real, {"kink"}, "излом 5 мм не замечен")


# ── 3. ЗАПИСЬ ЕДИНИЦЫ ОРТОГОНАЛЬНА ГРУППЕ РЕВИТА ───────────────────────────

class TheUnitIsRecordedRegardlessOfTheRevitGroup(unittest.TestCase):
    """🔴 СУТЬ ВОЛНЫ. До 15.08.2026 `unit()` означал РОВНО «сделай группу
    Ревита»: члены схлопывались в один `create_group`, и всё, что автор сказал
    о замысле, переставало существовать сразу после раскрытия.

    Теперь запись единицы и форма её записи в Ревите — РАЗНЫЕ решения.
    """

    def test_the_slice_form_records_the_unit_and_keeps_the_ops(self):
        program = _program(_RUN3, as_group=False)
        rows = program["units"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["as_group"], False)
        # опы остались в программе как есть: уровень + три стены
        self.assertEqual(sum(1 for op in program["ops"]
                             if op.get("op") == "create_wall"), 3)
        self.assertEqual(len(rows[0]["member_ids"]), 3)

    def test_the_group_form_records_the_unit_and_collapses_the_ops(self):
        program = _program(_RUN3, as_group=True)
        rows = program["units"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["as_group"], True)
        # опы схлопнулись: уровень + ОДНА группа
        names = [op.get("op") for op in program["ops"]]
        self.assertEqual(names.count("create_group"), 1, names)
        self.assertEqual(names.count("create_wall"), 0, names)
        # члены при этом названы поимённо — их и адресует наблюдение
        self.assertEqual(len(rows[0]["member_ids"]), 3)

    def test_the_reading_is_the_same_in_both_forms(self):
        """🔴 ГЛАВНОЕ СВОЙСТВО: способ ЗАПИСИ не меняет того, как набор
        ЧИТАЕТСЯ. Если бы менял, автору пришлось бы выбирать форму записи ради
        проверки — то есть проверка диктовала бы замысел."""
        striped = dict(types=[_BRICK, "Витраж 200", _BRICK])
        as_slice, _ = _observe(_program(_RUN3, as_group=False, **striped))
        as_group, _ = _observe(_program(_RUN3, as_group=True, **striped))
        self.assertEqual(len(as_slice), 1)
        self.assertEqual(len(as_group), 1)
        self.assertEqual(as_slice[0].code, as_group[0].code)
        self.assertEqual(as_slice[0].address, as_group[0].address)
        self.assertEqual(as_slice[0].of_unit, as_group[0].of_unit)

    def test_the_default_is_still_the_group(self):
        """Умолчание в этой волне НЕ меняется намеренно: `create_group`
        опознают пять потребителей (`course.measure`, `sdk`, `acceptance`,
        `design.coherence`, `clash_bundle`), и смена умолчания — отдельное
        решение с отдельной ценой."""
        dsl.reset()
        with dsl.program():
            level = dsl.OP_FUNCTIONS["create_level"](elev_mm=0.0, name="Этаж 1")
            with unit("без указания формы"):
                dsl.OP_FUNCTIONS["create_wall"](
                    p0_mm=[0, 0], p1_mm=[3000, 0], level=level, height_mm=3000.0)
            program = take_ops()
        self.assertEqual([op.get("op") for op in program["ops"]].count(
            "create_group"), 1)
        self.assertEqual(program["units"][0]["as_group"], True)


# ── 4. МОЛЧАНИЕ НАЗЫВАЕТСЯ ─────────────────────────────────────────────────

class TheDegenerateInputIsNamed(unittest.TestCase):
    """Вырожденный вход обязан быть НАЗВАН, а не пройти молча зелёным.

    На одном члене всякий предикат непрерывности зелен ПО ПОСТРОЕНИЮ —
    сравнивать не с чем. Зелёное здесь означало бы «проверено», хотя не
    проверялось ничего: форма 18 канона, пойманная на входе.
    """

    def test_one_member_is_silence_with_a_reason_not_a_pass(self):
        _found, silent = _observe(_program((((0, 0), (9000, 0)),)))
        self.assertTrue(silent, "единственный член прошёл молча")
        reason = " ".join(silent.values())
        self.assertIn("сравнивать", reason)
        self.assertIn(">= 2", reason)

    def test_two_members_are_actually_judged(self):
        """КОНТРОЛЬ к предыдущему: на двух членах предикат обязан РАБОТАТЬ,
        иначе порог «>= 2» просто выключил бы проверку."""
        _found, silent = _observe(_program(
            (((0, 0), (3000, 0)), ((3000, 0), (6000, 0)))))
        self.assertEqual(silent, {}, silent)

    def test_a_unit_without_a_reading_is_recorded_but_not_judged(self):
        """Единица без `reads_as` — законная запись: она остаётся АДРЕСОМ.
        Судить её не за что, и выдумывать прочтение за автора нельзя."""
        program = _program(_RUN3, reads_as=None,
                           types=[_BRICK, "Витраж 200", _BRICK])
        self.assertEqual(len(program["units"]), 1)
        self.assertIsNone(program["units"][0]["reads_as"])
        found, silent = _observe(program)
        self.assertEqual(found, [])
        self.assertEqual(silent, {})

    def test_an_unknown_reading_is_refused_at_authoring_time(self):
        """Имя вне реестра отвергается ТАМ, ГДЕ ПИШУТ, — с перечнем известных.
        Отказ на сливе программы не получил бы номера строки автора."""
        dsl.reset()
        with self.assertRaises(Exception) as caught:
            with dsl.program():
                level = dsl.OP_FUNCTIONS["create_level"](elev_mm=0.0, name="Э1")
                with unit("лента", reads_as="совершенно_любое"):
                    dsl.OP_FUNCTIONS["create_wall"](
                        p0_mm=[0, 0], p1_mm=[1000, 0], level=level,
                        height_mm=3000.0)
        text = str(caught.exception)
        self.assertIn("continuous", text, text)

    def test_placements_without_a_group_are_refused(self):
        """Вхождения — свойство ГРУППЫ. Без группы повторять нечего, и молча
        проглотить их значило бы потерять написанное автором."""
        dsl.reset()
        with self.assertRaises(Exception):
            with dsl.program():
                level = dsl.OP_FUNCTIONS["create_level"](elev_mm=0.0, name="Э1")
                with unit("лента", as_group=False, placements=[(1600, 0)]):
                    dsl.OP_FUNCTIONS["create_wall"](
                        p0_mm=[0, 0], p1_mm=[1000, 0], level=level,
                        height_mm=3000.0)


# ── 5. РАТЧЕТ РЕЕСТРА ПРОЧТЕНИЙ ────────────────────────────────────────────

class EveryReadingCanSayNo(unittest.TestCase):
    """🔴 РАТЧЕТ ОТКРЫТОГО РЕЕСТРА. Реестр прочтений открыт на дополнение — и
    ровно поэтому каждый жилец обязан нести свою пару контролей. Предикат,
    который не умеет сказать «нет», не предикат, а украшение.

    Этот класс падает на добавлении имени БЕЗ пары. Он и есть цена входа.
    """

    #: имя прочтения -> (вход, который ОБЯЗАН дать находку,
    #:                   вход, который ОБЯЗАН пройти чисто)
    CONTROLS: dict[str, tuple[dict, dict]] = {
        "continuous": (
            {"spans": _RUN3, "types": [_BRICK, "Витраж 200", _BRICK]},
            {"spans": _RUN3},
        ),
    }

    def test_every_registered_reading_has_a_pair_of_controls(self):
        self.assertEqual(
            sorted(UNIT_READS), sorted(self.CONTROLS),
            "у прочтения нет пары контролей: предикат без контроля зелен по "
            "построению и не измеряет ничего. Заведи оба входа — нарушающий "
            "и здоровый — и только тогда вноси имя в UNIT_READS")

    def test_every_registered_reading_is_explained_to_the_author(self):
        self.assertEqual(
            sorted(UNIT_READS), sorted(UNIT_READS_RU),
            "прочтение без объяснения: автор увидит имя в отказе и не поймёт, "
            "что оно требует")

    def test_every_registered_reading_has_its_own_observation_code(self):
        """Реестр ОТКРЫТ, список кодов ЗАКРЫТ — и шов между ними обязан
        скрипеть: новый предикат без своего кода прислонился бы к чужому и
        стал бы неотличим от него в квитанции."""
        for name in UNIT_READS:
            with self.subTest(reading=name):
                self.assertIn("unit_not_%s" % name, OBSERVATION_CODES)

    def test_the_violating_input_is_found_and_the_healthy_one_is_not(self):
        for name, (bad, good) in self.CONTROLS.items():
            with self.subTest(reading=name):
                found, _ = _observe(_program(reads_as=name, **bad))
                self.assertEqual(len(found), 1,
                                 "нарушающий вход прочтения %r не найден" % name)
                found, _ = _observe(_program(reads_as=name, **good))
                self.assertEqual(found, [],
                                 "здоровый вход прочтения %r объявлен "
                                 "нарушением" % name)


# ── 6. НАБЛЮДЕНИЕ ПЕРЕЖИВАЕТ СВОРАЧИВАНИЕ ИСТОРИИ ──────────────────────────

class TheUnitAddressSurvivesHistoryCollapse(unittest.TestCase):
    """Восприятие, которое модель не может ВСПОМНИТЬ, — не петля.

    Проверяется ТЕМ ЖЕ прибором, что и дайджест сборки: настоящим
    сворачивателем истории, а не его пересказом.
    """

    def _view(self):
        from kukai.ir.assembly_view import AssemblyView
        found, silent = _observe(_program(
            _RUN3, types=[_BRICK, "Витраж 200", _BRICK]))
        return AssemblyView(observations=tuple(found), silent_sources=silent)

    def test_the_digest_carries_the_unit_address(self):
        line = digest(self._view())
        self.assertIn("unit_not_continuous", line)
        self.assertIn("/u0", line, line)

    def test_the_digest_survives_the_real_collapser(self):
        from kukai.api.chat_helpers import _summarize_tool_result
        from kukai.ir.serving import lift_assembly_note

        note = digest(self._view())
        block = {"programs": 1, "verdict": "PASS", "assembly_note": note}
        receipt = lift_assembly_note(
            {"ok": True, "result": {}, "building": block}, block)
        collapsed = _summarize_tool_result(
            json.dumps(receipt, ensure_ascii=False), cap=600)
        self.assertIn("unit_not_continuous", collapsed, collapsed)
        self.assertIn("/u0", collapsed, collapsed)

    def test_without_the_lift_it_would_be_lost(self):
        """КОНТРОЛЬ: без подъёма дайджест не выживает — иначе предыдущая
        проверка зелена по причине, к единице отношения не имеющей."""
        from kukai.api.chat_helpers import _summarize_tool_result
        nested = json.dumps({
            "ok": True, "result": {},
            "building": {"assembly_note": digest(self._view())},
        }, ensure_ascii=False)
        self.assertNotIn("unit_not_continuous",
                         _summarize_tool_result(nested, cap=600))


# ── 7. ФОРМА ТАБЛИЦЫ И ЕЁ ГРАНИЦЫ ──────────────────────────────────────────

class TheUnitTableIsAnEnvelopeRow(unittest.TestCase):

    def test_ops_are_byte_identical_with_and_without_a_reading(self):
        """🔴 УСЛОВИЕ, А НЕ ВКУС. Дайджест программы подписывает её; метка
        прочтения, вписанная в оп, сдвинула бы подпись у здания, которое не
        менялось. Поэтому единица едет ТАБЛИЦЕЙ, а опы остаются теми же."""
        with_reading = _program(_RUN3, reads_as="continuous")
        without = _program(_RUN3, reads_as=None)
        self.assertEqual(with_reading["ops"], without["ops"])

    def test_no_units_means_no_key(self):
        """Отсутствие остаётся отсутствием: программа без единиц не несёт
        ключа `units` вовсе."""
        dsl.reset()
        with dsl.program():
            level = dsl.OP_FUNCTIONS["create_level"](elev_mm=0.0, name="Этаж 1")
            dsl.OP_FUNCTIONS["create_wall"](
                p0_mm=[0, 0], p1_mm=[3000, 0], level=level, height_mm=3000.0)
            program = take_ops()
        self.assertNotIn("units", program)

    def test_the_envelope_accepts_units(self):
        """Конверт закрыт, и `units` внесён в него ЯВНЫМ решением: программа
        с единицами — обычная программа, отказывать ей не за что."""
        # `plan_program` ОТКАЗЫВАЕТ ИСКЛЮЧЕНИЕМ (`KirRefusal`), а не полем
        # `.ok` — первая редакция этого теста спрашивала несуществующее поле и
        # падала `AttributeError`, то есть проверяла бы форму ответа, а не
        # приём конверта. Отсутствие отказа И ЕСТЬ приём.
        from kukai.ir.compiler import plan_program
        plan_program(_program(_RUN3))   # не бросил -> конверт принят

    def test_an_unknown_envelope_key_is_still_refused(self):
        """КОНТРОЛЬ к предыдущему: конверт не открылся вообще — он принял
        ровно одно новое имя."""
        from kukai.ir.compiler import plan_program
        from kukai.ir.diag import KirRefusal
        program = _program(_RUN3)
        program["совершенно_любое"] = []
        with self.assertRaises(KirRefusal):
            plan_program(program)

    def test_the_unit_address_is_deterministic_and_independent_of_the_name(self):
        first = _program(_RUN3, name="лента")["units"][0]["unit_id"]
        second = _program(_RUN3, name="совсем другое имя")["units"][0]["unit_id"]
        self.assertEqual(first, second, "адрес единицы зависит от имени автора")

    def test_the_address_cap_is_declared_when_it_bites(self):
        """Усечённый список адресов, не сказавший об усечении, читается как
        полный. На широкой ленте усечение обязано быть объявлено."""
        # РАЗРЫВАМИ, А НЕ ТИПОМ. Первая редакция делала меньшинством ОДНУ
        # стену и получала один адрес — то есть проверяла бы усечение на
        # входе, где усекать нечего (вырожденный контроль). Дыра между каждой
        # парой даёт находку у каждой стены и адресов заведомо больше потолка.
        wide = tuple(((i * 2000, 0), (i * 2000 + 1000, 0))
                     for i in range(ADDRESS_CAP + 6))
        found, _ = _observe(_program(wide))
        self.assertEqual(len(found), 1)
        observation = found[0]
        self.assertLessEqual(len(observation.address), ADDRESS_CAP)
        self.assertGreater(observation.address_total, len(observation.address))
        self.assertIn("at_of", observation.to_dict())


if __name__ == "__main__":
    unittest.main()
