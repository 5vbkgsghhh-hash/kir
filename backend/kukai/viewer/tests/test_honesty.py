"""Слой честности. Главный тест здесь — РЕГРЕССИЯ НА ДЕФЕКТ ПРИБОРА.

Первый замер соединения оболочек с узлами L1 (10.08.2026) дал 32.7–37.9 %
«оболочек без узла» и выглядел фактом о зданиях. Это был дефект ОБХОДА:
`atom_cluster` / `row` / `grid_array` держат схлопнутые атомы в `members`, а
не в `children`, и у самого кластера `payload` пуст. После правки обхода —
0 из 120 242 на трёх зданиях.

Прибор, покрывающий часть своего диапазона, хуже отсутствующего; поэтому
именно на этот класс ошибки стоит опровергающий тест, падающий на старом коде.
"""

import unittest

from kukai.viewer import honesty as H


class ClusterMembersAreVisible(unittest.TestCase):

    def test_atoms_inside_a_cluster_are_not_lost(self):
        """Опровергающий тест дефекта 10.08: обход по одним `children`
        возвращал бы ОДИН узел вместо трёх и объявлял бы два элемента
        «без узла L1»."""
        tree = {
            "kind": "building",
            "children": [
                {"kind": "op", "payload": {"kind": "op", "op_name": "create_wall",
                                           "source_element_id": "1"}},
                {"kind": "atom_cluster", "payload": {}, "members": [
                    {"kind": "atom", "source_element_id": "2",
                     "reason": {"code": "generator_child"}},
                    {"kind": "atom", "source_element_id": "3",
                     "reason": {"code": "missing_geometry"}},
                ]},
            ],
        }
        found = {p["source_element_id"] for p in H.iter_l1_nodes(tree)}
        self.assertEqual(found, {"1", "2", "3"})

    def test_members_and_children_are_both_walked_at_any_depth(self):
        tree = {"kind": "building", "children": [
            {"kind": "floor", "children": [
                {"kind": "row", "payload": {}, "members": [
                    {"kind": "atom", "source_element_id": "deep",
                     "reason": {"code": "no_lifter"}}]}]}]}
        self.assertEqual([p["source_element_id"] for p in H.iter_l1_nodes(tree)],
                         ["deep"])

    def test_nodes_without_an_element_address_are_skipped_silently_but_totally(self):
        """Узел без адреса соединить не с чем — но и выдумывать ему адрес
        нельзя. Он просто не участвует, и перепись это увидит как разницу
        между числом узлов и числом оболочек."""
        tree = {"kind": "building", "payload": {"kind": "op"}, "children": []}
        self.assertEqual(list(H.iter_l1_nodes(tree)), [])


class FidelityIsChosenByEvidence(unittest.TestCase):

    def test_degeneracy_outranks_grade(self):
        """Габарит нулевого объёма остаётся `coarse` по таблице грейдов, но
        телом не является вообще. Нарисовать его ящиком значило бы придумать
        ему толщину — а таких 38.2 % на демо-v3."""
        self.assertIs(H.fidelity_of("coarse", "bbox", "aabb_plane"),
                      H.Fidelity.DEGENERATE)
        self.assertIs(H.fidelity_of("conservative", "profile", "aabb_point"),
                      H.Fidelity.DEGENERATE)

    def test_bbox_is_box_only_and_never_shaped(self):
        """99.89 % демо-v3 — габариты. Показать их формой значило бы соврать
        именно про то, чего мы не знаем."""
        self.assertIs(H.fidelity_of("coarse", "bbox", "ok"),
                      H.Fidelity.BOX_ONLY)

    def test_every_conservative_source_is_shaped(self):
        for source in ("profile", "prism", "axis_section"):
            self.assertIs(H.fidelity_of("conservative", source, "ok"),
                          H.Fidelity.SHAPED, source)


class CensusMustBalance(unittest.TestCase):

    def test_totals_agree_across_both_axes(self):
        """Перепись, не сходящаяся по одной из осей, делает любой процент на
        экране бездоказательным."""
        census = H.HonestyCensus()
        for i in range(5):
            census.add(H.ElementHonesty(str(i), H.Trust.ATOM,
                                        H.Fidelity.BOX_ONLY, "generator_child"))
        census.add(H.ElementHonesty("x", H.Trust.OP_PROVEN,
                                    H.Fidelity.SHAPED, "create_wall"))
        self.assertTrue(census.balanced())
        self.assertEqual(census.total, 6)
        self.assertEqual(census.by_atom_reason["generator_child"], 5)

    def test_unproven_ops_are_counted_apart_from_atoms(self):
        census = H.HonestyCensus()
        census.add(H.ElementHonesty("a", H.Trust.OP_UNPROVEN,
                                    H.Fidelity.SHAPED, "create_dimension"))
        self.assertEqual(census.by_unproven_op, {"create_dimension": 1})
        self.assertEqual(census.by_atom_reason, {})


