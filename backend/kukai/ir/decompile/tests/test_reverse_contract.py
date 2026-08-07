"""Executable coverage contract between the KIR forward and reverse axes."""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
import unittest
from collections import Counter

from kukai.ir import spec
from kukai.ir.decompile import lift, materialize
from kukai.ir.reverse_contract import (
    REVERSE_CONTRACTS,
    REVERSE_CONTRACT_SCHEMA,
    ReverseContractError,
    ReverseMode,
    assert_composed_emission,
    assert_lift_emission,
    reverse_contract_report,
)


class ReverseContractTests(unittest.TestCase):
    def test_manifest_is_exhaustive_over_live_write_registry(self):
        write_ops = {
            name for name, op_spec in spec.OPS.items()
            if op_spec.family in spec.WRITE_FAMILIES
        }
        self.assertEqual(set(REVERSE_CONTRACTS), write_ops)
        # 35 -> 37 (03.08.2026): +create_room_separator (волна разделителей)
        # и +create_opening (волна проёмов). Число здесь — ЗАМОК, а не
        # статистика: манифест обязан расти вместе с реестром, а не молча
        # отставать от него.
        self.assertEqual(len(REVERSE_CONTRACTS), 37)
        # 23 -> 24 (03.08.2026): create_railing переведён из capture_gap в
        # direct. Захват путей ограждений едет с 29.07, и k2_ar_rd_v9 несёт
        # 31 строку захвата — прежняя формулировка «L0 has neither a railing
        # path nor …» перестала быть правдой. Число здесь и есть тот замок,
        # который не даёт манифесту протухнуть молча.
        self.assertEqual(
            sum(contract.direct_same_op_lift
                for contract in REVERSE_CONTRACTS.values()),
            25,
        )
        with self.assertRaises(TypeError):
            REVERSE_CONTRACTS["delete"] = REVERSE_CONTRACTS["create_wall"]  # type: ignore[index]

    def test_every_category_candidate_is_direct_or_an_explicit_capture_gap(self):
        for category, candidate in lift._CANDIDATES.items():
            with self.subTest(category=category, op=candidate.op):
                contract = REVERSE_CONTRACTS[candidate.op]
                self.assertIn(
                    contract.mode,
                    (ReverseMode.DIRECT, ReverseMode.CAPTURE_GAP),
                )
                if contract.mode is ReverseMode.DIRECT:
                    self.assertIn(candidate.lifter_name, contract.entrypoints)

    def test_every_declared_direct_entrypoint_exists_and_names_the_emitted_op(self):
        for op_name, contract in REVERSE_CONTRACTS.items():
            if contract.mode is not ReverseMode.DIRECT:
                continue
            for entrypoint in contract.entrypoints:
                with self.subTest(op=op_name, entrypoint=entrypoint):
                    function = getattr(lift, entrypoint)
                    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
                    string_literals = {
                        node.value
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Constant)
                        and isinstance(node.value, str)
                    }
                    self.assertIn(op_name, string_literals)

    def test_l1_emission_guard_refuses_non_direct_operations(self):
        self.assertEqual(assert_lift_emission("create_wall").op_name,
                         "create_wall")
        # create_railing уехал отсюда 03.08 вместе с подключением захвата;
        # на его месте — create_dimension, последний оставшийся capture_gap
        # (вида-владельца и Dimension.References чтение не снимает).
        for op_name in ("create_dimension", "delete", "load_family"):
            with self.subTest(op=op_name), self.assertRaises(
                    ReverseContractError):
                assert_lift_emission(op_name)

    def test_composed_group_emission_has_a_checked_entrypoint(self):
        contract = assert_composed_emission("create_group")
        self.assertEqual(contract.entrypoints, ("component_to_group_program",))
        self.assertTrue(callable(getattr(materialize, contract.entrypoints[0])))
        for op_name in ("create_wall", "delete", "load_family"):
            with self.subTest(op=op_name), self.assertRaises(
                    ReverseContractError):
                assert_composed_emission(op_name)

    def test_report_is_stable_json_and_exposes_honest_modes(self):
        report = reverse_contract_report()
        self.assertEqual(report["schema"], REVERSE_CONTRACT_SCHEMA)
        self.assertEqual(report["write_ops"], 37)
        self.assertEqual(report["direct_same_op_lifts"], 25)
        self.assertEqual(
            report["modes"],
            {
                "direct": 25,
                # 1 -> 2: create_opening объявлен capture_gap честно — L0 1.0
                # не несёт ни Opening.Host, ни границы проёма, и DIRECT здесь
                # обещал бы подъём, которого нет.
                "capture_gap": 2,
                "decomposed": 3,
                "composed": 1,
                "state_transition": 4,
                "pinned_existing": 1,
                "external_source": 1,
            },
        )
        self.assertEqual(
            [row["op"] for row in report["contracts"]],
            sorted(REVERSE_CONTRACTS),
        )
        self.assertEqual(
            json.dumps(report, ensure_ascii=False, sort_keys=True),
            json.dumps(reverse_contract_report(), ensure_ascii=False,
                       sort_keys=True),
        )
        self.assertEqual(
            Counter(row["mode"] for row in report["contracts"]),
            Counter(report["modes"]),
        )


if __name__ == "__main__":
    unittest.main()
