"""Addressable differences between authored projects, not native update commands.

Payload equality and conservative dependency impact are separate axes. Neither
an unchanged payload nor absence of a discovered explicit ref proves unchanged
Revit realization. This report does not ground selectors, execute recipes,
validate a whole KIR program, transform units, or rewrite reference dictionaries.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Mapping

from kir import faceref, relate, spec
from kir.project import ProjectError, ProjectRevision, _canonical, _object, _thaw
from kir.registry_base import IR_VERSION

#: The name of the live source-address field in the refinement record
#: (`kir-schematic-refinement/2`).
_LIVE_ADDRESS = "live_instance_key"


DIFF_SCHEMA = "kir-authoring-diff/1"


@dataclass(frozen=True, slots=True)
class ProjectDiff:
    """Immutable report; ``to_dict`` returns detached JSON, never a write plan."""

    _data: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_data", _object(self._data, "project_diff"))

    @property
    def added(self) -> tuple[str, ...]:
        return self._data["added"]

    @property
    def removed(self) -> tuple[str, ...]:
        return self._data["removed"]

    @property
    def changed(self) -> tuple[str, ...]:
        return self._data["changed"]

    @property
    def affected(self) -> tuple[str, ...]:
        return self._data["affected"]

    @property
    def unchanged(self) -> tuple[str, ...]:
        return self._data["unchanged"]

    def to_dict(self) -> dict:
        return _thaw(self._data)


def _equal(before: Any, after: Any) -> bool:
    # Python equality collapses True/1/1.0 and signed zero; authoring JSON does not.
    return _canonical(before) == _canonical(after)


def _fields_changed(before: dict, after: dict) -> dict:
    return {key: {"before": before.get(key), "after": after.get(key)}
            for key in sorted(before.keys() | after.keys())
            if key not in before or key not in after
            or not _equal(before[key], after[key])}


def _order(before: list[str], after: list[str]) -> dict:
    """Relative order of retained IDs; insertion alone does not reorder them."""
    old, new = set(before), set(after)
    common_before = [key for key in before if key in new]
    common_after = [key for key in after if key in old]
    positions = {key: i for i, key in enumerate(common_after)}
    reordered = set()
    maximum = -1
    for key in common_before:
        position = positions[key]
        if maximum > position:
            reordered.add(key)
        maximum = max(maximum, position)
    minimum = len(common_before)
    for key in reversed(common_before):
        position = positions[key]
        if minimum < position:
            reordered.add(key)
        minimum = min(minimum, position)
    return {"before": before, "after": after,
            "changed": before != after,
            "reordered": [key for key in common_after if key in reordered]}


def _collection(before: list[dict], after: list[dict]) -> dict:
    old, new = {x["key"]: x for x in before}, {x["key"]: x for x in after}
    added = [key for key in new if key not in old]
    removed = [key for key in old if key not in new]
    changed = [key for key in new if key in old and not _equal(old[key], new[key])]
    changed_set = set(changed)
    return {"added": added, "removed": removed, "changed": changed,
            "unchanged": [key for key in new if key in old and key not in changed_set],
            "entries": ([{"key": key, "before": None, "after": new[key]} for key in added]
                        + [{"key": key, "before": old[key], "after": None} for key in removed]
                        + [{"key": key, "fields": _fields_changed(old[key], new[key])}
                           for key in changed]),
            "order": _order(list(old), list(new))}


def _module_provenance_reasons(old: Any, new: Any) -> set[str]:
    """Why the MODULE PASSPORT changed: the owner, and each pin field,
    separately.

    🔴 WHY. `instance.module_digest` is a hash of the whole definition,
    and before 07.09.2026 a recipe change reached the outputs as exactly
    one word, `instance_module_digest_changed`: measurement showed it
    firing BOTH on an edit to the recipe's code AND on a change to
    `environment_digest` alone. Registry P03 requires "recipe changes
    named separately", so the reason is named by the field that actually
    diverged. The digest itself stays: it is an address, not a reason.

    Nothing is executed: `source` is compared by its own `source_digest`.
    """
    if old is None or new is None:
        return set()
    reasons = set()
    if old.owner != new.owner:
        reasons.add("module_owner_changed")
    if old.recipe is None and new.recipe is None:
        return reasons
    if old.recipe is None:
        reasons.add("module_recipe_added")
        return reasons
    if new.recipe is None:
        reasons.add("module_recipe_removed")
        return reasons
    for attribute, name in (("source_digest", "source"),
                            ("environment_digest", "environment_digest"),
                            ("entrypoint", "entrypoint"),
                            ("dependencies", "dependencies")):
        if not _equal(_thaw(getattr(old.recipe, attribute)),
                      _thaw(getattr(new.recipe, attribute))):
            reasons.add(f"module_recipe_{name}_changed")
    return reasons


def _body_signature(operation: dict, geometry: Any) -> str:
    # `id` is derived from the address keys, and so a renamed output gets
    # a DIFFERENT one; what is compared is what the author wrote, together
    # with the body owning the geometry.
    return _canonical([{key: value for key, value in operation.items() if key != "id"},
                       geometry])


def _rekeyed(old: dict, new: dict, old_geometry: dict, new_geometry: dict,
             old_addresses: dict, new_addresses: dict,
             added: list[str], removed: list[str]) -> list[dict]:
    """A "lost here — gained there" pair under a BYTE-FOR-BYTE EQUAL
    payload.

    🔴 WHAT THIS IS NOT. An output's identity is derived from keys
    (`project.output_id`), so renaming a key STAYS a
    `removed`+`added` pair — this decision is fixed by the instrument
    `test_named_output_rename_is_remove_add_not_guessed_identity_rewrite`
    and is not revisited here. Only the PAIR is named, by both addresses,
    and only where it is unambiguous: if the exact same text left one key
    and arrived at exactly one other. Two identical bodies renamed at the
    same time give TWO candidates on each side — then there is no pair,
    and the diff does not guess.
    """
    groups: dict[str, tuple[list[str], list[str]]] = defaultdict(lambda: ([], []))
    for oid in removed:
        groups[_body_signature(old[oid], old_geometry.get(oid))][0].append(oid)
    for oid in added:
        groups[_body_signature(new[oid], new_geometry.get(oid))][1].append(oid)
    pairs = []
    for gone, born in groups.values():
        if len(gone) != 1 or len(born) != 1:
            continue
        source, target = old_addresses[gone[0]], new_addresses[born[0]]
        pairs.append({"before_instance_key": source["instance_key"],
                      "before_output_key": source["output_key"], "before_op_id": gone[0],
                      "after_instance_key": target["instance_key"],
                      "after_output_key": target["output_key"], "after_op_id": born[0]})
    return sorted(pairs, key=lambda pair: (pair["before_instance_key"], pair["before_output_key"]))


def _outputs(project: ProjectRevision) -> tuple[dict, dict]:
    operations, addresses = {}, {}
    for instance, output, identifier in project.addressed_outputs():
        operation = {**_thaw(output.operation), "id": identifier}
        operations[identifier] = operation
        addresses[identifier] = {"instance_key": instance.key, "output_key": output.key}
    return operations, addresses


def _dependencies(project: ProjectRevision, operations: dict) -> tuple[list, list]:
    """Mirror the planner's typed slots, reusing its element-address walker.

    compiler.plan_program currently has no public selector-ref iterator. Its
    slots (compiler.py DAG pass) are sel/target_w, refs_w and face.of; these are
    read from ParamSpec, not searched in arbitrary JSON. Group members have a
    different scope and macros are not registry operations: neither is guessed.
    """
    edges, issues = [], []
    positions = {oid: index for index, oid in enumerate(operations)}
    if project.ir_version != IR_VERSION:
        return [], [{"op_id": None, "kind": "uninterpreted_ir_version",
                     "value": project.ir_version, "supported": IR_VERSION}]

    def issue(oid: str, field: str, kind: str, value: Any = None) -> None:
        issues.append({"op_id": oid, "field": field, "kind": kind, "value": value})

    def reference(oid: str, field: str, target: Any, param=None) -> None:
        if not isinstance(target, str) or not target:
            issue(oid, field, "malformed_reference", target)
            return
        # The compiler's typed selector normalization strips ref whitespace.
        target = target.strip()
        if not target:
            issue(oid, field, "malformed_reference", target)
            return
        edges.append({"source": target, "dependent": oid, "field": field})
        if target not in operations:
            issue(oid, field, "unresolved_reference", target)
            return
        if positions[target] >= positions[oid]:
            issue(oid, field, "reference_not_earlier", target)
        producer = spec.OPS.get(operations[target]["op"])
        if producer is None:
            issue(oid, field, "producer_contract_unknown", target)
            return
        # result_for assumes a validated enum; persisted projects also contain
        # drafts. Invalid discriminators must not silently select its fallback.
        if producer.result_by_param is not None:
            discriminator, _ = producer.result_by_param
            discriminator_spec = next(p for p in producer.params if p.name == discriminator)
            value = operations[target].get(discriminator, discriminator_spec.default)
            if not isinstance(value, str) or value not in discriminator_spec.choices:
                issue(oid, field, "producer_contract_unresolved", target)
                return
        try:
            result = producer.result_for(operations[target])
        except (TypeError, ValueError):
            issue(oid, field, "producer_contract_unreadable", target)
            return
        if not result.referenceable or (param is not None and not param.accepts_reference(
                result.reference_kind)):
            issue(oid, field, "incompatible_reference_kind", target)

    def selector(oid: str, field: str, value: Any, param) -> None:
        if not isinstance(value, dict):
            if value is not None:
                issue(oid, field, "malformed_selector", value)
            return
        if value.get("by") == "ref":
            reference(oid, field, value.get("value"), param)
        else:
            issue(oid, field, "selector_requires_grounding", value.get("by"))

    for oid, op in operations.items():
        operation_spec = spec.OPS.get(op["op"])
        if operation_spec is None:
            issue(oid, "op", "unknown_or_macro_operation", op["op"])
            continue
        for param in operation_spec.params:
            value = op.get(param.name)
            if param.kind in ("sel", "target_w"):
                selector(oid, param.name, value, param)
            elif param.kind == "refs_w" and isinstance(value, list):
                for index, item in enumerate(value):
                    field = f"{param.name}[{index}]"
                    if item is None:
                        issue(oid, field, "malformed_selector")
                    elif isinstance(item, dict) and item.get("by") == faceref.BY_FACE:
                        if item.get("of") is None:
                            issue(oid, field + ".of", "malformed_selector")
                        else:
                            selector(oid, field + ".of", item.get("of"), param)
                    else:
                        selector(oid, field, item, param)
            elif param.kind == "refs_w" and value is not None:
                issue(oid, param.name, "malformed_reference_list", value)
            elif param.kind == "member_ops":
                issue(oid, param.name, "nested_scope_not_expanded")
        element_refs = relate.element_address_refs(op)
        for field, target in element_refs:
            reference(oid, field + ".at_element", target)
        resolved_address_fields = {field for field, _ in element_refs}
        for field in relate.addressable_params(op["op"]):
            value = op.get(field)
            if relate.is_element_address(value) and field not in resolved_address_fields:
                address_selector = value.get("at_element")
                if address_selector is None:
                    issue(oid, field + ".at_element", "malformed_selector")
                else:
                    selector(oid, field + ".at_element", address_selector, None)
            elif relate.is_address(value) and not relate.is_element_address(value):
                issue(oid, field, "grid_address_requires_resolution")
    return edges, issues


def _refinement_edges(project: ProjectRevision) -> list:
    """ONE edge: "the refinement's source" -> each of its descendants.

    🔴 WHY THIS EDGE EXISTS AND WHY IT DID NOT BEFORE. The scheduler
    slots above are references INSIDE the program (`sel`, `refs_w`,
    `face.of`). The relationship "this wall descends from that concept
    volume over there" is not a reference: the program's section has no
    concept-volume construct at all. So the diff had nowhere to learn it
    from, and the recon measurement showed this as a number: editing
    `atrium_radius_mm` AFTER refinement produced `changed 0 · affected 1 ·
    unchanged 23` — twenty-one descendants stayed silent. The edge is read
    from the AUTHOR'S OWN record (`metadata["refinement"]`), not derived
    from geometry: here, provenance is the author's claim, and it stays
    that way.

    Both `/1` and `/2` are read. For `/1`, the source lives in a past
    revision, and this snapshot may not have its output at all — then the
    edge simply does not arise (no source, nothing to propagate), silently
    and without invention. Transitivity is provided by the shared
    traversal below: the same traversal carries `dependency_changed` from
    a descendant to whoever references that descendant.
    """
    edges = []
    addresses = {(instance.key, output.key): identifier
                 for instance, output, identifier in project.addressed_outputs()}
    for instance in project.instances:
        record = _thaw(instance.metadata.get("refinement")) if instance.metadata else None
        if not isinstance(record, dict) or "source" not in record or "members" not in record:
            continue
        source = record["source"]
        if not isinstance(source, dict):
            continue
        # 🔴 THE LIVE ADDRESS IS TAKEN IF IT IS DECLARED. The historical
        # key (`instance_key`) says WHERE THE SOURCE WAS at the moment of
        # output; after refinement it is no longer there, and a lookup by
        # it produced ZERO edges — measured 07.09.2026, exactly the
        # silence this edge is being introduced to fix.
        # `live_instance_key` says where that same output sits NOW.
        origin = addresses.get((source.get(_LIVE_ADDRESS, source.get("instance_key")),
                                source.get("output_key")))
        if origin is None:
            continue
        for member in record["members"]:
            if not isinstance(member, dict) or "output_key" not in member:
                continue
            owner = member.get("instance_key", instance.key)
            dependent = addresses.get((owner, member["output_key"]))
            if dependent is not None and dependent != origin:
                edges.append({"source": origin, "dependent": dependent,
                              "field": "refinement.source"})
    return edges


def diff_projects(before: ProjectRevision, after: ProjectRevision) -> ProjectDiff:
    """Compare two snapshots of the same project without executing either.

    ``affected`` means a retained equal-payload output needs reconsideration;
    it does not assert that geometry actually changed. ``unchanged`` excludes
    affected outputs, and only concerns this authoring/reference analysis.
    Context changes conservatively require review, never unit conversion.
    """
    if not isinstance(before, ProjectRevision) or not isinstance(after, ProjectRevision):
        raise ProjectError("diff_projects requires two ProjectRevision values")
    if before.project_id != after.project_id:
        raise ProjectError("cannot diff revisions from different projects")
    old, old_addresses = _outputs(before)
    new, new_addresses = _outputs(after)
    old_geometry = {oid: output.geometry.to_dict()
                    for _, output, oid in before.geometry_references()}
    new_geometry = {oid: output.geometry.to_dict()
                    for _, output, oid in after.geometry_references()}
    added = [oid for oid in new if oid not in old]
    removed = [oid for oid in old if oid not in new]
    changed = [oid for oid in new if oid in old and (
        not _equal(old[oid], new[oid]) or not _equal(old_geometry.get(oid), new_geometry.get(oid)))]
    changed_set = set(changed)
    equal = [oid for oid in new if oid in old and oid not in changed_set]
    operation_order = _order(list(old), list(new))
    modules = _collection([x.to_dict() for x in before.modules],
                          [x.to_dict() for x in after.modules])
    instances = _collection([x.to_dict() for x in before.instances],
                            [x.to_dict() for x in after.instances])
    # Output bodies have their own addressable records below; avoid repeating
    # complete old/new bodies inside every changed instance.
    for entry in instances["entries"]:
        if "fields" in entry and "outputs" in entry["fields"]:
            output_delta = _collection(entry["fields"]["outputs"]["before"],
                                       entry["fields"]["outputs"]["after"])
            entry["fields"]["outputs"] = {
                key: value for key, value in output_delta.items() if key != "entries"}
        for side in ("before", "after"):
            if entry.get(side) is not None:
                entry[side] = {**entry[side], "outputs": [x["key"] for x in entry[side]["outputs"]]}
    project_changes = _fields_changed(
        {key: getattr(before, key) for key in ("intent", "metadata", "ir_version", "parent_revision", "schema")},
        {key: getattr(after, key) for key in ("intent", "metadata", "ir_version", "parent_revision", "schema")})

    reasons: dict[str, set[str]] = defaultdict(set)
    for oid in added + removed + changed:
        if not _equal(old.get(oid), new.get(oid)):
            reasons[oid].add("operation_payload_changed")
        if not _equal(old_geometry.get(oid), new_geometry.get(oid)):
            reasons[oid].add("geometry_source_changed")
    for oid in operation_order["reordered"]:
        reasons[oid].add("operation_order_changed")
    rekeyed = _rekeyed(old, new, old_geometry, new_geometry,
                       old_addresses, new_addresses, added, removed)
    for pair in rekeyed:
        reasons[pair["before_op_id"]].add("output_rekeyed")
        reasons[pair["after_op_id"]].add("output_rekeyed")
    old_modules = {module.key: module for module in before.modules}
    new_modules = {module.key: module for module in after.modules}
    old_instances = {x.key: x for x in before.instances}
    new_instances = {x.key: x for x in after.instances}
    instance_outputs = defaultdict(set)
    for oid, address in {**old_addresses, **new_addresses}.items():
        instance_outputs[address["instance_key"]].add(oid)
    changed_parameters: dict[str, list[str]] = {}
    for key in old_instances.keys() & new_instances.keys():
        old_instance, new_instance = old_instances[key], new_instances[key]
        context = [field for field in ("module_key", "module_digest", "parameters", "metadata")
                   if not _equal(getattr(old_instance, field), getattr(new_instance, field))]
        # The reason "the recipe changed" comes from the DEFINITION of the
        # module the instance is bound to: the digest itself does not name
        # it.
        provenance = _module_provenance_reasons(old_modules.get(old_instance.module_key),
                                                new_modules.get(new_instance.module_key))
        if "parameters" in context:
            # 🔴 THE PARAMETER'S NAME IS THE ONLY THING KNOWN HERE. The
            # author's model does NOT declare which output a given
            # parameter reads (`ModuleInstance`: "Parameters are retained
            # inputs, not live bindings"), and there is no `depends_on`
            # registry for parameters. So the scope stays conservative —
            # ALL of the instance's outputs — and the unknown is named:
            # the names of the changed parameters, plus an explicit
            # caveat in `analysis.limitations`. Narrowing the scope by
            # guesswork ("the name does not appear in the operation's
            # body") would mean passing off a reference that was not
            # found as proven independence.
            changed_parameters[key] = sorted(
                name for name in _thaw(old_instance.parameters).keys() | _thaw(new_instance.parameters).keys()
                if not _equal(_thaw(old_instance.parameters).get(name),
                              _thaw(new_instance.parameters).get(name)))
        if context or provenance:
            for oid in instance_outputs[key]:
                reasons[oid].update("instance_" + field + "_changed" for field in context)
                reasons[oid].update(provenance)
    if set(project_changes) - {"parent_revision"}:
        for oid in old.keys() | new.keys():
            reasons[oid].add("project_context_changed")

    old_edges, old_issues = _dependencies(before, old)
    new_edges, new_issues = _dependencies(after, new)
    old_edges += _refinement_edges(before)
    new_edges += _refinement_edges(after)
    if reasons:
        for issue in old_issues + new_issues:
            identifiers = (issue["op_id"],) if issue["op_id"] is not None else old.keys() | new.keys()
            for oid in identifiers:
                reasons[oid].add("dependency_analysis_incomplete")
    downstream: dict[str, set[str]] = defaultdict(set)
    for edge in old_edges + new_edges:
        downstream[edge["source"]].add(edge["dependent"])
    visited = set(reasons)
    queue = deque(reasons)
    while queue:
        for dependent in downstream.get(queue.popleft(), ()):
            reasons[dependent].add("dependency_changed")
            if dependent not in visited:
                visited.add(dependent)
                queue.append(dependent)
    affected = [oid for oid in equal if oid in visited]
    unchanged = [oid for oid in equal if oid not in visited]
    outputs = []
    for oid in list(new) + removed:
        status = ("added" if oid not in old else "removed" if oid not in new
                  else "changed" if oid in changed_set else "unchanged")
        address = new_addresses.get(oid, old_addresses.get(oid))
        record = {"op_id": oid, **address,
                  "payload_status": status,
                  "impact": "reconsider" if oid in visited else "no_explicit_impact_found",
                  "reasons": sorted(reasons.get(oid, ()))}
        if address["instance_key"] in changed_parameters:
            record["changed_parameters"] = changed_parameters[address["instance_key"]]
        if status != "unchanged":
            record.update(before=old.get(oid), after=new.get(oid))
            if oid in old_geometry or oid in new_geometry:
                record.update(geometry_before=old_geometry.get(oid), geometry_after=new_geometry.get(oid))
        outputs.append(record)
    return ProjectDiff({
        "schema": DIFF_SCHEMA, "scope": "authoring_only",
        "project_id": before.project_id, "base_revision": before.revision_id,
        "target_revision": after.revision_id,
        "added": added, "removed": removed, "changed": changed,
        "affected": affected, "unchanged": unchanged, "rekeyed": rekeyed,
        "outputs": outputs,
        "operation_order": operation_order, "modules": modules, "instances": instances,
        "project_changes": project_changes,
        "dependencies": {"before": old_edges, "after": new_edges},
        "dependency_issues": {"before": old_issues, "after": new_issues},
        "analysis": {"semantic_validation": "not_run", "native_execution": "not_run",
                     "explicit_reference_analysis_complete": not old_issues and not new_issues,
                     "limitations": [
                         "Impact is conservative authoring review, not an actual geometry-change verdict.",
                         "Implicit spatial, catalog and backend side-effect dependencies are not proved.",
                         "Metadata units/frames are compared verbatim; no coordinates are converted.",
                         "Instance parameters declare no per-output dependency: a parameter edit "
                         "conservatively reconsiders every output of that instance.",
                         "A rename is named only for an unambiguous byte-equal removed/added pair; "
                         "output identity stays key-derived, so a rekey remains removed plus added.",
                         "This report cannot be executed as a safe native update subset."]},
    })


__all__ = ["DIFF_SCHEMA", "ProjectDiff", "diff_projects"]
