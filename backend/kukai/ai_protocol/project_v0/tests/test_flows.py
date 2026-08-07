from __future__ import annotations

import dataclasses

import pytest

from kukai.ai_protocol.project_v0 import (
    ModelQueryCommandV0,
    ExceptionPutV0,
    ModulePutV0,
    ProjectApplyError,
    ProjectConflictError,
    ProjectContractError,
    ProjectLimitError,
    ProjectReadCommandV0,
    ReceiptAuthorityError,
    ReceiptRefV0,
    RootPutV0,
    SourcePatchCommandV0,
    create_project_state,
    model_query,
    project_read,
    source_patch,
)
from kukai.design_source import (
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    canonical_bytes,
)
from kukai.design_source.errors import MaterializationError
from kukai.design_source.examples import make_tower_source
from kukai.design_source.materializer import child_instance_id


def _read(state, scope: str, target_id: str | None = None):
    return project_read(state, ProjectReadCommandV0(
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        scope=scope,
        target_id=target_id,
    ))


def _root_with(state, width) -> RootInstanceV0:
    arguments = dict(state.head.root.arguments.items())
    arguments["floor_width"] = width
    return RootInstanceV0(
        instance_id=state.head.root.instance_id,
        module_id=state.head.root.module_id,
        arguments=arguments,
    )


def _patch(state, patch_id, refs, operations, *, base=None):
    return SourcePatchCommandV0(
        project_id=state.project_id,
        base_revision_digest=(
            state.head.revision_digest if base is None else base),
        patch_id=patch_id,
        receipt_refs=tuple(refs),
        operations=tuple(operations),
    )


def _query_all_floor_entities(state, *, limit: int = 7):
    cursor = None
    records = []
    while True:
        transition = model_query(state, ModelQueryCommandV0(
            project_id=state.project_id,
            revision_digest=state.head.revision_digest,
            build_digest=state.build.manifest.build_digest,
            scope="origin",
            filters={"module_id": "mod_typical_floor"},
            limit=limit,
            cursor=cursor,
        ))
        state = transition.state
        records.extend(transition.result.items)
        cursor = transition.result.cursor
        if cursor is None:
            return state, tuple(records)


def test_read_query_patch_read_query_flow_uses_only_new_head(state3) -> None:
    root_read = _read(state3, "root_instance")
    before_query = model_query(root_read.state, ModelQueryCommandV0(
        project_id=root_read.state.project_id,
        revision_digest=root_read.state.head.revision_digest,
        build_digest=root_read.state.build.manifest.build_digest,
        scope="summary",
        filters={},
        limit=1,
    ))
    old_revision = before_query.state.head.revision_digest
    old_build = before_query.state.build.manifest.build_digest
    patched = source_patch(before_query.state, _patch(
        before_query.state,
        "patch_flow_root",
        (root_read.result.receipt.ref, before_query.result.receipt.ref),
        (RootPutV0("widen", _root_with(before_query.state, 36000)),),
    ))

    assert patched.state.head.revision_digest != old_revision
    assert patched.state.build.manifest.build_digest != old_build
    assert patched.state.build_index is not before_query.state.build_index
    manifest_read = _read(patched.state, "manifest")
    after_query = model_query(manifest_read.state, ModelQueryCommandV0(
        project_id=manifest_read.state.project_id,
        revision_digest=manifest_read.state.head.revision_digest,
        build_digest=manifest_read.state.build.manifest.build_digest,
        scope="summary",
        filters={},
        limit=1,
    ))
    assert manifest_read.result.value["revision_digest"] == (
        patched.state.head.revision_digest)
    assert after_query.result.items[0]["build_digest"] == (
        patched.state.build.manifest.build_digest)

    with pytest.raises(ProjectConflictError, match="current-head-only"):
        model_query(after_query.state, ModelQueryCommandV0(
            project_id=after_query.state.project_id,
            revision_digest=old_revision,
            build_digest=old_build,
            scope="summary",
            filters={},
            limit=1,
        ))


def test_old_patch_replays_after_later_present_module_update(state3) -> None:
    root_read = _read(state3, "root_instance")
    original_base = root_read.state.head.revision_digest
    first_command = _patch(
        root_read.state,
        "patch_historical_replay",
        (root_read.result.receipt.ref,),
        (RootPutV0("root", _root_with(root_read.state, 31000)),),
    )
    first = source_patch(root_read.state, first_command)

    module_read = _read(first.state, "module", "mod_typical_floor")
    floor = module_read.state.head.module_map["mod_typical_floor"]
    second = source_patch(module_read.state, _patch(
        module_read.state,
        "patch_present_module_update",
        (module_read.result.receipt.ref,),
        (ModulePutV0("put_present", floor),),
    ))
    assert len(second.state.revisions) == 3
    assert len(second.state.patch_outcomes) == 2

    replay = _patch(
        second.state,
        "patch_historical_replay",
        (root_read.result.receipt.ref,),
        (RootPutV0("root", _root_with(root_read.state, "31000")),),
        base=original_base,
    )
    before = canonical_bytes(second.state.to_data())
    replayed = source_patch(second.state, replay)
    assert replayed.state is second.state
    assert canonical_bytes(second.state.to_data()) == before
    assert canonical_bytes(replayed.result.to_data()) == canonical_bytes(
        first.result.to_data())


