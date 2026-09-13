"""The author's program (not an example) -> an OCCT body -> ONE reader for all three.

🔴 THE BEFORE MEASUREMENT (07.09.2026,
`.work/marathon-fable-20260907/geo/`): a `kir.dsl` program with
`create_solid_blend` + `create_solid_boolean`, laid into `ProjectStore`
via the existing path, gave `bodies_declared 0 / bodies_with_geometry 0`
— the language knew how to SAY a loft with an atrium, the project did not
know how to HAVE one. Rich geometry only entered through trusted examples
(`examples/curved_podium.py`, `examples/podium_passage.py`), which
themselves call OCP directly: a path unreachable from either the SDK or
the authored script's sandbox.

🔴 THE BEFORE MEASUREMENT for G02: not one of the three readers named the
modeling tolerance of the chosen body; the analysis report named neither
the bundle, nor the body, nor the frame.
"""
from __future__ import annotations

import json

import pytest

pytest.importorskip("OCP.BRepPrimAPI", reason="optional real OCCT backend")

from kir import dsl
from kir.geometry_authoring import (BODY_OPS, GeometryRefusal, author_project,
                                    build_body)
from kir.geometry_materialization import materialize_project
from kir.geometry_readers import from_analysis, from_materialization, from_scene, one_geometry
from kir.occt_geometry import IDENTITY_FRAME
from kir.project import RecipePin
from kir.project_store import ProjectStore

STORE_V2 = "kir-project-store/2"
LOW = [[0, 0], [24000, 0], [24000, 18000], [0, 18000]]
TOP = [[3000, 3000], [21000, 3000], [21000, 15000], [3000, 15000]]


def atrium_program():
    """An AUTHORED program, not an instrument fixture: only registry ops."""
    dsl.reset(intent="башня с атриумом")
    dsl.create_solid_blend(profile={"shape": "poly", "points_mm": LOW},
                           profile_top={"shape": "poly", "points_mm": TOP},
                           height_mm=12000, category="mass", name="Оболочка", id="shell")
    dsl.create_solid_boolean(operation="difference",
                             profile={"shape": "poly", "points_mm": LOW}, height_mm=12000,
                             parts=[{"shape": "cylinder", "center_mm": [12000, 9000, 6000],
                                     "radius_mm": 4000, "height_mm": 12000}],
                             category="mass", name="Стилобат с атриумом", id="podium")
    return dsl.build()


def authored(tmp_path, program=None, *, frame=IDENTITY_FRAME, tolerance=0.01, name="p.sqlite"):
    program = program if program is not None else atrium_program()
    revision, assets = author_project(
        program, project_id="dsl-atrium",
        recipe=RecipePin(json.dumps(program, ensure_ascii=False, sort_keys=True), "a" * 64),
        parameters={"low": LOW, "top": TOP}, frame=frame, modeling_tolerance_mm=tolerance)
    store = ProjectStore.create(tmp_path / name, revision, schema=STORE_V2,
                                assets=list(assets.values()))
    return store, revision, assets


def test_an_authored_dsl_program_saves_real_bodies(tmp_path):
    """A. A loft and a void, from the LANGUAGE, reach the saved project as bodies."""
    from kir.clash.project_analysis import analyze_project

    store, revision, assets = authored(tmp_path)
    assert [op["op"] for op in atrium_program()["ops"]] == ["create_solid_blend", "create_solid_boolean"]
    assert len(assets) == 2 and len(revision.geometry_references()) == 2

    report = analyze_project(store)
    assert report.bodies_declared == 2 and report.bodies_with_geometry == 2, report.to_dict()
    assert set(report.hull_source.values()) == {"brep"}, report.hull_source

    # A NUMBER THAT WAS NOT IN THE INPUT. Simpson's prismatoid formula for
    # the ruled side surface: V = h/6·(A_bottom + 4·A_middle + A_top). The
    # void is a cylinder.
    volumes = {bundle.to_dict()["manifest"]["binding"]["output_key"]:
               bundle.to_dict()["manifest"]["measurements"]["volume_mm3"]
               for bundle in assets.values()}
    prismatoid = 12000 / 6 * (24000 * 18000 + 4 * 21000 * 15000 + 18000 * 12000)
    assert volumes["shell"] == pytest.approx(prismatoid, rel=1e-6)
    assert volumes["podium"] == pytest.approx(24000 * 18000 * 12000 - 3.141592653589793 * 4000 ** 2 * 12000,
                                              rel=1e-4)
    # The void is NOT a label: the podium has one more face than a plain box.
    faces = {key: bundle.to_dict()["manifest"]["measurements"]["face_count"]
             for key, bundle in ((b.to_dict()["manifest"]["binding"]["output_key"], b)
                                 for b in assets.values())}
    assert faces == {"shell": 6, "podium": 7}


