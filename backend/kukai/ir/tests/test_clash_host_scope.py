"""ГРАНИЦА ИЗВЛЕЧЕНИЯ — НЕ ОШИБКА АВТОРА (волна 11.08.2026).

Продолжение `test_clash_wiring.py`. Отдельный файл, потому что предмет здесь
один и узкий: висячее ребро хозяина, у которого ДВА разных значения в
зависимости от того, ЧЬИ это слова.

КАЖДЫЙ ТЕСТ ЗДЕСЬ ПАДАЛ ДО ПРАВКИ.
"""
from __future__ import annotations

import unittest

from kukai.clash import hulls as H
from kukai.clash import snapshot as S
from kukai.ir import clash_bundle
from kukai.ir import clash_judgement as J


def _finding(a_id, b_id, la="door", lb="wall", rel="overlap",
             grade="conservative", depth=120.0, sa="profile", sb="profile"):
    return {
        "finding_id": f"{a_id}~{b_id}",
        "a": {"source_element_id": a_id, "label": la,
              "category": "OST_Doors", "hull_source": sa},
        "b": {"source_element_id": b_id, "label": lb,
              "category": "OST_Walls", "hull_source": sb},
        "hull_relation": rel, "hull_grade": grade,
        "hull_overlap_depth_mm": depth, "ranking_tol_mm": 1.0,
        "pair_kind": "physical",
    }


