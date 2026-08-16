"""KIR-P003 на JSON-двери обязан называть СЛЕДУЮЩИЙ ХОД, а не только повод.

ЗАМЕР, КУПИВШИЙ ЭТОТ ФАЙЛ — живой ход владельца 16.08.2026, флеш-модель
`deepseek-v4-flash`. В ОДНОМ ходу рядом легли два отказа, и они повели себя
ПРОТИВОПОЛОЖНО:

  * `KIR-T002`, `create_roof.slopes` — «slopes без единого угла — это плоская
    крыша, просто не задавай поле». Исправленная программа пришла через
    ЧЕТЫРЕ СЕКУНДЫ (10:45:45 -> 10:45:49);
  * `KIR-P003`, `create_door.__host_wall__` — «неизвестное поле». Ход УМЕР.

Разница ровно одна: первый текст несёт следующий ход, второй — повод.

ПОЧЕМУ ЭТО ПРОВЕРЯЕТСЯ, А НЕ ОСТАВЛЕНО НА ВКУС. Требование владельца от
16.08: КИР обязан работать на ФЛЕШ-модели («обычные подписчики тоже должны
уметь им пользоваться»). Значит текст отказа — не документация для умного, а
РЕЛЬС для слабого, и он обязан держаться прибором.

🔴 ЧЕГО ЭТОТ ФАЙЛ НЕ ПРОВЕРЯЕТ. Он не проверяет, что модель ПОСЛУШАЕТСЯ. Это
свойство модели, снимаемое лестницей, а не набором. Здесь держится ровно то,
что в нашей власти: следующий ход НАЗВАН и ВЫВЕДЕН ИЗ РЕЕСТРА.
"""
from __future__ import annotations

import unittest

from kukai.ir import compiler, spec
from kukai.ir.tests.test_course import GROUND_SNAPSHOT

LVL = {"by": "name", "value": "Этаж 1"}


def _compile(op: dict):
    program = {"ir_version": spec.IR_VERSION, "intent": "контроль", "ops": [op]}
    return compiler.compile_program(
        program, revit_version="2026", snapshot=GROUND_SNAPSHOT, bulk=False)


def _p003(res) -> str:
    for d in (res.diagnostics or []):
        if d.code == "KIR-P003":
            return d.message_ru or ""
    raise AssertionError(
        "KIR-P003 не поднялся вовсе — зонд слеп, а не предмет исправен; "
        f"коды: {[d.code for d in (res.diagnostics or [])]}")


class TheRefusalNamesTheNextMove(unittest.TestCase):
    def test_it_names_the_next_move_in_words(self):
        """КОНТРОЛЬ-FAIL: верните message_ru к голому «неизвестное поле 'x' у y»
        — этот тест покраснеет, и покраснеет ПОВЕДЕНЧЕСКИ, на тексте, который
        читает модель, а не на наличии символа."""
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg,
                      "отказ назвал повод и не назвал следующий ход")

    def test_the_slots_come_from_the_registry_not_from_prose(self):
        """Список слотов обязан БЫТЬ ВЫВЕДЕН, а не написан.

        Проверяется не «в тексте есть слова», а совпадение с реестром: каждый
        параметр опа обязан быть назван. Рукописный список разъехался бы с
        реестром на первой же новой операции, и разъехался бы МОЛЧА — в этом
        дереве разъехались ВСЕ рукописные списки и НИ ОДИН порождаемый.
        """
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        missing = [p.name for p in spec.OPS["create_wall"].params
                   if p.name not in msg]
        self.assertEqual(missing, [],
                         f"слоты реестра не названы в отказе: {missing}")

    def test_a_near_miss_gets_the_near_name(self):
        """`height` -> `height_mm`. Суффикс `_mm` — самая частая промашка."""
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        self.assertIn("height_mm", msg)
        self.assertIn("Похоже на", msg,
                      "ближайшее имя не предложено, хотя оно вычислимо")

    def test_a_far_miss_does_not_invent_a_neighbour(self):
        """ОБРАТНЫЙ ПОЛЮС, без него починка свелась бы к «всегда что-то советуй».

        У поля, не похожего ни на что, «похоже на» появиться НЕ ДОЛЖНО:
        выдуманный сосед хуже молчания, потому что его проверяют ходом.
        """
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "зззз": 1}))
        self.assertNotIn("Похоже на", msg)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", msg,
                      "следующий ход обязан быть назван и без соседа")

    def test_the_call_form_has_one_generator_for_both_doors(self):
        """Скриптовая и JSON-дверь печатают ОДНУ форму опа, а не две похожих.

        Второй текст о форме опа был бы вторым мнением и разошёлся бы с первым
        ровно тогда, когда оба читают подряд. Держится тождеством строки, а не
        обещанием в докстроке.
        """
        from kukai.ir.dsl import _call_form
        msg = _p003(_compile({"op": "create_wall", "id": "w1",
                              "p0_mm": [0, 0], "p1_mm": [4000, 0],
                              "level": LVL, "height": 3000}))
        self.assertIn(_call_form(spec.OPS["create_wall"]), msg,
                      "JSON-дверь печатает СВОЮ форму опа, а не общую")


class TheSyntheticFieldIsStillRefusedWhereItDoesNotBelong(unittest.TestCase):
    """Многословие не имеет права стать глушилкой отказов.

    `__host_wall__` у владельца (`create_door`) СНИМАЕТСЯ разбором, у чужого
    опа — по-прежнему KIR-P003. Этот полюс уже держит
    `test_synthetic_fields_have_one_authority.py`; здесь проверяется, что мой
    текст его не размыл.
    """

    def test_owner_op_passes_and_stranger_op_refuses(self):
        door = _compile({"op": "create_door", "id": "d1",
                         "host": {"by": "element_id", "value": 424242},
                         "offset_mm": 1500,
                         spec.SYNTHETIC_HOST_WALL: {"p0_mm": [0, 0],
                                                    "p1_mm": [1000, 0]}})
        codes = {d.code for d in (door.diagnostics or [])}
        self.assertNotIn("KIR-P003", codes,
                         "синтетика у владельца обязана сниматься молча")

        wall = _compile({"op": "create_wall", "id": "w1",
                         "p0_mm": [0, 0], "p1_mm": [4000, 0], "level": LVL,
                         spec.SYNTHETIC_HOST_WALL: {"p0_mm": [0, 0]}})
        self.assertIn("KIR-P003", {d.code for d in (wall.diagnostics or [])},
                      "синтетика у чужого опа обязана остаться отказом")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