def test_reopen_keeps_the_same_body_bytes(tmp_path):
    store, _revision, assets = authored(tmp_path)
    again = ProjectStore.open(store.path)
    for bundle in assets.values():
        assert again.get_asset(bundle.digest).dumps() == bundle.dumps()


@pytest.mark.parametrize("operation,code", [
    ({"op": "create_solid_boolean", "id": "x", "operation": "intersect",
      "profile": {"shape": "poly", "points_mm": LOW}, "height_mm": 12000,
      "parts": [{"shape": "box", "center_mm": [900000, 0, 0], "size_mm": [1000, 1000, 1000]}],
      "category": "mass", "name": "n"}, "empty_boolean_result"),
    ({"op": "create_solid_extrusion", "id": "x", "profile": {"shape": "poly", "points_mm": LOW},
      "height_mm": 0.001, "category": "mass", "name": "n"}, "thin_body"),
    ({"op": "create_solid_blend", "id": "x", "profile": {"shape": "poly", "points_mm": LOW},
      "profile_top": {"shape": "poly", "points_mm": [[0, 0], [1, 0], [1, 1]]},
      "height_mm": 12000, "category": "mass", "name": "n"}, "unsupported_profile"),
    ({"op": "create_wall", "id": "x"}, "unsupported_op"),
])
def test_the_kernel_refuses_by_name_not_by_empty_geometry(operation, code):
    """Empty geometry and an exact zero are forbidden: the refusal has A NAME."""
    with pytest.raises(GeometryRefusal) as caught:
        build_body(operation)
    assert caught.value.code == code, str(caught.value)


def test_a_reflected_frame_is_refused_by_name(tmp_path):
    reflected = (-1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
    with pytest.raises(GeometryRefusal) as caught:
        authored(tmp_path, frame=reflected)
    assert caught.value.code == "invalid_frame"


def readers(store):
    from kir.clash.project_analysis import analyze_project
    from kir.viewer.standalone_export import export_standalone_scene

    revision = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _i, output, _o in revision.geometry_references()}
    materialized = materialize_project(revision, bundles)
    scene = export_standalone_scene(materialized).to_dict()
    report = analyze_project(store)
    analysis, limits = from_analysis(report)
    return ({"scene": from_scene(scene), "emission": from_materialization(materialized),
             "analysis": analysis}, limits, report)


