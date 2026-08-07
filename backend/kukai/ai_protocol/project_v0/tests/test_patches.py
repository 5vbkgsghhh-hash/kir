from __future__ import annotations

import dataclasses

import pytest

from kukai.ai_protocol.project_v0 import (
    ExceptionPutV0,
    ExceptionRemoveV0,
    ModelQueryCommandV0,
    ModulePutV0,
    PatchContradictionError,
    ProjectApplyError,
    ProjectConflictError,
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
    ModuleV0,
    ParameterSpecV0,
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    SourceRevisionV0,
    canonical_bytes,
)
from kukai.design_source.examples import make_tower_source
from kukai.design_source.materializer import child_instance_id


def _read(state, scope: str, target_id: str | None = None):
    return project_read(state, ProjectReadCommandV0(
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        scope=scope,
        target_id=target_id,
    ))


def _collect_reads(state, requests):
    refs = {}
    for label, scope, target_id in requests:
        transition = _read(state, scope, target_id)
        state = transition.state
        refs[label] = transition.result.receipt.ref
    return state, refs


def _command(state, patch_id: str, refs, operations, *, base_digest=None):
    return SourcePatchCommandV0(
        project_id=state.project_id,
        base_revision_digest=(
            state.head.revision_digest if base_digest is None else base_digest),
        patch_id=patch_id,
        receipt_refs=tuple(refs),
        operations=tuple(operations),
    )


def _root_with(state, **changes) -> RootInstanceV0:
    arguments = dict(state.head.root.arguments.items())
    arguments.update(changes)
    return RootInstanceV0(
        instance_id=state.head.root.instance_id,
        module_id=state.head.root.module_id,
        arguments=arguments,
    )


def _floor_target(level_key: str = "L002") -> str:
    return child_instance_id(
        "ins_building", "call_levels", "floor_instances", level_key)


def _exception(
    *,
    exception_id: str = "exc_width",
    target: str | None = None,
    expected=30000,
    value=36000,
) -> SetInstanceArgumentExceptionV0:
    return SetInstanceArgumentExceptionV0(
        exception_id=exception_id,
        target_instance_id=_floor_target() if target is None else target,
        parameter_id="width",
        expected_value=expected,
        value=value,
    )


def _clone_module(module: ModuleV0, module_id: str, *, spare=False) -> ModuleV0:
    parameters = module.parameters
    if spare:
        parameters = (*parameters, ParameterSpecV0("spare", "length"))
    return ModuleV0(
        module_id=module_id,
        parameters=parameters,
        slots=module.slots,
        generator_calls=module.generator_calls,
        label="",
    )


def _exception_owner_reads(state):
    return _collect_reads(state, (
        ("exception", "exception", "exc_width"),
        ("root", "root_instance", None),
        ("floor", "module", "mod_typical_floor"),
        ("building", "module", "mod_building"),
    ))


def test_same_target_root_sequence_normalizes_aliases_and_replays_first(
    state3,
) -> None:
    state, refs = _collect_reads(
        state3, (("root", "root_instance", None),))
    base_digest = state.head.revision_digest
    command = _command(state, "patch_root_sequence", refs.values(), (
        RootPutV0("root_1", _root_with(state, floor_width=31000)),
        RootPutV0("root_2", _root_with(state, floor_width=32000)),
    ))

    applied = source_patch(state, command)

    assert applied.state.head.root.arguments["floor_width"] == "32000"
    assert applied.state.revisions == (state.head, applied.state.head)
    assert applied.state.build_index is not state.build_index
    assert applied.result.base_revision_digest == base_digest
    assert applied.result.revision_digest == applied.state.head.revision_digest
    replay_command = _command(
        applied.state,
        "patch_root_sequence",
        refs.values(),
        (
            RootPutV0("root_1", _root_with(state, floor_width="31000")),
            RootPutV0("root_2", _root_with(state, floor_width="32000")),
        ),
        base_digest=base_digest,
    )
    replayed = source_patch(applied.state, replay_command)
    assert replayed.state is applied.state
    assert replayed.result is not applied.result
    assert canonical_bytes(replayed.result.to_data()) == canonical_bytes(
        applied.result.to_data())

    changed = _command(
        applied.state,
        "patch_root_sequence",
        refs.values(),
        (
            RootPutV0("root_1", _root_with(state, floor_width="31000")),
            RootPutV0("root_2", _root_with(state, floor_width="32001")),
        ),
        base_digest=base_digest,
    )
    before = canonical_bytes(applied.state.to_data())
    with pytest.raises(PatchContradictionError):
        source_patch(applied.state, changed)
    assert canonical_bytes(applied.state.to_data()) == before


