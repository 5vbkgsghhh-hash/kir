"""Explicit exports/imports association inside the existing project archive.

Fresh binding deliberately recompiles the guarded runtime projection. Historical
validation only checks retained algebra: it neither reconstructs a fresh plan
nor proves historical normalization/native execution/receipt existence. Imports
remain imports and never acquire fictitious CREATE result rows.
"""
import hashlib
import math

from kir.project import (PROJECT_SCHEMA, PROJECT_SCHEMA_V2, ProjectRevision, _canonical, _digest, _hash,
                         _key, _object, _thaw, output_id)
from kir.project_submission import SubmittedProjectBinding, ProjectSubmissionError, _compiled_claim


STAGED_SUBMISSION_SCHEMA = "kir-submitted-project-binding/3"
_CLAIMS = {"association": "matched_staged_projection_and_reprepared_source",
    "publication_scope": "exports_only_with_explicit_observed_imports", "normalization": "retained_compiler_claims_not_replayed_on_load",
    "project_persistence": "not_established", "import_archive_existence": "not_established",
    "recipe_execution": "not_established", "kernel_execution": "not_established", "native_execution": "not_established",
    "native_element_mapping": "exports_not_created", "dispatch_state": "not_recorded", "retry_permission": "none",
    "engineering_acceptance": "not_established"}
# Pinned grammar of partition profile /1, not today's registry. Historical
# readers must not silently adopt a future operation/ref contract.
_SLOTS = {"create_level": (), "create_wall_type": ("source_type",),
          "create_wall": ("level", "type", "top_level"),
          "create_floor": ("level", "type"), "create_floor_by_contour": ("level", "type")}
_PARTITION_CLAIMS = {"scope": "authored_partition_only", "native_identity": "not_observed", "native_birth": "not_established",
    "observed_match": "not_evaluated", "execution_permission": "not_granted", "closed_compilable_program": "not_claimed",
    "materialization_plan": "full_source_revalidated", "numeric_selector_binding": "not_performed", "native_execution": "not_run"}
_CORE_CLAIMS = {"scope": "fresh_guarded_preparation_only", "guard_proofs": "identity_dependencies_not_ownership",
                "import_preservation": "declared_clauses_only", "dispatch_permission": "none"}
_DESCRIPTOR = {"output_id", "instance_key", "output_key", "source_index", "project_source_index", "operation",
               "source_operation_digest", "reference_kind"}
_OUTPUT = {"source_index", "closure_source_index", "project_source_index", "instance_key", "module_key", "output_key",
           "output_id", "source_op", "authored_output_digest", "materialized_op_digest", "runtime_op_digest", "compiled_ops"}


def _need(value, detail):
    if not value:
        raise ProjectSubmissionError("invalid_staged_submission", detail)


def _fields(value, names):
    _need(type(value) is dict and set(value) == set(names), "unknown/missing staged fields")
    return value


#: Retained plan evidence this reader accepts. LOCAL by design: a historical
#: reader must not silently adopt a future contract by importing the live one.
_PLAN_V4 = "kir-planned-program/4"
_PLAN_V5 = "kir-planned-program/5"


def _plan_fields(schema, base: set) -> set:
    """The exact allowlist for one plan schema: /5 carries the signed lineage, /4 does not."""
    return (base | {"lineage"}) if schema == _PLAN_V5 else base


def _equal(left, right):
    return _canonical(left) == _canonical(right)


def _hashed(value, key):
    _digest(value[key], key)
    _need(value[key] == _hash({k: v for k, v in value.items() if k != key}), key + " differs")


def _result_kind(op):
    name = op.get("op")
    _need(name in _SLOTS, "operation outside retained staged profile")
    if name == "create_wall_type":
        kind = op.get("host_kind", "wall")
        _need(type(kind) is str and kind in ("wall", "floor"), "host type outside retained profile")
        return kind + "_type"
    return "level" if name == "create_level" else "wall" if name == "create_wall" else "element"


