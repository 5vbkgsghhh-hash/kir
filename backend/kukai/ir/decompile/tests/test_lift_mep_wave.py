# -*- coding: utf-8 -*-
"""Обратный ход волны ЭОМ/гибких/заготовок (09.08.2026).

За одно утро в реестр приехали пять операций MEP: `create_conduit`,
`create_pipe_placeholder`, `create_duct_placeholder`, `create_flex_duct`,
`create_flex_pipe`. Прямое направление выросло, обратное — нет, и это
НОРМАЛЬНО ровно до тех пор, пока разрыв НАЗВАН. Здесь он назван и закреплён,
потому что каждая из трёх ситуаций врёт по-своему, если её не сторожить.

1. КОРОБ ПОДНИМАЕТСЯ. Строка L0 короба неотличима по форме от лотка, лифтер
   написан той же волной — и его единственный тест до сегодня жил в манифесте
   (`test_reverse_contract`), то есть проверял ОБЕЩАНИЕ, а не подъём.

2. ГИБКИЙ УЧАСТОК ОТКАЗЫВАЕТ ПО ВЕРНОМУ ИМЕНИ. До этой волны обе категории
   получали `no_lifter` — «операции под это нет», — и это было правдой ровно
   до утра 09.08. Теперь правда лежит на ступень раньше: оп есть, а формы его
   в захвате нет. Разница не косметическая: `no_lifter` посылает следующего в
   реестр операций, `source_contract_gap` — в ЧТЕНИЕ.

3. ЗАГОТОВКА СЕГОДНЯ ПОДНИМАЕТСЯ КАК НАСТОЯЩАЯ ТРУБА, И ЭТО НАДО ДЕРЖАТЬ НА
   ВИДУ. Единственный признак заготовки — бит `IsPlaceholder`, которого в
   строке L0 нет; отличить её нечем ПО ПОСТРОЕНИЮ. Значит круг честно
   пересобирает НЕ заготовку, а полноценный участок, и это следствие
   объявлено в манифесте словами. Тест ниже требует, чтобы объявление и
   поведение не разъехались молча: пока бита нет, обещать `capture_gap`
   обязаны обе стороны сразу.
"""
from __future__ import annotations

import unittest
from dataclasses import fields

from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import (
    _CANDIDATES,
    _OPS_WITHOUT_L0_INPUTS,
    lift_document_detailed,
)
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    LocationCurveKind,
    ProjectInfo,
)
from kukai.ir.reverse_contract import REVERSE_CONTRACTS, ReverseMode


def _run(eid, category, *, curve_kind=None, params=None):
    """Линейный участок MEP ровно в той форме, какой его отдаёт эмиссия."""

    return L0Element(
        element_id=eid, category=category, category_ru="",
        type_id="7001", type_name="Тип 100",
        level_id="10", level_name="Этаж 1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 3000.0), p1_mm=(6000.0, 0.0, 3000.0),
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=None, params=params or {}, curve_kind=curve_kind)