@pytest.mark.parametrize("frame", [
    IDENTITY_FRAME,
    (1., 0., 0., 130000., 0., 1., 0., -40000., 0., 0., 1., 9000., 0., 0., 0., 1.),
    (0., -1., 0., 100000., 1., 0., 0., -50000., 0., 0., 1., 0., 0., 0., 0., 1.),
])
def test_three_readers_name_one_body_one_revision_one_frame_one_tolerance(tmp_path, frame):
    """G02. Translation and rotation are included; reflection is refused above, by name."""
    store, _revision, _assets = authored(tmp_path, frame=frame, tolerance=0.05)
    rows, limits, report = readers(store)
    agreed = one_geometry(rows)
    assert len(agreed) == 2
    for oid, row in agreed.items():
        assert row["revision"] == store.head().revision_id == report.revision
        assert row["frame"] == tuple(float(v) for v in frame)
        assert row["modeling_tolerance_mm"] == 0.05
        assert row["bundle_sha256"] and row["body_sha256"]
        # 🔴 MEASURED 07.09: before the fix, `body_geometry` stood here as
        # {"bundle_sha256": ["analysis"], "body_sha256": ["analysis"],
        #  "modeling_tolerance_mm": ["analysis"]} — the analysis was silent
        # about three fields out of five. An empty dict is exactly the
        # closed row for G02.
        assert row["unnamed_by"] == {}
    assert limits == []
    # The report says this OUT LOUD, not as a field of the object.
    payload = report.to_dict()
    assert set(payload["body_geometry"]) == set(payload["body_ids"])
    for oid, named in payload["body_geometry"].items():
        assert named["frame"] == list(frame) and named["modeling_tolerance_mm"] == 0.05
        assert named["bundle_sha256"] and named["body_sha256"]


def test_a_reader_that_names_another_body_is_refused(tmp_path):
    """REFUSAL CONTROL: swapping a body's number for one reader is caught."""
    store, _revision, _assets = authored(tmp_path)
    rows, _limits, _report = readers(store)
    oid = sorted(rows["scene"])[0]
    rows["scene"] = {**rows["scene"], oid: {**rows["scene"][oid], "bundle_sha256": "f" * 64}}
    with pytest.raises(GeometryRefusal) as caught:
        one_geometry(rows)
    assert caught.value.code == "reader_disagreement" and "bundle_sha256" in str(caught.value)


def test_body_ops_are_registry_names_only():
    from kir import spec

    assert set(BODY_OPS) <= set(spec.OPS)


# ── A REAL AUTHORING WORKFLOW: model script -> sandbox -> claim -> bodies ──

WORKFLOW_SCRIPT = '''
project_id = param("project_id", "atrium-workflow")
instance_key = param("instance_key", "i")
radius = param("atrium_radius_mm", 4000)
low = [[0,0],[24000,0],[24000,18000],[0,18000]]
top = [[3000,3000],[21000,3000],[21000,15000],[3000,15000]]
envelope(intent="башня с атриумом")
create_solid_blend(profile={"shape":"poly","points_mm":low},
                   profile_top={"shape":"poly","points_mm":top},
                   height_mm=12000, category="mass", name="Оболочка",
                   id=project_output_id(project_id, instance_key, "shell"))
create_solid_boolean(operation="difference", profile={"shape":"poly","points_mm":low},
                     height_mm=12000,
                     parts=[{"shape":"cylinder","center_mm":[12000,9000,6000],
                             "radius_mm":radius,"height_mm":12000}],
                     category="mass", name="Стилобат",
                     id=project_output_id(project_id, instance_key, "podium"))
'''


def workflow_base(project_id):
    from kir.project import (ModuleDefinition, ModuleInstance, NamedOutput,
                             PROJECT_SCHEMA_V2, ProjectRevision)

    return ProjectRevision(
        project_id, [ModuleDefinition("m", "sealed_evaluation", None)],
        [ModuleInstance("i", "m", [NamedOutput("placeholder",
                                               {"op": "create_level", "elev_mm": 0, "name": "Э1"})])],
        intent="башня с атриумом", schema=PROJECT_SCHEMA_V2)


def run_workflow(tmp_path, *, radius=4000, name="w.sqlite"):
    from kir.project import output_id
    from kir.project_merge import accept_proposal
    from kir.project_recipe import bind_recipe_result
    from kir.sandbox import SandboxPolicy, execute_author_script
    from kir.geometry_authoring import attach_recipe_bodies

    project_id = "atrium-workflow"
    parameters = {"project_id": project_id, "instance_key": "i", "atrium_radius_mm": radius}
    result = execute_author_script(WORKFLOW_SCRIPT,
                                   policy=SandboxPolicy(dsl_module="kir.recipe_language"),
                                   params=parameters)
    assert result.ok, result.refusal
    base = workflow_base(project_id)
    store = ProjectStore.create(tmp_path / name, base, schema=STORE_V2)
    binding = bind_recipe_result(
        base, instance_key="i", module_key="m", source=WORKFLOW_SCRIPT, parameters=parameters,
        output_bindings={key: output_id(project_id, "i", key) for key in ("shell", "podium")},
        result=result, author="автор", reason="атриум")
    assert binding.projection_refusal is None, binding.projection_refusal
    proposal, assets = attach_recipe_bodies(binding)
    acceptance = accept_proposal(store, proposal, expected_revision=base.revision_id,
                                 authorized_scope=proposal.scope, assets=list(assets.values()))
    assert acceptance.merge.clean
    return store, assets