def _plan(value, raw_ops):
    schema = value.get("schema") if type(value) is dict else None
    _fields(value, _plan_fields(schema, {"schema", "ir_version", "family", "intent", "allow_destructive",
                                         "bulk", "source_op_count", "program_id", "ops", "plan_digest"}))
    _need(value["schema"] in (_PLAN_V4, _PLAN_V5)
          and value["family"] == "write" and value["allow_destructive"] is False
          and type(value["bulk"]) is bool and value["program_id"] is None, "retained plan profile differs")
    _need(type(value["ir_version"]) is str and type(value["intent"]) is str, "plan envelope differs")
    _need(type(value["ops"]) is list and type(value["source_op_count"]) is int
          and value["source_op_count"] == len(raw_ops) == len(value["ops"]) > 0, "flat plan count differs")
    _hashed(value, "plan_digest")
    seen = set()
    for index, (op, raw) in enumerate(zip(value["ops"], raw_ops, strict=True)):
        _fields(op, {"payload", "family", "effect", "result", "contract_digest", "nested_contracts", "provenance"})
        payload, origin = op["payload"], op["provenance"]
        _need(type(payload) is dict and payload.get("op") == raw["op"] and payload.get("id") == raw["id"], "plan/source identity differs")
        _need(payload["id"] not in seen and op["family"] == "authoring" and op["effect"] == "create"
              and op["nested_contracts"] == [], "non-flat or repeated CREATE plan")
        seen.add(payload["id"])
        _digest(op["contract_digest"], "contract_digest")
        _need(_equal(op["result"], {"identity_cardinality": "one", "identity_field": "id", "reference_kind": _result_kind(payload)}),
              "retained result contract differs from staged profile")
        _fields(origin, {"source_index", "source_op", "source_id", "fields"})
        _need(type(origin["source_index"]) is int and origin["source_index"] == index
              and origin["source_id"] == raw["id"] and origin["source_op"] == raw["op"], "plan origin differs")
        _need(type(origin["fields"]) is dict and set(origin["fields"]) == set(payload)
              and all(type(v) is str and v in {"explicit", "registry_default", "compiler_derived"}
                      for v in origin["fields"].values()), "unsupported retained field provenance")
    return {op["payload"]["id"]: op for op in value["ops"]}


def bind_staged_project_submission(projection, prepared) -> SubmittedProjectBinding:
    """Fresh factory: revalidate projection and recompile the expected full C#.

    This explicit cost is confined to new binding. It prevents caller-edited
    PreparedExecution attributes from standing in for emitted guards/isolation.
    """
    from kir.revit_connector import PreparedExecution
    from kir.staged_create_projection import StagedCreateProjection, prepare_staged_create
    _need(type(projection) is StagedCreateProjection and type(prepared) is PreparedExecution, "fresh staged inputs required")
    expected = prepare_staged_create(projection, operation_id=prepared.operation_id)
    _need(prepared.source == expected.source and _equal(prepared.binding_dict(), expected.binding_dict())
          and prepared.expected_identities == expected.expected_identities
          and prepared.association_digest == expected.association_digest
          and _equal(prepared.planned.to_evidence_dict(), expected.planned.to_evidence_dict())
          and _equal(prepared.planned.units, expected.planned.units)
          and _equal(prepared.grounded.to_evidence_dict() if prepared.grounded else None,
                     expected.grounded.to_evidence_dict() if expected.grounded else None), "prepared input differs from actual re-preparation")
    partition = projection.partition
    project, materialized = partition.project, partition.materialization
    table = partition.to_dict()
    addresses = project.addressed_outputs()
    logical_raw = materialized.to_program()["ops"]
    runtime_raw = projection.runtime_program["ops"]
    outputs = []
    for dense, descriptor in enumerate(table["exports"]):
        index, closure_index = descriptor["project_source_index"], descriptor["source_index"]
        instance, output, oid = addresses[index]
        outputs.append({"source_index": dense, "closure_source_index": closure_index, "project_source_index": index,
            "instance_key": instance.key, "module_key": instance.module_key, "output_key": output.key, "output_id": oid,
            "source_op": output.operation["op"], "authored_output_digest": _hash(output.to_dict()),
            "materialized_op_digest": _hash(logical_raw[closure_index]), "runtime_op_digest": _hash(runtime_raw[dense]),
            "compiled_ops": [_compiled_claim(prepared.planned.ops[dense].to_evidence_dict())]})
    payload = {"schema": STAGED_SUBMISSION_SCHEMA,
        "project": {"project_id": project.project_id, "schema": project.schema, "revision_id": project.revision_id},
        "instances": [{"instance_key": i.key, "module_key": i.module_key, "instance_snapshot_digest": _hash(i.to_dict()),
                       "module_definition_digest": i.module_digest} for i in project.instances],
        "outputs": outputs, "partition": table, "materialization": materialized.to_dict(),
        "logical_plan_evidence": materialized.planned.to_evidence_dict(),
        "projection": {"association_core": projection.core, "association_digest": projection.association_digest,
                       "runtime_program": projection.runtime_program},
        "materialization_digest": materialized.to_dict()["materialization_digest"],
        "materialized_program_digest": _hash(materialized.to_program()), "plan_digest": prepared.planned.plan_digest,
        "planned_units_digest": _hash(prepared.planned.units),
        "grounded_evidence_digest": prepared.grounded.ground_digest if prepared.grounded else None,
        "execution": prepared.binding_dict(), "claims": dict(_CLAIMS)}
    binding = object.__new__(SubmittedProjectBinding)
    object.__setattr__(binding, "_payload", _object(payload, "staged_submission"))
    object.__setattr__(binding, "digest", _hash(payload))
    validate_staged_submission_claims(binding.to_dict(), execution=prepared.binding_dict(),
        plan_evidence=prepared.planned.to_evidence_dict(), planned_units=_thaw(prepared.planned.units),
        grounded_evidence=prepared.grounded.to_evidence_dict() if prepared.grounded else None, source=prepared.source)
    validate_staged_submission_source(project, binding.to_dict(), selection_policy="current")
    return binding


