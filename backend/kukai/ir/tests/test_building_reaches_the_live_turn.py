"""ИНДЕКС ЗДАНИЯ ОБЯЗАН ДОЕХАТЬ ДО СКРИПТА НА ЖИВОМ ХОДЕ.

🔴 ЧТО ЭТОТ ФАЙЛ СТОРОЖИТ, И ПОЧЕМУ ОН НУЖЕН ИМЕННО ЗДЕСЬ.

Волна «здание в руках скрипта» построила `building.census/levels/find/get`
и доказала сценарий владельца — найти на этаже, посмотреть один, написать
правку — на прямом вызове песочницы. `serving` при этом передавал в
`execute_author_script` ТОЛЬКО `model=`, и аргумент `building=` не передавал
НИКТО. То есть на живом ходе `building.*` отвечал «индекс не подан» ВСЕГДА, а
способность была построена и не соединена в тот же день, что и написана.

Тесты волны этого не видели, потому что звали песочницу НАПРЯМУЮ и подавали
индекс руками. Поэтому здесь вход берётся у ПРОДА (`serving._authored_input`)
— форма 27: тест, строящий вход сам, сторожит фикстуру, а не путь.
"""
from __future__ import annotations

import asyncio
import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault(
    "KUKAI_DECOMPILE_DATA", "/opt/kukai-rebuild1/backend/backend/data/decompile")

from kukai.ir import serving  # noqa: E402
from kukai.ir import sandbox  # noqa: E402

#: Документ, чей разбор в корпусе ЕСТЬ. Имя проверяется тестом ниже, а не
#: принимается на веру: корпус машинно-локален и может не содержать его вовсе.
DOC_WITH_RUN = "SOB6.2_UPO_L_DOO_AR_R23_kuklev.d.s"
LEVEL_WITH_WALLS = "L_02ДОО_+6.100"


def _corpus_present() -> bool:
    return os.path.isdir(os.environ.get("KUKAI_DECOMPILE_DATA", ""))


def _authored(source: str):
    async def go():
        return await serving._authored_input({"program_py": source}, None, None)
    return asyncio.run(go())


class ИмяСпрашиваетсяУАвторитета(unittest.TestCase):
    """Тождество имени с пространством скрипта — ратчетом, а не соглашением."""

    def test_имя_объявлено_в_песочнице(self):
        self.assertIn(
            serving._BUILDING_NAME, sandbox.HOST_NAMES,
            "имя %r не объявлено в sandbox.HOST_NAMES — переименуют, и сборка "
            "индекса начнёт пропускаться МОЛЧА" % serving._BUILDING_NAME)


class РаботаТолькоЗаТемЧтоСпросили(unittest.TestCase):
    """Цена: скрипт, не назвавший имени, не платит ни за что."""

    def test_не_назвал_имени_индекс_не_собирается(self):
        self.assertIsNone(
            serving._building_index_for_turn("create_wall(id='w1')"))

    def test_назвал_имя_собирается(self):
        self.assertTrue(serving._script_may_read_building("building.census()"))

    def test_ошибка_только_в_сторону_лишней_работы(self):
        """Имя в комментарии даёт лишнюю работу, а не пропущенную способность."""
        self.assertTrue(serving._script_may_read_building("# про building"))


