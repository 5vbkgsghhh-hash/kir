"""Inert selected-instance program with explicit authored dependency closure.

This is not a native execution scope or a whole-project validation. Selectors
requiring backend grounding stay intact. Geometry-owned dependencies require
explicit materialization, never substitution with their display operation.
"""
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from kir.project import ProjectError, ProjectRevision
from kir.project_diff import _dependencies, _outputs


class ProjectSelectionError(ProjectError):
    code = "project_selection_unresolved"


SELECTION_POLICY = "authored_dependency_closure/1"


@dataclass(frozen=True, slots=True, init=False)
class ProjectSelection:
    """Inert authored addresses, not compilation or native execution evidence."""
    project: ProjectRevision
    instance_keys: tuple[str, ...]
    output_ids: tuple[str, ...]
    project_source_indices: tuple[int, ...]

    def __init__(self, *args, **kwargs):
        raise TypeError("use select_project_instances with the full authored project")

    def to_dict(self):
        return {"policy": SELECTION_POLICY, "root_instance_keys": list(self.instance_keys),
                "source_output_count": len(self.project.addressed_outputs())}


def select_project_instances(project: ProjectRevision, *, instance_keys: Sequence[str]) -> ProjectSelection:
    """Resolve the existing registry dependency closure in original source order.

    Roots are canonicalized to authored instance order; duplicate/unknown roots
    refuse. Bodies remain addresses here and require the geometry owner later.
    Macros/groups retain the existing explicit unsupported-selection refusal.
    """
    if type(project) is not ProjectRevision:
        raise ProjectSelectionError("expected exact ProjectRevision")
    if (not isinstance(instance_keys, Sequence) or isinstance(instance_keys, (str, bytes))
            or not instance_keys or any(type(key) is not str for key in instance_keys)
            or len(set(instance_keys)) != len(instance_keys)):
        raise ProjectSelectionError("expected distinct nonempty instance roots")
    roots = set(instance_keys)
    canonical = tuple(item.key for item in project.instances if item.key in roots)
    if len(canonical) != len(roots):
        raise ProjectSelectionError("selected instance is absent")
    operations, addresses = _outputs(project)
    selected = {oid for oid, address in addresses.items() if address["instance_key"] in roots}
    edges, issues = _dependencies(project, operations)
    parents = defaultdict(list)
    for edge in edges:
        parents[edge["dependent"]].append(edge["source"])
    pending = list(selected)
    while pending:
        for parent in parents[pending.pop()]:
            if parent not in selected:
                selected.add(parent)
                pending.append(parent)
    deferred = {"selector_requires_grounding", "grid_address_requires_resolution"}
    relevant = [issue for issue in issues if issue["op_id"] is None or
                (issue["op_id"] in selected and issue["kind"] not in deferred)]
    if relevant:
        raise ProjectSelectionError(f"explicit dependency closure is unresolved: {relevant}")
    result = object.__new__(ProjectSelection)
    for name, value in {"project": project, "instance_keys": canonical,
        "output_ids": tuple(oid for oid in operations if oid in selected),
        "project_source_indices": tuple(i for i, oid in enumerate(operations) if oid in selected)}.items():
        object.__setattr__(result, name, value)
    return result


def validate_project_selection(project: ProjectRevision, selection: ProjectSelection) -> None:
    """Recheck a supplied typed selection; frozen Python objects aren't authority."""
    if (type(selection) is not ProjectSelection or type(project) is not ProjectRevision
            or type(getattr(selection, "project", None)) is not ProjectRevision):
        raise ProjectSelectionError("expected full project and exact ProjectSelection")
    if (type(getattr(selection, "instance_keys", None)) is not tuple
            or type(getattr(selection, "output_ids", None)) is not tuple
            or type(getattr(selection, "project_source_indices", None)) is not tuple
            or any(type(index) is not int for index in selection.project_source_indices)):
        raise ProjectSelectionError("selection requires immutable roots/addresses and exact integer positions")
    expected = select_project_instances(project, instance_keys=selection.instance_keys)
    if (selection.project.dumps() != project.dumps() or selection.instance_keys != expected.instance_keys
            or selection.output_ids != expected.output_ids
            or selection.project_source_indices != expected.project_source_indices):
        raise ProjectSelectionError("selection differs from the full authored source/closure")


def selected_instance_program(project: ProjectRevision, instance_key: str) -> dict:
    """Detached operations in authored order; caller must invoke the planner.

    Uses the same registry-slot analysis as authored diff/merge, not recursive
    scanning for arbitrary dictionaries that happen to contain ``by:ref``.
    Unrelated drafts and external bodies are not interpreted as dependencies.
    """
    if type(project) is not ProjectRevision:
        raise ProjectSelectionError("expected exact ProjectRevision")
    if type(instance_key) is not str:
        raise ProjectSelectionError("selected instance is absent")
    selection = select_project_instances(project, instance_keys=(instance_key,))
    selected = set(selection.output_ids)
    operations, _ = _outputs(project)
    if any(oid in selected for _, _, oid in project.geometry_references()):
        raise ProjectSelectionError("selected outputs/dependencies require explicit geometry materialization")
    # 🔴 D-1: the envelope carries the project's STABLE IDENTITY. The compiler
    # builds the type-ownership address from it (`kir:{lineage}:{op_id}`),
    # and the address stops shifting when a neighboring wall is edited.
    # `project_id` lives across all revisions — unlike `revision_id`, which
    # changes with every edit and would produce exactly the defect being
    # fixed.
    return {"ir_version": project.ir_version, "intent": project.intent,
            "lineage": project.project_id,
            "ops": [operation for oid, operation in operations.items() if oid in selected]}
