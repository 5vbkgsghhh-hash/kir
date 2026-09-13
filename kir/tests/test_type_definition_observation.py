"""Actual emitted getter fragments + reference compile, never a live BIM model."""
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

import pytest

from kir import compile_program, sdk, spec
from kir.element_query import emit_element_state
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, wrap_connector_source
from kir.revit_observation import ObservationRefusal, parse_element_observation
from kir.schema_gen import program_schema
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_type_creation_conformance import type_conformance_runner
from kir.type_definition_observation import (
    TypeDefinitionObservation, prepare_type_definition_observation, parse_type_definition_observation,
    compare_type_definition, validate_type_definition_claims,
)


CASES = ("normal", "wrong_width", "wrong_total", "wrong_function", "wrong_material", "material_case",
    "ambiguous_material", "no_material", "material_missing", "material_identity_throw", "material_id_null",
    "material_lookup_throw", "material_catalog_throw", "material_name_throw", "structure_null", "structure_throw",
    "layers_null", "layers_throw", "layer_width_throw", "function_throw", "layer_nan", "total_inf", "total_throw",
    "vertically_compound", "non_homogeneous", "homogeneous_throw", "curtain", "kind_throw", "unsupported",
    "document_modifiable", "document_throw", "lookup_throw", "missing", "identity_throw", "membrane",
    "empty_layers", "too_many_layers")
OPS = [{"op": "query_element_state", "id": kind, "unique_id": kind + "-uid", "include_type_definition": True}
       for kind in ("wall", "floor")]


def factory(kind="wall", *, membrane=False):
    return {"op": "create_wall_type", "host_kind": kind, "new_name": "Declared " + kind,
        "source_type": {"by": "element_id", "value": 100 if kind == "wall" else 400},
        "layers": [({"width_mm": 0, "function": "Membrane"} if membrane else
                    {"width_mm": 200, "function": "Structure", "material": "Concrete"}),
                   {"width_mm": 20, "function": "Finish1"}]}


@pytest.mark.parametrize("version", [str(year) for year in range(2021, 2027)])
def test_optin_profile_and_unchanged_default_source(version):
    old = {"op": "query_element_state", "id": "wall", "unique_id": "wall-uid"}
    default = compile_program({"ops": [old]}, revit_version=version)
    explicit_false = compile_program({"ops": [{**old, "include_type_definition": False}]}, revit_version=version)
    included = compile_program({"ops": [{**old, "include_type_definition": True}]}, revit_version=version)
    assert default.ok and explicit_false.ok and included.ok
    assert default.csharp == explicit_false.csharp
    assert '"kir-element-state/1"' in default.csharp and '"type_definition"' not in default.csharp
    assert '"kir-element-state/2"' in included.csharp
    assert ".IsVerticallyHomogeneous()" in included.csharp and ".IsVerticallyCompound" in included.csharp
    assert "__wallType.Width" in included.csharp and "__structure.GetWidth()" in included.csharp
    for forbidden in (".Duplicate(", ".SetCompoundStructure(", ".SetLayers(", ".Activate(", "new Transaction(", "doc.Regenerate("):
        assert forbidden not in included.csharp
    assert included.planned.to_ops()[0]["include_type_definition"] is True
    assert "include_type_definition" not in explicit_false.planned.to_ops()[0]


@pytest.mark.parametrize("flag", [None, 0, 1, "true", [], {}])
def test_boolean_optin_is_strict_not_silently_dropped(flag):
    result = compile_program({"ops": [{**OPS[0], "include_type_definition": flag}]})
    assert not result.ok and any(d.field_name == "include_type_definition" and d.code == "KIR-T001" for d in result.diagnostics)


def test_sdk_and_generated_schema_expose_only_optional_boolean_profile():
    op = sdk.query_element_state(unique_id="wall-uid", include_type_definition=True)
    assert op["include_type_definition"] is True
    variants = program_schema()["properties"]["ops"]["items"]["oneOf"]
    schema = next(x for x in variants if x["properties"]["op"].get("const") == "query_element_state")
    assert schema["properties"]["include_type_definition"]["type"] == "boolean"
    assert "include_type_definition" not in schema["required"]


