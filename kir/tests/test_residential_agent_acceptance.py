"""Independent authored/XY acceptance of the real saved residential pilot.

The demo uses actual Python worker/coordinator processes and an OCCT asset.
Neither these checks nor Python C# emission establish native Revit/BIM results.
All fixtures must be contained by an explicit .work pytest basetemp.
"""
import base64
from dataclasses import replace
import hashlib
import json
import math
import os
import subprocess
import sys

import pytest
from shapely.geometry import Polygon

from examples import residential_agent_workflow as pilot
from examples.residential_recipes import section_recipe
from kir.compiler import compile_program
from kir.project import _canonical, _thaw, output_id
from kir.project_merge import ChangeProposal, ProposalScope
from kir.project_refinement import refinement_view
from kir.project_store import ProjectStore
from kir.project_tasks import read_task, submit_task, task_history
from kir.section_plan_acceptance import assess_section_plan_change


def instances(project):
    return {item.key: item for item in project.instances}


def modules(project):
    return {item.key: item.to_dict() for item in project.modules}


def operations(project, key):
    return {out.key: _thaw(out.operation) for out in instances(project)[key].outputs}


def body_snapshot(store, project):
    descriptor = instances(project)["podium"].outputs[0].geometry
    assert descriptor is not None
    bundle = store.get_asset(descriptor.bundle_sha256)
    data = bundle.to_dict()
    brep = base64.b64decode(data["brep_base64"], validate=True)
    assert hashlib.sha256(brep).hexdigest() == descriptor.body_sha256 == bundle.body_digest
    assert descriptor.bundle_sha256 == bundle.digest
    assert data["manifest"]["units"] == "mm"
    return {"descriptor": descriptor.to_dict(), "bundle_bytes": bundle.dumps().encode(),
            "brep_bytes": brep, "frame": data["manifest"]["frame"]}


@pytest.fixture(scope="module")
def completed_demo(tmp_path_factory):
    directory = tmp_path_factory.mktemp("residential-demo")
    captured = {}
    original = pilot.initialize
    def capture_before_workers(path):
        store = original(path)
        captured["base"] = store.head()
        captured["body"] = body_snapshot(store, captured["base"])
        captured["history"] = tuple(revision.dumps() for revision in store.history())
        return store
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(pilot, "initialize", capture_before_workers)
        report = pilot.run_demo(directory / "project.sqlite")
    store = ProjectStore.open(directory / "project.sqlite")
    return store, report, captured


def assert_section_values(project, height, setback):
    ops = operations(project, "tower-a")
    expected_keys = [f"storey-{number:02d}-{suffix}" for number in (1, 2, 3)
                     for suffix in ("level", "slab", "wall-0", "wall-1", "wall-2", "wall-3", "space")]
    assert list(ops) == expected_keys
    holes = []
    for number in (1, 2, 3):
        prefix = f"storey-{number:02d}"
        assert ops[prefix + "-level"]["elev_mm"] == (number - 1) * height
        width = 14000 - (setback if number == 3 else 0)
        expected_outer = [[0, 0], [width, 0], [width, 9000], [0, 9000]]
        slab = ops[prefix + "-slab"]
        assert slab["contour"]["outer"]["points_mm"] == expected_outer
        assert len(slab["contour"]["holes"]) == 1
        ring = slab["contour"]["holes"][0]["points_mm"]
        void = Polygon(ring)
        assert void.bounds == (5000, 3000, 7000, 5000) and void.area == 4_000_000
        holes.append(void)
        region = Polygon(expected_outer, [ring])
        assert region.is_valid and region.area == width * 9000 - 4_000_000
        level_id = output_id(project.project_id, "tower-a", prefix + "-level")
        assert slab["level"] == {"by": "ref", "value": level_id}
        assert ops[prefix + "-space"]["level"] == {"by": "ref", "value": level_id}
        for side in range(4):
            wall = ops[f"{prefix}-wall-{side}"]
            assert wall["height_mm"] == height
            assert wall["p0_mm"] == expected_outer[side]
            assert wall["p1_mm"] == expected_outer[(side + 1) % 4]
            assert wall["level"] == {"by": "ref", "value": level_id}
    assert all(hole.equals(holes[0]) for hole in holes)


