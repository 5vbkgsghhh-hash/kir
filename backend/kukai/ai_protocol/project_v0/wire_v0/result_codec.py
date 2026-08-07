"""Semantic admission for accepted AP02-K values carried by AP02-W."""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from kukai.ai_protocol.project_v0.contracts import (
    CoverageV0,
    CursorRefV0,
    ModelQueryCommandV0,
    ModelQueryResultV0,
    ProjectReadResultV0,
    ReadReceiptV0,
    SourcePatchResultV0,
    exact_digest,
    exact_identifier,
    exact_int,
)
from kukai.ai_protocol.project_v0.errors import ProjectContractError
from kukai.ai_protocol.project_v0.schemas import (
    COVERAGE_SCHEMA,
    CURSOR_REF_SCHEMA,
    MODEL_QUERY_RESULT_SCHEMA,
    MODEL_QUERY_SCOPES,
    MAX_PAGE_BYTES,
    MAX_PAGE_ITEMS,
    PROJECT_READ_RESULT_SCHEMA,
    PROJECT_READ_SCOPES,
    READ_RECEIPT_SCHEMA,
    SOURCE_PATCH_RESULT_SCHEMA,
)
from kukai.ai_protocol.project_v0.source_codec import (
    parse_exception,
    parse_module,
    parse_root,
)
from kukai.design_source import (
    BuildEntityV0,
    BuildOriginV0,
    FrozenMap,
    canonical_bytes,
    canonical_digest,
    root_digest,
)
from kukai.design_source.errors import DesignSourceError
from kukai.design_source.query import BuildSummaryV0


_COVERAGE_FIELDS = frozenset({
    "evaluated",
    "requested",
    "returned",
    "schema",
    "state",
})
_RECEIPT_FIELDS = frozenset({
    "authority",
    "build_digest",
    "chain_digest",
    "coverage",
    "kind",
    "object_digest",
    "present",
    "project_id",
    "receipt_digest",
    "receipt_id",
    "result_digest",
    "revision_digest",
    "schema",
    "scope",
    "selector",
})
_CURSOR_REF_FIELDS = frozenset({"cursor_digest", "cursor_id", "schema"})
_PROJECT_READ_RESULT_FIELDS = frozenset({
    "build_digest",
    "coverage",
    "cursor",
    "present",
    "project_id",
    "receipt",
    "revision_digest",
    "schema",
    "scope",
    "selector",
    "value",
})
_MODEL_QUERY_RESULT_FIELDS = frozenset({
    "build_digest",
    "coverage",
    "cursor",
    "filters",
    "items",
    "project_id",
    "receipt",
    "revision_digest",
    "schema",
    "scope",
})
_SOURCE_PATCH_RESULT_FIELDS = frozenset({
    "base_revision_digest",
    "build_digest",
    "patch_id",
    "project_id",
    "revision_digest",
    "schema",
    "semantic_patch_digest",
    "source_digest",
    "transition_digest",
})
_BUILD_ORIGIN_FIELDS = frozenset({
    "call_id",
    "exception_digests",
    "generator_digest",
    "generator_id",
    "identity_namespace_digest",
    "instance_id",
    "module_digest",
    "module_id",
    "occurrence_key",
    "schema",
    "slot_id",
    "source_digest",
})
_BUILD_ENTITY_FIELDS = frozenset({
    "dependencies",
    "geometry",
    "logical_id",
    "origin",
    "properties",
    "schema",
    "semantic_type",
})
_BUILD_SUMMARY_FIELDS = frozenset({
    "build_digest",
    "counts_by_semantic_type",
    "entity_count",
    "schema",
})
_MANIFEST_VIEW_FIELDS = frozenset({
    "build_digest",
    "entity_count",
    "exception_count",
    "instance_count",
    "module_count",
    "package_lock_digest",
    "project_id",
    "revision_digest",
    "root_instance_id",
    "root_module_id",
    "schema",
    "source_digest",
})
_MODULE_INDEX_ENTRY_FIELDS = frozenset({
    "module_digest",
    "module_id",
    "schema",
})
_EXCEPTION_INDEX_ENTRY_FIELDS = frozenset({
    "exception_digest",
    "exception_id",
    "schema",
    "target_instance_id",
})

