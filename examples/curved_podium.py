"""Optional standalone CAD example: smooth podium -> atrium -> resumed edit.

Install the geometry extra with pip install -e '.[geometry]' first.
    python examples/curved_podium.py --stage changed

Stdout is one self-contained artifact containing ProjectRevision and BRep/mesh
bundle. No files are overwritten; no recipe is run when these JSON values load.
The explicitly called Python recipe uses OCCT itself, not a new KIR CAD DSL.
The project's operation is a triangle fallback, NOT native BIM or an exact Revit
solid. The bundle separately retains the BRep used to derive that fallback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform

from kir.occt_geometry import (GeometryBundle, GeometryRefusal, IDENTITY_FRAME, OCP_VERSION,
                              capture_body)
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, RecipePin, _canonical


PROJECT_ID = "curved-podium-spike"
MODULE_KEY = "smooth-podium"
DEFAULTS = {"height_mm": 12000., "bulge_mm": 2000., "atrium_radius_mm": 3000.}


def recipe_pin() -> RecipePin:
    from kir import occt_geometry

    source = Path(__file__).read_text(encoding="utf-8")
    adapter_digest = hashlib.sha256(Path(occt_geometry.__file__).read_bytes()).hexdigest()
    dependencies = {"kir.occt_geometry": adapter_digest}
    declared_environment = {"python": platform.python_version(), "ocp_package": OCP_VERSION,
                            "dependencies": dependencies}
    environment_digest = hashlib.sha256(json.dumps(
        declared_environment, sort_keys=True).encode("utf-8")).hexdigest()
    return RecipePin(source, environment_digest, entrypoint="build_body", dependencies=dependencies)


def build_body(parameters: dict):
    """Real smooth OCCT loft and Boolean cut; no own interpolation or healing."""
    try:
        valid = isinstance(parameters, dict) and set(parameters) == set(DEFAULTS) and all(
            type(v) in (int, float) and math.isfinite(v) for v in parameters.values())
    except OverflowError:
        valid = False
    if not valid:
        raise GeometryRefusal("invalid_recipe_parameters", "expected finite height, bulge and atrium radius")
    height, bulge, radius = (parameters[k] for k in DEFAULTS)
    if not (3000 <= height <= 30000 and 0 <= bulge <= 4000 and 1000 <= radius <= 5000):
        raise GeometryRefusal("unsupported_recipe_range", "podium spike parameter range exceeded")

    try:
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
        from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
        from OCP.gp import gp_Pnt, gp_Ax2, gp_Dir
    except ImportError as exc:
        raise GeometryRefusal("kernel_unavailable", "install kir-building[geometry]") from exc

    try:
        loft = BRepOffsetAPI_ThruSections(True, False, 0.01)
        # Compatibility is an explicit part of this recipe, not a hidden
        # universal seam/twist policy. This example has corresponding rectangles.
        loft.CheckCompatibility(True)
        loft.SetMutableInput(False)
        for fraction, bulge_fraction, center_x in (
                (0., 0., 0.), (.25, .5, 500.), (.5, 1., 1000.),
                (.75, .5, 500.), (1., 0., 0.)):
            half_width = 12000. + bulge * bulge_fraction
            polygon = BRepBuilderAPI_MakePolygon()
            for x, y in ((-half_width, -8000.), (half_width, -8000.),
                         (half_width, 8000.), (-half_width, 8000.)):
                polygon.Add(gp_Pnt(x + center_x, y, fraction * height))
            polygon.Close()
            if not polygon.IsDone():
                raise GeometryRefusal("kernel_build_failed", "section wire construction failed")
            loft.AddWire(polygon.Wire())
        loft.Build()
        if not loft.IsDone():
            raise GeometryRefusal("kernel_build_failed", "smooth loft did not finish")
        opening = BRepPrimAPI_MakeCylinder(
            gp_Ax2(gp_Pnt(0, 0, -1000), gp_Dir(0, 0, 1)), radius, height + 2000).Shape()
        cut = BRepAlgoAPI_Cut()
        # Use the existing kernel, in non-destructive mode. Inputs are not
        # perturbed or healed to make the Boolean succeed.
        from OCP.TopTools import TopTools_ListOfShape
        arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
        arguments.Append(loft.Shape())
        tools.Append(opening)
        cut.SetArguments(arguments)
        cut.SetTools(tools)
        cut.SetNonDestructive(True)
        cut.Build()
        if not cut.IsDone():
            raise GeometryRefusal("kernel_build_failed", "atrium Boolean did not finish")
        return cut.Shape()
    except GeometryRefusal:
        raise
    except Exception as exc:
        raise GeometryRefusal("kernel_build_failed", str(exc)) from exc


def evaluate(parameters: dict, *, source_lineage=(), frame=IDENTITY_FRAME) -> GeometryBundle:
    return capture_body(build_body(parameters), project_id=PROJECT_ID,
                        instance_key="podium", output_key="volume", recipe=recipe_pin(),
                        parameters=parameters, source_lineage=source_lineage, frame=frame,
                        linear_deflection_mm=20., max_vertices=4096, max_triangles=4096)


def _instance(bundle: GeometryBundle):
    op = bundle.fallback_op(name="Curved podium with atrium", category="mass")
    op.pop("id")  # ProjectRevision owns the same deterministic named output ID.
    return ModuleInstance("podium", MODULE_KEY, {"volume": op},
                          bundle.to_dict()["manifest"]["parameters"], metadata={
                              "geometry_bundle_sha256": bundle.digest,
                              "representation": "derived_triangle_fallback",
                              "bim_semantics": "absent", "native_execution": "not_run"})


def initial() -> tuple[ProjectRevision, GeometryBundle]:
    bundle = evaluate(dict(DEFAULTS))
    project = ProjectRevision(PROJECT_ID,
        [ModuleDefinition(MODULE_KEY, "sealed_evaluation", recipe_pin())],
        [_instance(bundle)], intent="Smooth podium with a retained exact-representation source",
        metadata={"scope": "geometry spike", "bim_design": "not_provided"})
    return project, bundle


def change(project: ProjectRevision, bundle: GeometryBundle, **changes):
    previous = next((item for item in project.instances if item.key == "podium"), None)
    definition = next((item for item in project.modules if item.key == MODULE_KEY), None)
    manifest = bundle.to_dict()["manifest"]
    expected = bundle.fallback_op(name="Curved podium with atrium", category="mass")
    expected.pop("id")
    if (project.project_id != PROJECT_ID or previous is None or definition is None
            or previous.module_key != MODULE_KEY
            or previous.metadata.get("geometry_bundle_sha256") != bundle.digest
            or manifest["binding"] != {"project_id": PROJECT_ID, "instance_key": "podium",
                                       "output_key": "volume", "op_id": bundle.op_id}
            or _canonical(previous.parameters) != _canonical(manifest["parameters"])
            or len(previous.outputs) != 1 or previous.outputs[0].key != "volume"
            or _canonical(previous.outputs[0].operation) != _canonical(expected)):
        raise GeometryRefusal("source_binding_mismatch", "project and body bundle do not match")
    current_recipe = recipe_pin()
    if definition.recipe != current_recipe or manifest["recipe"] != current_recipe.to_dict():
        raise GeometryRefusal("recipe_changed", "explicit recipe migration required before regeneration")
    parameters = dict(previous.parameters)
    parameters.update(changes)
    updated_bundle = evaluate(parameters, source_lineage=(bundle.digest,), frame=manifest["frame"])
    updated_project = project.replace_instance(_instance(updated_bundle), expected_revision=project.revision_id)
    return updated_project, updated_bundle


def workflow():
    first = initial()
    resumed = ProjectRevision.loads(first[0].dumps()), GeometryBundle.loads(first[1].dumps())
    return first, change(*resumed, bulge_mm=2500., atrium_radius_mm=3500.)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("initial", "changed"), default="changed")
    args = parser.parse_args(argv)
    try:
        first, changed = workflow()
        project, bundle = first if args.stage == "initial" else changed
        project.plan()
        print(json.dumps({"schema": "kir-curved-podium-example/1", "project": project.to_dict(),
                          "geometry_bundle": bundle.to_dict()}, ensure_ascii=False))
        return 0
    except GeometryRefusal as exc:
        import sys
        print(json.dumps({"error": exc.code, "message": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