def _tables(data, plan_evidence):
    project = _fields(data["project"], {"project_id", "schema", "revision_id"})
    _key(project["project_id"], "project_id"); _digest(project["revision_id"], "project_revision")
    _need(project["schema"] in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2), "unknown Project schema")
    _need(type(data["instances"]) is list and bool(data["instances"]), "instance table missing")
    instances, modules = {}, {}
    for row in data["instances"]:
        _fields(row, {"instance_key", "module_key", "instance_snapshot_digest", "module_definition_digest"})
        key, module = _key(row["instance_key"], "instance"), _key(row["module_key"], "module")
        _digest(row["instance_snapshot_digest"], "instance_digest"); _digest(row["module_definition_digest"], "module_digest")
        _need(key not in instances and modules.get(module, row["module_definition_digest"]) == row["module_definition_digest"], "instance/module contradiction")
        instances[key], modules[module] = row, row["module_definition_digest"]
    partition = _fields(data["partition"], {"schema", "profile", "project", "selection", "materialization_digest", "source_output_count",
        "closure_output_count", "export_output_count", "scoped_outputs", "imports", "exports", "dependency_edges",
        "unbound_selectors", "symbolic_export_ops", "claims", "partition_digest"})
    _need(partition["schema"] == "kir-project-execution-partition/1" and partition["profile"] == "direct_level_host_type_wall_floor/1"
          and _equal(partition["project"], project) and _equal(partition["claims"], _PARTITION_CLAIMS), "partition profile differs")
    _hashed(partition, "partition_digest")
    materialized = data["materialization"]
    selected = partition["selection"] is not None
    _fields(materialized, {"schema", "project_id", "project_revision_id", "plan_digest", "program", "sources", "scope",
        "native_bim", "revit_execution", "geometric_error_bound", "recipe_execution", "materialization_digest"} | ({"selection"} if selected else set()))
    _need(materialized["schema"] == ("kir-geometry-materialization/2" if selected else "kir-geometry-materialization/1")
          and materialized["project_id"] == project["project_id"] and materialized["project_revision_id"] == project["revision_id"]
          and materialized["sources"] == [] and materialized["scope"] == ("selected_body_to_triangle_representation" if selected else "body_to_triangle_representation")
          and materialized["native_bim"] == "not_claimed" and materialized["revit_execution"] == materialized["recipe_execution"] == "not_run"
          and materialized["geometric_error_bound"] == "not_measured", "materialization profile differs")
    _hashed(materialized, "materialization_digest")
    _need(materialized["materialization_digest"] == data["materialization_digest"] == partition["materialization_digest"], "materialization chain differs")
    program = _fields(materialized["program"], {"ir_version", "intent", "lineage", "ops"})
    _need(program["lineage"] == project["project_id"], "logical source lineage differs")
    _need(type(program["ops"]) is list and bool(program["ops"]) and _hash(program) == data["materialized_program_digest"], "logical raw program differs")
    logical = data["logical_plan_evidence"]
    logical_ops = _plan(logical, program["ops"])
    _need(logical["schema"] == plan_evidence["schema"], "mixed logical/runtime lineage contracts")
    if logical["schema"] == _PLAN_V5:
        _need(logical["lineage"] == program["lineage"], "signed logical lineage differs")
    _need(logical["plan_digest"] == materialized["plan_digest"] and logical["ir_version"] == program["ir_version"]
          and logical["intent"] == program["intent"] and logical["bulk"] == plan_evidence["bulk"], "logical plan binding differs")
    n = len(program["ops"])
    _need(type(partition["source_output_count"]) is int and partition["source_output_count"] >= n
          and type(partition["closure_output_count"]) is int and partition["closure_output_count"] == n,
          "logical counts differ")
    if selected:
        selection = _fields(partition["selection"], {"policy", "root_instance_keys", "source_output_count"})
        roots = selection["root_instance_keys"]
        _need(selection["policy"] == "authored_dependency_closure/1" and selection["source_output_count"] == partition["source_output_count"]
              and type(selection["source_output_count"]) is int and type(roots) is list and bool(roots)
              and all(type(key) is str and key in instances for key in roots) and len(set(roots)) == len(roots)
              and roots == [key for key in instances if key in roots] and _equal(materialized["selection"], selection), "selection differs")
    else:
        _need(partition["source_output_count"] == n, "whole scope count differs")
    _need(type(partition["scoped_outputs"]) is list and len(partition["scoped_outputs"]) == n, "closure table missing")
    descriptors, raw_by_id, last, last_instance = {}, {}, -1, -1
    order = {key: i for i, key in enumerate(instances)}
    for index, (row, raw) in enumerate(zip(partition["scoped_outputs"], program["ops"], strict=True)):
        _fields(row, _DESCRIPTOR)
        ikey, okey = _key(row["instance_key"], "instance"), _key(row["output_key"], "output")
        _need(ikey in instances and order[ikey] >= last_instance, "closure instance order differs")
        last_instance = order[ikey]
        _need(type(row["source_index"]) is int and row["source_index"] == index
              and type(row["project_source_index"]) is int and last < row["project_source_index"] < partition["source_output_count"], "closure order differs")
        last = row["project_source_index"]
        oid = output_id(project["project_id"], ikey, okey)
        _need(row["output_id"] == oid and oid not in descriptors and type(raw) is dict and raw.get("id") == oid
              and row["operation"] == raw.get("op") and row["source_operation_digest"] == _hash(raw)
              and row["reference_kind"] == _result_kind(logical_ops[oid]["payload"]), "closure address/source differs")
        descriptors[oid], raw_by_id[oid] = row, raw
    imports, exports = partition["imports"], partition["exports"]
    _need(type(imports) is list and type(exports) is list and bool(exports), "partition lists missing")
    import_ids = [row["output_id"] for row in imports]
    export_ids = [row["output_id"] for row in exports]
    _need(len(set(import_ids + export_ids)) == n and set(import_ids + export_ids) == set(descriptors), "partition overlap/missing output")
    _need(_equal(imports, [v for k, v in descriptors.items() if k in import_ids])
          and _equal(exports, [v for k, v in descriptors.items() if k in export_ids])
          and type(partition["export_output_count"]) is int and partition["export_output_count"] == len(exports), "partition order/count differs")
    _need(all(descriptors[oid]["operation"] in ("create_level", "create_wall_type") for oid in import_ids), "unsupported import producer")
    _need(_equal(partition["symbolic_export_ops"], [raw_by_id[oid] for oid in export_ids]), "symbolic exports differ")
    edges, unbound = [], []
    positions = {oid: i for i, oid in enumerate(descriptors)}
    for oid, raw in raw_by_id.items():
        for field in _SLOTS[raw["op"]]:
            selector = raw.get(field)
            if selector is None:
                continue
            _need(type(selector) is dict and set(selector) <= {"by", "value", "kind"}, "unsupported retained selector")
            if selector.get("by") == "ref":
                target = selector.get("value")
                _need(type(target) is str and target.strip() in descriptors and field != "source_type", "unresolved retained ref")
                target = target.strip()
                wanted = "level" if field in ("level", "top_level") else "wall_type" if raw["op"] == "create_wall" else "floor_type"
                _need(positions[target] < positions[oid] and descriptors[target]["reference_kind"] == wanted
                      and oid not in import_ids, "retained ref order/kind/import dependency differs")
                edges.append({"source": target, "dependent": oid, "field": field})
            else:
                unbound.append({"op_id": oid, "field": field, "kind": "selector_requires_grounding", "value": selector.get("by")})
    _need(_equal(partition["dependency_edges"], edges) and _equal(partition["unbound_selectors"], unbound), "retained dependency/selector tables differ")
    return partition, instances, raw_by_id, logical_ops, import_ids, export_ids


