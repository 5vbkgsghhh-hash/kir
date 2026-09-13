"""Translation, ROTATION, and PERMISSIBLE reflection reach all three readers.

🔴 WHAT WAS TRUE ON 07.09.2026 BEFORE THE FIX. Exactly one move could move
an AUTHORED body — `rebind_body_frame(world_delta_mm=…)`, that is,
TRANSLATION. There was nothing to rotate an already-captured body with:
`with_frame` accepts any valid frame, but composing a rotation frame around
a world axis was left to the caller, and every caller would compose it on
its own — that is, differently. Reflection was named a refusal
(`invalid_frame`) and stopped there: the contract this refusal REQUIRES
("reflection requires a separate orientation contract") did not exist in
the tree.

WHAT IS TRUE NOW:

* `rotate_body_frame` rotates the PLACEMENT. `body_sha256` must stay the
  same — the shape is untouched, and this is checked, not promised;
* `mirror_body` reflects THE BODY ITSELF, leaving the frame a right-handed
  triple. Volume and the face count are preserved (reflection is an
  isometry), `body_sha256` CHANGES: a mirrored body is a different body,
  and this cannot be passed over in silence;
* a reflection recorded INTO THE FRAME is still a named refusal;
* both are seen identically by ALL THREE G02 readers — the standalone
  scene, the analysis, and the DirectShape emission — not just one of the
  three.
"""
from __future__ import annotations

import json
import math

import pytest

pytest.importorskip("OCP.BRepPrimAPI", reason="optional real OCCT backend")

from kir import dsl
from kir.geometry_authoring import (GeometryRefusal, author_bodies, mirror_body,
                                    rebind_body_frame, rotate_body_frame)
from kir.geometry_materialization import materialize_project, validate_geometry_bindings
from kir.geometry_readers import from_analysis, from_materialization, from_scene, one_geometry
from kir.occt_geometry import IDENTITY_FRAME
from kir.project import (PROJECT_SCHEMA_V2, BodyRepresentation, ModuleDefinition,
                         ModuleInstance, NamedOutput, ProjectRevision, RecipePin)
from kir.project_store import ProjectStore


STORE_V2 = "kir-project-store/2"
PLAN = [[0, 0], [18000, 0], [18000, 12000], [0, 12000]]
PROJECT = "dsl-placement"


def tower_program():
    dsl.reset(intent="корпус, который надо поставить на место")
    dsl.create_solid_extrusion(profile={"shape": "l", "origin": [0, 0], "size_mm": [18000, 12000],
                                        "cut_mm": [6000, 4000]},
                               height_mm=9000, category="mass", name="Корпус", id="slab")
    return dsl.build()


def placed(tmp_path, transform=lambda bundle: bundle, *, name="p.sqlite"):
    """An authored program -> bodies -> A PLACEMENT MOVE -> a saved project."""
    program = tower_program()
    recipe = RecipePin(json.dumps(program, ensure_ascii=False, sort_keys=True), "b" * 64)
    parameters = {"plan": PLAN}
    bundles = author_bodies(program, project_id=PROJECT, instance_key="i",
                            recipe=recipe, parameters=parameters, frame=IDENTITY_FRAME)
    moved = {key: transform(bundle) for key, bundle in bundles.items()}
    outputs = [NamedOutput(operation["id"],
                           {"op": "create_directshape", "category": operation["category"],
                            "name": operation["name"]},
                           BodyRepresentation(moved[operation["id"]].digest,
                                              moved[operation["id"]].body_digest))
               for operation in program["ops"]]
    revision = ProjectRevision(
        PROJECT, [ModuleDefinition("m", "sealed_evaluation", recipe)],
        [ModuleInstance("i", "m", outputs, parameters=parameters)],
        intent=program.get("intent"), schema=PROJECT_SCHEMA_V2)
    assets = {bundle.digest: bundle for bundle in moved.values()}
    validate_geometry_bindings(revision, assets)
    store = ProjectStore.create(tmp_path / name, revision, schema=STORE_V2, assets=list(assets.values()))
    return store, moved


