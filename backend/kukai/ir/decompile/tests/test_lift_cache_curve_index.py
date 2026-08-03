"""Главный лифт обязан видеть тот же curve-индекс, что и ре-лифт A5.

Архитектурный разбор 2026-07-25, §3.3 — подтверждено чтением вызовов:

  * ``pipeline.py`` СОБИРАЕТ curve-индекс (платит round-trip'ом в мост, пишет
    ``curve.index.json``) и зовёт ``cached_lift_document_detailed`` БЕЗ него —
    обёртка кэша просто не принимает такой параметр;
  * ``kir_idempotence.py`` в ре-лифт индекс ПЕРЕДАЁТ.

Отсюда инверсия принципа «одинаковый контекст»: пересобранная сторона видит
дугу, оригинальная — хорду, и сверка идёт на деградированном представлении.
Метрика при этом смещена В СВОЮ ПОЛЬЗУ: дуговая стена декомпилируется в хорду,
пересобирается прямой и засчитывается совпавшей.

Ловушка, из-за которой наивная передача индекса тихо НЕ сработала бы:
``lift_cache_key`` индекс не хешировал, поэтому на тот же документ вернулась бы
ранее сохранённая ХОРДОВАЯ запись — фикс выглядел бы применённым и молча не
работал.
"""

from __future__ import annotations

import math
import tempfile
import unittest

from kukai.ir.decompile.lift_cache import (
    cached_lift_document_detailed,
    lift_cache_key,
)
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


_RADIUS = 8000.0


def _arc_index(radius: float = _RADIUS) -> dict:
    """Side-индекс: стена «100» — четверть окружности, а не хорда."""

    return {
        "100": {
            "curve_kind": "arc",
            "arc": {
                "center_mm": [0.0, 0.0, 0.0],
                "radius_mm": radius,
                "x_axis": [1.0, 0.0, 0.0],
                "y_axis": [0.0, 1.0, 0.0],
                "start_angle_rad": 0.0,
                "end_angle_rad": math.pi / 2.0,
            },
        }
    }


def _curved_wall() -> L0Element:
    """Стена, чьи КОНЦЫ совпадают с концами дуги (frozen L0 знает только p0/p1)."""

    return L0Element(
        element_id="100", category="OST_Walls", category_ru="Стены",
        type_id="7", type_name="W200", level_id="10", level_name="L1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(_RADIUS, 0.0, 0.0), p1_mm=(0.0, _RADIUS, 0.0),
        rotation_deg=None,
        bbox_min_mm=(0.0, -100.0, 0.0),
        bbox_max_mm=(_RADIUS, _RADIUS, 3000.0),
        host_id=None, params={"WALL_USER_HEIGHT_PARAM": 3000.0})


def _doc(*elements: L0Element) -> L0Document:
    return L0Document(
        doc_name="curve-cache", revit_version="2024", units="mm",
        change_stamp="t", levels=(LevelInfo("10", "L1", 0.0),),
        grids=(), rooms=(), project_info=ProjectInfo(), elements=elements)


def _wall_node(result) -> dict:
    return {n["source_element_id"]: n for n in result.nodes}["100"]


class CachedLiftAcceptsTheCurveIndex(unittest.TestCase):
    """§3.3: обёртка кэша обязана доносить индекс до лифта."""

    def test_arc_survives_the_cached_path(self) -> None:
        result = cached_lift_document_detailed(
            _doc(_curved_wall()), None, None,
            wall_curve_index=_arc_index())
        params = _wall_node(result)["params"]
        self.assertIn(
            "arc", params,
            "дуговая стена деградировала до прямой в главном пайплайне, хотя "
            "curve-индекс собран и оплачен round-trip'ом в мост")
        self.assertAlmostEqual(params["arc"]["radius_mm"], _RADIUS, places=6)

    def test_without_the_index_the_wall_stays_straight(self) -> None:
        """Отсутствие индекса — честная деградация, а не ошибка."""

        result = cached_lift_document_detailed(_doc(_curved_wall()), None, None)
        self.assertNotIn("arc", _wall_node(result)["params"])


class CurveIndexEntersTheCacheKey(unittest.TestCase):
    """Ловушка: без индекса в ключе кэш вернул бы старую ХОРДОВУЮ запись."""

    def test_key_distinguishes_arc_from_no_index(self) -> None:
        document = _doc(_curved_wall())
        self.assertNotEqual(
            lift_cache_key(document, None, None),
            lift_cache_key(document, None, None,
                           wall_curve_index=_arc_index()),
            "ключ кэша не различает наличие curve-индекса — на тот же документ "
            "вернётся ранее сохранённый хордовый лифт")

    def test_key_distinguishes_different_arcs(self) -> None:
        document = _doc(_curved_wall())
        self.assertNotEqual(
            lift_cache_key(document, None, None,
                           wall_curve_index=_arc_index(_RADIUS)),
            lift_cache_key(document, None, None,
                           wall_curve_index=_arc_index(_RADIUS + 1000.0)),
            "разные дуги дали один ключ кэша")

    def test_enabled_cache_does_not_serve_a_stale_chord(self) -> None:
        """Сквозная проверка ловушки на РЕАЛЬНОМ кэше на диске."""

        document = _doc(_curved_wall())
        with tempfile.TemporaryDirectory() as cache_dir:
            # 1) прогрев БЕЗ индекса — на диск ложится хордовый результат
            cold = cached_lift_document_detailed(
                document, None, None, enabled=True, cache_dir=cache_dir)
            self.assertNotIn("arc", _wall_node(cold)["params"])

            # 2) тот же документ, но теперь индекс есть: обязана быть дуга,
            #    а не поднятая из кэша хорда
            warm = cached_lift_document_detailed(
                document, None, None, wall_curve_index=_arc_index(),
                enabled=True, cache_dir=cache_dir)
            self.assertIn(
                "arc", _wall_node(warm)["params"],
                "кэш отдал ХОРДОВУЮ запись на запрос с curve-индексом — "
                "фикс выглядит применённым и молча не работает")


if __name__ == "__main__":
    unittest.main()
