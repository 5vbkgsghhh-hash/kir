from __future__ import annotations

import json

import pytest

from kukai.ai_protocol.project_v0 import (
    ProjectContractError,
    ProjectLimitError,
    parse_exception,
    parse_model_query_command,
    parse_module,
    parse_project_read_command,
    parse_root,
    parse_source_patch_command,
)
from kukai.ai_protocol.project_v0.schemas import (
    CURSOR_REF_SCHEMA,
    EXCEPTION_PUT_SCHEMA,
    EXCEPTION_REMOVE_SCHEMA,
    MODEL_QUERY_COMMAND_SCHEMA,
    MODULE_PUT_SCHEMA,
    PROJECT_READ_COMMAND_SCHEMA,
    RECEIPT_REF_SCHEMA,
    ROOT_PUT_SCHEMA,
    SOURCE_PATCH_COMMAND_SCHEMA,
)
from kukai.design_source import canonical_bytes
from kukai.design_source.examples import make_tower_source
from kukai.design_source.materializer import child_instance_id


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _receipt_ref() -> dict:
    return {
        "receipt_digest": DIGEST_A,
        "receipt_id": "rr_" + "a" * 40,
        "schema": RECEIPT_REF_SCHEMA,
    }


def _patch_data(operations) -> dict:
    return {
        "base_revision_digest": DIGEST_B,
        "operations": operations,
        "patch_id": "patch_1",
        "project_id": "project_v0",
        "receipt_refs": [_receipt_ref()],
        "schema": SOURCE_PATCH_COMMAND_SCHEMA,
    }


def test_module_parser_accepts_only_semantic_form_and_injects_empty_label() -> None:
    source = make_tower_source()
    original = source.modules[0]

    admitted = parse_module(original.semantic_data())

    assert admitted.module_digest == original.module_digest
    assert admitted.label == ""
    assert canonical_bytes(admitted.semantic_data()) == canonical_bytes(
        original.semantic_data())
    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_module(original.to_data())


@pytest.mark.parametrize("field", ["label", "metadata", "authority", "approval"])
def test_module_parser_rejects_metadata_authority_and_aliases(field: str) -> None:
    data = make_tower_source().modules[0].semantic_data()
    data[field] = {} if field == "metadata" else "forbidden"

    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_module(data)


def test_module_parser_rejects_key_identity_mismatch_and_nested_unknown() -> None:
    data = make_tower_source().modules[0].semantic_data()
    parameter_key = next(iter(data["parameters"]))
    data["parameters"]["wrong"] = data["parameters"].pop(parameter_key)
    with pytest.raises(ProjectContractError, match="key/identity mismatch"):
        parse_module(data)

    data = make_tower_source().modules[0].semantic_data()
    parameter_key = next(iter(data["parameters"]))
    data["parameters"][parameter_key] = {
        **data["parameters"][parameter_key].to_data(),
        "alias": True,
    }
    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_module(data)


def test_root_and_exception_parsers_round_trip_exact_records() -> None:
    source = make_tower_source(exception_floor_key="L002")

    root = parse_root(source.root.to_data())
    exception = parse_exception(source.exceptions[0].to_data())

    assert canonical_bytes(root.to_data()) == canonical_bytes(source.root.to_data())
    assert exception.exception_digest == source.exceptions[0].exception_digest


def test_project_read_parser_enforces_scope_specific_exact_fields() -> None:
    data = {
        "module_id": "mod_typical_floor",
        "project_id": "project_v0",
        "revision_digest": DIGEST_A,
        "schema": PROJECT_READ_COMMAND_SCHEMA,
        "scope": "module",
    }
    admitted = parse_project_read_command(data)
    assert admitted.target_id == "mod_typical_floor"

    wrong = dict(data)
    wrong["exception_id"] = "exc_1"
    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_project_read_command(wrong)

    alias = dict(data)
    alias["token"] = "caller-token"
    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_project_read_command(alias)