def test_new_stale_patch_conflicts_after_replay_lookup(state3) -> None:
    state, refs = _collect_reads(
        state3, (("root", "root_instance", None),))
    base_digest = state.head.revision_digest
    applied = source_patch(state, _command(
        state,
        "patch_first",
        refs.values(),
        (RootPutV0("root", _root_with(state, floor_width=31000)),),
    ))
    stale = _command(
        applied.state,
        "patch_new_stale",
        refs.values(),
        (RootPutV0("root", _root_with(state, floor_width=32000)),),
        base_digest=base_digest,
    )

    with pytest.raises(ProjectConflictError, match="current-head-only"):
        source_patch(applied.state, stale)


def test_exception_create_remove_sequence_tracks_union_and_alias_replay(
    state3,
) -> None:
    state, refs = _exception_owner_reads(state3)
    base_digest = state.head.revision_digest
    command = _command(state, "patch_exception_ephemeral", refs.values(), (
        ExceptionPutV0("put", _exception(expected=30000, value=36000)),
        ExceptionRemoveV0("remove", "exc_width"),
    ))

    applied = source_patch(state, command)

    assert applied.state.head.exceptions == ()
    assert applied.state.head.source_digest == state.head.source_digest
    assert (
        applied.state.build.manifest.build_digest
        == state.build.manifest.build_digest
    )
    target_binding = applied.state.patch_outcomes[0].target_modules[_floor_target()]
    floor = state.head.module_map["mod_typical_floor"]
    assert dict(target_binding.items()) == {
        "base_module_digest": floor.module_digest,
        "module_id": floor.module_id,
    }

    replay = _command(
        applied.state,
        "patch_exception_ephemeral",
        refs.values(),
        (
            ExceptionPutV0(
                "put", _exception(expected="30000", value="36000")),
            ExceptionRemoveV0("remove", "exc_width"),
        ),
        base_digest=base_digest,
    )
    replayed = source_patch(applied.state, replay)
    assert replayed.state is applied.state
    assert replayed.result.semantic_patch_digest == (
        applied.result.semantic_patch_digest)


@pytest.mark.parametrize("missing", ["exception", "root", "floor", "building"])
def test_exception_patch_requires_every_exact_owner_in_pre_ancestry(
    state3,
    missing: str,
) -> None:
    state, refs = _exception_owner_reads(state3)
    del refs[missing]
    command = _command(state, f"patch_missing_{missing}", refs.values(), (
        ExceptionPutV0("put", _exception()),
    ))
    before = canonical_bytes(state.to_data())

    with pytest.raises(ReceiptAuthorityError):
        source_patch(state, command)
    assert canonical_bytes(state.to_data()) == before


def test_exception_create_update_remove_across_revisions(state3) -> None:
    state, refs = _exception_owner_reads(state3)
    created = source_patch(state, _command(
        state,
        "patch_exception_create",
        refs.values(),
        (ExceptionPutV0("create", _exception(value=36000)),),
    ))
    assert created.state.head.exception_map["exc_width"].value == "36000"

    state, refs = _exception_owner_reads(created.state)
    updated = source_patch(state, _command(
        state,
        "patch_exception_update",
        refs.values(),
        (ExceptionPutV0("update", _exception(value=42000)),),
    ))
    assert updated.state.head.exception_map["exc_width"].value == "42000"

    state, refs = _exception_owner_reads(updated.state)
    removed = source_patch(state, _command(
        state,
        "patch_exception_remove",
        refs.values(),
        (ExceptionRemoveV0("remove", "exc_width"),),
    ))
    assert removed.state.head.exceptions == ()
    assert len(removed.state.revisions) == 4
    assert len(removed.state.patch_outcomes) == 3
    assert removed.state.build.manifest.build_digest == (
        state3.build.manifest.build_digest)


