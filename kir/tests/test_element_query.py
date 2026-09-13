"""Typed UniqueId query: registry/planning/emission, not live Revit readback."""
import pytest

from kir import compile_program, plan_program, sdk, spec
from kir.schema_gen import program_schema


UID = "00112233-4455-6677-8899-aabbccddeeff-00000123"


def program(value=UID):
    return {"ops": [{"op": "query_element_state", "id": "read", "unique_id": value}]}


@pytest.mark.parametrize("version", ["2021", "2022", "2023", "2024", "2025", "2026"])
def test_identity_query_is_read_only_and_uses_native_uid_and_project_relative_level_value(version):
    compiled = compile_program(program(), revit_version=version)
    assert compiled.ok, [d.as_dict() for d in compiled.diagnostics]
    assert compiled.planned.family.value == "query"
    assert f'doc.GetElement("{UID}")' in compiled.csharp
    assert ".ProjectElevation" in compiled.csharp and ".Elevation" in compiled.csharp
    assert "BuiltInParameter.LEVEL_ELEV" in compiled.csharp
    assert "BuiltInParameter.LEVEL_RELATIVE_BASE_TYPE" in compiled.csharp
    assert '"name_match_count"' in compiled.csharp
    assert '"name_resolves_builtin"' in compiled.csharp
    assert '"not_found"' in compiled.csharp and '"identity_mismatch"' in compiled.csharp
    assert '"level_parameter_identity_mismatch"' in compiled.csharp
    assert '"element_identity_status"' in compiled.csharp
    assert "new Transaction(" not in compiled.csharp
    assert ".Set(" not in compiled.csharp and "Math.Round(" not in compiled.csharp
    assert "FilteredElementCollector" not in compiled.csharp
    assert (".IntegerValue" in compiled.csharp) is (version <= "2023")


@pytest.mark.parametrize("value", [None, True, 700, {}, [], "", "   "])
def test_missing_or_wrong_uid_is_a_typed_refusal(value):
    compiled = compile_program(program(value))
    assert not compiled.ok
    assert any(d.code == "KIR-T001" and d.field_name == "unique_id" for d in compiled.diagnostics)
    assert not any(d.code == "KIR-P000" for d in compiled.diagnostics)


def test_missing_field_and_overbudget_uid_refuse_without_silent_numeric_fallback():
    missing = program()
    del missing["ops"][0]["unique_id"]
    assert not compile_program(missing).ok
    cap = spec.OPS["query_element_state"].params[0].max_val
    assert compile_program(program("x" * cap)).ok
    result = compile_program(program("x" * (cap + 1)))
    assert not result.ok and any(d.code == "KIR-T002" for d in result.diagnostics)
    result = compile_program({"ops": [{"op": "query_element_state", "id": "read",
                                       "unique_id": UID, "element_id": 700}]})
    assert not result.ok


@pytest.mark.parametrize("uid", [" " + UID + " ", UID.upper(), 'opaque"\\value', "opaque\nvalue", "UID-Ж😀"])
def test_opaque_uid_is_never_trimmed_or_case_folded_and_is_escaped(uid):
    compiled = compile_program(program(uid))
    assert compiled.ok, compiled.diagnostics
    assert compiled.planned.to_ops()[0]["unique_id"] == uid
    assert 'requested_unique_id' in compiled.csharp


def test_registry_generated_sdk_and_schema_expose_the_same_contract():
    op = sdk.query_element_state(unique_id=UID, id="read")
    planned = plan_program({"ops": [op]})
    assert planned.to_ops() == program()["ops"]
    variants = program_schema()["properties"]["ops"]["items"]["oneOf"]
    schema = next(row for row in variants if row["properties"]["op"].get("const") == "query_element_state")
    assert schema["properties"]["unique_id"]["maxLength"] == 512
    assert "unique_id" in schema["required"] and not schema["additionalProperties"]


def test_multiple_queries_have_distinct_outer_blocks_and_keep_full_scope():
    ops = [dict(program()["ops"][0], id="level"),
           dict(program()["ops"][0], id="protected", unique_id="other-uid")]
    result = compile_program({"ops": ops}, revit_version="2026")
    assert result.ok, result.diagnostics
    assert result.csharp.count("// query_element_state ") == 2
    assert '__results["level"]' in result.csharp and '__results["protected"]' in result.csharp