def test_the_sandbox_authoring_path_reaches_real_occt_bodies(tmp_path):
    """A. A MODEL script (sandbox, chroot, zero network) -> bodies in storage.

    The sandbox does not import OCP and does not call `capture_body`: the
    bodies are built by the trusted caller, using the very SAME registry
    operations that the script named.
    """
    from kir.clash.project_analysis import analyze_project

    store, assets = run_workflow(tmp_path)
    report = analyze_project(store)
    assert report.bodies_declared == 2 and report.bodies_with_geometry == 2
    assert sorted(key for _i, key in report.body_keys.values()) == ["podium", "shell"]
    assert len(store.head().geometry_references()) == 2 and len(assets) == 2
    # The binding is not verified by us: a body with a foreign address/parameters will not pass.
    from kir.geometry_materialization import validate_geometry_bindings

    validate_geometry_bindings(store.head(), {a.digest: a for a in assets.values()})


def test_a_second_change_of_the_source_moves_the_body_and_the_readers(tmp_path):
    """A second change to the source: the bodies and all readers travel TOGETHER."""
    first, _assets = run_workflow(tmp_path, radius=4000, name="a.sqlite")
    second, _other = run_workflow(tmp_path, radius=6000, name="b.sqlite")
    rows_a, _l, _r = readers(first)
    rows_b, _l2, _r2 = readers(second)
    agreed_a, agreed_b = one_geometry(rows_a), one_geometry(rows_b)
    assert set(agreed_a) == set(agreed_b)
    # A different radius — a DIFFERENT body for EVERY reader, not just one.
    changed = [oid for oid in agreed_a if agreed_a[oid]["body_sha256"] != agreed_b[oid]["body_sha256"]]
    assert len(changed) == 1, (agreed_a, agreed_b)


# ─────────────── SELF-REVIEW: the probe came first, only what turned red was fixed ───────────────

def test_the_same_program_gives_the_same_body_bytes():
    """(b) Determinism: two runs of one program -> ONE `bundle_sha256`."""
    from kir.geometry_authoring import author_bodies

    program = {"ops": [{"op": "create_solid_blend", "id": "s",
                        "profile": {"shape": "poly", "points_mm": LOW},
                        "profile_top": {"shape": "poly", "points_mm": TOP},
                        "height_mm": 12000, "category": "mass", "name": "О"}]}
    options = dict(project_id="p", instance_key="i", recipe=RecipePin("x", "a" * 64), parameters={})
    first, second = author_bodies(program, **options), author_bodies(program, **options)
    assert first["s"].digest == second["s"].digest
    assert first["s"].body_digest == second["s"].body_digest
    assert first["s"].dumps() == second["s"].dumps()


def test_the_thin_body_threshold_is_read_not_written():
    """(c) The threshold is taken from the tolerance's owner, not written as a second literal."""
    import inspect

    from kir.geometry_authoring import DEFAULT_TOLERANCE_MM
    from kir.occt_geometry import capture_body

    owner = inspect.signature(capture_body).parameters["modeling_tolerance_mm"].default
    assert DEFAULT_TOLERANCE_MM == owner
    source = inspect.getsource(inspect.getmodule(build_body))
    assert "DEFAULT_TOLERANCE_MM: float = _signature(" in source, "порог снова стал литералом"
    # The threshold TRAVELS WITH the tolerance: the same bar becomes thin at a larger tolerance.
    slab = {"op": "create_solid_extrusion", "id": "x",
            "profile": {"shape": "poly", "points_mm": LOW}, "height_mm": 0.5,
            "category": "mass", "name": "n"}
    build_body(slab, modeling_tolerance_mm=0.01)
    with pytest.raises(GeometryRefusal) as caught:
        build_body(slab, modeling_tolerance_mm=1.0)
    assert caught.value.code == "thin_body" and "1.0" in str(caught.value)