def readers(store):
    from kir.clash.project_analysis import analyze_project
    from kir.viewer.standalone_export import export_standalone_scene

    revision = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _i, output, _o in revision.geometry_references()}
    materialized = materialize_project(revision, bundles)
    scene = export_standalone_scene(materialized).to_dict()
    analysis, limits = from_analysis(analyze_project(store))
    return ({"scene": from_scene(scene), "emission": from_materialization(materialized),
             "analysis": analysis}, limits)


def turn(degrees, about=(0., 0., 0.)):
    return lambda bundle: rotate_body_frame(bundle, degrees=degrees, axis=(0., 0., 1.), about_mm=about)


def test_a_rotation_is_a_placement_and_never_a_new_body(tmp_path):
    """The shape is untouched: `body_sha256` is the same, the FRAME is different."""
    _store, original = placed(tmp_path, name="a.sqlite")
    _store2, turned = placed(tmp_path, turn(90.0, (9000., 6000., 0.)), name="b.sqlite")
    for key, bundle in original.items():
        assert turned[key].body_digest == bundle.body_digest
        assert turned[key].digest != bundle.digest
        assert turned[key].manifest["measurements"] == bundle.manifest["measurements"]
    # A 90° rotation around (9000, 6000): the matrix and the translation are named by numbers.
    assert turned["slab"].manifest["frame"] == pytest.approx(
        [0., -1., 0., 15000., 1., 0., 0., -3000., 0., 0., 1., 0., 0., 0., 0., 1.], abs=1e-9)


def test_a_rotation_round_trip_returns_the_original_placement(tmp_path):
    """CONTROL: −90° after +90° returns THE SAME bundle byte-for-byte."""
    _store, original = placed(tmp_path, name="a.sqlite")
    there = rotate_body_frame(original["slab"], degrees=37.5, axis=(0.2, -0.4, 1.), about_mm=(1000., 2000., 3000.))
    back = rotate_body_frame(there, degrees=-37.5, axis=(0.2, -0.4, 1.), about_mm=(1000., 2000., 3000.))
    assert there.digest != original["slab"].digest
    assert back.manifest["frame"] == pytest.approx(list(IDENTITY_FRAME), abs=1e-9)


@pytest.mark.parametrize("name,transform", [
    ("перенос", lambda bundle: rebind_body_frame(bundle, world_delta_mm=(130000., -40000., 9000.))),
    ("поворот", turn(90.0, (9000., 6000., 0.))),
    ("поворот вокруг наклонной оси", lambda bundle: rotate_body_frame(
        bundle, degrees=25.0, axis=(0., 1., 1.), about_mm=(0., 0., 0.))),
    ("отражение тела", lambda bundle: mirror_body(bundle, normal=(1., 0., 0.), through_mm=(9000., 0., 0.))),
])
def test_every_placement_reaches_all_three_readers_as_one_geometry(tmp_path, name, transform):
    """G02 on a placement move: three readers name ONE body and ONE frame."""
    store, moved = placed(tmp_path, transform, name="p.sqlite")
    rows, limits = readers(store)
    agreed = one_geometry(rows)
    assert limits == [] and len(agreed) == 1
    for oid, row in agreed.items():
        assert row["revision"] == store.head().revision_id
        assert row["unnamed_by"] == {}
        assert row["bundle_sha256"] == moved["slab"].digest
        assert row["body_sha256"] == moved["slab"].body_digest
        assert list(row["frame"]) == moved["slab"].manifest["frame"]
        assert row["modeling_tolerance_mm"] == moved["slab"].manifest["modeling_tolerance_mm"]


def test_a_reader_left_behind_on_the_old_placement_is_named(tmp_path):
    """REFUSAL CONTROL. A reader left on the old frame is caught."""
    store, _moved = placed(tmp_path, turn(90.0), name="p.sqlite")
    rows, _limits = readers(store)
    oid = sorted(rows["analysis"])[0]
    stale = dict(rows["analysis"][oid])
    stale["frame"] = tuple(IDENTITY_FRAME)
    rows["analysis"] = {**rows["analysis"], oid: stale}
    with pytest.raises(GeometryRefusal) as caught:
        one_geometry(rows)
    assert caught.value.code == "reader_disagreement" and ".frame" in str(caught.value)


