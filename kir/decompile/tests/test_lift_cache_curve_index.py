"""The main lift must see the same curve index as the A5 re-lift.

Architectural analysis 2026-07-25, §3.3 — confirmed by reading the calls:

  * ``pipeline.py`` COLLECTS the curve index (pays a round trip to the
    bridge, writes ``curve.index.json``) and calls
    ``cached_lift_document_detailed`` WITHOUT it — the cache wrapper simply
    does not accept such a parameter;
  * ``kir/idempotence.py`` PASSES the index into the re-lift.

Hence an inversion of the "same context" principle: the reassembled side
sees an arc, the original sees a chord, and the comparison runs on a
degraded representation. The metric is skewed IN ITS OWN FAVOR here: an arc
wall is decompiled into a chord, reassembled as a straight line, and
counted as matching.

The trap that would make a naive passing-in of the index silently NOT
work: ``lift_cache_key`` did not hash the index, so the same document would
return a previously saved CHORD record — the fix would look applied and
silently not work.
"""

from __future__ import annotations

import math
import tempfile
import unittest

from kir.decompile.lift_cache import (
    cached_lift_document_detailed,
    lift_cache_key,
)
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


_RADIUS = 8000.0


def _arc_index(radius: float = _RADIUS) -> dict:
    """Side index: wall "100" is a quarter circle, not a chord."""

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
    """A wall whose ENDPOINTS coincide with the ends of the arc (frozen L0
    knows only p0/p1)."""

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
    """§3.3: the cache wrapper must carry the index through to the lift."""

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
        """Absence of the index is an honest degradation, not an error."""

        result = cached_lift_document_detailed(_doc(_curved_wall()), None, None)
        self.assertNotIn("arc", _wall_node(result)["params"])


class CurveIndexEntersTheCacheKey(unittest.TestCase):
    """The trap: without the index in the key, the cache would return the
    old CHORD record."""

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
        """An end-to-end check of the trap against a REAL cache on disk."""

        document = _doc(_curved_wall())
        with tempfile.TemporaryDirectory() as cache_dir:
            # 1) warm-up WITHOUT the index — a chord result lands on disk
            cold = cached_lift_document_detailed(
                document, None, None, enabled=True, cache_dir=cache_dir)
            self.assertNotIn("arc", _wall_node(cold)["params"])

            # 2) the same document, but now the index is present: the
            #    result must be an arc, not a chord pulled from the cache
            warm = cached_lift_document_detailed(
                document, None, None, wall_curve_index=_arc_index(),
                enabled=True, cache_dir=cache_dir)
            self.assertIn(
                "arc", _wall_node(warm)["params"],
                "кэш отдал ХОРДОВУЮ запись на запрос с curve-индексом — "
                "фикс выглядит применённым и молча не работает")


if __name__ == "__main__":
    unittest.main()
