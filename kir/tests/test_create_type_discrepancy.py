"""Real project/compiler/archive/query parser; native responses are synthetic.

No Revit/API execution, geometry re-derivation during assessment, or claim that
fixture seed IDs 100/400 exist in any live document.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from uuid import uuid4

import pytest

from kir.contracts import ElementIdentityProof
from kir.create_publication import bind_create_receipt
from kir.create_type_discrepancy import (
    CreateTypeDiscrepancyError, CreateTypeDiscrepancyReport, assess_create_type_discrepancies,
)
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, output_id, _thaw
from kir.revit_connector import ConnectorPreparationError, ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.revit_observation import ObservationRefusal, prepare_element_observation, parse_element_observation
from kir.tests.test_revit_level_update import make_case, response_for
from kir.tests.test_revit_observation import identity, row as observed_row, unavailable


def project(*, walls=1, both_floors=False, selector=None, macro=False):
    pid = "consumer-types"
    ref = lambda key: {"by": "ref", "value": output_id(pid, "section", key)}
    outputs = {
        "level": {"op": "create_level", "elev_mm": 0},
        "wall-type": {"op": "create_wall_type", "host_kind": "wall", "new_name": "Declared wall",
                      "source_type": {"by": "element_id", "value": 100},
                      "layers": [{"width_mm": 200, "function": "Structure"}]},
        "floor-type": {"op": "create_wall_type", "host_kind": "floor", "new_name": "Declared floor",
                       "source_type": {"by": "element_id", "value": 400},
                       "layers": [{"width_mm": 200, "function": "Structure"}]},
    }
    for index in range(walls):
        wall = {"op": "create_wall", "p0_mm": [index * 5000, 0], "p1_mm": [(index + 1) * 5000, 0],
                "height_mm": 3000, "level": ref("level"), "type": ref("wall-type")}
        if selector == "element_id":
            wall["type"] = {"by": "element_id", "value": 100}
        if selector == "omitted":
            del wall["type"]
        outputs[f"wall-{index}"] = wall
    if both_floors:
        outputs["floor"] = {"op": "create_floor", "outline": [[0, 0], [5000, 0], [5000, 5000], [0, 5000]],
                            "level": ref("level"), "type": ref("floor-type")}
        outputs["contour"] = {"op": "create_floor_by_contour",
            "contour": {"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [5000, 5000]}},
            "level": ref("level"), "type": ref("floor-type")}
    if macro:
        outputs["expanded"] = {"op": "stack", "levels": 1, "h_mm": 3000, "floor": [
            {"op": "create_wall", "id": "inside", "p0_mm": [0, 1000], "p1_mm": [5000, 1000],
             "height_mm": 3000, "type": ref("wall-type")}]}
    return ProjectRevision(pid, [ModuleDefinition("explicit")], [ModuleInstance("section", "explicit", outputs)])


def scenario(tmp_path, **kwargs):
    case = make_case(tmp_path, project=project(**kwargs))
    ids = {}
    for index, output in enumerate(case["record"].project_submission["outputs"]):
        key, oid = output["output_key"], output["output_id"]
        number = 800 if key == "wall-type" else 801 if key == "floor-type" else 900 + index
        ids[key] = oid
        if oid not in case["result"]:  # Macro has no direct primary result.
            continue
        case["result"][oid] = {"id": str(number), **identity(number, "uid-" + key)}
        if output["source_op"] == "create_wall_type":
            case["result"][oid]["duplicated"] = True
    case["ids"] = ids
    case["response"]["receipt"]["changes"]["added"] = [
        int(value["id"]) for value in case["result"].values() if type(value) is dict and "id" in value]
    return case


def bind(case):
    response = deepcopy(case["response"])
    response["receipt"]["result_json"] = json.dumps(case["result"])
    return bind_create_receipt(case["record"], json.dumps(response), credentials=case["credentials"],
                               request_id=response["request_id"])


def observation(case, *, omit=(), mutate=None, revision=9, runtime=None, document="native-doc"):
    # Build actual parsed observation over its explicitly requested subset.
    # A smaller valid query must not erase the report's larger source denominator.
    values = {}
    original = case["record"].project_submission["outputs"]
    for output in original:
        key = output["output_key"]
        if key in omit or key == "expanded":
            continue
        uid = "uid-" + key
        native = case["result"].get(output["output_id"])
        # Receipt omission does not imply native nonexistence in this fixture.
        number = int(native["id"]) if type(native) is dict and "id" in native else 9999
        current = observed_row(uid, is_level=False)
        current.update(identity(number, uid))
        current["category_id"] = -2000011 if output["source_op"] == "create_wall" else -2000032
        if output["source_op"] in ("create_wall", "create_floor", "create_floor_by_contour"):
            floor = output["source_op"] != "create_wall"
            current["type_state"] = {"status": "observed", **identity(801 if floor else 800, "uid-floor-type" if floor else "uid-wall-type")}
        else:
            current["type_state"] = {"status": "none", **unavailable()}
        values[uid] = current
    if mutate:
        mutate(values)
    prepared = prepare_element_observation(list(values), target=runtime or case["prepared"].target,
        precondition=ContextPrecondition(document, revision), operation_id=str(uuid4()))
    credentials = SessionCredentials(prepared.target, str(uuid4()), "query-fixture-only")
    payload = {op["id"]: values[op["unique_id"]] for op in prepared.planned.to_ops()}
    response = response_for(prepared, credentials, payload,
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    return parse_element_observation(prepared, json.dumps(response), credentials=credentials,
                                     request_id=response["request_id"])


def assess(case, observed=None, bound=None):
    return assess_create_type_discrepancies(case["project"], case["record"], bound or bind(case),
                                           observed or observation(case))


def consumer(data, key="wall-0"):
    return next(row for row in data["outputs"] if row["output_key"] == key)


def test_seed_is_not_expected_created_type_and_all_three_consumers_are_supported(tmp_path):
    case = scenario(tmp_path, both_floors=True)
    data = assess(case).to_dict()
    assert data["consumer_count"] == 3 and data["counts"] == {"matched": 3, "mismatch": 0, "unavailable": 0, "conflict": 0}
    wall = consumer(data)
    assert wall["original_expected_type_identity"]["element_id"] == wall["observed_assigned_type_identity"]["element_id"] == 800
    assert wall["expected_type_output"]["output_key"] == "wall-type"
    for key in ("floor", "contour"):
        assert consumer(data, key)["observed_assigned_type_identity"]["element_id"] == 801
    assert data["historical"]["execution"]["precondition"]["revision"] == 8
    assert data["observation"]["precondition"]["revision"] == 9
    assert data["historical"]["timestamp_utc"] and data["observation"]["timestamp_utc"] is None
    assert data["observation"]["timestamp_status"] == "not_retained_by_observation_owner"


@pytest.mark.parametrize("wrong", [100, 999])
def test_seed_or_foreign_type_is_a_real_discrepancy(tmp_path, wrong):
    case = scenario(tmp_path)
    observed = observation(case, mutate=lambda rows: rows["uid-wall-0"].update(
        type_state={"status": "observed", **identity(wrong, "other-type-" + str(wrong))}))
    row = consumer(assess(case, observed).to_dict())
    assert row["state"] == "mismatch" and row["diagnostic"] == "consumer_assigned_other_type"
    assert row["observed_assigned_type_identity"]["element_id"] == wrong


def test_fifteen_consumer_denominator_survives_missing_observation(tmp_path):
    case = scenario(tmp_path, walls=13, both_floors=True)
    data = assess(case, observation(case, omit=("wall-7",))).to_dict()
    assert len(data["outputs"]) == data["consumer_count"] == 15
    assert data["counts"] == {"matched": 14, "mismatch": 0, "unavailable": 1, "conflict": 0}
    assert consumer(data, "wall-7")["diagnostic"] == "consumer_observation_missing"


def test_actual_residential_section_keeps_twelve_wall_and_three_slab_addresses(tmp_path):
    from examples.residential_project import concept
    from examples.residential_refinement import develop_section
    from examples.residential_typed_section import add_section_types

    source = concept()
    section = develop_section(source)
    typed = add_section_types(section, source=source, expected_revision=section.revision_id,
        wall_name="Explicit section wall", wall_layers=[{"width_mm": 200, "function": "Structure"}],
        wall_source_type={"by": "element_id", "value": 100},
        floor_name="Explicit section floor", floor_layers=[{"width_mm": 200, "function": "Structure"}],
        floor_source_type={"by": "element_id", "value": 400})
    case = make_case(tmp_path, project=typed)
    operations = {op.op_id: op.to_dict() for op in case["prepared"].planned.ops}
    # Populate the actual archived op addresses, never assumed output names.
    for index, (oid, op) in enumerate(operations.items()):
        case["result"][oid] = {"id": str(700 + index), **identity(700 + index, "native-" + oid)}
        if op["op"] == "create_wall_type":
            case["result"][oid]["duplicated"] = True
    values = {}
    for oid, op in operations.items():
        if op["op"] not in ("create_wall", "create_floor_by_contour", "create_wall_type"):
            continue
        native = case["result"][oid]
        uid = native["element_identity"]["unique_id"]
        current = observed_row(uid, is_level=False)
        current.update(identity(int(native["id"]), uid))
        if op["op"] == "create_wall_type":
            current["type_state"] = {"status": "none", **unavailable()}
        else:
            wanted = case["result"][op["type"]["value"]]["element_identity"]
            current["type_state"] = {"status": "observed", **identity(wanted["element_id"], wanted["unique_id"])}
        values[uid] = current
    missing_oid = next(oid for oid, op in operations.items() if op["op"] == "create_wall")
    del values["native-" + missing_oid]
    query = prepare_element_observation(list(values), target=case["prepared"].target,
        precondition=ContextPrecondition("native-doc", 9), operation_id=str(uuid4()))
    credentials = case["credentials"]
    response = response_for(query, credentials,
        {op["id"]: values[op["unique_id"]] for op in query.planned.to_ops()},
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    fresh = parse_element_observation(query, json.dumps(response), credentials=credentials,
                                      request_id=response["request_id"])
    before = typed.dumps(), case["path"].read_bytes()
    data = assess(case, fresh).to_dict()
    assert data["consumer_count"] == 15
    assert sum(row["source_op"] == "create_wall" for row in data["outputs"]) == 12
    assert sum(row["source_op"] == "create_floor_by_contour" for row in data["outputs"]) == 3
    assert data["counts"] == {"matched": 14, "mismatch": 0, "unavailable": 1, "conflict": 0}
    missing = next(row for row in data["outputs"] if row["output_id"] == missing_oid)
    assert missing["instance_key"] == "tower-a" and missing["diagnostic"] == "consumer_observation_missing"
    assert before == (typed.dumps(), case["path"].read_bytes())


@pytest.mark.parametrize("missing", ["wall-type", "floor-type"])
def test_expected_type_requires_its_own_fresh_query_row(tmp_path, missing):
    case = scenario(tmp_path, both_floors=True)
    data = assess(case, observation(case, omit=(missing,))).to_dict()
    target = "wall-0" if missing == "wall-type" else "floor"
    assert consumer(data, target)["state"] == "unavailable"
    assert consumer(data, target)["diagnostic"] == "expected_type_observation_missing"


@pytest.mark.parametrize("kind", ["wall", "floor"])
@pytest.mark.parametrize("own_type_state", ["observed", "unavailable"])
def test_expected_type_own_type_must_fit_supported_profile(tmp_path, kind, own_type_state):
    case = scenario(tmp_path, both_floors=True)
    def change(rows):
        value = ({"status": "observed", **identity(1777, "own-type-outside-profile")}
                 if own_type_state == "observed" else {"status": "unavailable", **unavailable()})
        rows["uid-" + kind + "-type"]["type_state"] = value
    recorded = observation(case, mutate=change)  # Real generic parser accepts both.
    data = assess(case, recorded).to_dict()
    keys = ("wall-0",) if kind == "wall" else ("floor", "contour")
    expected_code = "expected_type_profile_unsupported" if own_type_state == "observed" else "expected_type_profile_unavailable"
    for key in keys:
        assert consumer(data, key)["state"] == "unavailable"
        assert consumer(data, key)["diagnostic"] == expected_code
    assert data["consumer_count"] == 3
    assert data["counts"]["unavailable"] == len(keys)
    assert data["counts"]["matched"] == 3 - len(keys)


def test_repeated_report_is_revision_bound_not_new_currentness_evidence(tmp_path):
    case = scenario(tmp_path)
    bound, recorded = bind(case), observation(case)
    first, repeated = assess(case, recorded, bound), assess(case, recorded, bound)
    assert first.digest == repeated.digest
    data = repeated.to_dict()
    assert consumer(data)["state"] == "matched"
    assert consumer(data)["diagnostic"] == "revision_bound_type_link_matches_output"
    assert data["claims"]["comparison"] == "revision_bound_observed_type_identity_vs_qualified_output_identity"
    assert data["claims"]["current_model_state"] == "not_established"
    assert data["observation"]["precondition"]["revision"] == 9
    assert data["observation"]["timestamp_utc"] is None


@pytest.mark.parametrize("mode", ["none", "unavailable", "not_found"])
def test_explicit_native_missing_states_are_not_defaults(tmp_path, mode):
    case = scenario(tmp_path)
    def change(rows):
        current = rows["uid-wall-0"]
        if mode == "not_found":
            current.update(status="not_found", reason=None, name=None, category_id=None, is_level=None,
                type_state=None, level_status="not_evaluated", **unavailable())
        else:
            current["type_state"] = {"status": mode, **unavailable()}
    row = consumer(assess(case, observation(case, mutate=change)).to_dict())
    assert row["state"] == ("mismatch" if mode == "none" else "unavailable")


@pytest.mark.parametrize("fault", ["truncated", "deleted", "missing", "legacy", "bad-duplicate"])
def test_unqualified_original_capture_cannot_be_repaired_by_fresh_matching_link(tmp_path, fault):
    case = scenario(tmp_path)
    fresh = observation(case)
    oid = case["ids"]["wall-type"]
    if fault == "truncated": case["response"]["receipt"]["changes"]["truncated"] = True
    elif fault == "deleted": case["response"]["receipt"]["changes"]["deleted"] = [800]
    elif fault == "missing": del case["result"][oid]
    elif fault == "legacy": case["result"][oid] = {"id": "800", "duplicated": True}
    else: case["result"][oid]["duplicated"] = 0
    row = consumer(assess(case, fresh).to_dict())
    assert row["state"] == "unavailable"


def test_reused_type_is_a_link_not_created_or_owned(tmp_path):
    case = scenario(tmp_path)
    case["result"][case["ids"]["wall-type"]]["duplicated"] = False
    case["response"]["receipt"]["changes"]["added"].remove(800)
    data = assess(case).to_dict()
    assert consumer(data)["state"] == "matched"
    assert consumer(data)["type_publication_state"] == "reused_existing"
    assert data["claims"]["exclusive_type_ownership"] == "not_established"


def test_original_duplicate_uid_is_conflict_not_fresh_match(tmp_path):
    case = scenario(tmp_path)
    fresh = observation(case)
    case["result"]["unexpected"] = deepcopy(case["result"][case["ids"]["wall-type"]])
    assert consumer(assess(case, fresh).to_dict())["state"] == "conflict"


def test_fresh_duplicate_identity_is_rejected_by_existing_observation_owner(tmp_path):
    case = scenario(tmp_path)
    def contradiction(rows):
        rows["uid-floor-type"]["element_identity"]["element_id"] = 800
    with pytest.raises(ObservationRefusal, match="conflicting_element_identity"):
        observation(case, mutate=contradiction)


@pytest.mark.parametrize("axis", ["target", "document", "revision-equal", "revision-old"])
def test_other_or_prepublication_observation_refuses(tmp_path, axis):
    case = scenario(tmp_path)
    kwargs = ({"runtime": RuntimeTarget(str(uuid4()), str(uuid4()), "2026")} if axis == "target" else
              {"document": "foreign"} if axis == "document" else {"revision": 8 if axis == "revision-equal" else 7})
    with pytest.raises(CreateTypeDiscrepancyError):
        assess(case, observation(case, **kwargs))


def test_wrong_source_revision_and_raw_carriers_refuse(tmp_path):
    case = scenario(tmp_path)
    bound, fresh = bind(case), observation(case)
    changed = case["project"].revise(expected_revision=case["project"].revision_id, metadata={"new": True})
    with pytest.raises(ValueError):
        assess_create_type_discrepancies(changed, case["record"], bound, fresh)
    with pytest.raises(CreateTypeDiscrepancyError, match="typed_discrepancy_inputs_required"):
        assess_create_type_discrepancies(case["project"], case["record"], bound, fresh.rows)


@pytest.mark.parametrize("target", ["absent", "level", "non-native-shape"])
def test_invalid_or_nontype_authored_ref_cannot_become_a_fresh_submission(tmp_path, target):
    from kir.diag import KirRefusal
    from kir.viewer.tests.test_live_scene_mesh import _VAULT

    source = project()
    instance = source.instances[0]
    outputs = list(instance.outputs)
    outputs.insert(3, NamedOutput("non-native-shape", {
        "op": "create_directshape", "mesh": _VAULT, "category": "mass", "name": "Not a type"}))
    outputs = tuple(replace(output, operation={**_thaw(output.operation), "type": {
        "by": "ref", "value": output_id(source.project_id, "section", target)}})
        if output.key == "wall-0" else output for output in outputs)
    invalid = source.replace_instance(replace(instance, outputs=outputs), expected_revision=source.revision_id)
    # Existing planner/materializer owns this refusal; no fake archive or fresh
    # carrier is fabricated merely to enter this downstream consumer.
    with pytest.raises((ConnectorPreparationError, KirRefusal)):
        make_case(tmp_path, project=invalid)
    assert not (tmp_path / "original.sqlite").exists()


@pytest.mark.parametrize("selector", ["element_id", "omitted"])
def test_unsupported_selector_keeps_named_consumer(tmp_path, selector):
    case = scenario(tmp_path, selector=selector)
    data = assess(case).to_dict()
    assert data["consumer_count"] == 1
    assert consumer(data)["diagnostic"] == "explicit_type_output_ref_required"


def test_macro_is_a_named_unsupported_output_not_disappearing_consumer(tmp_path):
    case = scenario(tmp_path, macro=True)
    data = assess(case).to_dict()
    assert consumer(data, "expanded")["state"] == "unavailable"
    assert consumer(data, "expanded")["diagnostic"] == "direct_consumer_profile_unsupported"


def test_type_definition_and_postcondition_failure_are_separate_axes(tmp_path):
    case = scenario(tmp_path)
    # Same UID/type assignment tells us nothing about an in-place layer edit.
    # The present query wire has no layer field; adding one is a parser error.
    case["result"]["postcondition_violations"] = ["type layer thickness differs"]
    def changed_saved_version(rows):
        rows["uid-wall-type"]["element_identity"]["version_guid"] = "b" * 32
        rows["uid-wall-0"]["type_state"]["element_identity"]["version_guid"] = "b" * 32
    data = assess(case, observation(case, mutate=changed_saved_version)).to_dict()
    assert consumer(data)["state"] == "matched"
    assert consumer(data)["original_expected_type_identity"]["version_guid"] == "a" * 32
    assert consumer(data)["observed_expected_type_identity"]["version_guid"] == "b" * 32
    assert data["historical"]["outcome"]["witness"] == "violated"
    for axis in ("type_definition", "layers", "geometry", "engineering"):
        assert data["claims"][axis] == "not_evaluated"
    assert data["claims"]["whole_bim_acceptance"] == "not_established"
    with pytest.raises(ObservationRefusal):
        observation(case, mutate=lambda rows: rows["uid-wall-type"].update(layers_preserved=True))


def test_report_is_detached_and_pure_with_no_aggregate_acceptance(tmp_path, monkeypatch):
    case = scenario(tmp_path)
    bound, fresh = bind(case), observation(case)
    original = case["path"].read_bytes(), case["project"].dumps(), bound.to_dict(), fresh.rows
    import kir.compiler
    import kir.geometry_materialization
    import kir.revit_transport
    def forbidden(*args, **kwargs): pytest.fail("pure report attempted execution")
    monkeypatch.setattr(kir.compiler, "compile_program", forbidden)
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.geometry_materialization, "materialize_project", forbidden)
    monkeypatch.setattr(kir.revit_transport, "exchange", forbidden)
    report = assess(case, fresh, bound)
    data = report.to_dict()
    data["outputs"].clear()
    assert len(report.to_dict()["outputs"]) == 1
    assert not any(hasattr(report, field) for field in ("ok", "accepted", "may_retry", "execute_request"))
    assert original == (case["path"].read_bytes(), case["project"].dumps(), bound.to_dict(), fresh.rows)
    with pytest.raises(FrozenInstanceError): report.digest = "other"
    with pytest.raises(TypeError): CreateTypeDiscrepancyReport()
