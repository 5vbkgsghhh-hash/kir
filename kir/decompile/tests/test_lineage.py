"""The lineage projection joins receipts without inventing identity."""
from __future__ import annotations

import json

import pytest

from kir import sdk
from kir.compiler import plan_program
from kir.created_ledger import SCHEMA_VERSION as CREATED_LEDGER_SCHEMA
from kir.decompile.l1_schema import stable_l1_id
from kir.decompile.lineage import LineageError, _runtime_index, derive_lineage
from kir.decompile.materialize import leaves_to_program


def _wall(source_id: str = "1001") -> dict:
    return {
        "kind": "op",
        "op_name": "create_wall",
        "_id": stable_l1_id("op", source_id),
        "type_name": "W200",
        "params": {
            "p0_mm": [0.0, 0.0],
            "p1_mm": [5000.0, 0.0],
            "level": {"by": "name", "value": "L1", "_id": "500"},
            "height_mm": 2800.0,
            "type": {"by": "name", "value": "W200", "_id": "600"},
        },
        "source_element_id": source_id,
        "level_name": "L1",
        "anchor_mm": [2500.0, 0.0, 0.0],
    }


def _atom(source_id: str = "2001") -> dict:
    return {
        "kind": "atom",
        "_id": stable_l1_id("atom", source_id),
        "category": "OST_Furniture",
        "category_ru": "мебель",
        "type_name": "T",
        "bbox_min_mm": [0.0, 0.0, 0.0],
        "bbox_max_mm": [100.0, 100.0, 100.0],
        "source_element_id": source_id,
        "level_name": "L1",
        "anchor_mm": [50.0, 50.0, 0.0],
        "reason": {"code": "no_lifter", "detail": "synthetic atom"},
    }


def _runtime_row(result, created):
    plan = result.plans[0]
    assert plan is not None
    return {
        "schema_version": CREATED_LEDGER_SCHEMA,
        "plan_digest": plan.plan_digest,
        "device_id": "device-A",
        "doc_key": "target-model",
        "op_kinds_known": True,
        "created": created,
        "created_count": sum(len(ids) for ids in created.values()),
    }


def test_exact_existing_receipts_form_one_derived_chain() -> None:
    leaf = _wall()
    result = leaves_to_program([leaf])
    op_id = result.accounting.records[0].op_id
    assert op_id is not None

    view = derive_lineage(
        result,
        runtime_rows=(_runtime_row(result, {op_id: ["9001"]}),),
    )

    assert view.runtime_records_bound == 1
    assert len(view.rows) == 1
    row = view.rows[0]
    assert row.source_element_id == leaf["source_element_id"]
    assert row.l1_id == leaf["_id"]
    assert row.kir_op_id == op_id
    assert row.kir_op_name == "create_wall"
    assert row.plan_digest == result.plans[0].plan_digest
    assert row.runtime_document_key == "target-model"
    assert row.runtime_device_id == "device-A"
    assert row.runtime_element_ids == ("9001",)

    # The JSON projection is detached from the types but preserves every value verbatim.
    wire = json.loads(json.dumps(view.as_dict()))
    assert wire["rows"][0]["runtime_element_ids"] == ["9001"]


def test_missing_runtime_evidence_round_trips_as_null_not_guess() -> None:
    leaf = _wall()
    result = leaves_to_program([leaf])

    view = derive_lineage(result)
    row = view.rows[0]
    assert row.kir_op_id is not None
    assert row.plan_digest is not None
    assert row.runtime_record_present is False
    assert row.runtime_document_key is None
    assert row.runtime_device_id is None
    assert row.runtime_element_ids is None

    wire = json.loads(json.dumps(view.as_dict()))["rows"][0]
    assert wire["runtime_element_ids"] is None
    assert wire["runtime_element_ids"] != [row.kir_op_id]
    assert wire["runtime_element_ids"] != [row.source_element_id]


def test_a_matching_runtime_record_without_an_op_result_stays_null() -> None:
    result = leaves_to_program([_wall()])
    view = derive_lineage(
        result, runtime_rows=(_runtime_row(result, {}),))

    assert view.rows[0].runtime_record_present is True
    assert view.rows[0].runtime_element_ids is None


def test_a_typed_residual_never_mints_a_kir_or_native_id() -> None:
    atom = _atom()
    view = derive_lineage(leaves_to_program([atom]))
    row = view.rows[0]

    assert row.source_element_id == atom["source_element_id"]
    assert row.l1_id == atom["_id"]
    assert row.kir_op_id is None
    assert row.kir_op_name is None
    assert row.program_index is None
    assert row.plan_digest is None
    assert row.runtime_element_ids is None


def test_runtime_evidence_outside_the_exact_plan_refuses() -> None:
    result = leaves_to_program([_wall()])
    row = _runtime_row(result, {})
    row["plan_digest"] = "f" * 64

    with pytest.raises(LineageError, match="outside materialization"):
        derive_lineage(result, runtime_rows=(row,))


def test_runtime_ids_cannot_disagree_with_the_planned_result_cardinality() -> None:
    result = leaves_to_program([_wall()])
    op_id = result.accounting.records[0].op_id
    assert op_id is not None

    with pytest.raises(LineageError, match="ONE cardinality"):
        derive_lineage(
            result,
            runtime_rows=(_runtime_row(
                result, {op_id: ["9001", "9002"]}),),
        )


def test_many_result_cannot_count_one_native_element_twice() -> None:
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [sdk.create_room_separator(
            path=[[0, 0], [5000, 0]], level="Этаж 1", id="sep1")],
    })
    row = {
        "schema_version": CREATED_LEDGER_SCHEMA,
        "plan_digest": plan.plan_digest,
        "device_id": "device-A",
        "doc_key": "target-model",
        "op_kinds_known": True,
        "created": {"sep1": ["101", "101"]},
        "created_count": 2,
    }
    with pytest.raises(LineageError, match="repeat one Revit ElementId"):
        _runtime_index(
            (row,),
            plans_by_digest={
                plan.plan_digest: {op.op_id: op for op in plan.ops},
            },
        )


def test_two_executions_of_one_plan_are_ambiguous_not_latest_wins() -> None:
    result = leaves_to_program([_wall()])
    op_id = result.accounting.records[0].op_id
    assert op_id is not None
    first = _runtime_row(result, {op_id: ["9001"]})
    second = _runtime_row(result, {op_id: ["9999"]})
    second["doc_key"] = "another-target"

    with pytest.raises(LineageError, match="multiple runtime rows"):
        derive_lineage(result, runtime_rows=(first, second))


@pytest.mark.parametrize("field", ["device_id", "doc_key"])
def test_document_local_ids_require_an_exact_runtime_scope(field: str) -> None:
    result = leaves_to_program([_wall()])
    row = _runtime_row(result, {})
    row[field] = ""

    with pytest.raises(LineageError, match="bind the target model"):
        derive_lineage(result, runtime_rows=(row,))


def test_legacy_or_internally_inconsistent_ledger_row_is_not_evidence() -> None:
    result = leaves_to_program([_wall()])
    op_id = result.accounting.records[0].op_id
    assert op_id is not None
    row = _runtime_row(result, {op_id: ["9001"]})

    with pytest.raises(LineageError, match="operation-kind binding"):
        derive_lineage(
            result, runtime_rows=({**row, "op_kinds_known": False},))
    with pytest.raises(LineageError, match="created_count disagrees"):
        derive_lineage(
            result, runtime_rows=({**row, "created_count": 0},))