def test_module_create_then_update_same_target_uses_local_expected_before(
    state3,
) -> None:
    state, refs = _collect_reads(
        state3, (("new", "module", "mod_floor_copy"),))
    floor = state.head.module_map["mod_typical_floor"]
    created = _clone_module(floor, "mod_floor_copy")
    updated = _clone_module(floor, "mod_floor_copy", spare=True)

    applied = source_patch(state, _command(
        state,
        "patch_module_sequence",
        refs.values(),
        (
            ModulePutV0("create", created),
            ModulePutV0("update", updated),
        ),
    ))

    final = applied.state.head.module_map["mod_floor_copy"]
    assert final.module_digest == updated.module_digest
    assert "spare" in final.parameter_map
    assert applied.state.build.manifest.entity_ids == (
        state.build.manifest.entity_ids)
    assert applied.state.build.manifest.entity_count == (
        state.build.manifest.entity_count)


def test_future_exception_target_is_explicitly_staged_across_revisions(
    state3,
) -> None:
    state, refs = _collect_reads(
        state3, (("root", "root_instance", None),))
    new_keys = (*state.head.root.arguments["level_keys"], "L004")
    future_target = _floor_target("L004")
    command = _command(state, "patch_future_target", refs.values(), (
        RootPutV0("grow", _root_with(state, level_keys=new_keys)),
        ExceptionPutV0("future", _exception(target=future_target)),
    ))
    before = canonical_bytes(state.to_data())

    with pytest.raises(ProjectApplyError, match="later revision"):
        source_patch(state, command)
    assert canonical_bytes(state.to_data()) == before


def test_post_build_target_module_switch_is_refused_atomically(state3) -> None:
    state, refs = _collect_reads(state3, (
        ("new_module", "module", "mod_floor_copy"),
        ("exception", "exception", "exc_width"),
        ("root", "root_instance", None),
        ("floor", "module", "mod_typical_floor"),
        ("building", "module", "mod_building"),
    ))
    floor_copy = _clone_module(
        state.head.module_map["mod_typical_floor"], "mod_floor_copy")
    command = _command(state, "patch_target_module_switch", refs.values(), (
        ModulePutV0("create_floor_copy", floor_copy),
        RootPutV0("switch_floor_module", _root_with(
            state, floor_module="mod_floor_copy")),
        ExceptionPutV0("track_target", _exception()),
        ExceptionRemoveV0("untrack_target", "exc_width"),
    ))
    before = canonical_bytes(state.to_data())

    with pytest.raises(ProjectApplyError, match="changed module"):
        source_patch(state, command)
    assert canonical_bytes(state.to_data()) == before


def _state_with_alternate_building_module():
    base = make_tower_source(n_floors=3)
    alternate = _clone_module(
        base.module_map["mod_building"], "mod_building_alt")
    source = SourceRevisionV0.genesis(
        project_id=base.project_id,
        package_lock_digest=base.package_lock_digest,
        modules=(*base.modules, alternate),
        root=base.root,
        author_id="agent",
    )
    return create_project_state(source)


