"""Body ownership is authoring data; inspect/diff/store do not need OCP."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from kir.project import (BodyRepresentation, GeometryResolutionRequired, ModuleDefinition,
                         ModuleInstance, NamedOutput, PROJECT_SCHEMA, PROJECT_SCHEMA_V2,
                         ProjectError, ProjectRevision, RevisionConflict, output_id)
from kir.project_diff import diff_projects


REFERENCE = BodyRepresentation("a" * 64, "b" * 64)


def project(*, geometry=REFERENCE, extra=()):
    body = NamedOutput("solid", {"op": "create_directshape", "category": "mass", "name": "Body"}, geometry)
    return ProjectRevision("p", [ModuleDefinition("m")],
                           [ModuleInstance("body", "m", [body, *extra])], schema=PROJECT_SCHEMA_V2)


def test_old_format_is_checked_against_an_independent_literal_encoder():
    def sha(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode()).hexdigest()
    module = {"key": "m", "owner": "explicit", "recipe": None}
    body = {"schema": "kir-authoring-project/1", "project_id": "old",
            "ir_version": "1.0", "parent_revision": None, "intent": "",
            "metadata": {}, "modules": [module], "instances": [{
                "key": "i", "module_key": "m", "module_digest": sha(module),
                "parameters": {}, "metadata": {}, "outputs": [{
                    "key": "L", "operation": {"op": "create_level", "name": "L", "elev_mm": 0}}]}]}
    source = json.dumps({**body, "revision_id": sha(body)}, sort_keys=True,
                        ensure_ascii=False, separators=(",", ":"))
    restored = ProjectRevision.loads(source)
    assert restored.schema == PROJECT_SCHEMA
    assert restored.dumps() == source
    assert "geometry" not in restored.instances[0].outputs[0].to_dict()
    assert restored.to_program()["ops"][0]["id"] == output_id("old", "i", "L")


def test_upgrade_is_a_new_revision_and_preserves_namespace_and_legacy_payload():
    old = ProjectRevision("old", [ModuleDefinition("m")], [ModuleInstance("i", "m", {
        "L": {"op": "create_level", "name": "L", "elev_mm": 0}})])
    before = old.dumps()
    upgraded = old.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=old.revision_id)
    assert old.dumps() == before
    assert upgraded.parent_revision == old.revision_id
    assert upgraded.schema == PROJECT_SCHEMA_V2 and upgraded.revision_id != old.revision_id
    assert upgraded.to_program() == old.to_program()
    assert ProjectRevision.loads(upgraded.dumps()).dumps() == upgraded.dumps()
    assert upgraded.revise(expected_revision=upgraded.revision_id, intent="changed").schema == PROJECT_SCHEMA_V2
    with pytest.raises(RevisionConflict):
        old.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision="wrong")
    for selected in (PROJECT_SCHEMA, PROJECT_SCHEMA_V2, "future"):
        with pytest.raises(ProjectError):
            upgraded.upgrade_schema(selected, expected_revision=upgraded.revision_id)


def test_body_ref_requires_explicit_new_schema_and_never_has_an_implicit_mesh():
    selected = project()
    with pytest.raises(ProjectError, match="explicit upgrade"):
        replace(selected, schema=PROJECT_SCHEMA)
    restored = ProjectRevision.loads(selected.dumps())
    assert restored.dumps() == selected.dumps()
    assert restored.instances[0].outputs[0].geometry == REFERENCE
    assert "mesh" not in restored.instances[0].outputs[0].operation
    for method in (restored.to_program, restored.plan):
        with pytest.raises(GeometryResolutionRequired, match="geometry_resolution_required"):
            method()


@pytest.mark.parametrize("changes", [
    {"mesh": {"vertices_mm": [], "triangles": []}}, {"id": "other"},
    {"op": "create_wall"}, {"unknown": 1}, {"geometry": {}},
])
def test_body_owned_template_cannot_have_a_second_geometry_owner(changes):
    with pytest.raises(ProjectError):
        NamedOutput("shape", {"op": "create_directshape", **changes}, REFERENCE)


@pytest.mark.parametrize("digest", ["", "A" * 64, True, None, [], "a" * 63])
def test_malformed_reference_digest_is_rejected(digest):
    with pytest.raises(ProjectError):
        BodyRepresentation(digest, "b" * 64)


def test_inert_iterator_has_exact_order_addresses_and_no_mutable_payloads():
    follow = NamedOutput("mark", {"op": "set_param", "target": {"by": "ref", "value": output_id("p", "body", "solid")},
                                 "param": "Mark", "value": "body"})
    selected = project(extra=(follow,))
    rows = selected.addressed_outputs()
    assert [row[1].key for row in rows] == ["solid", "mark"]
    assert rows[0][2] == output_id("p", "body", "solid")
    assert selected.geometry_references() == (rows[0],)
    with pytest.raises(TypeError):
        rows[0][1].operation["name"] = "changed"


def test_diff_compares_body_descriptor_without_lowering_or_loading_assets(monkeypatch):
    follow = NamedOutput("mark", {"op": "set_param", "target": {"by": "ref", "value": output_id("p", "body", "solid")},
                                 "param": "Mark", "value": "body"})
    before = project(extra=(follow,))
    body = replace(before.instances[0].outputs[0], geometry=BodyRepresentation("c" * 64, "d" * 64))
    after = before.replace_instance(replace(before.instances[0], outputs=[body, follow]),
                                    expected_revision=before.revision_id)
    def forbidden(_self):
        raise AssertionError("inert diff must not invoke lowering")
    monkeypatch.setattr(ProjectRevision, "to_program", forbidden)
    result = diff_projects(before, after)
    first, second = [row[2] for row in before.addressed_outputs()]
    assert result.changed == (first,)
    assert result.affected == (second,)
    record = next(row for row in result.to_dict()["outputs"] if row["op_id"] == first)
    assert record["before"] == record["after"]  # template is unchanged, geometry owner is not
    assert record["geometry_before"] == REFERENCE.to_dict()
    assert record["geometry_after"] == body.geometry.to_dict()
    assert "geometry_source_changed" in record["reasons"]
    assert "operation_payload_changed" not in record["reasons"]
    assert diff_projects(after, after).unchanged == (first, second)


def test_opaque_draft_field_named_geometry_is_not_a_typed_body_reference():
    ordinary = NamedOutput("L", {"op": "create_level", "elev_mm": 0, "name": "L", "geometry": "opaque"})
    before = ProjectRevision("p", [ModuleDefinition("m")], [ModuleInstance("i", "m", [ordinary])])
    after = before.replace_instance(replace(before.instances[0], outputs=[
        replace(ordinary, operation={**ordinary.operation, "geometry": "different"})]),
        expected_revision=before.revision_id)
    assert before.geometry_references() == ()
    record = diff_projects(before, after).to_dict()["outputs"][0]
    assert "geometry_source_changed" not in record["reasons"]
    assert "geometry_before" not in record


def test_schema_context_change_is_visible_without_reinterpreting_existing_outputs():
    before = ProjectRevision("p", [ModuleDefinition("m")], [ModuleInstance("i", "m", {
        "L": {"op": "create_level", "name": "L", "elev_mm": 0}})])
    after = before.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=before.revision_id)
    diff = diff_projects(before, after).to_dict()
    assert not diff["changed"] and len(diff["affected"]) == 1
    assert diff["project_changes"]["schema"] == {"before": PROJECT_SCHEMA, "after": PROJECT_SCHEMA_V2}