def assert_tower_b_geometry(project):
    ops = operations(project, "tower-b")
    assert list(ops) == ["concept-volume"]
    op = ops["concept-volume"]
    assert op["op"] == "create_solid_blend" and op["height_mm"] == 8 * 4100 and op["base_z_mm"] == 0
    bottom = op["profile"]["outer"]["points_mm"]
    top = op["profile_top"]["outer"]["points_mm"]
    assert bottom == [[24000, 0], [38000, 0], [38000, 9000], [24000, 9000]]
    assert len(top) == 4
    polygon = Polygon(top)
    assert polygon.is_valid and polygon.area == pytest.approx(126_000_000 * .82**2, rel=1e-12)
    assert (polygon.centroid.x, polygon.centroid.y) == pytest.approx((31000, 4500), abs=1e-7, rel=0)
    # Independent polar-vector check: preserves vertex correspondence and sees
    # actual -24 degree rotation, not just a parameter label or unchanged ID.
    for low, high in zip(bottom, top, strict=True):
        a = complex(low[0] - 31000, low[1] - 4500)
        b = complex(high[0] - 31000, high[1] - 4500)
        ratio = b / a
        assert abs(ratio) == pytest.approx(.82, abs=1e-12)
        assert math.degrees(math.atan2(ratio.imag, ratio.real)) == pytest.approx(-24, abs=1e-10)


def assert_xy_denominators(report, protected):
    expected = {
        "named_subject_retained": 21, "room_axis_enclosure": 3, "room_seed_in_slab_xy_region": 3,
        "selected_void_footprint_retained": 3, "selected_void_chain_xy_continuity": 2,
        "protected_instance_snapshot": len(protected),
    }
    for predicate, count in expected.items():
        rows = [row for row in report["rows"] if row["predicate"] == predicate]
        assert len(rows) == count and all(row["status"] == "evaluated" for row in rows)
    protected_rows = [row for row in report["rows"] if row["predicate"] == "protected_instance_snapshot"]
    assert {row["subject"] for row in protected_rows} == set(protected)
    unknown = {row["predicate"] for row in report["rows"] if row["status"] == "not_evaluated"}
    assert unknown == {"vertical_placement", "room_boundary_excludes_slab_holes", "native_realization",
                       "structural_safety", "runtime_liveness", "engineering_adequacy"}
    assert not any(row["status"] == "violated" for row in report["rows"])
    assert report["native_execution"] == "not_run" and report["ancestry"] == "not_checked"


