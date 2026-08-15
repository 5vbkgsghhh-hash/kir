"""Происхождение версии ДОЕЗЖАЕТ до читателя — на успехе и на отказе.

Половина работы, которой не было: единственный источник (`revit_version.py`)
можно построить и подключить, а квитанция всё равно не скажет, угадали мы или
нам сообщили. Тогда величина по-прежнему объявлена в одном месте и прочитана в
другом — наш собственный класс дефекта, только этажом выше.

Эти проверки пиннят ФАКТ, а не формулировку: не текст сообщения, а наличие
поля и его значение.

ГРАНИЦА. Здесь НЕТ утверждения, что выводов версии в дереве ровно N — перепись
выводов и её храповик пишет зона ВОРОТА отдельным файлом. Здесь только: то, что
вывели, доезжает.
"""
from __future__ import annotations

import asyncio
import inspect
import unittest

from kukai.ir import revit_version as rv
from kukai.ir import serving


class _Shim:
    """Минимальная поверхность llm_client, какой её видит `serving`."""

    def __init__(self, value):
        self._revit_version = value


class TheResolverIsAskedOnceAndNeverRaises(unittest.TestCase):

    def test_the_unknown_session_is_named_defaulted_not_reported(self):
        # `chat_ws.py` НАМЕРЕННО кладёт None в сессии без документа.
        r = serving._resolved_revit_version(_Shim(None))
        self.assertEqual(r.version, rv.DEFAULT_VERSION)
        self.assertEqual(r.provenance, rv.DEFAULTED)
        self.assertTrue(r.is_guess)

    def test_a_reported_version_is_not_a_guess(self):
        r = serving._resolved_revit_version(_Shim("2023"))
        self.assertEqual(r.version, "2023")
        self.assertEqual(r.provenance, rv.REPORTED)
        self.assertFalse(r.is_guess)

    def test_a_client_whose_attribute_explodes_does_not_break_the_turn(self):
        class Hostile:
            @property
            def _revit_version(self):
                raise RuntimeError("чужой объект")

        r = serving._resolved_revit_version(Hostile())
        self.assertEqual(r.provenance, rv.DEFAULTED)

    def test_a_version_we_do_not_hold_is_told_apart_from_silence(self):
        # Ревит 2019 у пользователя — факт о МИРЕ; пустая строка — факт о
        # нашем канале. Слить их в одно слово значит потерять оба.
        self.assertEqual(
            serving._resolved_revit_version(_Shim("2019")).provenance,
            rv.UNSUPPORTED)
        self.assertEqual(
            serving._resolved_revit_version(_Shim("")).provenance,
            rv.DEFAULTED)

    def test_the_resolved_version_is_always_one_the_emitter_can_take(self):
        for raw in (None, "", "чушь", "2019", "2030", "0", "Revit 2024.2"):
            with self.subTest(raw=raw):
                self.assertIn(
                    serving._resolved_revit_version(_Shim(raw)).version,
                    rv.supported())


class TheStampRidesOnEveryOutcome(unittest.TestCase):

    def test_a_guess_is_named_in_the_receipt(self):
        out = serving._stamp_revit_version({"ok": True}, _Shim(None))
        self.assertEqual(out["revit_version"], rv.DEFAULT_VERSION)
        self.assertEqual(out["revit_version_provenance"], rv.DEFAULTED)

    def test_a_refusal_carries_it_too(self):
        # Отказ «оп недоступен на Revit 2021» читается по-разному в
        # зависимости от того, СООБЩИЛИ нам версию или мы её подставили.
        out = serving._stamp_revit_version(
            {"ok": False, "error": "emit"}, _Shim(""))
        self.assertEqual(out["revit_version_provenance"], rv.DEFAULTED)

    def test_an_honest_version_adds_NOTHING(self):
        # Обычный ход обязан остаться байт в байт прежним.
        before = {"ok": True, "kir": True}
        after = serving._stamp_revit_version(dict(before), _Shim("2023"))
        self.assertEqual(after, before)

    def test_the_stamp_never_overwrites_what_the_turn_already_said(self):
        out = serving._stamp_revit_version(
            {"ok": True, "revit_version": "2021"}, _Shim(None))
        self.assertEqual(out["revit_version"], "2021")

    def test_a_hostile_shim_leaves_the_result_untouched(self):
        class Hostile:
            @property
            def _revit_version(self):
                raise RuntimeError("нет")

        before = {"ok": True}
        self.assertEqual(
            serving._stamp_revit_version(dict(before), Hostile()),
            {"ok": True, "revit_version": rv.DEFAULT_VERSION,
             "revit_version_provenance": rv.DEFAULTED,
             "revit_version_raw": ""})

    def test_a_non_dict_result_is_returned_as_is(self):
        self.assertIsNone(serving._stamp_revit_version(None, _Shim(None)))

    def test_the_raw_string_cannot_flood_the_receipt(self):
        # Строку даёт МОСТ — чужая сторона, а квитанции здесь под бюджетом.
        out = serving._stamp_revit_version({"ok": True}, _Shim("щ" * 5000))
        self.assertLessEqual(
            len(out["revit_version_raw"]), rv.RAW_IN_RECEIPT_CAP + 1)
        self.assertTrue(out["revit_version_raw"].endswith("…"))


class TheWiringIsPinnedAtBothDoors(unittest.TestCase):
    """Пин ПРОВОДКИ, а не поведения: без него можно построить источник,
    написать штамп и не позвать его ни разу — наш преобладающий дефект
    «приехало неподключённым»."""

    def test_both_public_doors_call_the_stamp(self):
        for door in (serving.handle_revit_ir, serving.handle_revit_ir_bulk):
            with self.subTest(door=door.__name__):
                self.assertIn("_stamp_revit_version",
                              inspect.getsource(door),
                              f"{door.__name__} не ставит происхождение")

    def test_serving_no_longer_derives_the_version_by_hand(self):
        src = inspect.getsource(serving)
        self.assertNotIn('or "2026"', src,
                         "в serving вернулось умолчание литералом")
        self.assertNotIn(r'_re.search(r"20\d\d"', src,
                         "в serving вернулся свой разбор года")

    def test_the_admin_route_does_not_launder_a_guess_into_a_report(self):
        from kukai.api import admin_kir
        self.assertNotIn('target["revit_version"] or "2026"',
                         inspect.getsource(admin_kir),
                         "админский маршрут снова выдаёт догадку за отчёт")


class TheStampSurvivesTheRealDoor(unittest.IsolatedAsyncioTestCase):

    async def test_a_gate_refusal_from_the_real_door_carries_provenance(self):
        # Настоящая дверь, настоящий отказ гейта (устройство не админское),
        # а не собранный руками словарь.
        res = await serving.handle_revit_ir(
            {"program": {"ir_version": "1.0", "ops": []}},
            _Shim(None), None, query_id="probe-prov")
        self.assertIsInstance(res, dict)
        self.assertIs(res.get("ok"), False)
        self.assertEqual(res.get("revit_version_provenance"), rv.DEFAULTED,
                         f"отказ доехал без происхождения: {sorted(res)}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