def _core(data, partition, logical_ops, raw_by_id, import_ids, export_ids, runtime_ops, execution):
    from kir.contracts import ElementIdentityProof
    from kir.revit_connector import ContextPrecondition
    from kir.type_definition_observation import validate_type_definition_claims
    projection = _fields(data["projection"], {"association_core", "association_digest", "runtime_program"})
    core = _fields(projection["association_core"], {"schema", "partition_digest", "runtime_program_digest", "runtime_plan_digest",
        "target", "precondition", "isolation", "import_lineage", "projection_table", "expected_identities", "required_import_unique_ids", "observation", "claims"})
    _need(core["schema"] == "kir-staged-create-association-core/1" and _equal(core["claims"], _CORE_CLAIMS)
          and core["partition_digest"] == partition["partition_digest"] and projection["association_digest"] == _hash(core), "association core differs")
    _need(core["isolation"] in ("atomic", "per_op") and _equal(core["target"], execution["target"])
          and _equal(core["precondition"], execution["precondition"]), "association execution/C0 differs")
    validate_type_definition_claims(core["observation"])
    _need(_equal(core["observation"]["target"], core["target"]) and _equal(core["observation"]["precondition"], core["precondition"]), "observation C0 differs")
    _need(type(core["import_lineage"]) is list and [row["output_id"] for row in core["import_lineage"]] == import_ids, "import lineage coverage differs")
    guards, uids, imported = {}, {}, {}
    # Indexed once; first match wins, as the linear scans they replace did.
    descriptors, owners = {}, {}
    for descriptor in partition["imports"]:
        descriptors.setdefault(descriptor["output_id"], descriptor)
    for item in data["instances"]:
        owners.setdefault(item["instance_key"], item)
    for row in core["import_lineage"]:
        fields = {"output_id", "instance_key", "output_key", "reference_kind", "source_operation_digest", "module_definition_digest",
            "instance_parameters_digest", "original_project_revision", "original_archive_digest", "original_receipt_digest",
            "original_identity_assessment_digest", "original_precondition", "original_identity_state", "original_identity",
            "observed_identity", "observation_row", "declared_comparison"}
        if type(row) is dict and "identity_replacement" in row:
            fields.add("identity_replacement")
        _fields(row, fields)
        # Current projections name the absence explicitly; older records omit
        # it. A replacement summary is not the full confirmed replacement ledger.
        # This retained profile continues to require the SAME original UID.
        _need(row.get("identity_replacement") is None,
              "identity replacement persistence is outside this staged profile")
        oid = row["output_id"]
        descriptor = descriptors[oid]
        for key in ("instance_key", "output_key", "reference_kind", "source_operation_digest"):
            _need(_equal(row[key], descriptor[key]), "import source identity differs")
        for key in ("module_definition_digest", "instance_parameters_digest", "original_project_revision", "original_archive_digest",
                    "original_receipt_digest", "original_identity_assessment_digest"):
            _digest(row[key], key)
        owner = owners.get(row["instance_key"])
        _need(owner is not None and row["module_definition_digest"] == owner["module_definition_digest"],
              "import module claims differ")
        original, current = ElementIdentityProof.from_dict(row["original_identity"]), ElementIdentityProof.from_dict(row["observed_identity"])
        _fields(row["original_precondition"], {"document_key", "revision", "active_view_id", "selection_digest"})
        old = ContextPrecondition(**row["original_precondition"])
        _need(_equal(old.to_dict(), row["original_precondition"]) and old.document_key == core["precondition"]["document_key"]
              and row["original_identity_state"] in ("created_here", "reused_existing")
              and (core["precondition"]["revision"] > old.revision or core["precondition"]["revision"] == old.revision
                   and row["original_identity_state"] == "reused_existing"), "original/current context ordering differs")
        _need(original.unique_id == current.unique_id and current.unique_id not in uids, "import UID changed or repeated")
        observed = core["observation"]["rows"].get(current.unique_id)
        _need(observed is not None and _equal(row["observation_row"], observed) and observed["status"] == "observed"
              and _equal(observed["element_identity"], current.to_dict()), "import observation differs")
        imported[oid], uids[current.unique_id] = current, oid
        proofs = [current]
        if observed["type_state"]["status"] == "observed":
            proofs.append(ElementIdentityProof.from_dict(observed["type_state"]["element_identity"]))
        if observed["type_definition"]["status"] == "observed":
            proofs.extend(ElementIdentityProof.from_dict(layer["material_identity"])
                          for layer in observed["type_definition"]["value"]["layers"] if layer["material_identity"] is not None)
        for proof in proofs:
            _need(guards.get(proof.element_id, proof) == proof, "import guards conflict")
            guards[proof.element_id] = proof
        _comparison(row["declared_comparison"], logical_ops[oid]["payload"], observed, core["observation"])
    expected_guards = [v.to_dict() for v in sorted(guards.values(), key=lambda v: (v.element_id, v.unique_id))]
    _need(_equal(core["expected_identities"], expected_guards)
          and core["required_import_unique_ids"] == [imported[oid].unique_id for oid in import_ids], "guard set/UID coverage differs")
    table = []
    for oid in export_ids:
        raw, logical = raw_by_id[oid], logical_ops[oid]["payload"]
        expected_raw, expected_normal = _thaw(raw), _thaw(logical)
        for field in _SLOTS[raw["op"]]:
            selector = raw.get(field)
            if type(selector) is not dict or selector.get("by") != "ref" or selector.get("value", "").strip() not in imported:
                continue
            target = selector["value"].strip()
            _need(field != "source_type" and type(logical.get(field)) is dict and logical[field].get("by") == "ref"
                  and logical[field].get("value") == target, "typed import selector differs")
            projected = {**selector, "by": "element_id", "value": imported[target].element_id}
            expected_raw[field] = projected
            expected_normal[field] = {**logical[field], "by": "element_id", "value": imported[target].element_id}
            table.append({"export_output_id": oid, "field": field, "import_output_id": target,
                          "source_selector": selector, "runtime_selector": projected})
        raw_runtime = next(op for op in projection["runtime_program"]["ops"] if op["id"] == oid)
        _need(_equal(raw_runtime, expected_raw) and _equal(runtime_ops[oid]["payload"], expected_normal), "runtime changed more than typed imports")
        _need(all(_equal(runtime_ops[oid][key], logical_ops[oid][key]) for key in ("family", "effect", "result", "contract_digest", "nested_contracts")),
              "runtime contract differs from retained logical operation")
    _need(_equal(core["projection_table"], table) and set(imported) == {row["import_output_id"] for row in table}, "projection table missing/extra/unused import")
    return core