@pytest.mark.parametrize("version", [str(year) for year in range(2021, 2027)])
def test_actual_connector_policy_and_all_six_api_reference_versions(version, type_conformance_runner):
    result = compile_program({"ops": OPS}, revit_version=version)
    assert result.ok, result.diagnostics
    row, = type_conformance_runner(version, [wrap_connector_source(result.csharp)])
    assert row["ok"] is True and row["assembly_bytes"] > 0, row


@pytest.fixture(scope="module")
def native_rows(tmp_path_factory):
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK absent; getter fixture not executed")
    root = tmp_path_factory.mktemp("type-def-api")
    source = Path(__file__).with_name("type_definition_runtime.cs").read_text()
    for version in ("2023", "2026"):
        parts = [emit_element_state(op, version) for op in OPS]
        fragments = "\n\n".join(parts)
        actual = compile_program({"ops": OPS}, revit_version=version)
        assert actual.ok and all(actual.csharp.count(part) == 1 for part in parts)
        assert actual.csharp.index(parts[0]) < actual.csharp.index(parts[1])
        source = source.replace("/* QUERY" + version + " */", fragments)
    source = source.replace("/* CASES */", ",".join(json.dumps(case) for case in CASES))
    (root / "Generated.cs").write_text(source)
    (root / "Probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
        '<OutputType>Exe</OutputType><Nullable>disable</Nullable><ImplicitUsings>disable</ImplicitUsings>'
        '<UseAppHost>false</UseAppHost><UseSharedCompilation>false</UseSharedCompilation>'
        '<EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup>'
        '<ItemGroup><Compile Include="Generated.cs" /></ItemGroup></Project>')
    (root / "NuGet.Config").write_text('<configuration><packageSources><clear /></packageSources></configuration>')
    for name in ("empty.props", "empty.targets"):
        (root / name).write_text("<Project/>")
    env = {**os.environ, "DOTNET_CLI_HOME": str(root / "cli"), "NUGET_PACKAGES": str(root / "packages"),
           "TMPDIR": str(root), "TMP": str(root), "TEMP": str(root), "DOTNET_NOLOGO": "1",
           "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1", "DOTNET_CLI_USE_MSBUILD_SERVER": "0"}
    build = subprocess.run([dotnet, "build", str(root / "Probe.csproj"), "-c", "Release", "--nologo",
        "--configfile", str(root / "NuGet.Config"), "-p:NuGetAudit=false",
        "-p:DirectoryBuildPropsPath=" + str(root / "empty.props"),
        "-p:DirectoryBuildTargetsPath=" + str(root / "empty.targets")],
        env=env, cwd=root, text=True, capture_output=True, timeout=120)
    assert build.returncode == 0, build.stdout + build.stderr
    run = subprocess.run([dotnet, str(root / "bin/Release/net8.0/Probe.dll")],
        env=env, cwd=root, text=True, capture_output=True, timeout=30)
    assert run.returncode == 0 and not run.stderr and "secret" not in run.stdout, run.stdout + run.stderr
    return json.loads(run.stdout)


