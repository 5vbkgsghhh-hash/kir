"""Receipt-authorized, replay-safe AP02-K source.patch implementation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kukai.design_source import (
    BuildResultV0,
    DesignPatchV0,
    ModuleV0,
    PatchRequestV0,
    PutExceptionOpV0,
    PutModuleOpV0,
    PutRootInstanceOpV0,
    RemoveExceptionOpV0,
    RootInstanceV0,
    SetInstanceArgumentExceptionV0,
    SourceRevisionV0,
    apply_patch,
    canonical_bytes,
    canonical_digest,
    materialize,
    root_digest,
)
from kukai.design_source.errors import DesignSourceError

from .contracts import (
    ExceptionPutV0,
    ExceptionRemoveV0,
    ModulePutV0,
    ReadReceiptV0,
    RootPutV0,
    SourcePatchCommandV0,
    SourcePatchResultV0,
    frozen_object,
)
from .errors import (
    PatchContradictionError,
    ProjectApplyError,
    ProjectConflictError,
    ProjectContractError,
    ProjectLimitError,
    ReceiptAuthorityError,
)
from .receipts import require_owner_receipt, resolve_receipt_refs
from .schemas import MAX_RESULT_BYTES, SEMANTIC_PATCH_SCHEMA
from .state import (
    KernelTransitionV0,
    PatchOutcomeRecordV0,
    ProjectStateV0,
    evolve_state,
)


_STAGED_TARGET_MESSAGE = (
    "exception target is not in the retained base BuildResult; stage graph "
    "changes and address the new instance in a later revision"
)


@dataclass(frozen=True, slots=True)
class _NormalizedPatchV0:
    semantic_data: Any
    semantic_digest: str
    design_operations: tuple[Any, ...]
    target_modules: Any
    module_targets: tuple[str, ...]
    exception_targets: tuple[str, ...]
    has_root_operation: bool


def _clone_result(result: SourcePatchResultV0) -> SourcePatchResultV0:
    return SourcePatchResultV0(
        patch_id=result.patch_id,
        semantic_patch_digest=result.semantic_patch_digest,
        transition_digest=result.transition_digest,
        project_id=result.project_id,
        base_revision_digest=result.base_revision_digest,
        revision_digest=result.revision_digest,
        source_digest=result.source_digest,
        build_digest=result.build_digest,
    )


def _target_context_from_build(state: ProjectStateV0) -> dict[str, dict[str, str]]:
    modules = state.head.module_map
    context: dict[str, dict[str, str]] = {}
    for instance in state.build.instances:
        module = modules.get(instance.module_id)
        if module is None or module.module_digest != instance.module_digest:
            raise ProjectContractError(
                "retained BuildInstance does not bind its base source module")
        context[instance.instance_id] = {
            "base_module_digest": module.module_digest,
            "module_id": module.module_id,
        }
    return context


def _historical_target_context(
    base: SourceRevisionV0,
    stored: Any,
) -> dict[str, dict[str, str]]:
    context: dict[str, dict[str, str]] = {}
    for instance_id, binding in stored.items():
        if set(binding) != {"base_module_digest", "module_id"}:
            raise PatchContradictionError(
                "stored replay target context has an invalid exact shape")
        module_id = binding["module_id"]
        module = base.module_map.get(module_id)
        if module is None or module.module_digest != binding["base_module_digest"]:
            raise PatchContradictionError(
                "stored replay target context does not bind its base module")
        context[instance_id] = {
            "base_module_digest": binding["base_module_digest"],
            "module_id": module_id,
        }
    return context


def _normalize_root(
    raw: RootInstanceV0,
    modules: dict[str, ModuleV0],
) -> RootInstanceV0:
    module = modules.get(raw.module_id)
    if module is None:
        raise ProjectApplyError(
            f"root references unknown module {raw.module_id!r}")
    specs = module.parameter_map
    if set(raw.arguments) != set(specs):
        missing = sorted(set(specs) - set(raw.arguments))
        extra = sorted(set(raw.arguments) - set(specs))
        raise ProjectApplyError(
            f"root arguments mismatch; missing={missing}, extra={extra}")
    arguments = {
        parameter_id: specs[parameter_id].normalize(raw.arguments[parameter_id])
        for parameter_id in specs
    }
    for spec in module.parameters:
        if spec.kind == "module_ref" and arguments[spec.parameter_id] not in modules:
            raise ProjectApplyError(
                f"root argument {spec.parameter_id!r} references unknown module "
                f"{arguments[spec.parameter_id]!r}")
    return RootInstanceV0(
        instance_id=raw.instance_id,
        module_id=raw.module_id,
        arguments=arguments,
    )


def _normalize_exception(
    raw: SetInstanceArgumentExceptionV0,
    modules: dict[str, ModuleV0],
    target_context: dict[str, dict[str, str]],
    *,
    replay: bool,
) -> SetInstanceArgumentExceptionV0:
    binding = target_context.get(raw.target_instance_id)
    if binding is None:
        if replay:
            raise PatchContradictionError(
                "replayed patch references a target absent from stored context")
        raise ProjectApplyError(_STAGED_TARGET_MESSAGE)
    module = modules.get(binding["module_id"])
    if module is None:
        raise ProjectApplyError(
            "exception target module is absent after preceding patch operations")
    spec = module.parameter_map.get(raw.parameter_id)
    if spec is None:
        raise ProjectApplyError(
            f"exception parameter {raw.parameter_id!r} is absent from target module")
    return SetInstanceArgumentExceptionV0(
        exception_id=raw.exception_id,
        target_instance_id=raw.target_instance_id,
        parameter_id=raw.parameter_id,
        expected_value=spec.normalize(raw.expected_value),
        value=spec.normalize(raw.value),
    )


def _remember_exception_target(
    exception: SetInstanceArgumentExceptionV0,
    target_context: dict[str, dict[str, str]],
    used_context: dict[str, dict[str, str]],
    *,
    replay: bool,
) -> None:
    binding = target_context.get(exception.target_instance_id)
    if binding is None:
        if replay:
            raise PatchContradictionError(
                "replayed patch needs an exception target absent from stored context")
        raise ProjectApplyError(_STAGED_TARGET_MESSAGE)
    used_context[exception.target_instance_id] = dict(binding)


def _normalize_patch(
    base: SourceRevisionV0,
    command: SourcePatchCommandV0,
    target_context: dict[str, dict[str, str]],
    *,
    replay: bool,
) -> _NormalizedPatchV0:
    modules = dict(base.module_map.items())
    exceptions = dict(base.exception_map.items())
    root = base.root
    normalized_operations = []
    design_operations = []
    used_context: dict[str, dict[str, str]] = {}
    module_targets: set[str] = set()
    exception_targets: set[str] = set()
    has_root_operation = False

    try:
        for operation in command.operations:
            if type(operation) is ModulePutV0:
                module_id = operation.module.module_id
                current = modules.get(module_id)
                design_operations.append(PutModuleOpV0(
                    op_id=operation.op_id,
                    module=operation.module,
                    expected_digest=(
                        None if current is None else current.module_digest),
                ))
                normalized_operations.append(operation.to_data())
                modules[module_id] = operation.module
                module_targets.add(module_id)
                continue

            if type(operation) is RootPutV0:
                normalized_root = _normalize_root(operation.root, modules)
                normalized = RootPutV0(operation.op_id, normalized_root)
                design_operations.append(PutRootInstanceOpV0(
                    op_id=operation.op_id,
                    root=normalized_root,
                    expected_digest=root_digest(root),
                ))
                normalized_operations.append(normalized.to_data())
                root = normalized_root
                has_root_operation = True
                continue

            if type(operation) is ExceptionPutV0:
                exception_id = operation.exception.exception_id
                current = exceptions.get(exception_id)
                if current is not None:
                    _remember_exception_target(
                        current, target_context, used_context, replay=replay)
                normalized_exception = _normalize_exception(
                    operation.exception,
                    modules,
                    target_context,
                    replay=replay,
                )
                _remember_exception_target(
                    normalized_exception,
                    target_context,
                    used_context,
                    replay=replay,
                )
                normalized = ExceptionPutV0(
                    operation.op_id, normalized_exception)
                design_operations.append(PutExceptionOpV0(
                    op_id=operation.op_id,
                    exception=normalized_exception,
                    expected_digest=(
                        None if current is None else current.exception_digest),
                ))
                normalized_operations.append(normalized.to_data())
                exceptions[exception_id] = normalized_exception
                exception_targets.add(exception_id)
                continue

            if type(operation) is ExceptionRemoveV0:
                current = exceptions.get(operation.exception_id)
                if current is None:
                    raise ProjectApplyError(
                        f"exception {operation.exception_id!r} does not exist")
                _remember_exception_target(
                    current, target_context, used_context, replay=replay)
                design_operations.append(RemoveExceptionOpV0(
                    op_id=operation.op_id,
                    exception_id=operation.exception_id,
                    expected_digest=current.exception_digest,
                ))
                normalized_operations.append(operation.to_data())
                del exceptions[operation.exception_id]
                exception_targets.add(operation.exception_id)
                continue

            raise ProjectContractError("patch operation escaped command admission")
    except PatchContradictionError:
        raise
    except ProjectApplyError:
        raise
    except DesignSourceError as exc:
        raise ProjectApplyError(str(exc)) from exc

    semantic_data = frozen_object({
        "base_revision_digest": command.base_revision_digest,
        "operations": tuple(normalized_operations),
        "project_id": command.project_id,
        "receipt_refs": tuple(item.to_data() for item in command.receipt_refs),
        "schema": SEMANTIC_PATCH_SCHEMA,
    }, "normalized semantic patch")
    return _NormalizedPatchV0(
        semantic_data=semantic_data,
        semantic_digest=canonical_digest(
            "kir.ai-semantic-patch.v0", semantic_data),
        design_operations=tuple(design_operations),
        target_modules=frozen_object(
            used_context, "normalized exception target modules"),
        module_targets=tuple(sorted(module_targets)),
        exception_targets=tuple(sorted(exception_targets)),
        has_root_operation=has_root_operation,
    )


def _require_current_receipts(
    state: ProjectStateV0,
    receipts: tuple[ReadReceiptV0, ...],
) -> None:
    for receipt in receipts:
        if (
            receipt.project_id != state.project_id
            or receipt.revision_digest != state.head.revision_digest
            or receipt.build_digest != state.build.manifest.build_digest
        ):
            raise ReceiptAuthorityError(
                "every source.patch receipt must bind the retained current head")


def _require_root_owner(
    state: ProjectStateV0,
    receipts: tuple[ReadReceiptV0, ...],
) -> None:
    require_owner_receipt(
        receipts,
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope="root_instance",
        selector={},
        present=True,
        object_digest=root_digest(state.head.root),
    )


def _require_module_owner(
    state: ProjectStateV0,
    receipts: tuple[ReadReceiptV0, ...],
    module_id: str,
) -> None:
    module = state.head.module_map.get(module_id)
    require_owner_receipt(
        receipts,
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope="module",
        selector={"module_id": module_id},
        present=module is not None,
        object_digest=None if module is None else module.module_digest,
    )


def _require_exception_owner(
    state: ProjectStateV0,
    receipts: tuple[ReadReceiptV0, ...],
    exception_id: str,
) -> None:
    exception = state.head.exception_map.get(exception_id)
    require_owner_receipt(
        receipts,
        project_id=state.project_id,
        revision_digest=state.head.revision_digest,
        build_digest=state.build.manifest.build_digest,
        scope="exception",
        selector={"exception_id": exception_id},
        present=exception is not None,
        object_digest=(
            None if exception is None else exception.exception_digest),
    )


def _ancestry_modules_for(
    source: SourceRevisionV0,
    build: BuildResultV0,
    target_instance_id: str,
) -> tuple[tuple[str, str], ...]:
    instances = {item.instance_id: item for item in build.instances}
    current = instances.get(target_instance_id)
    if current is None:
        raise ProjectApplyError(_STAGED_TARGET_MESSAGE)
    ancestry: dict[str, str] = {}
    seen: set[str] = set()
    while current is not None:
        if current.instance_id in seen:
            raise ProjectContractError("retained BuildInstance ancestry contains a cycle")
        seen.add(current.instance_id)
        module = source.module_map.get(current.module_id)
        if module is None or module.module_digest != current.module_digest:
            raise ProjectContractError(
                "retained BuildInstance ancestry does not bind source module")
        existing = ancestry.get(module.module_id)
        if existing is not None and existing != module.module_digest:
            raise ProjectContractError("one ancestry binds conflicting module digests")
        ancestry[module.module_id] = module.module_digest
        if current.parent_instance_id is None:
            current = None
        else:
            parent = instances.get(current.parent_instance_id)
            if parent is None:
                raise ProjectContractError(
                    "retained BuildInstance ancestry has a missing parent")
            current = parent
    return tuple(sorted(ancestry.items()))


def _authorize_patch(
    state: ProjectStateV0,
    normalized: _NormalizedPatchV0,
    receipts: tuple[ReadReceiptV0, ...],
) -> None:
    for module_id in normalized.module_targets:
        _require_module_owner(state, receipts, module_id)
    for exception_id in normalized.exception_targets:
        _require_exception_owner(state, receipts, exception_id)
    if normalized.has_root_operation or normalized.target_modules:
        _require_root_owner(state, receipts)
    closure_modules: dict[str, str] = {}
    for target_instance_id in normalized.target_modules:
        for module_id, module_digest in _ancestry_modules_for(
            state.head, state.build, target_instance_id):
            existing = closure_modules.get(module_id)
            if existing is not None and existing != module_digest:
                raise ProjectContractError(
                    "exception ancestry union binds conflicting module digests")
            closure_modules[module_id] = module_digest
    for module_id in sorted(closure_modules):
        _require_module_owner(state, receipts, module_id)


def _authorize_post_targets(
    state: ProjectStateV0,
    candidate: SourceRevisionV0,
    retained_build: BuildResultV0,
    normalized: _NormalizedPatchV0,
    receipts: tuple[ReadReceiptV0, ...],
) -> None:
    instances = {item.instance_id: item for item in retained_build.instances}
    post_modules: set[str] = set()
    for target_instance_id, binding in normalized.target_modules.items():
        target = instances.get(target_instance_id)
        if target is None:
            raise ProjectApplyError(_STAGED_TARGET_MESSAGE)
        if target.module_id != binding["module_id"]:
            raise ProjectApplyError(
                "exception target changed module in the candidate build; stage "
                "the structural change and exception change across revisions")
        post_modules.update(
            module_id
            for module_id, _module_digest in _ancestry_modules_for(
                candidate, retained_build, target_instance_id)
        )
    for module_id in sorted(post_modules):
        _require_module_owner(state, receipts, module_id)


def _replay(
    state: ProjectStateV0,
    command: SourcePatchCommandV0,
    outcome: PatchOutcomeRecordV0,
) -> KernelTransitionV0:
    if command.base_revision_digest != outcome.base_revision_digest:
        raise PatchContradictionError(
            "patch_id was already used with another base revision")
    base = state.revision_map.get(outcome.base_revision_digest)
    if base is None:
        raise PatchContradictionError(
            "stored patch outcome has no retained base revision")
    try:
        context = _historical_target_context(base, outcome.target_modules)
        normalized = _normalize_patch(
            base, command, context, replay=True)
    except PatchContradictionError:
        raise
    except (ProjectContractError, ProjectApplyError, DesignSourceError) as exc:
        raise PatchContradictionError(
            "replayed patch cannot reproduce its normalized semantics") from exc
    if (
        normalized.semantic_digest != outcome.semantic_patch_digest
        or canonical_bytes(normalized.semantic_data)
        != canonical_bytes(outcome.semantic_patch_data)
        or canonical_bytes(normalized.target_modules)
        != canonical_bytes(outcome.target_modules)
    ):
        raise PatchContradictionError(
            "patch_id was already used with different normalized arguments")
    return KernelTransitionV0(state, _clone_result(outcome.result))


def source_patch(
    state: ProjectStateV0,
    command: SourcePatchCommandV0,
) -> KernelTransitionV0:
    """Apply one exact current-head patch or replay its retained outcome."""

    if type(state) is not ProjectStateV0:
        raise ProjectContractError("source_patch requires exact ProjectStateV0")
    if type(command) is not SourcePatchCommandV0:
        raise ProjectContractError("source_patch requires exact SourcePatchCommandV0")
    if command.project_id != state.project_id:
        raise ProjectConflictError("source.patch crosses project authority")

    prior = state.outcome_map.get(command.patch_id)
    if prior is not None:
        return _replay(state, command, prior)
    if command.base_revision_digest != state.head.revision_digest:
        raise ProjectConflictError("source.patch is current-head-only")

    receipts = resolve_receipt_refs(state, command.receipt_refs)
    _require_current_receipts(state, receipts)
    normalized = _normalize_patch(
        state.head,
        command,
        _target_context_from_build(state),
        replay=False,
    )
    _authorize_patch(state, normalized, receipts)
    request = PatchRequestV0(
        patch_id=command.patch_id,
        base_revision_digest=command.base_revision_digest,
        claimed_author_id="offline_protocol_v0",
        read_receipts=tuple(item.receipt_digest for item in receipts),
        patch=DesignPatchV0(normalized.design_operations),
    )
    try:
        candidate = apply_patch(state.head, request)
        retained_build = materialize(candidate)
    except DesignSourceError as exc:
        raise ProjectApplyError(str(exc), details={
            "design_source_code": exc.code,
        }) from exc
    _authorize_post_targets(
        state, candidate, retained_build, normalized, receipts)

    transition_digest = canonical_digest("kir.ai-source-transition.v0", {
        "base_revision_digest": state.head.revision_digest,
        "build_digest": retained_build.manifest.build_digest,
        "project_id": state.project_id,
        "revision_digest": candidate.revision_digest,
        "semantic_patch_digest": normalized.semantic_digest,
        "source_digest": candidate.source_digest,
    })
    result = SourcePatchResultV0(
        patch_id=command.patch_id,
        semantic_patch_digest=normalized.semantic_digest,
        transition_digest=transition_digest,
        project_id=state.project_id,
        base_revision_digest=state.head.revision_digest,
        revision_digest=candidate.revision_digest,
        source_digest=candidate.source_digest,
        build_digest=retained_build.manifest.build_digest,
    )
    if len(canonical_bytes(result.to_data())) > MAX_RESULT_BYTES:
        raise ProjectLimitError("source.patch result exceeds 2MB")
    outcome = PatchOutcomeRecordV0(
        patch_id=command.patch_id,
        base_revision_digest=state.head.revision_digest,
        semantic_patch_digest=normalized.semantic_digest,
        semantic_patch_data=normalized.semantic_data,
        target_modules=normalized.target_modules,
        result=result,
    )
    next_state = evolve_state(
        state,
        head=candidate,
        build=retained_build,
        outcome=outcome,
    )
    return KernelTransitionV0(next_state, _clone_result(result))


__all__ = ["source_patch"]