def _comparison(value, operation, observed, observation):
    """Inert consistency of the already-retained comparison, no re-planning."""
    _need(type(value) is dict and type(value.get("checks")) is dict and value["checks"], "import comparison absent")
    _need(all(type(row) is dict and row.get("status") == "matched" for row in value["checks"].values()), "import comparison not matched")
    tolerance = value.get("tolerance_mm")
    _need(type(tolerance) in (int, float) and math.isfinite(tolerance) and tolerance >= 0, "invalid retained tolerance")
    if operation["op"] == "create_level":
        _fields(value, {"schema", "checks", "tolerance_mm", "expected_elevation_mm", "observed_project_elevation_mm",
                        "observed_reported_elevation_mm", "claims"})
        required = {"project_elevation", "reported_elevation"} | ({"declared_name"} if "name" in operation else set())
        _need(value["schema"] == "kir-staged-level-comparison/1" and set(value["checks"]) == required
              and observed["is_level"] is True and observed["level_status"] == "observed" and observed["type_state"]["status"] == "observed",
              "Level comparison profile differs")
        _need(tolerance == 1.0 and type(operation["elev_mm"]) in (int, float) and math.isfinite(operation["elev_mm"])
              and all(_equal(check, {"status": "matched"}) for check in value["checks"].values())
              and _equal(value["claims"], {"scope": "declared_level_elevation_and_optional_name", "ownership": "not_established"}),
              "retained Level clause profile differs")
        _need(_equal(value["expected_elevation_mm"], operation["elev_mm"])
              and _equal(value["observed_project_elevation_mm"], observed["level"]["project_elevation_mm"])
              and _equal(value["observed_reported_elevation_mm"], observed["level"]["reported_elevation_mm"])
              and all(abs(observed["level"][key] - operation["elev_mm"]) <= tolerance for key in ("project_elevation_mm", "reported_elevation_mm"))
              and ("name" not in operation or observed["name"] == operation["name"]), "Level comparison contradicts observed fields")
    else:
        _fields(value, {"schema", "observation_digest", "unique_id", "expected_clauses_digest", "precondition", "checks", "tolerance_mm", "claims"})
        layers = operation["layers"]
        required = {"host_kind", "type_name", "layer_count", "total_width"} | {f"layers[{i}].{key}" for i in range(len(layers)) for key in ("width_mm", "function", "material")}
        _need(value["schema"] == "kir-type-definition-comparison/1" and set(value["checks"]) == required
              and value["observation_digest"] == observation["observation_digest"] and value["unique_id"] == observed["requested_unique_id"]
              and _equal(value["precondition"], observation["precondition"])
              and value["expected_clauses_digest"] == _hash({"host_kind": operation.get("host_kind", "wall"), "new_name": operation["new_name"], "layers": layers})
              and observed["type_definition"]["status"] == "observed", "type comparison binding differs")
        from kir.type_definition_observation import _NOT_EVALUATED
        _need(tolerance == 0.5 and _equal(value["claims"], {"current_model_state": "not_established", "project_source_binding": "not_established",
              "source_seed_identity": "not_evaluated", "update_permission": "none", "not_evaluated": list(_NOT_EVALUATED)}),
              "retained type clause profile differs")
        reasons = {"host_kind": "observed_host_kind", "type_name": "observed_type_name", "layer_count": "observed_layer_count", "total_width": "observed_total_width"}
        for i, layer in enumerate(layers):
            reasons.update({f"layers[{i}].width_mm": "observed_layer_width", f"layers[{i}].function": "observed_layer_function",
                            f"layers[{i}].material": "declared_no_material" if layer.get("material") is None else "observed_unique_material_name"})
        _need(all(_equal(value["checks"][key], {"status": "matched", "reason": reason}) for key, reason in reasons.items()), "retained type checks differ")
        actual = observed["type_definition"]["value"]
        _need(actual["host_kind"] == operation.get("host_kind", "wall") and actual["name"] == operation["new_name"]
              and len(actual["layers"]) == len(layers)
              and abs(actual["total_width_mm"] - round(sum(layer["width_mm"] for layer in layers), 6)) <= tolerance,
              "type comparison contradicts observed profile")
        for expected, read in zip(layers, actual["layers"], strict=True):
            _need(type(expected["width_mm"]) in (int, float) and math.isfinite(expected["width_mm"])
                  and abs(expected["width_mm"] - read["width_mm"]) <= tolerance and expected["function"] == read["function"], "layer comparison contradicts fields")
            _need((read["material_id"] == -1 if expected.get("material") is None else
                   read["material_name"] == expected["material"] and read["material_name_match_count"] == 1), "material comparison contradicts fields")