def test_post_build_changed_ancestry_requires_new_prestate_owner() -> None:
    initial = _state_with_alternate_building_module()
    state, refs = _exception_owner_reads(initial)
    alternate_root = RootInstanceV0(
        instance_id=state.head.root.instance_id,
        module_id="mod_building_alt",
        arguments=state.head.root.arguments,
    )
    command = _command(state, "patch_changed_ancestry", refs.values(), (
        RootPutV0("switch_root_module", alternate_root),
        ExceptionPutV0("track_target", _exception()),
        ExceptionRemoveV0("untrack_target", "exc_width"),
    ))
    before = canonical_bytes(state.to_data())

    with pytest.raises(ReceiptAuthorityError, match="mod_building_alt"):
        source_patch(state, command)
    assert canonical_bytes(state.to_data()) == before

    state, refs = _exception_owner_reads(initial)
    alternate_owner = _read(state, "module", "mod_building_alt")
    state = alternate_owner.state
    refs["alternate"] = alternate_owner.result.receipt.ref
    alternate_root = RootInstanceV0(
        instance_id=state.head.root.instance_id,
        module_id="mod_building_alt",
        arguments=state.head.root.arguments,
    )
    accepted = source_patch(state, _command(
        state,
        "patch_changed_ancestry_authorized",
        refs.values(),
        (
            RootPutV0("switch_root_module", alternate_root),
            ExceptionPutV0("track_target", _exception()),
            ExceptionRemoveV0("untrack_target", "exc_width"),
        ),
    ))
    assert accepted.state.head.root.module_id == "mod_building_alt"


def test_query_receipt_cannot_authorize_module_write(state3) -> None:
    queried = model_query(state3, ModelQueryCommandV0(
        project_id=state3.project_id,
        revision_digest=state3.head.revision_digest,
        build_digest=state3.build.manifest.build_digest,
        scope="summary",
        filters={},
        limit=1,
    ))
    floor = queried.state.head.module_map["mod_typical_floor"]
    command = _command(
        queried.state,
        "patch_query_only",
        (queried.result.receipt.ref,),
        (ModulePutV0("put", floor),),
    )

    with pytest.raises(ReceiptAuthorityError):
        source_patch(queried.state, command)


def test_unknown_or_digest_substituted_receipt_is_refused(state3) -> None:
    state, refs = _collect_reads(
        state3, (("root", "root_instance", None),))
    real = refs["root"]
    floor = state.head.module_map["mod_typical_floor"]
    forged = ReceiptRefV0(real.receipt_id, "sha256:" + "0" * 64)
    command = _command(
        state,
        "patch_forged_receipt",
        (forged,),
        (ModulePutV0("put", floor),),
    )

    with pytest.raises(ReceiptAuthorityError, match="digest"):
        source_patch(state, command)

    unknown = dataclasses.replace(
        forged,
        receipt_id="rr_" + "f" * 40,
        receipt_digest="sha256:" + "f" * 64,
    )
    command = _command(
        state,
        "patch_unknown_receipt",
        (unknown,),
        (ModulePutV0("put", floor),),
    )
    with pytest.raises(ReceiptAuthorityError, match="not in the host ledger"):
        source_patch(state, command)


def test_late_materialization_failure_preserves_exact_old_state(state3) -> None:
    state, refs = _collect_reads(
        state3, (("root", "root_instance", None),))
    command = _command(state, "patch_invalid_geometry", refs.values(), (
        RootPutV0("valid_first", _root_with(state, floor_width=31000)),
        RootPutV0("invalid_later", _root_with(state, floor_width=-1)),
    ))
    before = canonical_bytes(state.to_data())

    with pytest.raises(ProjectApplyError):
        source_patch(state, command)
    assert canonical_bytes(state.to_data()) == before


def test_apply_and_retained_materialization_each_run_once(
    state3,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import kukai.ai_protocol.project_v0.patches as project_patches
    import kukai.design_source.materializer as design_materializer

    state, refs = _collect_reads(
        state3, (("new", "module", "mod_floor_copy"),))
    module = _clone_module(
        state.head.module_map["mod_typical_floor"], "mod_floor_copy")
    original = design_materializer.materialize
    calls = {"apply_validation": 0, "retained": 0}

    def apply_validation(source):
        calls["apply_validation"] += 1
        return original(source)

    def retained(source):
        calls["retained"] += 1
        return original(source)

    monkeypatch.setattr(design_materializer, "materialize", apply_validation)
    monkeypatch.setattr(project_patches, "materialize", retained)

    source_patch(state, _command(
        state,
        "patch_double_materialize",
        refs.values(),
        (ModulePutV0("create", module),),
    ))

    assert calls == {"apply_validation": 1, "retained": 1}
