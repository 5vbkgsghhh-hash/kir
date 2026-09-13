"""Validate complete argument resources: isolated property tests miss broken refs."""
from copy import deepcopy
import json

import pytest
from jsonschema import Draft202012Validator

from kir import schema_dedup, schema_transport, serving
from kir.schema_gen import program_schema
from kir.tests.test_public_program_lineage import program


def assert_local_refs_resolve(schema):
    pending = [schema]
    seen = 0
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if "$ref" in item:
                assert item["$ref"].startswith("#/")
                target = schema
                for part in item["$ref"][2:].split("/"):
                    target = target[part.replace("~1", "/").replace("~0", "~")]
                assert isinstance(target, dict)
                seen += 1
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return seen


@pytest.mark.parametrize("dedup,script_first", [("0", "0"), ("1", "0"), ("0", "1"), ("1", "1")])
def test_serving_full_arguments_preserve_lineage_and_all_reference_targets(monkeypatch, dedup, script_first):
    monkeypatch.setenv("KIR_SCHEMA_DEDUP", dedup)
    monkeypatch.setenv("KIR_SCRIPT_FIRST", script_first)
    declared, _ = schema_transport.program_schema_for_tool()
    original = json.dumps(declared, sort_keys=True)
    tools = []
    serving.inject_revit_ir_schema(tools)
    whole = tools[0]["function"]["parameters"]
    Draft202012Validator.check_schema(whole)
    validator = Draft202012Validator(whole)
    validator.validate({"program": program()})
    validator.validate({"program": program("residential")})
    for value in (None, "", False, 1, "owner\n", "owner\r", "owner\u2028", "x" * 65):
        assert list(validator.iter_errors({"program": {**program(), "lineage": value}}))
    assert list(validator.iter_errors({"program": {**program(), "unknown_envelope": True}}))
    if script_first == "0":
        assert list(validator.iter_errors({"program": {**program(), "ops": [{"op": "invented"}]}}))
        assert schema_dedup.expand(whole)["properties"]["program"] == program_schema()
    count = assert_local_refs_resolve(whole)
    assert (count > 0) is (dedup == "1" and script_first == "0")
    assert json.dumps(declared, sort_keys=True) == original
    again = []
    serving.inject_revit_ir_schema(again)
    assert again == tools
    serving.inject_revit_ir_schema(tools)
    assert len(tools) == 1


def test_lifting_is_detached_and_cannot_adopt_conflicting_or_independent_definitions():
    child = schema_dedup.hoist(program_schema())
    wrapper = {"type": "object", "properties": {"program": child}}
    before = deepcopy(wrapper)
    embedded = schema_dedup.lift_property_defs(wrapper, "program")
    assert wrapper == before and "$defs" in child
    assert "$defs" in embedded and "$defs" not in embedded["properties"]["program"]
    assert assert_local_refs_resolve(embedded) > 0
    first = next(iter(embedded["$defs"]))
    embedded["$defs"][first]["probe"] = True
    assert wrapper == before
    collision = {**wrapper, "$defs": {first: {"type": "null"}}}
    with pytest.raises(ValueError, match="collide"):
        schema_dedup.lift_property_defs(collision, "program")
    identified = deepcopy(wrapper)
    identified["properties"]["program"]["$id"] = "urn:kir:independent-test-resource"
    with pytest.raises(ValueError, match="independent"):
        schema_dedup.lift_property_defs(identified, "program")