def test_the_heaviest_program_the_registry_allows_refuses_by_name():
    """(a) The worst thing the registry allows refuses BY NAME, not by silence.

    The trusted caller has NO CPU/RSS isolation, and this is stated in the
    module's header. Budgets constrain the RESULT: exceeding the
    tessellation budget is a `budget_exceeded` refusal, with no silent
    coarsening and no empty body.
    """
    import math

    from kir.ops_boolean import BOOLEAN_PARTS_MAX
    from kir.occt_geometry import capture_body

    ring = [[round(200000 * math.cos(2 * math.pi * i / 256), 3),
             round(200000 * math.sin(2 * math.pi * i / 256), 3)] for i in range(256)]
    operation = {"op": "create_solid_boolean", "id": "h", "operation": "difference",
                 "profile": {"shape": "poly", "points_mm": ring}, "height_mm": 30000,
                 "parts": [{"shape": "sphere", "center_mm": [index * 40000 - 120000, 0, 15000],
                            "radius_mm": 12000.0} for index in range(BOOLEAN_PARTS_MAX - 1)],
                 "category": "mass", "name": "H"}
    shape = build_body(operation)                    # the kernel manages
    with pytest.raises(GeometryRefusal) as caught:   # the result — does not
        capture_body(shape, project_id="p", instance_key="i", output_key="h",
                     recipe=RecipePin("x", "a" * 64), parameters={})
    assert caught.value.code == "budget_exceeded"
    assert "no coarsening" in str(caught.value)


# ── "FINISH, THEN MODIFY": AN AUTHORED BODY GETS REPAIRED, NEIGHBORS STAY INTACT ──────────
#
# 🔴 THE BEFORE MEASUREMENT (07.09.2026, red on the end-to-end e2e
# instrument): the pair `tower-c/plinth × tower-c/shell` (contained, depth
# 3600 mm) could not be repaired by A SINGLE strategy — `propose_fix`
# answered "raise_clear needs a box parameter named 'plinth' on instance
# 'tower-c'; this output's shape is parameterised otherwise". The authored
# program places ALL bodies into one instance with ONE set of parameters,
# and by construction it has no box keyed to the output's name.

PLINTH = [[6000, 5000], [16000, 5000], [16000, 12000], [6000, 12000]]


def tower_program():
    dsl.reset(intent="ЖК: башня и стилобат")
    dsl.create_solid_blend(profile={"shape": "poly", "points_mm": LOW},
                           profile_top={"shape": "poly", "points_mm": TOP},
                           height_mm=12000, category="mass", name="Оболочка", id="shell")
    dsl.create_solid_extrusion(profile={"shape": "poly", "points_mm": PLINTH},
                               height_mm=3600, base_z_mm=0, category="mass",
                               name="Стилобат", id="plinth")
    return dsl.build()


def tower(tmp_path, name="tower.sqlite", **extra):
    from kir.geometry_authoring import author_project

    program = tower_program()
    revision, assets = author_project(
        program, project_id="tower-c", instance_key="tower-c",
        recipe=RecipePin(json.dumps(program, ensure_ascii=False, sort_keys=True), "a" * 64),
        parameters={"low": LOW, "top": TOP, "plinth": PLINTH, **extra})
    store = ProjectStore.create(tmp_path / name, revision, schema=STORE_V2,
                                assets=list(assets.values()))
    return store, revision


