"""Версия объясняет пустой пул — значит отвечает ПЕРВОЙ.

Найдено живым прогоном 13.08.2026 на Revit 2023: `create_topography
variety=toposolid` отвечал `KIR-G104` «toposolid_types: пусто в модели», хотя
компилятор ЗНАЛ правду — `KIR-E003` про версию стоял в эмиссии, а заземление
пула бежит раньше. Побеждал отказ, сработавший первым.

Цена не в неточности, а в НЕВЫПОЛНИМОСТИ совета: «пусто в модели» читается
как «заведи тип», и ЛЛМ уходила заводить тип толщи рельефа на версии, где
толщ рельефа не существует. Главный пользователь KIR — не человек, а модель;
она не догадается.

Обе половины стоят рядом НАМЕРЕННО: без второй проверка была бы зелена по
построению у любого опа, который вообще не собирается.
"""
from __future__ import annotations

import unittest

from kukai.ir.compiler import compile_program
from kukai.ir.ops_site import TOPOSOLID_MIN_VERSION

_POINTS = [[0, 0, 0], [8000, 0, 0], [8000, 6000, 0], [0, 6000, 500]]


def _prog(variety: str = "toposolid") -> dict:
    return {"ir_version": "1.0", "intent": "ось версий", "ops": [
        {"op": "create_topography", "id": "T1", "variety": variety,
         "points_mm": _POINTS,
         "level": {"by": "element_id", "value": 42}}]}


def _codes(out) -> list[str]:
    return [d.code for d in (out.diagnostics or [])]


class VersionAnswersBeforeTheEmptyPool(unittest.TestCase):

    def test_below_the_threshold_the_version_answers_and_the_pool_is_silent(
            self) -> None:
        # БЕЗ снапшота и БЕЗ пришпиленного типа — ровно тот вход, на котором
        # живьём приходило «пусто в модели».
        for ver in ("2021", "2022", "2023"):
            with self.subTest(ver=ver):
                out = compile_program(_prog(), revit_version=ver,
                                      query_id="t")
                self.assertFalse(out.ok)
                codes = _codes(out)
                self.assertIn("KIR-E003", codes,
                              f"версия промолчала на {ver}: {codes}")
                self.assertNotIn("KIR-G104", codes,
                                 "пустой пул снова отвечает вперёд версии")

    def test_with_a_real_snapshot_the_empty_pool_still_does_not_answer_first(
            self) -> None:
        """ЖИВОЕ УСЛОВИЕ 13.08: снапшот ЕСТЬ, а пул пуст — и пуст он не
        потому, что в документе не завели тип, а потому, что на этой версии
        толщ рельефа не бывает вовсе. Именно здесь приходил `KIR-G104`."""
        # Снапшот собран ЗДЕСЬ, а не импортом из соседнего теста: тот ставит
        # `KIR_REJECTIONS_PATH` на импорте, и страж окружения этого conftest
        # справедливо ловит утечку. Нужного здесь ровно два поля.
        snap = {
            "__document_fingerprint": {
                "title": "KIR Test Model",
                "path_name": "C:\\models\\kir-test.rvt",
                "project_uid": "kir-test-project-uid"},
            "levels": [{"id": 42, "name": "Этаж 1", "elevation_mm": 0.0}],
            "toposolid_types": [],
        }

        out = compile_program(_prog(), revit_version="2023",
                              snapshot=snap, query_id="t")
        codes = _codes(out)
        self.assertIn("KIR-E003", codes, f"версия промолчала: {codes}")
        self.assertNotIn("KIR-G104", codes,
                         "«пусто в модели» снова отвечает вперёд версии")

        # И контроль-FAIL этой же половины: на 2026 тот же пустой пул ОБЯЗАН
        # ответить сам — там пустота есть факт о документе, а не о версии,
        # и подменять её версией было бы ровно той же ложью наоборот.
        out26 = compile_program(_prog(), revit_version="2026",
                                snapshot=snap, query_id="t")
        codes26 = _codes(out26)
        self.assertNotIn("KIR-E003", codes26)
        self.assertTrue(
            any(c.startswith("KIR-G") for c in codes26),
            f"на 2026 пустой пул обязан отказать сам: {codes26}")

    def test_the_refusal_names_the_version_and_the_next_move(self) -> None:
        out = compile_program(_prog(), revit_version="2023", query_id="t")
        msg = next(d.message_ru for d in out.diagnostics
                   if d.code == "KIR-E003")
        self.assertIn("2023", msg)              # ЕГО версия, не абстрактная
        self.assertIn(TOPOSOLID_MIN_VERSION, msg)
        # Следующий ход назван, и назван как ДРУГОЙ элемент, а не замена.
        self.assertIn("surface", msg)

    def test_at_and_above_the_threshold_the_version_says_NOTHING(self) -> None:
        # Контроль-FAIL проверки: без него она была бы зелена на любом опе,
        # который просто не собирается.
        for ver in ("2024", "2025", "2026"):
            with self.subTest(ver=ver):
                out = compile_program(_prog(), revit_version=ver,
                                      query_id="t")
                self.assertNotIn("KIR-E003", _codes(out),
                                 f"версия отказала там, где толща законна"
                                 f" ({ver})")

    def test_the_other_variety_is_untouched_on_every_version(self) -> None:
        # `surface` живёт на всех шести; страж не смеет её задеть.
        for ver in ("2021", "2023", "2026"):
            with self.subTest(ver=ver):
                self.assertNotIn(
                    "KIR-E003",
                    _codes(compile_program(_prog("surface"),
                                           revit_version=ver, query_id="t")))


class TheGuardLivesWithItsThreshold(unittest.TestCase):
    """Порог и отказ — в одном месте; вызовов два, копий текста ноль."""

    def test_the_emitter_does_not_carry_its_own_copy_of_the_message(
            self) -> None:
        import inspect
        from kukai.ir import site_emit
        src = inspect.getsource(site_emit)
        self.assertEqual(
            src.count("тип появился только"), 0,
            "текст отказа снова размножен по эмиттеру")

    def test_the_snapshot_builder_says_why_it_compares_by_name(self) -> None:
        # Без этой записи следующий читатель заменит строку на typeof из
        # аккуратности и уронит снапшот на трёх версиях из шести.
        import inspect
        from kukai.ir import open_model
        src = inspect.getsource(open_model)
        head = src[:src.index('__AddPool("toposolid_types"')]
        self.assertIn("typeof(ToposolidType)", head[-1200:],
                      "у строковой сверки не сказано, почему она строковая")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
