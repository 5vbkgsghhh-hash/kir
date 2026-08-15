"""Контроль ПОМОЩНИКА, и он не выводится из зелени тех 95, кому помощник дан.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. `gate_fixture.enter_kir_mode` открывает третье условие
гейта девяноста пяти тестам. **Помощник-пустышка позеленил бы их всех** — не тот
ключ, не тот контекст, не та область видимости, — и позеленил бы ВХОЛОСТУЮ: гейт
по-прежнему отказывал бы, просто никто бы этого не замечал.

    девяносто пять зелёных без акта различения
    ХУЖЕ девяноста пяти красных: красные видны, эти нет

Поэтому у помощника собственный контроль, и он двусторонний. Одной стороны мало:
«с помощником открыто» верно и у помощника, который ничего не делает, если путь
и без него был открыт. Разделяет только вторая строка.

    control-PASS   помощник вызван     -> revit_ir_enabled() is True
    control-FAIL   помощник НЕ вызван  -> revit_ir_enabled() is False

Оба условия, кроме третьего, здесь выставлены РУКАМИ — иначе контроль проверял
бы чужую фикстуру вместо помощника.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kukai.ir import serving
from kukai.ir.tests.gate_fixture import enter_kir_mode


class TheHelperOpensTheThirdConditionAndOnlyIt(unittest.TestCase):

    def setUp(self) -> None:
        # Восстанавливаем НАБЛЮДЁННОЕ, а не запомненную константу.
        self._env = {k: os.environ.get(k)
                     for k in ("KUKAI_KIR_TOOL", "KUKAI_ADMIN_DEVICES")}
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()

    def tearDown(self) -> None:
        self._dev.stop()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_without_the_helper_the_gate_is_shut(self):
        """КОНТРОЛЬ-FAIL, и он здесь главный.

        Флаг есть, устройство админское — отказать может ТОЛЬКО режим. Если это
        утверждение когда-нибудь станет зелёным без помощника, значит путь
        открыт чем-то ещё, и все девяносто пять «починенных» тестов проходят не
        благодаря фикстуре, а мимо неё.
        """
        self.assertFalse(
            serving.revit_ir_enabled(),
            "гейт открыт БЕЗ третьего условия — либо режим утёк из соседнего "
            "теста, либо гейт перестал его требовать; в обоих случаях помощник "
            "ничего не доказывает")

    def test_with_the_helper_the_gate_opens(self):
        """КОНТРОЛЬ-PASS: помощник действительно ставит признак."""
        enter_kir_mode(self)
        self.assertTrue(
            serving.revit_ir_enabled(),
            "помощник вызван, а гейт закрыт — фикстура пустышка")

    def test_the_helper_restores_what_it_observed(self):
        """Признак живёт в `ContextVar`; невозврат делает соседей зелёными.

        Проверяется ИМЕННО возврат, а не установка: тест, оставивший режим
        включённым, чинит глобальное состояние за других — та самая подпорка,
        которую мы вынимали из `test_any_query`, и она маскирует чужой дефект.
        """
        from kukai.llm.turn_context import kir_mode_active

        before = kir_mode_active()
        case = unittest.TestCase()
        case.setUp()
        enter_kir_mode(case)
        self.assertTrue(kir_mode_active(), "помощник не поставил признак")
        case.doCleanups()
        self.assertEqual(kir_mode_active(), before,
                         "помощник не вернул наблюдённое значение")


if __name__ == "__main__":
    unittest.main()