_T = TypeVar("_T")


def _typed_boundary(path: str):
    """Keep public semantic admission inside one accepted-K error family."""

    def decorate(parser: Callable[..., _T]) -> Callable[..., _T]:
        @wraps(parser)
        def admitted(*args: Any, **kwargs: Any) -> _T:
            try:
                return parser(*args, **kwargs)
            except ProjectContractError:
                raise
            except (
                DesignSourceError,
                LookupError,
                RecursionError,
                TypeError,
                ValueError,
            ) as exc:
                raise ProjectContractError(f"{path}: {exc}") from exc

        return admitted

    return decorate


def _exact_object(value: Any, fields: frozenset[str], path: str) -> FrozenMap:
    if type(value) is not FrozenMap:
        raise ProjectContractError(f"{path} must be an exact object")
    if set(value) != fields:
        raise ProjectContractError(
            f"{path} fields mismatch; "
            f"missing={sorted(fields - set(value))}, "
            f"extra={sorted(set(value) - fields)}"
        )
    return value


def _require_exact_data(value: FrozenMap, rebuilt: Any, path: str) -> None:
    if canonical_bytes(value) != canonical_bytes(rebuilt.to_data()):
        raise ProjectContractError(f"{path} canonical value mismatch")


@_typed_boundary("coverage")
def parse_k_coverage(value: Any, path: str = "coverage") -> CoverageV0:
    """Admit one exact accepted-K coverage value without weakening counts."""

    data = _exact_object(value, _COVERAGE_FIELDS, path)
    if data["schema"] != COVERAGE_SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    coverage = CoverageV0(
        data["state"],
        data["requested"],
        data["evaluated"],
        data["returned"],
    )
    _require_exact_data(data, coverage, path)
    return coverage


@_typed_boundary("read_receipt")
def parse_k_read_receipt(
    value: Any,
    path: str = "read_receipt",
) -> ReadReceiptV0:
    """Recompute a receipt's derived identity and digest from its exact body."""

    data = _exact_object(value, _RECEIPT_FIELDS, path)
    if data["schema"] != READ_RECEIPT_SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    receipt = ReadReceiptV0(
        kind=data["kind"],
        authority=data["authority"],
        project_id=data["project_id"],
        revision_digest=data["revision_digest"],
        build_digest=data["build_digest"],
        scope=data["scope"],
        selector=data["selector"],
        present=data["present"],
        object_digest=data["object_digest"],
        result_digest=data["result_digest"],
        coverage=parse_k_coverage(data["coverage"], f"{path}.coverage"),
        chain_digest=data["chain_digest"],
    )
    _require_exact_data(data, receipt, path)
    return receipt


def _same_value(left: Any, right: Any, path: str) -> None:
    if type(left) is CoverageV0:
        left = left.to_data()
    if type(right) is CoverageV0:
        right = right.to_data()
    if canonical_bytes(left) != canonical_bytes(right):
        raise ProjectContractError(f"{path} binding mismatch")


def _parse_cursor_ref(value: Any, path: str) -> CursorRefV0:
    data = _exact_object(value, _CURSOR_REF_FIELDS, path)
    if data["schema"] != CURSOR_REF_SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    cursor = CursorRefV0(data["cursor_id"], data["cursor_digest"])
    _require_exact_data(data, cursor, path)
    return cursor


def _parse_build_origin(value: Any, path: str) -> BuildOriginV0:
    data = _exact_object(value, _BUILD_ORIGIN_FIELDS, path)
    if data["schema"] != BuildOriginV0.SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    if type(data["exception_digests"]) is not tuple:
        raise ProjectContractError(
            f"{path}.exception_digests must be an exact array")
    origin = BuildOriginV0(
        source_digest=data["source_digest"],
        identity_namespace_digest=data["identity_namespace_digest"],
        module_id=data["module_id"],
        module_digest=data["module_digest"],
        instance_id=data["instance_id"],
        generator_id=data["generator_id"],
        generator_digest=data["generator_digest"],
        call_id=data["call_id"],
        slot_id=data["slot_id"],
        occurrence_key=data["occurrence_key"],
        exception_digests=data["exception_digests"],
    )
    _require_exact_data(data, origin, path)
    return origin


