"""Strict semantic parsers for AP02-K commands and Design Source records."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

from kukai.design_source import (
    CanonicalError,
    FrozenMap,
    GeneratorCallV0,
    ModuleV0,
    ParameterSpecV0,
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    SlotSpecV0,
    canonical_bytes,
    strict_json_loads,
)
from kukai.design_source.errors import DesignSourceError

from .contracts import (
    CursorRefV0,
    ExceptionPutV0,
    ExceptionRemoveV0,
    ModelQueryCommandV0,
    ModulePutV0,
    ProjectReadCommandV0,
    ReceiptRefV0,
    RootPutV0,
    SourcePatchCommandV0,
)
from .errors import ProjectContractError, ProjectLimitError
from .schemas import (
    EXCEPTION_PUT_SCHEMA,
    EXCEPTION_REMOVE_SCHEMA,
    CURSOR_REF_SCHEMA,
    MAX_ARGUMENT_BYTES,
    MODEL_QUERY_COMMAND_SCHEMA,
    MODULE_PUT_SCHEMA,
    PROJECT_READ_COMMAND_SCHEMA,
    RECEIPT_REF_SCHEMA,
    ROOT_PUT_SCHEMA,
    SOURCE_PATCH_COMMAND_SCHEMA,
)


def _admit_object(value: Any, path: str, *, max_bytes: int = MAX_ARGUMENT_BYTES) -> FrozenMap:
    if not isinstance(value, Mapping):
        raise ProjectContractError(f"{path} must be an object")
    try:
        payload = canonical_bytes(value)
        if len(payload) > max_bytes:
            raise ProjectLimitError(f"{path} exceeds {max_bytes} canonical bytes")
        admitted = strict_json_loads(payload)
    except ProjectLimitError:
        raise
    except (CanonicalError, TypeError, ValueError, RecursionError) as exc:
        raise ProjectContractError(f"{path} is not canonical: {exc}") from exc
    if type(admitted) is not FrozenMap:
        raise ProjectContractError(f"{path} must be an exact object")
    return admitted


def _object(value: Any, path: str) -> FrozenMap:
    if type(value) is not FrozenMap:
        raise ProjectContractError(f"{path} must be an exact object")
    return value


def _array(value: Any, path: str) -> tuple[Any, ...]:
    if type(value) is not tuple:
        raise ProjectContractError(f"{path} must be an exact array")
    return value


def _fields(value: FrozenMap, expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ProjectContractError(
            f"{path} fields mismatch; missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _schema(value: FrozenMap, expected: str, path: str) -> None:
    if type(value.get("schema")) is not str or value["schema"] != expected:
        raise ProjectContractError(f"{path}.schema is not exact")


def _construct(path: str, factory: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return factory(*args, **kwargs)
    except (DesignSourceError, CanonicalError, TypeError, ValueError) as exc:
        raise ProjectContractError(f"{path}: {exc}") from exc


def _keyed_records(
    value: Any,
    path: str,
    parser: Callable[[FrozenMap, str], Any],
    id_attribute: str,
) -> tuple[Any, ...]:
    records = _object(value, path)
    parsed = []
    for key, item in records.items():
        record = parser(_object(item, f"{path}.{key}"), f"{path}.{key}")
        if key != getattr(record, id_attribute):
            raise ProjectContractError(f"{path}.{key} key/identity mismatch")
        parsed.append(record)
    return tuple(parsed)


def _parse_parameter(value: FrozenMap, path: str) -> ParameterSpecV0:
    _fields(value, {"kind", "parameter_id", "schema"}, path)
    _schema(value, ParameterSpecV0.SCHEMA, path)
    return _construct(path, ParameterSpecV0, value["parameter_id"], value["kind"])


def _parse_slot(value: FrozenMap, path: str) -> SlotSpecV0:
    _fields(
        value,
        {
            "cardinality",
            "kind",
            "required_target_properties",
            "schema",
            "semantic_type",
            "slot_id",
        },
        path,
    )
    _schema(value, SlotSpecV0.SCHEMA, path)
    required = _array(value["required_target_properties"],
                      f"{path}.required_target_properties")
    return _construct(
        path,
        SlotSpecV0,
        value["slot_id"],
        value["kind"],
        value["semantic_type"],
        value["cardinality"],
        required,
    )


def _parse_generator_call(value: FrozenMap, path: str) -> GeneratorCallV0:
    _fields(
        value,
        {
            "arguments",
            "bindings",
            "call_id",
            "generator_digest",
            "generator_id",
            "schema",
        },
        path,
    )
    _schema(value, GeneratorCallV0.SCHEMA, path)
    return _construct(
        path,
        GeneratorCallV0,
        call_id=value["call_id"],
        generator_id=value["generator_id"],
        generator_digest=value["generator_digest"],
        arguments=_object(value["arguments"], f"{path}.arguments"),
        bindings=_object(value["bindings"], f"{path}.bindings"),
    )


def parse_module(value: Any, path: str = "module") -> ModuleV0:
    data = _admit_object(value, path)
    _fields(
        data,
        {"generator_calls", "module_id", "parameters", "schema", "slots"},
        path,
    )
    _schema(data, ModuleV0.SCHEMA, path)
    parameters = _keyed_records(
        data["parameters"], f"{path}.parameters", _parse_parameter, "parameter_id")
    slots = _keyed_records(data["slots"], f"{path}.slots", _parse_slot, "slot_id")
    calls = _keyed_records(
        data["generator_calls"],
        f"{path}.generator_calls",
        _parse_generator_call,
        "call_id",
    )
    return _construct(
        path,
        ModuleV0,
        module_id=data["module_id"],
        parameters=parameters,
        slots=slots,
        generator_calls=calls,
        label="",
    )


def parse_root(value: Any, path: str = "root") -> RootInstanceV0:
    data = _admit_object(value, path)
    _fields(data, {"arguments", "instance_id", "module_id", "schema"}, path)
    _schema(data, RootInstanceV0.SCHEMA, path)
    return _construct(
        path,
        RootInstanceV0,
        instance_id=data["instance_id"],
        module_id=data["module_id"],
        arguments=_object(data["arguments"], f"{path}.arguments"),
    )


def parse_exception(
    value: Any,
    path: str = "exception",
) -> SetInstanceArgumentExceptionV0:
    data = _admit_object(value, path)
    _fields(
        data,
        {
            "exception_id",
            "expected_value",
            "parameter_id",
            "schema",
            "target_instance_id",
            "value",
        },
        path,
    )
    _schema(data, SetInstanceArgumentExceptionV0.SCHEMA, path)
    return _construct(
        path,
        SetInstanceArgumentExceptionV0,
        exception_id=data["exception_id"],
        target_instance_id=data["target_instance_id"],
        parameter_id=data["parameter_id"],
        expected_value=data["expected_value"],
        value=data["value"],
    )


def _parse_receipt_ref(value: Any, path: str) -> ReceiptRefV0:
    data = _object(value, path)
    _fields(data, {"receipt_digest", "receipt_id", "schema"}, path)
    if data["schema"] != RECEIPT_REF_SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    return ReceiptRefV0(data["receipt_id"], data["receipt_digest"])


def _parse_cursor_ref(value: Any, path: str) -> CursorRefV0:
    data = _object(value, path)
    _fields(data, {"cursor_digest", "cursor_id", "schema"}, path)
    if data["schema"] != CURSOR_REF_SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    return CursorRefV0(data["cursor_id"], data["cursor_digest"])


def parse_project_read_command(value: Any) -> ProjectReadCommandV0:
    data = _admit_object(value, "project.read")
    base = {"project_id", "revision_digest", "schema", "scope"}
    if data.get("scope") == "module":
        expected = base | {"module_id"}
        target = data.get("module_id")
    elif data.get("scope") == "exception":
        expected = base | {"exception_id"}
        target = data.get("exception_id")
    else:
        expected = base
        target = None
    _fields(data, expected, "project.read")
    _schema(data, PROJECT_READ_COMMAND_SCHEMA, "project.read")
    return ProjectReadCommandV0(
        project_id=data["project_id"],
        revision_digest=data["revision_digest"],
        scope=data["scope"],
        target_id=target,
    )


def parse_model_query_command(value: Any) -> ModelQueryCommandV0:
    data = _admit_object(value, "model.query")
    _fields(
        data,
        {
            "build_digest",
            "cursor",
            "filters",
            "limit",
            "project_id",
            "revision_digest",
            "schema",
            "scope",
        },
        "model.query",
    )
    _schema(data, MODEL_QUERY_COMMAND_SCHEMA, "model.query")
    cursor = None
    if data["cursor"] is not None:
        cursor = _parse_cursor_ref(data["cursor"], "model.query.cursor")
    return ModelQueryCommandV0(
        project_id=data["project_id"],
        revision_digest=data["revision_digest"],
        build_digest=data["build_digest"],
        scope=data["scope"],
        filters=_object(data["filters"], "model.query.filters"),
        limit=data["limit"],
        cursor=cursor,
    )


def _parse_operation(value: Any, path: str):
    data = _object(value, path)
    schema = data.get("schema")
    if schema == MODULE_PUT_SCHEMA:
        _fields(data, {"module", "op_id", "schema"}, path)
        return ModulePutV0(data["op_id"], parse_module(data["module"], f"{path}.module"))
    if schema == ROOT_PUT_SCHEMA:
        _fields(data, {"op_id", "root", "schema"}, path)
        return RootPutV0(data["op_id"], parse_root(data["root"], f"{path}.root"))
    if schema == EXCEPTION_PUT_SCHEMA:
        _fields(data, {"exception", "op_id", "schema"}, path)
        return ExceptionPutV0(
            data["op_id"], parse_exception(data["exception"], f"{path}.exception"))
    if schema == EXCEPTION_REMOVE_SCHEMA:
        _fields(data, {"exception_id", "op_id", "schema"}, path)
        return ExceptionRemoveV0(data["op_id"], data["exception_id"])
    raise ProjectContractError(f"{path}.schema is not one of the four AP02-K ops")


def parse_source_patch_command(value: Any) -> SourcePatchCommandV0:
    data = _admit_object(value, "source.patch")
    _fields(
        data,
        {
            "base_revision_digest",
            "operations",
            "patch_id",
            "project_id",
            "receipt_refs",
            "schema",
        },
        "source.patch",
    )
    _schema(data, SOURCE_PATCH_COMMAND_SCHEMA, "source.patch")
    refs = tuple(
        _parse_receipt_ref(item, f"source.patch.receipt_refs[{index}]")
        for index, item in enumerate(_array(data["receipt_refs"],
                                           "source.patch.receipt_refs"))
    )
    operations = tuple(
        _parse_operation(item, f"source.patch.operations[{index}]")
        for index, item in enumerate(_array(data["operations"],
                                           "source.patch.operations"))
    )
    return SourcePatchCommandV0(
        project_id=data["project_id"],
        base_revision_digest=data["base_revision_digest"],
        patch_id=data["patch_id"],
        receipt_refs=refs,
        operations=operations,
    )


__all__ = [
    "parse_exception",
    "parse_model_query_command",
    "parse_module",
    "parse_project_read_command",
    "parse_root",
    "parse_source_patch_command",
]
