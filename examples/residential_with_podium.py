"""Three authored towers + a body-owned curved podium in one saved project.

Install the optional geometry extra with pip install -e '.[geometry]', then run explicitly:
    python examples/residential_with_podium.py --store NEW.sqlite

The /1 root and its tower recipe are reused unchanged. The history records an
explicit /2 upgrade, a podium asset, a schematic section, and its later edit.
This is not a geometry-faithful concept-to-BIM conversion: the section removes
the tower's twist/taper. Podium/tower contact at z=0 is not a native joined solid.
No Revit is used. Reported scene/code generation are planned, not observed BIM.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import struct

from examples import residential_project as towers
from kir.geometry_materialization import GeometryMaterialization, materialize_project
from kir.occt_geometry import GeometryBundle, GeometryRefusal, OCP_VERSION, capture_body
from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance, NamedOutput,
                         PROJECT_SCHEMA_V2, ProjectRevision, RecipePin, _canonical)
from kir.project_store import ProjectStore, ProjectStoreError, StoreConflict


PODIUM_MODULE = "residential-wide-podium-v1"
PODIUM_INSTANCE = "podium"
PODIUM_OUTPUT = "atrium-volume"
DEFAULTS = {"height_mm": 3000., "bulge_mm": 2000., "atrium_radius_mm": 2500.}
STAGES = ("root", "upgraded", "podium", "refined", "changed")


def recipe_pin() -> RecipePin:
    """Declared source/environment, not a claim of deterministic recipe replay."""
    from kir import occt_geometry

    source = Path(__file__).read_text(encoding="utf-8")
    dependencies = {"kir.occt_geometry": hashlib.sha256(
        Path(occt_geometry.__file__).read_bytes()).hexdigest()}
    environment = {"python": platform.python_version(), "ocp_package": OCP_VERSION,
                   "dependencies": dependencies}
    environment_digest = hashlib.sha256(json.dumps(environment, sort_keys=True).encode()).hexdigest()
    return RecipePin(source, environment_digest, entrypoint="build_podium_body",
                     dependencies=dependencies)


def build_podium_body(parameters: dict):
    """Five smooth sections and a real OCCT Boolean; no custom CAD algorithms."""
    try:
        valid = (isinstance(parameters, dict) and set(parameters) == set(DEFAULTS)
                 and all(type(value) in (int, float) and math.isfinite(value)
                         for value in parameters.values()))
    except OverflowError:
        valid = False
    if not valid:
        raise GeometryRefusal("invalid_recipe_parameters", "expected finite height, bulge, atrium radius")
    height, bulge, radius = (parameters[key] for key in DEFAULTS)
    if not (2000 <= height <= 6000 and 0 <= bulge <= 4000 and 1000 <= radius <= 4000):
        raise GeometryRefusal("unsupported_recipe_range", "wide-podium example range exceeded")
    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.TopTools import TopTools_ListOfShape
        from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir
    except ImportError as exc:
        raise GeometryRefusal("kernel_unavailable", "install kir-building[geometry]") from exc
    try:
        loft = BRepOffsetAPI_ThruSections(True, False, 0.01)
        loft.CheckCompatibility(True)
        loft.SetMutableInput(False)
        for fraction, weight in ((0., 0.), (.25, .5), (.5, 1.), (.75, .5), (1., 0.)):
            polygon = BRepBuilderAPI_MakePolygon()
            left, right = -2000. - bulge * weight, 65000. + bulge * weight
            for x, y in ((left, -5000.), (right, -5000.), (right, 14000.), (left, 14000.)):
                polygon.Add(gp_Pnt(x, y, -height + fraction * height))
            polygon.Close()
            if not polygon.IsDone():
                raise GeometryRefusal("kernel_build_failed", "podium section wire failed")
            loft.AddWire(polygon.Wire())
        loft.Build()
        if not loft.IsDone():
            raise GeometryRefusal("kernel_build_failed", "podium smooth loft failed")
        # Tower A ends at x=14000, tower B starts at 24000. Even the largest
        # permitted opening (15000..23000) stays in the clear gap at z=0.
        opening = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(19000., 4500., -height - 1000.), gp_Dir(0, 0, 1)),
            radius, height + 2000.).Shape()
        arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        arguments.Append(loft.Shape())
        tools.Append(opening)
        cut = BRepAlgoAPI_Cut()
        cut.SetArguments(arguments)
        cut.SetTools(tools)
        cut.SetNonDestructive(True)
        cut.Build()
        if not cut.IsDone():
            raise GeometryRefusal("kernel_build_failed", "podium atrium Boolean failed")
        return cut.Shape()
    except GeometryRefusal:
        raise
    except Exception as exc:
        raise GeometryRefusal("kernel_build_failed", str(exc)) from exc


def add_podium(project: ProjectRevision) -> tuple[ProjectRevision, GeometryBundle]:
    """Explicitly evaluate a new output; failure cannot modify the prior value."""
    if project.schema != PROJECT_SCHEMA_V2:
        raise GeometryRefusal("schema_upgrade_required", "upgrade the authoring project explicitly first")
    if project.project_id != towers.PROJECT_ID or any(
            item.key == PODIUM_INSTANCE for item in project.instances):
        raise GeometryRefusal("example_scope_mismatch", "expected the unmodified three-tower project")
    expected = towers.concept()
    # The footprint/atrium recipe is fitted to this declared example layout,
    # not to arbitrary towers. Do not claim contact after a caller moves one.
    if (_canonical([item.to_dict() for item in project.modules])
            != _canonical([item.to_dict() for item in expected.modules])
            or _canonical([item.to_dict() for item in project.instances])
            != _canonical([item.to_dict() for item in expected.instances])):
        raise GeometryRefusal("example_scope_mismatch", "tower geometry or its declared recipe differs from the supported concept")
    pin = recipe_pin()
    bundle = capture_body(build_podium_body(dict(DEFAULTS)), project_id=project.project_id,
                          instance_key=PODIUM_INSTANCE, output_key=PODIUM_OUTPUT,
                          recipe=pin, parameters=DEFAULTS, linear_deflection_mm=40.)
    output = NamedOutput(PODIUM_OUTPUT, {"op": "create_directshape", "category": "mass",
                                        "name": "Curved podium with an inter-tower atrium"},
                         BodyRepresentation(bundle.digest, bundle.body_digest))
    instance = ModuleInstance(PODIUM_INSTANCE, PODIUM_MODULE, [output], DEFAULTS,
                              metadata={"bim_semantics": "absent", "native_execution": "not_run",
                                        "tower_contact": "z0_only_not_native_joined"})
    proposal = project.revise(expected_revision=project.revision_id,
                              modules=[*project.modules, ModuleDefinition(PODIUM_MODULE, "sealed_evaluation", pin)],
                              instances=[*project.instances, instance])
    return proposal, bundle


def workflow() -> tuple[tuple[ProjectRevision, ...], GeometryBundle]:
    root = towers.concept()
    upgraded = root.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=root.revision_id)
    podium, bundle = add_podium(upgraded)
    refined = towers.develop_section(podium)
    changed = towers.develop_section(ProjectRevision.loads(refined.dumps()),
                                    height_mm=4200., setback_mm=1800.)
    return (root, upgraded, podium, refined, changed), bundle


def create_store(path: str | Path, *, stage: str = "changed") -> ProjectStore:
    """Create a NEW file only. Build first; later I/O failure may leave a prefix."""
    if stage not in STAGES:
        raise ValueError("unknown example stage")
    revisions, bundle = workflow()  # no file exists yet if geometry/recipe fails
    store = ProjectStore.create(path, revisions[0])
    if stage != "root":
        store.upgrade_schema("kir-project-store/2", expected_revision=revisions[0].revision_id)
    for index, revision in enumerate(revisions[1:STAGES.index(stage) + 1], 1):
        store.commit(revision, expected_revision=revision.parent_revision,
                     assets=[bundle] if index == 2 else [])
    return store


def continue_section(store: ProjectStore, *, expected_revision: str,
                     height_mm: float = 4200., setback_mm: float = 1800.) -> ProjectRevision:
    """Explicit generator call + expected-head commit; no session/global state."""
    previous = store.head()
    if previous.revision_id != expected_revision:
        raise StoreConflict("section edit requires the current expected revision")
    # Existing generator checks its stored source/environment pin before running.
    # The untouched podium is NOT rebuilt or repinned to this process's source.
    proposal = towers.develop_section(previous, height_mm=height_mm, setback_mm=setback_mm)
    store.commit(proposal, expected_revision=expected_revision)
    return proposal


def materialize_saved(store: ProjectStore) -> GeometryMaterialization:
    project = store.head()
    bundles = {output.geometry.bundle_sha256: store.get_asset(output.geometry.bundle_sha256)
               for _, output, _ in project.geometry_references()}
    return materialize_project(project, bundles)


def publication_report(result: GeometryMaterialization) -> dict:
    """Decode the scene actually produced; code generation is not live execution."""
    from kir import compile_program
    from kir.viewer.codec import SCENE_MAGIC
    from kir.viewer.live_scene import scene_from_programs

    blob, meta = scene_from_programs([result.to_program()], origin_mm=(0., 0., 0.))
    length = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
    start = len(SCENE_MAGIC) + 4
    header = json.loads(blob[start:start + length])
    body = start + length
    ids = next(item for item in header["buffers"] if item["name"] == "ids")
    visible = blob[body + ids["offset"]:body + ids["offset"] + ids["length"]].decode().splitlines()
    compilation = []
    for version in ("2023", "2026"):
        compiled = compile_program(result.planned, revit_version=version)
        compilation.append({"revit_version": version, "ok": compiled.ok,
                            "stage": "kir_validation_and_codegen", "live_execution": "not_run",
                            "diagnostics": [{"code": d.code, "message": d.message_ru}
                                            for d in compiled.diagnostics]})
    return {"project_revision_id": result.project.revision_id, "plan_digest": result.planned.plan_digest,
            "scene": {"elements": header["elements"], "counts": header["counts"],
                      "visible_ids": visible, "mesh_shown": meta["mesh_shown"],
                      "source": meta["source"], "assertion": meta["assertion"]},
            "compilation": compilation, "scope": "authored_and_materialized_not_observed",
            "limitations": ["section_is_schematic_redesign_with_twist_and_taper_loss",
                            "podium_is_triangle_fallback_not_native_BIM",
                            "no_native_join_no_MEP_no_readback", "mesh_error_bound_not_measured"]}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=STAGES, default="changed")
    parser.add_argument("--store", metavar="NEW_DATABASE", help="exclusively create the complete history up to this stage")
    args = parser.parse_args(argv)
    try:
        if args.store is not None:
            store = create_store(args.store, stage=args.stage)
            result = materialize_saved(store)
            revisions = store.history()
        else:
            revisions, bundle = workflow()
            revisions = revisions[:STAGES.index(args.stage) + 1]
            result = materialize_project(revisions[-1], {bundle.digest: bundle})
        print(json.dumps({"schema": "kir-residential-podium-example/1", "project": result.project.to_dict(),
                          "history": [{"stage": stage, "schema": revision.schema,
                                       "revision_id": revision.revision_id, "parent_revision": revision.parent_revision}
                                      for stage, revision in zip(STAGES, revisions)],
                          "geometry_assets": [{"bundle_sha256": output.geometry.bundle_sha256,
                                               "body_sha256": output.geometry.body_sha256}
                                              for _, output, _ in result.project.geometry_references()],
                          "asset_durability": "sqlite_store" if args.store else "in_memory_only_not_saved",
                          "store": str(Path(args.store).absolute()) if args.store else None,
                          "publication": publication_report(result)}, ensure_ascii=False))
        return 0
    except (GeometryRefusal, ProjectStoreError, ValueError) as exc:
        parser.exit(2, f"example not completed: {exc}\n"
                    "If storage began, a saved prefix may remain; inspect its head before continuing.\n")


if __name__ == "__main__":
    raise SystemExit(main())
