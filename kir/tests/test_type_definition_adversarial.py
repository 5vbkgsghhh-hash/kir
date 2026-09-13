"""Independent oracle controls; real generated getters, controlled API stubs.

Mutated wire controls test the actual strict parser. They are not proof of live
Revit behavior, whole type preservation or authenticated native transport.
"""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir.contracts import ElementIdentityProof
from kir.project import _hash
from kir.revit_connector import prepare_execution
from kir.revit_observation import ObservationRefusal, parse_element_observation
from kir.type_definition_observation import (compare_type_definition, parse_type_definition_observation,
                                            prepare_type_definition_observation)
from kir.tests.test_type_definition_observation import native_rows, parse_rows, factory
from kir.tests.test_revit_level_update import response_for


def material(layer, number, name="Concrete", count=1):
    layer.update(material_id=number, material_name=name, material_name_match_count=count,
        material_identity=ElementIdentityProof(number, "material-" + str(number), "12345678123456781234567812345678").to_dict())


@pytest.mark.parametrize("location", ["same-type", "across-types"])
def test_two_distinct_observed_materials_cannot_both_be_unique_by_the_same_name(native_rows, location):
    def contradict(rows):
        if location == "same-type": material(rows["wall"]["type_definition"]["value"]["layers"][1], 3002)
        else: material(rows["floor"]["type_definition"]["value"]["layers"][0], 3002)
    try:
        observed, _, _, _ = parse_rows(native_rows, mutate=contradict)
    except ObservationRefusal:
        return
    expected = factory()
    if location == "same-type": expected["layers"][1]["material"] = "Concrete"
    report = compare_type_definition(observed, unique_id="wall-uid", factory_op=expected)
    assert not all(check["status"] == "matched" for check in report["checks"].values()), report


@pytest.mark.parametrize("count", [0, 2])
def test_same_name_catalog_counts_must_agree_and_cover_observed_distinct_ids(native_rows, count):
    def contradict(rows):
        material(rows["floor"]["type_definition"]["value"]["layers"][0], 3002, count=count)
        if count == 0:
            rows["wall"]["type_definition"]["value"]["layers"][0]["material_name_match_count"] = 0
    with pytest.raises(ObservationRefusal): parse_rows(native_rows, mutate=contradict)


def test_case_distinct_material_names_are_not_false_global_conflicts(native_rows):
    def lawful(rows): material(rows["floor"]["type_definition"]["value"]["layers"][0], 3002, "concrete")
    observed, _, _, _ = parse_rows(native_rows, mutate=lawful)
    expected = factory("floor"); expected["layers"][0]["material"] = "concrete"
    report = compare_type_definition(observed, unique_id="floor-uid", factory_op=expected)
    assert all(check["status"] == "matched" for check in report["checks"].values())


@pytest.mark.parametrize("type_key", ["wall", "floor"])
def test_qualified_wall_or_floor_type_cannot_also_be_a_layer_material(native_rows, type_key):
    def impossible_getter_shape(rows):
        target = rows[type_key]
        rows["wall"]["type_definition"]["value"]["layers"][0].update(
            material_id=target["element_identity"]["element_id"], material_name=target["name"],
            material_identity=deepcopy(target["element_identity"]), material_name_match_count=1)
    try:
        observed, _, _, _ = parse_rows(native_rows, mutate=impossible_getter_shape)
    except ObservationRefusal:
        return
    expected = factory(); expected["layers"][0]["material"] = "Declared " + type_key
    report = compare_type_definition(observed, unique_id="wall-uid", factory_op=expected)
    assert not all(check["status"] == "matched" for check in report["checks"].values()), report