class MissingEvidenceIsNeverGreen(unittest.TestCase):

    def test_absent_tree_reports_unavailable_rather_than_empty(self):
        """Отсутствие дерева и дерево без атомов — разные факты. Молчание
        второго читалось бы как «всё поднято»."""
        mapping, note = H.read_l1_honesty("/nonexistent/run")
        self.assertEqual(mapping, {})
        self.assertFalse(note["available"])
        self.assertTrue(note["reason"])

    def test_refutation_is_not_a_trust_state(self):
        """ОТМЕНА МОЕГО СОБСТВЕННОГО СОСТОЯНИЯ. `Trust.CLASH_REFUTED` был
        подменой оси: `Trust` судит ЭЛЕМЕНТ, а опровержение принадлежит
        ОТНОШЕНИЮ (`GraphEdge.refuted_by` обязателен ровно при
        `Modality.REFUTED`). Дверь, чьё ребро с комнатой снято правилом,
        прочитана прекрасно, и красить её как опровергнутую нельзя."""
        self.assertNotIn("clash_refuted", {t.value for t in H.Trust})
        from kukai.viewer import graph as G
        self.assertTrue(G.FLAG_REFUTED)


class AxesKeepThreeStates(unittest.TestCase):
    """Тристейт `serving._unwitnessed_axes`, упакованный в байт.

    `{}` = все три оси объявлены; словарь = по этим осям обязательств нет;
    `None` = судить нечем. **`None` — это НЕ «всё хорошо»**, и двоичная лампа
    слила бы третье состояние с первым, то есть показала бы зелёный там, где
    не смотрели. Ровно тот дефект, ради которого поле и заведено.
    """

    def test_declared_everywhere_is_zero(self):
        self.assertEqual(H.axes_byte({}), 0)

    def test_unjudgeable_is_not_zero(self):
        self.assertEqual(H.axes_byte(None), H.AXES_UNJUDGEABLE)
        self.assertNotEqual(H.AXES_UNJUDGEABLE, 0)

    def test_each_axis_owns_its_bit_in_the_published_order(self):
        for index, axis in enumerate(H.AXES_ORDER):
            self.assertEqual(H.axes_byte({axis: ["какой-то_оп"]}), 1 << index)

    def test_all_three_missing_sets_all_three_bits(self):
        self.assertEqual(
            H.axes_byte({axis: ["оп"] for axis in H.AXES_ORDER}), 7)

    def test_an_unknown_axis_reads_as_unjudgeable_not_as_clean(self):
        """Владелец таблицы обязательств вправе завести четвёртую ось. Ответ
        с осью, которой мы не знаем, обязан стать «судить нечем»: отдать ноль
        значило бы сказать «объявлено всё» про то, чего мы не поняли."""
        self.assertEqual(H.axes_byte({"новая_ось": ["оп"]}),
                         H.AXES_UNJUDGEABLE)

    def test_no_ops_is_unjudgeable_rather_than_clean(self):
        """У элемента без операции нечего спрашивать. `{}` здесь значило бы
        «все обязательства объявлены», то есть похвалу за молчание."""
        self.assertIsNone(H.axes_for_ops([]))

    def test_the_rule_itself_is_not_copied_here(self):
        """Правило живёт в `serving._unwitnessed_axes` и ВЫЗЫВАЕТСЯ. Две копии
        расходятся молча и порознь не падают — тот же довод, по которому в
        `serving._axes_from_violations` копия одна."""
        import inspect
        source = inspect.getsource(H.axes_for_ops)
        self.assertIn("_unwitnessed_axes", source)

    def test_a_wall_declares_all_three_and_a_level_does_not(self):
        """Живой замер таблицы 11.08: `create_wall` объявляет все три оси,
        `create_level` не объявляет семантику и топологию. Если этот тест
        падёт, изменилась таблица обязательств, а не вьюер."""
        self.assertEqual(H.axes_for_ops(["create_wall"]), {})
        missing = H.axes_for_ops(["create_level"])
        self.assertIsNotNone(missing)
        self.assertIn("semantic", missing)


class NoBodyIsItsOwnState(unittest.TestCase):

    def test_it_is_not_the_same_as_a_flat_hull(self):
        """`DEGENERATE` — тело есть и оно плоское; `NO_BODY` — тела нет
        вовсе. Слить их значило бы сказать «построено плоским» про то, что
        не построено."""
        self.assertIn(H.Fidelity.NO_BODY, set(H.Fidelity))
        self.assertNotEqual(H.Fidelity.NO_BODY, H.Fidelity.DEGENERATE)

    def test_fidelity_of_never_invents_it(self):
        """`fidelity_of` судит ПОСТРОЕННУЮ оболочку и потому не вправе
        возвращать `NO_BODY`: отсутствие тела — факт другого модуля."""
        for grade in ("coarse", "conservative", "exact"):
            for source in ("bbox", "profile", "prism", "axis_section"):
                for degen in ("ok", "aabb_plane", "aabb_line", "aabb_point"):
                    self.assertIsNot(H.fidelity_of(grade, source, degen),
                                     H.Fidelity.NO_BODY)