def _doc(*elements):
    return L0Document(
        doc_name="mep", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "Этаж 1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


def _lift(*elements):
    result = lift_document_detailed(_doc(*elements))
    return ({node["source_element_id"]: node for node in result.nodes},
            {item.source_element_id: item for item in result.diagnostics})


class ConduitActuallyLifts(unittest.TestCase):
    """Обещание манифеста, проверенное подъёмом, а не чтением манифеста."""

    def test_a_straight_conduit_becomes_create_conduit(self):
        nodes, diagnostics = _lift(_run("101", "OST_Conduit"))
        self.assertEqual(diagnostics, {})
        node = nodes["101"]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_conduit")
        self.assertEqual(node["params"]["p0_mm"], [0.0, 0.0, 3000.0])
        self.assertEqual(node["params"]["p1_mm"], [6000.0, 0.0, 3000.0])
        self.assertEqual(
            node["params"]["level"],
            {"by": "name", "value": "Этаж 1", "_id": "10"})
        self.assertEqual(node["params"]["conduit_type"]["by"], "name")

    def test_the_diameter_is_deliberately_absent(self):
        """Номинал короба — торговый размер типа, и прямой оп его не берёт.

        Поднять число, которого обратно не построить, значило бы выдать
        невыполнимую программу за замкнутый круг.
        """

        nodes, _ = _lift(_run("101", "OST_Conduit",
                              params={"RBS_CONDUIT_DIAMETER_PARAM": 50.0}))
        self.assertNotIn("diameter_mm", nodes["101"]["params"])

    def test_a_non_line_conduit_stays_an_honest_atom(self):
        """ОПРОВЕРГАЮЩИЙ: хорда вместо дуги прошла бы verify как exact."""

        nodes, diagnostics = _lift(
            _run("102", "OST_Conduit", curve_kind=LocationCurveKind.ARC))
        self.assertEqual(nodes["102"]["kind"], "atom")
        self.assertIs(
            diagnostics["102"].reason, AtomReason.CURVE_KIND_UNSUPPORTED)


class FlexRunsRefuseByTheirOwnName(unittest.TestCase):
    """Оп ЕСТЬ, формы его в захвате НЕТ — и отказ обязан сказать именно это."""

    CATEGORIES = {
        "OST_FlexDuctCurves": ("create_flex_duct", "FlexDuct.Points"),
        "OST_FlexPipeCurves": ("create_flex_pipe", "FlexPipe.Points"),
    }

    def test_each_flex_category_names_its_own_op_and_the_missing_member(self):
        for index, (category, (op_name, _member)) in enumerate(
                sorted(self.CATEGORIES.items())):
            with self.subTest(category=category):
                nodes, diagnostics = _lift(_run(str(200 + index), category))
                node = nodes[str(200 + index)]
                self.assertEqual(node["kind"], "atom")
                self.assertIs(
                    diagnostics[str(200 + index)].reason,
                    AtomReason.SOURCE_CONTRACT_GAP,
                    "no_lifter послал бы писать операцию, которая написана")
                detail = node["reason"]["detail"]
                self.assertIn(op_name, detail)
                self.assertIn("path", detail)
                self.assertIn("FlexDuct.Points", detail)

    def test_the_partial_gap_does_not_claim_a_total_one(self):
        """Первый ЧАСТИЧНЫЙ разрыв захвата: `level` мы несём, `path` — нет.

        Прежняя формулировка отказа утверждала «НИ ОДНОГО из обязательных
        входов». На гибком участке это ложь, и ложь именно в том утверждении,
        ради точности которого весь этот код заведён.
        """

        nodes, _ = _lift(_run("201", "OST_FlexDuctCurves"))
        detail = nodes["201"]["reason"]["detail"]
        self.assertNotIn("НИ ОДНОГО", detail)
        self.assertIn("1 из 2", detail)
        self.assertIn("level", detail)

    def test_endpoints_alone_never_become_a_straight_flex_run(self):
        """ОПРОВЕРГАЮЩИЙ: подмена сплайна прямой — выдуманная геометрия.

        Строка у гибкого участка ТА ЖЕ, что у жёсткого: пара концов. Если
        когда-нибудь появится лифтер, строящий по ним прямой участок, любая
        ломаная с теми же концами будет от него неотличима — и упадёт здесь.
        """

        for category in sorted(self.CATEGORIES):
            with self.subTest(category=category):
                self.assertNotIn(category, _CANDIDATES)
                self.assertIn(category, _OPS_WITHOUT_L0_INPUTS)
        for op_name, _member in self.CATEGORIES.values():
            contract = REVERSE_CONTRACTS[op_name]
            with self.subTest(op=op_name):
                self.assertIs(contract.mode, ReverseMode.CAPTURE_GAP)
                self.assertEqual(
                    contract.representation_ops, (),
                    "прямой участок между концами гибкой подводки — не её "
                    "представление, а другая труба")


class APlaceholderRebuildsAsARealRun(unittest.TestCase):
    """Следствие, объявленное словами, закреплено поведением.

    Это НЕ проверка того, что мы хорошо поступаем, — мы поступаем плохо и
    знаем об этом. Тест держит объявление и поведение сцепленными: пока бита
    `IsPlaceholder` в захвате нет, обе стороны обязаны говорить одно и то же.
    """

    PAIRS = (
        ("OST_PipeCurves", "create_pipe", "create_pipe_placeholder",
         "RBS_PIPE_DIAMETER_PARAM"),
        ("OST_DuctCurves", "create_duct", "create_duct_placeholder",
         "RBS_CURVE_DIAMETER_PARAM"),
    )

    def test_l0_carries_no_bit_that_could_tell_them_apart(self):
        """Проверяется СТРУКТУРНО, по полям строки, а не списком строк."""

        field_names = {field.name for field in fields(L0Element)}
        carriers = sorted(
            name for name in field_names
            if "placeholder" in name.lower() or "flex" in name.lower())
        self.assertEqual(
            carriers, [],
            "в L0Element появилось поле про заготовку: объявленный "
            "capture_gap про IsPlaceholder больше не верен")

    def test_a_run_lifts_as_the_real_op_because_nothing_says_otherwise(self):
        """Заготовка и настоящий участок дают ОДИН И ТОТ ЖЕ узел L1."""

        for category, real_op, _placeholder_op, diameter in self.PAIRS:
            with self.subTest(category=category):
                nodes, diagnostics = _lift(
                    _run("300", category, params={diameter: 100.0}))
                self.assertEqual(diagnostics, {})
                self.assertEqual(nodes["300"]["op_name"], real_op)

    def test_the_declaration_names_the_consequence_out_loud(self):
        for _category, real_op, placeholder_op, _diameter in self.PAIRS:
            contract = REVERSE_CONTRACTS[placeholder_op]
            with self.subTest(op=placeholder_op):
                self.assertIs(contract.mode, ReverseMode.CAPTURE_GAP)
                self.assertIn("IsPlaceholder", contract.reason)
                self.assertEqual(contract.representation_ops, (real_op,))
                self.assertIn(real_op, contract.limitation)
                self.assertIn("REAL", contract.limitation)


if __name__ == "__main__":
    unittest.main()
