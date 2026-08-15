from __future__ import annotations

import asyncio
from dataclasses import replace

from kukai.ir import spec
from kukai.ir.compiler import plan_program
from kukai.ir.op_contract import (
    OP_CONTRACT_SCHEMA,
    audit_contract_kernel,
    contract_for,
)


WALL = {
    "ir_version": "1.0",
    "ops": [{
        "op": "create_wall",
        "id": "W1",
        "p0_mm": [0, 0],
        "p1_mm": [6000, 0],
        "level": {"by": "element_id", "value": 42},
    }],
}


def test_every_registry_operation_forms_one_canonical_contract() -> None:
    assert audit_contract_kernel() == ()
    contracts = [contract_for(name) for name in sorted(spec.OPS)]
    assert len(contracts) == len(spec.OPS)
    assert len({item.op_name for item in contracts}) == len(spec.OPS)
    assert all(item.to_dict()["schema"] == OP_CONTRACT_SCHEMA
               for item in contracts)


def test_write_contract_carries_lowering_and_witness_obligations() -> None:
    contract = contract_for("create_wall").to_dict()
    refinement = contract["refinement"]
    assert refinement is not None
    assert refinement["materializer"]
    assert any(item["kind"] == "geometry"
               for item in refinement["obligations"])
    assert any(item["kind"] == "topology"
               for item in refinement["obligations"])


def test_plan_is_bound_to_the_full_registry_contract(monkeypatch) -> None:
    original = spec.OPS["create_wall"]
    before = plan_program(WALL)
    assert before.ops[0].contract_digest == contract_for("create_wall").digest

    changed = replace(
        original,
        tolerances={**original.tolerances, "contract_probe_mm": 0.125},
    )
    monkeypatch.setitem(spec.OPS, "create_wall", changed)
    after = plan_program(WALL)

    assert after.ops[0].contract_digest != before.ops[0].contract_digest
    assert after.plan_digest != before.plan_digest


def test_same_contract_and_source_are_deterministic() -> None:
    first = plan_program(WALL)
    second = plan_program(WALL)
    assert first.plan_digest == second.plan_digest
    assert first.ops[0].contract_digest == second.ops[0].contract_digest


def test_live_compile_gate_fails_before_service_on_contract_drift(
        monkeypatch, capsys) -> None:
    from kukai.ir import gate_runner

    monkeypatch.setattr(
        gate_runner, "audit_contract_kernel", lambda: ("synthetic drift",))

    class MustNotConstruct:
        def __init__(self) -> None:
            raise AssertionError("compile service touched before contract gate")

    monkeypatch.setattr(gate_runner, "CompileClient", MustNotConstruct)
    assert asyncio.run(gate_runner.main()) == 3
    assert "synthetic drift" in capsys.readouterr().out
