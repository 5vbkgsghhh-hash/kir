"""Слой графа во вьюере: линия авторитета и «этого в Revit ещё нет».

Главное, что держат эти тесты, — РАЗДЕЛЬНОСТЬ ОСЕЙ. Точность формы,
существование узла и опровергнутость отношения суть три разных факта, и
каждый раз, когда их сливали, получался зелёный экран про непрочитанное.
"""

import os
import unittest

from kukai.viewer import graph as G
from kukai.viewer import honesty as H


class VocabularyIsBorrowedNotCopied(unittest.TestCase):

    def test_codes_cover_the_owner_enums_exactly(self):
        """Словарь у здания один. Своя копия значений `Authority`/`Existence`
        разъехалась бы с графом, и `planned` во вьюере через месяц оказался бы
        не тем `planned`."""
        from kukai.ir.decompile.building_graph import Authority, Existence
        self.assertEqual(set(G.AUTHORITY_CODE) - {"unknown"},
                         {a.value for a in Authority})
        self.assertEqual(set(G.EXISTENCE_CODE) - {"unknown"},
                         {e.value for e in Existence})

    def test_unknown_exists_on_both_axes(self):
        """Сцена без слоя графа обязана говорить «не спрашивали», а не
        выдавать всё за построенное."""
        self.assertIn("unknown", G.AUTHORITY_CODE)
        self.assertIn("unknown", G.EXISTENCE_CODE)

    def test_codes_fit_a_single_byte(self):
        for table in (G.AUTHORITY_CODE, G.EXISTENCE_CODE):
            self.assertTrue(all(0 <= v <= 255 for v in table.values()))

    def test_flags_are_distinct_bits(self):
        self.assertEqual(G.FLAG_REFUTED & G.FLAG_UNRESOLVED, 0)


class RefutationBelongsToTheRelation(unittest.TestCase):
    """ОТМЕНА МОЕГО СОБСТВЕННОГО СОСТОЯНИЯ, записанная тестом.

    У вьюера было `Trust.CLASH_REFUTED`. Оно удалено не потому, что источник
    не появился — появился (`Modality.REFUTED` + `GraphEdge.refuted_by`, живой
    замер `демо-v3`: 5 941 снятое ребро правилом
    `host_does_not_separate_exactly_two_rooms`), — а потому, что это была
    подмена оси: `Trust` судит ЭЛЕМЕНТ, опровержение принадлежит ОТНОШЕНИЮ.
    Дверь, чьё ребро с комнатой снято правилом, прочитана прекрасно.
    """

    def test_trust_no_longer_carries_it(self):
        self.assertNotIn("clash_refuted", {t.value for t in H.Trust})

    def test_the_signal_lives_on_its_own_axis(self):
        self.assertTrue(G.FLAG_REFUTED)

    def test_the_edge_type_requires_a_rule_name(self):
        """Опровержение без имени правила есть то самое молчание: «не нашли»
        становится неотличимо от «не искали». Владелец графа держит это
        типом, и вьюер опирается именно на это."""
        from kukai.ir.decompile.building_graph import (GraphBuildError,
                                                       GraphEdge, Modality,
                                                       Relation)
        with self.assertRaises(GraphBuildError):
            GraphEdge(relation=Relation.HOSTED_IN, src="a", dst="b",
                      modality=Modality.REFUTED)


class TheForeignFlagIsRespected(unittest.TestCase):
    """Флаг `KUKAI_IR_BUILDING_GRAPH` по умолчанию ВЫКЛЮЧЕН, и его владелец
    написал почему: модуль ни разу не сверялся с живым Revit. Показать
    инженеру непроверенные числа как правду — риск ровно того же рода."""

    def test_a_disabled_flag_gives_a_named_absence_not_silence(self):
        previous = os.environ.pop("KUKAI_IR_BUILDING_GRAPH", None)
        try:
            facts, note = G.facts_for_decompile(
                {"doc_name": "проба"}, [], generator_child_ids=(),
                l1_source_ids=())
            self.assertEqual(facts, {})
            self.assertFalse(note["available"])
            self.assertIn("KUKAI_IR_BUILDING_GRAPH", note["reason"])
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_BUILDING_GRAPH"] = previous

    def test_unavailable_still_publishes_every_key(self):
        """Потребитель не обязан знать, была ли причина. Отсутствующий ключ
        читался бы как ноль, а ноль — как «спросили, ничего нет»."""
        note = G.unavailable("нипочему")
        for key in ("authority", "existence", "relations", "refuted_by_rule",
                    "unresolved_by_reason", "without_l1", "nodes"):
            self.assertIn(key, note)
        self.assertIsNone(note["without_l1"])