def _parse_build_entity(value: Any, path: str) -> BuildEntityV0:
    data = _exact_object(value, _BUILD_ENTITY_FIELDS, path)
    if data["schema"] != BuildEntityV0.SCHEMA:
        raise ProjectContractError(f"{path}.schema is not exact")
    if type(data["properties"]) is not FrozenMap:
        raise ProjectContractError(f"{path}.properties must be an exact object")
    if type(data["geometry"]) is not FrozenMap:
        raise ProjectContractError(f"{path}.geometry must be an exact object")
    if type(data["dependencies"]) is not tuple:
        raise ProjectContractError(f"{path}.dependencies must be an exact array")
    entity = BuildEntityV0(
        logical_id=data["logical_id"],
        semantic_type=data["semantic_type"],
        properties=data["properties"],
        geometry=data["geometry"],
        dependencies=data["dependencies"],
        origin=_parse_build_origin(data["origin"], f"{path}.origin"),
    )
    _require_exact_data(data, entity, path)
    return entity


def _parse_build_summary(
    value: Any,
    path: str,
    expected_build_digest: str,
) -> BuildSummaryV0:
    data = _exact_object(value, _BUILD_SUMMARY_FIELDS, path)
    if data["schema"] != BuildSummaryV0.schema:
        raise ProjectContractError(f"{path}.schema is not exact")
    if type(data["counts_by_semantic_type"]) is not FrozenMap:
        raise ProjectContractError(
            f"{path}.counts_by_semantic_type must be an exact object")
    summary = BuildSummaryV0(
        data["build_digest"],
        data["entity_count"],
        data["counts_by_semantic_type"],
    )
    rebuilt = {
        "build_digest": summary.build_digest,
        "counts_by_semantic_type": summary.counts_by_semantic_type,
        "entity_count": summary.entity_count,
        "schema": summary.schema,
    }
    _same_value(data, rebuilt, path)
    if summary.build_digest != expected_build_digest:
        raise ProjectContractError(f"{path}.build_digest binding mismatch")
    return summary


def _parse_manifest_view(
    value: Any,
    *,
    project_id: str,
    revision_digest: str,
    build_digest: str,
    path: str,
) -> None:
    data = _exact_object(value, _MANIFEST_VIEW_FIELDS, path)
    if data["schema"] != "kir-ai-project-manifest-view/0":
        raise ProjectContractError(f"{path}.schema is not exact")
    exact_identifier(data["project_id"], f"{path}.project_id")
    exact_identifier(data["root_instance_id"], f"{path}.root_instance_id")
    exact_identifier(data["root_module_id"], f"{path}.root_module_id")
    for name in (
        "build_digest",
        "package_lock_digest",
        "revision_digest",
        "source_digest",
    ):
        exact_digest(data[name], f"{path}.{name}")
    for name in (
        "entity_count",
        "exception_count",
        "instance_count",
        "module_count",
    ):
        exact_int(data[name], f"{path}.{name}", minimum=0, maximum=1_000_000_000)
    if (
        data["project_id"] != project_id
        or data["revision_digest"] != revision_digest
        or data["build_digest"] != build_digest
    ):
        raise ProjectContractError(f"{path} head binding mismatch")


