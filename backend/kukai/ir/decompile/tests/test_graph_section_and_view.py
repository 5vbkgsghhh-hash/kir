"""ИЗМЕРЕННОЕ СЕЧЕНИЕ И ПРОЕКЦИЯ ДЛЯ ВЬЮЕРА — опровергающие тесты.

ЧТО ТЕРЯЛОСЬ. L0 несёт наружный диаметр КАЖДОЙ трубы, а `lift._lift_pipe`
читает только `RBS_PIPE_DIAMETER_PARAM` (номинал). Замер 10.08.2026 (сырой
разбор `L0.jsonl`, `snowdon_plumb_v4`, машинно-локальный корпус):

    труб 15 342, с наружным 15 342, с номиналом 15 342 — то есть 100 % несут ОБА
    различных пар (номинал -> наружный): 14
        12.7  -> 15.875   x7318      50.8  -> 60.325  x1835
        25.4  -> 28.575   x3300      50.8  -> 53.975  x530
        101.6 -> 114.3    x1424      152.4 -> 168.275 x430
    наружный РАВЕН номиналу лишь у 20 труб из 15 342

КЛЮЧЕВОЙ ФАКТ, А НЕ ПРОСТО ПОТЕРЯ: **номинал 50.8 отвечает и 60.325, и
53.975**, значит отображение номинал -> наружный НЕ ФУНКЦИЯ, и восстановить
наружный из того, что несёт оп, НЕВОЗМОЖНО В ПРИНЦИПЕ — он определяется ТИПОМ.

И это не только трубы: `snowdon_elec_v1` несёт `RBS_CONDUIT_OUTER_DIAM_PARAM`
у 530 коробов из 605 узлов с измеренным сечением. Категорию никто не называл.

ПОЧЕМУ ФАКТ ЛЁГ НА УЗЕЛ, А НЕ В ОПЕРАНД ОПА. Наружный диаметр — это то, что
Revit ВЫВОДИТ из типа; оп уже несёт `pipe_type` по имени (`_catalog_ref`),
поэтому ПЕРЕСБОРКА не теряет ничего: Revit выведет наружный из того же типа.
Теряют его ОФЛАЙН-ЧИТАТЕЛИ — клеши и вьюер, — у которых таблицы типоразмеров
документа нет. Сделать его витнессируемым операндом значило бы объявить
своим то, что назначает Revit, и получить свидетеля, требующего того, чего
никто не просил, — тот самый класс, что закрыт в `tests/test_silent_defaults.py`
(«либо эмиттер СТАВИТ значение, либо решает Revit»).
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
    Existence,
    graph_from_l0,
    graph_view,
    outer_size_mm,
)

_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}


def _pipe(element_id, params):
    return {"element_id": element_id, "category": "OST_PipeCurves",
            "type_id": "T1", "type_name": "Труба", "level_id": None,
            "host_id": None, "params": params}


class NominalNeverStandsInForOuter(unittest.TestCase):
    """ОПРОВЕРГАЮЩИЙ СЛУЧАЙ: один номинал — два наружных."""

    def test_the_same_nominal_carries_two_different_outers(self) -> None:
        """Замер `snowdon_plumb_v4`: 50.8 -> 60.325 (1 835 труб) И
        50.8 -> 53.975 (530 труб). Никакая таблица по номиналу их не
        различит — наружный есть функция ТИПА."""
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_DIAMETER_PARAM": 50.8,
                         "RBS_PIPE_OUTER_DIAMETER": 60.325}),
            _pipe("P2", {"RBS_PIPE_DIAMETER_PARAM": 50.8,
                         "RBS_PIPE_OUTER_DIAMETER": 53.975})])
        self.assertEqual(outer_size_mm(graph.node("P1"))[0], 60.325)
        self.assertEqual(outer_size_mm(graph.node("P2"))[0], 53.975)
        self.assertEqual(graph.node("P1").section["RBS_PIPE_DIAMETER_PARAM"],
                         graph.node("P2").section["RBS_PIPE_DIAMETER_PARAM"])

    def test_nominal_alone_yields_None_not_a_substitute(self) -> None:
        """Подставить номинал значило бы объявить телом ИМЯ типоразмера и
        занизить тело на 9.525 мм — в опасную сторону: клеш не найдётся."""
        graph = graph_from_l0(
            _HEADER, [_pipe("P1", {"RBS_PIPE_DIAMETER_PARAM": 50.8})])
        self.assertIsNone(outer_size_mm(graph.node("P1")))

    def test_the_measured_source_rides_with_the_value(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_OUTER_DIAMETER": 60.325})])
        value, source = outer_size_mm(graph.node("P1"))
        self.assertEqual(source, "RBS_PIPE_OUTER_DIAMETER")
        self.assertEqual(value, 60.325)

    def test_conduits_are_covered_too(self) -> None:
        """`snowdon_elec_v1`: 530 коробов несут наружный. Категорию, которую
        никто не называл, закрывает тот же закрытый список."""
        row = _pipe("C1", {"RBS_CONDUIT_OUTER_DIAM_PARAM": 55.8038})
        row["category"] = "OST_Conduit"
        graph = graph_from_l0(_HEADER, [row])
        self.assertEqual(outer_size_mm(graph.node("C1"))[1],
                         "RBS_CONDUIT_OUTER_DIAM_PARAM")


class SectionComesFromOneClosedList(unittest.TestCase):
    """Два словаря на один факт расходятся — список берётся у чтения."""

    def test_the_list_is_the_extractor_list_not_a_copy(self) -> None:
        from kukai.ir.decompile.extract import SECTION_PARAM_NAMES
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {name: 1.0 for name in SECTION_PARAM_NAMES})])
        self.assertEqual(set(graph.node("P1").section),
                         set(SECTION_PARAM_NAMES))

    def test_unlisted_params_do_not_leak_into_section(self) -> None:
        graph = graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_OUTER_DIAMETER": 60.325,
                         "SOME_OTHER_PARAM": 7.0})])
        self.assertNotIn("SOME_OTHER_PARAM", graph.node("P1").section)

    def test_absent_section_is_empty_not_zero(self) -> None:
        graph = graph_from_l0(_HEADER, [_pipe("P1", {})])
        self.assertEqual(dict(graph.node("P1").section), {})
        self.assertIsNone(outer_size_mm(graph.node("P1")))


class ViewerReadsStateNotHulls(unittest.TestCase):
    """Вьюер читал ОБОЛОЧКИ: на `демо-v3` 99.89 % из них габаритные ящики, а
    38.24 % вырождены. Проекция отвечает на вопрос «что это за узел»."""

    def _graph(self):
        return graph_from_l0(_HEADER, [
            _pipe("P1", {"RBS_PIPE_OUTER_DIAMETER": 60.325}),
            _pipe("P2", {})])

    def test_projection_carries_both_honesty_axes(self) -> None:
        view = graph_view(self._graph())
        self.assertEqual(view.authority, {"declared": 2})
        self.assertEqual(view.existence, {Existence.MATERIALIZED.value: 2})
        for node in view.nodes:
            self.assertTrue(node.authority_source,
                            "ось без свидетеля не читается")

    def test_projection_carries_no_body_geometry(self) -> None:
        """Граница ответственности: проекция НЕ рисует. Офлайн-3D показывает
        объявленное; выведенное Revit офлайн не существует, и рисовать его
        тем же телом значило бы подписать непрочитанную ось."""
        node = graph_view(self._graph()).nodes[0]
        for banned in ("bbox", "hull", "solid", "mesh", "vertices"):
            self.assertFalse(hasattr(node, banned))

    def test_without_l1_distinguishes_not_asked_from_none(self) -> None:
        """`None` значит «не спрашивали», пустой кортеж — «спросили, таких
        нет». Тот же закон, что у `hosted` в клешах."""
        graph = self._graph()
        self.assertIsNone(graph_view(graph).without_l1)
        self.assertEqual(graph_view(graph, l1_source_ids=["P1", "P2"]).without_l1,
                         ())
        self.assertEqual(graph_view(graph, l1_source_ids=["P1"]).without_l1,
                         ("P2",))

    def test_census_and_honesty_counters_ride_in_the_projection(self) -> None:
        view = graph_view(self._graph())
        self.assertEqual(view.census_rows, 2)
        self.assertEqual(dict(view.census_refusals), {})
        self.assertEqual(dict(view.unresolved_by_reason), {})
        self.assertEqual(dict(view.refuted_by_rule), {})

    def test_unresolved_reasons_reach_the_viewer_named(self) -> None:
        graph = graph_from_l0(
            _HEADER,
            [{"element_id": "F1", "category": "OST_ElectricalFixtures",
              "type_id": "t", "type_name": "T", "level_id": None,
              "host_id": "LNK-1", "params": {}}])
        view = graph_view(graph)
        self.assertEqual(sum(view.unresolved_by_reason.values()), 1)
        self.assertNotIn("unnamed", view.unresolved_by_reason)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