class PlannedIsAssertedByTheViewerAndSaysSo(unittest.TestCase):
    """Строителя графа ИЗ ПРОГРАММ не существует: `graph_from_l0` единственный
    и ставит всем `MATERIALIZED`. Значит `planned` проставляет вьюер, и это
    обязано быть написано в своде, а не подразумеваться."""

    def test_every_program_element_is_planned(self):
        facts, note = G.facts_for_programs(
            {"p1/w0": {"op": "create_wall"}, "p1/d0": {"op": "create_door"}})
        self.assertEqual({f.existence for f in facts.values()}, {"planned"})
        self.assertEqual(note["existence"], {"planned": 2})

    def test_the_authority_source_is_the_program_op(self):
        facts, _ = G.facts_for_programs({"p1/w0": {"op": "create_wall"}})
        self.assertEqual(facts["p1/w0"].authority_source, "program_op")
        self.assertEqual(facts["p1/w0"].authority, "declared")

    def test_the_viewer_admits_that_it_is_the_one_asserting(self):
        _, note = G.facts_for_programs({"p1/w0": {"op": "create_wall"}})
        self.assertEqual(note["source"], "viewer_asserts_planned")
        self.assertIn("ВЬЮЕР", note["source_ru"])

    def test_what_revit_will_add_beyond_the_declaration_is_named(self):
        """Витражная стена рождает ячейки, панели и импосты; лестница — марши,
        площадки и ограждения. Показать их вьюер не может (число знает только
        Revit), но промолчать значило бы обещать, что на экране всё здание."""
        _, note = G.facts_for_programs({"p1/st": {"op": "create_stairs"}})
        self.assertIn("OST_StairsRuns", note["will_derive"])
        self.assertTrue(note["will_derive_ru"])

    def test_an_op_without_derived_children_adds_nothing(self):
        _, note = G.facts_for_programs({"p1/p0": {"op": "create_pipe"}})
        self.assertEqual(note["will_derive"], {})


class ExistenceIsNotFidelity(unittest.TestCase):
    """Все четыре сочетания осмысленны, и в этом весь смысл двух осей.

    `NO_BODY` — «элемент объявлен, тела мы не знаем».
    `PLANNED` — «элемента в модели ещё нет».
    Тело может быть известно точно, а элемента в Revit не быть: инженер
    написал программу и не нажал кнопку. Слить их значило бы сделать кнопку
    «отправить в Revit» лотереей.
    """

    def test_they_are_carried_by_different_tables(self):
        from kukai.viewer.scene import FIDELITY_CODE
        self.assertIn("no_body", FIDELITY_CODE)
        self.assertNotIn("no_body", G.EXISTENCE_CODE)
        self.assertNotIn("planned", FIDELITY_CODE)

    def test_a_planned_element_can_still_have_a_known_body(self):
        """Живая сцена со снимком типов даёт настоящие тела задуманным
        элементам — замер: тело есть при `existence=planned`."""
        from kukai.viewer import live_scene as L
        snapshot = {
            "levels": [{"id": 1, "name": "L1", "elevation_mm": 0.0}],
            "pipe_types": [{"id": 30, "name": "Сталь",
                            "section": {"kind": "nominal_table",
                                        "source": "PipeSegment.GetSizes",
                                        "sizes": [[100.0, 114.3]]}}]}
        ops = [{"op": "create_pipe", "id": "p0",
                "p0_mm": [0.0, 0.0, 2800.0], "p1_mm": [12000.0, 0.0, 2800.0],
                "diameter_mm": 100.0,
                "pipe_type": {"by": "name", "value": "Сталь"},
                "level": {"by": "name", "value": "L1"}}]
        _, meta = L.scene_from_programs([{"ops": ops}], snapshot=snapshot)
        self.assertEqual(meta["bodies"], 1)
        self.assertEqual(meta["graph"]["existence"], {"planned": 1})
        self.assertEqual(meta["honesty"]["by_fidelity"].get("no_body", 0), 0)


class BothEndsOfARefutedEdgeAreMarked(unittest.TestCase):
    """Опровергнутое отношение касается ОБОИХ концов, и молчать про второй
    нельзя. Замер на `sob62_fas_r23_v19` с включённым флагом: 14 снятых рёбер
    дают 28 помеченных элементов."""

    def test_the_marking_is_derived_from_edges_not_nodes(self):
        import inspect
        source = inspect.getsource(G.facts_for_decompile)
        self.assertIn("graph.edges", source)
        self.assertIn("edge.src", source)
        self.assertIn("edge.dst", source)