def parse_rows(native_rows, case="normal", version="2026", mutate=None):
    target = RuntimeTarget(str(uuid4()), str(uuid4()), version)
    auth = SessionCredentials(target, str(uuid4()), "test-only")
    query = prepare_type_definition_observation(["wall-uid", "floor-uid"], target=target,
        precondition=ContextPrecondition("native-document", 18), operation_id=str(uuid4()))
    rows = deepcopy(native_rows[version + ":" + case]["rows"])
    if mutate:
        mutate(rows)
    payload = {op["id"]: rows["wall" if i == 0 else "floor"] for i, op in enumerate(query.planned.to_ops())}
    response = response_for(query, auth, payload,
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    parsed = parse_type_definition_observation(query, json.dumps(response), credentials=auth, request_id=response["request_id"])
    return parsed, query, response, auth


@pytest.mark.parametrize("version", ["2023", "2026"])
@pytest.mark.parametrize("case", CASES)
def test_actual_emitter_getter_outcomes_reach_strict_profile_parser(native_rows, version, case):
    observed, _, _, _ = parse_rows(native_rows, case, version)
    for kind in ("wall", "floor"):
        definition = observed.rows[kind + "-uid"]["type_definition"]
        if case in ("normal", "wrong_width", "wrong_total", "wrong_function", "wrong_material", "material_case", "ambiguous_material", "no_material", "membrane", "vertically_compound"):
            assert definition["status"] == "observed", definition
        elif case in ("unsupported", "non_homogeneous") or case == "curtain" and kind == "wall":
            assert definition["status"] == "not_applicable" and definition["value"] is None
        elif case in ("curtain", "kind_throw") and kind == "floor":
            assert definition["status"] == "observed"
        else:
            assert definition["status"] == "unavailable" and definition["value"] is None, (case, definition)
    if case in ("document_modifiable", "document_throw"):
        assert native_rows[version + ":" + case]["uid_lookups"] == 0
        assert native_rows[version + ":" + case]["structure_reads"] == 0


@pytest.mark.parametrize("kind", ["wall", "floor"])
def test_actual_values_material_identity_and_normal_clause_match(native_rows, kind):
    observed, _, _, _ = parse_rows(native_rows)
    data = observed.rows[kind + "-uid"]["type_definition"]["value"]
    assert data["total_width_mm"] == pytest.approx(220)
    assert [x["width_mm"] for x in data["layers"]] == pytest.approx([200, 20])
    assert [x["function"] for x in data["layers"]] == ["Structure", "Finish1"]
    assert data["layers"][0]["material_id"] == 3001
    assert data["layers"][0]["material_identity"]["unique_id"] == "material-3001"
    assert data["layers"][0]["material_name_match_count"] == 1
    assert data["layers"][1]["material_id"] == -1 and data["layers"][1]["material_identity"] is None
    report = compare_type_definition(observed, unique_id=kind + "-uid", factory_op=factory(kind))
    assert all(check["status"] == "matched" for check in report["checks"].values())
    assert "full_type_definition" in report["claims"]["not_evaluated"]
    assert report["claims"]["current_model_state"] == "not_established"


@pytest.mark.parametrize("case,key,status", [("wrong_width", "layers[0].width_mm", "mismatch"),
    ("wrong_total", "total_width", "mismatch"), ("wrong_function", "layers[0].function", "mismatch"),
    ("wrong_material", "layers[0].material", "mismatch"), ("material_case", "layers[0].material", "mismatch"),
    ("no_material", "layers[0].material", "mismatch"), ("ambiguous_material", "layers[0].material", "not_evaluated")])
def test_actual_wrong_values_cannot_match_expected_factory(native_rows, case, key, status):
    observed, _, _, _ = parse_rows(native_rows, case)
    report = compare_type_definition(observed, unique_id="wall-uid", factory_op=factory())
    assert report["checks"][key]["status"] == status


@pytest.mark.parametrize("case", ["structure_null", "layer_nan", "material_missing", "unsupported", "non_homogeneous"])
def test_unavailable_profile_keeps_every_expected_clause(native_rows, case):
    observed, _, _, _ = parse_rows(native_rows, case)
    report = compare_type_definition(observed, unique_id="wall-uid", factory_op=factory())
    assert len(report["checks"]) == 10 and all(row["status"] == "not_evaluated" for row in report["checks"].values())


def test_zero_width_membrane_is_lawful(native_rows):
    observed, _, _, _ = parse_rows(native_rows, "membrane")
    result = compare_type_definition(observed, unique_id="wall-uid", factory_op=factory(membrane=True))
    assert all(row["status"] == "matched" for row in result["checks"].values())


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1, "200"])
def test_bad_expected_numeric_input_cannot_create_vacuous_match(native_rows, bad):
    observed, _, _, _ = parse_rows(native_rows)
    expected = factory(); expected["layers"][0]["width_mm"] = bad
    with pytest.raises(ObservationRefusal, match="factory_definition_invalid"):
        compare_type_definition(observed, unique_id="wall-uid", factory_op=expected)