class TheBoundaryOfExtractionIsNotAnAuthorsError(unittest.TestCase):
    """ВИСЯЧИЙ ХОЗЯИН — ДВА РАЗНЫХ ФАКТА, И ОДИН ИЗ НИХ НЕ ПРО АВТОРА.

    ЗАМЕР ПО ВСЕМУ КОРПУСУ (11.08.2026, `/tmp/wiring/m_dangling.py`: 67
    снимков, 1 139 477 элементов, 213 811 рёбер `host_id`). Висячих ссылок
    1 263 — 0.6% на весь корпус, но они СОСРЕДОТОЧЕНЫ, а не размазаны:

        snowdon_elec_v1        959 из 1 001    (95.8%)
        snowdon_plumb_v1..v4    50..54 из 50..54 (100%)
        snowdon_plumb_v5        86 из 2 860    (3.0%)
        sob62_r23_v2..v6         1 из 187..189 (0.5%)
        остальные 41 снимок с рёбрами         (0%)

    ЧЕМ ОНИ ЯВЛЯЮТСЯ НА САМОМ ДЕЛЕ (`/tmp/wiring/m_elec.py`):

      * 1 010 указывают в ЗАПИСЬ `link` файла L0 — хозяин лежит в СВЯЗАННОМ
        файле. У `snowdon_elec_v1` все 959 ведут в ТРИ разных
        `RevitLinkInstance` (`1362762` x812, `1362428` x110, `1484390` x37), а
        владельцы — светильники, щиты и приборы: OST_ElectricalFixtures 497,
        OST_LightingDevices 187, OST_ElectricalEquipment 165;
      * 86 (`snowdon_plumb_v5`) указывают в `ReferencePlane` — датум, который
        `hulls.KIND_TABLE` телом не считает В ПРИНЦИПЕ. Хозяин не «потерялся»:
        он НИКОГДА не мог стать оболочкой.

    Ни одно из двух не есть ошибка автора: и то и другое — ГРАНИЦА НАШЕГО
    ИЗВЛЕЧЕНИЯ. Свернуть их в `contradicts` («автор назвал не того») значит
    обвинить автора 959 раз подряд в том, чего он не делал. Это тот же класс
    дефекта, что закрыт вчера, только с обратным знаком: там прибор молчал
    похоже на чисто, здесь ГРАНИЦА ПРИБОРА ВЫГЛЯДИТ ОШИБКОЙ АВТОРА.

    РАЗЛИЧАЕТ ИХ ИСТОЧНИК, А НЕ ДОГАДКА. `program_host_ref` — слова САМОЙ
    программы, и там несуществующая ссылка ДЕЙСТВИТЕЛЬНО чинится автором
    (`KIR-V002` запрещает ссылку через границу программы). `l0_host_id` —
    слова РАЗБОРА, и там ненайденный хозяин говорит лишь о том, что мы его не
    извлекли.
    """

    def test_an_L0_host_never_extracted_is_not_blamed_on_the_author(self):
        hosted = {"1516314": {"host_element_id": None,
                              "host_ref": "1362762",
                              "host_class": None,
                              "source": "l0_host_id"}}
        row = J.judge([_finding("1516314", "1516399")], hosted=hosted).judged[0]
        self.assertEqual(row.host_state, "host_out_of_scope")
        self.assertNotEqual(row.host_state, "contradicts")
        self.assertEqual(row.declared_host_id, "1362762")

    def test_a_program_ref_that_does_not_exist_IS_the_authors_fault(self):
        ops = {"p1/d": {"op": "create_door", "id": "d",
                        "host": {"by": "ref", "value": "нет-такой-стены"}}}
        hosted = J.hosted_from_ops(ops)
        self.assertEqual(hosted["p1/d"]["source"], "program_host_ref")
        self.assertEqual(J.host_relation("p1/d", "p1/w", hosted)[0],
                         "contradicts")

    def test_out_of_scope_still_does_NOT_acquit(self):
        """Граница извлечения — НЕ оправдание. Живёт ли элемент внутри второй
        стороны, мы не знаем; «не знаем» и «живёт» — разные ответы, и ступень
        обязана остаться той же, что у пары без хозяина вовсе."""
        hosted = {"a": {"host_element_id": None, "host_ref": "1362762",
                        "source": "l0_host_id"}}
        row = J.judge([_finding("a", "b")], hosted=hosted).judged[0]
        self.assertNotEqual(row.rule_id, "host_declared")
        self.assertEqual(
            row.rung, J.judge([_finding("a", "b")], hosted={}).judged[0].rung)

    def test_the_text_names_the_boundary_and_never_the_author(self):
        hosted = {"a": {"host_element_id": None, "host_ref": "1362762",
                        "source": "l0_host_id"}}
        text = J.judge([_finding("a", "b")], hosted=hosted).judged[0].text_ru
        self.assertIn("1362762", text)
        self.assertNotIn("автор назвал хозяином", text)
        self.assertIn("ИЗВЛЕЧ", text.upper())

    def test_a_resolvable_L0_host_elsewhere_is_STILL_contradicts(self):
        """Граница извлечения — ТОЛЬКО про ненайденного хозяина. Когда хозяин
        найден и это другой элемент, факт остаётся фактом: замер 10.08 — 587
        из 588 таких пар на `sob62_r23_v5` и 8 728 из 8 728 на
        `sob62_fas_r23_v19` имеют хозяина С ТЕЛОМ, то есть проверяемого."""
        hosted = {"10324348": {"host_element_id": "9857641",
                               "host_class": "Wall", "source": "l0_host_id"}}
        row = J.judge([_finding("10324348", "13109052")],
                      hosted=hosted).judged[0]
        self.assertEqual(row.host_state, "contradicts")

    def test_an_unknown_source_is_extraction_not_authorship(self):
        """Обвинять автора можно ТОЛЬКО по его собственным словам. Источник, о
        котором мы ничего не знаем, — не его слова."""
        hosted = {"a": {"host_element_id": None, "host_ref": "zzz",
                        "source": "какой-то-будущий-индекс"}}
        row = J.judge([_finding("a", "b")], hosted=hosted).judged[0]
        self.assertEqual(row.host_state, "host_out_of_scope")

    def test_the_state_list_stays_closed_and_counted(self):
        self.assertEqual(set(J.HOST_STATES),
                         {"confirms", "contradicts", "host_out_of_scope",
                          "absent", "unknown"})
        hosted = {"a": {"host_element_id": None, "host_ref": "x",
                        "source": "l0_host_id"},
                  "c": {"host_element_id": "zzz", "source": "l0_host_id"}}
        out = J.judge([_finding("a", "b"), _finding("c", "d"),
                       _finding("e", "f")], hosted=hosted)
        self.assertEqual(out.by_host_state,
                         {"absent": 1, "contradicts": 1,
                          "host_out_of_scope": 1})
        self.assertEqual(sum(out.by_host_state.values()), len(out.judged))
        for state in out.by_host_state:
            self.assertIn(state, J.HOST_STATES)