def test_model_query_parser_enforces_closed_scope_filters_and_cursor() -> None:
    data = {
        "build_digest": DIGEST_B,
        "cursor": None,
        "filters": {"module_id": "mod_typical_floor"},
        "limit": 128,
        "project_id": "project_v0",
        "revision_digest": DIGEST_A,
        "schema": MODEL_QUERY_COMMAND_SCHEMA,
        "scope": "origin",
    }
    admitted = parse_model_query_command(data)
    assert admitted.filters["module_id"] == "mod_typical_floor"

    data["filters"] = {"category": "walls"}
    with pytest.raises(ProjectContractError, match="filters"):
        parse_model_query_command(data)

    data["filters"] = {"module_id": "mod_typical_floor"}
    data["cursor"] = {
        "cursor_digest": DIGEST_A,
        "cursor_id": "cur_" + "a" * 40,
        "schema": CURSOR_REF_SCHEMA,
    }
    assert parse_model_query_command(data).cursor is not None


def test_patch_parser_accepts_exact_four_ops_and_preserves_same_target_order() -> None:
    source = make_tower_source(exception_floor_key="L002")
    module = source.module_map["mod_typical_floor"].semantic_data()
    target = child_instance_id(
        "ins_building", "call_levels", "floor_instances", "L002")
    exception = {
        "exception_id": "exc_new",
        "expected_value": 30000,
        "parameter_id": "width",
        "schema": "kir-design-exception-set-instance-argument/0",
        "target_instance_id": target,
        "value": "36000",
    }
    operations = [
        {"module": module, "op_id": "m1", "schema": MODULE_PUT_SCHEMA},
        {"module": module, "op_id": "m2", "schema": MODULE_PUT_SCHEMA},
        {"op_id": "r1", "root": source.root.to_data(), "schema": ROOT_PUT_SCHEMA},
        {"exception": exception, "op_id": "e1", "schema": EXCEPTION_PUT_SCHEMA},
        {
            "exception_id": "exc_new",
            "op_id": "e2",
            "schema": EXCEPTION_REMOVE_SCHEMA,
        },
    ]

    admitted = parse_source_patch_command(_patch_data(operations))

    assert [item.op_id for item in admitted.operations] == ["m1", "m2", "r1", "e1", "e2"]
    assert admitted.operations[3].exception.expected_value == 30000


@pytest.mark.parametrize(
    "forged",
    ["author_id", "principal", "authority", "approval", "token", "request_id"],
)
def test_patch_parser_rejects_model_supplied_authority(forged: str) -> None:
    source = make_tower_source()
    data = _patch_data([{
        "module": source.modules[0].semantic_data(),
        "op_id": "m1",
        "schema": MODULE_PUT_SCHEMA,
    }])
    data[forged] = "forged"

    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_source_patch_command(data)


def test_patch_ops_reject_server_owned_expected_digest() -> None:
    source = make_tower_source()
    operation = {
        "expected_digest": source.modules[0].module_digest,
        "module": source.modules[0].semantic_data(),
        "op_id": "m1",
        "schema": MODULE_PUT_SCHEMA,
    }
    with pytest.raises(ProjectContractError, match="fields mismatch"):
        parse_source_patch_command(_patch_data([operation]))


def test_command_parser_applies_one_megabyte_canonical_budget_first() -> None:
    data = {
        "padding": "x" * 1_000_000,
        "project_id": "project_v0",
        "revision_digest": DIGEST_A,
        "schema": PROJECT_READ_COMMAND_SCHEMA,
        "scope": "manifest",
    }
    assert len(canonical_bytes(data)) > 1_000_000

    with pytest.raises(ProjectLimitError, match="canonical bytes"):
        parse_project_read_command(data)


def test_parser_copies_mutable_input_without_aliases() -> None:
    data = json.loads(canonical_bytes(
        make_tower_source().modules[0].semantic_data()))
    admitted = parse_module(data)
    data["module_id"] = "mod_mutated"
    data["parameters"].clear()

    assert admitted.module_id != "mod_mutated"
    assert admitted.parameters