@pytest.mark.parametrize("fault", ["schema", "extra", "width_bool", "function", "material_id", "name_count", "material_uid", "row_missing"])
def test_malformed_profile_refuses_without_defaulted_facts(native_rows, fault):
    def change(rows):
        row = rows["wall"]; value = row["type_definition"]["value"]
        if fault == "schema": row["schema_version"] = "kir-element-state/1"
        elif fault == "extra": value["graphics_preserved"] = True
        elif fault == "width_bool": value["layers"][0]["width_mm"] = True
        elif fault == "function": value["layers"][0]["function"] = []
        elif fault == "material_id": value["layers"][0]["material_identity"]["element_id"] = 3002
        elif fault == "name_count": value["layers"][0]["material_name_match_count"] = True
        elif fault == "material_uid": value["layers"][0]["material_identity"]["unique_id"] = "floor-uid"
        else: del row["type_definition"]
    with pytest.raises(ObservationRefusal): parse_rows(native_rows, mutate=change)


def test_old_parser_does_not_accept_optin_fields_and_carrier_is_detached(native_rows):
    observed, query, response, auth = parse_rows(native_rows)
    with pytest.raises(ObservationRefusal):
        parse_element_observation(query, json.dumps(response), credentials=auth, request_id=response["request_id"])
    mutated = observed.rows; mutated["wall-uid"]["type_definition"]["value"]["layers"].clear()
    assert len(observed.rows["wall-uid"]["type_definition"]["value"]["layers"]) == 2
    assert observed.precondition.revision == 18
    with pytest.raises(FrozenInstanceError): observed.digest = "new"
    with pytest.raises(TypeError): TypeDefinitionObservation()


@pytest.mark.parametrize("field,value", [("material_name", "Different"), ("material_name_match_count", 2)])
def test_same_revision_material_facts_cannot_contradict_between_types(native_rows, field, value):
    def change(rows):
        rows["floor"]["type_definition"]["value"]["layers"][0][field] = value
    with pytest.raises(ObservationRefusal, match="conflicting_material_observation"):
        parse_rows(native_rows, mutate=change)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_global_material_name_count_covers_distinct_observed_ids_only_as_lower_bound(native_rows, count):
    def change(rows):
        wall = rows["wall"]["type_definition"]["value"]["layers"][0]
        floor = rows["floor"]["type_definition"]["value"]["layers"][0]
        wall["material_name_match_count"] = floor["material_name_match_count"] = count
        floor["material_id"] = floor["material_identity"]["element_id"] = 3002
        floor["material_identity"]["unique_id"] = "material-3002"
    if count < 2:
        with pytest.raises(ObservationRefusal, match="material_name_count"):
            parse_rows(native_rows, mutate=change)
    else:
        observed, _, _, _ = parse_rows(native_rows, mutate=change)
        # A third unqueried material is legal; it prevents unique-name match.
        for kind in ("wall", "floor"):
            report = compare_type_definition(observed, unique_id=kind + "-uid", factory_op=factory(kind))
            assert report["checks"]["layers[0].material"]["status"] == "not_evaluated"


def test_same_ordinal_name_cannot_report_different_catalog_counts(native_rows):
    def change(rows):
        floor = rows["floor"]["type_definition"]["value"]["layers"][0]
        floor["material_id"] = floor["material_identity"]["element_id"] = 3002
        floor["material_identity"]["unique_id"] = "material-3002"
        floor["material_name_match_count"] = 2
    with pytest.raises(ObservationRefusal, match="conflicting_material_name_count"):
        parse_rows(native_rows, mutate=change)


@pytest.mark.parametrize("target", ["wall", "floor", "level", "element-type"])
def test_known_native_roles_cannot_be_materials_even_when_full_identity_agrees(native_rows, target):
    def change(rows):
        material = rows["wall"]["type_definition"]["value"]["layers"][0]
        if target in ("wall", "floor"):
            typed = rows[target]
            material.update(material_id=typed["element_identity"]["element_id"],
                material_identity=deepcopy(typed["element_identity"]), material_name=typed["name"])
        elif target == "element-type":
            rows["floor"]["type_definition"] = {"status": "not_applicable", "reason": "unsupported_element_kind", "value": None}
            rows["floor"]["type_state"] = {"status": "observed", "element_identity_status": "captured",
                "element_identity_reason": None, "element_identity": deepcopy(material["material_identity"])}
        else:
            from kir.tests.test_revit_observation import row as level_row
            typed = level_row("floor-uid")
            typed.update(schema_version="kir-element-state/2",
                element_identity=deepcopy(material["material_identity"]),
                type_definition={"status": "not_applicable", "reason": "unsupported_element_kind", "value": None})
            # Keep the requested opaque UID consistent with the shared proof;
            # this reaches role checking, not the generic UID mismatch guard.
            material["material_identity"]["unique_id"] = "floor-uid"
            typed["element_identity"]["unique_id"] = "floor-uid"
            rows["floor"] = typed
    with pytest.raises(ObservationRefusal, match="material_role_conflict"):
        parse_rows(native_rows, mutate=change)


