"""THE BUILDING INDEX MUST REACH THE SCRIPT ON A LIVE TURN.

🔴 WHAT THIS FILE GUARDS, AND WHY IT IS NEEDED EXACTLY HERE.

The "building in the script's hands" wave built
`building.census/levels/find/get` and proved the owner's scenario — find on a
floor, look at one, write a fix — on a direct sandbox call. Meanwhile
`serving` was passing ONLY `model=` into `execute_author_script`, and NO ONE
was passing the `building=` argument. That means on a live turn `building.*`
ALWAYS answered "index not supplied," and the capability had been built and
left unconnected on the very day it was written.

The wave's tests did not see this because they called the sandbox DIRECTLY
and supplied the index by hand. That is why the input here is taken from
PROD (`serving._authored_input`) — form 27: a test that constructs its own
input guards the fixture, not the path.
"""
from __future__ import annotations

import asyncio
import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault(
    "KUKAI_DECOMPILE_DATA", "/opt/kukai-rebuild1/backend/backend/data/decompile")

from kir import serving  # noqa: E402
from kir import sandbox  # noqa: E402

#: A document whose decompile EXISTS in the corpus. The name is checked by
#: the test below, not taken on faith: the corpus is machine-local and may
#: not contain it at all.
DOC_WITH_RUN = "SOB6.2_UPO_L_DOO_AR_R23_kuklev.d.s"
LEVEL_WITH_WALLS = "L_02ДОО_+6.100"


def _corpus_present() -> bool:
    return os.path.isdir(os.environ.get("KUKAI_DECOMPILE_DATA", ""))


def _authored(source: str):
    async def go():
        return await serving._authored_input({"program_py": source}, None, None)
    return asyncio.run(go())


class ИмяСпрашиваетсяУАвторитета(unittest.TestCase):
    """Identity of the name with the script's namespace — by ratchet, not by
    convention."""

    def test_имя_объявлено_в_песочнице(self):
        self.assertIn(
            serving._BUILDING_NAME, sandbox.HOST_NAMES,
            "имя %r не объявлено в sandbox.HOST_NAMES — переименуют, и сборка "
            "индекса начнёт пропускаться МОЛЧА" % serving._BUILDING_NAME)


class РаботаТолькоЗаТемЧтоСпросили(unittest.TestCase):
    """The price: a script that did not name the name pays nothing at all."""

    def test_не_назвал_имени_индекс_не_собирается(self):
        self.assertIsNone(
            serving._building_index_for_turn("create_wall(id='w1')"))

    def test_назвал_имя_собирается(self):
        self.assertTrue(serving._script_may_read_building("building.census()"))

    def test_ошибка_только_в_сторону_лишней_работы(self):
        """A name in a comment gives extra work, not a missed capability."""
        self.assertTrue(serving._script_may_read_building("# про building"))


class ТриИсходаРазличимы(unittest.TestCase):
    """Index exists · no decompile · header unknown — three DIFFERENT
    answers."""

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
        # An empty index would read as "there is nothing in the building" —
        # that is a different fact.
        self.assertIn("НАШЕМ чтении", payload["refused"])

    def test_чужой_текст_объявлен_чужим(self):
        """The resolver's reason is written for the CACHE; the borrowing is
        named."""
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
        # Freshness is NOT proven by name — and this must be visible.
        self.assertIn("freshness", payload)
        self.assertIs(payload["freshness"]["proven"], False)


class ПричинаДоезжаетДоСкрипта(unittest.TestCase):
    """A refusal must be NAMED, not a generic "not supplied"."""

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
    """"Find on the floor → look at one → write a fix" — in ONE turn.

    The input is taken from prod (`_authored_input`), rather than assembled
    by hand.
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
        # The addresses are real element_id values from the index, not made
        # up.
        for op in ops:
            value = str(op.get("target", {}).get("value") or "")
            self.assertTrue(value.isdigit() and int(value) > 0,
                            "адрес правки не похож на element_id: %r" % value)

    def test_без_индекса_тот_же_скрипт_ОТКАЗЫВАЕТ(self):
        """WIRING FAIL CONTROL: remove the index — the scenario must fail.

        This is the control for the defect itself: before 16.08 the live
        turn behaved EXACTLY this way, and nothing turned red.
        """
        serving._turn_document_title = lambda: "НЕТ-ТАКОГО-ДОКУМЕНТА-9999"
        result = _authored(self.SCRIPT)
        self.assertIsNotNone(
            result.refusal,
            "скрипт прошёл БЕЗ индекса — значит проводка ничего не решает")


if __name__ == "__main__":
    unittest.main()