def validate_staged_submission_claims(value, *, execution, plan_evidence, planned_units, grounded_evidence, source) -> None:
    """Check retained /3 algebra only, including the original source commitment."""
    from kir.revit_connector import source_association_digest
    try:
        data = _fields(value, {"schema", "project", "instances", "outputs", "partition", "materialization", "logical_plan_evidence", "projection",
            "materialization_digest", "materialized_program_digest", "plan_digest", "planned_units_digest", "grounded_evidence_digest",
            "execution", "claims", "submission_digest"})
        _need(data["schema"] == STAGED_SUBMISSION_SCHEMA and _equal(data["claims"], _CLAIMS), "staged schema/claims differ")
        _hashed(data, "submission_digest")
        _need(type(source) is str and hashlib.sha256(source.encode()).hexdigest() == execution["source_sha256"]
              and _equal(data["execution"], execution), "full retained source/binding required")
        _need(_equal(planned_units, []) and data["planned_units_digest"] == _hash(planned_units), "staged units profile unsupported")
        runtime = _fields(data["projection"]["runtime_program"],
                          _plan_fields(plan_evidence["schema"], {"ir_version", "intent", "ops"}))
        runtime_ops = _plan(plan_evidence, runtime["ops"])
        if plan_evidence["schema"] == _PLAN_V5:
            _need(runtime["lineage"] == plan_evidence["lineage"] == data["project"]["project_id"],
                  "runtime native lineage differs from source")
        _need(data["plan_digest"] == plan_evidence["plan_digest"] and runtime["ir_version"] == plan_evidence["ir_version"]
              and runtime["intent"] == plan_evidence["intent"], "runtime plan binding differs")
        part, instances, raw, logical, imported, exported = _tables(data, plan_evidence)
        _need(list(runtime_ops) == exported and runtime["ir_version"] == data["materialization"]["program"]["ir_version"]
              and runtime["intent"] == data["materialization"]["program"]["intent"], "runtime exports differ")
        core = _core(data, part, logical, raw, imported, exported, runtime_ops, execution)
        _need(core["runtime_program_digest"] == _hash(runtime) and core["runtime_plan_digest"] == plan_evidence["plan_digest"]
              and source_association_digest(source) == data["projection"]["association_digest"], "source association header/core differs")
        ground_digest = grounded_evidence["ground_digest"] if grounded_evidence else None
        _need(data["grounded_evidence_digest"] == ground_digest, "ground digest differs")
        if grounded_evidence is not None:
            _need(grounded_evidence["plan_digest"] == plan_evidence["plan_digest"], "ground parent differs")
            _hashed(grounded_evidence, "ground_digest")
            ground_ops = grounded_evidence["ops"]
            _need(type(ground_ops) is list and len(ground_ops) == len(exported)
                  and [row["payload"]["id"] for row in ground_ops] == exported, "ground output order differs")
            grounded = {row["payload"]["id"]: row["payload"] for row in ground_ops}
            for row in ground_ops:
                _fields(row, {"payload", "payload_digest"})
                _need(row["payload_digest"] == _hash(row["payload"]), "ground payload digest differs")
            for slot in core["projection_table"]:
                marker = grounded[slot["export_output_id"]].get(slot["field"])
                _need(_equal(marker, {"__grounded__": {"id": slot["runtime_selector"]["value"], "name": None, "via": "element_id"}}),
                      "ground import resolution differs from C0 projection")
        _need(type(data["outputs"]) is list and len(data["outputs"]) == len(exported), "runtime output coverage differs")
        for index, (oid, output) in enumerate(zip(exported, data["outputs"], strict=True)):
            _fields(output, _OUTPUT)
            descriptor = next(v for v in part["exports"] if v["output_id"] == oid)
            expected = {"source_index": index, "closure_source_index": descriptor["source_index"], "project_source_index": descriptor["project_source_index"],
                "output_id": oid, "instance_key": descriptor["instance_key"], "output_key": descriptor["output_key"],
                "module_key": instances[descriptor["instance_key"]]["module_key"], "source_op": descriptor["operation"],
                "materialized_op_digest": _hash(raw[oid]), "runtime_op_digest": _hash(runtime["ops"][index]),
                "compiled_ops": [_compiled_claim(runtime_ops[oid])]}
            _digest(output["authored_output_digest"], "authored_output_digest")
            _need(all(_equal(output[key], val) for key, val in expected.items()), "export address/digest/compiled result differs")
    except ProjectSubmissionError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, StopIteration) as error:
        raise ProjectSubmissionError("invalid_staged_submission", "malformed retained staged association") from error