def test_explicit_material_query_can_share_its_proof_with_a_layer_without_being_a_type(native_rows):
    observed, original, _, credentials = parse_rows(native_rows)
    wall = observed.rows["wall-uid"]
    layer = wall["type_definition"]["value"]["layers"][0]
    material_row = deepcopy(observed.rows["floor-uid"])
    material_row.update(requested_unique_id=layer["material_identity"]["unique_id"],
        element_identity=deepcopy(layer["material_identity"]), name=layer["material_name"],
        type_definition={"status": "not_applicable", "reason": "unsupported_element_kind", "value": None})
    query = prepare_type_definition_observation(["wall-uid", material_row["requested_unique_id"]],
        target=original.target, precondition=original.precondition, operation_id=str(uuid4()))
    payload = {op["id"]: value for op, value in zip(query.planned.to_ops(), (wall, material_row), strict=True)}
    response = response_for(query, credentials, payload,
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    result = parse_type_definition_observation(query, json.dumps(response), credentials=credentials,
                                               request_id=response["request_id"])
    assert result.rows[material_row["requested_unique_id"]]["type_definition"]["status"] == "not_applicable"
    assert all(check["status"] == "matched" for check in
        compare_type_definition(result, unique_id="wall-uid", factory_op=factory())["checks"].values())


@pytest.mark.parametrize("native_case", ["curtain", "non_homogeneous", "structure_null", "structure_throw"])
def test_known_type_with_unsupported_or_unreadable_definition_is_not_a_material(native_rows, native_case):
    # These named getter results occur only after an actual Wall/FloorType cast.
    # Preserve that recorded classification even though layer facts are absent.
    victim, consumer_kind = ("wall", "floor") if native_case == "curtain" else ("floor", "wall")
    def impossible_getter_shape(rows):
        rows[consumer_kind] = deepcopy(native_rows["2026:normal"]["rows"][consumer_kind])
        target = rows[victim]
        assert target["type_definition"]["status"] != "observed"
        rows[consumer_kind]["type_definition"]["value"]["layers"][0].update(
            material_id=target["element_identity"]["element_id"], material_name=target["name"],
            material_identity=deepcopy(target["element_identity"]), material_name_match_count=1)
    try:
        observed, _, _, _ = parse_rows(native_rows, native_case, mutate=impossible_getter_shape)
    except ObservationRefusal:
        return
    expected = factory(consumer_kind); expected["layers"][0]["material"] = "Declared " + victim
    report = compare_type_definition(observed, unique_id=consumer_kind + "-uid", factory_op=expected)
    assert not all(check["status"] == "matched" for check in report["checks"].values()), report


@pytest.mark.parametrize("case,field", [("wrong_width", "layers[0].width_mm"), ("wrong_total", "total_width"),
                                       ("wrong_function", "layers[0].function")])
def test_identical_uid_version_does_not_replace_actual_getter_measurement(native_rows, case, field):
    normal, _, _, _ = parse_rows(native_rows)
    changed, _, _, _ = parse_rows(native_rows, case)
    assert normal.rows["wall-uid"]["element_identity"] == changed.rows["wall-uid"]["element_identity"]
    report = compare_type_definition(changed, unique_id="wall-uid", factory_op=factory())
    assert report["checks"][field]["status"] == "mismatch"
    assert report["claims"]["current_model_state"] == "not_established"
    assert "full_type_definition" in report["claims"]["not_evaluated"]


def test_actual_layer_order_is_semantic_not_just_equal_total_width(native_rows):
    observed, _, _, _ = parse_rows(native_rows,
        mutate=lambda rows: rows["wall"]["type_definition"]["value"]["layers"].reverse())
    report = compare_type_definition(observed, unique_id="wall-uid", factory_op=factory())
    assert report["checks"]["total_width"]["status"] == "matched"
    assert all(report["checks"][f"layers[{index}].{field}"]["status"] == "mismatch"
               for index in range(2) for field in ("width_mm", "function"))


@pytest.mark.parametrize("case", ["structure_null", "non_homogeneous", "homogeneous_throw"])
def test_null_or_non_simple_actual_structure_never_produces_matched_clauses(native_rows, case):
    observed, _, _, _ = parse_rows(native_rows, case)
    for kind in ("wall", "floor"):
        report = compare_type_definition(observed, unique_id=kind + "-uid", factory_op=factory(kind))
        assert len(report["checks"]) == 10
        assert all(check["status"] == "not_evaluated" for check in report["checks"].values())


def test_homogeneous_wall_compound_flag_does_not_hide_its_layer_observations(native_rows):
    observed, _, _, _ = parse_rows(native_rows, "vertically_compound")
    for kind in ("wall", "floor"):
        report = compare_type_definition(observed, unique_id=kind + "-uid", factory_op=factory(kind))
        assert all(check["status"] == "matched" for check in report["checks"].values())
    assert observed.rows["wall-uid"]["type_definition"]["value"]["is_vertically_compound"] is True


@pytest.mark.parametrize("bad", [[], [{"width_mm": True, "function": "Structure"}],
    [{"width_mm": float("nan"), "function": "Structure"}], [{"width_mm": 200, "function": None}]])
def test_malformed_expected_layer_profile_cannot_make_vacuous_match(native_rows, bad):
    observed, _, _, _ = parse_rows(native_rows)
    expected = factory(); expected["layers"] = bad
    with pytest.raises(ObservationRefusal, match="factory_definition_invalid"):
        compare_type_definition(observed, unique_id="wall-uid", factory_op=expected)


def test_type_host_kind_is_observed_not_echoed_from_expected_factory(native_rows):
    observed, _, _, _ = parse_rows(native_rows)
    expected = factory("wall"); expected["new_name"] = "Declared floor"
    report = compare_type_definition(observed, unique_id="floor-uid", factory_op=expected)
    assert report["checks"]["type_name"]["status"] == "matched"
    assert report["checks"]["host_kind"]["status"] == "mismatch"


@pytest.mark.parametrize("crossing", ["old-query-new-rows", "new-query-old-rows", "new-rows-old-parser",
                                     "new-query-old-rows-old-parser"])
def test_old_and_optin_query_profiles_cannot_cross_parse(native_rows, crossing):
    _, prepared, response, credentials = parse_rows(native_rows)
    if crossing == "old-query-new-rows":
        old_ops = [{k: v for k, v in op.items() if k != "include_type_definition"} for op in prepared.planned.to_ops()]
        old = prepare_execution({"ops": old_ops}, target=prepared.target, precondition=prepared.precondition,
                                operation_id=str(uuid4()))
        # Even an independently correctly bound old query cannot authorize /2.
        wire = response_for(old, credentials, json.loads(response["receipt"]["result_json"]),
            changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
        with pytest.raises(ObservationRefusal, match="type_definition_query_required"):
            parse_type_definition_observation(old, json.dumps(wire), credentials=credentials, request_id=wire["request_id"])
    elif crossing in ("new-query-old-rows", "new-query-old-rows-old-parser"):
        wire = deepcopy(response)
        result = json.loads(wire["receipt"]["result_json"])
        for row in result.values():
            row.pop("type_definition")
            row["schema_version"] = "kir-element-state/1"
        wire["receipt"]["result_json"] = json.dumps(result)
        with pytest.raises(ObservationRefusal):
            parser = (parse_element_observation if crossing == "new-query-old-rows-old-parser"
                      else parse_type_definition_observation)
            parser(prepared, json.dumps(wire), credentials=credentials, request_id=wire["request_id"])
    else:
        with pytest.raises(ObservationRefusal):
            parse_element_observation(prepared, json.dumps(response), credentials=credentials, request_id=response["request_id"])


def resign_claims(claims):
    claims["observation_digest"] = _hash({key: claims[key] for key in
        ("target", "precondition", "operation_id", "source_sha256", "rows")})


def test_structural_validation_is_pure_and_never_promotes_claims_to_a_fresh_carrier(native_rows, monkeypatch):
    import kir.type_definition_observation as owner
    import kir.compiler
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    before = deepcopy(claims)
    def forbidden(*_args, **_kwargs): pytest.fail("inert validation planned or manufactured a response")
    monkeypatch.setattr(owner, "prepare_execution", forbidden)
    monkeypatch.setattr(owner, "assess_connector_query_response", forbidden)
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    assert observed.validate() is None
    assert owner.validate_type_definition_claims(claims) is None
    assert claims == before and observed.to_dict() == before
    with pytest.raises(ObservationRefusal, match="type_definition_observation_required"):
        compare_type_definition(claims, unique_id="wall-uid", factory_op=factory())
    with pytest.raises(TypeError): owner.TypeDefinitionObservation(**claims)


@pytest.mark.parametrize("fault", ["duplicate-name", "zero-count", "type-as-material", "revision-bool",
                                  "wrong-row-scope", "source-hash", "claims", "schema"])
def test_resigned_inert_claims_share_strict_row_role_and_metadata_refusals(native_rows, fault):
    from kir.type_definition_observation import validate_type_definition_claims
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    rows = claims["rows"]
    if fault == "duplicate-name": material(rows["floor-uid"]["type_definition"]["value"]["layers"][0], 3002)
    elif fault == "zero-count":
        for row in rows.values(): row["type_definition"]["value"]["layers"][0]["material_name_match_count"] = 0
    elif fault == "type-as-material":
        target = rows["floor-uid"]
        rows["wall-uid"]["type_definition"]["value"]["layers"][0].update(
            material_id=target["element_identity"]["element_id"], material_name=target["name"],
            material_identity=deepcopy(target["element_identity"]), material_name_match_count=1)
    elif fault == "revision-bool": claims["precondition"]["revision"] = True
    elif fault == "wrong-row-scope": rows["not-requested"] = rows.pop("wall-uid")
    elif fault == "source-hash": claims["source_sha256"] = "A" * 64
    elif fault == "claims": claims["claims"]["current_model_state"] = "verified"
    else: claims["schema"] = "kir-type-definition-observation/2"
    resign_claims(claims)
    with pytest.raises(ObservationRefusal): validate_type_definition_claims(claims)


def test_coherent_resigned_claims_are_only_a_different_inert_statement(native_rows):
    from kir.type_definition_observation import validate_type_definition_claims
    observed, _, _, _ = parse_rows(native_rows)
    changed = observed.to_dict()
    changed["precondition"]["revision"] += 1
    changed["rows"]["wall-uid"]["name"] = "Different declared observation"
    changed["rows"]["wall-uid"]["type_definition"]["value"]["name"] = "Different declared observation"
    with pytest.raises(ObservationRefusal): validate_type_definition_claims(changed)
    resign_claims(changed)
    assert validate_type_definition_claims(changed) is None
    assert observed.to_dict()["observation_digest"] != changed["observation_digest"]
    assert observed.precondition.revision == 18
    with pytest.raises(ObservationRefusal, match="type_definition_observation_required"):
        compare_type_definition(changed, unique_id="wall-uid", factory_op=factory())
