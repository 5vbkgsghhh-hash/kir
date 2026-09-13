"""Fresh association of authored snapshots with one prepared execution input.

No storage, native parsing, recipe execution or transport occurs here. The
materialization owner establishes its program/plan contract; this seam binds
that exact value to project/output/instance identities and the prepared plan.
Serialization retains assertions, never reconstructs a fresh binding object.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib

from kir.geometry_materialization import GeometryMaterialization
from kir.macros import MACRO_OPS
from kir.project import (PROJECT_SCHEMA, PROJECT_SCHEMA_V2, ProjectError, ProjectRevision,
                         _canonical, _digest, _fields, _hash, _key, _object, _thaw, output_id)
from kir.revit_connector import PreparedExecution
from kir.project_selection import SELECTION_POLICY, select_project_instances, validate_project_selection

#: Plan evidence that carries a signed native lineage. Local on purpose: this
#: reader judges retained records and must not follow a future live constant.
_LINEAGED_PLAN_SCHEMA = "kir-planned-program/5"


SUBMISSION_SCHEMA = "kir-submitted-project-binding/1"
SELECTED_SUBMISSION_SCHEMA = "kir-submitted-project-binding/2"
_CLAIMS = {"association": "matched_supplied_snapshots_and_prepared_input",
    "project_persistence": "not_established", "recipe_execution": "not_established",
    "kernel_execution": "not_established", "native_execution": "not_established",
    "dispatch_state": "not_recorded", "retry_permission": "none", "engineering_acceptance": "not_established",
    "native_element_mapping": "not_created", "macro_provenance": "source_operation_not_nested_field_history"}
_SELECTED_CLAIMS = {**_CLAIMS, "publication_scope": "selected_dependency_closure_only"}


class ProjectSubmissionError(ProjectError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def _require(condition, code, message):
    if not condition:
        raise ProjectSubmissionError(code, message)


def _compiled_claim(evidence):
    """One summary of the existing plan contract, shared by fresh/read paths."""
    payload = evidence["payload"]
    return {"op_id": payload["id"], "op": payload["op"], "payload_digest": _hash(payload),
            "contract_digest": evidence["contract_digest"], "result": evidence["result"],
            "nested_contract_count": len(evidence["nested_contracts"]),
            "nested_contracts_digest": _hash(evidence["nested_contracts"])}


@dataclass(frozen=True, slots=True, init=False)
class SubmittedProjectBinding:
    """Factory-only in-process association; no from_dict/loads or execute API."""
    digest: str
    _payload: object = field(repr=False)

    def __init__(self, *args, **kwargs):
        raise TypeError("use bind_project_submission with actual project/materialization/preparation")

    def to_dict(self) -> dict:
        return {**_thaw(self._payload), "submission_digest": self.digest}

    def dumps(self) -> str:
        return _canonical(self.to_dict())


def bind_project_submission(project: ProjectRevision, materialized: GeometryMaterialization,
                            prepared: PreparedExecution) -> SubmittedProjectBinding:
    """Bind exact values, including 1:N macro origins and instance provenance.

    No inverse association is inferred from source hashes or stable output IDs.
    The caller chooses this snapshot; equal executable geometry can belong to
    different authored revisions. This does not prove the snapshot is saved,
    that a recipe/kernel ran, or that an execution was sent or committed.
    """
    return _bind_project_submission(project, materialized, prepared, selected=False)


def bind_selected_project_submission(project: ProjectRevision, materialized: GeometryMaterialization,
                                     prepared: PreparedExecution) -> SubmittedProjectBinding:
    """Associate an explicit materialized closure with its FULL source revision.

    Uses the same mapping algebra and factory-only result as whole-project /1.
    A selection covering every output still names the distinct /2 profile.
    """
    return _bind_project_submission(project, materialized, prepared, selected=True)


def _bind_project_submission(project, materialized, prepared, *, selected):
    _require(type(project) is ProjectRevision and type(materialized) is GeometryMaterialization
             and type(prepared) is PreparedExecution, "submission_input_required",
             "expected exact ProjectRevision, GeometryMaterialization and fresh PreparedExecution values")
    _require((materialized.selection is not None) is selected, "submission_profile_mismatch",
             "whole and selected materialization require their explicit submission factory")
    _require(_canonical(project.to_dict()) == _canonical(materialized.project.to_dict()),
             "submission_project_mismatch", "materialization belongs to a different exact project snapshot")
    plan = materialized.planned
    _require(_canonical(plan.to_evidence_dict()) == _canonical(prepared.planned.to_evidence_dict())
             and _canonical(plan.units) == _canonical(prepared.planned.units),
             "submission_plan_mismatch", "prepared plan/provenance/units differs from materialization")
    _require(isinstance(prepared.source, str) and hashlib.sha256(prepared.source.encode("utf-8")).hexdigest()
             == prepared.source_sha256, "submission_source_mismatch", "prepared full source does not match its digest")
    if prepared.grounded is not None:
        _require(_canonical(prepared.grounded.planned.to_evidence_dict()) == _canonical(plan.to_evidence_dict())
                 and _canonical(prepared.grounded.planned.units) == _canonical(plan.units),
                 "submission_plan_mismatch", "grounded evidence names another parent plan")

    full_addresses = project.addressed_outputs()
    if selected:
        validate_project_selection(project, materialized.selection)
        project_indices = materialized.selection.project_source_indices
        addresses = tuple(full_addresses[index] for index in project_indices)
    else:
        addresses = full_addresses
    program = materialized.to_program()
    operations = program.get("ops")
    _require(isinstance(operations, list) and len(operations) == len(addresses),
             "submission_output_mismatch", "materialized operation count differs from named outputs")
    _require(plan.source_op_count == len(addresses), "submission_origin_mismatch", "plan source count differs from authored outputs")
    expected_program = {"ir_version": project.ir_version, "intent": project.intent,
                        "lineage": project.project_id, "ops": []}
    by_body = {}
    for row in materialized.sources:
        oid = row.get("op_id")
        _require(isinstance(oid, str) and oid not in by_body, "submission_body_mismatch", "duplicate or malformed body sidecar address")
        by_body[oid] = row
    expected_bodies = {oid for _, output, oid in addresses if output.geometry is not None}
    _require(set(by_body) == expected_bodies, "submission_body_mismatch", "body sidecars do not exactly cover body-owned outputs")
    outputs, compiled_by_source = [], [[] for _ in addresses]
    for index, ((instance, output, oid), operation) in enumerate(zip(addresses, operations, strict=True)):
        _require(isinstance(operation, dict), "submission_output_mismatch", "materialized operation is not an object")
        expected_op = {**_thaw(output.operation), "id": oid}
        row = {"source_index": index, "instance_key": instance.key, "module_key": instance.module_key,
               "output_key": output.key, "output_id": oid, "source_op": output.operation["op"],
               "authored_output_digest": _hash(output.to_dict()), "materialized_op_digest": _hash(operation),
               "compiled_ops": compiled_by_source[index]}
        if selected:
            row["project_source_index"] = project_indices[index]
        if output.geometry is not None:
            sidecar = by_body[oid]
            _require("mesh" in operation and sidecar.get("source_bundle_sha256") == output.geometry.bundle_sha256
                     and sidecar.get("source_body_sha256") == output.geometry.body_sha256
                     and sidecar.get("mesh_sha256") == _hash(operation["mesh"]),
                     "submission_body_mismatch", "body descriptor, sidecar or materialized mesh digest differs")
            expected_op["mesh"] = operation["mesh"]
            row["body"] = {"descriptor": output.geometry.to_dict(), "mesh_digest": _hash(operation["mesh"]),
                           "materialization_sidecar_digest": _hash(sidecar)}
        _require(_canonical(operation) == _canonical(expected_op), "submission_output_mismatch",
                 "materialization changed an authored field, address or output order")
        expected_program["ops"].append(expected_op)
        outputs.append(row)
    _require(_canonical(program) == _canonical(expected_program), "submission_output_mismatch", "materialized envelope differs from project")

    seen = set()
    for planned_op in plan.ops:
        origin = planned_op.provenance
        index = origin.source_index
        _require(type(index) is int and 0 <= index < len(addresses), "submission_origin_mismatch", "compiled source index is outside authored outputs")
        source_op = operations[index]
        macro = source_op["op"] if source_op["op"] in MACRO_OPS else None
        _require(origin.source_id == addresses[index][2] and origin.source_op == source_op["op"]
                 and origin.macro_name == macro, "submission_origin_mismatch", "compiled provenance names a different source operation")
        if macro is None:
            _require(planned_op.op_id == source_op["id"] and planned_op.op_name == source_op["op"],
                     "submission_origin_mismatch", "non-macro operation changed its output identity")
        if addresses[index][1].geometry is not None:
            _require(_canonical(planned_op.to_dict().get("mesh")) == _canonical(source_op.get("mesh")),
                     "submission_body_mismatch", "prepared plan mesh differs from materialized body representation")
        _require(planned_op.op_id not in seen, "submission_origin_mismatch", "compiled operation has multiple owners")
        seen.add(planned_op.op_id)
        evidence = planned_op.to_evidence_dict()
        compiled_by_source[index].append(_compiled_claim(evidence))
    _require(all(compiled_by_source), "submission_origin_mismatch", "an authored output has no compiled source coverage")

    payload = {"schema": SELECTED_SUBMISSION_SCHEMA if selected else SUBMISSION_SCHEMA,
        "project": {"project_id": project.project_id, "schema": project.schema, "revision_id": project.revision_id},
        "instances": [{"instance_key": item.key, "module_key": item.module_key,
                       "instance_snapshot_digest": _hash(item.to_dict()), "module_definition_digest": item.module_digest}
                      for item in project.instances],
        "outputs": outputs, "materialization_digest": materialized.to_dict()["materialization_digest"],
        "materialized_program_digest": _hash(program), "plan_digest": plan.plan_digest,
        "planned_units_digest": _hash(plan.units),
        "grounded_evidence_digest": prepared.grounded.ground_digest if prepared.grounded is not None else None,
        "execution": prepared.binding_dict(),
        "claims": dict(_SELECTED_CLAIMS if selected else _CLAIMS)}
    if selected:
        payload["selection"] = materialized.selection.to_dict()
    binding = object.__new__(SubmittedProjectBinding)
    object.__setattr__(binding, "_payload", _object(payload, "submitted_project_binding"))
    object.__setattr__(binding, "digest", _hash(payload))
    return binding


def validate_submission_source(project: ProjectRevision, submission, *, selection_policy="current") -> None:
    """Recheck retained /1 or /2 association against the actual FULL source.

    Call after validate_submission_claims/Archive validation. This adds source
    evidence absent from the archive: instance snapshots, original addresses,
    authored payloads and exact dependency closure for NEW admission (current).
    Historical reads use retained: verify original addresses and complete root
    output coverage, without invoking today's registry/dependency semantics.
    Retained association is NOT a fresh closure proof. The materialized program
    checksum is source-verifiable only when every selected output is ordinary;
    body meshes remain outside this source-only check. No compilation, recipes,
    BRep derivation or transport; success never reconstructs fresh binding.
    """
    if isinstance(submission, dict) and submission.get("schema") == "kir-submitted-project-binding/3":
        from kir.staged_submission import validate_staged_submission_source
        return validate_staged_submission_source(project, submission, selection_policy=selection_policy)
    code = "submission_project_mismatch"
    try:
        _require(type(selection_policy) is str and selection_policy in ("current", "retained"),
                 code, "selection_policy must be current or retained")
        _require(type(project) is ProjectRevision, code, "expected exact full ProjectRevision")
        _require(submission["schema"] in (SUBMISSION_SCHEMA, SELECTED_SUBMISSION_SCHEMA), code, "unknown submission profile")
        _require(submission["project"] == {"project_id": project.project_id, "schema": project.schema,
                                          "revision_id": project.revision_id}, code, "full source revision differs")
        expected_instances = [{"instance_key": item.key, "module_key": item.module_key,
            "instance_snapshot_digest": _hash(item.to_dict()), "module_definition_digest": item.module_digest}
            for item in project.instances]
        _require(_canonical(submission["instances"]) == _canonical(expected_instances), code, "full instance ownership differs")
        full_addresses = project.addressed_outputs()
        selected = submission["schema"] == SELECTED_SUBMISSION_SCHEMA
        if selected:
            declared = _fields(submission["selection"], {"policy", "root_instance_keys", "source_output_count"}, "selection")
            roots = declared["root_instance_keys"]
            _require(declared["policy"] == SELECTION_POLICY
                     and type(declared["source_output_count"]) is int
                     and declared["source_output_count"] == len(full_addresses)
                     and type(roots) is list and bool(roots) and all(type(key) is str for key in roots),
                     code, "source selection declaration differs")
            root_set = set(roots)
            _require(len(root_set) == len(roots)
                     and roots == [item.key for item in project.instances if item.key in root_set],
                     code, "source root identity/order differs")
            if selection_policy == "current":
                choice = select_project_instances(project, instance_keys=roots)
                _require(_canonical(declared) == _canonical(choice.to_dict()), code, "source selection differs")
                indices = choice.project_source_indices
            else:
                # The archived selected order is historical data. Re-expanding
                # current registry rules here would make old evidence unreadable.
                indices = tuple(row["project_source_index"] for row in submission["outputs"])
                _require(bool(indices) and all(type(index) is int and 0 <= index < len(full_addresses) for index in indices)
                         and tuple(sorted(set(indices))) == indices, code, "retained source positions differ")
                required = {index for index, (instance, _, _) in enumerate(full_addresses) if instance.key in root_set}
                _require(required <= set(indices), code, "retained selection omits a declared root output")
        else:
            _require("selection" not in submission, code, "whole profile cannot carry a selection")
            indices = tuple(range(len(full_addresses)))
        _require(len(submission["outputs"]) == len(indices), code, "selected source coverage differs")
        ordinary_operations = []
        for dense, (index, row) in enumerate(zip(indices, submission["outputs"], strict=True)):
            instance, output, oid = full_addresses[index]
            expected = {"source_index": dense, "instance_key": instance.key, "module_key": instance.module_key,
                "output_key": output.key, "output_id": oid, "source_op": output.operation["op"],
                "authored_output_digest": _hash(output.to_dict())}
            if selected:
                expected["project_source_index"] = index
            _require(all(_canonical(row.get(key)) == _canonical(value) for key, value in expected.items()),
                     code, "source output address/order/payload differs")
            _require((output.geometry is not None) == ("body" in row), code, "body source coverage differs")
            if output.geometry is not None:
                _require(_canonical(row["body"]["descriptor"]) == _canonical(output.geometry.to_dict()),
                         code, "body source descriptor differs")
            else:
                operation = {**_thaw(output.operation), "id": oid}
                ordinary_operations.append(operation)
                _require(row["materialized_op_digest"] == _hash(operation),
                         code, "ordinary materialized payload differs from authored source")
        if len(ordinary_operations) == len(indices):
            # D-1: the materialization envelope carries the project's stable
            # identity, and reconstruction must build THE SAME envelope,
            # otherwise the check catches its own incompleteness instead of
            # a real divergence in the source.
            _require(submission["materialized_program_digest"] == _hash({"ir_version": project.ir_version,
                "intent": project.intent, "lineage": project.project_id,
                "ops": ordinary_operations}), code,
                "ordinary materialized program digest differs from authored source")
    except ProjectSubmissionError:
        raise
    except (ProjectError, TypeError, ValueError, KeyError, IndexError, AttributeError) as exc:
        raise ProjectSubmissionError(code, "invalid source association or unresolved selection") from exc


def validate_submission_claims(value, *, execution, plan_evidence, planned_units, grounded_evidence, source=None) -> None:
    """Check an inert record and its references to retained execution evidence.

    Does NOT reconstruct ProjectRevision, PlannedProgram, a fresh submission or
    materialization; no recipe/kernel/compiler runs. Project/instance/output/
    materialization digests whose payloads are not retained here remain claims.
    Input byte/depth budgets belong to the archive decoder, not this algebra.
    """
    if isinstance(value, dict) and value.get("schema") == "kir-submitted-project-binding/3":
        from kir.staged_submission import validate_staged_submission_claims
        return validate_staged_submission_claims(value, execution=execution, plan_evidence=plan_evidence,
            planned_units=planned_units, grounded_evidence=grounded_evidence, source=source)
    code = "invalid_submission_claims"
    try:
        selected = isinstance(value, dict) and value.get("schema") == SELECTED_SUBMISSION_SCHEMA
        names = {"schema", "project", "instances", "outputs", "materialization_digest",
            "materialized_program_digest", "plan_digest", "planned_units_digest", "grounded_evidence_digest",
            "execution", "claims", "submission_digest"}
        if selected:
            names.add("selection")
        data = _fields(value, names, "submission")
        _require(data["schema"] == (SELECTED_SUBMISSION_SCHEMA if selected else SUBMISSION_SCHEMA), code, "unknown submission schema")
        for key in ("submission_digest", "materialization_digest", "materialized_program_digest", "plan_digest", "planned_units_digest"):
            _digest(data[key], key)
        _require(data["submission_digest"] == _hash({key: item for key, item in data.items() if key != "submission_digest"}), code, "submission digest mismatch")
        _require(_canonical(data["execution"]) == _canonical(execution), code, "submission execution binding differs from retained archive")
        _require(data["plan_digest"] == plan_evidence["plan_digest"] and data["planned_units_digest"] == _hash(planned_units),
                 code, "submission plan/units differs from retained archive")
        ground_digest = grounded_evidence["ground_digest"] if grounded_evidence is not None else None
        if data["grounded_evidence_digest"] is not None:
            _digest(data["grounded_evidence_digest"], "grounded_evidence_digest")
        _require(data["grounded_evidence_digest"] == ground_digest, code, "submission grounding differs from retained archive")
        _require(_canonical(data["claims"]) == _canonical(_SELECTED_CLAIMS if selected else _CLAIMS), code, "unsupported submission claims")
        project = _fields(data["project"], {"project_id", "schema", "revision_id"}, "submission.project")
        _key(project["project_id"], "project_id")
        _digest(project["revision_id"], "project_revision_id")
        _require(project["schema"] in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2), code, "unsupported project schema claim")
        if plan_evidence["schema"] == _LINEAGED_PLAN_SCHEMA:
            _require(plan_evidence.get("lineage") == project["project_id"],
                     code, "signed native lineage differs from authored project")
        _require(isinstance(data["instances"], list) and isinstance(data["outputs"], list), code, "instance/output tables must be arrays")
        instances, modules, instance_order = {}, {}, {}
        for ordinal, instance in enumerate(data["instances"]):
            _fields(instance, {"instance_key", "module_key", "instance_snapshot_digest", "module_definition_digest"}, "submission.instance")
            key = _key(instance["instance_key"], "instance_key")
            module = _key(instance["module_key"], "module_key")
            _digest(instance["instance_snapshot_digest"], "instance_snapshot_digest")
            _digest(instance["module_definition_digest"], "module_definition_digest")
            _require(key not in instances, code, "duplicate instance key")
            _require(module not in modules or modules[module] == instance["module_definition_digest"], code, "one module has contradictory definition claims")
            instances[key], modules[module] = instance, instance["module_definition_digest"]
            instance_order[key] = ordinal
        outputs, seen_outputs = data["outputs"], set()
        if selected:
            selection = _fields(data["selection"], {"policy", "root_instance_keys", "source_output_count"}, "selection")
            roots, count = selection["root_instance_keys"], selection["source_output_count"]
            _require(selection["policy"] == SELECTION_POLICY and type(count) is int and count >= len(outputs) > 0
                     and type(roots) is list and bool(roots), code, "invalid selected scope")
            _require(all(type(key) is str and key in instances for key in roots) and len(set(roots)) == len(roots)
                     and roots == sorted(roots, key=instance_order.__getitem__), code, "root order/identity differs")
        _require(type(plan_evidence["source_op_count"]) is int and plan_evidence["source_op_count"] == len(outputs),
                 code, "source count differs from output table")
        grouped = [[] for _ in outputs]
        last_instance = -1
        last_project_index = -1
        for index, output in enumerate(outputs):
            names = {"source_index", "instance_key", "module_key", "output_key", "output_id", "source_op",
                     "authored_output_digest", "materialized_op_digest", "compiled_ops"}
            if isinstance(output, dict) and "body" in output:
                names.add("body")
            if selected:
                names.add("project_source_index")
            _fields(output, names, "submission.output")
            if selected:
                index_in_project = output["project_source_index"]
                _require(type(index_in_project) is int and last_project_index < index_in_project < count,
                         code, "project source positions are outside scope or out of order")
                last_project_index = index_in_project
            _require(type(output["source_index"]) is int and output["source_index"] == index, code, "output source order differs")
            key, instance_key = _key(output["output_key"], "output_key"), _key(output["instance_key"], "instance_key")
            _require(instance_key in instances and instances[instance_key]["module_key"] == output["module_key"], code, "output owner is absent or differs")
            _require(instance_order[instance_key] >= last_instance, code, "output order disagrees with instance order")
            last_instance = instance_order[instance_key]
            oid = output_id(project["project_id"], instance_key, key)
            _require(output["output_id"] == oid and oid not in seen_outputs, code, "output address differs or repeats")
            seen_outputs.add(oid)
            _digest(output["authored_output_digest"], "authored_output_digest")
            _digest(output["materialized_op_digest"], "materialized_op_digest")
            _require(isinstance(output["source_op"], str) and bool(output["source_op"]), code, "source operation name missing")
            _require(isinstance(output["compiled_ops"], list) and bool(output["compiled_ops"]), code, "source output has no compiled coverage")
            if "body" in output:
                body = _fields(output["body"], {"descriptor", "mesh_digest", "materialization_sidecar_digest"}, "submission.body")
                descriptor = _fields(body["descriptor"], {"kind", "bundle_sha256", "body_sha256"}, "submission.body.descriptor")
                _require(project["schema"] == PROJECT_SCHEMA_V2 and descriptor["kind"] == "occt_brep_mesh"
                         and output["source_op"] == "create_directshape", code, "body descriptor incompatible with source/schema")
                for name in ("bundle_sha256", "body_sha256"):
                    _digest(descriptor[name], name)
                for name in ("mesh_digest", "materialization_sidecar_digest"):
                    _digest(body[name], name)
        seen_compiled = set()
        for op in plan_evidence["ops"]:
            payload, origin = op["payload"], op["provenance"]
            index = origin["source_index"]
            _require(type(index) is int and 0 <= index < len(outputs), code, "compiled source index outside output table")
            output = outputs[index]
            _require(origin["source_id"] == output["output_id"] and origin["source_op"] == output["source_op"], code, "compiled origin differs from output")
            macro = origin.get("macro_name")
            if macro is None:
                _require(payload["id"] == output["output_id"] and payload["op"] == output["source_op"], code, "direct compiled output identity differs")
            else:
                _require(isinstance(macro, str) and macro == output["source_op"], code, "macro origin differs from source operation")
            _require(isinstance(payload["id"], str) and payload["id"] not in seen_compiled, code, "compiled operation is duplicated or malformed")
            seen_compiled.add(payload["id"])
            grouped[index].append(_compiled_claim(op))
            if "body" in output:
                _require(macro is None and "mesh" in payload and _hash(payload["mesh"]) == output["body"]["mesh_digest"],
                         code, "body mesh differs from retained plan payload")
        for output, compiled in zip(outputs, grouped, strict=True):
            _require(bool(compiled) and _canonical(output["compiled_ops"]) == _canonical(compiled), code,
                     "compiled payload/result/nested contracts or source coverage differs from retained plan")
    except ProjectSubmissionError:
        raise
    except (ProjectError, TypeError, ValueError, KeyError, IndexError) as exc:
        raise ProjectSubmissionError(code, "malformed submission claims or execution references") from exc


__all__ = ["SUBMISSION_SCHEMA", "SELECTED_SUBMISSION_SCHEMA", "ProjectSubmissionError", "SubmittedProjectBinding",
           "bind_project_submission", "bind_selected_project_submission", "validate_submission_claims", "validate_submission_source"]