def test_an_authored_body_is_repaired_and_its_neighbours_stay_byte_identical(tmp_path):
    from kir.clash.project_analysis import analyze_project, reanalyze_after_fix
    from kir.project_fix import apply_fix, propose_fix

    store, revision = tower(tmp_path)
    report = analyze_project(store, exact=True)
    assert report.bodies_with_geometry == 2 and len(report.findings) == 1
    finding = report.findings[0]
    assert finding.relation == "contained" and finding.depth_mm == pytest.approx(3600.0)

    before = {output.key: output.geometry.bundle_sha256
              for _i, output, _o in revision.geometry_references()}
    neighbour = store.get_asset(before["shell"]).dumps()

    # The `raise_clear` default REFUSES BY NAME and names what to repair
    # with: a silent fallback would turn a named refusal into a silent success.
    from kir.project_fix import FixError, RAISE_CLEAR_BODY

    with pytest.raises(FixError) as refused:
        propose_fix(store, report, finding.finding_id)
    assert "parameterised otherwise" in str(refused.value)
    assert RAISE_CLEAR_BODY in str(refused.value)

    proposal, bundle = propose_fix(store, report, finding.finding_id,
                                   strategy=RAISE_CLEAR_BODY)
    assert proposal.strategy == RAISE_CLEAR_BODY
    assert len(proposal.changed_outputs) == 1
    assert proposal.world_lift_mm == pytest.approx(12050.0, abs=1e-3)
    assert "переносом фрейма" in proposal.describe()

    head = apply_fix(store, proposal, assets=[bundle], verify=True)
    assert head != revision.revision_id
    after = reanalyze_after_fix(store, exact=True)
    assert len(after.findings) == 0, [f.to_dict() for f in after.findings]

    reopened = ProjectStore.open(store.path)
    now = {output.key: output.geometry.bundle_sha256
           for _i, output, _o in reopened.head().geometry_references()}
    # THE NEIGHBOR IS UNTOUCHED — byte-for-byte, not "in meaning".
    assert now["shell"] == before["shell"]
    assert reopened.get_asset(now["shell"]).dumps() == neighbour
    assert now["plinth"] != before["plinth"]
    # The authored instance parameters are UNTOUCHED: the neighbors' manifests carry the very same ones.
    assert dict(reopened.head().instances[0].parameters) == dict(revision.instances[0].parameters)


def test_a_moved_authored_body_keeps_its_shape_and_only_its_place(tmp_path):
    """Moving the frame is a TRANSLATION: `body_sha256` is the same, the place is different."""
    from kir.geometry_authoring import rebind_body_frame

    store, revision = tower(tmp_path, name="shape.sqlite")
    original = store.get_asset(
        next(o.geometry.bundle_sha256 for _i, o, _x in revision.geometry_references()
             if o.key == "plinth"))
    moved = rebind_body_frame(original, world_delta_mm=(0.0, 0.0, 12050.0))
    assert moved.body_digest == original.body_digest
    assert moved.digest != original.digest
    was, now = (b.to_dict()["manifest"] for b in (original, moved))
    assert now["frame"][11] == pytest.approx(was["frame"][11] + 12050.0)
    assert [now["frame"][i] for i in range(16) if i != 11] == [was["frame"][i] for i in range(16) if i != 11]
    for field in ("binding", "recipe", "parameters", "measurements",
                  "modeling_tolerance_mm", "source_lineage", "units"):
        assert now[field] == was[field], field


def test_a_shared_axis_refuses_by_name_instead_of_moving_neighbours(tmp_path):
    """The `authored_body_needs_recipe_rebind` refusal, instead of a silent shift of the neighbors."""
    from kir.project_fix import FixError, propose_fix

    # The axis has lived in the instance's SHARED parameters FROM THE VERY
    # START: a fix can no longer place it there — every body's manifest
    # carries the owner's parameters, and storage rejects foreign ones
    # (`parameters_mismatch`). This is exactly why the authored path cannot
    # edit parameters for the sake of a single body.
    store, _revision = tower(tmp_path, name="axis.sqlite",
                             p0_mm=[0.0, 0.0, 0.0], p1_mm=[1000.0, 0.0, 0.0])
    report = analyze_project_of(store)
    with pytest.raises(FixError) as caught:
        propose_fix(store, report, report.findings[0].finding_id,
                    strategy="raise_clear_body")
    assert "authored_body_needs_recipe_rebind" in str(caught.value)