def test_real_parallel_demo_preserves_sources_geometry_and_scoped_predicates(completed_demo):
    store, report, captured = completed_demo
    base = captured["base"]
    concurrent = store.get(report["concurrent_revision"])
    final = store.get(report["final_revision"])
    source = store.get(report["source_revision"])
    assert report["baseline_revision"] == base.revision_id
    for key, before, after in (("concurrent_diff", base, concurrent), ("resume_diff", concurrent, final)):
        difference = report[key]
        assert difference["scope"] == "authoring_only"
        assert difference["base_revision"] == before.revision_id
        assert difference["target_revision"] == after.revision_id
        assert difference["project_id"] == before.project_id == after.project_id
    first_accepts = report["coordinator"]["results"]
    resumed_accepts = report["resumed_coordinator"]["results"]
    assert len(first_accepts) == 2 and len(resumed_accepts) == 1
    for acceptance in [*first_accepts, *resumed_accepts]:
        digest = acceptance["selected_plan_digest"]
        assert type(digest) is str and len(digest) == 64
        assert all(character in "0123456789abcdef" for character in digest)
    conflicts = report["conflict"]["results"]
    assert len(conflicts) == 1 and conflicts[0]["selected_plan_digest"] is None
    assert report["workers"]["both_alive_at_release"] is True
    assert len({row["pid"] for row in report["workers"]["ready"]}) == 2
    assert all(row["evaluation_invoked"] and row["state"] == "submitted" for row in report["workers"]["results"])
    assert report["tasks"] == {"section-a": "accepted", "tower-b": "accepted", "section-conflict": "conflicted", "section-resume": "accepted"}
    assert tuple(revision.dumps() for revision in store.history()[:len(captured["history"])]) == captured["history"]
    assert_section_values(concurrent, 4500, 1200)
    assert_section_values(final, 4800, 1600)
    assert_tower_b_geometry(concurrent)
    assert_tower_b_geometry(final)
    for key in ("tower-c", "podium"):
        assert _canonical(instances(base)[key].to_dict()) == _canonical(instances(concurrent)[key].to_dict()) == _canonical(instances(final)[key].to_dict())
        module = instances(base)[key].module_key
        assert modules(base)[module] == modules(concurrent)[module] == modules(final)[module]
    assert instances(concurrent)["tower-b"].to_dict() == instances(final)["tower-b"].to_dict()
    assert body_snapshot(store, base) == body_snapshot(store, concurrent) == body_snapshot(store, final) == captured["body"]
    a = ChangeProposal.from_dict(read_task(store, "section-a")["proposal"])
    b = ChangeProposal.from_dict(read_task(store, "tower-b")["proposal"])
    assert a.base.dumps() == b.base.dumps() == base.dumps()
    assert instances(concurrent)["tower-a"].to_dict() == instances(a.candidate)["tower-a"].to_dict()
    assert instances(concurrent)["tower-b"].to_dict() == instances(b.candidate)["tower-b"].to_dict()
  # 🔴 +"tower-a-concept" (2026-09-07): the concept volume no longer
  # disappears on detailing, it stays in the head as a SEPARATE instance —
  # otherwise there would be nothing left to edit for the original form
  # after detailing. It is PROTECTED: a section edit has no right to touch
  # it, and the count of protected items rightly grew from 3 to 4.
    for candidate, protected in ((a.candidate, ["tower-b", "tower-c", "podium", "tower-a-concept"]),
                                 (concurrent, ["tower-c", "podium"]), (final, ["tower-c", "podium"])):
        view = refinement_view(candidate, "tower-a", source=source)
        old = refinement_view(base, "tower-a", source=source)
        assert view["source"] == old["source"] and view["losses"] == old["losses"]
        assert view["inactive_parameters"] == ["twist_deg"] and view["geometry_preservation"] == "not_claimed"
        assessment = assess_section_plan_change(base, candidate, source=source, instance_key="tower-a",
            required_void_chain=pilot.CHAIN, protected_instances=protected).to_dict()
        assert assessment["before_revision_id"] == base.revision_id and assessment["proposed_revision_id"] == candidate.revision_id
        assert assessment["source"]["revision_id"] == source.revision_id
        assert_xy_denominators(assessment, protected)
    # The actual coordinator accepted B first. Its A gate must protect B as it
    # existed in CURRENT, rather than falsely rejecting B's legitimate edit.
    actual_a_gate = report["coordinator"]["results"][1]["section_assessment"]
    assert actual_a_gate["before_revision_id"] != base.revision_id
    assert_xy_denominators(actual_a_gate, ["tower-b", "tower-c", "podium", "tower-a-concept"])