class ТриИсходаРазличимы(unittest.TestCase):
    """Индекс есть · разбора нет · заголовок неизвестен — три РАЗНЫХ ответа."""

    def setUp(self):
        self._title = serving._turn_document_title

    def tearDown(self):
        serving._turn_document_title = self._title

    def test_заголовок_неизвестен_называется(self):
        serving._turn_document_title = lambda: ""
        payload = serving._building_index_for_turn("building.census()")
        self.assertIn("refused", payload)
        self.assertIn("плагин", payload["refused"])

    def test_разбора_нет_называется_и_не_пустой_индекс(self):
        serving._turn_document_title = lambda: "НЕТ-ТАКОГО-ДОКУМЕНТА-9999"
        payload = serving._building_index_for_turn("building.census()")
        self.assertIn("refused", payload)
        self.assertNotIn("tier", payload)
        # Пустой индекс читался бы как «в здании ничего нет» — это другой факт.
        self.assertIn("НАШЕМ чтении", payload["refused"])

    def test_чужой_текст_объявлен_чужим(self):
        """Причина резолвера написана для КЛЕША; заимствование называется."""
        serving._turn_document_title = lambda: "НЕТ-ТАКОГО-ДОКУМЕНТА-9999"
        payload = serving._building_index_for_turn("building.census()")
        self.assertIn("общий с клешем", payload["refused"])

    @unittest.skipUnless(_corpus_present(), "корпус разборов машинно-локален")
    def test_разбор_есть_индекс_приезжает_со_свежестью(self):
        serving._turn_document_title = lambda: DOC_WITH_RUN
        payload = serving._building_index_for_turn("building.census()")
        self.assertNotIn("refused", payload)
        self.assertEqual(payload.get("tier"), "full")
        self.assertTrue(payload.get("source_run"))
        # Свежесть НЕ доказывается именем — и это должно быть видно.
        self.assertIn("freshness", payload)
        self.assertIs(payload["freshness"]["proven"], False)


class ПричинаДоезжаетДоСкрипта(unittest.TestCase):
    """Отказ обязан быть НАЗВАННЫМ, а не общим «не подан»."""

    def test_причина_видна_скрипту(self):
        view = sandbox.BuildingView({"refused": "разбора документа нет"})
        with self.assertRaises(RuntimeError) as ctx:
            view.census()
        self.assertIn("разбора документа нет", str(ctx.exception))

    def test_без_причины_общий_отказ_остаётся(self):
        view = sandbox.BuildingView()
        with self.assertRaises(RuntimeError) as ctx:
            view.census()
        self.assertIn("не подан", str(ctx.exception))


@unittest.skipUnless(_corpus_present(), "корпус разборов машинно-локален")
class СценарийВладельцаНаЖивомПути(unittest.TestCase):
    """«Найди на этаже → посмотри один → напиши правку» — ОДНИМ ходом.

    Вход берётся у прода (`_authored_input`), а не собирается руками.
    """

    def setUp(self):
        self._title = serving._turn_document_title
        serving._turn_document_title = lambda: DOC_WITH_RUN

    def tearDown(self):
        serving._turn_document_title = self._title

    SCRIPT = (
        'walls = building.find(cat="OST_Walls", lvl="%s", limit=3)\n'
        'one = building.get(walls[0]["id"])\n'
        'for w in walls:\n'
        '    set_param(id="p"+w["id"], target={"by":"element_id","value":w["id"]},\n'
        '              param="Комментарии", value="проверено")\n' % LEVEL_WITH_WALLS)

    def test_ход_пишет_правку_по_настоящим_адресам(self):
        result = _authored(self.SCRIPT)
        self.assertIsNone(result.refusal, "сценарий владельца не прошёл")
        ops = ((result.args or {}).get("program") or {}).get("ops") or []
        self.assertEqual(len(ops), 3)
        self.assertEqual({o.get("op") for o in ops}, {"set_param"})
        # Адреса — настоящие element_id из индекса, а не выдуманные.
        for op in ops:
            value = str(op.get("target", {}).get("value") or "")
            self.assertTrue(value.isdigit() and int(value) > 0,
                            "адрес правки не похож на element_id: %r" % value)

    def test_без_индекса_тот_же_скрипт_ОТКАЗЫВАЕТ(self):
        """КОНТРОЛЬ-FAIL проводки: снимаем индекс — сценарий обязан упасть.

        Это и есть контроль на сам дефект: до 16.08 живой ход вёл себя ИМЕННО
        так, и никто не краснел.
        """
        serving._turn_document_title = lambda: "НЕТ-ТАКОГО-ДОКУМЕНТА-9999"
        result = _authored(self.SCRIPT)
        self.assertIsNotNone(
            result.refusal,
            "скрипт прошёл БЕЗ индекса — значит проводка ничего не решает")


if __name__ == "__main__":
    unittest.main()
