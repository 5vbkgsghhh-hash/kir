"""ПРОЦЕНТ ПОКРЫТИЯ ЕДЕТ СО СВОИМИ УСЛОВИЯМИ, ИНАЧЕ ОН НЕИНТЕРПРЕТИРУЕМ.

ПОВОД — ЗАМЕР 12.08.2026, И ОН БЬЁТ В ГЛАВНУЮ ВИТРИНУ ПРОЕКТА. Две ревизии
ОДНОГО фасада, компилятор между ними не менялся ни на строку:

    sob62_fas_r23_v12   63.80%      прочитано 5 095, отсканировано 14 категорий
    sob62_fas_r23_v19   91.23%      прочитано 5 218, отсканировано 15

27 пунктов. Делает их НЕ выразительность и не объём чтения в наивном смысле
(+2.4% элементов). Одна лишняя прочитанная категория — 122 сетки витража —
позволила лифтеру ОПОЗНАТЬ 1 264 панели и импоста как порождённых детей
витражной стены; `generator_child` из честной цифры исключается, поэтому упал
ЗНАМЕНАТЕЛЬ (4 205 -> 2 942), а числитель почти не двинулся (2 683 -> 2 806).
**123 прочитанных элемента переклассифицировали 1 264 других.**

НИ ОДИН СУЩЕСТВОВАВШИЙ ФЛАГ ЭТОГО НЕ ЛОВИЛ: у обоих прогонов
`census_balanced: true`, `errors: []`, `done: 1`, `is_partial_read: false`,
`generator_children_assumption_broken: false`. Различал их только
`categories_scanned`, который ни с чем не сравнивался.

СЛЕДСТВИЕ, КОТОРОЕ ВАЖНЕЕ САМОГО СЛУЧАЯ: опубликованные 96.13% сняты БЕЗ этих
условий рядом. Число не «неверно» — оно НЕИНТЕРПРЕТИРУЕМО, и разница между
этими двумя словами и есть честность проекта.

СИГНАЛ НЕ ЗАВЕДЁН ЗАНОВО, А СПРОШЕН У АВТОРИТЕТОВ: таблица извлечения знает,
что мы умеем читать; перепись §18.1 — что в документе есть; `L0` — что
прочитано. `category_outside_table` в условия НЕ входит намеренно: это
известный пробел, ради описания которого метрика и заведена.
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_coverage_conditions.jsonl"))

_TOOLS = pathlib.Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import content_coverage as CC  # noqa: E402


#: Полный набор боковых индексов — по умолчанию у обоих отчётов, чтобы тесты
#: первого условия не разваливались о второе.
_ALL_SIDES = ["annotation", "curtain", "curve", "dimension",
              "family_placement", "group", "mep_system", "sketch", "tag"]


def _report(unread: dict[str, int], scanned: int,
            sides: list[str] | None = None) -> dict:
    """Отчёт-скелет: тест про УСЛОВИЯ, а не про арифметику покрытия."""
    return {"conditions": {"table_available": True,
                           "categories_scanned": scanned,
                           "in_table_unread": dict(unread),
                           "in_table_unread_elements": sum(unread.values()),
                           "side_indexes": list(
                               _ALL_SIDES if sides is None else sides)}}


class TwoReportsAreComparableOnlyOnEqualReads(unittest.TestCase):

    def test_control_a_report_is_comparable_with_itself(self):
        """КОНТРОЛЬ-PASS. Без него отказ ниже ничего не значил бы: правило,
        которое отвергает ВСЁ, не отличает сопоставимое от несопоставимого."""
        one = _report({"OST_Dimensions": 426}, scanned=14)
        ok, why = CC.comparable(one, one)
        self.assertTrue(ok, why)
        self.assertEqual(why, "")

    def test_one_extra_unread_category_makes_them_incomparable(self):
        """КОНТРОЛЬ-FAIL. Ровно случай двух ревизий фасада: множества
        различаются ОДНОЙ категорией, и этого достаточно."""
        left = _report({"OST_Dimensions": 426, "OST_CurtainGridsWall": 122},
                       scanned=14)
        right = _report({"OST_Dimensions": 426}, scanned=15)
        ok, why = CC.comparable(left, right)
        self.assertFalse(ok)
        self.assertIn("OST_CurtainGridsWall", why)
        self.assertIn("несопоставимы", why)

    def test_the_refusal_names_both_sides(self):
        """Отказ, называющий код без данных, заставляет работать читателя —
        тот же дефект, что у отказа без следующего хода."""
        left = _report({"OST_A": 1}, scanned=14)
        right = _report({"OST_B": 2}, scanned=14)
        ok, why = CC.comparable(left, right)
        self.assertFalse(ok)
        self.assertIn("OST_A", why)
        self.assertIn("OST_B", why)

    def test_unknown_conditions_refuse_rather_than_assume_equality(self):
        """Отсутствие условий — НЕ «условия одинаковы». Пустой словарь читался
        бы как «всё прочитано», то есть как самый благоприятный исход."""
        ok, why = CC.comparable({"conditions": {"table_available": False}},
                                _report({}, scanned=15))
        self.assertFalse(ok)
        self.assertIn("неизвестны", why)

    def test_equal_sets_with_different_counts_stay_comparable(self):
        """Сопоставимость решает МНОЖЕСТВО категорий, а не их размеры: два
        здания законно имеют разное число элементов в одной категории, и
        запрещать такое сравнение значило бы запретить разброс вообще."""
        ok, why = CC.comparable(_report({"OST_Dimensions": 426}, 14),
                                _report({"OST_Dimensions": 9}, 14))
        self.assertTrue(ok, why)


class SideIndexesAreAConditionOfTheSameRank(unittest.TestCase):
    """ВТОРОЕ УСЛОВИЕ, ЗАКРЫТОЕ 12.08.2026 ДО ПЕРВОГО ЖИВОГО СРАВНЕНИЯ.

    Перепись может быть полна у обоих прогонов, а лифтеру у одного НЕЧЕМ
    поднимать: боковой индекс решает саму ВОЗМОЖНОСТЬ подъёма. Без
    `family_placement` каждый экземпляр семейства — атом; без `dimension`
    размеры не поднимутся никогда.

    ПОВОД НАЗВАН ДО УКУСА, А НЕ ПОСЛЕ. `k2_ar_rd_v15`, с которого сняты все
    наши числа покрытия, завершился с `stage="error"` и БЕЗ `mep_system`,
    `tag`, `dimension`. Живой разбор идёт со всеми стадиями. Их сравнение
    прошло бы прежний `comparable()` (непрочитанные категории совпадают,
    перепись у обоих полна) и показало бы разницу, которую прочли бы как
    выигрыш компилятора — а это разница ПОЛНОТЫ ПРОГОНОВ. Тот же дефект, что
    стоил 27 пунктов на двух ревизиях фасада, и в самом важном сравнении.
    """

    def test_same_indexes_stay_comparable(self):
        """КОНТРОЛЬ-PASS: правило, отвергающее ВСЁ, не отличает сопоставимое
        от несопоставимого."""
        ok, why = CC.comparable(_report({}, 44), _report({}, 44))
        self.assertTrue(ok, why)

    def test_a_missing_side_index_makes_them_incomparable(self):
        left = _report({}, 44, sides=["curve", "sketch"])
        right = _report({}, 44, sides=["curve", "sketch", "dimension"])
        ok, why = CC.comparable(left, right)
        self.assertFalse(ok)
        self.assertIn("dimension", why)
        self.assertIn("боковых индексов", why)

    def test_the_refusal_explains_that_it_is_not_the_compiler(self):
        """Отказ обязан назвать МЕХАНИЗМ, иначе его прочтут как придирку и
        обойдут: разница в полноте прогонов легко читается как разница
        компилятора, ради чего замок и ставится."""
        ok, why = CC.comparable(_report({}, 44, sides=["curve"]),
                                _report({}, 44, sides=["curve", "tag"]))
        self.assertFalse(ok)
        self.assertIn("НЕ потому, что компилятор хуже", why)

    def test_unknown_side_indexes_refuse_rather_than_assume_equality(self):
        """Отчёт, снятый прибором до 12.08, набора не несёт. Пустой список
        читался бы как «индексов не было» — самый благоприятный исход."""
        stale = {"conditions": {"table_available": True,
                                "in_table_unread": {},
                                "categories_scanned": 44}}
        ok, why = CC.comparable(stale, _report({}, 44))
        self.assertFalse(ok)
        self.assertIn("неизвестен", why)

    def test_the_list_comes_from_the_loader_not_a_second_copy(self):
        """Свой список имён разошёлся бы с загрузчиком при первой новой
        стадии, и разошёлся бы МОЛЧА: недостающее имя выглядело бы как «у
        прогона нет этого индекса»."""
        import sys
        sys.path.insert(0, str(_TOOLS))
        from relift_offline import _SIDE_INDEX_FILES
        self.assertEqual(tuple(CC._SIDE_INDEX_NAMES), tuple(_SIDE_INDEX_FILES))


class TheConditionsLineAlwaysSaysWhatItKnows(unittest.TestCase):

    def test_it_names_the_unread_categories(self):
        text = CC._conditions_line(
            _report({"OST_CurtainGridsWall": 122}, 14)["conditions"])
        self.assertIn("OST_CurtainGridsWall", text)
        self.assertIn("ТОЛЬКО с прогоном", text)

    def test_an_empty_set_still_states_the_condition(self):
        """Пустое множество — это УСЛОВИЕ «прочитано всё, что умеем», а не
        отсутствие условия; молчание тут читалось бы как «сравнивай с чем
        угодно»."""
        text = CC._conditions_line(_report({}, 15)["conditions"])
        self.assertIn("Сопоставим только", text)

    def test_a_missing_table_says_so_instead_of_printing_zero(self):
        text = CC._conditions_line({"table_available": False})
        self.assertIn("УСЛОВИЯ НЕИЗВЕСТНЫ", text)


if __name__ == "__main__":
    unittest.main()
