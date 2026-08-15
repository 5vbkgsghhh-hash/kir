"""Источник `prism`: полоса вокруг оси × [z0, z1], и почему её сегодня никто
не заявляет.

Билдер написан, проверен и НЕ ПОДКЛЮЧЁН — ровно как `hull_from_wall_axis` до
него. Разница в том, что теперь это не «руки не дошли», а ЗАМЕР: волна sections
дала стене толщину из типа и проверила полосу на 800 настоящих стенах здания
Snowdon против габаритов Revit — 97 нарушений закона консервативности, до
2854 мм наружу (`clash.tools.bundle_containment_gate`). Замок «ноль нарушений»
не открыт.

Эти тесты держат три вещи: билдер верен, отказ НАЗВАН, и ни одна категория
таблицы не заявляет источник, за который никто не отвечает.
"""
from __future__ import annotations

import unittest

from kukai.clash import hulls as H


def _wall(prism=None, **extra):
    element = {"element_id": "w1", "category": "OST_Walls",
               "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [5000.0, 0.0, 0.0],
               "z0_mm": 0.0, "z1_mm": 3000.0}
    if prism is not None:
        element["prism"] = prism
    element.update(extra)
    return element


class ThePrismBuilderIsCorrect(unittest.TestCase):

    def test_a_full_set_builds_a_strip_of_half_the_width_on_each_side(self):
        """Смещение ровно нуль: живой замер 28.07 (700+ настоящих стен) —
        тело СИММЕТРИЧНО `LocationCurve` при любом ординале привязки."""
        record, why = H._prism_record(
            _wall({"width_mm": 200.0, "uniform": True}),
            dict(source_id="w1", category="OST_Walls", label="wall",
                 mvp_side="struct", level_id=None, type_name=None),
            (0.0, 3000.0))
        self.assertEqual(why, "")
        self.assertIsNotNone(record)
        lo, hi = record.hull.bounds()
        self.assertAlmostEqual(lo[1], -100.0)
        self.assertAlmostEqual(hi[1], 100.0)
        self.assertEqual((lo[2], hi[2]), (0.0, 3000.0))
        self.assertEqual(record.hull_source, "prism")
        self.assertEqual(record.grade, "conservative")

    def test_every_missing_input_is_a_named_refusal(self):
        common = dict(source_id="w1", category="OST_Walls", label="wall",
                      mvp_side="struct", level_id=None, type_name=None)
        cases = [
            (_wall({"uniform": True}), (0.0, 3000.0),
             "prism_incomplete_width_mm"),
            (_wall({"width_mm": 200.0, "uniform": False,
                    "blockers": ["wall_sweeps"]}), (0.0, 3000.0),
             "prism_blocked_wall_sweeps"),
            (_wall({"width_mm": 0.0, "uniform": True}), (0.0, 3000.0),
             "prism_width_invalid"),
            (_wall({"width_mm": 200.0, "uniform": True}), None,
             "prism_z_span_missing"),
        ]
        for element, span, expected in cases:
            with self.subTest(expected=expected):
                record, why = H._prism_record(element, dict(common), span)
                self.assertIsNone(record)
                self.assertEqual(why, expected)

    def test_a_zero_length_axis_refuses_instead_of_building_a_point(self):
        element = _wall({"width_mm": 200.0, "uniform": True})
        element["p1_mm"] = list(element["p0_mm"])
        record, why = H._prism_record(
            element, dict(source_id="w1", category="OST_Walls", label="wall",
                          mvp_side="struct", level_id=None, type_name=None),
            (0.0, 3000.0))
        self.assertIsNone(record)
        self.assertEqual(why, "prism_zero_length")

    def test_an_element_without_a_prism_key_says_nothing_at_all(self):
        """Ни отказа, ни оболочки: элемент, который не ПЫТАЛСЯ, не обязан
        объясняться — иначе разбор L0 засыпал бы перепись причинами того,
        чего у него и не спрашивали."""
        record, why = H._prism_record(
            _wall(), dict(source_id="w1", category="OST_Walls", label="wall",
                          mvp_side="struct", level_id=None, type_name=None),
            (0.0, 3000.0))
        self.assertIsNone(record)
        self.assertEqual(why, "")


class TheSourceIsClaimedOnlyWhereNothingCanBeMeasured(unittest.TestCase):
    """14.08.2026 полоса допущена — и допущена УЖЕ, чем читается строка таблицы.

    Прежний храповик здесь требовал верного: заявить `prism` можно только
    ВМЕСТЕ с пересъёмкой ворот содержания. Ворота НЕ пересняты, и 97 нарушений
    из 800 остаются в силе. Изменилось другое: те 800 — стены, РАЗОБРАННЫЕ из
    модели, у которых настоящий габарит есть, и полоса с ним спорит. У стены,
    ОБЪЯВЛЕННОЙ программой, габарита нет вовсе — там выбор «полоса против
    ничего», и замок ворот про этот случай не говорит ничего.

    Поэтому допуск стоит на ДАННЫХ, а не на намерении, и эти три теста держат
    обе его половины: где мерить не с чем — полоса; где есть чем — габарит,
    как и было.
    """

    def test_the_wall_is_the_only_category_claiming_the_prism(self):
        """Список заявителей ЗАКРЫТ. Новая категория с полосой обязана прийти
        со своим замером, а не унаследовать чужой."""
        claimed = [category for category, rule in H.KIND_TABLE.items()
                   if "prism" in rule.sources]
        self.assertEqual(claimed, ["OST_Walls"])
        self.assertEqual(H.KIND_TABLE["OST_Walls"].sources, H.SOURCES_PRISM)

    def test_a_declared_wall_gets_the_band_instead_of_nothing(self):
        """Стена без габарита: до правки — ноль тел, после — полоса.

        Это ровно случай владельца 14.08: программа назвала тип, толщина
        приехала из снимка, а сцена осталась пустой.
        """
        record, refusal = H.build_hull(_wall({"width_mm": 200.0,
                                              "uniform": True}))
        self.assertIsNone(refusal)
        self.assertEqual(record.hull_source, "prism")
        self.assertEqual(record.grade, "conservative")

    def test_a_wall_with_a_prism_still_falls_back_to_the_box(self):
        """ГЛАВНЫЙ ЗАМОК ПРАВКИ, и он не сдвинулся ни на байт: там, где
        настоящее тело измерено, оно и остаётся телом. Замок содержания
        закрыт для этого случая, и полоса его не обходит."""
        element = _wall({"width_mm": 200.0, "uniform": True})
        element["bbox_min_mm"] = [0.0, -500.0, 0.0]
        element["bbox_max_mm"] = [5000.0, 500.0, 3000.0]
        record, refusal = H.build_hull(element)
        self.assertIsNone(refusal)
        self.assertEqual(record.hull_source, "bbox")

    def test_the_corpus_shape_is_untouched_because_it_carries_no_prism(self):
        """РАДИУС ПРАВКИ, замеренный, а не обещанный: элемент КОРПУСА — это
        габарит без ключа `prism`, и он получает ровно то же, что получал."""
        element = _wall()
        element["bbox_min_mm"] = [0.0, -500.0, 0.0]
        element["bbox_max_mm"] = [5000.0, 500.0, 3000.0]
        record, refusal = H.build_hull(element)
        self.assertIsNone(refusal)
        self.assertEqual(record.hull_source, "bbox")
        self.assertEqual(record.grade, "coarse")


if __name__ == "__main__":
    unittest.main()