def test_stale_extra_receipt_cannot_accompany_current_owner(state3) -> None:
    old_root = _read(state3, "root_instance")
    first = source_patch(old_root.state, _patch(
        old_root.state,
        "patch_make_stale",
        (old_root.result.receipt.ref,),
        (RootPutV0("root", _root_with(old_root.state, 31000)),),
    ))
    current_root = _read(first.state, "root_instance")
    command = _patch(
        current_root.state,
        "patch_with_stale_extra",
        (current_root.result.receipt.ref, old_root.result.receipt.ref),
        (RootPutV0("root", _root_with(current_root.state, 32000)),),
    )
    before = canonical_bytes(current_root.state.to_data())

    with pytest.raises(
        ReceiptAuthorityError, match="every source.patch receipt"
    ) as caught:
        source_patch(current_root.state, command)
    assert caught.value.code == "OWNER_RECEIPT_REQUIRED"
    assert canonical_bytes(current_root.state.to_data()) == before


def test_receipt_dereference_precedes_new_patch_target_preconditions(state3) -> None:
    root_read = _read(state3, "root_instance")
    real = root_read.result.receipt.ref
    forged = ReceiptRefV0(real.receipt_id, "sha256:" + "0" * 64)
    invalid_target = SetInstanceArgumentExceptionV0(
        exception_id="exc_unknown",
        target_instance_id="ins_unknown",
        parameter_id="width",
        expected_value=30000,
        value=36000,
    )
    command = _patch(
        root_read.state,
        "patch_receipt_before_target",
        (forged,),
        (ExceptionPutV0("put", invalid_target),),
    )

    with pytest.raises(ReceiptAuthorityError, match="digest"):
        source_patch(root_read.state, command)


