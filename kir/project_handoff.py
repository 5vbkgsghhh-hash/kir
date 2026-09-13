"""Explicit ownership transfer of an inert evaluated authoring snapshot.

The old definition/recipe remains in the project. No recipe, geometry kernel,
compiler or native runtime is invoked, and no ProjectStore is modified. The
small metadata record identifies a historical handoff, not an evergreen claim
that later explicit edits still equal the source evaluation.
"""
from __future__ import annotations

from dataclasses import replace

from kir.project import (ModuleDefinition, ProjectError, ProjectRevision,
                         _hash, _key, _thaw)


HANDOFF_SCHEMA = "kir-instance-ownership-handoff/1"


class HandoffError(ProjectError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def handoff_instance_to_explicit(project: ProjectRevision, instance_key: str, *,
                                 new_module_key: str, expected_revision: str) -> ProjectRevision:
    """Return one direct child preserving every output, address and input value.

    The caller explicitly selects the snapshot and a NEW module key. Parameters
    become historical inputs, not live generator controls. The new owner is the
    existing ModuleDefinition ``explicit`` variant, not a recipe under a new
    label. Persistence and its expected-head CAS remain the caller's operation.
    Existing metadata is preserved literally; an occupied handoff slot refuses.
    Body-owned outputs are outside this first ownership-transfer subset.
    """
    if type(project) is not ProjectRevision:
        raise HandoffError("invalid_handoff", "expected an exact ProjectRevision")
    # Preserve the Project owner's named RevisionConflict, before constructing
    # any replacement. This checks the supplied value, not a store's current head.
    project._check_revision(expected_revision)
    try:
        _key(instance_key, "instance_key")
        _key(new_module_key, "new_module_key")
    except ProjectError as error:
        raise HandoffError("invalid_handoff", str(error)) from error
    selected = next((item for item in project.instances if item.key == instance_key), None)
    if selected is None:
        raise HandoffError("handoff_instance_missing", "selected instance does not exist")
    if any(module.key == new_module_key for module in project.modules):
        raise HandoffError("handoff_module_exists", "new_module_key must not reuse an existing definition")
    definition = next(module for module in project.modules if module.key == selected.module_key)
    if definition.owner != "sealed_evaluation":
        raise HandoffError("handoff_owner_not_sealed", "only a sealed evaluation can transfer to explicit authoring")
    if "ownership_handoff" in selected.metadata:
        raise HandoffError("handoff_metadata_occupied", "an existing handoff declaration is never overwritten")
    if any(output.geometry is not None for output in selected.outputs):
        raise HandoffError("handoff_body_owned_unsupported", "body-owned outputs retain their existing recipe/asset binding")

    explicit = ModuleDefinition(new_module_key, owner="explicit", recipe=None)
    record = {
        "schema": HANDOFF_SCHEMA,
        "kind": "sealed_evaluation_to_explicit",
        "source": {
            "project_id": project.project_id, "revision_id": project.revision_id,
            "instance_key": selected.key, "instance_snapshot_digest": _hash(selected.to_dict()),
            "module_key": selected.module_key, "module_definition_digest": definition.definition_digest,
            "outputs_digest": _hash([output.to_dict() for output in selected.outputs]),
        },
        "target": {"module_key": explicit.key, "module_definition_digest": explicit.definition_digest,
                   "owner": "explicit"},
        "parameters_role": "historical_inputs_not_generation_controls",
        "claims": {"preserved": "authored_output_payloads_and_order_at_handoff",
                   "recipe_execution": "not_run", "compiler_validation": "not_run",
                   "geometry_evaluation": "not_run", "native_execution": "not_run",
                   "history_persistence": "not_established"},
    }
    replacement = replace(selected, module_key=explicit.key, module_digest=explicit.definition_digest,
                          metadata={**_thaw(selected.metadata), "ownership_handoff": record})
    return project.revise(expected_revision=expected_revision,
                          modules=(*project.modules, explicit),
                          instances=tuple(replacement if item.key == selected.key else item
                                          for item in project.instances))


__all__ = ["HANDOFF_SCHEMA", "HandoffError", "handoff_instance_to_explicit"]