class TheWallCensusAsksTheTableInsteadOfAsserting(unittest.TestCase):
    """`_wall_geometry` ЗАЯВЛЯЛ строкой, что оболочки у стены нет
    (`wall_prism_refused_by_containment_gate`), НИ РАЗУ не спросив таблицу,
    которая это решает.

    ЗАМЕР 11.08.2026 (`/tmp/wiring/m_wall.py`): сегодня заявление ВЕРНО —
    `hulls.KIND_TABLE["OST_Walls"].sources == ("bbox",)`, и `build_hull` на
    ПОЛНОЙ призме (`width_mm` 200, `uniform` True, без блокеров) возвращает
    `None` с причиной «нет ни контура, ни сечения, ни габаритного бокса».
    Замок закрыт, и мой вчерашний доклад о том, что он открылся, был ОШИБКОЙ
    ВЫВОДА: `hulls.hull_from_wall_axis` в дереве есть, но `KIND_TABLE` его
    стенам не разрешает.

    Дефект поэтому не в числе, а в СПОСОБЕ: константа одного модуля
    утверждает содержимое таблицы другого, ни разу её не прочитав. В день,
    когда `prism` появится в `sources`, стена получит тело — а перепись
    `clash_bundle` продолжит считать её «без геометрии», и квитанция скажет
    «НЕ ВИДЕЛИ» про элемент, который видели. Лечится это не новым числом, а
    ВОПРОСОМ к той таблице, которая решает.
    """

    def _wall_op(self):
        return {"op": "create_wall", "id": "w1",
                "type": {"by": "name", "value": "Стена 200"},
                "level": {"by": "name", "value": "L1"},
                "height_mm": 3000.0,
                "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [4000.0, 0.0, 0.0]}

    def _snapshot(self):
        return {"levels": [{"id": "lv1", "name": "L1", "elevation_mm": 0.0}],
                "wall_types": [{"id": "wt1", "name": "Стена 200",
                                "section": {"kind": "plate",
                                            "thickness_mm": 200.0,
                                            "uniform": True, "blockers": [],
                                            "source": "type"}}]}

    def _geometry(self):
        return clash_bundle.bundle_elements([{"ops": [self._wall_op()]}],
                                            snapshot=self._snapshot())

    def test_the_numbers_are_still_collected(self):
        """Правка не имеет права трогать СБОР чисел: призма собирается ровно
        как собиралась, меняется только то, что об этом говорится."""
        el = self._geometry().elements[0]
        self.assertIn("prism", el)
        self.assertEqual(el["prism"]["width_mm"], 200.0)
        self.assertEqual((el["z0_mm"], el["z1_mm"]), (0.0, 3000.0))

    def test_the_blame_matches_what_the_table_actually_allows(self):
        geo = self._geometry()
        blamed = "wall_prism_refused_by_containment_gate" in geo.no_geometry
        allowed = "prism" in (H.KIND_TABLE["OST_Walls"].sources or ())
        self.assertEqual(blamed, not allowed)

    def test_a_wall_is_never_both_hulled_and_counted_as_bodiless(self):
        """ЗАМОК ОТ РАСХОЖДЕНИЯ. Элемент, попавший в тела, не имеет права
        одновременно стоять в переписи «без геометрии»: квитанция считает
        `without_body` по первому, а ПРИЧИНУ печатает по второй."""
        geo = self._geometry()
        snap = S.build_from_elements(geo.elements, origin={"source": "t"},
                                     profiles=geo.profiles)
        hulled = len(snap.records) > 0
        blamed = sum(geo.no_geometry.values()) > 0
        self.assertNotEqual(
            hulled, blamed, "стена одновременно с телом и без геометрии")

    def test_a_wall_the_snapshot_cannot_type_names_its_own_reason(self):
        """Отказ ДО призмы не подменяется: «типа нет в снапшоте» и «таблица
        призму не берёт» — разные починки, и разными обязаны остаться."""
        geo = clash_bundle.bundle_elements(
            [{"ops": [self._wall_op()]}],
            snapshot={"levels": [{"id": "lv1", "name": "L1",
                                  "elevation_mm": 0.0}], "wall_types": []})
        self.assertIn("wall_type_not_in_snapshot", geo.no_geometry)
        self.assertNotIn("prism", geo.elements[0])


if __name__ == "__main__":
    unittest.main()