def test_a_mirror_keeps_volume_and_faces_but_is_honestly_another_body(tmp_path):
    """PERMISSIBLE reflection: an isometry of the shape, a RIGHT-HANDED frame, a different body name."""
    _store, original = placed(tmp_path, name="a.sqlite")
    source = original["slab"]
    mirrored = mirror_body(source, normal=(1., 0., 0.), through_mm=(9000., 0., 0.))
    before, after = source.manifest["measurements"], mirrored.manifest["measurements"]
    assert after["volume_mm3"] == pytest.approx(before["volume_mm3"], rel=1e-9)
    assert after["face_count"] == before["face_count"] and after["solid_count"] == 1
    # The shape is DIFFERENT (the L-shaped plan is asymmetric), while the placement is the same.
    assert mirrored.body_digest != source.body_digest
    assert mirrored.manifest["frame"] == source.manifest["frame"] == list(IDENTITY_FRAME)
    assert mirrored.manifest["binding"] == source.manifest["binding"]
    assert mirrored.manifest["recipe"] == source.manifest["recipe"]
    # 🔴 THE INVOLUTION IS GEOMETRIC, NOT BYTE-FOR-BYTE, AND THIS IS A
    # MEASUREMENT, NOT AN ASSUMPTION. A second reflection about the same
    # plane returns THE SAME shape (volume, centroid, bounding box, face
    # count all match), but `body_sha256` DOES NOT come back: the cycle
    # "parse -> BRepBuilderAPI -> write" re-emits the ASCII BRep
    # differently — the same measured fact because of which `with_frame`
    # does not call the kernel at all. Demanding byte equality here would
    # mean writing into the instrument an expectation the kernel does not
    # give.
    twice = mirror_body(mirrored, normal=(1., 0., 0.), through_mm=(9000., 0., 0.))
    again = twice.manifest["measurements"]
    assert again["volume_mm3"] == pytest.approx(before["volume_mm3"], rel=1e-9)
    assert again["centroid_mm"] == pytest.approx(before["centroid_mm"], abs=1e-6)
    assert again["bbox_min_mm"] == pytest.approx(before["bbox_min_mm"], abs=1e-6)
    assert again["bbox_max_mm"] == pytest.approx(before["bbox_max_mm"], abs=1e-6)
    assert again["face_count"] == before["face_count"]


def test_a_reflection_written_into_the_frame_stays_a_named_refusal(tmp_path):
    """A left-handed frame would silently flip the normals for EVERY reader."""
    _store, original = placed(tmp_path, name="a.sqlite")
    reflected = (-1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)
    with pytest.raises(GeometryRefusal) as caught:
        original["slab"].with_frame(reflected)
    assert caught.value.code == "invalid_frame" and "reflection" in str(caught.value)


@pytest.mark.parametrize("kwargs,code", [
    ({"degrees": float("nan")}, "invalid_input"),
    ({"degrees": 30.0, "axis": (0., 0., 0.)}, "invalid_input"),
    ({"degrees": 30.0, "about_mm": (0., 0.)}, "invalid_input"),
])
def test_a_placement_that_cannot_be_named_is_refused_not_approximated(tmp_path, kwargs, code):
    _store, original = placed(tmp_path, name="a.sqlite")
    with pytest.raises(GeometryRefusal) as caught:
        rotate_body_frame(original["slab"], **kwargs)
    assert caught.value.code == code


def test_a_mirror_needs_a_direction_and_says_so(tmp_path):
    _store, original = placed(tmp_path, name="a.sqlite")
    with pytest.raises(GeometryRefusal) as caught:
        mirror_body(original["slab"], normal=(0., 0., 0.))
    assert caught.value.code == "invalid_input"