def resign_claims(value):
    from kir.project import _hash
    value["observation_digest"] = _hash({key: value[key] for key in
        ("target", "precondition", "operation_id", "source_sha256", "rows")})
    return value


def test_structural_validators_are_pure_and_do_not_restore_authority(native_rows, monkeypatch):
    import kir.compiler
    import kir.revit_transport
    import kir.type_definition_observation as owner
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    def forbidden(*args, **kwargs): pytest.fail("structural validator performed an external/compile action")
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.compiler, "compile_program", forbidden)
    monkeypatch.setattr(kir.revit_transport, "exchange", forbidden)
    monkeypatch.setattr(owner, "assess_connector_query_response", forbidden)
    assert observed.validate() is None and validate_type_definition_claims(claims) is None
    assert type(claims) is dict
    with pytest.raises(ObservationRefusal, match="type_definition_observation_required"):
        compare_type_definition(claims, unique_id="wall-uid", factory_op=factory())
    with pytest.raises(TypeError): TypeDefinitionObservation(**claims)


@pytest.mark.parametrize("fault", ["source", "digest", "target", "rows", "not-deep-frozen"])
def test_carrier_revalidation_rejects_accidental_tampering(native_rows, fault):
    from types import MappingProxyType
    from kir.project import _object
    observed, _, _, _ = parse_rows(native_rows)
    altered = copy(observed)
    if fault == "source": object.__setattr__(altered, "source_sha256", "0" * 64)
    elif fault == "digest": object.__setattr__(altered, "digest", "0" * 64)
    elif fault == "target": object.__setattr__(altered, "target", observed.target.to_dict())
    elif fault == "not-deep-frozen": object.__setattr__(altered, "_rows", MappingProxyType(observed.rows))
    else:
        rows = observed.rows; rows["wall-uid"]["type_definition"]["value"]["total_width_mm"] += 1
        object.__setattr__(altered, "_rows", _object(rows, "changed"))
    with pytest.raises(ObservationRefusal): altered.validate()
    with pytest.raises(ObservationRefusal): compare_type_definition(altered, unique_id="wall-uid", factory_op=factory())
    assert observed.validate() is None


@pytest.mark.parametrize("fault", ["source-malformed", "source-uppercase", "query-uuid", "target-year", "target-uuid",
    "revision-bool", "revision-float", "view-bool", "scope-key", "scope-empty", "extra-field", "unknown-claim"])
def test_rehashed_inert_metadata_and_scope_errors_are_not_normalized(native_rows, fault):
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    if fault == "source-malformed": claims["source_sha256"] = "not-a-hash"
    elif fault == "source-uppercase": claims["source_sha256"] = "A" * 64
    elif fault == "query-uuid": claims["operation_id"] = "not-a-query-id"
    elif fault == "target-year": claims["target"]["revit_version"] = 2026
    elif fault == "target-uuid": claims["target"]["journal_id"] = "not-a-uuid"
    elif fault == "revision-bool": claims["precondition"]["revision"] = True
    elif fault == "revision-float": claims["precondition"]["revision"] = 18.0
    elif fault == "view-bool": claims["precondition"]["active_view_id"] = False
    elif fault == "scope-key": claims["rows"]["another-uid"] = claims["rows"].pop("wall-uid")
    elif fault == "scope-empty": claims["rows"] = {}
    elif fault == "extra-field": claims["native_authority"] = True
    else: claims["claims"]["current_model_state"] = "verified"
    with pytest.raises(ObservationRefusal): validate_type_definition_claims(resign_claims(claims))


