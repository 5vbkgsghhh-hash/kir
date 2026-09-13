"""Explicit display-artifact fixtures, evaluated in a child process.

🔴 13.09.2026. This file used to live in `frontend/standalone/tests/`, although
not a line of it is JavaScript: it builds KIR display artifacts for the checks in
this directory. When the browser window was removed it would have been deleted
with that tree — it moved here instead, because its subject is the artifact
format, and the format stayed.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, output_id, _canonical, _hash
from kir.viewer.standalone import load_display_artifact
from kir.viewer.standalone_export import export_standalone_scene
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY

mode = sys.argv[1]
saved_workflow = None
if mode.startswith("codec-labels"):
    from kir.viewer.codec import SceneBuilder
    b = SceneBuilder()
    labels = {"codec-labels-empty": [], "codec-labels-single": [""],
              "codec-labels-last": ["first", ""],
              "codec-labels-unicode": ["A\u2028B\u2029C\u0085D\rE\vF\fG", ""]}[mode]
    for index, label in enumerate(labels):
        kind, slot = b.add_box((index * 10, 0, 0), (index * 10 + 1, 1, 1))
        b.add_element(element_id=f"box-{index}", category="control", level=None,
                      kind=kind, slot=slot, trust=3, fidelity=2, **({"label": label} if label else {}))
    print(base64.b64encode(b.finish({"fidelity_codes": {"exact": 0, "shaped": 1, "box_only": 2, "degenerate": 3, "no_body": 4}})).decode())
    raise SystemExit
if mode == "codec":
    from kir.viewer.codec import SceneBuilder
    b = SceneBuilder(origin_mm=(100000, -50000, -1200))
    def add(name, shape, fidelity=1):
        kind, slot = shape
        b.add_element(element_id=name, category="control", level="control-level", label=name,
                      kind=kind, slot=slot, trust=3, fidelity=fidelity)
    add("box", b.add_box((100000, -50000, -1200), (101000, -48000, 1800)), 2)
    add("capsule", b.add_capsule([(104000, -50000, -1200), (104000, -49000, -1200), (105000, -49000, -1200)], 100))
    add("prism", b.add_prism([[(107000, -50000), (108000, -50000), (107000, -49000)],
                              [(109000, -50000), (110000, -50000), (109000, -49000)]], -1200, 1800))
    for index in (0, 1):
        x = 112000 + index * 2000
        add(f"mesh-{index}", b.add_mesh([(x, -50000, -1200), (x + 1000, -50000, -1200),
                                         (x, -49000, -1200), (x, -50000, -200)],
                                         [(0, 2, 1), (0, 1, 3), (1, 2, 3), (2, 0, 3)]), 0)
    print(base64.b64encode(b.finish({"fidelity_codes": {"exact": 0, "shaped": 1, "box_only": 2, "degenerate": 3, "no_body": 4}})).decode())
    raise SystemExit
if mode == "saved-residential":
    from examples.residential_with_podium import continue_section, materialize_saved
    from kir.project_store import ProjectStore
    with tempfile.TemporaryDirectory(prefix="kir-browser-saved-residential-") as folder:
        path = str(Path(folder) / "project.sqlite")
        child = subprocess.run([sys.executable, "-c", """
