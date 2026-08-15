"""Индикатор компилируемости. Проверяется в первую очередь ЕГО ЧЕСТНОСТЬ.

Лампа, которая не знает, что она не смотрела, — это тот же дефект «свидетель
подписывает непрочитанную ось», из-за которого 10.08 переделали шесть
проверок, только размером с продукт. Поэтому тесты ниже держат не «зелёное
зелено», а «серое не выдаёт себя за зелёное» и «список слепоты неснимаем».
"""

import unittest

from kukai.viewer import compilability as C


def _program(count, *, ok=True):
    return {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": f"w{i}",
         "p0_mm": [0, i * 1000], "p1_mm": [5000, i * 1000],
         "height_mm": 3000,
         "level": ({"by": "name", "value": "L1"} if ok else "не селектор")}
        for i in range(count)]}


class TristateNeverCollapses(unittest.TestCase):

    def test_nothing_to_judge_is_unknown_and_not_ok(self):
        """Пустой журнал — это НЕ «здание компилируется». Слить эти два
        состояния значит показать зелёный там, где не смотрели."""
        verdict = C.check_programs([])
        self.assertEqual(verdict.state, "unknown")
        self.assertTrue(verdict.reason)
        self.assertNotEqual(verdict.state, "ok")

    def test_unknown_says_so_in_russian_too(self):
        payload = C.check_programs([]).to_dict()
        self.assertIn("НЕ", payload["state_ru"])

    def test_a_valid_program_is_ok(self):
        self.assertEqual(C.check_programs([_program(3)]).state, "ok")

    def test_a_typed_failure_is_refused_and_names_its_code(self):
        """Отказ обязан называть причину: молчащий откат неотличим от поломки."""
        verdict = C.check_programs([_program(2, ok=False)])
        self.assertEqual(verdict.state, "refused")
        self.assertTrue(verdict.refusals[0]["text"])


class BudgetsAreTheOnesTheCompilerHolds(unittest.TestCase):

    def test_authored_budget_refuses_at_twenty_one(self):
        """MAX_OPS_PER_PROGRAM = 20 меряет программу, НАПИСАННУЮ моделью.
        Замер: отказ приходит за 0.04 мс, то есть дешевле любого другого."""
        from kukai.ir.compiler import MAX_OPS_PER_PROGRAM
        self.assertEqual(MAX_OPS_PER_PROGRAM, 20)
        ok = C.check_programs([_program(MAX_OPS_PER_PROGRAM)])
        self.assertEqual(ok.state, "ok")
        over = C.check_programs([_program(MAX_OPS_PER_PROGRAM + 1)])
        self.assertEqual(over.state, "refused")
        self.assertIn("KIR-L001", over.refusals[0]["codes"])

    def test_bulk_budget_is_a_different_number_and_is_held(self):
        """MAX_BULK_OPS = 300 меряет ЧАНК МАТЕРИАЛИЗАТОРА — другой бюджет для
        другого автора. Смешать их значило бы отказать честной пересборке."""
        from kukai.ir.compiler import MAX_BULK_OPS
        self.assertEqual(MAX_BULK_OPS, 300)
        over = C.check_programs([_program(MAX_BULK_OPS + 1)], bulk=True)
        self.assertEqual(over.state, "refused")
        self.assertIn("KIR-L001", over.refusals[0]["codes"])

    def test_budgets_are_published_not_reimplemented(self):
        """Числа берутся ИЗ КОМПИЛЯТОРА. Своя копия разъехалась бы молча."""
        from kukai.ir.compiler import (MAX_BULK_OPS, MAX_OPS_PER_PROGRAM,
                                       MAX_VALIDATED_OPS)
        budgets = C.check_programs([_program(1)]).budgets
        self.assertEqual(budgets["authored"], MAX_OPS_PER_PROGRAM)
        self.assertEqual(budgets["internal_bulk"], MAX_BULK_OPS)
        self.assertEqual(budgets["post_macro"], MAX_VALIDATED_OPS)


class BlindnessIsPartOfTheAnswer(unittest.TestCase):

    def test_blind_list_rides_on_every_verdict_including_the_green_one(self):
        """Зелёная лампа обязана нести список того, чего она не смотрела —
        иначе зелёный читается как «проверено всё»."""
        for programs in ([], [_program(3)], [_program(2, ok=False)]):
            payload = C.check_programs(programs).to_dict()
            self.assertEqual(list(payload["blind"]), list(C.BLIND))
            self.assertTrue(payload["blind"])

    def test_roslyn_is_named_first_because_it_is_the_costliest_miss(self):
        self.assertIn("Roslyn", C.BLIND[0])

    def test_the_named_blind_spots_cover_the_gate_classes(self):
        """Список слепоты — ДАННЫЕ, и он обязан покрывать классы, которые
        индикатор физически не видит."""
        blob = " ".join(C.BLIND)
        for token in ("Roslyn", "api_signatures", "bridge_reference_closure",
                      "приёмка", "клеши", "design_check", "бюджет"):
            self.assertIn(token, blob, token)

    def test_grounding_absence_is_stated_not_implied(self):
        """Без снимка типов документа селекторы НЕ проверены. Показать это
        как «ok» значило бы обещать заземление, которого не делали."""
        verdict = C.check_programs([_program(3)])
        self.assertEqual(verdict.grounding, "not_checked")
        self.assertIn("НЕ ПРОВЕРЕНО", verdict.grounding_note)


class TheIndicatorNeverCostsTheTurn(unittest.TestCase):

    def test_it_does_not_raise_on_junk(self):
        """Индикатор существует ради хода и не имеет права его ронять."""
        for junk in ([None], [42], ["строка"], [{"ops": "не список"}]):
            C.check_programs(junk)

    def test_missing_session_is_unknown_rather_than_an_exception(self):
        payload = C.check_session("нет-такого-устройства", "нет-документа")
        self.assertEqual(payload["state"], "unknown")
        self.assertTrue(payload["reason"])