def test_coherent_rehashed_claims_are_only_inert_data(native_rows):
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    claims["precondition"]["revision"] += 20
    claims["source_sha256"] = "b" * 64
    resign_claims(claims)
    assert validate_type_definition_claims(claims) is None
    assert claims["claims"]["current_model_state"] == "not_established"
    with pytest.raises(ObservationRefusal, match="type_definition_observation_required"):
        compare_type_definition(claims, unique_id="wall-uid", factory_op=factory())


@pytest.mark.parametrize("fault", ["material-count", "material-role"])
def test_inert_revalidation_reuses_role_and_name_consistency(native_rows, fault):
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    material = claims["rows"]["wall-uid"]["type_definition"]["value"]["layers"][0]
    if fault == "material-count":
        material["material_name_match_count"] = 0
    else:
        target = claims["rows"]["floor-uid"]
        material.update(material_id=target["element_identity"]["element_id"],
            material_identity=deepcopy(target["element_identity"]), material_name=target["name"])
    with pytest.raises(ObservationRefusal): validate_type_definition_claims(resign_claims(claims))


def test_claims_budget_and_deep_or_cyclic_input_are_named_refusals(native_rows, monkeypatch):
    import kir.type_definition_observation as owner
    observed, _, _, _ = parse_rows(native_rows)
    claims = observed.to_dict()
    cyclic = {}; cyclic["self"] = cyclic
    with pytest.raises(ObservationRefusal, match="type_definition_claims_budget"):
        validate_type_definition_claims(cyclic)
    monkeypatch.setattr(owner, "MAX_TYPE_DEFINITION_BYTES", 100)
    with pytest.raises(ObservationRefusal, match="type_definition_claims_budget"):
        validate_type_definition_claims(claims)


@pytest.mark.parametrize("case", ["curtain", "non_homogeneous", "structure_null", "structure_throw",
    "kind_throw", "layers_null", "layers_throw", "layer_width_throw", "function_throw", "layer_nan", "total_inf",
    "total_throw", "homogeneous_throw", "empty_layers", "too_many_layers", "material_id_null", "material_missing",
    "material_identity_throw", "material_lookup_throw", "material_catalog_throw", "material_name_throw"])
def test_actual_postcast_failure_keeps_type_role_in_live_and_inert_validation(native_rows, case):
    def change(rows):
        # Actual getter-produced unknown-definition row, not inferred from its
        # name or a fabricated successful full-definition value.
        known_type = deepcopy(native_rows["2026:" + case]["rows"]["wall"])
        assert known_type["status"] == "observed" and known_type["type_definition"]["value"] is None
        rows["wall"] = known_type
        material = rows["floor"]["type_definition"]["value"]["layers"][0]
        material.update(material_id=known_type["element_identity"]["element_id"],
            material_identity=deepcopy(known_type["element_identity"]), material_name=known_type["name"])
    with pytest.raises(ObservationRefusal, match="material_role_conflict"):
        parse_rows(native_rows, mutate=change)
    valid, _, _, _ = parse_rows(native_rows)
    values = {"wall": valid.rows["wall-uid"], "floor": valid.rows["floor-uid"]}
    change(values)
    claims = valid.to_dict()
    claims["rows"] = {"wall-uid": values["wall"], "floor-uid": values["floor"]}
    with pytest.raises(ObservationRefusal, match="material_role_conflict"):
        validate_type_definition_claims(resign_claims(claims))


def test_homogeneous_wall_keeps_native_compound_flag(native_rows):
    observed, _, _, _ = parse_rows(native_rows, "vertically_compound")
    wall = observed.rows["wall-uid"]["type_definition"]
    floor = observed.rows["floor-uid"]["type_definition"]
    assert wall["status"] == floor["status"] == "observed"
    assert wall["value"]["is_vertically_compound"] is True
    assert wall["value"]["is_vertically_homogeneous"] is True
    assert floor["value"]["is_vertically_compound"] is False
    assert [x["width_mm"] for x in wall["value"]["layers"]] == [200.0, 20.0]