def analyze_project_of(store):
    from kir.clash.project_analysis import analyze_project

    return analyze_project(store, exact=True)


# ── A CURVED BODY MOVES THE SAME WAY A FLAT ONE DOES ─────────────────────────
#
# 🔴 THE BEFORE MEASUREMENT (07.09.2026, R4 red on the Q01 end-to-end
# instrument): for a loft with a 15° profile rotation and a shift,
# `_move_authored_body` answered "authored_body_needs_recipe_rebind: the
# transfer changed the body's BRep (e09f9279814a -> 88464fb690b8)", while
# on a boolean prism the same `raise_clear_body` worked. The cause was not
# "curvature": the transfer went into the kernel (`read_body()` ->
# `capture_body(frame=…)`), and the decompile + copy + write loop
# re-issued the B-spline side surfaces differently. BRep, the preview, and
# the measurements are LOCAL and do not depend on the frame — meaning the
# transfer does not need the kernel at all.

def turned(points, degrees, dx=0.0, dy=0.0):
    """A profile rotated about its own center and shifted — as in e2e."""
    import math

    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    return [[round(cx + (p[0] - cx) * cos - (p[1] - cy) * sin + dx, 6),
             round(cy + (p[0] - cx) * sin + (p[1] - cy) * cos + dy, 6)] for p in points]


CURVED_TOP = turned([[3000, 3000], [21000, 3000], [21000, 15000], [3000, 15000]],
                    15.0, 2500.0, -1800.0)


def curved_tower(tmp_path, name="curved.sqlite"):
    from kir.geometry_authoring import author_project

    program = {"intent": "ЖК: криволинейная оболочка и стилобат", "ops": [
        {"op": "create_solid_blend", "id": "shell",
         "profile": {"shape": "poly", "points_mm": LOW},
         "profile_top": {"shape": "poly", "points_mm": CURVED_TOP},
         "height_mm": 12000, "category": "mass", "name": "Оболочка"},
        {"op": "create_solid_extrusion", "id": "plinth",
         "profile": {"shape": "poly", "points_mm": PLINTH},
         "height_mm": 3600, "base_z_mm": 0, "category": "mass", "name": "Стилобат"}]}
    revision, assets = author_project(
        program, project_id="tower-c", instance_key="tower-c",
        recipe=RecipePin(json.dumps(program, ensure_ascii=False, sort_keys=True), "a" * 64),
        parameters={"low": LOW, "top": CURVED_TOP, "plinth": PLINTH})
    store = ProjectStore.create(tmp_path / name, revision, schema=STORE_V2,
                                assets=list(assets.values()))
    return store, revision


@pytest.mark.parametrize("moved_key", ["plinth", "shell"])
def test_a_curved_authored_body_moves_like_a_flat_one(tmp_path, moved_key):
    """R4. A loft with a 15° rotation is repaired by the SAME `raise_clear_body`."""
    from kir.clash.project_analysis import analyze_project, reanalyze_after_fix
    from kir.project_fix import RAISE_CLEAR_BODY, apply_fix, propose_fix

    store, revision = curved_tower(tmp_path, name=f"curved-{moved_key}.sqlite")
    report = analyze_project(store, exact=True)
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.relation == "contained"

    by_key = {output.key: output for _i, output, _o in revision.geometry_references()}
    address = {key: oid for _i, output, oid in revision.geometry_references()
               for key in (output.key,)}
    other_key = "shell" if moved_key == "plinth" else "plinth"
    neighbour_sha = by_key[other_key].geometry.bundle_sha256
    neighbour_bytes = store.get_asset(neighbour_sha).dumps()

    proposal, bundle = propose_fix(store, report, finding.finding_id,
                                   strategy=RAISE_CLEAR_BODY, move=address[moved_key])
    assert proposal.changed_outputs == frozenset({address[moved_key]})
    head = apply_fix(store, proposal, assets=[bundle], verify=True)
    assert head != revision.revision_id
    assert len(reanalyze_after_fix(store, exact=True).findings) == 0

    reopened = ProjectStore.open(store.path)
    now = {output.key: output.geometry for _i, output, _o in reopened.head().geometry_references()}
    # THE BODY IS THE SAME, THE PLACE IS DIFFERENT.
    assert now[moved_key].body_sha256 == by_key[moved_key].geometry.body_sha256
    assert now[moved_key].bundle_sha256 != by_key[moved_key].geometry.bundle_sha256
    # THE NEIGHBOR IS UNTOUCHED, BYTE FOR BYTE.
    assert now[other_key].bundle_sha256 == neighbour_sha
    assert reopened.get_asset(neighbour_sha).dumps() == neighbour_bytes