def validate_staged_submission_source(project, submission, *, selection_policy="current") -> None:
    """Bind raw retained closure to the actual complete Project; no history replay."""
    try:
        _need(type(project) is ProjectRevision and selection_policy in ("current", "retained"), "source/policy invalid")
        _need(_equal(submission["project"], {"project_id": project.project_id, "schema": project.schema, "revision_id": project.revision_id}), "actual source revision differs")
        expected_instances = [{"instance_key": i.key, "module_key": i.module_key, "instance_snapshot_digest": _hash(i.to_dict()),
                               "module_definition_digest": i.module_digest} for i in project.instances]
        _need(_equal(submission["instances"], expected_instances), "actual instance ownership differs")
        part, materialized = submission["partition"], submission["materialization"]
        addresses = project.addressed_outputs()
        _need(len(addresses) == part["source_output_count"], "actual source count differs")
        indices = [row["project_source_index"] for row in part["scoped_outputs"]]
        _need(all(type(i) is int and 0 <= i < len(addresses) for i in indices) and indices == sorted(set(indices)), "actual source indices invalid")
        if part["selection"] is None:
            _need(indices == list(range(len(addresses))), "whole source omitted output")
        else:
            roots = part["selection"]["root_instance_keys"]
            _need(roots == [i.key for i in project.instances if i.key in roots], "actual roots differ")
            _need({i for i, (instance, _, _) in enumerate(addresses) if instance.key in roots} <= set(indices), "declared root output missing")
            if selection_policy == "current":
                from kir.project_selection import select_project_instances
                choice = select_project_instances(project, instance_keys=roots)
                _need(_equal(choice.to_dict(), part["selection"]) and list(choice.project_source_indices) == indices, "current closure differs")
        raw = []
        for descriptor, index in zip(part["scoped_outputs"], indices, strict=True):
            instance, output, oid = addresses[index]
            _need(output.geometry is None and descriptor["output_id"] == oid and descriptor["instance_key"] == instance.key
                  and descriptor["output_key"] == output.key, "actual output/body differs")
            operation = {**_thaw(output.operation), "id": oid}
            _need(descriptor["source_operation_digest"] == _hash(operation), "actual raw operation differs")
            raw.append(operation)
        _need(_equal(materialized["program"], {"ir_version": project.ir_version, "intent": project.intent,
                                               "lineage": project.project_id, "ops": raw}), "actual closed raw program differs")
        for output in submission["outputs"]:
            instance, actual, _ = addresses[output["project_source_index"]]
            _need(output["authored_output_digest"] == _hash(actual.to_dict()), "actual export payload differs")
        for imported in submission["projection"]["association_core"]["import_lineage"]:
            descriptor = next(v for v in part["imports"] if v["output_id"] == imported["output_id"])
            instance, _, _ = addresses[descriptor["project_source_index"]]
            _need(imported["module_definition_digest"] == instance.module_digest
                  and imported["instance_parameters_digest"] == _hash(instance.parameters), "actual import ownership differs")
        if selection_policy == "current":
            from kir.compiler import plan_program
            from kir.geometry_materialization import GeometryMaterialization
            from kir.project_execution_partition import partition_project_execution
            selection = None if part["selection"] is None else choice
            plan = plan_program(materialized["program"], bulk=submission["logical_plan_evidence"]["bulk"])
            _need(_equal(plan.to_evidence_dict(), submission["logical_plan_evidence"]), "current logical normalization differs")
            retained = GeometryMaterialization(project, materialized["program"], plan, (), selection)
            derived = partition_project_execution(project, retained, import_output_ids=[v["output_id"] for v in part["imports"]])
            _need(_equal(derived.to_dict(), part), "current partition profile differs")
    except ProjectSubmissionError:
        raise
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, StopIteration) as error:
        raise ProjectSubmissionError("invalid_staged_submission", "staged source association differs") from error


__all__ = ["STAGED_SUBMISSION_SCHEMA", "bind_staged_project_submission", "validate_staged_submission_claims",
           "validate_staged_submission_source"]