import json, os, sys
from examples.residential_with_podium import create_store
store = create_store(sys.argv[1], stage='refined')
print(json.dumps({'pid': os.getpid(), 'revision': store.head().revision_id}))
""", path], capture_output=True, check=True, text=True, timeout=30)
        created = json.loads(child.stdout)
        store = ProjectStore.open(path, readonly=False)
        previous = store.head()
        assert previous.revision_id == created["revision"]
        untouched = [instance.to_dict() for instance in previous.instances[1:]]
        source_towers = []
        for instance in previous.instances[1:3]:
            op = dict(instance.outputs[0].to_dict()["operation"],
                      id=output_id(previous.project_id, instance.key, "concept-volume"))
            source_towers.append({"display_id": "p1/" + op["id"], "operation_sha256": _hash(op),
                "lower_mm": [[*point, op["base_z_mm"]] for point in op["profile"]["outer"]["points_mm"]],
                "upper_mm": [[*point, op["base_z_mm"] + op["height_mm"]]
                             for point in op["profile_top"]["outer"]["points_mm"]]})
        changed = continue_section(store, expected_revision=previous.revision_id,
                                   height_mm=4500., setback_mm=1200.)
        assert _canonical(untouched) == _canonical([instance.to_dict() for instance in changed.instances[1:]])
        assert [module.to_dict() for module in previous.modules] == [module.to_dict() for module in changed.modules]
        materialized = materialize_saved(store)
        program = materialized.to_program()
        assert [op["elev_mm"] for op in program["ops"] if op["op"] == "create_level"] == [0., 4500., 9000.]
        assert all(op["height_mm"] == 4500. for op in program["ops"] if op["op"] == "create_wall")
        top_wall = next(output.operation for output in changed.instances[0].outputs if output.key == "storey-03-wall-0")
        assert top_wall["p1_mm"][0] == 12800.
        saved_workflow = {"created_process": created["pid"], "resumed_process": os.getpid(),
            "parent_revision_id": previous.revision_id, "revision_id": changed.revision_id,
            "history_length": len(store.history()),
            "section_height_mm": changed.instances[0].parameters["storey_height_mm"],
            "section_setback_mm": changed.instances[0].parameters["terrace_setback_mm"],
            "untouched_before_sha256": _hash(untouched),
            "untouched_after_sha256": _hash([instance.to_dict() for instance in changed.instances[1:]]),
            "source_towers": source_towers}
elif mode == "duct-label":
    project = ProjectRevision("label-probe", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput("duct", {"op": "route_duct_system", "level": {"by": "name", "value": "L"},
            "diameter_mm": 200, "nodes": [{"id": "A", "xyz_mm": [0, 0, 3000]},
                                          {"id": "B", "xyz_mm": [5000, 0, 3000]}],
            "segments": [{"from": "A", "to": "B"}]})])])
    materialized = materialize_project(project, {})
elif mode in ("residential", "podium", "refined"):
    from examples.residential_with_podium import workflow
    revisions, bundle = workflow()
    index = {"podium": 2, "refined": 3, "residential": 4}[mode]
    materialized = materialize_project(revisions[index], {bundle.digest: bundle})
elif mode in ("label", "controls"):
    evil = '<img src=x onerror="globalThis.injected=true">'
    level_id = output_id("label-control", "i", "level")
    outputs = [
        NamedOutput("level", {"op": "create_level", "name": evil, "elev_mm": 0}),
        NamedOutput("wall", {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [4000, 0],
                             "height_mm": 3000, "level": {"by": "ref", "value": level_id}})]
    if mode == "controls":
        outputs.extend([
            NamedOutput("room", {"op": "create_room", "xy": [10000, 0], "level": {"by": "ref", "value": level_id}}),
            NamedOutput("floor", {"op": "create_floor", "outline": [[6000, 0], [9000, 0], [9000, 2000], [6000, 2000]],
                                  "level": {"by": "ref", "value": level_id}})])
        for index in (0, 1):
            x = 12000 + index * 2000
            outputs.append(NamedOutput(f"mesh-{index}", {"op": "create_directshape", "category": "mass", "name": "Tetrahedron",
                "mesh": {"vertices_mm": [[x, 0, 0], [x + 1000, 0, 0], [x, 1000, 0], [x, 0, 1000]],
                         "triangles": [[0, 2, 1], [0, 1, 3], [1, 2, 3], [2, 0, 3]]}}))
    project = ProjectRevision("label-control", [ModuleDefinition("m")], [ModuleInstance("i", "m", outputs)])
    materialized = materialize_project(project, {})
else:
    from examples.residential_project import concept
    materialized = materialize_project(concept(), {})
artifact = export_standalone_scene(materialized, consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
raw = artifact.dumps().encode()
validated = load_display_artifact(raw)
print(json.dumps({"artifact_base64": base64.b64encode(raw).decode(), "saved_workflow": saved_workflow, "transport": json.loads(
    json.dumps(dict(validated.transport), default=lambda value: dict(value) if hasattr(value, "items") else list(value)))}))
