"""Planning must not change native ownership; lineage is semantic, not a label."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from kir.compiler import compile_program, plan_program
from kir import spec
from kir.emit_core import lineage_token
from kir.tests.fixtures import GROUND_SNAPSHOT
from kir.tests.test_a_stable_address_is_not_permission import BASE, owners


@pytest.mark.parametrize("version", spec.REVIT_VERSIONS)
def test_dict_and_typed_plan_emit_the_same_native_owner(version):
    program = dict(BASE, lineage="residential")
    direct = compile_program(program, revit_version=version, snapshot=GROUND_SNAPSHOT)
    planned = compile_program(plan_program(program), revit_version=version, snapshot=GROUND_SNAPSHOT)
    assert direct.ok and planned.ok
    assert owners(planned.csharp) == [f"kir:{lineage_token('residential')}:WT1"]
    assert direct.csharp == planned.csharp


def test_neighbor_edits_do_not_rename_the_type_through_the_typed_path():
    program = dict(BASE, lineage="residential")
    changed = deepcopy(program)
    changed["ops"][1]["height_mm"] = 3100
    outputs = [compile_program(plan_program(value), snapshot=GROUND_SNAPSHOT)
               for value in (program, changed)]
    assert all(output.ok for output in outputs)
    assert owners(outputs[0].csharp) == owners(outputs[1].csharp)


def test_explicit_lineage_is_signed_and_legacy_absence_stays_absent():
    legacy = plan_program(BASE)
    owner = plan_program(dict(BASE, lineage="residential"))
    other = plan_program(dict(BASE, lineage="another-project"))
    assert legacy.to_evidence_dict()["schema"] == "kir-planned-program/4"
    assert "lineage" not in legacy.to_evidence_dict()
    assert owner.to_evidence_dict()["schema"] == "kir-planned-program/5"
    assert owner.lineage == owner.to_evidence_dict()["lineage"] == "residential"
    assert len({legacy.plan_digest, owner.plan_digest, other.plan_digest}) == 3
    with pytest.raises(ValueError, match="plan_digest"):
        replace(owner, lineage="another-project")


@pytest.mark.parametrize("lineage", ["", "a\n", "a" * 65, True, {"owner": "p"}])
def test_invalid_lineage_cannot_enter_a_typed_plan(lineage):
    with pytest.raises(ValueError, match="lineage"):
        replace(plan_program(BASE), lineage=lineage, plan_digest="")
    out = compile_program(dict(BASE, lineage=lineage), snapshot=GROUND_SNAPSHOT)
    assert not out.ok and any(item.field_name == "lineage" for item in out.diagnostics)


def test_local_witness_writer_names_the_actual_plan_schema(tmp_path, monkeypatch):
    from kir import witness_feed
    planned = plan_program({"lineage": "synthetic-observation", "ops": [
        {"op": "query_count", "id": "q", "kind": "wall"}]})
    path = tmp_path / "synthetic-witness.jsonl"
    # Restore before autouse environment auditing, independently of fixture order.
    with monkeypatch.context() as environment:
        environment.setenv("KIR_WITNESS_PATH", str(path))
        witness_feed.record_witness(program=planned, family="query", revit_version="2026",
            ok=True, witness={"readback_ok": True}, duration_ms=1, result_payload={"q": {"count": 1}})
    row = json.loads(path.read_text(encoding="utf-8"))
    assert row["plan_schema"] == "kir-planned-program/5"
    assert row["plan_digest"] == planned.plan_digest