def _parse_module_index(value: Any, path: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ProjectContractError(f"{path} must be an exact array")
    identifiers = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        data = _exact_object(item, _MODULE_INDEX_ENTRY_FIELDS, item_path)
        if data["schema"] != "kir-ai-module-index-entry/0":
            raise ProjectContractError(f"{item_path}.schema is not exact")
        identifiers.append(exact_identifier(
            data["module_id"], f"{item_path}.module_id"))
        exact_digest(data["module_digest"], f"{item_path}.module_digest")
    if identifiers != sorted(set(identifiers)):
        raise ProjectContractError(f"{path} identity/order invariant failed")
    return tuple(identifiers)


def _parse_exception_index(value: Any, path: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ProjectContractError(f"{path} must be an exact array")
    identifiers = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        data = _exact_object(item, _EXCEPTION_INDEX_ENTRY_FIELDS, item_path)
        if data["schema"] != "kir-ai-exception-index-entry/0":
            raise ProjectContractError(f"{item_path}.schema is not exact")
        identifiers.append(exact_identifier(
            data["exception_id"], f"{item_path}.exception_id"))
        exact_identifier(
            data["target_instance_id"], f"{item_path}.target_instance_id")
        exact_digest(
            data["exception_digest"], f"{item_path}.exception_digest")
    if identifiers != sorted(set(identifiers)):
        raise ProjectContractError(f"{path} identity/order invariant failed")
    return tuple(identifiers)


def _read_payload_semantics(
    data: FrozenMap,
    coverage: CoverageV0,
) -> tuple[str, str | None]:
    scope = data["scope"]
    selector = data["selector"]
    present = data["present"]
    value = data["value"]
    if type(selector) is not FrozenMap:
        raise ProjectContractError("project.read result selector is not exact")
    if type(present) not in {bool, type(None)}:
        raise ProjectContractError("project.read result present is not exact")

    expected_requested = 1
    expected_returned = 1
    object_digest = None
    authority = "INFORMATIONAL"
    if scope == "manifest":
        if selector or present is not True:
            raise ProjectContractError("manifest read shape is inconsistent")
        _parse_manifest_view(
            value,
            project_id=data["project_id"],
            revision_digest=data["revision_digest"],
            build_digest=data["build_digest"],
            path="project.read.result.value",
        )
    elif scope == "module.index":
        if selector or present is not None:
            raise ProjectContractError("module index read shape is inconsistent")
        identifiers = _parse_module_index(value, "project.read.result.value")
        expected_requested = len(identifiers)
        expected_returned = len(identifiers)
    elif scope == "exception.index":
        if selector or present is not None:
            raise ProjectContractError("exception index read shape is inconsistent")
        identifiers = _parse_exception_index(value, "project.read.result.value")
        expected_requested = len(identifiers)
        expected_returned = len(identifiers)
    elif scope == "root_instance":
        if selector or present is not True:
            raise ProjectContractError("root read shape is inconsistent")
        root = parse_root(value, "project.read.result.value")
        _same_value(value, root.to_data(), "project.read root value")
        object_digest = root_digest(root)
        authority = "OWNER"
    elif scope in {"module", "exception"}:
        key = "module_id" if scope == "module" else "exception_id"
        if set(selector) != {key}:
            raise ProjectContractError(f"{scope} selector is inconsistent")
        exact_identifier(selector[key], f"project.read.selector.{key}")
        if present is False:
            if value is not None:
                raise ProjectContractError(f"absent {scope} must carry null value")
            expected_returned = 0
        elif present is True:
            parsed = (
                parse_module(value, "project.read.result.value")
                if scope == "module"
                else parse_exception(value, "project.read.result.value")
            )
            rebuilt = (
                parsed.semantic_data() if scope == "module" else parsed.to_data())
            _same_value(value, rebuilt, f"project.read {scope} value")
            payload_id = (
                parsed.module_id if scope == "module" else parsed.exception_id)
            if payload_id != selector[key]:
                raise ProjectContractError(
                    f"project.read {scope} selector/value identity mismatch")
            object_digest = (
                parsed.module_digest
                if scope == "module"
                else parsed.exception_digest
            )
        else:
            raise ProjectContractError(f"{scope} present must be exact bool")
        authority = "OWNER"
    else:
        raise ProjectContractError("project.read result scope is unsupported")

    expected = CoverageV0(
        "COMPLETE",
        expected_requested,
        expected_requested,
        expected_returned,
    )
    _same_value(coverage.to_data(), expected.to_data(), "project.read coverage")
    return authority, object_digest


@_typed_boundary("project.read result")
def parse_project_read_result(value: Any) -> ProjectReadResultV0:
    """Admit one exact K project.read result and all receipt bindings."""

    data = _exact_object(
        value, _PROJECT_READ_RESULT_FIELDS, "project.read result")
    if data["schema"] != PROJECT_READ_RESULT_SCHEMA:
        raise ProjectContractError("project.read result schema is not exact")
    if data["cursor"] is not None:
        raise ProjectContractError("project.read result cursor must be null")
    project_id = exact_identifier(data["project_id"], "project.read.project_id")
    revision_digest = exact_digest(
        data["revision_digest"], "project.read.revision_digest")
    build_digest = exact_digest(
        data["build_digest"], "project.read.build_digest")
    scope = data["scope"]
    if type(scope) is not str or scope not in PROJECT_READ_SCOPES:
        raise ProjectContractError("project.read result scope is unsupported")
    coverage = parse_k_coverage(data["coverage"], "project.read.coverage")
    authority, object_digest = _read_payload_semantics(data, coverage)
    receipt = parse_k_read_receipt(data["receipt"], "project.read.receipt")
    result_digest = canonical_digest("kir.ai-project-read-result-body.v0", {
        "coverage": coverage.to_data(),
        "present": data["present"],
        "project_id": project_id,
        "revision_digest": revision_digest,
        "scope": scope,
        "selector": data["selector"],
        "value": data["value"],
    })
    expected_receipt = {
        "authority": authority,
        "build_digest": build_digest,
        "chain_digest": None,
        "coverage": coverage.to_data(),
        "kind": "PROJECT_READ",
        "object_digest": object_digest,
        "present": data["present"],
        "project_id": project_id,
        "result_digest": result_digest,
        "revision_digest": revision_digest,
        "scope": scope,
        "selector": data["selector"],
    }
    for name, expected in expected_receipt.items():
        _same_value(getattr(receipt, name), expected, f"project.read.receipt.{name}")
    result = ProjectReadResultV0(
        project_id=project_id,
        revision_digest=revision_digest,
        build_digest=build_digest,
        scope=scope,
        selector=data["selector"],
        present=data["present"],
        value=data["value"],
        coverage=coverage,
        receipt=receipt,
    )
    _require_exact_data(data, result, "project.read result")
    return result


def _query_items(
    data: FrozenMap,
    coverage: CoverageV0,
) -> tuple[Any, ...]:
    items = data["items"]
    if type(items) is not tuple:
        raise ProjectContractError("model.query items must be an exact array")
    if len(items) > MAX_PAGE_ITEMS:
        raise ProjectContractError(
            f"model.query items exceed the K page cap of {MAX_PAGE_ITEMS}")
    if coverage.evaluated != coverage.requested:
        raise ProjectContractError("model.query must evaluate its full census")
    if coverage.returned != len(items):
        raise ProjectContractError("model.query returned census mismatch")
    scope = data["scope"]
    if scope == "summary":
        if (
            coverage.state != "COMPLETE"
            or coverage.requested != 1
            or coverage.returned != 1
            or len(items) != 1
        ):
            raise ProjectContractError("summary query census is inconsistent")
        summary = _parse_build_summary(
            items[0], "model.query.items[0]", data["build_digest"])
        return (summary,)

    entities = tuple(
        _parse_build_entity(item, f"model.query.items[{index}]")
        for index, item in enumerate(items)
    )
    identifiers = tuple(item.logical_id for item in entities)
    if identifiers != tuple(sorted(set(identifiers))):
        raise ProjectContractError("model.query item identity/order invariant failed")
    if scope == "logical_id":
        if (
            coverage.state != "COMPLETE"
            or coverage.requested != 1
            or coverage.returned != 1
            or len(entities) != 1
        ):
            raise ProjectContractError("logical_id query result is inconsistent")
        if entities[0].logical_id != data["filters"]["logical_id"]:
            raise ProjectContractError("logical_id query identity is inconsistent")
    elif scope == "origin":
        for entity in entities:
            for name, expected in data["filters"].items():
                if getattr(entity.origin, name) != expected:
                    raise ProjectContractError(
                        "origin query returned an entity outside its filters")
        if coverage.state == "PARTIAL" and (
            coverage.returned == 0 or coverage.returned >= coverage.requested
        ):
            raise ProjectContractError("partial origin page census is inconsistent")
    return entities


@_typed_boundary("model.query result")
def parse_model_query_result(value: Any) -> ModelQueryResultV0:
    """Admit one exact K model.query page and receipt/result bindings."""

    data = _exact_object(
        value, _MODEL_QUERY_RESULT_FIELDS, "model.query result")
    if len(canonical_bytes(data)) > MAX_PAGE_BYTES:
        raise ProjectContractError(
            f"model.query result exceeds the K page cap of {MAX_PAGE_BYTES} bytes")
    if data["schema"] != MODEL_QUERY_RESULT_SCHEMA:
        raise ProjectContractError("model.query result schema is not exact")
    project_id = exact_identifier(data["project_id"], "model.query.project_id")
    revision_digest = exact_digest(
        data["revision_digest"], "model.query.revision_digest")
    build_digest = exact_digest(
        data["build_digest"], "model.query.build_digest")
    scope = data["scope"]
    if type(scope) is not str or scope not in MODEL_QUERY_SCOPES:
        raise ProjectContractError("model.query result scope is unsupported")
    ModelQueryCommandV0(
        project_id=project_id,
        revision_digest=revision_digest,
        build_digest=build_digest,
        scope=scope,
        filters=data["filters"],
        limit=1,
    )
    coverage = parse_k_coverage(data["coverage"], "model.query.coverage")
    _query_items(data, coverage)
    cursor = (
        None
        if data["cursor"] is None
        else _parse_cursor_ref(data["cursor"], "model.query.cursor")
    )
    if (coverage.state == "COMPLETE") != (cursor is None):
        raise ProjectContractError("model.query coverage/cursor invariant failed")
    receipt = parse_k_read_receipt(data["receipt"], "model.query.receipt")
    if receipt.chain_digest is None:
        raise ProjectContractError("model.query receipt requires chain_digest")
    result_digest = canonical_digest("kir.ai-model-query-result-body.v0", {
        "build_digest": build_digest,
        "chain_digest": receipt.chain_digest,
        "coverage": coverage.to_data(),
        "filters": data["filters"],
        "items": data["items"],
        "project_id": project_id,
        "revision_digest": revision_digest,
        "scope": scope,
    })
    expected_receipt = {
        "authority": "INFORMATIONAL",
        "build_digest": build_digest,
        "coverage": coverage.to_data(),
        "kind": "MODEL_QUERY",
        "object_digest": None,
        "present": None,
        "project_id": project_id,
        "result_digest": result_digest,
        "revision_digest": revision_digest,
        "scope": scope,
        "selector": data["filters"],
    }
    for name, expected in expected_receipt.items():
        _same_value(getattr(receipt, name), expected, f"model.query.receipt.{name}")
    result = ModelQueryResultV0(
        project_id=project_id,
        revision_digest=revision_digest,
        build_digest=build_digest,
        scope=scope,
        filters=data["filters"],
        items=data["items"],
        coverage=coverage,
        cursor=cursor,
        receipt=receipt,
    )
    _require_exact_data(data, result, "model.query result")
    return result


@_typed_boundary("source.patch result")
def parse_source_patch_result(value: Any) -> SourcePatchResultV0:
    """Admit one exact K source.patch transition and recompute its digest."""

    data = _exact_object(
        value, _SOURCE_PATCH_RESULT_FIELDS, "source.patch result")
    if data["schema"] != SOURCE_PATCH_RESULT_SCHEMA:
        raise ProjectContractError("source.patch result schema is not exact")
    result = SourcePatchResultV0(
        patch_id=data["patch_id"],
        semantic_patch_digest=data["semantic_patch_digest"],
        transition_digest=data["transition_digest"],
        project_id=data["project_id"],
        base_revision_digest=data["base_revision_digest"],
        revision_digest=data["revision_digest"],
        source_digest=data["source_digest"],
        build_digest=data["build_digest"],
    )
    expected_transition = canonical_digest("kir.ai-source-transition.v0", {
        "base_revision_digest": result.base_revision_digest,
        "build_digest": result.build_digest,
        "project_id": result.project_id,
        "revision_digest": result.revision_digest,
        "semantic_patch_digest": result.semantic_patch_digest,
        "source_digest": result.source_digest,
    })
    if result.transition_digest != expected_transition:
        raise ProjectContractError("source.patch transition_digest mismatch")
    _require_exact_data(data, result, "source.patch result")
    return result


__all__ = [
    "parse_k_coverage",
    "parse_k_read_receipt",
    "parse_model_query_result",
    "parse_project_read_result",
    "parse_source_patch_result",
]