def test_revision_capacity_failure_happens_after_compute_without_state_change(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.patches as patch_module
    import kukai.ai_protocol.project_v0.state as state_module

    root_read = _read(state3, "root_instance")
    before = canonical_bytes(root_read.state.to_data())
    old_index = root_read.state.build_index
    original_apply = patch_module.apply_patch
    original_materialize = patch_module.materialize
    calls = {"apply": 0, "retained": 0}

    def counted_apply(source, request):
        calls["apply"] += 1
        return original_apply(source, request)

    def counted_materialize(source):
        calls["retained"] += 1
        return original_materialize(source)

    monkeypatch.setattr(patch_module, "apply_patch", counted_apply)
    monkeypatch.setattr(patch_module, "materialize", counted_materialize)
    monkeypatch.setattr(state_module, "MAX_REVISIONS", 1)

    with pytest.raises(ProjectLimitError, match="ledger is full"):
        source_patch(root_read.state, _patch(
            root_read.state,
            "patch_capacity",
            (root_read.result.receipt.ref,),
            (RootPutV0("root", _root_with(root_read.state, 31000)),),
        ))
    assert calls == {"apply": 1, "retained": 1}
    assert canonical_bytes(root_read.state.to_data()) == before
    assert root_read.state.build_index is old_index


def test_second_materialization_failure_is_atomic(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.patches as patch_module

    root_read = _read(state3, "root_instance")
    before = canonical_bytes(root_read.state.to_data())

    def fail_retained(_source):
        raise MaterializationError("forced retained-build failure")

    monkeypatch.setattr(patch_module, "materialize", fail_retained)
    with pytest.raises(
        ProjectApplyError, match="forced retained-build failure"
    ) as caught:
        source_patch(root_read.state, _patch(
            root_read.state,
            "patch_second_materialize_failure",
            (root_read.result.receipt.ref,),
            (RootPutV0("root", _root_with(root_read.state, 31000)),),
        ))
    assert caught.value.code == "SOURCE_PATCH_REFUSED"
    assert canonical_bytes(root_read.state.to_data()) == before


def test_result_budget_failure_is_atomic(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.patches as patch_module

    root_read = _read(state3, "root_instance")
    before = canonical_bytes(root_read.state.to_data())
    monkeypatch.setattr(patch_module, "MAX_RESULT_BYTES", 1)

    with pytest.raises(ProjectLimitError, match="result exceeds"):
        source_patch(root_read.state, _patch(
            root_read.state,
            "patch_result_limit",
            (root_read.result.receipt.ref,),
            (RootPutV0("root", _root_with(root_read.state, 31000)),),
        ))
    assert canonical_bytes(root_read.state.to_data()) == before


def test_patch_outcome_rejects_transition_or_target_binding_tamper(state3) -> None:
    root_read = _read(state3, "root_instance")
    patched = source_patch(root_read.state, _patch(
        root_read.state,
        "patch_outcome_binding",
        (root_read.result.receipt.ref,),
        (RootPutV0("root", _root_with(root_read.state, 31000)),),
    ))
    outcome = patched.state.patch_outcomes[0]
    bad_result = dataclasses.replace(
        outcome.result, transition_digest="sha256:" + "0" * 64)
    with pytest.raises(ProjectContractError, match="transition digest"):
        dataclasses.replace(outcome, result=bad_result)

    with pytest.raises(ProjectContractError, match="fields mismatch"):
        dataclasses.replace(outcome, target_modules={
            "ins_fake": {"module_id": "mod_building"},
        })


def test_maximum_128_ordered_patch_operations_are_admitted(state3) -> None:
    module_read = _read(state3, "module", "mod_typical_floor")
    floor = module_read.state.head.module_map["mod_typical_floor"]
    operations = tuple(
        ModulePutV0(f"put_{index}", floor) for index in range(128))

    patched = source_patch(module_read.state, _patch(
        module_read.state,
        "patch_128_ops",
        (module_read.result.receipt.ref,),
        operations,
    ))
    assert patched.state.head.module_map[floor.module_id].module_digest == (
        floor.module_digest)


@pytest.mark.parametrize(
    ("floors", "expected_instances", "expected_entities"),
    ((3, 4, 18), (54, 55, 324)),
)
def test_full_read_query_patch_requery_flow_preserves_complete_census(
    floors: int,
    expected_instances: int,
    expected_entities: int,
) -> None:
    initial = create_project_state(make_tower_source(n_floors=floors))
    manifest = _read(initial, "manifest")
    before_state, before_records = _query_all_floor_entities(manifest.state)
    before_ids = tuple(item["logical_id"] for item in before_records)
    expected_floor_entities = floors * 5

    assert manifest.result.value["instance_count"] == expected_instances
    assert manifest.result.value["entity_count"] == expected_entities
    assert before_state.build.manifest.instance_count == expected_instances
    assert before_state.build.manifest.entity_count == expected_entities
    assert len(before_ids) == len(set(before_ids)) == expected_floor_entities

    target = child_instance_id(
        "ins_building", "call_levels", "floor_instances", "L002")
    owner_requests = (
        ("exception", "exception", "exc_flow_width"),
        ("root", "root_instance", None),
        ("floor", "module", "mod_typical_floor"),
        ("building", "module", "mod_building"),
    )
    refs = []
    owner_state = before_state
    for _label, scope, target_id in owner_requests:
        owner = _read(owner_state, scope, target_id)
        owner_state = owner.state
        assert owner.result.receipt.authority == "OWNER"
        assert owner.result.coverage.state == "COMPLETE"
        refs.append(owner.result.receipt.ref)
    exception = SetInstanceArgumentExceptionV0(
        exception_id="exc_flow_width",
        target_instance_id=target,
        parameter_id="width",
        expected_value=30000,
        value=36000,
    )
    patched = source_patch(owner_state, _patch(
        owner_state,
        f"patch_flow_{floors}",
        refs,
        (ExceptionPutV0("put_width", exception),),
    ))

    assert patched.state.head.revision_digest != owner_state.head.revision_digest
    assert patched.state.build.manifest.build_digest != (
        owner_state.build.manifest.build_digest)
    assert patched.state.build.manifest.instance_count == expected_instances
    assert patched.state.build.manifest.entity_count == expected_entities
    after_manifest = _read(patched.state, "manifest")
    after_state, after_records = _query_all_floor_entities(after_manifest.state)
    after_ids = tuple(item["logical_id"] for item in after_records)

    assert after_manifest.result.value["instance_count"] == expected_instances
    assert after_manifest.result.value["entity_count"] == expected_entities
    assert len(after_ids) == len(set(after_ids)) == expected_floor_entities
    assert after_ids == before_ids
    before_by_id = {
        item["logical_id"]: canonical_bytes({
            key: value for key, value in item.items() if key != "origin"
        })
        for item in before_records
    }
    after_by_id = {
        item["logical_id"]: canonical_bytes({
            key: value for key, value in item.items() if key != "origin"
        })
        for item in after_records
    }
    assert sum(
        before_by_id[logical_id] != after_by_id[logical_id]
        for logical_id in before_ids
    ) == 5
    assert after_state.build.manifest.instance_count == expected_instances
    assert after_state.build.manifest.entity_count == expected_entities