def test_redelivery_and_new_coordinator_only_read_historical_decision(completed_demo, monkeypatch):
    store, report, _ = completed_demo
    before = store.path.read_bytes()
    import kir.task_recipe_runner as runner
    monkeypatch.setattr(runner, "execute_author_script", lambda *a, **k: pytest.fail("worker replay executed source"))
    replayed = pilot.run_worker(store.path, "section-a")
    assert replayed["evaluation_invoked"] is False and replayed["state"] == "accepted"
    script = """
import json, sys
from kir.project_store import ProjectStore
from kir.project_tasks import task_history, decide_task
store = ProjectStore.open(sys.argv[1], readonly=False)
event = next(row for row in task_history(store, 'section-a') if row['kind'] == 'decide')
result = decide_task(store, 'section-a', request_id=event['request_id'], expected_version=event['previous'],
    generation=event['generation'], actor=event['actor'], proposal_id=event['body']['proposal_id'],
    expected_revision=event['body']['expected_revision'])
print(json.dumps({'inserted': result['inserted'], 'head': result['head_revision'],
                  'accepted': result['event']['result']['accepted_revision']}))
"""
    child = subprocess.run([sys.executable, "-B", "-c", script, str(store.path)],
        capture_output=True, text=True, timeout=60, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    acknowledged = json.loads(child.stdout)
    assert acknowledged == {"inserted": False, "head": report["final_revision"], "accepted": report["concurrent_revision"]}
    assert store.path.read_bytes() == before


def test_compiler_legal_room_in_void_is_refused_before_task_decision(tmp_path):
    store = pilot.initialize(tmp_path / "bad-room.sqlite")
    base = store.head()
    task = pilot.assign_recipe_task(store, "bad-room", section_recipe(base), actor="section-worker",
                                   expected_revision=base.revision_id)
    # An ordinary manually authored proposal, not a fabricated source_tool or
    # claimed sandbox execution. Preserve every typed role and original source.
    from examples import residential_refinement
    source = store.get(instances(base)["tower-a"].metadata["refinement"]["source"]["revision_id"])
    normal = residential_refinement.develop_section(base, source=source, height_mm=4500, setback_mm=1200)
    section = instances(normal)["tower-a"]
    bad_outputs = []
    for output in section.outputs:
        op = _thaw(output.operation)
        if output.key == "storey-02-space":
            op["xy"] = [6000, 4000]
        bad_outputs.append(replace(output, operation=op))
    candidate = base.replace_instance(replace(section, outputs=bad_outputs), expected_revision=base.revision_id)
    assert refinement_view(candidate, "tower-a", source=source)["binding_status"] == "exact_supplied_source"
    program = {"ir_version": candidate.ir_version, "intent": candidate.intent,
        "ops": [{**_thaw(output.operation), "id": output_id(candidate.project_id, "tower-a", output.key)}
                for output in instances(candidate)["tower-a"].outputs]}
    for year in ("2023", "2026"):
        compiled = compile_program(program, revit_version=year, snapshot=None)
        assert compiled.ok, compiled.diagnostics
    change = ChangeProposal(base, candidate, ProposalScope(instances=("tower-a",)), "section-worker", "Deliberate invalid room seed")
    submitted = submit_task(store, "bad-room", change, request_id="manual-proposal", expected_version=task["version"],
                            generation=task["generation"], actor="section-worker")
    before = store.path.read_bytes()
    with pytest.raises(pilot.PilotRefusal, match="section_xy_not_qualified") as error:
        pilot.accept_task(store, "bad-room", expected_revision=base.revision_id)
    rows = error.value.report["rows"]
    failed = [row for row in rows if row["predicate"] == "room_seed_in_slab_xy_region" and row["status"] == "violated"]
    assert len(failed) == 1 and failed[0]["subject"] == "storey-02-space"
    assert failed[0]["reason"] == "seed_outside_slab_material_xy"
    assert len([row for row in rows if row["predicate"] == "room_axis_enclosure" and row["status"] == "evaluated"]) == 3
    assert error.value.report["expected_subjects"]["rooms"] == [f"storey-{n:02d}-space" for n in (1, 2, 3)]
    assert store.path.read_bytes() == before and store.head().revision_id == base.revision_id
    assert read_task(store, "bad-room") == submitted["task"]
    assert all(event["kind"] != "decide" for event in task_history(store, "bad-room"))
