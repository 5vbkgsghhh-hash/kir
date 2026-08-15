"""Ворота обязаны НАЗЫВАТЬ, чем они заземляются, рядом со своим числом.

ЗАЧЕМ. Зона НАБОР померила 12.08: `gate_runner` берёт заземляющий снимок из
`kukai.ir.tests.fixtures.GROUND_SNAPSHOT` — синтетической ФИКСТУРЫ. Значит
полнота её пулов есть свойство ВОРОТ, а не только набора, и всякое «OK» у
программы, требующей снимка, есть утверждение О ФИКСТУРЕ.

Цена уже заплачена однажды: у фикстуры не хватало пула `roof_types`, и
`create_roof`/`create_extrusion_roof` не заземлялись по умолчанию нигде.
Обошлось ОДНИМ красным лишь потому, что пул объявлен НЕОБЯЗАТЕЛЬНЫМ —
``("type", "roof_types", False)``. Обязательный в той же позиции обрушил бы
ворота ЦЕЛИКОМ, и выглядело бы это как «оп сломан». Механизм недостачи стоит
запомнить отдельно: пулов у производителя 35, у фикстуры 35, совпадающих имён
34 — **счёт сходился, расходились ИМЕНА**, и любая проверка «сколько пулов»
подтвердила бы полноту. Сверка МНОЖЕСТВ у `spec.OPS` стоит у зоны НАБОР; здесь
не дублируется.

ЧТО ПИНИТ ЭТОТ ФАЙЛ И ПОЧЕМУ ИМЕННО ЭТО. Канон говорит прямо: у прозы нет
детектора, ни один прогон не покраснеет оттого, что комментарий врёт. Поэтому
здесь пинится не обещание в докстринге, а ПЕЧАТАЕМАЯ СТРОКА и адрес, из которого
она собрана, — то, что мутация может покрасить. Убери объявление из итогового
блока — этот файл краснеет.

ЧЕГО ЭТОТ ФАЙЛ НЕ УТВЕРЖДАЕТ: он не гоняет ворота (для этого нужна живая
kukai-compile.service на :52412) и ничего не говорит о полноте самой фикстуры.
Он утверждает ровно одно — что предмет числа НАЗВАН там же, где число.
"""
from __future__ import annotations

import importlib
import inspect
import unittest

from kukai.ir import gate_runner


class TheGateNamesWhatItGroundsAgainst(unittest.TestCase):

    def test_the_origin_constant_points_at_the_fixture(self):
        """Адрес заземления объявлен константой, а не разбросан по строкам."""
        self.assertEqual(
            gate_runner.GROUND_SNAPSHOT_ORIGIN,
            "kukai.ir.tests.fixtures.GROUND_SNAPSHOT")

    def test_the_named_module_actually_holds_that_snapshot(self):
        """Контроль-FAIL адреса: имя обязано разрешаться в живой объект.

        Иначе объявление — строка, пережившая переезд фикстуры, и оно
        указывало бы в никуда с полной уверенностью.
        """
        module_path, _, attribute = (
            gate_runner.GROUND_SNAPSHOT_ORIGIN.rpartition("."))
        module = importlib.import_module(module_path)
        self.assertTrue(
            hasattr(module, attribute),
            f"адрес {gate_runner.GROUND_SNAPSHOT_ORIGIN} не разрешается — "
            f"объявление пережило переезд фикстуры")
        self.assertIsInstance(getattr(module, attribute), dict)

    def test_the_summary_prints_the_ground_beside_the_count(self):
        """Объявление стоит в ИТОГОВОМ блоке, а не только в докстринге.

        Читатель берёт последние строки прогона, а не докстринг модуля.
        Поэтому предмет числа обязан печататься там же, где число.
        """
        source = inspect.getsource(gate_runner.main)
        self.assertIn("GROUND_SNAPSHOT_ORIGIN", source,
                      "итоговый блок не называет заземление — число осталось "
                      "без предмета")
        self.assertIn("фикстур", source.lower(),
                      "заземление названо адресом, но не названо СИНТЕТИЧЕСКИМ")

    def test_the_verdict_stays_last(self):
        """Объявление напечатано ДО вердикта — иначе `tail -1` вернёт не то.

        Тот же закон, по которому в этом файле уже стоят манифест сборок и
        строка учёта: самое дешёвое чтение обязано оставаться правдивым.
        """
        source = inspect.getsource(gate_runner.main)
        ground = source.index("GROUND_SNAPSHOT_ORIGIN} — не против")
        verdict = source.index("'PASS' if failures == 0 else 'FAIL'")
        self.assertLess(
            ground, verdict,
            "объявление заземления печатается ПОСЛЕ вердикта — вердикт "
            "перестал быть последней строкой")


if __name__ == "__main__":
    unittest.main()