def test_a_move_rewrites_one_manifest_field_and_nothing_else(tmp_path):
    """The transfer does not rebuild the BRep, the preview, or the measurements — they are LOCAL."""
    from kir.geometry_authoring import rebind_body_frame

    store, revision = curved_tower(tmp_path, name="fields.sqlite")
    loft = store.get_asset(next(o.geometry.bundle_sha256 for _i, o, _x
                                in revision.geometry_references() if o.key == "shell"))
    moved = rebind_body_frame(loft, world_delta_mm=(1200.0, -300.0, 5000.0))
    was, now = loft.to_dict(), moved.to_dict()
    assert now["brep_base64"] == was["brep_base64"]        # byte for byte
    assert now["preview_mesh"] == was["preview_mesh"]
    assert now["bundle_sha256"] != was["bundle_sha256"]
    changed = [key for key in was["manifest"] if was["manifest"][key] != now["manifest"][key]]
    assert changed == ["frame"], changed
    for axis, delta in enumerate((1200.0, -300.0, 5000.0)):
        assert now["manifest"]["frame"][4 * axis + 3] == pytest.approx(
            was["manifest"]["frame"][4 * axis + 3] + delta)


def test_moving_a_body_never_needs_the_kernel(tmp_path, monkeypatch):
    """A CONTROL ON THE CAUSE: with the kernel unavailable, the transfer MUST still work.

    As long as the transfer went into OCP, a "curved" body and a "flat" one
    behaved differently. A kernel pulled out from under it distinguishes
    metadata from geometry better than words do.
    """
    from kir import occt_geometry
    from kir.geometry_authoring import rebind_body_frame

    store, revision = curved_tower(tmp_path, name="nokernel.sqlite")
    loft = store.get_asset(next(o.geometry.bundle_sha256 for _i, o, _x
                                in revision.geometry_references() if o.key == "shell"))

    def refuse():
        raise occt_geometry.GeometryRefusal("kernel_unavailable", "ядро снято зондом")

    monkeypatch.setattr(occt_geometry, "_kernel", refuse)
    moved = rebind_body_frame(loft, world_delta_mm=(0.0, 0.0, 5000.0))
    assert moved.body_digest == loft.body_digest
    with pytest.raises(occt_geometry.GeometryRefusal):   # the kernel is genuinely removed
        moved.measure()


def test_a_reflected_rebind_is_refused_by_name(tmp_path):
    """Reflection remains a refusal on transfer too: the frame is checked in full."""
    from kir.geometry_authoring import rebind_body_frame

    store, revision = curved_tower(tmp_path, name="reflect.sqlite")
    loft = store.get_asset(next(o.geometry.bundle_sha256 for _i, o, _x
                                in revision.geometry_references() if o.key == "shell"))
    with pytest.raises(GeometryRefusal) as caught:
        loft.with_frame((-1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.))
    assert caught.value.code == "invalid_frame"
    with pytest.raises(GeometryRefusal):
        rebind_body_frame(loft, world_delta_mm=(0.0, 0.0, float("inf")))
